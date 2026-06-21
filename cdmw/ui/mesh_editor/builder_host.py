"""Mesh editor builder-host boundary."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QWidget


class MeshReplacementPartsOutlinerTree(QTreeWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._source_drop_handler: Callable[[object, object], bool] | None = None
        self._drag_source_item: QTreeWidgetItem | None = None

    def set_source_drop_handler(self, callback: Callable[[object, object], bool]) -> None:
        self._source_drop_handler = callback

    def startDrag(self, supported_actions: object) -> None:
        self._drag_source_item = self.currentItem()
        super().startDrag(supported_actions)

    def dropEvent(self, event: object) -> None:
        handler = self._source_drop_handler
        source_item = self._drag_source_item or self.currentItem()
        try:
            position = event.position().toPoint() if hasattr(event, "position") else event.pos()
        except Exception:
            position = QPoint()
        target_item = self.itemAt(position)
        self._drag_source_item = None
        if handler is not None and handler(source_item, target_item):
            try:
                event.acceptProposedAction()
            except Exception:
                pass
            return
        try:
            event.ignore()
        except Exception:
            pass


__all__ = ["MeshReplacementPartsOutlinerTree"]
