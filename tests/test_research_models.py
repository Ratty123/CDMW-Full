from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTreeWidget

from cdmw.core.research import (
    MaterialTextureReferenceRow,
    MipAnalysisRow,
    ResearchNote,
    SidecarDiscoveryRow,
    TextureBudgetRow,
    TextureClassificationRow,
    TextureSetGroup,
    TextureSetMember,
    TextureUsageHeatRow,
    UnknownResolverGroup,
    UnknownResolverMember,
)
from cdmw.models import ArchiveEntry
from cdmw.ui.research.models import (
    archive_picker_folder_key,
    archive_picker_item_kind,
    archive_picker_item_value,
    build_archive_picker_file_item,
    build_archive_picker_folder_item,
    build_budget_file_item,
    build_classification_item,
    build_heatmap_scope_item,
    build_mip_item,
    build_note_item,
    build_reference_row_item,
    build_sidecar_row_item,
    build_texture_group_item,
    build_ui_constraint_row_item,
    build_ui_constraint_item,
    build_unknown_group_item,
    build_unknown_member_item,
    current_archive_picker_entry_from_item,
    current_unknown_group_from_item,
    find_archive_picker_file_item,
    item_payload,
    item_user_role,
    resolve_texture_group_item,
    selected_unknown_groups_from_items,
    selected_texture_group_from_items,
    texture_group_member_paths,
)


_APP = QApplication.instance() or QApplication([])


def test_texture_group_and_classification_items_format_core_columns() -> None:
    group = TextureSetGroup(
        group_key="texture/armor",
        display_name="Armor",
        member_count=2,
        package_labels=["pak_a", "pak_b"],
        member_kinds=["color", "normal"],
        members=[
            TextureSetMember("texture/armor_a.dds", "pak_a", "color", ".dds"),
            TextureSetMember("texture/armor_n.dds", "pak_a", "normal", ".dds"),
        ],
    )
    group_item = build_texture_group_item(group)
    assert group_item.text(0) == "Armor"
    assert group_item.text(1) == "2"
    assert group_item.childCount() == 2
    assert group_item.child(0).text(0) == "armor_a.dds"
    assert group_item.toolTip(0) == "texture/armor"
    assert resolve_texture_group_item(group_item.child(0)) is group_item.child(0)
    assert selected_texture_group_from_items([group_item.child(0)], [group]) is group
    assert selected_texture_group_from_items([], [group]) is None
    assert selected_texture_group_from_items([group_item.child(0)], object()) is None
    assert texture_group_member_paths(group) == ["texture/armor_a.dds", "texture/armor_n.dds"]
    assert texture_group_member_paths(None) == []

    row = TextureClassificationRow("texture/armor_a.dds", "pak_a", "color", 88, "name match", "texture/armor")
    item = build_classification_item(row)
    assert item.text(0) == "armor_a.dds"
    assert item.text(2) == "88%"
    assert item.toolTip(0) == "texture/armor_a.dds"


def test_archive_picker_items_mark_folder_and_file_payloads() -> None:
    folder_item = build_archive_picker_folder_item(("0001", "texture"), has_children=True)
    assert folder_item.text(0) == "texture"
    assert folder_item.childCount() == 1
    assert folder_item.child(0).text(0) == "Loading..."
    assert archive_picker_item_kind(folder_item) == "folder"
    assert archive_picker_folder_key(folder_item) == ("0001", "texture")

    entry = ArchiveEntry(
        path=r"0001\texture\armor.dds",
        pamt_path=Path("pakchunk0/paz00001.paz"),
        paz_file=Path("pakchunk0/paz00001.paz"),
        offset=0,
        comp_size=1,
        orig_size=1,
        flags=0,
        paz_index=0,
    )
    file_item = build_archive_picker_file_item(entry, 7, show_full_path=False)
    assert file_item.text(0) == "armor.dds"
    assert file_item.text(1) == ".dds"
    assert file_item.toolTip(0) == r"0001\texture\armor.dds"
    assert archive_picker_item_kind(file_item) == "file"
    assert archive_picker_item_value(file_item) == 7
    assert item_user_role(file_item) == "file"
    assert item_payload(file_item, str) == "file"
    assert item_payload(file_item, ArchiveEntry) is None
    assert current_archive_picker_entry_from_item(file_item, [entry]) is None
    entries = [entry] * 8
    assert current_archive_picker_entry_from_item(file_item, entries) is entry
    assert current_archive_picker_entry_from_item(folder_item, [entry]) is None
    assert archive_picker_item_kind(None) == ""
    assert archive_picker_item_value(None) is None
    assert archive_picker_folder_key(file_item) == ()

    tree = QTreeWidget()
    tree.addTopLevelItem(file_item)
    assert find_archive_picker_file_item(tree, 7) is file_item
    assert find_archive_picker_file_item(tree, 8) is None


def test_note_item_formats_tags_and_payload_key() -> None:
    note = ResearchNote(
        target_key="texture/armor.dds",
        source_kind="archive",
        tags=["armor", "review"],
        note="Check replacement.",
        updated_at="2026-06-13T01:00:00",
    )

    item = build_note_item("texture/armor.dds", note)

    assert item.text(0) == "texture/armor.dds"
    assert item.text(1) == "armor, review"
    assert item.text(3) == "archive"
    assert item.data(0, 256) == "texture/armor.dds"
    assert item.toolTip(1) == "armor, review"


def test_heatmap_mip_and_constraint_items_format_payloads() -> None:
    heat_item = build_heatmap_scope_item(
        (
            "world",
            [TextureUsageHeatRow("world", "terrain", 3, 2, 1, 0, 1, 0, 75, ["a.dds"])],
        )
    )
    assert heat_item.text(0) == "world"
    assert heat_item.child(0).text(1) == "75"
    assert heat_item.child(0).toolTip(0) == "a.dds"

    mip = MipAnalysisRow(
        "texture/armor.dds",
        "BC7",
        "BC7",
        "512x512",
        "1024x1024",
        8,
        9,
        1,
        planner_profile="Default",
        planner_path_kind="color",
        warnings=["Mip changed"],
    )
    mip_item = build_mip_item(mip)
    assert mip_item.text(3) == "8 -> 9"
    assert "Planner profile: Default" in mip_item.toolTip(4)

    ui_row = MaterialTextureReferenceRow(
        "ui/layout.xml",
        "pak_a",
        "texture/ui.dds",
        "pak_a",
        "ui_rect",
        1,
        "GetRect",
        texture_width=64,
        texture_height=32,
        get_rect_raw="0,0,64,32",
    )
    ui_item = build_ui_constraint_item(ui_row)
    assert ui_item.text(0) == "texture/ui.dds"
    assert ui_item.text(2) == "64x32"


def test_budget_file_item_formats_growth_and_risk() -> None:
    row = TextureBudgetRow(
        relative_path="texture/armor.dds",
        group_key="texture/armor",
        system_area="characters",
        folder_bucket="texture",
        texture_type="color",
        planner_profile="Default",
        planner_path_kind="color",
        planner_alpha_policy="preserve",
        original_bytes=100,
        rebuilt_bytes=250,
        byte_delta=150,
        byte_ratio=2.5,
        original_width=512,
        original_height=512,
        rebuilt_width=1024,
        rebuilt_height=1024,
        pixel_ratio=4.0,
        original_mips=8,
        rebuilt_mips=9,
        mip_delta=1,
        original_format="BC7",
        rebuilt_format="BC7",
        format_changed=False,
        changed=True,
        risk_score=42,
        risk_band="Medium",
        risk_signals=["Large growth"],
    )
    item = build_budget_file_item(row)
    assert item.text(1) == "+150"
    assert item.text(2) == "2.50x"
    assert item.text(5) == "42 (Medium)"
    assert "Large growth" in item.toolTip(5)


def test_unknown_reference_ui_and_sidecar_items_format_rows() -> None:
    member = UnknownResolverMember(
        "texture/armor_unknown.dds",
        "pak_a",
        "unknown",
        "needs review",
        role_hint="mask?",
        extension=".dds",
    )
    group = UnknownResolverGroup(
        "texture/armor",
        "Armor",
        1,
        1,
        ["pak_a", "pak_b"],
        [],
        [],
        members=[member],
        local_approval_state="Missing",
    )
    group_item = build_unknown_group_item(
        group,
        display_name="armor_unknown.dds",
        classification_text="Unknown",
        package_text="pak_a, pak_b",
    )
    assert group_item.text(0) == "armor_unknown.dds"
    assert group_item.text(2) == "Missing"
    assert group_item.toolTip(3) == "pak_a, pak_b"
    assert current_unknown_group_from_item(group_item) is group
    assert current_unknown_group_from_item(None) is None
    assert selected_unknown_groups_from_items([group_item, group_item]) == [group]

    member_item = build_unknown_member_item(member, local_text="No")
    assert member_item.text(0) == "armor_unknown.dds"
    assert member_item.text(2) == "No"
    assert member_item.toolTip(0) == "texture/armor_unknown.dds"
    assert selected_unknown_groups_from_items([member_item]) == []

    reference = MaterialTextureReferenceRow(
        "ui/layout.xml",
        "pak_a",
        "texture/ui.dds",
        "pak_b",
        "ui_rect",
        12,
        "snippet",
        get_rect_raw="0,0,64,32",
        constraint_kind="Explicit UI rect",
    )
    reference_item = build_reference_row_item(reference)
    assert reference_item.text(0) == "ui/layout.xml"
    assert reference_item.text(4) == "12"
    assert reference_item.toolTip(0) == "snippet"

    ui_item = build_ui_constraint_row_item(reference)
    assert ui_item.text(0) == "texture/ui.dds"
    assert ui_item.text(3) == "0,0,64,32"

    sidecar_item = build_sidecar_row_item(
        SidecarDiscoveryRow("model.pac", "texture/ui.dds", "pak_a", "sidecar", 91, "nearby")
    )
    assert sidecar_item.text(2) == "91%"
    assert sidecar_item.toolTip(0) == "texture/ui.dds"
