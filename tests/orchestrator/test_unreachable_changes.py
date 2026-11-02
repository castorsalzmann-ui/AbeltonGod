"""#176, round-1 review of PR #181: what the user is told about changes when a request ends
early (Claude unreachable, Ctrl+C, guard timeout).

"Es wurde nichts geändert." is a claim about the user's files and Live set. It must be absent
as soon as the guard counted a write, on every path that builds the sentence. The writes here
are Live writes (``live_tool``), the case the first round of tests did not cover (P1).
Expected texts are written here, not taken from the code.
"""

from __future__ import annotations

import io
import logging

import pytest
from orch_helpers import (  # noqa: F401 - *_fixture are pytest fixtures (see orch_helpers)
    ScriptedModel,
    call,
    clock_fixture,
    events_fixture,
    live_tool,
    make_guard_fixture,
)

from guard import Guard, Limit, ModelUsage
from orchestrator.chat import main
from orchestrator.loop import Orchestrator
from orchestrator.model_client import ModelResponse, ModelUnreachable
from orchestrator.tools import Approval, Tool, Toolbox

USAGE = ModelUsage(output_tokens=10, cost_usd=0.01)
NOTHING = "nichts geändert"
LIVE = "Änderung(en) am Live-Set"


class Yes:
    def confirm(self, tool, arguments, plan):
        return True


def write_then(second):
    """Model: first answer asks for one Live write, the second call does ``second(i, req)``."""

    def script(i, request):
        if i == 0:
            return ModelResponse(text="", tool_calls=(call("live_write", {}),), usage=USAGE)
        return second(i, request)

    return script


def orch(guard, script, events, tools=None):
    box = Toolbox(tools if tools is not None else [live_tool(events)])
    return Orchestrator(guard, ScriptedModel(script, events), box, profile="p", approver=Yes())


def unreachable(i, request):
    raise ModelUnreachable("no connection", request_sent=False)


def ctrl_c(i, request):
    raise KeyboardInterrupt


def interrupting_live_tool(events):
    """A Live write that is interrupted by Ctrl+C inside the handler (after its work)."""

    def handler(args):
        events.add("handler", "live_write")
        raise KeyboardInterrupt

    return Tool("live_write", "Change the Live set.",
                {"type": "object", "properties": {}, "additionalProperties": False},
                handler, approval=Approval.CONFIRM, max_live_writes=1)


def test_unreachable_after_a_live_write_does_not_say_nothing_changed(make_guard, events):
    out = orch(make_guard(), write_then(unreachable), events).handle("x")
    assert out.success is False and out.error == "model_unreachable"
    assert NOTHING not in out.message_de
    assert "Bis dahin erledigt: 1 Änderung(en) am Live-Set." in out.message_de


def test_ctrl_c_in_the_next_model_call_after_a_live_write(make_guard, events):
    out = orch(make_guard(), write_then(ctrl_c), events).handle("x")
    assert out.success is False and out.error == "interrupted"
    assert NOTHING not in out.message_de and LIVE in out.message_de


def test_ctrl_c_inside_the_live_handler_says_at_most(make_guard, events):
    """The guard settles the in-flight write at its declared maximum: the text must not claim
    it as done (P5)."""
    tools = [interrupting_live_tool(events)]
    out = orch(make_guard(), write_then(unreachable), events, tools).handle("x")
    assert out.success is False and out.error == "interrupted"
    assert NOTHING not in out.message_de
    assert "Möglicherweise schon geändert: höchstens 1 Änderung(en) am Live-Set." in out.message_de
    assert "erledigt" not in out.message_de


def test_guard_timeout_after_a_live_write_does_not_say_nothing_changed(make_guard, events,
                                                                       clock):
    def late(i, request):
        clock.t += 150  # TEST_POLICY timeout_s = 100
        raise ModelUnreachable("no answer", waited_s=150)

    out = orch(make_guard(), write_then(late), events).handle("x")
    assert out.success is False and out.error == "model_unreachable"
    assert out.stop_reason is Limit.TIMEOUT
    assert NOTHING not in out.message_de
    assert "Bis dahin erledigt: 1 Änderung(en) am Live-Set." in out.message_de


@pytest.mark.parametrize("second", [unreachable, ctrl_c], ids=["unreachable", "ctrl-c"])
def test_without_a_write_it_says_nothing_changed(make_guard, events, second):
    """The other half: with no write at all the sentence is there."""
    out = orch(make_guard(), lambda i, r: second(i, r), events, tools=[]).handle("x")
    assert out.success is False and "Es wurde nichts geändert." in out.message_de


# --- P4: a second Ctrl+C while the session closes ------------------------------------------


def _reader(lines):
    it = iter(lines)

    def read(prompt):
        try:
            return next(it)
        except StopIteration:
            raise EOFError from None

    return read


def test_second_ctrl_c_during_the_session_close_does_not_end_the_chat(tmp_path):
    class Model:
        calls = 0
        closes = 0

        def complete(self, request):
            Model.calls += 1
            if Model.calls == 1:
                raise KeyboardInterrupt
            return ModelResponse(text="Wieder da")

        def end_request(self):
            Model.closes += 1
            if Model.closes == 1:
                raise KeyboardInterrupt  # the user presses Ctrl+C again while it closes

    out = io.StringIO()
    try:
        code = main([], read=_reader(["Hallo", "noch mal", "exit"]), out=out,
                    guard=Guard(log_path=tmp_path / "u.jsonl"), model=Model())
    except KeyboardInterrupt:  # a plain failure, not an aborted test session
        pytest.fail("a second Ctrl+C during the close escaped the chat")
    text = out.getvalue()
    assert code == 0 and "Abgebrochen (Strg+C)" in text and "Wieder da" in text


# --- P3: no English SDK log line in the chat ------------------------------------------------


def test_chat_silences_the_sdk_error_log(tmp_path, caplog, request):
    sdk_log = logging.getLogger("claude_agent_sdk._internal.query")
    root = logging.getLogger("claude_agent_sdk")
    # #185: do not read the level the logger happens to have (an earlier test under xdist may
    # have left it at CRITICAL, which would hide a missing restore); set a known one
    request.addfinalizer(lambda root=root, level=root.level: root.setLevel(level))
    root.setLevel(logging.WARNING)
    before = logging.WARNING

    class Model:
        def complete(self, request):
            # what the SDK logs when the CLI it reads from was killed
            sdk_log.error("Fatal error in message reader: Command failed with exit code -9")
            raise ModelUnreachable("no connection", request_sent=False)

    caplog.set_level(logging.DEBUG)
    out = io.StringIO()
    main([], read=_reader(["Hallo", "exit"]), out=out,
         guard=Guard(log_path=tmp_path / "u.jsonl"), model=Model())
    assert "nicht erreichbar" in out.getvalue()
    assert [r.message for r in caplog.records if r.name.startswith("claude_agent_sdk")] == []
    assert root.level == before  # restored after the chat


def test_the_waiting_line_does_not_promise_ctrl_c_at_the_confirm_question(tmp_path):
    class Model:
        def complete(self, request):
            return ModelResponse(text="ok")

    out = io.StringIO()
    main([], read=_reader(["Hallo", "exit"]), out=out,
         guard=Guard(log_path=tmp_path / "u.jsonl"), model=Model())
    text = out.getvalue()
    assert "Strg+C bricht die Anfrage ab." in text
    assert 'Bei der Frage "Ausführen?" heißt Strg+C: nein.' in text
