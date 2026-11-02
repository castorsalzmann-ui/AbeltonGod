"""Hat voice (Phase 06, issue #270): square bank + noise, steep high-pass, envelope, choke.

Contract: ``contracts/hat-params.schema.json`` v0.1. Signal path (all float64, mono):

1. Noise = white noise from sub-stream 0 of the seed (:func:`audio_engine.dsp.substreams`).
   Bank (model ``metal_bank``) = six band-limited squares at :data:`BANK_HZ` times
   ``pitch_scale`` (all odd harmonics below sr / 2, start phases 0, :func:`dsp.square_bank`);
   the low three and the high three are summed separately and crossfaded by ``color``
   (``cos(color * pi / 2)`` and ``sin(color * pi / 2)``).
2. Filter chain, applied to bank and noise separately (:func:`dsp.mix_passband`): steep
   high-pass (two RBJ sections at ``hp_hz``), peaking (``peak_hz``, ``peak_db``, skipped at 0),
   low-pass ``lp_hz``, then ``bp_mix`` times a band-pass (``bp_hz``, ``bp_q``, constant 0 dB
   peak) added to the signal (emphasis path; skipped at 0). The filtered parts are RMS-normalised
   and mixed ``sqrt(metal) * bank + sqrt(1 - metal) * noise`` (``metal`` is the passband power
   share; model ``noise``: share 0).
3. Envelope (the kick's :func:`kick._amp_envelope`): linear attack, exponential fall of 60 dB
   in ``decay_ms`` after the attack. ``body_mix`` > 0: the filtered mix is split into a low
   part (rbj_lowpass at :data:`SPLIT_RATIO` * ``hp_hz``) and the rest; low part keeps the slow
   envelope, the rest gets ``(1 - body_mix) * slow + body_mix * fast`` with ``fast`` = decay
   ``decay_hi_ratio * decay_ms``. At ``body_mix`` 0 this is exactly the single envelope. The
   envelope covers the whole file.
4. ``drive`` > 0: the signal is scaled to peak 1, then the kick's anti-aliased saturation.
5. 5 ms fade-out at the file end, mean removal, peak ceiling measured on the quantised file.
6. ``choke_ms`` > 0: from ``choke_ms`` after the first sound sample a 5 ms linear fade to zero,
   zero after. It acts after normalisation so the samples before the fade equal the unchoked
   render bit for bit.
7. ``offset_ms`` of leading silence, ``polarity``.

Same resolved parameters give the same samples (no clock, no global RNG). ``variants`` is a
batch-only field and is not part of the resolved form after :func:`render_hat`, as for the kick.
"""

from __future__ import annotations

import math
import numbers
from functools import cache
from typing import Any

import numpy as np
from jsonschema import Draft202012Validator

from .dsp import (
    biquad_bandpass,
    highpass_cascade,
    mix_passband,
    rbj_lowpass,
    rbj_peaking,
    square_bank,
    substreams,
)
from .kick import FADE_OUT_MS, _amp_envelope, _drive, _fade_out, _normalise, _remove_mean
from .params import CONTRACTS_DIR, _error_line, _to_python, load_schema

HAT_NAME = "abeltongod-audio-engine-hat"
# Bump on every change that alters rendered bytes (D-013 per category, D-025); update the golden
# hashes in tests/audio_engine/test_hat.py in the same PR.
HAT_VERSION = "0.1.0"
HAT_SCHEMA_FILE = CONTRACTS_DIR / "hat-params.schema.json"

BANK_HZ = (205.3, 304.4, 369.6, 522.7, 540.0, 800.0)
SPLIT_RATIO = 1.5  # body split corner = SPLIT_RATIO * hp_hz (not a contract field)
TAIL_MS = 30.0  # default length = offset + attack + decay + TAIL_MS
HP_SECTIONS = 2
INTEGER_FIELDS = ("seed", "variants", "sample_rate", "bit_depth", "polarity")
BATCH_ONLY_PARAMS = ("variants",)
NOISE_STREAM = 0
N_STREAMS = 1


class HatParamsError(ValueError):
    """Raised when hat parameters do not match the contract; the message lists every problem."""


@cache
def _schema() -> dict[str, Any]:
    return load_schema(HAT_SCHEMA_FILE)


def resolve_hat_params(params: dict[str, Any]) -> dict[str, Any]:
    """Validate against the contract and return the resolved form (new dict, defaults filled).

    Unknown, missing, out-of-range or non-finite fields and ``lp_hz <= 1.2 * hp_hz`` are
    rejected, never clamped. ``length_ms`` omitted becomes ``offset_ms + attack_ms + decay_ms +
    30`` (recorded in the resolved form). Resolving a resolved form returns it unchanged.
    """
    if not isinstance(params, dict):
        raise HatParamsError(f"Hat parameters must be an object, got {type(params).__name__}.")
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
        if resolved["lp_hz"] <= 1.2 * resolved["hp_hz"]:
            lines.append(
                f"- lp_hz: must be greater than 1.2 * hp_hz = {1.2 * resolved['hp_hz']:g}, "
                f"got {resolved['lp_hz']!r}"
            )
    if lines:
        raise HatParamsError("Invalid hat parameters:\n" + "\n".join(lines))
    if "length_ms" not in resolved:
        resolved["length_ms"] = round(
            resolved["offset_ms"] + resolved["attack_ms"] + resolved["decay_ms"] + TAIL_MS, 6
        )
    return resolved


def render_hat(params: dict[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    """Render one hat. Returns ``(audio, resolved_params)``; audio is float64 in [-1, 1]."""
    p = resolve_hat_params(params)
    for key in BATCH_ONLY_PARAMS:
        p.pop(key, None)
    return render_resolved(p), p


def file_samples(p: dict[str, Any]) -> int:
    return int(round(p["length_ms"] * int(p["sample_rate"]) / 1000.0))


def offset_samples(p: dict[str, Any]) -> int:
    return int(round(p["offset_ms"] * int(p["sample_rate"]) / 1000.0))


def choke_gain(m: int, sr: int, choke_ms: float) -> np.ndarray:
    """Gain curve of ``m`` samples: 1 up to ``choke_ms``, linear to 0 over 5 ms, then 0."""
    c = int(round(choke_ms * sr / 1000.0))
    f = max(1, int(round(FADE_OUT_MS * sr / 1000.0)))
    g = np.ones(m)
    if c >= m:
        return g
    k = np.arange(m - c)
    g[c:] = np.clip(1.0 - k / f, 0.0, 1.0)
    return g


def envelope(p: dict[str, Any], m: int, decay_ms: float | None = None) -> np.ndarray:
    """Amplitude envelope of ``m`` samples from the first sound sample (``decay_ms`` overrides)."""
    sr = int(p["sample_rate"])
    t = np.arange(m, dtype=np.float64) / sr
    d = p["decay_ms"] if decay_ms is None else decay_ms
    return _amp_envelope(t, p["attack_ms"] / 1000.0, d / 1000.0)


def _chain(p: dict[str, Any]):
    sr = int(p["sample_rate"])

    def chain(x: np.ndarray) -> np.ndarray:
        y = highpass_cascade(x, sr, p["hp_hz"], HP_SECTIONS)
        if p["peak_db"] != 0:
            y = rbj_peaking(y, sr, p["peak_hz"], 1.0, p["peak_db"])
        y = rbj_lowpass(y, sr, p["lp_hz"])
        if p["bp_mix"] > 0:
            y = y + p["bp_mix"] * biquad_bandpass(y, sr, p["bp_hz"], p["bp_q"])
        return y

    return chain


def _bank(p: dict[str, Any], m: int) -> np.ndarray:
    sr = int(p["sample_rate"])
    freqs = [f * p["pitch_scale"] for f in BANK_HZ]
    low = square_bank(freqs[:3], sr, m)
    high = square_bank(freqs[3:], sr, m)
    a = p["color"] * math.pi / 2.0
    return math.cos(a) * low + math.sin(a) * high


def render_resolved(p: dict[str, Any]) -> np.ndarray:
    """Render already resolved parameters (no validation)."""
    sr = int(p["sample_rate"])
    n = file_samples(p)
    n_off = offset_samples(p)
    m = n - n_off
    noise = substreams(p["seed"], N_STREAMS)[NOISE_STREAM].standard_normal(m)
    if p["model"] == "noise":
        bank, share = np.zeros(m), 0.0
    else:
        bank, share = _bank(p, m), p["metal"]
    x = mix_passband(bank, noise, share, _chain(p))

    slow = envelope(p, m)
    if p["body_mix"] > 0:
        low = rbj_lowpass(x, sr, min(SPLIT_RATIO * p["hp_hz"], 0.45 * sr))
        fast = envelope(p, m, p["decay_hi_ratio"] * p["decay_ms"])
        x = low * slow + (x - low) * ((1.0 - p["body_mix"]) * slow + p["body_mix"] * fast)
    else:
        x = x * slow
    if p["drive"] > 0:
        peak = float(np.max(np.abs(x)))
        if peak > 0.0:
            x = _drive(x / peak, p["drive"])
    x = _fade_out(x, sr, FADE_OUT_MS)
    x = _remove_mean(x)
    x = _normalise(x, p["peak_ceiling_dbfs"], p["bit_depth"])
    if p["choke_ms"] > 0:
        x = x * choke_gain(m, sr, p["choke_ms"])
    if n_off:
        x = np.concatenate([np.zeros(n_off), x])
    if p["polarity"] == -1:
        x = -x
    return x
