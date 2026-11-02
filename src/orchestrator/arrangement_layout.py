"""Arrangement plan generator, step G1: section layout and length fit (#212).

Design: docs/research/2026-11-02_arrangement-plan-generator-design.md, sections 2 and 7 (G1).
Input is a ``PlanRequest`` (genre, bpm, one length, optional settings); output is the section
list of a plan (type, start_bar, length_bars) or a list of errors. No energy nodes yet (G2).

How the length is fitted:
- Fixed sections: intro (``intro_length``), breakdown(s) (``breakdown_length``) and the outro. The
  outro comes from ``default_outro`` for the end value of a drop (0.90 or more), which is 64 bars
  (the walk needs more phrases than 64 bars have); ``outro_length`` is its minimum.
- Elastic sections: groove, break, builds and drops. Each takes one of its allowed lengths.
- The combination that adds up to ``target_bars`` and is closest to the default lengths (sum of
  absolute differences) wins; ties go to the lexicographically smallest tuple of lengths.
- If no combination adds up, the request fails with ``length_infeasible`` and the nearest feasible
  totals below and above (a request with one of them succeeds).

User decisions of 2026-11-02: the outro rule stays (a track over 7 minutes only gets a warning);
a second breakdown is a third build and drop appended after drop 2.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from fractions import Fraction
from functools import cache
from typing import Any

from orchestrator.arrangement_plan import PHRASE_BARS, default_outro

GENRES = ("techno", "trance")
BPM_RANGE = (20, 999)
BARS_RANGE = (32, 1024)
WINDOW_MINUTES = (4.0, 7.0)  # S2: an editor warning, not a format rule
DROP_END_VALUE = 0.90  # lowest value a default drop ends at (G2 writes 0.90 / 0.95)

SETTING_DEFAULTS: dict[str, Any] = {
    "build_kick": "filtered_in_build", "intro_length": 32, "outro_length": 32,
    "intro_outro_bass": "on", "breakdown_count": 1, "breakdown_length": 32,
    "breakdown_rumble": "off", "second_drop": "stronger", "change_grid": 8,
    "pre_drop_gap": 4, "fills": "off",
}
SETTING_ALLOWED: dict[str, tuple] = {
    "build_kick": ("filtered_in_build", "at_drop"), "intro_length": (16, 32, 64),
    "outro_length": (16, 32, 64), "intro_outro_bass": ("on", "outside_mix_zone", "off"),
    "breakdown_count": (1, 2), "breakdown_length": (16, 32, 64),
    "breakdown_rumble": ("off", "on"), "second_drop": ("stronger", "equal", "ask"),
    "change_grid": tuple(range(1, 65)), "pre_drop_gap": (0, 1, 2, 4),
    "fills": ("off", "section_change", "every_8"),
}

# Allowed lengths of the elastic section types (docs/INTERFACES.md, `sections[]`).
ELASTIC_LENGTHS = {
    "groove": (16, 32, 48, 64), "break": (8, 16), "build": (8, 16, 32), "drop": (16, 32, 64),
}
# Default lengths (templates T2 / T3 of the planner note); the fit stays as close as it can.
ELASTIC_DEFAULT = {"groove": 32, "break": 8, "build": 16, "drop": 32}

# Skeleton per genre: "I" intro, "B" breakdown, "O" outro are fixed; the rest is elastic.
# (type, default length for an elastic section; None for fixed ones)
_SECTIONS_BEFORE_BREAKDOWN = {
    "techno": [("intro", None), ("groove", 32), ("break", 8), ("build", 8), ("drop", 32)],
    "trance": [("intro", None), ("groove", 32), ("build", 16), ("drop", 32)],
}
_AFTER_BREAKDOWN = [("breakdown", None), ("build", 16), ("drop", 32)]


@dataclass(frozen=True)
class PlanRequest:
    genre: Any
    bpm: Any
    target_bars: Any = None
    target_minutes: Any = None
    settings: dict | None = None


@dataclass
class LayoutResult:
    sections: list[dict] = field(default_factory=list)
    total_bars: int = 0
    settings: dict = field(default_factory=dict)
    adjustments: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)  # {"code", "detail"}

    @property
    def ok(self) -> bool:
        return not self.errors


def _err(code: str, **detail: Any) -> dict:
    return {"code": code, "detail": detail}


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_real(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def minutes_to_bars(minutes: float, bpm: float) -> int:
    """bars = minutes * 60 * bpm / 240, rounded to the nearest multiple of 8; an exact tie goes
    to the longer length. Exact arithmetic, so the tie is decided on the numbers given."""
    phrases = Fraction(minutes) * Fraction(bpm) / (4 * PHRASE_BARS)
    return math.floor(phrases + Fraction(1, 2)) * PHRASE_BARS


def _nearest_valid_bars(value: float) -> list[int]:
    lo, hi = BARS_RANGE
    below = max(lo, min(hi, math.floor(value / PHRASE_BARS) * PHRASE_BARS))
    above = max(lo, min(hi, math.ceil(value / PHRASE_BARS) * PHRASE_BARS))
    return sorted({below, above})


def _check_settings(raw: Any) -> tuple[dict, list[dict]]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        return dict(SETTING_DEFAULTS), [_err("bad_setting", field="settings", allowed="a map")]
    merged, errors = dict(SETTING_DEFAULTS), []
    for key, value in raw.items():
        allowed = SETTING_ALLOWED.get(key)
        if allowed is None:
            errors.append(_err("bad_setting", field=key, allowed=sorted(SETTING_ALLOWED)))
        elif isinstance(value, bool) or value not in allowed:
            errors.append(_err("bad_setting", field=key, allowed=list(allowed)))
        else:
            merged[key] = value
    return merged, errors


def _check_length(req: PlanRequest) -> tuple[int | None, list[dict]]:
    """Resolve target_bars / target_minutes to a bar count; errors if neither fits."""
    has_bars, has_min = req.target_bars is not None, req.target_minutes is not None
    if has_bars == has_min:
        return None, [_err("length_both_or_none")]
    if has_bars:
        bars = req.target_bars
        if not _is_real(bars):
            return None, [_err("length_out_of_range", nearest=list(BARS_RANGE))]
    else:
        minutes = req.target_minutes
        if not _is_real(minutes) or minutes <= 0:
            return None, [_err("length_out_of_range", nearest=[BARS_RANGE[0]])]
        bars = minutes_to_bars(minutes, req.bpm)
    lo, hi = BARS_RANGE
    if bars < lo or bars > hi:
        return None, [_err("length_out_of_range", nearest=_nearest_valid_bars(bars))]
    if not _is_int(bars) or bars % PHRASE_BARS:
        return None, [_err("length_not_multiple_of_8", nearest=_nearest_valid_bars(bars))]
    return int(bars), []


def _outro_bars(outro_length: int) -> int:
    length, _ = default_outro(DROP_END_VALUE, min_length=outro_length)
    return length


def _skeleton(genre: str, breakdown_count: int) -> list[tuple[str, int | None]]:
    """(type, default length) per section; fixed sections have default None."""
    seq = list(_SECTIONS_BEFORE_BREAKDOWN[genre])
    for _ in range(breakdown_count):
        seq += _AFTER_BREAKDOWN
    return [*seq, ("outro", None)]


@cache
def _fit_table(genre: str, breakdown_count: int, intro: int, breakdown: int,
               outro: int) -> dict[int, tuple[int, ...]]:
    """Total bars -> chosen lengths of all sections, for every total that can be reached."""
    skeleton = _skeleton(genre, breakdown_count)
    fixed_len = {"intro": intro, "breakdown": breakdown, "outro": outro}
    elastic = [i for i, (t, _) in enumerate(skeleton) if t in ELASTIC_LENGTHS]
    best: dict[int, tuple[tuple[int, tuple[int, ...]], tuple[int, ...]]] = {}
    for combo in itertools.product(*(ELASTIC_LENGTHS[skeleton[i][0]] for i in elastic)):
        lengths = [fixed_len.get(t, 0) for t, _ in skeleton]
        for i, n in zip(elastic, combo, strict=True):
            lengths[i] = n
        deviation = sum(abs(n - skeleton[i][1]) for i, n in zip(elastic, combo, strict=True))
        key = (deviation, combo)
        total = sum(lengths)
        if total not in best or key < best[total][0]:
            best[total] = (key, tuple(lengths))
    return {total: lengths for total, (_, lengths) in best.items()}


def plan_layout(req: PlanRequest) -> LayoutResult:
    """Validate ``req`` and return the section list that fits its length, or the errors."""
    result = LayoutResult()
    errors = result.errors
    if req.genre not in GENRES or not isinstance(req.genre, str):
        errors.append(_err("bad_genre", field="genre", allowed=list(GENRES)))
    bpm = req.bpm
    if not _is_real(bpm) or not BPM_RANGE[0] <= bpm <= BPM_RANGE[1]:
        errors.append(_err("bad_bpm", field="bpm", allowed=list(BPM_RANGE)))
    settings, setting_errors = _check_settings(req.settings)
    errors += setting_errors
    bpm_bad = any(e["code"] == "bad_bpm" for e in errors)
    if bpm_bad and req.target_minutes is not None:
        bars = None  # minutes cannot be converted without a valid bpm
    else:
        bars, length_errors = _check_length(req)
        errors += length_errors
    if errors:
        return result

    table = _fit_table(req.genre, settings["breakdown_count"], settings["intro_length"],
                       settings["breakdown_length"], _outro_bars(settings["outro_length"]))
    if bars not in table:
        feasible = sorted(table)
        below = [t for t in feasible if t < bars]
        above = [t for t in feasible if t > bars]
        errors.append(_err("length_infeasible", target_bars=bars,
                           nearest={"below": below[-1] if below else None,
                                    "above": above[0] if above else None}))
        return result

    skeleton = _skeleton(req.genre, settings["breakdown_count"])
    start = 1
    for (kind, _), length in zip(skeleton, table[bars], strict=True):
        result.sections.append({"type": kind, "start_bar": start, "length_bars": length})
        start += length
    result.total_bars = bars
    result.settings = settings
    if result.sections[-1]["length_bars"] > settings["outro_length"]:
        result.adjustments.append({
            "code": "outro_lengthened",
            "detail": f"outro is {result.sections[-1]['length_bars']} bars, not "
                      f"{settings['outro_length']}: the energy walk after a full drop needs it"})
    minutes = bars * 240 / bpm / 60
    if not WINDOW_MINUTES[0] <= minutes <= WINDOW_MINUTES[1]:
        result.warnings.append({
            "code": "duration_window",
            "detail": f"{minutes:.2f} min at {bpm} BPM is outside "
                      f"{WINDOW_MINUTES[0]:.0f}-{WINDOW_MINUTES[1]:.0f} min"})
    return result
