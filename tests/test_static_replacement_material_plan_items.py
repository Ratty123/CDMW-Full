from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from cdmw.ui.archive_browser.static_replacement_material_plan_items import (
    donor_material_plan_item,
    donor_part_tree_item,
    donor_texture_binding_item,
    empty_donor_part_tree_item,
    final_binding_row_item,
    final_material_status_item,
    material_plan_item_selection,
    replacement_texture_plan_item,
    source_material_route_item,
)

_APP = QApplication.instance() or QApplication([])


def test_material_plan_item_selection_normalizes_sources_and_text_fields() -> None:
    item = source_material_route_item(
        SimpleNamespace(
            status="Routed",
            source_part_names=("Body",),
            detected_roles=("base",),
            reason="Use source material",
            source_material_name="Skin",
            target_material_name="BodyMat",
        ),
        source_indices=("2", "bad", 1),
        target_index=4,
        status_color="#3fb950",
    )
    item.setText(1, "Base")
    item.setText(3, "body.dds")

    selection = material_plan_item_selection(item)

    assert selection.has_item is True
    assert selection.source_indices == (1, 2)
    assert selection.target_index == 4
    assert selection.material_name == "Skin"
    assert selection.texture_role == "Base"
    assert selection.texture_path == "body.dds"
    assert material_plan_item_selection(None).has_item is False


def test_source_material_route_item_sets_columns_roles_and_detail_html() -> None:
    route = SimpleNamespace(
        status="Routed",
        source_part_names=("Body", "Arms"),
        detected_roles=("base", "normal"),
        reason="Use source material",
        source_material_name="Skin",
        target_material_name="BodyMat",
    )

    item = source_material_route_item(route, source_indices=(1, 2), target_index=4, status_color="#3fb950")

    assert item.text(0) == "BodyMat"
    assert item.text(1) == "Skin"
    assert item.text(2) == "Body, Arms"
    assert item.data(0, Qt.UserRole) == (1, 2)
    assert item.data(0, Qt.UserRole + 1) == 4
    assert item.data(0, Qt.UserRole + 2) == "Skin"
    assert "Use source material" in item.data(0, Qt.UserRole + 3)
    assert item.foreground(4).color().name() == "#3fb950"


def test_replacement_texture_plan_item_keeps_source_preview_and_status_roles() -> None:
    plan_row = SimpleNamespace(
        part_label="Body",
        part_material="Body / Skin",
        full_part_material="Body / Skin",
        role="Base",
        source="skin.png",
        final_path="skin.dds",
        controls="Copy",
        slot_kind="base",
        status=SimpleNamespace(label="Ready"),
    )

    item = replacement_texture_plan_item(
        plan_row,
        source_indices=(3,),
        target_index=7,
        target_name="BodyTarget",
        material_name="Skin",
        source_preview_path="skin.preview.png",
        preview_status="thumbnail if decoded; final path via Test Build",
        status_color="#3fb950",
        status_foreground="#0d1117",
    )

    assert item.text(0) == "Body"
    assert item.text(4) == "Ready"
    assert item.data(0, Qt.UserRole) == (3,)
    assert item.data(0, Qt.UserRole + 1) == 7
    assert item.data(0, Qt.UserRole + 4) == "skin.preview.png"
    assert item.data(0, Qt.UserRole + 6) == "base"
    assert "BodyTarget" in item.data(0, Qt.UserRole + 3)
    assert item.background(4).color().name() == "#3fb950"


def test_final_preview_items_store_contract_context() -> None:
    status_item = final_material_status_item(
        material_name="Skin",
        source_parts="Body",
        maps="Base, Normal",
        status_label="ready",
        detail="validated",
        source_indices=(5,),
        target_index=9,
        status_color="#79c0ff",
    )
    assert status_item.text(2) == "Body"
    assert status_item.data(0, Qt.UserRole + 1) == 9
    assert "Final status" in status_item.data(0, Qt.UserRole + 3)

    binding_row = SimpleNamespace(
        status="ready",
        resolved_texture_path="out/body.dds",
        texture_path="in/body.png",
        sidecar_path="body.pac_xml",
        parameter_name="BaseColor",
        role="Base",
        preview_texture_path="body.preview.png",
        binding_source="copied",
        detail="ok",
    )
    binding_item = final_binding_row_item(
        binding_row,
        part_label="Body",
        part_name="BodyPart",
        material_name="Skin",
        source_indices=(5,),
        target_index=9,
        preview_status="thumbnail",
        status_color="#79c0ff",
        slot_kind="base",
    )
    assert binding_item.text(0) == "Body"
    assert binding_item.text(3) == "out/body.dds"
    assert binding_item.data(0, Qt.UserRole + 2) == "Skin"
    assert binding_item.data(0, Qt.UserRole + 4) == "body.preview.png"
    assert "BaseColor" in binding_item.data(0, Qt.UserRole + 3)


def test_donor_material_plan_item_labels_mode_status_and_target_role() -> None:
    plan = SimpleNamespace(
        patch_mode="authoritative_recipe",
        donor_material_name="DonorSkin",
        donor_submesh_name="",
        donor_sidecar_path="materials/donor.pac_xml",
        donor_shader_family="skin_shader",
        texture_bindings=(SimpleNamespace(semantic_subtype="emissive", parameter_name="_GlowTexture"),),
    )

    item = donor_material_plan_item(3, plan, target_display_name="Body target")

    assert item.text(0) == "Body target"
    assert item.text(1) == "Authoritative donor recipe"
    assert item.text(2) == "DonorSkin"
    assert item.text(4) == "emissive/glow"
    assert item.data(0, Qt.UserRole) == 3
    assert item.data(0, Qt.UserRole + 1) is plan
    assert item.foreground(4).color().name() == "#facc15"


def test_donor_picker_items_store_bindings_and_texture_state() -> None:
    binding = SimpleNamespace(shader_family="skin_shader")
    row = {"part_name": "Body", "shader": "skin_shader", "bindings": (binding,), "emissive": True}

    part_item = donor_part_tree_item(row)

    assert part_item.text(0) == "Body"
    assert part_item.text(2) == "1"
    assert part_item.text(3) == "Yes"
    assert part_item.data(0, Qt.UserRole) == (binding,)
    assert part_item.data(0, Qt.UserRole + 1) == "Body"
    assert part_item.foreground(3).color().name() == "#facc15"

    empty_item = empty_donor_part_tree_item()
    assert empty_item.text(0) == "No material wrappers found"
    assert "No readable donor material wrappers" in empty_item.toolTip(0)

    texture_item = donor_texture_binding_item(
        binding,
        slot_label="Base",
        parameter_name="_BaseTexture",
        texture_path="textures/body.dds",
        state="emissive/glow",
    )
    assert texture_item.text(0) == "Base"
    assert texture_item.text(2) == "body.dds"
    assert texture_item.data(0, Qt.UserRole) is binding
    assert texture_item.toolTip(2) == "textures/body.dds"
    assert texture_item.foreground(4).color().name() == "#facc15"
