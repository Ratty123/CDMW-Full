"""Qt item builders for added-part texture rows."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QTreeWidgetItem


def added_part_texture_item(
    *,
    source_index: int,
    source_display_name: str,
    target_summary: str,
    material_name: str,
    base_display: str,
    normal_display: str,
    material_display: str,
    height_display: str,
    status_label: str,
    status_color: str,
) -> QTreeWidgetItem:
    item = QTreeWidgetItem(
        [
            source_display_name,
            target_summary,
            material_name,
            base_display,
            normal_display,
            material_display,
            height_display,
            status_label,
        ]
    )
    item.setData(0, Qt.UserRole, int(source_index))
    for column in range(8):
        item.setToolTip(column, item.text(column))
    item.setForeground(7, QBrush(QColor(status_color)))
    item.setBackground(7, QBrush(QColor(status_color)))
    item.setForeground(7, QBrush(QColor("#0d1117" if status_label == "Ready" else "#ffffff")))
    return item


__all__ = [
    "added_part_texture_item",
]
