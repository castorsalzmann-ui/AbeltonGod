"""Deterministic kick synthesis.

Signal chain (all mono, float64, sample-exact for given parameters and seed):

1. Body: sine whose frequency falls exponentially from ``pitch_start_hz`` towards
   ``pitch_end_hz`` with time constant ``pitch_decay_ms`` (phase is the analytic integral,
   see :func:`body_phase`). ``pitch_end_hz`` is the asymptote: with a long ``pitch_decay_ms``
   the kick can fade out before it gets there.
2. Amplitude envelope: linear attack over ``amp_attack_ms``, then exponential decay where
   ``amp_decay_ms`` is the time to fall by 60 dB.
3. Click: band-pass filtered noise burst (seeded RNG) centred on ``click_tone_hz``, mixed at
   ``click_level``; raised-cosine edges so it starts and ends at exactly zero.
4. Drive: normalised tanh saturation, ``drive`` 0 = clean, 1 = heavy. Computed at
   ``DRIVE_OVERSAMPLE`` times the sample rate with a linear-phase low-pass, so the partials
   tanh creates above the Nyquist frequency are removed instead of aliasing back into the
   audible band. Sample 0 is then set to exactly zero: the band-limited result is slightly
   non-zero there (up to a few percent of peak with ``amp_attack_ms`` 0), and every kick
   starts at exactly zero, as it did with the base-rate tanh.
5. Tone: tilt around a one-pole low-pass at 1.5 kHz; ``tone`` -1 = darker, +1 = brighter.
6. DC blocker (one-pole high-pass, 10 Hz), 5 ms cosine fade-out, then the remaining mean is
   removed with a Hann-shaped correction so the first and last samples stay exactly zero.
7. Normalise so that even after quantising to ``bit_depth`` the peak stays at or below
   ``peak_ceiling_dbfs``.

The same parameters always give the same samples. No wall clock, no global RNG.
``variants`` is a batch instruction for the caller (Phase 01b) and is not part of a single
render; it is removed from the returned parameters.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .dsp import (
    biquad_bandpass,
    kaiser_lowpass,
    one_pole_highpass,
    one_pole_lowpass,
    oversampled,
    raised_cosine,
)
from .params import resolve_kick_params

CLICK_LENGTH_MS = 15.0
CLICK_DECAY_MS = 3.0
CLICK_FADE_IN_MS = 0.25
CLICK_FADE_OUT_MS = 2.0
CLICK_Q = 0.9
TONE_PIVOT_HZ = 1500.0
DC_BLOCK_HZ = 10.0
FADE_OUT_MS = 5.0
# Drive anti-aliasing: 8x oversampling, Kaiser low-pass with ~100 dB stop band and a
# transition of 8 % of the sample rate centred on Nyquist (48 kHz: 22.1-25.9 kHz).
DRIVE_OVERSAMPLE = 8
DRIVE_FILTER_TRANSITION = 0.08
DRIVE_FILTER_BETA = 10.0
_DRIVE_FILTER = kaiser_lowpass(DRIVE_OVERSAMPLE, DRIVE_FILTER_TRANSITION, DRIVE_FILTER_BETA)

# Parameters that describe how many kicks to make, not how one kick sounds.
BATCH_ONLY_PARAMS = ("variants",)


def render_kick(params: dict[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    """Render one kick. Returns ``(audio, resolved_params)``; audio is float64 in [-1, 1]."""
    p = resolve_kick_params(params)
    for key in BATCH_ONLY_PARAMS:
        p.pop(key, None)
    sr = int(p["sample_rate"])
    n = int(round(p["length_ms"] * sr / 1000.0))
    t = np.arange(n, dtype=np.float64) / sr

    x = np.sin(body_phase(t, p)) * _amp_envelope(
        t, p["amp_attack_ms"] / 1000.0, p["amp_decay_ms"] / 1000.0
    )
    if p["click_level"] > 0:
        x = x + p["click_level"] * _click(n, sr, p["click_tone_hz"], p["seed"])

    x = _drive(x, p["drive"])
    x = _tone(x, sr, p["tone"])
    x = one_pole_highpass(x, sr, DC_BLOCK_HZ)
    x = _fade_out(x, sr, FADE_OUT_MS)
    x = _remove_mean(x)
    x = _normalise(x, p["peak_ceiling_dbfs"], p["bit_depth"])
    return x, p


def body_phase(t: np.ndarray, p: dict[str, Any]) -> np.ndarray:
    """Analytic body phase: 2*pi * integral of f(t) = f_end + (f_start - f_end) * e^(-t/tau)."""
    f_start, f_end = p["pitch_start_hz"], p["pitch_end_hz"]
    tau = p["pitch_decay_ms"] / 1000.0
    return 2.0 * math.pi * (f_end * t + (f_start - f_end) * tau * (1.0 - np.exp(-t / tau)))


def _amp_envelope(t: np.ndarray, attack: float, decay_to_60db: float) -> np.ndarray:
    tau = decay_to_60db / math.log(1000.0)
    env = np.exp(-np.clip(t - attack, 0.0, None) / tau)
    if attack > 0:
        env = np.where(t < attack, t / attack, env)
    return env


def _click(n: int, sr: int, centre_hz: float, seed: int) -> np.ndarray:
    m = min(n, int(round(CLICK_LENGTH_MS * sr / 1000.0)))
    rng = np.random.default_rng(seed)
    tc = np.arange(m, dtype=np.float64) / sr
    burst = rng.standard_normal(m) * np.exp(-tc / (CLICK_DECAY_MS / 1000.0))
    filtered = biquad_bandpass(burst, sr, min(centre_hz, 0.45 * sr), CLICK_Q)
    # Exact zero at both ends: no step at sample 0, no hard cut after 15 ms.
    fade_in = min(m, max(2, int(round(CLICK_FADE_IN_MS * sr / 1000.0))))
    fade_out = min(m - fade_in, int(round(CLICK_FADE_OUT_MS * sr / 1000.0)))
    filtered[:fade_in] *= raised_cosine(fade_in, rising=True)
    if fade_out > 0:
        filtered[m - fade_out :] *= raised_cosine(fade_out, rising=False)
    peak = float(np.max(np.abs(filtered))) if m else 0.0
    out = np.zeros(n)
    if peak > 0:
        out[:m] = filtered / peak
    return out


def _drive(x: np.ndarray, drive: float) -> np.ndarray:
    if drive <= 0:
        return x
    y = oversampled(x, DRIVE_OVERSAMPLE, lambda u: _saturate(u, drive), _DRIVE_FILTER)
    if len(y):
        y[0] = 0.0
    return y


def _saturate(x: np.ndarray, drive: float) -> np.ndarray:
    """Memoryless normalised tanh curve; maps [-1, 1] onto [-1, 1]."""
    gain = 1.0 + 9.0 * drive
    return np.tanh(gain * x) / math.tanh(gain)


def _tone(x: np.ndarray, sr: int, tone: float) -> np.ndarray:
    if tone == 0:
        return x
    low = one_pole_lowpass(x, sr, TONE_PIVOT_HZ)
    if tone < 0:
        return x + (-tone) * (low - x)
    return x + tone * (x - low)


def _fade_out(x: np.ndarray, sr: int, ms: float) -> np.ndarray:
    m = min(len(x), int(round(ms * sr / 1000.0)))
    y = x.copy()
    if m > 0:
        y[-m:] *= raised_cosine(m, rising=False)
    return y


def _remove_mean(x: np.ndarray) -> np.ndarray:
    """Subtract the mean as a Hann-shaped bump (zero at both ends) instead of a constant.

    Short or truncated kicks contain an incomplete last cycle, so their mean is not zero even
    without any real offset. A constant subtraction would create a step at start and end;
    the Hann shape removes exactly the mean while keeping both ends at zero.
    """
    n = len(x)
    if n < 3:
        return x
    w = 0.5 * (1.0 - np.cos(2.0 * math.pi * np.arange(n) / (n - 1)))
    return x - (float(np.mean(x)) / float(np.mean(w))) * w


def _normalise(x: np.ndarray, ceiling_dbfs: float, bit_depth: int) -> np.ndarray:
    """Scale so the quantised peak cannot exceed the ceiling (half an LSB of headroom)."""
    peak = float(np.max(np.abs(x)))
    if peak == 0.0:
        return x
    full_scale = 2 ** (bit_depth - 1) - 1
    target = 10.0 ** (ceiling_dbfs / 20.0) - 0.5 / full_scale
    return x * (target / peak)
