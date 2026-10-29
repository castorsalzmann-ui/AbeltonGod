"""Claude Agent SDK model client (Phase 04b step 2a, #106; D-002, D-011, D-014, D-020).

``SdkModelClient`` implements ``ModelClient`` on top of ``claude_agent_sdk.ClaudeSDKClient``
and keeps the interface's promise: **one** ``complete`` call is **one** model call, and every
tool runs in the orchestrator loop through ``Toolbox.run`` (and so through the guard).

How the SDK's own agent loop is held to that (one SDK session per user request):

1. The first ``complete`` of a request opens a session with a **closed tool surface**
   (``tools=[]``, ``strict_mcp_config``, ``setting_sources=[]``, ``permission_mode="dontAsk"``,
   tool search off) and the limits from the guard permit (``max_turns`` >= 1, never 0, and
   ``max_budget_usd`` > 0, via ``checked_sdk_limits``). It sends the user text and reads the
   stream until the model asks for a tool or the run ends.
2. Every tool call the CLI wants to run first hits **one catch-all PreToolUse hook** (no
   matcher, so built-ins and sub-agent tools are covered too). The hook does not decide by
   itself: it hands the call to the loop (``complete`` returns it as a ``ToolCall``) and waits.
3. The loop runs the call through ``Toolbox.run`` (guard first, schema check, approval,
   handler). The next ``complete`` - which the loop only makes after ``before_model_call`` -
   brings the results back. Only then does the hook answer: an error result becomes a
   **deny** whose reason is the error the model reads; a success becomes an **allow** with
   the validated arguments, and the in-process MCP tool (a relay, not the tool) returns the
   stored result. So the CLI can only start its next model call *after* the guard permitted
   it.
4. The relay never sees a ``Tool`` handler (it is built from ``ToolSpec`` only), so it cannot
   run local code. A relay call without a matching guard-approved result returns an error and
   marks the session as violated; a hook allow is only possible for a name with this
   server's prefix, never for a built-in or a sub-agent tool.

Fail-closed checks (each ends the request with a clear error, never a success):

- the credential source the CLI reports (``account`` in the initialize response, before the
  prompt is sent; then ``apiKeySource`` in the init message) must match the D-014 switch;
- the init message must list no tool outside this server, and must come before any answer;
- a second model call inside one ``complete`` (one the guard did not permit), a sub-agent
  model call, a relay call without approval and a stream that ends without a result are
  protocol errors;
- ``error_max_turns`` / ``error_max_budget_usd`` results (or the ``ResultError`` the SDK
  raises for them) become ``ModelLimitReached`` with the usage still reported; the loop turns
  them into a guard stop.

What is **not verified** (research note ``2026-10-28_agent-sdk-behaviour.md``, #83): that the
hook fires before the SDK's own schema check (V4/V9), that ``updatedInput`` reaches the tool
(V9), the init ``tools`` list with this configuration (V6), the ``apiKeySource`` values on the
user's machine (V7), the turn definition behind ``max_turns`` (V1), and the ``account`` field
of the initialize response (read from the bundled CLI 2.1.310, not documented).

Cost: the SDK reports cost only at the end (``total_cost_usd``, an API-equivalent estimate
under the subscription). Intermediate turns report no usage, so the guard counts each call's
reservation; the final turn reports ``total - already counted`` (never below 0), so the
guard's total is at least the SDK's. ``estimate_cost_usd`` gives the loop a per-call
reservation (profile budget / profile model calls) instead of "all money left".
Output tokens are only known when the run was a single model call; otherwise the guard counts
each call at its cap, so a multi-turn request reaches the guard's warn level after its first
tool turn (known limit, not a measured value).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import copy
import json
import math
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from claude_agent_sdk import (
    AssistantMessage as SdkAssistantMessage,
)
from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    CLIConnectionError,
    CLIJSONDecodeError,
    CLINotFoundError,
    HookMatcher,
    ProcessError,
    RateLimitEvent,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
    tool,
)
from claude_agent_sdk import (
    ResultError as SdkResultError,
)
from claude_agent_sdk._errors import MessageParseError  # not re-exported by the package

from guard import ModelUsage
from orchestrator.auth import (
    AuthConfigError,
    AuthMode,
    AuthSettings,
    check_api_key_source,
    merged_environment,
)
from orchestrator.loop import checked_sdk_limits
from orchestrator.model_client import (
    ModelLimitReached,
    ModelProtocolError,
    ModelRequest,
    ModelResponse,
    ModelUnavailable,
    ToolCall,
    ToolResult,
    ToolResultMessage,
    UserMessage,
)

SERVER_NAME = "abeltongod"
TOOL_PREFIX = f"mcp__{SERVER_NAME}__"
# Names the loop gets for calls that are not ours. The colon can never be part of a Tool name
# (tools.TOOL_NAME), so these always end as "unknown_tool" in Toolbox.run - counted by the
# guard, denied by the hook.
BUILTIN_PREFIX = "builtin:"
SUBAGENT_PREFIX = "subagent:"
LIMIT_SUBTYPES = ("error_max_turns", "error_max_budget_usd")
# Second layer behind tools=[] (research note Q5). Not "mcp__*": that would remove ours too.
DISALLOWED_TOOLS = (
    "Agent", "Task", "Bash", "Read", "Write", "Edit", "Glob", "Grep",
    "WebFetch", "WebSearch", "ToolSearch", "Skill", "NotebookEdit", "TodoWrite",
)
# How long the first hook of a turn waits for the assistant message that carries its
# tool_use block, so all calls of one model answer reach the loop together.
BLOCK_WAIT_S = 0.5
# Extra seconds the hook (and the sync wrapper) wait beyond the request timeout.
GRACE_S = 5.0

TransportFactory = Callable[[ClaudeAgentOptions], Any]


def per_call_estimate(profile: Any) -> float:
    """Reservation per model call: the profile's request budget spread over its model calls.
    A placeholder until #83 (V3) measures real per-call cost."""
    return float(profile.max_budget_usd) / max(1, int(profile.max_model_calls))


def _json_numbers(value: Any) -> Any:
    """1.0 and 1 are the same JSON number; the CLI (JavaScript) writes both as ``1``."""
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    if isinstance(value, Mapping):
        return {k: _json_numbers(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_json_numbers(v) for v in value]
    return value


def _canon(value: Any) -> str:
    """Key for "the same arguments" across the CLI round trip (updatedInput -> tool call)."""
    return json.dumps(_json_numbers(value), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def _loop_name(raw_name: Any, agent_id: Any) -> str:
    """Name under which the loop (and so the guard) sees a call the CLI wants to run."""
    name = raw_name if isinstance(raw_name, str) and raw_name else "<unnamed>"
    if agent_id:
        return f"{SUBAGENT_PREFIX}{name}"
    if name.startswith(TOOL_PREFIX) and len(name) > len(TOOL_PREFIX):
        return name[len(TOOL_PREFIX):]
    return f"{BUILTIN_PREFIX}{name}"


def _deny(reason: str, *, stop: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    if stop:  # effect on the result subtype not verified (V5); the session is closed anyway
        out["continue_"] = False
        out["stopReason"] = reason
    return out


def _allow(arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": copy.deepcopy(arguments),
        }
    }


def _text(content: Mapping[str, Any]) -> str:
    return json.dumps(content, ensure_ascii=False, sort_keys=True)


@dataclass
class _Hook:
    future: asyncio.Future
    raw_name: str
    loop_name: str
    arguments: Any
    agent_id: Any


@dataclass
class _Session:
    system: str
    allowed_names: frozenset[str]
    events: asyncio.Queue = field(default_factory=asyncio.Queue)
    client: Any = None
    reader: asyncio.Task | None = None
    init_checked: bool = False
    closed: bool = False
    violation: str | None = None
    seen_message_ids: set[str] = field(default_factory=set)
    current_message_id: str | None = None
    turn_text: list[str] = field(default_factory=list)
    blocks: dict[str, ToolCall] = field(default_factory=dict)  # tool_use_id -> call
    hooks: dict[str, _Hook] = field(default_factory=dict)
    returned: dict[str, ToolCall] = field(default_factory=dict)  # given to the loop
    results: dict[str, ToolResult] = field(default_factory=dict)  # from the loop
    approved: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    guard_note: str = ""
    counted_cost: float = 0.0
    cost_known: bool = True
    history_len: int = 0
    unapproved_relay_calls: int = 0
    stream_ended: bool = False  # the CLI's output ended: nobody would answer an interrupt


class SdkModelClient:
    """``ModelClient`` on the Claude Agent SDK. Thread-safe for one request at a time (the
    guard allows one concurrent request). Owns a private event loop in a daemon thread."""

    def __init__(
        self,
        settings: AuthSettings,
        *,
        per_call_estimate_usd: float | None = None,
        transport_factory: TransportFactory | None = None,
        environ: Mapping[str, str] | None = None,
        env_file: Any = None,
        cli_path: str | None = None,
    ) -> None:
        if not isinstance(settings, AuthSettings):
            raise TypeError("settings must be AuthSettings (from orchestrator.auth.load_auth)")
        self.settings = settings
        self._estimate = per_call_estimate_usd
        self._transport_factory = transport_factory
        self._environ = environ
        self._env_file = env_file
        self._cli_path = cli_path
        self._session: _Session | None = None
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, name="claude-agent-sdk", daemon=True
        )
        self._thread.start()
        self.last_options: ClaudeAgentOptions | None = None  # for tests and diagnostics

    # ----- ModelClient ----------------------------------------------------------------------

    def estimate_cost_usd(self, request: ModelRequest) -> float | None:
        return self._estimate

    def complete(self, request: ModelRequest) -> ModelResponse:
        wait = max(0.0, float(request.timeout_s)) + GRACE_S
        fut = asyncio.run_coroutine_threadsafe(self._complete(request), self._loop)
        try:
            return fut.result(timeout=wait)
        except concurrent.futures.TimeoutError:
            fut.cancel()
            self.end_request()
            raise ModelUnavailable(f"no answer from Claude within {wait:.0f} s") from None

    def end_request(self) -> None:
        """Close the open SDK session (if any). The loop calls this when a request ends, so a
        CLI waiting in the hook can never go on to an unpermitted model call."""
        if self._loop.is_closed():
            return
        fut = asyncio.run_coroutine_threadsafe(self._close_session(), self._loop)
        try:
            fut.result(timeout=30)
        except Exception:  # noqa: BLE001 - closing must never raise into the loop
            pass

    def close(self) -> None:
        self.end_request()
        if not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)

    # ----- session ---------------------------------------------------------------------------

    async def _complete(self, request: ModelRequest) -> ModelResponse:
        deadline = time.monotonic() + max(0.0, float(request.timeout_s))
        messages = request.messages
        try:
            if len(messages) == 1 and isinstance(messages[0], UserMessage):
                await self._close_session()
                sess = await self._open_session(request, deadline)
            else:
                sess = self._session
                if sess is None or sess.closed:
                    raise ModelUnavailable(
                        "no open Claude session for this request", request_sent=False
                    )
                self._deliver(sess, request)
            return await self._pump(sess, request, deadline)
        except BaseException:
            await self._close_session()
            raise

    def _options(self, request: ModelRequest, limits: dict[str, Any], sess: _Session):
        specs = list(request.tools)
        sdk_tools = [self._relay(spec.name, spec.description, spec.input_schema) for spec in specs]
        mcp_servers: dict[str, Any] = {}
        if sdk_tools:
            mcp_servers[SERVER_NAME] = create_sdk_mcp_server(SERVER_NAME, tools=sdk_tools)
        env = {
            "ENABLE_TOOL_SEARCH": "false",
            # Per-call output cap from the guard permit (Claude Code setting; not verified).
            "CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(int(request.max_output_tokens)),
        }
        if self.settings.mode is AuthMode.API_KEY:
            key = merged_environment(self._environ, self._env_file).get("ANTHROPIC_API_KEY", "")
            env["ANTHROPIC_API_KEY"] = key.strip()
        hook_timeout = max(1.0, float(request.timeout_s)) + GRACE_S
        return ClaudeAgentOptions(
            tools=[],
            allowed_tools=sorted(sess.allowed_names),
            disallowed_tools=list(DISALLOWED_TOOLS),
            mcp_servers=mcp_servers,
            strict_mcp_config=True,
            setting_sources=[],
            permission_mode="dontAsk",
            system_prompt=request.system,
            model=self.settings.model,
            max_turns=limits["max_turns"],
            max_budget_usd=float(limits["max_budget_usd"]),
            hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[self._pre_tool_use],
                                              timeout=hook_timeout)]},
            env=env,
            cli_path=self._cli_path,
            agents=None,
            plugins=[],
        )

    async def _open_session(self, request: ModelRequest, deadline: float) -> _Session:
        try:
            limits = checked_sdk_limits(request.sdk_limits)
        except Exception as exc:  # SdkLimitError: never start the SDK with "no limit"
            raise ModelUnavailable(f"refused to start Claude: {exc}", request_sent=False) from exc
        allowed = frozenset(TOOL_PREFIX + spec.name for spec in request.tools)
        sess = _Session(system=request.system, allowed_names=allowed)
        options = self._options(request, limits, sess)
        self.last_options = options
        transport = self._transport_factory(options) if self._transport_factory else None
        client = ClaudeSDKClient(options=options, transport=transport)
        sess.client = client
        self._session = sess
        try:
            await asyncio.wait_for(client.connect(), timeout=max(0.1, deadline - time.monotonic()))
        except CLINotFoundError as exc:
            raise ModelUnavailable(
                f"Claude Code CLI not found ({exc})", request_sent=False
            ) from exc
        except (CLIConnectionError, ProcessError, TimeoutError, OSError) as exc:
            raise ModelUnavailable(
                f"could not start Claude ({type(exc).__name__}: {exc})", request_sent=False
            ) from exc
        except Exception as exc:  # initialize refused, control timeout, ...
            raise ModelUnavailable(
                f"could not start Claude ({type(exc).__name__}: {exc})", request_sent=False
            ) from exc
        self._check_account(await client.get_server_info())
        sess.reader = asyncio.ensure_future(self._forward(sess, client))
        prompt = request.messages[0].text
        sess.history_len = 1
        try:
            await client.query(prompt)
        except Exception as exc:  # the prompt may be partly written: count it as sent
            raise ModelUnavailable(
                f"could not send the request to Claude ({type(exc).__name__}: {exc})"
            ) from exc
        return sess

    async def _forward(self, sess: _Session, client: Any) -> None:
        try:
            async for message in client.receive_messages():
                await sess.events.put(("msg", message))
            sess.stream_ended = True
            await sess.events.put(("end", None))
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001 - mapped in _pump
            sess.stream_ended = True
            await sess.events.put(("error", exc))

    async def _close_session(self) -> None:
        """End the session without ever answering a waiting hook: an answer (even a deny)
        lets the CLI go on to its next model call, which the guard did not permit (found by
        the CI tests of #106). Order: interrupt the turn, then disconnect (which cancels the
        waiting hook handlers without a reply, closes stdin and stops the process).

        Residual risk (not verified): if the interrupt fails, the SDK's close gives the CLI
        up to 5 s after stdin EOF before SIGTERM; what the CLI does with a hook that never
        gets an answer in that window is not documented (V4, #83)."""
        sess, self._session = self._session, None
        if sess is None or sess.closed:
            return
        sess.closed = True
        client = sess.client
        if client is not None:
            if not sess.stream_ended:
                try:
                    await asyncio.wait_for(client.interrupt(), timeout=3)
                except BaseException:  # noqa: BLE001 - best effort; disconnect still runs
                    pass
        if sess.reader is not None:
            sess.reader.cancel()
        if client is not None:
            try:
                await asyncio.wait_for(client.disconnect(), timeout=25)
            except BaseException:  # noqa: BLE001 - best effort
                pass
        for hook in sess.hooks.values():
            if not hook.future.done():
                hook.future.cancel()

    # ----- checks ----------------------------------------------------------------------------

    def _check_account(self, info: Any) -> None:
        """Early check before the prompt is sent: the initialize response's ``account`` (not
        documented; read from the bundled CLI). Refuses only on positive evidence."""
        account = info.get("account") if isinstance(info, Mapping) else None
        if not isinstance(account, Mapping):
            return
        source = account.get("apiKeySource")
        provider = account.get("apiProvider")
        if self.settings.mode is AuthMode.SUBSCRIPTION:
            if source:
                raise ModelUnavailable(
                    f"auth mode 'subscription', but Claude Code would use an API key "
                    f"(source {source!r}); remove it or set ABELTONGOD_CLAUDE_AUTH=api_key",
                    request_sent=False,
                )
            if provider not in (None, "firstParty"):
                raise ModelUnavailable(
                    f"auth mode 'subscription', but Claude Code uses provider {provider!r}",
                    request_sent=False,
                )
        elif source not in (None, "ANTHROPIC_API_KEY"):
            raise ModelUnavailable(
                f"auth mode 'api_key', but Claude Code reports key source {source!r}",
                request_sent=False,
            )

    def _check_init(self, sess: _Session, data: Mapping[str, Any]) -> None:
        try:
            check_api_key_source(self.settings.mode, data.get("apiKeySource"))
        except AuthConfigError as exc:
            raise ModelUnavailable(f"auth check failed: {exc}") from exc
        tools = data.get("tools")
        if not isinstance(tools, list) or not all(isinstance(t, str) for t in tools):
            raise ModelProtocolError("init message has no readable tools list")
        extra = sorted(t for t in tools if t not in sess.allowed_names)
        if extra:
            raise ModelProtocolError(
                "closed tool surface violated: Claude Code offers " + ", ".join(extra)
            )
        sess.init_checked = True

    # ----- results from the loop -------------------------------------------------------------

    def _deliver(self, sess: _Session, request: ModelRequest) -> None:
        last = request.messages[-1] if request.messages else None
        if not isinstance(last, ToolResultMessage) or len(request.messages) != (
            sess.history_len + 2
        ):
            raise ModelUnavailable(
                "the conversation does not continue the open Claude session", request_sent=False
            )
        sess.history_len = len(request.messages)
        note = ""
        if request.system != sess.system:
            extra = request.system[len(sess.system):] if request.system.startswith(
                sess.system) else request.system
            note = extra.strip()
        sess.guard_note = note
        sess.turn_text = []
        for result in last.results:
            if result.call_id not in sess.returned:
                raise ModelUnavailable(
                    f"result for unknown tool call {result.call_id!r}", request_sent=False
                )
            sess.results[result.call_id] = result
            hook = sess.hooks.get(result.call_id)
            if hook is not None and not hook.future.done():
                # The model call these results start is the one the guard just permitted.
                hook.future.set_result(result)

    def _decide(self, sess: _Session, tid: str, hook: _Hook, result: ToolResult | None):
        if result is None or sess.closed:
            return _deny("the request has ended; this tool call was not run", stop=True)
        note = f"\n{sess.guard_note}" if sess.guard_note else ""
        if result.is_error:
            return _deny(_text(result.content) + note)
        call = sess.returned.get(tid)
        if (
            hook.agent_id
            or not hook.raw_name.startswith(TOOL_PREFIX)
            or hook.raw_name not in sess.allowed_names
            or call is None
            or call.name != hook.loop_name
            or result.name != hook.loop_name
        ):
            return _deny(_text({"error": "not_permitted",
                                "message": "this tool is not available"}) + note)
        if _canon(hook.arguments) != _canon(call.arguments):
            return _deny(_text({"error": "not_permitted",
                                "message": "arguments changed after validation"}) + note)
        key = (hook.loop_name, _canon(call.arguments))
        sess.approved.setdefault(key, []).append(_text(result.content) + note)
        return _allow(call.arguments)

    # ----- hook and relay (run inside the SDK) -----------------------------------------------

    async def _pre_tool_use(self, input_data: Any, tool_use_id: Any, context: Any):
        """Catch-all PreToolUse hook. Never raises (a raising hook's effect is unverified,
        V4); every failure is a deny."""
        try:
            sess = self._session
            if sess is None or sess.closed:
                # Only a CLI that is being shut down asks now. Any answer would let it go on
                # to a model call; it waits until the shutdown cancels this handler.
                await asyncio.get_running_loop().create_future()
            data = input_data if isinstance(input_data, Mapping) else {}
            tid = tool_use_id if isinstance(tool_use_id, str) and tool_use_id else data.get(
                "tool_use_id")
            if not isinstance(tid, str) or not tid:
                return _deny("tool call without an id")
            raw = data.get("tool_name")
            hook = _Hook(
                future=asyncio.get_running_loop().create_future(),
                raw_name=raw if isinstance(raw, str) else "",
                loop_name=_loop_name(raw, data.get("agent_id")),
                arguments=copy.deepcopy(data.get("tool_input")),
                agent_id=data.get("agent_id"),
            )
            if tid in sess.hooks:
                return _deny("the same tool call was presented twice")
            sess.hooks[tid] = hook
            if tid in sess.results:
                return self._decide(sess, tid, hook, sess.results[tid])
            await sess.events.put(("hook", tid))
            result = await hook.future
            return self._decide(sess, tid, hook, result)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - fail closed
            return _deny("internal error in the resource guard hook", stop=True)

    def _relay(self, name: str, description: str, schema: dict[str, Any]):
        client = self

        async def relay(args: dict[str, Any]) -> dict[str, Any]:
            sess = client._session
            queue = sess.approved.get((name, _canon(args))) if sess is not None else None
            if not queue:
                if sess is not None:
                    sess.unapproved_relay_calls += 1
                    sess.violation = f"tool {name} was called without the guard's approval"
                return {
                    "content": [{"type": "text", "text": _text(
                        {"error": "not_permitted", "message": "not approved by the guard"})}],
                    "is_error": True,
                }
            return {"content": [{"type": "text", "text": queue.pop(0)}]}

        return tool(name, description, copy.deepcopy(schema))(relay)

    # ----- reading the stream ----------------------------------------------------------------

    async def _next_event(self, sess: _Session, deadline: float):
        left = deadline - time.monotonic()
        if left <= 0:
            raise ModelUnavailable("Claude did not answer within the request timeout")
        try:
            return await asyncio.wait_for(sess.events.get(), timeout=left)
        except TimeoutError:
            raise ModelUnavailable("Claude did not answer within the request timeout") from None

    async def _pump(self, sess: _Session, request: ModelRequest, deadline: float):
        new_ids: list[str] = []
        while True:
            if sess.violation:
                raise ModelProtocolError(sess.violation)
            kind, payload = await self._next_event(sess, deadline)
            if kind == "msg":
                result = self._on_message(sess, payload, new_ids, request)
                if result is not None:
                    await self._close_session()
                    return result
            elif kind == "hook":
                if payload in sess.returned:
                    continue  # its result is already on the way (or delivered)
                await self._collect_blocks(sess, payload, new_ids, request, deadline)
                return self._tool_turn(sess, request)
            elif kind == "error":
                raise self._map_exception(sess, payload, request)
            else:  # "end"
                raise ModelUnavailable("Claude Code ended the session without a result")

    async def _collect_blocks(self, sess, tid, new_ids, request, deadline) -> None:
        """Wait briefly for the assistant message that carries ``tid``'s tool_use block."""
        until = min(deadline, time.monotonic() + BLOCK_WAIT_S)
        while tid not in sess.blocks:
            left = until - time.monotonic()
            if left <= 0:
                return
            try:
                kind, payload = await asyncio.wait_for(sess.events.get(), timeout=left)
            except TimeoutError:
                return
            if kind == "msg":
                if self._on_message(sess, payload, new_ids, request) is not None:
                    raise ModelProtocolError("run ended while a tool call was pending")
            elif kind == "hook":
                continue  # handled with the others in _tool_turn
            elif kind == "error":
                raise self._map_exception(sess, payload, request)
            else:
                raise ModelUnavailable("Claude Code ended the session without a result")

    def _tool_turn(self, sess: _Session, request: ModelRequest) -> ModelResponse:
        calls: list[ToolCall] = []
        for tid, block_call in sess.blocks.items():
            if tid in sess.returned:
                continue
            hook = sess.hooks.get(tid)
            call = ToolCall(tid, hook.loop_name, copy.deepcopy(hook.arguments)) if hook else (
                block_call)
            calls.append(call)
        for tid, hook in sess.hooks.items():
            if tid not in sess.returned and tid not in sess.blocks:
                calls.append(ToolCall(tid, hook.loop_name, copy.deepcopy(hook.arguments)))
        for call in calls:
            sess.returned[call.id] = call
        if request.reserved_cost_usd is not None:
            sess.counted_cost += float(request.reserved_cost_usd)
        else:
            sess.cost_known = False
        text = "".join(sess.turn_text)
        return ModelResponse(text=text, tool_calls=tuple(calls), usage=None, stop_reason="tool_use")

    def _on_message(self, sess, message, new_ids, request) -> ModelResponse | None:
        if isinstance(message, SystemMessage):
            if message.subtype == "init":
                self._check_init(sess, message.data)
            return None
        if isinstance(message, RateLimitEvent):
            if getattr(message.rate_limit_info, "status", None) == "rejected":
                raise ModelUnavailable("the Claude usage limit is reached (rate limit rejected)")
            return None
        if isinstance(message, SdkAssistantMessage):
            if not sess.init_checked:
                raise ModelProtocolError("Claude answered before the session was checked")
            if message.parent_tool_use_id is not None:
                raise ModelProtocolError("a sub-agent made a model call")
            if message.error:
                raise ModelUnavailable(f"Claude reported an error: {message.error}")
            mid = message.message_id or f"<no id {id(message)}>"
            if mid not in sess.seen_message_ids:
                sess.seen_message_ids.add(mid)
                new_ids.append(mid)
                if len(new_ids) > 1:
                    raise ModelProtocolError(
                        "Claude Code made a model call the guard did not permit"
                    )
                sess.current_message_id = mid
                sess.turn_text = []
            for block in message.content:
                if isinstance(block, TextBlock):
                    sess.turn_text.append(block.text)
                elif isinstance(block, ToolUseBlock) and block.id not in sess.blocks:
                    sess.blocks[block.id] = ToolCall(
                        block.id, _loop_name(block.name, None), copy.deepcopy(block.input)
                    )
            return None
        if isinstance(message, ResultMessage):
            return self._on_result(sess, message)
        return None  # user echoes, stream events, task frames

    def _usage(self, sess: _Session, total: Any, tokens: Any = None) -> ModelUsage | None:
        """Usage for the call that ends the run. Token counts only when the whole session was
        this one model call (the result's ``usage`` is a session total; per-step usage on
        assistant messages is a placeholder, auth note row 17); otherwise None, so the guard
        counts the call at its cap."""
        out_tokens = in_tokens = None
        if len(sess.seen_message_ids) == 1 and isinstance(tokens, Mapping):
            out_tokens = tokens.get("output_tokens")
            in_tokens = tokens.get("input_tokens")
        if isinstance(total, bool) or not isinstance(total, int | float):
            if out_tokens is None:
                return None
            return ModelUsage(output_tokens=out_tokens, input_tokens=in_tokens)
        if not math.isfinite(total) or total < 0:
            return ModelUsage(cost_usd=total)  # unreadable -> the guard stops on it
        already = sess.counted_cost if sess.cost_known else 0.0
        return ModelUsage(
            output_tokens=out_tokens,
            input_tokens=in_tokens,
            cost_usd=max(0.0, float(total) - already),
        )

    def _on_result(self, sess: _Session, message: ResultMessage) -> ModelResponse:
        usage = self._usage(sess, message.total_cost_usd, message.usage)
        if message.subtype in LIMIT_SUBTYPES:
            raise ModelLimitReached(
                message.subtype, "; ".join(message.errors or []) or message.subtype, usage=usage
            )
        if message.is_error:
            detail = "; ".join(message.errors or []) or (message.result or message.subtype)
            raise ModelUnavailable(f"Claude ended with an error: {detail}", usage=usage)
        if sess.violation:
            raise ModelProtocolError(sess.violation)
        text = message.result if isinstance(message.result, str) else "".join(sess.turn_text)
        return ModelResponse(text=text, usage=usage, stop_reason=message.stop_reason)

    def _map_exception(self, sess: _Session, exc: BaseException, request) -> Exception:
        if isinstance(exc, SdkResultError):
            usage = self._usage(sess, exc.data.get("total_cost_usd"), exc.data.get("usage"))
            if exc.subtype in LIMIT_SUBTYPES:
                return ModelLimitReached(exc.subtype, str(exc), usage=usage)
            return ModelUnavailable(f"Claude ended with an error: {exc}", usage=usage)
        if isinstance(exc, MessageParseError | CLIJSONDecodeError):
            return ModelProtocolError(f"unreadable message from Claude Code: {exc}")
        if isinstance(exc, ProcessError | CLIConnectionError):
            return ModelUnavailable(f"Claude Code stopped: {exc}")
        if isinstance(exc, Exception):
            return ModelUnavailable(f"Claude Code failed: {type(exc).__name__}: {exc}")
        return ModelUnavailable(f"Claude Code failed: {type(exc).__name__}")


__all__ = [
    "BUILTIN_PREFIX",
    "DISALLOWED_TOOLS",
    "SERVER_NAME",
    "SUBAGENT_PREFIX",
    "TOOL_PREFIX",
    "SdkModelClient",
    "per_call_estimate",
]
