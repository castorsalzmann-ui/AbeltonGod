"""Blaster service layer (no Qt): settings, shots, shot history, bank export.

The window pulls a trigger -> :meth:`BlasterSession.fire` renders the next shot through a
:class:`LaserEngine` (``audio_engine.laser.render_laser(params, seed)``, issue #416), keeps it in
a short history and plays a 16-bit copy through the preview backend. Nothing here judges how a
shot sounds, and nothing here talks to Live.

Adapter boundary. The laser engine is built in parallel. Everything that depends on its final
parameter names lives in :func:`to_engine_params` and :class:`CategoryBankWriter`; the rest of
the GUI only knows the 0-100 sliders of :class:`BlasterSettings`. Until the engine is merged,
:func:`load_engine` reports "not available" and tests use ``gui_core.blaster_stub``.

Same settings + same seed give the same samples (the engine's promise) and therefore the same
WAV bytes (the encoder here is deterministic).
"""

from __future__ import annotations

import importlib
import importlib.util
import math
import shutil
import struct
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from audio_engine.io import encode_wav

from .preview import NoBackend, PlaybackBackend

DEFAULT_SAMPLE_RATE = 44100
MAX_SHOT_SECONDS = 10.0
HISTORY_LIMIT = 40
BANK_MAX = 64
SLIDER_MIN, SLIDER_MAX = 0, 100
EXPORT_BITS = 24
PLAY_BITS = 16


@dataclass(frozen=True)
class Dimension:
    key: str
    label: str  # German, short
    hint: str  # German, one line: what the family is meant to be (not how it sounds)
    accent: str  # glow colour of the blaster for this dimension


# Working names of the shot families. The engine decides its final set (#416); this list is the
# adapter's view and is aligned when the engine is wired in. Nothing says what a family sounds
# like beyond its name.
DIMENSIONS: tuple[Dimension, ...] = (
    Dimension("classic", "Klassik", "Absteigender Strahl, der Klassiker", "#ff4a2a"),
    Dimension("plasma", "Plasma", "Dichter, rauer Strahl", "#ff3df0"),
    Dimension("ion", "Ion", "Heller, schmaler Strahl", "#27e0ff"),
    Dimension("void", "Void", "Tiefer Riss mit langem Nachhall", "#8b5cff"),
    Dimension("subboom", "Sub-Boom", "Kurzer Schlag mit Tiefbass", "#ffb21f"),
    Dimension("glitch", "Glitch", "Zerhackter Strahl", "#3dff8c"),
)
DIMENSION_KEYS = tuple(d.key for d in DIMENSIONS)


def dimension(key: str) -> Dimension:
    for d in DIMENSIONS:
        if d.key == key:
            return d
    raise ValueError(f"Unbekannte Dimension: {key}")


class BlasterError(Exception):
    """A user-facing problem; the message is German."""


@dataclass(frozen=True)
class BlasterSettings:
    """What the window's controls hold: a dimension and six sliders (0-100)."""

    dimension: str = "classic"
    pitch: int = 50
    sweep: int = 50
    length: int = 40
    roughness: int = 30
    echo: int = 20
    width: int = 50

    def __post_init__(self) -> None:
        if self.dimension not in DIMENSION_KEYS:
            raise ValueError(f"Unbekannte Dimension: {self.dimension}")
        for name in SLIDER_NAMES:
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, int) or not SLIDER_MIN <= v <= SLIDER_MAX:
                raise ValueError(f"{name} muss eine ganze Zahl von 0 bis 100 sein, nicht {v!r}.")


SLIDER_NAMES = ("pitch", "sweep", "length", "roughness", "echo", "width")
SLIDER_LABELS = {
    "pitch": "Tonhöhe", "sweep": "Sweep", "length": "Länge",
    "roughness": "Rauheit", "echo": "Echo", "width": "Breite",
}


def _lerp_exp(lo: float, hi: float, t: float) -> float:
    return lo * (hi / lo) ** t


def to_engine_params(s: BlasterSettings) -> dict[str, Any]:
    """Slider positions -> engine parameters (physical units). ADAPTER: the names follow the
    brief of issue #416 (pitch start/end, sweep, length, FM, noise, tail, width) and are the one
    place to change when the laser contract fixes the final names. The seed is not part of it."""
    start = _lerp_exp(200.0, 8000.0, s.pitch / 100)
    octaves = 5.0 * s.sweep / 100
    end = max(20.0, start * 2.0 ** (-octaves))
    return {
        "family": s.dimension,
        "pitch_start_hz": round(start, 2),
        "pitch_end_hz": round(end, 2),
        "length_ms": round(_lerp_exp(60.0, 1500.0, s.length / 100), 1),
        "fm_amount": round(s.roughness / 100, 3),
        "noise_amount": round(s.roughness / 200, 3),
        "tail_amount": round(s.echo / 100, 3),
        "stereo_width": round(s.width / 100, 3),
    }


def readout(name: str, value: int) -> str:
    """German text next to a slider: the physical value that goes to the engine."""
    p = to_engine_params(replace(BlasterSettings(), **{name: value}))
    if name == "pitch":
        hz = p["pitch_start_hz"]
        return f"{hz / 1000:.1f} kHz".replace(".", ",") if hz >= 1000 else f"{hz:.0f} Hz"
    if name == "sweep":
        return f"−{5.0 * value / 100:.1f} Okt".replace(".", ",")
    if name == "length":
        return f"{p['length_ms']:.0f} ms"
    return f"{value} %"


# ---- engine adapter -----------------------------------------------------------------------
class LaserEngine(Protocol):
    sample_rate: int

    def render(self, params: dict[str, Any], seed: int) -> np.ndarray:
        """Float samples in [-1, 1]: shape ``(n,)`` (mono) or ``(n, 2)`` (stereo)."""
        ...


class ModuleLaserEngine:
    """Wraps ``audio_engine.laser.render_laser``."""

    def __init__(self, module: Any) -> None:
        self._render = module.render_laser
        self.sample_rate = int(getattr(module, "SAMPLE_RATE", DEFAULT_SAMPLE_RATE))

    def render(self, params: dict[str, Any], seed: int) -> np.ndarray:
        return np.asarray(self._render(params, seed))


def load_engine() -> tuple[LaserEngine | None, str]:
    """The real engine, or ``(None, German reason)`` while ``audio_engine.laser`` is missing."""
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
    sample_rate: int = DEFAULT_SAMPLE_RATE
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


def encode_shot_wav(samples: np.ndarray, sr: int, bits: int) -> bytes:
    """PCM WAV of a mono or stereo shot (deterministic). Mono goes through the engine's own
    encoder; stereo is the same bytes with a two-channel header and interleaved frames."""
    if samples.ndim == 1:
        return encode_wav(samples, sr, bits)
    wav = bytearray(encode_wav(samples.reshape(-1), sr, bits))  # interleaved L R L R ...
    width = bits // 8
    struct.pack_into("<HHIIHH", wav, 20, 1, 2, sr, sr * 2 * width, 2 * width, bits)
    return bytes(wav)


@dataclass(frozen=True)
class FireResult:
    shot: Shot | None
    message: str  # German; "" when everything worked
    error: bool = False
    played: bool = False


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
        self._own_dir = work_dir is None
        self.work_dir = Path(work_dir) if work_dir else Path(
            tempfile.mkdtemp(prefix="abeltongod-blaster-")
        )

    # ---- shots ------------------------------------------------------------------------
    def render_shot(
        self, settings: BlasterSettings, seed: int
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Samples and engine params for ``(settings, seed)``; raises :class:`BlasterError`."""
        if self.engine is None:
            raise BlasterError(self.unavailable_reason)
        params = to_engine_params(settings)
        try:
            raw = self.engine.render(dict(params), int(seed))
        except BlasterError:
            raise
        except ValueError as exc:
            raise BlasterError(f"Ungültige Parameter: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - a message, never a crash in the paint loop
            raise BlasterError(f"Schuss fehlgeschlagen: {type(exc).__name__}: {exc}") from exc
        return check_samples(raw), params

    def fire(self, play: bool = True) -> FireResult:
        """Pull the trigger: render the shot for the next seed, keep it, play it. The seed
        counter only advances for a shot that was rendered."""
        seed = self.next_seed
        try:
            samples, params = self.render_shot(self.settings, seed)
        except BlasterError as exc:
            return FireResult(None, str(exc), error=True)
        sr = getattr(self.engine, "sample_rate", DEFAULT_SAMPLE_RATE)
        self._count += 1
        shot = Shot(self._count, seed, self.settings, params, samples, sr)
        try:
            shot = self._write_files(shot)
        except OSError as exc:
            self._count -= 1
            return FireResult(None, f"Schuss konnte nicht zwischengespeichert werden: {exc}",
                              error=True)
        self.next_seed = seed + 1
        self.history.insert(0, shot)
        self._trim()
        if not play:
            return FireResult(shot, "")
        return self._play(shot)

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
        wav.write_bytes(encode_shot_wav(shot.samples, shot.sample_rate, EXPORT_BITS))
        try:
            play.write_bytes(encode_shot_wav(shot.samples, shot.sample_rate, PLAY_BITS))
        except OSError:
            wav.unlink(missing_ok=True)
            raise
        return replace(shot, wav_path=wav, play_path=play)

    def _trim(self) -> None:
        while len(self.history) > self.history_limit:
            old = self.history.pop()
            for p in (old.wav_path, old.play_path):
                if p is not None:
                    p.unlink(missing_ok=True)

    def stop(self) -> None:
        try:
            self.backend.stop()
        except Exception:  # noqa: BLE001
            pass

    def close(self) -> None:
        self.stop()
        if self._own_dir:
            shutil.rmtree(self.work_dir, ignore_errors=True)


# ---- bank export --------------------------------------------------------------------------
class BankWriter(Protocol):
    def write(self, shot_params: dict[str, Any], seed: int, samples: np.ndarray, sr: int,
              folder: Path, stem: str, description: str) -> tuple[Path, Path]:
        """Write ``<stem>.wav`` + sidecar into ``folder`` (never overwriting); return both."""
        ...


class CategoryBankWriter:
    """Real writer: the engine's own sidecar path (``audio_engine.io.write_sample("laser", ...)``,
    the sample-metadata contract). Needs the laser category to be registered (#416); until then
    it raises :class:`BlasterError`. How the engine's request object is built from the blaster's
    params is verified when the engine is wired in."""

    def write(self, shot_params, seed, samples, sr, folder, stem, description):
        from audio_engine.categories import CategoryUnavailable
        from audio_engine.io import write_sample

        try:
            return write_sample("laser", {**shot_params, "seed": seed}, folder, name=stem,
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


def export_bank(
    session: BlasterSession,
    count: int,
    parent: Path,
    writer: BankWriter | None = None,
) -> BankResult:
    """Render ``count`` shots with the session's settings for the next ``count`` seeds and write
    them with sidecars into a NEW folder below ``parent``. The seed counter advances by the
    number of shots written. Existing files are never touched. A failure keeps what was
    written before it and says how many files that were."""
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= BANK_MAX:
        return BankResult(None, (), 0, f"Die Bank braucht 1 bis {BANK_MAX} Schüsse.", True)
    writer = writer or CategoryBankWriter()
    settings, first = session.settings, session.next_seed
    # Render everything first, so an engine failure creates no folder at all.
    shots: list[tuple[int, np.ndarray, dict[str, Any]]] = []
    try:
        for i in range(count):
            samples, params = session.render_shot(settings, first + i)
            shots.append((first + i, samples, params))
    except BlasterError as exc:
        return BankResult(None, (), count, str(exc), True)
    sr = getattr(session.engine, "sample_rate", DEFAULT_SAMPLE_RATE)
    try:
        folder = unique_folder(Path(parent))
    except (OSError, BlasterError) as exc:
        return BankResult(None, (), count, f"Ordner konnte nicht angelegt werden: {exc}", True)
    dim = dimension(settings.dimension)
    written: list[tuple[Path, Path]] = []
    try:
        for i, (seed, samples, params) in enumerate(shots, 1):
            stem = f"laser_{settings.dimension}_s{seed}"
            text = f"Laser-Schuss, Dimension {dim.label}, Seed {seed}, Blaster-Bank Nr. {i}."
            written.append(writer.write(params, seed, samples, sr, folder, stem, text))
    except (OSError, BlasterError, ValueError) as exc:
        msg = f"Bank abgebrochen nach {len(written)} von {count} Dateien: {exc}"
        session.next_seed = first + len(written)
        return BankResult(folder, tuple(written), count, msg, True)
    session.next_seed = first + count
    return BankResult(folder, tuple(written), count,
                      f"Bank mit {count} Schüssen geschrieben: {folder}")


Opener = Callable[[Path], bool]
