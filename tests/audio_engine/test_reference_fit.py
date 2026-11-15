"""Reference steering v2, fit core for kick and bass (#564).

Independence: references are renders of our own engines with parameters drawn here; the
u-maps, contract ranges, band edges and tolerances used to draw and to judge are written in
this file as numbers, not read from the module under test. Nothing here checks, or could
check, how a fit compares to a reference for a listener.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from audio_engine import reference_fit as F
from audio_engine import reference_v2 as V
from audio_engine.bass import render_resolved as render_bass
from audio_engine.bass import resolve_bass_params
from audio_engine.bass_variants import make_variants as bass_variants
from audio_engine.kick import render_resolved as render_kick
from audio_engine.params import resolve_kick_params
from audio_engine.presets import load_preset, preset_names
from audio_engine.variants import make_variants as kick_variants

SR = 48000
RESOLVE = {"kick": resolve_kick_params, "bass": resolve_bass_params}
RENDER = {"kick": render_kick, "bass": render_bass}
TIMING_FIELDS = ("seconds", "candidate_seconds")
GENEROUS_SECONDS = 3600.0  # recovery and machinery tests are bounded by renders, not time


def resolved_form(category: str, params: dict) -> dict:
    """The per-sample resolved form: every default filled, without the batch field."""
    out = RESOLVE[category](dict(params))
    out.pop("variants", None)
    return out


def render(category: str, **changes) -> tuple[dict, np.ndarray]:
    name = "centre" if category == "kick" else "default"
    resolved = resolved_form(category, dict(load_preset(name, category), **changes))
    return resolved, RENDER[category](resolved)


def candidate(category: str, label: str, **changes) -> F.Candidate:
    params, audio = render(category, **changes)
    return F.Candidate(label, params, V.features_from_audio(category, audio, SR),
                       F.profile(category, audio, SR))


def use_candidates(monkeypatch, *cands: F.Candidate) -> None:
    monkeypatch.setattr(F, "candidate_set", lambda category: tuple(cands))


def stable(report: dict) -> dict:
    return {k: v for k, v in report.items() if k not in TIMING_FIELDS}


# --- profile (rule 2.6) -----------------------------------------------------------------------

# 12 log bands from 30 Hz to 16 kHz: edge k = 30 * (16000 / 30) ** (k / 12)
BAND_EDGES_HZ = (30.0, 50.6, 85.5, 144.2, 243.4, 410.8, 693.2, 1169.9, 1974.3, 3331.9, 5622.9,
                 9489.4, 16000.0)


def band_of(hz: float) -> int:
    return max(k for k in range(12) if BAND_EDGES_HZ[k] <= hz)


def test_profile_shape_floor_and_largest_cell():
    t = np.arange(int(0.45 * SR)) / SR
    x = np.sin(2 * np.pi * 1500.0 * t)  # 1500 Hz: the middle of band 7 (1170-1974 Hz)
    p = F.profile("kick", x, SR)
    assert p.shape == (6, 12)
    assert float(p.max()) == 0.0 and float(p.min()) >= -60.0
    # steady tone: the longest zone (250-450 ms) holds the most energy, in the 1.5 kHz band
    assert band_of(1500.0) == 7
    assert np.unravel_index(int(np.argmax(p)), p.shape) == (5, 7)
    # zone energies of a steady tone go with the zone lengths: 150 ms vs 200 ms = -1.25 dB
    assert p[4, 7] == pytest.approx(10 * math.log10(150 / 200), abs=0.1)
    # 5 ms = 7.5 cycles: the rectangular window leaks part of the energy out of the band
    assert p[0, 7] == pytest.approx(10 * math.log10(5 / 200), abs=0.5)
    # the band three octaves down holds only window leakage
    assert p[5, band_of(190.0)] < -40.0


def test_profile_zone_follows_a_known_decay():
    t = np.arange(int(0.45 * SR)) / SR
    x = np.sin(2 * np.pi * 2550.0 * t) * 10 ** (-60.0 * t / 0.3 / 20.0)  # -60 dB after 300 ms
    p = F.profile("kick", x, SR)
    b = band_of(2550.0)  # the middle of band 8 (1974-3332 Hz)

    def zone_energy(a_ms: float, b_ms: float) -> float:  # integral of the squared envelope
        k = 2 * 60.0 / 0.3 / 20.0 * math.log(10)
        return (math.exp(-k * a_ms / 1000) - math.exp(-k * b_ms / 1000)) / k

    zones = [(0, 5), (5, 15), (15, 40), (40, 100), (100, 250), (250, 450)]
    energy = [zone_energy(a, b_) for a, b_ in zones]
    for z, e in enumerate(energy):
        expect = max(-60.0, 10 * math.log10(e / max(energy)))
        assert p[z, b] == pytest.approx(expect, abs=0.5), z


def test_profile_of_silence_and_short_signals():
    assert np.all(F.profile("kick", np.zeros(4800), SR) == -60.0)
    short = np.sin(2 * np.pi * 500.0 * np.arange(int(0.02 * SR)) / SR)  # ends in zone 2
    p = F.profile("kick", short, SR)
    assert np.all(p[3:] == -60.0) and p[1].max() > -10.0


def test_profile_is_the_same_at_both_sample_rates():
    # 85.5, 410.8 and 3331.9 Hz sit on band edges. Measured: 0.02-0.06 units inside a band,
    # 0.10 / 0.17 / 0.24 on those edges (the FFT bin is 2.9 Hz wide at 48 kHz and 2.7 Hz at
    # 44.1 kHz, so a tone on an edge splits a little differently).
    for hz, limit in ((60.0, 0.1), (1000.0, 0.1), (9000.0, 0.1), (85.5, 0.3), (410.8, 0.3),
                      (3331.9, 0.3)):
        a, b = (F.profile("bass", np.sin(2 * np.pi * hz * np.arange(int(0.5 * sr)) / sr), sr)
                for sr in (48000, 44100))
        assert F.profile_distance(a, b) < limit, hz


def test_bass_zones_are_stated_and_differ_from_the_kick():
    assert F.PROFILE_ZONES_MS["kick"] == (0.0, 5.0, 15.0, 40.0, 100.0, 250.0, 450.0)
    assert F.PROFILE_ZONES_MS["bass"] == (0.0, 10.0, 30.0, 60.0, 120.0, 250.0, 500.0)


def test_profile_distance_and_total_count_the_profile_as_one_feature():
    a = np.full((6, 12), -30.0)
    assert F.profile_distance(a, a) == 0.0
    assert F.profile_distance(a, a - 3.0) == pytest.approx(1.0)  # 3 dB everywhere = 1 unit
    assert F.profile_distance(a, a - 6.0) == pytest.approx(2.0)
    table = {"x": V.FeatureScale("lin", 1.0, 1.0, False),
             "y": V.FeatureScale("lin", 1.0, 1.0, False),
             "noise": V.FeatureScale("lin", 1.0, 0.0, False)}
    per = {"x": 3.0, "y": 0.0, "noise": 100.0}
    # (3^2 + 0^2 + 6^2) / 3 = 15: two weighted features plus the profile; weight 0 is left out
    assert F.combined_total(per, 6.0, table) == pytest.approx(math.sqrt(15.0))


# --- u-map ------------------------------------------------------------------------------------

def test_u_map_values_written_here():
    assert F.to_u("log", 200.0, 20.0, 2000.0) == pytest.approx(0.5)
    assert F.from_u("log", 0.5, 20.0, 2000.0) == pytest.approx(200.0)
    assert F.from_u("log", 0.25, 60.0, 600.0) == pytest.approx(106.6968, abs=1e-4)
    assert F.to_u("lin", 0.0, -1.0, 1.0) == pytest.approx(0.5)
    assert F.from_u("lin", 0.75, -1.0, 1.0) == pytest.approx(0.5)
    # u is limited to [0, 1]: no trial outside the contract range
    assert F.from_u("log", 1.7, 20.0, 2000.0) == 2000.0
    assert F.from_u("lin", -0.2, 0.0, 1.0) == 0.0


def test_search_tables_use_contract_ranges_and_log_for_hz_ms_ratio():
    kick = dict(F.SEARCH["kick"])
    bass = dict(F.SEARCH["bass"])
    assert kick == {"pitch_end_hz": "log", "pitch_start_hz": "log", "pitch_decay_ms": "log",
                    "amp_decay_ms": "log", "drive": "lin", "tone": "lin", "click_level": "lin",
                    "click_tone_hz": "log"}
    assert all(kind == ("log" if name.endswith(("_hz", "_ms", "_q")) else "lin")
               for name, kind in bass.items())
    assert "note" not in bass and "cents" not in bass and "seed" not in bass
    assert F._ranges("kick")["amp_decay_ms"] == (20.0, 2000.0)
    assert F._ranges("kick")["pitch_end_hz"] == (30.0, 120.0)
    assert F._ranges("bass")["lp_hz"] == (60.0, 4000.0)
    assert F._ranges("bass")["gate_ms"] == (50.0, 1500.0)


# --- candidate sets ---------------------------------------------------------------------------

@pytest.mark.parametrize(("category", "count", "first"),
                         [("kick", 48, "centre v0"), ("bass", 64, "bright v0")])
def test_candidate_set_is_presets_times_eight_and_cached(category, count, first):
    cands = F.candidate_set(category)
    assert len(cands) == count and cands[0].label == first
    assert F.candidate_set(category) is cands  # once per process
    assert all("variants" not in c.params and c.profile.shape == (6, 12) for c in cands)
    # variant 0 is the preset itself
    preset = resolved_form(category, load_preset(first[:-3], category))
    assert cands[0].params == preset


def test_unknown_category_and_bad_audio_are_refused():
    with pytest.raises(ValueError, match="hat"):
        F.fit_reference("hat", np.zeros(4800), SR)
    for bad in (np.zeros(8), np.zeros((10, 3, 2)), np.full(4800, np.nan)):
        with pytest.raises(ValueError, match="finite mono"):
            F.fit_reference("kick", bad, SR)
    with pytest.raises(ValueError, match="negative"):
        F.fit_reference("kick", np.ones(4800), SR, max_renders=-1)


# --- stage 0, identity, ties ------------------------------------------------------------------

@pytest.mark.parametrize(("category", "index"), [("kick", 13), ("bass", 42)])
def test_identity_a_candidate_as_reference_stays(category, index):
    cand = F.candidate_set(category)[index]
    audio = RENDER[category](cand.params)
    result = F.fit_reference(category, audio, SR, max_seconds=GENEROUS_SECONDS)
    rep = result.report
    assert rep["start_candidate"] == cand.label
    assert rep["total_before"] == 0.0 and rep["total_after"] == 0.0
    assert result.params == cand.params == result.start_params
    assert rep["stop_reason"] == "step"  # the whole search ran and found nothing lower
    assert rep["fit_seed"] == cand.params["seed"]
    assert all(e["status"] != F.TEXT_ESTIMATE_KEPT for e in rep["stage1"])


def test_ties_go_to_the_first_candidate_in_grid_order(monkeypatch):
    first, second = candidate("kick", "first"), candidate("kick", "second")
    use_candidates(monkeypatch, first, second)
    _, audio = render("kick")
    rep = F.fit_reference("kick", audio, SR, max_renders=0).report
    assert rep["start_candidate"] == "first" and rep["total_before"] == 0.0
    use_candidates(monkeypatch, second, first)
    assert F.fit_reference("kick", audio, SR, max_renders=0).report["start_candidate"] == "second"


def test_stage0_picks_the_nearest_candidate(monkeypatch):
    use_candidates(monkeypatch, candidate("kick", "long", amp_decay_ms=900, length_ms=900),
                   candidate("kick", "short", amp_decay_ms=150, length_ms=300))
    _, audio = render("kick", amp_decay_ms=160, length_ms=300)
    rep = F.fit_reference("kick", audio, SR, max_renders=0).report
    assert rep["start_candidate"] == "short" and rep["total_before"] > 0.0


# --- budget, time, cancel, rejected trials ----------------------------------------------------

def far_kick() -> np.ndarray:
    return render("kick", seed=4242, pitch_start_hz=330, pitch_end_hz=41, pitch_decay_ms=22,
                  amp_decay_ms=250, click_level=0.8, drive=0.3, length_ms=380)[1]


def test_render_budget_stops_the_search_and_caps_every_render():
    audio = far_kick()
    result = F.fit_reference("kick", audio, SR, max_renders=40, max_seconds=GENEROUS_SECONDS)
    rep = result.report
    assert rep["stop_reason"] == "renders" and rep["stop_label"] == "Render-Budget erreicht"
    assert 0 < rep["renders"] <= 40 and rep["max_renders"] == 40
    assert rep["total_after"] <= rep["total_before"]
    # the determination check is inside the budget: 16 renders were held back for it
    assert all(p["determined"] is not None for p in rep["parameters"])
    assert resolved_form("kick", result.params) == result.params


def test_zero_renders_returns_the_start_candidate_unchecked():
    result = F.fit_reference("kick", far_kick(), SR, max_renders=0)
    rep = result.report
    assert rep["renders"] == 0 and rep["stop_reason"] == "renders"
    assert result.params == result.start_params
    assert rep["total_after"] == rep["total_before"]
    assert all(p["determined"] is None and p["flag"] == "nicht geprüft"
               for p in rep["parameters"])


def test_time_budget_with_an_injected_clock():
    ticks = iter(range(10_000))
    result = F.fit_reference("kick", far_kick(), SR, max_renders=300, max_seconds=12.0,
                             clock=lambda: float(next(ticks)))
    rep = result.report
    assert rep["stop_reason"] == "time" and rep["stop_label"] == "Zeit-Budget erreicht"
    # the clock advances 1 s per reading and is read once before every render
    assert 0 < rep["renders"] <= 12
    assert rep["total_after"] <= rep["total_before"]
    assert resolved_form("kick", result.params) == result.params


def test_cancel_returns_the_best_point_so_far():
    audio = far_kick()
    calls = {"n": 0}

    def cancel_after_25() -> bool:
        calls["n"] += 1
        return calls["n"] > 25

    result = F.fit_reference("kick", audio, SR, max_seconds=GENEROUS_SECONDS,
                             cancel=cancel_after_25)
    rep = result.report
    assert rep["stop_reason"] == "cancelled" and rep["stop_label"] == "abgebrochen"
    assert rep["renders"] == 25
    assert rep["total_after"] <= rep["total_before"]
    # the same 25 renders as an uncancelled fit with that render budget would find at best
    full = F.fit_reference("kick", audio, SR, max_seconds=GENEROUS_SECONDS)
    assert full.report["total_after"] <= rep["total_after"]
    assert all(p["determined"] is None for p in rep["parameters"])

    at_once = F.fit_reference("kick", audio, SR, cancel=lambda: True)
    assert at_once.report["stop_reason"] == "cancelled" and at_once.report["renders"] == 0
    assert at_once.params == at_once.start_params


def test_contract_refusals_are_counted_and_never_clamped(monkeypatch):
    # start with pitch_start_hz just above pitch_end_hz: moving either across the other is
    # refused by the contract's pitch-order rule
    use_candidates(monkeypatch, candidate("kick", "narrow", pitch_start_hz=64, pitch_end_hz=60))
    _, audio = render("kick", pitch_start_hz=66, pitch_end_hz=61, seed=77)
    result = F.fit_reference("kick", audio, SR, max_renders=120, max_seconds=GENEROUS_SECONDS)
    rep = result.report
    assert rep["rejected_trials"] > 0
    assert result.params["pitch_end_hz"] <= result.params["pitch_start_hz"]
    assert resolved_form("kick", result.params) == result.params
    assert rep["total_after"] <= rep["total_before"]


def test_bass_cross_field_refusals_are_counted(monkeypatch):
    # hp_hz 30 with note 36 (65.4 Hz): raising hp_hz past 0.8 f0 = 52.3 Hz is refused
    use_candidates(monkeypatch, candidate("bass", "roll", note=36, hp_hz=30, lp_hz=320))
    _, audio = render("bass", note=36, hp_hz=45, lp_hz=300, gate_ms=180)
    result = F.fit_reference("bass", audio, SR, max_seconds=GENEROUS_SECONDS)
    assert result.report["rejected_trials"] > 0
    assert resolved_form("bass", result.params) == result.params


# --- stage 1 ----------------------------------------------------------------------------------

def test_bass_note_without_and_with_sub_octave(monkeypatch):
    use_candidates(monkeypatch, candidate("bass", "g2"))  # note 43, no sub-octave
    _, plain = render("bass", note=33, cents=20)
    result = F.fit_reference("bass", plain, SR, max_renders=40, max_seconds=GENEROUS_SECONDS)
    entry = result.report["stage1"][0]
    assert entry["parameter"] == "note" and entry["status"] == "übernommen"
    assert entry["method"] == "note"
    assert result.params["note"] == 33 and result.params["cents"] == pytest.approx(20, abs=2)

    # with a sub-octave the waveform period is f0 / 2: the note is one octave above note_hz
    _, with_sub = render("bass", note=45, sub_octave_level=0.8)
    assert V.features_from_audio("bass", with_sub, SR)["note_hz"] == pytest.approx(55.0, rel=0.01)
    result = F.fit_reference("bass", with_sub, SR, max_renders=40, max_seconds=GENEROUS_SECONDS)
    entry = result.report["stage1"][0]
    assert entry["method"] == "note + sub_octave_level" and entry["status"] == "übernommen"
    assert result.params["note"] == 45 and result.params["sub_octave_level"] > 0


def test_bass_note_estimate_lowers_hp_when_the_contract_needs_it(monkeypatch):
    use_candidates(monkeypatch, candidate("bass", "hp", note=43, hp_hz=60, lp_hz=350))
    _, audio = render("bass", note=26)  # 36.7 Hz: hp_hz must be below 29.4 Hz
    result = F.fit_reference("bass", audio, SR, max_renders=40, max_seconds=GENEROUS_SECONDS)
    entry = result.report["stage1"][0]
    assert entry["status"] == "übernommen" and entry["rejected_by_contract"] >= 1
    assert "hp_hz auf 20 Hz gesetzt" in entry["detail"]
    assert result.params["note"] == 26


def test_an_estimate_that_raises_the_total_is_dropped(monkeypatch):
    use_candidates(monkeypatch, candidate("kick", "centre"))
    _, audio = render("kick", seed=5, amp_decay_ms=500)
    real = F._ratio_hypotheses

    def wrong(param, cur, ref, features):
        if param == "pitch_end_hz":
            return [F._Hypothesis("direkt", {"pitch_end_hz": 110.0}, "falsch")]
        return real(param, cur, ref, features)

    monkeypatch.setattr(F, "_ratio_hypotheses", wrong)
    result = F.fit_reference("kick", audio, SR, max_renders=20, max_seconds=GENEROUS_SECONDS)
    entry = next(e for e in result.report["stage1"] if e["parameter"] == "pitch_end_hz")
    assert entry["status"] == "Schätzung verworfen"
    assert entry["estimate"] == {"pitch_end_hz": 110.0}
    assert entry["total_with_estimate"] > result.report["total_before"]
    assert result.params["pitch_end_hz"] == 52


def test_kick_length_comes_from_the_reference(monkeypatch):
    use_candidates(monkeypatch, candidate("kick", "centre"))  # length_ms 480
    _, audio = render("kick", length_ms=200, seed=3)
    result = F.fit_reference("kick", audio, SR, max_renders=20, max_seconds=GENEROUS_SECONDS)
    entry = result.report["stage1"][0]
    assert entry["parameter"] == "length_ms" and entry["status"] == "übernommen"
    assert result.params["length_ms"] == pytest.approx(200.0, abs=1.0)


def test_unmeasurable_reference_values_are_reported_not_guessed(monkeypatch):
    use_candidates(monkeypatch, candidate("kick", "centre"))
    rng = np.random.Generator(np.random.PCG64(11))
    noise = rng.standard_normal(int(0.1 * SR)) * np.linspace(1.0, 0.9, int(0.1 * SR))
    rep = F.fit_reference("kick", noise, SR, max_renders=30,
                          max_seconds=GENEROUS_SECONDS).report
    missing = [f for f in rep["features"] if f["reference"] is None]
    assert missing and all(f["note"] == "nicht messbar" for f in missing)
    decay = next(e for e in rep["stage1"] if e["parameter"] == "amp_decay_ms")
    assert decay["status"] == "nicht messbar" and decay["estimate"] is None
    assert rep["total_after"] <= rep["total_before"]


# --- report -----------------------------------------------------------------------------------

def test_report_is_json_and_complete(monkeypatch):
    result = F.fit_reference("kick", far_kick(), SR, max_renders=60,
                             max_seconds=GENEROUS_SECONDS)
    text = result.to_json()  # allow_nan=False: no inf or nan anywhere
    data = json.loads(text)
    rep = data["report"]
    assert data["params"] == result.params
    assert [f["name"] for f in rep["features"]] == list(V.FEATURES["kick"])
    for f in rep["features"]:
        assert {"reference", "start", "fit", "distance_before", "distance_after", "weight",
                "fit_scale", "calibrated_scale", "provisional_scale", "scale_source"} <= set(f)
    assert rep["profile"]["label"] == "Form (nur für die Suche)"
    assert {"distance_before", "distance_after"} <= set(rep["profile"])
    assert [p["name"] for p in rep["parameters"]] == [n for n, _ in F.SEARCH["kick"]]
    for p in rep["parameters"]:
        assert p["start"] == result.start_params[p["name"]]
        assert p["fit"] == result.params[p["name"]]
        assert p["flag"] in ("festgelegt", "von den Messwerten nicht festgelegt")
    assert rep["fit_seed"] == result.params["seed"] == result.start_params["seed"]
    assert rep["scales"]["table_loaded"] is True and rep["scales"]["table_message"] == ""
    assert {"renders", "seconds", "stop_reason", "rejected_trials", "total_before",
            "total_after", "stage1", "weak_by_design", "pitch_settles"} <= set(rep)
    # the total is the weighted features plus the profile as one feature
    table = V.feature_table("kick")
    for side in ("before", "after"):
        squares = sum(table[f["name"]].weight * f[f"distance_{side}"] ** 2
                      for f in rep["features"]) + rep["profile"][f"distance_{side}"] ** 2
        weights = sum(fs.weight for fs in table.values()) + 1.0
        assert rep[f"total_{side}"] == pytest.approx(math.sqrt(squares / weights))


def test_scale_source_is_reported(monkeypatch):
    use_candidates(monkeypatch, candidate("kick", "centre"))
    _, audio = render("kick", seed=9)
    rep = F.fit_reference("kick", audio, SR, max_renders=0).report
    assert rep["scales"]["table_loaded"] is True
    assert rep["scales"]["rule"] == "fit scale = max(calibrated scale, provisional scale)"
    assert sorted(rep["scales"]["set_by_calibrated"] + rep["scales"]["set_by_provisional"]) \
        == sorted(V.FEATURES["kick"])
    message = "Die Kalibriertabelle fehlt (test); es gelten vorläufige Skalen."
    monkeypatch.setattr(V, "calibration_status", lambda path=None: SimpleNamespace(
        loaded=False, reason="missing", message=message, table={}))
    rep = F.fit_reference("kick", audio, SR, max_renders=0).report
    assert rep["scales"]["table_loaded"] is False and rep["scales"]["table_message"] == message
    assert rep["scales"]["set_by_provisional"] == list(V.FEATURES["kick"])
    assert all(f["calibrated_scale"] is None and f["weight"] == 1.0 for f in rep["features"])


def fake_table(category: str, scales: dict[str, float], weights: dict[str, float]):
    rows = {n: {"scale": scales.get(n, 1e-3), "weight": weights.get(n, 1.0)}
            for n in V.FEATURES[category]}
    return SimpleNamespace(loaded=True, reason="loaded", message="",
                           table={"categories": {category: {"features": rows}}})


def test_fit_scale_is_the_larger_of_calibrated_and_provisional(monkeypatch):
    # provisional scales of the note's section 3: kick body_hz 2 semitones, sub_share 0.05,
    # decay_20db_ms ln 1.25; bass attack_ms ln 1.3, note_hz 0.1 semitones
    monkeypatch.setattr(V, "calibration_status", lambda path=None: fake_table(
        "kick", {"body_hz": 0.00036, "sub_share": 0.2, "decay_20db_ms": math.log(1.25)},
        {"click_share": 0.0}))
    rows = F.fit_scales("kick").rows
    assert rows["body_hz"].fit.scale == 2.0 and rows["body_hz"].source == "provisional"
    assert rows["body_hz"].calibrated == 0.00036 and rows["body_hz"].provisional == 2.0
    assert rows["sub_share"].fit.scale == 0.2 and rows["sub_share"].source == "calibrated"
    assert rows["decay_20db_ms"].source == "calibrated"  # equal: the table's value stands
    assert rows["click_share"].fit.weight == 0.0  # weights are the table's
    monkeypatch.setattr(V, "calibration_status", lambda path=None: fake_table(
        "bass", {"attack_ms": 2.062743, "note_hz": 0.00386}, {}))
    rows = F.fit_scales("bass").rows
    assert rows["attack_ms"].fit.scale == 2.062743 and rows["attack_ms"].source == "calibrated"
    assert rows["note_hz"].fit.scale == pytest.approx(0.1)
    assert rows["note_hz"].source == "provisional"


def test_report_distances_use_the_fit_scale(monkeypatch):
    use_candidates(monkeypatch, candidate("kick", "centre"))  # pitch_end_hz 52
    _, audio = render("kick", pitch_end_hz=58, seed=2)
    rep = F.fit_reference("kick", audio, SR, max_renders=0).report
    row = next(f for f in rep["features"] if f["name"] == "fundamental_hz")
    assert row["provisional_scale"] == 1.0 and row["calibrated_scale"] < 0.1
    assert row["scale_source"] == "provisional" and row["fit_scale"] == 1.0
    semitones = abs(12 * math.log2(row["reference"] / row["start"]))
    assert 1.0 < semitones < 3.0  # 52 -> 58 Hz is 1.9 semitones
    assert row["distance_before"] == pytest.approx(semitones / 1.0)


def test_no_listening_or_likeness_wording():
    source = Path(F.__file__).read_text(encoding="utf-8").lower()
    report = F.fit_reference("bass", render("bass", note=40)[1], SR,
                             max_renders=30).to_json().lower()
    for word in ("ähnlich", "klingt", "klang", "similar", "sounds like", "resembl"):
        assert word not in report, word
        assert word not in source, word


def test_determination_flag_on_a_parameter_without_effect(monkeypatch):
    # contract: lp_env_decay_ms has no effect at lp_env_amount 0
    use_candidates(monkeypatch, candidate("bass", "flat", lp_env_amount=0, drive=0))
    _, audio = render("bass", lp_env_amount=0, drive=0)
    rep = F.fit_reference("bass", audio, SR, max_seconds=GENEROUS_SECONDS).report
    rows = {p["name"]: p for p in rep["parameters"]}
    assert rows["lp_env_decay_ms"]["determined"] is False
    assert rows["lp_env_decay_ms"]["flag"] == "von den Messwerten nicht festgelegt"
    assert rows["lp_env_decay_ms"]["cost_change_minus"] == 0.0
    assert rows["gate_ms"]["determined"] is True and rows["gate_ms"]["flag"] == "festgelegt"
    # drive is 0 = the lower edge: that side gives no evidence and is named
    assert rows["drive"]["side_minus"] == "Rand des Wertebereichs"
    assert rows["drive"]["cost_change_minus"] is None


def test_fit_from_a_read_reference_carries_the_reader_flags(monkeypatch):
    use_candidates(monkeypatch, candidate("kick", "centre"))
    _, audio = render("kick", seed=8)
    stereo = np.stack([audio, audio], axis=1)
    ref = V.ReferenceAudioV2(stereo, SR, 2, 24, "pcm", 1, len(stereo), False)
    result = F.fit_reference_audio(ref, "kick", max_renders=20)
    assert result.report["reference"] == {"sample_rate": SR, "channels": 2, "hit_count": 1,
                                          "multi_hit": False, "censored_tail": False}
    json.loads(result.to_json())


# --- determinism ------------------------------------------------------------------------------

def test_same_reference_twice_in_one_process():
    audio = far_kick()
    a = F.fit_reference("kick", audio, SR, max_renders=80, max_seconds=GENEROUS_SECONDS)
    b = F.fit_reference("kick", audio, SR, max_renders=80, max_seconds=GENEROUS_SECONDS)
    assert a.params == b.params
    assert stable(a.report) == stable(b.report)


_CHILD = """
import hashlib, json, sys
from audio_engine import reference_fit as F
from audio_engine.bass import render_resolved as rb, resolve_bass_params
from audio_engine.kick import render_resolved as rk
from audio_engine.params import resolve_kick_params
from audio_engine.presets import load_preset
out = {}
for cat, resolve, render, name, changes in (
        ("kick", resolve_kick_params, rk, "punchy", {"seed": 31, "amp_decay_ms": 300}),
        ("bass", resolve_bass_params, rb, "rolling", {"note": 38, "lp_hz": 500})):
    p = resolve({k: v for k, v in dict(load_preset(name, cat), **changes).items()
                 if k != "variants"})
    r = F.fit_reference(cat, render(p), 48000, max_renders=70, max_seconds=3600.0)
    rep = {k: v for k, v in r.report.items() if k not in ("seconds", "candidate_seconds")}
    text = json.dumps({"params": r.params, "report": rep}, sort_keys=True)
    out[cat] = [hashlib.sha256(text.encode()).hexdigest(), r.report["renders"]]
print(json.dumps(out))
"""


def test_same_reference_in_two_processes():
    env = dict(os.environ, PYTHONPATH=str(Path(F.__file__).resolve().parents[1]),
               PYTHONHASHSEED="random")
    runs = []
    for _ in range(2):
        done = subprocess.run([sys.executable, "-c", _CHILD], env=env, capture_output=True,
                              text=True, timeout=600, check=False)
        assert done.returncode == 0, done.stderr
        runs.append(json.loads(done.stdout))
    assert runs[0] == runs[1]
    assert runs[0]["kick"][1] > 0 and runs[0]["bass"][1] > 0
    assert len(hashlib.sha256(b"").hexdigest()) == len(runs[0]["kick"][0])


# --- recovery of synthetic references (note section 7) ----------------------------------------
#
# References are renders of our own engines with known parameters, so this is an upper bound
# for real references ("inverse crime", note "For workers"). Truth = a preset variant drawn
# with PCG64, each searched parameter replaced: box (a) u +- 0.15 around the variant's value,
# box (b) u uniform in [0, 1]. A truth the contract refuses is drawn again. The space below
# (map and contract range per parameter) is written here, not read from the fit.

REFERENCE_SEED = 987654  # no candidate uses it (their seeds are 1 ... 1005 plus variant offsets)
DRAW_SEED = {("kick", "a"): 52201, ("bass", "a"): 52202, ("kick", "b"): 52203,
             ("bass", "b"): 52204}
BOX_COUNT = {"a": 8, "b": 4}
BOX_B_RENDERS = 100  # box (b) asserts only after <= before; long bass notes render slowly
SPACE = {
    "kick": {
        "pitch_end_hz": ("log", 30, 120), "pitch_start_hz": ("log", 60, 600),
        "pitch_decay_ms": ("log", 2, 300), "amp_decay_ms": ("log", 20, 2000),
        "drive": ("lin", 0, 1), "tone": ("lin", -1, 1), "click_level": ("lin", 0, 1),
        "click_tone_hz": ("log", 500, 12000),
    },
    "bass": {
        "saw_level": ("lin", 0, 1), "square_level": ("lin", 0, 1), "sine_level": ("lin", 0, 1),
        "sub_octave_level": ("lin", 0, 1), "drive": ("lin", 0, 1), "lp_hz": ("log", 60, 4000),
        "hp_hz": ("log", 20, 120), "lp_q": ("log", 0.5, 6), "lp_env_amount": ("lin", 0, 4),
        "lp_env_decay_ms": ("log", 5, 800), "amp_attack_ms": ("log", 0.5, 30),
        "gate_ms": ("log", 50, 1500), "release_ms": ("log", 5, 400),
    },
}
# Tolerances, measured on the draws below (tables in the PR of #564). "rel" = |fit / truth - 1|,
# "abs" = |fit - truth|. Tier A: every box (a) reference. Tier B: at least the stated number
# of the 8 box (a) references. Tier C: not asserted; must be flagged or listed as weak.
TIER_A = {
    "kick": {"pitch_end_hz": ("rel", 0.12)},
    "bass": {"note": ("abs", 0), "cents": ("abs", 10.0)},
}
TIER_B = {
    "kick": {"pitch_start_hz": ("rel", 0.12, 6), "amp_decay_ms": ("rel", 0.12, 5),
             "pitch_decay_ms": ("rel", 0.25, 6), "drive": ("abs", 0.12, 5)},
    "bass": {"gate_ms": ("rel", 0.20, 7), "lp_hz": ("rel", 0.35, 6), "drive": ("abs", 0.1, 5)},
}
TIER_C = {
    "kick": ("tone", "click_level", "click_tone_hz"),
    "bass": ("saw_level", "square_level", "sine_level", "sub_octave_level", "hp_hz", "lp_q",
             "lp_env_amount", "lp_env_decay_ms", "amp_attack_ms", "release_ms"),
}


def _u(kind: str, value: float, lo: float, hi: float) -> float:
    return math.log(value / lo) / math.log(hi / lo) if kind == "log" else (value - lo) / (hi - lo)


def _value(kind: str, u: float, lo: float, hi: float) -> float:
    u = min(1.0, max(0.0, u))
    return round(lo * (hi / lo) ** u if kind == "log" else lo + (hi - lo) * u, 4)


def preset_variants(category: str) -> list[dict]:
    make = kick_variants if category == "kick" else bass_variants
    return [resolved_form(category, v) for name in preset_names(category)
            for v in make(load_preset(name, category), 8)]


def draw_references(category: str, box: str) -> list[tuple[dict, np.ndarray]]:
    rng = np.random.Generator(np.random.PCG64(DRAW_SEED[category, box]))
    bases = preset_variants(category)
    out = []
    while len(out) < BOX_COUNT[box]:
        base = bases[int(rng.integers(len(bases)))]
        truth = dict(base)
        for name, (kind, lo, hi) in SPACE[category].items():
            u = _u(kind, base[name], lo, hi) + float(rng.uniform(-0.15, 0.15)) if box == "a" \
                else float(rng.uniform())
            truth[name] = _value(kind, u, lo, hi)
        if category == "bass":  # note 24 ... 55 and cents -50 ... 50 by the same rule
            if box == "a":
                un = (base["note"] - 24) / 31 + float(rng.uniform(-0.15, 0.15))
                uc = (base["cents"] + 50) / 100 + float(rng.uniform(-0.15, 0.15))
            else:
                un, uc = float(rng.uniform()), float(rng.uniform())
            truth["note"] = int(round(24 + 31 * min(1.0, max(0.0, un))))
            truth["cents"] = round(-50 + 100 * min(1.0, max(0.0, uc)), 4)
        truth["seed"] = REFERENCE_SEED
        try:
            truth = resolved_form(category, truth)
        except ValueError:
            continue
        out.append((truth, RENDER[category](truth)))
    return out


def _error(mode: str, fit: float, truth: float) -> float:
    return abs(fit / truth - 1.0) if mode == "rel" else abs(fit - truth)


def recovery_rows(category: str, box: str, max_renders: int | None = None) -> list[dict]:
    """One row per reference: truth, fit result and signed errors (also used for the PR
    tables: run with ``-s`` to see them)."""
    rows = []
    names = list(SPACE[category]) + (["note", "cents"] if category == "bass" else [])
    for i, (truth, audio) in enumerate(draw_references(category, box), start=1):
        result = F.fit_reference(category, audio, SR, max_renders=max_renders,
                                 max_seconds=GENEROUS_SECONDS)
        rep = result.report
        flagged = {p["name"] for p in rep["parameters"] if p["determined"] is False}
        cells = []
        for n in names:
            kind = SPACE[category].get(n, ("lin",))[0]
            cell = f"{(result.params[n] / truth[n] - 1) * 100:+.0f} %" if kind == "log" \
                else f"{result.params[n] - truth[n]:+.2f}"
            cells.append(cell + ("*" if n in flagged else ""))
        print(f"| {i} | {rep['total_before']:.2f} -> {rep['total_after']:.2f} | "
              f"{rep['renders']} | {rep['seconds']:.1f} | {rep['stop_reason']} | "
              + " | ".join(cells) + " |")
        rows.append({"index": i, "truth": truth, "result": result})
    return rows


@pytest.mark.parametrize("category", ["kick", "bass"])
def test_recovery_near_presets_box_a(category):
    rows = recovery_rows(category, "a")
    assert len(rows) >= 8
    problems = []
    for row in rows:
        truth, result, rep = row["truth"], row["result"], row["result"].report
        assert truth["seed"] != rep["fit_seed"]
        if not rep["total_after"] <= rep["total_before"]:
            problems.append(f"ref {row['index']}: after {rep['total_after']} > before")
        if rep["stop_reason"] not in ("step", "renders"):
            problems.append(f"ref {row['index']}: stop reason {rep['stop_reason']}")
        if rep["renders"] > 300:
            problems.append(f"ref {row['index']}: {rep['renders']} renders")
        for name, (mode, tol) in TIER_A[category].items():
            e = _error(mode, result.params[name], truth[name])
            if e > tol:
                problems.append(f"tier A ref {row['index']} {name}: fit {result.params[name]}"
                                f", truth {truth[name]}, error {e:.3f} > {tol}")
        flagged = {p["name"] for p in rep["parameters"] if p["determined"] is False}
        for name in TIER_C[category]:
            if name not in flagged and name not in rep["weak_by_design"]:
                problems.append(f"tier C ref {row['index']} {name}: neither flagged nor weak")
    for name, (mode, tol, need) in TIER_B[category].items():
        hits = sum(_error(mode, r["result"].params[name], r["truth"][name]) <= tol
                   for r in rows)
        if hits < need:
            problems.append(f"tier B {name}: {hits} of {len(rows)} within {tol}, need {need}")
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("category", ["kick", "bass"])
def test_recovery_full_range_box_b(category):
    rows = recovery_rows(category, "b", max_renders=BOX_B_RENDERS)
    assert len(rows) >= 4
    for row in rows:
        rep = row["result"].report
        assert rep["total_after"] <= rep["total_before"], row["index"]
        assert rep["stop_reason"] in ("step", "renders"), row["index"]
        assert rep["stop_label"] == F.STOP_LABEL[rep["stop_reason"]]
        assert rep["renders"] <= BOX_B_RENDERS
        assert resolved_form(category, row["result"].params) == row["result"].params


def test_tiers_cover_every_searched_parameter_once():
    for category in ("kick", "bass"):
        tiers = [*TIER_A[category], *TIER_B[category], *TIER_C[category]]
        searched = [n for n, _ in F.SEARCH[category]]
        extra = ["note", "cents"] if category == "bass" else []
        assert sorted(tiers) == sorted(searched + extra)
        assert set(F.WEAK_BY_DESIGN[category]) == set(TIER_C[category])
