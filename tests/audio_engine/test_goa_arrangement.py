"""Tests for the Goa bass-roll variants and the full-track multitrack SMF generator.

CI only: the SMF is read back with a parser defined in this file (no mido, no Live).
Expected values (tick positions, track names, sha256 of the pre-change default output)
are written here, not taken from the code under test."""

import hashlib
import random

import pytest

from audio_engine import goa_arrangement as ga
from audio_engine import goa_patterns as gp

PPQ = 480
BAR = 1920
SCALE_PCS = {
    "phrygian": {0, 1, 3, 5, 7, 8, 10},
    "phrygian_dominant": {0, 1, 4, 5, 7, 8, 10},
    "harmonic_minor": {0, 2, 3, 5, 7, 8, 11},
    "aeolian": {0, 2, 3, 5, 7, 8, 10},
}
TRACKS = ["kick", "bass", "lead", "arp", "pad", "perc"]
ROLLS = ["off_kick_16th", "offbeat_8th", "gallop", "triplet_gallop"]

# (kind, seed, bars, bpm, scale, extra) -> (sha256 of to_json, sha256 of MIDI bytes),
# computed from the UNMODIFIED origin/main 3779f0b (before the roll option existed).
PINNED = {
    ("bass", 0, 4, 145.0, "phrygian", ()): (
        "42b86a3fff6fde8e88dfe7852a72efc233870d23b467b78106b4a063a60cafa5",
        "de4abc08376e9e2e49357b45230755a1b6ca3446a0d17b0480ce3ffb08978c8c"),
    ("bass", 7, 8, 140.0, "harmonic_minor",
     (("density", 0.5), ("accent", 0.3), ("slide", 0.2))): (
        "31382268886d1e15f6d2b8005c0a625dfa2cf65a0c7e9f2745123b5fc2d4eece",
        "d6b6546e2319c25328791e3ffc53779cc55a9048391dad4c318a0bcd5792ebc8"),
    ("bass", 123, 16, 150.0, "aeolian", (("density", 1.0),)): (
        "a8612ead2ac4239229cd44f7cc4c053c42e2a07833f7e2de8de5e8a51cd15002",
        "052932a3131bacdc7e218e122ee2787e468479508486139cdc07e5a1d2249696"),
    ("bass", 5, 1, 135.0, "phrygian_dominant", ()): (
        "1de70f662fca441066048fe87582cd6315711a346613bec0a38127722d36eb68",
        "66623f36a8a7119416c3a4aee9f1621a5861a3cfebc5bafbdc561f1921639e5d"),
    ("lead", 0, 4, 145.0, "phrygian", ()): (
        "c8982465400575433abf84c3f52251b4f90cd5f4537febb90f7c5df8213b68c4",
        "5951f1adeee7e89e7f1b9a56c09069cc6476c462785ba20d358523e51a65aba1"),
    ("lead", 7, 8, 140.0, "harmonic_minor",
     (("density", 0.5), ("accent", 0.3), ("slide", 0.2))): (
        "1e91ddf49c5decf3b2394c27f2858a4ba44d1e014e92de0df1cc7fa242ca2faa",
        "65b2d8f23136e276cd85745badf0360b98881c60f156cc5dde6b87465e1b3b91"),
    ("lead", 123, 16, 150.0, "aeolian", (("density", 1.0),)): (
        "d2598a5858d212e9c09ae2dd7e7d73f3bd8fde399b4d5165c45f7f28693d77bf",
        "b821b714190a90131db503c02abb5f3a87c4775adf54559b907f40d821d0c877"),
    ("arp", 0, 4, 145.0, "phrygian", ()): (
        "8df074da4bc666a79015e2ec5a4c510cc0d861b4df73c07e8932e6a8a11d1228",
        "1275620f155da6b42ad07459a6eafeb6cf55f41e7dd52ba6f5d30bafdaea6798"),
    ("arp", 7, 8, 140.0, "harmonic_minor",
     (("density", 0.5), ("accent", 0.3), ("slide", 0.2))): (
        "b495e4a72ea384a91b3b81d4471201f57df6aea62e3e14f21a1fbc48c7115551",
        "ffe0f105013c82f49b37e2dac024fc8bab9206602a7b9212c1777e053ccc58e0"),
}


def read_smf(data):
    """Independent SMF reader -> (format, ppq, [track]); track = dict(name, tempo, markers,
    texts, notes, end); notes = [(on_tick, off_tick, pitch, velocity)]."""
    assert data[:4] == b"MThd" and int.from_bytes(data[4:8], "big") == 6
    fmt = int.from_bytes(data[8:10], "big")
    n = int.from_bytes(data[10:12], "big")
    ppq = int.from_bytes(data[12:14], "big")
    pos = 14
    tracks = []

    def vlq(buf, i):
        v = 0
        while True:
            b = buf[i]
            i += 1
            v = (v << 7) | (b & 0x7F)
            if not b & 0x80:
                return v, i

    for _ in range(n):
        assert data[pos:pos + 4] == b"MTrk"
        ln = int.from_bytes(data[pos + 4:pos + 8], "big")
        body = data[pos + 8:pos + 8 + ln]
        pos += 8 + ln
        i = t = 0
        tr = {"name": None, "tempo": None, "markers": [], "texts": [], "notes": [], "end": None}
        open_ = {}
        while i < len(body):
            d, i = vlq(body, i)
            t += d
            st = body[i]
            if st == 0xFF:
                typ = body[i + 1]
                l2, j = vlq(body, i + 2)
                pl = body[j:j + l2]
                i = j + l2
                if typ == 0x03:
                    tr["name"] = pl.decode()
                elif typ == 0x51:
                    tr["tempo"] = int.from_bytes(pl, "big")
                elif typ == 0x06:
                    tr["markers"].append((t, pl.decode()))
                elif typ == 0x01:
                    tr["texts"].append(pl.decode())
                elif typ == 0x2F:
                    tr["end"] = t
            elif st == 0x90:
                assert body[i + 1] not in open_, "same-pitch overlap"
                open_[body[i + 1]] = (t, body[i + 2])
                i += 3
            elif st == 0x80:
                on, v = open_.pop(body[i + 1])
                tr["notes"].append((on, t, body[i + 1], v))
                i += 3
            else:
                raise AssertionError(f"unexpected status {st:#x}")
        assert not open_
        tracks.append(tr)
    assert pos == len(data)
    return fmt, ppq, tracks


# ------------------------------------------------------------ default stays identical

@pytest.mark.parametrize("key", list(PINNED))
def test_default_output_is_byte_identical_to_main(key):
    kind, seed, bars, bpm, scale, extra = key
    line = gp.generate(kind, root=33, scale=scale, bars=bars, seed=seed, bpm=bpm, **dict(extra))
    jh, mh = PINNED[key]
    assert hashlib.sha256(gp.to_json(line).encode()).hexdigest() == jh
    assert hashlib.sha256(gp.line_to_midi(line)).hexdigest() == mh


def test_explicit_default_roll_equals_omitted_roll():
    for seed in range(10):
        a = gp.bass_line(33, "phrygian", 8, seed=seed)
        b = gp.bass_line(33, "phrygian", 8, seed=seed, roll="off_kick_16th")
        assert gp.to_json(a) == gp.to_json(b)


# ------------------------------------------------------------ roll variants

def on_steps(line):
    return [i for i, s in enumerate(line["steps"]) if s["on"]]


@pytest.mark.parametrize("seed", range(20))
def test_grid_rolls_keep_their_steps(seed):
    rng = random.Random(seed)
    bpm = rng.uniform(135, 150)
    scale = rng.choice(sorted(SCALE_PCS))
    bars = rng.randint(1, 16)
    root = rng.randint(24, 40)
    for roll, allowed, per_bar in (("off_kick_16th", {1, 2, 3}, 9),
                                   ("offbeat_8th", {2}, 4), ("gallop", {1, 3}, 8)):
        line = gp.bass_line(root, scale, bars, seed=seed, bpm=bpm, roll=roll,
                            accent=rng.random())
        st = on_steps(line)
        assert {s % 4 for s in st} <= allowed
        assert len(st) == per_bar * bars
        assert all(((line["steps"][s]["note"] - root) % 12) in SCALE_PCS[scale] for s in st)
        for b in range(bars):  # the earliest note of every bar is the root
            first = min(s for s in st if s // 16 == b)
            assert line["steps"][first]["note"] == root
    # determinism
    assert gp.to_json(gp.bass_line(33, bars=4, seed=seed, roll="gallop")) == \
        gp.to_json(gp.bass_line(33, bars=4, seed=seed, roll="gallop"))


@pytest.mark.parametrize("seed", range(20))
def test_triplet_gallop_positions(seed):
    rng = random.Random(1000 + seed)
    bars = rng.randint(1, 16)
    scale = rng.choice(sorted(SCALE_PCS))
    pat = gp.bass_triplet_gallop(33, scale, bars, seed=seed, bpm=rng.uniform(135, 150))
    assert set(pat) == {"length_beats", "notes"}
    assert pat["length_beats"] == 4 * bars
    assert len(pat["notes"]) == 8 * bars
    for n in pat["notes"]:
        ticks = round(n["start"] * PPQ)
        assert ticks % PPQ in (160, 320)  # beat + 1/3 and beat + 2/3, never on the kick
        assert round(n["duration"] * PPQ) == 96
        assert ticks + 96 <= bars * BAR
        assert (n["pitch"] - 33) % 12 in SCALE_PCS[scale]
    assert pat == gp.bass_triplet_gallop(33, scale, bars, seed=seed, bpm=140.0)


def test_roll_errors():
    with pytest.raises(ValueError):
        gp.bass_line(33, roll="triplet_gallop")
    with pytest.raises(ValueError):
        gp.bass_line(33, roll="nope")
    with pytest.raises(ValueError):
        gp.bass_triplet_gallop(33, density=1.5)


def test_patterns_cli_triplet_roll(tmp_path):
    out = tmp_path / "t.mid"
    assert gp.main(["--kind", "bass", "--root", "33", "--roll", "triplet_gallop", "--bars", "2",
                    "--out", str(out)]) == 0
    fmt, ppq, tracks = read_smf(out.read_bytes())
    assert fmt == 1 and ppq == PPQ
    bass = tracks[1]["notes"]
    assert len(bass) == 16 and all(a % PPQ in (160, 320) for a, *_ in bass)
    assert gp.main(["--kind", "lead", "--root", "60", "--roll", "gallop",
                    "--out", str(tmp_path / "x.mid")]) == 2


# ------------------------------------------------------------ full track

def expected_sections(dj):
    """Written out here: (name, bars) in order; energy/element expectations are checked
    separately from the arrangement dict."""
    base = [("Intro", 8), ("Groove", 8), ("Build 1", 8), ("Build 2", 8), ("Build 3", 8),
            ("Climb 1", 16), ("Climb 2", 16), ("Break 1", 16), ("Return", 8), ("Build 4", 8),
            ("Build 5", 8), ("Climb 3", 16), ("Peak 1", 16), ("Peak 2", 16), ("Break 2", 16),
            ("Final 1", 16), ("Final 2", 16), ("Taper", 8), ("Outro", 8)]
    return ([("DJ Intro", dj)] if dj else []) + base + ([("DJ Outro", dj)] if dj else [])


def params_for(i):
    rng = random.Random(i)
    return dict(seed=rng.randint(-5, 10**6), bpm=round(rng.uniform(135, 150), 2),
                root=rng.choice(ga.ROOT_NAMES), scale=rng.choice(sorted(SCALE_PCS)),
                roll=ROLLS[i % 4], dj_bars=rng.choice([0, 8, 16, 32]))


@pytest.mark.parametrize("i", range(24))
def test_track_smf_matches_plan(i):
    p = params_for(i)
    arr = ga.build_arrangement(**p)
    fmt, ppq, tracks = read_smf(ga.build_midi(**p))
    exp = expected_sections(p["dj_bars"])
    total = sum(b for _, b in exp)
    assert fmt == 1 and ppq == PPQ and len(tracks) == 7
    assert [t["name"] for t in tracks[1:]] == TRACKS
    assert {t["end"] for t in tracks} == {total * BAR}
    cond = tracks[0]
    assert cond["tempo"] == round(60_000_000 / p["bpm"])
    assert f"key: {p['root']} {p['scale']}" in cond["texts"]
    starts, pos = [], 0
    for name, bars in exp:
        starts.append((pos * BAR, name))
        pos += bars
    assert cond["markers"] == starts
    assert [(s["name"], s["bars"]) for s in arr["sections"]] == exp
    pc = ga.ROOT_NAMES.index(p["root"])
    for trk, name in zip(tracks[1:], TRACKS, strict=True):
        notes = trk["notes"]
        assert notes, name
        active = []
        pos = 0
        for s in arr["sections"]:
            if name in s["elements"]:
                active.append((pos * BAR, (pos + s["bars"]) * BAR))
            pos += s["bars"]
        for on, off, pitch, vel in notes:
            assert off > on and off <= total * BAR
            assert 1 <= vel <= 127 and 0 <= pitch <= 127
            assert any(a <= on < b and off <= b for a, b in active), (name, on)
        if name in ("bass", "lead", "arp", "pad"):
            assert all((pn - pc) % 12 in SCALE_PCS[p["scale"]] for _, _, pn, _ in notes)
        if name == "kick":
            expect = [b * PPQ for b in range(0, total * 4)
                      if any(a <= b * PPQ < e for a, e in active)]
            assert [n[0] for n in notes] == expect
            assert {n[2] for n in notes} == {36}
        if name == "bass":
            mods = {"off_kick_16th": None, "offbeat_8th": {240}, "gallop": {120, 360},
                    "triplet_gallop": {160, 320}}[p["roll"]]
            for on, *_ in notes:
                if mods is None:
                    assert on % PPQ != 0
                else:
                    assert on % PPQ in mods
        if name == "perc":
            assert {n[2] for n in notes} <= {42, 44, 70}


def test_energy_curve_and_structure():
    arr = ga.build_arrangement(seed=1, bpm=145)
    secs = arr["sections"]
    assert sum(s["bars"] for s in secs) == 224
    pos = 0
    for s in secs:
        assert pos % 8 == 0 and s["bars"] % 8 == 0
        pos += s["bars"]
    e = {s["name"]: s["energy"] for s in secs}
    assert e["Climb 2"] < e["Peak 2"] < e["Final 2"] == 1.0  # rising sawtooth peaks
    for brk in ("Break 1", "Break 2"):
        s = next(x for x in secs if x["name"] == brk)
        assert "kick" not in s["elements"] and "bass" not in s["elements"]
        assert s["energy"] < 0.4
    # layers accumulate through the first build
    first = [x for x in secs[:5]]
    assert [len(x["elements"]) for x in first] == [2, 3, 4, 5, 6]
    assert [x["energy"] for x in first] == sorted(x["energy"] for x in first)
    # 224 bars at 135-150 BPM = 5.97 to 6.63 minutes
    assert 5.9 < 224 * 4 * 60 / 150 / 60 and 224 * 4 * 60 / 135 / 60 < 6.7


def test_velocity_follows_energy():
    arr = ga.build_arrangement(seed=2, bpm=140)
    _, _, tracks = read_smf(ga.build_midi(seed=2, bpm=140))
    kick = tracks[1]["notes"]
    pos = 0
    for s in arr["sections"]:
        if "kick" in s["elements"]:
            vels = {v for on, _, _, v in kick if pos * BAR <= on < (pos + s["bars"]) * BAR}
            assert vels == {int(110 * (0.7 + 0.3 * s["energy"]) + 0.5)}
        pos += s["bars"]


@pytest.mark.parametrize("roll", ROLLS)
def test_deterministic_and_seed_sensitive(roll):
    a = ga.build_midi(seed=4, bpm=142, roll=roll)
    assert a == ga.build_midi(seed=4, bpm=142, roll=roll)
    assert a != ga.build_midi(seed=5, bpm=142, roll=roll)
    assert a != ga.build_midi(seed=4, bpm=142, roll=roll, dj_bars=16)


def test_roll_changes_bass_only():
    a = read_smf(ga.build_midi(seed=4, roll="off_kick_16th"))[2]
    b = read_smf(ga.build_midi(seed=4, roll="offbeat_8th"))[2]
    assert a[2]["notes"] != b[2]["notes"]  # bass differs
    for idx in (1, 5, 6):  # kick, pad, perc identical
        assert a[idx]["notes"] == b[idx]["notes"]


def test_dj_intro_outro_content():
    arr = ga.build_arrangement(seed=3, dj_bars=16)
    first, last = arr["sections"][0], arr["sections"][-1]
    assert first["name"] == "DJ Intro" and first["bars"] == 16
    assert first["elements"] == ["kick", "perc"]
    assert last["name"] == "DJ Outro" and last["elements"] == ["kick", "bass", "perc"]
    with pytest.raises(ValueError):
        ga.build_arrangement(dj_bars=12)


@pytest.mark.parametrize("bad", [dict(bpm=134.9), dict(bpm=150.1), dict(root="H"),
                                 dict(scale="dorian"), dict(roll="x"), dict(seed=1.5)])
def test_invalid_parameters(bad):
    with pytest.raises(ValueError):
        ga.build_arrangement(**bad)


# ------------------------------------------------------------ CLI and files

def test_cli_writes_and_refuses_overwrite(tmp_path):
    out = tmp_path / "run"
    assert ga.main(["--out", str(out), "--seed", "9", "--bpm", "140",
                    "--dj-intro-outro"]) == 0
    mid = out / "goa_seed9_140bpm.mid"
    readme = out / "README.md"
    assert mid.read_bytes() == ga.build_midi(seed=9, bpm=140.0, dj_bars=16)
    text = readme.read_text(encoding="utf-8")
    for t in TRACKS:
        assert f"| {t} |" in text
    assert "Drift" in text and "NOT tested in Live" in text and "DJ Intro" in text
    before = (mid.read_bytes(), text)
    assert ga.main(["--out", str(out), "--seed", "9", "--bpm", "140"]) == 2
    assert (mid.read_bytes(), readme.read_text(encoding="utf-8")) == before
    # a pre-existing README alone also blocks, and nothing is written
    other = tmp_path / "other"
    other.mkdir()
    (other / "README.md").write_text("mine")
    assert ga.main(["--out", str(other), "--seed", "1"]) == 2
    assert [p.name for p in other.iterdir()] == ["README.md"]
    assert (other / "README.md").read_text() == "mine"


def test_cli_repeat_runs_identical_and_bad_bpm_writes_nothing(tmp_path):
    for d in ("a", "b"):
        assert ga.main(["--out", str(tmp_path / d), "--seed", "2", "--roll", "gallop"]) == 0
    for name in ("goa_seed2_145bpm.mid", "README.md"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()
    assert ga.main(["--out", str(tmp_path / "c"), "--bpm", "120"]) == 2
    assert not (tmp_path / "c").exists()
