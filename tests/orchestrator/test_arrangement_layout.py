"""Plan generator G1 (#212): layout and length fit.

The reference for the fit is a brute force written here: it walks every combination of allowed
lengths of a hand-written skeleton (planner note T2 / T3, INTERFACES `sections[]` lengths) and
does not call the fitter's table. The outro of 64 bars after a full drop is a format fact
(INTERFACES "Outro entry"), written as a number.
"""

import itertools
import json
from pathlib import Path

import pytest

from orchestrator.arrangement_layout import PlanRequest, plan_layout
from orchestrator.arrangement_plan import plan_problems

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "arrangement_plan"

ALLOWED = {"groove": (16, 32, 48, 64), "break": (8, 16), "build": (8, 16, 32),
           "drop": (16, 32, 64)}
# (type, default length); None = fixed by a setting
SKELETON = {
    "techno": [("intro", None), ("groove", 32), ("break", 8), ("build", 8), ("drop", 32),
               ("breakdown", None), ("build", 16), ("drop", 32), ("outro", None)],
    "trance": [("intro", None), ("groove", 32), ("build", 16), ("drop", 32),
               ("breakdown", None), ("build", 16), ("drop", 32), ("outro", None)],
}
SETTING_SETS = [
    {}, {"intro_length": 16}, {"intro_length": 64, "breakdown_length": 16},
    {"breakdown_length": 64}, {"breakdown_count": 2}, {"breakdown_count": 2, "intro_length": 16},
    {"outro_length": 16}, {"outro_length": 64},
]


def reference(genre, settings):
    """total -> lengths of the best combination (closest to the defaults, then smallest)."""
    s = {"intro_length": 32, "breakdown_length": 32, "breakdown_count": 1} | settings
    seq = list(SKELETON[genre])
    if s["breakdown_count"] == 2:  # user decision: breakdown, build, drop appended after drop 2
        seq[-1:-1] = [("breakdown", None), ("build", 16), ("drop", 32)]
    fixed = {"intro": s["intro_length"], "breakdown": s["breakdown_length"], "outro": 64}
    best = {}
    for combo in itertools.product(*(
            ALLOWED[t] if t in ALLOWED else (fixed[t],) for t, _ in seq)):
        dev = sum(abs(n - d) for n, (_, d) in zip(combo, seq, strict=True) if d is not None)
        total = sum(combo)
        if total not in best or (dev, combo) < best[total][0]:
            best[total] = ((dev, combo), combo)
    return {t: v[1] for t, v in best.items()}, [t for t, _ in seq]


def lengths(result):
    return tuple(s["length_bars"] for s in result.sections)


def request(genre, bars, settings=None):
    return PlanRequest(genre=genre, bpm=140, target_bars=bars, settings=settings)


@pytest.mark.parametrize("genre", ["techno", "trance"])
@pytest.mark.parametrize("settings", SETTING_SETS, ids=json.dumps)
def test_fit_matches_brute_force_for_every_length(genre, settings):
    ref, types = reference(genre, settings)
    feasible = sorted(ref)
    assert feasible, "reference found no layout"
    for bars in range(32, 1025, 8):
        res = plan_layout(request(genre, bars, settings))
        if bars in ref:
            assert res.ok, (bars, res.errors)
            assert lengths(res) == ref[bars], bars
            assert [s["type"] for s in res.sections] == types
            assert res.total_bars == bars
            # the format's own checker accepts these sections (flat energy line: any B2/B3 holds)
            plan = {
                "schema_version": "0.1", "bpm": 140, "time_signature": "4/4", "phrase_bars": 8,
                "total_bars": bars, "sections": res.sections,
                "energy_nodes": [{"pos": 0, "value": 0.5, "drawn": False},
                                 {"pos": bars, "value": 0.5, "drawn": False}],
                "settings": res.settings}
            assert plan_problems(plan) == [], bars
        else:
            assert [e["code"] for e in res.errors] == ["length_infeasible"], bars
            near = res.errors[0]["detail"]["nearest"]
            below = max((t for t in feasible if t < bars), default=None)
            above = min((t for t in feasible if t > bars), default=None)
            assert near == {"below": below, "above": above}, bars
            for n in near.values():
                if n is not None:
                    assert plan_layout(request(genre, n, settings)).ok


def test_default_256_bars_is_template_t2_and_t3():
    for genre, name in (("techno", "T2"), ("trance", "T3")):
        plan = json.loads((FIXTURES / f"{name}.json").read_text())
        res = plan_layout(request(genre, 256))
        assert res.sections == plan["sections"]
        assert res.settings == plan["settings"]


def test_outro_is_64_after_a_full_drop_and_reported():
    res = plan_layout(request("techno", 256))
    assert res.sections[-1]["length_bars"] == 64
    assert [a["code"] for a in res.adjustments] == ["outro_lengthened"]


def test_minutes_become_bars_and_ties_round_up():
    # bars = minutes * 60 * bpm / 240 = minutes * bpm / 4, to the nearest multiple of 8
    # (minutes, bpm, expected bars); 64 and 144 are shorter than the default layout allows, so
    # the converted value shows up as target_bars of the length_infeasible error
    for minutes, bpm, bars in [(6, 140, 208),   # 210 bars -> 208
                               (2, 120, 64),    # 60 bars = 7.5 phrases, exact tie -> up
                               (5, 128, 160), (6.5, 128, 208), (8, 140, 280)]:
        res = plan_layout(PlanRequest("techno", bpm, target_minutes=minutes))
        got = res.total_bars if res.ok else res.errors[0]["detail"]["target_bars"]
        assert got == bars, (minutes, bpm)
    short = plan_layout(PlanRequest("techno", 140, target_minutes=0.1))  # 3.5 bars -> 0
    assert codes(short) == ["length_out_of_range"]


def test_duration_window_is_only_a_warning():
    long = plan_layout(request("techno", 256))  # 7.31 min at 140
    assert long.ok and [w["code"] for w in long.warnings] == ["duration_window"]
    ok = plan_layout(request("techno", 224))  # 6.4 min
    assert ok.ok and ok.warnings == []


def test_same_request_gives_same_json():
    for genre in ("techno", "trance"):
        for bars in (200, 256, 320, 999):
            a = plan_layout(request(genre, bars, {"breakdown_count": 2}))
            b = plan_layout(request(genre, bars, {"breakdown_count": 2}))
            assert json.dumps(a, default=vars) == json.dumps(b, default=vars)


# --- error table 2.3, one test per code ----------------------------------------------------------

def codes(res):
    return [e["code"] for e in res.errors]


def test_bad_genre():
    res = plan_layout(request("house", 256))
    assert codes(res) == ["bad_genre"] and res.sections == []
    assert res.errors[0]["detail"]["allowed"] == ["techno", "trance"]


@pytest.mark.parametrize("bpm", [19, 1000, "140", None, float("nan")])
def test_bad_bpm(bpm):
    assert codes(plan_layout(PlanRequest("techno", bpm, target_bars=256))) == ["bad_bpm"]
    assert codes(plan_layout(PlanRequest("techno", bpm, target_minutes=6))) == ["bad_bpm"]


@pytest.mark.parametrize("settings", [{"nope": 1}, {"intro_length": 20}, {"fills": "always"},
                                      {"change_grid": 65}, {"breakdown_count": True}])
def test_bad_setting(settings):
    res = plan_layout(request("techno", 256, settings))
    assert codes(res) == ["bad_setting"]
    assert "field" in res.errors[0]["detail"]


def test_length_both_or_none():
    assert codes(plan_layout(PlanRequest("techno", 140))) == ["length_both_or_none"]
    both = PlanRequest("techno", 140, target_bars=256, target_minutes=6)
    assert codes(plan_layout(both)) == ["length_both_or_none"]


def test_length_not_multiple_of_8():
    res = plan_layout(request("techno", 250))
    assert codes(res) == ["length_not_multiple_of_8"]
    assert res.errors[0]["detail"]["nearest"] == [248, 256]


@pytest.mark.parametrize("bars,nearest", [(24, [32]), (1032, [1024]), (0, [32])])
def test_length_out_of_range(bars, nearest):
    res = plan_layout(request("techno", bars))
    assert codes(res) == ["length_out_of_range"]
    assert res.errors[0]["detail"]["nearest"] == nearest


def test_length_infeasible_gives_nearest_that_succeed():
    res = plan_layout(request("techno", 64))  # default settings need at least 200 bars
    assert codes(res) == ["length_infeasible"]
    near = res.errors[0]["detail"]["nearest"]
    assert near == {"below": None, "above": 200}
    assert plan_layout(request("techno", 200)).ok
