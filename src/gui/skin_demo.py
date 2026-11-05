"""Open the Goa skin window: ``python -m gui.skin_demo [--screenshot DIR]``.

``--screenshot DIR`` renders the window at three sizes to PNG files in DIR and exits (used for
visual checks; run it with ``QT_QPA_PLATFORM=offscreen`` on a machine without a display)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCREENSHOT_SIZES = ((460, 340), (360, 260), (720, 520))


def save_screenshots(window, out_dir: Path) -> list[Path]:
    """Grab the window at the given sizes; background is the transparent area (kept as alpha)."""
    from PySide6.QtWidgets import QApplication

    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for w, h in SCREENSHOT_SIZES:
        window.resize(w, h)
        window.show()
        QApplication.processEvents()  # let the layout follow the new size
        path = out_dir / f"goa_skin_{w}x{h}.png"
        if not window.grab().save(str(path)):
            raise OSError(f"could not write {path}")
        paths.append(path)
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gui.skin_demo")
    parser.add_argument("--screenshot", metavar="DIR", help="save PNGs to DIR and exit")
    args = parser.parse_args(argv)
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print('PySide6 fehlt. Installieren mit: pip install -e ".[gui]"', file=sys.stderr)
        return 2
    from .skin.settings import SkinSettings
    from .skin.window import CompactGoaWindow

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    if args.screenshot:
        # Screenshots must not read or write the user's real settings file.
        window = CompactGoaWindow(settings=SkinSettings())
        paths = save_screenshots(window, Path(args.screenshot))
        for p in paths:
            print(p)
        return 0
    window = CompactGoaWindow(use_default_path=True)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
