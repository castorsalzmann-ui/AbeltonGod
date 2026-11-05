"""Version line for ``--version``: project version, git sha and engine version.

The build (``scripts/build_exe.py``) writes ``build_info.json`` into the bundle. Without it
(running from a checkout) the version comes from ``pyproject.toml`` and the sha from ``git``.
"""

from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path

from audio_engine import ENGINE_VERSION

from .paths import bundle_root

UNKNOWN = "unknown"


def _from_checkout() -> dict[str, str]:
    root = Path(__file__).resolve().parents[2]
    info = {"version": UNKNOWN, "git_sha": UNKNOWN}
    try:
        data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        info["version"] = str(data["project"]["version"])
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        pass
    try:
        done = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short=12", "HEAD"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if done.returncode == 0 and done.stdout.strip():
            info["git_sha"] = done.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return info


def build_info() -> dict[str, str]:
    path = bundle_root() / "build_info.json"
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return {"version": str(data["version"]), "git_sha": str(data["git_sha"])}
        except (OSError, KeyError, ValueError):
            return {"version": UNKNOWN, "git_sha": UNKNOWN}
    return _from_checkout()


def version_line() -> str:
    info = build_info()
    return f"AbeltonGod {info['version']} (git {info['git_sha']}, engine {ENGINE_VERSION})"
