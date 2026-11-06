"""GUI tour (#437): every page and window, one render per category plus Goa, Acid and Blaster,
each result looked up in the main window's library. Offscreen, silent backend, all default
paths in a temp folder (``scripts/qa/gui_tour.py``). Known gaps are xfail(strict=True) with
their issue number, so a fix turns the test red until the gap entry is removed.

Nothing here is evidence for the look on a real Windows screen, the sound, or Live (the Live
step runs against the fake AbletonOSC server of tests/bridge)."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

if os.environ.get("ABELTONGOD_REQUIRE_GUI") == "1":  # CI: a missing Qt must fail, not skip
    import PySide6.QtWidgets  # noqa: F401
else:
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtGui import QImage  # noqa: E402

from gui.main_window import TOOL_PAGES  # noqa: E402
from gui_core.categories import CATEGORIES, LIBRARY_LABEL  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TOUR_PY = ROOT / "scripts" / "qa" / "gui_tour.py"


def _load(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


tour_mod = _load("gui_tour", TOUR_PY)
sys.path.insert(0, str(ROOT / "tests" / "gui_core"))
from live_helpers import config_for, make_fake, writes  # noqa: E402

PAGE_LABELS = [c.label for c in CATEGORIES] + [LIBRARY_LABEL] + [t[1] for t in TOOL_PAGES]
PAGE_STEPS = [f"page:{tour_mod._slug(label)}" for label in PAGE_LABELS]
RENDER_STEPS = ([f"render:{k}" for k in tour_mod.CATEGORY_KEYS]
                + ["render:goa-page", "render:goa-window", "render:acid",
                   "render:blaster-shot", "render:blaster-bank"])
WINDOW_STEPS = [f"open:{k}" for k in tour_mod.TOOL_KEYS]
FIT_KEYS = ("main", *tour_mod.TOOL_KEYS)


def _param(name: str):
    issue = tour_mod.KNOWN_GAPS.get(name)
    if issue is None:
        return name
    return pytest.param(name, marks=pytest.mark.xfail(
        strict=True, reason=f"GUI gap #{issue}"), id=name)


@pytest.fixture(scope="module")
def tour(tmp_path_factory):
    """One tour per worker (about 4-9 s); the window is closed inside, only data is kept."""
    home = tmp_path_factory.mktemp("tour_home")
    shots = tmp_path_factory.mktemp("tour_shots")
    return tour_mod.run_tour(home, shots, "100")


def test_the_tour_visits_exactly_the_expected_steps(tour):
    names = [s.name for s in tour.steps]
    expected = (PAGE_STEPS + RENDER_STEPS[:8] + WINDOW_STEPS + RENDER_STEPS[8:]
                + ["close:tools-with-main"])
    assert names == expected


@pytest.mark.parametrize("name", [_param(n) for n in PAGE_STEPS])
def test_every_main_window_page_shows(tour, name):
    step = tour.step(name)
    assert step.ok, step.detail


@pytest.mark.parametrize("name", [_param(n) for n in RENDER_STEPS])
def test_render_lands_in_the_library(tour, name):
    step = tour.step(name)
    assert step.ok, step.detail


@pytest.mark.parametrize("name", [_param(n) for n in WINDOW_STEPS + ["close:tools-with-main"]])
def test_tool_windows_open_and_close_with_the_main_window(tour, name):
    step = tour.step(name)
    assert step.ok, step.detail


@pytest.mark.xfail(strict=True, reason="GUI gap #443: snare and bass default names collide")
def test_category_names_do_not_collide(tour):
    """One render per category into a fresh folder must not need a counter suffix."""
    names = [tour.step(f"render:{k}").detail for k in tour_mod.CATEGORY_KEYS]
    assert not [n for n in names if re.search(r"_\d{3}\.wav$", n)], names


def test_screenshots_of_every_page_and_window_at_100_percent(tour):
    names = sorted(p.name for p in tour.shots)
    assert len(names) == len(PAGE_STEPS) + len(tour_mod.TOOL_KEYS), names
    for p in tour.shots:
        img = QImage(str(p))
        assert not img.isNull() and img.width() >= 300 and img.height() >= 200, p.name


@pytest.fixture(scope="module")
def tour150(tmp_path_factory, tour):
    """The 150 % pass in a child process (the scale factor is fixed when Qt starts)."""
    out = tmp_path_factory.mktemp("tour150")
    report = out / "report.json"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / "src")] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    proc = subprocess.run(
        [sys.executable, str(TOUR_PY), "--scale", "1.5", "--no-renders",
         "--shots", str(out / "shots"), "--json", str(report)],
        capture_output=True, text=True, env=env, timeout=300)
    assert report.is_file(), proc.stdout + proc.stderr
    data = json.loads(report.read_text(encoding="utf-8"))
    data["returncode"] = proc.returncode
    data["stdout"] = proc.stdout
    return data


def test_150_percent_pass_has_every_page_and_window_at_one_and_a_half_pixels(tour, tour150):
    assert tour150["returncode"] == 0, tour150["stdout"]
    shots150 = {Path(p).name.split("_", 1)[1]: Path(p) for p in tour150["shots"]}
    shots100 = {p.name.split("_", 1)[1]: p for p in tour.shots}
    assert set(shots150) == set(shots100)
    for name, p in shots100.items():
        a, b = QImage(str(p)), QImage(str(shots150[name]))
        if name.startswith("window_blaster"):
            continue  # clamps itself to the (smaller logical) screen: checked by fit:blaster
        assert abs(b.width() - 1.5 * a.width()) <= 2 and abs(b.height() - 1.5 * a.height()) <= 2, (
            name, a.size(), b.size())


@pytest.mark.parametrize("name", [_param(f"fit:{k}@150") for k in FIT_KEYS])
def test_windows_fit_a_1080p_screen_at_150_percent(tour150, name):
    """Emulated 1920 x 1080 monitor at 150 % = 1280 x 720 logical px (no title or task bar)."""
    step = next(s for s in tour150["steps"] if s["name"] == name)
    assert step["ok"], step["detail"]
    assert "on a 1280 x 720 screen" in step["detail"]  # the emulated screen was really used


def test_screenshots_never_go_into_the_repo(tmp_path):
    assert not tour_mod.shots_allowed(ROOT / "shots")
    assert not tour_mod.shots_allowed(ROOT / "docs" / "qa")
    assert tour_mod.shots_allowed(ROOT / ".pytest_tmp" / "shots")  # git-ignored test temp
    assert tour_mod.shots_allowed(tmp_path / "shots") or tmp_path.is_relative_to(ROOT)
    assert tour_mod.main(["--scale", "1", "--shots", str(ROOT / "shots")]) == 2
    assert not (ROOT / "shots").exists()


# --- steps with their own window -------------------------------------------------------------

@pytest.fixture
def home(tmp_path):
    with tour_mod.isolated_env(tmp_path):
        yield tmp_path


@pytest.mark.xfail(strict=True, reason="GUI gap #441: Goa page keeps its first base folder")
def test_goa_page_follows_the_output_folder(qapp_tour, home):
    w = tour_mod.make_window(home / "first")
    w.folder_edit.setText(str(home / "second"))
    w.categories.setCurrentRow(w.tool_rows["goa"])
    assert Path(w.goa.folder_edit.text()).is_relative_to(home / "second")


@pytest.mark.xfail(strict=True, reason="GUI gap #413: Live import refuses GUI renders "
                   "outside a project folder Samples/Drums/<category>")
def test_a_gui_render_goes_through_the_live_plan_against_the_fake_server(qapp_tour, home):
    """Render a kick with the main window, pick it on the Live page, read the (fake) set and
    ask for a plan. Fake AbletonOSC only: not a Live test."""
    w = tour_mod.make_window(home / "out")
    step = tour_mod.render_category(w, "kick")
    assert step.ok, step.detail
    fake = make_fake()
    try:
        page = w.live
        page.config = config_for(fake, home)
        w.categories.setCurrentRow(w.tool_rows["live"])
        assert page.wav_path is not None and page.wav_path.endswith(step.detail)
        page.inspect_button.click()
        assert tour_mod.wait_for(lambda: page.inspection is not None and not page.busy, 30)
        assert page.inspection.ok, page.inspection.error
        page.plan_button.click()
        assert tour_mod.wait_for(lambda: page.plan is not None and not page.busy, 30)
        assert page.plan.ok, page.status.text()
        assert writes(fake) == []  # reading and planning never write
        page.testset_check.setChecked(True)
        page.import_button.click()
        assert tour_mod.wait_for(lambda: page.plan is None and not page.busy, 30)
        assert "Fertig" in page.status.text(), page.status.text()
        assert [a for a, _p in writes(fake)] == ["/live/song/create_audio_track",
                                                  "/live/clip_slot/create_audio_clip"]
    finally:
        fake.close()


@pytest.fixture
def qapp_tour():
    from gui.app import create_app

    return create_app([])
