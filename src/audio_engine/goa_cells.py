"""Cell-based note generator for the Goa clips (#570): rule set N1-N10 of
``docs/research/2026-11-10_klassische-goa-leads-und-melodien.md``.

What this builds (a documented construction, not a statement about sound; nothing here was
listened to or tested in Live): each melodic voice plays ONE short cell of ``L`` 16th steps
that is repeated literally, runs across bar lines when ``L`` does not divide 16, and
restarts hard every ``restart_bars`` bars. Pitches come from the first ``k`` tones of a
fixed ranking of the scale (root, second, seventh, fifth, third, fourth, sixth), so a cell
hovers around the root and its neighbour. Every number below is a working value and a named
option (D-027); the report marks which rules rest on sources, on forum posts or on
derivation.

Step model (N6)
---------------
A cell step is a note, a tie (the previous note is held through the step) or a rest. Four
independent dimensions, each with its own sub-seed:

* pitch  - which tone every cell step has (also for steps that rest),
* rhythm - which steps are notes, ties or rests,
* accent - a velocity cycle of 3 or 5 (two velocity levels). It counts the NOTES of a
  block, not the grid steps ("an accent on every fifth note"): for a voice on every 16th
  that is the same thing; for a voice with rests the share of accented notes then stays
  1/3 or 1/5 whatever the rests are. With ``auto`` the cycle is one that shares no factor
  with the number of notes per cell pass, so the accents move through the cell. Cycle 5
  also accents the first note of every block (keeps the share at or above 1/5),
* slide  - which notes overlap the next note (cycle of ``slide_cycle`` steps).

The clip seed also feeds a fifth stream, the *contour*: cell length (when ``auto``), the
two candidate steps of the excursion, whether the excursion is the octave, the block that
uses which candidate and the step the variant changes. Rhythm and slides read the contour
(the excursion steps are the last to become rests; slides sit on the steps into and out of
the excursion, where the pitch always changes), never the pitches. That is why a changed
pitch sub-seed changes pitches only, and so on for the other three (N10).

Sub-seeds: ``sub[d] = int(sha256("goa_cells:sub:<seed>:<d>")[:8])`` for d in pitch, rhythm,
accent, slide, unless given in ``sub_seeds``. Every random stream is
``random.Random(int(sha256("goa_cells:<seed or sub-seed>:<dimension>:<voice>")[:8]))`` and
only integer draws (``randrange``, ``shuffle``) are used; all note maths is integer ticks.

Encoding of the result (relied on by the preview, #571): plain notes (start, end, pitch,
velocity) in ticks at PPQ 480. An accent is the higher of two velocity levels. A slide is
a note that ends ``slide_overlap_ticks`` after the next note of the same voice has started.

Looping: all cycles restart at every block start; no tie and no slide crosses a restart or
the clip end, so every note ends at or before the end of its block.

Voices (N7)
-----------
* arp   - the cell on (by default) every 16th.
* pluck - the acid line: the same step model with ties, rests and slides, 12 or 16 steps
  when the length is ``auto``.
* lead  - ``lead_mode="own"``: its own thinner cell; ``"double"``: the arp's notes
  ``12 * (1 + register[lead])`` semitones higher (this leaves the lead's register window:
  the lead and arp windows overlap, so an octave doubling cannot fit both).
* pad   - root plus fifth, held (never three pitch classes).

The moving voices (lead, arp, pluck) generated together are checked against each other
(not against the pad, which is the drone the scale's second sits on): where two notes of
different voices are exactly one semitone apart and sound together for at least
``clash_min_ticks``, an accent on either note is removed (velocity only; this can take
the accent share of that clip below 1/5). Single-voice generation has no such step, and
the four dimensions are independent per voice only there.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections.abc import Mapping, Sequence
from typing import Any

from audio_engine.acid_midi import PPQ, Note

VOICES = ("lead", "arp", "pad", "pluck")
CELL_VOICES = ("lead", "arp", "pluck")
# N1. No major scale. double_harmonic, dorian, minor_blues, hungarian_minor are new here.
SCALES: dict[str, tuple[int, ...]] = {
    "phrygian": (0, 1, 3, 5, 7, 8, 10),
    "phrygian_dominant": (0, 1, 4, 5, 7, 8, 10),
    "harmonic_minor": (0, 2, 3, 5, 7, 8, 11),
    "double_harmonic": (0, 1, 4, 5, 7, 8, 11),
    "aeolian": (0, 2, 3, 5, 7, 8, 10),
    "dorian": (0, 2, 3, 5, 7, 9, 10),
    "minor_blues": (0, 3, 5, 6, 7, 10),
    "hungarian_minor": (0, 2, 3, 6, 7, 8, 11),
}
DEFAULT_SCALE = "phrygian"
# N2: ranking by interval class above the root; scale tones outside it follow, ascending.
RANKING = ((0,), (1, 2), (10, 11), (7,), (3, 4), (5,), (8,))
CELL_LENGTHS = (5, 6, 9, 11, 12, 16)  # N3
ACID_AUTO_LENGTHS = (12, 16)  # N7: the acid line when its length is "auto"
GROUPINGS: dict[str, tuple[int, ...] | None] = {  # N4
    "displaced": None, "3+3+2": (3, 3, 2), "3+3+3+3+4": (3, 3, 3, 3, 4)}
RESTART_BARS = (2, 4, 8)
ACCENT_CYCLES = (3, 5)
LEAD_MODES = ("own", "double")
ARP_PATTERNS = ("up", "down", "updown", "random")  # accepted, unused by the cell model
SUB_SEEDS = ("pitch", "rhythm", "accent", "slide")
PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

MIN_BPM, MAX_BPM, DEFAULT_BPM = 135.0, 150.0, 145.0
MIN_BARS, MAX_BARS, DEFAULT_BARS = 1, 16, 4
MIN_REGISTER, MAX_REGISTER = -2, 2
STEP_TICKS = PPQ // 4
BAR_STEPS = 16
BAR_TICKS = 4 * PPQ
# register windows as before (lowest pitch, size); half open
WINDOW = {"lead": (60, 24), "arp": (57, 24), "pad": (48, 12), "pluck": (36, 24)}
# tones this far below / above the cell root: hover range and excursion range
HOVER_LO, HOVER_HI, EXCURSION_HI = -3, 4, 8

DEFAULT_DENSITY = {"lead": 0.45, "arp": 1.0, "pad": 0.0, "pluck": 0.875}
DEFAULT_PITCHES = {"lead": 5, "arp": 4, "pluck": 4}
MAX_PITCHES = {"lead": 6, "arp": 5, "pluck": 5}
MIN_PITCHES = 3
DEFAULT_SLIDES = {"lead": 1, "arp": 0, "pluck": 2}
DEFAULT_TIE_PERCENT = {"lead": 50, "arp": 0, "pluck": 50}
SLIDE_MIN_VOICES = ("pluck",)  # keeps one slide per bar where a candidate step exists
# name: (default, lowest, highest). Working values; source classes are listed in the PR.
INT_OPTIONS: dict[str, tuple[int, int, int]] = {
    "velocity": (84, 1, 126),            # N6 example value
    "accent_velocity": (120, 2, 127),    # N6 example value
    "gate": (50, 25, 100),               # percent of a step for a note without slide (N6)
    "root_share": (50, 0, 80),           # percent of cell steps on the root (target)
    "max_leap": (12, 12, 24),            # semitones between neighbouring cell steps
    "max_span": (8, 8, 12),              # cell range without the octave excursion
    "weight_root": (6, 1, 100),          # walk weights (N3: root, then neighbours)
    "weight_neighbour": (3, 1, 100),
    "weight_other": (1, 1, 100),
    "step_bonus": (3, 1, 100),           # factor for a move of at most 2 semitones
    "octave_percent": (50, 0, 100),      # chance that the excursion is the octave
    "variant_steps": (1, 0, 1),          # N5: steps the variant changes (0 = no variant)
    "slide_cycle": (7, 2, 16),           # steps of the slide cycle
    "slide_into_percent": (70, 0, 100),  # share of the cycle that slides INTO the excursion
    "slide_out_percent": (30, 0, 100),   # ... and OUT of it
    "slide_overlap_ticks": (15, 1, 29),  # as acid_midi (0.03125 beat)
    "pad_velocity": (78, 1, 127),
    "pad_gap_ticks": (30, 0, 119),       # the pad ends this long before it is struck again
    "clash_min_ticks": (STEP_TICKS, 1, BAR_TICKS),
}
_KNOWN = {"seed", "bars", "bpm", "root", "scale", "density", "register", "arp_pattern",
          "progression", "voices", "cell_length", "lead_mode", "restart_bars", "grouping",
          "pitches", "accent_cycle", "slides", "sub_seeds", "tie_percent"} | set(INT_OPTIONS)


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _digest_int(text: str) -> int:
    return int.from_bytes(hashlib.sha256(text.encode("ascii")).digest()[:8], "big")


def sub_seed(seed: int, dimension: str) -> int:
    """Default sub-seed of one dimension (documented derivation, see module text)."""
    return _digest_int(f"goa_cells:sub:{seed}:{dimension}")


def _stream(seed: int, dimension: str, voice: str) -> random.Random:
    return random.Random(_digest_int(f"goa_cells:{seed}:{dimension}:{voice}"))


def root_pc(root: Any) -> int:
    if not isinstance(root, str) or len(root) not in (1, 2) or root[0] not in PC \
            or (len(root) == 2 and root[1] not in "#b"):
        raise ValueError("root must be A-G with an optional # or b")
    return (PC[root[0]] + (1 if root.endswith("#") else -1 if root.endswith("b") else 0)) % 12


def ranking(scale: str) -> list[int]:
    """Scale tones (semitones above the root) in the N2 order."""
    tones = SCALES[scale]
    out = [s for group in RANKING for s in group if s in tones]
    return out + [s for s in tones if s not in out]


def _place(semitone: int) -> int:
    """Where a scale tone sits relative to the cell root: sevenths and sixths from 9
    semitones up sit below the root."""
    return semitone - 12 if semitone >= 9 else semitone


# ---------------------------------------------------------------- options

def _voice_map(value: Any, name: str, default: Mapping[str, Any], voices: Sequence[str],
               check) -> dict[str, Any]:
    out = dict(default)
    if isinstance(value, Mapping):
        unknown = set(value) - set(voices)
        if unknown:
            raise ValueError(f"{name}: unknown voices {sorted(unknown)}")
        out.update(value)
    elif value is not None:
        out = {v: value for v in voices}
    for k, v in out.items():
        check(k, v)
    return out


def normalise(params: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and fill defaults. Returns every option with its chosen value."""
    extra = set(params) - _KNOWN
    if extra:
        raise ValueError(f"unknown options {sorted(extra)} (clips have no sections or energy)")
    g = params.get
    seed = g("seed", 0)
    if not _is_int(seed) or seed < 0:
        raise ValueError("seed must be an integer >= 0")
    bars = g("bars", DEFAULT_BARS)
    if not _is_int(bars) or not MIN_BARS <= bars <= MAX_BARS:
        raise ValueError(f"bars must be an integer {MIN_BARS}-{MAX_BARS}")
    bpm = g("bpm", DEFAULT_BPM)
    if not _is_num(bpm) or not MIN_BPM <= bpm <= MAX_BPM:
        raise ValueError(f"bpm must be a number {MIN_BPM:g}-{MAX_BPM:g}")
    root = g("root", "A")
    root_pc(root)
    scale = g("scale", DEFAULT_SCALE)
    if scale not in SCALES:
        raise ValueError(f"scale must be one of {sorted(SCALES)}")

    def check_density(k: str, v: Any) -> None:
        if not _is_num(v) or not 0 <= v <= 1:
            raise ValueError(f"density[{k}] must be a number 0-1")

    def check_register(k: str, v: Any) -> None:
        if not _is_int(v) or not MIN_REGISTER <= v <= MAX_REGISTER:
            raise ValueError(f"register[{k}] must be an integer {MIN_REGISTER}..{MAX_REGISTER}")

    density = _voice_map(g("density"), "density", DEFAULT_DENSITY, VOICES, check_density)
    register = _voice_map(g("register"), "register", dict.fromkeys(VOICES, 0), VOICES,
                          check_register)
    arp_pattern = g("arp_pattern", "up")
    if arp_pattern not in ARP_PATTERNS:
        raise ValueError(f"arp_pattern must be one of {list(ARP_PATTERNS)}")
    prog = g("progression", (0,))
    if not isinstance(prog, Sequence) or isinstance(prog, str) or not 1 <= len(prog) <= 16 \
            or not all(_is_int(x) and 0 <= x < len(SCALES[scale]) for x in prog):
        raise ValueError("progression must be 1-16 scale degrees, each an integer from 0 to "
                         f"{len(SCALES[scale]) - 1} for {scale}")
    voices = g("voices", list(VOICES))
    if not isinstance(voices, Sequence) or isinstance(voices, str) or not voices \
            or any(v not in VOICES for v in voices) or len(set(voices)) != len(voices):
        raise ValueError(f"voices must be a non-empty list of distinct names from {list(VOICES)}")
    voices = [v for v in VOICES if v in voices]

    lead_mode = g("lead_mode", "own")
    if lead_mode not in LEAD_MODES:
        raise ValueError(f"lead_mode must be one of {list(LEAD_MODES)}")
    restart_bars = g("restart_bars", 4)
    if not _is_int(restart_bars) or restart_bars not in RESTART_BARS:
        raise ValueError(f"restart_bars must be one of {list(RESTART_BARS)}")
    grouping = g("grouping", "displaced")
    if grouping not in GROUPINGS:
        raise ValueError(f"grouping must be one of {list(GROUPINGS)}")

    def check_length(k: str, v: Any) -> None:
        if v != "auto" and not (_is_int(v) and v in CELL_LENGTHS):
            raise ValueError(f"cell_length[{k}] must be auto or one of {list(CELL_LENGTHS)}")

    cell_length = _voice_map(g("cell_length"), "cell_length", dict.fromkeys(CELL_VOICES, "auto"),
                             CELL_VOICES, check_length)
    if GROUPINGS[grouping] is not None and any(v != "auto" for v in cell_length.values()):
        raise ValueError(f"grouping {grouping} sets the cell length; leave cell_length at auto")

    def check_pitches(k: str, v: Any) -> None:
        if not _is_int(v) or not MIN_PITCHES <= v <= MAX_PITCHES[k]:
            raise ValueError(f"pitches[{k}] must be an integer {MIN_PITCHES}-{MAX_PITCHES[k]}")

    pitches = _voice_map(g("pitches"), "pitches", DEFAULT_PITCHES, CELL_VOICES, check_pitches)

    def check_slides(k: str, v: Any) -> None:
        if not _is_int(v) or not 0 <= v <= 2:
            raise ValueError(f"slides[{k}] must be an integer 0-2 (slides per bar)")

    slides = _voice_map(g("slides"), "slides", DEFAULT_SLIDES, CELL_VOICES, check_slides)

    def check_tie(k: str, v: Any) -> None:
        if not _is_int(v) or not 0 <= v <= 100:
            raise ValueError(f"tie_percent[{k}] must be an integer 0-100")

    tie_percent = _voice_map(g("tie_percent"), "tie_percent", DEFAULT_TIE_PERCENT, CELL_VOICES,
                             check_tie)
    accent_cycle = g("accent_cycle", "auto")
    if accent_cycle != "auto" and not (_is_int(accent_cycle) and accent_cycle in ACCENT_CYCLES):
        raise ValueError(f"accent_cycle must be auto or one of {list(ACCENT_CYCLES)}")
    given = g("sub_seeds") or {}
    if not isinstance(given, Mapping) or set(given) - set(SUB_SEEDS) \
            or not all(_is_int(v) and v >= 0 for v in given.values()):
        raise ValueError(f"sub_seeds must map names from {list(SUB_SEEDS)} to integers >= 0")
    sub = {d: given.get(d, sub_seed(seed, d)) for d in SUB_SEEDS}

    o: dict[str, Any] = {
        "seed": seed, "bars": bars, "bpm": float(bpm), "root": root, "scale": scale,
        "density": density, "register": register, "arp_pattern": arp_pattern,
        "progression": list(prog), "voices": voices, "cell_length": cell_length,
        "lead_mode": lead_mode, "restart_bars": restart_bars, "grouping": grouping,
        "pitches": pitches, "accent_cycle": accent_cycle, "slides": slides,
        "sub_seeds": sub, "tie_percent": tie_percent}
    for name, (default, lo, hi) in INT_OPTIONS.items():
        v = g(name, default)
        if not _is_int(v) or not lo <= v <= hi:
            raise ValueError(f"{name} must be an integer {lo}-{hi}")
        o[name] = v
    if o["accent_velocity"] <= o["velocity"]:
        raise ValueError("accent_velocity must be higher than velocity")
    return o


def bar_slots(o: Mapping[str, Any]) -> list[int]:
    """Index into the progression for every bar: chords spread evenly over the bars; a clip
    with fewer bars than chords holds the first ``bars`` chords, one per bar."""
    bars, k = o["bars"], len(o["progression"])
    if bars >= k:
        return [b * k // bars for b in range(bars)]
    return list(range(bars))


def _bar_degrees(o: Mapping[str, Any]) -> list[int]:
    return [o["progression"][s] for s in bar_slots(o)]


# ---------------------------------------------------------------- cell

def _weighted(rng: random.Random, items: Sequence[int], weights: Sequence[int]) -> int:
    x = rng.randrange(sum(weights))
    for item, w in zip(items, weights, strict=True):
        if x < w:
            return item
        x -= w
    raise AssertionError("unreachable")


def _cell_root(voice: str, register: int, rpc: int) -> tuple[int, int, int]:
    """(root pitch of the cell, window low, window high exclusive). The root is the lowest
    pitch of the root's class with ``HOVER_LO`` semitones of room below it."""
    lo = WINDOW[voice][0] + 12 * register
    hi = lo + WINDOW[voice][1]
    base = lo - HOVER_LO
    return base + (rpc - base) % 12, lo, hi


def _free_steps(length: int, pa: int, pb: int, starts: Sequence[int]) -> list[int]:
    """Steps that are neither an excursion candidate nor next to one (nor a group start)."""
    taken = {pa, pb}
    return [s for s in range(1, length)
            if s not in taken and s not in starts
            and (s - 1) % length not in taken and (s + 1) % length not in taken]


class _Plan:
    """Everything that defines one cell voice before it is laid out on the grid."""

    def __init__(self, o: Mapping[str, Any], voice: str) -> None:
        self.voice = voice
        rpc = root_pc(o["root"])
        self.root, self.lo, self.hi = _cell_root(voice, o["register"][voice], rpc)
        groups = GROUPINGS[o["grouping"]]

        # ---- contour (clip seed)
        rng = _stream(o["seed"], "contour", voice)
        pool = ACID_AUTO_LENGTHS if voice == "pluck" else CELL_LENGTHS
        drawn = pool[rng.randrange(len(pool))]
        if groups is not None:
            self.length = sum(groups)
        elif o["cell_length"][voice] == "auto":
            self.length = drawn
        else:
            self.length = o["cell_length"][voice]
        n = self.length
        self.starts = [0] if groups is None else [sum(groups[:i]) for i in range(len(groups))]
        positions = [s for s in range(1, n) if s not in self.starts]
        pa = positions[rng.randrange(len(positions))]
        cands = [p for p in positions if p != pa and _free_steps(n, pa, p, self.starts)]
        pb = cands[rng.randrange(len(cands))]
        self.candidates = (pa, pb)
        octave = rng.randrange(100) < o["octave_percent"]
        free = _free_steps(n, pa, pb, self.starts)
        keep = free[rng.randrange(len(free))]  # the step that always holds the neighbour
        self.neighbour_step = keep
        others = [s for s in positions if s not in (pa, pb, keep)] \
            or [s for s in positions if s not in (pa, pb)]
        self.variant_step = others[rng.randrange(len(others))]
        blocks = -(-o["bars"] // o["restart_bars"])
        self.block_positions = [pa, pb][:blocks] + [
            (pa, pb)[rng.randrange(2)] for _ in range(max(0, blocks - 2))]

        # ---- pitch (pitch sub-seed): tones are semitone offsets from the cell root
        rng = _stream(o["sub_seeds"]["pitch"], "pitch", voice)
        order = ranking(o["scale"])[:o["pitches"][voice]]
        placed = [_place(s) for s in order]
        neighbour = placed[1]
        hover = [t for t in placed if HOVER_LO <= t <= HOVER_HI]
        tones = [t for t in placed if HOVER_HI < t <= EXCURSION_HI
                 and t - neighbour <= o["max_span"]]
        pick = rng.randrange(max(1, len(tones)))
        if octave or not tones:
            self.excursion = 12 if self.root + 12 < self.hi else -12
        else:
            self.excursion = tones[pick]
            hover = [t for t in hover if self.excursion - t <= o["max_span"]]
        self.is_octave = abs(self.excursion) == 12
        near = {(p + d) % n for p in (pa, pb) for d in (-1, 1)}

        def allowed(step: int) -> list[int]:
            if step in near:
                return [t for t in hover if abs(self.excursion - t) <= o["max_leap"]]
            return hover

        special = (placed[1], placed[2])

        def weight(t: int, prev: int) -> int:
            base = o["weight_root"] if t == 0 else \
                o["weight_neighbour"] if t in special else o["weight_other"]
            return base * (o["step_bonus"] if abs(t - prev) <= 2 else 1)

        cell = [0] * n
        for s in range(1, n):
            options = allowed(s)
            got = _weighted(rng, options, [weight(t, cell[s - 1]) for t in options])
            cell[s] = 0 if s in self.starts else got
        cell[keep] = neighbour  # N2: the neighbour is always there (not next to an excursion)
        need = -(-n * o["root_share"] // 100)
        convert = [s for s in range(1, n) if s != keep]
        rng.shuffle(convert)
        for s in convert:
            if min(sum(1 for i in range(n) if i != p and cell[i] == 0) for p in (pa, pb)) >= need:
                break
            cell[s] = 0
        self.cell = cell
        alt = [t for t in allowed(self.variant_step) if t != cell[self.variant_step]]
        pick = rng.randrange(max(1, len(alt)))
        self.variant_tone = alt[pick] if alt and o["variant_steps"] else None

        # ---- rhythm (rhythm sub-seed): "n" note, "t" tie, "r" rest per cell step
        rng = _stream(o["sub_seeds"]["rhythm"], "rhythm", voice)
        notes = (int(o["density"][voice] * 1000 + 0.5) * n + 500) // 1000

        # The higher the rank, the later a step becomes a rest. An octave excursion goes
        # before its neighbours do, so a sounding octave always has the neighbours the
        # leap limit was checked against; another excursion tone is within the limit of
        # every cell tone and is kept longer. Root step and neighbour step go last.
        def rank(s: int) -> int:
            if s in (0, keep):
                return 6 if s == 0 else 5
            if s in (pa, pb):
                return (1 if s == pb else 2) if self.is_octave else (3 if s == pb else 4)
            return (3 if self.is_octave else 1) if s in near else 0

        plain = [s for s in range(n) if rank(s) == 0]
        rng.shuffle(plain)
        resting = set((plain + sorted((s for s in range(n) if rank(s)), key=lambda s: (rank(s), s))
                       )[:n - notes])
        draws = [rng.randrange(100) for _ in range(n)]
        kinds = ["n"] * n
        for s in range(n):
            if s in resting:
                # a tie follows a note only: the longest note is two steps (an 8th)
                tie = s > 0 and kinds[s - 1] == "n" and draws[s] < o["tie_percent"][voice]
                kinds[s] = "t" if tie else "r"
        self.kinds = kinds

        # ---- accent (accent sub-seed)
        rng = _stream(o["sub_seeds"]["accent"], "accent", voice)
        coprime = [a for a in ACCENT_CYCLES if math.gcd(a, max(1, notes)) == 1] \
            or list(ACCENT_CYCLES)
        pick = rng.randrange(2)
        self.accent_cycle = coprime[pick % len(coprime)] if o["accent_cycle"] == "auto" \
            else o["accent_cycle"]
        self.accent_phase = 1 + rng.randrange(self.accent_cycle - 1)

        # ---- slide (slide sub-seed): a rank per step of the slide cycle
        rng = _stream(o["sub_seeds"]["slide"], "slide", voice)
        self.slide_rank = list(range(o["slide_cycle"]))
        rng.shuffle(self.slide_rank)


def _shift(o: Mapping[str, Any], tone: int, degree: int) -> int:
    """Diatonic transposition of a tone (semitone offset from the root) by scale degrees."""
    if degree == 0:
        return tone
    scale = SCALES[o["scale"]]
    j = scale.index(tone % 12) + degree
    return scale[j % len(scale)] + 12 * (tone // 12 + j // len(scale))


def _cell_notes(o: Mapping[str, Any], plan: _Plan) -> list[Note]:
    voice, n = plan.voice, plan.length
    total = o["bars"] * BAR_STEPS
    block_steps = o["restart_bars"] * BAR_STEPS
    degrees = _bar_degrees(o)
    gate = STEP_TICKS * o["gate"] // 100
    cycle = o["slide_cycle"]
    out: list[Note] = []
    for b, b0 in enumerate(range(0, total, block_steps)):
        b1 = min(total, b0 + block_steps)
        exc_step = plan.block_positions[b]
        variant_from = b1 - BAR_STEPS if b1 - b0 >= 2 * BAR_STEPS else b1

        def kind(s: int, b0: int = b0) -> str:
            return plan.kinds[(s - b0) % n]

        def is_slide_candidate(s: int, b0: int = b0, b1: int = b1, exc: int = exc_step) -> int:
            """0 = no, 1 = into the excursion, 2 = out of it."""
            if kind(s) != "n" or s + 1 >= b1 or kind(s + 1) != "n" \
                    or degrees[s // BAR_STEPS] != degrees[(s + 1) // BAR_STEPS]:
                return 0
            return 1 if (s + 1 - b0) % n == exc else 2 if (s - b0) % n == exc else 0

        slides: set[int] = set()
        for bar0 in range(b0, b1, BAR_STEPS):
            found = []
            for s in range(bar0, min(b1, bar0 + BAR_STEPS)):
                c = is_slide_candidate(s)
                if c:
                    r = plan.slide_rank[(s - b0) % cycle]
                    share = o["slide_into_percent"] if c == 1 else o["slide_out_percent"]
                    found.append((c, r, s, r * 100 < share * cycle))
            found.sort()
            chosen = [f[2] for f in found if f[3]][:o["slides"][voice]]
            if not chosen and found and o["slides"][voice] and voice in SLIDE_MIN_VOICES:
                chosen = [found[0][2]]
            slides.update(chosen)

        count = 0  # notes of this block so far: the accent cycle runs over notes
        for s in range(b0, b1):
            if kind(s) != "n":
                continue
            i = (s - b0) % n
            tone = plan.excursion if i == exc_step else plan.cell[i]
            if s >= variant_from and i == plan.variant_step and plan.variant_tone is not None:
                tone = plan.variant_tone
            degree = degrees[s // BAR_STEPS]
            pitch = plan.root + _shift(o, tone, degree)
            if degree:
                while pitch >= plan.hi:
                    pitch -= 12
                while pitch < plan.lo:
                    pitch += 12
            ties = 0
            while s + ties + 1 < b1 and kind(s + ties + 1) == "t":
                ties += 1
            start = s * STEP_TICKS
            end = start + STEP_TICKS + o["slide_overlap_ticks"] if s in slides \
                else start + ties * STEP_TICKS + gate
            accent = count % plan.accent_cycle == plan.accent_phase \
                or (plan.accent_cycle == 5 and count == 0)
            count += 1
            out.append(Note(start, end, pitch, o["accent_velocity"] if accent else o["velocity"]))
    # Only with a chord change: folding into the register window can put the excursion on
    # the pitch next to it. One pitch cannot overlap itself, so that slide ends at the next
    # note instead. On the default progression the two pitches always differ.
    for i in range(len(out) - 1):
        if out[i].end > out[i + 1].start and out[i].pitch == out[i + 1].pitch:
            out[i] = Note(out[i].start, out[i + 1].start, out[i].pitch, out[i].velocity)
    return out


def _fifth_above(scale: Sequence[int], degree: int) -> int:
    """The scale tone whose interval above the degree is closest to 7 semitones."""
    base = scale[degree]
    return min(scale, key=lambda t: (abs((t - base) % 12 - 7), (t - base) % 12))


def _pad_notes(o: Mapping[str, Any]) -> list[Note]:
    """Root plus fifth of the degree, held per chord span (the whole clip by default).
    Density above 0 strikes again every ``4 - round(3 * density)`` bars."""
    rpc = root_pc(o["root"])
    lo = WINDOW["pad"][0] + 12 * o["register"]["pad"]
    scale = SCALES[o["scale"]]
    milli = int(o["density"]["pad"] * 1000 + 0.5)
    slots = bar_slots(o)
    out: list[Note] = []
    bar = 0
    while bar < o["bars"]:
        end = bar
        while end < o["bars"] and slots[end] == slots[bar]:
            end += 1
        degree = o["progression"][slots[bar]]
        every = end - bar if milli == 0 else 4 - (3 * milli + 500) // 1000
        pcs = sorted({(rpc + scale[degree]) % 12, (rpc + _fifth_above(scale, degree)) % 12})
        while bar < end:
            span = min(every, end - bar)
            for pc in pcs:
                out.append(Note(bar * BAR_TICKS, (bar + span) * BAR_TICKS - o["pad_gap_ticks"],
                                lo + (pc - lo) % 12, o["pad_velocity"]))
            bar += span
    return out


def _remove_clashing_accents(o: Mapping[str, Any], clips: dict[str, list[Note]]) -> None:
    """Between the moving voices only. The pad is the drone: a second or seventh next to
    its root is the scale's own construction (N1, N2), not a clash between two lines."""
    held = [(v, i, nt) for v, notes in clips.items() for i, nt in enumerate(notes)
            if v != "pad" and nt.end - nt.start >= o["clash_min_ticks"]]
    for a, (va, ia, na) in enumerate(held):
        for vb, ib, nb in held[a + 1:]:
            if va == vb or abs(na.pitch - nb.pitch) != 1 \
                    or min(na.end, nb.end) - max(na.start, nb.start) < o["clash_min_ticks"]:
                continue
            for v, i, nt in ((va, ia, na), (vb, ib, nb)):
                if nt.velocity == o["accent_velocity"]:
                    clips[v][i] = Note(nt.start, nt.end, nt.pitch, o["velocity"])


def clips_for(o: Mapping[str, Any], voices: Sequence[str]) -> dict[str, list[Note]]:
    """Notes of ``voices`` (generated together) for options already normalised."""
    clips: dict[str, list[Note]] = {}
    for v in VOICES:
        if v not in voices:
            continue
        if v == "pad":
            notes = _pad_notes(o)
        elif v == "lead" and o["lead_mode"] == "double":
            up = 12 * (1 + o["register"]["lead"])
            notes = [Note(n.start, n.end, n.pitch + up, n.velocity)
                     for n in _cell_notes(o, _Plan(o, "arp"))]
            if any(not 0 <= n.pitch <= 127 for n in notes):
                raise ValueError("lead_mode double: the doubled arp leaves the MIDI range; "
                                 "lower register[lead] or register[arp]")
        else:
            notes = _cell_notes(o, _Plan(o, v))
        clips[v] = sorted(notes, key=lambda n: (n.start, n.pitch))
    if len(clips) > 1:
        _remove_clashing_accents(o, clips)
    return clips


def generate(**params: Any) -> dict[str, list[Note]]:
    """``{voice: notes}`` for the selected voices, generated together (N7 clash rule).
    Notes are in ticks at PPQ 480, sorted by (start, pitch)."""
    o = normalise(params)
    return clips_for(o, o["voices"])


def describe(**params: Any) -> dict[str, dict[str, Any]]:
    """What the seed chose per cell voice: cell length, accent cycle, pitch count."""
    o = normalise(params)
    out: dict[str, dict[str, Any]] = {}
    for v in o["voices"]:
        if v == "pad":
            continue
        source = "arp" if v == "lead" and o["lead_mode"] == "double" else v
        plan = _Plan(o, source)
        out[v] = {"cell_length": plan.length, "accent_cycle": plan.accent_cycle,
                  "pitches": o["pitches"][source], "slides_per_bar": o["slides"][source],
                  "octave_excursion": plan.is_octave}
    return out
