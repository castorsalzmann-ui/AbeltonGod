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
        # The real factories: the Goa window (real Goa form) uses the shared in-memory settings
        # and no settings file of its own (#439, #440).
        win = MainWindow(out_dir=Path(tmp) / "out", window_factories=dict(DEFAULT_FACTORIES))
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
    """Kept for callers of the old name: the default Goa factory touches no settings file
    any more, so this is the real Goa window."""
    from .windows import DEFAULT_FACTORIES

    return DEFAULT_FACTORIES["goa"](out_dir)
