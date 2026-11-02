"""What ``rerender_from_sidecar`` checks beyond the JSON schema (#85, lead decision: enforce).

Standard library only. A sidecar written by the running engine is changed by hand; each case
expects ``SidecarError`` before anything renders and no change on disk. Expected values are
written here, not read from the engine: the valid and invalid ``created_at`` texts are listed
or built with explicit formatting, not with ``datetime.isoformat``.
"""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

import pytest
from support import kick_params as kp

import audio_engine.io as io_mod
from audio_engine.io import SidecarError, rerender_from_sidecar, write_kick

PARAMS = {"schema_version": "0.2", "seed": 85, "length_ms": 120}


@pytest.fixture(scope="module")
def written(tmp_path_factory) -> tuple[bytes, str]:
    """(WAV bytes, sidecar text) of a kick written by the running engine as ``t85``."""
    wav, js = write_kick(PARAMS, tmp_path_factory.mktemp("w85"), name="t85")
    return wav.read_bytes(), js.read_text(encoding="utf-8")


def _put(root: Path, text: str, wav: bytes | None, stem: str = "t85") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    if wav is not None:
        (root / f"{stem}.wav").write_bytes(wav)
    path = root / f"{stem}.json"
    path.write_text(text, encoding="utf-8")
    return path


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(root.iterdir())}


def _rejected(path: Path, monkeypatch) -> None:
    def no_render(params):
        raise AssertionError("rendered a sidecar that failed the read check")

    before = _snapshot(path.parent)
    monkeypatch.setattr(io_mod, "render_kick_wav", no_render)
    with pytest.raises(SidecarError):
        rerender_from_sidecar(path)
    with pytest.raises(SidecarError):
        rerender_from_sidecar(path, allow_engine_mismatch=True)
    assert _snapshot(path.parent) == before


def test_untampered_sidecar_with_its_wav_rerenders(written, tmp_path) -> None:
    wav, text = written
    path = _put(tmp_path, text, wav)
    assert hashlib.sha256(rerender_from_sidecar(path)).hexdigest() == json.loads(text)["sha256"]


def test_untampered_sidecar_without_a_wav_rerenders(written, tmp_path) -> None:
    path = _put(tmp_path, written[1], None)
    assert rerender_from_sidecar(path) == written[0]


# --- non-finite numbers -------------------------------------------------------------------------


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1e999", "-1e999"])
def test_non_finite_feature_is_rejected(written, tmp_path, monkeypatch, literal) -> None:
    meta = json.loads(written[1])
    meta["features"]["peak_dbfs"] = "@@"
    text = json.dumps(meta).replace('"@@"', literal)
    _rejected(_put(tmp_path, text, written[0]), monkeypatch)


@pytest.mark.parametrize("literal", ["NaN", "1e999"])
def test_non_finite_parameter_is_rejected_before_render(
    written, tmp_path, monkeypatch, literal
) -> None:
    meta = json.loads(written[1])
    meta["parameters"]["drive"] = "@@"
    text = json.dumps(meta).replace('"@@"', literal)
    _rejected(_put(tmp_path, text, written[0]), monkeypatch)


# --- created_at ---------------------------------------------------------------------------------

GOOD_STAMPS = [
    "2026-10-28T12:00:00+00:00", "2026-10-28T12:00:00Z", "2026-10-28T12:00:00z".upper(),
    "2026-10-28T12:00:00.250+02:00", "2024-02-29T23:59:59-05:30", "1999-12-31T00:00:00+14:00",
]
BAD_STAMPS = [
    "yesterday", "", "2026-10-28", "2026-10-28 12:00:00+00:00", "2026-10-28T12:00:00",
    "2026-10-28T12:00+00:00", "20261028T120000Z", "2026-13-01T00:00:00Z",
    "2026-02-30T00:00:00Z", "2025-02-29T00:00:00Z", "2026-10-28T24:00:00Z",
    "2026-10-28T12:60:00Z", "2026-10-28T12:00:60Z", "2026-10-28T12:00:00+0200",
    "2026-10-28T12:00:00+02", " 2026-10-28T12:00:00Z", "2026-10-28T12:00:00Z ",
    "2026-10-28T12:00:00Z\n", "２０２６-10-28T12:00:00Z",
]


def _with_stamp(written, stamp: str) -> str:
    meta = json.loads(written[1])
    meta["created_at"] = stamp
    return json.dumps(meta)


@pytest.mark.parametrize("stamp", GOOD_STAMPS)
def test_valid_rfc3339_stamps_are_accepted(written, tmp_path, stamp) -> None:
    path = _put(tmp_path, _with_stamp(written, stamp), written[0])
    assert rerender_from_sidecar(path) == written[0]


@pytest.mark.parametrize("stamp", BAD_STAMPS)
def test_bad_stamps_are_rejected(written, tmp_path, monkeypatch, stamp) -> None:
    _rejected(_put(tmp_path, _with_stamp(written, stamp), written[0]), monkeypatch)


@pytest.mark.parametrize("seed", range(40))
def test_random_valid_and_broken_stamps(written, tmp_path, monkeypatch, seed) -> None:
    rng = kp.rng(8500 + seed)
    y, mo, d = rng.randint(1970, 2099), rng.randint(1, 12), rng.randint(1, 28)
    h, mi, s = rng.randint(0, 23), rng.randint(0, 59), rng.randint(0, 59)
    off = rng.choice(["Z", f"{rng.choice('+-')}{rng.randint(0, 14):02d}:{rng.choice([0, 30]):02d}"])
    good = f"{y:04d}-{mo:02d}-{d:02d}T{h:02d}:{mi:02d}:{s:02d}{off}"
    path = _put(tmp_path / "ok", _with_stamp(written, good), written[0])
    assert rerender_from_sidecar(path) == written[0]
    breaks = [
        good.replace("T", " "), good[:-1] if off == "Z" else good[:-3], good.replace("-", "/", 1),
        f"{y:04d}-{rng.randint(13, 99):02d}-{d:02d}T{h:02d}:{mi:02d}:{s:02d}{off}",
        f"{y:04d}-{mo:02d}-{rng.randint(32, 99):02d}T{h:02d}:{mi:02d}:{s:02d}{off}",
        f"{y:04d}-{mo:02d}-{d:02d}T{rng.randint(24, 99):02d}:{mi:02d}:{s:02d}{off}",
        good + "x",
    ]
    for i, bad in enumerate(breaks):
        _rejected(_put(tmp_path / f"b{i}", _with_stamp(written, bad), written[0]), monkeypatch)


# --- sha256 and file ----------------------------------------------------------------------------


def test_sha256_that_does_not_match_the_wav_is_rejected(written, tmp_path, monkeypatch) -> None:
    meta = json.loads(written[1])
    meta["sha256"] = "0" * 64
    _rejected(_put(tmp_path, json.dumps(meta), written[0]), monkeypatch)


def test_wav_with_one_changed_byte_is_rejected(written, tmp_path, monkeypatch) -> None:
    wav = bytearray(written[0])
    wav[-5] ^= 0x01
    _rejected(_put(tmp_path, written[1], bytes(wav)), monkeypatch)


@pytest.mark.parametrize("seed", range(20))
def test_random_sha256_and_wav_tampering(written, tmp_path, monkeypatch, seed) -> None:
    rng = random.Random(8600 + seed)
    meta = json.loads(written[1])
    if seed % 2:
        meta["sha256"] = "".join(rng.choice("0123456789abcdef") for _ in range(64))
        if meta["sha256"] == json.loads(written[1])["sha256"]:  # pragma: no cover
            return
        wav = written[0]
    else:
        raw = bytearray(written[0])
        raw[rng.randrange(len(raw))] ^= 1 << rng.randrange(8)
        wav = bytes(raw)
    _rejected(_put(tmp_path, json.dumps(meta), wav), monkeypatch)


@pytest.mark.parametrize("name", ["other.wav", "T85.wav", "sub/t85.wav", "t85.wav.wav", ".wav"])
def test_file_that_is_not_this_sidecars_wav_is_rejected(
    written, tmp_path, monkeypatch, name
) -> None:
    meta = json.loads(written[1])
    meta["file"] = name
    _rejected(_put(tmp_path, json.dumps(meta), written[0]), monkeypatch)


def test_sidecar_renamed_away_from_its_file_is_rejected(written, tmp_path, monkeypatch) -> None:
    _rejected(_put(tmp_path, written[1], written[0], stem="renamed"), monkeypatch)
