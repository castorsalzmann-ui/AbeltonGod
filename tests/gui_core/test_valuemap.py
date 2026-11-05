"""ValueMap: slider position <-> contract value, clamping and German text (no Qt)."""

from __future__ import annotations

import random

import pytest

from gui_core.form import CATEGORY_KEYS, field_specs
from gui_core.valuemap import ValueMap, map_of

NUMERIC = [
    (c, s) for c in CATEGORY_KEYS for s in field_specs(c) if s.kind in ("int", "float")
]


def test_linear_map_written_out_by_hand():
    m = ValueMap(0.0, 1.0)  # 1000 positions
    assert m.pos_max == 1000
    assert m.from_pos(0) == 0.0 and m.from_pos(1000) == 1.0
    assert m.from_pos(500) == 0.5 and m.from_pos(123) == 0.123
    assert m.to_pos(0.25) == 250 and m.to_pos(7) == 1000 and m.to_pos(-3) == 0


def test_log_map_gives_the_geometric_middle_with_three_digits():
    m = ValueMap(20.0, 2000.0, log=True)  # ratio 100: the middle is sqrt(20 * 2000) = 200
    assert m.from_pos(500) == 200.0
    assert m.from_pos(0) == 20.0 and m.from_pos(1000) == 2000.0
    assert m.to_pos(200) == 500
    assert m.from_pos(250) == 63.2  # 20 * 100 ** 0.25 = 63.2456 -> 3 digits


def test_integer_map_moves_in_whole_numbers():
    m = ValueMap(1, 8, integer=True, steps=7)
    assert [m.from_pos(p) for p in range(8)] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert all(isinstance(m.from_pos(p), int) for p in range(8))


def test_zero_off_gives_position_zero_to_the_off_value():
    m = ValueMap(5.0, 500.0, log=True, zero_off=True, unit="ms")
    assert m.from_pos(0) == 0 and m.to_pos(0) == 0
    assert m.from_pos(1) == 5.0 and m.from_pos(m.pos_max) == 500.0
    assert m.format(0) == "aus" and m.format(40.0) == "40 ms"
    assert m.clamp(0) == 0 and m.clamp(2) == 5.0


@pytest.mark.parametrize(("value", "text"), [
    (0.35, "0,35 Hz"), (260.0, "260 Hz"), (0.3, "0,3 Hz"), (-12.0, "-12 Hz"),
])
def test_format_uses_a_decimal_comma_and_drops_trailing_zeros(value, text):
    assert ValueMap(-20.0, 1000.0, unit="Hz").format(value) == text


def test_every_numeric_contract_field_maps_inside_its_range_and_monotonic():
    """Whole contract range of all six categories, not favourite fields."""
    assert len(NUMERIC) > 80
    for category, spec in NUMERIC:
        m = map_of(spec)
        lo, hi = spec.minimum, spec.maximum
        values = [m.from_pos(p) for p in range(m.pos_max + 1)]
        assert values == sorted(values), (category, spec.name)
        assert all(v == 0 or lo <= v <= hi for v in values), (category, spec.name)
        assert values[-1] == hi and values[0] in (lo, 0), (category, spec.name)
        if spec.kind == "int":
            assert all(isinstance(v, int) for v in values)


def test_position_round_trip_and_clamp_property_with_seeded_random_values():
    rng = random.Random(420)
    for category, spec in NUMERIC:
        m = map_of(spec)
        for _ in range(25):
            p = rng.randint(0, m.pos_max)
            v = m.from_pos(p)
            assert abs(m.to_pos(v) - p) <= (1 if not m.log else 12), (category, spec.name, p)
            outside = spec.maximum + rng.random() * 1000
            assert m.clamp(outside) == spec.maximum and m.to_pos(outside) == m.pos_max
            assert m.clamp(spec.minimum - rng.random() * 1000) == spec.minimum


def test_wide_ranges_are_logarithmic_and_narrow_ones_linear():
    by_name = {(c, s.name): map_of(s) for c, s in NUMERIC}
    assert by_name[("kick", "pitch_start_hz")].log is False  # 60..600 is a factor of 10
    assert by_name[("kick", "click_tone_hz")].log is True  # 500..12000
    assert by_name[("hat", "decay_ms")].log is True
    assert by_name[("kick", "tone")].log is False  # includes negative values
    assert by_name[("bass", "note")].integer is True
