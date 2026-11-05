"""Edit model of the acid window (no Qt): 32 step slots, scale handling, JSON, MIDI export.

PROPOSAL level like the format itself (``audio_engine.acid_midi``, version ``0.1-proposal``):
no contract, nothing is written to Live. Every user-facing error is a German
:class:`AcidFileError` / ``AcidOptionError``; the model is unchanged after a failed call.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audio_engine.acid_midi import (
    FORMAT_NAME,
    FORMAT_VERSION,
    MAX_LENGTH,
    MAX_NOTE,
    acid_line_to_midi,
    validate_line,
)

from .acid_generate import (
    ROOTS,
    SCALES,
    AcidOptionError,
    GenOptions,
    degree_octave,
    generate_line,
    root_midi,
    scale_notes,
    snap_note,
)

SLOTS = MAX_LENGTH
BPM_RANGE = (20.0, 400.0)  # the range acid_midi accepts
DEFAULT_BPM = 130.0


class AcidFileError(ValueError):
    """Load/save/export problem with a German message."""


@dataclass
class Step:
    on: bool = False
    note: int = 45
    accent: bool = False
    slide: bool = False


def parse_bpm(text: str) -> float:
    try:
        v = float(text.strip().replace(",", "."))
    except ValueError:
        raise AcidOptionError("BPM muss eine Zahl sein.") from None
    if not BPM_RANGE[0] <= v <= BPM_RANGE[1] or v != v:
        raise AcidOptionError(
            f"BPM muss zwischen {BPM_RANGE[0]:.0f} und {BPM_RANGE[1]:.0f} liegen.")
    return v


def parse_seed(text: str) -> int:
    try:
        return int(text.strip())
    except ValueError:
        raise AcidOptionError("Seed muss eine ganze Zahl sein.") from None


def parse_percent(text: str, label: str) -> float:
    """``"35"`` or ``"35 %"`` -> 0.35."""
    try:
        v = float(text.strip().rstrip("%").strip().replace(",", "."))
    except ValueError:
        raise AcidOptionError(f"{label} muss eine Zahl von 0 bis 100 sein.") from None
    if not 0.0 <= v <= 100.0:
        raise AcidOptionError(f"{label} muss eine Zahl von 0 bis 100 sein.")
    return v / 100.0


class AcidModel:
    def __init__(self) -> None:
        self.root = "A"
        self.scale = "minor"
        self.root_octave = 2
        self.length = 16
        self.bpm = DEFAULT_BPM
        self.seed = 0
        self.render: dict[str, Any] | None = None
        self.steps = [Step(note=root_midi(self.root, self.root_octave)) for _ in range(SLOTS)]
        self.generate(GenOptions())

    # ---- queries -----------------------------------------------------------------------
    def palette(self, octaves: int = 3) -> list[int]:
        return scale_notes(self.root, self.scale, self.root_octave, octaves)

    def to_line(self) -> dict[str, Any]:
        steps: list[dict[str, Any]] = []
        for s in self.steps[: self.length]:
            if not s.on:
                steps.append({"on": False})
                continue
            d: dict[str, Any] = {"on": True, "note": s.note, "accent": s.accent, "slide": s.slide}
            do = degree_octave(s.note, self.root, self.scale, self.root_octave)
            if do is not None:
                d["degree"], d["octave"] = do
            steps.append(d)
        line: dict[str, Any] = {
            "format": FORMAT_NAME, "version": FORMAT_VERSION, "seed": self.seed,
            "root": self.root, "root_octave": self.root_octave, "scale": self.scale,
            "length": self.length, "steps": steps,
        }
        if self.render is not None:
            line["render"] = copy.deepcopy(self.render)
        return line

    # ---- editing -----------------------------------------------------------------------
    def _idx(self, i: int) -> Step:
        if not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < SLOTS:
            raise AcidOptionError(f"Step {i!r} gibt es nicht (1 bis {SLOTS}).")
        return self.steps[i]

    def toggle_on(self, i: int) -> bool:
        s = self._idx(i)
        s.on = not s.on
        return s.on

    def toggle_accent(self, i: int) -> bool:
        s = self._idx(i)
        s.accent = not s.accent
        return s.accent

    def toggle_slide(self, i: int) -> bool:
        s = self._idx(i)
        s.slide = not s.slide
        return s.slide

    def set_note(self, i: int, note: int) -> None:
        s = self._idx(i)
        if not isinstance(note, int) or isinstance(note, bool) or not 0 <= note <= MAX_NOTE:
            raise AcidOptionError(f"Note muss eine ganze Zahl von 0 bis {MAX_NOTE} sein.")
        s.note = note

    def set_length(self, n: int) -> None:
        if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= MAX_LENGTH:
            raise AcidOptionError(f"Länge muss eine ganze Zahl von 1 bis {MAX_LENGTH} sein.")
        self.length = n

    def set_bpm(self, bpm: float) -> None:
        self.bpm = parse_bpm(str(bpm))

    def set_scale(self, root: str, scale: str) -> None:
        """Change root/scale; every note is snapped to the nearest note of the new scale."""
        if root not in ROOTS:
            raise AcidOptionError(f"Unbekannte Grundnote: {root!r}.")
        if scale not in SCALES:
            raise AcidOptionError(f"Unbekannte Skala: {scale!r}.")
        for s in self.steps:
            s.note = snap_note(s.note, root, scale)
        self.root, self.scale = root, scale

    def set_root_octave(self, octave: int) -> None:
        """Move the root octave; all notes move with it (degrees are kept)."""
        new_base = root_midi(self.root, octave)  # validates 0..6
        delta = new_base - root_midi(self.root, self.root_octave)
        if any(not 0 <= s.note + delta <= MAX_NOTE for s in self.steps):
            raise AcidOptionError("Diese Oktave würde Noten aus dem MIDI-Bereich schieben.")
        for s in self.steps:
            s.note += delta
        self.root_octave = octave

    def clear(self) -> None:
        for s in self.steps:
            s.on = s.accent = s.slide = False

    def generate(self, opts: GenOptions) -> None:
        """Fill the grid from ``opts`` (root/scale/octave/length come from the options)."""
        self._adopt(generate_line(opts))

    # ---- file / line --------------------------------------------------------------------
    def _adopt(self, line: dict[str, Any]) -> None:
        """Replace the line state with a validated line (keeps BPM; all-or-nothing)."""
        root = line.get("root") if line.get("root") in ROOTS else self.root
        scale = line.get("scale") if line.get("scale") in SCALES else self.scale
        ro = line.get("root_octave")
        ro = ro if isinstance(ro, int) and not isinstance(ro, bool) and 0 <= ro <= 6 \
            else self.root_octave
        default_note = root_midi(root, ro)
        steps = [Step(note=default_note) for _ in range(SLOTS)]
        for i, d in enumerate(line["steps"]):
            if d["on"]:
                steps[i] = Step(True, d["note"], bool(d.get("accent", False)),
                                bool(d.get("slide", False)))
        self.root, self.scale, self.root_octave = root, scale, ro
        self.length = line["length"]
        self.seed = line.get("seed", self.seed)
        self.render = copy.deepcopy(line["render"]) if "render" in line else None
        self.steps = steps

    def load_line(self, line: Any) -> None:
        try:
            validate_line(line)
        except ValueError as exc:
            raise AcidFileError(f"Das ist keine gültige Acid-Linie: {exc}") from None
        self._adopt(line)

    def load_file(self, path: str | Path) -> None:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            raise AcidFileError(f"Datei konnte nicht gelesen werden: {exc.strerror or exc}") \
                from None
        except UnicodeDecodeError:
            raise AcidFileError("Datei ist kein UTF-8-Text.") from None
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AcidFileError(f"Datei ist kein gültiges JSON (Zeile {exc.lineno}).") from None
        self.load_line(data)

    def save_file(self, path: str | Path) -> Path:
        """Write the line as JSON (atomic: temp file + replace, so a failure keeps the old file)."""
        p = Path(path)
        text = json.dumps(self.to_line(), indent=2) + "\n"
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=p.name + ".", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                    f.write(text)
                os.replace(tmp, p)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        except OSError as exc:
            raise AcidFileError(f"Datei konnte nicht geschrieben werden: {exc.strerror or exc}") \
                from None
        return p

    def midi_bytes(self) -> bytes:
        """Exactly ``acid_line_to_midi(self.to_line(), bpm=self.bpm)``."""
        try:
            return acid_line_to_midi(self.to_line(), bpm=self.bpm)
        except ValueError as exc:
            raise AcidFileError(f"MIDI-Export nicht möglich: {exc}") from None

    def export_midi(self, path: str | Path) -> Path:
        data = self.midi_bytes()  # computed first: a bad line writes nothing
        p = Path(path)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        except OSError as exc:
            raise AcidFileError(f"Datei konnte nicht geschrieben werden: {exc.strerror or exc}") \
                from None
        return p
