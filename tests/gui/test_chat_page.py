"""#491: the Copilot page as the user drives it: fake model, real orchestrator and guard, the
fake AbletonOSC server of tests/bridge, the main window's library. The confirmation dialog is
answered by clicking its buttons (yes / no / Esc / timeout / cancel button).

CI only: nothing here is evidence for Claude, for Live, or for the look on a Windows screen."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

if os.environ.get("ABELTONGOD_REQUIRE_GUI") == "1":  # CI: a missing Qt must fail, not skip
    import PySide6.QtWidgets  # noqa: F401
else:
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gui_core"))
from chat_helpers import (  # noqa: E402
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
from PySide6.QtCore import Qt, QUrl  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402

from gui.app import create_app  # noqa: E402
from gui.chat_panel import NO_TEXT, YES_TEXT  # noqa: E402
from gui.drag import PATH_ROLE  # noqa: E402
from gui.main_window import MainWindow  # noqa: E402
from gui_core.chat import ConfirmRequest, ConfirmText  # noqa: E402

WAIT_S = 30.0


@pytest.fixture(scope="module")
def qapp():
    return create_app([])


class FakeBackend:
    available = True

    def play(self, wav_path):
        pass

    def stop(self):
        pass


@pytest.fixture
def fake():
    server = make_fake()
    yield server
    server.close()


def wait_for(qapp, cond, seconds=WAIT_S):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    qapp.processEvents()
    return cond()


def window_for(tmp_path, turns, fake=None):
    session, model = make_chat(tmp_path, turns, fake)
    w = MainWindow(out_dir=tmp_path / "out", backend=FakeBackend(), opener=lambda p: True,
                   chat_session=session)
    w.show()
    w.categories.setCurrentRow(w.tool_rows["chat"])
    return w, model


def ask(qapp, w, text):
    c = w.chat
    c.input.setText(text)
    c.send_button.click()
    assert c.busy and c.cancel_button.isEnabled() and not c.send_button.isEnabled()


def wait_dialog(qapp, c):
    assert wait_for(qapp, lambda: c.confirm_dialog is not None and c.confirm_dialog.isVisible()), \
        "no confirmation dialog"
    return c.confirm_dialog


def import_turns():
    return [turn_generate(), turn_import(), turn_text("Clap liegt in Spur 3.")]


def test_page_names_the_tools_and_the_output_folder(qapp, tmp_path):
    w, _ = window_for(tmp_path, [turn_text()])
    try:
        c = w.chat
        assert str(tmp_path / "out") in c.tools_info.text()
        assert not (tmp_path / "out").exists()  # opening the page creates nothing
        assert "höchstens 8 Modellaufrufe" in c.budget.text()
        assert not c.cancel_button.isEnabled()
    finally:
        w.close()


def test_generate_lands_in_the_library_and_as_a_link_in_the_transcript(qapp, tmp_path):
    w, model = window_for(tmp_path, [turn_generate(), turn_text("Clap fertig.")])
    try:
        c = w.chat
        ask(qapp, w, "Mach einen Clap")
        assert wait_for(qapp, lambda: not c.busy)
        made = wavs(tmp_path / "out")
        assert len(made) == 1 and c.last_reply.success
        assert str(made[0]) in c.transcript.toPlainText()
        assert QUrl.fromLocalFile(str(made[0])).toString() in c.transcript.toHtml()
        assert "2 von 12 Dateien" in c.budget.text()
        assert "generate_sample" in c.tools_info.text()
        c._link_clicked(QUrl.fromLocalFile(str(made[0])))  # what a click on the link does
        assert w.on_library and w.library.current_path() == made[0]
        listed = [Path(w.library.list.item(i).data(PATH_ROLE))
                  for i in range(w.library.list.count())]
        assert made[0] in listed
    finally:
        w.close()


def test_yes_in_the_dialog_imports_and_the_dialog_lists_what_is_written(qapp, tmp_path, fake):
    w, _ = window_for(tmp_path, import_turns(), fake)
    try:
        c = w.chat
        ask(qapp, w, "Clap in Spur 3")
        dlg = wait_dialog(qapp, c)
        wav = wavs(tmp_path / "out")[0]
        text = dlg.text()
        assert 'Spur 3 "3-Audio"' in text and str(wav) in text and "SHA-256" in text
        assert dlg.defaultButton() is c.confirm_buttons["no"]
        assert dlg.escapeButton() is c.confirm_buttons["no"]
        assert dlg.windowModality() == Qt.WindowModality.ApplicationModal
        assert writes(fake) == []  # nothing before the yes
        assert c.confirm_buttons["yes"].text() == YES_TEXT
        c.confirm_buttons["yes"].click()
        assert wait_for(qapp, lambda: not c.busy)
        assert c.last_reply.success, c.last_reply.text
        assert writes(fake) == [(CREATE, (2, 0, str(wav)))]
        assert "1 von 2 Live-Änderungen" in c.budget.text()
    finally:
        w.close()


@pytest.mark.parametrize("how", ["no", "escape", "default"])
def test_no_escape_and_the_default_button_write_nothing(qapp, tmp_path, fake, how):
    w, _ = window_for(tmp_path, import_turns(), fake)
    try:
        c = w.chat
        ask(qapp, w, "Clap in Spur 3")
        dlg = wait_dialog(qapp, c)
        if how == "no":
            assert c.confirm_buttons["no"].text() == NO_TEXT
            c.confirm_buttons["no"].click()
        elif how == "escape":
            QTest.keyClick(dlg, Qt.Key.Key_Escape)
        else:  # Enter takes the default button
            QTest.keyClick(dlg, Qt.Key.Key_Return)
        assert wait_for(qapp, lambda: not c.busy)
        assert not c.last_reply.success and writes(fake) == []
        assert "0 von 2 Live-Änderungen" in c.budget.text()
    finally:
        w.close()


def test_a_dialog_closed_without_a_button_is_a_no(qapp, tmp_path, fake):
    """Any close that is not the yes button answers no (here: closed by code while the worker
    still waits, the path a window-manager close or a future caller takes)."""
    w, _ = window_for(tmp_path, import_turns(), fake)
    try:
        c = w.chat
        ask(qapp, w, "Clap in Spur 3")
        dlg = wait_dialog(qapp, c)
        request = c.pending_confirm
        dlg.done(0)
        assert wait_for(qapp, lambda: not c.busy)
        assert request.closed and not c.last_reply.success and writes(fake) == []
    finally:
        w.close()


def test_the_dialog_closes_as_no_when_its_time_is_up(qapp, tmp_path, fake):
    w, _ = window_for(tmp_path, import_turns(), fake)
    try:
        c = w.chat
        c.approver.timeout_s = 1.0  # the subject of this test is the timeout
        ask(qapp, w, "Clap in Spur 3")
        wait_dialog(qapp, c)
        assert wait_for(qapp, lambda: not c.busy)
        assert c.confirm_dialog is None and not c.last_reply.success
        assert writes(fake) == []
    finally:
        w.close()


def test_the_gui_countdown_closes_the_dialog_by_itself(qapp, tmp_path):
    """#493 review (mutant R1): no worker waits here, so only the dialog's own timer can close
    it; it answers no when the request's deadline is reached, and shows the time left."""
    w, _ = window_for(tmp_path, [turn_text()])
    try:
        c = w.chat
        request = ConfirmRequest(ConfirmText("Live-Set ändern?", ("Test",)), 1.5)
        c._show_confirm(request)
        dlg = c.confirm_dialog
        assert dlg is not None and dlg.isVisible()
        assert dlg.informativeText() in ("Noch 2 s.", "Noch 1 s.")
        assert wait_for(qapp, lambda: c.confirm_dialog is None, seconds=10)
        assert request.closed and request.wait() is False
    finally:
        w.close()


def test_cancel_button_answers_the_open_dialog_with_no_and_stops(qapp, tmp_path, fake):
    w, model = window_for(tmp_path, import_turns(), fake)
    try:
        c = w.chat
        ask(qapp, w, "Clap in Spur 3")
        wait_dialog(qapp, c)
        c.cancel_button.click()
        assert wait_for(qapp, lambda: not c.busy)
        assert c.last_reply.cancelled and "Abgebrochen" in c.transcript.toPlainText()
        assert writes(fake) == [] and len(model.requests) == 2
        assert c.confirm_dialog is None
        assert not [m for m in qapp.topLevelWidgets()
                    if isinstance(m, QMessageBox) and m.isVisible()]
    finally:
        w.close()


def test_memory_carries_the_previous_exchange(qapp, tmp_path):
    w, model = window_for(tmp_path, [turn_text("Welche Spur?"), turn_text("Gut.")])
    try:
        c = w.chat
        ask(qapp, w, "Importiere den Clap")
        assert wait_for(qapp, lambda: not c.busy)
        ask(qapp, w, "Spur 3")
        assert wait_for(qapp, lambda: not c.busy)
        assert "Copilot: Welche Spur?" in model.requests[1].system
    finally:
        w.close()


def test_the_page_follows_the_output_folder_setting(qapp, tmp_path):
    w, _ = window_for(tmp_path, [turn_generate(), turn_text()])
    try:
        other = tmp_path / "anders"
        w.hub.store.update(output_dir=str(other))
        assert w.chat.session.output_dir == other
        ask(qapp, w, "Clap")
        assert wait_for(qapp, lambda: not w.chat.busy)
        assert len(wavs(other)) == 1 and wavs(tmp_path / "out") == []
    finally:
        w.close()


def test_with_the_project_setting_the_dialog_names_the_copy_and_yes_imports_it(
        qapp, tmp_path, fake):
    """#500: the shared project folder (settings) makes the import copy into it first."""
    proj = make_project(tmp_path)
    w, _ = window_for(tmp_path, import_turns(), fake)
    try:
        c = w.chat
        w.hub.store.update(project_dir=str(proj))
        assert c.session.project_dir == str(proj)
        ask(qapp, w, "Clap in Spur 3")
        dlg = wait_dialog(qapp, c)
        target = proj / "Samples" / "Drums" / "Claps" / wavs(tmp_path / "out")[0].name
        assert f"nach {target}" in dlg.text()
        c.confirm_buttons["yes"].click()
        assert wait_for(qapp, lambda: not c.busy)
        assert c.last_reply.success and writes(fake) == [(CREATE, (2, 0, str(target)))]
        assert target.is_file() and f"Projektordner {proj}" in c.tools_info.text()
    finally:
        w.close()
