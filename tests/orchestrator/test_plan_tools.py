"""#222 (G5): the ``plan_arrangement`` tool, its refusals, the plan table and the CLI.

CI only: fake model, no Claude, no Live. Nothing here is a Live test.
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pytest
from orch_helpers import (  # noqa: F401 - *_fixture are pytest fixtures (see orch_helpers)
    Events,
    ScriptedModel,
    clock_fixture,
    events_fixture,
    make_guard_fixture,
)
from test_contracts import STRICT_TOOLS, TOOL_SCHEMAS, load, optional_fields, strict_subset_problems

from orchestrator import plan_cli
from orchestrator.arrangement_generator import generate_plan
from orchestrator.arrangement_layout import PlanRequest
from orchestrator.arrangement_plan import plan_problems
from orchestrator.fake_model import FakeModel
from orchestrator.loop import Orchestrator
from orchestrator.model_client import ToolResultMessage
from orchestrator.plan_tools import (
    REFUSALS,
    PlanSession,
    build_request,
    refusal_text,
    tool_input_schema,
)
from orchestrator.tools import Toolbox, validation_errors

SRC = Path(__file__).resolve().parents[2] / "src" / "orchestrator"
USAGE = {"output_tokens": 10, "input_tokens": 100, "cost_usd": 0.01}
GOOD = {"genre": "techno", "bpm": 140, "length": 6, "length_unit": "minutes",
        "setting_changes": []}


class Approver:
    def __init__(self) -> None:
        self.asked = 0

    def confirm(self, tool, arguments, plan) -> bool:
        self.asked += 1
        return True


def chat(guard, events, session, turns, text="mach einen Plan"):
    """One chat request against a fake model; returns (outcome, model, approver)."""
    fake = FakeModel([{**t, "usage": USAGE} for t in turns])
    model = ScriptedModel(lambda i, request: fake.complete(request), events)
    approver = Approver()
    orch = Orchestrator(guard, model, Toolbox(session.tools()), profile="p", approver=approver,
                        context=session.context)
    return orch.handle(text), model, approver


def tool_results(model):
    return [m.results[0] for r in model.requests for m in r.messages
            if isinstance(m, ToolResultMessage)]


# --- schema ----------------------------------------------------------------------------------


def test_schema_is_strict_and_adds_no_optional_parameter():
    schema = tool_input_schema()
    assert strict_subset_problems(schema, allow_root_metadata=False) == []
    assert optional_fields(schema) == 0
    # budget: the three kick tools use exactly 24 of 24; this tool must keep it there
    kick_total = sum(optional_fields(load(TOOL_SCHEMAS[t])) for t in STRICT_TOOLS)
    assert kick_total + optional_fields(schema) == 24


def test_schema_accepts_the_good_call_and_refuses_the_rest():
    tool = PlanSession().tools()[0]
    assert validation_errors(tool, GOOD) == []
    assert validation_errors(tool, {**GOOD, "setting_changes": [
        {"key": "intro_length", "value": 16}, {"key": "fills", "value": "off"}]}) == []
    assert validation_errors(tool, {k: v for k, v in GOOD.items() if k != "bpm"})
    assert validation_errors(tool, {**GOOD, "genre": "house"})
    assert validation_errors(tool, {**GOOD, "extra": 1})
    assert validation_errors(tool, {**GOOD, "setting_changes": [{"key": "tempo", "value": 1}]})


# --- chat request -> plan --------------------------------------------------------------------


def test_chat_request_becomes_a_plan_without_asking_the_user(make_guard, events):
    session = PlanSession()
    args = {**GOOD, "length_unit": "bars", "length": 200,
            "setting_changes": [{"key": "breakdown_rumble", "value": "on"}]}
    out, model, approver = chat(make_guard(), events, session, [
        {"tool_calls": [{"id": "c1", "name": "plan_arrangement", "arguments": args}]},
        {"text": "Plan steht."},
    ])
    assert out.success and out.reply == "Plan steht."
    assert approver.asked == 0  # routine
    result = tool_results(model)[0]
    assert not result.is_error
    content = result.content
    assert content["plan_id"] == "plan-1" and content["total_bars"] == 200
    assert content["settings"]["breakdown_rumble"] == "on"
    assert [s["type"] for s in content["sections"]][0] == "intro"
    assert content["sections"][-1]["type"] == "outro"
    assert "energy_nodes" not in content and "timeline" not in content
    assert "nothing was written" in content["note"]
    stored = session.plan("plan-1")
    assert plan_problems(stored) == [] and stored["bpm"] == 140
    # a later request sees the plan id in the session context
    assert "plan-1" in session.context() and "200 bars" in session.context()
    # the tool declared and wrote no file and no Live change
    assert out.usage["files_written"] == 0 and out.usage["live_writes"] == 0


def test_minutes_are_converted_locally_and_the_result_carries_the_warning(make_guard, events):
    session = PlanSession()
    out, model, _ = chat(make_guard(), events, session, [
        {"tool_calls": [{"id": "c1", "name": "plan_arrangement",
                         "arguments": {**GOOD, "length": 8}}]},  # 8 min at 140 = 280 bars
        {"text": "ok"},
    ])
    assert out.success
    content = tool_results(model)[0].content
    assert content["total_bars"] == 280
    assert [w["code"] for w in content["warnings"]] == ["duration_window"]


# --- refusals ----------------------------------------------------------------------------------

REQ = PlanRequest("techno", 140, target_bars=200)
SECTIONS = [{"type": "intro", "start_bar": 1, "length_bars": 32},
            {"type": "drop", "start_bar": 33, "length_bars": 32},
            {"type": "outro", "start_bar": 65, "length_bars": 16}]
G1_G2_ERRORS = {  # code -> a request the generator really refuses with it
    "bad_genre": lambda: generate_plan(PlanRequest("house", 140, target_bars=200)),
    "bad_bpm": lambda: generate_plan(PlanRequest("techno", 5, target_bars=200)),
    "bad_setting": lambda: generate_plan(PlanRequest("techno", 140, target_bars=200,
                                                     settings={"intro_length": 7})),
    "length_both_or_none": lambda: generate_plan(PlanRequest("techno", 140)),
    "length_not_multiple_of_8": lambda: generate_plan(PlanRequest("techno", 140,
                                                                  target_bars=201)),
    "length_out_of_range": lambda: generate_plan(PlanRequest("techno", 140, target_bars=2000)),
    "length_infeasible": lambda: generate_plan(PlanRequest("techno", 140, target_bars=64)),
    "length_with_sections": lambda: generate_plan(REQ, sections=SECTIONS),
    "sections_invalid": lambda: generate_plan(
        PlanRequest("techno", 140), sections=[{"type": "drop", "start_bar": 1,
                                                "length_bars": 32}]),
    "drawn_node_invalid": lambda: generate_plan(REQ, drawn_nodes=[{"pos": 0, "value": 2}]),
    "outro_slot_too_short": lambda: generate_plan(
        PlanRequest("techno", 140), sections=SECTIONS,
        drawn_nodes=[{"pos": 64, "value": 1.0}]),
}


def codes_in_source() -> set[str]:
    found = set()
    for name in ("arrangement_layout.py", "arrangement_generator.py"):
        found |= set(re.findall(r'_err\(\s*"([a-z_0-9]+)"', (SRC / name).read_text("utf-8")))
    return found


def test_every_generator_error_code_has_a_refusal_text():
    """A new code in G1/G2 without a text here turns this red."""
    assert codes_in_source() == set(G1_G2_ERRORS) == set(REFUSALS)


@pytest.mark.parametrize("code", sorted(G1_G2_ERRORS))
def test_each_error_code_gets_a_model_facing_text(code):
    result = G1_G2_ERRORS[code]()
    assert [e["code"] for e in result.errors] == [code]
    text = refusal_text(result.errors)
    assert text.startswith(f"{code}: ") and text.endswith("Nothing was planned.")


def test_infeasible_text_names_the_default_minimums_and_the_nearest_lengths():
    text = refusal_text(G1_G2_ERRORS["length_infeasible"]().errors)
    assert "above 200 bars" in text and "at least 200 bars" in text and "192" in text
    assert "setting_changes" in text


@pytest.mark.parametrize("args, code", [
    ({"length": 64, "length_unit": "bars"}, "length_infeasible"),
    ({"length": 201, "length_unit": "bars"}, "length_not_multiple_of_8"),
    ({"length": 2000, "length_unit": "bars"}, "length_out_of_range"),
    ({"bpm": 5}, "bad_bpm"),
    ({"setting_changes": [{"key": "intro_length", "value": 7}]}, "bad_setting"),
    ({"setting_changes": [{"key": "second_drop", "value": "ask"}]}, "second_drop_ask"),
])
def test_refusals_reach_the_model_as_errors_and_store_no_plan(make_guard, events, args, code):
    session = PlanSession()
    out, model, _ = chat(make_guard(), events, session, [
        {"tool_calls": [{"id": "c1", "name": "plan_arrangement", "arguments": {**GOOD, **args}}]},
        {"text": "Das geht nicht."},
    ])
    # a refused tool call leaves its item open: the request is honestly not a success
    assert not out.success and out.open == ("Werkzeug plan_arrangement",)
    result = tool_results(model)[0]
    assert result.is_error and result.content["error"] == "tool_error"
    assert result.content["codes"] == [code]
    assert session.plans == {} and session.context() == ""
    assert "Nothing was planned" in result.content["message"]


def test_whole_float_setting_values_work_and_fractions_are_refused():
    session = PlanSession()
    tool = session.tools()[0]
    ok = {**GOOD, "length": 200, "length_unit": "bars",
          "setting_changes": [{"key": "intro_length", "value": 16.0}]}
    assert validation_errors(tool, ok) == []  # the schema takes 16.0 as an integer
    assert tool.handler(ok).content["settings"]["intro_length"] == 16
    bad = {**ok, "setting_changes": [{"key": "intro_length", "value": 16.5}]}
    assert validation_errors(tool, bad)  # the schema already refuses a fraction
    request = build_request("techno", 140, 200, "bars", [("intro_length", 16.5)])
    assert [e["code"] for e in generate_plan(request).errors] == ["bad_setting"]


def test_second_drop_ask_text_tells_the_model_to_ask_the_user(make_guard, events):
    out, model, _ = chat(make_guard(), events, PlanSession(), [
        {"tool_calls": [{"id": "c1", "name": "plan_arrangement", "arguments": {
            **GOOD, "setting_changes": [{"key": "second_drop", "value": "ask"}]}}]},
        {"text": "Soll der zweite Drop staerker sein?"},
    ])
    message = tool_results(model)[0].content["message"]
    assert "ask the user" in message and "stronger" in message and "equal" in message


def test_description_states_the_outro_and_length_limits():
    text = PlanSession().tools()[0].description
    assert "outro_length setting never makes it shorter" in text
    assert "64 bars" in text and "200 bars" in text and "192 bars" in text


# --- CLI ---------------------------------------------------------------------------------------


def test_cli_writes_a_valid_plan_and_never_overwrites(tmp_path):
    target = tmp_path / "plan.json"
    out = io.StringIO()
    argv = ["--genre", "techno", "--bpm", "140", "--bars", "200", "--set", "fills=every_8",
            "--out", str(target)]
    assert plan_cli.main(argv, out=out) == 0
    plan = json.loads(target.read_text("utf-8"))
    assert plan_problems(plan) == [] and plan["settings"]["fills"] == "every_8"
    assert "Wrote" in out.getvalue()
    before = target.read_bytes()
    assert plan_cli.main(argv, out=io.StringIO()) == 2
    assert target.read_bytes() == before


def test_cli_prints_the_refusal_text_and_writes_nothing(tmp_path):
    target = tmp_path / "plan.json"
    out = io.StringIO()
    code = plan_cli.main(["--genre", "techno", "--bpm", "140", "--bars", "64",
                          "--out", str(target)], out=out)
    assert code == 1 and not target.exists()
    assert "length_infeasible" in out.getvalue()
