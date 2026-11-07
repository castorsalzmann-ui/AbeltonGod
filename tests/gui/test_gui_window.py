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
from PySide6.QtWidgets import QLineEdit  # noqa: E402

from gui.app import create_app  # noqa: E402
from gui.main_window import MainWindow  # noqa: E402
from gui.widgets import Segmented  # noqa: E402
from gui_core.form import kick_field_specs  # noqa: E402
from gui_core.form_layout import main_controls  # noqa: E402
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
        "Kick", "Hi-Hat", "Snare", "Clap", "Rim", "Bass", "Laser", "Perc", "Bibliothek",
        "Goa-Arrangement", "Arrangement-Planer", "Live-Import", "Copilot",
    ]
    for it in items:
        assert it.flags() & Qt.ItemFlag.ItemIsEnabled
    assert window.render_button.isEnabled() and not window.cancel_button.isEnabled()
    assert window.render_button.text() == "Rendern"


def test_form_has_a_control_and_label_for_every_contract_field(window):
    for spec in kick_field_specs():
        assert spec.name in window.panel.controls
        assert window.panel.controls[spec.name].label.text() == spec.label
    assert isinstance(window.panel.controls["sample_rate"].seg, Segmented)
    assert len(window.panel.chips.buttons) >= 5


def test_main_controls_are_knobs_and_the_rest_waits_in_the_collapsed_section(window):
    panel = window.panel
    assert [k.name for k in panel.knobs] == list(main_controls("kick"))
    assert 3 <= len(panel.knobs) <= 5
    assert not panel.advanced.is_expanded() and not panel.advanced.body.isVisibleTo(panel)
    panel.advanced.set_expanded(True)
    assert panel.controls["amp_decay_ms"].isVisibleTo(panel)
    assert not panel.controls["amp_decay_ms"].style_name == "knob"


def test_a_bad_seed_disables_render_and_shows_message(window):
    seed = window.panel.controls["seed"]
    type_into(seed.edit, "x")
    seed.edit.edited.emit("x")
    assert not window.render_button.isEnabled()
    assert "Rendern nicht möglich" in window.status.text() and "Seed" in window.status.text()
    assert window.status.property("level") == "error"
    assert seed.edit.property("invalid") is True
    type_into(seed.edit, "7")
    seed.edit.edited.emit("7")
    assert window.render_button.isEnabled() and seed.edit.property("invalid") is False
    assert window.status.text() == ""


def test_start_render_refuses_invalid_form_even_when_called_directly(window):
    seed = window.panel.controls["seed"]
    seed.edit.setText("x")
    seed.edit.edited.emit("x")
    window.start_render()
    assert window.handle is None and not window.running
    assert window.results.count() == 0


def test_switching_a_field_off_ignores_its_value_and_shows_the_default(window):
    c = window.panel.controls["tone"]
    c.readout.setText("0.7")
    c.readout.entered.emit("0.7")
    assert c.value() == 0.7 and "tone" in window.model.active
    c.dot.setChecked(False)
    assert "tone" not in window.model.active and not c.is_active()
    assert window.render_button.isEnabled()


def test_preset_change_updates_the_fields(window):
    window.panel.chips.buttons[window.panel.chips.items.index("dense")].click()
    assert window.model.preset == "dense"
    from audio_engine.presets import load_preset

    assert window.panel.controls["seed"].edit.text() == str(load_preset("dense")["seed"])


def test_render_lists_file_and_preview_player_loads_it(qapp, window):
    window.panel.controls["variants"].readout.setText("2")
    window.panel.controls["variants"].readout.entered.emit("2")
    window.render_button.click()
    assert wait_for(qapp, lambda: window.results.count() == 2)
    assert window.status.text().startswith("Fertig: 2 Datei(en)")
    assert window.progress.value() == window.progress.maximum() == 2
    for row in range(2):
        path = Path(window.results.item(row).data(Qt.ItemDataRole.UserRole))
        assert path.is_file()
        assert path.parent == Path(window.folder_edit.text()) / "Samples" / "Drums" / "Kicks"
    assert window.results.item(0).text().startswith("kick  kick_punchy_s")
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
