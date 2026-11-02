"""#258 (G7): the ``generate_sample`` tool, category clap.

CI only: fake German model, fake AbletonOSC for the import check. No Claude call, no Live.
Expected values are written here or measured independently (hashlib over the file bytes, the
contract file read directly), not taken from the code under test.
"""

from __future__ import annotations

import ast
import hashlib
import json
import random
from pathlib import Path

from kick_helpers import RecordingApprover as Approver
from kick_helpers import (  # noqa: F401 - fake_fixture is a pytest fixture
    fake_fixture,
    make_session,
    writes_sent,
)
from orch_helpers import (  # noqa: F401 - *_fixture are pytest fixtures (see orch_helpers)
    ScriptedModel,
    clock_fixture,
    events_fixture,
    make_guard_fixture,
)
from test_contracts import STRICT_TOOLS, TOOL_SCHEMAS, load, optional_fields, strict_subset_problems
from test_guard_wiring import SRC, violations

from orchestrator.fake_model import FakeModel
from orchestrator.loop import Orchestrator
from orchestrator.model_client import ToolCall, ToolResultMessage
from orchestrator.sample_tools import SampleTools, check_adjust, tool_input_schema
from orchestrator.tools import Toolbox, validation_errors

CONTRACT = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts" / "clap-params.schema.json")
    .read_text("utf-8"))["properties"]
ADJUSTABLE = {k: v for k, v in CONTRACT.items()
              if k not in ("schema_version", "seed", "variants", "preset")}
USAGE = {"output_tokens": 10, "input_tokens": 100, "cost_usd": 0.01}
GOOD = {"category": "clap", "preset": "short", "prompt": "", "seed": 7, "variants": 1,
        "adjust": []}
# Fast and small: a short clap keeps the tests quick.
FAST = [{"key": "length_ms", "value": 200}]


def boxes(tmp_path, fake=None):
    session = make_session(tmp_path, fake)
    return session, Toolbox(session.tools() + SampleTools(session).tools(),
                            capability_gate=session.gate())


def run(guard, box, name, args, approver=None):
    with guard.request("p") as req:
        return box.run(req, ToolCall("c1", name, args), approver)


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# --- schema ----------------------------------------------------------------------------------


def test_schema_is_strict_with_no_optional_parameter_and_no_ranges():
    schema = tool_input_schema()
    assert strict_subset_problems(schema, allow_root_metadata=False) == []
    assert optional_fields(schema) == 0
    assert schema["additionalProperties"] is False
    assert schema["properties"]["adjust"]["items"]["additionalProperties"] is False
    assert "minimum" not in json.dumps(schema) and "maximum" not in json.dumps(schema)


def test_registered_tools_stay_within_24_optional_parameters(tmp_path):
    """The strict budget (kick 23 + import_sample 1 = 24) must not grow by registering this
    tool. The kick tools are counted from their strict contracts, the new tool from what is
    really registered."""
    _, box = boxes(tmp_path)
    mine = next(s for s in box.specs() if s.name == "generate_sample")
    strict_total = sum(optional_fields(load(TOOL_SCHEMAS[t])) for t in STRICT_TOOLS)
    assert strict_total + optional_fields(mine.input_schema) <= 24


# --- adjust validation: whole contract range -------------------------------------------------


def test_every_adjustable_field_accepts_its_whole_range_and_rejects_beyond():
    rng = random.Random(258)
    for key, spec in ADJUSTABLE.items():
        if "enum" in spec:
            for v in spec["enum"]:
                assert check_adjust([{"key": key, "value": v}]) == ({key: v}, [])
            assert check_adjust([{"key": key, "value": 12345}])[1]
            continue
        lo, hi = spec["minimum"], spec["maximum"]
        whole = spec.get("type") == "integer"
        draws = [lo, hi] + [rng.randint(lo, hi) if whole else rng.uniform(lo, hi)
                            for _ in range(20)]
        for v in draws:
            values, problems = check_adjust([{"key": key, "value": v}])
            assert problems == [] and values == {key: v}, (key, v)
        for v in (hi * 1.02 + 0.01, lo * 0.98 - 0.01, hi + 1, lo - 1):
            if lo <= v <= hi:
                continue
            values, problems = check_adjust([{"key": key, "value": v}])
            assert values == {} and len(problems) == 1, (key, v)  # rejected, never clamped


def test_all_problems_are_listed_and_nothing_is_written(tmp_path, make_guard):
    session, box = boxes(tmp_path)
    args = {**GOOD, "prompt": "kurz", "adjust": [
        {"key": "tail_level", "value": 1.5},          # out of range
        {"key": "bursts", "value": 2.5},               # not whole
        {"key": "bp_hz", "value": 1000}, {"key": "bp_hz", "value": 1100},  # duplicate
        {"key": "reverb", "value": 1},                 # unknown
        {"key": "sample_rate", "value": 96000},        # not in enum
        {"key": "seed", "value": 1},                   # own argument
    ]}
    result = run(make_guard(), box, "generate_sample", args)
    assert result.is_error
    text = result.content["message"] if "message" in result.content else str(result.content)
    for needle in ("prompt must be", "tail_level must be from 0 to 1", "whole number",
                   "duplicate key 'bp_hz'", "unknown key 'reverb'", "sample_rate must be one of",
                   "'seed' is its own argument"):
        assert needle in text, needle
    assert not list((Path(session.project_dir)).rglob("*.wav"))
    assert session.sample_ids() == ()


def test_bad_preset_seed_variants_and_category_are_refused(tmp_path, make_guard):
    session, box = boxes(tmp_path)
    guard = make_guard()
    for change in ({"preset": "huge"}, {"seed": 4294967296}, {"seed": -1}, {"variants": 0},
                   {"variants": 9}):
        result = run(guard, box, "generate_sample", {**GOOD, "adjust": FAST, **change})
        assert result.is_error, change
    assert validation_errors(SampleTools(session).tools()[0],
                             {**GOOD, "category": "kick"})  # enum: clap only


# --- happy path, determinism, import ---------------------------------------------------------


def test_valid_call_writes_wav_and_sidecar_and_the_id_imports(tmp_path, make_guard, fake):
    session, box = boxes(tmp_path, fake)
    guard = make_guard()
    result = run(guard, box, "generate_sample", {**GOOD, "variants": 2, "adjust": FAST})
    assert result.is_error is False, result.content
    samples = result.content["samples"]
    assert [s["sample_id"] for s in samples] == ["clap-1", "clap-2"]
    folder = Path(result.content["folder"])
    assert folder.name != "" and "clap" in folder.parts[-1].lower()
    assert len(list(folder.iterdir())) == 4  # 2 x (WAV + sidecar) = 2 * variants
    for s in samples:
        side = json.loads((folder / s["file"]).with_suffix(".json").read_text("utf-8"))
        assert side["category"] == "clap" and side["schema_version"] == "0.2"
        assert side["parameters"]["length_ms"] == 200 and side["parameters"]["preset"] == "short"
    assert session.entry("clap-1").sha256 == sha(session.entry("clap-1").path)
    # the existing import path takes the clap id (fake AbletonOSC, not Live)
    approver = Approver(True)
    imported = run(guard, box, "import_sample", {"sample_id": "clap-2", "track_index": 0},
                   approver)
    assert imported.is_error is False, imported.content
    path = session.entry("clap-2").path
    assert writes_sent(fake) == [("/live/clip_slot/create_audio_clip", (0, 0, path))]
    # kick ids are untouched by clap ids
    assert session.entry("kick-1") is None


def test_same_call_gives_the_same_wav_bytes(tmp_path, make_guard):
    hashes = []
    for sub in ("a", "b"):
        (tmp_path / sub).mkdir()
        session, box = boxes(tmp_path / sub)
        r = run(make_guard(), box, "generate_sample", {**GOOD, "variants": 2, "adjust": FAST})
        assert r.is_error is False, r.content
        hashes.append([sha(session.entry(s["sample_id"]).path) for s in r.content["samples"]])
    assert hashes[0] == hashes[1] and hashes[0][0] != hashes[0][1]
    # a different seed gives a different clap
    (tmp_path / "c").mkdir()
    session, box = boxes(tmp_path / "c")
    r = run(make_guard(), box, "generate_sample", {**GOOD, "seed": 8, "adjust": FAST})
    assert sha(session.entry("clap-1").path) != hashes[0][0]


# --- guard -----------------------------------------------------------------------------------


def test_the_guard_file_budget_applies(tmp_path, make_guard):
    """Profile 'p' allows 10 files: 5 claps pass, 8 claps (16 files) are refused by the guard
    with the numbers, nothing written, and the refusal is an error result, not a success."""
    _, box = boxes(tmp_path)
    guard = make_guard()
    ok = run(guard, box, "generate_sample", {**GOOD, "variants": 5, "adjust": FAST})
    assert ok.is_error is False and len(ok.content["samples"]) == 5
    (tmp_path / "x").mkdir()
    session2, box2 = boxes(tmp_path / "x")
    refused = run(make_guard(), box2, "generate_sample",
                  {**GOOD, "variants": 8, "adjust": FAST})
    assert refused.is_error and refused.content["error"] == "file_budget"
    assert "16 files" in refused.content["message"] and "10" in refused.content["message"]
    assert session2.sample_ids() == () and not list(Path(session2.project_dir).rglob("*.wav"))


def test_second_call_in_one_request_is_counted(tmp_path, make_guard):
    session, box = boxes(tmp_path)
    guard = make_guard()
    with guard.request("p") as req:
        a = box.run(req, ToolCall("c1", "generate_sample",
                                  {**GOOD, "variants": 3, "adjust": FAST}), None)
        b = box.run(req, ToolCall("c2", "generate_sample",
                                  {**GOOD, "seed": 9, "variants": 3, "adjust": FAST}), None)
    assert a.is_error is False
    assert b.is_error and b.content["error"] == "file_budget"  # 6 + 6 > 10
    assert len(session.sample_ids()) == 3


def test_no_route_around_the_toolbox_in_sample_tools():
    """Static guard-wiring check also sees this module; a direct handler call is caught."""
    text = (SRC / "orchestrator" / "sample_tools.py").read_text("utf-8")
    mods = [(r, t) for r, t in _modules() if r != "orchestrator/sample_tools.py"]
    assert violations(mods + [("orchestrator/sample_tools.py", ast.parse(text))]) == []
    bad = text + "\n\ndef direct(tool, args):\n    return tool.handler(args)\n"
    assert violations(mods + [("orchestrator/sample_tools.py", ast.parse(bad))])


def _modules():
    from test_guard_wiring import _modules as modules

    return modules()


# --- fake German model -----------------------------------------------------------------------


def test_german_request_to_tool_call_to_answer(tmp_path, make_guard, events):
    session, box = boxes(tmp_path)
    args = {**GOOD, "adjust": [{"key": "length_ms", "value": 250},
                               {"key": "bp_hz", "value": 2200}]}
    fake = FakeModel([
        {"text": "Ich rendere eine kurze, helle Klatsche.",
         "tool_calls": [{"id": "c1", "name": "generate_sample", "arguments": args}],
         "usage": USAGE},
        {"text": "Fertig: clap-1 ist kurz und hell.", "usage": USAGE}])
    model = ScriptedModel(lambda i, request: fake.complete(request), events)
    orch = Orchestrator(make_guard(), model, box, profile="p", approver=Approver(True),
                        context=session.context)
    out = orch.handle("Mach mir eine kurze, helle Klatsche.")
    assert out.success and out.reply == "Fertig: clap-1 ist kurz und hell."
    results = [m.results[0] for r in model.requests for m in r.messages
               if isinstance(m, ToolResultMessage)]
    assert results[0].is_error is False
    assert results[0].content["samples"][0]["sample_id"] == "clap-1"
    assert out.usage["files_written"] == 2 and out.usage["live_writes"] == 0
    assert "clap-1" in session.context()
    # the sidecar carries the adjusted values
    entry = session.entry("clap-1")
    side = json.loads(Path(entry.path).with_suffix(".json").read_text("utf-8"))
    assert side["parameters"]["bp_hz"] == 2200 and side["parameters"]["length_ms"] == 250
