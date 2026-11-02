"""Rim voice (#321): contract, determinism, measured targets, golden hashes, fault injection.

Measurement method (independent of the engine code, numpy only): spectral peaks come from a
Hann-windowed, zero-padded FFT with parabolic interpolation, decay from a straight-line fit of
the dB envelope of an FFT analytic signal (Hilbert), levels from FFT magnitudes. Expected values
are written here from the contract text; the engine's envelope helper, filters and phase are
never used as the reference. Each important check is a ``_check_*`` function that runs on the
engine and again on a deliberately broken engine (the "mutant" tests), so the check is shown to
be able to fail.
"""

from __future__ import annotations

import hashlib
import json
import math
import time

import numpy as np
import pytest

import audio_engine.rim as R
from audio_engine import rim_variants
from audio_engine.io import encode_wav, wav_samples
from audio_engine.presets import load_preset, preset_names
from audio_engine.rim import RimParamsError, render_rim, resolve_rim_params

SCHEMA = json.loads(R.RIM_SCHEMA_FILE.read_text(encoding="utf-8"))
PROPS = SCHEMA["properties"]
NUMERIC = [k for k, v in PROPS.items() if v.get("type") in ("number", "integer")]
BASE = {"schema_version": "0.1", "seed": 5}
SR = 48000
NO_CLICK = {"click_level": 0.0}


def _draw(rng: np.random.Generator) -> dict:
    """One random parameter set over the whole contract range (endpoints now and then)."""
    p: dict = {"schema_version": "0.1", "seed": int(rng.integers(0, 2**32))}
    for name, prop in PROPS.items():
        if name in ("schema_version", "seed", "preset", "bpm", "variants", "hp_hz"):
            continue
        if "enum" in prop:
            p[name] = prop["enum"][int(rng.integers(len(prop["enum"])))]
        else:
            pick = rng.random()
            p[name] = float(
                prop["minimum"] if pick < 0.08 else prop["maximum"] if pick < 0.16
                else rng.uniform(prop["minimum"], prop["maximum"])
            )
    hi = min(PROPS["hp_hz"]["maximum"], 0.8 * p["f1_hz"] - 1e-3)
    p["hp_hz"] = float(rng.uniform(PROPS["hp_hz"]["minimum"], hi)) if rng.random() < 0.9 else hi
    if rng.random() < 0.15:
        p["level2"] = 0.0
    if rng.random() < 0.15:
        p["click_level"] = 0.0
    return p


RANDOM = [_draw(np.random.default_rng(900 + i)) for i in range(20)]


def _r(**kw) -> np.ndarray:
    return render_rim({**BASE, **kw})[0]


# --- independent measurement helpers (numpy only) ---------------------------------------------


def _bandpass(x: np.ndarray, lo: float, hi: float, sr: int = SR) -> np.ndarray:
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1.0 / sr)
    spec[(f < lo) | (f > hi)] = 0.0
    return np.fft.irfft(spec, len(x))


def _analytic(x: np.ndarray) -> np.ndarray:
    n = len(x)
    h = np.zeros(n)
    h[0] = 1.0
    if n % 2 == 0:
        h[n // 2] = 1.0
        h[1:n // 2] = 2.0
    else:
        h[1:(n + 1) // 2] = 2.0
    return np.fft.ifft(np.fft.fft(x) * h)


def _spectrum(x: np.ndarray, t0_ms: float, t1_ms: float) -> tuple[np.ndarray, np.ndarray]:
    w = x[int(t0_ms * SR / 1000):int(t1_ms * SR / 1000)]
    n = 1 << 17
    return np.fft.rfftfreq(n, 1.0 / SR), np.abs(np.fft.rfft(w * np.hanning(len(w)), n))


def _peak(x: np.ndarray, lo: float, hi: float, t0_ms: float = 0.0, t1_ms: float = 30.0
          ) -> tuple[float, float]:
    """(frequency by parabolic interpolation, magnitude) of the spectral peak in [lo, hi]."""
    f, sp = _spectrum(x, t0_ms, t1_ms)
    i = int(np.argmax(np.where((f >= lo) & (f <= hi), sp, 0.0)))
    a, b, c = np.log(sp[i - 1:i + 2] + 1e-30)
    shift = 0.5 * (a - c) / (a - 2 * b + c)
    return float(f[i] + shift * (f[1] - f[0])), float(sp[i])


def _fit_decay_ms(env: np.ndarray, top_db: float, bottom_db: float) -> float:
    """60 dB time from a straight-line fit of the dB envelope between ``top_db`` and
    ``bottom_db`` below its maximum (searched in the first 20 ms), after that maximum."""
    db = 20.0 * np.log10(np.maximum(env, 1e-12))
    im = int(np.argmax(env[:int(0.02 * SR)]))
    seg = db[im:]
    first_top = int(np.argmax(seg <= db[im] - top_db))
    first_bottom = int(np.argmax(seg <= db[im] - bottom_db))
    idx = np.arange(first_top, first_bottom + 1)  # first pass through the band, ripple included
    slope = np.polyfit(idx / SR, seg[idx], 1)[0]
    return -60.0 / slope * 1000.0


# --- contract ---------------------------------------------------------------------------------


def test_defaults_are_filled_and_resolving_twice_changes_nothing() -> None:
    r = resolve_rim_params(BASE)
    for name, prop in PROPS.items():
        if "default" in prop:
            assert r[name] == prop["default"]
    assert r["length_ms"] == 200
    assert resolve_rim_params(r) == r
    assert "variants" in r and "variants" not in render_rim(BASE)[1]


@pytest.mark.parametrize("field", NUMERIC)
def test_every_numeric_bound_is_enforced_not_clamped(field: str) -> None:
    prop = PROPS[field]
    for edge in (prop["minimum"], prop["maximum"]):
        extra = {}
        if field == "hp_hz" and edge == prop["maximum"]:
            continue  # 6000 violates hp < 0.8 f1 for every f1: own test below
        assert resolve_rim_params({**BASE, **extra, field: edge})[field] == edge
    for bad in (prop["minimum"] - 1e-6, prop["maximum"] + 1e-6):
        if prop["type"] == "integer":
            bad = int(prop["minimum"] - 1) if bad < prop["minimum"] else int(prop["maximum"] + 1)
        with pytest.raises(RimParamsError, match=field):
            resolve_rim_params({**BASE, field: bad})


def test_hp_hz_maximum_is_unreachable_by_the_cross_field_rule() -> None:
    """Measured finding: hp_hz < 0.8 * f1_hz <= 2800, so the schema maximum 6000 never passes."""
    with pytest.raises(RimParamsError, match="hp_hz: must be less than 0.8"):
        resolve_rim_params({**BASE, "f1_hz": 3500, "hp_hz": 6000})
    assert resolve_rim_params({**BASE, "f1_hz": 3500, "hp_hz": 2799.9})["hp_hz"] == 2799.9


@pytest.mark.parametrize("f1", [300.0, 455.0, 1000.0, 2500.0, 3500.0])
def test_cross_field_rule_hp_less_than_0_8_f1(f1: float) -> None:
    edge = 0.8 * f1
    for hp in (edge, edge + 0.1):
        if hp <= 6000:
            with pytest.raises(RimParamsError, match="hp_hz: must be less than 0.8"):
                resolve_rim_params({**BASE, "f1_hz": f1, "hp_hz": hp})
    assert resolve_rim_params({**BASE, "f1_hz": f1, "hp_hz": edge - 0.1})
    # omitted partners stay valid (contract $comment 1): default hp with every f1, and default
    # f1 with an hp below 364
    assert resolve_rim_params({**BASE, "f1_hz": f1})
    with pytest.raises(RimParamsError, match="hp_hz"):
        resolve_rim_params({**BASE, "hp_hz": 364})
    assert resolve_rim_params({**BASE, "hp_hz": 363.9})


@pytest.mark.parametrize(
    "bad",
    [{"nope": 1}, {"bit_depth": 20}, {"polarity": 0}, {"level2": float("nan")}, {"seed": -1},
     {"drive": True}, {"f1_hz": "455"}, {"variants": 2.5}, {"f3_ratio": 0}, {"bend": 1.0},
     {"tone_peak_db": 0}],
)
def test_bad_values_and_fields_outside_v01_are_rejected(bad: dict) -> None:
    with pytest.raises(RimParamsError):
        resolve_rim_params({**BASE, **bad})
    with pytest.raises(RimParamsError):
        resolve_rim_params({"seed": 1})  # schema_version missing


def test_whole_number_floats_become_ints() -> None:
    r = resolve_rim_params({**BASE, "seed": 7.0, "polarity": -1.0, "sample_rate": 44100.0})
    assert (r["seed"], r["polarity"], r["sample_rate"]) == (7, -1, 44100)
    assert all(type(r[k]) is int for k in ("seed", "polarity", "sample_rate"))


# --- determinism and wrong-audio failures over the whole range ---------------------------------


@pytest.mark.parametrize("p", RANDOM, ids=[f"r{i}" for i in range(len(RANDOM))])
def test_random_full_range_invariants(p: dict) -> None:
    a, r = render_rim(p)
    again, _ = render_rim(p)
    assert a.tobytes() == again.tobytes()
    other = render_rim({**p, "seed": (p["seed"] + 1) % 2**32})[0]
    assert (other.tobytes() != a.tobytes()) == (r["click_level"] > 0.0)
    sr, bits = r["sample_rate"], r["bit_depth"]
    assert len(a) == round(r["length_ms"] * sr / 1000)
    assert np.all(np.isfinite(a))
    off = round(r["offset_ms"] * sr / 1000)
    assert np.all(a[:off] == 0.0) and a[off] == 0.0  # silence, then the first sound sample is 0
    q = wav_samples(encode_wav(a, sr, bits)) / (2 ** (bits - 1) - 1)
    peak_db = 20 * math.log10(float(np.max(np.abs(q))))
    assert r["peak_ceiling_dbfs"] - 0.05 <= peak_db <= r["peak_ceiling_dbfs"] + 1e-9
    assert a[-1] == 0.0  # fade-out, no click at the end
    assert abs(float(np.mean(a))) < 1e-3 * float(np.max(np.abs(a)))
    assert resolve_rim_params(r) == {**r, "variants": 1}


def test_worst_case_render_time() -> None:
    p = {**BASE, "length_ms": 600, "decay1_ms": 120, "decay2_ms": 120, "drive": 1,
         "click_level": 1, "click_ms": 3, "f1_hz": 3500, "f2_ratio": 5.0, "level2": 1,
         "sample_rate": 44100}
    start = time.perf_counter()
    render_rim(p)
    assert time.perf_counter() - start <= 20.0


def test_file_fields_do_what_they_say() -> None:
    a, _ = render_rim(BASE)
    assert len(a) == round(0.2 * SR)
    off = _r(offset_ms=12)
    assert np.all(off[:576] == 0.0) and np.any(off[576:] != 0.0) and len(off) == len(a)
    assert np.array_equal(_r(polarity=-1), -a)
    cut = _r(length_ms=50)
    assert len(cut) == 2400 and cut[-1] == 0.0 and np.any(cut[:2000] != 0.0)
    w16 = encode_wav(_r(sample_rate=44100, bit_depth=16), 44100, 16)
    assert w16[24:28] == (44100).to_bytes(4, "little")


# --- measured targets: partials ----------------------------------------------------------------

PARTIAL_CASES = [  # (f1_hz, f2_ratio, hp_hz)
    (300.0, 2.0, 200.0), (455.0, 3.66, 200.0), (700.0, 4.4, 300.0), (1200.0, 2.7, 600.0),
    (2000.0, 3.1, 900.0), (3500.0, 5.0, 1500.0), (800.0, 2.0, 400.0),
]


def _check_partial_frequencies() -> None:
    """Spectral peaks of the first 30 ms (long decays) are at f1_hz and f1_hz * f2_ratio,
    within 0.5 % (measured on the engine: 0.04 %)."""
    for f1, ratio, hp in PARTIAL_CASES:
        a = _r(f1_hz=f1, f2_ratio=ratio, hp_hz=hp, level2=1.0, decay1_ms=120, decay2_ms=120,
               **NO_CLICK, length_ms=300)
        low, _ = _peak(a, 0.8 * f1, 1.2 * f1)
        high, _ = _peak(a, 0.9 * f1 * ratio, 1.1 * f1 * ratio)
        assert abs(low / f1 - 1) < 0.005, (f1, low)
        assert abs(high / (f1 * ratio) - 1) < 0.005, (f1, ratio, high)


def test_partial_frequencies_are_where_the_contract_says() -> None:
    _check_partial_frequencies()


def test_partial_frequencies_survive_a_click() -> None:
    for seed in (1, 2, 3):
        a = _r(seed=seed, click_level=1.0, click_ms=3, decay1_ms=40, decay2_ms=40, level2=0.8)
        low, _ = _peak(a, 350, 600)
        assert abs(low / 455 - 1) < 0.01, (seed, low)


def _check_level2() -> None:
    """The upper line is level2 times the lower one (linear, at t = 0): spectral peak ratio
    over the first 30 ms with equal decays, within 0.7 dB. The two lines sit at 1.67 and
    4.7 kHz where the 200 Hz high-pass acts by less than 0.1 dB."""
    for lv in (0.1, 0.3, 0.6, 1.0):
        a = _r(level2=lv, decay1_ms=120, decay2_ms=120, f1_hz=1000, f2_ratio=4.0, hp_hz=200,
               **NO_CLICK, length_ms=300)
        _, lo = _peak(a, 900, 1100)
        _, hi = _peak(a, 3800, 4200)
        got = 20 * math.log10(hi / lo)
        assert abs(got - 20 * math.log10(lv)) < 0.7, (lv, got)


def test_level2_is_the_amplitude_ratio() -> None:
    _check_level2()


def test_level2_zero_is_a_single_partial() -> None:
    a = _r(level2=0.0, **NO_CLICK, decay1_ms=120, f1_hz=1000, hp_hz=200, length_ms=300)
    _, lo = _peak(a, 900, 1100)
    _, where = _peak(a, 1500, 17500)
    assert where < 1e-3 * lo  # nothing but the lower line (and its skirt)
    # f2_ratio and decay2_ms have no effect at level2 0
    b = _r(level2=0.0, **NO_CLICK, decay1_ms=120, f1_hz=1000, hp_hz=200, length_ms=300,
           f2_ratio=4.9, decay2_ms=7)
    assert np.array_equal(a, b)


def _check_decays() -> None:
    """decay1_ms / decay2_ms are 60 dB times (contract point 4). Lower partial alone
    (level2 0): analytic envelope of the whole signal, fit -3..-25 dB, within 6 % (measured
    +3.7 % at the default 40 ms, <= 1 % from 80 ms). Upper partial: band 0.85..1.15 times its
    frequency, decays from 40 ms (a brick-wall band biases shorter ones: +9 % measured at
    15 ms, which is why shorter decays are not checked on the upper partial), within 8 %."""
    for f1, d in [(455.0, 15.0), (455.0, 40.0), (900.0, 70.0), (2500.0, 25.0), (455.0, 110.0)]:
        a = _r(f1_hz=f1, level2=0.0, decay1_ms=d, **NO_CLICK, hp_hz=200, length_ms=500)
        got = _fit_decay_ms(np.abs(_analytic(a)), 3.0, 25.0)
        assert abs(got / d - 1) < 0.06, (f1, d, got)
    for d2 in (40.0, 70.0, 110.0):
        a = _r(f1_hz=700.0, f2_ratio=3.5, level2=1.0, decay1_ms=5, decay2_ms=d2, **NO_CLICK,
               hp_hz=200, length_ms=500)
        env = np.abs(_analytic(_bandpass(a, 0.85 * 2450, 1.15 * 2450)))
        got = _fit_decay_ms(env, 3.0, 25.0)
        assert abs(got / d2 - 1) < 0.08, (d2, got)


def test_decays_match_the_contract() -> None:
    _check_decays()


def _check_highpass_gain() -> None:
    """hp_hz is a 2nd-order Butterworth-type high-pass (-3 dB at hp_hz): the lower line loses
    10 log10(1 + (hp/f1)^4) dB (written here; the upper line at 5 * f1 loses < 0.01 dB),
    measured as the change of the lower/upper line ratio against hp_hz 200 (the minimum),
    within 0.2 dB."""
    for f1, frac in [(1000.0, 0.79), (1000.0, 0.7), (600.0, 0.6), (1500.0, 0.75)]:
        kw = {"f1_hz": f1, "f2_ratio": 5.0, "level2": 1.0, "decay1_ms": 120, "decay2_ms": 120,
              "click_level": 0.0, "length_ms": 300}

        def ratio(hp, kw=kw):
            a = _r(**kw, hp_hz=hp)
            return 20 * math.log10(_peak(a, 0.9 * kw["f1_hz"], 1.1 * kw["f1_hz"])[1]
                                   / _peak(a, 4.5 * kw["f1_hz"], 5.5 * kw["f1_hz"])[1])

        want = -10 * math.log10(1 + frac**4) + 10 * math.log10(1 + (200.0 / f1) ** 4)
        got = ratio(frac * f1) - ratio(200.0)
        assert abs(got - want) < 0.2, (f1, frac, got, want)


def test_highpass_gain_follows_a_second_order_corner() -> None:
    _check_highpass_gain()


# --- click -------------------------------------------------------------------------------------


def _lower_amplitude(x0: np.ndarray) -> float:
    """Amplitude of the decaying lower partial (455 Hz, 40 ms) in ``x0``: least-squares fit of
    sin and cos times exp(-t ln(1000) / 40 ms) over 3-40 ms (written here; phase independent,
    so the high-pass phase lead does not bias it). Includes the high-pass gain (0.98)."""
    n = np.arange(int(0.003 * SR), int(0.040 * SR))
    tm = n / SR
    e = np.exp(-tm * math.log(1000) / 0.040)
    basis = np.stack([np.sin(2 * np.pi * 455 * tm) * e, np.cos(2 * np.pi * 455 * tm) * e], 1)
    return float(np.hypot(*np.linalg.lstsq(basis, x0[n], rcond=None)[0]))


def _click_of(seed: int, level: float, ms: float) -> tuple[np.ndarray, float]:
    """Click signal in the units of the click-free render, and the lower-partial amplitude in
    the same units. x_c = k * (x_0 + click): k is fitted below 2.5 kHz, where the click (high-
    passed at 4 kHz) has almost no energy."""
    kw = {"level2": 0.0, "decay1_ms": 40, "hp_hz": 200, "seed": seed}
    x0 = _r(**kw, click_level=0.0)
    xc = _r(**kw, click_level=level, click_ms=ms)
    lo0, loc = _bandpass(x0, 0, 2500), _bandpass(xc, 0, 2500)
    k = float(np.dot(loc, lo0) / np.dot(lo0, lo0))
    return xc / k - x0, _lower_amplitude(x0)


def _check_click_level_and_decay() -> None:
    """click_level is the click's RMS at t = 0 relative to the lower partial's amplitude, and
    click_ms its 60 dB time (contract point 6). Over 0-3 ms with click_ms 3 the expected RMS is
    click_level * sqrt(mean(exp(-2 t ln(1000) / 3 ms))) (written here); mean of 20 seeds
    (one seed scatters ~10 % in 144 samples), between 0.85 and 1.0 of nominal (measured 0.92,
    see below). Decay: 0.25 ms RMS blocks, fit from -3 to -30 dB, 20 seeds averaged, within
    12 %."""
    t = np.arange(int(0.003 * SR)) / SR
    shape = float(np.sqrt(np.mean(np.exp(-2 * t * math.log(1000) / 0.003))))
    for level in (0.3, 0.7, 1.0):
        got = []
        for seed in range(1, 21):
            c, amp = _click_of(seed, level, 3.0)
            got.append(float(np.sqrt(np.mean(c[:len(t)] ** 2))) / amp)
        # measured 0.92 of nominal: the two RBJ sections start from rest, so the first two
        # click samples are 0.65 / 0.69 of the stationary RMS, and the envelope weights them
        # most (about 5 % of the RMS over 0-3 ms); the rest is the 0.98 high-pass gain on the
        # reference amplitude. A click 20 % too loud lands at 1.10 and fails the upper bound.
        assert 0.85 <= np.mean(got) / (level * shape) <= 1.0, (level, np.mean(got), shape)
    for ms in (1.0, 3.0):
        acc = np.zeros(int(0.0015 * SR) // 12)
        for seed in range(1, 21):
            c, _ = _click_of(seed, 1.0, ms)
            blk = c[:len(acc) * 12].reshape(-1, 12)
            acc += np.mean(blk**2, axis=1)
        env = np.sqrt(acc / 20)
        db = 20 * np.log10(env)
        idx = np.nonzero((db <= db[0] - 3) & (db >= db[0] - 30))[0]
        slope = np.polyfit((idx + 0.5) * 12 / SR, db[idx], 1)[0]
        assert abs(-60 / slope * 1000 / ms - 1) < 0.12, (ms, -60 / slope * 1000)


def test_click_level_and_decay_match_the_contract() -> None:
    _check_click_level_and_decay()


def test_click_is_high_passed_at_4_khz_and_not_touched_by_hp_hz() -> None:
    c, _ = _click_of(3, 1.0, 3.0)
    e = np.abs(np.fft.rfft(c[:480])) ** 2  # 10 ms
    f10 = np.fft.rfftfreq(480, 1.0 / SR)
    assert e[f10 < 1500].sum() < 0.02 * e[f10 > 4000].sum()
    assert e[(f10 > 4500) & (f10 < 18000)].sum() > 0.5 * e.sum()


def test_click_level_zero_is_seed_independent_with_positive_control() -> None:
    _check_seed_acts_only_on_click()


def _check_seed_acts_only_on_click() -> None:
    assert np.array_equal(_r(seed=1, click_level=0.0), _r(seed=2, click_level=0.0))
    assert not np.array_equal(_r(seed=1, click_level=0.05), _r(seed=2, click_level=0.05))
    # the partials do not move with the seed: below 2 kHz the two renders agree up to the
    # click's skirt and the normalisation
    a, b = _bandpass(_r(seed=1), 0, 2000), _bandpass(_r(seed=2), 0, 2000)
    assert float(np.corrcoef(a, b)[0, 1]) > 0.999


def test_click_level_raises_the_high_band_monotonically() -> None:
    for seed in range(1, 6):
        share = []
        for lv in (0.0, 0.2, 0.5, 1.0):
            hb = _bandpass(_r(seed=seed, click_level=lv, click_ms=2), 4000, 20000)
            share.append(float(np.sum(hb[:240] ** 2) / np.sum(_r(seed=seed, click_level=lv,
                                                                  click_ms=2) ** 2)))
        assert share == sorted(share), share


def test_drive_changes_the_signal_and_lowers_the_crest_factor() -> None:
    for seed in range(1, 5):
        crest = []
        for d in (0.0, 0.3, 0.6, 1.0):
            a = _r(seed=seed, drive=d)
            crest.append(float(np.max(np.abs(a)) / np.sqrt(np.mean(a**2))))
        assert crest == sorted(crest, reverse=True) and crest[0] > crest[-1] + 0.2, crest


def test_no_energy_above_the_click_lowpass() -> None:
    """The click is band-limited below 0.45 * sample_rate: at 44.1 kHz the energy above
    20 kHz (0.454 * sr) is small against the band 4-18 kHz."""
    a = _r(sample_rate=44100, click_level=1.0, click_ms=3, f1_hz=300, level2=0.0)
    e = np.abs(np.fft.rfft(a)) ** 2
    f = np.fft.rfftfreq(len(a), 1 / 44100)
    assert e[f > 20500].sum() < 0.1 * e[(f > 4000) & (f < 18000)].sum()


# --- fault injection: each key check turns red on a broken engine -------------------------------


def test_mutant_lower_partial_5_percent_sharp_fails(monkeypatch) -> None:
    real = R._partials
    monkeypatch.setattr(R, "_partials", lambda p, t: real({**p, "f1_hz": p["f1_hz"] * 1.05}, t))
    with pytest.raises(AssertionError):
        _check_partial_frequencies()


def test_mutant_upper_ratio_2_percent_off_fails(monkeypatch) -> None:
    real = R._partials
    monkeypatch.setattr(R, "_partials",
                        lambda p, t: real({**p, "f2_ratio": p["f2_ratio"] * 1.02}, t))
    with pytest.raises(AssertionError):
        _check_partial_frequencies()


def test_mutant_level2_scaled_fails(monkeypatch) -> None:
    real = R._partials
    monkeypatch.setattr(R, "_partials", lambda p, t: real({**p, "level2": p["level2"] * 0.85}, t))
    with pytest.raises(AssertionError):
        _check_level2()


def test_mutant_slower_envelope_fails_decay_and_click_checks(monkeypatch) -> None:
    real = R._amp_envelope
    monkeypatch.setattr(R, "_amp_envelope", lambda t, a, d: real(t, a, d * 1.15))
    with pytest.raises(AssertionError):
        _check_decays()
    with pytest.raises(AssertionError):
        _check_click_level_and_decay()


def test_mutant_highpass_corner_moved_fails(monkeypatch) -> None:
    real = R.rbj_highpass
    monkeypatch.setattr(R, "rbj_highpass", lambda x, sr, f0, *a: real(x, sr, f0 * 1.25, *a))
    with pytest.raises(AssertionError):
        _check_highpass_gain()


def test_mutant_click_scaled_fails(monkeypatch) -> None:
    real = R._click
    monkeypatch.setattr(R, "_click", lambda p, t: 1.2 * real(p, t))
    with pytest.raises(AssertionError):
        _check_click_level_and_decay()


def test_mutant_seed_ignored_fails_the_positive_control(monkeypatch) -> None:
    real = R.substreams
    monkeypatch.setattr(R, "substreams", lambda seed, count: real(0, count))
    with pytest.raises(AssertionError):
        _check_seed_acts_only_on_click()


# --- presets -----------------------------------------------------------------------------------

PRESETS = ["clave", "high", "long", "rim", "tight"]


def test_the_five_presets_exist_and_validate() -> None:
    assert preset_names("rim") == PRESETS
    for name in PRESETS:
        p = load_preset(name, "rim")
        assert p["preset"] == name
        resolve_rim_params(p)
    assert load_preset("clave", "rim")["level2"] == 0


def test_preset_measurements_follow_their_fields() -> None:
    """Directions only (placeholders, no taste range): fitted lower-partial decay order, f1
    order, and the clave preset has one spectral line."""
    def decay(name):
        a = render_rim({**load_preset(name, "rim"), "level2": 0.0, "click_level": 0.0})[0]
        return _fit_decay_ms(np.abs(_analytic(a)), 3.0, 25.0)

    assert decay("tight") < decay("rim") < decay("long")
    a = render_rim(load_preset("clave", "rim"))[0]
    f, sp = _spectrum(a, 0, 30)
    assert abs(_peak(a, 2000, 3000)[0] / 2500 - 1) < 0.01
    assert sp[(f > 1500) & (f < 3400)].max() == sp.max()
    hi = sp[(f > 3200) & (f < 3900)].max()  # where an upper partial would be, f2_ratio 3.66 aside
    assert hi < 0.2 * sp.max()
    assert _peak(render_rim(load_preset("high", "rim"))[0], 600, 1500)[0] > 800


# --- golden hashes (Linux x86_64, NumPy 2.5.3) --------------------------------------------------

GOLDEN_VERSION = "0.1.0"
GOLDEN: dict = {
    "preset-rim": (lambda: load_preset("rim", "rim"),
                   "519531b8c652931a72f4f85f46c37dd3b4194adb7b6cbda910706e80aa4bdba4"),
    "preset-tight": (lambda: load_preset("tight", "rim"),
                     "51c0e498a4166cb5566df845dcecc936d0c23db375e7d3f8ff661bc8f35c29dd"),
    "preset-long": (lambda: load_preset("long", "rim"),
                    "24d1ad9915ef80231c5428a0fa587dd492a602b6ed541d77cd5a20ab323634d5"),
    "preset-high": (lambda: load_preset("high", "rim"),
                    "ba8bb8926e6384d65f0ac656b41d9c48b1a4e23a15ab188ce9b5ea4cafcf0122"),
    "preset-clave": (lambda: load_preset("clave", "rim"),
                     "aad895b1c091526c1ac1738d0c1ed48bd3cd7e972340bf4516d0c5478b10bdc7"),
    "all-fields-44k1-16bit": (
        lambda: {"schema_version": "0.1", "seed": 9, "f1_hz": 620, "f2_ratio": 3.2,
                 "level2": 0.45, "decay1_ms": 55, "decay2_ms": 22, "hp_hz": 400,
                 "click_level": 0.5, "click_ms": 1.8, "drive": 0.5, "polarity": -1,
                 "offset_ms": 3, "length_ms": 150, "sample_rate": 44100, "bit_depth": 16,
                 "peak_ceiling_dbfs": -1.5},
        "f18373fa2cf6bf13a1bbcc49812976264be26949cca4312c9aa2ea10fd3ea90f"),
}


def _wav(params: dict) -> bytes:
    a, r = render_rim(params)
    return encode_wav(a, r["sample_rate"], r["bit_depth"])


def test_golden_hashes_belong_to_the_version() -> None:
    assert R.RIM_VERSION == GOLDEN_VERSION, (
        "rim engine bytes changed: bump RIM_VERSION (D-013) and update GOLDEN in this file"
    )
    assert R.RIM_NAME == "abeltongod-audio-engine-rim"


@pytest.mark.parametrize("name", GOLDEN)
def test_golden_sha256(name: str) -> None:
    params, expected = GOLDEN[name]
    assert hashlib.sha256(_wav(params())).hexdigest() == expected


def test_other_categories_still_load() -> None:
    assert "centre" in preset_names("kick") and "short" in preset_names("clap")
    assert "closed-std" in preset_names("hat")


# --- variants ----------------------------------------------------------------------------------


@pytest.mark.parametrize("p", RANDOM[:10], ids=[f"r{i}" for i in range(10)])
def test_variants_stay_in_the_contract_and_are_reproducible(p: dict) -> None:
    vs = rim_variants.make_variants(p, 4)
    assert vs == rim_variants.make_variants(p, 4)
    assert vs[0] == {k: v for k, v in resolve_rim_params(p).items() if k != "variants"}
    assert len({v["seed"] for v in vs}) == 4
    for v in vs:
        assert resolve_rim_params(v) == {**v, "variants": 1}
        assert v["hp_hz"] < 0.8 * v["f1_hz"]
        assert (v["level2"] == 0) == (vs[0]["level2"] == 0)


def test_variants_edge_hp_next_to_f1_and_spread_box() -> None:
    edge = {**BASE, "f1_hz": 1000, "hp_hz": 799.9}
    for v in rim_variants.make_variants(edge, 8):
        assert v["hp_hz"] < 0.8 * v["f1_hz"] and v["f1_hz"] >= 1000
    vs = rim_variants.make_variants({**BASE, "decay1_ms": 60}, 8)
    decays = [v["decay1_ms"] for v in vs]
    assert 54 <= min(decays) and max(decays) <= 66 and len(set(decays)) > 1
    clave = rim_variants.make_variants(load_preset("clave", "rim"), 8)
    assert all(v["level2"] == 0 for v in clave)
    assert len({v["f1_hz"] for v in clave}) > 1
