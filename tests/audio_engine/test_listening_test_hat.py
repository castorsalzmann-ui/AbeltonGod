"""Hat listening test package (#300): file list, determinism, pattern timing, levels, key."""

from __future__ import annotations

import re
from fractions import Fraction

import numpy as np
import pytest

from audio_engine import listening_test3 as lt3
from audio_engine import listening_test_hat as lth
from audio_engine.io import wav_samples

COUNTS = {"T0": 2, "T1": 2, "T2": 3, "T3": 3, "T4": 3, "T5": 2, "T6": 4}
NAMES = sorted(f"{item}_{'ABCD'[i]}.wav" for item, n in COUNTS.items() for i in range(n))
BEAT = Fraction(60 * 48000, 136)  # exact samples per beat


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    a = tmp_path_factory.mktemp("lth_a") / "out"
    b = tmp_path_factory.mktemp("lth_b") / "out"
    return a, lth.write_package(a), b, lth.write_package(b)


def test_file_list_and_format(built):
    pkg = built[0] / "hoerer"
    assert sorted(p.name for p in pkg.iterdir()) == NAMES
    assert len(NAMES) == 19
    assert (built[0] / "Schluessel.md").exists()
    wav = (pkg / "T1_A.wav").read_bytes()
    assert len(wav_samples(wav)) == 338824  # 16 beats at 136 BPM, 48 kHz
    assert wav[24:28] == (48000).to_bytes(4, "little") and wav[34:36] == (24).to_bytes(2, "little")


def test_same_run_twice_is_byte_identical(built):
    a, _, b, _ = built
    for name in NAMES:
        assert (a / "hoerer" / name).read_bytes() == (b / "hoerer" / name).read_bytes(), name
    assert (a / "Schluessel.md").read_bytes() == (b / "Schluessel.md").read_bytes()


def test_control_pair_identical_and_real_pairs_differ(built):
    pkg = built[0] / "hoerer"
    assert (pkg / "T0_A.wav").read_bytes() == (pkg / "T0_B.wav").read_bytes()
    assert built[1]["t0_identical"]
    for item in ("T1", "T5"):
        assert (pkg / f"{item}_A.wav").read_bytes() != (pkg / f"{item}_B.wav").read_bytes()


def _round(x: Fraction) -> int:
    return int(np.floor(float(x) + 0.5))


def test_pattern_timing_exact():
    # expected values written out from exact fractions, not from the module's float formula
    closed = [_round(Fraction(k) * BEAT / 4) for k in range(64)]
    openh = [_round((b + Fraction(1, 2)) * BEAT) for b in range(16)]
    assert lth.slot_starts("closed") == closed
    assert lth.slot_starts("open") == openh
    assert closed[:5] == [0, 5294, 10588, 15882, 21176]  # beat = 21176.47 samples
    assert openh[:2] == [10588, 31765]
    # sixteenths: 16 per bar; open: off-beat 8ths, 4 per bar
    assert len(closed) == 64 and len(openh) == 16
    assert all(s % 1 == 0 for s in closed)


def test_hat_onsets_in_files_match_pattern(built):
    # an impulse-like check on the files: hat-only part is silent before the first slot of the
    # open pattern and starts exactly there; closed pattern starts at sample 0
    pkg = built[0] / "hoerer"
    open_hat = lth.hat_only_ints((pkg / "T5_A.wav").read_bytes())
    first = lth.slot_starts("open")[0]
    assert np.abs(open_hat[:first]).max() <= 1  # quantisation difference only
    assert np.abs(open_hat[first : first + 480]).max() > 100


def test_open_hat_is_cut_before_next_slot(built):
    # a 500 ms open hat is still loud just before the 3 ms fade and ~silent at the cut
    pkg = built[0] / "hoerer"
    x = lth.hat_only_ints((pkg / "T5_B.wav").read_bytes())
    s = lth.slot_starts("open")
    fade = round(0.003 * 48000)
    assert np.abs(x[s[1] - 2 * fade : s[1] - fade]).max() > 20 * abs(x[s[1] - 1])


def test_levels_from_files_on_disk(built):
    # independent of measure(): file minus kick loop = hat loop; RMS over the window of several
    # slots (first, middle, last full one) must agree across the files of an item
    pkg = built[0] / "hoerer"
    kick = np.round(lt3.build_loop(lt3._dense(), -6.0) * (2**23 - 1))
    by_item: dict[str, list[float]] = {}
    for path in sorted(pkg.glob("T?_?.wav")):
        item = path.stem[:2]
        closed = item not in ("T4", "T5")
        starts = lth.slot_starts("closed" if closed else "open")
        win = round((0.030 if closed else 0.100) * 48000)
        hat = wav_samples(path.read_bytes()) - kick
        for slot in (0, len(starts) // 2, len(starts) - 2):
            x = hat[starts[slot] : starts[slot] + win] / 2.0**23
            by_item.setdefault(item, []).append(10 * np.log10(np.mean(x**2)))
    for item, levels in by_item.items():
        assert max(levels) - min(levels) < 0.5, (item, levels)
    peaks = [np.abs(wav_samples(p.read_bytes())).max() / (2**23 - 1) for p in pkg.glob("*.wav")]
    assert 20 * np.log10(max(peaks)) <= -0.3


def test_level_match_can_fail(monkeypatch):
    # fault injection: without the match (all hits measured as equal) the spread is large
    monkeypatch.setattr(lth, "match_db", lambda hit, kind: 0.0)
    report = lth.measure(lth.render_package())
    assert report["match_spread_db"]["T1"] > 0.5
    assert max(report["match_spread_db"].values()) > 1.0


def test_key_maps_every_blind_name(built):
    rows = {}
    for line in (built[0] / "Schluessel.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"\| `(T\d_[A-D]\.wav)` \| (.+?) \| ([+-]\d+\.\d\d) dB \|", line)
        if m:
            rows[m.group(1)] = (m.group(2), float(m.group(3)))
    assert sorted(rows) == NAMES
    descriptions = {d for d, _, _ in lth.RENDERS.values()}
    assert all(content in descriptions for content, _ in rows.values())
    order = lt3.blind_order("T1", 2, lth.BLIND_SEED)
    assert rows[f"T1_{'AB'[order[1]]}.wav"][0] == lth.RENDERS["tight"][0]


def test_blind_order_is_a_permutation_and_names_hide_content():
    for item, ids in lth.ITEMS.items():
        assert sorted(lt3.blind_order(item, len(ids), lth.BLIND_SEED)) == list(range(len(ids)))
        assert len(ids) == COUNTS[item]
