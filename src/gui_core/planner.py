"""Arrangement planner page, Qt-free part (#139, D-024, sprint W2 workstream A).

The page is a thin shell over the merged planner code: ``plan_layout`` (G1),
``generate_plan`` (G2), ``derive_timeline`` (G4) and the one checker ``plan_problems``. This
module never computes a section, a node value or an element state itself; it keeps the user's
inputs (genre, tempo, length, the 11 style settings, the drawn energy nodes), calls the
planner, translates its codes into German texts and writes the plan file.

Drawn nodes follow the planner's definition (``arrangement_generator`` module text): they are
kept with identical ``pos``, ``value`` and order, every undrawn node at their ``pos`` is
dropped, and builds and the outro take their anchors from them. The editing helpers below only
keep the list in the shape ``generate_plan`` accepts (integer ``pos`` in 0..total, ``pos``
never decreasing, at most two nodes at one ``pos``, no pair at the track edges).

Export: arrangement-plan v0.1 JSON (``contracts/arrangement-plan.schema.json``), checked with
``plan_problems`` right before writing, into ``<Ausgabeordner>/Plans``; an existing file is
never overwritten. Nothing goes to Live and no model is called.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gui_core.form import parse_number
from orchestrator.arrangement_generator import generate_plan
from orchestrator.arrangement_layout import (
    BARS_RANGE,
    BPM_RANGE,
    GENRES,
    SETTING_ALLOWED,
    SETTING_DEFAULTS,
    plan_layout,
)
from orchestrator.arrangement_plan import energy_at, plan_problems
from orchestrator.arrangement_timeline import Timeline, derive_timeline
from orchestrator.plan_tools import build_request

PLANS_FOLDER = "Plans"
VALUE_DECIMALS = 2  # drawn values are rounded to this (a mouse cannot place more exactly)

GENRE_LABELS = {"techno": "Techno", "trance": "Trance"}
UNITS = (("minutes", "Minuten"), ("bars", "Takte"))

SECTION_LABELS = {
    "intro": "Intro", "groove": "Groove", "break": "Break", "breakdown": "Breakdown",
    "build": "Build-up", "drop": "Drop", "outro": "Outro",
}
# Lane order of the element timeline (drums, low end, then the melodic layers).
ELEMENT_LABELS = {
    "kick": "Kick", "bass": "Bass", "rumble": "Rumble", "hats_closed": "Hats zu",
    "hat_open": "Hat offen", "perc1": "Perc 1", "perc2": "Perc 2", "clap": "Clap",
    "atmos": "Atmo", "pad": "Pad", "synth": "Synth", "synth2": "Synth 2",
}
EVENT_LABELS = {
    "riser": "Riser", "impact": "Impact", "downlifter": "Downlifter",
    "pre_drop_gap": "Pause vor Drop", "fill": "Fill",
}


@dataclass(frozen=True)
class SettingSpec:
    key: str
    label: str
    group: str
    values: tuple  # the planner's allowed values (SETTING_ALLOWED), in its order
    labels: tuple[str, ...]  # one German label per value
    help: str


def _spec(key: str, label: str, group: str, labels: dict | None, help_text: str) -> SettingSpec:
    values = SETTING_ALLOWED[key]
    shown = tuple(labels[v] if labels else str(v) for v in values) if key != "change_grid" \
        else ()
    return SettingSpec(key, label, group, values, shown, help_text)


SETTING_SPECS: tuple[SettingSpec, ...] = (
    _spec("intro_length", "Intro (Takte)", "Form", None,
          "Länge des Intros in Takten."),
    _spec("outro_length", "Outro mind. (Takte)", "Form", None,
          "Mindestlänge des Outros. Nach einem vollen Drop braucht der Energie-Abstieg "
          "(ein Element pro 8-Takt-Grenze) 64 Takte; kürzer wird es dadurch nicht."),
    _spec("breakdown_count", "Breakdowns", "Form", None,
          "1 oder 2. Ein zweiter Breakdown hängt Build-up und Drop nach Drop 2 an."),
    _spec("breakdown_length", "Breakdown (Takte)", "Form", None,
          "Länge jedes Breakdowns in Takten."),
    _spec("second_drop", "Zweiter Drop", "Energie",
          {"stronger": "Stärker", "equal": "Gleich", "ask": "Offen"},
          "Stärker: jeder spätere Drop liegt 0,05 höher. Gleich: wie der erste. Offen: wie "
          "der erste, mit Hinweis."),
    _spec("build_kick", "Kick im Build-up", "Übergänge",
          {"filtered_in_build": "Gefiltert im Build", "at_drop": "Erst zum Drop"},
          "Ob die Kick im Build-up läuft oder erst mit dem Drop zurückkommt."),
    _spec("pre_drop_gap", "Pause vor Drop (Takte)", "Übergänge", None,
          "Stille vor jedem Drop, in Takten (0 = keine)."),
    _spec("fills", "Fills", "Übergänge",
          {"off": "Aus", "section_change": "Bei Abschnittswechsel", "every_8": "Alle 8 Takte"},
          "Ein-Takt-Fills zwischen Kick-Abschnitten."),
    _spec("change_grid", "Wechselraster (Takte)", "Übergänge", None,
          "Abstand der Punkte, an denen Elemente ein- oder aussetzen dürfen, gezählt ab "
          "jedem Abschnittsbeginn (1-64)."),
    _spec("intro_outro_bass", "Bass in Intro/Outro", "Bass",
          {"on": "An", "outside_mix_zone": "Außerhalb Mix-Zone", "off": "Aus"},
          "Mix-Zone: die ersten 16 Takte des Intros und die letzten 16 des Outros."),
    _spec("breakdown_rumble", "Rumble im Breakdown", "Bass",
          {"off": "Aus", "on": "An"}, "Tiefes Rumble unter dem Breakdown."),
)
SETTING_GROUPS = ("Form", "Energie", "Übergänge", "Bass")


# --- German texts for the planner's codes ------------------------------------------------------

def _nearest(detail: dict) -> str:
    near = detail.get("nearest")
    if isinstance(near, dict):
        parts = [str(v) for v in (near.get("below"), near.get("above")) if v is not None]
    else:
        parts = [str(v) for v in (near or [])]
    return " oder ".join(parts) + " Takte" if parts else "keine"


# German for the ``reason`` texts of the planner's ``drawn_node_invalid`` (``_check_drawn``).
DRAWN_REASONS = {
    "not a list": "keine Liste",
    "needs integer pos and value": "braucht einen ganzen Takt und einen Wert",
    "value outside 0..1": "Wert außerhalb 0..1",
    "pos decreases": "liegt vor dem vorigen Punkt",
    "third node at one pos": "dritter Punkt auf einem Takt",
    "pair at the track edge": "Stufe am Anfang oder Ende des Tracks",
}


def error_text(error: dict) -> str:
    """One German sentence per planner error code; unknown codes show code and detail."""
    code, d = error.get("code"), error.get("detail") or {}
    if code == "bad_bpm":
        lo, hi = d.get("allowed") or BPM_RANGE
        return f"BPM muss eine Zahl von {lo} bis {hi} sein."
    if code == "length_out_of_range":
        return (f"Die Länge liegt außerhalb von {BARS_RANGE[0]}-{BARS_RANGE[1]} Takten. "
                f"Nächste: {_nearest(d)}.")
    if code == "length_not_multiple_of_8":
        return f"Die Länge in Takten muss ein Vielfaches von 8 sein. Nächste: {_nearest(d)}."
    if code == "length_infeasible":
        return (f"{d.get('target_bars')} Takte lassen sich mit diesen Einstellungen nicht in "
                f"Abschnitte teilen. Nächste mögliche Längen: {_nearest(d)} (oder Intro / "
                "Breakdown kürzer stellen).")
    if code == "drawn_node_invalid":
        reason = str(d.get("reason"))
        german = DRAWN_REASONS.get(reason)
        if german is None and reason.startswith("pos outside"):
            german = "liegt außerhalb des Tracks"
        return (f"Gezeichneter Punkt {d.get('index')} ungültig: {german or reason}. Punkt "
                "löschen oder verschieben.")
    if code == "outro_slot_too_short":
        return (f"Die gezeichnete Energie lässt das Outro so hoch beginnen, dass es "
                f"{d.get('required')} Takte bräuchte; es hat {d.get('slot')}. Punkt am "
                "Outro-Beginn senken oder Outro länger stellen.")
    if code == "bad_genre":
        return "Genre muss Techno oder Trance sein."
    return f"{code}: {d}"


def note_text(item: dict) -> str:
    """German text for a planner warning or adjustment, with the planner's own detail."""
    code, detail = item.get("code"), item.get("detail")
    label = {
        "duration_window": "Dauer außerhalb 4-7 min",
        "outro_lengthened": "Outro verlängert",
        "second_drop_ask": "Zweiter Drop offen",
    }.get(code, code)
    return f"{label} ({detail})" if detail else str(label)


# --- state -------------------------------------------------------------------------------------

@dataclass
class PlannerState:
    """What the page shows after one planner call."""

    plan: dict | None = None
    timeline: Timeline | None = None
    sections: list[dict] = field(default_factory=list)  # from the layout, also with errors
    total_bars: int = 0
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # planner warnings and adjustments
    ignored_drawn: int = 0  # drawn nodes behind the end of the track (not sent)

    @property
    def ok(self) -> bool:
        return self.plan is not None


class PlannerModel:
    """Inputs of the planner page and the last planner result (``state``)."""

    def __init__(self) -> None:
        self.genre = "techno"
        self.bpm_text = "140"
        self.length_text = "6"
        self.unit = "minutes"
        self.settings: dict[str, Any] = dict(SETTING_DEFAULTS)
        self.drawn: list[dict] = []  # {"pos": int, "value": float}, in plan order
        self.state = PlannerState()
        self.compute()

    # --- inputs ------------------------------------------------------------------------------
    def set_setting(self, key: str, value: Any) -> None:
        if key not in SETTING_ALLOWED or value not in SETTING_ALLOWED[key]:
            raise ValueError(f"{key}={value!r} is not an allowed planner setting")
        self.settings[key] = value

    def _numbers(self) -> tuple[Any, Any, list[str]]:
        bpm, length = parse_number(self.bpm_text), parse_number(self.length_text)
        errors = []
        if bpm is None:
            errors.append(f"BPM ist keine Zahl ({self.bpm_text!r}).")
        if length is None:
            errors.append(f"Länge ist keine Zahl ({self.length_text!r}).")
        return bpm, length, errors

    def compute(self) -> PlannerState:
        """Call the planner with the current inputs; the result is ``self.state``."""
        state = PlannerState()
        bpm, length, errors = self._numbers()
        if errors:
            state.errors = errors
            self.state = state
            return state
        req = build_request(self.genre, bpm, length, self.unit, list(self.settings.items()))
        layout = plan_layout(req)
        if not layout.ok:
            state.errors = [error_text(e) for e in layout.errors]
            self.state = state
            return state
        state.sections, state.total_bars = list(layout.sections), layout.total_bars
        total = layout.total_bars
        # Nodes behind the end are not sent, nor the second node of a step pair that lands on
        # the end bar after shortening (the planner allows no pair at the track edge).
        active = [dict(n) for n in self.drawn if n["pos"] < total]
        active += [dict(n) for n in self.drawn if n["pos"] == total][:1]
        state.ignored_drawn = len(self.drawn) - len(active)
        result = generate_plan(req, drawn_nodes=active)
        state.notes = [note_text(a) for a in result.adjustments + result.warnings]
        if not result.ok:
            state.errors = [error_text(e) for e in result.errors]
        else:
            state.plan = result.plan
            state.timeline = derive_timeline(result.plan)
        self.state = state
        return state

    # --- drawn nodes -------------------------------------------------------------------------
    def _total(self) -> int:
        return self.state.total_bars

    def _fits(self, pos: int, skip: int | None = None) -> bool:
        """Whether one more node may sit at ``pos`` (at most two, no pair at the edges)."""
        same = sum(1 for i, n in enumerate(self.drawn) if n["pos"] == pos and i != skip)
        return same == 0 or (same == 1 and pos not in (0, self._total()))

    @staticmethod
    def _value(value: float) -> float:
        return round(min(max(float(value), 0.0), 1.0), VALUE_DECIMALS)

    def add_node(self, pos: int, value: float) -> int | None:
        """Insert a drawn node (after the drawn nodes already at ``pos``: a second one there
        is the leaving value of a step). Returns its index, or None if ``pos`` is full."""
        total = self._total()
        if not total:
            return None
        pos = min(max(int(pos), 0), total)
        if not self._fits(pos):
            return None
        index = sum(1 for n in self.drawn if n["pos"] <= pos)
        self.drawn.insert(index, {"pos": pos, "value": self._value(value)})
        return index

    def move_node(self, index: int, pos: int, value: float) -> tuple[int, float]:
        """Move drawn node ``index``. ``pos`` stays between its neighbours (the order never
        changes) and keeps the old place when the new one is full. Returns (pos, value)."""
        node = self.drawn[index]
        lo = self.drawn[index - 1]["pos"] if index > 0 else 0
        hi = self.drawn[index + 1]["pos"] if index + 1 < len(self.drawn) else self._total()
        new = min(max(int(pos), lo), hi)
        if new != node["pos"] and self._fits(new, skip=index):
            node["pos"] = new
        node["value"] = self._value(value)
        return node["pos"], node["value"]

    def remove_node(self, index: int) -> None:
        del self.drawn[index]

    def clear_drawn(self) -> None:
        self.drawn.clear()


def section_rows(state: PlannerState) -> list[tuple[str, str, int, str]]:
    """(name, bars "a-b", length, energy "start -> end") per section of a valid plan; the
    energies are the planner's own (``energy_at``: leaving value at the start, arriving value
    at the end)."""
    if state.plan is None:
        return []
    nodes, rows = state.plan["energy_nodes"], []
    for s in state.plan["sections"]:
        start, length = s["start_bar"] - 1, s["length_bars"]
        e0, e1 = energy_at(nodes, start)[1], energy_at(nodes, start + length)[0]
        rows.append((SECTION_LABELS.get(s["type"], s["type"]),
                     f"{s['start_bar']}-{s['start_bar'] + length - 1}", length,
                     f"{e0:.2f} → {e1:.2f}"))
    return rows


# --- export ------------------------------------------------------------------------------------

class ExportError(ValueError):
    """The plan fails the checker (never expected: ``generate_plan`` checks it too)."""


def plans_dir(output_root: Path) -> Path:
    return Path(output_root) / PLANS_FOLDER


def plan_file_name(plan: dict, genre: str) -> str:
    bpm = re.sub(r"[^0-9]+", "-", f"{plan['bpm']:g}").strip("-")
    return f"arrangement_{genre}_{bpm}bpm_{plan['total_bars']}bars"


def export_plan(plan: dict, folder: Path, genre: str) -> Path:
    """Write ``plan`` as JSON into ``folder`` (created) under a new name; never overwrites.
    The plan is checked with ``plan_problems`` first. Raises ``ExportError`` or ``OSError``."""
    problems = plan_problems(plan)
    if problems:
        raise ExportError("; ".join(problems))
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    base = plan_file_name(plan, genre if genre in GENRES else "plan")
    text = json.dumps(plan, indent=2) + "\n"
    for n in range(1, 1000):
        path = folder / (f"{base}.json" if n == 1 else f"{base}_{n:03d}.json")
        try:
            handle = path.open("x", encoding="utf-8")
        except FileExistsError:
            continue
        try:
            with handle:
                handle.write(text)
        except BaseException:
            path.unlink(missing_ok=True)  # no half-written plan file is left behind
            raise
        return path
    raise FileExistsError(f"no free file name for {base} in {folder}")
