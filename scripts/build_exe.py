"""Build ``dist/AbeltonGod/AbeltonGod.exe`` (PyInstaller, onedir) from a checkout (#401).

    pip install -e ".[build,gui]"
    python scripts/build_exe.py [--dist DIR]

Why onedir, not onefile: the engine modules find ``contracts/`` and ``config/`` as
``Path(__file__).parents[2]``. In an onedir build that resolves to the exe folder, so the
script copies those folders (and ``.env.example``) next to the exe. A onefile exe unpacks to
a temp folder whose parent is not under our control, so the same lookup would break. Onedir
also starts faster (no unpack on every start) and triggers fewer virus-scanner false alarms.
The CI artifact is the zipped folder.

Two exes in that one folder, from one generated spec file with a shared COLLECT (#445):
``AbeltonGod.exe`` is windowed (GUI subsystem, double-click opens the GUI, no console window
to hide), ``AbeltonGod-cli.exe`` is a console exe for the command line and the text menu. Both
run the same entry script and share ``_internal``; the file name selects the mode.

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
# Files PyInstaller's PySide6 hook collects that the widget GUI never loads (#435, measured
# on the runner: 72 MB PySide6 folder). Paths relative to _internal/PySide6; removed after the
# build. Why each is unused:
#   opengl32sw.dll      software OpenGL (Mesa) fallback; only Qt Quick / QOpenGL use OpenGL,
#                       the GUI paints with QPainter on the raster backend
#   translations/       Qt's own .qm files; nothing installs a QTranslator (texts are German
#                       in the code)
#   imageformats/       PNG (the only format the GUI writes, screenshots) is built into QtGui;
#                       no image file is loaded
#   iconengines/        SVG icon engine; no icon file is loaded
#   tls/, networkinformation/, Qt6Network.dll   QtNetwork is not imported
#   generic/            TUIO touch input over the network
#   Qt6Svg.dll          only needed by the svg imageformat/icon plugins removed above
#   qdirect2d, qminimal alternative platform plugins; qwindows (screen) and qoffscreen
#                       (--gui-selftest) stay
# The "Build exe" smoke proves the rest is enough: --gui-selftest on the real ``windows``
# platform and offscreen, and a copy without qwindows.dll must fail (build-exe.yml).
QT_PRUNE = ("opengl32sw.dll", "translations", "plugins/imageformats", "plugins/iconengines",
            "plugins/tls", "plugins/networkinformation", "plugins/generic",
            "plugins/platforms/qdirect2d.dll", "plugins/platforms/qminimal.dll",
            "Qt6Network.dll", "Qt6Svg.dll")
# Must exist after pruning, or the build fails (a wrong prune entry is caught at build time).
QT_REQUIRED = ("Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll", "QtCore.pyd", "QtGui.pyd",
               "QtWidgets.pyd", "plugins/platforms/qwindows.dll",
               "plugins/platforms/qoffscreen.dll")
SIDE_DIRS = ("contracts", "config")


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


CLI_NAME = NAME + "-cli"

SPEC_TEMPLATE = '''# Generated by scripts/build_exe.py - do not edit.
import sys
sys.path.insert(0, {src!r})
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

datas = {datas!r}
binaries = []
hiddenimports = {hidden!r}
for pkg in {packages!r}:
    hiddenimports += collect_submodules(pkg)
for pkg in {collect_all!r}:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
for pkg in {collect_data!r}:
    datas += collect_data_files(pkg)

a = Analysis([{entry!r}], pathex=[{src!r}], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, excludes={excludes!r})
pyz = PYZ(a.pure)
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name={name!r}, console=False,
          upx=False)
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name={cli_name!r}, console=True,
          upx=False)
COLLECT(gui, cli, a.binaries, a.datas, upx=False, name={name!r})
'''


def spec_text(info: Path) -> str:
    """The spec: one Analysis, a windowed and a console EXE, one shared COLLECT (#445)."""
    datas = [(str(ROOT / "src" / "audio_engine" / "presets"), "audio_engine/presets"),
             (str(ROOT / "scripts"), "scripts"), (str(info), ".")]
    return SPEC_TEMPLATE.format(
        src=str(ROOT / "src"), datas=datas, hidden=script_imports() + list(QT_MODULES),
        packages=list(PACKAGES), collect_all=list(COLLECT_ALL), collect_data=list(COLLECT_DATA),
        entry=str(ROOT / "src" / "launcher" / "exe_entry.py"), excludes=list(QT_EXCLUDES),
        name=NAME, cli_name=CLI_NAME)


def pyinstaller_args(dist: Path, work: Path, info: Path) -> list[str]:
    spec = work / f"{NAME}.spec"
    spec.write_text(spec_text(info), encoding="utf-8")
    return ["--noconfirm", "--clean", "--distpath", str(dist), "--workpath", str(work / "pyi"),
            str(spec)]


def _tree_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def size_report(folder: Path, top: int = 20) -> str:
    """Sizes of the built folder (#435): total, per entry of the folder and of ``_internal``
    and ``_internal/PySide6``, and the largest files. Plain text for the CI log."""
    mb = 1024 * 1024
    lines = [f"total: {_tree_size(folder) / mb:.1f} MB in {folder}"]
    for sub in (folder, folder / "_internal", folder / "_internal" / "PySide6"):
        if not sub.is_dir():
            continue
        rows = sorted(((_tree_size(p), p.name) for p in sub.iterdir()), reverse=True)
        lines.append(f"-- {sub.relative_to(folder.parent)} (top {top})")
        lines += [f"{size / mb:8.1f} MB  {name}" for size, name in rows[:top]]
    files = sorted(((p.stat().st_size, p) for p in folder.rglob("*") if p.is_file()),
                   reverse=True)
    lines.append(f"-- largest files (top {top})")
    lines += [f"{size / mb:8.1f} MB  {p.relative_to(folder)}" for size, p in files[:top]]
    return "\n".join(lines)


def prune_qt(folder: Path, prune: tuple[str, ...] = QT_PRUNE,
             required: tuple[str, ...] = QT_REQUIRED) -> tuple[int, list[str]]:
    """Remove ``prune`` below ``folder/_internal/PySide6``. Returns (bytes freed, lines for
    the log). Raises FileNotFoundError when a ``required`` file is missing afterwards. An entry
    that does not exist is only logged (PySide6 versions differ in what they ship)."""
    qt = folder / "_internal" / "PySide6"
    freed, lines = 0, []
    for rel in prune:
        path = qt / rel
        if not path.exists():
            lines.append(f"prune: {rel} not present")
            continue
        size = _tree_size(path)
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        freed += size
        lines.append(f"prune: {rel} {size / 1024 / 1024:.1f} MB")
    missing = [rel for rel in required if not (qt / rel).is_file()]
    if missing:
        raise FileNotFoundError(f"required Qt files missing after pruning: {missing}")
    return freed, lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dist", type=Path, default=ROOT / "dist")
    ap.add_argument("--work", type=Path, default=ROOT / "build" / "exe")
    ap.add_argument("--report", type=Path, metavar="FOLDER",
                    help="only print the size report of an already built folder")
    ap.add_argument("--subsystem", type=Path, metavar="FOLDER",
                    help="only check that the GUI exe is windowed (2) and the CLI exe console (3)")
    a = ap.parse_args(argv)
    if a.report:
        print(size_report(a.report))
        return 0
    if a.subsystem:
        got = {p.name: pe_subsystem(p) for p in (a.subsystem / f"{NAME}.exe",
                                                 a.subsystem / f"{CLI_NAME}.exe")}
        print(got)
        return 0 if got == {f"{NAME}.exe": 2, f"{CLI_NAME}.exe": 3} else 1
    try:
        import PyInstaller.__main__ as pyi
    except ImportError:
        print('error: PyInstaller is missing. Install it with: pip install -e ".[build]"',
              file=sys.stderr)
        return 2
    a.work.mkdir(parents=True, exist_ok=True)
    pyi.run(pyinstaller_args(a.dist, a.work, write_build_info(a.work)))
    folder = a.dist / NAME
    if (folder / "_internal" / "PySide6").is_dir():
        try:
            # the required names are the Windows ones (.dll/.pyd); the exe is built there
            freed, lines = prune_qt(folder, required=QT_REQUIRED if sys.platform == "win32"
                                    else ())
        except FileNotFoundError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print("\n".join(lines))
        print(f"pruned unused Qt files: {freed / 1024 / 1024:.1f} MB")
    for name in SIDE_DIRS:
        target = folder / name
        if target.exists():
            shutil.rmtree(target)
        # config/dev-budget.json is a development-session file, not part of the product.
        shutil.copytree(ROOT / name, target, ignore=shutil.ignore_patterns("dev-budget.json"))
    shutil.copy2(ROOT / ".env.example", folder / ".env.example")
    suffix = ".exe" if sys.platform == "win32" else ""
    for name in (NAME, CLI_NAME):
        exe = folder / (name + suffix)
        if not exe.is_file():
            print(f"error: {exe} was not built", file=sys.stderr)
            return 1
        print(f"built {exe}")
    return 0


def pe_subsystem(path: Path) -> int:
    """The ``Subsystem`` field of a Windows PE file: 2 = GUI (windowed), 3 = console."""
    data = path.read_bytes()[:4096]
    if data[:2] != b"MZ":
        raise ValueError(f"{path} is not a PE file")
    pe = int.from_bytes(data[0x3C:0x40], "little")
    if data[pe:pe + 4] != b"PE\0\0":
        raise ValueError(f"{path} has no PE header")
    # COFF header is 20 bytes after the signature; Subsystem sits at offset 68 of the
    # optional header for both PE32 and PE32+.
    return int.from_bytes(data[pe + 24 + 68:pe + 24 + 70], "little")


if __name__ == "__main__":
    sys.exit(main())
