"""ITU-R BS.1770-4 loudness in NumPy: K-weighting, momentary, short-term, integrated (#483).

Measurement only; nothing in the engine calls it yet. No new dependency.

Input: ``audio`` of shape ``(n,)`` (mono) or ``(n, c)`` with ``1 <= c <= 5`` channels in the
BS.1770 order L, R, C, Ls, Rs. Channel weights G = 1, 1, 1, 1.41, 1.41 (BS.1770-4 Table 3).
A mono file is one channel with weight 1 (no "dual mono" +3 dB), so a sine gives 3.01 dB less
on a mono file than the same sine on both channels of a stereo file. LFE is not supported.

K-weighting = two biquads in series: the pre-filter (high shelf, about +4 dB above ~1.7 kHz)
and the RLB high-pass (~38 Hz). BS.1770-4 publishes digital coefficients for 48 kHz only. For
every rate the coefficients are computed here with the bilinear transform from analog
parameters (f0, gain, Q) that reproduce the 48 kHz table; those parameter values are the ones
used in libebur128 (``ebur128_init_filter``) and pyloudnorm, quoted from memory, not
re-opened on 2026-11-07. At 48 kHz they reproduce the standard's table to within 1e-12
(checked in ``tests/audio_engine/test_loudness.py`` against the table written in the test).

Filtering: the cascade's impulse response is computed once per rate (direct recursion) and
truncated where it has decayed below 1e-18 of its peak scale, then applied by FFT
convolution. That is a speed measure (a Python sample loop over minutes of audio is too slow);
the test compares it against the recursive biquad in ``dsp._biquad`` (max difference < 1e-9).

Windows (sample counts are rounded to the nearest integer at the given rate):

* momentary: 400 ms rectangular, ungated (EBU Tech 3341);
* short-term: 3 s rectangular, ungated;
* integrated: 400 ms gating blocks with 75 % overlap (step 100 ms), absolute gate -70 LUFS,
  relative gate 10 LU below the loudness of the blocks that pass the absolute gate. A block
  passes a gate when its loudness is strictly above it (BS.1770-4, eq. 5-7).

``momentary_lufs`` / ``short_term_lufs`` return one value per window; the first window starts
at sample 0, windows advance by ``hop_s`` and only windows that lie fully inside the file are
measured (a file shorter than the window gives an empty array). A window, block or file with
zero energy measures ``-inf``; ``integrated_lufs`` is ``-inf`` when no block passes the
absolute gate (silence, or a file shorter than 400 ms).

Not implemented: true-peak (BS.1770-4 Annex 2, oversampled peak). Skipped on purpose; use
sample peak with that limitation in mind. Loudness range (LRA, Tech 3342) is not implemented.
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np

from .dsp import fft_size

LOUDNESS_OFFSET_DB = -0.691  # BS.1770-4 eq. 2: makes a 997 Hz sine at 0 dBFS on L read -3.01 LKFS
CHANNEL_WEIGHTS = (1.0, 1.0, 1.0, 1.41, 1.41)  # L, R, C, Ls, Rs (BS.1770-4 Table 3)
MOMENTARY_S = 0.4
SHORT_TERM_S = 3.0
BLOCK_S = 0.4
BLOCK_STEP_S = 0.1  # 75 % overlap
ABSOLUTE_GATE_LUFS = -70.0
RELATIVE_GATE_LU = -10.0

# Analog parameters of the two K-weighting stages (libebur128 / pyloudnorm values, see above).
_SHELF_F0 = 1681.974450955533
_SHELF_GAIN_DB = 3.999843853973347
_SHELF_Q = 0.7071752369554196
_SHELF_VB_EXP = 0.4996667741545416
_HP_F0 = 38.13547087602444
_HP_Q = 0.5003270373238773

_IR_FLOOR = 1e-18

Biquad = tuple[tuple[float, float, float], tuple[float, float, float]]


def k_weighting_coefficients(sample_rate: int) -> tuple[Biquad, Biquad]:
    """``((b, a) pre-filter, (b, a) RLB high-pass)`` for ``sample_rate``, ``a[0] == 1``."""
    sr = _check_rate(sample_rate)
    k = math.tan(math.pi * _SHELF_F0 / sr)
    vh = 10.0 ** (_SHELF_GAIN_DB / 20.0)
    vb = vh**_SHELF_VB_EXP
    a0 = 1.0 + k / _SHELF_Q + k * k
    shelf = (
        ((vh + vb * k / _SHELF_Q + k * k) / a0, 2.0 * (k * k - vh) / a0,
         (vh - vb * k / _SHELF_Q + k * k) / a0),
        (1.0, 2.0 * (k * k - 1.0) / a0, (1.0 - k / _SHELF_Q + k * k) / a0),
    )
    k = math.tan(math.pi * _HP_F0 / sr)
    a0 = 1.0 + k / _HP_Q + k * k
    highpass = (
        (1.0, -2.0, 1.0),
        (1.0, 2.0 * (k * k - 1.0) / a0, (1.0 - k / _HP_Q + k * k) / a0),
    )
    return shelf, highpass


def _recursive(x: list[float], b, a) -> list[float]:
    b0, b1, b2 = b
    _, a1, a2 = a
    y = []
    x1 = x2 = y1 = y2 = 0.0
    for xi in x:
        yi = b0 * xi + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        y.append(yi)
        x2, x1 = x1, xi
        y2, y1 = y1, yi
    return y


@lru_cache(maxsize=16)
def _impulse_response(sample_rate: int) -> np.ndarray:
    stages = k_weighting_coefficients(sample_rate)
    radius = max(float(np.max(np.abs(np.roots(a)))) for _, a in stages)
    # Repeated real poles (the RLB high-pass is near critically damped) decay as n * r^n; the
    # factor 2 on the length covers that term with a wide margin.
    length = 2 * math.ceil(math.log(_IR_FLOOR) / math.log(radius)) + 3
    h = [1.0] + [0.0] * (length - 1)
    for b, a in stages:
        h = _recursive(h, b, a)
    out = np.asarray(h, dtype=np.float64)
    out.setflags(write=False)
    return out


def k_weight(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    """K-weighted copy of ``audio`` (same shape, float64); zero initial filter state."""
    x = _as_channels(audio)
    h = _impulse_response(_check_rate(sample_rate))
    n = x.shape[0]
    if n == 0:
        return np.zeros_like(x).reshape(np.shape(audio))
    size = fft_size(n + h.size - 1)
    spectrum = np.fft.rfft(h, size)
    y = np.fft.irfft(np.fft.rfft(x, size, axis=0) * spectrum[:, None], size, axis=0)[:n]
    return y.reshape(np.shape(audio)) if np.ndim(audio) == 1 else y


def momentary_lufs(audio: np.ndarray, sample_rate: int, hop_s: float = 0.1) -> np.ndarray:
    """Loudness of each 400 ms window (ungated), windows every ``hop_s`` seconds."""
    return _windowed(audio, sample_rate, MOMENTARY_S, hop_s)


def short_term_lufs(audio: np.ndarray, sample_rate: int, hop_s: float = 0.1) -> np.ndarray:
    """Loudness of each 3 s window (ungated), windows every ``hop_s`` seconds."""
    return _windowed(audio, sample_rate, SHORT_TERM_S, hop_s)


def integrated_lufs(audio: np.ndarray, sample_rate: int) -> float:
    """Gated integrated loudness (BS.1770-4) in LUFS; ``-inf`` if no block passes -70 LUFS."""
    sr = _check_rate(sample_rate)
    power = _window_power(audio, sr, BLOCK_S, BLOCK_STEP_S)
    loud = _to_lufs(power)
    above_abs = loud > ABSOLUTE_GATE_LUFS
    if not np.any(above_abs):
        return float("-inf")
    relative_gate = float(_to_lufs(np.mean(power[above_abs]))) + RELATIVE_GATE_LU
    gated = above_abs & (loud > relative_gate)
    return float(_to_lufs(np.mean(power[gated])))


# --- helpers -------------------------------------------------------------------------------


def _windowed(audio, sample_rate, window_s: float, hop_s: float) -> np.ndarray:
    sr = _check_rate(sample_rate)
    return _to_lufs(_window_power(audio, sr, window_s, hop_s))


def _window_power(audio, sr: int, window_s: float, hop_s: float) -> np.ndarray:
    """Channel-weighted mean square of the K-weighted signal per window."""
    if not (math.isfinite(hop_s) and hop_s > 0):
        raise ValueError(f"hop_s must be a positive number, got {hop_s!r}")
    x = _as_channels(audio)
    y = k_weight(x, sr)
    weights = np.asarray(CHANNEL_WEIGHTS[: x.shape[1]])
    z = (y * y) @ weights
    window = round(window_s * sr)
    hop = max(1, round(hop_s * sr))
    if z.size < window:
        return np.zeros(0)
    starts = np.arange(0, z.size - window + 1, hop)
    csum = np.concatenate(([0.0], np.cumsum(z)))
    power = (csum[starts + window] - csum[starts]) / window
    # Cumulative-sum rounding can leave a tiny negative value on a silent window.
    return np.maximum(power, 0.0)


def _to_lufs(power):
    with np.errstate(divide="ignore"):
        return LOUDNESS_OFFSET_DB + 10.0 * np.log10(power)


def _as_channels(audio) -> np.ndarray:
    x = np.asarray(audio, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    if x.ndim != 2 or not 1 <= x.shape[1] <= len(CHANNEL_WEIGHTS):
        raise ValueError(
            f"audio must have shape (n,) or (n, c) with 1 <= c <= 5, got {np.shape(audio)}"
        )
    if not np.all(np.isfinite(x)):
        raise ValueError("audio contains NaN or infinity")
    return x


def _check_rate(sample_rate) -> int:
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, (int, np.integer)):
        raise ValueError(f"sample_rate must be an int, got {sample_rate!r}")
    if not 8000 <= int(sample_rate) <= 384000:
        raise ValueError(f"sample_rate must be 8000..384000 Hz, got {sample_rate}")
    return int(sample_rate)
