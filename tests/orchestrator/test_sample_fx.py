"""#515: the ``generate_sample`` row for category ``fx`` (riser, downlifter, impact, sweep,
noise / reverse crash).

CI only: fake model, fake AbletonOSC for the import check. No Claude call, no Live. Expected
frame counts are written here from the contract formula done by hand (fx-params $comment
point 1: round((length_beats + tail_beats) * 60 * sample_rate / bpm)), the WAV is read with the
standard library ``wave`` module, not with the engine.
"""

from __future__ import annotations

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
from test_sample_dispatch import CLAP_TO_FX_515, CLAP_TO_PERC_506, digest, strip

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
# table without the fx row (CLAP_TO_PERC_506) is the "before" and keeps its pin
# HAT_PRESET_ONLY_SCHEMA_SHA256 in test_sample_dispatch.py.
# Re-pinned after the review of #516 (bpm only from adjust, "ask the user" text); the first
# pin of this PR was 4c037dad…1157e3f.
FX_SCHEMA_SHA256 = "7ff418776438c13a2a5b5546bf0e8ac887afefa81f044d3694f729e2ae46737e"
FX_PRESETS = ["downlifter", "impact", "noise-crash", "reverse-crash", "riser-16bar",
              "riser-32bar", "riser-8bar", "sweep"]
USAGE = {"output_tokens": 10, "input_tokens": 100, "cost_usd": 0.01}
# riser-8bar = 32 beats (preset file), riser tail default 4 beats (contract allOf riser branch)
RISER_140 = {"category": "fx", "preset": "riser-8bar", "prompt": "", "seed": 5, "variants": 1,
             "adjust": [{"key": "bpm", "value": 140}]}
# By hand: (32 + 4) * 60 * 48000 / 140 = 740571.43 -> 740571 frames; boundary
# 32 * 60 * 48000 / 140 = 658285.71 -> 658286.
RISER_140_FRAMES = 740571
RISER_140_BOUNDARY = 658286
# impact, short and cheap: 1 + 0.5 beats at 150 BPM = 0.6 s
IMPACT = {"category": "fx", "preset": "impact", "prompt": "", "seed": 2, "variants": 1,
          "adjust": [{"key": "bpm", "value": 150}, {"key": "length_beats", "value": 1},
                     {"key": "tail_beats", "value": 0.5}]}
IMPACT_FRAMES = 28800  # 1.5 * 60 * 48000 / 150


def box_for(tmp_path, fake=None):
    session = make_session(tmp_path, fake)
    return session, Toolbox(session.tools() + SampleTools(session).tools(),
                            capability_gate=session.gate())


def run(guard, box, args, approver=None, name="generate_sample"):
    with guard.request("p") as req:
        return box.run(req, ToolCall("c1", name, args), approver)


def frames_and_channels(path):
    with wave.open(str(path), "rb") as w:
        return w.getnframes(), w.getnchannels(), w.getframerate()


# --- schema ----------------------------------------------------------------------------------


def test_fx_row_is_in_the_copilot_tool_and_keeps_the_shape():
    # #536: the default table has an atmos row since; CLAP_TO_FX_515 is the table of #515
    before, after = tool_input_schema(CLAP_TO_PERC_506), tool_input_schema(CLAP_TO_FX_515)
    assert digest(after) == FX_SCHEMA_SHA256 != digest(before)
    assert after["properties"]["category"]["enum"][-1] == "fx"
    assert strip(after) == strip(before) and optional_fields(after) == 0
    text = after["description"]
    for preset in FX_PRESETS:
        assert preset in text
    # tempo: bpm is required and named as the project's tempo; lengths are beats
    assert "bpm (60..200, required)" in text
    assert "always put the Live project's tempo into adjust as bpm" in text
    assert "if you do not know the tempo, ask the user before calling" in text
    assert "A call without bpm in adjust is refused, whatever the preset." in text
    assert "135" not in text  # the presets' tempo is not offered as a fallback
    assert "length_beats (1..128 in steps of 0.25, default set by the kind)" in text
    assert "ramp_beats (0.0625..128, default = length_beats)" in text
    assert ("kind is chosen by the preset only (adjust cannot set it): riser: riser-16bar, "
            "riser-32bar, riser-8bar, ''; downlifter: downlifter; sweep: sweep; impact: impact; "
            "noise_crash: noise-crash; reverse_crash: reverse-crash.") in text
    a = ADAPTERS["fx"]
    assert a.contract == "fx-params.schema.json" and sorted(a.presets) == FX_PRESETS
    assert a.make_variants.__module__ == "audio_engine.fx_variants"
    tool = SampleTools(type("S", (), {"project_dir": "."})(), CLAP_TO_FX_515).tools()[0]
    assert tool.max_files_written == 16
    assert "Categories: clap, hat, snare, rim, bass, laser, perc, fx." in tool.description


def test_text_choices_are_not_adjust_keys():
    keys = adjustable_keys(ADAPTERS["fx"])
    for key in ("kind", "filter_mode", "noise_color", "tone_wave", "echo_note", "seed",
                "variants", "preset", "schema_version"):
        assert key not in keys
    assert "bpm" in keys and "length_beats" in keys


# --- the fake model path: riser at 140 BPM ---------------------------------------------------


def test_fake_model_riser_at_140_bpm_gives_wav_and_sidecar_of_the_contract_length(
        tmp_path, make_guard, events, fake):
    session, box = box_for(tmp_path, fake)
    model_script = FakeModel([
        {"text": "Ich rendere einen Riser über 8 Takte bei 140 BPM.",
         "tool_calls": [{"id": "c1", "name": "generate_sample", "arguments": RISER_140}],
         "usage": USAGE},
        {"text": "Fertig: fx-1, 8 Takte bei 140 BPM.", "usage": USAGE}])
    model = ScriptedModel(lambda i, request: model_script.complete(request), events)
    orch = Orchestrator(make_guard(), model, box, profile="p", approver=Approver(True),
                        context=session.context)
    out = orch.handle("Mach mir einen Riser über 8 Takte, Projekt läuft auf 140 BPM.")
    assert out.success and out.reply == "Fertig: fx-1, 8 Takte bei 140 BPM."
    results = [m.results[0] for r in model.requests for m in r.messages
               if isinstance(m, ToolResultMessage)]
    assert results[0].is_error is False, results[0].content
    assert results[0].content["category"] == "fx"
    assert [s["sample_id"] for s in results[0].content["samples"]] == ["fx-1"]
    assert out.usage["files_written"] == 2 and out.usage["live_writes"] == 0
    wavs = sorted(Path(session.project_dir).rglob("*.wav"))
    assert len(wavs) == 1
    assert wavs[0].parent.parts[-3:] == ("Samples", "FX", "Transitions")
    assert frames_and_channels(wavs[0]) == (RISER_140_FRAMES, 2, 48000)
    side = json.loads(wavs[0].with_suffix(".json").read_text("utf-8"))
    assert side["category"] == "fx" and side["schema_version"] == "0.2"
    p = side["parameters"]
    assert (p["bpm"], p["kind"], p["length_beats"], p["tail_beats"], p["preset"]) == (
        140, "riser", 32, 4, "riser-8bar")
    assert side["features"]["boundary_frame"] == RISER_140_BOUNDARY
    assert side["features"]["anchor"] == "start"
    # the existing import path takes the fx id (fake AbletonOSC, not Live)
    approver = Approver(True)
    imported = run(make_guard(), box, {"sample_id": "fx-1", "track_index": 0}, approver,
                   name="import_sample")
    assert imported.is_error is False, imported.content
    assert writes_sent(fake) == [("/live/clip_slot/create_audio_clip",
                                  (0, 0, session.entry("fx-1").path))]


@pytest.mark.parametrize("bpm,frames", [(150, IMPACT_FRAMES), (120, 36000)])
def test_the_tempo_from_adjust_sets_the_file_length(tmp_path, make_guard, bpm, frames):
    session, box = box_for(tmp_path)
    args = {**IMPACT, "adjust": [{"key": "bpm", "value": bpm}, *IMPACT["adjust"][1:]]}
    r = run(make_guard(), box, args)
    assert r.is_error is False, r.content
    wav = next(Path(session.project_dir).rglob("*.wav"))
    assert frames_and_channels(wav)[0] == frames  # 1.5 beats at bpm, 48 kHz


@pytest.mark.parametrize("preset", FX_PRESETS)
def test_a_preset_without_bpm_in_adjust_is_refused(tmp_path, make_guard, preset):
    """Lead decision on #515: every fx preset carries bpm 135, which is not the project's
    tempo; without bpm in adjust nothing is rendered, whatever the preset."""
    session, box = box_for(tmp_path)
    args = {**IMPACT, "preset": preset, "adjust": IMPACT["adjust"][1:]}  # no bpm
    r = run(make_guard(), box, args)
    assert r.is_error
    assert "bpm is required for fx" in r.content["message"]
    _assert_nothing(session)


# --- refusals --------------------------------------------------------------------------------


def _assert_nothing(session):
    assert not list(Path(session.project_dir).rglob("*.wav"))
    assert not list(Path(session.project_dir).rglob("*.json"))
    assert session.sample_ids() == ()


def test_invalid_fx_calls_are_refused_and_write_nothing(tmp_path, make_guard):
    session, box = box_for(tmp_path)
    bad = [
        {**RISER_140, "preset": "", "adjust": []},  # no bpm anywhere
        {**RISER_140, "preset": "rolling"},  # a bass preset
        {**RISER_140, "prompt": "riser"},
        {**RISER_140, "adjust": [{"key": "bpm", "value": 59}]},
        {**RISER_140, "adjust": [{"key": "bpm", "value": 201}]},
        {**RISER_140, "adjust": [{"key": "bpm", "value": 140}, {"key": "length_beats",
                                                                 "value": 31.9}]},
        {**RISER_140, "adjust": [{"key": "kind", "value": 1}]},
        {**RISER_140, "adjust": [{"key": "filter_mode", "value": 1}]},
        {**RISER_140, "adjust": [{"key": "decay_ms", "value": 300}]},  # a laser key
        {**RISER_140, "variants": 9},
    ]
    for args in bad:
        r = run(make_guard(), box, args)
        assert r.is_error, args
    _assert_nothing(session)


def test_local_refusal_texts_name_the_contract_rule():
    def problems(*adjust, preset="riser-8bar"):
        return build_request({**RISER_140, "preset": preset, "adjust": list(adjust)})[1]

    def with_bpm(*adjust):  # bpm last, so the adjust[i] indices of the other items stay
        return problems(*adjust, {"key": "bpm", "value": 140})

    required = ("bpm is required for fx: add {key: 'bpm', value: ...} to adjust (lengths are "
                "in beats; use the Live project's tempo, ask the user if it is not known; a "
                "preset's tempo does not count)")
    assert problems(preset="") == [required]
    assert problems() == [required]  # riser-8bar carries bpm 135: it does not count
    assert problems({"key": "bpm", "value": 201}) == [
        "adjust[0]: bpm must be from 60 to 200, got 201"]
    assert with_bpm({"key": "length_beats", "value": 31.9}) == [
        "adjust[0]: length_beats must be from 1 to 128 in steps of 0.25, got 31.9"]
    assert with_bpm({"key": "tail_beats", "value": 0.25}, {"key": "cut_beats", "value": 7.75}) \
        == []
    assert with_bpm({"key": "kind", "value": 2}) == [
        "adjust[0]: kind is chosen by the preset, not through adjust; presets: "
        + ", ".join(FX_PRESETS)]
    assert with_bpm({"key": "echo_note", "value": 2}) == [
        "adjust[0]: echo_note follows the preset or the kind's defaults, not adjust; presets: "
        + ", ".join(FX_PRESETS)]
    # all problems in one refusal: the unknown preset and the missing bpm
    assert problems(preset="nope") == [
        "unknown preset 'nope'; presets: " + ", ".join(FX_PRESETS) + " (or '' for the defaults)",
        required]
    # a bpm given but out of range is named once (as out of range), not also as missing
    assert problems({"key": "bpm", "value": 201}, preset="nope")[1:] == [
        "adjust[0]: bpm must be from 60 to 200, got 201"]


@pytest.mark.parametrize("adjust,rule", [
    # rule A: (128 + 4) beats at 60 BPM = 132 s > 72 s
    ([{"key": "bpm", "value": 60}, {"key": "length_beats", "value": 128}], "(rule A)"),
    # rule B: both layers silent
    ([{"key": "bpm", "value": 140}, {"key": "noise_level", "value": 0},
      {"key": "tone_level", "value": 0}], "(rule B)"),
    # rule C: cut_beats not below length_beats
    ([{"key": "bpm", "value": 140}, {"key": "length_beats", "value": 4},
      {"key": "cut_beats", "value": 4}], "(rule C)"),
])
def test_cross_field_rules_come_back_as_the_contract_error(tmp_path, make_guard, adjust, rule):
    session, box = box_for(tmp_path)
    r = run(make_guard(), box, {**RISER_140, "adjust": adjust})
    assert r.is_error
    assert "fx parameters refused: Invalid fx parameters:" in r.content["message"]
    assert rule in r.content["message"]
    _assert_nothing(session)


def test_the_guard_file_budget_applies_to_fx(tmp_path, make_guard):
    session, box = box_for(tmp_path)
    refused = run(make_guard(max_files_written=10), box, {**IMPACT, "variants": 6})
    assert refused.is_error and refused.content["error"] == "file_budget"
    _assert_nothing(session)


# --- property test over the contract ranges --------------------------------------------------


def _value(spec, rng):
    if "enum" in spec:
        return rng.choice(spec["enum"])
    lo, hi = spec["minimum"], spec["maximum"]
    if "multipleOf" in spec:
        step = spec["multipleOf"]
        return rng.randint(round(lo / step), round(hi / step)) * step
    return round(rng.uniform(lo, hi), 3)


def test_random_in_range_adjust_values_are_accepted_and_off_grid_refused():
    rng = random.Random(515)
    keys = adjustable_keys(ADAPTERS["fx"])
    for _ in range(300):
        chosen = rng.sample(sorted(keys), rng.randint(1, 4))
        adjust = [{"key": k, "value": _value(keys[k], rng)} for k in chosen]
        values, problems = build_request(
            {"category": "fx", "preset": rng.choice(["", *FX_PRESETS]), "prompt": "",
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
            _, problems = build_request({**RISER_140, "adjust": [{"key": key, "value": value}]})
            assert problems and key in problems[0], (key, value)
