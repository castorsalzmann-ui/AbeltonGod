"""Reference steering v2, slice 1 (#540): reader, kick and bass features, calibrated scales.

Independence: WAV files are built here by hand (RIFF chunks) or with the stdlib ``wave``
writer, never with the reader. Expected feature values are written here or computed here from
the formula of a synthetic signal (sweep phase solved by bisection, partial amplitudes of an
additive note), never with the module's helpers. The six v1 kick values are pinned to numbers
recorded on ``origin/main`` before this change. Tolerances come from measurements on the
same kind of signal (PR #540 body).
"""

from __future__ import annotations

import io
import json
import math
import random
import struct
import wave

import numpy as np
import pytest

from audio_engine import ENGINE_VERSION
from audio_engine import reference as R
from audio_engine import reference_v2 as V
from audio_engine.bass import BASS_VERSION, BassParamsError, note_frequency, render_bass
from audio_engine.bass import _schema as bass_schema
from audio_engine.kick import render_resolved as render_kick
from audio_engine.params import (
    KICK_SCHEMA_FILE,
    KickParamsError,
    load_schema,
    resolve_kick_params,
    v03_properties,
)
from audio_engine.presets import load_preset, preset_names
from audio_engine.reference_calibration import spread_stats

SR = 48000


# --- WAV builders (independent of the reader) ---------------------------------------------------

def _riff(chunks: list[tuple[bytes, bytes]]) -> bytes:
    body = b"WAVE"
    for cid, data in chunks:
        body += cid + struct.pack("<I", len(data)) + data + (b"\0" if len(data) % 2 else b"")
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _fmt(tag: int, channels: int, sr: int, bits: int, sub: int | None = None) -> bytes:
    block = channels * bits // 8
    head = struct.pack("<HHIIHH", tag, channels, sr, sr * block, block, bits)
    if sub is None:
        return head
    guid_tail = bytes.fromhex("000000001000800000aa00389b71")
    return head + struct.pack("<HHI", 22, bits, 0) + struct.pack("<H", sub) + guid_tail


def float_wav(channels: list[np.ndarray], sr: int = SR, extensible: bool = False,
              dtype: str = "<f4") -> bytes:
    inter = np.stack(channels, axis=1).reshape(-1).astype(dtype)
    bits = np.dtype(dtype).itemsize * 8
    fmt = _fmt(0xFFFE, len(channels), sr, bits, sub=3) if extensible else \
        _fmt(3, len(channels), sr, bits)
    return _riff([(b"fmt ", fmt), (b"data", inter.tobytes())])


def pcm_wav(channels: list[np.ndarray], sr: int = SR, bits: int = 24) -> bytes:
    full = 2 ** (bits - 1) - 1
    ints = np.stack([np.round(np.clip(c, -1, 1) * full).astype(np.int64) for c in channels],
                    axis=1).reshape(-1)
    if bits == 16:
        frames = ints.astype("<i2").tobytes()
    else:
        frames = b"".join(int(v & 0xFFFFFF).to_bytes(3, "little") for v in ints.tolist())
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(len(channels))
        w.setsampwidth(bits // 8)
        w.setframerate(sr)
        w.writeframes(frames)
    return buf.getvalue()


def expected_pcm(x: np.ndarray, bits: int) -> np.ndarray:
    full = 2 ** (bits - 1)
    return np.round(np.clip(x, -1, 1) * (full - 1)) / full


def kickish(ms: float, sr: int = SR, f_end: float = 50.0, decay_s: float = 0.08) -> np.ndarray:
    t = np.arange(int(round(sr * ms / 1000))) / sr
    phase = 2 * np.pi * (f_end * t + 150 * 0.02 * (1 - np.exp(-t / 0.02)))
    return 0.9 * np.cos(phase) * np.exp(-t / decay_s)


def write(tmp_path, data: bytes, name: str = "ref.wav"):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def _err(tmp_path, data: bytes, category: str = "kick") -> str:
    with pytest.raises(R.ReferenceAudioError) as exc:
        V.read_reference_v2(write(tmp_path, data), category)
    return str(exc.value)


# --- E1: reader ---------------------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(4))
def test_reader_reads_every_format_rate_and_layout_exactly(tmp_path, seed):
    """Property: random format (PCM 16/24, float 32 plain or extensible), rate (44.1/48/96
    kHz), mono/stereo and length inside the kick limits; samples equal the written values."""
    rng = random.Random(500 + seed)
    for k in range(6):
        sr = rng.choice([44100, 48000, 96000])
        kind = rng.choice(["pcm16", "pcm24", "float", "float_ext"])
        ms = rng.uniform(85.0, 1990.0)
        left = kickish(ms, sr) * rng.uniform(0.2, 1.0)
        chans = [left] if rng.random() < 0.5 else [left, kickish(ms, sr, f_end=60) * 0.5]
        if kind.startswith("pcm"):
            bits = int(kind[3:])
            data = pcm_wav(chans, sr, bits)
            expected = [expected_pcm(c, bits) for c in chans]
        else:
            bits = 32
            data = float_wav(chans, sr, extensible=kind == "float_ext")
            expected = [c.astype(np.float32).astype(np.float64) for c in chans]
        ref = V.read_reference_v2(write(tmp_path, data, f"r{seed}_{k}.wav"), "kick")
        want = expected[0] if len(chans) == 1 else np.stack(expected, axis=1)
        assert ref.samples.shape == want.shape
        assert np.array_equal(ref.samples, want), (sr, kind)
        assert (ref.sample_rate, ref.channels, ref.bit_depth) == (sr, len(chans), bits)
        assert ref.sample_format == ("pcm" if kind.startswith("pcm") else "float")
        assert ref.hit_count == 1 and not ref.multi_hit
        assert np.array_equal(ref.mid, want if want.ndim == 1 else want.mean(axis=1))


def test_stereo_is_kept_as_two_channels(tmp_path):
    left, right = kickish(400), 0.3 * kickish(400, f_end=70)
    ref = V.read_reference_v2(write(tmp_path, float_wav([left, right])), "kick")
    assert ref.samples.shape == (len(left), 2)
    assert np.array_equal(ref.samples[:, 0], left.astype(np.float32).astype(np.float64))
    assert np.array_equal(ref.samples[:, 1], right.astype(np.float32).astype(np.float64))
    assert np.array_equal(ref.first_hit_stereo, ref.samples)


def test_float_values_above_full_scale_are_kept():
    x = kickish(300) * 3.0  # a float file may exceed 1.0
    ref = V.decode_reference_v2(float_wav([x]), "kick")
    assert float(np.max(np.abs(ref.samples))) == pytest.approx(2.7, rel=1e-6)


def test_length_limits_come_from_the_contracts():
    # Written here from the contract files: kick length_ms 80..2000; bass gate 50..1500,
    # release 5..400, offset up to 12 -> 55 .. 1912 ms.
    assert V.length_limits_ms("kick") == (80.0, 2000.0)
    assert V.length_limits_ms("bass") == (55.0, 1912.0)


@pytest.mark.parametrize(("category", "lo", "hi"), [("kick", 80, 2000), ("bass", 55, 1912)])
def test_length_limits_are_exact_and_refused_in_german(tmp_path, category, lo, hi):
    def tone(n):  # one decaying hit of n samples
        t = np.arange(n) / SR
        return 0.8 * np.sin(2 * np.pi * 60 * t) * np.exp(-t / 0.4)

    n_lo, n_hi = lo * SR // 1000, hi * SR // 1000
    for n in (n_lo, n_hi):
        assert len(V.decode_reference_v2(float_wav([tone(n)]), category).samples) == n
    long = _err(tmp_path, float_wav([tone(n_hi + 1)]), category)
    assert "zu lang" in long and f"höchstens {hi / 1000:g} s" in long
    short = _err(tmp_path, float_wav([tone(n_lo - 1)]), category)
    assert "zu kurz" in short and f"mindestens {lo:g} ms" in short


@pytest.mark.parametrize(("data", "text"), [
    (_riff([(b"fmt ", _fmt(1, 1, SR, 8)), (b"data", b"\x80" * 9600)]), "8 Bit PCM"),
    (_riff([(b"fmt ", _fmt(3, 1, SR, 64)), (b"data", b"\0" * 38400)]), "64 Bit Float"),
    (_riff([(b"fmt ", _fmt(2, 1, SR, 4)), (b"data", b"\0" * 400)]), "Nur unkomprimiertes"),
    (_riff([(b"fmt ", _fmt(3, 1, 22050, 32)), (b"data", b"\0" * 40000)]), "22050 Hz"),
    (_riff([(b"fmt ", _fmt(3, 3, SR, 32)), (b"data", b"\0" * 57600)]), "3 Kanäle"),
    (b"RIFFxxxxWAVX", "Keine WAV-Datei"),
])
def test_unreadable_files_are_refused_in_german(tmp_path, data, text):
    assert text in _err(tmp_path, data)


def test_nan_silence_long_loops_and_unknown_category_are_refused(tmp_path):
    x = kickish(300).astype(np.float32)
    x[100] = np.nan
    assert "NaN" in _err(tmp_path, float_wav([x]))
    assert "still" in _err(tmp_path, float_wav([np.zeros(SR // 2)]))
    k = kickish(300)
    assert "Mittensignal" in _err(tmp_path, float_wav([k, -k]))  # side-only content
    loop = np.tile(np.concatenate([kickish(300), np.zeros(SR // 5)]), 61)  # 30.5 s
    assert "höchstens 30 s" in _err(tmp_path, float_wav([loop]))
    with pytest.raises(R.ReferenceAudioError, match="noch nicht unterstützt"):
        V.read_reference_v2(write(tmp_path, float_wav([k])), "hat")


# --- E1: hits and censored tails ----------------------------------------------------------------

def _preset_kick(name: str) -> np.ndarray:
    return render_kick(R.candidates()[preset_names("kick").index(name) * 8].params)


def test_a_loop_yields_its_first_hit_and_a_flag(tmp_path):
    """128 BPM quarter notes (469 ms apart) of the 400 ms 'punchy' preset: four hits; the
    first hit ends in the gap before the second; its features are those of one render."""
    one = _preset_kick("punchy")
    step = int(round(0.46875 * SR))
    loop = np.zeros(4 * step)
    for i in range(4):
        loop[i * step: i * step + len(one)] += one
    ref = V.decode_reference_v2(float_wav([loop]), "kick")
    assert ref.hit_count == 4 and ref.multi_hit
    assert len(one) - 1 <= ref.first_hit_end <= step
    assert not ref.censored_tail
    alone = V.kick_features_from_audio(one, SR)
    first = V.reference_features(ref, "kick")
    for k in ("fundamental_hz", "body_hz", "pitch_10ms_hz", "pitch_40ms_hz"):
        assert first[k] == pytest.approx(alone[k], rel=1e-4), k


def test_overlapping_hits_are_split_and_the_first_is_censored():
    """Positive control for pitfall 7: 250 ms apart the 'punchy' tail is still above -40 dB
    when the next hit starts, so the first hit is cut there and flagged."""
    one = _preset_kick("punchy")
    step = int(0.25 * SR)
    loop = np.zeros(3 * step + len(one))
    for i in range(4):
        seg = loop[i * step: i * step + len(one)]
        seg += one[: len(seg)]
    ref = V.decode_reference_v2(float_wav([loop]), "kick")
    assert ref.hit_count == 4
    assert step - int(0.03 * SR) <= ref.first_hit_end <= step
    assert ref.censored_tail


def test_two_layers_that_cancel_and_rebuild_are_one_hit():
    """A 50 Hz and a 60 Hz layer: their mid cancels to -25 dB near 50 ms and rebuilds to
    -10 dB within 25 ms. That slow re-rise is not a new hit (a 30 ms lookback counted it)."""
    sr = 96000
    mid = (kickish(105, sr) + 0.5 * kickish(105, sr, f_end=60)) / 2
    assert V.detect_hits(mid - np.mean(mid), sr) == (1, len(mid))
    longer = (kickish(600) + 0.5 * kickish(600, f_end=60)) / 2
    assert V.detect_hits(longer - np.mean(longer), SR)[0] == 1
    # Equal layers with a slow decay rebuild to within 6 dB, so only the 12 ms rise window
    # keeps them one hit (a 30 ms window counted 2-4 hits here).
    for sr, decay in ((48000, 0.4), (96000, 0.6)):
        equal = (kickish(900, sr, decay_s=decay) + kickish(900, sr, f_end=60, decay_s=decay))
        assert V.detect_hits(equal - np.mean(equal), sr)[0] == 1


def _random_kick(rng: random.Random) -> dict:
    props, v3 = load_schema(KICK_SCHEMA_FILE)["properties"], v03_properties()
    while True:
        p = {"schema_version": "0.3", "seed": rng.randrange(2**32),
             "polarity": rng.choice([1, -1])}
        for k in ("length_ms", "pitch_start_hz", "pitch_end_hz", "pitch_decay_ms",
                  "amp_attack_ms", "amp_decay_ms", "click_level", "click_tone_hz", "drive",
                  "tone", "peak_ceiling_dbfs"):
            p[k] = rng.uniform(props[k]["minimum"], props[k]["maximum"])
        for k in ("click_decay_ms", "click_q", "offset_ms", "clip_db"):
            p[k] = rng.uniform(v3[k]["minimum"], v3[k]["maximum"])
        try:
            q = resolve_kick_params(p)
        except KickParamsError:
            continue
        q.pop("variants", None)
        return q


def _random_bass(rng: random.Random) -> tuple[np.ndarray, dict]:
    props = bass_schema()["properties"]
    while True:
        p = {"schema_version": "0.1", "seed": rng.randrange(2**32),
             "note": rng.randint(24, 55), "polarity": rng.choice([1, -1])}
        for k in ("cents", "saw_level", "square_level", "sine_level", "sub_octave_level",
                  "gate_ms", "release_ms", "amp_attack_ms", "hp_hz", "lp_hz", "lp_q",
                  "lp_env_amount", "lp_env_decay_ms", "drive", "offset_ms"):
            p[k] = rng.uniform(props[k]["minimum"], props[k]["maximum"])
        try:
            return render_bass(p)
        except BassParamsError:
            continue


@pytest.mark.parametrize("seed", range(2))
def test_engine_renders_over_the_contract_range_are_single_hits(seed):
    """Property (kick 0.3 incl. clip/offset/polarity, bass 0.1): one hit per render, the
    censored flag where the contract says the sound must be cut, and joined renders with
    40 ms gaps count as that many hits."""
    rng = random.Random(900 + seed)
    renders: dict[str, list[np.ndarray]] = {"kick": [], "bass": []}
    for _ in range(10):
        p = _random_kick(rng)
        x = render_kick(p)
        hits, end = V.detect_hits(x - np.mean(x), SR)
        assert (hits, end) == (1, len(x)), p
        to_40 = p["amp_attack_ms"] + p["amp_decay_ms"] * 2 / 3  # body at -40 dB
        if to_40 > p["length_ms"]:
            assert V.censored_tail(x, SR, "kick"), p
        if to_40 < 0.5 * p["length_ms"] and p["drive"] == 0 and p["clip_db"] == 0:
            assert not V.censored_tail(x, SR, "kick"), p
        renders["kick"].append(x)
        b, q = _random_bass(rng)
        hits, end = V.detect_hits(b - np.mean(b), SR)
        assert (hits, end) == (1, len(b)), q
        if q["drive"] == 0 and q["release_ms"] >= 12.0:  # drive bends the release end
            assert not V.censored_tail(b, SR, "bass"), q
        renders["bass"].append(b)
    win = np.full(int(0.01 * SR), 1 / int(0.01 * SR))
    gap = np.zeros(int(0.04 * SR))
    for cat, xs in renders.items():
        # equal loudest 10 ms RMS per hit: a hit more than 6 dB below the loudest is not split
        # (documented limit), and the renders carry random peak ceilings (-12 ... -0.1 dB)
        level = [x / np.sqrt(np.max(np.convolve(x * x, win, mode="same"))) for x in xs]
        for k in (2, 3, 5):
            joined = np.concatenate([np.concatenate([c, gap]) for c in rng.sample(level, k)])
            assert V.detect_hits(joined - np.mean(joined), SR)[0] == k, cat


def test_censored_flags_on_known_cases():
    cut = resolve_kick_params({"schema_version": "0.2", "seed": 1, "length_ms": 200,
                               "amp_decay_ms": 2000})
    cut.pop("variants")
    assert V.censored_tail(render_kick(cut), SR, "kick")
    assert not V.censored_tail(_preset_kick("punchy"), SR, "kick")
    bass, p = render_bass(load_preset("default", "bass"))
    assert not V.censored_tail(bass, SR, "bass")
    assert V.censored_tail(bass[: int(0.5 * p["gate_ms"] * SR / 1000)], SR, "bass")
    short, _ = render_bass(dict(load_preset("default", "bass"), release_ms=5))
    assert V.censored_tail(short, SR, "bass")


# --- E2: kick features --------------------------------------------------------------------------

# Recorded on origin/main 8d6b5a0 (before #540) with reference.measure on these candidates.
GOLDEN_V1 = {
    "centre v0": {"fundamental_hz": 52.08, "body_hz": 115.14, "decay_20db_ms": 172.0,
                  "decay_40db_ms": 353.0, "sub_share": 0.324909, "click_share": 0.014737},
    "dark-dry v1": {"fundamental_hz": 46.49, "body_hz": 47.08, "decay_20db_ms": 152.0,
                    "decay_40db_ms": 313.0, "sub_share": 0.910506, "click_share": 0.000484},
    "dense v2": {"fundamental_hz": 52.65, "body_hz": 110.65, "decay_20db_ms": 285.0,
                 "decay_40db_ms": 456.0, "sub_share": 0.619937, "click_share": 0.031227},
    "driven v3": {"fundamental_hz": 56.57, "body_hz": 59.76, "decay_20db_ms": 165.0,
                  "decay_40db_ms": 281.0, "sub_share": 0.822844, "click_share": 0.176395},
    "punchy v4": {"fundamental_hz": 56.11, "body_hz": 58.44, "decay_20db_ms": 180.0,
                  "decay_40db_ms": 322.0, "sub_share": 0.821519, "click_share": 0.032455},
    "rumble-ready v5": {"fundamental_hz": 50.72, "body_hz": 55.86, "decay_20db_ms": 238.0,
                        "decay_40db_ms": 485.0, "sub_share": 0.873556, "click_share": 0.008972},
}


def test_the_six_v1_kick_values_are_byte_equal():
    by_name = {c.name: c for c in R.candidates()}
    for name, want in GOLDEN_V1.items():
        x = render_kick(by_name[name].params)
        got = V.kick_features_from_audio(x, SR)
        assert {k: got[k] for k in want} == want, name
        assert R.measure(x, SR) == want, name


def _sweep_cycles(t, fs: float, fe: float, tau: float):
    """Phase in cycles of f(t) = fe + (fs - fe) exp(-t / tau) (integral written here)."""
    return fe * t + (fs - fe) * tau * (1.0 - np.exp(-t / tau))


def _one_period_hz(t: float, fs: float, fe: float, tau: float) -> tuple[float | None, float]:
    """Definition of the feature, solved by bisection on the formula: 1 / (t+ - t-) where the
    phase is half a cycle below / above its value at t. Returns (value, t-)."""
    c = float(_sweep_cycles(t, fs, fe, tau))

    def solve(target: float) -> float | None:
        lo, hi = 0.0, 2.0
        if float(_sweep_cycles(lo, fs, fe, tau)) > target:
            return None
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            if float(_sweep_cycles(mid, fs, fe, tau)) < target:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    a, b = solve(c - 0.5), solve(c + 0.5)
    return (None if a is None or b is None else 1.0 / (b - a)), (a if a is not None else -1.0)


@pytest.mark.parametrize(("fs", "fe", "tau_ms"), [(250, 50, 15), (150, 55, 30), (400, 60, 60)])
def test_pitch_curve_of_slow_sweeps_is_the_instantaneous_pitch(fs, fe, tau_ms):
    t = np.arange(int(0.5 * SR)) / SR
    x = np.cos(2 * np.pi * _sweep_cycles(t, fs, fe, tau_ms / 1000)) * np.exp(-t / 0.15)
    f = V.kick_features_from_audio(x, SR)
    for ms in (5, 10, 20, 40):
        want = fe + (fs - fe) * math.exp(-ms / tau_ms)
        assert f[f"pitch_{ms}ms_hz"] == pytest.approx(want, rel=0.01), ms


@pytest.mark.parametrize("seed", range(3))
def test_pitch_curve_follows_its_definition_over_the_contract_range(seed):
    """Property: sweeps with start 60-600 Hz, end 30-120 Hz, time constant 2-300 ms
    (log-uniform). Tolerance per time from 200 measured sweeps (worst 3.0 / 2.2 / 0.4 / 0.1 %);
    ``None`` only when the defining period starts within 2 ms of the onset."""
    rng = random.Random(70 + seed)
    tol = {5: 0.035, 10: 0.025, 20: 0.006, 40: 0.002}
    t = np.arange(int(0.6 * SR)) / SR
    for _ in range(12):
        fe = rng.uniform(30, 120)
        fs = rng.uniform(max(60, fe * 1.05), 600)
        tau = math.exp(rng.uniform(math.log(0.002), math.log(0.3)))
        x = np.cos(2 * np.pi * _sweep_cycles(t, fs, fe, tau)) * np.exp(-t / 0.2)
        got = V.pitch_at_ms(V.prepare_signal(x), SR)
        for ms, g in zip((5, 10, 20, 40), got, strict=True):
            want, t_minus = _one_period_hz(ms / 1000, fs, fe, tau)
            if g is None:
                assert want is None or t_minus < 0.002, (fs, fe, tau, ms)
                continue
            assert want is not None
            assert g == pytest.approx(want, rel=tol[ms]), (fs, fe, tau, ms)


def test_pitch_curve_ignores_the_harmonics_of_a_driven_body():
    """tanh-shaped body (odd harmonics, as the engine's drive makes): the one-period value
    stays on the fundamental (a +-1 ms phase slope was off by semitones here)."""
    t = np.arange(int(0.5 * SR)) / SR
    body = np.sin(2 * np.pi * _sweep_cycles(t, 220, 50, 0.02)) * np.exp(-t / 0.15)
    x = np.tanh(4 * body) / np.tanh(4)
    got = V.pitch_at_ms(V.prepare_signal(x), SR)
    # tanh(4x) is heavier than the engine's drive and the pitch moves inside the period, so
    # the harmonics cancel to about 1 % (measured 1.1 % at 20 ms); a fixed +-1 ms slope was off
    # by semitones on driven presets. 3 % = 0.5 semitone separates the two.
    for ms, g in zip((10, 20, 40), got[1:], strict=True):
        want, _ = _one_period_hz(ms / 1000, 220, 50, 0.02)
        assert g == pytest.approx(want, rel=0.03), ms


def test_tail_harmonics_on_known_partials():
    t = np.arange(SR) / SR
    env = np.exp(-t / 0.15)
    pure = np.sin(2 * np.pi * 50 * t) * env
    assert V.kick_features_from_audio(pure, SR)["tail_harmonics_db"] <= -55.0
    rich = (np.sin(2 * np.pi * 50 * t) + 0.1 * np.sin(2 * np.pi * 100 * t)
            + 0.05 * np.sin(2 * np.pi * 150 * t)) * env
    want = 10 * math.log10(0.1**2 + 0.05**2)  # -19.03 dB
    assert V.kick_features_from_audio(rich, SR)["tail_harmonics_db"] == pytest.approx(
        want, abs=0.3)


def test_body_zone_energy_on_known_signals():
    t = np.arange(int(0.08 * SR)) / SR
    # 200 Hz: 16 whole periods in the file (mean 0, so DC removal changes nothing) and 15 in
    # 5..80 ms (bin 15 exactly, no leakage). 160 Hz (12.8 periods) had a mean that moved it.
    low = np.cos(2 * np.pi * 200 * t)
    assert V.body_energy_db(V.prepare_signal(low), SR) == pytest.approx(10 * math.log10(75 / 80),
                                                                 abs=0.01)
    both = np.concatenate([low, np.cos(2 * np.pi * 1000 * t)])
    assert V.body_energy_db(V.prepare_signal(both), SR) == pytest.approx(10 * math.log10(75 / 160),
                                                                  abs=0.01)
    high = np.cos(2 * np.pi * 1000 * np.arange(int(0.16 * SR)) / SR)
    assert V.body_energy_db(V.prepare_signal(high), SR) <= -60.0
    assert V.body_energy_db(V.prepare_signal(low[: int(0.07 * SR)]), SR) is None


def test_body_zone_energy_does_not_depend_on_the_sample_rate():
    """Regression: a plain 'freq >= 80 Hz' band moved the value by 2 dB between 48 and
    44.1 kHz on preset kicks (bin 6 = 80.00 Hz vs 79.99 Hz)."""
    for name in ("punchy", "dark-dry"):
        p = R.candidates()[preset_names("kick").index(name) * 8].params
        a = V.kick_features_from_audio(render_kick(p), SR)["body_energy_db"]
        q = dict(p, sample_rate=44100)
        b = V.kick_features_from_audio(render_kick(q), 44100)["body_energy_db"]
        assert a == pytest.approx(b, abs=0.1), name


@pytest.mark.parametrize("seed", range(2))
def test_kick_features_stay_valid_over_the_contract_range(seed):
    rng = random.Random(40 + seed)
    for _ in range(8):
        p = _random_kick(rng)
        x = render_kick(p)
        f = V.kick_features_from_audio(x, SR)
        assert set(f) == set(V.KICK_FEATURES)
        assert {k: f[k] for k in GOLDEN_V1["punchy v4"]} == R.measure(x, SR)
        for k, v in f.items():
            assert v is None or math.isfinite(v), (k, v, p)
        for k in V.KICK_FEATURES:
            if k.startswith("pitch_") and f[k] is not None:
                assert 10.0 < f[k] < 900.0, (k, f[k], p)
        assert f["body_energy_db"] is None or V.DB_FLOOR <= f["body_energy_db"] <= 0.0


# --- E2: bass features --------------------------------------------------------------------------

def additive_note(f0: float, partials: list[tuple[float, float]], attack_ms: float,
                  gate_ms: float, release_ms: float, sr: int = SR) -> np.ndarray:
    """Sum of sines k f0 with amplitudes a, linear attack, hold, linear release (written here)."""
    n = int(round((gate_ms + release_ms) * sr / 1000))
    t = np.arange(n) / sr
    x = sum(a * np.sin(2 * np.pi * k * f0 * t) for k, a in partials)
    env = np.minimum(t / (attack_ms / 1000), 1.0)
    g = int(round(gate_ms * sr / 1000))
    env[g:] *= 1 - (np.arange(n - g) + 1) / (n - g)
    return x * env


def _onset_ms(x: np.ndarray) -> float:
    a = np.abs(x - np.mean(x))
    return float(np.argmax(a >= 0.1 * np.max(a))) / SR * 1000


def test_bass_features_of_an_additive_saw():
    saw = [(k, 1 / k) for k in range(1, 9)]
    x = additive_note(98.0, saw, 5, 300, 100)
    f = V.bass_features_from_audio(x, SR)
    period_ms = 1000 / 98.0
    assert 1200 * math.log2(f["note_hz"] / 98.0) == pytest.approx(0.0, abs=0.5)
    assert f["harm2_db"] == pytest.approx(20 * math.log10(1 / 2), abs=0.05)
    assert f["harm3_db"] == pytest.approx(20 * math.log10(1 / 3), abs=0.05)
    h, h2 = sum(1 / k for k in range(1, 9)), sum(1 / k**2 for k in range(1, 9))
    assert f["centroid_hz"] == pytest.approx(98.0 * h / h2, rel=0.005)  # power-weighted
    assert f["gate_ms"] == pytest.approx(300 - _onset_ms(x), abs=8.0)
    assert abs(f["release_ms"] - 99.0) <= period_ms
    assert abs(f["attack_ms"] - 4.0) <= period_ms + 1.0


def test_bass_sub_share_of_an_additive_saw():
    # 60 Hz saw: only the first partial (power 1 of sum 1/k^2) lies below 100 Hz, far from the
    # split (a 98 Hz partial leaks across it).
    x = additive_note(60.0, [(k, 1 / k) for k in range(1, 9)], 5, 400, 60)
    h2 = sum(1 / k**2 for k in range(1, 9))
    assert V.bass_features_from_audio(x, SR)["sub_share"] == pytest.approx(1 / h2, abs=0.01)


@pytest.mark.parametrize(("f0", "attack", "gate", "release"),
                         [(120, 2, 250, 80), (196, 30, 400, 200), (32.7, 4, 800, 150)])
def test_bass_gate_release_attack_within_one_period(f0, attack, gate, release):
    x = additive_note(f0, [(1, 1.0), (3, 1 / 3)], attack, gate, release)
    f = V.bass_features_from_audio(x, SR)
    period_ms = 1000 / f0
    assert 1200 * math.log2(f["note_hz"] / f0) == pytest.approx(0.0, abs=0.5)
    assert f["gate_ms"] == pytest.approx(gate - _onset_ms(x), abs=8.0)
    assert abs(f["release_ms"] - 0.99 * release) <= period_ms
    assert abs(f["attack_ms"] - 0.8 * attack) <= period_ms + 1.0
    assert f["harm2_db"] == V.DB_FLOOR
    assert f["harm3_db"] == pytest.approx(20 * math.log10(1 / 3), abs=0.05)


def test_a_sub_octave_makes_the_note_the_waveform_period():
    """The waveform repeats at f0 / 2 when a sub-octave sounds (module docstring)."""
    for partials in ([(1, 1.0), (0.5, 0.4)], [(1, 1.0), (3, 1 / 3), (0.5, 0.4)]):
        f = V.bass_features_from_audio(additive_note(98.0, partials, 3, 300, 60), SR)
        assert f["note_hz"] == pytest.approx(49.0, rel=0.001)


def test_filter_movement_on_a_known_early_partial():
    """cos 100 Hz plus cos 300 Hz in the first 30 ms only: early centroid 200 Hz, stationary
    100 Hz, so 20 log10(2) = 6.02 dB. 30 ms hold 3 and 9 whole periods."""
    n = int(0.45 * SR)
    t = np.arange(n) / SR
    x = np.cos(2 * np.pi * 100 * t) + np.cos(2 * np.pi * 300 * t) * (t < 0.03)
    env = np.ones(n)
    g = int(0.4 * SR)
    env[g:] = 1 - (np.arange(n - g) + 1) / (n - g)
    f = V.bass_features_from_audio(x * env, SR)
    assert f["filter_move_db"] == pytest.approx(20 * math.log10(2), abs=0.1)
    assert f["centroid_hz"] == pytest.approx(100.0, rel=0.002)


def test_bass_features_are_none_where_the_window_is_too_short():
    x = additive_note(note_frequency(24), [(1, 1.0)], 2, 50, 30)  # 20 ms window, 33 Hz
    f = V.bass_features_from_audio(x, SR)
    assert f["note_hz"] is None and f["harm2_db"] is None and f["filter_move_db"] is None


@pytest.mark.parametrize("seed", range(2))
def test_bass_note_over_the_contract_range(seed):
    """Property: every bass render gives finite features or None; the note is the note or,
    with a sub-octave, half of it, within 1 semitone always and within 10 cents for clean
    notes (drive 0, gate >= 200 ms; measured: within 0.4 cents)."""
    rng = random.Random(60 + seed)
    for _ in range(10):
        x, p = _random_bass(rng)
        if rng.random() < 0.5:
            x, p = render_bass(dict(p, drive=0.0, gate_ms=max(p["gate_ms"], 200.0)))
        f = V.bass_features_from_audio(x, SR)
        assert set(f) == set(V.BASS_FEATURES)
        for k, v in f.items():
            assert v is None or math.isfinite(v), (k, v, p)
        assert 0.0 <= f["sub_share"] <= 1.0
        if f["note_hz"] is None:
            continue
        f0 = note_frequency(p["note"], p["cents"])
        cands = (f0, f0 / 2) if p["sub_octave_level"] > 0 else (f0,)
        cents = min((1200 * math.log2(f["note_hz"] / c) for c in cands), key=abs)
        assert abs(cents) < 100, (cents, p)
        if p["drive"] == 0 and p["gate_ms"] >= 200:
            assert abs(cents) < 10, (cents, p)


# --- E3: distance, weight rule and the committed table ------------------------------------------

def test_distances_follow_the_documented_transforms():
    table = {"a": V.FeatureScale("semitone", 0.5, 1.0, False),
             "b": V.FeatureScale("log", math.log(1.1), 1.0, False),
             "c": V.FeatureScale("db", 2.0, 0.0, False),
             "d": V.FeatureScale("lin", 0.05, 1.0, False)}
    ref = {"a": 110.0, "b": 200.0, "c": -10.0, "d": 0.8}
    cand = {"a": 100.0, "b": 100.0, "c": -4.0, "d": None}
    per = V.feature_distances("kick", ref, cand, table)
    assert per["a"] == pytest.approx(12 * math.log2(1.1) / 0.5)  # 3.300 semitone units
    assert per["b"] == pytest.approx(math.log(2) / math.log(1.1))
    assert per["c"] == pytest.approx(3.0)
    assert per["d"] == 3.0  # one side None
    assert V.feature_distances("kick", {"a": None}, {"a": None}, {"a": table["a"]})["a"] == 0.0
    # weight 0 drops "c" from the total: sqrt((a^2 + b^2 + d^2) / 3)
    want = math.sqrt((per["a"] ** 2 + per["b"] ** 2 + 9.0) / 3)
    assert V.total_distance("kick", per, table) == pytest.approx(want)


def _values(means: list[float], seed_spread: float) -> list[list[float]]:
    return [[m + seed_spread * (j / 7 - 0.5) for j in range(8)] for m in means]


def test_spread_statistics_on_written_numbers():
    st = spread_stats(_values([0.0, 1.0, 2.0], 0.3) + [[None] * 8, [5.0, None] + [5.0] * 6])
    assert st["seed_spread"] == pytest.approx((0.3 * 3 + 0.0) / 4)
    assert st["seed_spread_max"] == pytest.approx(0.3)
    assert st["between_spread"] == pytest.approx(5.0)
    assert (st["candidates_measured"], st["mixed_none"]) == (4, 1)


@pytest.mark.parametrize(("seed_spread", "weight"), [
    (0.666667, 0.0),  # just above between / 3 = 0.6666667
    (0.666666, 1.0),  # just below
    (3.0, 0.0),       # seed spread larger than the between-candidate spread (issue E3)
    (0.1, 1.0),
])
def test_weight_zero_rule_at_its_threshold(seed_spread, weight):
    st = spread_stats(_values([0.0, 1.0, 2.0], seed_spread))
    assert st["between_spread"] == pytest.approx(2.0)
    assert V.weight_for(st["seed_spread"], st["between_spread"]) == weight


def _table() -> dict:
    return json.loads(V.CALIBRATION_FILE.read_text(encoding="utf-8"))


def test_the_committed_table_is_complete_and_self_consistent():
    table = _table()
    assert "reference_calibration" in table["command"]
    assert table["seeds"] == list(range(1, 9))
    assert table["engines"] == {"kick": ENGINE_VERSION, "bass": BASS_VERSION}, (
        "engine version changed: re-run " + table["command"])
    for cat in ("kick", "bass"):
        rows = table["categories"][cat]["features"]
        assert table["categories"][cat]["candidates"] == 8 * len(preset_names(cat))
        assert set(rows) == set(V.FEATURES[cat]), cat
        for name, row in rows.items():
            assert row["transform"] == V.FEATURES[cat][name][0]
            assert math.isfinite(row["scale"]) and row["scale"] > 0.0, (cat, name)
            assert row["scale"] == max(row["method_error"], row["seed_spread"]), (cat, name)
            want = 0.0 if row["seed_spread"] >= row["between_spread"] / 3 else 1.0
            assert row["weight"] == want, (cat, name)


def test_the_distance_uses_the_committed_scales():
    rows = _table()["categories"]["bass"]["features"]
    fs = V.feature_table("bass")
    assert all(not s.provisional for s in fs.values())
    assert {n: s.scale for n, s in fs.items()} == {n: r["scale"] for n, r in rows.items()}
    per = V.feature_distances("bass", {"note_hz": 110.0}, {"note_hz": 100.0})
    assert per["note_hz"] == pytest.approx(12 * math.log2(1.1) / rows["note_hz"]["scale"])
    assert V.feature_table("bass", {})["note_hz"] == V.FeatureScale("semitone", 0.1, 1.0, True)
