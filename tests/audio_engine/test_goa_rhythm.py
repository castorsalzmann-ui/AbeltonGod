"""Rhythm section from the engines (#392, D-027). Expected values are written in this file
(tick positions, pitches, decays copied from the preset JSON files), not taken from the code
under test; MIDI is read back with the independent parser of test_goa_arrangement."""

import hashlib
import json
import random

import pytest
from test_goa_arrangement import read_smf

from audio_engine import goa_arrangement as ga
from audio_engine import goa_patterns as gp
from audio_engine import goa_rhythm as gr
from audio_engine.io import render_sample_wav
from audio_engine.presets import load_preset, preset_names

PPQ, BAR = 480, 1920
# steps of 16 per bar -> ticks inside the bar (step * 120)
STEPS = {"backbeat": [4, 12], "beat_4": [12], "offbeat_8th": [2, 6, 10, 14],
         "sixteenth_offbeat": [3, 7, 11, 15]}
PITCH = {"snare": 38, "clap": 39, "rim": 37}
MIN_ENERGY = {"snare": 0.62, "clap": 0.46, "rim": 0.38}
# decay_ms written from presets/hat/*.json
HAT_DECAY = {"closed-tight": 35, "closed-std": 70, "closed-loose": 120,
             "open-short": 250, "open-long": 500}


def tracks(**p):
    _, _, t = read_smf(ga.build_midi(**p))
    return {x["name"]: x for x in t[1:]}


def active_ranges(arr, name):
    pos, out = 0, []
    for s in arr["sections"]:
        if name in s["elements"]:
            out.append((pos, pos + s["bars"]))
        pos += s["bars"]
    return out


# ------------------------------------------------------------ percussion voices


@pytest.mark.parametrize("voice", PITCH)
@pytest.mark.parametrize("pattern", STEPS)
def test_perc_part_positions(voice, pattern):
    part = gr.perc_part(voice, pattern)
    assert part["length_beats"] == 4
    assert [round(n["start"] * PPQ) for n in part["notes"]] == [s * 120 for s in STEPS[pattern]]
    assert {n["pitch"] for n in part["notes"]} == {PITCH[voice]}


@pytest.mark.parametrize("seed", range(16))
def test_perc_tracks_property(seed):
    """Random options over the whole option range: tracks exist iff switched on, hits sit on
    the expected ticks of the energy-gated sections that also have a kick."""
    rng = random.Random(seed)
    p = {"seed": seed, "bpm": rng.choice([135, 141.5, 150]), "dj_bars": rng.choice([0, 8, 16]),
         "intro_bars": rng.choice([0, 16]), "breakdowns": rng.choice([0, 1, 2]),
         "outro": rng.choice(["kick_on", "kick_less"])}
    on = {}
    for v in PITCH:
        pat = rng.choice([*STEPS, "none"])
        pre = rng.choice([*preset_names(v), "none"])
        p[f"{v}_pattern"], p[f"{v}_preset"] = pat, pre
        on[v] = pat != "none" and pre != "none"
    arr = ga.build_arrangement(**p)
    t = tracks(**p)
    kick_secs = [s for s in arr["sections"] if "kick" in s["elements"]]
    for v in PITCH:
        assert (v in t) == on[v], v
        if not on[v]:
            assert all(v not in s["elements"] for s in arr["sections"])
            continue
        expect_secs = [s["name"] for s in kick_secs if s["energy"] >= MIN_ENERGY[v]]
        assert [s["name"] for s in arr["sections"] if v in s["elements"]] == expect_secs
        expect = []
        for a, b in active_ranges(arr, v):
            steps = STEPS[p[f"{v}_pattern"]]
            expect += [bar * BAR + st * 120 for bar in range(a, b) for st in steps]
        assert [n[0] for n in t[v]["notes"]] == expect, v
        assert {n[2] for n in t[v]["notes"]} == {PITCH[v]}


def test_all_voices_off_gives_original_six_tracks():
    t = tracks(seed=1, snare_preset="none", clap_pattern="none", rim_preset="none")
    assert list(t) == ["kick", "bass", "lead", "arp", "pad", "pluck", "perc"]


def test_perc_option_changes_only_that_track():
    a = tracks(seed=2, snare_pattern="backbeat")
    b = tracks(seed=2, snare_pattern="beat_4")
    assert a["snare"]["notes"] != b["snare"]["notes"]
    for name in a:
        if name != "snare":
            assert a[name]["notes"] == b[name]["notes"], name


@pytest.mark.parametrize("bad", [dict(snare_pattern="x"), dict(clap_preset="nope"),
                                 dict(rim_preset="goa-roll-short"),  # a bass preset
                                 dict(snare_preset="none", rim_pattern="x")])
def test_perc_invalid_options(bad):
    with pytest.raises(ValueError):
        ga.build_arrangement(**bad)


def test_perc_bytes_deterministic():
    p = dict(seed=5, snare_preset="tight", clap_preset="long", rim_preset="clave",
             rim_pattern="offbeat_8th")
    assert ga.build_midi(**p) == ga.build_midi(**p)


# ------------------------------------------------------------ hat derived from the preset


@pytest.mark.parametrize("preset,bpm", [(k, b) for k in HAT_DECAY for b in (135.0, 150.0)])
def test_hat_part_from_preset(preset, bpm):
    kit = gr.resolve_kit(hat_preset=preset)
    decay_ticks = round(HAT_DECAY[preset] / 1000 * bpm / 60 * PPQ)
    is_open = HAT_DECAY[preset] >= 200
    pitch = 46 if is_open else 42
    fits = decay_ticks <= 120  # one 16th = 120 ticks
    for energy, extra in ((0.3, False), (0.5, True), (0.85, True)):
        notes = gr.hat_part(kit, energy, bpm)["notes"]
        starts = sorted(round(n["start"] * PPQ) for n in notes)
        expect = [480 * b + 240 for b in range(4)]
        if extra and fits:
            expect += [480 * b + o for b in range(4) for o in (120, 360)]
        if energy >= 0.8 and fits:
            expect += [480 * b for b in range(4)]
        assert starts == sorted(expect), (preset, bpm, energy)
        assert {n["pitch"] for n in notes} == {pitch}
        # length: the preset decay, cut one tick before the next hit of the bar
        gaps = {s: (nxt - s - 1) for s, nxt in zip(starts, [*starts[1:], 1920], strict=True)}
        for n in notes:
            s = round(n["start"] * PPQ)
            assert round(n["duration"] * PPQ) == min(decay_ticks, gaps[s])


def test_hat_track_in_arrangement_follows_preset():
    for preset, pitch in (("closed-std", 42), ("closed-loose", 42), ("open-long", 46)):
        p = dict(seed=3, bpm=140.0, hat_preset=preset)
        arr = ga.build_arrangement(**p)
        notes = tracks(**p)["perc"]["notes"]
        assert {n[2] for n in notes} == {pitch}
        # "Peak 2" energy 0.94: 16 hits per bar for closed-std, 4 where 16ths do not fit
        pos = 0
        for s in arr["sections"]:
            if s["name"] == "Peak 2":
                got = [n for n in notes if pos * BAR <= n[0] < (pos + 1) * BAR]
                assert len(got) == (16 if preset == "closed-std" else 4), preset
            pos += s["bars"]


# ------------------------------------------------------------ one source for bass / kick

def test_bass_roll_tables_live_in_goa_rhythm():
    # steps written here; step % 4 == 0 is the kick and never in a roll
    assert gr.ROLL_GRID["off_kick_16th"][0] == (1, 2, 3, 5, 6, 7, 9, 10, 11, 13, 14, 15)
    assert gr.ROLL_GRID["offbeat_8th"][0] == (2, 6, 10, 14)
    assert gr.ROLL_GRID["gallop"][0] == (1, 3, 5, 7, 9, 11, 13, 15)
    assert gr.BASS_POOL == (0, 7, 1, 4)
    assert (gr.GHOST_MAIN_SHARE, gr.GHOST_SIDE_SHARE) == (0.575, 0.33)
    # goa_patterns reads the very same objects (no second copy)
    assert gp._ROLL_GRID is gr.ROLL_GRID and gp._BASS_POOL is gr.BASS_POOL


@pytest.mark.parametrize("roll,allowed", [
    ("off_kick_16th", {120, 240, 360}), ("offbeat_8th", {240}), ("offbeat_ghost", {120, 240, 360}),
    ("gallop", {120, 360}), ("triplet_gallop", {160, 320})])
def test_bass_track_positions_per_roll(roll, allowed):
    for seed in range(4):
        notes = tracks(seed=seed, roll=roll)["bass"]["notes"]
        assert notes and {n[0] % PPQ for n in notes} <= allowed


def test_bass_gate_from_preset():
    for preset, gate_ms in (("goa-roll-short", 62), ("goa-roll-long", 100)):
        notes = tracks(seed=1, roll="offbeat_8th", bass_preset=preset)["bass"]["notes"]
        want = round(gate_ms / 1000 * 145 / 60 * PPQ)
        assert {n[1] - n[0] for n in notes} == {want}


def test_kick_four_on_the_floor():
    part = gr.kick_pattern()
    assert [(round(n["start"] * PPQ), n["pitch"]) for n in part["notes"]] == [
        (0, 36), (480, 36), (960, 36), (1440, 36)]


# ------------------------------------------------------------ README and samples


def test_readme_lists_preset_derived_parts_and_samples(tmp_path):
    out = tmp_path / "o"
    assert ga.main(["--out", str(out), "--seed", "2", "--hat-preset", "open-short",
                    "--snare-preset", "tight", "--snare-pattern", "beat_4",
                    "--clap-preset", "none"]) == 0
    text = (out / "README.md").read_text(encoding="utf-8")
    for needle in ("Derived from a preset", "Chosen by option, not derived from a preset",
                   "250 ms decay: open hat, MIDI 46", "`tight` / `beat_4`",
                   "`none` / `backbeat` (voice off)", "| snare |", "samples/snare_tight.wav"):
        assert needle in text, needle
    assert "| clap |" not in text
    files = sorted(p.name for p in (out / "samples").iterdir())
    stems = ["bass_goa-roll-medium", "hat_open-short", "kick_dense", "rim_rim", "snare_tight"]
    assert files == sorted(f"{s}{ext}" for s in stems for ext in (".json", ".wav"))
    for s in stems:  # #414: every one-shot has its sidecar with category and file name
        meta = json.loads((out / "samples" / f"{s}.json").read_text(encoding="utf-8"))
        assert meta["category"] == s.split("_")[0] and meta["file"] == f"{s}.wav"
        wav_bytes = (out / "samples" / f"{s}.wav").read_bytes()
        assert meta["sha256"] == hashlib.sha256(wav_bytes).hexdigest()
    for cat, preset in (("snare", "tight"), ("rim", "rim"), ("hat", "open-short")):
        wav = (out / "samples" / f"{cat}_{preset}.wav").read_bytes()
        assert wav == render_sample_wav(cat, load_preset(preset, cat))[0]
    # same options again: identical bytes
    out2 = tmp_path / "o2"
    assert ga.main(["--out", str(out2), "--seed", "2", "--hat-preset", "open-short",
                    "--snare-preset", "tight", "--snare-pattern", "beat_4",
                    "--clap-preset", "none"]) == 0
    for f in out.rglob("*"):
        if f.is_file():
            assert same_output(f, out2 / f.relative_to(out)), f


def same_output(a, b) -> bool:
    """Identical bytes; for a sidecar identical except ``created_at`` (the wall clock)."""
    if a.suffix != ".json":
        return a.read_bytes() == b.read_bytes()
    ma, mb = (json.loads(p.read_text(encoding="utf-8")) for p in (a, b))
    return {**ma, "created_at": None} == {**mb, "created_at": None}


def test_sample_sidecars_share_one_given_time_stamp(tmp_path):
    from datetime import UTC, datetime
    stamp = datetime(2026, 11, 6, 13, 0, tzinfo=UTC)
    ga.write_track(tmp_path / "a", seed=3, created_at=stamp)
    ga.write_track(tmp_path / "b", seed=3, created_at=stamp)
    a = sorted((tmp_path / "a" / "samples").glob("*.json"))
    assert len(a) == 6
    for p in a:
        meta = json.loads(p.read_text(encoding="utf-8"))
        assert meta["created_at"] == "2026-11-06T13:00:00+00:00"
        assert p.read_bytes() == (tmp_path / "b" / "samples" / p.name).read_bytes()


def test_an_existing_sidecar_target_blocks_everything(tmp_path):
    out = tmp_path / "o"
    (out / "samples").mkdir(parents=True)
    (out / "samples" / "kick_dense.json").write_text("{}", encoding="utf-8")
    with pytest.raises(FileExistsError, match="kick_dense.json"):
        ga.write_track(out, seed=1)
    assert sorted(p.name for p in out.rglob("*")) == ["kick_dense.json", "samples"]
