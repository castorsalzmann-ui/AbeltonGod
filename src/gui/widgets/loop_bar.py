"""Loop-preview row (#553): "Im Takt ▶", pattern, tempo, "mit Kick" (and optionally Stopp).

Only the controls; the window renders the loop with ``gui_core.loop_preview`` and plays it."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QPushButton, QSpinBox, QWidget

from gui.widgets.choice import FlowLayout
from gui_core.loop_preview import BPM_MAX, BPM_MIN, DEFAULT_BPM, PATTERN_CHOICES, default_pattern


class LoopBar(QWidget):
    play_clicked = Signal()
    stop_clicked = Signal()
    bpm_changed = Signal(int)
    changed = Signal()  # pattern, tempo or kick changed

    def __init__(self, with_stop: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        u = self.fontMetrics().height()
        # wraps in a narrow window (half screen at 150 %), so it never sets the window's width
        lay = FlowLayout(self, spacing=int(u * 0.3))
        self.play_button = QPushButton("Im Takt ▶")
        self.play_button.setToolTip("Spielt das Sample im 4/4-Takt in Schleife, bis Stopp.")
        self.pattern_box = QComboBox()
        self.pattern_box.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.pattern_box.setMinimumContentsLength(14)
        self.pattern_box.addItems(list(PATTERN_CHOICES))
        self.pattern_box.setToolTip("Wo im Takt das Sample erklingt")
        self.bpm_spin = QSpinBox()
        self.bpm_spin.setRange(BPM_MIN, BPM_MAX)
        self.bpm_spin.setValue(DEFAULT_BPM)
        self.bpm_spin.setSuffix(" BPM")
        self.kick_box = QCheckBox("mit Kick")
        self.kick_box.setToolTip("Legt die Standard-Kick auf jede Viertel")
        for w in (self.play_button, self.pattern_box, self.bpm_spin, self.kick_box):
            lay.addWidget(w)
        self.stop_button: QPushButton | None = None
        if with_stop:
            self.stop_button = QPushButton("■ Stopp")
            lay.addWidget(self.stop_button)
            self.stop_button.clicked.connect(self.stop_clicked)
        self.play_button.clicked.connect(self.play_clicked)
        self.bpm_spin.valueChanged.connect(self.bpm_changed)
        # a running loop follows every change (the window restarts it)
        self.bpm_spin.valueChanged.connect(lambda *_: self.changed.emit())
        self.pattern_box.currentIndexChanged.connect(lambda *_: self.changed.emit())
        self.kick_box.toggled.connect(lambda *_: self.changed.emit())

    def set_category(self, category: str | None) -> None:
        """Select the category's default pattern (the user can change it)."""
        self.pattern_box.setCurrentText(default_pattern(category))

    @property
    def pattern(self) -> str:
        return self.pattern_box.currentText()

    @property
    def bpm(self) -> int:
        return self.bpm_spin.value()

    def set_bpm(self, bpm: int) -> None:
        self.bpm_spin.blockSignals(True)
        self.bpm_spin.setValue(bpm)
        self.bpm_spin.blockSignals(False)

    @property
    def with_kick(self) -> bool:
        return self.kick_box.isChecked()
