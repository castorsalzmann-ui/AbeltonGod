"""Referenz page (#480): measure a WAV in a worker thread, show the values, hand the nearest
candidate to the kick form. Offscreen; says nothing about the sound."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import numpy as np
import pytest

if os.environ.get("ABELTONGOD_REQUIRE_GUI") == "1":  # CI: a missing Qt must fail, not skip
    import PySide6.QtWidgets  # noqa: F401
else:
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDropEvent  # noqa: E402

from audio_engine.io import encode_wav  # noqa: E402
from audio_engine.kick import render_kick, render_resolved  # noqa: E402
from audio_engine.presets import load_preset  # noqa: E402
from audio_engine.variants import make_variant  # noqa: E402
from gui.app import create_app  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("gui_tour", ROOT / "scripts" / "qa" / "gui_tour.py")
tour_mod = sys.modules.get("gui_tour")
if tour_mod is None:
    tour_mod = importlib.util.module_from_spec(_spec)
    sys.modules["gui_tour"] = tour_mod
    _spec.loader.exec_module(tour_mod)

WAIT = 60.0


@pytest.fixture
def window(tmp_path):
    create_app([])
    with tour_mod.isolated_env(tmp_path):
        w = tour_mod.make_window(tmp_path / "out")
        w.categories.setCurrentRow(w.tool_rows["reference"])
        yield w
        w.close()


def _variant_wav(tmp_path: Path) -> tuple[Path, dict]:
    params = make_variant(dict(load_preset("driven"), seed=4242), 77)
    path = tmp_path / "meine referenz.wav"
    path.write_bytes(encode_wav(render_resolved(params), 48000, 24))
    return path, params


def test_apply_puts_exactly_the_candidate_into_the_kick_form(window, tmp_path):
    path, _ = _variant_wav(tmp_path)
    page = window.reference
    assert not page.apply_button.isEnabled()
    assert page.analyse(path)
    assert not page.pick_button.isEnabled()  # busy
    assert tour_mod.wait_for(lambda: not page.busy, WAIT)
    assert page.outcome.ok, page.status.text()
    cand = page.outcome.match.nearest
    assert page.table.item(0, 2).text() != "–"
    assert cand.name in page.candidate_label.text()
    page.apply_button.click()
    assert window.form_key == "kick" and window.stack.currentIndex() == 0
    assert window.model.preset == cand.preset
    assert cand.name in window.status.text()
    # The form renders the candidate's samples, byte for byte (default format 48 kHz / 24 bit).
    audio, _ = render_kick(window.model.build_request())
    assert np.array_equal(audio, render_resolved(cand.params))
    assert window.render_button.isEnabled()


def test_unreadable_file_shows_the_german_reason_and_keeps_apply_off(window, tmp_path):
    bad = tmp_path / "kaputt.wav"
    bad.write_bytes(b"RIFF....nope")
    page = window.reference
    page.analyse(bad)
    assert tour_mod.wait_for(lambda: not page.busy, WAIT)
    assert "Keine WAV-Datei" in page.status.text()
    assert page.status.property("level") == "error"
    assert not page.apply_button.isEnabled()
    assert page.table.item(0, 1).text() == "–"


def test_a_second_file_is_refused_while_one_is_measured(window, tmp_path):
    path, _ = _variant_wav(tmp_path)
    page = window.reference
    assert page.analyse(path)
    assert not page.analyse(path)
    assert tour_mod.wait_for(lambda: not page.busy, WAIT)


def test_dropping_a_wav_starts_the_measurement(window, tmp_path):
    path, _ = _variant_wav(tmp_path)
    page = window.reference
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    event = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    page.dropEvent(event)
    assert page.busy or page.outcome is not None
    assert tour_mod.wait_for(lambda: not page.busy, WAIT)
    assert page.outcome.ok and page.outcome.path == path
    two = QMimeData()
    two.setUrls([QUrl.fromLocalFile(str(path)), QUrl.fromLocalFile(str(path))])
    assert page._dropped_path(two) is None  # one file at a time
