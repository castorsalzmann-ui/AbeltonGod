"""Read a WAV written by the engine and reduce it to min/max pairs for drawing (no Qt)."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from audio_engine.io import wav_samples


class WaveformError(ValueError):
    """The file is missing, unreadable or not an engine WAV."""


@dataclass(frozen=True)
class Waveform:
    samples: np.ndarray  # float64, full scale = 1.0
    sample_rate: int
    bit_depth: int

    @property
    def duration_s(self) -> float:
        return len(self.samples) / self.sample_rate


def load_waveform(path: str | Path) -> Waveform:
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise WaveformError(f"Datei nicht lesbar: {exc}") from exc
    try:
        ints = wav_samples(data)
        sr, bits = struct.unpack("<I", data[24:28])[0], struct.unpack("<H", data[34:36])[0]
    except (ValueError, struct.error) as exc:
        raise WaveformError(f"Keine WAV-Datei der Engine: {exc}") from exc
    if sr <= 0 or len(ints) == 0:
        raise WaveformError("Die WAV-Datei enthält keine Audiodaten.")
    return Waveform(ints / float(2 ** (bits - 1)), int(sr), int(bits))


def peaks(samples: np.ndarray, buckets: int) -> list[tuple[float, float]]:
    """``buckets`` (min, max) pairs covering all samples, in order.

    Bucket ``k`` holds samples ``[k*n//buckets, (k+1)*n//buckets)``; with fewer samples than
    buckets the trailing buckets repeat the last sample so the list always has ``buckets``
    entries.
    """
    if buckets <= 0:
        raise ValueError("buckets must be positive")
    n = len(samples)
    if n == 0:
        return [(0.0, 0.0)] * buckets
    out: list[tuple[float, float]] = []
    for k in range(buckets):
        lo, hi = k * n // buckets, (k + 1) * n // buckets
        if hi <= lo:
            lo = min(lo, n - 1)
            hi = lo + 1
        chunk = samples[lo:hi]
        out.append((float(chunk.min()), float(chunk.max())))
    return out
