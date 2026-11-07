"""FX transitions (sprint W2, issue #482): riser, downlifter, sweep, impact, noise crash and
reverse crash in one stereo parameter space.

Contract: ``contracts/fx-params.schema.json`` v0.1; the numbered rules are its ``$comment``
points. Output shape ``(n, 2)``. ``t`` is file time in beats (``i / spb`` with
``spb = 60 * sample_rate / bpm`` samples per beat).

Resolution (contract description): schema validation, top-level defaults, then the defaults of
the ``allOf`` branch of the kind (the riser branch also matches an omitted ``kind``), then the
derived ``ramp_beats`` / ``tone_glide_beats`` = ``length_beats``; then cross-field rules A
(file at most 72000 ms), B (noise and tone not both 0), C (``cut_beats < length_beats``).

Signal path (all float64):

1. Noise (point 2): sub-streams 0 and 1 of the seed, ``L = s0``,
   ``R = c s0 + sqrt(1 - c^2) s1`` with ``c = 1 - stereo_width``; pink = FFT shaping by
   ``sqrt(1000 / f)`` (0 below 20 Hz), scaled back to the white RMS per channel.
2. Filter (point 3): one topology-preserving-transform state-variable filter per channel
   (:func:`svf`), coefficients from the cutoff of every sample; ``bp`` = band-pass output times
   ``1 / filter_q``; ``hp_lp`` = hp at ``fc`` then lp at ``min(fc * lp_ratio, 0.45 sr)``, Q
   0.7071. The noise gain ``noise_level * 10^(L(t) / 20)`` (point 4) is applied after the
   filter.
3. Tone (point 5), mono: phase in cycles is the running sum of ``f / sr`` (phase 0 at t = 0).
   ``saw`` / ``square`` / ``metal`` are additive with every partial weighted 1 below
   ``0.40 * sr`` and faded linearly to 0 at ``0.45 * sr`` (:data:`PARTIAL_FADE_START`; the
   contract leaves this fade to the engine PR). ``metal`` = the six hat metal_bank squares at
   ``f_i * f(t) / 205.3``, summed and divided by 6.
4. Dry end (point 6): the dry signal is multiplied by a 5 ms linear ramp that ends at frame
   ``round((length_beats - cut_beats) * spb)`` and is 0 from there.
5. Chain (point 7): drive (the kick's anti-aliased saturation per channel, after scaling to
   peak 1) -> ``laser_fx.echo_v2`` (delay ``note_ms(echo_note, bpm)``; ``stereo_width`` is
   passed as in laser, where it is the echo crossover) -> plus ``reverb_mix *
   laser_fx.reverb_wet``. ``reverse_crash``: the dry signal is built in file time, reversed,
   run through this chain, and reversed back.
6. Pump (point 8) on the beat grid anchored at frame 0 (anchor start) or at frame N (anchor
   end): ``1 - pump_depth * (1 - phi)^4``.
7. 5 ms linear fade-out at the file end, THEN the peak scaling to ``peak_ceiling_dbfs`` for the
   quantised file (the kick's :func:`kick._normalise`). The contract lists the scaling before
   the fade; with that order a reverse crash (loudest at its end) would miss the "peak within
   one LSB" rule of point 9, so the fade comes first (contract text change: #496).

Cross-platform bytes (point 10): the per-sample transcendentals of this module (cutoff and
glide curves, dB -> gain, tan of the filter coefficient, sin / cos of the tone) are computed by
the polynomial helpers below from +, -, *, / and exact ``frexp`` / ``ldexp`` only, so they do
not depend on the platform's ``exp`` / ``tan`` (the kind of mismatch the laser echo had, PR
#429); the pump's fourth power is two multiplications. The filter recursion is plain Python
float arithmetic; ``np.sqrt`` (pink shaping, noise correlation) is correctly rounded by IEEE
754. Remaining library calls, NOT made platform-independent here: ``np.tanh`` inside the
kick's drive stage (``kick._drive``, only when ``drive`` > 0), the platform ``exp`` / ``pow``
inside the laser blocks (``laser_fx.echo_v2`` damping and grid, ``laser_fx.reverb_wet`` line
gains; per file, not per sample, except the echo's grid), the FFTs (pink noise, drive
oversampling, echo) and NumPy's normal sampler. All are covered by the golden hashes that CI
checks on Ubuntu and Windows.

Cost: the filter loop is ~0.7 us per sample and channel. The additive tone layer costs in
proportion to the partial count 0.45 * sr / tone_hz; since #503 it runs in cache-sized blocks
with exact shortcuts (same bytes): a 72 s saw at 20 Hz took 40.2 s before and 7.1 s after,
metal at 20 Hz 78.9 s -> 15.8 s (dev container, one run each).
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
from .kick import _drive, _normalise
from .laser import analyse_laser
from .params import CONTRACTS_DIR, _error_line, _to_python, load_schema

FX_NAME = "abeltongod-audio-engine-fx"
# Bump on every change that alters rendered bytes (D-013 per category, D-025); update the golden
# hashes in tests/audio_engine/test_fx.py in the same PR.
FX_VERSION = "0.1.0"
FX_SCHEMA_FILE = CONTRACTS_DIR / "fx-params.schema.json"

MAX_FILE_MS = 72000.0  # cross-field rule A
FADE_MS = 5.0
NYQUIST_SHARE = 0.45
PARTIAL_FADE_START = 0.40  # partials fade from 0.40 * sr to 0 at 0.45 * sr (engine choice)
ADDITIVE_BLOCK = 8192  # samples per block of the additive tone (cache-sized, #503)
HP_LP_Q = 0.7071
PINK_REF_HZ, PINK_LOW_HZ = 1000.0, 20.0
METAL_HZ = (205.3, 304.4, 369.6, 522.7, 540.0, 800.0)  # hat-params $comment point 2
METAL_BASE_HZ = METAL_HZ[0]
DERIVED = ("ramp_beats", "tone_glide_beats")
INTEGER_FIELDS = ("seed", "variants", "sample_rate", "bit_depth")
BATCH_ONLY_PARAMS = ("variants",)
NOISE_STREAMS = 2  # s0, s1; a later layer takes index 2


class FxParamsError(ValueError):
    """Raised when fx parameters do not match the contract; the message lists every problem."""


@cache
def _schema() -> dict[str, Any]:
    return load_schema(FX_SCHEMA_FILE)


@cache
def _branches() -> tuple[tuple[Draft202012Validator, dict[str, Any]], ...]:
    return tuple(
        (Draft202012Validator(b["if"]), b["then"]["properties"]) for b in _schema()["allOf"]
    )


# --- resolution --------------------------------------------------------------------------------


def resolve_fx_params(params: dict[str, Any]) -> dict[str, Any]:
    """Validate against the contract and return the resolved form (new dict, defaults filled).

    Unknown, missing, out-of-range or non-finite fields and violations of cross-field rules A-C
    are rejected, never clamped. Resolving a resolved form returns it unchanged.
    """
    if not isinstance(params, dict):
        raise FxParamsError(f"FX parameters must be an object, got {type(params).__name__}.")
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
        raise FxParamsError("Invalid fx parameters:\n" + "\n".join(lines))
    resolved = dict(params)
    for key in INTEGER_FIELDS:
        if isinstance(resolved.get(key), float):
            resolved[key] = int(resolved[key])
    for name, prop in schema["properties"].items():
        if name not in resolved and "default" in prop:
            resolved[name] = prop["default"]
    for check, props in _branches():
        if check.is_valid(params):
            for name, prop in props.items():
                if name not in resolved and "default" in prop:
                    resolved[name] = prop["default"]
    for name in DERIVED:
        resolved.setdefault(name, resolved["length_beats"])
    lines = cross_field_errors(resolved)
    if lines:
        raise FxParamsError("Invalid fx parameters:\n" + "\n".join(lines))
    return resolved


def cross_field_errors(p: dict[str, Any]) -> list[str]:
    """Rules A-C of the contract ($comment points 1, 2, 6) as error lines."""
    out = []
    ms = file_ms(p)
    if ms > MAX_FILE_MS * (1.0 + 1e-12):
        out.append(
            f"- length_beats + tail_beats: the file would be {ms:.1f} ms at {p['bpm']} BPM; "
            f"at most {MAX_FILE_MS:.0f} ms (rule A)"
        )
    if p["noise_level"] == 0 and p["tone_level"] == 0:
        out.append("- noise_level and tone_level are both 0: the file would be silent (rule B)")
    if p["cut_beats"] >= p["length_beats"]:
        out.append(
            f"- cut_beats {p['cut_beats']} must be smaller than length_beats "
            f"{p['length_beats']} (rule C)"
        )
    return out


def file_ms(p: dict[str, Any]) -> float:
    return (p["length_beats"] + p["tail_beats"]) * 60000.0 / p["bpm"]


def samples_per_beat(p: dict[str, Any]) -> float:
    return 60.0 * int(p["sample_rate"]) / p["bpm"]


def file_samples(p: dict[str, Any]) -> int:
    """Frames of the file: ``round((length_beats + tail_beats) * 60 * sr / bpm)`` (point 1)."""
    return int(round((p["length_beats"] + p["tail_beats"]) * 60.0 * int(p["sample_rate"])
                     / p["bpm"]))


def boundary_frame(p: dict[str, Any]) -> int:
    """``round(length_beats * 60 * sr / bpm)`` for every kind (point 1); N for reverse_crash."""
    return int(round(p["length_beats"] * 60.0 * int(p["sample_rate"]) / p["bpm"]))


def anchor(p: dict[str, Any]) -> str:
    return "end" if p["kind"] == "reverse_crash" else "start"


def render_fx(params: dict[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    """Render one FX file. Returns ``(audio (n, 2), resolved_params)``."""
    p = resolve_fx_params(params)
    for key in BATCH_ONLY_PARAMS:
        p.pop(key, None)
    return render_resolved(p), p


def analyse_fx(audio: np.ndarray, sr: int, p: dict[str, Any]) -> dict[str, Any]:
    """Sidecar features: the laser's stereo features plus ``boundary_frame`` and ``anchor``."""
    features = analyse_laser(audio, sr)
    features["boundary_frame"] = boundary_frame(p)
    features["anchor"] = anchor(p)
    return features


# --- platform-independent elementary functions -------------------------------------------------
# Only +, -, *, / (IEEE, correctly rounded everywhere), np.floor, np.frexp / np.ldexp (exact).

LN2 = 0.6931471805599453
LOG2_10 = 3.321928094887362
TWO_PI = 6.283185307179586
SQRT_HALF = 0.7071067811865476
_EXP_TERMS = 22  # Taylor of exp(r) for |r| <= ln2 / 2: last term < 1e-30
_LOG_TERMS = 14  # atanh series in s, |s| <= 0.1716: s^29 / 29 < 1e-23
_SIN_TERMS = 12  # Taylor of sin(x) for |x| <= pi / 2: x^25 / 25! < 1e-20


def exp2(y: np.ndarray) -> np.ndarray:
    """``2 ** y`` from a Taylor series (relative error ~1e-16)."""
    y = np.asarray(y, dtype=np.float64)
    k = np.floor(y + 0.5)
    r = (y - k) * LN2  # |r| <= ln2 / 2
    acc = np.ones_like(r)
    for i in range(_EXP_TERMS, 0, -1):
        acc = 1.0 + acc * r / float(i)
    return np.ldexp(acc, k.astype(np.int64))


def log2(x: np.ndarray) -> np.ndarray:
    """``log2(x)`` for ``x > 0`` from the atanh series of the mantissa."""
    x = np.asarray(x, dtype=np.float64)
    m, e = np.frexp(x)  # x = m * 2^e, m in [0.5, 1)
    low = m < SQRT_HALF
    m = np.where(low, m * 2.0, m)
    e = np.where(low, e - 1, e).astype(np.float64)
    s = (m - 1.0) / (m + 1.0)
    s2 = s * s
    acc = np.zeros_like(s)
    for i in range(_LOG_TERMS, -1, -1):
        acc = 1.0 / float(2 * i + 1) + acc * s2
    return e + 2.0 * s * acc / LN2


def _sin_reduced(v: np.ndarray) -> np.ndarray:
    """``sin(2 pi v)`` for ``v`` in [-0.25, 0.25]."""
    x = TWO_PI * v
    x2 = x * x
    acc = np.zeros_like(x)
    for i in range(_SIN_TERMS, -1, -1):
        acc = 1.0 / _factorial(2 * i + 1) * (-1.0) ** i + acc * x2
    return x * acc


@cache
def _factorial(n: int) -> float:
    return float(math.factorial(n))


def sin_cycles(u: np.ndarray) -> np.ndarray:
    """``sin(2 pi u)`` for any finite ``u`` (reduced to [-1/4, 1/4] of a cycle exactly)."""
    u = np.asarray(u, dtype=np.float64)
    v = u - np.floor(u + 0.5)  # [-0.5, 0.5)
    v = np.where(v > 0.25, 0.5 - v, v)
    v = np.where(v < -0.25, -0.5 - v, v)
    return _sin_reduced(v)


def cos_cycles(u: np.ndarray) -> np.ndarray:
    return sin_cycles(np.asarray(u, dtype=np.float64) + 0.25)


def tan_half_cycles(u: np.ndarray) -> np.ndarray:
    """``tan(pi u)`` for ``u`` in [0, 0.46] (the filter prewarp ``tan(pi fc / sr)``)."""
    half = np.asarray(u, dtype=np.float64) * 0.5
    return sin_cycles(half) / cos_cycles(half)


def db_to_gain(db: np.ndarray) -> np.ndarray:
    return exp2(np.asarray(db, dtype=np.float64) * (LOG2_10 / 20.0))


def power(base: np.ndarray, exponent: float) -> np.ndarray:
    """``base ** exponent`` for ``base`` in [0, 1] (0 ** e = 0)."""
    base = np.asarray(base, dtype=np.float64)
    if exponent == 1.0:
        return base.copy()
    out = np.zeros_like(base)
    pos = base > 0.0
    out[pos] = exp2(exponent * log2(base[pos]))
    return out


# --- curves (contract points 3-5) --------------------------------------------------------------


def _progress(t: np.ndarray, beats: float) -> np.ndarray:
    return np.minimum(1.0, t / beats)


def exp_glide(start: float, end: float, s: np.ndarray) -> np.ndarray:
    """``start * (end / start) ^ s`` for ``s`` in [0, 1]."""
    if start == end:
        return np.full(len(s), float(start))
    ratio = float(log2(np.array([end / start]))[0])
    return start * exp2(ratio * s)


def cutoff_track(p: dict[str, Any], t: np.ndarray) -> np.ndarray:
    s = power(_progress(t, p["length_beats"]), float(p["sweep_curve"]))
    return exp_glide(float(p["cutoff_start_hz"]), float(p["cutoff_end_hz"]), s)


def level_db(p: dict[str, Any], t: np.ndarray) -> np.ndarray:
    s = power(_progress(t, p["ramp_beats"]), float(p["level_curve"]))
    return p["level_start_db"] + (p["level_end_db"] - p["level_start_db"]) * s


def tone_hz(p: dict[str, Any], t: np.ndarray) -> np.ndarray:
    s = _progress(t, p["tone_glide_beats"])
    return exp_glide(float(p["tone_start_hz"]), float(p["tone_end_hz"]), s)


# --- noise and filter --------------------------------------------------------------------------


def noise_layer(p: dict[str, Any], n: int) -> np.ndarray:
    s0, s1 = (g.standard_normal(n) for g in substreams(p["seed"], NOISE_STREAMS))
    c = 1.0 - float(p["stereo_width"])
    right = s0.copy() if c == 1.0 else c * s0 + math.sqrt(1.0 - c * c) * s1
    x = np.stack([s0, right], axis=1)
    if p["noise_color"] == "pink" and n:
        x = np.stack([_pink(x[:, ch], int(p["sample_rate"])) for ch in (0, 1)], axis=1)
    return x


def _pink(x: np.ndarray, sr: int) -> np.ndarray:
    n = len(x)
    freqs = np.arange(n // 2 + 1, dtype=np.float64) * (sr / n)
    shape = np.zeros(len(freqs))
    keep = freqs >= PINK_LOW_HZ
    shape[keep] = np.sqrt(PINK_REF_HZ / freqs[keep])
    y = np.fft.irfft(np.fft.rfft(x) * shape, n)
    ry = math.sqrt(float(np.mean(y * y)))
    return y * (math.sqrt(float(np.mean(x * x))) / ry) if ry > 0.0 else y


def svf(x: np.ndarray, fc: np.ndarray, q: float, mode: str, sr: int) -> np.ndarray:
    """Zavalishin TPT state-variable filter, cutoff ``fc[i]`` at sample ``i`` (point 3).

    ``mode``: ``bp`` (band-pass times 1 / q, 0 dB peak), ``lp`` or ``hp``.
    """
    g = tan_half_cycles(fc / sr)
    k = 1.0 / q
    a1 = 1.0 / (1.0 + g * (g + k))
    a2 = g * a1
    a3 = g * a2
    xs, a1l, a2l, a3l = x.tolist(), a1.tolist(), a2.tolist(), a3.tolist()
    y = [0.0] * len(xs)
    ic1 = ic2 = 0.0
    for i in range(len(xs)):
        xi = xs[i]
        v3 = xi - ic2
        v1 = a1l[i] * ic1 + a2l[i] * v3
        v2 = ic2 + a2l[i] * ic1 + a3l[i] * v3
        ic1 = 2.0 * v1 - ic1
        ic2 = 2.0 * v2 - ic2
        if mode == "bp":
            y[i] = k * v1
        elif mode == "lp":
            y[i] = v2
        else:
            y[i] = xi - k * v1 - v2
    return np.array(y, dtype=np.float64)


def filter_noise(x: np.ndarray, p: dict[str, Any], t: np.ndarray) -> np.ndarray:
    sr = int(p["sample_rate"])
    fc = cutoff_track(p, t)
    mode, q = p["filter_mode"], float(p["filter_q"])

    def one(ch: np.ndarray) -> np.ndarray:
        if mode != "hp_lp":
            return svf(ch, fc, q, mode, sr)
        lp_fc = np.minimum(fc * float(p["lp_ratio"]), NYQUIST_SHARE * sr)
        return svf(svf(ch, fc, q, "hp", sr), lp_fc, HP_LP_Q, "lp", sr)

    left = one(x[:, 0])
    right = left.copy() if np.array_equal(x[:, 0], x[:, 1]) else one(x[:, 1])
    return np.stack([left, right], axis=1)


# --- tone --------------------------------------------------------------------------------------


def _phase_cycles(f: np.ndarray, sr: int) -> np.ndarray:
    cyc = np.zeros(len(f))
    if len(f) > 1:
        cyc[1:] = np.cumsum(f[:-1] / sr)
    return cyc


def _partial_weight(kf: np.ndarray, sr: int) -> np.ndarray:
    lo, hi = PARTIAL_FADE_START * sr, NYQUIST_SHARE * sr
    return np.clip((hi - kf) / (hi - lo), 0.0, 1.0)


def _additive(cyc: np.ndarray, f: np.ndarray, sr: int, odd_only: bool, alternate: bool
              ) -> np.ndarray:
    """``sum_k w_k(t) sign_k sin(2 pi k cyc) / k`` with sin(k x) by the Chebyshev recurrence.

    Evaluated in blocks of :data:`ADDITIVE_BLOCK` samples (#503). Every sample gets exactly the
    same sequence of floating-point operations as one pass over the whole file, so the bytes do
    not change; the speed comes from three exact shortcuts: a block stops at the first partial
    whose weight is 0 at the block's lowest frequency (all later terms are exactly 0), the
    weight is not computed where it is 1 at the block's highest frequency (``x * 1.0 == x``),
    and the arrays of a block stay in the CPU cache.
    """
    n = len(cyc)
    out = np.zeros(n)
    hi = NYQUIST_SHARE * sr
    for a in range(0, n, ADDITIVE_BLOCK):
        b = min(n, a + ADDITIVE_BLOCK)
        fb = f[a:b]
        fmin, fmax = float(np.min(fb)), float(np.max(fb))
        cur = sin_cycles(cyc[a:b])
        two_c = 2.0 * cos_cycles(cyc[a:b])
        prev = np.zeros(b - a)
        nxt = np.empty(b - a)
        term = np.empty(b - a)
        acc = out[a:b]
        k = 1
        while k * fmin < hi:
            if not odd_only or k % 2 == 1:
                sign = -1.0 if (alternate and k % 2 == 0) else 1.0
                if float(_partial_weight(np.array([k * fmax]), sr)[0]) == 1.0:
                    # every weight in the block is exactly 1: (s / k) * 1.0 * cur == (s / k) * cur
                    np.multiply(sign / k, cur, out=term)
                else:
                    np.multiply((sign / k) * _partial_weight(k * fb, sr), cur, out=term)
                acc += term
            # next = 2 cos(x) * cur - prev, written into reused buffers (same two roundings)
            np.multiply(two_c, cur, out=nxt)
            np.subtract(nxt, prev, out=nxt)
            prev, cur, nxt = cur, nxt, prev
            k += 1
    return out


def tone_layer(p: dict[str, Any], t: np.ndarray) -> np.ndarray:
    sr = int(p["sample_rate"])
    f = tone_hz(p, t)
    wave = p["tone_wave"]
    if wave == "metal":
        out = np.zeros(len(t))
        for fi in METAL_HZ:
            ff = f * (fi / METAL_BASE_HZ)
            out += (4.0 / math.pi) * _additive(_phase_cycles(ff, sr), ff, sr, True, False)
        osc = out / len(METAL_HZ)
    else:
        cyc = _phase_cycles(f, sr)
        if wave == "sine":
            osc = sin_cycles(cyc) * _partial_weight(f, sr)
        elif wave == "saw":
            osc = (2.0 / math.pi) * _additive(cyc, f, sr, False, True)
        else:
            osc = (4.0 / math.pi) * _additive(cyc, f, sr, True, False)
    if p["tone_decay_beats"] > 0:
        env = db_to_gain(-60.0 * t / p["tone_decay_beats"])
    else:
        env = db_to_gain(level_db(p, t))
    return float(p["tone_level"]) * env * osc


# --- assembly ----------------------------------------------------------------------------------


def _linear_fade(n: int, stop: int, sr: int) -> np.ndarray:
    """Gain 1 before ``stop - F``, linear from 1 to 0 over the F = 5 ms samples ending at
    ``stop`` (the last of them is 0), 0 from ``stop`` on."""
    f = max(2, int(round(FADE_MS * sr / 1000.0)))
    g = np.ones(n)
    stop = max(0, min(n, stop))
    g[stop:] = 0.0
    ramp = np.linspace(1.0, 0.0, f)
    lo = stop - f
    g[max(0, lo):stop] = ramp[max(0, -lo):]
    return g


def dry_signal(p: dict[str, Any]) -> np.ndarray:
    """Noise + tone in file time, with the dry end of point 6. Shape ``(n, 2)``."""
    sr = int(p["sample_rate"])
    n = file_samples(p)
    t = np.arange(n, dtype=np.float64) / samples_per_beat(p)
    dry = np.zeros((n, 2))
    if p["noise_level"] > 0:
        gain = float(p["noise_level"]) * db_to_gain(level_db(p, t))
        dry += filter_noise(noise_layer(p, n), p, t) * gain[:, None]
    if p["tone_level"] > 0:
        dry += tone_layer(p, t)[:, None]
    end = int(round((p["length_beats"] - p["cut_beats"]) * samples_per_beat(p)))
    return dry * _linear_fade(n, end, sr)[:, None]


def _chain(x: np.ndarray, p: dict[str, Any]) -> np.ndarray:
    sr = int(p["sample_rate"])
    if p["drive"] > 0 and len(x):
        peak = float(np.max(np.abs(x)))
        if peak > 0.0:
            x = np.stack([_drive(x[:, c] / peak, p["drive"]) for c in (0, 1)], axis=1)
    if p["echo_mix"] > 0 and len(x):
        d = max(1, int(round(laser_fx.note_ms(p["echo_note"], float(p["bpm"])) * sr / 1000.0)))
        x = laser_fx.echo_v2(x, p, d)
    if p["reverb_mix"] > 0 and len(x):
        x = x + float(p["reverb_mix"]) * laser_fx.reverb_wet(x, p)
    return x


def pump_gain(p: dict[str, Any], n: int) -> np.ndarray:
    i = np.arange(n, dtype=np.float64)
    beats = (i - n) / samples_per_beat(p) if anchor(p) == "end" else i / samples_per_beat(p)
    phi = beats - np.floor(beats)
    q = 1.0 - phi
    q2 = q * q  # (1 - phi)^4 by two multiplications: ``** 4`` would call the platform pow
    return 1.0 - float(p["pump_depth"]) * (q2 * q2)


def render_resolved(p: dict[str, Any]) -> np.ndarray:
    """Render already resolved parameters (no validation). Shape ``(n, 2)``."""
    sr = int(p["sample_rate"])
    n = file_samples(p)
    x = dry_signal(p)
    if p["kind"] == "reverse_crash":
        x = _chain(x[::-1].copy(), p)[::-1].copy()
    else:
        x = _chain(x, p)
    if p["pump_depth"] > 0:
        x = x * pump_gain(p, n)[:, None]
    x = x * _linear_fade(n, n, sr)[:, None]
    return _normalise(x, p["peak_ceiling_dbfs"], p["bit_depth"])
