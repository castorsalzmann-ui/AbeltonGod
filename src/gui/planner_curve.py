"""Arrangement planner canvas: section band, energy curve with nodes (drawn like automation in
Live, D-024) and the derived element timeline (one lane per element, filled where the planner's
``derive_timeline`` switches it on), plus an event row. All bars share one x axis.

Mouse on the curve (whole bars, values 0..1 in steps of 0.01):
- click on empty space: new drawn node there (drag to place it);
- press on a drawn node: drag it (it stays between its neighbours);
- press on a default node: a drawn copy replaces it (planner rule: a drawn node drops every
  default node at its bar), then drag;
- Shift + press on a drawn node: a second drawn node on the same bar (a step);
- right click or Delete on a drawn node: remove it.

The widget calls the editing helpers of :class:`gui_core.planner.PlannerModel` and emits
``edited``; the page then runs the planner again and hands the new state back. It computes no
plan values itself."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from gui_core.planner import (
    ELEMENT_LABELS,
    EVENT_LABELS,
    SECTION_LABELS,
    PlannerModel,
)

from . import theme

BEATS_PER_BAR = 4


class PlannerCanvas(QWidget):
    edited = Signal()  # the drawn nodes changed (the page recomputes)

    def __init__(self, model: PlannerModel) -> None:
        super().__init__()
        self.model = model
        self.drag: int | None = None  # index into model.drawn
        self.selected: int | None = None
        self.setObjectName("planner_canvas")
        self.setAccessibleName("Energiekurve")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(int(self._em() * 20))
        self.setFixedHeight(self._needed_height())

    # --- geometry (font units: follows the DPI) ------------------------------------------
    def _em(self) -> float:
        return float(self.fontMetrics().height())

    def _gutter(self) -> float:
        fm = self.fontMetrics()
        names = (*ELEMENT_LABELS.values(), "Events", "Energie")
        return max(fm.horizontalAdvance(t) for t in names) + self._em() * 0.8

    def _band_h(self) -> float:
        return self._em() * 1.5

    def _curve_h(self) -> float:
        return self._em() * 8

    def _lane_h(self) -> float:
        return self._em() * 1.05

    def _curve_top(self) -> float:
        return self._em() * 0.3 + self._band_h()

    def _lanes_top(self) -> float:
        return self._curve_top() + self._curve_h() + self._em() * 0.6

    def _needed_height(self) -> int:
        rows = len(ELEMENT_LABELS) + 1  # + events
        return int(self._lanes_top() + self._lane_h() * rows + self._em() * 0.5)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt name
        return QSize(int(self._em() * 50), self._needed_height())

    def _total(self) -> int:
        return self.model.state.total_bars

    def bar_to_x(self, bar: float) -> float:
        left = self._gutter()
        width = max(1.0, self.width() - left - self._em() * 0.6)
        return left + width * bar / max(1, self._total())

    def x_to_bar(self, x: float) -> int:
        left = self._gutter()
        width = max(1.0, self.width() - left - self._em() * 0.6)
        return min(max(round((x - left) / width * self._total()), 0), self._total())

    def value_to_y(self, value: float) -> float:
        top, h = self._curve_top(), self._curve_h()
        return top + h * (1.0 - value)

    def y_to_value(self, y: float) -> float:
        top, h = self._curve_top(), self._curve_h()
        return min(max(1.0 - (y - top) / h, 0.0), 1.0)

    def _in_curve(self, p: QPointF) -> bool:
        top = self._curve_top() - self._em() * 0.4
        bottom = self._curve_top() + self._curve_h() + self._em() * 0.4
        return p.x() >= self._gutter() - self._em() * 0.4 and top <= p.y() <= bottom

    def _radius(self) -> float:
        return self._em() * 0.45

    def _plan_nodes(self) -> list[dict]:
        plan = self.model.state.plan
        return plan["energy_nodes"] if plan else []

    def drawn_at(self, p: QPointF) -> int | None:
        """Index of the drawn node under ``p`` (the nearest one), or None."""
        best, best_d = None, self._radius() * 1.6
        for i, n in enumerate(self.model.drawn):
            if n["pos"] > self._total():
                continue
            d = abs(self.bar_to_x(n["pos"]) - p.x()) + abs(self.value_to_y(n["value"]) - p.y())
            if d <= best_d:
                best, best_d = i, d
        return best

    def default_at(self, p: QPointF) -> dict | None:
        for n in self._plan_nodes():
            if n["drawn"]:
                continue
            d = abs(self.bar_to_x(n["pos"]) - p.x()) + abs(self.value_to_y(n["value"]) - p.y())
            if d <= self._radius() * 1.6:
                return n
        return None

    # --- interaction ---------------------------------------------------------------------
    def _changed(self) -> None:
        self.edited.emit()
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt name
        p = event.position()
        if not self._total() or not self._in_curve(p):
            super().mousePressEvent(event)
            return
        hit = self.drawn_at(p)
        if event.button() == Qt.MouseButton.RightButton:
            if hit is not None:
                self.model.remove_node(hit)
                self.selected = self.drag = None
                self._changed()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if hit is not None and not shift:
            index = hit
        elif hit is not None:
            n = self.model.drawn[hit]
            index = self.model.add_node(n["pos"], n["value"])
        else:
            default = self.default_at(p)
            if default is not None:
                index = self.model.add_node(default["pos"], default["value"])
            else:
                index = self.model.add_node(self.x_to_bar(p.x()), self.y_to_value(p.y()))
        self.drag = self.selected = index
        if index is not None:
            self._changed()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt name
        p = event.position()
        if self.drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.model.move_node(self.drag, self.x_to_bar(p.x()), self.y_to_value(p.y()))
            self._changed()
            return
        text = self.tooltip_at(p)
        if text:
            QToolTip.showText(event.globalPosition().toPoint(), text, self)
        else:
            QToolTip.hideText()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt name
        self.drag = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt name
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.selected is not None \
                and self.selected < len(self.model.drawn):
            self.model.remove_node(self.selected)
            self.selected = None
            self._changed()
            event.accept()
            return
        super().keyPressEvent(event)

    def tooltip_at(self, p: QPointF) -> str:
        """Text for the point ``p``: a node, a section, or a cell of the element timeline."""
        state = self.model.state
        if not state.total_bars:
            return ""
        bar = self.x_to_bar(p.x())
        if self._in_curve(p):
            hit = self.drawn_at(p)
            if hit is not None:
                n = self.model.drawn[hit]
                return f"Gezeichnet: Takt {n['pos'] + 1}, Energie {n['value']:.2f}"
            d = self.default_at(p)
            if d is not None:
                return f"Standard: Takt {d['pos'] + 1}, Energie {d['value']:.2f}"
        if state.timeline is not None and p.y() >= self._lanes_top():
            for c in state.timeline.cells:
                if c.start <= bar < c.start + c.length:
                    names = [ELEMENT_LABELS[e] for e in ELEMENT_LABELS if e in c.elements]
                    return (f"{SECTION_LABELS.get(c.type, c.type)}: Takt {c.start + 1}-"
                            f"{c.start + c.length}, mittlere Energie {c.energy:.2f}\n"
                            + (", ".join(names) or "keine Elemente"))
        for s in state.sections:
            if s["start_bar"] - 1 <= bar < s["start_bar"] - 1 + s["length_bars"]:
                return (f"{SECTION_LABELS.get(s['type'], s['type'])}: Takt {s['start_bar']}-"
                        f"{s['start_bar'] + s['length_bars'] - 1} ({s['length_bars']} Takte)")
        return ""

    # --- painting ------------------------------------------------------------------------
    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt name
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.PANEL))
        state = self.model.state
        if not state.total_bars:
            p.setPen(QColor(theme.MUTED))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Keine gültige Vorschau")
            p.end()
            return
        em, fm = self._em(), self.fontMetrics()
        muted, border, text = QColor(theme.MUTED), QColor(theme.BORDER), QColor(theme.TEXT)
        band_top = em * 0.3
        curve_top, curve_h = self._curve_top(), self._curve_h()
        lanes_top, lh = self._lanes_top(), self._lane_h()
        bottom = lanes_top + lh * (len(ELEMENT_LABELS) + 1)
        right = self.bar_to_x(state.total_bars)

        # section band and section borders
        for i, s in enumerate(state.sections):
            x0 = self.bar_to_x(s["start_bar"] - 1)
            x1 = self.bar_to_x(s["start_bar"] - 1 + s["length_bars"])
            fill = QColor(theme.FIELD if i % 2 else theme.BG)
            p.fillRect(QRectF(x0, band_top, x1 - x0, self._band_h()), fill)
            p.setPen(text)
            name = fm.elidedText(SECTION_LABELS.get(s["type"], s["type"]),
                                 Qt.TextElideMode.ElideRight, int(max(0, x1 - x0 - em * 0.3)))
            p.drawText(QRectF(x0 + em * 0.15, band_top, x1 - x0, self._band_h()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)
            p.setPen(QPen(border))
            p.drawLine(QPointF(x0, band_top), QPointF(x0, bottom))
        p.drawLine(QPointF(right, band_top), QPointF(right, bottom))

        # curve frame and guide lines (0, 0.5, 1)
        p.setPen(muted)
        p.drawText(QPointF(em * 0.3, curve_top + fm.ascent()), "Energie")
        for v in (0.0, 0.5, 1.0):
            y = self.value_to_y(v)
            p.setPen(QPen(border, 1, Qt.PenStyle.DotLine))
            p.drawLine(QPointF(self._gutter(), y), QPointF(right, y))
            p.setPen(muted)
            label = f"{v:g}"
            p.drawText(QPointF(self._gutter() - fm.horizontalAdvance(label) - em * 0.2,
                               y + fm.ascent() * 0.4), label)

        # change grid (where elements may switch) as faint ticks under the curve
        if state.timeline is not None:
            p.setPen(QPen(border, 1, Qt.PenStyle.DotLine))
            for c in state.timeline.cells:
                x = self.bar_to_x(c.start)
                p.drawLine(QPointF(x, curve_top + curve_h), QPointF(x, lanes_top))

        # energy line through the plan's nodes, in plan order (a pair is a vertical step)
        nodes = self._plan_nodes()
        if nodes:
            path = QPainterPath()
            path.moveTo(self.bar_to_x(nodes[0]["pos"]), self.value_to_y(nodes[0]["value"]))
            for n in nodes[1:]:
                path.lineTo(self.bar_to_x(n["pos"]), self.value_to_y(n["value"]))
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setPen(QPen(QColor(theme.ACCENT), 2))
            p.drawPath(path)
            r = self._radius() * 0.6
            p.setPen(QPen(QColor(theme.NEUTRAL), 1))
            p.setBrush(QColor(theme.PANEL))
            for n in nodes:
                if not n["drawn"]:
                    p.drawEllipse(QPointF(self.bar_to_x(n["pos"]), self.value_to_y(n["value"])),
                                  r, r)
        # drawn nodes (also when the planner refused them: the user sees what to fix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = self._radius()
        for i, n in enumerate(self.model.drawn):
            if n["pos"] > state.total_bars:
                continue
            p.setPen(QPen(QColor(theme.TEXT if i == self.selected else theme.ACCENT_TEXT), 1.5))
            p.setBrush(QColor(theme.ACCENT if state.ok else theme.ERROR))
            p.drawEllipse(QPointF(self.bar_to_x(n["pos"]), self.value_to_y(n["value"])), r, r)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setBrush(Qt.BrushStyle.NoBrush)

        # element lanes
        lane_fill = QColor(theme.NEUTRAL)
        lane_fill.setAlpha(190)
        cells = state.timeline.cells if state.timeline is not None else []
        for row, (key, label) in enumerate(ELEMENT_LABELS.items()):
            y = lanes_top + row * lh
            p.setPen(muted)
            p.drawText(QPointF(em * 0.3, y + lh * 0.5 + fm.ascent() * 0.4), label)
            for c in cells:
                if key in c.elements:
                    x0, x1 = self.bar_to_x(c.start), self.bar_to_x(c.start + c.length)
                    p.fillRect(QRectF(x0 + 0.5, y + 2, max(1.0, x1 - x0 - 1), lh - 4), lane_fill)

        # events: riser as a ramp, gap as a dark block, the rest as ticks
        y = lanes_top + len(ELEMENT_LABELS) * lh
        p.setPen(muted)
        p.drawText(QPointF(em * 0.3, y + lh * 0.5 + fm.ascent() * 0.4), "Events")
        if state.timeline is not None:
            accent = QColor(theme.ACCENT)
            for ev in state.timeline.events:
                x0 = self.bar_to_x(ev.start_beat / BEATS_PER_BAR)
                x1 = self.bar_to_x((ev.start_beat + ev.length_beats) / BEATS_PER_BAR)
                if ev.kind == "riser":
                    ramp = QPainterPath()
                    ramp.moveTo(x0, y + lh - 2)
                    ramp.lineTo(x1, y + 2)
                    ramp.lineTo(x1, y + lh - 2)
                    ramp.closeSubpath()
                    p.fillPath(ramp, accent)
                elif ev.kind == "pre_drop_gap":
                    p.fillRect(QRectF(x0, y + 2, max(2.0, x1 - x0), lh - 4), QColor(theme.ERROR))
                else:
                    p.setPen(QPen(accent if ev.kind == "impact" else QColor(theme.TEXT), 2))
                    p.drawLine(QPointF(x0, y + 2), QPointF(x0, y + lh - 2))
        p.end()


def event_summary(model: PlannerModel) -> str:
    """Count of each event kind in the current timeline, for the page's legend line."""
    tl = model.state.timeline
    if tl is None:
        return ""
    counts: dict[str, int] = {}
    for ev in tl.events:
        counts[ev.kind] = counts.get(ev.kind, 0) + 1
    return ", ".join(f"{EVENT_LABELS.get(k, k)} {n}" for k, n in counts.items())
