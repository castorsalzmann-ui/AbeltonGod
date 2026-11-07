"""GUI tour (#437): every page and window, one render per category plus Goa, Acid and Blaster,
each result looked up in the main window's library. Offscreen, silent backend, all default
paths in a temp folder (``scripts/qa/gui_tour.py``). A known gap is reported as xfail only when
the step fails for that gap's documented reason (:func:`known_gap`); a pass ("looks fixed") and
any other failure are red, so a fix is noticed and an unrelated break is not hidden.

Nothing here is evidence for the look on a real Windows screen, the sound, or Live (the Live
step runs against the fake AbletonOSC server of tests/bridge)."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
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
                + ["render:goa-page", "export:planner", "render:goa-window", "render:acid",
                   "render:blaster-shot", "render:blaster-bank"])
WINDOW_STEPS = [f"open:{k}" for k in tour_mod.TOOL_KEYS]


def known_gap(issue: int, failed: bool, for_the_reason: bool, detail: str) -> None:
    """The strict-xfail rule with the reason pinned: xfail only when the check fails for the
    gap's own reason; red when it passes (gap fixed: remove the entry) or fails otherwise."""
    if not failed:
        pytest.fail(f"GUI gap #{issue} looks fixed; remove its known-gap entry. {detail}")
    if not for_the_reason:
        pytest.fail(f"failed, but not for the reason of GUI gap #{issue}: {detail}")
    pytest.xfail(f"GUI gap #{issue}: {detail}")


def expect_step(step) -> None:
    issue = step.known_issue
    if issue is None:
        assert step.ok, step.detail
        return
    known_gap(issue, not step.ok, step.gap is not None, step.detail)


@pytest.fixture(scope="module")
def tour(tmp_path_factory):
    """One tour per worker (about 4-9 s); the window is closed inside, only data is kept."""
    home = tmp_path_factory.mktemp("tour_home")
    shots = tmp_path_factory.mktemp("tour_shots")
    return tour_mod.run_tour(home, shots, "100")


def test_the_tour_visits_exactly_the_expected_steps(tour):
    names = [s.name for s in tour.steps]
    expected = (PAGE_STEPS + RENDER_STEPS[:9] + ["reference:kick"] + WINDOW_STEPS
                + RENDER_STEPS[9:] + ["close:tools-with-main", "choice:library"])
    assert names == expected


def test_a_library_file_can_be_marked_as_favourite(tour):
    expect_step(tour.step("choice:library"))


def test_reference_page_measures_the_kick_render_and_fills_the_kick_form(tour):
    """#480: the Referenz page measured the tour's kick render and "Als Startwerte übernehmen"
    put the nearest candidate's preset into the kick form (the step checks the form)."""
    expect_step(tour.step("reference:kick"))


@pytest.mark.parametrize("name", PAGE_STEPS)
def test_every_main_window_page_shows(tour, name):
    expect_step(tour.step(name))


@pytest.mark.parametrize("name", RENDER_STEPS)
def test_render_lands_in_the_library(tour, name):
    expect_step(tour.step(name))


@pytest.mark.parametrize("name", WINDOW_STEPS + ["close:tools-with-main"])
def test_tool_windows_open_and_close_with_the_main_window(tour, name):
    expect_step(tour.step(name))


def test_category_names_do_not_collide(tour):
    """One render per category into a fresh folder must not need a counter suffix, and each
    name starts with its category (#443)."""
    names = [tour.step(f"render:{k}").detail for k in tour_mod.CATEGORY_KEYS]
    assert all(n.endswith(".wav") for n in names), names  # every render produced a file
    clashes = [n for n in names if re.search(r"_\d{3}\.wav$", n)]
    assert clashes == [], names
    assert [n.split("_")[0] for n in names] == list(tour_mod.CATEGORY_KEYS), names


def test_screenshots_of_every_page_and_window_at_100_percent(tour):
    names = sorted(p.name for p in tour.shots)
    assert len(names) == len(PAGE_STEPS) + len(tour_mod.TOOL_KEYS), names
    for p in tour.shots:
        img = QImage(str(p))
        assert not img.isNull() and img.width() >= 300 and img.height() >= 200, p.name


@pytest.fixture(scope="module")
def tour150(tmp_path_factory, tour):
    """The 150 % pass in a child process (the scale factor is fixed when Qt starts). Its shots
    go to the system temp folder, outside the checkout: the CLI only accepts folders inside
    the checkout that git ignores, and a mutation-runner copy is no git checkout."""
    with tempfile.TemporaryDirectory(prefix="abeltongod-tour150-") as tmp:
        out = Path(tmp)
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
        yield data


def test_150_percent_pass_has_every_page_and_window_at_one_and_a_half_pixels(tour, tour150):
    assert tour150["returncode"] == 0, tour150["stdout"]
    shots150 = {Path(p).name.split("_", 1)[1]: Path(p) for p in tour150["shots"]}
    shots100 = {p.name.split("_", 1)[1]: p for p in tour.shots}
    assert set(shots150) == set(shots100)
    for name, p in shots100.items():
        a, b = QImage(str(p)), QImage(str(shots150[name]))
        if name.startswith(("window_blaster", "window_acid")):
            continue  # clamp themselves to the (smaller logical) screen (Acid since #442)
        assert abs(b.width() - 1.5 * a.width()) <= 2 and abs(b.height() - 1.5 * a.height()) <= 2, (
            name, a.size(), b.size())


def test_150_percent_pass_visits_every_page_and_window(tour150):
    """Pages and windows only (no renders); whether windows fit the screen at 150 % is checked
    once, in tests/gui/test_fit_150.py."""
    assert [s["name"] for s in tour150["steps"]] == (
        PAGE_STEPS + WINDOW_STEPS + ["close:tools-with-main"])
    assert all(s["ok"] for s in tour150["steps"]), tour150["stdout"]


def test_screenshots_never_go_into_the_repo(tmp_path, monkeypatch):
    assert not tour_mod.shots_allowed(ROOT / "shots")
    assert not tour_mod.shots_allowed(ROOT / "docs" / "qa")
    assert not tour_mod.shots_allowed(ROOT / ".tour_not_ignored" / "shots")
    if (ROOT / ".git").exists():  # a mutation-runner copy has no git: all refused there
        assert tour_mod.shots_allowed(ROOT / ".pytest_tmp" / "shots")  # .gitignore lists it
    assert tour_mod.shots_allowed(Path(os.path.abspath(os.sep)) / "elsewhere" / "shots")
    assert tour_mod.main(["--scale", "1", "--shots", str(ROOT / "shots")]) == 2
    assert not (ROOT / "shots").exists()

    def no_git(*_a, **_k):
        raise OSError("git not found")

    monkeypatch.setattr(tour_mod.subprocess, "run", no_git)  # without git: refuse in the repo
    assert not tour_mod.shots_allowed(ROOT / ".pytest_tmp" / "shots")


# --- steps with their own window -------------------------------------------------------------

@pytest.fixture
def home(tmp_path):
    with tour_mod.isolated_env(tmp_path):
        yield tmp_path


def test_goa_page_follows_the_output_folder(qapp_tour, home):
    """#441, closed by #450: a folder typed like a user (editing finished) is the shared output
    folder, and the Goa page's run folder follows it."""
    w = tour_mod.make_window(home / "first")
    w.folder_edit.setText(str(home / "second"))
    w.folder_edit.editingFinished.emit()
    w.categories.setCurrentRow(w.tool_rows["goa"])
    folder = Path(w.goa.folder_edit.text())
    assert folder.is_relative_to(home / "second" / "Goa"), f"Goa page folder {folder}"


def test_a_gui_render_goes_through_the_live_plan_against_the_fake_server(qapp_tour, home):
    """Render a kick with the main window, pick it on the Live page, name a Live project, read
    the (fake) set, plan and import: the render is copied into
    <project>/Samples/Drums/Kicks and that copy is imported (#413, fixed by #451). Fake
    AbletonOSC only: not a Live test."""
    w = tour_mod.make_window(home / "out")
    step = tour_mod.render_category(w, "kick")
    assert step.ok, step.detail
    proj = home / "Set Project"
    proj.mkdir()
    (proj / "Set.als").write_bytes(b"")
    fake = make_fake()
    try:
        page = w.live
        page.config = config_for(fake, home)
        page.refused_roots = ()  # pytest's temp folder lies inside the checkout
        w.categories.setCurrentRow(w.tool_rows["live"])
        assert page.wav_path is not None and page.wav_path.endswith(step.detail)
        page.project_edit.setText(str(proj))
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
        target = proj / "Samples" / "Drums" / "Kicks" / step.detail
        assert target.read_bytes() == Path(page.wav_path).read_bytes()
        assert writes(fake)[-1] == ("/live/clip_slot/create_audio_clip",
                                    writes(fake)[-1][1][:2] + (str(target),))
    finally:
        fake.close()


@pytest.fixture
def qapp_tour():
    from gui.app import create_app

    return create_app([])
