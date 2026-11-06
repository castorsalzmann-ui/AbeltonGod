"""#439: shared settings and the library / Live hand-off of the Goa, Acid and Blaster windows.

Offscreen, the real window factories and engines (goa_arrangement, the acid preview, the laser
category). Nothing talks to Ableton Live: "An Live senden" only opens the main window's Live
page with the file chosen, which is what is checked here. #444: the Blaster's drag-out never
offers a file from its temporary folder."""

from __future__ import annotations

import os
import time
import wave
from pathlib import Path

import pytest

if os.environ.get("ABELTONGOD_REQUIRE_GUI") == "1":  # CI: a missing Qt must fail, not skip
    import PySide6.QtWidgets  # noqa: F401
else:
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.app import create_app  # noqa: E402
from gui.drag import PATH_ROLE  # noqa: E402
from gui.main_window import MainWindow  # noqa: E402
from gui.windows import ResultActions  # noqa: E402
from gui_core.library import read_entry  # noqa: E402
from gui_core.settings import SettingsStore, WindowState, load_settings  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return create_app([])


class FakeBackend:
    available = True

    def play(self, wav_path):
        pass

    def stop(self):
        pass


def wait_for(cond, seconds=30):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return cond()


@pytest.fixture
def main(qapp, tmp_path, monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ABELTONGOD_CLAUDE_AUTH"):
        monkeypatch.delenv(name, raising=False)
    w = MainWindow(out_dir=tmp_path / "out", backend=FakeBackend())
    w.show()
    QApplication.processEvents()
    return w


def selected_library_path(main) -> Path | None:
    item = main.library.list.currentItem()
    return Path(item.data(PATH_ROLE)) if item is not None else None


def library_paths(main) -> list[Path]:
    return [Path(main.library.list.item(i).data(PATH_ROLE))
            for i in range(main.library.list.count())]


# ---- one render per tool window lands in the main library ------------------------------------
def test_acid_wav_lands_in_the_library_and_is_shown_from_the_acid_window(main, tmp_path):
    acid = main.windows.open("acid")
    assert acid is not None, main.windows.last_error
    assert Path(acid.folder_edit.text()) == tmp_path / "out" / "Acid"
    main.categories.setCurrentRow(main.library_row)  # the library is open while Acid writes
    acid.seed_edit.setText("5")
    acid.generate()
    wav = acid.export_wav()
    run = tmp_path / "out" / "Acid" / "acid_5"  # one run folder per line (#468)
    assert wav is not None and wav.parent == run and wav.is_file()
    assert wav in library_paths(main)  # refreshed without a restart
    assert acid.actions.show_button.isEnabled()
    assert not acid.actions.live_button.isEnabled()  # no contract sidecar for acid lines
    assert "Sidecar" in acid.actions.note.text()
    main.categories.setCurrentRow(0)
    acid.actions.show_button.click()
    assert main.stack.currentWidget() is main.library
    assert selected_library_path(main) == wav
    again = acid.export_wav()  # never overwrites
    assert again is not None and again != wav and again.name.endswith("_2.wav")
    mid = acid.export_midi()
    assert mid is not None and mid.parent == wav.parent
    assert not acid.actions.show_button.isEnabled()  # a MIDI file is not in the library
    assert "nur WAV" in acid.actions.note.text()


def test_files_in_the_old_tool_folders_stay_and_are_still_listed(main, tmp_path):
    """#468: the new layout (Acid/<run>, Goa/<run>) moves nothing; WAVs in the older acid/ and
    goa/ folders stay where they are and the library still lists them."""
    old_acid = tmp_path / "out" / "acid" / "acid_1.wav"
    old_goa = tmp_path / "out" / "goa" / "goa_seed1_145bpm" / "samples" / "kick.wav"
    for p in (old_acid, old_goa):
        p.parent.mkdir(parents=True)
        p.write_bytes(b"RIFF")
    acid = main.windows.open("acid")
    acid.generate()
    new = acid.export_wav()
    assert new.parent.parent == tmp_path / "out" / "Acid"
    main.categories.setCurrentRow(main.library_row)
    listed = library_paths(main)
    assert {old_acid, old_goa, new} <= set(listed)
    assert old_acid.read_bytes() == b"RIFF" and old_goa.read_bytes() == b"RIFF"


def test_acid_wav_follows_the_shared_sample_rate_and_bit_depth(main):
    acid = main.windows.open("acid")
    main.hub.store.update(sample_rate=44100, bit_depth=16)
    acid.generate()
    wav = acid.export_wav()
    with wave.open(str(wav)) as w:
        assert (w.getframerate(), w.getsampwidth()) == (44100, 2)


def test_goa_window_render_lands_in_the_library(main, tmp_path):
    win = main.windows.open("goa")
    assert win is not None, main.windows.last_error
    panel = win.body
    assert Path(panel.folder_edit.text()).parent == tmp_path / "out" / "Goa"
    panel.forms[next(iter(panel.forms))].edits["seed"].setText("1")
    panel.refresh()
    panel.render_button.click()
    assert wait_for(lambda: panel.result is not None)
    assert panel.result.ok, panel.result.error
    samples = panel.result.sample_paths
    assert samples and panel.actions.path == samples[0]
    panel.actions.show_button.click()
    assert main.stack.currentWidget() is main.library
    assert selected_library_path(main) == samples[0]
    assert set(samples) <= set(library_paths(main))
    # The Live hand-off is offered exactly when the sample has a readable sidecar (none before
    # #414's fix, one after it): the row says why instead of failing late on the Live page.
    readable = read_entry(samples[0]).readable
    assert panel.actions.live_button.isEnabled() == readable
    assert (panel.actions.note.text() == "") == readable


def test_blaster_save_lands_in_the_library_and_goes_to_the_live_page(main, tmp_path):
    bl = main.windows.open("blaster")
    assert bl is not None, main.windows.last_error
    if bl.session.engine is None:
        pytest.fail(f"laser engine missing: {bl.session.unavailable_reason}")
    bl.pull_trigger()
    assert wait_for(lambda: bl.history.count() == 1)
    assert bl.save_to_library()
    assert wait_for(lambda: not bl._saving)
    wav = bl.actions.path
    assert wav is not None, bl.status.text()
    assert wav.parent == tmp_path / "out" / "Samples" / "FX" / "Lasers"
    entry = read_entry(wav)
    assert entry.readable and entry.category == "laser"
    assert bl.actions.live_button.isEnabled()
    bl.actions.show_button.click()
    assert selected_library_path(main) == wav
    bl.actions.live_button.click()
    assert main.stack.currentWidget().widget() is main.live
    assert main.live.wav_path == str(wav)
    assert main.live.plan is None and not main.live.import_button.isEnabled()  # nothing sent


def test_blaster_bank_uses_the_project_folder_as_start_and_the_shared_format(main, tmp_path):
    asked = []
    bl = main.windows.open("blaster")
    main.hub.store.update(project_dir=str(tmp_path / "proj"), bit_depth=16)
    bl.ask_dir = lambda parent, start: asked.append(start) or (tmp_path / "out")
    bl.bank_count.setValue(2)
    bl.export_bank_dialog()
    assert wait_for(lambda: bl.actions.path is not None)
    assert asked == [tmp_path / "proj"]
    with wave.open(str(bl.actions.path)) as w:
        assert w.getsampwidth() == 2
    main.categories.setCurrentRow(main.library_row)
    assert bl.actions.path in library_paths(main)


# ---- #444: drag-out never offers the temporary folder -----------------------------------------
def offered(bl, rows) -> list[Path]:
    mime = bl.history.mimeData([bl.history.item(r) for r in rows])
    return [Path(u.toLocalFile()) for u in mime.urls()]


def under(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
    except ValueError:
        return False
    return True


def test_blaster_drag_never_offers_a_file_from_the_temporary_folder(main, tmp_path):
    bl = main.windows.open("blaster")
    for n in range(1, 4):
        bl.pull_trigger()
        assert wait_for(lambda n=n: bl.history.count() == n)
    paths = offered(bl, range(3))
    assert len(paths) == 3
    work = Path(bl.session.work_dir)
    assert all(not under(p, work) for p in paths), paths
    assert all(under(p, tmp_path / "out") and p.with_suffix(".json").is_file() for p in paths)
    for p in paths:  # the real laser writer: the stereo 24-bit shot
        with wave.open(str(p)) as w:
            assert (w.getnchannels(), w.getsampwidth()) == (2, 3) and w.getnframes() > 0
    bl.close()  # deletes the temporary folder: the offered files stay
    assert not work.exists() and all(p.is_file() for p in paths)


def test_blaster_drag_of_an_unknown_temp_file_offers_nothing(main):
    bl = main.windows.open("blaster")
    stray = Path(bl.session.work_dir) / "stray.wav"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_bytes(b"RIFF")
    assert bl.offer_for_drag(stray) is None


def test_blaster_drag_that_cannot_write_offers_nothing_and_says_why(main, tmp_path):
    bl = main.windows.open("blaster")
    bl.pull_trigger()
    assert wait_for(lambda: bl.history.count() == 1)
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    bl.library_dir = blocker / "Lasers"  # a folder below a file cannot be made
    assert offered(bl, [0]) == []
    assert "Ziehen nicht möglich" in bl.status.text()


# ---- hand-off widgets ---------------------------------------------------------------------------
def test_result_actions_without_the_main_window_are_off_and_say_why(qapp, tmp_path):
    a = ResultActions()
    wav = tmp_path / "x.wav"
    wav.write_bytes(b"RIFF")
    a.set_paths([wav])
    assert not a.show_button.isEnabled() and not a.live_button.isEnabled()
    assert "Hauptfenster" in a.show_button.toolTip()
    assert "Hauptfenster" in a.live_button.toolTip()


def test_show_in_library_clears_a_filter_that_hides_the_file(main):
    acid = main.windows.open("acid")
    acid.generate()
    wav = acid.export_wav()
    main.categories.setCurrentRow(main.library_row)
    main.library.search.setText("gibtsnicht")
    assert main.show_in_library(wav)
    assert selected_library_path(main) == wav and main.library.search.text() == ""


def test_show_in_library_outside_the_output_folder_says_so(main, tmp_path):
    other = tmp_path / "elsewhere.wav"
    other.write_bytes(b"RIFF")
    assert main.show_in_library(other) is False
    assert "nicht im Ausgabeordner" in main.library.info.text()


# ---- settings survive a restart ------------------------------------------------------------------
def test_settings_and_window_places_survive_a_restart(qapp, tmp_path):
    cfg = tmp_path / "cfg" / "settings.json"
    w = MainWindow(backend=FakeBackend(), settings_store=SettingsStore(path=cfg))
    w.show()
    dlg = w.open_settings()
    dlg.output_edit.setText(str(tmp_path / "out2"))
    dlg.project_edit.setText(str(tmp_path / "proj"))
    dlg.rate_box.setCurrentIndex(dlg.rate_box.findData(44100))
    dlg.bits_box.setCurrentIndex(dlg.bits_box.findData(16))
    dlg.accept()
    assert w.folder_edit.text() == str(tmp_path / "out2")
    assert w.goa.base_dir == tmp_path / "out2" / "Goa"
    req = w.models["kick"].build_request()
    assert (req["sample_rate"], req["bit_depth"]) == (44100, 16)
    acid = w.windows.open("acid")
    assert Path(acid.folder_edit.text()) == tmp_path / "out2" / "Acid"
    acid.setGeometry(40, 50, 900, 640)
    w.setGeometry(20, 30, 1000, 700)
    acid_geo = acid.geometry()
    main_geo = w.geometry()
    w.close()
    QApplication.processEvents()

    saved = load_settings(cfg)
    assert saved.output_dir == str(tmp_path / "out2") and saved.project_dir == str(tmp_path /
                                                                                 "proj")
    assert (saved.sample_rate, saved.bit_depth) == (44100, 16)
    assert saved.windows["acid"] == WindowState(acid_geo.x(), acid_geo.y(), acid_geo.width(),
                                                acid_geo.height())
    assert saved.windows["main"].width == main_geo.width()

    w2 = MainWindow(backend=FakeBackend(), settings_store=SettingsStore(path=cfg))
    w2.show()
    assert w2.folder_edit.text() == str(tmp_path / "out2")
    req = w2.models["bass"].build_request()
    assert (req["sample_rate"], req["bit_depth"]) == (44100, 16)
    assert (w2.geometry().width(), w2.geometry().height()) == (main_geo.width(),
                                                               main_geo.height())
    acid2 = w2.windows.open("acid")
    assert (acid2.geometry().width(), acid2.geometry().height()) == (acid_geo.width(),
                                                                     acid_geo.height())
    w2.close()


def test_main_folder_edit_is_the_shared_output_folder(main, tmp_path):
    main.folder_edit.setText(str(tmp_path / "moved"))
    main.folder_edit.editingFinished.emit()
    assert main.hub.settings.output_root() == tmp_path / "moved"
    acid = main.windows.open("acid")
    assert Path(acid.folder_edit.text()) == tmp_path / "moved" / "Acid"
    main.hub.store.update(output_dir=str(tmp_path / "again"))
    assert Path(acid.folder_edit.text()) == tmp_path / "again" / "Acid"  # followed: not typed
    acid.folder_edit.setText(str(tmp_path / "mine"))
    main.hub.store.update(output_dir=str(tmp_path / "third"))
    assert Path(acid.folder_edit.text()) == tmp_path / "mine"  # typed by the user: kept


# ---- format: back to the contract default, and other settings never touch the forms ----------
def fresh_requests() -> dict[str, dict]:
    from gui_core.form import CategoryFormModel

    return {k: CategoryFormModel(k).build_request() for k in ("kick", "bass", "laser")}


def test_contract_default_after_a_value_resets_forms_blaster_and_acid(main):
    fresh = fresh_requests()
    acid = main.windows.open("acid")
    bl = main.windows.open("blaster")
    main.hub.store.update(sample_rate=44100, bit_depth=16)
    assert main.models["kick"].build_request()["sample_rate"] == 44100
    assert (acid.sample_rate, acid.bit_depth) == (44100, 16)
    assert bl.format_overrides == {"sample_rate": 44100, "bit_depth": 16}
    main.hub.store.update(sample_rate=None, bit_depth=None)  # "Vertragsstandard"
    for key, req in fresh.items():  # byte-identical to a fresh form again
        assert main.models[key].build_request() == req, key
    assert (acid.sample_rate, acid.bit_depth) == (48000, 24)
    assert bl.format_overrides == {}


def test_a_folder_change_keeps_a_sample_rate_typed_into_a_form(main, tmp_path):
    main.hub.store.update(sample_rate=44100)
    model = main.models["kick"]
    model.set_text("sample_rate", "48000")  # the user changes the form by hand
    main.folder_edit.setText(str(tmp_path / "elsewhere"))
    main.folder_edit.editingFinished.emit()
    main.hub.store.update(project_dir=str(tmp_path / "p"))
    assert model.build_request()["sample_rate"] == 48000
    main.hub.store.update(bit_depth=16)  # only the changed field is applied
    req = model.build_request()
    assert (req["sample_rate"], req["bit_depth"]) == (48000, 16)


# ---- a tool window's place is saved when the user closes it ------------------------------------
def test_closing_a_tool_window_saves_its_place(qapp, tmp_path):
    cfg = tmp_path / "cfg" / "settings.json"
    w = MainWindow(out_dir=tmp_path / "out", backend=FakeBackend(),
                   settings_store=SettingsStore(path=cfg))
    w.show()
    acid = w.windows.open("acid")
    acid.setGeometry(60, 70, 880, 620)
    geo = acid.geometry()
    acid.close()  # the user closes Acid; the main window stays open
    QApplication.processEvents()
    assert load_settings(cfg).windows["acid"] == WindowState(geo.x(), geo.y(), geo.width(),
                                                             geo.height())
    again = w.windows.open("acid")  # reopened in the same session: same place
    assert (again.geometry().width(), again.geometry().height()) == (geo.width(), geo.height())
    w.close()


# ---- one project folder: Live page "Live-Projekt" == settings project_dir --------------------
def test_live_project_field_edits_the_shared_project_folder(main, tmp_path):
    proj = tmp_path / "Test Project"
    main.live.project_edit.setText(str(proj))
    main.live.project_edit.editingFinished.emit()
    assert main.hub.settings.project_dir == str(proj)
    assert main.hub.settings.bank_start_dir() == proj  # the Blaster's bank start folder
    dlg = main.open_settings()
    assert dlg.project_edit.text() == str(proj)
    dlg.reject()


def test_settings_project_folder_shows_on_the_live_page(main, tmp_path):
    dlg = main.open_settings()
    dlg.project_edit.setText(str(tmp_path / "P2"))
    dlg.accept()
    assert main.live.project_edit.text() == str(tmp_path / "P2")
    assert main.live.project_dir == str(tmp_path / "P2")
    bl = main.windows.open("blaster")
    assert bl.bank_start_dir == tmp_path / "P2"
    main.hub.store.update(project_dir="")
    assert main.live.project_edit.text() == "" and main.live.project_dir is None


def test_live_project_survives_a_restart(qapp, tmp_path):
    cfg = tmp_path / "cfg" / "settings.json"
    w = MainWindow(out_dir=tmp_path / "out", backend=FakeBackend(),
                   settings_store=SettingsStore(path=cfg))
    w.live.project_edit.setText(str(tmp_path / "LiveSet Project"))
    w.live.project_edit.editingFinished.emit()
    w.close()
    QApplication.processEvents()
    w2 = MainWindow(out_dir=tmp_path / "out", backend=FakeBackend(),
                    settings_store=SettingsStore(path=cfg))
    assert w2.live.project_edit.text() == str(tmp_path / "LiveSet Project")
    assert load_settings(cfg).project_dir == str(tmp_path / "LiveSet Project")
    w2.close()
