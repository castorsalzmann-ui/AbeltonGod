"""Clap voice (Phase 06, issue #231): seeded noise, band-passed, multi-burst envelope, tail.

Contract: ``contracts/clap-params.schema.json`` v0.1. Signal path (all float64, mono):

1. white noise from sub-stream 0 of the seed (:func:`audio_engine.dsp.substreams`),
   RBJ band-pass (``bp_hz``, ``bp_q``; constant 0 dB peak) over the whole noise;
2. amplitude envelope = ``bursts`` exponential bursts ``burst_spacing_ms`` apart (level of
   burst k: ``burst_level_falloff ** k``, fall of 60 dB in ``burst_decay_ms``) plus one tail
   that starts one spacing after the last burst onset (``tail_level`` relative to burst 0,
   60 dB in ``tail_decay_ms``). Each component rises linearly over :data:`ATTACK_MS` (not a
   contract field) so no component starts with a step;
3. RBJ high-pass at ``hp_hz`` after the envelope;
4. ``room`` > 0: the signal plus ``room`` times its convolution with a seeded noise impulse
   response (sub-stream 1, exponential, 60 dB in ``room_length_ms``, unit energy);
5. ``drive`` > 0: the signal is scaled to peak 1, then the kick's anti-aliased saturation
   (:func:`audio_engine.kick._drive`) is applied;
6. 5 ms fade-out, mean removal (the kick's Hann-shaped correction; a short noise burst has a
   non-zero mean even after the high-pass), peak ceiling measured on the quantised file (the
   kick's ``_normalise``), ``offset_ms`` of leading silence, ``polarity``.

Same resolved parameters give the same samples (no clock, no global RNG). ``variants`` is a
batch-only field and is not part of the resolved form, as for the kick.
"""

from __future__ import annotations

import math
import numbers
from functools import cache
from typing import Any

import numpy as np
from jsonschema import Draft202012Validator

from .dsp import biquad_bandpass, rbj_highpass, substreams
from .kick import FADE_OUT_MS, _drive, _fade_out, _normalise, _remove_mean
from .params import CONTRACTS_DIR, _error_line, _to_python, load_schema

CLAP_NAME = "abeltongod-audio-engine-clap"
# Bump on every change that alters rendered bytes (D-013 per category, D-025); update the golden
# hashes in tests/audio_engine/test_clap.py in the same PR.
CLAP_VERSION = "0.1.0"
CLAP_SCHEMA_FILE = CONTRACTS_DIR / "clap-params.schema.json"

ATTACK_MS = 0.3
INTEGER_FIELDS = ("seed", "variants", "bursts", "sample_rate", "bit_depth", "polarity")
BATCH_ONLY_PARAMS = ("variants",)
NOISE_STREAM, ROOM_STREAM = 0, 1
N_STREAMS = 2


class ClapParamsError(ValueError):
    """Raised when clap parameters do not match the contract; the message lists every problem."""


@cache
def _schema() -> dict[str, Any]:
    return load_schema(CLAP_SCHEMA_FILE)


def resolve_clap_params(params: dict[str, Any]) -> dict[str, Any]:
    """Validate against the contract and return the resolved form (new dict, defaults filled).

    Unknown, missing, out-of-range or non-finite fields are rejected, never clamped. Numbers
    must be int or float (NumPy scalars are converted); whole-number floats for integer fields
    become ints. Resolving a resolved form returns it unchanged.
    """
    if not isinstance(params, dict):
        raise ClapParamsError(f"Clap parameters must be an object, got {type(params).__name__}.")
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
        raise ClapParamsError("Invalid clap parameters:\n" + "\n".join(lines))
    resolved = dict(params)
    for key in INTEGER_FIELDS:
        if isinstance(resolved.get(key), float):
            resolved[key] = int(resolved[key])
    for name, prop in schema["properties"].items():
        if name not in resolved and "default" in prop:
            resolved[name] = prop["default"]
    return resolved


def render_clap(params: dict[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    """Render one clap. Returns ``(audio, resolved_params)``; audio is float64 in [-1, 1]."""
    p = resolve_clap_params(params)
    for key in BATCH_ONLY_PARAMS:
        p.pop(key, None)
    return render_resolved(p), p


def file_samples(p: dict[str, Any]) -> int:
    return int(round(p["length_ms"] * int(p["sample_rate"]) / 1000.0))


def offset_samples(p: dict[str, Any]) -> int:
    return int(round(p["offset_ms"] * int(p["sample_rate"]) / 1000.0))


def envelope(p: dict[str, Any], m: int) -> np.ndarray:
    """The amplitude envelope of ``m`` samples starting at the first burst (see module doc)."""
    sr = int(p["sample_rate"])
    t = np.arange(m, dtype=np.float64) / sr
    spacing = p["burst_spacing_ms"] / 1000.0
    attack = ATTACK_MS / 1000.0
    env = np.zeros(m)

    def add(onset: float, level: float, decay_ms: float) -> None:
        if level <= 0.0:
            return
        tau = decay_ms / 1000.0 / math.log(1000.0)
        dt = np.clip(t - onset, 0.0, None)
        shape = np.minimum(1.0, dt / attack) * np.exp(-dt / tau)
        env[:] += level * np.where(t >= onset, shape, 0.0)

    for k in range(p["bursts"]):
        add(k * spacing, p["burst_level_falloff"] ** k, p["burst_decay_ms"])
    add(p["bursts"] * spacing, p["tail_level"], p["tail_decay_ms"])
    return env


def render_resolved(p: dict[str, Any]) -> np.ndarray:
    """Render already resolved parameters (no validation)."""
    sr = int(p["sample_rate"])
    n = file_samples(p)
    n_off = offset_samples(p)
    m = n - n_off
    streams = substreams(p["seed"], N_STREAMS)

    x = biquad_bandpass(streams[NOISE_STREAM].standard_normal(m), sr, p["bp_hz"], p["bp_q"])
    x = x * envelope(p, m)
    x = rbj_highpass(x, sr, p["hp_hz"])
    if p["room"] > 0:
        x = x + p["room"] * _room(x, streams[ROOM_STREAM], sr, p["room_length_ms"])
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


def _room(x: np.ndarray, rng: np.random.Generator, sr: int, length_ms: float) -> np.ndarray:
    """``x`` convolved with a seeded noise impulse response (60 dB decay over ``length_ms``),
    unit energy, cut to the length of ``x``."""
    k = max(1, int(round(length_ms * sr / 1000.0)))
    t = np.arange(k) / sr
    ir = rng.standard_normal(k) * np.exp(-t / (length_ms / 1000.0 / math.log(1000.0)))
    ir /= math.sqrt(float(np.sum(ir**2)))
    size = len(x) + k
    return np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)[: len(x)]
