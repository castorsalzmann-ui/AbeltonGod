"""The -60 dB rule of ``length_beats`` (kick-params v0.3, rule (a), user decision on PR #114).

The contract text (``length_beats`` description) is implemented step by step:

1. Signal: the integer sample values written to the WAV (the candidate is encoded with
   :func:`audio_engine.io.encode_wav` and read back with :func:`audio_engine.io.wav_samples`),
   whole file including any ``offset_ms`` lead-in. A fraction of full scale is that integer
   divided by the full-scale value; every comparison below is a ratio, so the integers are
   used directly.
2. Envelope: rectangular RMS over ``N = sample_rate // 200`` samples, hop 1 sample, for every
   window start ``i = 0 … n - N``.
3. Reference ``R = max r``, ``i_max`` = the first ``i`` with ``r[i] = R``.
4. ``i60`` = the first ``i > i_max`` with ``20 * log10(r[i] / R) <= -60``; ``T60 = (i60 + N) /
   sample_rate`` (window end). No such window: does not fit.
5. Fits: ``T60 <= (n - n_fade) / sample_rate``.
6. An explicit ``amp_decay_ms`` that does not fit is rejected; the error names the value of
   (6a), or uses the (6a) wording when (6a) itself rejects (PR #114 review round 2, nit 1).
6a. Without ``amp_decay_ms``: bisection on the grid ``round(20 + k / 10, 1)``, ``k = 0 … 19800``,
    exactly as written in the contract.

Exact arithmetic: ``r[i] = sqrt(S[i] / N) / full_scale`` with the integer window sum of
squares ``S[i]``, so ``20 * log10(r[i] / R) <= -60`` is ``S[i] / S_max <= 10 ** -6``, i.e.
``S[i] <= S_max // 10 ** 6`` for integers. ``r[i] = R`` is ``S[i] = S_max``, and step 5 is
``i60 + N <= n - n_fade``. Window sums fit in int64: at most ``N * (2 ** 23) ** 2`` per
window and ``96000 * (2 ** 23) ** 2 < 2 ** 63`` for the whole cumulative sum (2000 ms at
48 kHz). So no floating-point or libm result takes the decision, and the derived value is the
same on every platform the renders are byte-identical on.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

import numpy as np

from .io import encode_wav, wav_samples
from .kick import fade_out_samples, render_resolved

GRID_MIN_MS = 20.0
GRID_STEPS = 19800  # k = 0 … 19800 -> 20.0 … 2000.0 ms in 0.1 ms steps
LEVEL_RATIO = 10**6  # -60 dB in power: S[i] * 10**6 <= S_max


def grid_value(k: int) -> float:
    """Grid value ``k``: ``round(20 + k / 10, 1)`` ms (contract text)."""
    return round(GRID_MIN_MS + k / 10, 1)


def window_samples(sr: int) -> int:
    """``N = sample_rate // 200`` (240 at 48 kHz, 220 at 44.1 kHz)."""
    return int(sr) // 200


def t60_window(samples: np.ndarray, sr: int) -> int | None:
    """``i60`` of step 4 (start of the first window 60 dB below the RMS maximum after
    ``i_max``), or ``None`` if there is none (also for silence or a file shorter than N)."""
    ints = np.asarray(samples, dtype=np.int64)
    n_win = window_samples(sr)
    if len(ints) < n_win:
        return None
    csum = np.concatenate([[0], np.cumsum(ints * ints)])
    sums = csum[n_win:] - csum[:-n_win]  # S[i] for i = 0 … n - N
    s_max = int(sums.max())
    if s_max == 0:
        return None
    i_max = int(np.argmax(sums))  # first maximum
    below = np.flatnonzero(sums[i_max + 1 :] <= s_max // LEVEL_RATIO)
    if len(below) == 0:
        return None
    return i_max + 1 + int(below[0])


def t60_seconds(samples: np.ndarray, sr: int) -> float | None:
    """``T60 = (i60 + N) / sample_rate`` or ``None`` (step 4)."""
    i60 = t60_window(samples, sr)
    return None if i60 is None else (i60 + window_samples(sr)) / sr


def samples_fit(samples: np.ndarray, sr: int) -> bool:
    """Step 5 on quantised samples: the -60 dB window ends before the end fade-out."""
    n = len(samples)
    i60 = t60_window(samples, sr)
    return i60 is not None and i60 + window_samples(sr) <= n - fade_out_samples(n, sr)


def fits(resolved: dict[str, Any]) -> bool:
    """Steps 1-5 for resolved parameters (``amp_decay_ms`` set): render, quantise, check."""
    return _fits_cached(_key(resolved))


def derive_amp_decay(resolved: dict[str, Any]) -> float | None:
    """Step 6a: the bisection result for ``resolved`` (its ``amp_decay_ms`` is ignored), or
    ``None`` when 20.0 ms does not fit (rejected)."""
    base = {k: v for k, v in resolved.items() if k != "amp_decay_ms"}
    return _derive_cached(_key(base))


def apply_length_rule(resolved: dict[str, Any], beats: float, decay_given: bool) -> str | None:
    """Rule (6)/(6a) on a resolved ``length_beats`` request, in place.

    Without ``amp_decay_ms`` the derived value is stored as ``amp_decay_ms``. Returns ``None``
    on success, else the error line (without the leading ``- ``)."""
    where = (
        f"length_beats {beats} at {resolved['bpm']} BPM ({resolved['length_ms']:.6g} ms, "
        "the 5 ms end fade-out not counted)"
    )
    no_fit = (
        "no amp_decay_ms of 20 ms or more decays 60 dB within length_beats at this bpm "
        f"({where}); shorten the decay by other means or use more beats"
    )
    if decay_given:
        if fits(resolved):
            return None
        derived = derive_amp_decay(resolved)
        if derived is None:
            return f"amp_decay_ms {resolved['amp_decay_ms']}: {no_fit}"
        return (
            f"amp_decay_ms {resolved['amp_decay_ms']} does not decay 60 dB within {where}; "
            f"the rule derives {derived} for these values (omit amp_decay_ms to use it). "
            "An explicit value is rejected, never shortened."
        )
    derived = derive_amp_decay(resolved)
    if derived is None:
        return f"amp_decay_ms: {no_fit}"
    resolved["amp_decay_ms"] = derived
    return None


def _key(params: dict[str, Any]) -> str:
    # Canonical JSON of resolved parameters: equal dicts give equal keys. bool/int/float keep
    # their JSON types (1 and 1.0 differ, as they may in the render).
    return json.dumps(params, sort_keys=True, allow_nan=False)


def _render_fits(params: dict[str, Any]) -> bool:
    sr = int(params["sample_rate"])
    wav = encode_wav(render_resolved(params), sr, params["bit_depth"])
    return samples_fit(wav_samples(wav), sr)


@lru_cache(maxsize=4096)
def _fits_cached(key: str) -> bool:
    return _render_fits(json.loads(key))


@lru_cache(maxsize=256)
def _derive_cached(key: str) -> float | None:
    base = json.loads(key)

    def ok(k: int) -> bool:
        return _fits_cached(_key({**base, "amp_decay_ms": grid_value(k)}))

    if ok(GRID_STEPS):
        return grid_value(GRID_STEPS)
    if not ok(0):
        return None
    lo, hi = 0, GRID_STEPS
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if ok(mid):
            lo = mid
        else:
            hi = mid
    return grid_value(lo)
