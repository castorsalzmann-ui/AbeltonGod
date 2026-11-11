"""GUI-2: navigation, Goa page, Live import page (fake OSC only) and chat page (fake model).

Offscreen. Nothing here talks to Ableton Live or Claude; the Live page is exercised against the
fake AbletonOSC server of tests/bridge and is not a Live test."""

from __future__ import annotations

import hashlib
import os
import sys
import time
from pathlib import Path

import pytest

if os.environ.get("ABELTONGOD_REQUIRE_GUI") == "1":  # CI: a missing Qt must fail, not skip
    import PySide6.QtWidgets  # noqa: F401
else:
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gui_core"))
from live_helpers import (  # noqa: E402
    config_for,
    make_fake,
    registry_with_status,
    write_wav,
    writes,
)
from PySide6.QtWidgets import QLabel, QPushButton  # noqa: E402

from audio_engine import goa_clips  # noqa: E402
from guard import Guard  # noqa: E402
from gui.app import create_app  # noqa: E402
from gui.main_window import MainWindow  # noqa: E402
from gui.widgets import NumberControl, PresetChips, Segmented, StepEdit, Toggle  # noqa: E402
from gui_core import goa_preview  # noqa: E402
from gui_core.chat import ChatSession  # noqa: E402
from orchestrator.fake_model import FakeModel  # noqa: E402

# `python -m audio_engine.goa_clips --out X --seed 3` (pinned literals, as in gui_core tests)
SEED3_CLIPS = {
    "goa_lead_seed3_145bpm_4bars.mid":
        "ee87c842b62762720d81a922107e8642bf21f87141ea26983497d3b967519b10",
    "goa_arp_seed3_145bpm_4bars.mid":
        "43ab8393f7248721d852c144d8b367708aa61b04428ec5b3c7ce21c53bb7c437",
    "goa_pad_seed3_145bpm_4bars.mid":
        "0a42ff5925093e8239c0eb4688dcee564af915643593ee861ef4100ea6799a78",
    "goa_pluck_seed3_145bpm_4bars.mid":
        "80a9a87587172e555f45823a1b4b48c24fbfbb8d02e22e2401862119886c84b5",
}
SEED3_README = "e16de7e93e3f8099fc47ea35cf62e82294b448ee9402a679c5f6eba6d9cb3f73"


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def qapp():
    return create_app([])


class FakeBackend:
    available = True

    def play(self, wav_path):
        pass

    def stop(self):
        pass


def wait_for(qapp, cond, seconds=30):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def opened():
    return []


@pytest.fixture
def window(qapp, tmp_path, opened, monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ABELTONGOD_CLAUDE_AUTH"):
        monkeypatch.delenv(name, raising=False)
    model = FakeModel([{"text": "Plan: erst Kick, dann Bass."}])
    session = ChatSession(tmp_path / ".env", model=model,
                          guard=Guard(log_path=tmp_path / "usage.jsonl"))
    w = MainWindow(out_dir=tmp_path / "out", backend=FakeBackend(),
                   opener=lambda p: opened.append(p) or True, chat_session=session)
    w.show()
    w.fake_model = model
    yield w
    w.close()


def go(window, key):
    window.categories.setCurrentRow(window.tool_rows[key])


# --- navigation -----------------------------------------------------------------------------

def test_tool_pages_replace_the_render_column_and_the_kick_page_brings_it_back(window):
    assert window.right.isVisibleTo(window)
    for key, page in (("goa", window.goa), ("live", window.live), ("chat", window.chat)):
        go(window, key)
        box = window.stack.currentWidget()  # each tool page sits in its scroll area (#442)
        assert box is window.tool_scrolls[key] and box.widget() is page and window.on_tool
        assert not window.right.isVisibleTo(window)
        assert not window.render_button.isEnabled()
    window.categories.setCurrentRow(0)
    assert window.right.isVisibleTo(window) and not window.on_tool
    assert window.stack.currentWidget() is window.panel and window.render_button.isEnabled()


# --- Goa page -------------------------------------------------------------------------------

def test_goa_page_makes_clips_without_song_form(window):
    """D-035 (1): the page "Goa-Melodie" makes MIDI clips: no timeline, no section table, no
    energy, no song length, no arrangement / drum / bass option anywhere on it."""
    go(window, "goa")
    p = window.goa
    assert window.categories.currentItem().text() == "Goa-Melodie"
    assert not hasattr(p, "mode_seg") and not hasattr(p, "forms")
    assert not hasattr(p, "timeline")
    assert not (ROOT / "src" / "gui" / "timeline_widget.py").exists()
    labels = {w.text() for w in p.findChildren(QLabel)} | {
        b.text() for b in p.findChildren(QPushButton)}
    headers = {p.table.horizontalHeaderItem(c).text() for c in range(p.table.columnCount())}
    for word in ("Arrangement (ganzer Track)", "Kick-Preset", "Bass-Preset", "Bass-Rhythmus",
                 "Keine Samples rendern", "DJ-Intro/Outro", "Abschnitt", "Energie",
                 "Minuten", "Phrasenlänge", "Rendern"):
        assert not any(word in t for t in labels | headers), word
    assert headers == {"Stimme", "Noten", "Datei"}
    assert p.form.model.spec("voices").choices == ("lead", "arp", "pad", "pluck")
    assert {b.text() for b in p.findChildren(QPushButton)} >= {
        "Lead", "Arp", "Pad", "Pluck", "Alle vorhören", "Stopp", "MIDI exportieren"}


def test_goa_form_has_a_widget_for_every_cli_option(window):
    form = window.goa.form
    dests = {a.dest for a in goa_clips.build_parser()._actions if a.dest not in ("help", "out")}
    assert set(form.edits) == dests
    for dest in dests:
        assert form.edits[dest].accessibleName() or isinstance(form.edits[dest], NumberControl)
    # optional options have a switch, the others do not
    assert set(form.checks) == {s.dest for s in form.model.specs if s.optional}


def type_text(edit, text):
    edit.setText(text)
    edit.edited.emit(text) if isinstance(edit, StepEdit) else edit.textEdited.emit(text)


def test_goa_invalid_value_blocks_export_and_preview_with_the_modules_message(qapp, window):
    go(window, "goa")
    p = window.goa
    form = p.form
    assert p.export_button.isEnabled() and p.all_button.isEnabled()
    edit = form.edits["seed"]
    assert isinstance(edit, StepEdit)
    type_text(edit, "abc")
    assert edit.property("invalid") is True and not p.export_button.isEnabled()
    assert not p.all_button.isEnabled()
    assert not any(b.isEnabled() for b in p.voice_buttons.values())
    assert "Export nicht möglich" in p.status.text()
    assert p.table.rowCount() == 0
    type_text(edit, "0")
    assert edit.property("invalid") is False and p.export_button.isEnabled()
    assert p.table.rowCount() == 4
    type_text(form.edits["bars"], "17")  # the generator's range is 1 to 16 bars
    assert not p.export_button.isEnabled() and "bars must be" in p.status.text()


def test_goa_tempo_slider_gives_whole_bpm_in_the_generators_range(qapp, window):
    go(window, "goa")
    p = window.goa
    bpm = p.form.edits["bpm"]
    assert isinstance(bpm, NumberControl)
    bpm.readout.setText("200")
    bpm.readout.entered.emit("200")  # generator range is 135 to 150 BPM
    assert p.model.text["bpm"] == "150" and p.export_button.isEnabled()
    bpm.slider.move_to_position(0)
    assert p.model.text["bpm"] == "135" and p.table.rowCount() == 4
    bpm.readout.setText("141.6")
    bpm.readout.entered.emit("141.6")
    assert p.model.text["bpm"] in ("141", "142") and p.export_button.isEnabled()


def test_goa_clip_table_follows_the_form(window):
    go(window, "goa")
    p = window.goa
    rows = [[p.table.item(r, c).text() for c in range(3)] for r in range(p.table.rowCount())]
    assert rows == [["Lead", "26", "goa_lead_seed0_145bpm_4bars.mid"],
                    ["Arp", "64", "goa_arp_seed0_145bpm_4bars.mid"],
                    ["Pad", "2", "goa_pad_seed0_145bpm_4bars.mid"],
                    ["Pluck", "56", "goa_pluck_seed0_145bpm_4bars.mid"]]
    assert "Je Clip 4 Takte" in p.summary.text() and "0, 0, 0, 0." in p.summary.text()
    type_text(p.form.edits["bars"], "8")
    assert "Je Clip 8 Takte" in p.summary.text() and "0, 0, 0, 0, 0, 0, 0, 0." in p.summary.text()
    assert p.table.item(0, 2).text() == "goa_lead_seed0_145bpm_8bars.mid"
    chips = p.form.edits["voices"]
    chips.buttons[chips.items.index("pad")].click()
    assert p.form.model.text["voices"] == "lead,arp,pluck"
    assert [p.table.item(r, 0).text() for r in range(p.table.rowCount())] == [
        "Lead", "Arp", "Pluck"]
    assert not p.voice_buttons["pad"].isEnabled() and p.voice_buttons["lead"].isEnabled()


def test_goa_preview_plays_the_rough_preview_per_voice_and_for_all(window, tmp_path):
    go(window, "goa")
    p = window.goa
    played: list[tuple[str, bytes]] = []

    class Recorder(FakeBackend):
        def play(self, wav_path):
            played.append(("play", Path(wav_path).read_bytes()))

        def stop(self):
            played.append(("stop", b""))

    p.backend = Recorder()
    out = Path(p.folder_edit.text())
    p.voice_buttons["arp"].click()
    assert played[-1][0] == "play" and p.playing == "arp"
    assert played[-1][1] == goa_preview.voice_preview_wav_bytes("arp", seed=0)
    assert "Spielt: Arp" in p.status.text() and "grobe Vorschau" in p.status.text()
    p.all_button.click()
    assert played[-2] == ("stop", b"")  # the previous sound stops first
    assert played[-1][1] == goa_preview.mix_preview_wav_bytes(seed=0)
    p.stop_button.click()
    assert played[-1] == ("stop", b"") and p.playing is None
    assert not out.exists()  # previewing writes nothing into the output folder
    p.backend = FakeBackend()
    p.backend.available = False
    p.voice_buttons["lead"].click()
    assert "Keine Audioausgabe" in p.status.text()


def test_goa_export_writes_the_shown_folder_and_offers_each_clip_for_drag(
        qapp, window, opened):
    go(window, "goa")
    p = window.goa
    form = p.form
    type_text(form.edits["seed"], "3")
    folder = Path(p.folder_edit.text())
    assert folder.name == "goa_clips_seed3_145bpm_4bars" and not folder.exists()
    p.export_button.click()
    assert wait_for(qapp, lambda: p.result is not None)
    assert p.result.ok, p.result.error
    assert p.result.out_dir == folder  # the folder shown before the export is the one written
    names = sorted(x.name for x in folder.iterdir())
    assert names == sorted([*SEED3_CLIPS, "README.md"])  # no samples, nothing else
    for name, digest in SEED3_CLIPS.items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest, name
    assert hashlib.sha256((folder / "README.md").read_bytes()).hexdigest() == SEED3_README
    assert p.readme.toPlainText() == (folder / "README.md").read_text(encoding="utf-8")
    assert "Fertig: 4 MIDI-Clips" in p.status.text() and not p.running
    # drag: one row per clip, offered as a file URL (mime level only; no drop into Live)
    items = [p.drag_list.item(i) for i in range(p.drag_list.count())]
    assert [i.text() for i in items] == [
        "goa_lead_seed3_145bpm_4bars.mid", "goa_arp_seed3_145bpm_4bars.mid",
        "goa_pad_seed3_145bpm_4bars.mid", "goa_pluck_seed3_145bpm_4bars.mid"]
    urls = p.drag_list.mimeData(items[1:2]).urls()
    assert [Path(u.toLocalFile()) for u in urls] == [folder / "goa_arp_seed3_145bpm_4bars.mid"]
    # never the same folder again
    assert Path(p.folder_edit.text()).name == "goa_clips_seed3_145bpm_4bars_2"
    p.open_button.click()
    assert opened == [folder]  # the folder of the finished run


def test_goa_existing_folder_is_an_error_and_nothing_is_overwritten(qapp, window):
    go(window, "goa")
    p = window.goa
    target = p.base_dir / "mine"
    target.mkdir(parents=True)
    (target / "README.md").write_text("alt", encoding="utf-8")
    p.folder_edit.setText(str(target))
    p.folder_edit.textEdited.emit(str(target))
    p.export_button.click()
    assert wait_for(qapp, lambda: p.result is not None)
    assert p.result.error.kind == "exists"
    assert "Fehler" in p.status.text() and "nichts überschrieben" in p.status.text()
    assert sorted(x.name for x in target.iterdir()) == ["README.md"]
    assert (target / "README.md").read_text(encoding="utf-8") == "alt"
    assert p.drag_list.count() == 0


def test_goa_optional_switch_activates_the_field(window):
    go(window, "goa")
    form = window.goa.form
    edit = form.edits["density"]
    assert not edit.isEnabled() and "density" not in form.model.active
    form.checks["density"].setChecked(True)
    assert edit.isEnabled() and "density" in form.model.active
    assert not window.goa.export_button.isEnabled()  # active but empty
    type_text(edit, "lead=0.5")
    assert window.goa.export_button.isEnabled()


# --- Live page (fake OSC only) --------------------------------------------------------------

@pytest.fixture
def live_setup(qapp, window, tmp_path):
    fake = make_fake()
    window.live.config = config_for(fake, tmp_path)
    wav_dir = tmp_path / "out"
    wav_dir.mkdir(exist_ok=True)
    wav = write_wav(wav_dir / "mine.wav")
    window.live.reload_library()
    window.live.add_wav(Path(wav))
    go(window, "live")
    yield window.live, fake, wav
    fake.close()


def test_live_page_flow_inspect_plan_confirm_import(qapp, live_setup):
    page, fake, wav = live_setup
    assert not page.plan_button.isEnabled() and not page.import_button.isEnabled()
    assert page.inspect_button.isEnabled() and not page.unverified_check.isVisibleTo(page)
    assert "'tested'" in page.gate_label.text()
    page.inspect_button.click()
    assert wait_for(qapp, lambda: page.inspection is not None)
    assert page.inspection.ok, page.inspection.error
    labels = [page.track_box.itemText(i) for i in range(page.track_box.count())]
    assert labels == ["Neue Audiospur am Ende", "1: 1-Audio", "2: 2-MIDI  (keine Audiospur)",
                      "3: 3-Audio"]
    assert not page.track_box.model().item(2).isEnabled()
    assert writes(fake) == []
    page.track_box.setCurrentIndex(3)  # "3: 3-Audio"
    page.slot_spin.setValue(2)  # scene 2 -> slot index 1
    assert page.plan is None and page.plan_button.isEnabled()
    page.plan_button.click()
    assert wait_for(qapp, lambda: page.plan is not None)
    assert "Spur 3 '3-Audio', Szene 2" in page.plan_text.toPlainText()
    assert not page.import_button.isEnabled()  # test-set not confirmed yet
    assert writes(fake) == []
    page.testset_check.setChecked(True)
    assert page.import_button.isEnabled()
    page.import_button.click()
    assert wait_for(qapp, lambda: page.plan is None and not page.busy)
    assert writes(fake) == [("/live/clip_slot/create_audio_clip", (2, 1, wav))]
    assert "Fertig" in page.status.text() and "angehört wurde nichts" in page.status.text()
    log = page.log_view.toPlainText()
    assert "create_audio_clip" in log and "Aktions-Log" in log
    assert not page.import_button.isEnabled()  # a new plan is needed for the next import
    assert not page.testset_check.isChecked()  # and the test-set confirmation is asked again


def test_live_page_changing_an_input_discards_the_plan(qapp, live_setup):
    page, fake, _wav = live_setup
    page.inspect_button.click()
    assert wait_for(qapp, lambda: page.inspection is not None)
    page.track_box.setCurrentIndex(1)
    page.plan_button.click()
    assert wait_for(qapp, lambda: page.plan is not None)
    page.testset_check.setChecked(True)
    assert page.import_button.isEnabled()
    page.slot_spin.setValue(4)
    assert page.plan is None and not page.import_button.isEnabled()
    assert page.plan_text.toPlainText() == ""
    assert writes(fake) == []


def test_live_page_shows_errors_from_the_service(qapp, live_setup):
    page, fake, _wav = live_setup
    fake.extension_installed = False
    page.inspect_button.click()
    assert wait_for(qapp, lambda: page.inspection is not None)
    assert not page.inspection.ok and "Erweiterung fehlt" in page.status.text()
    assert not page.plan_button.isEnabled()


def test_live_page_unverified_capability_needs_its_own_confirmation(qapp, window, tmp_path):
    fake = make_fake()
    try:
        reg = registry_with_status(tmp_path, {"clip_slot.create_audio_clip": "supported"})
        window.live._registry = reg
        window.live.config = config_for(fake, tmp_path)
        window.live._show_gate()
        wav = write_wav(tmp_path / "w.wav")
        window.live.add_wav(Path(wav))
        go(window, "live")
        page = window.live
        assert page.unverified_check.isVisibleTo(page)
        assert "NICHT VERIFIZIERT" in page.gate_label.text()
        page.inspect_button.click()
        assert wait_for(qapp, lambda: page.inspection is not None)
        assert not page.inspection.ok and "NICHT VERIFIZIERT" in page.status.text()
        assert fake.payload() == []  # refused before any message went out
        page.unverified_check.setChecked(True)
        page.inspection = None
        page.inspect_button.click()
        assert wait_for(qapp, lambda: page.inspection is not None)
        assert page.inspection.ok
        page.track_box.setCurrentIndex(1)
        page.plan_button.click()
        assert wait_for(qapp, lambda: page.plan is not None)
        page.testset_check.setChecked(True)
        assert page.import_button.isEnabled()
        page.unverified_check.setChecked(False)  # withdrawing the confirmation discards the plan
        assert not page.import_button.isEnabled() and writes(fake) == []
    finally:
        fake.close()


def test_live_page_copies_a_render_from_the_output_folder_into_the_project(qapp, live_setup,
                                                                          tmp_path):
    """#413: a GUI render outside a project is copied into <project>/Samples/... and the copy
    is imported (fake OSC only)."""
    from gui_core.form import CategoryFormModel
    from gui_core.render import RenderJob, run_job
    page, fake, _wav = live_setup
    m = CategoryFormModel("kick")
    r = run_job(RenderJob(m.build_request(), tmp_path / "renders", m.preset, m.overrides(),
                          "kick"))
    assert r.ok, r.error
    src = r.files[0].wav_path
    page.add_wav(src)
    page.refused_roots = ()  # pytest's temp folder lies inside the checkout
    page.inspect_button.click()
    assert wait_for(qapp, lambda: page.inspection is not None)
    # #443: the render sits in the project-shaped output tree: importable in place
    assert page.inspection.ok and not page.inspection.placement.moved, page.status.text()
    assert "kopiert" not in page.status.text()
    proj = tmp_path / "Set Project"
    proj.mkdir()
    (proj / "Set.als").write_bytes(b"")
    page.project_edit.setText(str(proj))
    page.inspection = None
    page.inspect_button.click()
    assert wait_for(qapp, lambda: page.inspection is not None)
    assert page.inspection.ok, page.inspection.error
    target = proj / "Samples" / "Drums" / "Kicks" / src.name
    assert str(target) in page.status.text() and not target.exists()
    page.plan_button.click()
    assert wait_for(qapp, lambda: page.plan is not None)
    assert "kopieren" in page.plan_text.toPlainText()
    page.testset_check.setChecked(True)
    page.import_button.click()
    assert wait_for(qapp, lambda: page.plan is None and not page.busy)
    assert "Fertig" in page.status.text(), page.status.text()
    assert target.read_bytes() == src.read_bytes()
    assert writes(fake)[-1] == ("/live/clip_slot/create_audio_clip", (3, 0, str(target)))


# --- chat page ------------------------------------------------------------------------------

def test_chat_page_sends_in_a_thread_and_shows_the_reply(qapp, window):
    go(window, "chat")
    c = window.chat
    assert c.ready and "Testmodell" in c.access.text()
    assert not c.send_button.isEnabled()
    c.input.setText("Wie fange ich an?")
    assert c.send_button.isEnabled()
    c.send_button.click()
    assert c.busy and not c.input.isEnabled()
    assert wait_for(qapp, lambda: not c.busy)
    text = c.transcript.toPlainText()
    # the guard's own warning (fake turn reports no cost) is shown with the reply
    assert "Du: Wie fange ich an?" in text and "Plan: erst Kick, dann Bass." in text
    assert "max_budget_usd" in text
    assert c.input.isEnabled() and len(window.fake_model.requests) == 1


def test_chat_page_without_key_says_so_and_cannot_send(qapp, tmp_path, monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ABELTONGOD_CLAUDE_AUTH"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text("ABELTONGOD_CLAUDE_AUTH=api_key\n", encoding="utf-8")
    w = MainWindow(out_dir=tmp_path / "o", backend=FakeBackend(), opener=lambda p: True,
                   chat_session=ChatSession(tmp_path / ".env"))
    try:
        w.show()
        go(w, "chat")
        assert not w.chat.ready and "Kein API-Schlüssel gefunden" in w.chat.access.text()
        w.chat.input.setText("Hallo")
        assert not w.chat.input.isEnabled() and not w.chat.send_button.isEnabled()
        w.chat.send()  # called directly: still nothing happens
        assert w.chat.transcript.toPlainText() == ""
    finally:
        w.close()


def test_every_goa_switch_and_button_row_reflects_the_model(window):
    go(window, "goa")
    form = window.goa.form
    for dest, edit in form.edits.items():
        spec = form.model.spec(dest)
        if isinstance(edit, Segmented):
            if dest in form.model.active:  # a switched-off optional shows its first choice
                assert edit.items[edit.index()] == form.model.text[dest]
        elif isinstance(edit, PresetChips) and not edit.multi:
            if dest in form.model.active:
                assert edit.current() == form.model.text[dest]
        elif isinstance(edit, Toggle):
            assert edit.isChecked() == (form.model.text[dest] == "ja")
        assert edit.isEnabled() == (dest in form.model.active), (dest, spec.kind)
