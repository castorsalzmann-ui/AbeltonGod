"""WAV + sidecar metadata output. Files are never overwritten.

WAV encoding uses only the standard library (``struct``): mono PCM, 16- or 24-bit, no dither,
so the bytes are a pure function of the samples.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
from contextlib import suppress
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
    return _riff_wav(frames, int(sr), bit_depth)


def _riff_wav(frames: bytes, sr: int, bit_depth: int) -> bytes:
    """Mono PCM WAV (format tag 1) with a 44-byte header.

    RIFF chunks must be word aligned: a data chunk with an odd byte count (24-bit, odd sample
    count) gets one zero pad byte after it. The data chunk size stays the real audio size; the
    RIFF size includes the pad. Even-sized files are byte-identical to the stdlib ``wave``
    writer, which writes no pad byte.
    """
    width = bit_depth // 8
    pad = b"\x00" * (len(frames) % 2)
    fmt = struct.pack("<HHIIHH", 1, 1, sr, sr * width, width, bit_depth)
    body = (
        b"WAVE"
        + b"fmt " + struct.pack("<I", len(fmt)) + fmt
        + b"data" + struct.pack("<I", len(frames)) + frames + pad
    )
    return b"RIFF" + struct.pack("<I", len(body)) + body


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
    tried. Returns ``(wav_path, json_path)``.

    If the call fails for any reason after it created a file (disk full, permission, Ctrl+C,
    also during the ``return``), the files it created are closed and removed again and the
    original error is raised unchanged: no 0-byte file, no WAV without sidecar. Known
    exceptions (#94), all a few bytecodes wide or outside this call:

    - an interrupt between an ``open`` returning and its result being stored leaves that
      0-byte file (Python runs no line in between; the call cannot know it created it);
    - a second Ctrl+C during the clean-up stops the clean-up;
    - a file the clean-up cannot remove (e.g. held open by a virus scanner on Windows) stays;
      the original error is still raised. (When the sidecar name was taken and our WAV
      cannot be removed, that removal error is what is raised.);
    - removal is by path: if someone else deleted our fresh file and created a new one under
      the same name before the clean-up, that file is removed.

    ``created_at`` must be a time-zone aware ``datetime`` (default: now in UTC); it is written
    as RFC 3339 with its offset, to the second. A naive datetime is rejected, because its zone
    cannot be known.
    """
    stamp = _created_at_text(created_at)
    wav_bytes, audio, resolved = render_kick_wav(params)
    features = analyse(audio, resolved["sample_rate"])
    if features["peak_dbfs"] is None:
        # Issue #7: a sidecar always carries a real level. Silence is a bug, not a sample.
        raise ValueError("Render is silent (peak 0); refusing to write a WAV and sidecar.")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = safe_stem(name)

    base_meta: dict[str, Any] = {
        "schema_version": METADATA_SCHEMA_VERSION,
        "category": "kick",
        "engine": {"name": ENGINE_NAME, "version": ENGINE_VERSION},
        "parameters": resolved,
        "features": features,
        "bpm": resolved.get("bpm"),
        "key": None,
        "sha256": hashlib.sha256(wav_bytes).hexdigest(),
        "created_at": stamp,
    }
    if description:
        base_meta["description"] = description

    for _ in range(_MAX_NAME_ATTEMPTS):
        wav_path, json_path = _unique_pair(out, stem)
        meta = {"file": wav_path.name, **base_meta}
        Draft202012Validator(load_schema(METADATA_SCHEMA_FILE)).validate(meta)
        meta_text = json.dumps(meta, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        # Ownership (#94): a file belongs to this call once its file object is stored, which
        # the "x" open statement does itself, inside the one try below. Every later statement,
        # up to and including the return and the name-clash handling, is covered by its
        # clean-up. ``None`` = not created by this call: that path is never removed.
        # No nested ``try`` statement here: on CPython 3.13 an exception raised (by a trace
        # function) at a nested ``try:`` line skipped the outer handler in the #94 sweep.
        wav_file = json_file = None
        try:
            with suppress(FileExistsError):
                wav_file = open(wav_path, "xb")  # "x": never overwrite
            if wav_file is None:
                continue  # taken since the check: try the next counter
            with wav_file:
                wav_file.write(wav_bytes)
            with suppress(FileExistsError):
                json_file = open(json_path, "x", encoding="utf-8")
            if json_file is None:
                # Sidecar name taken since the check: remove our WAV, try the next counter.
                # Still inside the try, so an error or Ctrl+C here (also a failed removal)
                # reaches the clean-up below.
                _discard(wav_file, wav_path, swallow=False)
                wav_file = None
                continue
            with json_file:
                json_file.write(meta_text)
            return wav_path, json_path
        except BaseException:
            # Disk full, permission, Ctrl+C ...: remove our files, sidecar first, and raise
            # the original error unchanged (clean-up errors are swallowed).
            _discard(json_file, json_path, swallow=True)
            _discard(wav_file, wav_path, swallow=True)
            raise
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


class EngineVersionMismatch(ValueError):
    """A sidecar was written by a different engine (name or version) than the running one.

    Since #35 ``ENGINE_VERSION`` changes whenever rendered bytes change, so re-rendering such a
    sidecar would silently give different bytes than the WAV it describes.
    """

    def __init__(self, path: Path, sidecar_engine: dict[str, str]) -> None:
        self.path = path
        self.sidecar_engine = dict(sidecar_engine)
        self.current_engine = {"name": ENGINE_NAME, "version": ENGINE_VERSION}
        super().__init__(
            f"{path}: written by engine {sidecar_engine.get('name')} "
            f"{sidecar_engine.get('version')}, this is {ENGINE_NAME} {ENGINE_VERSION}. "
            "A re-render would not reproduce its WAV. Pass allow_engine_mismatch=True to "
            "render its parameters with the current engine anyway (different bytes)."
        )


def rerender_from_sidecar(json_path: str | Path, *, allow_engine_mismatch: bool = False) -> bytes:
    """Re-render the WAV bytes described by a sidecar file.

    The caller compares the result with ``sha256`` in the sidecar. Identity is only guaranteed
    on the same platform and NumPy build; see the PR #8 notes on cross-OS determinism.

    Raises :class:`EngineVersionMismatch` if the sidecar's engine name or version differs from
    the running engine, because the bytes would differ (#35). With
    ``allow_engine_mismatch=True`` the parameters are rendered with the current engine; the
    result is then a new render, not a reproduction.
    """
    path = Path(json_path)
    meta = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator(load_schema(METADATA_SCHEMA_FILE)).validate(meta)
    engine = meta["engine"]
    if not allow_engine_mismatch and (
        engine["name"] != ENGINE_NAME or engine["version"] != ENGINE_VERSION
    ):
        raise EngineVersionMismatch(path, engine)
    wav_bytes, _, _ = render_kick_wav(_upgrade_sidecar_params(meta["parameters"]))
    return wav_bytes


def _created_at_text(created_at: datetime | None) -> str:
    if created_at is None:
        created_at = datetime.now(UTC)
    if not isinstance(created_at, datetime):
        raise TypeError(f"created_at must be a datetime, got {type(created_at).__name__}")
    offset = created_at.utcoffset()
    if offset is None:
        raise ValueError(
            f"created_at has no time zone ({created_at.isoformat()}); pass an aware datetime, "
            "e.g. datetime.now(UTC)"
        )
    if offset.total_seconds() % 60:
        raise ValueError(f"created_at time zone offset {offset} is not whole minutes (RFC 3339)")
    return created_at.isoformat(timespec="seconds")


def _discard(file: Any, path: Path, *, swallow: bool) -> None:
    """Close and remove a file this call created (``file`` is its file object; ``None`` means
    the call did not create ``path``, which is then left alone). Closing first matters on
    Windows, where an open file cannot be deleted; ``close`` is a no-op on a closed file.
    With ``swallow``, every ``OSError`` is ignored so that the error being propagated reaches
    the caller unchanged ("already gone" is always ignored)."""
    if file is None:
        return
    try:
        file.close()
    except OSError:
        if not swallow:
            raise
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError:
        if not swallow:
            raise


def _taken(path: Path) -> bool:
    # lexists: a dangling symlink also blocks the name (open(..., "x") refuses it).
    return os.path.lexists(path)


def _upgrade_sidecar_params(params: Any) -> Any:
    """kick-params 0.1 -> 0.2 changed only a default (pitch_decay_ms 40 -> 15, issue #7).
    A sidecar stores the fully resolved parameters, so a 0.1 sidecar that names
    pitch_decay_ms renders the same samples under 0.2. Anything else is left for validation
    to reject, never guessed."""
    if (
        isinstance(params, dict)
        and params.get("schema_version") == "0.1"
        and "pitch_decay_ms" in params
    ):
        return {**params, "schema_version": "0.2"}
    return params


def _unique_pair(out: Path, stem: str) -> tuple[Path, Path]:
    candidate = stem
    counter = 1
    while _taken(out / f"{candidate}.wav") or _taken(out / f"{candidate}.json"):
        counter += 1
        candidate = f"{stem}_{counter:03d}"
    return out / f"{candidate}.wav", out / f"{candidate}.json"
