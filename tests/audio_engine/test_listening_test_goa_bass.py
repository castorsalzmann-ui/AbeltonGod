"""Goa rolling-bass presets and listening package (#381): contract, determinism, levels, docs."""

from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path

import numpy as np
import pytest

from audio_engine import listening_test3 as lt3
from audio_engine import listening_test_bass as ltb
from audio_engine import listening_test_goa_bass as ltg
from audio_engine.bass import render_bass, resolve_bass_params
from audio_engine.io import encode_wav, wav_samples
from audio_engine.presets import describe, load_preset, preset_names

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "setup"
SCHEMA = json.loads((ROOT / "contracts" / "bass-params.schema.json").read_text("utf-8"))
COUNTS = {"G1": 3, "G2": 2, "G3": 3, "G4": 2, "G5": 3}
NAMES = sorted(f"{i}_{'ABC'[k]}.wav" for i, n in COUNTS.items() for k in range(n))
# expected values written here, not read from the presets: gate_ms, release_ms, filter decay ms
EXPECTED = {
    "goa-roll-short": (62, 12, 8),
    "goa-roll-medium": (85, 14, 15),
    "goa-roll-long": (100, 8, 25),
}
FORBIDDEN = re.compile(
    r"\b(goa-roll\w*|short|medium|long|ring|gate|gate_ms|decay|preset|note|release|filter|"
    r"Schluessel|Schlüssel|GOA_BASS_LEAD|Kontrolle|Kontrollpaar|byte-gleich|identisch|"
    r"gleiche Datei|Hypothese)\b",
    re.IGNORECASE,
)


def leaks(text: str) -> list[str]:
    return sorted({m.group(0).lower() for m in FORBIDDEN.finditer(text)})


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    a = tmp_path_factory.mktemp("ltg_a") / "out"
    b = tmp_path_factory.mktemp("ltg_b") / "out"
    return a, ltg.write_package(a), b, ltg.write_package(b)


# --- presets ------------------------------------------------------------------------------------


def test_presets_exist_and_match_the_written_values() -> None:
    names = preset_names("bass")
    for name, (gate, release, decay) in EXPECTED.items():
        assert name in names
        p = load_preset(name, "bass")
        assert (p["preset"], p["gate_ms"], p["release_ms"], p["lp_env_decay_ms"]) == (
            name, gate, release, decay)
        assert describe(name, "bass") != ""


def test_presets_validate_against_the_schema_ranges_without_clamping() -> None:
    props = SCHEMA["properties"]
    for name in EXPECTED:
        p = load_preset(name, "bass")
        assert set(p) <= set(props)  # no field outside the contract
        for key, value in p.items():
            spec = props[key]
            if "minimum" in spec:
                assert spec["minimum"] <= value <= spec["maximum"], (name, key)
        resolve_bass_params(p)  # cross-field rules too


def test_gate_is_between_half_and_one_sixteenth_at_140_to_146_bpm() -> None:
    # 16th = 60000 / (4 * bpm) ms; hypothesis window 0.55-1.0 (plan section 2.2: 0.6-1.0)
    for name in EXPECTED:
        gate = load_preset(name, "bass")["gate_ms"]
        for bpm in (140, 146):
            assert 0.55 <= gate / (60000 / (4 * bpm)) < 1.0, (name, bpm)
    gates = [load_preset(n, "bass")["gate_ms"] for n in EXPECTED]
    assert gates == sorted(gates) and len(set(gates)) == 3


def test_seeded_property_presets_render_clean_and_deterministic() -> None:
    rng = random.Random(381)
    for _ in range(12):
        name = rng.choice(list(EXPECTED))
        seed = rng.randrange(0, 2**32)
        note = rng.randint(24, 55)
        p = {**load_preset(name, "bass"), "seed": seed, "note": note, "hp_hz": 20}
        a, r = render_bass(p)
        b, _ = render_bass(p)
        wav = encode_wav(a, 48000, 24)
        assert wav == encode_wav(b, 48000, 24), (name, seed, note)
        assert hashlib.sha256(wav).digest() == hashlib.sha256(encode_wav(b, 48000, 24)).digest()
        assert a[0] == 0.0 and a[-1] == 0.0
        assert 20 * np.log10(np.abs(wav_samples(wav)).max() / (2**23 - 1)) <= -0.3 + 1e-9
        assert len(a) == round((r["gate_ms"] + r["release_ms"]) / 1000 * 48000)


# --- package ------------------------------------------------------------------------------------


def test_file_list_format_and_determinism(built) -> None:
    a, _, b, _ = built
    assert sorted(p.name for p in (a / "hoerer").iterdir()) == NAMES
    assert len(NAMES) == 13
    wav = (a / "hoerer" / "G1_A.wav").read_bytes()
    assert len(wav_samples(wav)) == 329143
    for name in NAMES:
        assert (a / "hoerer" / name).read_bytes() == (b / "hoerer" / name).read_bytes(), name
    assert (a / "Schluessel.md").read_bytes() == (b / "Schluessel.md").read_bytes()


def test_control_pair_identical_and_real_pairs_differ(built) -> None:
    pkg = built[0] / "hoerer"
    assert (pkg / "G2_A.wav").read_bytes() == (pkg / "G2_B.wav").read_bytes()
    assert built[1]["g2_identical"]
    for item, n in COUNTS.items():
        if item != "G2":
            blobs = {(pkg / f"{item}_{'ABC'[k]}.wav").read_bytes() for k in range(n)}
            assert len(blobs) == n, item


def test_levels_from_files_on_disk(built) -> None:
    # independent of the generator's measure: file minus the quantised kick loop made here,
    # RMS over the stated absolute window (written out) at several slots
    pkg = built[0] / "hoerer"
    kick = np.round(lt3.build_loop(lt3._dense(), -6.0, 140) * (2**23 - 1))
    windows_ms = {"G1": (24.8, 49.6), "G2": (34, 68), "G3": (34, 68), "G4": (34, 68),
                  "G5": (34, 68)}
    patterns = {"G4": "offbeat"}
    by_item: dict[str, list[float]] = {}
    for path in sorted(pkg.glob("G?_?.wav")):
        item = path.stem[:2]
        slots = ltb.pattern_slots(patterns.get(item, "rolling"))
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


def test_level_match_can_fail(monkeypatch) -> None:
    monkeypatch.setattr(ltb, "match_db", lambda note, window: 0.0)
    report = ltg.measure(ltg.render_package())
    assert max(report["match_spread_db"].values()) > 1.0


def test_key_maps_every_blind_name(built) -> None:
    rows = {}
    for line in (built[0] / "Schluessel.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"\| `(G\d_[A-C]\.wav)` \| (.+?) \| ([+-]\d+\.\d\d) dB \|", line)
        if m:
            rows[m.group(1)] = m.group(2)
    assert sorted(rows) == NAMES
    order = lt3.blind_order("G1", 3, ltg.BLIND_SEED)
    assert rows[f"G1_{'ABC'[order[2]]}.wav"] == ltg.RENDERS["long"][0]


def test_blind_order_is_a_permutation() -> None:
    for item, (_, ids) in ltg.ITEMS.items():
        assert sorted(lt3.blind_order(item, len(ids), ltg.BLIND_SEED)) == list(range(len(ids)))
        assert len(ids) == COUNTS[item]


def test_listener_doc_has_no_key_and_the_checker_can_fail() -> None:
    listener = (DOCS / "LISTENING_TEST_GOA_BASS.md").read_text(encoding="utf-8")
    lead = (DOCS / "LISTENING_TEST_GOA_BASS_LEAD.md").read_text(encoding="utf-8")
    assert leaks(listener) == []
    assert "Schluessel" not in listener and "_LEAD" not in listener
    assert len(leaks(lead)) >= 5
    for item in COUNTS:
        assert item in listener
