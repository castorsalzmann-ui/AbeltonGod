"""Live import page: pick a WAV, read the set, choose track and scene, check the plan, import.

All Live logic is ``gui_core.live`` (the import path of scripts/live_import.py on
``bridge.clip_import``). This widget only shows it. Everything that talks to Live runs in a
worker thread."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from bridge.capabilities import CapabilityRegistry
from gui_core.library import scan_library
from gui_core.live import (
    ImportPlan,
    ImportResult,
    LiveConfig,
    LiveInspection,
    capability_rows,
    execute_import,
    gate_text,
    inspect_live,
    prepare_import,
)
from gui_core.tasks import start_task

from .tool_style import STYLE

BODY_HOOK = "live_body"
NEW_TRACK_TEXT = "Neue Audiospur am Ende"


class _Signals(QObject):
    inspected = Signal(object)
    planned = Signal(object)
    imported = Signal(object)


class LivePanel(QWidget):
    def __init__(
        self,
        config: LiveConfig | None = None,
        registry: CapabilityRegistry | None = None,
        library_folder: Callable[[], Path] = lambda: Path("."),
    ) -> None:
        super().__init__()
        self.setObjectName(BODY_HOOK)
        self.setStyleSheet(STYLE)
        self.config = config or LiveConfig.from_env()
        self._registry = registry
        self.library_folder = library_folder
        self.inspection: LiveInspection | None = None
        self.plan: ImportPlan | None = None
        self.busy = False
        self._extra_wavs: list[Path] = []
        self._signals = _Signals()
        self._signals.inspected.connect(self._on_inspected)
        self._signals.planned.connect(self._on_planned)
        self._signals.imported.connect(self._on_imported)

        lay = QVBoxLayout(self)
        head = QLabel("Live-Import")
        head.setObjectName("heading")
        lay.addWidget(head)
        intro = QLabel(
            "Importiert eine WAV als Clip in die Session-Ansicht des geöffneten Live-Sets, über "
            "AbletonOSC. Nur mit einem Test-Set benutzen. Hier ist nichts in Live getestet, "
            "was die Registry nicht als 'tested' führt; ob es in deinem Set klappt, zeigt erst "
            "ein Lauf bei dir.")
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        intro.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        lay.addWidget(intro)

        form = QFormLayout()
        row = QHBoxLayout()
        self.wav_box = QComboBox()
        self.wav_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.wav_box.setMinimumContentsLength(24)
        row.addWidget(self.wav_box, 1)
        self.reload_button = QPushButton("Bibliothek lesen")
        self.pick_button = QPushButton("Andere Datei …")
        row.addWidget(self.reload_button)
        row.addWidget(self.pick_button)
        form.addRow("WAV", row)
        self.track_box = QComboBox()
        self.track_box.addItem(NEW_TRACK_TEXT, None)
        form.addRow("Ziel-Spur", self.track_box)
        self.slot_spin = QSpinBox()
        self.slot_spin.setRange(0, 999)
        self.slot_spin.setSpecialValueText("erste freie Zelle")
        form.addRow("Szene (Zelle)", self.slot_spin)
        lay.addLayout(form)

        self.gate_label = QLabel()
        self.gate_label.setWordWrap(True)
        self.gate_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        lay.addWidget(self.gate_label)
        self.unverified_check = QCheckBox(
            "Ich weiß, dass diese Live-Funktionen 'nicht verifiziert' sind, und will trotzdem "
            "importieren")
        lay.addWidget(self.unverified_check)

        buttons = QHBoxLayout()
        self.inspect_button = QPushButton("Live-Set lesen")
        self.plan_button = QPushButton("Plan prüfen")
        buttons.addWidget(self.inspect_button)
        buttons.addWidget(self.plan_button)
        buttons.addStretch(1)
        lay.addLayout(buttons)
        self.plan_text = QPlainTextEdit()
        self.plan_text.setReadOnly(True)
        self.plan_text.setPlaceholderText("Hier steht der Plan, bevor etwas an Live geht.")
        self.plan_text.setMaximumHeight(self.fontMetrics().height() * 10)
        lay.addWidget(self.plan_text)
        self.testset_check = QCheckBox(
            "Das geöffnete Set ist ein eigenes Test-Set (kein echtes Projekt)")
        lay.addWidget(self.testset_check)
        self.import_button = QPushButton("In Live importieren")
        self.import_button.setObjectName("primary")
        lay.addWidget(self.import_button)
        self.status = QLabel()
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        lay.addWidget(self.status)
        lay.addWidget(self._heading("Aktions-Log dieses Laufs"))
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        lay.addWidget(self.log_view, 1)

        self.reload_button.clicked.connect(self.reload_library)
        self.pick_button.clicked.connect(self._pick_file)
        self.inspect_button.clicked.connect(self.start_inspect)
        self.plan_button.clicked.connect(self.start_plan)
        self.import_button.clicked.connect(self.start_import)
        for sig in (self.wav_box.currentIndexChanged, self.track_box.currentIndexChanged,
                    self.slot_spin.valueChanged):
            sig.connect(self._inputs_changed)
        self.unverified_check.toggled.connect(self._inputs_changed)
        self.testset_check.toggled.connect(self._update_state)
        self._show_gate()
        self.reload_library()
        self._update_state()

    @staticmethod
    def _heading(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("heading")
        return label

    # --- gate ----------------------------------------------------------------------------
    def registry(self) -> CapabilityRegistry:
        if self._registry is None:
            self._registry = CapabilityRegistry.from_file()
        return self._registry

    def _show_gate(self) -> None:
        try:
            rows = capability_rows(self.registry())
        except Exception as exc:  # noqa: BLE001 - a broken registry is shown, not a crash
            self.gate_label.setText(f"Capability-Registry nicht lesbar: {exc}")
            self.unverified_check.setVisible(False)
            self._gate_ok = False
            return
        self._gate_ok = True
        self.gate_label.setText(gate_text(rows))
        self.unverified_check.setVisible(any(not r.verified for r in rows))

    @property
    def needs_unverified_ok(self) -> bool:
        return self.unverified_check.isVisibleTo(self)

    # --- inputs --------------------------------------------------------------------------
    def reload_library(self) -> None:
        current = self.wav_box.currentData()
        self.wav_box.blockSignals(True)
        self.wav_box.clear()
        for e in scan_library(self.library_folder()):
            self.wav_box.addItem(f"{e.name}   ({e.category})", str(e.wav_path))
        for p in self._extra_wavs:
            self.wav_box.addItem(f"{p.name}   (gewählt)", str(p))
        idx = self.wav_box.findData(current)
        self.wav_box.setCurrentIndex(idx if idx >= 0 else (0 if self.wav_box.count() else -1))
        self.wav_box.blockSignals(False)
        self._inputs_changed()

    def _pick_file(self) -> None:
        picked, _ = QFileDialog.getOpenFileName(self, "WAV wählen", str(self.library_folder()),
                                                "WAV (*.wav)")
        if picked:
            self.add_wav(Path(picked))

    def add_wav(self, path: Path) -> None:
        self._extra_wavs.append(path)
        self.wav_box.addItem(f"{path.name}   (gewählt)", str(path))
        self.wav_box.setCurrentIndex(self.wav_box.count() - 1)

    @property
    def wav_path(self) -> str | None:
        return self.wav_box.currentData()

    def _inputs_changed(self, *_a) -> None:
        self.plan = None  # a plan belongs to exactly these inputs
        self.plan_text.clear()
        self._update_state()

    def selected_track(self) -> int | None:
        return self.track_box.currentData()

    def selected_slot(self) -> int | None:
        v = self.slot_spin.value()
        return None if v == 0 else v - 1

    def _accept(self) -> bool:
        return self.unverified_check.isChecked()

    def set_status(self, text: str, error: bool = False) -> None:
        self.status.setText(text)
        self.status.setProperty("level", "error" if error else "ok")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _update_state(self, *_a) -> None:
        have_wav = self.wav_path is not None
        gate_ok = getattr(self, "_gate_ok", False)
        unv = (not self.needs_unverified_ok) or self._accept()
        idle = not self.busy
        self.inspect_button.setEnabled(have_wav and idle and gate_ok)
        self.plan_button.setEnabled(have_wav and idle and gate_ok and self.inspection is not None
                                    and self.inspection.ok)
        self.import_button.setEnabled(
            idle and gate_ok and self.plan is not None and self.plan.ok
            and self.testset_check.isChecked() and unv)

    # --- actions -------------------------------------------------------------------------
    def start_inspect(self) -> None:
        if self.busy or self.wav_path is None:
            return
        self.busy = True
        self.set_status("Liest das Live-Set …")
        self._update_state()
        cfg, wav, reg, acc = self.config, self.wav_path, self.registry(), self._accept()
        start_task(lambda: inspect_live(cfg, wav, reg, acc),
                   lambda h: self._signals.inspected.emit(h.result if h.error is None
                                                          else h.error), name="live-inspect")

    def _on_inspected(self, res: object) -> None:
        self.busy = False
        if not isinstance(res, LiveInspection):
            self.inspection = None
            self.set_status(f"Unerwarteter Fehler: {res!r}", error=True)
            self._update_state()
            return
        self.inspection = res
        self.plan = None
        if res.ok:
            current = self.track_box.currentData()
            self.track_box.blockSignals(True)
            self.track_box.clear()
            self.track_box.addItem(NEW_TRACK_TEXT, None)
            for t in res.tracks:
                self.track_box.addItem(t.label, t.index)
                if not t.is_audio:
                    item = self.track_box.model().item(self.track_box.count() - 1)
                    item.setEnabled(False)
            idx = self.track_box.findData(current)
            self.track_box.setCurrentIndex(max(idx, 0))
            self.track_box.blockSignals(False)
            self.slot_spin.setMaximum(res.num_scenes)
            sample = f" Sample: {res.sample.label}." if res.sample else ""
            self.set_status(f"Live {res.live_version}: {len(res.tracks)} Spuren, "
                            f"{res.num_scenes} Szenen.{sample} Nichts wurde geändert.")
        else:
            self.set_status(res.error, error=True)
        self._update_state()

    def start_plan(self) -> None:
        if self.busy or self.wav_path is None:
            return
        self.busy = True
        self.set_status("Prüft den Plan …")
        self._update_state()
        cfg, wav, reg, acc = self.config, self.wav_path, self.registry(), self._accept()
        track, slot = self.selected_track(), self.selected_slot()
        start_task(lambda: prepare_import(cfg, wav, track, slot, reg, acc),
                   lambda h: self._signals.planned.emit(h.result if h.error is None
                                                        else h.error), name="live-plan")

    def _on_planned(self, res: object) -> None:
        self.busy = False
        if not isinstance(res, ImportPlan):
            self.plan = None
            self.set_status(f"Unerwarteter Fehler: {res!r}", error=True)
        elif res.ok:
            self.plan = res
            self.plan_text.setPlainText(res.text)
            self.set_status("Plan steht. Test-Set bestätigen, dann kann importiert werden.")
        else:
            self.plan = None
            self.plan_text.setPlainText(res.error)
            self.set_status(res.error, error=True)
        self._update_state()

    def start_import(self) -> None:
        if self.busy or self.plan is None or not self.plan.ok:
            return
        if not self.testset_check.isChecked():
            return
        self.busy = True
        self.set_status("Importiert …")
        self._update_state()
        cfg, plan, reg, acc = self.config, self.plan, self.registry(), self._accept()
        start_task(lambda: execute_import(cfg, plan, True, reg, acc),
                   lambda h: self._signals.imported.emit(h.result if h.error is None
                                                         else h.error), name="live-import")

    def _on_imported(self, res: object) -> None:
        self.busy = False
        self.plan = None  # the set changed: a new plan is needed for the next import
        if not isinstance(res, ImportResult):
            self.set_status(f"Unerwarteter Fehler: {res!r}", error=True)
            self._update_state()
            return
        self.set_status(res.message, error=not res.ok)
        self.log_view.setPlainText("\n".join([*res.steps, "--- Aktions-Log ---", *res.log_lines]))
        self._update_state()
