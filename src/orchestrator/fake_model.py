"""Fake model client that replays recorded responses (CI only; never calls a network).

A recording is a JSON file (internal test fixture of the orchestrator, not a cross-module
contract)::

    {"recording_version": 1,
     "description": "why this recording exists",
     "source": "hand-written" | "recorded <date> on the user's machine",
     "repeat_last": false,            # true: after the last turn, repeat it forever (loops)
     "turns": [
        {"text": "...",
         "tool_calls": [{"id": "c1", "name": "echo", "arguments": {...}}],
         "usage": {"output_tokens": 120, "input_tokens": 900, "cost_usd": 0.01},
         "stop_reason": "tool_use"},
        {"error": "unavailable", "detail": "connection refused", "request_sent": false},
        {"error": "protocol", "detail": "malformed answer"},
        {"error": "limit", "subtype": "error_max_budget_usd", "detail": "...",
         "usage": {"output_tokens": 900, "cost_usd": 0.31}}
     ]}

The ``limit`` kind mimics the Agent SDK's stop path as described in the cluster-1 note
(PR #79, not verified): a ``ResultMessage`` with ``error_max_turns`` / ``error_max_budget_usd``
followed by ``ResultError``, with the usage still reported (a budget stop can overshoot).

When the recording is used up (and ``repeat_last`` is false) the next call raises
``ModelUnavailable`` so a test can never silently run past its script. Every request the fake
receives is kept in ``requests`` so tests can check what the orchestrator sent.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from guard import ModelUsage
from orchestrator.model_client import (
    ModelLimitReached,
    ModelProtocolError,
    ModelRequest,
    ModelResponse,
    ModelUnavailable,
    ToolCall,
)

RECORDING_VERSION = 1
LIMIT_SUBTYPES = ("error_max_turns", "error_max_budget_usd")


class RecordingError(ValueError):
    """A recording file is malformed."""


def _usage_from_json(raw: Any, where: str) -> ModelUsage | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise RecordingError(f"{where}.usage must be an object")
    return ModelUsage(
        output_tokens=raw.get("output_tokens"),
        input_tokens=raw.get("input_tokens"),
        cost_usd=raw.get("cost_usd"),
    )


def _turn_from_json(raw: Any, where: str) -> ModelResponse | Exception:
    if not isinstance(raw, Mapping):
        raise RecordingError(f"{where}: a turn must be an object")
    if "error" in raw:
        detail = str(raw.get("detail", "recorded error"))
        if raw["error"] == "unavailable":
            return ModelUnavailable(detail, request_sent=bool(raw.get("request_sent", True)))
        if raw["error"] == "protocol":
            return ModelProtocolError(detail)
        if raw["error"] == "limit":
            subtype = raw.get("subtype")
            if subtype not in LIMIT_SUBTYPES:
                raise RecordingError(f"{where}: limit subtype must be one of {LIMIT_SUBTYPES}")
            return ModelLimitReached(
                subtype, detail, usage=_usage_from_json(raw.get("usage"), where)
            )
        raise RecordingError(f"{where}: unknown error kind {raw['error']!r}")
    unknown = set(raw) - {"text", "tool_calls", "usage", "stop_reason"}
    if unknown:
        raise RecordingError(f"{where}: unknown keys {sorted(unknown)}")
    calls = []
    for i, call in enumerate(raw.get("tool_calls", [])):
        if not isinstance(call, Mapping) or not isinstance(call.get("name"), str):
            raise RecordingError(f"{where}.tool_calls[{i}]: needs a string 'name'")
        calls.append(
            ToolCall(
                id=str(call.get("id", f"call_{i}")),
                name=call["name"],
                # deep copy: a replayed turn must not share mutable arguments with the recording
                arguments=copy.deepcopy(call.get("arguments")),
            )
        )
    usage = _usage_from_json(raw.get("usage"), where)
    text = raw.get("text", "")
    if not isinstance(text, str):
        raise RecordingError(f"{where}.text must be a string")
    return ModelResponse(
        text=text, tool_calls=tuple(calls), usage=usage, stop_reason=raw.get("stop_reason")
    )


class FakeModel:
    """Implements ``ModelClient`` by replaying turns in order."""

    def __init__(self, turns: Iterable[Mapping[str, Any]], *, repeat_last: bool = False) -> None:
        self._raw = [copy.deepcopy(t) for t in turns]
        # Parse once up front so a broken recording fails before the test runs anything.
        for i, raw in enumerate(self._raw):
            _turn_from_json(raw, f"turns[{i}]")
        if repeat_last and not self._raw:
            raise RecordingError("repeat_last needs at least one turn")
        self.repeat_last = repeat_last
        self.requests: list[ModelRequest] = []
        self._next = 0

    @classmethod
    def from_file(cls, path: Path | str) -> FakeModel:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RecordingError(f"cannot read recording {path}: {exc}") from exc
        if not isinstance(data, Mapping) or data.get("recording_version") != RECORDING_VERSION:
            raise RecordingError(f"{path}: recording_version must be {RECORDING_VERSION}")
        turns = data.get("turns")
        if not isinstance(turns, list):
            raise RecordingError(f"{path}: 'turns' must be a list")
        return cls(turns, repeat_last=bool(data.get("repeat_last", False)))

    @property
    def calls(self) -> int:
        return len(self.requests)

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if self._next >= len(self._raw):
            if not self.repeat_last:
                raise ModelUnavailable(
                    f"fake model: recording exhausted after {len(self._raw)} turn(s)",
                    request_sent=False,
                )
            index = len(self._raw) - 1
        else:
            index = self._next
            self._next += 1
        turn = _turn_from_json(self._raw[index], f"turns[{index}]")
        if isinstance(turn, Exception):
            raise turn
        return turn


__all__ = ["RECORDING_VERSION", "FakeModel", "RecordingError"]
