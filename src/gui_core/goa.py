"""Goa clip form model, option translation and clip summary (no Qt).

D-035 (1): the Goa page and window make short MIDI clips, one per voice (lead, arp, pad,
pluck), like the Acid line. The generator is ``python -m audio_engine.goa_clips``; there are
no sections, no energy curve and no song length (song form belongs to the arrangement
planner, D-033). ``audio_engine.goa_arrangement`` is not imported here.

This module does not copy the generator's rules:

* The option list (names, choices, defaults) is read from the CLI's own ``build_parser()``;
  a test enumerates every parser option and fails when the form misses one.
* The form turns its state into the same ``--flag=value`` list a user would type, and the CLI's
  parser reads it back (:func:`parse_argv`), so choices and types are checked by the CLI itself.
* The namespace becomes keyword arguments with the CLI's own ``params_from_args``
  (:func:`call_of`; a test compares the written bytes against the real ``main``).
* Ranges and combinations are decided by ``goa_clips`` (ValueError text is shown as is); the
  clip summary (notes per voice, chord per bar, file names) comes from its functions.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

from audio_engine import goa_clips, goa_melody

from .form import parse_number

TITLE = "Goa-Melodie"  # same as the main window's page name (main_window.TOOL_PAGES)

SKIPPED_DESTS = ("help", "out")  # --out is the folder row of the page

LABELS_DE: dict[str, str] = {
    "seed": "Seed", "bars": "Clip-Länge (Takte)", "bpm": "Tempo", "root": "Grundton",
    "scale": "Tonleiter", "voices": "Stimmen", "density": "Dichte",
    "register": "Register (Oktaven)", "arp_pattern": "Arp-Muster",
    "progression": "Akkordfolge (Stufen)",
}
UNITS = {"bpm": "BPM", "bars": "Takte"}
GROUP_OF: dict[str, str] = {}
for _d in ("bars", "bpm", "root", "scale", "seed"):
    GROUP_OF[_d] = "Clip"
for _d in ("voices", "density", "register", "arp_pattern", "progression"):
    GROUP_OF[_d] = "Stimmen"
GROUPS = ("Clip", "Stimmen")
INT_DESTS = ("bpm",)  # whole BPM in the GUI (the CLI takes a float; 145 -> "145bpm")

# Hints for free-text fields (the module decides what is valid).
HINTS = {
    "density": "0 bis 1, oder je Stimme: lead=0.5,arp=1",
    "register": "-2 bis 2, oder je Stimme: lead=1,pad=-1",
    "progression": "Stufen 0 bis 6, durch Komma getrennt, z. B. 0,5,6,4",
    "root": "A bis G, optional mit # oder b",
    "bars": f"{goa_clips.MIN_BARS} bis {goa_clips.MAX_BARS} Takte",
}
MULTI_VOICES = {"voices": tuple(goa_clips.VOICES)}
VOICE_LABELS = {"lead": "Lead", "arp": "Arp", "pad": "Pad", "pluck": "Pluck"}


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
    elif action.type is int or dest in INT_DESTS:
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
        group=GROUP_OF.get(dest, "Clip"), unit=UNITS.get(dest, ""),
    )


def _default_text(value: Any) -> str:
    if isinstance(value, bool):
        return "nein" if not value else "ja"
    return f"{value:g}" if isinstance(value, float) else str(value)


def parser_of() -> argparse.ArgumentParser:
    return goa_clips.build_parser()


def option_specs() -> list[OptionSpec]:
    """One spec per CLI option (except ``--out``), in the order of :data:`GROUPS`."""
    specs = [_spec(a) for a in parser_of()._actions if a.dest not in SKIPPED_DESTS]
    return sorted(specs, key=lambda s: GROUPS.index(s.group))


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
    kwargs: dict[str, Any]  # for goa_clips.write_clips / gui_core.goa_preview


def call_of(a: argparse.Namespace) -> GoaCall:
    """The keyword arguments ``goa_clips.main`` builds from the same namespace. Raises
    ValueError for text the CLI would also fail on (``int('x')``)."""
    return GoaCall(a.out, goa_clips.params_from_args(a))


# --- clip summary ----------------------------------------------------------------------------

@dataclass(frozen=True)
class VoiceClip:
    voice: str
    notes: int
    file_name: str


@dataclass(frozen=True)
class ClipPlan:
    bars: int
    tempo: float
    key: str
    chords: tuple[int, ...]  # scale degree per bar (arp and pad)
    clips: tuple[VoiceClip, ...]  # selected voices, fixed order

    @property
    def seconds(self) -> float:
        return self.bars * 4 * 60 / self.tempo


def clip_plan(kwargs: dict[str, Any]) -> ClipPlan:
    o = goa_clips.normalise(kwargs)
    clips = tuple(VoiceClip(v, len(goa_clips.clip_notes(v, **kwargs)),
                            goa_clips.clip_filename(v, **kwargs)) for v in o["voices"])
    chords = tuple(o["progression"][s] for s in goa_clips.bar_chords(o))
    return ClipPlan(o["bars"], o["bpm"], f"{o['root']} {o['scale']}", chords, clips)


@dataclass(frozen=True)
class Evaluation:
    ok: bool
    problem: str  # German line, "" when ok
    plan: ClipPlan | None = None
    kwargs: dict[str, Any] | None = None  # the generator's options when ok


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
        """What the user would type after ``python -m audio_engine.goa_clips``."""
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
        bars = self.text.get("bars", str(goa_clips.DEFAULT_BARS)).strip() or "4"
        return f"goa_clips_seed{seed}_{bpm}bpm_{bars}bars"


def evaluate_argv(argv: tuple[str, ...]) -> Evaluation:
    """Parse with the CLI's parser and summarise the clips; the problem text is
    German-prefixed, the generator's own sentence follows."""
    try:
        call = call_of(parse_argv(argv))
        plan = clip_plan(call.kwargs)
        return Evaluation(True, "", plan, call.kwargs)
    except OptionError as exc:
        return Evaluation(False, f"Ungültige Option: {exc}")
    except (ValueError, KeyError, TypeError) as exc:
        return Evaluation(False, "Ungültige Optionen: " + " ".join(str(exc).split()))
    except Exception as exc:  # noqa: BLE001 - a result object, not a crash in the GUI
        return Evaluation(False, f"Unerwarteter Fehler: {type(exc).__name__}: {exc}")
