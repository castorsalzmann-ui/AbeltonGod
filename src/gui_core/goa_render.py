"""Goa render service (no Qt): writes the output folder exactly as the CLI does.

``run_goa_job`` parses the same ``--flag=value`` list the CLI would get, turns it into the
module's keyword arguments (:func:`gui_core.goa.call_of`) and calls ``write_track`` /
``write_melody``. Every failure comes back as an :class:`ErrorInfo`; nothing raises.
Existing files are never overwritten (the modules refuse and write nothing).
"""

from __future__ import annotations

import errno
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from audio_engine import goa_arrangement, goa_melody

from .goa import ARRANGEMENT, OptionError, call_of, parse_argv
from .render import ErrorInfo
from .tasks import TaskHandle, start_task


@dataclass(frozen=True)
class GoaJob:
    mode: str
    argv: tuple[str, ...]  # complete, including --out=


@dataclass(frozen=True)
class GoaResult:
    job: GoaJob
    out_dir: Path | None = None
    mid_path: Path | None = None
    readme_path: Path | None = None
    readme_text: str = ""
    sample_paths: tuple[Path, ...] = ()
    error: ErrorInfo | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def run_goa_job(job: GoaJob) -> GoaResult:
    try:
        call = call_of(job.mode, parse_argv(job.mode, job.argv))
    except OptionError as exc:
        return GoaResult(job, error=ErrorInfo("invalid_params", f"Ungültige Option: {exc}",
                                              str(exc)))
    except (ValueError, KeyError, TypeError) as exc:
        text = " ".join(str(exc).split())
        return GoaResult(job, error=ErrorInfo("invalid_params", f"Ungültige Optionen: {text}",
                                              str(exc)))
    out = Path(call.out_dir)
    if str(call.out_dir).strip() in ("", "."):
        return GoaResult(job, error=ErrorInfo("invalid_params", "Kein Ausgabeordner angegeben.",
                                              "empty --out"))
    try:
        if job.mode == ARRANGEMENT:
            mid, readme = goa_arrangement.write_track(
                out, render_samples=call.render_samples, **call.kwargs)
        else:
            mid, readme = goa_melody.write_melody(out, **call.kwargs)
        text = readme.read_text(encoding="utf-8")
        samples = tuple(sorted((out / "samples").glob("*.wav"))) if job.mode == ARRANGEMENT \
            else ()
    except FileExistsError as exc:
        return GoaResult(job, out, error=ErrorInfo(
            "exists", "In diesem Ordner liegen schon Dateien dieses Laufs. Es wurde nichts "
            f"überschrieben. Bitte einen neuen Ordner wählen. ({exc})", str(exc)))
    except OSError as exc:
        if exc.errno == errno.ENOSPC:
            return GoaResult(job, out, error=ErrorInfo(
                "disk_full", "Der Datenträger ist voll. Der Ordner kann unvollständig sein.",
                str(exc)))
        return GoaResult(job, out, error=ErrorInfo(
            "output", f"Der Ausgabeordner ist nicht beschreibbar: {exc}.", str(exc)))
    except ValueError as exc:  # generator refused the options: nothing was written
        text = " ".join(str(exc).split())
        return GoaResult(job, out, error=ErrorInfo(
            "invalid_params", f"Ungültige Optionen: {text}", str(exc)))
    except Exception as exc:  # noqa: BLE001
        return GoaResult(job, out, error=ErrorInfo(
            "internal", f"Unerwarteter Fehler: {type(exc).__name__}: {exc}", repr(exc)))
    return GoaResult(job, out, mid, readme, text, samples)


class GoaService:
    def __init__(self, runner: Callable[[GoaJob], GoaResult] = run_goa_job) -> None:
        self._runner = runner

    def start(self, job: GoaJob,
              on_done: Callable[[GoaResult], None] | None = None) -> TaskHandle:
        def work() -> GoaResult:
            try:
                return self._runner(job)
            except BaseException as exc:  # noqa: BLE001
                return GoaResult(job, error=ErrorInfo(
                    "internal", f"Unerwarteter Fehler: {type(exc).__name__}: {exc}", repr(exc)))

        return start_task(work, (lambda h: on_done(h.result)) if on_done else None,
                          name="goa-job")
