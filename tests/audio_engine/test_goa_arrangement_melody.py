"""Melodic voices in the Goa arrangement (issue #397, D-027): lead, arp, pad and pluck come
from goa_melody and every melody option changes the output measurably. Expected values are
written here (section start bars, note counts per bar, MIDI windows, pitch classes); MIDI is
read back with the independent parser of test_goa_arrangement."""

import itertools
import random

import pytest
from test_goa_arrangement import read_smf

from audio_engine import goa_arrangement as ga

PPQ, BAR = 480, 1920
MELODIC = ["lead", "arp", "pad", "pluck"]
TRACKS = ["kick", "bass", "lead", "arp", "pad", "pluck", "perc", "snare", "clap", "rim"]
PCS = {"phrygian": {0, 1, 3, 5, 7, 8, 10}, "phrygian_dominant": {0, 1, 4, 5, 7, 8, 10},
       "harmonic_minor": {0, 2, 3, 5, 7, 8, 11}, "aeolian": {0, 2, 3, 5, 7, 8, 10}}
# MIDI window (start, size) per voice before the octave shift, written from the issue/docs
WINDOW = {"lead": (60, 24), "arp": (57, 24), "pad": (48, 12), "pluck": (36, 24)}
# default arrangement, (name, start bar, bars, energy); 224 bars
SECTIONS = {"Climb 1": (40, 16, 0.70), "Final 2": (192, 16, 1.0), "Peak 1": (128, 16, 0.88)}
PLUCK_SECTIONS = ["Build 3", "Climb 1", "Climb 2", "Build 5", "Climb 3", "Peak 1", "Peak 2",
                  "Final 1", "Final 2"]


def tracks(**p):
    _, _, t = read_smf(ga.build_midi(**p))
    return {x["name"]: x for x in t[1:]}


def in_section(notes, name):
    start, bars, _ = SECTIONS[name]
    return [n for n in notes if start * BAR <= n[0] < (start + bars) * BAR]


def per_bar(notes, name):
    start, bars, _ = SECTIONS[name]
    counts = [0] * bars
    for n in in_section(notes, name):
        counts[n[0] // BAR - start] += 1
    return counts


# ------------------------------------------------------------ default: one track per voice

def test_default_has_one_track_per_voice_without_duplicates():
    _, _, t = read_smf(ga.build_midi(seed=3))
    names = [x["name"] for x in t[1:]]
    assert names == TRACKS and len(set(names)) == len(names)
    arr = ga.build_arrangement(seed=3)
    assert [e["name"] for e in arr["elements"]] == TRACKS
    for s in arr["sections"]:
        assert len(set(s["elements"])) == len(s["elements"])
    assert [s["name"] for s in arr["sections"] if "pluck" in s["elements"]] == PLUCK_SECTIONS
    # the section start bars used by the other tests
    pos = 0
    for s in arr["sections"]:
        if s["name"] in SECTIONS:
            assert (pos, s["bars"], s["energy"]) == SECTIONS[s["name"]]
        pos += s["bars"]
    assert pos == 224


# ------------------------------------------------------------ melody_voices

@pytest.mark.parametrize("keep", [c for r in range(5) for c in itertools.combinations(MELODIC, r)])
def test_voice_subsets(keep):
    base = tracks(seed=6)
    got = tracks(seed=6, melody_voices=list(keep))
    assert list(got) == [t for t in TRACKS if t not in MELODIC or t in keep]
    arr = ga.build_arrangement(seed=6, melody_voices=list(keep))
    for s in arr["sections"]:
        assert not set(s["elements"]) & (set(MELODIC) - set(keep))
    for name in got:  # nothing else moves, the kept voices keep their notes
        assert got[name]["notes"] == base[name]["notes"], name


def test_empty_melody_voices_builds():
    arr = ga.build_arrangement(seed=1, melody_voices=[])
    assert [e["name"] for e in arr["elements"]] == \
        ["kick", "bass", "perc", "snare", "clap", "rim"]
    assert ga.build_midi(seed=1, melody_voices=()) == ga.build_midi(seed=1, melody_voices=[])


# ------------------------------------------------------------ density and section energy

def test_density_notes_per_bar_follow_density_and_energy():
    # lead round(d*8), arp/pluck round(d*16), d = density * (0.5 + 0.5 * energy), half up
    t = tracks(seed=2, density=1.0)
    assert set(per_bar(t["lead"]["notes"], "Final 2")) == {8}  # d 1.0
    assert set(per_bar(t["arp"]["notes"], "Final 2")) == {16}
    assert set(per_bar(t["pluck"]["notes"], "Final 2")) == {16}
    assert set(per_bar(t["lead"]["notes"], "Peak 1")) == {8}  # d 0.94 -> 7.52 -> 8
    assert set(per_bar(t["arp"]["notes"], "Peak 1")) == {15}  # 15.04 -> 15
    assert set(per_bar(t["arp"]["notes"], "Climb 1")) == {14}  # d 0.85 -> 13.6 -> 14
    assert set(per_bar(t["lead"]["notes"], "Climb 1")) == {7}  # 6.8 -> 7
    t = tracks(seed=2, density=0.5)
    assert set(per_bar(t["lead"]["notes"], "Final 2")) == {4}
    assert set(per_bar(t["arp"]["notes"], "Final 2")) == {8}
    assert set(per_bar(t["pluck"]["notes"], "Final 2")) == {8}


def test_density_zero_silences_line_voices_but_not_the_pad():
    t = tracks(seed=2, density=0.0)
    for v in ("lead", "arp", "pluck"):
        assert t[v]["notes"] == [], v
    # pad density 0: chords of 4 bars, 3 chord tones -> 4 chords x 3 notes in 16 bars
    assert len(in_section(t["pad"]["notes"], "Final 2")) == 12


def test_pad_chord_length_follows_density():
    # density 1 at energy 1: 1-bar chords of 3 tones -> 16 chords x 3 notes in 16 bars
    t = tracks(seed=2, density={"pad": 1.0})
    assert len(in_section(t["pad"]["notes"], "Final 2")) == 48
    # density 0.5 at energy 1: 4 - round(1.5) = 2-bar chords -> 8 x 3
    t = tracks(seed=2, density={"pad": 0.5})
    assert len(in_section(t["pad"]["notes"], "Final 2")) == 24


def test_per_voice_density_touches_only_that_voice():
    base = tracks(seed=4)
    got = tracks(seed=4, density={"arp": 0.25})
    assert got["arp"]["notes"] != base["arp"]["notes"]
    assert set(per_bar(got["arp"]["notes"], "Final 2")) == {4}  # d 0.25 * 1.0 -> 4.0
    for n in TRACKS:
        if n != "arp":
            assert got[n]["notes"] == base[n]["notes"], n


# ------------------------------------------------------------ register

def test_register_shifts_exact_octaves():
    base = tracks(seed=5)
    up = tracks(seed=5, register=1)
    for v in MELODIC:
        assert [(a, b, p + 12, w) for a, b, p, w in base[v]["notes"]] == up[v]["notes"], v
    for n in ("kick", "bass", "perc", "snare", "clap", "rim"):
        assert up[n]["notes"] == base[n]["notes"]
    mixed = tracks(seed=5, register={"lead": -1, "pad": 2})
    assert [(a, b, p - 12, w) for a, b, p, w in base["lead"]["notes"]] == mixed["lead"]["notes"]
    assert [(a, b, p + 24, w) for a, b, p, w in base["pad"]["notes"]] == mixed["pad"]["notes"]
    assert mixed["arp"]["notes"] == base["arp"]["notes"]
    assert mixed["pluck"]["notes"] == base["pluck"]["notes"]


# ------------------------------------------------------------ arp pattern and progression

def test_arp_up_and_down_follow_the_chord_tones():
    # progression [0] in A phrygian: chord A C E; tones in the arp window 57..80
    tones = [57, 60, 64, 69, 72, 76]
    for pattern, order in (("up", tones), ("down", tones[::-1])):
        t = tracks(seed=1, density=1.0, progression=[0], arp_pattern=pattern)
        sec = sorted(in_section(t["arp"]["notes"], "Final 2"))
        assert len(sec) == 16 * 16
        for on, _off, pitch, _v in sec:
            step = (on % BAR) // (PPQ // 4)
            assert pitch == order[step % 6], (pattern, on)


def test_arp_pattern_and_progression_change_only_the_arp():
    base = tracks(seed=1)
    for change in (dict(arp_pattern="down"), dict(progression=[3]), dict(progression=[0, 6])):
        got = tracks(seed=1, **change)
        assert got["arp"]["notes"] != base["arp"]["notes"], change
        assert got["lead"]["notes"] == base["lead"]["notes"], change
        assert got["pluck"]["notes"] == base["pluck"]["notes"], change
    # the pad follows the progression as well (chord per 4 bars at pad density 0)
    assert tracks(seed=1, progression=[3])["pad"]["notes"] != base["pad"]["notes"]


def test_arp_stays_on_the_chord_of_the_progression():
    for pattern in ("up", "down", "updown", "random"):
        t = tracks(seed=8, progression=[0], arp_pattern=pattern)
        assert {p % 12 for _, _, p, _ in t["arp"]["notes"]} <= {9, 0, 4}  # A C E, written out


# ------------------------------------------------------------ scale and root

@pytest.mark.parametrize("i", range(10))
def test_melody_follows_root_and_scale(i):
    rng = random.Random(70 + i)
    root, scale = rng.choice(ga.ROOT_NAMES), rng.choice(sorted(PCS))
    rpc = ga.ROOT_NAMES.index(root)
    t = tracks(seed=i, root=root, scale=scale)
    for v in MELODIC:
        assert t[v]["notes"], v
        assert all((p - rpc) % 12 in PCS[scale] for _, _, p, _ in t[v]["notes"]), v
    other = "C" if root != "C" else "D"
    assert tracks(seed=i, root=other, scale=scale)["lead"]["notes"] != t["lead"]["notes"]


# ------------------------------------------------------------ determinism, seed

def test_deterministic_and_seed_sensitive_melody():
    opts = dict(density={"lead": 0.8}, register=1, arp_pattern="updown", progression=[0, 5])
    a = ga.build_midi(seed=9, **opts)
    assert a == ga.build_midi(seed=9, **opts)
    other = tracks(seed=10, **opts)
    mine = tracks(seed=9, **opts)
    for v in ("lead", "arp", "pluck"):
        assert other[v]["notes"] != mine[v]["notes"], v


def test_each_melody_option_changes_the_output():
    base = ga.build_midi(seed=1)
    for change in (dict(melody_voices=["lead", "arp", "pad"]), dict(density=0.9),
                   dict(density={"pluck": 0.1}), dict(register=-1), dict(arp_pattern="random"),
                   dict(progression=[0, 6]), dict(root="D"), dict(scale="aeolian")):
        assert ga.build_midi(seed=1, **change) != base, change


# ------------------------------------------------------------ property test over the ranges

@pytest.mark.parametrize("i", range(25))
def test_random_melody_options(i):
    rng = random.Random(3000 + i)
    keep = [v for v in MELODIC if rng.random() < 0.7]
    reg = {v: rng.randint(-2, 2) for v in MELODIC}
    dens = {v: round(rng.random(), 2) for v in MELODIC}
    p = dict(seed=rng.randint(0, 10**6), bpm=round(rng.uniform(135, 150), 1),
             root=rng.choice(ga.ROOT_NAMES), scale=rng.choice(sorted(PCS)),
             melody_voices=keep, density=dens, register=reg,
             arp_pattern=rng.choice(["up", "down", "updown", "random", None]),
             progression=rng.choice([None, [0], [0, 5, 6, 4],
                                     [rng.randint(0, 6) for _ in range(5)]]))
    rpc = ga.ROOT_NAMES.index(p["root"])
    t = tracks(**p)
    assert list(t) == [n for n in TRACKS if n not in MELODIC or n in keep]
    for v in keep:
        lo = WINDOW[v][0] + 12 * reg[v]
        for on, off, pitch, vel in t[v]["notes"]:
            assert lo <= pitch < lo + WINDOW[v][1]
            assert (pitch - rpc) % 12 in PCS[p["scale"]]
            assert off > on and 1 <= vel <= 127
    assert ga.build_midi(**p) == ga.build_midi(**p)


# ------------------------------------------------------------ errors

@pytest.mark.parametrize("bad", [
    dict(density=1.5), dict(density=-0.1), dict(density={"bass": 0.5}), dict(register=3),
    dict(register={"lead": -3}), dict(register=1.5), dict(arp_pattern="x"),
    dict(progression=[7]), dict(progression=[]), dict(melody_voices=["bass"]),
    dict(melody_voices="lead"), dict(melody_voices=["lead", "lead"]),
    dict(melody_voices=[], density=2.0),  # validated even when every voice is off
])
def test_invalid_melody_options(bad):
    with pytest.raises(ValueError):
        ga.build_arrangement(**bad)


# ------------------------------------------------------------ CLI and README

CLI = ["--seed", "3", "--melody-voices", "lead,pad,pluck", "--density", "lead=0.9,pad=1",
       "--register", "arp=-1,lead=1", "--arp-pattern", "down", "--progression", "0,3,4",
       "--scale", "aeolian", "--root", "D", "--no-samples"]


def test_cli_melody_options_readme_and_bytes(tmp_path):
    out = tmp_path / "m"
    assert ga.main(["--out", str(out), *CLI]) == 0
    mid = out / "goa_seed3_145bpm.mid"
    expect = ga.build_midi(seed=3, melody_voices=["lead", "pad", "pluck"],
                           density={"lead": 0.9, "pad": 1.0}, register={"arp": -1, "lead": 1},
                           arp_pattern="down", progression=[0, 3, 4], scale="aeolian", root="D")
    assert mid.read_bytes() == expect
    _, _, t = read_smf(mid.read_bytes())
    assert [x["name"] for x in t[1:]] == ["kick", "bass", "lead", "pad", "pluck", "perc",
                                         "snare", "clap", "rim"]
    text = (out / "README.md").read_text(encoding="utf-8")
    for needle in ("| melodic voices | lead, pad, pluck", "lead 0.9, pad 1, pluck 0.5",
                   "lead +1, pad +0, pluck +0 octaves", "`down`",
                   "| progression (scale degrees) | 0,3,4",
                   "| lead | seeded ostinato lead", "| pluck | seeded 16th-grid pluck",
                   "kick, bass, hat, snare, clap and rim engines"):
        assert needle in text, needle
    assert "| arp |" not in text and "rendered by the kick, bass and hat engines" not in text
    out2 = tmp_path / "m2"
    assert ga.main(["--out", str(out2), *CLI]) == 0
    assert (out2 / "README.md").read_bytes() == (out / "README.md").read_bytes()
    assert mid.read_bytes() == (out2 / mid.name).read_bytes()


def test_cli_default_readme_lists_all_melodic_tracks_and_options(tmp_path):
    assert ga.main(["--out", str(tmp_path / "d"), "--no-samples"]) == 0
    text = (tmp_path / "d" / "README.md").read_text(encoding="utf-8")
    for needle in ("| melodic voices | lead, arp, pad, pluck", "per cycle by seed", "| lead |",
                   "| arp |", "| pad |", "| pluck |", "kick, bass, hat, snare, clap and rim"):
        assert needle in text, needle


@pytest.mark.parametrize("bad", [["--melody-voices", "lead,bass"], ["--density", "1.5"],
                                 ["--register", "5"], ["--progression", "0,9"],
                                 ["--density", "bass=1"]])
def test_cli_bad_melody_option_writes_nothing(tmp_path, bad):
    assert ga.main(["--out", str(tmp_path / "x"), "--no-samples", *bad]) == 2
    assert not (tmp_path / "x").exists()
