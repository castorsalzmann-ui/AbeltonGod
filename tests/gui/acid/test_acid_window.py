"""Acid window on the offscreen platform (ABELTONGOD_REQUIRE_GUI=1: a missing Qt must fail)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

if os.environ.get("ABELTONGOD_REQUIRE_GUI") == "1":
    import PySide6.QtWidgets  # noqa: F401
else:
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from audio_engine.acid_midi import acid_line_to_midi  # noqa: E402
from gui.acid import skin  # noqa: E402
from gui.acid.app import create_acid_app, take_screenshots  # noqa: E402
from gui.acid.widgets import STEPS_PER_ROW  # noqa: E402
from gui.acid.window import PREVIEW_LABEL, AcidWindow  # noqa: E402
from gui_core.acid_generate import GenOptions, generate_line  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return create_acid_app([])


class FakeBackend:
    def __init__(self, available=True):
        self.available = available
        self.played: list[Path] = []
        self.header: list[bytes] = []
        self.stopped = 0

    def play(self, wav_path):
        self.played.append(wav_path)
        self.header.append(Path(wav_path).read_bytes()[:4])

    def stop(self):
        self.stopped += 1


@pytest.fixture
def win(qapp, tmp_path):
    opened: list[Path] = []
    w = AcidWindow(out_dir=tmp_path / "out", backend=FakeBackend(),
                   opener=lambda p: opened.append(p) or True,
                   ask_open=lambda parent, start: None, seed_source=lambda: 4242)
    w.opened = opened
    w.show()
    QApplication.processEvents()
    yield w
    w.close()


def click(win, step, region):
    pos = win.grid.region_rect(step, region).center().toPoint()
    QTest.mouseClick(win.grid, Qt.MouseButton.LeftButton, pos=pos)


def status_is_error(win):
    return win.status.property("level") == "error"


def test_grid_builds_16_steps_and_32_in_two_rows(win):
    assert win.grid.visible_steps() == 16 and win.grid.rows() == 1
    win.length_spin.setValue(32)
    assert win.model.length == 32 and win.grid.rows() == 2
    win.length_spin.setValue(5)
    assert win.grid.visible_steps() == 5 and win.grid.rows() == 1
    assert len(win.model.to_line()["steps"]) == 5


@pytest.mark.parametrize("length", [1, 7, 16, 17, 32])
def test_hit_test_finds_every_control_of_every_step(win, length):
    win.length_spin.setValue(length)
    QApplication.processEvents()
    for step in range(length):
        for region in win.grid.REGIONS:
            center = win.grid.region_rect(step, region).center()
            assert win.grid.hit_test(center) == (step, region)
    assert win.grid.hit_test(QPoint(2, 2).toPointF()) is None


def test_clicking_pad_accent_slide_updates_the_line(win):
    win.model.clear()
    win.grid.update()
    click(win, 3, "pad")
    click(win, 3, "accent")
    click(win, 3, "slide")
    step = win.model.to_line()["steps"][3]
    assert step["on"] and step["accent"] and step["slide"]
    click(win, 3, "pad")
    assert win.model.to_line()["steps"][3] == {"on": False}
    click(win, 3, "accent")
    assert win.model.steps[3].accent is False


def test_dragging_pitch_sets_notes_within_the_scale(win):
    win.model.clear()
    click(win, 0, "pad")
    rect = win.grid.region_rect(0, "pitch")
    x = int(rect.center().x())
    QTest.mouseClick(win.grid, Qt.MouseButton.LeftButton, pos=QPoint(x, int(rect.bottom())))
    assert win.model.steps[0].note == 45  # lowest note of the palette: A2 (A minor, octave 2)
    QTest.mouseClick(win.grid, Qt.MouseButton.LeftButton, pos=QPoint(x, int(rect.top())))
    assert win.model.steps[0].note == 81  # top: the root three octaves up (A5)
    # press + move + release: the last position wins and every value is a palette note
    QTest.mousePress(win.grid, Qt.MouseButton.LeftButton, pos=QPoint(x, int(rect.bottom())))
    for frac in (0.8, 0.55, 0.3):
        y = int(rect.bottom() - frac * rect.height())
        QTest.mouseMove(win.grid, QPoint(x, y))
        assert win.model.steps[0].note in win.model.palette(3)
    QTest.mouseRelease(win.grid, Qt.MouseButton.LeftButton, pos=QPoint(x, int(rect.top())))
    from PySide6.QtGui import QCursor  # diagnosis for a Windows CI failure (#517 PR)
    spot = win.grid.mapToGlobal(QPoint(x, int(rect.top())))
    where = (f"window {win.geometry()}, grid point {spot}, cursor {QCursor.pos()}, at point "
             f"{QApplication.topLevelAt(spot)}, widget {QApplication.widgetAt(spot)}, windows "
             f"{[w for w in QApplication.topLevelWidgets() if w.isVisible()]}")
    assert 45 < win.model.steps[0].note < 81, where
    assert win.model.to_line()["steps"][0]["note"] == win.model.steps[0].note


def test_generate_fills_grid_from_fields(win):
    win.density_edit.setText("50")
    win.accent_edit.setText("0")
    win.slide_edit.setText("100")
    win.range_spin.setValue(1)
    win.seed_edit.setText("31")
    win.root_box.setCurrentText("D")
    win.scale_box.setCurrentText("phrygian")
    win._scale_changed()
    win.generate_button.click()
    expected = generate_line(GenOptions(root="D", scale="phrygian", root_octave=2, length=16,
                                        density=0.5, accent_chance=0.0, slide_chance=1.0,
                                        octave_range=1, seed=31))
    assert win.model.to_line() == expected
    assert not status_is_error(win) and "Seed 31" in win.status.text()


def test_new_seed_uses_seed_source_and_generates(win):
    win.newseed_button.click()
    assert win.seed_edit.text() == "4242" and win.model.seed == 4242
    assert win.model.to_line() == generate_line(GenOptions(seed=4242))


@pytest.mark.parametrize("field,text,fragment", [
    ("density_edit", "abc", "Dichte muss"),
    ("density_edit", "101", "Dichte muss"),
    ("accent_edit", "-5", "Akzent muss"),
    ("slide_edit", "", "Slide muss"),
    ("seed_edit", "1.5", "Seed muss"),
])
def test_invalid_generator_input_is_rejected_in_german(win, field, text, fragment):
    before = win.model.to_line()
    getattr(win, field).setText(text)
    win.generate_button.click()
    assert status_is_error(win) and fragment in win.status.text()
    assert getattr(win, field).property("invalid") is True
    assert win.model.to_line() == before


def test_invalid_bpm_rejected_and_valid_bpm_used_for_export(win, tmp_path):
    win.bpm_edit.setText("9999")
    win.bpm_edit.editingFinished.emit()
    assert status_is_error(win) and "BPM muss zwischen 20 und 400" in win.status.text()
    assert win.model.bpm == 130.0
    assert win.export_midi() is None
    assert not (tmp_path / "out").exists()  # nothing written
    win.bpm_edit.setText("141,5")
    assert win.export_midi() is not None
    assert win.model.bpm == 141.5


def test_export_midi_bytes_equal_acid_midi_output(win, tmp_path):
    win.seed_edit.setText("77")
    win.density_edit.setText("80")
    win.generate_button.click()
    line = generate_line(GenOptions(seed=77, density=0.8))
    win.bpm_edit.setText("128")
    path = win.export_midi()
    assert path == tmp_path / "out" / "acid_77" / "acid_77.mid"  # run folder (#468)
    assert path.read_bytes() == acid_line_to_midi(line, bpm=128.0)
    assert "nicht in Live getestet" in win.status.text()


def test_save_json_then_load_round_trips(win, tmp_path):
    win.seed_edit.setText("9")
    win.generate_button.click()
    saved = win.save_json()
    assert saved == tmp_path / "out" / "acid_9" / "acid_9.json"
    line = json.loads(saved.read_text(encoding="utf-8"))
    assert line == generate_line(GenOptions(seed=9))
    win.model.clear()
    win.ask_open = lambda parent, start: saved
    win.load_button.click()
    assert win.model.to_line() == line and "Geladen" in win.status.text()
    assert win.length_spin.value() == 16 and win.root_box.currentText() == "A"


def test_load_invalid_file_gives_german_error_and_keeps_state(win, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"format": "nope"}', encoding="utf-8")
    before = win.model.to_line()
    win.ask_open = lambda parent, start: bad
    win.load_button.click()
    assert status_is_error(win) and "keine gültige Acid-Linie" in win.status.text()
    assert win.model.to_line() == before
    win.ask_open = lambda parent, start: None  # dialog cancelled
    win.load_button.click()
    assert win.model.to_line() == before


def test_open_folder_paths(win, tmp_path):
    win.open_button.click()
    assert status_is_error(win) and "existiert noch nicht" in win.status.text()
    assert win.opened == []
    win.save_json()  # creates the folder
    win.open_button.click()
    assert win.opened == [tmp_path / "out"]
    win.opener = lambda p: False
    win.open_button.click()
    assert "nicht geöffnet" in win.status.text() and status_is_error(win)


def test_scale_change_snaps_notes_and_octave_moves_them(win):
    win.model.clear()
    win.model.toggle_on(0)
    win.model.set_note(0, 46)
    win.root_box.setCurrentText("A")
    win.scale_box.setCurrentText("minor")
    win._scale_changed()
    assert win.model.steps[0].note == 45
    win.octave_spin.setValue(3)
    assert win.model.steps[0].note == 57 and win.model.root_octave == 3


def test_preview_plays_wav_and_is_labelled_rough(win):
    assert PREVIEW_LABEL == "grobe Vorschau, kein 303-Klang"
    assert PREVIEW_LABEL in win.preview_note.text()
    win.preview_button.click()
    assert len(win.backend.played) == 1 and win.backend.header == [b"RIFF"]
    assert PREVIEW_LABEL in win.status.text() and not status_is_error(win)
    win.stop_button.click()
    assert win.backend.stopped == 1


def test_preview_without_audio_output_says_so(qapp, tmp_path):
    w = AcidWindow(out_dir=tmp_path, backend=FakeBackend(available=False))
    w.preview_button.click()
    assert status_is_error(w) and w.status.text() == "Keine Audioausgabe verfügbar."
    w.close()


def test_animation_is_off_by_default_and_toggles_all_timers(win):
    parts = (win.header, win.footer, win.grid)
    assert not win.anim_box.isChecked()
    assert all(not w._timer.isActive() for w in parts)
    win.anim_box.setChecked(True)
    assert all(w._timer.isActive() and w.animating for w in parts)
    win.grid._tick()
    assert win.grid.t > 0
    win.anim_box.setChecked(False)
    assert all(not w._timer.isActive() for w in parts) and win.grid.t == 0.0


def test_animated_grid_still_draws_lit_pads_from_sprites(win):
    win.model.clear()
    win.model.toggle_on(2)
    win.grid.update()
    for animate in (False, True):
        win.set_animation(animate)
        win.grid.t = 1.0
        img = win.grid.grab().toImage()
        c = win.grid.region_rect(2, "pad").center().toPoint()
        dark = win.grid.region_rect(0, "pad").center().toPoint()
        assert img.pixelColor(c).green() > 150, animate  # lit pad is bright green either way
        assert img.pixelColor(dark).green() < 80, animate  # a rest stays dark


def test_labels_are_legible_contrast_ratios():
    # WCAG AA for normal text is 4.5; the palette must clear it on every dark ground it is used on
    for fg in (skin.TEXT, skin.MUTED):
        for bg in (skin.BLACK, skin.BG, skin.PLATE, skin.FIELD):
            assert skin.contrast_ratio(fg, bg) >= 4.5, (fg, bg)
    assert skin.contrast_ratio(skin.ERROR, skin.BLACK) >= 4.5
    assert skin.contrast_ratio(skin.LIME, skin.PLATE_HI) >= 4.5
    assert skin.contrast_ratio("#04100a", "#4fd01c") >= 4.5  # primary button text on its body
    # the helper itself: black on white is 21:1
    assert skin.contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0)


def test_screenshots_written_and_not_blank_and_drips_not_clipped(qapp, tmp_path):
    files = take_screenshots(tmp_path, sizes=((1000, 700),))
    assert len(files) == 1 and files[0].stat().st_size > 20_000
    img = QImage(str(files[0]))
    assert img.width() >= 1000 and img.height() >= 700
    lime = sum(1 for x in range(0, img.width(), 7) for y in range(0, img.height(), 7)
               if img.pixelColor(x, y).green() > 200)
    assert lime > 100  # lit pads, drips, text glow are present


def test_header_drips_end_above_the_widget_bottom(win):
    # grab from the window so the background AcidRoot paints behind the transparent band is included
    root = win.scroll.widget()  # the AcidRoot inside the scroll area (#442)
    img = root.grab(QRect(win.header.mapTo(root, QPoint(0, 0)), win.header.size())).toImage()
    h = img.height()
    for y in (h - 1, h - 2):  # last two pixel rows of the header band stay dark
        for x in range(0, img.width(), 3):
            c = img.pixelColor(x, y)
            assert c.green() < 120, (x, y, c.green())
    assert win.header.drip_max() < win.header.height()
    assert STEPS_PER_ROW == 16


def test_scroll_bars_follow_the_dark_skin(win):
    """W1 polish: the scroll bars of the scroll area (#442) are dark, not the default grey."""
    win.resize(600, 400)  # smaller than the skin: both bars show
    QApplication.processEvents()
    bar = win.scroll.verticalScrollBar()
    assert bar.isVisible()
    img = bar.grab().toImage()
    c = img.pixelColor(img.width() // 2, img.height() - 3)  # the groove, below the handle
    assert max(c.red(), c.green(), c.blue()) < 60, c.name()
