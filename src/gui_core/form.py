"""Parameter form model for every sample category, built from its contract (no Qt).

The model holds, per contract field, the text the user typed and whether the field is sent at
all ("active"). Ranges, defaults and enums come from ``contracts/<category>-params.schema.json``
(read at run time), never from a copy. Cross-field and version rules are not re-implemented:
the category's own ``resolve`` function (``audio_engine.categories``) decides. The shell only
shows this state; every check lives here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from audio_engine.categories import get_category
from audio_engine.params import CONTRACTS_DIR, load_schema
from audio_engine.presets import describe, load_preset, preset_names

CATEGORY_KEYS = ("kick", "hat", "snare", "clap", "rim", "bass", "laser", "perc", "fx")
# Contract fields the form does not edit as a value: the format version is derived, the preset
# name has its own drop-down.
HIDDEN_FIELDS = ("schema_version", "preset")
ALWAYS_ACTIVE = ("seed", "variants")
DEFAULT_PRESETS = {
    "kick": "punchy", "hat": "closed-std", "snare": "default", "clap": "default",
    "rim": "rim", "bass": "default", "laser": "blaster", "perc": "conga", "fx": "riser-8bar",
}
DEFAULT_PRESET = DEFAULT_PRESETS["kick"]
YES, NO = "ja", "nein"

LABELS_DE: dict[str, str] = {
    # shared
    "seed": "Seed", "variants": "Varianten", "bpm": "Tempo", "sample_rate": "Samplerate",
    "bit_depth": "Bittiefe", "length_ms": "Länge", "drive": "Drive", "polarity": "Polarität",
    "offset_ms": "Vorlauf", "peak_ceiling_dbfs": "Spitzenpegel", "hp_hz": "Hochpass",
    "lp_hz": "Tiefpass", "bp_hz": "Bandpass-Frequenz", "bp_q": "Bandpass-Güte (Q)",
    "gate_ms": "Gate", "click_level": "Klick-Pegel",
    # kick
    "pitch_start_hz": "Tonhöhe Start", "pitch_end_hz": "Tonhöhe Ende",
    "pitch_decay_ms": "Pitch-Abfall", "amp_attack_ms": "Anstieg",
    "amp_decay_ms": "Ausklang (-60 dB)", "click_tone_hz": "Klick-Frequenz",
    "tone": "Klang (dunkel/hell)", "tail_note": "Endton (MIDI-Note)",
    "length_beats": "Länge in Beats", "click_decay_ms": "Klick-Abfall",
    "click_q": "Klick-Güte (Q)", "clip_db": "Clip",
    # clap
    "bursts": "Anzahl Bursts", "burst_spacing_ms": "Burst-Abstand",
    "burst_decay_ms": "Burst-Abfall", "burst_level_falloff": "Burst-Pegelabfall",
    "tail_level": "Nachhall-Pegel", "tail_decay_ms": "Nachhall-Abfall", "room": "Raum",
    "room_length_ms": "Raumlänge", "fold": "Wavefolder", "crush": "Crush",
    "rate_div": "Sample-Teiler", "ring_hz": "Ringmod-Frequenz", "ring_mix": "Ringmod-Anteil",
    "comb_hz": "Kamm-Frequenz", "comb_fb": "Kamm-Rückkopplung", "tail_reverse": "Tail umkehren",
    # hat
    "model": "Modell", "decay_ms": "Abfall", "attack_ms": "Anstieg", "metal": "Metall",
    "pitch_scale": "Tonhöhen-Skala", "color": "Farbe", "bp_mix": "Bandpass-Anteil",
    "peak_hz": "Peak-Frequenz", "peak_db": "Peak-Pegel", "body_mix": "Körper-Anteil",
    "decay_hi_ratio": "Höhen-Abfall (Verhältnis)", "choke_ms": "Choke",
    # snare
    "body_hz": "Körper-Frequenz", "mode_ratio": "Obermode-Verhältnis",
    "pitch_drop": "Pitch-Absenkung", "pitch_drop_ms": "Pitch-Absenkzeit",
    "body_decay_ms": "Körper-Abfall", "body2_decay_ratio": "Körper-2-Abfallverhältnis",
    "body_level": "Körper-Pegel", "noise_decay_ms": "Rausch-Abfall",
    "noise_band_mix": "Rausch-Bandanteil", "noise_hp_hz": "Rausch-Hochpass",
    "noise_lp_hz": "Rausch-Tiefpass", "noise_attack_ms": "Rausch-Anstieg",
    "tone_peak_hz": "Klang-Peak-Frequenz", "tone_peak_db": "Klang-Peak-Pegel",
    # rim
    "f1_hz": "Frequenz 1", "f2_ratio": "Frequenz-2-Verhältnis", "level2": "Pegel 2",
    "decay1_ms": "Abfall 1", "decay2_ms": "Abfall 2", "click_ms": "Klick-Länge",
    # bass
    "note": "Note (MIDI)", "cents": "Feinstimmung", "saw_level": "Sägezahn-Pegel",
    "square_level": "Rechteck-Pegel", "sine_level": "Sinus-Pegel",
    "sub_octave_level": "Sub-Oktave-Pegel", "release_ms": "Release",
    "lp_q": "Tiefpass-Güte (Q)", "lp_env_amount": "Filter-Hüllkurve Stärke",
    "lp_env_decay_ms": "Filter-Hüllkurve Abfall",
    # laser (labels as in the blaster window, with the group in the name where it is unclear)
    "family": "Dimension", "sweep_ms": "Sweep-Zeit", "sweep_curve": "Sweep-Kurve",
    "fm_amount": "FM", "fm_ratio": "FM-Verhältnis", "ring_amount": "Ring-Anteil",
    "noise_level": "Rauschen", "noise_hz": "Rausch-Frequenz", "crackle": "Knistern",
    "glitch_steps": "Glitch-Stufen", "stereo_width": "Breite", "variation": "Variation",
    "echo_mix": "Echo-Anteil", "echo_ms": "Echo-Zeit", "echo_feedback": "Echo-Rückkopplung",
    "echo_sync": "Echo-Notenwert", "echo_damp_hz": "Echo-Dämpfung",
    "echo_pingpong": "Echo Ping-Pong",
    "salvo_count": "Schüsse", "salvo_rate_mode": "Takt-Art", "salvo_spacing_ms": "Abstand",
    "salvo_rate_hz": "Feuerrate", "salvo_sync_note": "Notenwert", "salvo_rate_ramp": "Rampe",
    "salvo_pan_mode": "Pan-Muster", "salvo_pan_width": "Pan-Breite",
    "salvo_level_step_db": "Pegel-Schritt", "salvo_pitch_step_st": "Ton-Schritt",
    "salvo_humanize": "Humanize",
    "filter_slope": "Filter-Flanke", "lp_resonance": "Tiefpass-Resonanz",
    "lp_sweep_ms": "Tiefpass-Sweep-Zeit", "lp_sweep_hz": "Tiefpass-Sweep-Ziel",
    "reverb_mix": "Hall-Anteil", "reverb_size": "Hall-Größe", "reverb_decay_ms": "Nachhall",
    "reverb_damp_hz": "Hall-Dämpfung", "reverb_predelay_ms": "Hall-Vorverzögerung",
    "reverb_width": "Hall-Breite",
    # perc (#475)
    "tune_semitones": "Stimmung", "decay_scale": "Abfall-Faktor",
    "attack_scale": "Anstiegs-Faktor", "bend_ratio": "Glide-Verhältnis", "bend_ms": "Glide-Zeit",
    "tick_level": "Tick-Pegel", "tick_hz": "Tick-Frequenz",
    # fx (#482)
    "kind": "Art", "tail_beats": "Ausklang nach dem Ziel", "cut_beats": "Pause vor dem Ziel",
    "pump_depth": "Pump-Tiefe", "noise_color": "Rauschfarbe", "filter_mode": "Filter-Art",
    "cutoff_start_hz": "Filter Start", "cutoff_end_hz": "Filter Ende",
    "lp_ratio": "Tiefpass-Verhältnis", "filter_q": "Filter-Güte (Q)",
    "level_start_db": "Pegel Start", "level_end_db": "Pegel Ende", "level_curve": "Pegel-Kurve",
    "ramp_beats": "Pegel-Rampe", "tone_level": "Ton-Pegel", "tone_wave": "Ton-Wellenform",
    "tone_start_hz": "Ton Start", "tone_end_hz": "Ton Ende", "tone_glide_beats": "Ton-Glide",
    "tone_decay_beats": "Ton-Abfall", "echo_note": "Echo-Notenwert",
}
_UNIT_BY_NAME = {"bpm": "BPM", "length_beats": "Beats", "tail_beats": "Beats",
                 "cut_beats": "Beats", "ramp_beats": "Beats", "tone_glide_beats": "Beats",
                 "tone_decay_beats": "Beats", "tail_note": "MIDI", "note": "MIDI",
                 "cents": "Cent", "bursts": "", "rate_div": "", "salvo_pitch_step_st": "st",
                 "salvo_count": "", "glitch_steps": "", "tune_semitones": "st"}
_UNIT_BY_SUFFIX = (("_dbfs", "dBFS"), ("_db", "dB"), ("_ms", "ms"), ("_hz", "Hz"))


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    kind: str  # "int" | "float" | "enum" | "bool"
    minimum: float | None
    maximum: float | None
    default: Any  # None = the contract gives no default
    choices: tuple[Any, ...]
    unit: str
    description: str  # contract text, shown as tooltip
    gate_version: str | None = None  # lives in the branch of this schema_version
    zero_ok: bool = False  # 0 = "off" besides the range (hat choke_ms, clap gate_ms)
    step: float | None = None  # contract ``multipleOf`` (fx lengths: 0.25 beat, #482)

    @property
    def optional_v03(self) -> bool:  # kept for the first GUI's name
        return self.gate_version is not None

    @property
    def choice_texts(self) -> tuple[str, ...]:
        if self.kind == "bool":
            return (NO, YES)
        return tuple(str(c) for c in self.choices)

    @property
    def range_text(self) -> str:
        if self.kind in ("enum", "bool"):
            return " / ".join(self.choice_texts)
        unit = f" {self.unit}" if self.unit else ""
        text = f"{_fmt(self.minimum)} bis {_fmt(self.maximum)}{unit}"
        return f"0 (aus) oder {text}" if self.zero_ok else text


def _fmt(x: Any) -> str:
    return f"{x:g}" if isinstance(x, float) else str(x)


def _unit(name: str) -> str:
    if name in _UNIT_BY_NAME:
        return _UNIT_BY_NAME[name]
    for suffix, unit in _UNIT_BY_SUFFIX:
        if name.endswith(suffix):
            return unit
    return ""


def _spec(name: str, d: dict[str, Any], gate: str | None) -> FieldSpec:
    zero_ok = False
    if "oneOf" in d or "anyOf" in d:  # "0 = off, otherwise a range" (const 0 + number branch)
        branches = d.get("oneOf") or d["anyOf"]
        number = next(b for b in branches if b.get("type") == "number")
        zero_ok = any(b.get("const") == 0 for b in branches)
        d = {**d, **number}
    if "enum" in d:
        kind, lo, hi, choices = "enum", None, None, tuple(d["enum"])
    elif d.get("type") == "boolean":
        kind, lo, hi, choices = "bool", None, None, (False, True)
    else:
        kind = "int" if d["type"] == "integer" else "float"
        lo, hi, choices = d["minimum"], d["maximum"], ()
    return FieldSpec(
        name=name, label=LABELS_DE.get(name, name), kind=kind, minimum=lo, maximum=hi,
        default=d.get("default"), choices=choices, unit=_unit(name),
        description=str(d.get("description", "")), gate_version=gate, zero_ok=zero_ok,
        step=d.get("multipleOf"),
    )


def schema_path(category: str):
    """The params contract of a GUI category, or of a contract category without a GUI page yet
    (fx, #492): any ``contracts/<category>-params.schema.json`` that exists."""
    path = CONTRACTS_DIR / f"{category}-params.schema.json"
    if category not in CATEGORY_KEYS and not (category.isidentifier() and path.is_file()):
        raise KeyError(f"unknown category {category!r}")
    return path


# --- defaults that depend on other fields (#492) ----------------------------------------------

@dataclass(frozen=True)
class SelectorBranch:
    """``if <field> == const then properties`` in the contract's ``allOf`` (an enum selector such
    as fx ``kind``; ``schema_version`` branches are the version gates above, not selectors)."""

    field: str
    const: Any
    when_absent: bool  # the branch also applies when the field is not sent (no ``required``)
    properties: dict[str, Any]


def selector_branches(schema: dict[str, Any]) -> list[SelectorBranch]:
    out: list[SelectorBranch] = []
    for branch in schema.get("allOf", ()):
        cond = branch.get("if", {})
        props = cond.get("properties", {})
        then = branch.get("then", {}).get("properties")
        if len(props) != 1 or not then:
            continue
        (field, rule), = props.items()
        if field == "schema_version" or "const" not in rule:
            continue
        out.append(SelectorBranch(field, rule["const"], field not in cond.get("required", ()),
                                  then))
    return out


_DERIVED = re.compile(r"Omitted = ([a-z_][a-z_0-9]*) \(derived default\)")


def derived_defaults(schema: dict[str, Any]) -> dict[str, str]:
    """``{field: source}`` for fields whose contract text says "Omitted = <source> (derived
    default)" (fx ``ramp_beats`` -> ``length_beats``). A branch default wins over this."""
    out: dict[str, str] = {}
    for name, d in schema.get("properties", {}).items():
        m = _DERIVED.search(str(d.get("description", "")))
        if m and m.group(1) in schema["properties"] and m.group(1) != name:
            out[name] = m.group(1)
    return out


def resolve_defaults(schema: dict[str, Any], sent: dict[str, Any]) -> dict[str, Any]:
    """The default the engine would use for every field not in ``sent``, read from the contract:
    the matching selector branch's ``default``, else the derived source's value, else the
    top-level ``default``. ``sent``: the values the form sends."""
    props = schema.get("properties", {})
    out = {n: d["default"] for n, d in props.items() if "default" in d and n not in sent}
    for b in selector_branches(schema):
        value = sent.get(b.field)
        # JSON Schema: an absent field makes ``if`` true unless the branch requires it
        if value == b.const or (value is None and b.when_absent):
            for n, d in b.properties.items():
                if "default" in d and n not in sent:
                    out[n] = d["default"]
    for name, source in derived_defaults(schema).items():
        if name in sent or name in out:
            continue
        value = sent.get(source, out.get(source))
        if value is not None:
            out[name] = value
    return out


def field_specs(category: str) -> list[FieldSpec]:
    """Every editable contract field: ``properties`` first, then each schema_version branch."""
    schema = load_schema(schema_path(category))
    specs = [
        _spec(n, d, None) for n, d in schema["properties"].items() if n not in HIDDEN_FIELDS
    ]
    own = {s.name for s in specs}
    for gate, props in gated_branches(schema).items():
        # A branch that only narrows a field the base already has (laser 0.1: length_ms up to
        # 3000) is a rule for the engine's resolve, not a second field.
        specs += [_spec(n, d, gate) for n, d in props.items() if n not in own]
    return specs


def gated_branches(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """``{schema_version: properties}`` for each ``if schema_version == X then properties``."""
    out: dict[str, dict[str, Any]] = {}
    for branch in schema.get("allOf", ()):
        const = (
            branch.get("if", {}).get("properties", {}).get("schema_version", {}).get("const")
        )
        if const is not None and "properties" in branch.get("then", {}):
            out[const] = branch["then"]["properties"]
    return out


def kick_field_specs() -> list[FieldSpec]:
    return field_specs("kick")


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


def _text_of(spec: FieldSpec | None, value: Any) -> str:
    if isinstance(value, bool):
        return YES if value else NO
    # repr: the shortest text that parses back to the same float (no lost digits).
    return repr(value) if isinstance(value, float) else str(value)


class FormError(ValueError):
    """``build_request`` on a form with problems."""


class CategoryFormModel:
    def __init__(self, category: str = "kick", preset: str | None = None) -> None:
        self.category = category
        self.specs = field_specs(category)
        self._by_name = {s.name: s for s in self.specs}
        self.text: dict[str, str] = {}
        self.active: set[str] = set()
        self._schema = load_schema(schema_path(category))
        # Always sent: seed, variants and every field the contract requires (fx: bpm, #482).
        required = set(self._schema.get("required", ())) & set(self._by_name)
        self.locked: frozenset[str] = frozenset(ALWAYS_ACTIVE) | frozenset(required)
        self._versions = list(self._schema["properties"]["schema_version"].get("enum", []))
        self.preset = ""
        self._preset_values: dict[str, Any] = {}
        # Defaults that follow other fields (#492): only a contract with selector branches or
        # derived defaults has any; for the others every default is the top-level one.
        self._dynamic = bool(selector_branches(self._schema) or derived_defaults(self._schema))
        self._defaults: dict[str, Any] = {}
        if preset is None and category not in DEFAULT_PRESETS:
            self._start_without_preset()  # a contract category without presets yet (fx)
        else:
            self.set_preset(preset or DEFAULT_PRESETS[category])

    @classmethod
    def without_preset(cls, category: str) -> CategoryFormModel:
        """A form at the contract's own defaults (no preset values, no preset name sent)."""
        m = cls(category)
        m.preset = ""
        m._preset_values = {}
        m.text = {}
        m._start_without_preset()
        return m

    def _start_without_preset(self) -> None:
        self.active = set(self.locked)
        self._defaults = self._resolved_defaults()
        for spec in self.specs:
            self.text[spec.name] = self._placeholder(spec)
        if "variants" in self._by_name:
            self.text["variants"] = "1"

    # --- presets -----------------------------------------------------------------------
    def preset_names(self) -> list[str]:
        return preset_names(self.category)

    def preset_description(self) -> str:
        """German text for the GUI (#467); the preset file's English text as fallback."""
        from .preset_texts import preset_text_de

        return preset_text_de(self.category, self.preset, describe(self.preset, self.category))

    def set_preset(self, name: str) -> None:
        values = load_preset(name, self.category)  # UnknownPresetError for a made-up name
        self.preset = name
        self._preset_values = values
        self.active = set(self.locked)
        for spec in self.specs:
            if spec.name in values:
                self.text[spec.name] = _text_of(spec, values[spec.name])
                self.active.add(spec.name)
        self._defaults = self._resolved_defaults()
        for spec in self.specs:
            if spec.name not in values:
                self.text[spec.name] = self._placeholder(spec)
        self.text["variants"] = "1"

    # --- defaults ----------------------------------------------------------------------
    def _sent_values(self) -> dict[str, Any]:
        out = {}
        for n in self.active:
            value, problem = self.parse(n)
            if problem is None:
                out[n] = value
        return out

    def _resolved_defaults(self) -> dict[str, Any]:
        if not self._dynamic:
            return {}
        return resolve_defaults(self._schema, self._sent_values())

    def default_of(self, name: str) -> Any:
        """The value the engine uses for ``name`` when it is not sent, as far as the contract
        says (selector branch, derived default, top-level default); ``None`` if it says none."""
        if self._dynamic:
            return self._defaults.get(name, self._by_name[name].default)
        return self._by_name[name].default

    def _refresh_defaults(self) -> None:
        """After an edit: fields that are not sent and still show their old default get the new
        one (a kind change). A field whose default did not change keeps its text."""
        if not self._dynamic:
            return
        old, self._defaults = self._defaults, self._resolved_defaults()
        for spec in self.specs:
            n = spec.name
            if n in self.active or old.get(n) == self._defaults.get(n):
                continue
            if self.text.get(n) == self._placeholder_for(spec, old.get(n, spec.default)):
                self.text[n] = self._placeholder(spec)

    def _placeholder(self, spec: FieldSpec) -> str:
        return self._placeholder_for(spec, self.default_of(spec.name))

    @staticmethod
    def _placeholder_for(spec: FieldSpec, default: Any) -> str:
        if default is not None:
            return _text_of(spec, default)
        if spec.kind in ("enum", "bool"):
            return spec.choice_texts[0]
        return _text_of(spec, spec.minimum)

    # --- editing -----------------------------------------------------------------------
    def spec(self, name: str) -> FieldSpec:
        return self._by_name[name]

    def set_text(self, name: str, text: str) -> None:
        self._by_name[name]  # KeyError for an unknown field
        self.text[name] = text
        self._refresh_defaults()

    def reset_field(self, name: str) -> None:
        """Back to the preset: its value (and sent) if the preset has the field, else off."""
        spec = self._by_name[name]
        if name in self._preset_values:
            self.text[name] = _text_of(spec, self._preset_values[name])
            self.active.add(name)
        elif name not in self.locked:
            self.active.discard(name)
            self._refresh_defaults()
            self.text[name] = self._placeholder(spec)
            return
        self._refresh_defaults()

    def set_active(self, name: str, on: bool) -> None:
        if name in self.locked:
            return
        self._by_name[name]
        (self.active.add if on else self.active.discard)(name)
        self._refresh_defaults()

    # --- checks ------------------------------------------------------------------------
    def parse(self, name: str) -> tuple[Any, str | None]:
        """``(value, None)`` or ``(None, German problem)`` for one field's text."""
        spec = self._by_name[name]
        raw = self.text.get(name, "").strip()
        if spec.kind == "bool":
            if raw in (YES, NO):
                return raw == YES, None
            return None, f"Erlaubt: {spec.range_text}."
        if spec.kind == "enum":
            for c, t in zip(spec.choices, spec.choice_texts, strict=True):
                if raw == t:
                    return c, None
            number = parse_number(raw)
            if number is not None:
                for c in spec.choices:
                    if not isinstance(c, str) and number == c:
                        return c, None
            return None, f"Erlaubt: {spec.range_text}."
        value = parse_number(raw)
        if value is None:
            return None, "Bitte eine Zahl eingeben."
        if spec.kind == "int" and not isinstance(value, int):
            return None, "Bitte eine ganze Zahl eingeben."
        if spec.zero_ok and value == 0:
            return value, None
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
        """Contract rules between fields, checked by the category's own resolve function.

        Skipped while a field is invalid. A kick ``length_beats`` request is only checked when
        the render runs (the contract's -60 dB rule needs renders).
        """
        if self.field_issues() or "length_beats" in self.active:
            return None
        try:
            get_category(self.category).resolve(self._request_unchecked())
        except ValueError as exc:
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
        return self._assemble(req)

    def probe_request(self, name: str, value: Any) -> dict[str, Any]:
        """The request as it would be with ``name`` active and set to ``value``.

        Used by the link rules to ask the engine's own ``resolve`` whether a value is allowed.
        Fields whose text is invalid are left out; ``length_beats`` is left out too (its rule
        renders the kick, too slow to ask on every slider step).
        """
        return self.probe_request_from(self.probe_base(), name, value)

    def probe_base(self) -> dict[str, Any]:
        """The valid active fields (without ``length_beats``) in field order: what every probe
        request of the current state shares. Parse once, probe many times."""
        req: dict[str, Any] = {}
        for n in self.specs_names():
            if n in self.active and n != "length_beats":
                value_n, problem = self.parse(n)
                if problem is None:
                    req[n] = value_n
        return req

    def probe_request_from(self, base: dict[str, Any], name: str, value: Any) -> dict[str, Any]:
        """``probe_request`` on a ``probe_base`` taken from the current state."""
        req = dict(base)
        req[name] = value
        return self._assemble(req)

    def base_request(self, base: dict[str, Any]) -> dict[str, Any]:
        """The request of ``probe_base`` itself (no field changed)."""
        return self._assemble(dict(base))

    def _assemble(self, req: dict[str, Any]) -> dict[str, Any]:
        gates = [self._by_name[n].gate_version for n in req if self._by_name[n].gate_version]
        if gates:
            req["schema_version"] = gates[0]
        else:
            fallback = self._versions[0] if self._versions else "0.1"
            req["schema_version"] = self._preset_values.get("schema_version", fallback)
        if self.preset:  # a contract category without presets yet (fx) sends none
            req["preset"] = self.preset
        # Key order as the CLI builds it (preset file order, new fields, variants last), so the
        # sidecar's "parameters" object is byte-identical too.
        ordered = {k: req.pop(k) for k in list(self._preset_values) if k in req and k != "variants"}
        variants = req.pop("variants")
        ordered.update(req)
        ordered["variants"] = variants
        return ordered

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


class KickFormModel(CategoryFormModel):
    def __init__(self, preset: str = DEFAULT_PRESET) -> None:
        super().__init__("kick", preset)

    @staticmethod
    def preset_names() -> list[str]:  # type: ignore[override]
        return preset_names("kick")
