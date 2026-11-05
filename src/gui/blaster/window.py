"""Blaster window: gun, dimension selector, sliders, shot history with WAV drag-out, bank export.

Standalone window (D-030): not a plugin, not inside Live. What the shots sound like is not
judged anywhere in this window.

Rendering (a shot, a bank) runs in a worker thread; the result comes back to the GUI thread as
a queued signal of a small relay object. The worker never touches a widget. While a job runs,
the trigger and the bank button are blocked and the energy cell shows "charging".
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from gui.drag import PATH_ROLE, DragList
from gui_core.blaster import (
    BANK_MAX,
    DIMENSIONS,
    SEED_MAX,
    SLIDERS,
    BankWriter,
    BlasterError,
    BlasterSession,
    BlasterSettings,
    LaserEngine,
    dimension,
    export_bank,
    load_engine,
)
from gui_core.paths import default_output_dir
from gui_core.preview import PlaybackBackend
from gui_core.waveform import peaks

from . import skin
from .gun import TRACE_BUCKETS, BlasterWidget

SHOT_ROLE = Qt.ItemDataRole.UserRole + 1
NOTE = ("Eigenständiges Fenster, kein Plugin und nicht in Live. Der Klang der Schüsse wird hier "
        "nicht bewertet; Herausziehen in Live oder den Explorer ist nur auf Datenebene getestet.")
_AUTO = object()


def _open_folder(path: Path) -> bool:
    from PySide6.QtCore import QUrl

    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def _ask_dir(parent: QWidget, start: Path) -> Path | None:
    name = QFileDialog.getExistingDirectory(parent, "Ordner für die neue Bank wählen", str(start))
    return Path(name) if name else None


class _Relay(QObject):
    """Carries a worker's result to the GUI thread (queued: the emitter is another thread)."""

    done = Signal(str, object)


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
        self.opener, self.ask_dir, self.bank_writer = opener, ask_dir, bank_writer
        self.job: str | None = None  # "shot" | "bank" while a worker runs
        self._closed = False
        self._relay = _Relay(self)
        self._relay.done.connect(self._on_job_done)
        stub = " (Stub-Engine, nur Test)" if getattr(engine, "is_stub", False) else ""
        self.setWindowTitle("AbeltonGod · Laser-Blaster" + stub)
        self.setStyleSheet(skin.STYLESHEET)
        self._build()
        self._on_dimension(DIMENSIONS[0].key)
        if engine is None:
            self.set_status(self.session.unavailable_reason, error=True)
            self.gun.set_ready(False)
        else:
            self.set_status("Bereit. Abzug drücken.")
        u = self.fontMetrics().height()
        self.resize(int(u * 66), int(u * 52))

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
        col.addLayout(head)

        self.gun = BlasterWidget()
        self.gun.triggered.connect(self.pull_trigger)
        col.addWidget(self.gun, 5)

        row = QHBoxLayout()
        row.setSpacing(int(u * 0.6))
        # --- left: dimension + sliders
        left, ll = self._panel()
        ll.addWidget(self._cap("Dimension"))
        grid = QGridLayout()
        grid.setSpacing(int(u * 0.3))
        self.dim_buttons: dict[str, QPushButton] = {}
        for i, d in enumerate(DIMENSIONS):
            b = QPushButton(d.label)
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setToolTip(d.hint)
            b.setStyleSheet(f"QPushButton:checked {{ border: 2px solid {d.accent}; color: #ffffff;"
                            f" background: {skin.mix(skin.PANEL, d.accent, 0.22).name()}; }}")
            b.clicked.connect(self._on_dim_clicked)
            self.dim_buttons[d.key] = b
            grid.addWidget(b, 0, i)
        ll.addLayout(grid)
        self.dim_hint = QLabel("")
        self.dim_hint.setObjectName("muted")
        ll.addWidget(self.dim_hint)
        sg = QGridLayout()
        sg.setHorizontalSpacing(int(u * 0.7))
        sg.setVerticalSpacing(int(u * 0.1))
        defaults = BlasterSettings()
        self.sliders: dict[str, QSlider] = {}
        self.readouts: dict[str, QLabel] = {}
        self.slider_labels: dict[str, QLabel] = {}
        half = (len(SLIDERS) + 1) // 2
        for i, spec in enumerate(SLIDERS):
            r, c = i % half, (i // half) * 3
            sl = QSlider(Qt.Orientation.Horizontal)
            sl.setRange(0, 100)
            sl.setValue(defaults.position(spec.name))
            sl.valueChanged.connect(self._on_slider)
            ro = QLabel("")
            ro.setMinimumWidth(int(u * 3.6))
            ro.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lab = QLabel(spec.label)
            self.sliders[spec.name], self.readouts[spec.name] = sl, ro
            self.slider_labels[spec.name] = lab
            sg.addWidget(lab, r, c)
            sg.addWidget(sl, r, c + 1)
            sg.addWidget(ro, r, c + 2)
        sg.setColumnStretch(1, 1)
        sg.setColumnStretch(4, 1)
        sg.setColumnMinimumWidth(3, int(u * 1.2))
        ll.addLayout(sg)
        row.addWidget(left, 6)

        # --- right: history + seed + bank
        right, rl = self._panel()
        rl.addWidget(self._cap("Schüsse (in Live oder Explorer ziehen)"))
        self.history = DragList()
        self.history.setMinimumHeight(int(u * 6))
        self.history.currentItemChanged.connect(self._on_select)
        self.history.itemDoubleClicked.connect(self._on_replay_item)
        rl.addWidget(self.history, 1)
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
        rl.addLayout(seed_row)
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
                                 "Samples/FX/Lasers/laser_bank_NNN. Vorhandene Dateien werden "
                                 "nie überschrieben.")
        self.bank_btn.clicked.connect(self.export_bank_dialog)
        bank_row.addWidget(self.bank_btn)
        rl.addLayout(bank_row)
        row.addWidget(right, 4)
        col.addLayout(row, 0)

        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        col.addWidget(self.status)
        note = QLabel(NOTE)
        note.setObjectName("muted")
        note.setWordWrap(True)
        col.addWidget(note)

    # ---- state ------------------------------------------------------------------------------
    def set_status(self, text: str, error: bool = False) -> None:
        self.status.setText(text)
        self.status.setProperty("level", "error" if error else "info")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    @property
    def busy(self) -> bool:
        return self.job is not None

    def current_dimension(self) -> str:
        for key, b in self.dim_buttons.items():
            if b.isChecked():
                return key
        return DIMENSIONS[0].key

    def current_settings(self) -> BlasterSettings:
        return BlasterSettings(
            dimension=self.current_dimension(),
            positions=tuple(self.sliders[s.name].value() for s in SLIDERS),
        )

    def select_dimension(self, key: str) -> None:
        self._on_dimension(key)

    def _on_dim_clicked(self) -> None:
        self._on_dimension(self.current_dimension())

    def _on_dimension(self, key: str) -> None:
        d = dimension(key)
        self.dim_buttons[key].setChecked(True)
        self.gun.set_accent(d.accent)
        self.dim_hint.setText(f"{d.label}: {d.hint}. Der Klang ist nicht bewertet.")
        for spec in SLIDERS:  # a field that only one family uses is greyed out elsewhere
            if spec.only_family:
                on = key == spec.only_family
                self.sliders[spec.name].setEnabled(on)
                self.slider_labels[spec.name].setEnabled(on)
                self.readouts[spec.name].setEnabled(on)
        self._refresh_readouts()

    def _on_slider(self, _v: int = 0) -> None:
        self._refresh_readouts()

    def _refresh_readouts(self) -> None:
        for spec in SLIDERS:
            self.readouts[spec.name].setText(spec.readout(self.sliders[spec.name].value()))

    def _on_animation(self, on: bool) -> None:
        self.gun.set_animation(on)

    def _on_seed_edited(self) -> None:
        text = self.seed_edit.text().strip()
        try:
            v = int(text)
            if not 0 <= v <= SEED_MAX:
                raise ValueError
        except ValueError:
            self._mark_seed(True)
            self.set_status(f"Seed muss eine ganze Zahl von 0 bis {SEED_MAX} sein.", error=True)
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

    # ---- worker thread --------------------------------------------------------------------------
    def _start(self, kind: str, fn: Callable[[], Any]) -> None:
        self.job = kind
        self.gun.set_busy(True)
        self.bank_btn.setEnabled(False)
        threading.Thread(target=self._work, args=(kind, fn), name=f"blaster-{kind}",
                         daemon=True).start()

    def _work(self, kind: str, fn: Callable[[], Any]) -> None:
        try:
            result: Any = fn()
        except BaseException as exc:  # noqa: BLE001 - the GUI must always hear back
            result = exc
        try:
            self._relay.done.emit(kind, result)
        except RuntimeError:  # window already destroyed
            pass

    def _on_job_done(self, kind: str, result: Any) -> None:
        self.job = None
        if self._closed:
            return
        self.gun.set_busy(False)
        self.bank_btn.setEnabled(True)
        if kind == "shot":
            self._shot_done(result)
        else:
            self._bank_done(result)

    # ---- actions ----------------------------------------------------------------------------
    def pull_trigger(self) -> None:
        """Render (worker thread) and play the next shot with the current controls."""
        if self.busy:
            self.set_status("Der vorige Schuss wird noch gerendert …")
            return
        if self.seed_edit.property("invalid"):
            self.set_status("Der Seed ist ungültig; Schuss nicht ausgelöst.", error=True)
            return
        try:
            settings = self.current_settings()
        except ValueError as exc:
            self.set_status(str(exc), error=True)
            return
        seed = self.session.next_seed
        self.set_status("Schuss wird gerendert …")
        self._start("shot", lambda: (settings, seed, *self.session.render_shot(settings, seed)))

    def _shot_done(self, result: Any) -> None:
        if isinstance(result, BaseException):
            msg = str(result) if isinstance(result, BlasterError) else (
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
        self._show_trace(shot)
        self._sync_seed_field()
        self.gun.flash()
        self.set_status(res.message if res.message else f"Schuss {shot.label()}",
                        error=res.error)

    def _show_trace(self, shot) -> None:
        self.gun.set_trace(peaks(shot.mono, TRACE_BUCKETS))

    def _shot_of(self, item: QListWidgetItem | None):
        if item is None:
            return None
        idx = item.data(SHOT_ROLE)
        return next((s for s in self.session.history if s.index == idx), None)

    def _on_select(self, cur: QListWidgetItem | None, _prev=None) -> None:
        shot = self._shot_of(cur)
        if shot is not None:
            self._show_trace(shot)

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

    def export_bank_dialog(self) -> None:
        if self.busy:
            return
        chosen = self.ask_dir(self, self.out_dir)
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
        try:
            settings = self.current_settings()
        except ValueError as exc:
            self.set_status(str(exc), error=True)
            return
        first, count, writer = self.session.next_seed, self.bank_count.value(), self.bank_writer
        self.set_status(f"Bank mit {count} Schüssen wird geschrieben …")
        self._start("bank", lambda: (first, export_bank(settings, first, count, chosen, writer)))

    def _bank_done(self, result: Any) -> None:
        if isinstance(result, BaseException):
            self.set_status(f"Unerwarteter Fehler: {type(result).__name__}: {result}", error=True)
            return
        first, res = result
        self.session.next_seed = first + len(res.files)  # only written shots count
        self._sync_seed_field()
        self.set_status(res.message, error=res.error)
        if res.folder is not None and res.files:
            self.opener(res.folder)

    def closeEvent(self, e) -> None:  # noqa: N802
        self._closed = True
        self.gun.set_animation(False)
        self.session.close()
        super().closeEvent(e)
