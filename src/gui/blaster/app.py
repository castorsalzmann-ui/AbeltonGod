"""Entry logic of ``python -m gui.blaster [--screenshot DIR]``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_SIZES = ((1000, 760), (900, 700))


def create_blaster_app(argv: list[str] | None = None):
    from gui.app import create_app

    from . import skin

    app = create_app(argv)
    app.setStyleSheet(skin.STYLESHEET)
    return app


def take_screenshots(out_dir: Path, sizes=DEFAULT_SIZES) -> list[Path]:
    """PNGs of the window after one shot per size. Uses the real laser engine when present,
    otherwise the clearly marked stub (the window title says so). The name carries size and
    device pixel ratio."""
    import tempfile

    from PySide6.QtWidgets import QApplication

    from gui_core.blaster import load_engine
    from gui_core.blaster_stub import StubLaserEngine

    from .window import BlasterWindow

    out_dir.mkdir(parents=True, exist_ok=True)
    engine, _ = load_engine()
    engine = engine or StubLaserEngine(stereo=True)
    written: list[Path] = []
    for w, h in sizes:
        with tempfile.TemporaryDirectory(prefix="abeltongod-blaster-shot-") as tmp:
            win = BlasterWindow(out_dir=Path(tmp), engine=engine, work_dir=Path(tmp) / "w")
            win.resize(w, h)
            win.show()
            win.pull_trigger()
            win.pull_trigger()
            QApplication.processEvents()
            win.gun.t = 0.04  # freeze the flash for the picture
            win.gun._stop_animation()
            win.gun.t = 0.04
            win.gun.update()
            QApplication.processEvents()
            pm = win.grab()
            path = out_dir / f"blaster_{w}x{h}_dpr{pm.devicePixelRatio():g}.png"
            if not pm.save(str(path)):
                raise OSError(f"could not write {path}")
            written.append(path)
            win.close()
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m gui.blaster")
    ap.add_argument("--screenshot", metavar="DIR", help="render PNGs into DIR and exit")
    args = ap.parse_args(argv)
    try:
        app = create_blaster_app([])
    except ImportError:
        print("PySide6 fehlt. Installieren mit: pip install -e \".[gui]\"", file=sys.stderr)
        return 2
    if args.screenshot:
        for p in take_screenshots(Path(args.screenshot)):
            print(p)
        return 0
    from .window import BlasterWindow

    win = BlasterWindow()
    win.show()
    return app.exec()
