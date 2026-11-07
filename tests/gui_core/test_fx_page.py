"""fx GUI page (#482) without Qt: registration, Hauptregler from resolved per-kind values (other
categories unchanged), the 0.25-beat grid of the sliders, and the #503 render-time estimate."""

from __future__ import annotations

import pytest

from audio_engine.fx import resolve_fx_params
from audio_engine.presets import load_preset, preset_names
from gui_core import fx_cost
from gui_core.categories import CATEGORIES
from gui_core.form import CATEGORY_KEYS, DEFAULT_PRESETS, CategoryFormModel, field_specs
from gui_core.form_layout import main_choices, main_controls
from gui_core.valuemap import map_of

# Hauptregler before #482, written out (computed on main fcef67c): must stay exactly these.
OLD_MAIN = {
    "kick": (("click_level", "drive", "tone", "pitch_decay_ms", "pitch_start_hz"), ()),
    "hat": (("decay_ms", "hp_hz", "metal", "pitch_scale", "color"), ()),
    "snare": (("noise_hp_hz", "noise_decay_ms", "body_level", "body_decay_ms", "body_hz"), ()),
    "clap": (("drive", "tail_decay_ms", "tail_level", "hp_hz", "burst_level_falloff"), ()),
    "rim": (("f1_hz", "level2", "decay1_ms", "decay2_ms", "hp_hz"), ()),
    "bass": (("lp_env_decay_ms", "lp_env_amount", "saw_level", "lp_hz", "lp_q"), ()),
    "laser": (("stereo_width", "pitch_end_hz", "sweep_ms", "echo_mix", "decay_ms"),
              ("family",)),
    "perc": (("tune_semitones", "hp_hz", "decay_scale", "tick_level", "bend_ms"), ("model",)),
}


def test_fx_is_a_gui_category_with_its_default_preset() -> None:
    assert "fx" in CATEGORY_KEYS and DEFAULT_PRESETS["fx"] == "riser-8bar"
    assert [c.label for c in CATEGORIES if c.key == "fx"] == ["FX"]
    m = CategoryFormModel("fx")
    assert m.preset == "riser-8bar" and m.text["bpm"] == "135"
    req = m.build_request()
    assert req["preset"] == "riser-8bar" and req["kind"] == "riser" and req["bpm"] == 135
    assert resolve_fx_params(req)["length_beats"] == 32
    for name in preset_names("fx"):
        CategoryFormModel("fx", name).build_request()  # every preset opens without a problem


def test_required_bpm_is_always_sent_and_cannot_be_switched_off() -> None:
    """fx-params requires bpm: its dot is locked like seed / variants (a random-action GUI test
    switched it off and left a request the engine refused)."""
    m = CategoryFormModel("fx")
    assert m.locked == {"seed", "variants", "bpm"} and "bpm" in m.active
    m.set_active("bpm", False)
    m.reset_field("bpm")
    m.set_preset("impact")
    assert "bpm" in m.active and m.issues() == []
    assert "bpm" in CategoryFormModel.without_preset("fx").active
    for category in OLD_MAIN:  # every other contract requires only seed: nothing new locked
        assert CategoryFormModel(category).locked == {"seed", "variants"}, category


@pytest.mark.parametrize("category", sorted(OLD_MAIN))
def test_other_categories_keep_their_hauptregler(category: str) -> None:
    assert (main_controls(category), main_choices(category)) == OLD_MAIN[category]


def test_fx_hauptregler_come_from_resolved_per_kind_values() -> None:
    """The per-kind fields have no top-level default, so the presets are scored in resolved
    form; the fields that differ most between the kinds win (written out from that run)."""
    assert main_controls("fx") == ("level_end_db", "cutoff_end_hz", "level_start_db",
                                   "tone_level", "cutoff_start_hz")
    assert main_choices("fx") == ("kind",)


def test_beat_fields_slide_on_the_quarter_beat_grid_only() -> None:
    specs = {s.name: s for s in field_specs("fx")}
    for name in ("length_beats", "tail_beats", "cut_beats"):
        vm = map_of(specs[name])
        assert specs[name].step == 0.25 and not vm.log
        values = {vm.from_pos(p) for p in range(vm.pos_max + 1)}
        assert all(abs(v * 4 - round(v * 4)) < 1e-12 for v in values), name
        assert min(values) == specs[name].minimum and max(values) == specs[name].maximum
        assert len(values) == round((specs[name].maximum - specs[name].minimum) * 4) + 1
    for category in OLD_MAIN:  # no other params contract has a grid: their maps are as before
        assert all(s.step is None for s in field_specs(category)), category
    vm = map_of(specs["tail_beats"])
    assert vm.snap(12.8) == 12.75 and vm.snap(12.9) == 13.0 and vm.snap(99) == 16.0
    assert vm.snap(3.99, 0, 3.999) == 3.75  # a limit off the grid: the nearest step inside
    drive = next(s for s in field_specs("kick") if s.name == "drive")
    assert map_of(drive).snap(0.12345) == 0.12345  # no grid: unchanged


# --- #503 render-time estimate ------------------------------------------------------------------

BASE = {"schema_version": "0.1", "seed": 1, "bpm": 120, "kind": "sweep", "length_beats": 64,
        "tail_beats": 0, "reverb_mix": 0}
# Render times MEASURED in the dev container (Xeon 2.3 GHz, 2026-11-07, one process per case,
# 32 s at 48 kHz), plus the reviewer's 72 s cases of PR #499. Rough by nature: the estimate
# must stay within a factor of 2 of each.
MEASURED = [
    ({**BASE, "stereo_width": 0}, 0.85),
    ({**BASE, "stereo_width": 1}, 1.49),
    ({**BASE, "stereo_width": 1, "filter_mode": "hp_lp"}, 2.61),
    ({**BASE, "noise_level": 0, "tone_level": 1, "tone_wave": "saw", "tone_start_hz": 50,
      "tone_end_hz": 50}, 5.09),
    ({**BASE, "noise_level": 0, "tone_level": 1, "tone_wave": "metal", "tone_start_hz": 100,
      "tone_end_hz": 100}, 5.72),
    ({**BASE, "stereo_width": 1, "drive": 0.5}, 4.48),
    ({**BASE, "length_beats": 128, "tail_beats": 16, "noise_level": 0, "tone_level": 1,
      "tone_wave": "saw", "tone_start_hz": 20, "tone_end_hz": 20}, 41.8),
    ({**BASE, "length_beats": 128, "tail_beats": 16, "noise_level": 0, "tone_level": 1,
      "tone_wave": "metal", "tone_start_hz": 20, "tone_end_hz": 20}, 109.3),
]


@pytest.mark.parametrize("params,seconds", MEASURED)
def test_estimate_is_within_a_factor_two_of_the_measured_times(params, seconds) -> None:
    est = fx_cost.estimate_seconds(resolve_fx_params(params))
    assert seconds / 2 <= est <= seconds * 2, (est, seconds)


def test_warning_appears_only_for_slow_settings_and_counts_variants() -> None:
    for name in preset_names("fx"):  # every shipped preset at one variant: no note
        assert fx_cost.warning_text(resolve_fx_params(load_preset(name, "fx"))) == ""
    slow = resolve_fx_params(MEASURED[-2][0])
    text = fx_cost.warning_text(slow)
    assert text.startswith("Hinweis: geschätzte Renderzeit") and "Sägezahn" in text
    assert "grobe Schätzung" in text
    eight = fx_cost.warning_text(slow, 8)
    assert "8 Varianten" in eight and "min" in eight
    assert fx_cost.estimate_seconds(slow, 8) == pytest.approx(8 * fx_cost.estimate_seconds(slow))
    # a riser-32bar alone is ~4 s here, 8 variants of it get a note
    r32 = resolve_fx_params(load_preset("riser-32bar", "fx"))
    assert fx_cost.warning_text(r32) == "" and fx_cost.warning_text(r32, 8) != ""


def test_cost_note_follows_the_form() -> None:
    m = CategoryFormModel("fx")
    assert fx_cost.cost_note(m) == ""
    for name, text in (("noise_level", "0"), ("tone_level", "1"), ("tone_wave", "metal"),
                       ("tone_start_hz", "20"), ("tone_end_hz", "20"), ("length_beats", "128"),
                       ("variants", "2")):
        if name != "variants":
            m.set_active(name, True)
        m.set_text(name, text)
    note = fx_cost.cost_note(m)
    assert "Metall" in note and "2 Varianten" in note
    m.set_text("tone_start_hz", "abc")  # a field problem: the page shows that instead
    assert fx_cost.cost_note(m) == ""
    assert fx_cost.cost_note(CategoryFormModel("laser")) == ""
