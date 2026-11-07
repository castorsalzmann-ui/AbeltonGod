"""Deterministic fx variants around a base parameter set (issue #482).

Same scheme as the perc and rim variants: variant 0 is the base; variant ``i >= 1`` gets its own
seed (new noise) and moves the filter by one shared factor ``2^o``, ``o`` drawn from its own
SHA-256 hash inside +-0.1 octave intersected with what keeps both cutoffs in the contract range
(never clamped). Start and end move together, so a static filter stays static and a sweep keeps
its width. Lengths, levels and the kind never change (a variant must still land on the same bar
line). Every variant is validated by :func:`~audio_engine.fx.resolve_fx_params`.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

from .fx import BATCH_ONLY_PARAMS, FxParamsError, _schema, resolve_fx_params
from .variants import DECIMALS

SALT = b"abeltongod-fx-variant/v1:"
SPREAD_OCTAVES = 0.1
# (field, mode, half width), the same shape as the other *_variants.SPREAD tables; read by the
# GUI's Hauptregler scoring. Both cutoffs move by one shared factor (make_variant).
SPREAD: tuple[tuple[str, str, float], ...] = (
    ("cutoff_start_hz", "oct", SPREAD_OCTAVES),
    ("cutoff_end_hz", "oct", SPREAD_OCTAVES),
)


def derived_seed(base_seed: int, index: int) -> int:
    digest = hashlib.sha256(SALT + f"{int(base_seed)}:{int(index)}".encode()).digest()
    return int.from_bytes(digest[:4], "big")


def unit_offset(base_seed: int, index: int, field: str) -> float:
    """Uniform value in ``[-1, 1)`` from 53 bits of SHA-256, one hash per field."""
    digest = hashlib.sha256(SALT + f"{int(base_seed)}:{int(index)}:{field}".encode()).digest()
    return (int.from_bytes(digest[:8], "big") >> 11) / 2.0**52 - 1.0


def make_variant(base: dict[str, Any], index: int) -> dict[str, Any]:
    """Resolved parameters of variant ``index`` (0 = the base)."""
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise ValueError(f"variant index must be an int >= 0, got {index!r}")
    resolved = resolve_fx_params(base)
    for key in BATCH_ONLY_PARAMS:
        resolved.pop(key, None)
    if index == 0:
        return resolved
    props = _schema()["properties"]
    seed = resolved["seed"]
    a, b = float(resolved["cutoff_start_hz"]), float(resolved["cutoff_end_hz"])
    lo_hz, hi_hz = props["cutoff_start_hz"]["minimum"], props["cutoff_start_hz"]["maximum"]
    lo = max(-SPREAD_OCTAVES, math.log2(lo_hz / min(a, b)))
    hi = min(SPREAD_OCTAVES, math.log2(hi_hz / max(a, b)))
    if hi < lo:
        raise FxParamsError(f"Variant {index} of seed {seed}: no room to move the cutoff.")
    u = unit_offset(seed, index, "cutoff_octaves")
    factor = 2.0 ** (lo + (u + 1.0) / 2.0 * (hi - lo))
    out = dict(resolved)
    for key, value in (("cutoff_start_hz", a), ("cutoff_end_hz", b)):
        out[key] = round(value * factor, DECIMALS)  # inside the range: lo / hi bound factor
    if a == b:
        out["cutoff_end_hz"] = out["cutoff_start_hz"]
    out["seed"] = derived_seed(seed, index)
    return resolve_fx_params(out)


def make_variants(base: dict[str, Any], count: int) -> list[dict[str, Any]]:
    return [make_variant(base, i) for i in range(count)]
