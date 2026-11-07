"""Perc voice (#475): contract, determinism, measured targets, golden hashes, fault injection.

Measurement method (independent of the engine code, numpy only): pitch from a Hann-windowed,
zero-padded FFT peak with parabolic interpolation, glide from the instantaneous frequency of an
FFT analytic signal (Hilbert), decay from a straight-line fit of the dB envelope, filter gains
from partial ratios against the 2nd-order Butterworth magnitude written here. Base values are
written here from the contract text (not imported from the engine). Each important check is a
``_check_*`` function that runs on the engine and again on a deliberately broken engine (the
"mutant" tests), so the check is shown to be able to fail.
"""

from __future__ import annotations

import hashlib
import json
import math
import time

import numpy as np
import pytest

import audio_engine.perc as P
from audio_engine import perc_variants
from audio_engine.io import encode_wav, wav_samples
from audio_engine.perc import PercParamsError, render_perc, resolve_perc_params
from audio_engine.presets import load_preset, preset_names

SCHEMA = json.loads(P.PERC_SCHEMA_FILE.read_text(encoding="utf-8"))
PROPS = SCHEMA["properties"]
NUMERIC = [k for k, v in PROPS.items() if v.get("type") in ("number", "integer")]
BASE = {"schema_version": "0.1", "seed": 5}
SR = 48000
MODELS = ("conga", "tom", "shaker", "cowbell", "clave")
# contract $comment point 2, written by hand: (base_hz, base_decay_ms, base_attack_ms)
CONTRACT_BASE = {
    "tom": (130.81, 300.0, 0.6), "conga": (261.63, 200.0, 0.6), "cowbell": (540.0, 120.0, 1.0),
    "clave": (2400.0, 30.0, 0.5), "shaker": (4500.0, 80.0, 12.0),
}
NO_TICK = {"tick_level": 0.0}


def _draw(rng: np.random.Generator) -> dict:
    """One random parameter set over the whole contract range (endpoints now and then)."""
    p: dict = {"schema_version": "0.1", "seed": int(rng.integers(0, 2**32))}
    for name, prop in PROPS.items():
        if name in ("schema_version", "seed", "preset", "bpm", "variants"):
            continue
        if "enum" in prop:
            p[name] = prop["enum"][int(rng.integers(len(prop["enum"])))]
        else:
            pick = rng.random()
            p[name] = float(
                prop["minimum"] if pick < 0.08 else prop["maximum"] if pick < 0.16
                else rng.uniform(prop["minimum"], prop["maximum"])
            )
    if rng.random() < 0.3:
        del p["length_ms"]  # engine-chosen length
    if rng.random() < 0.15:
        p["tick_level"] = 0.0
    return p


RANDOM = [_draw(np.random.default_rng(4750 + i)) for i in range(30)]


def _r(**kw) -> np.ndarray:
    return render_perc({**BASE, **kw})[0]


# --- independent measurement helpers (numpy only) ---------------------------------------------


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


def _spectrum(x: np.ndarray, t0_ms: float, t1_ms: float, sr: int = SR):
    w = x[int(t0_ms * sr / 1000):int(t1_ms * sr / 1000)]
    n = 1 << 18
    return np.fft.rfftfreq(n, 1.0 / sr), np.abs(np.fft.rfft(w * np.hanning(len(w)), n))


def _peak(x: np.ndarray, lo: float, hi: float, t0_ms: float, t1_ms: float, sr: int = SR
          ) -> tuple[float, float]:
    """(frequency by parabolic interpolation, magnitude) of the spectral peak in [lo, hi]."""
    f, sp = _spectrum(x, t0_ms, t1_ms, sr)
    i = int(np.argmax(np.where((f >= lo) & (f <= hi), sp, 0.0)))
    a, b, c = np.log(sp[i - 1:i + 2] + 1e-30)
    shift = 0.5 * (a - c) / (a - 2 * b + c)
    return float(f[i] + shift * (f[1] - f[0])), float(sp[i])


def _fit_decay_ms(env_db: np.ndarray, rate: float, top_db: float, bottom_db: float) -> float:
    """60 dB time from a straight-line fit of a dB envelope (sampled at ``rate`` per second)
    on its first pass from ``top_db`` to ``bottom_db`` below its maximum, after the maximum."""
    im = int(np.argmax(env_db))
    seg = env_db[im:]
    first_top = int(np.argmax(seg <= env_db[im] - top_db))
    first_bottom = int(np.argmax(seg <= env_db[im] - bottom_db))
    idx = np.arange(first_top, first_bottom + 1)
    slope = np.polyfit(idx / rate, seg[idx], 1)[0]
    return -60.0 / slope * 1000.0


def _block_db(x: np.ndarray, block: int) -> np.ndarray:
    m = len(x) // block
    power = np.mean(x[:m * block].reshape(m, block) ** 2, axis=1)
    return 10.0 * np.log10(np.maximum(power, 1e-24))


def _butter_hp_gain(f: float, fc: float) -> float:
    """Magnitude of a 2nd-order Butterworth high-pass (analog prototype)."""
    return 1.0 / math.sqrt(1.0 + (fc / f) ** 4)


# --- contract -----------------------------------------------------------------------------------


def test_defaults_are_filled_and_resolving_twice_changes_nothing() -> None:
    r = resolve_perc_params(BASE)
    assert r["model"] == "conga" and r["tune_semitones"] == 0 and r["tick_level"] == 0.2
    assert r["length_ms"] == pytest.approx(0.6 + 200 + 5)  # offset + attack + t60 + fade
    assert resolve_perc_params(r) == r


@pytest.mark.parametrize("model", MODELS)
def test_default_length_follows_the_contract_rule(model: str) -> None:
    _hz, decay, attack = CONTRACT_BASE[model]
    for scale_d, scale_a, off in ((1, 1, 0), (4, 4, 12), (0.25, 0.25, 0)):
        r = resolve_perc_params({**BASE, "model": model, "decay_scale": scale_d,
                                 "attack_scale": scale_a, "offset_ms": off})
        expected = max(20.0, off + attack * scale_a + decay * scale_d + 5.0)
        assert r["length_ms"] == pytest.approx(expected), (model, scale_d)
        assert r["length_ms"] <= PROPS["length_ms"]["maximum"]


@pytest.mark.parametrize("field", NUMERIC)
def test_every_numeric_bound_is_enforced_not_clamped(field: str) -> None:
    prop = PROPS[field]
    for ok in (prop["minimum"], prop["maximum"]):
        resolve_perc_params({**BASE, field: ok})
    for bad in (prop["minimum"] - 0.01 * max(1, abs(prop["minimum"])),
                prop["maximum"] + 0.01 * max(1, abs(prop["maximum"]))):
        with pytest.raises(PercParamsError, match=field):
            resolve_perc_params({**BASE, field: bad})


@pytest.mark.parametrize("bad", [
    {"model": "bongo"}, {"model": "Tom"}, {"pitch_hz": 200}, {"tune_semitones": float("nan")},
    {"decay_scale": float("inf")}, {"schema_version": "0.2"}, {"seed": -1}, {"seed": 1.5},
    {"tick_level": True}, {"sample_rate": 96000},
])
def test_bad_values_and_fields_outside_v01_are_rejected(bad: dict) -> None:
    with pytest.raises(PercParamsError):
        resolve_perc_params({**BASE, **bad})


def test_non_dict_and_whole_number_floats() -> None:
    with pytest.raises(PercParamsError, match="object"):
        resolve_perc_params([1])
    r = resolve_perc_params({**BASE, "seed": 7.0, "sample_rate": 44100.0, "polarity": -1.0})
    assert type(r["seed"]) is int and r["sample_rate"] == 44100 and type(r["polarity"]) is int


# --- determinism and wrong-audio failures over the whole range ---------------------------------


@pytest.mark.parametrize("p", RANDOM, ids=[f"r{i}" for i in range(len(RANDOM))])
def test_random_full_range_invariants(p: dict) -> None:
    a, r = render_perc(p)
    again, _ = render_perc(p)
    assert a.tobytes() == again.tobytes()
    other = render_perc({**p, "seed": (p["seed"] + 1) % 2**32})[0]
    seeded = r["model"] == "shaker" or r["tick_level"] > 0.0
    assert (other.tobytes() != a.tobytes()) == seeded
    sr, bits = r["sample_rate"], r["bit_depth"]
    assert len(a) == round(r["length_ms"] * sr / 1000)
    assert np.all(np.isfinite(a))
    off = round(r["offset_ms"] * sr / 1000)
    assert np.all(a[:off] == 0.0) and a[off] == 0.0
    q = wav_samples(encode_wav(a, sr, bits)) / (2 ** (bits - 1) - 1)
    peak_db = 20 * math.log10(float(np.max(np.abs(q))))
    assert r["peak_ceiling_dbfs"] - 0.05 <= peak_db <= r["peak_ceiling_dbfs"] + 1e-9
    assert a[-1] == 0.0
    assert abs(float(np.mean(a))) < 1e-3 * float(np.max(np.abs(a)))
    assert resolve_perc_params(r) == {**r, "variants": 1}


def test_worst_case_render_time() -> None:
    worst = []
    for model in MODELS:
        p = {**BASE, "model": model, "length_ms": 2000, "decay_scale": 4, "attack_scale": 4,
             "drive": 1, "tick_level": 1, "hp_hz": 1000, "tune_semitones": 12}
        start = time.perf_counter()
        render_perc(p)
        worst.append(time.perf_counter() - start)
    assert max(worst) <= 20.0, worst


def test_file_fields_do_what_they_say() -> None:
    a = _r(length_ms=200)
    assert len(a) == round(0.2 * SR)
    off = _r(length_ms=200, offset_ms=12)
    assert np.all(off[:576] == 0.0) and np.any(off[576:] != 0.0) and len(off) == len(a)
    assert np.array_equal(_r(length_ms=200, polarity=-1), -a)
    cut = _r(length_ms=50)
    assert len(cut) == 2400 and cut[-1] == 0.0 and np.any(cut[:2000] != 0.0)
    w16 = encode_wav(_r(sample_rate=44100, bit_depth=16), 44100, 16)
    assert w16[24:28] == (44100).to_bytes(4, "little")


# --- measured targets: pitch --------------------------------------------------------------------

TUNES = (-12.0, -5.0, 0.0, 7.0, 12.0)


def _check_pitch() -> None:
    """Spectral peak of the sine models (glide off) and both cowbell squares sit at
    base_hz * 2^(tune / 12) (and * 800 / 540), within 0.3 % (measured: <= 0.0001 %)."""
    for model in ("tom", "conga", "clave"):
        for tune in TUNES:
            f0 = CONTRACT_BASE[model][0] * 2 ** (tune / 12)
            a = _r(model=model, tune_semitones=tune, bend_ratio=1.0, decay_scale=4,
                   **NO_TICK)
            t1 = min(len(a) * 1000 / SR - 10, 400)
            got, _ = _peak(a, 0.8 * f0, 1.2 * f0, 0, t1)
            assert abs(got / f0 - 1) < 0.003, (model, tune, got, f0)
    for tune in TUNES:
        f0 = 540.0 * 2 ** (tune / 12)
        a = _r(model="cowbell", tune_semitones=tune, decay_scale=4, **NO_TICK)
        low, _ = _peak(a, 0.9 * f0, 1.1 * f0, 0, 400)
        high, _ = _peak(a, 0.9 * f0 * 800 / 540, 1.1 * f0 * 800 / 540, 0, 400)
        assert abs(low / f0 - 1) < 0.003, (tune, low)
        assert abs(high / (f0 * 800 / 540) - 1) < 0.003, (tune, high)


def test_pitch_follows_base_and_tune() -> None:
    _check_pitch()


def _inst_freq(x: np.ndarray, t_ms: float, half_ms: float = 0.5) -> float:
    phase = np.unwrap(np.angle(_analytic(x)))
    i0, i1 = round((t_ms - half_ms) * SR / 1000), round((t_ms + half_ms) * SR / 1000)
    return float((phase[i1] - phase[i0]) / ((i1 - i0) / SR) / (2 * math.pi))


# Only cases where one period fits between the first sample and t (a shorter window reads the
# file start: tom 1.1 / 3 ms measured 130.9 Hz instead of 136.3 Hz, a method limit).
GLIDES = [("tom", 1.5, 10.0), ("conga", 2.0, 5.0), ("conga", 1.25, 20.0), ("conga", 1.1, 8.0)]


def _check_glide() -> None:
    """Mean instantaneous frequency (analytic-signal phase difference) over t +- h around
    t = bend_ms and 3 * bend_ms equals the mean of the contract's
    f(t) = f0 * (1 + (bend_ratio - 1) * e^(-t / bend_ms)) over the same interval, written here
    in closed form, within 1 % (measured: <= 0.29 %)."""
    for model, ratio, tau in GLIDES:
        f0 = CONTRACT_BASE[model][0]
        a = _r(model=model, bend_ratio=ratio, bend_ms=tau, attack_scale=0.25, decay_scale=4,
               **NO_TICK)
        for k in (1.0, 3.0):
            t = k * tau
            h = min(1000 / f0, 0.9 * t)  # one period, never before the first sample
            i0, i1 = round((t - h) * SR / 1000), round((t + h) * SR / 1000)
            t0, t1 = i0 * 1000 / SR, i1 * 1000 / SR
            expected = f0 * (1 + (ratio - 1) * tau / (t1 - t0)
                             * (math.exp(-t0 / tau) - math.exp(-t1 / tau)))
            got = _inst_freq(a, t, half_ms=h)
            assert abs(got / expected - 1) < 0.01, (model, ratio, tau, k, got, expected)


def test_membrane_glide_follows_the_contract() -> None:
    _check_glide()


@pytest.mark.parametrize("model", ["cowbell", "clave", "shaker"])
def test_bend_has_no_effect_outside_tom_and_conga(model: str) -> None:
    a = _r(model=model, bend_ratio=1.0)
    assert a.tobytes() == _r(model=model, bend_ratio=2.0, bend_ms=30).tobytes()
    assert _r(model="tom", bend_ratio=1.0).tobytes() != _r(model="tom", bend_ratio=2.0).tobytes()


def test_tick_has_no_effect_at_shaker() -> None:
    a = _r(model="shaker", tick_level=0.0)
    assert a.tobytes() == _r(model="shaker", tick_level=1.0, tick_hz=6000).tobytes()


def test_shaker_band_follows_tune() -> None:
    """Peak of the smoothed power spectrum (16 seeds) lies near the band centre
    4500 * 2^(tune / 12), within 20 % (measured: +5 % at -12, +1 % at 0, +14.5 % at +12; the
    cause of the upward shift at +12 is not established), and moves up with tune."""
    f = np.fft.rfftfreq(1 << 15, 1 / SR)
    peaks = []
    for tune in (-12.0, 0.0, 12.0):
        acc = sum(np.abs(np.fft.rfft(_r(model="shaker", tune_semitones=tune, seed=s,
                                        decay_scale=2), 1 << 15)) ** 2 for s in range(16))
        smooth = np.convolve(acc, np.ones(41) / 41, "same")
        f0 = 4500 * 2 ** (tune / 12)
        band = (f > 0.5 * f0) & (f < 2 * f0)
        peak = float(f[band][np.argmax(smooth[band])])
        assert abs(peak / f0 - 1) < 0.2, (tune, peak, f0)
        peaks.append(peak)
    assert peaks[1] / peaks[0] > 1.6 and peaks[2] / peaks[1] > 1.6, peaks


# --- measured targets: envelope ------------------------------------------------------------------

DECAY_CASES = [("clave", 2.0), ("clave", 4.0), ("tom", 0.5), ("tom", 1.0), ("conga", 3.0),
               ("cowbell", 1.0), ("cowbell", 2.5)]


def _check_decays() -> None:
    """t60 = base_decay_ms * decay_scale: a straight-line fit of the 1 ms block-power envelope
    between -3 and -30 dB, within 6 % (measured: <= 0.4 %); shaker (2 ms blocks, 6 seeds)
    within 10 % (measured: <= 1.5 %)."""
    for model, scale in DECAY_CASES:
        expected = CONTRACT_BASE[model][1] * scale
        a = _r(model=model, decay_scale=scale, bend_ratio=1.0, **NO_TICK)
        got = _fit_decay_ms(_block_db(a, 48), 1000.0, 3.0, 30.0)
        assert abs(got / expected - 1) < 0.06, (model, scale, got, expected)
    # shaker: block power averaged over seeds
    for scale in (1.0, 3.0):
        acc = sum(10 ** (_block_db(_r(model="shaker", decay_scale=scale, seed=s), 96) / 10)
                  for s in range(6))
        got = _fit_decay_ms(10 * np.log10(acc), 500.0, 3.0, 30.0)
        expected = 80.0 * scale
        assert abs(got / expected - 1) < 0.10, (scale, got, expected)


def test_decays_match_the_contract() -> None:
    _check_decays()


def _sine_attack_ms(a: np.ndarray, f0: float, guess_ms: float) -> float:
    """Attack of a sine model (glide off): divide by sin(2 pi f0 t) where |sin| > 0.5, fit the
    ramp as k * t over (0.1 .. 0.9) * guess and the decay as a log-linear line over
    (1.5 .. 4) * guess; the attack is where the ramp meets the decay line."""
    t = np.arange(len(a)) / SR
    s = np.sin(2 * math.pi * f0 * t)
    ok = np.abs(s) > 0.02  # float64 render: the division is exact away from the zeros
    env = np.where(ok, a / np.where(ok, s, 1.0), np.nan)
    tm = t * 1000

    def pick(lo, hi):
        m = ok & (tm > lo) & (tm < hi)
        return tm[m], env[m]

    tr, er = pick(0.1 * guess_ms, 0.9 * guess_ms)
    k = float(np.dot(tr, er) / np.dot(tr, tr))
    td, ed = pick(1.5 * guess_ms, 4 * guess_ms)
    slope, c = np.polyfit(td, np.log(ed), 1)
    att = guess_ms
    for _ in range(20):
        att = math.exp(c + slope * att) / k
    return att


def _check_attacks() -> None:
    """The linear attack ends at base_attack_ms * attack_scale, within 5 % for the sine
    models (measured: <= 0.0001 %); the cowbell envelope peak within 12 % (measured: 3.81 ms
    for 4 ms); shaker from 0.5 ms block power over 8 seeds within 15 % (measured: 12.75 ms for
    12 ms, 36.75 ms for 36 ms)."""
    for model, scale in (("clave", 4.0), ("clave", 1.0), ("tom", 4.0), ("tom", 1.0),
                         ("conga", 2.0)):
        expected = CONTRACT_BASE[model][2] * scale
        f0 = CONTRACT_BASE[model][0]
        a = _r(model=model, attack_scale=scale, decay_scale=4, bend_ratio=1.0, **NO_TICK)
        got = _sine_attack_ms(a, f0, expected)
        assert abs(got / expected - 1) <= 0.05, (model, scale, got, expected)
    a = _r(model="cowbell", attack_scale=4.0, decay_scale=4, **NO_TICK)
    got = int(np.argmax(np.abs(_analytic(a))[:int(0.05 * SR)])) * 1000 / SR
    assert abs(got / 4.0 - 1) <= 0.12, got
    for scale in (1.0, 3.0):
        acc = sum(10 ** (_block_db(_r(model="shaker", attack_scale=scale, decay_scale=3,
                                      seed=s), 24) / 10) for s in range(8))
        got = (int(np.argmax(acc)) + 0.5) * 0.5
        expected = 12.0 * scale
        assert abs(got - expected) <= 0.15 * expected, (scale, got, expected)


def test_attacks_match_the_contract() -> None:
    _check_attacks()


# --- tick -----------------------------------------------------------------------------------------


def _tick_part(seed: int, level: float, tick_hz: float = 2500.0) -> tuple[np.ndarray, float]:
    """(tick signal in voice units, voice scale) from a clave render with and without tick.

    The clave sine reaches amplitude 1 at the end of its attack, so the peak of the tick-free
    render is the engine's output scale; the ratio of the two scales comes from a least-squares
    fit after 40 ms, where the tick has ended."""
    common = {"model": "clave", "decay_scale": 4, "seed": seed, "length_ms": 140}
    dry = _r(**common, tick_level=0.0)
    wet = _r(**common, tick_level=level, tick_hz=tick_hz)
    s0 = float(np.max(np.abs(dry)))
    late = slice(int(0.04 * SR), int(0.12 * SR))
    ratio = float(np.dot(wet[late], dry[late]) / np.dot(dry[late], dry[late]))
    return (wet - ratio * dry) / (ratio * s0), ratio * s0


def _check_tick() -> None:
    """Tick RMS over its 30 ms window, averaged over 32 fixed seeds, relative to
    tick_level * 0.1203 (unit-RMS noise times an exp decay of 60 dB in 6 ms:
    sqrt(tau / (2 * 30 ms)), tau = 6 ms / ln 1000) lies in [0.82, 0.98] (measured: 0.895 at
    both levels, per-seed spread 17 %; the cause of the -10.5 % is not established, a
    candidate is the band-pass settling in the first samples where the envelope is largest);
    it scales linearly with tick_level (1 %); nothing of it after 40 ms; the peak of its
    smoothed spectrum is at tick_hz within 25 % (measured: 1125 / 2496 / 6281 Hz for
    1000 / 2500 / 6000)."""
    tau = 6.0 / math.log(1000.0)
    unit = math.sqrt(tau / 2 / 30.0 * (1 - math.exp(-2 * 30.0 / tau)))
    assert unit == pytest.approx(0.1203, abs=1e-3)
    w = int(0.03 * SR)
    rel = {}
    for level in (0.2, 1.0):
        rms = np.mean([math.sqrt(float(np.mean(_tick_part(s, level)[0][:w] ** 2)))
                       for s in range(32)])
        rel[level] = rms / (level * unit)
        assert 0.82 <= rel[level] <= 0.98, (level, rel[level])
    assert rel[0.2] == pytest.approx(rel[1.0], rel=0.01)
    # After 40 ms only a smooth residual of the per-render mean removal stays (measured:
    # 3.8e-4 of the tick peak); the tick itself ends at 30 ms.
    tick, _ = _tick_part(3, 1.0)
    late = np.max(np.abs(tick[int(0.04 * SR):int(0.12 * SR)]))
    assert late < 2e-3 * np.max(np.abs(tick[:int(0.01 * SR)])), late
    for tick_hz in (1000.0, 2500.0, 6000.0):
        acc = sum(np.abs(np.fft.rfft(_tick_part(s, 1.0, tick_hz)[0][:w], 1 << 14)) ** 2
                  for s in range(8))
        f = np.fft.rfftfreq(1 << 14, 1 / SR)
        smooth = np.convolve(acc, np.ones(33) / 33, "same")
        peak = float(f[np.argmax(smooth)])
        assert abs(peak / tick_hz - 1) < 0.25, (tick_hz, peak)


def test_tick_level_window_and_band_match_the_contract() -> None:
    _check_tick()


def _check_seed_acts_only_on_noise() -> None:
    for model in ("tom", "conga", "cowbell", "clave"):
        assert _r(model=model, seed=1, **NO_TICK).tobytes() == \
            _r(model=model, seed=2, **NO_TICK).tobytes()
        assert _r(model=model, seed=1).tobytes() != _r(model=model, seed=2).tobytes()
    assert _r(model="shaker", seed=1).tobytes() != _r(model="shaker", seed=2).tobytes()


def test_seed_acts_only_on_tick_and_shaker() -> None:
    _check_seed_acts_only_on_noise()


def test_tick_and_shaker_streams_are_independent() -> None:
    """The tick of seed s and the shaker noise of seed s are different sub-streams."""
    tick, _ = _tick_part(11, 1.0)
    shaker = _r(model="shaker", seed=11, attack_scale=0.25)
    n = int(0.01 * SR)
    c = np.corrcoef(tick[:n], shaker[:n])[0, 1]
    assert abs(c) < 0.3, c


# --- hp_hz, drive -----------------------------------------------------------------------------


HP_CASES = [100.0, 300.0, 600.0, 1000.0]


def _check_highpass() -> None:
    """Cowbell tuned down an octave (lower square 270 Hz, its 3rd harmonic 810 Hz, and the
    upper square 400 Hz): the change of the 810 / 270 Hz level ratio between hp_hz 20 (off)
    and hp_hz follows the Butterworth high-pass, within 1.5 dB (measured: <= 0.09 dB)."""
    f_lo, f_hi = 270.0, 810.0
    common = {"model": "cowbell", "tune_semitones": -12, "decay_scale": 4, **NO_TICK}
    dry = _r(**common)
    d_ratio = _peak(dry, 760, 860, 0, 400)[1] / _peak(dry, 250, 290, 0, 400)[1]
    for fc in HP_CASES:
        wet = _r(**common, hp_hz=fc)
        w_ratio = _peak(wet, 760, 860, 0, 400)[1] / _peak(wet, 250, 290, 0, 400)[1]
        got_db = 20 * math.log10(w_ratio / d_ratio)
        exp_db = 20 * math.log10(_butter_hp_gain(f_hi, fc) / _butter_hp_gain(f_lo, fc))
        assert abs(got_db - exp_db) < 1.5, (fc, got_db, exp_db)


def test_highpass_follows_a_second_order_corner() -> None:
    _check_highpass()


def test_hp_hz_20_is_off_and_above_changes_every_model() -> None:
    for model in MODELS:
        a = _r(model=model, hp_hz=20)
        assert a.tobytes() == _r(model=model).tobytes()
        assert a.tobytes() != _r(model=model, hp_hz=1000).tobytes()


def test_drive_changes_the_signal_and_lowers_the_crest_factor() -> None:
    for model in ("tom", "cowbell"):
        clean = _r(model=model, **NO_TICK)
        driven = _r(model=model, drive=1.0, **NO_TICK)
        assert clean.tobytes() != driven.tobytes()

        def crest(x):
            return float(np.max(np.abs(x)) / math.sqrt(np.mean(x * x)))

        assert crest(driven) < crest(clean), model


def test_models_differ_and_every_relative_field_changes_the_audio() -> None:
    renders = {m: _r(model=m, length_ms=100) for m in MODELS}
    assert len({a.tobytes() for a in renders.values()}) == len(MODELS)
    for field, value in (("tune_semitones", 3), ("decay_scale", 2), ("attack_scale", 2)):
        for model in MODELS:
            assert _r(model=model, length_ms=100, **{field: value}).tobytes() != \
                renders[model].tobytes(), (field, model)


# --- fault injection: each key check turns red on a broken engine -------------------------------


def test_mutant_pitch_2_percent_sharp_fails(monkeypatch) -> None:
    real = P.f0_hz
    monkeypatch.setattr(P, "f0_hz", lambda p: real(p) * 1.02)
    with pytest.raises(AssertionError):
        _check_pitch()


def test_mutant_cowbell_ratio_2_percent_off_fails(monkeypatch) -> None:
    monkeypatch.setattr(P, "COWBELL_RATIO", P.COWBELL_RATIO * 1.02)
    with pytest.raises(AssertionError):
        _check_pitch()


def test_mutant_glide_time_constant_off_fails(monkeypatch) -> None:
    real = P.body_phase
    monkeypatch.setattr(P, "body_phase", lambda t, g: real(
        t, {**g, "pitch_decay_ms": g["pitch_decay_ms"] * 1.3}))
    with pytest.raises(AssertionError):
        _check_glide()


def test_mutant_slower_decay_fails(monkeypatch) -> None:
    real = P.t60_ms
    monkeypatch.setattr(P, "t60_ms", lambda p: real(p) * 1.1)
    with pytest.raises(AssertionError):
        _check_decays()


def test_mutant_longer_attack_fails(monkeypatch) -> None:
    real = P.attack_ms
    monkeypatch.setattr(P, "attack_ms", lambda p: real(p) * 1.3)
    with pytest.raises(AssertionError):
        _check_attacks()


def test_mutant_tick_scaled_fails(monkeypatch) -> None:
    real = P._tick
    monkeypatch.setattr(P, "_tick", lambda p, t, s: 1.2 * real(p, t, s))
    with pytest.raises(AssertionError):
        _check_tick()


def test_mutant_tick_decay_slower_fails(monkeypatch) -> None:
    monkeypatch.setattr(P, "TICK_DECAY_MS", 9.0)
    with pytest.raises(AssertionError):
        _check_tick()


def test_mutant_highpass_corner_moved_fails(monkeypatch) -> None:
    real = P.rbj_highpass
    monkeypatch.setattr(P, "rbj_highpass", lambda x, sr, f0, *a: real(x, sr, f0 * 1.25, *a))
    with pytest.raises(AssertionError):
        _check_highpass()


def test_mutant_seed_ignored_fails(monkeypatch) -> None:
    real = P.substreams
    monkeypatch.setattr(P, "substreams", lambda seed, count: real(0, count))
    with pytest.raises(AssertionError):
        _check_seed_acts_only_on_noise()


# --- presets -------------------------------------------------------------------------------------

PRESETS = ["bongo", "clave", "conga", "conga-dry", "cowbell", "hard-groove-tom",
           "hard-groove-tom-low", "shaker", "shaker-long"]


def test_presets_exist_validate_and_toms_only_in_hard_groove_presets() -> None:
    assert preset_names("perc") == PRESETS
    models = set()
    for name in PRESETS:
        p = load_preset(name, "perc")
        assert p["preset"] == name
        r = resolve_perc_params(p)
        models.add(r["model"])
        assert (r["model"] == "tom") == name.startswith("hard-groove"), name  # D-032
    assert models == set(MODELS)
    assert "model" not in load_preset("conga", "perc")  # the contract default, not tom


def test_preset_measurements_follow_their_fields() -> None:
    """Directions only (placeholders, no taste range)."""
    def pitch(name, lo, hi):
        a = render_perc({**load_preset(name, "perc"), "tick_level": 0.0, "bend_ratio": 1.0})[0]
        return _peak(a, lo, hi, 0, len(a) * 1000 / SR - 10)[0]

    assert pitch("bongo", 400, 700) == pytest.approx(523.26, rel=0.005)
    assert pitch("conga", 200, 330) == pytest.approx(261.63, rel=0.005)
    assert pitch("hard-groove-tom-low", 70, 120) == pytest.approx(130.81 * 2 ** (-5 / 12),
                                                                  rel=0.005)
    assert len(render_perc(load_preset("shaker-long", "perc"))[0]) > \
        len(render_perc(load_preset("shaker", "perc"))[0])


# --- golden hashes (Linux x86_64 and Windows CI run the same table) -----------------------------

GOLDEN_VERSION = "0.1.0"
GOLDEN: dict = {
    **{f"preset-{n}": (lambda n=n: load_preset(n, "perc"), None) for n in PRESETS},
    "all-fields-44k1-16bit": (
        lambda: {"schema_version": "0.1", "seed": 9, "model": "cowbell", "tune_semitones": 3.5,
                 "decay_scale": 1.7, "attack_scale": 0.8, "bend_ratio": 1.4, "bend_ms": 9,
                 "tick_level": 0.45, "tick_hz": 3300, "hp_hz": 150, "drive": 0.5,
                 "polarity": -1, "offset_ms": 3, "length_ms": 180, "sample_rate": 44100,
                 "bit_depth": 16, "peak_ceiling_dbfs": -1.5},
        None),
}
GOLDEN_SHA = {  # pinned on Linux x86_64, NumPy 2.5.3; CI checks the same table on Windows
    "preset-bongo": "648bdac9c5b3341db460c60f220167ea0cc6a9b636b8d6f4b3205ac27428e816",
    "preset-clave": "e7f6a056295c438a76d160bbeb0df65a3bbe6e80642b31ce308d9e40ba92dddf",
    "preset-conga": "c71a6e303eaaeb1d7e4b7f061ea12d4763d0ac4f21504c261f1b656d1252afb4",
    "preset-conga-dry": "fc03539514aa044f9dc696342ccc70451f4132e828a2f1b3370661667e730175",
    "preset-cowbell": "0039e0d1a01c57a081b37c8e43bda22f012e618f4c977047aa9bd09859efb50e",
    "preset-hard-groove-tom":
        "79d7724848c6e74b48a854bd1b65cdf70ffb66fa82b28919e338d0aab9c30228",
    "preset-hard-groove-tom-low":
        "0b10602b0f34c25053698e24bc23e8f263ace393fd88fa316179738edce9a33a",
    "preset-shaker": "aac9123307ef60fe3d7da6873e142d4f3e40d720e512634d3512f58ad614e7fd",
    "preset-shaker-long": "d01c6ce22d83ce590092ac40bfbb3d686302433602b487cb1e3621679855cfe8",
    "all-fields-44k1-16bit":
        "e9481ad58d3b5da520e00b473179d8ce76c88f6de531a8fabbdb8094e0a51902",
}


def _wav(params: dict) -> bytes:
    a, r = render_perc(params)
    return encode_wav(a, r["sample_rate"], r["bit_depth"])


def test_golden_hashes_belong_to_the_version() -> None:
    assert P.PERC_VERSION == GOLDEN_VERSION, (
        "perc engine bytes changed: bump PERC_VERSION (D-013) and update GOLDEN_SHA in this file"
    )
    assert P.PERC_NAME == "abeltongod-audio-engine-perc"
    assert set(GOLDEN_SHA) == set(GOLDEN)


@pytest.mark.parametrize("name", GOLDEN)
def test_golden_sha256(name: str) -> None:
    params, _ = GOLDEN[name]
    assert hashlib.sha256(_wav(params())).hexdigest() == GOLDEN_SHA[name]


# --- variants -----------------------------------------------------------------------------------


@pytest.mark.parametrize("p", RANDOM[:12], ids=[f"r{i}" for i in range(12)])
def test_variants_stay_in_the_contract_and_are_reproducible(p: dict) -> None:
    vs = perc_variants.make_variants(p, 4)
    assert vs == perc_variants.make_variants(p, 4)
    assert vs[0] == {k: v for k, v in resolve_perc_params(p).items() if k != "variants"}
    assert len({v["seed"] for v in vs}) == 4
    for v in vs:
        assert resolve_perc_params(v) == {**v, "variants": 1}
        assert v["model"] == vs[0]["model"]
        assert (v["tick_level"] == 0) == (vs[0]["tick_level"] == 0)
        if "length_ms" not in p:
            assert v["length_ms"] == pytest.approx(P.default_length_ms(v))
        else:
            assert v["length_ms"] == p["length_ms"]


def test_variants_spread_box_and_untouched_fields() -> None:
    vs = perc_variants.make_variants({**BASE, "decay_scale": 2.0}, 8)
    scales = [v["decay_scale"] for v in vs]
    assert 1.8 <= min(scales) and max(scales) <= 2.2 and len(set(scales)) > 1
    tunes = [v["tune_semitones"] for v in vs]
    assert -0.25 <= min(tunes) and max(tunes) <= 0.25 and len(set(tunes)) > 1
    for v in perc_variants.make_variants({**BASE, "model": "cowbell"}, 8):
        assert v["bend_ms"] == 5  # no effect outside tom / conga: not moved
    for v in perc_variants.make_variants({**BASE, "model": "shaker"}, 8):
        assert v["tick_level"] == 0.2
    small = perc_variants.make_variants({**BASE, "tick_level": 0.01}, 8)
    assert all(v["tick_level"] > 0 for v in small)
