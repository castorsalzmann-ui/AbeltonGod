"""#500: the GUI copilot's ``import_sample`` copies into the shared project folder first, like
the Live-import page (``gui_core.live`` copy plan): never overwrite, an identical pair is
reused, the copy is kept when Live may point at it, removed only when nothing reached Live.
Without a project folder Live reads the file in the output folder, as before.

Fake model + fake AbletonOSC (tests/bridge): CI only, nothing here is evidence for Live."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from chat_helpers import (
    CREATE,
    make_chat,
    make_fake,
    make_project,
    turn_generate,
    turn_import,
    turn_text,
    wavs,
    writes,
)

from gui_core.chat import ConfirmRequest, GuiApprover, folder_problem_before_create
from gui_core.chat import output_folder_check as check
from library.project import ProjectReason
from orchestrator.kick_tools import sha256_file

DECIDE_S = 5.0
CLAPS = ("Samples", "Drums", "Claps")


@pytest.fixture
def fake():
    server = make_fake()
    yield server
    server.close()


class Answer:
    def __init__(self, yes, during=None):
        self.yes, self.during = yes, during
        self.asked: list = []

    def confirm(self, tool, arguments, plan=None):
        self.asked.append(plan)
        if self.during is not None:
            self.during()
        return self.yes


def script():
    return [turn_generate(), turn_import(), turn_text("Erledigt.")]


def project_files(project: Path) -> list[Path]:
    return sorted(p for p in project.rglob("*") if p.is_file() and p.suffix != ".als")


def test_yes_copies_into_the_project_and_live_gets_the_copy(tmp_path, fake):
    proj = make_project(tmp_path)
    approver = Answer(True)
    session, _ = make_chat(tmp_path, script(), fake, approver=approver, project=str(proj))
    reply = session.ask("Clap in Spur 3")
    assert reply.success, reply.text
    src = wavs(tmp_path / "out")[0]
    target = proj.joinpath(*CLAPS, src.name)
    assert writes(fake) == [(CREATE, (2, 0, str(target)))]
    assert target.read_bytes() == src.read_bytes() and target.with_suffix(".json").is_file()
    assert project_files(proj) == sorted([target, target.with_suffix(".json")])
    summary = approver.asked[0].summary
    assert summary["live_file"] == str(target) and summary["copy_from"] == str(src)
    assert "4 von 12 Dateien" in reply.budget  # 2 generated + 2 copied, counted by the guard
    assert src.is_file()  # the original stays


def test_the_dialog_names_the_copy_target(tmp_path, fake):
    proj = make_project(tmp_path)
    shown: list[ConfirmRequest] = []

    def post(request):
        shown.append(request)
        request.answer(False)

    session, _ = make_chat(tmp_path, script(), fake, approver=GuiApprover(post, DECIDE_S),
                           project=str(proj))
    session.ask("Clap in Spur 3")
    src = wavs(tmp_path / "out")[0]
    text = shown[0].text.text
    assert f"nach {proj.joinpath(*CLAPS, src.name)}" in text
    assert str(src) in text and sha256_file(src) in text and "kein Projektordner" not in text


def test_without_a_project_folder_live_reads_the_output_folder_file(tmp_path, fake):
    shown: list[ConfirmRequest] = []

    def post(request):
        shown.append(request)
        request.answer(True)

    session, _ = make_chat(tmp_path, script(), fake, approver=GuiApprover(post, DECIDE_S))
    assert session.ask("Clap in Spur 3").success
    src = wavs(tmp_path / "out")[0]
    assert writes(fake) == [(CREATE, (2, 0, str(src)))]
    assert "kein Projektordner in den Einstellungen" in shown[0].text.text
    assert "Kein Projektordner eingestellt" in session.tools_state().note


@pytest.mark.parametrize("answer", [False, None], ids=["no", "timeout"])
def test_no_and_timeout_copy_nothing(tmp_path, fake, answer):
    proj = make_project(tmp_path)

    def post(request):
        if answer is not None:
            request.answer(answer)

    approver = GuiApprover(post, DECIDE_S if answer is False else 0.3)  # timeout: the subject
    session, _ = make_chat(tmp_path, script(), fake, approver=approver, project=str(proj))
    assert not session.ask("Clap in Spur 3").success
    assert writes(fake) == [] and project_files(proj) == []


def test_unknown_outcome_keeps_the_copy(tmp_path, fake):
    """The clip's end marker is lost and the clip appears only after the read-back window:
    Live may still point at the copy, so it stays (same setup as the Live page's test)."""
    proj = make_project(tmp_path)
    fake.drop_next_marker_after = {CREATE}
    fake.clip_delay_s = 8.0  # > 1 s timeout + 2 s read-back window, with margin
    session, _ = make_chat(tmp_path, script(), fake, approver=Answer(True), project=str(proj),
                           bridge_timeout_s=1.0)  # the timeout is the subject here
    reply = session.ask("Clap in Spur 3")
    assert not reply.success
    target = proj.joinpath(*CLAPS, wavs(tmp_path / "out")[0].name)
    assert writes(fake) == [(CREATE, (2, 0, str(target)))]
    assert target.is_file() and target.with_suffix(".json").is_file()


def test_copy_is_removed_when_nothing_reached_live(tmp_path, fake):
    """The slot is taken between the yes and the write: the importer refuses before sending
    anything, so the copy is deleted again."""
    proj = make_project(tmp_path)

    def take_slot():
        fake.tracks[2]["slots"][0] = "C:/someone.wav"

    session, model = make_chat(tmp_path, script(), fake, approver=Answer(True, take_slot),
                               project=str(proj))
    reply = session.ask("Clap in Spur 3")
    assert not reply.success
    assert writes(fake) == [] and project_files(proj) == []
    # #506: the removed copy is not counted (only the 2 generated files are)
    assert model.requests[2].messages[-1].results[0].content["copy"] == "removed"
    assert "2 von 12 Dateien" in reply.budget


def test_a_changed_copy_decision_with_the_same_target_is_refused(tmp_path, fake):
    """#506 (reviewer mutant R3 of #504): between plan and yes an identical pair appears at the
    target, so the re-plan says "reuse" instead of "copy" for the same path. The user
    confirmed a copy: refused, nothing sent."""
    proj = make_project(tmp_path)

    def identical_pair_appears():
        src = wavs(tmp_path / "out")[0]
        target = proj.joinpath(*CLAPS, src.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(src.read_bytes())
        target.with_suffix(".json").write_bytes(src.with_suffix(".json").read_bytes())

    approver = Answer(True, identical_pair_appears)
    session, model = make_chat(tmp_path, script(), fake, approver=approver, project=str(proj))
    assert not session.ask("Clap in Spur 3").success
    assert approver.asked[0].summary["copy_from"] is not None  # a copy was planned and shown
    assert writes(fake) == []
    result = model.requests[2].messages[-1].results[0].content
    assert "changed since the plan" in result["message"] and result["live"] == "unchanged"


def test_an_identical_copy_is_reused_and_a_different_file_is_never_overwritten(tmp_path, fake):
    proj = make_project(tmp_path)
    turns = [turn_generate(), turn_import(), turn_text("eins"),
             turn_import("i2", {"sample_id": "clap-1", "track_index": 2, "slot_index": 1}),
             turn_text("zwei")]
    session, _ = make_chat(tmp_path, turns, fake, approver=Answer(True), project=str(proj))
    assert session.ask("Clap in Spur 3").success
    assert session.ask("Nochmal in Szene 2").success
    src = wavs(tmp_path / "out")[0]
    target = proj.joinpath(*CLAPS, src.name)
    assert [p for _, (_, _, p) in writes(fake)] == [str(target), str(target)]
    assert project_files(proj) == sorted([target, target.with_suffix(".json")])


def test_a_different_file_at_the_target_name_is_never_overwritten(tmp_path, fake):
    proj = make_project(tmp_path)
    taken = proj.joinpath(*CLAPS, "short_s7_v0.wav")  # the name the clap will get
    taken.parent.mkdir(parents=True)
    taken.write_bytes(b"someone else's file")
    session, _ = make_chat(tmp_path, script(), fake, approver=Answer(True), project=str(proj))
    assert session.ask("Clap in Spur 3").success
    assert wavs(tmp_path / "out")[0].name == taken.name
    assert taken.read_bytes() == b"someone else's file"
    used = Path(writes(fake)[0][1][2])
    assert used == taken.with_name("short_s7_v0_002.wav") and used.is_file()


def test_an_invalid_project_folder_refuses_before_anyone_is_asked(tmp_path, fake):
    proj = tmp_path / "NoSet"
    proj.mkdir()  # no .als file
    approver = Answer(True)
    session, _ = make_chat(tmp_path, script(), fake, approver=approver, project=str(proj))
    reply = session.ask("Clap in Spur 3")
    assert not reply.success and approver.asked == [] and writes(fake) == []
    assert project_files(proj) == []


def test_a_project_change_between_plan_and_yes_is_refused(tmp_path, fake):
    proj, other = make_project(tmp_path), make_project(tmp_path, "Other")
    session, _ = make_chat(tmp_path, script(), fake, project=str(proj))
    session.approver = Answer(True, lambda: session.set_project_dir(str(other)))
    assert not session.ask("Clap in Spur 3").success
    assert writes(fake) == [] and project_files(proj) == [] and project_files(other) == []


def test_a_failing_copy_sends_nothing(tmp_path, fake, monkeypatch):
    import gui_core.chat as chat_mod

    def disk_full(_placement):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(chat_mod, "copy_into_project", disk_full)
    proj = make_project(tmp_path)
    session, model = make_chat(tmp_path, script(), fake, approver=Answer(True),
                               project=str(proj))
    assert not session.ask("Clap in Spur 3").success
    assert writes(fake) == []
    result = model.requests[2].messages[-1].results[0].content
    assert result["error"] == "tool_error" and result["live"] == "unchanged"
    assert result["message"].startswith("copy into the project folder failed: OSError")


def test_tool_result_says_which_file_live_uses(tmp_path, fake):
    proj = make_project(tmp_path)
    session, model = make_chat(tmp_path, script(), fake, approver=Answer(True),
                               project=str(proj))
    session.ask("Clap in Spur 3")
    result = model.requests[2].messages[-1].results[0].content["imported"]
    src = wavs(tmp_path / "out")[0]
    assert result["live_file"] == str(proj.joinpath(*CLAPS, src.name))
    assert result["copied_into_project"] is True
    assert json.dumps(result)  # plain JSON for the model


# --- review nit of #493: a missing Backup folder in the middle of the output path ----------


def test_a_missing_backup_component_anywhere_is_refused(tmp_path):
    for out in (tmp_path / "nothere" / "Backup" / "out", tmp_path / "a" / "BACKUP"):
        problem = folder_problem_before_create(out, check, ())
        assert problem is not None and problem.reason is ProjectReason.BACKUP_FOLDER, out
        assert not (tmp_path / out.relative_to(tmp_path).parts[0]).exists()
    assert folder_problem_before_create(tmp_path / "nothere" / "Backups" / "out", check,
                                        ()) is None
