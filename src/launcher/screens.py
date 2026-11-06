"""Screenshots of the GUI on a real screen (``AbeltonGod-cli.exe --gui-screens DIR``, #463).

Opens the main window, shows every page and then the Goa, Acid and Blaster windows, and saves
two PNGs per view into ``DIR``:

* ``<scale>_<n>_<name>.png``: the screen area of the window including the title bar and frame
  (``QScreen.grabWindow(0, ...)``, i.e. what the desktop shows there);
* ``<scale>_<n>_<name>-inner.png``: the window's own rendering (``QWidget.grab``), without
  frame, independent of what overlaps it on the desktop.

Plus ``<scale>_index.txt`` with the screen size, device pixel ratio and each file. The scale
comes from ``QT_SCALE_FACTOR`` (set by the caller before the process starts). No sound is
played and nothing is rendered: the output folder and the Goa skin settings point into a temp
folder that is deleted afterwards. Used by the "Build exe" workflow on windows-latest; it says
nothing about the user's monitor.
"""

from __future__ import annotations

import os
import re
import tempfile
import time
from pathlib import Path
from typing import TextIO

SETTLE_S = 0.6  # let the window manager draw the frame before grabbing


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "page"


def _settle(app, seconds: float = SETTLE_S) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.02)


def _shoot(app, widget, folder: Path, stem: str, lines: list[str]) -> None:
    widget.raise_()
    widget.activateWindow()
    _settle(app)
    screen = widget.screen()
    fg = widget.frameGeometry()
    outer = screen.grabWindow(0, fg.x(), fg.y(), fg.width(), fg.height())
    inner = widget.grab()
    for suffix, pm in (("", outer), ("-inner", inner)):
        path = folder / f"{stem}{suffix}.png"
        ok = pm.save(str(path))
        lines.append(f"{path.name}: {pm.width()}x{pm.height()} px, saved={ok}")


def run(folder: Path, out: TextIO) -> int:
    folder.mkdir(parents=True, exist_ok=True)
    scale = os.environ.get("QT_SCALE_FACTOR", "1")
    tag = f"{round(float(scale) * 100):d}"
    names = ("ABELTONGOD_OUTPUT_DIR", "ABELTONGOD_SKIN_SETTINGS")
    old = {n: os.environ.get(n) for n in names}
    with tempfile.TemporaryDirectory(prefix="abeltongod-screens-") as tmp:
        os.environ["ABELTONGOD_OUTPUT_DIR"] = str(Path(tmp) / "out")
        os.environ["ABELTONGOD_SKIN_SETTINGS"] = str(Path(tmp) / "goa_skin.json")
        try:
            lines = _shoot_all(Path(tmp), folder, scale, tag)
        finally:  # the temp paths must not outlive this call
            for n, value in old.items():
                if value is None:
                    os.environ.pop(n, None)
                else:
                    os.environ[n] = value
    (folder / f"{tag}_index.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    out.write("\n".join(lines) + "\n")
    failed = [ln for ln in lines if "saved=False" in ln or "did not open" in ln]
    return 1 if failed else 0


def _shoot_all(tmp: Path, folder: Path, scale: str, tag: str) -> list[str]:
    from gui.app import create_app
    from gui.main_window import MainWindow
    from gui.windows import WINDOW_KEYS

    app = create_app([])
    win = MainWindow(out_dir=tmp / "out")
    win.show()
    screen = win.screen()
    geo = screen.geometry()
    lines = [f"platform {app.platformName()}, scale {scale}, screen {geo.width()}x"
             f"{geo.height()} logical, dpr {screen.devicePixelRatio():g}"]
    n = 0
    for row in range(win.categories.count()):
        win.categories.setCurrentRow(row)
        name = _slug(win.categories.item(row).text())
        n += 1
        _shoot(app, win, folder, f"{tag}_{n:02d}_main-{name}", lines)
    for key, _ in WINDOW_KEYS:
        tool = win.windows.open(key)
        n += 1
        if tool is None:
            lines.append(f"{key}: did not open ({win.windows.last_error})")
            continue
        _shoot(app, tool, folder, f"{tag}_{n:02d}_{key}", lines)
        tool.close()
        app.processEvents()
    win.close()
    app.processEvents()
    return lines
