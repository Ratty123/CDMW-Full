"""Qt item builders for static replacement material plan trees."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from html import escape

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QTreeWidgetItem


@dataclass(frozen=True, slots=True)
class MaterialPlanItemSelection:
    has_item: bool
    source_indices: tuple[int, ...]
    target_index: int
    material_name: str
    texture_role: str
    texture_path: str


def material_plan_item_selection(item: QTreeWidgetItem | None) -> MaterialPlanItemSelection:
    source_indices: set[int] = set()
    target_index = -1
    material_name = ""
    if item is not None:
        raw_sources = item.data(0, Qt.UserRole)
        if isinstance(raw_sources, (tuple, list, set)):
            for raw_index in raw_sources:
                try:
                    source_indices.add(int(raw_index))
                except (TypeError, ValueError):
                    continue
        else:
            try:
                source_indices.add(int(raw_sources))
            except (TypeError, ValueError):
                pass
        try:
            target_index = int(item.data(0, Qt.UserRole + 1))
        except (TypeError, ValueError):
            target_index = -1
        material_name = str(item.data(0, Qt.UserRole + 2) or "").strip()
    return MaterialPlanItemSelection(
        has_item=item is not None,
        source_indices=tuple(sorted(source_indices)),
        target_index=target_index,
        material_name=material_name,
        texture_role=item.text(1) if item is not None and item.columnCount() > 1 else "",
        texture_path=item.text(3) if item is not None and item.columnCount() > 3 else "",
    )


def source_material_route_item(
    route: object,
    *,
    source_indices: Sequence[int],
    target_index: int,
    status_color: str,
) -> QTreeWidgetItem:
    status_label = str(getattr(route, "status", "") or "Unknown")
    source_part_names = tuple(getattr(route, "source_part_names", ()) or ())
    source_parts = ", ".join(str(part) for part in source_part_names) or "-"
    roles = ", ".join(str(role) for role in tuple(getattr(route, "detected_roles", ()) or ())) or "-"
    action = str(getattr(route, "reason", "") or "").strip()
    source_material_name = str(getattr(route, "source_material_name", "") or "")
    item = QTreeWidgetItem(
        [
            str(getattr(route, "target_material_name", "") or ""),
            source_material_name or "-",
            source_parts,
            roles,
            status_label,
            action,
        ]
    )
    item.setData(0, Qt.UserRole, tuple(source_indices))
    item.setData(0, Qt.UserRole + 1, int(target_index))
    item.setData(0, Qt.UserRole + 2, source_material_name)
    item.setData(0, Qt.UserRole + 4, "")
    item.setData(0, Qt.UserRole + 6, "base")
    item.setData(
        0,
        Qt.UserRole + 3,
        "<div style='font-size:8px; line-height:1.15;'>"
        f"<b>Target:</b> {escape(str(getattr(route, 'target_material_name', '') or '-'))}<br>"
        f"<b>Replacement source:</b> {escape(source_material_name or '-')}<br>"
        f"<b>Source parts:</b> {escape(source_parts)}<br>"
        f"<b>Sidecar action:</b> {escape(action or status_label)}"
        "</div>",
    )
    for column in range(6):
        item.setToolTip(column, item.text(column))
    item.setForeground(4, QBrush(QColor(status_color)))
    return item


def replacement_texture_plan_item(
    plan_row: object,
    *,
    source_indices: Sequence[int],
    target_index: int,
    target_name: str,
    material_name: str,
    source_preview_path: str,
    preview_status: str,
    status_color: str,
    status_foreground: str,
) -> QTreeWidgetItem:
    status_label = str(getattr(getattr(plan_row, "status", None), "label", "") or "")
    item = QTreeWidgetItem(
        [
            str(getattr(plan_row, "part_label", "") or getattr(plan_row, "part_material", "")),
            str(getattr(plan_row, "role", "") or ""),
            str(getattr(plan_row, "source", "") or ""),
            str(getattr(plan_row, "final_path", "") or ""),
            status_label,
            str(getattr(plan_row, "controls", "") or ""),
        ]
    )
    item.setData(0, Qt.UserRole, tuple(source_indices))
    item.setData(0, Qt.UserRole + 1, int(target_index))
    item.setData(0, Qt.UserRole + 2, material_name)
    item.setData(0, Qt.UserRole + 4, source_preview_path)
    item.setData(0, Qt.UserRole + 6, getattr(plan_row, "slot_kind", "") or "base")
    item.setData(
        0,
        Qt.UserRole + 3,
        "<div style='font-size:8px; line-height:1.15;'>"
        f"<b>Target material:</b> {escape(target_name or '-')}<br>"
        f"<b>Replacement source:</b> {escape(str(getattr(plan_row, 'source', '') or '-'))}<br>"
        f"<b>Final output DDS:</b> {escape(str(getattr(plan_row, 'final_path', '') or '-'))}<br>"
        f"<b>Preview status:</b> {escape(preview_status)}<br>"
        f"<b>Sidecar action:</b> {escape(str(getattr(plan_row, 'controls', '') or status_label or '-'))}"
        "</div>",
    )
    for column in range(6):
        if column == 0:
            item.setToolTip(column, str(getattr(plan_row, "full_part_material", "") or getattr(plan_row, "part_material", "")))
        else:
            item.setToolTip(column, str(getattr(plan_row, "controls", "") or "") if column in {1, 4, 5} else item.text(column))
    item.setForeground(4, QBrush(QColor(status_color)))
    item.setBackground(4, QBrush(QColor(status_color)))
    item.setForeground(4, QBrush(QColor(status_foreground)))
    return item


def final_material_status_item(
    *,
    material_name: str,
    source_parts: str,
    maps: str,
    status_label: str,
    detail: str,
    source_indices: Sequence[int],
    target_index: int,
    status_color: str,
) -> QTreeWidgetItem:
    item = QTreeWidgetItem([material_name, material_name, source_parts, maps, status_label, detail or "validated"])
    item.setData(0, Qt.UserRole, tuple(source_indices))
    item.setData(0, Qt.UserRole + 1, int(target_index))
    item.setData(0, Qt.UserRole + 2, material_name)
    item.setData(0, Qt.UserRole + 4, "")
    item.setData(0, Qt.UserRole + 6, "base")
    item.setData(
        0,
        Qt.UserRole + 3,
        "<div style='font-size:8px; line-height:1.15;'>"
        f"<b>Target material:</b> {escape(material_name or '-')}<br>"
        f"<b>Replacement source:</b> {escape(source_parts)}<br>"
        f"<b>Final status:</b> {escape(status_label)}<br>"
        f"<b>Sidecar action:</b> {escape(detail or 'Validated from final texture contract')}"
        "</div>",
    )
    item.setForeground(4, QBrush(QColor(status_color)))
    return item


def final_binding_row_item(
    row: object,
    *,
    part_label: str,
    part_name: str,
    material_name: str,
    source_indices: Sequence[int],
    target_index: int,
    preview_status: str,
    status_color: str,
    slot_kind: str,
) -> QTreeWidgetItem:
    status_label = str(getattr(row, "status", "") or "unknown")
    resolved_path = str(getattr(row, "resolved_texture_path", "") or "").strip()
    requested_path = str(getattr(row, "texture_path", "") or "").strip()
    sidecar = str(getattr(row, "sidecar_path", "") or "").strip()
    parameter = str(getattr(row, "parameter_name", "") or "").strip()
    item = QTreeWidgetItem(
        [
            part_label,
            str(getattr(row, "role", "") or ""),
            requested_path or "-",
            resolved_path or requested_path or "-",
            preview_status,
            parameter or sidecar or "-",
        ]
    )
    item.setData(0, Qt.UserRole, tuple(source_indices))
    item.setData(0, Qt.UserRole + 1, int(target_index))
    item.setData(0, Qt.UserRole + 2, material_name)
    item.setData(0, Qt.UserRole + 4, str(getattr(row, "preview_texture_path", "") or ""))
    item.setData(0, Qt.UserRole + 6, slot_kind)
    item.setData(
        0,
        Qt.UserRole + 3,
        "<div style='font-size:8px; line-height:1.15;'>"
        f"<b>Target material:</b> {escape(material_name or '-')}<br>"
        f"<b>Target part:</b> {escape(part_name or '-')}<br>"
        f"<b>Original DDS / requested:</b> {escape(requested_path or '-')}<br>"
        f"<b>Final output DDS:</b> {escape(resolved_path or requested_path or '-')}<br>"
        f"<b>Sidecar parameter:</b> {escape(parameter or '-')}<br>"
        f"<b>Sidecar:</b> {escape(sidecar or '-')}<br>"
        f"<b>Preview status:</b> {escape(preview_status)}<br>"
        f"<b>Action:</b> {escape(str(getattr(row, 'binding_source', '') or status_label))}<br>"
        f"<b>Detail:</b> {escape(str(getattr(row, 'detail', '') or '-'))}"
        "</div>",
    )
    for column in range(6):
        item.setToolTip(column, item.text(column))
    item.setForeground(4, QBrush(QColor(status_color)))
    return item


def donor_material_plan_item(
    target_index: int,
    plan: object,
    *,
    target_display_name: str,
) -> QTreeWidgetItem:
    mode_label = {
        "authoritative_recipe": "Authoritative donor recipe",
        "donor_textures": "Donor textures",
        "material_behavior": "Donor material behavior",
        "material_profile": "Donor material profile",
    }.get(str(getattr(plan, "patch_mode", "") or ""), str(getattr(plan, "patch_mode", "") or "Donor material"))
    donor_label = (
        getattr(plan, "donor_material_name", "")
        or getattr(plan, "donor_submesh_name", "")
        or str(getattr(plan, "donor_sidecar_path", "") or "").replace("\\", "/").rsplit("/", 1)[-1]
    )
    status = (
        "emissive/glow"
        if any(
            "emissive" in str(getattr(binding, "semantic_subtype", "") or "").lower()
            or any(token in str(getattr(binding, "parameter_name", "") or "").lower() for token in ("emissive", "glow", "illum"))
            for binding in tuple(getattr(plan, "texture_bindings", ()) or ())
        )
        else "Ready"
    )
    item = QTreeWidgetItem(
        [
            target_display_name,
            mode_label,
            str(donor_label or "-"),
            str(getattr(plan, "donor_shader_family", "") or "-"),
            status,
        ]
    )
    item.setData(0, Qt.UserRole, int(target_index))
    item.setData(0, Qt.UserRole + 1, plan)
    item.setForeground(4, QBrush(QColor("#facc15" if status == "emissive/glow" else "#86efac")))
    for column in range(5):
        item.setToolTip(column, item.text(column))
    return item


def donor_part_tree_item(row: object) -> QTreeWidgetItem:
    bindings_for_part = tuple(row.get("bindings", ()) or ()) if hasattr(row, "get") else ()
    emissive = bool(row.get("emissive")) if hasattr(row, "get") else False
    item = QTreeWidgetItem(
        [
            str(row.get("part_name") or "Material") if hasattr(row, "get") else "Material",
            str(row.get("shader") or "-") if hasattr(row, "get") else "-",
            str(len(bindings_for_part)),
            "Yes" if emissive else "-",
        ]
    )
    item.setData(0, Qt.UserRole, bindings_for_part)
    item.setData(0, Qt.UserRole + 1, str(row.get("part_name") or "") if hasattr(row, "get") else "")
    if emissive:
        item.setForeground(3, QBrush(QColor("#facc15")))
    return item


def empty_donor_part_tree_item() -> QTreeWidgetItem:
    item = QTreeWidgetItem(["No material wrappers found", "-", "0", "-"])
    item.setToolTip(
        0,
        "No readable donor material wrappers were found for this mesh. Try a different donor mesh or verify that its .pac_xml sidecar is loaded.",
    )
    return item


def donor_texture_binding_item(
    binding: object,
    *,
    slot_label: str,
    parameter_name: str,
    texture_path: str,
    state: str,
) -> QTreeWidgetItem:
    item = QTreeWidgetItem(
        [
            slot_label or "Texture",
            parameter_name or "-",
            str(texture_path or "").replace("\\", "/").rsplit("/", 1)[-1] or texture_path,
            str(getattr(binding, "shader_family", "") or "-"),
            state,
        ]
    )
    item.setData(0, Qt.UserRole, binding)
    if state == "emissive/glow":
        item.setForeground(4, QBrush(QColor("#facc15")))
    for column in range(5):
        item.setToolTip(column, texture_path if column == 2 else item.text(column))
    return item


__all__ = [
    "donor_material_plan_item",
    "donor_part_tree_item",
    "donor_texture_binding_item",
    "empty_donor_part_tree_item",
    "final_binding_row_item",
    "final_material_status_item",
    "MaterialPlanItemSelection",
    "material_plan_item_selection",
    "replacement_texture_plan_item",
    "source_material_route_item",
]
