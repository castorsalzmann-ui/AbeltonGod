"""Small deterministic DSP building blocks shared by synthesis and analysis."""

from __future__ import annotations

import math

import numpy as np


def biquad_bandpass(x: np.ndarray, sr: int, f0: float, q: float) -> np.ndarray:
    """RBJ cookbook band-pass, constant 0 dB peak gain."""
    w0 = 2.0 * math.pi * f0 / sr
    alpha = math.sin(w0) / (2.0 * q)
    a0 = 1.0 + alpha
    b0, b2 = alpha / a0, -alpha / a0
    a1, a2 = -2.0 * math.cos(w0) / a0, (1.0 - alpha) / a0
    y = np.zeros_like(x)
    x1 = x2 = y1 = y2 = 0.0
    for i, xi in enumerate(x.tolist()):
        yi = b0 * xi + b2 * x2 - a1 * y1 - a2 * y2
        y[i] = yi
        x2, x1 = x1, xi
        y2, y1 = y1, yi
    return y


def one_pole_lowpass(x: np.ndarray, sr: int, fc: float) -> np.ndarray:
    a = math.exp(-2.0 * math.pi * fc / sr)
    y = np.empty_like(x)
    prev = 0.0
    for i, xi in enumerate(x.tolist()):
        prev = (1.0 - a) * xi + a * prev
        y[i] = prev
    return y


def one_pole_highpass(x: np.ndarray, sr: int, fc: float) -> np.ndarray:
    a = math.exp(-2.0 * math.pi * fc / sr)
    y = np.empty_like(x)
    x_prev = y_prev = 0.0
    for i, xi in enumerate(x.tolist()):
        y_prev = a * (y_prev + xi - x_prev)
        x_prev = xi
        y[i] = y_prev
    return y


def raised_cosine(m: int, rising: bool) -> np.ndarray:
    """Length-m ramp from 0 to 1 (rising) or 1 to 0, both ends exact."""
    if m <= 0:
        return np.ones(0)
    if m == 1:
        return np.zeros(1)
    ramp = 0.5 * (1.0 - np.cos(np.linspace(0.0, math.pi, m)))
    return ramp if rising else ramp[::-1]
