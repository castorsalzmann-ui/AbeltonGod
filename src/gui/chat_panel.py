"""Copilot chat page on ``gui_core.chat.ChatSession`` (the orchestrator, guard limits unchanged).
The request runs in a worker thread; the window stays usable. A request cannot be cancelled
from here (the guard's time limit ends it); the terminal chat can (Ctrl+C)."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui_core.chat import ChatReply, ChatSession
from gui_core.tasks import start_task

from .tool_style import STYLE

BODY_HOOK = "chat_body"


class _Signals(QObject):
    reply = Signal(object)


class ChatPanel(QWidget):
    def __init__(self, session: ChatSession | None = None) -> None:
        super().__init__()
        self.setObjectName(BODY_HOOK)
        self.setStyleSheet(STYLE)
        self.session = session or ChatSession()
        self.busy = False
        self.handle = None
        self._signals = _Signals()
        self._signals.reply.connect(self._on_reply)

        lay = QVBoxLayout(self)
        head = QLabel("Copilot")
        head.setObjectName("heading")
        lay.addWidget(head)
        self.access = QLabel()
        self.access.setWordWrap(True)
        self.access.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        lay.addWidget(self.access)
        info = QLabel(
            "Gleicher Copilot wie im Terminal (python -m orchestrator.chat) ohne Projektordner: "
            "er kann planen, erzeugt hier aber keine Samples und ändert Live nicht. Die Limits "
            "des Guard (Zeit, Kosten, Aufrufe) gelten unverändert.")
        info.setObjectName("muted")
        info.setWordWrap(True)
        info.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        lay.addWidget(info)
        self.transcript = QPlainTextEdit()
        self.transcript.setReadOnly(True)
        lay.addWidget(self.transcript, 1)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Frage an den Copilot …")
        self.send_button = QPushButton("Senden")
        self.send_button.setObjectName("primary")
        row.addWidget(self.input, 1)
        row.addWidget(self.send_button)
        lay.addLayout(row)
        self.status = QLabel()
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        lay.addWidget(self.status)

        self.send_button.clicked.connect(self.send)
        self.input.returnPressed.connect(self.send)
        self.input.textChanged.connect(self._update_state)
        self.refresh_access()

    def refresh_access(self) -> None:
        st = self.session.status()
        self.ready = st.ready
        self.access.setText(st.message)
        self.access.setProperty("level", "ok" if st.ready else "error")
        self.access.setObjectName("status")
        self.access.style().unpolish(self.access)
        self.access.style().polish(self.access)
        self._update_state()

    def _update_state(self, *_a) -> None:
        can = self.ready and not self.busy
        self.input.setEnabled(can)
        self.send_button.setEnabled(can and bool(self.input.text().strip()))

    def send(self) -> None:
        text = self.input.text().strip()
        if self.busy or not self.ready or not text:
            return
        self.input.clear()
        self.transcript.appendPlainText(f"Du: {text}")
        self.busy = True
        self.status.setText("Claude arbeitet … (läuft bis zum Zeitlimit des Guard)")
        self._update_state()
        self.handle = start_task(
            lambda: self.session.ask(text),
            lambda h: self._signals.reply.emit(
                h.result if h.error is None else ChatReply(f"Fehler: {h.error!r}", False)),
            name="chat-ask")

    def _on_reply(self, reply: ChatReply) -> None:
        self.busy = False
        self.transcript.appendPlainText(f"Copilot: {reply.text}\n")
        self.status.setText("" if reply.success else "Die Anfrage ist nicht erfolgreich zu Ende "
                            "gegangen (siehe Text oben).")
        self._update_state()

    def shutdown(self) -> None:
        if self.handle is not None:
            self.handle.wait(5)
        self.session.close()
