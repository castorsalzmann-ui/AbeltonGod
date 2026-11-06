"""Where a failed GUI start leaves its traces (#436).

The double-click path hides the black console window once the main window is up. A crash
before that point must not vanish: the traceback goes to a log file in the user's app-data
folder, and the user gets a message (a Qt message box when Qt is already up, otherwise the
console stays visible with the text and waits for Enter).

Log folder:

* ``ABELTONGOD_LOG_DIR`` if set (tests, or a user who wants it elsewhere);
* Windows: ``%LOCALAPPDATA%\\AbeltonGod\\logs`` (``%APPDATA%`` if LOCALAPPDATA is not set);
* elsewhere: ``$XDG_STATE_HOME/AbeltonGod/logs`` or ``~/.local/state/AbeltonGod/logs``.
"""

from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

LOG_NAME = "startup-errors.log"
# Keep the file small: when it grows past this, the older half is dropped.
MAX_BYTES = 256 * 1024


def log_dir() -> Path:
    env = os.environ.get("ABELTONGOD_LOG_DIR")
    if env:
        return Path(env)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / "AbeltonGod" / "logs"
        return Path.home() / "AppData" / "Local" / "AbeltonGod" / "logs"
    state = os.environ.get("XDG_STATE_HOME")
    return (Path(state) if state else Path.home() / ".local" / "state") / "AbeltonGod" / "logs"


def log_path() -> Path:
    return log_dir() / LOG_NAME


OUTPUT_NAME = "output.log"


def redirect_missing_streams() -> Path | None:
    """A windowed exe (``AbeltonGod.exe``) has ``sys.stdout``/``sys.stderr`` = None, and any
    write would raise. Send them to ``output.log`` in :func:`log_dir` (overwritten per start),
    or to a discarding stream if that file cannot be opened. Returns the file's path, or None
    when nothing was missing or it could not be opened."""
    if sys.stdout is not None and sys.stderr is not None:
        return None
    path = log_dir() / OUTPUT_NAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        stream = open(path, "w", encoding="utf-8", errors="backslashreplace",  # noqa: SIM115
                      buffering=1)
    except OSError:
        path, stream = None, open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream
    return path


def format_error(exc: BaseException, stage: str) -> str:
    from .version import version_line

    stamp = datetime.now().isoformat(timespec="seconds")
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return (f"=== {stamp} {version_line()} | stage: {stage} | python {sys.version.split()[0]}"
            f" | {sys.platform} | frozen={bool(getattr(sys, 'frozen', False))}\n{tb}\n")


def write_error(text: str) -> Path | None:
    """Append ``text`` to the log file. Returns the path, or None when it could not be written
    (read-only or full disk): the caller still shows the message, the log is a bonus."""
    path = log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.stat().st_size > MAX_BYTES:
            old = path.read_bytes()
            path.write_bytes(old[len(old) // 2:])
        with path.open("a", encoding="utf-8", errors="backslashreplace") as fh:
            fh.write(text)
    except OSError:
        return None
    return path
