"""Rim listening test package (#359): files, determinism, blind names, level match, key, docs."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest

from audio_engine import listening_test3 as lt3
from audio_engine import listening_test_rim as ltr
from audio_engine.hat import render_hat
from audio_engine.io import wav_samples
from audio_engine.presets import load_preset
from audio_engine.rim import render_rim

COUNTS = {"R0": 2, "R1": 5, "R2": 4, "R3": 3, "R4": 4}
NAMES = sorted(f"{item}_{'ABCDE'[i]}.wav" for item, n in COUNTS.items() for i in range(n))
DOCS = Path(__file__).resolve().parents[2] / "docs" / "setup"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    a = tmp_path_factory.mktemp("ltr_a") / "out"
    b = tmp_path_factory.mktemp("ltr_b") / "out"
    return a, ltr.write_package(a), b, ltr.write_package(b)


def test_file_list_and_format(built):
    pkg = built[0] / "hoerer"
    assert sorted(p.name for p in pkg.iterdir()) == NAMES
    assert len(NAMES) == 18
    wav = (pkg / "R1_A.wav").read_bytes()
    assert len(wav_samples(wav)) == 338824  # 16 beats at 136 BPM, 48 kHz
    assert wav[24:28] == (48000).to_bytes(4, "little") and wav[34:36] == (24).to_bytes(2, "little")


def test_same_run_twice_is_byte_identical(built):
    a, _, b, _ = built
    for name in NAMES:
        assert (a / "hoerer" / name).read_bytes() == (b / "hoerer" / name).read_bytes(), name
    assert (a / "Schluessel.md").read_bytes() == (b / "Schluessel.md").read_bytes()


def test_control_pair_identical_and_real_pairs_differ(built):
    pkg = built[0] / "hoerer"
    assert (pkg / "R0_A.wav").read_bytes() == (pkg / "R0_B.wav").read_bytes()
    assert built[1]["r0_identical"]
    for item, n in COUNTS.items():
        if item == "R0":
            continue
        blobs = {(pkg / f"{item}_{'ABCDE'[i]}.wav").read_bytes() for i in range(n)}
        assert len(blobs) == n, item


def test_rim_onsets_in_files_match_offbeat_pattern(built):
    pkg = built[0] / "hoerer"
    rim = ltr.rim_only_ints((pkg / "R3_A.wav").read_bytes())
    # off-beat 8ths: beat 0.5 = round(0.5 * 60 / 136 * 48000) = 10588; silent before it
    assert np.abs(rim[:10588]).max() <= 1
    assert np.abs(rim[10588 : 10588 + 480]).max() > 100


def test_levels_from_files_on_disk(built):
    # independent of measure(): the background is rebuilt here from the kick loop and a hat bed
    # placed by hand (16ths at exact fractions), the rim part is file minus background
    pkg = built[0] / "hoerer"
    beat = 60.0 * 48000 / 136
    hat = render_hat({**load_preset("closed-std", "hat"), "seed": 1, "peak_ceiling_dbfs": -0.3})[0]
    bed = np.zeros(lt3.loop_samples()[0])
    fade = round(0.003 * 48000)
    for k in range(64):
        s, e = round(k * beat / 4), round((k + 1) * beat / 4) if k < 63 else len(bed)
        seg = hat[: e - s].copy()
        seg[-fade:] *= 0.5 * (1 + np.cos(np.pi * np.arange(fade) / (fade - 1)))
        bed[s : s + len(seg)] += seg
    back = lt3.build_loop(lt3._dense(), -6.0) + bed * 10 ** (-14 / 20)
    back = np.round(back * (2**23 - 1))
    starts = [round((b + 0.5) * beat) for b in range(16)]
    win = round(0.060 * 48000)
    by_item: dict[str, list[float]] = {}
    for path in sorted(pkg.glob("R?_?.wav")):
        item = path.stem[:2]
        rim = wav_samples(path.read_bytes()) - back
        for slot in (0, 7, 14):
            x = rim[starts[slot] : starts[slot] + win] / 2.0**23
            by_item.setdefault(item, []).append(10 * np.log10(np.mean(x**2)))
    assert set(by_item) == set(COUNTS)
    for item, levels in by_item.items():
        assert max(levels) - min(levels) < 0.5, (item, levels)
    peaks = [np.abs(wav_samples(p.read_bytes())).max() / (2**23 - 1) for p in pkg.glob("*.wav")]
    assert 20 * np.log10(max(peaks)) <= -0.3


def test_gains_never_boost_and_quietest_keeps_zero(built):
    files = ltr.render_package()
    for item in COUNTS:
        gains = [f.gain_db for f in files if f.item == item]
        assert max(gains) == 0.0 and min(gains) <= 0.0


def test_level_match_can_fail(monkeypatch):
    # fault injection: without the match (all hits measured as equal) the spread is large
    monkeypatch.setattr(ltr, "match_db", lambda hit: 0.0)
    report = ltr.measure(ltr.render_package())
    assert report["match_spread_db"]["R1"] > 0.5
    assert max(report["match_spread_db"].values()) > 1.0


def test_blind_order_is_a_permutation_and_not_definition_order():
    shuffled = 0
    for item, ids in ltr.ITEMS.items():
        order = lt3.blind_order(item, len(ids), ltr.BLIND_SEED)
        assert sorted(order) == list(range(len(ids)))
        assert len(ids) == COUNTS[item]
        shuffled += order != list(range(len(ids)))
    assert shuffled >= 3


def _items_in_definition_order(files):
    return sum(
        all(f.label == "ABCDE"[ltr.ITEMS[item].index(f.render)] for f in files if f.item == item)
        for item in ltr.ITEMS
        if item != "R0"
    )


def test_real_package_not_in_definition_order():
    assert _items_in_definition_order(ltr.render_package()) < 3


def test_blind_order_fault_is_detected(monkeypatch):
    # fault injection: identity order puts every item in definition order; the check sees it
    monkeypatch.setattr(lt3, "blind_order", lambda block, n, seed=0: list(range(n)))
    assert _items_in_definition_order(ltr.render_package()) == 4


def test_key_maps_every_blind_name(built):
    rows = {}
    for line in (built[0] / "Schluessel.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"\| `(R\d_[A-E]\.wav)` \| (.+?) \| ([+-]\d+\.\d\d) dB \|", line)
        if m:
            rows[m.group(1)] = (m.group(2), float(m.group(3)))
    assert sorted(rows) == NAMES
    descriptions = {d for d, _ in ltr.RENDERS.values()}
    assert all(content in descriptions for content, _ in rows.values())
    order = lt3.blind_order("R1", 5, ltr.BLIND_SEED)
    assert rows[f"R1_{'ABCDE'[order[4]]}.wav"][0] == ltr.RENDERS["tight"][0]


# Hand-written expectation for every render: (preset, overrides). Not taken from the module.
EXPECTED = {
    "clave": ("clave", {}),
    "high": ("high", {}),
    "long": ("long", {}),
    "rim": ("rim", {}),
    "tight": ("tight", {}),
    "click0": ("rim", {"click_level": 0.0}),
    "click3": ("rim", {"click_level": 0.6, "click_ms": 3}),
    "click1": ("rim", {"click_level": 0.6, "click_ms": 1}),
    "click02": ("rim", {"click_level": 0.6, "click_ms": 0.2}),
    "hp200": ("high", {"hp_hz": 200}),
    "hp500": ("high", {"hp_hz": 500}),
    "hp700": ("high", {"hp_hz": 700}),
    "ratio2": ("rim", {"f2_ratio": 2.0}),
    "ratio366": ("rim", {"f2_ratio": 3.66}),
    "ratio5": ("rim", {"f2_ratio": 5.0}),
    "single": ("rim", {"level2": 0.0}),
}
# Which render ids each item holds, written out by hand.
EXPECTED_ITEMS = {
    "R1": {"clave", "high", "long", "rim", "tight"},
    "R0": {"rim"},
    "R2": {"click0", "click3", "click1", "click02"},
    "R3": {"hp200", "hp500", "hp700"},
    "R4": {"ratio2", "ratio366", "ratio5", "single"},
}


def test_renders_are_the_documented_parameters():
    assert set(ltr.RENDERS) == set(EXPECTED) and len(EXPECTED) == 16
    for rid, (preset, changes) in EXPECTED.items():
        want = render_rim({**load_preset(preset, "rim"), "seed": 1,
                           "peak_ceiling_dbfs": -0.3, **changes})[0]
        assert np.array_equal(ltr.RENDERS[rid][1](), want), rid
    for item, ids in ltr.ITEMS.items():
        assert set(ids) == EXPECTED_ITEMS[item], item


def test_renders_check_can_fail():
    # the check is not vacuous: a wrong ratio is not equal to the documented render
    want = render_rim({**load_preset("rim", "rim"), "seed": 1, "peak_ceiling_dbfs": -0.3,
                       "f2_ratio": 5.0 * 0.98})[0]
    assert not np.array_equal(ltr.RENDERS["ratio5"][1](), want)


def test_listener_doc_hides_names_control_and_key():
    text = (DOCS / "LISTENING_TEST_RIM.md").read_text(encoding="utf-8")
    low = text.lower()
    for word in ("clave", "tight", "preset", "click_ms", "click_level", "hp_hz", "f2_ratio",
                 "level2", "f1_hz", "kontroll", "identisch", "schluessel", "schlüssel",
                 "lead", "listening_test_rim", "pegelangleich"):
        assert word not in low, word
    # beyond the keyword list: every parameter name, preset name and render id from the
    # engine, every render description, and the numeric values that distinguish the files
    names = {"seed", "hp_hz", "f1_hz", "f2_ratio", "level2", "click_level", "click_ms"}
    names |= {k for preset, _ in EXPECTED.values() for k in load_preset(preset, "rim")}
    names |= {preset for preset, _ in EXPECTED.values()}
    names |= set(ltr.RENDERS) | {d.lower() for d, _ in ltr.RENDERS.values()}
    names -= {"schema_version", "preset", "rim"}  # "rim" is the topic of the document
    words = set(re.findall(r"[a-z0-9_]+", low))
    for name in sorted(names):
        assert name.lower() not in low if " " in name else name.lower() not in words, name
    for number in ("3,66", "3.66", "0,2 ms", "0.2 ms", "700 hz", "200 hz", "500 hz", "0,6",
                   "-8 db", "-6 db", "-14 db", "closed-std", "dense"):
        assert number not in low, number
    lead = (DOCS / "LISTENING_TEST_RIM_LEAD.md").read_text(encoding="utf-8")
    assert "python -m audio_engine.listening_test_rim --out" in lead
    assert "Schluessel.md" in lead
    # lead doc carries the second-control note and the measured hp_hz numbers (issue #365)
    assert "Zweite Kontrolle" in lead and "-18,1 / -24,7 / -28,8" in lead
    assert "Unterschied klein bei 200" not in lead
