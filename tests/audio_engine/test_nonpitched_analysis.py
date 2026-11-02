"""Non-pitched analysis features (#230) on synthetic signals with known values."""

from __future__ import annotations

import numpy as np
import pytest

from audio_engine.analysis import (
    analyse,
    analyse_nonpitched,
    rms_envelope,
    spectral_flatness,
)

SR = 48000


def _sine(f: float, n: int = SR, amp: float = 1.0) -> np.ndarray:
    return amp * np.sin(2 * np.pi * f * np.arange(n) / SR)


def test_centroid_of_bin_aligned_sines() -> None:
    x = (_sine(1000) + _sine(3000)) * 0.4
    assert analyse_nonpitched(x, SR)["spectral_centroid_hz"] == pytest.approx(2000.0, abs=0.5)
    assert analyse_nonpitched(_sine(5000, amp=0.5), SR)["spectral_centroid_hz"] == pytest.approx(
        5000.0, abs=0.5
    )


@pytest.mark.parametrize("hf_amp,expected", [(1.0, 0.5), (2.0, 0.8), (0.0, 0.0)])
def test_hf_share_is_energy_share_above_8k(hf_amp: float, expected: float) -> None:
    x = 0.3 * (_sine(4000) + hf_amp * _sine(12000))
    assert analyse_nonpitched(x, SR)["hf_share_8k"] == pytest.approx(expected, abs=1e-4)


@pytest.mark.parametrize("f,expected", [(7500.0, 0.0), (8500.0, 1.0)])
def test_hf_split_sits_at_8k(f: float, expected: float) -> None:
    got = analyse_nonpitched(0.5 * _sine(f), SR)["hf_share_8k"]
    assert got == pytest.approx(expected, abs=1e-4)


def _shaped_noise(env: np.ndarray, seed: int = 1) -> np.ndarray:
    return env * np.random.default_rng(seed).standard_normal(len(env))


@pytest.mark.parametrize("t60", [40.0, 120.0, 300.0])
def test_t60_of_exponential_decay(t60: float) -> None:
    n = SR
    t = np.arange(n) / SR
    env = 0.5 * 10 ** (-3.0 * t / (t60 / 1000))  # -60 dB after t60
    got = analyse_nonpitched(_shaped_noise(env), SR)["t60_ms"]
    assert got == pytest.approx(t60, rel=0.06)


def test_t60_is_none_when_sound_is_cut_off_by_the_file_end() -> None:
    t = np.arange(SR // 5) / SR  # 200 ms, decay needs 500 ms
    env = 0.5 * 10 ** (-3.0 * t / 0.25)  # only -48 dB at the file end
    env[-240:] *= np.linspace(1, 0, 240)  # 5 ms fade-out as the engines do
    # without the guard the fade-out would be read as the -60 dB point
    assert analyse_nonpitched(_shaped_noise(env), SR)["t60_ms"] is None


def _attack_env(rise_ms: float) -> np.ndarray:
    n_rise = int(rise_ms / 1000 * SR)
    return np.concatenate([np.linspace(0, 1, n_rise), np.exp(-np.arange(SR // 2) / (0.015 * SR))])


@pytest.mark.parametrize("rise", [2.0, 5.0, 10.0])
def test_rise_time_of_linear_attack(rise: float) -> None:
    # A 3 kHz carrier keeps the envelope smooth; 10 % -> 90 % of a linear ramp is 0.8 * rise.
    # The 1 ms RMS window smooths the ramp, worth up to about 0.2 ms.
    env = _attack_env(rise)
    x = env * np.sin(2 * np.pi * 3000 * np.arange(len(env)) / SR)
    assert analyse_nonpitched(x, SR)["rise_time_ms"] == pytest.approx(0.8 * rise, abs=0.3)


def test_rise_time_of_noise_is_approximate() -> None:
    # Noise makes the envelope fluctuate (about 20 % per 1 ms window): measured spread over six
    # seeds of a 5 ms attack was 3.6 ... 4.8 ms against 4.0 ms. Read it as +-1 ms.
    env = _attack_env(5.0)
    for seed in range(4):
        got = analyse_nonpitched(_shaped_noise(env, seed), SR)["rise_time_ms"]
        assert got == pytest.approx(4.0, abs=1.0)


def test_flatness_known_signals() -> None:
    impulse = np.zeros(4096)
    impulse[100] = 1.0
    assert spectral_flatness(impulse) == pytest.approx(1.0, abs=1e-9)
    assert spectral_flatness(_sine(1000, 4800)) < 1e-3
    noise = np.random.default_rng(0).standard_normal(1 << 16)
    assert spectral_flatness(noise) == pytest.approx(np.exp(-np.euler_gamma), abs=0.02)
    assert spectral_flatness(np.zeros(100)) is None


def test_silence_gives_none_features() -> None:
    out = analyse_nonpitched(np.zeros(1000), SR)
    assert out["peak_dbfs"] is None and out["length_ms"] > 0
    assert all(out[k] is None for k in ("spectral_centroid_hz", "hf_share_8k", "t60_ms",
                                        "rise_time_ms"))


def test_output_keys_match_the_sidecar_contract() -> None:
    import json

    from audio_engine.params import METADATA_SCHEMA_FILE

    schema = json.loads(METADATA_SCHEMA_FILE.read_text())
    allowed = set(schema["properties"]["features"]["properties"])
    assert set(analyse_nonpitched(_sine(1000), SR)) <= allowed


def test_rms_envelope_of_constant_sine() -> None:
    env = rms_envelope(_sine(1000, 4800), SR)
    assert env[1000] == pytest.approx(1 / np.sqrt(2), abs=0.01)


def test_kick_analyse_is_unchanged() -> None:
    # Same keys as before #230 and no new feature leaked into the kick output.
    assert set(analyse(_sine(60, 4800), SR)) == {
        "peak_dbfs", "length_ms", "fundamental_hz", "decay_20db_ms", "decay_40db_ms", "dc_offset",
    }
