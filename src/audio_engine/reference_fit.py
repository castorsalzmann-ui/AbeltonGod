"""Reference steering v2, fit core for kick and bass (#564, E6 of the design note).

Design: ``docs/research/2026-11-08_reference-steering-v2.md`` sections 2 (rules 4-7), 4, 7, 8.
The fit searches engine parameters whose *measured features* lie nearer to those of a
reference. It never says, and nothing here may say, how a fit compares to the reference for
a listener (D-032): the report holds measured values, distances and counts only.

What is compared
----------------
- The explained features of :mod:`audio_engine.reference_v2` with the scales and weights of
  its calibration table (read at run time through :func:`reference_v2.feature_table`).
- A spectro-temporal **profile** (note rule 2.6, :func:`profile`): energy in
  :data:`PROFILE_BANDS` log-spaced bands from 30 Hz to 16 kHz in six time zones counted from
  the onset (:data:`PROFILE_ZONES_MS`), rectangular window per zone, dB relative to the
  largest cell, floored at -60 dB. Distance = RMS cell difference / 3 dB. A band edge inside
  an FFT bin counts that bin by its share (as ``reference_v2.body_energy_db``), and every zone
  is zero-padded to one FFT length, so 44.1, 48 and 96 kHz signals use the same bands.
  Kick zones are the note's; the bass zones are this module's choice: 0-10, 10-30, 30-60,
  60-120, 120-250, 250-500 ms (the first 30 ms are the window of ``filter_move_db``; a note
  longer than 500 ms is seen past that point only by ``gate_ms`` and ``release_ms``).
- **Total** = root of the weighted mean square over the features with weight > 0 plus the
  profile as one more feature of weight :data:`PROFILE_WEIGHT`.

Stages (:func:`fit_reference`)
------------------------------
0. **Start**: the nearest of the category's candidate set (:func:`candidate_set`: every
   preset x variants 0 ... 7, rendered and measured once per process). Ties go to the first
   in grid order. Its total is "before".
1. **Estimates**, each checked by a render and kept only if it lowers the total (otherwise
   the report says "Schätzung verworfen"). Kick: ``length_ms`` from the reference length
   (from the onset, limited to the contract range; not searched afterwards), ``pitch_end_hz``
   from the tail fundamental, ``amp_decay_ms`` from the -40 dB (else -20 dB) decay time. Bass:
   ``note`` / ``cents`` from ``note_hz``, then ``gate_ms`` and ``release_ms``. A value is
   estimated *relative to the current point* where both sides are measured (parameter x
   reference value / current value: the tail fundamental is a mean over the tail window, not
   the asymptote ``pitch_end_hz``), and directly otherwise; both are tried when both exist.
   Bass note: ``note_hz`` is the waveform period, which is f0 / 2 with a sub-octave. Two
   hypotheses are rendered, "note" (the note at ``note_hz``, ``sub_octave_level`` 0) and
   "note + sub_octave_level" (the note one octave above, sub-octave on at the start
   candidate's level, or :data:`SUB_OCTAVE_TRIAL_LEVEL` if that is 0); the lower total wins
   and the report names it. If the contract's ``hp_hz < 0.8 f0`` rule refuses a hypothesis, it
   is tried once more with ``hp_hz`` at the contract minimum, and the report says so.
2. **Coordinate search** over :data:`SEARCH` in the normalised space u in [0, 1] (log map
   for Hz, ms and ratio fields, linear otherwise; ranges from the contracts). Step 0.25; per
   pass and parameter, in the fixed order of :data:`SEARCH`, u + step then u - step, the first
   lower total is accepted; a pass without improvement halves the step; the search ends below
   1 / 256. u is limited to [0, 1], so every trial is inside the contract range; values are
   rounded to :data:`VALUE_DECIMALS` decimals. Every trial goes through the category's
   ``resolve``: a ``ValueError`` (pitch order, bass cross-field rules) is a rejected trial,
   counted in the report, never clamped. ``note``, ``cents``, ``length_ms`` and the seed are
   not searched; the fit uses the start candidate's seed and reports it (rule 2.7). No random
   numbers: the same reference, code and NumPy build give the same fit.

Not done here: the note's section 3.1 asks to keep ``pitch_decay_ms`` under
``params.max_settled_pitch_decay_ms`` during a kick fit. That guideline is not a contract
rule; the report states for the start and the fit whether it holds (``pitch_settles``).

Budget
------
``max_renders`` caps every render of one fit (stage 1, stage 2 and the determination check;
the cached candidate set is not counted). Stage 2 stops ``2 x len(SEARCH)`` renders early so
the determination check fits in. ``max_seconds`` is checked before every render against the
injected ``clock`` and starts when the candidate set is there; ``cancel`` is polled before
every render. A stopped fit returns the best point so far with its stop reason; parameters
whose determination check did not run carry ``determined: None``.

Report (:class:`FitResult`, ``report`` is JSON-serialisable)
------------------------------------------------------------
Per feature reference / start / fit value and distance before / after; total and profile
distance before / after; stage-1 entries; per searched parameter the start value, the fit
value and the **determination flag**: the total changes by less than
:data:`DETERMINATION_UNITS` for u - 1/32 and u + 1/32 = "von den Messwerten nicht festgelegt"
(the value is a start point, not a measurement). A side at the range edge or refused by the
contract gives no evidence. ``seconds`` and ``candidate_seconds`` are wall-clock values and
the only fields that differ between two runs.
"""

from __future__ import annotations

import functools
import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from . import reference_v2 as V
from .bass import BASS_SCHEMA_FILE, resolve_bass_params
from .bass import render_resolved as _render_bass
from .bass_variants import make_variants as _bass_variants
from .kick import render_resolved as _render_kick
from .params import (
    KICK_SCHEMA_FILE,
    load_schema,
    max_settled_pitch_decay_ms,
    resolve_kick_params,
)
from .presets import load_preset, preset_names
from .variants import make_variants as _kick_variants

CATEGORIES = ("kick", "bass")
VARIANTS_PER_PRESET = 8

# --- profile (rule 2.6) -----------------------------------------------------------------------

PROFILE_BANDS = 12
PROFILE_BAND_HZ = (30.0, 16000.0)
PROFILE_ZONES_MS: dict[str, tuple[float, ...]] = {
    "kick": (0.0, 5.0, 15.0, 40.0, 100.0, 250.0, 450.0),
    "bass": (0.0, 10.0, 30.0, 60.0, 120.0, 250.0, 500.0),
}
PROFILE_FLOOR_DB = -60.0
PROFILE_SCALE_DB = 3.0
PROFILE_WEIGHT = 1.0  # the profile counts as one feature in the total (rule 2.4 (b))
PROFILE_LABEL = "Form (nur für die Suche)"
_PROFILE_MAX_DF_HZ = 3.0  # zero-padded bin width at most this

# --- search space -----------------------------------------------------------------------------

# Searched parameters in search order (the order of the note's tables 3.1 and 3.7) with the
# u-map: "log" for Hz, ms and ratio fields, "lin" otherwise.
SEARCH: dict[str, tuple[tuple[str, str], ...]] = {
    "kick": (
        ("pitch_end_hz", "log"),
        ("pitch_start_hz", "log"),
        ("pitch_decay_ms", "log"),
        ("amp_decay_ms", "log"),
        ("drive", "lin"),
        ("tone", "lin"),
        ("click_level", "lin"),
        ("click_tone_hz", "log"),
    ),
    "bass": (
        ("saw_level", "lin"),
        ("square_level", "lin"),
        ("sine_level", "lin"),
        ("sub_octave_level", "lin"),
        ("drive", "lin"),
        ("lp_hz", "log"),
        ("hp_hz", "log"),
        ("lp_q", "log"),
        ("lp_env_amount", "lin"),
        ("lp_env_decay_ms", "log"),
        ("amp_attack_ms", "log"),
        ("gate_ms", "log"),
        ("release_ms", "log"),
    ),
}
START_STEP = 0.25
MIN_STEP = 1.0 / 256.0
VALUE_DECIMALS = 4
DETERMINATION_STEP = 1.0 / 32.0
DETERMINATION_UNITS = 0.05
SUB_OCTAVE_TRIAL_LEVEL = 0.5

# Proposal of the note's section 4; the measured cost is in the PR of #564.
BUDGET: dict[str, tuple[int, float]] = {"kick": (300, 30.0), "bass": (300, 30.0)}

STOP_LABEL = {
    "step": "Schrittweite erreicht",
    "renders": "Render-Budget erreicht",
    "time": "Zeit-Budget erreicht",
    "cancelled": "abgebrochen",
}
TEXT_NOT_DETERMINED = "von den Messwerten nicht festgelegt"
TEXT_DETERMINED = "festgelegt"
TEXT_NOT_CHECKED = "nicht geprüft"
TEXT_ESTIMATE_KEPT = "übernommen"
TEXT_ESTIMATE_DROPPED = "Schätzung verworfen"
TEXT_ESTIMATE_SAME = "unverändert"
TEXT_ESTIMATE_NONE = "nicht messbar"
TEXT_NOT_MEASURABLE = "nicht messbar"

# Parameters that the recovery runs of #564 did not find again although the total fell
# (box (a), numbers in the PR): their fit values are start points even where the local check
# calls them determined. Shown in every report as ``weak_by_design``.
WEAK_BY_DESIGN: dict[str, tuple[str, ...]] = {
    "kick": ("click_tone_hz", "tone"),
    "bass": (),
}


def _resolver(category: str) -> tuple[Callable[[dict], dict], Callable[[dict], np.ndarray]]:
    if category == "kick":
        return resolve_kick_params, _render_kick
    if category == "bass":
        return resolve_bass_params, _render_bass
    raise ValueError(f"Unknown fit category {category!r}; possible: {', '.join(CATEGORIES)}.")


@functools.cache
def _ranges(category: str) -> dict[str, tuple[float, float]]:
    """Contract range of every numeric field of the category (from the schema file)."""
    _resolver(category)
    schema = load_schema(KICK_SCHEMA_FILE if category == "kick" else BASS_SCHEMA_FILE)
    return {name: (float(p["minimum"]), float(p["maximum"]))
            for name, p in schema["properties"].items()
            if "minimum" in p and "maximum" in p}


def to_u(kind: str, value: float, lo: float, hi: float) -> float:
    """Position of ``value`` in [lo, hi] as u in [0, 1] (log or linear map)."""
    if kind == "log":
        return math.log(value / lo) / math.log(hi / lo)
    return (value - lo) / (hi - lo)


def from_u(kind: str, u: float, lo: float, hi: float) -> float:
    """Inverse of :func:`to_u`; ``u`` is limited to [0, 1], the value rounded and kept inside
    the range (rounding must not carry it over an edge)."""
    u = min(1.0, max(0.0, u))
    value = lo * (hi / lo) ** u if kind == "log" else lo + (hi - lo) * u
    return min(hi, max(lo, round(value, VALUE_DECIMALS)))


# --- profile ----------------------------------------------------------------------------------

@functools.cache
def _band_overlap(sr: int, nfft: int) -> np.ndarray:
    """``(bands, bins)`` share of each rfft bin's width that lies inside each band."""
    df = sr / nfft
    centre = np.arange(nfft // 2 + 1) * df
    edges = np.geomspace(PROFILE_BAND_HZ[0], PROFILE_BAND_HZ[1], PROFILE_BANDS + 1)
    out = np.empty((PROFILE_BANDS, len(centre)))
    for b in range(PROFILE_BANDS):
        out[b] = np.clip(np.minimum(centre + df / 2, edges[b + 1])
                         - np.maximum(centre - df / 2, edges[b]), 0.0, None) / df
    return out


def profile(category: str, audio: np.ndarray, sr: int) -> np.ndarray:
    """``(zones, bands)`` profile in dB of a mono or stereo signal (module docstring)."""
    edges_ms = PROFILE_ZONES_MS[category]
    x = V.prepare_signal(audio)
    edges = [int(round(ms * sr / 1000.0)) for ms in edges_ms]
    need = max(max(b - a for a, b in zip(edges, edges[1:], strict=False)),
               int(math.ceil(sr / _PROFILE_MAX_DF_HZ)))
    nfft = 1 << int(math.ceil(math.log2(need)))
    overlap = _band_overlap(int(sr), nfft)
    energy = np.zeros((len(edges) - 1, PROFILE_BANDS))
    for z, (a, b) in enumerate(zip(edges, edges[1:], strict=False)):
        seg = x[a:b]
        if len(seg):
            energy[z] = overlap @ (np.abs(np.fft.rfft(seg, nfft)) ** 2)
    top = float(np.max(energy))
    if top <= 0.0:
        return np.full(energy.shape, PROFILE_FLOOR_DB)
    with np.errstate(divide="ignore"):
        db = 10.0 * np.log10(energy / top)
    return np.maximum(db, PROFILE_FLOOR_DB)


def profile_distance(a: np.ndarray, b: np.ndarray) -> float:
    """RMS cell difference of two profiles over :data:`PROFILE_SCALE_DB`."""
    return float(np.sqrt(np.mean((a - b) ** 2))) / PROFILE_SCALE_DB


def combined_total(per_feature: dict[str, float], profile_d: float,
                   table: dict[str, V.FeatureScale]) -> float:
    """Total distance: the weighted features plus the profile as one feature."""
    wsum = sum(fs.weight for fs in table.values())
    squares = sum(fs.weight * per_feature[n] ** 2 for n, fs in table.items())
    return math.sqrt((squares + PROFILE_WEIGHT * profile_d ** 2) / (wsum + PROFILE_WEIGHT)) \
        if wsum + PROFILE_WEIGHT > 0.0 else 0.0


# --- candidate sets (E4 for kick and bass) ----------------------------------------------------

@dataclass(frozen=True)
class Candidate:
    label: str  # "<preset> v<variant>"
    params: dict[str, Any]  # resolved, without "variants"
    features: dict[str, float | None]
    profile: np.ndarray


@functools.cache
def candidate_set(category: str) -> tuple[Candidate, ...]:
    """Every preset x variants 0 ... 7 of the category, rendered and measured once per
    process. Not cancellable; its cost is in ``candidate_seconds`` of the first report."""
    resolve, render = _resolver(category)
    make = _kick_variants if category == "kick" else _bass_variants
    out: list[Candidate] = []
    for name in preset_names(category):
        for i, variant in enumerate(make(load_preset(name, category), VARIANTS_PER_PRESET)):
            params = _without_variants(resolve(variant))
            audio = render(params)
            sr = int(params["sample_rate"])
            out.append(Candidate(f"{name} v{i}", params,
                                 V.features_from_audio(category, audio, sr),
                                 profile(category, audio, sr)))
    return tuple(out)


def _without_variants(params: dict[str, Any]) -> dict[str, Any]:
    out = dict(params)
    out.pop("variants", None)
    return out


# --- the run ----------------------------------------------------------------------------------

@dataclass(frozen=True)
class _Point:
    params: dict[str, Any]
    features: dict[str, float | None]
    distances: dict[str, float]
    profile_distance: float
    total: float


class _Stop(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _key(params: dict[str, Any]) -> tuple:
    return tuple(sorted(params.items()))


class _Run:
    """One fit: the reference's measures, the budget and the trial counter."""

    def __init__(self, category: str, audio: np.ndarray, sr: int, max_renders: int,
                 max_seconds: float, cancel: Callable[[], bool] | None,
                 clock: Callable[[], float]) -> None:
        self.category = category
        self.resolve, self.render = _resolver(category)
        self.table = V.feature_table(category)
        self.ref_features = V.features_from_audio(category, audio, sr)
        self.ref_profile = profile(category, audio, sr)
        self.max_renders = max_renders
        self.max_seconds = max_seconds
        self.cancel = cancel
        self.clock = clock
        self.t0 = clock()
        self.renders = 0
        self.rejected = 0
        self.memo: dict[tuple, _Point | None] = {}

    def point(self, params: dict[str, Any], features: dict[str, float | None],
              prof: np.ndarray) -> _Point:
        d = V.feature_distances(self.category, self.ref_features, features, self.table)
        pd = profile_distance(self.ref_profile, prof)
        return _Point(params, features, d, pd, combined_total(d, pd, self.table))

    def check(self) -> None:
        if self.cancel is not None and self.cancel():
            raise _Stop("cancelled")
        if self.clock() - self.t0 >= self.max_seconds:
            raise _Stop("time")

    def trial(self, params: dict[str, Any], limit: int) -> _Point | None:
        """The point of ``params``; ``None`` when the contract refuses them. Raises
        :class:`_Stop` before a render that the budget or the caller no longer allows."""
        key = _key(params)
        if key in self.memo:
            return self.memo[key]
        self.check()
        try:
            resolved = _without_variants(self.resolve(dict(params)))
        except ValueError:
            self.rejected += 1
            self.memo[key] = None
            return None
        if self.renders >= limit:
            raise _Stop("renders")
        audio = self.render(resolved)
        self.renders += 1
        sr = int(resolved["sample_rate"])
        p = self.point(resolved, V.features_from_audio(self.category, audio, sr),
                       profile(self.category, audio, sr))
        self.memo[key] = p
        return p


# --- stage 1 ----------------------------------------------------------------------------------

@dataclass(frozen=True)
class _Hypothesis:
    label: str
    changes: dict[str, Any]
    detail: str = ""


def _ratio_hypotheses(param: str, cur: _Point, ref: dict[str, float | None],
                      features: tuple[tuple[str, float], ...]) -> list[_Hypothesis]:
    """Relative and direct estimates of ``param`` from the first measured feature of
    ``features`` (name, factor): ``direct = factor x reference value``."""
    out: list[_Hypothesis] = []
    for name, factor in features:
        r = ref.get(name)
        if r is None or r <= 0.0:
            continue
        c = cur.features.get(name)
        if c is not None and c > 0.0:
            out.append(_Hypothesis("relativ", {param: round(cur.params[param] * r / c,
                                                            VALUE_DECIMALS)}, f"aus {name}"))
        out.append(_Hypothesis("direkt", {param: round(factor * r, VALUE_DECIMALS)},
                               f"aus {name}"))
        break
    return out


def _note_hypotheses(cur: _Point, ref: dict[str, float | None]) -> list[_Hypothesis]:
    f = ref.get("note_hz")
    if f is None or f <= 0.0:
        return []
    lo, hi = _ranges("bass")["note"]
    hp_min = _ranges("bass")["hp_hz"][0]
    sub = cur.params["sub_octave_level"]
    out: list[_Hypothesis] = []
    for label, hz, level in (("note", f, 0.0),
                             ("note + sub_octave_level", 2.0 * f,
                              sub if sub > 0 else SUB_OCTAVE_TRIAL_LEVEL)):
        midi = 69.0 + 12.0 * math.log2(hz / 440.0)
        note = int(math.floor(midi + 0.5))
        if not lo <= note <= hi:
            continue
        cents = round((midi - note) * 100.0, VALUE_DECIMALS)
        changes = {"note": note, "cents": cents, "sub_octave_level": level}
        out.append(_Hypothesis(label, changes))
        if cur.params["hp_hz"] > hp_min:
            out.append(_Hypothesis(label, dict(changes, hp_hz=hp_min),
                                   f"hp_hz auf {hp_min:g} Hz gesetzt (Vertragsregel hp_hz < "
                                   "0,8 f0)"))
    return out


def _estimators(category: str, length_ms: float) \
        -> tuple[tuple[str, Callable[[_Point, dict], list[_Hypothesis]]], ...]:
    if category == "kick":
        lo, hi = _ranges("kick")["length_ms"]
        length = round(min(hi, max(lo, length_ms)), 3)
        return (
            ("length_ms", lambda cur, ref: [_Hypothesis("direkt", {"length_ms": length},
                                                        "Länge der Referenz ab dem Einsatz")]),
            ("pitch_end_hz", lambda cur, ref: _ratio_hypotheses(
                "pitch_end_hz", cur, ref, (("fundamental_hz", 1.0),))),
            ("amp_decay_ms", lambda cur, ref: _ratio_hypotheses(
                "amp_decay_ms", cur, ref, (("decay_40db_ms", 1.5), ("decay_20db_ms", 3.0)))),
        )
    return (
        ("note", _note_hypotheses),
        ("gate_ms", lambda cur, ref: _ratio_hypotheses("gate_ms", cur, ref, (("gate_ms", 1.0),))),
        ("release_ms", lambda cur, ref: _ratio_hypotheses(
            "release_ms", cur, ref, (("release_ms", 1.0 / 0.99),))),
    )


def _stage1(run: _Run, best: _Point, length_ms: float, limit: int,
            entries: list[dict[str, Any]]) -> _Point:
    """Apply the estimates in order and append the report part to ``entries``. A
    :class:`_Stop` leaves through the caller: ``run.best`` holds the best point, and the
    entries not reached keep the status "nicht geprüft"."""
    estimators = _estimators(run.category, length_ms)
    for param, _ in estimators:
        entries.append({"parameter": param, "status": TEXT_NOT_CHECKED, "estimate": None,
                        "method": None, "detail": "", "total_with_estimate": None,
                        "rejected_by_contract": 0})
    for entry, (_, make) in zip(entries, estimators, strict=True):
        hyps = make(best, run.ref_features)
        if not hyps:
            entry["status"] = TEXT_ESTIMATE_NONE
            continue
        winner: tuple[float, _Hypothesis, _Point] | None = None
        same = False
        for h in hyps:
            if all(best.params.get(k) == v for k, v in h.changes.items()):
                same = True
                continue
            p = run.trial(dict(best.params, **h.changes), limit)
            if p is None:
                entry["rejected_by_contract"] += 1
                continue
            if winner is None or p.total < winner[0]:
                winner = (p.total, h, p)
        if winner is None:
            entry["status"] = TEXT_ESTIMATE_SAME if same else TEXT_ESTIMATE_DROPPED
            continue
        total, h, p = winner
        entry.update(estimate=dict(h.changes), method=h.label, detail=h.detail,
                     total_with_estimate=total)
        if total < best.total:
            entry["status"] = TEXT_ESTIMATE_KEPT
            best = p
            run.best = best
        else:
            entry["status"] = TEXT_ESTIMATE_DROPPED
    return best


# --- stage 2 ----------------------------------------------------------------------------------

def _stage2(run: _Run, best: _Point, limit: int) -> _Point:
    ranges = _ranges(run.category)
    search = SEARCH[run.category]
    u = {name: to_u(kind, best.params[name], *ranges[name]) for name, kind in search}
    step = START_STEP
    while step >= MIN_STEP:
        improved = False
        for name, kind in search:
            for sign in (1.0, -1.0):
                nu = min(1.0, max(0.0, u[name] + sign * step))
                value = from_u(kind, nu, *ranges[name])
                if value == best.params[name]:
                    continue
                p = run.trial(dict(best.params, **{name: value}), limit)
                if p is not None and p.total < best.total:
                    best = p
                    run.best = best
                    u[name] = nu
                    improved = True
                    break
        if not improved:
            step /= 2.0
    return best


def _determination(run: _Run, best: _Point, start: _Point) -> list[dict[str, Any]]:
    ranges = _ranges(run.category)
    rows: list[dict[str, Any]] = []
    stopped = False
    for name, kind in SEARCH[run.category]:
        row: dict[str, Any] = {
            "name": name, "map": kind, "start": start.params[name], "fit": best.params[name],
            "cost_change_minus": None, "cost_change_plus": None,
            "side_minus": TEXT_NOT_CHECKED, "side_plus": TEXT_NOT_CHECKED,
            "determined": None, "flag": TEXT_NOT_CHECKED,
            "weak_by_design": name in WEAK_BY_DESIGN[run.category],
        }
        rows.append(row)
        if stopped:
            continue
        u = to_u(kind, best.params[name], *ranges[name])
        try:
            for side, sign in (("minus", -1.0), ("plus", 1.0)):
                value = from_u(kind, u + sign * DETERMINATION_STEP, *ranges[name])
                if value == best.params[name]:
                    row[f"side_{side}"] = "Rand des Wertebereichs"
                    continue
                p = run.trial(dict(best.params, **{name: value}), run.max_renders)
                if p is None:
                    row[f"side_{side}"] = "vom Vertrag abgelehnt"
                    continue
                row[f"side_{side}"] = "gemessen"
                row[f"cost_change_{side}"] = p.total - best.total
        except _Stop:
            stopped = True
            continue
        changes = [abs(row[k]) for k in ("cost_change_minus", "cost_change_plus")
                   if row[k] is not None]
        row["determined"] = any(c >= DETERMINATION_UNITS for c in changes)
        row["flag"] = TEXT_DETERMINED if row["determined"] else TEXT_NOT_DETERMINED
    return rows


# --- result -----------------------------------------------------------------------------------

@dataclass(frozen=True)
class FitResult:
    """``params``: resolved engine parameters of the fit (they re-render it); ``report``:
    plain data, see the module docstring."""

    category: str
    params: dict[str, Any]
    start_params: dict[str, Any]
    report: dict[str, Any]

    def to_json(self) -> str:
        return json.dumps({"category": self.category, "params": self.params,
                           "start_params": self.start_params, "report": self.report},
                          ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)


def _settles(category: str, params: dict[str, Any]) -> bool | None:
    if category != "kick":
        return None
    return bool(params["pitch_decay_ms"] <= max_settled_pitch_decay_ms(params))


def fit_reference(category: str, audio: np.ndarray, sample_rate: int, *,
                  max_renders: int | None = None, max_seconds: float | None = None,
                  cancel: Callable[[], bool] | None = None,
                  clock: Callable[[], float] = time.perf_counter) -> FitResult:
    """Fit the category's engine parameters to one sound (mono ``(n,)`` or stereo ``(n, 2)``
    samples of one hit). See the module docstring for stages, budget and report."""
    _resolver(category)
    audio = np.asarray(audio, dtype=np.float64)
    if audio.ndim not in (1, 2) or len(audio) < 16 or not np.all(np.isfinite(audio)):
        raise ValueError("fit_reference needs finite mono (n,) or stereo (n, 2) samples, "
                         "at least 16.")
    if max_renders is None:
        max_renders = BUDGET[category][0]
    if max_seconds is None:
        max_seconds = BUDGET[category][1]
    if max_renders < 0 or max_seconds < 0:
        raise ValueError("max_renders and max_seconds must not be negative.")

    t_cand = clock()
    cands = candidate_set(category)
    candidate_seconds = clock() - t_cand

    run = _Run(category, audio, int(sample_rate), int(max_renders), float(max_seconds),
               cancel, clock)
    points = [run.point(c.params, c.features, c.profile) for c in cands]
    index = min(range(len(points)), key=lambda i: (points[i].total, i))  # ties: grid order
    start = points[index]
    run.memo[_key(start.params)] = start
    run.best = start

    length_ms = len(V.prepare_signal(audio)) / sample_rate * 1000.0
    search_limit = max(0, run.max_renders - 2 * len(SEARCH[category]))
    stage1: list[dict[str, Any]] = []
    try:
        best = _stage1(run, start, length_ms, search_limit, stage1)
        best = _stage2(run, best, search_limit)
        stop = "step"
    except _Stop as exc:
        stop = exc.reason
    best = run.best
    parameters = _determination(run, best, start)
    if cancel is not None and stop != "cancelled" and cancel():
        stop = "cancelled"

    table = run.table
    provisional = [n for n, fs in table.items() if fs.provisional]
    features = []
    for name, fs in table.items():
        ref_value = run.ref_features.get(name)
        features.append({
            "name": name, "weight": fs.weight, "scale": fs.scale, "transform": fs.transform,
            "reference": ref_value, "start": start.features.get(name),
            "fit": best.features.get(name),
            "distance_before": start.distances[name], "distance_after": best.distances[name],
            "note": TEXT_NOT_MEASURABLE if ref_value is None else "",
        })
    report: dict[str, Any] = {
        "category": category,
        "fit_seed": best.params["seed"],
        "start_candidate": cands[index].label,
        "scales": {
            "source": "provisional" if len(provisional) == len(table)
            else ("mixed" if provisional else "table"),
            "provisional_features": provisional,
        },
        "features": features,
        "profile": {
            "label": PROFILE_LABEL,
            "distance_before": start.profile_distance,
            "distance_after": best.profile_distance,
            "weight": PROFILE_WEIGHT,
            "zones_ms": list(PROFILE_ZONES_MS[category]),
            "band_edges_hz": [PROFILE_BAND_HZ[0], PROFILE_BAND_HZ[1], PROFILE_BANDS],
        },
        "total_before": start.total,
        "total_after": best.total,
        "stage1": stage1,
        "parameters": parameters,
        "weak_by_design": list(WEAK_BY_DESIGN[category]),
        "pitch_settles": {"start": _settles(category, start.params),
                          "fit": _settles(category, best.params)},
        "renders": run.renders,
        "max_renders": run.max_renders,
        "max_seconds": run.max_seconds,
        "rejected_trials": run.rejected,
        "stop_reason": stop,
        "stop_label": STOP_LABEL[stop],
        "seconds": clock() - run.t0,
        "candidate_seconds": candidate_seconds,
    }
    return FitResult(category, dict(best.params), dict(start.params), report)


def fit_reference_audio(ref: V.ReferenceAudioV2, category: str, **kwargs: Any) -> FitResult:
    """Fit the first hit of a reference read by :func:`reference_v2.read_reference_v2`. The
    report also carries the reader's flags (``multi_hit``, ``censored_tail``)."""
    result = fit_reference(category, ref.first_hit, ref.sample_rate, **kwargs)
    result.report["reference"] = {
        "sample_rate": ref.sample_rate, "channels": ref.channels,
        "hit_count": ref.hit_count, "multi_hit": ref.multi_hit,
        "censored_tail": ref.censored_tail,
    }
    return result
