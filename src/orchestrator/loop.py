"""Orchestrator loop (Phase 04b step 1): user text -> model -> tool calls -> schema validation
-> local execution -> structured results -> model -> answer.

Every model call and every tool call happens inside one ``guard.request(profile)``:

- model: ``before_model_call`` -> ``ModelClient.complete`` -> ``after_model_call``
  (``_call_model`` is the only place that calls ``complete``);
- tools: ``Toolbox.run`` (``before_tool`` first, also for rejected calls).

Outcomes are never reported as successful unless ``GuardedRequest.finish`` returned a success
result. A guard stop, an unreachable model, a backend limit, a malformed answer, a declined or
failed tool all end as ``success=False`` with what was finished and what is still open.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from guard import (
    Guard,
    GuardedRequest,
    GuardStop,
    Level,
    Limit,
    ModelUsage,
    RequestResult,
    warning_message_de,
)
from orchestrator.model_client import (
    AssistantMessage,
    Message,
    ModelClient,
    ModelLimitReached,
    ModelProtocolError,
    ModelRequest,
    ModelResponse,
    ModelUnavailable,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from orchestrator.tools import Approver, Toolbox

DEFAULT_PROFILE = "kick_generation"
ANSWER_ITEM = "Antwort"

DEFAULT_SYSTEM_PROMPT = (
    "You are the AbeltonGod copilot for Ableton Live 12. You only choose tools and their "
    "parameters; local code generates audio and talks to Live. Answer in the user's language "
    "(German or English). Use only the tools you are given."
)
WARN_SYSTEM_SUFFIX = (
    "\n\nResource guard: this request is close to its limits. Start no new sub-tasks and "
    "answer briefly."
)

_FAILURE_DE = {
    "model_unavailable": "Claude ist gerade nicht erreichbar ({detail}). "
    "Kick-Engine und Ableton-Bridge funktionieren weiter ohne Claude.",
    "model_limit": "Claude hat die Anfrage an einer eigenen Grenze beendet ({detail}).",
    "model_protocol": "Die Antwort von Claude war nicht lesbar ({detail}).",
    "model_client_error": "Interner Fehler im Modell-Client ({detail}).",
    "incomplete": "Nicht alles wurde erledigt.",
}


# Agent SDK result subtypes for the limits the guard hands it (permit.sdk_limits).
_BACKEND_LIMITS = {
    "error_max_turns": Limit.MODEL_CALLS,
    "error_max_budget_usd": Limit.REQUEST_BUDGET,
}


def tools_sentence(names: tuple[str, ...]) -> str:
    """Names exactly the registered tools and says nothing else exists (#163). Wording is
    minimal on purpose: language and style are a D-022 questionnaire decision."""
    if not names:
        return ("You have no tools in this session. Nothing can be generated or changed; "
                "do not offer it.")
    return (f"Tools available in this session: {', '.join(names)}. Nothing else is "
            "available yet; do not offer anything these tools cannot do.")


class SdkLimitError(RuntimeError):
    """The orchestrator was about to hand the backend a limit that disables it."""


@dataclass(frozen=True)
class Outcome:
    """What the user gets for one request."""

    success: bool
    reply: str
    message_de: str
    done: tuple[str, ...]
    open: tuple[str, ...]
    stop_reason: Limit | None = None
    error: str | None = None
    warnings: tuple[str, ...] = ()
    usage: dict[str, Any] = field(default_factory=dict)
    result: RequestResult | None = None

    def __post_init__(self) -> None:
        guard_success = self.result is not None and self.result.success
        if self.success != guard_success:
            raise ValueError("An outcome is a success exactly when the guard finished it.")
        if self.success and (self.stop_reason or self.error or self.open):
            raise ValueError("A stopped, failed or unfinished request cannot be a success.")
        if not self.success and not (self.stop_reason or self.error):
            raise ValueError("A failed outcome must name a stop reason or an error.")

    @property
    def text_for_user(self) -> str:
        parts = list(self.warnings)
        if self.reply:
            parts.append(self.reply)
        if not self.success:
            parts.append(self.message_de)
        return "\n".join(p for p in parts if p)


class _Abort(Exception):
    """Ends a request with a non-guard error (inside the guarded block, so the guard logs
    the request as ``error``)."""

    def __init__(self, error: str, detail: str, reply: str = "") -> None:
        super().__init__(f"{error}: {detail}")
        self.error = error
        self.detail = detail
        self.reply = reply


def checked_sdk_limits(limits: dict[str, Any]) -> dict[str, Any]:
    """Validate limits before they go to a backend. The Agent SDK passes ``--max-turns`` only
    when the value is truthy, so 0 would mean *no limit* (PR #79 research note, not verified;
    V2 there): refuse anything below 1 instead of passing it on."""
    turns = limits.get("max_turns")
    if isinstance(turns, bool) or not isinstance(turns, int) or turns < 1:
        raise SdkLimitError(f"max_turns must be an int >= 1, got {turns!r}")
    budget = limits.get("max_budget_usd")
    if isinstance(budget, bool) or not isinstance(budget, int | float) or not budget > 0:
        raise SdkLimitError(f"max_budget_usd must be > 0, got {budget!r}")
    return dict(limits)


def _response_problem(response: object) -> str | None:
    if not isinstance(response, ModelResponse):
        return f"client returned {type(response).__name__}, not ModelResponse"
    if not isinstance(response.text, str):
        return "response text is not a string"
    if not isinstance(response.tool_calls, tuple) or not all(
        isinstance(c, ToolCall) for c in response.tool_calls
    ):
        return "tool_calls must be a tuple of ToolCall"
    if response.usage is not None and not isinstance(response.usage, ModelUsage):
        return "usage must be ModelUsage or None"
    return None


class Orchestrator:
    def __init__(
        self,
        guard: Guard,
        model: ModelClient,
        toolbox: Toolbox,
        *,
        profile: str = DEFAULT_PROFILE,
        approver: Approver | None = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        estimate_cost_usd: Callable[[ModelRequest], float | None] | None = None,
        context: Callable[[], str] | None = None,
    ) -> None:
        guard.policy.profile(profile)  # unknown profile fails here, not on the first request
        self.guard = guard
        self.model = model
        self.toolbox = toolbox
        self.profile = profile
        self.approver = approver
        self.system_prompt = system_prompt
        # Session facts appended to the system prompt once per request (e.g. the kicks this
        # chat session made, so a later request can import one by its sample_id). Fixed for
        # the whole request: the SDK session keeps the system prompt of its first call.
        self.context = context
        # None = the guard reserves all money still available (most conservative).
        if estimate_cost_usd is None:
            estimate_cost_usd = getattr(model, "estimate_cost_usd", None)
        self._estimate = estimate_cost_usd or (lambda _request: None)

    def handle(self, text: str) -> Outcome:
        """Run one user request to its end. Never raises for model, tool or guard failures."""
        try:
            return self._handle(text)
        finally:
            end = getattr(self.model, "end_request", None)
            if callable(end):
                try:
                    end()
                except Exception:  # noqa: BLE001 - closing a session must not hide the outcome
                    pass

    def _handle(self, text: str) -> Outcome:
        warnings: list[str] = []
        req: GuardedRequest | None = None
        try:
            with self.guard.request(self.profile) as req:
                req.add_open(ANSWER_ITEM)
                return self._run(req, text, warnings)
        except GuardStop as stop:
            return Outcome(
                success=False,
                reply="",
                message_de=stop.user_message_de,
                done=stop.done,
                open=stop.open,
                stop_reason=stop.reason,
                warnings=tuple(warnings),
                usage=dict(stop.usage),
                result=stop.result,
            )
        except _Abort as abort:
            done = req.done if req is not None else ()
            still_open = req.open if req is not None else (ANSWER_ITEM,)
            return Outcome(
                success=False,
                reply=abort.reply,
                message_de=_FAILURE_DE[abort.error].format(detail=abort.detail),
                done=done,
                open=still_open or (ANSWER_ITEM,),
                error=abort.error,
                warnings=tuple(warnings),
            )

    # ----- internals ------------------------------------------------------------------------

    def _request_system(self) -> str:
        """System prompt for one request: the base text, the registered tools by name (#163:
        the model offered features that do not exist), then the session context."""
        system = f"{self.system_prompt}\n\n{tools_sentence(self.toolbox.names)}"
        if self.context is None:
            return system
        try:
            extra = self.context()
        except Exception:  # noqa: BLE001 - missing context must not stop the request
            return system
        if not isinstance(extra, str) or not extra.strip():
            return system
        return f"{system}\n\n{extra.strip()}"

    def _run(self, req: GuardedRequest, text: str, warnings: list[str]) -> Outcome:
        messages: list[Message] = [UserMessage(text)]
        system = self._request_system()
        pending = getattr(self.model, "tool_call_pending", None)
        still_waiting = pending if callable(pending) else None
        handed = getattr(self.model, "tool_call_presented", None)
        presented = handed if callable(handed) else None
        while True:
            response = self._call_model(req, messages, system)
            # One start for the whole turn: the confirmation window is per model turn, so time
            # spent on earlier calls of the turn counts (the CLI waits for all of them).
            turn_started = self.toolbox.clock()
            self._note_warning(req, warnings)
            if not response.tool_calls:
                return self._final(req, response, warnings)
            messages.append(AssistantMessage(response.text, response.tool_calls))
            results = []
            for call in response.tool_calls:
                results.append(self.toolbox.run(
                    req, call, self.approver,
                    turn_started=turn_started, still_waiting=still_waiting,
                    presented=presented,
                ))
                self._note_warning(req, warnings)
            messages.append(ToolResultMessage(tuple(results)))

    def _call_model(
        self, req: GuardedRequest, messages: list[Message], system: str | None = None
    ) -> ModelResponse:
        """The only place that calls the model. Guarded on both sides."""
        system = self.system_prompt if system is None else system
        if req.level is Level.WARN:
            system += WARN_SYSTEM_SUFFIX
        draft = ModelRequest(
            system=system,
            messages=tuple(messages),
            tools=self.toolbox.specs(),
            max_output_tokens=req.profile.max_output_tokens,
            timeout_s=req.remaining_s(),
            sdk_limits={},  # filled from the permit below
        )
        permit = req.before_model_call(estimated_cost_usd=self._safe_estimate(draft))
        # Same locked step and same day as the reservation, including this call (PR #89 review).
        limits = permit.sdk_limits
        try:
            request = ModelRequest(
                system=draft.system,
                messages=draft.messages,
                tools=draft.tools,
                max_output_tokens=permit.max_output_tokens,
                timeout_s=req.remaining_s(),
                sdk_limits=checked_sdk_limits(limits),
                reserved_cost_usd=permit.reserved_cost_usd,
            )
            response = self.model.complete(request)
        except ModelUnavailable as exc:
            # Reported usage wins; else provably not sent -> it cost nothing; else count the
            # reservation.
            usage = exc.usage
            if usage is None and not exc.request_sent:
                usage = ModelUsage(output_tokens=0, cost_usd=0.0)
            req.after_model_call(permit, usage if isinstance(usage, ModelUsage) else None)
            raise _Abort("model_unavailable", exc.detail) from exc
        except ModelLimitReached as exc:
            usage = exc.usage if isinstance(exc.usage, ModelUsage) else None
            req.after_model_call(permit, usage)  # may already stop on the overshoot
            limit = _BACKEND_LIMITS.get(exc.subtype)
            if limit is not None:
                # The backend enforced a limit the guard gave it: report it as the guard's stop.
                req.stop_request(limit, f"Agent SDK {exc.subtype}: {exc.detail}")
            raise _Abort("model_limit", exc.subtype) from exc
        except ModelProtocolError as exc:
            req.after_model_call(permit, None)
            raise _Abort("model_protocol", str(exc)) from exc
        except SdkLimitError as exc:
            req.after_model_call(permit, ModelUsage(output_tokens=0, cost_usd=0.0))
            raise _Abort("model_client_error", str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - a client bug must not crash the chat
            req.after_model_call(permit, None)
            raise _Abort("model_client_error", type(exc).__name__) from exc
        problem = _response_problem(response)
        if problem is not None:
            usage = getattr(response, "usage", None)
            req.after_model_call(permit, usage if isinstance(usage, ModelUsage) else None)
            raise _Abort("model_protocol", problem)
        req.after_model_call(permit, response.usage)
        return response

    def _final(
        self, req: GuardedRequest, response: ModelResponse, warnings: list[str]
    ) -> Outcome:
        req.mark_done(ANSWER_ITEM)
        if req.open:
            raise _Abort("incomplete", ", ".join(req.open), reply=response.text)
        result = req.finish(response.text)
        return Outcome(
            success=True,
            reply=response.text,
            message_de="",
            done=result.done,
            open=(),
            warnings=tuple(warnings),
            usage=dict(result.usage),
            result=result,
        )

    def _safe_estimate(self, request: ModelRequest) -> float | None:
        """A broken or invalid estimate falls back to None (reserve all money left)."""
        try:
            value = self._estimate(request)
        except Exception:  # noqa: BLE001 - an estimator bug must not skip the guard
            return None
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return float(value) if math.isfinite(value) and value >= 0 else None

    @staticmethod
    def _note_warning(req: GuardedRequest, warnings: list[str]) -> None:
        if req.level is Level.WARN:
            note = warning_message_de(req.warnings)
            if note and note not in warnings:
                warnings.append(note)


__all__ = [
    "ANSWER_ITEM",
    "DEFAULT_PROFILE",
    "DEFAULT_SYSTEM_PROMPT",
    "Orchestrator",
    "Outcome",
    "SdkLimitError",
    "checked_sdk_limits",
]
