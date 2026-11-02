"""Keyword listening package (#271): file list, determinism, levels, key/listener split."""

from __future__ import annotations

import re

import numpy as np
import pytest

from audio_engine import listening_keywords as lk
from audio_engine.io import wav_samples

LISTENER_FILES = sorted(
    ["REF.wav", "Anleitung.md", "Antwortbogen.md"]
    + [f"E{i:02d}.wav" for i in range(1, 18)] + [f"K{i:02d}.wav" for i in range(1, 7)]
)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    a = tmp_path_factory.mktemp("kw_a") / "out"
    b = tmp_path_factory.mktemp("kw_b") / "out"
    return a, lk.write_package(a), b, lk.write_package(b)


def _read_ints(path):
    return wav_samples(path.read_bytes()) / 2.0**23


def test_file_lists_and_format(built):
    out = built[0]
    assert sorted(p.name for p in (out / "hoerer").iterdir()) == LISTENER_FILES
    assert sorted(p.name for p in (out / "lead").iterdir()) == ["Schluessel.md", "Vorcheck.md"]
    wav = (out / "hoerer" / "E01.wav").read_bytes()
    assert len(wav_samples(wav)) == 4 * round(60 / 136 * 4 * 48000)  # 4 bars, 1.765 s each
    assert wav[24:28] == (48000).to_bytes(4, "little") and wav[34:36] == (24).to_bytes(2, "little")
    assert built[1]["files"] == 24


def test_same_run_twice_is_byte_identical(built):
    a, _, b, _ = built
    for sub in ("hoerer", "lead"):
        names = sorted(p.name for p in (a / sub).iterdir())
        assert names == sorted(p.name for p in (b / sub).iterdir())
        for name in names:
            assert (a / sub / name).read_bytes() == (b / sub / name).read_bytes(), name


def test_listener_folder_has_no_keywords_prompts_or_key(built):
    out = built[0]
    key = (out / "lead" / "Schluessel.md").read_text(encoding="utf-8")
    prompts = [p for _, p, _ in lk.ENDS] + [p for _, p in lk.COMBINED]
    forbidden = re.compile(r"\b(" + "|".join(lk.FORBIDDEN_IN_LISTENER) + r")\b", re.I)
    for path in (out / "hoerer").iterdir():
        assert "schluessel" not in path.stem.lower() or path.suffix == ".md"
        assert path.name not in ("Schluessel.md", "Vorcheck.md")
        data = path.read_bytes()
        for prompt in prompts:
            assert prompt.encode() not in data, (path.name, prompt)
        if path.suffix == ".md":
            text = path.read_text(encoding="utf-8")
            assert not forbidden.search(text), (path.name, forbidden.search(text).group(0))
            assert "Gain" not in text and "dBFS" not in text
    # the key does hold them (so the check above is not vacuous)
    assert all(p in key for p in prompts)
    assert forbidden.search(key)


def test_key_decodes_every_listener_file(built):
    out = built[0]
    key = (out / "lead" / "Schluessel.md").read_text(encoding="utf-8")
    for path in (out / "hoerer").glob("*.wav"):
        assert f"`{path.name}`" in key, path.name
    # the answer sheet lists every blind file once and not REF
    sheet = (out / "hoerer" / "Antwortbogen.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| ([EK]\d\d) \|", sheet, re.M)
    assert rows == [f"E{i:02d}" for i in range(1, 18)] + [f"K{i:02d}" for i in range(1, 7)]


def test_levels_measured_from_files_on_disk(built):
    # independent of the module: read the written files, peak limit and 0.1 dB onset-RMS match
    hoerer = built[0] / "hoerer"
    ref_level = None
    files = sorted(hoerer.glob("*.wav"), key=lambda p: p.name != "REF.wav")
    for path in files:
        x = _read_ints(path)
        assert 20 * np.log10(np.abs(x).max()) <= -0.3, path.name
        start = int(np.flatnonzero(np.abs(x) >= 0.1 * np.abs(x).max())[0])
        level = 10 * np.log10(np.mean(x[start : start + 4800] ** 2))
        if path.name == "REF.wav":
            ref_level = level
            assert abs(20 * np.log10(np.abs(x).max()) - (-7.0)) < 0.01
        else:
            assert abs(level - ref_level) < 0.1, (path.name, level - ref_level)


def test_twin_is_a_byte_copy_of_ref_and_others_differ(built):
    hoerer = built[0] / "hoerer"
    data = {p.name: p.read_bytes() for p in hoerer.glob("*.wav")}
    twins = [n for n, d in data.items() if d == data["REF.wav"] and n != "REF.wav"]
    assert len(twins) == 1 and twins[0].startswith("E")
    assert len(set(data.values())) == 23  # 24 files, exactly one duplicate


def test_blind_numbers_are_a_permutation():
    for block, n in ((lk.BLOCK_SINGLE, 17), (lk.BLOCK_COMBO, 6)):
        assert sorted(lk.blind_order(block, n, lk.BLIND_SEED)) == list(range(n))


def test_precheck_reports_every_keyword_and_flags_failures(built):
    report = (built[0] / "lead" / "Vorcheck.md").read_text(encoding="utf-8")
    for kw in lk.KEYWORDS:
        assert f"| `{kw}` |" in report
    assert ("FAIL" in report) == (not built[1]["precheck_all_pass"])
    # the plan's own numbers are printed next to ours
    assert "0.431" in report and "0.713" in report


def test_precheck_fails_when_a_keyword_does_not_move(monkeypatch):
    """Fault injection: a mapping that ignores `sub` must turn the pre-check red."""
    real = lk.parse_prompt
    monkeypatch.setattr(lk, "parse_prompt", lambda t: real(t.replace("sub:2", "")))
    items = lk.render_package()
    report, ok = lk.precheck(items)
    assert not ok
    assert re.search(r"\| `sub` \| sub150 .*FAIL", report)


def test_refuses_non_empty_folder(tmp_path):
    (tmp_path / "x").write_text("x")
    with pytest.raises(FileExistsError):
        lk.write_package(tmp_path)
