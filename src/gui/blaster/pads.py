"""Two drawn editors for the blaster: :class:`XYPad` (pitch start / end) and :class:`CurveEditor`
(sweep time and sweep curve). Both work on contract values through a ``ValueMap`` and emit the
contract field name, like the widget kit. Shift = fine, Ctrl+click = ``ctrlClicked`` (the
window resets to the default), arrow keys move by the map's steps. All painting ends its
QPainter (PR #412)."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from gui_core.valuemap import ValueMap

from . import skin

KEY_LEFT, KEY_RIGHT = Qt.Key.Key_Left, Qt.Key.Key_Right
KEY_UP, KEY_DOWN = Qt.Key.Key_Up, Qt.Key.Key_Down


class _Pad(QWidget):
    edited = Signal(str, object)
    committed = Signal(str)
    ctrlClicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.accent = QColor("#ff4a2a")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._drag = False
        self._fine: tuple[QPointF, object] | None = None

    def set_accent(self, color: str) -> None:
        self.accent = QColor(color)
        self.update()

    def _plot(self) -> QRectF:
        m = self.fontMetrics().height() * 0.9
        return QRectF(m, m * 0.6, self.width() - 1.6 * m, self.height() - 1.9 * m)

    def _frame(self, p: QPainter) -> QRectF:
        r = self._plot()
        p.setPen(QPen(QColor(skin.LINE), 1))
        p.setBrush(QColor(skin.FIELD))
        p.drawRoundedRect(r, 4, 4)
        if self.hasFocus():
            p.setPen(QPen(QColor(skin.STEEL_HI), 1, Qt.PenStyle.DotLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(-2, -2, 2, 2), 5, 5)
        return r


class XYPad(_Pad):
    """x = ``pitch_start_hz``, y = ``pitch_end_hz`` (high at the top), both on their log maps."""

    def __init__(self, x_name: str, y_name: str, x_map: ValueMap, y_map: ValueMap) -> None:
        super().__init__()
        self.x_name, self.y_name, self.xm, self.ym = x_name, y_name, x_map, y_map
        self.x_val: float = x_map.minimum
        self.y_val: float = y_map.minimum
        self.setMinimumSize(int(self.fontMetrics().height() * 8), int(
            self.fontMetrics().height() * 8))
        self.setAccessibleName("Start-Ton und End-Ton")
        self.setToolTip("Waagerecht: Start-Ton, senkrecht: End-Ton. Umschalt = fein, "
                        "Strg+Klick = Standard. Pfeiltasten bewegen den Punkt.")

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt name
        u = self.fontMetrics().height()
        return QSize(u * 11, u * 9)

    def set_values(self, x: float, y: float) -> None:
        self.x_val, self.y_val = x, y
        self.update()

    def _pt(self) -> QPointF:
        r = self._plot()
        fx = self.xm.to_pos(self.x_val) / self.xm.pos_max
        fy = self.ym.to_pos(self.y_val) / self.ym.pos_max
        return QPointF(r.left() + fx * r.width(), r.bottom() - fy * r.height())

    def pos_of(self, x: float, y: float) -> QPointF:
        """Widget position of the point for the given values (tests click there)."""
        old = self.x_val, self.y_val
        self.x_val, self.y_val = x, y
        pt = self._pt()
        self.x_val, self.y_val = old
        return pt

    def _positions_at(self, pt: QPointF) -> tuple[int, int]:
        r = self._plot()
        fx = min(1.0, max(0.0, (pt.x() - r.left()) / r.width()))
        fy = min(1.0, max(0.0, (r.bottom() - pt.y()) / r.height()))
        return int(round(fx * self.xm.pos_max)), int(round(fy * self.ym.pos_max))

    def _move_to(self, px: int, py: int) -> None:
        nx, ny = self.xm.from_pos(px), self.ym.from_pos(py)
        if nx != self.x_val and px != self.xm.to_pos(self.x_val):
            self.x_val = nx
            self.edited.emit(self.x_name, nx)
        if ny != self.y_val and py != self.ym.to_pos(self.y_val):
            self.y_val = ny
            self.edited.emit(self.y_name, ny)
        self.update()

    def _finish(self) -> None:
        self.committed.emit(self.x_name)
        self.committed.emit(self.y_name)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt name
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            r = self._frame(p)
            p.setPen(QPen(skin.qc(self.accent, 0.12), 1))
            for hz in (100, 1000):  # decade lines
                if self.xm.minimum < hz < self.xm.maximum:
                    x = r.left() + self.xm.to_pos(hz) / self.xm.pos_max * r.width()
                    p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
                if self.ym.minimum < hz < self.ym.maximum:
                    y = r.bottom() - self.ym.to_pos(hz) / self.ym.pos_max * r.height()
                    p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(QPen(skin.qc(skin.MUTED, 0.45), 1, Qt.PenStyle.DashLine))
            p.drawLine(r.bottomLeft(), r.topRight())  # start = end
            pt = self._pt()
            p.setPen(QPen(skin.qc(self.accent, 0.5), 1))
            p.drawLine(QPointF(pt.x(), r.top()), QPointF(pt.x(), r.bottom()))
            p.drawLine(QPointF(r.left(), pt.y()), QPointF(r.right(), pt.y()))
            rad = self.fontMetrics().height() * 0.42
            p.setPen(QPen(QColor(skin.TEXT), 1.5))
            p.setBrush(self.accent)
            p.drawEllipse(pt, rad, rad)
            p.setPen(QColor(skin.MUTED))
            f = p.font()
            f.setPointSizeF(max(6.0, f.pointSizeF() * 0.85))
            p.setFont(f)
            p.drawText(QPointF(r.left() + 4, r.bottom() + self.fontMetrics().height() * 0.8),
                       "Start-Ton  >")
            p.drawText(QPointF(r.right() - self.fontMetrics().horizontalAdvance("End-Ton ^") - 2,
                               r.top() + self.fontMetrics().height()), "End-Ton ^")
        finally:
            p.end()

    def mousePressEvent(self, e) -> None:  # noqa: N802 - Qt name
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.ctrlClicked.emit()
            return
        self._drag, self._fine = True, None
        self._move_to(*self._positions_at(e.position()))

    def mouseMoveEvent(self, e) -> None:  # noqa: N802 - Qt name
        if not self._drag:
            return
        if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:  # 1/5 of the pointer travel
            if self._fine is None:
                self._fine = (e.position(), (self.xm.to_pos(self.x_val),
                                             self.ym.to_pos(self.y_val)))
            p0, (px0, py0) = self._fine  # type: ignore[misc]
            r = self._plot()
            dx = (e.position().x() - p0.x()) / r.width() * self.xm.pos_max * 0.2
            dy = -(e.position().y() - p0.y()) / r.height() * self.ym.pos_max * 0.2
            self._move_to(min(self.xm.pos_max, max(0, px0 + int(round(dx)))),
                          min(self.ym.pos_max, max(0, py0 + int(round(dy)))))
        else:
            self._fine = None
            self._move_to(*self._positions_at(e.position()))

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802 - Qt name
        if self._drag:
            self._drag = False
            self._finish()

    def keyPressEvent(self, e) -> None:  # noqa: N802 - Qt name
        fine = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        px, py = self.xm.to_pos(self.x_val), self.ym.to_pos(self.y_val)
        sx, sy = (1, 1) if fine else (self.xm.single_step(), self.ym.single_step())
        moves = {KEY_RIGHT: (px + sx, py), KEY_LEFT: (px - sx, py),
                 KEY_UP: (px, py + sy), KEY_DOWN: (px, py - sy)}
        if e.key() in moves:
            nx, ny = moves[e.key()]
            self._move_to(min(self.xm.pos_max, max(0, nx)), min(self.ym.pos_max, max(0, ny)))
            self._finish()
            e.accept()
        else:
            super().keyPressEvent(e)


class CurveEditor(_Pad):
    """The sweep: pitch over time from ``pitch_start_hz`` to ``pitch_end_hz``. The end handle
    moves ``sweep_ms`` (log scale), the middle handle bends ``sweep_curve``. The drawn line is
    the contract formula f(t) = start * (end / start) ^ (min(1, t / sweep) ^ curve)."""

    PAD_LO, PAD_SPAN = 0.15, 0.7  # the sweep end sits between 15 % and 85 % of the width

    def __init__(self, sweep_map: ValueMap, curve_map: ValueMap) -> None:
        super().__init__()
        self.sm, self.cm = sweep_map, curve_map
        self.start, self.end = 3000.0, 200.0
        self.sweep: float = sweep_map.minimum
        self.curve: float = 1.0
        self._grab = ""
        u = self.fontMetrics().height()
        self.setMinimumSize(u * 8, u * 6)
        self.setAccessibleName("Sweep-Kurve")
        self.setToolTip("Rechter Punkt: Sweep-Zeit. Mittlerer Punkt: Sweep-Kurve (unter 1 früh, "
                        "über 1 spät). Umschalt = fein, Strg+Klick = Standard.")

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt name
        u = self.fontMetrics().height()
        return QSize(u * 11, u * 7)

    def set_values(self, start: float, end: float, sweep: float, curve: float) -> None:
        self.start, self.end, self.sweep, self.curve = start, end, sweep, curve
        self.update()

    # geometry: pitch rows between max(start,end) (top) and min (bottom), log scale
    def _xe(self, r: QRectF) -> float:
        f = self.sm.to_pos(self.sweep) / self.sm.pos_max
        return r.left() + (self.PAD_LO + self.PAD_SPAN * f) * r.width()

    def _y(self, r: QRectF, q: float) -> float:
        """Screen y for sweep progress q (0 = start pitch, 1 = end pitch)."""
        top, bot = r.top() + r.height() * 0.1, r.bottom() - r.height() * 0.1
        if self.start >= self.end:
            return top + q * (bot - top)
        return bot - q * (bot - top)

    def curve_points(self, r: QRectF | None = None, n: int = 64) -> list[QPointF]:
        r = r or self._plot()
        xe = self._xe(r)
        pts = []
        for i in range(n + 1):
            t = i / n
            pts.append(QPointF(r.left() + t * (xe - r.left()), self._y(r, t ** self.curve)))
        pts.append(QPointF(r.right(), self._y(r, 1.0)))
        return pts

    def handle_positions(self) -> tuple[QPointF, QPointF]:
        """(sweep-time handle, curve handle) in widget coordinates."""
        r = self._plot()
        xe = self._xe(r)
        return (QPointF(xe, self._y(r, 1.0)),
                QPointF(r.left() + (xe - r.left()) / 2, self._y(r, 0.5 ** self.curve)))

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt name
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            r = self._frame(p)
            pts = self.curve_points(r)
            p.setPen(QPen(skin.qc(self.accent, 0.12), 1))
            for i in range(1, 4):
                p.drawLine(QPointF(r.left(), r.top() + r.height() * i / 4),
                           QPointF(r.right(), r.top() + r.height() * i / 4))
            p.setPen(QPen(self.accent, 2.2))
            for a, b in zip(pts, pts[1:], strict=False):
                p.drawLine(a, b)
            h_end, h_mid = self.handle_positions()
            rad = self.fontMetrics().height() * 0.38
            p.setBrush(self.accent)
            p.setPen(QPen(QColor(skin.TEXT), 1.5))
            p.drawEllipse(h_end, rad, rad)
            p.setBrush(QColor(skin.FIELD))
            p.drawEllipse(h_mid, rad, rad)
            p.setPen(QColor(skin.MUTED))
            f = p.font()
            f.setPointSizeF(max(6.0, f.pointSizeF() * 0.85))
            p.setFont(f)
            p.drawText(QPointF(r.left() + 4, r.bottom() + self.fontMetrics().height() * 0.8),
                       "Zeit  >")
        finally:
            p.end()

    # interaction
    def _nearest(self, pt: QPointF) -> str:
        h_end, h_mid = self.handle_positions()
        d_end = math.hypot(pt.x() - h_end.x(), pt.y() - h_end.y())
        d_mid = math.hypot(pt.x() - h_mid.x(), pt.y() - h_mid.y())
        return "sweep" if d_end <= d_mid else "curve"

    def _set_sweep(self, x: float) -> None:
        r = self._plot()
        f = (x - r.left()) / r.width()
        f = min(1.0, max(0.0, (f - self.PAD_LO) / self.PAD_SPAN))
        pos = int(round(f * self.sm.pos_max))
        if pos != self.sm.to_pos(self.sweep):
            self.sweep = self.sm.from_pos(pos)
            self.edited.emit("sweep_ms", self.sweep)
            self.update()

    def _set_curve(self, y: float) -> None:
        r = self._plot()
        y0, y1 = self._y(r, 0.0), self._y(r, 1.0)
        if abs(y1 - y0) < 1:
            return
        q = min(0.98, max(0.02, (y - y0) / (y1 - y0)))
        value = self.cm.clamp(round(math.log(q) / math.log(0.5), 3))
        if value != self.curve:
            self.curve = value
            self.edited.emit("sweep_curve", value)
            self.update()

    def mousePressEvent(self, e) -> None:  # noqa: N802 - Qt name
        if e.button() != Qt.MouseButton.LeftButton:
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.ctrlClicked.emit()
            return
        self._grab = self._nearest(e.position())
        self._fine = None
        self.mouseMoveEvent(e)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802 - Qt name
        if not self._grab:
            return
        pt = e.position()
        if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            if self._fine is None:
                self._fine = (pt, (self.sm.to_pos(self.sweep), self.curve))
            p0, (pos0, curve0) = self._fine  # type: ignore[misc]
            if self._grab == "sweep":
                r = self._plot()
                dpos = (pt.x() - p0.x()) / (self.PAD_SPAN * r.width()) * self.sm.pos_max * 0.2
                pos = min(self.sm.pos_max, max(0, pos0 + int(round(dpos))))
                if pos != self.sm.to_pos(self.sweep):
                    self.sweep = self.sm.from_pos(pos)
                    self.edited.emit("sweep_ms", self.sweep)
                    self.update()
            else:
                h = self._plot().height() * 0.8
                value = self.cm.clamp(round(curve0 + (pt.y() - p0.y()) / h * 0.2 * (
                    self.cm.maximum - self.cm.minimum) * (1 if self.start >= self.end else -1), 3))
                if value != self.curve:
                    self.curve = value
                    self.edited.emit("sweep_curve", value)
                    self.update()
            return
        self._fine = None
        if self._grab == "sweep":
            self._set_sweep(pt.x())
        else:
            self._set_curve(pt.y())

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802 - Qt name
        if self._grab:
            name = "sweep_ms" if self._grab == "sweep" else "sweep_curve"
            self._grab = ""
            self.committed.emit(name)

    def keyPressEvent(self, e) -> None:  # noqa: N802 - Qt name
        fine = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if e.key() in (KEY_LEFT, KEY_RIGHT):
            step = 1 if fine else self.sm.single_step()
            pos = self.sm.to_pos(self.sweep) + (step if e.key() == KEY_RIGHT else -step)
            self.sweep = self.sm.from_pos(min(self.sm.pos_max, max(0, pos)))
            self.edited.emit("sweep_ms", self.sweep)
            self.committed.emit("sweep_ms")
        elif e.key() in (KEY_UP, KEY_DOWN):
            step = 0.01 if fine else 0.1
            value = self.cm.clamp(round(self.curve + (step if e.key() == KEY_UP else -step), 3))
            self.curve = value
            self.edited.emit("sweep_curve", value)
            self.committed.emit("sweep_curve")
        else:
            super().keyPressEvent(e)
            return
        self.update()
        e.accept()
