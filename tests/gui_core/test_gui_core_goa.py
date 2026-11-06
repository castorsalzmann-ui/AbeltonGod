"""Goa service layer (no Qt): option coverage, byte identity with the CLIs, error objects, the
timeline against the generator's plan data."""

from __future__ import annotations

import errno
import hashlib
import json
import random
from pathlib import Path

import pytest

from audio_engine import goa_arrangement, goa_melody
from gui_core import goa
from gui_core.goa import ARRANGEMENT, MELODY, GoaFormModel
from gui_core.goa_render import GoaJob, GoaService, run_goa_job

# sha256 of the CLI output, pinned as literals (made with `python -m audio_engine.goa_*` on the
# argument lists below, not with the code under test).
PINNED = {
    "arr_default": {
        "goa_seed1_145bpm.mid": "ed6118d21ad392474c0422b4d12ed8f2fa4ca585c47918673b5f149a1dc9fb79",
        "README.md": "376510c4af42786c49ee957589d4905a7bb1ed01cc15eebcb1c43095d909974e"},
    "arr_custom": {
        "goa_seed7_140bpm.mid": "8ee29352aff1445051f27886fa389bee96bf81cd741bc83d12e495c58715a331",
        "README.md": "5b8e157960a00b257d11ff3afa9d2ab9e07f1aaea61becae86c8f1b9c15b2649"},
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
    "arr_default": (ARRANGEMENT, {"seed": "1", "no_samples": "ja"}),
    "arr_custom": (ARRANGEMENT, {
        "seed": "7", "bpm": "140", "root": "F#", "scale": "harmonic_minor", "roll": "gallop",
        "intro_bars": "8", "breakdowns": "1", "outro": "kick_less", "outro_bars": "16",
        "dj_bars": "16", "snare_preset": "none", "clap_pattern": "sixteenth_offbeat",
        "melody_voices": "lead,pad", "density": "lead=0.5,pad=0.2",
        "register": "lead=1,pad=-1", "arp_pattern": "updown", "progression": "0,3,4,0",
        "no_samples": "ja"}),
    "mel_default": (MELODY, {"seed": "3"}),
    "mel_custom": (MELODY, {
        "seed": "9", "bpm": "138", "root": "Bb", "scale": "aeolian", "length": "2",
        "density": "0.4", "register": "-1", "arp_pattern": "random", "progression": "0,5",
        "voices": "lead,arp", "sections": "Intro:4:0.3:lead,Peak:8:1:lead+arp"}),
}


def filled(mode: str, values: dict[str, str]) -> GoaFormModel:
    m = GoaFormModel(mode)
    for dest, text in values.items():
        if m.spec(dest).optional:
            m.set_active(dest, True)
        m.set_text(dest, text)
    return m


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree(root: Path) -> dict[str, object]:
    """Every file's bytes; a sample sidecar (#414) without its wall-clock ``created_at``."""
    out: dict[str, object] = {}
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix == ".json":
            out[str(p.relative_to(root))] = {**json.loads(p.read_text(encoding="utf-8")),
                                             "created_at": None}
        else:
            out[str(p.relative_to(root))] = p.read_bytes()
    return out


# --- every CLI option is in the form --------------------------------------------------------

@pytest.mark.parametrize("mode,module", [(ARRANGEMENT, goa_arrangement), (MELODY, goa_melody)])
def test_every_cli_option_has_a_form_field(mode, module):
    actions = [a for a in module.build_parser()._actions if a.dest not in ("help", "out")]
    cli = {a.dest: a.option_strings[0] for a in actions}
    form = {s.dest: s.flag for s in GoaFormModel(mode).specs}
    assert cli == form  # nothing missing, nothing invented
    assert len(cli) >= 11
    argv = GoaFormModel(mode).argv("X")
    assert "--out=X" in argv


def test_form_argv_with_every_optional_switched_on_is_accepted_by_the_cli_parser():
    for mode in goa.MODES:
        m = GoaFormModel(mode)
        for s in m.specs:
            if s.optional:
                m.set_active(s.dest, True)
                if s.kind == "enum":
                    assert m.text[s.dest] == s.choices[0]
                elif s.dest in ("density", "register"):
                    m.set_text(s.dest, "0" if s.dest == "register" else "0.5")
                elif s.dest == "progression":
                    m.set_text(s.dest, "0,5,6,4")
                elif s.dest == "sections":
                    m.set_text(s.dest, "A:4:0.5:lead")
        assert m.evaluate().ok, m.evaluate().problem
        ns = goa.parse_argv(mode, m.argv("X"))
        assert ns.out == "X"


# --- byte identity --------------------------------------------------------------------------

@pytest.mark.parametrize("key", sorted(FORM_RUNS))
def test_form_render_matches_the_pinned_cli_hashes(key, tmp_path):
    mode, values = FORM_RUNS[key]
    model = filled(mode, values)
    out = tmp_path / "out"
    res = run_goa_job(GoaJob(mode, tuple(model.argv(str(out)))))
    assert res.ok, res.error
    got = {p.name: sha(p) for p in out.iterdir() if p.is_file()}
    assert got == PINNED[key]
    assert res.readme_text == (out / "README.md").read_text(encoding="utf-8")
    assert res.mid_path.name in PINNED[key]


@pytest.mark.parametrize("mode,module,extra", [
    (ARRANGEMENT, goa_arrangement, ["--seed=2"]),  # with samples: every file incl. the WAVs
    (MELODY, goa_melody, ["--seed=2"]),
])
def test_whole_folder_equals_what_the_real_cli_main_writes(mode, module, extra, tmp_path):
    cli = tmp_path / "cli"
    assert module.main([f"--out={cli}", *extra]) == 0
    model = GoaFormModel(mode)
    model.set_text("seed", "2")
    gui = tmp_path / "gui"
    res = run_goa_job(GoaJob(mode, tuple(model.argv(str(gui)))))
    assert res.ok and tree(gui) == tree(cli)
    if mode == ARRANGEMENT:
        assert len(res.sample_paths) == 6 and all(p.suffix == ".wav" for p in res.sample_paths)


# --- errors ---------------------------------------------------------------------------------

@pytest.mark.parametrize("mode,field,value,needle", [
    (ARRANGEMENT, "bpm", "200", "bpm must be"),
    (ARRANGEMENT, "bpm", "130", "bpm must be"),
    (ARRANGEMENT, "density", "2", "density"),
    (ARRANGEMENT, "register", "5", "register"),
    (ARRANGEMENT, "progression", "0,9", "progression"),
    (ARRANGEMENT, "melody_voices", "", ""),  # empty list is legal for the generator
    (MELODY, "length", "40", "length"),
    (MELODY, "root", "H", "root"),
    (MELODY, "sections", "oops", "section"),
    (MELODY, "voices", "lead,lead", ""),
])
def test_out_of_range_options_are_refused_by_the_module_and_nothing_is_written(
        mode, field, value, needle, tmp_path):
    model = filled(mode, {field: value})
    ev = model.evaluate()
    out = tmp_path / "never"
    res = run_goa_job(GoaJob(mode, tuple(model.argv(str(out)))))
    if ev.ok:  # accepted by the generator: then the render also works
        assert res.ok
        return
    assert needle in ev.problem and ev.problem.startswith("Ungültige")
    assert res.error is not None and res.error.kind == "invalid_params"
    assert needle in res.error.message and res.error.detail
    assert not out.exists()


def test_syntax_problems_are_marked_per_field_and_block_the_plan():
    m = GoaFormModel(ARRANGEMENT)
    m.set_text("bpm", "schnell")
    m.set_text("seed", "1.5")
    assert set(m.field_issues()) == {"bpm", "seed"}
    ev = m.evaluate()
    assert not ev.ok and ev.plan is None and ev.problem.startswith("Seed:")
    m.set_text("bpm", "145")
    m.set_text("seed", "3")
    assert m.field_issues() == {} and m.evaluate().ok


def test_switching_an_optional_field_off_ignores_its_bad_text():
    m = filled(ARRANGEMENT, {"density": "banana"})
    assert not m.evaluate().ok
    m.set_active("density", False)
    assert m.evaluate().ok and not any(a.startswith("--density") for a in m.argv())


def test_an_existing_target_is_never_overwritten(tmp_path):
    model = filled(ARRANGEMENT, {"seed": "1", "no_samples": "ja"})
    out = tmp_path / "out"
    first = run_goa_job(GoaJob(ARRANGEMENT, tuple(model.argv(str(out)))))
    assert first.ok
    before = tree(out)
    second = run_goa_job(GoaJob(ARRANGEMENT, tuple(model.argv(str(out)))))
    assert second.error is not None and second.error.kind == "exists"
    assert "Es wurde nichts überschrieben" in second.error.message
    assert tree(out) == before


def test_unwritable_folder_and_full_disk_are_error_objects(tmp_path, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    model = filled(ARRANGEMENT, {"no_samples": "ja"})
    res = run_goa_job(GoaJob(ARRANGEMENT, tuple(model.argv(str(blocker / "sub")))))
    assert res.error is not None and res.error.kind == "output" and not res.ok

    def full(*a, **k):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(goa_arrangement, "write_track", full)
    res = run_goa_job(GoaJob(ARRANGEMENT, tuple(model.argv(str(tmp_path / "x")))))
    assert res.error is not None and res.error.kind == "disk_full"

    def boom(*a, **k):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(goa_arrangement, "write_track", boom)
    res = run_goa_job(GoaJob(ARRANGEMENT, tuple(model.argv(str(tmp_path / "y")))))
    assert res.error is not None and res.error.kind == "internal" and "kaputt" in res.error.message


def test_no_output_folder_is_an_error_object():
    res = run_goa_job(GoaJob(ARRANGEMENT, ("--out=",)))
    assert res.error is not None and "Ausgabeordner" in res.error.message


def test_service_runs_in_a_thread_and_always_finishes(tmp_path):
    model = filled(ARRANGEMENT, {"no_samples": "ja"})
    seen = []
    h = GoaService().start(GoaJob(ARRANGEMENT, tuple(model.argv(str(tmp_path / "o")))),
                           seen.append)
    assert h.wait(30) and h.result.ok and seen and seen[0].ok

    def crash(job):
        raise RuntimeError("x")

    h = GoaService(crash).start(GoaJob(ARRANGEMENT, ()))
    assert h.wait(30) and h.result.error.kind == "internal"


# --- timeline vs the generator's plan data -------------------------------------------------

def test_default_timeline_has_the_known_literal_values():
    plan = GoaFormModel(ARRANGEMENT).evaluate().plan
    assert plan.total_bars == 224 and len(plan.sections) == 19
    first, last = plan.sections[0], plan.sections[-1]
    assert (first.start_bar, first.bars, first.name, first.energy, first.elements) == (
        1, 8, "Intro", 0.30, ("kick", "bass"))
    b1 = next(s for s in plan.sections if s.name == "Break 1")
    assert (b1.start_bar, b1.bars, b1.energy, b1.elements) == (73, 16, 0.30, ("arp", "pad"))
    assert (last.start_bar, last.bars, last.name) == (217, 8, "Outro")
    assert plan.tracks[:7] == ("kick", "bass", "lead", "arp", "pad", "pluck", "perc")
    assert abs(plan.minutes - 224 * 4 / 145) < 1e-9


def test_timeline_equals_the_generator_sections_for_random_options():
    rng = random.Random(20261105)
    for _ in range(25):
        voices = [v for v in ("lead", "arp", "pad", "pluck") if rng.random() < 0.6]
        vals = {
            "seed": str(rng.randrange(0, 10**6)),
            "bpm": repr(round(rng.uniform(135, 150), 2)),
            "root": rng.choice(goa_arrangement.ROOT_NAMES),
            "intro_bars": str(rng.choice((0, 8, 16, 24, 32))),
            "breakdowns": str(rng.choice((0, 1, 2))),
            "outro": rng.choice(("kick_on", "kick_less")),
            "outro_bars": str(rng.choice((8, 16, 24, 32))),
            "dj_bars": str(rng.choice((0, 8, 16, 24, 32))),
            "melody_voices": ",".join(voices),
        }
        model = filled(ARRANGEMENT, vals)
        plan = model.evaluate().plan
        assert plan is not None, model.evaluate().problem
        # independent expectation, written here from the documented plan (224 bars default)
        b, intro = int(vals["breakdowns"]), int(vals["intro_bars"])
        expected_bars = (224 - (24 if b < 2 else 0) - (16 if b < 1 else 0) + intro
                         + (int(vals["outro_bars"]) - 8) + 2 * int(vals["dj_bars"]))
        assert plan.total_bars == expected_bars
        starts = [s.start_bar for s in plan.sections]
        assert starts[0] == 1
        assert all(starts[i + 1] == starts[i] + plan.sections[i].bars
                   for i in range(len(starts) - 1))
        played = {e for s in plan.sections for e in s.elements}
        for v in ("lead", "arp", "pad", "pluck"):
            if v not in voices:
                assert v not in played
            assert (v in plan.tracks) == (v in voices)
        # and the same numbers as the generator's own arrangement dict
        call = goa.call_of(ARRANGEMENT, goa.parse_argv(ARRANGEMENT, model.argv("X")))
        arr = goa_arrangement.build_arrangement(**call.kwargs)
        assert [(s.name, s.bars, s.energy, s.elements) for s in plan.sections] == [
            (s["name"], s["bars"], s["energy"], tuple(s["elements"])) for s in arr["sections"]]
        assert plan.tempo == arr["tempo"]


def test_melody_timeline_comes_from_the_melody_sections():
    m = filled(MELODY, {"sections": "Intro:4:0.3:lead,Peak:8:1:lead+arp", "voices": "lead,arp"})
    plan = m.evaluate().plan
    assert [(s.start_bar, s.bars, s.name, s.energy, s.elements) for s in plan.sections] == [
        (1, 4, "Intro", 0.3, ("lead",)), (5, 8, "Peak", 1.0, ("lead", "arp"))]
    assert plan.tracks == ("lead", "arp") and plan.total_bars == 12
