"""Stereo scope: both channels of the whole rendered file (a salvo shows all its shots), with a
time scale. Shows what the engine returned; it does not judge it."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from gui_core.waveform import peaks

from . import skin

BUCKETS = 240


class SalvoScope(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.accent = QColor("#ff4a2a")
        self.left: list[tuple[float, float]] = []
        self.right: list[tuple[float, float]] = []
        self.duration_s = 0.0
        self.preview = False
        self.label = ""
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName("Stereo-Oszilloskop")

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt name
        return QSize(self.fontMetrics().height() * 20, int(self.fontMetrics().height() * 6.5))

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt name
        return QSize(self.fontMetrics().height() * 8, int(self.fontMetrics().height() * 6.5))

    def set_accent(self, color: str) -> None:
        self.accent = QColor(color)
        self.update()

    def set_audio(self, samples: np.ndarray, sample_rate: int, preview: bool = False,
                  label: str = "") -> None:
        a = np.asarray(samples, dtype=np.float64)
        if a.ndim == 1:
            a = np.stack([a, a], axis=1)
        self.left, self.right = peaks(a[:, 0], BUCKETS), peaks(a[:, 1], BUCKETS)
        self.duration_s = len(a) / float(sample_rate)
        self.preview, self.label = preview, label
        self.update()

    def clear(self) -> None:
        self.left, self.right, self.duration_s = [], [], 0.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt name
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            fm = self.fontMetrics()
            r = QRectF(1, 1, self.width() - 2, self.height() - 2)
            p.setPen(QPen(QColor(skin.LINE), 1))
            p.setBrush(QColor("#03060d"))
            p.drawRoundedRect(r, 5, 5)
            axis_h = fm.height() * 1.1
            lanes = QRectF(r.left() + fm.horizontalAdvance("L") + 10, r.top() + 4,
                           r.width() - fm.horizontalAdvance("L") - 18, r.height() - axis_h - 6)
            half = lanes.height() / 2
            p.setPen(QColor(skin.MUTED))
            p.drawText(QPointF(r.left() + 5, lanes.top() + half / 2 + fm.ascent() / 2), "L")
            p.drawText(QPointF(r.left() + 5, lanes.top() + 1.5 * half + fm.ascent() / 2), "R")
            for i, chan in enumerate((self.left, self.right)):
                mid = lanes.top() + half * (i + 0.5)
                amp = half / 2 - 2
                p.setPen(QPen(skin.qc(self.accent, 0.2), 1))
                p.drawLine(QPointF(lanes.left(), mid), QPointF(lanes.right(), mid))
                p.setPen(QPen(skin.qc(self.accent, 0.95), 1.6))
                n = len(chan)
                for k, (lo, hi) in enumerate(chan):
                    x = lanes.left() + lanes.width() * k / max(1, n - 1)
                    low = min(lo, hi - 0.02)
                    p.drawLine(QPointF(x, mid - hi * amp), QPointF(x, mid - low * amp))
            if self.duration_s > 0:  # time scale: a tick about every 0.25 / 0.5 / 1 s
                step = 0.25 if self.duration_s <= 1.5 else 0.5 if self.duration_s <= 3 else 1.0
                p.setPen(QPen(skin.qc(skin.MUTED, 0.6), 1))
                t = 0.0
                while t <= self.duration_s + 1e-9:
                    x = lanes.left() + lanes.width() * t / self.duration_s
                    p.drawLine(QPointF(x, lanes.bottom()), QPointF(x, lanes.bottom() + 3))
                    text = f"{t:g} s".replace(".", ",")
                    p.drawText(QPointF(min(x, lanes.right() - fm.horizontalAdvance(text)),
                                       r.bottom() - 3), text)
                    t += step
            if self.preview:
                badge = "Vorschau (gekürzt)"
                bw = fm.horizontalAdvance(badge) + 12
                br = QRectF(lanes.right() - bw, lanes.top(), bw, fm.height() * 1.1)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(skin.qc(skin.ERROR, 0.25))
                p.drawRoundedRect(br, 4, 4)
                p.setPen(QColor(skin.TEXT))
                p.drawText(br, Qt.AlignmentFlag.AlignCenter, badge)
            if not self.left:
                p.setPen(QColor(skin.MUTED))
                p.drawText(lanes, Qt.AlignmentFlag.AlignCenter, "Noch kein Schuss")
        finally:
            p.end()
