"""clap-params v0.1 and the category generalisation of sample-metadata v0.2 (#229).

Expected ranges are written out here by hand, not read from the schema, so a changed range in
the contract turns a test red and has to be changed on purpose.
"""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts"


def load(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


CLAP = load("clap-params.schema.json")
CLAP_V = Draft202012Validator(CLAP)
META_V = Draft202012Validator(load("sample-metadata.schema.json"))

# name: (minimum, maximum, default), numbers as proposed in #229.
CLAP_RANGES = {
    "length_ms": (200, 2000, 500),
    "burst_spacing_ms": (3, 30, 11),
    "burst_decay_ms": (5, 60, 23),
    "burst_level_falloff": (0.5, 1, 0.85),
    "tail_level": (0, 1, 0.7),
    "tail_decay_ms": (40, 800, 200),
    "bp_hz": (500, 4000, 1300),
    "bp_q": (0.5, 8, 1.4),
    "hp_hz": (100, 2000, 450),
    "room": (0, 1, 0),
    "room_length_ms": (100, 800, 400),
    "drive": (0, 1, 0),
    "offset_ms": (0, 12, 0),
    "peak_ceiling_dbfs": (-12, -0.1, -0.3),
    "bpm": (60, 200, None),
}
CLAP_FIELDS = {
    "schema_version", "seed", "variants", "sample_rate", "bit_depth", "bursts", "polarity",
    "preset", *CLAP_RANGES,
}


def test_clap_field_set_and_required() -> None:
    assert set(CLAP["properties"]) == CLAP_FIELDS
    assert CLAP["required"] == ["schema_version", "seed"]


@pytest.mark.parametrize("name", sorted(CLAP_RANGES))
def test_clap_range_matches_table_and_edges(name: str) -> None:
    low, high, default = CLAP_RANGES[name]
    prop = CLAP["properties"][name]
    assert (prop["minimum"], prop["maximum"], prop.get("default")) == (low, high, default)
    base = {"schema_version": "0.1", "seed": 1}
    for ok in (low, high):
        CLAP_V.validate({**base, name: ok})
    span = high - low
    for bad in (low - span / 100, high + span / 100):
        with pytest.raises(ValidationError):
            CLAP_V.validate({**base, name: bad})


def test_clap_discrete_fields() -> None:
    base = {"schema_version": "0.1", "seed": 1}
    good = {"bursts": [1, 6], "variants": [1, 8], "sample_rate": [44100, 48000],
            "bit_depth": [16, 24], "polarity": [1, -1], "seed": [0, 4294967295]}
    bad = {"bursts": [0, 7, 2.5], "variants": [0, 9], "sample_rate": [96000],
           "bit_depth": [32], "polarity": [0, 2], "seed": [-1, 4294967296, 1.5]}
    for name, values in good.items():
        for v in values:
            CLAP_V.validate({**base, name: v})
    for name, values in bad.items():
        for v in values:
            with pytest.raises(ValidationError):
                CLAP_V.validate({**base, name: v})


def test_clap_required_version_and_unknown_fields() -> None:
    CLAP_V.validate({"schema_version": "0.1", "seed": 0})
    for doc in ({"seed": 1}, {"schema_version": "0.1"}, {"schema_version": "0.2", "seed": 1},
                {"schema_version": "0.1", "seed": 1, "wobble": 1},
                {"schema_version": "0.1", "seed": 1, "voice": "snare"}):
        with pytest.raises(ValidationError):
            CLAP_V.validate(doc)


def test_clap_longest_burst_onset_fits_minimum_length() -> None:
    """The contract has no cross-field rule because this inequality holds for the whole range."""
    p = CLAP["properties"]
    span = (p["bursts"]["maximum"] - 1) * p["burst_spacing_ms"]["maximum"]
    assert span < p["length_ms"]["minimum"]


def test_shared_fields_have_the_same_definition_as_kick_params() -> None:
    """Drift check: fields the clap copies from kick-params must not diverge."""
    kick = load("kick-params.schema.json")
    kick_props = {**kick["properties"], **kick["allOf"][0]["then"]["properties"]}

    def core(prop: dict) -> dict:
        return {k: v for k, v in prop.items() if k != "description"}

    for name in ("seed", "variants", "sample_rate", "bit_depth", "peak_ceiling_dbfs",
                 "preset", "polarity", "offset_ms"):
        assert core(CLAP["properties"][name]) == core(kick_props[name]), name
    for key in ("type", "minimum", "maximum"):
        assert CLAP["properties"]["bpm"][key] == kick_props["bpm"][key]


# --- sample-metadata v0.2 ---------------------------------------------------------------------

KICK_DOC = {
    "schema_version": "0.1", "file": "kick.wav", "category": "kick",
    "engine": {"name": "abeltongod-audio-engine", "version": "0.1.0"},
    "parameters": {"schema_version": "0.3", "seed": 7},
    "features": {"peak_dbfs": -0.3, "length_ms": 450.0, "fundamental_hz": 48.6},
    "created_at": "2026-11-02T12:00:00+00:00",
}
CLAP_DOC = {
    "schema_version": "0.2", "file": "clap.wav", "category": "clap",
    "engine": {"name": "abeltongod-audio-engine-clap", "version": "0.1.0"},
    "parameters": {"schema_version": "0.1", "seed": 7},
    "features": {
        "peak_dbfs": -0.3, "length_ms": 500.0, "spectral_centroid_hz": 2100.5,
        "hf_share_8k": 0.12, "t60_ms": 240.0, "rise_time_ms": 0.4, "fundamental_hz": None,
    },
    "created_at": "2026-11-02T12:00:00+00:00",
}


def _changed(base: dict, path: str, value) -> dict:
    doc = copy.deepcopy(base)
    node = doc
    *parents, last = path.split(".")
    for key in parents:
        node = node[key]
    if value is ...:
        del node[last]
    else:
        node[last] = value
    return doc


def test_metadata_valid_instances() -> None:
    META_V.validate(KICK_DOC)
    META_V.validate(CLAP_DOC)
    # Non-pitched features may be absent: only peak and length are required.
    META_V.validate(_changed(CLAP_DOC, "features", {"peak_dbfs": -6.0, "length_ms": 300.0}))
    # Kick sidecar fixture from before this change.
    META_V.validate(json.loads((ROOT / "tests/fixtures/sidecars/kick-v01.json").read_text("utf-8")))


METADATA_INVALID = {
    "clap with schema_version 0.1": _changed(CLAP_DOC, "schema_version", "0.1"),
    "clap with the kick engine name": _changed(CLAP_DOC, "engine.name", "abeltongod-audio-engine"),
    "clap parameters without seed": _changed(CLAP_DOC, "parameters.seed", ...),
    "clap parameters with kick-params version": _changed(
        CLAP_DOC, "parameters.schema_version", "0.3"),
    "category snare not allowed": _changed(CLAP_DOC, "category", "snare"),
    "category snare": _changed(KICK_DOC, "category", "snare"),
    "kick with schema_version 0.2": _changed(KICK_DOC, "schema_version", "0.2"),
    "schema_version 0.3": _changed(CLAP_DOC, "schema_version", "0.3"),
    "hf_share above 1": _changed(CLAP_DOC, "features.hf_share_8k", 1.5),
    "negative centroid": _changed(CLAP_DOC, "features.spectral_centroid_hz", -1),
    "t60 as string": _changed(CLAP_DOC, "features.t60_ms", "240"),
    "unknown feature": _changed(CLAP_DOC, "features.loudness", -9.0),
}


@pytest.mark.parametrize("doc", METADATA_INVALID.values(), ids=METADATA_INVALID)
def test_metadata_invalid_instances(doc) -> None:
    with pytest.raises(ValidationError):
        META_V.validate(doc)


def test_kick_engine_constants_match_the_contract_text() -> None:
    """Drift: the kick engine name in code is the one the contract text and the clap rule
    distinguish from; the description limit in the CLI equals the schema's maxLength."""
    from audio_engine import ENGINE_NAME
    from audio_engine.cli import MAX_DESCRIPTION

    meta = load("sample-metadata.schema.json")
    assert f"'{ENGINE_NAME}'" in meta["description"]
    clap_name = meta["allOf"][1]["then"]["properties"]["engine"]["properties"]["name"]["const"]
    assert clap_name == ENGINE_NAME + "-clap"
    assert meta["properties"]["description"]["maxLength"] == MAX_DESCRIPTION
