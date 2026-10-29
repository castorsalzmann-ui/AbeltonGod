"""Fake Claude Code CLI for the SDK client tests (CI only; no process, no network).

``FakeCLI`` is a ``claude_agent_sdk.Transport``. It speaks the CLI side of the stream-json
control protocol, so the **real** SDK code runs on top of it: ``ClaudeSDKClient``, ``Query``
(hook dispatch, ``mcp_message`` routing) and the in-process MCP server built by
``create_sdk_mcp_server`` (handshake, ``tools/list``, ``tools/call`` with the SDK's own schema
check). Only the CLI and the model are scripted.

The CLI behaviour emulated here follows the research note
``docs/research/2026-10-28_agent-sdk-behaviour.md`` and the SDK 0.2.174 source; it is **not**
a recording of the real CLI (none exists yet, #83). In particular: PreToolUse hooks run before
the tool, a deny becomes an error tool result with the reason, an allow's ``updatedInput``
replaces the arguments, and a tool name without the ``mcp__<server>__`` prefix is a built-in
that "executes" here (logged as ``builtin_executed``: in a real CLI that would be Bash etc.).
Interrupt and close take effect after ``LAG_S``, so what the fake already received is still
acted on (a real CLI is a separate process).

Script (a dict)::

    {"account": {...} | None,              # initialize response "account" (default {})
     "api_key_source": "none",             # init message apiKeySource
     "init_tools": [...] | None,           # default: the MCP tools the server lists
     "skip_init": False,                   # True: no init message at all
     "turns": [
        {"hang": True},                     # never answers (timeout tests)
        {"eof": True},                      # output stream ends, no result
        {"text": "...", "id": "msg_1", "split": False,
         "tool_uses": [{"id": "t1", "name": "mcp__abeltongod__echo", "input": {...},
                        "agent_id": None, "skip_hooks": False}]},
        {"text": "final answer"},           # no tool_uses -> success result
        {"result": {"subtype": "error_max_turns", "is_error": True, ...},
         "then_exit": False},               # True: the read stream fails like a CLI exit
        {"assistant_error": "rate_limit"},
        {"rate_limit": "rejected"},
        {"raw": {...}},                     # any frame, sent as is
     ],
     "total_cost_usd": 0.12}
"""

from __future__ import annotations

import asyncio
import copy
import itertools
import json
import re
from typing import Any

from claude_agent_sdk import ProcessError, Transport

SERVER = "abeltongod"
PREFIX = f"mcp__{SERVER}__"
# Delay before an interrupt or a close stops the fake. Long enough for the fake to act on
# every message it already has (a few event-loop steps), so a client that answers a waiting
# hook on shutdown is seen making the extra model call (mutant S31).
LAG_S = 0.03


class FakeCLI(Transport):
    def __init__(self, script: dict[str, Any], options: Any = None) -> None:
        self.script = copy.deepcopy(script)
        self.options = options
        self.out: asyncio.Queue = asyncio.Queue()
        self.pending: dict[str, asyncio.Future] = {}
        self.ids = itertools.count(1)
        self.hook_matchers: list[tuple[str | None, list[str]]] = []
        self.log: list[tuple] = []
        self.model_calls = 0
        self.closed = False
        self.task: asyncio.Task | None = None
        self.prompts: list[str] = []

    # ----- Transport --------------------------------------------------------------------------

    async def connect(self) -> None:
        return None

    def is_ready(self) -> bool:
        return not self.closed

    async def end_input(self) -> None:
        return None

    async def close(self) -> None:
        self.closed = True
        # A real CLI keeps running for a moment after stdin closes (the SDK waits up to 5 s);
        # anything it already received can still lead to a model call in that window.
        await asyncio.sleep(LAG_S)
        if self.task is not None and not self.task.done():
            self.task.cancel()
        for fut in self.pending.values():
            if not fut.done():
                fut.cancel()
        await self.out.put(None)

    async def write(self, data: str) -> None:
        for line in data.splitlines():
            if line.strip():
                self._on_input(json.loads(line))

    def read_messages(self):
        return self._reader()

    async def _reader(self):
        while True:
            item = await self.out.get()
            if item is None:
                return
            if isinstance(item, BaseException):
                raise item
            yield item

    # ----- CLI side ---------------------------------------------------------------------------

    def _on_input(self, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        if kind == "control_request":
            req = msg["request"]
            response: dict[str, Any] = {}
            if req.get("subtype") == "initialize":
                for matcher in (req.get("hooks") or {}).get("PreToolUse", []):
                    self.hook_matchers.append((matcher.get("matcher"),
                                               list(matcher["hookCallbackIds"])))
                response = {"commands": [], "account": self.script.get("account", {})}
            elif req.get("subtype") == "interrupt" and self.task is not None:
                # Not instantaneous: what the CLI already received (e.g. a hook answer) is
                # still acted on before the turn ends.
                asyncio.get_running_loop().call_later(LAG_S, self.task.cancel)
            self.log.append(("control", req.get("subtype")))
            self.out.put_nowait({"type": "control_response", "response": {
                "subtype": "success", "request_id": msg["request_id"], "response": response}})
        elif kind == "control_response":
            resp = msg["response"]
            fut = self.pending.pop(resp["request_id"], None)
            if fut is not None and not fut.done():
                fut.set_result(resp)
        elif kind == "user":
            self.prompts.append(msg["message"]["content"])
            self.task = asyncio.ensure_future(self._run())

    async def _control(self, request: dict[str, Any]) -> dict[str, Any]:
        rid = f"cli_{next(self.ids)}"
        fut = asyncio.get_running_loop().create_future()
        self.pending[rid] = fut
        await self.out.put({"type": "control_request", "request_id": rid, "request": request})
        resp = await fut
        if resp.get("subtype") == "error":
            raise RuntimeError(resp.get("error"))
        return resp.get("response", {})

    async def _mcp(self, method: str, params: dict[str, Any] | None, *, notify=False):
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if not notify:
            message["id"] = next(self.ids)
        resp = await self._control(
            {"subtype": "mcp_message", "server_name": SERVER, "message": message})
        return resp.get("mcp_response", {})

    def _has_server(self) -> bool:
        servers = getattr(self.options, "mcp_servers", None) or {}
        return isinstance(servers, dict) and SERVER in servers

    async def _run(self) -> None:
        try:
            await self._run_script()
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001 - surfaces as a reader failure
            self.log.append(("fake_cli_error", repr(exc)))
            await self.out.put(exc)

    async def _run_script(self) -> None:
        tools: list[str] = []
        if self._has_server():
            await self._mcp("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                           "clientInfo": {"name": "fake-cli", "version": "0"}})
            await self._mcp("notifications/initialized", None, notify=True)
            listed = await self._mcp("tools/list", {})
            tools = [PREFIX + t["name"] for t in listed["result"]["tools"]]
            self.log.append(("tools_listed", tuple(tools), listed["result"]["tools"]))
        init_tools = self.script.get("init_tools")
        if not self.script.get("skip_init"):
            await self._put_init(tools, init_tools)
        await self._run_turns()

    async def _put_init(self, tools: list[str], init_tools: list[str] | None) -> None:
        await self.out.put({
            "type": "system", "subtype": "init", "uuid": "u-init", "session_id": "s1",
            "apiKeySource": self.script.get("api_key_source", "none"),
            "tools": tools if init_tools is None else init_tools,
            "mcp_servers": [], "model": "claude-opus-5-5", "cwd": ".",
            "permissionMode": "dontAsk", "slash_commands": [], "output_style": "default",
            "skills": [], "claude_code_version": "fake",
        })

    async def _run_turns(self) -> None:
        for n, turn in enumerate(self.script["turns"], start=1):
            if turn.get("hang"):
                await asyncio.Event().wait()
            if turn.get("eof"):
                await self.out.put(None)
                return
            if "raw" in turn:
                await self.out.put(turn["raw"])
                continue
            if "rate_limit" in turn:
                await self.out.put({"type": "rate_limit_event", "uuid": f"r{n}",
                                    "session_id": "s1",
                                    "rate_limit_info": {"status": turn["rate_limit"]}})
                continue
            if "result" in turn:
                await self.out.put(self._result(turn["result"]))
                if turn.get("then_exit"):
                    await asyncio.sleep(0.01)
                    await self.out.put(ProcessError("Command failed", exit_code=1))
                return
            self.model_calls += 1
            self.log.append(("model_call", self.model_calls))
            mid = turn.get("id", f"msg_{n}")
            if "assistant_error" in turn:
                await self.out.put(self._assistant(mid, [{"type": "text", "text": ""}],
                                                   error=turn["assistant_error"]))
                continue
            blocks: list[dict[str, Any]] = []
            if turn.get("text"):
                blocks.append({"type": "text", "text": turn["text"]})
            for use in turn.get("tool_uses", []):
                if use.get("agent_id"):
                    continue  # a sub-agent's call is not part of the main answer
                blocks.append({"type": "tool_use", "id": use["id"], "name": use["name"],
                               "input": use["input"]})
            if turn.get("split"):
                for block in blocks:
                    await self.out.put(self._assistant(mid, [block]))
            else:
                await self.out.put(self._assistant(mid, blocks))
            uses = turn.get("tool_uses", [])
            if not uses:
                await self.out.put(self._result({"subtype": "success", "is_error": False,
                                                 "result": turn.get("text", "")}))
                return
            for use in uses:
                content, is_error = await self._run_tool(use)
                await self.out.put({"type": "user", "session_id": "s1", "message": {
                    "role": "user", "content": [{"type": "tool_result", "tool_use_id": use["id"],
                                                 "content": content, "is_error": is_error}]}})
        await self.out.put(self._result({"subtype": "error_during_execution", "is_error": True,
                                         "errors": ["fake script exhausted"]}))

    async def _run_tool(self, use: dict[str, Any]) -> tuple[str, bool]:
        name, args = use["name"], copy.deepcopy(use["input"])
        if not use.get("skip_hooks"):
            for matcher, callback_ids in self.hook_matchers:
                if matcher and not re.fullmatch(matcher, name):
                    continue
                for cid in callback_ids:
                    hook_input = {"hook_event_name": "PreToolUse", "tool_name": name,
                                  "tool_input": copy.deepcopy(args), "tool_use_id": use["id"],
                                  "session_id": "s1", "cwd": ".", "transcript_path": "",
                                  "permission_mode": "dontAsk"}
                    if use.get("agent_id"):
                        hook_input["agent_id"] = use["agent_id"]
                        hook_input["agent_type"] = "general-purpose"
                    out = await self._control({"subtype": "hook_callback", "callback_id": cid,
                                               "input": hook_input, "tool_use_id": use["id"]})
                    spec = out.get("hookSpecificOutput") or {}
                    decision = spec.get("permissionDecision")
                    self.log.append(("hook", name, decision, use["id"]))
                    if out.get("continue") is False:
                        self.log.append(("hook_stop", name))
                    if decision == "deny":
                        return spec.get("permissionDecisionReason", "denied"), True
                    if "updatedInput" in spec:
                        args = copy.deepcopy(spec["updatedInput"])
        if name.startswith(PREFIX):
            resp = await self._mcp("tools/call", {"name": name[len(PREFIX):], "arguments": args})
            result = resp.get("result", {})
            text = "".join(c.get("text", "") for c in result.get("content", []))
            is_error = bool(result.get("isError"))
            self.log.append(("mcp_call", name, copy.deepcopy(args), is_error, text))
            return text, is_error
        self.log.append(("builtin_executed", name, copy.deepcopy(args)))
        return "ok", False

    def _assistant(self, mid: str, content: list[dict[str, Any]], error: str | None = None):
        msg: dict[str, Any] = {"type": "assistant", "session_id": "s1", "parent_tool_use_id": None,
                               "message": {"id": mid, "model": "claude-opus-5-5",
                                           "content": content, "usage": {"output_tokens": 1}}}
        if error:
            msg["error"] = error
        return msg

    def _result(self, fields: dict[str, Any]) -> dict[str, Any]:
        base = {"type": "result", "subtype": "success", "is_error": False, "duration_ms": 1,
                "duration_api_ms": 1, "num_turns": self.model_calls, "session_id": "s1",
                "total_cost_usd": self.script.get("total_cost_usd"), "usage": {}}
        base.update(fields)
        return base

    # ----- what the tests check ---------------------------------------------------------------

    def events(self, kind: str) -> list[tuple]:
        return [e for e in self.log if e[0] == kind]


class FakeCLIFactory:
    """``transport_factory`` for ``SdkModelClient``: one FakeCLI per session, all kept."""

    def __init__(self, *scripts: dict[str, Any]) -> None:
        self.scripts = list(scripts)
        self.made: list[FakeCLI] = []
        self.options: list[Any] = []

    def __call__(self, options: Any) -> FakeCLI:
        script = self.scripts[min(len(self.made), len(self.scripts) - 1)]
        cli = FakeCLI(script, options)
        self.made.append(cli)
        self.options.append(options)
        return cli

    @property
    def cli(self) -> FakeCLI:
        return self.made[-1]
