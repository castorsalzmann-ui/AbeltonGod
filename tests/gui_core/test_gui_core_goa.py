"""Goa clip service layer (no Qt, D-035, #546): option coverage, byte identity with the clip
CLI, error objects, the clip summary, and no song form (no sections, energy or song length;
no path of the GUI layer reaches ``goa_arrangement``)."""

from __future__ import annotations

import ast
import errno
import hashlib
import random
import struct
from pathlib import Path

import pytest

from audio_engine import goa_clips
from gui_core import goa
from gui_core.goa import GoaFormModel
from gui_core.goa_render import GoaJob, GoaService, run_goa_job

SRC = Path(__file__).resolve().parents[2] / "src"

# sha256 of the CLI output, pinned as literals (made with `python -m audio_engine.goa_clips`
# on the argument lists below, not with the code under test).
PINNED = {
    "default": {  # --seed 3
        "goa_lead_seed3_145bpm_4bars.mid":
            "ee87c842b62762720d81a922107e8642bf21f87141ea26983497d3b967519b10",
        "goa_arp_seed3_145bpm_4bars.mid":
            "43ab8393f7248721d852c144d8b367708aa61b04428ec5b3c7ce21c53bb7c437",
        "goa_pad_seed3_145bpm_4bars.mid":
            "0a42ff5925093e8239c0eb4688dcee564af915643593ee861ef4100ea6799a78",
        "goa_pluck_seed3_145bpm_4bars.mid":
            "80a9a87587172e555f45823a1b4b48c24fbfbb8d02e22e2401862119886c84b5",
        "README.md": "e16de7e93e3f8099fc47ea35cf62e82294b448ee9402a679c5f6eba6d9cb3f73"},
    "custom": {  # --seed 9 --bars 2 --bpm 138 --root Bb --scale aeolian --density 0.4
                 # --register -1 --arp-pattern random --progression 0,5 --voices lead,arp
        "goa_lead_seed9_138bpm_2bars.mid":
            "2b9d27017d6334832c313d01981f2dd72e1f1e72c923495fac50932c0bffec30",
        "goa_arp_seed9_138bpm_2bars.mid":
            "6c6f3f6b6ffaae8f303e66209197163508e6f7bd8a56ca14db3dcd2606147f77",
        "README.md": "ef895bbc800aef23fc22beedcd374026eac9591d9a45a860a34d6cf0ed8a3e20"},
}

# What the user types into the form for each pinned run (field -> text; optionals switched on).
FORM_RUNS = {
    "default": {"seed": "3"},
    "custom": {
        "seed": "9", "bars": "2", "bpm": "138", "root": "Bb", "scale": "aeolian",
        "density": "0.4", "register": "-1", "arp_pattern": "random", "progression": "0,5",
        "voices": "lead,arp"},
}

# Song-form flags: of the removed arrangement mode and of goa_melody's sections.
SONG_FLAGS = ("--roll=gallop", "--kick-preset=default", "--intro-bars=8", "--breakdowns=1",
              "--no-samples", "--sections=A:4:0.5:lead", "--length=4", "--energy=1")


def filled(values: dict[str, str]) -> GoaFormModel:
    m = GoaFormModel()
    for dest, text in values.items():
        if m.spec(dest).optional:
            m.set_active(dest, True)
        m.set_text(dest, text)
    return m


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file()}


def smf_info(data: bytes) -> tuple[int, int, str, int]:
    """(format, tracks, track name, end tick) of a one-track SMF, read here byte by byte."""
    assert data[:4] == b"MThd"
    _len, fmt, ntrk, _ppq = struct.unpack(">IHHH", data[4:14])
    body = data[22:]
    i, tick, name, end = 0, 0, "", None
    while i < len(body):
        delta = 0
        while True:
            b = body[i]
            i += 1
            delta = (delta << 7) | (b & 0x7F)
            if b < 0x80:
                break
        tick += delta
        if body[i] == 0xFF:
            typ, ln = body[i + 1], body[i + 2]
            if typ == 0x03:
                name = body[i + 3:i + 3 + ln].decode("ascii")
            if typ == 0x2F:
                end = tick
            i += 3 + ln
        else:
            i += 3
    return fmt, ntrk, name, end


# --- every CLI option is in the form --------------------------------------------------------

def test_every_cli_option_has_a_form_field():
    parser = goa_clips.build_parser()
    cli = {a.dest: a.option_strings[0] for a in parser._actions
           if a.dest not in ("help", "out")}
    form = {s.dest: s.flag for s in GoaFormModel().specs}
    assert form == cli
    assert GoaFormModel().argv("X")[0] == "--out=X"


def test_form_argv_with_every_optional_switched_on_is_accepted_by_the_cli_parser():
    m = GoaFormModel()
    for s in m.specs:
        if s.optional:
            m.set_active(s.dest, True)
            m.set_text(s.dest, "0" if s.dest == "register" else "0.5")
    assert m.evaluate().ok, m.evaluate().problem
    assert goa.parse_argv(m.argv("X")).out == "X"


def test_tempo_is_whole_bpm_in_the_form():
    m = GoaFormModel()
    assert m.spec("bpm").kind == "int" and m.text["bpm"] == "145"
    m.set_text("bpm", "140.5")
    assert "bpm" in m.field_issues() and not m.evaluate().ok


# --- D-035: clips, no song form -------------------------------------------------------------

def _imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            out.add(mod)
            out |= {f"{mod}.{a.name}" for a in node.names}
    return out


def test_no_gui_module_imports_the_goa_arrangement_generator():
    """D-033: the full-song arranger stays a CLI. No module of the GUI layers may import it."""
    files = sorted((SRC / "gui").rglob("*.py")) + sorted((SRC / "gui_core").rglob("*.py"))
    assert len(files) > 20
    hits = [str(p.relative_to(SRC)) for p in files
            if any(name.endswith("goa_arrangement") for name in _imports(p))]
    assert hits == []


def test_the_form_has_clip_options_only():
    dests = {s.dest for s in GoaFormModel().specs}
    assert dests == {"seed", "bars", "bpm", "root", "scale", "density", "register",
                     "arp_pattern", "progression", "voices"}
    assert GoaFormModel().spec("voices").choices == ("lead", "arp", "pad", "pluck")
    assert GoaFormModel().text["bars"] == "4"


@pytest.mark.parametrize("flag", SONG_FLAGS)
def test_song_form_flags_are_refused_and_nothing_is_written(flag, tmp_path):
    out = tmp_path / "never"
    res = run_goa_job(GoaJob((f"--out={out}", flag)))
    assert res.error is not None and res.error.kind == "invalid_params"
    assert "Ungültige Option" in res.error.message
    assert not out.exists()


def test_export_writes_one_clip_per_chosen_voice_into_the_shown_folder(tmp_path):
    rng = random.Random(20261109)
    for i in range(6):
        voices = [v for v in ("lead", "arp", "pad", "pluck") if rng.random() < 0.6] or ["pad"]
        bars = rng.randint(1, 16)
        model = filled({"seed": str(rng.randrange(10**6)), "voices": ",".join(voices),
                        "bars": str(bars), "bpm": str(rng.randint(135, 150))})
        out = tmp_path / f"r{i}"
        res = run_goa_job(GoaJob(tuple(model.argv(str(out)))))
        assert res.ok, res.error
        assert res.out_dir == out  # the folder shown before the export is the one written
        assert sorted(p.name for p in out.iterdir()) == sorted(
            [p.name for p in res.mid_paths] + ["README.md"])
        assert [p.parent for p in res.mid_paths] == [out] * len(voices)
        for v, p in zip(voices, res.mid_paths, strict=True):
            assert smf_info(p.read_bytes()) == (0, 1, f"Goa {v}", bars * 1920)


# --- byte identity --------------------------------------------------------------------------

@pytest.mark.parametrize("key", sorted(FORM_RUNS))
def test_form_export_matches_the_pinned_cli_hashes(key, tmp_path):
    model = filled(FORM_RUNS[key])
    out = tmp_path / "out"
    res = run_goa_job(GoaJob(tuple(model.argv(str(out)))))
    assert res.ok, res.error
    got = {p.name: sha(p) for p in out.iterdir() if p.is_file()}
    assert got == PINNED[key]
    assert res.readme_text == (out / "README.md").read_text(encoding="utf-8")


def test_whole_folder_equals_what_the_real_cli_main_writes(tmp_path):
    cli = tmp_path / "cli"
    assert goa_clips.main([f"--out={cli}", "--seed=2", "--bars=8"]) == 0
    model = filled({"seed": "2", "bars": "8"})
    gui = tmp_path / "gui"
    res = run_goa_job(GoaJob(tuple(model.argv(str(gui)))))
    assert res.ok and tree(gui) == tree(cli)


# --- errors ---------------------------------------------------------------------------------

@pytest.mark.parametrize("field,value,needle", [
    ("bpm", "200", "bpm must be"),
    ("bpm", "130", "bpm must be"),
    ("density", "2", "density"),
    ("register", "5", "register"),
    ("progression", "0,9", "progression"),
    ("bars", "0", "bars"),
    ("bars", "17", "bars"),
])
def test_out_of_range_options_are_refused_by_the_module_and_nothing_is_written(
        field, value, needle, tmp_path):
    model = filled({field: value})
    ev = model.evaluate()
    out = tmp_path / "never"
    res = run_goa_job(GoaJob(tuple(model.argv(str(out)))))
    assert not ev.ok and ev.plan is None and ev.kwargs is None
    assert needle in ev.problem and ev.problem.startswith("Ungültige")
    assert res.error is not None and res.error.kind == "invalid_params"
    assert needle in res.error.message and res.error.detail
    assert not out.exists()


def test_syntax_problems_are_marked_per_field_and_block_the_plan():
    m = GoaFormModel()
    m.set_text("bpm", "schnell")
    m.set_text("seed", "1.5")
    assert set(m.field_issues()) == {"bpm", "seed"}
    ev = m.evaluate()
    assert not ev.ok and ev.plan is None and ev.problem.startswith("Seed:")
    m.set_text("bpm", "145")
    m.set_text("seed", "3")
    assert m.field_issues() == {} and m.evaluate().ok


def test_switching_an_optional_field_off_ignores_its_bad_text():
    m = filled({"density": "banana"})
    assert not m.evaluate().ok
    m.set_active("density", False)
    assert m.evaluate().ok and not any(a.startswith("--density") for a in m.argv())


def test_an_existing_target_is_never_overwritten(tmp_path):
    model = filled({"seed": "1"})
    out = tmp_path / "out"
    first = run_goa_job(GoaJob(tuple(model.argv(str(out)))))
    assert first.ok
    before = tree(out)
    second = run_goa_job(GoaJob(tuple(model.argv(str(out)))))
    assert second.error is not None and second.error.kind == "exists"
    assert "Es wurde nichts überschrieben" in second.error.message
    assert tree(out) == before


def test_unwritable_folder_and_full_disk_are_error_objects(tmp_path, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    model = GoaFormModel()
    res = run_goa_job(GoaJob(tuple(model.argv(str(blocker / "sub")))))
    assert res.error is not None and res.error.kind == "output" and not res.ok

    def full(*a, **k):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(goa_clips, "write_clips", full)
    res = run_goa_job(GoaJob(tuple(model.argv(str(tmp_path / "x")))))
    assert res.error is not None and res.error.kind == "disk_full"

    def boom(*a, **k):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(goa_clips, "write_clips", boom)
    res = run_goa_job(GoaJob(tuple(model.argv(str(tmp_path / "y")))))
    assert res.error is not None and res.error.kind == "internal" and "kaputt" in res.error.message


def test_no_output_folder_is_an_error_object():
    res = run_goa_job(GoaJob(("--out=",)))
    assert res.error is not None and "Ausgabeordner" in res.error.message


def test_service_runs_in_a_thread_and_always_finishes(tmp_path):
    model = GoaFormModel()
    seen = []
    h = GoaService().start(GoaJob(tuple(model.argv(str(tmp_path / "o")))), seen.append)
    assert h.wait(30) and h.result.ok and seen and seen[0].ok

    def crash(job):
        raise RuntimeError("x")

    h = GoaService(crash).start(GoaJob(()))
    assert h.wait(30) and h.result.error.kind == "internal"


# --- clip summary ---------------------------------------------------------------------------

def test_default_summary_has_the_known_literal_values():
    ev = GoaFormModel().evaluate()
    plan = ev.plan
    assert (plan.bars, plan.tempo, plan.key) == (4, 145.0, "A phrygian")
    assert plan.chords == (0, 0, 0, 0)  # default progression: root only (#570, N8)
    # note counts of the seed-0 default clips (#570 cell model; arp on every 16th = 64,
    # pad root + fifth held = 2; lead and pluck depend on the seed's cell)
    assert [(c.voice, c.notes) for c in plan.clips] == [
        ("lead", 26), ("arp", 64), ("pad", 2), ("pluck", 56)]
    assert plan.clips[0].file_name == "goa_lead_seed0_145bpm_4bars.mid"
    assert abs(plan.seconds - 16 * 60 / 145) < 1e-9
    assert ev.kwargs["voices"] == ["lead", "arp", "pad", "pluck"]


def test_summary_follows_bars_and_voices():
    plan = filled({"bars": "8", "voices": "pad,arp"}).evaluate().plan
    assert plan.chords == (0,) * 8
    assert [c.voice for c in plan.clips] == ["arp", "pad"]


def test_suggested_folder_names_seed_tempo_and_bars():
    assert filled({"seed": "7", "bpm": "140", "bars": "2"}).suggested_folder_name() == \
        "goa_clips_seed7_140bpm_2bars"
