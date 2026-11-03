"""Rim voice (Phase 06, issue #321): two damped sine partials, high-pass, optional noise click.

Contract: ``contracts/rim-params.schema.json`` v0.1. Signal path (all float64, mono; ``t`` is
measured from the first sound sample, ``m`` = file samples minus the offset):

1. Partials, both with phase 0 (sine) and no attack:
   ``sin(2 pi f1 t) * e1(t)`` and ``level2 * sin(2 pi f1 f2_ratio t) * e2(t)``, with the kick's
   :func:`kick._amp_envelope` (exponential, 60 dB in ``decay1_ms`` / ``decay2_ms``). At
   ``level2`` 0 the upper partial is not computed (single partial, clave case).
2. High-pass at ``hp_hz`` (one RBJ section, Q 1/sqrt 2) on the partial sum. The click is not
   filtered by it.
3. Click (``click_level`` > 0): white noise from sub-stream 0 of the seed, high-passed at
   :data:`CLICK_HP_HZ` and low-passed at ``0.45 * sample_rate`` (RBJ sections), scaled to unit
   RMS over the sound and then to ``click_level``, times an exponential envelope of ``click_ms``
   (60 dB). Unit RMS noise against a unit-amplitude lower partial is this module's reading of
   "scaled by click_level relative to the lower partial's amplitude at t = 0" (contract
   $comment point 6). At ``click_level`` 0 no noise is drawn: the output is seed-independent.
4. ``drive`` > 0: scaled to peak 1, then the kick's anti-aliased saturation.
5. First sample 0, 5 ms fade-out at the file end, mean removal, peak ceiling on the quantised
   file.
6. ``offset_ms`` of leading silence, ``polarity``.

Same resolved parameters give the same samples (no clock, no global RNG). ``variants`` is a
batch-only field and is not part of the resolved form after :func:`render_rim`.
"""

from __future__ import annotations

import math
import numbers
from functools import cache
from typing import Any

import numpy as np
from jsonschema import Draft202012Validator

from .dsp import rbj_highpass, rbj_lowpass, substreams
from .kick import FADE_OUT_MS, _amp_envelope, _drive, _fade_out, _normalise, _remove_mean
from .params import CONTRACTS_DIR, _error_line, _to_python, load_schema

RIM_NAME = "abeltongod-audio-engine-rim"
# Bump on every change that alters rendered bytes (D-013 per category, D-025); update the golden
# hashes in tests/audio_engine/test_rim.py in the same PR.
RIM_VERSION = "0.1.0"
RIM_SCHEMA_FILE = CONTRACTS_DIR / "rim-params.schema.json"

CLICK_HP_HZ = 4000.0  # contract $comment point 6
HP_F1_RATIO = 0.8  # contract $comment point 1: hp_hz < HP_F1_RATIO * f1_hz
INTEGER_FIELDS = ("seed", "variants", "sample_rate", "bit_depth", "polarity")
BATCH_ONLY_PARAMS = ("variants",)
CLICK_STREAM = 0
N_STREAMS = 1


class RimParamsError(ValueError):
    """Raised when rim parameters do not match the contract; the message lists every problem."""


@cache
def _schema() -> dict[str, Any]:
    return load_schema(RIM_SCHEMA_FILE)


def resolve_rim_params(params: dict[str, Any]) -> dict[str, Any]:
    """Validate against the contract and return the resolved form (new dict, defaults filled).

    Unknown, missing, out-of-range or non-finite fields and ``hp_hz >= 0.8 * f1_hz`` are
    rejected, never clamped. Resolving a resolved form returns it unchanged.
    """
    if not isinstance(params, dict):
        raise RimParamsError(f"Rim parameters must be an object, got {type(params).__name__}.")
    params = {k: _to_python(v) for k, v in params.items()}
    schema = _schema()
    lines = [
        f"- {k}: must be int or float, got {type(v).__name__} {v!r}"
        for k, v in sorted(params.items())
        if isinstance(v, numbers.Number) and not isinstance(v, int | float)
    ]
    lines += [
        f"- {k}: must be a finite number, got {v!r}"
        for k, v in params.items()
        if isinstance(v, float) and not math.isfinite(v)
    ]
    if not lines:
        validator = Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(params), key=lambda e: list(e.path))
        lines = [_error_line(e) for e in errors]
    resolved = dict(params)
    if not lines:
        for key in INTEGER_FIELDS:
            if isinstance(resolved.get(key), float):
                resolved[key] = int(resolved[key])
        for name, prop in schema["properties"].items():
            if name not in resolved and "default" in prop:
                resolved[name] = prop["default"]
        if not resolved["hp_hz"] < HP_F1_RATIO * resolved["f1_hz"]:
            lines.append(
                f"- hp_hz: must be less than 0.8 * f1_hz = {HP_F1_RATIO * resolved['f1_hz']:g}, "
                f"got {resolved['hp_hz']!r}"
            )
    if lines:
        raise RimParamsError("Invalid rim parameters:\n" + "\n".join(lines))
    return resolved


def render_rim(params: dict[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    """Render one rim. Returns ``(audio, resolved_params)``; audio is float64 in [-1, 1]."""
    p = resolve_rim_params(params)
    for key in BATCH_ONLY_PARAMS:
        p.pop(key, None)
    return render_resolved(p), p


def file_samples(p: dict[str, Any]) -> int:
    return int(round(p["length_ms"] * int(p["sample_rate"]) / 1000.0))


def offset_samples(p: dict[str, Any]) -> int:
    return int(round(p["offset_ms"] * int(p["sample_rate"]) / 1000.0))


def _partials(p: dict[str, Any], t: np.ndarray) -> np.ndarray:
    f1 = p["f1_hz"]
    x = np.sin(2.0 * math.pi * f1 * t) * _amp_envelope(t, 0.0, p["decay1_ms"] / 1000.0)
    if p["level2"] > 0.0:
        upper = np.sin(2.0 * math.pi * f1 * p["f2_ratio"] * t)
        x = x + p["level2"] * upper * _amp_envelope(t, 0.0, p["decay2_ms"] / 1000.0)
    return x


def _click(p: dict[str, Any], t: np.ndarray) -> np.ndarray:
    sr = int(p["sample_rate"])
    noise = substreams(p["seed"], N_STREAMS)[CLICK_STREAM].standard_normal(len(t))
    y = rbj_lowpass(rbj_highpass(noise, sr, CLICK_HP_HZ), sr, 0.45 * sr)
    rms = math.sqrt(float(np.mean(y * y)))
    if rms <= 0.0:
        raise ValueError("the click has no energy")
    return p["click_level"] * (y / rms) * _amp_envelope(t, 0.0, p["click_ms"] / 1000.0)


def render_resolved(p: dict[str, Any]) -> np.ndarray:
    """Render already resolved parameters (no validation)."""
    sr = int(p["sample_rate"])
    n = file_samples(p)
    n_off = offset_samples(p)
    m = n - n_off
    t = np.arange(m, dtype=np.float64) / sr
    x = rbj_highpass(_partials(p, t), sr, p["hp_hz"])
    if p["click_level"] > 0.0:
        x = x + _click(p, t)
    if m:
        x[0] = 0.0
    if p["drive"] > 0:
        peak = float(np.max(np.abs(x)))
        if peak > 0.0:
            x = _drive(x / peak, p["drive"])
    x = _fade_out(x, sr, FADE_OUT_MS)
    x = _remove_mean(x)
    x = _normalise(x, p["peak_ceiling_dbfs"], p["bit_depth"])
    if n_off:
        x = np.concatenate([np.zeros(n_off), x])
    if p["polarity"] == -1:
        x = -x
    return x
