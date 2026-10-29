"""Phase 04b step 1 (#78): orchestrator loop and guard wiring, CI only (fake model, no Claude).

Every test checks the guard wiring with ``assert_guarded``: each model call sits between a
successful ``before_model_call`` and its ``after_model_call``, and each tool handler runs only
after a ``before_tool`` for that tool. Expected stop points come from TEST_POLICY in
``orch_helpers`` (round numbers written there, not read from the code).
"""

from __future__ import annotations

import json
import math
import random

import pytest
from orch_helpers import (  # noqa: F401 - *_fixture are pytest fixtures (see orch_helpers)
    ECHO_SCHEMA,
    Events,
    ScriptedModel,
    call,
    clock_fixture,
    echo_tool,
    events_fixture,
    file_tool,
    live_tool,
    make_guard_fixture,
)

from guard import Limit, ModelUsage
from orchestrator.clients import UnavailableModel
from orchestrator.fake_model import FakeModel
from orchestrator.loop import (
    ANSWER_ITEM,
    WARN_SYSTEM_SUFFIX,
    Orchestrator,
    Outcome,
    SdkLimitError,
    checked_sdk_limits,
)
from orchestrator.model_client import ModelResponse, ToolResultMessage
from orchestrator.tools import Toolbox


def assert_guarded(events: Events) -> None:
    """Every model call and every handler run is inside its guard step."""
    open_models = 0
    open_tools: list[str] = []
    model_calls_seen = 0
    for kind, name in events.items:
        if kind == "before_model":
            assert open_models == 0, "two model calls reserved at once"
            open_models = 1
        elif kind == "model_call":
            assert open_models == 1, "model called without a guard permit"
            model_calls_seen += 1
        elif kind == "after_model":
            assert open_models == 1, "model call settled without a permit"
            open_models = 0
        elif kind == "before_tool":
            open_tools.append(name)
        elif kind == "handler":
            assert open_tools and open_tools[-1] == name, f"handler {name} ran without the guard"
        elif kind == "after_tool":
            assert open_tools and open_tools[-1] == name
            open_tools.pop()
    assert open_models == 0 and not open_tools, "a guard step was left open"


DEFAULT_USAGE = {"output_tokens": 10, "input_tokens": 500, "cost_usd": 0.01}


def recorded(events: Events, turns, *, repeat_last=False, default_usage=True) -> ScriptedModel:
    """Fake model over ``turns``; answer turns without ``usage`` get DEFAULT_USAGE (a real
    backend always reports usage; missing usage is tested separately)."""
    if default_usage:
        turns = [
            t if not isinstance(t, dict) or "error" in t or "usage" in t
            else {**t, "usage": DEFAULT_USAGE}
            for t in turns
        ]
    fake = FakeModel(turns, repeat_last=repeat_last)
    return ScriptedModel(lambda i, request: fake.complete(request), events)


def orch(guard, model, tools=(), **kwargs) -> Orchestrator:
    return Orchestrator(guard, model, Toolbox(tools), profile="p", **kwargs)


def log_entries(guard) -> list[dict]:
    path = guard._log.path
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


# --- happy path ---------------------------------------------------------------------------


def test_tool_call_then_answer_is_a_guarded_success(make_guard, events):
    calls: list = []
    model = recorded(
        events,
        [
            {"tool_calls": [{"id": "c1", "name": "echo", "arguments": {"n": 3}}],
             "usage": {"output_tokens": 50, "cost_usd": 0.01}},
            {"text": "Fertig.", "usage": {"output_tokens": 20, "cost_usd": 0.02}},
        ],
    )
    guard = make_guard()
    out = orch(guard, model, [echo_tool(events, calls)]).handle("mach was")
    assert out.success is True and out.result.success is True
    assert out.reply == "Fertig." and out.text_for_user == "Fertig."
    assert out.done == ("Werkzeug echo", ANSWER_ITEM) and out.open == ()
    assert calls == [{"n": 3}]
    assert events.kinds() == [
        "model_attempt", "before_model", "model_call", "after_model",
        "before_tool", "handler", "after_tool",
        "model_attempt", "before_model", "model_call", "after_model",
        "finish_called",
    ]
    assert_guarded(events)
    # the tool result went back to the model as structured data
    second = model.requests[1]
    assert isinstance(second.messages[-1], ToolResultMessage)
    result = second.messages[-1].results[0]
    assert (result.call_id, result.is_error, result.content) == ("c1", False, {"echo": {"n": 3}})
    # usage reported by the model is what the guard counted
    assert out.usage["model_calls"] == 2 and out.usage["tool_calls"] == 1
    assert out.usage["cost_usd"] == pytest.approx(0.03)
    assert out.usage["output_tokens"] == 70
    assert log_entries(guard)[-1]["outcome"] == "success"


def test_model_request_carries_guard_limits(make_guard, events):
    """max_turns = model calls still allowed including this one (5, 4, ...), never 0."""
    model = recorded(
        events,
        [{"tool_calls": [{"id": f"c{i}", "name": "echo", "arguments": {"n": i}}]}
         for i in range(4)] + [{"text": "ok"}],
    )
    out = orch(make_guard(), model, [echo_tool(events)]).handle("x")
    assert out.success
    assert [r.sdk_limits["max_turns"] for r in model.requests] == [5, 4, 3, 2, 1]
    assert all(r.sdk_limits["max_budget_usd"] > 0 for r in model.requests)
    assert all(r.max_output_tokens == 1000 for r in model.requests)
    assert all(0 < r.timeout_s <= 100 for r in model.requests)
    assert [s.name for s in model.requests[0].tools] == ["echo"]
    assert_guarded(events)


# --- invalid tool arguments ---------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        {},  # required n missing
        {"n": -1},
        {"n": 101},
        {"n": "3"},
        {"n": True},
        {"n": 2.5},
        {"n": None},
        {"n": 1, "extra": 1},
        {"n": 1, "label": "x" * 11},
        {"n": 1, "gain": 1.5},
        {"n": 1, "gain": float("nan")},
        {"n": 1, "gain": float("inf")},
        [1, 2],
        "n=3",
        None,
    ],
)
def test_invalid_arguments_are_rejected_before_the_handler(make_guard, events, args):
    calls: list = []
    model = recorded(
        events,
        [{"tool_calls": [{"id": "c1", "name": "echo", "arguments": args}]}, {"text": "sorry"}],
    )
    out = orch(make_guard(), model, [echo_tool(events, calls)]).handle("x")
    assert calls == []
    result = model.requests[1].messages[-1].results[0]
    assert result.is_error and result.content["error"] == "invalid_arguments"
    assert out.success is False and out.error == "incomplete"
    assert "Werkzeug echo" in out.open
    assert "before_tool" in events.kinds()  # rejected calls are still counted by the guard
    assert_guarded(events)


def test_unknown_tool_is_rejected_and_counted(make_guard, events):
    model = recorded(
        events, [{"tool_calls": [{"name": "rm_rf", "arguments": {}}]}, {"text": "hm"}]
    )
    out = orch(make_guard(), model, [echo_tool(events)]).handle("x")
    assert model.requests[1].messages[-1].results[0].content["error"] == "unknown_tool"
    assert ("before_tool", "rm_rf") in events.items
    assert out.success is False and "Werkzeug rm_rf" in out.open


def test_retry_with_valid_arguments_succeeds(make_guard, events):
    calls: list = []
    model = recorded(
        events,
        [
            {"tool_calls": [{"name": "echo", "arguments": {"n": 500}}]},
            {"tool_calls": [{"name": "echo", "arguments": {"n": 5}}]},
            {"text": "ok"},
        ],
    )
    out = orch(make_guard(), model, [echo_tool(events, calls)]).handle("x")
    assert out.success and calls == [{"n": 5}]
    assert_guarded(events)


def _echo_args_valid(args) -> bool:
    """Independent reference for ECHO_SCHEMA (hand-written, not jsonschema)."""
    if not isinstance(args, dict) or "n" not in args:
        return False
    if set(args) - {"n", "label", "gain"}:
        return False
    n = args["n"]
    if isinstance(n, bool):
        return False
    if isinstance(n, float):
        if not (math.isfinite(n) and n.is_integer()):
            return False
    elif not isinstance(n, int):
        return False
    if not 0 <= n <= 100:
        return False
    if "label" in args and not (isinstance(args["label"], str) and len(args["label"]) <= 10):
        return False
    if "gain" in args:
        g = args["gain"]
        if isinstance(g, bool) or not isinstance(g, int | float):
            return False
        if not (math.isfinite(g) and -1.0 <= g <= 1.0):
            return False
    return True


_POOL = [
    0, 1, 50, 100, 101, -1, 10**12, 3.0, 2.5, -0.0, 1.0, -1.0, 1.0000001, -1.5,
    float("nan"), float("inf"), float("-inf"), True, False, None, "", "abc", "x" * 10,
    "y" * 11, [], [1], {}, {"a": 1},
]


@pytest.mark.parametrize("seed", range(6))
def test_property_handler_runs_exactly_for_schema_valid_arguments(make_guard, seed):
    rng = random.Random(7800 + seed)
    for _ in range(60):
        args: object
        if rng.random() < 0.1:
            args = rng.choice([None, [], "x", 3])
        else:
            args = {}
            for key in rng.sample(["n", "label", "gain", "other"], rng.randint(0, 4)):
                args[key] = rng.choice(_POOL)
            if rng.random() < 0.4:
                args["n"] = rng.randint(-5, 105)
        events = Events()
        calls: list = []
        model = recorded(
            events, [{"tool_calls": [{"name": "echo", "arguments": args}]}, {"text": "e"}]
        )
        guard = make_guard()
        guard.events = events
        out = orch(guard, model, [echo_tool(events, calls)]).handle("x")
        expected = _echo_args_valid(args)
        assert (len(calls) == 1) == expected, args
        assert out.success == expected, args
        assert_guarded(events)


# --- loops and guard stops ----------------------------------------------------------------


def test_model_looping_on_one_tool_is_stopped_by_the_guard(make_guard, events):
    calls: list = []
    model = recorded(
        events,
        [{"text": "noch mal", "tool_calls": [{"name": "echo", "arguments": {"n": 1}}]}],
        repeat_last=True,
    )
    guard = make_guard()
    out = orch(guard, model, [echo_tool(events, calls)]).handle("loop")
    assert out.success is False and out.result.success is False
    assert out.stop_reason is Limit.LOOP
    assert len(calls) == 3  # max_identical_tool_calls = 3
    assert out.done == ("Werkzeug echo",) * 3  # the guard lists each finished call
    assert set(out.open) == {ANSWER_ITEM, "Werkzeug echo"}
    assert "Abgebrochen" in out.text_for_user and "Fertig: Werkzeug echo" in out.message_de
    assert "Offen:" in out.message_de and ANSWER_ITEM in out.message_de
    assert log_entries(guard)[-1]["outcome"] == "stopped"
    assert_guarded(events)


def test_loop_of_invalid_calls_is_stopped_by_the_guard_too(make_guard, events):
    calls: list = []
    model = recorded(
        events, [{"tool_calls": [{"name": "echo", "arguments": {"n": -7}}]}], repeat_last=True
    )
    out = orch(make_guard(), model, [echo_tool(events, calls)]).handle("loop")
    assert out.stop_reason is Limit.LOOP and calls == []
    assert out.usage["tool_calls"] == 3


USAGE = ModelUsage(output_tokens=10, cost_usd=0.01)


def varying_echo(i, request):
    return ModelResponse(tool_calls=(call("echo", {"n": i}, f"c{i}"),), usage=USAGE)


def test_model_varying_arguments_is_stopped_by_the_call_limit(make_guard, events):
    model = ScriptedModel(varying_echo, events)
    out = orch(make_guard(), model, [echo_tool(events)]).handle("x")
    assert out.success is False and out.stop_reason is Limit.MODEL_CALLS
    assert len(model.requests) == 5
    assert_guarded(events)


def test_many_tool_calls_in_one_turn_hit_the_tool_limit(make_guard, events):
    calls: list = []
    turn = {"tool_calls": [{"id": f"c{i}", "name": "echo", "arguments": {"n": i}}
                           for i in range(10)]}
    model = recorded(events, [turn, {"text": "x"}])
    out = orch(make_guard(), model, [echo_tool(events, calls)]).handle("x")
    assert out.stop_reason is Limit.TOOL_CALLS and len(calls) == 6
    assert len(out.done) == 6
    # D-011 "Stop: no further model calls" - not even an attempt after the tool stop
    assert events.kinds().count("model_attempt") == 1


def test_a_tool_stop_ends_the_request_without_another_model_attempt(make_guard, events):
    model = recorded(
        events,
        [{"tool_calls": [{"name": "echo", "arguments": {"n": 1}}]}],
        repeat_last=True,
    )
    out = orch(make_guard(), model, [echo_tool(events)]).handle("loop")
    assert out.stop_reason is Limit.LOOP
    kinds = events.kinds()
    # 3 identical calls run; the 4th model turn asks for a 4th, which the guard stops
    assert kinds.count("model_attempt") == len(model.requests) == 4
    assert kinds[-1] == "after_model"  # the refused before_tool records nothing after it


def test_file_budget_stops_before_the_handler(make_guard, events):
    model = recorded(
        events,
        [{"tool_calls": [{"id": f"c{i}", "name": "render", "arguments": {"k": i}}]}
         for i in range(6)],
    )
    out = orch(make_guard(), model, [file_tool(events, files=4)]).handle("x")
    assert out.stop_reason is Limit.FILES
    assert events.kinds().count("handler") == 2  # 4 + 4 of 10; the third would make 12
    assert_guarded(events)


def test_cost_over_request_budget_stops(make_guard, events):
    model = recorded(
        events,
        [
            {"tool_calls": [{"name": "echo", "arguments": {"n": 1}}],
             "usage": {"output_tokens": 10, "cost_usd": 0.7}},
            {"tool_calls": [{"name": "echo", "arguments": {"n": 2}}],
             "usage": {"output_tokens": 10, "cost_usd": 0.7}},
            {"text": "never"},
        ],
    )
    out = orch(make_guard(), model, [echo_tool(events)]).handle("x")
    assert out.stop_reason is Limit.REQUEST_BUDGET and out.success is False
    assert len(model.requests) == 2
    assert out.done == ("Werkzeug echo",)


def test_missing_usage_counts_the_full_reservation(make_guard, events):
    """No usage reported -> the guard counts all money reserved (1.0), so the next call stops."""
    model = recorded(
        events,
        [{"tool_calls": [{"name": "echo", "arguments": {"n": 1}}]}, {"text": "x"}],
        default_usage=False,
    )
    out = orch(make_guard(), model, [echo_tool(events)]).handle("x")
    assert out.stop_reason is Limit.REQUEST_BUDGET and len(model.requests) == 1
    assert out.usage["cost_usd"] == pytest.approx(1.0)
    assert out.usage["output_tokens"] == 1000


def test_output_tokens_over_limit_stop(make_guard, events):
    model = recorded(events, [{"text": "long", "usage": {"output_tokens": 1001}}])
    out = orch(make_guard(), model).handle("x")
    assert out.stop_reason is Limit.OUTPUT_TOKENS and out.reply == ""


def test_timeout_inside_a_tool_stops_the_request(make_guard, events, clock):
    def slow(args):
        clock.t += 150
        from orchestrator.tools import ToolOutput

        return ToolOutput({}, files_written=0)

    from orchestrator.tools import Tool

    tool = Tool("slow", "", {"type": "object"}, slow)
    model = recorded(events, [{"tool_calls": [{"name": "slow", "arguments": {}}]}, {"text": "x"}])
    out = orch(make_guard(), model, [tool]).handle("x")
    assert out.stop_reason is Limit.TIMEOUT and len(model.requests) == 1


def test_warn_level_shortens_and_tells_the_user(make_guard, events):
    model = recorded(
        events,
        [{"tool_calls": [{"id": f"c{i}", "name": "echo", "arguments": {"n": i}}]}
         for i in range(4)] + [{"text": "kurz"}],
    )
    out = orch(make_guard(), model, [echo_tool(events)]).handle("x")
    assert out.success
    # 4 of 5 model calls = 0.8 -> warn before the 5th call
    assert WARN_SYSTEM_SUFFIX not in model.requests[3].system
    assert model.requests[4].system.endswith(WARN_SYSTEM_SUFFIX)
    assert out.warnings and out.warnings[0].startswith("Hinweis:")
    assert out.text_for_user.startswith("Hinweis:")


# --- model unreachable or misbehaving -----------------------------------------------------


def test_unreachable_model_is_a_clear_error_and_costs_nothing(make_guard, events):
    guard = make_guard()
    model = UnavailableModel("connection refused")
    out = orch(guard, model, [echo_tool(events)]).handle("drei Kicks")
    assert out.success is False and out.error == "model_unavailable"
    assert "nicht erreichbar" in out.message_de and "connection refused" in out.message_de
    assert "Kick-Engine" in out.message_de
    assert out.open == (ANSWER_ITEM,)
    assert guard.session_spent_usd == 0.0
    assert log_entries(guard)[-1]["outcome"] == "error"
    assert_guarded(events)


def test_unreachable_after_a_tool_keeps_what_finished(make_guard, events):
    model = recorded(
        events,
        [
            {"tool_calls": [{"name": "echo", "arguments": {"n": 1}}]},
            {"error": "unavailable", "detail": "timeout", "request_sent": True},
        ],
    )
    guard = make_guard()
    out = orch(guard, model, [echo_tool(events)]).handle("x")
    assert out.error == "model_unavailable"
    assert out.done == ("Werkzeug echo",) and out.open == (ANSWER_ITEM,)
    # a request that may have been sent counts its reservation (all money left: 1.0)
    assert guard.session_spent_usd == pytest.approx(1.0)


def test_engine_still_renders_when_the_model_is_unreachable(make_guard, events):
    from audio_engine.kick import render_kick
    from audio_engine.presets import load_preset

    out = orch(make_guard(), UnavailableModel("offline")).handle("x")
    assert out.error == "model_unavailable"
    audio, params = render_kick({**load_preset("centre"), "length_ms": 200})
    assert audio.size == round(200 * params["sample_rate"] / 1000) and audio.size > 0


def test_backend_limit_result_counts_its_usage(make_guard, events):
    model = recorded(
        events,
        [{"error": "limit", "subtype": "error_max_turns", "detail": "Reached max turns",
          "usage": {"output_tokens": 100, "cost_usd": 0.2}}],
    )
    guard = make_guard()
    out = orch(guard, model).handle("x")
    assert out.success is False and out.error == "model_limit"
    assert "error_max_turns" in out.message_de
    assert guard.session_spent_usd == pytest.approx(0.2)


def test_backend_budget_overshoot_becomes_a_guard_stop(make_guard, events):
    model = recorded(
        events,
        [{"error": "limit", "subtype": "error_max_budget_usd", "detail": "budget",
          "usage": {"output_tokens": 100, "cost_usd": 1.3}}],
    )
    out = orch(make_guard(), model).handle("x")
    assert out.success is False and out.stop_reason is Limit.REQUEST_BUDGET


def test_protocol_error_is_reported(make_guard, events):
    model = recorded(events, [{"error": "protocol", "detail": "bad json"}])
    out = orch(make_guard(), model).handle("x")
    assert out.error == "model_protocol" and "bad json" in out.message_de


@pytest.mark.parametrize(
    "bad",
    [
        "a string",
        None,
        ModelResponse(text=3),
        ModelResponse(tool_calls=[("echo", {})]),
        ModelResponse(tool_calls=("echo",)),
        ModelResponse(usage={"cost_usd": 0}),
    ],
)
def test_malformed_client_responses_do_not_crash(make_guard, events, bad):
    model = ScriptedModel(lambda i, r: bad, events)
    out = orch(make_guard(), model, [echo_tool(events)]).handle("x")
    assert out.success is False and out.error == "model_protocol"
    assert_guarded(events)


def test_client_bug_does_not_crash(make_guard, events):
    def boom(i, r):
        raise ZeroDivisionError

    out = orch(make_guard(), ScriptedModel(boom, events)).handle("x")
    assert out.error == "model_client_error" and "ZeroDivisionError" in out.message_de


def test_broken_estimator_falls_back_to_full_reservation(make_guard, events):
    def bad(_request):
        raise RuntimeError

    model = recorded(events, [{"text": "ok"}])
    guard = make_guard()
    out = orch(guard, model, estimate_cost_usd=bad).handle("x")
    assert out.success
    model_entries = [e for e in log_entries(guard) if e["kind"] == "model"]
    assert model_entries[0]["estimated_cost_usd"] == pytest.approx(1.0)


@pytest.mark.parametrize("value", [float("nan"), -1.0, True, "0.1"])
def test_invalid_estimates_fall_back_to_full_reservation(make_guard, events, value):
    guard = make_guard()
    out = orch(guard, recorded(events, [{"text": "ok"}]), estimate_cost_usd=lambda r: value
               ).handle("x")
    assert out.success
    assert [e for e in log_entries(guard) if e["kind"] == "model"][0][
        "estimated_cost_usd"] == pytest.approx(1.0)


def test_a_valid_estimate_is_used(make_guard, events):
    guard = make_guard()
    orch(guard, recorded(events, [{"text": "ok"}]), estimate_cost_usd=lambda r: 0.05).handle("x")
    assert [e for e in log_entries(guard) if e["kind"] == "model"][0][
        "estimated_cost_usd"] == pytest.approx(0.05)


# --- approval levels ----------------------------------------------------------------------


class Approver:
    def __init__(self, answer):
        self.answer = answer
        self.asked: list = []

    def confirm(self, tool, arguments):
        self.asked.append((tool.name, arguments))
        return self.answer


@pytest.mark.parametrize(
    ("approver", "ran"),
    [(None, False), (Approver(False), False), (Approver("yes"), False), (Approver(1), False),
     (Approver(True), True)],
)
def test_live_tools_need_an_explicit_yes(make_guard, events, approver, ran):
    model = recorded(
        events, [{"tool_calls": [{"name": "live_write", "arguments": {}}]}, {"text": "x"}]
    )
    out = orch(make_guard(), model, [live_tool(events)], approver=approver).handle("x")
    assert (("handler", "live_write") in events.items) == ran
    assert out.success == ran
    result = model.requests[1].messages[-1].results[0]
    assert result.is_error != ran
    if not ran:
        assert result.content["error"] == "declined"
        assert "Werkzeug live_write" in out.open
    if approver is not None:
        assert approver.asked == [("live_write", {})]
    assert_guarded(events)


def test_approver_that_raises_is_a_decline(make_guard, events):
    class Broken:
        def confirm(self, tool, arguments):
            raise OSError("terminal gone")

    model = recorded(
        events, [{"tool_calls": [{"name": "live_write", "arguments": {}}]}, {"text": "x"}]
    )
    out = orch(make_guard(), model, [live_tool(events)], approver=Broken()).handle("x")
    assert ("handler", "live_write") not in events.items
    assert model.requests[1].messages[-1].results[0].content["error"] == "declined"
    assert out.success is False


def test_live_write_budget_stops_before_the_handler(make_guard, events):
    """max_live_writes = 2, each call declares 1: the third call must not reach Live."""
    model = recorded(
        events,
        [{"tool_calls": [{"id": f"c{i}", "name": "live_write", "arguments": {}}]}
         for i in range(4)],
    )
    out = orch(make_guard(max_identical_tool_calls=10), model, [live_tool(events)],
               approver=Approver(True)).handle("x")
    assert out.stop_reason is Limit.LIVE_WRITES
    assert events.kinds().count("handler") == 2
    assert out.usage["live_writes"] == 2
    assert_guarded(events)


def test_routine_tools_are_not_asked(make_guard, events):
    approver = Approver(False)
    model = recorded(events, [{"tool_calls": [{"name": "render", "arguments": {}}]},
                              {"text": "x"}])
    out = orch(make_guard(), model, [file_tool(events)], approver=approver).handle("x")
    assert out.success and approver.asked == []


def test_invalid_arguments_to_a_live_tool_are_never_shown_for_approval(make_guard, events):
    approver = Approver(True)
    model = recorded(
        events, [{"tool_calls": [{"name": "live_write", "arguments": {"x": 1}}]}, {"text": "x"}]
    )
    orch(make_guard(), model, [live_tool(events)], approver=approver).handle("x")
    assert approver.asked == [] and ("handler", "live_write") not in events.items


# --- tool failures ------------------------------------------------------------------------


def test_tool_errors_go_back_to_the_model_and_count_declared_writes(make_guard, events):
    from orchestrator.tools import Tool, ToolError

    def fails(args):
        events.add("handler", "bad")
        raise ToolError("disk full")

    def bug(args):
        events.add("handler", "bug")
        raise KeyError("x")

    tools = [
        Tool("bad", "", {"type": "object"}, fails, max_files_written=3),
        Tool("bug", "", {"type": "object"}, bug),
    ]
    model = recorded(
        events,
        [{"tool_calls": [{"id": "1", "name": "bad", "arguments": {}},
                         {"id": "2", "name": "bug", "arguments": {}}]},
         {"text": "x"}],
    )
    guard = make_guard()
    out = orch(guard, model, tools).handle("x")
    results = model.requests[1].messages[-1].results
    assert [r.content["error"] for r in results] == ["tool_error", "internal_error"]
    assert results[0].content["message"] == "disk full"
    assert out.success is False and {"Werkzeug bad", "Werkzeug bug"} <= set(out.open)
    assert out.usage == {}  # not a guard stop; usage only on guard outcomes
    # a failed tool may have written part of its files: the declared 3 are counted
    tool_entries = [e for e in log_entries(guard) if e["kind"] == "tool"]
    assert [(e["tool"], e["ok"], e["files_written"]) for e in tool_entries] == [
        ("bad", False, 3), ("bug", False, 0)]
    assert_guarded(events)


# --- outcome invariants -------------------------------------------------------------------


def test_outcome_cannot_claim_success_without_the_guard():
    with pytest.raises(ValueError):
        Outcome(success=True, reply="", message_de="", done=(), open=())
    with pytest.raises(ValueError):
        Outcome(success=False, reply="", message_de="", done=(), open=())


@pytest.mark.parametrize("seed", range(4))
def test_property_success_only_when_the_guard_logged_success(make_guard, seed):
    """Random fake sessions: success is reported exactly when the guard logged a success."""
    rng = random.Random(7810 + seed)
    for _ in range(40):
        events = Events()
        turns = []
        for _t in range(rng.randint(1, 7)):
            r = rng.random()
            if r < 0.15:
                turns.append({"error": rng.choice(["unavailable", "protocol"])})
            elif r < 0.55:
                n = rng.choice([1, 1, 2, 500, -1])
                turns.append({"tool_calls": [{"name": rng.choice(["echo", "echo", "nope"]),
                                              "arguments": {"n": n}}],
                              "usage": {"output_tokens": rng.randint(0, 1100),
                                        "cost_usd": rng.choice([0.0, 0.1, 0.4])}})
            else:
                turns.append({"text": "fertig", "usage": {"output_tokens": 5}})
        guard = make_guard()
        guard.events = events
        model = recorded(events, turns, repeat_last=rng.random() < 0.3)
        out = orch(guard, model, [echo_tool(events)]).handle("x")
        end = log_entries(guard)[-1]
        assert end["kind"] == "request_end"
        assert out.success == (end["outcome"] == "success"), (turns, out)
        if out.stop_reason is not None:
            assert end["outcome"] == "stopped" and not out.success
        if not out.success:
            assert out.open, "a failed request must say what is still open"
        assert_guarded(events)


# --- SDK limits ---------------------------------------------------------------------------


@pytest.mark.parametrize("turns", [0, -1, None, True, 1.0, "3"])
def test_max_turns_zero_or_invalid_is_never_passed_on(turns):
    """Agent SDK: max_turns=0 means *no limit* (PR #79 note, V2): refuse it."""
    with pytest.raises(SdkLimitError):
        checked_sdk_limits({"max_turns": turns, "max_budget_usd": 0.1})


@pytest.mark.parametrize("budget", [0, 0.0, -0.1, None, True, float("nan")])
def test_zero_or_invalid_budget_is_never_passed_on(budget):
    with pytest.raises(SdkLimitError):
        checked_sdk_limits({"max_turns": 1, "max_budget_usd": budget})


def test_valid_sdk_limits_pass():
    assert checked_sdk_limits({"max_turns": 1, "max_budget_usd": 0.01}) == {
        "max_turns": 1, "max_budget_usd": 0.01}


@pytest.mark.parametrize("max_calls", [1, 2, 3, 8])
def test_property_last_allowed_call_gets_max_turns_one(make_guard, events, max_calls):
    model = ScriptedModel(varying_echo, events)
    out = orch(make_guard(max_model_calls=max_calls, max_tool_calls=20), model,
               [echo_tool(events)]).handle("x")
    assert out.stop_reason is Limit.MODEL_CALLS
    assert [r.sdk_limits["max_turns"] for r in model.requests] == list(range(max_calls, 0, -1))


class MidnightNow:
    """Wall clock that reads 23:59:59 for the first ``before`` calls, then 00:00:01 the next
    day. Injected into the guard to put local midnight between two guard steps."""

    def __init__(self, before: int) -> None:
        self.calls = 0
        self.before = before

    def __call__(self):
        from datetime import datetime, timedelta, timezone

        self.calls += 1
        day, hms = (28, (23, 59, 59)) if self.calls <= self.before else (29, (0, 0, 1))
        return datetime(2026, 10, day, *hms, tzinfo=timezone(timedelta(hours=1)))


def _guard_with_now(tmp_path, clock, events, now, **policy):
    from orch_helpers import SpyGuard, make_policy

    return SpyGuard(make_policy(**policy), log_path=tmp_path / "midnight.jsonl", clock=clock,
                    now=now, events=events)


def _midnight_run(tmp_path, clock, events, before):
    now = MidnightNow(before)
    folder = tmp_path / f"m{before}"
    folder.mkdir()
    guard = _guard_with_now(folder, clock, events, now, daily_budget_usd=0.5)
    spend = recorded(events, [{"text": "a", "usage": {"output_tokens": 1, "cost_usd": 0.5}}])
    first = orch(guard, spend).handle("x")
    model = recorded(events, [{"text": "b", "usage": {"output_tokens": 1, "cost_usd": 0.01}}])
    out = orch(guard, model).handle("y")
    return now, guard, first, model, out


def test_midnight_rollover_gives_the_client_the_budget_it_reserves_against(
    tmp_path, clock, events
):
    """Review of PR #89, finding 1: the old day's daily budget is used up (0.5 of 0.5). At
    local midnight a new request read sdk_limits from the old day (max_budget_usd 0.0) but
    reserved against the new day's fresh budget, so the client got a 0 budget and the user an
    "internal client error". Wherever midnight falls, the client must get a positive budget
    that matches what the guard reserved, and the request must succeed.

    A calibration run counts how often the guard reads the wall clock; midnight is then put
    before each of those reads once (every position distinct, none repeated)."""
    reads = _midnight_run(tmp_path, clock, events, 10**9)[0].calls
    assert reads >= 10, "too few clock reads - the sweep would prove little"
    for before in range(reads + 1):
        _now, guard, first, model, out = _midnight_run(tmp_path, clock, events, before)
        _check_midnight_case(before, guard, first, model, out)


def _check_midnight_case(before, guard, first, model, out):
    if not first.success:
        # midnight fell inside the first request; its spend is on the new day already
        assert first.stop_reason is not None or first.error is not None, before
        return
    assert out.error != "model_client_error", (before, out.message_de)
    if out.success:
        assert len(model.requests) == 1
        budget = model.requests[0].sdk_limits["max_budget_usd"]
        assert budget > 0
        entry = [e for e in log_entries(guard) if e["kind"] == "model"][-1]
        assert budget == pytest.approx(entry["estimated_cost_usd"])
    else:
        # still before midnight: the old day's budget is used up -> a clean guard stop
        assert out.stop_reason is Limit.DAILY_BUDGET and model.requests == []


def test_permit_without_limits_cannot_be_built():
    from guard import Level, ModelCallPermit

    with pytest.raises(TypeError):
        ModelCallPermit(1, "r", 100, 0.1, Level.OK)  # sdk_limits has no default


@pytest.mark.parametrize(
    "bad_limits",
    [{}, {"max_turns": 0, "max_budget_usd": 0.5}, {"max_turns": 2, "max_budget_usd": 0.0},
     {"max_budget_usd": 0.5}],
)
def test_a_permit_with_unusable_limits_never_reaches_the_client(make_guard, events, bad_limits):
    """Review round 2 of PR #89, finding 1: whatever the permit carries, the loop refuses to
    hand the client a missing or disabling limit; the request is not a success and the
    reserved call is settled at no cost."""
    import dataclasses

    guard = make_guard()
    real = guard.request

    def request(profile):
        req = real(profile)
        before = req.before_model_call

        def broken_before(**kwargs):
            return dataclasses.replace(before(**kwargs), sdk_limits=dict(bad_limits))

        req.before_model_call = broken_before
        return req

    guard.request = request
    model = recorded(events, [{"text": "ok"}])
    out = orch(guard, model).handle("x")
    assert model.requests == []
    assert out.success is False and out.error == "model_client_error"
    assert guard.session_spent_usd == 0.0
    assert log_entries(guard)[-1]["outcome"] == "error"


def test_permit_sdk_limits_include_the_call_and_match_the_reservation(make_guard):
    guard = make_guard(session_budget_usd=0.4)
    with guard.request("p") as req:
        p1 = req.before_model_call()
        assert p1.sdk_limits == {"max_turns": 5, "max_budget_usd": pytest.approx(0.4)}
        assert p1.reserved_cost_usd == pytest.approx(0.4)
        req.after_model_call(p1, ModelUsage(output_tokens=1, cost_usd=0.1))
        p2 = req.before_model_call(estimated_cost_usd=0.05)
        assert p2.sdk_limits == {"max_turns": 4, "max_budget_usd": pytest.approx(0.3)}
        req.after_model_call(p2, ModelUsage(output_tokens=1, cost_usd=0.05))


# --- review of PR #89: findings 3-8 ------------------------------------------------------


def test_stop_raised_inside_finish_is_never_a_success(make_guard, events, clock):
    """Finding 3: the timeout fires in ``finish()`` itself (after the last model call)."""

    guard = make_guard()
    # 99 s pass inside the model call (under the 100 s limit when after_model_call checks),
    # then 2 s more right before finish(): only finish() itself can see the timeout.
    guard.before_finish = lambda: setattr(clock, "t", clock.t + 2.0)

    def slow(i, request):
        clock.t += 99.0
        return ModelResponse(text="fertig", usage=USAGE)

    out = orch(guard, ScriptedModel(slow, events)).handle("x")
    assert ("finish_called", "") in events.items
    assert out.success is False and out.result.success is False
    assert out.stop_reason is Limit.TIMEOUT
    assert out.reply == ""  # the model's text is not presented as a finished answer
    assert log_entries(guard)[-1]["outcome"] == "stopped"


def test_unavailable_default_counts_the_reservation(make_guard, events):
    """Finding 4: ``ModelUnavailable`` without ``request_sent`` means "maybe sent" -> the
    guard counts what it reserved (1.0, all money left)."""
    from orchestrator.model_client import ModelUnavailable

    def down(i, r):
        raise ModelUnavailable("reset by peer")

    guard = make_guard()
    out = orch(guard, ScriptedModel(down, events)).handle("x")
    assert out.error == "model_unavailable"
    assert ModelUnavailable("x").request_sent is True
    assert guard.session_spent_usd == pytest.approx(1.0)


def test_client_gets_the_time_left_as_timeout(make_guard, events, clock):
    """Finding 5: ``timeout_s`` is the guard's remaining time, measured independently here."""
    def step(i, request):
        clock.t += 30.0
        if i < 2:
            return ModelResponse(tool_calls=(call("echo", {"n": i}, f"c{i}"),), usage=USAGE)
        return ModelResponse(text="ok", usage=USAGE)

    model = ScriptedModel(step, events)
    out = orch(make_guard(), model, [echo_tool(events)]).handle("x")
    assert out.success
    assert [r.timeout_s for r in model.requests] == pytest.approx([100.0, 70.0, 40.0])


def test_routine_tool_that_reports_a_live_write_is_stopped(make_guard, events):
    """Finding 8: a routine tool declares no Live writes; if it reports one anyway it ran
    without approval. The request stops and is never a success."""
    from orchestrator.tools import Tool, ToolOutput

    def sneaky(args):
        events.add("handler", "sneaky")
        return ToolOutput({"ok": True}, live_writes=1)

    tool = Tool("sneaky", "", {"type": "object"}, sneaky)
    model = recorded(events, [{"tool_calls": [{"name": "sneaky", "arguments": {}}]},
                              {"text": "alles gut"}])
    guard = make_guard()
    out = orch(guard, model, [tool]).handle("x")
    assert out.success is False and out.stop_reason is Limit.UNDECLARED_WRITE
    assert len(model.requests) == 1  # no further model call after the violation
    assert "Werkzeug sneaky" in out.open and "Werkzeug sneaky" not in out.done
    assert out.usage["live_writes"] == 1  # what it reported is counted
    assert "angekündigt" in out.message_de
    assert log_entries(guard)[-1]["outcome"] == "stopped"


@pytest.mark.parametrize(("declared", "reported", "stopped"),
                         [(2, 2, False), (2, 1, False), (2, 3, True), (0, 1, True)])
def test_files_beyond_the_declaration_stop(make_guard, events, declared, reported, stopped):
    from orchestrator.tools import Tool, ToolOutput

    tool = Tool("render", "", {"type": "object"},
                lambda a: ToolOutput({}, files_written=reported), max_files_written=declared)
    model = recorded(events, [{"tool_calls": [{"name": "render", "arguments": {}}]},
                              {"text": "x"}])
    out = orch(make_guard(), model, [tool]).handle("x")
    assert (out.stop_reason is Limit.UNDECLARED_WRITE) == stopped
    assert out.success is (not stopped)


def test_session_budget_left_is_passed_as_sdk_budget(make_guard, events):
    guard = make_guard(session_budget_usd=0.4)
    model = recorded(events, [{"text": "a", "usage": {"cost_usd": 0.1}}, {"text": "b"}])
    o = orch(guard, model)
    assert o.handle("1").success and o.handle("2").success
    assert model.requests[0].sdk_limits["max_budget_usd"] == pytest.approx(0.4)
    assert model.requests[1].sdk_limits["max_budget_usd"] == pytest.approx(0.3)


def test_unknown_profile_fails_at_construction(make_guard):
    from guard import UnknownProfileError

    with pytest.raises(UnknownProfileError):
        Orchestrator(make_guard(), UnavailableModel("x"), Toolbox(), profile="nope")


def test_default_profile_is_kick_generation(tmp_path):
    from guard import Guard

    o = Orchestrator(Guard(log_path=tmp_path / "u.jsonl"), UnavailableModel("x"), Toolbox())
    assert o.profile == "kick_generation"
    assert o.handle("x").error == "model_unavailable"


def test_echo_schema_is_what_the_tests_assume():
    assert ECHO_SCHEMA["properties"]["n"]["maximum"] == 100


def test_model_usage_type_is_reexported():
    assert ModelUsage(output_tokens=1).output_tokens == 1
