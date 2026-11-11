"""Cell model of the Goa clips (#570): the checks of the table "Messbare Pruefungen ohne
Hoeren" in ``docs/research/2026-11-10_klassische-goa-leads-und-melodien.md``.

Every check measures the EXPORTED notes: the ``.mid`` bytes of ``goa_clips.build_clips`` are
read back with the parser below (written here, not the module's writer). Scales, register
windows, the neighbour tone per scale and all target numbers are written out in this file.
The checks show that a clip follows the documented construction; they say nothing about
how it sounds.
"""

from __future__ import annotations

import hashlib
import random
import struct
from collections import Counter

import pytest

from audio_engine import goa_cells, goa_clips

SEEDS = range(16)
STEP = 120  # ticks of a 16th at PPQ 480
BAR = 1920
# Semitones above the root, written here independently of goa_cells.SCALES (rule N1).
SCALE_STEPS = {
    "phrygian": {0, 1, 3, 5, 7, 8, 10},
    "phrygian_dominant": {0, 1, 4, 5, 7, 8, 10},
    "harmonic_minor": {0, 2, 3, 5, 7, 8, 11},
    "double_harmonic": {0, 1, 4, 5, 7, 8, 11},
    "aeolian": {0, 2, 3, 5, 7, 8, 10},
    "dorian": {0, 2, 3, 5, 7, 9, 10},
    "minor_blues": {0, 3, 5, 6, 7, 10},
    "hungarian_minor": {0, 2, 3, 6, 7, 8, 11},
}
# The root's neighbour (rule N2): the second of the scale; the blues scale has no second,
# there it is the seventh below the root.
NEIGHBOUR = {"phrygian": 1, "phrygian_dominant": 1, "harmonic_minor": 2, "double_harmonic": 1,
             "aeolian": 2, "dorian": 2, "minor_blues": 10, "hungarian_minor": 2}
ROOTS = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6,
         "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}
WINDOW = {"lead": (60, 83), "arp": (57, 80), "pad": (48, 59), "pluck": (36, 59)}
CELL_LENGTHS = (5, 6, 9, 11, 12, 16)
CELL_VOICES = ("lead", "arp", "pluck")
BASE, ACCENT = 84, 120  # the two velocity levels (rule N6 example values)
MAX_PCS = {"arp": 5, "pluck": 5, "lead": 6, "pad": 2}
NOTES_PER_BAR = {"arp": (14, 16), "pluck": (12, 16), "lead": (4, 10)}
SLIDES_PER_BAR = {"arp": (0, 2), "pluck": (1, 2), "lead": (0, 2)}
SLIDE_OVERLAP = 15


def parse_smf(data: bytes) -> dict:
    """Independent reader: notes as (start, end, pitch, velocity) in absolute ticks."""
    assert data[:4] == b"MThd" and data[14:18] == b"MTrk"
    _, fmt, ntrk, ppq = struct.unpack(">IHHH", data[4:14])
    (length,) = struct.unpack(">I", data[18:22])
    body = data[22:22 + length]
    assert len(data) == 22 + length and (fmt, ntrk, ppq) == (0, 1, 480)
    i, tick, end = 0, 0, None
    on: dict[int, tuple[int, int]] = {}
    notes = []
    while i < len(body):
        delta = 0
        while True:
            b = body[i]
            i += 1
            delta = (delta << 7) | (b & 0x7F)
            if b < 0x80:
                break
        tick += delta
        st = body[i]
        if st == 0xFF:
            typ, ln = body[i + 1], body[i + 2]
            i += 3 + ln
            if typ == 0x2F:
                end = tick
                assert i == len(body)
        elif st & 0xF0 == 0x90:
            pitch, vel = body[i + 1], body[i + 2]
            assert pitch not in on, "same pitch started while sounding"
            on[pitch] = (tick, vel)
            i += 3
        elif st & 0xF0 == 0x80:
            s, vel = on.pop(body[i + 1])
            notes.append((s, tick, body[i + 1], vel))
            i += 3
        else:
            raise AssertionError(f"unexpected status {st:#x}")
    assert not on, "note without note-off"
    return {"end": end, "notes": sorted(notes)}


def exported(**opts) -> dict[str, list[tuple[int, int, int, int]]]:
    """Notes per voice as written to the files (voices generated together)."""
    return {v: parse_smf(b)["notes"] for v, b in goa_clips.build_clips(**opts).items()}


def solo(voice: str, **opts) -> list[tuple[int, int, int, int]]:
    return exported(voices=[voice], **opts)[voice]


def root_pitch(notes, root: str) -> int:
    """The cell root: the most frequent pitch of the root's pitch class."""
    counts = Counter(p for _, _, p, _ in notes if p % 12 == ROOTS[root])
    return counts.most_common(1)[0][0]


def by_step(notes) -> dict[int, int]:
    return {s // STEP: p for s, _, p, _ in notes}


def slide_starts(notes) -> list[int]:
    """Start ticks of notes that overlap the next note of the voice (the slide encoding)."""
    return [a[0] for a, b in zip(notes, notes[1:], strict=False) if a[1] > b[0]]


ALL_SCALES = sorted(SCALE_STEPS)


def test_scale_list_is_the_documented_one_without_major():
    assert {k: set(v) for k, v in goa_cells.SCALES.items()} == SCALE_STEPS
    assert goa_cells.DEFAULT_SCALE == "phrygian"
    for steps in goa_cells.SCALES.values():
        assert not {0, 4, 7, 11} <= set(steps) or 1 in steps  # no major (ionian) scale
    with pytest.raises(ValueError):
        goa_cells.normalise({"scale": "major"})


# ---- all pitches in scale, straight 16th grid, register windows ----------------------------

@pytest.mark.parametrize("scale", ALL_SCALES)
def test_every_pitch_is_in_the_scale_on_the_16th_grid_inside_the_window(scale):
    for seed in SEEDS:
        for root in ("A", "C", "F#", "Bb"):
            clips = exported(seed=seed, scale=scale, root=root)
            assert list(clips) == ["lead", "arp", "pad", "pluck"]
            allowed = {(ROOTS[root] + s) % 12 for s in SCALE_STEPS[scale]}
            for voice, notes in clips.items():
                assert notes, voice
                lo, hi = WINDOW[voice]
                for s, _e, p, vel in notes:
                    assert p % 12 in allowed, (voice, seed, p)
                    assert lo <= p <= hi, (voice, seed, p)
                    assert s % STEP == 0, "N9: straight 16th grid, no triplets or 32nds"
                    assert vel in ((78,) if voice == "pad" else (BASE, ACCENT))


def _random_options(rng: random.Random) -> dict:
    scale = rng.choice(ALL_SCALES)
    o = {"seed": rng.randint(0, 10**6), "bars": rng.randint(1, 16),
         "bpm": round(rng.uniform(135, 150), 2), "root": rng.choice(list(ROOTS)),
         "scale": scale, "voices": rng.sample(list(goa_cells.VOICES), rng.randint(1, 4)),
         "progression": [rng.randrange(len(SCALE_STEPS[scale]))
                         for _ in range(rng.randint(1, 16))],
         "density": {v: rng.choice([0.0, 1.0, round(rng.random(), 3)])
                     for v in goa_cells.VOICES},
         "register": {v: rng.randint(-2, 2) for v in ("arp", "pad", "pluck")},
         "restart_bars": rng.choice([2, 4, 8]), "lead_mode": rng.choice(["own", "double"]),
         "pitches": {"lead": rng.randint(3, 6), "arp": rng.randint(3, 5),
                     "pluck": rng.randint(3, 5)},
         "slides": {v: rng.randint(0, 2) for v in CELL_VOICES},
         "accent_cycle": rng.choice(["auto", 3, 5]), "gate": rng.randint(25, 100),
         "variant_steps": rng.randint(0, 1)}
    if rng.random() < 0.3:
        o["grouping"] = rng.choice(["3+3+2", "3+3+3+3+4"])
    else:
        o["cell_length"] = {v: rng.choice(["auto", *CELL_LENGTHS]) for v in CELL_VOICES}
    return o


def test_property_any_valid_options_give_a_loopable_clip_in_the_scale():
    """Whole option range (also chord changes, extreme densities, every register): notes in
    the scale, on the grid, inside the clip, two velocity levels, deterministic."""
    rng = random.Random(570)
    for _ in range(150):
        o = _random_options(rng)
        clips = goa_clips.build_clips(**o)
        assert clips == goa_clips.build_clips(**o)
        allowed = {(ROOTS[o["root"]] + s) % 12 for s in SCALE_STEPS[o["scale"]]}
        for voice, data in clips.items():
            m = parse_smf(data)
            assert m["end"] == o["bars"] * BAR
            for s, e, p, vel in m["notes"]:
                assert p % 12 in allowed and 0 <= p <= 127, (voice, o)
                assert 0 <= s < e <= m["end"], "no note crosses the clip end"
                assert s % STEP == 0
                assert vel in ((78,) if voice == "pad" else (BASE, ACCENT))


# ---- pitch set ------------------------------------------------------------------------------

@pytest.mark.parametrize("scale", ALL_SCALES)
@pytest.mark.parametrize("pitches", [{"lead": 3, "arp": 3, "pluck": 3}, None,
                                     {"lead": 6, "arp": 5, "pluck": 5}])
def test_distinct_pitch_classes_arp_acid_5_lead_6_pad_2_on_the_default_progression(
        scale, pitches):
    kw = {} if pitches is None else {"pitches": pitches}
    for seed in SEEDS:
        for voice, notes in exported(seed=seed, scale=scale, **kw).items():
            pcs = {p % 12 for _, _, p, _ in notes}
            assert len(pcs) <= MAX_PCS[voice], (voice, seed, pcs)
            if pitches is not None and voice != "pad":
                assert len(pcs) <= pitches[voice]


def test_pitch_count_limits_are_enforced():
    for bad in ({"pitches": {"arp": 6}}, {"pitches": {"pluck": 6}}, {"pitches": {"lead": 7}},
                {"pitches": 2}, {"pitches": {"pad": 3}}):
        with pytest.raises(ValueError):
            goa_cells.normalise(bad)


# ---- literal repetition at distance L -------------------------------------------------------

@pytest.mark.parametrize("length", CELL_LENGTHS)
@pytest.mark.parametrize("restart", [2, 4, 8])
def test_repetition_at_cell_distance_between_restarts_is_at_least_80_percent(length, restart):
    """Step s equals step s - L (pitch, or no onset) inside a restart block: >= 80 % in
    every block that has such a pair, and 100 % before the block's last bar (rule N5: the
    one variant sits in the last bar before a restart). Default progression."""
    bars = 8
    for seed in SEEDS:
        clips = exported(seed=seed, bars=bars, restart_bars=restart, cell_length=length)
        for voice in CELL_VOICES:
            steps = by_step(clips[voice])
            for b0 in range(0, bars * 16, restart * 16):
                b1 = min(bars * 16, b0 + restart * 16)
                pairs = [(s, steps.get(s) == steps.get(s - length))
                         for s in range(b0 + length, b1)]
                if not pairs:
                    continue
                share = sum(ok for _, ok in pairs) / len(pairs)
                assert share >= 0.80, (voice, seed, b0, share)
                assert all(ok for s, ok in pairs if s < b1 - 16), (voice, seed, b0)


def test_the_cell_is_restarted_at_every_block_start():
    """With L = 11 and a restart every 2 bars the block start is not a multiple of 11
    steps: every block must begin like the first one (hard restart, rule N4)."""
    for seed in SEEDS:
        clips = exported(seed=seed, bars=8, restart_bars=2, cell_length=11,
                         variant_steps=0, voices=["arp"])
        steps = by_step(clips["arp"])
        first = [steps[s] for s in range(11)]
        for b0 in (32, 64, 96):  # blocks 1-3 (2 bars = 32 steps each)
            same = sum(steps[b0 + s] == first[s] for s in range(11))
            assert same >= 9, (seed, b0)  # at most the two excursion candidates differ
        assert steps[0] == steps[32] == steps[64] == steps[96]  # step 1 is the root


def test_the_cell_runs_across_the_bar_line():
    """A cell of 5, 9 or 11 steps must not restart at every bar (displacement, rule N4)."""
    for length in (5, 9, 11):
        differs = 0
        for seed in SEEDS:
            steps = by_step(solo("arp", seed=seed, cell_length=length, variant_steps=0))
            differs += [steps[s] for s in range(16)] != [steps[s] for s in range(16, 32)]
        assert differs >= 12, (length, differs)


# ---- root share and neighbour ---------------------------------------------------------------

@pytest.mark.parametrize("scale", ALL_SCALES)
def test_root_share_at_least_40_percent_and_neighbour_present_for_arp_and_acid(scale):
    """Default densities (arp every step, acid 87.5 % of the steps), every cell length."""
    for seed in SEEDS:
        for length in ("auto", *CELL_LENGTHS):
            clips = exported(seed=seed, scale=scale, cell_length=length,
                             voices=["arp", "pluck"])
            for voice in ("arp", "pluck"):
                rel = [(p - 9) % 12 for _, _, p, _ in clips[voice]]  # root A = pitch class 9
                assert rel.count(0) / len(rel) >= 0.40, (voice, seed, length)
                assert NEIGHBOUR[scale] in rel, (voice, seed, length)


# ---- leaps and range ------------------------------------------------------------------------

LOW_DENSITY = {"density": {"lead": 0.3, "arp": 0.6, "pluck": 0.6}}


@pytest.mark.parametrize("scale", ALL_SCALES)
def test_largest_leap_12_and_cell_range_8_except_minor_blues_below_5_pitches_with_rests(scale):
    """Default progression. Range: all pitches of the clip except the root displaced by an
    octave (the root is the most frequent pitch of the root's class).

    Claim restricted: minor_blues with 3 or 4 pitches AND rests next to the excursion is
    left out. Its neighbour is the b7 BELOW the root and its only excursion tone within
    the range limit needs 5 pitches; with fewer, the octave stays and can sound next to
    the b7 (14 semitones). At the default densities and with 5 pitches the claim holds."""
    kws = [{}, {"pitches": {"lead": 6, "arp": 5, "pluck": 5}},
           dict(LOW_DENSITY, pitches={"lead": 5, "arp": 5, "pluck": 5})]
    if scale != "minor_blues":
        kws.append(LOW_DENSITY)
    for seed in SEEDS:
        for root in ("A", "D"):
            for kw in kws:
                clips = exported(seed=seed, scale=scale, root=root, **kw)
                for voice in CELL_VOICES:
                    pitches = [p for _, _, p, _ in clips[voice]]
                    leaps = [abs(a - b) for a, b in zip(pitches, pitches[1:], strict=False)]
                    assert max(leaps, default=0) <= 12, (voice, seed, kw)
                    r = root_pitch(clips[voice], root)
                    body = [p for p in pitches if abs(p - r) != 12]
                    assert max(body) - min(body) <= 8, (voice, seed, kw)


# ---- accents --------------------------------------------------------------------------------

@pytest.mark.parametrize("voice", CELL_VOICES)
@pytest.mark.parametrize("cycle", ["auto", 3, 5])
def test_accent_share_20_to_35_percent_with_an_accent_off_the_quarter_beats_4_bar_clips(
        voice, cycle):
    """Claimed for clips whose restart blocks hold at least 20 notes (the default 4-bar
    clip at default density does); a block of a handful of notes cannot hit a band of
    integers. Single voice and all four together at the default registers."""
    for seed in SEEDS:
        for length in ("auto", *CELL_LENGTHS):
            kw = {"seed": seed, "cell_length": length, "accent_cycle": cycle}
            for notes in (solo(voice, **kw), exported(**kw)[voice]):
                assert len(notes) >= 20
                accents = [s for s, _, _, vel in notes if vel == ACCENT]
                share = len(accents) / len(notes)
                assert 0.20 <= share <= 0.35, (voice, seed, length, share)
                assert any((s // STEP) % 4 for s in accents), "all accents on quarter beats"


def test_accent_cycle_auto_is_3_or_5_and_moves_against_the_cell():
    """The accented cell steps are not the same in every pass (the cycle is not locked to
    the cell and not to the beat)."""
    seen = set()
    for seed in SEEDS:
        for voice in CELL_VOICES:
            for length in CELL_LENGTHS:
                for cycle in ("auto", 3, 5):
                    kw = {"seed": seed, "cell_length": length, "accent_cycle": cycle}
                    if cycle == "auto":
                        seen.add(goa_cells.describe(**kw)[voice]["accent_cycle"])
                    notes = solo(voice, **kw)
                    # complete passes of the first restart block (64 steps)
                    passes = {frozenset((s // STEP) % length for s, _, _, vel in notes
                                        if vel == ACCENT and (s // STEP) // length == j)
                              for j in range(64 // length)}
                    assert len(passes) > 1, (voice, seed, length, cycle)
                    if voice == "arp":  # every 16th sounds: the accents reach every beat step
                        assert len({(s // STEP) % 4 for s, _, _, vel in notes
                                    if vel == ACCENT}) == 4
    assert seen == {3, 5}


# ---- slides ---------------------------------------------------------------------------------

@pytest.mark.parametrize("scale", ["phrygian", "minor_blues", "double_harmonic"])
def test_slides_per_bar_acid_1_to_2_others_0_to_2_and_none_across_a_restart(scale):
    for seed in SEEDS:
        for length in ("auto", *CELL_LENGTHS):
            for bars, restart in ((4, 4), (6, 2)):
                clips = exported(seed=seed, scale=scale, cell_length=length, bars=bars,
                                 restart_bars=restart)
                for voice in CELL_VOICES:
                    notes = clips[voice]
                    per_bar = Counter(s // BAR for s in slide_starts(notes))
                    lo, hi = SLIDES_PER_BAR[voice]
                    for bar in range(bars):
                        assert lo <= per_bar[bar] <= hi, (voice, seed, length, bar)
                    for a, b in zip(notes, notes[1:], strict=False):
                        if a[1] > b[0]:
                            assert a[1] - b[0] == SLIDE_OVERLAP and a[2] != b[2]
                            assert b[0] % (restart * BAR) != 0, "slide into a restart"
    assert slide_starts(exported(seed=1)["arp"]) == []  # arp default: no slides


def test_lead_and_arp_slides_follow_the_slides_option():
    total = Counter()
    for seed in SEEDS:
        clips = exported(seed=seed, slides=2)
        for voice in CELL_VOICES:
            total[voice] += len(slide_starts(clips[voice]))
        none = exported(seed=seed, slides=0)
        assert all(slide_starts(none[v]) == [] for v in CELL_VOICES)
    assert total["arp"] > 16 and total["pluck"] > 16 and total["lead"] > 0


# ---- density --------------------------------------------------------------------------------

@pytest.mark.parametrize("scale", ["phrygian", "aeolian"])
def test_notes_per_bar_arp_14_to_16_acid_12_to_16_lead_4_to_10_at_default_density(scale):
    for seed in SEEDS:
        for length in ("auto", *CELL_LENGTHS):
            clips = exported(seed=seed, scale=scale, cell_length=length)
            for voice, (lo, hi) in NOTES_PER_BAR.items():
                per_bar = Counter(s // BAR for s, _, _, _ in clips[voice])
                for bar in range(4):
                    assert lo <= per_bar[bar] <= hi, (voice, seed, length, per_bar)


def test_gate_is_half_a_step_and_a_tie_makes_an_eighth():
    """Note lengths: 60 ticks (half a 16th), 180 (one tied step), 135 (slide: one step
    plus the overlap). Nothing else at the defaults."""
    lengths = Counter()
    for seed in SEEDS:
        for voice, notes in exported(seed=seed).items():
            if voice != "pad":
                lengths.update((voice, e - s) for s, e, _, _ in notes)
    assert {n for _, n in lengths} == {60, 135, 180}
    assert {n for v, n in lengths if v == "arp"} == {60}
    assert lengths["pluck", 180] and lengths["lead", 180] and lengths["pluck", 135]


def test_density_zero_is_silent_and_density_one_fills_every_step():
    clips = exported(seed=4, density=0.0, voices=["lead", "arp", "pluck"])
    assert all(notes == [] for notes in clips.values())
    full = exported(seed=4, density=1.0)
    assert all(len(full[v]) == 64 for v in CELL_VOICES)


# ---- excursion ------------------------------------------------------------------------------

@pytest.mark.parametrize("length", CELL_LENGTHS)
def test_excursion_is_not_on_the_same_cell_step_in_every_block(length):
    """The excursion is the pitch farthest from the cell root. With two or more restart
    blocks its cell step must differ between blocks (rule N5); inside a block it stays."""
    for seed in SEEDS:
        for bars, restart in ((8, 4), (8, 2), (16, 8)):
            clips = exported(seed=seed, bars=bars, restart_bars=restart, cell_length=length,
                             voices=["arp", "pluck"])
            for voice in ("arp", "pluck"):
                steps = by_step(clips[voice])
                r = root_pitch(clips[voice], "A")
                where = []
                for b0 in range(0, bars * 16, restart * 16):
                    first = {i: steps[b0 + i] for i in range(length) if b0 + i in steps}
                    far = max(abs(p - r) for p in first.values())
                    assert far >= 5, (voice, seed, "no excursion in the cell")
                    hit = [i for i, p in first.items() if abs(p - r) == far]
                    assert len(hit) == 1, "at most one excursion per cell"
                    where.append(hit[0])
                    second = steps.get(b0 + length + hit[0])
                    if b0 + length + hit[0] < b0 + restart * 16 - 16:
                        assert second == first[hit[0]]
                assert len(set(where)) > 1, (voice, seed, where)


# ---- harmony --------------------------------------------------------------------------------

def test_default_progression_is_one_degree_and_the_pad_holds_root_and_fifth():
    args = goa_clips.build_parser().parse_args(["--out", "x"])
    assert goa_clips.params_from_args(args)["progression"] == [0]
    assert goa_cells.normalise({})["progression"] == [0]
    for scale in ALL_SCALES:
        for root, pcs in (("A", {9, 4}), ("C", {0, 7}), ("F#", {6, 1})):
            for bars in (1, 4, 16):
                pad = exported(seed=5, scale=scale, root=root, bars=bars)["pad"]
                assert {p % 12 for _, _, p, _ in pad} == pcs
                # one strike over the whole clip (ends 30 ticks before the loop point)
                assert [(s, e) for s, e, _, _ in pad] == [(0, bars * BAR - 30)] * 2


def test_pad_never_sounds_three_pitch_classes_whatever_the_progression():
    rng = random.Random(11)
    for _ in range(60):
        scale = rng.choice(ALL_SCALES)
        prog = [rng.randrange(len(SCALE_STEPS[scale])) for _ in range(rng.randint(1, 8))]
        bars = rng.randint(1, 16)
        pad = exported(seed=1, scale=scale, progression=prog, bars=bars,
                       density={"pad": rng.choice([0.0, 0.5, 1.0])})["pad"]
        for bar in range(bars):
            sounding = {p % 12 for s, e, p, _ in pad if s <= bar * BAR + 960 < e}
            assert len(sounding) == 2, (scale, prog, bar)


# A phrygian (A Bb C D E F G): root plus the scale tone closest to a fifth above it.
DYAD_A_PHRYGIAN = {0: {9, 4}, 5: {5, 0}, 6: {7, 2}, 4: {4, 10}}


def test_an_explicit_progression_moves_pad_and_cell_inside_the_scale():
    opts = {"seed": 2, "bars": 4, "progression": [0, 5, 6, 4], "cell_length": 16,
            "variant_steps": 0}
    clips = exported(**opts)
    for bar, degree in enumerate([0, 5, 6, 4]):
        mid = bar * BAR + 960
        assert {p % 12 for s, e, p, _ in clips["pad"] if s <= mid < e} == DYAD_A_PHRYGIAN[degree]
    arp = by_step(clips["arp"])
    # the cell's first step is the degree's own tone: A, F, G, E
    assert [arp[b * 16] % 12 for b in range(4)] == [9, 5, 7, 4]
    assert [arp[s] for s in range(16)] != [arp[s] for s in range(16, 32)]


# ---- voices against each other --------------------------------------------------------------

def held_clashes(clips) -> list:
    """Two notes of different moving voices exactly a semitone apart that sound together
    for a 16th or longer while one of them is accented."""
    out = []
    voices = [v for v in clips if v != "pad"]
    for i, va in enumerate(voices):
        for vb in voices[i + 1:]:
            for a in clips[va]:
                for b in clips[vb]:
                    if abs(a[2] - b[2]) == 1 and min(a[1], b[1]) - max(a[0], b[0]) >= STEP \
                            and ACCENT in (a[3], b[3]):
                        out.append((va, a, vb, b))
    return out


# Found by search (seeds 0-199, 5 roots, 4 register sets): two moving voices meet a
# semitone apart on an accent. At the default registers no case was found.
CLASH_CASES = [{"seed": 43, "root": "E", "register": {"pluck": 1}},
               {"seed": 43, "root": "A", "register": {"lead": -1}},
               {"seed": 112, "root": "E", "register": {"pluck": 1}}]


def test_no_held_semitone_clash_between_the_moving_voices_on_accents():
    """Lead, arp and acid line (the pad is the drone the second sits on: not counted)."""
    rng = random.Random(7)
    cases = [dict(c) for c in CLASH_CASES]
    for seed in SEEDS:
        for root in ("A", "C", "E"):
            cases.append({"seed": seed, "root": root})
            cases.append({"seed": seed, "root": root, "scale": rng.choice(ALL_SCALES),
                          "register": {"pluck": rng.choice([0, 1]),
                                       "lead": rng.choice([-1, 0]), "arp": rng.choice([-1, 0])},
                          "slides": 2, "lead_mode": rng.choice(["own", "double"])})
    for case in cases:
        assert held_clashes(exported(**case)) == [], case


@pytest.mark.parametrize("case", CLASH_CASES)
def test_the_clash_rule_only_removes_accents_and_single_voices_keep_theirs(case):
    together = exported(**case)
    changed = 0
    for voice in CELL_VOICES:
        alone = solo(voice, **case)
        assert [n[:3] for n in alone] == [n[:3] for n in together[voice]]
        for a, t in zip(alone, together[voice], strict=True):
            if a[3] != t[3]:
                assert (a[3], t[3]) == (ACCENT, BASE)
                changed += 1
    assert changed >= 1, "these cases need the rule; without it they would clash"


def test_lead_double_is_the_arp_one_octave_up_and_own_is_another_line():
    for seed in SEEDS:
        clips = exported(seed=seed, lead_mode="double")
        assert clips["lead"] == [(s, e, p + 12, vel) for s, e, p, vel in clips["arp"]]
        own = exported(seed=seed)
        assert own["arp"] == clips["arp"]
        assert [n[:2] for n in own["lead"]] != [n[:2] for n in own["arp"]]
        # the lead alone (arp not selected) is the same doubled line
        assert solo("lead", seed=seed, lead_mode="double") == clips["lead"]
    with pytest.raises(ValueError, match="MIDI range"):
        goa_cells.generate(lead_mode="double", register={"lead": 2, "arp": 2})


# ---- groupings ------------------------------------------------------------------------------

@pytest.mark.parametrize(("grouping", "length", "starts"), [
    ("3+3+2", 8, (0, 3, 6)), ("3+3+3+3+4", 16, (0, 3, 6, 9, 12))])
def test_bar_filling_groupings_put_the_root_on_every_group_and_do_not_drift(
        grouping, length, starts):
    for seed in SEEDS:
        clips = exported(seed=seed, grouping=grouping, variant_steps=0)
        for voice in ("arp", "pluck"):
            steps = by_step(clips[voice])
            r = root_pitch(clips[voice], "A")
            for s in range(64):
                if s % length in starts and s in steps:
                    assert abs(steps[s] - r) in (0, 12) and steps[s] % 12 == 9, (voice, seed, s)
                assert steps.get(s) == steps.get(s % 16), "the bar repeats: no displacement"
        assert goa_cells.describe(seed=seed, grouping=grouping)["arp"]["cell_length"] == length
    with pytest.raises(ValueError):
        goa_cells.normalise({"grouping": grouping, "cell_length": 9})


def test_auto_cell_length_comes_from_the_allowed_set_and_varies_with_the_seed():
    seen = {v: set() for v in CELL_VOICES}
    for seed in range(48):
        for voice, info in goa_cells.describe(seed=seed).items():
            seen[voice].add(info["cell_length"])
    assert seen["arp"] == set(CELL_LENGTHS) and seen["lead"] == set(CELL_LENGTHS)
    assert seen["pluck"] == {12, 16}  # N7: the acid line has 16 or 12 steps
    for bad in (7, 8, 4, 17, "x"):
        with pytest.raises(ValueError):
            goa_cells.normalise({"cell_length": bad})


# ---- determinism ----------------------------------------------------------------------------

def _sub(seed: int, dimension: str) -> int:
    """The documented derivation, written out here."""
    digest = hashlib.sha256(f"goa_cells:sub:{seed}:{dimension}".encode("ascii")).digest()
    return int.from_bytes(digest[:8], "big")


def test_sub_seeds_are_derived_from_the_clip_seed_as_documented():
    for seed in (0, 3, 99):
        subs = {d: _sub(seed, d) for d in ("pitch", "rhythm", "accent", "slide")}
        assert goa_cells.normalise({"seed": seed})["sub_seeds"] == subs
        assert goa_clips.build_clips(seed=seed) == goa_clips.build_clips(seed=seed, sub_seeds=subs)


# Pinned on Ubuntu; integer-only note maths, so Windows must give the same bytes (CI).
GOLDEN = {
    "lead": "4eb142db00c1b434f0d16a8b56035250ba71fcc884e3b18959693f29860f84ea",
    "arp": "f9bfbf6917ce0bc282820b838dbf718f5de56765d5f607df1c9571493514d221",
    "pad": "420af2a8a2a9abce4539c5b8e3198b86f782c8d014b99a3dbf7c09db0e90e48c",
    "pluck": "076f6aae4769bfc2d3e8f9ed016f6d9653ce319b920d84fb0caf8ad532404ad3",
}


def test_same_options_and_seed_give_the_pinned_bytes():
    opts = {"seed": 570, "bars": 8, "root": "F#", "scale": "phrygian_dominant", "bpm": 142.5,
            "restart_bars": 2, "progression": [0, 0, 6, 0], "slides": 2}
    a = goa_clips.build_clips(**opts)
    assert a == goa_clips.build_clips(**opts)
    assert {v: hashlib.sha256(b).hexdigest() for v, b in a.items()} == GOLDEN
    assert a != goa_clips.build_clips(**dict(opts, seed=571))


def _other(seed: int, dimension: str) -> dict:
    return {"sub_seeds": {dimension: seed + 1000}}


@pytest.mark.parametrize("voice", CELL_VOICES)
def test_pitch_sub_seed_changes_pitches_only(voice):
    moved = 0
    for seed in SEEDS:
        for length in ("auto", 5, 16):
            kw = {"seed": seed, "cell_length": length, "slides": 2}
            a, b = solo(voice, **kw), solo(voice, **kw, **_other(seed, "pitch"))
            assert [(s, e, vel) for s, e, _, vel in a] == [(s, e, vel) for s, e, _, vel in b]
            moved += [n[2] for n in a] != [n[2] for n in b]
    # Sanity floor that the pitch stream is seeded (measured 27-32 of 48 on these seeds;
    # short cells with the root-share target leave few free steps).
    assert moved >= 20


@pytest.mark.parametrize("voice", ["lead", "pluck"])
def test_rhythm_sub_seed_changes_onsets_and_lengths_only(voice):
    """Pitch belongs to the step: a step that sounds in both clips has the same pitch.
    The accent cycle counts notes: the velocity sequence stays (same notes per pass)."""
    moved = 0
    for seed in SEEDS:
        for length in ("auto", 9, 16):
            kw = {"seed": seed, "cell_length": length, "slides": 2}
            a, b = solo(voice, **kw), solo(voice, **kw, **_other(seed, "rhythm"))
            pa, pb = by_step(a), by_step(b)
            assert all(pa[s] == pb[s] for s in pa.keys() & pb.keys())
            n = min(len(a), len(b))
            assert n >= len(a) - 2 and [x[3] for x in a[:n]] == [x[3] for x in b[:n]]
            moved += sorted(pa) != sorted(pb)
    # Sanity floor (measured: lead 22, pluck 39 of 48): a cell with one or two rests has
    # few places for them.
    assert moved >= 15


@pytest.mark.parametrize("voice", CELL_VOICES)
def test_accent_sub_seed_changes_velocities_only(voice):
    moved = 0
    for seed in SEEDS:
        kw = {"seed": seed, "slides": 2}
        a, b = solo(voice, **kw), solo(voice, **kw, **_other(seed, "accent"))
        assert [n[:3] for n in a] == [n[:3] for n in b]
        moved += [n[3] for n in a] != [n[3] for n in b]
    assert moved >= 8  # of 16: a cycle has only 2 or 4 phases


@pytest.mark.parametrize("voice", CELL_VOICES)
def test_slide_sub_seed_changes_note_ends_only(voice):
    moved = 0
    for seed in SEEDS:
        kw = {"seed": seed, "slides": 2}
        a, b = solo(voice, **kw), solo(voice, **kw, **_other(seed, "slide"))
        assert [(s, p, vel) for s, _, p, vel in a] == [(s, p, vel) for s, _, p, vel in b]
        moved += [n[1] for n in a] != [n[1] for n in b]
    assert moved >= 6  # of 16; the slide cycle only chooses among the excursion's steps


# ---- loop -----------------------------------------------------------------------------------

@pytest.mark.parametrize("restart", [2, 4, 8])
def test_no_note_tie_or_slide_crosses_a_restart_or_the_clip_end(restart):
    for seed in SEEDS:
        for bars in (1, 3, 8, 16):
            clips = exported(seed=seed, bars=bars, restart_bars=restart, slides=2,
                             gate=100, density={"lead": 0.5, "arp": 0.9, "pluck": 0.8})
            for voice in CELL_VOICES:
                for s, e, _, _ in clips[voice]:
                    block_end = min(bars * BAR, (s // (restart * BAR) + 1) * restart * BAR)
                    assert e <= block_end, (voice, seed, bars, s, e)
            assert all(e <= bars * BAR for s, e, _, _ in clips["pad"])


# ---- options --------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    {"bars": 0}, {"bars": 17}, {"bpm": 134.9}, {"bpm": 151}, {"scale": "major"},
    {"restart_bars": 3}, {"lead_mode": "legato"}, {"grouping": "4+4"}, {"accent_cycle": 4},
    {"slides": 3}, {"gate": 10}, {"velocity": 120, "accent_velocity": 120},
    {"sub_seeds": {"filter": 1}}, {"sub_seeds": {"pitch": -1}}, {"progression": [7]},
    {"scale": "minor_blues", "progression": [6]}, {"sections": []}, {"energy": 1.0},
    {"density": 1.5}, {"register": 3}, {"root": "H"}, {"max_span": 6}, {"tie_percent": 101},
])
def test_invalid_options_raise(bad):
    with pytest.raises(ValueError):
        goa_cells.generate(**bad)


def test_tempo_default_and_every_working_value_is_a_named_option():
    o = goa_cells.normalise({})
    assert (o["bpm"], o["restart_bars"], o["lead_mode"], o["grouping"]) == (
        145.0, 4, "own", "displaced")
    assert (o["velocity"], o["accent_velocity"], o["gate"]) == (BASE, ACCENT, 50)
    for name, (default, lo, hi) in goa_cells.INT_OPTIONS.items():
        assert o[name] == default and lo <= default <= hi
        if name != "accent_velocity":  # its lowest value is below the default velocity
            assert goa_cells.normalise({name: lo})[name] == lo
        with pytest.raises(ValueError):
            goa_cells.normalise({name: hi + 1})
