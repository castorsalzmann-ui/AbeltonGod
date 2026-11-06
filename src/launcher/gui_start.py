"""Start the graphical interface from the launcher (``AbeltonGod.exe`` without arguments).

The GUI is optional (extra ``[gui]``); the exe bundles it. When PySide6 cannot be imported the
caller falls back to the text menu. A start failure is logged and shown, never silent (#436).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from typing import TextIO

from .startup_log import format_error, log_path, write_error


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


def show_own_console() -> None:
    """Undo :func:`hide_own_console` (Windows only), so a late error text can be read."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()  # type: ignore[attr-defined]
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 5)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass


def gui_importable() -> bool:
    try:
        import PySide6.QtWidgets  # noqa: F401
    except ImportError:
        return False
    return True


EXIT_GUI_FAILED = 4
# Test hook (exe smoke, #436): set to a stage name to make the start fail right there.
FAIL_ENV = "ABELTONGOD_TEST_START_FAILURE"
STAGES = ("import", "qt", "window")
# Platforms without a screen: a modal message box would wait forever for a click.
HEADLESS = ("offscreen", "minimal")


def _qt_message_box(text: str) -> bool:
    """Show ``text`` in a modal error box. False when there is no screen to show it on."""
    if os.environ.get("QT_QPA_PLATFORM", "").lower() in HEADLESS:
        return False
    from PySide6.QtWidgets import QMessageBox

    QMessageBox.critical(None, "AbeltonGod - Startfehler", text)
    return True


def _check_fail(stage: str) -> None:
    if os.environ.get(FAIL_ENV) == stage:
        raise RuntimeError(f"{FAIL_ENV}={stage} (test hook)")


def run_gui(*, out: TextIO | None = None, read: Callable[[str], str] = input,
            hide: Callable[[], bool] = hide_own_console,
            message_box: Callable[[str], bool] = _qt_message_box,
            main: Callable[[list[str]], int] | None = None) -> int | None:
    """Open the main window and run until it is closed. None when PySide6 is missing.

    The console is hidden only once the event loop runs, i.e. after the main window was built
    and shown; a failure before that leaves the console visible. Any failure is appended to
    :func:`startup_log.log_path` and reported (message box if Qt is up and a screen exists,
    else on the console, which then waits for Enter). Returns ``EXIT_GUI_FAILED`` then."""
    if not gui_importable():
        return None
    out = out or sys.stderr
    stage, qt_up = "import", False
    state = {"hidden": False, "failed": False}
    previous_hook = sys.excepthook

    def log_hook(kind, exc, tb):  # errors inside Qt slots after the console was hidden
        if isinstance(exc, Exception):
            write_error(format_error(exc.with_traceback(tb), "running"))
        previous_hook(kind, exc, tb)

    try:
        _check_fail("import")
        from gui.app import create_app
        from gui.app import main as gui_main

        stage = "qt"
        argv = [sys.argv[0]]
        create_app(argv)  # gui.app.main reuses this instance
        qt_up = True
        _check_fail("qt")
        from PySide6.QtCore import QTimer

        def hide_now() -> None:
            # not inside the error box's own event loop after a failed start
            if not state["failed"]:
                state["hidden"] = hide()

        QTimer.singleShot(0, hide_now)  # fires only inside exec(), after window.show()
        stage = "window"
        _check_fail("window")
        sys.excepthook = log_hook
        return (main or gui_main)(argv)
    except Exception as exc:  # noqa: BLE001 - every start failure must be reported
        state["failed"] = True
        return _report(exc, stage, qt_up, state["hidden"], out, read, message_box)
    finally:
        sys.excepthook = previous_hook


def _report(exc: Exception, stage: str, qt_up: bool, hidden: bool, out: TextIO,
            read: Callable[[str], str], message_box: Callable[[str], bool]) -> int:
    text = format_error(exc, stage)
    path = write_error(text)
    where = (f"Details stehen in:\n{path}" if path else
             f"Die Logdatei konnte nicht geschrieben werden ({log_path()}).")
    msg = (f"AbeltonGod konnte die Oberflaeche nicht starten.\n\n{type(exc).__name__}: {exc}"
           f"\n\n{where}\n\nDas Textmenue startet mit: AbeltonGod.exe --menu")
    try:
        out.write(text + msg + "\n")
        out.flush()
    except (OSError, ValueError):
        pass
    shown = False
    if qt_up:
        try:
            shown = message_box(msg)
        except Exception:  # noqa: BLE001 - the box itself failed: fall back to the console
            shown = False
    if not shown:
        if hidden:
            show_own_console()
        try:
            read("Enter zum Beenden ...")
        except (EOFError, KeyboardInterrupt, OSError, RuntimeError):
            pass
    return EXIT_GUI_FAILED


def run_selftest() -> int:
    if not gui_importable():
        sys.stdout.write("GUI selftest FAIL: PySide6 fehlt\n")
        return 1
    from gui.selftest import run

    return run(sys.stdout)
