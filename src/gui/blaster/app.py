"""Entry logic of ``python -m gui.blaster [--screenshot DIR]``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_SIZES = ((1280, 1000), (1000, 800))


def create_blaster_app(argv: list[str] | None = None):
    from gui.app import create_app

    from . import skin

    app = create_app(argv)
    app.setStyleSheet(skin.stylesheet("#ff4a2a"))
    return app


def take_screenshots(out_dir: Path, sizes=DEFAULT_SIZES) -> list[Path]:
    """PNGs of the window after one shot per size. Uses the real laser engine when present,
    otherwise the clearly marked stub (the window title says so). The name carries size and
    device pixel ratio."""
    import tempfile
    import time

    from PySide6.QtWidgets import QApplication

    from gui_core.blaster import load_engine
    from gui_core.blaster_stub import StubLaserEngine

    from .window import BlasterWindow

    out_dir.mkdir(parents=True, exist_ok=True)
    engine, _ = load_engine()
    engine = engine or StubLaserEngine()
    picture = {"salvo_count": 3, "salvo_pan_mode": "alternate_lr", "salvo_spacing_ms": 180,
               "reverb_mix": 0.3, "echo_mix": 0.25, "length_ms": 1400}
    written: list[Path] = []
    for w, h in sizes:
        with tempfile.TemporaryDirectory(prefix="abeltongod-blaster-shot-") as tmp:
            win = BlasterWindow(out_dir=Path(tmp), engine=engine, work_dir=Path(tmp) / "w")
            win.resize(w, h)
            win.show()
            for dim in ("pew", "plasma"):
                win.select_dimension(dim)
                if not getattr(engine, "is_stub", False):
                    try:  # the real engine may not render the v0.2 fields yet
                        win.session.render_shot(win.settings.with_values(**picture), 1)
                    except Exception:  # noqa: BLE001
                        win.session.engine = StubLaserEngine()
                        win.setWindowTitle(win.windowTitle() + " (Stub-Engine, nur Bild)")
                win._apply_settings(win.settings.with_values(**picture))
                win.pull_trigger()
                deadline = time.monotonic() + 30
                while win.busy and time.monotonic() < deadline:
                    QApplication.processEvents()
                    time.sleep(0.01)
            win.gun._stop_animation()
            win.gun.t = 0.04  # freeze the flash for the picture
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
    ap.add_argument("--scale", type=float, help="screenshots: Qt scale factor (1.5 = 150 %%)")
    args = ap.parse_args(argv)
    if args.scale:
        import os

        os.environ["QT_SCALE_FACTOR"] = str(args.scale)
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
