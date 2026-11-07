"""Deterministic perc variants around a base parameter set (issue #475).

Same scheme as the rim and hat variants: variant 0 is the base; variant ``i >= 1`` gets its own
seed and moves each field of :data:`SPREAD` by an offset from its own SHA-256 hash, drawn inside
the intersection of the spread box and the contract range, rounded to 4 decimals, never clamped.
The model never changes. Fields without effect in the model are not moved (``bend_ms`` outside
tom / conga, ``tick_level`` at shaker), and ``tick_level`` 0 (no tick) stays 0. A ``length_ms``
the request did not give is derived again from the moved ``decay_scale``. Every variant is
validated by :func:`~audio_engine.perc.resolve_perc_params`.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .perc import BATCH_ONLY_PARAMS, MEMBRANES, PercParamsError, _schema, resolve_perc_params
from .variants import DECIMALS, _grid_down, _grid_up

SALT = b"abeltongod-perc-variant/v1:"

# (field, mode, half width). abs: x +- w · rel: x * (1 +- w).
SPREAD: tuple[tuple[str, str, float], ...] = (
    ("tune_semitones", "abs", 0.25),
    ("decay_scale", "rel", 0.10),
    ("tick_level", "abs", 0.05),
    ("bend_ms", "rel", 0.10),
)


def derived_seed(base_seed: int, index: int) -> int:
    digest = hashlib.sha256(SALT + f"{int(base_seed)}:{int(index)}".encode()).digest()
    return int.from_bytes(digest[:4], "big")


def unit_offset(base_seed: int, index: int, field: str) -> float:
    """Uniform value in ``[-1, 1)`` from 53 bits of SHA-256, one hash per field."""
    digest = hashlib.sha256(SALT + f"{int(base_seed)}:{int(index)}:{field}".encode()).digest()
    return (int.from_bytes(digest[:8], "big") >> 11) / 2.0**52 - 1.0


def _moves(field: str, resolved: dict[str, Any]) -> bool:
    model = resolved["model"]
    if field == "bend_ms":
        return model in MEMBRANES and resolved["bend_ratio"] > 1.0
    if field == "tick_level":
        return model != "shaker" and resolved["tick_level"] > 0.0
    return True


def make_variant(base: dict[str, Any], index: int) -> dict[str, Any]:
    """Resolved parameters of variant ``index`` (0 = the base)."""
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise ValueError(f"variant index must be an int >= 0, got {index!r}")
    resolved = resolve_perc_params(base)
    for key in BATCH_ONLY_PARAMS:
        resolved.pop(key, None)
    if index == 0:
        return resolved
    props = _schema()["properties"]
    seed = resolved["seed"]
    out = dict(resolved)
    for field, mode, width in SPREAD:
        if not _moves(field, resolved):
            continue
        x = resolved[field]
        lo, hi = (x - width, x + width) if mode == "abs" else (x * (1 - width), x * (1 + width))
        lo = max(lo, props[field]["minimum"])
        if field == "tick_level":
            lo = max(lo, 10.0**-DECIMALS)  # a tick never disappears in a variant
        lo = _grid_up(lo)
        hi = _grid_down(min(hi, props[field]["maximum"]))
        if hi < lo:
            raise PercParamsError(f"Variant {index} of seed {seed}: empty range for {field}.")
        u = unit_offset(seed, index, field)
        out[field] = round(lo + (u + 1.0) / 2.0 * (hi - lo), DECIMALS)
    out["seed"] = derived_seed(seed, index)
    if "length_ms" not in base:
        out.pop("length_ms")
    return resolve_perc_params(out)


def make_variants(base: dict[str, Any], count: int) -> list[dict[str, Any]]:
    return [make_variant(base, i) for i in range(count)]
