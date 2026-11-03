"""Bass listening test package (#361): files, determinism, blind names, levels, key, docs."""

from __future__ import annotations

import re
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from audio_engine import listening_test3 as lt3
from audio_engine import listening_test_bass as ltb
from audio_engine.io import wav_samples

COUNTS = {"B1": 5, "B2": 2, "B3": 3, "B4": 2, "B5": 3, "B6": 3}
NAMES = sorted(f"{item}_{'ABCDE'[i]}.wav" for item, n in COUNTS.items() for i in range(n))
BEAT = Fraction(60 * 48000, 140)  # exact samples per beat
DOCS = Path(__file__).resolve().parents[2] / "docs" / "setup"
# words that name a preset, a parameter or the control; none may appear in the listener guide
FORBIDDEN = re.compile(
    r"\b(default|sub|rolling|bright|low|drive|gate|gate_ms|preset|note|release|Schluessel|"
    r"Schlüssel|BASS_LEAD|Kontrolle|Kontrollpaar|byte-gleich|identisch|gleiche Datei)\b",
    re.IGNORECASE,
)


def leaks(text: str) -> list[str]:
    return sorted({m.group(0).lower() for m in FORBIDDEN.finditer(text)})


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    a = tmp_path_factory.mktemp("ltb_a") / "out"
    b = tmp_path_factory.mktemp("ltb_b") / "out"
    return a, ltb.write_package(a), b, ltb.write_package(b)


def test_file_list_and_format(built):
    pkg = built[0] / "hoerer"
    assert sorted(p.name for p in pkg.iterdir()) == NAMES
    assert len(NAMES) == 18
    wav = (pkg / "B1_A.wav").read_bytes()
    assert len(wav_samples(wav)) == 329143  # 16 beats at 140 BPM, 48 kHz (round(16*20571.43))
    assert wav[24:28] == (48000).to_bytes(4, "little") and wav[34:36] == (24).to_bytes(2, "little")


def test_same_run_twice_is_byte_identical(built):
    a, _, b, _ = built
    for name in NAMES:
        assert (a / "hoerer" / name).read_bytes() == (b / "hoerer" / name).read_bytes(), name
    assert (a / "Schluessel.md").read_bytes() == (b / "Schluessel.md").read_bytes()


def test_control_pair_identical_and_real_pairs_differ(built):
    pkg = built[0] / "hoerer"
    assert (pkg / "B2_A.wav").read_bytes() == (pkg / "B2_B.wav").read_bytes()
    assert built[1]["b2_identical"]
    assert (pkg / "B4_A.wav").read_bytes() != (pkg / "B4_B.wav").read_bytes()


def test_pattern_slots_exact():
    # expected values written from exact fractions: one beat = 20571.43 samples at 140 BPM
    off = ltb.pattern_slots("offbeat")
    assert [s for s, _ in off[:3]] == [10286, 30857, 51429]
    assert off[0][1] == 30857 and len(off) == 16
    bar = ltb.pattern_slots("bar")
    assert len(bar) == 4 and bar[0][0] == 10286
    assert bar[1][0] == 92571 and bar[2][0] == 174857  # (4k + 0.5) * 20571.43, rounded
    roll = ltb.pattern_slots("rolling")
    assert len(roll) == 48 and roll[0] == (5143, 10286)
    assert all(s % 1 == 0 and e > s for s, e in roll)
    # no rolling note starts on a beat position
    beats = {round(float(b * BEAT)) for b in range(16)}
    assert not beats & {s for s, _ in roll}


def test_notes_are_cut_and_end_silent(built):
    # a 1000 ms note in 'bar' fits; a 800 ms note in the 428 ms slot is cut with a fade
    long_note = np.ones(ltb.SAMPLE_RATE)
    out = ltb.bass_loop(long_note, "offbeat")
    s, e = ltb.pattern_slots("offbeat")[0]
    assert out[e - 145] == 1.0 and out[e - 1] == 0.0
    assert out[s] == 1.0


def test_levels_from_files_on_disk(built):
    # independent of the generator's measure: file minus quantised kick loop (made here from the
    # kick helper at 140 BPM), RMS over the stated window at several slots, per block
    pkg = built[0] / "hoerer"
    kick = np.round(lt3.build_loop(lt3._dense(), -6.0, 140) * (2**23 - 1))
    windows_ms = {"B1": (44, 88), "B2": (100, 200), "B3": (100, 200), "B4": (400, 800),
                  "B5": (48, 96), "B6": (44, 88)}
    # B2/B3 windows follow the shortest gate of the block = 250 ms -> 100-200 ms
    by_item: dict[str, list[float]] = {}
    for path in sorted(pkg.glob("B?_?.wav")):
        item = path.stem[:2]
        pattern = ltb.ITEMS[item][0]
        slots = ltb.pattern_slots(pattern)
        lo, hi = (round(w / 1000 * 48000) for w in windows_ms[item])
        bass = wav_samples(path.read_bytes()) - kick
        for k in (0, len(slots) // 2, len(slots) - 2):
            x = bass[slots[k][0] + lo : slots[k][0] + hi] / 2.0**23
            by_item.setdefault(item, []).append(10 * np.log10(np.mean(x**2)))
    assert set(by_item) == set(COUNTS)
    for item, levels in by_item.items():
        assert max(levels) - min(levels) < 0.5, (item, levels)
    peaks = [np.abs(wav_samples(p.read_bytes())).max() / (2**23 - 1) for p in pkg.glob("*.wav")]
    assert 20 * np.log10(max(peaks)) <= -0.3


def test_level_match_can_fail(monkeypatch):
    # fault injection: without the match (all notes measured as equal) the spread is large
    monkeypatch.setattr(ltb, "match_db", lambda note, window: 0.0)
    report = ltb.measure(ltb.render_package())
    assert report["match_spread_db"]["B4"] > 2.0
    assert max(report["match_spread_db"].values()) > 2.0


def test_key_maps_every_blind_name(built):
    rows = {}
    for line in (built[0] / "Schluessel.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"\| `(B\d_[A-E]\.wav)` \| (.+?) \| ([+-]\d+\.\d\d) dB \|", line)
        if m:
            rows[m.group(1)] = m.group(2)
    assert sorted(rows) == NAMES
    descriptions = {v[0] for v in ltb.RENDERS.values()}
    assert all(content in descriptions for content in rows.values())
    order = lt3.blind_order("B4", 2, ltb.BLIND_SEED)
    assert rows[f"B4_{'AB'[order[1]]}.wav"] == ltb.RENDERS["d2_long"][0]


def test_blind_order_is_a_permutation():
    for item, (_, ids) in ltb.ITEMS.items():
        assert sorted(lt3.blind_order(item, len(ids), ltb.BLIND_SEED)) == list(range(len(ids)))
        assert len(ids) == COUNTS[item]


def test_listener_doc_has_no_key_and_lead_doc_would_be_caught():
    listener = (DOCS / "LISTENING_TEST_BASS.md").read_text(encoding="utf-8")
    lead = (DOCS / "LISTENING_TEST_BASS_LEAD.md").read_text(encoding="utf-8")
    assert leaks(listener) == []
    assert "Schluessel" not in listener and "LISTENING_TEST_BASS_LEAD" not in listener
    # the checker can fail: the lead guide trips it
    assert len(leaks(lead)) >= 5
    # the listener guide names every block and the open drive-free question
    for item in COUNTS:
        assert item in listener
    assert "Wummern" in listener
