"""Kit export (#498): gui_core.kit plan, export and favourites prefill. No Qt.

Expected names, hashes and bytes are written here or measured with hashlib / plain file reads,
not taken from gui_core.kit. kit.json is validated with a validator built in this file from
contracts/kit.schema.json."""

from __future__ import annotations

import errno
import hashlib
import json
import random
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from gui_core import kit
from gui_core.choices import make_entry
from gui_core.library import scan

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = Draft202012Validator(
    json.loads((ROOT / "contracts" / "kit.schema.json").read_text(encoding="utf-8")))

# slot -> (category, file stem, preset) of the library made by ``out``
FILES = {
    "kick": ("kick", "kick-rumble", "rumble"),
    "clap_snare": ("snare", "snare-tight", "tight"),
    "closed_hat": ("hat", "hat-closed-tick", "closed-tick"),
    "open_hat": ("hat", "hat-open-long", "open-long"),
    "rim": ("rim", "rim-click", "click"),
    "perc": ("perc", "perc-conga", "conga"),
    "bass": ("bass", "bass-sub", "sub"),
}
EXPECTED_NAMES = {
    "kick": "01_kick_kick-rumble.wav",
    "clap_snare": "02_snare_snare-tight.wav",
    "closed_hat": "03_hat-closed_hat-closed-tick.wav",
    "open_hat": "04_hat-open_hat-open-long.wav",
    "rim": "05_rim_rim-click.wav",
    "perc": "06_perc_perc-conga.wav",
    "bass": "07_bass_bass-sub.wav",
}
NOW = "2026-11-07T12:00:00Z"


def make_sample(folder: Path, stem: str, category: str, preset: str, created: str,
                payload: bytes | None = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    wav = folder / f"{stem}.wav"
    wav.write_bytes(payload if payload is not None else b"RIFF" + stem.encode() * 50)
    side = {"category": category, "created_at": created,
            "parameters": {"preset": preset, "seed": 7}, "note": "verbatim ü"}
    # Odd spacing on purpose: a re-encoded copy would not be byte-equal.
    wav.with_suffix(".json").write_text(json.dumps(side, indent=3) + "\n\n", encoding="utf-8")
    return wav


@pytest.fixture
def out(tmp_path: Path) -> Path:
    d = tmp_path / "out"
    for i, (cat, stem, preset) in enumerate(FILES.values()):
        make_sample(d / "Samples" / cat, stem, cat, preset, f"2026-11-07T10:0{i}:00Z")
    return d


def picks_of(out: Path, slots=FILES) -> dict[str, Path]:
    return {k: out / "Samples" / FILES[k][0] / f"{FILES[k][1]}.wav" for k in slots}


def kits(out: Path) -> Path:
    return out / "Samples" / "Kits"


def tree(folder: Path) -> list[str]:
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*")) \
        if folder.exists() else []


# --- normal path -----------------------------------------------------------------------------

def test_export_writes_a_valid_kit_with_byte_equal_copies_and_verbatim_sidecars(out):
    picks = picks_of(out)
    folder = kit.export_kit(kit.plan_kit(out, "Peak Time", picks), now=NOW)
    assert folder == kits(out) / "Peak-Time"
    doc = json.loads((folder / "kit.json").read_text(encoding="utf-8"))
    assert list(VALIDATOR.iter_errors(doc)) == []
    assert doc["name"] == "Peak-Time" and doc["created_at"] == NOW
    assert {k: v["file"] for k, v in doc["slots"].items()} == EXPECTED_NAMES
    for key, src in picks.items():
        copy = folder / EXPECTED_NAMES[key]
        assert copy.read_bytes() == src.read_bytes()
        assert copy.with_suffix(".json").read_bytes() == src.with_suffix(".json").read_bytes()
        item = doc["slots"][key]
        assert item["sha256"] == hashlib.sha256(src.read_bytes()).hexdigest()
        assert item["source"] == f"Samples/{FILES[key][0]}/{FILES[key][1]}.wav"
        assert item["category"] == FILES[key][0]
    assert sorted(p.name for p in folder.iterdir()) == sorted(
        [*EXPECTED_NAMES.values(), *(n[:-4] + ".json" for n in EXPECTED_NAMES.values()),
         "kit.json"])
    assert [p.name for p in kits(out).iterdir()] == ["Peak-Time"]  # no temp folder left


def test_bass_is_optional_and_left_out_when_empty(out):
    picks = {**picks_of(out), "bass": None}
    folder = kit.export_kit(kit.plan_kit(out, "k", picks), now=NOW)
    doc = json.loads((folder / "kit.json").read_text(encoding="utf-8"))
    assert "bass" not in doc["slots"] and not VALIDATOR.is_valid({**doc, "slots": {
        **doc["slots"], "bass": None}})
    assert list(VALIDATOR.iter_errors(doc)) == []


@pytest.mark.parametrize("slot", ["kick", "clap_snare", "closed_hat", "open_hat", "rim", "perc"])
def test_a_missing_drum_slot_is_refused_before_anything_is_written(out, slot):
    picks = {**picks_of(out), slot: None}
    with pytest.raises(kit.KitError, match="keine Datei"):
        kit.plan_kit(out, "k", picks)
    assert not kits(out).exists()


def test_wrong_category_unreadable_and_outside_files_are_refused(out, tmp_path):
    picks = picks_of(out)
    with pytest.raises(kit.KitError, match="ist kick"):
        kit.plan_kit(out, "k", {**picks, "rim": picks["kick"]})
    bad = out / "Samples" / "x.wav"
    bad.write_bytes(b"RIFF")
    with pytest.raises(kit.KitError, match="unlesbar"):
        kit.plan_kit(out, "k", {**picks, "perc": bad})
    other = make_sample(tmp_path / "elsewhere", "perc-x", "perc", "x", NOW)
    with pytest.raises(kit.KitError, match="nicht im Ausgabeordner"):
        kit.plan_kit(out, "k", {**picks, "perc": other})
    with pytest.raises(kit.KitError, match="Kit-Namen"):
        kit.plan_kit(out, "  ", picks)
    assert not kits(out).exists()


def test_an_existing_kit_name_gives_002_then_003_and_the_old_kit_is_untouched(out):
    picks = picks_of(out)
    first = kit.export_kit(kit.plan_kit(out, "Set", picks), now=NOW)
    before = {p: p.read_bytes() for p in first.iterdir()}
    (kits(out) / "Set_002").mkdir()  # a folder of that name (empty, maybe the user's)
    (kits(out) / "Set_002" / "mine.txt").write_text("keep")
    second = kit.export_kit(kit.plan_kit(out, "Set", picks), now=NOW)
    assert second.name == "Set_003"
    assert {p: p.read_bytes() for p in first.iterdir()} == before
    assert (kits(out) / "Set_002" / "mine.txt").read_text() == "keep"


def test_a_rename_that_finds_the_name_taken_tries_the_next_one(out, monkeypatch):
    """The name appears between the free check and the rename (another export): the next
    number is used, nothing is replaced."""
    real = kit._rename
    calls = []

    def racing(src, dst):
        calls.append(Path(dst).name)
        if len(calls) == 1:
            Path(dst).mkdir()
            (Path(dst) / "other.wav").write_bytes(b"x")
            raise OSError(errno.ENOTEMPTY, "Directory not empty")
        real(src, dst)

    monkeypatch.setattr(kit, "_rename", racing)
    folder = kit.export_kit(kit.plan_kit(out, "Race", picks_of(out)), now=NOW)
    assert calls == ["Race", "Race_002"] and folder.name == "Race_002"
    assert [p.name for p in (kits(out) / "Race").iterdir()] == ["other.wav"]


def test_too_long_paths_are_refused_before_writing(out):
    with pytest.raises(kit.KitError, match="Kit-Pfad zu lang"):
        kit.plan_kit(out, "k" * 80, picks_of(out), max_path_chars=len(str(out)) + 40)
    p = kit.plan_kit(out, "k", picks_of(out), max_path_chars=len(str(out)) + 70)
    # The copies first live in ".kit-tmp-" + 12 hex characters (longer than "k_999"); the
    # longest path is Live's "<copy>.wav.asd" there.
    longest = max(len(str(kits(out) / ".kit-tmp-abcdef012345" / i.file)) + 4 for i in p.items)
    assert longest <= len(str(out)) + 70


# --- failures leave nothing ------------------------------------------------------------------

def _fail_on(n: int, exc: BaseException):
    real = kit._copy_file
    count = [0]

    def copy(src, dst):
        count[0] += 1
        if count[0] == n:
            Path(dst).write_bytes(Path(src).read_bytes()[:10])  # a half-written file
            raise exc
        return real(src, dst)
    return copy


@pytest.mark.parametrize("n", [1, 3, 14])  # first WAV, a sidecar ... the last sidecar
def test_disk_full_during_the_copies_leaves_no_half_kit(out, monkeypatch, n):
    monkeypatch.setattr(kit, "_copy_file", _fail_on(n, OSError(errno.ENOSPC, "No space")))
    plan = kit.plan_kit(out, "Full", picks_of(out))
    with pytest.raises(OSError, match="No space"):
        kit.export_kit(plan, now=NOW)
    assert not kits(out).exists()  # also the Samples/Kits folder this call made is gone
    assert (out / "Samples").is_dir()


def test_failure_keeps_folders_that_existed_and_other_kits(out, monkeypatch):
    old = kit.export_kit(kit.plan_kit(out, "Old", picks_of(out)), now=NOW)
    before = tree(kits(out))
    monkeypatch.setattr(kit, "_copy_file", _fail_on(5, KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        kit.export_kit(kit.plan_kit(out, "New", picks_of(out)), now=NOW)
    assert tree(kits(out)) == before and old.is_dir()


@pytest.mark.parametrize("where", ["_write_new", "_rename"])
def test_failure_writing_kit_json_or_renaming_leaves_nothing(out, monkeypatch, where):
    def boom(*a, **k):
        raise OSError(errno.ENOSPC, "No space")
    monkeypatch.setattr(kit, where, boom)
    with pytest.raises(OSError):
        kit.export_kit(kit.plan_kit(out, "Full", picks_of(out)), now=NOW)
    assert not kits(out).exists()


def test_a_source_changed_after_planning_aborts_the_export(out):
    picks = picks_of(out)
    plan = kit.plan_kit(out, "k", picks)
    picks["rim"].write_bytes(b"RIFF changed")
    with pytest.raises(kit.KitError, match="geändert"):
        kit.export_kit(plan, now=NOW)
    assert not kits(out).exists()


def test_a_source_deleted_after_planning_aborts_the_export(out):
    picks = picks_of(out)
    plan = kit.plan_kit(out, "k", picks)
    picks["perc"].with_suffix(".json").unlink()
    with pytest.raises(kit.KitError, match="fehlt"):
        kit.export_kit(plan, now=NOW)
    assert not kits(out).exists()


# --- random kits over the input range --------------------------------------------------------

def test_seeded_random_kits_are_valid_and_byte_equal(tmp_path):
    rng = random.Random(498)
    names = ["Kit", "über drums", "CON", "a.b-c_d", "...", "x" * 120, "Tëst 01", "NUL.txt"]
    for round_ in range(25):
        out = tmp_path / f"o{round_}"
        picks = {}
        for slot in kit.SLOTS:
            if not slot.required and rng.random() < 0.5:
                continue
            cat = rng.choice(slot.categories)
            stem = "".join(rng.choice("abcXYZ09-_. ü") for _ in range(rng.randint(1, 60)))
            payload = rng.randbytes(rng.randint(0, 3000))
            folder = out / "Samples" / f"d{rng.randint(0, 2)}"
            src = make_sample(folder, f"s{slot.key}{stem}".rstrip(". "), cat, "p", NOW, payload)
            picks[slot.key] = src
        name = rng.choice(names)
        folder = kit.export_kit(kit.plan_kit(out, name, picks), now=NOW)
        doc = json.loads((folder / "kit.json").read_text(encoding="utf-8"))
        assert list(VALIDATOR.iter_errors(doc)) == [], (round_, name)
        assert set(doc["slots"]) == set(picks)
        for key, src in picks.items():
            copy = folder / doc["slots"][key]["file"]
            assert copy.read_bytes() == src.read_bytes(), (round_, key)
            assert copy.with_suffix(".json").read_bytes() == \
                src.with_suffix(".json").read_bytes()
            assert len(str(copy)) + 4 <= 259 or len(str(out)) > 150


# --- prefill from favourites -----------------------------------------------------------------

def _log(out: Path, items: list[tuple[Path, str, str]]) -> list[dict]:
    return [make_entry(wav, out, verdict, now=t) for wav, verdict, t in items]


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_prefill_takes_the_newest_favourite_by_instant_not_by_string(out):
    s = out / "Samples"
    a = make_sample(s / "kick", "kick-a", "kick", "a", NOW)
    b = make_sample(s / "kick", "kick-b", "kick", "b", NOW)
    c = make_sample(s / "kick", "kick-c", "kick", "c", NOW)
    log = _log(out, [
        (b, "favourite", "2026-11-07T09:45:00Z"),
        (a, "favourite", "2026-11-07T10:30:00+01:00"),  # = 09:30Z: older, string is larger
        (c, "favourite", "2026-11-07T11:00:00Z"),
        (c, "reject", "2026-11-07T11:05:00Z"),  # c is no longer a favourite
    ])
    got = kit.prefill(scan(out).entries, log, out, _sha)
    assert got["kick"] == b
    assert got["rim"] is None and got["bass"] is None  # no favourites there


def test_prefill_equal_instants_the_later_line_wins(out):
    s = out / "Samples"
    a = make_sample(s / "rim", "rim-a", "rim", "a", NOW)
    b = make_sample(s / "rim", "rim-b", "rim", "b", NOW)
    log = _log(out, [(a, "favourite", "2026-11-07T10:00:00Z"),
                     (b, "favourite", "2026-11-07T11:00:00+01:00")])
    assert kit.prefill(scan(out).entries, log, out, _sha)["rim"] == b


def test_prefill_hats_open_preset_goes_to_the_open_slot_and_files_are_not_reused(out):
    s = out / "Samples" / "hat"
    closed = make_sample(s, "h1", "hat", "closed-tick", NOW)
    opened = make_sample(s, "h2", "hat", "open-long", NOW)
    log = _log(out, [(closed, "favourite", "2026-11-07T10:00:00Z"),
                     (opened, "favourite", "2026-11-07T11:00:00Z")])  # newest is the open one
    got = kit.prefill(scan(out).entries, log, out, _sha)
    assert got["closed_hat"] == closed and got["open_hat"] == opened
    only = _log(out, [(opened, "favourite", "2026-11-07T11:00:00Z")])
    got = kit.prefill(scan(out).entries, only, out, _sha)
    assert got["open_hat"] is None and got["closed_hat"] == opened  # fallback, no reuse


def test_kit_copies_are_never_candidates_or_prefills(out):
    picks = picks_of(out)
    kit.export_kit(kit.plan_kit(out, "K", picks), now=NOW)
    entries = scan(out).entries
    for slot in kit.SLOTS:
        assert all("Kits" not in e.wav_path.parts for e in kit.candidates(slot, entries, out))
    log = _log(out, [(picks["kick"], "favourite", NOW)])
    assert kit.prefill(entries, log, out, _sha)["kick"] == picks["kick"]
