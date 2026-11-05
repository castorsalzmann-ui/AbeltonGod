"""Default places the GUI writes to."""

from __future__ import annotations

import os
from pathlib import Path

OUTPUT_ENV = "ABELTONGOD_OUTPUT_DIR"


def default_output_dir() -> Path:
    """``$ABELTONGOD_OUTPUT_DIR`` if set, else ``~/AbeltonGod/output`` (created on first render)."""
    env = os.environ.get(OUTPUT_ENV, "").strip()
    return Path(env) if env else Path.home() / "AbeltonGod" / "output"
