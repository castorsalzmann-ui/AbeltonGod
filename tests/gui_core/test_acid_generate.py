"""Acid generator and scale helpers. Expected values are written here, not taken from the
module's own tables."""

from __future__ import annotations

import math
import random

import pytest

from gui_core.acid_generate import (
    ROOTS,
    SCALES,
    AcidOptionError,
    GenOptions,
    degree_octave,
    generate_line,
    in_scale,
    note_name,
    root_midi,
    scale_notes,
    snap_note,
)

# Independent copy of the scale intervals (semitones from the root).
INTERVALS = {
    "minor": {0, 2, 3, 5, 7, 8, 10},
    "major": {0, 2, 4, 5, 7, 9, 11},
    "phrygian": {0, 1, 3, 5, 7, 8, 10},
    "dorian": {0, 2, 3, 5, 7, 9, 10},
    "harmonic minor": {0, 2, 3, 5, 7, 8, 11},
    "minor pentatonic": {0, 3, 5, 7, 10},
    "phrygian dominant": {0, 1, 4, 5, 7, 8, 10},
}
PC = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9,
      "A#": 10, "B": 11}


def random_options(rng: random.Random) -> GenOptions:
    scale = rng.choice(sorted(INTERVALS))
    return GenOptions(
        root=rng.choice(sorted(PC)), scale=scale, root_octave=rng.randint(0, 4),
        length=rng.randint(1, 32), density=rng.random(), accent_chance=rng.random(),
        slide_chance=rng.random(), octave_range=rng.randint(1, 3), seed=rng.randint(-5, 10**9),
    )


def test_tables_match_independent_copy():
    assert {k: set(v) for k, v in SCALES.items()} == INTERVALS
    assert list(ROOTS) == sorted(PC, key=PC.get)


def test_known_anchor_a2_is_45_and_names():
    assert root_midi("A", 2) == 45
    assert root_midi("C", 0) == 12
    assert note_name(45) == "A2" and note_name(60) == "C4" and note_name(61) == "C#4"
    assert scale_notes("A", "minor", 2, octaves=1) == [45, 47, 48, 50, 52, 53, 55, 57]


def test_deterministic_same_seed_equal_other_seed_differs():
    o = GenOptions(seed=77)
    assert generate_line(o) == generate_line(GenOptions(seed=77))
    assert generate_line(o) != generate_line(GenOptions(seed=78))


def test_golden_line_seed_1():
    """Pins the random stream for one option set (a change here is a deliberate format change)."""
    line = generate_line(GenOptions(seed=1))
    notes = [s["note"] if s["on"] else None for s in line["steps"]]
    assert notes == GOLDEN_SEED_1


# From one real run (A2 minor, density 0.6: 10 of 16 steps; all notes are in A minor).
GOLDEN_SEED_1 = [59, None, None, 57, 47, 50, 47, None, 65, 67, None, 65, None, 65, 67, None]


def test_every_note_in_scale_and_within_octave_range_random_options():
    rng = random.Random(20261105)
    for _ in range(400):
        o = random_options(rng)
        try:
            line = generate_line(o)
        except AcidOptionError:
            continue  # root octave 4 + 3 octaves can exceed MIDI 126; covered separately
        base = 12 * (o.root_octave + 1) + PC[o.root]
        assert line["length"] == o.length and len(line["steps"]) == o.length
        for s in line["steps"]:
            if not s["on"]:
                continue
            rel = s["note"] - base
            assert 0 <= s["octave"] < o.octave_range
            assert rel - 12 * s["octave"] in INTERVALS[o.scale]
            assert (s["note"] - PC[o.root]) % 12 in INTERVALS[o.scale]
            assert 0 <= s["note"] <= 126
            assert s["note"] == base + sorted(INTERVALS[o.scale])[s["degree"]] + 12 * s["octave"]


def test_density_count_exact_and_within_half_step_random_options():
    rng = random.Random(7)
    for _ in range(400):
        o = random_options(rng)
        try:
            line = generate_line(o)
        except AcidOptionError:
            continue
        on = sum(1 for s in line["steps"] if s["on"])
        assert on == math.floor(o.density * o.length + 0.5)
        assert abs(on - o.density * o.length) <= 0.5


@pytest.mark.parametrize("density,expected", [(0.0, 0), (1.0, 16), (0.5, 8), (0.25, 4)])
def test_density_curated(density, expected):
    line = generate_line(GenOptions(density=density, seed=3))
    assert sum(s["on"] for s in line["steps"]) == expected


def _flag_fraction(flag: str, chance_kw: str, chance: float) -> float:
    on = hits = 0
    for seed in range(300):
        line = generate_line(GenOptions(density=0.75, seed=seed, **{chance_kw: chance}))
        for s in line["steps"]:
            if s["on"]:
                on += 1
                hits += s[flag]
    return hits / on


@pytest.mark.parametrize("flag,kw", [("accent", "accent_chance"), ("slide", "slide_chance")])
def test_flag_chances(flag, kw):
    assert _flag_fraction(flag, kw, 0.0) == 0.0
    assert _flag_fraction(flag, kw, 1.0) == 1.0
    # 300 seeds * 12 steps = 3600 draws: sigma ~ 0.008 at p = 0.3, so 0.04 is 5 sigma.
    assert abs(_flag_fraction(flag, kw, 0.3) - 0.3) < 0.04


def test_octave_range_effect():
    seen = {1: set(), 2: set(), 3: set()}
    for seed in range(60):
        for r in seen:
            line = generate_line(GenOptions(octave_range=r, density=1.0, seed=seed))
            seen[r] |= {s["octave"] for s in line["steps"]}
    assert seen == {1: {0}, 2: {0, 1}, 3: {0, 1, 2}}


def test_options_change_the_line():
    base = GenOptions(seed=5)
    assert generate_line(base) != generate_line(GenOptions(seed=5, scale="major"))
    assert generate_line(base)["steps"] != generate_line(GenOptions(seed=5, density=0.9))["steps"]
    assert generate_line(GenOptions(seed=5, length=8))["length"] == 8


@pytest.mark.parametrize("kw,fragment", [
    ({"root": "H"}, "Grundnote"),
    ({"scale": "lydian"}, "Skala"),
    ({"length": 0}, "Länge"),
    ({"length": 33}, "Länge"),
    ({"length": 16.0}, "Länge"),
    ({"density": 1.5}, "Dichte"),
    ({"density": float("nan")}, "Dichte"),
    ({"accent_chance": -0.1}, "Akzent"),
    ({"slide_chance": True}, "Slide"),
    ({"octave_range": 0}, "Oktavbereich"),
    ({"octave_range": 4}, "Oktavbereich"),
    ({"seed": 1.5}, "Seed"),
    ({"root_octave": 9}, "Oktave"),
    ({"root_octave": 6, "root": "B", "octave_range": 3}, "MIDI-Bereich"),
])
def test_invalid_options_rejected_in_german(kw, fragment):
    with pytest.raises(AcidOptionError, match=fragment):
        generate_line(GenOptions(**kw))


def test_snap_and_membership_helpers():
    # A minor has no A# (46): ties go to the lower neighbour A (45).
    assert snap_note(46, "A", "minor") == 45
    assert snap_note(45, "A", "minor") == 45
    assert snap_note(49, "A", "minor") == 48  # C#3 -> C3 (tie with D 50 goes down)
    assert in_scale(48, "A", "minor") and not in_scale(46, "A", "minor")
    assert snap_note(0, "C", "major") == 0
    assert degree_octave(52, "A", "minor", 2) == (4, 0)
    assert degree_octave(57 + 3, "A", "minor", 2) == (2, 1)
    assert degree_octave(46, "A", "minor", 2) is None
    assert degree_octave(33, "A", "minor", 2) == (0, -1)
