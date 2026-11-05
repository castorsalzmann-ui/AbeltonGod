"""Entry logic of ``python -m gui.acid [--screenshot DIR]``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_SIZES = ((1180, 780), (1000, 700))


def create_acid_app(argv: list[str] | None = None):
    from gui.app import create_app

    from . import skin

    app = create_app(argv)
    app.setStyleSheet(skin.STYLESHEET)  # replaces the orange kick theme in this process
    return app


def take_screenshots(out_dir: Path, sizes=DEFAULT_SIZES, seed: int = 5) -> list[Path]:
    """Render the window at ``sizes`` into ``out_dir`` (PNG). The file name carries the size and
    the device pixel ratio, e.g. ``acid_1180x780_dpr1.5.png``."""
    from gui_core.acid_generate import GenOptions

    from .window import AcidWindow

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for w, h in sizes:
        win = AcidWindow(out_dir=out_dir)
        win.model.generate(GenOptions(seed=seed, density=0.7, accent_chance=0.3, slide_chance=0.3))
        win.sync()
        win.resize(w, h)
        win.show()
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()
        pm = win.grab()
        path = out_dir / f"acid_{w}x{h}_dpr{pm.devicePixelRatio():g}.png"
        if not pm.save(str(path)):
            raise OSError(f"could not write {path}")
        written.append(path)
        win.close()
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m gui.acid")
    ap.add_argument("--screenshot", metavar="DIR", help="render PNGs into DIR and exit")
    args = ap.parse_args(argv)
    try:
        app = create_acid_app([])
    except ImportError:
        print("PySide6 fehlt. Installieren mit: pip install -e \".[gui]\"", file=sys.stderr)
        return 2
    if args.screenshot:
        for p in take_screenshots(Path(args.screenshot)):
            print(p)
        return 0
    from .window import AcidWindow

    win = AcidWindow()
    win.show()
    return app.exec()

