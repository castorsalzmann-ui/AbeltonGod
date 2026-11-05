"""Sample categories shown in the GUI's left list (GUI-0: only the kick is enabled)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CategoryEntry:
    key: str
    label: str
    enabled: bool
    note: str  # shown next to a disabled entry


CATEGORIES: tuple[CategoryEntry, ...] = (
    CategoryEntry("kick", "Kick", True, ""),
    CategoryEntry("hat", "Hi-Hat", True, ""),
    CategoryEntry("snare", "Snare", True, ""),
    CategoryEntry("clap", "Clap", True, ""),
    CategoryEntry("rim", "Rim", True, ""),
    CategoryEntry("bass", "Bass", True, ""),
)

LIBRARY_KEY = "library"
LIBRARY_LABEL = "Bibliothek"
