"""fx page in the main window (#482): tempo on top with its hint, sections, render-time note."""

from __future__ import annotations

import os

import pytest

if os.environ.get("ABELTONGOD_REQUIRE_GUI") == "1":  # CI: a missing Qt must fail, not skip
    import PySide6.QtWidgets  # noqa: F401
else:
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from gui.app import create_app  # noqa: E402
from gui.category_panel import FX_BPM_HINT, CategoryPanel  # noqa: E402
from gui_core.form import CategoryFormModel  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return create_app([])


def test_fx_page_shows_tempo_on_top_with_the_hint(qapp) -> None:
    panel = CategoryPanel(CategoryFormModel("fx"))
    lay = panel.widget().layout()
    widgets = [lay.itemAt(i).widget() for i in range(lay.count())]
    bpm = panel.controls["bpm"]
    assert widgets.index(bpm) < widgets.index(panel.knob_box)  # above the Hauptregler
    hints = [w for w in widgets if w is not None and w.objectName() == "bpmhint"]
    assert len(hints) == 1 and hints[0].text() == FX_BPM_HINT and "Takt" in FX_BPM_HINT
    assert bpm.parent() is panel.widget()  # not inside "Erweitert"
    assert set(panel.group_sections) == {"Rauschen", "Filter", "Pegel", "Ton", "Delay",
                                         "Reverb"}
    other = CategoryPanel(CategoryFormModel("laser"))
    assert other.top_fields == () and other.cost_label is None


def test_render_time_note_appears_for_slow_settings_and_never_blocks(qapp) -> None:
    model = CategoryFormModel("fx")
    panel = CategoryPanel(model)
    assert panel.cost_label is not None and panel.cost_label.isHidden()
    # metal at 20 Hz over 32 bars: the slowest tone (~18 s estimated after #503; saw is ~6 s)
    for name, text in (("noise_level", "0"), ("tone_level", "1"), ("tone_wave", "metal"),
                       ("tone_start_hz", "20"), ("tone_end_hz", "20"),
                       ("length_beats", "128")):
        model.set_active(name, True)
        model.set_text(name, text)
    panel.sync_from_model()
    assert not panel.cost_label.isHidden() and "Metall" in panel.cost_label.text()
    assert model.is_valid  # a note only: the request can still be rendered
