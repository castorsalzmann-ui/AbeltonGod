"""Blaster window on the offscreen platform (ABELTONGOD_REQUIRE_GUI=1: a missing Qt must fail).

The engine is the STUB (gui_core.blaster_stub) or a fake; no real laser engine, no sound device,
no Live. This checks widget state, files and pixels of an offscreen render only."""

from __future__ import annotations

import gc
import os
import wave
from pathlib import Path

import pytest

if os.environ.get("ABELTONGOD_REQUIRE_GUI") == "1":
    import PySide6.QtWidgets  # noqa: F401
else:
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.blaster import gun as gunmod  # noqa: E402
from gui.blaster.app import create_blaster_app, take_screenshots  # noqa: E402
from gui.blaster.window import BlasterWindow  # noqa: E402
from gui_core.blaster import DIMENSIONS, encode_shot_wav  # noqa: E402
from gui_core.blaster_stub import StubLaserEngine  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return create_blaster_app([])


class FakeBackend:
    def __init__(self, available=True):
        self.available = available
        self.played: list[Path] = []

    def play(self, wav_path):
        self.played.append(Path(wav_path))

    def stop(self):
        pass


class FakeWriter:
    def write(self, params, seed, samples, sr, folder, stem, description):
        wav, js = Path(folder) / f"{stem}.wav", Path(folder) / f"{stem}.json"
        wav.write_bytes(encode_shot_wav(samples, sr, 24))
        js.write_text("{}")
        return wav, js


class BoomEngine:
    sample_rate = 22050

    def render(self, params, seed):
        raise RuntimeError("kaputt")


def destroy(w):
    """Deterministic teardown: the GC must not destroy a window in the middle of a later paint
    (the crash seen in PR #412)."""
    w.close()
    w.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()
    gc.collect()


def make(tmp_path, **kw):
    kw.setdefault("engine", StubLaserEngine())
    kw.setdefault("backend", FakeBackend())
    opened: list[Path] = []
    w = BlasterWindow(out_dir=tmp_path / "out", work_dir=tmp_path / "work",
                      opener=lambda p: opened.append(p) or True,
                      ask_dir=lambda parent, start: tmp_path / "bank", **kw)
    w.opened = opened
    w.show()
    QApplication.processEvents()
    return w


@pytest.fixture
def win(qapp, tmp_path):
    w = make(tmp_path, bank_writer=FakeWriter())
    yield w
    destroy(w)


def trigger_pos(w) -> QPointF:
    return w.gun._gun_transform().map(QPointF(506, 345))


def click_trigger(w):
    QTest.mouseClick(w.gun, Qt.MouseButton.LeftButton, pos=trigger_pos(w).toPoint())
    QApplication.processEvents()


def is_error(w):
    return w.status.property("level") == "error"


# ---- trigger -> shot ----------------------------------------------------------------------------
def test_clicking_the_trigger_renders_and_plays_a_shot(win):
    click_trigger(win)
    assert win.history.count() == 1 and len(win.backend.played) == 1
    shot = win.session.history[0]
    assert shot.seed == 1 and win.backend.played[0] == shot.play_path
    assert win.seed_edit.text() == "2" and "Seed 1" in win.status.text()
    assert not is_error(win)
    assert win.gun.trace, "the scope shows the shot"


def test_clicking_elsewhere_on_the_gun_does_not_fire(win):
    for pt in (QPointF(300, 230), QPointF(700, 230), QPointF(340, 440)):  # body, barrel, grip
        QTest.mouseClick(win.gun, Qt.MouseButton.LeftButton,
                         pos=win.gun._gun_transform().map(pt).toPoint())
    assert win.history.count() == 0 and win.backend.played == []


def test_right_click_on_the_trigger_does_not_fire(win):
    QTest.mouseClick(win.gun, Qt.MouseButton.RightButton, pos=trigger_pos(win).toPoint())
    assert win.history.count() == 0


def test_space_and_enter_pull_the_trigger(win):
    win.gun.setFocus()
    QTest.keyClick(win.gun, Qt.Key.Key_Space)
    QTest.keyClick(win.gun, Qt.Key.Key_Return)
    assert win.history.count() == 2 and not win.gun.pressed


def test_pressed_visual_follows_mouse_press_and_release(win):
    pos = trigger_pos(win).toPoint()
    QTest.mousePress(win.gun, Qt.MouseButton.LeftButton, pos=pos)
    assert win.gun.pressed
    QTest.mouseRelease(win.gun, Qt.MouseButton.LeftButton, pos=pos)
    assert not win.gun.pressed


def test_hover_over_trigger_sets_hover_state(win):
    QTest.mouseMove(win.gun, trigger_pos(win).toPoint())
    assert win.gun.hover
    QTest.mouseMove(win.gun, win.gun._gun_transform().map(QPointF(300, 230)).toPoint())
    assert not win.gun.hover


def test_same_seed_and_settings_give_the_same_wav_bytes(win):
    click_trigger(win)
    first = win.session.history[0].wav_path.read_bytes()
    win.seed_edit.setText("1")
    win.seed_edit.editingFinished.emit()
    click_trigger(win)
    second = win.session.history[0]
    assert second.seed == 1 and second.wav_path.read_bytes() == first
    click_trigger(win)  # seed 2: different
    assert win.session.history[0].wav_path.read_bytes() != first


def test_dimension_and_sliders_reach_the_engine(win):
    win.select_dimension("void")
    win.sliders["pitch"].setValue(100)
    win.sliders["length"].setValue(0)
    click_trigger(win)
    params, seed = win.session.engine.calls[-1]
    assert params["family"] == "void" and params["pitch_start_hz"] == 8000.0
    assert params["length_ms"] == 60.0 and seed == 1
    assert win.gun.accent.name() == next(d.accent for d in DIMENSIONS if d.key == "void")
    assert win.readouts["pitch"].text() == "8,0 kHz"


def test_every_dimension_can_be_selected_and_fired(win):
    for d in DIMENSIONS:
        win.dim_buttons[d.key].click()
        assert win.current_dimension() == d.key
        click_trigger(win)
        assert win.session.history[0].settings.dimension == d.key
    assert win.history.count() == len(DIMENSIONS)


@pytest.mark.parametrize("text", ["abc", "-3", "2147483648", "1.5", ""])
def test_invalid_seed_is_refused_and_blocks_the_shot(win, text):
    win.seed_edit.setText(text)
    win.seed_edit.editingFinished.emit()
    assert is_error(win) and "Seed" in win.status.text()
    click_trigger(win)
    assert win.history.count() == 0 and win.session.engine.calls == []


# ---- errors ----------------------------------------------------------------------------
def test_engine_error_shows_message_without_flash_or_history(qapp, tmp_path):
    w = make(tmp_path, engine=BoomEngine())
    click_trigger(w)
    assert is_error(w) and "kaputt" in w.status.text()
    assert w.history.count() == 0 and not w.gun.is_animating() and w.seed_edit.text() == "1"
    destroy(w)


def test_missing_engine_is_announced_and_trigger_does_nothing(qapp, tmp_path):
    w = make(tmp_path, engine=None)
    assert is_error(w) and "Laser-Engine" in w.status.text() and not w.gun.ready
    click_trigger(w)
    assert w.history.count() == 0 and w.backend.played == []
    destroy(w)


def test_no_audio_output_still_gives_a_shot(qapp, tmp_path):
    w = make(tmp_path, backend=FakeBackend(available=False))
    click_trigger(w)
    assert w.history.count() == 1 and "Keine Audioausgabe" in w.status.text()
    assert not is_error(w)
    destroy(w)


# ---- animation ----------------------------------------------------------------------------------
def test_no_timer_runs_at_rest_and_the_animation_stops_itself(win):
    assert not win.gun.is_animating()
    click_trigger(win)
    assert win.gun.is_animating() and win.gun.flash_level() > 0 and win.gun.recoil_level() > 0
    steps = 0
    while win.gun.is_animating():
        win.gun._tick()
        steps += 1
        assert steps < 100
    assert win.gun.flash_level() == 0 and win.gun.recoil_level() == 0
    assert win.gun._gun_transform() == win.gun._fit()[0]  # no recoil term left
    assert steps == pytest.approx(gunmod.ANIM_SECONDS * 1000 / gunmod.ANIM_INTERVAL_MS, abs=2)


def test_animation_off_means_no_timer_and_no_motion(win):
    win.anim_check.setChecked(False)
    click_trigger(win)
    assert win.history.count() == 1
    assert not win.gun.is_animating() and win.gun.flash_level() == 0
    assert win.gun.recoil_level() == 0
    fit, _ = win.gun._fit()
    assert win.gun._gun_transform() == fit


def test_switching_animation_off_mid_shot_stops_the_timer(win):
    click_trigger(win)
    assert win.gun.is_animating()
    win.anim_check.setChecked(False)
    assert not win.gun.is_animating()


def test_hiding_or_closing_stops_the_timer(qapp, tmp_path):
    w = make(tmp_path)
    click_trigger(w)
    assert w.gun.is_animating()
    w.hide()
    assert not w.gun.is_animating()
    w.show()
    click_trigger(w)
    w.close()
    assert not w.gun.is_animating()
    destroy(w)


def test_recoil_moves_the_gun_and_flash_changes_pixels(win):
    win.resize(900, 700)
    QApplication.processEvents()
    win.anim_check.setChecked(False)
    idle = win.grab().toImage()
    win.anim_check.setChecked(True)
    win.gun.t = 0.02
    win.gun.update()
    QApplication.processEvents()
    shot = win.grab().toImage()
    muzzle = win.gun.mapTo(win, win.gun._gun_transform().map(gunmod.MUZZLE).toPoint())

    def bright(img: QImage) -> int:
        c = img.pixelColor(muzzle)
        return c.red() + c.green() + c.blue()

    assert bright(shot) > bright(idle) + 150, (bright(shot), bright(idle))
    assert win.gun.recoil_level() > 0.5
    assert win.gun._gun_transform() != win.gun._fit()[0]  # recoil moves the gun
    win.gun._stop_animation()


# ---- history, drag-out -----------------------------------------------------------------
def test_history_items_drag_out_the_shot_wav(win):
    click_trigger(win)
    click_trigger(win)
    mime = win.history.mimeData([win.history.item(0), win.history.item(1)])
    paths = [Path(u.toLocalFile()) for u in mime.urls()]
    assert paths == [win.session.history[0].wav_path, win.session.history[1].wav_path]
    for p in paths:
        with wave.open(str(p)) as w:
            assert w.getsampwidth() == 3 and w.getnframes() > 0


def test_selecting_a_history_row_shows_its_trace_and_replay_plays_it(win):
    win.select_dimension("glitch")
    click_trigger(win)
    win.select_dimension("ion")
    win.sliders["length"].setValue(90)
    click_trigger(win)
    newest_trace = list(win.gun.trace)
    win.history.setCurrentRow(1)
    assert win.gun.trace != newest_trace
    win.replay_btn.click()
    assert win.backend.played[-1] == win.session.history[1].play_path
    win.history.itemDoubleClicked.emit(win.history.item(0))
    assert win.backend.played[-1] == win.session.history[0].play_path


def test_replay_without_selection_says_so(win):
    win.replay_btn.click()
    assert is_error(win) and "Noch kein Schuss" in win.status.text()


def test_history_is_capped_in_the_list_and_files(win):
    win.session.history_limit = 3
    for _ in range(5):
        click_trigger(win)
    assert win.history.count() == 3 and len(win.session.history) == 3
    assert len(list(win.session.work_dir.glob("*.play16.wav"))) == 3


# ---- bank ------------------------------------------------------------------------------
def test_bank_export_writes_a_new_folder_and_opens_it(win, tmp_path):
    win.bank_count.setValue(4)
    win.bank_btn.click()
    folder = tmp_path / "bank" / "laser_bank_001"
    assert sorted(p.suffix for p in folder.iterdir()) == [".json"] * 4 + [".wav"] * 4
    assert win.opened == [folder] and not is_error(win) and "4 Schüssen" in win.status.text()
    assert win.seed_edit.text() == "5"
    win.bank_btn.click()  # again: a second folder, the first stays
    assert (tmp_path / "bank" / "laser_bank_002").is_dir() and len(list(folder.iterdir())) == 8


def test_bank_cancel_changes_nothing(qapp, tmp_path):
    w = BlasterWindow(out_dir=tmp_path, engine=StubLaserEngine(), backend=FakeBackend(),
                      work_dir=tmp_path / "w", ask_dir=lambda p, s: None, bank_writer=FakeWriter())
    w.bank_btn.click()
    assert "abgebrochen" in w.status.text() and not (tmp_path / "bank").exists()
    assert w.session.next_seed == 1
    destroy(w)


def test_bank_without_engine_is_an_error_and_writes_nothing(qapp, tmp_path):
    w = make(tmp_path, engine=None, bank_writer=FakeWriter())
    w.bank_btn.click()
    assert is_error(w) and not (tmp_path / "bank").exists()
    destroy(w)


# ---- look ------------------------------------------------------------------------------
def test_screenshots_are_written_and_not_blank(qapp, tmp_path):
    files = take_screenshots(tmp_path / "shots", sizes=((900, 700),))
    img = QImage(str(files[0]))
    assert not img.isNull() and img.width() >= 900
    xs, ys = range(0, img.width(), 37), range(0, img.height(), 37)
    colours = {img.pixel(x, y) for x in xs for y in ys}
    assert len(colours) > 30
    assert "dpr" in files[0].name


@pytest.mark.parametrize("size", [(560, 520), (900, 700), (1400, 900)])
def test_window_renders_at_several_sizes(win, size):
    win.resize(*size)
    QApplication.processEvents()
    img = win.grab().toImage()
    assert img.width() >= size[0] and not img.isNull()
    assert win.gun.width() > 0


def test_texts_are_honest_and_german(win):
    note = win.findChildren(type(win.status))
    texts = " ".join(label.text() for label in note)
    assert "kein Plugin" in texts and "nicht in Live" in texts
    assert "nicht bewertet" in texts
    for banned in ("robust", "production", "perfekt", "professionell"):
        assert banned not in texts.lower()


def test_repeated_open_fire_close_does_not_crash(qapp, tmp_path):
    """GC-in-paint guard (PR #412): many windows, shots, grabs and teardowns in one process."""
    for i in range(12):
        w = make(tmp_path / f"r{i}", bank_writer=FakeWriter())
        for _ in range(3):
            click_trigger(w)
            w.gun._tick()
            w.grab()
        gc.collect()
        destroy(w)
