"""Kick form model: built from the contract, every check in the model (no Qt)."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from audio_engine.presets import load_preset
from gui_core.form import (
    ALWAYS_ACTIVE,
    HIDDEN_FIELDS,
    FormError,
    KickFormModel,
    kick_field_specs,
    parse_number,
)

CONTRACT = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts" / "kick-params.schema.json").read_text(
        encoding="utf-8"
    )
)
# Read straight from the JSON file here, not through the code under test.
V03 = CONTRACT["allOf"][0]["then"]["properties"]
ALL_FIELDS = {**CONTRACT["properties"], **V03}
EDITABLE = {k: v for k, v in ALL_FIELDS.items() if k not in HIDDEN_FIELDS}


def test_every_contract_field_has_a_spec_with_its_range():
    specs = {s.name: s for s in kick_field_specs()}
    assert set(specs) == set(EDITABLE)
    for name, d in EDITABLE.items():
        s = specs[name]
        if "enum" in d:
            assert s.kind == "enum" and list(s.choices) == d["enum"], name
        else:
            assert (s.minimum, s.maximum) == (d["minimum"], d["maximum"]), name
            assert s.kind == ("int" if d["type"] == "integer" else "float"), name
        assert s.label and s.label != name, f"{name}: German label missing"
    assert specs["pitch_decay_ms"].unit == "ms"
    assert specs["peak_ceiling_dbfs"].unit == "dBFS"
    assert specs["pitch_start_hz"].range_text == "60 bis 600 Hz"


@pytest.mark.parametrize("text,expected", [
    ("15", 15), ("-3", -3), ("0,5", 0.5), ("0.5", 0.5), (" 1e2 ", 100.0), (".5", 0.5),
])
def test_parse_number_accepts(text, expected):
    got = parse_number(text)
    assert got == expected and type(got) is type(expected)


@pytest.mark.parametrize("text", ["", "abc", "nan", "inf", "-inf", "1,2,3", "1..2", "0x10", "--1"])
def test_parse_number_rejects(text):
    assert parse_number(text) is None


def test_default_form_is_the_preset_and_valid():
    m = KickFormModel("punchy")
    assert m.is_valid and m.issues() == []
    req = m.build_request()
    expected = dict(load_preset("punchy"))
    expected["variants"] = 1
    assert req == expected
    assert m.overrides() == {}


def test_every_preset_loads_into_a_valid_form_and_reproduces_itself():
    for name in KickFormModel.preset_names():
        m = KickFormModel(name)
        assert m.issues() == [], name
        expected = dict(load_preset(name))
        expected["variants"] = 1
        assert m.build_request() == expected, name


def test_boundaries_accepted_and_just_outside_rejected_for_every_numeric_field():
    for name, d in EDITABLE.items():
        if "enum" in d:
            continue
        lo, hi = d["minimum"], d["maximum"]
        step = 1 if d["type"] == "integer" else 1e-6
        for text, ok in ((lo, True), (hi, True), (lo - step, False), (hi + step, False)):
            m = KickFormModel()
            m.set_active(name, True)
            m.set_text(name, repr(text))
            assert (name in m.field_issues()) is (not ok), (name, text)
            if not ok:
                assert not m.is_valid and m.issues(), (name, text)


def test_random_in_range_values_are_accepted_and_sent_unchanged():
    rng = random.Random(403)
    for _ in range(200):
        m = KickFormModel()
        name = rng.choice([n for n, d in ALL_FIELDS.items()
                           if n not in HIDDEN_FIELDS and "enum" not in d])
        d = ALL_FIELDS[name]
        if d["type"] == "integer":
            v = rng.randint(d["minimum"], d["maximum"])
        else:
            v = rng.uniform(d["minimum"], d["maximum"])
        m.set_active(name, True)
        m.set_text(name, repr(v))
        assert name not in m.field_issues()
        assert m.build_request()[name] == v


def test_enum_fields_only_take_listed_values():
    m = KickFormModel()
    for name, bad in (("sample_rate", "96000"), ("bit_depth", "32"), ("polarity", "0")):
        m.set_active(name, True)
        m.set_text(name, bad)
        assert name in m.field_issues(), name
    m.set_text("sample_rate", "44100")
    assert "sample_rate" not in m.field_issues()


def test_integer_fields_reject_fractions_and_seed_range():
    m = KickFormModel()
    m.set_text("seed", "4294967295")
    assert m.is_valid
    for bad in ("4294967296", "-1", "1.5", "abc", ""):
        m.set_text("seed", bad)
        assert "seed" in m.field_issues(), bad
        assert not m.is_valid
    with pytest.raises(FormError):
        m.build_request()


def test_variants_range():
    m = KickFormModel()
    for ok in ("1", "8"):
        m.set_text("variants", ok)
        assert m.is_valid
    for bad in ("0", "9"):
        m.set_text("variants", bad)
        assert "variants" in m.field_issues()


def test_inactive_field_is_not_sent_and_not_checked_but_seed_cannot_be_switched_off():
    m = KickFormModel()
    m.set_text("drive", "99")
    assert "drive" in m.field_issues()
    m.set_active("drive", False)
    assert m.is_valid and "drive" not in m.build_request()
    for name in ALWAYS_ACTIVE:
        m.set_active(name, False)
        assert name in m.active


def test_v03_field_switches_schema_version_and_overrides_are_listed():
    m = KickFormModel("punchy")
    assert m.build_request()["schema_version"] == "0.2"
    m.set_active("click_decay_ms", True)
    m.set_text("click_decay_ms", "5")
    m.set_text("drive", "0,5")
    req = m.build_request()
    assert req["schema_version"] == "0.3" and req["click_decay_ms"] == 5
    assert m.overrides() == {"drive": 0.5, "click_decay_ms": 5}
    assert m.is_valid


def test_cross_field_rule_from_the_contract_disables_render():
    m = KickFormModel("punchy")  # preset has pitch_end_hz
    m.set_active("tail_note", True)
    m.set_text("tail_note", "33")
    assert m.field_issues() == {}
    assert not m.is_valid
    assert "Ungültige Kombination" in m.issues()[0]
    m.set_active("pitch_end_hz", False)
    assert m.is_valid

    m = KickFormModel("punchy")  # pitch_start must not be lower than pitch_end
    m.set_text("pitch_start_hz", "60")
    m.set_text("pitch_end_hz", "100")
    assert not m.is_valid


def test_unknown_preset_is_an_error_not_a_silent_default():
    with pytest.raises(KeyError):
        KickFormModel("does-not-exist")
