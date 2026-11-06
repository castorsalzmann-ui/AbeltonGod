"""Main window: category list, kick panel, results with preview. No logic of its own."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from bridge.capabilities import CapabilityRegistry
from gui_core.categories import CATEGORIES, LIBRARY_LABEL
from gui_core.chat import ChatSession
from gui_core.form import CategoryFormModel
from gui_core.goa_render import GoaService
from gui_core.live import LiveConfig
from gui_core.preview import ERROR, PLAYING, PlaybackBackend, PreviewController
from gui_core.render import RenderHandle, RenderJob, RenderResult, RenderService
from gui_core.settings import SettingsStore, apply_format_to_form

from .audio import choose_backend
from .category_panel import CategoryPanel
from .chat_panel import ChatPanel
from .drag import PATH_ROLE, DragList
from .goa_panel import GoaPanel
from .library_panel import LibraryPanel
from .live_panel import LivePanel
from .waveform_widget import WaveformWidget
from .windows import (
    WINDOW_KEYS,
    AppHub,
    SettingsDialog,
    WindowManager,
    restore_state,
    window_state,
)

# Pages after the sample categories and the library (left list order).
TOOL_PAGES = (("goa", "Goa-Arrangement"), ("live", "Live-Import"), ("chat", "Copilot"))


class _Bridge(QObject):
    """Carries worker-thread callbacks to the GUI thread (queued signals)."""

    progress = Signal(int, int)
    done = Signal(object)


def open_in_file_manager(path: Path) -> bool:
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class MainWindow(QMainWindow):
    def __init__(
        self,
        out_dir: Path | None = None,
        service: RenderService | None = None,
        backend: PlaybackBackend | None = None,
        opener: Callable[[Path], bool] = open_in_file_manager,
        goa_service: GoaService | None = None,
        live_config: LiveConfig | None = None,
        registry: CapabilityRegistry | None = None,
        chat_session: ChatSession | None = None,
        window_factories: dict[str, Callable[[Path], QWidget]] | None = None,
        settings_store: SettingsStore | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("AbeltonGod")
        # One settings object for this window and every tool window. Without a store it lives
        # in memory only (tests, selftest); gui.app passes the one in the user config dir.
        self.hub = AppHub(settings_store or SettingsStore())
        if out_dir is not None:
            self.hub.store.update(output_dir=str(out_dir))
        self.windows = WindowManager(self._library_folder, window_factories, self.hub)
        self.service = service or RenderService()
        self.preview = PreviewController(backend or choose_backend())
        self.opener = opener
        self.models = {c.key: CategoryFormModel(c.key) for c in CATEGORIES}
        for m in self.models.values():
            apply_format_to_form(m, self.hub.settings)
        self._format = {"sample_rate": self.hub.settings.sample_rate,
                        "bit_depth": self.hub.settings.bit_depth}  # what the forms were given
        self.form_key = CATEGORIES[0].key  # the category whose form Render uses
        self.on_library = False
        self.on_tool = False  # Goa, Live or chat page: the render column is not used
        self.handle: RenderHandle | None = None
        self._bridge = _Bridge()
        self._bridge.progress.connect(self._on_progress)
        self._bridge.done.connect(self._on_done)
        self.result_paths: list[Path] = []

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)

        self.categories = QListWidget()
        self.categories.setObjectName("categories")
        for entry in (*CATEGORIES, None, *TOOL_PAGES):
            if isinstance(entry, tuple):
                label = entry[1]
            else:
                label = LIBRARY_LABEL if entry is None else entry.label
            plain = entry is None or isinstance(entry, tuple)
            text = label if plain or entry.enabled else f"{label}  ({entry.note})"
            item = QListWidgetItem(text)
            item.setSizeHint(QSize(0, self.fontMetrics().height() * 2))
            if not plain and not entry.enabled:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.categories.addItem(item)
        m = self.fontMetrics().horizontalAdvance("M")  # layout in font units: follows the DPI
        self.categories.setFixedWidth(m * 20)
        left = QVBoxLayout()
        left.addWidget(self.categories, 1)
        left.addWidget(self._build_window_buttons())
        outer.addLayout(left)

        split = QSplitter()
        split.setChildrenCollapsible(False)
        outer.addWidget(split, 1)
        self.stack = QStackedWidget()
        self.stack.setMinimumWidth(m * 50)  # five knobs (9 m each) plus the page margins
        self.panels: dict[str, CategoryPanel] = {}
        for c in CATEGORIES:
            panel = CategoryPanel(self.models[c.key])
            panel.changed.connect(self._update_state)
            self.panels[c.key] = panel
            self.stack.addWidget(panel)
        self.library = LibraryPanel()
        self.library.selected.connect(self._load_preview)
        self.stack.addWidget(self.library)
        self.library_row = len(CATEGORIES)
        self.goa = GoaPanel(self.hub.settings.goa_dir(), goa_service, opener)
        self.goa.attach_hub(self.hub)
        self.live = LivePanel(live_config, registry, self._library_folder)
        self.chat = ChatPanel(chat_session)
        self.tool_rows = {}
        for key, widget in (("goa", self.goa), ("live", self.live), ("chat", self.chat)):
            self.tool_rows[key] = self.stack.count()
            self.stack.addWidget(widget)
        split.addWidget(self.stack)
        right = self._build_right()
        right.setMinimumWidth(m * 38)
        self.right = right
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)

        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self._tick)
        self.library.folder = Path(self.folder_edit.text().strip() or ".")
        self.categories.currentRowChanged.connect(self.show_page)
        self.categories.setCurrentRow(0)
        self._update_state()
        self.resize(m * 112, self.fontMetrics().height() * 42)
        restore_state(self, self.hub.settings.windows.get("main"))
        self.hub.show_requested.connect(self.show_in_library)
        self.hub.live_requested.connect(self.send_to_live)
        self.hub.files_written.connect(self._on_files_written)
        self.hub.settings_changed.connect(self._on_settings_changed)
        self.settings_dialog: SettingsDialog | None = None

    def _build_window_buttons(self) -> QWidget:
        """Buttons that open the other windows (one instance each, see ``windows``)."""
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        heading = QLabel("Weitere Fenster")
        heading.setObjectName("heading")
        lay.addWidget(heading)
        self.window_buttons: dict[str, QPushButton] = {}
        slots = {"goa": self.open_goa_window, "acid": self.open_acid_window,
                 "blaster": self.open_blaster_window}
        for key, label in WINDOW_KEYS:
            button = QPushButton(label)
            button.setObjectName(f"open_{key}")
            button.clicked.connect(slots[key])
            self.window_buttons[key] = button
            lay.addWidget(button)
        self.settings_button = QPushButton("Einstellungen …")
        self.settings_button.setObjectName("open_settings")
        self.settings_button.setToolTip("Ausgabe- und Projektordner, Samplerate, Bittiefe: "
                                        "gelten für dieses und alle anderen Fenster.")
        self.settings_button.clicked.connect(self.open_settings)
        lay.addWidget(self.settings_button)
        self.window_note = QLabel()
        self.window_note.setObjectName("muted")
        self.window_note.setWordWrap(True)
        self.window_note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        lay.addWidget(self.window_note)
        return box

    # --- shared settings and hand-off from the tool windows (#439) -------------------------
    def open_settings(self) -> SettingsDialog:
        """Open the settings dialog (window-modal, returns at once); OK applies it."""
        dlg = SettingsDialog(self.hub.settings, self)
        dlg.accepted.connect(self._settings_accepted)
        self.settings_dialog = dlg
        dlg.open()
        return dlg

    def _settings_accepted(self) -> None:
        dlg = self.settings_dialog
        if dlg is None:
            return
        self.hub.store.update(**dlg.values())
        if self.hub.store.persistent and not self.hub.store.last_save_ok:
            self.window_note.setText("Die Einstellungen gelten, konnten aber nicht gespeichert "
                                     f"werden ({self.hub.store.path}).")

    def _folder_edited(self) -> None:
        text = self.folder_edit.text().strip()
        if text:
            self.hub.store.update(output_dir=text)

    def _on_settings_changed(self, settings) -> None:
        root = str(settings.output_root())
        if self.folder_edit.text().strip() != root:
            self.folder_edit.setText(root)
        # Only a changed format touches the forms: a value typed into a form survives a change
        # of the folders (review of #450).
        new = {"sample_rate": settings.sample_rate, "bit_depth": settings.bit_depth}
        fields = tuple(name for name, old in self._format.items() if new[name] != old)
        self._format = new
        if fields:
            for key, model in self.models.items():
                if apply_format_to_form(model, settings, fields):
                    self.panels[key].sync_from_model()
        if self.on_library:
            self.library.set_folder(Path(root))
        self._update_state()

    def _on_files_written(self, paths) -> None:
        """A tool window wrote files: the library page shows them without a restart."""
        if self.on_library:
            self.library.refresh()

    def _bring_to_front(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def show_in_library(self, path) -> bool:
        """Show the library page with ``path`` selected. False (and a note) if the file is not
        below the output folder, so the library cannot list it."""
        path = Path(path)
        self.categories.setCurrentRow(self.library_row)  # rescans the output folder
        self._bring_to_front()
        for attempt in range(2):
            for i in range(self.library.list.count()):
                item = self.library.list.item(i)
                if Path(item.data(PATH_ROLE)) == path:
                    self.library.list.setCurrentRow(i)
                    return True
            if attempt == 0:  # hidden by the filter: show everything
                self.library.category_box.setCurrentIndex(0)
                self.library.search.clear()
        self.library.info.setText(
            f"{path.name} liegt nicht im Ausgabeordner {self.library.folder}; die Bibliothek "
            "listet nur diesen Ordner.")
        return False

    def send_to_live(self, path) -> None:
        """Open the Live-import page with ``path`` chosen. Nothing is sent: the page's checks
        (read set, plan, test-set confirmation) run as for any other file."""
        path = Path(path)
        self.categories.setCurrentRow(self.tool_rows["live"])  # reloads its library list
        self._bring_to_front()
        idx = self.live.wav_box.findData(str(path))
        if idx >= 0:
            self.live.wav_box.setCurrentIndex(idx)
        else:
            self.live.add_wav(path)
        self.live.set_status(f"{path.name} gewählt. Live-Set lesen, Plan prüfen, Test-Set "
                             "bestätigen, dann importieren.")

    def _open_window(self, key: str) -> None:
        win = self.windows.open(key)
        self.window_note.setText(self.windows.last_error if win is None else "")

    def open_goa_window(self) -> None:
        self._open_window("goa")

    def open_acid_window(self) -> None:
        self._open_window("acid")

    def open_blaster_window(self) -> None:
        self._open_window("blaster")

    def _library_folder(self) -> Path:
        edit = getattr(self, "folder_edit", None)  # not built yet while the pages are made
        text = edit.text().strip() if edit is not None else ""
        return Path(text) if text else self.hub.settings.output_root()

    def _build_right(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Ausgabeordner"))
        self.folder_edit = QLineEdit(str(self.hub.settings.output_root()))
        self.folder_edit.editingFinished.connect(self._folder_edited)
        folder_row.addWidget(self.folder_edit, 1)
        choose = QPushButton("Wählen …")
        choose.clicked.connect(self._choose_folder)
        folder_row.addWidget(choose)
        lay.addLayout(folder_row)

        self.render_button = QPushButton("Rendern")
        self.render_button.setObjectName("primary")
        self.render_button.clicked.connect(self.start_render)
        self.cancel_button = QPushButton("Abbrechen")
        self.cancel_button.clicked.connect(self.cancel_render)
        buttons = QHBoxLayout()
        buttons.addWidget(self.render_button, 1)
        buttons.addWidget(self.cancel_button)
        lay.addLayout(buttons)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        lay.addWidget(self.progress)
        self.status = QLabel()
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        # Long messages wrap instead of widening the column.
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        lay.addWidget(self.status)

        heading = QLabel("Ergebnisse")
        heading.setObjectName("heading")
        lay.addWidget(heading)
        self.results = DragList()  # rows can be dragged out as WAV files
        self.results.setObjectName("results")
        self.results.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.results.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.results.currentRowChanged.connect(self._result_selected)
        lay.addWidget(self.results, 1)

        self.wave = WaveformWidget()
        lay.addWidget(self.wave)
        transport = QHBoxLayout()
        self.play_button = QPushButton("Abspielen")
        self.play_button.clicked.connect(self.play)
        self.stop_button = QPushButton("Stopp")
        self.stop_button.clicked.connect(self.stop)
        self.open_button = QPushButton("Ausgabeordner öffnen")
        self.open_button.clicked.connect(self.open_folder)
        transport.addWidget(self.play_button)
        transport.addWidget(self.stop_button)
        transport.addStretch(1)
        transport.addWidget(self.open_button)
        lay.addLayout(transport)
        self.preview_info = QLabel()
        self.preview_info.setObjectName("muted")
        self.preview_info.setWordWrap(True)
        self.preview_info.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        lay.addWidget(self.preview_info)
        return box

    # --- pages -------------------------------------------------------------------------
    @property
    def model(self) -> CategoryFormModel:
        return self.models[self.form_key]

    @property
    def panel(self) -> CategoryPanel:
        return self.panels[self.form_key]

    def show_page(self, row: int) -> None:
        """Row ``len(CATEGORIES)`` is the library, the others are category forms."""
        if row < 0:
            return
        self.on_library = row == self.library_row
        self.on_tool = row > self.library_row
        if self.on_library:
            self.library.set_folder(Path(self.folder_edit.text().strip() or "."))
        elif self.on_tool:
            if row == self.tool_rows["live"]:
                self.live.reload_library()
        else:
            self.form_key = CATEGORIES[row].key
        self.right.setVisible(not self.on_tool)  # the tool pages bring their own controls
        self.stack.setCurrentIndex(row)
        self._update_state()

    # --- state -------------------------------------------------------------------------
    @property
    def running(self) -> bool:
        # Until the result has been shown (_on_done), not merely until the worker is done.
        return self.handle is not None

    def set_status(self, text: str, error: bool = False) -> None:
        self.status.setText(text)
        self.status.setProperty("level", "error" if error else "ok")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _update_state(self) -> None:
        passive = self.on_library or self.on_tool
        issues = [] if passive else self.model.issues()
        self.render_button.setEnabled(not issues and not self.running and not passive)
        self.cancel_button.setEnabled(self.running)
        if self.running:
            return
        if passive:
            if self.status.text().startswith("Rendern nicht möglich"):
                self.set_status("")
        elif issues:
            self.set_status("Rendern nicht möglich: " + " | ".join(issues), error=True)
        elif self.status.property("level") == "error" and self.status.text().startswith(
            "Rendern nicht möglich"
        ):
            self.set_status("")
        playable = self.preview.waveform is not None
        self.play_button.setEnabled(playable)
        self.stop_button.setEnabled(playable)

    # --- render ------------------------------------------------------------------------
    def _choose_folder(self) -> None:
        picked = QFileDialog.getExistingDirectory(self, "Ausgabeordner wählen",
                                                  self.folder_edit.text())
        if picked:
            self.folder_edit.setText(picked)
            self._folder_edited()

    def start_render(self) -> None:
        if self.running or self.on_library or self.on_tool or not self.model.is_valid:
            return
        job = RenderJob(
            self.model.build_request(), Path(self.folder_edit.text().strip()),
            self.model.preset, self.model.overrides(), self.form_key,
        )
        total = int(job.request["variants"])
        self.progress.setRange(0, total)
        self.progress.setValue(0)
        self.set_status("Rendern …")
        self.handle = self.service.start(
            job, on_progress=self._bridge.progress.emit, on_done=self._bridge.done.emit
        )
        self._update_state()

    def cancel_render(self) -> None:
        if self.handle is not None:
            self.handle.cancel()
            self.set_status("Abbrechen …")

    def _on_progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(done)

    def _on_done(self, result: RenderResult) -> None:
        self.handle = None
        first_new = self.results.count()
        for f in result.files:
            item = QListWidgetItem(
                f"{result.job.category}  {f.wav_path.name}    Seed {f.seed}"
                + (f"    Spitze {f.peak_dbfs:.1f} dBFS" if f.peak_dbfs is not None else "")
            )
            item.setData(PATH_ROLE, str(f.wav_path))
            self.results.addItem(item)
        self.result_paths.extend(f.wav_path for f in result.files)
        n = len(result.files)
        if result.error is not None:
            self.set_status(f"Fehler: {result.error.message}", error=True)
        elif result.cancelled:
            self.set_status(f"Abgebrochen. {n} Datei(en) fertig.", error=True)
        else:
            self.set_status(f"Fertig: {n} Datei(en) in {result.job.out_dir}")
            self.progress.setValue(self.progress.maximum())
        if n:
            self.results.setCurrentRow(first_new)
        if self.on_library:
            self.library.refresh()
        self._update_state()

    # --- preview -----------------------------------------------------------------------
    def _result_selected(self, row: int) -> None:
        item = self.results.item(row)
        if item is not None:
            self._load_preview(Path(item.data(PATH_ROLE)))

    def _load_preview(self, path: Path) -> None:
        if self.preview.load(path):
            wf = self.preview.waveform
            self.wave.set_waveform(wf)
            self.preview_info.setText(
                f"{path.name}: {wf.duration_s * 1000:.0f} ms, {wf.sample_rate} Hz, "
                f"{wf.bit_depth} Bit. Die Höhe der Welle ist auf die Datei skaliert."
            )
        else:
            self.wave.set_waveform(None, self.preview.message)
            self.preview_info.setText(self.preview.message)
        self._update_state()

    def play(self) -> None:
        if self.preview.play():
            self.timer.start()
            self.preview_info.setText("Spielt …")
        elif self.preview.state == ERROR:
            self.preview_info.setText(self.preview.message)

    def stop(self) -> None:
        self.preview.stop()
        self.timer.stop()
        self.wave.set_playhead(0.0)

    def _tick(self) -> None:
        self.preview.tick()
        self.wave.set_playhead(self.preview.position())
        if self.preview.state != PLAYING:
            self.timer.stop()
            self.wave.set_playhead(0.0)

    def open_folder(self) -> None:
        folder = Path(self.folder_edit.text().strip())
        if not folder.is_dir():
            self.set_status("Der Ausgabeordner existiert noch nicht (er entsteht beim Rendern).",
                            error=True)
            return
        if not self.opener(folder):
            self.set_status("Der Ordner konnte nicht geöffnet werden.", error=True)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt name
        if self.handle is not None:
            self.handle.cancel()
            self.handle.wait(10)  # the daemon thread must not write into a closed window
        self.hub.store.set_window("main", window_state(self))
        self.windows.close_all()
        self.hub.detach()
        self.goa.shutdown()
        self.chat.shutdown()
        self.preview.close()
        super().closeEvent(event)
