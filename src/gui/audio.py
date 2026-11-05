"""Sound output for the preview.

PySide6-Essentials has no QtMultimedia (it ships in PySide6-Addons, ~150 MB more), so the
preview uses the standard library's ``winsound`` on Windows. Other systems get ``NoBackend``:
the waveform is still shown and the play button reports that no output is available.
Not exercised in CI (no sound device): only the choice of backend is tested.
"""

from __future__ import annotations

import sys
from pathlib import Path

from gui_core.preview import NoBackend, PlaybackBackend


class WinsoundBackend:
    available = sys.platform == "win32"

    def play(self, wav_path: Path) -> None:
        import winsound

        winsound.PlaySound(str(wav_path), winsound.SND_FILENAME | winsound.SND_ASYNC)

    def stop(self) -> None:
        import winsound

        winsound.PlaySound(None, winsound.SND_PURGE)


def choose_backend() -> PlaybackBackend:
    return WinsoundBackend() if sys.platform == "win32" else NoBackend()
