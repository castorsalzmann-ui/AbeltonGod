"""#148 rules in ``Toolbox.run`` and the SDK client that the kick tools rely on: per-call file
declarations, ToolError write counts, the plan step, the deadline re-check, the confirmation
window, ``tool_call_pending`` and the per-request system prompt."""

from __future__ import annotations

import pytest
from fake_cli import PREFIX, FakeCLIFactory
from orch_helpers import (  # noqa: F401 - *_fixture are pytest fixtures (see orch_helpers)
    FakeClock,
    clock_fixture,
    events_fixture,
    make_guard_fixture,
)
from test_sdk_client import make_client, no_real_cli  # noqa: F401

from guard import GuardStop, Limit
from orchestrator.loop import DEFAULT_SYSTEM_PROMPT, Orchestrator, tools_sentence
from orchestrator.model_client import ToolCall
from orchestrator.tools import (
    CONFIRM_WINDOW_S,
    Approval,
    Plan,
    Tool,
    Toolbox,
    ToolError,
    ToolOutput,
)

OBJ = {"type": "object", "properties": {"n": {"type": "integer"}}, "additionalProperties": False}


@pytest.fixture(name="clients")
def clients_fixture():
    made = []
    yield made
    for c in made:
        c.close()


class Yes:
    def __init__(self, during=None):
        self.during = during
        self.plans = []

    def confirm(self, tool, arguments, plan):
        self.plans.append(plan)
        if self.during:
            self.during()
        return True


def run(guard, box, args, approver=None, name="t", **kw):
    with guard.request("p") as req:
        return box.run(req, ToolCall("c1", name, args), approver, **kw)


def log_tools(guard):
    import json

    lines = guard._log.path.read_text("utf-8").splitlines()
    return [e for e in map(json.loads, lines) if e.get("kind") == "tool"]


# --- per-call declarations and reported writes -------------------------------------------


def test_files_for_sets_the_reservation(make_guard):
    seen = []

    def handler(args):
        seen.append(args)
        return ToolOutput({}, files_written=args["n"])

    tool = Tool("t", "", OBJ, handler, max_files_written=8, files_for=lambda a: a["n"])
    guard = make_guard(max_files_written=10)
    box = Toolbox([tool])
    with guard.request("p") as req:
        box.run(req, ToolCall("a", "t", {"n": 4}), None)
        box.run(req, ToolCall("b", "t", {"n": 4}), None)
        third = box.run(req, ToolCall("c", "t", {"n": 4}), None)  # 8 used, 4 more > 10
        assert req.files_left() == 2
        fourth = box.run(req, ToolCall("d", "t", {"n": 2}), None)  # exactly fits
        assert req.files_left() == 0
    assert third.content["error"] == "file_budget" and len(seen) == 3
    assert not fourth.is_error
    # with the static maximum (8) the second call would already have been stopped
    assert Tool("u", "", OBJ, handler, max_files_written=8).declared_files({"n": 4}) == 8


def test_more_files_than_this_call_declared_stops(make_guard):
    tool = Tool("t", "", OBJ, lambda a: ToolOutput({}, files_written=3), max_files_written=8,
                files_for=lambda a: 2)
    with pytest.raises(GuardStop) as stop:
        run(make_guard(), Toolbox([tool]), {"n": 1})
    assert stop.value.reason is Limit.UNDECLARED_WRITE


@pytest.mark.parametrize(("files", "live", "counted_files", "counted_live", "stops"), [
    (0, 0, 0, 0, False), (1, 0, 1, 0, False), (None, None, 2, 1, False),
    (3, 0, 3, 0, True), (0, 2, 0, 2, True)])
def test_tool_error_reports_what_really_happened(make_guard, files, live, counted_files,
                                                 counted_live, stops):
    def handler(args):
        raise ToolError("partly done", files_written=files, live_writes=live,
                        details={"live": "unknown", "error": "spoofed", "message": "x"})

    tool = Tool("t", "", OBJ, handler, approval=Approval.CONFIRM, max_files_written=2,
                max_live_writes=1)
    guard = make_guard(max_live_writes=5)
    if stops:
        with pytest.raises(GuardStop) as stop:
            run(guard, Toolbox([tool]), {"n": 1}, Yes())
        assert stop.value.reason is Limit.UNDECLARED_WRITE
    else:
        result = run(guard, Toolbox([tool]), {"n": 1}, Yes())
        assert result.content == {"error": "tool_error", "message": "partly done",
                                  "live": "unknown"}  # details cannot replace error/message
    [entry] = log_tools(guard)
    assert (entry["files_written"], entry["live_writes"]) == (counted_files, counted_live)


# --- plan step ------------------------------------------------------------------------------


def _confirm_tool(prepare, events):
    def handler(args, plan):
        events.add("handler", "t")
        return ToolOutput({"plan": plan.summary}, live_writes=1)

    return Tool("t", "", OBJ, handler, approval=Approval.CONFIRM, max_live_writes=1,
                prepare=prepare)


def test_plan_reaches_the_approver_and_the_handler(make_guard, events):
    yes = Yes()
    tool = _confirm_tool(lambda a: Plan({"slot": a["n"]}, data=object()), events)
    result = run(make_guard(), Toolbox([tool]), {"n": 2}, yes)
    assert result.content == {"plan": {"slot": 2}}
    assert yes.plans[0].summary == {"slot": 2}


@pytest.mark.parametrize("prepare", [
    lambda a: {"slot": 1},  # not a Plan
    lambda a: 1 / 0,
    "not callable",
])
def test_broken_plan_step_runs_nothing(make_guard, events, prepare):
    yes = Yes()
    guard = make_guard()
    result = run(guard, Toolbox([_confirm_tool(prepare, events)]), {"n": 1}, yes)
    assert result.content["error"] == "internal_error"
    assert yes.plans == [] and ("handler", "t") not in events.items
    assert log_tools(guard)[-1]["live_writes"] == 0


def test_plan_refusal_asks_nobody(make_guard, events):
    def refuse(args):
        raise ToolError("slot taken", details={"live": "unchanged"})

    yes = Yes()
    result = run(make_guard(), Toolbox([_confirm_tool(refuse, events)]), {"n": 1}, yes)
    assert result.content == {"error": "refused", "message": "slot taken", "live": "unchanged"}
    assert yes.plans == []


def test_invalid_arguments_never_reach_the_plan_step(make_guard, events):
    calls = []
    tool = _confirm_tool(lambda a: calls.append(a) or Plan({}), events)
    result = run(make_guard(), Toolbox([tool]), {"n": "1"}, Yes())
    assert result.content["error"] == "invalid_arguments" and calls == []


# --- after the yes ----------------------------------------------------------------------------


def test_check_deadline(make_guard, clock):
    guard = make_guard(timeout_s=10)
    with guard.request("p") as req:
        req.check_deadline()
        clock.t += 9.9
        req.check_deadline()
        clock.t += 0.1
        with pytest.raises(GuardStop) as stop:
            req.check_deadline("Werkzeug x")
        assert stop.value.reason is Limit.TIMEOUT and "Werkzeug x" in stop.value.open
        with pytest.raises(GuardStop):  # sticky
            req.check_deadline()


def test_check_deadline_raises_an_earlier_stop(make_guard):
    guard = make_guard()
    with guard.request("p") as req:
        with pytest.raises(GuardStop):
            req.stop_request(Limit.LOOP, "x")
        with pytest.raises(GuardStop) as stop:
            req.check_deadline()
        assert stop.value.reason is Limit.LOOP


@pytest.mark.parametrize("routine", [True, False])
def test_window_and_backend_check_apply_to_confirm_tools_only(make_guard, events, routine):
    ticks = FakeClock()
    ran = []

    def handler(args):
        ran.append(args)
        return ToolOutput({}, live_writes=0 if routine else 1)

    kw = {} if routine else {"approval": Approval.CONFIRM, "max_live_writes": 1}
    tool = Tool("t", "", OBJ, handler, **kw)
    result = run(make_guard(), Toolbox([tool], clock=ticks), {"n": 1},
                 Yes(during=lambda: setattr(ticks, "t", ticks.t + 1000)),
                 turn_started=ticks.t - 1, still_waiting=lambda cid: False)
    assert bool(ran) == routine
    if not routine:
        # the question fit the window; the yes came too late (#207: the post-Yes path, not the
        # pre-question refusal), and the text says the confirmation was given, not "nobody asked"
        assert result.content["error"] == "too_late"
        assert "the confirmation came 1001 s after" in result.content["message"]
        assert "nobody was asked" not in result.content["message"]


def _window_case(make_guard, events, elapsed):
    ticks = FakeClock()
    yes = Yes()
    tool = _confirm_tool(lambda a: Plan({"ok": 1}), events)
    result = run(make_guard(), Toolbox([tool], clock=ticks), {"n": 1}, yes,
                 turn_started=ticks.t - elapsed)
    return result, yes


@pytest.mark.parametrize("elapsed", [0.0, 19.9, 20.0, 20.001, 20.1, 21.0, 600.0, 1e9])
def test_user_is_asked_only_while_the_confirmation_window_fits(make_guard, events, elapsed):
    """#170: the window is checked before the question, not only after the yes. 20.0 s
    exactly still fits (the check is `<=`, as after the yes)."""
    result, yes = _window_case(make_guard, events, elapsed)
    fits = elapsed <= CONFIRM_WINDOW_S
    assert bool(yes.plans) == fits
    assert (("handler", "t") in events.items) == fits
    if fits:
        assert result.content == {"plan": {"ok": 1}}
    else:
        assert result.content["error"] == "too_late"
        assert "nobody was asked" in result.content["message"]
        assert "nothing was sent to Live" in result.content["message"]


def test_window_before_the_question_over_random_elapsed_times(make_guard, events):
    import random

    rng = random.Random(170)
    for _ in range(60):
        elapsed = rng.choice([rng.uniform(0, 40), 20.0 + rng.choice([-1, 1]) * 1e-6])
        events.items.clear()
        result, yes = _window_case(make_guard, events, elapsed)
        assert bool(yes.plans) == (elapsed <= CONFIRM_WINDOW_S), elapsed
        assert result.is_error == (elapsed > CONFIRM_WINDOW_S), elapsed


def test_window_used_up_by_a_nan_clock_asks_nobody(make_guard, events):
    ticks = FakeClock()
    yes = Yes()
    tool = _confirm_tool(lambda a: Plan({}), events)
    result = run(make_guard(), Toolbox([tool], clock=ticks), {"n": 1}, yes,
                 turn_started=float("nan"))
    assert result.content["error"] == "too_late" and yes.plans == []


def test_late_refusal_before_the_question_is_settled_in_the_guard(make_guard, events):
    guard = make_guard()
    ticks = FakeClock()
    tool = _confirm_tool(lambda a: Plan({}), events)
    run(guard, Toolbox([tool], clock=ticks), {"n": 1}, Yes(), turn_started=ticks.t - 99)
    last = log_tools(guard)[-1]
    assert last["live_writes"] == 0 and last["ok"] is False


@pytest.mark.parametrize("answer", [False, None, "yes", RuntimeError("x")])
def test_confirm_tool_not_presented_is_refused_before_anything(make_guard, events, answer):
    asked_presented = []

    def presented(call_id, wait_s):
        asked_presented.append((call_id, wait_s))
        if isinstance(answer, Exception):
            raise answer
        return answer

    yes = Yes()
    plans = []
    tool = _confirm_tool(lambda a: plans.append(a) or Plan({}), events)
    guard = make_guard()
    result = run(guard, Toolbox([tool]), {"n": 1}, yes, presented=presented)
    assert result.content["error"] == "not_presented"
    assert asked_presented == [("c1", 2.0)]
    assert plans == [] and yes.plans == [] and ("handler", "t") not in events.items
    assert log_tools(guard)[-1]["live_writes"] == 0


def test_presented_is_not_asked_for_routine_tools_and_true_goes_on(make_guard, events):
    asked = []
    routine = Tool("t", "", OBJ, lambda a: ToolOutput({}))
    run(make_guard(), Toolbox([routine]), {"n": 1}, None,
        presented=lambda c, w: asked.append(c) or False)
    assert asked == []
    tool = _confirm_tool(lambda a: Plan({"ok": 1}), events)
    result = run(make_guard(), Toolbox([tool]), {"n": 1}, Yes(), presented=lambda c, w: True)
    assert result.content == {"plan": {"ok": 1}}


def test_files_left(make_guard):
    guard = make_guard(max_files_written=10)
    tool = Tool("t", "", OBJ, lambda a: ToolOutput({}, files_written=3), max_files_written=3)
    with guard.request("p") as req:
        assert req.files_left() == 10
        Toolbox([tool]).run(req, ToolCall("a", "t", {"n": 1}), None)
        assert req.files_left() == 7


# --- tool_call_pending (SDK client) ---------------------------------------------------------


def test_tool_call_pending_is_true_only_while_the_cli_waits(make_guard, clients):
    factory = FakeCLIFactory({"turns": [
        {"tool_uses": [{"id": "t1", "name": PREFIX + "t", "input": {"n": 1}}]},
        {"text": "fertig"}]})
    client = make_client(clients, factory)
    seen = []

    def handler(args):
        seen.append((client.tool_call_pending("t1"), client.tool_call_pending("other")))
        return ToolOutput({})

    out = Orchestrator(make_guard(), client, Toolbox([Tool("t", "", OBJ, handler)]),
                       profile="p").handle("x")
    assert out.success
    assert seen == [(True, False)]
    assert client.tool_call_pending("t1") is False  # session over
    client.close()
    assert client.tool_call_pending("t1") is False


def test_tool_call_pending_is_false_after_a_violation(make_guard, clients):
    factory = FakeCLIFactory({"turns": [
        {"tool_uses": [{"id": "t1", "name": PREFIX + "t", "input": {"n": 1}}]},
        {"text": "x"}]})
    client = make_client(clients, factory)
    seen = []

    def handler(args):
        client._session.violation = "test"
        seen.append(client.tool_call_pending("t1"))
        return ToolOutput({})

    Orchestrator(make_guard(), client, Toolbox([Tool("t", "", OBJ, handler)]),
                 profile="p").handle("x")
    assert seen == [False]


def _presented_probe(make_guard, clients, setup, wait_s=0.2):
    """Ask ``tool_call_presented`` for t1, which the CLI really presented, from inside t1's
    own handler, after ``setup(client)`` changed the session."""
    factory = FakeCLIFactory({"turns": [
        {"tool_uses": [{"id": "t1", "name": PREFIX + "t", "input": {"n": 1}}]},
        {"text": "x"}]})
    client = make_client(clients, factory)
    seen = []

    def handler(args):
        setup(client)
        seen.append(client.tool_call_presented("t1", wait_s))
        return ToolOutput({})

    Orchestrator(make_guard(), client, Toolbox([Tool("t", "", OBJ, handler)]),
                 profile="p").handle("x")
    return seen


def test_tool_call_presented_is_true_for_a_presented_call(make_guard, clients):
    assert _presented_probe(make_guard, clients, lambda c: None) == [True]


@pytest.mark.parametrize("attribute", ["violation", "stream_ended", "closed"])
def test_tool_call_presented_is_false_for_a_violated_or_ended_session(
        make_guard, clients, attribute):
    """#170 (mutant Q4): a presented call is no longer presented once the session is violated,
    its stream ended or it is closed."""
    def setup(client):
        setattr(client._session, attribute, "test" if attribute == "violation" else True)

    assert _presented_probe(make_guard, clients, setup) == [False]


def test_tool_call_presented_is_false_after_the_hook_was_answered(make_guard, clients):
    def setup(client):
        client._session.hooks["t1"].future.set_result({})

    assert _presented_probe(make_guard, clients, setup) == [False]


@pytest.mark.parametrize("wait_s", [0.0, 0.3, 0.7])
def test_tool_call_presented_waits_no_longer_than_asked(make_guard, clients, wait_s):
    """#170 (mutant Q13: a wait that ignores ``wait_s``): an unpresented call is waited for
    about ``wait_s`` and not much longer."""
    import time

    factory = FakeCLIFactory({"turns": [
        {"tool_uses": [{"id": "t1", "name": PREFIX + "t", "input": {"n": 1}}]},
        {"text": "x"}]})
    client = make_client(clients, factory)
    took = []

    def handler(args):
        start = time.monotonic()
        got = client.tool_call_presented("never-presented", wait_s)
        took.append((got, time.monotonic() - start))
        return ToolOutput({})

    Orchestrator(make_guard(), client, Toolbox([Tool("t", "", OBJ, handler)]),
                 profile="p").handle("x")
    [(got, seconds)] = took
    assert got is False
    assert wait_s - 0.05 <= seconds <= wait_s + 0.6, seconds


def test_the_toolbox_asks_the_backend_for_at_most_the_pinned_present_wait():
    from orchestrator.tools import PRESENT_WAIT_S

    assert PRESENT_WAIT_S == 2.0  # the user decision of PR #168; change it on purpose only


# --- system prompt per request ----------------------------------------------------------------


def test_context_is_added_once_per_request_and_failures_are_ignored(make_guard):
    from orchestrator.fake_model import FakeModel

    for context, expected_tail in ((lambda: "Kicks: kick-1", "\n\nKicks: kick-1"),
                                   (lambda: 1 / 0, ""), (lambda: "   ", ""), (lambda: 7, "")):
        model = FakeModel([{"text": "a"}])
        Orchestrator(make_guard(), model, Toolbox(), profile="p", context=context).handle("x")
        assert model.requests[0].system == (
            DEFAULT_SYSTEM_PROMPT + "\n\n" + tools_sentence(()) + expected_tail)
