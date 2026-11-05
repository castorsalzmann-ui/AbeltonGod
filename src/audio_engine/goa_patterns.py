"""Seeded Goa-trance pattern generator: bass, lead and arpeggio lines as plain data.

Output is an acid-line dict (format "acid_line", version "0.1-proposal", see
``acid_midi``) so ``acid_midi.acid_line_to_midi`` writes it; extra top-level keys
(``kind``, ``bars``, ``bpm`` ...) are informational. Pure, stdlib only: same parameters
and seed give identical dicts, JSON text and MIDI bytes (a local ``random.Random`` is
the only source of randomness; no clock, no global RNG).

Musical assumptions (HYPOTHESES, not facts). They were written before the research note
docs/research/2026-11-03_goa-trance-musicology-and-sound.md (G1) was read; the table
below reconciles them with it. The note itself calls its numbers starter hypotheses.

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

Reconciliation with the G1 note (differences are known, behaviour is unchanged):

=====================  ===========================  ================================
Item                   This module                  G1 note
=====================  ===========================  ================================
Bass rhythm            default density 0.75 (9 of   default ``three_after_kick``
                       12 off-kick steps);          (steps 1,2,3 of each beat);
                       density 1.0 gives the same   same rhythm as density 1.0
                       rhythm
First roll note        same velocity as the others  played quieter
                       (not implemented)            (``roll_first_velocity`` 0.6)
Tempo range            hard 135-150 BPM             sources say 130-150 (finding 2)
Bass octave jumps      root octave in the pitch     ``octave_jump_prob`` 0 for bass
                       pool, about 19 % of bass     (no Goa source)
                       notes after the first
Variation bar          fresh bar every 4th bar      every 8th bar
Line keys              ``kind``, ``scale``, ``bpm`` ``role``, ``mode``, ``bpm_hint``
Roll patterns          ``roll=``: off_kick_16th     also offbeat_8th, gallop, full_16th
                       (default), offbeat_8th,
                       gallop (16th grid); true
                       triplet: bass_triplet_gallop
=====================  ===========================  ================================

Format decision (lead, 2026-11-03): the keys of this module (``kind``, ``scale``,
``bpm``) ARE the ``goa_line`` format; the proposal in section 5 of the G1 note is
superseded by it. The line stays an ``acid_line`` (version "0.1-proposal") with extra
informational keys.

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

from audio_engine import acid_midi, goa_rhythm

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


ROLLS = ("off_kick_16th", "offbeat_8th", "gallop", "offbeat_ghost")
TRIPLET_GALLOP = goa_rhythm.TRIPLET_GALLOP
ROLL_CHOICES = (*ROLLS, TRIPLET_GALLOP)
# D-027 (#392): the roll positions, the bass pitch pool and the ghost/triplet constants are
# owned by ``goa_rhythm`` (the rhythm section's single source); the names below are kept so
# this module and its callers read the same values.
_ROLL_GRID = goa_rhythm.ROLL_GRID
_BASS_POOL = goa_rhythm.BASS_POOL
_BASS_POOL_W = goa_rhythm.BASS_POOL_W
TRIPLET_GATE_BEATS = goa_rhythm.TRIPLET_GATE_BEATS
GHOST_MAIN_SHARE, GHOST_SIDE_SHARE = goa_rhythm.GHOST_MAIN_SHARE, goa_rhythm.GHOST_SIDE_SHARE
TRIPLET_VELOCITY = goa_rhythm.TRIPLET_VELOCITY
TRIPLET_ACCENT_VELOCITY = goa_rhythm.TRIPLET_ACCENT_VELOCITY


def bass_line(
    root: int, scale: str = "phrygian", bars: int = 4, density: float | None = None,
    accent: float = 0.2, slide: float = 0.0, seed: int = 0, bpm: float = DEFAULT_BPM,
    roll: str = "off_kick_16th",
) -> dict[str, Any]:
    """Rolling bass on the 16th grid, never on step % 4 == 0; notes on root/octave/2nd/fifth.

    ``roll`` picks the rhythm: ``off_kick_16th`` (default, the three 16ths after the kick,
    thinned by ``density``, default 0.75), ``offbeat_8th`` (step 2 of each beat, default
    density 1.0) or ``gallop`` (steps 1 and 3 of each beat, default density 1.0). A true
    triplet gallop does not fit the 16-step grid; see ``bass_triplet_gallop``.
    """
    _check_common(root, scale, bars, seed, bpm)
    if roll not in ROLLS:
        raise ValueError(f"roll must be one of {list(ROLLS)} (triplet: bass_triplet_gallop)")
    if roll == "offbeat_ghost":
        return _bass_ghost(root, scale, bars, accent, slide, seed, bpm)
    grid_t, wmap, default_density = _ROLL_GRID[roll]
    if density is None:
        density = default_density
    for n, v in (("density", density), ("accent", accent), ("slide", slide)):
        _check_fraction(n, v)
    rng = random.Random(f"goa-bass:{seed}")
    grid = list(grid_t)
    weights = [wmap[s % 4] for s in grid]

    def make_bar(_b: int) -> dict[int, int]:
        chosen = _sample(rng, grid, weights, _count(density, len(grid)))
        notes = {}
        for j, s in enumerate(chosen):
            idx = 0 if j == 0 else _pick(rng, _BASS_POOL, _BASS_POOL_W)  # bar starts on root
            notes[s] = scale_pitch(root, scale, idx)
        return notes

    bar_notes = _phrase(bars, 1, make_bar)
    extra = {"density": density, "accent_amount": accent, "slide_amount": slide}
    if roll != "off_kick_16th":  # the default keeps its exact key set
        extra["roll"] = roll
    return _assemble("bass", bar_notes, root, scale, seed, bpm, accent, slide, rng, extra)


def _bass_ghost(
    root: int, scale: str, bars: int, accent: float, slide: float, seed: int, bpm: float,
) -> dict[str, Any]:
    """Off-beat 8th on ``GHOST_MAIN_SHARE`` of all beats, the 16th before and after it on
    ``GHOST_SIDE_SHARE`` of all beats each (exact counts over the whole span, positions seeded);
    never on a kick step. ``density`` does not apply."""
    for n, v in (("accent", accent), ("slide", slide)):
        _check_fraction(n, v)
    rng = random.Random(f"goa-bass-ghost:{seed}")
    beats = list(range(bars * 4))
    flat = [1.0] * len(beats)
    chosen = {
        2: _sample(rng, beats, flat, _count(GHOST_MAIN_SHARE, len(beats))),
        1: _sample(rng, beats, flat, _count(GHOST_SIDE_SHARE, len(beats))),
        3: _sample(rng, beats, flat, _count(GHOST_SIDE_SHARE, len(beats))),
    }
    bar_notes: list[dict[int, int]] = []
    for b in range(bars):
        steps = sorted(4 * (bt % 4) + off for off, bl in chosen.items() for bt in bl
                       if bt // 4 == b)
        notes = {}
        for j, s in enumerate(steps):
            idx = 0 if j == 0 else _pick(rng, _BASS_POOL, _BASS_POOL_W)
            notes[s] = scale_pitch(root, scale, idx)
        bar_notes.append(notes)
    extra = {"density": None, "accent_amount": accent, "slide_amount": slide,
             "roll": "offbeat_ghost"}
    return _assemble("bass", bar_notes, root, scale, seed, bpm, accent, slide, rng, extra)


def bass_triplet_gallop(
    root: int, scale: str = "phrygian", bars: int = 4, density: float = 1.0,
    accent: float = 0.2, seed: int = 0, bpm: float = DEFAULT_BPM,
) -> dict[str, Any]:
    """Triplet gallop bass as a NATIVE arrangement pattern (``arrangement_midi``).

    Each beat is split in three triplet 8ths; the first belongs to the kick, the bass uses
    the second and third (starts at beat + 1/3 and beat + 2/3, exact at PPQ 480). Pitches
    follow the same pool as ``bass_line``; the bar starts on the root; accents are an exact
    count. Returns ``{"length_beats", "notes"}`` only (no 16th grid, so no acid_line).
    Whether this is the rhythm the user means by Goa is not established (G1 finding 9).
    """
    _check_common(root, scale, bars, seed, bpm)
    _check_fraction("density", density)
    _check_fraction("accent", accent)
    rng = random.Random(f"goa-bass-triplet:{seed}")
    slots = list(range(8))  # slot = 2 * beat + (0 for beat+1/3, 1 for beat+2/3)
    weights = [1.5 if s % 2 == 0 else 2.0 for s in slots]

    def make_bar(_b: int) -> dict[int, int]:
        chosen = _sample(rng, slots, weights, _count(density, len(slots)))
        notes = {}
        for j, s in enumerate(chosen):
            idx = 0 if j == 0 else _pick(rng, _BASS_POOL, _BASS_POOL_W)
            notes[s] = scale_pitch(root, scale, idx)
        return notes

    bar_notes = _phrase(bars, 1, make_bar)
    flat = [(b, s, p) for b, nb in enumerate(bar_notes) for s, p in sorted(nb.items())]
    accented = set(_sample(rng, list(range(len(flat))), [1.0] * len(flat),
                           _count(accent, len(flat))))
    notes_out = []
    for i, (b, s, p) in enumerate(flat):
        start = 4.0 * b + s // 2 + (s % 2 + 1) / 3.0
        notes_out.append({"pitch": p, "start": start, "duration": TRIPLET_GATE_BEATS,
                          "velocity": TRIPLET_ACCENT_VELOCITY if i in accented
                          else TRIPLET_VELOCITY})
    return {"length_beats": 4.0 * bars, "notes": notes_out}


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
    p.add_argument("--roll", choices=ROLL_CHOICES,
                   help="bass only: rhythm (default off_kick_16th; triplet_gallop is written "
                        "through arrangement_midi)")
    p.add_argument("--pattern", choices=ARP_PATTERNS, help="arp only")
    p.add_argument("--octaves", type=int, help="arp only")
    p.add_argument("--progression", help="arp only: comma-separated degrees 0-6, one per bar")
    p.add_argument("--out", required=True, help="output .mid path")
    p.add_argument("--json", dest="json_out", help="optional: also write the line as JSON")
    return p


def _main_triplet(a: argparse.Namespace, params: dict[str, Any]) -> int:
    from audio_engine import arrangement_midi

    kw = {k: v for k, v in params.items() if k != "slide"}
    if a.slide:
        print("error: --slide does not apply to triplet_gallop", file=sys.stderr)
        return 2
    try:
        pat = bass_triplet_gallop(**kw)
        arr = {"format": "goa_arrangement", "version": "0.1-proposal",
               "title": "goa-bass triplet gallop", "tempo": a.bpm,
               "key": {"root": _NAMES[a.root % 12], "scale": a.scale},
               "elements": [{"name": "bass", "pattern": pat}],
               "sections": [{"name": "Bass", "bars": a.bars, "energy": 1.0,
                             "elements": ["bass"]}]}
        data = arrangement_midi.arrangement_to_midi(arr)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if json_path := a.json_out:
        Path(json_path).write_text(json.dumps(pat, sort_keys=True, indent=2) + "\n",
                                   encoding="utf-8")
    Path(a.out).write_bytes(data)
    print(f"wrote {a.out}: bass triplet_gallop, {a.bars} bars, {len(pat['notes'])} notes, "
          f"{a.bpm:g} BPM")
    return 0


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    params: dict[str, Any] = {"root": a.root, "scale": a.scale, "bars": a.bars,
                              "seed": a.seed, "bpm": a.bpm}
    for k, v in (("density", a.density), ("accent", a.accent), ("slide", a.slide)):
        if v is not None:
            params[k] = v
    if a.roll is not None and a.kind != "bass":
        print("error: --roll applies to --kind bass only", file=sys.stderr)
        return 2
    if a.roll == TRIPLET_GALLOP:
        return _main_triplet(a, params)
    if a.roll is not None:
        params["roll"] = a.roll
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
