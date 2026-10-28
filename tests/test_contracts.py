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


# --- sample-metadata instances (#70) ---------------------------------------------------------

# Written by hand from the contract, not by the engine, so the instance does not inherit an
# engine bug. Every optional field is present once.
SAMPLE_METADATA = {
    "schema_version": "0.1",
    "file": "kick.wav",
    "category": "kick",
    "description": "hand-written test instance",
    "engine": {"name": "abeltongod-audio-engine", "version": "0.1.0"},
    "parameters": {"schema_version": "0.2", "seed": 7},
    "features": {
        "peak_dbfs": -0.3,
        "length_ms": 450.0,
        "fundamental_hz": 48.6,
        "decay_20db_ms": 168.0,
        "decay_40db_ms": 279.0,
        "dc_offset": 0.0,
    },
    "bpm": 128,
    "key": None,
    "sha256": "0123456789abcdef" * 4,
    "created_at": "2026-10-28T12:00:00+00:00",
}
SAMPLE_METADATA_REQUIRED = (
    "schema_version", "file", "category", "engine", "parameters", "features", "created_at",
)


def _sample_metadata(**changes) -> dict:
    """Deep copy of SAMPLE_METADATA; a value of ``...`` deletes the key."""
    doc = json.loads(json.dumps(SAMPLE_METADATA))
    for key, value in changes.items():
        if value is ...:
            del doc[key]
        else:
            doc[key] = value
    return doc


def test_sample_metadata_valid_instances() -> None:
    validator = Draft202012Validator(load("sample-metadata.schema.json"))
    validator.validate(_sample_metadata())
    # Only the required fields; null for every nullable feature.
    minimal = {k: v for k, v in _sample_metadata().items() if k in SAMPLE_METADATA_REQUIRED}
    minimal["features"] = {"peak_dbfs": -6.0, "length_ms": 80.0, "fundamental_hz": None,
                           "decay_20db_ms": None, "decay_40db_ms": None, "dc_offset": None}
    validator.validate(minimal)
    # The fixture sidecar from engine 0.0.1 still matches the contract (only its engine differs).
    fixture = ROOT / "tests" / "fixtures" / "sidecars" / "kick-v01.json"
    validator.validate(json.loads(fixture.read_text(encoding="utf-8")))


def test_sample_metadata_required_list_is_the_one_tested_here() -> None:
    """If the contract's required list changes, the negative cases below must follow."""
    assert tuple(load("sample-metadata.schema.json")["required"]) == SAMPLE_METADATA_REQUIRED


SAMPLE_METADATA_INVALID = {
    **{f"missing {key}": _sample_metadata(**{key: ...}) for key in SAMPLE_METADATA_REQUIRED},
    "unknown top-level field": _sample_metadata(wobble=1),
    "schema_version 0.2": _sample_metadata(schema_version="0.2"),
    "schema_version as number": _sample_metadata(schema_version=0.1),
    "file without .wav": _sample_metadata(file="kick.aiff"),
    "file not a string": _sample_metadata(file=1),
    "category snare": _sample_metadata(category="snare"),
    "description too long": _sample_metadata(description="x" * 501),
    "engine is a string": _sample_metadata(engine="abeltongod-audio-engine 0.1.0"),
    "engine is null": _sample_metadata(engine=None),
    "engine without version": _sample_metadata(engine={"name": "abeltongod-audio-engine"}),
    "engine without name": _sample_metadata(engine={"version": "0.1.0"}),
    "engine version as number": _sample_metadata(
        engine={"name": "abeltongod-audio-engine", "version": 0.1}
    ),
    "engine unknown field": _sample_metadata(
        engine={"name": "abeltongod-audio-engine", "version": "0.1.0", "build": "x"}
    ),
    "parameters is a list": _sample_metadata(parameters=[]),
    "features without peak_dbfs": _sample_metadata(features={"length_ms": 80.0}),
    "features peak_dbfs null": _sample_metadata(features={"peak_dbfs": None, "length_ms": 80.0}),
    "features unknown field": _sample_metadata(
        features={"peak_dbfs": -1.0, "length_ms": 80.0, "loudness": -9.0}
    ),
    "bpm as string": _sample_metadata(bpm="128"),
    "key as number": _sample_metadata(key=5),
    "sha256 upper case": _sample_metadata(sha256="0123456789ABCDEF" * 4),
    "sha256 too short": _sample_metadata(sha256="0" * 63),
    "created_at as number": _sample_metadata(created_at=1761652800),
    "root is a list": [SAMPLE_METADATA],
}


@pytest.mark.parametrize("doc", SAMPLE_METADATA_INVALID.values(), ids=SAMPLE_METADATA_INVALID)
def test_sample_metadata_invalid_instances(doc) -> None:
    validator = Draft202012Validator(load("sample-metadata.schema.json"))
    with pytest.raises(ValidationError):
        validator.validate(doc)
