"""Hat DSP blocks (#250): cascaded high-pass, passband-normalised mix, envelope fit."""

from __future__ import annotations

import math

import numpy as np
import pytest

from audio_engine.dsp import highpass_cascade, mix_passband, rbj_highpass, square_bank
from audio_engine.kick import _amp_envelope

SR = 48000
N_IR = 1 << 15
Q = 1 / math.sqrt(2)


def _chain(x: np.ndarray) -> np.ndarray:
    return highpass_cascade(x, SR, 6000.0, 2)


def test_cascade_magnitude_matches_two_squared_butterworth_sections() -> None:
    """Two identical Q=1/sqrt2 sections (not a 4th-order Butterworth): |H|^2 = (1/(1+r^4))^2
    with r = tan(pi f0 / sr) / tan(pi f / sr), measured from the FFT of the impulse response."""
    for f0 in (1000.0, 6000.0):
        impulse = np.zeros(N_IR)
        impulse[0] = 1.0
        got = np.abs(np.fft.rfft(highpass_cascade(impulse, SR, f0, 2)))
        f = np.fft.rfftfreq(N_IR, 1 / SR)[1:]
        ratio = np.tan(np.pi * f0 / SR) / np.tan(np.pi * f / SR)
        expected = 1.0 / (1.0 + ratio**4)
        np.testing.assert_allclose(got[1:], expected, rtol=3e-3, atol=1e-7)


def test_cascade_default_is_two_sections_and_one_section_is_plain_highpass() -> None:
    x = np.random.default_rng(1).standard_normal(2000)
    two = highpass_cascade(x, SR, 5000.0, 2)
    np.testing.assert_array_equal(highpass_cascade(x, SR, 5000.0), two)
    np.testing.assert_array_equal(highpass_cascade(x, SR, 5000.0, 1), rbj_highpass(x, SR, 5000.0))


@pytest.mark.parametrize("bad", [0, -1, 1.5, True])
def test_cascade_refuses_bad_section_count(bad) -> None:
    with pytest.raises(ValueError):
        highpass_cascade(np.zeros(10), SR, 5000.0, bad)


def _parts(seed: int, n: int = 24000):
    t = np.arange(n)
    bank = square_bank([205.3, 304.4, 369.6, 522.7, 540.0, 800.0], SR, n)
    return bank, np.random.default_rng(seed).standard_normal(n), t


@pytest.mark.parametrize("seed", range(5))
@pytest.mark.parametrize("share", [0.0, 0.1, 0.3, 0.6, 0.9, 1.0])
def test_mix_passband_share_measured_on_filtered_parts(seed: int, share: float) -> None:
    """Independent measurement: the power share of the filtered bank in the mix is obtained by
    projecting the mix onto the separately filtered bank and noise (least squares)."""
    bank, noise, _ = _parts(seed)
    mix = mix_passband(bank, noise, share, _chain)
    fb, fn = _chain(bank), _chain(noise)
    coef, *_ = np.linalg.lstsq(np.stack([fb, fn], axis=1), mix, rcond=None)
    pb = coef[0] ** 2 * np.mean(fb**2)
    pn = coef[1] ** 2 * np.mean(fn**2)
    assert pb / (pb + pn) == pytest.approx(share, abs=1e-9)
    # total power is about 1 (bank and noise are nearly uncorrelated)
    assert np.mean(mix**2) == pytest.approx(1.0, abs=0.1)


def test_mix_passband_differs_from_prefilter_normalisation() -> None:
    """The point of the block: normalising before the filter leaves far less bank power."""
    bank, noise, _ = _parts(0)
    pre = math.sqrt(0.6) * bank / bank.std() + math.sqrt(0.4) * noise / noise.std()
    pre_share_bank = np.mean(_chain(math.sqrt(0.6) * bank / bank.std()) ** 2)
    pre_share = pre_share_bank / np.mean(_chain(pre) ** 2)
    assert pre_share < 0.3  # model note: about 5 % of the bank survives the steep high-pass
    mix = mix_passband(bank, noise, 0.6, _chain)
    fb = _chain(bank)
    corr = np.corrcoef(mix, fb)[0, 1]
    assert corr == pytest.approx(math.sqrt(0.6), abs=0.05)


def test_mix_passband_errors() -> None:
    bank, noise, _ = _parts(0, 2000)
    with pytest.raises(ValueError):
        mix_passband(bank, noise, 1.1, _chain)
    with pytest.raises(ValueError):
        mix_passband(bank, noise[:-1], 0.5, _chain)
    with pytest.raises(ValueError):
        mix_passband(np.zeros(2000), noise, 0.5, _chain)
    mix_passband(np.zeros(2000), noise, 0.0, _chain)  # weight 0: no energy needed


def test_kick_envelope_fits_hat_definition() -> None:
    """Linear attack to 1, then -60 dB exactly ``decay`` after the attack (the hat contract)."""
    attack, decay = 0.0008, 0.07
    t = np.array([0.0, attack / 2, attack, attack + decay / 2, attack + decay])
    want = [0, 0.5, 1, 10**-1.5, 1e-3]
    np.testing.assert_allclose(_amp_envelope(t, attack, decay), want, rtol=1e-12, atol=1e-15)
