"""One calm dark theme for every page: a restrained palette, one accent colour for what matters
(main controls, the primary button, the selected page) and neutral greys for everything else.
Sizes are in em, so they follow the system font and therefore the DPI scaling (125 % / 150 %).

The widget kit (``gui.widgets``) paints with these constants too."""

from __future__ import annotations

BG = "#1f2226"
PANEL = "#272b30"
FIELD = "#181a1d"
BORDER = "#363b42"
TEXT = "#e4e7ea"
MUTED = "#8c939c"
ACCENT = "#e9a24b"
ACCENT_DIM = "#6d5430"  # accent track behind an inactive main control
ACCENT_TEXT = "#1b1b1b"
NEUTRAL = "#8f99a6"  # filled part of an "Erweitert" control
NEUTRAL_DIM = "#454b53"
BLOCKED = "#3b2826"  # range a linked parameter forbids
BLOCKED_EDGE = "#7a4a46"
ERROR = "#ee7d77"
HINT = "#c9a27c"  # why a linked parameter is limited (information, not an error)
WAVE = "#e9a24b"

STYLESHEET = f"""
* {{ color: {TEXT}; }}
QMainWindow, QWidget#root, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {BG}; }}
QLabel {{ background: transparent; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#status {{ padding: 0.3em 0.5em; }}
QLabel#status[level="error"] {{ color: {ERROR}; }}
QLabel#status[level="ok"] {{ color: {TEXT}; }}
QLabel#heading {{ color: {MUTED}; font-size: 0.85em; font-weight: 600; letter-spacing: 1px;
  padding-top: 0.8em; padding-bottom: 0.2em; }}
QLabel#linkhint {{ color: {HINT}; }}
QListWidget {{ background: {BG}; border: 0; outline: 0; padding: 0.2em; }}
QListWidget::item {{ padding: 0.45em 0.8em; border-radius: 0.3em; color: {MUTED}; }}
QListWidget::item:hover {{ background: {PANEL}; }}
QListWidget::item:selected {{ background: {PANEL}; color: {ACCENT}; }}
QListWidget::item:disabled {{ color: {NEUTRAL_DIM}; }}
QListWidget#results {{ background: {FIELD}; border-radius: 0.3em; }}
QLineEdit, QComboBox, QSpinBox {{
  background: {FIELD}; border: 1px solid {BORDER}; border-radius: 0.3em;
  padding: 0.25em 0.5em; min-height: 1.3em;
  selection-background-color: {ACCENT}; selection-color: {ACCENT_TEXT};
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: {MUTED}; background: {BG}; }}
QLineEdit:focus, QSpinBox:focus {{ border: 1px solid {NEUTRAL}; }}
QLineEdit[invalid="true"], QLineEdit[invalid="true"]:focus {{ border: 1px solid {ERROR}; }}
QLineEdit#readout {{ background: transparent; border: 1px solid transparent; padding: 0.1em 0.2em;
  min-height: 1.1em; }}
QLineEdit#readout:hover {{ border-color: {BORDER}; }}
QLineEdit#readout:focus {{ border-color: {NEUTRAL}; background: {FIELD}; }}
QLineEdit#readout[muted="true"] {{ color: {MUTED}; }}
QComboBox::drop-down {{ border: 0; width: 1.6em; }}
QComboBox QAbstractItemView {{ background: {FIELD}; selection-background-color: {PANEL};
  selection-color: {ACCENT}; border: 1px solid {BORDER}; outline: 0; }}
QPushButton {{
  background: {PANEL}; border: 1px solid {BORDER}; border-radius: 0.3em;
  padding: 0.4em 1em; min-height: 1.3em;
}}
QPushButton:hover {{ border-color: {NEUTRAL}; }}
QPushButton:focus {{ border-color: {NEUTRAL}; }}
QPushButton:disabled {{ color: {NEUTRAL_DIM}; border-color: {PANEL}; }}
QPushButton#primary {{ background: {ACCENT}; color: {ACCENT_TEXT}; font-weight: bold;
  border: 1px solid {ACCENT}; }}
QPushButton#primary:disabled {{ background: {PANEL}; color: {MUTED}; border-color: {BORDER}; }}
QPushButton#chip, QPushButton#seg {{ background: transparent; border: 1px solid {BORDER};
  border-radius: 1em; padding: 0.2em 0.9em; min-height: 1.2em; color: {MUTED}; }}
QPushButton#chip:hover, QPushButton#seg:hover {{ color: {TEXT}; border-color: {NEUTRAL}; }}
QPushButton#chip:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: {ACCENT_TEXT};
  font-weight: 600; }}
QPushButton#seg {{ border-radius: 0.3em; padding: 0.2em 0.8em; }}
QPushButton#seg:checked {{ background: {PANEL}; border-color: {NEUTRAL}; color: {TEXT}; }}
QPushButton#seg[accent="true"]:checked {{ border-color: {ACCENT}; color: {ACCENT}; }}
QToolButton#disclosure {{ background: transparent; border: 0; color: {MUTED}; padding: 0.4em 0;
  font-weight: 600; }}
QToolButton#disclosure:hover, QToolButton#disclosure:focus {{ color: {TEXT}; }}
QFrame#rule {{ background: {BORDER}; max-height: 1px; min-height: 1px; border: 0; }}
QScrollBar:vertical {{ background: {BG}; width: 0.8em; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BORDER}; min-height: 2em; border-radius: 0.3em; }}
QScrollBar:horizontal {{ background: {BG}; height: 0.8em; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; min-width: 2em; border-radius: 0.3em; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QProgressBar {{ background: {FIELD}; border: 0; border-radius: 0.2em; text-align: center;
  min-height: 0.5em; max-height: 0.5em; color: transparent; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 0.2em; }}
QSplitter::handle {{ background: {BG}; }}
QToolTip {{ background: {PANEL}; color: {TEXT}; border: 1px solid {BORDER}; }}
"""
