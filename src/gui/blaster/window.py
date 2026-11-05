"""Blaster window: gun, dimension selector, sliders, shot history with WAV drag-out, bank export.

Standalone window (D-030): not a plugin, not inside Live. What the shots sound like is not
judged anywhere in this window.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
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
    SLIDER_LABELS,
    SLIDER_NAMES,
    BankWriter,
    BlasterSession,
    BlasterSettings,
    LaserEngine,
    dimension,
    export_bank,
    load_engine,
    readout,
)
from gui_core.paths import default_output_dir
from gui_core.preview import PlaybackBackend
from gui_core.waveform import peaks

from . import skin
from .gun import TRACE_BUCKETS, BlasterWidget

SEED_MAX = 2_147_483_647
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
        self.resize(int(u * 62), int(u * 46))

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
            grid.addWidget(b, i // 3, i % 3)
        ll.addLayout(grid)
        self.dim_hint = QLabel("")
        self.dim_hint.setObjectName("muted")
        ll.addWidget(self.dim_hint)
        sg = QGridLayout()
        sg.setHorizontalSpacing(int(u * 0.7))
        sg.setVerticalSpacing(int(u * 0.15))
        defaults = BlasterSettings()
        self.sliders: dict[str, QSlider] = {}
        self.readouts: dict[str, QLabel] = {}
        for r, name in enumerate(SLIDER_NAMES):
            sl = QSlider(Qt.Orientation.Horizontal)
            sl.setRange(0, 100)
            sl.setValue(getattr(defaults, name))
            sl.valueChanged.connect(self._on_slider)
            ro = QLabel("")
            ro.setMinimumWidth(int(u * 4.2))
            ro.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.sliders[name], self.readouts[name] = sl, ro
            sg.addWidget(QLabel(SLIDER_LABELS[name]), r, 0)
            sg.addWidget(sl, r, 1)
            sg.addWidget(ro, r, 2)
        sg.setColumnStretch(1, 1)
        ll.addLayout(sg)
        row.addWidget(left, 5)

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
        self.bank_btn.setToolTip("Schreibt WAV + Sidecar in einen neuen Ordner. "
                                 "Vorhandene Dateien werden nie überschrieben.")
        self.bank_btn.clicked.connect(self.export_bank_dialog)
        bank_row.addWidget(self.bank_btn)
        rl.addLayout(bank_row)
        row.addWidget(right, 4)
        col.addLayout(row, 3)

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

    def current_dimension(self) -> str:
        for key, b in self.dim_buttons.items():
            if b.isChecked():
                return key
        return DIMENSIONS[0].key

    def current_settings(self) -> BlasterSettings:
        return BlasterSettings(
            dimension=self.current_dimension(),
            **{n: s.value() for n, s in self.sliders.items()},
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
        self._refresh_readouts()

    def _on_slider(self, _v: int = 0) -> None:
        self._refresh_readouts()

    def _refresh_readouts(self) -> None:
        for n, s in self.sliders.items():
            self.readouts[n].setText(readout(n, s.value()))

    def _on_animation(self, on: bool) -> None:
        self.gun.set_animation(on)

    def _on_seed_edited(self) -> None:
        text = self.seed_edit.text().strip()
        try:
            v = int(text)
            if not 0 <= v <= SEED_MAX:
                raise ValueError
        except ValueError:
            self.seed_edit.setProperty("invalid", True)
            self.seed_edit.style().unpolish(self.seed_edit)
            self.seed_edit.style().polish(self.seed_edit)
            self.set_status(f"Seed muss eine ganze Zahl von 0 bis {SEED_MAX} sein.", error=True)
            return
        self.seed_edit.setProperty("invalid", False)
        self.seed_edit.style().unpolish(self.seed_edit)
        self.seed_edit.style().polish(self.seed_edit)
        self.session.next_seed = v

    def _sync_seed_field(self) -> None:
        self.seed_edit.setText(str(self.session.next_seed))
        self.seed_edit.setProperty("invalid", False)

    # ---- actions ----------------------------------------------------------------------------
    def pull_trigger(self) -> None:
        """Render and play the next shot with the current controls."""
        if self.seed_edit.property("invalid"):
            self.set_status("Der Seed ist ungültig; Schuss nicht ausgelöst.", error=True)
            return
        try:
            self.session.settings = self.current_settings()
        except ValueError as exc:
            self.set_status(str(exc), error=True)
            return
        res = self.session.fire()
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
        if res.message:
            self.set_status(res.message, error=res.error)
        else:
            self.set_status(f"Schuss {shot.label()}")

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
        parent = self.ask_dir(self, self.out_dir)
        if parent is None:
            self.set_status("Bank-Export abgebrochen.")
            return
        self.export_bank_to(parent)

    def export_bank_to(self, parent: Path) -> None:
        try:
            self.session.settings = self.current_settings()
        except ValueError as exc:
            self.set_status(str(exc), error=True)
            return
        res = export_bank(self.session, self.bank_count.value(), parent, self.bank_writer)
        self._sync_seed_field()
        self.set_status(res.message, error=res.error)
        if res.folder is not None and res.files:
            self.opener(res.folder)

    def closeEvent(self, e) -> None:  # noqa: N802
        self.gun.set_animation(False)
        self.session.close()
        super().closeEvent(e)
