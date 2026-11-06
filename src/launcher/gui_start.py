"""Start the graphical interface from the launcher (``AbeltonGod.exe`` without arguments).

The GUI is optional (extra ``[gui]``); the exe bundles it. When PySide6 cannot be imported the
caller falls back to the text menu. A start failure is logged and shown, never silent (#436).

The GUI exe is a windowed build (#445): there is no console to hide, so no console tricks.
Where a message goes when the start fails:

1. a Qt message box, when Qt is already up and there is a screen;
2. else a native Windows message box, when the process has no console (windowed exe);
3. else the console (``python -m launcher`` from a shell, or the CLI exe), which waits for
   Enter when it is interactive.

Every failure is also appended to :func:`startup_log.log_path`.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from typing import TextIO

from .startup_log import format_error, log_path, write_error

EXIT_GUI_FAILED = 4
# Test hook (exe smoke, #436): set to a stage name to make the start fail right there.
FAIL_ENV = "ABELTONGOD_TEST_START_FAILURE"
STAGES = ("import", "qt", "window")
# Platforms without a screen: a modal message box would wait forever for a click.
HEADLESS = ("offscreen", "minimal")
TITLE = "AbeltonGod - Startfehler"


def gui_importable() -> bool:
    try:
        import PySide6.QtWidgets  # noqa: F401
    except ImportError:
        return False
    return True


def headless() -> bool:
    return os.environ.get("QT_QPA_PLATFORM", "").lower() in HEADLESS


def _qt_message_box(text: str) -> bool:
    """Show ``text`` in a modal Qt error box. False when there is no screen to show it on."""
    if headless():
        return False
    from PySide6.QtWidgets import QMessageBox

    QMessageBox.critical(None, TITLE, text)
    return True


def native_message_box(text: str) -> bool:
    """Windows only, and only without a console (the windowed exe): ``MessageBoxW``, which
    needs no Qt. False when not shown (other OS, a console exists, headless, or the call
    failed)."""
    if sys.platform != "win32" or headless():
        return False
    try:
        import ctypes

        if ctypes.windll.kernel32.GetConsoleWindow():  # type: ignore[attr-defined]
            return False
        ctypes.windll.user32.MessageBoxW(None, text, TITLE, 0x10)  # type: ignore[attr-defined]
        return True
    except (AttributeError, OSError):
        return False


def _console_wait(prompt: str) -> str:
    """``input`` only when someone can answer (an interactive console)."""
    stdin = sys.stdin
    if stdin is None or not stdin.isatty():
        return ""
    return input(prompt)


def notify(text: str, out: TextIO | None = None, read: Callable[[str], str] | None = None,
           native_box: Callable[[str], bool] | None = None) -> None:
    """Show a message that must not be missed outside Qt (native box or console)."""
    if (native_box or native_message_box)(text):
        return
    out = out if out is not None else sys.stderr
    try:
        out.write(text + "\n")
        out.flush()
    except (AttributeError, OSError, ValueError):
        pass
    try:
        (read or _console_wait)("Enter zum Beenden ...")
    except (EOFError, KeyboardInterrupt, OSError, RuntimeError):
        pass


def _check_fail(stage: str) -> None:
    if os.environ.get(FAIL_ENV) == stage:
        raise RuntimeError(f"{FAIL_ENV}={stage} (test hook)")


def run_gui(*, out: TextIO | None = None, read: Callable[[str], str] | None = None,
            message_box: Callable[[str], bool] = _qt_message_box,
            native_box: Callable[[str], bool] = native_message_box,
            main: Callable[[list[str]], int] | None = None) -> int | None:
    """Open the main window and run until it is closed. None when PySide6 is missing.

    Any start failure is appended to :func:`startup_log.log_path` and reported (see the module
    docstring); the return value is then ``EXIT_GUI_FAILED``. Exceptions inside Qt slots while
    the GUI runs go to the same log (``stage: running``) and to the previous excepthook."""
    if not gui_importable():
        return None
    stage, qt_up = "import", False
    previous_hook = sys.excepthook

    def log_hook(kind, exc, tb):
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
        stage = "window"
        _check_fail("window")
        sys.excepthook = log_hook
        return (main or gui_main)(argv)
    except Exception as exc:  # noqa: BLE001 - every start failure must be reported
        return _report(exc, stage, qt_up, out, read, message_box, native_box)
    finally:
        sys.excepthook = previous_hook


def _report(exc: Exception, stage: str, qt_up: bool, out: TextIO | None,
            read: Callable[[str], str] | None, message_box: Callable[[str], bool],
            native_box: Callable[[str], bool]) -> int:
    text = format_error(exc, stage)
    path = write_error(text)
    where = (f"Details stehen in:\n{path}" if path else
             f"Die Logdatei konnte nicht geschrieben werden ({log_path()}).")
    msg = (f"AbeltonGod konnte die Oberflaeche nicht starten.\n\n{type(exc).__name__}: {exc}"
           f"\n\n{where}\n\nDas Textmenue startet mit: AbeltonGod-cli.exe")
    out = out if out is not None else sys.stderr
    try:
        out.write(text)
        out.flush()
    except (AttributeError, OSError, ValueError):
        pass
    shown = False
    if qt_up:
        try:
            shown = message_box(msg)
        except Exception:  # noqa: BLE001 - the box itself failed: fall back
            shown = False
    if not shown:
        notify(msg, out, read, native_box)
    return EXIT_GUI_FAILED


def run_selftest() -> int:
    if not gui_importable():
        sys.stdout.write("GUI selftest FAIL: PySide6 fehlt\n")
        return 1
    from gui.selftest import run

    return run(sys.stdout)
