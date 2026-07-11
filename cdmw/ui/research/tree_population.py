"""Tree population helpers for Research tab row collections."""

from __future__ import annotations

from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from cdmw.domain.research.contracts import (
    MaterialTextureReferenceRow,
    MipAnalysisRow,
    NormalValidationRow,
    SidecarDiscoveryRow,
    TextureClassificationRow,
    TextureSetGroup,
    TextureUsageHeatRow,
)
from cdmw.ui.research.models import (
    build_classification_item,
    build_heatmap_scope_parent_item,
    build_heatmap_usage_item,
    build_mip_item,
    build_normal_item,
    build_reference_row_item,
    build_sidecar_row_item,
    build_texture_group_item,
    build_ui_constraint_row_item,
)

__all__ = [
    "populate_research_classification_tree",
    "populate_research_heatmap_tree",
    "populate_research_mip_tree",
    "populate_research_normal_tree",
    "populate_research_reference_tree",
    "populate_research_sidecar_tree",
    "populate_research_texture_group_tree",
    "populate_research_ui_constraint_tree",
]


def _select_first_item(tree: QTreeWidget) -> QTreeWidgetItem | None:
    if tree.topLevelItemCount() <= 0:
        return None
    first = tree.topLevelItem(0)
    if first is not None:
        tree.setCurrentItem(first)
    return first


def populate_research_texture_group_tree(tree: QTreeWidget, groups: object) -> QTreeWidgetItem | None:
    tree.setUpdatesEnabled(False)
    try:
        tree.clear()
        first_group_item: QTreeWidgetItem | None = None
        for group in groups if isinstance(groups, list) else []:
            if not isinstance(group, TextureSetGroup):
                continue
            parent = build_texture_group_item(group)
            tree.addTopLevelItem(parent)
            if first_group_item is None:
                first_group_item = parent
        if first_group_item is not None:
            tree.setCurrentItem(first_group_item)
        return first_group_item
    finally:
        tree.setUpdatesEnabled(True)


def populate_research_classification_tree(tree: QTreeWidget, rows: object) -> None:
    tree.setUpdatesEnabled(False)
    try:
        tree.clear()
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, TextureClassificationRow):
                tree.addTopLevelItem(build_classification_item(row))
    finally:
        tree.setUpdatesEnabled(True)


def populate_research_heatmap_tree(tree: QTreeWidget, rows: object) -> None:
    tree.setUpdatesEnabled(False)
    try:
        tree.clear()
        grouped: dict[str, QTreeWidgetItem] = {}
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, TextureUsageHeatRow):
                continue
            parent = grouped.get(row.scope)
            if parent is None:
                parent = build_heatmap_scope_parent_item(row.scope)
                grouped[row.scope] = parent
                tree.addTopLevelItem(parent)
            parent.addChild(build_heatmap_usage_item(row))
    finally:
        tree.setUpdatesEnabled(True)


def populate_research_mip_tree(tree: QTreeWidget, rows: object) -> bool:
    tree.setUpdatesEnabled(False)
    try:
        tree.clear()
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, MipAnalysisRow):
                tree.addTopLevelItem(build_mip_item(row))
        return _select_first_item(tree) is not None
    finally:
        tree.setUpdatesEnabled(True)


def populate_research_normal_tree(tree: QTreeWidget, rows: object, *, select_first: bool) -> bool:
    tree.setUpdatesEnabled(False)
    try:
        tree.clear()
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, NormalValidationRow):
                tree.addTopLevelItem(build_normal_item(row))
        return bool(select_first and _select_first_item(tree) is not None)
    finally:
        tree.setUpdatesEnabled(True)


def populate_research_reference_tree(tree: QTreeWidget, rows: object) -> bool:
    tree.clear()
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, MaterialTextureReferenceRow):
            tree.addTopLevelItem(build_reference_row_item(row))
    return _select_first_item(tree) is not None


def populate_research_ui_constraint_tree(tree: QTreeWidget, rows: object) -> None:
    tree.clear()
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, MaterialTextureReferenceRow):
            tree.addTopLevelItem(build_ui_constraint_row_item(row))


def populate_research_sidecar_tree(tree: QTreeWidget, rows: object) -> bool:
    tree.clear()
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, SidecarDiscoveryRow):
            tree.addTopLevelItem(build_sidecar_row_item(row))
    return _select_first_item(tree) is not None
