"""Window tests on the offscreen platform. Skipped when PySide6 is not installed."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

if os.environ.get("ABELTONGOD_REQUIRE_GUI") == "1":  # CI: a missing Qt must fail, not skip
    import PySide6.QtWidgets  # noqa: F401
else:
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QComboBox, QLabel, QLineEdit  # noqa: E402

from gui.app import create_app  # noqa: E402
from gui.main_window import MainWindow  # noqa: E402
from gui_core.form import kick_field_specs  # noqa: E402
from gui_core.preview import ERROR, LOADED, PLAYING  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return create_app([])


class FakeBackend:
    available = True

    def __init__(self):
        self.played = []

    def play(self, wav_path):
        self.played.append(wav_path)

    def stop(self):
        pass


@pytest.fixture
def window(qapp, tmp_path):
    w = MainWindow(out_dir=tmp_path / "out", backend=FakeBackend(), opener=lambda p: True)
    w.show()
    yield w
    w.close()


def wait_for(qapp, cond, seconds=15):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def type_into(edit: QLineEdit, text: str) -> None:
    edit.selectAll()
    QTest.keyClick(edit, Qt.Key.Key_Delete)
    QTest.keyClicks(edit, text)


def test_window_builds_with_categories(window):
    assert window.windowTitle() == "AbeltonGod"
    items = [window.categories.item(i) for i in range(window.categories.count())]
    assert [i.text() for i in items] == [
        "Kick", "Hi-Hat", "Snare", "Clap", "Rim", "Bass", "Bibliothek",
        "Goa-Arrangement", "Live-Import", "Copilot",
    ]
    for it in items:
        assert it.flags() & Qt.ItemFlag.ItemIsEnabled
    assert window.render_button.isEnabled() and not window.cancel_button.isEnabled()
    assert window.render_button.text() == "Rendern"


def test_form_lists_every_contract_field_with_its_range(window):
    labels = {lab.text() for lab in window.panel.findChildren(QLabel)}
    for spec in kick_field_specs():
        assert spec.name in window.panel.edits
        assert spec.range_text in labels, spec.name
        assert window.panel.checks[spec.name].text() == spec.label
    assert isinstance(window.panel.edits["sample_rate"], QComboBox)
    assert window.panel.preset_box.count() >= 5


def test_invalid_input_disables_render_and_shows_message(window):
    drive = window.panel.edits["drive"]
    type_into(drive, "7")
    assert not window.render_button.isEnabled()
    assert "Rendern nicht möglich" in window.status.text() and "Drive" in window.status.text()
    assert window.status.property("level") == "error"
    assert drive.property("invalid") is True
    type_into(drive, "0,3")
    assert window.render_button.isEnabled()
    assert drive.property("invalid") is False
    assert window.status.text() == ""


def test_start_render_refuses_invalid_form_even_when_called_directly(window):
    type_into(window.panel.edits["drive"], "7")
    window.start_render()
    assert window.handle is None and not window.running
    assert window.results.count() == 0


def test_switching_a_field_off_ignores_its_bad_value(window):
    type_into(window.panel.edits["tone"], "abc")
    assert not window.render_button.isEnabled()
    window.panel.checks["tone"].setChecked(False)
    assert window.render_button.isEnabled()
    assert not window.panel.edits["tone"].isEnabled()


def test_preset_change_updates_the_fields(window):
    window.panel.preset_box.setCurrentText("dense")
    assert window.model.preset == "dense"
    from audio_engine.presets import load_preset

    assert window.panel.edits["seed"].text() == str(load_preset("dense")["seed"])


def test_render_lists_file_and_preview_player_loads_it(qapp, window):
    type_into(window.panel.edits["variants"], "2")
    window.render_button.click()
    assert wait_for(qapp, lambda: window.results.count() == 2)
    assert window.status.text().startswith("Fertig: 2 Datei(en)")
    assert window.progress.value() == window.progress.maximum() == 2
    for row in range(2):
        path = Path(window.results.item(row).data(Qt.ItemDataRole.UserRole))
        assert path.is_file()
        assert path.parent == Path(window.folder_edit.text())
    assert window.results.item(0).text().startswith("kick  punchy_s")
    # first new result is selected and loaded
    assert window.results.currentRow() == 0
    assert window.preview.state == LOADED
    assert window.wave.waveform is not None and window.wave.waveform.duration_s > 0.3
    assert window.play_button.isEnabled()
    window.play_button.click()
    assert window.preview.state == PLAYING
    assert len(window.preview.backend.played) == 1
    window.stop_button.click()
    assert window.preview.state == LOADED


def test_render_error_is_shown_and_not_reported_as_done(qapp, window, tmp_path):
    blocker = tmp_path / "file.txt"
    blocker.write_text("x")
    window.folder_edit.setText(str(blocker / "sub"))
    window.render_button.click()
    assert wait_for(qapp, lambda: not window.running)
    assert window.status.text().startswith("Fehler:")
    assert window.status.property("level") == "error"
    assert window.results.count() == 0
    assert window.render_button.isEnabled()


def test_open_folder_uses_opener_only_for_existing_folder(window, tmp_path):
    opened = []
    window.opener = lambda p: opened.append(p) or True
    window.open_button.click()  # folder does not exist yet
    assert opened == [] and window.status.property("level") == "error"
    window.folder_edit.setText(str(tmp_path))
    window.open_button.click()
    assert opened == [tmp_path]


def test_play_without_audio_output_reports_instead_of_raising(qapp, tmp_path):
    from gui_core.preview import NoBackend

    w = MainWindow(out_dir=tmp_path / "o", backend=NoBackend())
    w.render_button.click()
    assert wait_for(qapp, lambda: w.results.count() == 1)
    w.play_button.click()
    assert w.preview.state == ERROR and "Audioausgabe" in w.preview_info.text()
    w.close()
