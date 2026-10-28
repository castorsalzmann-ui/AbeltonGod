"""Deterministic kick variants around a base parameter set (Phase 01b, issue #3).

Variant 0 is the base itself: the same resolved parameters, so the same bytes as rendering the
base alone (research note P1: the best-balanced kick is never gated, variants add range).

Variant ``i >= 1``:

- gets its own seed, :func:`derived_seed` = the first 4 bytes (big-endian) of
  ``SHA-256(SALT + "<base seed>:<i>")``, so its click noise changes too;
- moves each field of :data:`SPREAD` by an offset drawn from its own hash,
  :func:`unit_offset` = 53 bits of ``SHA-256(SALT + "<base seed>:<i>:<field>")`` mapped to
  ``[-1, 1)``. One hash per field: adding a field later never shifts the others. No NumPy or
  global RNG is involved, so the values are identical on every platform.

Each offset is drawn uniformly inside the intersection of the field's spread box and its
contract range (and, for the fields below, the extra limits), and rounded to 4 decimals. A
value is never clamped, so nothing piles up at an edge. Extra limits:

- ``drive`` only varies if the base drive is > 0, and then stays >= 0.0001: a clean base gives
  clean variants, a driven base gives driven variants.
- ``pitch_start_hz`` stays >= the variant's ``pitch_end_hz``.
- ``pitch_decay_ms``: if the base follows the pitch-settle guideline
  (:func:`audio_engine.params.pitch_settles`), the upper limit is the variant's own
  :func:`~audio_engine.params.max_settled_pitch_decay_ms` (rounded down to 4 decimals), so every
  variant follows it too. If that leaves the spread box empty (possible for a base whose
  pitch barely drops, where the other offsets shrink the allowed time constant a lot), the
  interval becomes ``[0.8 * max, max]`` (still inside the guideline and the contract); if even
  the contract minimum does not settle, :class:`VariantError` is raised.

Fields not in :data:`SPREAD` (``length_ms``, ``amp_attack_ms``, ``sample_rate``, ``bit_depth``,
``peak_ceiling_dbfs``, ``bpm``, ``preset``, ``schema_version``) are copied unchanged. Every
variant is validated by :func:`~audio_engine.params.resolve_kick_params` (rejected, never
clamped).
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

from .kick import BATCH_ONLY_PARAMS
from .params import (
    KICK_SCHEMA_FILE,
    KickParamsError,
    load_schema,
    max_settled_pitch_decay_ms,
    pitch_settles,
    resolve_kick_params,
)

SALT = b"abeltongod-kick-variant/v1:"
DECIMALS = 4
MIN_DRIVE_OF_DRIVEN_VARIANT = 1e-4

# (field, mode, half width). abs: x +- w · rel: x * (1 +- w) · oct: x * 2 ** (+-w).
# Order matters only for the dependencies: pitch_end_hz before pitch_start_hz, and every field
# that max_settled_pitch_decay_ms reads before pitch_decay_ms. The drawn offset of a field
# depends only on (base seed, i, field), never on this order.
SPREAD: tuple[tuple[str, str, float], ...] = (
    ("click_level", "abs", 0.12),
    ("click_tone_hz", "oct", 0.5),
    ("pitch_end_hz", "rel", 0.04),
    ("pitch_start_hz", "rel", 0.10),
    ("amp_decay_ms", "rel", 0.10),
    ("drive", "abs", 0.05),
    ("tone", "abs", 0.10),
    ("pitch_decay_ms", "rel", 0.20),
)
# When the guideline empties the pitch_decay_ms spread box, this fraction of the guideline
# maximum is the lower end of the fallback interval.
SETTLE_FALLBACK_FRACTION = 0.8


class VariantError(KickParamsError):
    """A variant cannot be made from these base parameters (e.g. no value settles)."""


def derived_seed(base_seed: int, index: int) -> int:
    """Seed of variant ``index`` (>= 1): first 4 bytes of SHA-256, big-endian (0 … 2**32 - 1)."""
    digest = hashlib.sha256(SALT + f"{int(base_seed)}:{int(index)}".encode()).digest()
    return int.from_bytes(digest[:4], "big")


def unit_offset(base_seed: int, index: int, field: str) -> float:
    """Uniform value in ``[-1, 1)`` from 53 bits of SHA-256, one hash per field."""
    digest = hashlib.sha256(SALT + f"{int(base_seed)}:{int(index)}:{field}".encode()).digest()
    return (int.from_bytes(digest[:8], "big") >> 11) / 2.0**52 - 1.0


def spread_box(field: str, value: float) -> tuple[float, float]:
    """The spread interval of ``field`` around ``value``, before any other limit."""
    mode, width = {f: (m, w) for f, m, w in SPREAD}[field]
    if mode == "abs":
        return value - width, value + width
    if mode == "rel":
        return value * (1 - width), value * (1 + width)
    return value * 2.0**-width, value * 2.0**width


def make_variant(base: dict[str, Any], index: int) -> dict[str, Any]:
    """Resolved parameters of variant ``index`` (0 = the base) for the base parameter set."""
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise ValueError(f"variant index must be an int >= 0, got {index!r}")
    resolved = resolve_kick_params(base)
    for key in BATCH_ONLY_PARAMS:
        resolved.pop(key, None)
    if index == 0:
        return resolved

    props = load_schema(KICK_SCHEMA_FILE)["properties"]
    settles = pitch_settles(resolved)
    seed = resolved["seed"]
    out = dict(resolved)
    for field, _, _ in SPREAD:
        x = resolved[field]
        if field == "drive" and x == 0:
            continue  # a clean base stays clean
        lo, hi = spread_box(field, x)
        lo, hi = max(lo, props[field]["minimum"]), min(hi, props[field]["maximum"])
        if field == "drive":
            lo = max(lo, MIN_DRIVE_OF_DRIVEN_VARIANT)
        if field == "pitch_start_hz":
            lo = max(lo, out["pitch_end_hz"])
        lo, hi = _grid_up(lo), _grid_down(hi)  # rounding the draw can then never leave [lo, hi]
        if field == "pitch_decay_ms" and settles:
            limit = _grid_down(max_settled_pitch_decay_ms(out))
            if limit < props[field]["minimum"]:
                raise VariantError(
                    f"Variant {index} of seed {seed}: no pitch_decay_ms in the contract range "
                    f"follows the pitch-settle guideline (max {limit} ms)."
                )
            hi = min(hi, limit)
            if hi < lo:
                lo = max(_grid_up(SETTLE_FALLBACK_FRACTION * hi), props[field]["minimum"])
        if hi < lo:
            raise VariantError(
                f"Variant {index} of seed {seed}: empty range for {field} ({lo} > {hi})."
            )
        u = unit_offset(seed, index, field)
        out[field] = round(lo + (u + 1.0) / 2.0 * (hi - lo), DECIMALS)
    out["seed"] = derived_seed(seed, index)
    return resolve_kick_params(out)


def make_variants(base: dict[str, Any], count: int) -> list[dict[str, Any]]:
    """Variants ``0 … count - 1``. All are made (and validated) before the caller writes."""
    return [make_variant(base, i) for i in range(count)]


def _grid_down(value: float) -> float:
    """Largest multiple of 10**-DECIMALS (as a rounded float) that is <= ``value``."""
    step = 10.0**-DECIMALS
    out = round(math.floor(value / step) * step, DECIMALS)
    while out > value:
        out = round(out - step, DECIMALS)
    return out


def _grid_up(value: float) -> float:
    """Smallest multiple of 10**-DECIMALS (as a rounded float) that is >= ``value``."""
    step = 10.0**-DECIMALS
    out = round(math.ceil(value / step) * step, DECIMALS)
    while out < value:
        out = round(out + step, DECIMALS)
    return out
