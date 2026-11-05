"""Laser voice (issue #416, D-030): sci-fi laser shots, six selectable families, stereo.

Contract: ``contracts/laser-params.schema.json`` v0.1 (the rules are numbered in its
``$comment``; this docstring only names where each is implemented).

Public API for the blaster window::

    render_laser(params: dict, seed: int) -> np.ndarray   # float64, shape (n, 2), L / R

``params`` is a laser-params object without ``seed`` (``schema_version`` may be omitted); the
``seed`` argument is the seed. Output is peak-normalised for the quantised file
(``peak_ceiling_dbfs``, ``bit_depth``), identical channels at ``stereo_width`` 0.

Signal path (all float64; internal rate ``OVERSAMPLE * sample_rate``):

1. Per channel: sweep frequency, integrated phase, family oscillator, FM (index limited so
   sidebands stay below 0.45 * internal rate), ring modulation, envelope.
2. Noise / crackle (per-channel mix of a common and an independent stream), same family-free
   envelope; 20 Hz high-pass on the sum.
3. Decimation by 2 with a linear-phase Kaiser low-pass (FFT convolution).
4. Echo (ping-pong with ``stereo_width``), ``drive`` (kick stage), first sample 0, 5 ms fade,
   mean removal, joint peak ceiling, offset, polarity.

No clock, no global RNG.
"""

from __future__ import annotations

import math
import numbers
from functools import cache
from typing import Any

import numpy as np
from jsonschema import Draft202012Validator

from . import analysis
from .dsp import (
    biquad_bandpass,
    fft_size,
    kaiser_lowpass,
    rbj_highpass,
    substreams,
)
from .kick import FADE_OUT_MS, _amp_envelope, _drive, _fade_out, _normalise, _remove_mean
from .params import CONTRACTS_DIR, _error_line, _to_python, load_schema

LASER_NAME = "abeltongod-audio-engine-laser"
# Bump on every change that alters rendered bytes (D-013 per category, D-025); update the golden
# hashes in tests/audio_engine/test_laser.py in the same PR.
LASER_VERSION = "0.1.0"
LASER_SCHEMA_FILE = CONTRACTS_DIR / "laser-params.schema.json"

FAMILIES = ("pew", "plasma", "ion", "rift", "subboom", "glitch")
INTEGER_FIELDS = ("seed", "variants", "sample_rate", "bit_depth", "polarity", "glitch_steps")
BATCH_ONLY_PARAMS = ("variants",)

OVERSAMPLE = 2
ALIAS_LIMIT = 0.45  # of the internal rate (contract point 4, 9)
FM_MAX_INDEX = 6.0
WIDTH_CENTS = 15.0
NOISE_Q = 1.2
NOISE_DECAY_SHARE = 0.5
CRACKLE_DENSITY = 1500.0  # impulses per second at crackle 1
CRACKLE_HP_HZ = 2000.0
SUB_HP_HZ = 20.0
ION_PARTIALS = ((2.003, 0.5), (3.01, 0.25))
SUB_RATIO = 0.25
SUB_DECAY_FACTOR = 1.5
GLITCH_DUTY = 0.6
GLITCH_EDGE = 0.05  # of a step
VARIATION_OCTAVES = 0.3
ECHO_FLOOR = 1e-4
# sub-streams of the seed
S_NOISE_COMMON, S_NOISE_L, S_NOISE_R, S_CRACKLE, S_GLITCH, S_VARIATION = range(6)
N_STREAMS = 6


class LaserParamsError(ValueError):
    """Raised when laser parameters do not match the contract; the message lists every problem."""


@cache
def _schema() -> dict[str, Any]:
    return load_schema(LASER_SCHEMA_FILE)


def resolve_laser_params(params: dict[str, Any]) -> dict[str, Any]:
    """Validate against the contract and return the resolved form (new dict, defaults filled).

    Unknown, missing, out-of-range or non-finite fields are rejected, never clamped. Resolving
    a resolved form returns it unchanged.
    """
    if not isinstance(params, dict):
        raise LaserParamsError(f"Laser parameters must be an object, got {type(params).__name__}.")
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
        raise LaserParamsError("Invalid laser parameters:\n" + "\n".join(lines))
    resolved = dict(params)
    for key in INTEGER_FIELDS:
        if isinstance(resolved.get(key), float):
            resolved[key] = int(resolved[key])
    for name, prop in schema["properties"].items():
        if name not in resolved and "default" in prop:
            resolved[name] = prop["default"]
    return resolved


def render_laser(params: dict[str, Any], seed: int) -> np.ndarray:
    """Render one shot; float64 array of shape ``(n, 2)`` (left, right). See module docstring."""
    request = {k: v for k, v in dict(params).items() if k != "seed"}
    request.setdefault("schema_version", "0.1")
    request["seed"] = seed
    return render_resolved(_strip(resolve_laser_params(request)))


def render_laser_category(params: dict[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    """Category-registry form: ``(audio (n, 2), resolved_params)``."""
    p = _strip(resolve_laser_params(params))
    return render_resolved(p), p


def _strip(p: dict[str, Any]) -> dict[str, Any]:
    p = dict(p)
    for key in BATCH_ONLY_PARAMS:
        p.pop(key, None)
    return p


def analyse_laser(audio: np.ndarray, sr: int) -> dict[str, float | None]:
    """Sidecar features: the non-pitched ones on the mid signal, ``peak_dbfs`` joint (point 14)."""
    if audio.ndim != 2 or audio.shape[1] != 2:
        raise ValueError("analyse_laser() expects stereo audio of shape (n, 2).")
    features = analysis.analyse_nonpitched(audio.mean(axis=1), sr)
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    features["peak_dbfs"] = round(20.0 * math.log10(peak), 3) if peak > 0 else None
    return features


def file_samples(p: dict[str, Any]) -> int:
    return int(round(p["length_ms"] * int(p["sample_rate"]) / 1000.0))


def offset_samples(p: dict[str, Any]) -> int:
    return int(round(p["offset_ms"] * int(p["sample_rate"]) / 1000.0))


# --- voice -----------------------------------------------------------------------------------


def _varied(p: dict[str, Any]) -> dict[str, float]:
    """Pitch / sweep / decay after the seeded variation (contract point 6), inside the ranges."""
    props = _schema()["properties"]
    out = {k: float(p[k]) for k in ("pitch_start_hz", "pitch_end_hz", "sweep_ms", "decay_ms")}
    v = float(p["variation"])
    if v > 0.0:
        u = substreams(p["seed"], N_STREAMS)[S_VARIATION].uniform(-1.0, 1.0, size=len(out))
        for (key, value), ui in zip(list(out.items()), u, strict=True):
            scaled = value * 2.0 ** (VARIATION_OCTAVES * v * ui)
            out[key] = min(max(scaled, props[key]["minimum"]), props[key]["maximum"])
    return out


def _sweep_freq(t: np.ndarray, f0: float, f1: float, sweep_s: float, curve: float) -> np.ndarray:
    progress = np.minimum(1.0, t / sweep_s) ** curve
    return f0 * (f1 / f0) ** progress


def _phase(freq: np.ndarray, rate: int) -> np.ndarray:
    """2 pi * integral of freq (rectangle rule, phase 0 at the first sample)."""
    cum = np.cumsum(freq) / rate
    return 2.0 * math.pi * (cum - cum[0] if len(cum) else cum)


def _saw_bandlimited(phase: np.ndarray, freq: np.ndarray, rate: int) -> np.ndarray:
    """Additive sawtooth; only harmonics below ``ALIAS_LIMIT * rate`` at each instant."""
    out = np.zeros_like(phase)
    limit = ALIAS_LIMIT * rate
    k = 1
    while True:
        mask = k * freq < limit
        if not mask.any():
            break
        out += np.where(mask, np.sin(k * phase) / k, 0.0)
        k += 1
        if k > 400:
            break
    return out * (2.0 / math.pi)


def _glitch_steps(t: np.ndarray, p: dict[str, Any], v: dict[str, float]):
    """Held-step frequency (with seeded detune) and the per-step gate (contract point 1)."""
    steps = int(p["glitch_steps"])
    sweep_s = v["sweep_ms"] / 1000.0
    u = np.minimum(t / sweep_s, 1.0)
    idx = np.minimum(np.floor(u * steps), steps - 1).astype(int)
    held = idx / steps
    f0, f1 = v["pitch_start_hz"], v["pitch_end_hz"]
    freq = f0 * (f1 / f0) ** (held ** p["sweep_curve"])
    detune = substreams(p["seed"], N_STREAMS)[S_GLITCH].uniform(-1.0, 1.0, size=steps)
    freq = freq * 2.0 ** (p["crackle"] * detune[idx])
    freq = np.clip(freq, 20.0, 12000.0)
    frac = np.where(t < sweep_s, u * steps - np.floor(u * steps), 0.0)
    gate = np.clip((GLITCH_DUTY - frac) / GLITCH_EDGE, 0.0, 1.0)
    gate = np.where(t < sweep_s, gate, 1.0)
    return freq, gate


def _oscillator(
    p: dict[str, Any], v: dict[str, float], t: np.ndarray, rate: int, detune: float
) -> np.ndarray:
    """One channel's voice at the internal rate, before noise and the envelope."""
    family = p["family"]
    sweep_s = v["sweep_ms"] / 1000.0
    f0, f1 = v["pitch_start_hz"] * detune, v["pitch_end_hz"] * detune
    gate = None
    if family == "glitch":
        freq, gate = _glitch_steps(t, p, {**v, "pitch_start_hz": f0, "pitch_end_hz": f1})
        freq = np.minimum(freq, ALIAS_LIMIT * rate)
    else:
        freq = _sweep_freq(t, f0, f1, sweep_s, p["sweep_curve"])
    phase = _phase(freq, rate)
    fm = p["fm_amount"]
    if fm > 0.0:
        room = (ALIAS_LIMIT * rate - freq) / (freq * p["fm_ratio"]) - 1.0
        index = np.clip(room, 0.0, FM_MAX_INDEX * fm)
        phase = phase + index * np.sin(p["fm_ratio"] * phase)
    if family == "plasma":
        x = _saw_bandlimited(phase, freq, rate)
    elif family == "ion":
        x = np.sin(phase)
        for ratio, level in ION_PARTIALS:
            x = x + level * np.sin(ratio * phase) * (ratio * freq < ALIAS_LIMIT * rate)
    elif family == "rift":
        mirror = _sweep_freq(t, f1, f0, sweep_s, p["sweep_curve"])
        x = 0.5 * (np.sin(phase) + np.sin(_phase(mirror, rate)))
    elif family == "subboom":
        attack = p["attack_ms"] / 1000.0
        sub_env = _amp_envelope(t, attack, SUB_DECAY_FACTOR * v["decay_ms"] / 1000.0)
        env = _amp_envelope(t, attack, v["decay_ms"] / 1000.0)
        sub = np.sin(_phase(freq * SUB_RATIO, rate))
        x = 0.5 * np.sin(phase) * env + sub * sub_env
    else:  # pew, glitch
        x = np.sin(phase)
    if gate is not None:
        x = x * gate
    ring = p["ring_amount"]
    if ring > 0.0:
        x = (1.0 - ring) * x + ring * x * np.sin(2.0 * math.pi * p["ring_hz"] * t)
    if family == "subboom":
        return x  # envelopes already applied per layer
    return x * _amp_envelope(t, p["attack_ms"] / 1000.0, v["decay_ms"] / 1000.0)


def _unit_rms(y: np.ndarray) -> np.ndarray:
    rms = math.sqrt(float(np.mean(y * y)))
    return y / rms if rms > 0.0 else y


def _noise_layers(p: dict[str, Any], v: dict[str, float], t: np.ndarray, rate: int):
    """``(left, right)`` noise + crackle at the internal rate (zeros when both are off)."""
    m = len(t)
    zeros = np.zeros(m)
    if p["noise_level"] <= 0.0 and p["crackle"] <= 0.0:
        return zeros, zeros
    streams = substreams(p["seed"], N_STREAMS)
    env = _amp_envelope(t, 0.0, NOISE_DECAY_SHARE * v["decay_ms"] / 1000.0)
    w = p["stereo_width"]
    common_w, indep_w = math.sqrt(1.0 - w), math.sqrt(w)
    chans = []
    if p["noise_level"] > 0.0:
        raw = [streams[i].standard_normal(m) for i in (S_NOISE_COMMON, S_NOISE_L, S_NOISE_R)]
        band = [_unit_rms(biquad_bandpass(r, rate, min(p["noise_hz"], 0.45 * rate), NOISE_Q))
                for r in raw]
        chans.append([p["noise_level"] * env * (common_w * band[0] + indep_w * band[i])
                      for i in (1, 2)])
    if p["crackle"] > 0.0:
        rng = streams[S_CRACKLE]
        hits = rng.random(m) < (CRACKLE_DENSITY * p["crackle"] / rate)
        signs = rng.choice([-1.0, 1.0], size=m)
        imp = rbj_highpass(np.where(hits, signs, 0.0), rate, CRACKLE_HP_HZ)
        peak = float(np.max(np.abs(imp)))
        imp = imp / peak if peak > 0.0 else imp
        chans.append([p["crackle"] * env * imp] * 2)
    left = sum(c[0] for c in chans)
    right = sum(c[1] for c in chans)
    return left, right


def _decimate(x: np.ndarray, m: int) -> np.ndarray:
    """Low-pass (cut at the base Nyquist) and keep every OVERSAMPLE-th sample, ``m`` of them."""
    h = kaiser_lowpass(OVERSAMPLE, 0.1, 9.0)
    delay = (len(h) - 1) // 2
    size = fft_size(len(x) + len(h))
    y = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(h, size), size)
    return y[delay : delay + len(x)][::OVERSAMPLE][:m]


def _echo(x: np.ndarray, p: dict[str, Any]) -> np.ndarray:
    """Add ping-pong echo taps to the stereo array ``x`` (contract point 7)."""
    mix = p["echo_mix"]
    if mix <= 0.0:
        return x
    sr = int(p["sample_rate"])
    d = max(1, int(round(p["echo_ms"] * sr / 1000.0)))
    w = p["stereo_width"]
    out = x.copy()
    n = len(x)
    k = 1
    while k * d < n:
        gain = mix * p["echo_feedback"] ** (k - 1)
        if gain < ECHO_FLOOR:
            break
        src = x[: n - k * d]
        if k % 2 == 1 and w > 0.0:
            src = np.stack([(1 - w) * src[:, 0] + w * src[:, 1],
                            (1 - w) * src[:, 1] + w * src[:, 0]], axis=1)
        out[k * d :] += gain * src
        k += 1
    return out


def render_resolved(p: dict[str, Any]) -> np.ndarray:
    """Render already resolved parameters (no validation). Shape ``(n, 2)``."""
    sr = int(p["sample_rate"])
    rate = OVERSAMPLE * sr
    n = file_samples(p)
    n_off = offset_samples(p)
    m = n - n_off
    t = np.arange(m * OVERSAMPLE, dtype=np.float64) / rate
    v = _varied(p)
    w = p["stereo_width"]
    cents = 2.0 ** (WIDTH_CENTS * w / 1200.0)
    noise_l, noise_r = _noise_layers(p, v, t, rate)
    if w > 0.0:
        sides = [(_oscillator(p, v, t, rate, cents), noise_l),
                 (_oscillator(p, v, t, rate, 1.0 / cents), noise_r)]
    else:
        osc = _oscillator(p, v, t, rate, 1.0)
        sides = [(osc, noise_l), (osc, noise_l)]
    cols = []
    for osc, noise in sides:
        y = rbj_highpass(osc + noise, rate, SUB_HP_HZ)
        cols.append(_decimate(y, m))
    x = np.stack(cols, axis=1) if m else np.zeros((0, 2))
    x = _echo(x, p)
    if m:
        x[0] = 0.0
    if p["drive"] > 0 and m:
        peak = float(np.max(np.abs(x)))
        if peak > 0.0:
            x = np.stack([_drive(x[:, c] / peak, p["drive"]) for c in (0, 1)], axis=1)
    x = np.stack([_remove_mean(_fade_out(x[:, c], sr, FADE_OUT_MS)) for c in (0, 1)], axis=1)
    x = _normalise(x, p["peak_ceiling_dbfs"], p["bit_depth"])
    if n_off:
        x = np.concatenate([np.zeros((n_off, 2)), x])
    if p["polarity"] == -1:
        x = -x
    return x
