"""Small structure widgets: :class:`Collapsible` ("Erweitert"), :class:`StepEdit` (a number or
text field that Up/Down step) and :func:`rule` (a thin separator)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from gui_core.form import parse_number


def heading(text: str) -> QLabel:
    """Small upper-case section title (muted)."""
    label = QLabel(text.upper())
    label.setObjectName("heading")
    return label


def muted(text: str = "") -> QLabel:
    """Wrapping grey helper text that never widens its column."""
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
    return label


def rule() -> QFrame:
    line = QFrame()
    line.setObjectName("rule")
    line.setFrameShape(QFrame.Shape.NoFrame)
    return line


class Collapsible(QWidget):
    """Header with an arrow and a body that opens and closes (closed at the start)."""

    toggled = Signal(bool)

    def __init__(self, title: str, expanded: bool = False) -> None:
        super().__init__()
        self._title = title
        self.header = QToolButton()
        self.header.setObjectName("disclosure")
        self.header.setCheckable(True)
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.body = QWidget()
        self.body.setVisible(expanded)
        self.header.setChecked(expanded)
        self.header.toggled.connect(self._on_toggled)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.header, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(self.body)
        self._refresh()

    def set_title(self, title: str) -> None:
        self._title = title
        self._refresh()

    def is_expanded(self) -> bool:
        return self.header.isChecked()

    def set_expanded(self, on: bool) -> None:
        self.header.setChecked(on)

    def _on_toggled(self, on: bool) -> None:
        self.body.setVisible(on)
        self._refresh()
        self.toggled.emit(on)

    def _refresh(self) -> None:
        self.header.setArrowType(Qt.ArrowType.DownArrow if self.header.isChecked()
                                 else Qt.ArrowType.RightArrow)
        self.header.setText(self._title)


class StepEdit(QLineEdit):
    """Flat text field for a number whose range the contract does not give. Up/Down (and the
    wheel while focused) step the number by ``step``; the text stays exactly as typed
    otherwise. ``edited`` fires with the text when the user changed it."""

    edited = Signal(str)

    def __init__(self, text: str = "", step: float = 1.0) -> None:
        super().__init__(text)
        self.step = step
        self.textEdited.connect(self.edited)

    def _nudge(self, direction: int) -> None:
        number = parse_number(self.text())
        if number is None:
            return
        new = number + direction * self.step
        text = str(int(new)) if isinstance(number, int) and float(self.step).is_integer() \
            else f"{new:g}"
        self.setText(text)
        self.edited.emit(text)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt name
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self._nudge(1 if event.key() == Qt.Key.Key_Up else -1)
            event.accept()
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt name
        if not self.hasFocus():
            event.ignore()
            return
        self._nudge(1 if event.angleDelta().y() > 0 else -1)
        event.accept()
