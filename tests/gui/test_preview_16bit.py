"""#462: every file the GUI hands to the sound backend is 16-bit PCM (winsound's PlaySound is not
established to play 24-bit, research note 2026-11-06 F4/F7), and the winsound flags. Offscreen,
fake backend (no sound device). Teardown: autouse fixture of tests/gui/conftest.py."""

from __future__ import annotations

import os
import struct
from pathlib import Path

import numpy as np
import pytest

if os.environ.get("ABELTONGOD_REQUIRE_GUI") == "1":
    import PySide6.QtWidgets  # noqa: F401
else:
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from audio_engine.io import encode_wav  # noqa: E402
from gui.app import create_app  # noqa: E402


def wav_format(path: Path) -> tuple[int, int]:
    """(format tag, bits per sample) read from the RIFF header, independent of our code."""
    data = Path(path).read_bytes()
    assert data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    pos = 12
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        if cid == b"fmt ":
            tag, _ch, _sr, _br, _align, bits = struct.unpack("<HHIIHH", data[pos + 8:pos + 24])
            return tag, bits
        pos += 8 + size + (size & 1)
    raise AssertionError("no fmt chunk")


class CheckingBackend:
    """Records the format of every file at the moment it is handed to play()."""

    available = True

    def __init__(self) -> None:
        self.formats: list[tuple[int, int]] = []

    def play(self, wav_path) -> None:
        self.formats.append(wav_format(wav_path))

    def stop(self) -> None:
        pass


@pytest.fixture(scope="module")
def qapp():
    return create_app([])


@pytest.fixture
def wav24(tmp_path) -> Path:
    t = np.arange(4800) / 48000
    stereo = np.stack([np.sin(2 * np.pi * 220 * t), np.sin(2 * np.pi * 330 * t)], axis=1) * 0.5
    p = tmp_path / "in24.wav"
    p.write_bytes(encode_wav(stereo, 48000, 24))
    assert wav_format(p) == (1, 24)  # the input really is 24-bit
    return p


def test_main_window_preview_plays_a_16_bit_copy_of_a_24_bit_file(qapp, tmp_path, wav24):
    from gui.main_window import MainWindow

    backend = CheckingBackend()
    w = MainWindow(out_dir=tmp_path / "out", backend=backend, opener=lambda p: True)
    assert w.preview.load(wav24)
    w.play()
    assert backend.formats == [(1, 16)]


def test_acid_preview_plays_16_bit(qapp, tmp_path):
    from gui.acid.window import AcidWindow

    backend = CheckingBackend()
    w = AcidWindow(out_dir=tmp_path / "out", backend=backend)
    w.preview()
    assert backend.formats == [(1, 16)]


def test_blaster_shot_and_live_preview_play_16_bit(qapp, tmp_path):
    from gui.blaster.window import BlasterWindow
    from gui_core.blaster_stub import StubLaserEngine

    backend = CheckingBackend()
    w = BlasterWindow(engine=StubLaserEngine(), backend=backend, out_dir=tmp_path / "out",
                      work_dir=tmp_path / "work")
    w.session.fire()
    w.session.play_preview(np.zeros((480, 2)))
    assert backend.formats == [(1, 16), (1, 16)]


def test_winsound_flags_never_play_the_default_sound_and_stop_without_purge(monkeypatch):
    import sys
    import types

    from gui import audio

    calls = []
    fake = types.SimpleNamespace(SND_FILENAME=0x20000, SND_ASYNC=0x1, SND_NODEFAULT=0x2,
                                 SND_PURGE=0x40,
                                 PlaySound=lambda sound, flags: calls.append((sound, flags)))
    monkeypatch.setitem(sys.modules, "winsound", fake)
    b = audio.WinsoundBackend(devices=lambda: 1)  # the runner has no device (#543 probe)
    b.play(Path("x.wav"))
    b.stop()
    # values from the Windows SDK (mmsystem.h), written here, not taken from the code
    assert calls == [("x.wav", 0x20000 | 0x1 | 0x2), (None, 0)]
