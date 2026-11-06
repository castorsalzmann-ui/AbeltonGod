"""Which fields of a category are "Hauptregler" (shown on top, accent colour). No Qt.

Method (derived, not listened to), per category:

1. Candidates are the numeric contract fields without housekeeping fields (seed, variants, bpm,
   sample_rate, bit_depth, polarity, offset_ms, peak_ceiling_dbfs, length_ms) and without the
   fields that only exist in a later contract version (they stay under "Erweitert").
2. Score = spread of the field's effective value over the category's presets (population
   standard deviation of the position on the slider scale, so 0..1; a preset that does not set
   the field counts with the contract default) + 0.1 when the engine's own variant generator
   (``SPREAD`` in ``*_variants``) moves that field.
3. The top ``MAIN_COUNT`` scores win; ties keep the contract's field order.

Enum fields that differ between presets (hat ``model``) are listed separately as ``main_choices``.
The result is a statement about the presets and the variant generator, not about sound quality.
"""

from __future__ import annotations

import statistics
from functools import cache

from audio_engine import (
    bass_variants,
    clap_variants,
    hat_variants,
    laser_variants,
    rim_variants,
    snare_variants,
)
from audio_engine import variants as kick_variants
from audio_engine.presets import load_preset, preset_names

from .form import FieldSpec, field_specs
from .valuemap import map_of

MAIN_COUNT = 5
SPREAD_BONUS = 0.1
HOUSEKEEPING = frozenset({
    "seed", "variants", "bpm", "sample_rate", "bit_depth", "polarity", "offset_ms",
    "peak_ceiling_dbfs", "length_ms", "length_beats",
})
_VARIANT_MODULES = {
    "kick": kick_variants, "hat": hat_variants, "snare": snare_variants, "clap": clap_variants,
    "rim": rim_variants, "bass": bass_variants, "laser": laser_variants,
}


def variant_fields(category: str) -> tuple[str, ...]:
    """Fields the engine's variant generator moves (first item of each SPREAD entry)."""
    return tuple(entry[0] for entry in _VARIANT_MODULES[category].SPREAD)


def _effective(spec: FieldSpec, preset: dict) -> object:
    return preset.get(spec.name, spec.default)


def spread_scores(category: str) -> dict[str, float]:
    """Score of every candidate field (step 2 of the method)."""
    presets = [load_preset(n, category) for n in preset_names(category)]
    moved = set(variant_fields(category))
    scores: dict[str, float] = {}
    for spec in field_specs(category):
        if spec.name in HOUSEKEEPING or spec.gate_version or spec.kind not in ("int", "float"):
            continue
        values = [_effective(spec, p) for p in presets]
        if any(v is None for v in values):
            continue
        vmap = map_of(spec)
        positions = [vmap.to_pos(v) / vmap.pos_max for v in values]  # type: ignore[arg-type]
        spread = statistics.pstdev(positions) if len(positions) > 1 else 0.0
        scores[spec.name] = spread + (SPREAD_BONUS if spec.name in moved else 0.0)
    return scores


@cache
def main_controls(category: str) -> tuple[str, ...]:
    """The numeric Hauptregler of a category, best first (at most ``MAIN_COUNT``)."""
    scores = spread_scores(category)
    order = {name: i for i, name in enumerate(scores)}  # contract order breaks ties
    ranked = sorted(scores, key=lambda n: (-scores[n], order[n]))
    return tuple(ranked[:MAIN_COUNT])


@cache
def main_choices(category: str) -> tuple[str, ...]:
    """Enum fields whose value differs between presets (shown as a button row on top)."""
    presets = [load_preset(n, category) for n in preset_names(category)]
    out = []
    for spec in field_specs(category):
        if spec.kind != "enum" or spec.name in HOUSEKEEPING or spec.gate_version:
            continue
        if len({_effective(spec, p) for p in presets}) > 1:
            out.append(spec.name)
    return tuple(out)
