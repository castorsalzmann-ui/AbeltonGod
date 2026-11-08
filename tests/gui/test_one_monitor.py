"""#517: AbeltonGod next to Live on one monitor. Every window has an "Immer im Vordergrund"
switch that is remembered per window; the main window switches to its compact layout when it
is narrower than the wide one. Offscreen: the stay-on-top window flag is checked, not how a
real window manager stacks the windows (that needs the user's Windows machine). The half-screen
fit of every page is in ``test_fit_150.py``."""

from __future__ import annotations

import os

import pytest

if os.environ.get("ABELTONGOD_REQUIRE_GUI") == "1":  # CI: a missing Qt must fail, not skip
    import PySide6.QtWidgets  # noqa: F401
else:
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QWidget  # noqa: E402

from gui.app import create_app  # noqa: E402
from gui.main_window import MainWindow  # noqa: E402
from gui.widgets.adaptive import AdaptiveBox  # noqa: E402
from gui_core.settings import SettingsStore, load_settings  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return create_app([])


class FakeBackend:
    available = True

    def play(self, wav_path):
        pass

    def stop(self):
        pass


def on_top(win) -> bool:
    return bool(win.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)


def switch_of(key: str, win):
    return win.strip.pin_button if key == "goa" else win.on_top_box


def open_main(cfg, tmp_path) -> MainWindow:
    w = MainWindow(out_dir=tmp_path / "out", backend=FakeBackend(),
                   settings_store=SettingsStore(path=cfg))
    w.show()
    QApplication.processEvents()
    return w


@pytest.mark.parametrize("key", ["main", "goa", "acid", "blaster"])
def test_always_on_top_switch_works_and_survives_a_restart(qapp, tmp_path, key):
    cfg = tmp_path / "cfg" / "settings.json"
    w = open_main(cfg, tmp_path)
    win = w if key == "main" else w.windows.open(key)
    switch = switch_of(key, win)
    start = on_top(win)  # Goa starts on top (its skin default), the others do not
    assert switch.isChecked() == start
    assert start == (key == "goa")
    switch.click()
    QApplication.processEvents()
    assert on_top(win) == (not start)
    assert win.isVisible()  # changing the flag hides a window; it must come back
    if key == "main":  # per window: the tool windows are not touched
        assert not on_top(w.windows.open("acid"))
    else:
        win.close()
        QApplication.processEvents()
    w.close()
    QApplication.processEvents()
    assert load_settings(cfg).windows[key].always_on_top == (not start)

    w2 = open_main(cfg, tmp_path)
    win2 = w2 if key == "main" else w2.windows.open(key)
    assert on_top(win2) == (not start)
    assert switch_of(key, win2).isChecked() == (not start)
    switch_of(key, win2).click()  # and back
    assert on_top(win2) == start
    w2.close()


def test_main_window_switches_layout_with_its_width(qapp, tmp_path):
    w = open_main(None, tmp_path)
    m = w.fontMetrics().horizontalAdvance("M")
    w.resize(m * 130, 700)
    QApplication.processEvents()
    assert not w.compact
    assert w.categories.isVisible() and not w.page_box.isVisible()
    w.resize(w.minimumSizeHint().width(), 700)  # the smallest the window can be
    QApplication.processEvents()
    assert w.compact
    assert w.page_box.isVisible() and not w.categories.isVisible()
    assert w.split.orientation() == Qt.Orientation.Vertical
    # the page chooser and the list are one: choosing in either shows the page
    w.page_box.setCurrentIndex(w.library_row)
    w.page_box.activated.emit(w.library_row)
    assert w.categories.currentRow() == w.library_row and w.on_library
    w.categories.setCurrentRow(w.tool_rows["live"])
    assert w.page_box.currentIndex() == w.tool_rows["live"]
    w.resize(m * 130, 700)
    QApplication.processEvents()
    assert not w.compact and w.split.orientation() == Qt.Orientation.Horizontal
    w.close()


def test_adaptive_box_is_a_row_when_it_fits_and_a_column_when_not(qapp):
    host = QWidget()
    box = AdaptiveBox(host)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(0)
    a, b = QLabel("a"), QLabel("b")
    a.setMinimumWidth(200)
    b.setMinimumWidth(300)
    box.addWidget(a)
    box.addWidget(b)
    assert host.minimumSizeHint().width() == 300  # the column's width
    host.resize(500, 200)
    host.show()
    QApplication.processEvents()
    assert a.geometry().top() == b.geometry().top()  # one row
    host.resize(499, 200)
    QApplication.processEvents()
    assert a.geometry().bottom() < b.geometry().top()  # a column
    assert b.width() >= 300
    host.close()
