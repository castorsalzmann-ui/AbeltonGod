"""Bass voice (Phase 06, issue #328): additive oscillators, high-pass, enveloped low-pass, gate.

Contract: ``contracts/bass-params.schema.json`` v0.1 (all numbers there are placeholders).
Signal path (all float64, mono, ``t`` from the first sound sample):

1. Oscillators (:func:`oscillators`): phase-0 sine series at ``f0 = 440 * 2^((note-69)/12) *
   2^(cents/1200)``: saw = sum_k sin(k w t) / k, square = same over odd k, sine = sin(w t), sub =
   sin(w t / 2). Each level is the amplitude of the first partial. Partials are exact and
   limited to ``k * f0 < 0.45 * sr``. The sines of the harmonics come from the Chebyshev
   recurrence ``s(k+1) = 2 cos(w t) s(k) - s(k-1)`` (adds and multiplies only).
2. 2nd-order high-pass at ``hp_hz`` (RBJ, Q = 1/sqrt(2)), then a 2nd-order low-pass (RBJ, Q =
   ``lp_q``) whose cutoff is ``lp_hz * 2^(lp_env_amount * 10^(-3 t / lp_env_decay))`` (the
   excess falls to 0.1 % after ``lp_env_decay_ms``). The coefficients change every sample
   (direct form I); ``lp_env_amount`` 0 uses the static filter.
3. Amplitude: linear attack ``amp_attack_ms``, hold until ``gate_ms``, linear release to 0 over
   ``release_ms`` (first and last sample exactly 0). File length = offset + gate + release.
4. ``drive`` > 0: signal scaled to peak 1, then the kick's anti-aliased saturation.
5. DC blocker (:func:`dc_block`, D-028): ``c * envelope`` is subtracted so the file mean is ~0.
6. Peak ceiling measured on the quantised file (the kick's normalise), ``offset_ms`` of leading
   silence, ``polarity``. No fade-out: the release ends at 0 and a bass keeps its sustained
   level (the mean of the file is reported as ``dc_offset``).

No randomness: ``seed`` only labels the render (the core voice is seed-independent, contract
rule 7). Same resolved parameters give the same samples.
"""

from __future__ import annotations

import math
import numbers
from functools import cache
from typing import Any

import numpy as np
from jsonschema import Draft202012Validator

from .dsp import rbj_highpass, rbj_lowpass
from .kick import _drive, _normalise
from .params import CONTRACTS_DIR, _error_line, _to_python, load_schema

BASS_NAME = "abeltongod-audio-engine-bass"
# Bump on every change that alters rendered bytes (D-013 per category, D-025); update the golden
# hashes in tests/audio_engine/test_bass.py in the same PR.
BASS_VERSION = "0.2.0"
BASS_SCHEMA_FILE = CONTRACTS_DIR / "bass-params.schema.json"

PARTIAL_LIMIT = 0.45  # partials and the cutoff stay below PARTIAL_LIMIT * sample_rate
HP_MARGIN = 0.8  # hp_hz < HP_MARGIN * f0
LP_OVER_HP = 1.2  # lp_hz >= LP_OVER_HP * hp_hz
OSCILLATOR_FIELDS = ("saw_level", "square_level", "sine_level", "sub_octave_level")
STATIONARY = (0.4, 0.8)  # fraction of gate_ms used for fundamental_hz (contract rule 6)
INTEGER_FIELDS = ("seed", "variants", "note", "sample_rate", "bit_depth", "polarity")
BATCH_ONLY_PARAMS = ("variants",)


class BassParamsError(ValueError):
    """Raised when bass parameters do not match the contract; the message lists every problem."""


@cache
def _schema() -> dict[str, Any]:
    return load_schema(BASS_SCHEMA_FILE)


def note_frequency(note: float, cents: float = 0.0) -> float:
    """f0 in Hz of a MIDI note plus a fine tune in cents (contract rule 1)."""
    return 440.0 * 2.0 ** ((note - 69) / 12.0) * 2.0 ** (cents / 1200.0)


def resolve_bass_params(params: dict[str, Any]) -> dict[str, Any]:
    """Validate against the contract and return the resolved form (new dict, defaults filled).

    Unknown, missing, out-of-range or non-finite fields and the four cross-field rules of the
    contract (hp_hz < 0.8 f0, lp_hz >= 1.2 hp_hz, lp_hz 2^lp_env_amount < 0.45 sr, one
    oscillator above 0) are rejected, never clamped. Resolving a resolved form returns it
    unchanged.
    """
    if not isinstance(params, dict):
        raise BassParamsError(f"Bass parameters must be an object, got {type(params).__name__}.")
    params = {k: _to_python(v) for k, v in params.items()}
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
        validator = Draft202012Validator(_schema())
        errors = sorted(validator.iter_errors(params), key=lambda e: list(e.path))
        lines = [_error_line(e) for e in errors]
    resolved = dict(params)
    if not lines:
        for key in INTEGER_FIELDS:
            if isinstance(resolved.get(key), float):
                resolved[key] = int(resolved[key])
        for name, prop in _schema()["properties"].items():
            if name not in resolved and "default" in prop:
                resolved[name] = prop["default"]
        lines = _cross_field_problems(resolved)
    if lines:
        raise BassParamsError("Invalid bass parameters:\n" + "\n".join(lines))
    return resolved


def _cross_field_problems(p: dict[str, Any]) -> list[str]:
    out: list[str] = []
    f0 = note_frequency(p["note"], p["cents"])
    if not p["hp_hz"] < HP_MARGIN * f0:
        out.append(
            f"- hp_hz: must be less than 0.8 * f0 = {HP_MARGIN * f0:g} Hz "
            f"(note {p['note']}, {p['cents']:g} cents), got {p['hp_hz']!r}"
        )
    if p["lp_hz"] < LP_OVER_HP * p["hp_hz"]:
        out.append(
            f"- lp_hz: must be at least 1.2 * hp_hz = {LP_OVER_HP * p['hp_hz']:g}, "
            f"got {p['lp_hz']!r}"
        )
    start = p["lp_hz"] * 2.0 ** p["lp_env_amount"]
    if not start < PARTIAL_LIMIT * p["sample_rate"]:
        out.append(
            f"- lp_env_amount: lp_hz * 2^lp_env_amount = {start:g} Hz (the cutoff at t = 0) must "
            f"be less than 0.45 * sample_rate = {PARTIAL_LIMIT * p['sample_rate']:g}"
        )
    if not any(p[name] > 0 for name in OSCILLATOR_FIELDS):
        out.append("- saw_level, square_level, sine_level, sub_octave_level: at least one must "
                   "be greater than 0 (otherwise the note is silent)")
    return out


def render_bass(params: dict[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    """Render one bass note. Returns ``(audio, resolved_params)``; audio is float64 in [-1, 1]."""
    p = resolve_bass_params(params)
    for key in BATCH_ONLY_PARAMS:
        p.pop(key, None)
    return render_resolved(p), p


def file_samples(p: dict[str, Any]) -> int:
    sr = int(p["sample_rate"])
    return int(round((p["offset_ms"] + p["gate_ms"] + p["release_ms"]) * sr / 1000.0))


def offset_samples(p: dict[str, Any]) -> int:
    return int(round(p["offset_ms"] * int(p["sample_rate"]) / 1000.0))


def gate_samples(p: dict[str, Any]) -> int:
    """Samples from the first sound sample to the gate end (attack included)."""
    return int(round(p["gate_ms"] * int(p["sample_rate"]) / 1000.0))


def oscillators(p: dict[str, Any], m: int) -> np.ndarray:
    """The summed oscillators, ``m`` samples from the first sound sample (see module doc)."""
    sr = int(p["sample_rate"])
    f0 = note_frequency(p["note"], p["cents"])
    theta = 2.0 * math.pi * f0 * np.arange(m, dtype=np.float64) / sr
    saw, square, sine, sub = (p[k] for k in OSCILLATOR_FIELDS)
    x = np.zeros(m)
    if sub > 0:
        x += sub * np.sin(0.5 * theta)
    k_max = 1
    if saw > 0 or square > 0:
        k_max = int(math.ceil(PARTIAL_LIMIT * sr / f0)) - 1  # largest k with k f0 < 0.45 sr
        while (k_max + 1) * f0 < PARTIAL_LIMIT * sr:
            k_max += 1
        while k_max * f0 >= PARTIAL_LIMIT * sr:
            k_max -= 1
    two_cos = 2.0 * np.cos(theta)
    s_prev, s = np.zeros(m), np.sin(theta)
    for k in range(1, k_max + 1):
        c = saw / k + (square / k if k % 2 else 0.0) + (sine if k == 1 else 0.0)
        if c != 0.0:
            x += c * s
        if k < k_max:
            s_prev, s = s, two_cos * s - s_prev
    return x


def cutoff_hz(p: dict[str, Any], t: np.ndarray) -> np.ndarray:
    """Low-pass cutoff at the times ``t`` (s): ``lp_hz * 2^(amount * 10^(-3 t / decay))``."""
    decay = p["lp_env_decay_ms"] / 1000.0
    return p["lp_hz"] * 2.0 ** (p["lp_env_amount"] * 10.0 ** (-3.0 * t / decay))


def _lowpass_varying(x: np.ndarray, sr: int, fc: np.ndarray, q: float) -> np.ndarray:
    """RBJ low-pass, direct form I, coefficients recomputed for every sample."""
    w0 = 2.0 * np.pi * fc / sr
    cw, alpha = np.cos(w0), np.sin(w0) / (2.0 * q)
    a0 = 1.0 + alpha
    b0 = ((1.0 - cw) / 2.0 / a0).tolist()
    b1 = ((1.0 - cw) / a0).tolist()
    a1 = (-2.0 * cw / a0).tolist()
    a2 = ((1.0 - alpha) / a0).tolist()
    y = np.zeros(len(x))
    x1 = x2 = y1 = y2 = 0.0
    for i, xi in enumerate(x.tolist()):
        yi = b0[i] * (xi + x2) + b1[i] * x1 - a1[i] * y1 - a2[i] * y2
        y[i] = yi
        x2, x1 = x1, xi
        y2, y1 = y1, yi
    return y


def amp_envelope(p: dict[str, Any], m: int) -> np.ndarray:
    """Linear attack, hold until ``gate_ms``, linear release; first and last sample are 0."""
    sr = int(p["sample_rate"])
    i = np.arange(m, dtype=np.float64)
    n_gate = min(gate_samples(p), m - 1)
    attack = p["amp_attack_ms"] * sr / 1000.0
    env = np.minimum(i / attack, 1.0)
    release = (m - n_gate)
    tail = i >= n_gate
    env[tail] *= 1.0 - (i[tail] - n_gate + 1.0) / release
    return env


def dc_block(x: np.ndarray, env: np.ndarray) -> np.ndarray:
    """Last stage of the voice (D-028, #335): remove the DC the drive creates, ``x - c env``.

    The drive turns the asymmetric saw into a signal with a mean, and that mean follows the
    amplitude envelope. A fixed linear high-pass was tried first and measured: it needs
    ~30 ms (5 Hz) to settle, which is longer than the shortest notes, so the file mean stayed
    up to 0.05 of the peak and the release end got a pulse of up to 0.16 of the peak. Here the
    subtracted part has the shape of the envelope, ``c = mean(x) / mean(env)``, so the mean of the
    float signal is 0 up to rounding, the first and last sample stay 0 (``env`` is 0 there) and
    no filter touches the note frequency. Deterministic, no state, no parameter.
    """
    total = float(np.sum(env))
    if total <= 0.0:
        return x
    return x - (float(np.sum(x)) / total) * env


def render_resolved(p: dict[str, Any]) -> np.ndarray:
    """Render already resolved parameters (no validation)."""
    sr = int(p["sample_rate"])
    n_off = offset_samples(p)
    m = file_samples(p) - n_off
    x = oscillators(p, m)
    x = rbj_highpass(x, sr, p["hp_hz"])
    if p["lp_env_amount"] > 0:
        fc = cutoff_hz(p, np.arange(m, dtype=np.float64) / sr)
        x = _lowpass_varying(x, sr, fc, p["lp_q"])
    else:
        x = rbj_lowpass(x, sr, p["lp_hz"], p["lp_q"])
    env = amp_envelope(p, m)
    x = x * env
    if p["drive"] > 0:
        peak = float(np.max(np.abs(x)))
        if peak > 0.0:
            x = _drive(x / peak, p["drive"])
            x[-1] = 0.0  # the drive residual is not exactly 0 at the end; the contract says 0
    x = dc_block(x, env)
    x = _normalise(x, p["peak_ceiling_dbfs"], p["bit_depth"])
    if n_off:
        x = np.concatenate([np.zeros(n_off), x])
    if p["polarity"] == -1:
        x = -x
    return x


# --- sidecar features ------------------------------------------------------------------------

FUND_SEARCH = 0.06  # the fundamental is searched within +-6 % of the note frequency


def stationary_window(p: dict[str, Any]) -> tuple[int, int]:
    """Sample range ``[a, b)`` of the file from 40 % to 80 % of ``gate_ms`` (after the offset)."""
    n_off, gate = offset_samples(p), gate_samples(p)
    return n_off + int(round(STATIONARY[0] * gate)), n_off + int(round(STATIONARY[1] * gate))


def fundamental_hz(audio: np.ndarray, p: dict[str, Any]) -> float | None:
    """Note frequency measured in the stationary window; ``None`` if it holds < 2 periods.

    The window is cut to a whole number of periods of the note, then the magnitude of the
    DFT (Hann window over the cut window) is maximised near the note frequency (grid, then
    golden-section), so the answer is a measurement within +-6 % of the note, not a copy of it.
    """
    sr = int(p["sample_rate"])
    f0 = note_frequency(p["note"], p["cents"])
    a, b = stationary_window(p)
    periods = int((b - a) * f0 / sr)
    if periods < 2:
        return None
    seg = audio[a : a + int(round(periods * sr / f0))] * p["polarity"]
    seg = seg * np.hanning(len(seg))  # Hann: the rectangular window leaks too much at 2-3 periods
    n = np.arange(len(seg), dtype=np.float64) / sr

    def mag(f: float) -> float:
        return abs(complex(np.dot(seg, np.exp(-2j * np.pi * f * n))))

    grid = np.linspace(f0 * (1 - FUND_SEARCH), f0 * (1 + FUND_SEARCH), 49)
    best = int(np.argmax([mag(float(f)) for f in grid]))
    lo, hi = float(grid[max(best - 1, 0)]), float(grid[min(best + 1, len(grid) - 1)])
    inv = (math.sqrt(5.0) - 1.0) / 2.0
    c, d = hi - inv * (hi - lo), lo + inv * (hi - lo)
    for _ in range(40):
        if mag(c) > mag(d):
            hi, d = d, c
            c = hi - inv * (hi - lo)
        else:
            lo, c = c, d
            d = lo + inv * (hi - lo)
    return round(0.5 * (lo + hi), 2)


def analyse_basic(audio: np.ndarray, sr: int) -> dict[str, float | None]:
    """peak, length and DC of a bass file (no gate information needed)."""
    if audio.ndim != 1:
        raise ValueError("analyse_bass() expects mono audio (1-D array).")
    n = len(audio)
    peak = float(np.max(np.abs(audio))) if n else 0.0
    return {
        "peak_dbfs": round(20.0 * math.log10(peak), 3) if peak > 0 else None,
        "length_ms": round(n / sr * 1000.0, 3),
        "dc_offset": round(float(np.mean(audio)), 6) if n else None,
    }


def analyse_bass(audio: np.ndarray, sr: int, p: dict[str, Any]) -> dict[str, float | None]:
    """Sidecar features of a bass: peak, length, fundamental_hz (stationary window), DC.

    ``analysis.analyse`` is not used: its tail window lands in the release of a gated note and
    its envelope features ripple on sustained notes (bass-params rule 8).
    """
    out = analyse_basic(audio, sr)
    out["fundamental_hz"] = fundamental_hz(audio, p) if out["peak_dbfs"] is not None else None
    return out
