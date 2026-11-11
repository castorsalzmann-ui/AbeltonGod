"""DSP blocks of the rough previews (#571): oscillators, resonant filter, ping-pong echoes.

Every expected value is written here or computed by another method than the code under test:
an explicit sum of sines for the oscillators, a plain per-sample loop and the analogue
magnitude formula for the filter, literal gains and positions for the echoes. No statement
about sound.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from gui_core import preview_dsp as dsp

SR = 44100


def additive(f0: float, start_phase: float, n: int, odd_only: bool) -> np.ndarray:
    """Sum of the sines of all harmonics below 0.45 * SR, written out one by one. Partial k
    has the amplitude (2 / pi) / k (saw) or (4 / pi) / k (square) times x / sin(x),
    x = pi * k * f0 / SR (the weight the module documents)."""
    t = np.arange(n) / SR
    out = np.zeros(n)
    for k in range(1, int(0.45 * SR / f0) + 1, 2 if odd_only else 1):
        x = math.pi * k * f0 / SR
        amp = (4.0 if odd_only else 2.0) / math.pi / k * (x / math.sin(x))
        out -= amp * np.sin(2 * math.pi * k * (start_phase + f0 * (t + 0.5 / SR)))
    return out


@pytest.mark.parametrize("f0", [16.35, 65.41, 261.63, 987.77, 3951.07, 12543.85])
@pytest.mark.parametrize("phase", [0.5, 0.0, 0.3])
def test_oscillators_are_the_sum_of_their_harmonics_below_the_limit(f0, phase):
    n = SR // 2
    freq = np.full(n, f0)
    assert np.max(np.abs(dsp.saw(freq, SR, phase) - additive(f0, phase, n, False))) < 1e-5
    assert np.max(np.abs(dsp.square(freq, SR, phase) - additive(f0, phase, n, True))) < 1e-5


def test_saw_rises_from_zero_and_stays_centred_over_a_long_note():
    x = dsp.saw(np.full(60 * SR, 262.67), SR)  # 60 s: the running sum must not drift
    assert abs(x[0]) < 0.05 and x[200] > x[0]  # start_phase 0.5: zero crossing, rising
    assert abs(float(np.mean(x[-SR:]))) < 1e-2 and float(np.max(np.abs(x))) < 1.35
    assert abs(float(np.mean(dsp.square(np.full(60 * SR, 262.67), SR)[-SR:]))) < 1e-2


def test_nothing_above_the_harmonic_limit():
    # 3951.07 Hz (MIDI 107): harmonics 1..5 lie below 0.45 * SR = 19845 Hz, the 6th would
    # be at 23706 Hz and fold back to 20394 Hz. One second, whole-number bins of 1 Hz.
    f0 = 3951.07
    for wave in (dsp.saw, dsp.square):
        x = wave(np.full(SR, f0), SR)
        spec = np.abs(np.fft.rfft(x * np.blackman(SR)))
        freqs = np.fft.rfftfreq(SR, 1 / SR)
        ref = float(np.max(spec))
        assert float(np.max(spec[freqs > 19845.0 + 60.0])) < ref * 1e-5  # -100 dB
        stray = np.ones(len(freqs), dtype=bool)
        for k in range(1, 6):
            stray &= np.abs(freqs - k * f0) > 60.0
        assert float(np.max(spec[stray])) < ref * 1e-5


def test_oscillator_rejects_frequencies_outside_its_range():
    for bad in (0.0, -5.0, 0.46 * SR):
        with pytest.raises(ValueError):
            dsp.saw(np.array([440.0, bad]), SR)
    assert len(dsp.saw(np.zeros(0), SR)) == 0 and len(dsp.square(np.zeros(0), SR)) == 0


# --- filter -------------------------------------------------------------------------------
def loop_filter(x: np.ndarray, cutoff: np.ndarray, q: float, band: bool) -> np.ndarray:
    """The same recursion as one plain per-sample loop without chunks (test reference)."""
    s1 = s2 = 0.0
    out = np.zeros(len(x))
    k = 1.0 / q
    for i in range(len(x)):
        g = math.tan(math.pi * cutoff[i] / SR)
        a1 = 1.0 / (1.0 + g * (g + k))
        v3 = x[i] - s2
        v1 = a1 * s1 + g * a1 * v3
        v2 = s2 + g * a1 * s1 + g * g * a1 * v3
        s1, s2 = 2.0 * v1 - s1, 2.0 * v2 - s2
        out[i] = k * v1 if band else v2
    return out


def steady_gain(mode: str, f: float, fc: float, q: float) -> float:
    n = SR
    x = np.sin(2 * np.pi * f * np.arange(n) / SR)
    (y,) = dsp.resonant_filter([x], [np.full(n, fc)], q, SR, mode)
    return float(np.max(np.abs(y[n // 2:])))


@pytest.mark.parametrize("q", [0.707, 4.0, 8.0])
def test_filter_gain_follows_the_two_pole_formula(q):
    # analogue two-pole section, r = f / fc: low-pass 1 / sqrt((1 - r^2)^2 + (r/q)^2),
    # band-pass (r/q) / the same root. fc = 500 Hz is far below SR, so the frequency
    # warping of the digital form stays under the tolerance.
    for r in (0.25, 0.5, 1.0, 2.0, 4.0):
        root = math.sqrt((1 - r * r) ** 2 + (r / q) ** 2)
        assert steady_gain(dsp.LOWPASS, 500.0 * r, 500.0, q) == pytest.approx(1 / root, rel=0.03)
        assert steady_gain(dsp.BANDPASS, 500.0 * r, 500.0, q) == pytest.approx(r / q / root,
                                                                                 rel=0.03)


def test_resonance_peak_sits_at_the_cutoff_also_near_the_top():
    # pre-warping: the band-pass has gain 1 at the cutoff itself, 0.1 % off it is lower
    for fc in (300.0, 5000.0, 15000.0):
        at = steady_gain(dsp.BANDPASS, fc, fc, 8.0)
        assert at == pytest.approx(1.0, abs=0.01)
        assert steady_gain(dsp.BANDPASS, fc * 1.1, fc, 8.0) < 0.9 * at
        assert steady_gain(dsp.BANDPASS, fc / 1.1, fc, 8.0) < 0.9 * at


@pytest.mark.parametrize("mode", [dsp.LOWPASS, dsp.BANDPASS])
def test_chunked_filter_equals_the_plain_loop(mode):
    # 0.7 s = 7 chunks; moving cutoff 2400 -> 300 Hz at q = 8. The seams between chunks
    # must stay below -80 dB of the signal's peak (the warm-up is designed for -100 dB).
    n = int(0.7 * SR)
    x = dsp.saw(np.full(n, 110.0), SR)
    cutoff = 300.0 * 2.0 ** (3.0 * np.exp(-np.arange(n) / (0.12 * SR)))
    short = 3000
    y_long, y_short = dsp.resonant_filter([x, x[:short]], [cutoff, cutoff[:short]], 8.0, SR,
                                          mode)
    ref = loop_filter(x, cutoff, 8.0, mode == dsp.BANDPASS)
    peak = float(np.max(np.abs(ref)))
    assert float(np.max(np.abs(y_short - ref[:short]))) < 1e-9 * peak  # one chunk: same maths
    assert float(np.max(np.abs(y_long - ref))) < 1e-4 * peak
    assert float(np.max(np.abs(y_long[4410:] - ref[4410:]))) > 0  # chunks really were used


def test_cutoff_is_clamped_below_nyquist():
    assert dsp.CUTOFF_MAX_FRACTION == 0.45  # written here: 10 % of Nyquist as margin
    np.testing.assert_array_equal(
        dsp.clamp_cutoff(np.array([1.0, 20.0, 1000.0, 19845.0, 22050.0, 1e6]), SR),
        np.array([20.0, 20.0, 1000.0, 19845.0, 19845.0, 19845.0]))
    x = dsp.saw(np.full(4000, 3951.07), SR)
    for mode in (dsp.LOWPASS, dsp.BANDPASS):
        (at_clamp,) = dsp.resonant_filter([x], [np.full(4000, 19845.0)], 8.0, SR, mode)
        for above in (22050.0, 30000.0, 441000.0):
            (y,) = dsp.resonant_filter([x], [np.full(4000, above)], 8.0, SR, mode)
            np.testing.assert_array_equal(y, at_clamp)


@pytest.mark.parametrize("mode", [dsp.LOWPASS, dsp.BANDPASS])
def test_filter_stays_bounded_at_maximum_resonance(mode):
    # q = Q_MAX = 20, full-scale square and saw inputs, cutoffs that sit on a partial, jump
    # every sample between the clamps, sweep through the whole range, or lie far above
    # Nyquist. Stated bound: |output| <= 2 * q * max|input| (a tested bound, not a proof).
    assert dsp.Q_MAX == 20.0
    n = SR // 2
    i = np.arange(n)
    inputs = [dsp.square(np.full(n, 987.77), SR), dsp.saw(np.full(n, 3951.07), SR),
              np.where(i % 2 == 0, 1.0, -1.0), np.ones(n)]
    cutoffs = [np.full(n, 987.77), np.full(n, 3 * 987.77), np.full(n, 3951.07),
               np.where(i % 2 == 0, 20.0, 1e6), 20.0 * 1000.0 ** (i / n),
               30000.0 * 1000.0 ** (-i / n), np.full(n, 1e6)]
    sigs = [x for x in inputs for _ in cutoffs]
    cuts = [c for _ in inputs for c in cutoffs]
    outs = dsp.resonant_filter(sigs, cuts, dsp.Q_MAX, SR, mode)
    for x, y in zip(sigs, outs):
        assert np.all(np.isfinite(y))
        assert float(np.max(np.abs(y))) <= 2 * dsp.Q_MAX * float(np.max(np.abs(x)))
    assert max(float(np.max(np.abs(y))) for y in outs) > 1.0  # the cases do excite it


def test_filter_rejects_bad_arguments():
    x = np.zeros(10)
    for q in (0.0, 0.49, 20.01, float("nan")):
        with pytest.raises(ValueError):
            dsp.resonant_filter([x], [x + 100.0], q, SR)
    with pytest.raises(ValueError):
        dsp.resonant_filter([x], [x + 100.0], 1.0, SR, "highpass")
    with pytest.raises(ValueError):
        dsp.resonant_filter([x], [np.zeros(9)], 1.0, SR)
    assert dsp.resonant_filter([], [], 1.0, SR) == []
    assert len(dsp.resonant_filter([np.zeros(0)], [np.zeros(0)], 1.0, SR)[0]) == 0


# --- echoes -------------------------------------------------------------------------------
def test_ping_pong_positions_gains_and_end():
    # wet 0.3, feedback 0.4: dry 0.7 on both sides; echo j has gain 0.3 * 0.4^(j-1), odd j
    # left, even j right. Relative to the dry 0.7 the echoes are at 0.4286, 0.1714, 0.0686,
    # 0.0274, 0.0110, 0.0044, 0.0018, 0.0007: the 8th is the first below -60 dB (0.001),
    # so 7 are rendered.
    x = np.zeros(50)
    x[0], x[7] = 1.0, -0.5
    y = dsp.ping_pong(x, 100, 0.4, 0.3)
    assert y.shape == (50 + 7 * 100, 2) and dsp.echo_count(0.4, 0.3) == 7
    expected = np.zeros_like(y)
    expected[0], expected[7] = (0.7, 0.7), (-0.35, -0.35)
    for j, gain in enumerate((0.3, 0.12, 0.048, 0.0192, 0.00768, 0.003072, 0.0012288), start=1):
        expected[100 * j, (j - 1) % 2] = gain
        expected[100 * j + 7, (j - 1) % 2] = -0.5 * gain
    np.testing.assert_allclose(y, expected, rtol=0, atol=1e-12)
    assert not y[708:].any()  # exact silence after the last echo


def test_echo_count_and_limits():
    # wet 0.15: 0.1765 * 0.4^(j-1) >= 0.001 up to j = 6 (0.0018), j = 7 gives 0.0007
    assert dsp.echo_count(0.4, 0.15) == 6
    assert dsp.echo_count(0.4, 0.0) == 0 and dsp.echo_count(0.0, 0.3) == 1
    assert dsp.echo_count(0.4, 0.3, floor_db=-20.0) == 2  # 0.4286, 0.1714, then 0.0686 < 0.1
    np.testing.assert_array_equal(dsp.ping_pong(np.ones(5), 3, 0.4, 0.0), np.ones((5, 2)))
    for feedback in (1.0, 1.2, -0.1):
        with pytest.raises(ValueError):
            dsp.ping_pong(np.ones(5), 3, feedback, 0.3)
    for wet in (1.0, -0.1):
        with pytest.raises(ValueError):
            dsp.ping_pong(np.ones(5), 3, 0.4, wet)
    with pytest.raises(ValueError):
        dsp.ping_pong(np.ones(5), 0, 0.4, 0.3)
