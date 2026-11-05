"""Seeded acid-line generator and scale helpers (pure, no Qt, no I/O). PROPOSAL, no contract.

The output is an ``acid_line`` object in the format ``audio_engine.acid_midi`` reads
(version ``"0.1-proposal"``; D-028: the format has no contract). Same options + same seed give
the identical object.

Rules (the tests restate them independently):

* ``n_on = floor(density * length + 0.5)`` steps sound; their positions are drawn uniformly
  without repetition. So density is exact up to rounding, not a probability.
* Every sounding step draws a scale degree (uniform over the scale), an octave offset
  ``0 .. octave_range-1`` (uniform), an accent (chance ``accent_chance``) and a slide flag
  (chance ``slide_chance``). A slide flag before a rest or on the last step has no effect on the
  notes (``acid_midi``), it is still stored.
* ``note = root_midi + interval[degree] + 12 * octave``; ``root_midi = 12 * (root_octave + 1) +
  index(root)`` (A2 = 45, as in the research note).

Only ``random.Random.random()`` is used, so the stream does not depend on Python's
``randrange`` details.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from audio_engine.acid_midi import FORMAT_NAME, FORMAT_VERSION, MAX_LENGTH, MAX_NOTE, validate_line

ROOTS: tuple[str, ...] = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

# Semitone offsets from the root within one octave. Names are the GUI labels.
SCALES: dict[str, tuple[int, ...]] = {
    "minor": (0, 2, 3, 5, 7, 8, 10),
    "major": (0, 2, 4, 5, 7, 9, 11),
    "phrygian": (0, 1, 3, 5, 7, 8, 10),
    "dorian": (0, 2, 3, 5, 7, 9, 10),
    "harmonic minor": (0, 2, 3, 5, 7, 8, 11),
    "minor pentatonic": (0, 3, 5, 7, 10),
    "phrygian dominant": (0, 1, 4, 5, 7, 8, 10),
}
DEFAULT_ROOT, DEFAULT_SCALE, DEFAULT_ROOT_OCTAVE = "A", "minor", 2
ROOT_OCTAVE_RANGE = (0, 6)
OCTAVE_RANGE_LIMITS = (1, 3)


class AcidOptionError(ValueError):
    """Invalid generator option; the message is German and shown to the user as is."""


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def root_midi(root: str, root_octave: int) -> int:
    """MIDI number of ``root`` in ``root_octave`` (C-1 = 0, A2 = 45)."""
    if root not in ROOTS:
        raise AcidOptionError(f"Unbekannte Grundnote: {root!r}.")
    if not _is_int(root_octave) or not ROOT_OCTAVE_RANGE[0] <= root_octave <= ROOT_OCTAVE_RANGE[1]:
        raise AcidOptionError(f"Oktave muss eine ganze Zahl von {ROOT_OCTAVE_RANGE[0]} bis "
                              f"{ROOT_OCTAVE_RANGE[1]} sein.")
    return 12 * (root_octave + 1) + ROOTS.index(root)


def scale_notes(root: str, scale: str, root_octave: int, octaves: int = 3) -> list[int]:
    """Ascending MIDI notes of the scale over ``octaves`` octaves, plus the root above them,
    clipped to the MIDI range accepted by ``acid_midi``."""
    if scale not in SCALES:
        raise AcidOptionError(f"Unbekannte Skala: {scale!r}.")
    base = root_midi(root, root_octave)
    notes = [base + 12 * o + iv for o in range(octaves) for iv in SCALES[scale]]
    notes.append(base + 12 * octaves)
    return [n for n in notes if n <= MAX_NOTE]


def snap_note(note: int, root: str, scale: str) -> int:
    """Nearest note of the scale (in any octave) to ``note``; a tie goes to the lower note."""
    if scale not in SCALES or root not in ROOTS:
        raise AcidOptionError("Unbekannte Grundnote oder Skala.")
    pcs = {(ROOTS.index(root) + iv) % 12 for iv in SCALES[scale]}
    best = None
    for d in range(0, 13):
        for cand in (note - d, note + d):
            if 0 <= cand <= MAX_NOTE and cand % 12 in pcs:
                best = cand
                break
        if best is not None:
            return best
    return note  # unreachable: every scale has a pitch class within 12 semitones


def in_scale(note: int, root: str, scale: str) -> bool:
    return (note - ROOTS.index(root)) % 12 in SCALES[scale]


def degree_octave(note: int, root: str, scale: str, root_octave: int) -> tuple[int, int] | None:
    """(degree index, octave offset from ``root_octave``) of ``note``, or None if not in scale."""
    base = root_midi(root, root_octave)
    octave, semis = divmod(note - base, 12)
    ivs = SCALES[scale]
    if semis in ivs:
        return ivs.index(semis), octave
    return None


_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def note_name(note: int) -> str:
    """``45`` -> ``"A2"`` (C-1 = 0)."""
    return f"{_NAMES[note % 12]}{note // 12 - 1}"


@dataclass(frozen=True)
class GenOptions:
    root: str = DEFAULT_ROOT
    scale: str = DEFAULT_SCALE
    root_octave: int = DEFAULT_ROOT_OCTAVE
    length: int = 16
    density: float = 0.6
    accent_chance: float = 0.25
    slide_chance: float = 0.2
    octave_range: int = 2
    seed: int = 0


def validate_options(o: GenOptions) -> None:
    """Raise :class:`AcidOptionError` (German message) if an option is out of range."""
    if o.root not in ROOTS:
        raise AcidOptionError(f"Unbekannte Grundnote: {o.root!r}.")
    if o.scale not in SCALES:
        raise AcidOptionError(f"Unbekannte Skala: {o.scale!r}.")
    if not _is_int(o.length) or not 1 <= o.length <= MAX_LENGTH:
        raise AcidOptionError(f"Länge muss eine ganze Zahl von 1 bis {MAX_LENGTH} sein.")
    for v, label in ((o.density, "Dichte"), (o.accent_chance, "Akzent-Chance"),
                     (o.slide_chance, "Slide-Chance")):
        if not _is_num(v) or not 0.0 <= v <= 1.0:
            raise AcidOptionError(f"{label} muss eine Zahl von 0 bis 1 sein.")
    lo, hi = OCTAVE_RANGE_LIMITS
    if not _is_int(o.octave_range) or not lo <= o.octave_range <= hi:
        raise AcidOptionError(f"Oktavbereich muss eine ganze Zahl von {lo} bis {hi} sein.")
    if not _is_int(o.seed):
        raise AcidOptionError("Seed muss eine ganze Zahl sein.")
    base = root_midi(o.root, o.root_octave)  # raises for a bad octave
    top = base + max(SCALES[o.scale]) + 12 * (o.octave_range - 1)
    if top > MAX_NOTE:
        raise AcidOptionError("Oktave plus Oktavbereich liegt über dem MIDI-Bereich; "
                              "bitte eine tiefere Oktave wählen.")


def generate_line(o: GenOptions) -> dict[str, Any]:
    """The acid line for ``o``. Deterministic: equal options give an equal (==) object."""
    validate_options(o)
    rng = random.Random(o.seed)
    n_on = int(o.density * o.length + 0.5)
    keys = [rng.random() for _ in range(o.length)]
    on_positions = set(sorted(range(o.length), key=lambda i: (keys[i], i))[:n_on])
    base = root_midi(o.root, o.root_octave)
    ivs = SCALES[o.scale]
    steps: list[dict[str, Any]] = []
    for i in range(o.length):
        if i not in on_positions:
            steps.append({"on": False})
            continue
        degree = min(int(rng.random() * len(ivs)), len(ivs) - 1)
        octave = min(int(rng.random() * o.octave_range), o.octave_range - 1)
        accent = rng.random() < o.accent_chance
        slide = rng.random() < o.slide_chance
        steps.append({
            "on": True, "note": base + ivs[degree] + 12 * octave,
            "accent": accent, "slide": slide, "degree": degree, "octave": octave,
        })
    line = {
        "format": FORMAT_NAME, "version": FORMAT_VERSION, "seed": o.seed,
        "root": o.root, "root_octave": o.root_octave, "scale": o.scale,
        "length": o.length, "steps": steps,
    }
    validate_line(line)
    return line
