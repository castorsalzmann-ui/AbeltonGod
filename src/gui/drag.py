"""Drag-out: a list whose rows are offered as file URLs (QMimeData urls; on Windows Qt turns
these into CF_HDROP for the drop target). Tested at the mime-data level only; a real drop into
Live or Explorer is not verified."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
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
    """List whose items carry a WAV path in ``PATH_ROLE``; dragging out offers that file.

    ``offer`` (optional) maps an item's path to the file actually offered, at drag start; None
    leaves that row out. The Blaster uses it so a drag never offers a shot from its temporary
    folder (trimmed and deleted on close; Live would play silence, #444)."""

    def __init__(self, offer: Callable[[Path], Path | None] | None = None) -> None:
        super().__init__()
        self.offer = offer
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    def mimeTypes(self) -> list[str]:  # noqa: N802 - Qt name
        return ["text/uri-list"]

    def offered_paths(self, items: Sequence[QListWidgetItem]) -> list[Path]:
        paths = [Path(i.data(PATH_ROLE)) for i in items if i.data(PATH_ROLE)]
        if self.offer is None:
            return paths
        mapped = (self.offer(p) for p in paths)
        return [p for p in mapped if p is not None]

    def mimeData(self, items: Sequence[QListWidgetItem]) -> QMimeData:  # noqa: N802
        return file_mime(self.offered_paths(items))

    def supportedDragActions(self) -> Qt.DropAction:  # noqa: N802
        return Qt.DropAction.CopyAction
