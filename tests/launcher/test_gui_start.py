"""Start failures of the double-click GUI path are logged and shown, never silent (#436), and
the windowed exe's missing streams are redirected (#445)."""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from launcher import cli, gui_start, startup_log  # noqa: E402


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
    def __init__(self, box_result=True, box_error=None, native_result=False):
        self.reads, self.boxes, self.natives = [], [], []
        self.box_result, self.box_error, self.native_result = box_result, box_error, native_result

    def read(self, prompt):
        self.reads.append(prompt)
        return ""

    def box(self, text):
        self.boxes.append(text)
        if self.box_error:
            raise self.box_error
        return self.box_result

    def native(self, text):
        self.natives.append(text)
        return self.native_result

    def run(self, **kw):
        return gui_start.run_gui(out=kw.pop("out", io.StringIO()), read=self.read,
                                 message_box=self.box, native_box=self.native, **kw)


def _broken(argv):
    raise ValueError("kaputtes Fenster")


def test_normal_start_passes_the_exit_code_and_writes_no_log(logdir, qt):
    rec = Recorder()
    assert rec.run(main=lambda argv: 0) == 0
    assert rec.reads == rec.boxes == rec.natives == []
    assert not logdir.exists()


def test_window_failure_is_logged_and_shown_in_a_qt_box(logdir, qt):
    rec = Recorder()
    out = io.StringIO()
    assert rec.run(main=_broken, out=out) == gui_start.EXIT_GUI_FAILED
    log = (logdir / startup_log.LOG_NAME).read_text(encoding="utf-8")
    assert "stage: window" in log and "ValueError: kaputtes Fenster" in log
    assert "Traceback" in log and "_broken" in log
    assert len(rec.boxes) == 1 and str(logdir / startup_log.LOG_NAME) in rec.boxes[0]
    assert rec.natives == [] and rec.reads == [], "Qt box shown: nothing else"
    assert "kaputtes Fenster" in out.getvalue()


@pytest.mark.parametrize("stage", gui_start.STAGES)
def test_each_stage_is_logged(logdir, qt, monkeypatch, stage):
    monkeypatch.setenv(gui_start.FAIL_ENV, stage)
    rec = Recorder()
    assert rec.run(main=lambda argv: 0) == gui_start.EXIT_GUI_FAILED
    assert f"stage: {stage}" in (logdir / startup_log.LOG_NAME).read_text(encoding="utf-8")
    # before Qt is up only the native box / console can report it
    assert (rec.boxes == []) == (stage == "import")


def test_failure_before_qt_uses_the_native_box(logdir, monkeypatch):
    monkeypatch.setenv(gui_start.FAIL_ENV, "import")
    monkeypatch.setattr(gui_start, "gui_importable", lambda: True)
    rec = Recorder(native_result=True)
    assert rec.run(main=lambda argv: 0) == gui_start.EXIT_GUI_FAILED
    assert rec.boxes == [] and len(rec.natives) == 1 and rec.reads == []
    assert "Details stehen in" in rec.natives[0]


def test_no_box_at_all_falls_back_to_the_console(logdir, monkeypatch):
    monkeypatch.setenv(gui_start.FAIL_ENV, "import")
    monkeypatch.setattr(gui_start, "gui_importable", lambda: True)
    rec = Recorder()
    out = io.StringIO()
    assert rec.run(out=out, main=lambda argv: 0) == gui_start.EXIT_GUI_FAILED
    assert rec.reads == ["Enter zum Beenden ..."]
    assert "Details stehen in" in out.getvalue()


@pytest.mark.parametrize("box_result, box_error", [(False, None), (None, RuntimeError("x"))])
def test_qt_box_not_possible_falls_back(logdir, qt, box_result, box_error):
    rec = Recorder(box_result=box_result, box_error=box_error)
    assert rec.run(main=_broken) == gui_start.EXIT_GUI_FAILED
    assert len(rec.boxes) == 1 and len(rec.natives) == 1
    assert rec.reads == ["Enter zum Beenden ..."]


def test_unwritable_log_still_reports(tmp_path, monkeypatch, qt):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    monkeypatch.setenv("ABELTONGOD_LOG_DIR", str(blocker))
    rec = Recorder()
    assert rec.run(main=_broken) == gui_start.EXIT_GUI_FAILED
    assert "konnte nicht geschrieben werden" in rec.boxes[0]


def test_reporting_survives_a_missing_stream(logdir, qt):
    rec = Recorder()

    class Gone:
        def write(self, text):
            raise ValueError("I/O operation on closed file")

        def flush(self):
            pass

    assert rec.run(main=_broken, out=Gone()) == gui_start.EXIT_GUI_FAILED
    assert len(rec.boxes) == 1


def test_excepthook_is_restored_and_logs_slot_errors(logdir, qt):
    def main_with_slot_error(argv):
        try:
            raise KeyError("im Slot")
        except KeyError as exc:
            sys.excepthook(type(exc), exc, exc.__traceback__)  # what PySide6 does
        return 0

    old = sys.excepthook
    sys.excepthook = quiet = lambda *a: None  # keep pytest's output clean
    try:
        assert Recorder().run(main=main_with_slot_error) == 0
        assert sys.excepthook is quiet
    finally:
        sys.excepthook = old
    assert "stage: running" in (logdir / startup_log.LOG_NAME).read_text(encoding="utf-8")


def test_headless_never_opens_a_modal_box(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    assert gui_start._qt_message_box("x") is False
    assert gui_start.native_message_box("x") is False


def test_console_wait_skips_without_an_interactive_stdin(monkeypatch):
    monkeypatch.setattr(sys, "stdin", None)
    assert gui_start._console_wait("p") == ""
    monkeypatch.setattr(sys, "stdin", io.StringIO("x\n"))  # not a tty
    assert gui_start._console_wait("p") == ""


def test_install_problems_are_reported_without_a_console(monkeypatch):
    monkeypatch.setattr(cli, "install_problems", lambda: ["contracts/ fehlt"])
    shown = []
    monkeypatch.setattr(gui_start, "native_message_box", lambda t: shown.append(t) or True)
    assert cli.main([], read=lambda p: "", out=io.StringIO(), gui=lambda: 0) == cli.EXIT_SETUP
    assert shown and "contracts/ fehlt" in shown[0]


def test_cli_exe_without_arguments_opens_the_text_menu():
    def no_gui():
        raise AssertionError("the CLI exe must not start the GUI")

    out = io.StringIO()
    assert cli.main([], read=lambda p: "", out=out, gui=no_gui, cli_exe=True) == 0
    assert "Werkzeuge:" in out.getvalue()


def test_windowed_streams_go_to_output_log(logdir, monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    path = startup_log.redirect_missing_streams()
    try:
        assert path == logdir / startup_log.OUTPUT_NAME
        print("hallo")
        sys.stderr.write("fehler\n")
        sys.stdout.flush()
        assert path.read_text(encoding="utf-8") == "hallo\nfehler\n"
    finally:
        sys.stdout.close()


def test_streams_left_alone_in_a_console(logdir):
    assert startup_log.redirect_missing_streams() is None
    assert not logdir.exists()


def test_unopenable_output_log_discards(tmp_path, monkeypatch):
    blocker = tmp_path / "f"
    blocker.write_text("x")
    monkeypatch.setenv("ABELTONGOD_LOG_DIR", str(blocker))
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    assert startup_log.redirect_missing_streams() is None
    try:
        print("weg")  # must not raise
    finally:
        sys.stdout.close()


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
