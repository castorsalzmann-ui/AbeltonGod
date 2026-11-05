"""Tests for audio_engine.goa_melody (#393). Expected values are written in the tests; the MIDI
is read back with a small independent SMF parser below (not arrangement_midi)."""

from __future__ import annotations

import random
import struct
from pathlib import Path

import pytest

from audio_engine import goa_melody as gm

PPQ = 480
BAR = 1920


# ------------------------------------------------------------ independent SMF reader

def _vlq(data: bytes, i: int) -> tuple[int, int]:
    v = 0
    while True:
        b = data[i]
        i += 1
        v = (v << 7) | (b & 0x7F)
        if not b & 0x80:
            return v, i


def read_smf(data: bytes) -> dict:
    assert data[:4] == b"MThd"
    fmt, ntr, ppq = struct.unpack(">HHH", data[8:14])
    assert (fmt, ppq) == (1, PPQ)
    i = 14
    tracks = []
    for _ in range(ntr):
        assert data[i:i + 4] == b"MTrk"
        (ln,) = struct.unpack(">I", data[i + 4:i + 8])
        body, i = data[i + 8:i + 8 + ln], i + 8 + ln
        t, j, name, notes, open_, meta, end = 0, 0, None, [], {}, [], None
        while j < len(body):
            dt, j = _vlq(body, j)
            t += dt
            st = body[j]
            if st == 0xFF:
                typ = body[j + 1]
                ln2, j = _vlq(body, j + 2)
                payload = body[j:j + ln2]
                j += ln2
                if typ == 0x03:
                    name = payload.decode()
                elif typ == 0x2F:
                    end = t
                else:
                    meta.append((t, typ, payload))
            else:
                kind, p, v = st & 0xF0, body[j + 1], body[j + 2]
                j += 3
                if kind == 0x90 and v > 0:
                    assert p not in open_, "overlapping same-pitch notes"
                    open_[p] = (t, v)
                else:
                    s, vel = open_.pop(p)
                    notes.append((s, t, p, vel))
        assert not open_
        tracks.append({"name": name, "notes": sorted(notes), "meta": meta, "end": end})
    return {"tracks": tracks, "by_name": {t["name"]: t for t in tracks[1:]}}


def render(**params):
    return read_smf(gm.build_midi(**params))


def one_section(bars=4, energy=1.0, voices=("lead", "arp", "pad", "pluck")):
    return [{"name": "S", "bars": bars, "energy": energy, "voices": list(voices)}]


def pcs(notes):
    return {n[2] % 12 for n in notes}


# ------------------------------------------------------------ determinism / structure

def test_same_params_same_bytes_and_seed_changes_output():
    a = gm.build_midi(seed=5)
    assert a == gm.build_midi(seed=5)
    assert a != gm.build_midi(seed=6)


def test_track_layout_and_header():
    r = render(seed=1, bpm=140, root="C#", scale="aeolian", sections=one_section(6))
    assert [t["name"] for t in r["tracks"][1:]] == ["lead", "arp", "pad", "pluck"]
    cond = r["tracks"][0]
    assert (0, 0x51, (428571).to_bytes(3, "big")) in cond["meta"]  # 60e6/140 = 428571.4
    assert (0, 0x01, b"key: C# aeolian") in cond["meta"]
    assert all(t["end"] == 6 * BAR for t in r["tracks"])


def test_voices_option_limits_tracks():
    r = render(voices=["pad", "lead"], sections=one_section(2))
    assert list(r["by_name"]) == ["lead", "pad"]


# ------------------------------------------------------------ note counts (expected written here)

def test_note_counts_at_density_one_and_half():
    r = render(density=1.0, length=4, sections=one_section(4))
    assert len(r["by_name"]["lead"]["notes"]) == 4 * 8
    assert len(r["by_name"]["arp"]["notes"]) == 4 * 16
    assert len(r["by_name"]["pluck"]["notes"]) == 4 * 16
    assert len(r["by_name"]["pad"]["notes"]) == 4 * 3  # 1-bar chords, 3 tones each
    r = render(density=0.5, length=4, sections=one_section(4))
    assert len(r["by_name"]["lead"]["notes"]) == 4 * 4
    assert len(r["by_name"]["arp"]["notes"]) == 4 * 8
    assert len(r["by_name"]["pluck"]["notes"]) == 4 * 8


def test_density_zero_silences_lead_arp_pluck_but_not_pad():
    r = render(density=0.0, sections=one_section(4))
    for v in ("lead", "arp", "pluck"):
        assert r["by_name"][v]["notes"] == []
    pad = r["by_name"]["pad"]["notes"]
    assert len(pad) == 3  # one 4-bar chord
    assert {(n[0], n[1]) for n in pad} == {(0, 4 * BAR - 30)}  # 4 bars minus 1/16 beat (30 ticks)


def test_density_is_monotone_in_note_count_and_per_voice_override():
    counts = [len(render(density={"lead": d}, sections=one_section(4, voices=["lead"]))
                  ["by_name"]["lead"]["notes"]) for d in (0, 0.25, 0.5, 0.75, 1)]
    assert counts == [0, 8, 16, 24, 32]
    r = render(density={"lead": 1.0, "arp": 0.25}, sections=one_section(4))
    assert len(r["by_name"]["lead"]["notes"]) == 32
    assert len(r["by_name"]["arp"]["notes"]) == 16  # round(0.25 * 16) = 4 per bar


def test_pad_chord_length_follows_density():
    # density -> chord length in bars (4 - round(3d)): 0 -> 4, 0.34 -> 3, 0.67 -> 2, 1 -> 1
    for d, chord_starts in ((0.0, [0]), (0.34, [0, 3]), (0.67, [0, 2]), (1.0, [0, 1, 2, 3])):
        r = render(density={"pad": d}, length=4, sections=one_section(4, voices=["pad"]))
        starts = sorted({n[0] for n in r["by_name"]["pad"]["notes"]})
        assert starts == [b * BAR for b in chord_starts], d


# ------------------------------------------------------------ pitch content

A_PHRYGIAN = {9, 10, 0, 2, 4, 5, 7}
A_HARMONIC_MINOR = {9, 11, 0, 2, 4, 5, 8}
C_AEOLIAN = {0, 2, 3, 5, 7, 8, 10}


@pytest.mark.parametrize("root,scale,expected", [
    ("A", "phrygian", A_PHRYGIAN), ("A", "harmonic_minor", A_HARMONIC_MINOR),
    ("C", "aeolian", C_AEOLIAN)])
def test_every_pitch_is_a_scale_tone(root, scale, expected):
    r = render(root=root, scale=scale, density=1.0, length=8, seed=3, sections=one_section(8))
    for name, t in r["by_name"].items():
        assert t["notes"] and pcs(t["notes"]) <= expected, name


def test_pad_chords_literal_a_phrygian_degree_zero():
    r = render(progression=[0], density=0.0, sections=one_section(4, voices=["pad"]))
    assert sorted(n[2] for n in r["by_name"]["pad"]["notes"]) == [48, 52, 57]  # C3 E3 A3


def test_arp_patterns_literal():
    up = [57, 60, 64, 69, 72, 76]  # A C E in 57..80
    seqs = {"up": [up[i % 6] for i in range(16)],
            "down": [up[::-1][i % 6] for i in range(16)],
            "updown": [[57, 60, 64, 69, 72, 76, 72, 69, 64, 60][i % 10] for i in range(16)]}
    for pat, want in seqs.items():
        r = render(arp_pattern=pat, progression=[0], density=1.0, length=1,
                   sections=one_section(1, voices=["arp"]))
        assert [n[2] for n in r["by_name"]["arp"]["notes"]] == want, pat
    r = render(arp_pattern="random", progression=[0], density=1.0, length=2, seed=2,
               sections=one_section(2, voices=["arp"]))
    got = [n[2] for n in r["by_name"]["arp"]["notes"]]
    assert set(got) <= set(up) and len(set(got)) > 1


def test_progression_changes_arp_chord_per_bar():
    r = render(progression=[0, 3], density=1.0, length=2, sections=one_section(2, voices=["arp"]))
    notes = r["by_name"]["arp"]["notes"]
    bar0, bar1 = {n[2] % 12 for n in notes if n[0] < BAR}, {n[2] % 12 for n in notes if n[0] >= BAR}
    assert bar0 == {9, 0, 4}   # A phrygian degree 0: A C E
    assert bar1 == {2, 5, 9}   # degree 3 = offset 5 -> D; stacked thirds D F A


def test_register_shifts_every_note_by_octaves():
    base = render(seed=9, density=1.0, sections=one_section(4))
    up = render(seed=9, density=1.0, register=1, sections=one_section(4))
    down = render(seed=9, density=1.0, register=-2, sections=one_section(4))
    for v in gm.VOICES:
        b = [(n[0], n[2]) for n in base["by_name"][v]["notes"]]
        assert [(n[0], n[2]) for n in up["by_name"][v]["notes"]] == [(s, p + 12) for s, p in b]
        assert [(n[0], n[2]) for n in down["by_name"][v]["notes"]] == [(s, p - 24) for s, p in b]
    mixed = render(seed=9, density=1.0, register={"lead": 2}, sections=one_section(4))
    assert [n[2] for n in mixed["by_name"]["lead"]["notes"]] == \
        [n[2] + 24 for n in base["by_name"]["lead"]["notes"]]
    assert mixed["by_name"]["arp"]["notes"] == base["by_name"]["arp"]["notes"]


def test_windows_literal_at_register_zero():
    r = render(seed=4, density=1.0, length=8, sections=one_section(8))
    lo_hi = {"lead": (60, 83), "arp": (57, 80), "pad": (48, 59), "pluck": (36, 59)}
    for v, (lo, hi) in lo_hi.items():
        ps = [n[2] for n in r["by_name"][v]["notes"]]
        assert min(ps) >= lo and max(ps) <= hi, v


# ------------------------------------------------------------ rhythm, length, energy, sections

def test_lead_is_monophonic_on_16th_grid_and_durations_literal():
    r = render(seed=1, density=0.5, sections=one_section(4, voices=["lead"]))
    n = r["by_name"]["lead"]["notes"]
    assert all(s % 120 == 0 for s, _, _, _ in n)
    for (s0, e0, _, _), (s1, _, _, _) in zip(n, n[1:], strict=False):
        assert e0 <= s1
        assert e0 == min(s1, s0 + 2 * PPQ)  # legato to the next onset, capped at 2 beats


def test_pluck_and_arp_gate_is_0_2_beats():
    r = render(density=1.0, sections=one_section(1, voices=["arp", "pluck"]))
    for v in ("arp", "pluck"):
        assert {e - s for s, e, _, _ in r["by_name"][v]["notes"]} == {96}


def test_length_repeats_phrase_inside_section():
    r = render(seed=8, length=2, density=0.75, sections=one_section(6, voices=["lead", "arp"]))
    for v in ("lead", "arp"):
        n = r["by_name"][v]["notes"]
        first = [(s, p, vel) for s, e, p, vel in n if s < 2 * BAR]
        again = [(s - 2 * BAR, p, vel) for s, e, p, vel in n if 2 * BAR <= s < 4 * BAR]
        third = [(s - 4 * BAR, p, vel) for s, e, p, vel in n if s >= 4 * BAR]
        assert first and first == again == third


def test_different_length_gives_different_phrase():
    a = render(seed=8, length=2, sections=one_section(4, voices=["lead"]))
    b = render(seed=8, length=4, sections=one_section(4, voices=["lead"]))
    assert a["by_name"]["lead"]["notes"] != b["by_name"]["lead"]["notes"]


def test_section_energy_scales_density_and_velocity_literal():
    hi = render(density=1.0, sections=one_section(4, 1.0, ["lead"]))["by_name"]["lead"]["notes"]
    lo = render(density=1.0, sections=one_section(4, 0.0, ["lead"]))["by_name"]["lead"]["notes"]
    assert len(hi) == 32 and len(lo) == 16  # d_eff 1.0 vs 0.5 -> 8 vs 4 notes per bar
    assert max(n[3] for n in hi) == 114 and min(n[3] for n in hi) == 100  # 100 (+14 on beats)
    assert max(n[3] for n in lo) == 80 and {n[3] for n in lo} <= {70, 80}  # x0.70, rounded


def test_sections_place_voices_only_where_listed_with_markers():
    secs = [{"name": "A", "bars": 2, "energy": 0.5, "voices": ["pad"]},
            {"name": "B", "bars": 3, "energy": 1.0, "voices": ["lead", "pad"]}]
    r = render(density=1.0, sections=secs)
    assert [m[2] for m in r["tracks"][0]["meta"] if m[1] == 0x06] == [b"A", b"B"]
    assert [m[0] for m in r["tracks"][0]["meta"] if m[1] == 0x06] == [0, 2 * BAR]
    assert all(n[0] >= 2 * BAR for n in r["by_name"]["lead"]["notes"])
    assert r["by_name"]["lead"]["notes"]
    assert min(n[0] for n in r["by_name"]["pad"]["notes"]) == 0
    assert r["by_name"]["arp"]["notes"] == [] and r["by_name"]["pluck"]["notes"] == []
    assert max(n[1] for n in r["by_name"]["pad"]["notes"]) <= 5 * BAR


def test_seed_changes_lead_and_pluck_positions_or_pitches():
    a = render(seed=1, sections=one_section(4))
    b = render(seed=2, sections=one_section(4))
    assert a["by_name"]["lead"]["notes"] != b["by_name"]["lead"]["notes"]
    assert a["by_name"]["pluck"]["notes"] != b["by_name"]["pluck"]["notes"]


def test_bpm_changes_tempo_event():
    for bpm, us in ((135, 444444), (150, 400000)):
        meta = render(bpm=bpm, sections=one_section(1))["tracks"][0]["meta"]
        assert (0, 0x51, us.to_bytes(3, "big")) in meta


# ------------------------------------------------------------ validation

@pytest.mark.parametrize("bad", [
    {"seed": -1}, {"seed": True}, {"bpm": 134.9}, {"bpm": 150.1}, {"root": "H"}, {"root": "A##"},
    {"scale": "dorian"}, {"length": 0}, {"length": 17}, {"density": 1.1}, {"density": -0.1},
    {"density": {"bass": 0.5}}, {"register": 3}, {"register": 0.5}, {"register": {"lead": -3}},
    {"arp_pattern": "zig"}, {"progression": []}, {"progression": [7]}, {"voices": []},
    {"voices": ["lead", "lead"]}, {"voices": ["bass"]}, {"sections": []},
    {"sections": [{"name": "x", "bars": 1, "energy": 2, "voices": ["pad"]}]},
    {"sections": [{"name": "x", "bars": 0, "energy": 1, "voices": ["pad"]}]},
    {"sections": [{"name": "x", "bars": 1, "energy": 1, "voices": ["kick"]}]},
    {"sections": [{"name": "x", "bars": 1, "energy": 1}]}, {"nonsense": 1}])
def test_invalid_options_raise_value_error(bad):
    with pytest.raises(ValueError):
        gm.build_midi(**bad)


# ------------------------------------------------------------ seeded property test

def _random_options(rng: random.Random) -> dict:
    voices = rng.sample(gm.VOICES, rng.randint(1, 4))
    return {
        "seed": rng.randint(0, 10_000), "bpm": rng.uniform(135, 150),
        "root": rng.choice(["A", "C", "C#", "Eb", "F#", "G", "B"]),
        "scale": rng.choice(sorted(gm.SCALES)), "length": rng.randint(1, 8),
        "density": {v: rng.random() for v in gm.VOICES},
        "register": {v: rng.randint(-2, 2) for v in gm.VOICES},
        "arp_pattern": rng.choice(gm.ARP_PATTERNS),
        "progression": [rng.randint(0, 6) for _ in range(rng.randint(1, 6))],
        "voices": voices,
        "sections": [{"name": f"S{i}", "bars": rng.randint(1, 9), "energy": rng.random(),
                      "voices": rng.sample(gm.VOICES, rng.randint(0, 4))}
                     for i in range(rng.randint(1, 4))]}


def test_property_random_options():
    rng = random.Random(393)
    scales = {"phrygian": (0, 1, 3, 5, 7, 8, 10), "phrygian_dominant": (0, 1, 4, 5, 7, 8, 10),
              "harmonic_minor": (0, 2, 3, 5, 7, 8, 11), "aeolian": (0, 2, 3, 5, 7, 8, 10)}
    base_pc = {"A": 9, "C": 0, "C#": 1, "Eb": 3, "F#": 6, "G": 7, "B": 11}
    for _ in range(60):
        o = _random_options(rng)
        data = gm.build_midi(**o)
        assert data == gm.build_midi(**o)
        r = read_smf(data)
        total = sum(s["bars"] for s in o["sections"]) * BAR
        allowed = {(base_pc[o["root"]] + x) % 12 for x in scales[o["scale"]]}
        assert sorted(r["by_name"]) == sorted(o["voices"])
        # section time ranges per voice
        pos, active = 0, []
        for s in o["sections"]:
            active.append((pos, pos + s["bars"] * BAR, set(s["voices"])))
            pos += s["bars"] * BAR
        for v, t in r["by_name"].items():
            assert t["end"] == total
            for s, e, p, vel in t["notes"]:
                assert 0 <= p <= 127 and 1 <= vel <= 127 and s < e <= total
                assert p % 12 in allowed
                assert any(a <= s < b and v in vs and e <= b for a, b, vs in active)
        # per-bar lead count in every complete phrase bar of every section
        if "lead" in r["by_name"]:
            for (a, _b, vs), s in zip(active, o["sections"], strict=True):
                if "lead" not in vs:
                    continue
                d = o["density"]["lead"] * (0.5 + 0.5 * s["energy"])
                want = int(d * 8 + 0.5)
                for bar in range(min(s["bars"], o["length"])):
                    got = [n for n in r["by_name"]["lead"]["notes"]
                           if a + bar * BAR <= n[0] < a + (bar + 1) * BAR]
                    assert len(got) == want


# ------------------------------------------------------------ files and CLI

def test_write_refuses_overwrite_and_writes_nothing(tmp_path: Path):
    out = tmp_path / "o"
    mid, readme = gm.write_melody(out, seed=2)
    assert mid.name == "goa_melody_seed2_145bpm.mid" and readme.name == "README.md"
    before = mid.read_bytes()
    with pytest.raises(FileExistsError):
        gm.write_melody(out, seed=2)
    assert mid.read_bytes() == before
    # a README already present blocks everything, nothing new is created
    out2 = tmp_path / "o2"
    out2.mkdir()
    (out2 / "README.md").write_text("mine")
    with pytest.raises(FileExistsError):
        gm.write_melody(out2, seed=2)
    assert sorted(p.name for p in out2.iterdir()) == ["README.md"]
    assert (out2 / "README.md").read_text() == "mine"


def test_invalid_options_create_no_folder(tmp_path: Path):
    out = tmp_path / "never"
    with pytest.raises(ValueError):
        gm.write_melody(out, bpm=100)
    assert not out.exists()


def test_cli_end_to_end_and_readme_lists_options(tmp_path: Path, capsys):
    out = tmp_path / "c"
    argv = ["--out", str(out), "--seed", "7", "--bpm", "140", "--root", "D", "--scale",
            "aeolian", "--length", "2", "--density", "lead=1,arp=0.5", "--register", "pad=-1",
            "--arp-pattern", "updown", "--progression", "0,3", "--voices", "lead,arp,pad",
            "--sections", "Go:4:0.8:lead+arp+pad"]
    assert gm.main(argv) == 0
    assert "wrote" in capsys.readouterr().out
    mid = out / "goa_melody_seed7_140bpm.mid"
    r = read_smf(mid.read_bytes())
    assert list(r["by_name"]) == ["lead", "arp", "pad"]
    d_eff = 0.5 + 0.5 * 0.8
    assert len(r["by_name"]["lead"]["notes"]) == 4 * int(1.0 * d_eff * 8 + 0.5)
    text = (out / "README.md").read_text()
    for needle in ("seed: 7", "bpm: 140", "root: D", "scale: aeolian",
                   "length (bars per phrase): 2", "arp pattern: updown", "0, 3",
                   "| pad | 0 | -1 | 36-47 |", "Go",
                   "--density", "--register", "--sections", "Not tested in Live"):
        assert needle in text, needle
    # same options into another folder: identical bytes; same folder again: refused
    out_b = tmp_path / "d"
    assert gm.main([a if a != str(out) else str(out_b) for a in argv]) == 0
    assert (out_b / mid.name).read_bytes() == mid.read_bytes()
    assert gm.main(argv) == 2
    assert "already exists" in capsys.readouterr().err


@pytest.mark.parametrize("extra", [["--density", "2"], ["--register", "9"], ["--bpm", "90"],
                                   ["--sections", "x:1:0.5"], ["--voices", "bass"],
                                   ["--root", "Q"], ["--length", "abc"]])
def test_cli_bad_options_exit_2_without_output(tmp_path: Path, extra):
    out = tmp_path / "x"
    try:
        rc = gm.main(["--out", str(out), *extra])
    except SystemExit as e:  # argparse type errors
        rc = e.code
    assert rc == 2
    assert not out.exists()
