"""Hat design-tool helpers (#251) on signals with known values (written here, not derived)."""

from __future__ import annotations

import numpy as np
import pytest

from audio_engine import analysis
from audio_engine.analysis import (
    analyse,
    analyse_nonpitched,
    early_late_centroid_ratio,
    hf_share,
    lf_leak_db,
    peak_count,
    t60_line_fit_ms,
    welch_flatness,
)

SR = 48000
SEEDS = range(8)


def _noise(seed: int, n: int = SR) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal(n)


def _expo(t60_ms: float, n: int, seed: int | None = None) -> np.ndarray:
    t = np.arange(n) / SR
    env = 10.0 ** (-3.0 * t / (t60_ms / 1000.0))  # -60 dB at t60_ms
    carrier = _noise(seed, n) if seed is not None else np.sin(2 * np.pi * 7000 * t)
    return env * carrier


def _highpass_fft(x: np.ndarray, hz: float) -> np.ndarray:
    spec = np.fft.rfft(x)
    spec[np.fft.rfftfreq(len(x), 1 / SR) < hz] = 0
    return np.fft.irfft(spec, len(x))


# --- welch_flatness ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", SEEDS)
def test_white_noise_welch_flatness_is_near_one(seed: int) -> None:
    f = welch_flatness(_noise(seed), SR, 6000, 16000)
    assert f is not None and 0.99 <= f <= 1.0
    # the whole-file helper sits near 0.56 (periodogram scatter): the reason for Welch
    assert analysis.spectral_flatness(_noise(seed)) < 0.65


def test_welch_flatness_of_lines_is_low() -> None:
    x = sum(np.sin(2 * np.pi * f * np.arange(SR) / SR) for f in (7000, 9000, 11000))
    x = x + 1e-3 * _noise(1)
    assert welch_flatness(x, SR, 6000, 16000) < 0.2


def test_welch_flatness_short_and_silent() -> None:
    short = _noise(3, int(0.015 * SR))  # 15 ms = 720 samples < 2048 and > 512
    tiny = _noise(3, 100)  # shorter than the 512 segment
    for x in (short, tiny):
        f = welch_flatness(x, SR, 4000, 16000)
        assert f is not None and 0.0 < f <= 1.0
    assert welch_flatness(np.zeros(SR), SR, 4000, 16000) is None
    assert welch_flatness(_noise(1, 8), SR, 4000, 16000) is None
    assert welch_flatness(_noise(1), SR, 30000, 40000) is None  # band above Nyquist


# --- lf_leak_db -------------------------------------------------------------------------------


@pytest.mark.parametrize("seed", SEEDS)
def test_energy_free_band_gives_leak_below_minus_80(seed: int) -> None:
    rng = np.random.default_rng(seed)
    hp = float(rng.uniform(3000, 9000))
    y = _highpass_fft(_noise(seed, 24000), hp / 2 + 100)  # nothing below hp/2
    assert lf_leak_db(y, SR, hp) < -80.0


def test_leak_matches_known_ratio() -> None:
    n = np.arange(SR)
    x = np.sin(2 * np.pi * 1000 * n / SR) + 0.1 * np.sin(2 * np.pi * 9000 * n / SR)
    # hp 6000: the leak band is below 3000 Hz = the 1 kHz sine. Power ratio of the two sines is
    # (0.1 / 1)^2, so the low share is 1 / 1.01.
    assert lf_leak_db(x, SR, 6000) == pytest.approx(10 * np.log10(1 / 1.01), abs=1e-3)
    assert lf_leak_db(x, SR, 18000) == pytest.approx(0.0, abs=0.05)
    # (line above) hp 18000: band is below 9000 Hz, the 9 kHz bin is excluded (< not <=):
    # only the 1 kHz sine counts, giving -0.043 dB
    assert lf_leak_db(np.zeros(10), SR, 6000) is None


def test_hf_share_known_value() -> None:
    n = np.arange(SR)
    x = sum(a * np.sin(2 * np.pi * f * n / SR) for f, a in ((6000, 1), (11000, 1), (13000, 2)))
    assert hf_share(x, SR) == pytest.approx(4 / 6, abs=1e-4)  # only the 13 kHz line is above 12k
    assert hf_share(np.zeros(5), SR) is None


# --- peak_count -------------------------------------------------------------------------------


def test_three_sines_give_three_peaks() -> None:
    n = np.arange(SR // 5)
    x = sum(np.sin(2 * np.pi * f * n / SR) for f in (5000, 7000, 9000))
    assert peak_count(x, SR) == 3


@pytest.mark.parametrize("seed", SEEDS)
def test_random_line_sets_are_counted(seed: int) -> None:
    rng = np.random.default_rng(seed)
    k = int(rng.integers(1, 9))
    freqs = np.sort(rng.choice(np.arange(5000, 19000, 700), size=k, replace=False))
    n = np.arange(SR // 5)
    x = sum(
        np.sin(2 * np.pi * (f + rng.uniform(0, 30)) * n / SR + rng.uniform(0, 6)) for f in freqs
    )
    x = x + 1e-3 * rng.standard_normal(len(n))
    assert peak_count(x, SR) == k


def test_peak_count_noise_short_and_silent() -> None:
    assert peak_count(_noise(2, 4800), SR) <= 2  # noise has no 15 dB lines
    short = sum(np.sin(2 * np.pi * f * np.arange(720) / SR) for f in (5000, 9000))  # 15 ms
    assert peak_count(short, SR) == 2
    assert peak_count(np.zeros(4800), SR) is None
    assert peak_count(np.ones(4), SR) is None


# --- t60_line_fit_ms --------------------------------------------------------------------------


@pytest.mark.parametrize("seed", SEEDS)
def test_line_fit_t60_random_decays_and_100ms_exponential(seed: int) -> None:
    rng = np.random.default_rng(seed)
    t60 = float(rng.uniform(60, 400))
    x = _expo(t60, int((t60 + 100) / 1000 * SR), seed)
    got = t60_line_fit_ms(x, SR)
    assert got == pytest.approx(t60, rel=0.04)  # noise carrier: scatter of the envelope
    # the deterministic carrier (100 ms exponential) is the pinned 2 % case
    x = _expo(100.0, SR // 4)
    assert t60_line_fit_ms(x, SR) == pytest.approx(100.0, rel=0.02)


def test_fit_none_cases() -> None:
    assert t60_line_fit_ms(np.zeros(SR), SR) is None
    assert t60_line_fit_ms(_expo(100.0, 720), SR) is None  # 15 ms: never reaches -40 dB
    assert t60_line_fit_ms(np.sin(2 * np.pi * 7000 * np.arange(SR) / SR), SR) is None  # no decay


# --- early_late_centroid_ratio ----------------------------------------------------------------


def test_early_late_ratio() -> None:
    n = 24000
    t = np.arange(n) / SR
    tone = lambda f, t60: np.sin(2 * np.pi * f * t) * 10.0 ** (-3.0 * t / (t60 / 1000.0))  # noqa: E731
    # high part dies at 60 ms, low part lasts 300 ms -> late window is dominated by 4 kHz
    split = 4 * tone(12000, 60) + tone(4000, 300)
    # Late window (60-100 % of the fitted T60) holds only the 4 kHz tone, so the ratio is the
    # early centroid / 4000 Hz. 2.57 was measured once on this signal (an expected value, not a
    # formula from the code); +-0.05 is narrower than the 0.125 shift when the window starts
    # at 10 % of T60 instead of 60 % (2.44).
    assert early_late_centroid_ratio(split, SR) == pytest.approx(2.57, abs=0.05)
    # a single decaying tone has the same centroid early and late
    assert early_late_centroid_ratio(tone(8000, 200), SR) == pytest.approx(1.0, abs=0.05)
    assert early_late_centroid_ratio(np.zeros(n), SR) is None


# --- scope: sidecar-facing output unchanged ---------------------------------------------------


def test_existing_outputs_have_no_new_keys() -> None:
    x = _noise(1, 9600)
    assert set(analyse_nonpitched(x, SR)) == {
        "peak_dbfs", "length_ms", "spectral_centroid_hz", "hf_share_8k", "t60_ms", "rise_time_ms",
    }
    assert set(analyse(x, SR)) == {
        "peak_dbfs", "length_ms", "fundamental_hz", "decay_20db_ms", "decay_40db_ms", "dc_offset",
    }
