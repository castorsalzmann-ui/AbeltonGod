"""Arrangement planner page (#139, D-024): style settings, energy curve with drawn nodes,
sections, element timeline, planner notes and the plan export into ``<Ausgabeordner>/Plans``.

State, planner calls and the export live in ``gui_core.planner``; this widget only shows them.
No Live writes, no model call."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui_core.paths import default_output_dir
from gui_core.planner import (
    BARS_RANGE,
    BPM_RANGE,
    GENRE_LABELS,
    SETTING_GROUPS,
    SETTING_SPECS,
    UNITS,
    ExportError,
    PlannerModel,
    export_plan,
    plans_dir,
    section_rows,
)

from .planner_curve import PlannerCanvas, event_summary
from .tool_style import STYLE
from .widgets import StepEdit, Stepper, heading, muted
from .widgets.choice import FlowLayout, WrapSegmented

MOUSE_HELP = ("Klick: Punkt setzen und ziehen · Standardpunkt anklicken: übernehmen · "
              "Shift+Klick auf Punkt: Stufe · Rechtsklick/Entf: löschen")


def points(n: int) -> str:
    return f"{n} gezeichneter Punkt" if n == 1 else f"{n} gezeichnete Punkte"


class PlannerPanel(QWidget):
    def __init__(self, output_root: Path | None = None,
                 opener: Callable[[Path], bool] | None = None) -> None:
        super().__init__()
        self.setObjectName("planner_body")
        self.setStyleSheet(STYLE)
        self.model = PlannerModel()
        self.output_root = Path(output_root) if output_root is not None else default_output_dir()
        self.opener = opener
        self.hub = None
        self.last_export: Path | None = None
        self.setting_edits: dict[str, QWidget] = {}
        em = self.fontMetrics().horizontalAdvance("M")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 4, 8, 8)
        intro = muted("Energie-Linie über die Abschnitte zeichnen (Punkte auf ganzen Takten). "
                      "Ergebnis ist nur eine "
                      "Plan-Datei (arrangement-plan v0.1); nichts wird an Live gesendet.")
        outer.addWidget(intro)

        top = QHBoxLayout()
        outer.addLayout(top)
        left = QWidget()
        left.setFixedWidth(em * 25)
        top.addWidget(left, 0, Qt.AlignmentFlag.AlignTop)
        form = QVBoxLayout(left)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(2)
        form.addWidget(heading("Track"))
        self.genre = WrapSegmented(list(GENRE_LABELS.values()))
        self.genre.setAccessibleName("Genre")
        self.genre.chosen.connect(self._genre_chosen)
        form.addWidget(self._row("Genre", self.genre))
        self.bpm_edit = StepEdit(self.model.bpm_text)
        self.bpm_edit.setAccessibleName("BPM")
        self.bpm_edit.setToolTip(f"Tempo, {BPM_RANGE[0]}-{BPM_RANGE[1]}")
        self.bpm_edit.edited.connect(self._bpm_edited)
        form.addWidget(self._row("BPM", self.bpm_edit))
        self.length_edit = StepEdit(self.model.length_text)
        self.length_edit.setAccessibleName("Länge")
        self.length_edit.setToolTip(f"Minuten oder Takte (Vielfaches von 8, "
                                    f"{BARS_RANGE[0]}-{BARS_RANGE[1]})")
        self.length_edit.edited.connect(self._length_edited)
        form.addWidget(self._row("Länge", self.length_edit))
        self.unit = WrapSegmented([label for _k, label in UNITS])
        self.unit.setAccessibleName("Einheit")
        self.unit.chosen.connect(self._unit_chosen)
        form.addWidget(self._row("Einheit", self.unit))
        for group in SETTING_GROUPS:
            form.addWidget(heading(group))
            for spec in (s for s in SETTING_SPECS if s.group == group):
                form.addWidget(self._row(spec.label, self._setting_editor(spec), spec.help))
        form.addStretch(1)

        right = QVBoxLayout()
        top.addLayout(right, 1)
        self.canvas = PlannerCanvas(self.model)
        self.canvas.edited.connect(self.refresh)
        right.addWidget(self.canvas)
        right.addWidget(muted(MOUSE_HELP))
        self.events_label = muted()
        right.addWidget(self.events_label)
        bar = QWidget()
        buttons = FlowLayout(bar)  # wraps on narrow pages and wide fonts (Windows, #139)
        self.clear_button = QPushButton("Gezeichnete Punkte löschen")
        self.clear_button.clicked.connect(self.clear_drawn)
        self.export_button = QPushButton("Plan exportieren")
        self.export_button.setObjectName("primary")
        self.export_button.clicked.connect(self.export)
        self.open_button = QPushButton("Plan-Ordner öffnen")
        self.open_button.clicked.connect(self.open_folder)
        buttons.addWidget(self.export_button)
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.clear_button)
        right.addWidget(bar)
        self.status = QLabel()
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        right.addWidget(self.status)
        right.addWidget(heading("Hinweise des Planers"))
        self.notes = muted()
        right.addWidget(self.notes)
        right.addWidget(heading("Abschnitte"))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Abschnitt", "Takte", "Länge", "Energie"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right.addWidget(self.table)
        self.folder_label = muted()
        right.addWidget(self.folder_label)
        right.addStretch(1)
        self.sync_from_model()
        self.refresh()

    # --- building ----------------------------------------------------------------------
    def _row(self, label: str, edit: QWidget, help_text: str = "") -> QWidget:
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        em = self.fontMetrics().horizontalAdvance("M")
        caption = QLabel(label)
        caption.setFixedWidth(em * 9)
        caption.setWordWrap(True)
        if help_text:
            caption.setToolTip(help_text)
            edit.setToolTip(help_text)
        lay.addWidget(caption, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(edit, 1)
        return box

    def _setting_editor(self, spec) -> QWidget:
        if spec.key == "change_grid":
            edit = Stepper(min(spec.values), max(spec.values))
            edit.setAccessibleName(spec.label)
            edit.valueChanged.connect(lambda v, k=spec.key: self._setting(k, v))
        else:
            edit = WrapSegmented(list(spec.labels))
            edit.setAccessibleName(spec.label)
            edit.chosen.connect(lambda i, s=spec: self._setting(s.key, s.values[i]))
        self.setting_edits[spec.key] = edit
        return edit

    # --- shared settings (output folder) -----------------------------------------------
    def attach_hub(self, hub) -> None:
        self.hub = hub
        hub.settings_changed.connect(self._settings_changed)
        self.set_output_root(hub.settings.output_root())

    def _settings_changed(self, settings) -> None:
        self.set_output_root(settings.output_root())

    def set_output_root(self, root: Path) -> None:
        self.output_root = Path(root)
        self.folder_label.setText(f"Ziel: {self.target_dir()}")

    def target_dir(self) -> Path:
        return plans_dir(self.output_root)

    # --- inputs ------------------------------------------------------------------------
    def sync_from_model(self) -> None:
        m = self.model
        self.genre.set_index(list(GENRE_LABELS).index(m.genre))
        self.unit.set_index([k for k, _l in UNITS].index(m.unit))
        for spec in SETTING_SPECS:
            edit, value = self.setting_edits[spec.key], m.settings[spec.key]
            if isinstance(edit, Stepper):
                edit.blockSignals(True)
                edit.setValue(value)
                edit.blockSignals(False)
            else:
                edit.set_index(spec.values.index(value))
        self.set_output_root(self.output_root)

    def _genre_chosen(self, index: int) -> None:
        self.model.genre = list(GENRE_LABELS)[index]
        self.refresh()

    def _unit_chosen(self, index: int) -> None:
        self.model.unit = UNITS[index][0]
        self.refresh()

    def _bpm_edited(self, text: str) -> None:
        self.model.bpm_text = text
        self.refresh()

    def _length_edited(self, text: str) -> None:
        self.model.length_text = text
        self.refresh()

    def _setting(self, key: str, value) -> None:
        self.model.set_setting(key, value)
        self.refresh()

    def clear_drawn(self) -> None:
        self.model.clear_drawn()
        self.canvas.selected = None
        self.refresh()

    # --- state -------------------------------------------------------------------------
    def set_status(self, text: str, error: bool = False) -> None:
        self.status.setText(text)
        self.status.setProperty("level", "error" if error else "ok")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def refresh(self) -> None:
        """Run the planner on the current inputs and show the result."""
        state = self.model.compute()
        self.bpm_edit.setProperty("invalid", state.total_bars == 0 and bool(state.errors))
        self.length_edit.setProperty("invalid", state.total_bars == 0 and bool(state.errors))
        for e in (self.bpm_edit, self.length_edit):
            e.style().unpolish(e)
            e.style().polish(e)
        self.export_button.setEnabled(state.ok)
        self.clear_button.setEnabled(bool(self.model.drawn))
        if state.ok:
            plan = state.plan
            minutes = plan["total_bars"] * 4 / plan["bpm"]
            drawn = len(self.model.drawn) - state.ignored_drawn
            text = (f"{plan['total_bars']} Takte, {minutes:.2f} min bei {plan['bpm']:g} BPM; "
                    f"{len(plan['sections'])} Abschnitte, {points(drawn)}.")
            if state.ignored_drawn:
                text += (f" {points(state.ignored_drawn)} hinter dem Ende (oder zweite Stufe "
                         "am Ende) nicht verwendet.")
            self.set_status(text)
        else:
            self.set_status("Kein Plan: " + " ".join(state.errors), error=True)
        self.notes.setText("\n".join(state.notes) if state.notes else "Keine.")
        self.events_label.setText("Events: " + (event_summary(self.model) or "keine"))
        rows = section_rows(state)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                item = QTableWidgetItem(str(value))
                if c:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, c, item)
        rh = self.table.verticalHeader().defaultSectionSize()
        self.table.setFixedHeight(self.table.horizontalHeader().height() + rh * len(rows) + 4)
        self.canvas.update()

    # --- export ------------------------------------------------------------------------
    def export(self) -> Path | None:
        state = self.model.state
        if state.plan is None:
            return None
        try:
            path = export_plan(state.plan, self.target_dir(), self.model.genre)
        except ExportError as exc:
            self.set_status(f"Plan verletzt das Format, nicht geschrieben: {exc}", error=True)
            return None
        except OSError as exc:
            self.set_status(f"Plan nicht geschrieben: {exc}", error=True)
            return None
        self.last_export = path
        self.set_status(f"Plan geschrieben: {path}")
        return path

    def open_folder(self) -> None:
        folder = self.target_dir()
        if not folder.is_dir():
            self.set_status("Der Plan-Ordner existiert noch nicht (er entsteht beim Export).",
                            error=True)
            return
        if self.opener is None or not self.opener(folder):
            self.set_status("Der Ordner konnte nicht geöffnet werden.", error=True)
