"""Checks that every contract is a valid JSON Schema and that the capability registry obeys it."""

import json
import math
import random
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


# --- kick-params v0.3 proposal (#104) --------------------------------------------------------

# Written by hand from the issue's design, not read from the schema: (min, max, default).
# None as default = the field has no default; absent means "use the 0.2 field as before".
V03_NUMBERS = {
    "tail_note": (23, 46, None),
    "length_beats": (0.25, 4, None),
    "click_decay_ms": (0.5, 12, 3),
    "click_q": (0.5, 8, 0.9),
    "offset_ms": (0, 12, 0),
    "clip_db": (0, 12, 0),
}
V03_FIELDS = (*V03_NUMBERS, "polarity")
V02 = {"schema_version": "0.2", "seed": 1}
V03 = {"schema_version": "0.3", "seed": 1}
# Every v0.2 field set to a non-default in-range value.
V02_FULL = {
    "schema_version": "0.2", "seed": 4294967295, "variants": 8, "bpm": 200, "sample_rate": 44100,
    "bit_depth": 16, "length_ms": 2000, "pitch_start_hz": 600, "pitch_end_hz": 120,
    "pitch_decay_ms": 300, "amp_attack_ms": 20, "amp_decay_ms": 2000, "click_level": 1,
    "click_tone_hz": 12000, "drive": 1, "tone": -1, "peak_ceiling_dbfs": -12, "preset": "x",
}


def _kick_validator() -> Draft202012Validator:
    return Draft202012Validator(load("kick-params.schema.json"))


def _valid(doc: dict) -> bool:
    return _kick_validator().is_valid(doc)


def test_kick_params_v03_fields_and_defaults_are_as_designed() -> None:
    branch = load("kick-params.schema.json")["allOf"][0]
    assert branch["if"] == {"properties": {"schema_version": {"const": "0.3"}}}
    props = branch["then"]["properties"]
    assert set(props) == set(V03_FIELDS)
    for name, (lo, hi, default) in V03_NUMBERS.items():
        assert (props[name]["minimum"], props[name]["maximum"]) == (lo, hi), name
        assert props[name].get("default") == default, name
    assert props["polarity"] == {**props["polarity"], "enum": [1, -1], "default": 1}
    # None of them is a top-level property: the engine fills those defaults into every sidecar.
    assert not set(V03_FIELDS) & set(load("kick-params.schema.json")["properties"])


def test_kick_params_v03_defaults_are_todays_engine_constants() -> None:
    """The defaults keep today's renders: they equal the fixed values of engine 0.1.0."""
    from audio_engine import kick

    assert (kick.CLICK_DECAY_MS, kick.CLICK_Q, kick.CLICK_LENGTH_MS) == (3.0, 0.9, 15.0)
    props = load("kick-params.schema.json")["allOf"][0]["then"]["properties"]
    assert props["click_decay_ms"]["default"] == kick.CLICK_DECAY_MS
    assert props["click_q"]["default"] == kick.CLICK_Q
    assert max(15, 5 * props["click_decay_ms"]["default"]) == kick.CLICK_LENGTH_MS


KICK_V03_VALID = {
    "0.2 minimal": V02,
    "0.2 every field": V02_FULL,
    "0.3 minimal": V03,
    "0.3 every 0.2 field": {**V02_FULL, "schema_version": "0.3"},
    "0.3 every v0.3 field at its minimum": {
        **V03, "bpm": 180, "tail_note": 23, "length_beats": 0.25, "click_decay_ms": 0.5,
        "click_q": 0.5, "polarity": -1, "offset_ms": 0, "clip_db": 0,
    },
    "0.3 every v0.3 field at its maximum": {
        **V03, "bpm": 120, "tail_note": 46, "length_beats": 4, "click_decay_ms": 12,
        "click_q": 8, "polarity": 1, "offset_ms": 12, "clip_db": 12,
    },
    "0.3 tail_note with pitch_start_hz": {**V03, "tail_note": 33, "pitch_start_hz": 200},
    "0.3 length_beats with bpm": {**V03, "length_beats": 1, "bpm": 128},
    "0.3 polarity -1": {**V03, "polarity": -1},
    "0.3 whole-number float note": {**V03, "tail_note": 33.0},
}


@pytest.mark.parametrize("doc", KICK_V03_VALID.values(), ids=KICK_V03_VALID)
def test_kick_params_valid_instances(doc: dict) -> None:
    _kick_validator().validate(doc)


KICK_V03_INVALID = {
    **{f"0.2 with {f}": {**V02, f: V03_NUMBERS.get(f, (1,))[0]} for f in V03_FIELDS},
    **{f"0.3 {f} below minimum": {**V03, "bpm": 120, f: lo - (1 if f == "tail_note" else 1e-6)}
       for f, (lo, _, _) in V03_NUMBERS.items()},
    **{f"0.3 {f} above maximum": {**V03, "bpm": 120, f: hi + (1 if f == "tail_note" else 1e-6)}
       for f, (_, hi, _) in V03_NUMBERS.items()},
    **{f"0.3 {f} as string": {**V03, "bpm": 120, f: "1"} for f in V03_FIELDS},
    "0.3 tail_note not whole": {**V03, "tail_note": 33.5},
    "0.3 tail_note with pitch_end_hz": {**V03, "tail_note": 33, "pitch_end_hz": 55},
    "0.3 length_beats without bpm": {**V03, "length_beats": 1},
    "0.3 length_beats with length_ms": {**V03, "length_beats": 1, "bpm": 128, "length_ms": 450},
    "0.3 polarity 0": {**V03, "polarity": 0},
    "0.3 polarity 2": {**V03, "polarity": 2},
    "0.3 polarity true": {**V03, "polarity": True},
    "0.3 polarity -0.5": {**V03, "polarity": -0.5},
    "0.3 unknown field": {**V03, "wobble": 3},
    "0.3 0.2 field out of range": {**V03, "drive": 1.02},
    "0.3 without seed": {"schema_version": "0.3"},
    "schema_version 0.1": {**V02, "schema_version": "0.1"},
    "schema_version 0.4": {**V02, "schema_version": "0.4"},
    "schema_version as number": {**V02, "schema_version": 0.3},
}


@pytest.mark.parametrize("doc", KICK_V03_INVALID.values(), ids=KICK_V03_INVALID)
def test_kick_params_invalid_instances(doc: dict) -> None:
    assert not _valid(doc)


def test_kick_params_v03_random_values_over_the_whole_range() -> None:
    """Seeded property test: in-range draws of every v0.3 field pass, draws just outside fail."""
    rng = random.Random(104)
    for _ in range(400):
        doc = dict(V03)
        for name, (lo, hi, _) in V03_NUMBERS.items():
            if rng.random() < 0.5:
                continue
            doc[name] = rng.randint(lo, hi) if name == "tail_note" else rng.uniform(lo, hi)
        if "length_beats" in doc:
            doc["bpm"] = rng.uniform(60, 200)
        if rng.random() < 0.5:
            doc["polarity"] = rng.choice([1, -1])
        assert _valid(doc), doc
        name, (lo, hi, _) = rng.choice(sorted(V03_NUMBERS.items()))
        step = rng.choice([1e-6, 1e-3, 1.0, 100.0]) * rng.uniform(1.0, 2.0)
        outside = rng.choice([lo - step, hi + step])
        assert not _valid({**doc, "bpm": 120, name: outside}), (name, outside)


# Resolved form (review of PR #114, problem 1). Written by hand from the contract text: every
# default filled, tail_note -> pitch_end_hz, length_beats -> length_ms, derived amp_decay_ms
# stored as amp_decay_ms. Applied here by hand, independent of the engine (PR #130 renders 0.3).
V02_DEFAULTS = {
    "variants": 1, "sample_rate": 48000, "bit_depth": 24, "length_ms": 450,
    "pitch_start_hz": 220, "pitch_end_hz": 48, "pitch_decay_ms": 15, "amp_attack_ms": 0.5,
    "amp_decay_ms": 320, "click_level": 0.35, "click_tone_hz": 3500, "drive": 0.2, "tone": 0,
    "peak_ceiling_dbfs": -0.3,
}
V03_DEFAULTS = {"click_decay_ms": 3, "click_q": 0.9, "polarity": 1, "offset_ms": 0, "clip_db": 0}


def _resolve_by_contract(request: dict, derived_decay_ms: float | None = None) -> dict:
    out = dict(request)
    if "tail_note" in out:
        out["pitch_end_hz"] = 440.0 * 2.0 ** ((out.pop("tail_note") - 69) / 12)
    if "length_beats" in out:
        out["length_ms"] = out.pop("length_beats") * 60000.0 / out["bpm"]
        if "amp_decay_ms" not in out:
            out["amp_decay_ms"] = derived_decay_ms
    for key, value in {**V02_DEFAULTS, **V03_DEFAULTS}.items():
        out.setdefault(key, value)
    return out


def test_kick_params_resolved_v03_instance_validates() -> None:
    request = {**V03, "tail_note": 33, "length_beats": 1, "bpm": 128, "polarity": -1}
    resolved = _resolve_by_contract(request, derived_decay_ms=401.3)
    assert resolved["pitch_end_hz"] == 55.0  # note 33 = A1
    assert resolved["length_ms"] == 468.75  # one beat at 128 BPM
    assert "tail_note" not in resolved and "length_beats" not in resolved
    _kick_validator().validate(resolved)
    # Resolving the resolved form again changes nothing (re-render without a new derivation).
    assert _resolve_by_contract(resolved) == resolved
    # The other design (input kept next to the filled default) is not a valid resolved form.
    assert not _valid({**resolved, "tail_note": 33})
    assert not _valid({**resolved, "length_beats": 1})


def test_kick_params_resolved_form_is_valid_over_the_whole_range() -> None:
    """Seeded: every v0.3 request (inside the ranges the engine accepts) resolves, by the
    contract's rule, to a valid instance that holds no input field and recovers the inputs."""
    rng = random.Random(1142)
    for _ in range(400):
        request = dict(V03)
        if rng.random() < 0.7:
            request["tail_note"] = rng.randint(23, 46)
        if rng.random() < 0.7:
            request["bpm"] = rng.uniform(60, 200)
            lo, hi = max(0.25, 80 * request["bpm"] / 60000), min(4, 2000 * request["bpm"] / 60000)
            request["length_beats"] = rng.uniform(lo, hi)
            if rng.random() < 0.5:
                request["amp_decay_ms"] = rng.uniform(20, 2000)
        for name in ("click_decay_ms", "click_q", "offset_ms", "clip_db"):
            if rng.random() < 0.5:
                lo, hi, _ = V03_NUMBERS[name]
                request[name] = rng.uniform(lo, hi)
        if rng.random() < 0.5:
            request["polarity"] = rng.choice([1, -1])
        assert _valid(request), request
        resolved = _resolve_by_contract(request, derived_decay_ms=rng.uniform(20, 2000))
        assert _valid(resolved), (request, resolved)
        assert not {"tail_note", "length_beats"} & set(resolved)
        if "tail_note" in request:
            note = 69 + 12 * math.log2(resolved["pitch_end_hz"] / 440)
            assert abs(note - request["tail_note"]) < 1e-9
        if "length_beats" in request:
            beats = resolved["length_ms"] * resolved["bpm"] / 60000
            assert math.isclose(beats, request["length_beats"], rel_tol=1e-12)


def test_kick_params_v03_rules_are_written_exactly() -> None:
    """The resolved form and the -60 dB rule are contract text the engine (#120) implements;
    pin every number and choice so a silent edit shows up here."""
    schema = load("kick-params.schema.json")
    root = schema["description"]
    for phrase in (
        "tail_note is replaced by the derived pitch_end_hz",
        "length_beats by the derived length_ms",
        "an amp_decay_ms derived under length_beats is stored as amp_decay_ms",
        "never contains tail_note or length_beats",
    ):
        assert phrase in root, phrase
    rule = schema["allOf"][0]["then"]["properties"]["length_beats"]["description"]
    for phrase in (
        "the samples written to the WAV (after quantisation",
        "rectangular RMS over N = sample_rate // 200 samples (240 at 48 kHz, 220 at 44.1 kHz)",
        "hop 1 sample",
        "i_max = the first i with r[i] = R",
        "T60 = (i60 + N) / sample_rate, the END of the first window i60 > i_max",
        "20 * log10(r[i60] / R) <= -60",
        "T60 <= (n - n_fade) / sample_rate",
        "the end fade-out never counts",
        "rejected, never shortened",
        "k = 0 ... 19800, value round(20 + k / 10, 1)",
        "2000.0 fits -> 2000.0; 20.0 does not fit -> rejected",
        "lo = 0, hi = 19800, while hi - lo > 1: mid = (lo + hi) // 2, lo = mid if mid fits",
        "result k = lo",
    ):
        assert phrase in rule, phrase
    assert (48000 // 200, 44100 // 200, round((2000 - 20) / 0.1)) == (240, 220, 19800)
    for name, default in (("pitch_end_hz", 48), ("length_ms", 450), ("amp_decay_ms", 320)):
        text = schema["properties"][name]["description"]
        assert f"the default {default} is not used" in text, name


def test_kick_params_old_sidecars_still_validate() -> None:
    """Parameters of a 0.2 sidecar written by today's engine, of every preset, and of the 0.1
    fixture sidecar after the documented 0.1 -> 0.2 upgrade (INTERFACES.md) still validate."""
    from audio_engine.kick import render_kick
    from audio_engine.presets import load_preset, preset_names

    validator = _kick_validator()
    _, resolved = render_kick({"schema_version": "0.2", "seed": 7, "bpm": 128})
    validator.validate(resolved)
    for name in preset_names():
        validator.validate(load_preset(name))
    fixture = ROOT / "tests" / "fixtures" / "sidecars" / "kick-v01.json"
    params = json.loads(fixture.read_text(encoding="utf-8"))["parameters"]
    assert params["schema_version"] == "0.1" and "pitch_decay_ms" in params
    assert not validator.is_valid(params)
    validator.validate({**params, "schema_version": "0.2"})


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
