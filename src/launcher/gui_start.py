"""Start the graphical interface from the launcher (``AbeltonGod.exe`` without arguments).

The GUI is optional (extra ``[gui]``); the exe bundles it. When PySide6 cannot be imported the
caller falls back to the text menu.
"""

from __future__ import annotations

import sys


def hide_own_console() -> bool:
    """Windows: a double-clicked console exe owns a black console window that would stay open
    behind the GUI. Hide it when this process is the only one attached to it (started from
    cmd or PowerShell there are two: the shell and us, then the console stays). Returns True
    when it was hidden. Not exercised in CI (no double-click there)."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        hwnd = kernel32.GetConsoleWindow()
        pids = (ctypes.c_uint * 4)()
        if not hwnd or kernel32.GetConsoleProcessList(pids, 4) != 1:
            return False
        ctypes.windll.user32.ShowWindow(hwnd, 0)  # type: ignore[attr-defined]
        return True
    except (AttributeError, OSError):
        return False


def gui_importable() -> bool:
    try:
        import PySide6.QtWidgets  # noqa: F401
    except ImportError:
        return False
    return True


def run_gui() -> int | None:
    """Open the main window and run until it is closed. None when PySide6 is missing."""
    if not gui_importable():
        return None
    from gui.app import main

    hide_own_console()
    return main([sys.argv[0]])


def run_selftest() -> int:
    if not gui_importable():
        sys.stdout.write("GUI selftest FAIL: PySide6 fehlt\n")
        return 1
    from gui.selftest import run

    return run(sys.stdout)
