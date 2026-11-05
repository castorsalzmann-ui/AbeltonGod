"""Preview playback logic (no Qt): 16-bit copy for the audio backend, state, playhead.

The actual sound output is a :class:`PlaybackBackend` supplied by the shell (QtMultimedia or
``winsound``); tests use a fake one. A backend that is missing or fails produces an error
message, never an exception.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from audio_engine.io import encode_wav

from .waveform import Waveform, WaveformError, load_waveform

IDLE, LOADED, PLAYING, ERROR = "idle", "loaded", "playing", "error"


class PlaybackBackend(Protocol):
    available: bool

    def play(self, wav_path: Path) -> None: ...
    def stop(self) -> None: ...


class NoBackend:
    available = False

    def play(self, wav_path: Path) -> None:
        raise RuntimeError("Keine Audioausgabe verfügbar.")

    def stop(self) -> None:
        pass


class PreviewController:
    def __init__(
        self, backend: PlaybackBackend | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.backend: PlaybackBackend = backend or NoBackend()
        self._clock = clock
        self._tmp = Path(tempfile.mkdtemp(prefix="abeltongod-preview-"))
        self.state = IDLE
        self.message = ""
        self.waveform: Waveform | None = None
        self.source: Path | None = None
        self._preview_path: Path | None = None
        self._started = 0.0

    def load(self, wav_path: str | Path) -> bool:
        """Load ``wav_path`` for display and playback. False (state ERROR) if unreadable."""
        self.stop()
        try:
            wf = load_waveform(wav_path)
        except WaveformError as exc:
            self.waveform, self.source, self._preview_path = None, None, None
            self.state, self.message = ERROR, str(exc)
            return False
        self.waveform, self.source = wf, Path(wav_path)
        # The backends play 16-bit PCM reliably; the engine writes 24-bit by default.
        out = self._tmp / "preview.wav"
        out.write_bytes(encode_wav(wf.samples, wf.sample_rate, 16))
        self._preview_path = out
        self.state, self.message = LOADED, ""
        return True

    def play(self) -> bool:
        if self.waveform is None or self._preview_path is None:
            self.message = "Keine Datei geladen."
            return False
        if not self.backend.available:
            self.state, self.message = ERROR, "Keine Audioausgabe verfügbar."
            return False
        try:
            self.backend.play(self._preview_path)
        except Exception as exc:  # noqa: BLE001
            self.state, self.message = ERROR, f"Wiedergabe fehlgeschlagen: {exc}"
            return False
        self._started = self._clock()
        self.state, self.message = PLAYING, ""
        return True

    def stop(self) -> None:
        if self.state == PLAYING:
            try:
                self.backend.stop()
            except Exception:  # noqa: BLE001
                pass
            self.state = LOADED

    def position(self) -> float:
        """Playhead in seconds; the end of the file once the sound is over."""
        if self.waveform is None:
            return 0.0
        if self.state != PLAYING:
            return 0.0
        return min(self._clock() - self._started, self.waveform.duration_s)

    def tick(self) -> None:
        """Called by the shell's timer: leaves PLAYING when the file has played out."""
        if self.state == PLAYING and self.waveform is not None:
            if self._clock() - self._started >= self.waveform.duration_s:
                self.state = LOADED

    def close(self) -> None:
        self.stop()
        shutil.rmtree(self._tmp, ignore_errors=True)
