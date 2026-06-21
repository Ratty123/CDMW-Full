from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTreeWidget

from cdmw.ui.archive_browser.static_replacement_part_items import (
    assignment_source_item,
    mapping_target_item,
    original_part_tree_item,
    parts_outliner_source_item,
    parts_outliner_target_item,
    parts_outliner_unassigned_group_item,
    source_tree_item,
)

_APP = QApplication.instance() or QApplication([])


def test_assignment_source_item_stores_source_role_and_geometry() -> None:
    tree = QTreeWidget()

    item = assignment_source_item(
        tree,
        source_index=5,
        display_name="Source 5: Cape",
        geometry_text="12 vertices, 6 faces",
        tooltip="CapeMat",
    )

    assert tree.topLevelItem(0) is item
    assert item.text(0) == "Source 5: Cape"
    assert item.text(1) == "12 vertices, 6 faces"
    assert item.data(0, Qt.UserRole) == 5
    assert item.toolTip(0) == "CapeMat"


def test_source_and_original_part_items_store_roles_and_tooltips() -> None:
    source_item = source_tree_item(
        source_index=2,
        label="Cape",
        role_hint="cloth",
        geometry_text="10 vertices, 4 faces",
        source_name="cape_mesh",
        source_material="CapeMat",
        copied_texture_count=2,
        copied_texture_disabled=False,
        copied_texture_tooltip="copied dds",
        enabled=True,
    )
    assert source_item.text(1) == "2"
    assert source_item.text(5) == "Preview-only | Copied Orig 2"
    assert source_item.data(0, Qt.UserRole) == (2,)
    assert source_item.checkState(0) == Qt.Checked
    assert "CapeMat" in source_item.toolTip(2)
    assert source_item.foreground(5).color().name() == "#3fb950"

    original_item = original_part_tree_item(
        original_index=4,
        label="Body",
        role_hint="body",
        geometry_text="20 vertices, 8 faces",
        source_name="body_mesh",
        source_material="BodyMat",
    )
    assert original_item.text(0) == "4"
    assert original_item.data(0, Qt.UserRole) == (4,)
    assert "body_mesh" in original_item.toolTip(1)


def test_mapping_target_item_stores_target_roles_and_review_state() -> None:
    item = mapping_target_item(
        target_index=3,
        target_label_text="Target 3: Body",
        target_role_hint="body",
        selected_display="Source 2",
        outliner_state="Assigned",
        outliner_state_color="#86efac",
        target_dds_status="DDS Ready",
        physics_status="Review",
        initial_source_indices=(2,),
        confidence_label_text="Mapped: High (0.9)",
        target_details="target details",
        target_texture_details="texture details",
        selected_ok=False,
        removed=False,
        mapping_text_empty=False,
    )

    assert item.text(0) == "Target 3: Body"
    assert item.text(3) == "Source 2"
    assert item.data(0, Qt.UserRole) == (2,)
    assert item.data(0, Qt.UserRole + 1) == 3
    assert item.data(0, Qt.UserRole + 2) == "mapped: high (0.9)"
    assert item.data(0, Qt.UserRole + 3) is False
    assert item.toolTip(5) == "texture details"
    assert item.foreground(3).color().name() == "#fca5a5"
    assert item.foreground(4).color().name() == "#86efac"
    assert item.foreground(6).color().name() == "#f2cc60"


def test_mapping_target_item_marks_removed_targets() -> None:
    item = mapping_target_item(
        target_index=4,
        target_label_text="Target 4: Removed",
        target_role_hint="misc",
        selected_display="None",
        outliner_state="Removed",
        outliner_state_color="#fb923c",
        target_dds_status="Pruned",
        physics_status="OK",
        initial_source_indices=(),
        confidence_label_text="Remove Original Part",
        target_details="target details",
        target_texture_details="texture details",
        selected_ok=True,
        removed=True,
        mapping_text_empty=True,
    )

    assert item.data(0, Qt.UserRole + 3) is True
    assert item.foreground(5).color().name() == "#fb923c"
    assert "Removed target" in item.toolTip(5)


def test_parts_outliner_items_store_target_source_and_unassigned_roles() -> None:
    target_item = parts_outliner_target_item(
        target_index=1,
        label="Target 1: Body",
        role_hint="body",
        dds_text="Ready",
        state_text="Kept",
        state_color="#3fb950",
        physics_text="Review",
        geometry_text="20 vertices",
        source_indices=(2, 3),
        texture_tooltip="texture detail",
        physics_tooltip="physics detail",
    )
    assert target_item.text(0) == "Target 1: Body"
    assert target_item.data(0, Qt.UserRole) == "target"
    assert target_item.data(0, Qt.UserRole + 2) == (2, 3)
    assert target_item.toolTip(3) == "texture detail"
    assert target_item.foreground(5).color().name() == "#f2cc60"

    source_item = parts_outliner_source_item(
        source_index=2,
        target_index=1,
        label="  -> Cape",
        target_text="Body",
        role_label="cloth",
        dds_text="DDS Ready",
        state_text="Assigned",
        state_color="#86efac",
        physics_text="Preserved",
        geometry_text="10 vertices",
        physics_tooltip="physics ok",
        copied_texture_tooltip="copied dds",
    )
    assert source_item.data(0, Qt.UserRole) == "source"
    assert source_item.data(0, Qt.UserRole + 1) == 1
    assert source_item.data(0, Qt.UserRole + 2) == (2,)
    assert source_item.toolTip(3) == "copied dds"
    assert source_item.foreground(5).color().name() == "#7ee787"

    group_item = parts_outliner_unassigned_group_item(12)
    assert group_item.text(6) == "12 part(s)"
    assert group_item.data(0, Qt.UserRole) == "unassigned_group"
