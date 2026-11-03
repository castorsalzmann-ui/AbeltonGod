"""Snare voice (Phase 06, issue #308): two sine partials with a pitch drop plus shaped noise.

Contract: ``contracts/snare-params.schema.json`` v0.1. Signal path (all float64, mono; ``t``
is measured from the first sound sample, ``m`` = file samples minus the offset):

1. Body: two sine partials. Both follow the same frequency ratio
   ``r(t) = 1 + (pitch_drop - 1) * exp(-t / tau)`` with ``tau = pitch_drop_ms`` (time constant,
   like the kick's ``pitch_decay_ms``): lower partial ``body_hz * r(t)``, upper partial
   ``body_hz * mode_ratio * r(t)``, so their ratio is ``mode_ratio`` at every instant. Phase is
   the analytic integral (:func:`body_phase`), start phase 0. The partials are summed with the
   upper at :data:`BODY2_LEVEL` times the lower, then RMS-normalised (no filter acts on the body).
   Envelopes (kick's :func:`kick._amp_envelope`, no attack): lower ``body_decay_ms``, upper
   ``body_decay_ms * body2_decay_ratio``, each 60 dB.
2. Noise: two layers, each its own sub-stream of the seed (:func:`audio_engine.dsp.substreams`).
   Wide layer (stream 0): high-pass ``noise_hp_hz``, optional peaking (``tone_peak_hz`` /
   ``tone_peak_db``, skipped at 0), low-pass ``noise_lp_hz``. Narrow layer (stream 1): same
   chain with the high-pass corner raised to ``min(NARROW_HP_RATIO * noise_hp_hz, 0.9 *
   noise_lp_hz)``. Each layer is RMS-normalised after its filters, then mixed
   ``sqrt(1 - noise_band_mix) * wide + sqrt(noise_band_mix) * narrow``. Envelopes: linear attack
   ``noise_attack_ms``, then 60 dB in ``noise_decay_ms`` (wide) and in
   ``NARROW_DECAY_RATIO * noise_decay_ms`` (narrow).
3. Mix ``sqrt(body_level) * body + sqrt(1 - body_level) * noise``: ``body_level`` is the share of
   the PASSBAND power (body and noise each RMS-normalised before their envelopes; contract
   $comment point 4). At ``body_level`` 1 no noise is drawn into the output (seed-independent).
4. ``drive`` > 0: scaled to peak 1, then the kick's anti-aliased saturation.
5. 5 ms fade-out at the file end, mean removal, peak ceiling on the quantised file.
6. ``offset_ms`` of leading silence, ``polarity``.

Same resolved parameters give the same samples (no clock, no global RNG). ``variants`` is a
batch-only field and is not part of the resolved form after :func:`render_snare`.
"""

from __future__ import annotations

import math
import numbers
from functools import cache
from typing import Any

import numpy as np
from jsonschema import Draft202012Validator

from .dsp import rbj_highpass, rbj_lowpass, rbj_peaking, substreams
from .kick import FADE_OUT_MS, _amp_envelope, _drive, _fade_out, _normalise, _remove_mean
from .params import CONTRACTS_DIR, _error_line, _to_python, load_schema

SNARE_NAME = "abeltongod-audio-engine-snare"
# Bump on every change that alters rendered bytes (D-013 per category, D-025); update the golden
# hashes in tests/audio_engine/test_snare.py in the same PR.
SNARE_VERSION = "0.1.0"
SNARE_SCHEMA_FILE = CONTRACTS_DIR / "snare-params.schema.json"

BODY2_LEVEL = 0.5  # upper partial amplitude relative to the lower (not a contract field)
NARROW_HP_RATIO = 1.5  # narrow noise layer high-pass = this * noise_hp_hz (not a contract field)
NARROW_DECAY_RATIO = 0.4  # narrow noise layer decay = this * noise_decay_ms (not a contract field)
PEAK_Q = 1.0
INTEGER_FIELDS = ("seed", "variants", "sample_rate", "bit_depth", "polarity")
BATCH_ONLY_PARAMS = ("variants",)
WIDE_STREAM, NARROW_STREAM = 0, 1
N_STREAMS = 2


class SnareParamsError(ValueError):
    """Raised when snare parameters do not match the contract; the message lists every problem."""


@cache
def _schema() -> dict[str, Any]:
    return load_schema(SNARE_SCHEMA_FILE)


def resolve_snare_params(params: dict[str, Any]) -> dict[str, Any]:
    """Validate against the contract and return the resolved form (new dict, defaults filled).

    Unknown, missing, out-of-range or non-finite fields and ``noise_lp_hz <= 1.2 *
    noise_hp_hz`` are rejected, never clamped. Resolving a resolved form returns it unchanged.
    """
    if not isinstance(params, dict):
        raise SnareParamsError(f"Snare parameters must be an object, got {type(params).__name__}.")
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
        if resolved["noise_lp_hz"] <= 1.2 * resolved["noise_hp_hz"]:
            lines.append(
                f"- noise_lp_hz: must be greater than 1.2 * noise_hp_hz = "
                f"{1.2 * resolved['noise_hp_hz']:g}, got {resolved['noise_lp_hz']!r}"
            )
    if lines:
        raise SnareParamsError("Invalid snare parameters:\n" + "\n".join(lines))
    return resolved


def render_snare(params: dict[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    """Render one snare. Returns ``(audio, resolved_params)``; audio is float64 in [-1, 1]."""
    p = resolve_snare_params(params)
    for key in BATCH_ONLY_PARAMS:
        p.pop(key, None)
    return render_resolved(p), p


def file_samples(p: dict[str, Any]) -> int:
    return int(round(p["length_ms"] * int(p["sample_rate"]) / 1000.0))


def offset_samples(p: dict[str, Any]) -> int:
    return int(round(p["offset_ms"] * int(p["sample_rate"]) / 1000.0))


def body_phase(t: np.ndarray, f_end: float, drop: float, tau: float) -> np.ndarray:
    """2*pi * integral of f(t) = f_end * (1 + (drop - 1) * e^(-t/tau)) from 0 (analytic)."""
    return 2.0 * math.pi * f_end * (t + (drop - 1.0) * tau * (1.0 - np.exp(-t / tau)))


def _unit_rms(x: np.ndarray) -> np.ndarray:
    rms = math.sqrt(float(np.mean(x * x))) if len(x) else 0.0
    if rms <= 0.0:
        raise ValueError("a mixed part has no energy")
    return x / rms


def _body(p: dict[str, Any], t: np.ndarray) -> np.ndarray:
    tau = p["pitch_drop_ms"] / 1000.0
    f0, ratio = p["body_hz"], p["mode_ratio"]
    low = np.sin(body_phase(t, f0, p["pitch_drop"], tau))
    high = np.sin(body_phase(t, f0 * ratio, p["pitch_drop"], tau))
    # RMS of the pair before the envelopes (the passband reading of body_level), then each
    # partial gets its own envelope.
    scale = math.sqrt(float(np.mean((low + BODY2_LEVEL * high) ** 2)))
    d = p["body_decay_ms"] / 1000.0
    return (low * _amp_envelope(t, 0.0, d) + BODY2_LEVEL * high
            * _amp_envelope(t, 0.0, d * p["body2_decay_ratio"])) / scale


def _noise_layer(p: dict[str, Any], rng: np.random.Generator, m: int, hp_hz: float) -> np.ndarray:
    sr = int(p["sample_rate"])
    y = rbj_highpass(rng.standard_normal(m), sr, hp_hz)
    if p["tone_peak_db"] != 0:
        y = rbj_peaking(y, sr, p["tone_peak_hz"], PEAK_Q, p["tone_peak_db"])
    y = rbj_lowpass(y, sr, p["noise_lp_hz"])
    return _unit_rms(y)


def _noise(p: dict[str, Any], t: np.ndarray) -> np.ndarray:
    m = len(t)
    streams = substreams(p["seed"], N_STREAMS)
    attack = p["noise_attack_ms"] / 1000.0
    decay = p["noise_decay_ms"] / 1000.0
    mix = p["noise_band_mix"]
    out = np.zeros(m)
    if mix < 1.0:
        wide = _noise_layer(p, streams[WIDE_STREAM], m, p["noise_hp_hz"])
        out += math.sqrt(1.0 - mix) * wide * _amp_envelope(t, attack, decay)
    if mix > 0.0:
        corner = min(NARROW_HP_RATIO * p["noise_hp_hz"], 0.9 * p["noise_lp_hz"])
        narrow = _noise_layer(p, streams[NARROW_STREAM], m, corner)
        out += math.sqrt(mix) * narrow * _amp_envelope(t, attack, NARROW_DECAY_RATIO * decay)
    return out


def render_resolved(p: dict[str, Any]) -> np.ndarray:
    """Render already resolved parameters (no validation)."""
    sr = int(p["sample_rate"])
    n = file_samples(p)
    n_off = offset_samples(p)
    m = n - n_off
    t = np.arange(m, dtype=np.float64) / sr
    level = p["body_level"]
    x = np.zeros(m)
    if level > 0.0:
        x += math.sqrt(level) * _body(p, t)
    if level < 1.0:
        x += math.sqrt(1.0 - level) * _noise(p, t)
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
