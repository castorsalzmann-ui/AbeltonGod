"""WAV + sidecar metadata output. Files are never overwritten.

WAV encoding uses only the standard library (``wave``): mono PCM, 16- or 24-bit, no dither,
so the bytes are a pure function of the samples.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import wave
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from jsonschema import Draft202012Validator

from . import ENGINE_NAME, ENGINE_VERSION
from .analysis import analyse
from .kick import render_kick
from .params import METADATA_SCHEMA_FILE, load_schema

METADATA_SCHEMA_VERSION = "0.1"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def encode_wav(audio: np.ndarray, sr: int, bit_depth: int) -> bytes:
    if bit_depth not in (16, 24):
        raise ValueError(f"bit_depth must be 16 or 24, got {bit_depth}")
    if not np.all(np.isfinite(audio)):
        raise ValueError("Audio contains NaN or Inf.")
    full_scale = 2 ** (bit_depth - 1) - 1
    ints = np.round(np.clip(audio, -1.0, 1.0) * full_scale).astype("<i4")
    if bit_depth == 16:
        frames = ints.astype("<i2").tobytes()
    else:
        frames = ints.view(np.uint8).reshape(-1, 4)[:, :3].tobytes()  # little-endian low 3 bytes
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(bit_depth // 8)
        w.setframerate(sr)
        w.writeframes(frames)
    return buf.getvalue()


def render_kick_wav(params: dict[str, Any]) -> tuple[bytes, np.ndarray, dict[str, Any]]:
    """Render and encode. Returns ``(wav_bytes, audio, resolved_params)``."""
    audio, resolved = render_kick(params)
    return encode_wav(audio, resolved["sample_rate"], resolved["bit_depth"]), audio, resolved


def write_kick(
    params: dict[str, Any],
    out_dir: str | Path,
    name: str = "kick",
    description: str | None = None,
    created_at: datetime | None = None,
) -> tuple[Path, Path]:
    """Render a kick and write ``<name>.wav`` + ``<name>.json`` into ``out_dir``.

    If either file exists, a counter suffix (``_002``, ``_003`` …) is added. Existing files are
    never touched. Returns ``(wav_path, json_path)``.
    """
    wav_bytes, audio, resolved = render_kick_wav(params)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    wav_path, json_path = _unique_pair(out, _SAFE_NAME.sub("-", name).strip("-") or "kick")

    meta: dict[str, Any] = {
        "schema_version": METADATA_SCHEMA_VERSION,
        "file": wav_path.name,
        "category": "kick",
        "engine": {"name": ENGINE_NAME, "version": ENGINE_VERSION},
        "parameters": resolved,
        "features": analyse(audio, resolved["sample_rate"]),
        "bpm": resolved.get("bpm"),
        "key": None,
        "sha256": hashlib.sha256(wav_bytes).hexdigest(),
        "created_at": (created_at or datetime.now(UTC)).isoformat(timespec="seconds"),
    }
    if description:
        meta["description"] = description
    Draft202012Validator(load_schema(METADATA_SCHEMA_FILE)).validate(meta)

    # "x" mode: fail instead of overwriting if something appeared in the meantime.
    with open(wav_path, "xb") as f:
        f.write(wav_bytes)
    with open(json_path, "x", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return wav_path, json_path


def rerender_from_sidecar(json_path: str | Path) -> bytes:
    """Re-render the WAV bytes described by a sidecar file."""
    meta = json.loads(Path(json_path).read_text(encoding="utf-8"))
    Draft202012Validator(load_schema(METADATA_SCHEMA_FILE)).validate(meta)
    wav_bytes, _, _ = render_kick_wav(meta["parameters"])
    return wav_bytes


def _unique_pair(out: Path, stem: str) -> tuple[Path, Path]:
    candidate = stem
    counter = 1
    while (out / f"{candidate}.wav").exists() or (out / f"{candidate}.json").exists():
        counter += 1
        candidate = f"{stem}_{counter:03d}"
    return out / f"{candidate}.wav", out / f"{candidate}.json"
