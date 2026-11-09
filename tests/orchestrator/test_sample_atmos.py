"""#536 (D-034): the ``generate_sample`` row for category ``atmos`` (noise_bed, drone,
resonant, granular loops).

CI only: fake model, fake AbletonOSC for the import check. No Claude call, no Live. Expected
frame counts are written here by hand from atmos-params $comment point 1
(N = round(240 * bars * sample_rate / bpm), seamless loop = exactly N frames); the WAV is read
with the standard library ``wave`` module, not with the engine.
"""

from __future__ import annotations

import dataclasses
import json
import random
import wave
from pathlib import Path

import pytest
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
from test_contracts import optional_fields
from test_sample_dispatch import CLAP_TO_FX_515, digest, strip

from guard import Limit
from orchestrator.fake_model import FakeModel
from orchestrator.loop import Orchestrator
from orchestrator.model_client import ToolCall, ToolResultMessage
from orchestrator.sample_tools import (
    ADAPTERS,
    SampleTools,
    adjustable_keys,
    build_request,
    tool_input_schema,
)
from orchestrator.tools import Toolbox

# Written down from a run on this branch (sha256 of json.dumps(schema, sort_keys=True)). The
# table without the atmos row (CLAP_TO_FX_515) is the "before" and keeps its pin
# FX_SCHEMA_SHA256 in test_sample_fx.py.
ATMOS_SCHEMA_SHA256 = "13e958925c30d465b71f863f5ce0e6ad10dd5f6aeb0ecfbd2cacfbf007839add"
ATMOS_PRESETS = ["air-bed", "dark-bed", "drone-octaves-e1", "drone-root-fifth",
                 "granular-drone", "granular-metal", "pumping-bed", "resonant-bed"]
USAGE = {"output_tokens": 10, "input_tokens": 100, "cost_usd": 0.01}
# drone at 150 BPM, 2 bars. By hand: 240 * 2 * 48000 / 150 = 153600 frames exactly.
# Tuning rule C: bin 48000 / 153600 = 0.3125 Hz, note 36 = 65.406 Hz -> bin 209 = 65.3125 Hz,
# 2.5 cents flat, inside the default 5 cents.
DRONE_150 = {"category": "atmos", "preset": "drone-root-fifth", "prompt": "", "seed": 5,
             "variants": 1, "adjust": [{"key": "bpm", "value": 150}, {"key": "bars", "value": 2}]}
DRONE_150_FRAMES = 153600
# noise bed, 1 bar, cheap
BED = {"category": "atmos", "preset": "pumping-bed", "prompt": "", "seed": 2, "variants": 1,
       "adjust": [{"key": "bpm", "value": 128}, {"key": "bars", "value": 1}]}
REQUIRED = ("bpm is required for atmos: add {key: 'bpm', value: ...} to adjust (the loop "
            "length is in bars at this tempo; use the Live project's tempo, ask the user if it "
            "is not known; a preset's tempo does not count)")


def box_for(tmp_path, fake=None, adapters=None):
    session = make_session(tmp_path, fake)
    return session, Toolbox(session.tools() + SampleTools(session, adapters).tools(),
                            capability_gate=session.gate())


def run(guard, box, args, approver=None, name="generate_sample"):
    with guard.request("p") as req:
        return box.run(req, ToolCall("c1", name, args), approver)


def frames_and_channels(path):
    with wave.open(str(path), "rb") as w:
        return w.getnframes(), w.getnchannels(), w.getframerate()


def _assert_nothing(session):
    assert not list(Path(session.project_dir).rglob("*.wav"))
    assert not list(Path(session.project_dir).rglob("*.json"))
    assert session.sample_ids() == ()


# --- schema ----------------------------------------------------------------------------------


def test_atmos_row_is_in_the_copilot_tool_and_keeps_the_shape():
    before, after = tool_input_schema(CLAP_TO_FX_515), tool_input_schema()
    assert digest(after) == ATMOS_SCHEMA_SHA256 != digest(before)
    assert after["properties"]["category"]["enum"][-1] == "atmos"
    assert strip(after) == strip(before) and optional_fields(after) == 0
    text = after["description"]
    for preset in ATMOS_PRESETS:
        assert preset in text
    # tempo: bpm is required and named as the project's tempo; the loop is bars at bpm
    assert "For category 'atmos'" in text
    seg = text[text.index("For category 'atmos'"):]
    assert "bpm (60..200, required)" in seg
    assert "always put the Live project's tempo into adjust as bpm" in seg
    assert "if you do not know the tempo, ask the user before calling" in seg
    assert "A call without bpm in adjust is refused, whatever the preset." in seg
    assert "135" not in seg  # the presets' tempo is not offered as a fallback
    assert "bars (one of 1/2/4/8/16/32, default 8)" in seg
    assert "hp_hz (20..2000, default set by the kind)" in seg
    # intervals: fixed per preset, the text names which preset gives which chord
    assert ("intervals is chosen by the preset only (adjust cannot set it): [0, 7, 12]: "
            "air-bed, dark-bed, drone-root-fifth, granular-drone, granular-metal, pumping-bed, "
            "resonant-bed, ''; [0, 12, 24]: drone-octaves-e1.") in seg
    assert ("kind is chosen by the preset only (adjust cannot set it): noise_bed: air-bed, "
            "dark-bed, pumping-bed, ''; drone: drone-octaves-e1, drone-root-fifth; resonant: "
            "resonant-bed; granular: granular-drone, granular-metal.") in seg
    a = ADAPTERS["atmos"]
    assert a.contract == "atmos-params.schema.json" and sorted(a.presets) == ATMOS_PRESETS
    assert a.make_variants.__module__ == "audio_engine.atmos_variants"
    tool = SampleTools(type("S", (), {"project_dir": "."})()).tools()[0]
    assert tool.max_files_written == 16
    assert "Categories: clap, hat, snare, rim, bass, laser, perc, fx, atmos." in tool.description


def test_text_choices_and_the_chord_are_not_adjust_keys():
    keys = adjustable_keys(ADAPTERS["atmos"])
    for key in ("kind", "loop_mode", "move_shape", "granular_source", "intervals",
                "filter_mode", "seed", "variants", "preset", "schema_version"):
        assert key not in keys
    assert "bpm" in keys and "bars" in keys and "note" in keys
    # every adjust key is a single number range or a numeric enum (the tool's value is a number)
    for key, spec in keys.items():
        assert ("minimum" in spec and "maximum" in spec) or all(
            isinstance(v, int | float) for v in spec["enum"]), key


# --- the fake model path: drone at 150 BPM ---------------------------------------------------


def test_fake_model_drone_at_150_bpm_gives_a_loop_of_the_contract_length(
        tmp_path, make_guard, events, fake):
    session, box = box_for(tmp_path, fake)
    model_script = FakeModel([
        {"text": "Ich rendere einen Drone-Loop über 2 Takte bei 150 BPM.",
         "tool_calls": [{"id": "c1", "name": "generate_sample", "arguments": DRONE_150}],
         "usage": USAGE},
        {"text": "Fertig: atmos-1, 2 Takte bei 150 BPM.", "usage": USAGE}])
    model = ScriptedModel(lambda i, request: model_script.complete(request), events)
    orch = Orchestrator(make_guard(), model, box, profile="p", approver=Approver(True),
                        context=session.context)
    out = orch.handle("Mach mir einen Drone über 2 Takte, Projekt läuft auf 150 BPM.")
    assert out.success and out.reply == "Fertig: atmos-1, 2 Takte bei 150 BPM."
    results = [m.results[0] for r in model.requests for m in r.messages
               if isinstance(m, ToolResultMessage)]
    assert results[0].is_error is False, results[0].content
    assert results[0].content["category"] == "atmos"
    assert [s["sample_id"] for s in results[0].content["samples"]] == ["atmos-1"]
    assert out.usage["files_written"] == 2 and out.usage["live_writes"] == 0
    wavs = sorted(Path(session.project_dir).rglob("*.wav"))
    assert len(wavs) == 1
    assert wavs[0].parent.parts[-2:] == ("Samples", "Atmos")
    assert frames_and_channels(wavs[0]) == (DRONE_150_FRAMES, 2, 48000)
    side = json.loads(wavs[0].with_suffix(".json").read_text("utf-8"))
    assert side["category"] == "atmos" and side["schema_version"] == "0.2"
    p = side["parameters"]
    assert (p["bpm"], p["bars"], p["kind"], p["intervals"], p["loop_mode"], p["preset"]) == (
        150, 2, "drone", [0, 7, 12], "seamless", "drone-root-fifth")
    assert isinstance(p["bars"], int)
    assert side["features"]["loop_samples"] == DRONE_150_FRAMES
    assert side["features"]["seamless"] is True
    # the existing import path takes the atmos id (fake AbletonOSC, not Live)
    imported = run(make_guard(), box, {"sample_id": "atmos-1", "track_index": 0},
                   Approver(True), name="import_sample")
    assert imported.is_error is False, imported.content
    assert writes_sent(fake) == [("/live/clip_slot/create_audio_clip",
                                  (0, 0, session.entry("atmos-1").path))]


# By hand: 240 * 1 * 48000 / bpm; 128 -> 90000, 120 -> 96000, 135 -> 85333.33 -> 85333
@pytest.mark.parametrize("bpm,frames", [(128, 90000), (120, 96000), (135, 85333)])
def test_the_tempo_from_adjust_sets_the_loop_length(tmp_path, make_guard, bpm, frames):
    session, box = box_for(tmp_path)
    args = {**BED, "adjust": [{"key": "bpm", "value": bpm}, *BED["adjust"][1:]]}
    r = run(make_guard(), box, args)
    assert r.is_error is False, r.content
    wav = next(Path(session.project_dir).rglob("*.wav"))
    assert frames_and_channels(wav) == (frames, 2, 48000)


@pytest.mark.parametrize("preset", [*ATMOS_PRESETS, ""])
def test_a_call_without_bpm_in_adjust_is_refused(tmp_path, make_guard, preset):
    """Every atmos preset carries bpm 135, which is not the project's tempo; without bpm in
    adjust nothing is rendered, whatever the preset (same rule as fx, #515)."""
    session, box = box_for(tmp_path)
    r = run(make_guard(), box, {**BED, "preset": preset, "adjust": BED["adjust"][1:]})
    assert r.is_error
    assert r.content["problems"] == [REQUIRED]
    _assert_nothing(session)


def test_fake_model_without_tempo_writes_nothing_and_gets_the_bpm_refusal(
        tmp_path, make_guard, events):
    session, box = box_for(tmp_path)
    no_bpm = {**BED, "adjust": BED["adjust"][1:]}
    model_script = FakeModel([
        {"text": "Ich rendere ein Atmo.",
         "tool_calls": [{"id": "c1", "name": "generate_sample", "arguments": no_bpm}],
         "usage": USAGE},
        {"text": "Welches Tempo hat dein Live-Projekt?", "usage": USAGE}])
    model = ScriptedModel(lambda i, request: model_script.complete(request), events)
    orch = Orchestrator(make_guard(), model, box, profile="p", approver=Approver(True),
                        context=session.context)
    out = orch.handle("Mach mir ein Atmo.")
    results = [m.results[0] for r in model.requests for m in r.messages
               if isinstance(m, ToolResultMessage)]
    assert results[0].is_error is True
    assert REQUIRED in results[0].content["message"]
    assert out.reply == "Welches Tempo hat dein Live-Projekt?"
    assert out.usage["files_written"] == 0
    _assert_nothing(session)


# --- refusals --------------------------------------------------------------------------------


def test_invalid_atmos_calls_are_refused_and_write_nothing(tmp_path, make_guard):
    session, box = box_for(tmp_path)
    bad = [
        {**BED, "preset": "riser-8bar"},  # an fx preset
        {**BED, "prompt": "dark pad"},
        {**BED, "adjust": [{"key": "bpm", "value": 59}]},
        {**BED, "adjust": [{"key": "bpm", "value": 201}]},
        {**BED, "adjust": [{"key": "bpm", "value": 128}, {"key": "bars", "value": 3}]},
        {**BED, "adjust": [{"key": "bpm", "value": 128}, {"key": "intervals", "value": 7}]},
        {**BED, "adjust": [{"key": "bpm", "value": 128}, {"key": "kind", "value": 1}]},
        {**BED, "adjust": [{"key": "bpm", "value": 128}, {"key": "filter_mode", "value": 1}]},
        {**BED, "adjust": [{"key": "bpm", "value": 128}, {"key": "length_beats", "value": 4}]},
        {**BED, "variants": 9},
    ]
    for args in bad:
        r = run(make_guard(), box, args)
        assert r.is_error, args
    _assert_nothing(session)


def test_local_refusal_texts():
    def problems(*adjust, preset="pumping-bed"):
        return build_request({**BED, "preset": preset, "adjust": list(adjust)})[1]

    def with_bpm(*adjust):  # bpm last, so the adjust[i] indices of the other items stay
        return problems(*adjust, {"key": "bpm", "value": 128})

    assert problems() == [REQUIRED]  # pumping-bed carries bpm 135: it does not count
    assert problems(preset="") == [REQUIRED]
    assert problems({"key": "bpm", "value": 201}) == [
        "adjust[0]: bpm must be from 60 to 200, got 201"]
    assert with_bpm({"key": "bars", "value": 3}) == [
        "adjust[0]: bars must be one of 1, 2, 4, 8, 16, 32, got 3"]
    assert with_bpm({"key": "fade_in_beats", "value": 1.1}) == [
        "adjust[0]: fade_in_beats must be from 0 to 64 in steps of 0.25, got 1.1"]
    presets = ", ".join(ATMOS_PRESETS)
    assert with_bpm({"key": "intervals", "value": 7}) == [
        f"adjust[0]: intervals is chosen by the preset, not through adjust; presets: {presets}"]
    assert with_bpm({"key": "filter_mode", "value": 2}) == [
        "adjust[0]: filter_mode follows the preset or the kind's defaults, not adjust; "
        f"presets: {presets}"]
    # the fx text keeps its own unit
    fx = build_request({"category": "fx", "preset": "impact", "prompt": "", "seed": 1,
                        "variants": 1, "adjust": []})[1]
    assert fx == ["bpm is required for fx: add {key: 'bpm', value: ...} to adjust (lengths are "
                  "in beats; use the Live project's tempo, ask the user if it is not known; a "
                  "preset's tempo does not count)"]


@pytest.mark.parametrize("adjust,rule", [
    # rule A: 32 bars at 100 BPM = 76.8 s > 72 s
    ([{"key": "bpm", "value": 100}, {"key": "bars", "value": 32}], "rule A"),
    # rule B: lp_hz below 1.5 * hp_hz
    ([{"key": "bpm", "value": 128}, {"key": "hp_hz", "value": 1000},
      {"key": "lp_hz", "value": 1400}], "rule B"),
])
def test_cross_field_rules_come_back_as_the_contract_error(tmp_path, make_guard, adjust, rule):
    session, box = box_for(tmp_path)
    r = run(make_guard(), box, {**BED, "adjust": adjust})
    assert r.is_error
    assert "atmos parameters refused: Invalid atmos parameters:" in r.content["message"]
    assert rule in r.content["message"]
    _assert_nothing(session)


def test_tuning_rule_c_comes_back_and_writes_nothing(tmp_path, make_guard):
    # 1 bar at 150 BPM: bin 0.625 Hz, note 36 (65.406 Hz) -> bin 105 = 65.625 Hz, 5.8 cents
    # sharp > the default 5 cents (by hand)
    session, box = box_for(tmp_path)
    r = run(make_guard(), box, {**DRONE_150, "adjust": [{"key": "bpm", "value": 150},
                                                        {"key": "bars", "value": 1}]})
    assert r.is_error and "rule C" in r.content["message"], r.content
    _assert_nothing(session)


def test_the_guard_file_budget_applies_to_atmos(tmp_path, make_guard):
    session, box = box_for(tmp_path)
    refused = run(make_guard(max_files_written=10), box, {**BED, "variants": 6})
    assert refused.is_error and refused.content["error"] == "file_budget"
    _assert_nothing(session)


def test_a_render_past_the_request_deadline_is_a_timeout_stop_not_a_success(
        tmp_path, make_guard, events, clock):
    """Atmos renders are the slowest category (up to about 40 s for a 32-bar loop, measured
    for #536 on a 2-core Linux dev box). The guard does not interrupt a running handler; when the
    render ends after the profile's timeout_s, the request ends as a timeout stop, never as a
    success, and the files that were written are counted."""
    real = ADAPTERS["atmos"].place

    def slow_place(*args, **kwargs):
        clock.t += 101  # TEST_POLICY timeout_s = 100
        return real(*args, **kwargs)

    table = {**ADAPTERS, "atmos": dataclasses.replace(ADAPTERS["atmos"], place=slow_place)}
    session, box = box_for(tmp_path, adapters=table)
    model_script = FakeModel([
        {"text": "Ich rendere.", "tool_calls": [
            {"id": "c1", "name": "generate_sample", "arguments": BED}], "usage": USAGE},
        {"text": "Fertig.", "usage": USAGE}])
    model = ScriptedModel(lambda i, request: model_script.complete(request), events)
    orch = Orchestrator(make_guard(), model, box, profile="p", approver=Approver(True),
                        context=session.context)
    out = orch.handle("Atmo bei 128 BPM, ein Takt.")
    assert out.success is False
    assert out.stop_reason is Limit.TIMEOUT
    assert out.usage["files_written"] == 2
    assert len(list(Path(session.project_dir).rglob("*.wav"))) == 1


# --- property test over the contract ranges --------------------------------------------------


def _value(spec, rng):
    if "enum" in spec:
        return rng.choice(spec["enum"])
    lo, hi = spec["minimum"], spec["maximum"]
    if "multipleOf" in spec:
        step = spec["multipleOf"]
        return rng.randint(round(lo / step), round(hi / step)) * step
    if spec.get("type") == "integer":
        return rng.randint(lo, hi)
    return round(rng.uniform(lo, hi), 3)


def test_random_in_range_adjust_values_are_accepted_and_out_of_range_refused():
    rng = random.Random(536)
    keys = adjustable_keys(ADAPTERS["atmos"])
    for _ in range(300):
        chosen = rng.sample(sorted(keys), rng.randint(1, 4))
        adjust = [{"key": k, "value": _value(keys[k], rng)} for k in chosen]
        values, problems = build_request(
            {"category": "atmos", "preset": rng.choice(["", *ATMOS_PRESETS]), "prompt": "",
             "seed": rng.randint(0, 2**32 - 1), "variants": rng.randint(1, 8),
             "adjust": adjust + ([] if "bpm" in chosen else [{"key": "bpm", "value": 128}])})
        assert problems == [], (adjust, problems)  # cross-field rules are the engine's
        for item in adjust:
            assert values[item["key"]] == item["value"]
    for key, spec in keys.items():
        if "minimum" not in spec:
            continue
        bad = [spec["minimum"] - 1e-3, spec["maximum"] + 1e-3]
        if "multipleOf" in spec:
            bad.append(spec["minimum"] + spec["multipleOf"] / 2 + 0.01)
        for value in bad:
            _, problems = build_request({**BED, "adjust": [{"key": key, "value": value}]})
            assert problems and key in problems[0], (key, value)
