"""atmos-params v0.1 (#526, D-034; input: docs/research/2026-11-08_parking-atmos-drones.md).

Expected ranges, per-kind defaults and limits are written out here by hand, not read from the
schema, so a changed number in the contract turns a test red and has to be changed on purpose.
The cross-field rules A-E are engine checks (JSON Schema cannot compare fields); this file
re-states them independently (``rule_violations``) to check that every default and every
worked example in the contract satisfies them. The warm-up rule (#525 review point 2) is
checked with an own state-variable filter, not the engine's.
"""

import json
import math
import random
import re
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts"


def load(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


ATMOS = load("atmos-params.schema.json")
V = Draft202012Validator(ATMOS)
TEXT = ATMOS["$comment"]
BASE = {"schema_version": "0.1", "seed": 1, "bpm": 135}
KINDS = ["noise_bed", "drone", "resonant", "granular"]
BARS = [1, 2, 4, 8, 16, 32]
MAX_FILE_MS = 72000  # cross-field rule A

# name: (minimum, maximum, top-level default); None = per-kind default
RANGES = {
    "bpm": (60, 200, None),
    "fade_in_beats": (0, 64, 4),
    "fade_out_beats": (0, 64, 4),
    "tail_beats": (0, 64, 0),
    "peak_ceiling_dbfs": (-12, -0.1, -1.0),
    "hp_hz": (20, 2000, None),
    "lp_hz": (200, 20000, None),
    "tilt_db_oct": (-6, 3, -3),
    "stereo_width": (0, 1, 0.7),
    "mono_below_hz": (0, 300, 120),
    "filter_hz": (20, 20000, None),
    "filter_q": (0.5, 12, None),
    "move_depth_oct": (0, 3, None),
    "amp_move_db": (0, 12, None),
    "pan_move": (0, 1, 0),
    "pump_depth": (0, 1, 0),
    "drive": (0, 1, 0),
    "cents": (-50, 50, 0),
    "brightness_db_oct": (-18, 0, -9),
    "drift_db": (0, 12, 3),
    "max_tuning_cents": (0.5, 20, 5),
    "res_q": (2, 200, 40),
    "grain_ms": (10, 500, 80),
    "grain_density": (1, 200, 30),
    "grain_pitch_cents": (0, 1200, 0),
    "grain_spread": (0, 1, 0.5),
    "grain_pan": (0, 1, 0.6),
    "reverb_mix": (0, 1, None),
    "reverb_size": (0, 1, 0.5),
    "reverb_decay_ms": (100, 12000, 4000),
    "reverb_predelay_ms": (0, 200, 0),
    "reverb_damp_hz": (300, 20000, 6000),
    "reverb_width": (0, 1, 1),
}
# integer fields: (minimum, maximum, default); None = per-kind default
INTEGERS = {
    "seed": (0, 4294967295, None),
    "variants": (1, 8, 1),
    "move_cycles": (0, 64, None),
    "note": (24, 72, 36),
    "partials": (1, 48, 12),
    "detune_bins": (0, 8, 1),
}
QUARTER_BEAT_FIELDS = ("fade_in_beats", "fade_out_beats", "tail_beats")
ENUMS = {
    "kind": (KINDS, "noise_bed"),
    "bars": (BARS, 8),
    "loop_mode": (["seamless", "oneshot"], "seamless"),
    "sample_rate": ([44100, 48000], 48000),
    "bit_depth": ([16, 24], 24),
    "filter_mode": (["off", "bp", "lp", "hp"], None),
    "move_shape": (["sine", "smooth_random"], "sine"),
    "granular_source": (["noise", "drone", "metal"], "drone"),
}
FIELDS = {"schema_version", "intervals", "preset", *RANGES, *INTEGERS, *ENUMS}
PER_KIND = {"hp_hz", "lp_hz", "filter_mode", "filter_hz", "filter_q", "move_cycles",
            "move_depth_oct", "amp_move_db", "reverb_mix"}

# Per-kind defaults (the note's section 6.4, with the #525 review fixes: moving-filter mode,
# centre and Q per kind; tonal hp_hz fixed instead of 0.8 * f0).
KIND_DEFAULTS = {
    "noise_bed": {"hp_hz": 150, "lp_hz": 8000, "filter_mode": "lp", "filter_hz": 3000,
                  "filter_q": 0.7071, "move_cycles": 2, "move_depth_oct": 1, "amp_move_db": 2,
                  "reverb_mix": 0.3},
    "drone": {"hp_hz": 20, "lp_hz": 6000, "filter_mode": "off", "filter_hz": 1000,
              "filter_q": 0.7071, "move_cycles": 1, "move_depth_oct": 0, "amp_move_db": 0,
              "reverb_mix": 0.35},
    "resonant": {"hp_hz": 20, "lp_hz": 10000, "filter_mode": "lp", "filter_hz": 4000,
                 "filter_q": 0.7071, "move_cycles": 1, "move_depth_oct": 0.5, "amp_move_db": 2,
                 "reverb_mix": 0.3},
    "granular": {"hp_hz": 100, "lp_hz": 12000, "filter_mode": "off", "filter_hz": 2000,
                 "filter_q": 0.7071, "move_cycles": 1, "move_depth_oct": 0, "amp_move_db": 2,
                 "reverb_mix": 0.4},
}


def matching_branches(doc: dict) -> list[dict]:
    return [b for b in ATMOS["allOf"] if Draft202012Validator(b["if"]).is_valid(doc)]


def resolve(doc: dict) -> dict:
    """Independent re-statement of the documented order: top-level defaults, then the branch."""
    out = dict(doc)
    for name, prop in ATMOS["properties"].items():
        if name not in out and "default" in prop:
            out[name] = prop["default"]
    for branch in matching_branches(doc):
        for name, prop in branch["then"]["properties"].items():
            if name not in out and "default" in prop:
                out[name] = prop["default"]
    return out


# --- independent re-statement of the cross-field rules ($comment points 1, 4, 6, 10, 11) -----

def loop_frames(bars: int, bpm: float, sr: int) -> int:
    return round(240 * bars * sr / bpm)


def f0_hz(note: int, cents: float) -> float:
    return 440.0 * 2.0 ** ((note - 69 + cents / 100.0) / 12.0)


def tuning_error_cents(p: dict) -> float:
    n = loop_frames(p["bars"], p["bpm"], p["sample_rate"])
    f0 = f0_hz(p["note"], p["cents"])
    b0 = max(1, round(f0 * n / p["sample_rate"]))
    return abs(1200.0 * math.log2(b0 * p["sample_rate"] / (n * f0)))


def rule_violations(p: dict) -> set[str]:
    bad = set()
    beats = 4 * p["bars"] + (p["tail_beats"] if p["loop_mode"] == "oneshot" else 0)
    if beats * 60000 / p["bpm"] > MAX_FILE_MS:
        bad.add("A")
    if p["lp_hz"] < 1.5 * p["hp_hz"]:
        bad.add("B")
    tonal = p["kind"] == "drone" or (p["kind"] == "granular"
                                     and p["granular_source"] in ("drone", "metal"))
    if tonal and tuning_error_cents(p) > p["max_tuning_cents"]:
        bad.add("C")
    if p["filter_mode"] != "off":
        half = p["move_depth_oct"] / 2
        if p["filter_hz"] * 2 ** -half < 20 or p["filter_hz"] * 2 ** half > 0.45 * p["sample_rate"]:
            bad.add("D")
    if p["loop_mode"] == "oneshot" and p["fade_in_beats"] + p["fade_out_beats"] > 4 * p["bars"]:
        bad.add("E")
    return bad


# --- field set, ranges, enums ------------------------------------------------------------------

def test_field_set_and_required() -> None:
    assert set(ATMOS["properties"]) == FIELDS
    assert ATMOS["required"] == ["schema_version", "seed", "bpm"]
    assert ATMOS["additionalProperties"] is False
    for absent in ("length_beats", "length_ms", "category", "cutoff_start_hz", "cutoff_end_hz",
                   "lp_ratio", "source", "key", "echo_mix"):
        assert absent not in ATMOS["properties"], absent


@pytest.mark.parametrize("name", sorted(RANGES))
def test_range_matches_table_and_edges(name: str) -> None:
    low, high, default = RANGES[name]
    prop = ATMOS["properties"][name]
    assert (prop["type"], prop["minimum"], prop["maximum"], prop.get("default")) == (
        "number", low, high, default)
    for ok in (low, high):
        V.validate({**BASE, name: ok})
    span = high - low
    for bad in (low - span / 100, high + span / 100):
        with pytest.raises(ValidationError):
            V.validate({**BASE, name: bad})


@pytest.mark.parametrize("name", sorted(INTEGERS))
def test_integer_fields(name: str) -> None:
    low, high, default = INTEGERS[name]
    prop = ATMOS["properties"][name]
    assert (prop["type"], prop["minimum"], prop["maximum"], prop.get("default")) == (
        "integer", low, high, default)
    for ok in (low, high):
        V.validate({**BASE, name: ok})
    for bad in (low - 1, high + 1, low + 0.5, str(low), True if low > 1 else None):
        with pytest.raises(ValidationError):
            V.validate({**BASE, name: bad})


@pytest.mark.parametrize("name", sorted(ENUMS))
def test_enums(name: str) -> None:
    values, default = ENUMS[name]
    prop = ATMOS["properties"][name]
    assert prop["enum"] == values
    assert prop.get("default") == default
    for v in values:
        V.validate({**BASE, name: v})
    for bad in ("", None, "Drone", "hp_lp", "pad", 3, 64, 96000, 32.5):
        if bad not in values:
            with pytest.raises(ValidationError):
                V.validate({**BASE, name: bad})


@pytest.mark.parametrize("name", QUARTER_BEAT_FIELDS)
def test_oneshot_beats_are_on_a_quarter_beat_grid(name: str) -> None:
    assert ATMOS["properties"][name]["multipleOf"] == 0.25
    for ok in (0.25, 2.5, 3.75, 64):
        V.validate({**BASE, "loop_mode": "oneshot", name: ok})
    for bad in (0.1, 2.3, 1.0625):
        with pytest.raises(ValidationError):
            V.validate({**BASE, "loop_mode": "oneshot", name: bad})


def test_intervals() -> None:
    prop = ATMOS["properties"]["intervals"]
    assert prop["default"] == [0, 7, 12]
    for ok in ([0], [0, 7, 12], [0, 3, 7, 10, 12, 36], [0, 36], [0, 12, 7]):
        V.validate({**BASE, "intervals": ok})
    for bad in ([], [7], [0, 0], [0, 7, 7], [0, 37], [0, -12], [0, 1, 2, 3, 4, 5, 6], [0, 7.5],
                [0.0, "7"], 0, "0,7"):
        with pytest.raises(ValidationError):
            V.validate({**BASE, "intervals": bad})


def test_required_version_and_unknown_fields() -> None:
    V.validate(BASE)
    for doc in ({"seed": 1, "bpm": 135}, {"schema_version": "0.1", "bpm": 135},
                {"schema_version": "0.1", "seed": 1}, {**BASE, "schema_version": "0.2"},
                {**BASE, "wobble": 1}, {**BASE, "source": "drone"},
                {**BASE, "preset": "x" * 65}, {**BASE, "preset": 3}):
        with pytest.raises(ValidationError):
            V.validate(doc)
    V.validate({**BASE, "preset": "x" * 64})


# --- per-kind defaults ---------------------------------------------------------------------------

def test_per_kind_defaults_match_the_table() -> None:
    assert len(ATMOS["allOf"]) == len(KINDS)
    for kind, expected in KIND_DEFAULTS.items():
        (branch,) = matching_branches({**BASE, "kind": kind})
        got = {n: p["default"] for n, p in branch["then"]["properties"].items()}
        assert got == expected, kind


def test_omitted_kind_takes_the_noise_bed_branch_only() -> None:
    (branch,) = matching_branches(BASE)
    (noise_bed,) = matching_branches({**BASE, "kind": "noise_bed"})
    assert branch is noise_bed
    assert resolve(BASE) == resolve({**BASE, "kind": "noise_bed"})


def test_every_kind_resolves_every_field_and_no_field_is_derived() -> None:
    no_top = {n for n, p in ATMOS["properties"].items() if "default" not in p}
    assert no_top - {"schema_version", "seed", "bpm", "preset"} == PER_KIND
    for kind in KINDS:
        resolved = resolve({**BASE, "kind": kind})
        assert set(resolved) == FIELDS - {"preset"}, kind
        V.validate(resolved)
    assert not any("x-derived-default" in p for p in ATMOS["properties"].values())


def test_no_field_has_both_a_top_level_and_a_branch_default() -> None:
    top = {n for n, p in ATMOS["properties"].items() if "default" in p}
    for branch in ATMOS["allOf"]:
        in_branch = {n for n, p in branch["then"]["properties"].items() if "default" in p}
        assert not top & in_branch, (branch["if"], top & in_branch)


def test_a_given_value_beats_the_kind_default() -> None:
    for kind in KINDS:
        assert resolve({**BASE, "kind": kind, "filter_q": 9})["filter_q"] == 9
        assert resolve({**BASE, "kind": kind, "hp_hz": 400})["hp_hz"] == 400


@pytest.mark.parametrize("sr", [44100, 48000])
def test_defaults_satisfy_every_cross_field_rule(sr: int) -> None:
    """Every kind's defaults, both loop modes, every tempo the range allows for the default
    8 bars, and every note at the default tuning tolerance (rule C)."""
    for kind in KINDS:
        for loop_mode in ("seamless", "oneshot"):
            for bpm in (60, 60.5, 106.67, 120, 128, 135, 140, 150, 174, 200):
                p = resolve({**BASE, "kind": kind, "bpm": bpm, "sample_rate": sr,
                             "loop_mode": loop_mode})
                assert rule_violations(p) == set(), (kind, loop_mode, bpm)
    for granular_source in ("drone", "metal"):
        for note in range(24, 73):
            p = resolve({**BASE, "kind": "granular", "granular_source": granular_source,
                         "note": note, "bpm": 200, "sample_rate": sr})
            assert rule_violations(p) == set(), note


# --- cross-field rules: curated cases ---------------------------------------------------------

CROSS_FIELD = {
    "A: 32 bars at 106 BPM (72.45 s)": ({"bars": 32, "bpm": 106}, {"A"}),
    "A edge: 32 bars at 106.67 BPM": ({"bars": 32, "bpm": 106.67}, set()),
    "A: oneshot tail counts": ({"bars": 16, "bpm": 60, "loop_mode": "oneshot",
                                "tail_beats": 8.25}, {"A"}),
    "A edge: oneshot exactly 72 s": ({"bars": 16, "bpm": 60, "loop_mode": "oneshot",
                                      "tail_beats": 8}, set()),
    "A: tail ignored when seamless": ({"bars": 16, "bpm": 60, "tail_beats": 64}, set()),
    "B: lp below 1.5 * hp": ({"hp_hz": 1000, "lp_hz": 1499}, {"B"}),
    "B edge: lp = 1.5 * hp": ({"hp_hz": 1000, "lp_hz": 1500}, set()),
    "C: drone 1 bar at 200 BPM, note 24, 20 cents": (
        {"kind": "drone", "bars": 1, "bpm": 200, "note": 24, "max_tuning_cents": 10}, {"C"}),
    "C: same at 11 cents passes": (
        {"kind": "drone", "bars": 1, "bpm": 200, "note": 24, "max_tuning_cents": 11}, set()),
    "C: resonant is not bin-locked": (
        {"kind": "resonant", "bars": 1, "bpm": 200, "note": 24, "max_tuning_cents": 0.5},
        set()),
    "C: granular noise source is not tonal": (
        {"kind": "granular", "granular_source": "noise", "bars": 1, "bpm": 200, "note": 24,
         "max_tuning_cents": 0.5}, set()),
    "D: lowest cutoff below 20 Hz": ({"filter_hz": 30, "move_depth_oct": 2}, {"D"}),
    "D edge: lowest cutoff exactly 20 Hz": ({"filter_hz": 40, "move_depth_oct": 2}, set()),
    "D: highest cutoff above 0.45 * 44100": (
        {"filter_hz": 15000, "move_depth_oct": 1, "sample_rate": 44100}, {"D"}),
    "D: off has no movement": ({"kind": "drone", "filter_hz": 20, "move_depth_oct": 3}, set()),
    "E: fades longer than the loop": ({"loop_mode": "oneshot", "bars": 1,
                                       "fade_in_beats": 2.25, "fade_out_beats": 2}, {"E"}),
    "E edge: fades fill the loop": ({"loop_mode": "oneshot", "bars": 1, "fade_in_beats": 2,
                                     "fade_out_beats": 2}, set()),
}


@pytest.mark.parametrize("change, expected", CROSS_FIELD.values(), ids=CROSS_FIELD)
def test_cross_field_rules_curated(change: dict, expected: set) -> None:
    doc = {**BASE, **change}
    V.validate(doc)  # the schema cannot compare fields: the engine rejects these
    assert rule_violations(resolve(doc)) == expected


def test_the_contract_names_every_rule_and_its_worked_examples() -> None:
    for needle in (
        "Cross-field rule A", "Cross-field rule B: lp_hz >= 1.5 * hp_hz", "Tuning rule C",
        "Cross-field rule D (filter_mode not off): fc_min >= 20 and fc_max <= 0.45 * sr",
        "Cross-field rule E (oneshot): fade_in_beats + fade_out_beats <= 4 * bars",
        "Reject cross-field rules A, B, C, D and E with an error text",
        "tail_beats counts in oneshot only", "32 bars need bpm >= 106.67",
        "Reject out-of-range values, never clamp", "byte-identical",
        "abeltongod-audio-engine-atmos", "NOT part of this v0.1 file",
    ):
        assert needle in TEXT, needle
    desc = ATMOS["description"]
    for needle in ("PER-KIND DEFAULTS LIVE IN THIS FILE", "noise_bed branch also applies when "
                   "`kind` is omitted", "PROPOSALS", "D-034", "Not part of v0.1",
                   "No field has a derived default"):
        assert needle in desc, needle


# --- length and the integer-N lists (#525 review point 3) --------------------------------------

def test_loop_length_examples_by_hand() -> None:
    assert loop_frames(1, 200, 48000) == 57600
    assert loop_frames(8, 135, 48000) == 682667  # 682666.67
    assert 240 * 1 * 44100 / 128 == 82687.5 and loop_frames(1, 128, 44100) == 82688
    assert "82687.5 -> 82688" in TEXT and "round half to even" in TEXT
    assert "round(240 * bars * sr / bpm)" in TEXT


def _integer_bars(sr: int, bpm: int) -> list[int]:
    return [b for b in BARS if Fraction(240 * b * sr, bpm).denominator == 1]


def test_integer_length_lists_in_the_contract_are_complete() -> None:
    """The sentences of $comment point 1, recomputed with exact fractions."""
    every = {sr: [t for t in range(120, 151) if _integer_bars(sr, t) == BARS]
             for sr in (44100, 48000)}
    assert every == {48000: [120, 125, 128, 144, 150],
                     44100: [120, 125, 126, 135, 140, 144, 147, 150]}
    assert _integer_bars(44100, 128) == [2, 4, 8, 16, 32]
    for sr, never in ((48000, [130, 132, 135, 138, 140, 142, 145]),
                      (44100, [130, 132, 138, 142, 145])):
        for t in never:
            assert _integer_bars(sr, t) == [], (sr, t)
    assert ("at 48000 Hz for every bars at 120, 125, 128, 144 and 150 BPM, never at 130, 132, "
            "135, 138, 140, 142 or 145") in TEXT
    assert ("at 44100 Hz for every bars at 120, 125, 126, 135, 140, 144, 147 and 150, at 128 "
            "only from 2 bars, never at 130, 132, 138, 142 or 145") in TEXT
    assert "Of the whole-number tempos 120-150 BPM" in TEXT


def test_tuning_example_of_rule_c_by_hand() -> None:
    p = {"bars": 1, "bpm": 200, "sample_rate": 48000, "note": 24, "cents": 0}
    assert abs(f0_hz(24, 0) - 32.7032) < 1e-4
    assert round(f0_hz(24, 0) * 57600 / 48000) == 39
    assert abs(tuning_error_cents(p) - 10.79) < 0.01
    half_bin = 200 / 240 / 2
    assert round(1200 * math.log2((f0_hz(24, 0) + half_bin) / f0_hz(24, 0)), 1) == 21.9
    assert round(1200 * math.log2(f0_hz(24, 0) / (f0_hz(24, 0) - half_bin)), 1) == 22.2
    assert "lands on bin 39, 10.8 cents flat" in TEXT


# --- warm-up from the decay (#525 review point 2) ----------------------------------------------

def _filter_factor() -> int:
    m = re.search(r"P_filter = ceil\((\d+) \* tau / T_loop\)", TEXT)
    assert m, "warm-up rule for the moving filter is missing"
    return int(m.group(1))


def p_filter(fc_min: float, q: float, bars: int, bpm: float, sr: int) -> int:
    tau = q / (math.pi * fc_min)
    return math.ceil(_filter_factor() * tau / (loop_frames(bars, bpm, sr) / sr))


def _own_svf(x: np.ndarray, fc: np.ndarray, q: float, sr: int, mode: str) -> np.ndarray:
    """Own TPT state-variable filter (Zavalishin), written for this test."""
    ic1 = ic2 = 0.0
    k = 1.0 / q
    out = np.empty_like(x)
    g_all = np.tan(np.pi * fc / sr)
    for n in range(len(x)):
        g = g_all[n]
        a1 = 1.0 / (1.0 + g * (g + k))
        a2 = g * a1
        a3 = g * a2
        v3 = x[n] - ic2
        v1 = a1 * ic1 + a2 * v3
        v2 = ic2 + a2 * ic1 + a3 * v3
        ic1 = 2.0 * v1 - ic1
        ic2 = 2.0 * v2 - ic2
        out[n] = v1 * k if mode == "bp" else (v2 if mode == "lp" else x[n] - k * v1 - v2)
    return out


@pytest.mark.parametrize("q, mode", [(12, "bp"), (0.5, "lp")])
def test_warm_up_rule_converges_at_the_worst_corner(q: float, mode: str) -> None:
    """Review #525 point 2: static cutoff 20 Hz, 1 bar at 200 BPM, 48 kHz. After P_filter
    warm-up loops the kept period and the next differ by less than 1/16 of a 24-bit LSB."""
    sr, bars, bpm, fc = 48000, 1, 200, 20.0
    n = loop_frames(bars, bpm, sr)
    p = p_filter(fc, q, bars, bpm, sr)
    x = np.random.default_rng(526).standard_normal(n)
    y = _own_svf(np.tile(x, p + 2), np.full(n * (p + 2), fc), q, sr, mode)
    kept, nxt = y[p * n:(p + 1) * n], y[(p + 1) * n:]
    assert np.max(np.abs(kept - nxt)) / np.max(np.abs(kept)) < 2.0 ** -23 / 16


def test_warm_up_counts_by_hand() -> None:
    assert _filter_factor() == 20
    assert p_filter(20, 12, 1, 200, 48000) == 4  # tau 0.191 s, T_loop 1.2 s
    assert p_filter(20, 0.5, 1, 200, 48000) == 1
    assert p_filter(20, 12, 32, 107, 48000) == 1
    assert "P_filter = 4" in TEXT and "tau = 0.191 s" in TEXT
    assert "tau = filter_q / (pi * fc_min)" in TEXT
    # reverb: 2.4 * T60 is 144 dB of decay (T60 = 60 dB)
    assert 2.4 * 60 == 144
    assert "P_reverb = ceil((2.4 * reverb_decay_ms + reverb_predelay_ms) / 1000 / T_loop)" in TEXT
    t_loop = loop_frames(1, 200, 48000) / 48000
    assert math.ceil((2.4 * 12000 + 200) / 1000 / t_loop) == 25  # longest reverb, shortest loop
    assert "rejects its own output" in TEXT and "LAST period is kept" in TEXT
    # the depth moves the lowest cutoff down: centre 40 Hz, 2 octaves -> fc_min 20 Hz
    assert 40 * 2 ** (-2 / 2) == 20


def test_dark_reverb_variant_is_in_range() -> None:
    """Review #525 point 4: note A2's dark variant is a 400 Hz high cut."""
    V.validate({**BASE, "reverb_damp_hz": 400})
    assert ATMOS["properties"]["reverb_damp_hz"]["minimum"] <= 400


def test_moving_filter_fields_exist() -> None:
    """Review #525 point 1: mode, centre and Q of the moving filter are contract fields."""
    props = ATMOS["properties"]
    assert props["filter_mode"]["enum"] == ["off", "bp", "lp", "hp"]
    assert (props["filter_hz"]["minimum"], props["filter_hz"]["maximum"]) == (20, 20000)
    assert (props["filter_q"]["minimum"], props["filter_q"]["maximum"]) == (0.5, 12)
    assert "fc(n) = filter_hz * 2^(move_depth_oct / 2 * c(n))" in TEXT
    assert "state-variable filter (Zavalishin)" in TEXT


# --- seeded random draws over the whole range --------------------------------------------------

def _random_doc(rng: random.Random) -> dict:
    doc = {**BASE, "variants": rng.randint(1, 8), "preset": "p" * rng.randint(0, 64)}
    for name, (lo, hi, _d) in RANGES.items():
        doc[name] = (rng.randint(int(lo * 4), int(hi * 4)) / 4
                     if name in QUARTER_BEAT_FIELDS else rng.uniform(lo, hi))
    for name, (lo, hi, _d) in INTEGERS.items():
        doc[name] = rng.randint(lo, hi)
    for name, (values, _d) in ENUMS.items():
        doc[name] = rng.choice(values)
    rest = rng.sample(range(1, 37), rng.randint(0, 5))
    doc["intervals"] = [0, *rest]
    return doc


def test_random_values_inside_and_outside_range() -> None:
    rng = random.Random(526)
    for _ in range(400):
        name = rng.choice(sorted(RANGES))
        low, high, _d = RANGES[name]
        kind = rng.choice(KINDS)
        value = rng.uniform(low, high)
        if name in QUARTER_BEAT_FIELDS:
            value = rng.randint(int(low * 4), int(high * 4)) / 4
        V.validate({**BASE, "kind": kind, name: value})
        excess = rng.uniform(0.001, 1) * (high - low)
        outside = rng.choice((low - excess, high + excess))
        if name in QUARTER_BEAT_FIELDS:
            outside = rng.choice((low - 0.25 * rng.randint(1, 8), high + 0.25 * rng.randint(1, 8)))
        with pytest.raises(ValidationError):
            V.validate({**BASE, "kind": kind, name: outside})


def test_random_full_documents_validate_and_unknown_keys_fail() -> None:
    rng = random.Random(5260)
    for _ in range(300):
        doc = _random_doc(rng)
        V.validate(doc)
        doc["wobble"] = 1
        with pytest.raises(ValidationError):
            V.validate(doc)


def test_random_draws_cross_field_rules_against_their_definitions() -> None:
    """Each rule, over random resolved documents, flips exactly at its stated bound."""
    rng = random.Random(5261)
    seen = {r: 0 for r in "ABCDE"}
    for _ in range(2000):
        p = resolve(_random_doc(rng))
        bad = rule_violations(p)
        for r in bad:
            seen[r] += 1
        # rule A: the file length in ms against 72000
        beats = 4 * p["bars"] + (p["tail_beats"] if p["loop_mode"] == "oneshot" else 0)
        assert ("A" in bad) == (beats * 60 / p["bpm"] > 72.0)
        # rule D boundaries in frequency: the cutoff track's range
        if p["filter_mode"] != "off":
            lo = p["filter_hz"] / 2 ** (p["move_depth_oct"] / 2)
            hi = p["filter_hz"] * 2 ** (p["move_depth_oct"] / 2)
            assert ("D" in bad) == (lo < 20 or hi > 0.45 * p["sample_rate"])
            # warm-up count is finite and at most 4 over the whole range (worst corner)
            if "D" not in bad and "A" not in bad:
                assert 1 <= p_filter(lo, p["filter_q"], p["bars"], p["bpm"],
                                     p["sample_rate"]) <= 4
        else:
            assert "D" not in bad
        # rule C: the error never exceeds half a bin
        n = loop_frames(p["bars"], p["bpm"], p["sample_rate"])
        f0 = f0_hz(p["note"], p["cents"])
        half = 0.5 * p["sample_rate"] / n
        assert tuning_error_cents(p) <= 1200 * math.log2(f0 / (f0 - half)) + 1e-9
        V.validate(p)  # a resolved request is still a valid instance
    assert all(count > 0 for count in seen.values()), seen  # every rule was exercised


def test_shared_fields_keep_the_fx_definition() -> None:
    fx = load("fx-params.schema.json")["properties"]
    props = ATMOS["properties"]

    def core(prop: dict) -> dict:
        return {k: v for k, v in prop.items() if k != "description"}

    for name in ("seed", "variants", "sample_rate", "bit_depth", "preset", "bpm",
                 "peak_ceiling_dbfs", "drive", "pump_depth", "reverb_size",
                 "reverb_predelay_ms", "reverb_width"):
        assert core(props[name]) == core(fx[name]), name
    for name in ("stereo_width", "filter_q", "reverb_mix"):
        assert (props[name]["minimum"], props[name]["maximum"]) == (
            fx[name]["minimum"], fx[name]["maximum"]), name
    # documented differences ($comment point 15)
    assert (fx["reverb_decay_ms"]["maximum"], props["reverb_decay_ms"]["maximum"]) == (8000, 12000)
    assert (fx["reverb_damp_hz"]["minimum"], props["reverb_damp_hz"]["minimum"]) == (1000, 300)
    assert (fx["stereo_width"]["default"], props["stereo_width"]["default"]) == (0.6, 0.7)
    assert "documented differences" in TEXT
