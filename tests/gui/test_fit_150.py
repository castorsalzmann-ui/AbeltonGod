"""#442: every window fits an emulated 1920 x 1080 monitor at 150 % display scaling, i.e. a
logical screen of 1280 x 720 px (no title bar or task bar counted), and every category page
fits a narrow column without a horizontal scroll bar.

The window check runs in a child process: Qt's scale factor is fixed when the application
starts. Teardown of the in-process widgets: autouse fixture of tests/gui/conftest.py.

Measured on main 979c516 (Linux offscreen, Qt font "M" = 11 px): main window min 1216 x 703,
Acid 1026 x 812, Blaster 111 x 366; a category page needed 523 px (47.5 M: five knobs in one
row). Windows CI run 42220197138 (PR #449): main 1324 x 688, Acid 1183 x 649. Which window is too
big depends on the platform fonts, so the xfails below are per platform; the parts are in files
of area E (main_window.py, goa_panel.py, acid/), proposals on #442.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

if os.environ.get("ABELTONGOD_REQUIRE_GUI") == "1":
    import PySide6.QtWidgets  # noqa: F401
else:
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

SCREEN = (1280, 720)  # 1920 x 1080 physical px at 150 %
PAGE_MAX_M = 34  # a category page fits a column of 34 "M" widths (was 47.5)
WINDOWS = ("main", "goa", "acid", "blaster")
SRC = Path(__file__).resolve().parents[2] / "src"

# Too big on the named platform (measured, see module doc). Empty since #442 P1/P2: the main
# window's tool pages and the Acid skin are scroll areas. Measured after (Linux, 150 %):
# main 1040 x 408, Goa 360 x 260, Acid 66 x 66, Blaster 111 x 366.
_TOO_BIG: dict[str, tuple[str, ...]] = {}  # main and acid fit since #442 P1/P2 (scroll areas)


def _param(key: str):
    platforms = _TOO_BIG.get(key, ())
    marks = [pytest.mark.xfail(sys.platform in platforms, strict=True,
                               reason=f"#442: {key} window too big at 150 % on {sys.platform} "
                                      "(area E files)")] if platforms else []
    return pytest.param(key, marks=marks, id=key)


def _name(w) -> str:
    """Class, object name and a short text or accessible name: enough to find the widget."""
    text = ""
    get = getattr(w, "text", None)
    if callable(get):
        try:
            value = get()
            text = value[:32] if isinstance(value, str) else ""
        except TypeError:
            text = ""
    text = text or w.accessibleName()
    return (f"{type(w).__name__}{'#' + w.objectName() if w.objectName() else ''}"
            f"{' ' + repr(text) if text else ''}")


def _widest(root, count: int = 6) -> list[str]:
    """The widest widgets under ``root`` by their own minimum width, without the containers
    whose width only comes from a child further down (leaf-most first)."""
    from PySide6.QtWidgets import QWidget

    def own_w(w):
        return max(w.minimumSizeHint().width(), w.minimumWidth())

    def field(w):  # the contract field of the control the widget belongs to
        while w is not None and w is not root:
            if hasattr(w, "spec") and hasattr(w, "name"):
                return f" ({w.name})"
            w = w.parentWidget()
        return ""

    found: dict[str, int] = {}
    for w in root.findChildren(QWidget):
        if w.isWindow() or not w.isVisibleTo(root):
            continue
        kids = [c for c in w.findChildren(QWidget) if c.isVisibleTo(root)]
        if any(own_w(c) >= own_w(w) for c in kids):
            continue  # a child is as wide: report the child
        kind = type(w).__name__ if hasattr(w, "spec") else _name(w)
        found[kind] = max(found.get(kind, 0), own_w(w))
        if hasattr(w, "spec"):
            found[kind + field(w)] = own_w(w)
            found.pop(kind)
    return [f"{wd} {n}" for n, wd in sorted(found.items(), key=lambda kv: -kv[1])[:count]]


# --- child process -----------------------------------------------------------------------------

def _child(out: Path) -> None:
    """Runs with the emulated screen; writes {key: {min, screen, drivers}} to ``out``."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget

    from gui.app import create_app

    app = create_app([])

    def own(w):
        h = w.minimumSizeHint()
        return max(h.width(), w.minimumWidth()), max(h.height(), w.minimumHeight())

    def drivers(root, axis):
        """Descendants whose own minimum is at least a third of the window's (a size path).
        Every page of a stacked widget is walked, also the hidden ones (they count for the
        stack's minimum)."""
        from PySide6.QtWidgets import QStackedWidget

        total, rows = own(root)[axis], []

        def walk(w, depth):
            for c in w.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
                hidden_page = isinstance(w, QStackedWidget)
                if c.isWindow() or not (c.isVisibleTo(root) or hidden_page):
                    continue
                m = own(c)[axis]
                if m >= total / 3 and depth < 6:
                    rows.append(f"{'  ' * depth}{m} {_name(c)}")
                    walk(c, depth + 1)
        walk(root, 0)
        return rows[:16]

    def make(key):
        if key == "main":
            from gui.main_window import MainWindow

            class Silent:
                available = True

                def play(self, p):
                    pass

                def stop(self):
                    pass

            return MainWindow(out_dir=out.parent / "out", backend=Silent(),
                              opener=lambda p: True)
        from gui.windows import DEFAULT_FACTORIES
        return DEFAULT_FACTORIES[key](out.parent / "out")

    screen = app.primaryScreen().availableGeometry().size()
    result = {}
    for key in WINDOWS:
        w = make(key)
        w.show()
        app.processEvents()
        result[key] = {"min": own(w), "screen": (screen.width(), screen.height()),
                       "width": drivers(w, 0), "height": drivers(w, 1)}
        w.close()
    out.write_text(json.dumps(result), encoding="utf-8")


@pytest.fixture(scope="module")
def sizes150(tmp_path_factory):
    folder = tmp_path_factory.mktemp("fit150")
    (folder / "screen.json").write_text(json.dumps({"screens": [{
        "name": "fit", "x": 0, "y": 0, "width": 1920, "height": 1080,
        "logicalDpi": 96, "logicalBaseDpi": 96, "dpr": 1}]}), encoding="utf-8")
    env = dict(os.environ)
    # Qt splits the platform string at ":", so the config file is named relative to the cwd.
    env.update(QT_QPA_PLATFORM="offscreen:configfile=screen.json", QT_SCALE_FACTOR="1.5",
               PYTHONPATH=os.pathsep.join([str(SRC), env.get("PYTHONPATH", "")]))
    out = folder / "sizes.json"
    proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), str(out)], cwd=folder,
                          env=env, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return json.loads(out.read_text(encoding="utf-8"))


@pytest.mark.parametrize("key", [_param(k) for k in WINDOWS])
def test_window_minimum_fits_1920x1080_at_150_percent(sizes150, key, capsys):
    got = sizes150[key]
    assert tuple(got["screen"]) == SCREEN  # the emulation itself
    (w, h), (sw, sh) = got["min"], SCREEN
    # The size path goes to the terminal on every platform (CI log: which widget drives it).
    with capsys.disabled():
        print(f"\n[#442] {key} on {sys.platform}: min {w} x {h} on {sw} x {sh}")
        for axis in ("width", "height"):
            print(f"[#442]   {axis}: " + " | ".join(got[axis]))
    assert w <= sw and h <= sh, f"{key}: smallest {w} x {h} on a {sw} x {sh} screen"


# --- category pages (in process, normal scale) --------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from gui.app import create_app

    return create_app([])


@pytest.mark.parametrize("category", ["kick", "hat", "snare", "clap", "rim", "bass", "laser"])
def test_category_page_fits_a_column_of_34_m_without_horizontal_scroll(qapp, category, capsys):
    from gui.category_panel import CategoryPanel
    from gui_core.form import CategoryFormModel

    p = CategoryPanel(CategoryFormModel(category))
    for s in [p.advanced, *p.group_sections.values()]:
        s.set_expanded(True)
    m = p.fontMetrics().horizontalAdvance("M")
    scroll = p.verticalScrollBar().sizeHint().width()
    p.resize(PAGE_MAX_M * m + scroll + 2 * p.frameWidth(), 700)
    p.show()
    qapp.processEvents()
    root = p.widget()
    with capsys.disabled():  # CI log: the widest widgets of each page on this platform
        print(f"\n[#442] page {category} on {sys.platform}: content min "
              f"{root.minimumSizeHint().width()} px, M = {m} px; widest: "
              + " | ".join(_widest(root)))
    assert root.minimumSizeHint().width() <= PAGE_MAX_M * m, root.minimumSizeHint()
    assert p.horizontalScrollBar().maximum() == 0
    # the knobs wrap: none outside the page, none on top of another or of the hint below
    rects = [k.geometry().translated(p.knob_box.pos()) for k in p.knobs]
    assert all(r.right() <= root.width() for r in rects)
    for i, a in enumerate(rects):
        assert not any(a.intersects(b) for b in rects[i + 1:])
    below = p.hint_label.geometry()
    assert max(r.bottom() for r in rects) < below.top()
    assert len({r.top() for r in rects}) >= 2  # 5 knobs of 9 M do not fit 34 M in one row


def test_knobs_stay_in_one_row_when_the_page_is_wide(qapp):
    from gui.category_panel import CategoryPanel
    from gui_core.form import CategoryFormModel

    p = CategoryPanel(CategoryFormModel("kick"))
    p.resize(1200, 700)
    p.show()
    qapp.processEvents()
    assert len({k.geometry().top() for k in p.knobs}) == 1


def test_seed_range_text_sits_under_the_field(qapp):
    from gui.widgets import SeedControl
    from gui_core.form import field_specs

    spec = next(s for s in field_specs("kick") if s.name == "seed")
    c = SeedControl(spec)
    c.show()
    qapp.processEvents()
    assert c.range_label.text() == spec.range_text
    assert c.range_label.geometry().top() >= c.edit.geometry().bottom()
    m = c.fontMetrics().horizontalAdvance("M")
    assert c.minimumSizeHint().width() <= 31 * m


if __name__ == "__main__":
    _child(Path(sys.argv[1]))
