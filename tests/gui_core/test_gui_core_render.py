"""Render service: same bytes as the CLI, errors as result objects, no hangs (no Qt)."""

from __future__ import annotations

import errno
import hashlib
import io
import json
import re
import threading
from pathlib import Path

import pytest

from audio_engine import cli
from audio_engine.io import write_kick
from gui_core.form import KickFormModel
from gui_core.render import RenderJob, RenderService, run_job

# sha256 of the WAVs written by `python -m audio_engine.kick` (run once on Linux/Python 3.13,
# see PR): --preset punchy --variants 2 --seed 42, and --preset punchy --seed 7 --set drive=0.5.
PUNCHY_S42 = (
    "47824200b3d4e4a67d36abbe3473124153738b00dea533322596dfabff6ecd36",
    "9144df7dd5b3f64fc1e2647db429c4afce31b652bf40ad46bd9100ba07cabf7b",
)
PUNCHY_S7_DRIVE = "b59bf515e5e9ea34448fbd09bdc00ce9a73171dffc506246d0ddde3ff72fd807"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def job_from_form(m: KickFormModel, out: Path) -> RenderJob:
    return RenderJob(m.build_request(), out, m.preset, m.overrides())


def form(seed: int | None = None, variants: int = 1, **fields) -> KickFormModel:
    m = KickFormModel("punchy")
    if seed is not None:
        m.set_text("seed", str(seed))
    m.set_text("variants", str(variants))
    for k, v in fields.items():
        m.set_text(k, str(v))
    return m


def test_same_params_and_seed_give_the_bytes_of_the_cli(tmp_path):
    result = run_job(job_from_form(form(42, 2), tmp_path / "gui"))
    assert result.ok and len(result.files) == 2
    assert [sha(f.wav_path) for f in result.files] == list(PUNCHY_S42)
    assert [f.wav_path.name for f in result.files] == ["kick_punchy_s42_v0.wav",
                                                       "kick_punchy_s42_v1.wav"]
    # #443: in the kick folder of the project-shaped output tree
    assert {f.wav_path.parent for f in result.files} == {
        tmp_path / "gui" / "Samples" / "Drums" / "Kicks"}

    # Independent route: the real CLI entry point, compared byte for byte.
    cli_out = tmp_path / "cli"
    code = cli.main(
        ["--preset", "punchy", "--variants", "2", "--seed", "42", "--out", str(cli_out)],
        stdout=io.StringIO(), stderr=io.StringIO(),
    )
    assert code == 0
    for f in result.files:
        cli_name = f.wav_path.name.removeprefix("kick_")  # #443: GUI adds the category
        assert f.wav_path.read_bytes() == (cli_out / cli_name).read_bytes()
        # sidecar: identical bytes except the creation time stamp and the file name
        def body(p: Path) -> str:
            text = re.sub(r'"created_at": "[^"]*"', "", p.read_text(encoding="utf-8"))
            return re.sub(r'"file": "[^"]*"', "", text)

        assert body(f.json_path) == body(cli_out / cli_name.replace(".wav", ".json"))


def test_overrides_match_cli_set_and_are_named_custom(tmp_path):
    result = run_job(job_from_form(form(7, drive="0,5"), tmp_path / "gui"))
    assert result.ok
    [f] = result.files
    assert f.wav_path.name == "kick_punchy_s7_v0_custom.wav"
    assert sha(f.wav_path) == PUNCHY_S7_DRIVE
    assert f.seed == 7
    assert f.peak_dbfs == pytest.approx(-0.3, abs=0.01)
    meta = json.loads(f.json_path.read_text(encoding="utf-8"))
    assert meta["parameters"]["drive"] == 0.5
    assert "drive=0.5" in meta["description"]


def test_every_category_gets_its_folder_and_a_name_with_its_category(tmp_path):
    """#443: one default render per category into one output folder: no counter suffix, the
    category in the name, the project layout's folder (written out here, not taken from the
    layout object)."""
    from gui_core.form import CATEGORY_KEYS, CategoryFormModel
    folders = {"kick": "Samples/Drums/Kicks", "clap": "Samples/Drums/Claps",
               "hat": "Samples/Drums/Hats", "snare": "Samples/Drums/Snares",
               "rim": "Samples/Drums/Rims", "bass": "Samples/Bass",
               "laser": "Samples/FX/Lasers"}
    assert set(folders) == set(CATEGORY_KEYS)
    out = tmp_path / "out"
    for cat in ("snare", "bass", *sorted(set(CATEGORY_KEYS) - {"snare", "bass"})):
        m = CategoryFormModel(cat)
        m.set_text("seed", "1")
        m.set_text("variants", "1")
        r = run_job(RenderJob(m.build_request(), out, m.preset, m.overrides(), cat))
        assert r.ok, r.error
        [f] = r.files
        assert f.wav_path.parent == out / folders[cat]
        assert f.wav_path.name == f"{cat}_{m.preset}_s1_v0.wav"
        assert f.json_path == f.wav_path.with_suffix(".json")


def test_second_run_never_overwrites(tmp_path):
    out = tmp_path / "o"
    a = run_job(job_from_form(form(5), out))
    b = run_job(job_from_form(form(5), out))
    assert a.ok and b.ok
    assert a.files[0].wav_path != b.files[0].wav_path
    assert b.files[0].wav_path.name == "kick_punchy_s5_v0_002.wav"
    assert a.files[0].wav_path.read_bytes() == b.files[0].wav_path.read_bytes()


def test_invalid_params_return_an_error_and_write_nothing(tmp_path):
    out = tmp_path / "never"
    req = form(1).build_request()
    req["drive"] = 7  # out of range: the form would refuse it, the service must too
    result = run_job(RenderJob(req, out, "punchy"))
    assert not result.ok and result.files == ()
    assert result.error and result.error.kind == "invalid_params"
    assert "drive" in result.error.message
    assert not out.exists()


def test_empty_output_folder_is_an_error(tmp_path):
    result = run_job(RenderJob(form(1).build_request(), Path(""), "punchy"))
    assert not result.ok and result.error.kind == "invalid_params"


def test_disk_full_on_second_variant_keeps_first_and_reports(tmp_path):
    calls = {"n": 0}

    def full_disk(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError(errno.ENOSPC, "No space left on device")
        return write_kick(*a, **kw)

    result = run_job(job_from_form(form(3, 3), tmp_path), writer=full_disk)
    assert not result.ok and not result.cancelled
    assert result.error.kind == "disk_full"
    assert "1 von 3" in result.error.message
    assert len(result.files) == 1 and result.files[0].wav_path.exists()


def test_unwritable_output_folder(tmp_path):
    blocker = tmp_path / "file.txt"
    blocker.write_text("x")
    result = run_job(job_from_form(form(1), blocker / "sub"))
    assert not result.ok and result.error.kind == "output"
    assert result.files == ()


def test_cancel_between_variants_is_not_success(tmp_path):
    cancel = threading.Event()
    result = run_job(
        job_from_form(form(9, 4), tmp_path), cancel=cancel,
        progress=lambda done, total: cancel.set() if done == 1 else None,
    )
    assert result.cancelled and not result.ok and result.error is None
    assert len(result.files) == 1


def test_cancel_before_start_writes_nothing(tmp_path):
    cancel = threading.Event()
    cancel.set()
    result = run_job(job_from_form(form(9, 2), tmp_path / "x"), cancel=cancel)
    assert result.cancelled and result.files == () and not (tmp_path / "x").exists()


def test_progress_reports_every_file(tmp_path):
    seen = []
    result = run_job(job_from_form(form(2, 3), tmp_path), progress=lambda d, t: seen.append((d, t)))
    assert result.ok and seen == [(1, 3), (2, 3), (3, 3)]


def test_service_runs_in_a_thread_and_always_finishes(tmp_path):
    done = []
    handle = RenderService().start(job_from_form(form(4), tmp_path), on_done=done.append)
    assert handle.wait(30) and handle.done
    assert handle.result.ok and done == [handle.result]


def test_unexpected_engine_error_becomes_an_error_object_not_a_hang(tmp_path):
    def boom(*a, **kw):
        raise RuntimeError("engine exploded")

    handle = RenderService(writer=boom).start(job_from_form(form(4), tmp_path))
    assert handle.wait(30)
    assert not handle.result.ok and handle.result.error.kind == "internal"
    assert "engine exploded" in handle.result.error.message


def test_run_job_itself_never_raises_on_engine_errors(tmp_path):
    def boom(*a, **kw):
        raise RuntimeError("engine exploded")

    result = run_job(job_from_form(form(4), tmp_path), writer=boom)
    assert not result.ok and result.error.kind == "internal"


def test_broken_callback_does_not_stop_the_handle(tmp_path):
    def bad(_):
        raise RuntimeError("callback bug")

    handle = RenderService().start(job_from_form(form(4), tmp_path), on_done=bad)
    assert handle.wait(30) and handle.result.ok


def test_service_cancel_through_the_handle(tmp_path):
    holder = []

    def cancelling(*a, **kw):
        while not holder:  # handle is stored right after start() returns
            threading.Event().wait(0.01)
        holder[0].cancel()
        return write_kick(*a, **kw)

    handle = RenderService(writer=cancelling).start(job_from_form(form(4, 3), tmp_path))
    holder.append(handle)
    assert handle.wait(30)
    assert handle.result.cancelled and not handle.result.ok
    assert len(handle.result.files) == 1  # the variant in flight finishes, the rest is skipped


def test_refused_render_messages_are_german():
    """W1 polish: the main window's status for a refused render is German; an engine message
    without a translation is marked as the engine's own (English) text."""
    from audio_engine.presets import UnknownPresetError
    from gui_core.render import _first_line

    silent = ValueError("Render is silent (peak 0); refusing to write a WAV and sidecar.")
    assert _first_line(silent) == ("Das Ergebnis wäre stumm (Spitze 0); es wurde nichts "
                                   "geschrieben.")
    assert _first_line(UnknownPresetError("nope")).startswith("Unbekanntes Preset. ")
    other = _first_line(ValueError("drive must be 0-1\nsecond line"))
    assert other == "Ungültige Parameter (Meldung der Engine, englisch): drive must be 0-1 " \
                    "second line"
