"""Click-path regressions of the form side-findings #424, #428 and #434 (offscreen; teardown:
autouse fixture of tests/gui/conftest.py). Model-level cases are in ``tests/regressions/``."""

from __future__ import annotations

import json
import os
import random

import pytest

if os.environ.get("ABELTONGOD_REQUIRE_GUI") == "1":
    import PySide6.QtWidgets  # noqa: F401
else:
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from audio_engine.params import CONTRACTS_DIR  # noqa: E402
from gui.app import create_app  # noqa: E402
from gui.category_panel import CategoryPanel  # noqa: E402
from gui.widgets import NumberControl  # noqa: E402
from gui_core import links  # noqa: E402
from gui_core.form import CategoryFormModel  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return create_app([])


def _contract(category: str) -> dict:
    return json.loads((CONTRACTS_DIR / f"{category}-params.schema.json").read_text("utf-8"))


def _type(c, text: str) -> None:
    c.readout.setText(text)
    c.readout.entered.emit(text)


def _panel(category: str) -> CategoryPanel:
    p = CategoryPanel(CategoryFormModel(category))
    p.resize(700, 900)
    p.show()
    return p


# --- #428 ------------------------------------------------------------------------------------

def test_bug_428_value_typed_into_an_inactive_field_is_clamped_and_render_stays_allowed(qapp):
    p = _panel("rim")
    f1, hp = p.controls["f1_hz"], p.controls["hp_hz"]
    _type(f1, "900")
    _type(hp, "500")
    hp.dot.setChecked(False)  # Hochpass off: its text "500" stays in the model
    f1.dot.setChecked(False)  # Frequenz 1 off: the engine uses the contract default
    bound = 0.8 * _contract("rim")["properties"]["f1_hz"]["default"]  # rule hp < 0.8 * f1
    _type(hp, "6000")
    assert p.model.issues() == [], p.model.issues()  # before the fix: "hp_hz must be < 364"
    value = p.model.parse("hp_hz")[0]
    assert 0.99 * bound < value < bound, value
    assert "außerhalb" in hp.note.text()


# --- #424 ------------------------------------------------------------------------------------

def test_bug_424_blaster_starts_exactly_on_the_contract_defaults(qapp, tmp_path):
    """The first blaster shot sends the contract defaults exactly (not a slider position
    rounded to 101 steps: 3000 Hz, not 2923 Hz). Defaults read from the contract file."""
    from gui.blaster.window import BlasterWindow
    from gui_core import blaster_params as bp
    from gui_core.blaster_stub import StubLaserEngine

    schema = _contract("laser")
    props = dict(schema["properties"])
    for branch in schema["allOf"]:
        props.update({k: v for k, v in branch["then"].get("properties", {}).items()
                      if k not in props})
    w = BlasterWindow(engine=StubLaserEngine(), out_dir=tmp_path / "out",
                      work_dir=tmp_path / "work")
    checked = 0
    for name, ctrls in w.num.items():
        default = props[name].get("default")
        if default is None:
            continue
        for c in ctrls:
            assert c.value() == default and type(c.value()) is type(default), (name, c.value())
            checked += 1
    params = bp.to_engine_params(w.settings)
    for name, value in params.items():
        if name in props and "default" in props[name] and name in w.num:
            assert value == props[name]["default"], (name, value)
    assert checked >= 40
    assert params["pitch_start_hz"] == 3000 and params["sweep_curve"] == 1  # the issue's cases


# --- #434 ------------------------------------------------------------------------------------

def _resolves(action) -> int:
    links.clear_cache()
    before = links.stats["resolve"]
    action()
    return links.stats["resolve"] - before


def test_bug_434_one_laser_edit_probes_only_the_fields_the_page_shows(qapp):
    """Before: every edit probed every numeric field (about 140 resolves on the laser page).
    Now: the visible ones (5 knobs + Varianten), plus the edited hidden field when touched."""
    p = _panel("laser")
    knob = p.controls[p.main_names[0]]
    n = _resolves(lambda: knob.slider.move_to_position(knob.vmap.pos_max // 3))
    assert n <= 25, n  # 5 visible numeric fields x 3 probes + derived/repair checks
    hidden = p.controls["reverb_mix"]
    assert not hidden.isVisibleTo(p)
    n = _resolves(lambda: hidden.slider.move_to_position(hidden.vmap.pos_max // 2))
    assert n <= 30, n


def test_bug_434_no_limit_is_probed_during_a_mouse_drag_and_release_brings_them_up(qapp):
    p = _panel("rim")
    f1, hp = p.controls["f1_hz"], p.controls["hp_hz"]
    s = f1.slider
    before = hp.slider.limits  # the slider's own value, without asking the page
    QTest.mousePress(s, Qt.MouseButton.LeftButton, pos=s.rect().center())
    assert f1.is_dragging()
    links.clear_cache()
    start = links.stats["resolve"]
    s.move_to_position(s.vmap.pos_max)  # as a mouse move does
    during = links.stats["resolve"] - start
    assert hp.slider.limits == before  # not probed while the mouse is down
    QTest.mouseRelease(s, Qt.MouseButton.LeftButton, pos=s.rect().center())
    assert not f1.is_dragging()
    assert 2799 <= hp.limits[1] <= 2800  # f1 3500 Hz now: hp < 0.8 * 3500
    assert during <= 6, during


def test_bug_434_shown_rows_are_probed_while_idle_in_small_batches(qapp):
    from gui.category_panel import IDLE_BATCH

    p = _panel("laser")
    for s in [p.advanced, *p.group_sections.values()]:
        s.set_expanded(True)
    knob = p.controls[p.main_names[0]]
    knob.slider.move_to_position(knob.vmap.pos_max // 4)
    knob.slider.released.emit()
    rows = [n for n in p._shown_numbers() if n not in p.main_names]
    assert len(rows) > 30 and all(n in p._stale for n in rows)  # not probed in the handler
    links.clear_cache()
    before = links.stats["resolve"]
    p._probe_pending()  # one idle tick
    assert links.stats["resolve"] - before <= 3 * IDLE_BATCH
    deadline = 200
    while p._pending and deadline:
        qapp.processEvents()
        deadline -= 1
    assert not p._pending and not any(n in p._stale for n in rows)


def test_bug_434_hidden_limits_are_probed_when_their_section_opens(qapp):
    p = _panel("bass")
    hp = p.controls["hp_hz"]
    assert not hp.isVisibleTo(p) and "hp_hz" in p._stale
    p.advanced.set_expanded(True)
    assert "hp_hz" not in p._stale
    assert hp.slider.limits[1] < 79 and "Note (MIDI)" in hp.note.text()


def test_bug_434_stale_hidden_field_is_probed_before_a_typed_value_is_clamped(qapp):
    """A hidden field's limits are out of date; typing into it must still clamp to the real
    limit (bass: hp_hz < 0.4 * f0, f0 from the note)."""
    p = _panel("bass")
    hp = p.controls["hp_hz"]
    assert hp.style_name == "row"  # under "Erweitert"
    _type(p.controls["note"], "40")  # f0 82.4 Hz: hp_hz at most 0.8 * f0, below the maximum
    assert "hp_hz" in p._stale
    _type(hp, "5000")
    assert p.model.issues() == [], p.model.issues()
    assert hp.value() < 0.8 * 82.41 and "außerhalb" in hp.note.text()


# The property over all pages (random drags, typed values, dots, choices, presets) lives in
# test_widgets.py; this one adds hidden fields and section toggles, which the lazy limits of
# #434 depend on.
@pytest.mark.parametrize("category", ["rim", "bass", "kick", "laser"])
def test_random_actions_with_sections_opening_and_closing_keep_the_form_accepted(qapp, category):
    rng = random.Random(f"sections-{category}")
    p = _panel(category)
    sections = [p.advanced, *p.group_sections.values()]
    numbers = [c for n, c in p.controls.items() if isinstance(c, NumberControl)
               and n != "variants"]
    for step in range(80):
        r = rng.random()
        c = rng.choice(numbers)
        if r < 0.35:
            c.slider.move_to_position(rng.randint(0, c.vmap.pos_max))
            c.slider.released.emit()
        elif r < 0.6:
            lo, hi = c.vmap.minimum, c.vmap.maximum
            _type(c, repr(round(rng.uniform(lo - (hi - lo), hi + (hi - lo)), 3)))
        elif r < 0.8:
            c.dot.setChecked(not c.dot.isChecked())
        else:
            s = rng.choice(sections)
            s.set_expanded(not s.is_expanded())
        assert p.model.issues() == [], (category, step, p.model.issues())
        p.settle()  # what the idle timer does between events
        shown = p._shown_numbers()
        for name in rng.sample(shown, min(3, len(shown))):  # what the page shows is up to date
            fresh = links.limit_of(p.model, name)
            assert (fresh.lo, fresh.hi) == p.controls[name].slider.limits, (category, step, name)
