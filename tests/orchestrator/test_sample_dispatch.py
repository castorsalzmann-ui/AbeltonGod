"""#273 (G8): ``generate_sample`` dispatches by the category adapter table.

CI only, no Claude call, no Live. A fake category adapter (clap rendering under another name,
with call recording) proves that the table, not a clap-only path, decides what runs.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest
from kick_helpers import RecordingApprover as Approver
from kick_helpers import (  # noqa: F401 - fake_fixture is a pytest fixture
    fake_fixture,
    make_session,
)
from orch_helpers import (  # noqa: F401 - *_fixture are pytest fixtures (see orch_helpers)
    clock_fixture,
    events_fixture,
    make_guard_fixture,
)
from test_contracts import optional_fields

from audio_engine.clap_variants import make_variants as clap_variants
from library import place_sample
from orchestrator.model_client import ToolCall
from orchestrator.sample_tools import (
    ADAPTERS,
    CategoryAdapter,
    SampleTools,
    build_request,
    tool_input_schema,
)
from orchestrator.tools import Toolbox

# Written down from a run of the clap-only tool on origin/main (e1e265a), not computed by the
# code under test: sha256 of json.dumps(schema, sort_keys=True).
PINNED_SCHEMA_SHA256 = "fab17e19f0bd57e4f6182403767fb31bafb6fa843280170a5e3c2d0fd4cede6b"
PINNED_TOOL_SHA256 = "2595a837c355d7465fce52e3ab26cf84e5ecc58166fc14a14fc241ce3f763d3a"
GOOD = {"category": "clap", "preset": "short", "prompt": "", "seed": 7, "variants": 1,
        "adjust": [{"key": "length_ms", "value": 200}]}


def digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


class Fake:
    """Fake adapter: clap engine under the category name ``fakeclap``, calls recorded."""

    def __init__(self, accepts_prompt=False):
        self.variant_calls: list[tuple[dict, int]] = []
        self.place_calls: list[tuple[str, str]] = []
        self.adapter = CategoryAdapter(
            "fakeclap", "clap-params.schema.json", self._variants, noun="fakeclap",
            accepts_prompt=accepts_prompt, place=self._place, preset_category="clap")

    def _variants(self, base, count):
        self.variant_calls.append((base, count))
        return clap_variants(base, count)

    def _place(self, category, params, project_dir, **kw):
        self.place_calls.append((category, kw["name"]))
        return place_sample("clap", params, project_dir, **kw)


CLAP_ONLY = {"clap": ADAPTERS["clap"]}  # the table of PR #266/#287, before the hat row (#294)
# The hat row before #506 (model still listed as an adjust key): the old tables below use it,
# so their pins stay the "before" of every later row.
HAT_V1 = dataclasses.replace(ADAPTERS["hat"], preset_only=())
CLAP_HAT = {"clap": ADAPTERS["clap"], "hat": HAT_V1}  # the table of PR #302, before snare (#317)

# the table before the rim and bass rows (#355)
CLAP_HAT_SNARE = {**CLAP_HAT, "snare": ADAPTERS["snare"]}
# the table before the laser row (#491)
CLAP_TO_BASS = {**CLAP_HAT_SNARE, "rim": ADAPTERS["rim"], "bass": ADAPTERS["bass"]}


def table(*extra):
    return {**CLAP_ONLY, **{a.name: a for a in extra}}


def box_for(tmp_path, adapters):
    session = make_session(tmp_path)
    tools = SampleTools(session, adapters)
    return session, tools, Toolbox(session.tools() + tools.tools(), capability_gate=session.gate())


def run(guard, box, args, approver=None):
    with guard.request("p") as req:
        return box.run(req, ToolCall("c1", "generate_sample", args), approver)


# --- schema shape ----------------------------------------------------------------------------


V01_CLAP_PRESETS = ["bright", "default", "long", "short"]  # the clap list before #280 (xtreme-*)
# sha256 of the clap-only schema with the CURRENT preset list (4 baseline + 7 xtreme-* names):
# only the preset names inside description text differ from PINNED_SCHEMA_SHA256 (#280); the
# shape test below proves that by stripping descriptions and enum values.
CLAP_SCHEMA_WITH_XTREME_SHA256 = (
    "cb0d129aaeafaec0f72259138e24f54a6cada6b492cdc15cd442e25d9f3662f9")


@pytest.fixture
def v01_clap_presets(monkeypatch):
    """The preset list the 'before' pins were taken with: the four v0.1 clap presets."""
    import orchestrator.sample_tools as st

    real = st.preset_names
    monkeypatch.setattr(
        st, "preset_names", lambda category="kick": V01_CLAP_PRESETS if category == "clap"
        else real(category))


def test_clap_only_schema_is_byte_identical_to_pr_266(v01_clap_presets):
    assert digest(tool_input_schema(CLAP_ONLY)) == PINNED_SCHEMA_SHA256
    tool = SampleTools(_NoSession(), CLAP_ONLY).tools(files_per_request=12)[0]
    assert digest(tool.input_schema) == PINNED_TOOL_SHA256
    assert tool.max_files_written == 16


def test_xtreme_presets_change_only_the_preset_names_in_the_text(monkeypatch):
    """#280: the tool lists preset_names('clap'); the new names are the only change."""
    now = tool_input_schema(CLAP_ONLY)
    assert digest(now) == CLAP_SCHEMA_WITH_XTREME_SHA256
    for name in ("xtreme-saturated", "xtreme-folded", "xtreme-crushed", "xtreme-metal",
                 "xtreme-gated", "xtreme-reversed", "xtreme-wreck"):
        assert name in now["description"]
    import orchestrator.sample_tools as st

    monkeypatch.setattr(st, "preset_names", lambda category="kick": V01_CLAP_PRESETS)
    before = tool_input_schema(CLAP_ONLY)
    assert digest(before) == PINNED_SCHEMA_SHA256
    assert strip(now) == strip(before)  # same shape
    assert optional_fields(now) == optional_fields(before) == 0  # budget unchanged
    assert now["required"] == before["required"]
    # text differs only by the added names: removing them gives the old text back
    text = now["description"]
    for name in (n for n in text.replace(",", " ").split() if n.startswith("xtreme-")):
        text = text.replace(", " + name, "")
    assert text == before["description"]


class _NoSession:
    project_dir = "."


def strip(schema):
    """The shape: the schema without descriptions and enum values."""
    if isinstance(schema, dict):
        return {k: strip(v) for k, v in schema.items()
                if k not in ("description",) and not (k == "enum" and isinstance(v, list))}
    if isinstance(schema, list):
        return [strip(v) for v in schema]
    return schema


def test_another_category_changes_enum_and_texts_but_not_the_shape():
    fake = Fake()
    two = tool_input_schema(table(fake.adapter))
    assert two["properties"]["category"]["enum"] == ["clap", "fakeclap"]
    assert strip(two) == strip(tool_input_schema(CLAP_ONLY))
    assert optional_fields(two) == 0
    assert "fakeclap" in two["description"] and "clap" in two["description"]
    assert two["required"] == ["category", "preset", "prompt", "seed", "variants", "adjust"]


# --- dispatch --------------------------------------------------------------------------------


def test_registered_fake_category_runs_through_its_adapter(tmp_path, make_guard):
    fake = Fake()
    session, _, box = box_for(tmp_path, table(fake.adapter))
    result = run(make_guard(), box, {**GOOD, "category": "fakeclap", "variants": 2})
    assert result.is_error is False, result.content
    assert [s["sample_id"] for s in result.content["samples"]] == ["fakeclap-1", "fakeclap-2"]
    assert result.content["category"] == "fakeclap"
    # the adapter's functions were the ones called, with the adapter's name
    assert [c for _, c in fake.variant_calls] == [2]
    assert fake.variant_calls[0][0]["schema_version"] == "0.1"
    assert fake.place_calls == [("fakeclap", "short_s7_v0"), ("fakeclap", "short_s7_v1")]
    assert session.entry("fakeclap-2").category == "fakeclap"
    # clap in the same table still works and keeps its own counter and engine
    clap = run(make_guard(), box, GOOD)
    assert clap.content["samples"][0]["sample_id"] == "clap-1"
    assert len(fake.variant_calls) == 1


def test_adapter_decides_whether_a_prompt_is_allowed():
    refuse = build_request({**GOOD, "category": "fakeclap", "prompt": "dark"},
                           table(Fake().adapter))[1]
    assert any("prompt must be ''" in p and "fakeclap" in p for p in refuse)
    ok = build_request({**GOOD, "category": "fakeclap", "prompt": "dark"},
                       table(Fake(accepts_prompt=True).adapter))[1]
    assert ok == []


def test_unregistered_category_is_refused_before_approval_and_any_file(tmp_path, make_guard):
    fake = Fake()
    session, tools, box = box_for(tmp_path, table(fake.adapter))
    approver = Approver(True)
    # (a) through the toolbox: the schema enum refuses, approver never asked
    for category in ("hat", "snare", "kick", ""):  # hat: not in THIS table (fake + clap)
        r = run(make_guard(), box, {**GOOD, "category": category}, approver)
        assert r.is_error, category
    # (b) a handler reached with an unregistered category (enum bypassed) still refuses
    handler = tools.tools()[0].handler
    for category in ("hat", "snare", None, 3):
        try:
            handler({**GOOD, "category": category})
        except Exception as exc:  # ToolError
            assert "not available" in str(exc) and "clap" in str(exc)
            assert getattr(exc, "files_written", 0) == 0
        else:
            raise AssertionError(f"{category!r} was accepted")
    assert build_request({**GOOD, "category": "hat"}, CLAP_ONLY)[1] == [
        "category 'hat' is not available yet; available: clap"]
    assert build_request({**GOOD, "category": "snare"}, CLAP_HAT)[1] == [
        "category 'snare' is not available yet; available: clap, hat"]
    assert approver.asked == []
    assert fake.variant_calls == [] and fake.place_calls == []
    assert session.sample_ids() == () and not list(Path(session.project_dir).rglob("*.wav"))
    assert not list(Path(session.project_dir).rglob("*.json"))


# --- hat (#294) ------------------------------------------------------------------------------

# Written down from a run on this branch; the clap-only hashes above are the "before".
HAT_SCHEMA_SHA256 = "4f5ff4b25b6cdc2a180ba8671547ba9a1f1947aa9248ce13428ecfd6369b0a54"
HAT = {"category": "hat", "preset": "closed-std", "prompt": "", "seed": 3, "variants": 2,
       "adjust": [{"key": "decay_ms", "value": 60}]}


def test_default_table_is_clap_hat_snare_rim_bass_laser_perc_fx_atmos():
    assert list(ADAPTERS) == ["clap", "hat", "snare", "rim", "bass", "laser", "perc", "fx",
                              "atmos"]
    assert ADAPTERS["hat"].contract == "hat-params.schema.json"


HAT_SCHEMA_WITH_XTREME_SHA256 = (
    "75aa87b14916e71fd124a2fa21311f6c8aced7d66885f43de60a95fb118af908")


def test_hat_row_changes_enum_and_texts_but_not_the_shape_or_the_budget(v01_clap_presets):
    schema = tool_input_schema(CLAP_HAT)  # the "before" of the snare row (#317)
    assert digest(schema) == HAT_SCHEMA_SHA256  # with the v0.1 clap preset list (#280 note)
    assert schema["properties"]["category"]["enum"] == ["clap", "hat"]
    assert strip(schema) == strip(tool_input_schema(CLAP_ONLY))
    assert optional_fields(schema) == 0
    for preset in ("closed-std", "open-short", "open-long"):
        assert preset in schema["description"]
    assert "choke_ms" in schema["description"]
    tool = SampleTools(_NoSession(), CLAP_HAT).tools()[0]
    assert tool.max_files_written == 16


def test_hat_table_with_the_xtreme_names_keeps_the_shape():
    now = tool_input_schema(CLAP_HAT)
    assert digest(now) == HAT_SCHEMA_WITH_XTREME_SHA256
    assert strip(now) == strip(tool_input_schema(CLAP_ONLY))
    assert optional_fields(now) == 0


def test_hat_generates_through_the_adapter(tmp_path, make_guard):
    session, _, box = box_for(tmp_path, ADAPTERS)
    result = run(make_guard(), box, HAT)
    assert result.is_error is False, result.content
    assert result.content["category"] == "hat"
    assert [s["sample_id"] for s in result.content["samples"]] == ["hat-1", "hat-2"]
    wavs = sorted(Path(session.project_dir).rglob("*.wav"))
    assert len(wavs) == 2 and all("Hats" in w.parts for w in wavs)
    meta = json.loads(wavs[0].with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["category"] == "hat" and meta["parameters"]["preset"] == "closed-std"
    assert meta["parameters"]["decay_ms"] == 60
    assert session.entry("hat-2").category == "hat"


def test_hat_is_deterministic_for_equal_arguments(tmp_path, make_guard):
    runs = []
    for sub in ("a", "b"):
        (tmp_path / sub).mkdir()
        session, _, box = box_for(tmp_path / sub, ADAPTERS)
        assert run(make_guard(), box, HAT).is_error is False
        runs.append([w.read_bytes() for w in sorted(Path(session.project_dir).rglob("*.wav"))])
    assert runs[0] == runs[1]


def test_hat_refusals_write_nothing(tmp_path, make_guard):
    session, _, box = box_for(tmp_path, ADAPTERS)
    bad = [
        {**HAT, "preset": "short"},  # a clap preset
        {**HAT, "prompt": "dark"},
        {**HAT, "adjust": [{"key": "decay_ms", "value": 5000}]},
        {**HAT, "adjust": [{"key": "choke_ms", "value": 3}]},  # 0 or 5..900
        {**HAT, "adjust": [{"key": "model", "value": 2}]},
        {**HAT, "adjust": [{"key": "polarity", "value": 0}]},
        {**HAT, "adjust": [{"key": "hp_hz", "value": 9000}, {"key": "lp_hz", "value": 9500}]},
        {**HAT, "variants": 9},
    ]
    for args in bad:
        r = run(make_guard(), box, args)
        assert r.is_error, args
    assert not list(Path(session.project_dir).rglob("*.wav"))
    assert not list(Path(session.project_dir).rglob("*.json"))
    assert session.sample_ids() == ()


def test_hat_choke_is_checked_locally_before_the_engine(tmp_path, make_guard):
    _, tools, _ = box_for(tmp_path, ADAPTERS)
    for value in (3, 4.9, 901):
        problems = build_request({**HAT, "adjust": [{"key": "choke_ms", "value": value}]})[1]
        assert problems == [f"adjust[0]: choke_ms must be 0 or from 5 to 900, got {value!r}"]


def test_hat_choke_accepts_zero_and_a_range_value(tmp_path, make_guard):
    session, _, box = box_for(tmp_path, ADAPTERS)
    for value in (0, 5, 120, 900):
        args = {**HAT, "variants": 1, "adjust": [{"key": "choke_ms", "value": value}]}
        r = run(make_guard(), box, args)
        assert r.is_error is False, (value, r.content)


def test_hat_files_count_against_the_guard_cap(tmp_path, make_guard):
    """Cap 10 files: 5 hats (WAV + sidecar) fit, 6 hats are stopped by the guard, no file."""
    session, _, box = box_for(tmp_path, ADAPTERS)
    refused = run(make_guard(max_files_written=10), box, {**HAT, "variants": 6})
    assert refused.is_error
    assert not list(Path(session.project_dir).rglob("*.wav"))
    ok = run(make_guard(max_files_written=10), box, {**HAT, "variants": 5})
    assert ok.is_error is False, ok.content
    assert len(list(Path(session.project_dir).rglob("*.wav"))) == 5


def test_kick_and_tom_stay_refused_with_the_default_table(tmp_path, make_guard):
    session, _, box = box_for(tmp_path, ADAPTERS)
    approver = Approver(True)
    for category in ("kick", "tom"):
        assert run(make_guard(), box, {**HAT, "category": category}, approver).is_error
    assert approver.asked == []
    assert build_request({**HAT, "category": "kick"})[1] == [
        "category 'kick' is not available yet; available: clap, hat, snare, rim, bass, laser, "
        "perc, fx, atmos"]
    assert not list(Path(session.project_dir).rglob("*.wav"))


# --- snare (#317) ----------------------------------------------------------------------------

SNARE_SCHEMA_SHA256 = "2aaca736095daf8ae65e7233259b18fe8355b9692e9ab7eaca4abb7be92ae787"
SNARE = {"category": "snare", "preset": "default", "prompt": "", "seed": 3, "variants": 2,
         "adjust": [{"key": "body_hz", "value": 200}]}


def test_snare_row_changes_enum_and_texts_but_not_the_shape_or_the_budget(v01_clap_presets):
    before, after = tool_input_schema(CLAP_HAT), tool_input_schema(CLAP_HAT_SNARE)
    assert digest(after) == SNARE_SCHEMA_SHA256 != digest(before)
    assert after["properties"]["category"]["enum"] == ["clap", "hat", "snare"]
    assert strip(after) == strip(before)  # same shape; enum and description text differ
    assert optional_fields(after) == 0
    for preset in ("default", "tight", "long", "bright", "tonal"):
        assert preset in after["description"]
    assert "body_hz" in after["description"]
    assert SampleTools(_NoSession(), CLAP_HAT_SNARE).tools()[0].max_files_written == 16


def test_snare_generates_through_the_adapter(tmp_path, make_guard):
    session, _, box = box_for(tmp_path, ADAPTERS)
    result = run(make_guard(), box, SNARE)
    assert result.is_error is False, result.content
    assert result.content["category"] == "snare"
    assert [s["sample_id"] for s in result.content["samples"]] == ["snare-1", "snare-2"]
    wavs = sorted(Path(session.project_dir).rglob("*.wav"))
    assert len(wavs) == 2 and all("Snares" in w.parts for w in wavs), wavs
    meta = json.loads(wavs[0].with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["category"] == "snare" and meta["parameters"]["preset"] == "default"
    assert meta["parameters"]["body_hz"] == 200
    assert session.entry("snare-2").category == "snare"


def test_snare_is_deterministic_for_equal_arguments(tmp_path, make_guard):
    runs = []
    for sub in ("a", "b"):
        (tmp_path / sub).mkdir()
        session, _, box = box_for(tmp_path / sub, ADAPTERS)
        assert run(make_guard(), box, SNARE).is_error is False
        runs.append([w.read_bytes() for w in sorted(Path(session.project_dir).rglob("*.wav"))])
    assert runs[0] == runs[1]


def test_snare_refusals_write_nothing(tmp_path, make_guard):
    session, _, box = box_for(tmp_path, ADAPTERS)
    bad = [
        {**SNARE, "preset": "closed-std"},  # a hat preset
        {**SNARE, "preset": "short"},  # a clap preset
        {**SNARE, "prompt": "dark"},  # no keyword parser for snare
        {**SNARE, "adjust": [{"key": "body_hz", "value": 50}]},
        {**SNARE, "adjust": [{"key": "mode_ratio", "value": 3}]},
        {**SNARE, "adjust": [{"key": "polarity", "value": 0}]},
        {**SNARE, "adjust": [{"key": "choke_ms", "value": 10}]},  # a hat key
        {**SNARE, "variants": 9},
    ]
    for args in bad:
        assert run(make_guard(), box, args).is_error, args
    assert not list(Path(session.project_dir).rglob("*.wav"))
    assert not list(Path(session.project_dir).rglob("*.json"))
    assert session.sample_ids() == ()


def test_snare_files_count_against_the_guard_cap(tmp_path, make_guard):
    session, _, box = box_for(tmp_path, ADAPTERS)
    refused = run(make_guard(max_files_written=10), box, {**SNARE, "variants": 6})
    assert refused.is_error
    assert not list(Path(session.project_dir).rglob("*.wav"))
    ok = run(make_guard(max_files_written=10), box, {**SNARE, "variants": 5})
    assert ok.is_error is False, ok.content
    assert len(list(Path(session.project_dir).rglob("*.wav"))) == 5


# --- rim and bass (#355) ---------------------------------------------------------------------

# Written down from a run on this branch (sha256 of json.dumps(schema, sort_keys=True)); the
# snare pins above are the "before". The first uses the v0.1 clap preset list, the second the
# current one (xtreme-* names).
#
# #385 (Goa bass presets goa-roll-short/-medium/-long): only the bass preset names inside the
# description text changed; shape, required fields and budget are untouched (0 optional params).
# Old pins, taken on origin/main (3779f0b) before the Goa presets:
#   RIM_BASS_SCHEMA_SHA256 was  90592a9575dfcd15443615eda99a76cc16dd8becb6842b361e0226f9812154f3
#   ..._WITH_XTREME_SHA256 was  050cd5b8364e4e2069d18bd86b32e5866517abc1abd65c6d318e739f192bfd0e
RIM_BASS_SCHEMA_SHA256 = "5776a82beb99ea2e673baff97908ecad019fd5237f4155294b8022fd8eee68c8"
RIM_BASS_SCHEMA_WITH_XTREME_SHA256 = (
    "ed212dc5ac548349e5d854ea07358869a1441f74dafd41a05d7b52e1a5a68953")
RIM ={"category": "rim", "preset": "clave", "prompt": "", "seed": 3, "variants": 2,
       "adjust": [{"key": "f1_hz", "value": 1200}]}
BASS = {"category": "bass", "preset": "rolling", "prompt": "", "seed": 3, "variants": 2,
        "adjust": [{"key": "note", "value": 40}]}
RIM_PRESETS = ["clave", "high", "long", "rim", "tight"]
BASS_PRESETS = ["bright", "default", "goa-roll-long", "goa-roll-medium", "goa-roll-short", "low",
                "rolling", "sub"]


def test_rim_and_bass_rows_change_enum_and_texts_but_not_the_shape_or_the_budget(
        v01_clap_presets):
    before, after = tool_input_schema(CLAP_HAT_SNARE), tool_input_schema(CLAP_TO_BASS)
    assert digest(before) == SNARE_SCHEMA_SHA256  # the old pin still holds for the old table
    assert digest(after) == RIM_BASS_SCHEMA_SHA256 != digest(before)
    assert after["properties"]["category"]["enum"] == ["clap", "hat", "snare", "rim", "bass"]
    assert strip(after) == strip(before)
    assert optional_fields(after) == 0
    for preset in RIM_PRESETS + BASS_PRESETS:
        assert preset in after["description"]
    for key in ("f2_ratio", "click_ms", "lp_env_amount", "sub_octave_level"):
        assert key in after["description"]
    assert SampleTools(_NoSession(), CLAP_TO_BASS).tools()[0].max_files_written == 16


def test_rim_and_bass_table_with_the_xtreme_names_keeps_the_shape():
    now = tool_input_schema(CLAP_TO_BASS)
    assert digest(now) == RIM_BASS_SCHEMA_WITH_XTREME_SHA256
    assert strip(now) == strip(tool_input_schema(CLAP_ONLY))
    assert optional_fields(now) == 0
    assert now["required"] == ["category", "preset", "prompt", "seed", "variants", "adjust"]


def test_rim_and_bass_adapters_point_at_their_own_engine_and_presets():
    for name, presets in (("rim", RIM_PRESETS), ("bass", BASS_PRESETS)):
        a = ADAPTERS[name]
        assert a.name == name and a.contract == f"{name}-params.schema.json"
        assert sorted(a.presets) == presets
        assert a.make_variants.__module__ == f"audio_engine.{name}_variants"


@pytest.mark.parametrize("args,folder,key,value", [
    (RIM, "Rims", "f1_hz", 1200), (BASS, "Bass", "note", 40)])
def test_rim_and_bass_generate_through_their_adapter(tmp_path, make_guard, args, folder, key,
                                                     value):
    session, _, box = box_for(tmp_path, ADAPTERS)
    name = args["category"]
    result = run(make_guard(), box, args)
    assert result.is_error is False, result.content
    assert result.content["category"] == name
    assert [s["sample_id"] for s in result.content["samples"]] == [f"{name}-1", f"{name}-2"]
    wavs = sorted(Path(session.project_dir).rglob("*.wav"))
    assert len(wavs) == 2 and all(folder in w.parts for w in wavs), wavs
    meta = json.loads(wavs[0].with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["category"] == name and meta["parameters"]["preset"] == args["preset"]
    assert meta["parameters"][key] == value
    assert session.entry(f"{name}-2").category == name


@pytest.mark.parametrize("args", [RIM, BASS])
def test_rim_and_bass_are_deterministic_for_equal_arguments(tmp_path, make_guard, args):
    runs = []
    for sub in ("a", "b"):
        (tmp_path / sub).mkdir()
        session, _, box = box_for(tmp_path / sub, ADAPTERS)
        assert run(make_guard(), box, args).is_error is False
        runs.append([w.read_bytes() for w in sorted(Path(session.project_dir).rglob("*.wav"))])
    assert runs[0] == runs[1]


def test_rim_and_bass_refusals_write_nothing(tmp_path, make_guard):
    session, _, box = box_for(tmp_path, ADAPTERS)
    bad = [
        {**RIM, "preset": "default"},  # a bass/snare preset, not a rim one
        {**RIM, "preset": "short"},  # a clap preset
        {**RIM, "prompt": "dark"},
        {**RIM, "adjust": [{"key": "f1_hz", "value": 100}]},
        {**RIM, "adjust": [{"key": "f2_ratio", "value": 6}]},
        {**RIM, "adjust": [{"key": "polarity", "value": 0}]},
        {**RIM, "adjust": [{"key": "note", "value": 40}]},  # a bass key
        {**RIM, "variants": 9},
        {**BASS, "preset": "clave"},  # a rim preset
        {**BASS, "prompt": "dark"},
        {**BASS, "adjust": [{"key": "note", "value": 23}]},
        {**BASS, "adjust": [{"key": "note", "value": 40.5}]},  # integer field
        {**BASS, "adjust": [{"key": "lp_hz", "value": 5000}]},
        {**BASS, "adjust": [{"key": "f1_hz", "value": 1200}]},  # a rim key
        {**BASS, "variants": 0},
    ]
    for args in bad:
        assert run(make_guard(), box, args).is_error, args
    assert not list(Path(session.project_dir).rglob("*.wav"))
    assert not list(Path(session.project_dir).rglob("*.json"))
    assert session.sample_ids() == ()


@pytest.mark.parametrize("args", [RIM, BASS])
def test_rim_and_bass_files_count_against_the_guard_cap(tmp_path, make_guard, args):
    session, _, box = box_for(tmp_path, ADAPTERS)
    refused = run(make_guard(max_files_written=10), box, {**args, "variants": 6})
    assert refused.is_error
    assert not list(Path(session.project_dir).rglob("*.wav"))
    ok = run(make_guard(max_files_written=10), box, {**args, "variants": 5})
    assert ok.is_error is False, ok.content
    assert len(list(Path(session.project_dir).rglob("*.wav"))) == 5


def test_max_variants_fit_the_request_file_budget(tmp_path, make_guard):
    for args in (RIM, BASS):
        sub = tmp_path / args["category"]
        sub.mkdir()
        session, _, box = box_for(sub, ADAPTERS)
        r = run(make_guard(max_files_written=16), box, {**args, "variants": 8})
        assert r.is_error is False, r.content
        assert len(list(Path(session.project_dir).rglob("*.wav"))) == 8


def _random_adjust(category, rng):
    """Valid values drawn over the whole contract range of 1-3 random adjustable keys."""
    from orchestrator.sample_tools import adjustable_keys

    keys = adjustable_keys(ADAPTERS[category])
    out = []
    for key in rng.sample(sorted(keys), rng.randint(1, 3)):
        spec = keys[key]
        if "enum" in spec:
            value = rng.choice(spec["enum"])
        elif spec.get("type") == "integer":
            value = rng.randint(spec["minimum"], spec["maximum"])
        else:
            value = round(rng.uniform(spec["minimum"], spec["maximum"]), 3)
        out.append({"key": key, "value": value})
    return out


@pytest.mark.parametrize("category", ["rim", "bass"])
def test_random_in_range_adjust_values_are_accepted_and_out_of_range_refused(category):
    """Property test over the contract ranges (seeded): in-range builds, a step outside fails."""
    import random

    from orchestrator.sample_tools import adjustable_keys

    rng = random.Random(355)
    keys = adjustable_keys(ADAPTERS[category])
    for _ in range(200):
        adjust = _random_adjust(category, rng)
        values, problems = build_request(
            {"category": category, "preset": "", "prompt": "", "seed": rng.randint(0, 2**32 - 1),
             "variants": rng.randint(1, 8), "adjust": adjust})
        # cross-field rules are the engine's; the tool-level check has no problem for a range value
        assert problems == [], (adjust, problems)
        for item in adjust:
            assert values[item["key"]] == item["value"]
    for key, spec in keys.items():
        if "minimum" in spec:
            for value in (spec["minimum"] - 1e-3, spec["maximum"] + 1e-3):
                _, problems = build_request({"category": category, "preset": "", "prompt": "",
                                             "seed": 1, "variants": 1,
                                             "adjust": [{"key": key, "value": value}]})
                assert problems and key in problems[0], (key, value)


# --- laser (#491) ----------------------------------------------------------------------------

# Written down from a run on this branch (sha256 of json.dumps(schema, sort_keys=True)); the
# five-row table above (CLAP_TO_BASS) is the "before" and keeps its own pins.
# Re-pinned on purpose with #487: `family` became preset-only (not an adjust key; the text
# names which preset gives which family). Before: 1cd6d880…5205e8.
LASER_SCHEMA_SHA256 = "c3f42976a2f91d4dcbca8c8ae5c90fa73f568bb8e6a7855b8be5491f65cf6c7a"
CLAP_TO_LASER = {**CLAP_TO_BASS, "laser": ADAPTERS["laser"]}
LASER = {"category": "laser", "preset": "pew", "prompt": "", "seed": 3, "variants": 2,
         "adjust": [{"key": "decay_ms", "value": 300}]}
LASER_PRESETS = ["blaster", "blaster-burst5", "blaster-double", "blaster-echo", "blaster-reverb",
                 "blaster-triple-lrl", "glitch", "ion", "pew", "pew-wide-echo", "plasma",
                 "plasma-driven", "rift", "subboom"]


def test_laser_row_changes_enum_and_texts_but_not_the_shape_or_the_budget():
    before, after = tool_input_schema(CLAP_TO_BASS), tool_input_schema(CLAP_TO_LASER)
    assert digest(before) == RIM_BASS_SCHEMA_WITH_XTREME_SHA256  # old pin, old table
    assert digest(after) == LASER_SCHEMA_SHA256 != digest(before)
    assert "family is chosen by the preset only" in after["description"]
    assert after["properties"]["category"]["enum"] == [
        "clap", "hat", "snare", "rim", "bass", "laser"]
    assert strip(after) == strip(before)
    assert optional_fields(after) == 0
    for preset in LASER_PRESETS:
        assert preset in after["description"]
    assert "pitch_start_hz" in after["description"]
    assert SampleTools(_NoSession(), CLAP_TO_LASER).tools()[0].max_files_written == 16
    a = ADAPTERS["laser"]
    assert a.contract == "laser-params.schema.json" and sorted(a.presets) == LASER_PRESETS
    assert a.make_variants.__module__ == "audio_engine.laser_variants"


@pytest.mark.parametrize("preset,version", [("pew", "0.1"), ("blaster-echo", "0.2")])
def test_laser_generates_through_the_adapter(tmp_path, make_guard, preset, version):
    session, _, box = box_for(tmp_path, ADAPTERS)
    result = run(make_guard(), box, {**LASER, "preset": preset})
    assert result.is_error is False, result.content
    assert result.content["category"] == "laser"
    assert [s["sample_id"] for s in result.content["samples"]] == ["laser-1", "laser-2"]
    wavs = sorted(Path(session.project_dir).rglob("*.wav"))
    assert len(wavs) == 2 and all("Lasers" in w.parts for w in wavs), wavs
    meta = json.loads(wavs[0].with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["category"] == "laser" and meta["parameters"]["preset"] == preset
    assert meta["parameters"]["schema_version"] == version
    assert meta["parameters"]["decay_ms"] == 300
    assert session.entry("laser-2").category == "laser"


def test_laser_is_deterministic_for_equal_arguments(tmp_path, make_guard):
    runs = []
    for sub in ("a", "b"):
        (tmp_path / sub).mkdir()
        session, _, box = box_for(tmp_path / sub, ADAPTERS)
        assert run(make_guard(), box, LASER).is_error is False
        runs.append([w.read_bytes() for w in sorted(Path(session.project_dir).rglob("*.wav"))])
    assert runs[0] == runs[1]


def test_laser_refusals_write_nothing(tmp_path, make_guard):
    session, _, box = box_for(tmp_path, ADAPTERS)
    bad = [
        {**LASER, "preset": "rolling"},  # a bass preset
        {**LASER, "prompt": "pew"},
        {**LASER, "adjust": [{"key": "decay_ms", "value": 10}]},
        {**LASER, "adjust": [{"key": "family", "value": 1}]},  # a string enum, set by preset
        {**LASER, "adjust": [{"key": "salvo_count", "value": 3}]},  # v0.2 field: preset only
        {**LASER, "adjust": [{"key": "note", "value": 40}]},  # a bass key
        {**LASER, "variants": 9},
    ]
    for args in bad:
        assert run(make_guard(), box, args).is_error, args
    assert not list(Path(session.project_dir).rglob("*.wav"))
    assert not list(Path(session.project_dir).rglob("*.json"))
    assert session.sample_ids() == ()


def test_laser_max_variants_fit_the_request_file_budget(tmp_path, make_guard):
    session, _, box = box_for(tmp_path, ADAPTERS)
    assert run(make_guard(max_files_written=10), box, {**LASER, "variants": 6}).is_error
    assert not list(Path(session.project_dir).rglob("*.wav"))
    r = run(make_guard(max_files_written=16), box, {**LASER, "variants": 8})
    assert r.is_error is False, r.content
    assert len(list(Path(session.project_dir).rglob("*.wav"))) == 8


# --- perc (#487) -----------------------------------------------------------------------------

# Written down from a run on this branch; the six-row table (CLAP_TO_LASER) is the "before".
PERC_SCHEMA_SHA256 = "71885221c0170f4493d36560cf3a2913f3d9a0f5cf912838d582a76ef441a9d4"
PERC = {"category": "perc", "preset": "conga", "prompt": "", "seed": 3, "variants": 2,
        "adjust": [{"key": "tune_semitones", "value": 2}]}
PERC_PRESETS = ["bongo", "clave", "conga", "conga-dry", "cowbell", "hard-groove-tom",
                "hard-groove-tom-low", "shaker", "shaker-long"]
# preset -> model, read from the preset files by hand (conga.json has no model: default conga)
PERC_MODELS = {"bongo": "conga", "clave": "clave", "conga": "conga", "conga-dry": "conga",
               "cowbell": "cowbell", "hard-groove-tom": "tom", "hard-groove-tom-low": "tom",
               "shaker": "shaker", "shaker-long": "shaker"}


CLAP_TO_PERC = {**CLAP_TO_LASER, "perc": ADAPTERS["perc"]}  # the table before #506


def test_perc_row_changes_enum_and_texts_but_not_the_shape_or_the_budget():
    before, after = tool_input_schema(CLAP_TO_LASER), tool_input_schema(CLAP_TO_PERC)
    assert digest(before) == LASER_SCHEMA_SHA256
    assert digest(after) == PERC_SCHEMA_SHA256 != digest(before)
    assert after["properties"]["category"]["enum"][-1] == "perc"
    assert strip(after) == strip(before) and optional_fields(after) == 0
    text = after["description"]
    for preset in PERC_PRESETS:
        assert preset in text
    # the tool text says how a model is chosen; toms only through the hard-groove presets
    assert ("model is chosen by the preset only (adjust cannot set it): conga: bongo, conga, "
            "conga-dry, ''; tom: hard-groove-tom, hard-groove-tom-low; shaker: shaker, "
            "shaker-long; cowbell: cowbell; clave: clave.") in text
    assert SampleTools(_NoSession()).tools()[0].max_files_written == 16
    a = ADAPTERS["perc"]
    assert a.contract == "perc-params.schema.json" and sorted(a.presets) == PERC_PRESETS
    assert a.make_variants.__module__ == "audio_engine.perc_variants"


@pytest.mark.parametrize("preset", PERC_PRESETS)
def test_every_perc_preset_renders_its_model_into_the_perc_folder(tmp_path, make_guard, preset):
    session, _, box = box_for(tmp_path, ADAPTERS)
    result = run(make_guard(), box, {**PERC, "preset": preset, "variants": 1})
    assert result.is_error is False, result.content
    assert [s["sample_id"] for s in result.content["samples"]] == ["perc-1"]
    wavs = sorted(Path(session.project_dir).rglob("*.wav"))
    assert len(wavs) == 1 and wavs[0].parent.parts[-3:] == ("Samples", "Drums", "Percs")
    meta = json.loads(wavs[0].with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["category"] == "perc" and meta["parameters"]["preset"] == preset
    assert meta["parameters"]["model"] == PERC_MODELS[preset]
    assert meta["parameters"]["tune_semitones"] == 2


def test_perc_without_a_preset_is_a_conga_not_a_tom(tmp_path, make_guard):
    session, _, box = box_for(tmp_path, ADAPTERS)
    assert run(make_guard(), box, {**PERC, "preset": "", "variants": 1}).is_error is False
    wav = next(Path(session.project_dir).rglob("*.wav"))
    assert json.loads(wav.with_suffix(".json").read_text("utf-8"))["parameters"]["model"] \
        == "conga"


def test_perc_is_deterministic_for_equal_arguments(tmp_path, make_guard):
    runs = []
    for sub in ("a", "b"):
        (tmp_path / sub).mkdir()
        session, _, box = box_for(tmp_path / sub, ADAPTERS)
        assert run(make_guard(), box, PERC).is_error is False
        runs.append([w.read_bytes() for w in sorted(Path(session.project_dir).rglob("*.wav"))])
    assert runs[0] == runs[1]


def test_perc_refusals_write_nothing(tmp_path, make_guard):
    session, _, box = box_for(tmp_path, ADAPTERS)
    bad = [
        {**PERC, "preset": "rolling"},  # a bass preset
        {**PERC, "prompt": "conga"},
        {**PERC, "adjust": [{"key": "model", "value": 1}]},  # preset only
        {**PERC, "adjust": [{"key": "tune_semitones", "value": 13}]},
        {**PERC, "adjust": [{"key": "decay_scale", "value": 0.2}]},
        {**PERC, "adjust": [{"key": "family", "value": 1}]},  # a laser key
        {**PERC, "variants": 9},
    ]
    for args in bad:
        assert run(make_guard(), box, args).is_error, args
    assert not list(Path(session.project_dir).rglob("*.wav"))
    assert not list(Path(session.project_dir).rglob("*.json"))
    assert session.sample_ids() == ()
    problems = build_request({**PERC, "adjust": [{"key": "model", "value": 1}]})[1]
    assert problems == ["adjust[0]: model is chosen by the preset, not through adjust; presets: "
                        + ", ".join(PERC_PRESETS)]


def test_perc_max_variants_fit_the_request_file_budget(tmp_path, make_guard):
    session, _, box = box_for(tmp_path, ADAPTERS)
    r = run(make_guard(max_files_written=16), box, {**PERC, "variants": 8})
    assert r.is_error is False, r.content
    assert len(list(Path(session.project_dir).rglob("*.wav"))) == 8


@pytest.mark.parametrize("category", ["perc", "laser"])
def test_random_in_range_adjust_values_are_accepted_for_perc_and_laser(category):
    """Seeded property test over the contract ranges of every adjustable key."""
    import random

    rng = random.Random(487)
    for _ in range(200):
        adjust = _random_adjust(category, rng)
        values, problems = build_request(
            {"category": category, "preset": "", "prompt": "", "seed": rng.randint(0, 2**32 - 1),
             "variants": rng.randint(1, 8), "adjust": adjust})
        assert problems == [], (adjust, problems)
        for item in adjust:
            assert values[item["key"]] == item["value"]


# --- hat model preset-only (#506) ------------------------------------------------------------

# Written down from a run on this branch. Before (the seven-row table with the old hat row,
# CLAP_TO_PERC): PERC_SCHEMA_SHA256. Only the hat text changes: `model` leaves the adjust keys
# and the text says which preset gives which model (no hat preset carries `model`, so every
# preset and '' give the contract default metal_bank; `noise` has no preset).
HAT_PRESET_ONLY_SCHEMA_SHA256 = "45ed5e010c510d76a8584c34076d6caeabdf82ae9a2e9a6fd2e637d01be3ca85"
# the default table after #506, before the fx row (#515; tests/orchestrator/test_sample_fx.py)
CLAP_TO_PERC_506 = {k: a for k, a in ADAPTERS.items() if k not in ("fx", "atmos")}
# the default table after #515, before the atmos row (#536; tests/orchestrator/test_sample_atmos.py)
CLAP_TO_FX_515 = {k: a for k, a in ADAPTERS.items() if k != "atmos"}


def test_hat_model_is_preset_only_and_the_rest_of_the_schema_is_unchanged():
    before, after = tool_input_schema(CLAP_TO_PERC), tool_input_schema(CLAP_TO_PERC_506)
    assert digest(before) == PERC_SCHEMA_SHA256
    assert digest(after) == HAT_PRESET_ONLY_SCHEMA_SHA256 != digest(before)
    assert strip(after) == strip(before) and optional_fields(after) == 0
    assert ("model is chosen by the preset only (adjust cannot set it): metal_bank: "
            "closed-loose, closed-std, closed-tight, open-long, open-short, ''; noise: no "
            "preset.") in after["description"]
    assert "model (one of metal_bank/noise" in before["description"]  # the old adjust key
    assert "model (one of metal_bank/noise" not in after["description"]
    assert build_request({**HAT, "adjust": [{"key": "model", "value": 2}]})[1] == [
        "adjust[0]: model is chosen by the preset, not through adjust; presets: closed-loose, "
        "closed-std, closed-tight, open-long, open-short"]
