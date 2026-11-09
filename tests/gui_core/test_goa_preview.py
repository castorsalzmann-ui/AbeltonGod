"""Goa clip preview (D-035 (2), #546): deterministic, bounded, finite, follows the notes.

No sound-quality claim: the checks are bytes, length, peak and where the energy sits.
"""

from __future__ import annotations

import random

import numpy as np
import pytest

from audio_engine import goa_clips
from gui_core import goa_preview as gp

SR = 22050


@pytest.mark.parametrize("voice", goa_clips.VOICES)
def test_voice_preview_deterministic_length_peak(voice):
    a = gp.voice_preview_wav_bytes(voice, seed=3, bars=2, bpm=140)
    assert a == gp.voice_preview_wav_bytes(voice, seed=3, bars=2, bpm=140)
    assert a[:4] == b"RIFF" and a[8:12] == b"WAVE"
    x = gp.render_voice_preview(voice, seed=3, bars=2, bpm=140)
    # 2 bars of 4 beats at 140 bpm = 3.4286 s, plus the 0.5 s tail
    assert abs(len(x) - (8 * 60 / 140 + 0.5) * SR) <= 1
    assert x.dtype == np.float32 and np.all(np.isfinite(x))
    assert abs(float(np.max(np.abs(x))) - 0.8) < 1e-6
    assert abs(float(x[-1])) < 1e-6  # ends at silence (fade)
    assert len(a) == 44 + 2 * len(x)


def test_mix_preview_deterministic_and_uses_every_voice():
    m = gp.mix_preview_wav_bytes(seed=11, bars=1)
    assert m == gp.mix_preview_wav_bytes(seed=11, bars=1)
    mix = gp.render_mix_preview(seed=11, bars=1)
    assert abs(float(np.max(np.abs(mix))) - 0.8) < 1e-6
    singles = {v: gp.render_voice_preview(v, seed=11, bars=1) for v in goa_clips.VOICES}
    for v, s in singles.items():
        assert not np.allclose(mix, s, atol=1e-3), v
    only_pad = gp.render_mix_preview(seed=11, bars=1, voices=["pad"])
    np.testing.assert_allclose(only_pad, singles["pad"], atol=1e-6)
    no_lead = gp.render_mix_preview(seed=11, bars=1, voices=["arp", "pad", "pluck"])
    assert not np.allclose(no_lead, mix, atol=1e-3)
    # two voices: the mix is lead (gain 1.0) + pad (gain 0.6), each at its own peak,
    # renormalised to 0.8; rebuilt here from the single-voice previews
    two = gp.render_mix_preview(seed=11, bars=1, voices=["lead", "pad"])
    ref = singles["lead"] / 0.8 + 0.6 * singles["pad"] / 0.8
    ref = ref * (0.8 / np.max(np.abs(ref)))
    np.testing.assert_allclose(two, ref, atol=2e-3)


def test_longest_clip_is_bounded():
    x = gp.render_mix_preview(seed=0, bars=16, bpm=135)
    assert len(x) / SR <= gp.MAX_SECONDS
    assert abs(len(x) / SR - (64 * 60 / 135 + 0.5)) < 1e-3


def test_silent_voice_is_silent():
    x = gp.render_voice_preview("lead", seed=2, density=0.0)
    assert not x.any()
    assert gp.voice_preview_wav_bytes("lead", seed=2, density=0.0)[44:] == bytes(2 * len(x))


def test_pad_energy_sits_at_its_chord_tones():
    # A phrygian, pad density 0 -> one 4-bar triad on degree 0 (A C E) in window 48-59:
    # MIDI 48, 52, 57 = 130.81, 164.81, 220.00 Hz (written out here).
    x = gp.render_voice_preview("pad", seed=0, voices=["pad"])
    spec = np.abs(np.fft.rfft(x.astype(np.float64)))
    freqs = np.fft.rfftfreq(len(x), 1 / SR)
    top = sorted(freqs[np.argsort(spec)[-30:]])
    for f0 in (130.81, 164.81, 220.00):
        assert any(abs(f - f0) < 2.0 for f in top), (f0, top)
    assert all(min(abs(f - f0) for f0 in (130.81, 164.81, 220.00)) < 2.0 for f in top)


def test_onsets_follow_the_notes():
    # pluck at density 0.25: 4 notes in one bar; sound only where a 16th carries a note
    # (or rings on from the previous one). Positions are read from the notes.
    opts = {"seed": 4, "bars": 1, "density": {"pluck": 0.25}, "bpm": 144}
    x = gp.render_voice_preview("pluck", **opts)
    starts = {n.start for n in goa_clips.clip_notes("pluck", **opts)}
    step = int(round(120 * 60 / 144 / 480 * SR))  # one 16th in samples
    for k in range(16):
        seg = np.abs(x[k * step + step // 4: k * step + step // 2])
        if k * 120 in starts:
            assert seg.max() > 0.05, k
        elif (k - 1) * 120 not in starts:
            assert seg.max() < 1e-3, k


def test_property_random_options():
    rng = random.Random(5460)
    for _ in range(12):
        opts = {"seed": rng.randint(0, 10**6), "bars": rng.randint(1, 16),
                "bpm": round(rng.uniform(135, 150), 1),
                "root": rng.choice(["A", "C#", "Eb", "G", "B"]),
                "scale": rng.choice(["phrygian", "phrygian_dominant", "harmonic_minor",
                                     "aeolian"]),
                "density": round(rng.random(), 2), "register": rng.randint(-2, 2),
                "arp_pattern": rng.choice(["up", "down", "updown", "random"])}
        v = rng.choice(list(goa_clips.VOICES))
        x = gp.render_voice_preview(v, **opts)
        assert np.all(np.isfinite(x)) and len(x) / SR <= gp.MAX_SECONDS
        assert abs(len(x) - (opts["bars"] * 240 / opts["bpm"] + 0.5) * SR) <= 1
        peak = float(np.max(np.abs(x)))
        assert peak == 0.0 or abs(peak - 0.8) < 1e-6
        assert peak > 0 or not goa_clips.clip_notes(v, **opts)


def test_invalid_input_raises():
    with pytest.raises(ValueError):
        gp.render_voice_preview("bass", seed=0)
    with pytest.raises(ValueError):
        gp.render_mix_preview(seed=0, bars=17)
    with pytest.raises(ValueError):
        gp.voice_preview_wav_bytes("lead", sections=[])
    assert gp.PREVIEW_LABEL == "grobe Vorschau"
