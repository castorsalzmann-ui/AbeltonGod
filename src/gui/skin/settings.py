"""Window settings (position, size, always-on-top, animation) as a small JSON file outside the
repo: ``$ABELTONGOD_SKIN_SETTINGS`` or ``~/AbeltonGod/goa_skin.json``. Never raises on a missing or
damaged file: the defaults are used."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

SETTINGS_ENV = "ABELTONGOD_SKIN_SETTINGS"
DEFAULT_SIZE = (460, 340)
MIN_SIZE = (360, 260)
MAX_COORD = 100_000


def default_settings_path() -> Path:
    env = os.environ.get(SETTINGS_ENV, "").strip()
    return Path(env) if env else Path.home() / "AbeltonGod" / "goa_skin.json"


@dataclass
class SkinSettings:
    x: int | None = None
    y: int | None = None
    width: int = DEFAULT_SIZE[0]
    height: int = DEFAULT_SIZE[1]
    always_on_top: bool = True
    animation: bool = False

    def clamped(self) -> SkinSettings:
        return SkinSettings(
            x=self.x,
            y=self.y,
            width=max(MIN_SIZE[0], min(MAX_COORD, self.width)),
            height=max(MIN_SIZE[1], min(MAX_COORD, self.height)),
            always_on_top=self.always_on_top,
            animation=self.animation,
        )


def _int_or_none(v) -> int | None:
    if isinstance(v, bool) or not isinstance(v, int) or abs(v) > MAX_COORD:
        return None
    return v


def load_settings(path: Path | None = None) -> SkinSettings:
    path = path or default_settings_path()
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return SkinSettings()
    if not isinstance(raw, dict):
        return SkinSettings()
    base = SkinSettings()
    x, y = _int_or_none(raw.get("x")), _int_or_none(raw.get("y"))
    if x is None or y is None:  # a position needs both coordinates
        x = y = None
    w = _int_or_none(raw.get("width"))
    h = _int_or_none(raw.get("height"))
    top, anim = raw.get("always_on_top"), raw.get("animation")
    return SkinSettings(
        x=x,
        y=y,
        width=w if w is not None else base.width,
        height=h if h is not None else base.height,
        always_on_top=top if isinstance(top, bool) else base.always_on_top,
        animation=anim if isinstance(anim, bool) else base.animation,
    ).clamped()


def save_settings(settings: SkinSettings, path: Path | None = None) -> bool:
    """Write atomically; return False (no exception) if the folder is not writable."""
    path = Path(path or default_settings_path())
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        return False
    return True
