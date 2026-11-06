"""Blaster v2 parameter model (no Qt): contract fields, groups, undo, A/B, randomise, presets,
job queue and the preview profile.

Everything numeric comes from ``contracts/laser-params.schema.json`` (read at run time through
``form._spec``): ranges, defaults, enums. The only things written here are German labels,
which control belongs to which group and which are "Hauptregler" (a GUI decision, no contract
content). A request is checked by the engine's own ``resolve_laser_params``; nothing is
clamped on the way to the engine. Values typed or dragged in the window are limited to the
contract range by the widgets (they show a note), the model rejects anything outside it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np

from audio_engine.laser import SYNC_DEFAULT_BPM, LaserParamsError, resolve_laser_params
from audio_engine.params import CONTRACTS_DIR, load_schema
from audio_engine.presets import describe, load_preset, preset_names

from .form import FieldSpec, _spec, gated_branches
from .valuemap import map_of

LASER_SCHEMA = CONTRACTS_DIR / "laser-params.schema.json"
SCHEMA_VERSION = "0.2"
SEED_MAX = 4_294_967_295
BPM_DEFAULT = SYNC_DEFAULT_BPM  # contract point 15: "absent = 120 in the resolved form"
MAX_FILE_BYTES = 1_000_000


class BlasterError(Exception):
    """A user-facing problem; the message is German."""


# ---- labels (German) and units ----------------------------------------------------------------
LABELS: dict[str, str] = {
    "family": "Dimension", "length_ms": "Länge", "pitch_start_hz": "Start-Ton",
    "pitch_end_hz": "End-Ton", "sweep_ms": "Sweep-Zeit", "sweep_curve": "Sweep-Kurve",
    "attack_ms": "Anstieg", "decay_ms": "Zerfall", "fm_amount": "FM", "fm_ratio": "FM-Verhältnis",
    "ring_amount": "Ring", "ring_hz": "Ring-Frequenz", "noise_level": "Rauschen",
    "noise_hz": "Rausch-Frequenz", "crackle": "Knistern", "glitch_steps": "Glitch-Stufen",
    "stereo_width": "Breite", "variation": "Variation", "drive": "Drive",
    "polarity": "Polarität", "offset_ms": "Vorlauf", "peak_ceiling_dbfs": "Spitzenpegel",
    "salvo_count": "Schüsse", "salvo_rate_mode": "Takt-Art", "salvo_spacing_ms": "Abstand",
    "salvo_rate_hz": "Feuerrate", "salvo_sync_note": "Notenwert", "salvo_rate_ramp": "Rampe",
    "salvo_pan_mode": "Pan-Muster", "salvo_pan_width": "Pan-Breite",
    "salvo_level_step_db": "Pegel-Schritt", "salvo_pitch_step_st": "Ton-Schritt",
    "salvo_humanize": "Humanize",
    "filter_slope": "Flanke", "hp_hz": "Hochpass", "lp_hz": "Tiefpass",
    "lp_resonance": "Resonanz", "lp_sweep_ms": "Sweep-Zeit", "lp_sweep_hz": "Sweep-Ziel",
    "echo_mix": "Echo", "echo_ms": "Zeit", "echo_sync": "Notenwert",
    "echo_feedback": "Rückkopplung", "echo_pingpong": "Ping-Pong", "echo_damp_hz": "Dämpfung",
    "reverb_mix": "Hall", "reverb_size": "Größe", "reverb_decay_ms": "Nachhall",
    "reverb_damp_hz": "Dämpfung", "reverb_predelay_ms": "Vorverzögerung",
    "reverb_width": "Breite", "bpm": "Tempo",
}
UNITS: dict[str, str] = {
    "salvo_level_step_db": "dB", "salvo_pitch_step_st": "st", "peak_ceiling_dbfs": "dBFS",
    "bpm": "BPM", "salvo_count": "", "glitch_steps": "",
}
PAN_LABELS: dict[str, str] = {
    "center": "Mitte", "alternate_lr": "L-R-L-R", "alternate_rl": "R-L-R-L",
    "sweep_lr": "Links > Rechts", "sweep_rl": "Rechts > Links", "random": "Zufall",
}
RATE_MODE_LABELS: dict[str, str] = {"ms": "ms", "hz": "Hz", "sync": "Sync"}

# ---- groups ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class GroupDef:
    key: str
    label: str
    main: tuple[str, ...]  # Hauptregler (accent colour)
    advanced: tuple[str, ...]  # under "Erweitert"
    switch: tuple[str, ...]  # fields whose non-default value means "this group is in use"
    hint: str  # German, one line: what the group does (no sound claim)

    @property
    def fields(self) -> tuple[str, ...]:
        return self.main + self.advanced


GROUPS: tuple[GroupDef, ...] = (
    GroupDef(
        "weapon", "Waffe",
        main=("family", "pitch_start_hz", "pitch_end_hz", "sweep_ms", "sweep_curve", "length_ms",
              "attack_ms", "decay_ms", "drive"),
        advanced=("fm_amount", "fm_ratio", "ring_amount", "ring_hz", "noise_level", "noise_hz",
                  "crackle", "glitch_steps", "stereo_width", "variation", "offset_ms",
                  "peak_ceiling_dbfs", "polarity"),
        switch=(), hint="Eine Stimme: Familie, Tonhöhen-Sweep, Hüllkurve."),
    GroupDef(
        "salvo", "Salve",
        main=("salvo_count", "salvo_rate_mode", "salvo_spacing_ms", "salvo_rate_hz",
              "salvo_sync_note", "salvo_rate_ramp", "salvo_pan_mode", "salvo_pan_width"),
        advanced=("salvo_level_step_db", "salvo_pitch_step_st", "salvo_humanize"),
        switch=("salvo_count",), hint="2 bis 5 Schüsse hintereinander in einer Datei."),
    GroupDef(
        "filter", "Filter",
        main=("lp_hz", "hp_hz", "lp_sweep_ms"),
        advanced=("lp_resonance", "lp_sweep_hz", "filter_slope"),
        switch=("hp_hz", "lp_hz", "lp_sweep_ms"), hint="Tiefpass, Hochpass, schließender Sweep."),
    GroupDef(
        "delay", "Delay",
        main=("echo_mix", "echo_ms", "echo_sync", "echo_feedback"),
        advanced=("echo_pingpong", "echo_damp_hz"),
        switch=("echo_mix",), hint="Echo mit Zeit oder Notenwert."),
    GroupDef(
        "reverb", "Reverb",
        main=("reverb_mix", "reverb_size", "reverb_decay_ms"),
        advanced=("reverb_damp_hz", "reverb_predelay_ms", "reverb_width"),
        switch=("reverb_mix",), hint="Algorithmischer Hall, deterministisch."),
)
GROUP_BY_KEY = {g.key: g for g in GROUPS}
GROUP_OF: dict[str, str] = {f: g.key for g in GROUPS for f in g.fields}
FIELD_NAMES: tuple[str, ...] = tuple(f for g in GROUPS for f in g.fields)
RANDOM_SKIP = frozenset({"polarity", "offset_ms", "peak_ceiling_dbfs"})
FIXED_FIELDS = ("sample_rate", "bit_depth")  # sent with the contract default, no control


@cache
def laser_specs() -> dict[str, FieldSpec]:
    """Every field the blaster edits (plus ``bpm``, ``sample_rate``, ``bit_depth``) as read from
    the contract, with German label and unit."""
    schema = load_schema(LASER_SCHEMA)
    raw: dict[str, tuple[dict[str, Any], str | None]] = {
        n: (d, None) for n, d in schema["properties"].items()}
    for gate, props in gated_branches(schema).items():
        for n, d in props.items():  # the 0.1 branch only narrows length_ms: not a field
            raw.setdefault(n, (d, gate))
    out: dict[str, FieldSpec] = {}
    for name in (*FIELD_NAMES, "bpm", *FIXED_FIELDS):
        d, gate = raw[name]
        spec = _spec(name, d, gate)
        out[name] = replace(spec, label=LABELS.get(name, name),
                            unit=UNITS.get(name, spec.unit))
    return out


def spec(name: str) -> FieldSpec:
    try:
        return laser_specs()[name]
    except KeyError:
        raise BlasterError(f"Unbekanntes Feld: {name}") from None


def default_of(name: str) -> Any:
    if name == "bpm":
        return BPM_DEFAULT
    return spec(name).default


@cache
def default_values() -> dict[str, Any]:
    return {n: default_of(n) for n in (*FIELD_NAMES, "bpm")}


def enum_values(name: str) -> tuple[Any, ...]:
    """Choices of an enum field, or the whole numbers of a small integer range (salvo_count)."""
    s = spec(name)
    if s.kind == "enum":
        return tuple(s.choices)
    if s.kind == "int":
        return tuple(range(int(s.minimum), int(s.maximum) + 1))  # type: ignore[arg-type]
    raise BlasterError(f"{name} ist kein Auswahlfeld.")


def note_ms(note: str, bpm: float) -> float:
    """Length of a note value in ms at ``bpm`` (contract point 17: quarter = 60000 / bpm; T =
    2/3, D = 3/2 of the plain value)."""
    m = re.fullmatch(r"1/(\d+)([TD]?)", note)
    if not m or int(m.group(1)) not in (4, 8, 16, 32):
        raise BlasterError(f"Unbekannter Notenwert: {note}")
    ms = 60000.0 / bpm * 4.0 / int(m.group(1))
    return ms * {"": 1.0, "T": 2.0 / 3.0, "D": 1.5}[m.group(2)]


# ---- settings ----------------------------------------------------------------------------------
def check_value(name: str, value: Any) -> Any:
    """``value`` if it is valid for the contract field, else :class:`BlasterError` (German)."""
    s = spec(name)
    label = s.label
    if s.kind == "enum":
        if value not in s.choices or isinstance(value, bool):
            raise BlasterError(f"{label}: {value!r} ist keine erlaubte Auswahl.")
        return value
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise BlasterError(f"{label} muss eine Zahl sein, nicht {value!r}.")
    if value != value or value in (float("inf"), float("-inf")):
        raise BlasterError(f"{label} muss eine endliche Zahl sein.")
    if s.kind == "int" and not float(value).is_integer():
        raise BlasterError(f"{label} muss eine ganze Zahl sein, nicht {value!r}.")
    if not s.minimum <= value <= s.maximum:  # type: ignore[operator]
        raise BlasterError(f"{label}: {value!r} liegt außerhalb von {s.range_text}.")
    return int(value) if s.kind == "int" else value


@dataclass(frozen=True, eq=False)
class BlasterSettings:
    """All edited contract fields (immutable snapshot) plus the tempo."""

    values: Mapping[str, Any] = field(default_factory=lambda: dict(default_values()))

    def __post_init__(self) -> None:
        vals = dict(self.values)
        extra = set(vals) - set(default_values())
        if extra:
            raise ValueError(f"Unbekannte Felder: {', '.join(sorted(extra))}")
        full = {**default_values(), **vals}
        for n, v in full.items():
            try:
                full[n] = check_value(n, v)
            except BlasterError as exc:
                raise ValueError(str(exc)) from exc
        object.__setattr__(self, "values", full)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, BlasterSettings) and dict(self.values) == dict(other.values)

    def __hash__(self) -> int:
        return hash(tuple(sorted(self.values.items())))

    def get(self, name: str) -> Any:
        return self.values[name]

    @property
    def dimension(self) -> str:
        return self.values["family"]

    def with_values(self, **kw: Any) -> BlasterSettings:
        return BlasterSettings({**self.values, **kw})

    def uses_sync(self) -> bool:
        return self.values["salvo_rate_mode"] == "sync" or self.values["echo_sync"] != "off"

    def group_in_use(self, key: str) -> bool:
        g = GROUP_BY_KEY[key]
        return any(self.values[f] != default_of(f) for f in g.switch)


def to_engine_params(s: BlasterSettings, caps: Mapping[str, float] | None = None
                     ) -> dict[str, Any]:
    """Request for ``render_laser`` / ``write_sample("laser", ...)`` without the seed: every
    edited field with its value, ``schema_version`` 0.2 and ``bpm`` only when a tempo sync is
    used. ``caps`` (preview profile) lowers listed fields to at most the given value."""
    p: dict[str, Any] = {"schema_version": SCHEMA_VERSION}
    for n in FIXED_FIELDS:
        p[n] = default_of(n)
    for n in FIELD_NAMES:
        v = s.values[n]
        if caps and n in caps and v > caps[n]:
            v = caps[n]
        p[n] = v
    if s.uses_sync():
        p["bpm"] = s.values["bpm"]
    return p


def validate_request(params: dict[str, Any], seed: int = 0) -> dict[str, Any]:
    """The engine's own check (``resolve_laser_params``); raises :class:`BlasterError`."""
    try:
        return resolve_laser_params({**params, "seed": seed})
    except LaserParamsError as exc:
        raise BlasterError(f"Ungültige Parameter: {exc}") from exc


# ---- preview profile (cheap render while dragging) -------------------------------------------
PREVIEW_CAPS: dict[str, float] = {
    "length_ms": 800, "decay_ms": 400, "salvo_count": 2, "reverb_decay_ms": 600,
}


def _caps_for(s: BlasterSettings) -> dict[str, float]:
    """The caps that matter for ``s`` (the reverb tail only while the reverb is on)."""
    return {n: c for n, c in PREVIEW_CAPS.items()
            if n != "reverb_decay_ms" or s.values["reverb_mix"] > 0}


def preview_params(s: BlasterSettings) -> dict[str, Any]:
    return to_engine_params(s, _caps_for(s))


def capped_fields(s: BlasterSettings) -> list[str]:
    """Fields whose value the preview profile lowers for ``s`` (German labels)."""
    return [spec(n).label for n, cap in _caps_for(s).items() if s.values[n] > cap]


# ---- fire rate -----------------------------------------------------------------------------------
AUTOFIRE_MIN_MS = 150.0


def base_gap_ms(s: BlasterSettings) -> float:
    """The gap between two shots of a salvo before the ramp (contract point 17)."""
    mode = s.values["salvo_rate_mode"]
    if mode == "ms":
        return float(s.values["salvo_spacing_ms"])
    if mode == "hz":
        return 1000.0 / float(s.values["salvo_rate_hz"])
    return note_ms(s.values["salvo_sync_note"], float(s.values["bpm"]))


def autofire_interval_ms(s: BlasterSettings) -> float:
    """Time between two salvos while the trigger is held: the shots continue at the chosen
    rate, so one salvo takes ``salvo_count`` gaps (ramp ignored). Never below
    :data:`AUTOFIRE_MIN_MS`."""
    return max(AUTOFIRE_MIN_MS, int(s.values["salvo_count"]) * base_gap_ms(s))


# ---- presets and files -----------------------------------------------------------------------
def settings_from_request(req: Mapping[str, Any]) -> tuple[BlasterSettings, int | None, str]:
    """Validate a laser-params object against the contract (the engine's resolve) and return
    ``(settings, seed or None, preset name)``. Raises :class:`BlasterError`."""
    if not isinstance(req, Mapping):
        raise BlasterError("Die Datei enthält kein Laser-Parameterobjekt.")
    try:
        resolved = resolve_laser_params(dict(req))
    except LaserParamsError as exc:
        raise BlasterError(f"Nicht gültig laut Kontrakt: {exc}") from exc
    vals = {n: resolved[n] for n in FIELD_NAMES if n in resolved}
    if "bpm" in resolved:
        vals["bpm"] = resolved["bpm"]
    seed = int(req["seed"]) if "seed" in req else None
    return BlasterSettings(vals), seed, str(req.get("preset", ""))


def laser_preset_names() -> list[str]:
    """Shipped laser presets; the blaster presets (``blaster*``) come first."""
    names = preset_names("laser")
    return sorted(names, key=lambda n: (not n.startswith("blaster"), n))


def preset_description(name: str) -> str:
    return describe(name, "laser")


def load_named_preset(name: str) -> BlasterSettings:
    try:
        raw = load_preset(name, "laser")
    except KeyError as exc:
        raise BlasterError(f"Preset unbekannt: {name}") from exc
    return settings_from_request(raw)[0]


def request_document(s: BlasterSettings, seed: int, name: str = "") -> dict[str, Any]:
    """A complete laser-params object (the contract's own format) for saving."""
    doc = {**to_engine_params(s), "seed": seed}
    doc.setdefault("bpm", s.values["bpm"]) if s.uses_sync() else None
    if name:
        doc["preset"] = name[:64]
    return doc


def save_settings_file(path: Path, s: BlasterSettings, seed: int, name: str = "") -> None:
    doc = request_document(s, seed, name or Path(path).stem)
    validate_request({k: v for k, v in doc.items() if k != "seed"}, seed)
    text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    tmp = Path(str(path) + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise BlasterError(f"Preset konnte nicht gespeichert werden: {exc}") from exc


def load_settings_file(path: Path) -> tuple[BlasterSettings, int | None, str]:
    try:
        if Path(path).stat().st_size > MAX_FILE_BYTES:
            raise BlasterError("Die Datei ist zu groß für ein Preset.")
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except BlasterError:
        raise
    except (OSError, UnicodeDecodeError) as exc:
        raise BlasterError(f"Datei nicht lesbar: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise BlasterError(f"Keine gültige JSON-Datei: {exc}") from exc
    return settings_from_request(doc)


def apply_groups(base: BlasterSettings, new: BlasterSettings, allowed: Iterable[str]
                 ) -> BlasterSettings:
    """``base`` with the fields of the groups in ``allowed`` taken from ``new`` (``bpm`` goes
    with the groups that use a tempo sync)."""
    allowed = set(allowed)
    vals = dict(base.values)
    for g in GROUPS:
        if g.key in allowed:
            for f in g.fields:
                vals[f] = new.values[f]
    if allowed & {"salvo", "delay"}:
        vals["bpm"] = new.values["bpm"]
    return BlasterSettings(vals)


# ---- randomise ----------------------------------------------------------------------------------
def randomise(s: BlasterSettings, groups: Iterable[str], seed: int) -> BlasterSettings:
    """Seeded random values for the fields of ``groups`` (uniform over the slider travel of
    each contract range, uniform over enum choices). Each group has its own random stream, so a
    group's result does not depend on which other groups are drawn. Same input, same output."""
    vals = dict(s.values)
    for gi, g in enumerate(GROUPS):
        if g.key not in set(groups):
            continue
        rng = np.random.default_rng([int(seed), gi])
        for f in g.fields:
            if f in RANDOM_SKIP:
                continue
            sp = spec(f)
            if sp.kind == "enum" or (sp.kind == "int" and sp.maximum - sp.minimum <= 8):
                choices = enum_values(f)
                vals[f] = choices[int(rng.integers(len(choices)))]
            else:
                vm = map_of(sp)
                vals[f] = vm.from_pos(int(rng.integers(0, vm.pos_max + 1)))
    return BlasterSettings(vals)


# ---- undo / redo and A/B ---------------------------------------------------------------------
class UndoStack:
    """Snapshots of the settings. ``record`` after a finished change (drag released, key
    pressed, preset loaded); an unchanged state is not recorded."""

    def __init__(self, initial: BlasterSettings, limit: int = 200) -> None:
        self._items: list[tuple[BlasterSettings, str]] = [(initial, "Start")]
        self._at = 0
        self.limit = limit

    @property
    def current(self) -> BlasterSettings:
        return self._items[self._at][0]

    def record(self, s: BlasterSettings, label: str = "") -> bool:
        if s == self.current:
            return False
        del self._items[self._at + 1:]
        self._items.append((s, label))
        if len(self._items) > self.limit:
            del self._items[0]
        self._at = len(self._items) - 1
        return True

    def can_undo(self) -> bool:
        return self._at > 0

    def can_redo(self) -> bool:
        return self._at < len(self._items) - 1

    def undo(self) -> BlasterSettings | None:
        if not self.can_undo():
            return None
        self._at -= 1
        return self.current

    def redo(self) -> BlasterSettings | None:
        if not self.can_redo():
            return None
        self._at += 1
        return self.current

    def undo_label(self) -> str:
        return self._items[self._at][1] if self.can_undo() else ""


class ABSlots:
    """Two settings slots; the active one is the live state. A slot that was never used starts
    as a copy of the state it is first switched from."""

    def __init__(self, live: BlasterSettings) -> None:
        self.slots: dict[str, BlasterSettings | None] = {"A": live, "B": None}
        self.active = "A"

    def switch(self, to: str, live: BlasterSettings) -> BlasterSettings:
        if to not in self.slots:
            raise BlasterError(f"Unbekannter Speicherplatz: {to}")
        self.slots[self.active] = live
        self.active = to
        if self.slots[to] is None:
            self.slots[to] = live
        return self.slots[to]  # type: ignore[return-value]

    def copy_to_other(self, live: BlasterSettings) -> str:
        other = "B" if self.active == "A" else "A"
        self.slots[self.active] = live
        self.slots[other] = live
        return other


# ---- job queue: one running, at most one pending ------------------------------------------------
PRIORITY = {"preview": 0, "shot": 1, "bank": 2}


@dataclass
class Job:
    kind: str  # "preview" | "shot" | "bank"
    fn: Callable[[], Any] | None = None  # built when the job starts (seed counter, folder)
    meta: Any = None


class JobQueue:
    """One job runs, at most one waits. A newer job replaces the waiting one when its priority
    is not lower; a lower-priority job (a preview behind a waiting shot) is dropped. Qt-free;
    the window starts the threads."""

    def __init__(self) -> None:
        self.running: Job | None = None
        self.pending: Job | None = None
        self.replaced = 0
        self.dropped = 0

    def submit(self, job: Job) -> str:
        """``"started"`` (caller runs it now), ``"queued"``, ``"replaced"`` or ``"dropped"``."""
        if self.running is None:
            self.running = job
            return "started"
        if self.pending is None:
            self.pending = job
            return "queued"
        if PRIORITY[job.kind] >= PRIORITY[self.pending.kind]:
            self.pending = job
            self.replaced += 1
            return "replaced"
        self.dropped += 1
        return "dropped"

    def finish(self) -> Job | None:
        """The running job ended; returns the waiting job to start next (now running)."""
        self.running, self.pending = self.pending, None
        return self.running

    @property
    def busy(self) -> bool:
        return self.running is not None
