"""Toxic-alien skin for the acid window, drawn procedurally with QPainter.

Original design, no image assets: corroded plates with an eaten edge, acid drips, bubbling
pools, rib/vertebra bands, a hex membrane, vein lines, glossy step pads and tendril slides.
All randomness comes from seeded ``random.Random`` instances, so a screenshot of the same
window size is reproducible. Sizes are derived from ``u`` (the font height) so the skin
follows the DPI scaling.

How the window looks on Windows or at other DPI settings is not verified by CI.
"""

from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QRadialGradient,
)

# ---- palette ---------------------------------------------------------------------------
BLACK = "#040805"      # window base
BG = "#08120a"         # darkest panel
PLATE = "#0d1e10"      # panel body
PLATE_HI = "#14301a"
LIME = "#c8ff3d"       # accent / hottest
NEON = "#7dff2a"       # lit
POISON = "#2fd01b"
BILE = "#5c7d14"       # sickly yellow-green
DEEP = "#0b4a17"
RUST = "#3a2d0c"
TEXT = "#d9ffc7"       # main label colour
MUTED = "#8fd07a"      # secondary label colour
ERROR = "#ff8a6a"
FIELD = "#050c07"

STYLESHEET = f"""
* {{ color: {TEXT}; }}
QWidget#acidroot {{ background: {BLACK}; }}
QLabel {{ background: transparent; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#status {{ padding: 0.2em 0.5em; }}
QLabel#status[level="error"] {{ color: {ERROR}; font-weight: bold; }}
QLabel#cap {{ color: {MUTED}; font-size: 0.85em; letter-spacing: 1px; }}
QLineEdit, QComboBox, QSpinBox {{
  background: {FIELD}; border: 1px solid {DEEP}; border-radius: 3px;
  padding: 0.2em 0.4em; min-height: 1.3em; color: {TEXT};
  selection-background-color: {POISON}; selection-color: {BLACK};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1px solid {NEON}; }}
QLineEdit[invalid="true"], QLineEdit[invalid="true"]:focus {{ border: 1px solid {ERROR}; }}
QComboBox::drop-down {{ border: 0; width: 1.4em; }}
QComboBox QAbstractItemView {{ background: {FIELD}; color: {TEXT}; border: 1px solid {DEEP};
  selection-background-color: {POISON}; selection-color: {BLACK}; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 1.2em; background: {PLATE_HI};
  border: 0; }}
QPushButton {{
  background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1d4a22, stop:0.5 #0f2c14,
     stop:1 #0a1d0d);
  border: 1px solid {POISON}; border-radius: 4px; padding: 0.35em 0.9em; min-height: 1.3em;
  color: {TEXT};
}}
QPushButton:hover {{ border-color: {LIME}; color: #ffffff; }}
QPushButton:pressed {{ background: #0a1d0d; }}
QPushButton:disabled {{ color: #6a8f5c; border-color: {DEEP}; }}
QPushButton#primary {{
  background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #b9f93a, stop:0.55 #4fd01c,
     stop:1 #1f8a12);
  color: #04100a; font-weight: bold; border: 1px solid {LIME};
}}
QPushButton#primary:hover {{ color: #000000; border-color: #ffffff; }}
QCheckBox {{ spacing: 0.5em; background: transparent; color: {TEXT}; }}
QCheckBox::indicator {{ width: 0.9em; height: 0.9em; border: 1px solid {POISON};
  background: {FIELD}; border-radius: 2px; }}
QCheckBox::indicator:checked {{ background: {NEON}; border-color: {LIME}; }}
QToolTip {{ background: {FIELD}; color: {TEXT}; border: 1px solid {POISON}; }}
"""


def qc(hex_or_color, alpha: float = 1.0) -> QColor:
    c = QColor(hex_or_color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def _lum(hex_color: str) -> float:
    c = QColor(hex_color)

    def ch(v: int) -> float:
        s = v / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG contrast ratio of two ``#rrggbb`` colours."""
    a, b = _lum(fg), _lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


# ---- noise -----------------------------------------------------------------------------
class Noise1D:
    """Smooth 1-D value noise in [-1, 1] (three octaves, cosine interpolation)."""

    def __init__(self, seed: int, length: float, base_step: float = 14.0) -> None:
        rng = random.Random(seed)
        self.octaves = []
        for k in range(3):
            step = base_step / (2 ** k)
            n = int(length / step) + 3
            self.octaves.append((step, [rng.uniform(-1, 1) for _ in range(n)], 0.5 ** k))
        self.norm = sum(o[2] for o in self.octaves)

    def __call__(self, x: float) -> float:
        total = 0.0
        for step, pts, amp in self.octaves:
            i = max(0, int(x / step))
            i = min(i, len(pts) - 2)
            f = min(1.0, max(0.0, x / step - i))
            f = (1 - math.cos(f * math.pi)) / 2
            total += (pts[i] * (1 - f) + pts[i + 1] * f) * amp
        return total / self.norm


# ---- corroded plate --------------------------------------------------------------------
def plate_path(rect: QRectF, seed: int, depth: float) -> QPainterPath:
    """Outline of a metal plate whose edge has been eaten by acid: irregular, with bites."""
    rng = random.Random(seed)
    w, h = rect.width(), rect.height()
    per = 2 * (w + h)
    noise = Noise1D(seed + 11, per, base_step=depth * 3.2)
    bites = [(rng.uniform(0, per), rng.uniform(0.6, 1.0) * depth * 1.5,
              rng.uniform(0.7, 2.2) * depth)
             for _ in range(int(per / (depth * 9)) + 1)]

    def inset(s: float) -> float:
        v = depth * (0.28 + 0.34 * (noise(s) + 1) / 2)
        for pos, d, wd in bites:
            dd = abs(s - pos)
            if dd < wd:
                v += d * (0.5 + 0.5 * math.cos(math.pi * dd / wd)) ** 1.6
        return min(v, depth * 1.6)

    step = max(1.5, depth / 5)
    pts: list[QPointF] = []
    x0, y0, x1, y1 = rect.left(), rect.top(), rect.right(), rect.bottom()
    s = 0.0
    x = x0
    while x < x1:  # top edge, left to right
        pts.append(QPointF(x, y0 + inset(s)))
        x += step
        s += step
    y = y0
    while y < y1:  # right edge, top to bottom
        pts.append(QPointF(x1 - inset(s), y))
        y += step
        s += step
    x = x1
    while x > x0:  # bottom edge, right to left
        pts.append(QPointF(x, y1 - inset(s)))
        x -= step
        s += step
    y = y1
    while y > y0:  # left edge, bottom to top
        pts.append(QPointF(x0 + inset(s), y))
        y -= step
        s += step
    path = QPainterPath()
    path.addPolygon(QPolygonF(pts))
    path.closeSubpath()
    return path


def paint_plate(p: QPainter, rect: QRectF, seed: int, depth: float, ribs: bool = True) -> None:
    """A corroded dark-green plate: body gradient, ribs, rust stains, pits, etched edge."""
    path = plate_path(rect, seed, depth)
    rng = random.Random(seed + 3)
    body = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    body.setColorAt(0, qc(PLATE_HI))
    body.setColorAt(0.5, qc(PLATE))
    body.setColorAt(1, qc(BG))
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    # soft glow outside the eaten edge (acid fumes)
    for k, a in ((3, 0.05), (2, 0.08), (1, 0.12)):
        pen = QPen(qc(POISON, a), depth * 0.5 * k)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
    p.fillPath(path, QBrush(body))
    p.setClipPath(path)
    if ribs:
        paint_ribs(p, rect, depth)
    # rust / bile stains creeping in from the edge
    for _ in range(int(rect.width() / depth / 2.2) + 3):
        edge = rng.choice("tblr")
        t = rng.random()
        if edge == "t":
            cx, cy = rect.left() + t * rect.width(), rect.top()
        elif edge == "b":
            cx, cy = rect.left() + t * rect.width(), rect.bottom()
        elif edge == "l":
            cx, cy = rect.left(), rect.top() + t * rect.height()
        else:
            cx, cy = rect.right(), rect.top() + t * rect.height()
        r = depth * rng.uniform(1.2, 3.2)
        g = QRadialGradient(QPointF(cx, cy), r)
        g.setColorAt(0, qc(RUST if rng.random() < 0.6 else BILE, 0.55))
        g.setColorAt(1, qc(RUST, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(QPointF(cx, cy), r, r)
    # pits: dark craters with a lit lower rim
    for _ in range(int(rect.width() * rect.height() / (depth * depth * 55)) + 6):
        cx = rect.left() + rng.random() * rect.width()
        cy = rect.top() + rng.random() * rect.height()
        near = min(cx - rect.left(), rect.right() - cx, cy - rect.top(), rect.bottom() - cy)
        if near > depth * 5 and rng.random() < 0.75:
            continue
        r = depth * rng.uniform(0.12, 0.42)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qc(POISON, 0.22))
        p.drawEllipse(QPointF(cx + r * 0.25, cy + r * 0.3), r, r)
        p.setBrush(qc(BLACK, 0.9))
        p.drawEllipse(QPointF(cx, cy), r * 0.88, r * 0.88)
    p.setClipping(False)
    # etched edge: bright thin line along the eaten outline, dim second line inside
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(qc(NEON, 0.30), max(2.0, depth * 0.30)))
    p.drawPath(path)
    p.setPen(QPen(qc(LIME, 0.85), max(1.0, depth * 0.10)))
    p.drawPath(path)
    p.restore()


def paint_ribs(p: QPainter, rect: QRectF, depth: float) -> None:
    """Biomechanical rib bands across the plate and a vertebra column along the left edge."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    gap = depth * 2.6
    x0, x1 = rect.left() + depth * 3.4, rect.right() - depth * 0.8
    y = rect.top() + gap
    while y < rect.bottom() - gap * 0.4:
        path = QPainterPath()
        path.moveTo(x0, y)
        path.quadTo((x0 + x1) / 2, y + gap * 0.55, x1, y)
        p.setPen(QPen(qc(BLACK, 0.7), depth * 0.6))
        p.drawPath(path)
        p.setPen(QPen(qc("#1f7a2a", 0.75), depth * 0.24))
        p.translate(0, -depth * 0.25)
        p.drawPath(path)
        p.translate(0, depth * 0.25)
        y += gap
    # vertebra column
    cx = rect.left() + depth * 1.9
    y = rect.top() + depth * 1.2
    n = 0
    p.setPen(QPen(qc(DEEP, 0.9), depth * 0.35))
    p.drawLine(QPointF(cx, rect.top() + depth), QPointF(cx, rect.bottom() - depth))
    while y < rect.bottom() - depth * 1.6:
        wv = depth * (1.05 + 0.18 * math.sin(n * 0.9))
        hv = depth * 0.82
        g = QLinearGradient(cx - wv, y, cx + wv, y)
        g.setColorAt(0, qc(BLACK, 0.9))
        g.setColorAt(0.35, qc("#2d6a2a", 0.95))
        g.setColorAt(1, qc(BLACK, 0.9))
        p.setPen(QPen(qc(POISON, 0.35), 1))
        p.setBrush(QBrush(g))
        p.drawRoundedRect(QRectF(cx - wv, y, 2 * wv, hv), hv * 0.45, hv * 0.45)
        p.setPen(QPen(qc(LIME, 0.35), 1))  # spine spike
        p.drawLine(QPointF(cx + wv, y + hv / 2), QPointF(cx + wv + depth * 0.7, y + hv / 2))
        y += hv * 1.25
        n += 1
    p.restore()


# ---- hex membrane and veins ------------------------------------------------------------
def paint_hex(p: QPainter, rect: QRectF, cell: float, seed: int) -> None:
    """Hex membrane: dim outlined cells, a few glossy swollen ones."""
    rng = random.Random(seed)
    p.save()
    p.setClipRect(rect)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    rad = cell / 2  # flat-top hexes: column pitch 1.5 R, row pitch sqrt(3) R, odd columns shifted
    dy = math.sqrt(3) * rad
    col = 0
    x = rect.left() - rad
    while x < rect.right() + rad:
        y = rect.top() - dy + (dy / 2 if col % 2 else 0.0)
        while y < rect.bottom() + dy:
            pts = QPolygonF([
                QPointF(x + cell * 0.5 * math.cos(math.radians(60 * k)),
                        y + cell * 0.5 * math.sin(math.radians(60 * k)))
                for k in range(6)
            ])
            roll = rng.random()
            if roll < 0.10:
                g = QRadialGradient(QPointF(x - cell * 0.1, y - cell * 0.12), cell * 0.5)
                g.setColorAt(0, qc(NEON, 0.30))
                g.setColorAt(1, qc(DEEP, 0.10))
                p.setBrush(QBrush(g))
            elif roll < 0.35:
                p.setBrush(qc(DEEP, 0.18))
            else:
                p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(qc(POISON, 0.15), 1))
            p.drawPolygon(pts)
            if roll < 0.10:  # wet highlight
                p.setPen(QPen(qc(TEXT, 0.35), max(1.0, cell * 0.04)))
                p.drawArc(QRectF(x - cell * 0.30, y - cell * 0.32, cell * 0.36, cell * 0.30),
                          110 * 16, 70 * 16)
            y += dy
        x += rad * 1.5
        col += 1
    p.restore()


def paint_veins(p: QPainter, rect: QRectF, seed: int, count: int, width: float) -> None:
    """Faint glowing vein lines (smooth random curves)."""
    rng = random.Random(seed)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setClipRect(rect)
    for _ in range(count):
        x = rect.left() + rng.random() * rect.width()
        y = rect.top() + rng.random() * rect.height()
        path = QPainterPath(QPointF(x, y))
        ang = rng.uniform(0, 2 * math.pi)
        for _seg in range(rng.randint(3, 6)):
            ang += rng.uniform(-0.9, 0.9)
            ln = rng.uniform(0.04, 0.12) * (rect.width() + rect.height())
            nx, ny = x + math.cos(ang) * ln, y + math.sin(ang) * ln
            path.quadTo(QPointF(x + math.cos(ang + 0.7) * ln * 0.6,
                                y + math.sin(ang + 0.7) * ln * 0.6), QPointF(nx, ny))
            x, y = nx, ny
        for wmul, a in ((4.0, 0.04), (2.0, 0.07), (1.0, 0.16)):
            p.setPen(QPen(qc(POISON, a), width * wmul, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap))
            p.drawPath(path)
    p.restore()


# ---- drips and pools -------------------------------------------------------------------
def drip_layout(width: float, seed: int, u: float, skip: tuple[float, float] | None = None):
    """Deterministic drip list [(x, length_factor, base_width, phase)] across ``width``."""
    rng = random.Random(seed)
    out = []
    x = u * rng.uniform(0.6, 1.6)
    while x < width - u:
        if skip is None or not (skip[0] - u * 0.5 < x < skip[1] + u * 0.5):
            out.append((x, rng.uniform(0.3, 1.0), u * rng.uniform(0.26, 0.46),
                        rng.uniform(0, 6.28)))
        x += u * rng.uniform(1.6, 4.4)
    return out


def paint_drips(p: QPainter, top_y: float, drips, max_len: float, t: float = 0.0,
                creep: float = 0.0) -> None:
    """Acid running down from ``top_y``. ``creep`` in [0, 1] scales how far lengths wobble
    with time ``t`` (0 = static). Every drip stays within ``max_len`` below ``top_y``."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    for x, lf, bw, ph in drips:
        wob = 1.0 + creep * 0.12 * math.sin(t * 0.7 + ph)
        length = min(max_len, max(bw * 4, max_len * lf * wob))
        r = bw * 1.05
        nw = r * 0.55
        path = QPainterPath()
        path.moveTo(x - bw * 2.4, top_y)
        path.cubicTo(x - bw * 0.6, top_y + length * 0.05, x - nw * 1.2, top_y + length * 0.22,
                     x - nw, top_y + length * 0.55)
        path.lineTo(x - nw, top_y + length - r * 1.6)
        path.cubicTo(x - r * 1.0, top_y + length - r * 1.45, x - r, top_y + length - r * 1.0,
                     x - r, top_y + length - r * 0.9)
        path.arcTo(QRectF(x - r, top_y + length - 2 * r, 2 * r, 2 * r), 180, 180)
        path.cubicTo(x + r, top_y + length - r * 1.0, x + r * 1.0, top_y + length - r * 1.45,
                     x + nw, top_y + length - r * 1.6)
        path.lineTo(x + nw, top_y + length * 0.55)
        path.cubicTo(x + nw * 1.2, top_y + length * 0.22, x + bw * 0.6, top_y + length * 0.05,
                     x + bw * 2.4, top_y)
        path.closeSubpath()
        g = QLinearGradient(x, top_y, x, top_y + length)
        g.setColorAt(0, qc(DEEP))
        g.setColorAt(0.35, qc(POISON))
        g.setColorAt(1, qc(LIME))
        for wmul, a in ((3.0, 0.07), (1.8, 0.12)):  # glow
            p.setPen(QPen(qc(NEON, a), bw * wmul))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        p.setPen(QPen(qc(BLACK, 0.5), 1))
        p.setBrush(QBrush(g))
        p.drawPath(path)
        # specular streak on the left of the bulb and along the neck
        p.setPen(QPen(qc("#ffffff", 0.55), max(1.0, bw * 0.28), Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(x - nw * 0.35, top_y + length * 0.3),
                   QPointF(x - nw * 0.35, top_y + length - r * 1.9))
        p.setBrush(qc("#ffffff", 0.7))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(x - r * 0.38, top_y + length - r * 1.15), r * 0.22, r * 0.3)
    p.restore()


def pool_path(rect: QRectF, seed: int) -> QPainterPath:
    rng = random.Random(seed)
    cx, cy = rect.center().x(), rect.center().y()
    a, b = rect.width() / 2, rect.height() / 2
    ph = [rng.uniform(0, 6.28) for _ in range(3)]
    pts = []
    n = 48
    for k in range(n):
        th = 2 * math.pi * k / n
        wob = 1 + 0.10 * math.sin(3 * th + ph[0]) + 0.07 * math.sin(5 * th + ph[1]) \
            + 0.04 * math.sin(9 * th + ph[2])
        pts.append(QPointF(cx + a * wob * math.cos(th), cy + b * wob * math.sin(th)))
    path = QPainterPath()
    path.addPolygon(QPolygonF(pts))
    path.closeSubpath()
    return path


def paint_pool(p: QPainter, rect: QRectF, seed: int, t: float = 0.0, animate: bool = False) -> None:
    """A blobby acid pool with bubbles; ``t`` moves the bubbles when ``animate``."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    path = pool_path(rect, seed)
    g = QRadialGradient(rect.center() - QPointF(0, rect.height() * 0.15), rect.width() * 0.55)
    g.setColorAt(0, qc(LIME, 0.95))
    g.setColorAt(0.5, qc(POISON))
    g.setColorAt(1, qc(DEEP))
    p.setPen(QPen(qc(NEON, 0.12), rect.height() * 0.35))
    p.drawPath(path)
    p.setPen(QPen(qc(BLACK, 0.7), 1))
    p.setBrush(QBrush(g))
    p.drawPath(path)
    p.setClipPath(path)
    rng = random.Random(seed + 5)
    for _ in range(max(4, int(rect.width() / max(6.0, rect.height()) * 5))):
        bx = rect.left() + rect.width() * rng.uniform(0.1, 0.9)
        by = rect.top() + rect.height() * rng.uniform(0.2, 0.8)
        r = rect.height() * rng.uniform(0.07, 0.2)
        ph = rng.uniform(0, 6.28)
        if animate:
            r *= 1.0 + 0.18 * math.sin(t * 1.3 + ph)
            by -= rect.height() * 0.08 * (0.5 + 0.5 * math.sin(t * 0.8 + ph))
        p.setPen(QPen(qc(LIME, 0.9), max(1.0, r * 0.18)))
        p.setBrush(qc(DEEP, 0.45))
        p.drawEllipse(QPointF(bx, by), r, r)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qc("#ffffff", 0.75))
        p.drawEllipse(QPointF(bx - r * 0.35, by - r * 0.35), r * 0.22, r * 0.16)
    p.restore()


# ---- pads, lamps, tendrils, knobs -------------------------------------------------------
def paint_pad(p: QPainter, rect: QRectF, lit: bool, accent: bool, glow: float = 1.0) -> None:
    """Glossy step pad. ``glow`` in [0, 1.2] scales the halo (slow pulse when animated)."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    rad = rect.width() * 0.26
    if lit:
        halo = NEON if not accent else LIME
        for k, a in ((5, 0.05), (4, 0.07), (3, 0.09), (2, 0.12), (1, 0.16)):
            p.setPen(QPen(qc(halo, a * glow), rect.width() * 0.07 * k))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect, rad, rad)
    g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    if lit and accent:
        g.setColorAt(0, qc("#f6ffb0"))
        g.setColorAt(0.45, qc(LIME))
        g.setColorAt(1, qc("#5fb512"))
    elif lit:
        g.setColorAt(0, qc("#a4ff55"))
        g.setColorAt(0.45, qc(POISON))
        g.setColorAt(1, qc("#0d6a1c"))
    else:
        g.setColorAt(0, qc("#1b3d20"))
        g.setColorAt(1, qc("#08150b"))
    p.setPen(QPen(qc(BLACK, 0.9), max(1.0, rect.width() * 0.04)))
    p.setBrush(QBrush(g))
    p.drawRoundedRect(rect, rad, rad)
    # inner rim
    rim = rect.adjusted(rect.width() * 0.06, rect.width() * 0.06, -rect.width() * 0.06,
                        -rect.width() * 0.06)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(qc(LIME if lit else POISON, 0.55 if lit else 0.30),
                  max(1.0, rect.width() * 0.03)))
    p.drawRoundedRect(rim, rad * 0.8, rad * 0.8)
    # wet specular highlight on the upper part
    sp = QRectF(rect.left() + rect.width() * 0.14, rect.top() + rect.height() * 0.09,
                rect.width() * 0.72, rect.height() * 0.36)
    sg = QLinearGradient(sp.topLeft(), sp.bottomLeft())
    sg.setColorAt(0, qc("#ffffff", 0.60 if lit else 0.20))
    sg.setColorAt(1, qc("#ffffff", 0.02))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(sg))
    p.drawRoundedRect(sp, rad * 0.8, rad * 0.8)
    if lit:
        p.setBrush(qc("#ffffff", 0.85))
        p.drawEllipse(QPointF(rect.left() + rect.width() * 0.26, rect.top() + rect.height() * 0.2),
                      rect.width() * 0.05, rect.width() * 0.035)
    if accent:  # sharp ring with four ticks
        ring = rect.adjusted(-rect.width() * 0.10, -rect.width() * 0.10,
                             rect.width() * 0.10, rect.width() * 0.10)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(qc("#f2ff7a" if lit else MUTED, 1.0 if lit else 0.5),
                      max(1.5, rect.width() * 0.045)))
        p.drawRoundedRect(ring, rad * 1.25, rad * 1.25)
        c = ring.center()
        tk = rect.width() * 0.10
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            hw, hh = ring.width() / 2, ring.height() / 2
            p.drawLine(QPointF(c.x() + dx * hw, c.y() + dy * hh),
                       QPointF(c.x() + dx * (hw + tk), c.y() + dy * (hh + tk)))
    p.restore()


def paint_lamp(p: QPainter, rect: QRectF, lit: bool, color: str) -> None:
    """Small round toggle lamp (accent / slide)."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    c = rect.center()
    r = min(rect.width(), rect.height()) / 2
    if lit:
        for k, a in ((3, 0.07), (2, 0.12), (1, 0.2)):
            p.setPen(QPen(qc(color, a), r * 0.55 * k))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, r, r)
    g = QRadialGradient(c - QPointF(r * 0.3, r * 0.35), r * 1.3)
    if lit:
        g.setColorAt(0, qc("#ffffff"))
        g.setColorAt(0.3, qc(color))
        g.setColorAt(1, qc(DEEP))
    else:
        g.setColorAt(0, qc("#25502a"))
        g.setColorAt(1, qc("#071009"))
    p.setPen(QPen(qc(color if lit else POISON, 0.9 if lit else 0.45), max(1.0, r * 0.14)))
    p.setBrush(QBrush(g))
    p.drawEllipse(c, r, r)
    p.restore()


def paint_tendril(p: QPainter, a: QPointF, b: QPointF, sag: float, width: float) -> None:
    """Slide tendril from ``a`` to ``b``: a tapered, sagging, glossy vine with small bulbs."""
    mid = QPointF((a.x() + b.x()) / 2, max(a.y(), b.y()) + sag)
    n = 18
    pts = []
    for k in range(n + 1):
        t = k / n
        x = (1 - t) ** 2 * a.x() + 2 * (1 - t) * t * mid.x() + t * t * b.x()
        y = (1 - t) ** 2 * a.y() + 2 * (1 - t) * t * mid.y() + t * t * b.y()
        pts.append((x, y, t))
    left, right = [], []
    for k, (x, y, t) in enumerate(pts):
        k0, k1 = pts[max(0, k - 1)], pts[min(n, k + 1)]
        dx, dy = k1[0] - k0[0], k1[1] - k0[1]
        ln = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / ln, dx / ln
        wd = width * (0.35 + 0.65 * math.sin(math.pi * t) ** 0.6) / 2
        left.append(QPointF(x + nx * wd, y + ny * wd))
        right.append(QPointF(x - nx * wd, y - ny * wd))
    poly = QPolygonF(left + right[::-1])
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(QPen(qc(NEON, 0.16), width * 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    line = QPainterPath(QPointF(pts[0][0], pts[0][1]))
    for x, y, _t in pts[1:]:
        line.lineTo(x, y)
    p.drawPath(line)
    g = QLinearGradient(a, QPointF(a.x(), a.y() + sag))
    g.setColorAt(0, qc(LIME))
    g.setColorAt(1, qc(POISON))
    p.setPen(QPen(qc(BLACK, 0.6), 1))
    p.setBrush(QBrush(g))
    p.drawPolygon(poly)
    p.setPen(QPen(qc("#ffffff", 0.55), max(1.0, width * 0.16), Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap))
    hl = QPainterPath(QPointF(pts[2][0], pts[2][1] - width * 0.12))
    for x, y, _t in pts[3:-2]:
        hl.lineTo(x, y - width * 0.12)
    p.drawPath(hl)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(qc(LIME))
    for k in (4, 9, 14):
        p.drawEllipse(QPointF(pts[k][0], pts[k][1] + width * 0.55), width * 0.16, width * 0.16)
    p.restore()


def paint_vine_track(p: QPainter, rect: QRectF, knob_y: float | None, ticks: list[float],
                     lit: bool, phase: float = 0.0) -> None:
    """Vertical pitch slide: a dark groove with a wavy vine inside, tick marks and a bulb knob
    at ``knob_y`` (None: no knob)."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    cx = rect.center().x()
    gw = rect.width() * 0.34
    groove = QRectF(cx - gw / 2, rect.top(), gw, rect.height())
    gg = QLinearGradient(groove.topLeft(), groove.topRight())
    gg.setColorAt(0, qc(BLACK))
    gg.setColorAt(0.5, qc("#10281a"))
    gg.setColorAt(1, qc(BLACK))
    p.setPen(QPen(qc(POISON, 0.35), 1))
    p.setBrush(QBrush(gg))
    p.drawRoundedRect(groove, gw / 2, gw / 2)
    for ty in ticks:
        p.setPen(QPen(qc(MUTED, 0.45), 1))
        p.drawLine(QPointF(cx + gw * 0.9, ty), QPointF(cx + gw * 1.6, ty))
    vine = QPainterPath(QPointF(cx, rect.top() + gw))
    steps = 24
    for k in range(1, steps + 1):
        y = rect.top() + gw + (rect.height() - 2 * gw) * k / steps
        vine.lineTo(cx + math.sin(k * 0.9 + phase) * gw * 0.28, y)
    p.setPen(QPen(qc(POISON if lit else DEEP, 0.9 if lit else 0.7), max(1.0, gw * 0.18)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(vine)
    if knob_y is not None:
        r = rect.width() * 0.30
        c = QPointF(cx, knob_y)
        if lit:
            p.setPen(QPen(qc(NEON, 0.18), r * 0.9))
            p.drawEllipse(c, r, r)
        g = QRadialGradient(c - QPointF(r * 0.3, r * 0.35), r * 1.4)
        if lit:
            g.setColorAt(0, qc("#ffffff"))
            g.setColorAt(0.28, qc(LIME))
            g.setColorAt(1, qc(DEEP))
        else:
            g.setColorAt(0, qc("#3b6b3a"))
            g.setColorAt(1, qc("#0a1a0d"))
        p.setPen(QPen(qc(BLACK, 0.9), 1))
        p.setBrush(QBrush(g))
        p.drawEllipse(c, r, r)
    p.restore()


def paint_glow_text(p: QPainter, rect: QRectF, text: str, font, color: str,
                    flags=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter) -> None:
    """Text with a soft acid halo (the halo is drawn from offset copies; the text stays crisp)."""
    p.save()
    p.setFont(font)
    for dx, dy, a in ((-2, 0, .10), (2, 0, .10), (0, -2, .10), (0, 2, .10),
                      (-1, -1, .18), (1, 1, .18)):
        p.setPen(qc(NEON, a))
        p.drawText(rect.translated(dx, dy), int(flags), text)
    p.setPen(qc(color))
    p.drawText(rect, int(flags), text)
    p.restore()
