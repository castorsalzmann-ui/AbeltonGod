"""Waveform reader, preview controller and the no-Qt rule for gui_core."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

import gui_core
from audio_engine.io import encode_wav
from gui_core.preview import ERROR, IDLE, LOADED, PLAYING, PreviewController
from gui_core.waveform import WaveformError, load_waveform, peaks

SRC = Path(gui_core.__file__).resolve().parents[1]  # the tree under test, not a fixed path


def write_wav(path: Path, audio, sr=48000, bits=24) -> Path:
    path.write_bytes(encode_wav(np.asarray(audio, dtype=float), sr, bits))
    return path


def test_load_waveform_values_24_and_16_bit(tmp_path):
    audio = [0.0, 0.5, -0.5, 1.0, -1.0, 0.25]
    for bits in (16, 24):
        wf = load_waveform(write_wav(tmp_path / f"a{bits}.wav", audio, 44100, bits))
        assert (wf.sample_rate, wf.bit_depth) == (44100, bits)
        np.testing.assert_allclose(wf.samples, audio, atol=2.0 ** -(bits - 1))
        assert wf.duration_s == pytest.approx(6 / 44100)


def test_load_waveform_errors(tmp_path):
    with pytest.raises(WaveformError):
        load_waveform(tmp_path / "missing.wav")
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not a wav at all, definitely longer than forty-four bytes of junk!!")
    with pytest.raises(WaveformError):
        load_waveform(bad)
    with pytest.raises(WaveformError):
        load_waveform(write_wav(tmp_path / "empty.wav", []))


def test_peaks_expected_values():
    s = np.array([0.1, -0.2, 0.5, 0.4, -0.9, 0.0, 0.3, 0.2])
    assert peaks(s, 4) == [(-0.2, 0.1), (0.4, 0.5), (-0.9, 0.0), (0.2, 0.3)]
    assert peaks(s, 1) == [(-0.9, 0.5)]
    assert peaks(np.array([0.5, -0.5]), 4) == [(0.5, 0.5), (0.5, 0.5), (-0.5, -0.5), (-0.5, -0.5)]
    assert peaks(np.array([]), 3) == [(0.0, 0.0)] * 3
    with pytest.raises(ValueError):
        peaks(s, 0)


def test_peaks_cover_every_sample_for_any_size():
    rng = np.random.default_rng(1)
    for n in (1, 2, 7, 100, 4801):
        s = rng.uniform(-1, 1, n)
        for b in (1, 3, 50, 300):
            p = peaks(s, b)
            assert len(p) == b
            assert min(lo for lo, _ in p) == s.min() and max(hi for _, hi in p) == s.max()


class FakeBackend:
    def __init__(self, available=True, fail=False):
        self.available, self.fail = available, fail
        self.played: list[Path] = []
        self.stops = 0

    def play(self, wav_path):
        if self.fail:
            raise OSError("device busy")
        self.played.append(wav_path)

    def stop(self):
        self.stops += 1


class Clock:
    t = 100.0

    def __call__(self):
        return self.t


def test_preview_load_play_stop_and_playhead(tmp_path):
    src = write_wav(tmp_path / "k.wav", np.linspace(-0.5, 0.5, 4800), 48000, 24)  # 0.1 s
    be, clock = FakeBackend(), Clock()
    p = PreviewController(be, clock)
    assert p.state == IDLE and not p.play()
    assert p.load(src) and p.state == LOADED
    assert p.waveform.duration_s == pytest.approx(0.1)
    assert p.play() and p.state == PLAYING
    # the backend got a 16-bit copy, not the original
    assert be.played[0] != src
    assert be.played[0].read_bytes()[34:36] == (16).to_bytes(2, "little")
    clock.t += 0.04
    assert p.position() == pytest.approx(0.04)
    p.tick()
    assert p.state == PLAYING
    clock.t += 0.2
    assert p.position() == pytest.approx(0.1)
    p.tick()
    assert p.state == LOADED
    assert p.play()
    p.stop()
    assert p.state == LOADED and be.stops == 1
    p.close()
    assert not be.played[0].exists()


def test_preview_errors_are_messages_not_exceptions(tmp_path):
    src = write_wav(tmp_path / "k.wav", [0.1, 0.2, 0.3])
    p = PreviewController(FakeBackend(available=False))
    assert p.load(src) and not p.play()
    assert p.state == ERROR and "Audioausgabe" in p.message
    p = PreviewController(FakeBackend(fail=True))
    p.load(src)
    assert not p.play() and p.state == ERROR and "device busy" in p.message
    p = PreviewController(FakeBackend())
    assert not p.load(tmp_path / "nope.wav") and p.state == ERROR and p.waveform is None


def test_gui_core_never_imports_qt():
    code = (
        "import sys, gui_core, gui_core.form, gui_core.render, gui_core.preview, "
        "gui_core.waveform, gui_core.categories, gui_core.paths;"
        "qt=('PySide6','PyQt5','PyQt6','shiboken6');"
        "bad=[m for m in sys.modules if m.split('.')[0] in qt];"
        "print(bad); sys.exit(1 if bad else 0)"
    )
    run = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60,
        env={"PYTHONPATH": str(SRC), "PATH": "", "SYSTEMROOT": "C:\\Windows"},
    )
    assert run.returncode == 0, run.stdout + run.stderr
    for py in (SRC / "gui_core").glob("*.py"):
        text = py.read_text(encoding="utf-8")
        assert "PySide6" not in text and "PyQt" not in text, py.name
