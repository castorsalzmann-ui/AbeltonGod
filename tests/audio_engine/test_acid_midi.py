"""Tests for the acid line -> SMF writer. Expected values are written by hand (ticks at
PPQ 480: step 120, gate 60, overlap 15); the bytes are parsed by a second, tiny SMF
reader defined here, not by the module under test."""

import copy
import json
import random

import pytest

from audio_engine import acid_midi as am

STEP, GATE, OVL = 120, 60, 15


def line(steps, **kw):
    steps = copy.deepcopy(steps)  # tests mutate lines; never share the REST dict
    d = {"format": "acid_line", "version": "0.1-proposal", "length": len(steps), "steps": steps}
    d.update(kw)
    return d


def on(note, accent=False, slide=False):
    return {"on": True, "note": note, "accent": accent, "slide": slide}


REST = {"on": False}


def read_smf(data):
    """Independent minimal SMF reader -> (ppq, [(abs_tick, kind, a, b)], end_tick)."""
    assert data[:4] == b"MThd" and int.from_bytes(data[4:8], "big") == 6
    fmt, ntrk, ppq = (int.from_bytes(data[8 + 2 * i : 10 + 2 * i], "big") for i in range(3))
    assert (fmt, ntrk) == (0, 1)
    assert data[14:18] == b"MTrk"
    size = int.from_bytes(data[18:22], "big")
    body = data[22:]
    assert len(body) == size  # no trailing bytes
    pos, t, evs, end = 0, 0, [], None
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
            payload = body[pos + 3 : pos + 3 + ln]
            pos += 3 + ln
            if typ == 0x2F:
                end = t
                assert pos == len(body)
            else:
                evs.append((t, "meta", typ, bytes(payload)))
        else:
            assert st in (0x90, 0x80)
            evs.append((t, "on" if st == 0x90 else "off", body[pos + 1], body[pos + 2]))
            pos += 3
    assert end is not None
    return ppq, evs, end


def notes_from(data):
    """Pair on/off events into (start, end, pitch, velocity)."""
    _, evs, _ = read_smf(data)
    open_, out = {}, []
    for t, kind, a, b in evs:
        if kind == "on":
            assert a not in open_, "same-pitch overlap"
            open_[a] = (t, b)
        elif kind == "off":
            s, v = open_.pop(a)
            out.append((s, t, a, v))
    assert not open_
    return sorted(out)


def test_golden_bytes_single_note():
    data = am.acid_line_to_midi(line([on(45, accent=True), REST, REST, REST]))
    expected = (
        b"MThd\x00\x00\x00\x06\x00\x00\x00\x01\x01\xe0"
        b"MTrk\x00\x00\x00\x15"
        b"\x00\xff\x58\x04\x04\x02\x18\x08"
        b"\x00\x90\x2d\x7f"
        b"\x3c\x80\x2d\x00"  # note-off after 60 ticks
        b"\x83\x24\xff\x2f\x00"  # end at 480 = 60 + 420; 420 = 3*128 + 36
    )
    assert data == expected


def test_basic_gate_velocity_and_rests():
    data = am.acid_line_to_midi(line([on(40), REST, on(43, accent=True), on(40)]))
    assert notes_from(data) == [
        (0, GATE, 40, 100),
        (2 * STEP, 2 * STEP + GATE, 43, 127),
        (3 * STEP, 3 * STEP + GATE, 40, 100),
    ]
    ppq, _, end = read_smf(data)
    assert ppq == 480 and end == 4 * STEP


def test_slide_different_pitch_overlaps_next():
    data = am.acid_line_to_midi(line([on(48, slide=True), on(50), REST, REST]))
    assert notes_from(data) == [(0, STEP + OVL, 48, 100), (STEP, STEP + GATE, 50, 100)]


def test_slide_before_rest_and_on_last_step_has_no_effect():
    data = am.acid_line_to_midi(line([on(48, slide=True), REST, REST, on(50, slide=True)]))
    assert notes_from(data) == [(0, GATE, 48, 100), (3 * STEP, 3 * STEP + GATE, 50, 100)]


def test_slide_does_not_wrap_around():
    data = am.acid_line_to_midi(line([on(48), REST, on(50, slide=True)]))
    assert notes_from(data)[-1] == (2 * STEP, 2 * STEP + GATE, 50, 100)


def test_same_pitch_slide_is_tie():
    data = am.acid_line_to_midi(line([on(45, slide=True), on(45), REST, REST]))
    assert notes_from(data) == [(0, STEP + GATE, 45, 100)]


@pytest.mark.parametrize("a1,a2", [(False, False), (True, False), (False, True), (True, True)])
def test_tie_accent_if_either(a1, a2):
    data = am.acid_line_to_midi(line([on(45, a1, True), on(45, a2), REST, REST]))
    assert notes_from(data) == [(0, STEP + GATE, 45, 127 if (a1 or a2) else 100)]


def test_tie_chain_then_slide_to_other_pitch():
    steps = [on(45, slide=True), on(45, slide=True), on(45, accent=True, slide=True), on(47), REST]
    data = am.acid_line_to_midi(line(steps))
    assert notes_from(data) == [(0, 3 * STEP + OVL, 45, 127), (3 * STEP, 3 * STEP + GATE, 47, 100)]


def test_tied_second_note_slides_on_to_other_pitch():
    data = am.acid_line_to_midi(line([on(45, slide=True), on(45, slide=True), on(52), REST]))
    assert notes_from(data) == [(0, 2 * STEP + OVL, 45, 100), (2 * STEP, 2 * STEP + GATE, 52, 100)]


def test_tie_at_end_stays_inside_clip():
    data = am.acid_line_to_midi(line([REST, REST, on(45, slide=True), on(45)]))
    assert notes_from(data) == [(2 * STEP, 3 * STEP + GATE, 45, 100)]
    assert read_smf(data)[2] == 4 * STEP


def test_odd_length_and_clip_end():
    data = am.acid_line_to_midi(line([on(40), REST, on(41, slide=True), on(42), REST]))
    assert read_smf(data)[2] == 5 * STEP
    assert len(notes_from(data)) == 3


def test_render_overrides():
    render = {"velocity": 80, "accent_velocity": 120, "gate": 0.0625, "slide_overlap": 0.0625}
    ln = line([on(40, slide=True), on(42, accent=True)], render=render)
    assert notes_from(am.acid_line_to_midi(ln)) == [
        (0, STEP + 30, 40, 80), (STEP, STEP + 30, 42, 120)]


def test_tempo_and_name_events():
    data = am.acid_line_to_midi(line([on(40)]), bpm=132, name="Acid A")
    _, evs, _ = read_smf(data)
    metas = {e[2]: e[3] for e in evs if e[1] == "meta"}
    assert metas[0x51] == round(60_000_000 / 132).to_bytes(3, "big")
    assert metas[0x03] == b"Acid A"
    plain = read_smf(am.acid_line_to_midi(line([on(40)])))[1]
    assert 0x51 not in {e[2] for e in plain if e[1] == "meta"}


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(format="x"),
    lambda d: d.update(version="1.0"),
    lambda d: d.update(length=2),
    lambda d: d.update(length=0, steps=[]),
    lambda d: d.update(length=33, steps=[{"on": False}] * 33),
    lambda d: d["steps"][0].update(note=127),
    lambda d: d["steps"][0].update(note=-1),
    lambda d: d["steps"][0].update(note=True),
    lambda d: d["steps"][0].update(slide=1),
    lambda d: d["steps"][0].pop("note"),
    lambda d: d["steps"][1].update(on=1),
    lambda d: d.update(seed="a"),
    lambda d: d.update(render={"velocity": 0}),
    lambda d: d.update(render={"gate": 0.25}),
    lambda d: d.update(render={"slide_overlap": -0.1}),
    lambda d: d.update(render={"bogus": 1}),
])
def test_invalid_lines_rejected(mutate, tmp_path):
    d = line([on(40), REST, on(42)])
    mutate(d)
    with pytest.raises(ValueError):
        am.acid_line_to_midi(d)
    out = tmp_path / "x.mid"
    with pytest.raises(ValueError):
        am.write_acid_midi(d, out)
    assert not out.exists()


def test_file_roundtrip_and_determinism(tmp_path):
    d = line([on(45, True, True), on(47), REST, on(45)], seed=7)
    p = tmp_path / "l.json"
    p.write_text(json.dumps(d))
    loaded = am.load_acid_line(p)
    assert am.write_acid_midi(loaded, tmp_path / "a.mid").read_bytes() == am.acid_line_to_midi(d)
    assert am.acid_line_to_midi(d) == am.acid_line_to_midi(copy.deepcopy(d))


def random_line(rng):
    n = rng.randint(1, 32)
    pitches = [rng.randint(0, 126) for _ in range(rng.randint(1, 3))]  # few pitches -> many ties
    steps = [
        REST if rng.random() < 0.3 else
        on(rng.choice(pitches), rng.random() < 0.3, rng.random() < 0.5)
        for _ in range(n)
    ]
    return line(steps, seed=rng.randint(0, 2**31))


def reference_events(ln):
    """Independent per-step reference: absolute (start, end, pitch, vel) written
    as a straight transcription of the rules, one step at a time."""
    st = ln["steps"]
    n = len(st)
    out = []
    merged_into_prev = [False] * n
    for i in range(n):
        if not st[i]["on"] or merged_into_prev[i]:
            continue
        j, acc = i, st[i]["accent"]
        while (j + 1 < n and st[j]["slide"] and st[j + 1]["on"]
               and st[j + 1]["note"] == st[i]["note"]):
            j += 1
            merged_into_prev[j] = True
            acc = acc or st[j]["accent"]
        nxt = st[j + 1] if j + 1 < n else None
        if st[j]["slide"] and nxt is not None and nxt["on"]:
            end = 120 * (j + 2) - 120 + 15
        else:
            end = 120 * j + 60
        out.append((120 * i, end, st[i]["note"], 127 if acc else 100))
    return sorted(out)


@pytest.mark.parametrize("seed", range(300))
def test_random_lines_match_reference_and_invariants(seed):
    rng = random.Random(seed)
    ln = random_line(rng)
    data = am.acid_line_to_midi(ln)
    got = notes_from(data)  # also asserts no same-pitch overlap and balanced on/off
    assert got == sorted(reference_events(ln))
    _, evs, end = read_smf(data)
    assert end == len(ln["steps"]) * STEP
    assert all(e[0] <= end for e in evs)
    assert all(0 <= p <= 126 and v in (100, 127) for _, _, p, v in got)
    assert [g[0] for g in got] == sorted(g[0] for g in got)
    assert all(e - s <= 2 * STEP + 32 * STEP and e > s for s, e, _, _ in got)
    # no overlap longer than 15 ticks between consecutive different notes
    for (_, e1, _, _), (s2, _, _, _) in zip(got, got[1:], strict=False):
        assert e1 - s2 <= OVL
    assert data == am.acid_line_to_midi(copy.deepcopy(ln))
