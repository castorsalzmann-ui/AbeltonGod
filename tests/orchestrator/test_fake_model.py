"""Interface stub (G0): the fake model replays recordings and never runs past them."""

from __future__ import annotations

import json

import pytest

from orchestrator.fake_model import FakeModel, RecordingError
from orchestrator.model_client import (
    ModelClient,
    ModelProtocolError,
    ModelRequest,
    ModelResponse,
    ModelUnavailable,
)


def _request() -> ModelRequest:
    return ModelRequest(
        system="s", messages=(), tools=(), max_output_tokens=100, timeout_s=10.0, sdk_limits={}
    )


def test_fake_is_a_model_client():
    assert isinstance(FakeModel([{"text": "hi"}]), ModelClient)


def test_replays_in_order_then_reports_exhausted():
    fake = FakeModel(
        [
            {"text": "a", "tool_calls": [{"id": "c1", "name": "t", "arguments": {"x": 1}}]},
            {"text": "b", "usage": {"output_tokens": 7, "cost_usd": 0.001}},
        ]
    )
    first = fake.complete(_request())
    assert isinstance(first, ModelResponse)
    assert first.text == "a"
    assert [(c.id, c.name, c.arguments) for c in first.tool_calls] == [("c1", "t", {"x": 1})]
    second = fake.complete(_request())
    assert second.text == "b" and second.tool_calls == ()
    assert second.usage.output_tokens == 7 and second.usage.cost_usd == 0.001
    with pytest.raises(ModelUnavailable) as err:
        fake.complete(_request())
    assert err.value.request_sent is False
    assert fake.calls == 3


def test_repeat_last_loops_forever():
    fake = FakeModel([{"tool_calls": [{"name": "t", "arguments": {}}]}], repeat_last=True)
    for _ in range(50):
        assert fake.complete(_request()).tool_calls[0].name == "t"


def test_replayed_arguments_are_copies():
    fake = FakeModel([{"tool_calls": [{"name": "t", "arguments": {"a": [1]}}]}], repeat_last=True)
    fake.complete(_request()).tool_calls[0].arguments["a"].append(2)
    assert fake.complete(_request()).tool_calls[0].arguments == {"a": [1]}


def test_recorded_errors_are_raised():
    fake = FakeModel(
        [
            {"error": "unavailable", "detail": "connection refused", "request_sent": False},
            {"error": "protocol", "detail": "garbage"},
        ]
    )
    with pytest.raises(ModelUnavailable, match="connection refused") as err:
        fake.complete(_request())
    assert err.value.request_sent is False
    with pytest.raises(ModelProtocolError, match="garbage"):
        fake.complete(_request())


@pytest.mark.parametrize(
    "turn",
    [
        "not an object",
        {"error": "boom"},
        {"tool_calls": [{"arguments": {}}]},
        {"text": 3},
        {"usage": 5},
        {"surprise": 1},
    ],
)
def test_malformed_turns_fail_at_load(turn):
    with pytest.raises(RecordingError):
        FakeModel([turn])


def test_from_file(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"recording_version": 1, "turns": [{"text": "x"}]}), "utf-8")
    assert FakeModel.from_file(path).complete(_request()).text == "x"
    path.write_text(json.dumps({"recording_version": 2, "turns": []}), "utf-8")
    with pytest.raises(RecordingError):
        FakeModel.from_file(path)
    path.write_text("{", "utf-8")
    with pytest.raises(RecordingError):
        FakeModel.from_file(path)
