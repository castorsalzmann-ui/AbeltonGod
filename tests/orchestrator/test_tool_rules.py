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
        with pytest.raises(GuardStop) as stop:  # 8 used, 4 more would be 12 > 10
            box.run(req, ToolCall("c", "t", {"n": 4}), None)
    assert stop.value.reason is Limit.FILES and len(seen) == 2
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
                 turn_started=ticks.t - CONFIRM_WINDOW_S - 1, still_waiting=lambda cid: False)
    assert bool(ran) == routine
    if not routine:
        assert result.content["error"] == "too_late"


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


# --- system prompt per request ----------------------------------------------------------------


def test_context_is_added_once_per_request_and_failures_are_ignored(make_guard):
    from orchestrator.fake_model import FakeModel

    for context, expected_tail in ((lambda: "Kicks: kick-1", "\n\nKicks: kick-1"),
                                   (lambda: 1 / 0, ""), (lambda: "   ", ""), (lambda: 7, "")):
        model = FakeModel([{"text": "a"}])
        Orchestrator(make_guard(), model, Toolbox(), profile="p", context=context).handle("x")
        assert model.requests[0].system == (
            DEFAULT_SYSTEM_PROMPT + "\n\n" + tools_sentence(()) + expected_tail)
