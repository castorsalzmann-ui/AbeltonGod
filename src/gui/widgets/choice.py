"""Button rows: :class:`Segmented` (one of a few values), :class:`PresetChips` (wrapping chips,
one or many selected) and the :class:`FlowLayout` they wrap with.

Keyboard: Tab enters the row once; Left/Right (Up/Down) move the choice, Home/End jump."""

from __future__ import annotations

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLayout,
    QPushButton,
    QSizePolicy,
    QWidget,
)


class FlowLayout(QLayout):
    """Left-to-right layout that wraps to the next line (Qt's flow layout example)."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: list = []
        self._space = spacing
        self.setContentsMargins(QMargins(0, 0, 0, 0))

    def addItem(self, item) -> None:  # noqa: N802 - Qt name
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802 - Qt name
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802 - Qt name
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt name
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt name
        return self._layout(QRect(0, 0, width, 0), dry=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 - Qt name
        super().setGeometry(rect)
        self._layout(rect, dry=False)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt name
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802 - Qt name
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _layout(self, rect: QRect, dry: bool) -> int:
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = area.x(), area.y(), 0
        for item in self._items:
            # never below the item's minimum (Windows CI: a knob's size hint was 2 px below
            # it, so its caption was cut, #517)
            hint = item.sizeHint().expandedTo(item.minimumSize())
            if x + hint.width() > area.right() + 1 and line_h > 0:
                x = area.x()
                y += line_h + self._space
                line_h = 0
            if not dry:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._space
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y() + m.bottom()


class _KeyRow(QWidget):
    """Common keyboard handling for a row of exclusive buttons."""

    def __init__(self) -> None:
        super().__init__()
        self.buttons: list[QPushButton] = []
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _move(self, delta: int | None, to: int | None = None) -> None:
        raise NotImplementedError

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt name
        key = event.key()
        if key in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self._move(1)
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self._move(-1)
        elif key == Qt.Key.Key_Home:
            self._move(None, 0)
        elif key == Qt.Key.Key_End:
            self._move(None, len(self.buttons) - 1)
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def _make_button(self, text: str, name: str) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName(name)
        b.setCheckable(True)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # the row has the focus, not each button
        b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        return b

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt name
        super().paintEvent(event)
        if self.hasFocus():  # a thin outline shows where the keyboard acts
            from PySide6.QtGui import QColor, QPainter, QPen

            from gui import theme
            p = QPainter(self)
            p.setPen(QPen(QColor(theme.NEUTRAL), 1, Qt.PenStyle.DotLine))
            p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 6, 6)


class Segmented(_KeyRow):
    """Exactly one of a few values; emits the index the user chose."""

    chosen = Signal(int)

    def __init__(self, items: list[str], accent: bool = False) -> None:
        super().__init__()
        self.items = list(items)
        self._index = -1
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(4)
        for i, text in enumerate(items):
            b = self._make_button(text, "seg")
            b.setProperty("accent", accent)
            b.clicked.connect(lambda _c, i=i: self._clicked(i))
            lay.addWidget(b)
            self.buttons.append(b)
        lay.addStretch(1)

    def index(self) -> int:
        return self._index

    def set_index(self, index: int) -> None:
        """Programmatic: shows the choice without emitting."""
        self._index = index
        for i, b in enumerate(self.buttons):
            b.setChecked(i == index)

    def _clicked(self, index: int) -> None:
        self._apply(index)

    def _apply(self, index: int) -> None:
        changed = index != self._index
        self.set_index(index)
        if changed:
            self.chosen.emit(index)

    def _move(self, delta: int | None, to: int | None = None) -> None:
        if not self.isEnabled():
            return
        target = to if delta is None else self._index + delta
        if target is not None and 0 <= target < len(self.buttons):
            self._apply(target)


class PresetChips(_KeyRow):
    """Wrapping chips. Single choice by default (``multi=False``); ``multi=True`` lets any
    number be on (Goa voices) and emits the set of chosen texts."""

    chosen = Signal(str)  # single mode: the chosen text
    changed = Signal(object)  # multi mode: list of chosen texts, in item order

    def __init__(self, items: list[str], multi: bool = False) -> None:
        super().__init__()
        self.items = list(items)
        self.multi = multi
        self._current = ""
        self._focus = 0
        flow = FlowLayout(self, spacing=6)
        for i, text in enumerate(items):
            b = self._make_button(text, "chip")
            b.clicked.connect(lambda _c, i=i: self._clicked(i))
            flow.addWidget(b)
            self.buttons.append(b)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

    def current(self) -> str:
        return self._current

    def selected(self) -> list[str]:
        return [b.text() for b in self.buttons if b.isChecked()]

    def set_current(self, text: str) -> None:
        """Programmatic (single mode): shows the choice without emitting."""
        self._current = text
        for b in self.buttons:
            b.setChecked(b.text() == text)

    def set_selected(self, texts) -> None:
        wanted = set(texts)
        for b in self.buttons:
            b.setChecked(b.text() in wanted)

    def _clicked(self, index: int) -> None:
        self._focus = index
        if self.multi:
            self.changed.emit(self.selected())
            return
        text = self.buttons[index].text()
        self.set_current(text)
        self.chosen.emit(text)

    def _move(self, delta: int | None, to: int | None = None) -> None:
        if not self.isEnabled() or not self.buttons:
            return
        if self.multi:  # the arrows only move the focus mark, Space/Enter toggles
            self._focus = min(max(to if delta is None else self._focus + delta, 0),
                              len(self.buttons) - 1)
            self.update()
            return
        cur = self.items.index(self._current) if self._current in self.items else -1
        target = to if delta is None else cur + delta
        if target is not None and 0 <= target < len(self.buttons):
            self._clicked(target)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt name
        if self.multi and event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return,
                                          Qt.Key.Key_Enter):
            b = self.buttons[self._focus]
            b.setChecked(not b.isChecked())
            self.changed.emit(self.selected())
            event.accept()
            return
        super().keyPressEvent(event)


class WrapSegmented(PresetChips):
    """Same interface as :class:`Segmented` (index in, index out) but the buttons wrap to the
    next line. Used for enums whose buttons do not fit in one row (laser pan pattern, the 12
    note values), so the page never needs a horizontal scroll bar."""

    chosen = Signal(int)  # type: ignore[assignment]  # the index, as Segmented

    def index(self) -> int:
        return self.items.index(self._current) if self._current in self.items else -1

    def set_index(self, index: int) -> None:
        """Programmatic: shows the choice without emitting."""
        self.set_current(self.items[index] if 0 <= index < len(self.items) else "")

    def _clicked(self, index: int) -> None:
        self._focus = index
        changed = index != self.index()
        self.set_index(index)
        if changed:
            self.chosen.emit(index)
