"""Tests for the Goa pattern generator. Expected values are written here (scale tables,
counts, tick positions); the MIDI bytes are read by a tiny SMF reader defined in this file."""

import random

import pytest

from audio_engine import acid_midi
from audio_engine import goa_patterns as gp

# Independent copy of the scale tables (semitones above the tonic).
SCALE_PCS = {
    "phrygian": {0, 1, 3, 5, 7, 8, 10},
    "phrygian_dominant": {0, 1, 4, 5, 7, 8, 10},
    "harmonic_minor": {0, 2, 3, 5, 7, 8, 11},
    "aeolian": {0, 2, 3, 5, 7, 8, 10},
}
GRID = {"bass": 12, "lead": 16, "arp": 16}


def read_midi(data):
    """-> (ppq, tempo_us or None, [(tick, 'on'/'off', pitch)], end_tick)."""
    assert data[:4] == b"MThd"
    ppq = int.from_bytes(data[12:14], "big")
    assert data[14:18] == b"MTrk"
    body = data[22:]
    assert len(body) == int.from_bytes(data[18:22], "big")
    pos = t = 0
    tempo, evs, end = None, [], None
    while pos < len(body):
        d = 0
        while True:
            b = body[pos]
            pos += 1
            d = (d << 7) | (b & 0x7F)
            if not b & 0x80:
                break
        t += d
        st = body[pos]
        if st == 0xFF:
            typ, ln = body[pos + 1], body[pos + 2]
            if typ == 0x51:
                tempo = int.from_bytes(body[pos + 3 : pos + 6], "big")
            if typ == 0x2F:
                end = t
            pos += 3 + ln
        else:
            evs.append((t, "on" if st == 0x90 else "off", body[pos + 1]))
            pos += 3
    return ppq, tempo, evs, end


def sounding(line):
    return [(i, s) for i, s in enumerate(line["steps"]) if s["on"]]


def random_params(rng, kind):
    p = {
        "root": rng.randint(12, 84),
        "scale": rng.choice(sorted(SCALE_PCS)),
        "bars": rng.randint(1, 16),
        "density": rng.random() if rng.random() < 0.8 else rng.choice([0.0, 1.0]),
        "accent": rng.random(),
        "slide": rng.random(),
        "seed": rng.randint(-(2**40), 2**40),
        "bpm": rng.uniform(135, 150),
    }
    if kind == "arp":
        p["pattern"] = rng.choice(gp.ARP_PATTERNS)
        p["octaves"] = rng.randint(1, 3)
        p["progression"] = [rng.randint(0, 6) for _ in range(rng.randint(1, 4))]
    return p


def draws(n=60):
    rng = random.Random(20261103)
    return [(k, random_params(rng, k)) for k in gp.KINDS for _ in range(n)]


@pytest.mark.parametrize("kind,params", draws())
def test_musical_constraints_over_range(kind, params):
    line = gp.generate(kind, **params)
    bars, root = params["bars"], params["root"]
    assert line["length"] == len(line["steps"]) == bars * 16
    assert line["format"] == "acid_line" and line["version"] == "0.1-proposal"
    notes = sounding(line)
    for _, s in notes:
        assert (s["note"] - root) % 12 in SCALE_PCS[params["scale"]]
        assert 0 <= s["note"] <= 126
        assert isinstance(s["accent"], bool) and isinstance(s["slide"], bool)
    # density: per-bar note count within half a note of density * grid size
    for b in range(bars):
        cnt = sum(1 for i, _ in notes if i // 16 == b)
        assert abs(cnt - params["density"] * GRID[kind]) <= 0.5 + 1e-9
    # accent: exact count within half a note
    n_acc = sum(s["accent"] for _, s in notes)
    assert abs(n_acc - params["accent"] * len(notes)) <= 0.5 + 1e-9
    # slides: never more than asked, only onto a different pitch on the next step
    n_sl = sum(s["slide"] for _, s in notes)
    assert n_sl <= params["slide"] * len(notes) + 0.5 + 1e-9
    for i, s in notes:
        if s["slide"]:
            nxt = line["steps"][i + 1]
            assert nxt["on"] and nxt["note"] != s["note"]
    # MIDI: bar-aligned end, tempo as requested, every note-on has an off
    ppq, tempo, evs, end = read_midi(gp.line_to_midi(line))
    assert ppq == 480 and end == bars * 4 * 480
    assert abs(60_000_000 / tempo - params["bpm"]) < 0.01
    assert sum(e[1] == "on" for e in evs) == sum(e[1] == "off" for e in evs) > 0 or not notes


@pytest.mark.parametrize("scale", sorted(SCALE_PCS))
def test_bass_rules(scale):
    for seed in range(20):
        line = gp.bass_line(33, scale, bars=8, density=0.75, seed=seed)
        for b in range(8):
            bar = [(i % 16, s["note"]) for i, s in sounding(line) if i // 16 == b]
            assert len(bar) == 9
            assert all(step % 4 != 0 for step, _ in bar)  # kick step stays free
            assert bar[0][1] == 33  # bar opens on the root
            assert {(n - 33) % 12 for _, n in bar} <= {0, 1 if "phr" in scale else 2, 4, 7}


def test_bass_full_roll_is_three_per_beat():
    line = gp.bass_line(33, bars=1, density=1.0, seed=3)
    assert [i for i, _ in sounding(line)] == [s for s in range(16) if s % 4]


def test_lead_range_and_opening_note():
    for seed in range(20):
        line = gp.lead_line(57, "harmonic_minor", bars=4, density=0.5, seed=seed)
        notes = sounding(line)
        assert notes[0][1]["note"] == 57
        assert all(57 <= s["note"] <= 57 + 12 + 3 for _, s in notes)  # degrees 0..9


def test_lead_motif_repeats_with_variation_bar():
    line = gp.lead_line(57, bars=4, density=0.5, seed=5)
    bar = lambda b: [(i % 16, s["note"]) for i, s in sounding(line) if i // 16 == b]  # noqa: E731
    assert bar(2) == bar(0)  # 2-bar motif repeated


def test_arp_up_pattern_exact():
    line = gp.arp_line(40, "aeolian", bars=1, density=1.0, octaves=1, pattern="up", seed=1)
    notes = [s["note"] for _, s in sounding(line)]
    # chord tones of A-aeolian-style stack on 40: 0,3,7,10 semitones -> repeating
    assert notes == [40, 43, 47, 50] * 4
    line = gp.arp_line(40, "aeolian", bars=1, density=1.0, octaves=1, pattern="down", seed=1)
    assert [s["note"] for _, s in sounding(line)] == [50, 47, 43, 40] * 4


def test_arp_progression_changes_chord():
    line = gp.arp_line(40, "aeolian", bars=2, octaves=1, progression=[0, 3], seed=1)
    second = [s["note"] for i, s in sounding(line) if i >= 16]
    assert second[0] == 40 + 5  # degree 3 of aeolian = +5 semitones


@pytest.mark.parametrize("kind", gp.KINDS)
def test_determinism(kind):
    p = {"root": 36, "scale": "phrygian_dominant", "bars": 8, "seed": 99, "bpm": 142}
    a, b = gp.generate(kind, **p), gp.generate(kind, **p)
    assert gp.to_json(a) == gp.to_json(b)
    assert gp.line_to_midi(a) == gp.line_to_midi(b)
    others = {gp.to_json(gp.generate(kind, **{**p, "seed": s})) for s in range(1, 6)}
    assert len(others | {gp.to_json(a)}) > 3  # seed matters


def test_rejections():
    ok = {"root": 36}
    for bpm in (134.9, 150.1, 0, float("nan"), "140", True):
        with pytest.raises(ValueError):
            gp.bass_line(**ok, bpm=bpm)
    for bpm in (135, 150, 145.5):
        gp.bass_line(**ok, bpm=bpm)
    bad = [{"root": 11}, {"root": 85}, {"root": 36.0}, {"root": 36, "scale": "dorian"},
           {"root": 36, "bars": 0}, {"root": 36, "bars": 17}, {"root": 36, "density": 1.1},
           {"root": 36, "accent": -0.1}, {"root": 36, "slide": 2}, {"root": 36, "seed": 1.5}]
    for kw in bad:
        with pytest.raises(ValueError):
            gp.bass_line(**kw)
    with pytest.raises(ValueError):
        gp.arp_line(36, pattern="random")
    with pytest.raises(ValueError):
        gp.arp_line(36, progression=[7])
    with pytest.raises(ValueError):
        gp.generate("pad", root=36)


def test_acid_midi_default_length_limit_unchanged():
    steps = [{"on": False}] * 33
    line = {"format": "acid_line", "version": "0.1-proposal", "length": 33, "steps": steps}
    with pytest.raises(ValueError):
        acid_midi.validate_line(line)
    acid_midi.validate_line(line, max_length=64)


def test_cli_writes_midi_and_matches_api(tmp_path, capsys):
    out, js = tmp_path / "f.mid", tmp_path / "f.json"
    argv = ["--kind", "bass", "--root", "33", "--scale", "phrygian", "--bars", "8",
            "--seed", "1", "--out", str(out), "--json", str(js)]
    assert gp.main(argv) == 0
    line = gp.bass_line(33, "phrygian", bars=8, seed=1)
    assert out.read_bytes() == gp.line_to_midi(line)
    assert js.read_text() == gp.to_json(line)
    assert gp.main([*argv[:-2], "--bpm", "120"]) == 2  # outside Goa range
    assert "error" in capsys.readouterr().err
