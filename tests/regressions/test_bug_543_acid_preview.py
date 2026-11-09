"""#543 (user, Windows exe): "Im Acid kann ich den Sound nicht abspielen".

The cause on the user's PC is not established (no log, no repro steps). What was found:

1. The play button sat in the file row at the bottom of the Acid window; in a half-screen
   window (640 x 680 logical px, Live next to it) it was below the fold.
2. ``AcidWindow.preview`` caught only some exception types; anything else vanished in the Qt
   slot (the windowed exe has no console), i.e. the click did nothing visible.
3. Measured on the Windows CI runner: asynchronous ``PlaySound`` reports no error even for a
   missing file or without any sound device, so a dead output was silent too.

Each case below is red on the code before the fix (see the PR) and green after.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

if os.environ.get("ABELTONGOD_REQUIRE_GUI") == "1":
    import PySide6.QtWidgets  # noqa: F401
else:
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.app import create_app  # noqa: E402

HALF_SCREEN = (640, 680)  # 1920 x 1080 at 150 % = 1280 x 720 logical; half of it, taskbar off


class FakeBackend:
    available = True

    def __init__(self, fail: Exception | None = None) -> None:
        self.played: list[Path] = []
        self.fail = fail

    def play(self, wav_path: Path) -> None:
        if self.fail is not None:
            raise self.fail
        self.played.append(Path(wav_path))

    def stop(self) -> None:
        pass


@pytest.fixture(scope="module")
def qapp():
    return create_app([])


def _window(tmp_path, backend):
    from gui.acid.window import AcidWindow

    w = AcidWindow(out_dir=tmp_path / "out", backend=backend)
    w.resize(*HALF_SCREEN)
    w.show()
    QApplication.processEvents()
    return w


def _is_error(w) -> bool:
    return w.status.property("level") == "error"


def test_play_and_stop_are_visible_without_scrolling_in_a_half_screen_window(qapp, tmp_path):
    w = _window(tmp_path, FakeBackend())
    try:
        assert w.width() <= HALF_SCREEN[0] and w.height() <= HALF_SCREEN[1]
        for b in (w.preview_button, w.stop_button):
            region = b.visibleRegion()
            # the whole button is on screen, not a sliver of it
            assert region.boundingRect().size() == b.size(), b.text()
    finally:
        w.close()


@pytest.mark.parametrize("size", [HALF_SCREEN, (1280, 720)])
@pytest.mark.parametrize("fail", [None, OSError("Gerät belegt")])
def test_the_play_result_is_visible_without_scrolling(qapp, tmp_path, size, fail):
    """Review of #561: the footer status sat below the fold too (0 x 0 visible)."""
    w = _window(tmp_path, FakeBackend(fail=fail))
    try:
        w.resize(*size)
        QApplication.processEvents()
        w.preview_button.click()
        QApplication.processEvents()
        label = w.preview_status
        want = "Wiedergabe fehlgeschlagen: Gerät belegt" if fail else "Spielt:"
        assert want in label.text()
        assert ("Kein Ton?" in label.text()) == (fail is None)
        assert (label.property("level") == "error") == (fail is not None)
        visible = label.visibleRegion().boundingRect()
        assert visible.size() == label.size() and visible.height() > 0, (size, visible)
    finally:
        w.close()


def test_an_unexpected_render_error_is_shown_in_german_not_swallowed(qapp, tmp_path,
                                                                     monkeypatch):
    import gui.acid.window as acid_window

    def boom(*_a, **_k):
        raise KeyError("steps")

    monkeypatch.setattr(acid_window, "preview_wav_bytes", boom)
    backend = FakeBackend()
    w = _window(tmp_path, backend)
    try:
        w.status.setText("")
        w.preview_button.click()
        QApplication.processEvents()
        assert _is_error(w)
        assert w.status.text().startswith("Vorschau konnte nicht berechnet werden")
        assert backend.played == []
    finally:
        w.close()


def test_a_backend_failure_of_any_type_is_shown(qapp, tmp_path):
    w = _window(tmp_path, FakeBackend(fail=OSError("Gerät belegt")))
    try:
        w.preview_button.click()
        QApplication.processEvents()
        assert _is_error(w) and "Wiedergabe fehlgeschlagen" in w.status.text()
        assert "Gerät belegt" in w.status.text()
    finally:
        w.close()


def test_winsound_backend_reports_a_missing_output_device_in_german(monkeypatch):
    import types

    from gui import audio

    calls = []
    fake = types.SimpleNamespace(SND_FILENAME=0x20000, SND_ASYNC=0x1, SND_NODEFAULT=0x2,
                                 PlaySound=lambda sound, flags: calls.append(sound))
    monkeypatch.setitem(sys.modules, "winsound", fake)
    with pytest.raises(RuntimeError, match="kein Wiedergabegerät"):
        audio.WinsoundBackend(devices=lambda: 0).play(Path("x.wav"))
    assert calls == []  # nothing handed to the silent async path
    audio.WinsoundBackend(devices=lambda: 2).play(Path("x.wav"))
    audio.WinsoundBackend(devices=lambda: None).play(Path("x.wav"))  # unknown: try anyway
    assert calls == ["x.wav", "x.wav"]


@pytest.mark.skipif(sys.platform != "win32", reason="real winmm only on Windows")
def test_windows_device_count_is_asked_from_winmm():
    from gui import audio

    n = audio.wave_output_devices()
    assert isinstance(n, int) and n >= 0
