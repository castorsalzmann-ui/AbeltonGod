"""Atmospheres and drones (issue #529, D-034): seamless stereo loops and one-shots of
``noise_bed``, ``drone``, ``resonant`` and ``granular`` in one parameter space.

Contract: ``contracts/atmos-params.schema.json`` v0.1; the numbered rules are its ``$comment``
points. Output shape ``(n, 2)``. N = ``round(240 * bars * sr / bpm)`` frames is one loop.

Resolution (contract description): non-finite numbers are rejected first, then schema
validation, top-level defaults, then the defaults of the ``allOf`` branch of the kind (the
noise_bed branch also matches an omitted ``kind``), then cross-field rules A-E.

Signal path, ``loop_mode`` seamless (all float64, every stage circular or in steady state):

1. Source (point 3), one period of N frames, built in the N-point real DFT domain:
   noise = sub-streams s0 / s1, ``R = c L + sqrt(1 - c^2) w1``, each channel times the tilt and
   scaled to the RMS of its white stream (Parseval on the spectrum); resonant = that noise
   spectrum times the comb ``sum_v sum_k a_k |H_bp(f; k f_v, res_q)|``; drone = bin-locked
   partials, each ``a_k g_p(n) sin(2 pi (b_p n / N + theta_p))``; granular = Hann grains of the
   internal source, overlap-added modulo N.
2. Fixed hp / lp (point 4): 2nd-order Butterworth magnitudes on the DFT bins, zero phase.
3. Moving filter (point 6), steady state (point 8): ``fx.svf`` over P + 2 tiled periods; the
   period at index P is kept, the one at P + 1 is the convergence guard.
4. Level and pan movement (point 7) from the one movement curve c(n) (point 5).
5. Drive: joint peak scaled to 1, then the kick's ``_drive`` per channel on the period padded
   circularly by :data:`DRIVE_PAD` frames on both sides (its FIR filters reach about 80 frames;
   the padding makes the result the circular one and keeps ``_drive``'s zeroed first sample out
   of the file).
6. Reverb: ``laser_fx.reverb_wet`` over P + 2 tiled periods (input mono as in laser); period P
   kept, energy-matched to the dry period: ``wet_P * sqrt(E_dry / E(wet_P))``; guard on P + 1.
7. Pump, 8. mono_below (side signal in the DFT domain, half-octave ramp), 9. peak scaling of
   the quantised file (``kick._normalise``).

``loop_mode`` oneshot (point 10): steps 1-2 on one period, then the linear fades
(``g[i] = i / Fi`` for the first Fi frames, ``g[i] = (N - i) / Fo`` for the last Fo frames before
frame N), zeros up to the file length, then steps 3-7 once from zero state over the whole file
(drive without the circular padding), mono_below on the file zero-padded by ``round(sr)``
frames, the 5 ms end fade of fx, peak scaling.

Drone synthesis (point 3, choices stated in the contract since #529): per kept partial the
drift gain ``g_p = 10^(drift_db / 2 * d_p / 20)`` is a periodic function of the movement phase
``u = move_cycles * n / N``; its Fourier coefficients come from a :data:`DRIFT_GRID`-point FFT
of ``g_p`` on ``u = m / DRIFT_GRID`` and are scattered around the partial's bin. The harmonics
of ``g_p`` above :data:`DRIFT_HARMONICS` are below 1e-17 of its mean (Taylor bound of the
exponential, ``drift_db`` <= 12), so the result equals the time-domain sum to far below one
24-bit LSB (an independent time-domain re-render in the tests checks this).

Cross-platform bytes (point 13): the per-sample transcendentals (movement curve, dB -> gain,
cutoff, tan of the filter coefficient, Hann window, pan) use the polynomial helpers of
:mod:`audio_engine.fx`. Remaining library calls covered only by the golden hashes on Ubuntu and
Windows CI: NumPy's FFTs, the normal sampler, ``np.tanh`` in the drive (only when drive > 0) and
the platform ``exp`` / ``pow`` inside ``laser_fx.reverb_wet`` (per file, not per sample).
"""

from __future__ import annotations

import math
import numbers
from functools import cache
from typing import Any

import numpy as np
from jsonschema import Draft202012Validator

from . import laser_fx
from .dsp import substreams
from .fx import cos_cycles, db_to_gain, exp2, log2, sin_cycles, svf
from .kick import _drive, _normalise
from .laser import analyse_laser
from .params import CONTRACTS_DIR, _error_line, load_schema

ATMOS_NAME = "abeltongod-audio-engine-atmos"
# Bump on every change that alters rendered bytes (D-013 per category, D-025); update the golden
# hashes in tests/audio_engine/test_atmos.py in the same PR.
ATMOS_VERSION = "0.1.0"
ATMOS_SCHEMA_FILE = CONTRACTS_DIR / "atmos-params.schema.json"

MAX_FILE_MS = 72000.0  # cross-field rule A
NYQUIST_SHARE = 0.45
FADE_MS = 5.0
TILT_REF_HZ, TILT_LOW_HZ = 1000.0, 20.0
METAL_HZ = (205.3, 304.4, 369.6, 522.7, 540.0, 800.0)  # hat-params $comment point 2
FILTER_TAU_FACTOR = 20.0  # point 8: e^-20
REVERB_T60_FACTOR = 2.4  # point 8: 2.4 * T60 = -144 dB
N_STREAMS = 8
S_NOISE_L, S_NOISE_R, S_MOVE, S_DRIFT, S_GRAIN = 0, 1, 2, 3, 4
DRAWS_PER_PARTIAL = 9  # theta, then a_1, phi_1, ..., a_4, phi_4 of the drift curve
MOVE_HARMONICS = 4
DRIFT_GRID = 512  # samples of one movement cycle for the drift gain's spectrum
DRIFT_HARMONICS = 255  # coefficients kept on each side (DRIFT_GRID / 2 - 1)
DRIVE_PAD = 256  # circular padding of the drive stage, frames (FIR reach about 80)
INTEGER_FIELDS = ("seed", "variants", "sample_rate", "bit_depth", "bars", "move_cycles",
                  "note", "partials", "detune_bins")
BATCH_ONLY_PARAMS = ("variants",)
TONAL_SOURCES = ("drone", "metal")


class AtmosParamsError(ValueError):
    """Atmos parameters do not match the contract; the message lists every problem."""


class AtmosConvergenceError(ValueError):
    """A recursive stage did not reach its steady state within its warm-up (point 8)."""


@cache
def _schema() -> dict[str, Any]:
    return load_schema(ATMOS_SCHEMA_FILE)


@cache
def _branches() -> tuple[tuple[Draft202012Validator, dict[str, Any]], ...]:
    return tuple(
        (Draft202012Validator(b["if"]), b["then"]["properties"]) for b in _schema()["allOf"]
    )


# --- resolution --------------------------------------------------------------------------------


def _plain(value: Any) -> Any:
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.generic):
        return value.item()
    return value


def _number_lines(key: str, value: Any) -> list[str]:
    if isinstance(value, list):
        return [line for i, v in enumerate(value) for line in _number_lines(f"{key}[{i}]", v)]
    if isinstance(value, bool):
        return []
    if isinstance(value, numbers.Number) and not isinstance(value, int | float):
        return [f"- {key}: must be int or float, got {type(value).__name__} {value!r}"]
    if isinstance(value, float) and not math.isfinite(value):
        return [f"- {key}: must be a finite number, got {value!r}"]
    return []


def resolve_atmos_params(params: dict[str, Any]) -> dict[str, Any]:
    """Validate against the contract and return the resolved form (new dict, defaults filled).

    Unknown, missing, out-of-range or non-finite fields and violations of cross-field rules A-E
    are rejected, never clamped. Resolving a resolved form returns it unchanged.
    """
    if not isinstance(params, dict):
        raise AtmosParamsError(
            f"Atmos parameters must be an object, got {type(params).__name__}.")
    params = {k: _plain(v) for k, v in params.items()}
    schema = _schema()
    lines = [line for k, v in sorted(params.items()) for line in _number_lines(k, v)]
    if not lines:
        errors = sorted(Draft202012Validator(schema).iter_errors(params),
                        key=lambda e: list(e.path))
        lines = [_error_line(e) for e in errors]
    if lines:
        raise AtmosParamsError("Invalid atmos parameters:\n" + "\n".join(lines))
    resolved = dict(params)
    for key in INTEGER_FIELDS:
        if isinstance(resolved.get(key), float):
            resolved[key] = int(resolved[key])
    for name, prop in schema["properties"].items():
        if name not in resolved and "default" in prop:
            resolved[name] = _plain(prop["default"])
    for check, props in _branches():
        if check.is_valid(params):
            for name, prop in props.items():
                if name not in resolved and "default" in prop:
                    resolved[name] = prop["default"]
    resolved["intervals"] = [int(v) for v in resolved["intervals"]]
    lines = cross_field_errors(resolved)
    if lines:
        raise AtmosParamsError("Invalid atmos parameters:\n" + "\n".join(lines))
    return resolved


def cross_field_errors(p: dict[str, Any]) -> list[str]:
    """Rules A-E of the contract (points 1, 4, 6, 10, 11) as error lines."""
    out = []
    oneshot = p["loop_mode"] == "oneshot"
    ms = file_ms(p)
    if ms > MAX_FILE_MS * (1.0 + 1e-12):
        what = "4 * bars + tail_beats" if oneshot else "bars"
        out.append(
            f"- {what}: the file would be {ms:.1f} ms at {p['bpm']} BPM; at most "
            f"{MAX_FILE_MS:.0f} ms (rule A; 32 bars need bpm >= 106.67)"
        )
    if p["lp_hz"] < 1.5 * p["hp_hz"]:
        out.append(f"- lp_hz {p['lp_hz']} must be at least 1.5 * hp_hz = {1.5 * p['hp_hz']:g} "
                   "(rule B)")
    if is_tonal(p):
        err = tuning_error_cents(p)
        if abs(err) > p["max_tuning_cents"] * (1.0 + 1e-12):
            out.append(
                f"- note {p['note']} / cents {p['cents']}: the loop's bin grid "
                f"({bin_hz(p):.3f} Hz at bars {p['bars']}, {p['bpm']} BPM) puts the "
                f"fundamental {err:+.2f} cents off, more than max_tuning_cents "
                f"{p['max_tuning_cents']} (rule C); use more bars, another note or a larger "
                "max_tuning_cents"
            )
    if p["filter_mode"] != "off":
        lo, hi = cutoff_range(p)
        nyq = NYQUIST_SHARE * int(p["sample_rate"])
        if lo < 20.0 * (1.0 - 1e-12) or hi > nyq * (1.0 + 1e-12):
            out.append(
                f"- filter_hz {p['filter_hz']} with move_depth_oct {p['move_depth_oct']}: the "
                f"cutoff moves {lo:.1f}-{hi:.1f} Hz, allowed 20-{nyq:.0f} Hz (rule D)"
            )
    if oneshot and p["fade_in_beats"] + p["fade_out_beats"] > 4 * p["bars"]:
        out.append(
            f"- fade_in_beats {p['fade_in_beats']} + fade_out_beats {p['fade_out_beats']} = "
            f"{p['fade_in_beats'] + p['fade_out_beats']:g} beats is longer than the loop "
            f"({p['bars']} bar(s) = {4 * p['bars']} beats); lower one of the two fades or use "
            "more bars (rule E; the default fades 4 + 4 need at least 2 bars)"
        )
    return out


def is_tonal(p: dict[str, Any]) -> bool:
    """Rule C applies: drone, and granular with a drone or metal source (point 11)."""
    return p["kind"] == "drone" or (
        p["kind"] == "granular" and p["granular_source"] in TONAL_SOURCES)


# --- lengths and pitch -------------------------------------------------------------------------


def loop_samples_exact(p: dict[str, Any]) -> float:
    return 240.0 * p["bars"] * int(p["sample_rate"]) / p["bpm"]


def loop_samples(p: dict[str, Any]) -> int:
    """N = round(240 * bars * sr / bpm), round half to even (point 1)."""
    return int(round(loop_samples_exact(p)))


def file_samples(p: dict[str, Any]) -> int:
    if p["loop_mode"] == "seamless":
        return loop_samples(p)
    beats = 4 * p["bars"] + p["tail_beats"]
    return int(round(beats * 60.0 * int(p["sample_rate"]) / p["bpm"]))


def file_ms(p: dict[str, Any]) -> float:
    beats = 4 * p["bars"] + (p["tail_beats"] if p["loop_mode"] == "oneshot" else 0)
    return beats * 60000.0 / p["bpm"]


def bin_hz(p: dict[str, Any]) -> float:
    return int(p["sample_rate"]) / loop_samples(p)


def root_hz(p: dict[str, Any]) -> float:
    """f0 = 440 * 2^((note - 69 + cents / 100) / 12)."""
    return 440.0 * float(exp2(np.array([(p["note"] - 69 + p["cents"] / 100.0) / 12.0]))[0])


def nearest_bin(f: float, n: int, sr: int) -> int:
    return max(1, int(round(f * n / sr)))


def tuning_error_cents(p: dict[str, Any]) -> float:
    """Realised fundamental b0 * sr / N against f0, cents (point 11)."""
    n, sr, f0 = loop_samples(p), int(p["sample_rate"]), root_hz(p)
    return 1200.0 * math.log2(nearest_bin(f0, n, sr) * sr / (n * f0))


def realised_detune_cents(p: dict[str, Any]) -> float | None:
    if p["kind"] != "drone" or p["detune_bins"] == 0:
        return None
    b0 = nearest_bin(root_hz(p), loop_samples(p), int(p["sample_rate"]))
    return 1200.0 * math.log2((b0 + p["detune_bins"]) / b0)


def cutoff_range(p: dict[str, Any]) -> tuple[float, float]:
    half = float(p["move_depth_oct"]) / 2.0
    lo, hi = exp2(np.array([-half, half]))
    return float(p["filter_hz"]) * float(lo), float(p["filter_hz"]) * float(hi)


# --- warm-up counts (point 8) ------------------------------------------------------------------


def preroll_filter(p: dict[str, Any]) -> int:
    if p["filter_mode"] == "off" or p["loop_mode"] != "seamless":
        return 0
    tau = float(p["filter_q"]) / (math.pi * cutoff_range(p)[0])
    t_loop = loop_samples(p) / int(p["sample_rate"])
    return math.ceil(FILTER_TAU_FACTOR * tau / t_loop)


def preroll_reverb(p: dict[str, Any]) -> int:
    if p["reverb_mix"] == 0 or p["loop_mode"] != "seamless":
        return 0
    t_loop = loop_samples(p) / int(p["sample_rate"])
    ms = REVERB_T60_FACTOR * float(p["reverb_decay_ms"]) + float(p["reverb_predelay_ms"])
    return math.ceil(ms / 1000.0 / t_loop)


# --- render ------------------------------------------------------------------------------------


def render_atmos(params: dict[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    """Render one atmos file. Returns ``(audio (n, 2), resolved_params)``."""
    p = resolve_atmos_params(params)
    for key in BATCH_ONLY_PARAMS:
        p.pop(key, None)
    return render_resolved(p), p


def analyse_atmos(audio: np.ndarray, sr: int, p: dict[str, Any]) -> dict[str, Any]:
    """Sidecar features: the laser's stereo features plus the atmos-only ones (#529 step 0)."""
    features = analyse_laser(audio, sr)
    features["loop_samples"] = loop_samples(p)
    features["loop_samples_exact"] = loop_samples_exact(p)
    features["seamless"] = p["loop_mode"] == "seamless"
    features["preroll_loops"] = {"filter": preroll_filter(p), "reverb": preroll_reverb(p)}
    features["tuning_error_cents"] = round(tuning_error_cents(p), 4) if is_tonal(p) else None
    detune = realised_detune_cents(p)
    features["realised_detune_cents"] = None if detune is None else round(detune, 4)
    return features


def render_resolved(p: dict[str, Any]) -> np.ndarray:
    """Render already resolved parameters (no validation). Shape ``(n, 2)``."""
    sr = int(p["sample_rate"])
    n = loop_samples(p)
    x = source_period(p)
    c = movement_curve(p, n)
    if p["loop_mode"] == "seamless":
        if p["filter_mode"] != "off":
            x = steady_state(lambda y: moving_filter(y, p, c), x, preroll_filter(p), p,
                             "moving filter")
        x = x * movement_gains(p, c)
        if p["drive"] > 0:
            x = circular_drive(x, float(p["drive"]))
        if p["reverb_mix"] > 0:
            x = x + float(p["reverb_mix"]) * steady_reverb(x, p)
        if p["pump_depth"] > 0:
            x = x * pump_gain(p, n)[:, None]
        if p["mono_below_hz"] > 0:
            x = mono_below(x, float(p["mono_below_hz"]), sr)
        return _normalise(x, p["peak_ceiling_dbfs"], p["bit_depth"])
    total = file_samples(p)
    x = x * oneshot_fades(p, n)[:, None]
    x = np.concatenate([x, np.zeros((total - n, 2))]) if total >= n else x[:total]
    cc = np.resize(c, total)
    if p["filter_mode"] != "off":
        x = moving_filter(x, p, cc)
    x = x * movement_gains(p, cc)
    if p["drive"] > 0:
        peak = float(np.max(np.abs(x)))
        if peak > 0.0:
            x = np.stack([_drive(x[:, ch] / peak, float(p["drive"])) for ch in (0, 1)], axis=1)
    if p["reverb_mix"] > 0:
        x = x + float(p["reverb_mix"]) * laser_fx.reverb_wet(x, p)
    if p["pump_depth"] > 0:
        x = x * pump_gain(p, total)[:, None]
    if p["mono_below_hz"] > 0:
        pad = np.concatenate([x, np.zeros((int(round(sr)), 2))])
        x = mono_below(pad, float(p["mono_below_hz"]), sr)[:total]
    x = x * end_fade(total, sr)[:, None]
    return _normalise(x, p["peak_ceiling_dbfs"], p["bit_depth"])


# --- sources (point 3) and fixed filters (point 4) ----------------------------------------------


def _freqs(n: int, sr: int) -> np.ndarray:
    return np.arange(n // 2 + 1, dtype=np.float64) * (sr / n)


def tilt_response(f: np.ndarray, tilt_db_oct: float) -> np.ndarray:
    out = np.zeros(len(f))
    keep = f >= TILT_LOW_HZ
    out[keep] = db_to_gain(tilt_db_oct * log2(f[keep] / TILT_REF_HZ))
    return out


def fixed_response(f: np.ndarray, hp_hz: float, lp_hz: float) -> np.ndarray:
    """``|H_hp| * |H_lp|``, 2nd-order Butterworth magnitudes (point 4)."""
    a = f / hp_hz
    a2 = a * a
    b = f / lp_hz
    b2 = b * b
    return a2 / np.sqrt(1.0 + a2 * a2) / np.sqrt(1.0 + b2 * b2)


def _rms_of_spectrum(spec: np.ndarray, n: int) -> float:
    """RMS of ``irfft(spec, n)`` by Parseval (bins 0 and n/2 once, the others twice)."""
    power = spec.real * spec.real + spec.imag * spec.imag
    weight = np.full(len(spec), 2.0)
    weight[0] = 1.0
    if n % 2 == 0:
        weight[-1] = 1.0
    return math.sqrt(float(np.sum(weight * power)) / (n * n))


def noise_spectrum(p: dict[str, Any], n: int) -> np.ndarray:
    """Tilted noise (point 3) as rfft bins, shape ``(n // 2 + 1, 2)``, each channel scaled
    to the RMS of its white stream."""
    streams = substreams(p["seed"], N_STREAMS)
    w0 = streams[S_NOISE_L].standard_normal(n)
    w1 = streams[S_NOISE_R].standard_normal(n)
    c = 1.0 - float(p["stereo_width"])
    right = w0.copy() if c == 1.0 else c * w0 + math.sqrt(1.0 - c * c) * w1
    tilt = tilt_response(_freqs(n, int(p["sample_rate"])), float(p["tilt_db_oct"]))
    out = []
    for w in (w0, right):
        spec = np.fft.rfft(w) * tilt
        rms = _rms_of_spectrum(spec, n)
        white = math.sqrt(float(np.mean(w * w)))
        out.append(spec * (white / rms) if rms > 0.0 else spec)
    return np.stack(out, axis=1)


def partial_weights(p: dict[str, Any], count: int) -> np.ndarray:
    k = np.arange(1, count + 1, dtype=np.float64)
    return db_to_gain(float(p["brightness_db_oct"]) * log2(k))


def voice_hz(p: dict[str, Any]) -> np.ndarray:
    semis = np.array(p["intervals"], dtype=np.float64) / 12.0
    return root_hz(p) * exp2(semis)


def comb_response(p: dict[str, Any], f: np.ndarray) -> np.ndarray:
    """Resonant: ``sum_v sum_k a_k / sqrt(1 + Q^2 (f / fc - fc / f)^2)`` at the exact
    ``fc = k f_v`` (point 3); 0 at f = 0."""
    sr = int(p["sample_rate"])
    q2 = float(p["res_q"]) ** 2
    weights = partial_weights(p, int(p["partials"]))
    out = np.zeros(len(f))
    pos = f > 0.0
    fp = f[pos]
    acc = np.zeros(len(fp))
    for fv in voice_hz(p).tolist():
        for k in range(1, int(p["partials"]) + 1):
            fc = k * fv
            if fc > NYQUIST_SHARE * sr:
                break
            d = fp / fc - fc / fp
            acc += weights[k - 1] / np.sqrt(1.0 + q2 * (d * d))
    out[pos] = acc
    return out


def drone_partials(p: dict[str, Any], n: int) -> list[tuple[int, float]]:
    """Kept partials in draw order (point 3): ``(bin, amplitude)``, voice by voice in
    ``intervals`` order, k ascending, each followed by its detune copy."""
    sr = int(p["sample_rate"])
    weights = partial_weights(p, int(p["partials"]))
    out = []
    d = int(p["detune_bins"])
    for fv in voice_hz(p).tolist():
        for k in range(1, int(p["partials"]) + 1):
            if k * fv > NYQUIST_SHARE * sr:
                break
            b = nearest_bin(k * fv, n, sr)
            out.append((b, float(weights[k - 1])))
            if d > 0 and (b + d) * sr / n <= NYQUIST_SHARE * sr:
                out.append((b + d, float(weights[k - 1])))
    return out


def _add_sine(spec: np.ndarray, b: int, coef: complex | np.ndarray, n: int,
              shifts: np.ndarray | None = None) -> None:
    """Add ``Im(g(n) e^{i 2 pi (b n / N + theta)})`` given as ``coef_j`` at bins ``b + j mc``.

    ``coef`` holds ``A * N / (2i) * e^{i 2 pi theta} * c_j`` for the shifts ``j mc`` (or one
    value without shifts). The conjugate term lands at ``-(b + j mc)``; every index is taken
    modulo N and kept where it is in [0, N / 2] (rfft half).
    """
    half = n // 2
    if shifts is None:
        idx = np.array([b])
        coef = np.array([coef])
    else:
        idx = b + shifts
    for sign, values in ((1, coef), (-1, np.conj(coef))):
        k = np.mod(sign * idx, n)
        keep = k <= half
        np.add.at(spec, k[keep], values[keep] if sign == 1 else -values[keep])


def drift_coefficients(p: dict[str, Any], draws: np.ndarray) -> np.ndarray:
    """Fourier coefficients c_j, j = -H .. H, of ``g = 10^(drift_db / 2 * d / 20)`` over one
    movement cycle, ``d(u) = sum_h a_h sin(2 pi (h u + phi_h)) / max_m |sum|`` on the grid
    ``u = m / DRIFT_GRID`` (contract point 3, #529)."""
    u = np.arange(DRIFT_GRID, dtype=np.float64) / DRIFT_GRID
    s = np.zeros(DRIFT_GRID)
    for h in range(1, MOVE_HARMONICS + 1):
        a = draws[2 * h - 1] / h
        s += a * sin_cycles(h * u + draws[2 * h])
    peak = float(np.max(np.abs(s)))
    d = s / peak if peak > 0.0 else s
    g = db_to_gain(float(p["drift_db"]) / 2.0 * d)
    c = np.fft.fft(g) / DRIFT_GRID
    h = DRIFT_HARMONICS
    return np.concatenate([c[DRIFT_GRID - h:], c[: h + 1]])


def drone_spectrum(p: dict[str, Any], n: int) -> np.ndarray:
    """Bin-locked partials (point 3) as rfft bins, shape ``(n // 2 + 1, 2)``.

    s3 draw order: per kept partial nine uniforms in [0, 1): ``theta`` (left phase, cycles;
    right phase ``theta * (1 + stereo_width)``), then ``a_1, phi_1, ..., a_4, phi_4`` of its
    drift curve (``a_h`` = value / h, ``phi_h`` in cycles). The drift uses ``move_cycles``
    cycles per loop; ``move_cycles`` 0 or ``drift_db`` 0 = constant level.
    """
    parts = drone_partials(p, n)
    draws = substreams(p["seed"], N_STREAMS)[S_DRIFT].random(DRAWS_PER_PARTIAL * len(parts))
    draws = draws.reshape(len(parts), DRAWS_PER_PARTIAL)
    mc = int(p["move_cycles"])
    drifting = mc > 0 and p["drift_db"] > 0
    shifts = (np.arange(-DRIFT_HARMONICS, DRIFT_HARMONICS + 1) * mc) if drifting else None
    width = float(p["stereo_width"])
    spec = np.zeros((n // 2 + 1, 2), dtype=np.complex128)
    for (b, amp), row in zip(parts, draws, strict=True):
        theta = float(row[0])
        coefs = drift_coefficients(p, row) if drifting else None
        for ch, phase in enumerate((theta, theta * (1.0 + width))):
            rot = complex(float(cos_cycles(np.array([phase]))[0]),
                          float(sin_cycles(np.array([phase]))[0]))
            base = amp * n / 2.0 * (-1j) * rot  # A N / (2i) e^{i 2 pi phase}
            col = spec[:, ch]
            if drifting:
                _add_sine(col, b, base * coefs, n, shifts)
            else:
                _add_sine(col, b, base, n)
    return spec


def metal_spectrum(p: dict[str, Any], n: int) -> np.ndarray:
    """Six band-limited squares (odd harmonics, ``4 / (pi h)``, phase 0), the hat metal bank
    scaled so its lowest partial is f0, bin-locked, averaged; both channels equal."""
    sr = int(p["sample_rate"])
    f0 = root_hz(p)
    spec = np.zeros(n // 2 + 1, dtype=np.complex128)
    for fi in METAL_HZ:
        f = f0 * fi / METAL_HZ[0]
        h = 1
        while h * f <= NYQUIST_SHARE * sr:
            amp = 4.0 / (math.pi * h) / len(METAL_HZ)
            _add_sine(spec, nearest_bin(h * f, n, sr), amp * n / 2.0 * (-1j), n)
            h += 2
    return np.stack([spec, spec], axis=1)


def granular_source(p: dict[str, Any], n: int) -> np.ndarray:
    src = p["granular_source"]
    if src == "noise":
        spec = noise_spectrum(p, n)
    elif src == "drone":
        spec = drone_spectrum(p, n)
    else:
        spec = metal_spectrum(p, n)
    return np.fft.irfft(spec, n, axis=0)


def hann(g: int) -> np.ndarray:
    """``0.5 - 0.5 cos(2 pi j / (G - 1))``, j = 0 .. G - 1 (G = 1: [1])."""
    if g == 1:
        return np.ones(1)
    j = np.arange(g, dtype=np.float64)
    return 0.5 - 0.5 * cos_cycles(j / (g - 1))


def grains(p: dict[str, Any], src: np.ndarray) -> np.ndarray:
    """Circular overlap-add of K Hann grains (point 3); each channel reads its own source
    channel, then the grain's equal-power pan gains apply."""
    n = len(src)
    sr = int(p["sample_rate"])
    count = max(1, int(round(float(p["grain_density"]) * n / sr)))
    g = int(round(float(p["grain_ms"]) * sr / 1000.0))
    win = hann(g)
    j = np.arange(g, dtype=np.float64)
    rng = substreams(p["seed"], N_STREAMS)[S_GRAIN]
    spread, pc, pan = float(p["grain_spread"]), float(p["grain_pitch_cents"]), float(p["grain_pan"])
    out = np.zeros((n, 2))
    for _ in range(count):
        o = int(rng.integers(0, n))
        u = float(rng.uniform(-1.0, 1.0))
        cents = float(rng.uniform(-pc, pc))
        q = float(rng.uniform(-pan, pan))
        ratio = float(exp2(np.array([cents / 1200.0]))[0])
        pos = np.mod(o + u * spread * n / 2.0 + j * ratio, n)
        i0 = np.floor(pos)
        frac = pos - i0
        a = i0.astype(np.int64) % n
        b = (a + 1) % n
        gains = (float(cos_cycles(np.array([(q + 1.0) / 8.0]))[0]),
                 float(sin_cycles(np.array([(q + 1.0) / 8.0]))[0]))
        dest = (o + np.arange(g)) % n
        for ch in (0, 1):
            val = src[a, ch] * (1.0 - frac) + src[b, ch] * frac
            out[dest, ch] += gains[ch] * (win * val)
    return out


def source_period(p: dict[str, Any]) -> np.ndarray:
    """Points 3 and 4: one period, shape ``(N, 2)``, after tilt and the fixed hp / lp."""
    n, sr = loop_samples(p), int(p["sample_rate"])
    f = _freqs(n, sr)
    kind = p["kind"]
    if kind == "granular":
        spec = np.fft.rfft(grains(p, granular_source(p, n)), axis=0)
    elif kind == "drone":
        spec = drone_spectrum(p, n)
    else:
        spec = noise_spectrum(p, n)
        if kind == "resonant":
            spec = spec * comb_response(p, f)[:, None]
    spec = spec * fixed_response(f, float(p["hp_hz"]), float(p["lp_hz"]))[:, None]
    return np.fft.irfft(spec, n, axis=0)


# --- movement (points 5-7) ---------------------------------------------------------------------


def movement_curve(p: dict[str, Any], n: int) -> np.ndarray:
    """c(n), n = 0 .. N - 1, in [-1, 1] with ``move_cycles`` cycles per loop (point 5)."""
    mc = int(p["move_cycles"])
    if mc == 0:
        return np.zeros(n)
    frames = np.arange(n, dtype=np.int64)
    if p["move_shape"] == "sine":
        return sin_cycles(((mc * frames) % n) / n)
    r = substreams(p["seed"], N_STREAMS)[S_MOVE].random(2 * MOVE_HARMONICS)
    s = np.zeros(n)
    for h in range(1, MOVE_HARMONICS + 1):
        s += (r[2 * h - 2] / h) * sin_cycles(((h * mc * frames) % n) / n + r[2 * h - 1])
    peak = float(np.max(np.abs(s)))
    return s / peak if peak > 0.0 else np.zeros(n)


def moving_filter(x: np.ndarray, p: dict[str, Any], c: np.ndarray) -> np.ndarray:
    """One TPT state-variable filter per channel, cutoff ``filter_hz * 2^(depth / 2 * c)``."""
    reps = len(x) // len(c)
    fc = float(p["filter_hz"]) * exp2(float(p["move_depth_oct"]) / 2.0 * c)
    if reps > 1:
        fc = np.tile(fc, reps)
    sr, q, mode = int(p["sample_rate"]), float(p["filter_q"]), p["filter_mode"]
    left = svf(x[:, 0], fc, q, mode, sr)
    right = left.copy() if np.array_equal(x[:, 0], x[:, 1]) else svf(x[:, 1], fc, q, mode, sr)
    return np.stack([left, right], axis=1)


def movement_gains(p: dict[str, Any], c: np.ndarray) -> np.ndarray:
    """Level ``amp_move_db / 2 * c`` dB times the pan ``sqrt(1 -+ pan_move * c)``."""
    level = db_to_gain(float(p["amp_move_db"]) / 2.0 * c)
    pm = float(p["pan_move"])
    return np.stack([level * np.sqrt(1.0 - pm * c), level * np.sqrt(1.0 + pm * c)], axis=1)


def pump_gain(p: dict[str, Any], n: int) -> np.ndarray:
    """``1 - pump_depth * (1 - phi)^4``, phi = fractional beat, frame 0 a beat start."""
    beats = np.arange(n, dtype=np.float64) / (60.0 * int(p["sample_rate"]) / p["bpm"])
    q = 1.0 - (beats - np.floor(beats))
    q2 = q * q
    return 1.0 - float(p["pump_depth"]) * (q2 * q2)


# --- steady state (point 8) --------------------------------------------------------------------


def _lsb(p: dict[str, Any]) -> float:
    return 1.0 / (2 ** (int(p["bit_depth"]) - 1) - 1)


def _converged(kept: np.ndarray, nxt: np.ndarray, p: dict[str, Any], stage: str,
               preroll: int) -> None:
    peak = float(np.max(np.abs(kept)))
    diff = float(np.max(np.abs(kept - nxt)))
    if peak > 0.0 and diff >= _lsb(p) * peak:
        raise AtmosConvergenceError(
            f"{stage}: after {preroll} warm-up period(s) the next period still differs by "
            f"{diff / peak / _lsb(p):.3g} LSB of {p['bit_depth']} bit; no file written "
            "(point 8)"
        )


def steady_state(stage, x: np.ndarray, preroll: int, p: dict[str, Any], name: str
                 ) -> np.ndarray:
    """Run ``stage`` over ``preroll + 2`` copies of the period ``x``; keep copy ``preroll``,
    check it against copy ``preroll + 1`` (the convergence guard)."""
    n = len(x)
    y = stage(np.tile(x, (preroll + 2, 1)))
    kept, nxt = y[preroll * n:(preroll + 1) * n], y[(preroll + 1) * n:]
    _converged(kept, nxt, p, name, preroll)
    return kept.copy()


def steady_reverb(x: np.ndarray, p: dict[str, Any]) -> np.ndarray:
    """Reverb wet signal of the period ``x`` in steady state, energy-matched to ``x``."""
    n, preroll = len(x), preroll_reverb(p)
    wet = steady_state(lambda y: laser_fx.reverb_wet(y, p), x, preroll, p, "reverb")
    e_wet = float(np.sum(wet * wet))
    e_dry = float(np.sum(x * x))
    if e_wet <= 0.0 or e_dry <= 0.0 or n == 0:
        return np.zeros_like(x)
    return wet * math.sqrt(e_dry / e_wet)


# --- drive, mono_below, fades ------------------------------------------------------------------


def circular_drive(x: np.ndarray, drive: float) -> np.ndarray:
    """The kick's drive on the period, padded circularly (module docstring step 5)."""
    peak = float(np.max(np.abs(x)))
    if peak == 0.0:
        return x
    y = x / peak
    pad = min(DRIVE_PAD, len(y))
    ext = np.concatenate([y[-pad:], y, y[:pad]])
    return np.stack([_drive(ext[:, ch], drive)[pad:pad + len(y)] for ch in (0, 1)], axis=1)


def mono_below(x: np.ndarray, f_hz: float, sr: int) -> np.ndarray:
    """Side signal times w(f) on the DFT bins: 0 up to f_hz, 1 from f_hz * 2^0.5, linear in
    log2 f between (point 9)."""
    n = len(x)
    mid = 0.5 * (x[:, 0] + x[:, 1])
    side = 0.5 * (x[:, 0] - x[:, 1])
    f = _freqs(n, sr)
    w = np.zeros(len(f))
    pos = f > f_hz
    w[pos] = np.minimum(1.0, 2.0 * log2(f[pos] / f_hz))
    side = np.fft.irfft(np.fft.rfft(side) * w, n)
    return np.stack([mid + side, mid - side], axis=1)


def oneshot_fades(p: dict[str, Any], n: int) -> np.ndarray:
    spb = 60.0 * int(p["sample_rate"]) / p["bpm"]
    fi = int(round(p["fade_in_beats"] * spb))
    fo = int(round(p["fade_out_beats"] * spb))
    g = np.ones(n)
    i = np.arange(n, dtype=np.float64)
    if fi > 0:
        g[:fi] *= i[:fi] / fi
    if fo > 0:
        lo = max(0, n - fo)
        g[lo:] *= (n - i[lo:]) / fo
    return g


def end_fade(n: int, sr: int) -> np.ndarray:
    """Linear fade over the last ``max(2, round(5 ms * sr))`` frames, last frame 0 (as fx)."""
    f = min(n, max(2, int(round(FADE_MS * sr / 1000.0))))
    g = np.ones(n)
    g[n - f:] = np.linspace(1.0, 0.0, max(2, int(round(FADE_MS * sr / 1000.0))))[-f:]
    return g
