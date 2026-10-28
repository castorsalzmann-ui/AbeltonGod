"""Acceptance tests for issue #2 (Phase 01a): deterministic kick, analysis, WAV, sidecar.

Two layers:
- curated parameter sets (readable, stable),
- property tests over random parameter sets drawn from the full schema range (seeded, so they
  are deterministic too). The review of PR #8 showed that curated sets alone hid failures.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import random
import wave
from datetime import UTC, datetime

import numpy as np
import pytest
from jsonschema import Draft202012Validator

import audio_engine.io as io_mod
from audio_engine.analysis import analyse, tail_window, zero_crossing_frequency
from audio_engine.io import (
    encode_wav,
    render_kick_wav,
    rerender_from_sidecar,
    safe_stem,
    write_kick,
)
from audio_engine.kick import body_phase, render_kick
from audio_engine.params import (
    KICK_SCHEMA_FILE,
    METADATA_SCHEMA_FILE,
    KickParamsError,
    load_schema,
)

BASE = {"schema_version": "0.1", "seed": 7}

PARAM_SETS = {
    "defaults": {},
    "low-40hz": {"pitch_end_hz": 40},
    "fast-pitch-60hz": {"pitch_end_hz": 60, "pitch_decay_ms": 20},
    "long-tail": {"pitch_end_hz": 55, "pitch_decay_ms": 60, "amp_decay_ms": 600},
    "hard-bright": {"drive": 1.0, "tone": 1.0, "click_level": 1.0},
    "clean-dark": {"drive": 0.0, "tone": -1.0, "click_level": 0.0},
    "slow-pitch-long": {"pitch_decay_ms": 120, "amp_decay_ms": 1200, "length_ms": 1200},
    "wide-sweep": {"pitch_start_hz": 600, "pitch_end_hz": 30, "pitch_decay_ms": 40},
    "44k1-16bit": {"sample_rate": 44100, "bit_depth": 16},
    "short": {"length_ms": 80, "amp_decay_ms": 60},
    "short-cut-off": {"length_ms": 80, "amp_attack_ms": 20, "amp_decay_ms": 2000},
}

N_RANDOM = 150
DC_THRESHOLD = 1e-9
# Measured tail vs. theoretical body pitch in the same window (user decisions on PR #8,
# 2026-10-28): ±3 % for windows of at least 80 ms, ±5 % for shorter ones, where the DC
# blocker and the click shift a 60 ms measurement by up to 3.4 % (re-review N2).
FUNDAMENTAL_TOLERANCE = 0.03
FUNDAMENTAL_TOLERANCE_SHORT = 0.05
SHORT_WINDOW_MS = 80.0
MAX_UNMEASURABLE_SHARE = 0.03


def params(name: str) -> dict:
    return {**BASE, **PARAM_SETS[name]}


def random_params(rng: random.Random) -> dict:
    """Uniform draw over the whole kick-params schema range (pitch_end <= pitch_start)."""
    p = {
        "schema_version": "0.1",
        "seed": rng.randrange(2**32),
        "sample_rate": rng.choice([44100, 48000]),
        "bit_depth": rng.choice([16, 24]),
        "length_ms": rng.uniform(80, 2000),
        "pitch_start_hz": rng.uniform(60, 600),
        "pitch_decay_ms": rng.uniform(2, 300),
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


RANDOM_SETS = [random_params(random.Random(1000 + i)) for i in range(N_RANDOM)]


def all_sets() -> list:
    return [pytest.param(params(n), id=n) for n in PARAM_SETS] + [
        pytest.param(p, id=f"random-{i}") for i, p in enumerate(RANDOM_SETS)
    ]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_wav(data: bytes) -> tuple[np.ndarray, int, int]:
    with wave.open(io.BytesIO(data)) as w:
        width, sr = w.getsampwidth(), w.getframerate()
        raw = w.readframes(w.getnframes())
    if width == 2:
        ints = np.frombuffer(raw, dtype="<i2").astype(np.int64)
    else:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int64)
        ints = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        ints = np.where(ints >= 2**23, ints - 2**24, ints)
    return ints, sr, width * 8


# --- determinism -----------------------------------------------------------------------------


@pytest.mark.parametrize("p", all_sets()[:20])
def test_same_params_and_seed_give_identical_wav(p: dict) -> None:
    first, _, _ = render_kick_wav(p)
    second, _, _ = render_kick_wav(p)
    assert sha(first) == sha(second)


def test_seed_changes_click_only_when_click_is_used() -> None:
    with_click = {**BASE, "click_level": 0.5}
    assert sha(render_kick_wav({**with_click, "seed": 1})[0]) != sha(
        render_kick_wav({**with_click, "seed": 2})[0]
    )
    no_click = {**BASE, "click_level": 0.0}
    assert sha(render_kick_wav({**no_click, "seed": 1})[0]) == sha(
        render_kick_wav({**no_click, "seed": 2})[0]
    )


def test_input_dict_is_not_mutated() -> None:
    p = {**params("defaults"), "variants": 3}
    before = dict(p)
    render_kick(p)
    assert p == before


# --- level, validity, DC, start/end, length --------------------------------------------------


@pytest.mark.parametrize("p", all_sets())
def test_signal_properties(p: dict) -> None:
    audio, r = render_kick(p)
    assert np.all(np.isfinite(audio))
    assert abs(float(np.mean(audio))) < DC_THRESHOLD
    assert audio[0] == 0.0 and audio[-1] == 0.0
    assert abs(len(audio) / r["sample_rate"] * 1000 - r["length_ms"]) <= 1.0


@pytest.mark.parametrize("p", all_sets())
def test_quantised_file_peak_never_exceeds_ceiling(p: dict) -> None:
    wav_bytes, _, r = render_kick_wav(p)
    ints, sr, bits = decode_wav(wav_bytes)
    assert (sr, bits) == (r["sample_rate"], r["bit_depth"])
    full_scale = 2 ** (bits - 1) - 1
    ceiling = 10 ** (r["peak_ceiling_dbfs"] / 20)
    peak = int(np.max(np.abs(ints)))
    assert peak <= ceiling * full_scale
    assert peak >= ceiling * full_scale - 1  # and uses the headroom (within 1 LSB)


@pytest.mark.parametrize("seed", range(50))
def test_first_sample_is_zero_for_any_seed(seed: int) -> None:
    audio, _ = render_kick({**BASE, "seed": seed, "click_level": 1.0, "drive": 1.0})
    assert audio[0] == 0.0


# --- fundamental: measurement equals theory --------------------------------------------------


@pytest.mark.parametrize("p", all_sets())
def test_measured_tail_pitch_matches_theoretical_body_pitch(p: dict) -> None:
    """Criterion (user decisions on PR #8, 2026-10-28): in the measurement window, the measured
    tail frequency equals the frequency of an ideal sine with the engine's analytic body phase
    in the same window — ±3 % for windows ≥ 80 ms, ±5 % below. pitch_end_hz is the
    asymptote, not a promise."""
    audio, r = render_kick(p)
    sr = r["sample_rate"]
    start, end = tail_window(audio, sr)
    ideal = np.sin(body_phase(np.arange(len(audio)) / sr, r))
    measured = analyse(audio, sr)["fundamental_hz"]
    expected = zero_crossing_frequency(ideal[start:end], sr)
    if measured is None:
        pytest.skip("tail too short or too quiet to measure (bounded by the share test below)")
    assert expected is not None
    window_ms = (end - start) / sr * 1000
    tol = FUNDAMENTAL_TOLERANCE if window_ms >= SHORT_WINDOW_MS else FUNDAMENTAL_TOLERANCE_SHORT
    assert abs(measured - expected) <= tol * expected


@pytest.mark.parametrize(
    "extra",
    [
        {"length_ms": 80, "amp_decay_ms": 60, "pitch_decay_ms": 60},
        {"length_ms": 80, "amp_decay_ms": 60, "pitch_decay_ms": 80},
    ],
    ids=["review-n2-a", "review-n2-b"],
)
def test_short_window_cases_from_review_stay_within_short_tolerance(extra: dict) -> None:
    """The two re-review cases (−3.44 %, −3.03 % at the time) are in the short-window regime and
    must stay within ±5 %. They may improve; only the regime and the bound are pinned."""
    audio, r = render_kick({**BASE, **extra})
    sr = r["sample_rate"]
    start, end = tail_window(audio, sr)
    assert (end - start) / sr * 1000 < SHORT_WINDOW_MS
    expected = zero_crossing_frequency(
        np.sin(body_phase(np.arange(len(audio)) / sr, r))[start:end], sr
    )
    measured = analyse(audio, sr)["fundamental_hz"]
    assert abs(measured - expected) <= FUNDAMENTAL_TOLERANCE_SHORT * expected


def test_tail_pitch_is_measurable_for_almost_all_kicks() -> None:
    unmeasurable = [
        i
        for i, p in enumerate(RANDOM_SETS)
        if analyse(*_render(p))["fundamental_hz"] is None
    ]
    assert len(unmeasurable) <= MAX_UNMEASURABLE_SHARE * N_RANDOM, unmeasurable
    for name in PARAM_SETS:
        assert analyse(*_render(params(name)))["fundamental_hz"] is not None, name


def _render(p: dict) -> tuple[np.ndarray, int]:
    audio, r = render_kick(p)
    return audio, r["sample_rate"]


INDEPENDENT_PITCH_SETS = [
    {},
    {"pitch_end_hz": 40},
    {"pitch_start_hz": 600, "pitch_end_hz": 30, "pitch_decay_ms": 40},
    {"pitch_decay_ms": 120, "amp_decay_ms": 1200, "length_ms": 1200},
    {"pitch_start_hz": 300, "pitch_end_hz": 90, "pitch_decay_ms": 15},
    {"sample_rate": 44100},
]
INDEPENDENT_PITCH_TOLERANCE = 0.02


@pytest.mark.parametrize("extra", INDEPENDENT_PITCH_SETS)
def test_body_pitch_follows_parameters_independently(extra: dict) -> None:
    """Does NOT use body_phase: the expected frequency is computed here from the parameters,
    f(t) = f_end + (f_start - f_end) * exp(-t / tau), and compared with the period between
    each pair of consecutive positive zero crossings (from 20 ms until the signal is 40 dB
    down). Click, drive and tone are off so only the body is measured. During development
    this test failed when body_phase was mutated (pitch_end_hz * 1.02 -> 2.5 %,
    * 1.04 -> 4.1 %, pitch_decay_ms * 2 -> 174 %); the clean engine measured 1.06 % worst."""
    p = {**BASE, "click_level": 0.0, "drive": 0.0, "tone": 0.0, **extra}
    audio, r = render_kick(p)
    sr = r["sample_rate"]
    idx = np.nonzero((audio[:-1] < 0) & (audio[1:] >= 0))[0]
    crossings = idx + audio[idx] / (audio[idx] - audio[idx + 1])
    floor = 0.01 * float(np.max(np.abs(audio)))
    f_start, f_end = r["pitch_start_hz"], r["pitch_end_hz"]
    tau = r["pitch_decay_ms"] / 1000
    checked = 0
    for a, b in zip(crossings[:-1], crossings[1:], strict=True):
        t_mid = (a + b) / 2 / sr
        if t_mid < 0.02:
            continue
        if np.max(np.abs(audio[int(a) : int(b) + 1])) < floor:
            break
        expected = f_end + (f_start - f_end) * math.exp(-t_mid / tau)
        assert abs(sr / (b - a) - expected) <= INDEPENDENT_PITCH_TOLERANCE * expected, t_mid
        checked += 1
    assert checked >= 3


def test_dc_correction_is_small_so_real_dc_faults_stay_visible(monkeypatch) -> None:
    """The mean is removed by construction, so the DC test alone cannot catch a DC bug.
    This checks the size of the correction: without it, |mean| stays below 2 % of full scale
    for every tested set (worst seen in review: 1.73 % for short-cut-off)."""
    import audio_engine.kick as kick_mod

    monkeypatch.setattr(kick_mod, "_remove_mean", lambda x: x)
    worst = max(abs(float(np.mean(render_kick(p.values[0])[0]))) for p in all_sets())
    assert worst < 0.02


def test_tail_window_stays_out_of_the_fade_out() -> None:
    """Review 3, R1: a crossing inside the 5 ms fade-out pulled a cut-off kick to -9.77 %."""
    import audio_engine.analysis as analysis_mod
    import audio_engine.kick as kick_mod

    assert analysis_mod.TAIL_END_MARGIN_MS >= kick_mod.FADE_OUT_MS
    p = {
        "schema_version": "0.1", "seed": 3905736558, "sample_rate": 44100, "bit_depth": 16,
        "length_ms": 143.07, "amp_decay_ms": 1703.56, "amp_attack_ms": 15.54,
        "pitch_start_hz": 469.66, "pitch_end_hz": 35.86, "pitch_decay_ms": 32.35,
        "click_level": 0.72, "click_tone_hz": 2483, "drive": 0.078, "tone": 0.051,
        "peak_ceiling_dbfs": -6.52,
    }
    audio, r = render_kick(p)
    sr = r["sample_rate"]
    start, end = tail_window(audio, sr)
    assert end <= len(audio) - round(kick_mod.FADE_OUT_MS * sr / 1000)
    expected = zero_crossing_frequency(
        np.sin(body_phase(np.arange(len(audio)) / sr, r))[start:end], sr
    )
    measured = analyse(audio, sr)["fundamental_hz"]
    assert abs(measured - expected) <= FUNDAMENTAL_TOLERANCE * expected


def test_settled_kick_reaches_pitch_end() -> None:
    audio, r = render_kick(params("defaults"))
    f = analyse(audio, r["sample_rate"])["fundamental_hz"]
    assert abs(f - r["pitch_end_hz"]) <= 0.05 * r["pitch_end_hz"]


def test_unsettled_pitch_is_reported_honestly() -> None:
    audio, r = render_kick({**BASE, "pitch_decay_ms": 120})
    assert analyse(audio, r["sample_rate"])["fundamental_hz"] > 1.2 * r["pitch_end_hz"]


# --- analysis on known signals ---------------------------------------------------------------


def test_analysis_on_pure_decaying_sine() -> None:
    sr = 48000
    t = np.arange(int(0.5 * sr)) / sr
    tau = 0.1 / math.log(10)  # -20 dB after 100 ms
    audio = 0.5 * np.sin(2 * math.pi * 50 * t) * np.exp(-t / tau)
    f = analyse(audio, sr)
    # First positive peak is at 5 ms (quarter period of 50 Hz), already decayed.
    assert f["peak_dbfs"] == pytest.approx(20 * math.log10(0.5 * math.exp(-0.005 / tau)), abs=0.05)
    assert f["fundamental_hz"] == pytest.approx(50.0, rel=0.01)
    assert f["decay_20db_ms"] == pytest.approx(100.0, abs=15.0)
    assert f["decay_40db_ms"] == pytest.approx(200.0, abs=15.0)
    assert f["length_ms"] == pytest.approx(500.0)


def test_trailing_zero_is_not_counted_as_crossing() -> None:
    sr = 48000
    seg = np.sin(2 * math.pi * 40 * np.arange(int(0.1 * sr)) / sr)
    seg = np.concatenate([seg[: int(0.0875 * sr)], [0.0]])  # ends just after a negative half
    assert zero_crossing_frequency(seg, sr) == pytest.approx(40.0, rel=0.005)


@pytest.mark.parametrize("audio", [np.zeros(0), np.zeros(4800)], ids=["empty", "silence"])
def test_analysis_handles_empty_and_silence(audio: np.ndarray) -> None:
    f = analyse(audio, 48000)
    assert f["peak_dbfs"] is None
    assert f["fundamental_hz"] is None


def test_analysis_rejects_stereo() -> None:
    with pytest.raises(ValueError):
        analyse(np.zeros((10, 2)), 48000)


# --- invalid and edge parameters -------------------------------------------------------------


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
        ({**BASE, "seed": 7.5}, "seed"),
    ],
)
def test_invalid_params_are_rejected_with_clear_error(bad: dict, fragment: str) -> None:
    with pytest.raises(KickParamsError) as exc:
        render_kick(bad)
    assert fragment in str(exc.value)


NUMBER_FIELDS = [
    name
    for name, prop in load_schema(KICK_SCHEMA_FILE)["properties"].items()
    if prop.get("type") in ("number", "integer")
]


@pytest.mark.parametrize("field", NUMBER_FIELDS)
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf], ids=["nan", "inf", "-inf"])
def test_non_finite_numbers_are_rejected(field: str, value: float) -> None:
    with pytest.raises(KickParamsError) as exc:
        render_kick({**BASE, field: value})
    assert field in str(exc.value)


def test_whole_number_floats_are_accepted_as_integers() -> None:
    a, _, ra = render_kick_wav({**BASE, "seed": 7.0, "bit_depth": 24.0, "sample_rate": 48000.0})
    b, _, _ = render_kick_wav(BASE)
    assert sha(a) == sha(b)
    assert isinstance(ra["seed"], int) and isinstance(ra["bit_depth"], int)


def test_variants_is_not_part_of_a_single_render() -> None:
    _, r = render_kick({**BASE, "variants": 5})
    assert "variants" not in r


def test_non_dict_params_are_rejected() -> None:
    with pytest.raises(KickParamsError):
        render_kick(["not", "a", "dict"])  # type: ignore[arg-type]


# --- WAV encoding ----------------------------------------------------------------------------


@pytest.mark.parametrize("bits", [16, 24])
def test_wav_roundtrip_header_and_values(bits: int) -> None:
    audio = np.array([0.0, 0.5, -0.5, 1.0, -1.0])
    ints, sr, b = decode_wav(encode_wav(audio, 48000, bits))
    full = 2 ** (bits - 1) - 1
    assert (sr, b) == (48000, bits)
    assert ints.tolist() == [0, round(0.5 * full), -round(0.5 * full), full, -full]


def test_wav_rejects_nan() -> None:
    with pytest.raises(ValueError):
        encode_wav(np.array([0.0, np.nan]), 48000, 24)


# --- sidecar and files -----------------------------------------------------------------------

FIXED_TIME = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize("p", all_sets()[:: max(1, len(all_sets()) // 15)])
def test_sidecar_validates_and_rerenders_identical_wav(p: dict, tmp_path) -> None:
    wav_path, json_path = write_kick(p, tmp_path, name="dark kick", created_at=FIXED_TIME)
    text = json_path.read_text(encoding="utf-8")
    assert "NaN" not in text and "Infinity" not in text
    meta = json.loads(text)
    Draft202012Validator(load_schema(METADATA_SCHEMA_FILE)).validate(meta)
    assert meta["file"] == wav_path.name == "dark-kick.wav"
    assert "variants" not in meta["parameters"]
    assert meta["created_at"] == "2026-10-28T12:00:00+00:00"
    assert meta["sha256"] == sha(wav_path.read_bytes())
    assert sha(rerender_from_sidecar(json_path)) == meta["sha256"]


def test_existing_files_are_never_overwritten(tmp_path) -> None:
    first_wav, _ = write_kick(BASE, tmp_path, created_at=FIXED_TIME)
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
    wav_path, _ = write_kick(BASE, tmp_path, created_at=FIXED_TIME)
    assert wav_path.name == "kick_002.wav"
    assert (tmp_path / "kick.json").read_text(encoding="utf-8") == "{}"


def test_name_taken_between_check_and_write_moves_to_next_counter(tmp_path, monkeypatch) -> None:
    real_unique_pair = io_mod._unique_pair
    calls = {"n": 0}

    def racing_unique_pair(out, stem):
        wav, js = real_unique_pair(out, stem)
        if calls["n"] == 0:  # someone else creates the file right after our check
            wav.write_bytes(b"other")
        calls["n"] += 1
        return wav, js

    monkeypatch.setattr(io_mod, "_unique_pair", racing_unique_pair)
    wav_path, _ = write_kick(BASE, tmp_path, created_at=FIXED_TIME)
    assert wav_path.name == "kick_002.wav"
    assert (tmp_path / "kick.wav").read_bytes() == b"other"


def test_sidecar_write_error_cleans_up_and_does_not_loop(tmp_path, monkeypatch) -> None:
    """Review N1: a write error (disk full) after the sidecar file was created must not be
    mistaken for a name clash; nothing may be left behind and the real error surfaces."""
    import builtins

    real_open = builtins.open

    class FullDisk:
        def __init__(self, f):
            self._f = f

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._f.close()
            return False

        def write(self, _data):
            raise OSError(28, "No space left on device (simulated)")

    def open_with_full_disk(file, mode="r", *args, **kwargs):
        f = real_open(file, mode, *args, **kwargs)
        return FullDisk(f) if str(file).endswith(".json") else f

    monkeypatch.setattr(io_mod, "open", open_with_full_disk, raising=False)
    with pytest.raises(OSError, match="No space left"):
        write_kick(BASE, tmp_path, created_at=FIXED_TIME)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt, OSError])
def test_wav_write_error_cleans_up(tmp_path, monkeypatch, interrupt) -> None:
    import builtins

    real_open = builtins.open

    class Broken:
        def __init__(self, f):
            self._f = f

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._f.close()
            return False

        def write(self, _data):
            raise interrupt("simulated")

    def open_broken_wav(file, mode="r", *args, **kwargs):
        f = real_open(file, mode, *args, **kwargs)
        return Broken(f) if str(file).endswith(".wav") else f

    monkeypatch.setattr(io_mod, "open", open_broken_wav, raising=False)
    with pytest.raises(interrupt):
        write_kick(BASE, tmp_path, created_at=FIXED_TIME)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "value",
    [np.float32("nan"), np.float16("inf"), np.float64("-inf"), np.longdouble("nan")],
    ids=["f32", "f16", "f64", "longdouble"],
)
def test_numpy_non_finite_scalars_are_rejected(value) -> None:
    with pytest.raises(KickParamsError):
        render_kick({**BASE, "drive": value})


def test_numpy_scalars_are_accepted_and_serialisable(tmp_path) -> None:
    p = {**BASE, "seed": np.int64(7), "drive": np.float32(0.25), "bit_depth": np.int32(24)}
    wav_path, json_path = write_kick(p, tmp_path, created_at=FIXED_TIME)
    meta = json.loads(json_path.read_text(encoding="utf-8"))
    assert meta["parameters"]["seed"] == 7 and isinstance(meta["parameters"]["drive"], float)


def test_failed_sidecar_write_leaves_no_orphan_wav(tmp_path, monkeypatch) -> None:
    import builtins

    real_open = builtins.open

    def failing_open(file, mode="r", *args, **kwargs):
        if str(file).endswith(".json") and "x" in mode:
            raise OSError("disk full (simulated)")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(io_mod, "open", failing_open, raising=False)
    with pytest.raises(OSError, match="simulated"):
        write_kick(BASE, tmp_path, created_at=FIXED_TIME)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("dark kick", "dark-kick"),
        ("CON", "kick-CON"),
        ("nul.final", "kick-nul.final"),
        ("com3", "kick-com3"),
        ("../../evil", "evil"),
        ("", "kick"),
        ("Ä", "kick"),
        ("x" * 200, "x" * 80),
    ],
)
def test_safe_stem(name: str, expected: str) -> None:
    assert safe_stem(name) == expected
