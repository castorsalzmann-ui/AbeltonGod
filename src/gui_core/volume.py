"""One output volume for every preview (D-035 (3), #545). No Qt.

The volume scales only what is played: :class:`VolumeBackend` writes a scaled copy of the
16-bit WAV it is asked to play into its own temp folder and hands that copy to the real
backend (``winsound`` cannot set a level). The file asked for is never touched, so written
samples, banks and exports keep their bytes.

Gain = volume / 100 on the sample values (linear amplitude: 45 % is about -6.9 dB).
"""

from __future__ import annotations

import shutil
import struct
import tempfile
from collections.abc import Callable
from pathlib import Path

import numpy as np

from .preview import PlaybackBackend

DEFAULT_VOLUME = 45  # user, 2026-11-09: "Startlautstärke auf 45%"
MIN_VOLUME, MAX_VOLUME = 0, 100


def clamp_volume(v: object) -> int | None:
    """``v`` as a whole percent 0-100, or ``None`` if it is not one."""
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    if not MIN_VOLUME <= v <= MAX_VOLUME or v != v:  # NaN
        return None
    return int(round(v))


class OutputVolume:
    """The shared value. Every volume control and every :class:`VolumeBackend` of the process
    reads the same instance (:data:`OUTPUT`); listeners hear every change."""

    def __init__(self, value: int = DEFAULT_VOLUME) -> None:
        self._value = value
        self._listeners: list[Callable[[int], None]] = []

    @property
    def value(self) -> int:
        return self._value

    def set(self, value: int) -> None:
        v = clamp_volume(value)
        if v is None:
            raise ValueError(f"volume must be 0-100, got {value!r}")
        if v == self._value:
            return
        self._value = v
        for fn in list(self._listeners):
            fn(v)

    def subscribe(self, fn: Callable[[int], None]) -> None:
        self._listeners.append(fn)

    def unsubscribe(self, fn: Callable[[int], None]) -> None:
        self._listeners = [f for f in self._listeners if f != fn]


OUTPUT = OutputVolume()


def scale_wav16(data: bytes, volume: int) -> bytes:
    """``data`` (RIFF PCM 16-bit, any channel count) with every sample times
    ``volume / 100``; header and other chunks unchanged. Raises ``ValueError`` for anything
    else (every preview path plays 16-bit, #462)."""
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("keine WAV-Datei")
    pos, bits, out = 12, None, bytearray(data)
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        (size,) = struct.unpack("<I", data[pos + 4:pos + 8])
        body = pos + 8
        if cid == b"fmt ":
            tag, _ch, _sr, _br, _al, bits = struct.unpack("<HHIIHH", data[body:body + 16])
            if tag != 1 or bits != 16:
                raise ValueError(f"nur 16-Bit-PCM kann leiser gespielt werden (Format {tag}, "
                                 f"{bits} Bit)")
        elif cid == b"data":
            if bits is None:
                raise ValueError("WAV ohne fmt-Block vor den Daten")
            end = min(len(data), body + size)
            end -= (end - body) % 2  # whole samples only
            samples = np.frombuffer(data[body:end], dtype="<i2").astype(np.float64)
            scaled = np.clip(np.round(samples * (volume / 100.0)), -32768, 32767)
            out[body:end] = scaled.astype("<i2").tobytes()
            return bytes(out)
        pos = body + size + (size & 1)
    raise ValueError("WAV ohne Daten")


class VolumeBackend:
    """Wraps a backend: plays a copy of the file scaled to ``volume()`` percent.

    Copies alternate between two names (a file ``winsound`` still plays cannot be deleted on
    Windows, measured on the CI runner for #543)."""

    def __init__(self, inner: PlaybackBackend,
                 volume: Callable[[], int] = lambda: OUTPUT.value) -> None:
        self.inner = inner
        self.volume = volume
        self._tmp: Path | None = None
        self._n = 0

    @property
    def available(self) -> bool:  # type: ignore[override]
        return bool(self.inner.available)

    def _dir(self) -> Path:
        if self._tmp is None:
            self._tmp = Path(tempfile.mkdtemp(prefix="abeltongod-volume-"))
        return self._tmp

    def scaled_copy(self, wav_path: Path) -> Path:
        data = Path(wav_path).read_bytes()
        self._n += 1
        out = self._dir() / f"play_{self._n % 2}.wav"
        out.write_bytes(scale_wav16(data, self.volume()))
        return out

    def play(self, wav_path: Path) -> None:
        try:
            copy = self.scaled_copy(wav_path)
        except ValueError as exc:
            raise RuntimeError(f"Lautstärke nicht anwendbar: {exc}") from exc
        except OSError as exc:
            raise RuntimeError(f"Abspielkopie konnte nicht geschrieben werden: {exc}") from exc
        self.inner.play(copy)

    def stop(self) -> None:
        self.inner.stop()

    def close(self) -> None:
        if self._tmp is not None:
            shutil.rmtree(self._tmp, ignore_errors=True)
