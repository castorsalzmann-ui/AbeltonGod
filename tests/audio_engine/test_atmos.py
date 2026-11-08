"""Atmos engine (#529, D-034): seamless loops and one-shots of four kinds.

Expected values are written here or computed by the independent reference in
``atmos_reference.py`` (other methods, see its docstring), never by the engine's own helpers.
Render sizes are kept to one or two bars at high tempo so the file stays fast on CI; the length
rule is checked over the whole contract range without rendering.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from fractions import Fraction
from pathlib import Path

import atmos_reference as ref
import numpy as np
import pytest
from jsonschema import Draft202012Validator

import audio_engine.atmos as A
from audio_engine import atmos_variants
from audio_engine.atmos import (
    AtmosConvergenceError,
    AtmosParamsError,
    render_atmos,
    resolve_atmos_params,
)
from audio_engine.categories import get_category
from audio_engine.cli import main as cli_main
from audio_engine.io import encode_wav, rerender_from_sidecar
from audio_engine.presets import describe, load_preset, preset_names

ROOT = Path(__file__).resolve().parents[2]
META_V = Draft202012Validator(
    json.loads((ROOT / "contracts/sample-metadata.schema.json").read_text("utf-8")))
SCHEMA = json.loads((ROOT / "contracts/atmos-params.schema.json").read_text("utf-8"))
KINDS = ("noise_bed", "drone", "resonant", "granular")
BASE = {"schema_version": "0.1", "seed": 5, "bpm": 200, "bars": 1, "max_tuning_cents": 20}
LSB24 = 1.0 / (2 ** 23 - 1)


def _render(params: dict) -> tuple[np.ndarray, dict]:
    return render_atmos(params)


# --- resolution and cross-field rules ------------------------------------------------------------


def test_kind_defaults_resolve_as_the_contract_table() -> None:
    # hand-written from the contract's allOf branches
    expected = {
        "noise_bed": (150, 8000, "lp", 3000, 2, 1, 2, 0.3),
        "drone": (20, 6000, "off", 1000, 1, 0, 0, 0.35),
        "resonant": (20, 10000, "lp", 4000, 1, 0.5, 2, 0.3),
        "granular": (100, 12000, "off", 2000, 1, 0, 2, 0.4),
    }
    for kind, values in expected.items():
        p = resolve_atmos_params({"schema_version": "0.1", "seed": 1, "bpm": 135, "kind": kind})
        got = tuple(p[k] for k in ("hp_hz", "lp_hz", "filter_mode", "filter_hz", "move_cycles",
                                   "move_depth_oct", "amp_move_db", "reverb_mix"))
        assert got == values, kind
        assert p["bars"] == 8 and p["loop_mode"] == "seamless" and p["intervals"] == [0, 7, 12]
        assert resolve_atmos_params(p) == p  # resolving a resolved form changes nothing
    omitted = resolve_atmos_params({"schema_version": "0.1", "seed": 1, "bpm": 135})
    assert omitted["kind"] == "noise_bed" and omitted["hp_hz"] == 150


REJECTED = {
    "rule A: 32 bars at 100 BPM": ({"bars": 32, "bpm": 100}, ("rule A", "72000")),
    # 16 bars at 100 BPM = 38.4 s loop; with 64 tail beats 76.8 s > 72 s
    "rule A: oneshot tail counts": ({"bars": 16, "bpm": 100, "loop_mode": "oneshot",
                                     "tail_beats": 64}, ("rule A", "tail_beats")),
    "rule B": ({"hp_hz": 1000, "lp_hz": 1400}, ("lp_hz", "rule B")),
    "rule C: drone note 24 at 1 bar": ({"kind": "drone", "bars": 1, "bpm": 200, "note": 24,
                                        "max_tuning_cents": 5}, ("rule C", "-10.79", "note 24")),
    "rule C: granular metal": ({"kind": "granular", "granular_source": "metal", "bars": 1,
                                "bpm": 200, "note": 24, "max_tuning_cents": 5}, ("rule C",)),
    "rule D: low end": ({"filter_hz": 30, "move_depth_oct": 2}, ("rule D", "filter_hz")),
    "rule D: high end": ({"filter_hz": 20000}, ("rule D",)),
    "rule E: 1-bar oneshot with default fades": (
        {"loop_mode": "oneshot", "bars": 1},
        ("rule E", "fade_in_beats 4", "fade_out_beats 4", "at least 2 bars")),
    "bpm NaN": ({"bpm": float("nan")}, ("bpm", "finite")),
    "cents inf": ({"cents": float("inf")}, ("cents", "finite")),
    "bars 3": ({"bars": 3}, ("bars",)),
    "intervals without root": ({"intervals": [7, 12]}, ("intervals",)),
    "unknown field": ({"cutoff_start_hz": 100}, ("cutoff_start_hz",)),
}


@pytest.mark.parametrize("name", REJECTED)
def test_rejected_requests_name_the_fields(name: str) -> None:
    change, needles = REJECTED[name]
    params = {"schema_version": "0.1", "seed": 1, "bpm": 135, **change}
    with pytest.raises(AtmosParamsError) as err:
        resolve_atmos_params(params)
    for needle in needles:
        assert needle in str(err.value), (needle, str(err.value))


def test_resonant_is_not_checked_by_rule_c() -> None:
    p = resolve_atmos_params({**BASE, "kind": "resonant", "note": 24, "max_tuning_cents": 0.5})
    assert p["kind"] == "resonant"


# --- length over the whole range (point 1) -------------------------------------------------------


def _expected_frames(bars, bpm, sr, mode="seamless", tail=0.0) -> int:
    beats = Fraction(4 * bars) + (Fraction(tail) if mode == "oneshot" else 0)
    return round(beats * 60 * sr / Fraction(bpm))  # exact, round half to even


def test_loop_length_examples_by_hand() -> None:
    p = {"bars": 1, "bpm": 128, "sample_rate": 44100, "loop_mode": "seamless", "tail_beats": 0}
    assert A.loop_samples(p) == 82688  # 82687.5 -> even
    assert A.loop_samples({**p, "bpm": 200, "sample_rate": 48000}) == 57600
    assert A.loop_samples({**p, "bars": 8, "bpm": 140, "sample_rate": 48000}) == 658286
    assert A.file_samples({**p, "bpm": 200, "sample_rate": 48000, "loop_mode": "oneshot",
                           "tail_beats": 2}) == 86400


def check_length_over_range(_render_unused=None) -> None:
    rng = np.random.default_rng(5290)
    for _ in range(3000):
        bars = int(rng.choice([1, 2, 4, 8, 16, 32]))
        bpm = float(rng.uniform(60, 200)) if rng.random() < 0.8 else float(rng.integers(60, 201))
        sr = int(rng.choice([44100, 48000]))
        tail = int(rng.integers(0, 257)) / 4
        mode = "oneshot" if rng.random() < 0.5 else "seamless"
        p = {"bars": bars, "bpm": bpm, "sample_rate": sr, "loop_mode": mode, "tail_beats": tail}
        assert A.loop_samples(p) == _expected_frames(bars, bpm, sr), p
        assert A.file_samples(p) == _expected_frames(bars, bpm, sr, mode, tail), p
    # rendered shapes at a few points (seamless and oneshot)
    for extra in ({"bpm": 187.3}, {"bpm": 191, "sample_rate": 44100},
                  {"bpm": 200, "loop_mode": "oneshot", "tail_beats": 1.75, "fade_in_beats": 1,
                   "fade_out_beats": 1}):
        audio, p = render_atmos({**BASE, "reverb_mix": 0, **extra})
        assert audio.shape == (_expected_frames(1, p["bpm"], p["sample_rate"], p["loop_mode"],
                                                p["tail_beats"]), 2)


def test_length_over_the_whole_range() -> None:
    check_length_over_range()


# --- independent re-render of the seamless loop within 1 LSB ------------------------------------

RERENDER = {
    "noise_bed lp smooth_random pan pump": {"kind": "noise_bed"},
    "noise_bed bp 3 cycles": {"kind": "noise_bed", "filter_mode": "bp", "filter_q": 4,
                              "filter_hz": 800, "move_depth_oct": 2, "move_cycles": 3,
                              "move_shape": "sine"},
    "noise_bed hp 44.1k": {"kind": "noise_bed", "filter_mode": "hp", "filter_hz": 500,
                           "sample_rate": 44100, "bpm": 190, "stereo_width": 1},
    "drone drift": {"kind": "drone", "drift_db": 6, "move_cycles": 2},
    "drone detune no drift": {"kind": "drone", "drift_db": 0, "detune_bins": 3},
    "resonant q80": {"kind": "resonant", "res_q": 80},
    "granular drone pitch": {"kind": "granular", "grain_pitch_cents": 300},
    "granular noise long grains": {"kind": "granular", "granular_source": "noise",
                                   "grain_ms": 300},
    "granular metal": {"kind": "granular", "granular_source": "metal", "note": 60},
}
RERENDER_COMMON = {**BASE, "pan_move": 0.4, "pump_depth": 0.5, "move_shape": "smooth_random"}


def _scaled_reference(p: dict) -> np.ndarray:
    r = ref.render(p)
    full = 2 ** (p["bit_depth"] - 1) - 1
    return r * ((10 ** (p["peak_ceiling_dbfs"] / 20) - 0.5 / full) / np.max(np.abs(r)))


def check_rerender(case: str = "noise_bed bp 3 cycles") -> float:
    audio, p = render_atmos({**RERENDER_COMMON, **RERENDER[case]})
    err = float(np.max(np.abs(audio - _scaled_reference(p)))) * (2 ** (p["bit_depth"] - 1) - 1)
    assert err < 1.0, (case, err)
    return err


@pytest.mark.parametrize("case", RERENDER)
def test_independent_rerender_within_one_lsb(case: str) -> None:
    err = check_rerender(case)
    print(f"{case}: max deviation {err:.4f} LSB")


# --- seam continuity -----------------------------------------------------------------------------

SINE = {**BASE, "kind": "drone", "note": 33, "intervals": [0], "partials": 1, "detune_bins": 0,
        "drift_db": 0, "reverb_mix": 0, "mono_below_hz": 0, "amp_move_db": 0}


def check_tonal_seam(_unused=None) -> None:
    """One bin-locked sine: the wrap x[N-1] -> x[0] continues the sine recurrence (E6)."""
    audio, p = render_atmos(SINE)
    n = len(audio)
    b = round(ref.f0(p) * n / p["sample_rate"])
    w = 2 * math.pi * b / n
    x = audio[:, 0]
    predicted = 2 * math.cos(w) * x[-1] - x[-2]
    interior = 2 * math.cos(w) * x[1:-1] - x[:-2] - x[2:]
    assert abs(x[0] - predicted) < 1e-9, abs(x[0] - predicted)
    assert np.max(np.abs(interior)) < 1e-9  # the same recurrence holds inside the loop


def test_tonal_seam_step() -> None:
    check_tonal_seam()


def _click_db(x: np.ndarray, sr: int) -> tuple[float, float, float]:
    """First-difference energy of a 5 ms window centred on the wrap of [x, x], and the lowest
    and highest of the windows inside the loop, each in dB against their median (research note
    section 3). The interior windows themselves span about +-5 dB on these files (measured,
    #529), so the seam window is compared with their range, not with a fixed +-3 dB."""
    w = int(round(0.005 * sr))
    d = np.diff(np.concatenate([x, x]), axis=0)
    energy = np.sum(d * d, axis=1)
    n = len(x)
    at_seam = float(np.sum(energy[n - w // 2: n + w // 2]))
    # interior: away from the wrap by two windows, so a filtered seam step does not reach it
    windows = energy[: (n // w) * w].reshape(-1, w).sum(axis=1)[2:-2]
    med = float(np.median(windows))
    return tuple(10 * math.log10(v / med) for v in (at_seam, windows.min(), windows.max()))


def check_noise_click(_unused=None) -> None:
    for kind in ("noise_bed", "resonant"):
        for seed in (1, 2, 3):
            audio, p = render_atmos({**BASE, "kind": kind, "seed": seed})
            seam, lo, hi = _click_db(audio, p["sample_rate"])
            assert lo <= seam <= hi, (kind, seed, seam, lo, hi)


def test_noise_seam_click() -> None:
    check_noise_click()


# --- warm-up guard (point 8) ---------------------------------------------------------------------

TIGHT = {**BASE, "bpm": 188.4, "kind": "noise_bed", "hp_hz": 20, "lp_hz": 200,
         "filter_mode": "lp", "filter_hz": 20, "filter_q": 12, "move_depth_oct": 0,
         "reverb_mix": 0, "pump_depth": 0, "amp_move_db": 0}


@pytest.mark.parametrize("bpm, mode, periods", [(188.4, "lp", 3), (188.4, "bp", 3),
                                                  (200, "lp", 4)])
def test_warm_up_at_the_tight_point_converges(bpm: float, mode: str, periods: int) -> None:
    """20 tau / T_loop = 2.9985 at 188.4 BPM (P = 3 gives only 20 tau), 3.18 at 200 (P = 4)."""
    params = {**TIGHT, "bpm": bpm, "filter_mode": mode}
    audio, p = render_atmos(params)
    assert A.preroll_filter(p) == periods
    err = float(np.max(np.abs(audio - _scaled_reference(p)))) / LSB24
    assert err < 1.0, err


def test_guard_refuses_without_warm_up(monkeypatch) -> None:
    monkeypatch.setattr(A, "preroll_filter", lambda p: 0)
    with pytest.raises(AtmosConvergenceError, match="moving filter"):
        render_atmos({**BASE, "kind": "noise_bed", "reverb_mix": 0})
    monkeypatch.undo()
    monkeypatch.setattr(A, "preroll_reverb", lambda p: 0)
    with pytest.raises(AtmosConvergenceError, match="reverb"):
        render_atmos({**BASE, "kind": "drone"})


def test_guard_refusal_writes_no_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(A, "preroll_reverb", lambda p: 0)
    code = cli_main(["--category", "atmos", "--preset", "air-bed", "--set", "bars=1",
                     "--set", "bpm=200", "--out", str(tmp_path / "o")])
    assert code == 2
    assert not (tmp_path / "o").exists() or not list((tmp_path / "o").iterdir())


# --- one-shots (point 10) ------------------------------------------------------------------------


def test_oneshot_fades_end_at_the_musical_end_and_the_tail_rings() -> None:
    dry = {**BASE, "loop_mode": "oneshot", "bars": 2, "fade_in_beats": 1, "fade_out_beats": 2,
           "tail_beats": 4, "reverb_mix": 0, "filter_mode": "off", "mono_below_hz": 0}
    audio, p = render_atmos(dry)
    n = A.loop_samples(p)
    spb = 60 * 48000 / 200
    assert audio.shape == (n + int(4 * spb), 2)
    assert np.all(audio[0] == 0) and np.all(audio[n:] == 0)  # fade from 0, silent tail
    assert np.max(np.abs(audio[int(spb): n - int(2 * spb)])) > 0.1
    late = np.max(np.abs(audio[n - int(spb / 8): n]))  # last 1/16 of the fade-out
    assert late < 0.1 * np.max(np.abs(audio))
    wet, _ = render_atmos({**dry, "reverb_mix": 0.5})
    assert np.max(np.abs(wet[n + int(spb):])) > 1e-3  # the reverb rings into the tail
    assert np.all(wet[-1] == 0)  # 5 ms end fade


# --- determinism, golden hashes ------------------------------------------------------------------

GOLDEN_VERSION = "0.1.0"
GOLDEN: dict[str, dict] = {
    "noise_bed": {**BASE, "kind": "noise_bed"},
    "noise_bed bp pan pump 44.1k 16 bit": {**RERENDER_COMMON, **RERENDER["noise_bed bp 3 cycles"],
                                          "sample_rate": 44100, "bit_depth": 16, "bpm": 190},
    "drone": {**BASE, "kind": "drone", "bars": 2},
    "resonant": {**BASE, "kind": "resonant"},
    "granular drone": {**BASE, "kind": "granular"},
    "granular metal": {**BASE, "kind": "granular", "granular_source": "metal", "note": 60,
                       "grain_pitch_cents": 200},
    "oneshot noise_bed": {**BASE, "loop_mode": "oneshot", "bars": 2, "tail_beats": 2},
}
GOLDEN_SHA = {  # pinned on Linux x86_64, NumPy 2.5.3; CI checks the same table on Windows
    "noise_bed": "40927cfa4f4ef3f667de936fdf763236d8f0b63e99399e2e7728fcd374ba6fbc",
    "noise_bed bp pan pump 44.1k 16 bit":
        "0540ab498a443b7df84be1c63da7bc31924575414bc3a35622b8625914c6ef03",
    "drone": "ef3840e2b6294471882d1141f9a41cf00ec07c82a58a0db6c9e547bdbaef3f7f",
    "resonant": "b0f9f48e8715d32681d098c5b0483189f6d5e56b886c6c832881bb82a9da4116",
    "granular drone": "d0b05d8b6d6c2af33cb072f29752ec4799f5419d16f3c1aa4caa8d95203669b2",
    "granular metal": "a73ad57a0d2dd31ab41c303f38825d4da3c9e707f8aa67297892a6566bd81339",
    "oneshot noise_bed": "3e0b056fbbc57dafa1d95f57a726aab7e7e889247833ec3f4b43527988722fce",
}


def _wav(params: dict) -> bytes:
    audio, p = render_atmos(params)
    return encode_wav(audio, p["sample_rate"], p["bit_depth"])


def test_golden_table_is_complete_and_version_pinned() -> None:
    assert A.ATMOS_VERSION == GOLDEN_VERSION, (
        "atmos engine bytes changed: bump ATMOS_VERSION (D-013) and update GOLDEN_SHA here")
    assert set(GOLDEN_SHA) == set(GOLDEN)


@pytest.mark.parametrize("name", GOLDEN)
def test_golden_sha256(name: str) -> None:
    first = _wav(GOLDEN[name])
    assert _wav(copy.deepcopy(GOLDEN[name])) == first  # same params, same bytes
    assert hashlib.sha256(first).hexdigest() == GOLDEN_SHA[name]


# --- random draws over the contract range --------------------------------------------------------


def _draw(rng: np.random.Generator) -> dict:
    props = SCHEMA["properties"]
    while True:
        p = {"schema_version": "0.1", "seed": int(rng.integers(0, 2**32))}
        for name, prop in props.items():
            if name in ("schema_version", "seed", "variants", "preset") or rng.random() < 0.3:
                continue
            if name == "intervals":
                k = int(rng.integers(1, 7))
                p[name] = [0, *sorted(rng.choice(np.arange(1, 37), k - 1, replace=False).tolist())]
            elif "enum" in prop:
                p[name] = prop["enum"][int(rng.integers(len(prop["enum"])))]
            elif prop["type"] == "integer":
                p[name] = int(rng.integers(prop["minimum"], prop["maximum"] + 1))
            else:
                lo, hi = prop["minimum"], prop["maximum"]
                pick = rng.random()
                v = lo if pick < 0.08 else hi if pick < 0.16 else float(rng.uniform(lo, hi))
                step = prop.get("multipleOf")
                p[name] = round(v / step) * step if step else v
        # short files keep CI fast; the length rule has its own full-range test
        p["bars"] = int(rng.choice([1, 2]))
        p["bpm"] = float(rng.uniform(150, 200))
        p["tail_beats"] = min(p.get("tail_beats", 0), 4)
        try:
            resolve_atmos_params(p)
        except AtmosParamsError:
            continue
        return p


RANDOM = [_draw(np.random.default_rng(5291 + i)) for i in range(10)]


@pytest.mark.parametrize("params", RANDOM, ids=[f"r{i}" for i in range(len(RANDOM))])
def test_random_contract_range_renders_valid_files(params: dict) -> None:
    audio, p = render_atmos(params)
    assert audio.shape == (A.file_samples(p), 2) and np.all(np.isfinite(audio))
    wav = encode_wav(audio, p["sample_rate"], p["bit_depth"])
    full = 2 ** (p["bit_depth"] - 1) - 1
    ints = np.round(np.clip(audio, -1, 1) * full)
    ceiling = 10 ** (p["peak_ceiling_dbfs"] / 20) * full
    assert ceiling - 1.0 <= np.max(np.abs(ints)) <= ceiling, p  # point 12
    meta = {"schema_version": "0.2", "file": "atmos.wav", "category": "atmos",
            "engine": {"name": A.ATMOS_NAME, "version": A.ATMOS_VERSION}, "parameters": p,
            "features": A.analyse_atmos(audio, p["sample_rate"], p),
            "created_at": "2026-11-09T12:00:00+00:00"}
    META_V.validate(meta)
    assert encode_wav(render_atmos(params)[0], p["sample_rate"], p["bit_depth"]) == wav


# --- sidecar features ----------------------------------------------------------------------------


def test_sidecar_features_by_hand() -> None:
    p = resolve_atmos_params({**BASE, "kind": "drone", "note": 24, "detune_bins": 2})
    audio = np.zeros((A.loop_samples(p), 2))
    audio[0] = 0.5
    f = A.analyse_atmos(audio, 48000, p)
    assert f["loop_samples"] == 57600 and f["loop_samples_exact"] == 57600.0
    assert f["seamless"] is True and f["preroll_loops"] == {"filter": 0, "reverb": 8}
    # note 24 = 32.7032 Hz lands on bin 39 of 0.8333 Hz: 32.5 Hz, -10.79 cents (#528 review)
    assert f["tuning_error_cents"] == pytest.approx(-10.79, abs=0.01)
    assert f["realised_detune_cents"] == pytest.approx(1200 * math.log2(41 / 39), abs=1e-3)
    q = resolve_atmos_params({**BASE, "loop_mode": "oneshot", "bars": 2, "bpm": 140})
    g = A.analyse_atmos(np.full((A.file_samples(q), 2), 0.1), 48000, q)
    assert g["seamless"] is False and g["preroll_loops"] == {"filter": 0, "reverb": 0}
    assert g["tuning_error_cents"] is None and g["realised_detune_cents"] is None
    assert g["loop_samples"] == 164571 and g["loop_samples_exact"] == pytest.approx(164571.4286)


# --- presets, variants, CLI, registry ------------------------------------------------------------

PRESETS = ("air-bed", "dark-bed", "drone-octaves-e1", "drone-root-fifth", "granular-drone",
           "granular-metal", "pumping-bed", "resonant-bed")


def test_presets_cover_every_kind_at_135_bpm() -> None:
    assert preset_names("atmos") == sorted(PRESETS)
    kinds = set()
    for name in PRESETS:
        raw = load_preset(name, "atmos")
        assert raw["preset"] == name and raw["bpm"] == 135
        kinds.add(resolve_atmos_params(raw)["kind"])  # also checks rules A-E
        assert "set bpm to the track's tempo" in describe(name, "atmos")
    assert kinds == set(KINDS)


def test_variants_change_only_the_seed() -> None:
    base = {**BASE, "kind": "drone"}
    v = atmos_variants.make_variants(base, 4)
    assert v[0] == {k: x for k, x in resolve_atmos_params(base).items() if k != "variants"}
    assert len({x["seed"] for x in v}) == 4
    for x in v[1:]:
        assert {k for k in x if x[k] != v[0][k]} == {"seed"}
    assert atmos_variants.make_variants(base, 4) == v


def test_cli_renders_atmos_and_the_sidecar_re_renders(tmp_path: Path, capsys) -> None:
    code = cli_main(["--category", "atmos", "--preset", "drone-root-fifth", "--set", "bars=2",
                     "--set", "bpm=200", "--set", "intervals=[0,7]", "--set",
                     "loop_mode=seamless", "--variants", "2", "--out", str(tmp_path)])
    assert code == 0
    sidecars = sorted(tmp_path.glob("*.json"))
    assert len(sidecars) == 2
    meta = json.loads(sidecars[0].read_text("utf-8"))
    META_V.validate(meta)
    assert meta["parameters"]["intervals"] == [0, 7] and meta["features"]["loop_samples"] == 115200
    assert meta["engine"] == {"name": "abeltongod-audio-engine-atmos", "version": "0.1.0"}
    assert rerender_from_sidecar(sidecars[0]) == sidecars[0].with_suffix(".wav").read_bytes()
    capsys.readouterr()
    bad = tmp_path / "bad"
    assert cli_main(["--category", "atmos", "--preset", "air-bed", "--set", "loop_mode=oneshot",
                     "--set", "bars=1", "--out", str(bad)]) == 2
    assert "rule E" in capsys.readouterr().err and not bad.exists()


def test_registry_and_library_folder(tmp_path: Path) -> None:
    from library import place_sample

    cat = get_category("atmos")
    assert (cat.engine_name, cat.metadata_schema_version) == (A.ATMOS_NAME, "0.2")
    wav = place_sample("atmos", {**BASE, "reverb_mix": 0}, tmp_path)
    assert wav.relative_to(tmp_path).parts[:2] == ("Samples", "Atmos")
    META_V.validate(json.loads(wav.with_suffix(".json").read_text("utf-8")))


# --- fault injection: each main check must fail on a broken engine -------------------------------


def _off_bin(orig):
    def drone_spectrum(p, n):  # the first partial 0.01 bins off the grid, as a free sine
        b = round(ref.f0(p) * n / p["sample_rate"]) + 0.01
        x = np.sin(2 * np.pi * b * np.arange(n) / n)
        return np.fft.rfft(np.stack([x, x], axis=1), axis=0)
    return drone_spectrum


def _random_walk(orig):
    def noise_spectrum(p, n):
        w = np.cumsum(np.random.default_rng(p["seed"]).standard_normal((n, 2)), axis=0)
        return np.fft.rfft(w - w.mean(axis=0), axis=0)
    return noise_spectrum


MUTANTS = {
    "frames: bpm x1.02": ("loop_samples", lambda f: lambda p: f({**p, "bpm": p["bpm"] * 1.02}),
                          check_length_over_range, False),
    "N + 1 frames": ("loop_samples", lambda f: lambda p: f(p) + 1, check_length_over_range,
                     False),
    "partial 0.01 bins off": ("drone_spectrum", _off_bin, check_tonal_seam, False),
    "no filter pre-roll (guard off)": ("preroll_filter", lambda f: lambda p: 0, check_rerender,
                                       True),
    "no reverb pre-roll (guard off)": ("preroll_reverb", lambda f: lambda p: 0,
                                       lambda: check_rerender("drone drift"), True),
    "movement 3 -> 3.01 cycles": (
        "movement_curve",
        lambda f: lambda p, n: np.sin(2 * np.pi * (p["move_cycles"] + 0.01) * np.arange(n) / n),
        check_rerender, False),
    "random-walk noise cut to length": ("noise_spectrum", _random_walk, check_noise_click,
                                        False),
}


@pytest.mark.parametrize("name", MUTANTS)
def test_mutant_is_caught(name: str, monkeypatch) -> None:
    target, factory, check, guard_off = MUTANTS[name]
    monkeypatch.setattr(A, target, factory(getattr(A, target)))
    if guard_off:
        monkeypatch.setattr(A, "_converged", lambda *a, **k: None)
    with pytest.raises(AssertionError):
        check()


def test_guard_mutant_is_caught(monkeypatch) -> None:
    """With the guard switched off, the refusal checked above no longer happens."""
    monkeypatch.setattr(A, "_converged", lambda *a, **k: None)
    monkeypatch.setattr(A, "preroll_filter", lambda p: 0)
    with pytest.raises(pytest.fail.Exception):
        with pytest.raises(AtmosConvergenceError):
            render_atmos({**BASE, "kind": "noise_bed", "reverb_mix": 0})
