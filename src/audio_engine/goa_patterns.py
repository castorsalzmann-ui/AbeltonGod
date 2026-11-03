"""Seeded Goa-trance pattern generator: bass, lead and arpeggio lines as plain data.

Output is an acid-line dict (format "acid_line", version "0.1-proposal", see
``acid_midi``) so ``acid_midi.acid_line_to_midi`` writes it; extra top-level keys
(``kind``, ``bars``, ``bpm`` ...) are informational. Pure, stdlib only: same parameters
and seed give identical dicts, JSON text and MIDI bytes (a local ``random.Random`` is
the only source of randomness; no clock, no global RNG).

Musical assumptions (HYPOTHESES, not facts; the research note
docs/research/2026-11-03_goa-trance-musicology-and-sound.md was not available when
this was written, so nothing here is aligned with it yet):

* H1 Goa tempo is roughly 135-150 BPM; anything outside is rejected.
* H2 The bass rolls on 16ths and leaves the kick step (step % 4 == 0) free, i.e. up to
  three notes per beat; the off-beat 8th (step % 4 == 2) is weighted as the most likely
  to be kept when density thins the roll.
* H3 Bass pitches move mostly on the root, its octave and the scale's second degree
  (the minor second in phrygian-type scales), sometimes the fifth.
* H4 Leads are short ostinati of one or two bars in a one-octave-plus range, repeated,
  with a fresh variation bar at the end of every 4-bar phrase.
* H5 Arpeggios run continuous 16ths over chord tones stacked in thirds from a scale degree.
* H6 Phrygian, phrygian dominant, harmonic minor and aeolian are the scale choices.

Density, accent and slide are exact counts per line, not probabilities:
notes per bar = round-half-up(density * grid size); accents = round-half-up(accent * notes);
slides = min(round-half-up(slide * notes), number of eligible notes) where eligible means
the next step sounds with a different pitch. Nothing here makes a listening claim.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from audio_engine import acid_midi

FORMAT_VERSION = acid_midi.FORMAT_VERSION
STEPS_PER_BAR = 16
MIN_BARS, MAX_BARS = 1, 16
MIN_BPM, MAX_BPM = 135.0, 150.0
DEFAULT_BPM = 145.0
MIN_ROOT, MAX_ROOT = 12, 84
LONG_MAX_LENGTH = MAX_BARS * STEPS_PER_BAR

SCALES: dict[str, tuple[int, ...]] = {
    "phrygian": (0, 1, 3, 5, 7, 8, 10),
    "phrygian_dominant": (0, 1, 4, 5, 7, 8, 10),
    "harmonic_minor": (0, 2, 3, 5, 7, 8, 11),
    "aeolian": (0, 2, 3, 5, 7, 8, 10),
}
ARP_PATTERNS = ("up", "down", "updown", "thirds")
KINDS = ("bass", "lead", "arp")
_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_RENDER = {
    "bass": {"velocity": 100, "accent_velocity": 127, "gate": 0.15, "slide_overlap": 0.03125},
    "lead": {"velocity": 96, "accent_velocity": 124, "gate": 0.18, "slide_overlap": 0.03125},
    "arp": {"velocity": 90, "accent_velocity": 120, "gate": 0.12, "slide_overlap": 0.03125},
}


# ---------------------------------------------------------------- helpers


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def _count(fraction: float, n: int) -> int:
    """Round-half-up of fraction * n."""
    return int(fraction * n + 0.5)


def scale_pitch(root: int, scale: str, index: int) -> int:
    """MIDI pitch of scale degree ``index`` (0 = root, 7 = root + octave, negative allowed)."""
    tones = SCALES[scale]
    return root + tones[index % 7] + 12 * (index // 7)


def _check_common(root: Any, scale: Any, bars: Any, seed: Any, bpm: Any) -> None:
    if not _is_int(root) or not MIN_ROOT <= root <= MAX_ROOT:
        raise ValueError(f"root must be an integer MIDI note {MIN_ROOT}-{MAX_ROOT}")
    if scale not in SCALES:
        raise ValueError(f"scale must be one of {sorted(SCALES)}")
    if not _is_int(bars) or not MIN_BARS <= bars <= MAX_BARS:
        raise ValueError(f"bars must be an integer {MIN_BARS}-{MAX_BARS}")
    if not _is_int(seed):
        raise ValueError("seed must be an integer")
    if not _is_num(bpm) or not MIN_BPM <= bpm <= MAX_BPM:
        raise ValueError(f"bpm must be a number {MIN_BPM:g}-{MAX_BPM:g} (Goa range)")


def _check_fraction(name: str, v: Any) -> None:
    if not _is_num(v) or not 0.0 <= v <= 1.0:
        raise ValueError(f"{name} must be a number 0-1")


def _sample(
    rng: random.Random, items: Sequence[int], weights: Sequence[float], k: int
) -> list[int]:
    """Weighted sample without replacement (Efraimidis-Spirakis), result sorted."""
    keyed = sorted(((rng.random() ** (1.0 / w), -i, it) for i, (it, w) in
                    enumerate(zip(items, weights, strict=True))), reverse=True)
    return sorted(it for _, _, it in keyed[:k])


def _pick(rng: random.Random, options: Sequence[int], weights: Sequence[float]) -> int:
    return rng.choices(list(options), weights=list(weights), k=1)[0]


def _assemble(
    kind: str, bar_notes: list[dict[int, int]], root: int, scale: str, seed: int, bpm: float,
    accent: float, slide: float, rng: random.Random, extra: dict[str, Any],
) -> dict[str, Any]:
    """bar_notes[b] = {step_in_bar: pitch}. Adds accents/slides and builds the line dict."""
    bars = len(bar_notes)
    steps: list[dict[str, Any]] = [{"on": False} for _ in range(bars * STEPS_PER_BAR)]
    for b, notes in enumerate(bar_notes):
        for s, pitch in notes.items():
            steps[b * STEPS_PER_BAR + s] = {"on": True, "note": pitch, "accent": False,
                                            "slide": False}
    on = [i for i, st in enumerate(steps) if st["on"]]
    # accents: exact count, the off-beat 8th (step % 4 == 2) preferred
    w = [3.0 if i % 4 == 2 else 1.0 for i in on]
    for i in _sample(rng, on, w, _count(accent, len(on))):
        steps[i]["accent"] = True
    # slides: only onto a different pitch on the very next step
    elig = [i for i in on if i + 1 < len(steps) and steps[i + 1]["on"]
            and steps[i + 1]["note"] != steps[i]["note"]]
    for i in _sample(rng, elig, [1.0] * len(elig), min(_count(slide, len(on)), len(elig))):
        steps[i]["slide"] = True
    line: dict[str, Any] = {
        "format": acid_midi.FORMAT_NAME, "version": FORMAT_VERSION, "seed": seed,
        "kind": kind, "root": _NAMES[root % 12], "root_note": root, "scale": scale,
        "bars": bars, "bpm": bpm, "length": len(steps), "steps": steps,
        "render": dict(_RENDER[kind]),
    }
    line.update(extra)
    acid_midi.validate_line(line, LONG_MAX_LENGTH)
    return line


def _phrase(bars: int, motif_bars: int, make_bar) -> list[dict[int, int]]:
    """Repeat a motif; the last bar of every 4-bar phrase is a fresh variation."""
    motif = [make_bar(b) for b in range(min(motif_bars, bars))]
    out = []
    for b in range(bars):
        out.append(make_bar(b) if b % 4 == 3 else dict(motif[b % len(motif)]))
    return out


# ---------------------------------------------------------------- generators


def bass_line(
    root: int, scale: str = "phrygian", bars: int = 4, density: float = 0.75,
    accent: float = 0.2, slide: float = 0.0, seed: int = 0, bpm: float = DEFAULT_BPM,
) -> dict[str, Any]:
    """Rolling off-beat bass: never on step % 4 == 0, notes on root/octave/2nd/fifth."""
    _check_common(root, scale, bars, seed, bpm)
    for n, v in (("density", density), ("accent", accent), ("slide", slide)):
        _check_fraction(n, v)
    rng = random.Random(f"goa-bass:{seed}")
    grid = [s for s in range(STEPS_PER_BAR) if s % 4 != 0]
    weights = [{2: 3.0, 3: 2.0, 1: 1.0}[s % 4] for s in grid]
    pool = (0, 7, 1, 4)  # root, octave (index 7), 2nd degree, fifth
    pool_w = (6.0, 2.0, 1.5, 1.0)

    def make_bar(_b: int) -> dict[int, int]:
        chosen = _sample(rng, grid, weights, _count(density, len(grid)))
        notes = {}
        for j, s in enumerate(chosen):
            idx = 0 if j == 0 else _pick(rng, pool, pool_w)  # bar starts on the root
            notes[s] = scale_pitch(root, scale, idx)
        return notes

    bar_notes = _phrase(bars, 1, make_bar)
    extra = {"density": density, "accent_amount": accent, "slide_amount": slide}
    return _assemble("bass", bar_notes, root, scale, seed, bpm, accent, slide, rng, extra)


def lead_line(
    root: int, scale: str = "phrygian", bars: int = 4, density: float = 0.6,
    accent: float = 0.2, slide: float = 0.15, seed: int = 0, bpm: float = DEFAULT_BPM,
) -> dict[str, Any]:
    """Ostinato lead: 1-2 bar motif, random walk over scale degrees 0..9 above ``root``."""
    _check_common(root, scale, bars, seed, bpm)
    for n, v in (("density", density), ("accent", accent), ("slide", slide)):
        _check_fraction(n, v)
    rng = random.Random(f"goa-lead:{seed}")
    steps_all = list(range(STEPS_PER_BAR))
    w = [3.0 if s == 0 else 2.0 if s % 4 == 0 else 1.5 if s % 4 == 2 else 1.0 for s in steps_all]
    state = {"idx": 0, "first": True}

    def make_bar(_b: int) -> dict[int, int]:
        chosen = _sample(rng, steps_all, w, _count(density, STEPS_PER_BAR))
        notes = {}
        for s in chosen:
            if state["first"]:
                state["first"] = False  # motif opens on the root
            else:
                opts = [d for d in (-2, -1, 0, 1, 2) if 0 <= state["idx"] + d <= 9]
                dw = {-2: 1.0, -1: 3.0, 0: 1.5, 1: 3.0, 2: 1.0}
                state["idx"] += _pick(rng, opts, [dw[d] for d in opts])
            notes[s] = scale_pitch(root, scale, state["idx"])
        return notes

    bar_notes = _phrase(bars, 2, make_bar)
    extra = {"density": density, "accent_amount": accent, "slide_amount": slide}
    return _assemble("lead", bar_notes, root, scale, seed, bpm, accent, slide, rng, extra)


def arp_line(
    root: int, scale: str = "phrygian", bars: int = 4, density: float = 1.0,
    accent: float = 0.15, slide: float = 0.0, seed: int = 0, bpm: float = DEFAULT_BPM,
    pattern: str = "up", octaves: int = 2, progression: Sequence[int] = (0,),
) -> dict[str, Any]:
    """Arpeggio over chord tones (stacked thirds in the scale) from a degree per bar."""
    _check_common(root, scale, bars, seed, bpm)
    for n, v in (("density", density), ("accent", accent), ("slide", slide)):
        _check_fraction(n, v)
    if pattern not in ARP_PATTERNS:
        raise ValueError(f"pattern must be one of {list(ARP_PATTERNS)}")
    if not _is_int(octaves) or not 1 <= octaves <= 3:
        raise ValueError("octaves must be an integer 1-3")
    prog = list(progression)
    if not prog or not all(_is_int(d) and 0 <= d <= 6 for d in prog):
        raise ValueError("progression must be a non-empty list of scale degrees 0-6")
    rng = random.Random(f"goa-arp:{seed}")
    steps_all = list(range(STEPS_PER_BAR))
    w = [3.0 if s == 0 else 1.5 if s % 4 == 0 else 1.0 for s in steps_all]
    bar_notes = []
    counter = 0
    for b in range(bars):
        deg = prog[b % len(prog)]
        tones = [deg + t + 7 * o for o in range(octaves) for t in (0, 2, 4, 6)]
        n = len(tones)
        if pattern == "up":
            order = tones
        elif pattern == "down":
            order = tones[::-1]
        elif pattern == "updown":
            order = tones + tones[-2:0:-1]
        else:  # thirds: 0,2,1,3,2,4,3,5 ...
            order = [tones[(j // 2 + (j % 2) * 2) % n] for j in range(2 * n)]
        chosen = set(_sample(rng, steps_all, w, _count(density, STEPS_PER_BAR)))
        notes = {}
        for s in steps_all:  # the sequence advances on every 16th, rests included
            if s in chosen:
                notes[s] = scale_pitch(root, scale, order[counter % len(order)])
            counter += 1
        bar_notes.append(notes)
    extra = {"density": density, "accent_amount": accent, "slide_amount": slide,
             "pattern": pattern, "octaves": octaves, "progression": prog}
    return _assemble("arp", bar_notes, root, scale, seed, bpm, accent, slide, rng, extra)


GENERATORS = {"bass": bass_line, "lead": lead_line, "arp": arp_line}


def generate(kind: str, **params: Any) -> dict[str, Any]:
    if kind not in GENERATORS:
        raise ValueError(f"kind must be one of {list(KINDS)}")
    return GENERATORS[kind](**params)


def to_json(line: Mapping[str, Any]) -> str:
    """Canonical JSON text (sorted keys): byte-identical for identical lines."""
    return json.dumps(line, sort_keys=True, indent=2) + "\n"


def line_to_midi(line: Mapping[str, Any]) -> bytes:
    """SMF bytes for a generated line (tempo event = line['bpm'], 4/4, track name = kind)."""
    return acid_midi.acid_line_to_midi(
        line, bpm=line.get("bpm"), name=f"goa-{line.get('kind', 'line')}",
        max_length=LONG_MAX_LENGTH)


# ---------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m audio_engine.goa_patterns",
        description="Seeded Goa-trance pattern generator (bass, lead, arp) -> .mid",
    )
    p.add_argument("--kind", choices=KINDS, required=True)
    p.add_argument("--root", type=int, required=True, help="MIDI note of the tonic (12-84)")
    p.add_argument("--scale", choices=sorted(SCALES), default="phrygian")
    p.add_argument("--bars", type=int, default=4)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--bpm", type=float, default=DEFAULT_BPM)
    p.add_argument("--density", type=float)
    p.add_argument("--accent", type=float)
    p.add_argument("--slide", type=float)
    p.add_argument("--pattern", choices=ARP_PATTERNS, help="arp only")
    p.add_argument("--octaves", type=int, help="arp only")
    p.add_argument("--progression", help="arp only: comma-separated degrees 0-6, one per bar")
    p.add_argument("--out", required=True, help="output .mid path")
    p.add_argument("--json", dest="json_out", help="optional: also write the line as JSON")
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    params: dict[str, Any] = {"root": a.root, "scale": a.scale, "bars": a.bars,
                              "seed": a.seed, "bpm": a.bpm}
    for k, v in (("density", a.density), ("accent", a.accent), ("slide", a.slide)):
        if v is not None:
            params[k] = v
    if a.kind == "arp":
        if a.pattern is not None:
            params["pattern"] = a.pattern
        if a.octaves is not None:
            params["octaves"] = a.octaves
        if a.progression is not None:
            try:
                params["progression"] = [int(x) for x in a.progression.split(",")]
            except ValueError:
                print("error: --progression must be comma-separated integers", file=sys.stderr)
                return 2
    try:
        line = generate(a.kind, **params)
        data = line_to_midi(line)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    Path(a.out).write_bytes(data)
    if a.json_out:
        Path(a.json_out).write_text(to_json(line), encoding="utf-8")
    n = sum(1 for s in line["steps"] if s["on"])
    print(f"wrote {a.out}: {a.kind}, {line['bars']} bars, {n} notes, {line['bpm']:g} BPM")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
