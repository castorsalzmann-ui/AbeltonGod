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
    CategoryEntry("hat", "Hi-Hat", False, "kommt in GUI-1"),
    CategoryEntry("snare", "Snare", False, "kommt in GUI-1"),
    CategoryEntry("clap", "Clap", False, "kommt in GUI-1"),
    CategoryEntry("rim", "Rim", False, "kommt in GUI-1"),
    CategoryEntry("bass", "Bass", False, "kommt in GUI-1"),
)
