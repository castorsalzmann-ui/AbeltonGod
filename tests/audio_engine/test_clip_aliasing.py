"""Aliasing of the v0.3 ``clip_db`` stage (#120 item 5, research note M9).

The reference is independent of the engine's resampling code: the same hard clip written
out here (scale to peak 1, raise by ``clip_db``, clip at +-1), computed by FFT zero-padding at
``REF_FACTOR`` = 64 times the sample rate. Both renders run the full chain; only
``_hard_clip`` is swapped, and ``_normalise`` is disabled so a peak difference cannot hide in
the scale. Errors are compared up to 20 kHz, relative to the reference peak.

Measured on the shipped stage (8x, the drive filter), written down before the bound was set:

- curated worst case below (48 kHz, drive 1, click 1 at 12 kHz, clip 12 dB): -62.3 dB;
  the same case at 44.1 kHz: -69.0 dB; default kick with clip 6 dB: -90.5 dB;
- 16x and 32x with the same filter family give -62.6 / -62.5 dB on the curated case, so the
  oversampling factor is not what limits it. Two parts were isolated: 8x against 64x with
  the same filter family (fold-back above 8x only) gives -75.7 dB, and low-passing the clip
  input at 20 kHz in both renders gives -76.3 dB. Most of the -62 dB therefore comes from
  content of the driven click between 20 kHz and the Nyquist frequency, which the Kaiser
  transition band (22.1 ... 25.9 kHz at 48 kHz) treats differently from the ideal brick wall
  before the clip. Derived from those two measurements; not proven further;
- the base-rate clip (no oversampling) gives -36.4 dB on the curated case.

So the shipped bound is -60 dB (curated and random cases), not the -70 dB of the drive test,
and -90 dBFS (research note M9 proposal) is not met for the extreme corner. The 16 random
cases below (seeds 12000 ... 12015) measured -78.6 dB at worst when this file was written.
Fold-back alone (8x vs 64x, same design, -70 dB like drive): curated -75.7 dB, random cases
-85.0 dB at worst (PR #130 review round 1 measured -74.4 dB on its own 12 hard cases).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from audio_engine import kick as K

AUDIBLE_HZ = 20000.0
REF_FACTOR = 64
LIMIT_DB = -60.0
# Fold-back only (same filter family at 64x as reference), curated case: -75.7 dB measured.
FOLDBACK_LIMIT_DB = -70.0
TAIL_EXCLUDE_MS = 10.0


def _clip_ref(x: np.ndarray, clip_db: float) -> np.ndarray:
    """Ideal band-limited hard clip: FFT interpolation to REF_FACTOR x, clip, band-limit."""
    if clip_db <= 0:
        return x
    y = x * (10.0 ** (clip_db / 20.0) / float(np.max(np.abs(x))))
    n = len(y)
    big = 2 * n
    spec = np.fft.rfft(np.concatenate([y, np.zeros(n)]))
    up_spec = np.zeros(big * REF_FACTOR // 2 + 1, dtype=complex)
    up_spec[: len(spec)] = spec
    up = np.fft.irfft(up_spec, big * REF_FACTOR) * REF_FACTOR
    down = np.fft.rfft(np.clip(up, -1.0, 1.0))[: big // 2 + 1] / REF_FACTOR
    out = np.fft.irfft(down, big)[:n]
    out[0] = 0.0  # the engine starts every kick at exactly zero
    return out


def _clip_naive(x: np.ndarray, clip_db: float) -> np.ndarray:
    if clip_db <= 0:
        return x
    return np.clip(x * (10.0 ** (clip_db / 20.0) / float(np.max(np.abs(x)))), -1.0, 1.0)


def _band_limit(x: np.ndarray, sr: int) -> np.ndarray:
    n = len(x)
    spec = np.fft.rfft(np.concatenate([x, np.zeros(n)]))
    spec[np.fft.rfftfreq(2 * n, 1.0 / sr) > AUDIBLE_HZ] = 0.0
    return np.fft.irfft(spec, 2 * n)[:n]


def _render(monkeypatch, params, clip_fn=None):
    with monkeypatch.context() as m:
        m.setattr(K, "_normalise", lambda x, ceiling, bits: x)
        if clip_fn is not None:
            m.setattr(K, "_hard_clip", clip_fn)
        return K.render_kick(params)


def _error_db(monkeypatch, params, clip_fn=None, ref_fn=_clip_ref) -> float:
    test, p = _render(monkeypatch, params, clip_fn)
    ref, _ = _render(monkeypatch, params, ref_fn)
    sr = int(p["sample_rate"])
    cut = len(ref) - int(round(TAIL_EXCLUDE_MS * sr / 1000.0))
    err = (_band_limit(test, sr) - _band_limit(ref, sr))[:cut]
    return 20.0 * math.log10(math.sqrt(float(np.mean(err**2))) / float(np.max(np.abs(ref))))


WORST = {
    "schema_version": "0.3", "seed": 7, "length_ms": 200, "clip_db": 12.0, "drive": 1.0,
    "click_level": 1.0, "click_tone_hz": 12000.0,
}


def _random_params(rng: np.random.Generator) -> dict:
    start = float(rng.uniform(60, 600))
    return {
        "schema_version": "0.3",
        "seed": int(rng.integers(0, 2**32)),
        "sample_rate": int(rng.choice([44100, 48000])),
        "length_ms": float(rng.uniform(80, 400)),  # the reference FFT grows with the length
        "pitch_start_hz": start,
        "pitch_end_hz": float(rng.uniform(30, min(120.0, start))),
        "pitch_decay_ms": float(rng.uniform(2, 300)),
        "amp_attack_ms": float(rng.choice([0.0, rng.uniform(0, 20)])),
        "amp_decay_ms": float(rng.uniform(20, 2000)),
        "click_level": float(rng.uniform(0, 1)),
        "click_tone_hz": float(rng.uniform(500, 12000)),
        "click_decay_ms": float(rng.uniform(0.5, 12)),
        "click_q": float(rng.uniform(0.5, 8)),
        "drive": float(rng.choice([0.0, rng.uniform(0, 1)])),
        "tone": float(rng.uniform(-1, 1)),
        "clip_db": float(rng.uniform(0.01, 12)),
    }


RANDOM_CASES = [_random_params(np.random.default_rng(12000 + i)) for i in range(16)]


def test_curated_worst_case_is_bounded(monkeypatch) -> None:
    assert _error_db(monkeypatch, WORST) <= LIMIT_DB


@pytest.mark.parametrize("params", RANDOM_CASES, ids=lambda p: f"seed{p['seed']}")
def test_random_case_is_bounded(monkeypatch, params) -> None:
    assert _error_db(monkeypatch, params) <= LIMIT_DB


def _clip64(x: np.ndarray, clip_db: float) -> np.ndarray:
    """The same oversampler design at 64x: differs from the shipped 8x only by fold-back."""
    from audio_engine.dsp import kaiser_lowpass, oversampled

    if clip_db <= 0:
        return x
    h64 = kaiser_lowpass(64, K.DRIVE_FILTER_TRANSITION, K.DRIVE_FILTER_BETA)
    y = x * (10.0 ** (clip_db / 20.0) / float(np.max(np.abs(x))))
    out = y + oversampled(y, 64, lambda u: np.clip(u, -1.0, 1.0) - u, h64)
    out[0] = 0.0
    return out


@pytest.mark.parametrize("params", [WORST, *RANDOM_CASES],
                         ids=lambda p: "worst" if p is WORST else f"seed{p['seed']}")
def test_foldback_above_the_oversampled_rate_is_small(monkeypatch, params) -> None:
    """The shipped 8x against the same design at 64x: only what folds back above 8x.
    Same -70 dB as the drive test (PR #130 review: also on the random cases)."""
    assert _error_db(monkeypatch, params, ref_fn=_clip64) <= FOLDBACK_LIMIT_DB


def test_metric_detects_base_rate_clip(monkeypatch) -> None:
    """Sensitivity: the clip without oversampling must fail the bound clearly."""
    assert _error_db(monkeypatch, WORST, _clip_naive) > LIMIT_DB + 20.0


def test_metric_detects_one_sample_shift(monkeypatch) -> None:
    real = K._hard_clip

    def late(x, clip_db):
        return np.concatenate([[0.0], real(x, clip_db)[:-1]])

    assert _error_db(monkeypatch, {**WORST, "drive": 0.2, "click_level": 0.35}, late) > LIMIT_DB


def test_clip_zero_is_skipped() -> None:
    x = np.sin(np.linspace(0, 40, 1000))
    assert K._hard_clip(x, 0) is x
    assert K._hard_clip(x, 0.0) is x


def test_clip_pushes_peaks_over_the_clip_point() -> None:
    """Behaviour, measured with the reference written above: the base-rate samples of the
    clipped kick stay within the band-limited overshoot of +-1, and the share of samples at
    the clip level grows with clip_db."""
    x = np.sin(np.linspace(0, 60, 4000)) * np.exp(-np.linspace(0, 5, 4000))
    shares = []
    for db in (1.0, 6.0, 12.0):
        y = K._hard_clip(x, db)
        assert float(np.max(np.abs(y))) < 1.05
        shares.append(float(np.mean(np.abs(y) > 0.99)))
    assert shares[0] < shares[1] < shares[2]
