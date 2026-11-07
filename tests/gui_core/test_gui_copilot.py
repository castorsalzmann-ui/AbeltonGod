"""#491: the GUI copilot service (``gui_core.chat``) without Qt: the terminal chat's tools on
the GUI output folder, the GUI approver (yes / no / timeout / cancel), guard limits, chat
memory, the budget line. Fake model + fake AbletonOSC server (tests/bridge): CI only, nothing
here is evidence for Claude or Live behaviour."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from chat_helpers import (
    CLAP,
    CREATE,
    guard_for,
    make_chat,
    make_fake,
    turn_generate,
    turn_import,
    turn_text,
    wavs,
    writes,
)

from guard import Limit
from gui_core.chat import (
    CONFIRM_TIMEOUT_S,
    LOGIN_HINT,
    ChatSession,
    ConfirmRequest,
    GuiApprover,
    budget_text,
    output_folder_check,
)
from library.project import ProjectReason
from orchestrator.fake_model import FakeModel
from orchestrator.kick_tools import sha256_file

DECIDE_S = 5.0  # a test that expects an answer never waits less (#180)


@pytest.fixture
def fake():
    server = make_fake()
    yield server
    server.close()


class Answer:
    """An approver that answers ``yes`` and records what it was shown."""

    def __init__(self, yes):
        self.yes = yes
        self.asked = []

    def confirm(self, tool, arguments, plan=None):
        self.asked.append((tool.name, plan.summary if plan else None))
        return self.yes


def gui_approver(answer, timeout_s=DECIDE_S, delay_s=0.0):
    """A ``GuiApprover`` whose "GUI" answers from another thread after ``delay_s``
    (``answer`` None: never answers)."""
    shown: list[ConfirmRequest] = []

    def post(request):
        shown.append(request)
        if answer is None:
            return

        def later():
            time.sleep(delay_s)
            request.answer(answer)

        threading.Thread(target=later, daemon=True).start()

    return GuiApprover(post, timeout_s=timeout_s), shown


# --- tools and folder ------------------------------------------------------------------------


def test_generate_writes_into_the_output_folder_and_reports_the_files(tmp_path):
    session, model = make_chat(tmp_path, [turn_generate(), turn_text("Ein Clap ist fertig.")])
    reply = session.ask("Mach einen kurzen Clap")
    assert reply.success, reply.text
    made = wavs(tmp_path / "out")
    assert len(made) == 1 and made[0].parent == tmp_path / "out" / "Samples" / "Drums" / "Claps"
    assert reply.files == tuple(made)
    meta = json.loads(made[0].with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["category"] == "clap" and meta["parameters"]["preset"] == "short"
    assert "2 von 8 Modellaufrufen" in reply.budget and "2 von 12 Dateien" in reply.budget
    st = session.tools_state()
    assert st.folder == tmp_path / "out" and "generate_sample" in st.names


def test_tools_state_creates_no_folder(tmp_path):
    session, _ = make_chat(tmp_path, [turn_text()])
    st = session.tools_state()
    assert not (tmp_path / "out").exists() and st.names == ()
    assert "bei der ersten Frage" in st.note and str(tmp_path / "out") in st.note


def test_a_refused_output_folder_leaves_only_the_plan_tools(tmp_path):
    (tmp_path / "Backup").mkdir()
    session, model = make_chat(tmp_path, [turn_text("Nur planen.")], out=tmp_path / "Backup")
    assert session.ask("Hallo").success
    assert [t.name for t in model.requests[0].tools] == ["plan_arrangement"]
    st = session.tools_state()
    assert st.folder is None and "Backup" in st.note and "Nur Planen" in st.note


def _refused_note(tmp_path, out, roots=()):
    session = ChatSession(tmp_path / ".env", model=FakeModel([turn_text("Nur planen.")]),
                          guard=guard_for(tmp_path), output_dir=out,
                          session_options={"refused_roots": roots})
    assert session.ask("Hallo").success
    st = session.tools_state()
    assert st.folder is None and "Nur Planen" in st.note
    assert "Projektordner" not in st.note and "Ausgabeordner" in st.note
    return st.note


def test_a_refused_output_folder_is_never_created(tmp_path, monkeypatch):
    """#493 review: check first, create only after the check passed."""
    monkeypatch.chdir(tmp_path)
    note = _refused_note(tmp_path, Path("relout/x"))
    assert not (tmp_path / "relout").exists() and "voller Pfad" in note
    inside = tmp_path / "checkout" / "a" / "out"
    (tmp_path / "checkout").mkdir()
    note = _refused_note(tmp_path, inside, roots=(tmp_path / "checkout",))
    assert not (tmp_path / "checkout" / "a").exists() and "AbeltonGod-Ordner" in note
    (tmp_path / "Backup").mkdir()
    note = _refused_note(tmp_path, tmp_path / "Backup" / "new" / "out")
    assert not (tmp_path / "Backup" / "new").exists() and "Backup" in note
    note = _refused_note(tmp_path, tmp_path / "x" / "Backup")
    assert not (tmp_path / "x").exists() and "Backup" in note


def test_a_missing_accepted_output_folder_is_created_on_the_first_question(tmp_path):
    out = tmp_path / "new" / "deeper" / "out"
    session, _ = make_chat(tmp_path, [turn_text()], out=out)
    assert not out.exists() and session.ask("Hallo").success
    assert out.is_dir() and session.tools_state().folder == out


def test_the_dialog_gets_only_what_is_left_of_the_confirmation_window(tmp_path, fake):
    """#493 review: work before the dialog (Live reads in prepare, slow earlier calls) uses up
    the window that started with the model turn; the dialog's time and text show the rest."""
    approver, shown = gui_approver(None, timeout_s=CONFIRM_TIMEOUT_S)
    session, _ = make_chat(tmp_path, import_script(), fake, approver=approver)
    session.tools_state()  # nothing built yet: the folder does not exist
    (tmp_path / "out").mkdir()
    session.tools_state()
    def clock():  # 15 s "pass" once prepare() has read Live (after the import turn started)
        return 1000.0 + (15.0 if fake.payload() else 0.0)

    session._toolbox.clock = clock
    t = time.monotonic()
    reply = session.ask("Clap erzeugen und importieren")
    assert not reply.success and writes(fake) == []
    req = shown[0]
    assert req.timeout_s == pytest.approx(5.0)
    assert "innerhalb von 5 s" in req.text.text and "20 s" not in req.text.text
    assert time.monotonic() - t < CONFIRM_TIMEOUT_S - 5  # it did not wait the full 20 s


def test_output_folder_check_lets_only_the_missing_set_file_pass(tmp_path):
    plain = tmp_path / "out"
    plain.mkdir()
    assert output_folder_check(plain, refused_roots=()) is None  # no .als: accepted here
    backup = tmp_path / "Backup"
    backup.mkdir()
    for folder, roots, reason in ((tmp_path / "missing", (), ProjectReason.MISSING),
                                  (backup, (), ProjectReason.BACKUP_FOLDER),
                                  (plain, (tmp_path,), ProjectReason.IN_CHECKOUT),
                                  ("relative/out", (), ProjectReason.NOT_ABSOLUTE)):
        problem = output_folder_check(folder, refused_roots=roots)
        assert problem is not None and problem.reason is reason, folder


def test_changing_the_output_folder_rebuilds_the_tools_and_keeps_the_memory(tmp_path):
    session, model = make_chat(tmp_path, [turn_generate(), turn_text("Clap eins."),
                                          turn_generate(), turn_text("Clap zwei.")])
    assert session.ask("Clap bitte").success
    session.set_output_dir(tmp_path / "other")
    assert session.ask("Noch einer").success
    assert len(wavs(tmp_path / "out")) == 1 and len(wavs(tmp_path / "other")) == 1
    assert "Clap eins." in model.requests[2].system  # memory survived the rebuild
    # the new session table is empty: ids of the old folder are not offered for import
    assert "clap-1" not in model.requests[2].system
    assert str(tmp_path / "other") in session.tools_state().note


def test_memory_hands_the_previous_exchange_to_the_next_request(tmp_path):
    session, model = make_chat(tmp_path, [turn_text("Welche Spur?"), turn_text("Gut.")])
    session.ask("Importiere den Clap")
    session.ask("Spur 3")
    assert "Importiere den Clap" not in model.requests[0].system
    assert "User: Importiere den Clap" in model.requests[1].system
    assert "Copilot: Welche Spur?" in model.requests[1].system


# --- approval: the import path against the fake AbletonOSC -----------------------------------


def import_script():
    return [turn_generate(), turn_import(), turn_text("Erledigt.")]


def test_yes_imports_exactly_the_file_named_in_the_dialog(tmp_path, fake):
    approver, shown = gui_approver(True)
    session, _ = make_chat(tmp_path, import_script(), fake, approver=approver)
    reply = session.ask("Clap erzeugen und in Spur 3 legen")
    assert reply.success, reply.text
    wav = wavs(tmp_path / "out")[0]
    assert writes(fake) == [(CREATE, (2, 0, str(wav)))]
    text = shown[0].text.text
    assert 'Spur 3 "3-Audio"' in text and "Szene 1 (von 4)" in text
    assert str(wav) in text and sha256_file(wav) in text and "clap-1 (clap)" in text
    assert "kein berechnetes Geld" not in reply.budget  # fake model: no subscription note
    assert "1 von 2 Live-Änderungen" in reply.budget


@pytest.mark.parametrize("answer", [False, None], ids=["no", "timeout"])
def test_no_and_timeout_write_nothing_and_are_not_a_success(tmp_path, fake, answer):
    timeout = DECIDE_S if answer is False else 0.3  # the subject of the second case is the timeout
    approver, shown = gui_approver(answer, timeout_s=timeout)
    session, _ = make_chat(tmp_path, import_script(), fake, approver=approver)
    t = time.monotonic()
    reply = session.ask("Clap erzeugen und importieren")
    assert not reply.success
    assert writes(fake) == [] and len(shown) == 1 and shown[0].closed
    assert "0 von 2 Live-Änderungen" in reply.budget
    if answer is None:
        assert time.monotonic() - t < DECIDE_S  # the worker did not wait for ever


def test_a_yes_after_the_timeout_does_not_count(tmp_path, fake):
    approver, shown = gui_approver(True, timeout_s=0.2, delay_s=1.0)
    session, _ = make_chat(tmp_path, import_script(), fake, approver=approver)
    assert not session.ask("importieren").success
    time.sleep(1.2)  # the late yes arrives now
    assert shown[0].answer(True) is False and writes(fake) == []


def test_a_dialog_that_cannot_be_shown_is_a_no(tmp_path, fake):
    def post(_request):
        raise RuntimeError("no GUI")

    session, _ = make_chat(tmp_path, import_script(), fake,
                           approver=GuiApprover(post, timeout_s=DECIDE_S))
    t = time.monotonic()
    assert not session.ask("importieren").success
    assert writes(fake) == [] and time.monotonic() - t < DECIDE_S


def test_cancel_while_the_dialog_is_open_declines_and_stops_the_request(tmp_path, fake):
    approver, shown = gui_approver(None, timeout_s=30)
    session, model = make_chat(tmp_path, import_script(), fake, approver=approver)
    result = {}
    worker = threading.Thread(target=lambda: result.setdefault("r", session.ask("import")))
    worker.start()
    end = time.monotonic() + DECIDE_S
    while not shown and time.monotonic() < end:
        time.sleep(0.01)
    assert shown, "the confirmation was never posted"
    session.cancel()
    worker.join(DECIDE_S)
    reply = result["r"]
    assert not reply.success and reply.cancelled and "Abgebrochen" in reply.text
    assert writes(fake) == [] and len(model.requests) == 2  # no model call after the cancel


def test_without_a_gui_approver_every_live_write_is_declined(tmp_path, fake):
    session, _ = make_chat(tmp_path, import_script(), fake)  # DenyApprover
    assert not session.ask("importieren").success
    assert writes(fake) == []


# --- cancel and guard limits -----------------------------------------------------------------


class BlockingModel(FakeModel):
    """The first call waits until ``release`` is set (a Claude answer on its way)."""

    def __init__(self, turns):
        super().__init__(turns)
        self.entered = threading.Event()
        self.release = threading.Event()

    def complete(self, request):
        if not self.entered.is_set():
            self.entered.set()
            self.release.wait(DECIDE_S)
        return super().complete(request)


def test_cancel_waits_for_the_running_model_call_then_runs_no_tool(tmp_path):
    model = BlockingModel([turn_generate(), turn_text()])
    session = ChatSession(tmp_path / ".env", model=model, guard=guard_for(tmp_path),
                          output_dir=tmp_path / "out", session_options={"refused_roots": ()})
    result = {}
    worker = threading.Thread(target=lambda: result.setdefault("r", session.ask("Clap")))
    worker.start()
    assert model.entered.wait(DECIDE_S)
    session.cancel()
    model.release.set()
    worker.join(DECIDE_S)
    reply = result["r"]
    assert reply.cancelled and not reply.success
    assert wavs(tmp_path / "out") == [] and "Es wurde nichts geändert." in reply.text


def test_a_cancel_after_the_request_does_not_stop_the_next_one(tmp_path):
    session, _ = make_chat(tmp_path, [turn_text("eins"), turn_text("zwei")])
    assert session.ask("a").success
    session.cancel()  # nothing runs: must not carry over
    assert session.ask("b").success


def test_the_file_limit_of_the_guard_still_applies(tmp_path):
    guard = guard_for(tmp_path, max_files_written=2)
    session, _ = make_chat(tmp_path, [turn_generate(args={**CLAP, "variants": 2}),
                                      turn_text()], guard=guard)
    reply = session.ask("Zwei Claps")
    assert wavs(tmp_path / "out") == [] and reply.files == ()
    assert not reply.success


def test_the_live_write_limit_of_the_guard_still_applies(tmp_path, fake):
    guard = guard_for(tmp_path, max_live_writes=0)
    approver = Answer(True)
    session, _ = make_chat(tmp_path, import_script(), fake, guard=guard, approver=approver)
    reply = session.ask("importieren")
    assert not reply.success and writes(fake) == [] and approver.asked == []
    assert guard.policy.profile("kick_generation").max_live_writes == 0
    assert Limit.LIVE_WRITES.value in json.dumps(
        [json.loads(x) for x in guard._log.path.read_text("utf-8").splitlines()])


# --- texts -----------------------------------------------------------------------------------


def test_budget_text_names_the_guards_own_limits(tmp_path):
    guard = guard_for(tmp_path)
    before = budget_text(guard)
    assert "höchstens 8 Modellaufrufe" in before and "12 Dateien" in before
    assert "2 Live-Änderungen" in before and "Sitzung 0,00 $ von 3,00 $" in before
    assert "heute 0,00 $ von 10,00 $" in before
    assert "kein berechnetes Geld" in budget_text(guard, mode="subscription")


def test_a_failed_subscription_request_names_the_login_as_a_possibility(tmp_path, monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ABELTONGOD_CLAUDE_AUTH"):
        monkeypatch.delenv(name, raising=False)
    model = FakeModel([{"error": "unavailable", "detail": "not logged in",
                        "request_sent": False}])
    session = ChatSession(tmp_path / ".env", model=model, guard=guard_for(tmp_path),
                          output_dir=tmp_path / "out", session_options={"refused_roots": ()})
    monkeypatch.setattr(session, "status",
                        lambda: type("S", (), {"ready": True, "message": "", "mode":
                                               "subscription"})())
    reply = session.ask("Hallo")
    assert not reply.success and LOGIN_HINT in reply.text and "Falls" in LOGIN_HINT

