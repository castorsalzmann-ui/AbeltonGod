"""Deterministic kick synthesis.

Signal chain (all mono, float64, sample-exact for given parameters and seed):

1. Body: sine whose frequency falls exponentially from ``pitch_start_hz`` to ``pitch_end_hz``
   with time constant ``pitch_decay_ms`` (phase is the analytic integral, no accumulation error).
2. Amplitude envelope: linear attack over ``amp_attack_ms``, then exponential decay where
   ``amp_decay_ms`` is the time to fall by 60 dB.
3. Click: band-pass filtered noise burst (seeded RNG) centred on ``click_tone_hz``, mixed at
   ``click_level``.
4. Drive: normalised tanh saturation, ``drive`` 0 = clean, 1 = heavy.
5. Tone: tilt around a one-pole low-pass at 1.5 kHz; ``tone`` -1 = darker, +1 = brighter.
6. DC blocker (one-pole high-pass, 10 Hz), 5 ms cosine fade-out.
7. Normalise so the absolute peak equals ``peak_ceiling_dbfs``.

The same resolved parameters always give the same samples. No wall clock, no global RNG.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .params import resolve_kick_params

CLICK_LENGTH_MS = 15.0
CLICK_DECAY_MS = 3.0
TONE_PIVOT_HZ = 1500.0
DC_BLOCK_HZ = 10.0
FADE_OUT_MS = 5.0


def render_kick(params: dict[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    """Render one kick. Returns ``(audio, resolved_params)``; audio is float64 in [-1, 1]."""
    p = resolve_kick_params(params)
    sr = int(p["sample_rate"])
    n = int(round(p["length_ms"] * sr / 1000.0))
    t = np.arange(n, dtype=np.float64) / sr

    body = _body(t, p["pitch_start_hz"], p["pitch_end_hz"], p["pitch_decay_ms"] / 1000.0)
    env = _amp_envelope(t, p["amp_attack_ms"] / 1000.0, p["amp_decay_ms"] / 1000.0)
    x = body * env

    if p["click_level"] > 0:
        x = x + p["click_level"] * _click(n, sr, p["click_tone_hz"], p["seed"])

    x = _drive(x, p["drive"])
    x = _tone(x, sr, p["tone"])
    x = _one_pole_highpass(x, sr, DC_BLOCK_HZ)
    x = _fade_out(x, sr, FADE_OUT_MS)
    x = _normalise(x, p["peak_ceiling_dbfs"])
    return x, p


def _body(t: np.ndarray, f_start: float, f_end: float, tau: float) -> np.ndarray:
    # f(t) = f_end + (f_start - f_end) * exp(-t / tau); phase = 2*pi * integral of f.
    phase = 2.0 * math.pi * (f_end * t + (f_start - f_end) * tau * (1.0 - np.exp(-t / tau)))
    return np.sin(phase)


def _amp_envelope(t: np.ndarray, attack: float, decay_to_60db: float) -> np.ndarray:
    tau = decay_to_60db / math.log(1000.0)
    after = np.clip(t - attack, 0.0, None)
    env = np.exp(-after / tau)
    if attack > 0:
        env = np.where(t < attack, t / attack, env)
    return env


def _click(n: int, sr: int, centre_hz: float, seed: int) -> np.ndarray:
    m = min(n, int(round(CLICK_LENGTH_MS * sr / 1000.0)))
    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(m)
    tc = np.arange(m, dtype=np.float64) / sr
    burst = noise * np.exp(-tc / (CLICK_DECAY_MS / 1000.0))
    centre = min(centre_hz, 0.45 * sr)
    filtered = _biquad_bandpass(burst, sr, centre, q=0.9)
    peak = float(np.max(np.abs(filtered))) or 1.0
    out = np.zeros(n)
    out[:m] = filtered / peak
    return out


def _biquad_bandpass(x: np.ndarray, sr: int, f0: float, q: float) -> np.ndarray:
    # RBJ cookbook band-pass, constant 0 dB peak gain.
    w0 = 2.0 * math.pi * f0 / sr
    alpha = math.sin(w0) / (2.0 * q)
    b0, b1, b2 = alpha, 0.0, -alpha
    a0, a1, a2 = 1.0 + alpha, -2.0 * math.cos(w0), 1.0 - alpha
    b0, b1, b2, a1, a2 = b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0
    y = np.zeros_like(x)
    x1 = x2 = y1 = y2 = 0.0
    for i, xi in enumerate(x.tolist()):
        yi = b0 * xi + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        y[i] = yi
        x2, x1 = x1, xi
        y2, y1 = y1, yi
    return y


def _drive(x: np.ndarray, drive: float) -> np.ndarray:
    if drive <= 0:
        return x
    gain = 1.0 + 9.0 * drive
    return np.tanh(gain * x) / math.tanh(gain)


def _one_pole_lowpass(x: np.ndarray, sr: int, fc: float) -> np.ndarray:
    a = math.exp(-2.0 * math.pi * fc / sr)
    y = np.empty_like(x)
    prev = 0.0
    for i, xi in enumerate(x.tolist()):
        prev = (1.0 - a) * xi + a * prev
        y[i] = prev
    return y


def _tone(x: np.ndarray, sr: int, tone: float) -> np.ndarray:
    if tone == 0:
        return x
    low = _one_pole_lowpass(x, sr, TONE_PIVOT_HZ)
    if tone < 0:
        return x + (-tone) * (low - x)
    return x + tone * (x - low)


def _one_pole_highpass(x: np.ndarray, sr: int, fc: float) -> np.ndarray:
    a = math.exp(-2.0 * math.pi * fc / sr)
    y = np.empty_like(x)
    x_prev = y_prev = 0.0
    for i, xi in enumerate(x.tolist()):
        y_prev = a * (y_prev + xi - x_prev)
        x_prev = xi
        y[i] = y_prev
    return y


def _fade_out(x: np.ndarray, sr: int, ms: float) -> np.ndarray:
    m = min(len(x), int(round(ms * sr / 1000.0)))
    if m == 0:
        return x
    ramp = 0.5 * (1.0 + np.cos(np.linspace(0.0, math.pi, m)))
    y = x.copy()
    y[-m:] *= ramp
    return y


def _normalise(x: np.ndarray, ceiling_dbfs: float) -> np.ndarray:
    peak = float(np.max(np.abs(x)))
    if peak == 0.0:
        return x
    return x * (10.0 ** (ceiling_dbfs / 20.0) / peak)
