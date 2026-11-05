"""Drag-out: a list whose rows are offered as file URLs (QMimeData urls; on Windows Qt turns
these into CF_HDROP for the drop target). Tested at the mime-data level only; a real drop into
Live or Explorer is not verified."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, QUrl
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem

PATH_ROLE = Qt.ItemDataRole.UserRole


def file_mime(paths: Iterable[Path]) -> QMimeData:
    """Mime data offering existing files as ``file:`` URLs (nothing for missing files)."""
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths if Path(p).is_file()])
    return mime


class DragList(QListWidget):
    """List whose items carry a WAV path in ``PATH_ROLE``; dragging out offers that file."""

    def __init__(self) -> None:
        super().__init__()
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    def mimeTypes(self) -> list[str]:  # noqa: N802 - Qt name
        return ["text/uri-list"]

    def mimeData(self, items: Sequence[QListWidgetItem]) -> QMimeData:  # noqa: N802
        return file_mime(
            Path(i.data(PATH_ROLE)) for i in items if i.data(PATH_ROLE)
        )

    def supportedDragActions(self) -> Qt.DropAction:  # noqa: N802
        return Qt.DropAction.CopyAction
