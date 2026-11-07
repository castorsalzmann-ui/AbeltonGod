"""Planner page model (#139, D-024): inputs reach the planner unchanged, drawn nodes act as the
planner defines, the node editing never builds a list the planner refuses, and the export
writes a plan that the contract checker accepts. No Qt.

References: plans are compared with ``generate_plan`` called here on a ``PlanRequest`` written
in the test (the planner is the definition; the page must not compute plan values itself),
expected numbers are written in the test, and the exported file is checked with the schema
file directly (jsonschema) next to the repo's one checker ``plan_problems``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from support.kick_params import rng, seed

from gui_core import planner
from gui_core.planner import ExportError, PlannerModel, export_plan, section_rows
from orchestrator.arrangement_generator import generate_plan
from orchestrator.arrangement_layout import SETTING_ALLOWED, SETTING_DEFAULTS, PlanRequest
from orchestrator.arrangement_plan import plan_problems

SCHEMA = Path(__file__).resolve().parents[2] / "contracts" / "arrangement-plan.schema.json"


def _req(**kw) -> PlanRequest:
    base = {"genre": "techno", "bpm": 140, "target_minutes": 6,
            "settings": dict(SETTING_DEFAULTS)}
    base.update(kw)
    return PlanRequest(**base)


def test_defaults_give_the_planners_plan_for_six_minutes_techno_at_140():
    m = PlannerModel()
    assert m.state.ok, m.state.errors
    assert m.state.total_bars == 208  # 6 min * 140 / 4 = 210 bars -> nearest multiple of 8
    assert m.state.plan == generate_plan(_req()).plan
    assert m.state.timeline is not None and m.state.timeline.cells


def test_a_drawn_node_acts_as_the_planner_defines():
    m = PlannerModel()
    default = m.state.plan
    assert m.add_node(100, 0.8) == 0
    m.compute()
    plan = m.state.plan
    assert plan == generate_plan(_req(), drawn_nodes=[{"pos": 100, "value": 0.8}]).plan
    assert plan != default
    at_100 = [n for n in plan["energy_nodes"] if n["pos"] == 100]
    assert at_100 == [{"pos": 100, "value": 0.8, "drawn": True}]  # defaults there dropped
    cell = next(c for c in m.state.timeline.cells if c.start <= 100 < c.start + c.length)
    old = PlannerModel().state.timeline.cells
    old_cell = next(c for c in old if c.start == cell.start)
    assert cell.energy != old_cell.energy  # the element timeline follows the drawn node


def test_a_drawn_node_on_a_section_start_replaces_the_default_step_pair():
    m = PlannerModel()
    groove = next(s for s in m.state.plan["sections"] if s["type"] == "groove")
    pos = groove["start_bar"] - 1
    assert len([n for n in m.state.plan["energy_nodes"] if n["pos"] == pos]) == 2
    m.add_node(pos, 0.5)
    m.compute()
    assert [n for n in m.state.plan["energy_nodes"] if n["pos"] == pos] == [
        {"pos": pos, "value": 0.5, "drawn": True}]


def test_a_second_node_on_one_bar_is_a_step_and_a_third_is_refused():
    m = PlannerModel()
    assert m.add_node(100, 0.3) == 0
    assert m.add_node(100, 0.9) == 1  # leaving value
    assert m.add_node(100, 0.5) is None
    assert m.add_node(0, 0.3) == 0
    assert m.add_node(0, 0.4) is None  # no pair at the track edge
    m.compute()
    drawn = [n for n in m.state.plan["energy_nodes"] if n["drawn"]]
    assert drawn == [{"pos": 0, "value": 0.3, "drawn": True},
                     {"pos": 100, "value": 0.3, "drawn": True},
                     {"pos": 100, "value": 0.9, "drawn": True}]


def test_move_keeps_the_order_and_clamps_value_and_pos():
    m = PlannerModel()
    m.add_node(50, 0.5)
    m.add_node(100, 0.5)
    assert m.move_node(0, 120, 1.7) == (100, 1.0)  # not past its neighbour; value capped
    assert m.move_node(1, 999, -1) == (208, 0.0)
    assert m.move_node(0, -5, 0.333) == (0, 0.33)


@pytest.mark.parametrize("base", [11, 12, 13, 14, 15])
def test_random_editing_never_builds_drawn_nodes_the_planner_refuses(base):
    """Seeded random add / move / remove sequences over the whole track and value range: the
    planner never answers ``drawn_node_invalid`` (the editing keeps its input rules). Other
    refusals (``outro_slot_too_short``) are planner answers about the energy, not shape."""
    r = rng(base)
    m = PlannerModel()
    total = m.state.total_bars
    for _ in range(60):
        op = r.random()
        if op < 0.5 or not m.drawn:
            m.add_node(r.choice([0, total, r.randrange(0, total + 1)]), r.random())
        elif op < 0.85:
            m.move_node(r.randrange(len(m.drawn)), r.randrange(-3, total + 4), r.uniform(-.2, 1.2))
        else:
            m.remove_node(r.randrange(len(m.drawn)))
        m.compute()
        codes = generate_plan(_req(), drawn_nodes=[dict(n) for n in m.drawn]).errors
        assert not [e for e in codes if e["code"] == "drawn_node_invalid"], (seed(base), m.drawn)
        if m.state.ok:
            assert plan_problems(m.state.plan) == []


def test_planner_refusals_of_drawn_nodes_have_german_texts():
    """The layout always leaves the outro 64 bars (the walk from a full drop), so the
    ``outro_slot_too_short`` refusal cannot be reached from this page; its text is checked
    on the planner's error shape."""
    text = planner.error_text({"code": "outro_slot_too_short",
                               "detail": {"required": 64, "slot": 32}})
    assert "64 Takte" in text and "32" in text and "Outro" in text
    text = planner.error_text({"code": "drawn_node_invalid",
                               "detail": {"index": 2, "reason": "pos decreases"}})
    assert text.startswith("Gezeichneter Punkt 2 ungültig")


@pytest.mark.parametrize("key", sorted(SETTING_ALLOWED))
def test_every_setting_value_reaches_the_plan(key):
    values = SETTING_ALLOWED[key]
    if key == "change_grid":
        values = (1, 7, 8, 64)
    for value in values:
        m = PlannerModel()
        m.length_text, m.unit = "256", "bars"
        m.set_setting(key, value)
        m.compute()
        settings = {**SETTING_DEFAULTS, key: value}
        expected = generate_plan(_req(target_minutes=None, target_bars=256, settings=settings))
        assert m.state.plan == expected.plan
        if m.state.ok:
            assert m.state.plan["settings"][key] == value
        else:
            assert m.state.errors and not any(e.startswith(("length_", "bad_"))
                                              for e in m.state.errors)


def test_unknown_setting_value_is_refused():
    with pytest.raises(ValueError):
        PlannerModel().set_setting("fills", "always")


@pytest.mark.parametrize("bpm,length,unit,needle", [
    ("x", "6", "minutes", "BPM ist keine Zahl"),
    ("140", "", "minutes", "Länge ist keine Zahl"),
    ("140", "184", "bars", "Nächste mögliche Längen: 200 Takte"),  # techno from 200 bars
    ("140", "203", "bars", "Vielfaches von 8"),
    ("1000", "256", "bars", "BPM muss eine Zahl von 20 bis 999"),
    ("140", "8", "bars", "außerhalb von 32-1024"),
])
def test_bad_inputs_give_german_texts_and_no_plan(bpm, length, unit, needle):
    m = PlannerModel()
    m.bpm_text, m.length_text, m.unit = bpm, length, unit
    m.compute()
    assert m.state.plan is None
    assert any(needle in e for e in m.state.errors), m.state.errors


def test_section_rows_show_the_planners_energies():
    rows = section_rows(PlannerModel().state)
    assert rows[0] == ("Intro", "1-32", 32, "0.30 → 0.45")  # intro steps 0.30 .. 0.45
    assert [r[0] for r in rows][-1] == "Outro"
    assert sum(r[2] for r in rows) == 208


# --- export ----------------------------------------------------------------------------------

def test_export_writes_a_plan_the_contract_accepts_and_never_overwrites(tmp_path):
    m = PlannerModel()
    m.add_node(100, 0.8)
    m.compute()
    folder = planner.plans_dir(tmp_path)
    first = export_plan(m.state.plan, folder, m.genre)
    second = export_plan(m.state.plan, folder, m.genre)
    assert first == tmp_path / "Plans" / "arrangement_techno_140bpm_208bars.json"
    assert second.name == "arrangement_techno_140bpm_208bars_002.json"
    data = json.loads(first.read_text(encoding="utf-8"))
    validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    assert list(validator.iter_errors(data)) == []
    assert plan_problems(data) == []
    assert data == m.state.plan and data["schema_version"] == "0.1"
    assert {"pos": 100, "value": 0.8, "drawn": True} in data["energy_nodes"]
    assert second.read_bytes() == first.read_bytes()


def test_export_refuses_a_plan_the_checker_rejects_and_writes_nothing(tmp_path):
    plan = PlannerModel().state.plan
    plan["sections"][0]["type"] = "drop"  # first section must be the intro
    with pytest.raises(ExportError, match="first_not_intro"):
        export_plan(plan, tmp_path / "Plans", "techno")
    assert not (tmp_path / "Plans").exists()


def test_a_failed_write_leaves_no_half_file(tmp_path, monkeypatch):
    plan = PlannerModel().state.plan
    real_open = Path.open

    class Full:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.handle.close()

        def write(self, text):
            self.handle.write(text[:10])
            raise OSError(28, "No space left on device")

    def fake_open(self, mode="r", *a, **kw):
        handle = real_open(self, mode, *a, **kw)
        return Full(handle) if mode == "x" else handle

    monkeypatch.setattr(Path, "open", fake_open)
    with pytest.raises(OSError, match="No space"):
        export_plan(plan, tmp_path, "techno")
    assert list(tmp_path.iterdir()) == []
