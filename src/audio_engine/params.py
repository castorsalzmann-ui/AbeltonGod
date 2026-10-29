"""Validation and default resolution for kick parameters (contracts/kick-params.schema.json).

kick-params 0.2 and 0.3 are rendered. The resolved form (what :func:`resolve_kick_params`
returns, the sidecar stores and a re-render reads) follows the schema root description:
every default is filled, ``tail_note`` is replaced by the derived ``pitch_end_hz``,
``length_beats`` by the derived ``length_ms``, and an ``amp_decay_ms`` derived under
``length_beats`` is stored as ``amp_decay_ms``. The v0.3 defaults are filled only into 0.3
documents, so a 0.2 document resolves to exactly the keys it had before v0.3 (same sidecar
bytes).
"""

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

# Fields used as Python ints (array sizes, RNG seed, WAV header, note table, sign).
INTEGER_FIELDS = ("seed", "variants", "sample_rate", "bit_depth", "tail_note", "polarity")

# kick-params versions this engine renders (#120 implements 0.3).
RENDERED_SCHEMA_VERSIONS = ("0.2", "0.3")
V03 = "0.3"

# Inputs that the resolved form replaces by derived values (schema root description).
DERIVED_INPUTS = ("tail_note", "length_beats")

# tail_note -> pitch_end_hz: 440 * 2 ** ((note - 69) / 12), written as the correctly rounded
# double of the exact value (50-digit decimal arithmetic). ``2.0 ** x`` goes through the
# platform's libm pow, which was 1-2 ULP off for 9 of these notes on Linux; a table gives the
# same bits on every platform (D-005).
NOTE_HZ: dict[int, float] = {
    23: 30.867706328507758, 24: 32.70319566257483, 25: 34.64782887210901,
    26: 36.70809598967595, 27: 38.890872965260115, 28: 41.20344461410874,
    29: 43.653528929125486, 30: 46.2493028389543, 31: 48.99942949771866,
    32: 51.91308719749314, 33: 55.0, 34: 58.27047018976124,
    35: 61.735412657015516, 36: 65.40639132514966, 37: 69.29565774421802,
    38: 73.4161919793519, 39: 77.78174593052023, 40: 82.40688922821748,
    41: 87.30705785825097, 42: 92.4986056779086, 43: 97.99885899543732,
    44: 103.82617439498628, 45: 110.0, 46: 116.54094037952248,
}

# The length_ms range a length_beats request must land in (schema: length_ms minimum/maximum).
_LENGTH_FIELD = "length_ms"


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


def v03_properties(schema: dict[str, Any] | None = None) -> dict[str, Any]:
    """The v0.3 field definitions: the ``then`` properties of the schema_version 0.3 branch."""
    schema = schema or load_schema(KICK_SCHEMA_FILE)
    for branch in schema.get("allOf", ()):
        if branch.get("if") == {"properties": {"schema_version": {"const": V03}}}:
            return branch["then"]["properties"]
    raise KeyError("kick-params schema has no schema_version 0.3 branch")


def resolve_kick_params(params: dict[str, Any]) -> dict[str, Any]:
    """Validate ``params`` against the contract and return its resolved form (new dict).

    Out-of-range, missing, unknown or non-finite (NaN, Infinity) fields are rejected, never
    clamped or dropped. Numbers must be ``int`` or ``float`` (NumPy scalars are converted
    first); ``Decimal``, ``Fraction`` and ``complex`` are rejected. All schema problems are
    listed together. Whole-number floats for integer fields (``7.0`` for ``seed``, ``33.0``
    for ``tail_note``, ``-1.0`` for ``polarity``) are accepted, as JSON Schema does, and
    converted to ``int`` losslessly.

    A ``length_beats`` request is checked against the -60 dB rule of the contract (see
    :mod:`audio_engine.length`); that needs renders, so it runs only after every other check
    passed. Resolving a resolved form returns it unchanged and renders nothing.
    """
    if not isinstance(params, dict):
        raise KickParamsError(f"Kick parameters must be an object, got {type(params).__name__}.")
    # NumPy scalars (np.float32, np.int64 …) become plain Python numbers first, so the finite
    # check below and JSON serialisation of the sidecar treat them like any other number.
    # np.longdouble.item() stays a NumPy type on Linux, so floating types go through float().
    params = {k: _to_python(v) for k, v in params.items()}
    schema = load_schema(KICK_SCHEMA_FILE)
    lines = _schema_problems(params, schema)
    if lines:
        raise KickParamsError("Invalid kick parameters:\n" + "\n".join(lines))

    resolved = dict(params)
    for key in INTEGER_FIELDS:
        if isinstance(resolved.get(key), float):
            resolved[key] = int(resolved[key])
    is_v03 = resolved["schema_version"] == V03
    note = resolved.pop("tail_note", None)
    beats = resolved.pop("length_beats", None)
    decay_given = "amp_decay_ms" in resolved
    if note is not None:
        resolved["pitch_end_hz"] = NOTE_HZ[note]
    if beats is not None:
        resolved[_LENGTH_FIELD] = beats * 60000 / resolved["bpm"]
    for name, prop in schema["properties"].items():
        if name == "amp_decay_ms" and beats is not None:
            continue  # derived below (rule a), the default 320 is not used
        if name not in resolved and "default" in prop:
            resolved[name] = prop["default"]
    if is_v03:
        for name, prop in v03_properties(schema).items():
            if name not in resolved and "default" in prop:
                resolved[name] = prop["default"]

    problems = []
    if beats is not None:
        lo = schema["properties"][_LENGTH_FIELD]["minimum"]
        hi = schema["properties"][_LENGTH_FIELD]["maximum"]
        ms = resolved[_LENGTH_FIELD]
        if not lo <= ms <= hi:
            bpm = resolved["bpm"]
            problems.append(
                f"- length_beats: {beats} beats at {bpm} BPM give {ms:.4g} ms, outside the file "
                f"length range {lo} ... {hi} ms; at {bpm} BPM length_beats must lie in "
                f"{lo * bpm / 60000:.4g} ... {hi * bpm / 60000:.4g}"
            )
    if resolved["pitch_end_hz"] > resolved["pitch_start_hz"]:
        if note is not None:
            problems.append(
                f"- tail_note {note} ({resolved['pitch_end_hz']:.4f} Hz) must not be higher "
                f"than pitch_start_hz ({resolved['pitch_start_hz']})"
            )
        else:
            problems.append(
                "- pitch_end_hz must not be higher than pitch_start_hz "
                f"({resolved['pitch_end_hz']} > {resolved['pitch_start_hz']})"
            )
    if problems:
        raise KickParamsError("Invalid kick parameters:\n" + "\n".join(problems))

    if beats is not None:
        from .length import apply_length_rule  # renders; imported late (length -> kick -> here)

        error = apply_length_rule(resolved, beats, decay_given)
        if error:
            raise KickParamsError("Invalid kick parameters:\n- " + error)
    return resolved


def _schema_problems(params: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    """Every contract problem of ``params`` as one line each (empty list = valid)."""
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
    version = params.get("schema_version")
    # Unknown fields are reported here instead of by unevaluatedProperties: when the 0.3
    # branch fails (e.g. tail_note 22), JSON Schema drops its annotations and reports every
    # v0.3 key as "unexpected" next to the real error (PR #114 review). The allowed set is
    # exactly what the schema evaluates when that branch passes, so validity is unchanged.
    v03 = v03_properties(schema)
    allowed = set(schema["properties"]) | (set(v03) if version == V03 else set())
    not_allowed = sorted(k for k in params if k not in allowed)
    early = [k for k in not_allowed if k in v03]
    unknown = [k for k in not_allowed if k not in v03]
    if early:
        lines.append(
            f"- {', '.join(early)}: kick-params v0.3 field(s), only allowed with "
            f"schema_version \"0.3\" (this document has schema_version {version!r})"
        )
    if unknown:
        lines.append(f"- (root): unknown field(s) {', '.join(repr(k) for k in unknown)}")
    checked = {k: (0 if k in exotic else v) for k, v in params.items()}
    errors = sorted(Draft202012Validator(schema).iter_errors(checked), key=lambda e: list(e.path))
    for err in errors:
        if err.validator == "unevaluatedProperties":
            continue  # reported above
        if err.path and err.path[0] in exotic:
            continue
        lines.append(_error_line(err))
    if version in schema["properties"]["schema_version"]["enum"] and (
        version not in RENDERED_SCHEMA_VERSIONS
    ):
        lines.append(
            f"- schema_version: kick-params {version} is specified in the contract but not "
            f"implemented by this engine (renders {', '.join(RENDERED_SCHEMA_VERSIONS)})"
        )
    return lines


def _error_line(err: Any) -> str:
    """One readable line per schema error. These go back to Claude (D-002), so the two v0.3
    exclusions and the bpm dependency get their own wording instead of the raw JSON Schema
    text ("... should not be valid under {'required': [...]}")."""
    path = list(err.schema_path)
    if err.validator == "not" and "dependentSchemas" in path:
        field = path[path.index("dependentSchemas") + 1]
        other = ", ".join(err.validator_value.get("required", ()))
        derived = {"tail_note": "pitch_end_hz", "length_beats": "length_ms"}.get(field, other)
        return (
            f"- {field}: cannot be combined with {other}; {field} sets {derived} itself, "
            "so give only one of the two"
        )
    if err.validator == "dependentRequired":
        parts = []
        for field, needs in err.validator_value.items():
            missing = [k for k in needs if field in err.instance and k not in err.instance]
            if missing:
                why = " (beats become milliseconds at bpm)" if field == "length_beats" else ""
                parts.append(f"- {field}: requires {', '.join(missing)}{why}")
        return "\n".join(parts) or f"- (root): {err.message}"
    where = ".".join(str(p) for p in err.path) or "(root)"
    return f"- {where}: {err.message}"


def tail_note_of(params: dict[str, Any]) -> int | None:
    """The MIDI note of ``pitch_end_hz`` in resolved parameters, if it is exactly one of the
    ``tail_note`` frequencies (:data:`NOTE_HZ`), else ``None``. For display (library, Claude).

    The resolved form keeps no trace of ``tail_note`` (contract), so a plain ``pitch_end_hz``
    request with the same frequency (e.g. 55.0 = note 33) gives the same note: it is the same
    kick (PR #114 review round 2, nit 2). Exact equality, no tolerance: 41.2 is not note 28.
    """
    hz = params.get("pitch_end_hz")
    for note, note_hz in NOTE_HZ.items():
        if hz == note_hz:
            return note
    return None


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

    Exception, ``length_beats`` requests (v0.3): their ``amp_decay_ms`` is derived from the
    rendered output, and that depends on ``pitch_decay_ms`` too (it moves the body phase at
    the -60 dB point). Measured on three requests (#120): the derived decay, and so this
    limit, moved by up to about 3 %, not monotonically, for ``pitch_decay_ms`` between 0.6
    and 1.0 times the limit. Check :func:`pitch_settles` on the final request.
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
