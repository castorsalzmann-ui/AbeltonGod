"""``drive`` is continuous from 0 (issue #16).

Before #16 the curve was ``tanh(g*x) / tanh(g)`` with ``g = 1 + 9 * drive``: at ``drive``
-> 0+ the gain was 1 and the curve already clearly bent, so ``drive: 1e-6`` differed from
``drive: 0`` by up to -11.9 dB (max abs difference relative to peak, 20 random sets). Now
the gain is ``g = 10 * drive ** 0.8`` (written out here, not imported), the curve tends to
the identity as g -> 0, and only the distortion residual is oversampled.

Expectations written here, independent of ``audio_engine.kick``:

- For small g, ``tanh(g*x) / tanh(g) = x + (g^2 / 3) * x * (1 - x^2) + O(g^4)`` (Taylor
  series of tanh). So the change from ``drive: 0`` is about ``g^2 / 3`` times the
  band-limited ``x - x^3``. The reference band-limits ``x^3`` itself, by FFT zero-padding,
  not with the engine's resampler.
- The change from the clean render grows monotonically with ``drive`` over the whole range,
  measured as the share of the output that is not a scaled copy of the clean render (so the
  peak normalisation cancels).
"""

from __future__ import annotations

import math
import random

import numpy as np
import pytest

from audio_engine import kick as K
from audio_engine.kick import render_kick

SCHEMA_VERSION = "0.2"
BASE = {"schema_version": SCHEMA_VERSION, "seed": 11}
N_RANDOM = 30


def _gain(drive: float) -> float:
    return 10.0 * drive**0.8


def _draw(rng: random.Random) -> dict:
    """Uniform draw over the whole kick-params contract range (drive is set by each test)."""
    p = {
        "schema_version": SCHEMA_VERSION,
        "seed": rng.randrange(2**32),
        "sample_rate": rng.choice([44100, 48000]),
        "bit_depth": rng.choice([16, 24]),
        "length_ms": rng.uniform(80, 2000),
        "pitch_start_hz": rng.uniform(60, 600),
        "pitch_decay_ms": rng.uniform(2, 300),
        "amp_attack_ms": rng.choice([0.0, rng.uniform(0, 20)]),
        "amp_decay_ms": rng.uniform(20, 2000),
        "click_level": rng.uniform(0, 1),
        "click_tone_hz": rng.uniform(500, 12000),
        "tone": rng.uniform(-1, 1),
        "peak_ceiling_dbfs": rng.uniform(-12, -0.1),
    }
    p["pitch_end_hz"] = rng.uniform(30, min(120, p["pitch_start_hz"]))
    return p


CURATED = {
    "defaults": {},
    "hard-click": {"click_level": 1.0, "click_tone_hz": 12000, "amp_attack_ms": 0.0},
    "no-click-long": {"click_level": 0.0, "length_ms": 2000, "amp_decay_ms": 2000},
    "short-44k1-16bit": {"length_ms": 80, "amp_decay_ms": 20, "sample_rate": 44100,
                         "bit_depth": 16},
}


def _sets(seed0: int, n: int = N_RANDOM) -> list:
    return [pytest.param({**BASE, **c}, id=name) for name, c in CURATED.items()] + [
        pytest.param(_draw(random.Random(seed0 + i)), id=f"random-{seed0 + i}") for i in range(n)
    ]


def _residual_share(y: np.ndarray, clean: np.ndarray) -> float:
    """Norm of the part of ``y`` that is not a scaled copy of ``clean``, relative to ``y``."""
    scale = float(y @ clean) / float(clean @ clean)
    return float(np.linalg.norm(y - scale * clean) / np.linalg.norm(y))


# --- monotonic growth over the whole drive range ----------------------------------------------

LADDER = (1e-6, 1e-4, 1e-3, 1e-2, 0.05, 0.1, 0.2, 0.35, 0.5, 0.65, 0.8, 0.9, 0.95, 1.0)
# Each step up the ladder must raise the residual share by at least this factor. Measured
# smallest step 1.0085 over 60 random sets (0.95 -> 1.0 is the flattest step).
MIN_STEP_RATIO = 1.003
# "Small" near 0: residual share <= SMALL_COEFF * g^2 for drive <= 1e-2. Measured largest
# share / g^2 about 0.09; the pre-#16 curve gave a share of about 0.1-0.3 at any drive > 0.
SMALL_COEFF = 0.2


@pytest.mark.parametrize("p", _sets(seed0=16000))
def test_change_from_clean_is_small_and_grows_monotonically(p: dict) -> None:
    clean, _ = render_kick({**p, "drive": 0.0})
    shares = [_residual_share(render_kick({**p, "drive": d})[0], clean) for d in LADDER]
    for d, s in zip(LADDER, shares, strict=True):
        if d <= 1e-2:
            assert s <= SMALL_COEFF * _gain(d) ** 2, (d, s)
    steps = [b / a for a, b in zip(shares, shares[1:], strict=False)]
    assert min(steps) >= MIN_STEP_RATIO, (steps, shares)


def test_drive_zero_and_tiny_drive_render_the_same_quantised_file() -> None:
    """At drive 1e-9 the change (about 3e-13 of peak) is far below one 24-bit step."""
    from audio_engine.io import render_kick_wav

    p = {**BASE, "click_level": 1.0, "click_tone_hz": 12000}
    assert render_kick_wav({**p, "drive": 1e-9})[0] == render_kick_wav({**p, "drive": 0.0})[0]


# --- continuity at 0 against an independent first-order reference ---------------------------


def _band_limited_cube(x: np.ndarray) -> np.ndarray:
    """x^3 without aliasing: FFT zero-padding to 4x the rate (x^3 needs 3x), cube, then keep
    only the band below the original Nyquist frequency. Padded to 2n against wrap-around."""
    n = len(x)
    big, f = 2 * n, 4
    spec = np.fft.rfft(np.concatenate([x, np.zeros(n)]))
    up_spec = np.zeros(big * f // 2 + 1, dtype=complex)
    up_spec[: len(spec)] = spec
    up = np.fft.irfft(up_spec, big * f) * f
    down = np.fft.rfft(up**3)[: big // 2 + 1] / f
    return np.fft.irfft(down, big)[:n]


def _first_order_drive(x: np.ndarray, drive: float) -> np.ndarray:
    if drive <= 0:
        return x
    y = x + _gain(drive) ** 2 / 3.0 * (x - _band_limited_cube(x))
    y[0] = 0.0  # documented: every kick starts at exactly zero
    return y


def _unnormalised(monkeypatch, p: dict, drive_fn=None) -> np.ndarray:
    with monkeypatch.context() as m:
        m.setattr(K, "_normalise", lambda x, ceiling, bits: x)
        if drive_fn is not None:
            m.setattr(K, "_drive", drive_fn)
        return render_kick(p)[0]


SMALL_DRIVES = (1e-7, 1e-5, 1e-4)
# Relative error of the change (engine vs first-order reference). Measured over these 42
# cases: median 0.0006, largest 0.0151. The O(g^2) term of the series is below 1e-4 here, so
# the rest is the difference between the engine's band limit (Kaiser transition 22.1-25.9 kHz
# at 48 kHz) and the reference's brick-wall at Nyquist; cause of the largest case not isolated
# further. A 2 % wrong gain moves the change by 4 % and must fail.
FIRST_ORDER_TOLERANCE = 0.02


@pytest.mark.parametrize("p", _sets(seed0=16500, n=10))
@pytest.mark.parametrize("drive", SMALL_DRIVES)
def test_change_near_zero_matches_first_order_reference(monkeypatch, p: dict, drive) -> None:
    clean = _unnormalised(monkeypatch, {**p, "drive": 0.0})
    got = _unnormalised(monkeypatch, {**p, "drive": drive}) - clean
    want = _unnormalised(monkeypatch, {**p, "drive": drive}, _first_order_drive) - clean
    err = float(np.linalg.norm(got - want) / np.linalg.norm(want))
    assert err <= FIRST_ORDER_TOLERANCE, err


# --- the curve itself -------------------------------------------------------------------------


def test_curve_is_exact_normalised_tanh_minus_identity() -> None:
    x = np.linspace(-1.7, 1.7, 3401)
    for drive in (0.01, 0.05, 0.25, 0.5, 1.0):
        g = _gain(drive)
        np.testing.assert_allclose(
            K._residual(x, drive), np.tanh(g * x) / math.tanh(g) - x, rtol=0, atol=1e-13
        )


def test_curve_is_continuous_where_the_series_takes_over() -> None:
    """Below a small gain the engine uses a Taylor series; it must join the closed form.
    Reference: the leading term (g^2 / 3) * x * (1 - x^2), written out here."""
    x = np.linspace(-1.7, 1.7, 3401)
    # Keep the relative error defined: the leading term is zero at x = 0 and |x| = 1.
    x = x[(np.abs(np.abs(x) - 1.0) > 0.05) & (np.abs(x) > 0.05)]
    for g in (1e-4, 5e-3, 9.99e-3, 1.001e-2, 2e-2):
        drive = (g / 10.0) ** 1.25
        lead = g * g / 3.0 * x * (1.0 - x * x)
        rel = np.abs(K._residual(x, drive) / lead - 1.0)
        # Next order, relative to the leading term: -a (1 + 6 x^2) / 15 with a = g^2, at most
        # 1.23 a on |x| <= 1.7 (from the series of tanh(g x) and of 1 / tanh(g)).
        assert float(rel.max()) <= 1.3 * g * g + 1e-12, (g, rel.max())


@pytest.mark.parametrize("drive", (0.0, 5e-324, 1e-300, 1e-30, 1e-12))
def test_tiny_drive_is_finite_and_clean(drive: float) -> None:
    x = np.linspace(-1.7, 1.7, 101)
    r = K._residual(x, drive)
    assert np.all(np.isfinite(r))
    # |x (1 - x^2)| <= 3.21 on [-1.7, 1.7], so the change is at most 1.07 g^2 (g = 10 d^0.8).
    assert float(np.max(np.abs(r))) <= 1.1 * _gain(drive) ** 2


@pytest.mark.parametrize("x0", (-1.7, -1.0, -0.5, -0.1, 0.1, 0.5, 1.0, 1.7))
def test_curve_deviation_grows_with_drive_at_every_level(x0: float) -> None:
    """Memoryless curve: for every input level, |curve - x| never shrinks as drive rises."""
    drives = np.concatenate([[0.0], np.geomspace(1e-8, 1.0, 400)])
    dev = np.array([abs(float(K._residual(np.array([x0]), d)[0])) for d in drives])
    assert np.all(np.diff(dev) >= -1e-15), np.diff(dev).min()
