"""snare-params v0.1 and category `snare` in sample-metadata v0.2 (#272).

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


SNARE = load("snare-params.schema.json")
SNARE_V = Draft202012Validator(SNARE)
META_V = Draft202012Validator(load("sample-metadata.schema.json"))
BASE = {"schema_version": "0.1", "seed": 1}

# name: (minimum, maximum, default); numbers from
# docs/research/2026-11-02_snare-rim-and-sub-bass-design.md section 2.2 (proposals).
SNARE_RANGES = {
    "length_ms": (100, 1500, 400),
    "body_hz": (120, 400, 190),
    "mode_ratio": (1.5, 2.4, 1.85),
    "pitch_drop": (1.0, 2.0, 1.4),
    "pitch_drop_ms": (3, 60, 25),
    "body_decay_ms": (30, 300, 90),
    "body2_decay_ratio": (0.3, 1.2, 0.7),
    "body_level": (0, 1, 0.6),
    "noise_decay_ms": (60, 800, 180),
    "noise_band_mix": (0, 1, 0.4),
    "noise_hp_hz": (500, 6000, 1800),
    "noise_lp_hz": (3000, 16000, 9000),
    "noise_attack_ms": (0.1, 12, 0.8),
    "tone_peak_hz": (2000, 8000, 5000),
    "tone_peak_db": (-6, 6, 0),
    "drive": (0, 1, 0),
    "offset_ms": (0, 12, 0),
    "peak_ceiling_dbfs": (-12, -0.1, -0.3),
    "bpm": (60, 200, None),
}
SNARE_FIELDS = {
    "schema_version", "seed", "variants", "sample_rate", "bit_depth", "polarity", "preset",
    *SNARE_RANGES,
}


def test_snare_field_set_and_required() -> None:
    assert set(SNARE["properties"]) == SNARE_FIELDS
    assert SNARE["required"] == ["schema_version", "seed"]
    # lead decisions on issue #272: these are NOT fields in v0.1
    for absent in ("snappy", "gate_ms", "body_shape", "model", "voice"):
        assert absent not in SNARE["properties"]


@pytest.mark.parametrize("name", sorted(SNARE_RANGES))
def test_snare_range_matches_table_and_edges(name: str) -> None:
    low, high, default = SNARE_RANGES[name]
    prop = SNARE["properties"][name]
    assert (prop["minimum"], prop["maximum"], prop.get("default")) == (low, high, default)
    for ok in (low, high):
        SNARE_V.validate({**BASE, name: ok})
    span = high - low
    for bad in (low - span / 100, high + span / 100):
        with pytest.raises(ValidationError):
            SNARE_V.validate({**BASE, name: bad})


def test_snare_random_values_inside_and_outside_range() -> None:
    rng = random.Random(272)
    for _ in range(300):
        name = rng.choice(sorted(SNARE_RANGES))
        low, high, _default = SNARE_RANGES[name]
        span = high - low
        SNARE_V.validate({**BASE, name: rng.uniform(low, high)})
        excess = rng.uniform(0.001, 1) * span
        outside = rng.choice((low - excess, high + excess))
        with pytest.raises(ValidationError):
            SNARE_V.validate({**BASE, name: outside})


def test_snare_discrete_fields() -> None:
    good = {"variants": [1, 8], "sample_rate": [44100, 48000], "bit_depth": [16, 24],
            "polarity": [1, -1], "seed": [0, 4294967295]}
    bad = {"variants": [0, 9], "sample_rate": [96000], "bit_depth": [32], "polarity": [0, 2],
           "seed": [-1, 4294967296, 1.5]}
    for name, values in good.items():
        for v in values:
            SNARE_V.validate({**BASE, name: v})
    for name, values in bad.items():
        for v in values:
            with pytest.raises(ValidationError):
                SNARE_V.validate({**BASE, name: v})


def test_snare_required_version_and_unknown_fields() -> None:
    SNARE_V.validate(BASE)
    for doc in ({"seed": 1}, {"schema_version": "0.1"}, {"schema_version": "0.2", "seed": 1},
                {**BASE, "wobble": 1}, {**BASE, "snappy": 0.5}, {**BASE, "gate_ms": 100},
                {**BASE, "body_shape": 0.5}, {**BASE, "model": "rim"}):
        with pytest.raises(ValidationError):
            SNARE_V.validate(doc)


def test_cross_field_rule_is_stated_and_omitted_partner_never_breaks_it() -> None:
    text = SNARE["$comment"] + SNARE["properties"]["noise_lp_hz"]["description"]
    assert "noise_lp_hz must be greater than 1.2 * noise_hp_hz" in text
    hp_lo, hp_hi, hp_def = SNARE_RANGES["noise_hp_hz"]
    lp_lo, lp_hi, lp_def = SNARE_RANGES["noise_lp_hz"]
    assert 1.2 * hp_hi < lp_def  # any hp with the default lp
    assert 1.2 * hp_def < lp_lo  # any lp with the default hp
    # The schema alone accepts a violating pair; the engine must refuse it.
    SNARE_V.validate({**BASE, "noise_hp_hz": 6000, "noise_lp_hz": 3000})
    assert lp_hi < 22050


def test_highest_partial_stays_below_0_45_nyquist() -> None:
    """The $comment says no cross-field rule is needed for the upper partial."""
    top = SNARE_RANGES["body_hz"][1] * SNARE_RANGES["mode_ratio"][1] * SNARE_RANGES["pitch_drop"][1]
    assert top == pytest.approx(1920)
    assert top < 0.45 * 44100


def test_contract_text_fixes_the_agreed_definitions() -> None:
    text = SNARE["$comment"]
    for needle in ("PASSBAND POWER AFTER THE NOISE FILTERS", "follows the pitch drop",
                   "body_hz * mode_ratio", "time to -60 dB after the attack",
                   "the seed changes only the noise", "seed-independent",
                   "Reject out-of-range values, never clamp", "Defaults are placeholders",
                   "abeltongod-audio-engine-snare", "5 ms linear fade-out"):
        assert needle in text, needle
    desc = SNARE["description"]
    for needle in ("`snappy` (vocabulary keyword weight only)", "separate future `rim-params`"):
        assert needle in desc, needle


def test_shared_fields_have_the_same_definition_as_clap_and_kick_params() -> None:
    clap = load("clap-params.schema.json")["properties"]
    kick = load("kick-params.schema.json")
    kick_props = {**kick["properties"], **kick["allOf"][0]["then"]["properties"]}

    def core(prop: dict) -> dict:
        return {k: v for k, v in prop.items() if k != "description"}

    assert SNARE["properties"]["schema_version"] == {"const": "0.1"}  # clap: 0.1 or 0.2 (#280)
    for name in ("seed", "variants", "bpm", "sample_rate", "bit_depth", "drive",
                 "polarity", "offset_ms", "peak_ceiling_dbfs", "preset"):
        assert core(SNARE["properties"][name]) == core(clap[name]), name
    for name in ("seed", "variants", "sample_rate", "bit_depth", "peak_ceiling_dbfs",
                 "preset", "polarity", "offset_ms"):
        assert core(SNARE["properties"][name]) == core(kick_props[name]), name


# --- sample-metadata: category snare -----------------------------------------------------------

SNARE_DOC = {
    "schema_version": "0.2", "file": "snare.wav", "category": "snare",
    "engine": {"name": "abeltongod-audio-engine-snare", "version": "0.1.0"},
    "parameters": {"schema_version": "0.1", "seed": 7},
    "features": {
        "peak_dbfs": -0.3, "length_ms": 400.0, "spectral_centroid_hz": 3000.0,
        "t60_ms": 180.0, "rise_time_ms": 0.9, "fundamental_hz": None,
    },
    "created_at": "2026-11-02T12:00:00+00:00",
}


def _changed(path: str, value, base: dict = SNARE_DOC) -> dict:
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


def test_metadata_snare_and_other_categories_still_validate() -> None:
    META_V.validate(SNARE_DOC)
    META_V.validate(json.loads((ROOT / "tests/fixtures/sidecars/kick-v01.json").read_text("utf-8")))
    for category, engine in (("clap", "abeltongod-audio-engine-clap"),
                             ("hat", "abeltongod-audio-engine-hat")):
        doc = copy.deepcopy(SNARE_DOC)
        doc.update(category=category, file=f"{category}.wav")
        doc["engine"]["name"] = engine
        META_V.validate(doc)
    kick = copy.deepcopy(SNARE_DOC)
    kick.update(category="kick", schema_version="0.1", file="kick.wav")
    kick["engine"]["name"] = "abeltongod-audio-engine"
    META_V.validate(kick)


METADATA_INVALID = {
    "snare with schema_version 0.1": _changed("schema_version", "0.1"),
    "snare with the kick engine name": _changed("engine.name", "abeltongod-audio-engine"),
    "snare with the clap engine name": _changed("engine.name", "abeltongod-audio-engine-clap"),
    "snare with the hat engine name": _changed("engine.name", "abeltongod-audio-engine-hat"),
    "snare parameters without seed": _changed("parameters.seed", ...),
    "snare parameters with kick-params version": _changed("parameters.schema_version", "0.3"),
    "category perc": _changed("category", "perc"),
}


@pytest.mark.parametrize("doc", METADATA_INVALID.values(), ids=METADATA_INVALID)
def test_metadata_snare_invalid_instances(doc) -> None:
    with pytest.raises(ValidationError):
        META_V.validate(doc)


@pytest.mark.parametrize("category", ["clap", "hat"])
def test_snare_engine_name_is_refused_for_other_categories(category: str) -> None:
    doc = copy.deepcopy(SNARE_DOC)
    doc["category"] = category
    with pytest.raises(ValidationError):
        META_V.validate(doc)
