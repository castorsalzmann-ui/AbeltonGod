"""Small deterministic DSP building blocks shared by synthesis and analysis."""

from __future__ import annotations

import math
from collections import OrderedDict

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


def fft_size(n: int) -> int:
    """Smallest even number >= ``n`` with no prime factor above 5 (fast FFT length)."""
    best = None
    p2 = 2
    while p2 < 2 * n + 2:
        p3 = p2
        while p3 < 2 * n + 2:
            p5 = p3
            while p5 < 2 * n + 2:
                if p5 >= n and (best is None or p5 < best):
                    best = p5
                p5 *= 5
            p3 *= 3
        p2 *= 2
    return best


# Filter spectra are the same for every render of the same length, so the last few are kept.
_SPECTRA: OrderedDict = OrderedDict()
_SPECTRA_MAX = 4


def _filter_spectra(h: np.ndarray, factor: int, size: int) -> tuple[np.ndarray, np.ndarray]:
    """Spectra (rfft bins of length ``size``) for the up- and down-sampling filter.

    The down-sampling one includes the filter delay as a phase shift and the 1/factor of
    the decimation fold.
    """
    key = (size, factor, h.tobytes())
    if key in _SPECTRA:
        _SPECTRA.move_to_end(key)
        return _SPECTRA[key]
    delay = (len(h) - 1) // 2
    spec = np.fft.rfft(h, size)
    shift = np.exp(2j * math.pi * np.arange(size // 2 + 1) * delay / size)
    _SPECTRA[key] = (spec * factor, spec * shift / factor)
    if len(_SPECTRA) > _SPECTRA_MAX:
        _SPECTRA.popitem(last=False)
    return _SPECTRA[key]


def kaiser_lowpass(factor: int, transition: float, beta: float) -> np.ndarray:
    """Linear-phase windowed-sinc low-pass for resampling by ``factor``.

    The cut-off sits at the Nyquist frequency of the base rate. ``transition`` is the full
    transition width as a fraction of the base sample rate, centred on that Nyquist frequency.
    The returned taps have an odd length (integer group delay) and unit DC gain.
    """
    # Kaiser's estimate: N = (A - 8) / (2.285 * delta_omega), A from beta (beta = 0.1102*(A-8.7)).
    atten = beta / 0.1102 + 8.7
    delta_omega = 2.0 * math.pi * transition / factor
    taps = int(math.ceil((atten - 8.0) / (2.285 * delta_omega)))
    taps += 1 - taps % 2
    m = np.arange(taps, dtype=np.float64) - (taps - 1) / 2.0
    h = np.sinc(m / factor) * np.kaiser(taps, beta)
    return h / h.sum()


def oversampled(x: np.ndarray, factor: int, fn, h: np.ndarray) -> np.ndarray:
    """Apply the memoryless function ``fn`` at ``factor`` times the sample rate.

    ``x`` is upsampled (zero stuffing + ``h``), ``fn`` is applied, the result is low-passed with
    ``h`` again and decimated. Both filter delays are removed, so output sample ``i`` lines up
    with input sample ``i``. Partials that ``fn`` creates above the base Nyquist frequency are
    filtered out instead of folding back into the audible band (aliasing).

    Both filters run as FFT convolutions over the whole signal (one large FFT each way; zero
    stuffing and decimation are done in the frequency domain). So a single NaN or Inf sample
    makes the whole output non-finite (callers pass finite, validated audio). A one-sample
    input is band-limited like an impulse, so ``fn`` is not applied to its value directly.
    """
    if factor < 1:
        raise ValueError(f"factor must be >= 1, got {factor}")
    n = len(x)
    if n == 0:
        return x.copy()
    delay = (len(h) - 1) // 2
    # Base-rate length m (fast FFT size) with room for the whole linear convolution, so the
    # circular FFT convolutions below never wrap around.
    m = fft_size(n + -(-(len(h) - 1) // factor))
    size = factor * m
    up_spec, down_spec = _filter_spectra(h, factor, size)
    # Zero stuffing repeats the base spectrum `factor` times; build it directly.
    base = np.fft.fft(x, m)
    up = np.fft.irfft(base[np.arange(size // 2 + 1) % m] * up_spec, size)[: n * factor + delay]
    up = up[delay:]
    z = np.fft.rfft(fn(up), size) * down_spec
    # Keeping every factor-th sample folds the full spectrum onto the base band.
    full = np.concatenate([z, np.conj(z[1 : size // 2][::-1])])
    return np.fft.ifft(full.reshape(factor, m).sum(axis=0)).real[:n]
