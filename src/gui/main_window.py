"""Main window: category list, kick panel, results with preview. No logic of its own.

Two layouts (#517, one monitor next to Live). *Wide*: page list on the left, the page, the
render column on the right. *Compact*, whenever the window is narrower than the wide layout
needs (e.g. half a 1920 x 1080 screen at 150 %): a page chooser and the window buttons on top,
the page, the render column below it. The window's minimum is the compact one; the switch
happens on resize (:meth:`MainWindow.set_compact`)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QBoxLayout,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from bridge.capabilities import CapabilityRegistry
from gui_core.categories import CATEGORIES, LIBRARY_LABEL
from gui_core.chat import ChatSession
from gui_core.choices import ChoiceLog
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
from .planner_panel import PlannerPanel
from .reference_panel import ReferencePanel
from .waveform_widget import WaveformWidget
from .windows import (
    WINDOW_KEYS,
    AppHub,
    OnTopBox,
    OnTopWindow,
    SettingsDialog,
    WindowManager,
    restore_state,
    window_state,
)

# Pages after the sample categories and the library (left list order).
TOOL_PAGES = (("goa", "Goa-Melodie"),("planner", "Arrangement-Planer"),
              ("live", "Live-Import"), ("chat", "Copilot"), ("reference", "Referenz"))


class _Root(QWidget):
    """Central widget. Its minimum width is the compact layout's (``compact_width``, measured
    once), so the window can be made narrower than the wide layout; ``on_resize`` picks the
    layout before the children are placed again."""

    def __init__(self) -> None:
        super().__init__()
        self.compact_width = 0
        self.on_resize: Callable[[int], None] | None = None

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt name
        hint = super().minimumSizeHint()
        if self.compact_width:  # the same on every page: changing the page never resizes
            hint.setWidth(self.compact_width)
        return hint

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt name
        if self.on_resize is not None:
            self.on_resize(event.size().width())
        super().resizeEvent(event)


class _VScroll(QScrollArea):
    """A frameless holder that scrolls only vertically: the content's minimum height no longer
    sets the window's (it scrolls instead), its minimum width still does (nothing is cut off at
    the side)."""

    def __init__(self, widget: QWidget) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWidget(widget)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt name
        hint = super().minimumSizeHint()
        w = self.widget()
        need = max(w.minimumSizeHint().width(), w.minimumWidth())
        bar = self.verticalScrollBar().sizeHint().width()
        hint.setWidth(max(hint.width(), need + bar + 2 * self.frameWidth()))
        return hint

    def event(self, e) -> bool:
        if e.type() == QEvent.Type.LayoutRequest:  # the content's minimum may have changed
            self.updateGeometry()
        return super().event(e)


class _Stack(QStackedWidget):
    """Page stack whose minimum is the shown page's, not the widest page's: a narrow category
    page keeps the wide layout although the Goa page is wider (#517)."""

    def __init__(self) -> None:
        super().__init__()
        self.currentChanged.connect(lambda _i: self.updateGeometry())

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt name
        page = self.currentWidget()
        if page is None:
            return super().minimumSizeHint()
        return page.minimumSizeHint().expandedTo(page.minimumSize())


class _Bridge(QObject):
    """Carries worker-thread callbacks to the GUI thread (queued signals)."""

    progress = Signal(int, int)
    done = Signal(object)


def open_in_file_manager(path: Path) -> bool:
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class MainWindow(OnTopWindow, QMainWindow):
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

        root = _Root()
        root.setObjectName("root")
        self.setCentralWidget(root)
        self.root = root
        outer = QBoxLayout(QBoxLayout.Direction.LeftToRight, root)
        self.outer = outer
        self.compact = False

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
        # Compact layout: the same rows (one model) in a drop-down above the page.
        self.page_box = QComboBox()
        self.page_box.setObjectName("page_box")
        self.page_box.setAccessibleName("Seite")
        self.page_box.setModel(self.categories.model())
        self.page_box.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.page_box.setMinimumContentsLength(12)  # its width follows the window, not a label
        self.page_box.setVisible(False)
        self.page_box.activated.connect(self.categories.setCurrentRow)
        self.categories.currentRowChanged.connect(self._sync_page_box)
        left = QVBoxLayout()
        left.addWidget(self.page_box)
        left.addWidget(self.categories, 1)
        left.addWidget(self._build_window_buttons())
        outer.addLayout(left)

        split = QSplitter()
        self.split = split
        split.setChildrenCollapsible(False)
        outer.addWidget(split, 1)
        self.stack = _Stack()  # its minimum: the shown page's (no explicit one, #517)
        self.panels: dict[str, CategoryPanel] = {}
        for c in CATEGORIES:
            panel = CategoryPanel(self.models[c.key])
            # category pages: content 34 M (knobs wrap, #442) plus the page's scroll bar
            panel.setMinimumWidth(m * 34 + panel.verticalScrollBar().sizeHint().width()
                                  + 2 * panel.frameWidth())
            panel.changed.connect(self._update_state)
            self.panels[c.key] = panel
            self.stack.addWidget(panel)
        self.library = LibraryPanel(ChoiceLog.beside_settings(self.hub.store.path))
        self.library.selected.connect(self._load_preview)
        self.library_scroll = _VScroll(self.library)  # its height scrolls (compact layout)
        self.stack.addWidget(self.library_scroll)
        self.library_row = len(CATEGORIES)
        self.goa = GoaPanel(self.hub.settings.goa_dir(), goa_service, opener)
        self.goa.attach_hub(self.hub)
        self.live = LivePanel(live_config, registry, self._library_folder)
        self.live.attach_hub(self.hub)  # its "Live-Projekt" field is the shared project folder
        self.chat = ChatPanel(chat_session, opener)
        self.chat.attach_hub(self.hub)  # session folder = output folder; new files -> library
        self.reference = ReferencePanel()
        self.reference.apply_requested.connect(self.apply_reference)
        self.tool_rows = {}
        self.tool_scrolls: dict[str, QScrollArea] = {}
        self.planner = PlannerPanel(self.hub.settings.output_root(), opener)
        self.planner.attach_hub(self.hub)  # plans go to <Ausgabeordner>/Plans
        for key, widget in (("goa", self.goa), ("planner", self.planner), ("live", self.live),
                            ("chat", self.chat), ("reference", self.reference)):
            # A scroll area per tool page: their height does not set the window's minimum
            # (fits 1920 x 1080 at 150 %, #442 P1); their width does, so no control is cut
            # off at the side (#517).
            box = _VScroll(widget)
            self.tool_scrolls[key] = box
            self.tool_rows[key] = self.stack.count()
            self.stack.addWidget(box)
        split.addWidget(self.stack)
        right = self._build_right()
        self._right_width = m * 38  # the render column in the wide layout
        right.setMinimumWidth(self._right_width)
        self.right = right
        self.right_scroll = _VScroll(right)
        split.addWidget(self.right_scroll)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)

        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self._tick)
        self.library.folder = Path(self.folder_edit.text().strip() or ".")
        self.categories.currentRowChanged.connect(self.show_page)
        self.categories.setCurrentRow(0)
        self._update_state()
        self._measure_layouts()
        root.on_resize = self._fit_layout
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
        self.window_heading = QLabel("Weitere Fenster")
        self.window_heading.setObjectName("heading")
        lay.addWidget(self.window_heading)
        self.window_buttons: dict[str, QPushButton] = {}
        slots = {"goa": self.open_goa_window, "acid": self.open_acid_window,
                 "blaster": self.open_blaster_window}
        for key, label in WINDOW_KEYS:
            button = QPushButton(label)
            button.setObjectName(f"open_{key}")
            button.clicked.connect(slots[key])
            self.window_buttons[key] = button
        self.settings_button = QPushButton("Einstellungen …")
        self.settings_button.setObjectName("open_settings")
        self.settings_button.setToolTip("Ausgabe- und Projektordner, Samplerate, Bittiefe: "
                                        "gelten für dieses und alle anderen Fenster.")
        self.settings_button.clicked.connect(self.open_settings)
        self.button_grid = QGridLayout()  # one column (wide), two columns (compact)
        self.button_grid.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(self.button_grid)
        self._place_window_buttons(1)
        self.on_top_box = OnTopBox()  # #517: next to Live on one monitor
        lay.addWidget(self.on_top_box)
        self.window_note = QLabel()
        self.window_note.setObjectName("muted")
        self.window_note.setWordWrap(True)
        self.window_note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        lay.addWidget(self.window_note)
        return box

    def _place_window_buttons(self, columns: int) -> None:
        buttons = [*self.window_buttons.values(), self.settings_button]
        for b in buttons:
            self.button_grid.removeWidget(b)
        for i, b in enumerate(buttons):
            self.button_grid.addWidget(b, i // columns, i % columns)

    # --- wide / compact layout (#517) ------------------------------------------------------
    def _sync_page_box(self, row: int) -> None:
        if self.page_box.currentIndex() != row:
            self.page_box.setCurrentIndex(row)

    def set_compact(self, on: bool) -> None:
        """Compact: page chooser and window buttons on top, page and render column stacked.
        Wide: page list left, page and render column side by side."""
        on = bool(on)
        if on == self.compact:
            return
        self.compact = on
        self.outer.setDirection(QBoxLayout.Direction.TopToBottom if on
                                else QBoxLayout.Direction.LeftToRight)
        self.categories.setVisible(not on)
        self.page_box.setVisible(on)
        self.window_heading.setVisible(not on)
        self._place_window_buttons(2 if on else 1)
        self.right.setMinimumWidth(0 if on else self._right_width)
        self.split.setOrientation(Qt.Orientation.Vertical if on else Qt.Orientation.Horizontal)
        if on:  # the page gets most of the height, the results the rest
            h = max(self.split.height(), 2)
            self.split.setSizes([h * 3 // 5, h - h * 3 // 5])
        self.root.updateGeometry()

    def _measure_layouts(self) -> None:
        """Measure both layouts once, over every page: below the widest page's wide minimum
        the window is compact (one threshold, so changing the page never flips the layout);
        the widest page's compact minimum is the window's minimum width."""
        self.ensurePolished()
        lay = self.root.layout()
        shown = self.stack.currentIndex()
        right_shown = not self.right_scroll.isHidden()
        widths = {False: 0, True: 0}
        self.layout_widths: dict[int, tuple[int, int]] = {}  # row -> (wide, compact); for tests
        for row in range(self.stack.count()):
            self.stack.setCurrentIndex(row)
            self.right_scroll.setVisible(row <= self.library_row)
            got = []
            for compact in (False, True):
                self.set_compact(compact)
                lay.invalidate()
                got.append(lay.minimumSize().width())
                widths[compact] = max(widths[compact], got[-1])
            self.layout_widths[row] = (got[0], got[1])
        self.set_compact(False)
        self.stack.setCurrentIndex(shown)
        self.right_scroll.setVisible(right_shown)
        lay.invalidate()
        self._wide_width, self.root.compact_width = widths[False], widths[True]

    def _fit_layout(self, width: int) -> None:
        was = self.compact
        self.set_compact(width < self._wide_width)
        if self.compact != was:
            self.root.layout().activate()  # place the children for the new layout now

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

    def apply_reference(self, candidate) -> None:
        """"Als Startwerte übernehmen" on the Referenz page (#480): the candidate's preset and
        values go into the kick form, the output format stays as the settings say, and the
        kick page is shown. Nothing is rendered."""
        from gui_core.reference import apply_to_form

        model = self.models["kick"]
        apply_to_form(model, candidate)
        apply_format_to_form(model, self.hub.settings)
        self.panels["kick"].sync_from_model()
        self.categories.setCurrentRow([c.key for c in CATEGORIES].index("kick"))
        self.set_status(f"Startwerte aus der Referenz: {candidate.name}. Prüfen, dann rendern.")

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
        self.right_scroll.setVisible(not self.on_tool)  # the tool pages bring their own controls
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
        self.reference.shutdown()
        self.preview.close()
        super().closeEvent(event)
