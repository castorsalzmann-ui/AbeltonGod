"""WAV + sidecar metadata output. Files are never overwritten.

WAV encoding uses only the standard library (``struct``): mono PCM, 16- or 24-bit, no dither,
so the bytes are a pure function of the samples.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import struct
from contextlib import suppress
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

import numpy as np
from jsonschema import Draft202012Validator

from .categories import get_category
from .kick import render_kick  # noqa: F401  (name kept: test harness patches io.render_kick)
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
    if audio.ndim not in (1, 2) or (audio.ndim == 2 and audio.shape[1] != 2):
        raise ValueError(f"audio must have shape (n,) or (n, 2), got {audio.shape}")
    channels = 1 if audio.ndim == 1 else 2  # (n, 2) is written interleaved (laser, #416)
    ints = np.round(np.clip(audio, -1.0, 1.0) * full_scale).astype("<i4").reshape(-1)
    if bit_depth == 16:
        frames = ints.astype("<i2").tobytes()
    else:
        frames = ints.view(np.uint8).reshape(-1, 4)[:, :3].tobytes()  # little-endian low 3 bytes
    return _riff_wav(frames, int(sr), bit_depth, channels)


def wav_samples(wav: bytes) -> np.ndarray:
    """Integer sample values (int64) of a WAV written by :func:`encode_wav`.

    Reads only this module's own layout (44-byte header, mono PCM 16 or 24 bit); anything
    else raises ``ValueError``. Used by the -60 dB rule, which the contract defines on the
    samples written to the WAV.
    """
    if len(wav) < 44 or wav[:4] != b"RIFF" or wav[8:16] != b"WAVEfmt " or wav[36:40] != b"data":
        raise ValueError("not a WAV in the encode_wav layout")
    tag, channels, _, _, width, bits = struct.unpack("<HHIIHH", wav[20:36])
    if (tag, channels) != (1, 1) or bits not in (16, 24) or width != bits // 8:
        raise ValueError(f"unsupported WAV format: tag {tag}, {channels} channel(s), {bits} bit")
    (size,) = struct.unpack("<I", wav[40:44])
    frames = wav[44 : 44 + size]
    if len(frames) != size or size % width:
        raise ValueError("WAV data chunk is truncated")
    if bits == 16:
        return np.frombuffer(frames, dtype="<i2").astype(np.int64)
    raw = np.frombuffer(frames, dtype=np.uint8).reshape(-1, 3).astype(np.int64)
    value = raw[:, 0] | (raw[:, 1] << 8) | (raw[:, 2] << 16)
    return np.where(value >= 1 << 23, value - (1 << 24), value)


def _riff_wav(frames: bytes, sr: int, bit_depth: int, channels: int = 1) -> bytes:
    """PCM WAV (format tag 1, mono or interleaved stereo) with a 44-byte header.

    RIFF chunks must be word aligned: a data chunk with an odd byte count (24-bit, odd sample
    count) gets one zero pad byte after it. The data chunk size stays the real audio size; the
    RIFF size includes the pad. Even-sized files are byte-identical to the stdlib ``wave``
    writer, which writes no pad byte.
    """
    width = bit_depth // 8
    pad = b"\x00" * (len(frames) % 2)
    fmt = struct.pack("<HHIIHH", 1, channels, sr, sr * width * channels, width * channels,
                      bit_depth)
    body = (
        b"WAVE"
        + b"fmt " + struct.pack("<I", len(fmt)) + fmt
        + b"data" + struct.pack("<I", len(frames)) + frames + pad
    )
    return b"RIFF" + struct.pack("<I", len(body)) + body


def render_sample_wav(
    category: str, params: dict[str, Any]
) -> tuple[bytes, np.ndarray, dict[str, Any]]:
    """Render and encode a sample of ``category``. Returns ``(wav_bytes, audio, resolved)``.

    Raises :class:`audio_engine.categories.CategoryUnavailable` if the category has no renderer.
    """
    audio, resolved = get_category(category).render(params)
    return encode_wav(audio, resolved["sample_rate"], resolved["bit_depth"]), audio, resolved


def render_kick_wav(params: dict[str, Any]) -> tuple[bytes, np.ndarray, dict[str, Any]]:
    """Render and encode. Returns ``(wav_bytes, audio, resolved_params)``."""
    return render_sample_wav("kick", params)


def _renderer(category: str) -> Any:
    """``render_kick_wav`` for the kick (tests patch that name), the generic one otherwise."""
    return render_kick_wav if category == "kick" else partial(render_sample_wav, category)


def write_sample(
    category: str,
    params: dict[str, Any],
    out_dir: str | Path,
    name: str | None = None,
    description: str | None = None,
    created_at: datetime | None = None,
) -> tuple[Path, Path]:
    """Render a sample of ``category`` and write its WAV + sidecar; see :func:`write_kick`.

    ``name`` defaults to the category's default stem. Raises
    :class:`audio_engine.categories.CategoryUnavailable` before anything is rendered or written
    if the category has no renderer.
    """
    cat = get_category(category)
    return write_kick(
        params, out_dir, cat.default_stem if name is None else name, description, created_at,
        category=category,
    )


def write_kick(
    params: dict[str, Any],
    out_dir: str | Path,
    name: str = "kick",
    description: str | None = None,
    created_at: datetime | None = None,
    *,
    category: str = "kick",
) -> tuple[Path, Path]:
    """Render a kick and write ``<name>.wav`` + ``<name>.json`` into ``out_dir``.

    This function is the one implementation for every category (``category`` defaults to
    ``"kick"``; :func:`write_sample` is the category-first entry). It keeps its name because
    the interrupt sweeps and the bridge/library tests trace and patch ``write_kick``.

    If either file exists, a counter suffix (``_002``, ``_003`` …) is added. Existing files are
    never touched; if a name is taken between the check and the write, the next counter is
    tried. Returns ``(wav_path, json_path)``.

    If the call fails for any reason after it created a file (disk full, permission, Ctrl+C),
    the files it created are closed and removed again and the original error is raised
    unchanged: no 0-byte file, no WAV without sidecar. Known exceptions (#94, #96), all a few
    bytecodes wide or outside this call:

    - an interrupt during or right after an ``open``, before its result is stored, leaves that
      0-byte file (the call cannot know it created it). Measured in the review of PR #205
      with an interrupt raised by SIGALRM (the script is not in the repo): a 0-byte remainder
      occurred in both modes (13.7 % with ``"x"`` and an encoding,
      10.3 % with ``"xb"``), so the mode is not established as the cause;
    - the last bytecodes of the ``return`` are outside the handler: an exception injected there
      by a trace function leaves the complete pair. Whether a real Ctrl+C can land there is
      not established;
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
    # One line on purpose: the interrupt-sweep tests address write_kick by line number (#183).
    cat, stamp = get_category(category), _created_at_text(created_at)
    wav_bytes, audio, resolved = _renderer(category)(params)
    features = cat.features(audio, resolved)
    if features["peak_dbfs"] is None:
        # Issue #7: a sidecar always carries a real level. Silence is a bug, not a sample.
        raise ValueError("Render is silent (peak 0); refusing to write a WAV and sidecar.")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = safe_stem(name, cat.default_stem)

    base_meta: dict[str, Any] = {
        "schema_version": cat.metadata_schema_version,
        "category": cat.name,
        "engine": cat.engine,
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


def safe_stem(name: str, default: str = "kick") -> str:
    """File-system safe stem: ASCII letters, digits, ``.``, ``_``, ``-``; max 80 characters;
    never a reserved Windows device name (CON, NUL, COM1 …). ``default`` is used for a name
    with no usable characters and as prefix for a device name (``kick`` unless the category
    says otherwise)."""
    stem = _SAFE_NAME.sub("-", name).strip("-.") or default
    stem = stem[:_MAX_STEM_LENGTH].rstrip("-.") or default
    if stem.split(".")[0].upper() in _WINDOWS_RESERVED:
        stem = f"{default}-{stem}"
    return stem


class EngineVersionMismatch(ValueError):
    """A sidecar was written by a different engine (name or version) than the running one.

    Since #35 ``ENGINE_VERSION`` changes whenever rendered bytes change, so re-rendering such a
    sidecar would silently give different bytes than the WAV it describes.
    """

    def __init__(
        self,
        path: Path,
        sidecar_engine: dict[str, str],
        current_engine: dict[str, str] | None = None,
    ) -> None:
        if current_engine is None:
            current_engine = get_category("kick").engine
        self.path = path
        self.sidecar_engine = dict(sidecar_engine)
        self.current_engine = dict(current_engine)
        super().__init__(
            f"{path}: written by engine {sidecar_engine.get('name')} "
            f"{sidecar_engine.get('version')}, this is {current_engine['name']} "
            f"{current_engine['version']}. "
            "A re-render would not reproduce its WAV. Pass allow_engine_mismatch=True to "
            "render its parameters with the current engine anyway (different bytes)."
        )


def rerender_from_sidecar(json_path: str | Path, *, allow_engine_mismatch: bool = False) -> bytes:
    """Re-render the WAV bytes described by a sidecar file.

    The caller compares the result with ``sha256`` in the sidecar. Identity is only guaranteed
    on the same platform and NumPy build; see the PR #8 notes on cross-OS determinism.

    Raises :class:`audio_engine.categories.CategoryUnavailable` if the sidecar's category has no
    renderer in this engine (e.g. ``clap`` before the clap voice exists).

    Raises :class:`EngineVersionMismatch` if the sidecar's engine name or version differs from
    the running engine of its category, because the bytes would differ (#35). With
    ``allow_engine_mismatch=True`` the parameters are rendered with the current engine; the
    result is then a new render, not a reproduction.
    """
    path = Path(json_path)
    meta = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator(load_schema(METADATA_SCHEMA_FILE)).validate(meta)
    # Refuse by category first: a clap sidecar must never reach kick-param validation, and a
    # category without a renderer is an error of its own (CategoryUnavailable).
    cat = get_category(meta["category"])
    _check_sidecar_facts(meta, path)
    engine = meta["engine"]
    if not allow_engine_mismatch and engine != cat.engine:
        raise EngineVersionMismatch(path, engine, cat.engine)
    params = meta["parameters"]
    if cat.name == "kick":
        params = _upgrade_sidecar_params(params)
    wav_bytes, _, _ = render_sample_wav(cat.name, params)
    return wav_bytes


class SidecarError(ValueError):
    """A sidecar passes the JSON schema but contradicts itself or its WAV (#85)."""


_RFC3339 = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})", re.ASCII
)


def _all_finite(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_all_finite(v) for v in value.values())
    if isinstance(value, list):
        return all(_all_finite(v) for v in value)
    return True


def _check_sidecar_facts(meta: dict[str, Any], path: Path) -> None:
    """What the JSON schema cannot say (#85, option a, standard library only).

    - every number is finite (``NaN``, ``Infinity`` and ``1e999`` all parse to non-finite floats);
    - ``created_at`` is a strict RFC 3339 date-time: ``T`` separator, seconds, ``Z`` or a
      ``+hh:mm`` offset, and a real calendar time (``datetime.fromisoformat``);
    - ``file`` names the WAV that belongs to this sidecar (same folder, same stem);
    - if that WAV exists, ``sha256`` is the hash of its bytes. A missing WAV is not an error
      (the sidecar alone is enough to re-render); then ``sha256`` is not checked.
    """
    if not _all_finite(meta):
        raise SidecarError("sidecar contains a non-finite number")
    stamp = meta["created_at"]
    if not _RFC3339.fullmatch(stamp):
        raise SidecarError(f"created_at {stamp!r} is not an RFC 3339 date-time")
    try:
        datetime.fromisoformat(stamp)
    except ValueError as exc:
        raise SidecarError(f"created_at {stamp!r} is not a valid date-time: {exc}") from exc
    wav = path.with_suffix(".wav")
    if meta["file"] != wav.name:
        raise SidecarError(f"file {meta['file']!r} is not the WAV of this sidecar ({wav.name!r})")
    if "sha256" in meta and wav.is_file():
        if hashlib.sha256(wav.read_bytes()).hexdigest() != meta["sha256"]:
            raise SidecarError(f"sha256 does not match {wav.name}")


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
