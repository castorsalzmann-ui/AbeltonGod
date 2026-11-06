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
        sr, bits = struct.unpack("<I", data[24:28])[0], struct.unpack("<H", data[34:36])[0]
        channels = struct.unpack("<H", data[22:24])[0]
        if channels == 2 and len(data) >= 44:  # laser: interleaved stereo, drawn as the mid
            ints = _stereo_mid(data, bits)
        else:
            ints = wav_samples(data)
    except (ValueError, struct.error) as exc:
        raise WaveformError(f"Keine WAV-Datei der Engine: {exc}") from exc
    if sr <= 0 or len(ints) == 0:
        raise WaveformError("Die WAV-Datei enthält keine Audiodaten.")
    return Waveform(ints / float(2 ** (bits - 1)), int(sr), int(bits))


def _stereo_mid(data: bytes, bits: int) -> np.ndarray:
    """Mean of left and right of an engine stereo WAV (44-byte header, PCM 16 or 24 bit)."""
    if data[:4] != b"RIFF" or data[36:40] != b"data" or bits not in (16, 24):
        raise ValueError("unsupported stereo WAV layout")
    (size,) = struct.unpack("<I", data[40:44])
    frames = data[44 : 44 + size]
    width = bits // 8
    if len(frames) != size or size % (2 * width):
        raise ValueError("WAV data chunk is truncated")
    if bits == 16:
        both = np.frombuffer(frames, dtype="<i2").astype(np.int64)
    else:
        raw = np.frombuffer(frames, dtype=np.uint8).reshape(-1, 3).astype(np.int64)
        value = raw[:, 0] | (raw[:, 1] << 8) | (raw[:, 2] << 16)
        both = np.where(value >= 1 << 23, value - (1 << 24), value)
    return (both[0::2] + both[1::2]) / 2.0


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
