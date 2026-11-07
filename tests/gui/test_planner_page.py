"""Arrangement-Planer page of the main window (#139, D-024): mouse input on the curve reaches
the planner as drawn nodes, settings buttons reach the planner, export writes a plan that
the contract checker accepts. Offscreen; nothing talks to Live, no model is called.

The look on a real screen is not checked here (the screenshot is for people)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

if os.environ.get("ABELTONGOD_REQUIRE_GUI") == "1":  # CI: a missing Qt must fail, not skip
    import PySide6.QtWidgets  # noqa: F401
else:
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from gui.app import create_app  # noqa: E402
from gui.main_window import MainWindow  # noqa: E402
from gui.planner_panel import PlannerPanel  # noqa: E402
from orchestrator.arrangement_generator import generate_plan  # noqa: E402
from orchestrator.arrangement_layout import SETTING_DEFAULTS, PlanRequest  # noqa: E402
from orchestrator.arrangement_plan import plan_problems  # noqa: E402

DEFAULT_REQ = PlanRequest("techno", 140, target_minutes=6, settings=dict(SETTING_DEFAULTS))


class Silent:
    available = True

    def play(self, p):
        pass

    def stop(self):
        pass


@pytest.fixture
def window(tmp_path):
    create_app([])
    opened = []
    w = MainWindow(out_dir=tmp_path / "out", backend=Silent(),
                   opener=lambda p: opened.append(p) or True)
    w.resize(1400, 900)
    w.show()
    w.categories.setCurrentRow(w.tool_rows["planner"])
    w.opened = opened
    QTest.qWait(1)
    yield w
    w.close()


def at(canvas, bar: float, value: float) -> QPoint:
    return QPoint(round(canvas.bar_to_x(bar)), round(canvas.value_to_y(value)))


def test_the_page_is_in_the_left_list_and_shows_a_plan(window):
    page = window.planner
    assert isinstance(page, PlannerPanel)
    assert window.stack.currentWidget().widget() is page and window.on_tool
    assert window.categories.currentItem().text() == "Arrangement-Planer"
    assert page.model.state.plan == generate_plan(DEFAULT_REQ).plan
    assert page.export_button.isEnabled()
    assert page.table.rowCount() == len(page.model.state.plan["sections"])


def test_a_click_on_the_curve_is_a_drawn_node_the_planner_uses(window):
    page, canvas = window.planner, window.planner.canvas
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     at(canvas, 100, 0.8))
    assert len(page.model.drawn) == 1
    node = page.model.drawn[0]
    assert node["pos"] == 100 and abs(node["value"] - 0.8) <= 0.01  # one pixel of rounding
    expected = generate_plan(DEFAULT_REQ, drawn_nodes=[dict(node)]).plan
    assert page.model.state.plan == expected
    assert [n for n in expected["energy_nodes"] if n["pos"] == 100] == [{**node, "drawn": True}]
    assert page.clear_button.isEnabled()


def test_dragging_moves_the_node_and_right_click_removes_it(window):
    page, canvas = window.planner, window.planner.canvas
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     at(canvas, 100, 0.8))
    QTest.mouseMove(canvas, at(canvas, 104, 0.2))
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                       at(canvas, 104, 0.2))
    node = page.model.drawn[0]
    assert node["pos"] == 104 and abs(node["value"] - 0.2) <= 0.01
    assert page.model.state.plan == generate_plan(DEFAULT_REQ, drawn_nodes=[dict(node)]).plan
    QTest.mouseClick(canvas, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier,
                     at(canvas, 104, node["value"]))
    assert page.model.drawn == []
    assert page.model.state.plan == generate_plan(DEFAULT_REQ).plan


def test_a_click_on_a_default_node_takes_it_over_as_drawn(window):
    page, canvas = window.planner, window.planner.canvas
    drop = next(s for s in page.model.state.plan["sections"] if s["type"] == "drop")
    end = drop["start_bar"] - 1 + drop["length_bars"]  # default drop end node: 0.95
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     at(canvas, end, 0.95))
    assert page.model.drawn == [{"pos": end, "value": 0.95}]
    nodes = page.model.state.plan["energy_nodes"]
    assert [n for n in nodes if n["pos"] == end] == [{"pos": end, "value": 0.95, "drawn": True}]


def test_shift_click_on_a_drawn_node_makes_a_step(window):
    page, canvas = window.planner, window.planner.canvas
    p = at(canvas, 100, 0.5)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p)
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, p)
    assert [n["pos"] for n in page.model.drawn] == [100, 100]


def test_settings_buttons_reach_the_planner(window):
    page = window.planner
    page.genre.buttons[1].click()  # Trance
    assert "break" not in [s["type"] for s in page.model.state.plan["sections"]]
    page.setting_edits["fills"].buttons[2].click()  # every 8 bars
    assert page.model.state.plan["settings"]["fills"] == "every_8"
    assert any(e.kind == "fill" for e in page.model.state.timeline.events)
    page.setting_edits["change_grid"].plus.click()
    assert page.model.state.plan["settings"]["change_grid"] == 9


def test_a_length_the_planner_refuses_disables_export_and_says_why(window):
    page = window.planner
    page.unit.buttons[1].click()  # Takte
    page.length_edit.setText("184")
    page.length_edit.edited.emit("184")
    assert not page.export_button.isEnabled()
    assert "200 Takte" in page.status.text() and page.status.property("level") == "error"
    assert page.export() is None


def test_export_writes_a_valid_plan_into_the_output_folder(window, tmp_path):
    page, canvas = window.planner, window.planner.canvas
    QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     at(canvas, 100, 0.8))
    page.export_button.click()
    path = page.last_export
    assert path is not None and path.parent == tmp_path / "out" / "Plans"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert plan_problems(data) == []
    assert data == page.model.state.plan
    assert str(path) in page.status.text()
    page.open_button.click()
    assert window.opened == [path.parent]


def test_the_plan_folder_follows_the_shared_output_folder(window, tmp_path):
    window.folder_edit.setText(str(tmp_path / "elsewhere"))
    window.folder_edit.editingFinished.emit()
    assert window.planner.target_dir() == tmp_path / "elsewhere" / "Plans"
    assert not Path(tmp_path / "elsewhere" / "Plans").exists()  # created on export only
