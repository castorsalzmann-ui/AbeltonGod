"""``AbeltonGod.exe`` command line and double-click menu."""

from __future__ import annotations

import shlex
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from .paths import install_problems
from .tools import BY_NAME, TOOLS, Tool, run_tool
from .version import version_line

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_SETUP = 3


def tool_list() -> str:
    width = max(len(t.name) for t in TOOLS)
    return "\n".join(f"  {t.name:<{width}}  {t.summary}" for t in TOOLS)


def usage() -> str:
    return (
        "AbeltonGod.exe <werkzeug> [optionen]\n"
        "AbeltonGod.exe --version | --help | --list\n"
        "Ohne Argumente (Doppelklick) startet ein Textmenue.\n\n"
        "Werkzeuge (Optionen: AbeltonGod.exe <werkzeug> --help):\n" + tool_list()
    )


def default_out() -> Path:
    return Path.home() / "AbeltonGod-out"


def free_subdir(base: Path, stem: str) -> Path:
    """``base/stem``, or ``base/stem_2`` ... when that exists (the goa tools never overwrite)."""
    cand = base / stem
    n = 2
    while cand.exists():
        cand = base / f"{stem}_{n}"
        n += 1
    return cand


def _split(text: str) -> list[str]:
    # posix=False keeps Windows backslashes; it leaves quotes on, so strip them.
    return [p[1:-1] if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'" else p
            for p in shlex.split(text, posix=False)]


def menu(read: Callable[[str], str], out: TextIO) -> int:
    out.write(version_line() + "\n\nWerkzeuge:\n")
    for i, t in enumerate(TOOLS, 1):
        out.write(f"  {i:2d}  {t.name:<18} {t.summary}\n")
    try:
        choice = read("\nWerkzeug (Nummer oder Name, Enter = Ende): ").strip()
        if not choice:
            return EXIT_OK
        tool = _pick(choice)
        if tool is None:
            out.write(f"Unbekanntes Werkzeug {choice!r}.\n")
            _pause(read)
            return EXIT_USAGE
        args = list(tool.menu_args)
        if tool.out_mode:
            base = Path(read(f"Ausgabeordner [{default_out()}]: ").strip().strip('"')
                        or default_out())
            target = free_subdir(base, tool.name) if tool.out_mode == "new" else base
            args += ["--out", str(target)]
        extra = read("Weitere Optionen (Enter = keine; '--help' zeigt alle): ").strip()
        args += _split(extra)
        out.write(f"\n> AbeltonGod.exe {tool.name} {' '.join(args)}\n\n")
        out.flush()
        code = run_tool(tool, args)
        out.write(f"\nFertig (Exit-Code {code}).\n")
        if tool.out_mode:
            out.write(f"Dateien liegen unter: {args[args.index('--out') + 1]}\n")
        _pause(read)
        return code
    except (EOFError, KeyboardInterrupt):
        out.write("\nAbgebrochen.\n")
        return EXIT_OK


def _pick(choice: str) -> Tool | None:
    if choice.isdigit():
        i = int(choice)
        return TOOLS[i - 1] if 1 <= i <= len(TOOLS) else None
    return BY_NAME.get(choice.lower())


def _pause(read: Callable[[str], str]) -> None:
    try:
        read("Enter zum Beenden ...")
    except (EOFError, KeyboardInterrupt):
        pass


def run_default(read: Callable[[str], str], out: TextIO) -> int:
    """The no-argument (double-click) path. Today: the text menu. Later (D-029, #403) this is
    the one place that starts the GUI (``python -m gui``) and falls back to the menu when
    PySide6 is missing."""
    problems = install_problems()
    if problems:
        out.write("Installation unvollstaendig:\n  " + "\n  ".join(problems) + "\n")
        _pause(read)
        return EXIT_SETUP
    return menu(read, out)


def main(argv: list[str] | None = None, *, read: Callable[[str], str] = input,
         out: TextIO | None = None) -> int:
    out = out or sys.stdout
    for stream in (sys.stdout, sys.stderr):  # a cp1252 console must not crash on a character
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="backslashreplace")
            except (AttributeError, ValueError):
                pass
    args = sys.argv[1:] if argv is None else list(argv)
    if not args:
        return run_default(read, out)
    first, rest = args[0], args[1:]
    if first == "--version":
        out.write(version_line() + "\n")
        return EXIT_OK
    if first in ("--help", "-h", "help"):
        out.write(usage() + "\n")
        return EXIT_OK
    if first == "--list":
        out.write(tool_list() + "\n")
        return EXIT_OK
    tool = BY_NAME.get(first)
    if tool is None:
        sys.stderr.write(f"Unbekanntes Werkzeug {first!r}. Verfuegbar:\n{tool_list()}\n")
        return EXIT_USAGE
    problems = install_problems()
    if problems and "--help" not in rest and "-h" not in rest:
        sys.stderr.write("Installation unvollstaendig:\n  " + "\n  ".join(problems) + "\n")
        return EXIT_SETUP
    return run_tool(tool, rest)


def entry() -> None:  # pragma: no cover - thin wrapper
    sys.exit(main())
