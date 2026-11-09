"""atmos GUI page (#533) without Qt: registration, per-kind defaults from the contract's allOf,
the intervals list field, Live note names, all 8 presets rendered into Samples/Atmos and the
render-time estimate."""

from __future__ import annotations

import json

import pytest

from audio_engine import atmos
from audio_engine.categories import get_category
from audio_engine.presets import describe, load_preset, preset_names
from gui_core import atmos_cost
from gui_core.categories import CATEGORIES
from gui_core.form import (
    CATEGORY_KEYS,
    DEFAULT_PRESETS,
    CategoryFormModel,
    field_specs,
    live_note_name,
)
from gui_core.form_layout import main_choices
from gui_core.library import scan
from gui_core.preset_texts import PRESET_TEXTS_DE
from gui_core.render import RenderJob, run_job

PRESETS = ("air-bed", "dark-bed", "drone-octaves-e1", "drone-root-fifth", "granular-drone",
           "granular-metal", "pumping-bed", "resonant-bed")


def test_atmos_is_a_gui_category_with_its_default_preset() -> None:
    assert "atmos" in CATEGORY_KEYS and DEFAULT_PRESETS["atmos"] == "air-bed"
    assert [c.label for c in CATEGORIES if c.key == "atmos"] == ["Atmos"]
    assert tuple(preset_names("atmos")) == PRESETS
    m = CategoryFormModel("atmos")
    assert m.locked == {"seed", "variants", "bpm"} and m.text["bpm"] == "135"
    assert m.text["bars"] == "8" and m.text["loop_mode"] == "seamless"


def test_bars_and_loop_mode_are_not_hauptregler_choices() -> None:
    """They sit on top with the tempo (#533), never twice on the page."""
    choices = main_choices("atmos")
    assert "kind" in choices and "bars" not in choices and "loop_mode" not in choices


def test_kind_switch_shows_the_kinds_defaults_from_the_contract() -> None:
    """Placeholders follow kind (allOf branches); values written out from the contract."""
    m = CategoryFormModel.without_preset("atmos")
    # kind not sent: the noise_bed branch applies (no "required" in it)
    assert (m.text["hp_hz"], m.text["lp_hz"], m.text["filter_mode"]) == ("150", "8000", "lp")
    expected = {"drone": ("20", "6000", "off", "0.35"), "resonant": ("20", "10000", "lp", "0.3"),
                "granular": ("100", "12000", "off", "0.4"),
                "noise_bed": ("150", "8000", "lp", "0.3")}
    m.set_active("kind", True)
    for kind, values in expected.items():
        m.set_text("kind", kind)
        got = (m.text["hp_hz"], m.text["lp_hz"], m.text["filter_mode"], m.text["reverb_mix"])
        assert got == values, kind
        assert "hp_hz" not in m.build_request()  # a default is shown, not sent
        assert atmos.resolve_atmos_params(m.build_request())["hp_hz"] == float(values[0])


def test_intervals_list_round_trips_and_rejects_what_the_contract_rejects() -> None:
    m = CategoryFormModel("atmos", "drone-octaves-e1")
    assert m.text["intervals"] == "0, 12, 24" and "intervals" in m.active
    assert m.build_request()["intervals"] == [0, 12, 24]
    for text, ok in (("0, 7, 12", True), ("0 3 7 10", True), ("0;5", True), ("0", True),
                     ("7, 0", False), ("0, 0", False), ("0, 37", False), ("0, -1", False),
                     ("0, 1, 2, 3, 4, 5, 6", False), ("0, 1.5", False), ("", False),
                     ("Quinte", False)):
        m.set_text("intervals", text)
        problem = m.field_issues().get("intervals")
        assert (problem is None) is ok, (text, problem)
        if ok:  # the engine accepts what the form accepts
            atmos.resolve_atmos_params(m.build_request())
    spec = next(s for s in field_specs("atmos") if s.name == "intervals")
    assert (spec.kind, spec.min_items, spec.max_items, spec.first_item) == ("list", 1, 6, 0)


def test_note_names_follow_live() -> None:
    """#533 comment: Live names MIDI 36 C1 and 60 C3 (written out, not computed)."""
    assert [live_note_name(n) for n in (24, 28, 36, 48, 60, 61, 72)] == [
        "C0", "E0", "C1", "C2", "C3", "C#3", "C4"]
    note = next(s for s in field_specs("atmos") if s.name == "note")
    assert "36 = C1" in note.description and "C2" not in note.description
    for name in PRESETS:  # GUI and preset-file texts: no scientific names for these notes
        for text in (PRESET_TEXTS_DE[("atmos", name)], describe(name, "atmos")):
            assert "C2 root" not in text and "on C3" not in text and "Drone on E1" not in text
    assert "C1" in PRESET_TEXTS_DE[("atmos", "drone-root-fifth")]
    assert "E0" in describe("drone-octaves-e1", "atmos")


def test_all_presets_render_from_the_form_into_samples_atmos(tmp_path) -> None:
    """Done-when of #533: every shipped preset renders from the GUI form into the library
    folder Samples/Atmos and the library lists it as atmos. The form sends what the preset file
    holds (plus variants), so the engine resolves both to the same parameters: same bytes as
    the CLI path (determinism is the engine's own test; one render per preset here, ~25 s)."""
    out = tmp_path / "out"
    resolve = get_category("atmos").resolve
    for name in PRESETS:
        m = CategoryFormModel("atmos", name)
        req = m.build_request()
        assert {k: v for k, v in req.items() if k != "variants"} == load_preset(name, "atmos")
        r = run_job(RenderJob(req, out, m.preset, m.overrides(), "atmos"))
        assert r.ok, (name, r.error)
        [f] = r.files
        assert f.wav_path.parent == out / "Samples" / "Atmos"
        assert f.wav_path.name == f"atmos_{name}_s{load_preset(name, 'atmos')['seed']}_v0.wav"
        meta = json.loads(f.json_path.read_text(encoding="utf-8"))
        assert meta["category"] == "atmos" and meta["features"]["seamless"] is True
        resolved = resolve(load_preset(name, "atmos"))
        assert meta["features"]["loop_samples"] == atmos.loop_samples(resolved)
    entries = scan(out).entries
    assert sorted(e.preset for e in entries) == sorted(PRESETS)
    assert all(e.readable and e.category == "atmos" for e in entries)
    assert all("kind=" in e.key_params and "bpm=135" in e.key_params for e in entries)


def test_oneshot_and_bars_reach_the_request() -> None:
    m = CategoryFormModel("atmos")
    for name, text in (("loop_mode", "oneshot"), ("bars", "4"), ("tail_beats", "8")):
        m.set_active(name, True)
        m.set_text(name, text)
    p = atmos.resolve_atmos_params(m.build_request())
    assert (p["loop_mode"], p["bars"], p["tail_beats"]) == ("oneshot", 4, 8)
    line = atmos_cost.length_text(m)
    assert "One-Shot" in line and "8 Beats Ausklang" in line
    m.set_text("bars", "1")  # rule E: 4 + 4 fade beats > 4 beats
    assert m.cross_issue() is not None and atmos_cost.length_text(m) == ""


# --- render-time estimate -----------------------------------------------------------------------

B = {"schema_version": "0.1", "seed": 1, "bpm": 107, "bars": 32}
# Render times MEASURED in the dev container (Xeon 2.3 GHz, 2026-11-09, 71.8 s files at 48 kHz,
# one process, sequential, other agents on the same 2 cores). The estimate must stay within a
# factor of 2 of each.
MEASURED = [
    ({**B, "kind": "noise_bed"}, 30.30),
    ({**B, "kind": "noise_bed", "filter_mode": "off", "reverb_mix": 0}, 8.24),
    ({**B, "kind": "noise_bed", "reverb_mix": 0}, 21.90),
    ({**B, "kind": "noise_bed", "filter_mode": "off"}, 14.17),
    ({**B, "kind": "noise_bed", "filter_mode": "off", "reverb_mix": 0, "drive": 0.5}, 18.19),
    ({**B, "kind": "drone", "reverb_mix": 0}, 5.25),
    ({**B, "kind": "resonant", "reverb_mix": 0, "filter_mode": "off"}, 8.61),
    ({**B, "kind": "granular", "reverb_mix": 0}, 9.69),
    ({**B, "kind": "granular"}, 15.06),
    ({**B, "kind": "granular", "reverb_mix": 0, "grain_density": 200, "grain_ms": 500}, 33.57),
    ({**B, "kind": "granular", "reverb_mix": 0, "grain_density": 200, "grain_ms": 10}, 10.90),
    ({**B, "bars": 16, "kind": "noise_bed", "loop_mode": "oneshot", "tail_beats": 8}, 6.17),
    ({**B, "bars": 1, "bpm": 200, "kind": "noise_bed", "filter_mode": "off", "reverb_mix": 0.5,
      "reverb_decay_ms": 12000}, 0.77),
]


@pytest.mark.parametrize("params,seconds", MEASURED)
def test_estimate_is_within_a_factor_two_of_the_measured_times(params, seconds) -> None:
    est = atmos_cost.estimate_seconds(get_category("atmos").resolve(params))
    assert seconds / 2 <= est <= seconds * 2, (est, seconds)


def test_note_appears_for_long_files_only_and_counts_variants() -> None:
    for name in PRESETS:  # every shipped preset at one variant: no note
        assert atmos_cost.warning_text(atmos.resolve_atmos_params(load_preset(name, "atmos"))) == ""
    slow = atmos.resolve_atmos_params(MEASURED[9][0])  # ~34 s granular, 72 s file
    text = atmos_cost.warning_text(slow)
    assert text.startswith("Hinweis: geschätzte Renderzeit") and "Grain-Dichte" in text
    assert "8 Varianten" in atmos_cost.warning_text(slow, 8)
    m = CategoryFormModel("atmos")
    assert atmos_cost.cost_note(m) == ""
    for name, text in (("bars", "32"), ("bpm", "107")):
        m.set_active(name, True)
        m.set_text(name, text)
    assert atmos_cost.cost_note(m).startswith("Hinweis")  # 72 s noise bed: ~28 s estimated
    assert m.is_valid  # a note only: the request can still be rendered
    m.set_text("bpm", "abc")
    assert atmos_cost.cost_note(m) == ""
