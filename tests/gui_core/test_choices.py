"""gui_core.choices (#110 step 2): entries, append, read, current verdict. No Qt.

Validity is checked with the contract file directly (jsonschema on
contracts/choice-log.schema.json), not with the module's own validator, and the expected
SHA-256 comes from a one-shot hashlib call, not the module's chunked hasher.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from gui_core import choices
from gui_core.choices import ChoiceError, ChoiceLog, current_verdicts, make_entry, parse_lines

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = Draft202012Validator(json.loads(
    (ROOT / "contracts" / "choice-log.schema.json").read_text(encoding="utf-8")))
FIX = ROOT / "tests" / "fixtures"
SIDECAR = FIX / "sidecars" / "kick-v01.json"
NOW = "2026-11-07T12:00:00Z"


def lines(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def out(tmp_path: Path) -> Path:
    """Output folder with one WAV + sidecar (kick-v01) and one WAV without a sidecar."""
    d = tmp_path / "out" / "Samples" / "Kicks"
    d.mkdir(parents=True)
    (d / "kick-v01.wav").write_bytes(b"RIFF" + bytes(range(256)) * 9)
    shutil.copy(SIDECAR, d / "kick-v01.json")
    (tmp_path / "out" / "loose.wav").write_bytes(b"RIFFloose")
    return tmp_path / "out"


def test_entry_from_a_sidecar_copies_parameters_verbatim(out):
    wav = out / "Samples" / "Kicks" / "kick-v01.wav"
    e = make_entry(wav, out, "favourite", "  zu dumpf  ", now=NOW)
    assert list(CONTRACT.iter_errors(e)) == []
    side = json.loads(SIDECAR.read_text(encoding="utf-8"))
    assert e["sample"] == {"path": "Samples/Kicks/kick-v01.wav",
                           "sha256": hashlib.sha256(wav.read_bytes()).hexdigest(),
                           "category": "kick"}
    assert e["sidecar"] == {"engine": {"name": "abeltongod-audio-engine", "version": "0.0.1"},
                            "preset": None, "seed": 5, "parameters": side["parameters"]}
    assert e["note"] == "zu dumpf" and e["source"] == "gui" and e["time"] == NOW


def test_entry_without_sidecar(out):
    e = make_entry(out / "loose.wav", out, "reject")
    assert list(CONTRACT.iter_errors(e)) == []
    assert e["sidecar"] is None and e["sample"]["category"] is None and "note" not in e
    assert e["time"].endswith("Z")


def test_entry_with_a_broken_sidecar_keeps_the_verdict(out):
    (out / "loose.json").write_text("{not json", encoding="utf-8")
    assert make_entry(out / "loose.wav", out, "neutral")["sidecar"] is None
    (out / "loose.json").write_text(json.dumps({"category": "clap", "engine": {"name": ""}}),
                                    encoding="utf-8")
    e = make_entry(out / "loose.wav", out, "neutral")
    assert e["sidecar"] is None and e["sample"]["category"] == "clap"


def test_entry_refusals(out, tmp_path):
    outside = tmp_path / "elsewhere.wav"
    outside.write_bytes(b"x")
    with pytest.raises(ChoiceError, match="nicht im Ausgabeordner"):
        make_entry(outside, out, "favourite")
    with pytest.raises(ChoiceError, match="nicht lesbar"):
        make_entry(out / "missing.wav", out, "favourite")
    with pytest.raises(ChoiceError, match="Unbekanntes Urteil"):
        make_entry(out / "loose.wav", out, "like")
    with pytest.raises(ChoiceError, match="Format"):
        make_entry(out / "loose.wav", out, "favourite", "x" * 2001)


def test_append_and_read_round_trip(out, tmp_path):
    log = ChoiceLog(tmp_path / "cfg" / "choices.jsonl")  # parent dir is created
    a = make_entry(out / "loose.wav", out, "favourite", "Grüße\nzweite Zeile", now=NOW)
    b = make_entry(out / "loose.wav", out, "reject", now="2026-11-07T12:00:01Z")
    log.append(a)
    log.append(b)
    text = log.path.read_text(encoding="utf-8")
    assert text.count("\n") == 2 and text.endswith("\n")  # the note's newline is escaped
    for entry in lines(log.path):
        assert list(CONTRACT.iter_errors(entry)) == []
    res = log.read()
    assert (res.entries, res.skipped, res.error) == ([a, b], 0, "")


def test_refused_entry_writes_nothing(out, tmp_path):
    log = ChoiceLog(tmp_path / "choices.jsonl")
    e = make_entry(out / "loose.wav", out, "favourite", now=NOW)
    e["verdict"] = "Favorit"
    with pytest.raises(ChoiceError):
        log.append(e)
    assert not log.path.exists()


def test_reader_skips_and_counts_bad_lines(tmp_path):
    good = (FIX / "choice_log" / "valid.jsonl").read_bytes().splitlines()
    data = b"\n".join([
        good[0],
        b"{not json",
        b"",  # blank line
        b"\xff\xfe broken utf-8",
        b'{"schema_version": "0.1"}',  # JSON, refused by the contract
        b"[]",
        good[1],
    ]) + b"\n"
    path = tmp_path / "choices.jsonl"
    path.write_bytes(data)
    res = ChoiceLog(path).read()
    assert res.skipped == 5
    assert res.entries == [json.loads(good[0]), json.loads(good[1])]
    assert path.read_bytes() == data  # never repaired


def test_missing_and_unreadable_file(tmp_path):
    assert ChoiceLog(tmp_path / "nope.jsonl").read() == choices.LogRead()
    (tmp_path / "dir.jsonl").mkdir()
    res = ChoiceLog(tmp_path / "dir.jsonl").read()
    assert res.entries == [] and "nicht lesbar" in res.error


def test_append_after_a_cut_line_starts_a_new_line(out, tmp_path):
    path = tmp_path / "choices.jsonl"
    path.write_bytes(b'{"schema_version": "0.1", "time": "2026-11-0')  # crash mid-write
    log = ChoiceLog(path)
    e = make_entry(out / "loose.wav", out, "favourite", now=NOW)
    log.append(e)
    res = log.read()
    assert res.entries == [e] and res.skipped == 1


def test_short_write_raises_and_the_next_append_recovers(out, tmp_path, monkeypatch):
    """Disk full: os.write writes part of the line. The append must raise (the GUI then says
    'nicht gespeichert'), and the next append must still give a readable entry."""
    log = ChoiceLog(tmp_path / "choices.jsonl")
    first = make_entry(out / "loose.wav", out, "favourite", now=NOW)
    log.append(first)
    real_write = os.write
    monkeypatch.setattr(choices.os, "write", lambda fd, data: real_write(fd, data[:10]))
    with pytest.raises(OSError):
        log.append(make_entry(out / "loose.wav", out, "reject", now=NOW))
    monkeypatch.setattr(choices.os, "write", real_write)
    last = make_entry(out / "loose.wav", out, "neutral", now="2026-11-07T12:00:05Z")
    log.append(last)
    res = log.read()
    assert res.entries == [first, last] and res.skipped == 1


def test_write_error_raises(out, tmp_path, monkeypatch):
    log = ChoiceLog(tmp_path / "choices.jsonl")

    def full(fd, data):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(choices.os, "write", full)
    with pytest.raises(OSError):
        log.append(make_entry(out / "loose.wav", out, "favourite", now=NOW))


def test_in_memory_log_uses_the_same_rules(out):
    log = ChoiceLog()
    assert log.location == "nur im Speicher"
    e = make_entry(out / "loose.wav", out, "favourite", now=NOW)
    log.append(e)
    log._memory += b"{cut"
    log.append(e)
    res = log.read()
    assert res.entries == [e, e] and res.skipped == 1


def test_beside_settings(tmp_path):
    assert ChoiceLog.beside_settings(tmp_path / "settings.json").path == \
        tmp_path / "choices.jsonl"
    assert ChoiceLog.beside_settings(None).path is None


# --- current verdict -------------------------------------------------------------------------

ORDER = (FIX / "choice_log" / "order.jsonl").read_bytes()


def test_current_verdict_by_instant_on_the_order_fixture():
    """order.jsonl: line 1 10:30+01:00 (= 09:30Z) reject, line 2 09:45Z favourite, line 3
    09:30Z neutral. Newest instant is line 2; string order would say line 1."""
    res = parse_lines(ORDER)
    assert res.skipped == 0 and len(res.entries) == 3
    (sha,) = current_verdicts(res.entries)
    assert current_verdicts(res.entries)[sha]["verdict"] == "favourite"
    # Without line 2 the two 09:30Z entries tie: the later line (neutral) wins.
    assert current_verdicts([res.entries[0], res.entries[2]])[sha]["verdict"] == "neutral"


def test_entries_without_hash_are_history_only():
    lt1 = parse_lines((FIX / "choice_log" / "lt1.jsonl").read_bytes())
    assert len(lt1.entries) == 7 and lt1.skipped == 0
    assert current_verdicts(lt1.entries) == {}


def test_known_sha256_is_cached_per_file_state(tmp_path, monkeypatch):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"abc")
    cache: dict = {}
    calls = []
    real = choices.file_sha256
    monkeypatch.setattr(choices, "file_sha256", lambda p: calls.append(p) or real(p))
    assert choices.known_sha256(wav, cache) == hashlib.sha256(b"abc").hexdigest()
    assert choices.known_sha256(wav, cache) == hashlib.sha256(b"abc").hexdigest()
    assert len(calls) == 1
    wav.write_bytes(b"abcd")  # new size: hashed again
    assert choices.known_sha256(wav, cache) == hashlib.sha256(b"abcd").hexdigest()
    assert choices.known_sha256(tmp_path / "gone.wav", cache) is None
