"""The blaster, drawn with QPainter (no image assets).

Design space 1000 x ~520, gun pointing right. Static layers (background, gunmetal body) are
rendered once per size into pixmaps; the glowing parts, trigger, muzzle flash and beam are
cheap dynamic draws. The animation (recoil + flash) runs a 30 fps timer only for a fraction
of a second after a shot and only when switched on; at rest no timer is active.
"""

from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
    QTransform,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import skin

VIEW = QRectF(40, 50, 940, 470)  # part of the design space that is fitted into the widget
PIVOT = QPointF(350, 320)  # recoil rotates about the grip
MUZZLE = QPointF(948, 230)
ANIM_INTERVAL_MS = 33
ANIM_SECONDS = 0.5
FLASH_SECONDS = 0.22
RECOIL_TAU = 0.09
RECOIL_PX = 20.0
RECOIL_DEG = 3.0
CELL_SEGMENTS = 8
TRACE_BUCKETS = 90


def _rr(x: float, y: float, w: float, h: float, r: float) -> QPainterPath:
    p = QPainterPath()
    p.addRoundedRect(QRectF(x, y, w, h), r, r)
    return p


def _poly(*pts: tuple[float, float]) -> QPainterPath:
    p = QPainterPath()
    p.addPolygon(QPolygonF([QPointF(x, y) for x, y in pts]))
    p.closeSubpath()
    return p


def _metal(rect: QRectF, lo: str = skin.STEEL_LO, mid: str = skin.STEEL,
           hi: str = skin.STEEL_HI) -> QLinearGradient:
    g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    g.setColorAt(0.0, QColor(hi))
    g.setColorAt(0.28, QColor(mid))
    g.setColorAt(1.0, QColor(lo))
    return g


# ---- geometry (design space) ---------------------------------------------------------------
def _body_path() -> QPainterPath:
    p = _rr(200, 150, 450, 160, 28)
    rear = QPainterPath()
    rear.moveTo(214, 152)
    rear.lineTo(130, 168)
    rear.quadTo(62, 230, 130, 292)
    rear.lineTo(214, 308)
    rear.closeSubpath()
    return p.united(rear)


def _grip_path() -> QPainterPath:
    p = QPainterPath()
    p.moveTo(262, 300)
    p.lineTo(432, 300)
    p.lineTo(402, 492)
    p.quadTo(399, 512, 380, 512)
    p.lineTo(300, 512)
    p.quadTo(280, 512, 277, 494)
    p.closeSubpath()
    return p


def _guard_path() -> QPainterPath:
    p = QPainterPath()
    p.moveTo(452, 308)
    p.cubicTo(452, 410, 566, 410, 566, 308)
    return p


def _trigger_path() -> QPainterPath:
    return _poly((492, 306), (520, 306), (522, 332), (508, 372), (484, 366), (494, 334))


TRIGGER_PIVOT = QPointF(506, 308)
TRIGGER_PRESS_DEG = 14.0


def _hit_path() -> QPainterPath:
    """Generous click target: the lever and the whole inside of the trigger guard."""
    hit = QPainterPath()
    hit.addRect(QRectF(448, 300, 122, 100))
    st = QPainterPathStroker()
    st.setWidth(34)
    return hit.united(st.createStroke(_trigger_path()))


# ---- static layers ---------------------------------------------------------------------------
def paint_background(p: QPainter, w: float, h: float) -> None:
    r = QRectF(0, 0, w, h)
    g = QLinearGradient(r.topLeft(), r.bottomLeft())
    g.setColorAt(0, QColor("#0a1024"))
    g.setColorAt(0.62, QColor("#05070d"))
    g.setColorAt(1, QColor("#090d1b"))
    p.fillRect(r, g)
    rng = random.Random(417)
    for _ in range(70):  # stars
        x, y = rng.random() * w, rng.random() * h * 0.7
        a = 0.15 + rng.random() * 0.5
        s = 0.6 + rng.random() * 1.4
        p.fillRect(QRectF(x, y, s, s), skin.qc("#9fb4ff", a))
    # floor grid with perspective
    hor = h * 0.72
    pen = QPen(skin.qc(skin.LINE, 0.55), max(1.0, w / 900))
    p.setPen(pen)
    p.drawLine(QPointF(0, hor), QPointF(w, hor))
    for i in range(-10, 11):
        p.drawLine(QPointF(w / 2 + i * w * 0.02, hor), QPointF(w / 2 + i * w * 0.14, h))
    for k in range(1, 6):
        y = hor + (h - hor) * (k / 5) ** 2
        p.drawLine(QPointF(0, y), QPointF(w, y))
    v = QRadialGradient(QPointF(w / 2, h / 2), max(w, h) * 0.7)
    v.setColorAt(0.5, skin.qc("#000000", 0))
    v.setColorAt(1, skin.qc("#000000", 0.6))
    p.fillRect(r, v)


def paint_gun_body(p: QPainter) -> None:
    """The gunmetal parts at rest, in design space (no glow, no trigger)."""
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    edge = QPen(QColor(skin.STEEL_DK), 3.0)
    edge.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    # muzzle prongs (behind the barrel housing)
    for path in (_poly((846, 170), (952, 188), (952, 206), (846, 216)),
                 _poly((846, 290), (952, 272), (952, 254), (846, 244))):
        p.setPen(edge)
        p.setBrush(QBrush(_metal(path.boundingRect())))
        p.drawPath(path)
    # grip
    grip = _grip_path()
    p.setPen(edge)
    p.setBrush(QBrush(_metal(grip.boundingRect(), skin.STEEL_DK, skin.STEEL_LO, skin.STEEL)))
    p.drawPath(grip)
    p.setPen(QPen(skin.qc("#000000", 0.45), 3))
    for i in range(7):  # grip ridges
        y = 340 + i * 24
        p.drawLine(QPointF(292 + i * -1.5, y), QPointF(414 + i * -4.5, y - 4))
    # top fin and energy cell housing
    fin = _poly((250, 152), (292, 112), (540, 112), (580, 152))
    p.setPen(edge)
    p.setBrush(QBrush(_metal(fin.boundingRect(), skin.STEEL_DK, skin.STEEL_LO, skin.STEEL)))
    p.drawPath(fin)
    # barrel housing
    barrel = _rr(626, 180, 240, 100, 16)
    p.setBrush(QBrush(_metal(barrel.boundingRect())))
    p.drawPath(barrel)
    # body
    body = _body_path()
    p.setBrush(QBrush(_metal(body.boundingRect())))
    p.drawPath(body)
    # highlight along the top edge, seams and screws
    p.setPen(QPen(skin.qc("#ffffff", 0.28), 2.2))
    p.drawLine(QPointF(224, 156), QPointF(626, 156))
    p.drawLine(QPointF(640, 186), QPointF(850, 186))
    p.setPen(QPen(skin.qc("#000000", 0.5), 2.0))
    p.drawLine(QPointF(214, 152), QPointF(214, 308))
    p.drawLine(QPointF(626, 160), QPointF(626, 300))
    p.drawLine(QPointF(440, 290), QPointF(610, 290))
    for x, y in ((236, 172), (236, 290), (606, 172), (606, 290), (880, 230)):
        rv = QRadialGradient(QPointF(x - 1.5, y - 1.5), 7)
        rv.setColorAt(0, QColor(skin.STEEL_HI))
        rv.setColorAt(1, QColor(skin.STEEL_DK))
        p.setPen(QPen(QColor(skin.STEEL_DK), 1.2))
        p.setBrush(QBrush(rv))
        p.drawEllipse(QPointF(x, y), 6.5, 6.5)
    # rear vents
    p.setPen(QPen(QColor(skin.STEEL_DK), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for i in range(5):
        y = 188 + i * 20
        p.drawLine(QPointF(112 + abs(i - 2) * 6, y), QPointF(158, y))
    # trigger guard
    guard = QPainterPathStroker()
    guard.setWidth(14)
    gpath = guard.createStroke(_guard_path())
    p.setPen(edge)
    p.setBrush(QBrush(_metal(gpath.boundingRect(), skin.STEEL_DK, skin.STEEL_LO, skin.STEEL)))
    p.drawPath(gpath)


# ---- widget ------------------------------------------------------------------------------------
class BlasterWidget(QWidget):
    """The gun. ``triggered`` is emitted when the trigger is pressed (mouse, Space or Enter)."""

    triggered = Signal()
    released = Signal()  # the trigger was let go (hold-to-autofire stops)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(380, 200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setToolTip("Abzug drücken: Klick auf den Abzug, Leertaste oder Eingabetaste")
        self.accent = QColor("#ff4a2a")
        self.ready = True  # False: no engine, the glow stays dark
        self.animation = True
        self.pressed = False
        self.busy = False
        self.hover = False
        self.t = ANIM_SECONDS  # seconds since the last shot; >= ANIM_SECONDS means at rest
        self.trace: list[tuple[float, float]] = []
        self._layers: dict[str, tuple[tuple, QPixmap]] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(ANIM_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)

    # ---- state ----------------------------------------------------------------------------
    def set_accent(self, color: str) -> None:
        self.accent = QColor(color)
        self.update()

    def set_ready(self, ready: bool) -> None:
        self.ready = ready
        self.update()

    def set_busy(self, busy: bool) -> None:
        """A shot is being rendered: the energy cell shows "charging" (two segments)."""
        self.busy = busy
        self.update()

    def set_trace(self, peaks: list[tuple[float, float]]) -> None:
        self.trace = list(peaks)
        self.update()

    def set_animation(self, on: bool) -> None:
        self.animation = on
        if not on:
            self._stop_animation()
            self.t = ANIM_SECONDS
            self.update()

    def is_animating(self) -> bool:
        return self._timer.isActive()

    def flash(self) -> None:
        """Muzzle flash + recoil for a shot that was rendered (nothing when animation is off)."""
        if not self.animation:
            return
        self.t = 0.0
        self._timer.start()
        self.update()

    def _tick(self) -> None:
        self.t += ANIM_INTERVAL_MS / 1000.0
        if self.t >= ANIM_SECONDS:
            self._stop_animation()
        self.update()

    def _stop_animation(self) -> None:
        self._timer.stop()
        self.t = ANIM_SECONDS

    def hideEvent(self, e) -> None:  # noqa: N802 - Qt name
        self._stop_animation()
        super().hideEvent(e)

    def closeEvent(self, e) -> None:  # noqa: N802
        self._stop_animation()
        super().closeEvent(e)

    # ---- animation curves --------------------------------------------------------------------
    def flash_level(self) -> float:
        return max(0.0, 1.0 - self.t / FLASH_SECONDS) ** 1.5 if self.t < FLASH_SECONDS else 0.0

    def recoil_level(self) -> float:
        return math.exp(-self.t / RECOIL_TAU) if self.t < ANIM_SECONDS else 0.0

    # ---- geometry ------------------------------------------------------------------------------
    def _fit(self) -> tuple[QTransform, float]:
        sc = min(self.width() / VIEW.width(), self.height() / VIEW.height())
        ox = (self.width() - VIEW.width() * sc) / 2 - VIEW.x() * sc
        oy = (self.height() - VIEW.height() * sc) / 2 - VIEW.y() * sc
        tr = QTransform()
        tr.translate(ox, oy)
        tr.scale(sc, sc)
        return tr, sc

    def _gun_transform(self) -> QTransform:
        fit, sc = self._fit()
        r = self.recoil_level() if self.animation else 0.0
        if r <= 0.001:
            return fit
        pv = fit.map(PIVOT)
        rec = QTransform()
        rec.translate(-RECOIL_PX * r * sc, 0)
        rec.translate(pv.x(), pv.y())
        rec.rotate(-RECOIL_DEG * r)
        rec.translate(-pv.x(), -pv.y())
        return fit * rec

    def over_trigger(self, pos: QPointF) -> bool:
        inv, ok = self._gun_transform().inverted()
        return ok and _hit_path().contains(inv.map(pos))

    def _layer(self, name: str, key: tuple, draw) -> QPixmap:
        cached = self._layers.get(name)
        if cached is not None and cached[0] == key:
            return cached[1]
        dpr = self.devicePixelRatioF()
        pm = QPixmap(max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr)))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        q = QPainter(pm)
        try:
            q.setRenderHint(QPainter.RenderHint.Antialiasing)
            draw(q)
        finally:
            q.end()
        self._layers[name] = (key, pm)
        return pm

    # ---- painting ----------------------------------------------------------------------------
    def paintEvent(self, _e) -> None:  # noqa: N802 - Qt name
        key = (self.width(), self.height(), self.devicePixelRatioF())
        bg = self._layer("bg", key, lambda q: paint_background(q, self.width(), self.height()))
        body = self._layer("body", key, self._draw_body_layer)
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawPixmap(0, 0, bg)
            tr = self._gun_transform()
            glow = self.flash_level() if self.animation else 0.0
            self._paint_backglow(p, glow)
            p.setTransform(tr)
            fit, _sc = self._fit()
            # The body layer is stored in widget coordinates at rest; undo the fit, apply the
            # (fit + recoil) transform.
            inv, _ok = fit.inverted()
            p.setTransform(inv * tr)
            p.drawPixmap(0, 0, body)
            p.setTransform(tr)
            self._paint_glowing_parts(p, glow)
            self._paint_trigger(p)
            self._paint_muzzle(p, glow)
            p.resetTransform()
            if self.hasFocus():
                p.setPen(QPen(skin.qc(skin.STEEL_HI, 0.7), 1.5, Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(QRectF(2, 2, self.width() - 4, self.height() - 4), 6, 6)
        finally:
            p.end()

    def _draw_body_layer(self, q: QPainter) -> None:
        fit, _ = self._fit()
        q.setTransform(fit)
        paint_gun_body(q)

    def _glow_strength(self) -> float:
        return 0.55 if self.ready else 0.08

    def _paint_backglow(self, p: QPainter, flash: float) -> None:
        fit, sc = self._fit()
        c = fit.map(QPointF(560, 240))
        rad = 420 * sc
        g = QRadialGradient(c, rad)
        a = (0.10 if self.ready else 0.02) + 0.22 * flash
        g.setColorAt(0, skin.qc(self.accent, a))
        g.setColorAt(1, skin.qc(self.accent, 0))
        p.fillRect(QRectF(0, 0, self.width(), self.height()), g)

    def _glow_pen_brush(self, strength: float) -> QColor:
        return skin.mix(skin.STEEL_DK, self.accent.name(), min(1.0, strength))

    def _paint_glowing_parts(self, p: QPainter, flash: float) -> None:
        a = self.accent
        base = self._glow_strength()
        level = min(1.0, base + 0.45 * flash)
        # inner barrel slot, under the coils
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(skin.qc(a, 0.25 + 0.6 * level))
        p.drawRoundedRect(QRectF(640, 226, 220, 8), 4, 4)
        # barrel coils with soft halo
        for x in (662, 704, 746, 788):
            rect = QRectF(x, 198, 16, 64)
            for k, al in ((3, 0.08), (2, 0.14), (1, 0.22)):
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(skin.qc(a, al * level * 1.6))
                p.drawRoundedRect(rect.adjusted(-3 * k, -2 * k, 3 * k, 2 * k), 6, 6)
            lit = level
            p.setPen(QPen(QColor(skin.STEEL_DK), 1.5))
            p.setBrush(self._glow_pen_brush(0.25 + 0.75 * lit))
            p.drawRoundedRect(rect, 4, 4)
        p.setPen(Qt.PenStyle.NoPen)
        # accent stripe on the body
        p.setBrush(self._glow_pen_brush(0.35 + 0.65 * level))
        p.drawRoundedRect(QRectF(452, 168, 150, 9), 4, 4)
        # energy cell on top: glass tube with segments that dip after a shot
        glass = QRectF(318, 66, 196, 44)
        p.setPen(QPen(QColor(skin.STEEL_DK), 3))
        p.setBrush(skin.qc("#0a1226", 0.95))
        p.drawRoundedRect(glass, 18, 18)
        if self.busy:
            lit_n = 2
        elif flash <= 0 and self.t >= ANIM_SECONDS:
            lit_n = CELL_SEGMENTS
        else:
            lit_n = max(2, int(CELL_SEGMENTS * min(1.0, 0.25 + 0.75 * (self.t / ANIM_SECONDS))))
        seg_w = (glass.width() - 24) / CELL_SEGMENTS
        for i in range(CELL_SEGMENTS):
            r = QRectF(glass.x() + 14 + i * seg_w, glass.y() + 9, seg_w - 4,
                       glass.height() - 18)
            on = i < lit_n and self.ready
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self._glow_pen_brush(0.95) if on else skin.qc(skin.STEEL_LO, 0.9))
            p.drawRoundedRect(r, 3, 3)
        p.setPen(QPen(skin.qc("#ffffff", 0.35), 2))
        y = glass.y() + 6
        p.drawLine(QPointF(glass.x() + 22, y), QPointF(glass.right() - 40, y))
        self._paint_scope(p)

    def _paint_scope(self, p: QPainter) -> None:
        a = self.accent
        scr = QRectF(238, 186, 196, 86)
        p.setPen(QPen(QColor(skin.STEEL_DK), 3))
        p.setBrush(QColor("#03060d"))
        p.drawRoundedRect(scr, 8, 8)
        p.setPen(QPen(skin.qc(a, 0.16), 1))
        for i in range(1, 4):
            y = scr.y() + scr.height() * i / 4
            p.drawLine(QPointF(scr.x() + 6, y), QPointF(scr.right() - 6, y))
        for i in range(1, 8):
            x = scr.x() + scr.width() * i / 8
            p.drawLine(QPointF(x, scr.y() + 6), QPointF(x, scr.bottom() - 6))
        mid = scr.center().y()
        amp = scr.height() / 2 - 8
        inner_w = scr.width() - 16
        pen = QPen(skin.qc(a, 0.95 if self.ready else 0.3), 2.2)
        p.setPen(pen)
        if not self.trace:
            p.drawLine(QPointF(scr.x() + 8, mid), QPointF(scr.right() - 8, mid))
            return
        n = len(self.trace)
        for i, (lo, hi) in enumerate(self.trace):
            x = scr.x() + 8 + inner_w * i / max(1, n - 1)
            p.drawLine(QPointF(x, mid - hi * amp), QPointF(x, mid - min(lo, hi - 0.02) * amp))

    def _paint_trigger(self, p: QPainter) -> None:
        tr = _trigger_path()
        p.save()
        if self.pressed:
            p.translate(TRIGGER_PIVOT)
            p.rotate(TRIGGER_PRESS_DEG)
            p.translate(-TRIGGER_PIVOT.x(), -TRIGGER_PIVOT.y())
        hot = self.pressed or self.hover
        top = skin.mix("#7a1c12", self.accent.name(), 0.85 if hot else 0.45)
        bot = skin.mix("#26090a", self.accent.name(), 0.35 if hot else 0.12)
        g = QLinearGradient(QPointF(0, 306), QPointF(0, 372))
        g.setColorAt(0, top)
        g.setColorAt(1, bot)
        p.setPen(QPen(QColor(skin.STEEL_DK), 2.5))
        p.setBrush(QBrush(g))
        p.drawPath(tr)
        p.setPen(QPen(skin.qc("#ffffff", 0.35), 1.8))
        p.drawLine(QPointF(497, 318), QPointF(509, 354))
        p.restore()

    def _paint_muzzle(self, p: QPainter, flash: float) -> None:
        a, m = self.accent, MUZZLE
        base = self._glow_strength()
        orb = QRadialGradient(m, 30)
        orb.setColorAt(0, skin.qc("#ffffff", 0.9 if self.ready else 0.2))
        orb.setColorAt(0.35, skin.qc(a, 0.75 * base + 0.25))
        orb.setColorAt(1, skin.qc(a, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(orb))
        p.drawEllipse(m, 30, 30)
        if flash <= 0:
            return
        fit, _ = self._fit()
        inv, _ok = fit.inverted()
        x_right = inv.map(QPointF(self.width(), 0)).x() + 40
        # beam streak from the muzzle to the right edge
        beam = QLinearGradient(m, QPointF(x_right, m.y()))
        beam.setColorAt(0, skin.qc("#ffffff", 0.95 * flash))
        beam.setColorAt(0.25, skin.qc(a, 0.8 * flash))
        beam.setColorAt(1, skin.qc(a, 0.0))
        h = 10 + 16 * flash
        p.setBrush(QBrush(beam))
        p.drawRoundedRect(QRectF(m.x(), m.y() - h / 2, x_right - m.x(), h), h / 2, h / 2)
        core = QLinearGradient(m, QPointF(x_right, m.y()))
        core.setColorAt(0, skin.qc("#ffffff", flash))
        core.setColorAt(1, skin.qc("#ffffff", 0))
        p.setBrush(QBrush(core))
        p.drawRect(QRectF(m.x(), m.y() - 2.5, x_right - m.x(), 5))
        # flash bloom with spikes
        rad = 40 + 90 * flash
        bloom = QRadialGradient(m, rad)
        bloom.setColorAt(0, skin.qc("#ffffff", flash))
        bloom.setColorAt(0.3, skin.qc(a, 0.7 * flash))
        bloom.setColorAt(1, skin.qc(a, 0))
        p.setBrush(QBrush(bloom))
        p.drawEllipse(m, rad, rad)
        p.setPen(QPen(skin.qc("#ffffff", 0.8 * flash), 2.5, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        for ang in (-70, -35, 35, 70, 180 - 35, 180 + 35):
            dx, dy = math.cos(math.radians(ang)), math.sin(math.radians(ang))
            p.drawLine(QPointF(m.x() + dx * 18, m.y() + dy * 18),
                       QPointF(m.x() + dx * (30 + 70 * flash), m.y() + dy * (30 + 70 * flash)))

    # ---- input -------------------------------------------------------------------------------
    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        over = self.over_trigger(e.position())
        if over != self.hover:
            self.hover = over
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor if over
                                   else Qt.CursorShape.ArrowCursor))
            self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        if self.hover:
            self.hover = False
            self.unsetCursor()
            self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self.over_trigger(e.position()):
            self.setFocus()
            self._pull()
        else:
            super().mousePressEvent(e)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if self.pressed:
            self.pressed = False
            self.update()
            self.released.emit()
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not e.isAutoRepeat():
                self._pull()
            return
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e) -> None:  # noqa: N802
        if e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not e.isAutoRepeat() and self.pressed:
                self.pressed = False
                self.update()
                self.released.emit()
            return
        super().keyReleaseEvent(e)

    def _pull(self) -> None:
        self.pressed = True
        self.update()
        self.triggered.emit()
