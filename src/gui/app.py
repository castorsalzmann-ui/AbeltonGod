"""Application entry: ``python -m gui``."""

from __future__ import annotations

import sys


def create_app(argv: list[str] | None = None):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    from . import theme

    # Fractional scaling (125 % / 150 %) without rounding to whole factors.
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(theme.STYLESHEET)
    return app


def main(argv: list[str] | None = None) -> int:
    try:
        app = create_app(argv)
    except ImportError:
        print("PySide6 fehlt. Installieren mit: pip install -e \".[gui]\"", file=sys.stderr)
        return 2
    from gui_core.settings import SettingsStore

    from .main_window import MainWindow

    window = MainWindow(settings_store=SettingsStore.from_default_location())
    window.show()
    return app.exec()
