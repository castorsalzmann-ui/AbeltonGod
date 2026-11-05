"""Custom-painted widgets of the acid window: panels, header, footer, step grid.

Static layers (plate, hex membrane, background) are rendered once per size into a pixmap;
the animation (off by default) only repaints the cheap dynamic parts.
"""

from __future__ import annotations

import bisect
import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QLinearGradient, QPainter, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QSizePolicy, QWidget

from gui_core.acid_generate import SCALES, note_name
from gui_core.acid_model import AcidModel

from . import skin

STEPS_PER_ROW = 16
ANIM_INTERVAL_MS = 125  # 8 fps: slow pulse and creeping drips; timers run only when switched on


def _unit(w: QWidget) -> float:
    return float(w.fontMetrics().height())


def _cached(widget: QWidget, key, draw) -> QPixmap:
    """Pixmap for ``key`` (size, ratio ...), re-rendered by ``draw(painter)`` when it changes."""
    cache = getattr(widget, "_layer_cache", None)
    if cache is not None and cache[0] == key:
        return cache[1]
    dpr = widget.devicePixelRatioF()
    pm = QPixmap(int(widget.width() * dpr), int(widget.height() * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    draw(p)
    p.end()
    widget._layer_cache = (key, pm)
    return pm


class Animated(QWidget):
    """Mixin-like base: ``set_animation(True)`` starts a slow timer that advances ``t``."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.t = 0.0
        self.animating = False
        self._timer = QTimer(self)
        self._timer.setInterval(ANIM_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)

    def set_animation(self, on: bool) -> None:
        self.animating = on
        if on:
            self._timer.start()
        else:
            self._timer.stop()
            self.t = 0.0
            self.update()

    def _tick(self) -> None:
        self.t += ANIM_INTERVAL_MS / 1000.0
        self.update()


class AcidRoot(QWidget):
    """Window background: near-black gradient, glowing veins, vignette."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("acidroot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def paintEvent(self, _e) -> None:  # noqa: N802 - Qt name
        key = (self.width(), self.height(), self.devicePixelRatioF())

        def draw(p: QPainter) -> None:
            r = QRectF(0, 0, self.width(), self.height())
            g = QLinearGradient(r.topLeft(), r.bottomLeft())
            g.setColorAt(0, skin.qc("#0a1a0c"))
            g.setColorAt(0.6, skin.qc(skin.BLACK))
            g.setColorAt(1, skin.qc("#061208"))
            p.fillRect(r, g)
            skin.paint_veins(p, r, 7, 16, max(1.0, _unit(self) * 0.12))
            v = QRadialGradient(r.center(), max(r.width(), r.height()) * 0.75)
            v.setColorAt(0.55, skin.qc("#000000", 0))
            v.setColorAt(1, skin.qc("#000000", 0.55))
            p.fillRect(r, v)

        QPainter(self).drawPixmap(0, 0, _cached(self, key, draw))


class EtchedPanel(QWidget):
    """Corroded plate with rib/vertebra texture and an etched caption. Children go inside
    the margins that leave room for the caption, the eaten edge and the vertebra column."""

    def __init__(self, title: str, seed: int, ribs: bool = True,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title, self.seed, self.ribs = title, seed, ribs
        u = _unit(self)
        self.depth = u * 0.6
        left = u * (3.8 if ribs else 2.0)
        self.setContentsMargins(0, 0, 0, 0)
        self._margins = (int(left), int(u * 3.8), int(u * 1.8), int(u * 1.7))
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def content_margins(self) -> tuple[int, int, int, int]:
        return self._margins

    def paintEvent(self, _e) -> None:  # noqa: N802 - Qt name
        key = (self.width(), self.height(), self.devicePixelRatioF(), self.title)

        def draw(p: QPainter) -> None:
            u = _unit(self)
            rect = QRectF(self.depth * 1.3, self.depth * 1.3,
                          self.width() - self.depth * 2.6, self.height() - self.depth * 2.6)
            skin.paint_plate(p, rect, self.seed, self.depth, ribs=self.ribs)
            f = QFont(self.font())
            f.setBold(True)
            f.setPixelSize(max(9, int(u * 0.95)))
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, u * 0.12)
            tr = QRectF(rect.left() + u * (3.8 if self.ribs else 2.0), rect.top() + u * 1.2,
                        rect.width() - u * 3, u * 1.4)
            skin.paint_glow_text(p, tr, self.title.upper(), f, skin.LIME)

        QPainter(self).drawPixmap(0, 0, _cached(self, key, draw))


class HeaderBand(Animated):
    """Title, tagline, corroded top lip and acid drips running down from it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(400, int(_unit(self) * 5.6))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def title_rect(self) -> QRectF:
        u = _unit(self)
        return QRectF(u * 0.6, u * 1.1, u * 17, u * 4.2)

    def lip_height(self) -> float:
        return _unit(self) * 0.6

    def drip_max(self) -> float:
        return self.height() - self.lip_height() - 2

    def paintEvent(self, _e) -> None:  # noqa: N802 - Qt name
        u = _unit(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w = self.width()
        tr = self.title_rect()

        def lip(q: QPainter) -> None:
            q.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            noise = skin.Noise1D(5, w, base_step=u * 1.6)
            from PySide6.QtGui import QPainterPath, QPolygonF
            pts = [QPointF(0, 0)]
            x = 0.0
            while x <= w:
                pts.append(QPointF(x, self.lip_height() * (0.65 + 0.35 * noise(x))))
                x += u * 0.35
            pts += [QPointF(w, 0)]
            path = QPainterPath()
            path.addPolygon(QPolygonF(pts))
            path.closeSubpath()
            g = QLinearGradient(0, 0, 0, self.lip_height())
            g.setColorAt(0, skin.qc("#0a2a10"))
            g.setColorAt(1, skin.qc(skin.DEEP))
            q.fillPath(path, g)
            q.setPen(QPen(skin.qc(skin.NEON, 0.35), u * 0.16))
            q.drawPolyline(QPolygonF(pts[1:-1]))
            q.setPen(QPen(skin.qc(skin.LIME, 0.9), 1))
            q.drawPolyline(QPolygonF(pts[1:-1]))

        p.drawPixmap(0, 0, _cached(self, ("lip", w, self.devicePixelRatioF()), lip))
        drips = skin.drip_layout(w, 21, u, skip=(tr.left(), tr.right()))
        skin.paint_drips(p, self.lip_height() * 0.7, drips, self.drip_max(), self.t,
                         creep=1.0 if self.animating else 0.0)
        f = QFont(self.font())
        f.setBold(True)
        f.setPixelSize(int(u * 3.0))
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, u * 0.25)
        skin.paint_glow_text(p, QRectF(tr.left(), tr.top() - u * 0.3, tr.width(), u * 3.4),
                             "ACID", f, skin.LIME)
        f2 = QFont(self.font())
        f2.setPixelSize(int(u * 0.95))
        f2.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, u * 0.1)
        p.setFont(f2)
        p.setPen(skin.qc(skin.MUTED))
        p.drawText(QRectF(tr.left() + u * 0.2, tr.top() + u * 2.95, u * 30, u * 1.3),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   "GIFTLINIE  ·  MUSTER-GENERATOR (VORSCHLAG)")
        p.end()


class FooterBand(Animated):
    """Status line host; bubbling pools sit at the right edge. Put the status label in a
    layout on this widget (margins leave the pool area free)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(400, int(_unit(self) * 2.9))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def pool_rects(self) -> list[QRectF]:
        u = _unit(self)
        w, h = self.width(), self.height()
        return [QRectF(w - u * 13.5, h - u * 2.0, u * 6.6, u * 1.7),
                QRectF(w - u * 6.4, h - u * 2.6, u * 5.6, u * 2.2),
                QRectF(w - u * 17.5, h - u * 1.4, u * 3.2, u * 1.1)]

    def paintEvent(self, _e) -> None:  # noqa: N802 - Qt name
        p = QPainter(self)
        for i, r in enumerate(self.pool_rects()):
            skin.paint_pool(p, r, 40 + i, self.t, self.animating)
        p.end()


class StepGridWidget(Animated):
    """The 303-style grid: per step a pitch vine, a glossy pad and accent/slide lamps."""

    changed = Signal()

    REGIONS = ("pitch", "pad", "accent", "slide")

    def __init__(self, model: AcidModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model = model
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(int(_unit(self) * 17))
        self.setMouseTracking(False)
        self._drag_step: int | None = None
        self._sprites: dict[tuple, QPixmap] = {}

    # ---- geometry ----------------------------------------------------------------------
    def update_min_height(self) -> None:
        """Room for the pitch vines: 17 font heights per row of 16 steps."""
        self.setMinimumHeight(int(_unit(self) * 17 * self.rows()))
        self.updateGeometry()

    def rows(self) -> int:
        return (self.model.length + STEPS_PER_ROW - 1) // STEPS_PER_ROW

    def _frame(self):
        u = _unit(self)
        gutter = u * 4.6
        right = u * 0.8
        top = u * 0.8
        bottom = u * 0.6
        cw = (self.width() - gutter - right) / STEPS_PER_ROW
        bh = (self.height() - top - bottom) / max(1, self.rows())
        return u, gutter, top, cw, bh

    def block_layout(self, row: int) -> dict[str, float]:
        """y positions of one row block."""
        u, _g, top, _cw, bh = self._frame()
        y0 = top + row * bh
        label_h = u * 1.25
        num_h = u * 1.1
        lamp_h = u * 1.25
        pad_h = min(self._frame()[3] * 0.58, u * 3.2)
        fixed = label_h + pad_h + 2 * lamp_h + num_h + u * 0.9
        track_h = max(u * 3.0, bh - fixed - u * 0.5)
        y = y0
        out = {"y0": y0, "label": y}
        y += label_h
        out["track_top"], out["track_h"] = y, track_h
        y += track_h + u * 0.35
        out["pad"], out["pad_h"] = y, pad_h
        y += pad_h + u * 0.55
        out["accent"] = y
        y += lamp_h
        out["slide"] = y
        y += lamp_h
        out["num"] = y
        out["lamp_h"], out["num_h"], out["label_h"] = lamp_h, num_h, label_h
        return out

    def visible_steps(self) -> int:
        return self.model.length

    def column_x(self, col: int) -> tuple[float, float]:
        _u, gutter, _t, cw, _bh = self._frame()
        return gutter + col * cw, cw

    def region_rect(self, step: int, region: str) -> QRectF:
        row, col = divmod(step, STEPS_PER_ROW)
        lay = self.block_layout(row)
        x, cw = self.column_x(col)
        if region == "pitch":
            return QRectF(x + cw * 0.1, lay["track_top"], cw * 0.8, lay["track_h"])
        if region == "pad":
            ps = lay["pad_h"]
            return QRectF(x + (cw - ps) / 2, lay["pad"], ps, ps)
        if region in ("accent", "slide"):
            d = min(lay["lamp_h"] * 0.85, cw * 0.7)
            return QRectF(x + (cw - d) / 2, lay[region] + (lay["lamp_h"] - d) / 2, d, d)
        raise ValueError(region)

    def hit_test(self, pos: QPointF) -> tuple[int, str] | None:
        for step in range(self.visible_steps()):
            for region in self.REGIONS:
                r = self.region_rect(step, region)
                if region == "pitch":
                    r = r.adjusted(0, -_unit(self) * 0.3, 0, _unit(self) * 0.3)
                if r.contains(pos):
                    return step, region
        return None

    def _palette(self) -> list[int]:
        return self.model.palette(3)

    def note_to_y(self, note: int, rect: QRectF) -> float:
        pal = self._palette()
        i = bisect.bisect_left(pal, note)
        if i < len(pal) and pal[i] == note:
            pos = float(i)
        elif i == 0:
            pos = 0.0
        elif i >= len(pal):
            pos = float(len(pal) - 1)
        else:
            lo, hi = pal[i - 1], pal[i]
            pos = (i - 1) + (note - lo) / (hi - lo)
        frac = pos / max(1, len(pal) - 1)
        pad = rect.width() * 0.32
        return rect.bottom() - pad - frac * (rect.height() - 2 * pad)

    def y_to_note(self, y: float, rect: QRectF) -> int:
        pal = self._palette()
        pad = rect.width() * 0.32
        frac = (rect.bottom() - pad - y) / max(1.0, rect.height() - 2 * pad)
        idx = round(min(1.0, max(0.0, frac)) * (len(pal) - 1))
        return pal[idx]

    # ---- interaction -------------------------------------------------------------------
    def mousePressEvent(self, e) -> None:  # noqa: N802 - Qt name
        hit = self.hit_test(e.position())
        if hit is None or e.button() != Qt.MouseButton.LeftButton:
            return
        step, region = hit
        if region == "pad":
            self.model.toggle_on(step)
        elif region == "accent":
            self.model.toggle_accent(step)
        elif region == "slide":
            self.model.toggle_slide(step)
        else:
            self._drag_step = step
            self._set_pitch(step, e.position().y())
            return
        self.update()
        self.changed.emit()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802 - Qt name
        if self._drag_step is not None:
            self._set_pitch(self._drag_step, e.position().y())

    def mouseReleaseEvent(self, _e) -> None:  # noqa: N802 - Qt name
        self._drag_step = None

    def _set_pitch(self, step: int, y: float) -> None:
        note = self.y_to_note(y, self.region_rect(step, "pitch"))
        if note != self.model.steps[step].note:
            self.model.set_note(step, note)
            self.update()
            self.changed.emit()

    # ---- painting ----------------------------------------------------------------------
    def _state_key(self):
        m = self.model
        return (self.width(), self.height(), self.devicePixelRatioF(), m.length, m.root, m.scale,
                m.root_octave, self.animating,
                tuple((s.on, s.note, s.accent, s.slide) for s in m.steps[: m.length]))

    def _pad_sprite(self, size: float, accent: bool, level: int) -> QPixmap:
        """Lit pad with halo at pulse ``level`` (0..4), cached: the animation only blits these."""
        cache = self._sprites
        dpr = self.devicePixelRatioF()
        key = (round(size, 1), accent, level, dpr)
        if key not in cache:
            margin = size * 0.6
            side = size + 2 * margin
            pm = QPixmap(int(side * dpr) + 1, int(side * dpr) + 1)
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.GlobalColor.transparent)
            q = QPainter(pm)
            skin.paint_pad(q, QRectF(margin, margin, size, size), True, accent, 0.6 + 0.2 * level)
            q.end()
            cache[key] = pm
        return cache[key]

    def paintEvent(self, _e) -> None:  # noqa: N802 - Qt name
        # Static layer (hex, tracks, labels, lamps, tendrils, pads) is rendered once per model
        # state; while animating, lit pads are left out of it and blitted as cached sprites.
        p = QPainter(self)
        p.drawPixmap(0, 0, _cached(self, self._state_key(),
                                   lambda q: self._draw_static(q, skip_lit_pads=self.animating)))
        if self.animating:
            for step in range(self.visible_steps()):
                s = self.model.steps[step]
                if not s.on:
                    continue
                r = self.region_rect(step, "pad")
                level = int(round(2 + 2 * math.sin(self.t * 1.5 + step * 0.45)))
                sprite = self._pad_sprite(r.width(), s.accent, level)
                margin = r.width() * 0.6
                p.drawPixmap(QPointF(r.left() - margin, r.top() - margin), sprite)
        p.end()

    def _draw_static(self, p: QPainter, skip_lit_pads: bool) -> None:
        u = _unit(self)
        skin.paint_hex(p, QRectF(0, 0, self.width(), self.height()), u * 2.6, 99)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        m = self.model
        _u, gutter, _top, cw, _bh = self._frame()
        small = QFont(self.font())
        small.setPixelSize(max(9, int(u * 0.8)))
        small.setBold(False)
        bold = QFont(small)
        bold.setBold(True)
        pal = self._palette()
        ticks_idx = [i for i in range(0, len(pal), len(SCALES[m.scale]))]
        # row labels
        for row in range(self.rows()):
            lay = self.block_layout(row)
            p.setFont(bold)
            p.setPen(skin.qc(skin.MUTED))
            for name, ykey, hkey in (("TON", "track_top", "track_h"), ("STEP", "pad", "pad_h"),
                                     ("AKZENT", "accent", "lamp_h"),
                                     ("SLIDE", "slide", "lamp_h")):
                r = QRectF(u * 0.4, lay[ykey], gutter - u * 0.8, lay[hkey])
                if name == "TON":
                    r = QRectF(u * 0.4, lay[ykey], gutter - u * 0.8, u * 1.4)
                p.drawText(r, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                           name)
        for step in range(self.visible_steps()):
            s = m.steps[step]
            row, col = divmod(step, STEPS_PER_ROW)
            lay = self.block_layout(row)
            x, _cw = self.column_x(col)
            if step % 4 == 0 and col:  # beat divider
                p.setPen(QPen(skin.qc(skin.POISON, 0.22), 1, Qt.PenStyle.DashLine))
                p.drawLine(QPointF(x, lay["y0"]), QPointF(x, lay["num"] + lay["num_h"]))
            tr = self.region_rect(step, "pitch")
            ty = [self.note_to_y(pal[i], tr) for i in ticks_idx]
            ky = self.note_to_y(s.note, tr)
            skin.paint_vine_track(p, tr, ky, ty, s.on, phase=step * 0.7)
            # note name above the track
            p.setFont(bold if s.on else small)
            p.setPen(skin.qc(skin.TEXT if s.on else skin.MUTED))
            p.drawText(QRectF(x, lay["label"], cw, lay["label_h"]),
                       int(Qt.AlignmentFlag.AlignCenter), note_name(s.note))
            if not (skip_lit_pads and s.on):
                skin.paint_pad(p, self.region_rect(step, "pad"), s.on, s.on and s.accent)
            skin.paint_lamp(p, self.region_rect(step, "accent"), s.accent, skin.LIME)
            skin.paint_lamp(p, self.region_rect(step, "slide"), s.slide, "#5cf0d0")
            p.setFont(bold if step % 4 == 0 else small)
            p.setPen(skin.qc(skin.TEXT if step % 4 == 0 else skin.MUTED))
            p.drawText(QRectF(x, lay["num"], cw, lay["num_h"]),
                       int(Qt.AlignmentFlag.AlignCenter), str(step + 1))
            # tendril to the next step when sliding between two sounding steps
            if s.on and s.slide and step + 1 < m.length and (step + 1) % STEPS_PER_ROW:
                nxt = m.steps[step + 1]
                a = self.region_rect(step, "pad")
                b = self.region_rect(step + 1, "pad")
                y = a.center().y() + a.height() * 0.12
                skin.paint_tendril(p, QPointF(a.right() - a.width() * 0.12, y),
                                   QPointF(b.left() + b.width() * 0.12, y),
                                   a.height() * (0.42 if nxt.on else 0.2), a.height() * 0.28)
