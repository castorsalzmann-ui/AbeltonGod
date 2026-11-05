"""Where the launcher finds bundled files, from a checkout and from the PyInstaller build.

Two roots:

* ``bundle_root()``: where the bundled data lives. Frozen: PyInstaller's ``sys._MEIPASS``
  (``_internal`` next to the exe in an onedir build). Checkout: the repo root.
* ``app_dir()``: the folder of the exe (frozen) or the repo root. ``.env``, ``contracts/`` and
  ``config/`` must be here: the engine modules compute ``Path(__file__).parents[2]`` and in an
  onedir build that is exactly this folder (``_internal/<package>/<module>`` -> exe folder).
  ``scripts/build_exe.py`` copies ``contracts/`` and ``config/`` there after the build.
"""

from __future__ import annotations

import sys
from pathlib import Path

REQUIRED_DIRS = ("contracts", "config")


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def app_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def scripts_dir() -> Path:
    return bundle_root() / "scripts"


def install_problems() -> list[str]:
    """Missing data folders next to the exe (empty in a checkout, where they exist)."""
    root = app_dir()
    return [f"{name}/ fehlt neben {root}" for name in REQUIRED_DIRS if not (root / name).is_dir()]
