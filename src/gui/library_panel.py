"""Library page: lists the WAVs of the output folder with their sidecar data. Scanning,
reading and filtering are gui_core.library; this widget only shows them."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui_core.categories import CATEGORIES
from gui_core.library import UNREADABLE, LibraryEntry, filter_entries, scan_library

from .drag import PATH_ROLE, DragList


class LibraryPanel(QWidget):
    selected = Signal(object)  # Path of the selected WAV

    def __init__(self) -> None:
        super().__init__()
        self.entries: list[LibraryEntry] = []
        self.folder = Path()
        lay = QVBoxLayout(self)
        head = QLabel("Bibliothek")
        head.setObjectName("heading")
        lay.addWidget(head)
        row = QHBoxLayout()
        self.category_box = QComboBox()
        self.category_box.addItem("Alle Kategorien", None)
        for c in CATEGORIES:
            self.category_box.addItem(c.label, c.key)
        self.category_box.addItem("Unlesbar", UNREADABLE)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Suchen (Name, Preset, Seed …)")
        self.search.setClearButtonEnabled(True)
        refresh = QPushButton("Aktualisieren")
        row.addWidget(self.category_box)
        row.addWidget(self.search, 1)
        row.addWidget(refresh)
        lay.addLayout(row)
        self.info = QLabel()
        self.info.setObjectName("muted")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.list = DragList()
        self.list.setObjectName("library")
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        lay.addWidget(self.list, 1)
        hint = QLabel("Zeilen lassen sich als WAV-Datei aus dem Fenster ziehen.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        refresh.clicked.connect(self.refresh)
        self.category_box.currentIndexChanged.connect(self._show)
        self.search.textChanged.connect(self._show)
        self.list.currentItemChanged.connect(self._picked)

    def set_folder(self, folder: Path) -> None:
        self.folder = Path(folder)
        self.refresh()

    def refresh(self) -> None:
        self.entries = scan_library(self.folder)
        self._show()

    def _show(self) -> None:
        shown = filter_entries(
            self.entries, self.category_box.currentData(), self.search.text()
        )
        self.list.clear()
        for e in shown:
            if e.readable:
                first = f"{e.name}   {e.category} · {e.preset or '-'} · Seed {e.seed}"
                second = "   ".join(p for p in (e.key_params, e.created_at.replace("T", " ")) if p)
                text = f"{first}\n{second}" if second else first
            else:
                text = f"{e.name}   {UNREADABLE} ({e.problem})"
            item = QListWidgetItem(text)
            item.setData(PATH_ROLE, str(e.wav_path))
            self.list.addItem(item)
        self.info.setText(
            f"{len(shown)} von {len(self.entries)} Dateien in {self.folder}"
            if self.entries else f"Keine WAV-Dateien in {self.folder}"
        )

    def _picked(self, item: QListWidgetItem | None, _prev=None) -> None:
        if item is not None:
            self.selected.emit(Path(item.data(PATH_ROLE)))
