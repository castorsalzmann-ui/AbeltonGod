"""Tests for the goa_arrangement -> format-1 SMF exporter.

Expected values are hand-written (BAR = 1920 ticks at PPQ 480). The file is parsed by a
reader defined in this test file, not by the module. The property test builds a
reference by a different method: it renders every element onto a tick grid (per-tick
"which note is sounding") and compares that with the notes parsed from the file.
Nothing here touches Ableton.
"""

import copy
import random

import pytest

from audio_engine import arrangement_midi as am

BAR = 1920


# ---------------------------------------------------------------- independent reader

def read_smf(data):
    """-> (format, ppq, [track]) ; track = {'name','meta':[(tick,type,payload)],
    'notes':[(start,end,pitch,vel)], 'end':tick}. Strict about chunk sizes."""
    assert data[:4] == b"MThd" and int.from_bytes(data[4:8], "big") == 6
    fmt = int.from_bytes(data[8:10], "big")
    ntrk = int.from_bytes(data[10:12], "big")
    ppq = int.from_bytes(data[12:14], "big")
    pos = 14
    tracks = []
    for _ in range(ntrk):
        assert data[pos : pos + 4] == b"MTrk"
        size = int.from_bytes(data[pos + 4 : pos + 8], "big")
        body = data[pos + 8 : pos + 8 + size]
        assert len(body) == size
        pos += 8 + size
        t, i, meta, open_, notes, end, name = 0, 0, [], {}, [], None, None
        while i < len(body):
            d = 0
            while True:
                b = body[i]
                i += 1
                d = (d << 7) | (b & 0x7F)
                if not b & 0x80:
                    break
            t += d
            st = body[i]
            if st == 0xFF:
                typ = body[i + 1]
                ln = 0
                j = i + 2
                while True:
                    b = body[j]
                    j += 1
                    ln = (ln << 7) | (b & 0x7F)
                    if not b & 0x80:
                        break
                payload = bytes(body[j : j + ln])
                i = j + ln
                if typ == 0x2F:
                    end = t
                    assert i == len(body), "bytes after end-of-track"
                else:
                    meta.append((t, typ, payload))
                    if typ == 3:
                        name = payload.decode("ascii")
            elif st == 0x90:
                assert body[i + 2] > 0
                assert (body[i + 1]) not in open_, "note on while same pitch is open"
                open_[body[i + 1]] = (t, body[i + 2])
                i += 3
            elif st == 0x80:
                s, v = open_.pop(body[i + 1])
                notes.append((s, t, body[i + 1], v))
                i += 3
            else:
                raise AssertionError(f"unexpected status {st:#x}")
        assert not open_ and end is not None
        tracks.append({"name": name, "meta": meta, "notes": sorted(notes), "end": end})
    assert pos == len(data), "bytes after last track"
    return fmt, ppq, tracks


# ---------------------------------------------------------------- builders

def hits(pitch, starts, dur=0.25, vel=100, length=4):
    return {"length_beats": length, "notes": [
        {"pitch": pitch, "start": s, "duration": dur, "velocity": vel} for s in starts]}


def arr(elements, sections, tempo=145, **kw):
    d = {"format": "goa_arrangement", "version": "0.1-proposal", "tempo": tempo,
         "key": {"root": "A", "scale": "phrygian"},
         "elements": [{"name": n, "pattern": p} for n, p in elements],
         "sections": sections}
    d.update(kw)
    return d


def sec(name, bars, energy, els, **kw):
    d = {"name": name, "bars": bars, "energy": energy, "elements": els}
    d.update(kw)
    return d


# ---------------------------------------------------------------- curated cases

def test_curated_layout_and_positions():
    a = arr([("kick", hits(36, [0, 2], vel=100)), ("bass", hits(33, [1], dur=1, vel=80))],
            [sec("Intro", 2, 0.0, ["kick"]), sec("Peak", 1, 1.0, ["kick", "bass"]),
             sec("Gap", 1, 0.5, [])])
    fmt, ppq, tr = read_smf(am.arrangement_to_midi(a))
    assert (fmt, ppq, len(tr)) == (1, 480, 3)
    cond, kick, bass = tr
    assert [t["name"] for t in tr[1:]] == ["kick", "bass"]
    # conductor: tempo 145 -> 413793 us, 4/4, markers at bar starts, length 4 bars
    meta = {(t, typ): p for t, typ, p in cond["meta"] if typ != 6}
    assert meta[(0, 0x51)] == (413793).to_bytes(3, "big")
    assert meta[(0, 0x58)] == bytes([4, 2, 24, 8])
    assert meta[(0, 0x01)] == b"key: A phrygian"
    assert [(t, p) for t, typ, p in cond["meta"] if typ == 6] == [
        (0, b"Intro"), (2 * BAR, b"Peak"), (3 * BAR, b"Gap")]
    assert all(t["end"] == 4 * BAR for t in tr)
    # energy 0.0 -> 100 * 0.70 = 70 ; energy 1.0 -> 100 ; kick eighth-note-free: beats 0 and 2
    exp = []
    for bar in range(2):
        for beat in (0, 2):
            exp.append((bar * BAR + beat * 480, bar * BAR + beat * 480 + 120, 36, 70))
    for beat in (0, 2):
        exp.append((2 * BAR + beat * 480, 2 * BAR + beat * 480 + 120, 36, 100))
    assert kick["notes"] == sorted(exp)
    # bass only in Peak (bar 3 of 4 -> starts at 2*BAR), beat 1, 1 beat long, vel 80
    assert bass["notes"] == [(2 * BAR + 480, 2 * BAR + 960, 33, 80)]


def test_energy_scaling_values():
    a = arr([("k", hits(36, [0], vel=100))],
            [sec("a", 1, 0.5, ["k"]), sec("b", 1, 1.0, ["k"])])
    notes = read_smf(am.arrangement_to_midi(a))[2][1]["notes"]
    assert [n[3] for n in notes] == [85, 100]


def test_pattern_cut_at_section_end_and_override():
    # 3-beat pattern in a 1-bar section: repeat at beat 3 is cut after 1 beat
    p3 = {"length_beats": 3,
          "notes": [{"pitch": 40, "start": 0, "duration": 3, "velocity": 127}]}
    over = {"x": hits(41, [0], dur=0.5, vel=60)}
    a = arr([("x", p3)], [sec("s", 1, 1.0, ["x"]), sec("t", 1, 1.0, ["x"], patterns=over)])
    n = read_smf(am.arrangement_to_midi(a))[2][1]["notes"]
    # explicit expectation (4-beat override pattern, one hit per bar)
    assert n[0:2] == [(0, 1440, 40, 127), (1440, 1920, 40, 127)]
    assert n[2:] == [(BAR, BAR + 240, 41, 60)]


def test_acid_line_pattern_and_goa_line_alias():
    steps = [{"on": True, "note": 45, "accent": True}, {"on": False}] + [{"on": False}] * 14
    line = {"format": "acid_line", "version": "0.1-proposal", "length": 16, "steps": steps}
    goa = dict(line, format="goa_line", version="0.1-proposal")
    for ln in (line, goa):
        a = arr([("b", ln)], [sec("s", 2, 1.0, ["b"])])
        n = read_smf(am.arrangement_to_midi(a))[2][1]["notes"]
        # 16 steps = 1 bar, gate 0.125 beat = 60 ticks, accent velocity 127
        assert n == [(0, 60, 45, 127), (BAR, BAR + 60, 45, 127)]


def test_byte_identical_and_input_not_modified():
    a = am.demo_arrangement()
    before = copy.deepcopy(a)
    assert am.arrangement_to_midi(a) == am.arrangement_to_midi(copy.deepcopy(a))
    assert a == before


def test_demo_roundtrip_and_cli(tmp_path):
    out = tmp_path / "demo.mid"
    assert am.main([str(out)]) == 0
    fmt, ppq, tr = read_smf(out.read_bytes())
    assert fmt == 1 and [t["name"] for t in tr] == ["Goa demo", "kick", "hat", "bass", "lead"]
    assert all(t["end"] == 32 * BAR for t in tr)
    assert [p for t, typ, p in tr[0]["meta"] if typ == 6] == [
        b"Intro", b"Groove", b"Break", b"Peak", b"Outro"]
    assert list(tmp_path.iterdir()) == [out]


def test_element_never_active_still_gets_a_track():
    a = arr([("k", hits(36, [0])), ("idle", hits(40, [0]))], [sec("s", 1, 1.0, ["k"])])
    tr = read_smf(am.arrangement_to_midi(a))[2]
    assert tr[2]["name"] == "idle" and tr[2]["notes"] == []


# ---------------------------------------------------------------- error paths

def bad_cases():
    ok = arr([("k", hits(36, [0]))], [sec("s", 1, 0.5, ["k"])])

    def mod(f):
        d = copy.deepcopy(ok)
        f(d)
        return d

    return {
        "tempo low": mod(lambda d: d.update(tempo=134.9)),
        "tempo high": mod(lambda d: d.update(tempo=150.1)),
        "tempo nan": mod(lambda d: d.update(tempo=float("nan"))),
        "tempo bool": mod(lambda d: d.update(tempo=True)),
        "version": mod(lambda d: d.update(version="9")),
        "root": mod(lambda d: d["key"].update(root="H")),
        "energy high": mod(lambda d: d["sections"][0].update(energy=1.01)),
        "energy neg": mod(lambda d: d["sections"][0].update(energy=-0.01)),
        "bars zero": mod(lambda d: d["sections"][0].update(bars=0)),
        "bars float": mod(lambda d: d["sections"][0].update(bars=2.0)),
        "unknown element": mod(lambda d: d["sections"][0].update(elements=["zz"])),
        "dup in section": mod(lambda d: d["sections"][0].update(elements=["k", "k"])),
        "dup element": mod(lambda d: d["elements"].append(copy.deepcopy(d["elements"][0]))),
        "non-ascii name": mod(lambda d: d["sections"][0].update(name="Intrö")),
        "no sections": mod(lambda d: d.update(sections=[])),
        "too long": mod(lambda d: d["sections"][0].update(bars=512)
                        or d["sections"].extend(
                            [sec("a", 512, 0, []), sec("b", 1, 0, [])])),
        "pitch 128": mod(lambda d: d["elements"][0]["pattern"]["notes"][0].update(pitch=128)),
        "velocity 0": mod(lambda d: d["elements"][0]["pattern"]["notes"][0].update(velocity=0)),
        "note past end": mod(lambda d: d["elements"][0]["pattern"]["notes"][0].update(start=3.9)),
        "one tick past end": mod(lambda d: d["elements"][0]["pattern"].update(
            length_beats=1, notes=[{"pitch": 36, "start": 0, "duration": 1 + 1 / 480,
                                    "velocity": 9}])),
        "same pitch overlap": mod(lambda d: d["elements"][0]["pattern"]["notes"].append(
            {"pitch": 36, "start": 0.1, "duration": 0.25, "velocity": 90})),
        "override inactive": mod(lambda d: d["sections"][0].update(patterns={"x": hits(1, [0])})),
        "bad line": mod(lambda d: d["elements"][0].update(
            pattern={"format": "goa_line", "length": 2, "steps": []})),
        "unknown pattern format": mod(lambda d: d["elements"][0].update(
            pattern={"format": "zzz_line"})),
        "not an object": [],
    }


@pytest.mark.parametrize("name", list(bad_cases()))
def test_invalid_input_is_refused_and_writes_nothing(name, tmp_path):
    case = bad_cases()[name]
    with pytest.raises(am.ArrangementError):
        am.arrangement_to_midi(case)
    out = tmp_path / "x.mid"
    with pytest.raises(am.ArrangementError):
        am.write_arrangement_midi(case, out)
    assert list(tmp_path.iterdir()) == []


def test_write_failure_leaves_no_temp_file(tmp_path, monkeypatch):
    def boom(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(am.os, "replace", boom)
    with pytest.raises(OSError):
        am.write_arrangement_midi(am.demo_arrangement(), tmp_path / "x.mid")
    assert list(tmp_path.iterdir()) == []


def test_cli_error_exit_code(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    assert am.main([str(tmp_path / "o.mid"), "--input", str(bad)]) == 2
    assert not (tmp_path / "o.mid").exists()


# ---------------------------------------------------------------- property test

def random_arrangement(rng):
    names = ["kick", "hat", "bass", "lead", "arp", "pad", "fx"]
    els = []
    for n in rng.sample(names, rng.randint(1, len(names))):
        length = rng.choice([1, 2, 3, 4, 6, 8, 5.5])
        notes, used = [], {}
        for _ in range(rng.randint(0, 8)):
            p = rng.randint(0, 127)
            s = round(rng.uniform(0, length - 0.1) * 8) / 8
            d = round(rng.uniform(0.05, length - s) * 8) / 8
            if d <= 0 or s + d > length or s < used.get(p, 0):
                continue
            used[p] = s + d
            notes.append({"pitch": p, "start": s, "duration": d, "velocity": rng.randint(1, 127)})
        els.append((n, {"length_beats": length, "notes": notes}))
    secs = []
    for i in range(rng.randint(1, 8)):
        act = [n for n, _ in els if rng.random() < 0.6]
        secs.append(sec(f"S{i}", rng.randint(1, 12), rng.choice([0, 1, rng.random()]), act))
    return arr(els, secs, tempo=rng.uniform(135, 150))


def reference_tracks(a):
    """Per-tick reference: for each element, dict tick -> {pitch: velocity} of sounding
    notes, built by walking every tick of every section (slow, different method)."""
    ref = {e["name"]: {} for e in a["elements"]}
    pats = {e["name"]: e["pattern"] for e in a["elements"]}
    t0 = 0
    for s in a["sections"]:
        scale = 0.7 + 0.3 * s["energy"]
        for name in s["elements"]:
            p = pats[name]
            plen = int(p["length_beats"] * 480 + 0.5)
            for tick in range(s["bars"] * BAR):
                local = tick % plen
                for n in p["notes"]:
                    st = int(n["start"] * 480 + 0.5)
                    en = st + int(n["duration"] * 480 + 0.5)
                    if st <= local < en:
                        v = max(1, min(127, int(n["velocity"] * scale + 0.5)))
                        ref[name].setdefault(t0 + tick, {})[n["pitch"]] = v
        t0 += s["bars"] * BAR
    return ref


@pytest.mark.parametrize("seed", range(12))
def test_property_matches_per_tick_reference(seed):
    rng = random.Random(seed)
    a = random_arrangement(rng)
    data = am.arrangement_to_midi(a)
    assert data == am.arrangement_to_midi(copy.deepcopy(a))
    fmt, ppq, tr = read_smf(data)
    total = sum(s["bars"] for s in a["sections"]) * BAR
    assert fmt == 1 and ppq == 480 and len(tr) == 1 + len(a["elements"])
    assert all(t["end"] == total for t in tr)
    tempo = [p for t, typ, p in tr[0]["meta"] if typ == 0x51][0]
    assert abs(60_000_000 / int.from_bytes(tempo, "big") - a["tempo"]) < 0.01
    marks, pos = [], 0
    for s in a["sections"]:
        marks.append((pos, s["name"].encode()))
        pos += s["bars"] * BAR
    assert [(t, p) for t, typ, p in tr[0]["meta"] if typ == 6] == marks
    ref = reference_tracks(a)
    for el, track in zip(a["elements"], tr[1:], strict=True):
        assert track["name"] == el["name"]
        got = {}
        for s, e, p, v in track["notes"]:
            assert 0 <= s < e <= total and 1 <= v <= 127
            for tick in range(s, e):
                assert p not in got.get(tick, {}), "overlap"
                got.setdefault(tick, {})[p] = v
        # same-pitch back-to-back notes from different repeats are indistinguishable
        # per tick, which is what the reference also yields
        assert got == ref[el["name"]], f"seed {seed} element {el['name']}"


def test_tempo_range_ends():
    for bpm in (135, 150, 142.5):
        a = arr([("k", hits(36, [0]))], [sec("s", 1, 1, ["k"])], tempo=bpm)
        t = [p for _, typ, p in read_smf(am.arrangement_to_midi(a))[2][0]["meta"] if typ == 0x51][0]
        assert int.from_bytes(t, "big") == round(60_000_000 / bpm)
