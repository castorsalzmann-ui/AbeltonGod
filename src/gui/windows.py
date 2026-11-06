"""The other windows of the program (Goa, Acid, Blaster), opened from the main window, and what
they share with it.

One instance per key: a second click raises the open window instead of making another. A window
that was closed is replaced by a fresh one on the next click (the windows clean up in their own
``closeEvent``, so a closed one is not reused). Closing a window never ends the program; closing
the main window closes them all. Window classes are imported on first use, so the main window
starts without loading all skins.

Shared parts (#439):

* :class:`AppHub` carries the one :class:`gui_core.settings.SettingsStore` and the hand-off
  signals: files written (the library refreshes), "In Bibliothek zeigen" and "An Live senden"
  (the main window opens its library or Live-import page with that file; the Live page's own
  checks and confirmations decide whether anything is imported -- nothing goes to Live from here).
* :class:`ResultActions` is the two-button row every tool window shows for its latest result.
* :class:`WindowManager` gives each opened window the hub (``attach_hub``, if it has one) and
  remembers its position and size in the settings.
* :class:`SettingsDialog` edits output folder, project folder, sample rate and bit depth.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QRect, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui_core.library import read_entry
from gui_core.settings import (
    BIT_DEPTHS,
    DEFAULT_BIT_DEPTH,
    DEFAULT_SAMPLE_RATE,
    SAMPLE_RATES,
    AppSettings,
    SettingsStore,
    WindowState,
)

WINDOW_KEYS = (("goa", "Goa-Fenster"), ("acid", "Acid-Linie"), ("blaster", "Laser-Blaster"))

SHOW_TEXT = "In Bibliothek zeigen"
LIVE_TEXT = "An Live senden"
NO_HUB_NOTE = ("Bibliothek und Live-Import gibt es nur, wenn das Fenster aus dem Hauptfenster "
               "geöffnet wurde.")
LIVE_TIP = ("Öffnet die Live-Import-Seite des Hauptfensters mit dieser Datei. Dort laufen alle "
            "Prüfungen; ohne deine Bestätigung geht nichts an Live.")


def open_in_file_manager(path: Path) -> bool:
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


# --- shared state ------------------------------------------------------------------------------
class AppHub(QObject):
    """One per main window. Signals carry ``AppSettings``, ``list[Path]`` or one ``Path``."""

    settings_changed = Signal(object)
    files_written = Signal(object)
    show_requested = Signal(object)
    live_requested = Signal(object)

    def __init__(self, store: SettingsStore | None = None) -> None:
        super().__init__()
        self.store = store or SettingsStore()
        self.store.subscribe(self._changed)

    @property
    def settings(self) -> AppSettings:
        return self.store.settings

    def _changed(self, settings: AppSettings) -> None:
        self.settings_changed.emit(settings)

    def detach(self) -> None:
        self.store.unsubscribe(self._changed)


def live_problem(path: Path | None) -> str:
    """Why ``path`` cannot go to the Live import page ('' = it can). Only the first, cheap check
    (a WAV with a readable sidecar); the full check is the Live page's."""
    if path is None:
        return "Noch kein Ergebnis."
    if path.suffix.lower() != ".wav":
        return "Nur WAV-Dateien gehen an den Live-Import."
    if not path.is_file():
        return "Die Datei gibt es nicht mehr."
    entry = read_entry(path)
    if not entry.readable:
        return (f"Für den Live-Import fehlt eine lesbare Sidecar-Datei ({entry.problem}); "
                "der Import braucht sie.")
    return ""


class ResultActions(QWidget):
    """"In Bibliothek zeigen" and "An Live senden" for the latest result of a tool window."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.hub: AppHub | None = None
        self.path: Path | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.show_button = QPushButton(SHOW_TEXT)
        self.show_button.setObjectName("show_in_library")
        self.live_button = QPushButton(LIVE_TEXT)
        self.live_button.setObjectName("send_to_live")
        self.live_button.setToolTip(LIVE_TIP)
        row.addWidget(self.show_button)
        row.addWidget(self.live_button)
        row.addStretch(1)
        lay.addLayout(row)
        self.note = QLabel()
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        self.note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        lay.addWidget(self.note)
        self.show_button.clicked.connect(self.show_in_library)
        self.live_button.clicked.connect(self.send_to_live)
        self._update()

    def set_hub(self, hub: AppHub | None) -> None:
        self.hub = hub
        self._update()

    def set_paths(self, paths: list[Path] | tuple[Path, ...]) -> None:
        """The result to act on: the first WAV of ``paths`` (or the first file)."""
        paths = [Path(p) for p in paths]
        wavs = [p for p in paths if p.suffix.lower() == ".wav"]
        self.path = wavs[0] if wavs else (paths[0] if paths else None)
        self._update()

    def _update(self) -> None:
        if self.hub is None:
            self.show_button.setEnabled(False)
            self.live_button.setEnabled(False)
            self.note.setText(NO_HUB_NOTE)
            return
        p = self.path
        is_wav = p is not None and p.suffix.lower() == ".wav" and p.is_file()
        self.show_button.setEnabled(is_wav)
        problem = live_problem(p)
        self.live_button.setEnabled(not problem)
        if p is None:
            self.note.setText("")
        elif not is_wav:
            self.note.setText(f"Die Bibliothek listet nur WAV-Dateien. {p.name} liegt in "
                              f"{p.parent}.")
        else:
            self.note.setText(problem)

    def refresh(self) -> None:
        self._update()

    def show_in_library(self) -> None:
        if self.hub is not None and self.path is not None:
            self.hub.show_requested.emit(self.path)

    def send_to_live(self) -> None:
        if self.hub is not None and self.path is not None and not live_problem(self.path):
            self.hub.live_requested.emit(self.path)


# --- geometry ------------------------------------------------------------------------------------
def window_state(widget: QWidget) -> WindowState:
    g = widget.geometry()
    top = anim = None
    if hasattr(widget, "always_on_top") and hasattr(widget, "frame"):  # the Goa skin
        top = bool(widget.always_on_top())
        anim = bool(widget.frame.animated())
    return WindowState(g.x(), g.y(), g.width(), g.height(), top, anim)


def on_some_screen(state: WindowState) -> bool:
    rect = QRect(state.x, state.y, state.width, state.height)
    return any(s.availableGeometry().intersects(rect) for s in QGuiApplication.screens())


def restore_state(widget: QWidget, state: WindowState | None) -> bool:
    """Put ``widget`` where ``state`` says; the size only if the saved monitor is gone. False
    (nothing changed) without a state."""
    if state is None:
        return False
    if state.always_on_top is not None and hasattr(widget, "set_always_on_top"):
        widget.set_always_on_top(state.always_on_top)
    if state.animation is not None and hasattr(widget, "set_animation"):
        widget.set_animation(state.animation)
    if on_some_screen(state):
        widget.setGeometry(state.x, state.y, state.width, state.height)
    else:
        widget.resize(state.width, state.height)
    return True


# --- default windows -----------------------------------------------------------------------------
def _goa(out_dir: Path) -> QWidget:
    from .goa_panel import GoaPanel
    from .skin.settings import SkinSettings
    from .skin.window import CompactGoaWindow

    body = GoaPanel(AppSettings(output_dir=str(out_dir)).goa_dir(), opener=open_in_file_manager)
    win = CompactGoaWindow(settings=SkinSettings(), body=body)  # settings: the shared store
    u = win.fontMetrics().height()
    want_w, want_h = int(u * 84), int(u * 46)
    screen = QGuiApplication.primaryScreen()
    if screen is not None:
        area = screen.availableGeometry()
        want_w, want_h = min(want_w, area.width()), min(want_h, int(area.height() * 0.95))
    win.resize(want_w, want_h)
    return win


def _acid(out_dir: Path) -> QWidget:
    from .acid.window import AcidWindow

    return AcidWindow(out_dir=AppSettings(output_dir=str(out_dir)).acid_dir())


def _blaster(out_dir: Path) -> QWidget:
    from .blaster.window import BlasterWindow

    return BlasterWindow(out_dir=out_dir)


DEFAULT_FACTORIES: dict[str, Callable[[Path], QWidget]] = {
    "goa": _goa, "acid": _acid, "blaster": _blaster,
}


def _alive(widget: QWidget | None) -> bool:
    if widget is None:
        return False
    try:
        import shiboken6

        return shiboken6.isValid(widget)
    except ImportError:  # pragma: no cover - shiboken ships with PySide6
        return True


class WindowManager(QObject):
    def __init__(self, out_dir: Callable[[], Path],
                 factories: dict[str, Callable[[Path], QWidget]] | None = None,
                 hub: AppHub | None = None) -> None:
        super().__init__()
        self._out_dir = out_dir
        self._factories = dict(DEFAULT_FACTORIES if factories is None else factories)
        self._open: dict[str, QWidget] = {}
        self.hub = hub
        self.last_error = ""

    def is_open(self, key: str) -> bool:
        w = self._open.get(key)
        return _alive(w) and w.isVisible()  # type: ignore[union-attr]

    def window(self, key: str) -> QWidget | None:
        return self._open.get(key) if self.is_open(key) else None

    def open(self, key: str) -> QWidget | None:
        """Show the window ``key`` (new, or the open one raised). None when it cannot be made;
        the reason is in ``last_error`` (German)."""
        if key not in self._factories:
            raise KeyError(key)
        existing = self.window(key)
        if existing is not None:
            existing.raise_()
            existing.activateWindow()
            return existing
        old = self._open.pop(key, None)
        if _alive(old):
            old.deleteLater()  # type: ignore[union-attr]
        try:
            win = self._factories[key](self._out_dir())
            if self.hub is not None and hasattr(win, "attach_hub"):
                win.attach_hub(self.hub)
        except Exception as exc:  # noqa: BLE001 - a missing part must not close the program
            self.last_error = (
                f"Das Fenster konnte nicht geöffnet werden: {type(exc).__name__}: {exc}")
            return None
        self.last_error = ""
        self._open[key] = win
        win.setProperty("window_key", key)
        if self.hub is not None:
            restore_state(win, self.hub.settings.windows.get(key))
            win.installEventFilter(self)
        win.show()
        return win

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt name
        if event.type() == QEvent.Type.Close and self.hub is not None:
            key = obj.property("window_key")
            if isinstance(key, str) and self._open.get(key) is obj:
                self.hub.store.set_window(key, window_state(obj))
        return False

    def close_all(self) -> None:
        for key in list(self._open):
            w = self._open.pop(key)
            if _alive(w):
                if self.hub is not None and w.isVisible():
                    self.hub.store.set_window(key, window_state(w))
                w.removeEventFilter(self)
                w.close()
                w.deleteLater()


# --- settings dialog -----------------------------------------------------------------------------
class SettingsDialog(QDialog):
    """Output folder, project folder, sample rate, bit depth. ``values()`` gives the fields for
    ``SettingsStore.update``; the main window applies them on accept."""

    def __init__(self, settings: AppSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Einstellungen")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.output_edit = QLineEdit(str(settings.output_root()))
        form.addRow("Ausgabeordner", self._with_chooser(self.output_edit, "Ausgabeordner"))
        self.project_edit = QLineEdit(settings.project_dir)
        self.project_edit.setPlaceholderText("leer = keiner")
        form.addRow("Projektordner", self._with_chooser(self.project_edit, "Projektordner"))
        self.rate_box = QComboBox()
        self.rate_box.addItem(f"Vertragsstandard ({DEFAULT_SAMPLE_RATE} Hz)", None)
        for r in SAMPLE_RATES:
            self.rate_box.addItem(f"{r} Hz", r)
        self.rate_box.setCurrentIndex(max(0, self.rate_box.findData(settings.sample_rate)))
        form.addRow("Samplerate", self.rate_box)
        self.bits_box = QComboBox()
        self.bits_box.addItem(f"Vertragsstandard ({DEFAULT_BIT_DEPTH} Bit)", None)
        for b in BIT_DEPTHS:
            self.bits_box.addItem(f"{b} Bit", b)
        self.bits_box.setCurrentIndex(max(0, self.bits_box.findData(settings.bit_depth)))
        form.addRow("Bittiefe", self.bits_box)
        lay.addLayout(form)
        note = QLabel(
            "Alle Fenster schreiben unter den Ausgabeordner: Acid nach acid/, Goa nach goa/, "
            "Blaster nach Samples/FX/Lasers/. Die Bibliothek liest nur den Ausgabeordner. "
            "Der Projektordner ist nur der Startordner für den Bank-Export des Blasters. "
            "Samplerate und Bittiefe sind die Startwerte der Kategorie-Formulare (ein Preset-"
            "Wechsel setzt sie zurück) und gelten für Blaster-Speichern, Blaster-Bänke und "
            "Acid-WAVs.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _with_chooser(self, edit: QLineEdit, title: str) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit, 1)
        button = QPushButton("Wählen …")
        button.setProperty("target_title", title)
        button.clicked.connect(self._choose)
        row.addWidget(button)
        self._edits = getattr(self, "_edits", {})
        self._edits[title] = edit
        return box

    def _choose(self) -> None:
        title = self.sender().property("target_title")
        edit = self._edits[title]
        picked = QFileDialog.getExistingDirectory(self, f"{title} wählen", edit.text())
        if picked:
            edit.setText(picked)

    def values(self) -> dict:
        return {
            "output_dir": self.output_edit.text().strip(),
            "project_dir": self.project_edit.text().strip(),
            "sample_rate": self.rate_box.currentData(),
            "bit_depth": self.bits_box.currentData(),
        }
