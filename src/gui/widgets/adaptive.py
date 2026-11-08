"""A box layout that is a row while its items fit side by side and a column when they do not
(#517: the main window at half the screen width). Its minimum width is the column's, so a parent
can make it narrow; the switch happens in ``setGeometry``, before the items are placed."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize
from PySide6.QtWidgets import QBoxLayout, QWidget

ROW = QBoxLayout.Direction.LeftToRight
COLUMN = QBoxLayout.Direction.TopToBottom


class AdaptiveBox(QBoxLayout):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(ROW, parent)

    def _items(self) -> list:
        items = (self.itemAt(i) for i in range(self.count()))
        return [it for it in items if it is not None and not it.isEmpty()]

    def _gap(self) -> int:
        return max(0, self.spacing())

    def row_width(self) -> int:
        """The width the items need side by side (each at its minimum)."""
        m, items = self.contentsMargins(), self._items()
        return (m.left() + m.right() + sum(it.minimumSize().width() for it in items)
                + self._gap() * max(0, len(items) - 1))

    def is_row(self) -> bool:
        return self.direction() == ROW

    def minimumSize(self) -> QSize:  # noqa: N802 - Qt name
        m, items = self.contentsMargins(), self._items()
        if not items:
            return QSize(m.left() + m.right(), m.top() + m.bottom())
        width = max(it.minimumSize().width() for it in items)
        heights = [it.minimumSize().height() for it in items]
        height = (max(heights) if self.is_row()
                  else sum(heights) + self._gap() * (len(items) - 1))
        return QSize(width + m.left() + m.right(), height + m.top() + m.bottom())

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 - Qt name
        want = ROW if rect.width() >= self.row_width() else COLUMN
        if want != self.direction():
            self.setDirection(want)
        super().setGeometry(rect)
