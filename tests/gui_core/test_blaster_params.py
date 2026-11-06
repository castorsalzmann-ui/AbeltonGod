"""Blaster v2 parameter model (no Qt): contract fields, groups, randomise, undo, A/B, presets,
files, job queue, fire rate, preview profile. Ranges are read from the schema file in the test
itself (a second, independent reader), expected numbers are written out by hand."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from audio_engine import laser
from audio_engine.io import encode_wav
from audio_engine.laser import render_laser
from gui_core import blaster_params as bp
from gui_core.blaster import BlasterSession
from gui_core.blaster_params import BlasterError, BlasterSettings

SCHEMA = json.loads(Path("contracts/laser-params.schema.json").read_text(encoding="utf-8"))
PROPS = dict(SCHEMA["properties"])
for _branch in SCHEMA["allOf"]:
    if _branch["if"]["properties"]["schema_version"]["const"] == "0.2":
        PROPS.update(_branch["then"]["properties"])
HOUSEKEEPING = {"schema_version", "seed", "variants", "bpm", "sample_rate", "bit_depth", "preset"}


def numeric(name):
    return "minimum" in PROPS[name]


# ---- fields come from the contract -------------------------------------------------------------
def test_every_contract_field_has_exactly_one_control_group():
    expected = set(PROPS) - HOUSEKEEPING
    assert set(bp.FIELD_NAMES) == expected
    assert len(bp.FIELD_NAMES) == len(set(bp.FIELD_NAMES))  # no field in two groups
    assert [g.key for g in bp.GROUPS] == ["weapon", "salvo", "filter", "delay", "reverb"]


@pytest.mark.parametrize("name", bp.FIELD_NAMES)
def test_ranges_defaults_and_choices_equal_the_schema_file(name):
    s, raw = bp.spec(name), PROPS[name]
    if numeric(name):
        assert (s.minimum, s.maximum) == (raw["minimum"], raw["maximum"])
        assert (s.kind == "int") == (raw["type"] == "integer")
    else:
        assert list(s.choices) == raw["enum"]
    assert s.default == raw["default"]
    assert bp.default_of(name) == raw["default"]
    assert s.label and s.label != name  # a German label exists


def test_main_controls_are_in_their_groups_and_advanced_do_not_overlap():
    for g in bp.GROUPS:
        assert not set(g.main) & set(g.advanced)
    assert "drive" in bp.GROUP_BY_KEY["weapon"].main and "fm_ratio" in bp.GROUP_BY_KEY[
        "weapon"].advanced


def test_bpm_default_is_the_engines_sync_default_and_only_sent_with_sync():
    assert bp.BPM_DEFAULT == laser.SYNC_DEFAULT_BPM == 120
    assert "bpm" not in bp.to_engine_params(BlasterSettings())
    p = bp.to_engine_params(BlasterSettings().with_values(salvo_rate_mode="sync", bpm=140))
    assert p["bpm"] == 140
    p = bp.to_engine_params(BlasterSettings().with_values(echo_sync="1/8"))
    assert p["bpm"] == 120


# ---- settings: whole range accepted, outside rejected, nothing clamped -------------------------
def random_settings(rng):
    vals = {}
    for n in bp.FIELD_NAMES:
        raw = PROPS[n]
        if "enum" in raw:
            vals[n] = rng.choice(raw["enum"])
        elif raw["type"] == "integer":
            vals[n] = rng.randint(raw["minimum"], raw["maximum"])
        else:
            vals[n] = rng.uniform(raw["minimum"], raw["maximum"])
    return BlasterSettings(vals)


def test_random_settings_over_the_whole_range_pass_the_engines_validation():
    rng = random.Random(5)
    for _ in range(300):
        s = random_settings(rng)
        p = bp.to_engine_params(s)
        resolved = bp.validate_request(p, rng.randint(0, bp.SEED_MAX))
        for n in bp.FIELD_NAMES:  # the engine got exactly what the model holds
            assert resolved[n] == s.get(n), n


def test_range_ends_are_valid_and_just_outside_is_refused_for_every_numeric_field():
    for n in bp.FIELD_NAMES:
        if not numeric(n):
            continue
        lo, hi = PROPS[n]["minimum"], PROPS[n]["maximum"]
        for v in (lo, hi):
            assert BlasterSettings().with_values(**{n: v}).get(n) == v
            bp.validate_request(bp.to_engine_params(BlasterSettings().with_values(**{n: v})))
        step = (hi - lo) * 1e-3 if PROPS[n]["type"] == "number" else 1
        for v in (lo - step, hi + step):
            with pytest.raises(ValueError):
                BlasterSettings().with_values(**{n: v})


@pytest.mark.parametrize("bad", [True, "5", None, float("nan"), float("inf")])
def test_settings_refuse_wrong_types(bad):
    with pytest.raises(ValueError):
        BlasterSettings().with_values(drive=bad)


def test_settings_refuse_unknown_fields_and_bad_choices_and_non_integers():
    with pytest.raises(ValueError, match="Unbekannte Felder"):
        BlasterSettings({"nope": 1})
    with pytest.raises(ValueError):
        BlasterSettings().with_values(family="nope")
    with pytest.raises(ValueError):
        BlasterSettings().with_values(salvo_count=2.5)
    with pytest.raises(ValueError):
        BlasterSettings().with_values(salvo_pan_mode="left")


def test_default_request_is_the_contract_default_and_version_02():
    p = bp.to_engine_params(BlasterSettings())
    assert p["schema_version"] == "0.2" and p["sample_rate"] == 48000 and p["bit_depth"] == 24
    resolved = bp.validate_request(p)
    for n, raw in PROPS.items():
        if "default" in raw and n in resolved:
            assert resolved[n] == raw["default"], n


def test_settings_equality_and_group_in_use():
    a, b = BlasterSettings(), BlasterSettings().with_values(reverb_mix=0.0)
    assert a == b and hash(a) == hash(b)
    assert not a.group_in_use("reverb") and a.with_values(reverb_mix=0.2).group_in_use("reverb")
    assert a.with_values(salvo_count=2).group_in_use("salvo")
    assert a.with_values(hp_hz=100).group_in_use("filter")
    assert a.with_values(lp_sweep_ms=10).group_in_use("filter")


# ---- randomise ---------------------------------------------------------------------------------
def test_randomise_is_deterministic_in_range_and_seed_dependent():
    base = BlasterSettings()
    two = ["weapon", "reverb"]
    assert bp.randomise(base, two, 4) == bp.randomise(base, two, 4)
    assert bp.randomise(base, ["weapon"], 4) != bp.randomise(base, ["weapon"], 5)
    rng = random.Random(8)
    seen = set()
    for _ in range(200):
        s = bp.randomise(base, [g.key for g in bp.GROUPS], rng.randint(0, bp.SEED_MAX))
        bp.validate_request(bp.to_engine_params(s))  # whole contract range, never invalid
        seen.add(s.dimension)
    assert seen == set(PROPS["family"]["enum"])  # every family gets drawn


def test_randomise_touches_only_the_requested_groups_and_groups_are_independent():
    base = BlasterSettings().with_values(drive=0.4, echo_mix=0.5)
    only_reverb = bp.randomise(base, ["reverb"], 9)
    for n in bp.FIELD_NAMES:
        if bp.GROUP_OF[n] != "reverb":
            assert only_reverb.get(n) == base.get(n), n
    assert any(only_reverb.get(n) != base.get(n) for n in bp.GROUP_BY_KEY["reverb"].fields)
    both = bp.randomise(base, ["reverb", "delay"], 9)
    for n in bp.GROUP_BY_KEY["reverb"].fields:  # the reverb draw does not depend on the delay
        assert both.get(n) == only_reverb.get(n)


def test_randomise_leaves_polarity_offset_and_ceiling_alone():
    base = BlasterSettings().with_values(polarity=-1, offset_ms=3.0, peak_ceiling_dbfs=-2.0)
    s = bp.randomise(base, ["weapon"], 1)
    assert (s.get("polarity"), s.get("offset_ms"), s.get("peak_ceiling_dbfs")) == (-1, 3.0, -2.0)


def test_apply_groups_takes_only_allowed_groups():
    base = BlasterSettings().with_values(drive=0.9, reverb_mix=0.9)
    new = BlasterSettings().with_values(drive=0.1, reverb_mix=0.1, echo_mix=0.2)
    out = bp.apply_groups(base, new, ["reverb", "delay"])
    assert (out.get("drive"), out.get("reverb_mix"), out.get("echo_mix")) == (0.9, 0.1, 0.2)


# ---- undo / redo, A/B --------------------------------------------------------------------------
def test_undo_redo_walks_the_recorded_states_and_a_new_change_cuts_redo():
    s0 = BlasterSettings()
    st = bp.UndoStack(s0)
    s1, s2, s3 = s0.with_values(drive=0.1), s0.with_values(drive=0.2), s0.with_values(drive=0.3)
    assert st.record(s1, "a") and st.record(s2, "b")
    assert not st.record(s2, "same")  # unchanged: not recorded
    assert st.undo() == s1 and st.undo() == s0 and st.undo() is None
    assert st.redo() == s1 and st.can_redo()
    assert st.record(s3, "c") and not st.can_redo()
    assert st.undo() == s1


def test_undo_stack_is_bounded():
    st = bp.UndoStack(BlasterSettings(), limit=5)
    for i in range(1, 20):
        st.record(BlasterSettings().with_values(drive=i / 20), "x")
    n = 0
    while st.undo() is not None:
        n += 1
    assert n == 4


def test_ab_slots_keep_two_independent_states():
    a = BlasterSettings().with_values(drive=0.2)
    ab = bp.ABSlots(a)
    b = ab.switch("B", a)
    assert b == a and ab.active == "B"  # B starts as a copy of A
    live_b = a.with_values(drive=0.8)
    assert ab.switch("A", live_b) == a and ab.slots["B"] == live_b
    assert ab.copy_to_other(a.with_values(drive=0.5)) == "B"
    assert ab.slots["A"] == ab.slots["B"] == a.with_values(drive=0.5)
    with pytest.raises(BlasterError):
        ab.switch("C", a)


# ---- fire rate ---------------------------------------------------------------------------------
@pytest.mark.parametrize("note,bpm,ms", [
    ("1/4", 120, 500.0), ("1/8", 120, 250.0), ("1/16", 120, 125.0), ("1/32", 120, 62.5),
    ("1/8T", 120, 250 * 2 / 3), ("1/8D", 120, 375.0), ("1/16D", 150, 150.0),
    ("1/4T", 60, 2000 / 3), ("1/32T", 200, 300 / 8 * 2 / 3),
])
def test_note_lengths_follow_the_contract_table(note, bpm, ms):
    assert bp.note_ms(note, bpm) == pytest.approx(ms)


def test_note_names_all_resolve_and_unknown_is_refused():
    for note in PROPS["salvo_sync_note"]["enum"]:
        assert bp.note_ms(note, 120) > 0
    with pytest.raises(BlasterError):
        bp.note_ms("1/7", 120)


def test_base_gap_and_autofire_interval_per_mode():
    s = BlasterSettings().with_values(salvo_count=3, salvo_spacing_ms=200)
    assert bp.base_gap_ms(s) == 200 and bp.autofire_interval_ms(s) == 600
    s = s.with_values(salvo_rate_mode="hz", salvo_rate_hz=8, salvo_count=2)
    assert bp.base_gap_ms(s) == 125 and bp.autofire_interval_ms(s) == 250
    s = s.with_values(salvo_rate_mode="sync", salvo_sync_note="1/16", bpm=120, salvo_count=4)
    assert bp.base_gap_ms(s) == 125 and bp.autofire_interval_ms(s) == 500
    fast = BlasterSettings().with_values(salvo_count=1, salvo_spacing_ms=20)
    assert bp.autofire_interval_ms(fast) == bp.AUTOFIRE_MIN_MS == 150


# ---- preview profile ---------------------------------------------------------------------------
def test_preview_caps_lower_only_what_is_over_the_cap_and_keep_the_request_valid():
    s = BlasterSettings().with_values(length_ms=5000, decay_ms=2500, salvo_count=5,
                                      reverb_mix=0.3, reverb_decay_ms=5000)
    full, cheap = bp.to_engine_params(s), bp.preview_params(s)
    assert (cheap["length_ms"], cheap["decay_ms"], cheap["salvo_count"],
            cheap["reverb_decay_ms"]) == (800, 400, 2, 600)
    assert (full["length_ms"], full["salvo_count"]) == (5000, 5)  # the real shot is untouched
    assert bp.capped_fields(s) == ["Länge", "Zerfall", "Schüsse", "Nachhall"]
    small = BlasterSettings().with_values(length_ms=300, decay_ms=100)
    assert bp.preview_params(small) == bp.to_engine_params(small)  # reverb off: its tail is moot
    assert not bp.capped_fields(small)
    rng = random.Random(2)
    for _ in range(300):
        c = bp.preview_params(random_settings(rng))
        bp.validate_request(c)
        assert c["length_ms"] <= 800 and c["decay_ms"] <= 400 and c["salvo_count"] <= 2
        assert c["reverb_mix"] == 0 or c["reverb_decay_ms"] <= 600


# ---- presets and files -------------------------------------------------------------------------
def test_every_shipped_preset_loads_and_blaster_presets_come_first():
    names = bp.laser_preset_names()
    assert names and set(names) == set(__import__("audio_engine.presets").presets.preset_names(
        "laser"))
    first_other = next((i for i, n in enumerate(names) if not n.startswith("blaster")), len(names))
    assert all(n.startswith("blaster") for n in names[:first_other])
    for n in names:
        s = bp.load_named_preset(n)
        bp.validate_request(bp.to_engine_params(s))


def test_unknown_preset_is_a_message():
    with pytest.raises(BlasterError, match="unbekannt"):
        bp.load_named_preset("../etc/passwd")


def test_settings_file_round_trip_keeps_every_value_and_the_seed(tmp_path):
    rng = random.Random(21)
    for i in range(30):
        s = random_settings(rng)
        path = tmp_path / f"p{i}.json"
        bp.save_settings_file(path, s, 77 + i, "mein-preset")
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["seed"] == 77 + i and doc["preset"] == "mein-preset"
        assert doc["schema_version"] == "0.2"
        back, seed, name = bp.load_settings_file(path)
        assert back == s and seed == 77 + i and name == "mein-preset"


def test_loading_validates_against_the_contract(tmp_path):
    def load(doc, raw=None):
        p = tmp_path / "x.json"
        p.write_text(raw if raw is not None else json.dumps(doc), encoding="utf-8")
        return bp.load_settings_file(p)

    ok, seed, _ = load({"schema_version": "0.2", "seed": 5, "salvo_count": 3})
    assert ok.get("salvo_count") == 3 and seed == 5
    for bad in (
        {"schema_version": "0.2", "seed": 1, "salvo_count": 9},  # out of range
        {"schema_version": "0.2", "seed": 1, "drive": 1.5},
        {"schema_version": "0.2", "seed": 1, "nonsense": 1},  # unknown field
        {"schema_version": "0.1", "seed": 1, "salvo_count": 2},  # v0.2 field in a v0.1 document
        {"schema_version": "0.9", "seed": 1},
        {"schema_version": "0.2"},  # seed missing
        {"schema_version": "0.2", "seed": 1, "family": "laserbeam"},
    ):
        with pytest.raises(BlasterError, match="Kontrakt"):
            load(bad)
    for raw in ("not json", "[1, 2]", "", "{"):
        with pytest.raises(BlasterError):
            load(None, raw)
    with pytest.raises(BlasterError, match="nicht lesbar"):
        bp.load_settings_file(tmp_path / "missing.json")


def test_loading_refuses_a_huge_file(tmp_path):
    p = tmp_path / "big.json"
    p.write_text(" " * (bp.MAX_FILE_BYTES + 1), encoding="utf-8")
    with pytest.raises(BlasterError, match="zu groß"):
        bp.load_settings_file(p)


def test_saving_into_a_missing_folder_is_a_message_and_leaves_nothing(tmp_path):
    with pytest.raises(BlasterError, match="nicht gespeichert"):
        bp.save_settings_file(tmp_path / "nope" / "a.json", BlasterSettings(), 1)
    assert list(tmp_path.iterdir()) == []


def test_a_preset_written_by_the_repo_loads_like_the_engine_resolves_it():
    for n in bp.laser_preset_names():
        raw = json.loads((Path("src/audio_engine/presets/laser") / f"{n}.json").read_text("utf-8"))
        resolved = laser.resolve_laser_params(raw)
        s = bp.load_named_preset(n)
        for f in bp.FIELD_NAMES:
            if f in resolved:
                assert s.get(f) == resolved[f], (n, f)


# ---- job queue ---------------------------------------------------------------------------------
def test_queue_runs_one_and_keeps_at_most_one_waiting():
    q = bp.JobQueue()
    a, b, c, d = (bp.Job("shot", None, i) for i in range(4))
    assert q.submit(a) == "started" and q.busy
    assert q.submit(b) == "queued" and q.pending is b
    assert q.submit(c) == "replaced" and q.pending is c and q.replaced == 1
    assert q.submit(d) == "replaced" and q.pending is d and q.replaced == 2
    assert q.finish() is d and q.running is d and q.pending is None
    assert q.finish() is None and not q.busy


def test_queue_priorities_preview_never_displaces_a_waiting_shot():
    q = bp.JobQueue()
    q.submit(bp.Job("shot"))
    shot, pre1, pre2 = bp.Job("shot"), bp.Job("preview"), bp.Job("preview")
    q.submit(shot)
    assert q.submit(pre1) == "dropped" and q.pending is shot and q.dropped == 1
    q.finish()
    assert q.submit(pre1) == "queued" and q.submit(pre2) == "replaced" and q.pending is pre2
    assert q.submit(bp.Job("shot")) == "replaced"  # a shot replaces a waiting preview
    bank = bp.Job("bank")
    assert q.submit(bank) == "replaced" and q.pending is bank
    assert q.submit(bp.Job("shot")) == "dropped"


def test_queue_never_holds_more_than_two_jobs_under_random_use():
    rng = random.Random(4)
    q = bp.JobQueue()
    for _ in range(500):
        if rng.random() < 0.3 and q.busy:
            q.finish()
        else:
            q.submit(bp.Job(rng.choice(["preview", "shot", "bank"])))
        assert sum(x is not None for x in (q.running, q.pending)) <= 2
        assert not (q.pending and not q.running)


# ---- byte identity with the engine -------------------------------------------------------------
V01_REFERENCES = [  # (settings values, hand-written engine request without seed)
    ({"family": "pew", "length_ms": 400},
     {"schema_version": "0.1", "family": "pew", "length_ms": 400}),
    ({"family": "plasma", "noise_level": 0.4, "crackle": 0.3, "length_ms": 300},
     {"schema_version": "0.1", "family": "plasma", "noise_level": 0.4, "crackle": 0.3,
      "length_ms": 300}),
    ({"family": "rift", "stereo_width": 0.7, "echo_mix": 0.3, "length_ms": 500, "drive": 0.2},
     {"schema_version": "0.1", "family": "rift", "stereo_width": 0.7, "echo_mix": 0.3,
      "length_ms": 500, "drive": 0.2}),
]
V02_REFERENCES = [
    ({"salvo_count": 3, "salvo_pan_mode": "alternate_lr", "length_ms": 900},
     {"schema_version": "0.2", "salvo_count": 3, "salvo_pan_mode": "alternate_lr",
      "length_ms": 900}),
    ({"family": "glitch", "reverb_mix": 0.3, "reverb_decay_ms": 800, "length_ms": 1200},
     {"schema_version": "0.2", "family": "glitch", "reverb_mix": 0.3, "reverb_decay_ms": 800,
      "length_ms": 1200}),
    ({"family": "ion", "salvo_count": 2, "salvo_rate_mode": "sync", "bpm": 140, "lp_hz": 3000,
      "hp_hz": 200, "echo_mix": 0.3, "echo_sync": "1/8", "length_ms": 1000},
     {"schema_version": "0.2", "family": "ion", "salvo_count": 2, "salvo_rate_mode": "sync",
      "bpm": 140, "lp_hz": 3000, "hp_hz": 200, "echo_mix": 0.3, "echo_sync": "1/8",
      "length_ms": 1000}),
]


def engine_renders_v02():
    try:
        render_laser({"schema_version": "0.2", "salvo_count": 2, "length_ms": 200}, 1)
    except ValueError:
        return False
    return True


def check_bytes(values, request, seed, tmp_path):
    from gui_core.blaster import load_engine

    engine, _ = load_engine()
    session = BlasterSession(engine, None, tmp_path / "w", first_seed=seed)
    try:
        s = BlasterSettings().with_values(**values)
        samples, _params = session.render_shot(s, seed)
        ref = render_laser(request, seed)  # hand-written request, the engine's own entry
        assert encode_wav(samples, 48000, 24) == encode_wav(ref, 48000, 24)
    finally:
        session.close()


@pytest.mark.parametrize("values,request_", V01_REFERENCES)
def test_window_path_is_byte_identical_to_render_laser_for_v01_settings(values, request_,
                                                                         tmp_path):
    check_bytes(values, request_, 7, tmp_path)


@pytest.mark.parametrize("values,request_", V02_REFERENCES)
def test_window_path_is_byte_identical_to_render_laser_for_salvo_filter_reverb(
        values, request_, tmp_path):
    if not engine_renders_v02():
        pytest.skip("this engine version does not render contract v0.2 yet (PR #429)")
    check_bytes(values, request_, 11, tmp_path)


def test_every_shipped_preset_renders_byte_identical_through_the_window_path(tmp_path):
    """Preset file -> model -> request -> engine equals the preset file rendered directly."""
    from gui_core.blaster import load_engine

    names = bp.laser_preset_names()
    assert {"blaster", "blaster-double", "blaster-triple-lrl", "blaster-burst5",
            "blaster-echo", "blaster-reverb"} <= set(names)
    assert names[:6] == sorted(n for n in names if n.startswith("blaster"))
    engine, _ = load_engine()
    session = BlasterSession(engine, None, tmp_path / "w")
    try:
        for n in names:
            raw = json.loads((Path("src/audio_engine/presets/laser") / f"{n}.json")
                             .read_text("utf-8"))
            raw.pop("seed", None)
            raw.pop("preset", None)
            samples, _ = session.render_shot(bp.load_named_preset(n), 5)
            assert encode_wav(samples, 48000, 24) == encode_wav(render_laser(raw, 5), 48000, 24), n
    finally:
        session.close()
