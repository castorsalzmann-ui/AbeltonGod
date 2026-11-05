"""scripts/qa/smoke_pipeline.py: the independent checks must see planted faults (QA tool test).

WAVs are written with the stdlib ``wave`` module (not the engine). The end-to-end part runs the
smoke on one preset per category; it needs no Ableton and uses only the fake server double.
"""

from __future__ import annotations

import hashlib
import importlib.util
import math
import struct
import sys
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "smoke_pipeline", ROOT / "scripts/qa/smoke_pipeline.py")
smoke = importlib.util.module_from_spec(spec)
sys.modules["smoke_pipeline"] = smoke
spec.loader.exec_module(smoke)

SR = 44100


def make_wav(path: Path, *, dc=0.0, amp=0.5, tail=True, seconds=0.2) -> bytes:
    n = int(SR * seconds)
    frames = b""
    for i in range(n):
        env = (1 - i / n) if tail else 1.0
        v = amp * env * math.sin(2 * math.pi * 200 * i / SR) + dc
        frames += struct.pack("<h", max(-32768, min(32767, round(v * 32768))))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(frames)
    return path.read_bytes()


def meta_for(data: bytes, amp=0.5, seconds=0.2) -> dict:
    return {"sha256": hashlib.sha256(data).hexdigest(),
            "features": {"peak_dbfs": 20 * math.log10(max(amp, 1e-9)),
                         "length_ms": seconds * 1000}}


def failed(res: smoke.Results) -> set[str]:
    return {name.split(": ", 1)[1] for name, ok, _ in res.rows if not ok}


def run_check(tmp_path, meta_fix=None, **kw) -> smoke.Results:
    p = tmp_path / "a.wav"
    data = make_wav(p, **kw)
    meta = meta_for(data, amp=kw.get("amp", 0.5), seconds=kw.get("seconds", 0.2))
    if meta_fix:
        meta_fix(meta)
    res = smoke.Results()
    smoke.check_audio(res, "t", p, meta)
    return res


def test_clean_wav_passes_every_check(tmp_path):
    res = run_check(tmp_path)
    assert failed(res) == set(), res.rows
    assert len(res.rows) >= 9


@pytest.mark.parametrize("kw, expected", [
    ({"dc": 0.05}, "DC offset"),
    ({"amp": 0.0}, "peak <= full scale, not silent"),
    ({"amp": 1.5}, "no clipping"),
    ({"tail": False}, "tail ends near zero"),
    ({"seconds": 8.0}, "length"),
])
def test_planted_audio_faults_are_flagged(tmp_path, kw, expected):
    res = run_check(tmp_path, **kw)
    assert expected in failed(res), (kw, res.rows)


def test_sidecar_disagreement_is_flagged(tmp_path):
    def wrong(meta):
        meta["features"]["peak_dbfs"] += 1.0
        meta["features"]["length_ms"] += 5
        meta["sha256"] = "0" * 64

    assert {"sidecar peak_dbfs matches", "sidecar length_ms matches",
            "sidecar sha256 matches file"} <= failed(run_check(tmp_path, wrong))


def test_reader_rejects_broken_files(tmp_path):
    good = make_wav(tmp_path / "g.wav")
    for bad in (good[:30], good[:-3], b"RIFX" + good[4:], good[:36] + b"junk" + good[40:]):
        with pytest.raises(ValueError):
            smoke.read_wav(bad)


def test_reader_matches_stdlib_wave(tmp_path):
    p = tmp_path / "g.wav"
    make_wav(p)
    ours = smoke.read_wav(p.read_bytes())
    with wave.open(str(p), "rb") as w:
        assert (ours["sr"], ours["channels"], ours["bits"], ours["frames"]) == (
            w.getframerate(), w.getnchannels(), w.getsampwidth() * 8, w.getnframes())


def test_end_to_end_one_preset_per_category(tmp_path):
    out = tmp_path / "summary.json"
    assert smoke.main(["--presets-per-category", "1", "--categories", "kick", "clap", "hat",
                       "--keep", str(tmp_path / "w"),
                       "--json", str(out)]) == 0
    import json

    summary = json.loads(out.read_text("utf-8"))
    assert summary["failed"] == 0 and summary["checks"] > 100
    assert {c for c, v in summary["categories"].items() if v["registered"]} >= {
        "kick", "clap", "hat"}


# --- #364: negative tests and --expect-fail ---------------------------------------------------

def test_riff_size_field_mismatch_is_flagged(tmp_path):
    p = tmp_path / "a.wav"
    data = bytearray(make_wav(p))
    data[4:8] = struct.pack("<I", len(data))  # should be len - 8
    p.write_bytes(bytes(data))
    meta = meta_for(bytes(data))
    res = smoke.Results()
    smoke.check_audio(res, "t", p, meta)
    assert "riff size field" in failed(res), res.rows


def test_library_overwrite_instead_of_002_suffix_is_flagged(tmp_path, monkeypatch):
    import library

    real = library.place_sample
    seen: dict[str, Path] = {}

    def overwriting(category, params, project, **kw):
        path = real(category, params, project, **kw)
        # a broken collision rule: the second call hands back the first name again
        return seen.setdefault(str(project), path)

    monkeypatch.setattr(library, "place_sample", overwriting)
    res = smoke.Results()
    smoke.smoke_library(res, tmp_path)
    bad = failed(res)
    assert any(n.endswith("collision gets _002, first untouched") for n in bad), res.rows
    clean = smoke.Results()
    monkeypatch.setattr(library, "place_sample", real)
    smoke.smoke_library(clean, tmp_path / "clean")
    assert failed(clean) == set(), clean.rows
    assert len(clean.rows) >= 5


@pytest.mark.parametrize("fault", ["wrong-bytes", "raises"])
def test_rerender_from_sidecar_faults_are_flagged(tmp_path, monkeypatch, fault):
    import audio_engine.io as engine_io

    def broken(path, **kw):
        if fault == "raises":
            raise RuntimeError("boom")
        return b"not the wav"

    monkeypatch.setattr(engine_io, "rerender_from_sidecar", broken)
    res = smoke.Results()
    smoke.smoke_categories(res, tmp_path, 1, ["kick"])
    bad = {n for n, ok, _ in res.rows if not ok}
    expected = ("re-render from sidecar is byte-identical" if fault == "wrong-bytes"
                else "re-render from sidecar")
    assert any(n.endswith(expected) for n in bad), res.rows


def test_toolbox_names_check_can_fail(tmp_path, monkeypatch):
    from orchestrator.tools import Toolbox

    monkeypatch.setattr(Toolbox, "names", property(lambda self: ("only_this",)))
    res = smoke.Results()
    smoke.smoke_tools(res, tmp_path)
    assert "toolbox: names" in {n for n, ok, _ in res.rows if not ok}, res.rows


def test_split_known_matches_name_or_detail_and_reports_stale():
    rows = [("kick/x: DC offset", False, "dc=0.01"), ("bass/y: length", False, "9 s")]
    known, unexpected, stale = smoke.split_known(rows, ["DC offset", "nothing-matches"])
    assert known == [rows[0]] and unexpected == [rows[1]] and stale == ["nothing-matches"]
    assert smoke.split_known(rows, ["9 s"])[0] == [rows[1]]  # detail text matches too
    assert smoke.split_known(rows, []) == ([], rows, [])


def _fake_run(monkeypatch, rows):
    def categories(res, work, limit, only):
        for name, ok, detail in rows:
            res.check(name, ok, detail)
        return {}

    monkeypatch.setattr(smoke, "smoke_categories", categories)
    monkeypatch.setattr(smoke, "smoke_library", lambda res, work: None)
    monkeypatch.setattr(smoke, "smoke_tools", lambda res, work: {})


def test_expect_fail_exit_codes(monkeypatch, tmp_path, capsys):
    _fake_run(monkeypatch, [("bass/a: DC offset", False, "dc=0.02"), ("bass/a: length", True, "")])
    keep = ["--keep", str(tmp_path)]
    assert smoke.main(keep) == 1  # no flag: the failure counts
    assert smoke.main([*keep, "--expect-fail", "bass/a: DC offset"]) == 0
    out = capsys.readouterr().out
    assert "KNOWN bass/a: DC offset: dc=0.02" in out
    # a stale flag (nothing fails there any more) is reported but is not a gate failure
    assert smoke.main([*keep, "--expect-fail", "DC offset", "--expect-fail", "length"]) == 0
    out = capsys.readouterr().out
    assert "STALE --expect-fail 'length'" in out and "no failing check matches" in out
    assert smoke.main([*keep, "--expect-fail", "nothing-matches"]) == 1  # real failure still fails
    # an unrelated failure is not hidden by the flag
    _fake_run(monkeypatch, [("bass/a: DC offset", False, ""), ("bass/a: tail", False, "")])
    assert smoke.main([*keep, "--expect-fail", "DC offset"]) == 1
    summary_path = tmp_path / "s.json"
    smoke.main([*keep, "--expect-fail", "DC offset", "--json", str(summary_path)])
    import json
    s = json.loads(summary_path.read_text("utf-8"))
    assert s["failed"] == 1 and s["known"] == 1
