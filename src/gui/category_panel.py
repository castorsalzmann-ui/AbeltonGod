"""Parameter page of one category, built from the widget kit.

Layout: preset chips, the "Hauptregler" as knobs (accent colour), the output row (seed, variants)
and a collapsed "Erweitert" section with every other contract field as a neutral slider, switch
or button row. State and checks live in ``CategoryFormModel``; links between fields (limits from
the engine's own ``resolve``, exclusions and derived values from the contract) live in
``gui_core.links``. This widget only shows them and forwards edits.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from gui_core import links
from gui_core.form import ALWAYS_ACTIVE, CategoryFormModel, FieldSpec, _text_of
from gui_core.form_layout import main_choices, main_controls

from .widgets import (
    BoolControl,
    ChoiceControl,
    Collapsible,
    NumberControl,
    ParamControl,
    PresetChips,
    SeedControl,
    heading,
    muted,
    rule,
)


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

        lay.addWidget(heading("Hauptregler"))
        for name in main_choices(model.category):
            lay.addWidget(self._make(model.spec(name), main=True))
        knob_row = QHBoxLayout()
        knob_row.setSpacing(2)
        for name in self.main_names:
            knob = self._make(model.spec(name), main=True)
            self.knobs.append(knob)  # type: ignore[arg-type]
            knob_row.addWidget(knob)
        knob_row.addStretch(1)
        lay.addLayout(knob_row)
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

        lay.addWidget(rule())
        lay.addWidget(heading("Ausgabe"))
        for name in ALWAYS_ACTIVE:
            lay.addWidget(self._make(model.spec(name), main=False))

        self.advanced = Collapsible("Erweitert")
        body = QVBoxLayout(self.advanced.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(4)
        extra = [s for s in model.specs if s.name not in self.main_names
                 and s.name not in ALWAYS_ACTIVE and s.name not in main_choices(model.category)]
        base = [s for s in extra if not s.gate_version]
        gated = [s for s in extra if s.gate_version]
        for spec in base:
            body.addWidget(self._make(spec, main=False))
        if gated:
            versions = ", ".join(sorted({s.gate_version for s in gated}))  # type: ignore[type-var]
            body.addWidget(heading(f"Zusätzliche Felder (Kontrakt {versions})"))
            for spec in gated:
                body.addWidget(self._make(spec, main=False))
        self.advanced.set_title(f"Erweitert ({len(extra)} Felder)")
        lay.addWidget(self.advanced)
        lay.addStretch(1)
        self.sync_from_model()

    # --- building ----------------------------------------------------------------------------
    def _make(self, spec: FieldSpec, main: bool) -> ParamControl:
        c: ParamControl
        if spec.kind == "bool":
            c = BoolControl(spec)
        elif spec.kind == "enum":
            c = ChoiceControl(spec, accent=main)
        elif spec.name == "seed":
            c = SeedControl(spec)
        elif main and spec.name in self.main_names:
            c = NumberControl(spec, style="knob", accent=True)
        else:
            c = NumberControl(spec, style="row", always_active=spec.name in ALWAYS_ACTIVE)
        c.edited.connect(self._edited)
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
        self._refresh(skip=name)
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

    def _refresh(self, skip: str | None, final: bool = False) -> None:
        was = self._syncing
        self._syncing = True
        try:
            model = self.model
            problems = model.field_issues()
            derived = links.derived_values(model, heavy=final)
            lims = links.limits(model, skip=skip)
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
            self._show_links(lims, links_issue=model.cross_issue())
        finally:
            self._syncing = was

    def _show_value(self, c: ParamControl, active: bool, derived: links.Derived) -> None:
        spec = c.spec
        if isinstance(c, NumberControl):
            value, problem = self.model.parse(c.name)
            if not active and c.name in derived.shown:
                value, problem = derived.shown[c.name], None
            if problem is None and (c.value() != value):
                c.set_value(value)
        elif isinstance(c, SeedControl):
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
