"""Robustness of WAV encoding, file naming, sidecar timestamps and parameter types (issue #12).

Each section covers one item of #12. The RIFF checks parse the bytes with ``struct`` here in the
test, independently of ``encode_wav`` and of the standard library ``wave`` module.
"""

from __future__ import annotations

import io
import json
import os
import random
import struct
import wave
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from audio_engine.io import encode_wav, render_kick_wav, write_kick
from audio_engine.kick import render_kick
from audio_engine.params import KICK_SCHEMA_FILE, KickParamsError, load_schema

BASE = {"schema_version": "0.1", "seed": 7}
FIXED_TIME = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


# --- 1. RIFF pad byte ------------------------------------------------------------------------


def parse_riff(data: bytes) -> dict:
    """Walk the RIFF chunks by hand. Returns the fmt fields and the data chunk."""
    assert data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    (riff_size,) = struct.unpack("<I", data[4:8])
    assert riff_size == len(data) - 8, "RIFF size must cover the whole file"
    chunks = {}
    pos = 12
    while pos < len(data):
        cid = data[pos : pos + 4]
        (size,) = struct.unpack("<I", data[pos + 4 : pos + 8])
        body = data[pos + 8 : pos + 8 + size]
        assert len(body) == size, f"chunk {cid!r} runs past the end of the file"
        pad = size % 2
        if pad:
            assert data[pos + 8 + size : pos + 9 + size] == b"\x00", f"{cid!r}: pad byte missing"
        chunks[cid] = body
        pos += 8 + size + pad
    assert pos == len(data), "trailing bytes after the last chunk"
    fmt = struct.unpack("<HHIIHH", chunks[b"fmt "])
    return {"fmt": fmt, "data": chunks[b"data"], "riff_size": riff_size}


@pytest.mark.parametrize("bits", [16, 24])
@pytest.mark.parametrize("n", [0, 1, 2, 3, 4, 3841, 3842])
def test_wav_chunks_are_word_aligned_for_any_sample_count(bits: int, n: int) -> None:
    rng = np.random.default_rng(n)
    audio = rng.uniform(-1, 1, n)
    data = encode_wav(audio, 48000, bits)
    riff = parse_riff(data)
    width = bits // 8
    assert riff["fmt"] == (1, 1, 48000, 48000 * width, width, bits)
    assert len(riff["data"]) == n * width  # chunk size = real audio, without the pad byte
    assert len(data) % 2 == 0 and riff["riff_size"] % 2 == 0
    # The standard library still reads every frame and stops at the data chunk size.
    with wave.open(io.BytesIO(data)) as w:
        assert w.getnframes() == n
        assert w.readframes(n) == riff["data"]


def test_odd_length_kick_from_the_review_is_padded() -> None:
    # Review case from #8: 3841 samples at 48 kHz / 24 bit → 11523 data bytes.
    wav, audio, _ = render_kick_wav({**BASE, "length_ms": 3841 / 48, "sample_rate": 48000})
    assert len(audio) == 3841
    riff = parse_riff(wav)
    assert len(riff["data"]) == 11523
    assert len(wav) == 44 + 11523 + 1


def test_even_sample_counts_keep_the_previous_bytes() -> None:
    """For even sizes the header must stay what the stdlib ``wave`` writer produced before #12,
    so existing renders keep their hashes."""
    rng = np.random.default_rng(5)
    for bits in (16, 24):
        for n in (2, 480, 3842):
            audio = rng.uniform(-1, 1, n)
            ours = encode_wav(audio, 44100, bits)
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(bits // 8)
                w.setframerate(44100)
                w.writeframes(ours[44:])
            assert ours == buf.getvalue(), (bits, n)


def test_random_kicks_are_always_word_aligned() -> None:
    rng = random.Random(1212)
    for _ in range(40):
        p = {
            **BASE,
            "seed": rng.randrange(2**32),
            "sample_rate": rng.choice([44100, 48000]),
            "bit_depth": rng.choice([16, 24]),
            "length_ms": rng.uniform(80, 300),
        }
        wav, audio, r = render_kick_wav(p)
        riff = parse_riff(wav)
        assert len(riff["data"]) == len(audio) * r["bit_depth"] // 8
        assert len(wav) % 2 == 0


# --- 2. dangling symlink at the target name --------------------------------------------------


def _symlink_or_skip(link: Path, target: Path) -> None:
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError) as exc:  # Windows without symlink privilege
        pytest.skip(f"cannot create symlinks here: {exc}")


@pytest.mark.parametrize("suffix", [".wav", ".json"])
def test_dangling_symlink_blocks_the_name_and_stays_untouched(tmp_path, suffix: str) -> None:
    link = tmp_path / f"kick{suffix}"
    _symlink_or_skip(link, tmp_path / "missing-target")
    wav_path, json_path = write_kick(BASE, tmp_path, created_at=FIXED_TIME)
    assert (wav_path.name, json_path.name) == ("kick_002.wav", "kick_002.json")
    assert link.is_symlink() and not link.exists()
    assert not (tmp_path / "missing-target").exists()


# --- 3. created_at must carry a time zone ----------------------------------------------------


# The target folder does not exist yet: a bad created_at must fail before write_kick creates it.


def test_naive_created_at_is_rejected_before_anything_is_written(tmp_path) -> None:
    out = tmp_path / "new"
    with pytest.raises(ValueError, match="time zone"):
        write_kick(BASE, out, created_at=datetime(2026, 10, 28, 12, 0))
    assert list(tmp_path.iterdir()) == []


def test_offset_with_seconds_is_rejected(tmp_path) -> None:
    out = tmp_path / "new"
    odd = datetime(2026, 10, 28, 12, 0, tzinfo=timezone(timedelta(seconds=30)))
    with pytest.raises(ValueError, match="whole minutes"):
        write_kick(BASE, out, created_at=odd)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("bad", ["2026-10-28T12:00:00Z", 1761652800, datetime.now(UTC).date()])
def test_non_datetime_created_at_is_rejected(tmp_path, bad) -> None:
    out = tmp_path / "new"
    with pytest.raises(TypeError, match="created_at"):
        write_kick(BASE, out, created_at=bad)  # type: ignore[arg-type]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        (FIXED_TIME, "2026-10-28T12:00:00+00:00"),
        (datetime(2026, 10, 28, 13, 0, tzinfo=timezone(timedelta(hours=1))),
         "2026-10-28T13:00:00+01:00"),
        (datetime(2026, 10, 28, 12, 0, 0, 999999, tzinfo=UTC), "2026-10-28T12:00:00+00:00"),
    ],
)
def test_aware_created_at_is_written_as_rfc3339(tmp_path, when, expected) -> None:
    _, json_path = write_kick(BASE, tmp_path, created_at=when)
    assert json.loads(json_path.read_text(encoding="utf-8"))["created_at"] == expected


def test_default_created_at_is_utc(tmp_path) -> None:
    _, json_path = write_kick(BASE, tmp_path)
    stamp = datetime.fromisoformat(json.loads(json_path.read_text(encoding="utf-8"))["created_at"])
    assert stamp.utcoffset() == timedelta(0)


# --- 4. only int and float are accepted as numbers -------------------------------------------

SCHEMA_PROPS = load_schema(KICK_SCHEMA_FILE)["properties"]
NUMERIC_FIELDS = {
    "seed": 7,
    "variants": 1,
    "bpm": 136,
    **{
        name: prop["default"]
        for name, prop in SCHEMA_PROPS.items()
        if prop.get("type") == "number" and "default" in prop
    },
    "sample_rate": 48000,
    "bit_depth": 24,
}


def test_numeric_field_list_covers_the_contract() -> None:
    numeric = {
        n for n, p in SCHEMA_PROPS.items()
        if p.get("type") in ("number", "integer") or "enum" in p
    }
    assert numeric == set(NUMERIC_FIELDS)


@pytest.mark.parametrize("field", sorted(NUMERIC_FIELDS))
@pytest.mark.parametrize(
    "wrap",
    [Decimal, Fraction, lambda v: complex(v, 0), lambda v: np.complex128(v)],
    ids=["Decimal", "Fraction", "complex", "np.complex128"],
)
def test_exotic_numeric_types_are_rejected_clearly(field: str, wrap) -> None:
    value = wrap(NUMERIC_FIELDS[field])  # in range, so only the type can be the problem
    with pytest.raises(KickParamsError) as exc:
        render_kick({**BASE, field: value})
    message = str(exc.value)
    assert field in message and "int or float" in message


def test_all_type_problems_are_listed_together() -> None:
    with pytest.raises(KickParamsError) as exc:
        render_kick({**BASE, "drive": Decimal("0.2"), "tone": Fraction(1, 2)})
    assert "drive" in str(exc.value) and "tone" in str(exc.value)


def test_type_problems_do_not_hide_other_problems() -> None:
    # pitch_start_hz and sample_rate: the schema would reject a 0, so a leaked error about the
    # internal placeholder would show up here.
    bad = {
        "seed": 7,
        "pitch_start_hz": Decimal("220"),
        "sample_rate": Fraction(48000),
        "tone": 99,
        "foo": 1,
        "typo": Decimal("1"),
    }
    with pytest.raises(KickParamsError) as exc:
        render_kick(bad)
    lines = str(exc.value).splitlines()[1:]
    for key in ("pitch_start_hz", "sample_rate", "typo"):
        assert f"- {key}: must be int or float, got " in str(exc.value), key
        assert sum(line.startswith(f"- {key}:") for line in lines) == 1, key
    assert any(line.startswith("- tone:") and "99" in line for line in lines)  # out of range
    assert any("'foo'" in line and "'typo'" in line for line in lines)  # unknown fields
    assert any("schema_version" in line for line in lines)  # missing


def test_exotic_required_field_is_not_reported_as_missing() -> None:
    with pytest.raises(KickParamsError) as exc:
        render_kick({"schema_version": "0.1", "seed": Decimal(7)})
    assert "seed: must be int or float" in str(exc.value)
    assert "required" not in str(exc.value)


def test_bool_is_still_rejected_by_the_schema() -> None:
    with pytest.raises(KickParamsError, match="drive"):
        render_kick({**BASE, "drive": True})
