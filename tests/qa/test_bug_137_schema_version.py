"""Regression for #137: the kick-params generator must load with ``schema_version`` as ``enum``.

PR #117 read ``properties.schema_version.const``; PR #114 had made it
``{"enum": ["0.2", "0.3"]}``, so ``tests/support/kick_params.py`` raised ``KeyError: 'const'``
at import and pytest stopped with INTERNALERROR before any test.

Each case copies the generator module into ``tmp_path/tests/support/`` next to a schema
fixture in ``tmp_path/contracts/`` (the module finds the schema relative to its own file) and
imports that copy. No other test module is needed, so this file also runs with
``--noconftest`` (the shared ``tests/conftest.py`` imports the generator itself and would
otherwise turn a broken generator into INTERNALERROR instead of a red test).

Expected values are written here, not taken from the generator.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import random
import shutil
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
GENERATOR = ROOT / "tests" / "support" / "kick_params.py"
CONTRACT = json.loads((ROOT / "contracts" / "kick-params.schema.json").read_text(encoding="utf-8"))

# The v0.2 fields under ``properties`` that ALL draws (everything but schema_version).
V02_FIELDS = (
    "seed", "variants", "bpm", "sample_rate", "bit_depth", "length_ms", "pitch_start_hz",
    "pitch_end_hz", "pitch_decay_ms", "amp_attack_ms", "amp_decay_ms", "click_level",
    "click_tone_hz", "drive", "tone", "peak_ceiling_dbfs", "preset",
)
# v0.3 fields (allOf branch, PR #114), never drawn by the generator.
V03_FIELDS = {"tail_note", "length_beats"}


def _load(tmp_path: Path, schema: dict):
    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / "kick-params.schema.json").write_text(
        json.dumps(schema), encoding="utf-8"
    )
    (tmp_path / "tests" / "support").mkdir(parents=True)
    target = tmp_path / "tests" / "support" / "kick_params.py"
    shutil.copy(GENERATOR, target)
    name = f"_qa137_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, target)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses resolve the module by name
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(name, None)
    return mod


def _const_schema() -> dict:
    """The v0.2 shape: schema_version as const "0.2", no allOf branch."""
    schema = copy.deepcopy(CONTRACT)
    schema["properties"]["schema_version"] = {"const": "0.2"}
    schema.pop("allOf", None)
    return schema


def _check_v02_draws(kp) -> None:
    assert kp.SCHEMA_VERSION == "0.2"
    assert kp.ALL.fields == V02_FIELDS
    for profile in kp.PROFILES.values():
        for s in range(20):
            d = kp.draw(random.Random(s), profile)
            assert d["schema_version"] == "0.2", (profile.name, d)
            assert not V03_FIELDS & set(d), (profile.name, d)


def test_the_merged_contract_has_the_enum_and_v03_branch() -> None:
    """Guards the fixture assumption: the real contract is the enum shape of #137."""
    assert CONTRACT["properties"]["schema_version"]["enum"] == ["0.2", "0.3"]
    branch_fields = {
        f for b in CONTRACT["allOf"] for f in b.get("then", {}).get("properties", {})
    }
    assert V03_FIELDS <= branch_fields
    assert not branch_fields & set(CONTRACT["properties"])


def test_generator_loads_with_schema_version_enum(tmp_path: Path) -> None:
    _check_v02_draws(_load(tmp_path, copy.deepcopy(CONTRACT)))


def test_generator_loads_with_schema_version_const(tmp_path: Path) -> None:
    _check_v02_draws(_load(tmp_path, _const_schema()))


@pytest.mark.parametrize(
    "version_spec",
    [{"enum": ["0.3"]}, {"const": "0.3"}, {"enum": []}, {"type": "string"}],
    ids=["enum-without-0.2", "const-0.3", "empty-enum", "no-const-no-enum"],
)
def test_generator_refuses_a_contract_without_v02(tmp_path: Path, version_spec: dict) -> None:
    schema = copy.deepcopy(CONTRACT)
    schema["properties"]["schema_version"] = version_spec
    with pytest.raises(ValueError, match="not allowed by the contract"):
        _load(tmp_path, schema)


def test_generator_refuses_a_v02_allof_branch(tmp_path: Path) -> None:
    """A branch keyed on "0.2" would allow fields the generator does not draw."""
    schema = copy.deepcopy(CONTRACT)
    schema["allOf"][0]["if"] = {"properties": {"schema_version": {"const": "0.2"}}}
    with pytest.raises(ValueError, match="allOf branch"):
        _load(tmp_path, schema)
