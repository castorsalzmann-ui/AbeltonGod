"""rim-params v0.1 and category `rim` in sample-metadata v0.2 (#296).

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


RIM = load("rim-params.schema.json")
RIM_V = Draft202012Validator(RIM)
META_V = Draft202012Validator(load("sample-metadata.schema.json"))
BASE = {"schema_version": "0.1", "seed": 1}

# name: (minimum, maximum, default); numbers from docs/research/2026-11-02_rim-targets.md
# sections 2 and 5 (hypotheses / proposals).
RIM_RANGES = {
    "length_ms": (50, 600, 200),
    "f1_hz": (300, 3500, 455),
    "f2_ratio": (2.0, 5.0, 3.66),
    "level2": (0, 1, 0.6),
    "decay1_ms": (5, 120, 40),
    "decay2_ms": (5, 120, 15),
    "hp_hz": (200, 6000, 200),
    "click_level": (0, 1, 0.2),
    "click_ms": (0.2, 3, 1),
    "drive": (0, 1, 0),
    "offset_ms": (0, 12, 0),
    "peak_ceiling_dbfs": (-12, -0.1, -0.3),
    "bpm": (60, 200, None),
}
RIM_FIELDS = {
    "schema_version", "seed", "variants", "sample_rate", "bit_depth", "polarity", "preset",
    *RIM_RANGES,
}


def test_rim_field_set_and_required() -> None:
    assert set(RIM["properties"]) == RIM_FIELDS
    assert RIM["required"] == ["schema_version", "seed"]
    # deferred in v0.1 (weak or absent evidence, or lead decision): NOT fields
    for absent in ("f3_ratio", "bend", "tone_peak_hz", "tone_peak_db", "model", "voice"):
        assert absent not in RIM["properties"]


@pytest.mark.parametrize("name", sorted(RIM_RANGES))
def test_rim_range_matches_table_and_edges(name: str) -> None:
    low, high, default = RIM_RANGES[name]
    prop = RIM["properties"][name]
    assert (prop["minimum"], prop["maximum"], prop.get("default")) == (low, high, default)
    for ok in (low, high):
        RIM_V.validate({**BASE, name: ok})
    span = high - low
    for bad in (low - span / 100, high + span / 100):
        with pytest.raises(ValidationError):
            RIM_V.validate({**BASE, name: bad})


def test_rim_random_values_inside_and_outside_range() -> None:
    rng = random.Random(296)
    for _ in range(300):
        name = rng.choice(sorted(RIM_RANGES))
        low, high, _default = RIM_RANGES[name]
        span = high - low
        RIM_V.validate({**BASE, name: rng.uniform(low, high)})
        excess = rng.uniform(0.001, 1) * span
        outside = rng.choice((low - excess, high + excess))
        with pytest.raises(ValidationError):
            RIM_V.validate({**BASE, name: outside})


def test_rim_discrete_fields() -> None:
    good = {"variants": [1, 8], "sample_rate": [44100, 48000], "bit_depth": [16, 24],
            "polarity": [1, -1], "seed": [0, 4294967295]}
    bad = {"variants": [0, 9], "sample_rate": [96000], "bit_depth": [32], "polarity": [0, 2],
           "seed": [-1, 4294967296, 1.5]}
    for name, values in good.items():
        for v in values:
            RIM_V.validate({**BASE, name: v})
    for name, values in bad.items():
        for v in values:
            with pytest.raises(ValidationError):
                RIM_V.validate({**BASE, name: v})


def test_rim_required_version_and_unknown_fields() -> None:
    RIM_V.validate(BASE)
    for doc in ({"seed": 1}, {"schema_version": "0.1"}, {"schema_version": "0.2", "seed": 1},
                {**BASE, "wobble": 1}, {**BASE, "f3_ratio": 6}, {**BASE, "bend": 1.2},
                {**BASE, "model": "clave"}):
        with pytest.raises(ValidationError):
            RIM_V.validate(doc)


def test_cross_field_rule_is_stated_and_omitted_partner_behaves_as_documented() -> None:
    text = RIM["$comment"] + RIM["properties"]["hp_hz"]["description"]
    assert "hp_hz must be less than 0.8 * f1_hz" in text
    f1_lo, _f1_hi, f1_def = RIM_RANGES["f1_hz"][0], RIM_RANGES["f1_hz"][1], RIM_RANGES["f1_hz"][2]
    hp_def = RIM_RANGES["hp_hz"][2]
    assert hp_def < 0.8 * f1_lo  # default hp never breaks the rule for any f1_hz
    assert 0.8 * f1_def == pytest.approx(364)  # documented: explicit hp_hz >= 364 breaks default f1
    # The schema alone accepts a violating pair; the engine must refuse it.
    RIM_V.validate({**BASE, "f1_hz": 300, "hp_hz": 6000})


def test_highest_partial_stays_below_0_45_nyquist() -> None:
    """The $comment says no cross-field rule is needed for the upper partial."""
    top = RIM_RANGES["f1_hz"][1] * RIM_RANGES["f2_ratio"][1]
    assert top == 17500
    assert top < 0.45 * 44100


def test_contract_text_fixes_the_agreed_definitions() -> None:
    text = RIM["$comment"]
    for needle in ("level2 0 means no upper partial", "time to -60 dB after the attack",
                   "phase 0", "the seed changes only the click", "seed-independent",
                   "Reject out-of-range values, never clamp", "Defaults are placeholders",
                   "abeltongod-audio-engine-rim", "5 ms linear fade-out",
                   "click_level 0 means no click", "own sub-stream"):
        assert needle in text, needle
    desc = RIM["description"]
    for needle in ("PROPOSALS", "one hobby page", "`f3_ratio`", "`bend`"):
        assert needle in desc, needle


def test_shared_fields_have_the_same_definition_as_clap_and_kick_params() -> None:
    clap = load("clap-params.schema.json")["properties"]
    kick = load("kick-params.schema.json")
    kick_props = {**kick["properties"], **kick["allOf"][0]["then"]["properties"]}

    def core(prop: dict) -> dict:
        return {k: v for k, v in prop.items() if k != "description"}

    assert RIM["properties"]["schema_version"] == {"const": "0.1"}  # clap: 0.1 or 0.2 (#280)
    for name in ("seed", "variants", "bpm", "sample_rate", "bit_depth", "drive",
                 "polarity", "offset_ms", "peak_ceiling_dbfs", "preset"):
        assert core(RIM["properties"][name]) == core(clap[name]), name
    for name in ("seed", "variants", "sample_rate", "bit_depth", "peak_ceiling_dbfs",
                 "preset", "polarity", "offset_ms"):
        assert core(RIM["properties"][name]) == core(kick_props[name]), name


# --- sample-metadata: category rim -------------------------------------------------------------

RIM_DOC = {
    "schema_version": "0.2", "file": "rim.wav", "category": "rim",
    "engine": {"name": "abeltongod-audio-engine-rim", "version": "0.1.0"},
    "parameters": {"schema_version": "0.1", "seed": 7},
    "features": {
        "peak_dbfs": -0.3, "length_ms": 200.0, "spectral_centroid_hz": 2500.0,
        "t60_ms": 60.0, "rise_time_ms": 0.5, "fundamental_hz": None,
    },
    "created_at": "2026-11-02T12:00:00+00:00",
}


def _changed(path: str, value, base: dict = RIM_DOC) -> dict:
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


def test_metadata_rim_and_other_categories_still_validate() -> None:
    META_V.validate(RIM_DOC)
    META_V.validate(json.loads((ROOT / "tests/fixtures/sidecars/kick-v01.json").read_text("utf-8")))
    for category, engine in (("clap", "abeltongod-audio-engine-clap"),
                             ("hat", "abeltongod-audio-engine-hat"),
                             ("snare", "abeltongod-audio-engine-snare")):
        doc = copy.deepcopy(RIM_DOC)
        doc.update(category=category, file=f"{category}.wav")
        doc["engine"]["name"] = engine
        META_V.validate(doc)
    kick = copy.deepcopy(RIM_DOC)
    kick.update(category="kick", schema_version="0.1", file="kick.wav")
    kick["engine"]["name"] = "abeltongod-audio-engine"
    META_V.validate(kick)


METADATA_INVALID = {
    "rim with schema_version 0.1": _changed("schema_version", "0.1"),
    "rim with the kick engine name": _changed("engine.name", "abeltongod-audio-engine"),
    "rim with the clap engine name": _changed("engine.name", "abeltongod-audio-engine-clap"),
    "rim with the hat engine name": _changed("engine.name", "abeltongod-audio-engine-hat"),
    "rim with the snare engine name": _changed("engine.name", "abeltongod-audio-engine-snare"),
    "rim parameters without seed": _changed("parameters.seed", ...),
    "rim parameters with kick-params version": _changed("parameters.schema_version", "0.3"),
    "category perc": _changed("category", "perc"),
}


@pytest.mark.parametrize("doc", METADATA_INVALID.values(), ids=METADATA_INVALID)
def test_metadata_rim_invalid_instances(doc) -> None:
    with pytest.raises(ValidationError):
        META_V.validate(doc)


@pytest.mark.parametrize("category", ["clap", "hat", "snare"])
def test_rim_engine_name_is_refused_for_other_categories(category: str) -> None:
    doc = copy.deepcopy(RIM_DOC)
    doc["category"] = category
    with pytest.raises(ValidationError):
        META_V.validate(doc)
