"""Deterministic laser variants around a base parameter set (issue #416).

Same scheme as the rim variants: variant 0 is the base; variant ``i >= 1`` gets its own seed and
moves each field of :data:`SPREAD` by an offset from its own SHA-256 hash, drawn inside the
intersection of the spread box and the contract range, rounded to 4 decimals, never clamped.
Every variant is validated by :func:`~audio_engine.laser.resolve_laser_params`.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .laser import BATCH_ONLY_PARAMS, LaserParamsError, _schema, resolve_laser_params
from .variants import DECIMALS, _grid_down, _grid_up

SALT = b"abeltongod-laser-variant/v1:"

# (field, mode, half width). abs: x +- w · rel: x * (1 +- w).
SPREAD: tuple[tuple[str, str, float], ...] = (
    ("pitch_start_hz", "rel", 0.08),
    ("pitch_end_hz", "rel", 0.08),
    ("sweep_ms", "rel", 0.10),
    ("decay_ms", "rel", 0.10),
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
    resolved = resolve_laser_params(base)
    for key in BATCH_ONLY_PARAMS:
        resolved.pop(key, None)
    if index == 0:
        return resolved
    props = _schema()["properties"]
    seed = resolved["seed"]
    out = dict(resolved)
    for field, mode, width in SPREAD:
        x = resolved[field]
        lo, hi = (x - width, x + width) if mode == "abs" else (x * (1 - width), x * (1 + width))
        lo, hi = max(lo, props[field]["minimum"]), min(hi, props[field]["maximum"])
        lo, hi = _grid_up(lo), _grid_down(hi)
        if hi < lo:
            raise LaserParamsError(f"Variant {index} of seed {seed}: empty range for {field}.")
        u = unit_offset(seed, index, field)
        out[field] = round(lo + (u + 1.0) / 2.0 * (hi - lo), DECIMALS)
    out["seed"] = derived_seed(seed, index)
    return resolve_laser_params(out)


def make_variants(base: dict[str, Any], count: int) -> list[dict[str, Any]]:
    return [make_variant(base, i) for i in range(count)]
