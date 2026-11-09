"""atmos page in the main window (#533): tempo, bars and loop / one-shot on top, the length line,
the intervals list field, the Live note name and the render-time note; one render from the
window into Samples/Atmos."""

from __future__ import annotations

import os
import time

import pytest

if os.environ.get("ABELTONGOD_REQUIRE_GUI") == "1":  # CI: a missing Qt must fail, not skip
    import PySide6.QtWidgets  # noqa: F401
else:
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from gui.app import create_app  # noqa: E402
from gui.category_panel import ATMOS_BPM_HINT, CategoryPanel  # noqa: E402
from gui.widgets import ListControl  # noqa: E402
from gui_core.form import CategoryFormModel  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return create_app([])


def test_atmos_page_shows_tempo_bars_and_loop_mode_on_top(qapp) -> None:
    panel = CategoryPanel(CategoryFormModel("atmos"))
    lay = panel.widget().layout()
    widgets = [lay.itemAt(i).widget() for i in range(lay.count())]
    for name in ("bpm", "bars", "loop_mode"):
        c = panel.controls[name]
        assert c.parent() is panel.widget(), name  # not inside a section
        assert widgets.index(c) < widgets.index(panel.knob_box), name
    hints = [w for w in widgets if w is not None and w.objectName() == "bpmhint"]
    assert len(hints) == 1 and hints[0].text() == ATMOS_BPM_HINT
    assert panel.length_label is not None and not panel.length_label.isHidden()
    assert panel.length_label.text().startswith("8 Takte bei 135 BPM = 14,2 s")
    assert set(panel.group_sections) == {"One-Shot", "Filter", "Bewegung", "Ton", "Grains",
                                         "Reverb"}
    assert panel.cost_label is not None and panel.cost_label.isHidden()


def test_loop_mode_and_bars_change_the_length_line(qapp) -> None:
    model = CategoryFormModel("atmos")
    panel = CategoryPanel(model)
    panel.controls["loop_mode"].seg.chosen.emit(1)  # oneshot, as a click does
    assert model.parse("loop_mode")[0] == "oneshot" and "loop_mode" in model.active
    assert "One-Shot" in panel.length_label.text()
    bars = panel.controls["bars"]
    bars.seg.chosen.emit(bars.texts.index("16"))
    assert panel.length_label.text().startswith("16 Takte bei 135 BPM = 28,4 s")


def test_intervals_field_is_a_list_edit_and_blocks_render_when_wrong(qapp) -> None:
    model = CategoryFormModel("atmos", "drone-root-fifth")
    panel = CategoryPanel(model)
    c = panel.controls["intervals"]
    assert isinstance(c, ListControl) and c.value() == "0, 7, 12"
    c.edit.setText("0, 5, 12")
    c.edit.editingFinished.emit()
    assert model.build_request()["intervals"] == [0, 5, 12]
    c.edit.setText("5, 0")
    c.edit.editingFinished.emit()
    assert not model.is_valid and c.edit.property("invalid") is True
    assert panel.controls["note"].note.text() == "In Live: C1"


def test_long_file_shows_the_render_time_note(qapp) -> None:
    model = CategoryFormModel("atmos", "granular-drone")
    panel = CategoryPanel(model)
    for name, text in (("bars", "32"), ("bpm", "107"), ("grain_density", "200"),
                       ("grain_ms", "500")):
        model.set_active(name, True)
        model.set_text(name, text)
    panel.sync_from_model()
    assert not panel.cost_label.isHidden() and "Grain-Dichte" in panel.cost_label.text()
    assert model.is_valid


def test_render_from_the_main_window_lands_in_samples_atmos(qapp, tmp_path, capsys) -> None:
    from gui.drag import PATH_ROLE
    from gui.main_window import MainWindow
    from gui_core.categories import CATEGORIES

    w = MainWindow(out_dir=tmp_path / "out")
    try:
        w.categories.setCurrentRow([c.key for c in CATEGORIES].index("atmos"))
        assert w.panel.model.category == "atmos" and w.render_button.isEnabled()
        t = time.perf_counter()
        w.render_button.click()
        end = time.monotonic() + 120
        while w.running and time.monotonic() < end:
            qapp.processEvents()
            time.sleep(0.01)
        qapp.processEvents()
        took = time.perf_counter() - t
        with capsys.disabled():
            print(f"\n[#533] atmos air-bed render from the window: {took:.1f} s")
        assert not w.running and w.results.count() == 1, w.status.text()
        wav = w.results.item(0).data(PATH_ROLE)
        assert str(wav).replace("\\", "/").endswith("/out/Samples/Atmos/atmos_air-bed_s1_v0.wav")
    finally:
        w.close()
        w.deleteLater()
