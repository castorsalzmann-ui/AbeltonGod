"""Validation and default resolution for kick parameters (contracts/kick-params.schema.json)."""

from __future__ import annotations

import json
import math
from functools import cache
from pathlib import Path
from typing import Any

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
    clamped or dropped. Whole-number floats for integer fields (``7.0`` for ``seed``) are
    accepted, as JSON Schema does, and converted to ``int`` losslessly.
    """
    if not isinstance(params, dict):
        raise KickParamsError(f"Kick parameters must be an object, got {type(params).__name__}.")
    schema = load_schema(KICK_SCHEMA_FILE)
    lines = [
        f"- {key}: must be a finite number, got {value!r}"
        for key, value in params.items()
        if isinstance(value, float) and not math.isfinite(value)
    ]
    errors = sorted(Draft202012Validator(schema).iter_errors(params), key=lambda e: list(e.path))
    for err in errors:
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
