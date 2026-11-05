"""Whole-number stepper: "-" and "+" buttons around a readout. Same small interface as a spin box
(``value``, ``setValue``, ``setRange``, ``setMaximum``, ``setSpecialValueText``,
``valueChanged``) for places where a slider makes no sense (the scene number of the Live page).

Keyboard: Up/Down (and the wheel while focused) step by 1, Page Up/Down by 10, Home/End to the
ends."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget


class Stepper(QWidget):
    valueChanged = Signal(int)  # noqa: N815 - Qt style, like QSpinBox

    def __init__(self, minimum: int = 0, maximum: int = 99) -> None:
        super().__init__()
        self._min, self._max, self._value = minimum, maximum, minimum
        self._special = ""
        em = self.fontMetrics().horizontalAdvance("M")
        self.minus = QPushButton("−")
        self.plus = QPushButton("+")
        for b in (self.minus, self.plus):
            b.setFixedWidth(em * 2)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setAutoRepeat(True)
            b.setStyleSheet("padding: 0.3em 0;")
        self.readout = QLabel()
        self.readout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.readout.setMinimumWidth(em * 11)
        self.minus.clicked.connect(lambda: self.step(-1))
        self.plus.clicked.connect(lambda: self.step(1))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(self.minus)
        lay.addWidget(self.readout, 1)
        lay.addWidget(self.plus)
        self.setMaximumWidth(em * 24)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._show()

    # --- spin box like interface -----------------------------------------------------------
    def value(self) -> int:
        return self._value

    def minimum(self) -> int:
        return self._min

    def maximum(self) -> int:
        return self._max

    def setRange(self, lo: int, hi: int) -> None:  # noqa: N802
        self._min, self._max = lo, hi
        self.setValue(self._value)

    def setMaximum(self, hi: int) -> None:  # noqa: N802
        self.setRange(self._min, hi)

    def setSpecialValueText(self, text: str) -> None:  # noqa: N802
        """Text shown instead of the number when the value is the minimum."""
        self._special = text
        self._show()

    def setValue(self, value: int) -> None:  # noqa: N802
        value = min(max(int(value), self._min), self._max)
        changed = value != self._value
        self._value = value
        self._show()
        if changed:
            self.valueChanged.emit(value)

    def text(self) -> str:
        return self.readout.text()

    # --- user ------------------------------------------------------------------------------
    def step(self, delta: int) -> None:
        if self.isEnabled():
            self.setValue(self._value + delta)

    def _show(self) -> None:
        shown = self._special if self._special and self._value == self._min else str(self._value)
        self.readout.setText(shown)
        self.minus.setEnabled(self._value > self._min)
        self.plus.setEnabled(self._value < self._max)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt name
        moves = {Qt.Key.Key_Up: 1, Qt.Key.Key_Right: 1, Qt.Key.Key_Down: -1,
                 Qt.Key.Key_Left: -1, Qt.Key.Key_PageUp: 10, Qt.Key.Key_PageDown: -10}
        key = event.key()
        if key in moves:
            self.step(moves[key])
        elif key == Qt.Key.Key_Home:
            self.setValue(self._min)
        elif key == Qt.Key.Key_End:
            self.setValue(self._max)
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt name
        if not self.hasFocus():
            event.ignore()
            return
        self.step(1 if event.angleDelta().y() > 0 else -1)
        event.accept()
