"""Control inventory of the GUI (#437): every button, action, shortcut and interactive custom
widget of the main window pages and the tool windows, with the signals that have a receiver.

Two checks build on it (``tests/gui/test_tour_inventory.py``):

* **No dead control.** A control is *handled* when one of its user signals has a receiver:
  ``clicked`` / ``toggled`` / ``pressed`` / ``released`` / ``triggered`` / ``activated``, or a
  signal of its ``QButtonGroup``. A button inside a widget-kit container (``Segmented``,
  ``PresetChips``, ``ParamControl`` ...) is only handled when the container passes the click
  on: one of the container's own signals must have a receiver too. A custom widget that declares
  signals of its own (knob, gun, XY pad, step grid ...) needs a receiver on one of them.
  :data:`ALLOWED` names the few controls without a receiver on purpose (state read when an
  action runs), each with the reason; hidden ``ActiveDot`` layout spacers are left out.
* **Inventory is complete.** :func:`inventory_ids` gives one ID per distinct control; the IDs in
  ``docs/qa/GUI_CONTROLS.md`` must be exactly this set, so a new button fails the test until it
  is documented, and a removed one until its row is deleted.

Receivers are read with ``QObject.isSignalConnected`` (Qt's own bookkeeping). That proves a
receiver exists, not that it does the right thing: the tour (``gui_tour.py``) and the area tests
check effects. Shadowed signals (a subclass re-declaring ``chosen``) are OR-ed by name.
Limitation: a control created later (e.g. only after a render) is not seen; the walk runs on
freshly opened windows.

CLI: ``python scripts/qa/gui_controls.py`` lists the IDs (NEW = not in the document, GONE = in
the document but not in the GUI) and the unhandled controls; exit 1 on either.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "qa" / "GUI_CONTROLS.md"

USER_SIGNALS = ("clicked", "toggled", "pressed", "released", "triggered", "activated",
                "activatedAmbiguously")
GROUP_SIGNALS = ("buttonClicked", "idClicked", "buttonToggled", "idToggled", "buttonPressed",
                 "idPressed", "buttonReleased", "idReleased")
# Kit containers: their buttons are generated per field / choice; one ID per container kind.
KIT = ("Segmented", "WrapSegmented", "PresetChips", "NumberControl", "SeedControl",
       "ChoiceControl", "BoolControl", "ParamControl", "Stepper", "ToggleRow", "EnumRow",
       "Collapsible")
# Containers whose internal connection IS the effect (no outward receiver needed).
SELF_CONTAINED = {"Collapsible": "expands / collapses its own section"}
IGNORED_SIGNALS = {"destroyed", "objectNameChanged"}

# (area, "Kind:label") -> reason. Every entry is a control the user can touch that has no
# receiver of its own; keep this list short and give the reader of the state.
ALLOWED: dict[tuple[str, str], str] = {
    ("blaster", "QCheckBox:Dauerfeuer beim Halten"):
        "state only: read in BlasterWindow._on_gun_triggered (starts the autofire timer)",
}
SPACERS = ("ActiveDot",)  # hidden layout spacers: keep the label column aligned


@dataclass(frozen=True)
class Control:
    area: str  # "main", "kick" ... "library", "goa-page", "live", "chat", "goa", "acid", ...
    kind: str  # class name
    label: str  # text / object name / accessible name / tooltip; "*" for kit-generated ones
    owner: str  # kit container class or ""
    signals: tuple[str, ...]  # user signals with a receiver
    owner_ok: bool  # the kit container passes the click on (True when there is none)
    hidden: bool
    # plain Qt input (line edit, combo box, spin box, list): listed for the inventory, but
    # not held to the receiver rule, because many are read only when an action runs
    input: bool = False

    @property
    def id(self) -> str:
        kind = f"{self.owner}/{self.kind}" if self.owner else self.kind
        return f"{self.area} · {kind} · {self.label}"  # no "|": the ID sits in a table cell

    @property
    def handled(self) -> bool:
        return bool(self.signals) and self.owner_ok


# --- signal bookkeeping ----------------------------------------------------------------------

def connected_signals(obj, names: Iterable[str] | None = None) -> set[str]:
    """Names of ``obj``'s signals that have at least one receiver (OR over overloads)."""
    from PySide6.QtCore import QMetaMethod

    wanted = set(names) if names is not None else None
    mo, out = obj.metaObject(), set()
    for i in range(mo.methodCount()):
        m = mo.method(i)
        if m.methodType() != QMetaMethod.MethodType.Signal:
            continue
        name = bytes(m.name()).decode()
        if (wanted is None or name in wanted) and obj.isSignalConnected(m):
            out.add(name)
    return out - IGNORED_SIGNALS


def own_signals(obj) -> set[str]:
    """Signals declared by Python subclasses (not by Qt's own classes)."""
    from PySide6.QtCore import QMetaMethod

    names, mo = set(), obj.metaObject()
    while mo is not None and not mo.className().startswith("Q"):
        for i in range(mo.methodOffset(), mo.methodCount()):
            m = mo.method(i)
            if m.methodType() == QMetaMethod.MethodType.Signal:
                names.add(bytes(m.name()).decode())
        mo = mo.superClass()
    return names


def _kit_owner(widget, root):
    """Nearest kit container above ``widget``. A section (``Collapsible``) only owns its own
    header button; the fields inside it are walked like any other."""
    p = widget.parent()
    while p is not None and p is not root:
        name = type(p).__name__
        if name in KIT and (name not in SELF_CONTAINED or p is widget.parent()):
            return p
        p = p.parent()
    return None


def _label(obj) -> str:
    """Stable name: the caption of a button / action / shortcut; for other widgets the
    accessible or object name (their ``text()`` would be the current value)."""
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QAbstractButton

    text = ""
    if isinstance(obj, QAbstractButton | QAction):
        text = obj.text()
    elif hasattr(obj, "key"):  # QShortcut
        text = obj.key().toString()
    if not text and hasattr(obj, "accessibleName"):
        text = obj.accessibleName()
    text = text or obj.objectName()
    if not text and hasattr(obj, "toolTip"):
        text = obj.toolTip()
    return " ".join(str(text).replace("|", "/").replace("`", "'").split())[:48].strip() or "-"


def _attr_name(obj) -> str:
    """``Owner.attribute`` under which an ancestor keeps ``obj`` (e.g. ``AcidWindow.seed_edit``),
    or "". Gives unnamed inputs a stable, code-searchable name."""
    key = _key(obj)
    p = obj.parent()
    while p is not None:
        for name, value in vars(p).items():
            try:
                if value is obj or (hasattr(value, "metaObject") and _key(value) == key):
                    return f"{type(p).__name__}.{name}"
            except (RuntimeError, TypeError):
                continue
        p = p.parent()
    return ""


def _name(obj) -> str:
    """Caption / accessible name; without one, the attribute that holds the widget."""
    label = _label(obj)
    return (_attr_name(obj) or label) if label == "-" else label


def _qt_internal(button) -> bool:
    """Buttons Qt makes inside its own widgets (tab-bar scroll arrows, table corner, line-edit
    clear button): not part of the app's controls."""
    from PySide6.QtWidgets import QAbstractScrollArea, QLineEdit, QTabBar

    parent = button.parent()
    return (button.objectName().startswith("qt_")
            or isinstance(parent, QTabBar | QLineEdit | QAbstractScrollArea))


INPUT_SIGNALS = ("textChanged", "textEdited", "editingFinished", "returnPressed",
                 "currentIndexChanged", "currentTextChanged", "activated", "valueChanged",
                 "currentRowChanged", "currentItemChanged", "itemDoubleClicked")


def _inputs():
    from PySide6.QtWidgets import QAbstractSpinBox, QComboBox, QLineEdit, QListWidget

    return (QLineEdit, QComboBox, QAbstractSpinBox, QListWidget)


def _input_internal(w) -> bool:
    """Line edits Qt makes inside a spin box or combo box."""
    from PySide6.QtWidgets import QAbstractSpinBox, QComboBox

    return isinstance(w.parent(), QAbstractSpinBox | QComboBox)


def _key(obj) -> int:
    import shiboken6

    return shiboken6.getCppPointer(obj)[0]


# --- walking ---------------------------------------------------------------------------------

def collect_pairs(area: str, root) -> list[tuple[Control, object]]:
    """(control, Qt object) for every button, action, shortcut and custom widget with signals
    of its own under ``root``."""
    from PySide6.QtGui import QAction, QShortcut
    from PySide6.QtWidgets import QAbstractButton, QWidget

    INPUTS = _inputs()  # noqa: N806 - Qt classes are imported lazily
    out: list[tuple[Control, object]] = []
    seen: set[int] = set()
    for b in root.findChildren(QAbstractButton):
        seen.add(_key(b))
        if _qt_internal(b):
            continue
        sig = connected_signals(b, USER_SIGNALS)
        group = b.group()
        if group is not None:
            sig |= {f"group.{s}" for s in connected_signals(group, GROUP_SIGNALS)}
        owner = _kit_owner(b, root)
        owner_name = type(owner).__name__ if owner is not None else ""
        owner_ok = True
        if owner is not None and owner_name not in SELF_CONTAINED:
            owner_ok = bool(connected_signals(owner, own_signals(owner)))
        label = "*" if owner is not None else _name(b)
        out.append((Control(area, type(b).__name__, label, owner_name, tuple(sorted(sig)),
                            owner_ok, b.isHidden()), b))
    for a in root.findChildren(QAction):
        if a.objectName().startswith("_q_"):  # Qt-internal (line-edit clear button)
            continue
        sig = tuple(sorted(connected_signals(a, USER_SIGNALS)))
        out.append((Control(area, "QAction", _label(a), "", sig, True, False), a))
    for s in root.findChildren(QShortcut):
        sig = tuple(sorted(connected_signals(s, USER_SIGNALS)))
        out.append((Control(area, "QShortcut", _label(s), "", sig, True, False), s))
    for w in root.findChildren(QWidget):
        if _key(w) in seen or _kit_owner(w, root) is not None:
            continue
        name = type(w).__name__
        if isinstance(w, INPUTS) and not own_signals(w):
            if _input_internal(w):
                continue
            sig = tuple(sorted(connected_signals(w, INPUT_SIGNALS)))
            out.append((Control(area, name, _name(w), "", sig, True, w.isHidden(),
                                input=True), w))
            continue
        if name in KIT:  # the container itself: one row per kind, it must pass changes on
            sig = ("(self-contained)",) if name in SELF_CONTAINED else tuple(sorted(
                connected_signals(w, own_signals(w))))
            out.append((Control(area, name, "*", "", sig, True, w.isHidden()), w))
            continue
        own = own_signals(w)
        if not own:
            continue
        sig = tuple(sorted(connected_signals(w, own)))
        out.append((Control(area, name, _name(w), "", sig, True, w.isHidden()), w))
    return out


def collect(area: str, root) -> list[Control]:
    return [c for c, _ in collect_pairs(area, root)]


def main_window_pages(window) -> list[tuple[str, object]]:
    """(area, page) for every page of the main window's stack, in list order."""
    from gui_core.categories import CATEGORIES

    names = [c.key for c in CATEGORIES] + ["library"]
    names += ["goa-page" if k == "goa" else k
              for k in sorted(window.tool_rows, key=window.tool_rows.get)]
    assert len(names) == window.stack.count(), (names, window.stack.count())
    return [(names[i], window.stack.widget(i)) for i in range(window.stack.count())]


def collect_main(window) -> list[Control]:
    """Every page of the main window, plus area "main" for its own columns (left list, window
    buttons, render column) = everything not inside a page."""
    from PySide6.QtCore import QObject

    out: list[Control] = []
    in_pages = {_key(window.stack)}
    for area, page in main_window_pages(window):
        out += collect(area, page)
        in_pages.add(_key(page))
        in_pages |= {_key(o) for o in page.findChildren(QObject)}
    out += [c for c, obj in collect_pairs("main", window) if _key(obj) not in in_pages]
    return out


def all_controls(window, tool_windows: dict[str, object]) -> list[Control]:
    out = collect_main(window)
    for key, win in tool_windows.items():
        out += collect(key, win)
    return out


def unhandled(controls: Iterable[Control]) -> list[Control]:
    """Controls without a receiver that are neither allowed nor hidden spacers."""
    bad = []
    for c in controls:
        if c.handled or c.input or (c.hidden and c.kind in SPACERS):
            continue
        if (c.area, f"{c.kind}:{c.label}") in ALLOWED:
            continue
        bad.append(c)
    return bad


def inventory_ids(controls: Iterable[Control]) -> set[str]:
    """One ID per distinct control kind/label per area (hidden spacers left out)."""
    return {c.id for c in controls if not (c.hidden and c.kind in SPACERS)}


def doc_ids(text: str) -> set[str]:
    """IDs listed in the inventory document: the first table cell, in backticks."""
    ids = set()
    for line in text.splitlines():
        if line.startswith("| `"):
            ids.add(line[3:line.index("`", 3)])
    return ids


def main() -> int:
    import os
    import tempfile

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import gui_tour

    from gui.app import create_app

    create_app([])
    with tempfile.TemporaryDirectory() as home, gui_tour.isolated_env(Path(home)):
        window = gui_tour.make_window(Path(home) / "out")
        tools = {}
        for key in gui_tour.TOOL_KEYS:
            window.window_buttons[key].click()
            tools[key] = window.windows.window(key)
        controls = all_controls(window, tools)
        ids = inventory_ids(controls)
        documented = doc_ids(DOC.read_text(encoding="utf-8")) if DOC.is_file() else set()
        for i in sorted(ids):
            print(("    " if i in documented else "NEW ") + i)
        for i in sorted(documented - ids):
            print("GONE " + i)
        bad = unhandled(controls)
        for c in bad:
            print(f"UNHANDLED {c.id} (signals {c.signals}, kit passes on: {c.owner_ok})")
        print(f"{len(controls)} controls, {len(ids)} inventory IDs, "
              f"{len(ids - documented)} new, {len(documented - ids)} gone, {len(bad)} unhandled")
        window.close()
    return 1 if bad or ids != documented else 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "src"))
    sys.exit(main())
