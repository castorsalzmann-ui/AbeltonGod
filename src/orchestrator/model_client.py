"""Model-client interface (Phase 04b step 1, D-020): the only shape in which the orchestrator
talks to a model.

One ``ModelClient.complete`` call is **one model call** (one turn): it gets the conversation so
far plus the tool specs and returns text and/or tool calls. The orchestrator loop owns the
iteration, so the guard sees every call (D-011). Nothing here knows about a concrete SDK; an
adapter for the Claude Agent SDK or the Messages API implements this protocol later (after the
cluster-1 research note, D-020).

Errors a client may raise:

- ``ModelUnavailable``: the model could not be reached or refused the call (network, auth,
  rate limit, adapter missing). ``request_sent=False`` says the request provably never reached
  the model (e.g. connection refused), so it cost nothing; the default ``True`` is the
  conservative assumption.
- ``ModelProtocolError``: the model answered, but the answer cannot be read.

Anything else a client raises is a bug in the client.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from guard import ModelUsage


class ModelError(Exception):
    """Base class for errors a model client reports on purpose."""


class ModelUnavailable(ModelError):
    """The model could not be reached (network, auth, adapter missing, rate limit)."""

    def __init__(self, detail: str, *, request_sent: bool = True) -> None:
        super().__init__(detail)
        self.detail = detail
        self.request_sent = request_sent


class ModelProtocolError(ModelError):
    """The model answered, but the answer is malformed."""


@dataclass(frozen=True)
class ToolSpec:
    """What the model is told about one tool. ``input_schema`` is a JSON Schema object that
    comes from ``contracts/`` for product tools (step 2)."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    """One tool call the model asked for. ``arguments`` is whatever the model sent; it is
    untrusted until the toolbox has validated it against the tool's schema."""

    id: str
    name: str
    arguments: Any


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    name: str
    is_error: bool
    content: dict[str, Any]


@dataclass(frozen=True)
class UserMessage:
    text: str
    role: str = field(default="user", init=False)


@dataclass(frozen=True)
class AssistantMessage:
    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    role: str = field(default="assistant", init=False)


@dataclass(frozen=True)
class ToolResultMessage:
    results: tuple[ToolResult, ...]
    role: str = field(default="tool", init=False)


Message = UserMessage | AssistantMessage | ToolResultMessage


@dataclass(frozen=True)
class ModelRequest:
    """Everything one model call gets. The guard fills the limits:

    - ``max_output_tokens``: from the guard permit (pass to the SDK/API as max tokens).
    - ``timeout_s``: seconds left in the guarded request.
    - ``sdk_limits``: ``GuardedRequest.sdk_limits()`` (``max_turns``, ``max_budget_usd``) for
      an SDK that enforces its own limits as the first line (D-011).
    """

    system: str
    messages: tuple[Message, ...]
    tools: tuple[ToolSpec, ...]
    max_output_tokens: int
    timeout_s: float
    sdk_limits: dict[str, Any]


@dataclass(frozen=True)
class ModelResponse:
    """One model turn. No ``tool_calls`` means this is the final answer."""

    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    usage: ModelUsage | None = None
    stop_reason: str | None = None


@runtime_checkable
class ModelClient(Protocol):
    def complete(self, request: ModelRequest) -> ModelResponse:
        """Make exactly one model call. Raise ``ModelUnavailable`` / ``ModelProtocolError``."""
        ...


__all__ = [
    "AssistantMessage",
    "Message",
    "ModelClient",
    "ModelError",
    "ModelProtocolError",
    "ModelRequest",
    "ModelResponse",
    "ModelUnavailable",
    "ToolCall",
    "ToolResult",
    "ToolResultMessage",
    "ToolSpec",
    "UserMessage",
]
