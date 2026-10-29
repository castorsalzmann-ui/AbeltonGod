"""Issue #7: envelope semantics of kick-params and the pitch-settle guideline.

Expected values are written here from the contract text (kick-params v0.2 descriptions) or
measured with zero crossings; nothing is taken from the helper under test.
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

import numpy as np
import pytest

import audio_engine.io as io_mod
from audio_engine.kick import render_kick
from audio_engine.params import (
    KICK_SCHEMA_FILE,
    KickParamsError,
    load_schema,
    max_settled_pitch_decay_ms,
    pitch_settles,
    resolve_kick_params,
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
    assert schema["properties"]["schema_version"]["enum"] == ["0.2", "0.3"]
    assert schema["properties"]["pitch_decay_ms"]["default"] == 15


# --- v0.3 (#104): specified in the contract, refused by this engine ---------------------------

# Resolved 0.2 parameters as engine 0.1.0 writes them into every sidecar (written out by hand).
# The v0.3 proposal must not add a key here, or every sidecar's bytes change.
RESOLVED_V02_KEYS = {
    "schema_version", "seed", "variants", "sample_rate", "bit_depth", "length_ms",
    "pitch_start_hz", "pitch_end_hz", "pitch_decay_ms", "amp_attack_ms", "amp_decay_ms",
    "click_level", "click_tone_hz", "drive", "tone", "peak_ceiling_dbfs",
}


def test_v02_resolution_gains_no_v03_field() -> None:
    assert set(resolve_kick_params({"schema_version": "0.2", "seed": 1})) == RESOLVED_V02_KEYS


@pytest.mark.parametrize(
    "extra",
    [{}, {"click_q": 0.9}, {"polarity": 1}, {"tail_note": 33}],
    ids=["no v0.3 field", "click_q default", "polarity default", "tail_note"],
)
def test_engine_refuses_v03_until_implemented(extra: dict) -> None:
    with pytest.raises(KickParamsError) as exc:
        resolve_kick_params({"schema_version": "0.3", "seed": 1, **extra})
    assert "kick-params 0.3 is specified in the contract but not implemented" in str(exc.value)


def test_v03_field_at_v02_is_an_unknown_field() -> None:
    with pytest.raises(KickParamsError) as exc:
        resolve_kick_params({"schema_version": "0.2", "seed": 1, "click_q": 2.0})
    assert "click_q" in str(exc.value)
    assert "not implemented" not in str(exc.value)


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


MEASURE_TOLERANCE = 0.015
# Cycles quieter than this (relative to the render's peak) are not measured: on very fast
# decays the zero crossings there no longer follow the body pitch (review of #7: -36.8 dB,
# +6.5 % vs an ideal sine). Cause (#27, triage comment): below amp_decay_ms ~110 ms the body
# decays faster than the 10 Hz DC blocker's tail (tau 15.9 ms). That tail, plus the Hann mean
# correction in the cases where the signal never crosses zero again, moves the crossings. With
# both stages switched off the deviation is 0.00 %. -30 dB is not a safe floor in general
# (fast-decay cycles at -20 to -30 dB reach 13 %). This test passes because it only uses
# cycles near the settle time.
LEVEL_FLOOR_DB = -30.0
OVERSHOOT = 1.3


def _usable_cycles(audio: np.ndarray, sr: int) -> list[tuple[float, float]]:
    floor = 10 ** (LEVEL_FLOOR_DB / 20) * float(np.max(np.abs(audio)))
    usable_end = len(audio) / sr - END_MARGIN_S
    return [
        (a, b)
        for a, b in _cycles(audio, sr)
        if a >= 0.02
        and b <= usable_end
        and np.max(np.abs(audio[int(a * sr) : int(b * sr) + 1])) >= floor
    ]


def check_guideline_against_render(p: dict) -> int:
    """At pitch_decay_ms = limit the pitch at the settle time t is 1.05 * pitch_end_hz.
    1 / period is the mean pitch over one cycle and the pitch only falls, so:
    - at the limit, the first usable cycle starting after t is at most 1.05 * f_end;
    - at 1.3 x the limit, the last usable cycle ending before t is above 1.05 * f_end.
    Body only (click, drive, tone off): this checks the helper, not the analysis.
    Returns how many of the two checks had a usable cycle (0 = not measurable)."""
    limit = max_settled_pitch_decay_ms(p)
    if not 2 <= limit <= 300 / OVERSHOOT:
        return 0
    target = 1.05 * p["pitch_end_hz"]
    t = _settle_time_s(p)
    checked = 0

    audio, r = render_kick({**p, **BODY_ONLY, "pitch_decay_ms": limit})
    after = [c for c in _usable_cycles(audio, r["sample_rate"]) if c[0] >= t]
    if after:
        start, end = after[0]
        assert 1 / (end - start) <= target * (1 + MEASURE_TOLERANCE), (start, 1 / (end - start))
        checked += 1

    audio, r = render_kick({**p, **BODY_ONLY, "pitch_decay_ms": OVERSHOOT * limit})
    before = [c for c in _usable_cycles(audio, r["sample_rate"]) if c[1] <= t]
    if before:
        start, end = before[-1]
        assert 1 / (end - start) > target * (1 + MEASURE_TOLERANCE), (end, 1 / (end - start))
        checked += 1
    return checked


SETTLE_SETS = [_random_params(random.Random(7000 + i)) for i in range(200)]


def test_guideline_limit_matches_measured_pitch() -> None:
    measurable = sum(check_guideline_against_render(p) > 0 for p in SETTLE_SETS)
    # Guards against a test that silently measures nothing. Not measurable: no allowed
    # pitch_decay_ms settles, or every cycle near t is below the level floor.
    assert measurable >= 0.85 * len(SETTLE_SETS), measurable


# No test of the *measured* tail (analyse) against pitch_end_hz here: the analysis window can
# start at 20 ms, before the -20 dB settle time, so it averages in unsettled pitch. Review of
# #7 measured up to +16.6 % on fresh seeds for kicks at the guideline limit. The guideline
# promises the pitch curve at -20 dB, not the analysis result.


@pytest.mark.parametrize("extra", [h[0] for h in HAND_CASES if 2 <= h[1] <= 300])
def test_pitch_settles_is_exact_at_the_limit(extra: dict) -> None:
    p = {**BASE, **extra}
    limit = max_settled_pitch_decay_ms(p)
    assert pitch_settles({**p, "pitch_decay_ms": limit})
    if limit * 1.001 <= 300:
        assert not pitch_settles({**p, "pitch_decay_ms": limit * 1.001})
    assert pitch_settles({**p, "pitch_decay_ms": max(2.0, limit * 0.999)})


# --- amp_decay_ms means "60 dB" ---------------------------------------------------------------


@pytest.mark.parametrize(
    "extra",
    [{}, {"amp_decay_ms": 900, "length_ms": 1200}, {"amp_decay_ms": 240, "amp_attack_ms": 10}],
)
def test_amp_decay_is_the_time_to_fall_60_db(extra: dict) -> None:
    """Contract text: -20 dB after amp_decay_ms / 3. Body only, pitch nearly constant
    (60 -> 58 Hz), level from the peak of each cycle, slope fitted between the end of the
    attack + 20 ms and 2/3 of amp_decay_ms; expected slope written from the contract."""
    p = {
        **BASE, **BODY_ONLY, "pitch_start_hz": 60, "pitch_end_hz": 58, "pitch_decay_ms": 2,
        **extra,
    }
    audio, r = render_kick(p)
    sr = r["sample_rate"]
    t0 = (r["amp_attack_ms"] + 20) / 1000
    t1 = min(r["amp_decay_ms"] * 2 / 3, r["length_ms"] - 10) / 1000
    times, levels = [], []
    for a, b in _cycles(audio, sr):
        if t0 <= a and b <= t1:
            times.append((a + b) / 2)
            levels.append(20 * np.log10(np.max(np.abs(audio[int(a * sr) : int(b * sr) + 1]))))
    assert len(times) >= 4
    slope_db_per_s = np.polyfit(times, levels, 1)[0]
    expected = -60 / (r["amp_decay_ms"] / 1000)
    assert slope_db_per_s == pytest.approx(expected, rel=0.03)


# --- old sidecars -----------------------------------------------------------------------------

V01_SIDECAR = Path(__file__).resolve().parents[1] / "fixtures" / "sidecars" / "kick-v01.json"


def test_v01_sidecar_from_engine_001_is_refused() -> None:
    """Fixture written by main at bb66f08 (before the 0.2 bump) with write_kick on Linux, by
    engine 0.0.1. Its bytes cannot be reproduced any more (drive changed in #20 and #16), so
    since #35 a re-render must fail instead of silently giving different bytes."""
    with pytest.raises(io_mod.EngineVersionMismatch, match="0.0.1"):
        io_mod.rerender_from_sidecar(V01_SIDECAR)


V01_SHA_ENGINE_001 = "edb09d1594868dded2ae4ec1e84fc0b5564b64d54e9a2c058465ae764ba2e455"
# The same parameters rendered by engine 0.1.0 (continuous drive, #16), Linux.
V01_SHA_ENGINE_010 = "3db3c8a837f091698385ef7e63730ef04a3684851be0c2de5fe8586fc89af8c3"


@pytest.mark.skipif(sys.platform != "linux", reason="fixture sha256 was rendered on Linux")
def test_v01_sidecar_bytes_really_changed() -> None:
    """Why the refusal above is needed: rendered anyway, the bytes are those of engine 0.1.0,
    not the ones the 0.0.1 sidecar records. Both hashes are literal."""
    meta = json.loads(V01_SIDECAR.read_text(encoding="utf-8"))
    assert meta["sha256"] == V01_SHA_ENGINE_001
    assert meta["engine"]["version"] == "0.0.1"
    wav = io_mod.rerender_from_sidecar(V01_SIDECAR, allow_engine_mismatch=True)
    assert len(wav) == 44 + 3 * 21600  # 450 ms at 48 kHz, 24-bit, even: no pad byte
    assert hashlib.sha256(wav).hexdigest() == V01_SHA_ENGINE_010


def test_v01_sidecar_renders_like_the_same_params_under_v02() -> None:
    """The 0.1 -> 0.2 parameter upgrade still works (with the explicit opt-in)."""
    params = json.loads(V01_SIDECAR.read_text(encoding="utf-8"))["parameters"]
    wav, _, _ = io_mod.render_kick_wav({**params, "schema_version": "0.2"})
    assert io_mod.rerender_from_sidecar(V01_SIDECAR, allow_engine_mismatch=True) == wav


def test_v01_sidecar_without_pitch_decay_is_rejected(tmp_path) -> None:
    meta = json.loads(V01_SIDECAR.read_text(encoding="utf-8"))
    del meta["parameters"]["pitch_decay_ms"]
    path = tmp_path / "old.json"
    path.write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(KickParamsError, match="schema_version"):
        io_mod.rerender_from_sidecar(path, allow_engine_mismatch=True)


def test_v01_request_without_sidecar_is_rejected() -> None:
    """A 0.1 request may rely on the old default; it must fail, not change its sound."""
    with pytest.raises(KickParamsError, match="schema_version"):
        render_kick({"schema_version": "0.1", "seed": 5})


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
