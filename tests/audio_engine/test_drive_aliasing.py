"""Aliasing of the drive stage (issue #13).

The reference is independent of the engine's resampling code: an ideal band-limited
saturation computed with FFT zero-padding at 32x the sample rate, using the tanh curve
written out here. Both renders run the full ``render_kick`` chain; only ``_drive`` is swapped,
and ``_normalise`` is disabled so a small peak difference cannot hide in the scale.
Errors are compared in the band up to 20 kHz, relative to the reference peak.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from audio_engine import kick as K
from audio_engine.dsp import kaiser_lowpass, oversampled

AUDIBLE_HZ = 20000.0
REF_FACTOR = 16  # 16, 32 and 8 give the same result to 0.3 dB (checked during development)
# Issue #13. Measured on the full chain during development: random worst -88 dB,
# curated worst -82 dB; the old base-rate tanh gives -41 dB on the curated case.
LIMIT_DB = -70.0
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
    m = min(n, K.DRIVE_FADE_IN_SAMPLES)
    y[:m] *= 0.5 * (1.0 - np.cos(np.linspace(0.0, math.pi, m)))
    return y


def _naive_drive(x: np.ndarray, drive: float) -> np.ndarray:
    """The pre-#13 drive: tanh at the base rate (aliases)."""
    if drive <= 0:
        return x
    y = _curve(x, drive)
    m = min(len(y), K.DRIVE_FADE_IN_SAMPLES)
    y[:m] *= 0.5 * (1.0 - np.cos(np.linspace(0.0, math.pi, m)))
    return y


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
    "schema_version": "0.1", "seed": 7, "drive": 1.0, "click_level": 1.0,
    "click_tone_hz": 12000.0,
}


def _random_params(rng: np.random.Generator) -> dict:
    start = float(rng.uniform(60, 600))
    return {
        "schema_version": "0.1",
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


RANDOM_CASES = [_random_params(np.random.default_rng(1300 + i)) for i in range(24)]


def test_worst_curated_case_aliasing_is_bounded(monkeypatch) -> None:
    assert _alias_db(monkeypatch, WORST) <= LIMIT_DB


@pytest.mark.parametrize("params", RANDOM_CASES, ids=lambda p: f"seed{p['seed']}")
def test_random_case_aliasing_is_bounded(monkeypatch, params) -> None:
    assert _alias_db(monkeypatch, params) <= LIMIT_DB


def test_metric_detects_naive_drive(monkeypatch) -> None:
    """Sensitivity: the pre-#13 drive at the base rate must fail the same limit clearly."""
    assert _alias_db(monkeypatch, WORST, _naive_drive) > LIMIT_DB + 20.0


def test_metric_detects_one_sample_shift(monkeypatch) -> None:
    """Sensitivity: a one-sample delay in the drive output must fail the limit."""
    real_drive = K._drive

    def late(x, drive):
        return np.concatenate([[0.0], real_drive(x, drive)[:-1]])

    params = {"schema_version": "0.1", "seed": 3, "drive": 0.5}
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
