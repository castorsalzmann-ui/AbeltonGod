"""Goa page: option form for the arrangement and melody generators, section preview, render.

State and checks live in ``gui_core.goa``; the generator runs in ``gui_core.goa_render``. This
widget only shows them."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
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

from audio_engine import goa_patterns
from gui_core.form import FieldSpec, parse_number
from gui_core.goa import GROUPS, MODE_LABELS, MODES, GoaFormModel, OptionSpec, TimelinePlan
from gui_core.goa_render import GoaJob, GoaResult, GoaService
from gui_core.paths import default_output_dir

from .timeline_widget import TimelineWidget
from .tool_style import STYLE
from .widgets import (
    ActiveDot,
    NumberControl,
    PresetChips,
    Segmented,
    StepEdit,
    Toggle,
    heading,
    muted,
)

BODY_HOOK = "goa_body"  # objectName of the page body: a hook for later skins/extra panels


class _Signals(QObject):
    done = Signal(object)


class OptionForm(QScrollArea):
    """One mode's options, built from the widget kit. ``edits[dest]`` is the editing widget:
    ``NumberControl`` (bpm), ``Segmented`` / ``PresetChips`` (choices, voices), ``Toggle``
    (flags) or ``StepEdit`` / ``QLineEdit`` (numbers and texts the generator checks itself).
    ``checks[dest]`` is the dot of an optional option (sent only when on)."""

    changed = Signal()

    def __init__(self, model: GoaFormModel) -> None:
        super().__init__()
        self.model = model
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.edits: dict[str, QWidget] = {}
        self.checks: dict[str, ActiveDot] = {}
        self.hints: dict[str, QLabel] = {}
        self._syncing = False
        root = QWidget()
        root.setObjectName("root")
        lay = QVBoxLayout(root)
        lay.setContentsMargins(8, 4, 12, 16)
        lay.setSpacing(6)
        self.setWidget(root)
        for group in GROUPS:
            specs = [s for s in model.specs if s.group == group]
            if not specs:
                continue
            lay.addWidget(heading(group))
            for spec in specs:
                lay.addWidget(self._row(spec))
        lay.addStretch(1)
        self.sync_from_model()

    def _row(self, spec: OptionSpec) -> QWidget:
        em = self.fontMetrics().horizontalAdvance("M")
        edit = self._editor(spec)
        edit.setToolTip(spec.help)
        self.edits[spec.dest] = edit
        if isinstance(edit, NumberControl):
            edit.setFixedWidth(16777215)
            return edit  # brings its own label
        box = QWidget()
        outer = QVBoxLayout(box)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        dot = ActiveDot()
        policy = dot.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        dot.setSizePolicy(policy)
        if spec.optional:
            dot.toggled.connect(lambda on, d=spec.dest: self._toggled(d, on))
            self.checks[spec.dest] = dot
        else:
            dot.hide()
        label = QLabel(spec.label)
        label.setToolTip(spec.help)
        label.setFixedWidth(em * 15)
        label.setFixedHeight(int(self.fontMetrics().height() * 1.9))  # first line of the editor
        top = Qt.AlignmentFlag.AlignTop
        row.addWidget(dot, 0, top)
        row.addWidget(label, 0, top)
        is_number = isinstance(edit, StepEdit)
        if is_number:
            edit.setFixedWidth(em * 12)
            row.setSpacing(8)
        row.addWidget(edit, 0 if is_number else 1, top)
        hint = muted(spec.range_text if isinstance(edit, StepEdit | QLineEdit) else "")
        hint.setVisible(isinstance(edit, StepEdit | QLineEdit))
        self.hints[spec.dest] = hint
        if is_number:
            row.addWidget(hint, 1)
            outer.addLayout(row)
        else:
            outer.addLayout(row)
            outer.addWidget(hint)
        return box

    def _editor(self, spec: OptionSpec) -> QWidget:
        if spec.kind == "flag":
            tg = Toggle()
            tg.toggled.connect(lambda on, d=spec.dest: self._edited(d, "ja" if on else "nein"))
            tg.setAccessibleName(spec.label)
            return tg
        if spec.kind == "multi":
            chips = PresetChips(list(spec.choices), multi=True)
            chips.changed.connect(lambda sel, d=spec.dest: self._edited(d, ",".join(sel)))
            chips.setAccessibleName(spec.label)
            return chips
        if spec.kind == "enum":
            if len(spec.choices) <= 4 and max(len(c) for c in spec.choices) <= 8:
                seg = Segmented(list(spec.choices))
                seg.chosen.connect(
                    lambda i, d=spec.dest, s=spec: self._edited(d, s.choices[i]))
                seg.setAccessibleName(spec.label)
                return seg
            chips = PresetChips(list(spec.choices))
            chips.chosen.connect(lambda text, d=spec.dest: self._edited(d, text))
            chips.setAccessibleName(spec.label)
            return chips
        if spec.dest == "bpm":
            fs = FieldSpec(
                name="bpm", label=spec.label, kind="float", minimum=goa_patterns.MIN_BPM,
                maximum=goa_patterns.MAX_BPM, default=None, choices=(), unit="BPM",
                description=spec.help)
            c = NumberControl(fs, style="row", always_active=True)
            c.edited.connect(lambda _n, v, d=spec.dest: self._edited(d, f"{v:g}"))
            return c
        if spec.kind in ("int", "float"):
            se = StepEdit()
            se.edited.connect(lambda text, d=spec.dest: self._edited(d, text))
            se.setAccessibleName(spec.label)
            return se
        le = QLineEdit()
        le.textEdited.connect(lambda text, d=spec.dest: self._edited(d, text))
        le.setAccessibleName(spec.label)
        return le

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
        if dest in self.checks and not self.checks[dest].isChecked():
            self.model.set_active(dest, True)  # touching an optional value sends it
        self._mark()
        self.changed.emit()

    # --- model -> widgets ----------------------------------------------------------------
    def sync_from_model(self) -> None:
        self._syncing = True
        try:
            for dest, edit in self.edits.items():
                text = self.model.text[dest]
                spec = self.model.spec(dest)
                if isinstance(edit, NumberControl):
                    number = parse_number(text)
                    if number is not None:
                        edit.set_value(number)
                elif isinstance(edit, Segmented):
                    edit.set_index(spec.choices.index(text) if text in spec.choices else -1)
                elif isinstance(edit, PresetChips) and edit.multi:
                    edit.set_selected([v for v in text.split(",") if v])
                elif isinstance(edit, PresetChips):
                    edit.set_current(text)
                elif isinstance(edit, Toggle):
                    edit.setChecked(text == "ja")
                elif isinstance(edit, QLineEdit) and edit.text() != text:
                    edit.setText(text)
                if dest in self.checks:
                    self.checks[dest].setChecked(dest in self.model.active)
        finally:
            self._syncing = False
        self._mark()

    def _mark(self) -> None:
        problems = self.model.field_issues()
        for dest, edit in self.edits.items():
            active = dest in self.model.active
            edit.setEnabled(active)
            bad = dest in problems
            if isinstance(edit, QLineEdit) and bool(edit.property("invalid")) != bad:
                edit.setProperty("invalid", bad)
                edit.style().unpolish(edit)
                edit.style().polish(edit)
            edit.setToolTip(problems[dest] if bad else self.model.spec(dest).help)
            if dest in self.hints and isinstance(edit, QLineEdit):
                spec = self.model.spec(dest)
                self.hints[dest].setText(problems[dest] if bad else spec.range_text)


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
        left.addWidget(heading("Erzeuger"))
        self.mode_seg = Segmented([MODE_LABELS[m] for m in MODES], accent=True)
        self.mode_seg.set_index(0)
        self.mode_seg.chosen.connect(lambda i: self.set_mode(MODES[i]))
        left.addWidget(self.mode_seg)
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

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.mode_seg.set_index(MODES.index(mode))
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
