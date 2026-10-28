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
_MAX_STEM_LENGTH = 80
_MAX_NAME_ATTEMPTS = 1000
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def encode_wav(audio: np.ndarray, sr: int, bit_depth: int) -> bytes:
    if bit_depth not in (16, 24):
        raise ValueError(f"bit_depth must be 16 or 24, got {bit_depth}")
    bit_depth = int(bit_depth)
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
        w.setframerate(int(sr))
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
    never touched; if a name is taken between the check and the write, the next counter is
    tried. If the sidecar cannot be written, the WAV written by this call is removed again, so
    no orphan is left. Returns ``(wav_path, json_path)``.
    """
    wav_bytes, audio, resolved = render_kick_wav(params)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = safe_stem(name)

    base_meta: dict[str, Any] = {
        "schema_version": METADATA_SCHEMA_VERSION,
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
        base_meta["description"] = description

    for _ in range(_MAX_NAME_ATTEMPTS):
        wav_path, json_path = _unique_pair(out, stem)
        meta = {"file": wav_path.name, **base_meta}
        Draft202012Validator(load_schema(METADATA_SCHEMA_FILE)).validate(meta)
        meta_text = json.dumps(meta, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        try:
            with open(wav_path, "xb") as f:  # "x": never overwrite
                f.write(wav_bytes)
        except FileExistsError:
            continue  # taken since the check: try the next counter
        try:
            with open(json_path, "x", encoding="utf-8") as f:
                f.write(meta_text)
        except BaseException:
            wav_path.unlink(missing_ok=True)  # only the file this call just created
            if json_path.exists():
                continue
            raise
        return wav_path, json_path
    raise FileExistsError(
        f"No free file name for '{stem}' in {out} after {_MAX_NAME_ATTEMPTS} tries"
    )


def safe_stem(name: str) -> str:
    """File-system safe stem: ASCII letters, digits, ``.``, ``_``, ``-``; max 80 characters;
    never a reserved Windows device name (CON, NUL, COM1 …)."""
    stem = _SAFE_NAME.sub("-", name).strip("-.") or "kick"
    stem = stem[:_MAX_STEM_LENGTH].rstrip("-.") or "kick"
    if stem.split(".")[0].upper() in _WINDOWS_RESERVED:
        stem = f"kick-{stem}"
    return stem


def rerender_from_sidecar(json_path: str | Path) -> bytes:
    """Re-render the WAV bytes described by a sidecar file.

    The caller compares the result with ``sha256`` in the sidecar. Identity is only guaranteed
    on the same platform and NumPy build; see the PR #8 notes on cross-OS determinism.
    """
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
