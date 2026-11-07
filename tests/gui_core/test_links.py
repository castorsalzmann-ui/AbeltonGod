"""Linked parameters (limits, exclusions, derived values) and the Hauptregler choice (no Qt).

The references here are written in the test or taken straight from ``get_category(cat).resolve``
(the engine's own check), never from ``gui_core.links``."""

from __future__ import annotations

import math
import random

import pytest

from audio_engine.categories import get_category
from gui_core import links
from gui_core.form import CATEGORY_KEYS, CategoryFormModel
from gui_core.form_layout import (
    MAIN_COUNT,
    main_choices,
    main_controls,
    spread_scores,
    variant_fields,
)

CATEGORY_PARAMS = [c for c in CATEGORY_KEYS]


def engine_accepts(model: CategoryFormModel, name: str, value) -> bool:
    try:
        get_category(model.category).resolve(model.probe_request(name, value))
    except ValueError:
        return False
    return True


def grid_of(spec) -> float:
    """Step the limits are rounded to: the decimals the slider shows (3 for log ranges)."""
    from gui_core.valuemap import map_of

    vm = map_of(spec)
    return 10.0 ** -(max(vm.decimals, 3) if vm.log else vm.decimals)


def activate_with(model: CategoryFormModel, name: str, text: str) -> None:
    links.activate(model, name)
    model.set_text(name, text)


# --- contract rules, with hand-written expectations --------------------------------------------

def test_exclusions_and_requirements_are_read_from_the_kick_contract():
    assert sorted(links.exclusions("kick")) == [("length_beats", "length_ms"),
                                                ("tail_note", "pitch_end_hz")]
    assert links.requirements("kick") == {"length_beats": ("bpm",)}
    for category in ("hat", "snare", "rim", "bass", "clap"):
        assert links.exclusions(category) == [] and links.requirements(category) == {}


def test_activating_an_excluding_field_switches_the_other_off_with_a_german_notice():
    m = CategoryFormModel("kick")
    assert "pitch_end_hz" in m.active
    notices = links.activate(m, "tail_note")
    assert "pitch_end_hz" not in m.active and "tail_note" in m.active
    assert notices and "schließen sich aus" in notices[0] and "Tonhöhe Ende" in notices[0]
    links.activate(m, "pitch_end_hz")  # and the other way round
    assert "tail_note" not in m.active and m.is_valid
    notices = links.activate(m, "length_beats")
    assert {"bpm", "length_beats"} <= m.active and "length_ms" not in m.active
    assert any("braucht Tempo" in n for n in notices)


def test_derived_values_come_from_the_resolved_form():
    m = CategoryFormModel("kick")
    activate_with(m, "tail_note", "33")  # note 33 = A1 = 55 Hz (12-tone, 69 = 440 Hz)
    d = links.derived_values(m)
    assert "55" in d.notes["tail_note"] and "Tonhöhe Ende" in d.notes["tail_note"]
    activate_with(m, "bpm", "120")
    activate_with(m, "length_beats", "2")  # 2 beats at 120 BPM = 1000 ms
    d = links.derived_values(m, heavy=True)
    assert "1000" in d.notes["length_beats"]
    assert "length_beats" not in links.derived_values(m).notes  # light mode renders nothing
    assert d.shown["length_ms"] == 1000.0


def test_hat_length_follows_decay_when_it_is_not_given():
    m = CategoryFormModel("hat")
    m.set_active("length_ms", False)
    before = links.derived_values(m).shown["length_ms"]
    m.set_text("decay_ms", "400")
    assert links.derived_values(m).shown["length_ms"] > before


# --- value limits -----------------------------------------------------------------------------

def test_rim_high_pass_is_limited_by_the_first_partial():
    m = CategoryFormModel("rim")  # preset rim: f1_hz 455 -> hp_hz < 0.8 * 455 = 364
    lim = links.limit_of(m, "hp_hz")
    assert lim.limited and 363 <= lim.hi <= 364 and lim.lo == m.spec("hp_hz").minimum
    assert lim.partners == ("f1_hz",)
    assert "Frequenz 1 = 455" in lim.reason and "höchstens 36" in lim.reason
    activate_with(m, "f1_hz", "1000")  # a higher partial frees the high-pass
    assert not links.limit_of(m, "hp_hz").limited or links.limit_of(m, "hp_hz").hi >= 799


def test_bass_filter_limits_follow_note_and_high_pass():
    m = CategoryFormModel("bass")
    assert 78.3 <= links.limit_of(m, "hp_hz").hi <= 78.4  # 0.8 * 97.9989 Hz (note 43)
    activate_with(m, "hp_hz", "60")
    lp = links.limit_of(m, "lp_hz")
    assert 72 <= lp.lo <= 72.1 and "Hochpass" in lp.reason  # lp_hz >= 1.2 * hp_hz
    note = links.limit_of(m, "note")
    # 0.8 * f0 > 60 Hz needs f0 > 75 Hz: note 39 = 77.8 Hz is the lowest, 38 = 73.4 Hz is not
    assert note.limited and note.lo == 39


def test_snare_and_hat_noise_filters_keep_their_ratio():
    m = CategoryFormModel("snare")
    activate_with(m, "noise_hp_hz", "5000")
    lo = links.limit_of(m, "noise_lp_hz").lo
    assert 6000 <= lo <= 6001  # lp > 1.2 * hp
    h = CategoryFormModel("hat")
    activate_with(h, "lp_hz", "9000")
    assert 7499 <= links.limit_of(h, "hp_hz").hi <= 7500  # hp < lp / 1.2


def test_oscillators_cannot_all_be_switched_off():
    m = CategoryFormModel("bass")
    for name in ("saw_level", "square_level", "sub_octave_level"):
        activate_with(m, name, "0")
    sine = links.limit_of(m, "sine_level")
    assert sine.limited and sine.lo > 0 and "mindestens" in sine.reason
    assert not engine_accepts(m, "sine_level", 0)


def test_limits_hold_the_engine_to_the_edge_for_every_category_and_random_state():
    """Property: an end of the allowed range is accepted by the engine, the next grid value
    beyond it is refused (seeded random states over all categories)."""
    rng = random.Random(4201)
    checked = 0
    for category in CATEGORY_PARAMS:
        m = CategoryFormModel(category)
        names = [s.name for s in m.specs if s.kind in ("int", "float") and not s.zero_ok
                 and s.name not in ("seed", "variants", "length_beats")]
        for _ in range(12):
            for name in rng.sample(names, 3):  # put three random fields into the request
                spec = m.spec(name)
                links.activate(m, name)
                value = spec.minimum + rng.random() * (spec.maximum - spec.minimum)
                if spec.kind == "int":
                    value = round(value)
                lim = links.limit_of(m, name)
                value = min(max(value, lim.lo), lim.hi)
                if spec.step:  # fx beats: the slider only gives multiples of 0.25 (#482)
                    value = min(max(round(value / spec.step) * spec.step,
                                    math.ceil(lim.lo / spec.step) * spec.step),
                                math.floor(lim.hi / spec.step) * spec.step)
                m.set_text(name, repr(value) if spec.kind == "float" else str(value))
                assert m.cross_issue() is None, (category, name, value)
            for name in names:
                lim = links.limit_of(m, name)
                spec = m.spec(name)
                if not lim.limited:
                    continue
                checked += 1
                assert engine_accepts(m, name, lim.lo) and engine_accepts(m, name, lim.hi)
                grid = 1 if spec.kind == "int" else grid_of(spec)
                if lim.hi < spec.maximum:  # one grid step further out is refused
                    assert not engine_accepts(m, name, lim.hi + 1.01 * grid)
                if lim.lo > spec.minimum:
                    assert not engine_accepts(m, name, lim.lo - 1.01 * grid)
            m.set_preset(rng.choice(m.preset_names()))
    assert checked > 20, checked


def _clone(m: CategoryFormModel) -> CategoryFormModel:
    c = CategoryFormModel(m.category, m.preset)
    c.text, c.active = dict(m.text), set(m.active)
    return c


@pytest.mark.parametrize("category", CATEGORY_PARAMS)
def test_property_the_ends_of_every_limit_are_accepted_once_the_field_is_switched_on(category):
    """Property (#428): for every numeric field, active or switched off with a stale text, the
    form stays accepted when the user switches the field on and sets it to either end of its
    limit (what clamping does). Checked through the user's path (``activate`` + ``issues``),
    not through the probe code. Seeded random states: values over the full contract range,
    dots switched off and on, presets."""
    rng = random.Random(f"ends-{category}")
    m = CategoryFormModel(category)
    names = [s.name for s in m.specs if s.kind in ("int", "float") and not s.zero_ok
             and s.name not in ("seed", "variants", "length_beats")]
    checked = limited = 0
    for _ in range(10):
        for name in rng.sample(names, min(4, len(names))):
            spec = m.spec(name)
            links.activate(m, name)
            value = spec.minimum + rng.random() * (spec.maximum - spec.minimum)
            value = round(value) if spec.kind == "int" else value
            lim = links.limit_of(m, name)
            value = min(max(value, lim.lo), lim.hi)
            m.set_text(name, repr(value) if spec.kind == "float" else str(value))
            if rng.random() < 0.5:
                m.set_active(name, False)  # off, its text stays (the #428 situation)
        links.repair(m)
        if m.issues():
            continue
        for name in rng.sample(names, min(6, len(names))):
            lim = links.limit_of(m, name)
            limited += lim.limited
            for end in (lim.lo, lim.hi):
                c = _clone(m)
                links.activate(c, name)
                spec = c.spec(name)
                c.set_text(name, str(int(end)) if spec.kind == "int" else repr(float(end)))
                assert c.issues() == [], (category, name, end, lim, c.issues())
                checked += 1
        if rng.random() < 0.3:
            m.set_preset(rng.choice(m.preset_names()))
    assert checked >= 40, checked


def test_bug_428_ends_check_turns_red_when_the_stale_text_is_used(monkeypatch):
    """Fault injection for the property above: the old anchor (the field's own text, or
    nothing when it is refused) makes the rim case of #428 report the field as free."""
    m = CategoryFormModel("rim")
    for name, text in (("f1_hz", "900"), ("hp_hz", "500")):
        activate_with(m, name, text)
    m.set_active("hp_hz", False)
    m.set_active("f1_hz", False)
    lim = links.limit_of(m, "hp_hz")
    assert lim.limited and "Frequenz 1 = 455 Hz" in lim.reason  # the value the engine uses

    def old_anchor(probe, spec):
        value, problem = probe.model.parse(spec.name)
        return value if problem is None and probe.accepts(spec.name, value)[0] else None

    monkeypatch.setattr(links, "_anchor", old_anchor)
    assert not links.limit_of(m, "hp_hz").limited  # the mutant reproduces the bug


def test_cached_answers_keep_value_types_apart():
    """1, 1.0 and True are equal in Python but not to the contract: a cached answer for one
    must not answer another (independent check: a fresh resolve without the cache)."""
    links.clear_cache()
    base = CategoryFormModel("kick")._request_unchecked()
    answers = {}
    for seed in (1, True):
        req = {**base, "seed": seed}
        answers[seed is True] = links.accepts_request("kick", req)[0]
        try:
            get_category("kick").resolve(dict(req))
            direct = True
        except ValueError:
            direct = False
        assert answers[seed is True] == direct, seed
    assert answers == {False: True, True: False}


def test_cache_answers_a_repeated_state_without_a_new_resolve_and_is_bounded(monkeypatch):
    links.clear_cache()
    m = CategoryFormModel("rim")
    links.limits(m)
    before = links.stats["resolve"]
    again = links.limits(m)
    assert links.stats["resolve"] == before  # same state: every probe from the cache
    links.clear_cache()
    assert links.limits(m) == again  # the cache never changes an answer
    monkeypatch.setattr(links, "CACHE_SIZE", 5)
    links.clear_cache()
    links.limits(m)
    assert len(links._cache) == 5


def test_one_current_value_check_is_shared_by_every_active_field():
    """#434: a refresh of the laser form needed ~140 resolves (3 per numeric field). The
    "current value" check is the same request for every active field, so it is asked once."""
    m = CategoryFormModel("laser")
    links.clear_cache()
    before = links.stats["resolve"]
    links.limits(m)
    numeric = sum(1 for s in m.specs if s.kind in ("int", "float"))
    used = links.stats["resolve"] - before
    active = sum(1 for s in m.specs if s.kind in ("int", "float") and s.name in m.active)
    assert used <= 3 * numeric - (active - 1), (used, numeric, active)


def test_an_inactive_field_probes_as_if_switched_on_without_its_excluded_partner():
    """Kick ``tail_note`` excludes the active ``pitch_end_hz``: its limits are probed as
    ``activate`` would leave the form (pitch_end_hz off), not by scanning refused values."""
    m = CategoryFormModel("kick")
    assert "pitch_end_hz" in m.active and "tail_note" not in m.active
    links.clear_cache()
    before = links.stats["resolve"]
    lim = links.limit_of(m, "tail_note")
    assert links.stats["resolve"] - before <= 4 and not lim.limited


def test_a_state_the_engine_already_refuses_gets_no_limits_instead_of_a_wrong_one():
    m = CategoryFormModel("bass")
    activate_with(m, "hp_hz", "400")  # invalid against note 43
    assert not links.limit_of(m, "lp_hz").limited and not links.limit_of(m, "hp_hz").limited


# --- Hauptregler ------------------------------------------------------------------------------

@pytest.mark.parametrize("category", CATEGORY_PARAMS)
def test_main_controls_are_three_to_five_numeric_contract_fields_without_housekeeping(category):
    names = main_controls(category)
    assert 3 <= len(names) <= MAIN_COUNT
    m = CategoryFormModel(category)
    for n in names:
        s = m.spec(n)
        assert s.kind in ("int", "float") and not s.gate_version
        assert n not in ("seed", "variants", "bpm", "sample_rate", "bit_depth", "polarity",
                         "offset_ms", "peak_ceiling_dbfs", "length_ms")


def test_main_controls_are_the_top_scores_of_the_stated_method():
    for category in CATEGORY_PARAMS:
        scores = spread_scores(category)
        best = sorted(scores.values(), reverse=True)[:MAIN_COUNT]
        assert sorted((scores[n] for n in main_controls(category)), reverse=True) == best
    assert main_controls("kick") == ("click_level", "drive", "tone", "pitch_decay_ms",
                                     "pitch_start_hz")
    assert main_controls("bass")[:3] == ("lp_env_decay_ms", "lp_env_amount", "saw_level")
    assert main_choices("kick") == () and "model" not in main_choices("hat")


def test_variant_fields_come_from_the_engines_spread_tables():
    assert "click_level" in variant_fields("kick") and "hp_hz" in variant_fields("clap")
    assert variant_fields("bass") == ("lp_env_amount", "lp_hz", "lp_env_decay_ms", "lp_q",
                                      "drive")
