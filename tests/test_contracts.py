"""Checks that every contract is a valid JSON Schema and that the capability registry obeys it."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts"
CONFIG = ROOT / "config"


def load(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", sorted(CONTRACTS.glob("*.schema.json")), ids=lambda p: p.name)
def test_schema_is_valid(path: Path) -> None:
    Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


def test_capabilities_match_schema() -> None:
    Draft202012Validator(load("capabilities.schema.json")).validate(load("capabilities.json"))


def test_capability_ids_are_unique() -> None:
    ids = [c["id"] for c in load("capabilities.json")["capabilities"]]
    assert len(ids) == len(set(ids))


def test_tested_capability_requires_evidence() -> None:
    validator = Draft202012Validator(load("capabilities.schema.json"))
    doc = {
        "schema_version": "1",
        "live_version_tested": "12.1",
        "capabilities": [
            {"id": "x", "kind": "read", "target": "/x", "status": "tested", "notes": ""}
        ],
    }
    with pytest.raises(ValidationError):
        validator.validate(doc)


def test_live_version_tested_is_set_when_anything_is_tested() -> None:
    """A `tested` status is only meaningful with the Live version it was tested on (#42)."""
    doc = load("capabilities.json")
    if any(c["status"] == "tested" for c in doc["capabilities"]):
        version = doc.get("live_version_tested")
        assert isinstance(version, str) and version.strip(), version


def test_song_undo_notes_keep_the_user_decided_limitation() -> None:
    """song.undo is `tested` from script 0.1.0 by user decision (PR #42); the notes must keep
    the limitation that run could not exclude (bug #39)."""
    undo = next(c for c in load("capabilities.json")["capabilities"] if c["id"] == "song.undo")
    notes = undo["notes"]
    assert "did not re-read the whole set after undo (bug #39)" in notes
    assert "an undo that reverted an unrelated action could not be excluded" in notes
    assert "R4 = unmuted" in notes


def test_default_guard_policy_matches_schema() -> None:
    policy = json.loads((CONFIG / "guard-policy.json").read_text(encoding="utf-8"))
    Draft202012Validator(load("guard-policy.schema.json")).validate(policy)
    for name, profile in policy["profiles"].items():
        assert profile["max_budget_usd"] <= policy["global"]["session_budget_usd"], name
    assert policy["profiles"]["mentor_answer"]["max_live_writes"] == 0
    assert policy["profiles"]["mentor_answer"]["max_files_written"] == 0


def test_guard_policy_rejects_missing_limit() -> None:
    validator = Draft202012Validator(load("guard-policy.schema.json"))
    policy = json.loads((CONFIG / "guard-policy.json").read_text(encoding="utf-8"))
    del policy["profiles"]["kick_generation"]["timeout_s"]
    with pytest.raises(ValidationError):
        validator.validate(policy)


def test_kick_params_defaults_are_within_bounds() -> None:
    schema = load("kick-params.schema.json")
    for name, prop in schema["properties"].items():
        if "default" not in prop:
            continue
        default = prop["default"]
        if "minimum" in prop:
            assert default >= prop["minimum"], name
        if "maximum" in prop:
            assert default <= prop["maximum"], name
        if "enum" in prop:
            assert default in prop["enum"], name


def test_kick_params_rejects_unknown_and_out_of_range() -> None:
    validator = Draft202012Validator(load("kick-params.schema.json"))
    validator.validate({"schema_version": "0.2", "seed": 1})
    with pytest.raises(ValidationError):
        validator.validate({"schema_version": "0.2", "seed": 1, "pitch_end_hz": 5})
    with pytest.raises(ValidationError):
        validator.validate({"schema_version": "0.2", "seed": 1, "wobble": 3})
