"""Library page: lists the WAVs of the output folder with their sidecar data. Scanning,
reading and filtering are gui_core.library; this widget only shows them.

Choice log (#110): "Favorit" / "Passt nicht" (with an optional note) append one entry for the
selected WAV to the choice log (gui_core.choices); rows show the current verdict, "nur
Favoriten" keeps the current favourites, and a small list shows the newest log entries.

Kit export (#498): the closed section "Kit erstellen" picks one WAV per slot (prefilled from the
favourites, newest first) and copies them with their sidecars and a kit.json into
<Ausgabeordner>/Samples/Kits/<Name>/ (gui_core.kit). Files only, nothing goes to Live."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from gui_core import kit as kitcore
from gui_core.categories import CATEGORIES
from gui_core.choices import (
    LABELS,
    MAX_NOTE,
    ChoiceError,
    ChoiceLog,
    current_verdicts,
    known_sha256,
    make_entry,
)
from gui_core.library import MAX_FILES, UNREADABLE, LibraryEntry, filter_entries, scan

from .drag import PATH_ROLE, DragList
from .widgets import Collapsible

MARKS = {"favourite": "★ ", "reject": "✗ "}
LOG_ROWS = 50  # newest log entries shown


class LibraryPanel(QWidget):
    selected = Signal(object)  # Path of the selected WAV

    def __init__(self, choices: ChoiceLog | None = None) -> None:
        super().__init__()
        self.entries: list[LibraryEntry] = []
        self.truncated = False
        self.folder = Path()
        self.choices = choices or ChoiceLog()
        self.verdicts: dict[str, dict] = {}  # sha256 -> entry with the current verdict
        self._sha_cache: dict = {}
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
        self.only_favourites = QCheckBox("nur Favoriten")
        refresh = QPushButton("Aktualisieren")
        row.addWidget(self.category_box)
        row.addWidget(self.search, 1)
        row.addWidget(self.only_favourites)
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

        judge = QHBoxLayout()
        self.note = QLineEdit()
        self.note.setPlaceholderText("Notiz (optional)")
        self.note.setMaxLength(MAX_NOTE)
        self.note.setClearButtonEnabled(True)
        self.favourite_button = QPushButton("Favorit")
        self.reject_button = QPushButton("Passt nicht")
        judge.addWidget(self.note, 1)
        judge.addWidget(self.favourite_button)
        judge.addWidget(self.reject_button)
        lay.addLayout(judge)
        self.choice_info = QLabel()
        self.choice_info.setObjectName("muted")
        self.choice_info.setWordWrap(True)
        lay.addWidget(self.choice_info)
        self.log_view = QListWidget()
        self.log_view.setObjectName("choices_log")
        self.log_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.log_view.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.log_view.setMaximumHeight(5 * self.fontMetrics().height() + 12)
        lay.addWidget(self.log_view)
        lay.addWidget(self._build_kit())

        refresh.clicked.connect(self.refresh)
        self.category_box.currentIndexChanged.connect(self._show)
        self.search.textChanged.connect(self._show)
        self.only_favourites.toggled.connect(self._show)
        self.list.currentItemChanged.connect(self._picked)
        self.favourite_button.clicked.connect(lambda: self.judge("favourite"))
        self.reject_button.clicked.connect(lambda: self.judge("reject"))
        self._load_choices()
        self._fill_kit()
        self._update_buttons()

    def set_folder(self, folder: Path) -> None:
        self.folder = Path(folder)
        self.refresh()

    def refresh(self) -> None:
        res = scan(self.folder)
        self.entries, self.truncated = res.entries, res.truncated
        self._load_choices()
        self._show()
        self._fill_kit()

    def verdict_of(self, wav: Path) -> str | None:
        """Current verdict of a listed WAV, or None when the log has none for its bytes."""
        if not self.verdicts:
            return None
        sha = known_sha256(Path(wav), self._sha_cache)
        entry = self.verdicts.get(sha) if sha else None
        return entry["verdict"] if entry else None

    def _show(self) -> None:
        current = self.current_path()
        shown = filter_entries(
            self.entries, self.category_box.currentData(), self.search.text()
        )
        if self.only_favourites.isChecked():
            shown = [e for e in shown if self.verdict_of(e.wav_path) == "favourite"]
        self.list.blockSignals(True)
        self.list.clear()
        for e in shown:
            mark = MARKS.get(self.verdict_of(e.wav_path) or "", "")
            if e.readable:
                first = f"{mark}{e.name}   {e.category} · {e.preset or '-'} · Seed {e.seed}"
                second = "   ".join(p for p in (e.key_params, e.created_at.replace("T", " ")) if p)
                text = f"{first}\n{second}" if second else first
            else:
                text = f"{mark}{e.name}   {UNREADABLE} ({e.problem})"
            item = QListWidgetItem(text)
            item.setData(PATH_ROLE, str(e.wav_path))
            self.list.addItem(item)
            if current is not None and Path(current) == e.wav_path:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        text = (f"{len(shown)} von {len(self.entries)} Dateien in {self.folder}"
                if self.entries else f"Keine WAV-Dateien in {self.folder}")
        if self.truncated:
            text += (f". Suche nach {MAX_FILES} Dateien angehalten (nach Ordner und Name, "
                     "nicht nach Datum); für den Rest einen kleineren Ordner wählen.")
        self.info.setText(text)
        self._update_buttons()

    def current_path(self) -> Path | None:
        item = self.list.currentItem()
        return Path(item.data(PATH_ROLE)) if item is not None else None

    def _picked(self, item: QListWidgetItem | None, _prev=None) -> None:
        self._update_buttons()
        if item is not None:
            self.selected.emit(Path(item.data(PATH_ROLE)))

    def _update_buttons(self) -> None:
        on = self.list.currentItem() is not None
        self.favourite_button.setEnabled(on)
        self.reject_button.setEnabled(on)

    # --- choice log ----------------------------------------------------------------------

    def judge(self, verdict: str) -> bool:
        """Append ``verdict`` (with the note) for the selected WAV. False and a message in
        ``choice_info`` when nothing is selected or the entry cannot be written."""
        wav = self.current_path()
        if wav is None:
            self.choice_info.setText("Erst eine Datei in der Liste wählen.")
            return False
        try:
            self.choices.append(make_entry(wav, self.folder, verdict, self.note.text()))
        except ChoiceError as exc:
            self.choice_info.setText(f"Nicht gespeichert: {exc}")
            return False
        except OSError as exc:
            self.choice_info.setText(
                f"Nicht gespeichert ({type(exc).__name__}) in {self.choices.location}")
            return False
        self.note.clear()
        self._load_choices(f"{LABELS[verdict]}: {wav.name} gespeichert.")
        self._show()
        self._fill_kit()
        return True

    def _load_choices(self, done: str = "") -> None:
        res = self.choices.read()
        self.verdicts = current_verdicts(res.entries)
        self.log_view.clear()
        for e in reversed(res.entries[-LOG_ROWS:]):
            when = e["time"].replace("T", " ")[:16]
            name = e["sample"]["path"].rsplit("/", 1)[-1]
            note = f" · {e['note']}" if "note" in e else ""
            self.log_view.addItem(f"{when} · {LABELS[e['verdict']]} · {name}{note}")
        parts = [done] if done else []
        if res.error:
            parts.append(res.error)
        parts.append(f"Auswahl-Log: {len(res.entries)} Einträge ({self.choices.location})")
        if res.skipped:
            parts.append(f"{res.skipped} fehlerhafte Zeilen übersprungen")
        self.choice_info.setText(". ".join(parts) + ".")

    # --- kit export (#498) -----------------------------------------------------------------

    def _build_kit(self) -> Collapsible:
        self.kit_section = Collapsible("Kit erstellen")
        inner = QWidget()
        grid = QGridLayout(inner)
        grid.setContentsMargins(0, 0, 0, 0)
        self.kit_boxes: dict[str, QComboBox] = {}
        for row, slot in enumerate(kitcore.SLOTS):
            box = QComboBox()
            box.setAccessibleName(f"Kit {slot.label}")
            box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            box.setMinimumContentsLength(12)
            grid.addWidget(QLabel(slot.label), row, 0)
            grid.addWidget(box, row, 1)
            self.kit_boxes[slot.key] = box
        grid.setColumnStretch(1, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(inner)
        # The slot list scrolls instead of growing the page (fits 1920 x 1080 at 150 %, #442).
        scroll.setMaximumHeight(9 * self.fontMetrics().height() + 12)
        body = QVBoxLayout(self.kit_section.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.addWidget(scroll)
        row = QHBoxLayout()
        self.kit_name = QLineEdit()
        self.kit_name.setPlaceholderText("Kit-Name")
        self.kit_name.setAccessibleName("Kit-Name")
        self.kit_name.setMaxLength(80)
        self.kit_prefill_button = QPushButton("Aus Favoriten")
        self.kit_export_button = QPushButton("Kit exportieren")
        row.addWidget(self.kit_name, 1)
        row.addWidget(self.kit_prefill_button)
        row.addWidget(self.kit_export_button)
        body.addLayout(row)
        self.kit_info = QLabel("Kopiert die Dateien mit Sidecars und kit.json nach "
                               "Samples/Kits/<Name>; nichts geht an Live.")
        self.kit_info.setObjectName("muted")
        self.kit_info.setWordWrap(True)
        body.addWidget(self.kit_info)
        self.kit_prefill_button.clicked.connect(self.prefill_kit)
        self.kit_export_button.clicked.connect(self.export_kit)
        return self.kit_section

    def kit_picks(self) -> dict[str, Path | None]:
        return {k: (Path(b.currentData()) if b.currentData() else None)
                for k, b in self.kit_boxes.items()}

    def _sha_of(self, wav: Path) -> str | None:
        return known_sha256(Path(wav), self._sha_cache)

    def _fill_kit(self) -> None:
        """Re-list the candidates per slot, keeping the current picks; when nothing is picked
        yet, prefill from the favourites."""
        keep = self.kit_picks()
        fav = {sha for sha, e in self.verdicts.items() if e["verdict"] == "favourite"}
        for slot in kitcore.SLOTS:
            box = self.kit_boxes[slot.key]
            box.blockSignals(True)
            box.clear()
            box.addItem("(keine)", None)
            for e in kitcore.candidates(slot, self.entries, self.folder):
                mark = "★ " if fav and self._sha_of(e.wav_path) in fav else ""
                box.addItem(f"{mark}{e.name}", str(e.wav_path))
            want = keep[slot.key]
            i = box.findData(str(want)) if want is not None else -1
            box.setCurrentIndex(max(i, 0))
            box.blockSignals(False)
        if not any(self.kit_picks().values()):
            self.prefill_kit()

    def prefill_kit(self) -> None:
        picks = kitcore.prefill(self.entries, self.choices.read().entries, self.folder,
                                self._sha_of)
        for key, wav in picks.items():
            box = self.kit_boxes[key]
            box.setCurrentIndex(max(box.findData(str(wav)), 0) if wav is not None else 0)

    def export_kit(self) -> Path | None:
        """Export the picked kit. Returns the new kit folder, or None with the reason in
        ``kit_info`` (nothing is left behind on failure)."""
        try:
            plan = kitcore.plan_kit(self.folder, self.kit_name.text(), self.kit_picks())
            folder = kitcore.export_kit(plan)
        except kitcore.KitError as exc:
            self.kit_info.setText(f"Kein Kit erstellt: {exc}")
            return None
        except OSError as exc:
            self.kit_info.setText(f"Kein Kit erstellt ({type(exc).__name__}: {exc.strerror or exc})"
                                  "; nichts wurde hinterlassen.")
            return None
        self.refresh()
        self.kit_info.setText(f"Kit gespeichert: {folder} ({len(plan.items)} Dateien).")
        return folder
