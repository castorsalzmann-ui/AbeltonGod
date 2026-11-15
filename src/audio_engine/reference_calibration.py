"""Scale calibration for reference features (#540, E3 of the reference-steering-v2 note).

Run outside CI; the output is committed as data (``calibration/reference_scales.json``)::

    python -m audio_engine.reference_calibration --write

(add ``-o pythonpath=src``-style path setup in a worktree: ``PYTHONPATH=src python -m ...``).

For each category (kick, bass) the candidate set is every preset with variants 0 ... 7 of its
``make_variants`` (variant 0 is the preset itself). All values are in the transformed units of
:data:`audio_engine.reference_v2.FEATURES` (semitones, ln, dB, shares).

- **Seed spread** of a candidate: max - min of the feature over seeds 1 ... 8 (the candidate's
  parameters with ``seed`` replaced). The category value is the mean over candidates (note
  rule 2.4 (a)); the largest candidate value is stored as ``seed_spread_max``.
- **Between-candidate spread**: max - min over candidates of the per-candidate seed means.
- **Method error** of a candidate: the largest deviation of the feature from

  1. the same parameters rendered at 44.1 kHz (the reader takes both rates),
  2. the same parameters rendered at 16 bit,
  3. the known value, where the engine defines one: kick pitch at t (the contract's pitch
     curve at the onset-relative time), kick ``fundamental_hz`` (mean body frequency over the
     tail window, from the analytic phase of the pitch curve); bass ``note_hz`` (the note
     f0, or f0 / 2 when a sub-octave is on, whichever is nearer: both are periods of the
     waveform, the table counts how often f0 / 2 was nearer), and on the *neutral* render
     (``drive`` 0, ``lp_env_amount`` 0, as contract rule 8 verifies fields) ``gate_ms`` (gate
     plus offset minus the onset time), ``release_ms`` (0.99 x ``release_ms``, where the
     ramp is at -40 dB) and ``attack_ms`` (0.8 x ``amp_attack_ms``, 10 to 90 % of the ramp).

  The category value is the mean over candidates; the largest is ``method_error_max``.
  A check where one side is ``None`` is not counted as a deviation; such checks are counted
  in ``none_checks``.
- **Degrade error** of a candidate (#563): the largest deviation of the feature between the
  candidate's render and *degraded copies of the same samples* (:data:`DEGRADATIONS`: resampled
  to 44.1 and 96 kHz, 16 bit with TPDF dither, gain below and above full scale, DC offset,
  silence in front, a few samples cut at both ends). A user's reference is a file that went
  through other tools; this is the reading error such a round trip adds. The category value
  is the mean over candidates; ``degrade_error_max`` is the largest candidate value and
  ``degrade_max_by`` the largest per degradation. A copy where the feature is measured on one
  side and ``None`` on the other is not a deviation; it is counted in ``degrade_none_checks``.
- **Scale** = max(method error, degrade error, seed spread) (note rule 2.3, lead decision of
  2026-11-09: no floor at the provisional scale); **weight** = 0 when the seed spread is at
  least a third of the between-candidate spread, else 1 (rule 2.4 (a), see
  :func:`audio_engine.reference_v2.weight_for`).
- **Self-distance** (``self_distance`` per category): the total distance, with the new
  scales, between each candidate and each of its degraded copies. It shows what the mean
  aggregation leaves over: a pair above 1 is a copy of the same audio that reads as more
  than one scale unit away.

Values are rounded to 6 decimals before scale and weight are derived, so the committed table
is consistent with itself (a test checks this). No wall clock and no global random numbers
(the dither uses its own ``PCG64`` generator with a fixed seed): the same engine and NumPy
build give the same table.
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import sys
from collections.abc import Callable
from typing import Any

import numpy as np

from . import ENGINE_VERSION
from . import reference_v2 as V
from .analysis import tail_window
from .bass import BASS_VERSION, BassParamsError, note_frequency, resolve_bass_params
from .bass import render_resolved as render_bass_resolved
from .bass_variants import make_variants as bass_variants
from .kick import render_resolved as render_kick_resolved
from .params import KickParamsError, resolve_kick_params
from .presets import load_preset, preset_names
from .reference import onset_index
from .variants import make_variants as kick_variants

SEEDS = tuple(range(1, 9))
VARIANTS = 8
COMMAND = "PYTHONPATH=src python -m audio_engine.reference_calibration --write"
DECIMALS = 6


# --- pure statistics (tested on synthetic numbers) ---------------------------------------------

def spread_stats(per_candidate: list[list[float | None]]) -> dict[str, float | int]:
    """Seed and between-candidate spreads of one feature (transformed values).

    ``per_candidate[c][s]`` is the value of candidate c at seed s, ``None`` when not measured.
    Candidates without any value are left out; a candidate with some ``None`` uses its other
    values and is counted in ``mixed_none``.
    """
    spreads, means, mixed = [], [], 0
    for values in per_candidate:
        got = [v for v in values if v is not None]
        if not got:
            continue
        if len(got) < len(values):
            mixed += 1
        spreads.append(max(got) - min(got))
        means.append(sum(got) / len(got))
    if not spreads:
        return {"seed_spread": 0.0, "seed_spread_max": 0.0, "between_spread": 0.0,
                "candidates_measured": 0, "mixed_none": mixed}
    return {
        "seed_spread": round(statistics.fmean(spreads), DECIMALS),
        "seed_spread_max": round(max(spreads), DECIMALS),
        "between_spread": round(max(means) - min(means), DECIMALS),
        "candidates_measured": len(spreads),
        "mixed_none": mixed,
    }


def scale_and_weight(method_error: float, degrade_error: float, seed_spread: float,
                     between_spread: float) -> tuple[float, float]:
    """(scale, weight) of one feature from its rounded statistics (rules 2.3 and 2.4 (a))."""
    return (max(method_error, degrade_error, seed_spread),
            V.weight_for(seed_spread, between_spread))


# --- degraded copies (#563; tested on synthetic signals) ---------------------------------------

# Sinc zero crossings on each side of the resampling kernel, counted at the lower of the two
# rates: 64 gives a 2 kHz transition band at 44.1 kHz with the window below.
RESAMPLE_ZEROS = 64
# Kaiser window parameter: about 90 dB stop band, below the 16-bit noise of the dither copy.
RESAMPLE_BETA = 8.6
# -6 dB point as a share of the lower Nyquist frequency: the transition band (20.0 to
# 21.9 kHz for 44.1 kHz) then ends below Nyquist, so nothing folds back.
RESAMPLE_CUTOFF = 0.95
RESAMPLE_RATES = (44100, 96000)  # the two other rates the v2 reader takes
DITHER_SEED = 563  # the issue number; any fixed seed gives a deterministic table
DITHER_FULL_SCALE = 32768.0  # the reader divides 16-bit samples by this
GAIN_LOW_DB = -12.0  # the issue's value: a file exported with headroom
GAIN_OVER_DB = 6.0  # float copy with peaks above full scale, which the v2 reader keeps
DC_OFFSET = 0.01  # 1 % of full scale (-40 dBFS): large for a converter offset, far below clipping
PAD_FRONT_MS = 10.0  # silence in front; features are counted from the onset
CUT_SAMPLES = 8  # cut at both ends (0.17 ms at 48 kHz): an edit that is not on the first sample


def _kernel(t: np.ndarray, fc: float, half: float) -> np.ndarray:
    """Kaiser-windowed sinc low-pass at ``fc`` (share of Nyquist), ``t`` in input samples."""
    inside = np.abs(t) < half
    w = np.zeros_like(t)
    w[inside] = np.i0(RESAMPLE_BETA * np.sqrt(1.0 - (t[inside] / half) ** 2)) \
        / np.i0(RESAMPLE_BETA)
    return fc * np.sinc(fc * t) * w


def resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    """Band-limited resampling of the samples (polyphase windowed sinc, NumPy only).

    Output sample n sits at input time n * sr_in / sr_out; the output has
    ceil(len * sr_out / sr_in) samples. Each polyphase row is normalised to sum 1, so a
    constant stays the same constant at every output phase. Samples outside the input count
    as 0. Mono or ``(n, channels)``.
    """
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 2:
        return np.stack([resample(x[:, c], sr_in, sr_out) for c in range(x.shape[1])], axis=1)
    if sr_in == sr_out:
        return x.copy()
    g = math.gcd(sr_in, sr_out)
    up, down = sr_out // g, sr_in // g
    fc = RESAMPLE_CUTOFF * min(1.0, up / down)
    half = RESAMPLE_ZEROS / fc
    h = math.ceil(half)
    k = np.arange(-h + 1, h + 1, dtype=np.float64)  # taps j = i0 + k
    phases = np.arange(up, dtype=np.float64)[:, None] / up
    coeff = _kernel(phases - k[None, :], fc, half)
    coeff /= np.sum(coeff, axis=1, keepdims=True)
    n_out = -(-len(x) * up // down)
    pos = np.arange(n_out, dtype=np.int64) * down
    i0, phase = pos // up, pos % up
    windows = np.lib.stride_tricks.sliding_window_view(
        np.concatenate([np.zeros(h), x, np.zeros(h + 1)]), 2 * h)
    out = np.empty(n_out)
    for a in range(0, n_out, 8192):
        b = min(a + 8192, n_out)
        out[a:b] = np.einsum("nk,nk->n", windows[i0[a:b] + 1], coeff[phase[a:b]])
    return out


def dither_16bit(x: np.ndarray, seed: int = DITHER_SEED) -> np.ndarray:
    """16-bit quantisation with TPDF dither of +-1 LSB (own ``PCG64`` generator)."""
    x = np.asarray(x, dtype=np.float64)
    rng = np.random.Generator(np.random.PCG64(seed))
    tpdf = rng.random(x.shape) - rng.random(x.shape)
    q = np.clip(np.rint(x * DITHER_FULL_SCALE + tpdf), -DITHER_FULL_SCALE,
                DITHER_FULL_SCALE - 1.0)
    return q / DITHER_FULL_SCALE


def pad_front(x: np.ndarray, sr: int, ms: float = PAD_FRONT_MS) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    n = int(round(ms * sr / 1000.0))
    return np.concatenate([np.zeros((n, *x.shape[1:])), x])


def cut_edges(x: np.ndarray, samples: int = CUT_SAMPLES) -> np.ndarray:
    return np.asarray(x, dtype=np.float64)[samples:len(x) - samples].copy()


# name -> (text for the table header, function (audio, sr) -> (audio, sr))
DEGRADATIONS: dict[str, tuple[str, Callable[[np.ndarray, int], tuple[np.ndarray, int]]]] = {
    "resample_44k1": (
        "resampled to 44100 Hz (polyphase Kaiser-windowed sinc)",
        lambda x, sr: (resample(x, sr, 44100), 44100)),
    "resample_96k": (
        "resampled to 96000 Hz (polyphase Kaiser-windowed sinc)",
        lambda x, sr: (resample(x, sr, 96000), 96000)),
    "dither_16bit": (
        "16 bit, TPDF dither of +-1 LSB, PCG64 with the fixed seed",
        lambda x, sr: (dither_16bit(x), sr)),
    "gain_low": (
        "gain of GAIN_LOW_DB, float",
        lambda x, sr: (np.asarray(x, dtype=np.float64) * 10.0 ** (GAIN_LOW_DB / 20.0), sr)),
    "gain_over": (
        "gain of GAIN_OVER_DB, float, peaks above full scale",
        lambda x, sr: (np.asarray(x, dtype=np.float64) * 10.0 ** (GAIN_OVER_DB / 20.0), sr)),
    "dc_offset": (
        "DC_OFFSET added to every sample",
        lambda x, sr: (np.asarray(x, dtype=np.float64) + DC_OFFSET, sr)),
    "pad_front": (
        "PAD_FRONT_MS of silence in front",
        lambda x, sr: (pad_front(x, sr), sr)),
    "cut_edges": (
        "CUT_SAMPLES samples cut at the start and at the end",
        lambda x, sr: (cut_edges(x), sr)),
}
DEGRADE_CONSTANTS = {
    "RESAMPLE_ZEROS": RESAMPLE_ZEROS, "RESAMPLE_BETA": RESAMPLE_BETA,
    "RESAMPLE_CUTOFF": RESAMPLE_CUTOFF, "DITHER_SEED": DITHER_SEED,
    "GAIN_LOW_DB": GAIN_LOW_DB, "GAIN_OVER_DB": GAIN_OVER_DB, "DC_OFFSET": DC_OFFSET,
    "PAD_FRONT_MS": PAD_FRONT_MS, "CUT_SAMPLES": CUT_SAMPLES,
}


def degraded_features(category: str, audio: np.ndarray, sr: int) \
        -> dict[str, dict[str, float | None]]:
    """Features of every degraded copy of ``audio`` (degradation name -> features)."""
    out = {}
    for name, (_, fn) in DEGRADATIONS.items():
        y, rate = fn(audio, sr)
        out[name] = V.features_from_audio(category, y, rate)
    return out


def degrade_deviations(category: str, base: dict[str, float | None],
                       copies: dict[str, dict[str, float | None]]) \
        -> tuple[dict[str, dict[str, float]], dict[str, int]]:
    """Per feature: |T(copy) - T(base)| per degradation, and the one-sided ``None`` count."""
    devs: dict[str, dict[str, float]] = {}
    nones: dict[str, int] = {}
    for n in V.FEATURES[category]:
        b = _t(category, n, base[n])
        devs[n], nones[n] = {}, 0
        for name, feats in copies.items():
            v = _t(category, n, feats[n])
            if (v is None) != (b is None):
                nones[n] += 1
            elif v is not None:
                devs[n][name] = abs(v - b)
    return devs, nones


def self_distance_stats(category: str, rows: dict[str, Any],
                        pairs: list[tuple[str, dict, dict[str, dict]]]) -> dict[str, Any]:
    """Total distance between each candidate and each degraded copy with the scales of ``rows``."""
    table = V.feature_table(category, {"categories": {category: {"features": rows}}})
    totals, worst, missing = [], None, 0
    by: dict[str, list[float]] = {name: [] for name in DEGRADATIONS}
    for label, base, copies in pairs:
        for name, feats in copies.items():
            per = V.feature_distances(category, base, feats, table)
            total = V.total_distance(category, per, table)
            totals.append(total)
            by[name].append(total)
            missing += any((base[n] is None) != (feats[n] is None) for n in table)
            if worst is None or total > worst[0]:
                feature = max((n for n in per if table[n].weight > 0), key=lambda n: per[n])
                worst = (total, label, name, feature, per[feature])
    return {
        "pairs": len(totals),
        "pairs_with_one_sided_none": missing,
        "median": round(float(np.median(totals)), DECIMALS),
        "p95": round(float(np.percentile(totals, 95)), DECIMALS),
        "max": round(worst[0], DECIMALS),
        "max_candidate": worst[1],
        "max_degradation": worst[2],
        "max_feature": worst[3],
        "max_feature_distance": round(worst[4], DECIMALS),
        "by_degradation": {name: {"median": round(float(np.median(v)), DECIMALS),
                                  "max": round(max(v), DECIMALS)} for name, v in by.items()},
    }


# --- engine renders ----------------------------------------------------------------------------

def _t(category: str, name: str, value: float | None) -> float | None:
    return None if value is None else V.transform(V.FEATURES[category][name][0], value)


def _kick_known(p: dict[str, Any], audio: np.ndarray) -> dict[str, float]:
    """Known kick values of a render: pitch curve at the feature times and tail mean pitch."""
    sr = int(p["sample_rate"])
    fs, fe, tau = p["pitch_start_hz"], p["pitch_end_hz"], p["pitch_decay_ms"] / 1000.0
    n_off = int(round(p.get("offset_ms", 0) * sr / 1000.0))
    on = onset_index(audio - np.mean(audio))
    t0 = (on - n_off) / sr  # body time of the onset

    def freq(t: float) -> float:
        return fe + (fs - fe) * math.exp(-t / tau)

    def phase(t: float) -> float:  # 2 pi times this is the body phase
        return fe * t + (fs - fe) * tau * (1.0 - math.exp(-t / tau))

    out = {f"pitch_{ms:g}ms_hz": freq(t0 + ms / 1000.0) for ms in V.PITCH_TIMES_MS}
    x = V.prepare_signal(audio)
    a, b = tail_window(x, sr)
    if b > a:
        ta, tb = t0 + a / sr, t0 + b / sr
        out["fundamental_hz"] = (phase(tb) - phase(ta)) / (tb - ta)
    return out


def _bass_known(p: dict[str, Any], audio: np.ndarray, f: dict[str, float | None]) \
        -> tuple[dict[str, float], bool]:
    """Known bass values; the flag says f0 / 2 was the nearer note."""
    f0 = note_frequency(p["note"], p["cents"])
    out: dict[str, float] = {}
    octave = False
    if f["note_hz"] is not None:
        out["note_hz"] = f0
        if p["sub_octave_level"] > 0 and abs(math.log(f["note_hz"] / (f0 / 2))) < \
                abs(math.log(f["note_hz"] / f0)):
            out["note_hz"], octave = f0 / 2, True
    return out, octave


def _bass_neutral_known(p: dict[str, Any], audio: np.ndarray) -> dict[str, float]:
    sr = int(p["sample_rate"])
    on_ms = onset_index(audio - np.mean(audio)) / sr * 1000.0
    return {"gate_ms": p["gate_ms"] + p["offset_ms"] - on_ms,
            "release_ms": 0.99 * p["release_ms"],
            "attack_ms": 0.8 * p["amp_attack_ms"]}


def _candidates(category: str) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for name in preset_names(category):
        base = load_preset(name, category)
        variants = kick_variants(base, VARIANTS) if category == "kick" else \
            bass_variants(base, VARIANTS)
        out += [(f"{name} v{i}", p) for i, p in enumerate(variants)]
    return out


def _resolver(category: str) -> tuple[Callable, Callable, tuple[type, ...]]:
    if category == "kick":
        return resolve_kick_params, render_kick_resolved, (KickParamsError,)
    return resolve_bass_params, render_bass_resolved, (BassParamsError,)


def _strip(p: dict[str, Any]) -> dict[str, Any]:
    q = dict(p)
    q.pop("variants", None)
    return q


def calibrate(category: str, log: Callable[[str], None] = lambda s: None) -> dict[str, Any]:
    """Measure the table rows of one category (module docstring)."""
    resolve, render, errors = _resolver(category)
    names = V.FEATURES[category]
    cands = _candidates(category)
    seed_values: dict[str, list[list[float | None]]] = {n: [] for n in names}
    method: dict[str, list[float]] = {n: [] for n in names}
    none_checks: dict[str, int] = dict.fromkeys(names, 0)
    degrade: dict[str, list[float]] = {n: [] for n in names}
    degrade_by: dict[str, dict[str, float]] = {n: dict.fromkeys(DEGRADATIONS, 0.0) for n in names}
    degrade_none: dict[str, int] = dict.fromkeys(names, 0)
    pairs: list[tuple[str, dict, dict[str, dict]]] = []
    octave = 0
    for label, p in cands:
        sr = int(p["sample_rate"])
        per_seed = []
        for s in SEEDS:
            q = _strip(resolve(dict(p, seed=s)))
            per_seed.append(V.features_from_audio(category, render(q), sr))
        for n in names:
            seed_values[n].append([_t(category, n, f[n]) for f in per_seed])
        audio = render(_strip(p))
        base = V.features_from_audio(category, audio, sr)
        copies = degraded_features(category, audio, sr)
        pairs.append((label, base, copies))
        devs_by, nones = degrade_deviations(category, base, copies)
        for n in names:
            degrade_none[n] += nones[n]
            if devs_by[n]:
                degrade[n].append(max(devs_by[n].values()))
            for name, d in devs_by[n].items():
                degrade_by[n][name] = max(degrade_by[n][name], d)
        checks: list[dict[str, float | None]] = []
        for change in ({"sample_rate": 44100}, {"bit_depth": 16}):
            try:
                q = _strip(resolve(dict(p, **change)))
            except errors:
                continue
            checks.append(V.features_from_audio(category, render(q), int(q["sample_rate"])))
        known: dict[str, float]
        if category == "kick":
            known = _kick_known(p, audio)
        else:
            known, oct_ = _bass_known(p, audio, base)
            octave += oct_
            try:
                neutral = _strip(resolve(dict(p, drive=0, lp_env_amount=0)))
                na = render(neutral)
                nf = V.features_from_audio(category, na, sr)
                for k, v in _bass_neutral_known(neutral, na).items():
                    if nf[k] is not None:
                        checks.append({k: nf[k], "__known__" + k: v})
                    else:
                        none_checks[k] += 1
            except errors:
                pass
        for n in names:
            devs = []
            b = _t(category, n, base[n])
            for c in checks:
                if "__known__" + n in c:
                    devs.append(abs(_t(category, n, c[n]) - _t(category, n, c["__known__" + n])))
                    continue
                if n not in c:
                    continue
                v = _t(category, n, c[n])
                if (v is None) != (b is None):
                    none_checks[n] += 1
                elif v is not None:
                    devs.append(abs(v - b))
            if n in known and known[n] > 0:
                if b is None:
                    none_checks[n] += 1
                else:
                    devs.append(abs(b - _t(category, n, known[n])))
            if devs:
                method[n].append(max(devs))
        log(f"{category} {label}")
    rows = {}
    for n, (kind, provisional) in names.items():
        st = spread_stats(seed_values[n])
        me = round(statistics.fmean(method[n]), DECIMALS) if method[n] else 0.0
        de = round(statistics.fmean(degrade[n]), DECIMALS) if degrade[n] else 0.0
        scale, weight = scale_and_weight(me, de, st["seed_spread"], st["between_spread"])
        rows[n] = {
            "transform": kind,
            "provisional_scale": round(provisional, DECIMALS),
            "method_error": me,
            "method_error_max": round(max(method[n]), DECIMALS) if method[n] else 0.0,
            "method_candidates": len(method[n]),
            "none_checks": none_checks[n],
            "degrade_error": de,
            "degrade_error_max": round(max(degrade[n]), DECIMALS) if degrade[n] else 0.0,
            "degrade_candidates": len(degrade[n]),
            "degrade_none_checks": degrade_none[n],
            "degrade_max_by": {k: round(v, DECIMALS) for k, v in degrade_by[n].items()},
            **st,
            "scale": scale,
            "weight": weight,
        }
    out = {"candidates": len(cands), "features": rows,
           "self_distance": self_distance_stats(category, rows, pairs)}
    if category == "bass":
        out["note_octave_below_nearer"] = octave
    return out


def build_table(log: Callable[[str], None] = lambda s: None) -> dict[str, Any]:
    return {
        "description": "Reference feature scales (reference steering v2, E3). Generated, "
                       "do not edit by hand.",
        "command": COMMAND,
        "seeds": list(SEEDS),
        "variants_per_preset": VARIANTS,
        "aggregation": "method_error, degrade_error and seed_spread: mean over candidates; "
                       "scale = max(method_error, degrade_error, seed_spread); weight 0 if "
                       "seed_spread >= between_spread / 3",
        "degradations": {name: text for name, (text, _) in DEGRADATIONS.items()},
        "degrade_constants": DEGRADE_CONSTANTS,
        "engines": {"kick": ENGINE_VERSION, "bass": BASS_VERSION},
        "numpy": np.__version__,
        "python": platform.python_version(),
        "categories": {c: calibrate(c, log) for c in V.CATEGORIES},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help=f"write {V.CALIBRATION_FILE}")
    args = ap.parse_args(argv)
    table = build_table(lambda s: print(s, file=sys.stderr))
    text = json.dumps(table, indent=2, sort_keys=True) + "\n"
    if args.write:
        V.CALIBRATION_FILE.parent.mkdir(parents=True, exist_ok=True)
        V.CALIBRATION_FILE.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
