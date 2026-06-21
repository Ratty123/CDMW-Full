"""Qt item builders for static replacement source/original/outliner rows."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem


def assignment_source_item(
    parent: QTreeWidget,
    *,
    source_index: int,
    display_name: str,
    geometry_text: str,
    tooltip: str,
) -> QTreeWidgetItem:
    item = QTreeWidgetItem(parent)
    item.setText(0, display_name)
    item.setText(1, geometry_text)
    item.setData(0, Qt.UserRole, int(source_index))
    item.setToolTip(0, tooltip)
    return item


def source_tree_item(
    *,
    source_index: int,
    label: str,
    role_hint: str,
    geometry_text: str,
    source_name: str,
    source_material: str,
    copied_texture_count: int,
    copied_texture_disabled: bool,
    copied_texture_tooltip: str,
    enabled: bool,
) -> QTreeWidgetItem:
    status_text = (
        "Preview-only | Route DDS"
        if copied_texture_count and copied_texture_disabled
        else f"Preview-only | Copied Orig {copied_texture_count:,}"
        if copied_texture_count
        else "Active"
    )
    status_color = "#d29922" if copied_texture_count and copied_texture_disabled else "#3fb950"
    item = QTreeWidgetItem(["", str(source_index), label, role_hint, "", status_text, geometry_text])
    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
    item.setData(0, Qt.UserRole, (int(source_index),))
    item.setData(1, Qt.UserRole, (int(source_index),))
    item.setToolTip(0, "Include this imported part in mapped replacement output.")
    item.setToolTip(2, f"{label}\nName: {source_name or '-'}\nMaterial: {source_material or '-'}")
    item.setToolTip(4, "Original draw/material slot(s) currently receiving this replacement part.")
    item.setToolTip(5, copied_texture_tooltip if copied_texture_count else "Replacement source status.")
    item.setForeground(5, QBrush(QColor(status_color if copied_texture_count else "#86efac")))
    item.setCheckState(0, Qt.Checked if enabled else Qt.Unchecked)
    return item


def original_part_tree_item(
    *,
    original_index: int,
    label: str,
    role_hint: str,
    geometry_text: str,
    source_name: str,
    source_material: str,
) -> QTreeWidgetItem:
    item = QTreeWidgetItem([str(original_index), label, role_hint, geometry_text, ""])
    item.setData(0, Qt.UserRole, (int(original_index),))
    item.setToolTip(1, f"{label}\nName: {source_name or '-'}\nMaterial: {source_material or '-'}")
    item.setToolTip(4, "Replacement source index created from this original reference part.")
    return item


def mapping_target_item(
    *,
    target_index: int,
    target_label_text: str,
    target_role_hint: str,
    selected_display: str,
    outliner_state: str,
    outliner_state_color: str,
    target_dds_status: str,
    physics_status: str,
    initial_source_indices: tuple[int, ...],
    confidence_label_text: str,
    target_details: str,
    target_texture_details: str,
    selected_ok: bool,
    removed: bool,
    mapping_text_empty: bool,
) -> QTreeWidgetItem:
    item = QTreeWidgetItem(
        [
            target_label_text,
            target_role_hint,
            "",
            selected_display,
            outliner_state,
            target_dds_status,
            physics_status,
        ]
    )
    item.setData(0, Qt.UserRole, tuple(initial_source_indices))
    item.setData(0, Qt.UserRole + 1, int(target_index))
    item.setData(0, Qt.UserRole + 2, confidence_label_text.lower())
    item.setData(0, Qt.UserRole + 3, bool(mapping_text_empty))
    for tooltip_column in range(7):
        item.setToolTip(tooltip_column, target_details)
    item.setToolTip(5, target_texture_details)
    item.setForeground(4, QBrush(QColor(outliner_state_color)))
    item.setToolTip(4, confidence_label_text)
    if removed:
        item.setForeground(5, QBrush(QColor("#fb923c")))
        item.setToolTip(
            5,
            "Removed target: original DDS/material sidecar parameters can be pruned during patched sidecar output.",
        )
    if physics_status == "Review":
        item.setForeground(6, QBrush(QColor("#f2cc60")))
        item.setToolTip(
            6,
            "This target name suggests physics, collision, cloth, or shape data. Review related companion files before build.",
        )
    if not selected_ok:
        item.setForeground(3, QBrush(QColor("#fca5a5")))
    return item


def parts_outliner_target_item(
    *,
    target_index: int,
    label: str,
    role_hint: str,
    dds_text: str,
    state_text: str,
    state_color: str,
    physics_text: str,
    geometry_text: str,
    source_indices: tuple[int, ...],
    texture_tooltip: str,
    physics_tooltip: str,
) -> QTreeWidgetItem:
    item = QTreeWidgetItem(
        [
            label,
            "Original draw slot",
            role_hint,
            dds_text,
            state_text,
            physics_text,
            geometry_text,
        ]
    )
    item.setData(0, Qt.UserRole, "target")
    item.setData(0, Qt.UserRole + 1, int(target_index))
    item.setData(0, Qt.UserRole + 2, tuple(source_indices))
    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDropEnabled)
    item.setForeground(0, QBrush(QColor("#79c0ff")))
    item.setForeground(1, QBrush(QColor("#8b949e")))
    item.setForeground(4, QBrush(QColor(state_color)))
    item.setToolTip(0, "Target = original game draw/material slot.")
    item.setToolTip(1, "Original target slot. Source child rows below this target feed replacement geometry into it.")
    item.setToolTip(2, "Target role inferred from original name/material.")
    item.setToolTip(3, texture_tooltip)
    if physics_text == "Review":
        item.setForeground(5, QBrush(QColor("#f2cc60")))
        item.setToolTip(5, physics_tooltip)
    return item


def parts_outliner_source_item(
    *,
    source_index: int,
    target_index: int,
    label: str,
    target_text: str,
    role_label: str,
    dds_text: str,
    state_text: str,
    state_color: str,
    physics_text: str,
    geometry_text: str,
    physics_tooltip: str,
    copied_texture_tooltip: str = "",
    unassigned: bool = False,
) -> QTreeWidgetItem:
    item = QTreeWidgetItem([label, target_text, role_label, dds_text, state_text, physics_text, geometry_text])
    item.setData(0, Qt.UserRole, "source")
    item.setData(0, Qt.UserRole + 1, int(target_index))
    item.setData(0, Qt.UserRole + 2, (int(source_index),))
    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled)
    item.setForeground(0, QBrush(QColor("#f2cc60" if unassigned else "#7ee787")))
    item.setForeground(1, QBrush(QColor("#d29922" if unassigned else "#c9d1d9")))
    item.setForeground(4, QBrush(QColor(state_color)))
    item.setToolTip(
        0,
        "Unassigned replacement source. Select it to inspect/transform; assign a Target to export it."
        if unassigned
        else "Source = replacement part feeding the target above.",
    )
    item.setToolTip(
        1,
        "Click to choose an original target, or keep Preview-only / Unassigned."
        if unassigned
        else "Click to choose which original target this source feeds, or set it Preview-only / Unassigned.",
    )
    item.setToolTip(2, "Click to override this replacement source role.")
    item.setToolTip(3, copied_texture_tooltip or "DDS = visible texture contract for this replacement source.")
    item.setToolTip(5, physics_tooltip)
    if physics_text == "Review":
        item.setForeground(5, QBrush(QColor("#f2cc60")))
    elif physics_text == "Preserved":
        item.setForeground(5, QBrush(QColor("#7ee787")))
    return item


def parts_outliner_unassigned_group_item(count: int) -> QTreeWidgetItem:
    item = QTreeWidgetItem(["Unassigned Sources", "Preview-only", "-", "-", "Preview-only", "-", f"{int(count):,} part(s)"])
    item.setData(0, Qt.UserRole, "unassigned_group")
    item.setData(0, Qt.UserRole + 1, -1)
    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDropEnabled)
    item.setForeground(0, QBrush(QColor("#f2cc60")))
    item.setForeground(4, QBrush(QColor("#d29922")))
    item.setToolTip(0, "Preview-only/unassigned replacement sources. These do not export until assigned to a target.")
    return item


__all__ = [
    "assignment_source_item",
    "mapping_target_item",
    "original_part_tree_item",
    "parts_outliner_source_item",
    "parts_outliner_target_item",
    "parts_outliner_unassigned_group_item",
    "source_tree_item",
]
