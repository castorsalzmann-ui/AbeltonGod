"""Skin settings file (#407): round trip and damaged-file behaviour."""

from __future__ import annotations

import json

from gui.skin.settings import MIN_SIZE, SkinSettings, load_settings, save_settings


def test_round_trip(tmp_path):
    p = tmp_path / "sub" / "skin.json"
    s = SkinSettings(x=120, y=-40, width=611, height=403, always_on_top=False, animation=True)
    assert save_settings(s, p) is True
    assert load_settings(p) == s


def test_missing_file_gives_defaults(tmp_path):
    s = load_settings(tmp_path / "nope.json")
    assert s == SkinSettings()
    assert s.always_on_top is True and s.animation is False
    assert (s.width, s.height) == (460, 340)


def test_damaged_file_gives_defaults(tmp_path):
    p = tmp_path / "skin.json"
    for text in ("{not json", "[1, 2]", "", '"x"'):
        p.write_text(text, encoding="utf-8")
        assert load_settings(p) == SkinSettings()


def test_wrong_types_fall_back_per_field(tmp_path):
    p = tmp_path / "skin.json"
    p.write_text(
        json.dumps({"x": "3", "y": 5, "width": True, "height": 500.5,
                    "always_on_top": "yes", "animation": 1}),
        encoding="utf-8",
    )
    s = load_settings(p)
    assert s.x is None and s.y is None  # half a position is no position
    assert (s.width, s.height) == (460, 340)
    assert s.always_on_top is True and s.animation is False


def test_size_is_clamped_to_minimum(tmp_path):
    p = tmp_path / "skin.json"
    p.write_text(json.dumps({"width": 10, "height": 20}), encoding="utf-8")
    s = load_settings(p)
    assert (s.width, s.height) == MIN_SIZE


def test_unwritable_target_returns_false_without_raising(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert save_settings(SkinSettings(), blocker / "skin.json") is False


def test_failed_save_keeps_the_old_file(tmp_path):
    p = tmp_path / "skin.json"
    save_settings(SkinSettings(width=500), p)
    assert not (tmp_path / "skin.json.tmp").exists()
    assert load_settings(p).width == 500
