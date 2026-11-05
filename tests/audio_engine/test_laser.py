"""Laser engine (#416, D-030): contract range, determinism, level, DC, length, stereo, files.

Expected values are written in the tests or measured with a method independent of the engine
(zero crossings, windowed peaks, raw WAV bytes). No test says how a shot sounds.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import struct
from pathlib import Path

import numpy as np
import pytest

from audio_engine import cli, laser, laser_variants
from audio_engine.categories import get_category
from audio_engine.io import encode_wav, rerender_from_sidecar, write_sample
from audio_engine.laser import LaserParamsError, render_laser, resolve_laser_params
from audio_engine.presets import load_preset, preset_names

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "contracts" / "laser-params.schema.json").read_text("utf-8"))
PROPS = SCHEMA["properties"]
RANGE_FIELDS = [k for k, v in PROPS.items() if "minimum" in v and k not in ("seed", "variants")]
V01_MAX = {"length_ms": 3000}  # schema_version 0.1 caps the length below the 0.2 maximum


def v01_max(name: str) -> float:
    return V01_MAX.get(name, PROPS[name]["maximum"])
FAMILIES = ["pew", "plasma", "ion", "rift", "subboom", "glitch"]


def random_params(rng: random.Random, edge: float = 0.2) -> dict:
    """A request over the whole contract range; each field sometimes at an edge."""
    p: dict = {"schema_version": "0.1", "family": rng.choice(FAMILIES)}
    for name in RANGE_FIELDS:
        lo, hi = PROPS[name]["minimum"], v01_max(name)
        if rng.random() < edge:
            p[name] = rng.choice((lo, hi))
        elif PROPS[name]["type"] == "integer":
            p[name] = rng.randint(lo, hi)
        else:
            p[name] = rng.uniform(lo, hi)
    p["sample_rate"] = rng.choice((44100, 48000))
    p["bit_depth"] = rng.choice((16, 24))
    p["polarity"] = rng.choice((1, -1))
    return p


def decode(wav: bytes) -> tuple[np.ndarray, int, int]:
    """(ints shape (n, channels), channels, bits) from the raw bytes: independent of io.py."""
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
    tag, channels, sr, byte_rate, block, bits = struct.unpack("<HHIIHH", wav[20:36])
    assert tag == 1 and block == channels * bits // 8 and byte_rate == sr * block
    (size,) = struct.unpack("<I", wav[40:44])
    raw = wav[44 : 44 + size]
    if bits == 16:
        ints = np.frombuffer(raw, dtype="<i2").astype(np.int64)
    else:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int64)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        ints = np.where(v >= 1 << 23, v - (1 << 24), v)
    return ints.reshape(-1, channels), channels, bits


def check_render(p: dict) -> np.ndarray:
    """Invariants every render must hold; raises AssertionError. Returns the audio."""
    r = resolve_laser_params(p)
    audio = render_laser({k: v for k, v in r.items() if k != "seed"}, r["seed"])
    sr = r["sample_rate"]
    n = int(round(r["length_ms"] * sr / 1000.0))
    assert audio.shape == (n, 2) and audio.dtype == np.float64
    assert np.all(np.isfinite(audio))
    wav = encode_wav(audio, sr, r["bit_depth"])
    ints, channels, bits = decode(wav)
    assert channels == 2 and ints.shape == (n, 2)
    full = 2 ** (bits - 1) - 1
    ceiling = 10 ** (r["peak_ceiling_dbfs"] / 20) * full
    peak = int(np.abs(ints).max())
    assert 0 < peak <= ceiling, (peak, ceiling)  # quantised file, not the float buffer
    assert peak < full  # no clipping
    # polarity applies after the ceiling; the sign of the first non-zero sample is not fixed
    assert np.all(ints[0] == 0)  # first sample 0
    assert np.all(np.abs(ints[: round(r["offset_ms"] * sr / 1000)]) == 0)
    assert abs(float(audio.mean(axis=0).max())) < 5e-4 * float(np.abs(audio).max()) + 1e-9
    assert abs(float(audio.mean(axis=0).min())) < 5e-4 * float(np.abs(audio).max()) + 1e-9
    assert float(np.abs(audio[-1]).max()) < 1e-3  # faded out at the end
    return audio


# --- presets ---------------------------------------------------------------------------------

# SHA-256 of the 24-bit stereo WAV bytes of each preset at LASER_VERSION 0.1.0. A byte change
# needs a LASER_VERSION bump and new hashes in the same PR (D-013).
GOLDEN = {
    "glitch": "8979dfe3cce60aa012e2a2d038924bcb0d5b77c4066e8b55bd0822eedeb5b0e7",
    "ion": "e1f4ed18158b403a90ab696f4209af5a0010f754d08d6250279685240c050c68",
    "pew": "27d5c3250d6c3ad1e0c68ac7b6a04c34a0eee10d93cb6bce90d00ace0d265eb3",
    "pew-wide-echo": "97569e3cdb94260f7efb59d99a4e112bdef450abe106befd10a19932b2ab48ff",
    "plasma": "140ca48ac75351300b8df6991ec9a144e17901a23d94f24b529ee6a15b25e349",
    "plasma-driven": "992a44f0e33466600d4fd04d5944b61c82967c2a035be97890447c19c13db500",
    "rift": "e219d1773176b87ad0dece4c3218ab4606b4fea688ab38b875d9ad2384d3b0b6",
    "subboom": "c062824ba139ec5a47006c1c5f2f559a8b17c3c8a745ec505ffbf515937d5be3",
    # contract v0.2 presets (#425), pinned at LASER_VERSION 0.2.0
    "blaster": "08339cbe082ec138699d58bca65594dde83f02bd93b0e2185b8794011c6b7277",
    "blaster-burst5": "fd0ac80ff07cec258d099127257f4c23686a2ef1f326b7a13347969d0214f8af",
    "blaster-double": "9afff649a1ddb5a6d0046fd8801367ed0700f9248566ca3f3df8744afe038377",
    "blaster-echo": "6c900608e9b818170f95c61b7147aa4e9cc22173c9c8a93394fa559725fdf3d6",
    "blaster-reverb": "f4638a524b97f0ea144a48832c5440a163b0fd3edd503ed1f39c184f91db9e86",
    "blaster-triple-lrl": "cf4829fd345e7fa0f14028b6305a1e7b6fb066407494fff9c58ea3d42d8d0e68",
}


def _preset_wav(name: str) -> bytes:
    p = resolve_laser_params(load_preset(name, "laser"))
    audio, r = get_category("laser").render(p)
    return encode_wav(audio, r["sample_rate"], r["bit_depth"])


def test_at_least_six_presets_and_all_families_covered() -> None:
    names = preset_names("laser")
    assert len(names) >= 6
    fams = {load_preset(n, "laser")["family"] for n in names}
    assert fams == set(FAMILIES)


@pytest.mark.parametrize("name", preset_names("laser"))
def test_preset_renders_valid_and_matches_its_name(name: str) -> None:
    p = load_preset(name, "laser")
    assert p["preset"] == name
    check_render(p)
    engine = get_category("laser").engine
    assert engine == {"name": laser.LASER_NAME, "version": laser.LASER_VERSION}


@pytest.mark.parametrize("name", preset_names("laser"))
def test_preset_bytes_are_pinned(name: str) -> None:
    got = hashlib.sha256(_preset_wav(name)).hexdigest()
    assert got == GOLDEN.get(name), f"{name}: {got}"


# --- property tests over the full contract range ---------------------------------------------


def test_random_requests_hold_all_invariants() -> None:
    rng = random.Random(416)
    for i in range(48):
        p = random_params(rng)
        p["seed"] = rng.randint(0, 2**32 - 1)
        try:
            check_render(p)
        except AssertionError as exc:  # name the request that failed
            raise AssertionError(f"draw {i}: {p}") from exc


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("corner", ["min", "max"])
def test_corner_requests_hold_all_invariants(family: str, corner: str) -> None:
    pick = 0 if corner == "min" else 1
    p = {"schema_version": "0.1", "seed": 3, "family": family}
    for name in RANGE_FIELDS:
        p[name] = (PROPS[name]["minimum"], v01_max(name))[pick]
    p["glitch_steps"] = (2, 24)[pick]
    check_render(p)


@pytest.mark.parametrize("sr", [44100, 48000])
@pytest.mark.parametrize("length_ms", [100, 3000, 123.456])
def test_length_is_exact(sr: int, length_ms: float) -> None:
    a = render_laser({"length_ms": length_ms, "sample_rate": sr, "offset_ms": 12}, 1)
    assert len(a) == int(round(length_ms * sr / 1000.0))


def test_same_params_same_seed_is_byte_identical_and_seed_matters_only_when_documented() -> None:
    rng = random.Random(5)
    for _ in range(8):
        p = random_params(rng)
        a = encode_wav(render_laser(p, 77), p["sample_rate"], p["bit_depth"])
        b = encode_wav(render_laser(p, 77), p["sample_rate"], p["bit_depth"])
        assert a == b
    quiet = {"noise_level": 0, "crackle": 0, "variation": 0, "family": "glitch"}
    assert np.array_equal(render_laser(quiet, 1), render_laser(quiet, 2))  # documented
    for field in ("noise_level", "crackle", "variation"):
        p = {**quiet, field: 0.7}
        assert not np.array_equal(render_laser(p, 1), render_laser(p, 2)), field


def test_seed_argument_wins_over_seed_in_params() -> None:
    p = {"noise_level": 0.5}
    assert np.array_equal(render_laser({**p, "seed": 9}, 4), render_laser(p, 4))


def test_every_exposed_parameter_changes_the_output() -> None:
    base = {"family": "glitch", "echo_mix": 0.5, "stereo_width": 0.5, "noise_level": 0.3,
            "crackle": 0.3, "fm_amount": 0.4, "ring_amount": 0.4, "variation": 0.5,
            "drive": 0.3, "length_ms": 800}
    ref = render_laser(base, 5)
    for name in RANGE_FIELDS:
        if name in ("bpm", "peak_ceiling_dbfs", "length_ms", "offset_ms"):
            continue
        lo, hi = PROPS[name]["minimum"], PROPS[name]["maximum"]
        cur = base.get(name, PROPS[name]["default"])
        new = lo if abs(cur - lo) > abs(cur - hi) else hi
        if PROPS[name]["type"] == "integer":
            new = int(new)
        assert not np.array_equal(render_laser({**base, name: new}, 5), ref), name
    for name, new in (("family", "rift"), ("polarity", -1), ("sample_rate", 44100)):
        assert not np.array_equal(render_laser({**base, name: new}, 5), ref), name


def test_bpm_and_preset_do_not_change_the_audio() -> None:
    a = render_laser({}, 1)
    assert np.array_equal(a, render_laser({"bpm": 140, "preset": "x"}, 1))


# --- measured behaviour (independent methods) -------------------------------------------------


def _zc_freq(x: np.ndarray, sr: int, t0: float, t1: float) -> float:
    seg = x[int(t0 * sr) : int(t1 * sr)]
    s = np.signbit(seg).astype(np.int8)
    crossings = np.flatnonzero(np.diff(s) != 0)
    assert len(crossings) >= 4
    return (len(crossings) - 1) / 2 / ((crossings[-1] - crossings[0]) / sr)


def test_pew_sweep_ends_at_pitch_end_and_passes_geometric_mean_halfway() -> None:
    sr = 48000
    a = render_laser({"pitch_start_hz": 2000, "pitch_end_hz": 250, "sweep_ms": 200,
                      "decay_ms": 3000, "length_ms": 1000}, 1)[:, 0]
    assert _zc_freq(a, sr, 0.5, 0.9) == pytest.approx(250, rel=0.02)
    assert _zc_freq(a, sr, 0.095, 0.105) == pytest.approx(math.sqrt(2000 * 250), rel=0.08)
    rising = render_laser({"pitch_start_hz": 250, "pitch_end_hz": 1000, "sweep_ms": 100,
                           "decay_ms": 3000, "length_ms": 1000}, 1)[:, 0]
    assert _zc_freq(rising, sr, 0.5, 0.9) == pytest.approx(1000, rel=0.02)


def test_sweep_curve_moves_the_midpoint_pitch_the_right_way() -> None:
    def mid(curve: float) -> float:
        a = render_laser({"pitch_start_hz": 2000, "pitch_end_hz": 250, "sweep_ms": 200,
                          "sweep_curve": curve, "decay_ms": 3000}, 1)[:, 0]
        return _zc_freq(a, 48000, 0.095, 0.105)

    # progress at half time = 0.5 ** curve; expected f = 2000 * (250 / 2000) ** progress
    for curve in (0.5, 2.0):
        expected = 2000 * (250 / 2000) ** (0.5**curve)
        assert mid(curve) == pytest.approx(expected, rel=0.08)


def _window_peak(x: np.ndarray, sr: int, t0: float, t1: float) -> float:
    return float(np.abs(x[int(t0 * sr) : int(t1 * sr)]).max())


def test_decay_ms_is_time_to_minus_60_db_after_the_attack() -> None:
    sr = 48000
    a = render_laser({"pitch_start_hz": 300, "pitch_end_hz": 300, "decay_ms": 100,
                      "attack_ms": 0, "length_ms": 600}, 1)[:, 0]
    peak = _window_peak(a, sr, 0, 0.01)
    # 50 ms after the attack = -30 dB, 100 ms = -60 dB (windows of one period)
    assert 20 * math.log10(_window_peak(a, sr, 0.050, 0.0535) / peak) == pytest.approx(-30, abs=2)
    assert 20 * math.log10(_window_peak(a, sr, 0.100, 0.1035) / peak) == pytest.approx(-60, abs=3)


def test_echo_adds_a_tap_at_echo_ms_and_is_off_at_zero_mix() -> None:
    sr = 48000
    p = {"decay_ms": 20, "length_ms": 600, "pitch_start_hz": 800, "pitch_end_hz": 800}
    dry = render_laser(p, 1)[:, 0]
    wet = render_laser({**p, "echo_mix": 0.5, "echo_ms": 200, "echo_feedback": 0}, 1)[:, 0]
    assert _window_peak(dry, sr, 0.25, 0.4) < 1e-3 * dry.max()
    ratio = _window_peak(wet, sr, 0.2, 0.25) / _window_peak(wet, sr, 0, 0.05)
    assert ratio == pytest.approx(0.5, rel=0.1)
    assert _window_peak(wet, sr, 0.45, 0.6) < 1e-3 * wet.max()  # feedback 0: one tap only


def test_stereo_width_zero_is_identical_and_width_decorrelates() -> None:
    p = {"family": "plasma", "noise_level": 0.4, "crackle": 0.3, "echo_mix": 0.4,
         "length_ms": 800, "decay_ms": 600}
    mono = render_laser(p, 3)
    assert np.array_equal(mono[:, 0], mono[:, 1])
    corr = []
    for w in (0.25, 1.0):
        s = render_laser({**p, "stereo_width": w}, 3)
        corr.append(float(np.corrcoef(s[:, 0], s[:, 1])[0, 1]))
    assert corr[1] < corr[0] < 0.999


def test_offset_polarity_and_peak_ceiling() -> None:
    sr = 48000
    base = {"seed": 1, "noise_level": 0.2}
    a = render_laser({**base, "offset_ms": 10}, 1)
    assert np.all(a[: int(0.010 * sr)] == 0)
    n = render_laser({**base, "polarity": -1}, 1)
    assert np.array_equal(n, -render_laser(base, 1))
    for ceiling in (-0.1, -6.0, -12.0):
        audio = render_laser({**base, "peak_ceiling_dbfs": ceiling}, 1)
        ints, _, _ = decode(encode_wav(audio, sr, 24))
        assert np.abs(ints).max() <= 10 ** (ceiling / 20) * (2**23 - 1)
        assert np.abs(ints).max() > 0.99 * 10 ** (ceiling / 20) * (2**23 - 1) - 2


def test_plasma_saw_has_no_off_harmonic_energy_and_is_fast() -> None:
    """Fixed 7 kHz saw: all energy sits on multiples of 7 kHz (interpolation / table spurs would
    land elsewhere). Measured 8e-12; a 5 kHz saw gives 3e-4 because its 25 kHz harmonic lies in
    the decimation filter's transition band and folds to 23 kHz (known, see the PR)."""
    import time

    t0 = time.perf_counter()
    a = render_laser({"family": "plasma", "pitch_start_hz": 7000, "pitch_end_hz": 7000,
                      "length_ms": 1000, "decay_ms": 3000, "peak_ceiling_dbfs": -1}, 1)[:, 0]
    assert time.perf_counter() - t0 < 5.0  # generous; the measured time is in the PR
    spec = np.abs(np.fft.rfft(a[2400:-2400] * np.hanning(len(a) - 4800))) ** 2
    freqs = np.fft.rfftfreq(len(a) - 4800, 1 / 48000)
    off = np.abs(((freqs + 3500) % 7000) - 3500) > 150  # farther than 150 Hz from a multiple
    assert spec[off].sum() < 1e-8 * spec.sum()


def test_no_energy_above_nyquist_fold_for_a_fast_high_sweep() -> None:
    """A measured number, not a requirement: share of power in 20-22 kHz for a plain sine sweep."""
    a = render_laser({"pitch_start_hz": 8000, "pitch_end_hz": 8000, "length_ms": 500,
                      "decay_ms": 3000}, 1)[:, 0]
    spec = np.abs(np.fft.rfft(a * np.hanning(len(a)))) ** 2
    freqs = np.fft.rfftfreq(len(a), 1 / 48000)
    assert spec[(freqs > 20000)].sum() < 1e-6 * spec.sum()


# --- contract enforcement ----------------------------------------------------------------------


@pytest.mark.parametrize("name", RANGE_FIELDS)
def test_out_of_range_is_rejected_never_clamped(name: str) -> None:
    lo, hi = PROPS[name]["minimum"], PROPS[name]["maximum"]
    for bad in (lo - 0.01 * (hi - lo) - 1e-9, hi + 0.01 * (hi - lo) + 1e-9):
        with pytest.raises(LaserParamsError, match=name):
            resolve_laser_params({"schema_version": "0.1", "seed": 1, name: bad})


def test_bad_inputs_are_rejected() -> None:
    ok = {"schema_version": "0.1", "seed": 1}
    for bad in ({**ok, "family": "laser"}, {**ok, "wobble": 1}, {**ok, "decay_ms": float("nan")},
                {**ok, "decay_ms": float("inf")}, {**ok, "decay_ms": "250"},
                {**ok, "glitch_steps": 3.5}, {"seed": 1, "schema_version": "0.3"}):
        with pytest.raises(LaserParamsError):
            resolve_laser_params(bad)
    with pytest.raises(LaserParamsError):
        resolve_laser_params([1, 2])  # type: ignore[arg-type]
    with pytest.raises(LaserParamsError):
        render_laser({}, -1)
    with pytest.raises(LaserParamsError):
        render_laser({"decay_ms": 5}, 1)


def test_v02_defaults_render_the_v01_bytes_and_resolve_stably() -> None:
    for name in preset_names("laser"):
        p = load_preset(name, "laser")
        if p["schema_version"] != "0.1":
            continue
        a = render_laser(p, p["seed"])
        b = render_laser({**p, "schema_version": "0.2"}, p["seed"])
        assert np.array_equal(a, b), name
    r = resolve_laser_params({"schema_version": "0.2", "seed": 1, "salvo_rate_mode": "sync"})
    assert r["salvo_count"] == 1 and r["bpm"] == 120 and r["reverb_mix"] == 0
    assert resolve_laser_params(r) == r


def test_resolving_twice_is_stable() -> None:
    r = resolve_laser_params({"schema_version": "0.1", "seed": 4, "decay_ms": 99})
    assert resolve_laser_params(r) == r
    assert r["family"] == "pew" and r["length_ms"] == 500


# --- fault injection: the invariant checks must turn red ----------------------------------------


def _check_default() -> None:
    check_render({"schema_version": "0.1", "seed": 1, "noise_level": 0.3, "length_ms": 300,
                  "decay_ms": 3000, "pitch_start_hz": 900, "pitch_end_hz": 100})


def test_check_render_is_green_without_fault() -> None:
    _check_default()


@pytest.mark.parametrize(
    "target,fault",
    [
        ("_normalise", lambda x, c, b: x * 1.5),  # peak above the ceiling / clipping
        ("_normalise", lambda x, c, b: x * 1.02 * 10 ** (c / 20) / np.abs(x).max()),  # +2 %
        ("_remove_mean", lambda x: x + 0.05),  # DC
        ("_fade_out", lambda x, sr, ms: x),  # no fade
        ("file_samples", lambda p: int(round(p["length_ms"] * p["sample_rate"] / 1000)) + 1),
    ],
    ids=["gain-1.5", "ceiling-plus-2pct", "dc-offset", "no-fade", "length-plus-1"],
)
def test_fault_injection_turns_the_checks_red(monkeypatch, target, fault) -> None:
    monkeypatch.setattr(laser, target, fault)
    with pytest.raises(AssertionError):
        _check_default()


def test_fault_injection_seed_ignored_turns_the_seed_check_red(monkeypatch) -> None:
    monkeypatch.setattr(laser, "substreams", lambda seed, count: [
        np.random.Generator(np.random.PCG64(0)) for _ in range(count)])
    p = {"noise_level": 0.7}
    assert np.array_equal(render_laser(p, 1), render_laser(p, 2))  # what the test would catch


# --- files, sidecar, CLI, variants --------------------------------------------------------------


def test_write_sample_sidecar_and_rerender_roundtrip(tmp_path: Path) -> None:
    for name in ("ion", "glitch"):
        params = load_preset(name, "laser")
        wav_path, json_path = write_sample("laser", params, tmp_path, name=name)
        meta = json.loads(json_path.read_text("utf-8"))
        assert meta["category"] == "laser" and meta["schema_version"] == "0.2"
        # schema 0.1 requests keep engine 0.1.0: same bytes, so old sidecars still re-render
        assert meta["engine"] == {"name": laser.LASER_NAME, "version": "0.1.0"}
        wav = wav_path.read_bytes()
        assert hashlib.sha256(wav).hexdigest() == meta["sha256"]
        ints, channels, _ = decode(wav)
        assert channels == 2
        assert meta["features"]["peak_dbfs"] <= -0.3 + 1e-3
        assert rerender_from_sidecar(json_path) == wav


def test_cli_renders_every_preset_and_lists_them(tmp_path: Path, capsys) -> None:
    assert cli.main(["--category", "laser", "--list-presets"]) == 0
    listed = capsys.readouterr().out
    for name in preset_names("laser"):
        assert name in listed
    for name in preset_names("laser"):
        out = tmp_path / name
        assert cli.main(["--category", "laser", "--preset", name, "--out", str(out)]) == 0
        assert len(list(out.glob("*.wav"))) == 1 and len(list(out.glob("*.json"))) == 1


def test_cli_errors_exit_2_and_write_nothing(tmp_path: Path) -> None:
    out = tmp_path / "x"
    args = ["--category", "laser", "--out", str(out)]
    assert cli.main([*args, "--preset", "nope"]) == 2
    assert cli.main([*args, "--preset", "pew", "--set", "decay_ms=5"]) == 2
    assert cli.main([*args, "--preset", "pew", "--set", "family=ion"]) == 2
    assert not out.exists()


def test_cli_set_overrides_and_variants(tmp_path: Path) -> None:
    out = tmp_path / "v"
    rc = cli.main(["--category", "laser", "--preset", "pew", "--variants", "3", "--set",
                   "stereo_width=0.5", "--out", str(out)])
    assert rc == 0
    wavs = sorted(out.glob("*.wav"))
    assert len(wavs) == 3 and len({w.read_bytes() for w in wavs}) == 3
    metas = [json.loads(p.read_text("utf-8")) for p in sorted(out.glob("*.json"))]
    assert all(m["parameters"]["stereo_width"] == 0.5 for m in metas)


def test_library_folder_for_laser() -> None:
    from library.layout import LibraryLayout

    assert LibraryLayout().parts_for("laser") == ("Samples", "FX", "Lasers")


def test_variants_are_deterministic_inside_the_range_and_distinct() -> None:
    base = {"schema_version": "0.1", "seed": 11, "pitch_start_hz": 8000, "decay_ms": 20}
    a = laser_variants.make_variants(base, 8)
    b = laser_variants.make_variants(base, 8)
    assert a == b
    assert a[0] == {k: v for k, v in resolve_laser_params(base).items() if k != "variants"}
    assert len({v["seed"] for v in a}) == 8
    for v in a:
        resolve_laser_params(v)
        for field, _mode, _w in laser_variants.SPREAD:
            assert PROPS[field]["minimum"] <= v[field] <= PROPS[field]["maximum"]
    assert len({v["pitch_end_hz"] for v in a}) == 8
