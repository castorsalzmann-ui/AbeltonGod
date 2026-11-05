"""ChromeThornFrame: paints the chrome-thorn border and the cyber body with QPainter vectors.

The static part (thorns, rail, body) is drawn into a cached pixmap that is rebuilt only when the
size or the device pixel ratio changes; the optional neon pulse repaints just the thin inner
line, so an idle window costs almost nothing.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRegion,
)
from PySide6.QtWidgets import QWidget

from . import geometry as geo
from . import palette as pal

PULSE_INTERVAL_MS = 50  # 20 fps is plenty for a slow glow
PULSE_PERIOD_S = 4.0
_LIGHT = (-0.7071, -0.7071)  # light comes from the top left


def _mix(c1: str, c2: str, t: float) -> QColor:
    a, b = QColor(c1), QColor(c2)
    return QColor.fromRgbF(
        a.redF() + (b.redF() - a.redF()) * t,
        a.greenF() + (b.greenF() - a.greenF()) * t,
        a.blueF() + (b.blueF() - a.blueF()) * t,
    )


def _gradient(p0: QPointF, p1: QPointF, positions, stops) -> QLinearGradient:
    g = QLinearGradient(p0, p1)
    for pos, col in zip(positions, stops, strict=True):
        g.setColorAt(pos, QColor(col))
    return g


def _facet_gradient(p0: QPointF, p1: QPointF, lit: float) -> QLinearGradient:
    g = QLinearGradient(p0, p1)
    stops = zip(pal.CHROME_POSITIONS, pal.CHROME_LIT, pal.CHROME_SHADE, strict=True)
    for pos, light, shade in stops:
        g.setColorAt(pos, _mix(shade, light, lit))
    return g


def paint_thorns(p: QPainter, thorns: list[geo.Thorn]) -> None:
    """Chrome facets, ridge, specular edge on the lit side, cool/warm rim on the shade side."""
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    for t in thorns:
        fa, fb = t.facets()
        na, nb = t.outer_side_normals()
        lit_a = max(0.0, min(1.0, 0.5 + 0.5 * (na[0] * _LIGHT[0] + na[1] * _LIGHT[1]) * 1.4))
        lit_b = max(0.0, min(1.0, 0.5 + 0.5 * (nb[0] * _LIGHT[0] + nb[1] * _LIGHT[1]) * 1.4))
        # Make the two facets of one thorn clearly different (a polished faceted look).
        if abs(lit_a - lit_b) < 0.35:
            if lit_a >= lit_b:
                lit_a, lit_b = min(1.0, lit_a + 0.2), max(0.0, lit_b - 0.2)
            else:
                lit_a, lit_b = max(0.0, lit_a - 0.2), min(1.0, lit_b + 0.2)
        m = t.base_mid
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(_facet_gradient(m, t.tip, lit_a)))
        p.drawPath(fa)
        p.setBrush(QBrush(_facet_gradient(m, t.tip, lit_b)))
        p.drawPath(fb)
        # Ridge line.
        p.setPen(QPen(QColor(8, 10, 20, 170), 0.8))
        p.drawLine(m, t.tip)
        # Edge highlights along the curved outer sides.
        for a_pt, ctrl, lit in ((t.a, t.ctrl_a, lit_a), (t.b, t.ctrl_b, lit_b)):
            edge = QPainterPath(a_pt)
            edge.quadTo(ctrl, t.tip)
            if lit > 0.5:
                col = QColor(pal.SPECULAR)
                col.setAlphaF(0.55 + 0.45 * lit)
                p.setPen(QPen(col, 1.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            else:
                col = QColor(pal.RIM_COOL)
                col.setAlphaF(0.8)
                p.setPen(QPen(col, 1.0,Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(edge)


def paint_rail(p: QPainter, body: QRectF, rail: float, radius: float) -> None:
    ring = geo.rail_path(body, rail, radius)
    p.setPen(Qt.PenStyle.NoPen)
    g = _gradient(body.topLeft(), body.bottomRight(), pal.RAIL_POSITIONS, pal.RAIL_STOPS)
    p.setBrush(QBrush(g))
    p.drawPath(ring)
    # Bright specular edge on the outside, dark reflection line on the inside.
    outer = QPainterPath()
    outer.addRoundedRect(body.adjusted(0.6, 0.6, -0.6, -0.6), radius, radius)
    p.setBrush(Qt.BrushStyle.NoBrush)
    spec = QLinearGradient(body.topLeft(), body.bottomRight())
    spec.setColorAt(0.0, QColor(255, 255, 255, 255))
    spec.setColorAt(0.5, QColor(170, 200, 255, 120))
    spec.setColorAt(1.0, QColor(255, 255, 255, 230))
    p.setPen(QPen(QBrush(spec), 1.2))
    p.drawPath(outer)
    inner_rect = body.adjusted(rail, rail, -rail, -rail)
    inner = QPainterPath()
    inner.addRoundedRect(inner_rect, radius * 0.5, radius * 0.5)
    p.setPen(QPen(QColor(2, 3, 10, 235), 1.4))  # inner shadow
    p.drawPath(inner)


def paint_body(p: QPainter, rect: QRectF, radius: float) -> None:
    g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    g.setColorAt(0.0, QColor(pal.BODY_TOP))
    g.setColorAt(1.0, QColor(pal.BODY_BOTTOM))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(g))
    p.drawRoundedRect(rect, radius, radius)
    # Faint magenta glow in the lower right, cyan in the upper left (accent haze).
    for centre, col in ((rect.topLeft(), pal.CYAN), (rect.bottomRight(), pal.MAGENTA)):
        from PySide6.QtGui import QRadialGradient

        rg = QRadialGradient(centre, min(rect.width(), rect.height()) * 0.9)
        c0 = QColor(col)
        c0.setAlpha(34)
        c1 = QColor(col)
        c1.setAlpha(0)
        rg.setColorAt(0.0, c0)
        rg.setColorAt(1.0, c1)
        p.setBrush(QBrush(rg))
        p.drawRoundedRect(rect, radius, radius)


class ChromeThornFrame(QWidget):
    """The window skin. Child widgets go inside :meth:`content_rect`."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._cache: QPixmap | None = None
        self._cache_key: tuple | None = None
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(PULSE_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._animated = False
        self._clock = 0.0

    # -- geometry ---------------------------------------------------------------------------
    def reach(self) -> float:
        return geo.reach_for(self.width(), self.height())

    def rail(self) -> float:
        return geo.rail_for(self.reach())

    def body_rect(self) -> QRectF:
        return geo.body_rect(self.width(), self.height(), self.reach())

    def content_rect(self) -> QRect:
        """Where child widgets may sit: inside rail and neon line."""
        inset = self.rail() + 5.0
        return self.body_rect().adjusted(inset, inset, -inset, -inset).toAlignedRect()

    def content_margin(self) -> int:
        return int(round(self.reach() + self.rail() + 5.0))

    def thorns(self) -> list[geo.Thorn]:
        return geo.build_thorns(self.width(), self.height())

    # -- animation --------------------------------------------------------------------------
    def set_animated(self, on: bool) -> None:
        self._animated = bool(on)
        if on:
            self._timer.start()
        else:
            self._timer.stop()
            self._phase = 0.0
            self.update(self._neon_region())

    def animated(self) -> bool:
        return self._animated

    def _tick(self) -> None:
        self._clock += PULSE_INTERVAL_MS / 1000.0
        self._phase = 0.5 + 0.5 * math.sin(2 * math.pi * self._clock / PULSE_PERIOD_S)
        self.update(self._neon_region())

    def _neon_rect(self) -> QRectF:
        r = self.body_rect()
        inset = self.rail() + 2.0
        return r.adjusted(inset, inset, -inset, -inset)

    def _neon_region(self) -> QRegion:
        outer = self._neon_rect().adjusted(-4, -4, 4, 4).toAlignedRect()
        inner = self._neon_rect().adjusted(4, 4, -4, -4).toAlignedRect()
        return QRegion(outer).subtracted(QRegion(inner))

    # -- painting ---------------------------------------------------------------------------
    def _static_layer(self) -> QPixmap:
        dpr = self.devicePixelRatioF()
        key = (self.width(), self.height(), dpr)
        if self._cache is None or self._cache_key != key:
            pm = QPixmap(int(math.ceil(self.width() * dpr)), int(math.ceil(self.height() * dpr)))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.GlobalColor.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            reach, rail = self.reach(), self.rail()
            body = self.body_rect()
            radius = max(5.0, reach * 0.45)
            paint_thorns(p, self.thorns())
            paint_rail(p, body, rail, radius)
            inner = body.adjusted(rail, rail, -rail, -rail)
            paint_body(p, inner, radius * 0.5)
            p.end()
            self._cache, self._cache_key = pm, key
        return self._cache

    def _paint_neon(self, p: QPainter) -> None:
        r = self._neon_rect()
        radius = max(3.0, self.reach() * 0.22)
        g = QConicalGradient(r.center(), 45)
        g.setColorAt(0.0, QColor(pal.CYAN))
        g.setColorAt(0.5, QColor(pal.MAGENTA))
        g.setColorAt(1.0, QColor(pal.CYAN))
        strength = 0.55 + 0.45 * self._phase if self._animated else 0.8
        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)
        p.setBrush(Qt.BrushStyle.NoBrush)
        glow = QPen(QBrush(g), 3.6)
        p.setOpacity(0.16 * strength)
        p.setPen(glow)
        p.drawPath(path)
        p.setOpacity(strength)
        p.setPen(QPen(QBrush(g), 1.2))
        p.drawPath(path)
        p.setOpacity(1.0)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.drawPixmap(0, 0, self._static_layer())
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._paint_neon(p)
        p.end()
