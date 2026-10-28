"""Acceptance tests for issue #2 (Phase 01a): deterministic kick, analysis, WAV, sidecar."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime

import numpy as np
import pytest
from jsonschema import Draft202012Validator

from audio_engine.analysis import analyse
from audio_engine.io import encode_wav, render_kick_wav, rerender_from_sidecar, write_kick
from audio_engine.kick import render_kick
from audio_engine.params import METADATA_SCHEMA_FILE, KickParamsError, load_schema

BASE = {"schema_version": "0.1", "seed": 7}

# Parameter sets covering the extremes of drive, tone, click and pitch.
PARAM_SETS = {
    "defaults": {},
    "low-40hz": {"pitch_end_hz": 40},
    "fast-pitch-60hz": {"pitch_end_hz": 60, "pitch_decay_ms": 20},
    "long-tail": {"pitch_end_hz": 55, "pitch_decay_ms": 60, "amp_decay_ms": 600},
    "hard-bright": {"drive": 1.0, "tone": 1.0, "click_level": 1.0},
    "clean-dark": {"drive": 0.0, "tone": -1.0, "click_level": 0.0},
    "slow-pitch-long": {"pitch_decay_ms": 120, "amp_decay_ms": 1200, "length_ms": 1200},
    "44k1-16bit": {"sample_rate": 44100, "bit_depth": 16},
    "short": {"length_ms": 80, "amp_decay_ms": 60},
}

DC_THRESHOLD = 1e-3
FUNDAMENTAL_TOLERANCE = 0.10
SETTLED_TIME_CONSTANTS = 5.0


def params(name: str) -> dict:
    return {**BASE, **PARAM_SETS[name]}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- determinism -----------------------------------------------------------------------------


@pytest.mark.parametrize("name", PARAM_SETS)
def test_same_params_and_seed_give_identical_wav(name: str) -> None:
    first, _, _ = render_kick_wav(params(name))
    second, _, _ = render_kick_wav(params(name))
    assert sha(first) == sha(second)


def test_seed_changes_click_only_when_click_is_used() -> None:
    with_click = {**BASE, "click_level": 0.5}
    a, _, _ = render_kick_wav({**with_click, "seed": 1})
    b, _, _ = render_kick_wav({**with_click, "seed": 2})
    assert sha(a) != sha(b)

    no_click = {**BASE, "click_level": 0.0}
    c, _, _ = render_kick_wav({**no_click, "seed": 1})
    d, _, _ = render_kick_wav({**no_click, "seed": 2})
    assert sha(c) == sha(d)


def test_input_dict_is_not_mutated() -> None:
    p = params("defaults")
    before = dict(p)
    render_kick(p)
    assert p == before


# --- level, validity, DC, length -------------------------------------------------------------


@pytest.mark.parametrize("name", PARAM_SETS)
def test_signal_is_finite_below_ceiling_and_dc_free(name: str) -> None:
    audio, p = render_kick(params(name))
    assert np.all(np.isfinite(audio))
    ceiling = 10 ** (p["peak_ceiling_dbfs"] / 20)
    assert np.max(np.abs(audio)) <= ceiling + 1e-12
    assert abs(float(np.mean(audio))) < DC_THRESHOLD


@pytest.mark.parametrize("ceiling", [-12.0, -6.0, -1.0, -0.1])
def test_peak_matches_configured_ceiling(ceiling: float) -> None:
    audio, p = render_kick({**BASE, "peak_ceiling_dbfs": ceiling})
    features = analyse(audio, p["sample_rate"])
    assert features["peak_dbfs"] <= ceiling + 1e-9
    assert features["peak_dbfs"] == pytest.approx(ceiling, abs=0.01)


@pytest.mark.parametrize("name", PARAM_SETS)
def test_length_within_one_millisecond(name: str) -> None:
    audio, p = render_kick(params(name))
    assert abs(len(audio) / p["sample_rate"] * 1000 - p["length_ms"]) <= 1.0


@pytest.mark.parametrize("name", PARAM_SETS)
def test_no_step_at_start_and_silent_end(name: str) -> None:
    # The click transient starts at sample 1 by design, so sample 0 is near zero, not exactly
    # zero; anything below -40 dBFS causes no audible step. The fade-out makes the end exact.
    audio, _ = render_kick(params(name))
    assert abs(audio[0]) < 0.01
    assert audio[-1] == pytest.approx(0.0, abs=1e-12)


# --- fundamental -----------------------------------------------------------------------------


@pytest.mark.parametrize("name", PARAM_SETS)
def test_tail_fundamental_matches_pitch_end_when_pitch_has_settled(name: str) -> None:
    """Scope of the ±10 % criterion: the pitch envelope must have run at least five time
    constants before the sound is 40 dB down. Otherwise the tail is genuinely higher than
    pitch_end_hz (see test_unsettled_pitch_is_reported_honestly)."""
    audio, p = render_kick(params(name))
    f = analyse(audio, p["sample_rate"])
    settled_until_ms = f["decay_40db_ms"] or p["length_ms"]
    if settled_until_ms < SETTLED_TIME_CONSTANTS * p["pitch_decay_ms"]:
        pytest.skip("pitch envelope not settled before -40 dB; criterion does not apply")
    assert f["fundamental_hz"] is not None
    assert abs(f["fundamental_hz"] - p["pitch_end_hz"]) <= FUNDAMENTAL_TOLERANCE * p["pitch_end_hz"]


def test_all_listed_param_sets_are_in_scope_of_the_fundamental_criterion() -> None:
    # Guards against the test above silently skipping everything.
    in_scope = 0
    for name in PARAM_SETS:
        audio, p = render_kick(params(name))
        f = analyse(audio, p["sample_rate"])
        if (f["decay_40db_ms"] or p["length_ms"]) >= SETTLED_TIME_CONSTANTS * p["pitch_decay_ms"]:
            in_scope += 1
    assert in_scope >= len(PARAM_SETS) - 1


def test_unsettled_pitch_is_reported_honestly() -> None:
    audio, p = render_kick({**BASE, "pitch_decay_ms": 120})
    f = analyse(audio, p["sample_rate"])
    assert f["fundamental_hz"] > 1.2 * p["pitch_end_hz"]


# --- analysis on a known signal --------------------------------------------------------------


def test_analysis_on_pure_decaying_sine() -> None:
    sr = 48000
    t = np.arange(int(0.5 * sr)) / sr
    tau = 0.1 / math.log(10)  # -20 dB after 100 ms
    audio = 0.5 * np.sin(2 * math.pi * 50 * t) * np.exp(-t / tau)
    f = analyse(audio, sr)
    # First positive peak is at 5 ms (quarter period of 50 Hz), already decayed by exp(-5ms/tau).
    expected_peak = 20 * math.log10(0.5 * math.exp(-0.005 / tau))
    assert f["peak_dbfs"] == pytest.approx(expected_peak, abs=0.05)
    assert f["fundamental_hz"] == pytest.approx(50.0, rel=0.01)
    assert f["decay_20db_ms"] == pytest.approx(100.0, abs=15.0)
    assert f["decay_40db_ms"] == pytest.approx(200.0, abs=15.0)
    assert f["length_ms"] == pytest.approx(500.0)


def test_analysis_rejects_stereo() -> None:
    with pytest.raises(ValueError):
        analyse(np.zeros((10, 2)), 48000)


# --- invalid parameters ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("bad", "fragment"),
    [
        ({"schema_version": "0.1"}, "seed"),
        ({**BASE, "pitch_end_hz": 5}, "pitch_end_hz"),
        ({**BASE, "drive": 1.5}, "drive"),
        ({**BASE, "sample_rate": 96000}, "sample_rate"),
        ({**BASE, "wobble": 3}, "wobble"),
        ({**BASE, "schema_version": "9"}, "schema_version"),
        ({**BASE, "pitch_start_hz": 60, "pitch_end_hz": 100}, "pitch_end_hz"),
    ],
)
def test_invalid_params_are_rejected_with_clear_error(bad: dict, fragment: str) -> None:
    with pytest.raises(KickParamsError) as exc:
        render_kick(bad)
    assert fragment in str(exc.value)


def test_non_dict_params_are_rejected() -> None:
    with pytest.raises(KickParamsError):
        render_kick(["not", "a", "dict"])  # type: ignore[arg-type]


# --- WAV encoding ----------------------------------------------------------------------------


@pytest.mark.parametrize("bits", [16, 24])
def test_wav_roundtrip_header_and_values(bits: int) -> None:
    import io
    import wave

    audio = np.array([0.0, 0.5, -0.5, 1.0, -1.0])
    data = encode_wav(audio, 48000, bits)
    with wave.open(io.BytesIO(data)) as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == bits // 8
        assert w.getframerate() == 48000
        raw = w.readframes(w.getnframes())
    width = bits // 8
    values = [
        int.from_bytes(raw[i : i + width], "little", signed=True) for i in range(0, len(raw), width)
    ]
    full = 2 ** (bits - 1) - 1
    assert values == [0, round(0.5 * full), -round(0.5 * full), full, -full]


def test_wav_rejects_nan() -> None:
    with pytest.raises(ValueError):
        encode_wav(np.array([0.0, np.nan]), 48000, 24)


# --- sidecar and files -----------------------------------------------------------------------

FIXED_TIME = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


def test_sidecar_validates_and_rerenders_identical_wav(tmp_path) -> None:
    wav_path, json_path = write_kick(
        {**BASE, "bpm": 136}, tmp_path, name="dark kick", created_at=FIXED_TIME
    )
    meta = json.loads(json_path.read_text(encoding="utf-8"))
    Draft202012Validator(load_schema(METADATA_SCHEMA_FILE)).validate(meta)

    assert meta["file"] == wav_path.name == "dark-kick.wav"
    assert meta["bpm"] == 136
    assert meta["created_at"] == "2026-10-28T12:00:00+00:00"
    assert meta["sha256"] == sha(wav_path.read_bytes())
    assert sha(rerender_from_sidecar(json_path)) == meta["sha256"]


def test_existing_files_are_never_overwritten(tmp_path) -> None:
    first_wav, first_json = write_kick(BASE, tmp_path, created_at=FIXED_TIME)
    original = first_wav.read_bytes()
    second_wav, second_json = write_kick({**BASE, "seed": 8}, tmp_path, created_at=FIXED_TIME)
    third_wav, _ = write_kick({**BASE, "seed": 9}, tmp_path, created_at=FIXED_TIME)

    assert [first_wav.name, second_wav.name, third_wav.name] == [
        "kick.wav",
        "kick_002.wav",
        "kick_003.wav",
    ]
    assert first_wav.read_bytes() == original
    assert second_json.name == "kick_002.json"


def test_orphan_sidecar_also_blocks_the_name(tmp_path) -> None:
    (tmp_path / "kick.json").write_text("{}", encoding="utf-8")
    wav_path, json_path = write_kick(BASE, tmp_path, created_at=FIXED_TIME)
    assert wav_path.name == "kick_002.wav"
    assert (tmp_path / "kick.json").read_text(encoding="utf-8") == "{}"
