"""CompactGoaWindow: frameless, translucent outside the thorns, always-on-top toggle, drag by the
top strip, custom chrome buttons, size grip, remembered position/size.

This is NOT embedded in Ableton Live: Qt cannot put a widget into Live's own UI. It is a separate
top-level window the user places over or next to Live (ABOUT_TEXT says so in the window)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QVBoxLayout,
    QWidget,
)

from . import geometry as geo
from . import palette as pal
from .frame import ChromeThornFrame
from .settings import MIN_SIZE, SkinSettings, load_settings, save_settings

ABOUT_TEXT = (
    "Kompaktes Fenster, kein Teil von Live: Es liegt als eigenes Fenster (immer im Vordergrund, "
    "abschaltbar) ueber oder neben Ableton. Einbetten in Lives Oberflaeche geht nicht ohne "
    "Max for Live oder ein VST3-Plugin. Ob es in jeder Fokus-Situation oben bleibt, ist nicht "
    "geprueft."
)
ABOUT_SHORT = "Eigenes Fenster, nicht in Live eingebettet."

STYLE = f"""
QLabel {{ background: transparent; color: {pal.TEXT}; }}
QLabel#title {{ color: {pal.CYAN}; font-weight: bold; letter-spacing: 3px; }}
QLabel#muted {{ color: {pal.MUTED}; }}
QLabel#about {{ color: {pal.MUTED}; font-size: 8pt; }}
QLabel#status {{ color: {pal.MAGENTA}; }}
QLineEdit {{ background: {pal.FIELD}; color: {pal.TEXT}; border: 1px solid #2c2f5a;
  border-radius: 3px; padding: 3px 6px; selection-background-color: {pal.MAGENTA}; }}
QLineEdit:focus {{ border: 1px solid {pal.CYAN}; }}
QPushButton#render {{ background: #1b1440; color: {pal.TEXT}; border: 1px solid {pal.MAGENTA};
  border-radius: 3px; padding: 5px 16px; font-weight: bold; }}
QPushButton#render:hover {{ background: #2a1a5e; border-color: {pal.CYAN}; }}
QToolTip {{ background: {pal.PANEL}; color: {pal.TEXT}; border: 1px solid {pal.CYAN}; }}
"""


class ChromeButton(QAbstractButton):
    """Small vector-drawn window button. ``kind``: min, close, pin, anim."""

    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.setCheckable(kind in ("pin", "anim"))
        self.setFixedSize(24, 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        active = self.isChecked()
        hot = self.underMouse()
        accent = QColor(pal.MAGENTA if self.kind == "close" else pal.CYAN)
        fill = QColor(accent)
        fill.setAlpha(70 if hot else (45 if active else 18))
        p.setPen(QPen(accent if (hot or active) else QColor("#3a3f6e"), 1.0))
        p.setBrush(fill)
        p.drawRoundedRect(r, 4, 4)
        c = r.center()
        pen = QPen(QColor(pal.TEXT) if (hot or active) else QColor(pal.MUTED), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if self.kind == "min":
            p.drawLine(QPointF(c.x() - 4, c.y() + 3), QPointF(c.x() + 4, c.y() + 3))
        elif self.kind == "close":
            p.drawLine(QPointF(c.x() - 3.5, c.y() - 3.5), QPointF(c.x() + 3.5, c.y() + 3.5))
            p.drawLine(QPointF(c.x() - 3.5, c.y() + 3.5), QPointF(c.x() + 3.5, c.y() - 3.5))
        elif self.kind == "pin":  # an upward chevron over a bar: "stay on top"
            path = QPainterPath(QPointF(c.x() - 4, c.y() + 1.5))
            path.lineTo(c.x(), c.y() - 2.5)
            path.lineTo(c.x() + 4, c.y() + 1.5)
            p.drawPath(path)
            p.drawLine(QPointF(c.x() - 4, c.y() - 5), QPointF(c.x() + 4, c.y() - 5))
        else:  # anim: a small wave
            path = QPainterPath(QPointF(c.x() - 5, c.y()))
            path.cubicTo(c.x() - 3, c.y() - 6, c.x() - 1, c.y() - 6, c.x(), c.y())
            path.cubicTo(c.x() + 1, c.y() + 6, c.x() + 3, c.y() + 6, c.x() + 5, c.y())
            p.drawPath(path)
        p.end()


class ChromeGrip(QSizeGrip):
    """Size grip drawn as three neon diagonal strokes."""

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        p.setPen(QPen(QColor(pal.CYAN), 1.3))
        for i in (4, 8, 12):
            p.drawLine(QPointF(w - 1, h - i), QPointF(w - i, h - 1))
        p.end()


class TitleStrip(QWidget):
    """Top strip: title, buttons; dragging it moves the window."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._drag_offset: QPoint | None = None
        self.setFixedHeight(28)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 0, 0, 0)
        lay.setSpacing(5)
        self.title = QLabel(title)
        self.title.setObjectName("title")
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay.addWidget(self.title)
        lay.addStretch(1)
        self.anim_button = ChromeButton("anim")
        self.anim_button.setToolTip("Animation (Neon-Puls)")
        self.pin_button = ChromeButton("pin")
        self.pin_button.setToolTip("Immer im Vordergrund")
        self.min_button = ChromeButton("min")
        self.min_button.setToolTip("Minimieren")
        self.close_button = ChromeButton("close")
        self.close_button.setToolTip("Schliessen")
        for b in (self.anim_button, self.pin_button, self.min_button, self.close_button):
            lay.addWidget(b)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None and handle.startSystemMove():
                event.accept()
                return
            self._drag_offset = event.globalPosition().toPoint() - self.window().pos()
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_offset = None


class GoaPlaceholderPanel(QWidget):
    """Placeholder body: title, section/BPM fields, Render button.

    ``goa_arrangement`` has no service-layer function in ``gui_core`` yet, so Render only emits
    :attr:`render_requested` and says so. GUI-2 (#406) replaces this panel through the body slot."""

    render_requested = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(7)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.section = QLineEdit("Intro")
        self.bpm = QLineEdit("145")
        self.section.setToolTip("Aktueller Abschnitt")
        self.bpm.setToolTip("Tempo in BPM")
        self.bpm.setMaximumWidth(80)
        self.section.setMinimumHeight(26)
        self.bpm.setMinimumHeight(26)
        for label, edit in (("Abschnitt", self.section), ("BPM", self.bpm)):
            col = QVBoxLayout()
            col.setSpacing(2)
            cap = QLabel(label)
            cap.setObjectName("muted")
            col.addWidget(cap)
            col.addWidget(edit)
            row.addLayout(col, 1 if edit is self.section else 0)
        lay.addLayout(row)
        self.render_button = QPushButton("Render")
        self.render_button.setObjectName("render")
        self.render_button.clicked.connect(self._on_render)
        lay.addWidget(self.render_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.status = QLabel("Platzhalter: Render folgt mit GUI-2 (#406).")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        lay.addStretch(1)

    def _on_render(self) -> None:
        self.status.setText("Noch nicht angeschlossen: es wurde nichts gerendert.")
        self.render_requested.emit(self.section.text(), self.bpm.text())


class CompactGoaWindow(QWidget):
    def __init__(
        self,
        settings_path: Path | None = None,
        body: QWidget | None = None,
        settings: SkinSettings | None = None,
        use_default_path: bool = False,
    ) -> None:
        super().__init__()
        # The window only reads/writes a settings file when a path is given or the default
        # location is asked for explicitly: tests and screenshots never touch the home folder.
        self._persist = settings_path is not None or use_default_path
        self._settings_path = settings_path
        if settings is None:
            settings = load_settings(settings_path) if self._persist else SkinSettings()
        self._settings = settings.clamped()
        self.setWindowTitle("Goa")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(*MIN_SIZE)
        self.setStyleSheet(STYLE)
        self._apply_flags(self._settings.always_on_top)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.frame = ChromeThornFrame(self)
        outer.addWidget(self.frame)
        self._layout = QVBoxLayout(self.frame)
        self._layout.setSpacing(4)
        self.strip = TitleStrip("GOA", self.frame)
        self._layout.addWidget(self.strip)
        self.body_slot = QVBoxLayout()
        self.body_slot.setContentsMargins(0, 0, 0, 0)
        self._layout.addLayout(self.body_slot, 1)
        footer = QHBoxLayout()
        footer.setContentsMargins(8, 0, 0, 0)
        self.about = QLabel(ABOUT_SHORT)
        self.about.setObjectName("about")
        self.about.setWordWrap(True)
        self.about.setToolTip(ABOUT_TEXT)
        footer.addWidget(self.about, 1)
        self.grip = ChromeGrip(self.frame)
        self.grip.setFixedSize(16, 16)
        footer.addWidget(self.grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        self._layout.addLayout(footer)

        self.body: QWidget | None = None
        self._holder: QWidget | None = None  # the body or its scroll area
        self.set_body(body if body is not None else GoaPlaceholderPanel())

        self.strip.close_button.clicked.connect(self.close)
        self.strip.min_button.clicked.connect(self.showMinimized)
        self.strip.pin_button.setChecked(self._settings.always_on_top)
        self.strip.pin_button.toggled.connect(self.set_always_on_top)
        self.strip.anim_button.setChecked(self._settings.animation)
        self.strip.anim_button.toggled.connect(self.set_animation)
        self.frame.set_animated(self._settings.animation)

        self.resize(self._settings.width, self._settings.height)
        pos = self._settings_position()
        if pos is not None:
            self.move(pos)
        self._update_margins()

    # -- body slot --------------------------------------------------------------------------
    def set_body(self, widget: QWidget, scroll: bool = False) -> None:
        """Put any QWidget into the body slot (the previous one is released). ``scroll=True``
        wraps it in a scroll area, so a large body (the Goa form) does not set the window's
        minimum size (150 % on 1920 x 1080); ``self.body`` stays the widget itself."""
        old = self._holder
        if old is not None:
            self.body_slot.removeWidget(old)
            old.setParent(None)
            old.deleteLater()
        self.body = widget
        holder: QWidget = widget
        if scroll:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            area.setWidget(widget)
            holder = area
        self._holder = holder
        self.body_slot.addWidget(holder)

    def attach_hub(self, hub) -> None:
        """Hand the shared settings and library/Live hand-off to the body (if it takes them)."""
        if self.body is not None and hasattr(self.body, "attach_hub"):
            self.body.attach_hub(hub)

    # -- always on top / animation ----------------------------------------------------------
    def _apply_flags(self, on_top: bool) -> None:
        flags = Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        if on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)

    def always_on_top(self) -> bool:
        return bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)

    def set_always_on_top(self, on: bool) -> None:
        on = bool(on)
        if on == self.always_on_top():
            return
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)  # hides the window
        if was_visible:
            self.show()
        if self.strip.pin_button.isChecked() != on:
            self.strip.pin_button.setChecked(on)

    def set_animation(self, on: bool) -> None:
        self.frame.set_animated(on)
        if self.strip.anim_button.isChecked() != bool(on):
            self.strip.anim_button.setChecked(bool(on))

    # -- settings ---------------------------------------------------------------------------
    def _settings_position(self) -> QPoint | None:
        s = self._settings
        if s.x is None or s.y is None:
            return None
        rect = QRectF(s.x, s.y, s.width, s.height)
        for screen in QGuiApplication.screens():
            if QRectF(screen.availableGeometry()).intersects(rect):
                return QPoint(s.x, s.y)
        return None  # saved monitor is gone: let the system place the window

    def current_settings(self) -> SkinSettings:
        g = self.geometry()
        return SkinSettings(
            x=g.x(),
            y=g.y(),
            width=g.width(),
            height=g.height(),
            always_on_top=self.always_on_top(),
            animation=self.frame.animated(),
        )

    def save_settings(self) -> bool:
        """Write the settings file; False (and nothing written) if persistence is off."""
        if not self._persist:
            return False
        return save_settings(self.current_settings(), self._settings_path)

    # -- events -----------------------------------------------------------------------------
    def _update_margins(self) -> None:
        reach = geo.reach_for(self.width(), self.height())
        m = int(round(reach + geo.rail_for(reach) + 5.0))
        self._layout.setContentsMargins(m, m - 4, m, m + 2)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_margins()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.save_settings()
        if self.body is not None and hasattr(self.body, "shutdown"):
            self.body.shutdown()  # a running Goa render must not call into a closed window
        super().closeEvent(event)
