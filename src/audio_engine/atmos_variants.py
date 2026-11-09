"""Deterministic atmos variants around a base parameter set (issue #529).

Variant 0 is the base; variant ``i >= 1`` only gets its own seed (SHA-256 of the base seed and
the index, as the other ``*_variants`` modules): new noise, new partial phases and drift curves,
a new grain plan and a new smooth_random movement. Nothing else changes, so a variant keeps the
loop length, the tempo, the note and therefore the tuning check (rule C) of the base. Every
variant is validated by :func:`~audio_engine.atmos.resolve_atmos_params`.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .atmos import BATCH_ONLY_PARAMS, resolve_atmos_params

SALT = b"abeltongod-atmos-variant/v1:"
# (field, mode, half width) as the other *_variants.SPREAD tables (read by the GUI's main-knob
# scoring): atmos variants move no field, only the seed.
SPREAD: tuple[tuple[str, str, float], ...] = ()


def derived_seed(base_seed: int, index: int) -> int:
    digest = hashlib.sha256(SALT + f"{int(base_seed)}:{int(index)}".encode()).digest()
    return int.from_bytes(digest[:4], "big")


def make_variant(base: dict[str, Any], index: int) -> dict[str, Any]:
    """Resolved parameters of variant ``index`` (0 = the base)."""
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise ValueError(f"variant index must be an int >= 0, got {index!r}")
    resolved = resolve_atmos_params(base)
    for key in BATCH_ONLY_PARAMS:
        resolved.pop(key, None)
    if index == 0:
        return resolved
    out = resolve_atmos_params({**resolved, "seed": derived_seed(resolved["seed"], index)})
    for key in BATCH_ONLY_PARAMS:
        out.pop(key, None)
    return out


def make_variants(base: dict[str, Any], count: int) -> list[dict[str, Any]]:
    return [make_variant(base, i) for i in range(count)]
