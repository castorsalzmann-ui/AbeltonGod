"""The other windows of the program (Goa skin, Acid, Blaster), opened from the main window.

One instance per key: a second click raises the open window instead of making another. A window
that was closed is replaced by a fresh one on the next click (the windows clean up in their own
``closeEvent``, so a closed one is not reused). Closing a window never ends the program; closing
the main window closes them all. Window classes are imported on first use, so the main window
starts without loading all skins.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QWidget

WINDOW_KEYS = (("goa", "Goa-Fenster"), ("acid", "Acid-Linie"), ("blaster", "Laser-Blaster"))


def _goa(out_dir: Path) -> QWidget:
    from .skin.window import CompactGoaWindow

    return CompactGoaWindow(use_default_path=True)


def _acid(out_dir: Path) -> QWidget:
    from .acid.window import AcidWindow

    return AcidWindow(out_dir=out_dir)


def _blaster(out_dir: Path) -> QWidget:
    from .blaster.window import BlasterWindow

    return BlasterWindow(out_dir=out_dir)


DEFAULT_FACTORIES: dict[str, Callable[[Path], QWidget]] = {
    "goa": _goa, "acid": _acid, "blaster": _blaster,
}


def _alive(widget: QWidget | None) -> bool:
    if widget is None:
        return False
    try:
        import shiboken6

        return shiboken6.isValid(widget)
    except ImportError:  # pragma: no cover - shiboken ships with PySide6
        return True


class WindowManager(QObject):
    def __init__(self, out_dir: Callable[[], Path],
                 factories: dict[str, Callable[[Path], QWidget]] | None = None) -> None:
        super().__init__()
        self._out_dir = out_dir
        self._factories = dict(DEFAULT_FACTORIES if factories is None else factories)
        self._open: dict[str, QWidget] = {}
        self.last_error = ""

    def is_open(self, key: str) -> bool:
        w = self._open.get(key)
        return _alive(w) and w.isVisible()  # type: ignore[union-attr]

    def window(self, key: str) -> QWidget | None:
        return self._open.get(key) if self.is_open(key) else None

    def open(self, key: str) -> QWidget | None:
        """Show the window ``key`` (new, or the open one raised). None when it cannot be made;
        the reason is in ``last_error`` (German)."""
        if key not in self._factories:
            raise KeyError(key)
        existing = self.window(key)
        if existing is not None:
            existing.raise_()
            existing.activateWindow()
            return existing
        old = self._open.pop(key, None)
        if _alive(old):
            old.deleteLater()  # type: ignore[union-attr]
        try:
            win = self._factories[key](self._out_dir())
        except Exception as exc:  # noqa: BLE001 - a missing part must not close the program
            self.last_error = (
                f"Das Fenster konnte nicht geöffnet werden: {type(exc).__name__}: {exc}")
            return None
        self.last_error = ""
        self._open[key] = win
        win.show()
        return win

    def close_all(self) -> None:
        for key in list(self._open):
            w = self._open.pop(key)
            if _alive(w):
                w.close()
                w.deleteLater()
