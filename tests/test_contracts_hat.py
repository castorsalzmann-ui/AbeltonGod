"""hat-params v0.1 and category `hat` in sample-metadata v0.2 (#249).

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


HAT = load("hat-params.schema.json")
HAT_V = Draft202012Validator(HAT)
META_V = Draft202012Validator(load("sample-metadata.schema.json"))
BASE = {"schema_version": "0.1", "seed": 1}

# name: (minimum, maximum, default); numbers from the hat design note section 4 (proposals).
HAT_RANGES = {
    "length_ms": (20, 2000, None),
    "decay_ms": (10, 900, 60),
    "attack_ms": (0.1, 5, 0.8),
    "metal": (0, 1, 0.6),
    "pitch_scale": (0.5, 2.0, 1.0),
    "color": (0, 1, 0.5),
    "hp_hz": (2000, 12000, 6000),
    "lp_hz": (8000, 22000, 18000),
    "bp_hz": (1500, 12000, 7100),
    "bp_q": (0.4, 4, 0.7),
    "bp_mix": (0, 1, 0),
    "peak_hz": (5000, 14000, 9000),
    "peak_db": (-6, 9, 0),
    "body_mix": (0, 1, 0),
    "decay_hi_ratio": (0.2, 1, 0.5),
    "drive": (0, 1, 0),
    "offset_ms": (0, 12, 0),
    "peak_ceiling_dbfs": (-12, -0.1, -0.3),
    "bpm": (60, 200, None),
}
HAT_FIELDS = {
    "schema_version", "seed", "variants", "sample_rate", "bit_depth", "model", "polarity",
    "choke_ms", "preset", *HAT_RANGES,
}

# The five styles of docs/research/2026-11-02_hat-targets-and-listening-plan.md section 2.
STYLES = {
    "closed tight": {"decay_ms": 35, "hp_hz": 7000},
    "closed std": {"decay_ms": 70, "hp_hz": 6000},
    "closed loose": {"decay_ms": 120, "hp_hz": 5000},
    "open short": {"decay_ms": 250, "hp_hz": 6000},
    "open long": {"decay_ms": 500, "hp_hz": 5500},
}


def test_hat_field_set_and_required() -> None:
    assert set(HAT["properties"]) == HAT_FIELDS
    assert HAT["required"] == ["schema_version", "seed"]
    assert HAT["properties"]["model"]["enum"] == ["metal_bank", "noise"]
    assert HAT["properties"]["model"]["default"] == "metal_bank"


@pytest.mark.parametrize("name", sorted(HAT_RANGES))
def test_hat_range_matches_table_and_edges(name: str) -> None:
    low, high, default = HAT_RANGES[name]
    prop = HAT["properties"][name]
    assert (prop["minimum"], prop["maximum"], prop.get("default")) == (low, high, default)
    for ok in (low, high):
        HAT_V.validate({**BASE, name: ok})
    span = high - low
    for bad in (low - span / 100, high + span / 100):
        with pytest.raises(ValidationError):
            HAT_V.validate({**BASE, name: bad})


def test_hat_discrete_fields_and_choke() -> None:
    good = {"variants": [1, 8], "sample_rate": [44100, 48000], "bit_depth": [16, 24],
            "polarity": [1, -1], "seed": [0, 4294967295], "model": ["metal_bank", "noise"],
            "choke_ms": [0, 5, 5.0, 120.5, 900]}
    bad = {"variants": [0, 9], "sample_rate": [96000], "bit_depth": [32], "polarity": [0, 2],
           "seed": [-1, 4294967296, 1.5], "model": ["shaker", "ride", "noise_hat"],
           "choke_ms": [-1, 0.1, 4.9, 900.1, "5"]}
    for name, values in good.items():
        for v in values:
            HAT_V.validate({**BASE, name: v})
    for name, values in bad.items():
        for v in values:
            with pytest.raises(ValidationError):
                HAT_V.validate({**BASE, name: v})


def test_hat_required_version_and_unknown_fields() -> None:
    HAT_V.validate(BASE)
    for doc in ({"seed": 1}, {"schema_version": "0.1"}, {"schema_version": "0.2", "seed": 1},
                {**BASE, "wobble": 1}, {**BASE, "shaker_bp_hz": 4500}, {**BASE, "width": 0.5}):
        with pytest.raises(ValidationError):
            HAT_V.validate(doc)


@pytest.mark.parametrize("style", STYLES)
def test_target_note_styles_validate_and_satisfy_cross_field_rule(style: str) -> None:
    doc = {**BASE, **STYLES[style], "lp_hz": 18000, "metal": 0.6}
    HAT_V.validate(doc)
    assert doc["lp_hz"] > 1.2 * doc["hp_hz"]


def test_cross_field_rule_is_stated_and_defaults_satisfy_it() -> None:
    """JSON Schema cannot compare two fields: the rule is contract text, enforced by the engine.
    Every hp_hz in range with the default lp_hz is valid, so a document that omits lp_hz can
    never break the rule."""
    text = HAT["$comment"] + HAT["properties"]["lp_hz"]["description"]
    assert "lp_hz must be greater than 1.2 * hp_hz" in text
    assert 1.2 * HAT_RANGES["hp_hz"][1] < HAT_RANGES["lp_hz"][2]
    assert 1.2 * HAT_RANGES["hp_hz"][2] < HAT_RANGES["lp_hz"][2]
    # The schema alone accepts a violating pair (hp 12000, lp 8000); the engine must refuse it.
    HAT_V.validate({**BASE, "hp_hz": 12000, "lp_hz": 8000})


def test_contract_text_fixes_the_agreed_definitions() -> None:
    text = HAT["$comment"]
    for needle in ("PASSBAND POWER AFTER THE HIGH-PASS CHAIN", "ALL odd harmonics",
                   "start phases 0", "fallen 60 dB",
                   "first crossing", "within 10 %", "5 ms linear fade-out",
                   "The body path is high-passed too", "abeltongod-audio-engine-hat"):
        assert needle in text, needle


def test_shared_fields_have_the_same_definition_as_kick_params() -> None:
    kick = load("kick-params.schema.json")
    kick_props = {**kick["properties"], **kick["allOf"][0]["then"]["properties"]}

    def core(prop: dict) -> dict:
        return {k: v for k, v in prop.items() if k != "description"}

    for name in ("seed", "variants", "sample_rate", "bit_depth", "peak_ceiling_dbfs",
                 "preset", "polarity", "offset_ms"):
        assert core(HAT["properties"][name]) == core(kick_props[name]), name


# --- sample-metadata: category hat -------------------------------------------------------------

HAT_DOC = {
    "schema_version": "0.2", "file": "hat.wav", "category": "hat",
    "engine": {"name": "abeltongod-audio-engine-hat", "version": "0.1.0"},
    "parameters": {"schema_version": "0.1", "seed": 7},
    "features": {
        "peak_dbfs": -0.3, "length_ms": 120.0, "spectral_centroid_hz": 11000.0,
        "hf_share_8k": 0.75, "t60_ms": 66.0, "rise_time_ms": 0.9, "fundamental_hz": None,
    },
    "created_at": "2026-11-02T12:00:00+00:00",
}


def _changed(path: str, value) -> dict:
    doc = copy.deepcopy(HAT_DOC)
    node = doc
    *parents, last = path.split(".")
    for key in parents:
        node = node[key]
    if value is ...:
        del node[last]
    else:
        node[last] = value
    return doc


def test_metadata_hat_and_older_sidecars_validate() -> None:
    META_V.validate(HAT_DOC)
    META_V.validate(_changed("features", {"peak_dbfs": -6.0, "length_ms": 80.0}))
    META_V.validate(json.loads((ROOT / "tests/fixtures/sidecars/kick-v01.json").read_text("utf-8")))
    clap = copy.deepcopy(HAT_DOC)
    clap.update(category="clap", file="clap.wav")
    clap["engine"]["name"] = "abeltongod-audio-engine-clap"
    META_V.validate(clap)


METADATA_INVALID = {
    "hat with schema_version 0.1": _changed("schema_version", "0.1"),
    "hat with the kick engine name": _changed("engine.name", "abeltongod-audio-engine"),
    "hat with the clap engine name": _changed("engine.name", "abeltongod-audio-engine-clap"),
    "hat parameters without seed": _changed("parameters.seed", ...),
    "hat parameters with kick-params version": _changed("parameters.schema_version", "0.3"),
    "hat hf_share above 1": _changed("features.hf_share_8k", 1.5),
    "category shaker": _changed("category", "shaker"),
}


@pytest.mark.parametrize("doc", METADATA_INVALID.values(), ids=METADATA_INVALID)
def test_metadata_hat_invalid_instances(doc) -> None:
    with pytest.raises(ValidationError):
        META_V.validate(doc)


def test_clap_engine_name_is_refused_for_hat_and_vice_versa() -> None:
    clap = copy.deepcopy(HAT_DOC)
    clap["category"] = "clap"
    # still carries the hat engine name
    with pytest.raises(ValidationError):
        META_V.validate(clap)
