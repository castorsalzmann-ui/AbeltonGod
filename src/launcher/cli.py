"""Command line and text menu of ``AbeltonGod-cli.exe``; no-argument GUI start of
``AbeltonGod.exe`` (two exes, #445)."""

from __future__ import annotations

import shlex
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from .gui_start import notify, run_gui, run_selftest
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
        "AbeltonGod-cli.exe <werkzeug> [optionen]\n"
        "AbeltonGod-cli.exe --version | --help | --list | --menu | --gui-selftest\n"
        "Ohne Argumente: AbeltonGod-cli.exe oeffnet das Textmenue (auch: --menu),\n"
        "AbeltonGod.exe das Programmfenster (GUI; ohne Textausgabe).\n\n"
        "Werkzeuge (Optionen: AbeltonGod-cli.exe <werkzeug> --help):\n" + tool_list()
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
        out.write(f"\n> AbeltonGod-cli.exe {tool.name} {' '.join(args)}\n\n")
        out.flush()
        code = run_tool(tool, args)
        out.write(f"\nFertig (Exit-Code {code}).\n")
        if tool.out_mode:
            out.write(f"Dateien liegen unter: {args[args.index('--out') + 1]}\n")
        _pause(read)
        return code
    except (EOFError, KeyboardInterrupt, RuntimeError):  # RuntimeError: no stdin (windowed)
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
    except (EOFError, KeyboardInterrupt, RuntimeError):
        pass


def run_default(read: Callable[[str], str], out: TextIO,
                gui: Callable[[], int | None] | None = None) -> int:
    """The no-argument (double-click) path: the graphical main window (D-029, #432). Without
    PySide6 (``gui`` returns None) it falls back to the text menu."""
    problems = install_problems()
    if problems:
        # windowed exe: no console, so a native message box (gui_start.notify)
        notify("Installation unvollstaendig:\n  " + "\n  ".join(problems), out, read)
        return EXIT_SETUP
    code = (gui or run_gui)()
    if code is not None:
        return code
    out.write("Die grafische Oberflaeche ist nicht verfuegbar (PySide6 fehlt): Textmenue.\n\n")
    return menu(read, out)


def main(argv: list[str] | None = None, *, read: Callable[[str], str] = input,
         out: TextIO | None = None, gui: Callable[[], int | None] | None = None,
         cli_exe: bool = False) -> int:
    """``cli_exe``: running as ``AbeltonGod-cli.exe`` (console build, #445); without arguments
    it opens the text menu instead of the GUI."""
    out = out or sys.stdout
    for stream in (sys.stdout, sys.stderr):  # a cp1252 console must not crash on a character
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="backslashreplace")
            except (AttributeError, ValueError):
                pass
    args = sys.argv[1:] if argv is None else list(argv)
    if not args:
        return menu(read, out) if cli_exe else run_default(read, out, gui)
    first, rest = args[0], args[1:]
    if first == "--menu":
        return menu(read, out)
    if first == "--gui-selftest":
        return run_selftest()
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


CLI_SUFFIX = "-cli"


def is_cli_exe(executable: str) -> bool:
    """The mode rule of the two exes (#445): ``AbeltonGod-cli.exe`` (any case) is the console
    build; every other name, e.g. ``AbeltonGod.exe``, is the windowed GUI build."""
    return Path(executable).stem.lower().endswith(CLI_SUFFIX)


def entry(cli_exe: bool = False) -> None:  # pragma: no cover - thin wrapper
    sys.exit(main(cli_exe=cli_exe))
