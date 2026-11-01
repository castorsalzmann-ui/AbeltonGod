"""Arrangement plan format v0.1: contracts/arrangement-plan.schema.json (#146, D-024).

The rule checker lives in ``src/orchestrator/arrangement_plan.py`` (one implementation, no copy
here). Positive and negative instances are JSON files in ``tests/fixtures/arrangement_plan/``
(templates T1-T3 and ``cases.json``), so a reader in another language can run the same cases.

Expected values (template node values, bar ranges, defaults, interpolated energies, element
counts) are written here by hand from docs/research/2026-10-29_arrangement-planner-sections-
energy.md, sections 3.1, 4, 5.1 and 8, and from the user decisions of 2026-10-30 / 2026-11-01.
The element model below is a second, independent table of the note's thresholds.
"""

import copy
import itertools
import json
import math
import random
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from orchestrator import arrangement_plan as ap
from orchestrator.arrangement_plan import (
    B3_MARGIN,
    ENTRY_MODE,
    TOL,
    boundary_changes,
    change_points,
    default_outro,
    energy_at,
    nodes_at,
    plan_problems,
    problem_codes,
)

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_FILE = ROOT / "contracts" / "arrangement-plan.schema.json"
SCHEMA = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
FIXTURES = ROOT / "tests" / "fixtures" / "arrangement_plan"


def codes(plan, **kw) -> set[str]:
    return problem_codes(plan, **kw)


# --- fixtures: templates and cases as JSON -----------------------------------------------------

def _decode(value):
    """JSON cannot hold NaN/Infinity: {"$number": "nan"} stands for the float."""
    if isinstance(value, dict):
        if set(value) == {"$number"}:
            return float(value["$number"])
        return {k: _decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode(v) for v in value]
    return value


def _load(name: str):
    return _decode(json.loads((FIXTURES / name).read_text(encoding="utf-8")))


def apply_patch(doc: dict, patch: list[dict]) -> dict:
    """RFC 6902 add / remove / replace on a deep copy ('-' appends)."""
    doc = copy.deepcopy(doc)
    for step in patch:
        *parents, last = step["path"].split("/")[1:]
        target = doc
        for key in parents:
            target = target[int(key)] if isinstance(target, list) else target[key]
        if isinstance(target, list):
            if step["op"] == "add":
                target.append(step["value"]) if last == "-" else target.insert(
                    int(last), step["value"])
            elif step["op"] == "remove":
                del target[int(last)]
            else:
                target[int(last)] = step["value"]
        elif step["op"] == "remove":
            del target[last]
        else:
            assert step["op"] in ("add", "replace"), step
            target[last] = step["value"]
    return doc


T1, T2, T3 = (_load(f"{n}.json") for n in ("T1", "T2", "T3"))
TEMPLATES = {"T1": T1, "T2": T2, "T3": T3}
CASES_FILE = _load("cases.json")
CASES = CASES_FILE["cases"]
BASE = _load(CASES_FILE["base"])

DEFAULT_SETTINGS = {
    "build_kick": "filtered_in_build",
    "intro_length": 32,
    "outro_length": 32,
    "intro_outro_bass": "on",
    "breakdown_count": 1,
    "breakdown_length": 32,
    "breakdown_rumble": "off",
    "second_drop": "stronger",
    "change_grid": 8,
    "pre_drop_gap": 4,
    "fills": "off",
}

LENGTHS = {
    "intro": [16, 32, 64], "groove": [16, 32, 48, 64], "break": [8, 16],
    "breakdown": [16, 32, 64], "build": [8, 16, 32], "drop": [16, 32, 64], "outro": [16, 32, 64],
}
MIDDLE = ["groove", "break", "breakdown", "build", "drop"]


def t2() -> dict:
    return copy.deepcopy(T2)


# --- the checker is the one in src/ -------------------------------------------------------------

def test_one_checker_in_src_and_none_in_the_tests() -> None:
    """The planner, generator and builder import orchestrator.arrangement_plan; this file must
    not grow a second implementation (INTERFACES: one checker)."""
    import ast

    defined = {n.name for n in ast.walk(ast.parse(Path(__file__).read_text(encoding="utf-8")))
               if isinstance(n, ast.FunctionDef)}
    assert not defined & {"plan_problems", "energy_at", "nodes_at", "change_points"}
    assert ap.SCHEMA_FILE == SCHEMA_FILE
    assert ap.schema() == SCHEMA


# --- schema and templates -----------------------------------------------------------------------

def test_schema_is_valid_2020_12_with_its_own_id() -> None:
    Draft202012Validator.check_schema(SCHEMA)
    assert SCHEMA["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert SCHEMA["$id"].endswith("/contracts/arrangement-plan.schema.json")
    assert SCHEMA["properties"]["schema_version"] == {"const": "0.1"}


def test_plan_is_not_a_tool_input_and_could_not_be_sent_strict() -> None:
    """Claude does not send plans (INTERFACES.md). The one strict checker confirms the schema
    is outside the strict subset, so it must never be registered as a tool unchanged."""
    from test_contracts import TOOL_SCHEMAS, strict_subset_problems

    from orchestrator.kick_tools import TOOL_CONTRACTS

    assert SCHEMA_FILE.name not in TOOL_SCHEMAS.values()
    assert SCHEMA_FILE.name not in TOOL_CONTRACTS.values()  # what the wiring registers (#148)
    problems = strict_subset_problems(SCHEMA)
    for keyword in ("'minimum'", "'multipleOf'", "'$ref'", "'$defs'"):
        assert any(keyword in p for p in problems), keyword


@pytest.mark.parametrize("name", TEMPLATES)
def test_templates_are_valid_plans(name: str) -> None:
    assert plan_problems(TEMPLATES[name]) == []


def test_templates_have_the_lengths_of_the_note_and_the_long_outro() -> None:
    """T2/T3 and T1 got a 64-bar outro (user decision 2026-11-01, "Max. 1 Element pro Grenze"):
    from a full drop it takes eight phrases to take the elements out one by one."""
    assert [T1["total_bars"], T2["total_bars"], T3["total_bars"]] == [192, 256, 256]
    ranges = [(s["start_bar"], s["start_bar"] + s["length_bars"] - 1) for s in T2["sections"]]
    assert ranges == [(1, 32), (33, 64), (65, 72), (73, 80), (81, 112), (113, 144), (145, 160),
                      (161, 192), (193, 256)]
    assert [s["type"] for s in T1["sections"]] == [
        "intro", "groove", "breakdown", "build", "drop", "outro"]
    assert [s["length_bars"] for s in T1["sections"]] == [32, 32, 16, 16, 32, 64]
    assert [s["type"] for s in T3["sections"]] == [
        "intro", "groove", "build", "drop", "breakdown", "build", "drop", "outro"]
    # T1 keeps its 16-bar breakdown although breakdown_length is 32 (lengths apply on placing)
    assert T1["sections"][2] == {"type": "breakdown", "start_bar": 65, "length_bars": 16}
    assert T1["settings"]["breakdown_length"] == 32
    for plan in TEMPLATES.values():
        assert plan["settings"] == DEFAULT_SETTINGS


def test_template_curve_reads_as_designed() -> None:
    """Linear interpolation and step-pair order, checked on literal values of T2."""
    nodes = T2["energy_nodes"]
    assert energy_at(nodes, 48) == pytest.approx((0.65, 0.65))      # groove 0.60 -> 0.70
    assert energy_at(nodes, 64) == (0.70, 0.45)                      # groove end | break
    assert energy_at(nodes, 76) == pytest.approx((0.65, 0.65))      # build 0.45 -> 0.85
    assert energy_at(nodes, 80) == (0.85, 0.90)                      # build end | drop
    assert energy_at(nodes, 120) == pytest.approx((0.25, 0.25))     # breakdown 0.30 -> 0.20
    assert energy_at(nodes, 192) == (1.00, 1.00)                     # outro continues
    assert energy_at(nodes, 200) == (1.00, 0.80)                     # first decay step
    assert energy_at(nodes, 212) == (0.75, 0.75)                     # second phrase held
    assert energy_at(nodes, 224) == (0.70, 0.65)
    assert energy_at(nodes, 248) == (0.40, 0.30)
    assert energy_at(nodes, 256) == (0.30, 0.30)


def test_plain_json_integers_and_whole_number_floats() -> None:
    """INTERFACES: writers emit JSON integers. JSON Schema 2020-12 `integer` also accepts a
    whole-number float, so the checker does too (and treats 8.0 as the same position as 8)."""
    doc = t2()
    doc["total_bars"] = 256.0
    doc["sections"][2]["start_bar"] = 65.0
    doc["energy_nodes"][9]["pos"] = 64.0
    doc["energy_nodes"][10]["pos"] = 64.0
    doc["settings"]["change_grid"] = 8.0
    assert plan_problems(doc) == []


# --- JSON cases --------------------------------------------------------------------------------

def test_cases_file_is_well_formed_and_covers_every_rule_code() -> None:
    names = [c["name"] for c in CASES]
    assert len(names) == len(set(names)) == len(CASES) > 60
    seen = {code for c in CASES for code in c["expect"]}
    assert seen == {
        "schema", "tiling", "total_bars", "first_not_intro", "last_not_outro",
        "intro_outro_inside", "node_order", "three_at_pos", "first_node_pos", "last_node_pos",
        "pair_at_edge", "nonfinite", "b2_jump", "b3_build_end"}
    assert sum(1 for c in CASES if not c["expect"]) >= 10   # positive cases next to negatives
    assert plan_problems(BASE) == []


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_json_case(case: dict) -> None:
    doc = apply_patch(BASE, _decode(case["patch"]))
    assert codes(doc) == set(case["expect"]), plan_problems(doc)


def test_step_pair_order_is_binding() -> None:
    """Swapping a pair changes the curve; at a build end the swap breaks B3 (V6)."""
    nodes = t2()["energy_nodes"]
    assert energy_at(nodes, 64) == (0.70, 0.45)
    swapped = copy.deepcopy(nodes)
    swapped[9], swapped[10] = swapped[10], swapped[9]            # 64: 0.70 | 0.45 -> 0.45 | 0.70
    assert energy_at(swapped, 64) == (0.45, 0.70)
    assert energy_at(swapped, 60) != energy_at(nodes, 60)       # the groove end moved


def test_stable_sort_keeps_the_plan_and_value_sort_changes_the_curve() -> None:
    """Sorting pairs by value often still passes every rule (step entries have no rule), so
    order is a reader/writer duty, not only a validity check: the curve itself changes."""
    nodes = T2["energy_nodes"]
    assert sorted(nodes, key=lambda n: n["pos"]) == nodes
    by_value = sorted(nodes, key=lambda n: (n["pos"], n["value"]))
    assert by_value != nodes
    assert energy_at(by_value, 64) == (0.45, 0.70)          # break would enter at 0.70
    assert energy_at(by_value, 112) == (0.30, 0.95)         # breakdown would enter at 0.95


def test_b2_step_sections_may_jump_undrawn() -> None:
    """groove, break, breakdown and drop enter with a step: T2 has undrawn jumps there."""
    jumps = {p for p in (32, 64, 80, 112, 160) if len(nodes_at(T2["energy_nodes"], p)) == 2}
    assert jumps == {32, 64, 80, 112, 160}
    assert all(not n["drawn"] for n in T2["energy_nodes"])
    assert plan_problems(T2) == []


def test_entry_modes_follow_the_user_decisions() -> None:
    assert ENTRY_MODE == {
        "groove": "step", "break": "step", "breakdown": "step", "build": "continue",
        "drop": "step", "outro": "continue"}
    for plan, start, end in ((T1, 128, 0.95), (T2, 192, 1.00), (T3, 192, 1.00)):
        assert nodes_at(plan["energy_nodes"], start) == [
            {"pos": start, "value": end, "drawn": False}]
    # the table is read: with outro = step, the undrawn jump of the old default is allowed
    old = apply_patch(T2, [{"op": "add", "path": "/energy_nodes/21",
                            "value": {"pos": 192, "value": 0.55, "drawn": False}}])
    assert codes(old) == {"b2_jump"}
    assert plan_problems(old, entry_mode={**ENTRY_MODE, "outro": "step"}) == []


def test_b3_margin_and_tolerance_are_the_contract_values() -> None:
    assert B3_MARGIN == 0.05
    assert TOL == 1e-9


# --- outro and intro: at most one element per 8-bar boundary ------------------------------------

# A second table of the note's section 5.1 (drum-led elements; kick always on, bass set by
# `intro_outro_bass`), kept apart from the module's tuple on purpose.
ELEMENTS = {"atmos": 0.20, "hats": 0.30, "perc1": 0.40, "clap": 0.55, "synth": 0.65,
            "pad": 0.70, "open_hat": 0.75, "perc2": 0.80, "synth2": 0.90}


def elements_on(value: float) -> set[str]:
    return {name for name, threshold in ELEMENTS.items() if value >= threshold}


def changes(a: float, b: float) -> int:
    return len(elements_on(a) ^ elements_on(b))


def test_threshold_table_matches_the_note() -> None:
    assert ap.ELEMENT_THRESHOLDS == tuple(sorted(ELEMENTS.values()))
    assert ap.OUTRO_LENGTHS == (16, 32, 64)
    assert ap.MIX_ZONE_CAP == 0.50
    assert ap.OUTRO_END_VALUE == 0.25


def test_the_note_example_counts() -> None:
    """Hand-counted: 1.00 -> 0.75 crosses 0.80 and 0.90 (2); 0.75 -> 0.50 crosses 0.55, 0.65,
    0.70, 0.75 (4); 0.50 -> 0.25 crosses 0.30 and 0.40 (2). The even-step outro of the first
    PR draft therefore fails the rule; the walk down the intervals does not."""
    assert [changes(a, b) for a, b in ((1.0, .75), (.75, .5), (.5, .25))] == [2, 4, 2]
    assert [ap.elements_crossed(a, b) for a, b in ((1.0, .75), (.75, .5), (.5, .25))] == [2, 4, 2]
    old_nodes = [{"pos": p, "value": v, "drawn": False} for p, v in (
        (0, 1.0), (8, 1.0), (8, .75), (16, .75), (16, .5), (24, .5), (24, .25), (32, .25))]
    assert boundary_changes(old_nodes, 0, 32) == [2, 4, 2]
    assert ap.elements_crossed(.5, .5) == 0
    assert ap.elements_crossed(.8, .8 - 1e-12) == 1      # an element is on AT its threshold
    assert ap.elements_crossed(.3, .2) == 1 and ap.elements_crossed(.2, .3) == 1


@pytest.mark.parametrize("name", TEMPLATES)
def test_template_outros_change_one_element_per_boundary(name: str) -> None:
    plan = TEMPLATES[name]
    outro = plan["sections"][-1]
    assert outro["length_bars"] == 64
    start = outro["start_bar"] - 1
    assert boundary_changes(plan["energy_nodes"], start, 64) == [1] * 7
    first = nodes_at(plan["energy_nodes"], start)[0]["value"]
    assert phrases_of(plan, start) == pytest.approx([first, .80, .75, .70, .65, .55, .40, .30])
    # the last 16 bars (mix zone) stay under the cap
    assert max(phrases_of(plan, start)[-2:]) <= 0.50


def phrases_of(plan: dict, start: int) -> list[float]:
    return ap.phrase_values(plan["energy_nodes"], start, 64)


@pytest.mark.parametrize("name", TEMPLATES)
def test_template_intros_change_at_most_one_element_per_boundary(name: str) -> None:
    nodes = TEMPLATES[name]["energy_nodes"]
    assert ap.phrase_values(nodes, 0, 32) == [0.30, 0.35, 0.40, 0.45]
    assert boundary_changes(nodes, 0, 32) == [0, 1, 0]       # perc 1 comes in at 0.40 (hand count)


def test_default_outro_literal_walks() -> None:
    full = (64, [(0, 1.0), (8, 1.0), (8, .8), (16, .8), (16, .75), (24, .75), (24, .7), (32, .7),
                 (32, .65), (40, .65), (40, .55), (48, .55), (48, .4), (56, .4), (56, .3),
                 (64, .3)])
    assert default_outro(1.0) == full
    assert default_outro(1.0, 64) == full
    # from 0.85 the walk reaches the interval of 0.25 in eight phrases
    length, nodes = default_outro(0.85)
    assert length == 64
    assert [v for p, v in nodes if p == 56] == [.3, .25]
    assert nodes[-1] == (64, .25)
    # shorter starts need fewer phrases: 0.52 -> 0.30 -> 0.25 takes three, so 32 bars
    assert default_outro(0.52) == (32, [(0, .52), (8, .52), (8, .3), (16, .3), (16, .25),
                                         (32, .25)])
    assert default_outro(0.35) == (16, [(0, .35), (8, .35), (8, .25), (16, .25)])
    assert default_outro(0.35, 32) == (32, [(0, .35), (8, .35), (8, .25), (32, .25)])
    assert default_outro(0.10) == (16, [(0, .1), (16, .1)])
    assert default_outro(0.0, 64) == (64, [(0, 0.0), (64, 0.0)])
    assert default_outro(0.25, 32) == (32, [(0, .25), (32, .25)])


@pytest.mark.parametrize("bad", [-0.01, 1.01, math.nan, math.inf])
def test_default_outro_refuses_a_start_outside_0_1(bad: float) -> None:
    with pytest.raises(ValueError, match="start_value"):
        default_outro(bad)


@pytest.mark.parametrize("bad", [0, 8, 24, 48, 128])
def test_default_outro_refuses_a_length_that_is_not_allowed(bad: int) -> None:
    with pytest.raises(ValueError, match="min_length"):
        default_outro(0.5, bad)


def _starts(rng: random.Random) -> float:
    edges = [0.0, 1.0, 0.25, *ELEMENTS.values()]
    pick = rng.random()
    if pick < 0.3:
        return rng.choice(edges)
    if pick < 0.5:
        e = rng.choice(edges)
        return min(1.0, max(0.0, e + rng.choice([-1, 1]) * rng.choice([1e-12, 1e-9, 0.01])))
    return rng.random()


def _plan_with_outro(start: float, min_length: int) -> tuple[dict, int]:
    length, outro = default_outro(start, min_length)
    nodes = [*[(p, v) for p, v in [(0, .30), (8, .30), (8, .35), (16, .35), (16, .40), (24, .40),
                                   (24, .45), (32, .45)]],
             (32, start), *[(64 + p, v) for p, v in outro]]
    plan = {
        "schema_version": "0.1", "bpm": 140, "time_signature": "4/4", "phrase_bars": 8,
        "total_bars": 64 + length,
        "sections": [{"type": "intro", "start_bar": 1, "length_bars": 32},
                     {"type": "drop", "start_bar": 33, "length_bars": 32},
                     {"type": "outro", "start_bar": 65, "length_bars": length}],
        "energy_nodes": [{"pos": p, "value": v, "drawn": False} for p, v in nodes],
        "settings": dict(DEFAULT_SETTINGS),
    }
    return plan, length


def test_default_outro_over_the_whole_range() -> None:
    """Seeded: any start 0..1 (thresholds, just either side of them, random), every minimum
    length. The outro is a valid plan part, never changes more than one element per boundary
    (counted with the independent element table), only goes down, honours the mix-zone cap,
    and takes the shortest allowed length."""
    rng = random.Random(20261101)
    seen_lengths = set()
    for _ in range(3000):
        start = _starts(rng)
        floor = rng.choice([16, 32, 64])
        plan, length = _plan_with_outro(start, floor)
        assert plan_problems(plan) == [], (start, floor)
        seen_lengths.add(length)
        assert length in (16, 32, 64) and length >= floor
        values = ap.phrase_values(plan["energy_nodes"], 64, length)
        assert len(values) == length // 8
        assert values[0] == start
        for a, b in itertools.pairwise(values):
            assert b <= a, (start, values)
            assert changes(a, b) <= 1, (start, floor, values)
        assert max(values[-2:]) <= 0.50, (start, values)
        assert boundary_changes(plan["energy_nodes"], 64, length) == [
            changes(a, b) for a, b in itertools.pairwise(values)]
        # the walk ends at the interval of 0.25 (0.30 when the start needs nine phrases),
        # or stays where it started below 0.30
        assert values[-1] == (0.30 if start >= 0.90 else 0.25 if start >= 0.30 else start)
        # shortest allowed length: independent count of the element sets the walk passes
        needed = min(8, changes(start, 0.25) + 1) if start >= 0.30 else 1
        if start >= 0.90:
            needed = 8
        assert length == next(n for n in (16, 32, 64) if n >= floor and n // 8 >= needed), (
            start, floor, length)
    assert seen_lengths == {16, 32, 64}


def test_default_outro_start_above_0_90_needs_the_full_64_and_ends_at_0_30() -> None:
    for start in (0.90, 0.95, 1.0):
        length, nodes = default_outro(start)
        assert length == 64 and nodes[-1] == (64, 0.30)
    for start in (0.80, 0.89, 0.8999):
        length, nodes = default_outro(start)
        assert length == 64 and nodes[-1] == (64, 0.25)


# --- change points (user decision 2026-11-01: the grid counts from each section's start) --------

def _with_grid(plan: dict, grid: int) -> dict:
    doc = copy.deepcopy(plan)
    doc["settings"]["change_grid"] = grid
    return doc


def test_change_points_literal_examples() -> None:
    # T2 sections start at pos 0, 32, 64, 72, 80, 112, 144, 160, 192 and end at 256
    assert change_points(T2) == [0, 8, 16, 24, 32, 40, 48, 56, 64, 72, 80, 88, 96, 104, 112, 120,
                                 128, 136, 144, 152, 160, 168, 176, 184, 192, 200, 208, 216, 224,
                                 232, 240, 248]
    # grid 12: every section restarts the count (reviewer's example: bar 33, 16-bar section)
    plan = _with_grid(T2, 12)
    pts = change_points(plan)
    assert [p for p in pts if 32 <= p < 64] == [32, 44, 56]      # groove: 32 bars from pos 32
    assert [p for p in pts if 64 <= p < 80] == [64, 72]         # break 8 bars, build 8 bars
    assert [p for p in pts if 144 <= p < 160] == [144, 156]     # build 2: 16 bars from pos 144
    assert [p for p in pts if 192 <= p < 256] == [192, 204, 216, 228, 240, 252]
    # grid 1: every bar; grid 64 (the bound): only the section starts
    assert change_points(_with_grid(T2, 1)) == list(range(256))
    assert change_points(_with_grid(T2, 64)) == [0, 32, 64, 72, 80, 112, 144, 160, 192]
    # a grid of 4 is a subdivision of 8: every 8-bar point stays
    four = change_points(_with_grid(T2, 4))
    assert set(change_points(T2)) <= set(four) and len(four) == 64


def _section_of(plan: dict, pos: int) -> dict:
    return next(s for s in plan["sections"]
                if s["start_bar"] - 1 <= pos < s["start_bar"] - 1 + s["length_bars"])


def test_change_points_over_the_whole_range() -> None:
    """Brute force: bar ``pos`` is a change point iff its distance to the start of its own
    section is a multiple of the grid. Every grid 1..64 on the templates and on random plans."""
    rng = random.Random(20261101)
    plans = [*TEMPLATES.values(), *(random_plan(rng) for _ in range(60))]
    for plan in plans:
        for grid in [*range(1, 65), rng.randint(1, 64)]:
            doc = _with_grid(plan, grid)
            expected = [pos for pos in range(doc["total_bars"])
                        if (pos - (_section_of(doc, pos)["start_bar"] - 1)) % grid == 0]
            assert change_points(doc) == expected, (grid, doc["sections"])
            assert set(s["start_bar"] - 1 for s in doc["sections"]) <= set(expected)


def test_change_points_read_only_the_sections_and_the_grid() -> None:
    """The setting never moves a section or a node, drawn or not: the call leaves the plan
    unchanged, and no node value or flag changes the result."""
    for grid in (1, 3, 8, 12, 64):
        doc = _with_grid(T2, grid)
        before = copy.deepcopy(doc)
        points = change_points(doc)
        assert doc == before
        other = copy.deepcopy(doc)
        for n in other["energy_nodes"]:
            n["value"], n["drawn"] = 1.0 - n["value"], True
        assert change_points(other) == points
        assert plan_problems(doc) == []                         # the setting itself breaks nothing


# --- settings ----------------------------------------------------------------------------------

SETTINGS = SCHEMA["$defs"]["settings"]
ALLOWED = {
    "build_kick": ["filtered_in_build", "at_drop"],
    "intro_length": [16, 32, 64],
    "outro_length": [16, 32, 64],
    "intro_outro_bass": ["on", "outside_mix_zone", "off"],
    "breakdown_count": [1, 2],
    "breakdown_length": [16, 32, 64],
    "breakdown_rumble": ["off", "on"],
    "second_drop": ["stronger", "equal", "ask"],
    # change_grid is any whole bar count 1..64 (user decision 2026-10-30); these are samples
    "change_grid": [1, 3, 4, 8, 12, 16, 63, 64],
    "pre_drop_gap": [0, 1, 2, 4],
    "fills": ["off", "section_change", "every_8"],
}


def test_settings_are_the_eleven_of_the_note_all_required() -> None:
    assert len(ALLOWED) == 11
    assert sorted(SETTINGS["required"]) == sorted(ALLOWED)
    assert sorted(SETTINGS["properties"]) == sorted(ALLOWED)
    assert SETTINGS["additionalProperties"] is False


@pytest.mark.parametrize("key", [k for k in ALLOWED if k != "change_grid"])
def test_setting_allowed_values_and_default(key: str) -> None:
    prop = SETTINGS["properties"][key]
    assert prop["enum"] == ALLOWED[key]
    assert prop["default"] == DEFAULT_SETTINGS[key]


def test_change_grid_is_any_whole_bar_count_1_to_64_default_8() -> None:
    prop = SETTINGS["properties"]["change_grid"]
    assert prop["default"] == 8 == DEFAULT_SETTINGS["change_grid"]
    assert (prop["minimum"], prop["maximum"], prop["type"]) == (1, 64, "integer")
    assert "enum" not in prop
    for n in range(-3, 100):
        doc = t2()
        doc["settings"]["change_grid"] = n
        assert (plan_problems(doc) == []) == (1 <= n <= 64), n
    for bad in (10**6, 2.5, "8", None, True, math.nan):
        doc = t2()
        doc["settings"]["change_grid"] = bad
        assert codes(doc) == {"schema"}, bad


def test_the_checker_never_reads_settings_beyond_the_schema() -> None:
    """Honest scope (review round 1): `plan_problems` checks `settings` only through the
    schema, so this test shows that every allowed value is accepted by the format, not that a
    generator keeps sections and nodes still. That property (V6 of the planner note, V2 of the
    musical-transfer note) needs generated plans and belongs to the generator issue. What is
    testable now is `change_points` above: it moves nothing."""
    combos = list(itertools.product(*ALLOWED.values()))
    rng = random.Random(146)
    sample = rng.sample(combos, 80)
    for combo in sample:
        for plan in TEMPLATES.values():
            doc = copy.deepcopy(plan)
            doc["settings"] = dict(zip(ALLOWED, combo, strict=True))
            assert plan_problems(doc) == [], combo


@pytest.mark.parametrize(("key", "bad"), [
    ("pre_drop_gap", 3), ("pre_drop_gap", "1 bar"), ("fills", "on"), ("fills", True),
    ("intro_length", 48), ("breakdown_count", 0), ("breakdown_count", 3),
    ("second_drop", "weaker"), ("build_kick", "out_last_4"), ("intro_outro_bass", None),
    ("breakdown_rumble", False),
])
def test_setting_values_outside_the_list_fail(key: str, bad) -> None:
    doc = t2()
    doc["settings"][key] = bad
    assert codes(doc) == {"schema"}


def test_settings_missing_or_extra_key_fails() -> None:
    for key in ALLOWED:
        doc = t2()
        del doc["settings"][key]
        assert codes(doc) == {"schema"}, key
    doc = t2()
    doc["settings"]["swing"] = 0.1
    assert codes(doc) == {"schema"}


# --- section lengths ---------------------------------------------------------------------------

@pytest.mark.parametrize("index", range(9))
def test_each_section_type_takes_exactly_its_lengths(index: int) -> None:
    """Every length 4..128 in steps of 4 on every T2 section: the schema accepts exactly the
    lengths of the note's table (another length then only breaks the tiling)."""
    kind = T2["sections"][index]["type"]
    for n in range(4, 129, 4):
        doc = t2()
        doc["sections"][index]["length_bars"] = n
        assert ("schema" in codes(doc)) == (n not in LENGTHS[kind]), (kind, n)


# --- seeded property tests over the whole range ---------------------------------------------

def _value(rng: random.Random) -> float:
    return rng.choice([0.0, 1.0, rng.random(), rng.random()])


def random_plan(rng: random.Random) -> dict:
    """A random valid plan: any section order, every allowed length, any node values."""
    types = ["intro", *(rng.choice(MIDDLE) for _ in range(rng.randint(0, 14))), "outro"]
    lengths = [rng.choice(LENGTHS[t]) for t in types]
    while sum(lengths) > 1024:
        del types[1], lengths[1]
    sections, bar = [], 1
    for t, n in zip(types, lengths, strict=True):
        sections.append({"type": t, "start_bar": bar, "length_bars": n})
        bar += n
    total = bar - 1
    bounds = {s["start_bar"] - 1 for s in sections} | {total}
    positions = sorted(bounds | set(rng.sample(range(1, total), rng.randint(0, 10))))
    nodes = []
    for p in positions:
        for _ in range(1 if p in (0, total) else rng.choice([1, 2])):
            nodes.append({"pos": p, "value": _value(rng), "drawn": rng.random() < 0.3})
    plan = {
        "schema_version": "0.1", "bpm": rng.choice([20, 999, rng.uniform(20, 999)]),
        "time_signature": "4/4", "phrase_bars": 8, "total_bars": total,
        "sections": sections, "energy_nodes": nodes,
        "settings": {k: rng.choice(v) for k, v in ALLOWED.items()},
    }
    for s in sections:  # B3, then B2 (marking a node drawn changes no value)
        if s["type"] != "build":
            continue
        start, end = s["start_bar"] - 1, s["start_bar"] - 1 + s["length_bars"]
        at_end = nodes_at(nodes, end)
        if at_end[0]["drawn"]:
            continue
        if len(at_end) == 1:
            if rng.random() < 0.5:
                at_end[0]["drawn"] = True
            else:  # a single undrawn end node: B3 makes the build flat (v = build start)
                at_end[0]["value"] = energy_at(nodes, start)[1]
        else:
            begin = energy_at(nodes, start)[1]
            at_end[0]["value"] = max(begin, at_end[1]["value"] - B3_MARGIN)
    for s in sections[1:]:
        here = nodes_at(nodes, s["start_bar"] - 1)
        if ENTRY_MODE[s["type"]] == "continue" and len(here) == 2:
            here[0]["drawn"] = True
    return plan


def test_random_plans_over_the_whole_range_are_valid() -> None:
    rng = random.Random(20261030)
    seen_types, seen_totals = set(), set()
    for _ in range(400):
        plan = random_plan(rng)
        assert plan_problems(plan) == [], plan
        seen_types |= {s["type"] for s in plan["sections"]}
        seen_totals.add(plan["total_bars"])
    assert seen_types == set(LENGTHS)
    assert min(seen_totals) <= 64 and max(seen_totals) >= 512


def _break_one(rng: random.Random, plan: dict) -> set[str]:
    """Apply one random violation; return the codes that must appear."""
    nodes, sections = plan["energy_nodes"], plan["sections"]
    kind = rng.choice(["shift", "order", "third", "value", "edge", "length", "total", "b2", "b3"])
    if kind == "shift" and len(sections) > 2:
        sections[rng.randrange(1, len(sections))]["start_bar"] += rng.choice([-8, 8, 16])
        return {"tiling"}
    if kind == "order":
        pairs = [(i, j) for i in range(len(nodes)) for j in range(i + 1, len(nodes))
                 if nodes[i]["pos"] != nodes[j]["pos"]]
        i, j = rng.choice(pairs)
        nodes[i], nodes[j] = nodes[j], nodes[i]
        return {"node_order"}
    if kind == "third":
        i = rng.randrange(1, len(nodes) - 1)
        while nodes[i]["pos"] in (0, plan["total_bars"]):
            i = rng.randrange(1, len(nodes) - 1)
        p = nodes[i]["pos"]
        extra = 3 - len(nodes_at(nodes, p))
        for _ in range(extra):
            nodes.insert(i, {"pos": p, "value": _value(rng), "drawn": True})
        return {"three_at_pos"}
    if kind == "value":
        rng.choice(nodes)["value"] = rng.choice([1 + rng.uniform(1e-9, 5), -rng.uniform(1e-9, 5)])
        return {"schema"}
    if kind == "edge":
        if rng.random() < 0.5:
            nodes.insert(0, {"pos": 0, "value": _value(rng), "drawn": True})
        else:
            nodes.append({"pos": plan["total_bars"], "value": _value(rng), "drawn": True})
        return {"pair_at_edge"}
    if kind == "length":
        s = rng.choice(sections)
        s["length_bars"] = rng.choice(
            [n for n in range(8, 129, 4) if n not in LENGTHS[s["type"]]])
        return {"schema"}
    if kind == "total":
        plan["total_bars"] += rng.choice([-8, 8])
        return {"total_bars", "last_node_pos"} if 32 <= plan["total_bars"] <= 1024 else {"schema"}
    builds = [s for s in sections if s["type"] == "build"]
    if not builds:
        return _break_one(rng, plan)
    s = rng.choice(builds)
    if kind == "b3":  # move an undrawn build end off max(start, next - 0.05)
        end = nodes_at(nodes, s["start_bar"] - 1 + s["length_bars"])
        if end[0]["drawn"]:
            return _break_one(rng, plan)
        end[0]["value"] = min(1.0, max(0.0, end[0]["value"] + rng.choice([-1, 1]) * 0.2))
        if abs(end[0]["value"] - (max(energy_at(nodes, s["start_bar"] - 1)[1],
                                      end[-1]["value"] - B3_MARGIN))) <= TOL:
            return _break_one(rng, plan)
        return {"b3_build_end"}
    start = s["start_bar"] - 1
    here = nodes_at(nodes, start)
    for n in here:
        n["drawn"] = False
    first = nodes.index(here[0])
    jump = here[-1]["value"] + rng.choice([-1, 1]) * rng.uniform(0.01, 0.5)
    if len(here) == 1:
        nodes.insert(first, {"pos": start, "value": min(1.0, max(0.0, jump)), "drawn": False})
    else:
        here[0]["value"] = min(1.0, max(0.0, jump))
    if abs(nodes_at(nodes, start)[0]["value"] - nodes_at(nodes, start)[1]["value"]) <= TOL:
        return _break_one(rng, plan)
    return {"b2_jump"}


def test_random_plans_with_one_violation_fail_with_its_code() -> None:
    rng = random.Random(146146)
    for _ in range(600):
        plan = random_plan(rng)
        must = _break_one(rng, plan)
        found = codes(plan)
        assert found & must, (must, plan_problems(plan))
