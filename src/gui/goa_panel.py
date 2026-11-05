"""Goa page: option form for the arrangement and melody generators, section preview, render.

State and checks live in ``gui_core.goa``; the generator runs in ``gui_core.goa_render``. This
widget only shows them."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from gui_core.goa import GROUPS, MODE_LABELS, MODES, GoaFormModel, OptionSpec, TimelinePlan
from gui_core.goa_render import GoaJob, GoaResult, GoaService
from gui_core.paths import default_output_dir

from .timeline_widget import TimelineWidget
from .tool_style import STYLE

BODY_HOOK = "goa_body"  # objectName of the page body: a hook for later skins/extra panels


class _Signals(QObject):
    done = Signal(object)


class OptionForm(QScrollArea):
    """One mode's options. ``edits[dest]`` is the editing widget (QLineEdit, QComboBox,
    QCheckBox, or a QWidget holding one QCheckBox per voice for ``multi``)."""

    changed = Signal()

    def __init__(self, model: GoaFormModel) -> None:
        super().__init__()
        self.model = model
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.edits: dict[str, QWidget] = {}
        self.checks: dict[str, QCheckBox] = {}
        self.voice_boxes: dict[str, dict[str, QCheckBox]] = {}
        self._syncing = False
        root = QWidget()
        root.setObjectName("root")
        lay = QVBoxLayout(root)
        self.setWidget(root)
        for group in GROUPS:
            specs = [s for s in model.specs if s.group == group]
            if not specs:
                continue
            head = QLabel(group)
            head.setObjectName("heading")
            lay.addWidget(head)
            grid = QGridLayout()
            grid.setColumnStretch(0, 3)
            grid.setColumnStretch(1, 3)
            grid.setColumnStretch(2, 3)
            for row, spec in enumerate(specs):
                self._add_row(grid, row, spec)
            lay.addLayout(grid)
        lay.addStretch(1)
        self.sync_from_model()

    def _add_row(self, grid: QGridLayout, row: int, spec: OptionSpec) -> None:
        if spec.optional:
            label: QWidget = QCheckBox(spec.label)
            label.toggled.connect(lambda on, d=spec.dest: self._toggled(d, on))
            self.checks[spec.dest] = label  # type: ignore[assignment]
        else:
            label = QLabel(spec.label)
        label.setToolTip(spec.help)
        edit: QWidget
        if spec.kind == "flag":
            edit = QCheckBox("ja")
            edit.toggled.connect(lambda on, d=spec.dest: self._edited(d, "ja" if on else "nein"))
        elif spec.kind == "enum":
            edit = QComboBox()
            edit.addItems(list(spec.choices))
            edit.currentTextChanged.connect(lambda t, d=spec.dest: self._edited(d, t))
        elif spec.kind == "multi":
            edit = QWidget()
            h = QHBoxLayout(edit)
            h.setContentsMargins(0, 0, 0, 0)
            boxes = {}
            for v in spec.choices:
                cb = QCheckBox(v)
                cb.toggled.connect(lambda _on, d=spec.dest: self._voices_edited(d))
                h.addWidget(cb)
                boxes[v] = cb
            self.voice_boxes[spec.dest] = boxes
        else:
            edit = QLineEdit()
            edit.textEdited.connect(lambda t, d=spec.dest: self._edited(d, t))
        edit.setToolTip(spec.help)
        if not isinstance(edit, QWidget) or spec.kind != "multi":
            edit.setAccessibleName(spec.label)
        self.edits[spec.dest] = edit
        hint = QLabel(spec.range_text)
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        grid.addWidget(label, row, 0)
        grid.addWidget(edit, row, 1)
        grid.addWidget(hint, row, 2)

    # --- user edits ----------------------------------------------------------------------
    def _toggled(self, dest: str, on: bool) -> None:
        if self._syncing:
            return
        self.model.set_active(dest, on)
        self.sync_from_model()
        self.changed.emit()

    def _edited(self, dest: str, text: str) -> None:
        if self._syncing:
            return
        self.model.set_text(dest, text)
        self._mark()
        self.changed.emit()

    def _voices_edited(self, dest: str) -> None:
        if self._syncing:
            return
        chosen = [v for v, cb in self.voice_boxes[dest].items() if cb.isChecked()]
        self.model.set_text(dest, ",".join(chosen))
        self._mark()
        self.changed.emit()

    # --- model -> widgets ----------------------------------------------------------------
    def sync_from_model(self) -> None:
        self._syncing = True
        try:
            for dest, edit in self.edits.items():
                text = self.model.text[dest]
                spec = self.model.spec(dest)
                if isinstance(edit, QComboBox):
                    edit.setCurrentText(text)
                elif isinstance(edit, QCheckBox):
                    edit.setChecked(text == "ja")
                elif isinstance(edit, QLineEdit):
                    edit.setText(text)
                elif spec.kind == "multi":
                    chosen = set(text.split(","))
                    for v, cb in self.voice_boxes[dest].items():
                        cb.setChecked(v in chosen)
                if dest in self.checks:
                    self.checks[dest].setChecked(dest in self.model.active)
        finally:
            self._syncing = False
        self._mark()

    def _mark(self) -> None:
        problems = self.model.field_issues()
        for dest, edit in self.edits.items():
            edit.setEnabled(dest in self.model.active)
            bad = dest in problems
            edit.setProperty("invalid", bad)
            edit.setToolTip(problems[dest] if bad else self.model.spec(dest).help)
            edit.style().unpolish(edit)
            edit.style().polish(edit)


class GoaPanel(QWidget):
    def __init__(
        self,
        base_dir: Path | None = None,
        service: GoaService | None = None,
        opener: Callable[[Path], bool] | None = None,
    ) -> None:
        super().__init__()
        self.setObjectName(BODY_HOOK)
        self.setStyleSheet(STYLE)
        self.service = service or GoaService()
        self.opener = opener or (lambda p: False)
        self.base_dir = Path(base_dir) if base_dir else default_output_dir() / "goa"
        self.models = {m: GoaFormModel(m) for m in MODES}
        self.mode = MODES[0]
        self.handle = None
        self._folder_auto = True
        self._signals = _Signals()
        self._signals.done.connect(self._on_done)
        self.result: GoaResult | None = None

        outer = QHBoxLayout(self)
        left = QVBoxLayout()
        self.mode_box = QComboBox()
        for m in MODES:
            self.mode_box.addItem(MODE_LABELS[m], m)
        self.mode_box.currentIndexChanged.connect(self._mode_changed)
        top = QFormLayout()
        top.addRow("Erzeuger", self.mode_box)
        left.addLayout(top)
        self.forms = {m: OptionForm(self.models[m]) for m in MODES}
        self.form_stack = QStackedWidget()
        for m in MODES:
            self.forms[m].changed.connect(self.refresh)
            self.form_stack.addWidget(self.forms[m])
        left.addWidget(self.form_stack, 1)
        left_box = QWidget()
        left_box.setLayout(left)
        left_box.setMinimumWidth(self.fontMetrics().horizontalAdvance("M") * 50)
        outer.addWidget(left_box, 3)

        right = QVBoxLayout()
        row = QHBoxLayout()
        row.addWidget(QLabel("Neuer Ordner"))
        self.folder_edit = QLineEdit()
        self.folder_edit.textEdited.connect(self._folder_typed)
        row.addWidget(self.folder_edit, 1)
        right.addLayout(row)
        buttons = QHBoxLayout()
        self.render_button = QPushButton("Rendern")
        self.render_button.setObjectName("primary")
        self.render_button.clicked.connect(self.start_render)
        self.open_button = QPushButton("Ordner öffnen")
        self.open_button.clicked.connect(self.open_folder)
        buttons.addWidget(self.render_button, 1)
        buttons.addWidget(self.open_button)
        right.addLayout(buttons)
        self.status = QLabel()
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        right.addWidget(self.status)

        self.tabs = QTabWidget()
        preview = QWidget()
        pv = QVBoxLayout(preview)
        self.summary = QLabel()
        self.summary.setObjectName("muted")
        self.summary.setWordWrap(True)
        self.summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        pv.addWidget(self.summary)
        self.timeline = TimelineWidget()
        pv.addWidget(self.timeline)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Start", "Takte", "Abschnitt", "Energie", "Spuren"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        pv.addWidget(self.table, 1)
        self.tabs.addTab(preview, "Vorschau")
        self.readme = QPlainTextEdit()
        self.readme.setReadOnly(True)
        self.readme.setPlaceholderText("Nach dem Rendern steht hier die README des Ordners.")
        self.tabs.addTab(self.readme, "README")
        right.addWidget(self.tabs, 1)
        self.note = QLabel(
            "Nichts davon ist in Live getestet oder angehört. Das Arrangement ist eine MIDI-"
            "Datei mit Beispiel-WAVs; du ziehst sie selbst in Live (Anleitung in der README).")
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        self.note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        right.addWidget(self.note)
        outer.addLayout(right, 4)
        self.refresh()

    # --- state ---------------------------------------------------------------------------
    @property
    def model(self) -> GoaFormModel:
        return self.models[self.mode]

    @property
    def running(self) -> bool:
        return self.handle is not None

    def set_base_dir(self, base: Path) -> None:
        self.base_dir = Path(base)
        self._auto_folder()

    def set_status(self, text: str, error: bool = False) -> None:
        self.status.setText(text)
        self.status.setProperty("level", "error" if error else "ok")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _mode_changed(self, _i: int) -> None:
        self.mode = self.mode_box.currentData()
        self.form_stack.setCurrentIndex(MODES.index(self.mode))
        self._folder_auto = True
        self.refresh()

    def _folder_typed(self, _t: str) -> None:
        self._folder_auto = False
        self.refresh()

    def _auto_folder(self) -> None:
        if self._folder_auto:
            name = self.model.suggested_folder_name()
            path, n = self.base_dir / name, 1
            while path.exists():  # a finished run is never overwritten: offer the next name
                n += 1
                path = self.base_dir / f"{name}_{n}"
            self.folder_edit.setText(str(path))

    def refresh(self) -> None:
        self._auto_folder()
        ev = self.model.evaluate()
        self.render_button.setEnabled(ev.ok and not self.running)
        if not self.running:
            if ev.ok:
                if self.status.property("level") == "error" and self.status.text().startswith(
                        "Rendern nicht möglich"):
                    self.set_status("")
            else:
                self.set_status("Rendern nicht möglich: " + ev.problem, error=True)
        self.show_plan(ev.plan)

    def show_plan(self, plan: TimelinePlan | None) -> None:
        self.timeline.set_plan(plan)
        self.table.setRowCount(0)
        if plan is None:
            self.summary.setText("Keine gültige Vorschau, solange die Optionen nicht stimmen.")
            return
        self.summary.setText(
            f"{plan.total_bars} Takte, etwa {plan.minutes:.1f} Minuten bei {plan.tempo:g} BPM, "
            f"Tonart {plan.key}. Spuren: {', '.join(plan.tracks)}. Aus den Plandaten des "
            "Erzeugers; angehört wurde nichts.")
        self.table.setRowCount(len(plan.sections))
        for r, s in enumerate(plan.sections):
            cells = [str(s.start_bar), str(s.bars), s.name, f"{s.energy:.2f}",
                     ", ".join(s.elements)]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c in (0, 1, 3):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                          | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()

    # --- render --------------------------------------------------------------------------
    def start_render(self) -> None:
        if self.running or not self.model.is_valid:
            return
        folder = self.folder_edit.text().strip()
        job = GoaJob(self.mode, tuple(self.model.argv(folder)))
        self.set_status("Rendern …")
        self.render_button.setEnabled(False)
        self.handle = self.service.start(job, on_done=self._signals.done.emit)

    def _on_done(self, result: GoaResult) -> None:
        self.handle = None
        self.result = result
        if result.error is not None:
            self.set_status(f"Fehler: {result.error.message}", error=True)
        else:
            self.readme.setPlainText(result.readme_text)
            self.tabs.setCurrentIndex(1)
            self.set_status(
                f"Fertig: {result.mid_path.name}, README"
                + (f" und {len(result.sample_paths)} Beispiel-WAV(s)" if result.sample_paths
                   else "") + f" in {result.out_dir}")
        self.refresh()

    def open_folder(self) -> None:
        folder = Path(self.folder_edit.text().strip())
        if not folder.is_dir() and self.result is not None and self.result.ok:
            folder = self.result.out_dir  # the last finished run
        if not folder.is_dir():
            self.set_status("Der Ordner existiert noch nicht (er entsteht beim Rendern).",
                            error=True)
            return
        if not self.opener(folder):
            self.set_status("Der Ordner konnte nicht geöffnet werden.", error=True)

    def shutdown(self) -> None:
        if self.handle is not None:
            self.handle.wait(30)
