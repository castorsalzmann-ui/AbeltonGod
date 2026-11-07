"""#491: ``Orchestrator.cancel`` (the GUI's cancel button) stops a request at its next guard
step: before the next model call or the next tool call. Fake model only, no Claude call."""

from __future__ import annotations

import json

from orch_helpers import (  # noqa: F401 - *_fixture are pytest fixtures (see orch_helpers)
    clock_fixture,
    events_fixture,
    make_guard_fixture,
)

from orchestrator.fake_model import FakeModel
from orchestrator.loop import Orchestrator
from orchestrator.tools import Tool, Toolbox, ToolOutput

USAGE = {"output_tokens": 10, "cost_usd": 0.01}


def log_outcomes(guard) -> list[str]:
    lines = guard._log.path.read_text("utf-8").splitlines()
    return [json.loads(x).get("outcome") for x in lines if json.loads(x)["kind"] == "request_end"]


class CancelAfter(FakeModel):
    """Calls ``orch.cancel()`` while its ``n``-th answer is on its way (a press during a
    running Claude call)."""

    def __init__(self, turns, n):
        super().__init__(turns)
        self.n = n
        self.orch = None

    def complete(self, request):
        response = super().complete(request)
        if len(self.requests) == self.n:
            self.orch.cancel()
        return response


def build(guard, model, ran):
    def tool(args):
        ran.append(args)
        return ToolOutput({"ok": True}, files_written=0, live_writes=0)

    box = Toolbox([Tool("t", "", {"type": "object"}, tool)])
    o = Orchestrator(guard, model, box, profile="p")
    model.orch = o
    return o


def test_cancel_during_a_model_call_runs_no_tool_and_is_not_a_success(make_guard):
    ran: list = []
    model = CancelAfter([{"tool_calls": [{"id": "1", "name": "t", "arguments": {}},
                                         {"id": "2", "name": "t", "arguments": {}}],
                          "usage": USAGE},
                         {"text": "done", "usage": USAGE}], n=1)
    guard = make_guard()
    out = build(guard, model, ran).handle("go")
    assert out.success is False and out.error == "cancelled"
    assert ran == [] and len(model.requests) == 1
    assert out.message_de == "Abgebrochen (Knopf Abbrechen). Es wurde nichts geändert."
    assert log_outcomes(guard) == ["error"]  # the guard never logs it as a success


def test_cancel_after_the_tools_stops_before_the_next_model_call(make_guard):
    ran: list = []
    model = CancelAfter([{"tool_calls": [{"id": "1", "name": "t", "arguments": {}}],
                          "usage": USAGE},
                         {"text": "done", "usage": USAGE}], n=1)
    o = build(make_guard(), model, ran)
    # cancel arrives after the first tool ran: patch the tool to press it
    original = o.toolbox.run

    def run_then_cancel(*a, **kw):
        result = original(*a, **kw)
        o.cancel()
        return result

    model.n = 0  # no press from the model this time
    o.toolbox.run = run_then_cancel
    out = o.handle("go")
    assert out.error == "cancelled" and len(ran) == 1 and len(model.requests) == 1


def test_a_press_during_the_final_answer_keeps_it_and_is_cleared_afterwards(make_guard):
    """No step follows the final answer, so it stands; the flag must not stop the next one."""
    ran: list = []
    model = CancelAfter([{"text": "a", "usage": USAGE}, {"text": "b", "usage": USAGE}], n=1)
    o = build(make_guard(), model, ran)
    assert o.handle("1").success
    second = o.handle("2")
    assert second.success and second.reply == "b"
