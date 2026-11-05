"""Goa form model, option translation and timeline plan (no Qt).

The two Goa generators are ``python -m audio_engine.goa_arrangement`` and
``python -m audio_engine.goa_melody``. This module does not copy their rules:

* The option list (names, choices, defaults) is read from the CLIs' own ``build_parser()``;
  a test enumerates every parser option and fails when the form misses one.
* The form turns its state into the same ``--flag=value`` list a user would type, and the CLI's
  parser reads it back (:func:`parse_argv`), so choices and types are checked by the CLI itself.
* The namespace becomes keyword arguments exactly as each module's ``main`` does it
  (:func:`call_of`; a test compares the written bytes against the real ``main``).
* Ranges and combinations are decided by the modules' ``build_arrangement`` (ValueError text
  is shown as is); the timeline is drawn from the ``sections`` of its result.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

from audio_engine import goa_arrangement, goa_melody, goa_patterns, goa_rhythm
from audio_engine.presets import preset_names

from .form import parse_number

ARRANGEMENT, MELODY = "arrangement", "melody"
MODES = (ARRANGEMENT, MELODY)
MODE_LABELS = {ARRANGEMENT: "Arrangement (ganzer Track)", MELODY: "Melodie (lead/arp/pad/pluck)"}

SKIPPED_DESTS = ("help", "out")  # --out is the folder row of the page

LABELS_DE: dict[str, str] = {
    "seed": "Seed", "bpm": "Tempo", "root": "Grundton", "scale": "Tonleiter",
    "roll": "Bass-Rhythmus (Roll)", "intro_bars": "Intro ohne Kick", "breakdowns": "Breakdowns",
    "outro": "Outro", "outro_bars": "Outro-Länge", "dj_bars": "DJ-Intro/Outro",
    "kick_preset": "Kick-Preset", "bass_preset": "Bass-Preset", "hat_preset": "Hi-Hat-Preset",
    "snare_preset": "Snare-Preset", "snare_pattern": "Snare-Muster",
    "clap_preset": "Clap-Preset", "clap_pattern": "Clap-Muster",
    "rim_preset": "Rim-Preset", "rim_pattern": "Rim-Muster",
    "melody_voices": "Melodie-Stimmen", "voices": "Melodie-Stimmen", "density": "Dichte",
    "register": "Register (Oktaven)", "arp_pattern": "Arp-Muster",
    "progression": "Akkordfolge (Stufen)", "no_samples": "Keine Samples rendern",
    "length": "Phrasenlänge (Takte)", "sections": "Abschnitte",
}
UNITS = {"bpm": "BPM", "intro_bars": "Takte", "outro_bars": "Takte", "dj_bars": "Takte",
         "length": "Takte"}
GROUP_OF: dict[str, str] = {}
for _d in ("seed", "bpm", "root", "scale"):
    GROUP_OF[_d] = "Grundlagen"
for _d in ("roll", "intro_bars", "breakdowns", "outro", "outro_bars", "dj_bars", "length",
           "sections"):
    GROUP_OF[_d] = "Form"
for _d in ("kick_preset", "bass_preset", "hat_preset", "snare_preset", "snare_pattern",
           "clap_preset", "clap_pattern", "rim_preset", "rim_pattern"):
    GROUP_OF[_d] = "Rhythmus-Stimmen"
for _d in ("melody_voices", "voices", "density", "register", "arp_pattern", "progression"):
    GROUP_OF[_d] = "Melodie"
GROUP_OF["no_samples"] = "Dateien"
GROUPS = ("Grundlagen", "Form", "Rhythmus-Stimmen", "Melodie", "Dateien")

# Hints for free-text fields (the module decides what is valid).
HINTS = {
    "density": "0 bis 1, oder je Stimme: lead=0.5,arp=1",
    "register": "-2 bis 2, oder je Stimme: lead=1,pad=-1",
    "progression": "Stufen 0 bis 6, durch Komma getrennt, z. B. 0,5,6,4",
    "sections": "Name:Takte:Energie:stimme+stimme, durch Komma getrennt",
    "root": "A bis G, optional mit # oder b",
}
PRESET_CATEGORY = {"kick_preset": "kick", "bass_preset": "bass", "hat_preset": "hat",
                   "snare_preset": "snare", "clap_preset": "clap", "rim_preset": "rim"}
PERC_PRESETS = ("snare_preset", "clap_preset", "rim_preset")  # these accept 'none' (voice off)
MULTI_VOICES = {"melody_voices": goa_arrangement.MELODIC, "voices": tuple(goa_melody.VOICES)}


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
            return f"{goa_patterns.MIN_BPM:g} bis {goa_patterns.MAX_BPM:g} BPM"
        return self.unit or ("ganze Zahl" if self.kind == "int" else "Zahl")


def _choice_texts(dest: str, action: argparse.Action) -> tuple[str, ...]:
    if dest in PRESET_CATEGORY:
        names = tuple(preset_names(PRESET_CATEGORY[dest]))
        return (*names, goa_rhythm.NONE) if dest in PERC_PRESETS else names
    if dest == "dj_bars":
        return tuple(str(c) for c in goa_arrangement.DJ_BARS_CHOICES)
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


def parser_of(mode: str) -> argparse.ArgumentParser:
    if mode == ARRANGEMENT:
        return goa_arrangement.build_parser()
    if mode == MELODY:
        return goa_melody.build_parser()
    raise KeyError(f"unknown Goa mode {mode!r}")


def option_specs(mode: str) -> list[OptionSpec]:
    """One spec per CLI option (except ``--out``), in the parser's order."""
    return [_spec(a) for a in parser_of(mode)._actions if a.dest not in SKIPPED_DESTS]


# --- argv <-> namespace -> call --------------------------------------------------------------

class OptionError(ValueError):
    """The CLI's own parser refused the options (message is the parser's)."""


def parse_argv(mode: str, argv: list[str] | tuple[str, ...]) -> argparse.Namespace:
    parser = parser_of(mode)

    def refuse(message: str) -> None:
        raise OptionError(message)

    parser.error = refuse  # type: ignore[method-assign] - no stderr print, no SystemExit
    return parser.parse_args(list(argv))


@dataclass(frozen=True)
class GoaCall:
    mode: str
    out_dir: str
    kwargs: dict[str, Any]  # for build_arrangement / write_track / write_melody
    render_samples: bool = True


def call_of(mode: str, a: argparse.Namespace) -> GoaCall:
    """The keyword arguments the module's ``main`` builds from the same namespace. Raises
    ValueError for text the CLI would also fail on (``int('x')``)."""
    if mode == ARRANGEMENT:
        kw: dict[str, Any] = {
            "melody_voices": [v for v in a.melody_voices.split(",") if v],
            "arp_pattern": a.arp_pattern}
        if a.density is not None:
            kw["density"] = goa_melody._parse_voice_map(a.density, float, "density")
        if a.register is not None:
            kw["register"] = goa_melody._parse_voice_map(a.register, int, "register")
        if a.progression is not None:
            kw["progression"] = [int(x) for x in a.progression.split(",")]
        kw.update(
            seed=a.seed, bpm=a.bpm, root=a.root, scale=a.scale, roll=a.roll,
            dj_bars=a.dj_bars, intro_bars=a.intro_bars, breakdowns=a.breakdowns,
            outro=a.outro, outro_bars=a.outro_bars, kick_preset=a.kick_preset,
            bass_preset=a.bass_preset, hat_preset=a.hat_preset, snare_preset=a.snare_preset,
            clap_preset=a.clap_preset, rim_preset=a.rim_preset,
            snare_pattern=a.snare_pattern, clap_pattern=a.clap_pattern,
            rim_pattern=a.rim_pattern)
        return GoaCall(mode, a.out, kw, render_samples=not a.no_samples)
    kw = {
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
    return GoaCall(mode, a.out, kw)


def build_plan_data(call: GoaCall) -> dict[str, Any]:
    """The generator's own arrangement dict (what the MIDI is made from)."""
    if call.mode == ARRANGEMENT:
        return goa_arrangement.build_arrangement(**call.kwargs)
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
    def __init__(self, mode: str = ARRANGEMENT) -> None:
        self.mode = mode
        self.specs = option_specs(mode)
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
        """What the user would type after ``python -m audio_engine.goa_<mode>``."""
        argv = [f"--out={out_dir}"]
        for s in self.specs:
            if s.dest not in self.active:
                continue
            raw = self.text[s.dest].strip()
            if s.kind == "flag":
                if raw == "ja":
                    argv.append(s.flag)
            elif s.dest == "dj_bars":
                argv.append(f"{s.flag}={raw}")
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
        result = evaluate_argv(self.mode, argv)
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
        prefix = "goa" if self.mode == ARRANGEMENT else "goa_melody"
        return f"{prefix}_seed{seed}_{bpm}bpm"


def evaluate_argv(mode: str, argv: tuple[str, ...]) -> Evaluation:
    """Parse with the CLI's parser and build the generator's plan; the problem text is
    German-prefixed, the generator's own sentence follows."""
    try:
        call = call_of(mode, parse_argv(mode, argv))
        arr = build_plan_data(call)
        return Evaluation(True, "", timeline_of(arr))
    except OptionError as exc:
        return Evaluation(False, f"Ungültige Option: {exc}")
    except (ValueError, KeyError, TypeError) as exc:
        return Evaluation(False, "Ungültige Optionen: " + " ".join(str(exc).split()))
    except Exception as exc:  # noqa: BLE001 - a result object, not a crash in the GUI
        return Evaluation(False, f"Unerwarteter Fehler: {type(exc).__name__}: {exc}")
