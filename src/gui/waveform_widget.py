"""Draws min/max peaks of a loaded WAV and the playhead. The peaks come from gui_core."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from gui_core.waveform import Waveform, peaks

from . import theme


class WaveformWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.waveform: Waveform | None = None
        self.playhead_s = 0.0
        self.message = "Keine Datei ausgewählt"
        self.setObjectName("waveform")
        self.setMinimumHeight(self.fontMetrics().height() * 6)

    def set_waveform(self, wf: Waveform | None, message: str = "") -> None:
        self.waveform = wf
        self.playhead_s = 0.0
        self.message = message or "Keine Datei ausgewählt"
        self.update()

    def set_playhead(self, seconds: float) -> None:
        self.playhead_s = seconds
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt name
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(theme.FIELD))
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.drawRect(0, 0, w - 1, h - 1)
        mid = h / 2
        p.drawLine(0, int(mid), w, int(mid))
        if self.waveform is None:
            p.setPen(QColor(theme.MUTED))
            p.drawText(QRectF(0, 0, w, h), int(Qt.AlignmentFlag.AlignCenter), self.message)
            return
        wf = self.waveform
        # Scale to the file's own peak so quiet files are visible; the axis is not dBFS.
        top = max(1e-9, float(abs(wf.samples).max()))
        pen = QPen(QColor(theme.WAVE), 1)
        p.setPen(pen)
        amp = (h / 2 - 3) / top
        for x, (lo, hi) in enumerate(peaks(wf.samples, max(1, w - 2))):
            p.drawLine(x + 1, int(mid - hi * amp), x + 1, int(mid - lo * amp))
        if self.playhead_s > 0:
            px = 1 + int((w - 2) * min(1.0, self.playhead_s / wf.duration_s))
            p.setPen(QPen(QColor(theme.TEXT), 1))
            p.drawLine(px, 0, px, h)
