"""Headless start check of the GUI (``AbeltonGod.exe --gui-selftest``, used by the exe smoke test).

Builds the main window, visits every page, opens each of the other windows once, closes
everything and returns 0. With the offscreen platform nothing is shown on a screen. It does not
render sound, does not use the user's settings file and writes only into a temporary folder.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def run(out=None) -> int:
    out = out or sys.stdout
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from .app import create_app
        from .main_window import MainWindow
        from .windows import DEFAULT_FACTORIES, WINDOW_KEYS
    except ImportError as exc:
        out.write(f"GUI selftest FAIL: PySide6 fehlt ({exc})\n")
        return 1

    app = create_app([])
    with tempfile.TemporaryDirectory(prefix="abeltongod-selftest-") as tmp:
        factories = dict(DEFAULT_FACTORIES)
        factories["goa"] = _goa_without_settings_file
        win = MainWindow(out_dir=Path(tmp) / "out", window_factories=factories)
        win.show()
        pages = win.stack.count()
        for row in range(pages):
            win.categories.setCurrentRow(row)
            app.processEvents()
        opened = []
        for key, _ in WINDOW_KEYS:
            opened.append(win.windows.open(key) is not None)
            app.processEvents()
        ok = all(opened)
        reason = win.windows.last_error
        blaster = win.windows.window("blaster")
        if ok and getattr(getattr(blaster, "session", None), "engine", None) is None:
            ok, reason = False, "Blaster ohne Laser-Engine (nicht im Paket?)"
        win.close()
        app.processEvents()
    if not ok:
        out.write(f"GUI selftest FAIL: window did not open {opened} {reason}\n")
        return 1
    out.write(f"GUI selftest ok: main window with {pages} pages, {len(opened)} windows opened "
              f"and closed (platform {os.environ.get('QT_QPA_PLATFORM')})\n")
    return 0


def _goa_without_settings_file(out_dir: Path):
    from .skin.settings import SkinSettings
    from .skin.window import CompactGoaWindow

    return CompactGoaWindow(settings=SkinSettings())
