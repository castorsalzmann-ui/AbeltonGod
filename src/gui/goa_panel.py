"""Goa-Clips page (and the Goa window's body): option form of the clip generator
(``goa_clips``: one looping MIDI clip per voice: lead, arp, pad, pluck), rough preview per
voice and for all voices, MIDI export, drag of each .mid into Live.

D-035 (1): clips like the Acid line. No sections, no energy curve, no song length; song form
is the Arrangement-Planer's job (D-033). State and checks live in ``gui_core.goa``; the export
runs in ``gui_core.goa_render``; the preview sound comes from ``gui_core.goa_preview``. This
widget only shows them."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from audio_engine import goa_melody
from gui_core import goa_preview
from gui_core.form import FieldSpec, parse_number
from gui_core.goa import GROUPS, TITLE, VOICE_LABELS, ClipPlan, GoaFormModel, OptionSpec
from gui_core.goa_render import GoaJob, GoaResult, GoaService
from gui_core.paths import default_output_dir
from gui_core.preview import PlaybackBackend

from .drag import PATH_ROLE, DragList
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
from .widgets.adaptive import AdaptiveBox

BODY_HOOK = "goa_body"  # objectName of the page body: a hook for later skins/extra panels
ALL = "all"  # preview key of "Alle vorhören"


class _Signals(QObject):
    done = Signal(object)


class OptionForm(QScrollArea):
    """The clip generator's options, built from the widget kit. ``edits[dest]`` is the
    editing widget: ``NumberControl`` (bpm), ``Segmented`` / ``PresetChips`` (choices,
    voices), ``Toggle`` (flags) or ``StepEdit`` / ``QLineEdit`` (numbers and texts the
    generator checks itself).
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
        # A long label wraps (Windows CI: "Bass-Rhythmus (Roll)" needed 240 px of 180, #517);
        # at least the editor's first line high.
        label.setWordWrap(True)
        label.setMinimumHeight(int(self.fontMetrics().height() * 1.9))
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
            # The unit beside a number field is one short line ("ganze Zahl", "Takte"): it
            # counts in the form's minimum width, so a narrow window stacks form and preview
            # instead of squeezing it to a few px (#530 review: 7 px in the Goa window).
            hint.setWordWrap(False)
            hint.setMinimumWidth(hint.fontMetrics().horizontalAdvance(hint.text()) + 2)
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
            # A segmented row cannot wrap: only for a few short choices (the four arp patterns
            # made the form 41 M wide, too wide at half the screen width, #517).
            if len(spec.choices) <= 4 and sum(len(c) for c in spec.choices) <= 12:
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
            # whole BPM only (D-035 GUI): the slider and the readout give integers
            fs = FieldSpec(
                name="bpm", label=spec.label, kind="int", minimum=goa_melody.MIN_BPM,
                maximum=goa_melody.MAX_BPM, default=None, choices=(), unit="BPM",
                description=spec.help)
            c = NumberControl(fs, style="row", always_active=True)
            c.edited.connect(lambda _n, v, d=spec.dest: self._edited(d, str(int(round(v)))))
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
        backend: PlaybackBackend | None = None,
    ) -> None:
        super().__init__()
        self.setObjectName(BODY_HOOK)
        self.setStyleSheet(STYLE)
        self.service = service or GoaService()
        self.opener = opener or (lambda p: False)
        if backend is None:
            # The app's own backend choice (winsound on Windows); the shared output volume
            # wraps it there (D-035 (3)), so the Goa preview follows it without code here.
            from .audio import choose_backend

            backend = choose_backend()
        self.backend = backend
        self.base_dir = Path(base_dir) if base_dir else default_output_dir() / "Goa"
        self.model = GoaFormModel()
        self.handle = None
        self._folder_auto = True
        self._signals = _Signals()
        self._signals.done.connect(self._on_done)
        self.result: GoaResult | None = None
        self.playing: str | None = None  # voice or ALL of the last started preview
        self._tmp = Path(tempfile.mkdtemp(prefix="abeltongod-goa-"))

        # Form and result side by side while they fit, else the result below the form (#517:
        # the main window at half the screen width; the Goa window at its start size).
        outer = AdaptiveBox(self)
        left = QVBoxLayout()
        left.addWidget(heading(TITLE))
        intro = muted("Kurze MIDI-Clips (1 bis 16 Takte), einer je Stimme: Lead, Arp, Pad, "
                      "Pluck. Den ganzen Song baust du im Arrangement-Planer.")
        intro.setWordWrap(True)
        intro.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        left.addWidget(intro)
        # The actions (preview, folder, export, status) sit above the form, so the Goa window
        # (form and clip table stacked, #517) shows them without scrolling.
        self._build_actions(left)
        self.form = OptionForm(self.model)
        self.form.changed.connect(self.refresh)
        left.addWidget(self.form, 1)
        left_box = QWidget()
        left_box.setLayout(left)
        # The form scrolls inside: its width (the widest row plus the scroll bar) and, for the
        # stacked layout, a height of its own (else it shrinks to a few px).
        self.ensurePolished()
        f = self.form
        f.setMinimumWidth(f.widget().minimumSizeHint().width()
                          + f.verticalScrollBar().sizeHint().width() + 2 * f.frameWidth())
        f.setMinimumHeight(self.fontMetrics().height() * 18)
        outer.addWidget(left_box, 1)

        right = QVBoxLayout()
        self.tabs = QTabWidget()
        self._build_tabs(right)
        outer.addLayout(right, 1)
        self.hub = None
        self.refresh()

    def _build_actions(self, right: QVBoxLayout) -> None:
        # --- preview: one button per voice, all, stop
        right.addWidget(QLabel(f"Vorhören ({goa_preview.PREVIEW_LABEL})"))
        voices_row = QHBoxLayout()
        self.voice_buttons: dict[str, QPushButton] = {}
        for v, text in VOICE_LABELS.items():
            b = QPushButton(text)
            b.setObjectName(f"preview_{v}")
            b.setToolTip(f"{text}-Clip vorhören ({goa_preview.PREVIEW_LABEL}, ein Durchlauf)")
            b.clicked.connect(lambda _c=False, voice=v: self.preview(voice))
            self.voice_buttons[v] = b
            voices_row.addWidget(b)
        right.addLayout(voices_row)
        play_row = QHBoxLayout()
        self.all_button = QPushButton("Alle vorhören")
        self.all_button.setToolTip("Alle gewählten Stimmen zusammen vorhören "
                                   f"({goa_preview.PREVIEW_LABEL})")
        self.all_button.clicked.connect(lambda: self.preview(ALL))
        self.stop_button = QPushButton("Stopp")
        self.stop_button.clicked.connect(self.stop_preview)
        play_row.addWidget(self.all_button, 1)
        play_row.addWidget(self.stop_button)
        right.addLayout(play_row)
        # --- export
        row = QHBoxLayout()
        row.addWidget(QLabel("Neuer Ordner"))
        self.folder_edit = QLineEdit()
        self.folder_edit.textEdited.connect(self._folder_typed)
        row.addWidget(self.folder_edit, 1)
        right.addLayout(row)
        buttons = QHBoxLayout()
        self.export_button = QPushButton("MIDI exportieren")
        self.export_button.setObjectName("primary")
        self.export_button.setToolTip("Schreibt eine .mid je gewählter Stimme und eine README "
                                      "in den Ordner oben")
        self.export_button.clicked.connect(self.start_export)
        self.open_button = QPushButton("Ordner öffnen")
        self.open_button.clicked.connect(self.open_folder)
        buttons.addWidget(self.export_button, 1)
        buttons.addWidget(self.open_button)
        right.addLayout(buttons)
        self.status = QLabel()
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        right.addWidget(self.status)
        # --- drag: one row per exported clip (next to the export, visible without scrolling)
        self.drag_list = DragList()
        self.drag_list.setObjectName("goa_clip_files")
        self.drag_list.setToolTip("Nach dem Export: eine Zeile auf eine MIDI-Spur in Live ziehen "
                                  "(ein Clip; nicht in Live getestet)")
        self.drag_list.setMaximumHeight(int(self.fontMetrics().height() * 5.5))
        self.drag_list.hide()  # shown once there is something to drag
        right.addWidget(self.drag_list)

    def _build_tabs(self, right: QVBoxLayout) -> None:
        clips = QWidget()
        cv = QVBoxLayout(clips)
        self.summary = QLabel()
        self.summary.setObjectName("muted")
        self.summary.setWordWrap(True)
        self.summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        cv.addWidget(self.summary)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Stimme", "Noten", "Datei"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        cv.addWidget(self.table, 1)
        self.tabs.addTab(clips, "Clips")
        self.readme = QPlainTextEdit()
        self.readme.setReadOnly(True)
        self.readme.setPlaceholderText("Nach dem Export steht hier die README des Ordners.")
        self.tabs.addTab(self.readme, "README")
        right.addWidget(self.tabs, 1)
        self.note = QLabel(
            "Nichts davon ist in Live getestet. Die Vorschau ist grob (einfache Töne, kein "
            "Synth); das Produkt sind die MIDI-Clips, auf die du in Live eigene Instrumente "
            "legst.")
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        self.note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        right.addWidget(self.note)

    def attach_hub(self, hub) -> None:
        """Follow the shared output folder (clips are MIDI only: nothing for the library,
        which lists WAVs)."""
        self.hub = hub
        hub.settings_changed.connect(self._settings_changed)
        self.set_base_dir(hub.settings.goa_dir())

    def _settings_changed(self, settings) -> None:
        self.set_base_dir(settings.goa_dir())

    # --- state ---------------------------------------------------------------------------
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
        self.export_button.setEnabled(ev.ok and not self.running)
        chosen = set(ev.kwargs["voices"]) if ev.ok else set()
        for v, b in self.voice_buttons.items():
            b.setEnabled(v in chosen)
        self.all_button.setEnabled(ev.ok)
        if not self.running:
            if ev.ok:
                if self.status.property("level") == "error" and self.status.text().startswith(
                        "Export nicht möglich"):
                    self.set_status("")
            else:
                self.set_status("Export nicht möglich: " + ev.problem, error=True)
        self.show_plan(ev.plan)

    def show_plan(self, plan: ClipPlan | None) -> None:
        self.table.setRowCount(0)
        if plan is None:
            self.summary.setText("Keine Clips, solange die Optionen nicht stimmen.")
            return
        self.summary.setText(
            f"Je Clip {plan.bars} Takte ({plan.seconds:.1f} s bei {plan.tempo:g} BPM), "
            f"Tonart {plan.key}. Akkord je Takt (Arp und Pad): "
            f"{', '.join(map(str, plan.chords))}.")
        self.table.setRowCount(len(plan.clips))
        for r, c in enumerate(plan.clips):
            cells = [VOICE_LABELS[c.voice], str(c.notes), c.file_name]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col == 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                          | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r, col, item)
        self.table.resizeColumnsToContents()

    # --- preview -------------------------------------------------------------------------
    def preview(self, which: str) -> bool:
        """Play the rough preview of one voice (``lead`` ...) or of all chosen voices
        (:data:`ALL`). Never writes into the output folder."""
        ev = self.model.evaluate()
        if not ev.ok:
            self.set_status("Vorhören nicht möglich: " + ev.problem, error=True)
            return False
        if not self.backend.available:
            self.set_status("Keine Audioausgabe verfügbar.", error=True)
            return False
        self.stop_preview()
        try:
            if which == ALL:
                data = goa_preview.mix_preview_wav_bytes(**ev.kwargs)
            else:
                data = goa_preview.voice_preview_wav_bytes(which, **ev.kwargs)
            path = self._tmp / f"goa_preview_{which}.wav"
            path.write_bytes(data)
            self.play_file(path)
        except (ValueError, OSError, RuntimeError) as exc:
            self.set_status(f"Vorhören fehlgeschlagen: {exc}", error=True)
            return False
        self.playing = which
        what = "alle Stimmen" if which == ALL else VOICE_LABELS[which]
        self.set_status(f"Spielt: {what}, {goa_preview.PREVIEW_LABEL} "
                        f"({ev.plan.bars} Takte, ein Durchlauf).")
        return True

    def play_file(self, path: Path) -> None:
        """The one place the Goa preview reaches the sound output (16-bit WAV)."""
        self.backend.play(path)

    def stop_preview(self) -> None:
        self.playing = None
        try:
            self.backend.stop()
        except Exception:  # noqa: BLE001
            pass

    # --- export --------------------------------------------------------------------------
    def start_export(self) -> None:
        if self.running or not self.model.is_valid:
            return
        folder = self.folder_edit.text().strip()
        job = GoaJob(tuple(self.model.argv(folder)))
        self.set_status("Exportiere …")
        self.export_button.setEnabled(False)
        self.handle = self.service.start(job, on_done=self._signals.done.emit)

    def _on_done(self, result: GoaResult) -> None:
        self.handle = None
        self.result = result
        if result.error is not None:
            self.set_status(f"Fehler: {result.error.message}", error=True)
        else:
            self.readme.setPlainText(result.readme_text)
            self.drag_list.clear()
            for p in result.mid_paths:
                item = QListWidgetItem(p.name)
                item.setData(PATH_ROLE, str(p))
                item.setToolTip(str(p))
                self.drag_list.addItem(item)
            self.drag_list.setVisible(self.drag_list.count() > 0)
            self.tabs.setCurrentIndex(0)
            self.set_status(f"Fertig: {len(result.mid_paths)} MIDI-Clips und README in "
                            f"{result.out_dir}. Jede Datei unten auf eine MIDI-Spur in Live "
                            "ziehen (nicht in Live getestet).")
        self.refresh()

    def open_folder(self) -> None:
        folder = Path(self.folder_edit.text().strip())
        if not folder.is_dir() and self.result is not None and self.result.ok:
            folder = self.result.out_dir  # the last finished run
        if not folder.is_dir():
            self.set_status("Der Ordner existiert noch nicht (er entsteht beim Export).",
                            error=True)
            return
        if not self.opener(folder):
            self.set_status("Der Ordner konnte nicht geöffnet werden.", error=True)

    def shutdown(self) -> None:
        self.stop_preview()
        if self.handle is not None:
            self.handle.wait(30)
        shutil.rmtree(self._tmp, ignore_errors=True)
