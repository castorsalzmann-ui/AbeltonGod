"""Render service: runs the kick engine in a worker thread and returns result objects (no Qt).

Every outcome is a :class:`RenderResult`: invalid parameters, an unwritable folder, a full
disk, a cancel and unexpected engine errors come back as an :class:`ErrorInfo` (or
``cancelled``), never as an exception in the caller and never as a hang. A stopped or failed
request is never ``ok``.

Naming and variants follow ``python -m audio_engine.kick`` (cli.plan): the same preset, seed,
overrides and variant count give the same files and the same bytes.
"""

from __future__ import annotations

import errno
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from audio_engine.io import write_kick
from audio_engine.params import KickParamsError, resolve_kick_params
from audio_engine.presets import UnknownPresetError, describe
from audio_engine.variants import make_variants

MAX_DESCRIPTION = 500  # sample-metadata: description maxLength (same cut as the CLI)

Writer = Callable[..., tuple[Path, Path]]


@dataclass(frozen=True)
class RenderJob:
    """What to render. ``request`` is a complete kick-params object (incl. seed, variants)."""

    request: dict[str, Any]
    out_dir: Path
    preset: str
    overrides: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ErrorInfo:
    kind: str  # "invalid_params" | "output" | "disk_full" | "internal"
    message: str  # German, for the user
    detail: str  # original text, for the log


@dataclass(frozen=True)
class RenderedFile:
    index: int
    wav_path: Path
    json_path: Path
    seed: int
    params: dict[str, Any]  # the variant's request-level parameters
    peak_dbfs: float | None


@dataclass(frozen=True)
class RenderResult:
    job: RenderJob
    files: tuple[RenderedFile, ...]
    error: ErrorInfo | None = None
    cancelled: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None and not self.cancelled


Progress = Callable[[int, int], None]


def run_job(
    job: RenderJob,
    cancel: threading.Event | None = None,
    progress: Progress | None = None,
    writer: Writer = write_kick,
) -> RenderResult:
    """Run ``job`` in the calling thread. Never raises (except for process-level exits)."""
    cancel = cancel or threading.Event()
    files: list[RenderedFile] = []
    try:
        variants, stems, descriptions = _plan(job)
    except (KickParamsError, UnknownPresetError, ValueError, KeyError, TypeError) as exc:
        return RenderResult(job, (), ErrorInfo("invalid_params", _first_line(exc), str(exc)))
    except Exception as exc:  # noqa: BLE001 - a result object, not a crash
        return RenderResult(job, (), _internal(exc))

    total = len(variants)
    try:
        for i, (params, stem, text) in enumerate(zip(variants, stems, descriptions, strict=True)):
            if cancel.is_set():
                return RenderResult(job, tuple(files), cancelled=True)
            wav, sidecar = writer(params, job.out_dir, name=stem, description=text)
            files.append(RenderedFile(
                i, Path(wav), Path(sidecar), int(params["seed"]), dict(params), _peak(sidecar)
            ))
            if progress:
                progress(i + 1, total)
    except OSError as exc:
        return RenderResult(job, tuple(files), _output_error(exc, len(files), total))
    except Exception as exc:  # noqa: BLE001
        return RenderResult(job, tuple(files), _internal(exc))
    if cancel.is_set() and len(files) < total:  # pragma: no cover - loop returns earlier
        return RenderResult(job, tuple(files), cancelled=True)
    return RenderResult(job, tuple(files))


def _plan(job: RenderJob) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    if str(job.out_dir).strip() in ("", "."):  # Path("") is "." = the current folder
        raise ValueError("Kein Ausgabeordner angegeben.")
    request = dict(job.request)
    base = resolve_kick_params(request)
    variants = make_variants(request, base["variants"])  # all made and checked before writing
    suffix = "_custom" if job.overrides else ""
    stem = f"{job.preset}_s{base['seed']}"
    stems = [f"{stem}_v{i}{suffix}" for i in range(len(variants))]
    text = describe(job.preset, "kick")
    custom = ", ".join(f"{k}={v}" for k, v in job.overrides.items())
    n, seed = len(variants), base["seed"]
    descriptions = []
    for i in range(n):
        d = f"Preset {job.preset}: {text} Variant {i} of {n}, base seed {seed}."
        if custom:
            d += f" Custom values: {custom}."
        descriptions.append(d[:MAX_DESCRIPTION])
    return variants, stems, descriptions


def _peak(sidecar: Path) -> float | None:
    try:
        meta = json.loads(Path(sidecar).read_text(encoding="utf-8"))
        return meta["features"]["peak_dbfs"]
    except (OSError, ValueError, KeyError):
        return None


def _first_line(exc: BaseException) -> str:
    text = str(exc).strip()
    return "Ungültige Parameter: " + " ".join(text.split("\n")[:4])


def _output_error(exc: OSError, written: int, total: int) -> ErrorInfo:
    tail = f" {written} von {total} Dateien wurden vorher geschrieben."
    if exc.errno == errno.ENOSPC:
        return ErrorInfo("disk_full", "Der Datenträger ist voll." + tail, str(exc))
    return ErrorInfo(
        "output", f"Der Ausgabeordner ist nicht beschreibbar: {exc}." + tail, str(exc)
    )


def _internal(exc: BaseException) -> ErrorInfo:
    return ErrorInfo("internal", f"Unerwarteter Fehler: {type(exc).__name__}: {exc}", repr(exc))


class RenderHandle:
    """A running job. ``wait`` returns True once the result is there."""

    def __init__(self) -> None:
        self._cancel = threading.Event()
        self._done = threading.Event()
        self.result: RenderResult | None = None

    def cancel(self) -> None:
        self._cancel.set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._done.wait(timeout)

    @property
    def done(self) -> bool:
        return self._done.is_set()


class RenderService:
    def __init__(self, writer: Writer = write_kick) -> None:
        self._writer = writer

    def start(
        self,
        job: RenderJob,
        on_progress: Progress | None = None,
        on_done: Callable[[RenderResult], None] | None = None,
    ) -> RenderHandle:
        """Start ``job`` in a daemon thread. Callbacks run in that thread."""
        handle = RenderHandle()

        def work() -> None:
            try:
                result = run_job(job, handle._cancel, on_progress, self._writer)
            except BaseException as exc:  # noqa: BLE001 - the handle must always finish
                result = RenderResult(job, (), _internal(exc))
            handle.result = result
            handle._done.set()
            if on_done:
                try:
                    on_done(result)
                except Exception:  # noqa: BLE001 - a broken callback must not kill the thread
                    pass

        threading.Thread(target=work, name="render-job", daemon=True).start()
        return handle
