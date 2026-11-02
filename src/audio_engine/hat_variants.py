"""Deterministic hat variants around a base parameter set (issue #270).

Same scheme as the clap (:mod:`audio_engine.clap_variants`): variant 0 is the base; variant
``i >= 1`` gets its own seed and moves each field of :data:`SPREAD` by an offset from its own
SHA-256 hash, drawn inside the intersection of the spread box and the contract range (and of
the cross-field rule ``lp_hz > 1.2 * hp_hz`` for ``hp_hz``), rounded to 4 decimals, never
clamped. A ``length_ms`` the request did not give is derived again from the moved ``decay_ms``.
Every variant is validated by :func:`~audio_engine.hat.resolve_hat_params`.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .hat import BATCH_ONLY_PARAMS, HatParamsError, _schema, resolve_hat_params
from .variants import DECIMALS, _grid_down, _grid_up

SALT = b"abeltongod-hat-variant/v1:"

# (field, mode, half width). abs: x +- w · rel: x * (1 +- w).
SPREAD: tuple[tuple[str, str, float], ...] = (
    ("decay_ms", "rel", 0.10),
    ("hp_hz", "rel", 0.08),
    ("metal", "abs", 0.05),
    ("pitch_scale", "rel", 0.05),
    ("color", "abs", 0.10),
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
    resolved = resolve_hat_params(base)
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
        hi = min(hi, props[field]["maximum"])
        if field == "hp_hz":
            hi = min(hi, resolved["lp_hz"] / 1.2 - 0.001)  # lp_hz > 1.2 * hp_hz stays true
        hi = _grid_down(hi)
        if hi < lo:
            raise HatParamsError(f"Variant {index} of seed {seed}: empty range for {field}.")
        u = unit_offset(seed, index, field)
        out[field] = round(lo + (u + 1.0) / 2.0 * (hi - lo), DECIMALS)
    out["seed"] = derived_seed(seed, index)
    if "length_ms" not in base:
        out.pop("length_ms")
    return resolve_hat_params(out)


def make_variants(base: dict[str, Any], count: int) -> list[dict[str, Any]]:
    return [make_variant(base, i) for i in range(count)]
