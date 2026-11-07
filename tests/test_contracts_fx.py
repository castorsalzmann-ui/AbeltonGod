"""fx-params v0.1 and category `fx` in sample-metadata v0.2 (#482, D-032).

Expected ranges, per-kind defaults and limits are written out here by hand, not read from the
schema, so a changed number in the contract turns a test red and has to be changed on purpose.
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


FX = load("fx-params.schema.json")
FX_V = Draft202012Validator(FX)
META = load("sample-metadata.schema.json")
META_V = Draft202012Validator(META)
BASE = {"schema_version": "0.1", "seed": 1, "bpm": 135}
KINDS = ["riser", "downlifter", "sweep", "impact", "noise_crash", "reverse_crash"]

# name: (minimum, maximum, top-level default); None = per-kind or derived default
FX_RANGES = {
    "bpm": (60, 200, None),
    "length_beats": (1, 128, None),
    "tail_beats": (0, 16, None),
    "cut_beats": (0, 8, 0),
    "peak_ceiling_dbfs": (-12, -0.1, -1.0),
    "stereo_width": (0, 1, 0.6),
    "drive": (0, 1, 0),
    "pump_depth": (0, 1, 0),
    "noise_level": (0, 1, 1),
    "cutoff_start_hz": (20, 20000, None),
    "cutoff_end_hz": (20, 20000, None),
    "lp_ratio": (1.5, 16, 4),
    "filter_q": (0.5, 12, None),
    "sweep_curve": (0.2, 6, None),
    "level_start_db": (-60, 0, None),
    "level_end_db": (-60, 0, None),
    "level_curve": (0.2, 6, 1),
    "ramp_beats": (0.0625, 128, None),
    "tone_level": (0, 1, None),
    "tone_start_hz": (20, 4000, None),
    "tone_end_hz": (20, 4000, None),
    "tone_glide_beats": (0.0625, 128, None),
    "tone_decay_beats": (0, 32, None),
    "reverb_mix": (0, 1, None),
    "reverb_size": (0, 1, 0.5),
    "reverb_decay_ms": (100, 8000, 3000),
    "reverb_predelay_ms": (0, 200, 0),
    "reverb_damp_hz": (1000, 20000, 6000),
    "reverb_width": (0, 1, 1),
    "echo_mix": (0, 1, 0),
    "echo_feedback": (0, 0.9, 0.4),
    "echo_damp_hz": (500, 20000, 6000),
    "echo_pingpong": (0, 1, 0),
}
QUARTER_BEAT_FIELDS = ("length_beats", "tail_beats", "cut_beats")
FX_ENUMS = {
    "kind": (KINDS, "riser"),
    "noise_color": (["white", "pink"], "white"),
    "filter_mode": (["bp", "lp", "hp", "hp_lp"], None),
    "tone_wave": (["sine", "saw", "square", "metal"], None),
    "echo_note": (["1/4", "1/8", "1/8D", "1/8T", "1/16"], "1/8D"),
    "sample_rate": ([44100, 48000], 48000),
    "bit_depth": ([16, 24], 24),
}
FX_FIELDS = {"schema_version", "seed", "variants", "preset", *FX_RANGES, *FX_ENUMS}
DERIVED = {"ramp_beats", "tone_glide_beats"}  # omitted = the resolved length_beats

_TONE_OFF = {"tone_level": 0, "tone_decay_beats": 0}
# Per-kind defaults as the note's section 5.3 proposes them (impact hp 30 Hz, noise_crash
# 1000 Hz / 4 bars per F8, reverse_crash tail 0 by rule); tone values for kinds with the tone
# off are placeholders so that turning the tone on gives a defined sound.
KIND_DEFAULTS = {
    "riser": {"length_beats": 64, "tail_beats": 4, "filter_mode": "bp",
              "cutoff_start_hz": 300, "cutoff_end_hz": 9000, "filter_q": 1.2,
              "sweep_curve": 1.5,
              "level_start_db": -36, "level_end_db": 0, **_TONE_OFF, "tone_wave": "sine",
              "tone_start_hz": 220, "tone_end_hz": 880, "reverb_mix": 0.3},
    "sweep": {"length_beats": 16, "tail_beats": 2, "filter_mode": "lp",
              "cutoff_start_hz": 200, "cutoff_end_hz": 12000, "filter_q": 4, "sweep_curve": 1,
              "level_start_db": -6, "level_end_db": 0, **_TONE_OFF, "tone_wave": "sine",
              "tone_start_hz": 220, "tone_end_hz": 880, "reverb_mix": 0.2},
    "downlifter": {"length_beats": 8, "tail_beats": 4, "filter_mode": "bp",
                   "cutoff_start_hz": 8000, "cutoff_end_hz": 200, "filter_q": 1.2,
                   "sweep_curve": 0.7,
                   "level_start_db": 0, "level_end_db": -36, **_TONE_OFF, "tone_wave": "saw",
                   "tone_start_hz": 400, "tone_end_hz": 60, "reverb_mix": 0.35},
    "impact": {"length_beats": 8, "tail_beats": 8, "filter_mode": "hp",
               "cutoff_start_hz": 30, "cutoff_end_hz": 30, "filter_q": 0.7071, "sweep_curve": 1,
               "level_start_db": 0, "level_end_db": -60, "ramp_beats": 0.25,
               "tone_level": 1, "tone_wave": "sine", "tone_start_hz": 150, "tone_end_hz": 40,
               "tone_glide_beats": 0.5, "tone_decay_beats": 6, "reverb_mix": 0.4},
    "noise_crash": {"length_beats": 16, "tail_beats": 4, "filter_mode": "hp",
                    "cutoff_start_hz": 1000, "cutoff_end_hz": 1000, "filter_q": 0.7071,
                    "sweep_curve": 1, "level_start_db": 0, "level_end_db": -60, **_TONE_OFF,
                    "tone_wave": "sine", "tone_start_hz": 150, "tone_end_hz": 40,
                    "reverb_mix": 0.3},
    "reverse_crash": {"length_beats": 4, "tail_beats": 0, "filter_mode": "hp",
                      "cutoff_start_hz": 3000, "cutoff_end_hz": 3000, "filter_q": 0.7071,
                      "sweep_curve": 1, "level_start_db": -60, "level_end_db": 0, "tone_level": 0.5,
                      "tone_wave": "metal", "tone_start_hz": 205.3, "tone_end_hz": 205.3,
                      "tone_decay_beats": 0, "reverb_mix": 0.3},
}
MAX_FILE_MS = 72000  # cross-field rule A


def matching_branches(doc: dict) -> list[dict]:
    return [b for b in FX["allOf"] if Draft202012Validator(b["if"]).is_valid(doc)]


def resolve(doc: dict) -> dict:
    """Independent re-statement of the documented resolution order (description): top-level
    defaults, then the kind branch, then the derived defaults."""
    out = dict(doc)
    for name, prop in FX["properties"].items():
        if name not in out and "default" in prop:
            out[name] = prop["default"]
    for branch in matching_branches(doc):
        for name, prop in branch["then"]["properties"].items():
            if name not in out and "default" in prop:
                out[name] = prop["default"]
    for name in DERIVED:
        out.setdefault(name, out["length_beats"])
    return out


def test_fx_field_set_and_required() -> None:
    assert set(FX["properties"]) == FX_FIELDS
    assert FX["required"] == ["schema_version", "seed", "bpm"]
    assert FX["additionalProperties"] is False
    for absent in ("length_ms", "pitch_hz", "category", "model", "family", "echo_sync",
                   "lp_hz", "hp_hz", "shepard", "key", "note"):
        assert absent not in FX["properties"], absent


@pytest.mark.parametrize("name", sorted(FX_RANGES))
def test_fx_range_matches_table_and_edges(name: str) -> None:
    low, high, default = FX_RANGES[name]
    prop = FX["properties"][name]
    assert (prop["minimum"], prop["maximum"], prop.get("default")) == (low, high, default)
    for ok in (low, high):
        FX_V.validate({**BASE, name: ok})
    span = high - low
    for bad in (low - span / 100, high + span / 100):
        with pytest.raises(ValidationError):
            FX_V.validate({**BASE, name: bad})


@pytest.mark.parametrize("name", sorted(FX_ENUMS))
def test_fx_enums(name: str) -> None:
    values, default = FX_ENUMS[name]
    prop = FX["properties"][name]
    assert prop["enum"] == values
    assert prop.get("default") == default
    for v in values:
        FX_V.validate({**BASE, name: v})
    for bad in ("", None, 0, "off", "Riser", "pink_noise", 96000, "1/32"):
        if bad not in values:
            with pytest.raises(ValidationError):
                FX_V.validate({**BASE, name: bad})


@pytest.mark.parametrize("name", QUARTER_BEAT_FIELDS)
def test_lengths_are_on_a_quarter_beat_grid(name: str) -> None:
    assert FX["properties"][name]["multipleOf"] == 0.25
    for ok in (1.25, 2.5, 3.75, 8):
        FX_V.validate({**BASE, "kind": "impact", name: ok})
    for bad in (1.1, 2.3, 1.0625):
        with pytest.raises(ValidationError):
            FX_V.validate({**BASE, "kind": "impact", name: bad})


def test_fx_discrete_and_required_fields() -> None:
    FX_V.validate(BASE)
    for name, good, bad in (("variants", [1, 8], [0, 9, 1.5]),
                            ("seed", [0, 4294967295], [-1, 4294967296, 1.5]),
                            ("preset", ["", "x" * 64], ["x" * 65, 3])):
        for v in good:
            FX_V.validate({**BASE, name: v})
        for v in bad:
            with pytest.raises(ValidationError):
                FX_V.validate({**BASE, name: v})
    for doc in ({"seed": 1, "bpm": 135}, {"schema_version": "0.1", "bpm": 135},
                {"schema_version": "0.1", "seed": 1},  # bpm is required: lengths are beats
                {**BASE, "schema_version": "0.2"}, {**BASE, "wobble": 1},
                {**BASE, "length_ms": 1000}, {**BASE, "echo_sync": "1/8"}):
        with pytest.raises(ValidationError):
            FX_V.validate(doc)


def test_per_kind_defaults_match_the_table() -> None:
    assert len(FX["allOf"]) == len(KINDS)
    for kind, expected in KIND_DEFAULTS.items():
        (branch,) = matching_branches({**BASE, "kind": kind})
        got = {n: p["default"] for n, p in branch["then"]["properties"].items()}
        assert got == expected, kind


def test_omitted_kind_takes_the_riser_branch_only() -> None:
    (branch,) = matching_branches(BASE)
    (riser,) = matching_branches({**BASE, "kind": "riser"})
    assert branch is riser
    assert resolve(BASE) == resolve({**BASE, "kind": "riser"}) | {"kind": "riser"}


def test_every_kind_resolves_every_field() -> None:
    """No per-kind field is left without a default: each one has a default in every branch,
    except the two derived ones (= length_beats)."""
    per_kind = {n for n, p in FX["properties"].items() if "default" not in p} - {
        "schema_version", "seed", "bpm", "preset"}
    assert per_kind == {"length_beats", "tail_beats", "filter_mode", "cutoff_start_hz",
                        "cutoff_end_hz", "filter_q", "sweep_curve", "level_start_db",
                        "level_end_db", "ramp_beats", "tone_level", "tone_wave",
                        "tone_start_hz", "tone_end_hz", "tone_glide_beats", "tone_decay_beats",
                        "reverb_mix"}
    for kind in KINDS:
        branch_fields = set(KIND_DEFAULTS[kind])
        assert per_kind - DERIVED <= branch_fields, kind
        resolved = resolve({**BASE, "kind": kind})
        assert set(resolved) == FX_FIELDS - {"preset"}, kind
        FX_V.validate(resolved)
    impact = resolve({**BASE, "kind": "impact"})
    assert (impact["ramp_beats"], impact["tone_glide_beats"]) == (0.25, 0.5)
    riser = resolve(BASE)
    assert (riser["ramp_beats"], riser["tone_glide_beats"]) == (64, 64)


def test_no_field_has_both_a_top_level_and_a_branch_default() -> None:
    """Under the documented order (top level first, then the branch, each filling only missing
    keys) a branch default next to a top-level default would never take effect (#490 review)."""
    top = {n for n, p in FX["properties"].items() if "default" in p}
    for branch in FX["allOf"]:
        in_branch = {n for n, p in branch["then"]["properties"].items() if "default" in p}
        assert not top & in_branch, (branch["if"], top & in_branch)


# Fully RESOLVED values per kind, written by hand (not read from the branches): the fields whose
# default differs between kinds, plus the derived ones and a few top-level ones.
RESOLVED = {
    "riser": {"filter_q": 1.2, "sweep_curve": 1.5, "length_beats": 64, "ramp_beats": 64,
              "filter_mode": "bp", "cutoff_end_hz": 9000, "level_start_db": -36,
              "level_curve": 1, "peak_ceiling_dbfs": -1.0},
    "sweep": {"filter_q": 4, "sweep_curve": 1, "filter_mode": "lp", "tail_beats": 2,
              "tone_glide_beats": 16},
    "downlifter": {"filter_q": 1.2, "sweep_curve": 0.7, "cutoff_start_hz": 8000,
                   "tone_wave": "saw", "ramp_beats": 8},
    "impact": {"filter_q": 0.7071, "sweep_curve": 1, "ramp_beats": 0.25,
               "tone_glide_beats": 0.5, "tone_decay_beats": 6, "tone_level": 1},
    "noise_crash": {"filter_q": 0.7071, "sweep_curve": 1, "cutoff_start_hz": 1000,
                    "level_end_db": -60, "ramp_beats": 16},
    "reverse_crash": {"filter_q": 0.7071, "sweep_curve": 1, "tail_beats": 0,
                      "tone_wave": "metal", "level_start_db": -60, "ramp_beats": 4},
}


@pytest.mark.parametrize("kind", KINDS)
def test_resolved_values_per_kind(kind: str) -> None:
    resolved = resolve({**BASE, "kind": kind})
    for name, value in RESOLVED[kind].items():
        assert resolved[name] == value, (kind, name)
    if kind == "riser":  # omitted kind resolves exactly like riser
        assert resolve(BASE)["sweep_curve"] == 1.5
        assert resolve(BASE)["filter_q"] == 1.2
    # a given value always beats the kind default
    assert resolve({**BASE, "kind": kind, "filter_q": 9})["filter_q"] == 9


def test_defaults_satisfy_the_cross_field_rules_at_every_tempo() -> None:
    for kind, d in KIND_DEFAULTS.items():
        beats = d["length_beats"] + d["tail_beats"]
        for bpm in (60, 60.5, 120, 135, 150, 200):
            assert beats * 60000 / bpm <= MAX_FILE_MS, (kind, bpm)  # rule A
        resolved = resolve({**BASE, "kind": kind})
        assert resolved["noise_level"] > 0 or resolved["tone_level"] > 0  # rule B
        assert resolved["cut_beats"] < resolved["length_beats"]  # rule C
    # rule A's bound is exactly 32 bars + the longest tail at 120 BPM
    assert (128 + 16) * 60000 / 120 == MAX_FILE_MS
    assert "at most 72000 ms" in FX["$comment"]


def test_reverse_crash_has_no_tail() -> None:
    FX_V.validate({**BASE, "kind": "reverse_crash", "tail_beats": 0})
    for bad in (0.25, 4, 16):
        with pytest.raises(ValidationError):
            FX_V.validate({**BASE, "kind": "reverse_crash", "tail_beats": bad})
    for kind in KINDS[:-1]:
        FX_V.validate({**BASE, "kind": kind, "tail_beats": 16})


def test_boundary_frames_by_hand() -> None:
    """$comment point 1 at the note's section 3 numbers: 32 bars at 135 BPM, 48 kHz."""
    assert round(128 * 60 * 48000 / 135) == 2730667
    assert round((128 + 4) * 60 * 48000 / 135) == 2816000
    text = FX["$comment"]
    for needle in ("round((length_beats + tail_beats) * 60 * sample_rate / bpm) frames",
                   "round(length_beats * 60 * sample_rate / bpm)", "anchor end",
                   "boundary - length_beats", "for EVERY kind",
                   "it equals the frame count N, one past its last frame N - 1",
                   "boundary_frame = N"):
        assert needle in text, needle
    # reverse_crash default (4 beats, no tail) at 135 BPM, 48 kHz: boundary_frame = N = 85333,
    # one past the last frame index 85332
    assert round(4 * 60 * 48000 / 135) == round((4 + 0) * 60 * 48000 / 135) == 85333
    desc = META["properties"]["features"]["properties"]["boundary_frame"]["description"]
    assert "for every kind" in desc and "one past the last frame N - 1" in desc


def test_fx_random_values_inside_and_outside_range() -> None:
    rng = random.Random(482)
    for _ in range(400):
        name = rng.choice(sorted(FX_RANGES))
        low, high, _default = FX_RANGES[name]
        kind = rng.choice(KINDS[:-1])  # reverse_crash pins tail_beats to 0
        value = rng.uniform(low, high)
        if name in QUARTER_BEAT_FIELDS:
            value = rng.randint(int(low * 4), int(high * 4)) / 4
        FX_V.validate({**BASE, "kind": kind, name: value})
        span = high - low
        excess = rng.uniform(0.001, 1) * span
        outside = rng.choice((low - excess, high + excess))
        if name in QUARTER_BEAT_FIELDS:
            outside = rng.choice((low - 0.25 * rng.randint(1, 8), high + 0.25 * rng.randint(1, 8)))
        with pytest.raises(ValidationError):
            FX_V.validate({**BASE, "kind": kind, name: outside})


def test_fx_random_full_documents_validate() -> None:
    """Every field at once, random over the whole range, for every kind."""
    rng = random.Random(4820)
    for _ in range(300):
        kind = rng.choice(KINDS)
        doc = {**BASE, "seed": rng.randrange(0, 2**32), "kind": kind,
               "variants": rng.randint(1, 8), "preset": "p" * rng.randint(0, 64)}
        for name, (lo, hi, _d) in FX_RANGES.items():
            doc[name] = (rng.randint(int(lo * 4), int(hi * 4)) / 4
                         if name in QUARTER_BEAT_FIELDS else rng.uniform(lo, hi))
        for name, (values, _d) in FX_ENUMS.items():
            if name != "kind":
                doc[name] = rng.choice(values)
        if kind == "reverse_crash":
            doc["tail_beats"] = 0
        FX_V.validate(doc)
        doc["wobble"] = 1
        with pytest.raises(ValidationError):
            FX_V.validate(doc)


def test_contract_text_fixes_the_agreed_definitions() -> None:
    text = FX["$comment"]
    for needle in (
        "ONE time-varying 2nd-order filter whose cutoff is updated every sample, not a blend",
        "184 of 280 frames", "state-variable filter (Zavalishin)",
        "times 1 / filter_q (0 dB peak gain)", "the min is a derived corner",
        "acts on the noise layer only", "audio_engine.dsp.substreams",
        "correlation 1 - stereo_width", "sqrt(1000 / f)",
        "p = min(1, t / length_beats)", "min(1, t / ramp_beats) ^ level_curve",
        "phase 0 at t = 0", "fall of 60 dB over tone_decay_beats",
        "5 ms linear fade-out that ends there", "Cross-field rule A", "Cross-field rule B",
        "Cross-field rule C", "laser_fx.echo_v2", "laser_fx.reverb_wet",
        "reversed in time", "FILE time", "(1 - phi)^4", "within one LSB and never above",
        "byte-identical", "Reject out-of-range values, never clamp",
        "Defaults are placeholders", "abeltongod-audio-engine-fx",
        "boundary_frame and anchor", "echo_note is new",
    ):
        assert needle in text, needle
    desc = FX["description"]
    for needle in ("PER-KIND DEFAULTS LIVE IN THIS FILE", "riser branch also applies when "
                   "`kind` is omitted", "omitted = the resolved length_beats",
                   "Presets are named overrides", "PROPOSALS", "D-032", "Not part of v0.1"):
        assert needle in desc, needle


def test_metal_partials_are_the_hat_metal_bank() -> None:
    partials = "205.3, 304.4, 369.6, 522.7, 540 and 800 Hz"
    assert partials in load("hat-params.schema.json")["$comment"]
    assert partials in FX["$comment"]


def test_shared_fields_have_the_same_definition_as_laser_v02() -> None:
    laser = load("laser-params.schema.json")
    lprops = dict(laser["properties"])
    for branch in laser["allOf"]:
        lprops.update(branch.get("then", {}).get("properties", {}))

    def core(prop: dict) -> dict:
        return {k: v for k, v in prop.items() if k != "description"}

    props = FX["properties"]
    for name in ("seed", "variants", "sample_rate", "bit_depth", "preset", "reverb_size",
                 "reverb_predelay_ms", "reverb_damp_hz", "reverb_width", "echo_mix",
                 "echo_feedback", "echo_pingpong"):
        assert core(props[name]) == core(lprops[name]), name
    for name in ("bpm", "stereo_width", "reverb_mix", "echo_damp_hz"):
        assert (props[name]["minimum"], props[name]["maximum"]) == (
            lprops[name]["minimum"], lprops[name]["maximum"]), name
    # documented differences
    assert (lprops["reverb_decay_ms"]["maximum"], props["reverb_decay_ms"]["maximum"]) == (
        6000, 8000)
    assert (lprops["echo_damp_hz"]["default"], props["echo_damp_hz"]["default"]) == (20000, 6000)
    kick = load("kick-params.schema.json")["properties"]
    # same range; fx defaults 0 / -1.0 (kick 0.2 / -0.3)
    for name in ("drive", "peak_ceiling_dbfs"):
        assert (props[name]["minimum"], props[name]["maximum"]) == (
            kick[name]["minimum"], kick[name]["maximum"]), name


# --- sample-metadata: category fx --------------------------------------------------------------

FX_DOC = {
    "schema_version": "0.2", "file": "fx.wav", "category": "fx",
    "engine": {"name": "abeltongod-audio-engine-fx", "version": "0.1.0"},
    "parameters": {"schema_version": "0.1", "seed": 7, "bpm": 135, "kind": "riser"},
    "features": {
        "peak_dbfs": -1.0, "length_ms": 29333.3, "spectral_centroid_hz": 3000.0,
        "boundary_frame": 1365333, "anchor": "start",
    },
    "created_at": "2026-11-07T12:00:00+00:00",
}
OTHER_ENGINES = {
    "clap": "abeltongod-audio-engine-clap", "hat": "abeltongod-audio-engine-hat",
    "snare": "abeltongod-audio-engine-snare", "rim": "abeltongod-audio-engine-rim",
    "bass": "abeltongod-audio-engine-bass", "laser": "abeltongod-audio-engine-laser",
    "perc": "abeltongod-audio-engine-perc",
}


def _changed(path: str, value, base: dict = FX_DOC) -> dict:
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


def test_metadata_category_enum_ends_with_fx() -> None:
    assert META["properties"]["category"]["enum"] == [
        "kick", "clap", "hat", "snare", "rim", "bass", "laser", "perc", "fx"]


def test_metadata_fx_and_other_categories_still_validate() -> None:
    META_V.validate(FX_DOC)
    for kind in KINDS:
        META_V.validate(_changed("parameters.kind", kind))
    META_V.validate(_changed("features.anchor", "end"))
    META_V.validate(_changed("features.boundary_frame", 0))
    META_V.validate(json.loads((ROOT / "tests/fixtures/sidecars/kick-v01.json").read_text("utf-8")))
    for category, engine in OTHER_ENGINES.items():
        doc = copy.deepcopy(FX_DOC)
        doc.update(category=category, file=f"{category}.wav")
        doc["engine"]["name"] = engine
        del doc["features"]["boundary_frame"], doc["features"]["anchor"]
        META_V.validate(doc)


METADATA_INVALID = {
    "fx with schema_version 0.1": _changed("schema_version", "0.1"),
    "fx with the kick engine name": _changed("engine.name", "abeltongod-audio-engine"),
    **{f"fx with the {c} engine name": _changed("engine.name", e)
       for c, e in OTHER_ENGINES.items()},
    "fx parameters without seed": _changed("parameters.seed", ...),
    "fx parameters without bpm": _changed("parameters.bpm", ...),
    "fx parameters without schema_version": _changed("parameters.schema_version", ...),
    "fx parameters with version 0.2": _changed("parameters.schema_version", "0.2"),
    "fx without boundary_frame": _changed("features.boundary_frame", ...),
    "fx without anchor": _changed("features.anchor", ...),
    "anchor middle": _changed("features.anchor", "middle"),
    "boundary_frame negative": _changed("features.boundary_frame", -1),
    "boundary_frame fractional": _changed("features.boundary_frame", 1.5),
    "boundary_frame as string": _changed("features.boundary_frame", "1365333"),
    "category riser (a kind, not a category)": _changed("category", "riser"),
    "category FX": _changed("category", "FX"),
}


@pytest.mark.parametrize("doc", METADATA_INVALID.values(), ids=METADATA_INVALID)
def test_metadata_fx_invalid_instances(doc) -> None:
    with pytest.raises(ValidationError):
        META_V.validate(doc)


@pytest.mark.parametrize("category", sorted(OTHER_ENGINES))
def test_fx_engine_name_and_fx_features_are_refused_for_other_categories(category: str) -> None:
    doc = copy.deepcopy(FX_DOC)
    doc["category"] = category
    with pytest.raises(ValidationError):  # fx engine name
        META_V.validate(doc)
    doc["engine"]["name"] = OTHER_ENGINES[category]
    with pytest.raises(ValidationError):  # boundary_frame / anchor are fx-only
        META_V.validate(doc)
    for field in ("boundary_frame", "anchor"):
        one = copy.deepcopy(doc)
        del one["features"]["anchor" if field == "boundary_frame" else "boundary_frame"]
        with pytest.raises(ValidationError):
            META_V.validate(one)


def test_fx_contract_category_is_registered_with_the_contract_engine_name() -> None:
    """#482 engine step: the engine renders fx under the engine name this contract fixes."""
    from audio_engine.categories import CONTRACT_CATEGORIES, get_category, registered_categories

    assert CONTRACT_CATEGORIES[-1] == "fx"
    assert "fx" in registered_categories()
    assert get_category("fx").engine_name == "abeltongod-audio-engine-fx"
    assert get_category("fx").metadata_schema_version == "0.2"
