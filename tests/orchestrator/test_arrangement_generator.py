"""Plan generator G2 (#218): default energy nodes, settings effects, drawn-node overlay.

References are independent of the generator: the three templates T1-T3 are fixture files checked
by hand in the contract PR (#182); the other expected node lists are written out here from the
planner note (section 4) and INTERFACES. ``plan_problems`` is the oracle for validity only.
Seeds come from ``kp.rng`` so ``--fresh-seeds`` moves them.
"""

import json
from pathlib import Path

import pytest
from support import kick_params as kp

from orchestrator.arrangement_generator import generate_plan
from orchestrator.arrangement_layout import PlanRequest
from orchestrator.arrangement_plan import boundary_changes, plan_problems

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "arrangement_plan"

# Allowed setting values, written from INTERFACES "Settings".
ALLOWED = {
    "build_kick": ["filtered_in_build", "at_drop"], "intro_length": [16, 32, 64],
    "outro_length": [16, 32, 64], "intro_outro_bass": ["on", "outside_mix_zone", "off"],
    "breakdown_count": [1, 2], "breakdown_length": [16, 32, 64],
    "breakdown_rumble": ["off", "on"], "second_drop": ["stronger", "equal", "ask"],
    "change_grid": list(range(1, 65)), "pre_drop_gap": [0, 1, 2, 4],
    "fills": ["off", "section_change", "every_8"],
}


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def gen(genre="techno", bars=256, bpm=140, settings=None, **kw):
    return generate_plan(PlanRequest(genre, bpm, target_bars=bars, settings=settings), **kw)


def pairs(plan, lo=None, hi=None):
    return [(n["pos"], n["value"]) for n in plan["energy_nodes"]
            if (lo is None or lo <= n["pos"] <= hi)]


def random_settings(r):
    return {k: r.choice(v) for k, v in ALLOWED.items() if r.random() < 0.5}


# --- P2: the three templates, exactly --------------------------------------------------------

def test_templates_are_reproduced_exactly():
    t1 = fixture("T1")
    res = generate_plan(PlanRequest("techno", 140), sections=t1["sections"])
    assert res.ok and res.plan == t1
    for genre, name in (("techno", "T2"), ("trance", "T3")):
        res = gen(genre)
        assert res.ok and res.plan == fixture(name)
        assert [a["code"] for a in res.adjustments] == ["outro_lengthened"]
        assert [w["code"] for w in res.warnings] == ["duration_window"]


# --- P1 / P9: valid plans over the ranges, deterministic -------------------------------------

@pytest.mark.parametrize("genre", ["techno", "trance"])
def test_every_feasible_length_gives_a_valid_plan(genre):
    r = kp.rng(9100 + len(genre))
    setting_sets = [{}, {"intro_length": 16}, {"intro_length": 64, "breakdown_length": 16},
                    {"breakdown_count": 2}, {"second_drop": "equal", "change_grid": 64},
                    {"second_drop": "ask", "change_grid": 1}] + [random_settings(r)
                                                                for _ in range(6)]
    made = 0
    for settings in setting_sets:
        for bars in range(32, 1025, 8):
            bpm = r.choice([20, 100, 136, 140, 146, 180, 999, r.randint(20, 999)])
            res = gen(genre, bars, bpm, settings)
            if not res.ok:
                assert [e["code"] for e in res.errors] == ["length_infeasible"]
                continue
            made += 1
            assert plan_problems(res.plan) == [], (genre, bars, settings)
            assert res.plan["total_bars"] == bars and res.plan["bpm"] == bpm
            assert res.plan["energy_nodes"][-1]["pos"] == bars
            assert {k: res.plan["settings"][k] for k in settings} == settings
            assert not any(n["drawn"] for n in res.plan["energy_nodes"])
    assert made > 100


def test_same_request_gives_same_json():
    r = kp.rng(9200)
    for _ in range(30):
        genre, bars, settings = r.choice(["techno", "trance"]), r.randrange(160, 400, 8), \
            random_settings(r)
        drawn = [{"pos": r.randrange(0, 20) * 8, "value": r.random()} for _ in range(3)]
        drawn.sort(key=lambda n: n["pos"])
        a = json.dumps(gen(genre, bars, settings=settings, drawn_nodes=drawn), default=vars)
        b = json.dumps(gen(genre, bars, settings=settings, drawn_nodes=drawn), default=vars)
        assert a == b


# --- P5: the visible settings change the plan the documented way -----------------------------

def at(plan, pos):
    """Values of the nodes at ``pos``, in array order."""
    return [n["value"] for n in plan["energy_nodes"] if n["pos"] == pos]


def test_second_drop_setting():
    # T3: drop 1 spans pos 80..112, drop 2 pos 160..192
    for value, start2, end2 in (("stronger", 0.95, 1.0), ("equal", 0.9, 0.95),
                                ("ask", 0.9, 0.95)):
        plan = gen("trance", settings={"second_drop": value}).plan
        assert at(plan, 160) == [round(start2 - 0.05, 4), start2], value  # B3: build end | drop
        assert at(plan, 192)[0] == end2, value
        assert at(plan, 80) == [0.85, 0.9] and at(plan, 112)[0] == 0.95  # drop 1 never changes
    asked = gen("trance", settings={"second_drop": "ask"})
    assert [w["code"] for w in asked.warnings if w["code"] == "second_drop_ask"] == [
        "second_drop_ask"]
    assert all(w["code"] != "second_drop_ask" for w in gen("trance").warnings)


def test_intro_length_changes_the_intro_steps():
    expect = {16: [(0, 0.3), (8, 0.3), (8, 0.45), (16, 0.45)],
              32: [(0, 0.3), (8, 0.3), (8, 0.35), (16, 0.35), (16, 0.4), (24, 0.4), (24, 0.45),
                   (32, 0.45)]}
    for length, nodes in expect.items():
        res = gen(settings={"intro_length": length})
        assert pairs(res.plan, 0, length)[:len(nodes)] == nodes
        assert res.plan["sections"][0]["length_bars"] == length
    res = gen(bars=288, settings={"intro_length": 64})
    nodes = pairs(res.plan, 0, 64)[:-1]  # without the groove's leaving node
    assert len(nodes) == 2 + 2 * 7  # 8 phrases: 7 step pairs
    assert nodes[0] == (0, 0.3) and nodes[-1] == (64, 0.45)
    values = [v for _, v in nodes]
    assert values == sorted(values)


def test_breakdown_settings_change_layout_and_nodes():
    plan = gen(bars=240, settings={"breakdown_length": 16}).plan
    b = next(s for s in plan["sections"] if s["type"] == "breakdown")
    start = b["start_bar"] - 1
    assert b["length_bars"] == 16
    assert (at(plan, start)[-1], at(plan, start + 8), at(plan, start + 16)[0]) == (
        0.3, [0.2], 0.35)

    # breakdown_count 2: a third build and drop are appended after drop 2 (user decision)
    plan = gen("techno", 352, settings={"breakdown_count": 2}).plan
    types = [s["type"] for s in plan["sections"]]
    assert types[-7:] == ["breakdown", "build", "drop", "breakdown", "build", "drop", "outro"]
    drops = [s for s in plan["sections"] if s["type"] == "drop"]
    assert len(drops) == 3
    for d, (v0, v1) in zip(drops, [(0.9, 0.95), (0.95, 1.0), (0.95, 1.0)], strict=True):
        s = d["start_bar"] - 1
        assert (at(plan, s)[-1], at(plan, s + d["length_bars"])[0]) == (v0, v1)


def test_outro_length_setting_is_shadowed_after_a_full_drop():
    # The walk after a drop needs the 64-bar outro whatever outro_length says (INTERFACES).
    plans = [gen(settings={"outro_length": n}).plan for n in (16, 32, 64)]
    assert plans[0]["sections"][-1]["length_bars"] == 64
    assert plans[0]["energy_nodes"] == plans[1]["energy_nodes"] == plans[2]["energy_nodes"]


# --- P8: at most one element change per boundary in the default intro and outro --------------

def test_intro_and_outro_change_one_element_per_boundary():
    # hand-written: 64-bar outro from 1.00 drops one threshold per boundary (1.0 > .9 > .8 ...)
    res = gen("techno")
    out = res.plan["sections"][-1]
    assert boundary_changes(res.plan["energy_nodes"], out["start_bar"] - 1, 64) == [1] * 7
    # 32-bar intro .30 .35 .40 .45: only .35 -> .40 crosses a threshold (0.40)
    assert boundary_changes(res.plan["energy_nodes"], 0, 32) == [0, 1, 0]
    r = kp.rng(9300)
    for _ in range(60):
        settings = {"intro_length": r.choice([16, 32, 64]),
                    "second_drop": r.choice(ALLOWED["second_drop"]),
                    "outro_length": r.choice([16, 32, 64]),
                    "breakdown_count": r.choice([1, 2])}
        plan = gen(r.choice(["techno", "trance"]), r.randrange(200, 400, 8),
                   settings=settings)
        if not plan.ok:
            continue
        nodes, sections = plan.plan["energy_nodes"], plan.plan["sections"]
        for s in (sections[0], sections[-1]):
            changes = boundary_changes(nodes, s["start_bar"] - 1, s["length_bars"])
            assert max(changes, default=0) <= 1, (s["type"], settings, changes)


# --- P4: drawn nodes -------------------------------------------------------------------------

def test_drawn_single_node_replaces_a_default_pair():
    # T3: (32, 0.45 | 0.6) is the intro/groove step; one drawn node leaves only itself there
    res = gen("trance", drawn_nodes=[{"pos": 32, "value": 0.5}])
    assert pairs(res.plan, 24, 64) == [(24, 0.4), (24, 0.45), (32, 0.5), (64, 0.7)]
    assert [n["drawn"] for n in res.plan["energy_nodes"] if n["pos"] == 32] == [True]


def test_drawn_pair_is_kept_in_order_and_anchors_follow():
    # a drawn step pair at the groove end (64): 0.8 arriving, 0.2 leaving. The build continues
    # from 0.2 and ends 0.05 under drop 1's start; the jump into the build stands (B2, drawn).
    drawn = [{"pos": 64, "value": 0.8}, {"pos": 64, "value": 0.2}]
    res = gen("trance", drawn_nodes=drawn)
    assert pairs(res.plan, 32, 80) == [(32, 0.45), (32, 0.6), (64, 0.8), (64, 0.2),
                                       (80, 0.85), (80, 0.9)]
    assert [n["drawn"] for n in res.plan["energy_nodes"] if n["pos"] == 64] == [True, True]
    # the same with the values swapped keeps the swapped order
    swapped = gen("trance", drawn_nodes=drawn[::-1])
    assert [n["value"] for n in swapped.plan["energy_nodes"] if n["pos"] == 64] == [0.2, 0.8]


def test_build_end_anchor_never_falls_below_its_start():
    # drawn 0.95 at the groove end: the build starts at 0.95, so it stays flat (B3: max rule)
    res = gen("trance", drawn_nodes=[{"pos": 64, "value": 0.95}])
    assert pairs(res.plan, 64, 80) == [(64, 0.95), (80, 0.95), (80, 0.9)]


def test_outro_walks_from_a_drawn_start():
    # hand-derived from INTERFACES: from 0.5 the walk goes 0.5, 0.3, 0.25 (one element per
    # boundary: 0.4 then 0.3), then holds; the 64-bar slot of the drop stays
    res = gen("techno", drawn_nodes=[{"pos": 192, "value": 0.5}])
    assert pairs(res.plan, 192, 256) == [(192, 0.5), (200, 0.5), (200, 0.3), (208, 0.3),
                                         (208, 0.25), (256, 0.25)]


def test_drawn_nodes_survive_over_the_range():
    r = kp.rng(9400)
    for case in range(120):
        genre, bars = r.choice(["techno", "trance"]), r.choice([224, 256, 288, 320])
        base = gen(genre, bars, settings=random_settings(r))
        if not base.ok:
            continue
        sections = base.plan["sections"]
        bounds = [s["start_bar"] - 1 for s in sections]
        drawn = []
        for _ in range(r.randint(1, 8)):
            pos = r.choice([r.choice(bounds), r.randint(0, bars)])
            value = r.choice([0.0, 1.0, r.random(), r.random()])
            drawn.append({"pos": pos, "value": value})
            if r.random() < 0.25 and 0 < pos < bars:  # a pair
                drawn.append({"pos": pos, "value": r.random()})
        drawn.sort(key=lambda n: n["pos"])
        counts = {}
        for n in drawn:
            counts[n["pos"]] = counts.get(n["pos"], 0) + 1
        drawn = [n for n in drawn if counts[n["pos"]] <= 2]
        for edge in (0, bars):  # at most one node on the track edges
            on_edge = [n for n in drawn if n["pos"] == edge]
            drawn = [n for n in drawn if n not in on_edge[1:]]
        res = gen(genre, bars, settings=base.plan["settings"], drawn_nodes=drawn)
        assert res.ok, (case, drawn, res.errors)
        plan = res.plan
        assert plan_problems(plan) == [], case
        assert plan["sections"] == sections
        kept = [{"pos": n["pos"], "value": n["value"]}
                for n in plan["energy_nodes"] if n["drawn"]]
        assert kept == drawn, case
        positions = {n["pos"] for n in drawn}
        assert all(n["drawn"] for n in plan["energy_nodes"] if n["pos"] in positions)


# --- error paths -----------------------------------------------------------------------------

def codes(res):
    return [e["code"] for e in res.errors]


@pytest.mark.parametrize("drawn,reason", [
    ([{"pos": 8, "value": 1.2}], "value outside 0..1"),
    ([{"pos": 8, "value": -0.1}], "value outside 0..1"),
    ([{"pos": 300, "value": 0.5}], "pos outside 0..256"),
    ([{"pos": 16, "value": 0.5}, {"pos": 8, "value": 0.5}], "pos decreases"),
    ([{"pos": 8, "value": 0.5}] * 3, "third node at one pos"),
    ([{"pos": 0, "value": 0.5}] * 2, "pair at the track edge"),
    ([{"pos": 256, "value": 0.5}] * 2, "pair at the track edge"),
    ([{"pos": 8}], "needs integer pos and value"),
])
def test_invalid_drawn_nodes_are_refused(drawn, reason):
    res = gen(drawn_nodes=drawn)
    assert codes(res) == ["drawn_node_invalid"] and res.plan is None
    assert res.errors[0]["detail"]["reason"] == reason


def test_layout_errors_pass_through_and_return_no_plan():
    assert codes(generate_plan(PlanRequest("house", 140, target_bars=256))) == ["bad_genre"]
    assert codes(gen(bars=100)) == ["length_not_multiple_of_8"]


def test_explicit_sections_are_checked():
    ok = [{"type": "intro", "start_bar": 1, "length_bars": 16},
          {"type": "groove", "start_bar": 17, "length_bars": 16},
          {"type": "outro", "start_bar": 33, "length_bars": 16}]
    # the walk from the groove end 0.70 has six phrases (.70 .65 .55 .40 .30 .25): 64 bars;
    # a 16-bar slot is refused, not stretched
    res = generate_plan(PlanRequest("techno", 140), sections=ok)
    assert codes(res) == ["outro_slot_too_short"]
    assert res.errors[0]["detail"] == {"required": 64, "slot": 16}
    ok[2]["length_bars"] = 64
    assert generate_plan(PlanRequest("techno", 140), sections=ok).ok
    bad = [dict(ok[1], start_bar=1), *ok[1:]]  # does not start with an intro
    res = generate_plan(PlanRequest("techno", 140), sections=bad)
    assert codes(res) == ["sections_invalid"]
    assert codes(generate_plan(PlanRequest("techno", 140, target_bars=64), sections=ok)) == [
        "length_with_sections"]
