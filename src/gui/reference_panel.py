""""Referenz" page (#480): pick a kick WAV, show its measures next to the nearest candidate,
hand the candidate's values to the kick form. Logic in ``gui_core.reference``; the
measurement runs in a worker thread."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
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

from gui_core.reference import (
    INTRO,
    LIMITS,
    ROWS,
    ReferenceOutcome,
    analyse_reference,
    candidate_text,
    file_text,
    table_rows,
)
from gui_core.tasks import TaskHandle, start_task

from .tool_style import STYLE
from .widgets import heading

BODY_HOOK = "reference_body"
HEADERS = ("Messwert", "Referenz", "Kandidat", "Abstand")


class _Signals(QObject):
    done = Signal(object)


def _muted(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
    return label


class ReferencePanel(QWidget):
    # the nearest Candidate; the main window puts it into the kick form
    apply_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName(BODY_HOOK)
        self.setStyleSheet(STYLE)
        self.setAcceptDrops(True)
        self.busy = False
        self.outcome: ReferenceOutcome | None = None
        self.handle: TaskHandle | None = None
        self.last_dir = ""
        self._signals = _Signals()
        self._signals.done.connect(self._on_done)

        lay = QVBoxLayout(self)
        lay.addWidget(heading("Referenz"))
        lay.addWidget(_muted(INTRO))
        row = QHBoxLayout()
        self.pick_button = QPushButton("WAV wählen …")
        self.pick_button.clicked.connect(self.pick_file)
        row.addWidget(self.pick_button)
        self.file_label = _muted("Noch keine Datei.")
        row.addWidget(self.file_label, 1)
        lay.addLayout(row)

        self.table = QTableWidget(len(ROWS), len(HEADERS))
        self.table.setHorizontalHeaderLabels(list(HEADERS))
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, len(HEADERS)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        for i, (_, label, _, _) in enumerate(ROWS):
            self.table.setItem(i, 0, QTableWidgetItem(label))
            for col in range(1, len(HEADERS)):
                self.table.setItem(i, col, QTableWidgetItem("–"))
        rows_h = self.table.verticalHeader().length() + header.height() + 4
        self.table.setMinimumHeight(rows_h)
        self.table.setMaximumHeight(rows_h)
        lay.addWidget(self.table)

        self.candidate_label = _muted()
        lay.addWidget(self.candidate_label)
        self.apply_button = QPushButton("Als Startwerte übernehmen")
        self.apply_button.setObjectName("primary")
        self.apply_button.setToolTip("Lädt das Preset des Kandidaten und seine Werte ins "
                                     "Kick-Formular und wechselt dorthin; gerendert wird erst "
                                     "mit „Rendern“.")
        self.apply_button.clicked.connect(self.apply)
        lay.addWidget(self.apply_button)
        self.status = _muted()
        self.status.setObjectName("status")
        lay.addWidget(self.status)
        lay.addWidget(_muted(LIMITS))
        lay.addStretch(1)
        self._update_state()

    # --- input ---------------------------------------------------------------------------------
    def pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Referenz-WAV wählen", self.last_dir,
                                              "WAV-Dateien (*.wav *.WAV)")
        if path:
            self.analyse(Path(path))

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt name
        if self._dropped_path(event.mimeData()) is not None and not self.busy:
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt name
        path = self._dropped_path(event.mimeData())
        if path is not None and self.analyse(path):
            event.acceptProposedAction()

    @staticmethod
    def _dropped_path(mime) -> Path | None:
        if not mime.hasUrls():
            return None
        locals_ = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]
        return Path(locals_[0]) if len(locals_) == 1 else None

    def analyse(self, path: Path) -> bool:
        """Start the measurement of ``path`` in a worker thread; False while one runs."""
        if self.busy:
            return False
        self.busy = True
        self.outcome = None
        self.last_dir = str(path.parent)
        self.file_label.setText(path.name)
        self._set_status(f"Misst {path.name} … (beim ersten Mal werden die Kandidaten "
                         "gerendert, ein paar Sekunden)")
        self._update_state()
        self.handle = start_task(lambda: analyse_reference(path),
                                 lambda h: self._signals.done.emit(h.result), "reference")
        return True

    # --- result --------------------------------------------------------------------------------
    def _on_done(self, outcome: ReferenceOutcome | None) -> None:
        self.busy = False
        self.handle = None
        self.outcome = outcome
        if outcome is None or not outcome.ok:
            self._clear()
            text = outcome.error if outcome is not None else "Analyse fehlgeschlagen."
            self._set_status(text, error=True)
        else:
            match = outcome.match
            for i, cells in enumerate(table_rows(match)):
                for col, text in enumerate(cells):
                    self.table.item(i, col).setText(text)
            self.file_label.setText(file_text(match, outcome.path))
            self.candidate_label.setText(candidate_text(match))
            self._set_status("Gemessen. „Als Startwerte übernehmen“ lädt den Kandidaten ins "
                             "Kick-Formular.")
        self._update_state()

    def _clear(self) -> None:
        for i in range(len(ROWS)):
            for col in range(1, len(HEADERS)):
                self.table.item(i, col).setText("–")
        self.candidate_label.setText("")

    def apply(self) -> None:
        if self.outcome is not None and self.outcome.ok and not self.busy:
            self.apply_requested.emit(self.outcome.match.nearest)

    def _set_status(self, text: str, error: bool = False) -> None:
        self.status.setText(text)
        self.status.setProperty("level", "error" if error else "ok")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _update_state(self) -> None:
        self.pick_button.setEnabled(not self.busy)
        self.apply_button.setEnabled(not self.busy and self.outcome is not None
                                     and self.outcome.ok)

    def shutdown(self) -> None:
        """Window closes: a running measurement must not call back into deleted widgets."""
        if self.handle is not None:
            self.handle.wait(10)
