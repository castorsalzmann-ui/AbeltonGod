"""Listening test 3 package (#103): file list, determinism, levels, K5 sidecars."""

from __future__ import annotations

import hashlib
import json

import pytest

from audio_engine import listening_test3 as lt3
from audio_engine.io import rerender_from_sidecar, wav_samples

EXPECTED_FILES = sorted(
    [f"K0_{c}.wav" for c in "AB"] + [f"K1_{c}.wav" for c in "ABC"]
    + [f"K2_{c}.wav" for c in "AB"] + [f"K3_{c}.wav" for c in "AB"]
    + [f"K4_{c}.wav" for c in "AB"] + [f"K5_{c}.wav" for c in "ABCD"] + ["Schluessel.md"]
)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    a = tmp_path_factory.mktemp("lt3_a") / "out"
    b = tmp_path_factory.mktemp("lt3_b") / "out"
    return a, lt3.write_package(a), b, lt3.write_package(b)


def test_file_list(built):
    out = built[0]
    assert sorted(p.name for p in (out / "package").iterdir()) == EXPECTED_FILES
    # 4 bars at 136 BPM = 16 beats = 7.0588 s, mono 48 kHz / 24 bit
    wav = (out / "package" / "K1_A.wav").read_bytes()
    assert len(wav_samples(wav)) == 338824
    assert wav[24:28] == (48000).to_bytes(4, "little") and wav[34:36] == (24).to_bytes(2, "little")


def test_same_run_twice_is_byte_identical(built):
    a, _, b, _ = built
    for name in EXPECTED_FILES:
        assert (a / "package" / name).read_bytes() == (b / "package" / name).read_bytes(), name


def test_levels_and_control(built):
    report = built[1]
    assert all(v <= -0.3 for v in report["peak_dbfs"].values())
    assert all(v < 0.1 for v in report["rms_spread_db"].values()), report["rms_spread_db"]
    pkg = built[0] / "package"
    assert (pkg / "K0_A.wav").read_bytes() == (pkg / "K0_B.wav").read_bytes()
    assert report["k0_identical"]


def test_levels_measured_from_files_on_disk(built):
    # independent of measure(): read the written files and apply the plan's 0.1 dB limit
    import numpy as np

    pkg = built[0] / "package"
    for block in ("K1", "K2", "K3", "K4", "K5"):
        levels = []
        for path in sorted(pkg.glob(f"{block}_*.wav")):
            x = wav_samples(path.read_bytes()) / 2.0**23
            start = int(np.flatnonzero(np.abs(x) >= 0.1 * np.abs(x).max())[0])
            levels.append(10 * np.log10(np.mean(x[start : start + 4800] ** 2)))
        assert max(levels) - min(levels) < 0.1, block


def test_blind_order_is_a_fixed_permutation():
    for block, items in lt3.BLOCKS.items():
        assert sorted(lt3.blind_order(block, len(items))) == list(range(len(items)))
    # pinned: a change of the draw changes the key and must be deliberate
    assert {b: lt3.blind_order(b, len(i)) for b, i in lt3.BLOCKS.items()} == {
        "K2": [1, 0], "K0": [1, 0], "K3": [0, 1],
        "K1": [2, 1, 0], "K4": [0, 1], "K5": [2, 1, 0, 3],
    }


def test_k5_sidecars_carry_seeds_and_rerender(built):
    side = built[0] / "sidecars"
    seeds = []
    for i in range(4):
        meta = json.loads((side / f"K5_v{i}.json").read_text(encoding="utf-8"))
        seeds.append(meta["parameters"]["seed"])
        wav = rerender_from_sidecar(side / f"K5_v{i}.json")
        assert hashlib.sha256(wav).hexdigest() == meta["sha256"]
    assert len(set(seeds)) == 4
