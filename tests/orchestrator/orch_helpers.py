"""Shared test helpers and fixtures for the orchestrator tests.

Limits in TEST_POLICY are round numbers written here (not read from config/guard-policy.json),
so the expected stop points are independent of the code under test.

Deliberately **no** ``tests/orchestrator/conftest.py``: tests in ``tests/bridge`` do
``from conftest import ...``, and a second ``conftest`` module under rootdir imports replaces
it in ``sys.modules`` depending on collection order (seen as ImportError in two bug39 tests on
this branch, #86). Test modules import the fixtures below explicitly.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from guard import Guard, GuardedRequest, parse_policy
from orchestrator.model_client import ModelRequest, ModelResponse, ToolCall
from orchestrator.tools import Approval, Tool, ToolOutput

TEST_POLICY = {
    "schema_version": "1",
    "global": {"session_budget_usd": 3.0, "daily_budget_usd": 5.0, "max_concurrent_requests": 1},
    "profiles": {
        "p": {
            "max_output_tokens": 1000,
            "max_model_calls": 5,
            "max_tool_calls": 6,
            "max_budget_usd": 1.0,
            "timeout_s": 100,
            "max_identical_tool_calls": 3,
            "max_files_written": 10,
            "max_live_writes": 2,
            "warn_at_fraction": 0.8,
        }
    },
}

ECHO_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["n"],
    "properties": {
        "n": {"type": "integer", "minimum": 0, "maximum": 100},
        "label": {"type": "string", "maxLength": 10},
        "gain": {"type": "number", "minimum": -1.0, "maximum": 1.0},
    },
}


def make_policy(**changes: Any):
    doc = copy.deepcopy(TEST_POLICY)
    for key, value in changes.items():
        target = doc["global"] if key in doc["global"] else doc["profiles"]["p"]
        target[key] = value
    return parse_policy(doc)


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class Events:
    """Ordered record of guard steps and real executions."""

    def __init__(self) -> None:
        self.items: list[tuple[str, str]] = []

    def add(self, kind: str, name: str = "") -> None:
        self.items.append((kind, name))

    def kinds(self) -> list[str]:
        return [k for k, _ in self.items]


class SpyRequest(GuardedRequest):
    """A real GuardedRequest that also records each guard step that succeeded."""

    events: Events

    def before_model_call(self, **kwargs: Any):
        permit = super().before_model_call(**kwargs)
        self.events.add("before_model")
        return permit

    def after_model_call(self, permit, usage):
        self.events.add("after_model")
        return super().after_model_call(permit, usage)

    def before_tool(self, name, args, **kwargs: Any):
        permit = super().before_tool(name, args, **kwargs)
        self.events.add("before_tool", name)
        return permit

    def after_tool(self, permit, **kwargs: Any):
        self.events.add("after_tool", permit.name)
        return super().after_tool(permit, **kwargs)


class SpyGuard(Guard):
    def __init__(self, *args: Any, events: Events, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.events = events
        self.requests: list[SpyRequest] = []

    def request(self, profile_name: str) -> SpyRequest:
        profile = self.policy.profile(profile_name)
        req = SpyRequest(self, profile, f"{self.session_id}-spy{len(self.requests) + 1}")
        req.events = self.events
        self.requests.append(req)
        return req


@dataclass
class ScriptedModel:
    """Model client driven by a Python function (for property tests)."""

    script: Any
    events: Events | None = None
    requests: list[ModelRequest] = field(default_factory=list)

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if self.events is not None:
            self.events.add("model_call")
        return self.script(len(self.requests) - 1, request)


def echo_tool(events: Events | None = None, calls: list | None = None, **kwargs: Any) -> Tool:
    def handler(args: dict[str, Any]) -> ToolOutput:
        if events is not None:
            events.add("handler", "echo")
        if calls is not None:
            calls.append(copy.deepcopy(args))
        return ToolOutput({"echo": args}, files_written=0, live_writes=0)

    return Tool("echo", "Echo the arguments.", ECHO_SCHEMA, handler, **kwargs)


def file_tool(events: Events | None = None, files: int = 2) -> Tool:
    def handler(args: dict[str, Any]) -> ToolOutput:
        if events is not None:
            events.add("handler", "render")
        return ToolOutput({"files": files}, files_written=files)

    return Tool(
        "render",
        "Write files.",
        {"type": "object", "properties": {"k": {"type": "integer"}}, "additionalProperties": False},
        handler,
        max_files_written=files,
    )


def live_tool(events: Events | None = None) -> Tool:
    def handler(args: dict[str, Any]) -> ToolOutput:
        if events is not None:
            events.add("handler", "live_write")
        return ToolOutput({"ok": True}, live_writes=1)

    return Tool(
        "live_write",
        "Change the Live set.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        handler,
        approval=Approval.CONFIRM,
        max_live_writes=1,
    )


def call(name: str, args: Any, cid: str = "c") -> ToolCall:
    return ToolCall(cid, name, args)


# --- fixtures (import them explicitly in each test module) --------------------------------

BERLIN = timezone(timedelta(hours=1))


@pytest.fixture(name="clock")
def clock_fixture():
    return FakeClock()


@pytest.fixture(name="events")
def events_fixture():
    return Events()


@pytest.fixture(name="make_guard")
def make_guard_fixture(tmp_path, clock, events):
    counter = iter(range(10_000))

    def make(**policy_changes):
        return SpyGuard(
            make_policy(**policy_changes),
            log_path=tmp_path / f"usage{next(counter)}.jsonl",
            clock=clock,
            now=lambda: datetime(2026, 10, 28, 12, 0, tzinfo=BERLIN),
            events=events,
        )

    return make
