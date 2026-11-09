"""Output-volume control (D-035, #545): label, slider 0-100 and a percent readout.

Every instance shows and sets the one shared :data:`gui_core.volume.OUTPUT`, so moving it in
one window moves it in all. Saving to the settings file is the main window's job."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QWidget

from gui_core.volume import MAX_VOLUME, MIN_VOLUME, OUTPUT, OutputVolume


class VolumeControl(QWidget):
    def __init__(self, volume: OutputVolume = OUTPUT, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.volume = volume
        u = self.fontMetrics().height()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(int(u * 0.3))
        self.label = QLabel("Lautstärke")
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(MIN_VOLUME, MAX_VOLUME)
        self.slider.setSingleStep(1)
        self.slider.setPageStep(10)
        self.slider.setFixedWidth(int(u * 6))
        self.slider.setAccessibleName("Lautstärke der Vorschau")
        self.slider.setToolTip("Lautstärke aller Vorschauen (nur das Abspielen; geschriebene "
                               "Dateien bleiben unverändert).")
        self.readout = QLabel()
        # room for "100 %" in this font (Windows at 150 % needs more than 2.4 line heights)
        self.readout.setMinimumWidth(self.readout.fontMetrics().horizontalAdvance("100 %") + 6)
        for w in (self.label, self.slider, self.readout):
            lay.addWidget(w)
        self._show(volume.value)
        self.slider.valueChanged.connect(self._moved)
        volume.subscribe(self._show)
        self.destroyed.connect(lambda *_: volume.unsubscribe(self._show))

    def _moved(self, v: int) -> None:
        self.readout.setText(f"{v} %")
        self.volume.set(v)

    def _show(self, v: int) -> None:
        try:
            if self.slider.value() != v:
                self.slider.blockSignals(True)
                self.slider.setValue(v)
                self.slider.blockSignals(False)
            self.readout.setText(f"{v} %")
        except RuntimeError:  # the C++ widget is gone (window closed)
            self.volume.unsubscribe(self._show)
