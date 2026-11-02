"""Measured features of a rendered sample (direct measurement, no classification).

``fundamental_hz`` is the frequency of the *tail*: mean rate of positive-going zero crossings
in the measurement window returned by :func:`tail_window` — the 100 ms that end where the
envelope first falls 40 dB below its peak, but never earlier than 20 ms (so a click transient
is excluded). It is ``None`` when the window holds fewer than three crossings, i.e. the tail is
too short to measure. For a kick whose pitch has settled, the value is close to
``pitch_end_hz``; if the pitch is still falling in the window, it is higher — a property of
the sound, not a measurement error.

Known limitation of ``fundamental_hz`` on very short kicks (#27). When ``amp_decay_ms`` is
below about 110 ms, the body decays faster (tau = amp_decay_ms / ln 1000) than the tail of the
kick engine's 10 Hz DC blocker (tau = 15.9 ms). That slow tail, and on some kicks the
Hann-shaped mean correction, then moves the zero crossings or stops them altogether. With
both stages switched off the crossings follow the body exactly. Measured on body-only kicks:
single cycles off by up to 13 % at -20 to -30 dB, ``fundamental_hz`` off by up to 4.8 %, and
often ``None`` below about 60 ms. Read it as approximate (+-5 %), or ``None``, for very short
kicks. The analysis is correct for the file; the file differs from the body pitch.

``decay_20db_ms`` / ``decay_40db_ms`` are measured on the output and are not the inverse of
``amp_decay_ms`` (#32). Each envelope frame is the max |x| over 40 ms, stamped at the frame
start. After the peak that max is a crest from later in the frame, so the time can be early
by up to about half a pitch period. The threshold is relative to the signal peak, which lies
0 to 2.5 dB below the envelope peak, so the time can be up to ``deficit_db / 60 *
amp_decay_ms`` late (measured up to 5.1 ms). Clean kicks: -14 to +4.4 ms (-8 to +25 %) from
``amp_attack_ms + amp_decay_ms / 3``. With drive the output really decays more slowly:
median +40 %, up to +87 %, or ``None`` when the level does not fall 20 dB inside the file.
Never derive ``amp_decay_ms`` as ``3 * decay_20db_ms``; to change the decay, set
``amp_decay_ms``.
"""

from __future__ import annotations

import math

import numpy as np

ENV_WINDOW_MS = 40.0  # longer than one period at 30 Hz (33.3 ms), so the envelope does not ripple
ENV_HOP_MS = 1.0
ENV_MIN_FRAME_MS = 20.0  # shortest frame at the file end; > half a period at 30 Hz (16.7 ms)
TAIL_WINDOW_MS = 100.0
TAIL_EARLIEST_MS = 20.0  # after any click transient (15 ms in the kick engine)
# The window never reaches into the last TAIL_END_MARGIN_MS of the file: the kick engine's
# fade-out (5 ms) plus DC blocker can add a spurious zero crossing there (review 3, R1: -9.8 %
# on a cut-off kick). Must stay >= audio_engine.kick.FADE_OUT_MS (checked by a test).
TAIL_END_MARGIN_MS = 6.0


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
    last_usable = len(audio) - int(round(TAIL_END_MARGIN_MS * sr / 1000.0))
    end = max(0, min(last_usable, int(round(end_ms * sr / 1000.0))))
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
    # Frames run up to the file end, shortened there, but never shorter than ENV_MIN_FRAME_MS
    # (> half a period at 30 Hz, so every frame still contains a peak). Before review 4 the
    # frames stopped 40 ms before the end, so short kicks never "saw" their -40 dB point.
    min_len = min(len(audio), max(1, int(round(ENV_MIN_FRAME_MS * sr / 1000.0))))
    starts = np.arange(0, len(audio) - min_len + 1, hop)
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


# ---------------------------------------------------------------------------------------------
# Non-pitched features (#230; contract fields of sample-metadata v0.2). ``analyse`` above is
# unchanged, so kick sidecars keep their bytes.
# ---------------------------------------------------------------------------------------------

HF_SPLIT_HZ = 8000.0
ENV_RMS_MS = 1.0  # moving RMS window of the fine envelope used for T60 and rise time
# Frames whose window touches the last FADE_GUARD_MS of the file are ignored when looking for
# the -60 dB point: the engines' 5 ms fade-out would otherwise fake a decay (cut-off sounds
# must give None). Must stay >= the kick/clap FADE_OUT_MS (5 ms).
FADE_GUARD_MS = 6.0
RISE_LOW, RISE_HIGH = 0.1, 0.9  # fractions of the peak envelope (linear amplitude)


def analyse_nonpitched(audio: np.ndarray, sr: int) -> dict[str, float | None]:
    """peak_dbfs, length_ms and the four non-pitched features of sample-metadata v0.2.

    All spectral values use the whole file with no window (a window would down-weight the
    attack of a short sound). Silence gives ``None`` for every feature but ``length_ms``.
    """
    if audio.ndim != 1:
        raise ValueError("analyse_nonpitched() expects mono audio (1-D array).")
    n = len(audio)
    peak = float(np.max(np.abs(audio))) if n else 0.0
    out: dict[str, float | None] = {
        "peak_dbfs": round(_db(peak), 3) if peak > 0 else None,
        "length_ms": round(n / sr * 1000.0, 3),
        "spectral_centroid_hz": None,
        "hf_share_8k": None,
        "t60_ms": None,
        "rise_time_ms": None,
    }
    if peak == 0.0:
        return out
    power = _power_spectrum(audio)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    total = float(np.sum(power))
    out["spectral_centroid_hz"] = round(float(np.sum(freqs * power) / total), 2)
    out["hf_share_8k"] = round(float(np.sum(power[freqs > HF_SPLIT_HZ]) / total), 6)
    env = rms_envelope(audio, sr)
    out["t60_ms"] = t60_ms(env, sr)
    out["rise_time_ms"] = rise_time_ms(env, sr)
    return out


def spectral_flatness(audio: np.ndarray) -> float | None:
    """Geometric over arithmetic mean of the power spectrum (0 ... 1), whole file, DC excluded.

    1.0 for a flat spectrum (an impulse), near 0 for a pure tone. White noise gives about
    exp(-gamma) = 0.56 (periodogram bins are exponentially distributed). Not part of the
    sidecar contract (the ``features`` object does not list it); available for tests and
    voice design. ``None`` for silence or fewer than 3 samples.
    """
    if len(audio) < 3 or not np.any(audio):
        return None
    power = _power_spectrum(audio)[1:]
    power = np.maximum(power, 1e-300)
    return float(np.exp(np.mean(np.log(power))) / np.mean(power))


def rms_envelope(audio: np.ndarray, sr: int) -> np.ndarray:
    """Moving RMS (centred, ``ENV_RMS_MS`` window, zero-padded), one value per sample."""
    win = max(1, int(round(ENV_RMS_MS * sr / 1000.0)))
    kernel = np.full(win, 1.0 / win)
    return np.sqrt(np.maximum(np.convolve(audio**2, kernel, mode="same"), 0.0))


def t60_ms(env: np.ndarray, sr: int) -> float | None:
    """Time from the envelope peak until it first is 60 dB lower; ``None`` if that does not
    happen before the last ``FADE_GUARD_MS`` of the file."""
    if len(env) == 0 or float(np.max(env)) <= 0.0:
        return None
    peak_idx = int(np.argmax(env))
    limit = len(env) - int(round(FADE_GUARD_MS * sr / 1000.0))
    threshold = float(env[peak_idx]) * 1e-3  # -60 dB
    below = np.nonzero(env[peak_idx:max(peak_idx, limit)] <= threshold)[0]
    if len(below) == 0:
        return None
    return round(float(below[0]) / sr * 1000.0, 3)


def rise_time_ms(env: np.ndarray, sr: int) -> float | None:
    """First time the envelope reaches 10 % of its peak to first time it reaches 90 %, ms."""
    if len(env) == 0 or float(np.max(env)) <= 0.0:
        return None
    peak = float(np.max(env))
    lo = int(np.argmax(env >= RISE_LOW * peak))
    hi = int(np.argmax(env >= RISE_HIGH * peak))
    return round((hi - lo) / sr * 1000.0, 3)


def _power_spectrum(audio: np.ndarray) -> np.ndarray:
    return np.abs(np.fft.rfft(audio)) ** 2
