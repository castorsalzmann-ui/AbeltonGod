"""Kick parameter form model, built from contracts/kick-params.schema.json (no Qt).

The model holds, per contract field, the text the user typed and whether the field is sent at
all ("active"). Ranges, defaults, enums come from the contract, never from a copy. The shell
only shows this state; every check lives here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from audio_engine.params import (
    KICK_SCHEMA_FILE,
    KickParamsError,
    load_schema,
    resolve_kick_params,
    v03_properties,
)
from audio_engine.presets import describe, load_preset, preset_names

# Contract fields the form does not edit as a value: the format version is derived, the preset
# name has its own drop-down.
HIDDEN_FIELDS = ("schema_version", "preset")
ALWAYS_ACTIVE = ("seed", "variants")
V03 = "0.3"
DEFAULT_PRESET = "punchy"

LABELS_DE: dict[str, str] = {
    "seed": "Seed",
    "variants": "Varianten",
    "bpm": "Tempo",
    "sample_rate": "Samplerate",
    "bit_depth": "Bittiefe",
    "length_ms": "Länge",
    "pitch_start_hz": "Tonhöhe Start",
    "pitch_end_hz": "Tonhöhe Ende",
    "pitch_decay_ms": "Pitch-Abfall",
    "amp_attack_ms": "Anstieg",
    "amp_decay_ms": "Ausklang (-60 dB)",
    "click_level": "Klick-Pegel",
    "click_tone_hz": "Klick-Frequenz",
    "drive": "Drive",
    "tone": "Klang (dunkel/hell)",
    "peak_ceiling_dbfs": "Spitzenpegel",
    "tail_note": "Endton (MIDI-Note)",
    "length_beats": "Länge in Beats",
    "click_decay_ms": "Klick-Abfall",
    "click_q": "Klick-Güte (Q)",
    "polarity": "Polarität",
    "offset_ms": "Vorlauf",
    "clip_db": "Clip",
}
_UNIT_BY_NAME = {"bpm": "BPM", "length_beats": "Beats", "tail_note": "MIDI"}
_UNIT_BY_SUFFIX = (("_dbfs", "dBFS"), ("_db", "dB"), ("_ms", "ms"), ("_hz", "Hz"))


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    kind: str  # "int" | "float" | "enum"
    minimum: float | None
    maximum: float | None
    default: Any  # None = the contract gives no default
    choices: tuple[Any, ...]
    unit: str
    description: str  # contract text, shown as tooltip
    optional_v03: bool  # lives in the schema_version 0.3 branch

    @property
    def range_text(self) -> str:
        if self.kind == "enum":
            return " / ".join(str(c) for c in self.choices)
        unit = f" {self.unit}" if self.unit else ""
        return f"{_fmt(self.minimum)} bis {_fmt(self.maximum)}{unit}"


def _fmt(x: Any) -> str:
    return f"{x:g}" if isinstance(x, float) else str(x)


def _unit(name: str) -> str:
    if name in _UNIT_BY_NAME:
        return _UNIT_BY_NAME[name]
    for suffix, unit in _UNIT_BY_SUFFIX:
        if name.endswith(suffix):
            return unit
    return ""


def _spec(name: str, d: dict[str, Any], v03: bool) -> FieldSpec:
    if "enum" in d:
        kind, lo, hi, choices = "enum", None, None, tuple(d["enum"])
    else:
        kind = "int" if d["type"] == "integer" else "float"
        lo, hi, choices = d["minimum"], d["maximum"], ()
    return FieldSpec(
        name=name, label=LABELS_DE.get(name, name), kind=kind, minimum=lo, maximum=hi,
        default=d.get("default"), choices=choices, unit=_unit(name),
        description=str(d.get("description", "")), optional_v03=v03,
    )


def kick_field_specs() -> list[FieldSpec]:
    """Every editable contract field: the ``properties`` first, then the 0.3 branch."""
    schema = load_schema(KICK_SCHEMA_FILE)
    specs = [
        _spec(n, d, False) for n, d in schema["properties"].items() if n not in HIDDEN_FIELDS
    ]
    specs += [_spec(n, d, True) for n, d in v03_properties(schema).items()]
    return specs


_INT_RE = re.compile(r"[+-]?\d+")


def parse_number(text: str) -> int | float | None:
    """``"15"`` -> 15, ``"0,5"`` / ``"0.5"`` -> 0.5, anything else (also nan, inf) -> None.

    Integer literals stay ``int``, like the CLI's ``--set``, so the sidecar bytes match.
    """
    t = text.strip().replace(",", ".")
    if _INT_RE.fullmatch(t):
        return int(t)
    if not re.fullmatch(r"[+-]?(\d+\.\d*|\.\d+)([eE][+-]?\d+)?|[+-]?\d+[eE][+-]?\d+", t):
        return None
    return float(t)


def _text_of(value: Any) -> str:
    # repr: the shortest text that parses back to the same float (no lost digits).
    return repr(value) if isinstance(value, float) else str(value)


class FormError(ValueError):
    """``build_request`` on a form with problems."""


class KickFormModel:
    def __init__(self, preset: str = DEFAULT_PRESET) -> None:
        self.specs = kick_field_specs()
        self._by_name = {s.name: s for s in self.specs}
        self.text: dict[str, str] = {}
        self.active: set[str] = set()
        self.preset = preset
        self._preset_values: dict[str, Any] = {}
        self.set_preset(preset)

    # --- presets -----------------------------------------------------------------------
    @staticmethod
    def preset_names() -> list[str]:
        return preset_names("kick")

    def preset_description(self) -> str:
        return describe(self.preset, "kick")

    def set_preset(self, name: str) -> None:
        values = load_preset(name, "kick")  # UnknownPresetError for a made-up name
        self.preset = name
        self._preset_values = values
        self.active = {"seed", "variants"}
        for spec in self.specs:
            if spec.name in values:
                self.text[spec.name] = _text_of(values[spec.name])
                self.active.add(spec.name)
            else:
                self.text[spec.name] = self._placeholder(spec)
        self.text["variants"] = "1"

    @staticmethod
    def _placeholder(spec: FieldSpec) -> str:
        if spec.default is not None:
            return _text_of(spec.default)
        if spec.kind == "enum":
            return _text_of(spec.choices[0])
        return _text_of(spec.minimum)

    # --- editing -----------------------------------------------------------------------
    def spec(self, name: str) -> FieldSpec:
        return self._by_name[name]

    def set_text(self, name: str, text: str) -> None:
        self._by_name[name]  # KeyError for an unknown field
        self.text[name] = text

    def set_active(self, name: str, on: bool) -> None:
        if name in ALWAYS_ACTIVE:
            return
        self._by_name[name]
        (self.active.add if on else self.active.discard)(name)

    # --- checks ------------------------------------------------------------------------
    def parse(self, name: str) -> tuple[Any, str | None]:
        """``(value, None)`` or ``(None, German problem)`` for one field's text."""
        spec = self._by_name[name]
        value = parse_number(self.text.get(name, ""))
        if value is None:
            return None, "Bitte eine Zahl eingeben."
        if spec.kind == "enum":
            for c in spec.choices:
                if value == c:
                    return c, None
            return None, f"Erlaubt: {spec.range_text}."
        if spec.kind == "int" and not isinstance(value, int):
            return None, "Bitte eine ganze Zahl eingeben."
        if not (spec.minimum <= value <= spec.maximum):  # type: ignore[operator]
            return None, f"Erlaubter Bereich: {spec.range_text}."
        return value, None

    def field_issues(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for name in self.specs_names():
            if name in self.active:
                _, problem = self.parse(name)
                if problem:
                    out[name] = problem
        return out

    def specs_names(self) -> list[str]:
        return [s.name for s in self.specs]

    def cross_issue(self) -> str | None:
        """Contract rules between fields, checked by the engine's own validation.

        Skipped while a field is invalid. A ``length_beats`` request is only checked when the
        render runs (the contract's -60 dB rule needs renders).
        """
        if self.field_issues() or "length_beats" in self.active:
            return None
        try:
            resolve_kick_params(self._request_unchecked())
        except KickParamsError as exc:
            return "Ungültige Kombination: " + str(exc).replace("\n", " ")
        return None

    def issues(self) -> list[str]:
        """All problems as German lines (field problems first); empty = Render allowed."""
        lines = [f"{self._by_name[n].label}: {p}" for n, p in self.field_issues().items()]
        cross = self.cross_issue()
        if cross:
            lines.append(cross)
        return lines

    @property
    def is_valid(self) -> bool:
        return not self.issues()

    # --- request -----------------------------------------------------------------------
    def _request_unchecked(self) -> dict[str, Any]:
        req: dict[str, Any] = {}
        for name in self.specs_names():
            if name in self.active:
                req[name] = self.parse(name)[0]
        if any(self._by_name[n].optional_v03 for n in req):
            req["schema_version"] = V03
        else:
            req["schema_version"] = self._preset_values.get("schema_version", "0.2")
        req["preset"] = self.preset
        return req

    def build_request(self) -> dict[str, Any]:
        problems = self.field_issues()
        if problems:
            raise FormError("; ".join(problems.values()))
        return self._request_unchecked()

    def overrides(self) -> dict[str, Any]:
        """Fields whose value differs from the preset (or that the preset does not have).

        Seed and variants are not overrides (CLI: ``--seed``, ``--variants``). A field the
        preset has but the user switched off is not listed either.
        """
        req = self.build_request()
        skip = ("schema_version", "preset", "seed", "variants")
        return {
            k: v for k, v in req.items()
            if k not in skip and (k not in self._preset_values or self._preset_values[k] != v)
        }
