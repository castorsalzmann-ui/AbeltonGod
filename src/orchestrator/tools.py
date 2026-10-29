"""Model-callable tools and the only code path that runs them (D-002, D-004, D-011).

``Toolbox.run`` is the single executor. For every tool call the model asks for, in this order:

1. ``GuardedRequest.before_tool`` - always first, also for unknown tools and invalid
   arguments, so the guard counts every call and sees loops even of rejected calls (the same
   role as a catch-all PreToolUse deny hook in the Agent SDK). A ``GuardStop`` here means the
   handler never runs. The files a call may write are declared per call (``files_for``), from
   the raw arguments, before they are validated; anything unreadable declares the maximum.
   A call that declares more files than the request has left reserves nothing and is
   refused with the numbers (``file_budget``) after validation, instead of a guard stop.
2. Unknown tool name -> rejected.
3. Arguments validated against the tool's JSON Schema -> rejected if invalid. A confirm tool
   then waits up to ``PRESENT_WAIT_S`` until the backend has handed this very call to the
   guard (``presented``); if not, it is refused (``not_presented``) before anyone is asked.
4. ``prepare`` (confirm tools only, read only): checks against the current state and builds
   the ``Plan`` the user is shown, e.g. the track name and slot read from Live. A
   ``ToolError`` here refuses the call before anyone is asked.
5. Approval level ``confirm`` (anything that touches the Live set) -> asks the ``Approver``
   with the plan; no or no approver -> declined. After a yes, three checks before the handler
   (#81, #83 V10):
   - the request deadline again (``GuardedRequest.check_deadline``): a yes that comes after
     the request timed out stops the request, and nothing runs;
   - the yes must come within ``CONFIRM_WINDOW_S`` of the model turn that asked for the call
     (per turn, not per call), else it is refused as too late. Reason: while the user
     decides, the Claude Code CLI waits in its PreToolUse hook. The client hands it a 7-day
     hook timeout, and whether the real CLI keeps that value is V10 (#83, not verified). If it
     fell back to a default, it would block the call and make a model call the guard never
     permitted. Defaults named so far: 60 s (comment on ``HookMatcher.timeout`` in
     claude-agent-sdk 0.2.174 ``types.py``) and 600 s (Claude Code hooks docs, research note
     ``2026-10-28_agent-sdk-behaviour.md``); the window is set well below the smaller one;
   - the model client, if it can tell (``still_waiting``), must still be waiting for exactly
     this call (no hook cancelled by the CLI, no model call seen since the tool turn).
6. The handler runs (with the plan when the tool has ``prepare``).
7. ``GuardedRequest.after_tool`` with the reported files / Live writes. A rejected, declined or
   failed call is settled with ``ok=False``, so it stays listed as open until a later call of
   the same tool succeeds (guard default label ``Werkzeug <name>``). A ``ToolError`` may carry
   what the handler really wrote; without it the declared maximum is counted.

A tool that names a capability is only accepted when that capability is ``tested`` (D-004),
through a gate without check-script overrides; a capability that is not a read needs approval
``confirm``.
"""

from __future__ import annotations

import copy
import math
import numbers
import re
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from guard import GuardedRequest, GuardStop, Limit
from orchestrator.model_client import ToolCall, ToolResult, ToolSpec

MAX_REPORTED_ERRORS = 5
TOOL_NAME = re.compile(r"[a-zA-Z0-9_-]{1,128}")
# Longest time from the model turn that asked for a confirm tool to the user's yes (user
# decision on PR #168: 20 s). The smallest hook-timeout default named anywhere is 60 s (SDK
# types.py comment; the hooks docs say 600 s), so a confirmed write starts well inside it even
# if the CLI ignored the client's 7-day value (V10, #83).
CONFIRM_WINDOW_S = 20.0
# How long a confirm tool waits for the backend to present its own call (its PreToolUse hook)
# before the user is asked. The fake CLI presents a turn's calls one after another, each only
# after the previous hook was answered; whether the real CLI does so is not established.
PRESENT_WAIT_S = 2.0


class Approval(StrEnum):
    ROUTINE = "routine"  # generating files: runs without asking
    CONFIRM = "confirm"  # touching the Live set: the user must say yes first


class ToolDefinitionError(ValueError):
    """A tool definition breaks a rule (bad schema, wrong approval level, untested capability)."""


class ToolError(Exception):
    """Raised by a handler (or ``prepare``) for an expected failure; the message goes back to
    the model. ``files_written`` / ``live_writes``: what really happened before the failure
    (``None`` = not known, the guard counts the declared maximum). ``details``: extra fields
    for the model, e.g. whether Live is unchanged."""

    def __init__(
        self,
        message: str,
        *,
        files_written: int | None = None,
        live_writes: int | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.files_written = files_written
        self.live_writes = live_writes
        self.details = dict(details or {})


@dataclass(frozen=True)
class ToolOutput:
    """What a handler returns. ``files_written`` / ``live_writes`` are what it really did;
    ``None`` makes the guard count the declared maximum (conservative)."""

    content: dict[str, Any]
    files_written: int | None = None
    live_writes: int | None = None


@dataclass(frozen=True)
class Plan:
    """What ``prepare`` found: ``summary`` is shown to the user before the yes (plain JSON
    values), ``data`` goes to the handler unchanged."""

    summary: dict[str, Any]
    data: Any = None


Handler = Callable[..., ToolOutput]


@dataclass(frozen=True)
class Tool:
    """``files_for(arguments)``: the files one call may write, from the raw (not yet
    validated) arguments; capped at ``max_files_written``, and a failure or an unreadable
    value counts as ``max_files_written``. ``prepare(arguments) -> Plan``: read-only checks
    before the confirmation (confirm tools only); the handler then gets ``(arguments, plan)``.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Handler = field(repr=False)
    approval: Approval = Approval.ROUTINE
    max_files_written: int = 0
    max_live_writes: int = 0
    capabilities: tuple[str, ...] = ()
    files_for: Callable[[Any], int] | None = field(default=None, repr=False)
    prepare: Callable[[dict[str, Any]], Plan] | None = field(default=None, repr=False)

    def declared_files(self, arguments: Any) -> int:
        if self.files_for is None:
            return self.max_files_written
        try:
            value = self.files_for(arguments)
        except Exception:  # noqa: BLE001 - an unreadable declaration declares the maximum
            return self.max_files_written
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return self.max_files_written
        return min(value, self.max_files_written)

    def __post_init__(self) -> None:
        # API rule for tool names (tool-schema note, Q5); the SDK prefix mcp__<server>__ is
        # added by an adapter later and must keep the full name within the same rule.
        if not isinstance(self.name, str) or not TOOL_NAME.fullmatch(self.name):
            raise ToolDefinitionError(
                f"Tool name {self.name!r} must match {TOOL_NAME.pattern} (no dots, no spaces)."
            )
        for label, value in (
            ("max_files_written", self.max_files_written),
            ("max_live_writes", self.max_live_writes),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ToolDefinitionError(f"{self.name}: {label} must be an int >= 0")
        if not isinstance(self.approval, Approval):
            raise ToolDefinitionError(f"{self.name}: approval must be an Approval")
        if self.max_live_writes > 0 and self.approval is not Approval.CONFIRM:
            raise ToolDefinitionError(
                f"{self.name}: a tool that touches the Live set needs approval 'confirm'"
            )
        if not isinstance(self.capabilities, tuple) or not all(
            isinstance(c, str) for c in self.capabilities
        ):
            raise ToolDefinitionError(f"{self.name}: capabilities must be a tuple of ids")
        if self.prepare is not None and self.approval is not Approval.CONFIRM:
            raise ToolDefinitionError(
                f"{self.name}: prepare (a plan shown before the yes) is for confirm tools"
            )
        if self.files_for is not None and not callable(self.files_for):
            raise ToolDefinitionError(f"{self.name}: files_for must be callable")
        # prepare is not checked for callable here: the guard-wiring test allows no access to
        # it except the call in Toolbox.run and `is None` tests; a broken one fails there.
        if not isinstance(self.input_schema, Mapping) or self.input_schema.get("type") != (
            "object"
        ):
            raise ToolDefinitionError(f"{self.name}: input_schema must be a JSON Schema object")
        try:
            Draft202012Validator.check_schema(self.input_schema)
        except SchemaError as exc:
            raise ToolDefinitionError(f"{self.name}: invalid input_schema: {exc.message}") from exc
        # own copy: a later change to the caller's dict must not change what is validated
        object.__setattr__(self, "input_schema", copy.deepcopy(dict(self.input_schema)))

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(self.name, self.description, copy.deepcopy(dict(self.input_schema)))


class Approver(Protocol):
    def confirm(self, tool: Tool, arguments: dict[str, Any], plan: Plan | None) -> bool:
        """Ask the user, showing ``plan.summary`` if there is a plan. Return True only on an
        explicit yes."""
        ...


class CapabilityChecker(Protocol):
    def check(self, capability_id: str) -> object:
        """Raise if the capability may not be called (``bridge.capabilities.CapabilityGate``).
        The returned object's ``kind`` ("read", "write", "action") sets the approval rule."""
        ...


def _has_non_finite(value: Any) -> bool:
    """True for NaN/Infinity and for numbers JSON cannot carry. jsonschema accepts any
    ``numbers.Number`` as "number", so Decimal (incl. Decimal NaN), Fraction and complex
    would otherwise pass range-free fields."""
    if isinstance(value, bool) or isinstance(value, numbers.Integral):
        return False
    if isinstance(value, numbers.Number):
        # NumPy floats count as JSON numbers (float32 is not a float subclass)
        is_float = isinstance(value, float) or type(value).__module__ == "numpy"
        if not (is_float and isinstance(value, numbers.Real)):
            return True
        return not math.isfinite(float(value))
    if isinstance(value, Mapping):
        return any(_has_non_finite(v) for v in value.values())
    if isinstance(value, list | tuple):
        return any(_has_non_finite(v) for v in value)
    return False


def validation_errors(tool: Tool, arguments: Any) -> list[str]:
    """Problems with ``arguments`` for ``tool``; empty when valid."""
    if not isinstance(arguments, Mapping):
        return [f"arguments must be a JSON object, got {type(arguments).__name__}"]
    if _has_non_finite(arguments):
        return ["arguments contain NaN, Infinity or a non-JSON number type (Decimal, "
                "Fraction, complex), which JSON does not allow"]
    validator = Draft202012Validator(tool.input_schema)
    errors = sorted(validator.iter_errors(dict(arguments)), key=lambda e: list(e.path))
    return [
        f"{'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}" for e in errors
    ]


class Toolbox:
    """Holds the tools the model may call and runs them through the guard."""

    def __init__(
        self,
        tools: Iterable[Tool] = (),
        *,
        capability_gate: CapabilityChecker | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        # A check-script override (bridge.capabilities.CapabilityGate.allow_untested) would
        # let an untested capability pass the check below (D-004).
        if capability_gate is not None and getattr(capability_gate, "allow_untested", ()):
            raise ToolDefinitionError(
                "the toolbox's capability gate must not carry check-script overrides "
                "(allow_untested)"
            )
        self._gate = capability_gate
        self.clock = clock
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if not isinstance(tool, Tool):
            raise ToolDefinitionError("Only Tool objects can be registered.")
        if tool.name in self._tools:
            raise ToolDefinitionError(f"duplicate tool {tool.name!r}")
        if tool.capabilities:
            if self._gate is None:
                raise ToolDefinitionError(
                    f"{tool.name}: names capabilities but the toolbox has no capability gate"
                )
            for cap_id in tool.capabilities:
                try:
                    cap = self._gate.check(cap_id)
                except Exception as exc:  # noqa: BLE001 - any refusal rejects the tool
                    raise ToolDefinitionError(
                        f"{tool.name}: capability {cap_id!r} may not become a tool: {exc}"
                    ) from exc
                kind = getattr(cap, "kind", None)
                if kind != "read" and tool.approval is not Approval.CONFIRM:
                    raise ToolDefinitionError(
                        f"{tool.name}: capability {cap_id!r} is kind {kind!r}, not a read; "
                        "a tool that changes the Live set needs approval 'confirm'"
                    )
        self._tools[tool.name] = tool

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(t.spec for t in self._tools.values())

    def run(
        self,
        req: GuardedRequest,
        call: ToolCall,
        approver: Approver | None,
        *,
        turn_started: float | None = None,
        still_waiting: Callable[[str], bool] | None = None,
        presented: Callable[[str, float], bool] | None = None,
    ) -> ToolResult:
        """Run one model tool call through the guard. ``GuardStop`` propagates; every other
        failure becomes an error result the model can read.

        ``turn_started``: ``self.clock()`` when the model turn that asked for this call
        arrived (for ``CONFIRM_WINDOW_S``; the same value for every call of the turn).
        ``still_waiting(call_id)``: whether the model backend still waits for this call
        (``SdkModelClient.tool_call_pending``). ``presented(call_id, wait_s)``: whether the
        backend has presented this call to the guard, waiting up to ``wait_s``
        (``SdkModelClient.tool_call_presented``); a confirm tool asks it before the user."""
        tool = self._tools.get(call.name) if isinstance(call.name, str) else None
        name = call.name if isinstance(call.name, str) and call.name else "<unnamed>"
        declared_files = tool.declared_files(call.arguments) if tool else 0
        # A call that would not fit the request's file budget reserves nothing and is refused
        # below with the numbers, instead of stopping the whole request (PR #168 review).
        files_left = req.files_left()
        over_budget = declared_files > files_left
        permit = req.before_tool(
            name,
            call.arguments,
            writes_files=0 if over_budget else declared_files,
            live_writes=tool.max_live_writes if tool else 0,
        )
        if tool is None:
            req.after_tool(permit, files_written=0, live_writes=0, ok=False)
            return _error(call, "unknown_tool", f"no tool named {name!r}; known: {self.names}")
        errors = validation_errors(tool, call.arguments)
        if errors:
            req.after_tool(permit, files_written=0, live_writes=0, ok=False)
            return _error(
                call, "invalid_arguments", "; ".join(errors[:MAX_REPORTED_ERRORS]),
                errors=errors[:MAX_REPORTED_ERRORS],
            )
        if over_budget:
            req.after_tool(permit, files_written=0, live_writes=0, ok=False)
            return _error(
                call, "file_budget",
                f"this call would write {declared_files} files, but this request may write "
                f"only {files_left} more (guard limit max_files_written "
                f"{req.profile.max_files_written} per request). Nothing was written; ask for "
                "less in one call.",
                files_needed=declared_files, files_left=files_left,
            )
        if tool.approval is Approval.CONFIRM and presented is not None:
            try:
                shown = presented(call.id, PRESENT_WAIT_S) is True
            except Exception:  # noqa: BLE001 - unknown counts as "not presented"
                shown = False
            if not shown:
                req.after_tool(permit, files_written=0, live_writes=0, ok=False)
                return _error(
                    call, "not_presented",
                    f"Claude Code had not handed this {name} call to the guard within "
                    f"{PRESENT_WAIT_S:g} s (it is not the first tool call of its turn). Nobody "
                    "was asked and nothing was sent to Live. Call it again as the only tool "
                    "call of your next turn.",
                )
        arguments = copy.deepcopy(dict(call.arguments))
        plan: Plan | None = None
        if tool.prepare is not None:
            # Read-only by definition (it only builds the plan), so a failure counts no write.
            try:
                plan = tool.prepare(copy.deepcopy(arguments))
                if not isinstance(plan, Plan):
                    raise TypeError(f"prepare returned {type(plan).__name__}, not Plan")
            except ToolError as exc:
                req.after_tool(permit, files_written=0, live_writes=0, ok=False)
                return _error(call, "refused", str(exc), **_details(exc))
            except Exception as exc:  # noqa: BLE001 - a prepare bug must not end the session
                req.after_tool(permit, files_written=0, live_writes=0, ok=False)
                return _error(call, "internal_error", f"{type(exc).__name__} in {tool.name}")
        if tool.approval is Approval.CONFIRM:
            approved = False
            if approver is not None:
                try:
                    approved = approver.confirm(
                        tool, copy.deepcopy(arguments), copy.deepcopy(plan)
                    ) is True
                except Exception:  # noqa: BLE001 - a broken prompt is a "no", never a "yes"
                    approved = False
            if not approved:
                req.after_tool(permit, files_written=0, live_writes=0, ok=False)
                return _error(call, "declined", "the user did not confirm this action")
            refusal = self._after_yes(req, permit, call, name, turn_started, still_waiting)
            if refusal is not None:
                return refusal
        handler_args = (arguments,) if plan is None else (arguments, plan)
        try:
            output = tool.handler(*handler_args)
            if not isinstance(output, ToolOutput):
                raise TypeError(f"handler returned {type(output).__name__}, not ToolOutput")
        except ToolError as exc:
            # What the handler says it did before failing; None counts the declared maximum.
            overrun = _overrun(tool, declared_files, exc.files_written, exc.live_writes)
            req.after_tool(
                permit, files_written=exc.files_written, live_writes=exc.live_writes, ok=False
            )
            if overrun is not None:
                req.stop_request(Limit.UNDECLARED_WRITE, f"{tool.name} {overrun}")
            return _error(call, "tool_error", str(exc), **_details(exc))
        except Exception as exc:  # noqa: BLE001 - a handler bug must not end the session
            req.after_tool(permit, ok=False)
            return _error(call, "internal_error", f"{type(exc).__name__} in {tool.name}")
        overrun = _overrun(tool, declared_files, output.files_written, output.live_writes)
        # A tool that did more than it declared (e.g. a routine tool that touched Live without
        # approval) is settled as failed with what it reported, then the request is stopped.
        req.after_tool(
            permit,
            files_written=output.files_written,
            live_writes=output.live_writes,
            ok=overrun is None,
        )
        if overrun is not None:
            req.stop_request(Limit.UNDECLARED_WRITE, f"{tool.name} {overrun}")
        return ToolResult(call.id, tool.name, False, copy.deepcopy(output.content))

    def _after_yes(
        self,
        req: GuardedRequest,
        permit: Any,
        call: ToolCall,
        name: str,
        turn_started: float | None,
        still_waiting: Callable[[str], bool] | None,
    ) -> ToolResult | None:
        """Checks between the user's yes and the handler. ``None`` = go on; else the refusal
        (already settled, nothing ran). A timed-out request raises ``GuardStop``."""
        try:
            req.check_deadline(open_item=f"Werkzeug {name}")
        except GuardStop:
            # settle with nothing done; after_tool raises the same (sticky) stop
            req.after_tool(permit, files_written=0, live_writes=0, ok=False)
            raise
        if turn_started is not None:
            waited = self.clock() - turn_started
            if not waited <= CONFIRM_WINDOW_S:  # also catches NaN
                req.after_tool(permit, files_written=0, live_writes=0, ok=False)
                return _error(
                    call, "too_late",
                    f"the confirmation came {waited:.0f} s after the request for it (limit "
                    f"{CONFIRM_WINDOW_S:g} s); nothing was run and nothing was sent to Live. "
                    "Ask the user to request it again.",
                )
        if still_waiting is not None:
            try:
                alive = still_waiting(call.id) is True
            except Exception:  # noqa: BLE001 - unknown counts as "not waiting"
                alive = False
            if not alive:
                req.after_tool(permit, files_written=0, live_writes=0, ok=False)
                return _error(
                    call, "session_lost",
                    "the Claude session no longer waits for this call; nothing was run and "
                    "nothing was sent to Live",
                )
        return None


def _overrun(
    tool: Tool, declared_files: int, files: object, live: object
) -> str | None:
    """Text if the handler reports more writes than this call declared, else None. Values the
    guard cannot read are left to the guard (it stops on them)."""
    for label, reported, declared in (
        ("Live writes", live, tool.max_live_writes),
        ("files", files, declared_files),
    ):
        if isinstance(reported, numbers.Real) and not isinstance(reported, bool):
            if math.isfinite(float(reported)) and reported > declared:
                return f"reported {reported:g} {label}, declared at most {declared}"
    return None


def _details(exc: ToolError) -> dict[str, Any]:
    return {k: copy.deepcopy(v) for k, v in exc.details.items() if k not in ("error", "message")}


def _error(call: ToolCall, kind: str, message: str, **extra: Any) -> ToolResult:
    name = call.name if isinstance(call.name, str) else "<unnamed>"
    return ToolResult(call.id, name, True, {"error": kind, "message": message, **extra})


__all__ = [
    "CONFIRM_WINDOW_S",
    "PRESENT_WAIT_S",
    "Approval",
    "Approver",
    "CapabilityChecker",
    "Handler",
    "Plan",
    "Tool",
    "ToolDefinitionError",
    "ToolError",
    "ToolOutput",
    "Toolbox",
    "validation_errors",
]
