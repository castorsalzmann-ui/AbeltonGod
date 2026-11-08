"""``--gui-screens`` writes one PNG pair per page and tool window (#463). Offscreen here; the
real-screen run is the "Build exe" workflow on windows-latest."""

from __future__ import annotations

import io
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from launcher import cli  # noqa: E402


def test_gui_screens_writes_every_view(tmp_path, monkeypatch):
    if os.environ.get("ABELTONGOD_REQUIRE_GUI") != "1":
        pytest.importorskip("PySide6.QtWidgets")
    monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)
    monkeypatch.setenv("ABELTONGOD_OUTPUT_DIR", str(tmp_path / "mine"))
    monkeypatch.delenv("ABELTONGOD_SKIN_SETTINGS", raising=False)
    out = io.StringIO()
    assert cli.main(["--gui-screens", str(tmp_path / "s")], out=out) == 0
    names = sorted(p.name for p in (tmp_path / "s").glob("*.png"))
    for key in ("goa", "acid", "blaster"):
        assert any(n.endswith(f"_{key}.png") for n in names), names
    mains = [n for n in names if "_main-" in n and not n.endswith("-inner.png")]
    assert len(mains) >= 10, mains
    halves = [n for n in names if "_half-" in n and not n.endswith("-inner.png")]
    assert len(halves) == len(mains), halves  # #517: every page again at half width
    assert (tmp_path / "s" / "100_index.txt").is_file()
    # the temp paths screens.run sets must not leak into later code in this process
    assert os.environ["ABELTONGOD_OUTPUT_DIR"] == str(tmp_path / "mine")
    assert "ABELTONGOD_SKIN_SETTINGS" not in os.environ


def test_gui_screens_needs_one_folder():
    assert cli.main(["--gui-screens"], out=io.StringIO()) == cli.EXIT_USAGE
