"""Library: scan an output folder for WAVs and read their sidecars (no Qt, never raises on bad
files). A WAV whose sidecar is missing or unreadable is listed as unreadable, not dropped."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_FILES = 5000  # a scan stops here instead of walking an unbounded tree
UNREADABLE = "unlesbar"

# Parameters shown per category in the list (only those present are shown).
KEY_PARAMS: dict[str, tuple[str, ...]] = {
    "kick": ("pitch_end_hz", "amp_decay_ms", "drive"),
    "hat": ("decay_ms", "metal", "model"),
    "snare": ("body_hz", "noise_decay_ms", "drive"),
    "clap": ("bursts", "tail_decay_ms", "drive"),
    "rim": ("f1_hz", "decay1_ms", "drive"),
    "bass": ("note", "lp_hz", "gate_ms"),
    "laser": ("family", "pitch_start_hz", "salvo_count"),
}


@dataclass(frozen=True)
class LibraryEntry:
    wav_path: Path
    readable: bool
    category: str  # "kick" ... or UNREADABLE
    preset: str
    seed: int | None
    key_params: str
    created_at: str
    problem: str = ""  # why it is unreadable (German)

    @property
    def name(self) -> str:
        return self.wav_path.name


def read_entry(wav_path: Path) -> LibraryEntry:
    """The entry for one WAV. Never raises."""
    side = wav_path.with_suffix(".json")

    def bad(why: str) -> LibraryEntry:
        return LibraryEntry(wav_path, False, UNREADABLE, "", None, "", "", why)

    try:
        meta = json.loads(side.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return bad("Sidecar-Datei fehlt")
    except (OSError, ValueError) as exc:  # includes UnicodeDecodeError and JSON errors
        return bad(f"Sidecar nicht lesbar: {type(exc).__name__}")
    if not isinstance(meta, dict):
        return bad("Sidecar hat kein JSON-Objekt")
    params = meta.get("parameters")
    params = params if isinstance(params, dict) else {}
    # Sidecars of the first format version have no category: they were kicks.
    category = meta.get("category", "kick")
    if not isinstance(category, str) or not category:
        return bad("Sidecar ohne gültige Kategorie")
    seed = params.get("seed")
    preset = params.get("preset")
    created = meta.get("created_at")
    keys = KEY_PARAMS.get(category, ())
    shown = ", ".join(f"{k}={params[k]}" for k in keys if k in params and _plain(params[k]))
    return LibraryEntry(
        wav_path, True, category,
        preset if isinstance(preset, str) else "",
        seed if isinstance(seed, int) and not isinstance(seed, bool) else None,
        shown, created if isinstance(created, str) else "",
    )


def _plain(v: Any) -> bool:
    return isinstance(v, str | int | float | bool)


def scan_library(folder: str | Path) -> list[LibraryEntry]:
    """All WAVs under ``folder`` (newest first by creation time, then name). A missing folder
    gives an empty list."""
    root = Path(folder)
    entries: list[LibraryEntry] = []
    try:
        if not root.is_dir():
            return []
        for i, wav in enumerate(sorted(root.rglob("*.wav"))):
            if i >= MAX_FILES:
                break
            entries.append(read_entry(wav))
    except OSError:
        pass  # folder vanished or unreadable mid-scan: show what we have
    entries.sort(key=lambda e: e.name)
    entries.sort(key=lambda e: e.created_at, reverse=True)
    return entries


def filter_entries(
    entries: list[LibraryEntry], category: str | None = None, text: str = ""
) -> list[LibraryEntry]:
    """``category`` None = all (``UNREADABLE`` selects the unreadable ones). ``text`` matches
    case-insensitively in name, preset, category, seed and key parameters; every word must match."""
    words = text.lower().split()
    out = []
    for e in entries:
        if category is not None and e.category != category:
            continue
        hay = f"{e.name} {e.preset} {e.category} {e.seed if e.seed is not None else ''} " \
              f"{e.key_params}".lower()
        if all(w in hay for w in words):
            out.append(e)
    return out


def drag_paths(entries: list[LibraryEntry]) -> list[Path]:
    """The WAV files to offer in a drag (existing files only)."""
    return [e.wav_path for e in entries if e.wav_path.is_file()]
