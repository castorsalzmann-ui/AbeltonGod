"""Issue #7: envelope semantics of kick-params and the pitch-settle guideline.

Expected values are written here from the contract text (kick-params v0.2 descriptions) or
measured with zero crossings; nothing is taken from the helper under test.
"""

from __future__ import annotations

import random

import numpy as np
import pytest

import audio_engine.io as io_mod
from audio_engine.analysis import analyse
from audio_engine.kick import render_kick
from audio_engine.params import (
    KICK_SCHEMA_FILE,
    load_schema,
    max_settled_pitch_decay_ms,
    pitch_settles,
)

BASE = {"schema_version": "0.2", "seed": 7}
BODY_ONLY = {"click_level": 0.0, "drive": 0.0, "tone": 0.0}
END_MARGIN_S = 0.006  # stay out of the 5 ms fade-out (see analysis.TAIL_END_MARGIN_MS)


# --- contract text ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field", ["pitch_start_hz", "pitch_end_hz", "pitch_decay_ms", "amp_attack_ms", "amp_decay_ms"]
)
def test_envelope_fields_are_described(field: str) -> None:
    assert len(load_schema(KICK_SCHEMA_FILE)["properties"][field].get("description", "")) > 30


def test_schema_version_and_new_default() -> None:
    schema = load_schema(KICK_SCHEMA_FILE)
    assert schema["properties"]["schema_version"]["const"] == "0.2"
    assert schema["properties"]["pitch_decay_ms"]["default"] == 15


# --- guideline helper: hand-computed values ---------------------------------------------------
# t = min(attack + amp_decay / 3, length); limit = t / ln((f_start - f_end) / (0.05 * f_end))

HAND_CASES = [
    # defaults: t = 0.5 + 320/3 = 107.1667, ln(172 / 2.4) = 4.27201 -> 25.0858
    ({}, 25.0858),
    # cut off: t = min(20 + 2000/3, 80) = 80, ln(172 / 2.4) -> 18.7265
    ({"length_ms": 80, "amp_attack_ms": 20, "amp_decay_ms": 2000}, 18.7265),
    # wide drop: t = 0.5 + 2000/3 = 667.1667, ln(570 / 1.5) = ln 380 = 5.94017 -> 112.3144
    (
        {"amp_decay_ms": 2000, "length_ms": 2000, "pitch_start_hz": 600, "pitch_end_hz": 30},
        112.3144,
    ),
    # long and gentle: t = 667.1667, ln(90 / 1.5) = ln 60 = 4.09434 -> 162.9483
    (
        {"amp_decay_ms": 2000, "length_ms": 2000, "pitch_start_hz": 120, "pitch_end_hz": 30},
        162.9483,
    ),
    # drop within 5 %: 60 - 58 = 2 <= 2.9 -> schema maximum
    ({"pitch_start_hz": 60, "pitch_end_hz": 58}, 300.0),
    # very slow decay, capped at the schema maximum: t = 667.1667, ln(30 / 4.5) = 1.89712
    (
        {"amp_decay_ms": 2000, "length_ms": 2000, "pitch_start_hz": 120, "pitch_end_hz": 90},
        300.0,
    ),
    # nothing settles in time: t = 0 + 20/3 = 6.6667, ln(570 / 1.5) -> 1.1223 (< schema min 2)
    (
        {"amp_attack_ms": 0, "amp_decay_ms": 20, "pitch_start_hz": 600, "pitch_end_hz": 30},
        1.1223,
    ),
]


@pytest.mark.parametrize(("extra", "expected"), HAND_CASES)
def test_max_settled_pitch_decay_hand_values(extra: dict, expected: float) -> None:
    assert max_settled_pitch_decay_ms({**BASE, **extra}) == pytest.approx(expected, abs=1e-3)


def test_helper_ignores_pitch_decay_and_does_not_mutate() -> None:
    p = {**BASE, "pitch_decay_ms": 250}
    before = dict(p)
    assert max_settled_pitch_decay_ms(p) == pytest.approx(25.0858, abs=1e-3)
    assert p == before


def test_pitch_settles_examples() -> None:
    assert pitch_settles(BASE)  # schema defaults follow their own guideline
    assert not pitch_settles({**BASE, "pitch_decay_ms": 40})  # old default
    assert not pitch_settles({**BASE, "pitch_decay_ms": 120})  # example from issue #7
    # Typical reference kick (research note): tau ~ 6-20 ms, -40 dB after ~330 ms
    # (amp_decay ~ 490 ms), tail ~ 53 Hz.
    assert pitch_settles({**BASE, "amp_decay_ms": 490, "pitch_end_hz": 53, "pitch_decay_ms": 20})


# --- guideline helper vs. measured pitch ------------------------------------------------------


def _random_params(rng: random.Random) -> dict:
    p = {
        "schema_version": "0.2",
        "seed": rng.randrange(2**32),
        "sample_rate": rng.choice([44100, 48000]),
        "length_ms": rng.uniform(80, 2000),
        "pitch_start_hz": rng.uniform(60, 600),
        "amp_attack_ms": rng.uniform(0, 20),
        "amp_decay_ms": rng.uniform(20, 2000),
        "click_level": rng.uniform(0, 1),
        "click_tone_hz": rng.uniform(500, 12000),
        "drive": rng.uniform(0, 1),
        "tone": rng.uniform(-1, 1),
        "peak_ceiling_dbfs": rng.uniform(-12, -0.1),
    }
    p["pitch_end_hz"] = rng.uniform(30, min(120, p["pitch_start_hz"]))
    return p


def _cycles(audio: np.ndarray, sr: int) -> list[tuple[float, float]]:
    """(start, end) in seconds of each cycle between positive-going zero crossings."""
    idx = np.nonzero((audio[:-1] < 0) & (audio[1:] >= 0))[0]
    crossings = (idx + audio[idx] / (audio[idx] - audio[idx + 1])) / sr
    return list(zip(crossings[:-1], crossings[1:], strict=True))


def _settle_time_s(p: dict) -> float:
    """Contract text: -20 dB is reached amp_decay_ms / 3 after the attack, unless the file ends."""
    return min(p["amp_attack_ms"] + p["amp_decay_ms"] / 3, p["length_ms"]) / 1000


SETTLE_SETS = [_random_params(random.Random(7000 + i)) for i in range(120)]
MEASURE_TOLERANCE = 0.015


@pytest.mark.parametrize("p", SETTLE_SETS, ids=lambda p: str(p["seed"]))
def test_guideline_limit_matches_measured_pitch(p: dict) -> None:
    """At pitch_decay_ms = limit the pitch at the settle time t is 1.05 * pitch_end_hz.
    1 / period is the mean pitch over one cycle and the pitch only falls, so:
    - at the limit, a cycle starting after t is at most 1.05 * f_end;
    - at 1.3 x the limit, a cycle ending before t is above 1.05 * f_end.
    Body only (click, drive, tone off): this checks the helper, not the analysis."""
    limit = max_settled_pitch_decay_ms(p)
    if not 2 <= limit <= 300 / 1.3:
        pytest.skip("no allowed pitch_decay_ms settles, or the overshoot leaves the range")
    target = 1.05 * p["pitch_end_hz"]
    t = _settle_time_s(p)
    checked = 0

    q = {**p, **BODY_ONLY, "pitch_decay_ms": limit}
    audio, r = render_kick(q)
    sr = r["sample_rate"]
    usable_end = len(audio) / sr - END_MARGIN_S
    after = [c for c in _cycles(audio, sr) if t <= c[0] and c[1] <= usable_end]
    if after:
        start, end = after[0]
        assert 1 / (end - start) <= target * (1 + MEASURE_TOLERANCE), (start, 1 / (end - start))
        checked += 1

    q = {**p, **BODY_ONLY, "pitch_decay_ms": 1.3 * limit}
    audio, r = render_kick(q)
    before = [c for c in _cycles(audio, sr) if c[1] <= t and c[0] >= 0.02]
    if before:
        start, end = before[-1]
        assert 1 / (end - start) > target * (1 + MEASURE_TOLERANCE), (end, 1 / (end - start))
        checked += 1
    assert checked >= 1


def test_guideline_sets_cover_both_checks() -> None:
    """Guards against a test that silently skips most sets."""
    usable = [p for p in SETTLE_SETS if 2 <= max_settled_pitch_decay_ms(p) <= 300 / 1.3]
    assert len(usable) >= 100


TAIL_SETS = [_random_params(random.Random(9000 + i)) for i in range(150)]
# Measured on this branch (3 x 300 sets, seeds 11-13): worst +8.3 %. The analysis window
# ends at -40 dB and starts up to 100 ms earlier, so it includes pitch from before -20 dB.
TAIL_BOUND = 0.10


def test_kicks_following_the_guideline_have_a_tail_near_pitch_end() -> None:
    """User-facing claim: with the guideline, the measured tail of a kick that is not cut off
    is near pitch_end_hz. Full chain incl. click, drive and tone; analysis by zero crossings."""
    worst, measured = 0.0, 0
    for p in TAIL_SETS:
        limit = max_settled_pitch_decay_ms(p)
        if limit < 2:
            continue
        q = {**p, "pitch_decay_ms": random.Random(p["seed"]).uniform(2, limit)}
        audio, r = render_kick(q)
        f = analyse(audio, r["sample_rate"])
        if f["decay_40db_ms"] is None or f["fundamental_hz"] is None:
            continue  # cut off before -40 dB, or tail too short to measure
        dev = f["fundamental_hz"] / q["pitch_end_hz"] - 1
        worst = max(worst, abs(dev))
        measured += 1
    assert measured >= 60
    assert worst <= TAIL_BOUND, worst


# --- silence never gets a sidecar -------------------------------------------------------------


def test_silent_render_is_refused_and_writes_nothing(tmp_path, monkeypatch) -> None:
    real = io_mod.render_kick_wav

    def silent(params: dict):
        _, audio, resolved = real(params)
        silence = np.zeros_like(audio)
        return io_mod.encode_wav(silence, resolved["sample_rate"], resolved["bit_depth"]), (
            silence
        ), resolved

    monkeypatch.setattr(io_mod, "render_kick_wav", silent)
    with pytest.raises(ValueError, match="silent"):
        io_mod.write_kick(BASE, tmp_path)
    assert list(tmp_path.iterdir()) == []
