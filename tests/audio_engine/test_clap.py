"""Clap voice (#231): contract, determinism, parameter effects, aliasing, golden hashes.

References are written in the test (expected directions, a sample-by-sample energy sum, an
ideal 16x oversampled drive), not taken from the engine's own helpers.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

import audio_engine.clap as C
from audio_engine import clap_variants
from audio_engine.categories import get_category
from audio_engine.clap import ClapParamsError, render_clap, resolve_clap_params
from audio_engine.io import (
    EngineVersionMismatch,
    encode_wav,
    render_sample_wav,
    rerender_from_sidecar,
    wav_samples,
    write_sample,
)
from audio_engine.presets import load_preset, preset_names

SCHEMA = json.loads(C.CLAP_SCHEMA_FILE.read_text(encoding="utf-8"))
PROPS = SCHEMA["properties"]
NUMERIC = [k for k, v in PROPS.items() if v.get("type") in ("number", "integer")]
BASE = {"schema_version": "0.1", "seed": 5}
STAMP = datetime(2026, 11, 2, 12, 0, 0, tzinfo=UTC)


def _draw(rng: np.random.Generator) -> dict:
    """One random parameter set over the whole contract range (endpoints included now and then)."""
    p: dict = {"schema_version": "0.1", "seed": int(rng.integers(0, 2**32))}
    for name, prop in PROPS.items():
        if name in ("schema_version", "seed", "preset", "bpm", "variants"):
            continue
        if "enum" in prop:
            p[name] = prop["enum"][int(rng.integers(len(prop["enum"])))]
        elif prop["type"] == "integer":
            p[name] = int(rng.integers(prop["minimum"], prop["maximum"] + 1))
        else:
            pick = rng.random()
            p[name] = float(
                prop["minimum"] if pick < 0.08 else prop["maximum"] if pick < 0.16
                else rng.uniform(prop["minimum"], prop["maximum"])
            )
    return p


RANDOM = [_draw(np.random.default_rng(900 + i)) for i in range(16)]


# --- contract ---------------------------------------------------------------------------------


def test_defaults_are_filled_and_resolving_twice_changes_nothing() -> None:
    r = resolve_clap_params(BASE)
    for name, prop in PROPS.items():
        if "default" in prop:
            assert r[name] == prop["default"]
    assert resolve_clap_params(r) == r
    assert "variants" in r  # batch-only: dropped by render_clap, not by resolve
    assert "variants" not in render_clap(BASE)[1]


@pytest.mark.parametrize("field", NUMERIC)
def test_every_numeric_bound_is_enforced_not_clamped(field: str) -> None:
    prop = PROPS[field]
    for edge in (prop["minimum"], prop["maximum"]):
        assert resolve_clap_params({**BASE, field: edge})[field] == edge
    for bad in (prop["minimum"] - 1e-6, prop["maximum"] + 1e-6):
        if prop["type"] == "integer":
            bad = int(prop["minimum"] - 1) if bad < prop["minimum"] else int(prop["maximum"] + 1)
        with pytest.raises(ClapParamsError, match=field):
            resolve_clap_params({**BASE, field: bad})


@pytest.mark.parametrize(
    "bad",
    [{"nope": 1}, {"bit_depth": 20}, {"polarity": 0}, {"bursts": 2.5}, {"room": float("nan")},
     {"seed": -1}, {"drive": True}, {"bp_hz": "1300"}],
)
def test_bad_values_are_rejected(bad: dict) -> None:
    with pytest.raises(ClapParamsError):
        resolve_clap_params({**BASE, **bad})
    with pytest.raises(ClapParamsError):
        resolve_clap_params({"seed": 1})  # schema_version missing


def test_whole_number_floats_become_ints() -> None:
    r = resolve_clap_params({**BASE, "seed": 7.0, "bursts": 4.0, "polarity": -1.0})
    assert (r["seed"], r["bursts"], r["polarity"]) == (7, 4, -1)
    assert all(type(r[k]) is int for k in ("seed", "bursts", "polarity"))


# --- determinism, wrong-audio failures over the whole range -----------------------------------


@pytest.mark.parametrize("p", RANDOM, ids=[f"r{i}" for i in range(len(RANDOM))])
def test_random_full_range_invariants(p: dict) -> None:
    a, r = render_clap(p)
    again, _ = render_clap(p)
    assert a.tobytes() == again.tobytes()  # same parameters + seed -> same samples
    assert render_clap({**p, "seed": (p["seed"] + 1) % 2**32})[0].tobytes() != a.tobytes()
    sr, bits = r["sample_rate"], r["bit_depth"]
    assert len(a) == round(r["length_ms"] * sr / 1000)
    assert np.all(np.isfinite(a))
    q = wav_samples(encode_wav(a, sr, bits)) / (2 ** (bits - 1) - 1)
    peak_db = 20 * math.log10(float(np.max(np.abs(q))))
    assert r["peak_ceiling_dbfs"] - 0.05 <= peak_db <= r["peak_ceiling_dbfs"] + 1e-9
    assert a[0] == 0.0 and a[-1] == 0.0  # no click at the edges
    assert abs(float(np.mean(a))) < 1e-3 * float(np.max(np.abs(a)))  # no DC offset
    assert resolve_clap_params(r) == {**r, "variants": 1}  # re-resolving a sidecar's form


def test_worst_case_render_time() -> None:
    p = {**BASE, "length_ms": 2000, "room": 1, "room_length_ms": 800, "drive": 1, "bursts": 6}
    start = time.perf_counter()
    render_clap(p)
    elapsed = time.perf_counter() - start
    assert elapsed < 3.0, elapsed  # measured about 0.1 s on the dev box; generous for CI


# --- every parameter moves its analysis value --------------------------------------------------

SR = 48000
FX = {"schema_version": "0.1", "length_ms": 800, "tail_level": 0.5, "tail_decay_ms": 200}


def _measure(a: np.ndarray) -> dict[str, float]:
    energy = a**2
    spec = np.abs(np.fft.rfft(a)) ** 2
    f = np.fft.rfftfreq(len(a), 1 / SR)
    return {
        "centroid": float(np.sum(f * spec) / np.sum(spec)),
        "hf": float(np.sum(spec[f > 8000]) / np.sum(spec)),
        "low": float(np.sum(spec[f < 500]) / np.sum(spec)),
        "early40": float(np.sum(energy[: SR * 40 // 1000]) / np.sum(energy)),
        "late100": float(np.sum(energy[SR // 10 :]) / np.sum(energy)),
    }


# field, low, high, measured quantity, expected direction of (high - low). Directions follow
# from the voice description in the contract; each held for all four seeds when written.
EFFECTS = [
    ("tail_decay_ms", 60, 600, "late100", +1),
    ("tail_level", 0.0, 1.0, "early40", -1),
    ("bp_hz", 600, 3500, "centroid", +1),
    ("bp_q", 0.5, 8, "centroid", -1),
    ("hp_hz", 150, 1800, "low", -1),
    ("drive", 0.0, 1.0, "hf", +1),
    ("bursts", 1, 6, "early40", -1),
    ("burst_spacing_ms", 3, 30, "early40", -1),
    ("burst_decay_ms", 6, 55, "early40", +1),
    ("burst_level_falloff", 0.5, 1.0, "early40", +1),
    ("room", 0.0, 1.0, "late100", +1),
    ("room_length_ms", 100, 800, "late100", +1),
]


@pytest.mark.parametrize("field,lo,hi,what,sign", EFFECTS, ids=[e[0] for e in EFFECTS])
def test_parameter_moves_its_measured_value(field, lo, hi, what, sign) -> None:
    for seed in range(4):
        extra = {"room": 0.8} if field == "room_length_ms" else {}
        values = [
            _measure(render_clap({**FX, **extra, "seed": seed, field: v})[0])[what]
            for v in (lo, hi)
        ]
        assert sign * (values[1] - values[0]) > 0.05 * abs(values[0]) + 1e-4, (seed, values)


def test_tail_decay_sets_the_measured_slope() -> None:
    """Level fall of the tail in dB per second = 60 / tail_decay_s, regression over 10 ms RMS
    blocks (independent of the engine's envelope code)."""
    for decay_ms in (150.0, 300.0, 600.0):
        slopes = []
        for seed in range(3):
            p = {**FX, "seed": seed, "bursts": 1, "burst_decay_ms": 5, "tail_level": 1.0,
                 "tail_decay_ms": decay_ms, "length_ms": 1200, "bp_q": 0.7}
            a = render_clap(p)[0]
            t0, t1 = 60, 60 + min(int(decay_ms * 0.7), 400)  # ms after the first burst
            blocks = [a[SR * s // 1000 : SR * (s + 10) // 1000] for s in range(t0, t1, 10)]
            level = [10 * math.log10(float(np.mean(b**2))) for b in blocks]
            mid = [t0 + 5 + 10 * i for i in range(len(level))]
            slopes.append(-np.polyfit(np.array(mid) / 1000, level, 1)[0])
        # measured within 0.6 % of the contract value
        assert np.mean(slopes) == pytest.approx(60 / (decay_ms / 1000), rel=0.025)


@pytest.mark.parametrize("hp", [500.0, 1000.0, 1800.0])
def test_highpass_corner_is_where_the_contract_says(hp: float) -> None:
    """Same seed and envelope, hp_hz = hp against hp_hz = 100: the spectral ratio is the
    high-pass alone. 2nd order Butterworth: -3.01 dB at hp, 1/(1+16) = -12.3 dB at hp/2,
    relative to 8*hp where it is flat (analytic values, not engine code)."""
    kw = {**FX, "seed": 3, "length_ms": 2000, "tail_level": 1.0, "bp_q": 0.5}
    hi = np.abs(np.fft.rfft(render_clap({**kw, "hp_hz": hp})[0])) ** 2
    lo = np.abs(np.fft.rfft(render_clap({**kw, "hp_hz": 100})[0])) ** 2
    f = np.fft.rfftfreq(2 * SR, 1 / SR)

    def level(at: float) -> float:
        band = (f > 0.95 * at) & (f < 1.05 * at)
        return 10 * math.log10(float(np.sum(hi[band]) / np.sum(lo[band])))

    ref = level(8 * hp)
    assert level(hp) - ref == pytest.approx(-3.01, abs=0.35)
    assert level(hp / 2) - ref == pytest.approx(-12.3, abs=0.5)


def test_file_fields_do_what_they_say() -> None:
    a, r = render_clap({**FX, "seed": 1})
    assert len(a) == 38400
    off = render_clap({**FX, "seed": 1, "offset_ms": 12})[0]
    assert np.all(off[: 576] == 0.0) and np.any(off[576:] != 0.0)
    neg = render_clap({**FX, "seed": 1, "polarity": -1})[0]
    assert np.array_equal(neg, -a)
    wav, _, _ = render_sample_wav("clap", {**FX, "seed": 1, "sample_rate": 44100, "bit_depth": 16})
    assert wav[24:28] == (44100).to_bytes(4, "little") and wav[34:36] == (16).to_bytes(2, "little")


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
            m.setattr(C, "_normalise", lambda x, ceiling, bits: x)
            if fn is not None:
                m.setattr(C, "_drive", fn)
            return render_clap(p)[0]

    test, ref = render(drive_fn), render(_ideal_drive)
    sr = p.get("sample_rate", 48000)
    cut = len(ref) - round(0.006 * sr)
    err = (_band_limit(test, sr) - _band_limit(ref, sr))[:cut]
    return 20 * math.log10(math.sqrt(float(np.mean(err**2))) / float(np.max(np.abs(ref))))


ALIAS_CASES = [  # bright, narrow-in-time, full drive at 44.1 kHz first (smallest margin)
    {"seed": 1, "drive": 1.0, "bp_hz": 4000, "bp_q": 0.5, "hp_hz": 2000, "sample_rate": 44100},
    {"seed": 2, "drive": 1.0, "bp_hz": 3000, "bp_q": 0.5, "hp_hz": 1000, "sample_rate": 44100},
    {"seed": 3, "drive": 0.6, "bp_hz": 2000, "bp_q": 2.0, "hp_hz": 800},
    {"seed": 4, "drive": 0.1},
]


@pytest.mark.parametrize("extra", ALIAS_CASES, ids=lambda e: f"s{e['seed']}")
def test_drive_aliasing_stays_under_the_kick_bound(monkeypatch, extra) -> None:
    db = _alias_db(monkeypatch, {**BASE, **extra})
    assert db <= LIMIT_DB, db


def test_the_alias_check_can_fail(monkeypatch) -> None:
    """Guards the check: a drive that saturates at the base rate (no oversampling) is far over."""
    def naive(x, drive):
        g = 10.0 * drive**0.8
        y = np.tanh(g * x) / math.tanh(g)
        y[0] = 0.0
        return y

    assert _alias_db(monkeypatch, {**BASE, **ALIAS_CASES[0]}, naive) > LIMIT_DB + 20


# --- golden hashes -----------------------------------------------------------------------------

GOLDEN_VERSION = "0.1.0"
GOLDEN = {
    "preset-default": (lambda: load_preset("default", "clap"),
                       "dfedda70d564b7fecd1090e508b9b65fb32e62bbfc9c5f98d5f446aa17bcbebb"),
    "preset-short": (lambda: load_preset("short", "clap"),
                     "ef5c3f0a787b2d38155854045346b998a82002a067b09e2888364933f82f8e38"),
    "preset-long": (lambda: load_preset("long", "clap"),
                    "3d239f8d23665ffe11d86f3d4e341057e539649b4a5333729ab5c56daacd608a"),
    "preset-bright": (lambda: load_preset("bright", "clap"),
                      "33d103fa8c073826515ae08add8ac37622f38adae6adf4b649c7ec1d204d4259"),
    # every non-default field family: room, drive, offset, polarity, 44.1 kHz, 16 bit
    "all-fields-44k1-16bit": (
        lambda: {"schema_version": "0.1", "seed": 9, "room": 0.6, "drive": 0.5, "offset_ms": 3,
                 "polarity": -1, "sample_rate": 44100, "bit_depth": 16, "length_ms": 300},
        "4e2bffa5bf1577c47a21a51fba52ff4cfd054cc2ca466d1f201f41cd611e5f68"),
}


def test_golden_hashes_belong_to_the_version() -> None:
    assert C.CLAP_VERSION == GOLDEN_VERSION, (
        "clap engine bytes changed: bump CLAP_VERSION (D-013) and update GOLDEN in this file"
    )
    assert get_category("clap").engine == {"name": "abeltongod-audio-engine-clap",
                                           "version": GOLDEN_VERSION}


@pytest.mark.parametrize("name", GOLDEN)
def test_golden_sha256(name: str) -> None:
    params, expected = GOLDEN[name]
    wav, _, _ = render_sample_wav("clap", params())
    assert hashlib.sha256(wav).hexdigest() == expected


# --- sidecar, re-render, presets, variants -----------------------------------------------------


def test_sidecar_round_trip(tmp_path: Path) -> None:
    wav_path, json_path = write_sample("clap", load_preset("short", "clap"), tmp_path,
                                       created_at=STAMP)
    meta = json.loads(json_path.read_text(encoding="utf-8"))
    assert wav_path.name == "clap.wav"
    assert meta["category"] == "clap" and meta["schema_version"] == "0.2"
    assert meta["engine"] == {"name": "abeltongod-audio-engine-clap", "version": C.CLAP_VERSION}
    assert meta["features"]["spectral_centroid_hz"] > 0 and "fundamental_hz" not in meta["features"]
    assert rerender_from_sidecar(json_path) == wav_path.read_bytes()
    meta["engine"]["version"] = "9.9.9"
    json_path.write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(EngineVersionMismatch):
        rerender_from_sidecar(json_path)


def test_clap_engine_version_is_independent_of_the_kick(tmp_path: Path, monkeypatch) -> None:
    from audio_engine.io import write_kick
    wav, side = write_kick({"schema_version": "0.3", "seed": 4}, tmp_path, "k", created_at=STAMP)
    monkeypatch.setattr(C, "CLAP_VERSION", "9.9.9")
    assert rerender_from_sidecar(side) == wav.read_bytes()


@pytest.mark.parametrize("name", ["default", "short", "long", "bright"])
def test_presets_are_valid_contract_objects(name: str) -> None:
    p = load_preset(name, "clap")
    assert p["preset"] == name
    assert resolve_clap_params(p)["preset"] == name
    assert sorted(preset_names("clap")) == ["bright", "default", "long", "short"]
    assert "short" not in preset_names("kick")  # clap presets do not leak into the kick list


@pytest.mark.parametrize("p", RANDOM[:8], ids=[f"r{i}" for i in range(8)])
def test_variants_stay_in_the_contract_and_are_reproducible(p: dict) -> None:
    vs = clap_variants.make_variants(p, 5)
    assert vs == clap_variants.make_variants(p, 5)
    assert vs[0] == {k: v for k, v in resolve_clap_params(p).items() if k != "variants"}
    assert len({v["seed"] for v in vs}) == 5
    for v in vs:
        assert resolve_clap_params(v) == {**v, "variants": 1}
        assert v["preset"] == vs[0].get("preset") if "preset" in vs[0] else True
    base = render_clap(p)[0].tobytes()
    assert render_clap(vs[0])[0].tobytes() == base  # variant 0 is the base, byte for byte
    assert render_clap(vs[1])[0].tobytes() != base


def test_envelope_has_the_burst_spacing_falloff_and_tail_start_of_the_contract() -> None:
    """Direct check of the envelope with hand-computed values (no noise involved).

    3 bursts 10 ms apart, falloff 0.5, burst decay 20 ms to -60 dB, tail from 30 ms (one
    spacing after the last burst onset) at level 0.4, 100 ms to -60 dB. A component with
    onset s and level L is L * 10 ** (-3 * (t - s) / decay) once it has risen (0.3 ms), 0 before.
    """
    p = resolve_clap_params({**BASE, "bursts": 3, "burst_spacing_ms": 10.0, "burst_decay_ms": 20.0,
                             "burst_level_falloff": 0.5, "tail_level": 0.4,
                             "tail_decay_ms": 100.0})
    env = C.envelope(p, SR // 10)

    def at(ms: float) -> float:
        assert (ms * SR / 1000) % 1 == 0, "pick times that fall on a sample"
        return float(env[round(ms * SR / 1000)])

    def burst(level: float, onset: float, t: float) -> float:  # onset, t in ms
        return level * 10 ** (-3 * (t - onset) / 20.0)

    def tail(t: float) -> float:
        return 0.4 * 10 ** (-3 * (t - 30.0) / 100.0)

    exp = 1e-9
    assert at(0.0) == 0.0 and at(5.0) == pytest.approx(burst(1, 0, 5), abs=exp)
    assert at(9.875) == pytest.approx(burst(1, 0, 9.875), abs=exp)            # burst 1 not started
    assert at(15.0) == pytest.approx(burst(1, 0, 15) + burst(0.5, 10, 15), abs=exp)
    # just before the tail starts: bursts only
    assert at(29.875) == pytest.approx(
        burst(1, 0, 29.875) + burst(0.5, 10, 29.875) + burst(0.25, 20, 29.875), abs=exp)
    assert at(40.0) == pytest.approx(
        burst(1, 0, 40) + burst(0.5, 10, 40) + burst(0.25, 20, 40) + tail(40), abs=exp)
    assert at(90.0) == pytest.approx(
        burst(1, 0, 90) + burst(0.5, 10, 90) + burst(0.25, 20, 90) + tail(90), abs=exp)
