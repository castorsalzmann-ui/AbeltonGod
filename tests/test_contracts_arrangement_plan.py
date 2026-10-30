"""Arrangement plan format v0.1: contracts/arrangement-plan.schema.json (#146, D-024).

The schema carries what JSON Schema can say. ``plan_problems`` below carries the rest of the
contract (docs/INTERFACES.md, "Arrangement plan"): sections tile the track, intro first and
outro last, node order, step pairs, and the boundary rules B2/B3 for nodes the user did not draw.
It is the executable form of those rules; the planner window and the generator must accept and
reject exactly the instances below.

Expected values (template node values, bar ranges, defaults, interpolated energies) are written
here by hand from docs/research/2026-10-29_arrangement-planner-sections-energy.md, sections 3.1,
4 and 8, not computed with the checker.
"""

import copy
import itertools
import json
import math
import random
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_FILE = ROOT / "contracts" / "arrangement-plan.schema.json"
SCHEMA = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA)

# Entry mode per section type (B1 step / B2 continue). Must-resolve 2 of #146: the outro enters
# with a step (default start min(previous end, 0.55), T5 allows the jump down). The alternative
# (outro continues, no 0.55 cap) is the one-line change "outro": "continue".
ENTRY_MODE = {
    "groove": "step",
    "break": "step",
    "breakdown": "step",
    "build": "continue",
    "drop": "step",
    "outro": "step",
}
B3_MARGIN = 0.05  # B3: a build ends at max(its start value, next section's start - 0.05)
TOL = 1e-9


# --- the rules ---------------------------------------------------------------------------------

def _at(nodes: list[dict], pos: int) -> list[dict]:
    return [n for n in nodes if n["pos"] == pos]


def energy_at(nodes: list[dict], x: float) -> tuple[float, float]:
    """(value arriving from the left, value leaving to the right) at ``x``; linear in between.
    Needs nodes that already pass the order rules."""
    here = [n for n in nodes if n["pos"] == x]
    if here:
        return here[0]["value"], here[-1]["value"]
    left = [n for n in nodes if n["pos"] < x][-1]
    right = next(n for n in nodes if n["pos"] > x)
    frac = (x - left["pos"]) / (right["pos"] - left["pos"])
    v = left["value"] + frac * (right["value"] - left["value"])
    return v, v


def plan_problems(plan, entry_mode: dict | None = None) -> list[str]:
    """Every contract rule ``plan`` breaks, as "code: detail" (empty = valid plan)."""
    modes = ENTRY_MODE if entry_mode is None else entry_mode
    errors = sorted(VALIDATOR.iter_errors(plan), key=lambda e: list(e.absolute_path))
    if errors:  # the cross-field rules below assume the shape
        return [f"schema: {list(e.absolute_path)} {e.message}" for e in errors]
    problems = []
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
        here = _at(nodes, start)
        if (modes[s["type"]] == "continue" and len(here) == 2
                and not (here[0]["drawn"] or here[1]["drawn"])
                and abs(here[0]["value"] - here[1]["value"]) > TOL):
            problems.append(f"b2_jump: undrawn jump into continue section {i} at pos {start}")
        if s["type"] == "build":
            end = start + s["length_bars"]
            at_end = _at(nodes, end)
            if at_end and not at_end[0]["drawn"]:
                begin = energy_at(nodes, start)[1]
                want = max(begin, at_end[-1]["value"] - B3_MARGIN)
                if abs(at_end[0]["value"] - want) > TOL:
                    problems.append(
                        f"b3_build_end: build {i} ends at {at_end[0]['value']} at pos {end}, "
                        f"expected {want}")
    return problems


def codes(plan, **kw) -> set[str]:
    return {p.split(":", 1)[0] for p in plan_problems(plan, **kw)}


# --- templates T1-T3 (note section 3.1) with the default nodes of section 4 ------------------

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
    "fills": "section_change",
}


def _plan(sections: list[tuple[str, int, int]], nodes: list[tuple[int, float]], total: int) -> dict:
    return {
        "schema_version": "0.1",
        "bpm": 140,
        "time_signature": "4/4",
        "phrase_bars": 8,
        "total_bars": total,
        "sections": [{"type": t, "start_bar": b, "length_bars": n} for t, b, n in sections],
        "energy_nodes": [{"pos": p, "value": v, "drawn": False} for p, v in nodes],
        "settings": dict(DEFAULT_SETTINGS),
    }


INTRO_32 = [(0, 0.30), (8, 0.30), (8, 0.35), (16, 0.35), (16, 0.40), (24, 0.40), (24, 0.45)]


def _outro_32(start: int, arriving: float) -> list[tuple[int, float]]:
    # v0 = min(previous end, 0.55) = 0.55 after every drop here; one step down per 8 bars
    s = start
    return [(s, arriving), (s, 0.55), (s + 8, 0.55), (s + 8, 0.45), (s + 16, 0.45),
            (s + 16, 0.35), (s + 24, 0.35), (s + 24, 0.25), (s + 32, 0.25)]


T1 = _plan(
    [("intro", 1, 32), ("groove", 33, 32), ("breakdown", 65, 16), ("build", 81, 16),
     ("drop", 97, 32), ("outro", 129, 32)],
    [*INTRO_32, (32, 0.45), (32, 0.60), (64, 0.70), (64, 0.30), (72, 0.20), (80, 0.35),
     (96, 0.85), (96, 0.90), *_outro_32(128, 0.95)],
    160,
)
T2 = _plan(
    [("intro", 1, 32), ("groove", 33, 32), ("break", 65, 8), ("build", 73, 8), ("drop", 81, 32),
     ("breakdown", 113, 32), ("build", 145, 16), ("drop", 161, 32), ("outro", 193, 32)],
    [*INTRO_32, (32, 0.45), (32, 0.60), (64, 0.70), (64, 0.45), (72, 0.45), (80, 0.85),
     (80, 0.90), (112, 0.95), (112, 0.30), (128, 0.20), (144, 0.35), (160, 0.90), (160, 0.95),
     *_outro_32(192, 1.00)],
    224,
)
T3 = _plan(
    [("intro", 1, 32), ("groove", 33, 32), ("build", 65, 16), ("drop", 81, 32),
     ("breakdown", 113, 32), ("build", 145, 16), ("drop", 161, 32), ("outro", 193, 32)],
    [*INTRO_32, (32, 0.45), (32, 0.60), (64, 0.70), (80, 0.85), (80, 0.90), (112, 0.95),
     (112, 0.30), (128, 0.20), (144, 0.35), (160, 0.90), (160, 0.95), *_outro_32(192, 1.00)],
    224,
)
TEMPLATES = {"T1": T1, "T2": T2, "T3": T3}


def t2() -> dict:
    return copy.deepcopy(T2)


# --- schema and templates -----------------------------------------------------------------------

def test_schema_is_valid_2020_12_with_its_own_id() -> None:
    Draft202012Validator.check_schema(SCHEMA)
    assert SCHEMA["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert SCHEMA["$id"].endswith("/contracts/arrangement-plan.schema.json")
    assert SCHEMA["properties"]["schema_version"] == {"const": "0.1"}


@pytest.mark.parametrize("name", TEMPLATES)
def test_templates_are_valid_plans(name: str) -> None:
    assert plan_problems(TEMPLATES[name]) == []


def test_templates_have_the_lengths_of_the_note() -> None:
    assert [T1["total_bars"], T2["total_bars"], T3["total_bars"]] == [160, 224, 224]
    # T2 bar ranges from the note's table (section 3.1), 1-based and inclusive
    ranges = [(s["start_bar"], s["start_bar"] + s["length_bars"] - 1) for s in T2["sections"]]
    assert ranges == [(1, 32), (33, 64), (65, 72), (73, 80), (81, 112), (113, 144), (145, 160),
                      (161, 192), (193, 224)]
    # T1 keeps its 16-bar breakdown although breakdown_length is 32 (lengths apply on placing)
    assert T1["sections"][2] == {"type": "breakdown", "start_bar": 65, "length_bars": 16}
    assert T1["settings"]["breakdown_length"] == 32


def test_template_curve_reads_as_designed() -> None:
    """Linear interpolation and step-pair order, checked on literal values of T2."""
    nodes = T2["energy_nodes"]
    assert energy_at(nodes, 48) == pytest.approx((0.65, 0.65))      # groove 0.60 -> 0.70
    assert energy_at(nodes, 64) == (0.70, 0.45)                      # groove end | break
    assert energy_at(nodes, 76) == pytest.approx((0.65, 0.65))      # build 0.45 -> 0.85
    assert energy_at(nodes, 80) == (0.85, 0.90)                      # build end | drop
    assert energy_at(nodes, 120) == pytest.approx((0.25, 0.25))     # breakdown 0.30 -> 0.20
    assert energy_at(nodes, 192) == (1.00, 0.55)                     # drop 2 end | outro
    assert energy_at(nodes, 204) == (0.45, 0.45)                     # outro step held
    assert energy_at(nodes, 224) == (0.25, 0.25)


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
    "change_grid": [4, 8, 16],
    "pre_drop_gap": [0, 1, 2, 4],
    "fills": ["off", "section_change", "every_8"],
}


def test_settings_are_the_eleven_of_the_note_all_required() -> None:
    assert len(ALLOWED) == 11
    assert sorted(SETTINGS["required"]) == sorted(ALLOWED)
    assert sorted(SETTINGS["properties"]) == sorted(ALLOWED)
    assert SETTINGS["additionalProperties"] is False


@pytest.mark.parametrize("key", ALLOWED)
def test_setting_allowed_values_and_default(key: str) -> None:
    prop = SETTINGS["properties"][key]
    assert prop["enum"] == ALLOWED[key]
    assert prop["default"] == DEFAULT_SETTINGS[key]


def test_every_setting_combination_leaves_the_templates_valid() -> None:
    """A setting never invalidates a stored plan (D-024): a seeded sample of the 69,984
    combinations on T1-T3, plus change_grid 16 and 4 with T2's 8-bar break and build."""
    combos = list(itertools.product(*ALLOWED.values()))
    assert len(combos) == 69984
    rng = random.Random(146)
    sample = rng.sample(combos, 80) + [
        tuple(16 if k == "change_grid" else DEFAULT_SETTINGS[k] for k in ALLOWED),
        tuple(4 if k == "change_grid" else DEFAULT_SETTINGS[k] for k in ALLOWED),
    ]
    for combo in sample:
        for plan in TEMPLATES.values():
            doc = copy.deepcopy(plan)
            doc["settings"] = dict(zip(ALLOWED, combo, strict=True))
            assert plan_problems(doc) == [], combo


@pytest.mark.parametrize(("key", "bad"), [
    ("change_grid", 12), ("change_grid", 32), ("change_grid", "8"), ("pre_drop_gap", 3),
    ("pre_drop_gap", "1 bar"), ("fills", "on"), ("fills", True), ("intro_length", 48),
    ("breakdown_count", 0), ("breakdown_count", 3), ("second_drop", "weaker"),
    ("build_kick", "out_last_4"), ("intro_outro_bass", None), ("breakdown_rumble", False),
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


# --- negative instances --------------------------------------------------------------------------

def _set(path, value):
    def change(doc):
        target = doc
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
    return change


def _delete(path):
    def change(doc):
        target = doc
        for key in path[:-1]:
            target = target[key]
        del target[path[-1]]
    return change


SCHEMA_INVALID = {
    "missing energy_nodes": _delete(["energy_nodes"]),
    "missing settings": _delete(["settings"]),
    "extra root key": _set(["events"], []),
    "schema_version 0.2": _set(["schema_version"], "0.2"),
    "time signature 3/4": _set(["time_signature"], "3/4"),
    "phrase_bars 16": _set(["phrase_bars"], 16),
    "bpm 19": _set(["bpm"], 19),
    "bpm 1000": _set(["bpm"], 1000),
    "bpm inf": _set(["bpm"], math.inf),
    "bpm string": _set(["bpm"], "140"),
    "total not multiple of 8": _set(["total_bars"], 228),
    "total 24": _set(["total_bars"], 24),
    "total 1032": _set(["total_bars"], 1032),
    "total float": _set(["total_bars"], 224.5),
    "unknown section type": _set(["sections", 2, "type"], "peak"),
    "section extra key": _set(["sections", 2, "index"], 1),
    "section missing start": _delete(["sections", 2, "start_bar"]),
    "start_bar 0": _set(["sections", 0, "start_bar"], 0),
    "length 12": _set(["sections", 2, "length_bars"], 12),
    "break 32 (not allowed)": _set(["sections", 2, "length_bars"], 32),
    "groove 8 (not allowed)": _set(["sections", 1, "length_bars"], 8),
    "build 64 (not allowed)": _set(["sections", 3, "length_bars"], 64),
    "intro 8 (not allowed)": _set(["sections", 0, "length_bars"], 8),
    "outro 48 (not allowed)": _set(["sections", 8, "length_bars"], 48),
    "one section": _set(["sections"], [{"type": "intro", "start_bar": 1, "length_bars": 32}]),
    "one node": lambda d: d.update(energy_nodes=d["energy_nodes"][:1]),
    "value 1.01": _set(["energy_nodes", 3, "value"], 1.01),
    "value -0.01": _set(["energy_nodes", 3, "value"], -0.01),
    "value bool": _set(["energy_nodes", 3, "value"], True),
    "pos 2.5": _set(["energy_nodes", 3, "pos"], 2.5),
    "pos -1": _set(["energy_nodes", 0, "pos"], -1),
    "drawn missing": _delete(["energy_nodes", 3, "drawn"]),
    "drawn as int": _set(["energy_nodes", 3, "drawn"], 1),
    "node extra key": _set(["energy_nodes", 3, "curve"], "exp"),
}


@pytest.mark.parametrize("change", SCHEMA_INVALID.values(), ids=SCHEMA_INVALID)
def test_schema_invalid_instances(change) -> None:
    doc = t2()
    change(doc)
    assert codes(doc) == {"schema"}


def _swap(i, j):
    def change(doc):
        n = doc["energy_nodes"]
        n[i], n[j] = n[j], n[i]
    return change


def _insert(index, node):
    return lambda d: d["energy_nodes"].insert(index, node)


# index of nodes in T2: 0 (0) 1-2 (8) 3-4 (16) 5-6 (24) 7-8 (32) 9-10 (64) 11 (72) 12-13 (80)
# 14-15 (112) 16 (128) 17 (144) 18-19 (160) 20-21 (192) 22-23 (200) ... 28 (224)
RULE_INVALID = {
    "gap between sections": (_set(["sections", 2, "start_bar"], 73), {"tiling"}),
    "overlap": (_set(["sections", 3, "start_bar"], 65), {"tiling"}),
    "sections shorter than total": (_set(["sections", 8, "length_bars"], 16), {"total_bars"}),
    "total longer than sections": (lambda d: (d.update(total_bars=232),
                                              d["energy_nodes"][-1].update(pos=232)),
                                   {"total_bars"}),
    "first not intro": (_set(["sections", 0, "type"], "groove"), {"first_not_intro"}),
    "last not outro": (_set(["sections", 8, "type"], "drop"), {"last_not_outro"}),
    "intro inside": (_set(["sections", 1, "type"], "intro"), {"intro_outro_inside"}),
    "outro inside": (_set(["sections", 5, "type"], "outro"), {"intro_outro_inside"}),
    "nodes out of order": (_swap(16, 17), {"node_order"}),
    "three nodes at a pair": (_insert(13, {"pos": 80, "value": 0.88, "drawn": True}),
                              {"three_at_pos"}),
    "three nodes, two drawn": (_insert(10, {"pos": 64, "value": 0.5, "drawn": True}),
                               {"three_at_pos"}),
    "first node not at 0": (_set(["energy_nodes", 0, "pos"], 1), {"first_node_pos"}),
    "no node at 0": (lambda d: d["energy_nodes"].pop(0), {"first_node_pos"}),
    "last node not at total": (_set(["energy_nodes", 28, "pos"], 223), {"last_node_pos"}),
    "node beyond total": (_set(["energy_nodes", 28, "pos"], 225), {"last_node_pos"}),
    "pair at 0": (_insert(1, {"pos": 0, "value": 0.4, "drawn": True}), {"pair_at_edge"}),
    "pair at total": (lambda d: d["energy_nodes"].append({"pos": 224, "value": 0.1, "drawn": True}),
                      {"pair_at_edge"}),
    "bpm nan": (_set(["bpm"], math.nan), {"nonfinite"}),
    "value nan": (_set(["energy_nodes", 3, "value"], math.nan), {"nonfinite"}),
}


@pytest.mark.parametrize(("change", "expected"), RULE_INVALID.values(), ids=RULE_INVALID)
def test_rule_invalid_instances(change, expected: set[str]) -> None:
    doc = t2()
    change(doc)
    assert codes(doc) == expected


# --- step pairs and boundary rules ------------------------------------------------------------

def test_step_pair_order_is_binding() -> None:
    """Swapping a pair changes the curve; at a build end the swap breaks B3 (V6)."""
    doc = t2()
    _swap(9, 10)(doc)                                   # 64: 0.70 | 0.45 -> 0.45 | 0.70
    assert energy_at(doc["energy_nodes"], 64) == (0.45, 0.70)
    assert energy_at(doc["energy_nodes"], 60) != energy_at(T2["energy_nodes"], 60)
    doc = t2()
    _swap(12, 13)(doc)                                  # 80: 0.85 | 0.90 -> 0.90 | 0.85
    assert codes(doc) == {"b3_build_end"}


def test_stable_sort_keeps_the_plan_and_value_sort_changes_the_curve() -> None:
    """Sorting pairs by value often still passes every rule (step entries have no rule), so
    order is a reader/writer duty, not only a validity check: the curve itself changes."""
    nodes = T2["energy_nodes"]
    assert sorted(nodes, key=lambda n: n["pos"]) == nodes
    by_value = sorted(nodes, key=lambda n: (n["pos"], n["value"]))
    assert by_value != nodes
    assert energy_at(by_value, 64) == (0.45, 0.70)          # break would enter at 0.70
    assert energy_at(by_value, 192) == (0.55, 1.00)         # outro would enter at 1.00


def test_b2_undrawn_jump_into_a_build_fails_and_drawn_passes() -> None:
    doc = t2()                                          # T2 build 1 starts at pos 72 (0.45)
    _insert(12, {"pos": 72, "value": 0.50, "drawn": False})(doc)
    assert codes(doc) == {"b2_jump"}                    # B3 end stays max(0.50, 0.85)
    for which in (11, 12):
        drawn = copy.deepcopy(doc)
        drawn["energy_nodes"][which]["drawn"] = True
        assert "b2_jump" not in codes(drawn), which
    flat = t2()
    _insert(12, {"pos": 72, "value": 0.45, "drawn": False})(flat)
    assert plan_problems(flat) == []                    # a pair without a jump is no jump


def test_b2_step_sections_may_jump_undrawn() -> None:
    """groove, break, breakdown, drop and outro enter with a step: T2 has undrawn jumps there."""
    jumps = {p for p in (32, 64, 80, 112, 160, 192)
             if len(_at(T2["energy_nodes"], p)) == 2}
    assert jumps == {32, 64, 80, 112, 160, 192}
    assert all(not n["drawn"] for n in T2["energy_nodes"])
    assert plan_problems(T2) == []


def test_outro_entry_mode_is_step_and_continue_is_one_line_away() -> None:
    """Must-resolve 2: V6 tests the chosen rule. With outro = continue the default outro start
    min(previous end, 0.55) after a drop would be an undrawn jump."""
    assert ENTRY_MODE["outro"] == "step"
    assert ENTRY_MODE["build"] == "continue"
    assert codes(T2, entry_mode={**ENTRY_MODE, "outro": "continue"}) == {"b2_jump"}
    assert codes(T1, entry_mode={**ENTRY_MODE, "outro": "continue"}) == {"b2_jump"}


def test_b3_build_end_follows_the_drop_unless_drawn() -> None:
    doc = t2()
    doc["energy_nodes"][13]["value"] = 0.80              # drop 1 starts lower
    assert codes(doc) == {"b3_build_end"}                # build end must become 0.75
    doc["energy_nodes"][12]["value"] = 0.75
    assert plan_problems(doc) == []
    doc["energy_nodes"][13]["value"] = 0.30              # below the build start (0.45)
    doc["energy_nodes"][12]["value"] = 0.45              # end = max(start, 0.25) = start
    assert plan_problems(doc) == []
    doc["energy_nodes"][12].update(value=0.99, drawn=True)
    assert plan_problems(doc) == []                      # drawn by the user: never overridden


def test_b3_tolerance_is_tight() -> None:
    doc = t2()
    doc["energy_nodes"][12]["value"] = 0.85 + 1e-6
    assert codes(doc) == {"b3_build_end"}


def test_a_third_node_is_rejected_not_merged() -> None:
    """Must-resolve 3: a third node at a pos that holds a step pair is invalid, drawn or not."""
    for drawn in (False, True):
        for index in (12, 13, 14):
            doc = t2()
            _insert(index, {"pos": 80, "value": 0.87, "drawn": drawn})(doc)
            assert "three_at_pos" in codes(doc), (drawn, index)


# --- seeded property tests over the whole range ---------------------------------------------

LENGTHS = {
    "intro": [16, 32, 64], "groove": [16, 32, 48, 64], "break": [8, 16],
    "breakdown": [16, 32, 64], "build": [8, 16, 32], "drop": [16, 32, 64], "outro": [16, 32, 64],
}
MIDDLE = ["groove", "break", "breakdown", "build", "drop"]


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
        at_end = _at(nodes, end)
        if at_end[0]["drawn"]:
            continue
        if len(at_end) == 1:
            at_end[0]["drawn"] = True
        else:
            begin = energy_at(nodes, start)[1]
            at_end[0]["value"] = max(begin, at_end[1]["value"] - B3_MARGIN)
    for s in sections[1:]:
        here = _at(nodes, s["start_bar"] - 1)
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
    kind = rng.choice(["shift", "order", "third", "value", "edge", "length", "total", "b2"])
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
        extra = 3 - len(_at(nodes, p))
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
    start = s["start_bar"] - 1
    here = _at(nodes, start)
    for n in here:
        n["drawn"] = False
    first = nodes.index(here[0])
    jump = here[-1]["value"] + rng.choice([-1, 1]) * rng.uniform(0.01, 0.5)
    if len(here) == 1:
        nodes.insert(first, {"pos": start, "value": min(1.0, max(0.0, jump)), "drawn": False})
    else:
        here[0]["value"] = min(1.0, max(0.0, jump))
    if abs(_at(nodes, start)[0]["value"] - _at(nodes, start)[1]["value"]) <= TOL:
        return _break_one(rng, plan)
    return {"b2_jump"}


def test_random_plans_with_one_violation_fail_with_its_code() -> None:
    rng = random.Random(146146)
    for _ in range(600):
        plan = random_plan(rng)
        must = _break_one(rng, plan)
        found = codes(plan)
        assert found & must, (must, plan_problems(plan))
