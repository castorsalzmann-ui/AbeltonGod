"""Aliasing of the drive stage (issue #13).

The reference is independent of the engine's resampling code: an ideal band-limited
saturation computed with FFT zero-padding at ``REF_FACTOR`` times the sample rate,
using the tanh curve written out here. Both renders run the full ``render_kick`` chain;
only ``_drive`` is swapped, and ``_normalise`` is disabled so a small peak difference
cannot hide in the scale.
Errors are compared in the band up to 20 kHz, relative to the reference peak.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from audio_engine import kick as K
from audio_engine.dsp import fft_size, kaiser_lowpass, oversampled

AUDIBLE_HZ = 20000.0
REF_FACTOR = 8  # 8, 16 and 32 give the same result to 0.3 dB (checked in the #20 review)
# Issue #13 acceptance limit. The old base-rate tanh gives -41 dB on the curated case.
LIMIT_DB = -70.0
# Regression bound for the shipped filter (8x, transition 0.08, beta 10): curated -79 dB,
# random worst -85 dB (30 fresh seeds: -78 dB). 4x or a 0.2 transition give -70 dB on the
# curated case and must fail here; that is the point of this bound, not the issue limit.
REGRESSION_DB = -75.0
TAIL_EXCLUDE_MS = 10.0  # the last samples are faded out by the engine anyway


def _curve(x: np.ndarray, drive: float) -> np.ndarray:
    gain = 1.0 + 9.0 * drive
    return np.tanh(gain * x) / math.tanh(gain)


def _ideal_drive(x: np.ndarray, drive: float) -> np.ndarray:
    """Band-limited saturation by FFT interpolation (zero-padded to avoid wrap-around)."""
    if drive <= 0:
        return x
    n = len(x)
    big = 2 * n
    spec = np.fft.rfft(np.concatenate([x, np.zeros(n)]))
    up_spec = np.zeros(big * REF_FACTOR // 2 + 1, dtype=complex)
    up_spec[: len(spec)] = spec
    up = np.fft.irfft(up_spec, big * REF_FACTOR) * REF_FACTOR
    down = np.fft.rfft(_curve(up, drive))[: big // 2 + 1] / REF_FACTOR
    y = np.fft.irfft(down, big)[:n]
    y[0] = 0.0  # the engine starts every kick at exactly zero
    return y


def _naive_drive(x: np.ndarray, drive: float) -> np.ndarray:
    """The pre-#13 drive: tanh at the base rate (aliases)."""
    if drive <= 0:
        return x
    return _curve(x, drive)


def _band_limit(x: np.ndarray, sr: int) -> np.ndarray:
    n = len(x)
    spec = np.fft.rfft(np.concatenate([x, np.zeros(n)]))
    spec[np.fft.rfftfreq(2 * n, 1.0 / sr) > AUDIBLE_HZ] = 0.0
    return np.fft.irfft(spec, 2 * n)[:n]


def _render(monkeypatch, params, drive_fn=None):
    with monkeypatch.context() as m:
        m.setattr(K, "_normalise", lambda x, ceiling, bits: x)
        if drive_fn is not None:
            m.setattr(K, "_drive", drive_fn)
        audio, p = K.render_kick(params)
    return audio, p


def _alias_db(monkeypatch, params, drive_fn=None) -> float:
    test, p = _render(monkeypatch, params, drive_fn)
    ref, _ = _render(monkeypatch, params, _ideal_drive)
    sr = int(p["sample_rate"])
    cut = len(ref) - int(round(TAIL_EXCLUDE_MS * sr / 1000.0))
    err = (_band_limit(test, sr) - _band_limit(ref, sr))[:cut]
    peak = float(np.max(np.abs(ref)))
    return 20.0 * math.log10(math.sqrt(float(np.mean(err**2))) / peak)


WORST = {
    "schema_version": "0.2", "seed": 7, "drive": 1.0, "click_level": 1.0,
    "click_tone_hz": 12000.0,
}


def _random_params(rng: np.random.Generator) -> dict:
    start = float(rng.uniform(60, 600))
    return {
        "schema_version": "0.2",
        "seed": int(rng.integers(0, 2**32)),
        "sample_rate": int(rng.choice([44100, 48000])),
        "length_ms": float(rng.uniform(80, 2000)),
        "pitch_start_hz": start,
        "pitch_end_hz": float(rng.uniform(30, min(120.0, start))),
        "pitch_decay_ms": float(rng.uniform(2, 300)),
        "amp_attack_ms": float(rng.choice([0.0, rng.uniform(0, 20)])),
        "amp_decay_ms": float(rng.uniform(20, 2000)),
        "click_level": float(rng.uniform(0, 1)),
        "click_tone_hz": float(rng.uniform(500, 12000)),
        "drive": float(rng.uniform(0.01, 1)),
        "tone": float(rng.uniform(-1, 1)),
    }


def _hard_params(rng: np.random.Generator) -> dict:
    """Biased towards the smallest margin: heavy drive, loud bright click, 44.1 kHz, no attack."""
    p = _random_params(rng)
    p.update(
        drive=float(rng.uniform(0.7, 1)), click_level=float(rng.uniform(0.6, 1)),
        click_tone_hz=float(rng.uniform(8000, 12000)), sample_rate=44100,
        amp_attack_ms=0.0,
    )
    return p


RANDOM_CASES = [_random_params(np.random.default_rng(1300 + i)) for i in range(24)] + [
    _hard_params(np.random.default_rng(7700 + i)) for i in range(8)
]


def test_worst_curated_case_aliasing_is_bounded(monkeypatch) -> None:
    assert _alias_db(monkeypatch, WORST) <= min(LIMIT_DB, REGRESSION_DB)


@pytest.mark.parametrize("params", RANDOM_CASES, ids=lambda p: f"seed{p['seed']}")
def test_random_case_aliasing_is_bounded(monkeypatch, params) -> None:
    assert _alias_db(monkeypatch, params) <= min(LIMIT_DB, REGRESSION_DB)


def test_onset_is_not_reshaped(monkeypatch) -> None:
    """Only sample 0 may be forced to zero; the next samples follow the ideal drive.

    Bound 0.05 x peak; during development the shipped code deviated by 0.014 x peak
    here, while an 8-sample fade-in deviated by 0.43 x peak.
    """
    params = {"schema_version": "0.2", "seed": 1, "drive": 1.0, "click_level": 0.0,
              "amp_attack_ms": 0.0, "pitch_start_hz": 600.0}
    with monkeypatch.context() as m:
        m.setattr(K, "_normalise", lambda x, ceiling, bits: x)
        audio, _ = K.render_kick(params)
        m.setattr(K, "_drive", _ideal_drive)
        ref, _ = K.render_kick(params)
    peak = float(np.max(np.abs(ref)))
    assert audio[0] == 0.0
    assert float(np.max(np.abs(audio[1:32] - ref[1:32]))) <= 0.05 * peak


def test_shipped_drive_filter_design() -> None:
    """Pin the anti-aliasing design itself, not only its effect on the test kicks."""
    assert K.DRIVE_OVERSAMPLE >= 8
    h = K._DRIVE_FILTER
    resp = np.abs(np.fft.rfft(h, 1 << 18))
    f = np.fft.rfftfreq(1 << 18) * K.DRIVE_OVERSAMPLE  # in units of the base sample rate
    assert 20 * np.log10(resp[f >= 0.54].max()) < -95.0
    assert 20 * np.log10(resp[f <= 0.46].min()) > -0.01


def test_metric_detects_naive_drive(monkeypatch) -> None:
    """Sensitivity: the pre-#13 drive at the base rate must fail the same limit clearly."""
    assert _alias_db(monkeypatch, WORST, _naive_drive) > LIMIT_DB + 20.0


def test_metric_detects_one_sample_shift(monkeypatch) -> None:
    """Sensitivity: a one-sample delay in the drive output must fail the limit."""
    real_drive = K._drive

    def late(x, drive):
        return np.concatenate([[0.0], real_drive(x, drive)[:-1]])

    params = {"schema_version": "0.2", "seed": 3, "drive": 0.5}
    assert _alias_db(monkeypatch, params, late) > LIMIT_DB


def test_drive_zero_is_untouched() -> None:
    x = np.sin(np.linspace(0, 40, 1000))
    assert K._drive(x, 0.0) is x


def test_kaiser_lowpass_response() -> None:
    factor, transition = 8, 0.08
    h = kaiser_lowpass(factor, transition, 10.0)
    assert len(h) % 2 == 1
    assert math.isclose(float(h.sum()), 1.0, rel_tol=1e-12)
    np.testing.assert_allclose(h, h[::-1], atol=1e-15)  # linear phase
    resp = np.abs(np.fft.rfft(h, 1 << 18))
    # Frequency axis in units of the BASE sample rate (the filter runs at factor x base).
    f = np.fft.rfftfreq(1 << 18) * factor
    passband = resp[f <= 0.5 - transition / 2]
    stopband = resp[f >= 0.5 + transition / 2]
    assert 20 * np.log10(passband.max()) < 0.01 and 20 * np.log10(passband.min()) > -0.01
    assert 20 * np.log10(stopband.max()) < -95.0


@pytest.mark.parametrize("sr", [44100, 48000])
def test_oversampled_identity_keeps_signal_aligned(sr: int) -> None:
    n = 4800
    t = np.arange(n) / sr
    x = np.sin(2 * np.pi * 1000.0 * t) * np.hanning(n)
    h = kaiser_lowpass(8, 0.08, 10.0)
    y = oversampled(x, 8, lambda u: u, h)
    assert y.shape == x.shape
    np.testing.assert_allclose(y, x, atol=1e-5)


def test_oversampled_edge_lengths() -> None:
    h = kaiser_lowpass(8, 0.08, 10.0)
    assert oversampled(np.zeros(0), 8, np.tanh, h).shape == (0,)
    assert oversampled(np.array([0.5]), 8, np.tanh, h).shape == (1,)
    with pytest.raises(ValueError):
        oversampled(np.zeros(4), 0, np.tanh, h)


def _direct_oversampled(x: np.ndarray, factor: int, fn, h: np.ndarray) -> np.ndarray:
    """Plain time-domain version (zero stuffing + np.convolve), independent of the FFT path."""
    n, delay = len(x), (len(h) - 1) // 2
    up = np.zeros(n * factor)
    up[::factor] = x
    up = np.convolve(up, h * factor)[delay : delay + n * factor]
    return np.convolve(fn(up), h)[delay : delay + n * factor][::factor]


@pytest.mark.parametrize("factor", [1, 2, 8])
@pytest.mark.parametrize("n", [1, 2, 7, 81, 1000, 4801])
def test_oversampled_matches_direct_convolution(factor: int, n: int) -> None:
    rng = np.random.default_rng(factor * 1000 + n)
    x = 0.5 * rng.standard_normal(n)
    h = kaiser_lowpass(factor, 0.08, 10.0) if factor > 1 else np.array([1.0])
    np.testing.assert_allclose(
        oversampled(x, factor, np.tanh, h), _direct_oversampled(x, factor, np.tanh, h),
        rtol=0, atol=1e-12,
    )


def test_spectrum_cache_does_not_change_output() -> None:
    """Same input before and after the cache has been filled and evicted -> same bytes."""
    h = kaiser_lowpass(8, 0.08, 10.0)
    x = np.sin(np.linspace(0, 50, 2000))
    first = oversampled(x, 8, np.tanh, h)
    for n in (900, 1100, 1300, 1500, 1700, 1900):  # more lengths than the cache holds
        oversampled(np.ones(n) * 0.1, 8, np.tanh, h)
    again = oversampled(x, 8, np.tanh, h)
    cached = oversampled(x, 8, np.tanh, h)
    assert first.tobytes() == again.tobytes() == cached.tobytes()


def test_spectrum_cache_separates_factors() -> None:
    """Same filter, same FFT size, different factors must not share a cached spectrum."""
    h = kaiser_lowpass(4, 0.08, 10.0)
    taps = len(h) - 1
    size_for = {f: {f * fft_size(n + -(-taps // f)): n for n in range(200, 2000)} for f in (2, 4)}
    common = sorted(set(size_for[2]) & set(size_for[4]))[0]
    for factor in (2, 4):
        n = size_for[factor][common]
        x = 0.5 * np.random.default_rng(n).standard_normal(n)
        np.testing.assert_allclose(
            oversampled(x, factor, np.tanh, h), _direct_oversampled(x, factor, np.tanh, h),
            rtol=0, atol=1e-12,
        )
