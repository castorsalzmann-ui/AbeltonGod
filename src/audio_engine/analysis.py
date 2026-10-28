"""Measured features of a rendered sample (direct measurement, no classification).

``fundamental_hz`` is the frequency of the *tail*: zero-crossing rate in the 100 ms window that
ends where the envelope first falls 40 dB below its peak. For a kick whose pitch envelope has
settled by then, this is close to ``pitch_end_hz``. If the pitch is still falling in that window,
the value is higher than ``pitch_end_hz`` — that is a property of the sound, not a bug.
"""

from __future__ import annotations

import math

import numpy as np

ENV_WINDOW_MS = 25.0  # longer than one period at 40 Hz, so the envelope does not ripple
ENV_HOP_MS = 1.0
TAIL_WINDOW_MS = 100.0


def analyse(audio: np.ndarray, sr: int) -> dict[str, float | None]:
    if audio.ndim != 1:
        raise ValueError("analyse() expects mono audio (1-D array).")
    n = len(audio)
    peak = float(np.max(np.abs(audio))) if n else 0.0
    times_ms, env_db = _envelope_db(audio, sr)
    return {
        "peak_dbfs": round(_db(peak), 3),
        "length_ms": round(n / sr * 1000.0, 3),
        "fundamental_hz": _tail_fundamental(audio, sr, times_ms, env_db),
        "decay_20db_ms": _decay_time(times_ms, env_db, 20.0),
        "decay_40db_ms": _decay_time(times_ms, env_db, 40.0),
        "dc_offset": round(float(np.mean(audio)), 6) if n else None,
    }


def _db(value: float) -> float:
    return 20.0 * math.log10(value) if value > 0 else -math.inf


def _envelope_db(audio: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    win = max(1, int(round(ENV_WINDOW_MS * sr / 1000.0)))
    hop = max(1, int(round(ENV_HOP_MS * sr / 1000.0)))
    starts = np.arange(0, max(1, len(audio) - win + 1), hop)
    if len(audio) == 0:
        return np.zeros(1), np.full(1, -240.0)
    mags = np.array([np.max(np.abs(audio[s : s + win])) for s in starts])
    with np.errstate(divide="ignore"):
        env_db = 20.0 * np.log10(np.maximum(mags, 1e-12))
    times_ms = starts / sr * 1000.0
    return times_ms, env_db


def _decay_time(times_ms: np.ndarray, env_db: np.ndarray, drop_db: float) -> float | None:
    """Time (ms, from sample 0) at which the envelope first falls ``drop_db`` below its peak."""
    peak_idx = int(np.argmax(env_db))
    below = np.nonzero(env_db[peak_idx:] <= env_db[peak_idx] - drop_db)[0]
    if len(below) == 0:
        return None
    return round(float(times_ms[peak_idx + below[0]]), 3)


def _tail_fundamental(
    audio: np.ndarray, sr: int, times_ms: np.ndarray, env_db: np.ndarray
) -> float | None:
    end_ms = _decay_time(times_ms, env_db, 40.0)
    if end_ms is None:
        end_ms = len(audio) / sr * 1000.0
    end = int(round(end_ms * sr / 1000.0))
    start = max(0, end - int(round(TAIL_WINDOW_MS * sr / 1000.0)))
    seg = audio[start:end]
    # Positive-going zero crossings with linear interpolation.
    idx = np.nonzero((seg[:-1] < 0) & (seg[1:] >= 0))[0]
    if len(idx) < 3:
        return None
    frac = seg[idx] / (seg[idx] - seg[idx + 1])
    crossings = idx + frac
    period = float(np.mean(np.diff(crossings)))
    return round(sr / period, 2)
