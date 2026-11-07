"""perc-params v0.1 and category `perc` in sample-metadata v0.2 (#475, D-032).

Expected ranges, base values and limits are written out here by hand, not read from the schema,
so a changed number in the contract turns a test red and has to be changed on purpose.
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


PERC = load("perc-params.schema.json")
PERC_V = Draft202012Validator(PERC)
META = load("sample-metadata.schema.json")
META_V = Draft202012Validator(META)
BASE = {"schema_version": "0.1", "seed": 1}
MODELS = ["conga", "tom", "shaker", "cowbell", "clave"]

# name: (minimum, maximum, default); None = no default (engine-chosen or metadata only)
PERC_RANGES = {
    "length_ms": (20, 2000, None),
    "tune_semitones": (-12, 12, 0),
    "decay_scale": (0.25, 4, 1),
    "attack_scale": (0.25, 4, 1),
    "bend_ratio": (1.0, 2.0, 1.25),
    "bend_ms": (1, 30, 5),
    "tick_level": (0, 1, 0.2),
    "tick_hz": (1000, 6000, 2500),
    "hp_hz": (20, 1000, 20),
    "drive": (0, 1, 0),
    "offset_ms": (0, 12, 0),
    "peak_ceiling_dbfs": (-12, -0.1, -0.3),
    "bpm": (60, 200, None),
}
PERC_FIELDS = {
    "schema_version", "seed", "variants", "sample_rate", "bit_depth", "polarity", "preset",
    "model", *PERC_RANGES,
}
# model: (base_hz, base_decay_ms, base_attack_ms) as the $comment point 2 must state them
BASE_VALUES = {
    "tom": ("130.81", "300", "0.6"),
    "conga": ("261.63", "200", "0.6"),
    "cowbell": ("540", "120", "1"),
    "clave": ("2400", "30", "0.5"),
    "shaker": ("4500", "80", "12"),
}


def test_perc_field_set_and_required() -> None:
    assert set(PERC["properties"]) == PERC_FIELDS
    assert PERC["required"] == ["schema_version", "seed"]
    assert PERC["additionalProperties"] is False
    # deferred in v0.1: NOT fields
    for absent in ("note", "pitch_hz", "decay_ms", "attack_ms", "bongo", "f2_ratio", "level2",
                   "mod_ratio", "detune", "stereo_width", "voice", "category"):
        assert absent not in PERC["properties"], absent


@pytest.mark.parametrize("name", sorted(PERC_RANGES))
def test_perc_range_matches_table_and_edges(name: str) -> None:
    low, high, default = PERC_RANGES[name]
    prop = PERC["properties"][name]
    assert (prop["minimum"], prop["maximum"], prop.get("default")) == (low, high, default)
    for ok in (low, high):
        PERC_V.validate({**BASE, name: ok})
    span = high - low
    for bad in (low - span / 100, high + span / 100):
        with pytest.raises(ValidationError):
            PERC_V.validate({**BASE, name: bad})


def test_perc_random_values_inside_and_outside_range() -> None:
    rng = random.Random(475)
    for _ in range(300):
        name = rng.choice(sorted(PERC_RANGES))
        low, high, _default = PERC_RANGES[name]
        span = high - low
        PERC_V.validate({**BASE, "model": rng.choice(MODELS), name: rng.uniform(low, high)})
        excess = rng.uniform(0.001, 1) * span
        outside = rng.choice((low - excess, high + excess))
        with pytest.raises(ValidationError):
            PERC_V.validate({**BASE, name: outside})


def test_perc_random_full_documents_validate() -> None:
    """Every field at once, random over the whole range, for every model."""
    rng = random.Random(4750)
    for _ in range(200):
        doc = {**BASE, "seed": rng.randrange(0, 2**32), "model": rng.choice(MODELS),
               "variants": rng.randint(1, 8), "sample_rate": rng.choice([44100, 48000]),
               "bit_depth": rng.choice([16, 24]), "polarity": rng.choice([1, -1]),
               "preset": "p" * rng.randint(0, 64)}
        doc.update({n: rng.uniform(lo, hi) for n, (lo, hi, _d) in PERC_RANGES.items()})
        PERC_V.validate(doc)


def test_perc_model_enum_and_default_is_not_tom() -> None:
    prop = PERC["properties"]["model"]
    assert prop["enum"] == MODELS
    assert prop["default"] == "conga"
    assert prop["default"] != "tom"  # D-032: toms only in presets named for hard groove
    for model in MODELS:
        PERC_V.validate({**BASE, "model": model})
    for bad in ("bongo", "Tom", "tambourine", "metal", "", None, 0):
        with pytest.raises(ValidationError):
            PERC_V.validate({**BASE, "model": bad})


def test_perc_discrete_fields() -> None:
    good = {"variants": [1, 8], "sample_rate": [44100, 48000], "bit_depth": [16, 24],
            "polarity": [1, -1], "seed": [0, 4294967295], "preset": ["", "x" * 64]}
    bad = {"variants": [0, 9], "sample_rate": [96000], "bit_depth": [32], "polarity": [0, 2],
           "seed": [-1, 4294967296, 1.5], "preset": ["x" * 65, 3]}
    for name, values in good.items():
        for v in values:
            PERC_V.validate({**BASE, name: v})
    for name, values in bad.items():
        for v in values:
            with pytest.raises(ValidationError):
                PERC_V.validate({**BASE, name: v})


def test_perc_required_version_and_unknown_fields() -> None:
    PERC_V.validate(BASE)
    for doc in ({"seed": 1}, {"schema_version": "0.1"}, {"schema_version": "0.2", "seed": 1},
                {**BASE, "wobble": 1}, {**BASE, "pitch_hz": 200}, {**BASE, "note": 48},
                {**BASE, "decay_ms": 100}):
        with pytest.raises(ValidationError):
            PERC_V.validate(doc)


def test_base_value_table_is_stated_for_every_model() -> None:
    text = PERC["$comment"]
    for model, (hz, decay, attack) in BASE_VALUES.items():
        for needle in (f"{model}: base_hz {hz}", f"base_decay_ms {decay}",
                       f"base_attack_ms {attack}"):
            assert needle in text, (model, needle)
    for needle in ("f0 = base_hz[model] * 2^(tune_semitones / 12)",
                   "attack_ms = base_attack_ms * attack_scale",
                   "t60 = base_decay_ms * decay_scale"):
        assert needle in text, needle


def test_tune_range_reaches_the_documented_tom_span() -> None:
    """tune_semitones +-12 around C3 = 130.81 Hz: 65.4 .. 261.6 Hz (field description)."""
    lo, hi, _ = PERC_RANGES["tune_semitones"]
    assert 130.81 * 2 ** (lo / 12) == pytest.approx(65.405, abs=0.01)
    assert 130.81 * 2 ** (hi / 12) == pytest.approx(261.62, abs=0.01)
    assert "65.4 to 261.6 Hz" in PERC["properties"]["tune_semitones"]["description"]
    assert "lowest f0 is 65.4 Hz" in PERC["$comment"]


def test_highest_frequencies_stay_below_0_45_nyquist() -> None:
    """$comment point 7: no aliasing cross-field rule is needed. Numbers by hand."""
    octave_up = 2 ** (PERC_RANGES["tune_semitones"][1] / 12)
    tops = {
        "membrane start": 261.63 * octave_up * PERC_RANGES["bend_ratio"][1],
        "cowbell upper square": 540 * octave_up * 800 / 540,
        "cowbell band-pass": 2600 * octave_up,
        "clave": 2400 * octave_up,
        "shaker band-pass": 4500 * octave_up,
        "shaker high-pass": 3000 * octave_up,
        "tick": PERC_RANGES["tick_hz"][1],
    }
    assert tops["membrane start"] == pytest.approx(1046.52)
    assert tops["cowbell upper square"] == pytest.approx(1600)
    for name, f in tops.items():
        assert f < 0.45 * 44100, name
    text = PERC["$comment"]
    for needle in ("1046.5 Hz", "at most 1600 Hz", "at most 5200 Hz", "at most 4800 Hz",
                   "at most 9000 Hz", "at most 6000 Hz", "19845 Hz"):
        assert needle in text, needle


def test_contract_text_fixes_the_agreed_definitions() -> None:
    text = PERC["$comment"]
    for needle in ("time to -60 dB after the attack", "phase 0", "own sub-stream",
                   "seed-independent", "shaker is always seed-dependent",
                   "Reject out-of-range values, never clamp", "Defaults are placeholders",
                   "abeltongod-audio-engine-perc", "5 ms linear fade-out",
                   "tick_level 0 means no tick", "The default model is conga, not tom (D-032)",
                   "No cross-field rule", "bend_ratio and bend_ms act only on tom and conga",
                   "tick_level and tick_hz have no effect at shaker", "800 / 540",
                   "the rule of audio_engine.dsp.square_bank", "20 = off (no filter)",
                   "existing non-pitched ones",
                   "base_decay_ms 30 (placeholder; the artifact's 'decay 30' is the rim "
                   "recipe's decay knob, not a time to -60 dB)",
                   "a simplification: the rim voice reduced to a single partial"):
        assert needle in text, needle
    desc = PERC["description"]
    for needle in ("PROPOSALS", "D-032", "prior art from one browser artifact",
                   "no outside source gives numeric targets", "Not part of v0.1", "bongo"):
        assert needle in desc, needle


def test_shared_fields_have_the_same_definition_as_the_other_contracts() -> None:
    clap = load("clap-params.schema.json")["properties"]
    hat = load("hat-params.schema.json")["properties"]
    kick = load("kick-params.schema.json")
    kick_props = {**kick["properties"], **kick["allOf"][0]["then"]["properties"]}
    laser = load("laser-params.schema.json")
    (laser_v02,) = [b for b in laser["allOf"]
                    if b["if"] == {"properties": {"schema_version": {"const": "0.2"}}}]

    def core(prop: dict) -> dict:
        return {k: v for k, v in prop.items() if k != "description"}

    props = PERC["properties"]
    assert props["schema_version"] == {"const": "0.1"}
    for name in ("seed", "variants", "bpm", "sample_rate", "bit_depth", "drive",
                 "polarity", "offset_ms", "peak_ceiling_dbfs", "preset"):
        assert core(props[name]) == core(clap[name]), name
    for name in ("seed", "variants", "sample_rate", "bit_depth", "peak_ceiling_dbfs",
                 "preset", "polarity", "offset_ms"):
        assert core(props[name]) == core(kick_props[name]), name
    assert core(props["length_ms"]) == core(hat["length_ms"])  # engine-chosen when omitted
    assert core(props["hp_hz"]) == core(laser_v02["then"]["properties"]["hp_hz"])


# --- sample-metadata: category perc ------------------------------------------------------------

PERC_DOC = {
    "schema_version": "0.2", "file": "perc.wav", "category": "perc",
    "engine": {"name": "abeltongod-audio-engine-perc", "version": "0.1.0"},
    "parameters": {"schema_version": "0.1", "seed": 7, "model": "conga"},
    "features": {
        "peak_dbfs": -0.3, "length_ms": 250.0, "spectral_centroid_hz": 900.0,
        "t60_ms": 200.0, "rise_time_ms": 0.6, "fundamental_hz": None,
    },
    "created_at": "2026-11-07T12:00:00+00:00",
}
OTHER_ENGINES = {
    "clap": "abeltongod-audio-engine-clap", "hat": "abeltongod-audio-engine-hat",
    "snare": "abeltongod-audio-engine-snare", "rim": "abeltongod-audio-engine-rim",
    "bass": "abeltongod-audio-engine-bass", "laser": "abeltongod-audio-engine-laser",
}


def _changed(path: str, value, base: dict = PERC_DOC) -> dict:
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


def test_metadata_category_enum_ends_with_perc() -> None:
    assert META["properties"]["category"]["enum"] == [
        "kick", "clap", "hat", "snare", "rim", "bass", "laser", "perc"]


def test_metadata_perc_and_other_categories_still_validate() -> None:
    META_V.validate(PERC_DOC)
    for model in MODELS:
        META_V.validate(_changed("parameters.model", model))
    META_V.validate(json.loads((ROOT / "tests/fixtures/sidecars/kick-v01.json").read_text("utf-8")))
    for category, engine in OTHER_ENGINES.items():
        doc = copy.deepcopy(PERC_DOC)
        doc.update(category=category, file=f"{category}.wav")
        doc["engine"]["name"] = engine
        META_V.validate(doc)


METADATA_INVALID = {
    "perc with schema_version 0.1": _changed("schema_version", "0.1"),
    "perc with the kick engine name": _changed("engine.name", "abeltongod-audio-engine"),
    **{f"perc with the {c} engine name": _changed("engine.name", e)
       for c, e in OTHER_ENGINES.items()},
    "perc parameters without seed": _changed("parameters.seed", ...),
    "perc parameters without schema_version": _changed("parameters.schema_version", ...),
    "perc parameters with version 0.2": _changed("parameters.schema_version", "0.2"),
    "perc parameters with kick-params version": _changed("parameters.schema_version", "0.3"),
    "category tom (a model, not a category)": _changed("category", "tom"),
    "category percs": _changed("category", "percs"),
}


@pytest.mark.parametrize("doc", METADATA_INVALID.values(), ids=METADATA_INVALID)
def test_metadata_perc_invalid_instances(doc) -> None:
    with pytest.raises(ValidationError):
        META_V.validate(doc)


@pytest.mark.parametrize("category", sorted(OTHER_ENGINES))
def test_perc_engine_name_is_refused_for_other_categories(category: str) -> None:
    doc = copy.deepcopy(PERC_DOC)
    doc["category"] = category
    with pytest.raises(ValidationError):
        META_V.validate(doc)


def test_perc_is_a_contract_category_without_a_renderer_yet() -> None:
    """Step 1 of #475: the contract names perc; the engine refuses it until step 2."""
    from audio_engine.categories import (
        CONTRACT_CATEGORIES,
        CategoryUnavailable,
        get_category,
        registered_categories,
    )

    assert CONTRACT_CATEGORIES[-1] == "perc"
    assert "perc" not in registered_categories()
    with pytest.raises(CategoryUnavailable, match="no renderer"):
        get_category("perc")
