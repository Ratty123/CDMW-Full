"""Tree item factories for Research tab view models."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import List, Sequence, TypeVar

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from cdmw.domain.research.contracts import (
    MaterialTextureReferenceRow,
    MipAnalysisRow,
    NormalValidationRow,
    ResearchNote,
    SidecarDiscoveryRow,
    TextureBudgetClassSummary,
    TextureBudgetGroupSummary,
    TextureBudgetProfileSummary,
    TextureBudgetRow,
    TextureClassificationRow,
    TextureSetGroup,
    TextureUsageHeatRow,
    UnknownResolverGroup,
    UnknownResolverMember,
)
from cdmw.ui.research.archive_picker_state import archive_picker_file_label
from cdmw.ui.research.state import mip_analysis_tooltip_lines, normal_validation_tooltip_lines
from cdmw.models import ArchiveEntry

__all__ = [
    "archive_picker_folder_key",
    "archive_picker_item_kind",
    "archive_picker_item_value",
    "build_archive_picker_file_item",
    "build_archive_picker_folder_item",
    "build_budget_class_item",
    "build_budget_file_item",
    "build_budget_group_item",
    "build_budget_profile_item",
    "build_classification_item",
    "build_heatmap_scope_item",
    "build_heatmap_scope_parent_item",
    "build_heatmap_usage_item",
    "build_mip_item",
    "build_normal_item",
    "build_note_item",
    "build_reference_row_item",
    "build_sidecar_row_item",
    "build_texture_group_item",
    "build_ui_constraint_row_item",
    "build_ui_constraint_item",
    "build_unknown_group_item",
    "build_unknown_member_item",
    "current_archive_picker_entry_from_item",
    "current_unknown_group_from_item",
    "find_archive_picker_file_item",
    "item_payload",
    "item_user_role",
    "resolve_texture_group_item",
    "selected_unknown_groups_from_items",
    "selected_texture_group_from_items",
    "texture_group_member_paths",
]

T = TypeVar("T")


def item_user_role(item: QTreeWidgetItem | None) -> object:
    if item is None:
        return None
    return item.data(0, Qt.UserRole)


def item_payload(item: QTreeWidgetItem | None, payload_type: type[T]) -> T | None:
    value = item_user_role(item)
    return value if isinstance(value, payload_type) else None


def archive_picker_item_kind(item: QTreeWidgetItem | None) -> str:
    if item is None:
        return ""
    raw = item.data(0, Qt.UserRole)
    return raw if isinstance(raw, str) else ""


def archive_picker_item_value(item: QTreeWidgetItem | None) -> object:
    if item is None:
        return None
    return item.data(0, Qt.UserRole + 1)


def current_archive_picker_entry_from_item(
    item: QTreeWidgetItem | None,
    entries: Sequence[ArchiveEntry],
) -> ArchiveEntry | None:
    if archive_picker_item_kind(item) != "file":
        return None
    value = archive_picker_item_value(item)
    if not isinstance(value, int) or not (0 <= value < len(entries)):
        return None
    return entries[value]


def archive_picker_folder_key(item: QTreeWidgetItem | None) -> tuple[str, ...]:
    raw = archive_picker_item_value(item)
    return raw if isinstance(raw, tuple) else ()


def find_archive_picker_file_item(
    container: QTreeWidget | QTreeWidgetItem,
    entry_index: int,
) -> QTreeWidgetItem | None:
    child_count = container.topLevelItemCount() if isinstance(container, QTreeWidget) else container.childCount()
    for child_index in range(child_count):
        child = container.topLevelItem(child_index) if isinstance(container, QTreeWidget) else container.child(child_index)
        if child is None:
            continue
        if archive_picker_item_kind(child) == "file" and archive_picker_item_value(child) == entry_index:
            return child
    return None


def resolve_texture_group_item(item: QTreeWidgetItem | None) -> QTreeWidgetItem | None:
    current = item
    while current is not None:
        group_key = current.data(0, Qt.UserRole)
        if isinstance(group_key, str) and group_key.strip():
            return current
        current = current.parent()
    return None


def selected_texture_group_from_items(
    candidate_items: Sequence[QTreeWidgetItem],
    groups: object,
) -> TextureSetGroup | None:
    group_item = None
    for item in candidate_items:
        group_item = resolve_texture_group_item(item)
        if group_item is not None:
            break
    if group_item is None:
        return None
    group_key = group_item.data(0, Qt.UserRole)
    if not isinstance(group_key, str) or not group_key.strip():
        return None
    if not isinstance(groups, list):
        return None
    for group in groups:
        if isinstance(group, TextureSetGroup) and group.group_key == group_key:
            return group
    return None


def texture_group_member_paths(group: TextureSetGroup | None) -> list[str]:
    if group is None:
        return []
    return [member.path for member in group.members]


def current_unknown_group_from_item(item: QTreeWidgetItem | None) -> UnknownResolverGroup | None:
    return item_payload(item, UnknownResolverGroup)


def selected_unknown_groups_from_items(items: Sequence[QTreeWidgetItem]) -> list[UnknownResolverGroup]:
    groups: list[UnknownResolverGroup] = []
    seen_keys: set[str] = set()
    for item in items:
        value = item_payload(item, UnknownResolverGroup)
        if value is None:
            continue
        if value.group_key in seen_keys:
            continue
        seen_keys.add(value.group_key)
        groups.append(value)
    return groups


def build_archive_picker_folder_item(
    folder_key: tuple[str, ...],
    *,
    has_children: bool,
) -> QTreeWidgetItem:
    leaf = folder_key[-1] if folder_key else "/"
    item = QTreeWidgetItem([leaf, "Folder", ""])
    item.setData(0, Qt.UserRole, "folder")
    item.setData(0, Qt.UserRole + 1, folder_key)
    item.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
    if has_children:
        item.addChild(QTreeWidgetItem(["Loading...", "", ""]))
    return item


def build_archive_picker_file_item(
    entry: ArchiveEntry,
    entry_index: int,
    *,
    show_full_path: bool,
) -> QTreeWidgetItem:
    label = archive_picker_file_label(entry.path, show_full_path=show_full_path)
    item = QTreeWidgetItem([label, entry.extension or "file", entry.package_label])
    item.setData(0, Qt.UserRole, "file")
    item.setData(0, Qt.UserRole + 1, entry_index)
    item.setToolTip(0, entry.path)
    item.setToolTip(2, entry.package_label)
    return item


def build_note_item(key: str, note: ResearchNote) -> QTreeWidgetItem:
    tags_text = ", ".join(note.tags)
    item = QTreeWidgetItem([key, tags_text, note.updated_at, note.source_kind])
    item.setData(0, Qt.UserRole, key)
    item.setToolTip(0, key)
    item.setToolTip(1, tags_text)
    return item


def build_texture_group_item(group: TextureSetGroup) -> QTreeWidgetItem:
    parent = QTreeWidgetItem(
        [
            group.display_name,
            f"{group.member_count:,}",
            ", ".join(group.member_kinds),
            ", ".join(group.package_labels[:3]) + ("..." if len(group.package_labels) > 3 else ""),
        ]
    )
    parent.setData(0, Qt.UserRole, group.group_key)
    parent.setToolTip(0, group.group_key)
    for member in group.members[:40]:
        child = QTreeWidgetItem([PurePosixPath(member.path).name, "1", member.member_kind, member.package_label])
        child.setData(0, Qt.UserRole, group.group_key)
        child.setToolTip(0, member.path)
        parent.addChild(child)
    return parent


def build_classification_item(row: TextureClassificationRow) -> QTreeWidgetItem:
    item = QTreeWidgetItem(
        [PurePosixPath(row.path).name, row.texture_type, f"{row.confidence}%", row.package_label, row.reason]
    )
    item.setToolTip(0, row.path)
    return item


def build_heatmap_scope_item(scope_rows: tuple[str, List[TextureUsageHeatRow]]) -> QTreeWidgetItem:
    scope, rows = scope_rows
    parent = build_heatmap_scope_parent_item(scope)
    for row in rows:
        parent.addChild(build_heatmap_usage_item(row))
    return parent


def build_heatmap_scope_parent_item(scope: str) -> QTreeWidgetItem:
    parent = QTreeWidgetItem([scope, "", "", "", "", "", "", ""])
    parent.setFirstColumnSpanned(True)
    parent.setExpanded(True)
    return parent


def build_heatmap_usage_item(row: TextureUsageHeatRow) -> QTreeWidgetItem:
    item = QTreeWidgetItem(
        [
            row.label,
            f"{row.heat_score:,}",
            f"{row.texture_count:,}",
            f"{row.set_count:,}",
            f"{row.normal_count:,}",
            f"{row.ui_count:,}",
            f"{row.material_count:,}",
            f"{row.impostor_count:,}",
        ]
    )
    if row.sample_paths:
        item.setToolTip(0, "\n".join(row.sample_paths))
    return item


def build_mip_item(row: MipAnalysisRow) -> QTreeWidgetItem:
    item = QTreeWidgetItem(
        [
            row.relative_path,
            f"{row.original_size} | {row.original_format}",
            f"{row.rebuilt_size} | {row.rebuilt_format}",
            f"{row.original_mips} -> {row.rebuilt_mips}",
            "; ".join(row.warnings[:2]) if row.warnings else "No warning",
        ]
    )
    item.setData(0, Qt.UserRole, row)
    item.setToolTip(4, "\n".join(mip_analysis_tooltip_lines(row)))
    return item


def build_normal_item(row: NormalValidationRow) -> QTreeWidgetItem:
    item = QTreeWidgetItem([row.path, row.root_label, row.dds_format, row.size_text, "; ".join(row.issues[:2])])
    item.setData(0, Qt.UserRole, row)
    item.setToolTip(4, "\n".join(normal_validation_tooltip_lines(row)))
    return item


def build_ui_constraint_item(row: MaterialTextureReferenceRow) -> QTreeWidgetItem:
    dds_size = f"{row.texture_width}x{row.texture_height}" if row.texture_width > 0 and row.texture_height > 0 else "-"
    item = QTreeWidgetItem(
        [
            row.related_path,
            row.source_path,
            dds_size,
            row.get_rect_raw or "-",
            row.constraint_kind or "No explicit UI rect found",
            row.related_package_label or row.source_package_label,
        ]
    )
    item.setData(0, Qt.UserRole, row)
    item.setToolTip(0, row.related_path)
    item.setToolTip(1, row.source_path)
    item.setToolTip(2, row.warning_text or dds_size)
    item.setToolTip(3, row.warning_text or row.constraint_kind)
    return item


def build_unknown_group_item(
    group: UnknownResolverGroup,
    *,
    display_name: str,
    classification_text: str,
    package_text: str,
) -> QTreeWidgetItem:
    item = QTreeWidgetItem(
        [
            display_name,
            classification_text,
            group.local_approval_state,
            package_text,
        ]
    )
    item.setData(0, Qt.UserRole, group)
    item.setToolTip(0, group.group_key)
    item.setToolTip(1, classification_text)
    item.setToolTip(2, group.local_approval_state)
    item.setToolTip(3, ", ".join(group.package_labels))
    return item


def build_unknown_member_item(member: UnknownResolverMember, *, local_text: str) -> QTreeWidgetItem:
    item = QTreeWidgetItem(
        [
            PurePosixPath(member.path).name,
            member.current_kind,
            local_text,
            member.role_hint or "-",
            member.package_label,
            member.reason,
        ]
    )
    item.setData(0, Qt.UserRole, member)
    item.setToolTip(0, member.path)
    return item


def build_reference_row_item(row: MaterialTextureReferenceRow) -> QTreeWidgetItem:
    item = QTreeWidgetItem(
        [
            row.source_path,
            row.related_path,
            row.get_rect_raw or "-",
            row.constraint_kind or row.relation_kind,
            f"{row.match_count:,}",
            row.source_package_label or row.related_package_label,
        ]
    )
    item.setData(0, Qt.UserRole, row)
    item.setToolTip(0, row.snippet)
    item.setToolTip(1, row.related_package_label)
    item.setToolTip(2, row.get_rect_raw or "")
    item.setToolTip(3, row.warning_text or row.constraint_kind or row.relation_kind)
    return item


def build_ui_constraint_row_item(row: MaterialTextureReferenceRow) -> QTreeWidgetItem:
    dds_size = f"{row.texture_width}x{row.texture_height}" if row.texture_width > 0 and row.texture_height > 0 else "-"
    item = QTreeWidgetItem(
        [
            row.related_path,
            row.source_path,
            dds_size,
            row.get_rect_raw or "-",
            row.constraint_kind or "Explicit UI rect found",
            row.related_package_label or row.source_package_label,
        ]
    )
    item.setData(0, Qt.UserRole, row)
    item.setToolTip(0, row.warning_text or row.related_path)
    item.setToolTip(1, row.source_path)
    item.setToolTip(4, row.warning_text or row.constraint_kind)
    return item


def build_sidecar_row_item(row: SidecarDiscoveryRow) -> QTreeWidgetItem:
    item = QTreeWidgetItem(
        [
            row.related_path,
            row.relation_kind,
            f"{row.confidence}%",
            row.package_label,
            row.reason,
        ]
    )
    item.setData(0, Qt.UserRole, row)
    item.setToolTip(0, row.related_path)
    return item


def build_budget_file_item(row: TextureBudgetRow) -> QTreeWidgetItem:
    size_text = f"{row.original_width}x{row.original_height} -> {row.rebuilt_width}x{row.rebuilt_height}"
    item = QTreeWidgetItem(
        [
            row.relative_path,
            f"{row.byte_delta:+,}",
            f"{row.byte_ratio:.2f}x",
            size_text,
            row.texture_type,
            f"{row.risk_score} ({row.risk_band})",
        ]
    )
    item.setData(0, Qt.UserRole, row)
    item.setToolTip(0, row.relative_path)
    tooltip_lines = [
        f"Original bytes: {row.original_bytes:,}",
        f"Rebuilt bytes: {row.rebuilt_bytes:,}",
        f"Original format: {row.original_format}",
        f"Rebuilt format: {row.rebuilt_format}",
        f"Original mips: {row.original_mips}",
        f"Rebuilt mips: {row.rebuilt_mips}",
        "",
        *row.risk_signals,
    ]
    item.setToolTip(5, "\n".join(line for line in tooltip_lines if line))
    return item


def build_budget_class_item(row: TextureBudgetClassSummary) -> QTreeWidgetItem:
    item = QTreeWidgetItem(
        [
            row.texture_type,
            f"{row.affected_count:,}",
            f"{row.total_byte_delta:+,}",
            f"{row.average_risk:.1f}",
            row.risk_band,
        ]
    )
    item.setData(0, Qt.UserRole, row)
    item.setToolTip(0, "\n".join(row.sample_paths))
    return item


def build_budget_group_item(row: TextureBudgetGroupSummary) -> QTreeWidgetItem:
    item = QTreeWidgetItem(
        [
            row.group_key,
            f"{row.texture_count:,}",
            f"{row.total_byte_delta:+,}",
            f"{row.average_byte_ratio:.2f}x",
            str(row.risk_score),
            row.risk_band,
        ]
    )
    item.setData(0, Qt.UserRole, row)
    item.setToolTip(0, "\n".join(row.signals))
    return item


def build_budget_profile_item(row: TextureBudgetProfileSummary) -> QTreeWidgetItem:
    item = QTreeWidgetItem(
        [
            row.profile_label,
            f"{row.total_byte_delta:+,}",
            f"{row.total_byte_ratio:.2f}x",
            f"{row.changed_texture_count:,}",
            f"{row.upscaled_texture_count:,}",
        ]
    )
    item.setData(0, Qt.UserRole, row)
    item.setToolTip(0, "\n".join(row.reasons))
    return item
