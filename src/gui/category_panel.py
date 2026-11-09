"""Parameter page of one category, built from the widget kit.

Layout: preset chips, the "Hauptregler" as knobs (accent colour), the output row (seed, variants)
and a collapsed "Erweitert" section with every other contract field as a neutral slider, switch
or button row. State and checks live in ``CategoryFormModel``; links between fields (limits from
the engine's own ``resolve``, exclusions and derived values from the contract) live in
``gui_core.links``. This widget only shows them and forwards edits.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from gui_core import atmos_cost, fx_cost, links
from gui_core.form import ALWAYS_ACTIVE, CategoryFormModel, FieldSpec, _text_of
from gui_core.form_layout import main_choices, main_controls

from .widgets import (
    BoolControl,
    ChoiceControl,
    Collapsible,
    FlowLayout,
    ListControl,
    NumberControl,
    ParamControl,
    PresetChips,
    SeedControl,
    heading,
    muted,
    rule,
)

IDLE_BATCH = 4  # stale sliders probed per idle tick (#434: ~3 resolves each, a few ms)
LASER_GROUPS = (("salvo_", "Salve"), ("filter_", "Filter"), ("hp_", "Filter"), ("lp_", "Filter"),
                ("echo_", "Delay"), ("reverb_", "Reverb"))
# Short labels: "Rauschen und Filter (6 Felder)" was 407 px on Windows CI, above the 34 M page.
FX_GROUPS = (("noise_", "Rauschen"), ("filter_", "Filter"), ("cutoff_", "Filter"),
             ("lp_ratio", "Filter"), ("sweep_", "Filter"), ("level_", "Pegel"), ("ramp_", "Pegel"),
             ("pump_", "Pegel"), ("tone_", "Ton"), ("echo_", "Delay"), ("reverb_", "Reverb"))
ATMOS_GROUPS = (("fade_", "One-Shot"), ("tail_", "One-Shot"), ("hp_", "Filter"),
                ("lp_", "Filter"), ("filter_", "Filter"), ("move_", "Bewegung"),
                ("amp_move", "Bewegung"), ("pan_move", "Bewegung"), ("pump_", "Bewegung"),
                ("note", "Ton"), ("cents", "Ton"), ("intervals", "Ton"), ("partials", "Ton"),
                ("brightness_", "Ton"), ("detune_", "Ton"), ("drift_", "Ton"),
                ("max_tuning", "Ton"), ("res_q", "Ton"), ("granular_", "Grains"),
                ("grain_", "Grains"), ("reverb_", "Reverb"))
GROUPS = {"laser": LASER_GROUPS, "fx": FX_GROUPS, "atmos": ATMOS_GROUPS}
FX_BPM_HINT = ("Tempo des Tracks einstellen: die Längen sind in Beats, sonst endet das FX nicht "
               "auf dem Taktstrich in Live.")
ATMOS_BPM_HINT = ("Tempo des Tracks einstellen: die Schleife ist eine ganze Zahl von Takten bei "
                  "diesem Tempo, nur dann loopt sie in Live nahtlos auf dem Taktraster.")
# Fields shown above the Hauptregler, and the hint under them (fx #482, atmos #533).
TOP_FIELDS = {"fx": ("bpm",), "atmos": ("bpm", "bars", "loop_mode")}
BPM_HINTS = {"fx": FX_BPM_HINT, "atmos": ATMOS_BPM_HINT}
COST_NOTES = {"fx": fx_cost.cost_note, "atmos": atmos_cost.cost_note}  # render-time notes


def _field_groups(category: str, specs: list[FieldSpec]) -> dict[str, list[FieldSpec]]:
    """Laser and fx: groups of contract fields, each its own collapsible section (grouped by
    the contract's field-name prefix, so a new field with such a prefix lands in its group).
    Other categories have no groups."""
    table = GROUPS.get(category)
    if table is None:
        return {}
    out: dict[str, list[FieldSpec]] = {}
    for label in dict.fromkeys(g for _, g in table):  # group order of the table
        prefixes = tuple(p for p, g in table if g == label)
        members = [s for s in specs if s.name.startswith(prefixes)]
        if members:
            out[label] = members
    return out


class CategoryPanel(QScrollArea):
    changed = Signal()

    def __init__(self, model: CategoryFormModel) -> None:
        super().__init__()
        self.model = model
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.controls: dict[str, ParamControl] = {}
        self.main_names = main_controls(model.category)
        self.knobs: list[NumberControl] = []
        self._notices: list[str] = []
        self._syncing = False
        # Limits (#434). Each probe is an engine resolve (~0.5 ms laser), so a refresh probes
        # only the Hauptregler at once; the other shown sliders are "stale" and probed in small
        # batches while the event loop is idle, hidden ones when a section opens. Right before
        # the user moves or types into a stale control, or code reads its limits
        # (``limitsWanted``), it is probed first, so a stale limit is never used. During a
        # mouse drag only the Hauptregler are probed; the release refreshes the rest.
        self._lims: dict[str, links.Limit] = {}
        self._stale: set[str] = set()
        self._pending: list[str] = []
        self._idle = QTimer(self)
        self._idle.setInterval(0)
        self._idle.timeout.connect(self._probe_pending)

        root = QWidget()
        root.setObjectName("root")
        lay = QVBoxLayout(root)
        lay.setContentsMargins(8, 4, 12, 16)
        lay.setSpacing(6)
        self.setWidget(root)

        lay.addWidget(heading("Preset"))
        self.chips = PresetChips(model.preset_names())
        self.chips.setAccessibleName("Preset")
        self.chips.chosen.connect(self._preset_chosen)
        lay.addWidget(self.chips)
        self.preset_text = muted()
        lay.addWidget(self.preset_text)

        # fx (#482): all lengths are in beats, so the tempo is shown on top with a hint.
        # atmos (#533): tempo, bars and loop / one-shot on top, with a line about the file.
        self.top_fields: tuple[str, ...] = TOP_FIELDS.get(model.category, ())
        self.cost_label: QLabel | None = None
        self.length_label: QLabel | None = None
        if self.top_fields:
            lay.addWidget(heading("Tempo und Länge" if len(self.top_fields) > 1 else "Tempo"))
            for name in self.top_fields:
                lay.addWidget(self._make(model.spec(name), main=False))
            bpm_hint = muted(BPM_HINTS[model.category])
            bpm_hint.setObjectName("bpmhint")
            bpm_hint.setWordWrap(True)
            bpm_hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
            lay.addWidget(bpm_hint)
        if model.category == "atmos":
            self.length_label = muted()
            self.length_label.setObjectName("lengthhint")
            self.length_label.setWordWrap(True)
            self.length_label.setSizePolicy(QSizePolicy.Policy.Ignored,
                                            QSizePolicy.Policy.Minimum)
            lay.addWidget(self.length_label)

        lay.addWidget(heading("Hauptregler"))
        for name in main_choices(model.category):
            if name not in self.top_fields:
                lay.addWidget(self._make(model.spec(name), main=True))
        # The knobs wrap to a second line on a narrow page (#442: five knobs in one row made
        # the page 47 M wide, too wide for 1920 x 1080 at 150 %).
        self.knob_box = QWidget()
        knob_row = FlowLayout(self.knob_box, spacing=2)
        for name in self.main_names:
            knob = self._make(model.spec(name), main=True)
            self.knobs.append(knob)  # type: ignore[arg-type]
            knob_row.addWidget(knob)
        lay.addWidget(self.knob_box)
        self.link_label = QLabel()
        self.link_label.setObjectName("linkhint")
        self.link_label.setWordWrap(True)
        self.link_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        self.link_label.hide()
        lay.addWidget(self.link_label)
        self.hint_label = muted(
            "Ein Griff oder Regler an: der Wert wird mitgeschickt. Doppelklick setzt auf das "
            "Preset zurück.")
        lay.addWidget(self.hint_label)
        if model.category == "laser":
            note = muted(
                "Abzug, Salven-Muster, A/B-Speicher und Undo gibt es im Fenster "
                "\"Laser-Blaster\" (Knopf links unten).")
            note.setWordWrap(True)
            note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
            lay.addWidget(note)

        lay.addWidget(rule())
        lay.addWidget(heading("Ausgabe"))
        for name in ALWAYS_ACTIVE:
            lay.addWidget(self._make(model.spec(name), main=False))
        if model.category in COST_NOTES:  # render-time note before rendering (#503, #533)
            self.cost_label = QLabel()
            self.cost_label.setObjectName("costhint")
            self.cost_label.setWordWrap(True)
            self.cost_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
            self.cost_label.hide()
            lay.addWidget(self.cost_label)

        self.advanced = Collapsible("Erweitert")
        body = QVBoxLayout(self.advanced.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(4)
        extra = [s for s in model.specs if s.name not in self.main_names
                 and s.name not in ALWAYS_ACTIVE and s.name not in main_choices(model.category)
                 and s.name not in self.top_fields]
        groups = _field_groups(model.category, extra)
        grouped = {s.name for members in groups.values() for s in members}
        extra = [s for s in extra if s.name not in grouped]
        base = [s for s in extra if not s.gate_version]
        gated = [s for s in extra if s.gate_version]
        for spec in base:
            body.addWidget(self._make(spec, main=False))
        if gated:
            versions = ", ".join(sorted({s.gate_version for s in gated}))  # type: ignore[type-var]
            title = heading(f"Zusätzliche Felder (Kontrakt {versions})")
            title.setWordWrap(True)  # the upper-case title must not widen the page (#442)
            body.addWidget(title)
            for spec in gated:
                body.addWidget(self._make(spec, main=False))
        self.advanced.set_title(f"Erweitert ({len(extra)} Felder)")
        self.advanced.toggled.connect(self._section_toggled)
        lay.addWidget(self.advanced)
        self.group_sections: dict[str, Collapsible] = {}
        for label, members in groups.items():  # laser: Salve, Filter, Delay, Reverb
            section = Collapsible(f"{label} ({len(members)} Felder)")
            inner = QVBoxLayout(section.body)
            inner.setContentsMargins(0, 0, 0, 0)
            inner.setSpacing(4)
            for spec in members:
                inner.addWidget(self._make(spec, main=False))
            section.toggled.connect(self._section_toggled)
            self.group_sections[label] = section
            lay.addWidget(section)
        lay.addStretch(1)
        self.sync_from_model()

    # --- building ----------------------------------------------------------------------------
    def _make(self, spec: FieldSpec, main: bool) -> ParamControl:
        c: ParamControl
        if spec.kind == "bool":
            c = BoolControl(spec)
        elif spec.kind == "list":
            c = ListControl(spec)
        elif spec.kind == "enum":
            c = ChoiceControl(spec, accent=main)
        elif spec.name == "seed":
            c = SeedControl(spec)
        elif main and spec.name in self.main_names:
            c = NumberControl(spec, style="knob", accent=True)
        else:
            c = NumberControl(spec, style="row", always_active=spec.name in self.model.locked)
        c.edited.connect(self._edited)
        if isinstance(c, NumberControl):
            c.limitsWanted.connect(self._ensure_limit)
        c.activeToggled.connect(self._active_toggled)
        c.committed.connect(self._committed)
        c.resetRequested.connect(self._reset)
        self.controls[spec.name] = c
        return c

    # --- user edits --------------------------------------------------------------------------
    def _preset_chosen(self, name: str) -> None:
        if self._syncing or not name:
            return
        self.model.set_preset(name)
        self._notices = []
        self.sync_from_model()
        self.changed.emit()

    def _edited(self, name: str, value) -> None:
        if self._syncing:
            return
        spec = self.model.spec(name)
        self._notices = links.activate(self.model, name)
        text = value if isinstance(value, str) else _text_of(spec, value)
        self.model.set_text(name, text)
        self._repair(name)
        c = self.controls[name]
        dragging = isinstance(c, NumberControl) and c.is_dragging()
        self._refresh(skip=name, probe_limits=not dragging)
        self.changed.emit()

    def _repair(self, changed: str) -> None:
        """Re-check the combination after a change the limits cannot see (a dot, a choice)."""
        fixed = links.repair(self.model, changed=changed)
        self._notices += fixed.notices
        for moved in fixed.moved:
            self.controls[moved].clear_edit_note()  # an old remark about that value is stale

    def _committed(self, name: str) -> None:
        if not self._syncing:
            self._refresh(skip=None, final=True)

    def _active_toggled(self, name: str, on: bool) -> None:
        if self._syncing:
            return
        if on:
            self._notices = links.activate(self.model, name)
            shown = links.derived_values(self.model).shown.get(name)
            if shown is not None and self.model.parse(name)[0] != shown:
                self.model.set_text(name, _text_of(self.model.spec(name), shown))
        else:
            self._notices = []
            self.model.set_active(name, False)
        self.controls[name].clear_edit_note()
        self._repair(name)
        self._refresh(skip=None, final=True)
        self.changed.emit()

    def _reset(self, name: str) -> None:
        if self._syncing:
            return
        self._notices = []
        self.model.reset_field(name)
        self.controls[name].clear_edit_note()
        self._repair(name)
        self._refresh(skip=None, final=True)
        self.changed.emit()

    # --- model -> widgets --------------------------------------------------------------------
    def sync_from_model(self) -> None:
        """Show the model's state (after a preset change)."""
        self._syncing = True
        try:
            for c in self.controls.values():
                c.clear_edit_note()
            self.chips.set_current(self.model.preset)
            self.preset_text.setText(self.model.preset_description())
            self._refresh(skip=None, final=True)
        finally:
            self._syncing = False

    # --- limits ------------------------------------------------------------------------------
    def _shown_numbers(self) -> list[str]:
        return [n for n, c in self.controls.items()
                if isinstance(c, NumberControl) and c.isVisibleTo(self)]

    def _probe(self, names: list[str]) -> None:
        """Probe the limits of ``names`` now and show them."""
        if not names:
            return
        fresh = links.limits(self.model, names=names)
        for name, lim in fresh.items():
            self._lims[name] = lim
            self._stale.discard(name)
            self.controls[name].set_limits(lim.lo, lim.hi, lim.reason)  # type: ignore[attr-defined]

    def _ensure_limit(self, name: str) -> None:
        """A control is about to read its limits (user move or typed value)."""
        if name in self._stale:
            self._probe([name])

    def _section_toggled(self, on: bool) -> None:
        if on:
            self._probe([n for n in self._shown_numbers() if n in self._stale])

    def _schedule(self, names: list[str]) -> None:
        self._pending = names
        if names:
            self._idle.start()
        else:
            self._idle.stop()

    def _probe_pending(self) -> None:
        """Idle timer: probe the next few shown stale sliders (each batch stays short)."""
        shown = set(self._shown_numbers())
        batch: list[str] = []
        while self._pending and len(batch) < IDLE_BATCH:
            name = self._pending.pop(0)
            if name in self._stale and name in shown:
                batch.append(name)
        self._probe(batch)
        if not self._pending:
            self._idle.stop()

    def settle(self) -> None:
        """Probe every pending limit now (tests, screenshots)."""
        while self._pending:
            self._probe_pending()

    def _refresh(self, skip: str | None, final: bool = False, probe_limits: bool = True) -> None:
        was = self._syncing
        self._syncing = True
        try:
            model = self.model
            problems = model.field_issues()
            derived = links.derived_values(model, heavy=final)
            numbers = [n for n, c in self.controls.items()
                       if isinstance(c, NumberControl) and n != skip]
            shown = self._shown_numbers()
            # The Hauptregler are probed on every refresh, also during a drag: the link hint
            # lists their limits with the partner's current value (5 fields, mostly cached).
            now = [n for n in shown if n in self.main_names]
            if not probe_limits:  # mouse drag: the other sliders wait for the release
                shown = now
            lims = links.limits(model, skip=skip, names=now)
            self._lims.update(lims)
            self._stale.update(n for n in numbers if n not in lims)
            self._stale.difference_update(lims)
            self._schedule([n for n in shown if n != skip and n not in lims])
            for name, c in self.controls.items():
                active = name in model.active
                c.set_active(active)
                c.set_invalid(problems.get(name))
                if name == skip:
                    continue
                self._show_value(c, active, derived)
                if isinstance(c, NumberControl) and name in lims:
                    lim = lims[name]
                    c.set_limits(lim.lo, lim.hi, lim.reason)
                c.set_derived_note(derived.notes.get(name, ""))
            self._show_links(self._lims, links_issue=model.cross_issue())
            self._show_cost()
        finally:
            self._syncing = was

    def _show_cost(self) -> None:
        """fx / atmos: the rough render-time note of the current request (#503, #533), hidden
        when short; atmos also the line about the file length (and the root's name in Live)."""
        if self.length_label is not None:
            text = atmos_cost.length_text(self.model)
            self.length_label.setText(text)
            self.length_label.setVisible(bool(text))
        if self.cost_label is None:
            return
        text = COST_NOTES[self.model.category](self.model)
        self.cost_label.setText(text)
        self.cost_label.setVisible(bool(text))

    def _show_value(self, c: ParamControl, active: bool, derived: links.Derived) -> None:
        spec = c.spec
        if isinstance(c, NumberControl):
            value, problem = self.model.parse(c.name)
            if not active and c.name in derived.shown:
                value, problem = derived.shown[c.name], None
            if problem is None and (c.value() != value):
                c.set_value(value)
        elif isinstance(c, SeedControl | ListControl):
            c.set_value(self.model.text[c.name])
        else:
            text = self.model.text[c.name]
            if spec.kind == "bool" and c.value() != text or spec.kind == "enum" and (
                    c.value() != text):
                c.set_value(text)

    def _show_links(self, lims: dict[str, links.Limit], links_issue: str | None) -> None:
        lines = list(self._notices)
        for name in self.main_names:
            lim = lims.get(name)
            if lim is not None and lim.limited:
                lines.append(lim.reason)
        if links_issue:
            lines.append(links_issue)
        self.link_label.setText("\n".join(lines))
        self.link_label.setVisible(bool(lines))
