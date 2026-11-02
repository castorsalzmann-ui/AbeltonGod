"""Arrangement plan generator, step G4: the derived timeline (#221).

Design: docs/research/2026-11-02_arrangement-plan-generator-design.md section 5/7 (G4) and the
planner note 5.1-5.4 (docs/research/2026-10-29_arrangement-planner-sections-energy.md). The
thresholds are proposals of that note; this module only applies them (changing one is a user
decision). Internal code-level type, no contract (lead decision G3, 2026-11-02).

``derive_timeline(plan)`` reads a valid plan (sections, energy nodes, settings) and returns
- ``cells``: for every section the intervals between its change points (``change_points``: section
  start, then every ``change_grid`` bars). The elements that are on in a cell are decided once per
  cell from the mean energy over the cell (note 5.1: "once per 8-bar phrase, from the mean
  energy"; with ``change_grid`` 8 a cell is a phrase). So an element can only switch on a change
  point, and a bigger grid means fewer, longer cells.
- ``events``: riser, impact, downlifter, pre-drop gap and fills, in integer beats from the start
  of the track (4 beats per bar, 4/4 is fixed in v0.1).

Rules (all from the note unless marked _Interpretation_):
- drum-led (intro, groove, drop, outro): kick always on; every other element on at mean energy >=
  its threshold. In the mix zone (first 16 bars of the intro, last 16 of the outro; decided by the
  cell start) the energy is capped at 0.50. Bass: energy rule (0.45) in groove and drop; in intro
  and outro set by ``intro_outro_bass`` (``on``: outro always, intro from its last 8 bars;
  ``outside_mix_zone``: the same but never inside the mix zone; ``off``: never).
- break: kick and bass off, the other drum-led elements by their thresholds.
- breakdown: kick and bass off, no clap, no second synth; atmos and pad always on, synth from
  0.20, hats and percussion from max(own threshold, 0.40); ``rumble`` on if ``breakdown_rumble``.
- build: kick per ``build_kick`` (``at_drop``: off, unless the section before is a groove or a
  break), bass follows the kick, synth from 0.50. Nothing else is derived for a build (the note
  names no other element). The snare roll of note 5.3 is not modelled.
- events: ``riser`` over each whole build; ``impact`` (length 0) on bar 1 of every drop and of a
  groove that follows a breakdown; ``downlifter`` on bar 1 of a break or breakdown
  (_Interpretation_: it spans that bar); ``pre_drop_gap`` of that many beats ending at every
  drop's bar 1;
  ``fill`` (one bar, ``fills`` setting): ``section_change`` before a boundary between two
  drum-led sections, ``every_8`` in the last bar of every 8-bar phrase of a drum-led section that
  is followed by another drum-led section, except the last phrase of a section followed by
  something else. A boundary that has a pre-drop gap gets no fill (_Interpretation_). Consecutive
  fills carry different ``variant`` numbers (T4, C8).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from orchestrator.arrangement_plan import PHRASE_BARS, change_points, energy_at

# One table: element -> energy it is on from (note 5.1). The bass entry is used in groove and drop
# only; kick (always on in drum-led sections) is not in it.
ELEMENT_THRESHOLDS: dict[str, float] = {
    "atmos": 0.20, "hats_closed": 0.30, "perc1": 0.40, "bass": 0.45, "clap": 0.55,
    "synth": 0.65, "pad": 0.70, "hat_open": 0.75, "perc2": 0.80, "synth2": 0.90,
}
MIX_ZONE_BARS = 16
MIX_ZONE_CAP = 0.50
BREAKDOWN_DRUMS_MIN = 0.40  # hats and percussion in a breakdown (note 5.2)
BREAKDOWN_SYNTH_MIN = 0.20
BUILD_SYNTH_MIN = 0.50  # note 5.3
FILL_VARIANTS = 3
BEATS_PER_BAR = 4

DRUM_LED = ("intro", "groove", "drop", "outro")
_HATS_PERC = ("hats_closed", "hat_open", "perc1", "perc2")
_DECIMALS = 9


@dataclass(frozen=True)
class Cell:
    section: int  # index in plan["sections"]
    type: str
    start: int  # pos (bars from the track start)
    length: int  # bars
    energy: float  # mean energy over the cell (after the mix-zone cap)
    elements: frozenset[str]


@dataclass(frozen=True)
class Event:
    kind: str  # riser, impact, downlifter, pre_drop_gap, fill
    start_beat: int
    length_beats: int
    section: int  # section the event belongs to (the one whose start/end it sits at)
    variant: int | None = None  # fills only


@dataclass
class Timeline:
    cells: list[Cell] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)


def mean_energy(nodes: list[dict], a: int, b: int) -> float:
    """Exact mean of the piecewise-linear energy over ``a`` .. ``b`` (rounded to 9 decimals)."""
    xs = sorted({a, b, *(n["pos"] for n in nodes if a < n["pos"] < b)})
    area = 0.0
    for x0, x1 in zip(xs, xs[1:], strict=False):
        area += (x1 - x0) * (energy_at(nodes, x0)[1] + energy_at(nodes, x1)[0]) / 2
    return round(area / (b - a), _DECIMALS)


def _by_threshold(energy: float, names: tuple[str, ...] | list[str]) -> set[str]:
    return {n for n in names if energy >= ELEMENT_THRESHOLDS[n]}


def _cell_elements(kind: str, prev: str | None, start: int, sec_start: int, sec_len: int,
                   energy: float, settings: dict) -> frozenset[str]:
    on: set[str] = set()
    if kind in DRUM_LED:
        on.add("kick")
        on |= _by_threshold(energy, [n for n in ELEMENT_THRESHOLDS if n != "bass"])
        if kind in ("groove", "drop"):
            on |= _by_threshold(energy, ["bass"])
        else:
            mode = settings["intro_outro_bass"]
            in_zone = (start < sec_start + MIX_ZONE_BARS if kind == "intro"
                       else start >= sec_start + sec_len - MIX_ZONE_BARS)
            wanted = (start >= sec_start + sec_len - PHRASE_BARS) if kind == "intro" else True
            if mode == "on" and wanted or mode == "outside_mix_zone" and wanted and not in_zone:
                on.add("bass")
    elif kind == "break":
        on |= _by_threshold(energy, [n for n in ELEMENT_THRESHOLDS if n != "bass"])
    elif kind == "breakdown":
        on |= {"atmos", "pad"}
        if energy >= BREAKDOWN_SYNTH_MIN:
            on.add("synth")
        if energy >= BREAKDOWN_DRUMS_MIN:
            on |= _by_threshold(energy, _HATS_PERC)
        if settings["breakdown_rumble"] == "on":
            on.add("rumble")
    elif kind == "build":
        if settings["build_kick"] == "filtered_in_build" or prev in ("groove", "break"):
            on |= {"kick", "bass"}
        if energy >= BUILD_SYNTH_MIN:
            on.add("synth")
    return frozenset(on)


def derive_timeline(plan: dict) -> Timeline:
    """Element states per cell and events for a valid ``plan`` (see the module text)."""
    sections, nodes, settings = plan["sections"], plan["energy_nodes"], plan["settings"]
    points = set(change_points(plan))
    timeline = Timeline()
    for i, s in enumerate(sections):
        kind, sec_start, sec_len = s["type"], s["start_bar"] - 1, s["length_bars"]
        sec_end = sec_start + sec_len
        prev = sections[i - 1]["type"] if i else None
        cuts = sorted(p for p in points if sec_start <= p < sec_end) + [sec_end]
        for a, b in zip(cuts, cuts[1:], strict=False):
            energy = mean_energy(nodes, a, b)
            zone = (kind == "intro" and a < sec_start + MIX_ZONE_BARS) or (
                kind == "outro" and a >= sec_end - MIX_ZONE_BARS)
            if zone:
                energy = min(energy, MIX_ZONE_CAP)
            timeline.cells.append(Cell(i, kind, a, b - a, energy, _cell_elements(
                kind, prev, a, sec_start, sec_len, energy, settings)))
    timeline.events = _events(sections, settings)
    return timeline


def _events(sections: list[dict], settings: dict) -> list[Event]:
    events: list[Event] = []
    gap, fills = settings["pre_drop_gap"], settings["fills"]
    fill_count = 0
    for i, s in enumerate(sections):
        kind, start, length = s["type"], s["start_bar"] - 1, s["length_bars"]
        beat, end = start * BEATS_PER_BAR, (start + length) * BEATS_PER_BAR
        prev = sections[i - 1]["type"] if i else None
        nxt = sections[i + 1]["type"] if i + 1 < len(sections) else None
        if kind == "build":
            events.append(Event("riser", beat, length * BEATS_PER_BAR, i))
        if kind == "drop" or (kind == "groove" and prev == "breakdown"):
            events.append(Event("impact", beat, 0, i))
        if kind in ("break", "breakdown"):
            events.append(Event("downlifter", beat, BEATS_PER_BAR, i))
        if kind == "drop" and gap and i:
            events.append(Event("pre_drop_gap", beat - gap, gap, i - 1))
        if fills == "off" or kind not in DRUM_LED:
            continue
        # a fill sits in the last bar of a phrase; the section's last phrase only if a drum-led
        # section follows (no fill into a break, a build or the end of the track)
        boundary_fill = nxt in DRUM_LED and not (nxt == "drop" and gap)
        if fills == "section_change":
            phrase_ends = [end] if boundary_fill else []
        else:
            phrase_ends = [beat + PHRASE_BARS * BEATS_PER_BAR * k
                           for k in range(1, length // PHRASE_BARS + 1)]
            if not boundary_fill:
                phrase_ends.pop()
        for e in phrase_ends:
            events.append(Event("fill", e - BEATS_PER_BAR, BEATS_PER_BAR, i,
                                variant=fill_count % FILL_VARIANTS))
            fill_count += 1
    events.sort(key=lambda ev: (ev.start_beat, ev.kind))
    return events
