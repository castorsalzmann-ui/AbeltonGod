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


def _to_python(value: Any) -> Any:
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.generic):
        return value.item()
    return value
