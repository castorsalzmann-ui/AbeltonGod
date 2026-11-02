"""Deterministic clap variants around a base parameter set (issue #231).

Same scheme as the kick (:mod:`audio_engine.variants`): variant 0 is the base; variant
``i >= 1`` gets its own seed (the noise sub-streams then change too) and moves each field of
:data:`SPREAD` by an offset from its own SHA-256 hash, drawn uniformly inside the intersection
of the spread box and the contract range, rounded to 4 decimals, never clamped. No NumPy or
global RNG is used for the draws. Fields not in :data:`SPREAD` are copied unchanged. Every
variant is validated by :func:`~audio_engine.clap.resolve_clap_params`.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .clap import BATCH_ONLY_PARAMS, ClapParamsError, _schema, resolve_clap_params
from .variants import DECIMALS, _grid_down, _grid_up

SALT = b"abeltongod-clap-variant/v1:"

# (field, mode, half width). abs: x +- w · rel: x * (1 +- w).
SPREAD: tuple[tuple[str, str, float], ...] = (
    ("burst_spacing_ms", "abs", 1.0),
    ("burst_decay_ms", "rel", 0.10),
    ("burst_level_falloff", "abs", 0.04),
    ("tail_level", "abs", 0.08),
    ("tail_decay_ms", "rel", 0.10),
    ("bp_hz", "rel", 0.08),
    ("bp_q", "rel", 0.15),
    ("hp_hz", "rel", 0.10),
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
    resolved = resolve_clap_params(base)
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
        lo = _grid_up(max(lo, props[field]["minimum"]))
        hi = _grid_down(min(hi, props[field]["maximum"]))
        if hi < lo:
            raise ClapParamsError(f"Variant {index} of seed {seed}: empty range for {field}.")
        u = unit_offset(seed, index, field)
        out[field] = round(lo + (u + 1.0) / 2.0 * (hi - lo), DECIMALS)
    out["seed"] = derived_seed(seed, index)
    return resolve_clap_params(out)


def make_variants(base: dict[str, Any], count: int) -> list[dict[str, Any]]:
    return [make_variant(base, i) for i in range(count)]
