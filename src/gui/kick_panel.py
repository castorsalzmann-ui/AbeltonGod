"""Kick parameter panel: one row per contract field. State and checks live in KickFormModel."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from gui_core.form import ALWAYS_ACTIVE, KickFormModel


class KickPanel(QScrollArea):
    changed = Signal()

    def __init__(self, model: KickFormModel) -> None:
        super().__init__()
        self.model = model
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.edits: dict[str, QLineEdit | QComboBox] = {}
        self.checks: dict[str, QCheckBox] = {}
        self._syncing = False

        root = QWidget()
        root.setObjectName("root")
        lay = QVBoxLayout(root)
        self.setWidget(root)

        lay.addWidget(self._heading("Preset"))
        self.preset_box = QComboBox()
        self.preset_box.addItems(model.preset_names())
        self.preset_box.setCurrentText(model.preset)
        self.preset_box.currentTextChanged.connect(self._preset_chosen)
        lay.addWidget(self.preset_box)
        self.preset_text = QLabel()
        self.preset_text.setObjectName("muted")
        self.preset_text.setWordWrap(True)
        lay.addWidget(self.preset_text)

        main = QGridLayout()
        extra = QGridLayout()
        for grid in (main, extra):
            grid.setColumnStretch(0, 3)
            grid.setColumnStretch(1, 2)
            grid.setColumnStretch(2, 2)
        counters = {False: 0, True: 0}
        for spec in model.specs:
            grid = extra if spec.optional_v03 else main
            row = counters[spec.optional_v03]
            counters[spec.optional_v03] += 1
            check = QCheckBox(spec.label)
            check.setToolTip(spec.description)
            if spec.name in ALWAYS_ACTIVE:
                check.setChecked(True)
                check.setEnabled(False)
            else:
                check.toggled.connect(lambda on, n=spec.name: self._toggled(n, on))
            self.checks[spec.name] = check
            if spec.kind == "enum":
                edit: QLineEdit | QComboBox = QComboBox()
                edit.addItems([str(c) for c in spec.choices])
                edit.currentTextChanged.connect(lambda t, n=spec.name: self._edited(n, t))
            else:
                edit = QLineEdit()
                edit.textEdited.connect(lambda t, n=spec.name: self._edited(n, t))
            edit.setToolTip(spec.description)
            edit.setAccessibleName(spec.label)
            self.edits[spec.name] = edit
            unit = QLabel(spec.range_text)
            unit.setObjectName("muted")
            grid.addWidget(check, row, 0)
            grid.addWidget(edit, row, 1)
            grid.addWidget(unit, row, 2)

        lay.addWidget(self._heading("Parameter"))
        lay.addLayout(main)
        lay.addWidget(self._heading("Erweiterte Felder (Kontrakt 0.3)"))
        lay.addLayout(extra)
        lay.addStretch(1)
        self.sync_from_model()

    @staticmethod
    def _heading(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("heading")
        return label

    def _preset_chosen(self, name: str) -> None:
        if self._syncing or not name:
            return
        self.model.set_preset(name)
        self.sync_from_model()
        self.changed.emit()

    def _toggled(self, name: str, on: bool) -> None:
        if self._syncing:
            return
        self.model.set_active(name, on)
        self._refresh_marks()
        self.changed.emit()

    def _edited(self, name: str, text: str) -> None:
        if self._syncing:
            return
        self.model.set_text(name, text)
        self._refresh_marks()
        self.changed.emit()

    def sync_from_model(self) -> None:
        """Show the model's state (after a preset change)."""
        self._syncing = True
        try:
            self.preset_box.setCurrentText(self.model.preset)
            self.preset_text.setText(self.model.preset_description())
            for name, edit in self.edits.items():
                text = self.model.text[name]
                if isinstance(edit, QComboBox):
                    edit.setCurrentText(text)
                else:
                    edit.setText(text)
                if name not in ALWAYS_ACTIVE:
                    self.checks[name].setChecked(name in self.model.active)
        finally:
            self._syncing = False
        self._refresh_marks()

    def _refresh_marks(self) -> None:
        problems = self.model.field_issues()
        for name, edit in self.edits.items():
            edit.setEnabled(name in self.model.active)
            bad = name in problems
            edit.setProperty("invalid", bad)
            edit.setToolTip(problems[name] if bad else self.model.spec(name).description)
            edit.style().unpolish(edit)
            edit.style().polish(edit)
