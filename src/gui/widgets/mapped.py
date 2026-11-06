"""Slider and rotary knob that work on contract values through a :class:`ValueMap`.

Both keep the value they were given exactly (a preset's 0.35 stays 0.35); only dragging, the
keyboard and the wheel produce rounded values. Both know the range a linked parameter allows
(``set_limits``) and cannot be moved outside it; the forbidden part is drawn dimmed.

Keyboard: arrows move 1 % of the travel (Shift: one position), Page Up/Down 10 %, Home/End to
the ends of the allowed range. The wheel only acts while the widget has focus, so scrolling a
page does not change values by accident.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPen
from PySide6.QtWidgets import QAbstractSlider, QSizePolicy

from gui import theme
from gui_core.valuemap import ValueMap


class MappedSlider(QAbstractSlider):
    userChanged = Signal(object)  # the new value, after drag / keys / wheel
    released = Signal()  # drag finished (heavy updates may follow)
    resetRequested = Signal()  # double click
    ctrlClicked = Signal()  # Ctrl + click (the blaster resets to the default)

    def __init__(self, vmap: ValueMap, accent: bool = True) -> None:
        super().__init__()
        self.vmap = vmap
        self.accent = accent
        self.accent_color: QColor | None = None  # own accent instead of theme.ACCENT
        self.inactive = False  # parameter is not sent: drawn muted
        self._value: float = vmap.minimum
        self._limit_lo: float = vmap.minimum
        self._limit_hi: float = vmap.maximum
        self.setRange(0, vmap.pos_max)
        self.setSingleStep(vmap.single_step())
        self.setPageStep(vmap.page_step())
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(False)

    # --- value -----------------------------------------------------------------------------
    def value_exact(self) -> float:
        return self._value

    def set_value(self, value: float) -> None:
        """Programmatic: shows ``value`` (kept exactly, clamped into the contract range)."""
        self._value = self.vmap.clamp(value)
        self.blockSignals(True)
        self.setValue(self.vmap.to_pos(self._value))
        self.blockSignals(False)
        self.update()

    def set_limits(self, lo: float, hi: float) -> None:
        self._limit_lo, self._limit_hi = lo, hi
        self.update()

    @property
    def limits(self) -> tuple[float, float]:
        return self._limit_lo, self._limit_hi

    def _limit_positions(self) -> tuple[int, int]:
        lo = 0 if self._limit_lo <= self.vmap.minimum else self.vmap.to_pos(self._limit_lo)
        hi = (self.vmap.pos_max if self._limit_hi >= self.vmap.maximum
              else self.vmap.to_pos(self._limit_hi))
        return lo, hi

    def _fraction(self, pos: int) -> float:
        return pos / self.vmap.pos_max if self.vmap.pos_max else 0.0

    def move_to_position(self, pos: int) -> None:
        """User move: clamp into the allowed range, keep the value inside the limits."""
        lo_pos, hi_pos = self._limit_positions()
        pos = min(max(int(pos), lo_pos), hi_pos)
        if pos == self.vmap.to_pos(self._value):
            return  # same place: the exact value (e.g. from a preset) stays
        value = self.vmap.from_pos(pos)
        if self._limit_lo > self.vmap.minimum:
            value = self._limit_lo if pos <= lo_pos else max(value, self._limit_lo)
        if self._limit_hi < self.vmap.maximum:
            value = self._limit_hi if pos >= hi_pos else min(value, self._limit_hi)
        if self.vmap.integer:
            value = int(round(value))
        self.set_value(value)
        self.userChanged.emit(self._value)

    # --- keyboard / wheel -------------------------------------------------------------------
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt name
        key = event.key()
        fine = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        single = 1 if fine else self.singleStep()
        pos = self.vmap.to_pos(self._value)
        lo_pos, hi_pos = self._limit_positions()
        moves = {
            Qt.Key.Key_Right: pos + single, Qt.Key.Key_Up: pos + single,
            Qt.Key.Key_Left: pos - single, Qt.Key.Key_Down: pos - single,
            Qt.Key.Key_PageUp: pos + self.pageStep(), Qt.Key.Key_PageDown: pos - self.pageStep(),
            Qt.Key.Key_Home: lo_pos, Qt.Key.Key_End: hi_pos,
        }
        if key in moves and self.isEnabled():
            self.move_to_position(moves[key])
            self.released.emit()
            event.accept()
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt name
        if not self.hasFocus() or not self.isEnabled():
            event.ignore()  # let the scroll area scroll
            return
        steps = 1 if event.angleDelta().y() > 0 else -1
        self.move_to_position(self.vmap.to_pos(self._value) + steps * self.singleStep())
        self.released.emit()
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt name
        self.resetRequested.emit()

    # --- colours -----------------------------------------------------------------------------
    def _fill(self) -> QColor:
        if self.inactive:
            return QColor(theme.ACCENT_DIM if self.accent else theme.NEUTRAL_DIM)
        if self.accent and self.accent_color is not None:
            return QColor(self.accent_color)
        return QColor(theme.ACCENT if self.accent else theme.NEUTRAL)

    def _groove(self) -> QColor:
        if self.accent and not self.inactive and self.accent_color is not None:
            return QColor(self.accent_color).darker(320)
        return QColor(theme.ACCENT_DIM if self.accent and not self.inactive else theme.NEUTRAL_DIM
                      ).darker(180)

    def _ctrl(self, event) -> bool:
        """Ctrl + left click: signal and swallow (no move)."""
        if (event.button() == Qt.MouseButton.LeftButton
                and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.ctrlClicked.emit()
            return True
        return False

    def _em(self) -> int:
        return self.fontMetrics().height()


class TrackSlider(MappedSlider):
    def __init__(self, vmap: ValueMap, accent: bool = False) -> None:
        super().__init__(vmap, accent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._dragging = False

    def sizeHint(self):  # noqa: N802 - Qt name
        from PySide6.QtCore import QSize
        return QSize(self._em() * 12, int(self._em() * 1.5))

    def minimumSizeHint(self):  # noqa: N802 - Qt name
        from PySide6.QtCore import QSize
        return QSize(self._em() * 5, int(self._em() * 1.5))

    def _x_of(self, fraction: float) -> float:
        r = self._em() * 0.5
        return r + fraction * (self.width() - 2 * r)

    def _pos_at(self, x: float) -> int:
        r = self._em() * 0.5
        span = max(1.0, self.width() - 2 * r)
        return int(round(min(max((x - r) / span, 0.0), 1.0) * self.vmap.pos_max))

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt name
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self.height()
        cy = h / 2
        gh = max(3.0, self._em() * 0.28)
        left, right = self._x_of(0), self._x_of(1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._groove())
        p.drawRoundedRect(QRectF(left, cy - gh / 2, right - left, gh), gh / 2, gh / 2)
        lo_pos, hi_pos = self._limit_positions()
        p.setBrush(QColor(theme.BLOCKED))
        if lo_pos > 0:
            x = self._x_of(self._fraction(lo_pos))
            p.drawRoundedRect(QRectF(left, cy - gh / 2, x - left, gh), gh / 2, gh / 2)
            p.setPen(QPen(QColor(theme.BLOCKED_EDGE), 1.5))
            p.drawLine(QPointF(x, cy - gh * 1.4), QPointF(x, cy + gh * 1.4))
            p.setPen(Qt.PenStyle.NoPen)
        if hi_pos < self.vmap.pos_max:
            x = self._x_of(self._fraction(hi_pos))
            p.drawRoundedRect(QRectF(x, cy - gh / 2, right - x, gh), gh / 2, gh / 2)
            p.setPen(QPen(QColor(theme.BLOCKED_EDGE), 1.5))
            p.drawLine(QPointF(x, cy - gh * 1.4), QPointF(x, cy + gh * 1.4))
            p.setPen(Qt.PenStyle.NoPen)
        pos = self.vmap.to_pos(self._value)
        xv = self._x_of(self._fraction(pos))
        bipolar = self.vmap.minimum < 0 < self.vmap.maximum and not self.vmap.log
        x0 = self._x_of(self._fraction(self.vmap.to_pos(0))) if bipolar else left
        p.setBrush(self._fill())
        p.drawRoundedRect(QRectF(min(x0, xv), cy - gh / 2, abs(xv - x0), gh), gh / 2, gh / 2)
        r = self._em() * 0.36
        ring = QColor(theme.TEXT) if self.hasFocus() else self._fill()
        p.setPen(QPen(ring, 2 if self.hasFocus() else 1.5))
        p.setBrush(QColor(theme.BG) if self.inactive else self._fill())
        p.drawEllipse(QPointF(xv, cy), r, r)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt name
        if self.isEnabled() and self._ctrl(event):
            return
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self._dragging = True
            self._fine: tuple[float, int] | None = None
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.move_to_position(self._pos_at(event.position().x()))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt name
        if not self._dragging:
            return
        x = event.position().x()
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:  # fine: 1/5 of the travel
            if self._fine is None:
                self._fine = (x, self.vmap.to_pos(self._value))
            x0, pos0 = self._fine
            span = max(1.0, self.width() - self._em())
            self.move_to_position(pos0 + int(round((x - x0) / span * self.vmap.pos_max * 0.2)))
        else:
            self._fine = None
            self.move_to_position(self._pos_at(x))

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt name
        if self._dragging:
            self._dragging = False
            self.released.emit()


class KnobDial(MappedSlider):
    START_DEG = 225.0  # bottom left, 270 degrees clockwise to bottom right
    SWEEP_DEG = 270.0

    def __init__(self, vmap: ValueMap, accent: bool = True) -> None:
        super().__init__(vmap, accent)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._press: tuple[float, float, int] | None = None

    def sizeHint(self):  # noqa: N802 - Qt name
        from PySide6.QtCore import QSize
        side = int(self._em() * 3.6)
        return QSize(side, side)

    def _arc(self, p: QPainter, rect: QRectF, f0: float, f1: float, color: QColor,
             width: float) -> None:
        if f1 - f0 <= 0:
            return
        p.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        start = (self.START_DEG - f0 * self.SWEEP_DEG) * 16
        span = -(f1 - f0) * self.SWEEP_DEG * 16
        p.drawArc(rect, int(start), int(span))

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt name
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        pad = self._em() * 0.35
        width = max(3.0, self._em() * 0.3)
        rect = QRectF(pad, pad, w - 2 * pad, self.height() - 2 * pad)
        self._arc(p, rect, 0, 1, self._groove(), width)
        lo_pos, hi_pos = self._limit_positions()
        edge = QColor(theme.BLOCKED_EDGE)
        self._arc(p, rect.adjusted(-pad * 0.5, -pad * 0.5, pad * 0.5, pad * 0.5),
                  0, self._fraction(lo_pos) if lo_pos > 0 else 0, edge, 2)
        if hi_pos < self.vmap.pos_max:
            self._arc(p, rect.adjusted(-pad * 0.5, -pad * 0.5, pad * 0.5, pad * 0.5),
                      self._fraction(hi_pos), 1, edge, 2)
        f = self._fraction(self.vmap.to_pos(self._value))
        bipolar = self.vmap.minimum < 0 < self.vmap.maximum and not self.vmap.log
        f0 = self._fraction(self.vmap.to_pos(0)) if bipolar else 0.0
        self._arc(p, rect, min(f0, f), max(f0, f), self._fill(), width)
        # pointer
        angle = math.radians(self.START_DEG - f * self.SWEEP_DEG)
        c = rect.center()
        r = rect.width() / 2 - width * 1.6
        tip = QPointF(c.x() + r * math.cos(angle), c.y() - r * math.sin(angle))
        p.setPen(QPen(QColor(theme.TEXT) if not self.inactive else QColor(theme.MUTED), 2,
                      Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(c.x() + 0.25 * r * math.cos(angle), c.y() - 0.25 * r * math.sin(angle)),
                   tip)
        if self.hasFocus():
            p.setPen(QPen(QColor(theme.TEXT), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, w / 2 - 1, w / 2 - 1)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt name
        if self.isEnabled() and self._ctrl(event):
            return
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self._press = (event.position().x(), event.position().y(),
                           self.vmap.to_pos(self._value))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt name
        if self._press is None:
            return
        x0, y0, pos0 = self._press
        travel = self._em() * 12.0  # pixels for the whole range
        fine = 0.2 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1.0
        delta = ((y0 - event.position().y()) + (event.position().x() - x0)) / travel
        self.move_to_position(pos0 + int(round(delta * fine * self.vmap.pos_max)))

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt name
        if self._press is not None:
            self._press = None
            self.released.emit()
