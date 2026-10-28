"""Model-callable tools and the only code path that runs them (D-002, D-004, D-011).

``Toolbox.run`` is the single executor. For every tool call the model asks for, in this order:

1. ``GuardedRequest.before_tool`` - always first, also for unknown tools and invalid
   arguments, so the guard counts every call and sees loops even of rejected calls (the same
   role as a catch-all PreToolUse deny hook in the Agent SDK). A ``GuardStop`` here means the
   handler never runs.
2. Unknown tool name -> rejected.
3. Arguments validated against the tool's JSON Schema -> rejected if invalid.
4. Approval level ``confirm`` (anything that touches the Live set) -> asks the ``Approver``;
   no or no approver -> declined.
5. The handler runs.
6. ``GuardedRequest.after_tool`` with the reported files / Live writes. A rejected, declined or
   failed call is settled with ``ok=False``, so it stays listed as open until a later call of
   the same tool succeeds (guard default label ``Werkzeug <name>``).

Tool definitions for Live (``list_tracks``, ``import_sample``) and ``generate_kick`` come in
Phase 04b step 2 (D-020) from ``contracts/`` schemas. A tool that names a capability is only
accepted when that capability is ``tested`` (D-004).
"""

from __future__ import annotations

import copy
import math
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from guard import GuardedRequest
from orchestrator.model_client import ToolCall, ToolResult, ToolSpec

MAX_REPORTED_ERRORS = 5
TOOL_NAME = re.compile(r"[a-zA-Z0-9_-]{1,128}")


class Approval(StrEnum):
    ROUTINE = "routine"  # generating files: runs without asking
    CONFIRM = "confirm"  # touching the Live set: the user must say yes first


class ToolDefinitionError(ValueError):
    """A tool definition breaks a rule (bad schema, wrong approval level, untested capability)."""


class ToolError(Exception):
    """Raised by a handler for an expected failure; the message goes back to the model."""


@dataclass(frozen=True)
class ToolOutput:
    """What a handler returns. ``files_written`` / ``live_writes`` are what it really did;
    ``None`` makes the guard count the declared maximum (conservative)."""

    content: dict[str, Any]
    files_written: int | None = None
    live_writes: int | None = None


Handler = Callable[[dict[str, Any]], ToolOutput]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Handler = field(repr=False)
    approval: Approval = Approval.ROUTINE
    max_files_written: int = 0
    max_live_writes: int = 0
    capabilities: tuple[str, ...] = ()

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
        if (self.max_live_writes > 0 or self.capabilities) and self.approval is not (
            Approval.CONFIRM
        ):
            raise ToolDefinitionError(
                f"{self.name}: a tool that touches the Live set needs approval 'confirm'"
            )
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
    def confirm(self, tool: Tool, arguments: dict[str, Any]) -> bool:
        """Ask the user. Return True only on an explicit yes."""
        ...


class CapabilityChecker(Protocol):
    def check(self, capability_id: str) -> object:
        """Raise if the capability may not be called (``bridge.capabilities.CapabilityGate``)."""
        ...


def _has_non_finite(value: Any) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
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
        return ["arguments contain NaN or Infinity, which JSON does not allow"]
    validator = Draft202012Validator(tool.input_schema)
    errors = sorted(validator.iter_errors(dict(arguments)), key=lambda e: list(e.path))
    return [
        f"{'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}" for e in errors
    ]


class Toolbox:
    """Holds the tools the model may call and runs them through the guard."""

    def __init__(
        self, tools: Iterable[Tool] = (), *, capability_gate: CapabilityChecker | None = None
    ) -> None:
        self._gate = capability_gate
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
                    self._gate.check(cap_id)
                except Exception as exc:  # noqa: BLE001 - any refusal rejects the tool
                    raise ToolDefinitionError(
                        f"{tool.name}: capability {cap_id!r} may not become a tool: {exc}"
                    ) from exc
        self._tools[tool.name] = tool

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(t.spec for t in self._tools.values())

    def run(
        self, req: GuardedRequest, call: ToolCall, approver: Approver | None
    ) -> ToolResult:
        """Run one model tool call through the guard. ``GuardStop`` propagates; every other
        failure becomes an error result the model can read."""
        tool = self._tools.get(call.name) if isinstance(call.name, str) else None
        name = call.name if isinstance(call.name, str) and call.name else "<unnamed>"
        permit = req.before_tool(
            name,
            call.arguments,
            writes_files=tool.max_files_written if tool else 0,
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
        arguments = copy.deepcopy(dict(call.arguments))
        if tool.approval is Approval.CONFIRM:
            approved = False
            if approver is not None:
                try:
                    approved = approver.confirm(tool, copy.deepcopy(arguments)) is True
                except Exception:  # noqa: BLE001 - a broken prompt is a "no", never a "yes"
                    approved = False
            if not approved:
                req.after_tool(permit, files_written=0, live_writes=0, ok=False)
                return _error(call, "declined", "the user did not confirm this action")
        try:
            output = tool.handler(arguments)
            if not isinstance(output, ToolOutput):
                raise TypeError(f"handler returned {type(output).__name__}, not ToolOutput")
        except ToolError as exc:
            req.after_tool(permit, ok=False)  # counts the declared maximum of writes
            return _error(call, "tool_error", str(exc))
        except Exception as exc:  # noqa: BLE001 - a handler bug must not end the session
            req.after_tool(permit, ok=False)
            return _error(call, "internal_error", f"{type(exc).__name__} in {tool.name}")
        req.after_tool(
            permit, files_written=output.files_written, live_writes=output.live_writes, ok=True
        )
        return ToolResult(call.id, tool.name, False, copy.deepcopy(output.content))


def _error(call: ToolCall, kind: str, message: str, **extra: Any) -> ToolResult:
    name = call.name if isinstance(call.name, str) else "<unnamed>"
    return ToolResult(call.id, name, True, {"error": kind, "message": message, **extra})


__all__ = [
    "Approval",
    "Approver",
    "CapabilityChecker",
    "Handler",
    "Tool",
    "ToolDefinitionError",
    "ToolError",
    "ToolOutput",
    "Toolbox",
    "validation_errors",
]
