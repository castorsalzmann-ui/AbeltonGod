"""Build ``dist/AbeltonGod/AbeltonGod.exe`` (PyInstaller, onedir) from a checkout (#401).

    pip install -e ".[build]"
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
PACKAGES = ("audio_engine", "bridge", "library", "orchestrator", "guard", "launcher")
# Third-party packages whose data/binaries (and lazily imported submodules) must come along.
COLLECT_ALL = ("claude_agent_sdk", "mcp", "jsonschema", "jsonschema_specifications",
               "referencing", "pythonosc")
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
    for mod in script_imports():
        args += ["--hidden-import", mod]
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
