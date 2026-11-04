"""Configurable Goa arrangement (issue #390, D-027): bass rhythm, form, tempo, engine-sourced
rhythm tracks. Expected values are written here (bar counts, ticks, counts), not taken from
the code under test; MIDI is read back with the independent parser of test_goa_arrangement."""

import random

import pytest
from test_goa_arrangement import read_smf

from audio_engine import goa_arrangement as ga
from audio_engine import goa_patterns as gp
from audio_engine.io import render_sample_wav
from audio_engine.presets import load_preset

PPQ, BAR = 480, 1920
ROLLS = ["off_kick_16th", "offbeat_8th", "offbeat_ghost", "gallop", "triplet_gallop"]
# gate_ms written from the preset files (goa-roll-short/medium/long.json)
GATES = {"goa-roll-short": 62, "goa-roll-medium": 85, "goa-roll-long": 100}


def tracks(**p):
    _, _, t = read_smf(ga.build_midi(**p))
    return {x["name"]: x for x in t[1:]}, t[0]


# ------------------------------------------------------------ bass rhythm: ghosted off-beat

@pytest.mark.parametrize("seed", range(12))
def test_ghost_counts_and_positions(seed):
    rng = random.Random(seed)
    bars = rng.randint(1, 16)
    beats = 4 * bars
    line = gp.bass_line(33, rng.choice(sorted(gp.SCALES)), bars, seed=seed, roll="offbeat_ghost")
    st = [i for i, s in enumerate(line["steps"]) if s["on"]]
    # 57.5 % / 33 % / 33 % of all beats, round-half-up, written out here
    n2, n13 = int(0.575 * beats + 0.5), int(0.33 * beats + 0.5)
    assert sum(1 for i in st if i % 4 == 2) == n2
    assert sum(1 for i in st if i % 4 == 1) == n13
    assert sum(1 for i in st if i % 4 == 3) == n13
    assert all(i % 4 != 0 for i in st)  # never on a kick step


def test_ghost_exact_numbers_16_bars():
    line = gp.bass_line(33, bars=16, seed=3, roll="offbeat_ghost")
    st = [i for i, s in enumerate(line["steps"]) if s["on"]]
    assert [sum(1 for i in st if i % 4 == k) for k in (1, 2, 3)] == [21, 37, 21]


def test_ghost_velocity_in_arrangement():
    t, _ = tracks(seed=5, roll="offbeat_ghost")
    notes = t["bass"]["notes"]
    assert notes
    for on, _off, _pitch, vel in notes:
        if on % PPQ == 240:
            assert vel > 70  # the off-beat 8th keeps its normal velocity
        else:
            assert on % PPQ in (120, 360) and vel <= 70


# ------------------------------------------------------------ bass gate from the engine preset

@pytest.mark.parametrize("preset", sorted(GATES))
@pytest.mark.parametrize("bpm", [135.0, 142.5, 150.0])
def test_bass_note_length_is_preset_gate(preset, bpm):
    t, _ = tracks(seed=1, bpm=bpm, roll="offbeat_8th", bass_preset=preset)
    expect = round(GATES[preset] * bpm * 0.008)  # ms * bpm / 60000 * 480 ticks
    assert {off - on for on, off, _, _ in t["bass"]["notes"]} == {expect}


def test_gate_is_capped_below_next_note():
    # goa-roll-long at 150 BPM = 120 ticks = a full 16th: must end before the next onset
    t, _ = tracks(seed=1, bpm=150.0, roll="off_kick_16th", bass_preset="goa-roll-long")
    by_on = sorted(t["bass"]["notes"])
    tight = 0
    for a, b in zip(by_on, by_on[1:], strict=False):
        assert a[1] < b[0]  # every note ends before the next one starts
        if b[0] - a[0] == 120:  # adjacent 16ths: gate 120 is capped to 119
            assert a[1] - a[0] == 119
            tight += 1
    assert tight > 0


def test_preset_choice_changes_samples_and_midi():
    a = ga.build_midi(seed=1, bass_preset="goa-roll-short", roll="offbeat_8th")
    b = ga.build_midi(seed=1, bass_preset="goa-roll-long", roll="offbeat_8th")
    assert a != b
    with pytest.raises(ValueError):
        ga.build_arrangement(bass_preset="nope")
    with pytest.raises(ValueError):
        ga.build_arrangement(kick_preset="goa-roll-short")  # a bass preset is not a kick preset


# ------------------------------------------------------------ form

def section_list(**p):
    return [(s["name"], s["bars"]) for s in ga.build_arrangement(**p)["sections"]]


def test_kickless_intro():
    p = dict(seed=2, intro_bars=24)
    arr = ga.build_arrangement(**p)
    first = arr["sections"][0]
    assert (first["name"], first["bars"], first["elements"]) == \
        ("Intro no kick", 24, ["pad", "perc"])
    t, _ = tracks(**p)
    assert min(n[0] for n in t["kick"]["notes"]) == 24 * BAR  # kick enters after the intro
    assert min(n[0] for n in t["bass"]["notes"]) >= 24 * BAR
    assert min(n[0] for n in t["pad"]["notes"]) == 0


@pytest.mark.parametrize("b,total,names_gone", [
    (2, 224, set()),
    (1, 200, {"Break 1", "Return"}),
    (0, 184, {"Break 1", "Return", "Break 2"}),
])
def test_breakdown_count(b, total, names_gone):
    names = {n for n, _ in section_list(seed=1)}
    got = section_list(seed=1, breakdowns=b)
    assert sum(x for _, x in got) == total
    assert names - {n for n, _ in got} == names_gone
    arr = ga.build_arrangement(seed=1, breakdowns=b)
    kickless = [s for s in arr["sections"] if "kick" not in s["elements"]]
    assert len(kickless) == b


def test_outro_modes():
    total = 224 - 8 + 16
    for mode in ("kick_on", "kick_less"):
        p = dict(seed=3, outro=mode, outro_bars=16)
        t, cond = tracks(**p)
        last_kick_off = max(n[1] for n in t["kick"]["notes"])
        assert cond["end"] == total * BAR
        if mode == "kick_on":
            assert last_kick_off == total * BAR - PPQ + 120  # last beat of the file, 0.25 beat
        else:
            assert last_kick_off <= (total - 16) * BAR  # no kick in the last 16 bars
            last = ga.build_arrangement(**p)["sections"][-1]
            assert (last["name"], last["bars"], last["elements"]) == \
                ("Outro", 16, ["pad", "perc"])


def test_dj_intro_outro_still_wraps_new_form():
    got = section_list(seed=1, dj_bars=16, intro_bars=8, outro="kick_less")
    assert got[0] == ("DJ Intro", 16) and got[1] == ("Intro no kick", 8)
    assert got[-1] == ("DJ Outro", 16) and got[-2] == ("Outro", 8)


@pytest.mark.parametrize("i", range(30))
def test_random_option_combinations(i):
    rng = random.Random(900 + i)
    p = dict(seed=rng.randint(0, 10**6), bpm=round(rng.uniform(135, 150), 1),
             roll=rng.choice(ROLLS), dj_bars=rng.choice([0, 8, 16, 32]),
             intro_bars=rng.choice([0, 8, 16, 24, 32]), breakdowns=rng.choice([0, 1, 2]),
             outro=rng.choice(["kick_on", "kick_less"]), outro_bars=rng.choice([8, 16, 24, 32]),
             bass_preset=rng.choice(sorted(GATES)))
    total = ({0: 184, 1: 200, 2: 224}[p["breakdowns"]] - 8 + p["outro_bars"] + p["intro_bars"]
             + 2 * p["dj_bars"])
    t, cond = tracks(**p)
    assert cond["end"] == total * BAR
    assert cond["tempo"] == round(60_000_000 / p["bpm"])
    assert ga.build_midi(**p) == ga.build_midi(**p)
    if p["intro_bars"] and not p["dj_bars"]:
        assert min(n[0] for n in t["kick"]["notes"]) == p["intro_bars"] * BAR
    if p["outro"] == "kick_less" and not p["dj_bars"]:
        assert max(n[1] for n in t["kick"]["notes"]) <= (total - p["outro_bars"]) * BAR


def test_each_option_changes_output():
    base = ga.build_midi(seed=1)
    for change in (dict(roll="offbeat_ghost"), dict(intro_bars=8), dict(breakdowns=1),
                   dict(outro="kick_less"), dict(outro_bars=16), dict(bpm=140.0),
                   dict(bass_preset="goa-roll-long")):
        assert ga.build_midi(seed=1, **change) != base, change


@pytest.mark.parametrize("bad", [dict(intro_bars=5), dict(breakdowns=3), dict(outro="x"),
                                 dict(outro_bars=4), dict(breakdowns=True),
                                 dict(hat_preset="nope")])
def test_invalid_options(bad):
    with pytest.raises(ValueError):
        ga.build_arrangement(**bad)


# ------------------------------------------------------------ files: README + engine samples

def test_cli_options_readme_and_samples(tmp_path):
    out = tmp_path / "o"
    assert ga.main(["--out", str(out), "--seed", "4", "--bpm", "141", "--roll", "offbeat_ghost",
                    "--intro-bars", "16", "--breakdowns", "1", "--outro", "kick_less",
                    "--outro-bars", "16", "--bass-preset", "goa-roll-long"]) == 0
    text = (out / "README.md").read_text(encoding="utf-8")
    for needle in ("| tempo | 141 BPM", "inside", "`offbeat_ghost`", "| kick-less intro | 16 bars",
                   "| breakdowns | 1 |", "`kick_less`, 16 bars", "`goa-roll-long` (gate 100 ms",
                   "| DJ intro/outro | 0 bars each |", "Intro no kick"):
        assert needle in text, needle
    assert "NOT derived from presets" in text and "rendered WAV only" in text
    assert "key-dependent" in text and "MIDI 33 for this key" in text  # root A: 24 + 9
    assert "the rendered one-shot is at MIDI 36" in text
    # samples are exactly what the engines render from the presets
    for cat, preset in (("kick", "dense"), ("bass", "goa-roll-long"), ("hat", "closed-std")):
        wav = (out / "samples" / f"{cat}_{preset}.wav").read_bytes()
        assert wav == render_sample_wav(cat, load_preset(preset, cat))[0]
    # repeat run: identical bytes in every file
    out2 = tmp_path / "o2"
    assert ga.main(["--out", str(out2), "--seed", "4", "--bpm", "141", "--roll", "offbeat_ghost",
                    "--intro-bars", "16", "--breakdowns", "1", "--outro", "kick_less",
                    "--outro-bars", "16", "--bass-preset", "goa-roll-long"]) == 0
    files = sorted(p.relative_to(out) for p in out.rglob("*") if p.is_file())
    assert len(files) == 5
    for f in files:
        assert (out / f).read_bytes() == (out2 / f).read_bytes()
    # existing sample target blocks everything
    assert ga.main(["--out", str(out), "--seed", "4", "--bpm", "141"]) == 2


def test_readme_marks_tempo_outside_reference_range(tmp_path):
    assert ga.main(["--out", str(tmp_path / "x"), "--bpm", "136", "--no-samples"]) == 0
    assert "outside" in (tmp_path / "x" / "README.md").read_text(encoding="utf-8")
    assert not (tmp_path / "x" / "samples").exists()
