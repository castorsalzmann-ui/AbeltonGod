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


def controls_qss(accent: str) -> str:
    """Rules for the widget kit's object names (readout, chip, seg, disclosure, heading ...) in
    the blaster palette; ``accent`` is the colour of the selected dimension."""
    soft = mix(PANEL, accent, 0.22).name()
    return f"""
QLineEdit#readout {{ background: transparent; border: 1px solid transparent;
  padding: 0.05em 0.2em; min-height: 1.1em; }}
QLineEdit#readout:hover {{ border-color: {LINE}; }}
QLineEdit#readout:focus {{ border-color: {STEEL_HI}; background: {FIELD}; }}
QLineEdit#readout[muted="true"] {{ color: {MUTED}; }}
QLabel#heading {{ color: {MUTED}; font-size: 0.85em; font-weight: 600; letter-spacing: 1px; }}
QLabel#group {{ color: {TEXT}; font-weight: bold; letter-spacing: 2px; }}
QLabel#state {{ color: {MUTED}; font-size: 0.85em; }}
QLabel#state[on="true"] {{ color: {accent}; font-weight: bold; }}
QLabel#linkhint {{ color: #c9a27c; }}
QFrame#rule {{ background: {LINE}; max-height: 1px; min-height: 1px; border: 0; }}
QFrame#group {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 6px; }}
QFrame#group[locked="true"] {{ border: 1px solid {STEEL_HI}; }}
QPushButton#chip, QPushButton#seg {{ background: transparent; border: 1px solid {LINE};
  border-radius: 0.3em; padding: 0.15em 0.7em; min-height: 1.2em; color: {MUTED}; }}
QPushButton#chip {{ border-radius: 1em; padding: 0.15em 0.9em; }}
QPushButton#chip:hover, QPushButton#seg:hover {{ color: {TEXT}; border-color: {STEEL_HI}; }}
QPushButton#chip:checked, QPushButton#seg:checked {{ background: {soft}; color: #ffffff;
  border: 1px solid {accent}; }}
QPushButton#mini {{ padding: 0.1em 0.6em; min-height: 1.1em; font-size: 0.9em; }}
QPushButton#mini:checked {{ border-color: {accent}; color: #ffffff; background: {soft}; }}
QToolButton#disclosure {{ background: transparent; border: 0; color: {MUTED}; padding: 0.3em 0;
  font-weight: 600; }}
QToolButton#disclosure:hover, QToolButton#disclosure:focus {{ color: {TEXT}; }}
QProgressBar {{ background: {FIELD}; border: 1px solid {LINE}; border-radius: 3px;
  max-height: 0.5em; min-height: 0.5em; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 2px; }}
QScrollArea {{ background: transparent; border: 0; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: {BLACK}; width: 0.8em; }}
QScrollBar::handle:vertical {{ background: {STEEL}; border-radius: 0.3em; min-height: 2em; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""


def stylesheet(accent: str) -> str:
    return STYLESHEET + controls_qss(accent)


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
