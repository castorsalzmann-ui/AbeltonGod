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
    QVBoxLayout,
    QWidget,
)

from gui_core.categories import CATEGORIES
from gui_core.form import KickFormModel
from gui_core.paths import default_output_dir
from gui_core.preview import ERROR, PLAYING, PlaybackBackend, PreviewController
from gui_core.render import RenderHandle, RenderJob, RenderResult, RenderService

from .audio import choose_backend
from .kick_panel import KickPanel
from .waveform_widget import WaveformWidget


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
    ) -> None:
        super().__init__()
        self.setWindowTitle("AbeltonGod")
        self._initial_out = out_dir
        self.service = service or RenderService()
        self.preview = PreviewController(backend or choose_backend())
        self.opener = opener
        self.model = KickFormModel()
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
        for entry in CATEGORIES:
            text = entry.label if entry.enabled else f"{entry.label}  ({entry.note})"
            item = QListWidgetItem(text)
            item.setSizeHint(QSize(0, self.fontMetrics().height() * 2))
            if not entry.enabled:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.categories.addItem(item)
        self.categories.setCurrentRow(0)
        m = self.fontMetrics().horizontalAdvance("M")  # layout in font units: follows the DPI
        self.categories.setFixedWidth(m * 20)
        outer.addWidget(self.categories)

        split = QSplitter()
        split.setChildrenCollapsible(False)
        outer.addWidget(split, 1)
        self.panel = KickPanel(self.model)
        self.panel.setMinimumWidth(m * 44)
        self.panel.changed.connect(self._update_state)
        split.addWidget(self.panel)
        right = self._build_right()
        right.setMinimumWidth(m * 38)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)

        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self._tick)
        self._update_state()
        self.resize(m * 112, self.fontMetrics().height() * 42)

    def _build_right(self) -> QWidget:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Ausgabeordner"))
        self.folder_edit = QLineEdit(str(self._initial_out or default_output_dir()))
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
        self.results = QListWidget()
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
        issues = self.model.issues()
        self.render_button.setEnabled(not issues and not self.running)
        self.cancel_button.setEnabled(self.running)
        if self.running:
            return
        if issues:
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

    def start_render(self) -> None:
        if self.running or not self.model.is_valid:
            return
        job = RenderJob(
            self.model.build_request(), Path(self.folder_edit.text().strip()),
            self.model.preset, self.model.overrides(),
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
                f"{f.wav_path.name}    Seed {f.seed}"
                + (f"    Spitze {f.peak_dbfs:.1f} dBFS" if f.peak_dbfs is not None else "")
            )
            item.setData(Qt.ItemDataRole.UserRole, str(f.wav_path))
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
        self._update_state()

    # --- preview -----------------------------------------------------------------------
    def _result_selected(self, row: int) -> None:
        item = self.results.item(row)
        if item is None:
            return
        path = Path(item.data(Qt.ItemDataRole.UserRole))
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
        self.preview.close()
        super().closeEvent(event)
