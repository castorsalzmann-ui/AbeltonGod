"""Shared settings of the main window and the tool windows (Goa, Acid, Blaster). No Qt.

One JSON file in the user config dir (``$ABELTONGOD_CONFIG_DIR`` if set; Windows
``%APPDATA%\\AbeltonGod``; else ``$XDG_CONFIG_HOME/abeltongod`` or ``~/.config/abeltongod``),
file ``settings.json``. Never raises on a missing or damaged file: a bad value falls back to its
default, the other values are kept.

What the settings mean (decided in #439):

* ``output_dir`` -- root of the output tree. The main window renders into it, the library page
  lists every WAV below it. The tool windows write below it (see the ``*_dir`` helpers):
  Acid ``<out>/acid``, Goa ``<out>/goa/<run>``, Blaster ``<out>/Samples/FX/Lasers`` (the library
  layout's laser folder, so the Live import accepts the file). Empty = ``default_output_dir()``.
* ``project_dir`` -- optional Ableton project folder: the "Live-Projekt" of the Live-import page
  (one setting, edited there or in the dialog) and the start folder of the Blaster's bank
  export dialog. The library does not read it.
* ``sample_rate`` / ``bit_depth`` -- ``None`` = the contract default (48000 Hz, 24 bit). A set
  value is the start value of the category forms and is used for Blaster library saves, Blaster
  banks and Acid WAVs. Changing it (also back to ``None``) puts the forms to it; other settings
  changes never touch the forms.
* ``windows`` -- last position and size per window key (``main``, ``goa``, ``acid``,
  ``blaster``); the Goa window also keeps ``always_on_top`` and ``animation``.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from library.layout import LibraryLayout

from .paths import default_output_dir

CONFIG_ENV = "ABELTONGOD_CONFIG_DIR"
FILE_NAME = "settings.json"
FORMAT_VERSION = 1
SAMPLE_RATES = (44100, 48000)  # the contracts' enum
BIT_DEPTHS = (16, 24)
DEFAULT_SAMPLE_RATE, DEFAULT_BIT_DEPTH = 48000, 24  # the contracts' default
WINDOW_KEYS = ("main", "goa", "acid", "blaster")
MAX_COORD = 100_000
MIN_EDGE = 100  # a saved window smaller than this is ignored


def default_config_dir() -> Path:
    env = os.environ.get(CONFIG_ENV, "").strip()
    if env:
        return Path(env)
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "").strip()
        if appdata:
            return Path(appdata) / "AbeltonGod"
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    return (Path(xdg) if xdg else Path.home() / ".config") / "abeltongod"


def default_settings_path() -> Path:
    return default_config_dir() / FILE_NAME


@dataclass(frozen=True)
class WindowState:
    x: int
    y: int
    width: int
    height: int
    always_on_top: bool | None = None  # Goa window only
    animation: bool | None = None  # Goa window only

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"x": self.x, "y": self.y, "width": self.width,
                               "height": self.height}
        if self.always_on_top is not None:
            out["always_on_top"] = self.always_on_top
        if self.animation is not None:
            out["animation"] = self.animation
        return out


@dataclass(frozen=True)
class AppSettings:
    output_dir: str = ""
    project_dir: str = ""
    sample_rate: int | None = None
    bit_depth: int | None = None
    windows: dict[str, WindowState] = field(default_factory=dict)

    # --- derived places ------------------------------------------------------------------
    def output_root(self) -> Path:
        return Path(self.output_dir) if self.output_dir.strip() else default_output_dir()

    def project_root(self) -> Path | None:
        return Path(self.project_dir) if self.project_dir.strip() else None

    def acid_dir(self) -> Path:
        return self.output_root() / "acid"

    def goa_dir(self) -> Path:
        return self.output_root() / "goa"

    def laser_dir(self) -> Path:
        return self.output_root().joinpath(*LibraryLayout().parts_for("laser"))

    def bank_start_dir(self) -> Path:
        return self.project_root() or self.output_root()

    # --- audio format --------------------------------------------------------------------
    def effective_sample_rate(self) -> int:
        return self.sample_rate if self.sample_rate is not None else DEFAULT_SAMPLE_RATE

    def effective_bit_depth(self) -> int:
        return self.bit_depth if self.bit_depth is not None else DEFAULT_BIT_DEPTH

    def format_overrides(self) -> dict[str, int]:
        """The request fields a set format adds (empty when both are the contract default)."""
        out: dict[str, int] = {}
        if self.sample_rate is not None:
            out["sample_rate"] = self.sample_rate
        if self.bit_depth is not None:
            out["bit_depth"] = self.bit_depth
        return out

    def to_json(self) -> dict[str, Any]:
        return {
            "version": FORMAT_VERSION,
            "output_dir": self.output_dir,
            "project_dir": self.project_dir,
            "sample_rate": self.sample_rate,
            "bit_depth": self.bit_depth,
            "windows": {k: v.to_json() for k, v in sorted(self.windows.items())},
        }


def _int(v: Any, lo: int = -MAX_COORD, hi: int = MAX_COORD) -> int | None:
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        return None
    return v


def _window(raw: Any) -> WindowState | None:
    if not isinstance(raw, dict):
        return None
    x, y = _int(raw.get("x")), _int(raw.get("y"))
    w, h = _int(raw.get("width"), MIN_EDGE), _int(raw.get("height"), MIN_EDGE)
    if None in (x, y, w, h):
        return None
    top, anim = raw.get("always_on_top"), raw.get("animation")
    return WindowState(x, y, w, h,  # type: ignore[arg-type]
                       top if isinstance(top, bool) else None,
                       anim if isinstance(anim, bool) else None)


def settings_from_json(raw: Any) -> AppSettings:
    """Every value checked on its own: a bad one gets its default, the others are kept."""
    if not isinstance(raw, dict):
        return AppSettings()
    out, proj = raw.get("output_dir"), raw.get("project_dir")
    rate, bits = raw.get("sample_rate"), raw.get("bit_depth")
    wins = raw.get("windows")
    windows: dict[str, WindowState] = {}
    if isinstance(wins, dict):
        for key in WINDOW_KEYS:
            ws = _window(wins.get(key))
            if ws is not None:
                windows[key] = ws
    return AppSettings(
        output_dir=out if isinstance(out, str) else "",
        project_dir=proj if isinstance(proj, str) else "",
        sample_rate=rate if _int(rate) is not None and rate in SAMPLE_RATES else None,
        bit_depth=bits if _int(bits) is not None and bits in BIT_DEPTHS else None,
        windows=windows,
    )


def load_settings(path: Path | None = None) -> AppSettings:
    path = Path(path) if path is not None else default_settings_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return AppSettings()
    return settings_from_json(raw)


def save_settings(settings: AppSettings, path: Path | None = None) -> bool:
    """Write atomically (temp file + replace); False, no exception, if it cannot be written.
    A failed write leaves the previous file as it was."""
    path = Path(path) if path is not None else default_settings_path()
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(settings.to_json(), indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    return True


def free_stem(folder: Path, stem: str, suffixes: tuple[str, ...] = (".wav", ".json")) -> str:
    """``stem`` or ``stem_2``, ``stem_3`` ...: the first name with none of ``suffixes`` taken in
    ``folder`` (files are never overwritten, D-006)."""
    folder = Path(folder)
    cand, n = stem, 1
    while any((folder / f"{cand}{s}").exists() for s in suffixes):
        n += 1
        cand = f"{stem}_{n}"
    return cand


def _field_state(model: Any, name: str) -> tuple[str, bool]:
    return model.text.get(name, ""), name in model.active


def apply_format_to_form(model: Any, settings: AppSettings,
                         fields: tuple[str, ...] = ("sample_rate", "bit_depth")) -> bool:
    """Put the form's ``sample_rate`` / ``bit_depth`` (only those in ``fields``) to the
    settings: a set value is sent; ``None`` (contract default) puts the field back to what a
    fresh form of the same preset has (the request is then byte-identical to a fresh form). A
    value equal to what the form already sends, or to the default of a switched-off field,
    changes nothing. The caller applies this only when the format setting itself changed, so
    a value typed into a form survives other settings changes. True if the form changed."""
    changed = False
    names = set(model.specs_names())
    values = {"sample_rate": settings.sample_rate, "bit_depth": settings.bit_depth}
    for name in fields:
        if name not in names:
            continue
        value = values[name]
        before = _field_state(model, name)
        if value is None:
            model.reset_field(name)  # back to the preset (= the contract default if absent)
        else:
            current, problem = model.parse(name)
            if name in model.active and problem is None and current == value:
                continue
            if name not in model.active and model.spec(name).default == value:
                continue
            model.set_text(name, str(value))
            model.set_active(name, True)
        changed = changed or _field_state(model, name) != before
    return changed


class SettingsStore:
    """The one settings object all windows share. ``path=None`` keeps it in memory only (tests,
    the standalone tool windows): nothing is read or written. Listeners are called after every
    change with the new settings."""

    def __init__(self, settings: AppSettings | None = None, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        if settings is None:
            settings = load_settings(self.path) if self.path is not None else AppSettings()
        self.settings = settings
        self.last_save_ok = True
        self._listeners: list[Callable[[AppSettings], None]] = []

    @classmethod
    def from_default_location(cls) -> SettingsStore:
        return cls(path=default_settings_path())

    @property
    def persistent(self) -> bool:
        return self.path is not None

    def subscribe(self, fn: Callable[[AppSettings], None]) -> None:
        self._listeners.append(fn)

    def unsubscribe(self, fn: Callable[[AppSettings], None]) -> None:
        self._listeners = [f for f in self._listeners if f != fn]

    def save(self) -> bool:
        if self.path is None:
            return False
        self.last_save_ok = save_settings(self.settings, self.path)
        return self.last_save_ok

    def update(self, **changes: Any) -> AppSettings:
        """Change fields, save (if persistent) and tell the listeners. Unknown names raise
        TypeError; out-of-range values raise ValueError (the dialog never offers them)."""
        rate, bits = changes.get("sample_rate", None), changes.get("bit_depth", None)
        if rate is not None and rate not in SAMPLE_RATES:
            raise ValueError(f"sample_rate must be one of {SAMPLE_RATES} or None")
        if bits is not None and bits not in BIT_DEPTHS:
            raise ValueError(f"bit_depth must be one of {BIT_DEPTHS} or None")
        new = replace(self.settings, **changes)
        if new == self.settings:
            return new
        self.settings = new
        self.save()
        for fn in list(self._listeners):
            fn(new)
        return new

    def set_window(self, key: str, state: WindowState) -> None:
        """Remember a window's place; saved, but listeners are not called (nothing to redraw)."""
        if key not in WINDOW_KEYS:
            raise KeyError(key)
        if self.settings.windows.get(key) == state:
            return
        self.settings = replace(self.settings, windows={**self.settings.windows, key: state})
        self.save()
