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
- **Scale** = max(method error, seed spread) (note rule 2.3); **weight** = 0 when the seed
  spread is at least a third of the between-candidate spread, else 1 (rule 2.4 (a), see
  :func:`audio_engine.reference_v2.weight_for`).

Values are rounded to 6 decimals before scale and weight are derived, so the committed table
is consistent with itself (a test checks this). No wall clock, no random numbers: the same
engine and NumPy build give the same table.
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


def scale_and_weight(method_error: float, seed_spread: float, between_spread: float) \
        -> tuple[float, float]:
    """(scale, weight) of one feature from its rounded statistics (rules 2.3 and 2.4 (a))."""
    return max(method_error, seed_spread), V.weight_for(seed_spread, between_spread)


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
    x = V.prepare(audio)
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
        scale, weight = scale_and_weight(me, st["seed_spread"], st["between_spread"])
        rows[n] = {
            "transform": kind,
            "provisional_scale": round(provisional, DECIMALS),
            "method_error": me,
            "method_error_max": round(max(method[n]), DECIMALS) if method[n] else 0.0,
            "method_candidates": len(method[n]),
            "none_checks": none_checks[n],
            **st,
            "scale": scale,
            "weight": weight,
        }
    out = {"candidates": len(cands), "features": rows}
    if category == "bass":
        out["note_octave_below_nearer"] = octave
    return out


def build_table(log: Callable[[str], None] = lambda s: None) -> dict[str, Any]:
    return {
        "description": "Reference feature scales (#540, E3). Generated, do not edit by hand.",
        "command": COMMAND,
        "seeds": list(SEEDS),
        "variants_per_preset": VARIANTS,
        "aggregation": "method_error and seed_spread: mean over candidates; scale = "
                       "max(method_error, seed_spread); weight 0 if seed_spread >= "
                       "between_spread / 3",
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
