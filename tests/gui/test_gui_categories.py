"""GUI-1: category pages, library page and drag-out (offscreen; skipped without PySide6)."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

if os.environ.get("ABELTONGOD_REQUIRE_GUI") == "1":  # CI: a missing Qt must fail, not skip
    import PySide6.QtWidgets  # noqa: F401
else:
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import Qt, QUrl  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QLineEdit  # noqa: E402

from gui.app import create_app  # noqa: E402
from gui.drag import PATH_ROLE, DragList, file_mime  # noqa: E402
from gui.main_window import MainWindow  # noqa: E402
from gui.widgets import BoolControl, Segmented  # noqa: E402
from gui_core.form import CATEGORY_KEYS, CategoryFormModel  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return create_app([])


class FakeBackend:
    available = True

    def play(self, wav_path):
        pass

    def stop(self):
        pass


@pytest.fixture
def window(qapp, tmp_path):
    w = MainWindow(out_dir=tmp_path / "out", backend=FakeBackend(), opener=lambda p: True)
    w.show()
    yield w
    w.close()


def wait_for(qapp, cond, seconds=30):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def type_into(edit: QLineEdit, text: str) -> None:
    edit.selectAll()
    QTest.keyClick(edit, Qt.Key.Key_Delete)
    QTest.keyClicks(edit, text)


def go(window, key: str) -> None:
    window.categories.setCurrentRow(list(CATEGORY_KEYS).index(key))


def test_every_category_page_has_a_control_for_every_contract_field(window):
    for key in CATEGORY_KEYS:
        go(window, key)
        assert window.form_key == key and window.stack.currentWidget() is window.panel
        model = CategoryFormModel(key)
        assert set(window.panel.controls) == {s.name for s in model.specs}, key
        for spec in model.specs:
            assert window.panel.controls[spec.name].label.text() == spec.label
        assert window.render_button.isEnabled(), key
        assert len(window.panel.chips.buttons) == len(model.preset_names())
        assert window.panel.chips.current() == model.preset


def test_enum_fields_are_button_rows_and_bool_fields_are_switches(window):
    go(window, "hat")
    seg = window.panel.controls["model"].seg
    assert isinstance(seg, Segmented) and seg.items == ["metal_bank", "noise"]
    go(window, "clap")
    box = window.panel.controls["tail_reverse"]
    assert isinstance(box, BoolControl) and box.texts == ["nein", "ja"]
    box.toggle.setChecked(True)
    assert window.model.text["tail_reverse"] == "ja" and "tail_reverse" in window.model.active


def test_a_bad_seed_is_per_category_and_does_not_leak_to_others(window):
    go(window, "snare")
    seed = window.panel.controls["seed"]
    type_into(seed.edit, "abc")
    seed.edit.edited.emit("abc")
    assert not window.render_button.isEnabled()
    assert "Seed" in window.status.text()
    go(window, "rim")
    assert window.render_button.isEnabled() and window.status.text() == ""
    go(window, "snare")
    assert not window.render_button.isEnabled()


def test_a_typed_number_outside_the_range_is_clamped_not_sent(window):
    go(window, "snare")
    c = window.panel.controls["body_hz"]
    c.readout.setText("50")
    c.readout.entered.emit("50")
    assert c.value() == 120 and window.model.text["body_hz"] == "120.0"  # contract minimum
    assert "body_hz" in window.model.active and window.render_button.isEnabled()
    assert "liegt außerhalb" in c.note.text()


def test_cross_rule_of_the_engine_is_kept_by_the_bass_controls(window):
    go(window, "bass")
    hp = window.panel.controls["hp_hz"]
    lo, hi = hp.limits
    assert hi < hp.spec.maximum and "Note (MIDI)" in hp.limit_reason
    hp.readout.setText("120")
    hp.readout.entered.emit("120")  # would break hp_hz < 0.8 * f0: clamped to the limit
    assert hp.value() == hi and window.render_button.isEnabled()
    assert window.model.is_valid and "außerhalb" in hp.note.text()
    # moving the partner moves the limit: a higher note allows a higher high-pass
    note = window.panel.controls["note"]
    note.readout.setText("55")
    note.readout.entered.emit("55")
    assert hp.limits[1] > hi


def test_render_in_another_category_lists_the_file(qapp, window):
    go(window, "hat")
    window.render_button.click()
    assert wait_for(qapp, lambda: window.results.count() == 1)
    assert window.results.item(0).text().startswith("hat  hat_closed-std_s")
    assert window.status.text().startswith("Fertig: 1 Datei(en)")
    path = Path(window.results.item(0).data(PATH_ROLE))
    assert path.is_file() and path.with_suffix(".json").is_file()
    assert window.preview.waveform is not None


def test_library_page_lists_filters_and_previews(qapp, window):
    for key in ("kick", "bass"):
        go(window, key)
        window.render_button.click()
        assert wait_for(qapp, lambda: not window.running)
    window.categories.setCurrentRow(window.library_row)  # Bibliothek
    assert window.on_library and window.stack.currentWidget() is window.library
    assert not window.render_button.isEnabled()
    window.start_render()  # also refused when called directly
    assert window.handle is None
    lib = window.library
    assert lib.list.count() == 2 and "2 von 2" in lib.info.text()
    texts = [lib.list.item(i).text() for i in range(2)]
    assert any("kick" in t and "punchy" in t and "Seed 1003" in t for t in texts)
    lib.category_box.setCurrentIndex(lib.category_box.findData("bass"))
    assert lib.list.count() == 1 and "bass" in lib.list.item(0).text()
    lib.category_box.setCurrentIndex(0)
    type_into(lib.search, "kick")
    assert lib.list.count() == 1
    lib.list.setCurrentRow(0)
    assert window.preview.source == Path(lib.list.item(0).data(PATH_ROLE))
    assert window.wave.waveform is not None


def test_library_shows_bad_files_as_unlesbar(qapp, window, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "broken.wav").write_bytes(b"RIFF")
    window.categories.setCurrentRow(window.library_row)
    assert window.library.list.count() == 1
    assert "unlesbar" in window.library.list.item(0).text()
    window.library.list.setCurrentRow(0)  # preview of a non-engine file reports, never raises
    assert window.preview.waveform is None and "Keine WAV" in window.preview_info.text()


def test_drag_out_offers_the_wav_as_file_url(qapp, window, tmp_path):
    go(window, "kick")
    window.render_button.click()
    assert wait_for(qapp, lambda: window.results.count() == 1)
    wav = Path(window.results.item(0).data(PATH_ROLE))
    mime = window.results.mimeData([window.results.item(0)])
    assert mime.hasUrls()
    # Qt gives forward slashes on Windows: compare as paths, not as strings
    assert [Path(u.toLocalFile()) for u in mime.urls()] == [wav]
    assert mime.urls()[0].scheme() == "file"
    assert isinstance(window.results, DragList)
    assert window.results.dragEnabled()

    window.categories.setCurrentRow(window.library_row)
    lib = window.library
    assert lib.list.dragEnabled()
    urls = lib.list.mimeData([lib.list.item(0)]).urls()
    assert [Path(u.toLocalFile()) for u in urls] == [wav]


def test_drag_mime_skips_missing_files(tmp_path):
    real = tmp_path / "a.wav"
    real.write_bytes(b"x")
    mime = file_mime([real, tmp_path / "gone.wav"])
    assert mime.urls() == [QUrl.fromLocalFile(str(real))]
