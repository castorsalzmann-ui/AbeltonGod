"""Named kick presets (Phase 01b, issue #3).

Each ``<name>.json`` in this folder is exactly one ``kick-params`` object (contract
``contracts/kick-params.schema.json``) with ``preset`` set to its own name. There is no parallel
preset format. Names describe character, not genre (research note, short version 1). Every
preset follows the pitch-settle guideline (``audio_engine.params.pitch_settles``); a test
checks it.

The one-line descriptions below go into the sidecar ``description`` written by the CLI. They
describe the parameters, not how the kick sounds: only the user's listening test can say that.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PRESETS_DIR = Path(__file__).resolve().parent

DESCRIPTIONS = {
    "centre": "Near the medians of the measured reference range (tail 52 Hz, clean body, "
    "moderate click), with a slower pitch drop than most references (tau 40 ms, chosen by "
    "ear in #3).",
    "dark-dry": "Low tail (47 Hz), little click, darker tilt, no drive.",
    "punchy": "Higher tail (56 Hz), fastest pitch drop, more click, light drive.",
    "rumble-ready": "Long, clean, low tail (49 Hz) as a source for a rumble chain built in Live.",
    "driven": "Maximum click, bright tilt, deliberate drive (0.45), tail 58 Hz.",
}


class UnknownPresetError(KeyError):
    """No preset with this name. The message lists the valid names."""

    def __str__(self) -> str:  # KeyError would print the repr of the message
        return str(self.args[0])


def preset_names() -> list[str]:
    """Names of all presets shipped in this folder, sorted."""
    return sorted(p.stem for p in PRESETS_DIR.glob("*.json"))


def load_preset(name: str) -> dict[str, Any]:
    """The preset's ``kick-params`` object as stored (not resolved, not validated here)."""
    names = preset_names()
    if name not in names:  # only listed names: no path from user input reaches the file system
        raise UnknownPresetError(
            f"Unknown preset {name!r}. Valid presets: {', '.join(names)}."
        )
    return json.loads((PRESETS_DIR / f"{name}.json").read_text(encoding="utf-8"))


def describe(name: str) -> str:
    return DESCRIPTIONS.get(name, "")
