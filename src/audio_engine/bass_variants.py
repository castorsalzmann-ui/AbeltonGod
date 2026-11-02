"""Deterministic bass variants around a base parameter set (issue #328).

Same scheme as the hat (:mod:`audio_engine.hat_variants`): variant 0 is the base; variant
``i >= 1`` gets its own seed and moves each field of :data:`SPREAD` by an offset from its own
SHA-256 hash, drawn inside the intersection of the spread box and the contract range, rounded to
4 decimals, never clamped. The note, the oscillator levels, the gate and the release are never
moved (the pitch and the length of a bass are not variation). The cross-field rules stay true
by construction: ``lp_env_amount`` is drawn first with an upper end that keeps
``lp_hz * 2^amount < 0.45 sr`` for the lowest ``lp_hz`` of the box, then ``lp_hz`` is drawn between
``1.2 * hp_hz`` and the limit of the drawn amount. A field that is 0 in the base stays 0.
Every variant is validated by :func:`~audio_engine.bass.resolve_bass_params`.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

from .bass import (
    BATCH_ONLY_PARAMS,
    LP_OVER_HP,
    PARTIAL_LIMIT,
    BassParamsError,
    _schema,
    resolve_bass_params,
)
from .variants import DECIMALS, _grid_down, _grid_up

SALT = b"abeltongod-bass-variant/v1:"

# (field, half width relative to the value). Order matters: lp_env_amount before lp_hz.
SPREAD: tuple[tuple[str, float], ...] = (
    ("lp_env_amount", 0.10),
    ("lp_hz", 0.10),
    ("lp_env_decay_ms", 0.10),
    ("lp_q", 0.05),
    ("drive", 0.15),
)
STRICT = 1e-3  # Hz margin that keeps "< 0.45 sr" strict after rounding


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
    resolved = resolve_bass_params(base)
    for key in BATCH_ONLY_PARAMS:
        resolved.pop(key, None)
    if index == 0:
        return resolved
    props = _schema()["properties"]
    seed = resolved["seed"]
    limit = PARTIAL_LIMIT * resolved["sample_rate"]
    boxes: dict[str, tuple[float, float]] = {}
    for field, width in SPREAD:
        x = resolved[field]
        lo = _grid_up(max(x * (1 - width), props[field]["minimum"]))
        hi = _grid_down(min(x * (1 + width), props[field]["maximum"]))
        boxes[field] = (lo, hi)
    lp_lo = max(boxes["lp_hz"][0], _grid_up(LP_OVER_HP * resolved["hp_hz"]))
    boxes["lp_hz"] = (lp_lo, boxes["lp_hz"][1])
    a_cap = math.log2((limit - STRICT) / lp_lo)
    boxes["lp_env_amount"] = (boxes["lp_env_amount"][0], min(boxes["lp_env_amount"][1],
                                                           _grid_down(a_cap)))
    out = dict(resolved)
    for field, _ in SPREAD:
        lo, hi = boxes[field]
        if field == "lp_hz":
            hi = min(hi, _grid_down((limit - STRICT) / 2.0 ** out["lp_env_amount"]))
        if hi < lo:
            raise BassParamsError(f"Variant {index} of seed {seed}: empty range for {field}.")
        u = unit_offset(seed, index, field)
        out[field] = round(lo + (u + 1.0) / 2.0 * (hi - lo), DECIMALS)
    out["seed"] = derived_seed(seed, index)
    return resolve_bass_params(out)


def make_variants(base: dict[str, Any], count: int) -> list[dict[str, Any]]:
    return [make_variant(base, i) for i in range(count)]
