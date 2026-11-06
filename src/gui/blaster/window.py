"""Blaster window v2 (D-030, D-031): the gun, groups Waffe / Salve / Filter / Delay / Reverb on the
shared widget kit, precision controls, presets, stereo scope, shot history with WAV drag-out and
bank export.

Standalone window: not a plugin, nothing happens in Live. What the shots sound like is not
judged anywhere in this window.

Rendering (a shot, a live preview, a bank) runs in a worker thread; the result comes back to the
GUI thread as a queued signal of a small relay object. The worker never touches a widget. At
most one job runs and one waits (``gui_core.blaster_params.JobQueue``): a newer job replaces the
waiting one, so dragging a control or holding the trigger never builds a queue.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from gui.drag import PATH_ROLE, DragList
from gui.widgets import Collapsible, FlowLayout, NumberControl, PresetChips, Segmented
from gui.windows import ResultActions
from gui_core import blaster_params as bp
from gui_core.blaster import (
    BANK_MAX,
    DIMENSIONS,
    BankWriter,
    BlasterSession,
    CategoryBankWriter,
    LaserEngine,
    dimension,
    export_bank,
    load_engine,
)
from gui_core.paths import default_output_dir
from gui_core.preview import PlaybackBackend
from gui_core.settings import AppSettings, free_stem
from gui_core.tasks import start_task
from gui_core.valuemap import map_of
from gui_core.waveform import peaks

from . import skin
from .fields import EnumRow, PageStack, number
from .gun import TRACE_BUCKETS, BlasterWidget
from .pads import CurveEditor, XYPad
from .scope import SalvoScope

SHOT_ROLE = Qt.ItemDataRole.UserRole + 1
NOTE = ("Eigenständiges Fenster, kein Plugin und nichts davon läuft in Live. Der Klang der "
        "Schüsse wird hier nicht bewertet. Die Live-Vorschau ist gekürzt und ersetzt nicht den "
        "Vollqualitäts-Schuss. Herausziehen in Live oder den Explorer ist nur auf Datenebene "
        "getestet.")
KEYS_HELP = ("Strg+Eingabe: Vollqualität · Strg+Z / Strg+Y: Rückgängig / Wiederholen · "
             "Strg+Auf / Ab: Seed · Strg+R: Würfeln · Strg+1 / 2: A / B · Strg+S / O: Preset. "
             "Regler: Umschalt = fein, Strg+Klick = Standard, Doppelklick = Zahl eingeben.")
PREVIEW_DELAY_MS = 150
_AUTO = object()


def _open_folder(path: Path) -> bool:
    from PySide6.QtCore import QUrl

    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def _ask_dir(parent: QWidget, start: Path) -> Path | None:
    name = QFileDialog.getExistingDirectory(parent, "Ordner für die neue Bank wählen", str(start))
    return Path(name) if name else None


def _ask_save(parent: QWidget, start: Path) -> Path | None:
    name, _ = QFileDialog.getSaveFileName(parent, "Preset speichern", str(start),
                                          "Laser-Preset (*.json)")
    return Path(name) if name else None


def _ask_open(parent: QWidget, start: Path) -> Path | None:
    name, _ = QFileDialog.getOpenFileName(parent, "Preset laden", str(start),
                                          "Laser-Preset (*.json)")
    return Path(name) if name else None


class _Relay(QObject):
    """Carries a worker's result to the GUI thread (queued: the emitter is another thread)."""

    done = Signal(str, object)
    saved = Signal(object)  # library save: (wav, sidecar) or the exception


class FormatWriter:
    """A bank writer that adds the shared sample rate / bit depth to the request."""

    def __init__(self, inner: BankWriter, overrides: dict[str, int]) -> None:
        self.inner, self.overrides = inner, overrides

    def write(self, params, seed, folder, stem, description):
        return self.inner.write({**params, **self.overrides}, seed, folder, stem, description)


class BlasterWindow(QWidget):
    def __init__(
        self,
        out_dir: Path | None = None,
        engine: LaserEngine | None | object = _AUTO,
        backend: PlaybackBackend | None = None,
        work_dir: Path | None = None,
        opener: Callable[[Path], bool] = _open_folder,
        ask_dir: Callable[[QWidget, Path], Path | None] = _ask_dir,
        bank_writer: BankWriter | None = None,
        ask_save: Callable[[QWidget, Path], Path | None] = _ask_save,
        ask_open: Callable[[QWidget, Path], Path | None] = _ask_open,
    ) -> None:
        super().__init__()
        reason = ""
        if engine is _AUTO:
            engine, reason = load_engine()
        if backend is None:
            from gui.audio import choose_backend

            backend = choose_backend()
        self.session = BlasterSession(engine, backend, work_dir, unavailable_reason=reason)  # type: ignore[arg-type]
        self.backend = backend
        self.out_dir = out_dir or default_output_dir()
        self.library_dir = AppSettings(output_dir=str(self.out_dir)).laser_dir()
        self.bank_start_dir = self.out_dir
        self.format_overrides: dict[str, int] = {}
        self.hub = None
        self._saving = False
        self._kept: dict[tuple, Path] = {}  # shot -> its library copy (save / drag, #444)
        self.opener, self.ask_dir, self.bank_writer = opener, ask_dir, bank_writer
        self.ask_save, self.ask_open = ask_save, ask_open
        self.settings = bp.BlasterSettings()
        self.undo_stack = bp.UndoStack(self.settings)
        self.ab = bp.ABSlots(self.settings)
        self.locked: set[str] = set()
        self.random_seed = 1
        self.queue = bp.JobQueue()
        self.preset_name = ""
        self._preset_cache: dict[str, bp.BlasterSettings] = {}
        self._last_echo_note = "1/8"
        self._preview_play = False
        self.autofire_count = 0
        self.autofire_skipped = 0
        self.autofire_lagging = False
        self._closed = False
        self._syncing = False
        self.num: dict[str, list[NumberControl]] = {}
        self.enums: dict[str, list[EnumRow]] = {}
        self._relay = _Relay(self)
        self._relay.done.connect(self._on_job_done)
        self._relay.saved.connect(self._on_saved)
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(PREVIEW_DELAY_MS)
        self.preview_timer.timeout.connect(self._send_preview)
        self.fire_timer = QTimer(self)
        self.fire_timer.timeout.connect(self._autofire_tick)
        stub = " (Stub-Engine, nur Test)" if getattr(engine, "is_stub", False) else ""
        self.setWindowTitle("AbeltonGod · Laser-Blaster" + stub)
        self._build()
        self._make_shortcuts()
        self._sync_all()
        self.select_dimension(self.settings.dimension)
        if engine is None:
            self.set_status(self.session.unavailable_reason, error=True)
            self.gun.set_ready(False)
        else:
            self.set_status("Bereit. Abzug drücken.")
        u = self.fontMetrics().height()
        want_w, want_h = int(u * 84), int(u * 62)
        screen = QGuiApplication.primaryScreen()
        if screen is not None:  # never taller / wider than the screen
            area = screen.availableGeometry()
            want_w, want_h = min(want_w, area.width()), min(want_h, int(area.height() * 0.95))
        self.resize(want_w, want_h)

    # ---- construction -------------------------------------------------------------------------
    def _cap(self, text: str) -> QLabel:
        lab = QLabel(text.upper())
        lab.setObjectName("cap")
        return lab

    def _panel(self) -> tuple[QFrame, QVBoxLayout]:
        f = QFrame()
        f.setObjectName("panel")
        lay = QVBoxLayout(f)
        u = self.fontMetrics().height()
        lay.setContentsMargins(int(u * 0.8), int(u * 0.6), int(u * 0.8), int(u * 0.7))
        lay.setSpacing(int(u * 0.35))
        return f, lay

    def _build(self) -> None:
        u = self.fontMetrics().height()
        root = QWidget(self)
        root.setObjectName("blasterroot")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(root)
        col = QVBoxLayout(root)
        col.setContentsMargins(int(u * 0.8), int(u * 0.6), int(u * 0.8), int(u * 0.5))
        col.setSpacing(int(u * 0.5))
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setMinimumHeight(int(u * 20))
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, int(u * 0.5), 0)
        cl.setSpacing(int(u * 0.5))
        self.scroll.setWidget(content)
        col.addWidget(self.scroll, 1)

        head = QHBoxLayout()
        title = QLabel("ABELTONGOD · LASER-BLASTER")
        title.setObjectName("title")
        head.addWidget(title)
        head.addStretch(1)
        self.anim_check = QCheckBox("Rückstoß-Animation")
        self.anim_check.setChecked(True)
        self.anim_check.setToolTip("Mündungsfeuer und Rückstoß nach jedem Schuss. "
                                   "Aus: kein Timer, keine Bewegung.")
        self.anim_check.toggled.connect(self._on_animation)
        head.addWidget(self.anim_check)
        cl.addLayout(head)

        top = QHBoxLayout()
        top.setSpacing(int(u * 0.6))
        self.gun = BlasterWidget()
        self.gun.triggered.connect(self._on_gun_triggered)
        self.gun.released.connect(self._on_gun_released)
        top.addWidget(self.gun, 5)
        top.addWidget(self._build_side(), 4)
        cl.addLayout(top, 0)
        cl.addLayout(self._build_actions())

        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(int(u * 0.6))
        grid.addWidget(self._group_weapon(), 0, 0, 1, 3)
        grid.addWidget(self._group_salvo(), 0, 3, 1, 3)
        grid.addWidget(self._group_filter(), 1, 0, 1, 2)
        grid.addWidget(self._group_delay(), 1, 2, 1, 2)
        grid.addWidget(self._group_reverb(), 1, 4, 1, 2)
        for c in range(6):
            grid.setColumnStretch(c, 1)
        cl.addWidget(body)
        keys = QLabel(KEYS_HELP)
        keys.setObjectName("muted")
        keys.setWordWrap(True)
        cl.addWidget(keys)

        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        col.addWidget(self.status)
        note = QLabel(NOTE)
        note.setObjectName("muted")
        note.setWordWrap(True)
        col.addWidget(note)

    def _build_side(self) -> QWidget:
        u = self.fontMetrics().height()
        side, sl = self._panel()
        sl.addWidget(self._cap("Presets"))
        self.chips = PresetChips(bp.laser_preset_names())
        self.chips.chosen.connect(self._on_preset_chip)
        for b in self.chips.buttons:  # German preset text as tooltip (#467 texts, #472)
            b.setToolTip(bp.preset_description(b.text()))
        self.chips.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        sl.addWidget(self.chips)
        tools = QHBoxLayout()
        self.undo_btn = QPushButton("Rückgängig")
        self.undo_btn.setToolTip("Strg+Z")
        self.undo_btn.clicked.connect(self.undo)
        self.redo_btn = QPushButton("Wiederholen")
        self.redo_btn.setToolTip("Strg+Y")
        self.redo_btn.clicked.connect(self.redo)
        self.ab_seg = Segmented(["A", "B"], accent=True)
        self.ab_seg.set_index(0)
        self.ab_seg.chosen.connect(self._on_ab)
        self.ab_seg.setToolTip("Zwei Speicherplätze für Einstellungen (Strg+1 / Strg+2)")
        self.ab_copy = QPushButton("A > B")
        self.ab_copy.setToolTip("Kopiert die aktuellen Einstellungen in den anderen Platz")
        self.ab_copy.clicked.connect(self.copy_to_other_slot)
        for w in (self.undo_btn, self.redo_btn, self.ab_seg, self.ab_copy):
            tools.addWidget(w)
        tools.addStretch(1)
        sl.addLayout(tools)
        files = QHBoxLayout()
        self.save_btn = QPushButton("Preset speichern …")
        self.save_btn.clicked.connect(self.save_preset_dialog)
        self.load_btn = QPushButton("Preset laden …")
        self.load_btn.clicked.connect(self.load_preset_dialog)
        self.rand_all_btn = QPushButton("Alles würfeln")
        self.rand_all_btn.setToolTip("Würfelt alle nicht gesperrten Gruppen (Strg+R). "
                                     "Gleicher Zufalls-Seed, gleiches Ergebnis.")
        self.rand_all_btn.clicked.connect(self._on_random_all)
        for w in (self.save_btn, self.load_btn, self.rand_all_btn):
            files.addWidget(w)
        files.addStretch(1)
        sl.addLayout(files)
        sl.addWidget(self._cap("Oszilloskop (links / rechts, ganze Datei)"))
        self.scope = SalvoScope()
        sl.addWidget(self.scope)
        # Honest caption (#447): dragging works at the data level (a library copy is offered,
        # #444); a drop into Live has not been tried.
        shots_cap = self._cap("Schüsse (herausziehen: Kopie in der Bibliothek)")
        shots_cap.setToolTip("Ziehen legt den Schuss als WAV + Sidecar in die Bibliothek und "
                             "bietet diese Datei an. Ob das Ablegen in Live klappt, ist nicht "
                             "geprüft.")
        sl.addWidget(shots_cap)
        self.history = DragList(offer=self.offer_for_drag)
        self.history.setMinimumHeight(int(u * 4.5))
        self.history.setMaximumHeight(int(u * 14))
        self.history.currentItemChanged.connect(self._on_select)
        self.history.itemDoubleClicked.connect(self._on_replay_item)
        sl.addWidget(self.history, 1)
        seed_row = QHBoxLayout()
        seed_row.addWidget(QLabel("Nächster Seed"))
        self.seed_edit = QLineEdit(str(self.session.next_seed))
        self.seed_edit.setFixedWidth(int(u * 7))
        self.seed_edit.editingFinished.connect(self._on_seed_edited)
        seed_row.addWidget(self.seed_edit)
        seed_row.addStretch(1)
        self.replay_btn = QPushButton("Nochmal abspielen")
        self.replay_btn.clicked.connect(self.replay_selected)
        seed_row.addWidget(self.replay_btn)
        sl.addLayout(seed_row)
        bank_row = QHBoxLayout()
        bank_row.addWidget(QLabel("Bank mit"))
        self.bank_count = QSpinBox()
        self.bank_count.setRange(1, BANK_MAX)
        self.bank_count.setValue(8)
        bank_row.addWidget(self.bank_count)
        bank_row.addWidget(QLabel("Schüssen"))
        bank_row.addStretch(1)
        self.bank_btn = QPushButton("Bank exportieren …")
        self.bank_btn.setToolTip("Schreibt WAV + Sidecar in einen neuen Ordner "
                                 "Samples/FX/Lasers/laser_bank_NNN, mit den aktuellen "
                                 "Einstellungen (auch Salve, Filter, Delay, Reverb). "
                                 "Vorhandene Dateien werden nie überschrieben.")
        self.bank_btn.clicked.connect(self.export_bank_dialog)
        bank_row.addWidget(self.bank_btn)
        sl.addLayout(bank_row)
        lib_row = QHBoxLayout()
        self.keep_btn = QPushButton("In Bibliothek speichern")
        self.keep_btn.setObjectName("save_to_library")
        self.keep_btn.setToolTip("Schreibt den ausgewählten Schuss (gleiche Einstellungen, "
                                 "gleicher Seed) als WAV + Sidecar nach Samples/FX/Lasers im "
                                 "Ausgabeordner. Vorhandene Dateien werden nie überschrieben.")
        self.keep_btn.clicked.connect(self.save_to_library)
        lib_row.addWidget(self.keep_btn)
        lib_row.addStretch(1)
        sl.addLayout(lib_row)
        self.actions = ResultActions()
        sl.addWidget(self.actions)
        return side

    def _build_actions(self) -> QHBoxLayout:
        u = self.fontMetrics().height()
        bar = QHBoxLayout()
        bar.setSpacing(int(u * 0.8))
        self.full_btn = QPushButton("Vollqualität rendern")
        self.full_btn.setToolTip("Rendert den echten Schuss mit allen Einstellungen (Strg+Eingabe)"
                                 ", legt ihn in die Liste und spielt ihn ab. "
                                 "Dasselbe wie der Abzug.")
        self.full_btn.clicked.connect(self.pull_trigger)
        bar.addWidget(self.full_btn)
        self.live_check = QCheckBox("Live-Vorschau (gekürzt)")
        self.live_check.setToolTip(
            "Nach jeder Änderung wird ein gekürzter Schuss gerechnet (Länge, Zerfall, Schüsse und "
            "Hall-Nachhall begrenzt) und beim Loslassen abgespielt. Nicht in der Liste, nicht "
            "zum Herausziehen. Der echte Schuss kommt mit „Vollqualität rendern“.")
        self.live_check.toggled.connect(self._on_live_toggled)
        bar.addWidget(self.live_check)
        self.auto_check = QCheckBox("Dauerfeuer beim Halten")
        self.auto_check.setToolTip(
            "Abzug gedrückt halten wiederholt die Salve im Takt der Feuerrate (ein Render pro "
            "Salve, höchstens einer wartet). Untergrenze des Takts: "
            f"{int(bp.AUTOFIRE_MIN_MS)} ms.")
        bar.addWidget(self.auto_check)
        bar.addStretch(1)
        self.busy_bar = QProgressBar()
        self.busy_bar.setRange(0, 0)
        self.busy_bar.setTextVisible(False)
        self.busy_bar.setFixedWidth(int(u * 10))
        self.busy_bar.setVisible(False)
        bar.addWidget(self.busy_bar)
        self.busy_label = QLabel("")
        self.busy_label.setObjectName("muted")
        bar.addWidget(self.busy_label)
        return bar

    # ---- group building ----------------------------------------------------------------------
    def _reg_num(self, name: str, main: bool, knob: bool) -> NumberControl:
        c = number(name, main, knob)
        self.num.setdefault(name, []).append(c)
        c.edited.connect(self._on_edited)
        c.committed.connect(self._on_committed)
        c.slider.ctrlClicked.connect(partial(self._reset, (name,)))
        c.slider.resetRequested.connect(partial(self._focus_entry, c))
        return c

    def _reg_enum(self, name: str, values, labels=None, chips=False, caption=None,
                  accent=False) -> EnumRow:
        e = EnumRow(name, values, labels, chips=chips, caption=caption, accent=accent)
        self.enums.setdefault(name, []).append(e)
        e.edited.connect(self._on_edited)
        e.committed.connect(self._on_committed)
        return e

    def _knobs(self, names: tuple[str, ...]) -> QWidget:
        w = QWidget()
        flow = FlowLayout(w, spacing=int(self.fontMetrics().height() * 0.4))
        for n in names:
            flow.addWidget(self._reg_num(n, True, True))
        return w

    def _advanced(self, g: bp.GroupDef) -> Collapsible:
        box = Collapsible("Erweitert")
        lay = QVBoxLayout(box.body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        for n in g.advanced:
            s = bp.spec(n)
            if s.kind == "enum":
                values = bp.enum_values(n)
                labels = ["normal", "invertiert"] if n == "polarity" else None
                lay.addWidget(self._reg_enum(n, values, labels))
            else:
                lay.addWidget(self._reg_num(n, False, False))
        self.advanced[g.key] = box
        return box

    def _group_frame(self, g: bp.GroupDef) -> tuple[QFrame, QVBoxLayout]:
        if not hasattr(self, "advanced"):
            self.advanced: dict[str, Collapsible] = {}
            self.state_labels: dict[str, QLabel] = {}
            self.group_frames: dict[str, QFrame] = {}
            self.lock_btns: dict[str, QPushButton] = {}
            self.rand_btns: dict[str, QPushButton] = {}
        u = self.fontMetrics().height()
        f = QFrame()
        f.setObjectName("group")
        f.setProperty("locked", False)
        lay = QVBoxLayout(f)
        lay.setContentsMargins(int(u * 0.8), int(u * 0.6), int(u * 0.8), int(u * 0.7))
        lay.setSpacing(int(u * 0.4))
        head = QHBoxLayout()
        title = QLabel(g.label.upper())
        title.setObjectName("group")
        title.setToolTip(g.hint)
        state = QLabel("")
        state.setObjectName("state")
        head.addWidget(title)
        head.addWidget(state)
        head.addStretch(1)
        rnd = QPushButton("Würfeln")
        rnd.setObjectName("mini")
        rnd.setToolTip(f"Zufallswerte für {g.label} (Zufalls-Seed zählt hoch, gesperrte Gruppen "
                       "bleiben unverändert)")
        rnd.clicked.connect(partial(self._on_random_clicked, g.key))
        lock = QPushButton("Sperren")
        lock.setObjectName("mini")
        lock.setCheckable(True)
        lock.setToolTip(f"{g.label} sperren: Würfeln und Presets ändern diese Gruppe nicht")
        lock.toggled.connect(partial(self._on_lock, g.key))
        head.addWidget(rnd)
        head.addWidget(lock)
        lay.addLayout(head)
        self.state_labels[g.key], self.group_frames[g.key] = state, f
        self.lock_btns[g.key], self.rand_btns[g.key] = lock, rnd
        return f, lay

    def _group_weapon(self) -> QFrame:
        g = bp.GROUP_BY_KEY["weapon"]
        f, lay = self._group_frame(g)
        grid = QHBoxLayout()
        grid.setSpacing(int(self.fontMetrics().height() * 0.3))
        self.dim_buttons: dict[str, QPushButton] = {}
        for d in DIMENSIONS:
            b = QPushButton(d.label)
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setToolTip(d.hint)
            b.setStyleSheet(f"QPushButton:checked {{ border: 2px solid {d.accent}; color: #ffffff;"
                            f" background: {skin.mix(skin.PANEL, d.accent, 0.22).name()}; }}")
            b.clicked.connect(self._on_dim_clicked)
            self.dim_buttons[d.key] = b
            grid.addWidget(b)
        lay.addLayout(grid)
        self.dim_hint = QLabel("")
        self.dim_hint.setObjectName("muted")
        self.dim_hint.setWordWrap(True)
        lay.addWidget(self.dim_hint)
        pads = QHBoxLayout()
        pads.setSpacing(int(self.fontMetrics().height() * 0.6))
        self.pad = XYPad("pitch_start_hz", "pitch_end_hz", map_of(bp.spec("pitch_start_hz")),
                         map_of(bp.spec("pitch_end_hz")))
        self.curve = CurveEditor(map_of(bp.spec("sweep_ms")), map_of(bp.spec("sweep_curve")))
        for w in (self.pad, self.curve):
            w.edited.connect(self._on_edited)
            w.committed.connect(self._on_committed)
        self.pad.ctrlClicked.connect(partial(self._reset, ("pitch_start_hz", "pitch_end_hz")))
        self.curve.ctrlClicked.connect(partial(self._reset, ("sweep_ms", "sweep_curve")))
        pads.addWidget(self.pad, 1)
        pads.addWidget(self.curve, 1)
        lay.addLayout(pads)
        lay.addWidget(self._reg_num("pitch_start_hz", True, False))
        lay.addWidget(self._reg_num("pitch_end_hz", True, False))
        lay.addWidget(self._knobs(("sweep_ms", "sweep_curve", "length_ms", "attack_ms",
                                   "decay_ms", "drive")))
        lay.addWidget(self._advanced(g))
        return f

    def _group_salvo(self) -> QFrame:
        g = bp.GROUP_BY_KEY["salvo"]
        f, lay = self._group_frame(g)
        count_values = bp.enum_values("salvo_count")
        lay.addWidget(self._reg_enum("salvo_count", count_values, accent=True))
        modes = bp.enum_values("salvo_rate_mode")
        lay.addWidget(self._reg_enum("salvo_rate_mode", modes,
                                     [bp.RATE_MODE_LABELS[m] for m in modes],
                                     caption="Feuerrate: Angabe in", accent=True))
        rate = QHBoxLayout()
        self.rate_stack = PageStack()
        self.rate_stack.addWidget(self._reg_num("salvo_spacing_ms", True, True))
        self.rate_stack.addWidget(self._reg_num("salvo_rate_hz", True, True))
        sync = QWidget()
        sl = QHBoxLayout(sync)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(self._reg_enum("salvo_sync_note", bp.enum_values("salvo_sync_note"),
                                    chips=True, caption=""), 1)
        sl.addWidget(self._reg_num("bpm", True, True))
        self.rate_stack.addWidget(sync)
        rate.addWidget(self.rate_stack, 1)
        rate.addWidget(self._reg_num("salvo_rate_ramp", True, True))
        lay.addLayout(rate)
        pan = bp.enum_values("salvo_pan_mode")
        lay.addWidget(self._reg_enum("salvo_pan_mode", pan, [bp.PAN_LABELS[p] for p in pan],
                                     chips=True))
        lay.addWidget(self._reg_num("salvo_pan_width", True, False))
        lay.addWidget(self._advanced(g))
        lay.addStretch(1)
        return f

    def _group_filter(self) -> QFrame:
        g = bp.GROUP_BY_KEY["filter"]
        f, lay = self._group_frame(g)
        lay.addWidget(self._knobs(g.main))
        lay.addWidget(self._advanced(g))
        lay.addStretch(1)
        return f

    def _group_delay(self) -> QFrame:
        g = bp.GROUP_BY_KEY["delay"]
        f, lay = self._group_frame(g)
        lay.addWidget(self._knobs(("echo_mix", "echo_feedback")))
        lab = QLabel("ZEIT")
        lab.setObjectName("heading")
        lay.addWidget(lab)
        self.echo_mode = Segmented(["ms", "Sync"], accent=True)
        self.echo_mode.chosen.connect(self._on_echo_mode)
        lay.addWidget(self.echo_mode)
        self.echo_stack = PageStack()
        self.echo_stack.addWidget(self._reg_num("echo_ms", True, True))
        sync = QWidget()
        sl = QHBoxLayout(sync)
        sl.setContentsMargins(0, 0, 0, 0)
        notes = [n for n in bp.enum_values("echo_sync") if n != "off"]
        sl.addWidget(self._reg_enum("echo_sync", notes, chips=True, caption=""), 1)
        sl.addWidget(self._reg_num("bpm", True, True))
        self.echo_stack.addWidget(sync)
        lay.addWidget(self.echo_stack)
        lay.addWidget(self._advanced(g))
        lay.addStretch(1)
        return f

    def _group_reverb(self) -> QFrame:
        g = bp.GROUP_BY_KEY["reverb"]
        f, lay = self._group_frame(g)
        lay.addWidget(self._knobs(g.main))
        lay.addWidget(self._advanced(g))
        lay.addStretch(1)
        return f

    def _make_shortcuts(self) -> None:
        table = {
            "undo": ("Ctrl+Z", self.undo), "redo": ("Ctrl+Y", self.redo),
            "redo2": ("Ctrl+Shift+Z", self.redo), "fire": ("Ctrl+Return", self.pull_trigger),
            "fire2": ("Ctrl+Enter", self.pull_trigger),
            "seed_up": ("Ctrl+Up", partial(self.bump_seed, 1)),
            "seed_down": ("Ctrl+Down", partial(self.bump_seed, -1)),
            "random": ("Ctrl+R", self._on_random_all),
            "slot_a": ("Ctrl+1", partial(self._slot, "A")),
            "slot_b": ("Ctrl+2", partial(self._slot, "B")),
            "save": ("Ctrl+S", self.save_preset_dialog),
            "load": ("Ctrl+O", self.load_preset_dialog),
        }
        self.shortcuts: dict[str, QShortcut] = {}
        for name, (keys, slot) in table.items():
            sc = QShortcut(QKeySequence(keys), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(slot)
            self.shortcuts[name] = sc

    # ---- status and busy state ---------------------------------------------------------------
    def set_status(self, text: str, error: bool = False) -> None:
        self.status.setText(text)
        self.status.setProperty("level", "error" if error else "info")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    @property
    def busy(self) -> bool:
        return self.queue.busy

    @property
    def job(self) -> str | None:
        return self.queue.running.kind if self.queue.running else None

    def _update_busy(self) -> None:
        busy = self.queue.busy
        kind = self.job
        self.gun.set_busy(busy)
        self.busy_bar.setVisible(busy)
        names = {"shot": "Schuss wird gerendert", "preview": "Vorschau wird gerechnet",
                 "bank": "Bank wird geschrieben"}
        waiting = " · einer wartet" if self.queue.pending is not None else ""
        self.busy_label.setText(f"{names.get(kind or '', '')}{waiting}" if busy else "")
        self.bank_btn.setEnabled(not busy)
        self.keep_btn.setEnabled(not self._saving)

    # ---- settings <-> widgets ----------------------------------------------------------------
    def current_dimension(self) -> str:
        return self.settings.dimension

    def current_settings(self) -> bp.BlasterSettings:
        return self.settings

    def _apply_settings(self, s: bp.BlasterSettings) -> None:
        self.settings = s
        self.session.settings = s
        self._sync_all()

    def _sync_all(self) -> None:
        """Show ``self.settings`` in every widget (programmatic: no signals)."""
        s = self.settings
        self._syncing = True
        try:
            for name, ctrls in self.num.items():
                for c in ctrls:
                    c.set_value(s.get(name))
            for name, rows in self.enums.items():
                for e in rows:
                    e.set_value(s.get(name))
            self.pad.set_values(s.get("pitch_start_hz"), s.get("pitch_end_hz"))
            self.curve.set_values(s.get("pitch_start_hz"), s.get("pitch_end_hz"),
                                  s.get("sweep_ms"), s.get("sweep_curve"))
            self.dim_buttons[s.dimension].setChecked(True)
            mode = s.get("salvo_rate_mode")
            self.rate_stack.setCurrentIndex(("ms", "hz", "sync").index(mode))
            sync = s.get("echo_sync") != "off"
            self.echo_mode.set_index(1 if sync else 0)
            self.echo_stack.setCurrentIndex(1 if sync else 0)
            if sync:
                self._last_echo_note = s.get("echo_sync")
            self._refresh_family_state()
            self._refresh_group_state()
            self._refresh_tools()
        finally:
            self._syncing = False

    def _refresh_family_state(self) -> None:
        d = dimension(self.settings.dimension)
        self.dim_hint.setText(f"{d.label}: {d.hint}. Der Klang ist nicht bewertet.")
        on = self.settings.dimension == "glitch"
        for c in self.num["glitch_steps"]:
            c.setEnabled(on)
            c.setToolTip(bp.spec("glitch_steps").description if on else
                         "Nur in der Familie Glitch wirksam.")

    def _refresh_group_state(self) -> None:
        for g in bp.GROUPS:
            label = self.state_labels[g.key]
            if g.switch:
                on = self.settings.group_in_use(g.key)
                text = "an" if on else "aus"
                if g.key == "salvo":
                    text = f"{self.settings.get('salvo_count')} Schüsse" if on else "1 Schuss"
            else:
                on, text = True, ""
            label.setText(text)
            label.setProperty("on", on)
            label.style().unpolish(label)
            label.style().polish(label)

    def _refresh_tools(self) -> None:
        self.undo_btn.setEnabled(self.undo_stack.can_undo())
        self.redo_btn.setEnabled(self.undo_stack.can_redo())
        self.ab_seg.set_index(0 if self.ab.active == "A" else 1)
        match = ""
        if self.preset_name:
            ref = self._preset_settings(self.preset_name)
            if ref is not None and all(self.settings.get(f) == ref.get(f)
                                       for f in bp.FIELD_NAMES):
                match = self.preset_name
        self.chips.set_current(match)

    def _preset_settings(self, name: str) -> bp.BlasterSettings | None:
        if name not in self._preset_cache:
            try:
                self._preset_cache[name] = bp.load_named_preset(name)
            except bp.BlasterError:
                return None
        return self._preset_cache[name]

    def select_dimension(self, key: str) -> None:
        if key != self.settings.dimension:
            self._apply_settings(self.settings.with_values(family=key))
        self.dim_buttons[key].setChecked(True)
        self._apply_family_look()
        self._refresh_family_state()

    def _apply_family_look(self) -> None:
        d = dimension(self.settings.dimension)
        self.gun.set_accent(d.accent)
        self.scope.set_accent(d.accent)
        self.pad.set_accent(d.accent)
        self.curve.set_accent(d.accent)
        self.setStyleSheet(skin.stylesheet(d.accent))
        for ctrls in self.num.values():
            for c in ctrls:
                c.slider.accent_color = QColor(d.accent)
                c.slider.update()

    def _on_dim_clicked(self) -> None:
        for key, b in self.dim_buttons.items():
            if b.isChecked():
                self._on_edited("family", key)
                self._on_committed("family")
                return

    # ---- edits ---------------------------------------------------------------------------------
    def _on_edited(self, name: str, value: Any) -> None:
        if self._syncing:
            return
        try:
            new = self.settings.with_values(**{name: value})
        except ValueError as exc:
            self.set_status(str(exc), error=True)
            self._sync_all()
            return
        if name == "echo_sync" and value != "off":
            self._last_echo_note = value
        self._apply_settings(new)
        if name == "family":
            self._apply_family_look()
        self._schedule_preview(False)

    def _on_committed(self, name: str = "") -> None:
        if self._syncing:
            return
        label = bp.spec(name).label if name in bp.laser_specs() else name
        self.undo_stack.record(self.settings, label)
        self._refresh_tools()
        self._schedule_preview(True)

    def _reset(self, names: tuple[str, ...], *_: Any) -> None:
        """Ctrl+click: back to the contract default."""
        self._apply_settings(self.settings.with_values(**{n: bp.default_of(n) for n in names}))
        if "family" in names:
            self._apply_family_look()
        self.undo_stack.record(self.settings, "Standard")
        self._refresh_tools()
        self.set_status("Standardwert gesetzt: " + ", ".join(bp.spec(n).label for n in names))
        self._schedule_preview(True)

    def _focus_entry(self, ctrl: NumberControl, *_: Any) -> None:
        """Double click: numeric entry in the readout."""
        ctrl.readout.setFocus(Qt.FocusReason.MouseFocusReason)
        ctrl.readout.selectAll()

    def _on_echo_mode(self, index: int) -> None:
        value = "off" if index == 0 else self._last_echo_note
        self._on_edited("echo_sync", value)
        self._on_committed("echo_sync")

    def _on_animation(self, on: bool) -> None:
        self.gun.set_animation(on)

    # ---- locks, randomise, presets, A/B, undo ------------------------------------------------
    def _on_lock(self, key: str, on: bool) -> None:
        (self.locked.add if on else self.locked.discard)(key)
        f = self.group_frames[key]
        f.setProperty("locked", on)
        f.style().unpolish(f)
        f.style().polish(f)

    def set_locked(self, key: str, on: bool) -> None:
        self.lock_btns[key].setChecked(on)

    def _on_random_clicked(self, key: str, _checked: bool = False) -> None:
        self.randomise_groups((key,))

    def _on_random_all(self, *_: Any) -> None:
        self.randomise_groups(None)

    def randomise_groups(self, keys: tuple[str, ...] | None = None) -> None:
        wanted = [g.key for g in bp.GROUPS] if keys is None else list(keys)
        free = [k for k in wanted if k not in self.locked]
        if not free:
            self.set_status("Alle gewählten Gruppen sind gesperrt; nichts gewürfelt.", error=True)
            return
        seed = self.random_seed
        self.random_seed += 1
        self._apply_settings(bp.randomise(self.settings, free, seed))
        self._apply_family_look()
        self.undo_stack.record(self.settings, "Würfeln")
        self._refresh_tools()
        names = ", ".join(bp.GROUP_BY_KEY[k].label for k in free)
        skipped = [bp.GROUP_BY_KEY[k].label for k in wanted if k in self.locked]
        extra = f" Gesperrt, unverändert: {', '.join(skipped)}." if skipped else ""
        self.set_status(f"Gewürfelt (Zufalls-Seed {seed}): {names}.{extra}")
        self._schedule_preview(True)

    def _on_preset_chip(self, name: str) -> None:
        self.apply_preset(name)

    def apply_preset(self, name: str) -> None:
        try:
            new = bp.load_named_preset(name)
        except bp.BlasterError as exc:
            self.set_status(str(exc), error=True)
            return
        free = [g.key for g in bp.GROUPS if g.key not in self.locked]
        if not free:
            self.set_status("Alle Gruppen sind gesperrt; das Preset wurde nicht geladen.",
                            error=True)
            self.chips.set_current("")
            return
        self.preset_name = name
        self._apply_settings(bp.apply_groups(self.settings, new, free))
        self._apply_family_look()
        self.undo_stack.record(self.settings, f"Preset {name}")
        self._refresh_tools()
        kept = [bp.GROUP_BY_KEY[k].label for k in self.locked]
        extra = f" Gesperrt, unverändert: {', '.join(kept)}." if kept else ""
        self.set_status(f"Preset „{name}“ geladen.{extra}")
        self._schedule_preview(True)

    def undo(self) -> None:
        s = self.undo_stack.undo()
        if s is None:
            self.set_status("Nichts zum Rückgängigmachen.")
            return
        self._apply_settings(s)
        self._apply_family_look()
        self._refresh_tools()
        self.set_status("Rückgängig gemacht.")

    def redo(self) -> None:
        s = self.undo_stack.redo()
        if s is None:
            self.set_status("Nichts zum Wiederholen.")
            return
        self._apply_settings(s)
        self._apply_family_look()
        self._refresh_tools()
        self.set_status("Wiederholt.")

    def _on_ab(self, index: int) -> None:
        self._slot("AB"[index])

    def _slot(self, which: str, *_: Any) -> None:
        if which == self.ab.active:
            return
        self._apply_settings(self.ab.switch(which, self.settings))
        self._apply_family_look()
        self.undo_stack.record(self.settings, f"Platz {which}")
        self._refresh_tools()
        self.set_status(f"Platz {which}.")

    def copy_to_other_slot(self) -> None:
        other = self.ab.copy_to_other(self.settings)
        self.set_status(f"Einstellungen in Platz {other} kopiert.")

    def save_preset_dialog(self, *_: Any) -> None:
        start = self.out_dir / "laser-preset.json"
        path = self.ask_save(self, start)
        if path is None:
            self.set_status("Speichern abgebrochen.")
            return
        try:
            bp.save_settings_file(Path(path), self.settings, self.session.next_seed,
                                  self.preset_name)
        except bp.BlasterError as exc:
            self.set_status(str(exc), error=True)
            return
        self.set_status(f"Preset gespeichert: {path}")

    def load_preset_dialog(self, *_: Any) -> None:
        path = self.ask_open(self, self.out_dir)
        if path is None:
            self.set_status("Laden abgebrochen.")
            return
        self.load_preset_file(Path(path))

    def load_preset_file(self, path: Path) -> None:
        try:
            s, seed, name = bp.load_settings_file(path)
        except bp.BlasterError as exc:
            self.set_status(f"Preset nicht geladen: {exc}", error=True)
            return
        self.preset_name = name
        if seed is not None:
            self.session.next_seed = seed
            self._sync_seed_field()
        self._apply_settings(s)
        self._apply_family_look()
        self.undo_stack.record(self.settings, "Datei")
        self._refresh_tools()
        self.set_status(f"Preset geladen: {path}")
        self._schedule_preview(True)

    # ---- seed ----------------------------------------------------------------------------------
    def bump_seed(self, delta: int, *_: Any) -> None:
        self.session.next_seed = min(bp.SEED_MAX, max(0, self.session.next_seed + delta))
        self._sync_seed_field()

    def _on_seed_edited(self) -> None:
        text = self.seed_edit.text().strip()
        try:
            v = int(text)
            if not 0 <= v <= bp.SEED_MAX:
                raise ValueError
        except ValueError:
            self._mark_seed(True)
            self.set_status(f"Seed muss eine ganze Zahl von 0 bis {bp.SEED_MAX} sein.",
                            error=True)
            return
        self._mark_seed(False)
        self.session.next_seed = v

    def _mark_seed(self, invalid: bool) -> None:
        self.seed_edit.setProperty("invalid", invalid)
        self.seed_edit.style().unpolish(self.seed_edit)
        self.seed_edit.style().polish(self.seed_edit)

    def _sync_seed_field(self) -> None:
        self.seed_edit.setText(str(self.session.next_seed))
        self._mark_seed(False)

    # ---- jobs (worker thread, one running + one waiting) ------------------------------------
    def _submit(self, kind: str, meta: Any) -> str:
        res = self.queue.submit(bp.Job(kind, None, meta))
        if res == "started":
            self._launch(self.queue.running)  # type: ignore[arg-type]
        self._update_busy()
        return res

    def _launch(self, job: bp.Job) -> None:
        s = self.session
        if job.kind == "shot":
            settings, seed = job.meta, s.next_seed
            job.meta = (settings, seed)
            job.fn = partial(self._render_full, settings, seed)
        elif job.kind == "preview":
            settings, play = job.meta
            job.fn = partial(s.render_preview, settings, s.next_seed)
        else:
            settings, count, chosen = job.meta
            first = s.next_seed
            job.meta = (first,)
            job.fn = partial(self._write_bank, settings, first, count, chosen)
        threading.Thread(target=self._work, args=(job,), name=f"blaster-{job.kind}",
                         daemon=True).start()

    def _render_full(self, settings: bp.BlasterSettings, seed: int):
        return (settings, seed, *self.session.render_shot(settings, seed))

    def _write_bank(self, settings, first, count, chosen):
        return first, export_bank(settings, first, count, chosen, self._writer())

    def _work(self, job: bp.Job) -> None:
        try:
            result: Any = job.fn()  # type: ignore[misc]
        except BaseException as exc:  # noqa: BLE001 - the GUI must always hear back
            result = exc
        try:
            self._relay.done.emit(job.kind, result)
        except RuntimeError:  # window already destroyed
            pass

    def _on_job_done(self, kind: str, result: Any) -> None:
        job = self.queue.running
        try:
            if job is not None and not self._closed:
                if kind == "shot":
                    self._shot_done(result)
                elif kind == "preview":
                    self._preview_done(job, result)
                else:
                    self._bank_done(result)
        finally:
            nxt = self.queue.finish()
            if nxt is not None and not self._closed:
                self._launch(nxt)
            elif nxt is not None:
                self.queue.running = None
            if not self._closed:
                self._update_busy()

    # ---- actions ----------------------------------------------------------------------------
    def pull_trigger(self, *_: Any) -> str | None:
        """Render the next shot in full quality (worker thread), keep and play it."""
        if self.seed_edit.property("invalid"):
            self.set_status("Der Seed ist ungültig; Schuss nicht ausgelöst.", error=True)
            return None
        if self.session.engine is None:
            self.set_status(self.session.unavailable_reason, error=True)
            return None
        res = self._submit("shot", self.settings)
        if res == "started":
            self.set_status("Schuss wird gerendert …")
        elif res in ("queued", "replaced"):
            self.set_status("Der vorige Render läuft noch; der nächste Schuss wartet (einer).")
        return res

    def _shot_done(self, result: Any) -> None:
        if isinstance(result, BaseException):
            msg = str(result) if isinstance(result, bp.BlasterError) else (
                f"Unerwarteter Fehler: {type(result).__name__}: {result}")
            self.set_status(msg, error=True)
            return
        settings, seed, samples, params = result
        res = self.session.commit(settings, seed, samples, params)
        if res.shot is None:
            self.set_status(res.message, error=True)
            return
        shot = res.shot
        item = QListWidgetItem(shot.label())
        item.setData(PATH_ROLE, str(shot.wav_path))
        item.setData(SHOT_ROLE, shot.index)
        self.history.insertItem(0, item)
        while self.history.count() > self.session.history_limit:
            self.history.takeItem(self.history.count() - 1)
        self.history.blockSignals(True)
        self.history.setCurrentRow(0)
        self.history.blockSignals(False)
        self._show_shot(shot)
        self._sync_seed_field()
        self.gun.flash()
        self.set_status(res.message if res.message else f"Schuss {shot.label()}",
                        error=res.error)

    def _show_shot(self, shot) -> None:
        self.gun.set_trace(peaks(shot.mono, TRACE_BUCKETS))
        self.scope.set_audio(shot.samples, shot.sample_rate, preview=False)

    def _shot_of(self, item: QListWidgetItem | None):
        if item is None:
            return None
        idx = item.data(SHOT_ROLE)
        return next((s for s in self.session.history if s.index == idx), None)

    def _on_select(self, cur: QListWidgetItem | None, _prev=None) -> None:
        shot = self._shot_of(cur)
        if shot is not None:
            self._show_shot(shot)

    def _on_replay_item(self, item: QListWidgetItem) -> None:
        self._replay(self._shot_of(item))

    def replay_selected(self) -> None:
        self._replay(self._shot_of(self.history.currentItem()))

    def _replay(self, shot) -> None:
        if shot is None:
            self.set_status("Noch kein Schuss ausgewählt.", error=True)
            return
        res = self.session.replay(shot)
        self.set_status(res.message or f"Wiederholt: {shot.label()}", error=res.error)

    # ---- live preview ----------------------------------------------------------------------
    def _on_live_toggled(self, on: bool) -> None:
        if on:
            self._schedule_preview(False)
        else:
            self.preview_timer.stop()

    def _schedule_preview(self, play: bool) -> None:
        if not self.live_check.isChecked() or self.session.engine is None or self._syncing:
            return
        self._preview_play = self._preview_play or play
        self.preview_timer.start()

    def _send_preview(self) -> None:
        play, self._preview_play = self._preview_play, False
        self._submit("preview", (self.settings, play))

    def _preview_done(self, job: bp.Job, result: Any) -> None:
        _settings, play = job.meta
        if isinstance(result, BaseException):
            msg = str(result) if isinstance(result, bp.BlasterError) else (
                f"Unerwarteter Fehler: {type(result).__name__}: {result}")
            self.set_status("Vorschau: " + msg, error=True)
            return
        samples, _params = result
        self.scope.set_audio(samples, self.session.sample_rate, preview=True)
        capped = bp.capped_fields(_settings)
        note = f" Gekürzt: {', '.join(capped)}." if capped else ""
        text = "Vorschau (gekürzt gerechnet)." + note + " Der echte Schuss: Vollqualität rendern."
        if play:
            res = self.session.play_preview(samples)
            if res.message:
                text, err = res.message, res.error
                self.set_status(text, error=err)
                return
        self.set_status(text)

    # ---- hold to autofire ------------------------------------------------------------------
    def _on_gun_triggered(self) -> None:
        self.pull_trigger()
        if self.auto_check.isChecked() and self.session.engine is not None:
            self.autofire_count, self.autofire_skipped, self.autofire_lagging = 1, 0, False
            self.fire_timer.start(int(bp.autofire_interval_ms(self.settings)))

    def _on_gun_released(self) -> None:
        if self.fire_timer.isActive():
            self.fire_timer.stop()
            msg = f"Dauerfeuer beendet: {self.autofire_count} Salven ausgelöst"
            if self.autofire_skipped:
                msg += f", {self.autofire_skipped} ausgelassen (Render zu langsam für den Takt)"
            self.set_status(msg + ".", error=bool(self.autofire_skipped))

    def _autofire_tick(self) -> None:
        if not self.gun.pressed:
            self.fire_timer.stop()
            return
        interval = int(bp.autofire_interval_ms(self.settings))
        self.fire_timer.setInterval(interval)
        if self.queue.pending is not None:  # one already waits: never a second
            self.autofire_skipped += 1
            self.autofire_lagging = True
            self.set_status(
                f"Dauerfeuer kommt nicht hinterher: Ein Render dauert länger als der Takt von "
                f"{interval} ms. {self.autofire_skipped} Salven ausgelassen.", error=True)
            return
        self.autofire_count += 1
        self.pull_trigger()

    # ---- bank ---------------------------------------------------------------------------------
    def export_bank_dialog(self) -> None:
        if self.busy:
            return
        chosen = self.ask_dir(self, self.bank_start_dir)
        if chosen is None:
            self.set_status("Bank-Export abgebrochen.")
            return
        self.export_bank_to(chosen)

    def export_bank_to(self, chosen: Path) -> None:
        """Write the bank in a worker thread (N renders); the result arrives via the relay."""
        if self.busy:
            return
        if self.session.engine is None:
            self.set_status(self.session.unavailable_reason, error=True)
            return
        count = self.bank_count.value()
        shots = self.settings.get("salvo_count")
        what = f"{count} Salven à {shots} Schüsse" if shots > 1 else f"{count} Schüssen"
        self.set_status(f"Bank mit {what} wird geschrieben …")
        self._submit("bank", (self.settings, count, chosen))

    def _bank_done(self, result: Any) -> None:
        if isinstance(result, BaseException):
            self.set_status(f"Unerwarteter Fehler: {type(result).__name__}: {result}", error=True)
            return
        first, res = result
        self.session.next_seed = first + len(res.files)  # only written shots count
        self._sync_seed_field()
        self.set_status(res.message, error=res.error)
        if res.folder is not None and res.files:
            wavs = [w for w, _side in res.files]
            self.actions.set_paths(wavs)
            if self.hub is not None:
                self.hub.files_written.emit(wavs)
            self.opener(res.folder)

    # ---- library / shared settings (#439) ---------------------------------------------------
    def _writer(self) -> BankWriter:
        inner = self.bank_writer or CategoryBankWriter()
        return FormatWriter(inner, dict(self.format_overrides)) if self.format_overrides \
            else inner

    def attach_hub(self, hub) -> None:
        """Shared output folder and audio format, library and Live hand-off (main window)."""
        self.hub = hub
        self.actions.set_hub(hub)
        self._settings_changed(hub.settings)
        hub.settings_changed.connect(self._settings_changed)

    def _settings_changed(self, settings) -> None:
        self.out_dir = settings.output_root()
        self.library_dir = settings.laser_dir()
        self.bank_start_dir = settings.bank_start_dir()
        self.format_overrides = settings.format_overrides()

    def save_to_library(self, *_: Any) -> bool:
        """Write the selected shot (or the newest) through the laser category: WAV + sidecar in
        ``<out>/Samples/FX/Lasers``, a free name, never overwriting. Worker thread."""
        if self._saving:
            return False
        shot = self._shot_of(self.history.currentItem()) or (
            self.session.history[0] if self.session.history else None)
        if shot is None:
            self.set_status("Noch kein Schuss zum Speichern.", error=True)
            return False
        key = self._kept_key(shot)
        known = self._kept.get(key)
        if known is not None and known.is_file():
            self._kept_done(known, "Schon in der Bibliothek")
            return True
        work = partial(self._write_shot, shot, self.library_dir, self._writer())
        self._saving = True
        self._update_busy()
        self.set_status("Schuss wird in die Bibliothek geschrieben …")
        start_task(work, partial(self._save_finished, key), name="blaster-save")
        return True

    def _kept_key(self, shot) -> tuple:
        return (shot.index, str(self.library_dir), tuple(sorted(self.format_overrides.items())))

    @staticmethod
    def _write_shot(shot, folder: Path, writer: BankWriter) -> tuple[Path, Path]:
        """Re-render ``shot`` (same params, same seed: same bytes as the shot when no format is
        set) through the laser category writer: WAV + sidecar, never overwriting."""
        dim = dimension(shot.settings.dimension)
        text = f"Laser-Schuss, Dimension {dim.label}, Seed {shot.seed}, aus dem Blaster."
        folder.mkdir(parents=True, exist_ok=True)
        stem = free_stem(folder, f"laser_{shot.settings.dimension}_s{shot.seed}")
        return writer.write(dict(shot.params), shot.seed, folder, stem, text)

    def _save_finished(self, key: tuple, handle) -> None:  # worker thread: only the relay
        try:
            self._relay.saved.emit((key, handle.error if handle.error is not None
                                    else handle.result))
        except RuntimeError:  # window already destroyed
            pass

    def _on_saved(self, payload: Any) -> None:
        self._saving = False
        if self._closed:
            return
        self._update_busy()
        key, result = payload
        if isinstance(result, BaseException):
            self.set_status(f"Speichern fehlgeschlagen: {self._error_text(result)}", error=True)
            return
        wav, _side = result
        self._kept[key] = wav
        self._kept_done(wav, "In der Bibliothek")

    @staticmethod
    def _error_text(exc: BaseException) -> str:
        return str(exc) if isinstance(exc, (bp.BlasterError, OSError)) else (
            f"{type(exc).__name__}: {exc}")

    def _kept_done(self, wav: Path, what: str) -> None:
        self.actions.set_paths([wav])
        if self.hub is not None:
            self.hub.files_written.emit([wav])
        self.set_status(f"{what}: {wav}")

    def offer_for_drag(self, path: Path) -> Path | None:
        """What a drag from the shot list offers for ``path`` (#444): never a file in the
        session's temporary folder, which is trimmed after the history limit and deleted on
        close (Live would then play silence). A shot is written to the library first (GUI
        thread, one render) and that copy is offered; None (the row is left out) if that
        fails."""
        path = Path(path)
        shot = next((s for s in self.session.history if s.wav_path == path), None)
        if shot is None:
            return None if self._in_work_dir(path) else path
        key = self._kept_key(shot)
        known = self._kept.get(key)
        if known is not None and known.is_file():
            return known
        try:
            wav, _side = self._write_shot(shot, self.library_dir, self._writer())
        except Exception as exc:  # noqa: BLE001 - a failed drag must not end the program
            self.set_status("Ziehen nicht möglich, der Schuss konnte nicht in die Bibliothek "
                            f"geschrieben werden: {self._error_text(exc)}", error=True)
            return None
        self._kept[key] = wav
        self._kept_done(wav, "Für das Ziehen in die Bibliothek geschrieben")
        return wav

    def _in_work_dir(self, path: Path) -> bool:
        try:
            Path(path).resolve().relative_to(Path(self.session.work_dir).resolve())
        except ValueError:
            return False
        return True

    def closeEvent(self, e) -> None:  # noqa: N802
        self._closed = True
        self.preview_timer.stop()
        self.fire_timer.stop()
        self.gun.set_animation(False)
        self.session.close()
        super().closeEvent(e)
