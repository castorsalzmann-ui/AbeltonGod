"""Goa-Melodie service layer (no Qt): option coverage, byte identity with the melody CLI, error
objects, the timeline against the generator's plan data, and D-033 (melody only: no path of
the GUI layer reaches ``goa_arrangement``, no drum/bass track, no sample WAV)."""

from __future__ import annotations

import ast
import errno
import hashlib
import random
import struct
from pathlib import Path

import pytest

from audio_engine import goa_melody
from gui_core import goa
from gui_core.goa import GoaFormModel
from gui_core.goa_render import GoaJob, GoaService, run_goa_job

SRC = Path(__file__).resolve().parents[2] / "src"

# sha256 of the CLI output, pinned as literals (made with `python -m audio_engine.goa_melody`
# on the argument lists below, not with the code under test).
PINNED = {
    "mel_default": {
        "goa_melody_seed3_145bpm.mid":
            "9a601a7381fbaf7ffb5bb9354bed1ccad7cb78a41261648ddace68ab4ddd0579",
        "README.md": "8806593f873084d8c6dfdd550bcc16a4a2407dc310451bc523376eae1aa9c8d9"},
    "mel_custom": {
        "goa_melody_seed9_138bpm.mid":
            "0cd9ce75c7c79d722df406932ec3393a4f8336f5557d8a2606a198c8b4939ccc",
        "README.md": "953d87708d720c813ea397c28ea452c67c23198518bde8614180a62e67d13e6c"},
}

# What the user types into the form for each pinned run (field -> text; optionals switched on).
FORM_RUNS = {
    "mel_default": {"seed": "3"},
    "mel_custom": {
        "seed": "9", "bpm": "138", "root": "Bb", "scale": "aeolian", "length": "2",
        "density": "0.4", "register": "-1", "arp_pattern": "random", "progression": "0,5",
        "voices": "lead,arp", "sections": "Intro:4:0.3:lead,Peak:8:1:lead+arp"},
}

# Flags of the removed Goa-Arrangement mode (the goa_arrangement CLI still has them).
ARRANGEMENT_FLAGS = ("--roll=gallop", "--kick-preset=default", "--bass-preset=goa-roll-long",
                     "--intro-bars=8", "--breakdowns=1", "--outro=kick_less", "--dj-bars=16",
                     "--melody-voices=lead", "--no-samples")


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


def midi_track_names(data: bytes) -> list[str]:
    """Track names (meta 0x03 at tick 0) of every MTrk after the first (the conductor), read
    with a small SMF walker written here (not the project's MIDI writer)."""
    assert data[:4] == b"MThd"
    _len, fmt, ntrk, _ppq = struct.unpack(">IHHH", data[4:14])
    assert fmt == 1
    pos, names = 14, []
    for i in range(ntrk):
        assert data[pos:pos + 4] == b"MTrk"
        (size,) = struct.unpack(">I", data[pos + 4:pos + 8])
        body = data[pos + 8:pos + 8 + size]
        # first event: delta 0x00, FF 03 <len> <name>
        assert body[0] == 0 and body[1] == 0xFF and body[2] == 0x03, f"track {i}: no name"
        name = body[4:4 + body[3]].decode("ascii")
        if i:
            names.append(name)
        pos += 8 + size
    assert pos == len(data)
    return names


# --- every CLI option is in the form --------------------------------------------------------

def test_every_cli_option_has_a_form_field():
    parser = goa_melody.build_parser()
    cli = {a.dest: a.option_strings[0] for a in parser._actions
           if a.dest not in ("help", "out")}
    form = {s.dest: s.flag for s in GoaFormModel().specs}
    assert form == cli
    argv = GoaFormModel().argv("X")
    assert argv[0] == "--out=X"


def test_form_argv_with_every_optional_switched_on_is_accepted_by_the_cli_parser():
    m = GoaFormModel()
    for s in m.specs:
        if s.optional:
            m.set_active(s.dest, True)
            if s.kind == "enum":
                assert m.text[s.dest] == s.choices[0]
            elif s.dest in ("density", "register"):
                m.set_text(s.dest, "0" if s.dest == "register" else "0.5")
            elif s.dest == "sections":
                m.set_text(s.dest, "A:4:0.5:lead")
    assert m.evaluate().ok, m.evaluate().problem
    ns = goa.parse_argv(m.argv("X"))
    assert ns.out == "X"


# --- D-033: melody only ---------------------------------------------------------------------

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
    """D-033: the full-song arranger stays a CLI. No module of the GUI layers may import it
    (so no button, window or service can produce a Goa arrangement)."""
    files = sorted((SRC / "gui").rglob("*.py")) + sorted((SRC / "gui_core").rglob("*.py"))
    assert len(files) > 20
    hits = [str(p.relative_to(SRC)) for p in files
            if any(name.endswith("goa_arrangement") for name in _imports(p))]
    assert hits == []


def test_the_form_has_no_arrangement_or_drum_options():
    dests = {s.dest for s in GoaFormModel().specs}
    assert dests == {"seed", "bpm", "root", "scale", "length", "density", "register",
                     "arp_pattern", "progression", "voices", "sections"}
    assert GoaFormModel().spec("voices").choices == ("lead", "arp", "pad", "pluck")


@pytest.mark.parametrize("flag", ARRANGEMENT_FLAGS)
def test_arrangement_flags_are_refused_and_nothing_is_written(flag, tmp_path):
    out = tmp_path / "never"
    res = run_goa_job(GoaJob((f"--out={out}", flag)))
    assert res.error is not None and res.error.kind == "invalid_params"
    assert "Ungültige Option" in res.error.message
    assert not out.exists()


def test_rendered_midi_has_one_track_per_chosen_voice_and_no_samples(tmp_path):
    rng = random.Random(20261108)
    for i in range(6):
        voices = [v for v in ("lead", "arp", "pad", "pluck") if rng.random() < 0.6] or ["pad"]
        model = filled({"seed": str(rng.randrange(10**6)), "voices": ",".join(voices)})
        out = tmp_path / f"r{i}"
        res = run_goa_job(GoaJob(tuple(model.argv(str(out)))))
        assert res.ok, res.error
        assert sorted(p.name for p in out.iterdir()) == sorted([res.mid_path.name, "README.md"])
        assert midi_track_names(res.mid_path.read_bytes()) == voices


# --- byte identity --------------------------------------------------------------------------

@pytest.mark.parametrize("key", sorted(FORM_RUNS))
def test_form_render_matches_the_pinned_cli_hashes(key, tmp_path):
    model = filled(FORM_RUNS[key])
    out = tmp_path / "out"
    res = run_goa_job(GoaJob(tuple(model.argv(str(out)))))
    assert res.ok, res.error
    got = {p.name: sha(p) for p in out.iterdir() if p.is_file()}
    assert got == PINNED[key]
    assert res.readme_text == (out / "README.md").read_text(encoding="utf-8")
    assert res.mid_path.name in PINNED[key]


def test_whole_folder_equals_what_the_real_cli_main_writes(tmp_path):
    cli = tmp_path / "cli"
    assert goa_melody.main([f"--out={cli}", "--seed=2"]) == 0
    model = GoaFormModel()
    model.set_text("seed", "2")
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
    ("length", "0", "length"),
    ("sections", "A:4:2:lead", "energy"),
])
def test_out_of_range_options_are_refused_by_the_module_and_nothing_is_written(
        field, value, needle, tmp_path):
    model = filled({field: value})
    ev = model.evaluate()
    out = tmp_path / "never"
    res = run_goa_job(GoaJob(tuple(model.argv(str(out)))))
    assert not ev.ok
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

    monkeypatch.setattr(goa_melody, "write_melody", full)
    res = run_goa_job(GoaJob(tuple(model.argv(str(tmp_path / "x")))))
    assert res.error is not None and res.error.kind == "disk_full"

    def boom(*a, **k):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(goa_melody, "write_melody", boom)
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


# --- timeline vs the generator's plan data -------------------------------------------------

def test_default_timeline_has_the_known_literal_values():
    plan = GoaFormModel().evaluate().plan
    # goa_melody's default sections, written here as literals (elements in voice order)
    assert [(s.start_bar, s.bars, s.name, s.energy, s.elements) for s in plan.sections] == [
        (1, 8, "Intro", 0.3, ("pad",)), (9, 8, "Build", 0.6, ("arp", "pad", "pluck")),
        (17, 16, "Peak", 1.0, ("lead", "arp", "pad", "pluck")),
        (33, 8, "Break", 0.2, ("lead", "pad")),
        (41, 16, "Peak2", 1.0, ("lead", "arp", "pad", "pluck"))]
    assert plan.tracks == ("lead", "arp", "pad", "pluck") and plan.total_bars == 56
    assert abs(plan.minutes - 56 * 4 / 145) < 1e-9


def test_melody_timeline_comes_from_the_melody_sections():
    m = filled({"sections": "Intro:4:0.3:lead,Peak:8:1:lead+arp", "voices": "lead,arp"})
    plan = m.evaluate().plan
    assert [(s.start_bar, s.bars, s.name, s.energy, s.elements) for s in plan.sections] == [
        (1, 4, "Intro", 0.3, ("lead",)), (5, 8, "Peak", 1.0, ("lead", "arp"))]
    assert plan.tracks == ("lead", "arp") and plan.total_bars == 12
