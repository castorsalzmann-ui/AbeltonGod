"""Clap v0.2 "extreme" stages (issue #280, contract ``clap-params`` v0.2).

Every stage is a pure function of its input and its parameters: no random stream, no clock
(the seed's two streams stay noise and room). Each function returns its input object itself when
its off value is given (``fold`` 0, ``crush`` 0, ``rate_div`` 1, ``ring_mix`` 0, ``comb_fb`` 0,
``gate_ms`` 0, ``tail_reverse`` False), so a 0.2 document with every field off renders the
bytes of its 0.1 twin.

Where they sit in the signal path is decided in :func:`audio_engine.clap.render_resolved`
(contract order: crush, rate_div, ring, comb before the ``hp_hz`` high-pass; fold and drive
after the room; gate and reverse last before the fade-out).

``fold`` is continuous at 0. The contract curve ``sin(k pi u / 2)`` with ``k = 1 + 15 fold``
is not the identity at ``k = 1`` (it already lifts quiet parts by up to 3.9 dB relative to the
peak), so the folded curve is crossfaded in over ``fold`` 0 ... :data:`FOLD_BLEND`; above
that the contract curve is used unchanged. ``crush`` is *not* continuous at 0: its first step
is 12 bit by contract (measured in the PR).
"""

from __future__ import annotations

import math

import numpy as np

from .dsp import kaiser_lowpass, oversampled

# Defaults of the v0.2 fields. The root schema keeps the v0.1 properties only, so the engine
# fills these for schema_version "0.2" (the field descriptions in the contract name the same
# values; a test compares them).
V02_DEFAULTS: dict[str, float | int | bool] = {
    "fold": 0, "crush": 0, "rate_div": 1, "ring_hz": 440, "ring_mix": 0,
    "comb_hz": 800, "comb_fb": 0, "gate_ms": 0, "tail_reverse": False,
}
V02_FIELDS = tuple(V02_DEFAULTS)

FOLD_BLEND = 0.1  # fold below this crossfades the folded curve in (continuity at 0)
FOLD_OVERSAMPLE = 8
_FOLD_FILTER = kaiser_lowpass(FOLD_OVERSAMPLE, 0.08, 10.0)  # the kick drive's filter
GATE_FADE_MS = 1.0
JOINT_FADE_MS = 1.0
CRUSH_MAX_BITS, CRUSH_BIT_SPAN = 12.0, 9.0


def fold_factor(amount: float) -> float:
    return 1.0 + 15.0 * amount


def fold(x: np.ndarray, amount: float) -> np.ndarray:
    """Sine wave folding on the peak-normalised signal: ``sin(k pi u / 2)``, ``k = 1 + 15 amount``.

    Returns a peak-1 signal (the caller normalises later anyway). Only the residual
    ``w * (curve(u) - u)`` goes through the oversampler, as in the kick's drive, so the output
    converges to ``u`` as ``amount`` -> 0 and nothing aliases back in the audible band.
    ``w = min(1, amount / FOLD_BLEND)``. Sample 0 is set to zero like after drive.
    """
    if amount <= 0:
        return x
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    if peak == 0.0:
        return x
    k = fold_factor(amount)
    w = min(1.0, amount / FOLD_BLEND)
    u = x / peak
    y = u + oversampled(u, FOLD_OVERSAMPLE, lambda v: w * (np.sin(k * math.pi * v / 2.0) - v),
                        _FOLD_FILTER)
    y[0] = 0.0
    return y


def crush(x: np.ndarray, amount: float) -> np.ndarray:
    """Bit reduction: ``bits = 12 - 9 amount``, round to nearest, no dither.

    Quantised on the peak-normalised signal (full scale = the signal's own peak, so the result
    does not depend on its level), then scaled back.
    """
    if amount <= 0:
        return x
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    if peak == 0.0:
        return x
    step = 2.0 ** (1.0 - (CRUSH_MAX_BITS - CRUSH_BIT_SPAN * amount))
    return np.floor(x / peak / step + 0.5) * step * peak


def rate_div(x: np.ndarray, factor: int) -> np.ndarray:
    """Sample-and-hold: every ``factor`` samples (from sample 0) the value is held."""
    if factor <= 1:
        return x
    return x[(np.arange(len(x)) // factor) * factor]


def ring(x: np.ndarray, sr: int, hz: float, mix: float) -> np.ndarray:
    """``(1 - mix) x + mix x sin(2 pi hz n / sr)``: sine carrier, phase 0 at sample 0."""
    if mix <= 0:
        return x
    carrier = np.sin(2.0 * math.pi * hz * np.arange(len(x)) / sr)
    return (1.0 - mix) * x + mix * x * carrier


def comb(x: np.ndarray, sr: int, hz: float, fb: float) -> np.ndarray:
    """Feedback comb ``y[n] = x[n] + fb y[n - d]``, ``d = round(sr / hz)`` (stable: ``fb`` < 1).

    Evaluated block by block (``d`` samples at a time), which is the recurrence itself.
    """
    if fb <= 0:
        return x
    d = max(1, int(round(sr / hz)))
    y = np.array(x, dtype=np.float64)
    for s in range(d, len(y), d):
        y[s : s + d] += fb * y[s - d : s][: len(y[s : s + d])]
    return y


def gate_window(n: int, sr: int, gate_ms: float) -> np.ndarray | None:
    """Multiplier for a gate ``gate_ms`` after sample 0: 1, a 1 ms linear fade reaching 0 at
    the cut sample, then 0. ``None`` when ``gate_ms`` is 0 (off)."""
    if gate_ms <= 0:
        return None
    cut = int(round(gate_ms * sr / 1000.0))
    fade = max(1, int(round(GATE_FADE_MS * sr / 1000.0)))
    w = np.ones(n)
    idx = np.arange(n)
    ramp = (idx >= cut - fade) & (idx < cut)
    w[ramp] = 1.0 - (idx[ramp] - (cut - fade) + 1) / fade
    w[idx >= cut] = 0.0
    return w


def reverse_tail(x: np.ndarray, start: int, end: int, sr: int) -> np.ndarray:
    """Reverse ``x[start:end]`` in time. Both sides of the joint at ``start`` are faded
    through (almost) zero over 1 ms so the joint cannot click, whatever the level there."""
    end = min(end, len(x))
    if end - start < 2 or start <= 0:
        return x
    y = np.array(x, dtype=np.float64)
    y[start:end] = x[start:end][::-1]
    fade = max(1, min(int(round(JOINT_FADE_MS * sr / 1000.0)), start, (end - start) // 2))
    down = 1.0 - (np.arange(fade) + 1.0) / (fade + 1.0)
    y[start - fade : start] *= down
    y[start : start + fade] *= down[::-1]
    return y
