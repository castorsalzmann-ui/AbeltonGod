"""#553: "Im Takt ▶" on the main window (results and library share its transport) and on the
Blaster; loop played through the backend's play_loop until Stopp; tempo remembered. On
Windows CI the real winsound loop flags are exercised (no sound device there, so with the
device probe forced to 1, as in the #543 probe: async PlaySound reports nothing)."""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

if os.environ.get("ABELTONGOD_REQUIRE_GUI") == "1":
    import PySide6.QtWidgets  # noqa: F401
else:
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtWidgets import QApplication  # noqa: E402

from audio_engine.io import encode_wav  # noqa: E402
from gui.app import create_app  # noqa: E402
from gui_core.settings import SettingsStore, load_settings  # noqa: E402


class LoopRecorder:
    available = True

    def __init__(self) -> None:
        self.loops: list[bytes] = []
        self.played: list[Path] = []
        self.stopped = 0

    def play(self, wav_path) -> None:
        self.played.append(Path(wav_path))

    def play_loop(self, wav_path) -> None:
        self.loops.append(Path(wav_path).read_bytes())

    def stop(self) -> None:
        self.stopped += 1


def frames(data: bytes) -> int:
    ch, = struct.unpack("<H", data[22:24])
    size, = struct.unpack("<I", data[40:44])
    return size // (2 * ch)


@pytest.fixture(scope="module")
def qapp():
    return create_app([])


def test_main_window_loops_the_selected_sample_with_its_category_pattern(qapp, tmp_path):
    from gui.main_window import MainWindow

    cfg = tmp_path / "settings.json"
    backend = LoopRecorder()
    w = MainWindow(out_dir=tmp_path / "out", backend=backend,
                   settings_store=SettingsStore(path=cfg))
    try:
        w.show()
        QApplication.processEvents()
        w.loop_bar.play_button.click()  # nothing selected: says so, plays nothing
        assert "Erst ein Sample" in w.preview_info.text() and backend.loops == []
        hat = tmp_path / "hat_closed_s1_v0.wav"
        hat.write_bytes(encode_wav(np.full(480, 0.5), 48000, 24))
        w._load_preview(hat)
        assert w.loop_bar.pattern == "Offbeat-Achtel"  # the hat's default
        assert w.loop_bar.bpm == 140
        w.loop_bar.bpm_spin.setValue(120)
        assert load_settings(cfg).loop_bpm == 120
        w.loop_bar.play_button.click()
        assert len(backend.loops) == 1
        assert frames(backend.loops[0]) == 96000  # 1 bar at 120 BPM, 48 kHz
        assert "Spielt im Takt: Offbeat-Achtel, 120 BPM" in w.preview_info.text()
        assert w.preview.looping
        w.stop_button.click()
        assert backend.stopped >= 1 and not w.preview.looping
    finally:
        w.close()
        QApplication.processEvents()


def test_main_window_starts_with_the_saved_tempo(qapp, tmp_path):
    from gui.main_window import MainWindow

    cfg = tmp_path / "settings.json"
    SettingsStore(path=cfg).update(loop_bpm=150)
    w = MainWindow(out_dir=tmp_path / "out", backend=LoopRecorder(),
                   settings_store=SettingsStore(path=cfg))
    try:
        assert w.loop_bar.bpm == 150
    finally:
        w.close()


def test_blaster_loops_a_shot_with_kick_and_stops(qapp, tmp_path):
    from gui.blaster.window import BlasterWindow
    from gui_core.blaster_stub import StubLaserEngine

    backend = LoopRecorder()
    w = BlasterWindow(engine=StubLaserEngine(), backend=backend, out_dir=tmp_path / "out",
                      work_dir=tmp_path / "w")
    try:
        assert not w.loop_selected()  # no shot yet
        assert "Noch kein Schuss" in w.status.text()
        w.session.fire(play=False)
        w.history.clear()
        assert w.loop_bar.pattern == "einmal pro Takt"
        w.loop_bar.kick_box.setChecked(True)
        w.loop_bar.bpm_spin.setValue(120)
        assert w.loop_selected()
        assert len(backend.loops) == 1 and frames(backend.loops[0]) == 96000
        assert "mit Kick" in w.status.text()
        w.loop_bar.stop_button.click()
        assert backend.stopped >= 1
    finally:
        w.close()


def test_a_backend_without_loop_says_so(qapp, tmp_path):
    from gui_core.preview import PreviewController

    class Plain:
        available = True

        def play(self, p):
            pass

        def stop(self):
            pass

    pc = PreviewController(Plain())
    assert not pc.play_loop(b"RIFF")
    assert "Schleife" in pc.message


@pytest.mark.skipif(sys.platform != "win32", reason="winsound only on Windows")
def test_windows_winsound_loop_starts_and_stops_without_error(tmp_path):
    from gui.audio import WinsoundBackend
    from gui_core.loop_preview import loop_wav_bytes
    from gui_core.volume import VolumeBackend

    p = tmp_path / "loop.wav"
    p.write_bytes(loop_wav_bytes(np.full(480, 0.3), 48000, 140, "Viertel"))
    b = VolumeBackend(WinsoundBackend(devices=lambda: 1), lambda: 45)
    b.play_loop(p)
    b.stop()
    b.close()
