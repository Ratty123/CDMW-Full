"""Qt item builders for static replacement texture tables."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import PurePosixPath

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from cdmw.core.final_package_preview import (
    TEXTURE_PLAN_STATUS_READY,
    TEXTURE_PLAN_STATUS_REVIEW,
    TEXTURE_PLAN_STATUS_SUPPORT_ONLY,
    build_dds_override_table_row,
)
from cdmw.ui.archive_browser.static_replacement_texture_rows import (
    texture_row_override_key,
    texture_row_table_display,
)


def texture_assignment_slot_item(
    *,
    part_display: str,
    parameter_display: str,
    target_path: str,
    source_indices: tuple[int, ...],
    target_name: str,
    binding_part_name: str,
    binding_shader_family: str,
    binding_sidecar_kind: str,
    binding_linked_mesh: str,
    slot_label: str,
    slot_kind: str,
    semantic_type: str,
    semantic_subtype: str,
    reason: str,
) -> QTreeWidgetItem:
    item = QTreeWidgetItem(["", part_display, parameter_display, PurePosixPath(target_path).name, "", ""])
    item.setData(0, Qt.UserRole, tuple(source_indices))
    item.setData(0, Qt.UserRole + 1, target_name)
    item.setToolTip(
        1,
        "\n".join(
            part
            for part in (
                f"Target slot: {target_name}",
                f"Part: {binding_part_name}" if binding_part_name else "",
                f"Material family: {binding_shader_family}" if binding_shader_family else "",
                f"Sidecar: {binding_sidecar_kind}" if binding_sidecar_kind else "",
                f"Linked mesh: {binding_linked_mesh}" if binding_linked_mesh else "",
            )
            if part
        ),
    )
    item.setToolTip(
        2,
        "\n".join(
            part
            for part in (
                parameter_display,
                f"Classified as: {slot_label or slot_kind}",
                f"Preview route: {slot_kind}",
                f"Semantic: {semantic_type}/{semantic_subtype}",
                reason,
            )
            if part
        ),
    )
    item.setToolTip(3, target_path)
    item.setToolTip(4, reason)
    item.setToolTip(5, "Choose the PNG/DDS source that should replace this texture slot.")
    return item


def apply_texture_row_to_item(
    item: QTreeWidgetItem,
    row_state: dict[str, object],
    *,
    sync_assignment: Callable[[dict[str, object]], dict[str, object]],
    source_summary: Callable[[Mapping[str, object]], str],
    source_summary_tooltip: Callable[[Mapping[str, object]], str],
    effective_source: Callable[[Mapping[str, object]], str],
    assigned: Callable[[Mapping[str, object]], bool],
    status_color_for_label: Callable[[str], str],
) -> None:
    sync_assignment(row_state)
    table_row = build_dds_override_table_row(row_state)
    display = texture_row_table_display(
        row_state,
        table_row,
        source_summary=source_summary(row_state),
        source_summary_tooltip=source_summary_tooltip(row_state),
        effective_source=effective_source(row_state),
        assigned=assigned(row_state),
        status_color_for_label=status_color_for_label,
        dark_foreground_statuses=(
            TEXTURE_PLAN_STATUS_READY,
            TEXTURE_PLAN_STATUS_REVIEW,
            TEXTURE_PLAN_STATUS_SUPPORT_ONLY,
        ),
    )

    for column, value in enumerate(display.values):
        item.setText(column, value)
    item.setData(0, Qt.UserRole, tuple(row_state.get("source_indices", ()) or ()))
    item.setData(0, Qt.UserRole + 1, row_state)
    for column, tooltip in enumerate(display.tooltips):
        item.setToolTip(column, tooltip)
    item.setForeground(1, QBrush(QColor("#79c0ff")))
    item.setForeground(2, QBrush(QColor(display.role_color)))
    item.setForeground(3, QBrush(QColor(display.role_color)))
    item.setForeground(4, QBrush(QColor(display.source_color)))
    item.setForeground(5, QBrush(QColor(display.status_color)))
    item.setBackground(5, QBrush(QColor(display.status_color)))
    item.setForeground(5, QBrush(QColor(display.status_foreground)))


def texture_override_item() -> QTreeWidgetItem:
    return QTreeWidgetItem([""] * 7)


def texture_item_for_row(tree: QTreeWidget, row_state: Mapping[str, object]) -> QTreeWidgetItem | None:
    row_key = texture_row_override_key(row_state)
    for item_index in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(item_index)
        item_row = item.data(0, Qt.UserRole + 1)
        if item_row is row_state:
            return item
        if isinstance(item_row, Mapping) and texture_row_override_key(item_row) == row_key:
            return item
    return None


__all__ = [
    "apply_texture_row_to_item",
    "texture_assignment_slot_item",
    "texture_item_for_row",
    "texture_override_item",
]
