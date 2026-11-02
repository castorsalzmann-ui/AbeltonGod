"""Snare voice (#308): contract, determinism, parameter effects, measured targets, golden hashes.

Measurement method (independent of the engine code, numpy only): band-limiting is an ideal FFT
brick-wall filter, instantaneous frequency and amplitude come from an FFT analytic signal
(Hilbert), decay is a straight-line fit of the dB envelope, spectral levels are Welch averages.
Expected values are written here from the contract text. The engine's own phase integral,
envelope helper and filters are never used as the reference. Each important check is a
``_check_*`` function that is run on the engine and again on a deliberately broken engine
(the "mutant" tests), so the check is shown to be able to fail.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import time

import numpy as np
import pytest

import audio_engine.snare as S
from audio_engine import analysis, snare_variants
from audio_engine.io import encode_wav, wav_samples
from audio_engine.presets import load_preset, preset_names
from audio_engine.snare import SnareParamsError, render_snare, resolve_snare_params

SCHEMA = json.loads(S.SNARE_SCHEMA_FILE.read_text(encoding="utf-8"))
PROPS = SCHEMA["properties"]
NUMERIC = [k for k, v in PROPS.items() if v.get("type") in ("number", "integer")]
BASE = {"schema_version": "0.1", "seed": 5}
SR = 48000
NOISE_ONLY = {"body_level": 0.0, "noise_band_mix": 0.0, "noise_attack_ms": 0.1}
BODY_ONLY = {"body_level": 1.0}


def _draw(rng: np.random.Generator) -> dict:
    """One random parameter set over the whole contract range (endpoints now and then)."""
    p: dict = {"schema_version": "0.1", "seed": int(rng.integers(0, 2**32))}
    for name, prop in PROPS.items():
        if name in ("schema_version", "seed", "preset", "bpm", "variants", "noise_lp_hz"):
            continue
        if "enum" in prop:
            p[name] = prop["enum"][int(rng.integers(len(prop["enum"])))]
        else:
            pick = rng.random()
            p[name] = float(
                prop["minimum"] if pick < 0.08 else prop["maximum"] if pick < 0.16
                else rng.uniform(prop["minimum"], prop["maximum"])
            )
    lo = max(PROPS["noise_lp_hz"]["minimum"], 1.2 * p["noise_hp_hz"] + 1.0)
    p["noise_lp_hz"] = float(rng.uniform(lo, PROPS["noise_lp_hz"]["maximum"]))
    return p


RANDOM = [_draw(np.random.default_rng(800 + i)) for i in range(16)]


def _r(**kw) -> np.ndarray:
    return render_snare({**BASE, **kw})[0]


# --- independent measurement helpers (numpy only) ---------------------------------------------


def _bandpass(x: np.ndarray, lo: float, hi: float, sr: int = SR) -> np.ndarray:
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1.0 / sr)
    spec[(f < lo) | (f > hi)] = 0.0
    return np.fft.irfft(spec, len(x))


def _analytic(x: np.ndarray) -> np.ndarray:
    n = len(x)
    spec = np.fft.fft(x)
    h = np.zeros(n)
    h[0] = 1.0
    if n % 2 == 0:
        h[n // 2] = 1.0
        h[1:n // 2] = 2.0
    else:
        h[1:(n + 1) // 2] = 2.0
    return np.fft.ifft(spec * h)


def _inst_freq(x: np.ndarray, sr: int = SR) -> np.ndarray:
    ph = np.unwrap(np.angle(_analytic(x)))
    return np.diff(ph) * sr / (2.0 * math.pi)


def _fit_decay_ms(env: np.ndarray, sr: int, start_ms: float, top_db: float = 3.0,
                  bottom_db: float = 25.0) -> float:
    """60 dB decay time from a straight-line fit of the dB envelope between ``top_db`` and
    ``bottom_db`` below the value at ``start_ms`` (the attack is excluded by ``start_ms``)."""
    db = 20.0 * np.log10(np.maximum(env, 1e-12))
    i0 = int(start_ms * sr / 1000)
    ref = db[i0]
    seg = db[i0:]
    idx = np.nonzero((seg <= ref - top_db) & (seg >= ref - bottom_db))[0]
    idx = idx[: np.argmax(np.diff(idx) > 1) + 1] if np.any(np.diff(idx) > 1) else idx
    slope = np.polyfit(idx / sr, seg[idx], 1)[0]  # dB per second, negative
    return -60.0 / slope * 1000.0


def _rms_env(x: np.ndarray, sr: int, block_ms: float = 5.0) -> np.ndarray:
    b = int(block_ms * sr / 1000)
    n = len(x) // b
    e = np.sqrt(np.mean(x[: n * b].reshape(n, b) ** 2, axis=1))
    return np.repeat(e, b)


def _welch_db(x: np.ndarray, f0: float, half_width: float = 80.0, seg: int = 1024) -> float:
    w = np.hanning(seg)
    acc = np.zeros(seg // 2 + 1)
    for s in range(0, len(x) - seg + 1, seg // 2):
        acc += np.abs(np.fft.rfft(x[s:s + seg] * w)) ** 2
    f = np.fft.rfftfreq(seg, 1.0 / SR)
    return 10.0 * math.log10(float(np.mean(acc[np.abs(f - f0) <= half_width])))


def _peak_hz(x: np.ndarray, lo: float, hi: float) -> float:
    """Spectral peak in [lo, hi] with parabolic interpolation (Hann, zero-padded)."""
    n = 1 << 17
    sp = np.abs(np.fft.rfft(x * np.hanning(len(x)), n))
    f = np.fft.rfftfreq(n, 1.0 / SR)
    i = int(np.argmax(np.where((f >= lo) & (f <= hi), sp, 0.0)))
    a, b, c = np.log(sp[i - 1:i + 2] + 1e-30)
    return float(f[i] + 0.5 * (a - c) / (a - 2 * b + c) * (f[1] - f[0]))


# --- contract ---------------------------------------------------------------------------------


def test_defaults_are_filled_and_resolving_twice_changes_nothing() -> None:
    r = resolve_snare_params(BASE)
    for name, prop in PROPS.items():
        if "default" in prop:
            assert r[name] == prop["default"]
    assert r["length_ms"] == 400
    assert resolve_snare_params(r) == r
    assert "variants" in r and "variants" not in render_snare(BASE)[1]


@pytest.mark.parametrize("field", NUMERIC)
def test_every_numeric_bound_is_enforced_not_clamped(field: str) -> None:
    prop = PROPS[field]
    for edge in (prop["minimum"], prop["maximum"]):
        extra = {}
        if field == "noise_lp_hz" and edge == prop["minimum"]:
            extra = {"noise_hp_hz": 500}
        if field == "noise_hp_hz" and edge == prop["maximum"]:
            extra = {"noise_lp_hz": 16000}
        assert resolve_snare_params({**BASE, **extra, field: edge})[field] == edge
    for bad in (prop["minimum"] - 1e-6, prop["maximum"] + 1e-6):
        if prop["type"] == "integer":
            bad = int(prop["minimum"] - 1) if bad < prop["minimum"] else int(prop["maximum"] + 1)
        with pytest.raises(SnareParamsError, match=field):
            resolve_snare_params({**BASE, field: bad})


@pytest.mark.parametrize(
    "bad",
    [{"nope": 1}, {"bit_depth": 20}, {"polarity": 0}, {"body_level": float("nan")},
     {"seed": -1}, {"drive": True}, {"body_hz": "190"}, {"variants": 2.5}, {"snappy": 0.5},
     {"gate_ms": 50}, {"body_shape": 0}],
)
def test_bad_values_and_fields_outside_v01_are_rejected(bad: dict) -> None:
    with pytest.raises(SnareParamsError):
        resolve_snare_params({**BASE, **bad})
    with pytest.raises(SnareParamsError):
        resolve_snare_params({"seed": 1})  # schema_version missing


@pytest.mark.parametrize("hp", [500.0, 2000.0, 5000.0, 6000.0])
def test_cross_field_rule_lp_greater_than_1_2_hp(hp: float) -> None:
    edge = 1.2 * hp
    for lp in (edge, edge - 0.1, 3000.0 if edge > 3000 else edge - 1):
        if lp <= edge and 3000 <= lp:
            with pytest.raises(SnareParamsError, match="noise_lp_hz: must be greater"):
                resolve_snare_params({**BASE, "noise_hp_hz": hp, "noise_lp_hz": lp})
    ok = max(3000.0, edge + 0.1)
    assert resolve_snare_params({**BASE, "noise_hp_hz": hp, "noise_lp_hz": ok})
    # every omitted-partner combination stays valid (contract $comment 1)
    assert resolve_snare_params({**BASE, "noise_hp_hz": 6000})
    assert resolve_snare_params({**BASE, "noise_lp_hz": 3000})


def test_whole_number_floats_become_ints() -> None:
    r = resolve_snare_params({**BASE, "seed": 7.0, "polarity": -1.0, "sample_rate": 44100.0})
    assert (r["seed"], r["polarity"], r["sample_rate"]) == (7, -1, 44100)
    assert all(type(r[k]) is int for k in ("seed", "polarity", "sample_rate"))


# --- determinism and wrong-audio failures over the whole range ---------------------------------


@pytest.mark.parametrize("p", RANDOM, ids=[f"r{i}" for i in range(len(RANDOM))])
def test_random_full_range_invariants(p: dict) -> None:
    a, r = render_snare(p)
    again, _ = render_snare(p)
    assert a.tobytes() == again.tobytes()
    if r["body_level"] < 1.0:
        assert render_snare({**p, "seed": (p["seed"] + 1) % 2**32})[0].tobytes() != a.tobytes()
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
    assert resolve_snare_params(r) == {**r, "variants": 1}


def test_worst_case_render_time() -> None:
    p = {**BASE, "length_ms": 1500, "noise_decay_ms": 800, "body_decay_ms": 300, "drive": 1,
         "tone_peak_db": 6, "noise_band_mix": 0.5, "pitch_drop": 2.0, "sample_rate": 44100}
    start = time.perf_counter()
    render_snare(p)
    assert time.perf_counter() - start <= 20.0


def test_file_fields_do_what_they_say() -> None:
    a, r = render_snare(BASE)
    assert len(a) == round(0.4 * SR)
    off = _r(offset_ms=12)
    assert np.all(off[:576] == 0.0) and np.any(off[576:] != 0.0) and len(off) == len(a)
    assert np.array_equal(_r(polarity=-1), -a)
    cut = _r(length_ms=100)
    assert len(cut) == 4800 and cut[-1] == 0.0 and np.any(cut[:4500] != 0.0)
    w16 = encode_wav(_r(sample_rate=44100, bit_depth=16), 44100, 16)
    assert w16[24:28] == (44100).to_bytes(4, "little")


# --- measured targets: body --------------------------------------------------------------------

BODY_CASES = [  # (body_hz, mode_ratio, seed)
    (120.0, 1.5, 1), (150.0, 1.85, 2), (190.0, 1.85, 3), (260.0, 2.0, 4), (330.0, 2.4, 5),
    (400.0, 2.4, 6), (205.0, 1.7, 7), (310.0, 1.6, 8),
]


def _check_body_pitch_and_ratio() -> None:
    """T1/T3: with the drop finished (tau 8 ms, window 60-160 ms = 7.5 tau and later) the two
    spectral peaks are at body_hz and body_hz * mode_ratio, within 1.5 %. Also with noise on
    (body_level 0.6): the noise skirt must not move the peaks (P1)."""
    for hz, ratio, seed in BODY_CASES:
        for level in (1.0, 0.6):
            a = _r(body_hz=hz, mode_ratio=ratio, seed=seed, body_level=level, pitch_drop_ms=8,
                   pitch_drop=1.8, body_decay_ms=250, body2_decay_ratio=1.0, length_ms=300,
                   noise_hp_hz=2500, noise_decay_ms=60)
            w = a[int(0.060 * SR):int(0.160 * SR)]
            low = _peak_hz(w, 0.8 * hz, 1.2 * hz)
            high = _peak_hz(w, 0.85 * hz * ratio, 1.15 * hz * ratio)
            assert abs(low / hz - 1) < 0.015, (hz, ratio, level, low)
            assert abs(high / low / ratio - 1) < 0.015, (hz, ratio, level, high / low)


def test_body_hz_and_mode_ratio_are_where_the_contract_says() -> None:
    _check_body_pitch_and_ratio()


def _lower_partial_track(hz: float, drop: float, drop_ms: float, seed: int = 1) -> tuple:
    """Isolate the lower partial (mode_ratio 2.4, band 0.8 hz .. 1.1 hz drop) and return its
    amplitude envelope and instantaneous frequency (analytic signal)."""
    a = _r(**BODY_ONLY, body_hz=hz, mode_ratio=2.4, pitch_drop=drop, pitch_drop_ms=drop_ms,
           body_decay_ms=300, body2_decay_ratio=1.0, length_ms=500, seed=seed)
    z = _bandpass(a, 0.8 * hz, 1.1 * hz * drop)
    return np.abs(_analytic(z)), _inst_freq(z)


def _check_pitch_drop() -> None:
    """T2: f(t) / body_hz = 1 + (drop - 1) * exp(-t / pitch_drop_ms) (written here), measured
    from the analytic phase at 8, 16 and 30 ms, within 4 %."""
    for hz, drop, tau in [(190, 1.4, 25), (150, 2.0, 40), (300, 1.2, 12), (250, 1.7, 60),
                          (400, 2.0, 5), (120, 1.0, 25)]:
        _, f = _lower_partial_track(hz, drop, tau)
        for t_ms in (8, 16, 30):
            want = 1.0 + (drop - 1.0) * math.exp(-t_ms / tau)
            got = float(np.mean(f[int((t_ms - 1) * SR / 1000):int((t_ms + 1) * SR / 1000)])) / hz
            assert abs(got / want - 1) < 0.04, (hz, drop, tau, t_ms, got, want)


def test_pitch_drop_follows_the_exponential_curve() -> None:
    _check_pitch_drop()


def test_upper_partial_follows_the_drop_with_constant_ratio() -> None:
    """Contract: both partials share the curve, so the ratio is mode_ratio at every instant.
    Measured on the analytic signals of the two bands (they do not overlap at drop 1.4)."""
    hz, ratio = 200.0, 2.2
    a = _r(**BODY_ONLY, body_hz=hz, mode_ratio=ratio, pitch_drop=1.4, pitch_drop_ms=30,
           body_decay_ms=300, body2_decay_ratio=1.0, length_ms=400)
    lo = _inst_freq(_bandpass(a, 0.8 * hz, 1.1 * hz * 1.4))
    hi = _inst_freq(_bandpass(a, 0.9 * hz * ratio, 1.1 * hz * ratio * 1.4))
    for t_ms in (12, 18, 30, 50, 100):  # +-3 ms windows: the analytic signal ripples at +-3 %
        s = slice(int((t_ms - 3) * SR / 1000), int((t_ms + 3) * SR / 1000))
        assert abs(np.mean(hi[s]) / np.mean(lo[s]) / ratio - 1) < 0.025, t_ms


def _check_body_decays() -> None:
    """Q6: lower partial 60 dB time = body_decay_ms (fit -3..-25 dB from 10 ms, within 10 %);
    the upper partial = body_decay_ms * body2_decay_ratio. Decays from 90 ms: below that the
    brick-wall band cuts the wide spectrum of a fast-decaying partial and the analytic envelope
    is biased (measured +35 % at 40 ms), so this check says nothing about shorter decays."""
    for hz, dec in [(200, 90), (200, 150), (400, 150), (200, 300), (120, 300)]:
        a = _r(**BODY_ONLY, body_hz=hz, mode_ratio=2.4, pitch_drop=1.3, pitch_drop_ms=20,
               body_decay_ms=dec, body2_decay_ratio=1.0, length_ms=800)
        env = np.abs(_analytic(_bandpass(a, 0.5 * hz, 1.8 * hz)))
        got = _fit_decay_ms(env, SR, 10.0)
        assert abs(got / dec - 1) < 0.10, (hz, dec, got)
    for dec, ratio in [(300, 0.3), (150, 0.7), (150, 1.0), (150, 1.2)]:
        a = _r(**BODY_ONLY, body_hz=200, mode_ratio=2.4, pitch_drop=1.0, body_decay_ms=dec,
               body2_decay_ratio=ratio, length_ms=800)
        env = np.abs(_analytic(_bandpass(a, 408, 552)))
        got = _fit_decay_ms(env, SR, 6.0)
        assert abs(got / (dec * ratio) - 1) < 0.10, (dec, ratio, got)


def test_body_decays_match_the_contract() -> None:
    _check_body_decays()


# --- measured targets: noise -------------------------------------------------------------------


def _check_noise_decay() -> None:
    """Q7: wide layer 60 dB time = noise_decay_ms; narrow layer = 0.4 * noise_decay_ms
    (the engine constant NARROW_DECAY_RATIO, stated in snare.py), 5 ms RMS blocks above the
    high-pass, within 10 %."""
    for dec, seed in [(80, 1), (180, 2), (350, 3), (600, 4)]:
        a = _r(**NOISE_ONLY, noise_decay_ms=dec, seed=seed, length_ms=1500, noise_hp_hz=2500)
        env = _rms_env(_bandpass(a, 2500, 20000), SR)
        assert abs(_fit_decay_ms(env, SR, 3.0, 3.0, 22.0) / dec - 1) < 0.10, (dec, seed)
    for dec in (200, 500):
        a = _r(**{**NOISE_ONLY, "noise_band_mix": 1.0}, noise_decay_ms=dec, length_ms=1500,
               noise_hp_hz=2500)
        env = _rms_env(_bandpass(a, 3750, 20000), SR)
        assert abs(_fit_decay_ms(env, SR, 3.0, 3.0, 22.0) / (0.4 * dec) - 1) < 0.10, dec


def test_noise_decays_match_the_contract() -> None:
    _check_noise_decay()


def _check_filter_corners() -> None:
    """Q5: the noise filters are -3 dB at their corner. Welch level at the corner against a
    reference on the plateau (4x above the high-pass, a quarter of the low-pass), noise only,
    mean of 8 seeds (one Welch estimate scatters +-1 dB: the exponential envelope leaves few
    independent segments). Expected -3.0 dB: mean of the three corners within +-0.6, each
    within +-1.4 (measured: hp -2.2 / -3.0 / -2.9, lp -2.7 / -3.4 / -2.8)."""
    kw = {**NOISE_ONLY, "noise_decay_ms": 800, "length_ms": 1500}
    hp_d, lp_d = [], []
    for hp in (600.0, 1200.0, 2500.0):
        hp_d.append(float(np.mean([
            _welch_db(x, hp, max(60.0, 0.06 * hp)) - _welch_db(x, 4 * hp, 0.24 * hp)
            for x in (_r(**kw, seed=s, noise_hp_hz=hp, noise_lp_hz=16000) for s in range(1, 9))
        ])))
    for lp in (6000.0, 9000.0, 12000.0):
        lp_d.append(float(np.mean([
            _welch_db(x, lp, 0.04 * lp) - _welch_db(x, lp / 4, 0.04 * lp)
            for x in (_r(**kw, seed=s, noise_hp_hz=500, noise_lp_hz=lp) for s in range(1, 9))
        ])))
    for d in (hp_d, lp_d):
        assert -3.6 <= float(np.mean(d)) <= -2.4, d
        assert all(-4.4 <= v <= -1.6 for v in d), d


def test_noise_filter_corners_are_minus_3_db() -> None:
    _check_filter_corners()


def test_noise_corners_move_brightness_monotonically() -> None:
    for seed in range(1, 5):
        hps = [_r(seed=seed, **NOISE_ONLY, noise_hp_hz=h) for h in (600, 1800, 3500, 6000)]
        c = [analysis.analyse_nonpitched(x, SR)["spectral_centroid_hz"] for x in hps]
        assert c == sorted(c), c
        lps = [_r(seed=seed, **NOISE_ONLY, noise_lp_hz=f) for f in (4000, 7000, 11000, 16000)]
        c = [analysis.analyse_nonpitched(x, SR)["spectral_centroid_hz"] for x in lps]
        assert c == sorted(c), c


def test_tone_peak_sign_rule_and_off_at_zero() -> None:
    for seed in range(1, 5):
        kw = {**NOISE_ONLY, "seed": seed, "noise_hp_hz": 600, "noise_lp_hz": 16000}
        flat = _r(**kw)
        up = _r(**kw, tone_peak_hz=7000, tone_peak_db=6)
        down = _r(**kw, tone_peak_hz=7000, tone_peak_db=-6)
        # Each layer is RMS-normalised after the filters, so compare the peak against a
        # reference frequency away from it (2000 Hz is 1.8 octaves off, about +-0.4 dB).
        def shape(x):
            return _welch_db(x, 7000, 300) - _welch_db(x, 2000, 300)

        assert 3.0 < shape(up) - shape(flat) < 8.0
        assert -8.0 < shape(down) - shape(flat) < -3.0
    assert np.array_equal(_r(tone_peak_hz=7000, tone_peak_db=0), _r())


def test_noise_attack_moves_the_first_milliseconds() -> None:
    for seed in (1, 2, 3):
        share = []
        for att in (0.1, 1.0, 4.0, 10.0):
            a = _r(seed=seed, **{**NOISE_ONLY, "noise_attack_ms": att}, noise_decay_ms=100)
            share.append(float(np.sum(a[:96] ** 2) / np.sum(a[:4800] ** 2)))
        assert share == sorted(share, reverse=True), share
        assert share[0] > 4 * share[-1]


def test_noise_band_mix_adds_the_narrow_faster_band() -> None:
    """The narrow layer sits above 1.5 * noise_hp_hz and falls faster: the high band decays
    faster at mix 1 than at mix 0, and a mix of 0 / 1 uses only one stream each."""
    kw = {**NOISE_ONLY, "noise_hp_hz": 2000, "noise_decay_ms": 400, "length_ms": 800}
    t = []
    for mix in (0.0, 1.0):
        a = _r(**{**kw, "noise_band_mix": mix})
        t.append(_fit_decay_ms(_rms_env(_bandpass(a, 3500, 20000), SR), SR, 3.0, 3.0, 22.0))
    assert t[1] < 0.6 * t[0], t
    assert not np.array_equal(_r(**{**kw, "noise_band_mix": 0.0}),
                              _r(**{**kw, "noise_band_mix": 0.3}))


# --- body_level, seed, drive ---------------------------------------------------------------------

SAME_ENV = {"body_decay_ms": 100, "noise_decay_ms": 100, "body2_decay_ratio": 1.0,
            "noise_band_mix": 0.0, "noise_attack_ms": 0.1, "pitch_drop": 1.0, "length_ms": 300}


def _check_body_level_is_passband_share() -> None:
    """With equal envelopes the body is a known fraction of the mixed power, so the correlation
    of the mix with the body-only render is sqrt(body_level) (+-0.04), however much the noise
    filter removed (the noise here is cut hard by a 6000 Hz high-pass)."""
    for seed in (1, 2, 3):
        pure = _r(seed=seed, **SAME_ENV, body_level=1.0)
        for lv in (0.2, 0.5, 0.8):
            for hp in (600.0, 6000.0):
                mix = _r(seed=seed, **SAME_ENV, body_level=lv, noise_hp_hz=hp)
                c = float(np.corrcoef(mix, pure)[0, 1])
                assert abs(c - math.sqrt(lv)) <= 0.04, (seed, lv, hp, c)


def test_body_level_is_the_passband_power_share() -> None:
    _check_body_level_is_passband_share()


def _check_seed_acts_only_on_noise() -> None:
    """T8 with its positive control: no seed effect at body_level 1; an effect with noise."""
    assert np.array_equal(_r(seed=1, body_level=1.0), _r(seed=2, body_level=1.0))
    assert not np.array_equal(_r(seed=1, body_level=0.99), _r(seed=2, body_level=0.99))
    assert not np.array_equal(_r(seed=1, body_level=0.0), _r(seed=2, body_level=0.0))


def test_seed_changes_only_the_noise() -> None:
    _check_seed_acts_only_on_noise()


def test_the_two_noise_layers_use_independent_streams() -> None:
    """Changing noise_band_mix from 0 to a small value adds a layer without changing the wide
    layer's noise: the wide-layer-only render correlates with the 10 % render above 0.95."""
    a = _r(**NOISE_ONLY, noise_hp_hz=1800)
    b = _r(**{**NOISE_ONLY, "noise_band_mix": 0.1}, noise_hp_hz=1800)
    assert float(np.corrcoef(a, b)[0, 1]) > 0.95
    narrow = _r(**{**NOISE_ONLY, "noise_band_mix": 1.0}, noise_hp_hz=1800)
    assert float(np.corrcoef(b, narrow)[0, 1]) < 0.5


def test_drive_changes_the_signal_and_lowers_the_crest_factor() -> None:
    """drive acts after scaling to peak 1 (the kick's saturation stage): more drive, lower
    peak-to-RMS, monotone over 4 seeds. Aliasing of that stage is tested with the kick."""
    for seed in range(1, 5):
        crest = []
        for d in (0.0, 0.3, 0.6, 1.0):
            a = _r(seed=seed, drive=d)
            crest.append(float(np.max(np.abs(a)) / np.sqrt(np.mean(a**2))))
        assert crest == sorted(crest, reverse=True) and crest[0] > crest[-1] + 0.3, crest


# --- fault injection: each key check turns red on a broken engine -------------------------------


def test_mutant_body_scaled_fails_the_level_share_check(monkeypatch) -> None:
    real = S._body
    monkeypatch.setattr(S, "_body", lambda p, t: 1.3 * real(p, t))
    with pytest.raises(AssertionError):
        _check_body_level_is_passband_share()


def test_mutant_body_pitch_5_percent_sharp_fails(monkeypatch) -> None:
    real = S.body_phase
    monkeypatch.setattr(S, "body_phase", lambda t, f, d, tau: real(t, f * 1.05, d, tau))
    with pytest.raises(AssertionError):
        _check_body_pitch_and_ratio()


def test_mutant_upper_partial_ratio_off_fails(monkeypatch) -> None:
    real, calls = S.body_phase, itertools.count()
    monkeypatch.setattr(
        S, "body_phase",
        lambda t, f, d, tau: real(t, f * (1.05 if next(calls) % 2 else 1.0), d, tau))
    with pytest.raises(AssertionError):
        _check_body_pitch_and_ratio()


def test_mutant_pitch_drop_ignored_fails(monkeypatch) -> None:
    real = S.body_phase
    monkeypatch.setattr(S, "body_phase", lambda t, f, d, tau: real(t, f, 1.0, tau))
    with pytest.raises(AssertionError):
        _check_pitch_drop()


def test_mutant_drop_time_constant_2_percent_off_is_visible(monkeypatch) -> None:
    """A 25 % slower drop (the check's resolution is a few percent at 8-30 ms) fails."""
    real = S.body_phase
    monkeypatch.setattr(S, "body_phase", lambda t, f, d, tau: real(t, f, d, tau * 1.25))
    with pytest.raises(AssertionError):
        _check_pitch_drop()


def test_mutant_slower_envelope_fails_the_decay_checks(monkeypatch) -> None:
    real = S._amp_envelope
    monkeypatch.setattr(S, "_amp_envelope", lambda t, a, d: real(t, a, d * 1.15))
    with pytest.raises(AssertionError):
        _check_body_decays()
    with pytest.raises(AssertionError):
        _check_noise_decay()


def test_mutant_narrow_decay_ratio_fails(monkeypatch) -> None:
    monkeypatch.setattr(S, "NARROW_DECAY_RATIO", 0.5)
    with pytest.raises(AssertionError):
        _check_noise_decay()


def test_mutant_highpass_corner_moved_fails(monkeypatch) -> None:
    real = S.rbj_highpass
    monkeypatch.setattr(S, "rbj_highpass", lambda x, sr, f0, *a: real(x, sr, f0 * 1.25, *a))
    with pytest.raises(AssertionError):
        _check_filter_corners()


def test_mutant_lowpass_corner_moved_fails(monkeypatch) -> None:
    real = S.rbj_lowpass
    monkeypatch.setattr(S, "rbj_lowpass", lambda x, sr, f0, *a: real(x, sr, f0 * 0.75, *a))
    with pytest.raises(AssertionError):
        _check_filter_corners()


def test_mutant_seed_ignored_fails_the_positive_control(monkeypatch) -> None:
    real = S.substreams
    monkeypatch.setattr(S, "substreams", lambda seed, count: real(0, count))
    with pytest.raises(AssertionError):
        _check_seed_acts_only_on_noise()


# --- presets -----------------------------------------------------------------------------------

PRESETS = ["bright", "default", "long", "tight", "tonal"]


def test_the_five_presets_exist_and_validate() -> None:
    assert preset_names("snare") == PRESETS
    for name in PRESETS:
        p = load_preset(name, "snare")
        assert p["preset"] == name
        resolve_snare_params(p)


def test_preset_measurements_follow_their_fields() -> None:
    """Directions only (the note proposes no taste range): tail and brightness order. The tail
    is read in the band above 2.7 kHz: the sidecar ``t60_ms`` of a snare is floored by the
    mean-removal bump (see the PR), it is the same ~323 ms for 'tight' and 'default'."""
    renders = {n: [render_snare({**load_preset(n, "snare"), "seed": s})[0] for s in range(1, 5)]
               for n in PRESETS}

    def tail(name):
        return float(np.mean([_fit_decay_ms(_rms_env(_bandpass(x, 2700, 20000), SR), SR, 3.0,
                                            3.0, 20.0) for x in renders[name]]))

    def feat(name, key):
        return float(np.mean([analysis.analyse_nonpitched(x, SR)[key] for x in renders[name]]))

    assert tail("tight") < tail("default") < tail("long")
    assert feat("bright", "spectral_centroid_hz") > feat("default", "spectral_centroid_hz")
    assert feat("tonal", "hf_share_8k") < feat("default", "hf_share_8k")


# --- golden hashes (Linux x86_64, NumPy 2.5.3) --------------------------------------------------

GOLDEN_VERSION = "0.1.0"
GOLDEN: dict = {
    "preset-default": (lambda: load_preset("default", "snare"),
                       "e76a99e642019ba1c9a47d0c7a560a1716ebe8a5120b7a9c59e2ac8fdb09e0cb"),
    "preset-tight": (lambda: load_preset("tight", "snare"),
                     "0935e48ef0d5616bdd89215b7c6f3e403442dbe663a43ee2c48a7c6f2591126a"),
    "preset-long": (lambda: load_preset("long", "snare"),
                    "a39c230b9004e8cb298152c5f48fcc0cf66d554bbad6a51b8db6ec708fa1215a"),
    "preset-tonal": (lambda: load_preset("tonal", "snare"),
                     "94effc41d819b0f0bed3eca1b58872b4048871db0d2417477adda597a9a90010"),
    "preset-bright": (lambda: load_preset("bright", "snare"),
                      "0c4ad448be3ff5b9591e7e7f44d7f3a9230cadd56051a0652b443079deaabe9a"),
    "all-fields-44k1-16bit": (
        lambda: {"schema_version": "0.1", "seed": 9, "body_hz": 240, "mode_ratio": 2.1,
                 "pitch_drop": 1.7, "pitch_drop_ms": 14, "body_decay_ms": 120,
                 "body2_decay_ratio": 0.5, "body_level": 0.45, "noise_decay_ms": 250,
                 "noise_band_mix": 0.7, "noise_hp_hz": 2400, "noise_lp_hz": 11000,
                 "noise_attack_ms": 2.5, "tone_peak_hz": 4200, "tone_peak_db": 4, "drive": 0.5,
                 "polarity": -1, "offset_ms": 3, "length_ms": 350, "sample_rate": 44100,
                 "bit_depth": 16},
        "4cbaaacbe66e1b072a6dee215d9a67a82cd56b79878fe976a8f6b2b4e6d1382b"),
}


def _wav(params: dict) -> bytes:
    a, r = render_snare(params)
    return encode_wav(a, r["sample_rate"], r["bit_depth"])


def test_golden_hashes_belong_to_the_version() -> None:
    assert S.SNARE_VERSION == GOLDEN_VERSION, (
        "snare engine bytes changed: bump SNARE_VERSION (D-013) and update GOLDEN in this file"
    )
    assert S.SNARE_NAME == "abeltongod-audio-engine-snare"


@pytest.mark.parametrize("name", GOLDEN)
def test_golden_sha256(name: str) -> None:
    params, expected = GOLDEN[name]
    assert hashlib.sha256(_wav(params())).hexdigest() == expected


def test_kick_clap_and_hat_presets_still_load() -> None:
    assert "centre" in preset_names("kick") and "short" in preset_names("clap")
    assert "closed-std" in preset_names("hat")


# --- variants ----------------------------------------------------------------------------------


@pytest.mark.parametrize("p", RANDOM[:8], ids=[f"r{i}" for i in range(8)])
def test_variants_stay_in_the_contract_and_are_reproducible(p: dict) -> None:
    vs = snare_variants.make_variants(p, 4)
    assert vs == snare_variants.make_variants(p, 4)
    assert vs[0] == {k: v for k, v in resolve_snare_params(p).items() if k != "variants"}
    assert len({v["seed"] for v in vs}) == 4
    for v in vs:
        assert resolve_snare_params(v) == {**v, "variants": 1}
        assert v["noise_lp_hz"] > 1.2 * v["noise_hp_hz"]


def test_variants_edge_hp_next_to_lp_and_spread_box() -> None:
    edge = {**BASE, "noise_hp_hz": 5990, "noise_lp_hz": 7200.5}
    for v in snare_variants.make_variants(edge, 8):
        assert v["noise_lp_hz"] > 1.2 * v["noise_hp_hz"]
    vs = snare_variants.make_variants({**BASE, "noise_decay_ms": 300}, 8)
    decays = [v["noise_decay_ms"] for v in vs]
    assert 270 <= min(decays) and max(decays) <= 330
    assert len({v["noise_decay_ms"] for v in vs}) > 1


def test_engine_rejects_lp_not_above_1_2_hp_with_a_named_error() -> None:
    for hp, lp in ((5000, 6000), (5000, 5999.9), (6000, 3000), (2500, 3000)):
        with pytest.raises(SnareParamsError, match=r"noise_lp_hz: must be greater than 1\.2"):
            render_snare({**BASE, "noise_hp_hz": hp, "noise_lp_hz": lp})
    render_snare({**BASE, "noise_hp_hz": 2500, "noise_lp_hz": 3000.1, "length_ms": 100})
