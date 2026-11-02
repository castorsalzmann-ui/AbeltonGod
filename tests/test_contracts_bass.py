"""bass-params v0.1 and category `bass` in sample-metadata v0.2 (#320).

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


BASS = load("bass-params.schema.json")
BASS_V = Draft202012Validator(BASS)
META_V = Draft202012Validator(load("sample-metadata.schema.json"))
BASE = {"schema_version": "0.1", "seed": 1}

# name: (minimum, maximum, default); numbers from docs/research/2026-11-02_bass-targets.md
# sections 2 and 5 and the snare-rim-sub-bass design note section 3.3 (hypotheses / proposals).
BASS_RANGES = {
    "note": (24, 55, 43),
    "cents": (-50, 50, 0),
    "saw_level": (0, 1, 0.7),
    "square_level": (0, 1, 0),
    "sine_level": (0, 1, 0.7),
    "sub_octave_level": (0, 1, 0),
    "gate_ms": (50, 1500, 250),
    "release_ms": (5, 400, 60),
    "amp_attack_ms": (0.5, 30, 3),
    "hp_hz": (20, 120, 20),
    "lp_hz": (60, 4000, 350),
    "lp_q": (0.5, 6, 0.9),
    "lp_env_amount": (0, 4, 1.5),
    "lp_env_decay_ms": (5, 800, 120),
    "drive": (0, 1, 0.2),
    "offset_ms": (0, 12, 0),
    "peak_ceiling_dbfs": (-12, -0.1, -0.3),
    "bpm": (60, 200, None),
}
BASS_FIELDS = {
    "schema_version", "seed", "variants", "sample_rate", "bit_depth", "polarity", "preset",
    *BASS_RANGES,
}


def test_bass_field_set_and_required() -> None:
    assert set(BASS["properties"]) == BASS_FIELDS
    assert BASS["required"] == ["schema_version", "seed"]
    # deferred in v0.1 (no source, or lead decision): NOT fields; length is derived
    for absent in ("detune_cents", "model", "length_ms", "length_beats", "voice", "stereo"):
        assert absent not in BASS["properties"]


@pytest.mark.parametrize("name", sorted(BASS_RANGES))
def test_bass_range_matches_table_and_edges(name: str) -> None:
    low, high, default = BASS_RANGES[name]
    prop = BASS["properties"][name]
    assert (prop["minimum"], prop["maximum"], prop.get("default")) == (low, high, default)
    for ok in (low, high):
        BASS_V.validate({**BASE, name: ok})
    span = high - low
    for bad in (low - span / 100, high + span / 100):
        with pytest.raises(ValidationError):
            BASS_V.validate({**BASE, name: bad})


def test_bass_note_is_an_integer() -> None:
    BASS_V.validate({**BASE, "note": 43})
    for bad in (43.5, "43", 23, 56):
        with pytest.raises(ValidationError):
            BASS_V.validate({**BASE, "note": bad})


def test_bass_random_values_inside_and_outside_range() -> None:
    rng = random.Random(320)
    for _ in range(400):
        name = rng.choice(sorted(BASS_RANGES))
        low, high, _default = BASS_RANGES[name]
        span = high - low
        value = rng.uniform(low, high)
        if name == "note":
            value = rng.randint(low, high)
        BASS_V.validate({**BASE, name: value})
        excess = rng.uniform(0.001, 1) * span
        outside = rng.choice((low - excess, high + excess))
        with pytest.raises(ValidationError):
            BASS_V.validate({**BASE, name: outside})


def test_bass_random_full_documents_validate() -> None:
    rng = random.Random(3200)
    for _ in range(100):
        doc = dict(BASE)
        for name, (low, high, _d) in BASS_RANGES.items():
            doc[name] = rng.randint(low, high) if name == "note" else rng.uniform(low, high)
        BASS_V.validate(doc)


def test_bass_discrete_fields() -> None:
    good = {"variants": [1, 8], "sample_rate": [44100, 48000], "bit_depth": [16, 24],
            "polarity": [1, -1], "seed": [0, 4294967295]}
    bad = {"variants": [0, 9], "sample_rate": [96000], "bit_depth": [32], "polarity": [0, 2],
           "seed": [-1, 4294967296, 1.5]}
    for name, values in good.items():
        for v in values:
            BASS_V.validate({**BASE, name: v})
    for name, values in bad.items():
        for v in values:
            with pytest.raises(ValidationError):
                BASS_V.validate({**BASE, name: v})


def test_bass_required_version_and_unknown_fields() -> None:
    BASS_V.validate(BASE)
    for doc in ({"seed": 1}, {"schema_version": "0.1"}, {"schema_version": "0.2", "seed": 1},
                {**BASE, "wobble": 1}, {**BASE, "detune_cents": 5}, {**BASE, "model": "reese"},
                {**BASE, "length_ms": 300}):
        with pytest.raises(ValidationError):
            BASS_V.validate(doc)


def _f0(note: int, cents: float = 0.0) -> float:
    return 440 * 2 ** ((note - 69) / 12) * 2 ** (cents / 1200)


def test_note_frequency_endpoints_written_in_the_contract() -> None:
    assert _f0(43) == pytest.approx(98.0, abs=0.05)
    assert _f0(24) == pytest.approx(32.7, abs=0.05)
    assert _f0(55) == pytest.approx(196.0, abs=0.05)
    text = BASS["$comment"]
    assert "440 * 2^((note - 69) / 12) * 2^(cents / 1200)" in text
    for needle in ("note 43 = 98.0 Hz", "note 24 = 32.7 Hz", "note 55 = 196.0 Hz"):
        assert needle in text, needle


def test_defaults_satisfy_every_cross_field_rule_for_every_note() -> None:
    """Rules in the $comment; the schema cannot check them, the engine will. Defaults must pass."""
    d = {n: v[2] for n, v in BASS_RANGES.items()}
    for note in range(24, 56):
        for cents in (-50, 50):
            f0 = _f0(note, cents)
            assert d["hp_hz"] < 0.8 * f0  # (a)
    assert d["lp_hz"] >= 1.2 * d["hp_hz"]  # (b)
    for sr in (44100, 48000):
        assert d["lp_hz"] * 2 ** d["lp_env_amount"] < 0.45 * sr  # (c)
    assert d["saw_level"] + d["square_level"] + d["sine_level"] + d["sub_octave_level"] > 0  # (d)


def test_cross_field_rules_are_real_and_stated() -> None:
    text = BASS["$comment"]
    for needle in ("hp_hz must be less than 0.8 * f0", "lp_hz must be at least 1.2 * hp_hz",
                   "must be less than 0.45 * sample_rate", "(otherwise silence)"):
        assert needle in text, needle
    # The schema alone accepts violating pairs; the engine must refuse them.
    BASS_V.validate({**BASE, "note": 24, "hp_hz": 120})
    BASS_V.validate({**BASE, "lp_hz": 60, "hp_hz": 120})
    BASS_V.validate({**BASE, "lp_hz": 4000, "lp_env_amount": 4})
    BASS_V.validate({**BASE, "saw_level": 0, "sine_level": 0})
    # Rules (a) and (c) really bite inside the ranges (so they are not dead text):
    assert 120 >= 0.8 * _f0(24)
    assert 4000 * 2**4 > 0.45 * 48000
    # B1's 65 Hz needs a note of about 82 Hz or more; note 43 (98 Hz) allows it.
    assert 65 < 0.8 * _f0(43) and 65 > 0.8 * _f0(31)


def test_attack_is_always_shorter_than_gate_so_no_rule_is_needed() -> None:
    assert BASS_RANGES["amp_attack_ms"][1] < BASS_RANGES["gate_ms"][0]
    needle = "amp_attack_ms (at most 30) is always shorter than gate_ms (at least 50)"
    assert needle in BASS["$comment"]


def test_contract_text_fixes_the_agreed_definitions() -> None:
    text = BASS["$comment"]
    for needle in ("phase 0 at t = 0", "lp_hz is the sustained cutoff",
                   "lp_hz * 2^(lp_env_amount * 10^(-3 * t / lp_env_decay_ms))",
                   "linear ramp from 0 to 1 over amp_attack_ms",
                   "linear ramp from the held level to 0 over release_ms",
                   "The first sample and the last sample are 0",
                   "length_ms is derived and is not an input",
                   "not f0 / 2 when sub_octave_level > 0",
                   "40 % to 80 % of gate_ms", "fewer than 2 whole periods",
                   "it is never taken from the release", "core voice is seed-independent",
                   "Reject out-of-range values, never clamp", "Defaults are placeholders",
                   "abeltongod-audio-engine-bass", "The default note is 43"):
        assert needle in text, needle
    desc = BASS["description"]
    for needle in ("PROPOSALS", "one Attack Magazine tutorial", "`detune_cents`"):
        assert needle in desc, needle


def test_every_field_has_a_measurement_method_in_the_contract() -> None:
    """Item (8) of the $comment must name a method for each synthesis field and rule out the
    helpers that are unusable for bass."""
    text = BASS["$comment"]
    method = text[text.index("(8) Measurement method per field"):text.index("(9) No taste range")]
    for field in ("note and cents", "saw_level", "square_level", "sine_level", "sub_octave_level",
                  "hp_hz", "lp_hz", "lp_env_amount", "lp_env_decay_ms", "amp_attack_ms",
                  "gate_ms", "release_ms", "drive", "DC"):
        assert field in method, field
    for needle in ("zero-crossing", "autocorrelation", "peak envelope", "period-long RMS",
                   "4 times the sample rate", "rise_time_ms and t60_ms are not used for bass",
                   "tail_window lands in the release"):
        assert needle in method, needle
    # every synthesis field of the schema is covered (shared export-only fields are not)
    synth = set(BASS_RANGES) - {"bpm", "offset_ms", "peak_ceiling_dbfs", "note", "cents"}
    for name in synth:
        assert name in method, name


def test_shared_fields_have_the_same_definition_as_clap_and_kick_params() -> None:
    clap = load("clap-params.schema.json")["properties"]
    kick = load("kick-params.schema.json")
    kick_props = {**kick["properties"], **kick["allOf"][0]["then"]["properties"]}

    def core(prop: dict) -> dict:
        return {k: v for k, v in prop.items() if k != "description"}

    # drive: same stage and range, but a bass default of 0.2 (the research note), so the default
    # is compared separately.
    assert BASS["properties"]["schema_version"] == {"const": "0.1"}  # clap: 0.1 or 0.2 (#280)
    for name in ("seed", "variants", "bpm", "sample_rate", "bit_depth",
                 "polarity", "offset_ms", "peak_ceiling_dbfs", "preset"):
        assert core(BASS["properties"][name]) == core(clap[name]), name
    for name in ("seed", "variants", "sample_rate", "bit_depth", "peak_ceiling_dbfs",
                 "preset", "polarity", "offset_ms"):
        assert core(BASS["properties"][name]) == core(kick_props[name]), name
    drive = {k: v for k, v in core(BASS["properties"]["drive"]).items() if k != "default"}
    assert drive == {k: v for k, v in core(clap["drive"]).items() if k != "default"}


# --- sample-metadata: category bass ------------------------------------------------------------

BASS_DOC = {
    "schema_version": "0.2", "file": "bass.wav", "category": "bass",
    "engine": {"name": "abeltongod-audio-engine-bass", "version": "0.1.0"},
    "parameters": {"schema_version": "0.1", "seed": 7},
    "features": {"peak_dbfs": -0.3, "length_ms": 310.0, "fundamental_hz": 98.0},
    "created_at": "2026-11-02T12:00:00+00:00",
}


def _changed(path: str, value, base: dict = BASS_DOC) -> dict:
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


def test_metadata_bass_and_other_categories_still_validate() -> None:
    META_V.validate(BASS_DOC)
    META_V.validate(_changed("features.fundamental_hz", None))
    META_V.validate(json.loads((ROOT / "tests/fixtures/sidecars/kick-v01.json").read_text("utf-8")))
    for category, engine in (("clap", "abeltongod-audio-engine-clap"),
                             ("hat", "abeltongod-audio-engine-hat"),
                             ("snare", "abeltongod-audio-engine-snare"),
                             ("rim", "abeltongod-audio-engine-rim")):
        doc = copy.deepcopy(BASS_DOC)
        doc.update(category=category, file=f"{category}.wav")
        doc["engine"]["name"] = engine
        META_V.validate(doc)
    kick = copy.deepcopy(BASS_DOC)
    kick.update(category="kick", schema_version="0.1", file="kick.wav")
    kick["engine"]["name"] = "abeltongod-audio-engine"
    META_V.validate(kick)


METADATA_INVALID = {
    "bass with schema_version 0.1": _changed("schema_version", "0.1"),
    "bass with the kick engine name": _changed("engine.name", "abeltongod-audio-engine"),
    "bass with the clap engine name": _changed("engine.name", "abeltongod-audio-engine-clap"),
    "bass with the hat engine name": _changed("engine.name", "abeltongod-audio-engine-hat"),
    "bass with the snare engine name": _changed("engine.name", "abeltongod-audio-engine-snare"),
    "bass with the rim engine name": _changed("engine.name", "abeltongod-audio-engine-rim"),
    "bass parameters without seed": _changed("parameters.seed", ...),
    "bass parameters with kick-params version": _changed("parameters.schema_version", "0.3"),
    "category sub": _changed("category", "sub"),
}


@pytest.mark.parametrize("doc", METADATA_INVALID.values(), ids=METADATA_INVALID)
def test_metadata_bass_invalid_instances(doc) -> None:
    with pytest.raises(ValidationError):
        META_V.validate(doc)


@pytest.mark.parametrize("category", ["clap", "hat", "snare", "rim"])
def test_bass_engine_name_is_refused_for_other_categories(category: str) -> None:
    doc = copy.deepcopy(BASS_DOC)
    doc["category"] = category
    with pytest.raises(ValidationError):
        META_V.validate(doc)
