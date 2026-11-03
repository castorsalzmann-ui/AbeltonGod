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
