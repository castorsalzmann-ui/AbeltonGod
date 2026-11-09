"""#545 / D-035 (3): one output volume for every preview, default 45 %, remembered in the
settings, scaling only playback (a scaled temp copy), never the files on disk."""

from __future__ import annotations

import json
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
from gui_core import volume as vol  # noqa: E402
from gui_core.settings import (  # noqa: E402
    AppSettings,
    SettingsStore,
    load_settings,
    settings_from_json,
)


def data_samples(data: bytes) -> np.ndarray:
    """int16 samples of the data chunk, read with this test's own RIFF walk."""
    pos = 12
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        if cid == b"data":
            return np.frombuffer(data[pos + 8:pos + 8 + size], dtype="<i2").astype(np.int64)
        pos += 8 + size + (size & 1)
    raise AssertionError("no data chunk")


class Recorder:
    available = True

    def __init__(self) -> None:
        self.played: list[bytes] = []
        self.paths: list[Path] = []

    def play(self, wav_path) -> None:
        self.paths.append(Path(wav_path))
        self.played.append(Path(wav_path).read_bytes())

    def stop(self) -> None:
        pass


@pytest.fixture(scope="module")
def qapp():
    return create_app([])


@pytest.fixture(autouse=True)
def reset_volume():
    vol.OUTPUT.set(vol.DEFAULT_VOLUME)
    yield
    vol.OUTPUT.set(vol.DEFAULT_VOLUME)


@pytest.fixture
def wav(tmp_path) -> Path:
    t = np.arange(4800) / 48000
    stereo = np.stack([np.sin(2 * np.pi * 220 * t), -np.sin(2 * np.pi * 330 * t)], axis=1) * 0.9
    p = tmp_path / "shot.wav"
    p.write_bytes(encode_wav(stereo, 48000, 16))
    return p


# ---- settings ----------------------------------------------------------------------------------
def test_fresh_settings_start_at_45_percent_and_a_bad_value_falls_back(tmp_path):
    assert AppSettings().output_volume == 45
    assert load_settings(tmp_path / "missing.json").output_volume == 45
    for bad in (101, -1, "50", 50.5, True, None):
        assert settings_from_json({"output_volume": bad}).output_volume == 45, bad
    assert settings_from_json({"output_volume": 0}).output_volume == 0
    assert settings_from_json({"output_volume": 100}).output_volume == 100


def test_volume_is_saved_and_read_back(tmp_path):
    cfg = tmp_path / "settings.json"
    store = SettingsStore(path=cfg)
    store.update(output_volume=70)
    assert json.loads(cfg.read_text(encoding="utf-8"))["output_volume"] == 70
    assert SettingsStore(path=cfg).settings.output_volume == 70
    with pytest.raises(ValueError):
        store.update(output_volume=120)


# ---- playback scaling --------------------------------------------------------------------------
@pytest.mark.parametrize("percent", [0, 45, 100])
def test_playback_copy_is_scaled_and_the_file_on_disk_is_unchanged(wav, percent):
    original = wav.read_bytes()
    rec = Recorder()
    b = vol.VolumeBackend(rec, lambda: percent)
    b.play(wav)
    assert wav.read_bytes() == original  # the written file keeps its bytes
    assert rec.paths[0] != wav and rec.paths[0].parent != wav.parent
    played = rec.played[0]
    assert played[:44] == original[:44]  # same format and size
    src = data_samples(original)
    expected = np.round(src * percent / 100.0)  # written here, not taken from the code
    assert np.array_equal(data_samples(played), expected)
    b.close()


def test_volume_follows_the_shared_value_at_play_time(wav):
    rec = Recorder()
    b = vol.VolumeBackend(rec)  # default: reads vol.OUTPUT
    b.play(wav)
    vol.OUTPUT.set(90)
    b.play(wav)
    src = data_samples(wav.read_bytes())
    peak = int(np.max(np.abs(src)))
    assert int(np.max(np.abs(data_samples(rec.played[0])))) == round(peak * 0.45)
    assert int(np.max(np.abs(data_samples(rec.played[1])))) == round(peak * 0.90)
    assert rec.paths[0] != rec.paths[1]  # alternating copies: a playing file is never rewritten
    b.close()


def test_a_24_bit_file_is_refused_in_german_not_played_loud(tmp_path):
    p = tmp_path / "w24.wav"
    p.write_bytes(encode_wav(np.zeros(100), 48000, 24))
    rec = Recorder()
    with pytest.raises(RuntimeError, match="16-Bit"):
        vol.VolumeBackend(rec, lambda: 45).play(p)
    assert rec.played == []


@pytest.mark.skipif(sys.platform != "win32", reason="winsound only on Windows")
def test_the_windows_backend_plays_through_the_volume():
    from gui.audio import WinsoundBackend, choose_backend

    b = choose_backend()
    assert isinstance(b, vol.VolumeBackend) and isinstance(b.inner, WinsoundBackend)


# ---- windows -----------------------------------------------------------------------------------
def test_every_preview_window_shows_the_same_control_and_moving_one_moves_all(qapp, tmp_path):
    from gui.acid.window import AcidWindow
    from gui.blaster.window import BlasterWindow
    from gui.main_window import MainWindow
    from gui_core.blaster_stub import StubLaserEngine

    cfg = tmp_path / "cfg" / "settings.json"
    main = MainWindow(out_dir=tmp_path / "out", backend=Recorder(),
                      settings_store=SettingsStore(path=cfg))
    acid = AcidWindow(out_dir=tmp_path / "acid", backend=Recorder())
    blaster = BlasterWindow(engine=StubLaserEngine(), backend=Recorder(),
                            out_dir=tmp_path / "b", work_dir=tmp_path / "bw")
    wins = (main, acid, blaster)
    try:
        for w in wins:
            w.show()
        QApplication.processEvents()
        for w in wins:
            assert w.volume.slider.value() == 45 and w.volume.readout.text() == "45 %"
            assert w.volume.isVisible()
        acid.volume.slider.setValue(62)
        assert vol.OUTPUT.value == 62
        assert main.volume.slider.value() == 62 and blaster.volume.readout.text() == "62 %"
        main._volume_save.timeout.emit()  # what the 400 ms timer does
        assert load_settings(cfg).output_volume == 62
    finally:
        for w in wins:
            w.close()
        QApplication.processEvents()


def test_main_window_starts_with_the_saved_volume_and_saves_a_pending_change_on_close(
        qapp, tmp_path):
    from gui.main_window import MainWindow

    cfg = tmp_path / "settings.json"
    SettingsStore(path=cfg).update(output_volume=30)
    w = MainWindow(out_dir=tmp_path / "out", backend=Recorder(),
                   settings_store=SettingsStore(path=cfg))
    assert vol.OUTPUT.value == 30 and w.volume.slider.value() == 30
    w.volume.slider.setValue(80)
    assert w._volume_save.isActive()
    w.close()
    QApplication.processEvents()
    assert load_settings(cfg).output_volume == 80
