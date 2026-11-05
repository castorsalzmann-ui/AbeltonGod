"""On/off switch (:class:`Toggle`), a switch with a wrapped text (:class:`ToggleRow`) and the small
dot that says "this parameter is sent" (:class:`ActiveDot`)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QLabel, QSizePolicy, QWidget

from gui import theme


class Toggle(QAbstractButton):
    """Switch. Space / click toggles; ``isChecked`` / ``setChecked`` / ``toggled`` as usual."""

    def __init__(self, checked: bool = False) -> None:
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt name
        h = self.fontMetrics().height()
        return QSize(int(h * 2.0), int(h * 1.15))

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt name
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        on = self.isChecked()
        enabled = self.isEnabled()
        track = QColor(theme.ACCENT if on else theme.NEUTRAL_DIM)
        if not enabled:
            track = QColor(theme.NEUTRAL_DIM)
        p.setPen(QPen(QColor(theme.TEXT) if self.hasFocus() else Qt.GlobalColor.transparent, 1.5))
        p.setBrush(track)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.right() - 3 - d if on else r.left() + 3
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.BG if on else theme.TEXT))
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))


class ToggleRow(QWidget):
    """A switch followed by a text that wraps; clicking the text switches too."""

    toggled = Signal(bool)

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self.toggle = Toggle()
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        self.label.mousePressEvent = lambda _e: self.toggle.click() if self.isEnabled() else None  # type: ignore[method-assign]
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(self.label, 1)
        self.toggle.toggled.connect(self.toggled)
        self.setFocusProxy(self.toggle)

    def isChecked(self) -> bool:  # noqa: N802 - Qt-style name, so tests read like a checkbox
        return self.toggle.isChecked()

    def setChecked(self, on: bool) -> None:  # noqa: N802
        self.toggle.setChecked(on)

    def text(self) -> str:
        return self.label.text()


class ActiveDot(QAbstractButton):
    """Small round switch before a parameter: filled = the parameter is sent, ring = the
    engine's default is used."""

    def __init__(self) -> None:
        super().__init__()
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setToolTip("Gefüllt: der Wert wird mitgeschickt. Leer: Standardwert des Engines.")
        self.accent = False

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt name
        s = int(self.fontMetrics().height() * 0.9)
        return QSize(s, s)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt name
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        r = min(self.width(), self.height()) * 0.26
        color = QColor(theme.ACCENT if self.accent else theme.NEUTRAL)
        if not self.isEnabled():
            color = QColor(theme.NEUTRAL_DIM)
        if self.hasFocus():
            p.setPen(QPen(QColor(theme.TEXT), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, r + 3, r + 3)
        p.setPen(QPen(color, 1.5))
        p.setBrush(color if self.isChecked() else Qt.BrushStyle.NoBrush)
        p.drawEllipse(c, r, r)
