"""Control inventory (#437): no button, action, shortcut or interactive widget without a
receiver, and docs/qa/GUI_CONTROLS.md lists exactly the controls the GUI has
(``scripts/qa/gui_controls.py``). Offscreen; a receiver proves wiring, not the effect (the tour
and the area tests check effects)."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

if os.environ.get("ABELTONGOD_REQUIRE_GUI") == "1":  # CI: a missing Qt must fail, not skip
    import PySide6.QtWidgets  # noqa: F401
else:
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget  # noqa: E402

from gui.app import create_app  # noqa: E402
from gui.widgets import PresetChips  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


tour_mod = _load("gui_tour", ROOT / "scripts" / "qa" / "gui_tour.py")
gc_mod = _load("gui_controls", ROOT / "scripts" / "qa" / "gui_controls.py")

# Unhandled controls that are known gaps: (area, kind) -> issue. The test below turns red
# once the control gets a receiver or disappears.
KNOWN_DEAD: dict[tuple[str, str], int] = {}  # #440 fixed in PR #450


@pytest.fixture(scope="module")
def qapp():
    return create_app([])


@pytest.fixture
def gui(qapp, tmp_path):
    """Main window plus the three tool windows, all default paths in ``tmp_path``."""
    with tour_mod.isolated_env(tmp_path):
        window = tour_mod.make_window(tmp_path / "out")
        tools = {}
        for key in tour_mod.TOOL_KEYS:
            window.window_buttons[key].click()
            tools[key] = window.windows.window(key)
            assert tools[key] is not None, window.window_note.text()
        yield window, tools
        window.close()


@pytest.fixture(scope="module")
def controls(qapp, tmp_path_factory):
    """The inventory, built once per worker (about 3 s); only data leaves the fixture."""
    home = tmp_path_factory.mktemp("inventory")
    with tour_mod.isolated_env(home):
        window = tour_mod.make_window(home / "out")
        try:
            tools = {}
            for key in tour_mod.TOOL_KEYS:
                window.window_buttons[key].click()
                tools[key] = window.windows.window(key)
                assert tools[key] is not None, window.window_note.text()
            return gc_mod.all_controls(window, tools)
        finally:
            window.close()
            window.deleteLater()


def test_every_control_has_a_handler(controls):
    bad = [c for c in gc_mod.unhandled(controls) if (c.area, c.kind) not in KNOWN_DEAD]
    assert bad == [], "\n".join(f"{c.id}: no receiver (kit passes on: {c.owner_ok})"
                                for c in bad)


@pytest.mark.parametrize("key", list(KNOWN_DEAD), ids=lambda k: f"{k[0]}-{k[1]}")
def test_known_dead_controls_are_still_dead(controls, key):
    """xfail only while the control exists and has no receiver; red once it is handled or gone
    (then drop it from KNOWN_DEAD), so the entry cannot hide anything else."""
    issue = KNOWN_DEAD[key]
    found = [c for c in controls if (c.area, c.kind) == key]
    if not found:
        pytest.fail(f"GUI gap #{issue}: {key} is gone; remove it from KNOWN_DEAD")
    if all(c.handled for c in found):
        pytest.fail(f"GUI gap #{issue} looks fixed: {key} has a receiver; remove it")
    pytest.xfail(f"GUI gap #{issue}: {key} has no receiver")


def test_inventory_document_lists_exactly_the_controls_of_the_gui(controls):
    doc = gc_mod.doc_ids(gc_mod.DOC.read_text(encoding="utf-8"))
    ids = gc_mod.inventory_ids(controls)
    assert not ids - doc, "controls missing in docs/qa/GUI_CONTROLS.md:\n" + "\n".join(
        sorted(ids - doc))
    assert not doc - ids, "rows in docs/qa/GUI_CONTROLS.md without a control:\n" + "\n".join(
        sorted(doc - ids))


def test_inventory_covers_every_page_and_window(controls):
    areas = {c.area for c in controls}
    assert areas == {"main", "kick", "hat", "snare", "clap", "rim", "bass", "laser", "perc", "fx",
                     "library", "goa-page", "planner", "live", "chat", "reference", "goa",
                     "acid", "blaster"}


def test_every_allowed_exception_still_exists(controls):
    """A stale allow-list entry would hide nothing today but could hide a new control."""
    present = {(c.area, f"{c.kind}:{c.label}") for c in controls}
    assert set(gc_mod.ALLOWED) <= present


def test_inventory_rows_have_a_handler_and_an_effect():
    rows = [line for line in gc_mod.DOC.read_text(encoding="utf-8").splitlines()
            if line.startswith("| `")]
    for line in rows:
        cells = [c.strip() for c in line.strip("|").split("|")]
        assert len(cells) == 3 and all(cells), line


# --- the check can fail (planted faults) -----------------------------------------------------

def test_check_flags_a_button_without_receiver_and_a_kit_that_passes_nothing_on(qapp):
    root = QWidget()
    lay = QVBoxLayout(root)
    dead = QPushButton("Tot")
    live = QPushButton("Lebt")
    live.clicked.connect(root.close)
    chips = PresetChips(["a", "b"])  # its buttons are wired inside, but nobody hears `chosen`
    for w in (dead, live, chips):
        lay.addWidget(w)
    bad = {c.id for c in gc_mod.unhandled(gc_mod.collect("t", root))}
    assert bad == {"t · QPushButton · Tot", "t · PresetChips · *",
                   "t · PresetChips/QPushButton · *"}
    dead.clicked.connect(root.close)
    chips.chosen.connect(root.close)
    assert gc_mod.unhandled(gc_mod.collect("t", root)) == []
    root.deleteLater()


def test_check_flags_a_real_button_once_its_receiver_is_removed(gui):
    window, tools = gui
    assert not [c for c in gc_mod.unhandled(gc_mod.all_controls(window, tools))
                if c.area == "acid"]
    tools["acid"].export_button.clicked.disconnect()
    bad = [c.id for c in gc_mod.unhandled(gc_mod.all_controls(window, tools))]
    assert "acid · QPushButton · MIDI exportieren" in bad


def test_doc_parser_reads_the_first_cell_only():
    text = "| ID | Handler | Effect |\n| --- | --- | --- |\n| `a · B · c` | `x` | y |\n"
    assert gc_mod.doc_ids(text) == {"a · B · c"}
