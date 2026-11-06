"""Blaster service layer (no Qt): settings, shots, shot history, bank export.

Pulling the trigger renders the next shot through ``audio_engine.laser.render_laser(params,
seed)`` (contract ``contracts/laser-params.schema.json``, float64 ``(n, 2)``), keeps it in a
short history and plays a 16-bit copy through the preview backend. Nothing here judges how a
shot sounds, and nothing here talks to Live.

The window renders off the GUI thread: :meth:`BlasterSession.render_shot` is pure (safe in a
worker thread), :meth:`BlasterSession.commit` runs in the GUI thread and touches the history.
:meth:`BlasterSession.fire` is both in one call (tests, scripts).

Same settings + same seed give the same samples (the engine's contract) and therefore the same
WAV bytes (``audio_engine.io.encode_wav`` is deterministic).
"""

from __future__ import annotations

import importlib
import importlib.util
import math
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from audio_engine.io import encode_wav
from library.layout import LibraryLayout

from .blaster_params import (  # noqa: F401 - re-exported for the window and the tests
    SEED_MAX,
    BlasterError,
    BlasterSettings,
    preview_params,
    to_engine_params,
)
from .preview import NoBackend, PlaybackBackend

SAMPLE_RATE = 48000  # contract default; sent in every request
BIT_DEPTH = 24
MAX_SHOT_SECONDS = 10.0
HISTORY_LIMIT = 40
BANK_MAX = 64
PLAY_BITS = 16


@dataclass(frozen=True)
class Dimension:
    key: str  # the contract's `family`
    label: str  # German, short
    hint: str  # German: how the family is built (not how it sounds)
    accent: str  # glow colour of the blaster for this dimension


DIMENSIONS: tuple[Dimension, ...] = (
    Dimension("pew", "Klassik", "Sinus-Träger mit Sweep", "#ff4a2a"),
    Dimension("plasma", "Plasma", "Bandbegrenzter Sägezahn-Träger", "#ff3df0"),
    Dimension("ion", "Ion", "Sinus mit zwei unharmonischen Obertönen", "#27e0ff"),
    Dimension("rift", "Riss", "Zwei gegenläufige Sweeps", "#8b5cff"),
    Dimension("subboom", "Sub-Boom", "Sweep plus Sub-Ebene", "#ffb21f"),
    Dimension("glitch", "Glitch", "Gehaltene Tonhöhenstufen mit Gate", "#3dff8c"),
)
DIMENSION_KEYS = tuple(d.key for d in DIMENSIONS)


def dimension(key: str) -> Dimension:
    for d in DIMENSIONS:
        if d.key == key:
            return d
    raise ValueError(f"Unbekannte Dimension: {key}")




# ---- engine adapter -----------------------------------------------------------------------
class LaserEngine(Protocol):
    sample_rate: int

    def render(self, params: dict[str, Any], seed: int) -> np.ndarray:
        """Float samples in [-1, 1]: shape ``(n, 2)`` (stereo) or ``(n,)``."""
        ...


class ModuleLaserEngine:
    """Wraps ``audio_engine.laser.render_laser``."""

    def __init__(self, module: Any) -> None:
        self._render = module.render_laser
        self.sample_rate = SAMPLE_RATE

    def render(self, params: dict[str, Any], seed: int) -> np.ndarray:
        return np.asarray(self._render(params, seed))


def load_engine() -> tuple[LaserEngine | None, str]:
    """The real engine, or ``(None, German reason)`` if ``audio_engine.laser`` is not loadable."""
    try:
        if importlib.util.find_spec("audio_engine.laser") is None:
            return None, "Laser-Engine nicht verfügbar (audio_engine.laser fehlt)."
        module = importlib.import_module("audio_engine.laser")
        return ModuleLaserEngine(module), ""
    except Exception as exc:  # noqa: BLE001 - a message in the window, not a crash on start
        return None, f"Laser-Engine nicht ladbar: {type(exc).__name__}: {exc}"


# ---- shots ------------------------------------------------------------------------------
@dataclass(frozen=True)
class Shot:
    index: int  # 1-based, per session
    seed: int
    settings: BlasterSettings
    params: dict[str, Any]
    samples: np.ndarray = field(repr=False, compare=False)
    sample_rate: int = SAMPLE_RATE
    wav_path: Path | None = None  # 24-bit, what is dragged out
    play_path: Path | None = None  # 16-bit copy for the audio backend

    @property
    def duration_s(self) -> float:
        return len(self.samples) / self.sample_rate

    @property
    def peak_dbfs(self) -> float:
        peak = float(np.max(np.abs(self.samples))) if len(self.samples) else 0.0
        return 20.0 * math.log10(peak) if peak > 0 else float("-inf")

    @property
    def mono(self) -> np.ndarray:
        s = self.samples
        return s if s.ndim == 1 else s.mean(axis=1)

    def label(self) -> str:
        dur = f"{self.duration_s:.2f}".replace(".", ",")
        dim = dimension(self.settings.dimension).label
        return f"#{self.index} · {dim} · Seed {self.seed} · {dur} s"


def check_samples(raw: Any) -> np.ndarray:
    """Validated float64 copy of an engine result, or :class:`BlasterError`."""
    try:
        a = np.asarray(raw, dtype=np.float64)
    except (TypeError, ValueError):
        raise BlasterError("Die Engine lieferte keine Audiodaten.") from None
    if a.ndim == 2 and a.shape[1] == 1:
        a = a[:, 0]
    if a.ndim not in (1, 2) or (a.ndim == 2 and a.shape[1] != 2) or a.shape[0] == 0:
        raise BlasterError("Die Engine lieferte keine Audiodaten (mono oder stereo erwartet).")
    if not np.all(np.isfinite(a)):
        raise BlasterError("Die Engine lieferte ungültige Werte (NaN oder Inf).")
    peak = float(np.max(np.abs(a)))
    if peak == 0.0:
        raise BlasterError("Die Engine lieferte Stille.")
    if peak > 1.0 + 1e-9:
        raise BlasterError("Die Engine lieferte Pegel über Vollaussteuerung; nichts abgespielt.")
    return a


@dataclass(frozen=True)
class FireResult:
    shot: Shot | None
    message: str  # German; "" when everything worked
    error: bool = False
    played: bool = False


def render_with(engine: LaserEngine | None, reason: str, settings: BlasterSettings,
                seed: int, preview: bool = False) -> tuple[np.ndarray, dict[str, Any]]:
    """Samples and engine params for ``(settings, seed)``; raises :class:`BlasterError`.
    ``preview`` renders the capped profile (``blaster_params.PREVIEW_CAPS``).
    Pure: no state is touched, so it may run in a worker thread."""
    if engine is None:
        raise BlasterError(reason)
    params = preview_params(settings) if preview else to_engine_params(settings)
    try:
        raw = engine.render(dict(params), int(seed))
    except BlasterError:
        raise
    except ValueError as exc:
        text = str(exc)
        if "not rendered by this engine version" in text:
            raise BlasterError(
                "Diese Engine-Version rendert Salve, Filter, Delay-Erweiterungen und Reverb noch "
                f"nicht (Kontrakt v0.2). Engine-Meldung: {' '.join(text.split())}") from exc
        raise BlasterError(f"Ungültige Parameter: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - a message, never a crash
        raise BlasterError(f"Schuss fehlgeschlagen: {type(exc).__name__}: {exc}") from exc
    return check_samples(raw), params


class BlasterSession:
    """State behind the window: settings, seed counter, history, playback."""

    def __init__(
        self,
        engine: LaserEngine | None,
        backend: PlaybackBackend | None = None,
        work_dir: Path | None = None,
        first_seed: int = 1,
        history_limit: int = HISTORY_LIMIT,
        unavailable_reason: str = "",
    ) -> None:
        self.engine = engine
        self.backend: PlaybackBackend = backend or NoBackend()
        self.settings = BlasterSettings()
        self.next_seed = first_seed
        self.history_limit = history_limit
        self.unavailable_reason = unavailable_reason or "Laser-Engine nicht verfügbar."
        self.history: list[Shot] = []
        self._count = 0
        self._preview_n = 0
        self.stale_files: list[Path] = []  # trimmed shot files that could not be deleted yet
        self._own_dir = work_dir is None
        self.work_dir = Path(work_dir) if work_dir else Path(
            tempfile.mkdtemp(prefix="abeltongod-blaster-")
        )

    @property
    def sample_rate(self) -> int:
        return getattr(self.engine, "sample_rate", SAMPLE_RATE)

    # ---- shots ------------------------------------------------------------------------
    def render_shot(
        self, settings: BlasterSettings, seed: int
    ) -> tuple[np.ndarray, dict[str, Any]]:
        return render_with(self.engine, self.unavailable_reason, settings, seed)

    def commit(self, settings: BlasterSettings, seed: int, samples: np.ndarray,
               params: dict[str, Any], play: bool = True) -> FireResult:
        """Keep a rendered shot (files, history, seed counter) and play it. GUI thread."""
        self._count += 1
        shot = Shot(self._count, seed, settings, params, samples, self.sample_rate)
        try:
            shot = self._write_files(shot)
        except OSError as exc:
            self._count -= 1
            return FireResult(None, f"Schuss konnte nicht zwischengespeichert werden: {exc}",
                              error=True)
        self.next_seed = seed + 1
        self.history.insert(0, shot)
        self._trim()
        return self._play(shot) if play else FireResult(shot, "")

    def fire(self, play: bool = True) -> FireResult:
        """Render and commit the next shot in the calling thread. The seed counter only
        advances for a shot that was rendered."""
        seed = self.next_seed
        try:
            samples, params = self.render_shot(self.settings, seed)
        except BlasterError as exc:
            return FireResult(None, str(exc), error=True)
        return self.commit(self.settings, seed, samples, params, play)

    def replay(self, shot: Shot) -> FireResult:
        return self._play(shot)

    def _play(self, shot: Shot) -> FireResult:
        if not self.backend.available:
            return FireResult(shot, "Keine Audioausgabe verfügbar. Der Schuss wurde trotzdem "
                                    "erzeugt und kann herausgezogen werden.")
        try:
            if shot.play_path is None:
                raise OSError("keine Abspieldatei")
            self.backend.play(shot.play_path)
        except Exception as exc:  # noqa: BLE001
            return FireResult(shot, f"Wiedergabe fehlgeschlagen: {exc}", error=True)
        return FireResult(shot, "", played=True)

    def _write_files(self, shot: Shot) -> Shot:
        stem = f"shot_{shot.index:04d}_{shot.settings.dimension}_s{shot.seed}"
        self.work_dir.mkdir(parents=True, exist_ok=True)
        wav = self.work_dir / f"{stem}.wav"
        play = self.work_dir / f"{stem}.play16.wav"
        wav.write_bytes(encode_wav(shot.samples, shot.sample_rate, BIT_DEPTH))
        try:
            play.write_bytes(encode_wav(shot.samples, shot.sample_rate, PLAY_BITS))
        except OSError:
            wav.unlink(missing_ok=True)
            raise
        return replace(shot, wav_path=wav, play_path=play)

    def _trim(self) -> None:
        """Drop the oldest shots beyond the limit and delete their temp files. A file another
        program still holds (Windows: winsound playing it, a virus scanner) cannot be deleted
        now (PermissionError): it is kept in ``stale_files`` and tried again on the next trim
        and on ``close`` (#447); the shot is still dropped from the history."""
        while len(self.history) > self.history_limit:
            old = self.history.pop()
            self.stale_files.extend(p for p in (old.wav_path, old.play_path) if p is not None)
        self._delete_stale()

    def _delete_stale(self) -> None:
        left = []
        for p in self.stale_files:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                left.append(p)
        self.stale_files = left

    def render_preview(self, settings: BlasterSettings, seed: int
                       ) -> tuple[np.ndarray, dict[str, Any]]:
        """Capped render for the live preview (pure, worker thread)."""
        return render_with(self.engine, self.unavailable_reason, settings, seed, preview=True)

    def play_preview(self, samples: np.ndarray) -> FireResult:
        """Play a preview (16-bit copy, alternating file names, not kept in the history).
        GUI thread."""
        self._preview_n += 1
        path = self.work_dir / f"preview_{self._preview_n % 2}.play16.wav"
        try:
            self.work_dir.mkdir(parents=True, exist_ok=True)
            path.write_bytes(encode_wav(samples, self.sample_rate, PLAY_BITS))
        except OSError as exc:
            return FireResult(None, f"Vorschau konnte nicht zwischengespeichert werden: {exc}",
                              error=True)
        shot = Shot(0, 0, self.settings, {}, samples, self.sample_rate, None, path)
        return self._play(shot)

    def stop(self) -> None:
        try:
            self.backend.stop()
        except Exception:  # noqa: BLE001
            pass

    def close(self) -> None:
        self.stop()
        self._delete_stale()  # playback stopped: a held file can usually go now
        if self._own_dir:
            shutil.rmtree(self.work_dir, ignore_errors=True)


# ---- bank export --------------------------------------------------------------------------
class BankWriter(Protocol):
    def write(self, params: dict[str, Any], seed: int, folder: Path, stem: str,
              description: str) -> tuple[Path, Path]:
        """Render and write ``<stem>.wav`` + sidecar into ``folder`` (never overwriting)."""
        ...


class CategoryBankWriter:
    """The repo's writer: ``audio_engine.io.write_sample("laser", ...)`` renders through the
    laser category and writes WAV + sidecar (sample-metadata contract, no overwrite)."""

    def write(self, params, seed, folder, stem, description):
        from audio_engine.categories import CategoryUnavailable
        from audio_engine.io import write_sample

        try:
            return write_sample("laser", {**params, "seed": seed}, folder, name=stem,
                                description=description)
        except CategoryUnavailable as exc:
            raise BlasterError(f"Bank nicht möglich: {exc}") from exc


@dataclass(frozen=True)
class BankResult:
    folder: Path | None
    files: tuple[tuple[Path, Path], ...]
    requested: int
    message: str  # German
    error: bool = False

    @property
    def ok(self) -> bool:
        return not self.error and len(self.files) == self.requested


def unique_folder(parent: Path, base: str = "laser_bank") -> Path:
    """Create and return ``parent/<base>_001`` (or the next free number). Never reuses a folder."""
    parent.mkdir(parents=True, exist_ok=True)
    for n in range(1, 10_000):
        cand = parent / f"{base}_{n:03d}"
        try:
            cand.mkdir()
        except FileExistsError:
            continue
        return cand
    raise BlasterError("Kein freier Bank-Ordnername gefunden.")


def bank_parent(chosen: Path) -> Path:
    """``<chosen>/Samples/FX/Lasers``: the library layout's laser folder below ``chosen``."""
    return Path(chosen).joinpath(*LibraryLayout().parts_for("laser"))


def export_bank(
    settings: BlasterSettings,
    first_seed: int,
    count: int,
    chosen: Path,
    writer: BankWriter | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> BankResult:
    """Write ``count`` shots (seeds ``first_seed`` ...) with sidecars into a NEW folder
    ``<chosen>/Samples/FX/Lasers/laser_bank_NNN``. Pure with respect to the session (safe in a
    worker thread). Existing files are never touched. A failure keeps what was written before
    it and says how many files that were; a bank that wrote nothing removes its empty folder."""
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= BANK_MAX:
        return BankResult(None, (), 0, f"Die Bank braucht 1 bis {BANK_MAX} Schüsse.", True)
    if not 0 <= first_seed <= SEED_MAX - count:
        return BankResult(None, (), count, "Der Start-Seed passt nicht für diese Bankgröße.",
                          True)
    writer = writer or CategoryBankWriter()
    try:
        folder = unique_folder(bank_parent(Path(chosen)))
    except (OSError, BlasterError) as exc:
        return BankResult(None, (), count, f"Ordner konnte nicht angelegt werden: {exc}", True)
    dim = dimension(settings.dimension)
    params = to_engine_params(settings)
    written: list[tuple[Path, Path]] = []
    try:
        for i in range(count):
            seed = first_seed + i
            stem = f"laser_{settings.dimension}_s{seed}"
            n_shots = settings.values["salvo_count"]
            kind = f"Laser-Salve mit {n_shots} Schüssen" if n_shots > 1 else "Laser-Schuss"
            text = f"{kind}, Dimension {dim.label}, Seed {seed}, Blaster-Bank Nr. {i + 1}."
            written.append(writer.write(params, seed, folder, stem, text))
            if progress:
                progress(i + 1, count)
    except (OSError, BlasterError, ValueError) as exc:
        msg = f"Bank abgebrochen nach {len(written)} von {count} Dateien: {exc}"
        if not written:
            try:
                folder.rmdir()
            except OSError:
                pass
            return BankResult(None, (), count, msg, True)
        return BankResult(folder, tuple(written), count, msg, True)
    except Exception as exc:  # noqa: BLE001 - a result, not a crash in the worker thread
        msg = (f"Bank abgebrochen nach {len(written)} von {count} Dateien: "
               f"{type(exc).__name__}: {exc}")
        return BankResult(folder if written else None, tuple(written), count, msg, True)
    return BankResult(folder, tuple(written), count,
                      f"Bank mit {count} Schüssen geschrieben: {folder}")
