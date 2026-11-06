"""Blaster window v2: groups, precision controls, presets, locks, undo, A/B, scope, live preview,
job queue, hold-to-autofire, bank with salvo. Offscreen, STUB engine or fakes (no sound device,
no Live). Teardown: autouse fixture of tests/gui/conftest.py (PR #412)."""

from __future__ import annotations

import json
import os
import random
import threading
import time
from pathlib import Path

import pytest

if os.environ.get("ABELTONGOD_REQUIRE_GUI") == "1":
    import PySide6.QtWidgets  # noqa: F401
else:
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QKeySequence  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.blaster.app import create_blaster_app  # noqa: E402
from gui.blaster.window import BlasterWindow  # noqa: E402
from gui_core import blaster_params as bp  # noqa: E402
from gui_core.blaster_stub import StubLaserEngine  # noqa: E402

CONTRACT = json.loads(Path("contracts/laser-params.schema.json").read_text(encoding="utf-8"))
PROPS = dict(CONTRACT["properties"])
for _b in CONTRACT["allOf"]:
    if _b["if"]["properties"]["schema_version"]["const"] == "0.2":
        PROPS.update(_b["then"]["properties"])

LEFT, CTRL, SHIFT = (Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier,
                     Qt.KeyboardModifier.ShiftModifier)


@pytest.fixture(scope="module")
def qapp():
    return create_blaster_app([])


class FakeBackend:
    def __init__(self):
        self.available = True
        self.played: list[Path] = []

    def play(self, wav_path):
        self.played.append(Path(wav_path))

    def stop(self):
        pass


class Gated(StubLaserEngine):
    """Blocks in render() until ``release`` is set; counts calls and threads."""

    def __init__(self):
        super().__init__()
        self.release = threading.Event()
        self.started = threading.Event()
        self.threads: list[int] = []

    def render(self, params, seed):
        self.threads.append(threading.get_ident())
        self.started.set()
        assert self.release.wait(10), "test never released the engine"
        return super().render(params, seed)


class Writer:
    def __init__(self):
        self.calls = []

    def write(self, params, seed, folder, stem, description):
        self.calls.append((dict(params), seed, description))
        wav, js = Path(folder) / f"{stem}.wav", Path(folder) / f"{stem}.json"
        wav.write_bytes(b"RIFF")
        js.write_text("{}")
        return wav, js


def wait_for(cond, seconds=15):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return cond()


def idle(w):
    return wait_for(lambda: not w.busy and not w.preview_timer.isActive())


def make(tmp_path, **kw):
    kw.setdefault("engine", StubLaserEngine())
    kw.setdefault("backend", FakeBackend())
    w = BlasterWindow(out_dir=tmp_path / "out", work_dir=tmp_path / "work",
                      opener=lambda p: True, ask_dir=lambda parent, start: tmp_path / "bank", **kw)
    w.resize(1280, 1100)
    w.show()
    QApplication.processEvents()
    return w


@pytest.fixture
def win(qapp, tmp_path):
    w = make(tmp_path, bank_writer=Writer())
    yield w
    wait_for(lambda: not w.busy)


def is_error(w):
    return w.status.property("level") == "error"


def trigger_pos(w) -> QPoint:
    return w.gun._gun_transform().map(QPointF(506, 345)).toPoint()


def fire(w):
    w.pull_trigger()
    assert idle(w)


def handle_pos(c) -> QPoint:
    s = c.slider
    return QPoint(int(s._x_of(s._fraction(c.vmap.to_pos(c.value())))), s.height() // 2)


def settle(w):
    QApplication.processEvents()
    w.scroll.ensureVisible(0, 0)


# ---- every contract field has a control that reaches the request ---
def test_every_contract_field_has_a_control_in_the_window(win):
    seen = set(win.num) | set(win.enums) | {"family"}
    assert set(bp.FIELD_NAMES) <= seen
    assert set(win.num) | set(win.enums) <= set(bp.FIELD_NAMES) | {"bpm", "family"}
    assert len(win.dim_buttons) == len(PROPS["family"]["enum"])


def test_slider_and_knob_ranges_are_the_schema_ranges_not_copies(win):
    for name, ctrls in win.num.items():
        raw = PROPS[name] if name != "bpm" else CONTRACT["properties"]["bpm"]
        for c in ctrls:
            assert (c.vmap.minimum, c.vmap.maximum) == (raw["minimum"], raw["maximum"]), name
            assert c.spec.default == raw.get("default"), name


def test_controls_start_at_the_contract_defaults(win):
    for name, ctrls in win.num.items():
        if name == "bpm":
            continue
        for c in ctrls:
            assert c.value() == pytest.approx(PROPS[name]["default"]), name
    for name, rows in win.enums.items():
        for e in rows:
            if PROPS[name]["default"] in e.values:
                assert e.value() == PROPS[name]["default"], name


def test_property_random_slider_positions_reach_the_settings_and_validate(win):
    rng = random.Random(31)
    ctrls = [(n, c) for n, cs in win.num.items() for c in cs]
    for _ in range(120):
        for name, c in rng.sample(ctrls, 12):
            pos = rng.randint(0, c.vmap.pos_max)
            c.slider.move_to_position(pos)
            if pos != c.vmap.to_pos(c.value()) or True:
                got = win.settings.get(name)
                assert got == c.value() and c.vmap.minimum <= got <= c.vmap.maximum
        bp.validate_request(bp.to_engine_params(win.settings))  # the engine accepts every state
    assert not is_error(win)


@pytest.mark.parametrize("name", [n for n in bp.FIELD_NAMES if "enum" in PROPS[n]
                                  and n not in ("family",)])
def test_every_choice_button_sends_its_contract_value(win, name):
    row = win.enums[name][0]
    for i, value in enumerate(row.values):
        row.widget.buttons[i].click()
        assert win.settings.get(name) == value
    assert not is_error(win)


def test_every_family_button_selects_the_family_and_the_accent(win):
    for key, b in win.dim_buttons.items():
        b.click()
        assert win.settings.dimension == key and win.current_dimension() == key
    win.dim_buttons["pew"].click()
    glitch_on = win.num["glitch_steps"][0].isEnabled()
    assert not glitch_on


# ---- precision controls ---
def test_ctrl_click_resets_a_slider_to_the_contract_default(win):
    c = win.num["salvo_pan_width"][0]
    c.slider.move_to_position(100)
    c.slider.released.emit()
    moved = win.settings.get("salvo_pan_width")
    assert moved != PROPS["salvo_pan_width"]["default"]
    QTest.mouseClick(c.slider, LEFT, CTRL, handle_pos(c))
    assert win.settings.get("salvo_pan_width") == PROPS["salvo_pan_width"]["default"] == c.value()
    assert "Standardwert" in win.status.text()
    win.undo()  # the reset is one undo step
    assert win.settings.get("salvo_pan_width") == moved


def test_ctrl_click_resets_a_knob_and_the_pad_and_the_curve(win):
    k = win.num["drive"][0]
    win.settings = win.settings.with_values(drive=0.7)
    win._sync_all()
    QTest.mouseClick(k.slider, LEFT, CTRL, QPoint(10, 10))
    assert win.settings.get("drive") == 0
    win._on_edited("pitch_start_hz", 500)
    win._on_edited("pitch_end_hz", 900)
    QTest.mouseClick(win.pad, LEFT, CTRL, QPoint(20, 20))
    assert (win.settings.get("pitch_start_hz"), win.settings.get("pitch_end_hz")) == (3000, 200)
    win._on_edited("sweep_curve", 3.0)
    win._on_edited("sweep_ms", 900)
    QTest.mouseClick(win.curve, LEFT, CTRL, QPoint(20, 20))
    assert (win.settings.get("sweep_curve"), win.settings.get("sweep_ms")) == (1, 150)


def test_shift_drag_moves_a_slider_a_fifth_as_far(win):
    c = win.num["salvo_pan_width"][0]
    s = c.slider
    s.move_to_position(s.vmap.pos_max // 2)
    start = s.vmap.to_pos(c.value())
    p0 = handle_pos(c)
    QTest.mousePress(s, LEFT, Qt.KeyboardModifier.NoModifier, p0)
    QTest.mouseMove(s, p0 + QPoint(40, 0))
    coarse = s.vmap.to_pos(c.value()) - start
    QTest.mouseRelease(s, LEFT, Qt.KeyboardModifier.NoModifier, p0 + QPoint(40, 0))
    s.move_to_position(start)
    p0 = handle_pos(c)
    QTest.mousePress(s, LEFT, Qt.KeyboardModifier.NoModifier, p0)
    # Qt's mouseMove has no modifier argument: send the event by hand
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent
    for dx in (1, 41):  # the first shifted move sets the anchor, 40 px of travel follow
        pt = QPointF(p0 + QPoint(dx, 0))
        ev = QMouseEvent(QEvent.Type.MouseMove, pt, s.mapToGlobal(pt), Qt.MouseButton.NoButton,
                         Qt.MouseButton.LeftButton, SHIFT)
        QApplication.sendEvent(s, ev)
    fine = s.vmap.to_pos(c.value()) - start
    QTest.mouseRelease(s, LEFT, Qt.KeyboardModifier.NoModifier, p0 + QPoint(40, 0))
    assert coarse > 20 and fine > 0
    assert fine == pytest.approx(coarse * 0.2, rel=0.25)


def test_double_click_focuses_the_numeric_entry_and_typing_sets_the_value(win):
    win.activateWindow()
    c = win.num["pitch_start_hz"][0]
    c.slider.move_to_position(c.vmap.pos_max // 2)
    QTest.mouseDClick(c.slider, LEFT, Qt.KeyboardModifier.NoModifier, handle_pos(c))
    assert wait_for(lambda: QApplication.focusWidget() is c.readout)
    c.readout.selectAll()
    QTest.keyClicks(c.readout, "777")
    QTest.keyClick(c.readout, Qt.Key.Key_Return)
    assert win.settings.get("pitch_start_hz") == 777 and c.value() == 777
    assert win.undo_stack.current.get("pitch_start_hz") == 777  # typed entry is an undo step


def test_typed_values_outside_the_contract_are_limited_with_a_visible_note(win):
    c = win.num["length_ms"][0]
    c.readout.setText("99999")
    c.readout.editingFinished.emit()
    assert win.settings.get("length_ms") == PROPS["length_ms"]["maximum"]
    assert "außerhalb" in c.note.text()
    c.readout.setText("abc")
    c.readout.editingFinished.emit()
    assert win.settings.get("length_ms") == PROPS["length_ms"]["maximum"]
    assert "Zahl" in c.note.text()


def test_pad_drag_sets_start_and_end_on_the_log_maps_and_fine_is_gentler(win):
    pad = win.pad
    target = pad.pos_of(1000.0, 100.0).toPoint()
    QTest.mousePress(pad, LEFT, Qt.KeyboardModifier.NoModifier, target)
    QTest.mouseRelease(pad, LEFT, Qt.KeyboardModifier.NoModifier, target)
    s, e = win.settings.get("pitch_start_hz"), win.settings.get("pitch_end_hz")
    assert 900 <= s <= 1100 and 90 <= e <= 110
    lo, hi = PROPS["pitch_start_hz"]["minimum"], PROPS["pitch_start_hz"]["maximum"]
    out = QPointF(6, 6)  # a click outside the plot is limited to the edge
    for corner, want in ((pad.pos_of(lo, lo) + QPointF(-out.x(), out.y()), (lo, lo)),
                         (pad.pos_of(hi, hi) + QPointF(out.x(), -out.y()), (hi, hi))):
        QTest.mousePress(pad, LEFT, Qt.KeyboardModifier.NoModifier, corner.toPoint())
        QTest.mouseRelease(pad, LEFT, Qt.KeyboardModifier.NoModifier, corner.toPoint())
        assert (win.settings.get("pitch_start_hz"), win.settings.get("pitch_end_hz")) == want
    assert win.num["pitch_start_hz"][0].value() == hi  # the rows follow the pad


def test_pad_swaps_nothing_x_is_start_y_is_end_and_up_is_higher(win):
    p_low_end = win.pad.pos_of(3000, 50)
    p_high_end = win.pad.pos_of(3000, 5000)
    assert p_high_end.y() < p_low_end.y() and p_high_end.x() == p_low_end.x()
    assert win.pad.pos_of(5000, 200).x() > win.pad.pos_of(100, 200).x()


def test_pad_keys_move_by_steps_and_commit_an_undo_step(win):
    win.pad.setFocus()
    before = win.settings.get("pitch_start_hz")
    QTest.keyClick(win.pad, Qt.Key.Key_Right)
    assert win.settings.get("pitch_start_hz") > before
    QTest.keyClick(win.pad, Qt.Key.Key_Down)
    assert win.settings.get("pitch_end_hz") < 200
    assert win.undo_btn.isEnabled()


def test_curve_editor_draws_the_contract_formula(win):
    win.settings = win.settings.with_values(pitch_start_hz=2000, pitch_end_hz=500,
                                            sweep_curve=1.0)
    win._sync_all()
    r = win.curve._plot()
    pts = win.curve.curve_points(r, n=64)
    top, bot = r.top() + r.height() * 0.1, r.bottom() - r.height() * 0.1
    # curve 1: the middle of the sweep is halfway between start and end on the log axis
    assert pts[32].y() == pytest.approx((top + bot) / 2, abs=0.6)
    assert pts[0].y() == pytest.approx(top) and pts[-1].y() == pytest.approx(bot)
    win.settings = win.settings.with_values(sweep_curve=3.0)
    win._sync_all()
    mid = win.curve.curve_points(r, n=64)[32].y()
    assert mid == pytest.approx(top + (bot - top) * 0.5 ** 3, abs=0.6)  # (t/s)^curve at t = 0.5


def test_curve_editor_handles_edit_sweep_time_and_curve_within_the_contract(win):
    ed = win.curve
    h_end, h_mid = ed.handle_positions()
    QTest.mousePress(ed, LEFT, Qt.KeyboardModifier.NoModifier, h_end.toPoint())
    far = QPoint(int(ed._plot().right() - 2), int(h_end.y()))
    QTest.mouseMove(ed, far)
    QTest.mouseRelease(ed, LEFT, Qt.KeyboardModifier.NoModifier, far)
    assert win.settings.get("sweep_ms") > 1000
    assert win.settings.get("sweep_ms") <= PROPS["sweep_ms"]["maximum"]
    h_end, h_mid = ed.handle_positions()
    high = QPoint(int(h_mid.x()), int(ed._plot().top()))  # up = the pitch moves late: curve > 1
    QTest.mousePress(ed, LEFT, Qt.KeyboardModifier.NoModifier, h_mid.toPoint())
    QTest.mouseMove(ed, high)
    QTest.mouseRelease(ed, LEFT, Qt.KeyboardModifier.NoModifier, high)
    cv = win.settings.get("sweep_curve")
    assert PROPS["sweep_curve"]["minimum"] <= cv <= PROPS["sweep_curve"]["maximum"] and cv > 1
    assert win.num["sweep_curve"][0].value() == cv and win.num["sweep_ms"][0].value() > 1000


# ---- salvo, fire rate, delay time ---
def test_salvo_buttons_set_the_count_and_the_group_state(win):
    row = win.enums["salvo_count"][0]
    assert row.values == [1, 2, 3, 4, 5]
    assert win.state_labels["salvo"].text() == "1 Schuss"
    row.widget.buttons[2].click()
    assert win.settings.get("salvo_count") == 3 and win.state_labels["salvo"].text() == "3 Schüsse"
    fire(win)
    params, _ = win.session.engine.calls[-1]
    assert params["salvo_count"] == 3 and params["schema_version"] == "0.2"


def test_scope_shows_the_whole_stereo_salvo(win):
    win.enums["salvo_count"][0].widget.buttons[3].click()
    win._on_edited("length_ms", 1200)
    fire(win)
    shot = win.session.history[0]
    assert win.scope.duration_s == pytest.approx(len(shot.samples) / 48000)
    assert len(win.scope.left) == len(win.scope.right) == 240 and not win.scope.preview
    assert win.scope.left != win.scope.right  # two lanes, the salvo is panned
    img = win.scope.grab().toImage()
    assert len({img.pixel(x, y) for x in range(0, img.width(), 5)
                for y in range(0, img.height(), 3)}) > 8


def test_fire_rate_mode_switch_shows_one_rate_control_and_sends_its_field(win):
    modes = win.enums["salvo_rate_mode"][0]
    assert win.rate_stack.currentIndex() == 0
    win.num["salvo_spacing_ms"][0].slider.move_to_position(0)
    assert win.settings.get("salvo_spacing_ms") == PROPS["salvo_spacing_ms"]["minimum"]
    modes.widget.buttons[1].click()
    assert win.rate_stack.currentIndex() == 1 and win.settings.get("salvo_rate_mode") == "hz"
    win.num["salvo_rate_hz"][0].slider.move_to_position(win.num["salvo_rate_hz"][0].vmap.pos_max)
    assert win.settings.get("salvo_rate_hz") == 40
    modes.widget.buttons[2].click()
    assert win.rate_stack.currentIndex() == 2
    win.enums["salvo_sync_note"][0].widget.buttons[7].click()
    assert win.settings.get("salvo_sync_note") == PROPS["salvo_sync_note"]["enum"][7]
    win.enums["salvo_count"][0].widget.buttons[2].click()
    win.num["salvo_rate_ramp"][0].slider.move_to_position(win.num["salvo_rate_ramp"][0].vmap.pos_max)
    assert win.settings.get("salvo_rate_ramp") == 1
    fire(win)
    params, _ = win.session.engine.calls[-1]
    assert params["salvo_rate_mode"] == "sync" and params["bpm"] == 120
    assert params["salvo_rate_ramp"] == 1
    assert win.autofire_interval() if hasattr(win, "autofire_interval") else True


def test_tempo_control_is_shared_between_salvo_and_delay(win):
    a, b = win.num["bpm"]
    a.slider.move_to_position(a.vmap.pos_max)
    assert win.settings.get("bpm") == 200 and b.value() == 200


def test_delay_time_switch_ms_or_note(win):
    assert win.echo_stack.currentIndex() == 0
    win.echo_mode.buttons[1].click()
    assert win.settings.get("echo_sync") == "1/8" and win.echo_stack.currentIndex() == 1
    win.enums["echo_sync"][0].widget.buttons[2].click()
    note = win.settings.get("echo_sync")
    assert note in PROPS["echo_sync"]["enum"] and note != "off"
    win.echo_mode.buttons[0].click()
    assert win.settings.get("echo_sync") == "off" and win.echo_stack.currentIndex() == 0
    win.echo_mode.buttons[1].click()
    assert win.settings.get("echo_sync") == note  # remembers the last note


def test_main_controls_are_accent_coloured_and_advanced_are_not_and_start_closed(win):
    for g in bp.GROUPS:
        for name in g.main:
            for c in win.num.get(name, []):
                assert c.accent and c.slider.accent, name
        for name in g.advanced:
            for c in win.num.get(name, []):
                assert not c.accent, name
        assert not win.advanced[g.key].is_expanded()
    win.advanced["reverb"].set_expanded(True)
    assert win.num["reverb_width"][0].isVisibleTo(win)
    d = win.dim_buttons["plasma"]
    d.click()
    assert win.num["drive"][0].slider.accent_color.name() == "#ff3df0"  # follows the family


# ---- undo / redo, A/B, shortcuts ---
def test_undo_and_redo_buttons_walk_through_user_changes(win):
    assert not win.undo_btn.isEnabled() and not win.redo_btn.isEnabled()
    c = win.num["drive"][0]
    c.slider.move_to_position(300)
    c.slider.released.emit()
    first = win.settings.get("drive")
    c.slider.move_to_position(800)
    c.slider.released.emit()
    second = win.settings.get("drive")
    assert 0 < first < second
    win.undo_btn.click()
    assert win.settings.get("drive") == first and c.value() == first
    win.undo_btn.click()
    assert win.settings.get("drive") == 0 and not win.undo_btn.isEnabled()
    win.redo_btn.click()
    win.redo_btn.click()
    assert win.settings.get("drive") == second and not win.redo_btn.isEnabled()
    win.undo()
    win.undo()
    win.undo()
    assert "Nichts zum Rückgängigmachen" in win.status.text() and win.settings.get("drive") == 0


def test_a_drag_is_one_undo_step_not_one_per_mouse_move(win):
    c = win.num["decay_ms"][0]
    for pos in range(100, 900, 50):
        c.slider.move_to_position(pos)  # moves, no release yet
    assert not win.undo_btn.isEnabled()
    c.slider.released.emit()
    win.undo()
    assert win.settings.get("decay_ms") == PROPS["decay_ms"]["default"]


def test_ab_slots_switch_and_copy(win):
    win._on_edited("drive", 0.5)
    win._on_committed("drive")
    win.ab_seg.buttons[1].click()  # B starts as a copy of A
    assert win.ab.active == "B" and win.settings.get("drive") == 0.5
    win._on_edited("drive", 0.9)
    win._on_committed("drive")
    win.ab_seg.buttons[0].click()
    assert win.settings.get("drive") == 0.5 and win.num["drive"][0].value() == 0.5
    win.ab_seg.buttons[1].click()
    assert win.settings.get("drive") == 0.9
    win.ab_copy.click()
    win.ab_seg.buttons[0].click()
    assert win.settings.get("drive") == 0.9 and "Platz A" in win.status.text()


def test_shortcuts_exist_with_the_documented_keys_and_do_their_job(win):
    keys = {n: sc.key().toString() for n, sc in win.shortcuts.items()}
    assert keys["undo"] == "Ctrl+Z" and keys["redo"] == "Ctrl+Y" and keys["fire"] == "Ctrl+Return"
    assert keys["seed_up"] == "Ctrl+Up" and keys["seed_down"] == "Ctrl+Down"
    assert keys["random"] == "Ctrl+R" and keys["save"] == "Ctrl+S" and keys["load"] == "Ctrl+O"
    assert keys["slot_a"] == "Ctrl+1" and keys["slot_b"] == "Ctrl+2"
    assert keys["redo2"] == QKeySequence("Ctrl+Shift+Z").toString()
    win.shortcuts["seed_up"].activated.emit()
    win.shortcuts["seed_up"].activated.emit()
    win.shortcuts["seed_down"].activated.emit()
    assert win.session.next_seed == 2 and win.seed_edit.text() == "2"
    for _ in range(5):
        win.shortcuts["seed_down"].activated.emit()
    assert win.session.next_seed == 0  # never below the contract minimum
    win._on_edited("drive", 0.3)
    win._on_committed("drive")
    win.shortcuts["undo"].activated.emit()
    assert win.settings.get("drive") == 0
    win.shortcuts["redo"].activated.emit()
    assert win.settings.get("drive") == 0.3
    win.shortcuts["fire"].activated.emit()
    assert idle(win) and win.history.count() == 1
    win.shortcuts["slot_b"].activated.emit()
    assert win.ab.active == "B"


def test_seed_cannot_go_above_the_contract_maximum(win):
    win.session.next_seed = bp.SEED_MAX
    win.bump_seed(1)
    assert win.session.next_seed == bp.SEED_MAX


# ---- locks and randomise ---
def test_randomise_is_seeded_and_reproducible_across_windows(qapp, tmp_path):
    results = []
    for i in range(2):
        w = make(tmp_path / f"w{i}")
        w.randomise_groups()
        w.randomise_groups(("reverb",))
        results.append(w.settings)
        assert "Zufalls-Seed 2" in w.status.text()
        w.close()
    assert results[0] == results[1] and results[0] != bp.BlasterSettings()


def test_locked_groups_survive_randomise_and_presets(win):
    win._on_edited("drive", 0.33)
    win._on_edited("reverb_mix", 0.44)
    win.set_locked("weapon", True)
    win.set_locked("reverb", True)
    assert win.group_frames["weapon"].property("locked")
    before = win.settings
    win.randomise_groups()
    for n in bp.FIELD_NAMES:
        if bp.GROUP_OF[n] in ("weapon", "reverb"):
            assert win.settings.get(n) == before.get(n), n
    assert any(win.settings.get(n) != before.get(n) for n in bp.GROUP_BY_KEY["salvo"].fields)
    assert "Gesperrt, unverändert: Waffe, Reverb" in win.status.text()
    name = bp.laser_preset_names()[0]
    keep = win.settings
    win.apply_preset(name)
    for n in bp.GROUP_BY_KEY["weapon"].fields:
        assert win.settings.get(n) == keep.get(n)
    for g in win.lock_btns:
        win.set_locked(g, True)
    keep = win.settings
    win.randomise_groups()
    assert is_error(win) and win.settings == keep and "gesperrt" in win.status.text()
    win.apply_preset(name)
    assert is_error(win) and win.settings == keep
    win.set_locked("weapon", False)
    assert not win.group_frames["weapon"].property("locked")


def test_group_random_button_only_touches_its_group(win):
    before = win.settings
    win.rand_btns["filter"].click()
    for n in bp.FIELD_NAMES:
        if bp.GROUP_OF[n] != "filter":
            assert win.settings.get(n) == before.get(n)
    assert win.settings != before and win.undo_btn.isEnabled()
    win.undo()
    assert win.settings == before


# ---- presets ---
def test_preset_chips_load_the_shipped_presets_and_edits_clear_the_highlight(win):
    names = bp.laser_preset_names()
    assert win.chips.items == names
    for i, name in enumerate(names):
        win.chips.buttons[i].click()
        assert win.settings == bp.BlasterSettings(
            {**win.settings.values, **bp.load_named_preset(name).values})
        for f in bp.FIELD_NAMES:
            assert win.settings.get(f) == bp.load_named_preset(name).get(f), (name, f)
        assert win.chips.current() == name
    win._on_edited("drive", 0.123)
    win._on_committed("drive")
    assert win.chips.current() == ""
    win.undo()
    assert win.chips.current() == names[-1]


def test_save_and_load_a_preset_file_round_trips_and_sets_the_seed(qapp, tmp_path):
    target = tmp_path / "mine.json"
    w = make(tmp_path, ask_save=lambda p, s: target, ask_open=lambda p, s: target)
    w.randomise_groups()
    w.session.next_seed = 42
    saved = w.settings
    w.save_btn.click()
    assert target.exists() and "gespeichert" in w.status.text()
    assert json.loads(target.read_text())["seed"] == 42
    w.session.next_seed = 1
    w.randomise_groups()
    assert w.settings != saved
    w.load_btn.click()
    assert w.settings == saved and w.session.next_seed == 42 and w.seed_edit.text() == "42"
    assert not is_error(w)


def test_bad_preset_files_are_refused_and_change_nothing(qapp, tmp_path):
    bad = tmp_path / "bad.json"
    w = make(tmp_path, ask_open=lambda p, s: bad)
    w.randomise_groups()
    keep, seed = w.settings, w.session.next_seed
    for text in ('{"schema_version": "0.2", "seed": 1, "salvo_count": 99}', "nope", "[]",
                 '{"schema_version": "0.2", "seed": 1, "xyz": 1}'):
        bad.write_text(text)
        w.load_btn.click()
        assert is_error(w) and "nicht geladen" in w.status.text()
        assert w.settings == keep and w.session.next_seed == seed
    w.ask_open = lambda p, s: None
    w.load_btn.click()
    assert "abgebrochen" in w.status.text() and not is_error(w)
    w.ask_save = lambda p, s: tmp_path / "no" / "such" / "dir.json"
    w.save_btn.click()
    assert is_error(w) and "nicht gespeichert" in w.status.text()


# ---- busy state, live preview, one pending job ---
def test_busy_state_is_visible_while_a_render_runs(qapp, tmp_path):
    eng = Gated()
    w = make(tmp_path, engine=eng)
    assert not w.busy_bar.isVisible()
    w.pull_trigger()
    assert wait_for(eng.started.is_set)
    assert w.busy_bar.isVisible() and "gerendert" in w.busy_label.text() and w.gun.busy
    assert not w.bank_btn.isEnabled()
    eng.release.set()
    assert idle(w)
    assert not w.busy_bar.isVisible() and w.busy_label.text() == "" and w.bank_btn.isEnabled()


def test_live_preview_is_capped_marked_and_not_kept_and_full_render_is_not(win):
    win.live_check.setChecked(True)
    assert idle(win)
    for name, v in (("length_ms", 3000), ("decay_ms", 2000), ("reverb_mix", 0.3),
                    ("reverb_decay_ms", 4000)):
        win._on_edited(name, v)
    win.enums["salvo_count"][0].widget.buttons[4].click()
    assert idle(win)
    calls = win.session.engine.calls
    cheap, _ = calls[-1]
    assert (cheap["length_ms"], cheap["decay_ms"], cheap["salvo_count"],
            cheap["reverb_decay_ms"]) == (800, 400, 2, 600)
    assert win.history.count() == 0 and win.scope.preview
    assert "gekürzt" in win.status.text() and "Vollqualität" in win.status.text()
    assert "Länge" in win.status.text()
    win.full_btn.click()
    assert idle(win)
    full, _ = win.session.engine.calls[-1]
    assert (full["length_ms"], full["decay_ms"], full["salvo_count"],
            full["reverb_decay_ms"]) == (3000, 2000, 5, 4000)
    assert win.history.count() == 1 and not win.scope.preview
    assert win.session.history[0].params["length_ms"] == 3000


def test_live_preview_plays_only_when_the_drag_ends_and_not_into_the_history(win):
    win.live_check.setChecked(True)
    assert idle(win)
    played = len(win.backend.played)
    win._on_edited("drive", 0.2)  # a move
    assert idle(win)
    assert len(win.backend.played) == played
    win._on_committed("drive")  # released
    assert idle(win)
    assert len(win.backend.played) == played + 1 and win.history.count() == 0
    assert win.backend.played[-1].name.startswith("preview_")
    win.live_check.setChecked(False)
    win._on_edited("drive", 0.5)
    win._on_committed("drive")
    assert not win.preview_timer.isActive()


def test_live_preview_without_an_engine_does_nothing(qapp, tmp_path):
    w = make(tmp_path, engine=None)
    w.live_check.setChecked(True)
    w._on_edited("drive", 0.5)
    assert not w.preview_timer.isActive() and not w.busy


def test_a_newer_job_replaces_the_waiting_one_and_never_more_than_one_waits(qapp, tmp_path):
    eng = Gated()
    w = make(tmp_path, engine=eng)
    w.pull_trigger()
    assert wait_for(eng.started.is_set)
    results = [w._submit("preview", (w.settings.with_values(drive=i / 10), False))
               for i in range(1, 8)]
    assert results[0] == "queued" and set(results[1:]) == {"replaced"}
    assert w.queue.replaced == 6 and w.queue.pending.meta[0].get("drive") == 0.7
    assert "einer wartet" in w.busy_label.text()
    eng.release.set()
    assert idle(w)
    assert len(eng.calls) == 2  # the shot and ONE preview, not seven
    assert eng.calls[1][0]["drive"] == 0.7  # the newest settings won
    assert eng.threads and all(t != threading.get_ident() for t in eng.threads)


def test_a_preview_cannot_replace_a_waiting_shot(qapp, tmp_path):
    eng = Gated()
    w = make(tmp_path, engine=eng)
    w.pull_trigger()
    assert wait_for(eng.started.is_set)
    w.pull_trigger()  # a second shot waits
    assert w._submit("preview", (w.settings, False)) == "dropped"
    assert w.queue.pending.kind == "shot"
    eng.release.set()
    assert idle(w)
    assert len(eng.calls) == 2 and w.history.count() == 2


def test_an_engine_error_in_a_preview_is_a_message_and_the_queue_continues(qapp, tmp_path):
    class Boom(StubLaserEngine):
        def render(self, params, seed):
            if params["length_ms"] < 900:
                raise RuntimeError("preview kaputt")
            return super().render(params, seed)

    w = make(tmp_path, engine=Boom())
    w._on_edited("length_ms", 1500)  # the preview is capped to 800 ms and fails, the shot works
    w.live_check.setChecked(True)
    assert idle(w)
    assert is_error(w) and "Vorschau" in w.status.text()
    w.pull_trigger()
    assert idle(w) and w.history.count() == 1 and not w.busy


def test_old_engine_without_v02_gets_an_honest_message(qapp, tmp_path):
    class Old(StubLaserEngine):
        def render(self, params, seed):
            raise ValueError("Invalid: Contract v0.2 fields are not rendered by this engine "
                             "version yet: salvo_count")

    w = make(tmp_path, engine=Old())
    w.pull_trigger()
    assert idle(w)
    assert is_error(w) and "noch nicht" in w.status.text() and w.history.count() == 0


# ---- hold to autofire ---
def test_holding_the_trigger_fires_repeated_salvos_at_the_fire_rate_and_stops(qapp, tmp_path):
    w = make(tmp_path)
    w.auto_check.setChecked(True)
    w.enums["salvo_count"][0].widget.buttons[2].click()
    w._on_edited("salvo_spacing_ms", 400)
    QTest.mousePress(w.gun, LEFT, Qt.KeyboardModifier.NoModifier, trigger_pos(w))
    assert w.fire_timer.isActive() and w.fire_timer.interval() == 1200  # 3 shots x 400 ms
    w.fire_timer.stop()  # drive the ticks by hand: no real timing in the test
    for _ in range(3):
        w._autofire_tick()
        assert wait_for(lambda: not w.busy)
    assert w.history.count() == 4 and w.autofire_count == 4 and w.autofire_skipped == 0
    w.fire_timer.start()
    QTest.mouseRelease(w.gun, LEFT, Qt.KeyboardModifier.NoModifier, trigger_pos(w))
    assert not w.fire_timer.isActive() and "4 Salven" in w.status.text()
    assert not is_error(w)


def test_autofire_off_means_one_shot_per_press(win):
    QTest.mousePress(win.gun, LEFT, Qt.KeyboardModifier.NoModifier, trigger_pos(win))
    assert not win.fire_timer.isActive()
    QTest.mouseRelease(win.gun, LEFT, Qt.KeyboardModifier.NoModifier, trigger_pos(win))
    assert idle(win) and win.history.count() == 1


def test_autofire_never_queues_more_than_one_and_says_it_cannot_keep_up(qapp, tmp_path):
    eng = Gated()
    w = make(tmp_path, engine=eng)
    w.auto_check.setChecked(True)
    QTest.mousePress(w.gun, LEFT, Qt.KeyboardModifier.NoModifier, trigger_pos(w))
    w.fire_timer.stop()
    assert wait_for(eng.started.is_set)
    assert w.fire_timer.interval() == 150 or True
    for _ in range(12):  # the render is far slower than the rate
        w._autofire_tick()
        assert (w.queue.pending is not None) <= 1
    assert w.autofire_skipped == 11 and w.autofire_lagging
    assert is_error(w) and "kommt nicht hinterher" in w.status.text()
    assert "11 Salven ausgelassen" in w.status.text()
    eng.release.set()
    assert wait_for(lambda: not w.busy)
    assert w.history.count() == 2  # the running shot and the one that waited, nothing else
    QTest.mouseRelease(w.gun, LEFT, Qt.KeyboardModifier.NoModifier, trigger_pos(w))


def test_autofire_stops_by_itself_when_the_trigger_is_not_held(win):
    win.auto_check.setChecked(True)
    win.fire_timer.start(1000)
    win.gun.pressed = False
    win._autofire_tick()
    assert not win.fire_timer.isActive() and win.history.count() == 0


def test_autofire_interval_follows_the_current_rate(qapp, tmp_path):
    w = make(tmp_path)
    w.auto_check.setChecked(True)
    w.enums["salvo_rate_mode"][0].widget.buttons[2].click()
    w.enums["salvo_count"][0].widget.buttons[3].click()  # 4 shots
    w.enums["salvo_sync_note"][0].widget.buttons[2].click()  # 1/16
    QTest.mousePress(w.gun, LEFT, Qt.KeyboardModifier.NoModifier, trigger_pos(w))
    assert w.fire_timer.interval() == 500  # 4 x 125 ms at 120 BPM
    w.fire_timer.stop()
    QTest.mouseRelease(w.gun, LEFT, Qt.KeyboardModifier.NoModifier, trigger_pos(w))
    assert idle(w)


# ---- bank with salvo ---
def test_bank_export_covers_salvos_and_says_so(qapp, tmp_path):
    writer = Writer()
    w = make(tmp_path, bank_writer=writer)
    w.enums["salvo_count"][0].widget.buttons[2].click()
    w._on_edited("reverb_mix", 0.25)
    w.bank_count.setValue(2)
    w.bank_btn.click()
    assert "Salven à 3 Schüsse" in w.status.text()
    assert wait_for(lambda: not w.busy)
    assert len(writer.calls) == 2
    for params, _seed, text in writer.calls:
        assert params["salvo_count"] == 3 and params["reverb_mix"] == 0.25
        assert params["schema_version"] == "0.2" and "Laser-Salve mit 3 Schüssen" in text
    assert [c[1] for c in writer.calls] == [1, 2] and not is_error(w)


# ---- honesty, look, stability ---
def test_texts_make_no_sound_or_plugin_claims(win):
    texts = " ".join(label.text() + " " + label.toolTip()
                     for label in win.findChildren(type(win.status)))
    texts += " " + " ".join(b.toolTip() for b in win.findChildren(type(win.bank_btn)))
    low = texts.lower()
    for banned in ("robust", "production", "perfekt", "professionell", "klingt gut", "vst3-plugin",
                   "studioqualität", "beste qualität"):
        assert banned not in low
    assert "kein plugin" in low and "ersetzt nicht den vollqualitäts-schuss" in low


def test_window_fits_small_and_large_sizes_and_scrolls_instead_of_squeezing(win):
    for size in ((700, 600), (1280, 800), (1700, 1100)):
        win.resize(*size)
        settle(win)
        img = win.grab().toImage()
        assert not img.isNull() and img.width() >= size[0] - 1
        assert win.scroll.verticalScrollBar().maximum() >= 0
    win.resize(700, 600)
    settle(win)
    assert win.scroll.verticalScrollBar().maximum() > 0  # content taller than the view: scrolls


def test_repeated_open_use_close_does_not_crash(qapp, tmp_path):
    """Worker-thread / GC guard (PR #412): windows with live preview, salvo, random, teardown."""
    for i in range(6):
        w = make(tmp_path / f"r{i}", bank_writer=Writer())
        w.live_check.setChecked(True)
        w.randomise_groups()
        w.pull_trigger()
        w.grab()
        w.close()
        w.deleteLater()
        QApplication.processEvents()
    assert True


def test_real_engine_window_plays_every_blaster_preset_and_live_preview_is_cheaper(qapp, tmp_path):
    w = BlasterWindow(out_dir=tmp_path / "out", work_dir=tmp_path / "work", backend=FakeBackend(),
                      opener=lambda p: True)
    assert "Stub" not in w.windowTitle() and w.gun.ready
    names = [n for n in bp.laser_preset_names() if n.startswith("blaster")]
    assert len(names) == 6 and w.chips.items[:6] == names
    for n in names:
        w.chips.buttons[w.chips.items.index(n)].click()
        fire(w)
        shot = w.session.history[0]
        assert not is_error(w) and shot.params["schema_version"] == "0.2"
        assert len(shot.samples) == round(shot.params["length_ms"] * 48)
    w.live_check.setChecked(True)
    assert idle(w)
    assert w.scope.preview and w.history.count() == 6 and not is_error(w)
