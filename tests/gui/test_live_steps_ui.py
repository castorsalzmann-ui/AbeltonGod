"""#548: the Live-import page shows the numbered steps, the next step, why each grey button
is grey (tooltip), and the AbletonOSC setup hint after a failed "Live-Set lesen". Offscreen;
step results are fed in directly (no OSC; the fake-OSC flow is in test_gui_tools.py)."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

if os.environ.get("ABELTONGOD_REQUIRE_GUI") == "1":
    import PySide6.QtWidgets  # noqa: F401
else:
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from audio_engine.io import encode_wav  # noqa: E402
from gui.app import create_app  # noqa: E402
from gui_core.live import ImportPlan, LiveInspection  # noqa: E402

NO_ANSWER = ("FEHLER: AbletonOSC antwortet nicht (127.0.0.1:11000).\nMögliche Ursachen ...")


@pytest.fixture(scope="module")
def qapp():
    return create_app([])


@pytest.fixture
def page(qapp, tmp_path):
    from gui.live_panel import LivePanel

    p = LivePanel(library_folder=lambda: tmp_path / "empty")
    p.show()
    yield p
    p.close()


def add_wav(page, tmp_path) -> Path:
    w = tmp_path / "kick_x.wav"
    w.write_bytes(encode_wav(np.zeros(480), 48000, 24))
    page.add_wav(w)
    return w


def test_without_a_wav_every_step_says_what_to_do(page):
    assert not page.inspect_button.isEnabled()
    assert "Erst eine WAV wählen" in page.inspect_button.toolTip()
    assert "Erst eine WAV wählen" in page.next_label.text()
    assert "1 · Live-Set lesen" in page.steps_label.text()
    assert "<b>1 · Live-Set lesen</b>" in page.steps_label.text()
    assert not page.import_button.isEnabled() and page.import_button.toolTip().startswith(
        "Gesperrt:")
    assert not page.setup_label.isVisible()


def test_failed_read_shows_the_error_and_the_setup_hint(page, tmp_path):
    add_wav(page, tmp_path)
    assert page.inspect_button.isEnabled() and not page.inspect_button.toolTip().startswith(
        "Gesperrt")
    assert page.next_label.text() == "Nächster Schritt: 1 · „Live-Set lesen“ klicken."
    assert page.plan_button.toolTip() == "Gesperrt: Erst Schritt 1: „Live-Set lesen“."
    page._on_inspected(LiveInspection(False, NO_ANSWER))
    assert page.status.text().startswith("FEHLER: AbletonOSC antwortet nicht")
    assert page.status.property("level") == "error"
    assert page.setup_label.isVisible()
    assert "ABLETONOSC_WINDOWS.md" in page.setup_label.text()
    assert page.setup_label.openExternalLinks()
    assert not page.plan_button.isEnabled() and "fehlgeschlagen" in page.plan_button.toolTip()


def test_steps_advance_and_the_last_gate_names_the_confirmation(page, tmp_path):
    add_wav(page, tmp_path)
    page._on_inspected(LiveInspection(True, live_version="12.1"))
    assert not page.setup_label.isVisible()
    assert "<b>2 · Plan prüfen</b>" in page.steps_label.text()
    assert page.plan_button.isEnabled()
    assert page.import_button.toolTip() == "Gesperrt: Erst Schritt 2: „Plan prüfen“."
    page._on_planned(ImportPlan(True, text="Plan"))
    assert "<b>3 · In Live importieren</b>" in page.steps_label.text()
    assert not page.import_button.isEnabled()
    assert "Test-Set" in page.import_button.toolTip() and "Test-Set" in page.next_label.text()
    page.testset_check.setChecked(True)
    if page.needs_unverified_ok:  # registry has unverified capabilities: second confirmation
        assert "nicht verifiziert" in page.import_button.toolTip()
        page.unverified_check.setChecked(True)
    assert page.import_button.isEnabled()
    assert page.next_label.text() == "Nächster Schritt: 3 · „In Live importieren“ klicken."
