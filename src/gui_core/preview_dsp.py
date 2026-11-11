"""Small offline DSP blocks for the rough MIDI previews (numpy only, deterministic, no RNG).

Used by ``gui_core.goa_preview`` (#571). Three blocks, each a plain function of arrays:

* :func:`saw` / :func:`square`: band-limited oscillators with a per-sample frequency (so a
  glide is just a frequency ramp). Method: a band-limited impulse train in closed form (a
  ratio of two sines that equals the sum of the cosines of harmonics 1..M, with
  ``M * max(freq) <= HARMONIC_LIMIT * sr``), summed up (``cumsum``). No partial above the
  limit is ever generated, so nothing can fold back. The running sum weights partial ``k``
  with ``x / sin(x)``, ``x = pi * k * f / sr``, relative to the ideal ``1/k`` (arithmetic:
  +0.9 dB at ``sr/4``, +3.1 dB at ``0.45 * sr``).
* :func:`resonant_filter`: a two-pole state-variable filter in trapezoidal (zero-delay
  feedback) form with a per-sample cutoff, low-pass or band-pass output. The recursion runs
  as ONE Python loop over time for all signals at once (numpy across the signals). Long
  signals are cut into chunks of :data:`CHUNK_S`; every chunk but the first starts from zero
  state a warm-up time earlier, long enough for the state to decay by :data:`SEAM_DB`, so the
  loop length does not grow with the clip length.
* :func:`ping_pong`: echoes at multiples of one delay time, alternating left and right, as a
  finite sum: the echoes below :data:`TAIL_FLOOR_DB` (relative to the dry signal) are left
  out, so the result ends in exact silence.

Nothing here makes a claim about sound; the numbers are bounds and working values.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

HARMONIC_LIMIT = 0.45  # x sample rate: highest partial an oscillator generates (derived)
CUTOFF_MAX_FRACTION = 0.45  # x sample rate: the cutoff is clamped to this, below Nyquist (derived)
CUTOFF_MIN_HZ = 20.0  # lower clamp of the cutoff (derived; keeps the warm-up finite)
Q_MIN = 0.5  # lowest quality factor accepted (derived)
Q_MAX = 20.0  # highest quality factor accepted; the stability test runs at this value (derived)
CHUNK_S = 0.1  # filter chunk length in seconds (derived: bounds the Python loop length)
SEAM_DB = -100.0  # state left from before a chunk's warm-up, relative to its start (derived)
TAIL_FLOOR_DB = -60.0  # echoes below this level relative to the dry signal are dropped (derived)
KERNEL_EPS = 1e-9  # below this |sine| the kernel's limit value replaces the ratio (derived)

LOWPASS = "lowpass"
BANDPASS = "bandpass"


def midi_hz(note: float) -> float:
    """Equal temperament, A4 = MIDI 69 = 440 Hz."""
    return 440.0 * 2.0 ** ((note - 69) / 12.0)


def _wave(freq: np.ndarray, sr: int, start_phase: float, odd_only: bool) -> np.ndarray:
    freq = np.asarray(freq, dtype=np.float64)
    if freq.size == 0:
        return np.zeros(0)
    if float(np.min(freq)) <= 0 or float(np.max(freq)) > HARMONIC_LIMIT * sr:
        raise ValueError("oscillator frequency out of range")
    m = max(1, int(HARMONIC_LIMIT * sr / float(np.max(freq))))  # highest harmonic
    inc = freq / sr
    # phase (in periods) of sample n = start + sum of the increments before it
    phase = np.cumsum(inc)
    phase -= inc
    phase += start_phase
    phase -= np.floor(phase)
    if odd_only:
        # sum_{k odd <= M} cos(k theta) = sin(2 N theta) / (2 sin(theta)), N odd harmonics
        mult, scale = 2 * ((m + 1) // 2), -4.0
        angle = phase * (2.0 * np.pi)
        k = np.arange(1, m + 1, 2)
    else:
        # 1 + 2 sum_{k=1..M} cos(k theta) = sin((2M+1) theta/2) / sin(theta/2)
        mult, scale = 2 * m + 1, -2.0
        angle = phase * np.pi
        k = np.arange(1, m + 1)
    den = np.sin(angle)
    small = np.abs(den) < KERNEL_EPS
    hit = bool(small.any())
    if hit:
        den[small] = 1.0
    angle *= mult
    ratio = np.sin(angle, out=angle)
    ratio /= den
    if hit:  # the ratio's limit where the denominator vanishes (-2N at half a period)
        sign = np.where(np.abs(phase[small] - 0.5) < 0.25, -1.0, 1.0) if odd_only else 1.0
        ratio[small] = mult * sign
    if not odd_only:
        ratio -= 1.0
    ratio *= inc
    out = np.cumsum(ratio, out=ratio)
    out *= scale
    # Integration constant for a zero-mean wave, from the closed form of the cosine sums at
    # the start frequency: sum_k sin(k*theta0 - k*a/2) / sin(k*a/2), a = 2*pi*f0/sr.
    a = 2.0 * np.pi * float(inc[0])
    const = float(np.sum(np.sin(k * (2.0 * np.pi * start_phase - a / 2)) / np.sin(k * a / 2)))
    out += scale * float(inc[0]) * const
    return out


def saw(freq: np.ndarray, sr: int, start_phase: float = 0.5) -> np.ndarray:
    """Band-limited rising sawtooth in about [-1, 1] for the per-sample frequency ``freq`` (Hz).

    ``start_phase`` 0.5 starts at the zero crossing of the ramp. Every frequency must be
    positive and at most ``HARMONIC_LIMIT * sr``."""
    return _wave(freq, sr, start_phase, odd_only=False)


def square(freq: np.ndarray, sr: int, start_phase: float = 0.5) -> np.ndarray:
    """Band-limited square in about [-1, 1] (odd harmonics only, same limit as :func:`saw`);
    low in the first half of the period, high in the second."""
    return _wave(freq, sr, start_phase, odd_only=True)


def clamp_cutoff(cutoff: np.ndarray, sr: int) -> np.ndarray:
    """The cutoff the filter really uses: inside [CUTOFF_MIN_HZ, CUTOFF_MAX_FRACTION * sr]."""
    return np.clip(cutoff, CUTOFF_MIN_HZ, CUTOFF_MAX_FRACTION * sr)


def warmup_samples(q: float, min_cutoff_hz: float, sr: int) -> int:
    """Samples after which the filter state has decayed by ``SEAM_DB``. The continuous
    two-pole section decays as ``exp(-pi * fc * t / q)`` (pole real part ``w0 / (2 q)``)."""
    nepers = -SEAM_DB / 20.0 * math.log(10.0)
    return int(math.ceil(nepers * q / (math.pi * min_cutoff_hz) * sr))


def resonant_filter(signals: Sequence[np.ndarray], cutoffs: Sequence[np.ndarray], q: float,
                    sr: int, mode: str = LOWPASS) -> list[np.ndarray]:
    """Filter every signal with its own per-sample cutoff (Hz); all start from zero state.

    Two-pole state-variable filter, trapezoidal integrators. ``mode`` :data:`LOWPASS` has gain
    1 at 0 Hz and about ``q`` at the cutoff; :data:`BANDPASS` has gain 1 at the cutoff. The
    cutoff is clamped by :func:`clamp_cutoff`. The loop below is the only per-sample Python
    loop of the previews; its length is at most chunk + warm-up, whatever the clip length."""
    if mode not in (LOWPASS, BANDPASS):
        raise ValueError("mode must be lowpass or bandpass")
    if not Q_MIN <= q <= Q_MAX:
        raise ValueError(f"q must be {Q_MIN:g}-{Q_MAX:g}")
    if len(signals) != len(cutoffs) or any(len(s) != len(c) for s, c in zip(signals, cutoffs)):
        raise ValueError("every signal needs a cutoff array of its own length")
    cuts = [clamp_cutoff(np.asarray(c, dtype=np.float64), sr) for c in cutoffs]
    live = [i for i, s in enumerate(signals) if len(s)]
    outs = [np.zeros(len(s)) for s in signals]
    if not live:
        return outs
    chunk = max(1, int(CHUNK_S * sr))
    warm = warmup_samples(q, min(float(np.min(cuts[i])) for i in live), sr)
    # (signal index, first input sample incl. warm-up, first kept sample, end)
    plan = [(i, max(0, a - warm), a, min(len(signals[i]), a + chunk))
            for i in live for a in range(0, len(signals[i]), chunk)]
    rows = max(end - lead_in for _, lead_in, _, end in plan)
    x = np.zeros((rows, len(plan)))
    g = np.full((rows, len(plan)), math.pi * CUTOFF_MIN_HZ / sr)
    for col, (i, lead_in, _, end) in enumerate(plan):
        x[: end - lead_in, col] = signals[i][lead_in:end]
        g[: end - lead_in, col] = cuts[i][lead_in:end] * (math.pi / sr)
    np.tan(g, out=g)  # g = tan(pi * fc / sr): the integrator gain with frequency pre-warping
    k = 1.0 / q
    a1 = 1.0 / (1.0 + g * (g + k))
    a2 = g * a1
    a3 = np.multiply(g, a2, out=g)
    s1 = np.zeros(len(plan))
    s2 = np.zeros(len(plan))
    v1 = np.empty(len(plan))
    v2 = np.empty(len(plan))
    v3 = np.empty(len(plan))
    tmp = np.empty(len(plan))
    band = mode == BANDPASS
    for n in range(rows):  # x is overwritten with the output row by row
        xr, a2r = x[n], a2[n]
        np.subtract(xr, s2, out=v3)
        np.multiply(a1[n], s1, out=v1)
        np.multiply(a2r, v3, out=tmp)
        v1 += tmp
        np.multiply(a2r, s1, out=v2)
        v2 += s2
        np.multiply(a3[n], v3, out=tmp)
        v2 += tmp
        np.multiply(v1, 2.0, out=tmp)
        np.subtract(tmp, s1, out=s1)
        np.multiply(v2, 2.0, out=tmp)
        np.subtract(tmp, s2, out=s2)
        xr[:] = v1 if band else v2
    if band:
        x *= k  # unity gain at the cutoff
    for col, (i, lead_in, keep, end) in enumerate(plan):
        outs[i][keep:end] = x[keep - lead_in: end - lead_in, col]
    return outs


def echo_count(feedback: float, wet: float, floor_db: float = TAIL_FLOOR_DB) -> int:
    """How many echoes :func:`ping_pong` renders: echo ``j`` has the level
    ``wet / (1 - wet) * feedback ** (j - 1)`` relative to the dry signal; the first one below
    ``floor_db`` and all later ones are dropped."""
    if not 0.0 <= feedback < 1.0:
        raise ValueError("feedback must be at least 0 and below 1")
    if not 0.0 <= wet < 1.0:
        raise ValueError("wet must be at least 0 and below 1")
    if wet == 0.0:
        return 0
    floor = 10.0 ** (floor_db / 20.0)
    level = wet / (1.0 - wet)
    count = 0
    while level >= floor:
        count += 1
        if feedback == 0.0:
            break
        level *= feedback
    return count


def ping_pong(x: np.ndarray, delay_samples: int, feedback: float, wet: float,
              floor_db: float = TAIL_FLOOR_DB) -> np.ndarray:
    """Stereo ``(len(x) + echoes * delay_samples, 2)``: the dry signal times ``1 - wet`` on
    both channels, echo 1, 3, 5 ... on the left, echo 2, 4, 6 ... on the right, echo ``j``
    ``j * delay_samples`` late with gain ``wet * feedback ** (j - 1)``."""
    if delay_samples < 1:
        raise ValueError("delay must be at least one sample")
    count = echo_count(feedback, wet, floor_db)
    n = len(x)
    out = np.zeros((n + count * delay_samples, 2))
    out[:n, 0] = out[:n, 1] = (1.0 - wet) * x
    for j in range(1, count + 1):
        out[j * delay_samples: j * delay_samples + n, (j - 1) % 2] += (
            wet * feedback ** (j - 1)) * x
    return out
