"""Acid window: controls, generator, step grid, file actions, rough preview."""

from __future__ import annotations

import random
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from audio_engine.io import encode_wav
from gui_core.acid_generate import (
    ROOTS,
    SCALES,
    AcidOptionError,
    GenOptions,
)
from gui_core.acid_model import (
    AcidFileError,
    AcidModel,
    parse_bpm,
    parse_percent,
    parse_seed,
)
from gui_core.acid_preview import preview_wav_bytes, render_preview
from gui_core.paths import default_output_dir
from gui_core.preview import PlaybackBackend
from gui_core.settings import DEFAULT_BIT_DEPTH, DEFAULT_SAMPLE_RATE, free_stem

from ..windows import OnTopBox, OnTopWindow, ResultActions
from . import skin
from .widgets import AcidRoot, EtchedPanel, FooterBand, HeaderBand, StepGridWidget

PREVIEW_LABEL = "grobe Vorschau, kein 303-Klang"


def _open_in_file_manager(path: Path) -> bool:
    from PySide6.QtCore import QUrl

    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def _ask_open_file(parent: QWidget, start: Path) -> Path | None:
    name, _ = QFileDialog.getOpenFileName(parent, "Acid-Linie laden", str(start),
                                          "Acid-Linie (*.json)")
    return Path(name) if name else None


class AcidWindow(OnTopWindow, QWidget):
    def __init__(
        self,
        out_dir: Path | None = None,
        backend: PlaybackBackend | None = None,
        opener: Callable[[Path], bool] = _open_in_file_manager,
        ask_open: Callable[[QWidget, Path], Path | None] = _ask_open_file,
        seed_source: Callable[[], int] = lambda: random.randrange(1, 1_000_000),
    ) -> None:
        super().__init__()
        self.setWindowTitle("AbeltonGod · Acid-Linie")
        self.setStyleSheet(skin.STYLESHEET)
        self.model = AcidModel()
        self.opener, self.ask_open, self.seed_source = opener, ask_open, seed_source
        if backend is None:
            from gui.audio import choose_backend

            backend = choose_backend()
        self.backend = backend
        self.hub = None
        self._auto_folder: str | None = None  # the folder the settings gave (not typed)
        self.sample_rate, self.bit_depth = DEFAULT_SAMPLE_RATE, DEFAULT_BIT_DEPTH
        self._tmp = Path(tempfile.mkdtemp(prefix="abeltongod-acid-"))
        self._build(out_dir or default_output_dir())
        self.sync()
        u = self.fontMetrics().height()
        want_w, want_h = int(u * 74), int(u * 54)
        screen = QGuiApplication.primaryScreen()
        if screen is not None:  # never wider / taller than the screen (like the Blaster)
            area = screen.availableGeometry()
            want_w, want_h = min(want_w, area.width()), min(want_h, int(area.height() * 0.95))
        self.resize(want_w, want_h)

    # ---- construction ------------------------------------------------------------------
    def _field(self, text: str, width_em: float = 3.8) -> QLineEdit:
        e = QLineEdit(text)
        e.setFixedWidth(int(self.fontMetrics().height() * width_em))
        return e

    def _cap(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("cap")
        return lab

    def _panel(self, title: str, seed: int, ribs: bool = True) -> tuple[EtchedPanel, QVBoxLayout]:
        panel = EtchedPanel(title, seed, ribs)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(*panel.content_margins())
        return panel, lay

    def _build(self, out_dir: Path) -> None:
        u = self.fontMetrics().height()
        root = AcidRoot()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        # The whole skin scrolls, so its panels do not set the window's minimum (#442 P2);
        # AcidRoot paints its own background, the scroll area only frames it.
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setWidget(root)
        outer.addWidget(self.scroll)
        col = QVBoxLayout(root)
        col.setContentsMargins(int(u * 0.8), 0, int(u * 0.8), 0)
        col.setSpacing(int(u * 0.2))
        self.header = HeaderBand()
        col.addWidget(self.header)

        top = QHBoxLayout()
        top.setSpacing(int(u * 0.4))
        # --- line panel
        line_panel, ll = self._panel("Linie", 1)
        g = QGridLayout()
        g.setHorizontalSpacing(int(u * 0.8))
        g.setVerticalSpacing(int(u * 0.3))
        self.root_box = QComboBox()
        self.root_box.addItems(ROOTS)
        self.scale_box = QComboBox()
        self.scale_box.addItems(list(SCALES))
        self.octave_spin = QSpinBox()
        self.octave_spin.setRange(0, 6)
        self.length_spin = QSpinBox()
        self.length_spin.setRange(1, 32)
        self.bpm_edit = self._field("130")
        for c, (cap, w) in enumerate((("Wurzel", self.root_box), ("Skala", self.scale_box),
                                      ("Oktave", self.octave_spin), ("Länge", self.length_spin),
                                      ("BPM", self.bpm_edit))):
            g.addWidget(self._cap(cap.upper()), 0, c)
            g.addWidget(w, 1, c)
        ll.addLayout(g)
        # #543: play / stop at the top left, visible without scrolling in a half-screen window
        # (they sat in the file row at the bottom, below the fold at 640 x 680 logical px).
        self.preview_button = QPushButton("▶ Vorschau")
        self.preview_button.setObjectName("primary")
        self.preview_button.setToolTip(f"Spielt die Linie einmal ab ({PREVIEW_LABEL}).")
        self.stop_button = QPushButton("■ Stopp")
        prow = QHBoxLayout()
        prow.addWidget(self.preview_button)
        prow.addWidget(self.stop_button)
        prow.addStretch(1)
        ll.addLayout(prow)
        # The play result next to the buttons (the footer status is below the fold too, review
        # of #561): "Spielt …", or the German error.
        self.preview_status = QLabel("")
        self.preview_status.setObjectName("status")
        self.preview_status.setWordWrap(True)
        ll.addWidget(self.preview_status)
        ll.addStretch(1)
        top.addWidget(line_panel, 5)
        # --- generator panel
        gen_panel, gl = self._panel("Generator", 2)
        g2 = QGridLayout()
        g2.setHorizontalSpacing(int(u * 0.8))
        g2.setVerticalSpacing(int(u * 0.3))
        self.density_edit = self._field("60")
        self.accent_edit = self._field("25")
        self.slide_edit = self._field("20")
        self.range_spin = QSpinBox()
        self.range_spin.setRange(1, 3)
        self.range_spin.setValue(2)
        for spin in (self.range_spin, self.octave_spin, self.length_spin):
            spin.setFixedWidth(int(u * 4.4))
        self.seed_edit = self._field("0", 5.5)
        for c, (cap, w) in enumerate((("Dichte %", self.density_edit),
                                      ("Akzent %", self.accent_edit),
                                      ("Slide %", self.slide_edit),
                                      ("Oktaven", self.range_spin), ("Seed", self.seed_edit))):
            g2.addWidget(self._cap(cap.upper()), 0, c)
            g2.addWidget(w, 1, c)
        self.generate_button = QPushButton("Generieren")
        self.generate_button.setObjectName("primary")
        self.newseed_button = QPushButton("Neuer Seed")
        gl.addLayout(g2)
        brow = QHBoxLayout()
        brow.addWidget(self.generate_button)
        brow.addWidget(self.newseed_button)
        brow.addStretch(1)
        gl.addLayout(brow)
        top.addWidget(gen_panel, 7)
        col.addLayout(top)
        # --- grid
        grid_panel, gridl = self._panel("Gitter", 3, ribs=False)
        self.grid = StepGridWidget(self.model)
        gridl.addWidget(self.grid)
        col.addWidget(grid_panel, 1)
        # --- file / preview row
        act_panel, al = self._panel("Datei", 4)
        row = QHBoxLayout()
        row.setSpacing(int(u * 0.5))
        self.folder_edit = QLineEdit(str(out_dir))
        al.addWidget(self.folder_edit)
        self.load_button = QPushButton("Laden…")
        self.save_button = QPushButton("JSON speichern")
        self.export_button = QPushButton("MIDI exportieren")
        self.export_button.setObjectName("primary")
        self.wav_button = QPushButton("WAV exportieren")
        self.wav_button.setToolTip(f"Schreibt die Vorschau als WAV ({PREVIEW_LABEL}) in den "
                                   "Ausgabeordner. Ohne Sidecar: für Acid-Linien gibt es keinen "
                                   "Vertrag.")
        self.open_button = QPushButton("Ordner öffnen")
        self.anim_box = QCheckBox("Animation")
        # #517: next to Live on one monitor. In this row, not the second: with it there the
        # step grid's pitch area was 74 px high on Windows CI and the drag test failed.
        self.on_top_box = OnTopBox()
        for w in (self.load_button, self.save_button, self.export_button,
                  self.open_button, self.anim_box,
                  self.on_top_box):
            row.addWidget(w)
        al.addLayout(row)
        # Second row: WAV export, the hand-off and the preview note (the note had a line of its
        # own before, so the window keeps its height and width at 150 %, #442).
        row2 = QHBoxLayout()
        row2.setSpacing(int(u * 0.5))
        row2.addWidget(self.wav_button, 0, Qt.AlignmentFlag.AlignTop)
        self.actions = ResultActions()
        row2.addWidget(self.actions, 1)
        self.preview_note = QLabel(f"Vorschau: {PREVIEW_LABEL}")
        self.preview_note.setObjectName("muted")
        row2.addWidget(self.preview_note)
        al.addLayout(row2)
        col.addWidget(act_panel)
        # --- footer / status
        self.footer = FooterBand()
        fl = QHBoxLayout(self.footer)
        fl.setContentsMargins(int(u * 0.5), 0, int(u * 15), int(u * 0.3))
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        fl.addWidget(self.status)
        col.addWidget(self.footer)

        # --- wiring
        self.root_box.activated.connect(self._scale_changed)
        self.scale_box.activated.connect(self._scale_changed)
        self.octave_spin.valueChanged.connect(self._octave_changed)
        self.length_spin.valueChanged.connect(self._length_changed)
        self.bpm_edit.editingFinished.connect(self._bpm_changed)
        self.grid.changed.connect(lambda: self.set_status(""))
        self.generate_button.clicked.connect(self.generate)
        self.newseed_button.clicked.connect(self.new_seed)
        self.load_button.clicked.connect(self.load)
        self.save_button.clicked.connect(self.save_json)
        self.export_button.clicked.connect(self.export_midi)
        self.wav_button.clicked.connect(self.export_wav)
        self.open_button.clicked.connect(self.open_folder)
        self.preview_button.clicked.connect(self.preview)
        self.stop_button.clicked.connect(self.stop_preview)
        self.anim_box.toggled.connect(self.set_animation)

    # ---- state sync ---------------------------------------------------------------------
    def sync(self, show_seed: bool = True) -> None:
        """Show the model state in the controls (no signals fired). ``show_seed=False`` keeps
        a seed the user typed but has not generated with yet."""
        m = self.model
        for w in (self.root_box, self.scale_box, self.octave_spin, self.length_spin):
            w.blockSignals(True)
        self.root_box.setCurrentText(m.root)
        self.scale_box.setCurrentText(m.scale)
        self.octave_spin.setValue(m.root_octave)
        self.length_spin.setValue(m.length)
        for w in (self.root_box, self.scale_box, self.octave_spin, self.length_spin):
            w.blockSignals(False)
        self.bpm_edit.setText(f"{m.bpm:g}")
        if show_seed:
            self.seed_edit.setText(str(m.seed))
        self._mark(self.bpm_edit, False)
        self.grid.update_min_height()
        self.grid.update()

    def set_status(self, text: str, error: bool = False) -> None:
        self.status.setText(text)
        self.status.setProperty("level", "error" if error else "ok")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _mark(self, edit: QLineEdit, invalid: bool) -> None:
        edit.setProperty("invalid", invalid)
        edit.style().unpolish(edit)
        edit.style().polish(edit)

    def _fail(self, exc: Exception, edit: QLineEdit | None = None) -> None:
        if edit is not None:
            self._mark(edit, True)
        self.set_status(str(exc), error=True)

    # ---- handlers -----------------------------------------------------------------------
    def _scale_changed(self, *_a) -> None:
        try:
            self.model.set_scale(self.root_box.currentText(), self.scale_box.currentText())
        except AcidOptionError as exc:
            self._fail(exc)
        self.sync(show_seed=False)

    def _octave_changed(self, value: int) -> None:
        try:
            self.model.set_root_octave(value)
            self.set_status("")
        except AcidOptionError as exc:
            self._fail(exc)
        self.sync(show_seed=False)

    def _length_changed(self, value: int) -> None:
        try:
            self.model.set_length(value)
            self.set_status("")
        except AcidOptionError as exc:
            self._fail(exc)
        self.sync(show_seed=False)

    def _bpm_changed(self) -> None:
        try:
            self.model.bpm = parse_bpm(self.bpm_edit.text())
            self._mark(self.bpm_edit, False)
        except AcidOptionError as exc:
            self._fail(exc, self.bpm_edit)

    def _options(self) -> GenOptions:
        edits = (self.density_edit, self.accent_edit, self.slide_edit, self.seed_edit)
        for e in edits:
            self._mark(e, False)
        try:
            dens = parse_percent(self.density_edit.text(), "Dichte")
        except AcidOptionError:
            self._mark(self.density_edit, True)
            raise
        try:
            acc = parse_percent(self.accent_edit.text(), "Akzent")
        except AcidOptionError:
            self._mark(self.accent_edit, True)
            raise
        try:
            sl = parse_percent(self.slide_edit.text(), "Slide")
        except AcidOptionError:
            self._mark(self.slide_edit, True)
            raise
        try:
            seed = parse_seed(self.seed_edit.text())
        except AcidOptionError:
            self._mark(self.seed_edit, True)
            raise
        m = self.model
        return GenOptions(root=m.root, scale=m.scale, root_octave=m.root_octave, length=m.length,
                          density=dens, accent_chance=acc, slide_chance=sl,
                          octave_range=self.range_spin.value(), seed=seed)

    def generate(self) -> None:
        try:
            opts = self._options()
            self.model.generate(opts)
        except AcidOptionError as exc:
            self._fail(exc)
            return
        self.sync()
        self.set_status(f"Muster erzeugt (Seed {opts.seed}).")

    def new_seed(self) -> None:
        self.seed_edit.setText(str(self.seed_source()))
        self.generate()

    def _stem(self) -> str:
        return f"acid_{self.model.seed}"

    def _folder(self) -> Path:
        return Path(self.folder_edit.text().strip() or str(default_output_dir()))

    def _run_dir(self) -> Path:
        """One folder per line (seed) below the Acid folder: ``Acid/acid_<seed>/`` holds its
        JSON, MIDI and WAV (#468)."""
        return self._folder() / self._stem()

    def load(self) -> None:
        path = self.ask_open(self, self._folder())
        if path is None:
            return
        try:
            self.model.load_file(path)
        except AcidFileError as exc:
            self._fail(exc)
            return
        self.sync()
        self.set_status(f"Geladen: {path.name}")

    def save_json(self) -> Path | None:
        try:
            p = self.model.save_file(self._run_dir() / f"{self._stem()}.json")
        except AcidFileError as exc:
            self._fail(exc)
            return None
        self.set_status(f"Gespeichert: {p}")
        self.actions.set_paths([p])
        return p

    def export_midi(self) -> Path | None:
        try:
            self.model.bpm = parse_bpm(self.bpm_edit.text())
            p = self.model.export_midi(self._run_dir() / f"{self._stem()}.mid")
        except (AcidFileError, AcidOptionError) as exc:
            self._fail(exc, self.bpm_edit if isinstance(exc, AcidOptionError) else None)
            return None
        self.set_status(f"MIDI geschrieben: {p}  (nicht in Live getestet)")
        self.actions.set_paths([p])
        return p

    def export_wav(self) -> Path | None:
        """The rough preview as a WAV in the output folder (never overwriting: ``_2`` ...), at
        the shared sample rate and bit depth. No sidecar: there is no contract for acid lines."""
        try:
            self.model.bpm = parse_bpm(self.bpm_edit.text())
            samples = render_preview(self.model.to_line(), self.model.bpm, self.sample_rate)
            data = encode_wav(samples, self.sample_rate, self.bit_depth)
            folder = self._run_dir()
            folder.mkdir(parents=True, exist_ok=True)
            p = folder / f"{free_stem(folder, self._stem(), ('.wav',))}.wav"
            with open(p, "xb") as f:  # "x": never replace a file
                f.write(data)
        except (AcidOptionError, ValueError, OSError) as exc:
            self._fail(exc, self.bpm_edit if isinstance(exc, AcidOptionError) else None)
            return None
        self.set_status(f"WAV geschrieben: {p}  ({PREVIEW_LABEL}, {self.sample_rate} Hz, "
                        f"{self.bit_depth} Bit, ohne Sidecar)")
        self.actions.set_paths([p])
        if self.hub is not None:
            self.hub.files_written.emit([p])
        return p

    # ---- shared settings / hand-off -----------------------------------------------------
    def attach_hub(self, hub) -> None:
        """Shared output folder and audio format, library and Live hand-off (main window)."""
        self.hub = hub
        self.actions.set_hub(hub)
        self._auto_folder = str(hub.settings.acid_dir())
        self.folder_edit.setText(self._auto_folder)
        self._settings_changed(hub.settings)
        hub.settings_changed.connect(self._settings_changed)

    def _settings_changed(self, settings) -> None:
        self.sample_rate = settings.effective_sample_rate()
        self.bit_depth = settings.effective_bit_depth()
        new = str(settings.acid_dir())
        if self.folder_edit.text().strip() == self._auto_folder:
            self.folder_edit.setText(new)  # a folder the user typed is kept
        self._auto_folder = new

    def open_folder(self) -> None:
        folder = self._folder()
        if not folder.is_dir():
            self.set_status("Der Ausgabeordner existiert noch nicht (er entsteht beim Speichern).",
                            error=True)
            return
        if not self.opener(folder):
            self.set_status("Der Ordner konnte nicht geöffnet werden.", error=True)

    def preview(self) -> bool:
        """Render the rough preview and hand it to the backend. Every failure ends in a German
        status line (#543: an exception outside the caught types used to vanish in the Qt slot,
        and the windowed exe has no console to print it), shown in the footer and next to the
        play buttons (the footer can be below the fold in a half-screen window)."""
        ok = self._preview()
        self.preview_status.setText(self.status.text())
        self.preview_status.setProperty("level", self.status.property("level"))
        self.preview_status.style().unpolish(self.preview_status)
        self.preview_status.style().polish(self.preview_status)
        return ok

    def _preview(self) -> bool:
        if not self.backend.available:
            self.set_status("Keine Audioausgabe verfügbar.", error=True)
            return False
        try:
            self.model.bpm = parse_bpm(self.bpm_edit.text())
        except AcidOptionError as exc:
            self._fail(exc, self.bpm_edit)
            return False
        try:
            data = preview_wav_bytes(self.model.to_line(), self.model.bpm)
        except Exception as exc:  # noqa: BLE001 - shown to the user, never swallowed
            self.set_status(f"Vorschau konnte nicht berechnet werden: {exc}", error=True)
            return False
        try:
            path = self._tmp / "acid_preview.wav"
            path.write_bytes(data)
        except OSError as exc:
            self.set_status(f"Vorschau konnte nicht zwischengespeichert werden: {exc}",
                            error=True)
            return False
        try:
            self.backend.play(path)
        except Exception as exc:  # noqa: BLE001
            self.set_status(f"Wiedergabe fehlgeschlagen: {exc}", error=True)
            return False
        self.set_status(f"Spielt: {PREVIEW_LABEL} ({self.model.bpm:g} BPM). Kein Ton? Lautstärke "
                        "und Wiedergabegerät in Windows prüfen.")
        return True

    def stop_preview(self) -> None:
        try:
            self.backend.stop()
        except Exception:  # noqa: BLE001
            pass

    def set_animation(self, on: bool) -> None:
        for w in (self.header, self.footer, self.grid):
            w.set_animation(on)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt name
        self.set_animation(False)
        self.stop_preview()
        shutil.rmtree(self._tmp, ignore_errors=True)
        super().closeEvent(event)
