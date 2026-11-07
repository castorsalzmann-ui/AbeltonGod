"""Copilot page on ``gui_core.chat.ChatSession``: the terminal chat's tools and guard path in
the GUI (#491).

The request runs in a worker thread; the window stays usable. A confirm tool (a write to the
Live set) asks through :class:`gui_core.chat.GuiApprover`: the worker posts the question with a
signal and waits; this page shows a modal dialog on the GUI thread with exactly what would be
written (track, scene, file, SHA-256). "Nein" is the default button; Esc, closing the dialog,
the timeout (the orchestrator's confirmation window) and the cancel button all count as no.

"Abbrechen" stops the request at its next guard step (before the next model or tool call); a
Claude answer already on its way is waited for. New files are listed in the transcript as links
(click: show in the library) and announced to the main window (``AppHub.files_written``), whose
library re-reads the output folder."""

from __future__ import annotations

import html
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from gui_core.chat import ChatReply, ChatSession, ConfirmRequest, GuiApprover
from gui_core.tasks import start_task

from . import theme
from .tool_style import STYLE

BODY_HOOK = "chat_body"
# The transcript is a QTextBrowser (clickable file links); same look as the text views.
TRANSCRIPT_STYLE = f"""
QTextBrowser {{ background: {theme.FIELD}; border: 1px solid {theme.BORDER}; padding: 0.3em;
  selection-background-color: {theme.ACCENT}; selection-color: {theme.ACCENT_TEXT}; }}
"""
YES_TEXT = "Ja, ins Live-Set schreiben"
NO_TEXT = "Nein"


class _Signals(QObject):
    reply = Signal(object)
    confirm = Signal(object)  # ConfirmRequest, emitted from the worker thread


class ChatPanel(QWidget):
    def __init__(self, session: ChatSession | None = None,
                 opener: Callable[[Path], bool] | None = None) -> None:
        super().__init__()
        self.setObjectName(BODY_HOOK)
        self.setStyleSheet(STYLE + TRANSCRIPT_STYLE)
        self.session = session or ChatSession()
        self.opener = opener
        self.hub = None
        self.busy = False
        self.handle = None
        self.last_reply: ChatReply | None = None
        self.confirm_dialog: QMessageBox | None = None
        self.pending_confirm: ConfirmRequest | None = None
        self._signals = _Signals()
        self._signals.reply.connect(self._on_reply)
        # Queued: the slot runs on the GUI thread even though the worker emits it.
        self._signals.confirm.connect(self._show_confirm, Qt.ConnectionType.QueuedConnection)
        self.approver = GuiApprover(self._signals.confirm.emit)
        self.session.approver = self.approver

        lay = QVBoxLayout(self)
        head = QLabel("Copilot")
        head.setObjectName("heading")
        lay.addWidget(head)
        self.access = QLabel()
        self.access.setWordWrap(True)
        self.access.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        lay.addWidget(self.access)
        self.tools_info = QLabel()
        self.tools_info.setObjectName("muted")
        self.tools_info.setWordWrap(True)
        self.tools_info.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        lay.addWidget(self.tools_info)
        info = QLabel(
            "Gleicher Copilot wie im Terminal (python -m orchestrator.chat): gleiche Werkzeuge, "
            "gleicher Guard. Vor jeder Änderung am Live-Set fragt ein Fenster nach (Standard: "
            "Nein). Abbrechen wirkt beim nächsten Schritt, eine laufende Claude-Antwort wird "
            "abgewartet.")
        info.setObjectName("muted")
        info.setWordWrap(True)
        info.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        lay.addWidget(info)
        self.transcript = QTextBrowser()
        self.transcript.setObjectName("chat_transcript")
        self.transcript.setOpenLinks(False)
        self.transcript.setOpenExternalLinks(False)
        self.transcript.anchorClicked.connect(self._link_clicked)
        self.transcript.document().setDefaultStyleSheet(f"a {{ color: {theme.ACCENT}; }}")
        lay.addWidget(self.transcript, 1)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Frage an den Copilot …")
        self.send_button = QPushButton("Senden")
        self.send_button.setObjectName("primary")
        self.cancel_button = QPushButton("Abbrechen")
        self.cancel_button.setToolTip("Hält die Anfrage beim nächsten Schritt an; eine offene "
                                      "Live-Frage wird mit Nein beantwortet.")
        row.addWidget(self.input, 1)
        row.addWidget(self.send_button)
        row.addWidget(self.cancel_button)
        lay.addLayout(row)
        self.status = QLabel()
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        lay.addWidget(self.status)
        self.budget = QLabel()
        self.budget.setObjectName("muted")
        self.budget.setWordWrap(True)
        self.budget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        lay.addWidget(self.budget)

        self.send_button.clicked.connect(self.send)
        self.cancel_button.clicked.connect(self.cancel)
        self.input.returnPressed.connect(self.send)
        self.input.textChanged.connect(self._update_state)
        self.refresh_access()

    # --- settings ------------------------------------------------------------------------

    def set_session(self, session: ChatSession) -> None:
        """Use another chat session (the GUI tour's fake model). Not while a request runs."""
        if self.busy:
            raise RuntimeError("a request is running")
        old, self.session = self.session, session
        old.close()
        session.approver = self.approver
        if self.hub is not None:
            session.set_output_dir(self.hub.settings.output_root())
        self.refresh_access()

    def attach_hub(self, hub) -> None:
        """Follow the shared output folder; announce new files to the main window."""
        self.hub = hub
        hub.settings_changed.connect(self._settings_changed)
        self._settings_changed(hub.settings)

    def _settings_changed(self, settings) -> None:
        self.session.set_output_dir(settings.output_root())
        if not self.busy:
            self.refresh_tools()

    def refresh_access(self) -> None:
        st = self.session.status()
        self.ready = st.ready
        self.access.setText(st.message)
        self.access.setProperty("level", "ok" if st.ready else "error")
        self.access.setObjectName("status")
        self.access.style().unpolish(self.access)
        self.access.style().polish(self.access)
        self.refresh_tools()
        if not self.budget.text():
            self.budget.setText(self.session.budget())
        self._update_state()

    def refresh_tools(self) -> None:
        self.tools_info.setText(self.session.tools_state().note)

    def _update_state(self, *_a) -> None:
        can = self.ready and not self.busy
        self.input.setEnabled(can)
        self.send_button.setEnabled(can and bool(self.input.text().strip()))
        self.cancel_button.setEnabled(self.busy)

    # --- transcript ----------------------------------------------------------------------

    def _say(self, who: str, text: str) -> None:
        body = html.escape(text).replace("\n", "<br>")
        self.transcript.append(f"<p><b>{html.escape(who)}:</b> {body}</p>")

    def _files(self, files) -> None:
        links = "<br>".join(
            f'<a href="{QUrl.fromLocalFile(str(p)).toString()}">{html.escape(str(p))}</a>'
            for p in files)
        self.transcript.append(f"<p>Neue Dateien (Klick zeigt sie in der Bibliothek):<br>"
                               f"{links}</p>")

    def _link_clicked(self, url: QUrl) -> None:
        path = Path(url.toLocalFile())
        if self.hub is not None:
            self.hub.show_requested.emit(path)
        elif self.opener is not None:
            self.opener(path)

    # --- requests ------------------------------------------------------------------------

    def send(self) -> None:
        text = self.input.text().strip()
        if self.busy or not self.ready or not text:
            return
        self.input.clear()
        self._say("Du", text)
        self.busy = True
        self.status.setText("Claude arbeitet … (Abbrechen hält beim nächsten Schritt an)")
        self._update_state()
        self.handle = start_task(
            lambda: self.session.ask(text),
            lambda h: self._signals.reply.emit(
                h.result if h.error is None else ChatReply(f"Fehler: {h.error!r}", False)),
            name="chat-ask")

    def cancel(self) -> None:
        if not self.busy:
            return
        self.session.cancel()
        self.status.setText("Abbruch angefordert: die Anfrage hält beim nächsten Schritt an.")

    def _on_reply(self, reply: ChatReply) -> None:
        self.busy = False
        self.last_reply = reply
        self._close_confirm()
        self._say("Copilot", reply.text)
        if reply.files:
            self._files(reply.files)
            if self.hub is not None:
                self.hub.files_written.emit(list(reply.files))
        if reply.success:
            self.status.setText("")
        elif reply.cancelled:
            self.status.setText("Abgebrochen.")
        else:
            self.status.setText("Die Anfrage ist nicht erfolgreich zu Ende gegangen (siehe "
                                "Text oben).")
        if reply.budget:
            self.budget.setText(reply.budget)
        self.refresh_tools()
        self._update_state()

    # --- confirmation (GUI thread) -------------------------------------------------------

    def _show_confirm(self, request: ConfirmRequest) -> None:
        if request.closed:  # timed out or cancelled before the GUI got to it
            return
        self._close_confirm()
        dlg = QMessageBox(QMessageBox.Icon.Question, request.text.title, request.text.text,
                          QMessageBox.StandardButton.NoButton, self)
        yes = dlg.addButton(YES_TEXT, QMessageBox.ButtonRole.YesRole)
        no = dlg.addButton(NO_TEXT, QMessageBox.ButtonRole.NoRole)
        dlg.setStyleSheet(f"QMessageBox {{ background: {theme.BG}; }}")  # readable text
        dlg.setDefaultButton(no)
        dlg.setEscapeButton(no)
        dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
        left = [int(request.timeout_s)]
        dlg.setInformativeText(f"Noch {left[0]} s.")
        timer = QTimer(dlg)
        timer.setInterval(1000)

        def tick() -> None:
            left[0] -= 1
            if request.closed or left[0] <= 0:
                request.expire()  # the worker's own timeout says the same
                dlg.done(0)
                return
            dlg.setInformativeText(f"Noch {left[0]} s.")

        def finished(_result: int) -> None:
            timer.stop()
            request.answer(dlg.clickedButton() is yes)  # anything else (Esc, close) is no
            if self.confirm_dialog is dlg:
                self.confirm_dialog = None
                self.pending_confirm = None
            dlg.deleteLater()

        timer.timeout.connect(tick)
        dlg.finished.connect(finished)
        self.confirm_dialog, self.pending_confirm = dlg, request
        self.confirm_buttons = {"yes": yes, "no": no}
        timer.start()
        dlg.show()  # not open(): that would make it only window-modal

    def _close_confirm(self) -> None:
        dlg = self.confirm_dialog
        if dlg is not None:
            dlg.done(0)  # finished() answers the request with no

    def shutdown(self) -> None:
        self.session.cancel()
        self._close_confirm()
        if self.handle is not None:
            self.handle.wait(5)
        self.session.close()
