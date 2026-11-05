"""Dark theme in the grey-and-orange style of Ableton Live. Sizes are in em, so they follow
the system font and therefore the DPI scaling (125 % / 150 %)."""

from __future__ import annotations

BG = "#2b2b2b"
PANEL = "#363636"
FIELD = "#232323"
BORDER = "#4a4a4a"
TEXT = "#e8e8e8"
MUTED = "#a8a8a8"
ACCENT = "#ff9d2e"
ACCENT_TEXT = "#1b1b1b"
ERROR = "#ff7b7b"
WAVE = "#ff9d2e"

STYLESHEET = f"""
* {{ color: {TEXT}; }}
QMainWindow, QWidget#root, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {BG}; }}
QLabel {{ background: transparent; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#status {{ padding: 0.3em 0.5em; }}
QLabel#status[level="error"] {{ color: {ERROR}; }}
QLabel#status[level="ok"] {{ color: {TEXT}; }}
QLabel#heading {{ font-weight: bold; color: {ACCENT}; padding-top: 0.4em; }}
QListWidget {{ background: {PANEL}; border: 1px solid {BORDER}; outline: 0; padding: 0.2em; }}
QListWidget::item {{ padding: 0.45em 0.6em; }}
QListWidget::item:selected {{ background: {ACCENT}; color: {ACCENT_TEXT}; }}
QListWidget::item:disabled {{ color: {MUTED}; }}
QLineEdit, QComboBox {{
  background: {FIELD}; border: 1px solid {BORDER}; padding: 0.25em 0.4em; min-height: 1.3em;
  selection-background-color: {ACCENT}; selection-color: {ACCENT_TEXT};
}}
QLineEdit:disabled, QComboBox:disabled {{ color: {MUTED}; background: {BG}; }}
QLineEdit:focus {{ border: 1px solid {MUTED}; }}
QLineEdit[invalid="true"], QLineEdit[invalid="true"]:focus {{ border: 1px solid {ERROR}; }}
QComboBox QAbstractItemView {{ background: {FIELD}; selection-background-color: {ACCENT};
  selection-color: {ACCENT_TEXT}; }}
QPushButton {{
  background: {PANEL}; border: 1px solid {BORDER}; padding: 0.4em 1em; min-height: 1.3em;
}}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: {MUTED}; border-color: {PANEL}; }}
QPushButton#primary {{ background: {ACCENT}; color: {ACCENT_TEXT}; font-weight: bold;
  border: 1px solid {ACCENT}; }}
QPushButton#primary:disabled {{ background: {PANEL}; color: {MUTED}; border-color: {BORDER}; }}
QCheckBox {{ spacing: 0.5em; background: transparent; }}
QCheckBox::indicator {{ width: 0.9em; height: 0.9em; border: 1px solid {MUTED};
  background: {FIELD}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QCheckBox::indicator:disabled {{ border-color: {BORDER}; }}
QScrollBar:vertical {{ background: {BG}; width: 0.8em; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BORDER}; min-height: 2em; border-radius: 0.3em; }}
QScrollBar:horizontal {{ background: {BG}; height: 0.8em; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; min-width: 2em; border-radius: 0.3em; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QProgressBar {{ background: {FIELD}; border: 1px solid {BORDER}; text-align: center;
  min-height: 1.1em; }}
QProgressBar::chunk {{ background: {ACCENT}; }}
QSplitter::handle {{ background: {BG}; }}
QToolTip {{ background: {PANEL}; color: {TEXT}; border: 1px solid {BORDER}; }}
"""
