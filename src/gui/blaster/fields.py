"""Small building blocks of the blaster window on top of the widget kit: a labelled choice row
for enum / small-integer contract fields and the factory for number controls."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from gui.widgets import NumberControl, PresetChips, Segmented
from gui_core.blaster_params import spec


class EnumRow(QWidget):
    """One of a few contract values as a segmented row or as wrapping chips. ``values`` are the
    contract values (sent), ``labels`` the German texts (shown). Programmatic ``set_value``
    never emits; a click emits ``edited(name, value)`` then ``committed(name)``."""

    edited = Signal(str, object)
    committed = Signal(str)

    def __init__(self, name: str, values: Sequence[Any], labels: Sequence[str] | None = None,
                 chips: bool = False, caption: str | None = None, accent: bool = False) -> None:
        super().__init__()
        self.name = name
        self.values = list(values)
        self.labels = [str(x) for x in (labels if labels is not None else values)]
        self.chips = chips
        self._label = QLabel(caption if caption is not None else spec(name).label)
        self._label.setObjectName("heading")
        if chips:
            self.widget: PresetChips | Segmented = PresetChips(self.labels)
            self.widget.chosen.connect(self._chosen_text)
        else:
            self.widget = Segmented(self.labels, accent=accent)
            self.widget.chosen.connect(self._chosen_index)
        self.widget.setAccessibleName(spec(name).label)
        self.widget.setToolTip(spec(name).description)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        if caption != "":
            lay.addWidget(self._label)
        lay.addWidget(self.widget)

    def set_value(self, value: Any) -> None:
        i = self.values.index(value) if value in self.values else -1
        if self.chips:
            self.widget.set_current(self.labels[i] if i >= 0 else "")
        else:
            self.widget.set_index(i)

    def value(self) -> Any:
        if self.chips:
            cur = self.widget.current()
            return self.values[self.labels.index(cur)] if cur in self.labels else None
        i = self.widget.index()
        return self.values[i] if i >= 0 else None

    def _chosen_index(self, i: int) -> None:
        self.edited.emit(self.name, self.values[i])
        self.committed.emit(self.name)

    def _chosen_text(self, text: str) -> None:
        self._chosen_index(self.labels.index(text))


def number(name: str, main: bool, knob: bool) -> NumberControl:
    """A kit number control for a contract field (always sent: no activation dot)."""
    return NumberControl(spec(name), style="knob" if knob else "row", always_active=True,
                         accent=main)


def row(*widgets: QWidget, spacing: int = 8) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    for w in widgets:
        lay.addWidget(w)
    return lay


class PageStack(QWidget):
    """Like QStackedWidget, but only the shown page takes space (a stack sizes itself to its
    largest page, which leaves holes under the small ones)."""

    def __init__(self) -> None:
        super().__init__()
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._pages: list[QWidget] = []
        self._index = -1

    def addWidget(self, page: QWidget) -> None:  # noqa: N802 - mirrors QStackedWidget
        self._pages.append(page)
        self._lay.addWidget(page)
        page.setVisible(False)

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802 - mirrors QStackedWidget
        self._index = index
        for i, page in enumerate(self._pages):
            page.setVisible(i == index)

    def currentIndex(self) -> int:  # noqa: N802
        return self._index
