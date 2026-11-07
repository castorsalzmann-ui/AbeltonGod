"""Percussion voice (sprint W2, issue #475): conga, tom, shaker, cowbell, clave in one space.

Contract: ``contracts/perc-params.schema.json`` v0.1. The model picks the voice structure and
its base values (:data:`BASE_VALUES`, contract $comment point 2); ``tune_semitones``,
``decay_scale`` and ``attack_scale`` act relative to them. Signal path (all float64, mono; ``t``
is measured from the first sound sample, ``m`` = file samples minus the offset):

1. Voice, amplitude 1 before any filter (contract $comment point 3):
   ``tom`` / ``conga``: ``sin`` of the kick's analytic :func:`kick.body_phase` with
   ``f(t) = f0 + (f0 * bend_ratio - f0) * exp(-t / bend_ms)``, phase 0 at t = 0.
   ``cowbell``: ``0.5 *`` :func:`dsp.square_bank` at ``f0`` and ``f0 * 800 / 540`` (equal
   amplitude, phase 0), then the RBJ band-pass with 0 dB peak gain (:func:`dsp.biquad_bandpass`)
   at ``2600 * 2^(tune / 12)`` Hz, Q 1.4.
   ``clave``: ``sin(2 pi f0 t)``.
   ``shaker``: white noise from sub-stream :data:`SHAKER_STREAM`, band-pass at ``f0`` Q 1.5,
   RBJ high-pass at ``3000 * 2^(tune / 12)`` Hz, scaled to unit RMS.
2. Envelope: the kick's :func:`kick._amp_envelope` (linear attack, then exponential, 60 dB in
   t60 after the attack) with ``attack = base_attack_ms * attack_scale`` and
   ``t60 = base_decay_ms * decay_scale``.
3. Tick (not at shaker, only when ``tick_level`` > 0): white noise from sub-stream
   :data:`TICK_STREAM` over the first :data:`TICK_WINDOW_MS`, band-pass at ``tick_hz`` Q 1.2,
   scaled to unit RMS and to ``tick_level``, times an exponential envelope with 60 dB in
   :data:`TICK_DECAY_MS` from t = 0 (the same unit-RMS reading of "relative to the voice" as
   the rim click). The window ends where that envelope is 10^-15 (-300 dB).
4. ``hp_hz`` > 20: RBJ high-pass (Q 1/sqrt 2) on voice plus tick. 20 = no filter.
5. ``drive`` > 0: scaled to peak 1, then the kick's anti-aliased saturation.
6. First sample 0, 5 ms fade-out at the file end, mean removal, peak ceiling on the quantised
   file; then ``offset_ms`` of leading silence and ``polarity``.

Same resolved parameters give the same samples (no clock, no global RNG). ``variants`` is a
batch-only field and is not part of the resolved form after :func:`render_perc`.
"""

from __future__ import annotations

import math
import numbers
from functools import cache
from typing import Any

import numpy as np
from jsonschema import Draft202012Validator

from .dsp import biquad_bandpass, rbj_highpass, square_bank, substreams
from .kick import (
    FADE_OUT_MS,
    _amp_envelope,
    _drive,
    _fade_out,
    _normalise,
    _remove_mean,
    body_phase,
)
from .params import CONTRACTS_DIR, _error_line, _to_python, load_schema

PERC_NAME = "abeltongod-audio-engine-perc"
# Bump on every change that alters rendered bytes (D-013 per category, D-025); update the golden
# hashes in tests/audio_engine/test_perc.py in the same PR.
PERC_VERSION = "0.1.0"
PERC_SCHEMA_FILE = CONTRACTS_DIR / "perc-params.schema.json"

# model: (base_hz, base_decay_ms, base_attack_ms), contract $comment point 2
BASE_VALUES: dict[str, tuple[float, float, float]] = {
    "tom": (130.81, 300.0, 0.6),
    "conga": (261.63, 200.0, 0.6),
    "cowbell": (540.0, 120.0, 1.0),
    "clave": (2400.0, 30.0, 0.5),
    "shaker": (4500.0, 80.0, 12.0),
}
MEMBRANES = ("tom", "conga")
COWBELL_RATIO = 800.0 / 540.0
COWBELL_BP_HZ, COWBELL_BP_Q = 2600.0, 1.4
SHAKER_BP_Q = 1.5
SHAKER_HP_HZ = 3000.0
TICK_Q = 1.2
TICK_DECAY_MS = 6.0
TICK_WINDOW_MS = 30.0
HP_OFF_HZ = 20.0
TAIL_MS = FADE_OUT_MS  # default length: offset + attack + t60 + the fade (contract point 10)
MIN_LENGTH_MS = 20.0
INTEGER_FIELDS = ("seed", "variants", "sample_rate", "bit_depth", "polarity")
BATCH_ONLY_PARAMS = ("variants",)
TICK_STREAM = 0
SHAKER_STREAM = 1
N_STREAMS = 2


class PercParamsError(ValueError):
    """Raised when perc parameters do not match the contract; the message lists every problem."""


@cache
def _schema() -> dict[str, Any]:
    return load_schema(PERC_SCHEMA_FILE)


def tune_factor(p: dict[str, Any]) -> float:
    return 2.0 ** (p["tune_semitones"] / 12.0)


def f0_hz(p: dict[str, Any]) -> float:
    """Pitch of the voice: ``base_hz[model] * 2^(tune_semitones / 12)`` (contract point 1)."""
    return BASE_VALUES[p["model"]][0] * tune_factor(p)


def t60_ms(p: dict[str, Any]) -> float:
    return BASE_VALUES[p["model"]][1] * p["decay_scale"]


def attack_ms(p: dict[str, Any]) -> float:
    return BASE_VALUES[p["model"]][2] * p["attack_scale"]


def default_length_ms(p: dict[str, Any]) -> float:
    return max(MIN_LENGTH_MS, round(p["offset_ms"] + attack_ms(p) + t60_ms(p) + TAIL_MS, 6))


def resolve_perc_params(params: dict[str, Any]) -> dict[str, Any]:
    """Validate against the contract and return the resolved form (new dict, defaults filled).

    Unknown, missing, out-of-range or non-finite fields are rejected, never clamped. An omitted
    ``length_ms`` becomes ``offset_ms + attack + t60 + 5 ms`` (at least 20 ms). Resolving a
    resolved form returns it unchanged.
    """
    if not isinstance(params, dict):
        raise PercParamsError(f"Perc parameters must be an object, got {type(params).__name__}.")
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
    if lines:
        raise PercParamsError("Invalid perc parameters:\n" + "\n".join(lines))
    resolved = dict(params)
    for key in INTEGER_FIELDS:
        if isinstance(resolved.get(key), float):
            resolved[key] = int(resolved[key])
    for name, prop in schema["properties"].items():
        if name not in resolved and "default" in prop:
            resolved[name] = prop["default"]
    if "length_ms" not in resolved:
        resolved["length_ms"] = default_length_ms(resolved)
    return resolved


def render_perc(params: dict[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    """Render one perc hit. Returns ``(audio, resolved_params)``; audio is float64 in [-1, 1]."""
    p = resolve_perc_params(params)
    for key in BATCH_ONLY_PARAMS:
        p.pop(key, None)
    return render_resolved(p), p


def file_samples(p: dict[str, Any]) -> int:
    return int(round(p["length_ms"] * int(p["sample_rate"]) / 1000.0))


def offset_samples(p: dict[str, Any]) -> int:
    return int(round(p["offset_ms"] * int(p["sample_rate"]) / 1000.0))


def _unit_rms(y: np.ndarray, what: str) -> np.ndarray:
    rms = math.sqrt(float(np.mean(y * y))) if len(y) else 0.0
    if rms <= 0.0:
        raise ValueError(f"the {what} has no energy")
    return y / rms


def _voice(p: dict[str, Any], t: np.ndarray, streams: list[np.random.Generator]) -> np.ndarray:
    """The model's oscillator (and its own filters), amplitude 1 before filtering."""
    sr = int(p["sample_rate"])
    model, f0 = p["model"], f0_hz(p)
    if model in MEMBRANES:
        glide = {"pitch_start_hz": f0 * p["bend_ratio"], "pitch_end_hz": f0,
                 "pitch_decay_ms": p["bend_ms"]}
        return np.sin(body_phase(t, glide))
    if model == "clave":
        return np.sin(2.0 * math.pi * f0 * t)
    if model == "cowbell":
        bank = 0.5 * square_bank([f0, f0 * COWBELL_RATIO], sr, len(t))
        return biquad_bandpass(bank, sr, COWBELL_BP_HZ * tune_factor(p), COWBELL_BP_Q)
    if model == "shaker":
        if not len(t):
            return np.zeros(0)
        noise = streams[SHAKER_STREAM].standard_normal(len(t))
        y = rbj_highpass(biquad_bandpass(noise, sr, f0, SHAKER_BP_Q), sr,
                         SHAKER_HP_HZ * tune_factor(p))
        return _unit_rms(y, "shaker noise")
    raise ValueError(f"unknown perc model {model!r}")


def _tick(p: dict[str, Any], t: np.ndarray, streams: list[np.random.Generator]) -> np.ndarray:
    sr = int(p["sample_rate"])
    out = np.zeros(len(t))
    w = min(len(t), int(round(TICK_WINDOW_MS * sr / 1000.0)))
    if w == 0:
        return out
    noise = streams[TICK_STREAM].standard_normal(w)
    y = _unit_rms(biquad_bandpass(noise, sr, p["tick_hz"], TICK_Q), "tick")
    out[:w] = p["tick_level"] * y * _amp_envelope(t[:w], 0.0, TICK_DECAY_MS / 1000.0)
    return out


def has_tick(p: dict[str, Any]) -> bool:
    return p["model"] != "shaker" and p["tick_level"] > 0.0


def render_resolved(p: dict[str, Any]) -> np.ndarray:
    """Render already resolved parameters (no validation)."""
    sr = int(p["sample_rate"])
    n = file_samples(p)
    n_off = offset_samples(p)
    m = n - n_off
    t = np.arange(m, dtype=np.float64) / sr
    streams = substreams(p["seed"], N_STREAMS)
    env = _amp_envelope(t, attack_ms(p) / 1000.0, t60_ms(p) / 1000.0)
    x = _voice(p, t, streams) * env
    if has_tick(p):
        x = x + _tick(p, t, streams)
    if p["hp_hz"] > HP_OFF_HZ and m:
        x = rbj_highpass(x, sr, p["hp_hz"])
    if m:
        x[0] = 0.0
    if p["drive"] > 0:
        peak = float(np.max(np.abs(x))) if m else 0.0
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
