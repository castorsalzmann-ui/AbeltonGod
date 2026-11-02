"""Clap listening test package (#232): file list, determinism, control pair, key, levels."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import numpy as np
import pytest

from audio_engine import listening_test3 as lt3
from audio_engine import listening_test_clap as ltc
from audio_engine.io import wav_samples

COUNTS = {"C0": 2, "C1": 2, "C2": 3, "C3": 3, "C4": 2, "C5": 2, "C6": 4}
EXPECTED_FILES = sorted(
    [f"{item}_{'ABCD'[i]}.wav" for item, n in COUNTS.items() for i in range(n)] + ["Schluessel.md"]
)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    a = tmp_path_factory.mktemp("ltc_a") / "out"
    b = tmp_path_factory.mktemp("ltc_b") / "out"
    return a, ltc.write_package(a), b, ltc.write_package(b)


def test_file_list_and_format(built):
    pkg = built[0] / "package"
    assert sorted(p.name for p in pkg.iterdir()) == EXPECTED_FILES
    assert len(EXPECTED_FILES) - 1 == 18
    wav = (pkg / "C1_A.wav").read_bytes()
    assert len(wav_samples(wav)) == 338824  # 16 beats at 136 BPM, 48 kHz
    assert wav[24:28] == (48000).to_bytes(4, "little") and wav[34:36] == (24).to_bytes(2, "little")


def test_same_run_twice_is_byte_identical(built):
    a, _, b, _ = built
    for name in EXPECTED_FILES:
        assert (a / "package" / name).read_bytes() == (b / "package" / name).read_bytes(), name


def test_control_pair_identical_and_real_pairs_differ(built):
    pkg = built[0] / "package"
    assert (pkg / "C0_A.wav").read_bytes() == (pkg / "C0_B.wav").read_bytes()
    assert built[1]["c0_identical"]
    for item in ("C1", "C4", "C5"):
        assert (pkg / f"{item}_A.wav").read_bytes() != (pkg / f"{item}_B.wav").read_bytes()


def test_key_maps_every_blind_name(built):
    pkg = built[0] / "package"
    rows = {}
    for line in (pkg / "Schluessel.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"\| `(C\d_[A-D]\.wav)` \| (.+?) \| ([+-]\d+\.\d\d) dB \|", line)
        if m:
            rows[m.group(1)] = (m.group(2), float(m.group(3)))
    assert sorted(rows) == [n for n in EXPECTED_FILES if n.endswith(".wav")]
    descriptions = {d for d, _, _ in ltc.RENDERS.values()}
    assert all(content in descriptions for content, _ in rows.values())
    # 18 files from 11 unique renders
    assert len(ltc.RENDERS) == 11 and sum(len(v) for v in ltc.ITEMS.values()) == 18
    # the key says which file is which: spot-check against the plan's blind order
    order = lt3.blind_order("C1", 2, ltc.BLIND_SEED)
    assert rows[f"C1_{'AB'[order[1]]}.wav"][0] == ltc.RENDERS["L"][0]


def test_levels_from_files_on_disk(built):
    # independent of measure(): file minus kick loop = clap loop; RMS over 60 ms of each clap
    pkg = built[0] / "package"
    _, starts = lt3.loop_samples()
    kick = np.round(lt3.build_loop(lt3._dense(), -6.0) * (2**23 - 1))
    win = round(0.060 * 48000)
    by_item: dict[str, list[float]] = {}
    for path in sorted(pkg.glob("C?_?.wav")):
        clap = wav_samples(path.read_bytes()) - kick
        for s in (starts[1], starts[3], starts[15]):
            x = clap[s : s + win] / 2.0**23
            by_item.setdefault(path.stem[:2], []).append(10 * np.log10(np.mean(x**2)))
    for item, levels in by_item.items():
        assert max(levels) - min(levels) < 0.5, (item, levels)
    peaks = [np.abs(wav_samples(p.read_bytes())).max() / (2**23 - 1) for p in pkg.glob("*.wav")]
    assert 20 * np.log10(max(peaks)) <= -0.3


def test_blind_order_is_a_fixed_permutation():
    for item, ids in ltc.ITEMS.items():
        assert sorted(lt3.blind_order(item, len(ids), ltc.BLIND_SEED)) == list(range(len(ids)))
    assert {i: lt3.blind_order(i, len(v), ltc.BLIND_SEED) for i, v in ltc.ITEMS.items()} == {
        "C1": [0, 1], "C0": [1, 0], "C4": [0, 1], "C5": [1, 0],
        "C3": [2, 1, 0], "C2": [2, 0, 1], "C6": [3, 1, 2, 0],
    }


def test_no_audio_files_in_the_repo():
    root = Path(__file__).resolve().parents[2]
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.split()
    assert not [f for f in tracked if f.lower().endswith((".wav", ".flac", ".mp3", ".aif"))]
