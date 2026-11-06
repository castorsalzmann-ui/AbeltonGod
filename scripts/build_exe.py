"""Build ``dist/AbeltonGod/AbeltonGod.exe`` (PyInstaller, onedir) from a checkout (#401).

    pip install -e ".[build,gui]"
    python scripts/build_exe.py [--dist DIR]

Why onedir, not onefile: the engine modules find ``contracts/`` and ``config/`` as
``Path(__file__).parents[2]``. In an onedir build that resolves to the exe folder, so the
script copies those folders (and ``.env.example``) next to the exe. A onefile exe unpacks to
a temp folder whose parent is not under our control, so the same lookup would break. Onedir
also starts faster (no unpack on every start) and triggers fewer virus-scanner false alarms.
The CI artifact is the zipped folder.

The script adds no tool code; it only collects what ``src/launcher/exe_entry.py`` dispatches
to: all packages under ``src/`` (hidden imports), the preset JSONs, the Live scripts (loaded
by path at run time), and ``build_info.json`` for ``--version``. Secrets are never copied:
only ``.env.example``, never ``.env``.
"""

from __future__ import annotations

import argparse
import ast
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "AbeltonGod"
PACKAGES = ("audio_engine", "bridge", "library", "orchestrator", "guard", "launcher",
            "gui", "gui_core")
# GUI (D-029, #432). PyInstaller's PySide6 hook collects the Qt plugins (platforms incl.
# qwindows, styles, imageformats ...) of every Qt module that is imported, so the three modules
# the GUI uses are named explicitly; the Qt modules it never uses are left out to keep the
# folder small (the build log and the exe_smoke ``gui`` check show if one was needed).
QT_MODULES = ("PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets")
QT_EXCLUDES = ("PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtQuickWidgets",
               "PySide6.QtQuickControls2", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
               "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtSql", "PySide6.QtTest",
               "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtSvg",
               "PySide6.QtSvgWidgets", "PySide6.QtNetwork", "PySide6.QtDBus",
               "PySide6.QtWebChannel", "PySide6.QtWebSockets", "PySide6.QtXml",
               "PySide6.QtConcurrent", "PySide6.QtStateMachine", "PySide6.QtUiTools",
               "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSensors",
               "PySide6.QtSerialPort", "PySide6.QtTextToSpeech", "PySide6.QtPrintSupport")
# Third-party packages whose data/binaries (and lazily imported submodules) must come along.
COLLECT_ALL = ("claude_agent_sdk", "jsonschema", "jsonschema_specifications",
               "referencing", "pythonosc")
# mcp: collect_all imports every submodule and mcp.cli exits without its optional typer extra
# (CI run 42080769820), so only its data is collected; the code is found by static analysis.
COLLECT_DATA = ("mcp",)
SIDE_DIRS = ("contracts", "config")
DATA_SEP = ";" if sys.platform == "win32" else ":"


def script_imports() -> list[str]:
    """Every module the scripts/ files import: they are loaded by path at run time, so
    PyInstaller's static analysis of the entry point does not see them (stdlib ones too)."""
    names: set[str] = set()
    for path in sorted((ROOT / "scripts").glob("*.py")):
        if path.name == "build_exe.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names.add(node.module)
    return sorted(names)


def git_sha() -> str:
    try:
        done = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short=12", "HEAD"],
                              capture_output=True, text=True, timeout=10, check=False)
        return done.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def write_build_info(work: Path) -> Path:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    path = work / "build_info.json"
    path.write_text(json.dumps({"version": data["project"]["version"], "git_sha": git_sha()}),
                    encoding="utf-8")
    return path


def pyinstaller_args(dist: Path, work: Path, info: Path) -> list[str]:
    args = [
        "--noconfirm", "--clean", "--onedir", "--console", "--name", NAME,
        "--distpath", str(dist), "--workpath", str(work / "pyi"), "--specpath", str(work),
        "--paths", str(ROOT / "src"),
        "--add-data", f"{ROOT / 'src' / 'audio_engine' / 'presets'}{DATA_SEP}audio_engine/presets",
        "--add-data", f"{ROOT / 'scripts'}{DATA_SEP}scripts",
        "--add-data", f"{info}{DATA_SEP}.",
    ]
    for pkg in PACKAGES:
        args += ["--collect-submodules", pkg]
    for pkg in COLLECT_ALL:
        args += ["--collect-all", pkg]
    for pkg in COLLECT_DATA:
        args += ["--collect-data", pkg]
    for mod in script_imports():
        args += ["--hidden-import", mod]
    for mod in QT_MODULES:
        args += ["--hidden-import", mod]
    for mod in QT_EXCLUDES:
        args += ["--exclude-module", mod]
    args.append(str(ROOT / "src" / "launcher" / "exe_entry.py"))
    return args


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dist", type=Path, default=ROOT / "dist")
    ap.add_argument("--work", type=Path, default=ROOT / "build" / "exe")
    a = ap.parse_args(argv)
    try:
        import PyInstaller.__main__ as pyi
    except ImportError:
        print('error: PyInstaller is missing. Install it with: pip install -e ".[build]"',
              file=sys.stderr)
        return 2
    a.work.mkdir(parents=True, exist_ok=True)
    pyi.run(pyinstaller_args(a.dist, a.work, write_build_info(a.work)))
    folder = a.dist / NAME
    for name in SIDE_DIRS:
        target = folder / name
        if target.exists():
            shutil.rmtree(target)
        # config/dev-budget.json is a development-session file, not part of the product.
        shutil.copytree(ROOT / name, target, ignore=shutil.ignore_patterns("dev-budget.json"))
    shutil.copy2(ROOT / ".env.example", folder / ".env.example")
    exe = folder / (NAME + (".exe" if sys.platform == "win32" else ""))
    if not exe.is_file():
        print(f"error: {exe} was not built", file=sys.stderr)
        return 1
    print(f"built {exe}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
