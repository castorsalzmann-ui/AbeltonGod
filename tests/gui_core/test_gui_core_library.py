"""Library scan, sidecar reading and filtering (no Qt)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from gui_core.form import CATEGORY_KEYS, CategoryFormModel
from gui_core.library import UNREADABLE, drag_paths, filter_entries, read_entry, scan_library
from gui_core.render import RenderJob, run_job

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sidecars" / "kick-v01.json"


def render(cat: str, out: Path, seed: int = 1) -> Path:
    m = CategoryFormModel(cat)
    m.set_text("seed", str(seed))
    r = run_job(RenderJob(m.build_request(), out, m.preset, m.overrides(), cat))
    assert r.ok, r.error
    return r.files[0].wav_path


def fake_wav(path: Path, sidecar: str | bytes | None) -> Path:
    path.write_bytes(b"RIFF")
    if sidecar is not None:
        side = path.with_suffix(".json")
        side.write_bytes(sidecar if isinstance(sidecar, bytes) else sidecar.encode())
    return path


def test_every_category_is_read_with_preset_seed_and_key_params(tmp_path):
    for cat in CATEGORY_KEYS:
        render(cat, tmp_path, seed=7)
    entries = scan_library(tmp_path)
    assert sorted(e.category for e in entries) == sorted(CATEGORY_KEYS)
    by_cat = {e.category: e for e in entries}
    for cat, e in by_cat.items():
        assert e.readable and e.seed == 7 and e.preset == CategoryFormModel(cat).preset
        assert e.created_at.endswith("Z") or "+" in e.created_at
    assert by_cat["kick"].key_params == "pitch_end_hz=56, amp_decay_ms=420, drive=0.15"
    assert by_cat["bass"].key_params.startswith("note=43")


def test_old_sidecar_version_and_missing_category_are_read(tmp_path):
    # the repository's version-0.1 fixture sidecar, next to a WAV of the right name
    old = tmp_path / "kick-v01.wav"
    fake_wav(old, None)
    shutil.copy(FIXTURE, old.with_suffix(".json"))
    e = read_entry(old)
    assert e.readable and e.category == "kick" and e.seed == 5
    assert "drive=0.4" in e.key_params

    meta = json.loads(FIXTURE.read_text())
    del meta["category"]  # the oldest sidecars had none: they were kicks
    nocat = fake_wav(tmp_path / "nocat.wav", json.dumps(meta))
    assert read_entry(nocat).category == "kick"


def test_bad_files_are_listed_as_unreadable_never_a_crash(tmp_path):
    cases = {
        "nosidecar": None,
        "badjson": "{not json",
        "binary": b"\xff\xfe\x00\x80",
        "list": "[1, 2]",
        "emptycat": json.dumps({"category": "", "parameters": {}}),
        "weird": json.dumps({"category": "snare", "parameters": "x", "created_at": 5}),
    }
    for name, side in cases.items():
        fake_wav(tmp_path / f"{name}.wav", side)
    entries = {e.wav_path.stem: e for e in scan_library(tmp_path)}
    assert set(entries) == set(cases)
    for name in ("nosidecar", "badjson", "binary", "list", "emptycat"):
        e = entries[name]
        assert not e.readable and e.category == UNREADABLE and e.problem, name
    assert entries["weird"].readable and entries["weird"].seed is None  # tolerated, not a crash
    assert entries["nosidecar"].problem == "Sidecar-Datei fehlt"
    boolseed = fake_wav(
        tmp_path / "boolseed.wav", json.dumps({"category": "kick", "parameters": {"seed": True}})
    )
    assert read_entry(boolseed).seed is None


def test_missing_or_empty_folder_gives_empty_list(tmp_path):
    assert scan_library(tmp_path / "nope") == []
    assert scan_library(tmp_path) == []


def test_subfolders_are_scanned_and_order_is_newest_first(tmp_path):
    a = render("kick", tmp_path / "a", seed=1)
    b = render("hat", tmp_path / "b" / "deep", seed=2)
    # a.wav (punchy...) sorts after closed-std... by name, so only the time stamp can order them
    for wav, stamp in ((a, "2026-03-01T10:00:00Z"), (b, "2026-01-01T10:00:00Z")):
        side = wav.with_suffix(".json")
        meta = json.loads(side.read_text())
        meta["created_at"] = stamp
        side.write_text(json.dumps(meta))
    assert [e.wav_path for e in scan_library(tmp_path)] == [a, b]


def test_filter_by_category_and_search_words(tmp_path):
    render("kick", tmp_path, seed=11)
    render("hat", tmp_path, seed=12)
    render("bass", tmp_path, seed=13)
    fake_wav(tmp_path / "broken.wav", None)
    entries = scan_library(tmp_path)
    assert len(entries) == 4
    assert [e.category for e in filter_entries(entries, "hat")] == ["hat"]
    assert [e.category for e in filter_entries(entries, UNREADABLE)] == [UNREADABLE]
    assert len(filter_entries(entries, None, "")) == 4
    assert [e.seed for e in filter_entries(entries, None, "s13")] == [13]
    assert [e.category for e in filter_entries(entries, None, "BASS seed")] == []
    assert [e.category for e in filter_entries(entries, None, "closed-std")] == ["hat"]
    assert filter_entries(entries, "kick", "closed") == []


def test_drag_paths_only_existing_files(tmp_path):
    wav = render("kick", tmp_path)
    entries = scan_library(tmp_path)
    assert drag_paths(entries) == [wav]
    wav.unlink()
    assert drag_paths(entries) == []
