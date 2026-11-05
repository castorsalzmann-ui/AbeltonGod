"""Procedural thorn geometry. Everything here is vector data (QPainterPath) derived from the
window size alone: no image assets, no randomness that depends on anything but a fixed seed.

Layout of a window of size W x H with thorn reach R (how far a tip may stick out):

    widget rect          = (0, 0, W, H)
    body rect ("outer")  = widget rect shrunk by R on every side; thorn bases sit on its edges
    thorn tips           = at most R outside the body rect, i.e. inside the widget (never clipped)
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath

# Thorn height classes (fraction of the reach); the pattern is repeated with a seeded shuffle.
_HEIGHTS = (0.42, 0.66, 1.0, 0.55, 0.82, 0.48, 0.92, 0.62)
_SEED = 407

EDGES = ("top", "right", "bottom", "left")
CORNERS = ("tl", "tr", "br", "bl")


def reach_for(width: float, height: float) -> float:
    """Thorn reach in logical pixels: grows a little with the window, clamped."""
    return max(18.0, min(34.0, 0.078 * min(width, height)))


def rail_for(reach: float) -> float:
    """Thickness of the chrome rail the thorns grow from."""
    return max(4.0, reach * 0.30)


def body_rect(width: float, height: float, reach: float) -> QRectF:
    return QRectF(reach, reach, width - 2 * reach, height - 2 * reach)


@dataclass(frozen=True)
class Thorn:
    """One spike: a base segment a-b on the body edge, a tip, and bow of the two sides.

    The two sides are quadratic curves bowed towards the axis (concave), which gives the sharp,
    slender look. ``kind`` is ``edge:<name>`` or ``corner:<name>``.
    """

    kind: str
    a: QPointF
    b: QPointF
    tip: QPointF
    ctrl_a: QPointF
    ctrl_b: QPointF

    @property
    def base_mid(self) -> QPointF:
        return QPointF((self.a.x() + self.b.x()) / 2, (self.a.y() + self.b.y()) / 2)

    def path(self) -> QPainterPath:
        p = QPainterPath(self.a)
        p.quadTo(self.ctrl_a, self.tip)
        p.quadTo(self.ctrl_b, self.b)
        p.closeSubpath()
        return p

    def facets(self) -> tuple[QPainterPath, QPainterPath]:
        """Split along the ridge (base midpoint -> tip): the a-side and the b-side facet."""
        m = self.base_mid
        # Ridge is straight; each facet keeps its own curved outer side.
        fa = QPainterPath(self.a)
        fa.quadTo(self.ctrl_a, self.tip)
        fa.lineTo(m)
        fa.closeSubpath()
        fb = QPainterPath(m)
        fb.lineTo(self.tip)
        fb.quadTo(self.ctrl_b, self.b)
        fb.closeSubpath()
        return fa, fb

    def outer_side_normals(self) -> tuple[tuple[float, float], tuple[float, float]]:
        """Unit normals (pointing away from the thorn axis) of the a-side and the b-side."""
        return _side_normal(self.a, self.tip, self.base_mid), _side_normal(
            self.b, self.tip, self.base_mid
        )


def _side_normal(p: QPointF, tip: QPointF, mid: QPointF) -> tuple[float, float]:
    dx, dy = tip.x() - p.x(), tip.y() - p.y()
    n = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / n, dx / n
    # Orient away from the axis (base mid -> tip is "inside").
    cx, cy = (p.x() + tip.x() + mid.x()) / 3, (p.y() + tip.y() + mid.y()) / 3
    if (p.x() - cx) * nx + (p.y() - cy) * ny < 0:
        nx, ny = -nx, -ny
    return nx, ny


def _edge_frame(body: QRectF, edge: str):
    """Return (start, along, out) for an edge: start point, unit vector along, unit outward."""
    if edge == "top":
        return QPointF(body.left(), body.top()), (1.0, 0.0), (0.0, -1.0), body.width()
    if edge == "bottom":
        return QPointF(body.left(), body.bottom()), (1.0, 0.0), (0.0, 1.0), body.width()
    if edge == "left":
        return QPointF(body.left(), body.top()), (0.0, 1.0), (-1.0, 0.0), body.height()
    return QPointF(body.right(), body.top()), (0.0, 1.0), (1.0, 0.0), body.height()


def _edge_thorns(body: QRectF, edge: str, reach: float) -> list[Thorn]:
    start, along, out, length = _edge_frame(body, edge)
    clear = reach * 1.55  # keep the corner horn free
    usable = length - 2 * clear
    if usable < reach:
        return []
    rng = random.Random(f"{_SEED}:{edge}")
    heights = list(_HEIGHTS)
    widths: list[float] = []
    hs: list[float] = []
    total = 0.0
    while True:
        rng.shuffle(heights)
        for h in heights:
            w = reach * (0.55 + 0.45 * h) * rng.uniform(0.92, 1.12)
            if total + w > usable and widths:
                break
            widths.append(w)
            hs.append(h * reach)
            total += w
        else:
            continue
        break
    scale = usable / total  # the bases tile the usable run exactly: clean joins
    thorns: list[Thorn] = []
    pos = clear
    for i, (w, h) in enumerate(zip(widths, hs, strict=True)):
        w *= scale
        lean = (0.22 if (i // 2) % 2 == 0 else -0.22) * w * (0.4 + 0.6 * (h / reach))
        a = QPointF(start.x() + along[0] * pos, start.y() + along[1] * pos)
        b = QPointF(start.x() + along[0] * (pos + w), start.y() + along[1] * (pos + w))
        tip = QPointF(
            start.x() + along[0] * (pos + w / 2 + lean) + out[0] * h,
            start.y() + along[1] * (pos + w / 2 + lean) + out[1] * h,
        )
        # Control points: 40 % up each side, pulled towards the axis -> concave, slender.
        pull = 0.10
        ca = QPointF(
            a.x() + (tip.x() - a.x()) * 0.45 + (b.x() - a.x()) * pull,
            a.y() + (tip.y() - a.y()) * 0.45 + (b.y() - a.y()) * pull,
        )
        cb = QPointF(
            b.x() + (tip.x() - b.x()) * 0.45 - (b.x() - a.x()) * pull,
            b.y() + (tip.y() - b.y()) * 0.45 - (b.y() - a.y()) * pull,
        )
        thorns.append(Thorn(f"edge:{edge}", a, b, tip, ca, cb))
        pos += w
    return thorns


def _corner_thorn(body: QRectF, corner: str, reach: float) -> Thorn:
    """A larger curved horn that sweeps diagonally out of the corner."""
    sx = -1.0 if corner in ("tl", "bl") else 1.0  # outward x
    sy = -1.0 if corner in ("tl", "tr") else 1.0  # outward y
    cx = body.left() if sx < 0 else body.right()
    cy = body.top() if sy < 0 else body.bottom()
    c = reach * 1.3  # base length along each edge
    # Base: from a point on the vertical edge to a point on the horizontal edge.
    # Inward means opposite to the outward sign.
    a = QPointF(cx, cy - sy * c)
    b = QPointF(cx - sx * c, cy)
    r = reach * 0.98
    tip = QPointF(cx + sx * r, cy + sy * r)
    # Sickle: one side bows outward (convex), the other inward (concave).
    ca = QPointF(cx + sx * r * 0.95, cy - sy * c * 0.30)
    cb = QPointF(cx + sx * r * 0.10, cy + sy * r * 0.10)
    return Thorn(f"corner:{corner}", a, b, tip, ca, cb)


def build_thorns(width: float, height: float, reach: float | None = None) -> list[Thorn]:
    """All thorns for a window of the given size, edges first, then the four corner horns."""
    r = reach if reach is not None else reach_for(width, height)
    body = body_rect(width, height, r)
    thorns: list[Thorn] = []
    for edge in EDGES:
        thorns.extend(_edge_thorns(body, edge, r))
    for corner in CORNERS:
        thorns.append(_corner_thorn(body, corner, r))
    return thorns


def thorn_union(width: float, height: float, reach: float | None = None) -> QPainterPath:
    path = QPainterPath()
    for t in build_thorns(width, height, reach):
        path.addPath(t.path())
    return path


def rail_path(body: QRectF, rail: float, radius: float) -> QPainterPath:
    """The chrome rail: ring between the body rect and the body rect shrunk by ``rail``."""
    outer = QPainterPath()
    outer.addRoundedRect(body, radius, radius)
    inner = QPainterPath()
    inner.addRoundedRect(body.adjusted(rail, rail, -rail, -rail), radius * 0.5, radius * 0.5)
    return outer.subtracted(inner)
