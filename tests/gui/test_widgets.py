"""Widget kit (offscreen): value mapping, clamping, keyboard, linked parameters on the category
pages. Skipped when PySide6 is not installed."""

from __future__ import annotations

import os
import random

import pytest

if os.environ.get("ABELTONGOD_REQUIRE_GUI") == "1":  # CI: a missing Qt must fail, not skip
    import PySide6.QtWidgets  # noqa: F401
else:
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from gui.app import create_app  # noqa: E402
from gui.category_panel import CategoryPanel  # noqa: E402
from gui.widgets import (  # noqa: E402
    Collapsible,
    KnobDial,
    NumberControl,
    PresetChips,
    Segmented,
    Stepper,
    Toggle,
    ToggleRow,
    TrackSlider,
)
from gui_core.form import CATEGORY_KEYS, CategoryFormModel, field_specs  # noqa: E402
from gui_core.valuemap import ValueMap  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return create_app([])


def key(w, k, mod=Qt.KeyboardModifier.NoModifier):
    QTest.keyClick(w, k, mod)


# --- slider: mapping, keyboard, clamping ------------------------------------------------------

def test_slider_keeps_an_exact_value_and_moves_in_rounded_steps(qapp):
    s = TrackSlider(ValueMap(0.0, 1.0))
    got = []
    s.userChanged.connect(got.append)
    s.set_value(0.37)
    assert s.value_exact() == 0.37 and got == []  # programmatic: nothing emitted, nothing rounded
    s.show()
    s.setFocus()
    key(s, Qt.Key.Key_Right)  # 1 % of the travel
    assert got == [0.38]
    key(s, Qt.Key.Key_Left, Qt.KeyboardModifier.ShiftModifier)  # one position
    assert got[-1] == 0.379
    key(s, Qt.Key.Key_PageUp)
    assert got[-1] == 0.479
    key(s, Qt.Key.Key_Home)
    assert got[-1] == 0.0
    key(s, Qt.Key.Key_End)
    assert got[-1] == 1.0
    key(s, Qt.Key.Key_End)  # already there: no second event
    assert len(got) == 5


def test_slider_same_position_does_not_round_a_preset_value(qapp):
    s = TrackSlider(ValueMap(0.0, 1.0))
    s.set_value(0.3004)
    got = []
    s.userChanged.connect(got.append)
    s.move_to_position(300)  # the position the value already maps to
    assert got == [] and s.value_exact() == 0.3004


def test_slider_cannot_be_moved_outside_the_limits_and_ends_are_exact(qapp):
    s = TrackSlider(ValueMap(20.0, 6000.0, log=True))
    s.set_limits(20.0, 364.0)
    s.set_value(200.0)
    s.move_to_position(s.vmap.pos_max)  # drag to the far end
    assert s.value_exact() == 364.0
    s.move_to_position(0)
    assert s.value_exact() == 20.0
    s.set_limits(72.0, 6000.0)
    s.move_to_position(0)
    assert s.value_exact() == 72.0


def test_slider_mouse_press_and_drag_set_values_from_the_x_position(qapp):
    s = TrackSlider(ValueMap(0.0, 1.0))
    s.resize(400, 30)
    s.show()
    got = []
    s.userChanged.connect(got.append)
    r = s._em() * 0.5
    QTest.mouseClick(s, Qt.MouseButton.LeftButton, pos=QPoint(int(r + (400 - 2 * r) * 0.25), 15))
    assert abs(got[-1] - 0.25) < 0.01
    QTest.mousePress(s, Qt.MouseButton.LeftButton, pos=QPoint(int(r), 15))
    QTest.mouseMove(s, QPoint(430, 15))  # past the end: clamped
    QTest.mouseRelease(s, Qt.MouseButton.LeftButton, pos=QPoint(430, 15))
    assert got[-1] == 1.0


def test_wheel_only_acts_with_focus(qapp):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QWheelEvent

    s = TrackSlider(ValueMap(0.0, 1.0))
    s.show()
    s.set_value(0.5)

    def wheel():
        ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120),
                         Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                         Qt.ScrollPhase.NoScrollPhase, False)
        qapp.sendEvent(s, ev)
        return ev.isAccepted()

    s.activateWindow()
    QTest.qWaitForWindowActive(s)
    s.clearFocus()
    assert not wheel() and s.value_exact() == 0.5  # ignored: the page scrolls instead
    s.setFocus()
    assert wheel() and s.value_exact() == 0.51


def test_integer_slider_walks_whole_numbers(qapp):
    s = TrackSlider(ValueMap(1, 8, integer=True, steps=7))
    s.show()
    s.set_value(3)
    s.setFocus()
    got = []
    s.userChanged.connect(got.append)
    key(s, Qt.Key.Key_Right)
    key(s, Qt.Key.Key_Right)
    assert got == [4, 5] and all(isinstance(v, int) for v in got)


def test_knob_drags_vertically_and_respects_limits(qapp):
    k = KnobDial(ValueMap(0.0, 1.0))
    k.resize(60, 60)
    k.show()
    k.set_value(0.5)
    got = []
    k.userChanged.connect(got.append)
    QTest.mousePress(k, Qt.MouseButton.LeftButton, pos=QPoint(30, 30))
    QTest.mouseMove(k, QPoint(30, 30 - int(k._em() * 12 * 0.2)))  # up by 20 % of the travel
    QTest.mouseRelease(k, Qt.MouseButton.LeftButton, pos=QPoint(30, 10))
    assert abs(got[-1] - 0.7) < 0.02
    k.set_limits(0.0, 0.6)
    k.move_to_position(1000)
    assert k.value_exact() == 0.6
    k.setFocus()
    key(k, Qt.Key.Key_Down)
    assert k.value_exact() == 0.59


# --- controls: typed entry, clamping, activation ------------------------------------------------

def test_typed_value_keeps_its_digits_and_clamps_to_contract_and_limits(qapp):
    spec = next(s for s in field_specs("kick") if s.name == "drive")
    c = NumberControl(spec)
    got = []
    c.edited.connect(lambda n, v: got.append(v))
    for text, expected in (("0,37", 0.37), ("0.123456", 0.123456), ("7", 1), ("-2", 0), ("1", 1)):
        c.readout.setText(text)
        c.readout.entered.emit(text)
        assert got[-1] == expected, text
    assert isinstance(got[-1], int)  # an int typed into a float field stays an int (CLI parity)
    c.set_limits(0.0, 0.4, "Drive: höchstens 0,4.")
    c.readout.setText("0.9")
    c.readout.entered.emit("0.9")
    assert got[-1] == 0.4 and "außerhalb" in c.note.text()
    c.readout.setText("abc")
    c.readout.entered.emit("abc")
    assert got[-1] == 0.4 and "Zahl" in c.note.text()  # refused, value unchanged


def test_unit_text_can_be_typed_and_off_value_reads_aus(qapp):
    hat = {s.name: s for s in field_specs("hat")}["choke_ms"]
    c = NumberControl(hat)
    got = []
    c.edited.connect(lambda n, v: got.append(v))
    c.readout.setText("aus")
    c.readout.entered.emit("aus")
    assert got == [0] and c.readout.text() == "aus"
    c.readout.setText("40 ms")
    c.readout.entered.emit("40 ms")
    assert got[-1] == 40 and c.readout.text() == "40 ms"


def test_control_signals_are_silent_for_programmatic_changes(qapp):
    spec = next(s for s in field_specs("kick") if s.name == "tone")
    c = NumberControl(spec, style="knob", accent=True)
    got = []
    c.edited.connect(lambda *a: got.append(a))
    c.activeToggled.connect(lambda *a: got.append(a))
    c.set_value(0.25)
    c.set_active(False)
    c.set_limits(-0.5, 0.5, "x")
    assert got == [] and c.value() == 0.25 and not c.is_active()


# --- other kit widgets ------------------------------------------------------------------------

def test_toggle_space_key_and_toggle_row(qapp):
    t = Toggle()
    t.show()
    t.setFocus()
    got = []
    t.toggled.connect(got.append)
    key(t, Qt.Key.Key_Space)
    key(t, Qt.Key.Key_Space)
    assert got == [True, False]
    row = ToggleRow("Text")
    seen = []
    row.toggled.connect(seen.append)
    row.setChecked(True)
    assert row.isChecked() and seen == [True] and row.text() == "Text"


def test_segmented_arrows_home_end_and_silent_set(qapp):
    seg = Segmented(["a", "b", "c"])
    seg.show()
    seg.setFocus()
    got = []
    seg.chosen.connect(got.append)
    seg.set_index(0)
    assert got == []
    key(seg, Qt.Key.Key_Right)
    key(seg, Qt.Key.Key_End)
    key(seg, Qt.Key.Key_Right)  # at the end: stays
    key(seg, Qt.Key.Key_Home)
    assert got == [1, 2, 0] and seg.index() == 0
    seg.buttons[2].click()
    assert got[-1] == 2 and [b.isChecked() for b in seg.buttons] == [False, False, True]


def test_preset_chips_single_and_multi(qapp):
    chips = PresetChips(["x", "y", "z"])
    chips.show()
    chips.setFocus()
    got = []
    chips.chosen.connect(got.append)
    chips.set_current("x")
    key(chips, Qt.Key.Key_Right)
    chips.buttons[0].click()
    assert got == ["y", "x"] and chips.current() == "x"
    chips.buttons[0].click()  # clicking the chosen chip again keeps it chosen
    assert chips.buttons[0].isChecked()
    multi = PresetChips(["lead", "arp", "pad"], multi=True)
    multi.show()
    seen = []
    multi.changed.connect(seen.append)
    multi.set_selected(["lead", "pad"])
    assert seen == []
    multi.buttons[1].click()
    multi.buttons[0].click()
    assert seen == [["lead", "arp", "pad"], ["arp", "pad"]]
    multi.setFocus()
    key(multi, Qt.Key.Key_Right)
    key(multi, Qt.Key.Key_Space)  # focus mark moved to "arp": toggles it
    assert seen[-1] == ["pad"]


def test_chips_wrap_to_the_available_width(qapp):
    chips = PresetChips([f"preset-number-{i}" for i in range(10)])
    chips.resize(300, 10)
    chips.show()
    wide = chips.heightForWidth(1200)
    assert chips.layout().heightForWidth(300) > wide


def test_collapsible_and_stepper(qapp):
    c = Collapsible("Erweitert")
    c.show()
    assert not c.is_expanded() and not c.body.isVisible()
    c.header.click()
    assert c.is_expanded() and c.body.isVisible()
    s = Stepper(0, 5)
    s.setSpecialValueText("erste freie Zelle")
    s.show()
    assert s.text() == "erste freie Zelle"
    s.setFocus()
    got = []
    s.valueChanged.connect(got.append)
    key(s, Qt.Key.Key_Up)
    key(s, Qt.Key.Key_End)
    key(s, Qt.Key.Key_Up)  # at the maximum
    key(s, Qt.Key.Key_Down)
    assert got == [1, 5, 4] and s.text() == "4"
    s.setMaximum(2)
    assert s.value() == 2


# --- the category pages: linked parameters ---------------------------------------------------

@pytest.fixture
def make_panel(qapp):
    panels = []

    def make(category: str) -> CategoryPanel:
        p = CategoryPanel(CategoryFormModel(category))
        p.resize(700, 900)
        p.show()
        panels.append(p)
        return p

    yield make
    for p in panels:
        p.close()


def test_changing_the_partner_moves_the_limit_live_and_shows_the_reason(make_panel):
    p = make_panel("rim")
    hp = p.controls["hp_hz"]  # a main knob on the rim page
    assert hp.limits[1] < 364.01 and "Frequenz 1" in hp.limit_reason
    assert "Frequenz 1" in p.link_label.text()
    f1 = p.controls["f1_hz"]
    f1.slider.move_to_position(f1.vmap.pos_max)
    f1.slider.released.emit()
    assert 2799 <= hp.limits[1] <= 2800  # f1 now 3500 Hz: hp < 0.8 * 3500


def test_row_sliders_show_their_own_limit_reason_under_the_slider(make_panel):
    p = make_panel("bass")
    p.advanced.set_expanded(True)
    hp = p.controls["hp_hz"]  # an "Erweitert" row on the bass page
    assert hp.style_name == "row" and "Note (MIDI)" in hp.note.text()
    assert hp.note.isVisibleTo(p) and hp.limits[1] < 79


def test_knob_limits_are_listed_in_the_page_hint(make_panel):
    p = make_panel("bass")
    for name, text in (("note", "55"), ("hp_hz", "100")):  # f0 196 Hz allows hp up to 156 Hz
        c = p.controls[name]
        c.readout.setText(text)
        c.readout.entered.emit(text)
    lp = p.controls["lp_hz"]  # a main knob
    # lp_hz >= 1.2 * hp_hz, limit grid 0.001
    assert lp.style_name == "knob" and 120 <= lp.limits[0] <= 120.001
    assert "Tiefpass" in p.link_label.text() and "Hochpass" in p.link_label.text()


def test_derived_length_follows_decay_on_the_hat_page(make_panel):
    p = make_panel("hat")
    length = p.controls["length_ms"]
    assert not length.is_active()
    before = length.value()
    decay = p.controls["decay_ms"]
    decay.readout.setText("400")
    decay.readout.entered.emit("400")
    assert length.value() > before  # the engine derives the file length from the decay


def test_tail_note_switches_pitch_end_off_and_shows_the_hertz_it_makes(make_panel):
    p = make_panel("kick")
    p.advanced.set_expanded(True)
    note = p.controls["tail_note"]
    note.readout.setText("33")
    note.readout.entered.emit("33")
    assert "tail_note" in p.model.active and "pitch_end_hz" not in p.model.active
    assert "schließen sich aus" in p.link_label.text()
    assert "55" in note.note.text() and "Hz" in note.note.text()
    assert p.model.is_valid


@pytest.mark.parametrize("category", CATEGORY_KEYS)
def test_random_user_actions_never_produce_an_invalid_combination(make_panel, category):
    """Property: whatever is dragged, typed, switched or loaded, the engine still accepts the
    form (contract cross rules cannot be dialled in). Seeded random actions on every page."""
    rng = random.Random(f"links-{category}")
    p = make_panel(category)
    names = [n for n, c in p.controls.items() if isinstance(c, NumberControl)
             and n not in ("variants",)]
    for step in range(120):
        action = rng.random()
        name = rng.choice(names)
        c = p.controls[name]
        if action < 0.45:
            c.slider.move_to_position(rng.randint(0, c.vmap.pos_max))
        elif action < 0.75:
            lo, hi = c.vmap.minimum, c.vmap.maximum
            text = repr(round(rng.uniform(lo - 5, hi + 5), 3))
            c.readout.setText(text)
            c.readout.entered.emit(text)
        elif action < 0.9:
            c.dot.setChecked(not c.dot.isChecked())
        else:
            chips = p.chips
            chips.buttons[rng.randrange(len(chips.buttons))].click()
        assert p.model.issues() == [], (category, step, name, p.model.issues())


# --- review round 1: notes, dots and choices ---------------------------------------------------

def type_in(c, text):
    c.readout.setText(text)
    c.readout.entered.emit(text)


def visible_note(panel, c) -> bool:
    n = c.note
    return (not n.isWindow() and n.parent() is not None and n.isVisibleTo(panel)
            and n.text() != "")


def test_knob_clamp_note_is_a_visible_child_of_the_page_not_a_stray_window(make_panel):
    p = make_panel("kick")
    knob = p.controls["drive"]
    assert knob.style_name == "knob" and not knob.note.isWindow()
    type_in(knob, "99999")
    assert knob.value() == 1 and visible_note(p, knob)
    assert "außerhalb" in knob.note.text() and "gesetzt auf 1" in knob.note.text()
    assert knob.isAncestorOf(knob.note) and p.isAncestorOf(knob.note)
    type_in(knob, "0.5")  # a valid entry removes the note
    assert not knob.note.isVisibleTo(p)


@pytest.mark.parametrize(("typed", "expected", "word"), [
    ("0", 50, "außerhalb"), ("1e9", 1500, "außerhalb"), ("12,5 ms", 50, "außerhalb"),
])
def test_slider_row_keeps_its_clamp_note_after_the_page_refreshes(make_panel, typed, expected,
                                                                   word):
    p = make_panel("bass")
    p.advanced.set_expanded(True)
    gate = p.controls["gate_ms"]
    assert gate.style_name == "row"
    type_in(gate, typed)  # typing commits: the page refreshes (final=True) right after
    assert gate.value() == expected and visible_note(p, gate), typed
    assert word in gate.note.text()
    p._refresh(skip=None, final=True)  # any later refresh keeps it
    assert visible_note(p, gate)
    gate.slider.move_to_position(300)  # the next user edit of the field removes it
    assert not gate.note.isVisibleTo(p)


def test_a_typed_fraction_in_a_whole_number_field_is_rounded_with_a_note(make_panel):
    p = make_panel("bass")
    p.advanced.set_expanded(True)
    note = p.controls["note"]
    type_in(note, "43,6")
    assert note.value() == 44 and visible_note(p, note)
    assert "keine ganze Zahl" in note.note.text()
    p.chips.buttons[0].click()  # a preset change clears the old remark
    assert not note.note.isVisibleTo(p)


def test_switching_a_dot_off_that_breaks_a_partner_moves_the_partner(make_panel):
    p = make_panel("rim")
    f1, hp = p.controls["f1_hz"], p.controls["hp_hz"]
    type_in(f1, "3500")
    type_in(hp, "2800")  # hp_hz < 0.8 * 3500
    assert p.model.is_valid
    f1.dot.setChecked(False)  # f1_hz falls back to 455 Hz: hp_hz 2800 would be refused
    assert p.model.is_valid and "f1_hz" not in p.model.active
    assert hp.value() < 364.01  # moved to what 0.8 * 455 allows
    assert "Hochpass wurde auf" in p.link_label.text()
    assert "Frequenz 1" in p.link_label.text()
    assert "außerhalb" not in hp.note.text()  # no stale remark about the old typed value


def test_changing_the_sample_rate_moves_a_filter_that_would_pass_nyquist(make_panel):
    p = make_panel("bass")
    p.advanced.set_expanded(True)
    lp = p.controls["lp_hz"]
    type_in(lp, "4000")
    assert p.model.is_valid
    amount = p.controls["lp_env_amount"]
    type_in(amount, "2.5")  # cutoff at t = 0: lp_hz * 2^2.5 must stay under 0.45 * sample_rate
    assert p.model.is_valid
    p.controls["sample_rate"].seg.buttons[0].click()  # 44100
    assert p.model.text["sample_rate"] == "44100" and p.model.is_valid
    assert "Samplerate" in p.link_label.text() or "Tiefpass" in p.link_label.text()


def test_a_refused_combination_that_cannot_be_repaired_still_blocks_render(qapp, tmp_path):
    from gui.main_window import MainWindow

    class Quiet:
        available = True

        def play(self, wav_path):
            pass

        def stop(self):
            pass

    w = MainWindow(out_dir=tmp_path / "out", backend=Quiet(), opener=lambda p: True)
    w.show()
    try:
        w.categories.setCurrentRow(CATEGORY_KEYS.index("bass"))
        # set programmatically, as no control can produce it any more
        w.model.set_active("hp_hz", True)
        w.model.set_text("hp_hz", "120")
        w.panel.changed.emit()
        assert not w.render_button.isEnabled()
        assert "Rendern nicht möglich" in w.status.text()
        assert "Ungültige Kombination" in w.status.text()
        w.start_render()
        assert w.handle is None
    finally:
        w.close()


# The laser form has 4x the numeric fields of the others, so every edit re-checks far more
# limits (about 0.2 s per edit on Linux, 0.5 s on the Windows runner): three seeds, not seven,
# keep the Windows job inside its 20 minutes (CI run 42150106875 was cancelled at the limit;
# the cost itself is issue #434).
_SEEDS = (1, 2, 3, 4, 5, 6, 4242)
_RANDOM_CASES = [(c, s) for c in CATEGORY_KEYS for s in ((1, 2, 4242) if c == "laser" else _SEEDS)]


@pytest.mark.parametrize(("category", "seed"), _RANDOM_CASES,
                         ids=[f"{c}-{s}" for c, s in _RANDOM_CASES])
def test_random_actions_with_dots_choices_and_presets_keep_the_form_accepted(make_panel, category,
                                                                              seed):
    """Property: drags, typed values (also far outside), dot toggles, enum and switch clicks and
    preset changes never leave a combination the engine refuses (200 actions per run)."""
    from gui.widgets import BoolControl, ChoiceControl

    rng = random.Random(f"{category}-{seed}")
    p = make_panel(category)
    numbers = [c for n, c in p.controls.items() if isinstance(c, NumberControl)
               and n != "variants"]
    choices = [c for c in p.controls.values() if isinstance(c, ChoiceControl | BoolControl)]
    for step in range(200):
        r = rng.random()
        if r < 0.30:
            c = rng.choice(numbers)
            c.slider.move_to_position(rng.randint(0, c.vmap.pos_max))
        elif r < 0.50:
            c = rng.choice(numbers)
            lo, hi = c.vmap.minimum, c.vmap.maximum
            type_in(c, repr(round(rng.uniform(lo - (hi - lo), hi + (hi - lo)), 3)))
        elif r < 0.75:
            c = rng.choice(numbers)
            c.dot.setChecked(not c.dot.isChecked())
        elif r < 0.92 and choices:
            c = rng.choice(choices)
            if isinstance(c, ChoiceControl):
                c.seg.buttons[rng.randrange(len(c.seg.buttons))].click()
            else:
                c.toggle.setChecked(not c.toggle.isChecked())
        else:
            p.chips.buttons[rng.randrange(len(p.chips.buttons))].click()
        assert p.model.issues() == [], (category, seed, step, p.model.issues())
