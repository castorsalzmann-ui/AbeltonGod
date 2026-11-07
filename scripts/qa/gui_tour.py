"""GUI tour (#437): walk every page of the main window and every tool window offscreen, render
one sample per category plus Goa, Acid and Blaster, and check that each result shows up in the
main window's library; export one arrangement plan from the planner page and check it with the
contract checker; ask the Copilot page (fake model, no Claude call) for one clap and find it in
the library (#491). Optional screenshots of every page at 100 % and 150 %.

Usage (screenshots never go into the repo; pick a folder outside it)::

    QT_QPA_PLATFORM=offscreen python scripts/qa/gui_tour.py --shots /tmp/tour
    python scripts/qa/gui_tour.py --shots /tmp/tour --scale 1.5   # one scale per process

Without ``--scale`` the script runs itself once per scale in a child process (the emulated
monitor, see :func:`emulate_screen`, must be set before Qt starts, so one process cannot
change it). Exit code 0 when every step
passed or failed only on a known gap (the step names its issue), 1 otherwise.

What this is and is not: a smoke tour on the Qt ``offscreen`` platform with a silent audio
backend. It proves that each control path runs and where the files land; it says nothing about
the sound, the look on a real Windows screen, or Live (nothing talks to Ableton).

The library check uses the main window's library page (``LibraryPanel`` over the output folder),
the same list the user sees. The last step marks one library file as "Favorit" (choice log,
#110; in memory, the tour has no settings file). Known gaps are named in :data:`KNOWN_GAPS`
with the text the failure must show; a gap step is xfail only for that reason, and red once it
passes.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATEGORY_KEYS = ("kick", "clap", "hat", "snare", "rim", "bass", "laser")
TOOL_KEYS = ("goa", "acid", "blaster")
SCALES = (1.0, 1.5)
WAIT_S = 60.0  # a render that answers within this is fine; the tour fails, never hangs

# Step name -> (issue, text the step's detail must contain). A known gap counts only when the
# step fails for exactly that reason; any other failure, and a pass, are unexpected (the tests
# turn them red, so a fix is noticed and an unrelated break is not hidden as "known").
KNOWN_GAPS: dict[str, tuple[int, str]] = {}  # #439, #440 fixed in PR #450
# Whether a window fits the screen at 150 % is checked in one place only:
# tests/gui/test_fit_150.py (lead decision, PR #458). The tour keeps the 150 % screenshots.


@dataclass
class Step:
    name: str
    ok: bool
    detail: str = ""
    seconds: float = 0.0

    @property
    def gap(self) -> int | None:
        """Issue number when this step fails for its known gap's reason, else None."""
        known = KNOWN_GAPS.get(self.name)
        if known is None or self.ok or known[1] not in self.detail:
            return None
        return known[0]

    @property
    def known_issue(self) -> int | None:
        """Issue of the gap this step is listed under (whatever happened)."""
        known = KNOWN_GAPS.get(self.name)
        return known[0] if known else None


@dataclass
class TourReport:
    steps: list[Step] = field(default_factory=list)
    shots: list[Path] = field(default_factory=list)

    def step(self, name: str) -> Step:
        for s in self.steps:
            if s.name == name:
                return s
        raise KeyError(name)

    @property
    def unexpected(self) -> list[Step]:
        """Failed steps without their known gap's reason, and known-gap steps that pass now."""
        return [s for s in self.steps
                if (s.ok and s.known_issue is not None) or (not s.ok and s.gap is None)]


class SilentBackend:
    """Playback backend that never makes a sound (tour and tests)."""

    available = True

    def __init__(self) -> None:
        self.played: list[Path] = []

    def play(self, wav_path: Path) -> None:
        self.played.append(Path(wav_path))

    def stop(self) -> None:
        pass


@contextlib.contextmanager
def isolated_env(home: Path) -> Iterator[None]:
    """Point every default path the GUI writes to (output folder, Goa skin settings, home)
    into ``home`` and make the tool windows silent; restored afterwards."""
    import gui.audio

    names = ("ABELTONGOD_OUTPUT_DIR", "ABELTONGOD_SKIN_SETTINGS", "HOME", "USERPROFILE")
    old = {n: os.environ.get(n) for n in names}
    old_choose = gui.audio.choose_backend
    os.environ["ABELTONGOD_OUTPUT_DIR"] = str(home / "AbeltonGod" / "output")
    os.environ["ABELTONGOD_SKIN_SETTINGS"] = str(home / "AbeltonGod" / "goa_skin.json")
    os.environ["HOME"] = os.environ["USERPROFILE"] = str(home)
    gui.audio.choose_backend = SilentBackend  # the tool windows import it at construction
    try:
        yield
    finally:
        gui.audio.choose_backend = old_choose
        for n, v in old.items():
            if v is None:
                os.environ.pop(n, None)
            else:
                os.environ[n] = v


SCREEN_PX = (1920, 1080)  # physical pixels of the emulated monitor


def emulate_screen(folder: Path, scale: float) -> None:
    """Set ``QT_QPA_PLATFORM`` / ``QT_SCALE_FACTOR`` for an offscreen monitor of
    :data:`SCREEN_PX` physical pixels at display scaling ``scale``: the logical screen is
    pixels / scale and screenshots have ``scale`` pixels per logical pixel (measured: 1920 x
    1080 at 1.5 gives a 1280 x 720 screen and a 100 x 30 button grabs as 150 x 45). The default
    offscreen screen is 800 x 800, which squeezes windows that clamp themselves to the screen.
    This emulates Windows display scaling through Qt's own factor; it is not a Windows screen.
    Must run before the QApplication exists. Changes the working directory to ``folder``: Qt
    splits the platform string at ":", so an absolute Windows path ("C:\\...") cannot be passed
    and the config file is named relative to the working directory."""
    import json

    cfg = folder / "offscreen_screen.json"
    cfg.write_text(json.dumps({"screens": [{
        "name": "tour", "x": 0, "y": 0, "width": SCREEN_PX[0], "height": SCREEN_PX[1],
        "logicalDpi": 96, "logicalBaseDpi": 96, "dpr": 1}]}), encoding="utf-8")
    os.chdir(folder)
    os.environ["QT_QPA_PLATFORM"] = f"offscreen:configfile={cfg.name}"
    os.environ["QT_SCALE_FACTOR"] = f"{scale:g}"


def wait_for(cond: Callable[[], bool], seconds: float = WAIT_S) -> bool:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    app.processEvents()
    return cond()


def make_window(out_dir: Path):
    """The main window as the user gets it, except for the silent backend and a no-op opener."""
    from gui.main_window import MainWindow

    w = MainWindow(out_dir=out_dir, backend=SilentBackend(), opener=lambda p: True)
    w.show()
    return w


def library_entry(window, wav: Path):
    """The main window library's entry for ``wav`` (refreshed first), or None."""
    window.library.set_folder(window._library_folder())
    for e in window.library.entries:
        if e.wav_path.resolve() == Path(wav).resolve():
            return e
    return None


def library_rows(window) -> list[str]:
    window.library.set_folder(window._library_folder())
    return [window.library.list.item(i).text() for i in range(window.library.list.count())]


# --- steps -----------------------------------------------------------------------------------

def page_rows(window) -> list[tuple[int, str]]:
    """(row, label) of every entry in the main window's left list."""
    return [(i, window.categories.item(i).text()) for i in range(window.categories.count())]


def visit_pages(window, shots: Path | None, tag: str) -> list[Step]:
    steps = []
    for row, label in page_rows(window):
        t = time.perf_counter()
        window.categories.setCurrentRow(row)
        wait_for(lambda: True, 0)
        ok = window.stack.currentIndex() == row and window.stack.currentWidget().isVisible()
        detail = "" if ok else f"stack shows row {window.stack.currentIndex()}"
        if shots is not None:
            path = shots / f"{tag}_main_{row:02d}_{_slug(label)}.png"
            if not window.grab().save(str(path)):
                ok, detail = False, f"screenshot not written: {path}"
        steps.append(Step(f"page:{_slug(label)}", ok, detail, time.perf_counter() - t))
    window.categories.setCurrentRow(0)
    return steps


def render_category(window, key: str) -> Step:
    """Render the category's default form once (one variant) and look for it in the library."""
    from gui_core.categories import CATEGORIES

    t = time.perf_counter()
    name = f"render:{key}"
    row = [c.key for c in CATEGORIES].index(key)
    window.categories.setCurrentRow(row)
    variants = window.panel.controls.get("variants")
    if variants is not None:
        variants.readout.setText("1")
        variants.readout.entered.emit("1")
    if not window.render_button.isEnabled():
        return Step(name, False, f"Rendern gesperrt: {window.status.text()}",
                    time.perf_counter() - t)
    before = window.results.count()
    window.render_button.click()
    if not wait_for(lambda: not window.running):
        return Step(name, False, f"no result after {WAIT_S:.0f} s", time.perf_counter() - t)
    new = [window.results.item(i) for i in range(before, window.results.count())]
    if not new:
        return Step(name, False, f"no file: {window.status.text()}", time.perf_counter() - t)
    from gui.drag import PATH_ROLE

    wav = Path(new[0].data(PATH_ROLE))
    entry = library_entry(window, wav)
    if entry is None:
        return Step(name, False, f"{wav.name} not in the library list", time.perf_counter() - t)
    if not entry.readable or entry.category != key:
        return Step(name, False, f"library shows {entry.category!r} ({entry.problem})",
                    time.perf_counter() - t)
    return Step(name, True, wav.name, time.perf_counter() - t)


def render_goa_page(window) -> Step:
    """Goa page of the main window: render the default arrangement; its WAVs must be in the
    library as readable entries."""
    t = time.perf_counter()
    name = "render:goa-page"
    window.categories.setCurrentRow(window.tool_rows["goa"])
    page = window.goa
    if not page.render_button.isEnabled():
        return Step(name, False, f"Rendern gesperrt: {page.status.text()}",
                    time.perf_counter() - t)
    page.render_button.click()
    if not wait_for(lambda: not page.running):
        return Step(name, False, f"no result after {WAIT_S:.0f} s", time.perf_counter() - t)
    res = page.result
    if res is None or not res.ok:
        return Step(name, False, f"render failed: {page.status.text()}", time.perf_counter() - t)
    return _all_in_library(window, name, list(res.sample_paths), t,
                           f"{res.mid_path.name} + {len(res.sample_paths)} WAV")


def reference_kick(window) -> Step:
    """Referenz page (#480): measure the tour's own kick render, take the nearest candidate
    as start values; the kick page must show that candidate's preset."""
    t = time.perf_counter()
    name = "reference:kick"
    kicks = [p for p in window.result_paths if p.name.startswith("kick")]
    if not kicks:
        return Step(name, False, "no kick render to measure", time.perf_counter() - t)
    window.categories.setCurrentRow(window.tool_rows["reference"])
    page = window.reference
    if not page.analyse(kicks[0]):
        return Step(name, False, "measurement refused (busy)", time.perf_counter() - t)
    if not wait_for(lambda: not page.busy):
        return Step(name, False, f"no result after {WAIT_S:.0f} s", time.perf_counter() - t)
    if page.outcome is None or not page.outcome.ok:
        return Step(name, False, f"measurement failed: {page.status.text()}",
                    time.perf_counter() - t)
    if not page.apply_button.isEnabled():
        return Step(name, False, "apply button disabled after a result", time.perf_counter() - t)
    page.apply_button.click()
    wait_for(lambda: True, 0)
    cand = page.outcome.match.nearest
    if window.form_key != "kick" or window.model.preset != cand.preset:
        return Step(name, False, f"kick form shows {window.form_key}/{window.model.preset}, "
                    f"expected kick/{cand.preset}", time.perf_counter() - t)
    return Step(name, True, cand.name, time.perf_counter() - t)


def export_planner(window) -> Step:
    """Arrangement-Planer page (#139): export the default plan; the file must lie in
    ``<Ausgabeordner>/Plans`` and pass the contract checker ``plan_problems``."""
    import json

    from orchestrator.arrangement_plan import plan_problems

    t = time.perf_counter()
    name = "export:planner"
    window.categories.setCurrentRow(window.tool_rows["planner"])
    page = window.planner
    if not page.export_button.isEnabled():
        return Step(name, False, f"Export gesperrt: {page.status.text()}",
                    time.perf_counter() - t)
    page.export_button.click()
    path = page.last_export
    if path is None:
        return Step(name, False, f"no file: {page.status.text()}", time.perf_counter() - t)
    expected = window._library_folder() / "Plans"
    if path.parent != expected:
        return Step(name, False, f"{path} not in {expected}", time.perf_counter() - t)
    problems = plan_problems(json.loads(path.read_text(encoding="utf-8")))
    if problems:
        return Step(name, False, f"{path.name}: {problems[:2]}", time.perf_counter() - t)
    return Step(name, True, path.name, time.perf_counter() - t)


CHAT_CLAP = {"category": "clap", "preset": "short", "prompt": "", "seed": 7, "variants": 1,
             "adjust": []}


def chat_generate(window, home: Path) -> Step:
    """Copilot page (#491) on a fake model (no Claude call): one ``generate_sample`` call
    through the real orchestrator and guard; the clap must be in the library and listed as a
    link in the transcript. Live is not touched (the fake model asks for no import)."""
    from guard import Guard
    from gui_core.chat import ChatSession
    from orchestrator.fake_model import FakeModel

    t = time.perf_counter()
    name = "chat:generate"
    page = window.chat
    model = FakeModel([
        {"tool_calls": [{"id": "g1", "name": "generate_sample", "arguments": CHAT_CLAP}],
         "usage": {"output_tokens": 50, "cost_usd": 0.01}},
        {"text": "Ein Clap liegt in der Bibliothek.",
         "usage": {"output_tokens": 20, "cost_usd": 0.01}}])
    # refused_roots=(): the tour's home may be a test temp folder inside the checkout.
    page.set_session(ChatSession(home / ".env", model=model,
                                 guard=Guard(log_path=home / "AbeltonGod" / "usage.jsonl"),
                                 session_options={"refused_roots": ()}))
    window.categories.setCurrentRow(window.tool_rows["chat"])
    page.input.setText("Mach einen kurzen Clap")
    page.send()
    if not wait_for(lambda: not page.busy):
        return Step(name, False, f"no answer after {WAIT_S:.0f} s", time.perf_counter() - t)
    reply = page.last_reply
    if reply is None or not reply.success:
        return Step(name, False, f"request failed: {reply.text if reply else '-'}",
                    time.perf_counter() - t)
    missing = [p.name for p in reply.files if str(p) not in page.transcript.toPlainText()]
    if missing:
        return Step(name, False, f"not in the transcript: {missing}", time.perf_counter() - t)
    return _all_in_library(window, name, list(reply.files), t,
                           ", ".join(p.name for p in reply.files))


def _all_in_library(window, name: str, wavs: list[Path], t: float, what: str) -> Step:
    if not wavs:
        return Step(name, False, f"{what}: no WAV written", time.perf_counter() - t)
    missing, bad = [], []
    for wav in wavs:
        e = library_entry(window, wav)
        if e is None:
            missing.append(wav.name)
        elif not e.readable:
            bad.append(f"{wav.name}: {e.problem}")
    if missing:
        return Step(name, False, f"{what}: not in the library: {', '.join(missing[:3])}",
                    time.perf_counter() - t)
    if bad:
        return Step(name, False, f"{what}: unreadable in the library: {'; '.join(bad[:2])}",
                    time.perf_counter() - t)
    return Step(name, True, what, time.perf_counter() - t)


def open_tool(window, key: str, shots: Path | None, tag: str) -> tuple[Step, object]:
    t = time.perf_counter()
    window.window_buttons[key].click()
    win = window.windows.window(key)
    if win is None:
        return Step(f"open:{key}", False, window.window_note.text(),
                    time.perf_counter() - t), None
    wait_for(lambda: True, 0)
    if hasattr(win, "opener"):  # never launch the system file manager from the tour
        win.opener = lambda p: True
    ok, detail = win.isVisible(), win.windowTitle()
    if shots is not None:
        path = shots / f"{tag}_window_{key}.png"
        if not win.grab().save(str(path)):
            ok, detail = False, f"screenshot not written: {path}"
    return Step(f"open:{key}", ok, detail, time.perf_counter() - t), win


def render_goa_window(window, win) -> Step:
    """Goa tool window: its Render button must produce files that appear in the library."""
    t = time.perf_counter()
    before = set(_wavs(window._library_folder()))
    win.body.render_button.click()
    # The render may run in a worker thread (GoaPanel); the placeholder answers at once and
    # has no ``running``. Never a short fixed deadline (CLAUDE.md: >= 5 s for an answer).
    wait_for(lambda: not getattr(win.body, "running", False), WAIT_S)
    new = sorted(set(_wavs(window._library_folder())) - before)
    status = getattr(win.body, "status", None)
    text = status.text() if status is not None else ""
    if not new:
        return Step("render:goa-window", False, f"no new WAV; window says: {text}",
                    time.perf_counter() - t)
    return _all_in_library(window, "render:goa-window", new, t, f"{len(new)} WAV")


def render_acid(window, win) -> Step:
    """Acid window: generate, export MIDI and WAV; the WAV must be listed in the main library
    (without sidecar: acid lines have no contract, #439)."""
    t = time.perf_counter()
    win.generate_button.click()
    win.export_button.click()
    status = win.status.text()
    if "MIDI geschrieben" not in status:
        return Step("render:acid", False, f"export failed: {status}", time.perf_counter() - t)
    win.wav_button.click()
    wav = win.actions.path
    if wav is None or wav.suffix != ".wav":
        return Step("render:acid", False, f"WAV export failed: {win.status.text()}",
                    time.perf_counter() - t)
    if library_entry(window, wav) is None:
        return Step("render:acid", False, f"{wav.name} not in the library",
                    time.perf_counter() - t)
    return Step("render:acid", True, wav.name, time.perf_counter() - t)


def render_blaster_shot(window, win) -> Step:
    """Blaster: pull the trigger once; the shot must appear in the main library."""
    t = time.perf_counter()
    name = "render:blaster-shot"
    if win.pull_trigger() != "started":
        return Step(name, False, f"trigger refused: {win.status.text()}",
                    time.perf_counter() - t)
    if not wait_for(lambda: not win.busy):
        return Step(name, False, f"no shot after {WAIT_S:.0f} s", time.perf_counter() - t)
    if not win.session.history:
        return Step(name, False, "no shot in the history", time.perf_counter() - t)
    win.keep_btn.click()  # "In Bibliothek speichern" (#439)
    if not wait_for(lambda: not win._saving, WAIT_S) or win.actions.path is None:
        return Step(name, False, f"shot not saved: {win.status.text()}",
                    time.perf_counter() - t)
    wav = win.actions.path
    return _all_in_library(window, name, [wav], t, wav.name)


def export_blaster_bank(window, win) -> Step:
    """Blaster: export a bank of 2 shots into the library folder; both must be in the library."""
    t = time.perf_counter()
    name = "render:blaster-bank"
    target = window._library_folder()
    target.mkdir(parents=True, exist_ok=True)
    win.ask_dir = lambda parent, start: target
    before = set(_wavs(target))
    if hasattr(win, "bank_count"):
        win.bank_count.setValue(2)
    win.bank_btn.click()
    if not wait_for(lambda: not win.busy):
        return Step(name, False, f"no bank after {WAIT_S:.0f} s", time.perf_counter() - t)
    new = sorted(set(_wavs(target)) - before)
    return _all_in_library(window, name, new, t, f"bank of {len(new)} WAV")


def tools_close_with_main(window) -> Step:
    """Closing the main window closes the tool windows (WindowManager.close_all)."""
    keys = [k for k in TOOL_KEYS if window.windows.is_open(k)]
    window.close()
    still = [k for k in keys if window.windows.is_open(k)]
    return Step("close:tools-with-main", not still and bool(keys),
                f"open before: {keys}, still open: {still}")


def choose_in_library(window) -> Step:
    """Library choice log (#110): mark the first listed WAV as favourite with a note; the log
    must hold the entry, the row must show the mark and "nur Favoriten" must keep only it.
    The tour's main window has no settings file, so the log stays in memory."""
    from gui.drag import PATH_ROLE

    t = time.perf_counter()
    name = "choice:library"
    lib = window.library
    window.categories.setCurrentRow(window.library_row)
    wait_for(lambda: True, 0)
    if lib.choices.path is not None:
        return Step(name, False, f"log would be written to {lib.choices.path}",
                    time.perf_counter() - t)
    if lib.list.count() == 0:
        return Step(name, False, "library is empty", time.perf_counter() - t)
    lib.list.setCurrentRow(0)
    wav = lib.current_path()
    lib.note.setText("Tour")
    lib.favourite_button.click()
    res = lib.choices.read()
    last = res.entries[-1] if res.entries else {}
    problems = []
    if last.get("verdict") != "favourite" or last.get("note") != "Tour":
        problems.append(f"log entry {last!r}")
    if not lib.list.currentItem() or not lib.list.currentItem().text().startswith("★ "):
        problems.append("row has no favourite mark")
    # A verdict belongs to the bytes (sha256): byte-identical copies elsewhere in the output
    # folder (the Goa page and the Goa window render the same files) are favourites too.
    digest = hashlib.sha256(wav.read_bytes()).digest()
    same = sorted(e.wav_path for e in lib.entries
                  if hashlib.sha256(e.wav_path.read_bytes()).digest() == digest)
    lib.only_favourites.setChecked(True)
    kept = sorted(Path(lib.list.item(i).data(PATH_ROLE)) for i in range(lib.list.count()))
    lib.only_favourites.setChecked(False)
    if kept != same:
        problems.append(f"'nur Favoriten' shows {[p.name for p in kept]}, expected "
                        f"{[p.name for p in same]}")
    window.categories.setCurrentRow(0)
    return Step(name, not problems, "; ".join(problems), time.perf_counter() - t)


def _wavs(folder: Path) -> list[Path]:
    return sorted(folder.rglob("*.wav")) if folder.is_dir() else []


def _slug(text: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in text.split("  (")[0]]
    return "".join(keep).strip("-")


# --- whole tour ------------------------------------------------------------------------------

def run_tour(home: Path, shots: Path | None = None, tag: str = "100",
             renders: bool = True) -> TourReport:
    """Run the tour with every default path inside ``home``. ``renders=False`` only visits and
    photographs the pages and windows (the 150 % pass)."""
    from gui.app import create_app

    create_app([])
    report = TourReport()
    if shots is not None:
        shots.mkdir(parents=True, exist_ok=True)
    with isolated_env(home):
        window = make_window(home / "AbeltonGod" / "output")
        try:
            report.steps += visit_pages(window, shots, tag)
            if renders:
                report.steps += [render_category(window, k) for k in CATEGORY_KEYS]
                report.steps.append(render_goa_page(window))
                report.steps.append(export_planner(window))
                report.steps.append(reference_kick(window))
                report.steps.append(chat_generate(window, home))
            wins = {}
            for key in TOOL_KEYS:
                step, wins[key] = open_tool(window, key, shots, tag)
                report.steps.append(step)
            if renders:
                if wins["goa"] is not None:
                    report.steps.append(render_goa_window(window, wins["goa"]))
                if wins["acid"] is not None:
                    report.steps.append(render_acid(window, wins["acid"]))
                if wins["blaster"] is not None:
                    report.steps.append(render_blaster_shot(window, wins["blaster"]))
                    report.steps.append(export_blaster_bank(window, wins["blaster"]))
            report.steps.append(tools_close_with_main(window))
            if renders:
                report.steps.append(choose_in_library(window))
        finally:
            window.close()
            window.deleteLater()
            wait_for(lambda: True, 0)
    if shots is not None:
        report.shots = sorted(shots.glob(f"{tag}_*.png"))
    return report


def format_report(report: TourReport) -> str:
    lines = [f"{'step':28} {'result':10} {'s':>6}  detail"]
    for s in report.steps:
        if s.ok:
            res = f"FIXED? #{s.known_issue}" if s.known_issue else "PASS"
        else:
            res = f"GAP #{s.gap}" if s.gap else "FAIL"
        lines.append(f"{s.name:28} {res:10} {s.seconds:6.2f}  {s.detail}")
    return "\n".join(lines)


def shots_allowed(folder: Path) -> bool:
    """Screenshots never go into the repo. Inside the checkout a folder is accepted only when
    ``git check-ignore`` confirms that files in it are ignored (e.g. a pytest ``--basetemp``
    folder that ``.gitignore`` lists); without git, everything inside the checkout is refused."""
    path = folder.resolve()
    if not path.is_relative_to(ROOT):
        return True
    probe = path / "tour_probe.png"  # check-ignore also answers for paths that do not exist
    try:
        res = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", str(probe)],
                             capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return res.returncode == 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--shots", type=Path, default=None,
                    help="folder for screenshots (outside the repo); none = no screenshots")
    ap.add_argument("--scale", type=float, default=None,
                    help="run one scale in this process (default: 1.0 and 1.5 as children)")
    ap.add_argument("--no-renders", action="store_true", help="pages and windows only")
    ap.add_argument("--json", type=Path, default=None,
                    help="with --scale: also write the steps as JSON (for tests)")
    args = ap.parse_args(argv)
    if args.shots is not None and not shots_allowed(args.shots):
        print(f"--shots must be outside the repo ({ROOT}; pytest temp folders excepted)",
              file=sys.stderr)
        return 2
    if args.scale is None:
        code = 0
        for i, scale in enumerate(SCALES):
            cmd = [sys.executable, __file__, "--scale", str(scale)]
            if args.shots is not None:
                cmd += ["--shots", str(args.shots)]
            if args.no_renders or i > 0:  # renders once; the 150 % pass only photographs
                cmd.append("--no-renders")
            code = max(code, subprocess.call(cmd))
        return code
    tag = f"{round(args.scale * 100):d}"
    t = time.perf_counter()
    shots = args.shots.resolve() if args.shots is not None else None
    json_out = args.json.resolve() if args.json is not None else None
    cwd = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="abeltongod-tour-") as home:
        try:
            emulate_screen(Path(home), args.scale)
            report = run_tour(Path(home), shots, tag, renders=not args.no_renders)
        finally:
            os.chdir(cwd)  # Windows cannot delete the working directory
    print(f"GUI tour at {tag} %: {len(report.steps)} steps, "
          f"{len(report.shots)} screenshots, {time.perf_counter() - t:.1f} s")
    print(format_report(report))
    if json_out is not None:
        import json

        json_out.write_text(json.dumps(
            {"steps": [asdict(s) for s in report.steps],
             "shots": [str(p) for p in report.shots]}, indent=1), encoding="utf-8")
    bad = report.unexpected
    if bad:
        print(f"{len(bad)} unexpected: " + ", ".join(s.name for s in bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "src"))
    sys.exit(main())
