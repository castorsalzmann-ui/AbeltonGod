"""Shared GUI settings (#439): file round trip, damaged files, per-value fallback, the output
tree, the store's listeners and the form start values. No Qt."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from gui_core import settings as st
from gui_core.form import CategoryFormModel
from gui_core.settings import AppSettings, SettingsStore, WindowState


def test_round_trip_keeps_every_field(tmp_path):
    p = tmp_path / "cfg" / "settings.json"
    s = AppSettings(output_dir=str(tmp_path / "out"), project_dir=str(tmp_path / "proj"),
                    sample_rate=44100, bit_depth=16,
                    windows={"main": WindowState(10, 20, 900, 600),
                             "goa": WindowState(-5, 7, 400, 300, False, True)})
    assert st.save_settings(s, p) is True
    assert st.load_settings(p) == s
    assert not (tmp_path / "cfg" / "settings.json.tmp").exists()


def test_missing_or_damaged_file_gives_defaults(tmp_path):
    assert st.load_settings(tmp_path / "nope.json") == AppSettings()
    p = tmp_path / "s.json"
    for text in ("{not json", "[1, 2]", "", '"x"', "null", "\xff\xfe"):
        p.write_text(text, encoding="utf-8", errors="replace")
        assert st.load_settings(p) == AppSettings()


def test_a_bad_value_falls_back_alone_and_the_others_are_kept(tmp_path):
    p = tmp_path / "s.json"
    good = {"output_dir": "/o", "project_dir": "/p", "sample_rate": 48000, "bit_depth": 24,
            "windows": {"acid": {"x": 1, "y": 2, "width": 300, "height": 200}}}
    bad_values = {"output_dir": 5, "project_dir": None, "sample_rate": 22050,
                  "bit_depth": True, "windows": {"acid": {"x": "1", "y": 2, "width": 300,
                                                          "height": 200}}}
    defaults = AppSettings()
    for key, bad in bad_values.items():
        p.write_text(json.dumps({**good, key: bad}), encoding="utf-8")
        got = st.load_settings(p)
        expected = st.settings_from_json(good)
        for name in ("output_dir", "project_dir", "sample_rate", "bit_depth", "windows"):
            want = getattr(defaults, name) if name == key else getattr(expected, name)
            assert getattr(got, name) == want, (key, name)


def test_random_window_entries_never_raise_and_only_sane_ones_survive():
    rng = random.Random(439)
    pool = [0, -1, 99, 100, 5000, 100_001, -100_001, 1.5, True, None, "7", [], {}]
    for _ in range(500):
        raw = {k: rng.choice(pool) for k in ("x", "y", "width", "height")}
        got = st.settings_from_json({"windows": {"main": raw, "nope": raw}})
        assert "nope" not in got.windows
        ws = got.windows.get("main")
        if ws is not None:
            assert all(type(getattr(ws, k)) is int for k in ("x", "y", "width", "height"))
            assert ws.width >= 100 and ws.height >= 100
            assert max(abs(ws.x), abs(ws.y), ws.width, ws.height) <= 100_000


def test_unwritable_path_returns_false_and_keeps_the_old_file(tmp_path):
    p = tmp_path / "s.json"
    st.save_settings(AppSettings(output_dir="/first"), p)
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert st.save_settings(AppSettings(), blocker / "s.json") is False  # parent is a file
    assert st.load_settings(p).output_dir == "/first"


def test_config_dir_env_wins(tmp_path, monkeypatch):
    monkeypatch.setenv(st.CONFIG_ENV, str(tmp_path / "cfg"))
    assert st.default_settings_path() == tmp_path / "cfg" / "settings.json"


def test_output_tree_below_the_output_folder(tmp_path):
    s = AppSettings(output_dir=str(tmp_path))
    assert s.acid_dir() == tmp_path / "acid"
    assert s.goa_dir() == tmp_path / "goa"
    assert s.laser_dir() == tmp_path / "Samples" / "FX" / "Lasers"
    assert s.bank_start_dir() == tmp_path
    assert AppSettings(output_dir=str(tmp_path), project_dir="/proj").bank_start_dir() == \
        Path("/proj")
    assert (s.effective_sample_rate(), s.effective_bit_depth()) == (48000, 24)
    assert s.format_overrides() == {}
    assert AppSettings(sample_rate=44100).format_overrides() == {"sample_rate": 44100}


def test_store_saves_notifies_and_rejects_out_of_range(tmp_path):
    p = tmp_path / "s.json"
    store = SettingsStore(path=p)
    seen = []
    store.subscribe(seen.append)
    store.update(output_dir="/x", sample_rate=44100)
    assert seen and seen[-1].sample_rate == 44100
    assert st.load_settings(p).output_dir == "/x"
    n = len(seen)
    store.update(output_dir="/x")  # no change: no call
    assert len(seen) == n
    with pytest.raises(ValueError):
        store.update(sample_rate=22050)
    with pytest.raises(ValueError):
        store.update(bit_depth=32)
    store.set_window("acid", WindowState(1, 2, 300, 200))
    assert st.load_settings(p).windows["acid"] == WindowState(1, 2, 300, 200)
    assert len(seen) == n  # a window place does not redraw anything
    assert SettingsStore(path=p).settings == store.settings  # a restart reads it back


def test_memory_store_never_writes(tmp_path, monkeypatch):
    monkeypatch.setenv(st.CONFIG_ENV, str(tmp_path / "cfg"))
    store = SettingsStore()
    store.update(output_dir="/x")
    store.set_window("main", WindowState(1, 2, 300, 200))
    assert not (tmp_path / "cfg").exists() and store.save() is False


def test_free_stem_never_reuses_a_taken_name(tmp_path):
    assert st.free_stem(tmp_path, "a") == "a"
    (tmp_path / "a.wav").write_bytes(b"")
    assert st.free_stem(tmp_path, "a") == "a_2"
    (tmp_path / "a_2.json").write_text("{}")
    assert st.free_stem(tmp_path, "a") == "a_3"


@pytest.mark.parametrize("category", ["kick", "clap", "hat", "snare", "rim", "bass", "laser"])
def test_form_start_values_from_the_settings(category):
    plain = CategoryFormModel(category)
    before = plain.build_request()
    assert st.apply_format_to_form(plain, AppSettings()) is False  # None: untouched
    assert plain.build_request() == before
    m = CategoryFormModel(category)
    assert st.apply_format_to_form(m, AppSettings(sample_rate=44100, bit_depth=16)) is True
    req = m.build_request()
    assert (req["sample_rate"], req["bit_depth"]) == (44100, 16)
    assert st.apply_format_to_form(m, AppSettings(sample_rate=44100, bit_depth=16)) is False
    d = CategoryFormModel(category)  # the contract default: the request stays as it was
    st.apply_format_to_form(d, AppSettings(sample_rate=48000, bit_depth=24))
    if "sample_rate" not in before:
        assert d.build_request() == before
