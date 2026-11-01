"""Arrangement plan format v0.1: the one rule checker (#146, D-024).

Schema: ``contracts/arrangement-plan.schema.json``. JSON Schema cannot say that sections tile the
track, how step pairs are ordered or what the boundary rules B2/B3 demand; ``plan_problems`` says
it. Planner window, plan generator and Live builder use this module; nobody writes a second
checker (docs/INTERFACES.md, "Arrangement plan"). The positive and negative instances are JSON
files in ``tests/fixtures/arrangement_plan/`` so that a reader in another language can run them.

Also here: the template helpers that follow from user decisions, not from the schema
(``change_points``, ``default_outro``, ``boundary_changes``). They are not validity rules.
"""

from __future__ import annotations

import itertools
import json
import math
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "contracts"
SCHEMA_FILE = CONTRACTS_DIR / "arrangement-plan.schema.json"

# Entry mode per section type (B1 step / B2 continue). User decision 2026-10-30 ("Fliessend
# weiter"): the outro continues from the previous section's end value, with no step down at its
# start; it decays inside the section. The intro is first and has no entry.
ENTRY_MODE = {
    "groove": "step",
    "break": "step",
    "breakdown": "step",
    "build": "continue",
    "drop": "step",
    "outro": "continue",
}
B3_MARGIN = 0.05  # B3: a build ends at max(its start value, next section's start - 0.05)
TOL = 1e-9
PHRASE_BARS = 8


@cache
def _validator() -> Draft202012Validator:
    if not SCHEMA_FILE.exists():
        raise FileNotFoundError(
            f"Contract not found: {SCHEMA_FILE}. Plans are checked against the repo's "
            "contracts/ folder; install the project in editable mode (pip install -e .).")
    return Draft202012Validator(json.loads(SCHEMA_FILE.read_text(encoding="utf-8")))


def schema() -> dict[str, Any]:
    """The plan schema as loaded (read only)."""
    return _validator().schema


# --- the rules ---------------------------------------------------------------------------------

def nodes_at(nodes: list[dict], pos: int) -> list[dict]:
    """The nodes at ``pos`` in array order (0, 1 or 2 in a valid plan)."""
    return [n for n in nodes if n["pos"] == pos]


def energy_at(nodes: list[dict], x: float) -> tuple[float, float]:
    """(value arriving from the left, value leaving to the right) at ``x``; linear in between.
    Needs nodes that already pass the order rules and cover ``x``."""
    here = [n for n in nodes if n["pos"] == x]
    if here:
        return here[0]["value"], here[-1]["value"]
    left = [n for n in nodes if n["pos"] < x][-1]
    right = next(n for n in nodes if n["pos"] > x)
    frac = (x - left["pos"]) / (right["pos"] - left["pos"])
    v = left["value"] + frac * (right["value"] - left["value"])
    return v, v


def plan_problems(plan: Any, entry_mode: dict | None = None) -> list[str]:
    """Every contract rule ``plan`` breaks, as "code: detail" (empty = valid plan).

    ``entry_mode`` exists so a test can show that the table matters; callers leave it out.
    ``settings`` are checked by the schema only: no setting changes what makes a plan valid.
    """
    modes = ENTRY_MODE if entry_mode is None else entry_mode
    errors = sorted(_validator().iter_errors(plan), key=lambda e: list(e.absolute_path))
    if errors:  # the cross-field rules below assume the shape
        return [f"schema: {list(e.absolute_path)} {e.message}" for e in errors]
    problems: list[str] = []
    numbers = [plan["bpm"], *(n["value"] for n in plan["energy_nodes"])]
    if not all(math.isfinite(v) for v in numbers):
        problems.append("nonfinite: bpm and node values must be finite")
        return problems

    # S1 (starts at bar 8k + 1) follows from tiling: the first section starts at bar 1 and the
    # schema makes every length a multiple of phrase_bars (const 8).
    total, sections = plan["total_bars"], plan["sections"]
    expected = 1
    for i, s in enumerate(sections):
        if s["start_bar"] != expected:
            problems.append(
                f"tiling: section {i} starts at bar {s['start_bar']}, expected {expected}")
        expected = s["start_bar"] + s["length_bars"]
    if expected - 1 != total:
        problems.append(f"total_bars: sections end at bar {expected - 1}, total_bars is {total}")
    types = [s["type"] for s in sections]
    if types[0] != "intro":
        problems.append("first_not_intro: the first section must be the intro")
    if types[-1] != "outro":
        problems.append("last_not_outro: the last section must be the outro")
    if "intro" in types[1:] or "outro" in types[:-1]:
        problems.append("intro_outro_inside: intro and outro appear only first and last")

    nodes = plan["energy_nodes"]
    order_ok = all(a["pos"] <= b["pos"] for a, b in itertools.pairwise(nodes))
    if not order_ok:
        problems.append("node_order: pos must never decrease in array order")
    counts: dict[int, int] = {}
    for n in nodes:
        counts[n["pos"]] = counts.get(n["pos"], 0) + 1
    problems += [f"three_at_pos: {c} nodes at pos {p}" for p, c in sorted(counts.items()) if c > 2]
    if nodes[0]["pos"] != 0:
        problems.append(f"first_node_pos: first node at {nodes[0]['pos']}, must be 0")
    if nodes[-1]["pos"] != total:
        problems.append(f"last_node_pos: last node at {nodes[-1]['pos']}, must be {total}")
    for edge in (0, total):
        if counts.get(edge, 0) > 1:
            problems.append(f"pair_at_edge: a step pair at pos {edge}")
    if problems:  # boundary rules need a well-formed curve
        return problems

    for i, s in enumerate(sections[1:], start=1):
        start = s["start_bar"] - 1
        here = nodes_at(nodes, start)
        if (modes[s["type"]] == "continue" and len(here) == 2
                and not (here[0]["drawn"] or here[1]["drawn"])
                and abs(here[0]["value"] - here[1]["value"]) > TOL):
            problems.append(f"b2_jump: undrawn jump into continue section {i} at pos {start}")
        if s["type"] == "build":
            end = start + s["length_bars"]
            at_end = nodes_at(nodes, end)
            if at_end and not at_end[0]["drawn"]:
                begin = energy_at(nodes, start)[1]
                # With a single node at the end, arriving and leaving node are the same node:
                # v = max(begin, v - 0.05) holds only for v = begin, so that build is flat.
                want = max(begin, at_end[-1]["value"] - B3_MARGIN)
                if abs(at_end[0]["value"] - want) > TOL:
                    problems.append(
                        f"b3_build_end: build {i} ends at {at_end[0]['value']} at pos {end}, "
                        f"expected {want}")
    return problems


def problem_codes(plan: Any, **kw: Any) -> set[str]:
    return {p.split(":", 1)[0] for p in plan_problems(plan, **kw)}


# --- change points (user decision 2026-11-01: grid counts from each section's start) ----------

def change_points(plan: dict) -> list[int]:
    """Positions (``pos``, whole bars) where elements may switch on or off (T1).

    Counted from each section's start: ``start_pos, start_pos + g, start_pos + 2g, ...`` inside
    the section, with ``g`` = ``settings.change_grid``. Every section start is a change point.
    The end of the track is not (nothing follows). A grid of 12 in a 16-bar section at bar 33
    gives pos 32 and 44. A grid at least as long as the section leaves only its start. The
    setting reads nothing else: sections and nodes never move.
    """
    grid = plan["settings"]["change_grid"]
    points = []
    for s in plan["sections"]:
        start = s["start_bar"] - 1
        points += range(start, start + s["length_bars"], grid)
    return points


# --- element rule of the note (section 5.1): at most one element change per 8-bar boundary ----

# Energy thresholds of the drum-led elements, ascending (research note 2026-10-29, section 5.1,
# a proposal): atmos .20, closed hats .30, percussion 1 .40, clap .55, synth .65, pad .70, open
# hat .75, percussion 2 .80, second synth .90. Kick (always on) and bass (set by
# `intro_outro_bass` in intro and outro, not by energy) are left out.
ELEMENT_THRESHOLDS = (0.20, 0.30, 0.40, 0.55, 0.65, 0.70, 0.75, 0.80, 0.90)
OUTRO_LENGTHS = (16, 32, 64)
MIX_ZONE_CAP = 0.50  # energy cap in the last 16 bars of an outro (note section 5.1)
OUTRO_END_VALUE = 0.25  # the note's end of the outro decay


def elements_crossed(a: float, b: float) -> int:
    """How many element thresholds lie between the energies ``a`` and ``b`` (an element is on
    at energy >= its threshold). Equals the number of elements that switch between them."""
    lo, hi = min(a, b), max(a, b)
    return sum(1 for t in ELEMENT_THRESHOLDS if lo < t <= hi)


def phrase_values(nodes: list[dict], start_pos: int, length_bars: int) -> list[float]:
    """The energy a section has at the start of each of its 8-bar phrases (leaving value).
    This is the element state of the phrase for sections with stepped energy (intro, default
    outro). _Interpretation_ for ramps: the sample at the phrase start decides."""
    return [energy_at(nodes, start_pos + k)[1] for k in range(0, length_bars, PHRASE_BARS)]


def boundary_changes(nodes: list[dict], start_pos: int, length_bars: int) -> list[int]:
    """Element changes at each inner 8-bar boundary of a section (one count per boundary)."""
    values = phrase_values(nodes, start_pos, length_bars)
    return [elements_crossed(a, b) for a, b in itertools.pairwise(values)]


def default_outro(start_value: float, min_length: int = 16) -> tuple[int, list[tuple[int, float]]]:
    """Default outro for an energy ``start_value`` flowing in from the previous section.

    User decisions 2026-10-30 ("Fliessend weiter": the first node is the previous end value, no
    step) and 2026-11-01 ("Max. 1 Element pro Grenze": at most one element changes per 8-bar
    boundary; the outro gets longer when needed). Returns ``(length_bars, [(pos, value), ...])``
    with ``pos`` relative to the outro's start (0 = the shared start node).

    Rule (_Interpretation_ of the note's thresholds, which are a proposal): the phrase values
    walk down the element intervals, so each boundary crosses exactly one threshold. A phrase's
    value is the lower bound of its interval (the element at that bound is still on); the first
    phrase keeps ``start_value``; the interval of 0.25 ends the walk at 0.25. The length is the
    smallest of 16, 32, 64 that is >= ``min_length`` and has a phrase per interval. Above 0.90
    the walk needs 9 phrases; 64 bars have 8, so the walk stops at the interval of 0.30 and the
    outro ends at 0.30 instead of 0.25. Extra phrases hold the last value.
    """
    if not 0.0 <= start_value <= 1.0:  # False for NaN
        raise ValueError(f"start_value must be in 0..1, got {start_value!r}")
    if min_length not in OUTRO_LENGTHS:
        raise ValueError(f"min_length must be one of {OUTRO_LENGTHS}, got {min_length!r}")
    bounds = ELEMENT_THRESHOLDS[::-1]
    first = next((i for i, b in enumerate(bounds) if start_value >= b), len(bounds))
    walk = [start_value]
    for b in bounds[first + 1:]:
        walk.append(OUTRO_END_VALUE if b == ELEMENT_THRESHOLDS[0] else b)
    walk = walk[:OUTRO_LENGTHS[-1] // PHRASE_BARS]
    length = next(n for n in OUTRO_LENGTHS if n >= min_length and n // PHRASE_BARS >= len(walk))
    phrases = length // PHRASE_BARS
    values = walk + [walk[-1]] * (phrases - len(walk))
    nodes = [(0, values[0])]
    current = values[0]
    for k in range(1, phrases):
        if values[k] != current:
            nodes += [(PHRASE_BARS * k, current), (PHRASE_BARS * k, values[k])]
            current = values[k]
    nodes.append((length, current))
    return length, nodes
