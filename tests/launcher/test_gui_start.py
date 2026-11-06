"""Start failures of the double-click GUI path are logged and shown, never silent (#436)."""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from launcher import gui_start, startup_log  # noqa: E402


@pytest.fixture
def logdir(tmp_path, monkeypatch):
    d = tmp_path / "logs"
    monkeypatch.setenv("ABELTONGOD_LOG_DIR", str(d))
    monkeypatch.delenv(gui_start.FAIL_ENV, raising=False)
    return d


@pytest.fixture
def qt():
    if os.environ.get("ABELTONGOD_REQUIRE_GUI") != "1":
        pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication

    return QApplication


class Recorder:
    def __init__(self, box_result=True, box_error=None):
        self.hides, self.reads, self.boxes = [], [], []
        self.box_result, self.box_error = box_result, box_error

    def hide(self):
        self.hides.append(1)
        return True

    def read(self, prompt):
        self.reads.append(prompt)
        return ""

    def box(self, text):
        self.boxes.append(text)
        if self.box_error:
            raise self.box_error
        return self.box_result

    def run(self, **kw):
        return gui_start.run_gui(out=kw.pop("out", io.StringIO()), read=self.read,
                                 hide=self.hide, message_box=self.box, **kw)


def test_console_is_hidden_only_after_the_event_loop_runs(logdir, qt):
    rec = Recorder()

    def fake_main(argv):
        assert rec.hides == [], "console hidden before the window was built"
        qt.instance().processEvents()  # what exec() does first
        assert rec.hides == [1]
        return 0

    assert rec.run(main=fake_main) == 0
    assert rec.reads == [] and rec.boxes == []
    assert not logdir.exists(), "a normal start writes no log"


def test_window_failure_is_logged_and_shown_in_a_box(logdir, qt):
    rec = Recorder()
    out = io.StringIO()

    def broken_main(argv):
        raise ValueError("kaputtes Fenster")

    assert rec.run(main=broken_main, out=out) == gui_start.EXIT_GUI_FAILED
    log = (logdir / startup_log.LOG_NAME).read_text(encoding="utf-8")
    assert "stage: window" in log and "ValueError: kaputtes Fenster" in log
    assert "Traceback" in log and "broken_main" in log
    assert len(rec.boxes) == 1 and str(logdir / startup_log.LOG_NAME) in rec.boxes[0]
    assert rec.reads == [], "the box was shown, the console need not wait"
    qt.instance().processEvents()
    assert rec.hides == [], "the console must stay visible after a failed start"
    assert "kaputtes Fenster" in out.getvalue()


def test_failure_before_qt_keeps_the_console_and_waits(logdir, monkeypatch):
    monkeypatch.setenv(gui_start.FAIL_ENV, "import")
    monkeypatch.setattr(gui_start, "gui_importable", lambda: True)
    rec = Recorder()
    out = io.StringIO()
    assert rec.run(out=out, main=lambda argv: 0) == gui_start.EXIT_GUI_FAILED
    assert rec.boxes == [], "no message box before Qt is up"
    assert rec.reads == ["Enter zum Beenden ..."]
    assert rec.hides == []
    assert "stage: import" in (logdir / startup_log.LOG_NAME).read_text(encoding="utf-8")
    assert "Details stehen in" in out.getvalue()


@pytest.mark.parametrize("box_result, box_error", [(False, None), (None, RuntimeError("x"))])
def test_no_box_possible_falls_back_to_the_console(logdir, qt, box_result, box_error):
    rec = Recorder(box_result=box_result, box_error=box_error)

    def broken_main(argv):
        raise RuntimeError("weg")

    assert rec.run(main=broken_main) == gui_start.EXIT_GUI_FAILED
    assert len(rec.boxes) == 1 and rec.reads == ["Enter zum Beenden ..."]


def test_unwritable_log_still_reports(tmp_path, monkeypatch, qt):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    monkeypatch.setenv("ABELTONGOD_LOG_DIR", str(blocker))
    rec = Recorder()

    def broken_main(argv):
        raise RuntimeError("weg")

    assert rec.run(main=broken_main) == gui_start.EXIT_GUI_FAILED
    assert "konnte nicht geschrieben werden" in rec.boxes[0]


def test_excepthook_is_restored(logdir, qt):
    before = sys.excepthook
    Recorder().run(main=lambda argv: 0)
    assert sys.excepthook is before


def test_slot_errors_while_running_go_to_the_log(logdir, qt):
    def main_with_slot_error(argv):
        try:
            raise KeyError("im Slot")
        except KeyError as exc:
            sys.excepthook(type(exc), exc, exc.__traceback__)  # what PySide6 does
        return 0

    old = sys.excepthook
    sys.excepthook = lambda *a: None  # keep pytest's output clean
    try:
        assert Recorder().run(main=main_with_slot_error) == 0
    finally:
        sys.excepthook = old
    assert "stage: running" in (logdir / startup_log.LOG_NAME).read_text(encoding="utf-8")


def test_headless_platform_never_opens_a_modal_box(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    assert gui_start._qt_message_box("x") is False


def test_log_is_capped(logdir):
    logdir.mkdir()
    path = logdir / startup_log.LOG_NAME
    path.write_bytes(b"a" * (startup_log.MAX_BYTES + 10))
    assert startup_log.write_error("neu\n") == path
    assert path.stat().st_size < startup_log.MAX_BYTES
    assert path.read_text().endswith("neu\n")


def test_log_dir_per_platform(monkeypatch):
    monkeypatch.delenv("ABELTONGOD_LOG_DIR", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\u\AppData\Local")
    assert startup_log.log_dir() == Path(r"C:\Users\u\AppData\Local") / "AbeltonGod" / "logs"
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_STATE_HOME", "/s")
    assert startup_log.log_dir() == Path("/s/AbeltonGod/logs")
