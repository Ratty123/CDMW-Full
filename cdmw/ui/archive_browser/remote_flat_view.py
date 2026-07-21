"""Virtualized flat-table presentation for the remote archive catalogue."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QFrame, QTableView


class RemoteArchiveFlatTableView(QTableView):
    """Present very large flat models without QTreeView's all-row layout pass."""

    uiActivity = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setCornerButtonEnabled(False)
        self.horizontalHeader().hide()
        self.verticalHeader().hide()
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        self.uiActivity.emit()
        super().wheelEvent(event)

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        self.uiActivity.emit()
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        self.uiActivity.emit()
        if event.button() == Qt.RightButton:
            event.accept()
            return
        super().mousePressEvent(event)

    def scrollContentsBy(self, dx: int, dy: int) -> None:  # type: ignore[override]
        if dx or dy:
            self.uiActivity.emit()
        super().scrollContentsBy(dx, dy)


__all__ = ["RemoteArchiveFlatTableView"]
