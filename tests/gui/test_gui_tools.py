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
from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit  # noqa: E402

from audio_engine import goa_arrangement, goa_melody  # noqa: E402
from guard import Guard  # noqa: E402
from gui.app import create_app  # noqa: E402
from gui.main_window import MainWindow  # noqa: E402
from gui_core import goa  # noqa: E402
from gui_core.chat import ChatSession  # noqa: E402
from orchestrator.fake_model import FakeModel  # noqa: E402

SEED1_MID = "ed6118d21ad392474c0422b4d12ed8f2fa4ca585c47918673b5f149a1dc9fb79"
SEED1_README = "376510c4af42786c49ee957589d4905a7bb1ed01cc15eebcb1c43095d909974e"


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
        assert window.stack.currentWidget() is page and window.on_tool
        assert not window.right.isVisibleTo(window)
        assert not window.render_button.isEnabled()
    window.categories.setCurrentRow(0)
    assert window.right.isVisibleTo(window) and not window.on_tool
    assert window.stack.currentWidget() is window.panel and window.render_button.isEnabled()


# --- Goa page -------------------------------------------------------------------------------

@pytest.mark.parametrize("mode,module", [(goa.ARRANGEMENT, goa_arrangement),
                                         (goa.MELODY, goa_melody)])
def test_goa_form_has_a_widget_for_every_cli_option(window, mode, module):
    form = window.goa.forms[mode]
    dests = {a.dest for a in module.build_parser()._actions if a.dest not in ("help", "out")}
    assert set(form.edits) == dests
    for dest in dests:
        assert form.edits[dest].accessibleName() or dest in form.voice_boxes
    # optional options have a switch, the others do not
    assert set(form.checks) == {s.dest for s in form.model.specs if s.optional}


def set_enum(form, dest, text):
    box = form.edits[dest]
    assert isinstance(box, QComboBox)
    box.setCurrentText(text)


def test_goa_invalid_value_blocks_render_with_the_modules_message(qapp, window):
    go(window, "goa")
    p = window.goa
    form = p.forms[goa.ARRANGEMENT]
    assert p.render_button.isEnabled()
    edit = form.edits["bpm"]
    assert isinstance(edit, QLineEdit)
    edit.setText("200")
    edit.textEdited.emit("200")
    assert not p.render_button.isEnabled()
    assert "Rendern nicht möglich" in p.status.text() and "bpm must be" in p.status.text()
    assert p.table.rowCount() == 0 and p.timeline.plan is None
    edit.setText("145")
    edit.textEdited.emit("145")
    assert p.render_button.isEnabled() and p.table.rowCount() == 19
    edit.setText("abc")
    edit.textEdited.emit("abc")
    assert edit.property("invalid") is True and not p.render_button.isEnabled()


def test_goa_preview_shows_the_generators_plan(window):
    go(window, "goa")
    p = window.goa
    assert p.table.rowCount() == 19
    row0 = [p.table.item(0, c).text() for c in range(5)]
    assert row0 == ["1", "8", "Intro", "0.30", "kick, bass"]
    row_b1 = [p.table.item(7, c).text() for c in range(5)]
    assert row_b1 == ["73", "16", "Break 1", "0.30", "arp, pad"]
    assert "224 Takte" in p.summary.text()
    spans = p.timeline.section_spans()
    total_w = spans[-1][2] - spans[0][1]
    assert len(spans) == 19
    for s, x0, x1 in spans:
        assert abs((x1 - x0) / total_w - s.bars / 224) < 1e-6
    mid = (spans[7][1] + spans[7][2]) / 2
    assert p.timeline.section_at(mid).name == "Break 1"
    # a change in the form changes the preview
    form = p.forms[goa.ARRANGEMENT]
    set_enum(form, "dj_bars", "16")
    assert p.table.rowCount() == 21 and p.table.item(0, 2).text() == "DJ Intro"
    assert "256 Takte" in p.summary.text()
    p.timeline.grab()  # paints without raising


def test_goa_render_writes_the_cli_folder_and_shows_the_readme(qapp, window, opened):
    go(window, "goa")
    p = window.goa
    form = p.forms[goa.ARRANGEMENT]
    form.edits["seed"].setText("1")
    form.edits["seed"].textEdited.emit("1")
    form.edits["no_samples"].setChecked(True)  # keeps the test short; samples: gui_core test
    folder = Path(p.folder_edit.text())
    assert folder.name == "goa_seed1_145bpm" and not folder.exists()
    p.render_button.click()
    assert wait_for(qapp, lambda: p.result is not None)
    assert p.result.ok, p.result.error
    mid = folder / "goa_seed1_145bpm.mid"
    assert hashlib.sha256(mid.read_bytes()).hexdigest() == SEED1_MID
    assert hashlib.sha256((folder / "README.md").read_bytes()).hexdigest() == SEED1_README
    assert p.readme.toPlainText() == (folder / "README.md").read_text(encoding="utf-8")
    assert "Fertig" in p.status.text() and not p.running
    assert Path(p.folder_edit.text()).name == "goa_seed1_145bpm_2"  # never the same folder again
    p.open_button.click()
    assert opened == [folder]  # the folder of the finished run


def test_goa_existing_folder_is_an_error_and_nothing_is_overwritten(qapp, window):
    go(window, "goa")
    p = window.goa
    form = p.forms[goa.ARRANGEMENT]
    form.edits["no_samples"].setChecked(True)
    target = p.base_dir / "mine"
    target.mkdir(parents=True)
    (target / "README.md").write_text("alt", encoding="utf-8")
    p.folder_edit.setText(str(target))
    p.folder_edit.textEdited.emit(str(target))
    p.render_button.click()
    assert wait_for(qapp, lambda: p.result is not None)
    assert p.result.error.kind == "exists"
    assert "Fehler" in p.status.text() and "nichts überschrieben" in p.status.text()
    assert (target / "README.md").read_text(encoding="utf-8") == "alt"


def test_goa_melody_mode_renders_the_melody_cli_output(qapp, window):
    go(window, "goa")
    p = window.goa
    p.mode_box.setCurrentIndex(1)
    assert p.mode == goa.MELODY and p.form_stack.currentWidget() is p.forms[goa.MELODY]
    form = p.forms[goa.MELODY]
    form.edits["seed"].setText("3")
    form.edits["seed"].textEdited.emit("3")
    folder = Path(p.folder_edit.text())
    assert folder.name == "goa_melody_seed3_145bpm"
    p.render_button.click()
    assert wait_for(qapp, lambda: p.result is not None)
    assert p.result.ok, p.result.error
    got = hashlib.sha256((folder / "goa_melody_seed3_145bpm.mid").read_bytes()).hexdigest()
    assert got == "9a601a7381fbaf7ffb5bb9354bed1ccad7cb78a41261648ddace68ab4ddd0579"
    # voices as check boxes: switching one off removes its track from the preview
    boxes = form.voice_boxes["voices"]
    boxes["pad"].setChecked(False)
    assert form.model.text["voices"] == "lead,arp,pluck"
    assert "pad" not in p.summary.text().split("Spuren:")[1]


def test_goa_optional_switch_activates_the_field(window):
    go(window, "goa")
    form = window.goa.forms[goa.ARRANGEMENT]
    edit = form.edits["density"]
    assert not edit.isEnabled() and "density" not in form.model.active
    form.checks["density"].setChecked(True)
    assert edit.isEnabled() and "density" in form.model.active
    assert not window.goa.render_button.isEnabled()  # active but empty
    edit.setText("lead=0.5")
    edit.textEdited.emit("lead=0.5")
    assert window.goa.render_button.isEnabled()


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


def test_every_goa_checkbox_and_combo_reflects_the_model_after_a_mode_switch(window):
    go(window, "goa")
    p = window.goa
    for mode in goa.MODES:
        form = p.forms[mode]
        for dest, edit in form.edits.items():
            spec = form.model.spec(dest)
            if isinstance(edit, QComboBox):
                if dest in form.model.active:  # a switched-off optional shows its first choice
                    assert edit.currentText() == form.model.text[dest]
            elif isinstance(edit, QCheckBox):
                assert edit.isChecked() == (form.model.text[dest] == "ja")
            assert edit.isEnabled() == (dest in form.model.active), (mode, dest, spec.kind)
