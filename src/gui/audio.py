"""Sound output for the preview.

PySide6-Essentials has no QtMultimedia (it ships in PySide6-Addons, ~150 MB more), so the
preview uses the standard library's ``winsound`` on Windows. Other systems get ``NoBackend``:
the waveform is still shown and the play button reports that no output is available.

Measured on the Windows CI runner (PR for #543): asynchronous ``PlaySound`` returns without
an error even for a missing file or when no sound device exists, so a failure on that path is
silent by construction. ``play`` therefore asks Windows first whether any wave output device
exists (``waveOutGetNumDevs``) and reports it in German instead of staying silent.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from gui_core.preview import NoBackend, PlaybackBackend
from gui_core.volume import VolumeBackend

NO_DEVICE = ("Windows meldet kein Wiedergabegerät (waveOut). Lautsprecher oder Kopfhörer "
             "anschließen bzw. in den Windows-Soundeinstellungen ein Ausgabegerät aktivieren.")


def wave_output_devices() -> int | None:
    """Number of wave output devices Windows reports; ``None`` if it cannot be asked."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        return int(ctypes.windll.winmm.waveOutGetNumDevs())
    except (OSError, AttributeError):
        return None


class WinsoundBackend:
    available = sys.platform == "win32"

    def __init__(self, devices: Callable[[], int | None] = wave_output_devices) -> None:
        self._devices = devices

    def play(self, wav_path: Path) -> None:
        import winsound

        if self._devices() == 0:
            raise RuntimeError(NO_DEVICE)
        try:
            winsound.PlaySound(str(wav_path), play_flags(winsound))
        except RuntimeError as exc:
            raise RuntimeError(f"Windows konnte die Datei nicht abspielen ({exc}).") from exc

    def play_loop(self, wav_path: Path) -> None:
        """Repeat the file until :meth:`stop` (#553): SND_LOOP needs SND_ASYNC."""
        import winsound

        if self._devices() == 0:
            raise RuntimeError(NO_DEVICE)
        try:
            winsound.PlaySound(str(wav_path), play_flags(winsound) | winsound.SND_LOOP)
        except RuntimeError as exc:
            raise RuntimeError(f"Windows konnte die Datei nicht abspielen ({exc}).") from exc

    def stop(self) -> None:
        import winsound

        # A NULL sound stops async playback; SND_PURGE is "not supported" (Microsoft, Python
        # docs; #462).
        winsound.PlaySound(None, 0)


def play_flags(ws) -> int:
    """Flags for playing a file: asynchronous, and silent if the file is missing (without
    SND_NODEFAULT Windows plays its default system sound instead; #462)."""
    return ws.SND_FILENAME | ws.SND_ASYNC | ws.SND_NODEFAULT


def choose_backend() -> PlaybackBackend:
    """The app's backend: on Windows ``winsound`` behind the shared output volume (#545)."""
    if sys.platform != "win32":
        return NoBackend()
    return VolumeBackend(WinsoundBackend())
