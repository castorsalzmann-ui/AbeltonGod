"""Bass voice (#328): contract, determinism, measurements with the methods of bass-params rule 8,
golden hashes, fault injection.

References are written in the test: the RBJ filter responses are evaluated here from the
cookbook formulas, the pitch is measured with zero crossings and a zero-padded FFT (not with
``bass.fundamental_hz``), partials by a coherent DFT over whole periods, the low-pass envelope
by a second implementation (transposed direct form II) and by centroids. Each important check
is a ``_check_*`` function that runs on the engine and again on a deliberately broken engine
(``test_mutants_are_caught``) so it is shown to be able to fail.

``rise_time_ms`` / ``t60_ms`` / ``analysis.analyse`` are not used (contract rule 8).
"""

from __future__ import annotations

import hashlib
import json
import math

import numpy as np
import pytest

import audio_engine.bass as B
from audio_engine import bass_variants
from audio_engine.bass import BassParamsError, render_bass, resolve_bass_params
from audio_engine.io import encode_wav, wav_samples
from audio_engine.presets import load_preset, preset_names

SCHEMA = json.loads(B.BASS_SCHEMA_FILE.read_text(encoding="utf-8"))
PROPS = SCHEMA["properties"]
NUMERIC = [k for k, v in PROPS.items() if v.get("type") in ("number", "integer")
           and k not in ("seed", "variants", "bpm")]
BASE = {"schema_version": "0.1", "seed": 3}
NEUTRAL = {"lp_env_amount": 0, "drive": 0}  # the other stages off (rule 8)
SR = 48000


def _f0(note: float, cents: float = 0.0) -> float:
    return 440.0 * 2.0 ** ((note - 69) / 12.0 + cents / 1200.0)  # written here, not imported


def _r(**kw) -> tuple[np.ndarray, dict]:
    return render_bass({**BASE, **NEUTRAL, **kw})


def _draw(rng: np.random.Generator, gate: tuple[float, float] = (50, 1500)) -> dict:
    """One random valid document over the whole contract range (endpoints now and then)."""
    def u(name: str) -> float:
        lo, hi = PROPS[name]["minimum"], PROPS[name]["maximum"]
        pick = rng.random()
        return float(lo if pick < 0.06 else hi if pick < 0.12 else rng.uniform(lo, hi))

    sr = int(rng.choice([44100, 48000]))
    p: dict = {"schema_version": "0.1", "seed": int(rng.integers(0, 2**32)), "sample_rate": sr,
               "bit_depth": int(rng.choice([16, 24])), "polarity": int(rng.choice([1, -1])),
               "note": int(rng.integers(24, 56))}
    for name in ("cents", "saw_level", "square_level", "sine_level", "sub_octave_level",
                 "release_ms", "amp_attack_ms", "lp_q", "lp_env_amount", "lp_env_decay_ms",
                 "drive", "offset_ms", "peak_ceiling_dbfs"):
        p[name] = u(name)
    p["gate_ms"] = float(rng.uniform(*gate))
    if rng.random() < 0.3:
        p["sub_octave_level"] = 0.0
    if all(p[k] == 0 for k in ("saw_level", "square_level", "sine_level", "sub_octave_level")):
        p["sine_level"] = 0.5
    f0 = _f0(p["note"], p["cents"])
    hp_hi = min(120.0, 0.8 * f0 - 0.01)
    p["hp_hz"] = float(rng.uniform(20, hp_hi))
    cap = 0.45 * sr / 2.0 ** p["lp_env_amount"] - 0.01
    p["lp_hz"] = float(rng.uniform(max(60.0, 1.2 * p["hp_hz"]), min(4000.0, cap)))
    return p


RANDOM = [_draw(np.random.default_rng(900 + i)) for i in range(24)]


# --- window helpers (written here) ------------------------------------------------------------


def _window(p: dict, even: bool = False) -> tuple[int, int, int]:
    """(start, length, periods): 40-80 % of the gate, cut to whole periods of the note."""
    f0 = _f0(p["note"], p["cents"])
    gate = round(p["gate_ms"] * p["sample_rate"] / 1000)
    off = round(p["offset_ms"] * p["sample_rate"] / 1000)
    a, b = off + round(0.4 * gate), off + round(0.8 * gate)
    n = int((b - a) * f0 / p["sample_rate"])
    if even:
        n -= n % 2
    return a, round(n * p["sample_rate"] / f0), n


def _partial(x: np.ndarray, sr: int, f: float, a: int, length: int) -> float:
    n = np.arange(length)
    return 2.0 / length * abs(np.dot(x[a : a + length], np.exp(-2j * np.pi * f * n / sr)))


def _rbj(kind: str, fc: float, q: float, f: float, sr: int) -> float:
    """|H| of the RBJ cookbook 2nd-order low-/high-pass at f (evaluated on the unit circle)."""
    w0 = 2 * math.pi * fc / sr
    al, cw = math.sin(w0) / (2 * q), math.cos(w0)
    if kind == "lp":
        b = np.array([(1 - cw) / 2, 1 - cw, (1 - cw) / 2])
    else:
        b = np.array([(1 + cw) / 2, -(1 + cw), (1 + cw) / 2])
    a = np.array([1 + al, -2 * cw, 1 - al])
    z = np.exp(-1j * 2 * math.pi * f / sr * np.arange(3))
    return float(abs(np.dot(b, z) / np.dot(a, z)))


def _expected_ratios(p: dict, ks: list[float]) -> dict[float, float]:
    """Expected partial level at k f0 over the first partial (k = 1), from the contract."""
    f0, sr = _f0(p["note"], p["cents"]), p["sample_rate"]

    def level(k: float) -> float:
        if k == 0.5:
            c = p["sub_octave_level"]
        else:
            c = p["saw_level"] / k + (p["square_level"] / k if k % 2 == 1 else 0.0)
            c += p["sine_level"] if k == 1 else 0.0
        return c * _rbj("hp", p["hp_hz"], 1 / math.sqrt(2), k * f0, sr) * _rbj(
            "lp", p["lp_hz"], p["lp_q"], k * f0, sr)

    ref = level(1)
    return {k: level(k) / ref for k in ks}


def _db(x: float) -> float:
    return 20 * math.log10(max(x, 1e-12))


# --- contract -----------------------------------------------------------------------------------


def test_defaults_are_the_contract_defaults() -> None:
    p = resolve_bass_params(BASE)
    for name, prop in PROPS.items():
        if "default" in prop:
            assert p[name] == prop["default"], name
    assert p["note"] == 43 and p["hp_hz"] == 20 and p["drive"] == 0.2


@pytest.mark.parametrize("name", NUMERIC)
def test_out_of_range_is_rejected_never_clamped(name: str) -> None:
    lo, hi = PROPS[name].get("minimum"), PROPS[name].get("maximum")
    step = 1 if name == "note" else 1e-6 * max(1, abs(lo))
    for bad in (lo - step, hi + (1 if name == "note" else 1e-6 * max(1, abs(hi)))):
        with pytest.raises(BassParamsError, match=name):
            resolve_bass_params({**BASE, name: bad})


@pytest.mark.parametrize("bad", [
    {"unknown": 1}, {"note": 43.5}, {"note": True}, {"saw_level": float("nan")},
    {"gate_ms": float("inf")}, {"polarity": 0}, {"sample_rate": 96000}, {"bit_depth": 32},
    {"detune_cents": 3}, {"length_ms": 300}, {"preset": 3},
])
def test_bad_fields_are_rejected(bad: dict) -> None:
    with pytest.raises(BassParamsError):
        resolve_bass_params({**BASE, **bad})


def test_missing_required_and_non_object() -> None:
    with pytest.raises(BassParamsError):
        resolve_bass_params({"schema_version": "0.1"})
    with pytest.raises(BassParamsError):
        resolve_bass_params([])  # type: ignore[arg-type]


def test_cross_field_rules_reject_with_a_named_error_and_accept_at_the_edge() -> None:
    f31 = _f0(31)
    with pytest.raises(BassParamsError, match=r"hp_hz: must be less than 0\.8 \* f0"):
        render_bass({**BASE, "note": 31, "hp_hz": 40})
    assert 0.8 * f31 < 40  # the contract's own example
    resolve_bass_params({**BASE, "note": 31, "hp_hz": 0.8 * f31 - 1e-6})
    with pytest.raises(BassParamsError, match=r"hp_hz"):
        resolve_bass_params({**BASE, "note": 31, "hp_hz": 0.8 * f31 + 1e-6})
    with pytest.raises(BassParamsError, match=r"lp_hz: must be at least 1\.2 \* hp_hz"):
        resolve_bass_params({**BASE, "note": 55, "hp_hz": 100, "lp_hz": 119.99})
    resolve_bass_params({**BASE, "note": 55, "hp_hz": 100, "lp_hz": 120.0})
    with pytest.raises(BassParamsError, match=r"lp_env_amount"):
        resolve_bass_params({**BASE, "lp_hz": 4000, "lp_env_amount": 4})  # 64000 > 21600
    resolve_bass_params({**BASE, "lp_hz": 1300, "lp_env_amount": 4})  # 20800 < 21600
    resolve_bass_params({**BASE, "sample_rate": 44100, "lp_hz": 1240, "lp_env_amount": 4})
    with pytest.raises(BassParamsError, match=r"lp_env_amount"):
        resolve_bass_params({**BASE, "sample_rate": 44100, "lp_hz": 1241, "lp_env_amount": 4})
    zero = dict.fromkeys(("saw_level", "square_level", "sine_level", "sub_octave_level"), 0)
    with pytest.raises(BassParamsError, match="at least one must be greater than 0"):
        resolve_bass_params({**BASE, **zero})
    resolve_bass_params({**BASE, **zero, "sub_octave_level": 0.01})


@pytest.mark.parametrize("note", range(24, 56))
@pytest.mark.parametrize("cents", [-50, 0, 50])
def test_every_default_satisfies_the_cross_field_rules(note: int, cents: int) -> None:
    resolve_bass_params({**BASE, "note": note, "cents": cents})


def test_resolving_twice_is_the_identity_and_variants_is_batch_only() -> None:
    r = resolve_bass_params({**BASE, "variants": 3})
    assert resolve_bass_params(r) == r
    assert "variants" not in render_bass({**BASE, "variants": 3})[1]


# --- determinism, structure ---------------------------------------------------------------------


def _wav(p: dict) -> bytes:
    a, r = render_bass(p)
    return encode_wav(a, r["sample_rate"], r["bit_depth"])


def test_same_parameters_same_bytes_and_seed_does_not_change_the_voice() -> None:
    p = {**BASE, "note": 33, "gate_ms": 120}
    assert _wav(p) == _wav(p)
    audio = {s: render_bass({**p, "seed": s})[0] for s in (0, 1, 4294967295)}
    assert all(np.array_equal(audio[0], a) for a in audio.values())  # rule 7: seed-independent


@pytest.mark.parametrize("p", RANDOM, ids=[f"r{i}" for i in range(len(RANDOM))])
def test_structure_over_the_whole_contract_range(p: dict) -> None:
    audio, r = render_bass(p)
    sr = r["sample_rate"]
    n = round((r["offset_ms"] + r["gate_ms"] + r["release_ms"]) * sr / 1000)
    assert len(audio) == n and np.all(np.isfinite(audio))
    off = round(r["offset_ms"] * sr / 1000)
    assert not np.any(audio[:off])
    q = wav_samples(encode_wav(audio, sr, r["bit_depth"]))
    scale = 2 ** (r["bit_depth"] - 1) - 1
    assert q[0] == 0 and q[-1] == 0  # first and last sample are 0 (rule 5)
    peak = np.max(np.abs(q)) / scale
    ceiling = 10 ** (r["peak_ceiling_dbfs"] / 20)
    assert peak <= ceiling + 1e-12 and peak >= ceiling - 2.0 / scale
    pos = _wav({**p, "polarity": 1})
    neg = _wav({**p, "polarity": -1})
    assert np.array_equal(wav_samples(pos), -wav_samples(neg))


# --- pitch (Q1): two independent methods over the same interval, in cents -----------------------


def _cents(measured: float, f0: float) -> float:
    return 1200 * math.log2(measured / f0)


def _zero_crossing_hz(seg: np.ndarray, sr: int) -> float:
    i = np.nonzero((seg[:-1] < 0) & (seg[1:] >= 0))[0]
    frac = seg[i] / (seg[i] - seg[i + 1])
    return sr / float(np.mean(np.diff(i + frac)))


def _fft_peak_hz(seg: np.ndarray, sr: int) -> float:
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), 16 * len(seg)))
    k = int(np.argmax(spec))
    a, b, c = np.log(spec[k - 1 : k + 2] + 1e-300)
    return (k + 0.5 * (a - c) / (a - 2 * b + c)) * sr / (16 * len(seg))


def _check_pitch() -> float:
    rng = np.random.default_rng(31)
    worst = 0.0
    for note in range(24, 56):  # every note, random cents
        cents = float(rng.uniform(-50, 50))
        audio, p = _r(note=note, cents=cents, saw_level=0, gate_ms=700, lp_hz=4000)
        a, length, _ = _window(p)
        seg = audio[a : a + length]
        f0 = _f0(note, cents)
        zc, fft = _zero_crossing_hz(seg, SR), _fft_peak_hz(seg, SR)
        assert abs(_cents(zc, f0)) < 0.5 and abs(_cents(fft, f0)) < 1.0, (note, cents)
        assert abs(_cents(zc, fft)) < 1.0
        worst = max(worst, abs(_cents(zc, f0)), abs(_cents(fft, f0)))
    return worst


def test_pitch_all_notes_two_methods() -> None:
    _check_pitch()


@pytest.mark.parametrize("p", RANDOM, ids=[f"r{i}" for i in range(len(RANDOM))])
def test_fundamental_hz_feature_is_a_measurement_near_the_note(p: dict) -> None:
    audio, r = render_bass({**p, "gate_ms": max(p["gate_ms"], 500)})
    f0 = _f0(r["note"], r["cents"])
    got = B.fundamental_hz(audio, r)
    assert got is not None
    assert abs(_cents(got, f0)) < 5.0  # measured worst over notes with >= 500 ms gate: see PR


def test_fundamental_hz_is_null_below_two_periods_and_never_taken_from_the_release() -> None:
    audio, p = render_bass({**BASE, "note": 24, "gate_ms": 140})  # 0.4 * 140 ms = 1.83 periods
    assert B.fundamental_hz(audio, p) is None
    audio, p = render_bass({**BASE, "note": 24, "gate_ms": 160})
    assert B.fundamental_hz(audio, p) is not None
    audio, p = render_bass({**BASE, "note": 24, "gate_ms": 50, "release_ms": 400})
    assert B.fundamental_hz(audio, p) is None
    audio, p = render_bass({**BASE, "note": 43, "sub_octave_level": 1.0, "gate_ms": 600})
    assert abs(_cents(B.fundamental_hz(audio, p), _f0(43))) < 5  # the note, not f0 / 2


@pytest.mark.parametrize("freq", [96.5, 99.7, 101.9])
def test_fundamental_hz_follows_a_hand_made_detuned_sine_not_the_note(freq: float) -> None:
    # Note 43 is 98.0 Hz (written here, not computed); the input is a sine 1.5 to 40 cents away.
    audio, p = render_bass({**BASE, "note": 43, "gate_ms": 600})
    t = np.arange(len(audio)) / p["sample_rate"]
    sine = 0.5 * np.sin(2 * np.pi * freq * t)
    sidecar = B.analyse_bass(sine, p["sample_rate"], p)
    for got in (B.fundamental_hz(sine, p), sidecar["fundamental_hz"]):
        assert got is not None
        assert abs(got - freq) < 0.1, (freq, got)
        assert abs(got - 98.0) > 1.0  # not the note frequency


def test_dc_offset_is_the_signed_mean_of_a_hand_made_signal() -> None:
    sr = 48000
    t = np.arange(sr) / sr  # 1 s, 100 whole periods of 100 Hz: the sine part averages to 0
    wobble = 0.2 * np.sin(2 * np.pi * 100.0 * t)
    for dc in (0.3, -0.25, 0.0):
        got = B.analyse_basic(wobble + dc, sr)["dc_offset"]
        assert got == pytest.approx(dc, abs=1e-6), (dc, got)
    # a signal whose mean is negative while the mean of |x| is large
    sq = np.where(np.arange(1000) < 250, 0.5, -0.5)  # mean = 0.5 * (250 - 750) / 1000 = -0.25
    assert B.analyse_basic(sq, sr)["dc_offset"] == pytest.approx(-0.25, abs=1e-6)
    assert B.analyse_basic(-sq, sr)["dc_offset"] == pytest.approx(0.25, abs=1e-6)


# --- oscillators and static filters (Q2, Q4): partial levels against the written response -------


def _check_partials(cases: list[dict], tol_db: float = 0.15) -> float:
    worst = 0.0
    for case in cases:
        audio, p = _r(gate_ms=900, **case)
        a, length, n = _window(p, even=True)
        assert n >= 8
        f0 = _f0(p["note"], p["cents"])
        k_max = int((0.45 * p["sample_rate"]) / f0)
        ks = [k for k in (0.5, 1, 2, 3, 4, 5, 6, 7, 8, 11, 16, 25) if k <= k_max]
        want = _expected_ratios(p, ks)
        first = _partial(audio, p["sample_rate"], f0, a, length)
        for k in ks:
            if want[k] < 10 ** (-50 / 20) or (k == 0.5 and p["sub_octave_level"] == 0):
                continue
            got = _partial(audio, p["sample_rate"], k * f0, a, length) / first
            err = abs(_db(got) - _db(want[k]))
            worst = max(worst, err)
            assert err < tol_db, (case, k, _db(got), _db(want[k]))
    return worst


def _partial_cases() -> list[dict]:
    rng = np.random.default_rng(77)
    cases = [
        {"note": 43},  # defaults: saw + sine
        {"note": 24, "saw_level": 1, "sine_level": 0, "lp_hz": 4000, "lp_q": 0.5},
        {"note": 55, "saw_level": 0, "square_level": 1, "sine_level": 0.2, "lp_hz": 2500},
        {"note": 35, "saw_level": 0.3, "square_level": 0.4, "sine_level": 0.5,
         "sub_octave_level": 0.6, "hp_hz": 40, "lp_hz": 700, "lp_q": 3},
        {"note": 40, "lp_hz": 3 * _f0(40), "lp_q": 6},  # resonance at the 3rd partial
    ]
    for _ in range(8):
        p = _draw(rng, (900, 900))
        keep = {k: p[k] for k in ("note", "cents", "saw_level", "square_level", "sine_level",
                                  "sub_octave_level", "hp_hz", "lp_hz", "lp_q", "sample_rate")}
        keep["lp_hz"] = min(keep["lp_hz"], 0.45 * keep["sample_rate"] - 1)
        cases.append(keep)
    return cases


def test_oscillator_levels_and_static_filters_match_the_written_response() -> None:
    _check_partials(_partial_cases())


def test_partials_stop_below_0_45_sample_rate() -> None:
    """Note 24 with cents chosen so that one period is a whole number of samples: the window
    holds whole periods to the sample and the DFT has no leakage."""
    for sr, period in ((48000, 1468), (44100, 1349)):
        f0 = sr / period
        cents = 1200 * math.log2(f0 / _f0(24))
        assert abs(cents) < 1
        audio, p = _r(note=24, cents=cents, saw_level=1, sine_level=0, lp_hz=4000, lp_q=0.5,
                      sample_rate=sr, gate_ms=900)
        a = round(0.4 * 0.9 * sr)
        length = 10 * period
        k_max = int(0.45 * sr / f0)
        assert k_max * f0 < 0.45 * sr <= (k_max + 1) * f0
        want = _expected_ratios(p, [k_max - 1, k_max, k_max + 1])
        first = _partial(audio, sr, f0, a, length)
        for k in (k_max - 1, k_max):
            assert _partial(audio, sr, k * f0, a, length) / first == pytest.approx(
                want[k], rel=0.02)
        assert _partial(audio, sr, (k_max + 1) * f0, a, length) / first < 1e-3 * want[k_max]


# --- filter envelope (Q5) -----------------------------------------------------------------------


def _centroid(x: np.ndarray, sr: int) -> float:
    s = np.abs(np.fft.rfft(x)) ** 2
    return float(np.sum(np.fft.rfftfreq(len(x), 1 / sr) * s) / np.sum(s))


def _env_ratio(**kw) -> float:
    """Centroid of the first 30 ms over the centroid of the stationary window (rule 8)."""
    audio, p = render_bass({**BASE, "drive": 0, "amp_attack_ms": 0.5, **kw})
    a, length, _ = _window(p)
    return _centroid(audio[: int(0.03 * SR)], SR) / _centroid(audio[a : a + length], SR)


def _check_filter_envelope() -> None:
    saw = {"saw_level": 1, "sine_level": 0, "lp_hz": 200}  # the filter acts on the whole spectrum
    for note in (35, 43, 55):
        kw = {**saw, "note": note, "gate_ms": 600, "lp_env_decay_ms": 100}
        r0 = _env_ratio(**kw, lp_env_amount=0)
        low = _env_ratio(**kw, lp_env_amount=1.0)
        high = _env_ratio(**kw, lp_env_amount=3.0)
        assert low > r0 * 1.05 and high > low * 1.05, (note, r0, low, high)
    # cutoff law (written here): after decay_ms the excess is 0.1 %, so a window that starts at
    # t = decay_ms has the centroid of the stationary window (measured: 1.004 for 60 ms)
    audio, p = render_bass({**BASE, "drive": 0, "note": 43, "lp_env_amount": 3,
                            "lp_env_decay_ms": 60, "gate_ms": 900, **saw})
    late = _centroid(audio[int(0.5 * SR) : int(0.7 * SR)], SR)
    early = _centroid(audio[int(0.01 * SR) : int(0.03 * SR)], SR)
    at_decay = _centroid(audio[int(0.06 * SR) : int(0.08 * SR)], SR)
    assert early > 1.1 * late and abs(at_decay / late - 1) < 0.02, (early, at_decay, late)


def test_filter_envelope_raises_the_early_centroid_and_settles_at_decay() -> None:
    _check_filter_envelope()


def test_time_varying_lowpass_matches_a_second_implementation() -> None:
    """Transposed direct form II with coefficients written here; both are the same filter."""
    p = resolve_bass_params({**BASE, "lp_env_amount": 2.5, "lp_env_decay_ms": 40, "lp_q": 3,
                             "lp_hz": 500, "gate_ms": 150})
    t = np.arange(7200) / SR
    fc = 500 * 2 ** (2.5 * 10 ** (-3 * t / 0.04))  # the contract formula, written out
    assert np.allclose(B.cutoff_hz(p, t), fc, rtol=1e-12)
    x = np.random.default_rng(5).standard_normal(len(t))
    got = B._lowpass_varying(x, SR, fc, 3.0)
    w0 = 2 * np.pi * fc / SR
    al, cw = np.sin(w0) / 6.0, np.cos(w0)
    a0 = 1 + al
    b0, b1, a1, a2 = (1 - cw) / 2 / a0, (1 - cw) / a0, -2 * cw / a0, (1 - al) / a0
    ref, s1, s2 = np.zeros(len(x)), 0.0, 0.0
    for i, xi in enumerate(x):
        y = b0[i] * xi + s1
        s1 = b1[i] * xi - a1[i] * y + s2
        s2 = b0[i] * xi - a2[i] * y
        ref[i] = y
    # the two structures differ only through the changing coefficients (a few percent at most)
    assert np.sqrt(np.mean((got - ref) ** 2) / np.mean(ref**2)) < 0.05
    static = B._lowpass_varying(x, SR, np.full(len(x), 500.0), 3.0)
    assert np.allclose(static, B.rbj_lowpass(x, SR, 500.0, 3.0), atol=1e-12)


# --- amplitude (Q6, Q8, Q9, Q11) ----------------------------------------------------------------


def _peak_env(x: np.ndarray, half: int) -> np.ndarray:
    """Maximum of |x| per half period, hop one half period."""
    n = len(x) // half
    return np.abs(x[: n * half]).reshape(n, half).max(axis=1)


def _check_attack() -> None:
    rng = np.random.default_rng(12)
    for _ in range(12):
        note = int(rng.integers(35, 56))
        attack = float(rng.uniform(1.0, 30.0))
        audio, p = _r(note=note, saw_level=0, lp_hz=4000, amp_attack_ms=attack, gate_ms=400)
        per = SR / _f0(note)
        half = max(int(per / 2), 1)
        env = _peak_env(audio, half)
        a, length, _ = _window(p)
        stat = np.max(np.abs(audio[a : a + length]))
        t90 = (int(np.argmax(env >= 0.9 * stat)) + 0.5) * half / SR * 1000
        assert abs(t90 - 0.9 * attack) <= per / SR * 1000 + 0.05, (note, attack, t90)


def test_attack_time_on_a_peak_envelope() -> None:
    _check_attack()


def _release_cases():
    """16 seeded cases, release_ms >= 4 periods of f0 (rule 8 reads only there)."""
    rng = np.random.default_rng(14)
    for _ in range(16):
        note = int(rng.integers(35, 56))
        per_ms = 1000.0 / _f0(note)
        release = float(rng.uniform(max(5.0, 4 * per_ms), 400))
        yield note, per_ms, release, float(rng.uniform(50, 600))


def _release_offset_ms(audio, p, gate: float, release: float) -> float:
    """Rule 8, read literally: time from the gate end to the last sample with |x| >= 0.01 x the
    stationary peak, minus 0.99 * release_ms (0 = the ramp itself reaches 0.01 there; the rule
    says the result lies between -1 period and 0)."""
    a, length, _ = _window(p)
    stat = np.max(np.abs(audio[a : a + length]))
    g = round(gate * SR / 1000)
    last = g + int(np.nonzero(np.abs(audio[g:]) >= 0.01 * stat)[0][-1])
    return (last - g) / SR * 1000 - 0.99 * release


def _check_release(render=None) -> None:
    render = render or _r
    for note, per_ms, release, gate in _release_cases():
        audio, p = render(note=note, release_ms=release, gate_ms=gate, offset_ms=0)
        off = _release_offset_ms(audio, p, gate, release)
        # at most one period before 0.99 * release; 2 samples of slack for rounding; the rule
        # claims no upper bound; 1 ms is a sanity limit (the ramp is below 0.01 after that)
        assert -per_ms - 2 / SR * 1000 <= off <= 1.0, (note, release, gate, off, per_ms)


def _check_length() -> None:
    for note, _, release, gate in _release_cases():
        audio, _p = _r(note=note, release_ms=release, gate_ms=gate, offset_ms=0)
        assert len(audio) == round((gate + release) * SR / 1000)  # exact (rule 8)


def _check_release_and_length() -> None:
    _check_length()
    _check_release()


def test_gate_and_release_from_the_quantised_length_and_a_peak_envelope() -> None:
    _check_release_and_length()


def test_contract_rms_release_method_cannot_reach_minus_40_db() -> None:
    """Rule 8 reads the release on a period-long RMS (window = max(5 ms, one period)): when the
    release is not much longer than that window the RMS still holds the ramp at the file end, so
    -40 dB is never reached (finding, PR #328; the cases here are default-like releases)."""
    for note, rel in ((24, 60), (43, 60), (35, 100), (55, 5)):
        audio, p = _r(note=note, release_ms=rel, gate_ms=800)
        w = max(int(0.005 * SR), int(SR / _f0(note)))
        e = np.sqrt(np.convolve(audio**2, np.ones(w) / w)[: len(audio)])
        g = round(0.8 * SR)
        assert np.max(e[int(0.4 * g) : int(0.8 * g)]) > 0
        assert np.min(e[g:]) > 0.01 * np.max(e[int(0.4 * g) : g]), (note, rel)


def test_clicks_first_and_last_5_ms_stay_small() -> None:
    worst = 0.0
    for p in RANDOM:
        audio, r = render_bass({**p, "drive": 0, "offset_ms": 0, "gate_ms": max(p["gate_ms"], 200)})
        a, length, _ = _window(r)
        stat = np.max(np.abs(audio[a : a + length]))
        n5 = int(0.005 * r["sample_rate"])
        step = max(np.max(np.abs(np.diff(audio[: n5 + 1]))),
                   np.max(np.abs(np.diff(audio[-n5 - 1 :]))))
        worst = max(worst, step / stat)
    assert worst < 0.25, worst


# --- drive and DC -------------------------------------------------------------------------------


def _harmonics_db(**kw) -> tuple[float, float, float]:
    audio, p = render_bass({**BASE, "lp_env_amount": 0, "saw_level": 0, "gate_ms": 600, **kw})
    a, length, _ = _window(p)
    f0 = _f0(p["note"])
    first = _partial(audio, SR, f0, a, length)
    seg = audio[a : a + length]
    spec = np.abs(np.fft.rfft(seg)) ** 2
    bins = np.round(np.arange(1, int(0.5 * SR / f0)) * f0 * length / SR).astype(int)
    mask = np.ones(len(spec), bool)
    for b in bins:
        mask[max(b - 2, 0) : b + 3] = False
    mask[:3] = False
    inharmonic = float(np.sum(spec[mask]) / np.sum(spec))
    return (_db(_partial(audio, SR, 2 * f0, a, length) / first),
            _db(_partial(audio, SR, 3 * f0, a, length) / first), _db(inharmonic))


def _check_drive() -> None:
    clean = _harmonics_db(drive=0, lp_hz=4000, note=55)
    h2, h3, _ = _harmonics_db(drive=0.8, lp_hz=4000, note=55)
    assert clean[0] < -90 and clean[1] < -90
    assert h2 > clean[0] + 40 or h3 > clean[1] + 40
    assert max(h2, h3) > -45


def test_drive_adds_harmonics_and_stays_anti_aliased() -> None:
    _check_drive()
    for drive in (0.2, 0.6, 1.0):
        _, _, alias = _harmonics_db(drive=drive, lp_hz=4000, note=55)
        assert alias < -60, (drive, alias)  # inharmonic share of the energy, dB


def test_dc_of_neutral_renders_is_small() -> None:
    for p in RANDOM[:12]:
        audio, r = render_bass({**p, "drive": 0, "lp_env_amount": 0})
        assert abs(float(np.mean(audio))) < 0.01, p["note"]


# --- presets, variants --------------------------------------------------------------------------


def test_presets_are_valid_and_named_like_their_file() -> None:
    assert preset_names("bass") == [
        "bright", "default", "goa-roll-long", "goa-roll-medium", "goa-roll-short", "low",
        "rolling", "sub"]
    for name in preset_names("bass"):
        p = load_preset(name, "bass")
        assert p["preset"] == name
        resolve_bass_params(p)


@pytest.mark.parametrize("p", RANDOM[:10], ids=[f"r{i}" for i in range(10)])
def test_variants_stay_in_the_contract_and_are_reproducible(p: dict) -> None:
    vs = bass_variants.make_variants(p, 5)
    assert vs == bass_variants.make_variants(p, 5)
    base = resolve_bass_params(p)
    base.pop("variants")
    assert vs[0] == base
    assert len({v["seed"] for v in vs}) == 5
    for v in vs:
        assert resolve_bass_params(v) == {**v, "variants": 1}  # incl. all cross-field rules
        for fixed in ("note", "cents", "gate_ms", "release_ms", "saw_level", "hp_hz"):
            assert v[fixed] == base[fixed]
        for field, width in bass_variants.SPREAD:
            assert abs(v[field] - base[field]) <= width * base[field] + 1e-4
    assert any(v != vs[0] for v in vs[1:])


def test_variants_at_the_cutoff_limit_keep_the_rule() -> None:
    edge = {**BASE, "lp_hz": 1300, "lp_env_amount": 4, "hp_hz": 20}
    for v in bass_variants.make_variants(edge, 8):
        assert v["lp_hz"] * 2 ** v["lp_env_amount"] < 0.45 * 48000
    tight = {**BASE, "lp_hz": 24, "hp_hz": 20}
    with pytest.raises(BassParamsError):  # below the contract minimum 60: the base is refused
        bass_variants.make_variants(tight, 2)


# --- golden hashes (Linux x86_64, NumPy; see PR) -------------------------------------------------

GOLDEN_VERSION = "0.1.0"
GOLDEN: dict = {
    "preset-bright": "526b4872e63cee2b3a2b2c5fe418f0e7c00011a4139f66a0e533d8bd51f10464",
    "preset-default": "8fd29c62935ee6736ca06251a43b2ad5c94474183698359931062cd5c9f871d3",
    "preset-goa-roll-long": "1b3cd53fffbefdcffd47ed3a2505f4813bd44397e813e82390e2fe6e48ea5454",
    "preset-goa-roll-medium": "685dbddd4dee22a03e7d5115e50a0641fafa1a42b47816ec4ea7c12c4d04c0e6",
    "preset-goa-roll-short": "495f5f1075eb6e4f3092da6687cd3f507b1bb6908487da34ac34abff08c07f71",
    "preset-low": "83b70b00c68e1adaa5080700a5117b4da20ba9fe4a3f32eedf9519ab4e2649cf",
    "preset-rolling": "db969617c32b038c99dc22bf3ef02697f90fdee0e6c13adabe60fe902d044078",
    "preset-sub": "2c71272b1dc92bc75e9b068043edab0e888efacb38bd6b950652613fa23d8e40",
    "lowest-note-long": "8bce57df21dc0fc6bae3914093da7e6b3862a00c01c4e694bf2125ec535d50bb",
    "all-fields-44k1-16bit": "60931753a52b7c398fd6183c16b394bbec0868cf42a94ba609b4b4ef496a070f",
}


def _golden_cases() -> dict:
    cases = {f"preset-{n}": load_preset(n, "bass") for n in preset_names("bass")}
    cases["lowest-note-long"] = {**BASE, "note": 24, "gate_ms": 1500, "release_ms": 400}
    cases["all-fields-44k1-16bit"] = {
        **BASE, "seed": 9, "note": 50, "cents": -13.5, "saw_level": 0.4, "square_level": 0.5,
        "sine_level": 0.3, "sub_octave_level": 0.2, "gate_ms": 180, "release_ms": 40,
        "amp_attack_ms": 7, "hp_hz": 30, "lp_hz": 900, "lp_q": 2.5, "lp_env_amount": 2.2,
        "lp_env_decay_ms": 70, "drive": 0.6, "offset_ms": 3, "polarity": -1,
        "peak_ceiling_dbfs": -1.5, "sample_rate": 44100, "bit_depth": 16}
    return cases


def test_golden_hashes_belong_to_the_version() -> None:
    assert B.BASS_VERSION == GOLDEN_VERSION, (
        "bass engine bytes changed: bump BASS_VERSION (D-013) and update GOLDEN in this file")
    assert B.BASS_NAME == "abeltongod-audio-engine-bass"


@pytest.mark.parametrize("name", list(_golden_cases()))
def test_golden_sha256(name: str) -> None:
    assert hashlib.sha256(_wav(_golden_cases()[name])).hexdigest() == GOLDEN[name]


# --- fault injection -----------------------------------------------------------------------------


def _scaled(monkeypatch, **mult: float) -> None:
    orig = B.render_resolved

    def broken(p):
        return orig({**p, **{k: p[k] * v for k, v in mult.items()}})

    monkeypatch.setattr(B, "render_resolved", broken)


def _bad_cutoff(monkeypatch) -> None:
    monkeypatch.setattr(B, "cutoff_hz", lambda p, t: p["lp_hz"] * 2.0 ** (
        p["lp_env_amount"] * 10.0 ** (-1.0 * t / (p["lp_env_decay_ms"] / 1000.0))))


MUTANTS = [
    ("pitch", _check_pitch, {"note": 1.02}),
    ("pitch-cents", _check_pitch, {"cents": 1.0, "note": 1.0005}),
    ("partials-saw", lambda: _check_partials(_partial_cases()), {"saw_level": 1.1}),
    ("partials-lp", lambda: _check_partials(_partial_cases()), {"lp_hz": 1.02}),
    ("partials-hp", lambda: _check_partials(_partial_cases()), {"hp_hz": 1.3}),
    ("partials-q", lambda: _check_partials(_partial_cases()), {"lp_q": 1.08}),
    ("partials-sub", lambda: _check_partials(_partial_cases()), {"sub_octave_level": 1.1}),
    ("attack", _check_attack, {"amp_attack_ms": 1.25}),
    ("release", _check_release_and_length, {"release_ms": 1.2}),
    ("gate", _check_release_and_length, {"gate_ms": 1.003}),
    ("drive", _check_drive, {"drive": 0.0}),
    ("env-amount", _check_filter_envelope, {"lp_env_amount": 0.0}),
]


@pytest.mark.parametrize("name,check,mult", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_mutants_are_caught(monkeypatch, name: str, check, mult: dict) -> None:
    _scaled(monkeypatch, **mult)
    with pytest.raises(AssertionError):
        check()


def _release_renderer(delta_periods: float = 0.0, slope: float = 1.0):
    """Mutant renderer for the release assertion alone: the ramp length is changed by
    delta_periods periods and/or its slope by `slope`, and the file is cut or zero-padded back to
    the exact length, so the length assert cannot be what catches it. The mutant release is
    clipped to the contract range 5..400 ms (cases that need more are weaker, not rejected)."""

    def render(**kw):
        n = round((kw["gate_ms"] + kw["release_ms"]) * SR / 1000)
        per_ms = 1000.0 / _f0(kw["note"])
        rel = min(max((kw["release_ms"] + delta_periods * per_ms) / slope, 5.0), 400.0)
        audio, p = _r(**{**kw, "release_ms": rel})
        audio = audio[:n]
        return np.pad(audio, (0, n - len(audio))), p

    return render


@pytest.mark.parametrize("name,kw", [
    ("ramp-1.5-periods-short", {"delta_periods": -1.5}),
    ("ramp-1.5-periods-long", {"delta_periods": 1.5}),
    ("ramp-slope-x2", {"slope": 2.0}),
    ("ramp-slope-x0.5", {"slope": 0.5}),
], ids=lambda v: v if isinstance(v, str) else "")
def test_release_assertion_catches_a_changed_ramp(name: str, kw: dict) -> None:
    with pytest.raises(AssertionError):
        _check_release(_release_renderer(**kw))


def test_mutant_wrong_cutoff_law_is_caught(monkeypatch) -> None:
    _bad_cutoff(monkeypatch)
    with pytest.raises(AssertionError):
        _check_filter_envelope()
    with pytest.raises(AssertionError):  # and the second-implementation test
        test_time_varying_lowpass_matches_a_second_implementation()
