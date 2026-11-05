"""Section timeline of a Goa plan: energy bars on top, one lane per track below, the section
names rotated underneath. It only draws a :class:`gui_core.goa.TimelinePlan`; the numbers come
from the generator's arrangement data."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from gui_core.goa import SectionRow, TimelinePlan

from . import theme


class TimelineWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.plan: TimelinePlan | None = None
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setObjectName("timeline")

    def set_plan(self, plan: TimelinePlan | None) -> None:
        self.plan = plan
        self.setMinimumHeight(self._needed_height())
        self.updateGeometry()
        self.update()

    # --- geometry (font units, so it follows the DPI) ------------------------------------
    def _em(self) -> float:
        return float(self.fontMetrics().height())

    def _gutter(self) -> float:
        if self.plan is None:
            return 0.0
        fm = self.fontMetrics()
        names = (*self.plan.tracks, "Energie")
        return max(fm.horizontalAdvance(t) for t in names) + self._em()

    def _energy_h(self) -> float:
        return self._em() * 4.5

    def _lane_h(self) -> float:
        return self._em() * 1.2

    def _names_h(self) -> float:
        if self.plan is None:
            return 0.0
        fm = self.fontMetrics()
        longest = max((fm.horizontalAdvance(s.name) for s in self.plan.sections), default=0)
        return min(longest, self._em() * 9) + self._em() * 0.5

    def _needed_height(self) -> int:
        if self.plan is None:
            return int(self._em() * 3)
        return int(self._energy_h() + self._lane_h() * len(self.plan.tracks) + self._names_h()
                   + self._em() * 1.5)

    def sizeHint(self):  # noqa: N802 - Qt name
        from PySide6.QtCore import QSize

        return QSize(int(self._em() * 40), self._needed_height())

    def section_spans(self) -> list[tuple[SectionRow, float, float]]:
        """``(section, x_start, x_end)`` in widget pixels."""
        if self.plan is None or not self.plan.total_bars:
            return []
        left = self._gutter()
        width = max(1.0, self.width() - left - self._em() * 0.5)
        total = self.plan.total_bars
        return [(s, left + width * (s.start_bar - 1) / total,
                 left + width * (s.start_bar - 1 + s.bars) / total)
                for s in self.plan.sections]

    def section_at(self, x: float) -> SectionRow | None:
        for s, x0, x1 in self.section_spans():
            if x0 <= x < x1:
                return s
        return None

    # --- interaction ---------------------------------------------------------------------
    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt name
        s = self.section_at(event.position().x())
        if s is not None:
            QToolTip.showText(
                event.globalPosition().toPoint(),
                f"{s.name}: Takt {s.start_bar} bis {s.start_bar + s.bars - 1} "
                f"({s.bars} Takte), Energie {s.energy:.2f}\n" + ", ".join(s.elements), self)
        else:
            QToolTip.hideText()

    # --- painting ------------------------------------------------------------------------
    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt name
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.fillRect(self.rect(), QColor(theme.PANEL))
        if self.plan is None:
            p.setPen(QColor(theme.MUTED))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Keine gültige Vorschau")
            return
        em, fm = self._em(), self.fontMetrics()
        eh, lh = self._energy_h(), self._lane_h()
        top = em * 0.5
        muted, border = QColor(theme.MUTED), QColor(theme.BORDER)
        lane_fill = QColor(theme.MUTED)
        lane_fill.setAlpha(170)
        bar_fill = QColor(theme.ACCENT)
        bar_fill.setAlpha(210)
        spans = self.section_spans()
        # energy bars (full scale = 1.0)
        p.setPen(muted)
        p.drawText(QPointF(em * 0.3, top + fm.ascent()), "Energie")
        for s, x0, x1 in spans:
            h = max(1.0, eh * s.energy)
            p.fillRect(QRectF(x0 + 0.5, top + eh - h, max(1.0, x1 - x0 - 1), h), bar_fill)
        # lanes
        y = top + eh + em * 0.4
        for i, track in enumerate(self.plan.tracks):
            ly = y + i * lh
            p.setPen(muted)
            p.drawText(QPointF(em * 0.3, ly + lh * 0.5 + fm.ascent() * 0.4), track)
            for s, x0, x1 in spans:
                if track in s.elements:
                    p.fillRect(QRectF(x0 + 0.5, ly + 2, max(1.0, x1 - x0 - 1), lh - 4),
                               lane_fill)
        # section borders
        p.setPen(QPen(border))
        bottom = y + lh * len(self.plan.tracks)
        for _s, x0, _x1 in spans:
            p.drawLine(QPointF(x0, top), QPointF(x0, bottom))
        # section names, rotated, read from the top down
        p.setPen(QColor(theme.TEXT))
        for s, x0, x1 in spans:
            p.save()
            p.translate((x0 + x1) / 2 + fm.ascent() * 0.35, bottom + em * 0.3)
            p.rotate(90)
            avail = int(self._names_h() - em * 0.3)
            p.drawText(0, 0, fm.elidedText(s.name, Qt.TextElideMode.ElideRight, avail))
            p.restore()
        p.end()
