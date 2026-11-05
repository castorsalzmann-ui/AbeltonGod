"""Laser engine, contract v0.2 (#425, D-031): salvo, filter, echo additions, reverb, presets.

Expected values are written in the tests or measured with a method independent of the engine
(a direct-form biquad loop with hand-derived coefficients, zero crossings, windowed peaks, raw
WAV bytes). No test says how a shot sounds.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from pathlib import Path

import numpy as np
import pytest
from test_laser import FAMILIES, PROPS, SCHEMA, check_render, decode

from audio_engine import cli, laser, laser_fx
from audio_engine.categories import get_category
from audio_engine.io import encode_wav, rerender_from_sidecar, write_sample
from audio_engine.laser import LaserParamsError, render_laser, resolve_laser_params
from audio_engine.presets import load_preset, preset_names

V02 = laser.v02_properties()
V02_DISCRETE = {k: v for k, v in V02.items() if "enum" in v or v["type"] == "integer"}
V02_RANGE = {k: v for k, v in V02.items() if k not in V02_DISCRETE}
SR = 48000
V2 = {"schema_version": "0.2"}
# a clean sine voice: constant pitch, no attack, short decay
SINE = {**V2, "pitch_start_hz": 800, "pitch_end_hz": 800, "attack_ms": 0, "decay_ms": 60,
        "length_ms": 1500}


def random_v02(rng: random.Random, edge: float = 0.2) -> dict:
    """A 0.2 request over the whole contract range; each field sometimes at an edge."""
    p: dict = {"schema_version": "0.2", "family": rng.choice(FAMILIES)}
    fields = {k: v for k, v in PROPS.items()
              if "minimum" in v and k not in ("seed", "variants", "bpm")} | V02_RANGE
    for name, spec in fields.items():
        lo, hi = spec["minimum"], spec["maximum"]
        if spec["type"] == "integer":
            p[name] = rng.randint(lo, hi)
        elif rng.random() < edge:
            p[name] = rng.choice((lo, hi))
        else:
            p[name] = rng.uniform(lo, hi)
    for name, spec in V02_DISCRETE.items():
        p[name] = rng.choice(spec["enum"]) if "enum" in spec else rng.randint(
            spec["minimum"], spec["maximum"])
    p["bpm"] = rng.uniform(60, 200)
    p["sample_rate"] = rng.choice((44100, 48000))
    p["bit_depth"] = rng.choice((16, 24))
    p["polarity"] = rng.choice((1, -1))
    p["seed"] = rng.randint(0, 2**32 - 1)
    return p


def mid(a: np.ndarray) -> np.ndarray:
    return a.mean(axis=1)


def onsets(x: np.ndarray, sr: int = SR, rel: float = 0.02) -> list[int]:
    """Start sample of every burst: first sample above rel * peak after a 20 ms quiet gap."""
    idx = np.flatnonzero(np.abs(x) > rel * np.abs(x).max())
    gap = int(0.02 * sr)
    return [int(idx[0])] + [int(b) for a, b in zip(idx[:-1], idx[1:], strict=True) if b - a > gap]


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x * x)))


def win(x: np.ndarray, t0: float, t1: float, sr: int = SR) -> np.ndarray:
    return x[int(t0 * sr) : int(t1 * sr)]


# --- property tests over the whole contract range --------------------------------------------


def test_random_v02_requests_hold_all_invariants() -> None:
    rng = random.Random(425)
    for i in range(24):
        p = random_v02(rng)
        try:
            audio = check_render(p)
        except AssertionError as exc:
            raise AssertionError(f"draw {i}: {p}") from exc
        r = resolve_laser_params(p)
        wav = encode_wav(audio, r["sample_rate"], r["bit_depth"])
        ints, _, _ = decode(wav)
        assert np.all(ints[-1] == 0)  # the file ends silent: last frame is exactly 0
        if i < 6:  # byte identity: a second render of the same request
            again = render_laser({k: v for k, v in r.items() if k != "seed"}, r["seed"])
            assert encode_wav(again, r["sample_rate"], r["bit_depth"]) == wav


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("corner", ["min", "max"])
def test_v02_corner_requests_hold_all_invariants(family: str, corner: str) -> None:
    pick = 0 if corner == "min" else 1
    p: dict = {"schema_version": "0.2", "seed": 3, "family": family, "bpm": (60, 200)[pick]}
    for name, spec in (PROPS | V02).items():
        if "minimum" in spec and name not in ("seed", "variants", "bpm"):
            p[name] = (spec["minimum"], spec["maximum"])[pick]
    p["glitch_steps"] = (2, 24)[pick]
    p["salvo_count"] = (1, 5)[pick]
    for name, spec in V02_DISCRETE.items():
        if "enum" in spec:  # first value at the min corner, last at the max corner
            p[name] = spec["enum"][-pick]
    check_render(p)


@pytest.mark.parametrize("sr", [44100, 48000])
@pytest.mark.parametrize("length_ms", [100, 3000.5, 6000, 4321.123])
def test_length_is_exact_with_every_tail_source(sr: int, length_ms: float) -> None:
    p = {**V2, "length_ms": length_ms, "sample_rate": sr, "salvo_count": 3, "echo_mix": 0.5,
         "echo_sync": "1/16", "reverb_mix": 0.5, "reverb_decay_ms": 6000, "offset_ms": 12}
    a = render_laser(p, 1)
    assert len(a) == int(round(length_ms * sr / 1000.0))
    assert np.all(a[-1] == 0)


def test_v02_defaults_and_v01_requests_render_the_same_bytes() -> None:
    rng = random.Random(5)
    for _ in range(10):
        p01 = {k: v for k, v in random_v02(rng).items() if k not in V02 and k != "schema_version"}
        p01["length_ms"] = min(p01["length_ms"], 3000)
        p01["bpm"] = 100
        a = render_laser({**p01, "schema_version": "0.1"}, 9)
        b = render_laser({**p01, "schema_version": "0.2"}, 9)
        c = render_laser({**p01, "schema_version": "0.2", **{k: v["default"] for k, v in V02.items()
                                                              if k != "echo_sync"}}, 9)
        assert np.array_equal(a, b) and np.array_equal(a, c)


def test_seed_independence_where_the_contract_says_so() -> None:
    quiet = {**V2, "family": "plasma", "length_ms": 1200, "salvo_count": 4,
             "salvo_pan_mode": "sweep_rl", "salvo_level_step_db": -2, "salvo_pitch_step_st": 1,
             "salvo_rate_ramp": 0.5, "lp_hz": 2500, "lp_sweep_ms": 300, "hp_hz": 80,
             "echo_mix": 0.3, "echo_pingpong": 1, "echo_damp_hz": 3000, "reverb_mix": 0.3,
             "stereo_width": 0.5}
    assert np.array_equal(render_laser(quiet, 1), render_laser(quiet, 2))
    for extra in ({"salvo_pan_mode": "random"}, {"salvo_humanize": 0.8}, {"noise_level": 0.4},
                  {"variation": 0.5}):
        p = {**quiet, **extra}
        assert not np.array_equal(render_laser(p, 1), render_laser(p, 2)), extra


def test_every_v02_parameter_changes_the_output() -> None:
    base = {**V2, "bpm": 100, "length_ms": 1600, "salvo_count": 4, "salvo_pan_mode": "alternate_lr",
            "salvo_pan_width": 0.5, "salvo_humanize": 0.5, "salvo_rate_ramp": 0.3,
            "salvo_level_step_db": -2, "salvo_pitch_step_st": 2, "lp_hz": 4000, "hp_hz": 100,
            "lp_sweep_ms": 200, "lp_sweep_hz": 600, "lp_resonance": 0.3, "echo_mix": 0.4,
            "echo_sync": "1/8", "echo_damp_hz": 5000, "echo_pingpong": 0.5, "reverb_mix": 0.4,
            "stereo_width": 0.3}
    ref = render_laser(base, 5)
    alt = {"salvo_count": 2, "salvo_rate_mode": "hz", "salvo_spacing_ms": 400,
           "salvo_rate_hz": 30, "salvo_sync_note": "1/4", "salvo_rate_ramp": -0.8,
           "salvo_pan_mode": "sweep_lr", "salvo_pan_width": 1.0, "salvo_level_step_db": 3,
           "salvo_pitch_step_st": -3, "salvo_humanize": 0, "filter_slope": 12, "hp_hz": 400,
           "lp_hz": 9000, "lp_resonance": 0.9, "lp_sweep_ms": 600, "lp_sweep_hz": 2000,
           "echo_sync": "1/16", "echo_damp_hz": 1500, "echo_pingpong": 0, "reverb_mix": 0.1,
           "reverb_size": 0.9, "reverb_decay_ms": 4000, "reverb_damp_hz": 2000,
           "reverb_predelay_ms": 80, "reverb_width": 0.1}
    assert set(alt) == set(V02)  # every contract field is covered
    inactive = {"salvo_rate_hz", "salvo_sync_note"}  # base is in mode ms
    for name, new in alt.items():
        got = render_laser({**base, name: new}, 5)
        if name in inactive:
            assert np.array_equal(got, ref), name
        else:
            assert not np.array_equal(got, ref), name
    sync = {**base, "salvo_rate_mode": "sync"}
    assert not np.array_equal(render_laser({**sync, "salvo_sync_note": "1/4"}, 5),
                              render_laser({**sync, "salvo_sync_note": "1/32"}, 5))
    hz = {**base, "salvo_rate_mode": "hz"}
    assert not np.array_equal(render_laser({**hz, "salvo_rate_hz": 3}, 5),
                              render_laser({**hz, "salvo_rate_hz": 9}, 5))


def test_fields_without_effect_at_their_off_value_leave_the_bytes_alone() -> None:
    base = {**V2, "length_ms": 800, "noise_level": 0.2}
    ref = render_laser(base, 4)
    same = [
        {"salvo_spacing_ms": 700, "salvo_rate_hz": 3, "salvo_rate_ramp": 1,
         "salvo_sync_note": "1/4", "salvo_rate_mode": "hz", "salvo_level_step_db": 0,
         "salvo_humanize": 1},  # count 1
        {"salvo_pan_width": 0.2},  # pan mode center
        {"lp_sweep_hz": 5000, "filter_slope": 12, "lp_resonance": 1},  # no filter on
        {"lp_resonance": 1, "lp_sweep_hz": 900},  # lp_hz off, no sweep
        {"echo_sync": "1/4", "echo_damp_hz": 800, "echo_pingpong": 1},  # echo_mix 0
        {"reverb_size": 1, "reverb_decay_ms": 6000, "reverb_damp_hz": 1000,
         "reverb_predelay_ms": 200, "reverb_width": 0},  # reverb_mix 0
    ]
    for extra in same:
        assert np.array_equal(render_laser({**base, **extra}, 4), ref), extra


# --- salvo ---------------------------------------------------------------------------------------


def starts_ms(p: dict, seed: int = 1) -> list[float]:
    a = mid(render_laser({**SINE, **p}, seed))
    return [o / SR * 1000 for o in onsets(a)]


def test_salvo_timing_modes_and_ramp_match_hand_computed_values() -> None:
    near = lambda got, want: got == pytest.approx(want, abs=1.5)  # noqa: E731
    for p, want in (
        ({"salvo_count": 3, "salvo_spacing_ms": 200}, [0, 200, 400]),
        ({"salvo_count": 3, "salvo_rate_mode": "hz", "salvo_rate_hz": 5}, [0, 200, 400]),
        ({"salvo_count": 3, "salvo_rate_mode": "sync", "bpm": 120, "salvo_sync_note": "1/8"},
         [0, 250, 500]),
        ({"salvo_count": 3, "salvo_rate_mode": "sync", "bpm": 120, "salvo_sync_note": "1/8T"},
         [0, 166.667, 333.333]),
        ({"salvo_count": 2, "salvo_rate_mode": "sync", "bpm": 90, "salvo_sync_note": "1/4D"},
         [0, 1000]),
        ({"salvo_count": 2, "salvo_rate_mode": "sync", "salvo_sync_note": "1/16"},
         [0, 125]),  # no bpm: 120
        # ramp +1, 3 shots: gaps 200 * 2^0.5 = 282.84 then 200 * 2^-0.5 = 141.42
        ({"salvo_count": 3, "salvo_spacing_ms": 200, "salvo_rate_ramp": 1}, [0, 282.84, 424.26]),
        ({"salvo_count": 3, "salvo_spacing_ms": 200, "salvo_rate_ramp": -1}, [0, 141.42, 424.26]),
        ({"salvo_count": 2, "salvo_spacing_ms": 200, "salvo_rate_ramp": 1}, [0, 200]),
    ):
        got = starts_ms(p)
        assert len(got) == len(want), (p, got)
        assert all(near(g, w) for g, w in zip(got, want, strict=True)), (p, got)


def test_shots_past_the_end_are_dropped_not_shortened() -> None:
    got = starts_ms({"salvo_count": 5, "salvo_spacing_ms": 1000, "length_ms": 3000})
    assert len(got) == 3 and got[-1] == pytest.approx(2000, abs=1.5)  # 3000 / 4000 dropped
    edge = starts_ms({"salvo_count": 2, "salvo_spacing_ms": 990, "length_ms": 1000})
    assert len(edge) == 1  # starts at 990 ms, within 10 ms of the end
    keep = starts_ms({"salvo_count": 2, "salvo_spacing_ms": 980, "length_ms": 1000})
    assert len(keep) == 2


def test_level_and_pitch_step_per_shot() -> None:
    p = {**SINE, "salvo_count": 3, "salvo_spacing_ms": 300, "salvo_level_step_db": -6,
         "salvo_pitch_step_st": 12, "length_ms": 1500}
    a = mid(render_laser(p, 1))
    peaks = [float(np.abs(win(a, 0.3 * k + 0.001, 0.3 * k + 0.03)).max()) for k in range(3)]
    assert peaks[1] / peaks[0] == pytest.approx(0.5, rel=0.05)  # -6 dB = 0.5012
    assert peaks[2] / peaks[0] == pytest.approx(0.25, rel=0.05)
    for k, want in enumerate((800, 1600, 3200)):  # +12 semitones per shot
        seg = win(a, 0.3 * k + 0.002, 0.3 * k + 0.05)
        crossings = np.flatnonzero(np.diff(np.signbit(seg).astype(np.int8)) != 0)
        freq = (len(crossings) - 1) / 2 / ((crossings[-1] - crossings[0]) / SR)
        assert freq == pytest.approx(want, rel=0.03), k


def test_pitch_step_is_limited_to_the_contract_pitch_range() -> None:
    p = {**SINE, "pitch_start_hz": 6000, "pitch_end_hz": 6000, "salvo_count": 2,
         "salvo_spacing_ms": 300, "salvo_pitch_step_st": 12}
    a = mid(render_laser(p, 1))
    seg = win(a, 0.302, 0.35)
    crossings = np.flatnonzero(np.diff(np.signbit(seg).astype(np.int8)) != 0)
    assert (len(crossings) - 1) / 2 / ((crossings[-1] - crossings[0]) / SR) == pytest.approx(
        8000, rel=0.03)  # 12000 Hz limited to 8000


def test_pan_is_equal_power_and_hits_the_hard_positions() -> None:
    p = {**SINE, "salvo_count": 5, "salvo_spacing_ms": 250, "salvo_pan_mode": "sweep_lr",
         "length_ms": 1500}
    a = render_laser(p, 1)
    # positions -1, -0.5, 0, 0.5, 1: right / left level ratio = tan((pos + 1) * pi / 4)
    want = [0.0, 0.41421356, 1.0, 2.41421356, math.inf]
    powers = []
    for k in range(5):
        seg = win(a, 0.25 * k, 0.25 * k + 0.1)
        left, right = rms(seg[:, 0]), rms(seg[:, 1])
        powers.append(left**2 + right**2)
        if want[k] == 0.0:
            # the DC-removal bump (contract point 3) leaks about 1e-7 into a silent channel
            # (measured: with _remove_mean disabled the ratio is exactly 0)
            assert right < 1e-4 * left
        elif math.isinf(want[k]):
            assert left < 1e-4 * right
        else:
            assert right / left == pytest.approx(want[k], rel=0.01)
    assert max(powers) / min(powers) == pytest.approx(1.0, abs=0.01)  # equal power


def test_pan_modes_place_the_shots_where_the_contract_says() -> None:
    def side(p: dict, k: int) -> str:
        seg = win(render_laser({**SINE, "salvo_count": 3, "salvo_spacing_ms": 300, **p}, 1),
                  0.3 * k, 0.3 * k + 0.1)
        left, right = rms(seg[:, 0]), rms(seg[:, 1])
        if right < 1e-4 * left:
            return "L"
        if left < 1e-4 * right:
            return "R"
        return "C" if abs(left - right) < 1e-4 * left else "M"

    assert [side({"salvo_pan_mode": "alternate_lr"}, k) for k in range(3)] == ["L", "R", "L"]
    assert [side({"salvo_pan_mode": "alternate_rl"}, k) for k in range(3)] == ["R", "L", "R"]
    assert [side({"salvo_pan_mode": "sweep_lr"}, k) for k in range(3)] == ["L", "C", "R"]
    assert [side({"salvo_pan_mode": "sweep_rl"}, k) for k in range(3)] == ["R", "C", "L"]
    assert [side({"salvo_pan_mode": "center"}, k) for k in range(3)] == ["C", "C", "C"]
    assert [side({"salvo_pan_mode": "alternate_lr", "salvo_pan_width": 0}, k)
            for k in range(3)] == ["C", "C", "C"]


def test_random_pan_is_seeded_and_covers_both_sides() -> None:
    p = {**SINE, "salvo_count": 5, "salvo_spacing_ms": 250, "salvo_pan_mode": "random"}
    balances = []
    for seed in range(12):
        a = render_laser(p, seed)
        for k in range(5):
            seg = win(a, 0.25 * k, 0.25 * k + 0.1)
            balances.append(rms(seg[:, 1]) - rms(seg[:, 0]))
    assert min(balances) < 0 < max(balances)
    assert np.array_equal(render_laser(p, 3), render_laser(p, 3))


def test_humanize_moves_later_shots_but_never_the_first() -> None:
    base = {**SINE, "salvo_count": 4, "salvo_spacing_ms": 200}
    plain = render_laser(base, 6)
    hum = render_laser({**base, "salvo_humanize": 1}, 6)
    first = int(0.15 * SR)  # before the second shot (200 ms -20 %) starts
    assert float(np.corrcoef(mid(plain)[:first], mid(hum)[:first])[0, 1]) > 1 - 1e-9
    pairs = zip(onsets(mid(hum)), onsets(mid(plain)), strict=True)
    shifts = [(a - b) / SR * 1000 for a, b in pairs]
    assert shifts[0] == 0
    assert any(abs(s) > 0.5 for s in shifts[1:])
    assert all(abs(s) <= 0.2 * 200 + 1.5 for s in shifts[1:])  # 20 % of the gap before


# --- filter: module level against an independent reference -------------------------------------


def butterworth_biquads(kind: str, fc: float, sr: int, order: int):
    """(b, a) of the cascaded 2nd-order Butterworth sections by the bilinear transform, written
    out here from the analogue prototype poles (independent of laser_fx's RBJ formulas)."""
    k = math.tan(math.pi * fc / sr)
    out = []
    for i in range(order // 2):
        theta = math.pi * (2 * i + 1) / (2 * order)
        s = 2 * math.sin(theta)  # = 1 / Q of the section
        norm = 1 + s * k + k * k
        a = (2 * (k * k - 1) / norm, (1 - s * k + k * k) / norm)
        b = (k * k / norm, 2 * k * k / norm, k * k / norm) if kind == "lp" else (
            1 / norm, -2 / norm, 1 / norm)
        out.append((b, a))
    return out


def butterworth_gain(kind: str, f: float, fc: float, order: int, sr: int = SR) -> float:
    """|H| of the digital Butterworth filter (bilinear transform): 1 / sqrt(1 + r^(2 order)),
    r = tan(pi f / sr) / tan(pi fc / sr) for the low-pass and its inverse for the high-pass."""
    r = math.tan(math.pi * f / sr) / math.tan(math.pi * fc / sr)
    r = r if kind == "lp" else 1 / r
    return 1 / math.sqrt(1 + r ** (2 * order))


def loop_filter(x: np.ndarray, sections) -> np.ndarray:
    for (b0, b1, b2), (a1, a2) in sections:
        y = np.zeros_like(x)
        x1 = x2 = y1 = y2 = 0.0
        for i, xi in enumerate(x.tolist()):
            yi = b0 * xi + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
            y[i] = yi
            x2, x1, y2, y1 = x1, xi, y1, yi
        x = y
    return x


@pytest.mark.parametrize("kind", ["lp", "hp"])
@pytest.mark.parametrize("slope", [12, 24])
@pytest.mark.parametrize("fc,sr", [(100.0, 48000), (3000.0, 48000), (19000.0, 44100)])
def test_fft_filter_matches_a_direct_form_loop_with_independent_coefficients(
    kind: str, slope: int, fc: float, sr: int
) -> None:
    x = np.random.default_rng(1).standard_normal(6000)
    want = loop_filter(x, butterworth_biquads(kind, fc, sr, slope // 6))
    got = laser_fx.apply_sections(x[:, None], laser_fx.filter_sections(kind, sr, fc, slope))[:, 0]
    assert np.max(np.abs(got - want)) < 1e-6 * np.max(np.abs(want))


def sine_through(kind: str, f: float, fc: float, slope: int, res: float = 0.0) -> float:
    """Steady-state gain of the filter for a sine at ``f`` (both channels)."""
    n = 48000
    t = np.arange(n) / SR
    x = np.stack([np.sin(2 * math.pi * f * t)] * 2, axis=1)
    secs = laser_fx.filter_sections(kind, SR, fc, slope, res)
    y = laser_fx.apply_sections(x, secs)
    # amplitude from the rms of whole cycles (the sampled peak under-reads a phase-shifted sine)
    return float(math.sqrt(2.0) * rms(y[n // 2 :, 0]))


@pytest.mark.parametrize("slope,order", [(12, 2), (24, 4)])
def test_butterworth_gain_at_and_above_the_cutoff(slope: int, order: int) -> None:
    for f, fc in ((3000.0, 3000.0), (6000.0, 3000.0), (12000.0, 3000.0)):
        want = butterworth_gain("lp", f, fc, order)
        assert sine_through("lp", f, fc, slope) == pytest.approx(want, rel=0.01), f
    for f, fc in ((200.0, 200.0), (100.0, 200.0), (50.0, 200.0)):
        want = butterworth_gain("hp", f, fc, order)
        assert sine_through("hp", f, fc, slope) == pytest.approx(want, rel=0.02), f


@pytest.mark.parametrize("slope", [12, 24])
def test_resonance_raises_the_cutoff_gain_by_the_documented_q_factor(slope: int) -> None:
    ratio = sine_through("lp", 2000.0, 2000.0, slope, 1.0) / sine_through(
        "lp", 2000.0, 2000.0, slope, 0.0)
    assert ratio == pytest.approx(2.5, rel=0.02)  # Q of the highest-Q stage x (1 + 1.5)


def test_closing_sweep_follows_the_exponential_cutoff_path_and_restarts_per_shot() -> None:
    n = 48000
    t = np.arange(n) / SR
    x = np.stack([np.sin(2 * math.pi * 2000 * t)] * 2, axis=1)
    p = {"lp_hz": 8000.0, "lp_sweep_hz": 500.0, "lp_sweep_ms": 200.0, "filter_slope": 24,
         "lp_resonance": 0.0}
    y = laser_fx.low_pass(x, SR, p, [0, 24000])

    def gain(t0: float) -> float:
        i = int(t0 * SR)
        return float(np.abs(y[i : i + 96, 0]).max())

    def want(fc: float) -> float:
        return butterworth_gain("lp", 2000.0, fc, 4)

    assert gain(0.0) == pytest.approx(want(8000), abs=0.03)
    assert gain(0.1) == pytest.approx(want(2000.0), rel=0.08)  # halfway: 8000 * (1/16) ** 0.5
    assert gain(0.3) == pytest.approx(want(500), abs=0.01)
    assert gain(0.5 + 0.0) == pytest.approx(want(8000), abs=0.03)  # second shot restarts it
    assert gain(0.6) == pytest.approx(want(2000.0), rel=0.08)
    assert gain(0.9) == pytest.approx(want(500), abs=0.01)


def test_filters_in_a_render_remove_what_they_should() -> None:
    base = {**V2, "family": "plasma", "pitch_start_hz": 4000, "pitch_end_hz": 4000,
            "length_ms": 600, "decay_ms": 3000, "noise_level": 0.5, "noise_hz": 8000}

    def band(a: np.ndarray, lo: float, hi: float) -> float:
        spec = np.abs(np.fft.rfft(mid(a))) ** 2
        f = np.fft.rfftfreq(len(a), 1 / SR)
        return float(spec[(f > lo) & (f <= hi)].sum())

    dry = render_laser(base, 1)
    lp = render_laser({**base, "lp_hz": 1000}, 1)
    # power above 2 kHz relative to power below 1 kHz drops by more than 30 dB
    ratio = lambda a: band(a, 2000, 24000) / band(a, 0, 1000)  # noqa: E731
    assert ratio(lp) < 1e-3 * ratio(dry)
    low = {**base, "pitch_start_hz": 300, "pitch_end_hz": 300}
    hp = render_laser({**low, "hp_hz": 1000}, 1)
    ref = render_laser(low, 1)
    inv = lambda a: band(a, 0, 500) / band(a, 1000, 24000)  # noqa: E731
    assert inv(hp) < 1e-3 * inv(ref)


# --- echo additions ------------------------------------------------------------------------------


ECHO = {**SINE, "decay_ms": 20, "length_ms": 1500, "pitch_start_hz": 3000, "pitch_end_hz": 3000,
        "echo_mix": 0.5, "echo_feedback": 0.5}


def peak(a: np.ndarray, t0: float, t1: float) -> float:
    return float(np.abs(win(mid(a), t0, t1)).max())


def tap_rms(a: np.ndarray, t0: float) -> float:
    return rms(win(mid(a), t0, t0 + 0.1))


def test_echo_sync_places_the_taps_at_the_note_length() -> None:
    a = render_laser({**ECHO, "echo_sync": "1/8", "bpm": 120}, 1)  # 250 ms
    first = peak(a, 0, 0.03)
    assert peak(a, 0.25, 0.28) / first == pytest.approx(0.5, rel=0.06)
    assert peak(a, 0.5, 0.53) / first == pytest.approx(0.25, rel=0.06)
    assert peak(a, 0.1, 0.24) < 1e-3 * first
    t = render_laser({**ECHO, "echo_sync": "1/8T", "bpm": 120, "echo_feedback": 0}, 1)
    assert peak(t, 0.1667, 0.19) / peak(t, 0, 0.03) == pytest.approx(0.5, rel=0.06)
    assert peak(t, 0.25, 0.28) < 1e-3 * peak(t, 0, 0.03)


def test_echo_damping_darkens_later_taps_by_the_one_pole_gain() -> None:
    a = render_laser({**ECHO, "echo_damp_hz": 1000, "echo_ms": 250, "echo_feedback": 0.8}, 1)
    # one-pole at 1 kHz, sine 3 kHz: (1 - c) / |1 - c e^{-jw}|, c = exp(-2 pi 1000 / 48000)
    c = math.exp(-2 * math.pi * 1000 / SR)
    w = 2 * math.pi * 3000 / SR
    gain = (1 - c) / abs(1 - c * complex(math.cos(w), -math.sin(w)))
    # rms over the whole burst (the abrupt onset has low-frequency content that the damper
    # passes, so a peak reading is not the steady-state gain)
    first = tap_rms(a, 0.25)  # first tap is not damped: mix
    second = tap_rms(a, 0.5)  # tap 2: mix * fb * gain
    assert second / first == pytest.approx(0.8 * gain, rel=0.08)


def one_pole_loop(x: np.ndarray, fc: float, sr: int) -> np.ndarray:
    c = math.exp(-2 * math.pi * fc / sr)
    y = np.zeros_like(x)
    prev = np.zeros(x.shape[1])
    for i in range(len(x)):
        prev = (1 - c) * x[i] + c * prev
        y[i] = prev
    return y


@pytest.mark.parametrize("pp,w", [(0.0, 0.0), (1.0, 0.0), (0.4, 0.6)])
def test_echo_v2_matches_a_time_domain_loop_reference(pp: float, w: float) -> None:
    rng = np.random.default_rng(7)
    n, d, sr = 9000, 700, 48000
    x = rng.standard_normal((n, 2)) * np.exp(-np.arange(n) / 2500)[:, None]
    p = {"echo_mix": 0.6, "echo_feedback": 0.7, "sample_rate": sr, "stereo_width": w,
         "echo_pingpong": pp, "echo_damp_hz": 2500.0}
    want = x.copy()
    cur = x
    k = 1
    while k * d < n and 0.6 * 0.7 ** (k - 1) >= 1e-4:
        tap = cur[: n - k * d]
        if k % 2 == 1 and w > 0:
            tap = np.stack([(1 - w) * tap[:, 0] + w * tap[:, 1],
                            (1 - w) * tap[:, 1] + w * tap[:, 0]], axis=1)
        m = tap.mean(axis=1) * math.sqrt(2)
        pong = np.zeros_like(tap)
        pong[:, 1 if k % 2 == 1 else 0] = m
        want[k * d :] += 0.6 * 0.7 ** (k - 1) * ((1 - pp) * tap + pp * pong)
        cur = one_pole_loop(cur, 2500.0, sr)
        k += 1
    got = laser_fx.echo_v2(x, p, d)
    assert np.max(np.abs(got - want)) < 1e-6 * np.max(np.abs(want))


def test_echo_pingpong_alternates_the_taps_between_the_channels() -> None:
    a = render_laser({**ECHO, "echo_ms": 250, "echo_pingpong": 1, "echo_feedback": 0.8}, 1)
    left, right = a[:, 0], a[:, 1]
    tap1 = (slice(int(0.25 * SR), int(0.28 * SR)))
    tap2 = (slice(int(0.5 * SR), int(0.53 * SR)))
    assert np.abs(left[tap1]).max() < 1e-6 * np.abs(right[tap1]).max()  # odd: right only
    assert np.abs(right[tap2]).max() < 1e-6 * np.abs(left[tap2]).max()  # even: left only
    assert np.abs(left[: int(0.03 * SR)]).max() > 0  # the dry shot is in both channels
    assert np.abs(right[: int(0.03 * SR)]).max() > 0
    # sqrt(2) * mid on one side: tap 1 has the level of the dry shot's mid * mix * sqrt(2)
    assert np.abs(right[tap1]).max() / np.abs(left[: int(0.03 * SR)]).max() == pytest.approx(
        0.5 * math.sqrt(2), rel=0.06)


def test_echo_v2_equals_the_v01_echo_when_only_the_sync_matches_echo_ms() -> None:
    a = render_laser({**ECHO, "echo_ms": 250, "stereo_width": 0.4, "noise_level": 0.2}, 2)
    b = render_laser({**ECHO, "echo_sync": "1/8", "bpm": 120, "stereo_width": 0.4,
                      "noise_level": 0.2}, 2)
    assert np.array_equal(a, b)
    # the frequency-domain evaluation (damping at 20000 = off, ping-pong 0) is not used here;
    # force it with a tiny ping-pong and compare with the time-domain v0.1 echo
    c = render_laser({**ECHO, "echo_ms": 250, "stereo_width": 0.4, "noise_level": 0.2,
                      "echo_pingpong": 1e-9}, 2)
    assert np.max(np.abs(a - c)) < 1e-6


# --- reverb --------------------------------------------------------------------------------------


REV = {**SINE, "pitch_start_hz": 1500, "pitch_end_hz": 1500, "decay_ms": 20, "length_ms": 2500,
       "noise_level": 0.6, "reverb_mix": 1.0, "reverb_damp_hz": 20000, "stereo_width": 0}


def band_db(a: np.ndarray, t0: float, t1: float) -> float:
    return 10 * math.log10(float(np.mean(win(mid(a), t0, t1) ** 2)))


@pytest.mark.parametrize("size", [0.0, 0.5, 1.0])
def test_reverb_decays_at_the_requested_60_db_time(size: float) -> None:
    a = render_laser({**REV, "reverb_decay_ms": 1000, "reverb_size": size}, 1)
    # energy per 100 ms: 500-600 ms against 900-1000 ms is 400 ms of a 1000 ms (-60 dB) decay
    drop = band_db(a, 0.5, 0.6) - band_db(a, 0.9, 1.0)
    assert drop == pytest.approx(24.0, abs=6.0)
    drop2 = band_db(a, 0.7, 0.8) - band_db(a, 1.3, 1.4)
    assert drop2 == pytest.approx(36.0, abs=8.0)


def test_reverb_damping_makes_high_frequencies_decay_faster() -> None:
    def hf_share(a: np.ndarray, t0: float, t1: float) -> float:
        seg = win(mid(a), t0, t1)
        spec = np.abs(np.fft.rfft(seg)) ** 2
        f = np.fft.rfftfreq(len(seg), 1 / SR)
        return float(spec[f > 4000].sum() / spec.sum())

    bright = render_laser({**REV, "reverb_decay_ms": 1500, "reverb_damp_hz": 20000}, 1)
    dark = render_laser({**REV, "reverb_decay_ms": 1500, "reverb_damp_hz": 1500}, 1)
    assert hf_share(dark, 0.8, 1.2) < 0.2 * hf_share(bright, 0.8, 1.2)


def test_reverb_predelay_width_size_and_mix() -> None:
    body = {**REV, "noise_level": 0.0, "reverb_decay_ms": 1500}
    early = render_laser({**body, "reverb_predelay_ms": 0}, 1)
    late = render_laser({**body, "reverb_predelay_ms": 150}, 1)
    assert band_db(early, 0.04, 0.12) > band_db(late, 0.04, 0.12) + 40  # nothing before 150 ms
    assert band_db(late, 0.2, 0.3) > band_db(late, 0.04, 0.12) + 40
    narrow = render_laser({**body, "reverb_width": 0}, 1)
    wide = render_laser({**body, "reverb_width": 1}, 1)
    assert np.array_equal(narrow[:, 0], narrow[:, 1])  # mono source, mono wet: identical
    assert float(np.corrcoef(wide[:, 0], wide[:, 1])[0, 1]) < 0.9
    off = render_laser({**body, "reverb_mix": 0}, 1)
    assert not np.array_equal(off, narrow)
    small = render_laser({**body, "reverb_size": 0.0}, 1)
    large = render_laser({**body, "reverb_size": 1.0}, 1)
    assert not np.array_equal(small, large)


def test_reverb_wet_energy_equals_the_dry_energy_and_is_silent_for_silence() -> None:
    rng = np.random.default_rng(3)
    x = rng.standard_normal((20000, 2)) * np.exp(-np.arange(20000) / 3000)[:, None]
    p = {**resolve_laser_params({"schema_version": "0.2", "seed": 1}), "reverb_mix": 1.0}
    wet = laser_fx.reverb_wet(x, p)
    assert float(np.sum(wet * wet)) == pytest.approx(float(np.sum(x * x)), rel=1e-9)
    assert not np.any(laser_fx.reverb_wet(np.zeros((1000, 2)), p))


@pytest.mark.parametrize(
    "decay,size,damp", [(6000, 1.0, 20000), (100, 0.0, 1000), (6000, 0.0, 1000)]
)
def test_reverb_extremes_stay_finite_and_bounded(decay: int, size: float, damp: int) -> None:
    p = {**REV, "length_ms": 6000, "reverb_decay_ms": decay, "reverb_size": size,
         "reverb_damp_hz": damp}
    a = render_laser(p, 1)
    assert np.all(np.isfinite(a)) and np.abs(a).max() < 1.0
    assert np.all(a[-1] == 0)
    # the last 50 ms fade out: nothing is louder than the sample 50 ms before
    end = np.abs(a[-int(0.05 * SR) :]).max()
    assert end <= np.abs(a[-int(0.1 * SR) : -int(0.05 * SR)]).max() + 1e-12


def test_reverb_fade_is_50_ms_and_dry_fade_is_5_ms() -> None:
    p = {**SINE, "decay_ms": 3000, "length_ms": 800, "noise_level": 0.5}
    dry = render_laser(p, 1)
    wet = render_laser({**p, "reverb_mix": 0.5, "reverb_decay_ms": 6000}, 1)

    def level(a: np.ndarray, back_ms: float, width_ms: float = 4.0) -> float:
        """rms of a window of width_ms that ends back_ms before the end of the file."""
        end = len(a) - int(back_ms * SR / 1000)
        return rms(mid(a)[end - int(width_ms * SR / 1000) : end])

    # raised-cosine fades: 5 ms (dry) / 50 ms (reverb); the tail under the fade is nearly flat
    assert level(dry, 25) / level(dry, 60) == pytest.approx(1.0, abs=0.2)
    assert level(dry, 0.3, 1.0) < 0.2 * level(dry, 60)
    assert level(wet, 25) / level(wet, 60) == pytest.approx(0.5, abs=0.2)
    assert level(wet, 6) < 0.1 * level(wet, 60)


# --- presets, files, CLI ----------------------------------------------------------------------

GOLDEN_V02 = {
    "blaster": "08339cbe082ec138699d58bca65594dde83f02bd93b0e2185b8794011c6b7277",
    "blaster-burst5": "fd0ac80ff07cec258d099127257f4c23686a2ef1f326b7a13347969d0214f8af",
    "blaster-double": "9afff649a1ddb5a6d0046fd8801367ed0700f9248566ca3f3df8744afe038377",
    "blaster-echo": "6c900608e9b818170f95c61b7147aa4e9cc22173c9c8a93394fa559725fdf3d6",
    "blaster-reverb": "f4638a524b97f0ea144a48832c5440a163b0fd3edd503ed1f39c184f91db9e86",
    "blaster-triple-lrl": "cf4829fd345e7fa0f14028b6305a1e7b6fb066407494fff9c58ea3d42d8d0e68",
}
BLASTER = ("blaster", "blaster-double", "blaster-triple-lrl", "blaster-burst5", "blaster-echo",
           "blaster-reverb")


def test_new_presets_exist_and_blaster_has_the_requested_values() -> None:
    assert set(BLASTER) <= set(preset_names("laser"))
    b = load_preset("blaster", "laser")
    for key, want in (("family", "plasma"), ("pitch_start_hz", 1900), ("pitch_end_hz", 110),
                      ("sweep_ms", 700), ("sweep_curve", 0.6), ("decay_ms", 900),
                      ("length_ms", 1500), ("drive", 0.15), ("lp_hz", 3000), ("filter_slope", 24)):
        assert b[key] == want, key
    for off in ("noise_level", "crackle", "fm_amount", "ring_amount", "stereo_width", "echo_mix",
                "reverb_mix", "salvo_count"):
        assert off not in b or b[off] in (0, 1), off
    a = render_laser(b, b["seed"])
    assert np.array_equal(a[:, 0], a[:, 1])  # mono-centred
    assert load_preset("blaster-triple-lrl", "laser")["salvo_pan_mode"] == "alternate_lr"
    assert load_preset("blaster-double", "laser")["salvo_count"] == 2
    burst = load_preset("blaster-burst5", "laser")
    assert burst["salvo_count"] == 5 and burst["salvo_rate_ramp"] > 0


@pytest.mark.parametrize("name", BLASTER)
def test_new_presets_render_valid_and_are_pinned(name: str) -> None:
    p = load_preset(name, "laser")
    assert p["preset"] == name
    check_render(p)
    r = resolve_laser_params(p)
    audio, rr = get_category("laser").render(r)
    wav = encode_wav(audio, rr["sample_rate"], rr["bit_depth"])
    assert hashlib.sha256(wav).hexdigest() == GOLDEN_V02[name], name


def test_sidecar_roundtrip_for_v02_presets(tmp_path: Path) -> None:
    for name in ("blaster-burst5", "blaster-echo", "blaster-reverb"):
        wav_path, json_path = write_sample("laser", load_preset(name, "laser"), tmp_path, name=name)
        meta = json.loads(json_path.read_text("utf-8"))
        assert meta["parameters"]["schema_version"] == "0.2"
        assert meta["engine"] == {"name": laser.LASER_NAME, "version": "0.2.0"}
        wav = wav_path.read_bytes()
        assert hashlib.sha256(wav).hexdigest() == meta["sha256"]
        assert rerender_from_sidecar(json_path) == wav
        assert meta["features"]["peak_dbfs"] <= -0.3 + 1e-3


def test_cli_set_v02_fields_incl_text_values(tmp_path: Path) -> None:
    out = tmp_path / "c"
    rc = cli.main(["--category", "laser", "--preset", "pew", "--out", str(out), "--set",
                   "salvo_count=3", "--set", "salvo_pan_mode=alternate_lr", "--set",
                   "echo_mix=0.3", "--set", "echo_sync=1/8", "--set", "lp_hz=3000", "--set",
                   "reverb_mix=0.2"])
    assert rc == 0
    meta = json.loads(next(out.glob("*.json")).read_text("utf-8"))
    pr = meta["parameters"]
    assert pr["schema_version"] == "0.2" and pr["salvo_pan_mode"] == "alternate_lr"
    assert pr["echo_sync"] == "1/8" and pr["bpm"] == 120 and pr["lp_hz"] == 3000
    for bad in (["--set", "salvo_pan_mode=diagonal"], ["--set", "salvo_count=6"],
                ["--set", "lp_hz=100"]):
        assert cli.main(["--category", "laser", "--preset", "pew", "--out", str(tmp_path / "x"),
                         *bad]) == 2
    assert not (tmp_path / "x").exists()
    # text values stay refused for the other categories
    assert cli.main(["--category", "rim", "--preset", "rim", "--out", str(tmp_path / "y"),
                     "--set", "decay1_ms=abc"]) == 2


def test_cli_renders_variants_of_a_v02_preset(tmp_path: Path) -> None:
    out = tmp_path / "v"
    assert cli.main(["--category", "laser", "--preset", "blaster-triple-lrl", "--variants", "3",
                     "--out", str(out)]) == 0
    wavs = sorted(out.glob("*.wav"))
    assert len(wavs) == 3 and len({w.read_bytes() for w in wavs}) == 3


def test_contract_violations_are_rejected_never_clamped() -> None:
    for bad in ({"salvo_count": 6}, {"lp_hz": 199.9}, {"reverb_decay_ms": 6001},
                {"echo_sync": "1/3"}, {"salvo_pan_mode": "Left"}, {"length_ms": 6000.1}):
        with pytest.raises(LaserParamsError):
            resolve_laser_params({"schema_version": "0.2", "seed": 1, **bad})
    with pytest.raises(LaserParamsError):  # v0.2 field with v0.1
        resolve_laser_params({"schema_version": "0.1", "seed": 1, "lp_hz": 3000})
    with pytest.raises(LaserParamsError):
        resolve_laser_params({"schema_version": "0.1", "seed": 1, "length_ms": 3001})
    assert render_laser({"lp_hz": 3000}, 1).shape == (24000, 2)  # version inferred as 0.2
    assert SCHEMA["properties"]["length_ms"]["maximum"] == 6000


# --- fault injection: the checks above must turn red ---------------------------------------------


def _pan_check() -> None:
    test_pan_is_equal_power_and_hits_the_hard_positions()


def _timing_check() -> None:
    got = starts_ms({"salvo_count": 3, "salvo_rate_mode": "sync", "bpm": 120,
                     "salvo_sync_note": "1/8"})
    assert all(g == pytest.approx(w, abs=1.5) for g, w in zip(got, [0, 250, 500], strict=True))


def _filter_check() -> None:
    assert sine_through("lp", 6000.0, 3000.0, 24) == pytest.approx(
        butterworth_gain("lp", 6000.0, 3000.0, 4), rel=0.01)


def _reverb_check() -> None:
    a = render_laser({**REV, "reverb_decay_ms": 1000}, 1)
    assert band_db(a, 0.5, 0.6) - band_db(a, 0.9, 1.0) == pytest.approx(24.0, abs=6.0)


def _echo_check() -> None:
    a = render_laser({**ECHO, "echo_damp_hz": 1000, "echo_ms": 250, "echo_feedback": 0.8}, 1)
    c = math.exp(-2 * math.pi * 1000 / SR)
    w = 2 * math.pi * 3000 / SR
    gain = (1 - c) / abs(1 - c * complex(math.cos(w), -math.sin(w)))
    assert tap_rms(a, 0.5) / tap_rms(a, 0.25) == pytest.approx(0.8 * gain, rel=0.08)


_ECHO_V2 = laser_fx.echo_v2

FAULTS = {
    "linear-pan-law": (laser_fx, "pan_gains", lambda pos: (1 - pos, 1 + pos), _pan_check),
    "pan-gain-2pct": (laser_fx, "pan_gains", lambda pos: (
        1.02 * math.sqrt(2) * math.cos((pos + 1) * math.pi / 4),
        math.sqrt(2) * math.sin((pos + 1) * math.pi / 4)), _pan_check),
    "note-length-2pct": (laser_fx, "note_ms", lambda note, bpm: 1.02 * 60000 / bpm / 2,
                         _timing_check),
    "filter-bypassed": (laser_fx, "apply_sections", lambda x, s, start=0, stop=None: x,
                        _filter_check),
    "reverb-silenced": (laser_fx, "reverb_wet", lambda x, p: np.zeros_like(x), _reverb_check),
    "echo-no-damping": (laser_fx, "echo_v2", lambda x, p, d: _ECHO_V2(
        x, {**p, "echo_damp_hz": 20000.0}, d), _echo_check),
}


@pytest.mark.parametrize("name", list(FAULTS))
def test_fault_injection_turns_the_checks_red(monkeypatch, name: str) -> None:
    module, attr, fault, check = FAULTS[name]
    check()  # green without the fault
    monkeypatch.setattr(module, attr, fault)
    with pytest.raises(AssertionError):
        check()
