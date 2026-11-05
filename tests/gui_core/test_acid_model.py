"""Acid edit model: editing, JSON round trip, MIDI bytes, error paths (German messages)."""

from __future__ import annotations

import json
import os
import random

import pytest

from audio_engine.acid_midi import acid_line_to_midi
from gui_core.acid_generate import AcidOptionError, GenOptions, generate_line
from gui_core.acid_model import (
    AcidFileError,
    AcidModel,
    parse_bpm,
    parse_percent,
    parse_seed,
)


def test_initial_model_is_a_valid_generated_line():
    m = AcidModel()
    assert m.to_line() == generate_line(GenOptions())
    assert m.length == 16 and m.bpm == 130.0


def test_editing_steps():
    m = AcidModel()
    m.clear()
    assert [s["on"] for s in m.to_line()["steps"]] == [False] * 16
    assert m.toggle_on(3) is True
    assert m.toggle_accent(3) is True and m.toggle_slide(3) is True
    m.set_note(3, 52)
    step = m.to_line()["steps"][3]
    assert step == {"on": True, "note": 52, "accent": True, "slide": True,
                    "degree": 4, "octave": 0}
    assert m.toggle_on(3) is False
    assert m.to_line()["steps"][3] == {"on": False}


def test_length_limits_and_line_length():
    m = AcidModel()
    m.set_length(32)
    assert len(m.to_line()["steps"]) == 32
    m.set_length(1)
    assert m.to_line()["length"] == 1 and len(m.to_line()["steps"]) == 1
    for bad in (0, 33, -1, 4.5, True):
        with pytest.raises(AcidOptionError, match="Länge"):
            m.set_length(bad)
    assert m.length == 1


def test_bad_step_or_note_rejected_and_unchanged():
    m = AcidModel()
    before = m.to_line()
    for bad in (-1, 32, 100):
        with pytest.raises(AcidOptionError, match="gibt es nicht"):
            m.toggle_on(bad)
    for bad in (-1, 127, "60", 60.0):
        with pytest.raises(AcidOptionError, match="Note"):
            m.set_note(0, bad)
    assert m.to_line() == before


def test_set_scale_snaps_notes_to_new_scale():
    m = AcidModel()
    m.clear()
    m.toggle_on(0)
    m.set_note(0, 46)  # A#2: not in A minor
    assert m.to_line()["steps"][0].get("degree") is None
    m.set_scale("A", "minor")
    assert m.to_line()["steps"][0]["note"] == 45  # tie goes down
    m.set_note(0, 48)  # C3
    m.set_scale("C", "major")
    assert m.to_line()["steps"][0]["note"] == 48 and m.root == "C"
    m.set_note(0, 49)
    m.set_scale("A", "minor")
    assert m.to_line()["steps"][0]["note"] == 48
    with pytest.raises(AcidOptionError):
        m.set_scale("H", "minor")
    with pytest.raises(AcidOptionError):
        m.set_scale("A", "nope")
    assert (m.root, m.scale) == ("A", "minor")


def test_set_root_octave_moves_notes_and_checks_range():
    m = AcidModel()
    m.clear()
    m.toggle_on(0)
    m.set_note(0, 45)
    m.set_root_octave(3)
    assert m.to_line()["steps"][0]["note"] == 57 and m.to_line()["root_octave"] == 3
    m.set_root_octave(0)
    assert m.to_line()["steps"][0]["note"] == 21
    with pytest.raises(AcidOptionError):
        m.set_root_octave(7)
    m.set_note(1, 120)
    with pytest.raises(AcidOptionError, match="MIDI-Bereich"):
        m.set_root_octave(5)
    assert m.root_octave == 0 and m.to_line()["steps"][0]["note"] == 21


def test_generate_fills_grid_and_keeps_bpm():
    m = AcidModel()
    m.bpm = 150.0
    m.generate(GenOptions(root="D", scale="phrygian", length=24, seed=9, density=1.0))
    line = m.to_line()
    assert line == generate_line(GenOptions(root="D", scale="phrygian", length=24, seed=9,
                                            density=1.0))
    assert m.bpm == 150.0 and m.seed == 9 and m.length == 24


def test_json_round_trip_random_lines(tmp_path):
    rng = random.Random(99)
    for k in range(60):
        o = GenOptions(root=rng.choice(["A", "C#", "F", "B"]),
                       scale=rng.choice(["minor", "major", "phrygian dominant"]),
                       root_octave=rng.randint(0, 4), length=rng.randint(1, 32),
                       density=rng.random(), accent_chance=rng.random(),
                       slide_chance=rng.random(), octave_range=rng.randint(1, 3),
                       seed=rng.randint(0, 10**6))
        line = generate_line(o)
        src = tmp_path / f"in{k}.json"
        src.write_text(json.dumps(line), encoding="utf-8")
        m = AcidModel()
        m.load_file(src)
        assert m.to_line() == line
        out = m.save_file(tmp_path / f"out{k}.json")
        assert json.loads(out.read_text(encoding="utf-8")) == line
        m2 = AcidModel()
        m2.load_file(out)
        assert m2.to_line() == line


def test_load_keeps_render_block_and_unknown_root_falls_back():
    line = generate_line(GenOptions(seed=4))
    line["render"] = {"velocity": 90, "gate": 0.1}
    del line["root"]
    m = AcidModel()
    m.load_line(line)
    assert m.render == {"velocity": 90, "gate": 0.1}
    out = m.to_line()
    assert out["render"] == {"velocity": 90, "gate": 0.1} and out["root"] == "A"


def test_midi_bytes_equal_acid_midi_for_same_json(tmp_path):
    line = generate_line(GenOptions(seed=12, length=32, density=0.8, slide_chance=0.5))
    m = AcidModel()
    m.load_line(line)
    m.bpm = 142.5
    expected = acid_line_to_midi(line, bpm=142.5)
    assert m.midi_bytes() == expected
    p = m.export_midi(tmp_path / "sub" / "x.mid")
    assert p.read_bytes() == expected
    assert expected[:4] == b"MThd"
    # 120 BPM -> 500000 us per beat = 07 A1 20, written as a tempo meta event.
    m.bpm = 120.0
    assert b"\xff\x51\x03\x07\xa1\x20" in m.midi_bytes()


def test_export_failure_writes_nothing_and_says_so(tmp_path):
    m = AcidModel()
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.raises(AcidFileError, match="geschrieben"):
        m.export_midi(blocker / "a.mid")


@pytest.mark.parametrize("content,fragment", [
    ("not json", "JSON"),
    ("[]", "Acid-Linie"),
    (json.dumps({"format": "other", "version": "0.1-proposal", "length": 1, "steps": []}),
     "format"),
    (json.dumps({"format": "acid_line", "version": "9", "length": 1, "steps": [{"on": False}]}),
     "version"),
    (json.dumps({"format": "acid_line", "version": "0.1-proposal", "length": 2,
                 "steps": [{"on": False}]}), "steps"),
    (json.dumps({"format": "acid_line", "version": "0.1-proposal", "length": 1,
                 "steps": [{"on": True, "note": 200}]}), "note"),
])
def test_invalid_files_rejected_model_unchanged(tmp_path, content, fragment):
    p = tmp_path / "bad.json"
    p.write_text(content, encoding="utf-8")
    m = AcidModel()
    before = m.to_line()
    with pytest.raises(AcidFileError, match=fragment):
        m.load_file(p)
    assert m.to_line() == before


def test_missing_and_non_utf8_file(tmp_path):
    m = AcidModel()
    with pytest.raises(AcidFileError, match="gelesen"):
        m.load_file(tmp_path / "nope.json")
    p = tmp_path / "bin.json"
    p.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(AcidFileError, match="UTF-8"):
        m.load_file(p)


def test_save_is_atomic_when_replace_fails(tmp_path, monkeypatch):
    m = AcidModel()
    target = tmp_path / "line.json"
    target.write_text("OLD", encoding="utf-8")

    def boom(src, dst):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(AcidFileError, match="geschrieben"):
        m.save_file(target)
    assert target.read_text(encoding="utf-8") == "OLD"
    assert [p.name for p in tmp_path.iterdir()] == ["line.json"]  # temp file cleaned up


def test_parse_helpers():
    assert parse_bpm(" 128,5 ") == 128.5
    for bad in ("", "abc", "19", "401", "nan"):
        with pytest.raises(AcidOptionError, match="BPM"):
            parse_bpm(bad)
    assert parse_seed(" -3 ") == -3
    for bad in ("1.5", "x", ""):
        with pytest.raises(AcidOptionError, match="Seed"):
            parse_seed(bad)
    assert parse_percent("35 %", "Dichte") == pytest.approx(0.35)
    assert parse_percent("100", "Dichte") == 1.0
    for bad in ("101", "-1", "x", ""):
        with pytest.raises(AcidOptionError, match="Dichte"):
            parse_percent(bad, "Dichte")
