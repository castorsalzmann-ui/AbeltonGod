"""Degraded copies and scale rule of the reference calibration (#563).

Independence: every expected value is written here or follows from the formula of the
synthetic signal built here (a sine at a known frequency, the variance of TPDF dither plus
rounding = LSB^2 / 4, a gain as a plain factor). The degradations are called through
``DEGRADATIONS``, the table the calibration run uses, so removing one from the run is seen.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from audio_engine import reference_calibration as C
from audio_engine import reference_v2 as V

SR = 48000


def _apply(name: str, x: np.ndarray, sr: int = SR) -> tuple[np.ndarray, int]:
    return C.DEGRADATIONS[name][1](x, sr)


def _sine(freq: float, n: int, sr: int) -> np.ndarray:
    return np.sin(2.0 * np.pi * freq * np.arange(n) / sr)


def _kick() -> np.ndarray:
    """A swept sine (200 -> 50 Hz, 30 ms time constant) with a 1 ms attack and 80 ms decay."""
    t = np.arange(int(0.6 * SR)) / SR
    phase = 50.0 * t + 150.0 * 0.03 * (1.0 - np.exp(-t / 0.03))
    return 0.8 * np.sin(2.0 * np.pi * phase) * np.exp(-t / 0.08) * np.minimum(t / 0.001, 1.0)


def _bass() -> np.ndarray:
    """A 110 Hz note of six 1/k partials: 5 ms attack, 300 ms gate, 50 ms linear release."""
    t = np.arange(int(0.35 * SR)) / SR
    wave = sum(np.sin(2.0 * np.pi * 110.0 * k * t) / k for k in range(1, 7))
    env = np.minimum(t / 0.005, 1.0) * np.clip((0.35 - t) / 0.05, 0.0, 1.0)
    return 0.4 * wave * env


# --- the degradations on signals with known answers ---------------------------------------------

def test_the_degradation_set_is_the_issue_list():
    assert list(C.DEGRADATIONS) == ["resample_44k1", "resample_96k", "dither_16bit", "gain_low",
                                    "gain_over", "dc_offset", "pad_front", "cut_edges"]


@pytest.mark.parametrize(("name", "rate"), [("resample_44k1", 44100), ("resample_96k", 96000)])
@pytest.mark.parametrize("freq", [30.0, 1000.0, 19000.0])
def test_a_resampled_sine_is_the_same_sine_at_the_new_rate(name, rate, freq):
    x = _sine(freq, 9600, SR)
    y, sr = _apply(name, x)
    assert sr == rate
    assert len(y) == math.ceil(9600 * rate / SR)  # 8820 and 19200
    # Sample n of the copy sits at time n / rate: frequency, phase and level are kept. Away
    # from the edges (the kernel reaches 148 output samples) the error stays below 1e-4
    # (-80 dB; measured 2e-5 at 19 kHz).
    want = _sine(freq, len(y), rate)
    assert np.max(np.abs(y - want)[400:-400]) < 1e-4


def test_downsampling_removes_what_the_new_rate_cannot_hold():
    # 23 kHz is above the 22.05 kHz Nyquist of the copy; unfiltered it would fold to 21.1 kHz
    # at full level. Bound -80 dB (measured -95 dB).
    y, _ = _apply("resample_44k1", _sine(23000.0, 9600, SR))
    assert np.max(np.abs(y[400:-400])) < 1e-4


def test_resampling_keeps_a_constant_and_takes_stereo():
    y, _ = _apply("resample_44k1", np.full(2000, 0.25))
    assert np.max(np.abs(y[200:-200] - 0.25)) < 1e-12
    stereo = np.stack([_sine(440.0, 4800, SR), _sine(660.0, 4800, SR)], axis=1)
    out = C.resample(stereo, SR, 96000)
    assert out.shape == (9600, 2)
    assert np.array_equal(out[:, 1], C.resample(stereo[:, 1], SR, 96000))
    assert np.array_equal(C.resample(stereo, SR, SR), stereo)


def test_the_dithered_copy_is_16_bit_tpdf_with_a_fixed_seed():
    x = np.random.Generator(np.random.PCG64(7)).uniform(-0.9, 0.9, 200_000)
    state = np.random.get_state()[1].copy()
    y, sr = _apply("dither_16bit", x)
    assert sr == SR
    assert np.array_equal(np.random.get_state()[1], state)  # the global generator is untouched
    steps = y * 32768.0
    assert np.array_equal(steps, np.rint(steps))  # on the 16-bit grid
    err = steps - x * 32768.0
    assert np.max(np.abs(err)) <= 1.5  # +-1 LSB of dither plus +-0.5 LSB of rounding
    assert np.max(np.abs(err)) > 1.0  # plain rounding would stay within 0.5
    assert abs(float(np.mean(err))) < 0.01
    # TPDF dither (variance 1/6) plus rounding (1/12) gives LSB^2 / 4 whatever the signal;
    # rounding alone gives 0.083 and rectangular dither 0.167.
    assert float(np.var(err)) == pytest.approx(0.25, abs=0.01)
    assert np.array_equal(y, _apply("dither_16bit", x)[0])  # same seed, same copy
    assert not np.array_equal(y, C.dither_16bit(x, seed=C.DITHER_SEED + 1))


def test_gain_dc_and_trim_do_what_the_table_header_says():
    x = _kick()
    low, _ = _apply("gain_low", x)
    assert np.allclose(low, x * 0.251189, rtol=1e-5, atol=0.0)  # -12 dB
    over, _ = _apply("gain_over", x)
    assert np.allclose(over, x * 1.995262, rtol=1e-5, atol=0.0)  # +6 dB
    assert np.max(np.abs(over)) > 1.0  # above full scale, not clipped
    dc, _ = _apply("dc_offset", x)
    assert np.allclose(dc - x, 0.01, atol=1e-15)
    pad, _ = _apply("pad_front", x)
    assert len(pad) == len(x) + 480  # 10 ms at 48 kHz
    assert not pad[:480].any() and np.array_equal(pad[480:], x)
    cut, _ = _apply("cut_edges", x)
    assert np.array_equal(cut, x[8:-8])
    for name in ("gain_low", "gain_over", "dc_offset", "pad_front", "cut_edges"):
        assert _apply(name, x)[1] == SR
    consts = C.DEGRADE_CONSTANTS
    assert (consts["GAIN_LOW_DB"], consts["GAIN_OVER_DB"], consts["DC_OFFSET"],
            consts["PAD_FRONT_MS"], consts["CUT_SAMPLES"]) == (-12.0, 6.0, 0.01, 10.0, 8)


@pytest.mark.parametrize(("category", "signal"), [("kick", _kick), ("bass", _bass)])
def test_gain_dc_and_front_silence_keep_the_onset_relative_features(category, signal):
    x = signal()
    base = V.features_from_audio(category, x, SR)
    measured = [n for n, v in base.items() if v is not None]
    assert len(measured) >= len(base) - 1, base  # the signal exercises the features
    copies = C.degraded_features(category, x, SR)
    assert set(copies) == set(C.DEGRADATIONS)
    devs, nones = C.degrade_deviations(category, base, copies)
    for n in measured:
        for name in ("gain_low", "gain_over", "dc_offset", "pad_front"):
            # features are peak-normalised, DC-free and counted from the onset: these copies
            # read the same (bound: the 3-decimal rounding of the features)
            assert devs[n][name] <= 2e-3, (n, name, devs[n][name])
    assert not any(nones.values())


def test_a_resampled_copy_keeps_the_pitch_features():
    # 0.05 semitone = 3 cents; the kick sweep and the bass note are far below both Nyquists
    for category, signal, names in (
            ("kick", _kick, ("fundamental_hz", "body_hz", "pitch_20ms_hz", "pitch_40ms_hz")),
            ("bass", _bass, ("note_hz",))):
        x = signal()
        base = V.features_from_audio(category, x, SR)
        devs, _ = C.degrade_deviations(category, base, C.degraded_features(category, x, SR))
        for n in names:
            assert base[n] is not None
            for name in ("resample_44k1", "resample_96k"):
                assert devs[n][name] < 0.05, (n, name, devs[n][name])


# --- statistics on written numbers --------------------------------------------------------------

def test_degrade_deviations_on_written_numbers():
    base = dict.fromkeys(V.FEATURES["kick"])
    base.update(fundamental_hz=50.0, decay_20db_ms=100.0, sub_share=0.5, tail_harmonics_db=-20.0)
    a = dict(base, fundamental_hz=100.0, decay_20db_ms=200.0, sub_share=0.6, body_hz=60.0)
    b = dict(base, fundamental_hz=25.0, tail_harmonics_db=-23.5, sub_share=None)
    devs, nones = C.degrade_deviations("kick", base, {"a": a, "b": b})
    assert devs["fundamental_hz"] == pytest.approx({"a": 12.0, "b": 12.0})  # one octave each
    assert devs["decay_20db_ms"] == pytest.approx({"a": math.log(2.0), "b": 0.0})
    assert devs["tail_harmonics_db"] == pytest.approx({"a": 0.0, "b": 3.5})
    assert devs["sub_share"] == pytest.approx({"a": 0.1})  # copy b: one side None
    assert devs["body_hz"] == {} and devs["click_share"] == {}
    assert nones["sub_share"] == 1 and nones["body_hz"] == 1  # measured on one side only
    assert sum(nones.values()) == 2


@pytest.mark.parametrize(("method", "degrade", "seed", "scale"), [
    (0.3, 0.2, 0.1, 0.3),
    (0.1, 0.4, 0.2, 0.4),  # the degrade error is the largest
    (0.1, 0.2, 0.5, 0.5),
    (0.0, 0.007, 0.0, 0.007),  # a seed-free feature the engine checks read exactly
])
def test_scale_is_the_largest_of_the_three_errors(method, degrade, seed, scale):
    assert C.scale_and_weight(method, degrade, seed, 10.0) == (scale, 1.0)


def test_self_distance_on_written_numbers():
    rows = {"fundamental_hz": {"scale": 0.5, "weight": 1.0},
            "sub_share": {"scale": 0.01, "weight": 1.0},
            "click_share": {"scale": 0.001, "weight": 0.0}}  # the others: provisional scale
    base = dict.fromkeys(V.FEATURES["kick"], 100.0)
    one = {name: dict(base) for name in C.DEGRADATIONS}
    one["dither_16bit"] = dict(base, sub_share=100.04, click_share=150.0)  # 4 units; weight 0
    two = {name: dict(base) for name in C.DEGRADATIONS}
    two["resample_96k"] = dict(base, fundamental_hz=100.0 * 2 ** (3.0 / 12), sub_share=100.02)
    two["cut_edges"] = dict(base, body_hz=None)  # 3 units
    st = C.self_distance_stats("kick", rows, [("one", base, one), ("two", base, two)])
    # 12 kick features, 11 with weight > 0; totals: 4 / sqrt(11), sqrt((6^2 + 2^2) / 11),
    # 3 / sqrt(11), and 13 pairs at 0
    assert st["pairs"] == 16
    assert st["median"] == 0.0
    assert st["max"] == pytest.approx(math.sqrt(40.0 / 11.0), abs=1e-6)
    assert (st["max_candidate"], st["max_degradation"], st["max_feature"]) == \
        ("two", "resample_96k", "fundamental_hz")
    assert st["max_feature_distance"] == pytest.approx(6.0, abs=1e-6)
    assert st["pairs_with_one_sided_none"] == 1
    assert st["by_degradation"]["dither_16bit"]["max"] == pytest.approx(4 / math.sqrt(11), abs=1e-6)
    assert st["by_degradation"]["cut_edges"]["max"] == pytest.approx(3 / math.sqrt(11), abs=1e-6)
    assert st["by_degradation"]["gain_low"] == {"median": 0.0, "max": 0.0}
    # 95th percentile of 13 zeros and 0.905, 1.206, 1.907 (linear interpolation at rank 14.25)
    want = 4 / math.sqrt(11) + 0.25 * (math.sqrt(40.0 / 11.0) - 4 / math.sqrt(11))
    assert st["p95"] == pytest.approx(want, abs=1e-6)
