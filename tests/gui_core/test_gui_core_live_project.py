"""#413: GUI renders outside a Live project are copied into the project before the import.

CI only, against the fake AbletonOSC server: nothing here talks to Ableton Live. The copy rules
(never overwrite, reuse an identical pair, remove the copy when nothing reached Live) are file
system behaviour and are checked here for real; what Live does with the file is not.
"""

from __future__ import annotations

import errno
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from live_helpers import config_for, make_fake, writes  # noqa: E402

from bridge.sample_info import read_sample_info  # noqa: E402
from gui_core import live  # noqa: E402
from gui_core.form import CATEGORY_KEYS, CategoryFormModel  # noqa: E402
from gui_core.render import RenderJob, run_job  # noqa: E402

CREATE_CLIP = "/live/clip_slot/create_audio_clip"
CREATE_TRACK = "/live/song/create_audio_track"
NO_ROOTS = ()  # pytest's temp folder lies inside the checkout
FOLDERS = {"kick": ("Samples", "Drums", "Kicks"), "clap": ("Samples", "Drums", "Claps"),
           "hat": ("Samples", "Drums", "Hats"), "snare": ("Samples", "Drums", "Snares"),
           "rim": ("Samples", "Drums", "Rims"), "bass": ("Samples", "Bass"),
           "laser": ("Samples", "FX", "Lasers")}  # written out, not taken from the layout


@pytest.fixture
def fake():
    server = make_fake()
    yield server
    server.close()


def render(cat: str, out: Path, seed: int = 1) -> Path:
    m = CategoryFormModel(cat)
    m.set_text("seed", str(seed))
    r = run_job(RenderJob(m.build_request(), out, m.preset, m.overrides(), cat))
    assert r.ok, r.error
    return r.files[0].wav_path


def project(tmp_path: Path) -> Path:
    p = tmp_path / "Test Project"
    p.mkdir()
    (p / "Test.als").write_bytes(b"")
    return p


def test_every_category_is_copied_into_its_folder_and_imported(fake, tmp_path):
    assert set(FOLDERS) == set(CATEGORY_KEYS)
    proj = project(tmp_path)
    cfg = config_for(fake, tmp_path)
    for n, cat in enumerate(sorted(CATEGORY_KEYS)):
        src = render(cat, tmp_path / "out")
        refused = live.inspect_live(cfg, src)  # no project: the bridge rule refuses, with help
        assert not refused.ok and "Live-Projektordner wählen" in refused.error
        plan = live.prepare_import(cfg, src, None, None, project_dir=proj,
                                   refused_roots=NO_ROOTS)
        assert plan.ok, plan.error
        target = proj.joinpath(*FOLDERS[cat], src.name)
        assert plan.path == str(target) and plan.placement.copy
        assert "kopieren" in plan.text and str(src) in plan.text and str(target) in plan.text
        assert not target.exists()  # planning writes nothing
        res = live.execute_import(cfg, plan, test_set_confirmed=True)
        assert res.ok, res.message
        assert str(target) in res.message
        assert target.read_bytes() == src.read_bytes()
        assert target.with_suffix(".json").read_bytes() == src.with_suffix(".json").read_bytes()
        assert read_sample_info(target).category == cat
        assert writes(fake)[-2:] == [(CREATE_TRACK, (-1,)), (CREATE_CLIP, (3 + n, 0, str(target)))]


def test_a_file_already_in_its_project_folder_is_imported_in_place(fake, tmp_path):
    proj = project(tmp_path)
    src = render("kick", proj / "Samples" / "Drums" / "Kicks")
    plan = live.prepare_import(config_for(fake, tmp_path), src, 2, 0)  # no project needed
    assert plan.ok and plan.path == str(src) and not plan.placement.moved
    assert "kopieren" not in plan.text


def test_second_import_reuses_the_identical_copy_and_a_different_file_gets_a_new_name(
        fake, tmp_path):
    proj = project(tmp_path)
    cfg = config_for(fake, tmp_path)
    src = render("hat", tmp_path / "out")
    first = live.prepare_import(cfg, src, 2, 0, project_dir=proj, refused_roots=NO_ROOTS)
    assert live.execute_import(cfg, first, True).ok
    again = live.prepare_import(cfg, src, 2, 1, project_dir=proj, refused_roots=NO_ROOTS)
    assert again.ok and again.path == first.path and not again.placement.copy
    assert "schon unverändert im Projektordner" in again.text
    assert live.execute_import(cfg, again, True).ok
    # another render under the same file name (other output folder, other seed, renamed)
    rendered = render("hat", tmp_path / "out2", seed=9)
    other = rendered.with_name(src.name)
    meta = json.loads(rendered.with_suffix(".json").read_text(encoding="utf-8"))
    meta["file"] = other.name
    other.with_suffix(".json").write_text(json.dumps(meta), encoding="utf-8")
    rendered.rename(other)
    rendered.with_suffix(".json").unlink()
    assert other.read_bytes() != src.read_bytes()
    third = live.prepare_import(cfg, other, 2, 2, project_dir=proj, refused_roots=NO_ROOTS)
    assert third.ok and Path(third.path).name == f"{src.stem}_002.wav"
    assert live.execute_import(cfg, third, True).ok
    copy = Path(third.path)
    assert copy.read_bytes() == other.read_bytes()
    assert Path(first.path).read_bytes() == src.read_bytes()  # the first copy is untouched
    meta = json.loads(copy.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["file"] == copy.name
    assert read_sample_info(copy).category == "hat"


def test_copy_is_removed_when_nothing_reached_live(fake, tmp_path):
    proj = project(tmp_path)
    cfg = config_for(fake, tmp_path)
    src = render("clap", tmp_path / "out")
    plan = live.prepare_import(cfg, src, 2, 1, project_dir=proj, refused_roots=NO_ROOTS)
    fake.tracks[2]["slots"][2] = "C:\\someone_else.wav"  # the set changed after the plan
    res = live.execute_import(cfg, plan, True)
    assert not res.ok and not res.writes_sent and writes(fake) == []
    assert "wieder gelöscht" in res.message
    target = Path(plan.path)
    assert not target.exists() and not target.with_suffix(".json").exists()
    assert src.is_file()  # the original is never touched


def test_a_file_that_appeared_at_the_target_is_never_overwritten(fake, tmp_path):
    proj = project(tmp_path)
    cfg = config_for(fake, tmp_path)
    src = render("rim", tmp_path / "out")
    plan = live.prepare_import(cfg, src, 2, 0, project_dir=proj, refused_roots=NO_ROOTS)
    target = Path(plan.path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"someone else's file")  # appears between plan and import
    res = live.execute_import(cfg, plan, True)
    assert not res.ok and "Kopieren in den Projektordner fehlgeschlagen" in res.message
    assert "nichts in Live geändert" in res.message and writes(fake) == []
    assert target.read_bytes() == b"someone else's file"
    assert not target.with_suffix(".json").exists()  # our sidecar was removed again


def test_disk_full_during_the_copy_leaves_no_half_pair(fake, tmp_path, monkeypatch):
    proj = project(tmp_path)
    cfg = config_for(fake, tmp_path)
    src = render("bass", tmp_path / "out")
    plan = live.prepare_import(cfg, src, 2, 0, project_dir=proj, refused_roots=NO_ROOTS)

    def full(_fin, _fout):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(live.shutil, "copyfileobj", full)
    res = live.execute_import(cfg, plan, True)
    assert not res.ok and "No space left" in res.message and writes(fake) == []
    target = Path(plan.path)
    assert not target.exists() and not target.with_suffix(".json").exists()


@pytest.mark.parametrize("make,needle", [
    (lambda tmp: tmp / "nope", "gibt es nicht"),
    (lambda tmp: tmp, "keine .als-Datei"),
    (lambda tmp: "relative", "voller Pfad"),
])
def test_bad_project_folders_are_refused_with_a_reason_and_nothing_is_written(
        fake, tmp_path, make, needle):
    src = render("kick", tmp_path / "out")
    before = sorted(tmp_path.rglob("*"))
    res = live.prepare_import(config_for(fake, tmp_path), src, 2, 0, project_dir=make(tmp_path),
                              refused_roots=NO_ROOTS)
    assert not res.ok and needle in res.error, res.error
    assert fake.payload() == [] and sorted(tmp_path.rglob("*")) == before


def test_project_inside_the_checkout_is_refused_by_default(fake, tmp_path):
    proj = project(tmp_path)  # tmp_path lies in the checkout (--basetemp)
    src = render("kick", tmp_path / "out")
    roots = live.default_refused_roots()
    if not roots or not proj.resolve().is_relative_to(roots[0]):
        pytest.skip("temp folder is not inside the checkout here")
    res = live.prepare_import(config_for(fake, tmp_path), src, 2, 0, project_dir=proj)
    assert not res.ok and "AbeltonGod-Ordner" in res.error


def test_without_a_verified_checkout_no_root_is_refused(monkeypatch):
    assert live.default_refused_roots() in ((live.CHECKOUT_ROOT,), ())
    monkeypatch.setattr(live, "checkout_problem", lambda _root: "no checkout (exe)")
    assert live.default_refused_roots() == ()


def test_other_sidecar_problems_keep_the_bridge_refusal(fake, tmp_path):
    proj = project(tmp_path)
    src = render("kick", tmp_path / "out")
    side = src.with_suffix(".json")
    side.write_text(json.dumps({"category": "nope"}), encoding="utf-8")
    res = live.prepare_import(config_for(fake, tmp_path), src, 2, 0, project_dir=proj,
                              refused_roots=NO_ROOTS)
    assert not res.ok and "nicht importierbar" in res.error
    assert not (proj / "Samples").exists()
