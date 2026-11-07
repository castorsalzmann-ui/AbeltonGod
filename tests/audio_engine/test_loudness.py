"""BS.1770-4 loudness (#483) against references that do not come from the module.

References used, all written into this file:

* ITU-R BS.1770-4 Table 1 / Table 2: the 48 kHz K-weighting coefficients.
* EBU Tech 3341 v4, Table 1 (minimum requirements test signals), cases 1-6 and 9 rebuilt here
  from their text definitions, plus the momentary burst case (0.18 s at -20 dBFS inside
  -30 dBFS). Quoted from memory: the PDF could not be re-opened in this session (download
  blocked). Every expected value below is also checked by hand arithmetic in the comment next to
  it, so the test does not rest on the memory alone.
* The recursive biquad ``dsp._biquad`` (a different filtering method than the module's FFT
  convolution) running the table coefficients.

All test signals are sine waves at 1 kHz with the given peak level on every channel, so a
stereo sine at X dBFS reads X LUFS (the -0.691 offset cancels the K-weighting gain at 1 kHz).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from audio_engine import loudness
from audio_engine.dsp import _biquad
from audio_engine.loudness import (
    integrated_lufs,
    k_weight,
    k_weighting_coefficients,
    momentary_lufs,
    short_term_lufs,
)

SR = 48000
TOL = 0.1  # Tech 3341: +-0.1 LU for M, S and I

# BS.1770-4 Table 1 (pre-filter) and Table 2 (RLB high-pass), 48 kHz.
TABLE_SHELF = ((1.53512485958697, -2.69169618940638, 1.19839281085285),
               (1.0, -1.69065929318241, 0.73248077421585))
TABLE_HP = ((1.0, -2.0, 1.0), (1.0, -1.99004745483398, 0.99007225036621))


def sine_segments(segments, sr=SR, channels=2, freq=1000.0):
    """Continuous 1 kHz sine whose peak level steps through ``[(dBFS, seconds), ...]``."""
    gains = np.concatenate(
        [np.full(round(sec * sr), 10.0 ** (db / 20.0)) for db, sec in segments]
    )
    t = np.arange(gains.size) / sr
    mono = gains * np.sin(2.0 * math.pi * freq * t)
    return mono if channels == 1 else np.repeat(mono[:, None], channels, axis=1)


# --- K-weighting -------------------------------------------------------------------------------


def test_coefficients_at_48k_match_the_standard_table():
    shelf, hp = k_weighting_coefficients(48000)
    for got, want in ((shelf, TABLE_SHELF), (hp, TABLE_HP)):
        for g, w in zip(got, want, strict=True):
            np.testing.assert_allclose(g, w, rtol=0, atol=1e-12)


def test_fft_filter_equals_recursive_biquads_with_table_coefficients():
    x = np.random.default_rng(483).standard_normal((SR // 2, 2))
    want = np.stack(
        [_biquad(_biquad(x[:, c], *TABLE_SHELF), *TABLE_HP) for c in range(2)], axis=1
    )
    got = k_weight(x, SR)
    assert got.shape == x.shape
    assert np.max(np.abs(got - want)) < 1e-9


def _response_db(stages, sr, f):
    zinv = np.exp(-2j * math.pi * f / sr)
    h = 1.0
    for b, a in stages:
        h *= (b[0] + b[1] * zinv + b[2] * zinv**2) / (a[0] + a[1] * zinv + a[2] * zinv**2)
    return 20.0 * math.log10(abs(h))


@pytest.mark.parametrize("sr", [32000, 44100, 88200, 96000, 192000])
def test_other_rates_follow_the_48k_response(sr):
    """The computed filter at other rates has the 48 kHz table response (+-0.05 dB) below 12 kHz.

    Above that the bilinear transform warps the shelf differently per rate, so it is not checked.
    """
    for f in (20.0, 30.0, 60.0, 100.0, 500.0, 1000.0, 1500.0, 2000.0, 4000.0, 8000.0, 12000.0):
        want = _response_db((TABLE_SHELF, TABLE_HP), 48000, f)
        got = _response_db(k_weighting_coefficients(sr), sr, f)
        assert abs(got - want) < 0.05, (sr, f, got, want)


# --- EBU Tech 3341 v4 cases ----------------------------------------------------------------------


@pytest.mark.parametrize("level", [-23.0, -33.0])  # cases 1 and 2: stereo sine 20 s
def test_cases_1_2_steady_sine(level):
    x = sine_segments([(level, 20.0)])
    assert abs(integrated_lufs(x, SR) - level) <= TOL
    m = momentary_lufs(x, SR)
    s = short_term_lufs(x, SR)
    assert m.size == 197 and s.size == 171  # windows fully inside 20 s, 100 ms hop
    assert np.all(np.abs(m - level) <= TOL)
    assert np.all(np.abs(s - level) <= TOL)


def test_case_3_relative_gate():
    # -36 / -23 / -36 dBFS for 10 / 60 / 10 s. Ungated mean power would read about -24.6 LUFS
    # (10*log10((60*10^-2.3 + 20*10^-3.6) / 80)); the -36 blocks lie below the relative gate
    # (about -34.3), so the result is the -23 part.
    x = sine_segments([(-36.0, 10.0), (-23.0, 60.0), (-36.0, 10.0)])
    assert abs(integrated_lufs(x, SR) - -23.0) <= TOL


def test_case_4_absolute_and_relative_gate():
    x = sine_segments([(-72.0, 10.0), (-36.0, 10.0), (-23.0, 60.0), (-36.0, 10.0), (-72.0, 10.0)])
    assert abs(integrated_lufs(x, SR) - -23.0) <= TOL


def test_case_5_level_steps():
    # -26 / -20 / -26 dBFS for 20 / 20.1 / 20 s: nothing is gated (gate about -33);
    # 10*log10((40*10^-2.6 + 20.1*10^-2.0) / 60.1) = -22.99.
    x = sine_segments([(-26.0, 20.0), (-20.0, 20.1), (-26.0, 20.0)])
    assert abs(integrated_lufs(x, SR) - -23.0) <= TOL


def test_case_6_five_channels_weighting():
    # L, R at -28 dBFS, C at -24 dBFS, Ls, Rs at -30 dBFS. Sum of weighted peak^2:
    # 2*10^-2.8 + 10^-2.4 + 2*1.41*10^-3 = 0.009971, vs 2*10^-2.3 = 0.010024 for the stereo
    # -23 dBFS sine of case 1, so 10*log10(0.009971/0.010024) - 23 = -23.02.
    x = np.concatenate(
        [sine_segments([(db, 20.0)], channels=1)[:, None] for db in (-28, -28, -24, -30, -30)],
        axis=1,
    )
    assert abs(integrated_lufs(x, SR) - -23.0) <= TOL
    # Same file with the surround weight 1.0 instead of 1.41 would read -23.40 (hand arithmetic),
    # so the weight is visible at this tolerance.


def test_case_9_short_term_constant():
    # Five periods of 1.34 s at -20 dBFS + 1.66 s at -30 dBFS: every 3 s window holds 1.34 s of
    # each level's share, 10*log10((1.34*10^-2 + 1.66*10^-3) / 3) = -22.99.
    x = sine_segments([(-20.0, 1.34), (-30.0, 1.66)] * 5)
    s = short_term_lufs(x, SR, hop_s=0.01)
    assert s.size > 1000
    assert np.all(np.abs(s - -23.0) <= TOL)


def test_momentary_burst_max():
    # 0.18 s at -20 dBFS inside -30 dBFS: a 400 ms window holding the whole burst reads
    # 10*log10((0.18*10^-2 + 0.22*10^-3) / 0.4) = -22.97; no window reads more.
    x = sine_segments([(-30.0, 2.0), (-20.0, 0.18), (-30.0, 2.0)])
    m = momentary_lufs(x, SR, hop_s=0.01)
    assert abs(float(np.max(m)) - -23.0) <= TOL


def test_quiet_part_just_above_the_relative_gate_counts():
    # 60 s at -20 dBFS + 20 s at -30 dBFS: mean power 10*log10((60 + 20*0.1)/80) = -1.11 LU
    # relative to -20, gate -31.11, so the -30 part passes and I = -21.11. A gate at -8 LU
    # (-29.11) would drop it and read -20.0.
    x = sine_segments([(-20.0, 60.0), (-30.0, 20.0)])
    assert abs(integrated_lufs(x, SR) - -21.11) <= TOL


@pytest.mark.parametrize("freq", [25.0, 40.0, 60.0, 100.0, 300.0, 3000.0, 8000.0])
def test_loudness_of_sines_follows_the_table_response(freq):
    """Stereo sine at -20 dBFS: L = -0.691 + (-20) + |H_table(f)| in dB (BS.1770 eq. 2)."""
    want = -0.691 - 20.0 + _response_db((TABLE_SHELF, TABLE_HP), SR, freq)
    x = sine_segments([(-20.0, 4.0)], freq=freq)
    assert abs(integrated_lufs(x, SR) - want) <= 0.02, (freq, want)


def test_absolute_gate_decides_quiet_material():
    # 20 s at -65 dBFS, then 60 s at -74 dBFS. Without the -70 LUFS gate the -74 part would pass
    # the relative gate (mean 10*log10((20*10^-6.5 + 60*10^-7.4)/80) = -70.7, gate -80.7) and
    # pull the result to about -70.7. The three blocks that straddle the step (0.75, 0.5, 0.25
    # of their time at -65) still pass -70 and lower the result by about 0.03 LU.
    x = sine_segments([(-65.0, 20.0), (-74.0, 60.0)])
    assert abs(integrated_lufs(x, SR) - -65.0) <= TOL


# --- channels, silence, edges -------------------------------------------------------------------


def test_mono_is_one_channel_with_weight_one():
    mono = sine_segments([(-23.0, 10.0)], channels=1)
    stereo = sine_segments([(-23.0, 10.0)], channels=2)
    assert abs(integrated_lufs(mono, SR) - (-23.0 - 10 * math.log10(2))) <= TOL  # -26.01
    assert integrated_lufs(mono, SR) == pytest.approx(integrated_lufs(mono[:, None], SR))
    assert abs(integrated_lufs(stereo, SR) - -23.0) <= TOL


def test_silence_and_short_files():
    silence = np.zeros((SR * 5, 2))
    assert integrated_lufs(silence, SR) == float("-inf")
    assert np.all(momentary_lufs(silence, SR) == float("-inf"))
    assert np.all(short_term_lufs(silence, SR) == float("-inf"))
    short = sine_segments([(-10.0, 0.39)])  # shorter than one 400 ms block
    assert integrated_lufs(short, SR) == float("-inf")
    assert momentary_lufs(short, SR).size == 0
    assert short_term_lufs(sine_segments([(-10.0, 2.9)]), SR).size == 0
    assert k_weight(np.zeros(0), SR).shape == (0,)


def test_silence_padding_only_adds_the_straddling_blocks():
    # 10 s tone alone: 97 full blocks. With 10 s of silence on both sides the silent blocks are
    # gated out, but 3 blocks on each edge hold 0.75 / 0.5 / 0.25 of tone and pass both gates:
    # mean power 100/103 of the tone's, i.e. 10*log10(100/103) = -0.128 LU (BS.1770 behaviour).
    tone = sine_segments([(-23.0, 10.0)])
    padded = np.concatenate([np.zeros((SR * 10, 2)), tone, np.zeros((SR * 10, 2))])
    diff = integrated_lufs(padded, SR) - integrated_lufs(tone, SR)
    assert abs(diff - 10 * math.log10(100 / 103)) < 0.005


@pytest.mark.parametrize("bad", [np.zeros((10, 6)), np.zeros((10, 2, 1)), np.array([0.0, np.nan])])
def test_bad_audio_is_rejected(bad):
    with pytest.raises(ValueError):
        integrated_lufs(bad, SR)


@pytest.mark.parametrize("rate", [0, 44100.0, True, 1000, 500000])
def test_bad_rate_is_rejected(rate):
    with pytest.raises(ValueError):
        integrated_lufs(np.zeros(SR), rate)


def test_bad_hop_is_rejected():
    with pytest.raises(ValueError):
        momentary_lufs(np.zeros(SR), SR, hop_s=0.0)


# --- seeded property tests ----------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(12))
def test_random_rate_level_channels(seed):
    rng = np.random.default_rng(seed)
    sr = int(rng.choice([22050, 32000, 44100, 48000, 88200, 96000]))
    level = float(rng.uniform(-60.0, -1.0))
    channels = int(rng.integers(1, 3))
    x = sine_segments([(level, float(rng.uniform(1.0, 6.0)))], sr=sr, channels=channels)
    want = level if channels == 2 else level - 10 * math.log10(2)
    assert abs(integrated_lufs(x, sr) - want) <= TOL, (sr, level, channels)
    assert np.all(np.abs(momentary_lufs(x, sr) - want) <= TOL)


@pytest.mark.parametrize("seed", range(8))
def test_random_loud_quiet_pair_is_gated(seed):
    """Loud part at L, quiet part 20-40 dB lower: the quiet part is below the relative gate."""
    rng = np.random.default_rng(1000 + seed)
    loud = float(rng.uniform(-40.0, -5.0))
    quiet = loud - float(rng.uniform(20.0, 40.0))
    order = [(loud, 20.0), (quiet, float(rng.uniform(5.0, 40.0)))]
    if rng.integers(2):
        order.reverse()
    assert abs(integrated_lufs(sine_segments(order), SR) - loud) <= TOL, order


def test_constants_follow_bs1770():
    """Guard against silent edits of the published constants."""
    assert loudness.CHANNEL_WEIGHTS == (1.0, 1.0, 1.0, 1.41, 1.41)
    assert loudness.ABSOLUTE_GATE_LUFS == -70.0 and loudness.RELATIVE_GATE_LU == -10.0
    assert loudness.LOUDNESS_OFFSET_DB == -0.691
