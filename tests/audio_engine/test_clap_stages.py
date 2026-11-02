"""Clap v0.2 extreme stages and presets (#280).

References are written here with plain loops or a different method (spectral peaks, impulse
response, level counting, a 32x oversampled curve), not taken from the stage code. A check that
matters has a ``_mutant`` twin that feeds a faulty stage and expects the check to fail.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pytest

import audio_engine.clap as C
import audio_engine.clap_stages as S
from audio_engine import clap_variants
from audio_engine.clap import ClapParamsError, render_clap, resolve_clap_params
from audio_engine.dsp import biquad_bandpass, kaiser_lowpass, oversampled, rbj_highpass, substreams
from audio_engine.io import (
    encode_wav,
    render_sample_wav,
    rerender_from_sidecar,
    wav_samples,
    write_sample,
)
from audio_engine.presets import load_preset, preset_names

SR = 48000
V2 = {"schema_version": "0.2"}
XTREME = ["xtreme-saturated", "xtreme-folded", "xtreme-crushed", "xtreme-metal", "xtreme-gated",
          "xtreme-reversed", "xtreme-wreck"]
SCHEMA = json.loads(C.CLAP_SCHEMA_FILE.read_text(encoding="utf-8"))
V02_PROPS = SCHEMA["allOf"][0]["then"]["properties"]
OFF = {"fold": 0, "crush": 0, "rate_div": 1, "ring_mix": 0, "comb_fb": 0, "gate_ms": 0,
       "tail_reverse": False}
# one active value per field (gate_ms needs a file longer than the cut)
ACTIVE = {"fold": 0.5, "crush": 0.5, "rate_div": 4, "ring_mix": 0.8, "comb_fb": 0.7,
          "gate_ms": 60, "tail_reverse": True}


def _rms_db(x: np.ndarray) -> float:
    return 20 * math.log10(float(np.sqrt(np.mean(np.asarray(x) ** 2))) + 1e-30)


def _noise(seed: int, n: int = 6000) -> np.ndarray:
    """Band-limited-ish test signal that starts and ends at zero."""
    rng = np.random.default_rng(seed)
    x = np.convolve(rng.standard_normal(n), np.ones(4) / 4, mode="same")
    return x * np.sin(np.pi * np.arange(n) / n) ** 2


# --- contract / defaults -----------------------------------------------------------------------


def test_engine_defaults_match_the_contract_text() -> None:
    """The root schema has no defaults for the v0.2 fields; their descriptions name them."""
    import re

    for name, value in S.V02_DEFAULTS.items():
        text = V02_PROPS[name]["description"]
        m = re.search(r"filled by the engine for 0\.2 only\): (\S+)", text)
        assert m, name
        said = m.group(1).rstrip(".,;")
        expected = ("true" if value else "false") if isinstance(value, bool) else str(value)
        assert said == expected, (name, said)


def test_v01_form_has_no_new_keys_and_v02_form_has_all_of_them() -> None:
    r1 = resolve_clap_params({"schema_version": "0.1", "seed": 1})
    assert not set(S.V02_FIELDS) & set(r1)
    r2 = resolve_clap_params({**V2, "seed": 1, "rate_div": 3.0})
    assert {k: r2[k] for k in S.V02_FIELDS} == {**S.V02_DEFAULTS, "rate_div": 3}
    assert type(r2["rate_div"]) is int
    assert resolve_clap_params(r2) == r2


def test_v01_document_with_a_v02_field_is_refused_never_ignored() -> None:
    for field, value in ACTIVE.items():
        with pytest.raises(ClapParamsError):
            render_clap({"schema_version": "0.1", "seed": 1, field: value})
        with pytest.raises(ClapParamsError):
            render_clap({**V2, "seed": 1, field: value, "extra": 1})


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_all_off_is_byte_identical_to_the_v01_twin(seed: int) -> None:
    for extra in ({}, {"room": 0.5, "drive": 0.4, "offset_ms": 3, "sample_rate": 44100,
                       "bit_depth": 16}, {"gate_ms": 0, "tail_reverse": False, "ring_hz": 3000,
                                          "comb_hz": 100, "rate_div": 1}):
        a = render_clap({"schema_version": "0.1", "seed": seed, **{
            k: v for k, v in extra.items() if k not in S.V02_FIELDS}})[0]
        b = render_clap({**V2, "seed": seed, **extra})[0]
        assert a.tobytes() == b.tobytes()


@pytest.mark.parametrize("field", list(ACTIVE))
def test_every_new_field_changes_the_output(field: str) -> None:
    """A 0.2 document with a stage on is never silently ignored (reviewer finding, #289)."""
    kw = {**V2, "seed": 4, "length_ms": 1000, "tail_level": 1.0}
    off = render_clap(kw)[0]
    on = render_clap({**kw, field: ACTIVE[field]})[0]
    assert on.tobytes() != off.tobytes()


def test_documented_no_effect_cases() -> None:
    kw = {**V2, "seed": 4}
    base = render_clap(kw)[0].tobytes()
    assert render_clap({**kw, "ring_hz": 3000})[0].tobytes() == base  # ring_mix 0
    assert render_clap({**kw, "comb_hz": 4000})[0].tobytes() == base  # comb_fb 0
    short = {**kw, "length_ms": 200}  # gate 400 ms after the first burst: past the end
    assert render_clap({**short, "gate_ms": 400})[0].tobytes() == render_clap(short)[0].tobytes()
    # a gate that cuts before the tail starts (3 bursts x 11 ms = 33 ms): reverse has no segment
    gate_only = render_clap({**kw, "gate_ms": 20})[0].tobytes()
    assert render_clap({**kw, "gate_ms": 20, "tail_reverse": True})[0].tobytes() == gate_only


# --- stage references --------------------------------------------------------------------------


def _check_crush(fn) -> None:
    for seed in range(4):
        x = _noise(seed) * (0.3 + seed)
        for amount in (0.001, 0.25, 0.5, 0.77, 1.0):
            y = fn(x, amount)
            bits = 12 - 9 * amount
            peak = float(np.max(np.abs(x)))
            # different method: levels per side, nearest-level index, explicit loop
            levels = 2 ** (bits - 1)
            ref = np.array([round(v / peak * levels) / levels * peak for v in x.tolist()])
            assert np.allclose(y, ref, rtol=0, atol=1e-12 * peak), (seed, amount)
            assert np.max(np.abs(y - x)) <= peak / levels / 2 * (1 + 1e-9)  # half a step
    assert fn(x, 0.0) is x


def test_crush_matches_a_loop_reference() -> None:
    _check_crush(S.crush)


def test_crush_mutant() -> None:
    with pytest.raises(AssertionError):
        _check_crush(lambda x, a: S.crush(x, min(1.0, a * 1.02)))


def _check_rate_div(fn) -> None:
    for seed in range(3):
        x = _noise(seed, 1000)
        for f in (2, 3, 7, 16):
            y = fn(x, f)
            assert all(y[i] == x[i - i % f] for i in range(len(x))), (seed, f)
    assert fn(x, 1) is x


def test_rate_div_matches_a_loop_reference() -> None:
    _check_rate_div(S.rate_div)


def test_rate_div_mutant() -> None:
    with pytest.raises(AssertionError):
        _check_rate_div(lambda x, f: S.rate_div(x, max(1, f - 1)))


def _check_ring(fn) -> None:
    x = _noise(1, 3000)
    for hz, mix in ((20, 1.0), (440, 0.5), (3000, 0.8), (1234.5, 1.0)):
        y = fn(x, SR, hz, mix)
        ref = [(1 - mix) * v + mix * v * math.sin(2 * math.pi * hz * n / SR)
               for n, v in enumerate(x.tolist())]
        assert np.allclose(y, ref, atol=1e-12), (hz, mix)
    # different method: a pure tone at f0 ring-modulated at 1000 Hz has lines at |f0 -+ 1000|
    t = np.arange(SR) / SR
    tone = np.sin(2 * math.pi * 3000 * t)
    spec = np.abs(np.fft.rfft(fn(tone, SR, 1000, 1.0)))
    lines = sorted(np.argsort(spec)[-2:])
    assert lines == [2000, 4000]
    assert fn(x, SR, 440, 0.0) is x


def test_ring_matches_a_loop_reference_and_the_sideband_lines() -> None:
    _check_ring(S.ring)


def test_ring_mutant() -> None:
    with pytest.raises(AssertionError):
        _check_ring(lambda x, sr, hz, mix: S.ring(x, sr, hz * 1.02, mix))


def _check_comb(fn) -> None:
    for hz, fb, sr in ((200, 0.5, SR), (4000, 0.95, SR), (100, 0.9, 44100), (777, 0.3, SR)):
        x = _noise(2, 4000)
        d = int(round(sr / hz))
        ref = x.copy()
        for n in range(d, len(x)):
            ref[n] = x[n] + fb * ref[n - d]
        assert np.allclose(fn(x, sr, hz, fb), ref, atol=1e-12), (hz, fb)
    imp = np.zeros(2000)
    imp[0] = 1.0
    y = fn(imp, SR, 400, 0.6)  # delay 120: echoes 0.6 ** k
    assert [round(y[120 * k], 9) for k in range(4)] == [round(0.6**k, 9) for k in range(4)]
    assert np.count_nonzero(y) == 2000 // 120 + 1
    assert fn(imp, SR, 400, 0.0) is imp


def test_comb_matches_the_recurrence_and_the_impulse_response() -> None:
    _check_comb(S.comb)


def test_comb_mutant() -> None:
    with pytest.raises(AssertionError):
        _check_comb(lambda x, sr, hz, fb: S.comb(x, sr, hz, fb * 1.02))


def _check_gate(fn) -> None:
    n = 9600
    for ms in (5, 60, 123.4, 500):
        w = fn(n, SR, ms)
        cut = round(ms * SR / 1000)
        assert np.all(w[: max(0, cut - 48)] == 1.0)
        assert np.all(w[cut:] == 0.0)
        ramp = w[max(0, cut - 48) : min(cut, n)]
        assert np.all(np.diff(ramp) <= 0) and np.all((ramp >= 0) & (ramp <= 1))
        if cut <= n:
            assert w[cut - 1] == 0.0  # the fade reaches 0 at the last sample before the cut
    assert fn(n, SR, 0) is None


def test_gate_window_shape() -> None:
    _check_gate(S.gate_window)


def test_gate_mutant() -> None:
    def wrong(n, sr, ms):  # cut 1 ms late
        return S.gate_window(n, sr, ms + 1) if ms else None

    with pytest.raises(AssertionError):
        _check_gate(wrong)


def _check_reverse(fn) -> None:
    x = _noise(5, 5000)
    for start, end in ((400, 5000), (400, 3000), (1000, 1100)):
        y = fn(x, start, end, SR)
        f = min(48, start, (end - start) // 2)
        assert np.array_equal(y[: start - f], x[: start - f])
        assert np.array_equal(y[end:], x[end:])
        assert np.array_equal(y[start + f : end], x[start:end][::-1][f:])
        for v in (y[start - f : start], y[start : start + f]):  # faded through (almost) zero
            assert np.all(np.abs(v) <= np.abs(np.concatenate([x[start - f : start],
                                                              x[start:end][::-1][:f]])).max())
        assert abs(y[start - 1]) < abs(x[start - 1]) + 1e-15 and abs(y[start]) <= abs(x[end - 1])
    assert fn(x, 400, 401, SR) is x  # nothing to reverse


def test_reverse_tail_matches_slicing() -> None:
    _check_reverse(S.reverse_tail)


def test_reverse_mutant() -> None:
    with pytest.raises(AssertionError):
        _check_reverse(lambda x, s, e, sr: S.reverse_tail(x, s + 1, e, sr))


# --- fold --------------------------------------------------------------------------------------

F32 = kaiser_lowpass(32, 0.08, 10.0)


def _band_limit(x: np.ndarray, sr: int = SR, hz: float = 20000.0) -> np.ndarray:
    n = len(x)
    spec = np.fft.rfft(np.concatenate([x, np.zeros(n)]))
    spec[np.fft.rfftfreq(2 * n, 1.0 / sr) > hz] = 0.0
    return np.fft.irfft(spec, 2 * n)[:n]


def _fold_reference_32x(u: np.ndarray, amount: float) -> np.ndarray:
    """The same curve at 32x (the issue's reference): u + lowpass(w (sin(k pi v / 2) - v))."""
    k, w = 1 + 15 * amount, min(1.0, amount / 0.1)
    y = u + oversampled(u, 32, lambda v: w * (np.sin(k * math.pi * v / 2) - v), F32)
    y[0] = 0.0
    return y


def _fold_alias_db(fold_fn, p: dict, amount: float) -> float:
    a = render_clap(p)[0]
    u = a / np.max(np.abs(a))
    sr = p.get("sample_rate", SR)
    err = _band_limit(fold_fn(u, amount) - _fold_reference_32x(u, amount), sr)
    ref = _band_limit(_fold_reference_32x(u, amount), sr)
    cut = len(u) - round(0.006 * sr)
    ratio = np.sqrt(np.mean(err[:cut] ** 2)) / np.sqrt(np.mean(ref[:cut] ** 2))
    return 20 * math.log10(float(ratio))


ALIAS_CASES = [  # default voice, then bright and narrow at 44.1 kHz (smallest margin)
    ({"schema_version": "0.1", "seed": 1}, 1.0),
    ({"schema_version": "0.1", "seed": 2}, 0.4),
    ({"schema_version": "0.1", "seed": 3}, 0.1),
    ({"schema_version": "0.1", "seed": 1, "bp_hz": 4000, "bp_q": 0.5, "hp_hz": 2000,
      "sample_rate": 44100}, 1.0),
    ({"schema_version": "0.1", "seed": 2, "bp_hz": 3000, "bp_q": 0.5, "hp_hz": 1000,
      "sample_rate": 44100}, 0.7),
]


@pytest.mark.parametrize("p,amount", ALIAS_CASES, ids=[f"c{i}" for i in range(len(ALIAS_CASES))])
def test_fold_aliasing_against_a_32x_reference(p: dict, amount: float) -> None:
    assert _fold_alias_db(S.fold, p, amount) <= -68.0


def test_fold_alias_check_can_fail() -> None:
    def naive(u, amount):  # no oversampling
        k, w = 1 + 15 * amount, min(1.0, amount / 0.1)
        y = (1 - w) * u + w * np.sin(k * math.pi * u / 2)
        y[0] = 0.0
        return y

    assert _fold_alias_db(naive, *ALIAS_CASES[0]) > -68.0 + 20


def test_fold_pure_tone_matches_the_ideal_curve() -> None:
    """Independent of oversampling: a 1 kHz tone through sin(k pi u / 2) has the Bessel
    harmonics J_n(k pi / 2); the engine's harmonic levels agree with an FFT-ideal 16x curve."""
    t = np.arange(SR) / SR
    u = np.sin(2 * math.pi * 1000 * t) * np.minimum(1, np.minimum(t, 1 - t) / 0.01)
    for amount in (0.3, 1.0):
        k = 1 + 15 * amount
        spec = np.fft.rfft(np.concatenate([u, np.zeros(len(u))]))
        up = np.zeros(len(u) * 16 + 1, dtype=complex)
        up[: len(spec)] = spec
        v = np.fft.irfft(up, 2 * len(u) * 16) * 16
        r = np.fft.irfft(np.fft.rfft(np.sin(k * math.pi * v / 2))[: len(u) + 1] / 16,
                         2 * len(u))[: len(u)]
        err = (_band_limit(S.fold(u, amount)) - _band_limit(r))[500:-500]
        assert _rms_db(err) - _rms_db(_band_limit(r)[500:-500]) < -85


def test_fold_is_continuous_at_zero() -> None:
    """Lead note on #280 (a): the contract curve is not the identity at k = 1, so the engine
    crossfades it in. Output difference to fold 0 (dB re RMS, same seed, same peak) at tiny
    values, measured: 0.002 -> about -37, 0.005 -> -31, 0.01 -> -23, 0.02 -> -14.5; without the
    crossfade, 0.001 is already -6.4."""
    def err(f: float) -> float:
        a = render_clap({**V2, "seed": 1, "fold": f})[0]
        b = render_clap({**V2, "seed": 1})[0]
        return _rms_db(a - b) - _rms_db(b)

    values = [err(f) for f in (0.002, 0.005, 0.01, 0.02)]
    assert values == sorted(values)  # grows smoothly from zero
    assert values[0] < -33 and values[1] < -28 and values[3] < -10


def test_fold_continuity_check_can_fail(monkeypatch) -> None:
    monkeypatch.setattr(S, "FOLD_BLEND", 1e-9)  # no crossfade: the stage jumps on
    a = render_clap({**V2, "seed": 1, "fold": 0.002})[0]
    b = render_clap({**V2, "seed": 1})[0]
    assert _rms_db(a - b) - _rms_db(b) > -10


# --- order: sub-150 Hz energy (H-X4) -----------------------------------------------------------


def _sub150(a: np.ndarray, sr: int = SR) -> float:
    sp = np.abs(np.fft.rfft(a)) ** 2
    return float(sp[np.fft.rfftfreq(len(a), 1 / sr) < 150].sum() / sp.sum())


def _chain(stage, after_hp: bool, seed: int) -> float:
    p = resolve_clap_params({"schema_version": "0.1", "seed": seed})
    n = C.file_samples(p)
    x = biquad_bandpass(substreams(seed, 2)[0].standard_normal(n), SR, p["bp_hz"], p["bp_q"])
    x = x * C.envelope(p, n)
    x = stage(rbj_highpass(x, SR, p["hp_hz"])) if after_hp else rbj_highpass(stage(x), SR,
                                                                              p["hp_hz"])
    return _sub150(x - x.mean())


HX4 = {
    "rate_div16": lambda x: S.rate_div(x, 16),
    "ring1000": lambda x: S.ring(x, SR, 1000, 1.0),
    "ring3000": lambda x: S.ring(x, SR, 3000, 1.0),
}


@pytest.mark.parametrize("name", list(HX4))
def test_stages_before_the_highpass_keep_the_low_end_clean(name: str) -> None:
    """Measured (seeds 1-4 mean): before hp 0.00005-0.0002, after hp 0.014-0.055."""
    before = np.mean([_chain(HX4[name], False, s) for s in range(1, 5)])
    after = np.mean([_chain(HX4[name], True, s) for s in range(1, 5)])
    assert before <= 0.005 and after >= 0.01 and after > 20 * before


def test_render_keeps_the_stage_products_out_of_the_low_end() -> None:
    kw = {**V2, "seed": 2, "rate_div": 16, "ring_mix": 1.0, "ring_hz": 1000}
    assert _sub150(render_clap(kw)[0]) <= 0.005


# --- full-range property tests -------------------------------------------------------------------


def _draw(rng: np.random.Generator) -> dict:
    p: dict = {**V2, "seed": int(rng.integers(0, 2**32))}
    for name, prop in SCHEMA["properties"].items():
        if name in ("schema_version", "seed", "preset", "bpm", "variants"):
            continue
        if "enum" in prop:
            p[name] = prop["enum"][int(rng.integers(len(prop["enum"])))]
        elif prop["type"] == "integer":
            p[name] = int(rng.integers(prop["minimum"], prop["maximum"] + 1))
        else:
            pick = rng.random()
            p[name] = float(prop["minimum"] if pick < 0.08 else prop["maximum"] if pick < 0.16
                            else rng.uniform(prop["minimum"], prop["maximum"]))
    for name, prop in V02_PROPS.items():
        pick = rng.random()
        if name == "tail_reverse":
            p[name] = bool(rng.integers(2))
        elif name == "rate_div":
            p[name] = int(rng.choice([1, 16, int(rng.integers(1, 17))]))
        elif name == "gate_ms":
            p[name] = 0 if pick < 0.4 else float(rng.choice([5.0, 500.0, rng.uniform(5, 500)]))
        else:
            lo = prop["minimum"]
            hi = prop["maximum"]
            p[name] = float(lo if pick < 0.15 else hi if pick < 0.3 else rng.uniform(lo, hi))
    return p


RANDOM = [_draw(np.random.default_rng(2800 + i)) for i in range(24)]


@pytest.mark.parametrize("p", RANDOM, ids=[f"r{i}" for i in range(len(RANDOM))])
def test_random_full_range_invariants(p: dict) -> None:
    a, r = render_clap(p)
    assert a.tobytes() == render_clap(p)[0].tobytes()  # same parameters + seed, same bytes
    assert render_clap({**p, "seed": (p["seed"] + 1) % 2**32})[0].tobytes() != a.tobytes()
    sr, bits = r["sample_rate"], r["bit_depth"]
    assert len(a) == round(r["length_ms"] * sr / 1000) and np.all(np.isfinite(a))
    q = wav_samples(encode_wav(a, sr, bits)) / (2 ** (bits - 1) - 1)
    peak_db = 20 * math.log10(float(np.max(np.abs(q))))
    assert r["peak_ceiling_dbfs"] - 0.05 <= peak_db <= r["peak_ceiling_dbfs"] + 1e-9
    assert a[0] == 0.0 and a[-1] == 0.0
    assert abs(float(np.mean(a))) < 1e-3 * float(np.max(np.abs(a)))  # H-X5: no DC
    assert resolve_clap_params(r) == {**r, "variants": 1}
    v = clap_variants.make_variants(p, 3)
    assert render_clap(v[0])[0].tobytes() == a.tobytes()
    assert all(resolve_clap_params(x) == {**x, "variants": 1} for x in v)


def test_random_pre_highpass_stages_keep_the_low_end_clean() -> None:
    """Full range of crush, rate_div, ring and comb with a high-pass corner of 300 Hz or more
    (below that the high-pass itself passes the low end): measured worst 0.0011 of 60 draws."""
    rng = np.random.default_rng(2801)
    worst = 0.0
    for _ in range(24):
        p = _draw(rng)
        p.update(fold=0, drive=0, room=0, gate_ms=0, tail_reverse=False,
                 hp_hz=float(rng.uniform(300, 2000)), sample_rate=48000)
        worst = max(worst, _sub150(render_clap(p)[0]))
    assert worst <= 0.005, worst


def test_extreme_corners_stay_finite_at_the_ceiling() -> None:
    corner = {**V2, "seed": 9, "fold": 1, "crush": 1, "rate_div": 16, "ring_hz": 3000,
              "ring_mix": 1, "comb_hz": 100, "comb_fb": 0.95, "gate_ms": 5, "tail_reverse": True,
              "drive": 1, "room": 1, "length_ms": 2000, "bursts": 6}
    a, r = render_clap(corner)
    assert np.all(np.isfinite(a)) and abs(float(np.max(np.abs(a)))) <= 1.0
    assert render_clap({**corner, "gate_ms": 500})[0].tobytes() != a.tobytes()


# --- render-level behaviour of gate and reverse --------------------------------------------------


def test_gate_silences_everything_after_the_cut() -> None:
    kw = {**V2, "seed": 3, "length_ms": 1000, "tail_level": 1.0, "tail_decay_ms": 800}
    a = render_clap({**kw, "gate_ms": 100})[0]
    cut = round(0.1 * SR)
    # not exactly 0: the mean removal that follows the gate (contract order) subtracts a
    # Hann-shaped bump over the whole file; measured 7e-7 of the peak (about -123 dB)
    assert np.max(np.abs(a[cut:])) <= 1e-5 * np.max(np.abs(a))
    assert np.max(np.abs(a[cut - 480 : cut - 48])) > 1e-2 * np.max(np.abs(a))
    b = render_clap({**kw, "gate_ms": 100, "offset_ms": 10})[0]
    assert np.max(np.abs(b[cut + round(0.01 * SR) :])) <= 1e-5 * np.max(np.abs(b))  # counts
    # from the first burst, not from the file start


def test_reverse_puts_the_swell_at_the_end() -> None:
    kw = {**V2, "seed": 3, "length_ms": 700, "tail_level": 1.0, "tail_decay_ms": 300,
          "bursts": 1, "burst_decay_ms": 5}
    fwd = render_clap(kw)[0]
    rev = render_clap({**kw, "tail_reverse": True})[0]
    blk = lambda x, ms0, ms1: _rms_db(x[ms0 * SR // 1000 : ms1 * SR // 1000])  # noqa: E731
    assert blk(fwd, 50, 150) > blk(fwd, 500, 600) + 10  # forward: loud first, quiet last
    assert blk(rev, 500, 600) > blk(rev, 50, 150) + 10  # reversed: the other way round


def test_reverse_joint_has_no_click() -> None:
    worst = 0.0
    for seed in range(6):
        p = {**V2, "seed": seed, "tail_reverse": True, "tail_level": 1.0, "length_ms": 200,
             "tail_decay_ms": 800, "burst_decay_ms": 60, "bursts": 6, "burst_spacing_ms": 30}
        a = render_clap(p)[0]
        j = round(6 * 30 * SR / 1000)
        step = float(np.max(np.abs(np.diff(a[j - 20 : j + 20])))) if j + 20 < len(a) else 0.0
        worst = max(worst, step / float(np.max(np.abs(a))))
    assert worst < 0.5, worst  # a hard step would be close to the whole peak


# --- presets -------------------------------------------------------------------------------------

GOLDEN = {
    "xtreme-saturated": "0451f6f8c164593aa7f74b59d1e92c96240a36f519e6f3d8be90f7962b0662ca",
    "xtreme-folded": "1f3b63b6db97464d0a6fb96711967b5000143a696edcfd9e58466795b7aa9431",
    "xtreme-crushed": "6fd6ebe912d8c1c0dd786afd74a10956338111ce7f8c780da4b21d9c60ec8e53",
    "xtreme-metal": "0d26b570b1f9503d373fd2d23d51f1c2d61e2bf2f53c5f36c094e7ef4184c7d2",
    "xtreme-gated": "7d78cc5d6702f1e747361b725e2b0e36ac1c5c427334c7e7ca5343735990ed88",
    "xtreme-reversed": "fadcc117b69492215792377d9b8ef33086d2d9fe5bc9f125d4e2c5be266d77ca",
    "xtreme-wreck": "57b12ddc0485fb5367476ed6059ccc88ae5e1c2ded545c46679764a037b8f617",
}


def test_preset_family_is_listed_next_to_the_baseline() -> None:
    assert sorted(preset_names("clap")) == sorted(["default", "short", "long", "bright"] + XTREME)


@pytest.mark.parametrize("name", XTREME)
def test_extreme_presets_are_valid_and_pinned(name: str) -> None:
    p = load_preset(name, "clap")
    assert p["preset"] == name and p["schema_version"] == "0.2"
    r = resolve_clap_params(p)
    assert resolve_clap_params(r) == r
    wav, _, _ = render_sample_wav("clap", p)
    assert hashlib.sha256(wav).hexdigest() == GOLDEN[name]
    a = render_clap(p)[0]
    assert _sub150(a) <= 0.008  # measured: wreck 0.0075, folded 0.0035, others <= 0.0023
    vs = clap_variants.make_variants(p, 4)
    assert vs == clap_variants.make_variants(p, 4)
    assert render_clap(vs[0])[0].tobytes() == a.tobytes()
    assert render_clap(vs[1])[0].tobytes() != a.tobytes()


def test_metal_preset_keeps_the_low_end_clean() -> None:
    assert _sub150(render_clap(load_preset("xtreme-metal", "clap"))[0]) <= 0.005


def test_extreme_preset_sidecar_round_trip(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    _, side = write_sample("clap", load_preset("xtreme-wreck", "clap"), tmp_path,
                           created_at=datetime(2026, 11, 2, tzinfo=UTC))
    meta = json.loads(side.read_text(encoding="utf-8"))
    assert meta["parameters"]["schema_version"] == "0.2" and meta["parameters"]["fold"] == 0.3
    assert rerender_from_sidecar(side) == (tmp_path / "clap.wav").read_bytes()


def test_golden_all_fields_v02() -> None:
    p = {**V2, "seed": 9, "room": 0.6, "drive": 0.5, "offset_ms": 3, "polarity": -1,
         "sample_rate": 44100, "bit_depth": 16, "length_ms": 400, "fold": 0.5, "crush": 0.5,
         "rate_div": 3, "ring_hz": 700, "ring_mix": 0.5, "comb_hz": 900, "comb_fb": 0.5,
         "gate_ms": 250, "tail_reverse": True}
    wav, _, _ = render_sample_wav("clap", p)
    assert hashlib.sha256(wav).hexdigest() == (
        "13f630300193f1140babac8a924aeee0c0e4a762ff7195576586a588b943f513")
