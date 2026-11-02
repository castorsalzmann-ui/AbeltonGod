"""Arrangement plan generator, step G2: energy nodes, settings effects, drawn-node overlay (#218).

Design: docs/research/2026-11-02_arrangement-plan-generator-design.md, sections 2, 4 and 7 (G2).
``generate_plan`` turns a request (G1 layout, or explicit sections) plus optional drawn nodes into
an arrangement plan v0.1 that passes ``plan_problems``, or into errors. Pure Python, no Live, no
randomness: the same request gives the same JSON.

Default nodes (planner note section 4 as amended by INTERFACES):
- intro: one step per 8-bar phrase, evenly spaced from 0.30 to 0.45.
- groove 0.60 -> 0.70, break 0.45 flat, breakdown 0.30 / 0.20 (middle) / 0.35, drop 0.90 -> 0.95.
- later drops with ``second_drop = stronger``: 0.95 -> 1.00 (every drop after the first;
  ``equal`` and ``ask`` keep the first drop's values, ``ask`` adds a warning).
- build: continues from the previous end and ends at max(start, next start - 0.05) (B3); before
  a section that continues (build, outro) it stays flat.
- outro: ``default_outro`` walk from the value flowing in (one element per 8-bar boundary).
Values are rounded to 4 decimals (0.9 + 0.05 is 0.9500000000000001 in floating point).

Drawn nodes: kept with identical ``pos``, ``value`` and order, ``drawn: true``. Every undrawn node
at a ``pos`` that holds a drawn node is dropped (the format allows two nodes at most there); the
builds and the outro take their anchors from the drawn values (B2, B3). Sections never move.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from orchestrator.arrangement_layout import (
    GENRES,
    PlanRequest,
    _check_settings,
    _err,
    _is_int,
    _is_real,
    duration_warning,
    plan_layout,
)
from orchestrator.arrangement_plan import PHRASE_BARS, default_outro, plan_problems

DECIMALS = 4
INTRO_RANGE = (0.30, 0.45)
STEP_START = {"groove": 0.60, "break": 0.45, "breakdown": 0.30, "drop": 0.90}
STEP_END = {"groove": 0.70, "break": 0.45, "breakdown": 0.35}  # a drop ends DROP_RISE higher
BREAKDOWN_MIDDLE = 0.20
DROP_RISE = 0.05  # a drop ends this far above where it starts, and "stronger" lifts by it
SECOND_DROP_STEP = DROP_RISE
BUILD_MARGIN = 0.05


@dataclass
class PlanResult:
    plan: dict | None = None
    adjustments: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)  # {"code", "detail"}

    @property
    def ok(self) -> bool:
        return not self.errors


def _r(v: float) -> float:
    return round(v, DECIMALS)


def _check_drawn(raw: Any, total: int) -> tuple[list[dict], list[dict]]:
    """Validate the caller's drawn nodes; return them as plan nodes (``drawn: true``)."""
    if raw is None:
        return [], []
    if not isinstance(raw, (list, tuple)):
        return [], [_err("drawn_node_invalid", index=None, reason="not a list")]
    nodes: list[dict] = []
    for i, n in enumerate(raw):
        if not isinstance(n, dict) or not _is_int(n.get("pos")) or not _is_real(n.get("value")):
            return [], [_err("drawn_node_invalid", index=i, reason="needs integer pos and value")]
        if not 0 <= n["pos"] <= total:
            return [], [_err("drawn_node_invalid", index=i, reason=f"pos outside 0..{total}")]
        if not 0 <= n["value"] <= 1:
            return [], [_err("drawn_node_invalid", index=i, reason="value outside 0..1")]
        if nodes and n["pos"] < nodes[-1]["pos"]:
            return [], [_err("drawn_node_invalid", index=i, reason="pos decreases")]
        same = sum(1 for m in nodes if m["pos"] == n["pos"])
        if same >= 2:
            return [], [_err("drawn_node_invalid", index=i, reason="third node at one pos")]
        if same == 1 and n["pos"] in (0, total):
            return [], [_err("drawn_node_invalid", index=i, reason="pair at the track edge")]
        nodes.append({"pos": n["pos"], "value": n["value"], "drawn": True})
    return nodes, []


def build_nodes(sections: list[dict], settings: dict,
                drawn: list[dict]) -> tuple[list[dict], list[dict]]:
    """Energy nodes for valid ``sections``; returns (nodes, errors).

    Defaults first, with the anchors of builds and outro read from the drawn values; then the
    drawn nodes replace every undrawn node at their ``pos``.
    """
    drawn_at: dict[int, list[float]] = {}
    for n in drawn:
        drawn_at.setdefault(n["pos"], []).append(n["value"])

    # entry value of every step section (a build looks one section ahead)
    drops = 0
    entry: list[float | None] = []
    for s in sections:
        v0 = STEP_START.get(s["type"])
        if s["type"] == "drop":
            drops += 1
            if drops > 1 and settings["second_drop"] == "stronger":
                v0 = _r(v0 + SECOND_DROP_STEP)
        entry.append(v0)

    nodes: list[dict] = []

    def add(pos: int, value: float) -> None:
        nodes.append({"pos": pos, "value": value, "drawn": False})

    def leaving(pos: int) -> float:
        return drawn_at[pos][-1] if pos in drawn_at else nodes[-1]["value"]

    for i, s in enumerate(sections):
        kind, start, length = s["type"], s["start_bar"] - 1, s["length_bars"]
        end = start + length
        if kind == "intro":
            phrases = length // PHRASE_BARS
            lo, hi = INTRO_RANGE
            values = [_r(lo + (hi - lo) * k / (phrases - 1)) for k in range(phrases)]
            add(start, values[0])
            for k in range(1, phrases):
                add(start + PHRASE_BARS * k, values[k - 1])
                add(start + PHRASE_BARS * k, values[k])
            add(end, values[-1])
        elif kind == "build":
            begin = leaving(start)
            nxt = entry[i + 1] if i + 1 < len(sections) else None
            add(end, begin if nxt is None else max(begin, _r(nxt - BUILD_MARGIN)))
        elif kind == "outro":
            out_len, walk = default_outro(leaving(start), min_length=length)
            if out_len != length:
                return [], [_err("outro_slot_too_short", required=out_len, slot=length)]
            for pos, value in walk[1:]:  # walk[0] is the previous section's end node
                add(start + pos, value)
        else:  # step sections
            add(start, entry[i])
            if kind == "breakdown":
                add(start + length // 2, BREAKDOWN_MIDDLE)
            add(end, _r(entry[i] + DROP_RISE) if kind == "drop" else STEP_END[kind])

    merged = [n for n in nodes if n["pos"] not in drawn_at] + drawn
    merged.sort(key=lambda n: n["pos"])  # stable: pairs and drawn order keep their sequence
    return merged, []


def generate_plan(req: PlanRequest, *, sections: list[dict] | None = None,
                  drawn_nodes: list[dict] | None = None) -> PlanResult:
    """Build a plan for ``req``; ``sections`` replaces the G1 layout (the track length is then
    the sum of the sections and ``req`` carries no target). Never returns an invalid plan."""
    if sections is None:
        layout = plan_layout(req)
        result = PlanResult(adjustments=list(layout.adjustments), warnings=list(layout.warnings),
                            errors=list(layout.errors))
        if result.errors:
            return result
        sections, total, settings = layout.sections, layout.total_bars, layout.settings
    else:
        result = PlanResult()
        settings, errors = _check_settings(req.settings)
        result.errors += errors
        if req.genre not in GENRES or not isinstance(req.genre, str):
            result.errors.append(_err("bad_genre", field="genre", allowed=list(GENRES)))
        if not _is_real(req.bpm) or not 20 <= req.bpm <= 999:
            result.errors.append(_err("bad_bpm", field="bpm", allowed=[20, 999]))
        if req.target_bars is not None or req.target_minutes is not None:
            result.errors.append(_err("length_with_sections"))
        if result.errors:
            return result
        try:
            total = sum(s["length_bars"] for s in sections)
        except (TypeError, KeyError):
            total = 0
        stub = _plan(req.bpm, total, sections, [], settings)
        stub["energy_nodes"] = [{"pos": 0, "value": 0.5, "drawn": False},
                                {"pos": total, "value": 0.5, "drawn": False}]
        problems = plan_problems(stub)
        if problems:
            result.errors.append(_err("sections_invalid", problems=problems))
            return result
        warning = duration_warning(total, req.bpm)
        if warning:
            result.warnings.append(warning)

    drawn, errors = _check_drawn(drawn_nodes, total)
    result.errors += errors
    if result.errors:
        return result
    nodes, errors = build_nodes(sections, settings, drawn)
    result.errors += errors
    if result.errors:
        return result
    if settings["second_drop"] == "ask" and sum(s["type"] == "drop" for s in sections) > 1:
        result.warnings.append({
            "code": "second_drop_ask",
            "detail": "second_drop is 'ask': the later drops got the values of the first"})
    plan = _plan(req.bpm, total, sections, nodes, settings)
    problems = plan_problems(plan)
    if problems:  # an internal bug, never a user error
        raise RuntimeError(f"generated plan breaks the format: {problems}")
    result.plan = plan
    return result


def _plan(bpm: Any, total: int, sections: list[dict], nodes: list[dict], settings: dict) -> dict:
    return {"schema_version": "0.1", "bpm": bpm, "time_signature": "4/4", "phrase_bars": 8,
            "total_bars": total, "sections": sections, "energy_nodes": nodes,
            "settings": dict(settings)}
