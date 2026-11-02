"""#273 (G8): ``generate_sample`` dispatches by the category adapter table.

CI only, no Claude call, no Live. A fake category adapter (clap rendering under another name,
with call recording) proves that the table, not a clap-only path, decides what runs.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

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


def table(*extra):
    return {**ADAPTERS, **{a.name: a for a in extra}}


def box_for(tmp_path, adapters):
    session = make_session(tmp_path)
    tools = SampleTools(session, adapters)
    return session, tools, Toolbox(session.tools() + tools.tools(), capability_gate=session.gate())


def run(guard, box, args, approver=None):
    with guard.request("p") as req:
        return box.run(req, ToolCall("c1", "generate_sample", args), approver)


# --- schema shape ----------------------------------------------------------------------------


def test_clap_only_schema_is_byte_identical_to_pr_266():
    assert digest(tool_input_schema()) == PINNED_SCHEMA_SHA256
    tool = SampleTools(_NoSession()).tools(files_per_request=12)[0]
    assert digest(tool.input_schema) == PINNED_TOOL_SHA256
    assert tool.max_files_written == 16


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
    assert strip(two) == strip(tool_input_schema())
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
    for category in ("hat", "snare", "kick", ""):
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
    assert build_request({**GOOD, "category": "hat"})[1] == [
        "category 'hat' is not available yet; available: clap"]
    assert approver.asked == []
    assert fake.variant_calls == [] and fake.place_calls == []
    assert session.sample_ids() == () and not list(Path(session.project_dir).rglob("*.wav"))
    assert not list(Path(session.project_dir).rglob("*.json"))


def test_default_table_has_exactly_clap_until_a_voice_exists():
    assert list(ADAPTERS) == ["clap"]
