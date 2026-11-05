"""Palette and stylesheet of the blaster window (sci-fi, neon on gunmetal; no image assets)."""

from __future__ import annotations

from PySide6.QtGui import QColor

BLACK = "#05070d"
PANEL = "#0c1220"
PANEL_HI = "#16203a"
STEEL_HI = "#6f7f9c"
STEEL = "#3a4663"
STEEL_LO = "#1b2237"
STEEL_DK = "#0d111f"
TEXT = "#dbe6ff"
MUTED = "#8a9bc2"
ERROR = "#ff8a6a"
FIELD = "#060913"
LINE = "#26345a"

STYLESHEET = f"""
* {{ color: {TEXT}; }}
QWidget#blasterroot {{ background: {BLACK}; }}
QLabel {{ background: transparent; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#title {{ font-weight: bold; letter-spacing: 3px; color: {TEXT}; }}
QLabel#cap {{ color: {MUTED}; font-size: 0.85em; letter-spacing: 1px; }}
QLabel#status {{ padding: 0.2em 0.5em; }}
QLabel#status[level="error"] {{ color: {ERROR}; font-weight: bold; }}
QFrame#panel {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 6px; }}
QLineEdit, QSpinBox {{ background: {FIELD}; border: 1px solid {LINE}; border-radius: 3px;
  padding: 0.2em 0.4em; min-height: 1.3em; selection-background-color: {STEEL}; }}
QLineEdit:focus, QSpinBox:focus {{ border: 1px solid {STEEL_HI}; }}
QLineEdit[invalid="true"] {{ border: 1px solid {ERROR}; }}
QPushButton {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {PANEL_HI}, stop:1 {PANEL});
  border: 1px solid {STEEL}; border-radius: 4px; padding: 0.35em 0.9em; min-height: 1.3em; }}
QPushButton:hover {{ border-color: {STEEL_HI}; }}
QPushButton:pressed {{ background: {PANEL}; }}
QPushButton:disabled {{ color: #5d6a8c; border-color: {LINE}; }}
QPushButton:focus {{ border-color: {TEXT}; }}
QCheckBox {{ spacing: 0.5em; background: transparent; }}
QCheckBox::indicator {{ width: 0.9em; height: 0.9em; border: 1px solid {STEEL_HI};
  background: {FIELD}; border-radius: 2px; }}
QCheckBox::indicator:checked {{ background: {STEEL_HI}; }}
QSlider::groove:horizontal {{ height: 4px; background: {STEEL_LO}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {STEEL_HI}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {TEXT}; width: 0.9em; margin: -0.4em 0;
  border-radius: 0.45em; }}
QListWidget {{ background: {FIELD}; border: 1px solid {LINE}; border-radius: 3px; }}
QListWidget::item {{ padding: 0.25em 0.4em; }}
QListWidget::item:selected {{ background: {STEEL}; color: #ffffff; }}
QToolTip {{ background: {FIELD}; color: {TEXT}; border: 1px solid {STEEL}; }}
"""


def qc(color, alpha: float = 1.0) -> QColor:
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def mix(a: str, b: str, t: float) -> QColor:
    ca, cb = QColor(a), QColor(b)
    return QColor(
        int(ca.red() + (cb.red() - ca.red()) * t),
        int(ca.green() + (cb.green() - ca.green()) * t),
        int(ca.blue() + (cb.blue() - ca.blue()) * t),
    )
