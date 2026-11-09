"""Goa-Melodie form model, option translation and timeline plan (no Qt).

The GUI's Goa generator is ``python -m audio_engine.goa_melody`` (lead, arp, pad, pluck as
multitrack MIDI, one track per voice). D-033: the Goa plugin makes only melodies; arranging a
whole song belongs to the arrangement planner, so ``audio_engine.goa_arrangement`` (still a CLI)
is not imported here and no GUI path can reach it.

This module does not copy the generator's rules:

* The option list (names, choices, defaults) is read from the CLI's own ``build_parser()``;
  a test enumerates every parser option and fails when the form misses one.
* The form turns its state into the same ``--flag=value`` list a user would type, and the CLI's
  parser reads it back (:func:`parse_argv`), so choices and types are checked by the CLI itself.
* The namespace becomes keyword arguments exactly as the module's ``main`` does it
  (:func:`call_of`; a test compares the written bytes against the real ``main``).
* Ranges and combinations are decided by the module's ``build_arrangement`` (ValueError text
  is shown as is); the timeline is drawn from the ``sections`` of its result (the melody's own
  phrase sections, not a song form).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

from audio_engine import goa_melody

from .form import parse_number

MELODY = "melody"  # the only Goa generator of the GUI (D-033)
TITLE = "Goa-Melodie"

SKIPPED_DESTS = ("help", "out")  # --out is the folder row of the page

LABELS_DE: dict[str, str] = {
    "seed": "Seed", "bpm": "Tempo", "root": "Grundton", "scale": "Tonleiter",
    "voices": "Melodie-Stimmen", "density": "Dichte", "register": "Register (Oktaven)",
    "arp_pattern": "Arp-Muster", "progression": "Akkordfolge (Stufen)",
    "length": "Phrasenlänge (Takte)", "sections": "Abschnitte",
}
UNITS = {"bpm": "BPM", "length": "Takte"}
GROUP_OF: dict[str, str] = {}
for _d in ("seed", "bpm", "root", "scale"):
    GROUP_OF[_d] = "Grundlagen"
for _d in ("voices", "density", "register", "arp_pattern", "progression"):
    GROUP_OF[_d] = "Melodie"
for _d in ("length", "sections"):
    GROUP_OF[_d] = "Phrasen"
GROUPS = ("Grundlagen", "Melodie", "Phrasen")

# Hints for free-text fields (the module decides what is valid).
HINTS = {
    "density": "0 bis 1, oder je Stimme: lead=0.5,arp=1",
    "register": "-2 bis 2, oder je Stimme: lead=1,pad=-1",
    "progression": "Stufen 0 bis 6, durch Komma getrennt, z. B. 0,5,6,4",
    "sections": "Name:Takte:Energie:stimme+stimme, durch Komma getrennt",
    "root": "A bis G, optional mit # oder b",
}
MULTI_VOICES = {"voices": tuple(goa_melody.VOICES)}


@dataclass(frozen=True)
class OptionSpec:
    dest: str
    flag: str
    label: str
    kind: str  # "int" | "float" | "enum" | "text" | "multi" | "flag"
    choices: tuple[str, ...]
    default: str  # text shown at the start ("" when the CLI has no default)
    optional: bool  # CLI default is None: only sent when switched on
    help: str
    group: str
    unit: str = ""

    @property
    def range_text(self) -> str:
        if self.kind in ("enum", "multi"):
            return " / ".join(self.choices)
        if self.kind == "flag":
            return "ja / nein"
        if self.dest in HINTS:
            return HINTS[self.dest]
        if self.dest == "bpm":
            return f"{goa_melody.MIN_BPM:g} bis {goa_melody.MAX_BPM:g} BPM"
        return self.unit or ("ganze Zahl" if self.kind == "int" else "Zahl")


def _choice_texts(dest: str, action: argparse.Action) -> tuple[str, ...]:
    if dest in MULTI_VOICES:
        return tuple(MULTI_VOICES[dest])
    return tuple(str(c) for c in (action.choices or ()))


def _spec(action: argparse.Action) -> OptionSpec:
    dest = action.dest
    choices = _choice_texts(dest, action)
    if action.nargs == 0 and action.const is True:
        kind = "flag"
    elif dest in MULTI_VOICES:
        kind = "multi"
    elif choices:
        kind = "enum"
    elif action.type is int:
        kind = "int"
    elif action.type is float:
        kind = "float"
    else:
        kind = "text"
    default = action.default
    optional = default is None
    return OptionSpec(
        dest=dest, flag=action.option_strings[0], label=LABELS_DE.get(dest, dest), kind=kind,
        choices=choices, default="" if optional else _default_text(default),
        optional=optional and kind != "flag", help=action.help or "",
        group=GROUP_OF.get(dest, "Grundlagen"), unit=UNITS.get(dest, ""),
    )


def _default_text(value: Any) -> str:
    if isinstance(value, bool):
        return "nein" if not value else "ja"
    return f"{value:g}" if isinstance(value, float) else str(value)


def parser_of() -> argparse.ArgumentParser:
    return goa_melody.build_parser()


def option_specs() -> list[OptionSpec]:
    """One spec per CLI option (except ``--out``), in the parser's order."""
    return [_spec(a) for a in parser_of()._actions if a.dest not in SKIPPED_DESTS]


# --- argv <-> namespace -> call --------------------------------------------------------------

class OptionError(ValueError):
    """The CLI's own parser refused the options (message is the parser's)."""


def parse_argv(argv: list[str] | tuple[str, ...]) -> argparse.Namespace:
    parser = parser_of()

    def refuse(message: str) -> None:
        raise OptionError(message)

    parser.error = refuse  # type: ignore[method-assign] - no stderr print, no SystemExit
    return parser.parse_args(list(argv))


@dataclass(frozen=True)
class GoaCall:
    out_dir: str
    kwargs: dict[str, Any]  # for goa_melody.build_arrangement / write_melody


def call_of(a: argparse.Namespace) -> GoaCall:
    """The keyword arguments ``goa_melody.main`` builds from the same namespace. Raises
    ValueError for text the CLI would also fail on (``int('x')``)."""
    kw: dict[str, Any] = {
        "seed": a.seed, "bpm": a.bpm, "root": a.root, "scale": a.scale, "length": a.length,
        "arp_pattern": a.arp_pattern,
        "progression": [int(x) for x in a.progression.split(",")],
        "voices": [v for v in a.voices.split(",") if v]}
    if a.density is not None:
        kw["density"] = goa_melody._parse_voice_map(a.density, float, "density")
    if a.register is not None:
        kw["register"] = goa_melody._parse_voice_map(a.register, int, "register")
    if a.sections is not None:
        kw["sections"] = goa_melody._parse_sections(a.sections)
    return GoaCall(a.out, kw)


def build_plan_data(call: GoaCall) -> dict[str, Any]:
    """The generator's own plan dict (what the MIDI is made from)."""
    return goa_melody.build_arrangement(**call.kwargs)


# --- timeline --------------------------------------------------------------------------------

@dataclass(frozen=True)
class SectionRow:
    start_bar: int  # 1-based
    bars: int
    name: str
    energy: float
    elements: tuple[str, ...]


@dataclass(frozen=True)
class TimelinePlan:
    tempo: float
    key: str
    tracks: tuple[str, ...]
    sections: tuple[SectionRow, ...]

    @property
    def total_bars(self) -> int:
        return sum(s.bars for s in self.sections)

    @property
    def minutes(self) -> float:
        return self.total_bars * 4 * 60 / self.tempo / 60


def timeline_of(arr: dict[str, Any]) -> TimelinePlan:
    rows, pos = [], 1
    for s in arr["sections"]:
        rows.append(SectionRow(pos, s["bars"], s["name"], float(s["energy"]),
                               tuple(s["elements"])))
        pos += s["bars"]
    return TimelinePlan(
        float(arr["tempo"]), f"{arr['key']['root']} {arr['key']['scale']}",
        tuple(e["name"] for e in arr["elements"]), tuple(rows))


@dataclass(frozen=True)
class Evaluation:
    ok: bool
    problem: str  # German line, "" when ok
    plan: TimelinePlan | None = None


# --- form model ------------------------------------------------------------------------------

class GoaFormModel:
    def __init__(self) -> None:
        self.specs = option_specs()
        self._by = {s.dest: s for s in self.specs}
        self.text = {s.dest: s.default for s in self.specs}
        self.active = {s.dest for s in self.specs if not s.optional}
        self._cache: tuple[tuple[str, ...], Evaluation] | None = None

    def spec(self, dest: str) -> OptionSpec:
        return self._by[dest]

    def set_text(self, dest: str, text: str) -> None:
        self._by[dest]
        self.text[dest] = text

    def set_active(self, dest: str, on: bool) -> None:
        if not self._by[dest].optional:
            return
        spec = self._by[dest]
        if on and spec.kind == "enum" and self.text[dest] not in spec.choices:
            self.text[dest] = spec.choices[0]
        (self.active.add if on else self.active.discard)(dest)

    # Only syntax is checked here (a number is a number, a choice is a choice); ranges and
    # combinations belong to the generator and show up in evaluate().
    def field_issues(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for s in self.specs:
            if s.dest not in self.active:
                continue
            raw = self.text[s.dest].strip()
            if s.kind == "int":
                n = parse_number(raw)
                if not isinstance(n, int):
                    out[s.dest] = "Bitte eine ganze Zahl eingeben."
            elif s.kind == "float":
                if parse_number(raw) is None:
                    out[s.dest] = "Bitte eine Zahl eingeben."
            elif s.kind == "enum" and raw not in s.choices:
                out[s.dest] = f"Erlaubt: {s.range_text}."
            elif s.kind == "multi":
                parts = [p for p in raw.split(",") if p]
                if any(p not in s.choices for p in parts):
                    out[s.dest] = f"Erlaubt: {s.range_text}."
            elif s.kind == "text" and not s.optional and not raw:
                out[s.dest] = "Darf nicht leer sein."
            elif s.kind == "text" and s.optional and not raw:
                out[s.dest] = "Leer: Haken wegnehmen oder Wert eingeben."
        return out

    def argv(self, out_dir: str = "OUT") -> list[str]:
        """What the user would type after ``python -m audio_engine.goa_melody``."""
        argv = [f"--out={out_dir}"]
        for s in self.specs:
            if s.dest not in self.active:
                continue
            raw = self.text[s.dest].strip()
            if s.kind == "flag":
                if raw == "ja":
                    argv.append(s.flag)
            else:
                argv.append(f"{s.flag}={raw}")
        return argv

    def evaluate(self) -> Evaluation:
        issues = self.field_issues()
        if issues:
            first = next(iter(issues))
            return Evaluation(False, f"{self._by[first].label}: {issues[first]}")
        argv = tuple(self.argv())
        if self._cache is not None and self._cache[0] == argv:
            return self._cache[1]
        result = evaluate_argv(argv)
        self._cache = (argv, result)
        return result

    def issues(self) -> list[str]:
        ev = self.evaluate()
        return [] if ev.ok else [ev.problem]

    @property
    def is_valid(self) -> bool:
        return self.evaluate().ok

    def suggested_folder_name(self) -> str:
        seed = self.text.get("seed", "0").strip() or "0"
        bpm = self.text.get("bpm", "145").strip() or "145"
        return f"goa_melody_seed{seed}_{bpm}bpm"


def evaluate_argv(argv: tuple[str, ...]) -> Evaluation:
    """Parse with the CLI's parser and build the generator's plan; the problem text is
    German-prefixed, the generator's own sentence follows."""
    try:
        call = call_of(parse_argv(argv))
        arr = build_plan_data(call)
        return Evaluation(True, "", timeline_of(arr))
    except OptionError as exc:
        return Evaluation(False, f"Ungültige Option: {exc}")
    except (ValueError, KeyError, TypeError) as exc:
        return Evaluation(False, "Ungültige Optionen: " + " ".join(str(exc).split()))
    except Exception as exc:  # noqa: BLE001 - a result object, not a crash in the GUI
        return Evaluation(False, f"Unerwarteter Fehler: {type(exc).__name__}: {exc}")
