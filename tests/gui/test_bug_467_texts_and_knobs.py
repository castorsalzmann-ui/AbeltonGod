"""#467: German preset descriptions in the GUI; knobs stay aligned when a label wraps.
Offscreen; teardown: autouse fixture of tests/gui/conftest.py."""

from __future__ import annotations

import os
import re

import pytest

if os.environ.get("ABELTONGOD_REQUIRE_GUI") == "1":
    import PySide6.QtWidgets  # noqa: F401
else:
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from audio_engine.presets import describe, preset_names  # noqa: E402
from gui.app import create_app  # noqa: E402
from gui_core.form import CATEGORY_KEYS, CategoryFormModel  # noqa: E402
from gui_core.preset_texts import PRESET_TEXTS_DE  # noqa: E402

SHIPPED = [(c, p) for c in CATEGORY_KEYS for p in preset_names(c)]
GERMAN = re.compile(r"(?i)\b(und|mit|der|die|das|kein|keine|ohne|plus|bei|über|von|ein|eine|einem|nur|auf|aus)\b|[äöüß]")


@pytest.fixture(scope="module")
def qapp():
    return create_app([])


def test_every_shipped_preset_has_a_german_text_and_no_stale_entries():
    missing = [k for k in SHIPPED if k not in PRESET_TEXTS_DE]
    assert missing == []
    assert set(PRESET_TEXTS_DE) == set(SHIPPED)  # no entry for a preset that does not exist
    for key, text in PRESET_TEXTS_DE.items():
        assert GERMAN.search(text), key  # reads as German, not the copied English text
        assert text != describe(key[1], key[0]), key


def test_the_form_shows_the_german_text_and_falls_back_to_the_file(monkeypatch):
    m = CategoryFormModel("kick", "punchy")
    assert m.preset_description() == PRESET_TEXTS_DE[("kick", "punchy")]
    monkeypatch.delitem(PRESET_TEXTS_DE, ("kick", "punchy"))
    assert m.preset_description() == describe("punchy", "kick")


@pytest.mark.parametrize("category", CATEGORY_KEYS)
def test_knob_dials_line_up_also_when_a_label_wraps(qapp, category):
    from gui.category_panel import CategoryPanel

    p = CategoryPanel(CategoryFormModel(category))
    p.resize(1200, 800)
    p.show()
    qapp.processEvents()
    # force a two-line label on one knob, whatever the platform font wraps
    p.knobs[1].label.setText("Klang (dunkel/hell) und noch etwas mehr")
    p.knob_box.layout().invalidate()
    p.knob_box.adjustSize()
    qapp.processEvents()
    tops = {k.slider.mapTo(p.knob_box, k.slider.rect().topLeft()).y() for k in p.knobs}
    readouts = {k.readout.mapTo(p.knob_box, k.readout.rect().topLeft()).y() for k in p.knobs}
    assert len(tops) == 1 and len(readouts) == 1, (tops, readouts)
