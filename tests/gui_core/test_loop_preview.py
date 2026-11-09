"""#553: loop preview on a 4/4 grid. Hit positions are checked against values written here
(sample = round(sixteenth * 15 * sr / bpm), computed by hand or with exact fractions in the
test), not against the module's own helper."""

from __future__ import annotations

import json
import random
from fractions import Fraction

import numpy as np
import pytest

from gui_core import loop_preview as lp


def impulse(n: int = 1) -> np.ndarray:
    x = np.zeros(n)
    x[0] = 0.5
    return x


def onsets(loop: np.ndarray) -> list[int]:
    return [int(i) for i in np.flatnonzero(np.abs(loop[:, 0]) > 1e-9)]


# ---- grid --------------------------------------------------------------------------------------
def test_hit_positions_at_140_and_120_bpm_written_out():
    # 140 BPM, 48 kHz: a sixteenth is 48000 * 60 / 140 / 4 = 5142.857 samples
    assert lp.hit_positions("Viertel", 140, 48000) == [0, 20571, 41143, 61714]
    assert lp.loop_samples(140, 48000, 1) == 82286  # 4 beats = 82285.714
    # 120 BPM: a sixteenth is exactly 6000 samples
    assert lp.hit_positions("2 und 4", 120, 48000) == [24000, 72000]
    assert lp.hit_positions("Offbeat-Achtel", 120, 48000) == [12000, 36000, 60000, 84000]
    assert lp.hit_positions("einmal pro Takt", 120, 48000, bars=2) == [0, 96000]
    assert lp.loop_samples(120, 48000, 2) == 192000


def test_loop_has_its_hits_exactly_there_over_random_tempi_patterns_and_rates():
    rng = random.Random(553)
    for _ in range(200):
        bpm = rng.choice([rng.randint(60, 200), round(rng.uniform(60, 200), 2)])
        sr = rng.choice([44100, 48000])
        bars = rng.choice([1, 2])
        pattern = rng.choice(list(lp.PATTERNS))
        loop = lp.render_loop(impulse(), sr, bpm, pattern, bars)
        # independent: exact fraction, round half up, written here
        n = int(Fraction(bars * 4 * 60 * sr) / Fraction(bpm) + Fraction(1, 2))
        assert loop.shape == (n, 2), (bpm, sr, bars)
        steps = {"Viertel": [0, 4, 8, 12], "Offbeat-Achtel": [2, 6, 10, 14], "2 und 4": [4, 12],
                 "Achtel": list(range(0, 16, 2)), "Sechzehntel": list(range(16)),
                 "einmal pro Takt": [0]}[pattern]
        want = [int(Fraction((16 * b + s) * 15 * sr) / Fraction(bpm) + Fraction(1, 2))
                for b in range(bars) for s in steps]
        want = [p for p in want if p < n - int(round(lp.FADE_MS * sr / 1000))]  # not faded out
        got = [p for p in onsets(loop) if p < n - int(round(lp.FADE_MS * sr / 1000))]
        assert got == want, (bpm, sr, bars, pattern)


def test_overlapping_hits_sum_tails_are_cut_at_the_loop_end_with_a_fade():
    sr, bpm = 48000, 120  # sixteenth = 6000 samples, bar = 96000
    tone = np.full(30000, 0.1)  # longer than a quarter: hits overlap
    loop = lp.render_loop(tone, sr, bpm, "Viertel")
    assert loop.shape == (96000, 2)
    assert loop[100, 0] == pytest.approx(0.1)  # one hit
    assert loop[24100, 0] == pytest.approx(0.2)  # hit 1 still ringing + hit 2
    assert loop[-1, 0] == 0.0 and loop[-1, 1] == 0.0  # faded to zero at the loop point
    fade = int(round(lp.FADE_MS * sr / 1000))
    # only the 4th hit (72000 .. 102000) rings at the end: cut there, untouched before the fade
    assert loop[-fade - 1, 0] == pytest.approx(0.1)


def test_loud_sums_are_turned_down_to_the_ceiling_never_clipped():
    loud = np.full(48000, 0.9)
    loop = lp.render_loop(loud, 48000, 200, "Sechzehntel", kick=np.full(48000, 0.9))
    assert np.max(np.abs(loop)) == pytest.approx(lp.CEILING)
    data = lp.loop_wav_bytes(loud, 48000, 200, "Sechzehntel")
    ints = np.frombuffer(data[44:], dtype="<i2")
    assert np.max(np.abs(ints)) < 32767  # -1 dBFS, no full-scale samples


def test_kick_lands_on_every_quarter_and_the_sample_on_its_pattern():
    sr, bpm = 48000, 120
    loop = lp.render_loop(impulse(), sr, bpm, "2 und 4", kick=impulse() * 0.5)
    hits = {p: round(float(loop[p, 0]), 4) for p in onsets(loop)}
    assert hits == {0: 0.25, 24000: 0.75, 48000: 0.25, 72000: 0.75}


def test_stereo_samples_keep_their_channels_and_loops_play_as_they_are():
    st = np.zeros((10, 2))
    st[0] = (0.3, -0.2)
    loop = lp.render_loop(st, 48000, 120, "einmal pro Takt")
    assert tuple(loop[0]) == (0.3, -0.2)
    bed = np.linspace(-0.5, 0.5, 4800)
    as_is = lp.render_loop(bed, 48000, 120, lp.AS_IS, kick=impulse())
    assert as_is.shape == (4800, 2) and as_is[100, 0] == pytest.approx(bed[100])


def test_wrong_input_is_refused_in_german():
    with pytest.raises(lp.LoopError, match="Tempo"):
        lp.render_loop(impulse(), 48000, 300, "Viertel")
    with pytest.raises(lp.LoopError, match="Muster"):
        lp.render_loop(impulse(), 48000, 120, "Walzer")
    with pytest.raises(lp.LoopError, match="Takte"):
        lp.render_loop(impulse(), 48000, 120, "Viertel", bars=3)


def test_same_input_gives_the_same_bytes():
    x = np.random.default_rng(1).uniform(-0.5, 0.5, 5000)
    a = lp.loop_wav_bytes(x, 48000, 137, "Achtel", 2, impulse())
    assert a == lp.loop_wav_bytes(x, 48000, 137, "Achtel", 2, impulse())


# ---- defaults per category ---------------------------------------------------------------------
def test_default_pattern_per_category_from_sidecar_or_name(tmp_path):
    want = {"kick": "Viertel", "clap": "2 und 4", "snare": "2 und 4", "hat": "Offbeat-Achtel",
            "rim": "Achtel", "perc": "Achtel", "bass": "Offbeat-Achtel",
            "laser": "einmal pro Takt", "fx": "einmal pro Takt", "atmos": lp.AS_IS}
    for cat, pat in want.items():
        assert lp.default_pattern(cat) == pat
    assert lp.default_pattern(None) == "einmal pro Takt"
    w = tmp_path / "x.wav"
    w.write_bytes(b"")
    w.with_suffix(".json").write_text(json.dumps({"category": "hat"}), encoding="utf-8")
    assert lp.category_of(w) == "hat"
    w.with_suffix(".json").write_text(json.dumps({"schema_version": "0.1"}), encoding="utf-8")
    assert lp.category_of(w) == "kick"  # first sidecar format: kicks
    assert lp.category_of(tmp_path / "snare_default_s1_v0.wav") == "snare"  # no sidecar
    assert lp.category_of(tmp_path / "mystery.wav") is None


def test_default_kick_renders_at_the_sample_rate():
    k = lp.default_kick(48000)
    assert k.ndim == 1 and 1000 < len(k) < 48000 * 3 and np.max(np.abs(k)) > 0.5
