"""Rough preview: deterministic, finite, bounded, reacts to the line. No sound-quality claim."""

from __future__ import annotations

import numpy as np
import pytest

from gui_core.acid_generate import GenOptions, generate_line
from gui_core.acid_preview import SAMPLE_RATE, preview_wav_bytes, render_preview


def _line(steps, length=None):
    return {"format": "acid_line", "version": "0.1-proposal", "length": length or len(steps),
            "steps": steps}


def test_deterministic_bytes_and_length():
    line = generate_line(GenOptions(seed=5, slide_chance=0.5))
    a, b = preview_wav_bytes(line, 130.0), preview_wav_bytes(line, 130.0)
    assert a == b and a[:4] == b"RIFF"
    x = render_preview(line, 130.0)
    # 16 steps of 0.25 beat at 130 BPM = 1.846 s, plus a 0.15 s tail
    assert abs(len(x) / SAMPLE_RATE - (16 * 0.25 * 60 / 130 + 0.15)) < 0.01
    assert np.all(np.isfinite(x)) and 0.5 < np.max(np.abs(x)) <= 0.8001


def test_silent_line_is_silent_and_tempo_scales_length():
    silent = render_preview(_line([{"on": False}] * 4), 120.0)
    assert not silent.any()
    n120 = len(render_preview(_line([{"on": True, "note": 45}] * 4), 120.0))
    n60 = len(render_preview(_line([{"on": True, "note": 45}] * 4), 60.0))
    assert n60 > n120


def test_accent_slide_and_pitch_change_the_audio():
    base = [{"on": True, "note": 45}, {"on": True, "note": 52}, {"on": False}, {"on": False}]
    ref = render_preview(_line(base), 120.0)
    acc = [dict(base[0], accent=True)] + base[1:]
    sl = [dict(base[0], slide=True)] + base[1:]
    hi = [dict(base[0], note=57)] + base[1:]
    for variant in (acc, sl, hi):
        assert not np.array_equal(ref, render_preview(_line(variant), 120.0))


def test_bad_bpm_rejected():
    line = _line([{"on": True, "note": 45}])
    for bad in (10.0, 401.0):
        with pytest.raises(ValueError):
            render_preview(line, bad)
