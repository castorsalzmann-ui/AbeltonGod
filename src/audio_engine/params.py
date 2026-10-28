"""Validation and default resolution for kick parameters (contracts/kick-params.schema.json)."""

from __future__ import annotations

import json
import math
import numbers
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np
from jsonschema import Draft202012Validator

CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "contracts"
KICK_SCHEMA_FILE = CONTRACTS_DIR / "kick-params.schema.json"
METADATA_SCHEMA_FILE = CONTRACTS_DIR / "sample-metadata.schema.json"

# Fields used as Python ints (array sizes, RNG seed, WAV header).
INTEGER_FIELDS = ("seed", "variants", "sample_rate", "bit_depth")


class KickParamsError(ValueError):
    """Raised when kick parameters do not match the contract. The message lists every problem."""


@cache
def load_schema(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Contract not found: {path}. The audio engine reads schemas from the repo's "
            "contracts/ folder; install the project in editable mode (pip install -e .)."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_kick_params(params: dict[str, Any]) -> dict[str, Any]:
    """Validate ``params`` against the contract and return a new dict with all defaults filled in.

    Out-of-range, missing, unknown or non-finite (NaN, Infinity) fields are rejected, never
    clamped or dropped. Numbers must be ``int`` or ``float`` (NumPy scalars are converted
    first); ``Decimal``, ``Fraction`` and ``complex`` are rejected. All problems are listed
    together. Whole-number floats for integer fields (``7.0`` for
    ``seed``) are accepted, as JSON Schema does, and converted to ``int`` losslessly.
    """
    if not isinstance(params, dict):
        raise KickParamsError(f"Kick parameters must be an object, got {type(params).__name__}.")
    # NumPy scalars (np.float32, np.int64 …) become plain Python numbers first, so the finite
    # check below and JSON serialisation of the sidecar treat them like any other number.
    # np.longdouble.item() stays a NumPy type on Linux, so floating types go through float().
    params = {k: _to_python(v) for k, v in params.items()}
    # Only int and float are numbers here. Decimal, Fraction and complex pass (or crash) the
    # schema's number check and then fail deep inside the DSP; JSON input never produces them.
    # The schema check cannot compare complex values, so it sees a placeholder 0 for these keys
    # (the key stays present, so "required" and "unknown field" are still reported) and its
    # errors about the placeholder itself are dropped.
    exotic = {
        key
        for key, value in params.items()
        if isinstance(value, numbers.Number) and not isinstance(value, int | float)
    }
    lines = [
        f"- {key}: must be int or float, got {type(params[key]).__name__} {params[key]!r}"
        for key in sorted(exotic)
    ]
    lines += [
        f"- {key}: must be a finite number, got {value!r}"
        for key, value in params.items()
        if isinstance(value, float) and not math.isfinite(value)
    ]
    schema = load_schema(KICK_SCHEMA_FILE)
    checked = {k: (0 if k in exotic else v) for k, v in params.items()}
    errors = sorted(Draft202012Validator(schema).iter_errors(checked), key=lambda e: list(e.path))
    for err in errors:
        if err.path and err.path[0] in exotic:
            continue
        where = ".".join(str(p) for p in err.path) or "(root)"
        lines.append(f"- {where}: {err.message}")
    if lines:
        raise KickParamsError("Invalid kick parameters:\n" + "\n".join(lines))

    resolved = dict(params)
    for key in INTEGER_FIELDS:
        if isinstance(resolved.get(key), float):
            resolved[key] = int(resolved[key])
    for name, prop in schema["properties"].items():
        if name not in resolved and "default" in prop:
            resolved[name] = prop["default"]
    if resolved["pitch_end_hz"] > resolved["pitch_start_hz"]:
        raise KickParamsError(
            "Invalid kick parameters:\n- pitch_end_hz must not be higher than pitch_start_hz "
            f"({resolved['pitch_end_hz']} > {resolved['pitch_start_hz']})"
        )
    return resolved


# Pitch-settle guideline (issue #7, user decision 2026-10-28). Not enforced by the schema:
# presets (#3) and the Claude orchestrator (Phase 04b) call max_settled_pitch_decay_ms().
PITCH_SETTLE_LEVEL_DB = 20.0
PITCH_SETTLE_TOLERANCE = 0.05


def max_settled_pitch_decay_ms(params: dict[str, Any]) -> float:
    """Largest ``pitch_decay_ms`` for which the body pitch is within 5 % of ``pitch_end_hz``
    by the time the level has fallen 20 dB (or at ``length_ms``, if the file ends earlier).

    With the contract's pitch curve ``f(t) = f_end + (f_start - f_end) * exp(-t / tau)`` the
    condition ``f(t) <= 1.05 * f_end`` gives ``tau <= t / ln((f_start - f_end) / (0.05 * f_end))``.
    ``t = amp_attack_ms + amp_decay_ms / 3`` (−20 dB of a 60 dB decay), capped at ``length_ms``.
    ``pitch_decay_ms`` in ``params`` is ignored. The result is capped at the schema maximum; it
    can be below the schema minimum (2 ms), which means no allowed value settles in time.
    """
    p = resolve_kick_params(params)
    limit = float(load_schema(KICK_SCHEMA_FILE)["properties"]["pitch_decay_ms"]["maximum"])
    t_ms = min(
        p["amp_attack_ms"] + p["amp_decay_ms"] * PITCH_SETTLE_LEVEL_DB / 60.0, p["length_ms"]
    )
    drop = p["pitch_start_hz"] - p["pitch_end_hz"]
    allowed = PITCH_SETTLE_TOLERANCE * p["pitch_end_hz"]
    if drop <= allowed:
        return limit
    return min(limit, t_ms / math.log(drop / allowed))


def pitch_settles(params: dict[str, Any]) -> bool:
    """True if ``pitch_decay_ms`` follows the guideline of :func:`max_settled_pitch_decay_ms`."""
    return resolve_kick_params(params)["pitch_decay_ms"] <= max_settled_pitch_decay_ms(params)


def _to_python(value: Any) -> Any:
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.generic):
        return value.item()
    return value
