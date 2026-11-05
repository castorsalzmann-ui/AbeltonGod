"""laser-params v0.1 and category `laser` in sample-metadata v0.2 (#416, D-030).

Expected ranges are written out here by hand, not read from the schema, so a changed range in
the contract turns a test red and has to be changed on purpose.
"""

import copy
import json
import random
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts"


def load(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


LASER = load("laser-params.schema.json")
LASER_V = Draft202012Validator(LASER)
META_V = Draft202012Validator(load("sample-metadata.schema.json"))
BASE = {"schema_version": "0.1", "seed": 1}

# name: (minimum, maximum, default)
LASER_RANGES = {
    "length_ms": (100, 3000, 500),
    "pitch_start_hz": (40, 8000, 3000),
    "pitch_end_hz": (40, 8000, 200),
    "sweep_ms": (10, 2000, 150),
    "sweep_curve": (0.2, 6, 1),
    "attack_ms": (0, 50, 0.5),
    "decay_ms": (20, 3000, 250),
    "fm_amount": (0, 1, 0),
    "fm_ratio": (0.25, 4, 1.5),
    "ring_amount": (0, 1, 0),
    "ring_hz": (20, 4000, 440),
    "noise_level": (0, 1, 0),
    "noise_hz": (200, 12000, 4000),
    "crackle": (0, 1, 0),
    "glitch_steps": (2, 24, 8),
    "echo_mix": (0, 1, 0),
    "echo_ms": (20, 500, 120),
    "echo_feedback": (0, 0.9, 0.4),
    "stereo_width": (0, 1, 0),
    "variation": (0, 1, 0),
    "drive": (0, 1, 0),
    "offset_ms": (0, 12, 0),
    "peak_ceiling_dbfs": (-12, -0.1, -0.3),
    "bpm": (60, 200, None),
}
FAMILIES = ["pew", "plasma", "ion", "rift", "subboom", "glitch"]
LASER_FIELDS = {
    "schema_version", "seed", "variants", "sample_rate", "bit_depth", "polarity", "preset",
    "family", *LASER_RANGES,
}


def test_laser_field_set_and_required() -> None:
    assert set(LASER["properties"]) == LASER_FIELDS
    assert LASER["required"] == ["schema_version", "seed"]
    assert LASER["additionalProperties"] is False


@pytest.mark.parametrize("name", sorted(LASER_RANGES))
def test_laser_range_matches_table_and_edges(name: str) -> None:
    low, high, default = LASER_RANGES[name]
    prop = LASER["properties"][name]
    assert (prop["minimum"], prop["maximum"], prop.get("default")) == (low, high, default)
    for ok in (low, high):
        LASER_V.validate({**BASE, name: ok})
    span = high - low
    for bad in (low - span / 100, high + span / 100):
        with pytest.raises(ValidationError):
            LASER_V.validate({**BASE, name: bad})


def test_laser_random_values_inside_and_outside_range() -> None:
    rng = random.Random(416)
    for _ in range(400):
        name = rng.choice(sorted(set(LASER_RANGES) - {"glitch_steps"}))
        low, high, _default = LASER_RANGES[name]
        span = high - low
        LASER_V.validate({**BASE, name: rng.uniform(low, high)})
        excess = rng.uniform(0.001, 1) * span
        with pytest.raises(ValidationError):
            LASER_V.validate({**BASE, name: rng.choice((low - excess, high + excess))})


def test_laser_discrete_fields() -> None:
    good = {"variants": [1, 8], "sample_rate": [44100, 48000], "bit_depth": [16, 24],
            "polarity": [1, -1], "seed": [0, 4294967295], "family": FAMILIES,
            "glitch_steps": [2, 24]}
    bad = {"variants": [0, 9], "sample_rate": [96000], "bit_depth": [32], "polarity": [0, 2],
           "seed": [-1, 4294967296, 1.5], "family": ["laser", "Pew", "", 3],
           "glitch_steps": [1, 25, 8.5]}
    for name, values in good.items():
        for v in values:
            LASER_V.validate({**BASE, name: v})
    for name, values in bad.items():
        for v in values:
            with pytest.raises(ValidationError):
                LASER_V.validate({**BASE, name: v})
    assert LASER["properties"]["family"]["enum"] == FAMILIES
    assert LASER["properties"]["family"]["default"] == "pew"


def test_laser_required_version_and_unknown_fields() -> None:
    LASER_V.validate(BASE)
    for doc in ({"seed": 1}, {"schema_version": "0.1"}, {"schema_version": "0.2", "seed": 1},
                {**BASE, "wobble": 1}, {**BASE, "model": "pew"}, {**BASE, "width": 1}):
        with pytest.raises(ValidationError):
            LASER_V.validate(doc)


def test_every_combination_of_extremes_is_schema_valid() -> None:
    """The contract states there is no cross-field rule."""
    rng = random.Random(7)
    for _ in range(200):
        doc = dict(BASE)
        for name, (low, high, _d) in LASER_RANGES.items():
            if name != "glitch_steps":
                doc[name] = rng.choice((low, high))
        doc["family"] = rng.choice(FAMILIES)
        LASER_V.validate(doc)
    assert "No cross-field rule" in LASER["$comment"]


def test_contract_text_fixes_the_agreed_definitions() -> None:
    text = LASER["$comment"]
    for needle in ("time to fall 60 dB after the attack", "Reject out-of-range values, never clamp",
                   "abeltongod-audio-engine-laser", "5 ms fade-out", "byte-identical",
                   "seed-independent", "exactly round(length_ms * sample_rate / 1000)",
                   "QUANTISED", "ping-pong", "0.45", "mid signal"):
        assert needle in text, needle
    for family in FAMILIES:
        assert f"`{family}`" in text, family
    desc = LASER["description"]
    for needle in ("(n, 2)", "PROPOSALS", "No claim is made"):
        assert needle in desc, needle


def test_shared_fields_have_the_same_definition_as_rim_and_kick_params() -> None:
    rim = load("rim-params.schema.json")["properties"]

    def core(prop: dict) -> dict:
        return {k: v for k, v in prop.items() if k != "description"}

    for name in ("seed", "variants", "bpm", "sample_rate", "bit_depth", "drive", "polarity",
                 "offset_ms", "peak_ceiling_dbfs", "preset"):
        assert core(LASER["properties"][name]) == core(rim[name]), name


# --- sample-metadata: category laser -----------------------------------------------------------

LASER_DOC = {
    "schema_version": "0.2", "file": "laser.wav", "category": "laser",
    "engine": {"name": "abeltongod-audio-engine-laser", "version": "0.1.0"},
    "parameters": {"schema_version": "0.1", "seed": 7},
    "features": {
        "peak_dbfs": -0.3, "length_ms": 500.0, "spectral_centroid_hz": 2500.0,
        "t60_ms": 200.0, "rise_time_ms": 0.5,
    },
    "created_at": "2026-11-05T12:00:00+00:00",
}


def _changed(path: str, value) -> dict:
    doc = copy.deepcopy(LASER_DOC)
    node = doc
    *parents, last = path.split(".")
    for key in parents:
        node = node[key]
    if value is ...:
        del node[last]
    else:
        node[last] = value
    return doc


def test_metadata_laser_and_other_categories_still_validate() -> None:
    META_V.validate(LASER_DOC)
    META_V.validate(json.loads((ROOT / "tests/fixtures/sidecars/kick-v01.json").read_text("utf-8")))
    for category, engine in (("rim", "abeltongod-audio-engine-rim"),
                             ("bass", "abeltongod-audio-engine-bass"),
                             ("clap", "abeltongod-audio-engine-clap")):
        doc = copy.deepcopy(LASER_DOC)
        doc.update(category=category, file=f"{category}.wav")
        doc["engine"]["name"] = engine
        META_V.validate(doc)


METADATA_INVALID = {
    "laser with schema_version 0.1": _changed("schema_version", "0.1"),
    "laser with the kick engine name": _changed("engine.name", "abeltongod-audio-engine"),
    "laser with the rim engine name": _changed("engine.name", "abeltongod-audio-engine-rim"),
    "laser parameters without seed": _changed("parameters.seed", ...),
    "laser parameters with kick-params version": _changed("parameters.schema_version", "0.3"),
    "category lasers": _changed("category", "lasers"),
}


@pytest.mark.parametrize("doc", METADATA_INVALID.values(), ids=METADATA_INVALID)
def test_metadata_laser_invalid_instances(doc) -> None:
    with pytest.raises(ValidationError):
        META_V.validate(doc)


@pytest.mark.parametrize("category", ["clap", "hat", "snare", "rim", "bass"])
def test_laser_engine_name_is_refused_for_other_categories(category: str) -> None:
    doc = copy.deepcopy(LASER_DOC)
    doc["category"] = category
    with pytest.raises(ValidationError):
        META_V.validate(doc)
