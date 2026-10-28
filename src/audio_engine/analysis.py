"""Measured features of a rendered sample (direct measurement, no classification).

``fundamental_hz`` is the frequency of the *tail*: mean rate of positive-going zero crossings
in the measurement window returned by :func:`tail_window` — the 100 ms that end where the
envelope first falls 40 dB below its peak, but never earlier than 20 ms (so a click transient
is excluded). It is ``None`` when the window holds fewer than three crossings, i.e. the tail is
too short to measure. For a kick whose pitch has settled, the value is close to
``pitch_end_hz``; if the pitch is still falling in the window, it is higher — a property of
the sound, not a measurement error.
"""

from __future__ import annotations

import math

import numpy as np

ENV_WINDOW_MS = 40.0  # longer than one period at 30 Hz (33.3 ms), so the envelope does not ripple
ENV_HOP_MS = 1.0
TAIL_WINDOW_MS = 100.0
TAIL_EARLIEST_MS = 20.0  # after any click transient (15 ms in the kick engine)


def analyse(audio: np.ndarray, sr: int) -> dict[str, float | None]:
    if audio.ndim != 1:
        raise ValueError("analyse() expects mono audio (1-D array).")
    n = len(audio)
    peak = float(np.max(np.abs(audio))) if n else 0.0
    times_ms, env_db = _envelope_db(audio, sr)
    start, end = tail_window(audio, sr)
    return {
        "peak_dbfs": round(_db(peak), 3) if peak > 0 else None,
        "length_ms": round(n / sr * 1000.0, 3),
        "fundamental_hz": zero_crossing_frequency(audio[start:end], sr),
        "decay_20db_ms": _decay_time(times_ms, env_db, 20.0),
        "decay_40db_ms": _decay_time(times_ms, env_db, 40.0),
        "dc_offset": round(float(np.mean(audio)), 6) if n else None,
    }


def tail_window(audio: np.ndarray, sr: int) -> tuple[int, int]:
    """Sample range ``[start, end)`` used for ``fundamental_hz``."""
    times_ms, env_db = _envelope_db(audio, sr)
    end_ms = _decay_time(times_ms, env_db, 40.0)
    if end_ms is None:
        end_ms = len(audio) / sr * 1000.0
    end = min(len(audio), int(round(end_ms * sr / 1000.0)))
    earliest = int(round(TAIL_EARLIEST_MS * sr / 1000.0))
    start = max(earliest, end - int(round(TAIL_WINDOW_MS * sr / 1000.0)))
    return min(start, end), end


def zero_crossing_frequency(segment: np.ndarray, sr: int) -> float | None:
    """Mean frequency from positive-going zero crossings (linear interpolation); None if < 3.

    Exact zeros at the segment edges (e.g. the last sample of a faded-out file) are trimmed
    first; otherwise a negative sample followed by a final 0.0 would count as a crossing.
    """
    nonzero = np.nonzero(segment)[0]
    if len(nonzero) < 2:
        return None
    segment = segment[nonzero[0] : nonzero[-1] + 1]
    idx = np.nonzero((segment[:-1] < 0) & (segment[1:] >= 0))[0]
    if len(idx) < 3:
        return None
    frac = segment[idx] / (segment[idx] - segment[idx + 1])
    period = float(np.mean(np.diff(idx + frac)))
    return round(sr / period, 2)


def _db(value: float) -> float:
    return 20.0 * math.log10(value)


def _envelope_db(audio: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    if len(audio) == 0:
        return np.zeros(1), np.full(1, -240.0)
    win = max(1, int(round(ENV_WINDOW_MS * sr / 1000.0)))
    hop = max(1, int(round(ENV_HOP_MS * sr / 1000.0)))
    starts = np.arange(0, max(1, len(audio) - win + 1), hop)
    mags = np.array([np.max(np.abs(audio[s : s + win])) for s in starts])
    env_db = 20.0 * np.log10(np.maximum(mags, 1e-12))
    return starts / sr * 1000.0, env_db


def _decay_time(times_ms: np.ndarray, env_db: np.ndarray, drop_db: float) -> float | None:
    """Time (ms, from sample 0) at which the envelope first falls ``drop_db`` below its peak."""
    peak_idx = int(np.argmax(env_db))
    below = np.nonzero(env_db[peak_idx:] <= env_db[peak_idx] - drop_db)[0]
    if len(below) == 0:
        return None
    return round(float(times_ms[peak_idx + below[0]]), 3)
