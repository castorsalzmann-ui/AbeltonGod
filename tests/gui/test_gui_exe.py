"""#432: window navigation, laser form in the category panel, byte identity with the CLI and the
headless self test of the GUI (offscreen; the Windows look and the drop into Live are not
covered here)."""

from __future__ import annotations

import io
import json
import os
import time
from pathlib import Path

import pytest

if os.environ.get("ABELTONGOD_REQUIRE_GUI") == "1":  # CI: a missing Qt must fail, not skip
    import PySide6.QtWidgets  # noqa: F401
else:
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtWidgets import QWidget  # noqa: E402

from audio_engine import cli as engine_cli  # noqa: E402
from gui import selftest  # noqa: E402
from gui.app import create_app  # noqa: E402
from gui.main_window import MainWindow  # noqa: E402
from gui.widgets.choice import WrapSegmented  # noqa: E402
from gui.windows import DEFAULT_FACTORIES, WINDOW_KEYS, WindowManager  # noqa: E402
from gui_core.form import CATEGORY_KEYS, CategoryFormModel  # noqa: E402
from gui_core.form_layout import main_choices, main_controls  # noqa: E402
from gui_core.waveform import load_waveform  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return create_app([])


class FakeBackend:
    available = True

    def play(self, wav_path):
        pass

    def stop(self):
        pass


class Probe(QWidget):
    """A stand-in for one of the other windows (the real ones are tested in their own folders)."""

    made = 0

    def __init__(self):
        super().__init__()
        Probe.made += 1
        self.closed = False

    def closeEvent(self, event):  # noqa: N802
        self.closed = True
        super().closeEvent(event)


def probe_factories():
    return {key: _make_probe for key, _ in WINDOW_KEYS}


def _make_probe(out_dir):
    return Probe()


@pytest.fixture
def window(qapp, tmp_path):
    Probe.made = 0
    w = MainWindow(out_dir=tmp_path / "out", backend=FakeBackend(), opener=lambda p: True,
                   window_factories=probe_factories())
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


# --- navigation -------------------------------------------------------------------------------
def test_main_window_has_one_button_per_other_window(window):
    assert [b.text() for b in window.window_buttons.values()] == [
        "Goa-Fenster", "Acid-Linie", "Laser-Blaster"]


def test_button_opens_its_window_once_and_raises_it_again(window):
    window.window_buttons["acid"].click()
    first = window.windows.window("acid")
    assert isinstance(first, Probe) and first.isVisible()
    window.window_buttons["acid"].click()
    assert window.windows.window("acid") is first and Probe.made == 1


def test_each_button_opens_a_different_window(window):
    for button in window.window_buttons.values():
        button.click()
    opened = [window.windows.window(k) for k, _ in WINDOW_KEYS]
    assert all(w is not None for w in opened) and len({id(w) for w in opened}) == 3


def test_closing_one_window_keeps_the_app_and_the_others(window, qapp):
    for button in window.window_buttons.values():
        button.click()
    goa = window.windows.window("goa")
    goa.close()
    assert window.isVisible() and window.windows.window("goa") is None
    assert window.windows.is_open("acid") and window.windows.is_open("blaster")
    window.window_buttons["goa"].click()  # a fresh one after closing
    again = window.windows.window("goa")
    assert again is not None and again is not goa and Probe.made == 4


def test_closing_the_main_window_closes_all_windows(window):
    for button in window.window_buttons.values():
        button.click()
    kids = [window.windows.window(k) for k, _ in WINDOW_KEYS]
    window.close()
    assert all(k.closed for k in kids)


def test_a_window_that_cannot_be_made_shows_a_message_and_keeps_the_app(qapp, tmp_path):
    def broken(out_dir):
        raise ImportError("kaputt")

    w = MainWindow(out_dir=tmp_path, backend=FakeBackend(), window_factories={
        "goa": broken, "acid": _make_probe, "blaster": _make_probe})
    w.show()
    w.window_buttons["goa"].click()
    assert w.isVisible() and "kaputt" in w.window_note.text()
    w.window_buttons["acid"].click()
    assert w.window_note.text() == "" and w.windows.is_open("acid")
    w.close()


def test_unknown_window_key_is_an_error(qapp, tmp_path):
    mgr = WindowManager(lambda: tmp_path, probe_factories())
    with pytest.raises(KeyError):
        mgr.open("nope")


def test_the_real_windows_open_from_the_main_window(qapp, tmp_path):
    """The three real window classes, made by the default factories (Goa without its settings
    file so that the test does not touch the home folder)."""
    factories = dict(DEFAULT_FACTORIES)
    factories["goa"] = selftest._goa_without_settings_file
    w = MainWindow(out_dir=tmp_path / "o", backend=FakeBackend(), window_factories=factories)
    w.show()
    for key, _ in WINDOW_KEYS:
        w.window_buttons[key].click()
        assert w.windows.is_open(key), (key, w.windows.last_error)
    assert type(w.windows.window("blaster")).__name__ == "BlasterWindow"
    assert type(w.windows.window("acid")).__name__ == "AcidWindow"
    assert type(w.windows.window("goa")).__name__ == "CompactGoaWindow"
    w.close()


def test_selftest_runs_headless_and_reports_ok(qapp):
    out = io.StringIO()
    assert selftest.run(out) == 0
    assert out.getvalue().startswith("GUI selftest ok: main window with ")


# --- laser form -------------------------------------------------------------------------------
def go_laser(window):
    window.categories.setCurrentRow(list(CATEGORY_KEYS).index("laser"))


def test_laser_page_has_a_control_for_every_contract_field(window):
    go_laser(window)
    assert window.form_key == "laser" and window.stack.currentWidget() is window.panel
    model = CategoryFormModel("laser")
    assert set(window.panel.controls) == {s.name for s in model.specs}
    for spec in model.specs:
        assert window.panel.controls[spec.name].label.text() == spec.label
    assert window.render_button.isEnabled()
    assert window.panel.chips.current() == "blaster"


def test_laser_hauptregler_come_from_the_spread_method(window):
    go_laser(window)
    assert [k.name for k in window.panel.knobs] == list(main_controls("laser"))
    assert len(window.panel.knobs) == 5 and main_choices("laser") == ("family",)
    # none of the salvo/filter/delay/reverb fields that exist only in 0.2 is a Hauptregler
    assert not any(n.startswith(("salvo_", "reverb_")) for n in main_controls("laser"))


def test_laser_groups_hold_the_contract_fields_by_prefix(window):
    go_laser(window)
    panel = window.panel
    assert list(panel.group_sections) == ["Salve", "Filter", "Delay", "Reverb"]
    contract = {s.name for s in CategoryFormModel("laser").specs}
    salvo = {n for n in contract if n.startswith("salvo_")}
    reverb = {n for n in contract if n.startswith("reverb_")}
    assert len(salvo) == 11 and len(reverb) == 6  # written out: the 0.2 contract
    body = panel.group_sections["Salve"].body
    assert salvo <= {c.name for c in panel.controls.values() if body.isAncestorOf(c)}
    body = panel.group_sections["Reverb"].body
    assert reverb == {c.name for c in panel.controls.values() if body.isAncestorOf(c)}
    assert "echo_sync" in {c.name for c in panel.controls.values()
                           if panel.group_sections["Delay"].body.isAncestorOf(c)}
    assert not panel.group_sections["Salve"].is_expanded()


def test_wide_enums_wrap_instead_of_widening_the_page(window):
    go_laser(window)
    pan = window.panel.controls["salvo_pan_mode"]
    assert isinstance(pan.seg, WrapSegmented) and pan.seg.items[1] == "alternate_lr"
    pan.seg.buttons[2].click()
    assert pan.value() == "alternate_rl" and window.model.text["salvo_pan_mode"] == "alternate_rl"
    assert "salvo_pan_mode" in window.model.active
    note = window.panel.controls["salvo_sync_note"]
    assert isinstance(note.seg, WrapSegmented) and len(note.seg.buttons) == 12
    # the two-value rows keep the compact segmented look
    assert type(window.panel.controls["salvo_rate_mode"].seg).__name__ == "Segmented"
    assert window.panel.horizontalScrollBar().maximum() == 0


def test_laser_edit_activates_the_version_0_2_field_and_renders(window, qapp):
    go_laser(window)
    c = window.panel.controls["reverb_mix"]
    c.readout.setText("0.3")
    c.readout.entered.emit("0.3")
    assert "reverb_mix" in window.model.active
    assert window.model.build_request()["schema_version"] == "0.2"
    window.start_render()
    assert wait_for(qapp, lambda: not window.running)
    assert window.results.count() == 1 and window.status.text().startswith("Fertig")


def test_stereo_laser_result_shows_a_waveform_of_the_right_length(window, qapp):
    go_laser(window)
    window.start_render()
    assert wait_for(qapp, lambda: not window.running)
    wav = window.result_paths[0]
    wf = load_waveform(wav)
    # preset blaster: length_ms 1500 at 48 kHz, drawn as mid (not interleaved: 72000, not 144000)
    assert len(wf.samples) == 72000 and wf.sample_rate == 48000


# --- byte identity with the CLI ---------------------------------------------------------------
def cli_files(tmp: Path, preset: str, seed: int, sets: list[str], variants: int):
    argv = ["--category", "laser", "--preset", preset, "--seed", str(seed), "--out", str(tmp),
            "--variants", str(variants)]
    for item in sets:
        argv += ["--set", item]
    assert engine_cli.main(argv, io.StringIO(), io.StringIO()) == 0
    return {p.name: p.read_bytes() for p in sorted(tmp.iterdir())}


def gui_files(window, qapp, preset, seed, sets, variants, out: Path):
    go_laser(window)
    model = window.model
    model.set_preset(preset)
    window.panel.sync_from_model()
    model.set_text("seed", str(seed))
    model.set_text("variants", str(variants))
    for item in sets:
        name, _, text = item.partition("=")
        model.set_active(name, True)
        model.set_text(name, text)
    window.folder_edit.setText(str(out))
    window.start_render()
    assert wait_for(qapp, lambda: not window.running)
    assert window.status.text().startswith("Fertig"), window.status.text()
    folder = out / "Samples" / "FX" / "Lasers"  # #443: project-shaped output tree
    # names as the CLI writes them: the GUI adds the category in front (#443)
    return {p.name.removeprefix("laser_"): p.read_bytes() for p in sorted(folder.iterdir())}


CASES = [
    ("blaster", 21, [], 1),
    ("pew", 5, ["decay_ms=300"], 1),
    ("blaster-triple-lrl", 9, ["salvo_pan_mode=alternate_rl", "reverb_mix=0.3"], 2),
]


@pytest.mark.parametrize("preset,seed,sets,variants", CASES, ids=[c[0] for c in CASES])
def test_laser_form_writes_the_same_bytes_as_the_cli(window, qapp, tmp_path, preset, seed, sets,
                                                     variants):
    ref = cli_files(tmp_path / "cli", preset, seed, sets, variants)
    got = gui_files(window, qapp, preset, seed, sets, variants, tmp_path / "gui")
    assert set(got) == set(ref) and len(ref) == 2 * variants
    for name in ref:
        if name.endswith(".json"):  # the sidecar carries a creation time
            a, b = json.loads(ref[name]), json.loads(got[name])
            a.pop("created_at", None), b.pop("created_at", None)
            assert b.pop("file") == "laser_" + a.pop("file"), name
            assert a == b, name
        else:
            assert got[name] == ref[name], name
