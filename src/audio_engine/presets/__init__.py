"""Named kick presets (Phase 01b, issue #3).

Each ``<name>.json`` in this folder is exactly one ``kick-params`` object (contract
``contracts/kick-params.schema.json``) with ``preset`` set to its own name. There is no parallel
preset format. Names describe character, not genre (research note, short version 1). Every
preset follows the pitch-settle guideline (``audio_engine.params.pitch_settles``); a test
checks it.

The one-line descriptions below go into the sidecar ``description`` written by the CLI. They
describe the parameters, not how the kick sounds: only the user's listening test can say that.
They name no numbers (#63) and describe the preset as shipped. ``--set`` can change any value,
so a custom render lists its changed values after this text ("Custom values: ..."); the exact
values are in the preset JSON and in every sidecar's ``parameters``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PRESETS_DIR = Path(__file__).resolve().parent

DESCRIPTIONS = {
    "centre": "Near the medians of the measured reference range (mid tail pitch, clean body, "
    "moderate click), with a slower pitch drop than most references (chosen by ear).",
    "dark-dry": "Low tail, little click, darker tilt, no drive.",
    "dense": "The centre values with deliberate drive added; same seed as centre, so it "
    "differs from centre only in drive (chosen by ear in listening tests).",
    "punchy": "Higher tail, one of the two fastest pitch drops, more click, light drive.",
    "rumble-ready": "Long, clean, low tail as a source for a rumble chain built in Live.",
    "driven": "Maximum click, bright tilt, deliberate drive, high tail.",
}


CLAP_DESCRIPTIONS = {
    "default": "The contract defaults written out (three bursts, mid band-pass, 200 ms tail).",
    "short": "Starter set S of the clap reference analysis: four bursts, short tail, mid "
    "band-pass.",
    "long": "Starter set L of the clap reference analysis: four bursts, long tail, mid "
    "band-pass.",
    "bright": "Starter set B of the clap reference analysis: wide band-pass, high high-pass "
    "corner.",
    # Extreme family (#280, clap-params 0.2): the default voice plus one idea each. These
    # describe the parameters, not the sound.
    "xtreme-saturated": "Default voice with strong drive only.",
    "xtreme-folded": "Higher band-pass centre with sine wave folding.",
    "xtreme-crushed": "Bit reduction and sample-and-hold rate reduction, higher high-pass corner.",
    "xtreme-metal": "Ring modulation with a 400 Hz carrier plus a feedback comb.",
    "xtreme-gated": "Long tail cut by a hard gate.",
    "xtreme-reversed": "Strong, medium-length tail reversed in time (swell at the end).",
    "xtreme-wreck": "Drive, fold, bit reduction, rate reduction and comb together; the top of "
    "the range, not a starting point.",
}


HAT_DESCRIPTIONS = {
    "closed-tight": "Closed hat, short decay, high high-pass corner (starter set of the hat "
    "targets note).",
    "closed-std": "Closed hat, medium decay, mid high-pass corner (starter set of the hat "
    "targets note).",
    "closed-loose": "Closed hat, longer decay, lower high-pass corner (starter set of the hat "
    "targets note).",
    "open-short": "Open hat, short open decay, mid high-pass corner (starter set of the hat "
    "targets note).",
    "open-long": "Open hat, long decay, lower-mid high-pass corner (starter set of the hat "
    "targets note).",
}


SNARE_DESCRIPTIONS = {
    "default": "The contract defaults written out (190 Hz body, 180 ms noise decay).",
    "tight": "Short noise tail, higher body (starter set of the snare targets note, N3 short).",
    "long": "Long noise tail (starter set of the snare targets note, N3 long).",
    "tonal": "Higher body share, lower noise share (starter set, N2 body_level 0.85).",
    "bright": "Raised noise high-pass corner (starter set, N4 noise_hp_hz 3500).",
}


BASS_DESCRIPTIONS = {
    "default": "The contract defaults written out (note 43, saw plus sine, 250 ms gate).",
    "sub": "Sine with a small octave-below sine, low cutoff, no filter envelope, no drive.",
    "rolling": "Gate about one 16th at 136 BPM, short release, deeper filter envelope.",
    "bright": "Saw, square and sine, higher cutoff, more resonance, deeper filter envelope.",
    "low": "The defaults on note 31 with a longer gate (a researcher hypothesis for the note).",
}


class UnknownPresetError(KeyError):
    """No preset with this name. The message lists the valid names."""

    def __str__(self) -> str:  # KeyError would print the repr of the message
        return str(self.args[0])


def _folder(category: str) -> Path:
    if category == "kick":
        return PRESETS_DIR
    if category == "clap":
        return PRESETS_DIR / "clap"
    if category == "hat":
        return PRESETS_DIR / "hat"
    if category == "snare":
        return PRESETS_DIR / "snare"
    if category == "bass":
        return PRESETS_DIR / "bass"
    raise ValueError(f"no presets for category {category!r}")


def preset_names(category: str = "kick") -> list[str]:
    """Names of all presets of ``category`` shipped in its folder, sorted."""
    return sorted(p.stem for p in _folder(category).glob("*.json"))


def load_preset(name: str, category: str = "kick") -> dict[str, Any]:
    """The preset's params object as stored (not resolved, not validated here)."""
    names = preset_names(category)
    if name not in names:  # only listed names: no path from user input reaches the file system
        raise UnknownPresetError(
            f"Unknown preset {name!r}. Valid presets: {', '.join(names)}."
        )
    return json.loads((_folder(category) / f"{name}.json").read_text(encoding="utf-8"))


def describe(name: str, category: str = "kick") -> str:
    table = {
        "clap": CLAP_DESCRIPTIONS, "hat": HAT_DESCRIPTIONS, "snare": SNARE_DESCRIPTIONS,
        "bass": BASS_DESCRIPTIONS,
    }.get(category, DESCRIPTIONS)
    return table.get(name, "")
