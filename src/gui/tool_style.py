"""Style rules for widgets the base theme does not cover (tabs, tables, text views) on the Goa,
Live and chat pages. Colours come from ``gui.theme``; applied per page so the base theme stays
untouched."""

from __future__ import annotations

from . import theme

STYLE = f"""
QPlainTextEdit {{ background: {theme.FIELD}; border: 1px solid {theme.BORDER}; padding: 0.3em;
  selection-background-color: {theme.ACCENT}; selection-color: {theme.ACCENT_TEXT}; }}
QTabWidget::pane {{ border: 1px solid {theme.BORDER}; background: {theme.BG}; }}
QTabBar::tab {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER};
  padding: 0.3em 1em; margin-right: 2px; }}
QTabBar::tab:selected {{ background: {theme.ACCENT}; color: {theme.ACCENT_TEXT}; }}
QTableWidget {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER};
  gridline-color: {theme.BORDER}; selection-background-color: {theme.ACCENT};
  selection-color: {theme.ACCENT_TEXT}; }}
QHeaderView::section {{ background: {theme.FIELD}; border: 0; border-right: 1px solid
  {theme.BORDER}; padding: 0.2em 0.5em; color: {theme.MUTED}; }}
QTableCornerButton::section {{ background: {theme.FIELD}; }}
QSpinBox {{ background: {theme.FIELD}; border: 1px solid {theme.BORDER}; padding: 0.25em 0.4em;
  min-height: 1.3em; }}
"""
