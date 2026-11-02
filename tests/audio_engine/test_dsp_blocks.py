"""DSP blocks for non-pitched voices (#230), each against an independent reference.

Filters: the magnitude response is measured by FFT of the impulse response and compared with
the analogue prototype mapped through the bilinear transform with pre-warping at f0, written
out here from its textbook form (not from the module's coefficient formulas).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from audio_engine.dsp import rbj_highpass, rbj_lowpass, rbj_peaking, square_bank, substreams

SR = 48000
N_IR = 1 << 15
Q_BUTTER = 1 / math.sqrt(2)


def _response(block, f_hz: np.ndarray) -> np.ndarray:
    """|H| at ``f_hz`` from the FFT of the impulse response (long enough to have died out)."""
    impulse = np.zeros(N_IR)
    impulse[0] = 1.0
    spectrum = np.abs(np.fft.rfft(block(impulse)))
    bins = np.fft.rfftfreq(N_IR, 1 / SR)
    return np.interp(f_hz, bins, spectrum)


def _bilinear_s(f_hz: np.ndarray, f0: float) -> np.ndarray:
    """Normalised analogue frequency s/w0 for a digital frequency (pre-warped at f0)."""
    return 1j * np.tan(np.pi * f_hz / SR) / np.tan(np.pi * f0 / SR)


FREQS = np.array([50.0, 200.0, 800.0, 1000.0, 1500.0, 4000.0, 10000.0, 20000.0])


@pytest.mark.parametrize("f0,q", [(1000.0, Q_BUTTER), (450.0, 2.0), (6000.0, 0.5)])
def test_highpass_matches_analogue_prototype(f0: float, q: float) -> None:
    s = _bilinear_s(FREQS, f0)
    expected = np.abs(s**2 / (s**2 + s / q + 1))
    got = _response(lambda x: rbj_highpass(x, SR, f0, q), FREQS)
    np.testing.assert_allclose(got, expected, rtol=2e-3, atol=1e-6)


@pytest.mark.parametrize("f0,q", [(1000.0, Q_BUTTER), (8000.0, 2.0), (300.0, 0.5)])
def test_lowpass_matches_analogue_prototype(f0: float, q: float) -> None:
    s = _bilinear_s(FREQS, f0)
    expected = np.abs(1 / (s**2 + s / q + 1))
    got = _response(lambda x: rbj_lowpass(x, SR, f0, q), FREQS)
    np.testing.assert_allclose(got, expected, rtol=2e-3, atol=1e-6)


@pytest.mark.parametrize(
    "f0,q,gain_db", [(1000.0, 1.0, 6.0), (3000.0, 2.0, -9.0), (500.0, 0.7, 12.0)]
)
def test_peaking_matches_analogue_prototype(f0: float, q: float, gain_db: float) -> None:
    a = 10 ** (gain_db / 40)
    s = _bilinear_s(FREQS, f0)
    expected = np.abs((s**2 + s * a / q + 1) / (s**2 + s / (a * q) + 1))
    got = _response(lambda x: rbj_peaking(x, SR, f0, q, gain_db), FREQS)
    np.testing.assert_allclose(got, expected, rtol=2e-3)
    at_f0 = _response(lambda x: rbj_peaking(x, SR, f0, q, gain_db), np.array([f0]))[0]
    assert 20 * math.log10(at_f0) == pytest.approx(gain_db, abs=0.02)


def test_filter_corner_is_minus_3_db() -> None:
    for block in (rbj_highpass, rbj_lowpass):
        r = _response(lambda x, b=block: b(x, SR, 2000.0), np.array([2000.0]))[0]
        assert 20 * math.log10(r) == pytest.approx(-3.0103, abs=0.02)


@pytest.mark.parametrize("bad", [0.0, -5.0, SR / 2, SR])
def test_filters_refuse_corner_outside_range(bad: float) -> None:
    with pytest.raises(ValueError):
        rbj_highpass(np.zeros(8), SR, bad)


def _direct_square(f: float, n: int) -> np.ndarray:
    """Independent reference: explicit loop over odd harmonics below Nyquist."""
    out = np.zeros(n)
    for i in range(n):
        t = i / SR
        acc = 0.0
        for k in range(1, 1000, 2):
            if k * f >= SR / 2:
                break
            acc += math.sin(2 * math.pi * k * f * t) / k
        out[i] = 4 / math.pi * acc
    return out


@pytest.mark.parametrize("f", [110.0, 1234.5, 9000.0])
def test_square_bank_equals_direct_sum(f: float) -> None:
    np.testing.assert_allclose(square_bank([f], SR, 300), _direct_square(f, 300), atol=1e-9)


def test_square_bank_has_no_partial_above_nyquist() -> None:
    # 5 kHz: only k=1 fits below 24 kHz? 3*5k=15k fits, 5*5k=25k does not -> 2 harmonics.
    x = square_bank([5000.0], SR, SR)  # 1 s: 1 Hz bins
    mag = np.abs(np.fft.rfft(x)) / (SR / 2)
    peaks = np.nonzero(mag > 1e-6)[0]
    assert list(peaks) == [5000, 15000]
    # relative level of the 3rd harmonic is 1/3
    assert mag[15000] / mag[5000] == pytest.approx(1 / 3, rel=1e-6)


def test_square_bank_sums_and_ignores_frequencies_at_nyquist() -> None:
    a = square_bank([700.0], SR, 500)
    b = square_bank([900.0], SR, 500)
    np.testing.assert_allclose(square_bank([700.0, 900.0, SR / 2], SR, 500), a + b, atol=1e-12)


def test_substreams_deterministic_and_independent() -> None:
    first = [g.standard_normal(64) for g in substreams(7, 3)]
    again = [g.standard_normal(64) for g in substreams(7, 3)]
    for u, v in zip(first, again, strict=True):
        assert u.tobytes() == v.tobytes()
    # more layers later: the earlier streams do not move
    more = [g.standard_normal(64) for g in substreams(7, 5)]
    for u, v in zip(first, more, strict=False):
        assert u.tobytes() == v.tobytes()
    # streams and seeds differ, and are uncorrelated at this length
    assert not np.array_equal(first[0], first[1])
    assert not np.array_equal(first[0], [g.standard_normal(64) for g in substreams(8, 1)][0])
    big = [g.standard_normal(20000) for g in substreams(3, 2)]
    assert abs(np.corrcoef(big[0], big[1])[0, 1]) < 0.05


def test_substreams_do_not_touch_global_rng() -> None:
    np.random.seed(5)
    before = np.random.random()
    np.random.seed(5)
    substreams(1, 2)[0].standard_normal(10)
    assert np.random.random() == before


@pytest.mark.parametrize("bad", [-1, 1.5, True, "3"])
def test_substreams_refuse_bad_seed(bad) -> None:
    with pytest.raises(ValueError):
        substreams(bad, 1)
