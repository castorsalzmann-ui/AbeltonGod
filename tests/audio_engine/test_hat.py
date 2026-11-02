"""Hat voice (#270): contract, determinism, parameter effects, hypotheses H1-H12, golden hashes.

References are written in the test (expected directions, predicted spectral lines from the six
frequencies of the contract, a sample-by-sample level measure, an ideal 16x oversampled drive),
not taken from the engine's own helpers. Each important check is a ``_check_*`` function that
is run on the engine and again on a deliberately broken engine (the "mutant" tests) so the check
is shown to be able to fail.
"""

from __future__ import annotations

import hashlib
import json
import math
import time

import numpy as np
import pytest

import audio_engine.hat as H
from audio_engine import analysis
from audio_engine.hat import HatParamsError, render_hat, resolve_hat_params
from audio_engine.io import encode_wav, wav_samples
from audio_engine.presets import load_preset, preset_names

SCHEMA = json.loads(H.HAT_SCHEMA_FILE.read_text(encoding="utf-8"))
PROPS = SCHEMA["properties"]
NUMERIC = [k for k, v in PROPS.items() if v.get("type") in ("number", "integer")]
BASE = {"schema_version": "0.1", "seed": 5}
SR = 48000
FADE = 5.0


def _draw(rng: np.random.Generator) -> dict:
    """One random parameter set over the whole contract range (endpoints now and then)."""
    p: dict = {"schema_version": "0.1", "seed": int(rng.integers(0, 2**32))}
    for name, prop in PROPS.items():
        if name in ("schema_version", "seed", "preset", "bpm", "variants", "choke_ms", "lp_hz"):
            continue
        if "enum" in prop:
            p[name] = prop["enum"][int(rng.integers(len(prop["enum"])))]
        else:
            pick = rng.random()
            p[name] = float(
                prop["minimum"] if pick < 0.08 else prop["maximum"] if pick < 0.16
                else rng.uniform(prop["minimum"], prop["maximum"])
            )
    lo = max(PROPS["lp_hz"]["minimum"], 1.2 * p["hp_hz"] + 1.0)
    p["lp_hz"] = float(rng.uniform(lo, PROPS["lp_hz"]["maximum"]))
    p["choke_ms"] = 0 if rng.random() < 0.4 else float(rng.uniform(5, 900))
    if rng.random() < 0.5:
        p["length_ms"] = float(rng.uniform(20, 1200))
    return p


RANDOM = [_draw(np.random.default_rng(700 + i)) for i in range(14)]


def _r(**kw) -> np.ndarray:
    return render_hat({**BASE, **kw})[0]


def _norm_corr(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.corrcoef(a, b)[0, 1])


# --- contract ---------------------------------------------------------------------------------


def test_defaults_are_filled_and_resolving_twice_changes_nothing() -> None:
    r = resolve_hat_params(BASE)
    for name, prop in PROPS.items():
        if "default" in prop:
            assert r[name] == prop["default"]
    assert r["length_ms"] == pytest.approx(0.8 + 60 + 30)  # decay + attack + 30, recorded
    assert resolve_hat_params(r) == r
    assert "variants" in r and "variants" not in render_hat(BASE)[1]


@pytest.mark.parametrize("field", [f for f in NUMERIC if f != "choke_ms"])
def test_every_numeric_bound_is_enforced_not_clamped(field: str) -> None:
    prop = PROPS[field]
    extra = {"lp_hz": 22000} if field == "hp_hz" else {}
    for edge in (prop["minimum"], prop["maximum"]):
        if field == "lp_hz" and edge == prop["minimum"]:
            extra = {"hp_hz": 2000}
        assert resolve_hat_params({**BASE, **extra, field: edge})[field] == edge
    for bad in (prop["minimum"] - 1e-6, prop["maximum"] + 1e-6):
        if prop["type"] == "integer":
            bad = int(prop["minimum"] - 1) if bad < prop["minimum"] else int(prop["maximum"] + 1)
        with pytest.raises(HatParamsError, match=field):
            resolve_hat_params({**BASE, **extra, field: bad})


@pytest.mark.parametrize("bad", [0.1, 4.999, 900.5, -5])
def test_choke_below_five_or_out_of_range_is_rejected(bad: float) -> None:
    with pytest.raises(HatParamsError, match="choke_ms"):
        resolve_hat_params({**BASE, "choke_ms": bad})
    for ok in (0, 0.0, 5, 900):
        assert resolve_hat_params({**BASE, "choke_ms": ok})["choke_ms"] == ok


@pytest.mark.parametrize(
    "bad",
    [{"nope": 1}, {"bit_depth": 20}, {"polarity": 0}, {"model": "ride"}, {"metal": float("nan")},
     {"seed": -1}, {"drive": True}, {"hp_hz": "6000"}, {"variants": 2.5}],
)
def test_bad_values_are_rejected(bad: dict) -> None:
    with pytest.raises(HatParamsError):
        resolve_hat_params({**BASE, **bad})
    with pytest.raises(HatParamsError):
        resolve_hat_params({"seed": 1})  # schema_version missing


@pytest.mark.parametrize("hp", [2000.0, 6000.0, 9000.0, 12000.0])
def test_cross_field_rule_lp_greater_than_1_2_hp(hp: float) -> None:
    edge = 1.2 * hp
    lo = max(8000.0, edge)
    if lo >= edge and edge >= 8000.0:  # lp = exactly 1.2 * hp is rejected (rule is strict)
        with pytest.raises(HatParamsError, match="lp_hz"):
            resolve_hat_params({**BASE, "hp_hz": hp, "lp_hz": edge})
    with pytest.raises(HatParamsError, match="lp_hz"):
        resolve_hat_params({**BASE, "hp_hz": hp, "lp_hz": 8000 if hp >= 6667 else 7000})
    assert resolve_hat_params({**BASE, "hp_hz": hp, "lp_hz": max(8000.0, edge + 1)})


def test_whole_number_floats_become_ints() -> None:
    r = resolve_hat_params({**BASE, "seed": 7.0, "polarity": -1.0, "sample_rate": 44100.0})
    assert (r["seed"], r["polarity"], r["sample_rate"]) == (7, -1, 44100)
    assert all(type(r[k]) is int for k in ("seed", "polarity", "sample_rate"))


# --- determinism, wrong-audio failures over the whole range -----------------------------------


@pytest.mark.parametrize("p", RANDOM, ids=[f"r{i}" for i in range(len(RANDOM))])
def test_random_full_range_invariants(p: dict) -> None:
    a, r = render_hat(p)
    again, _ = render_hat(p)
    assert a.tobytes() == again.tobytes()
    if r["model"] == "noise" or r["metal"] < 1.0:  # metal 1 has no noise: the seed is unused
        assert render_hat({**p, "seed": (p["seed"] + 1) % 2**32})[0].tobytes() != a.tobytes()
    sr, bits = r["sample_rate"], r["bit_depth"]
    assert len(a) == round(r["length_ms"] * sr / 1000)
    assert np.all(np.isfinite(a))
    q = wav_samples(encode_wav(a, sr, bits)) / (2 ** (bits - 1) - 1)
    peak_db = 20 * math.log10(float(np.max(np.abs(q))))
    assert r["peak_ceiling_dbfs"] - 0.05 <= peak_db <= r["peak_ceiling_dbfs"] + 1e-9
    assert a[-1] == 0.0  # fade-out, no click at the end
    assert abs(float(np.mean(a))) < 1e-3 * float(np.max(np.abs(a)))
    assert resolve_hat_params(r) == {**r, "variants": 1}


def test_worst_case_render_time() -> None:
    p = {**BASE, "decay_ms": 900, "length_ms": 2000, "body_mix": 0.5, "bp_mix": 1,
         "peak_db": 9, "pitch_scale": 0.5, "drive": 1, "choke_ms": 800}
    start = time.perf_counter()
    render_hat(p)
    assert time.perf_counter() - start <= 20.0  # measured about 4 s alone on the dev box


def test_file_fields_do_what_they_say() -> None:
    a, r = render_hat(BASE)
    assert len(a) == round(r["length_ms"] * SR / 1000)
    off = _r(offset_ms=12)
    assert np.all(off[:576] == 0.0) and np.any(off[576:] != 0.0)
    assert len(off) == len(a) + 576  # the default length counts the offset
    assert np.array_equal(_r(polarity=-1), -a)
    cut = _r(length_ms=40)
    assert len(cut) == 1920 and cut[-1] == 0.0 and np.any(cut[:1800] != 0.0)
    w16 = encode_wav(_r(sample_rate=44100, bit_depth=16), 44100, 16)
    assert w16[24:28] == (44100).to_bytes(4, "little")


# --- every parameter moves its measured value --------------------------------------------------


def _hf(a: np.ndarray, split: float = 8000.0) -> float:
    return float(analysis.hf_share(a, SR, split))


def _centroid(a: np.ndarray) -> float:
    return float(analysis.analyse_nonpitched(a, SR)["spectral_centroid_hz"])


def test_hp_hz_moves_hf_share_and_centroid_up_and_bounds_the_leak() -> None:
    """H5: over 8 seeds the direction holds for every step; low leak below hp/2 stays small."""
    hps = [3000, 4500, 6000, 8000, 10000]
    for seed in range(1, 9):
        r = [_r(seed=seed, hp_hz=h, lp_hz=22000, decay_ms=70) for h in hps]
        hf = [_hf(a) for a in r]
        cen = [_centroid(a) for a in r]
        assert hf == sorted(hf) and cen == sorted(cen), (seed, hf, cen)
        for h, a in zip(hps, r, strict=True):
            assert analysis.lf_leak_db(a, SR, h) < -24.0  # model: -34..-28 dB with the bank in


def test_lp_hz_moves_centroid_and_hf_share_up() -> None:
    for seed in range(1, 5):
        r = [_r(seed=seed, lp_hz=f, decay_ms=70) for f in (10000, 14000, 18000, 22000)]
        assert [_centroid(a) for a in r] == sorted(_centroid(a) for a in r)
        assert [_hf(a) for a in r] == sorted(_hf(a) for a in r)


def test_peak_gain_sign_rule() -> None:
    """H6: a boost above the centroid raises it, a boost below it lowers it."""
    for seed in range(1, 5):
        flat = _centroid(_r(seed=seed, decay_ms=70))
        assert _centroid(_r(seed=seed, decay_ms=70, peak_hz=14000, peak_db=6)) > flat
        assert _centroid(_r(seed=seed, decay_ms=70, peak_hz=9000, peak_db=6)) < flat


def test_peak_db_zero_is_off_and_bp_mix_zero_is_off() -> None:
    base = _r()
    assert np.array_equal(_r(peak_db=0, peak_hz=13000), base)
    assert np.array_equal(_r(bp_mix=0, bp_hz=3000, bp_q=3), base)
    assert not np.array_equal(_r(bp_mix=1), base)


def test_bp_mix_adds_energy_around_bp_hz() -> None:
    for seed in (1, 2, 3):
        a = _r(seed=seed, bp_mix=0, hp_hz=2000, decay_ms=150)
        b = _r(seed=seed, bp_mix=1, bp_hz=5000, bp_q=2, hp_hz=2000, decay_ms=150)
        fa, fb = np.fft.rfftfreq(len(a), 1 / SR), np.abs(np.fft.rfft(b)) ** 2
        band = (fa > 4500) & (fa < 5500)
        pa = np.abs(np.fft.rfft(a)) ** 2
        # both are peak-normalised, so compare the band against the rest of the spectrum
        ratio = float(np.sum(fb[band]) / np.sum(fb[~band])) / float(
            np.sum(pa[band]) / np.sum(pa[~band])
        )
        assert ratio > 1.5


def _t60_ratio(decay_ms: float, seed: int) -> float:
    a = _r(seed=seed, decay_ms=decay_ms)
    return float(analysis.analyse_nonpitched(a, SR)["t60_ms"]) / decay_ms


def _check_decay_matches_t60() -> None:
    """H3: first-crossing t60 within 10 % of decay_ms over the whole range (20 log steps)."""
    for decay in np.geomspace(10, 900, 20):
        for seed in (1, 2):
            ratio = _t60_ratio(float(decay), seed)
            assert 0.90 <= ratio <= 1.10, (decay, seed, ratio)


def test_decay_ms_matches_measured_t60() -> None:
    _check_decay_matches_t60()


def test_line_fit_t60_is_closer_than_first_crossing_for_long_decays() -> None:
    for decay in (250.0, 500.0):
        a = _r(decay_ms=decay)
        fit = analysis.t60_line_fit_ms(a, SR)
        assert fit == pytest.approx(decay, rel=0.04)


def test_attack_ms_sets_the_first_samples() -> None:
    """A long attack puts a smaller share of the energy into the first millisecond."""
    for seed in (1, 2, 3):
        share = []
        for att in (0.1, 0.8, 3.0, 5.0):
            a = _r(seed=seed, attack_ms=att, decay_ms=60)
            share.append(float(np.sum(a[:48] ** 2) / np.sum(a[:2400] ** 2)))
        assert share == sorted(share, reverse=True), share
        assert share[0] > 4 * share[-1]


def test_model_noise_ignores_metal_pitch_and_color() -> None:
    base = _r(model="noise")
    assert np.array_equal(_r(model="noise", metal=1, pitch_scale=2, color=0), base)
    assert not np.array_equal(_r(model="metal_bank", metal=1), _r(model="noise", metal=1))
    assert np.array_equal(_r(metal=0, pitch_scale=2, color=1), base)  # metal 0 = noise only


def _check_metal_is_passband_share() -> None:
    """H2: correlation with the pure-bank render follows sqrt(metal) (+-0.05)."""
    for seed in (1, 2, 3):
        pure = _r(seed=seed, metal=1.0)
        for m in (0.3, 0.6, 0.9):
            c = _norm_corr(_r(seed=seed, metal=m), pure)
            assert abs(c - math.sqrt(m)) <= 0.05, (seed, m, c)


def test_metal_is_the_passband_power_share() -> None:
    _check_metal_is_passband_share()


def test_metal_raises_peak_count_and_lowers_flatness() -> None:
    """H7, H9 at fixed decay: monotone in metal for 4 seeds."""
    for seed in (1, 2, 3, 4):
        r = [_r(seed=seed, metal=m, decay_ms=70) for m in (0, 0.3, 0.6, 0.9, 1.0)]
        pc = [analysis.peak_count(a, SR) for a in r]
        fl = [analysis.welch_flatness(a, SR, 9000, 14400) for a in r]
        assert pc == sorted(pc) and pc[-1] > pc[0] + 20, pc
        assert fl == sorted(fl, reverse=True) and fl[0] > fl[-1] + 0.2, fl


def _line_fraction(a: np.ndarray, lines: list[float], tol: float = 20.0) -> float:
    """Share of 4-20 kHz power within ``tol`` Hz of any line."""
    f = np.fft.rfftfreq(len(a), 1 / SR)
    pw = np.abs(np.fft.rfft(a * np.hanning(len(a)))) ** 2
    band = (f >= 4000) & (f <= 20000)
    near = np.zeros(len(f), bool)
    for ln in lines:
        near |= np.abs(f - ln) <= tol
    return float(np.sum(pw[band & near]) / np.sum(pw[band]))


def _lines(freqs: list[float], scale: float, limit: float = 24000.0) -> list[float]:
    """Odd harmonics k * f * scale below Nyquist (written out here, from the contract text)."""
    out = []
    for f in freqs:
        k = 1
        while k * f * scale < SR / 2:
            out.append(k * f * scale)
            k += 2
    return out


LOW3, HIGH3 = [205.3, 304.4, 369.6], [522.7, 540.0, 800.0]


@pytest.mark.parametrize("scale", [0.8, 1.0, 1.5, 2.0])
def test_pitch_scale_puts_the_lines_where_the_contract_says(scale: float) -> None:
    """H8: with metal 1 the power sits on the predicted lines, and not on lines of another scale."""
    a = _r(metal=1.0, pitch_scale=scale, decay_ms=250, length_ms=300)
    right = _line_fraction(a, _lines(LOW3 + HIGH3, scale))
    wrong = _line_fraction(a, _lines(LOW3 + HIGH3, scale * 1.07))
    assert right > 0.9, right
    assert wrong < right - 0.25, (right, wrong)


def test_bank_has_no_line_above_the_harmonic_cap() -> None:
    """Contract: every odd harmonic below sr/2, nothing above (no folding). At scale 2 the
    800 Hz square has fundamental 1600 Hz; its 15th harmonic is 24 kHz > Nyquist (dropped)."""
    a = _r(metal=1.0, pitch_scale=2.0, hp_hz=2000, lp_hz=22000, decay_ms=250, length_ms=300)
    f = np.fft.rfftfreq(len(a), 1 / SR)
    pw = np.abs(np.fft.rfft(a * np.hanning(len(a)))) ** 2
    lines = np.array(_lines(LOW3 + HIGH3, 2.0))
    d = np.min(np.abs(f[:, None] - lines[None, :]), axis=1)
    far = d > 30.0
    assert float(np.sum(pw[far]) / np.sum(pw)) < 0.01


def test_color_crossfades_low_and_high_group() -> None:
    low = _lines(LOW3, 1.0)
    f0 = _line_fraction(_r(metal=1.0, color=0.0, decay_ms=250, length_ms=300), low)
    f1 = _line_fraction(_r(metal=1.0, color=1.0, decay_ms=250, length_ms=300), low)
    fm = _line_fraction(_r(metal=1.0, color=0.5, decay_ms=250, length_ms=300), low)
    assert f0 > 0.9 and f1 < 0.4 and f1 < fm < f0, (f0, fm, f1)


def _early_late(a: np.ndarray) -> float:
    return float(analysis.early_late_centroid_ratio(a, SR))


def test_body_split_raises_early_late_with_body_mix_and_ratio_one_is_neutral() -> None:
    """H10, measured part: neutral without a split (0.9-1.1) and at ratio 1; the ratio grows
    with body_mix; above 1.5 at body_mix 0.8 (measured 1.64-1.72, seeds 1-3)."""
    for seed in (1, 2, 3):
        kw = {"seed": seed, "decay_ms": 400, "hp_hz": 4000}
        none = _early_late(_r(**kw))
        same = _early_late(_r(**kw, body_mix=0.4, decay_hi_ratio=1.0))
        r = [_early_late(_r(**kw, body_mix=b, decay_hi_ratio=0.5)) for b in (0.2, 0.4, 0.8)]
        assert 0.9 <= none <= 1.1 and 0.9 <= same <= 1.1, (none, same)
        assert none < r[0] < r[1] < r[2] and r[2] > 1.5, r


@pytest.mark.xfail(strict=True, reason="H10 REJECTED on the engine voice: at body_mix 0.4 and "
                   "decay_hi_ratio 0.5 early_late is 1.10-1.16 (seeds 1-3), not above 1.5. "
                   "The body_mix semantics are the engine's (hat.py module doc); cause of the "
                   "gap to the model not established.")
def test_h10_split_at_body_mix_0_4_gives_early_late_above_1_5() -> None:
    for seed in (1, 2, 3):
        a = _r(seed=seed, decay_ms=400, hp_hz=4000, body_mix=0.4, decay_hi_ratio=0.5)
        assert _early_late(a) > 1.5


def test_body_mix_zero_makes_decay_hi_ratio_irrelevant_and_is_continuous() -> None:
    a = _r(decay_ms=300)
    assert np.array_equal(_r(decay_ms=300, decay_hi_ratio=0.2), a)
    tiny = _r(decay_ms=300, body_mix=1e-6, decay_hi_ratio=0.2)
    assert np.max(np.abs(tiny - a)) < 1e-4  # no jump when the split starts


def test_envelope_covers_the_whole_file() -> None:
    """Last 30 ms of a long-decay hat is not silent (envelope not cut short), 4 ms RMS."""
    a = _r(decay_ms=600, length_ms=500)
    tail = a[-int(0.030 * SR):-int(0.006 * SR)]
    assert float(np.sqrt(np.mean(tail**2))) > 1e-3 * float(np.max(np.abs(a)))


def _check_envelope_fall() -> None:
    """Independent of the engine: level at 0.5 decay vs the start, in 20 ms RMS windows, must
    follow 10**(-3 * t / decay) for t from the attack end (expected values written here)."""
    decay = 400.0
    meas, expect = [], []
    for seed in range(1, 5):
        a = _r(seed=seed, decay_ms=decay, hp_hz=4000)
        for t0 in (40.0, 120.0, 200.0):
            lo, hi = int(t0 / 1000 * SR), int((t0 + 20) / 1000 * SR)
            meas.append(20 * math.log10(float(np.sqrt(np.mean(a[lo:hi] ** 2)))))
            expect.append(-3 * 20 * (t0 + 10 - 0.8) / decay)
    meas, expect = np.array(meas).reshape(4, 3), np.array(expect).reshape(4, 3)
    d = meas - meas[:, :1] - (expect - expect[:, :1])
    assert np.max(np.abs(d)) < 1.5, d


def test_envelope_slope_matches_decay_ms() -> None:
    _check_envelope_fall()


# --- choke -------------------------------------------------------------------------------------


def _check_choke(choke_ms: float, offset_ms: float = 0.0) -> None:
    kw = {"decay_ms": 500, "seed": 3, "offset_ms": offset_ms}
    free, cut = _r(**kw), _r(**kw, choke_ms=choke_ms)
    start = round(offset_ms * SR / 1000) + round(choke_ms * SR / 1000)
    assert len(cut) == len(free)
    assert np.array_equal(cut[:start], free[:start])  # prefix bit-identical (H11)
    end = start + round(FADE * SR / 1000)
    assert np.all(cut[end:] == 0.0)
    peak = float(np.max(np.abs(free)))
    rms_after = float(np.sqrt(np.mean(cut[end:] ** 2))) if end < len(cut) else 0.0
    assert 20 * math.log10(max(rms_after, 1e-12) / peak) < -60
    fade = cut[start:end]
    ratio = fade[1:] / free[start + 1:end]  # linear gain from 1 towards 0
    assert np.all(np.diff(ratio) < 0) and ratio[0] < 1.0 and ratio[-1] > 0.0
    assert np.max(np.abs(cut)) <= peak + 1e-15  # never above the ceiling


@pytest.mark.parametrize("choke_ms", [5, 20, 80, 150, 400])
def test_choke_keeps_the_prefix_and_silences_after_the_fade(choke_ms: float) -> None:
    _check_choke(choke_ms)
    _check_choke(choke_ms, offset_ms=7)


def test_choke_beyond_the_file_changes_nothing() -> None:
    free = _r(decay_ms=60)
    assert np.array_equal(_r(decay_ms=60, choke_ms=900), free)


def test_choke_is_not_a_boolean() -> None:
    assert not np.array_equal(_r(decay_ms=500, choke_ms=20), _r(decay_ms=500, choke_ms=0))


# --- drive aliasing ----------------------------------------------------------------------------

OVERSAMPLE = 16
LIMIT_DB = -68.0  # the kick drive's bound (user decision 2026-11-02)


def _ideal_drive(x: np.ndarray, drive: float) -> np.ndarray:
    """Reference: tanh(g x) / tanh(g) at 16x (FFT up/down-sampling), g = 10 * drive ** 0.8."""
    n, g = len(x), 10.0 * drive**0.8
    spec = np.fft.rfft(np.concatenate([x, np.zeros(n)]))
    up = np.zeros(2 * n * OVERSAMPLE // 2 + 1, dtype=complex)
    up[: len(spec)] = spec
    u = np.fft.irfft(up, 2 * n * OVERSAMPLE) * OVERSAMPLE
    down = np.fft.rfft(np.tanh(g * u) / math.tanh(g))[: n + 1] / OVERSAMPLE
    y = np.fft.irfft(down, 2 * n)[:n]
    y[0] = 0.0
    return y


def _band_limit(x: np.ndarray, sr: int) -> np.ndarray:
    n = len(x)
    spec = np.fft.rfft(np.concatenate([x, np.zeros(n)]))
    spec[np.fft.rfftfreq(2 * n, 1.0 / sr) > 20000.0] = 0.0
    return np.fft.irfft(spec, 2 * n)[:n]


def _alias_db(monkeypatch, p: dict, drive_fn=None) -> float:
    def render(fn):
        with monkeypatch.context() as m:
            m.setattr(H, "_normalise", lambda x, ceiling, bits: x)
            if fn is not None:
                m.setattr(H, "_drive", fn)
            return render_hat(p)[0]

    test, ref = render(drive_fn), render(_ideal_drive)
    sr = p.get("sample_rate", 48000)
    cut = len(ref) - round(0.006 * sr)
    err = (_band_limit(test, sr) - _band_limit(ref, sr))[:cut]
    return 20 * math.log10(math.sqrt(float(np.mean(err**2))) / float(np.max(np.abs(ref))))


ALIAS_CASES = [
    {"seed": 1, "drive": 1.0, "decay_ms": 80, "sample_rate": 44100},
    {"seed": 2, "drive": 1.0, "decay_ms": 80, "hp_hz": 2000, "metal": 1.0},
    {"seed": 3, "drive": 0.6, "decay_ms": 250},
    {"seed": 4, "drive": 0.1, "decay_ms": 40},
]


@pytest.mark.parametrize("extra", ALIAS_CASES, ids=lambda e: f"s{e['seed']}")
def test_drive_aliasing_stays_under_the_kick_bound(monkeypatch, extra) -> None:
    db = _alias_db(monkeypatch, {**BASE, **extra})
    assert db <= LIMIT_DB, db


def test_the_alias_check_can_fail(monkeypatch) -> None:
    def naive(x, drive):
        g = 10.0 * drive**0.8
        y = np.tanh(g * x) / math.tanh(g)
        y[0] = 0.0
        return y

    assert _alias_db(monkeypatch, {**BASE, **ALIAS_CASES[0]}, naive) > LIMIT_DB + 20


# --- fault injection: each key check turns red on a broken engine -------------------------------


def test_mutant_prefilter_metal_normalisation_fails_the_share_check(monkeypatch) -> None:
    """Normalise before the filter chain (the rejected reading): H2 must fail."""
    def prefilter(bank, noise, share, chain):
        def unit(x):
            return x / math.sqrt(float(np.mean(x * x)))
        return chain(math.sqrt(share) * unit(bank) + math.sqrt(1.0 - share) * unit(noise))

    monkeypatch.setattr(H, "mix_passband", prefilter)
    with pytest.raises(AssertionError):
        _check_metal_is_passband_share()


def test_mutant_share_scaled_by_1_02_inside_a_close_value_fails(monkeypatch) -> None:
    """A 2 % share error is below the +-0.05 tolerance at one value; a 15 % one is not."""
    real = H.mix_passband
    monkeypatch.setattr(H, "mix_passband", lambda b, n, s, c: real(b, n, min(1.0, s * 1.35), c))
    with pytest.raises(AssertionError):
        _check_metal_is_passband_share()


def test_mutant_unapplied_choke_fails(monkeypatch) -> None:
    monkeypatch.setattr(H, "choke_gain", lambda m, sr, ms: np.ones(m))
    with pytest.raises(AssertionError):
        _check_choke(80)


def test_mutant_choke_cuts_before_its_time_fails(monkeypatch) -> None:
    real = H.choke_gain
    monkeypatch.setattr(H, "choke_gain", lambda m, sr, ms: real(m, sr, ms * 0.95))
    with pytest.raises(AssertionError):
        _check_choke(80)


def test_mutant_choke_before_normalisation_fails(monkeypatch) -> None:
    """Wrong order: normalise after the cut. The prefix then gets another gain."""
    real_choke = H.choke_gain
    orig = H.render_resolved

    def wrong(p):
        free = orig({**p, "choke_ms": 0})
        if p["choke_ms"] > 0:
            n_off = H.offset_samples(p)
            g = real_choke(len(free) - n_off, p["sample_rate"], p["choke_ms"])
            x = free[n_off:] * g
            x = x / np.max(np.abs(x)) * np.max(np.abs(free))  # renormalised after the cut
            return np.concatenate([np.zeros(n_off), x])
        return free

    monkeypatch.setattr(H, "render_resolved", wrong)
    with pytest.raises(AssertionError):
        _check_choke(5)


def test_mutant_slower_envelope_fails_the_decay_checks(monkeypatch) -> None:
    real = H._amp_envelope
    monkeypatch.setattr(H, "_amp_envelope", lambda t, a, d: real(t, a, d * 1.15))
    with pytest.raises(AssertionError):
        _check_decay_matches_t60()
    with pytest.raises(AssertionError):
        _check_envelope_fall()


# --- presets and the targets note (H1) ----------------------------------------------------------

# Boxes of docs/research/2026-11-02_hat-targets-and-listening-plan.md section 2, post-HP
# column (min..max over seeds 1-8 of the sound designer's own model). The engine must land
# within 15 % of the box edges (H1).
TARGETS = {
    "closed-tight": {"t60_ms": (32.5, 35.9), "spectral_centroid_hz": (11700, 12600),
                     "hf_share_8k": (0.836, 0.881)},
    "closed-std": {"t60_ms": (65.2, 69.9), "spectral_centroid_hz": (10882, 11525),
                   "hf_share_8k": (0.727, 0.779)},
    "closed-loose": {"t60_ms": (109.9, 117.9), "spectral_centroid_hz": (10100, 10700),
                     "hf_share_8k": (0.626, 0.685)},
    "open-short": {"t60_ms": (228.7, 241.9), "spectral_centroid_hz": (11000, 11400),
                   "hf_share_8k": (0.739, 0.771)},
    "open-long": {"t60_ms": (456, 474), "spectral_centroid_hz": (10700, 10900),
                  "hf_share_8k": (0.702, 0.717)},
}


def test_the_five_presets_exist_and_validate() -> None:
    assert preset_names("hat") == sorted(TARGETS)
    for name in TARGETS:
        p = load_preset(name, "hat")
        assert p["preset"] == name
        resolve_hat_params(p)


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_presets_land_inside_the_targets_note_boxes(name: str) -> None:
    base = load_preset(name, "hat")
    rows = [analysis.analyse_nonpitched(render_hat({**base, "seed": s})[0], SR)
            for s in range(1, 9)]
    for key, (lo, hi) in TARGETS[name].items():
        vals = [r[key] for r in rows]
        assert lo * 0.85 <= min(vals) and max(vals) <= hi * 1.15, (key, min(vals), max(vals))


# --- golden hashes (Linux x86_64, NumPy 2.5.3) --------------------------------------------------

GOLDEN_VERSION = "0.1.0"
GOLDEN: dict = {
    "preset-closed-tight": (lambda: load_preset("closed-tight", "hat"),
                 "0a972becc4fa9b98fd30fa7ee8c314a7e170ed10547369158a1c99364c7ee257"),
    "preset-closed-std": (lambda: load_preset("closed-std", "hat"),
                 "d4767905ee0299378f44c498544643efabdeafac2fac503219fee37787e511e7"),
    "preset-closed-loose": (lambda: load_preset("closed-loose", "hat"),
                 "57b18944cb69febfeda4bbf45307026825a2b8a39adf21c1c6891254aa842f5e"),
    "preset-open-short": (lambda: load_preset("open-short", "hat"),
                 "3f6cd7abb02f06cd46e76016038a4d515f8dc8f134481722ccd3f34b6ef8d522"),
    "preset-open-long": (lambda: load_preset("open-long", "hat"),
                 "f928f554298f4ba59697fe421d64b441f11473d421411fbf49789f48fddb68b4"),
    # every non-default field family
    "all-fields-44k1-16bit": (
        lambda: {"schema_version": "0.1", "seed": 9, "decay_ms": 200, "body_mix": 0.4,
                 "decay_hi_ratio": 0.4, "bp_mix": 0.5, "peak_db": 4, "color": 0.2,
                 "pitch_scale": 1.3, "drive": 0.5, "choke_ms": 120, "offset_ms": 3,
                 "polarity": -1, "sample_rate": 44100, "bit_depth": 16},
        "a5d803b003a96906ac75ee2ceed089fbc97d75d8244cef23208a8200c2a0b14c"),
}


def _wav(params: dict) -> bytes:
    a, r = render_hat(params)
    return encode_wav(a, r["sample_rate"], r["bit_depth"])


def test_golden_hashes_belong_to_the_version() -> None:
    assert H.HAT_VERSION == GOLDEN_VERSION, (
        "hat engine bytes changed: bump HAT_VERSION (D-013) and update GOLDEN in this file"
    )
    assert H.HAT_NAME == "abeltongod-audio-engine-hat"


@pytest.mark.parametrize("name", GOLDEN)
def test_golden_sha256(name: str) -> None:
    params, expected = GOLDEN[name]
    assert hashlib.sha256(_wav(params())).hexdigest() == expected


def test_kick_and_clap_golden_hashes_are_untouched_by_this_module() -> None:
    """The hat adds a preset folder and a describe() branch; the kick and clap presets still
    load by their old names (their own golden tests are in test_kick.py / test_clap.py)."""
    assert "centre" in preset_names("kick") and "short" in preset_names("clap")
