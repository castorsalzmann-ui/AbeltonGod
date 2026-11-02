"""Timeline derivation G4 (#221): P6, P7, P8 and V5 of the generator design note.

Independent references: the expected element sets of the curated cases are written out by hand
from the planner note (5.1-5.4) for the template T2 (a fixture file checked in the contract PR);
the random properties compare against ``ref_elements`` below, which keeps its OWN copy of the
thresholds and rules and measures the mean energy by sampling (the module integrates exactly).
Seeds come from ``kp.rng`` so ``--fresh-seeds`` moves them.
"""

import copy
import json
from pathlib import Path

import pytest
from support import kick_params as kp

from orchestrator import arrangement_plan as ap
from orchestrator.arrangement_generator import generate_plan
from orchestrator.arrangement_layout import PlanRequest
from orchestrator.arrangement_timeline import ELEMENT_THRESHOLDS, derive_timeline

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "arrangement_plan"

# The test's own copy of the table (planner note 5.1).
OWN = {"atmos": 0.20, "hats_closed": 0.30, "perc1": 0.40, "bass": 0.45, "clap": 0.55,
       "synth": 0.65, "pad": 0.70, "hat_open": 0.75, "perc2": 0.80, "synth2": 0.90}
DRUM_LED = ("intro", "groove", "drop", "outro")

ALLOWED = {
    "build_kick": ["filtered_in_build", "at_drop"], "intro_length": [16, 32, 64],
    "outro_length": [16, 32, 64], "intro_outro_bass": ["on", "outside_mix_zone", "off"],
    "breakdown_count": [1, 2], "breakdown_length": [16, 32, 64],
    "breakdown_rumble": ["off", "on"], "second_drop": ["stronger", "equal", "ask"],
    "change_grid": list(range(1, 65)), "pre_drop_gap": [0, 1, 2, 4],
    "fills": ["off", "section_change", "every_8"],
}


def t2(**settings):
    plan = json.loads((FIXTURES / "T2.json").read_text())
    plan["settings"].update(settings)
    return plan


def cells_by_start(plan):
    return {c.start: c for c in derive_timeline(plan).cells}


def kinds(plan, kind):
    return [(e.start_beat, e.length_beats) for e in derive_timeline(plan).events if e.kind == kind]


# --- one table ---------------------------------------------------------------------------------

def test_thresholds_are_the_note_table():
    assert ELEMENT_THRESHOLDS == OWN
    assert sorted(v for k, v in OWN.items() if k != "bass") == list(ap.ELEMENT_THRESHOLDS)


# --- element states of the default T2 (hand-written, grid 8) -----------------------------------

BASE = {"kick", "atmos", "hats_closed", "perc1", "bass", "clap"}
ALL_DRUM = BASE | {"synth", "pad", "hat_open", "perc2", "synth2"}


def test_default_t2_element_states():
    c = cells_by_start(t2())
    assert sorted(c) == list(range(0, 256, 8))  # one cell per phrase
    assert c[0].elements == {"kick", "atmos", "hats_closed"}  # 0.30, mix zone, bass not yet
    assert c[8].elements == {"kick", "atmos", "hats_closed"}
    assert c[16].elements == {"kick", "atmos", "hats_closed", "perc1"}  # 0.40
    assert c[24].elements == {"kick", "atmos", "hats_closed", "perc1", "bass"}  # last intro phrase
    assert c[32].elements == c[40].elements == BASE  # mean 0.6125 / 0.6375: below synth 0.65
    assert c[48].elements == c[56].elements == BASE | {"synth"}  # 0.6625 / 0.6875
    assert c[64].elements == {"atmos", "hats_closed", "perc1"}  # break 0.45: no kick, no bass
    assert c[72].elements == {"kick", "bass", "synth"}  # build after a break, ramp 0.45 -> 0.85
    assert c[80].elements == ALL_DRUM  # drop, mean 0.9063
    for start in (112, 120, 128, 136):  # breakdown energy 0.2 .. 0.3: below 0.40
        assert c[start].elements == {"atmos", "pad", "synth"}
    assert c[144].elements == {"kick", "bass"}  # build ramp 0.35 -> 0.9, mean 0.4875
    assert c[152].elements == {"kick", "bass", "synth"}  # mean 0.7625
    assert c[160].elements == ALL_DRUM


def test_default_t2_outro_loses_one_element_per_phrase():
    c = cells_by_start(t2())
    expect = [  # energy, element lost at this phrase (hand-listed from the threshold table)
        (1.0, None), (0.80, "synth2"), (0.75, "perc2"), (0.70, "hat_open"), (0.65, "pad"),
        (0.55, "synth"), (0.40, "clap"), (0.30, "perc1")]
    left = set(ALL_DRUM)
    for k, (energy, lost) in enumerate(expect):
        left -= {lost}
        cell = c[192 + 8 * k]
        assert cell.elements == left, k
        assert cell.energy == energy


def test_a_breakdown_never_has_kick_or_clap_and_a_build_never_drums():
    for plan in (t2(), t2(build_kick="at_drop", breakdown_rumble="on")):
        for c in derive_timeline(plan).cells:
            if c.type in ("break", "breakdown"):
                assert not {"kick", "bass"} & c.elements
            if c.type == "breakdown":
                assert not {"clap", "synth2"} & c.elements
            if c.type == "build":
                assert c.elements <= {"kick", "bass", "synth"}


# --- each setting value changes the timeline as documented (hand-written) ----------------------

def test_build_kick():
    default = cells_by_start(t2())
    at_drop = cells_by_start(t2(build_kick="at_drop"))
    assert at_drop[72].elements == {"kick", "bass", "synth"}  # after a break: in either way
    assert default[144].elements == {"kick", "bass"}
    assert at_drop[144].elements == frozenset()  # after a breakdown: out until the drop
    assert at_drop[152].elements == {"synth"}
    assert at_drop[80] == default[80] and at_drop[160] == default[160]  # the drops are the same


def test_intro_outro_bass():
    def bass(plan):
        c = cells_by_start(plan)
        return ([s for s in range(0, 32, 8) if "bass" in c[s].elements],
                [s for s in range(192, 256, 8) if "bass" in c[s].elements])

    assert bass(t2()) == ([24], list(range(192, 256, 8)))
    assert bass(t2(intro_outro_bass="outside_mix_zone")) == ([24], list(range(192, 240, 8)))
    assert bass(t2(intro_outro_bass="off")) == ([], [])


def test_breakdown_rumble():
    off, on = cells_by_start(t2()), cells_by_start(t2(breakdown_rumble="on"))
    for s in (112, 120, 128, 136):
        assert "rumble" not in off[s].elements
        assert on[s].elements == off[s].elements | {"rumble"}
    assert all("rumble" not in c.elements for s, c in on.items() if not 112 <= s < 144)


def test_change_grid_changes_the_cells_not_the_plan():
    def starts(g, lo, hi):
        return [c.start for c in derive_timeline(t2(change_grid=g)).cells if lo <= c.start < hi]

    assert starts(8, 112, 144) == [112, 120, 128, 136]
    assert starts(12, 112, 144) == [112, 124, 136]  # counted from the section start
    assert starts(64, 112, 144) == [112]
    assert starts(4, 64, 72) == [64, 68]  # the 8-bar break
    assert starts(12, 64, 72) == [64]  # a grid longer than the section: its start only
    assert starts(12, 144, 160) == [144, 156]
    lens = [c.length for c in derive_timeline(t2(change_grid=12)).cells if 112 <= c.start < 144]
    assert lens == [12, 12, 8]
    # one cell per section with grid 64: the intro's four steps (mean 0.375) become one state
    assert cells_by_start(t2(change_grid=64))[0].elements == {"kick", "atmos", "hats_closed"}


@pytest.mark.parametrize("gap", [0, 1, 2, 4])
def test_pre_drop_gap(gap):
    expect = [] if gap == 0 else [(320 - gap, gap), (640 - gap, gap)]  # drops at bar 80, 160
    assert kinds(t2(pre_drop_gap=gap), "pre_drop_gap") == expect


def test_events_default_t2():
    assert kinds(t2(), "riser") == [(288, 32), (576, 64)]
    assert kinds(t2(), "impact") == [(320, 0), (640, 0)]
    assert kinds(t2(), "downlifter") == [(256, 4), (448, 4)]
    assert kinds(t2(), "fill") == []  # fills are off by default


def test_fills_section_change():
    # drum-led -> drum-led boundaries of T2: intro|groove at bar 32, drop|outro at bar 192
    assert kinds(t2(fills="section_change"), "fill") == [(124, 4), (764, 4)]


def test_fills_every_8():
    ends = ([8, 16, 24, 32] + [40, 48, 56]  # intro; groove (the break follows: last phrase none)
            + [88, 96, 104]  # first drop (breakdown follows)
            + [168, 176, 184, 192]  # second drop, then the outro
            + [200, 208, 216, 224, 232, 240, 248])  # outro, end of the track: last phrase none
    assert kinds(t2(fills="every_8"), "fill") == [((e - 1) * 4, 4) for e in ends]


def test_fills_never_repeat_at_consecutive_boundaries():
    for fills in ("section_change", "every_8"):
        v = [e.variant for e in derive_timeline(t2(fills=fills)).events if e.kind == "fill"]
        assert len(v) > 1 and all(a != b for a, b in zip(v, v[1:], strict=False))


def test_a_pre_drop_gap_replaces_the_fill_before_a_drop():
    sections = [{"type": "intro", "start_bar": 1, "length_bars": 16},
                {"type": "groove", "start_bar": 17, "length_bars": 16},
                {"type": "drop", "start_bar": 33, "length_bars": 16},
                {"type": "outro", "start_bar": 49, "length_bars": 16}]
    nodes = [{"pos": 0, "value": 0.5, "drawn": True}, {"pos": 64, "value": 0.5, "drawn": True}]
    p = {"sections": sections, "energy_nodes": nodes, "settings": {**t2()["settings"],
         "fills": "section_change", "pre_drop_gap": 2}}
    ev = [(e.kind, e.start_beat, e.length_beats) for e in derive_timeline(p).events]
    assert ("fill", 60, 4) in ev and ("fill", 124, 4) not in ev  # intro|groove yes, groove|drop no
    assert ("pre_drop_gap", 126, 2) in ev and ("fill", 188, 4) in ev  # drop|outro still filled


# --- random plans: P6, P7 ----------------------------------------------------------------------

def ref_mean(nodes, a, b):
    """Mean energy by sampling 16 midpoints per bar (a different method from the module)."""
    total = 0.0
    n = 16 * (b - a)
    for j in range(n):
        x = a + (j + 0.5) / 16
        left = [m for m in nodes if m["pos"] < x][-1]
        right = [m for m in nodes if m["pos"] > x][0]
        total += left["value"] + (x - left["pos"]) / (right["pos"] - left["pos"]) * (
            right["value"] - left["value"])
    return round(total / n, 9)


def ref_elements(kind, prev, e, start, sec_start, sec_end, st):
    """The note's rules (5.1-5.3) written again from scratch for one cell; e is the mean energy."""
    t = OWN
    drums = {n for n in ("atmos", "hats_closed", "perc1", "clap", "synth", "pad", "hat_open",
                         "perc2", "synth2") if e >= t[n]}
    if kind in DRUM_LED:
        out = {"kick"} | drums
        if kind in ("groove", "drop") and e >= t["bass"]:
            out.add("bass")
        if kind == "intro" and st["intro_outro_bass"] != "off" and start >= sec_end - 8:
            if not (st["intro_outro_bass"] == "outside_mix_zone" and start < sec_start + 16):
                out.add("bass")
        if kind == "outro" and st["intro_outro_bass"] != "off":
            if not (st["intro_outro_bass"] == "outside_mix_zone" and start >= sec_end - 16):
                out.add("bass")
        return out
    if kind == "break":
        return drums
    if kind == "breakdown":
        out = {"atmos", "pad"} | ({"synth"} if e >= 0.2 else set())
        if e >= 0.4:
            out |= {n for n in ("hats_closed", "hat_open", "perc1", "perc2") if e >= t[n]}
        return out | ({"rumble"} if st["breakdown_rumble"] == "on" else set())
    out = set()  # build
    if st["build_kick"] == "filtered_in_build" or prev in ("groove", "break"):
        out |= {"kick", "bass"}
    return out | ({"synth"} if e >= 0.5 else set())


def ref_cells(plan):
    g = plan["settings"]["change_grid"]
    out = {}
    for i, s in enumerate(plan["sections"]):
        a0 = s["start_bar"] - 1
        a1 = a0 + s["length_bars"]
        prev = plan["sections"][i - 1]["type"] if i else None
        for a in range(a0, a1, g):
            b = min(a + g, a1)
            e = ref_mean(plan["energy_nodes"], a, b)
            zone = (s["type"] == "intro" and a < a0 + 16) or (s["type"] == "outro" and a >= a1 - 16)
            e = min(e, 0.5) if zone else e
            out[a] = (b - a, ref_elements(s["type"], prev, e, a, a0, a1, plan["settings"]))
    return out


def random_plan(r):
    """A generated plan with random genre, length, bpm, settings and sometimes drawn nodes."""
    for _ in range(50):
        settings = {k: r.choice(v) for k, v in ALLOWED.items() if r.random() < 0.6}
        req = PlanRequest(r.choice(["techno", "trance"]), r.choice([100, 136, 140, 174]),
                          target_bars=8 * r.randrange(12, 41), settings=settings)
        drawn = None
        if r.random() < 0.5:
            pos = sorted(r.randrange(1, req.target_bars) for _ in range(r.randrange(1, 6)))
            drawn = [{"pos": p, "value": r.choice([r.random(), 0.0, 1.0, 0.65, 0.4])}
                     for p in dict.fromkeys(pos)]
        res = generate_plan(req, drawn_nodes=drawn)
        if res.ok:
            return res.plan
    raise AssertionError("no feasible random plan")


def test_p6_random_plans_follow_the_reference_and_the_grid():
    r = kp.rng(2210)
    for _ in range(120):
        plan = random_plan(r)
        grid = plan["settings"]["change_grid"]
        tl = derive_timeline(plan)
        ref = ref_cells(plan)
        assert {c.start: (c.length, set(c.elements)) for c in tl.cells} == ref
        # the plan is the same for every grid: only the cells change
        base = copy.deepcopy(plan)
        base["settings"]["change_grid"] = 8
        assert base["sections"] == plan["sections"] and base["energy_nodes"] == plan["energy_nodes"]
        # every switch lies on a change point counted from the section start
        points = {s["start_bar"] - 1 + k for s in plan["sections"]
                  for k in range(0, s["length_bars"], grid)}
        cells = tl.cells
        for a, b in zip(cells, cells[1:], strict=False):
            if a.elements != b.elements:
                assert b.start in points
        assert {c.start for c in cells} == points


def test_p7_random_plans_events_sit_on_the_grids():
    r = kp.rng(2211)
    for _ in range(120):
        plan = random_plan(r)
        st = plan["settings"]
        events = derive_timeline(plan).events
        starts = {s["start_bar"] - 1: s for s in plan["sections"]}
        fills = [e for e in events if e.kind == "fill"]
        if st["fills"] == "off":
            assert not fills
        for e in fills:
            end_bar = (e.start_beat + e.length_beats) // 4
            assert e.length_beats == 4 and e.start_beat % 4 == 0
            owner = plan["sections"][e.section]
            assert (end_bar - (owner["start_bar"] - 1)) % 8 == 0  # on the 8-bar phrase grid
            if st["fills"] == "section_change":
                assert end_bar in starts  # at a section start, i.e. a change point
        assert all(a.variant != b.variant for a, b in zip(fills, fills[1:], strict=False))
        gaps = [e for e in events if e.kind == "pre_drop_gap"]
        drops = [(s["start_bar"] - 1) * 4 for s in plan["sections"] if s["type"] == "drop"]
        want = drops if st["pre_drop_gap"] else []
        assert [g.start_beat + g.length_beats for g in gaps] == want
        assert all(g.length_beats == st["pre_drop_gap"] for g in gaps)
        # fills and gaps do not depend on change_grid
        other = copy.deepcopy(plan)
        other["settings"]["change_grid"] = 1 + (st["change_grid"] % 64)
        assert derive_timeline(other).events == events


# --- P8: at most one element per 8-bar boundary in a default intro and outro -------------------

@pytest.mark.parametrize("second_drop", ["stronger", "equal", "ask"])
@pytest.mark.parametrize("outro_length", [16, 32, 64])
@pytest.mark.parametrize("intro_length", [16, 32, 64])
@pytest.mark.parametrize("genre", ["techno", "trance"])
def test_p8_default_intro_and_outro_change_one_element_per_boundary(
        genre, intro_length, outro_length, second_drop):
    settings = {"intro_length": intro_length, "outro_length": outro_length,
                "second_drop": second_drop}
    plan = next(res.plan for bars in range(160, 400, 8)
                if (res := generate_plan(PlanRequest(genre, 140, target_bars=bars,
                                                     settings=settings))).ok)
    cells = derive_timeline(plan).cells
    for kind in ("intro", "outro"):
        mine = [c for c in cells if c.type == kind]
        assert len(mine) >= 2
        for a, b in zip(mine, mine[1:], strict=False):
            # kick and bass are not counted (bass is set by intro_outro_bass, note 5.1)
            changed = (a.elements ^ b.elements) - {"kick", "bass"}
            assert len(changed) <= 1, (kind, a.start, changed)


# --- V5: raising energy inside a family never removes an element -------------------------------

def flat_plan(base, energies):
    secs = base["sections"]
    nodes = [{"pos": 0, "value": energies[0], "drawn": True}]
    for i in range(1, len(secs)):
        p = secs[i]["start_bar"] - 1
        nodes += [{"pos": p, "value": energies[i - 1], "drawn": True},
                  {"pos": p, "value": energies[i], "drawn": True}]
    nodes.append({"pos": base["total_bars"], "value": energies[-1], "drawn": True})
    plan = {**base, "energy_nodes": nodes}
    assert ap.plan_problems(plan) == []
    return plan


def test_v5_raising_energy_never_removes_an_element():
    r = kp.rng(2212)
    for _ in range(150):
        base = random_plan(r)
        n = len(base["sections"])
        low = [r.choice([r.random(), 0.0, 0.2, 0.3, 0.4, 0.5, 0.55, 0.65, 0.7, 0.8, 0.9])
               for _ in range(n)]
        high = [min(1.0, v + r.choice([0.0, 0.01, 0.1, 0.5])) for v in low]
        a = derive_timeline(flat_plan(base, low)).cells
        b = derive_timeline(flat_plan(base, high)).cells
        assert [c.start for c in a] == [c.start for c in b]
        for x, y in zip(a, b, strict=True):
            assert x.elements <= y.elements, (x.type, x.start)
    # and on a grid of equal energy for the whole track, from 0 to 1 in steps of 0.01
    base = t2()
    previous = None
    for k in range(101):
        cells = derive_timeline(flat_plan(base, [k / 100] * len(base["sections"]))).cells
        if previous:
            assert all(x.elements <= y.elements for x, y in zip(previous, cells, strict=True))
        previous = cells
