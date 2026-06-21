from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTreeWidget, QTreeWidgetItem

from cdmw.ui.archive_browser import static_replacement_texture_table as texture_table_compat
from cdmw.ui.archive_browser.static_replacement_texture_table import (
    all_suggested_texture_plan_rows,
    all_suggested_override_sources_action_state,
    dds_detail_clear_state,
    dds_detail_item_state,
    dds_detail_refresh_route_state,
    dds_detail_resolved_thumbnail_state,
    dds_detail_thumbnail_state,
    deferred_material_plan_display_state,
    empty_material_plan_display_state,
    final_dds_contract_summary_html,
    final_preview_binding_target_index,
    final_preview_binding_row_states,
    final_preview_material_status_row_states,
    final_preview_plan_state,
    material_plan_column_fit_specs,
    material_plan_column_refit_requests,
    material_plan_control_text,
    material_plan_profile_stats,
    material_plan_route_stats,
    registered_texture_sources_action_state,
    replacement_texture_plan_row_states,
    replacement_texture_plan_target_name,
    reset_selected_texture_plan_source_state,
    selected_material_override_rows,
    selected_material_texture_clear_action_state,
    selected_material_texture_file_action_state,
    selected_source_material_indices,
    selected_source_material_texture_action_state,
    selected_source_material_texture_plan_rows,
    selected_texture_editor_loading_initial_state,
    selected_texture_editor_state,
    selected_texture_plan_source_initial_state,
    selected_texture_row_initial_state,
    selected_texture_source_commit_state,
    selected_texture_source_combo_change_state,
    selected_texture_source_committing_initial_state,
    source_material_route_row_states,
    source_material_plan_display_state,
    suggested_texture_plan_action_state,
    suggested_texture_plan_rows,
    target_texture_clear_assignment_state,
    texture_clear_assignment_state,
    texture_details_state,
    texture_editor_control_text,
    texture_filter_refresh_initial_state,
    texture_material_plan_loaded_initial_state,
    texture_set_for_selected_source_material,
)
from cdmw.ui.archive_browser.static_replacement_texture_table_items import (
    apply_texture_row_to_item,
    texture_assignment_slot_item,
    texture_item_for_row,
    texture_override_item,
)
from cdmw.ui.archive_browser.static_replacement_material_route_state import (
    material_plan_detail_state,
    material_route_control_state,
)

_APP = QApplication.instance() or QApplication([])


def test_texture_table_compatibility_exports_item_helpers() -> None:
    assert texture_table_compat.apply_texture_row_to_item is apply_texture_row_to_item
    assert texture_table_compat.all_suggested_override_sources_action_state is all_suggested_override_sources_action_state
    assert texture_table_compat.registered_texture_sources_action_state is registered_texture_sources_action_state
    assert texture_table_compat.selected_material_texture_clear_action_state is selected_material_texture_clear_action_state
    assert texture_table_compat.selected_material_texture_file_action_state is selected_material_texture_file_action_state
    assert texture_table_compat.selected_source_material_texture_action_state is selected_source_material_texture_action_state
    assert texture_table_compat.selected_texture_source_combo_change_state is selected_texture_source_combo_change_state
    assert texture_table_compat.suggested_texture_plan_action_state is suggested_texture_plan_action_state
    assert texture_table_compat.dds_detail_clear_state is dds_detail_clear_state
    assert texture_table_compat.dds_detail_refresh_route_state is dds_detail_refresh_route_state
    assert texture_table_compat.dds_detail_resolved_thumbnail_state is dds_detail_resolved_thumbnail_state
    assert texture_table_compat.final_preview_plan_state is final_preview_plan_state
    assert texture_table_compat.material_plan_profile_stats is material_plan_profile_stats
    assert texture_table_compat.material_plan_route_stats is material_plan_route_stats
    assert texture_table_compat.replacement_texture_plan_row_states is replacement_texture_plan_row_states
    assert texture_table_compat.replacement_texture_plan_target_name is replacement_texture_plan_target_name
    assert texture_table_compat.source_material_plan_display_state is source_material_plan_display_state
    assert texture_table_compat.texture_assignment_slot_item is texture_assignment_slot_item
    assert texture_table_compat.texture_item_for_row is texture_item_for_row
    assert texture_table_compat.texture_override_item is texture_override_item


def test_selected_texture_plan_source_initial_state_preserves_defaults() -> None:
    assert selected_texture_plan_source_initial_state() == {"material_name": "", "source_indices": ()}


def test_selected_texture_editor_initial_states_preserve_defaults() -> None:
    assert selected_texture_row_initial_state() == {"row": None}
    assert selected_texture_editor_loading_initial_state() == {"active": False}
    assert selected_texture_source_committing_initial_state() == {"active": False}
    assert texture_filter_refresh_initial_state() == {"func": None}


def test_selected_texture_source_commit_state_detects_changes() -> None:
    unchanged = selected_texture_source_commit_state(
        " current.dds ",
        current_source="current.dds",
        current_checked=True,
    )
    assert unchanged.source_path == "current.dds"
    assert unchanged.desired_checked is True
    assert unchanged.changed is False

    cleared = selected_texture_source_commit_state(
        "",
        current_source="current.dds",
        current_checked=True,
    )
    assert cleared.source_path == ""
    assert cleared.desired_checked is False
    assert cleared.changed is True


def test_selected_texture_source_combo_change_state_normalizes_index_and_source() -> None:
    choices = ["", " chosen.dds ", "fallback.dds"]

    state = selected_texture_source_combo_change_state(
        "1",
        current_index=lambda: 2,
        count=lambda: len(choices),
        item_data=lambda index: choices[index],
    )

    assert state.combo_index == 1
    assert state.source_path == "chosen.dds"

    fallback = selected_texture_source_combo_change_state(
        99,
        current_index=lambda: 2,
        count=lambda: len(choices),
        item_data=lambda index: choices[index],
    )

    assert fallback.combo_index == 2
    assert fallback.source_path == "fallback.dds"


def test_texture_clear_assignment_state_tracks_rows() -> None:
    rows = [{"target_name": "Body"}, {"target_name": "Body"}]

    state = texture_clear_assignment_state(rows)

    assert state.rows == tuple(rows)
    assert state.has_rows is True
    assert texture_clear_assignment_state(()).has_rows is False


def test_target_texture_clear_assignment_state_reads_target_rows() -> None:
    body_rows = [{"target_name": "Body"}]
    rows_by_target = {"Body": body_rows}

    state = target_texture_clear_assignment_state(rows_by_target, "Body")

    assert state.rows == tuple(body_rows)
    assert state.has_rows is True
    assert target_texture_clear_assignment_state(rows_by_target, "Missing").rows == ()


def test_texture_material_plan_loaded_initial_state_preserves_flags() -> None:
    assert texture_material_plan_loaded_initial_state() == {"loaded": False, "loading": False}


def test_material_plan_control_text_preserves_route_and_dialog_copy() -> None:
    text = material_plan_control_text()

    assert text["group_title"] == "Materials"
    assert text["contract_tooltip"] == "Stock/shared shader layers and helper wrappers are preserved by default."
    assert text["final_contract_tooltip"] == "Final texture contract resolved from packaged sidecar/DDS payloads."
    assert text["apply_suggested"] == "Apply Suggested"
    assert "source texture plan" in str(text["apply_suggested_tooltip"])
    assert text["use_selected"] == "Use Selected"
    assert text["use_route_source"] == "Use route source"
    assert text["keep_original"] == "Keep original"
    assert text["choose_file"] == "Choose file"
    assert text["neutralize"] == "Neutralize"
    assert text["do_not_emit"] == "Do not emit"
    assert text["advanced_routes"] == "Advanced Routes"
    assert text["material_routing_headers"] == ["Target", "Source", "Parts", "Maps", "State", "Action"]
    assert text["material_plan_headers"] == ["Part", "Role", "Source", "DDS", "Preview", "Param"]
    assert text["dds_detail_no_preview"] == "No preview"
    assert text["dds_detail_select_row"] == "Select a row."
    assert text["dds_detail_not_previewable"] == "Not previewable"
    assert str(text["dds_detail_preview_read_failed"]).format(preview_path="preview.png") == (
        "Preview image could not be read: preview.png"
    )
    assert text["apply_suggested_reason"] == "Apply compatible sources; ambiguous rows stay unchanged."
    assert text["use_selected_missing_message"] == "Select a material row first."
    assert text["use_selected_base_enabled"] == "Base/color binding enabled."
    assert text["use_selected_no_rows"] == "No compatible rows matched."
    assert str(text["use_selected_reason"]).format(material_name="Body") == "Apply detected textures from Body."
    assert text["texture_route_title"] == "Texture Route"
    assert text["texture_route_select_first"] == "Select a material route first."
    assert text["choose_route_texture_title"] == "Choose Texture For Selected Route"
    assert text["add_replacement_textures_title"] == "Add Replacement Textures"
    assert text["add_replacement_folder_title"] == "Add Replacement Texture Folder"


def test_material_plan_column_specs_and_refit_requests_preserve_tree_sizing() -> None:
    specs = material_plan_column_fit_specs()

    assert specs["routing"] == {
        "minimum_widths": (90, 90, 110, 60, 58, 120),
        "maximum_widths": (240, 240, 320, 120, 92, 420),
        "expand_columns": (5, 2, 0, 1),
    }
    assert specs["plan"] == {
        "minimum_widths": (72, 58, 150, 230, 58, 90),
        "maximum_widths": (140, 120, 360, 520, 92, 240),
        "expand_columns": (3, 2, 5),
    }
    assert material_plan_column_refit_requests() == (
        (0, "routing"),
        (0, "plan"),
        (150, "routing"),
        (150, "plan"),
    )


def test_material_plan_projection_states_preserve_counts_and_rows() -> None:
    selected = {"material_name": "Body", "source_indices": (1,)}
    reset_selected_texture_plan_source_state(selected)
    assert selected == {"material_name": "", "source_indices": ()}

    stats = material_plan_profile_stats(
        (
            {"material_profile_label": " Skin ", "material_profile_shader": "PBR", "material_profile_emissive": True},
            {"material_profile_label": "Skin", "material_profile_shader": "PBR"},
            {"material_profile_label": "Cloth", "material_profile_shader": "ClothShader"},
            "ignored",
        )
    )
    assert stats.material_count == 2
    assert stats.shader_count == 2
    assert stats.emissive_count == 1

    route = SimpleNamespace(
        status="Ready",
        source_part_names=("Body", "Cape"),
        source_material_name="BodyMat",
        target_material_name="TargetMat",
        detected_roles=("base", "normal"),
        blocker=False,
    )
    blocker = SimpleNamespace(reason="blocked route", detected_roles=("roughness",), blocker=True)
    texture_sets = {"body": SimpleNamespace(slots={"metallic": object(), "normal": object()})}

    route_stats = material_plan_route_stats(texture_sets, (route, blocker), ("manual conflict",))
    assert route_stats.conflict_messages == ("manual conflict", "blocked route")
    assert route_stats.routing_blockers == (blocker,)
    assert route_stats.base_route_count == 1
    assert route_stats.normal_route_count == 1
    assert route_stats.pbr_count == 1

    route_rows = source_material_route_row_states((route,))
    assert route_rows[0].status_label == "Ready"
    assert route_rows[0].source_part_names == ("Body", "Cape")
    assert route_rows[0].source_material_name == "BodyMat"
    assert route_rows[0].target_material_name == "TargetMat"

    deferred = deferred_material_plan_display_state({"body": SimpleNamespace(slots={"base": object(), "normal": object()})})
    assert deferred.summary_kwargs == {
        "detected_sets": 1,
        "detected_slots": 2,
        "conflicts": ("Deferred until opened.",),
        "empty": False,
    }
    assert deferred.contract_kwargs["route_count"] == 0
    assert deferred.routing_visible is False
    assert deferred.apply_texture_plan_enabled is False

    empty = empty_material_plan_display_state()
    assert empty.summary_kwargs["empty"] is True
    assert empty.plan_visible is False

    ready = source_material_plan_display_state(
        texture_sets,
        detected_slot_count=5,
        route_count=2,
        route_stats=route_stats,
        profile_stats=stats,
        has_sidecar_bindings=True,
    )
    assert ready.summary_kwargs["detected_sets"] == 1
    assert ready.summary_kwargs["profile_material_count"] == 2
    assert ready.contract_kwargs == {
        "route_count": 2,
        "blocker_count": 1,
        "base_count": 1,
        "normal_count": 1,
        "pbr_count": 1,
    }
    assert ready.routing_visible is True
    assert ready.apply_texture_plan_enabled is True


def test_material_plan_row_projection_states_preserve_preview_and_final_rows() -> None:
    ready_status = SimpleNamespace(label="Ready")
    blocked_status = SimpleNamespace(label="Blocked")
    plan_rows = (
        SimpleNamespace(status=ready_status, full_part_material="Source / Body", part_material="Fallback"),
        SimpleNamespace(status=blocked_status, full_part_material="", part_material="Cape"),
    )

    projected = replacement_texture_plan_row_states(
        plan_rows,
        ready_statuses=("Ready", "Review"),
        support_only_statuses=("Support Only",),
    )
    assert projected[0].material_name == "Body"
    assert projected[0].preview_status == "thumbnail if decoded; final path via Test Build"
    assert projected[0].status_foreground == "#0d1117"
    assert projected[1].material_name == "Cape"
    assert projected[1].preview_status == "not previewable"
    assert projected[1].status_foreground == "#ffffff"

    mappings = (
        SimpleNamespace(source_submesh_indices=("bad", 3), target_submesh_name="CapeTarget"),
        SimpleNamespace(source_submesh_indices=(1, 2), target_submesh_name="BodyTarget"),
    )
    assert replacement_texture_plan_target_name((2,), mappings) == "BodyTarget"
    assert replacement_texture_plan_target_name(("missing",), mappings) == ""

    binding_rows = (
        SimpleNamespace(material_name="Body", part_name="", role="base", status="ready"),
        SimpleNamespace(material_name="Body", part_name="BodyPart", role="normal", status="review"),
        SimpleNamespace(material_name="Cape", part_name="CapePart", role="", status="missing"),
    )
    final_preview = SimpleNamespace(
        binding_rows=binding_rows,
        material_statuses=(SimpleNamespace(material_name="Body", status="ready", detail="ok"),),
        warnings=("warn",),
    )
    plan_state = final_preview_plan_state(final_preview)
    assert plan_state.detected_sets == 2
    assert plan_state.detected_slots == 3
    assert plan_state.warnings == ("warn",)

    material_rows = final_preview_material_status_row_states(plan_state.material_statuses, plan_state.binding_rows)
    assert material_rows[0].material_name == "Body"
    assert material_rows[0].status_label == "ready"
    assert material_rows[0].detail == "ok"
    assert material_rows[0].maps == "base, normal"

    binding_states = final_preview_binding_row_states(plan_state.binding_rows)
    assert [state.part_name for state in binding_states] == ["Body", "BodyPart", "CapePart"]
    assert [state.status_label for state in binding_states] == ["ready", "review", "missing"]
    assert final_preview_binding_target_index(
        "Part",
        "Material",
        target_index_for_name=lambda name: {"Part": -1, "Material": 7}.get(name, -1),
    ) == 7


def test_dds_detail_item_and_thumbnail_states_preserve_empty_failed_and_ready_routes() -> None:
    control_text = material_plan_control_text()

    assert dds_detail_item_state(has_item=False, preview_source="source.dds", slot_kind="normal") == {
        "has_item": False,
        "preview_source": None,
        "slot_kind": "base",
    }
    assert dds_detail_item_state(has_item=True, preview_source="source.dds", slot_kind="normal") == {
        "has_item": True,
        "preview_source": "source.dds",
        "slot_kind": "normal",
    }

    empty_state = dds_detail_thumbnail_state(
        has_item=False,
        preview_path=None,
        status_text="",
        pixmap_readable=False,
        control_text=control_text,
    )
    assert empty_state.has_item is False
    assert empty_state.show_pixmap is False
    assert empty_state.text == "No preview"
    assert empty_state.tooltip == ""

    missing_state = dds_detail_thumbnail_state(
        has_item=True,
        preview_path=None,
        status_text="Missing source",
        pixmap_readable=False,
        control_text=control_text,
    )
    assert missing_state.show_pixmap is False
    assert missing_state.text == "Not previewable"
    assert missing_state.tooltip == "Missing source"

    read_failed_state = dds_detail_thumbnail_state(
        has_item=True,
        preview_path=Path("preview.png"),
        status_text="Decoded",
        pixmap_readable=False,
        control_text=control_text,
    )
    assert read_failed_state.text == "Not previewable"
    assert read_failed_state.tooltip == "Preview image could not be read: preview.png"

    ready_state = dds_detail_thumbnail_state(
        has_item=True,
        preview_path=Path("preview.png"),
        status_text="Decoded",
        pixmap_readable=True,
        control_text=control_text,
    )
    assert ready_state.show_pixmap is True
    assert ready_state.text == ""
    assert ready_state.tooltip == "Decoded\npreview.png"

    resolved_missing = dds_detail_resolved_thumbnail_state(
        preview_path=None,
        status_text="Missing source",
        pixmap_readable=False,
        control_text=control_text,
    )
    assert resolved_missing.text == "Not previewable"
    assert resolved_missing.tooltip == "Missing source"


def test_dds_detail_clear_and_refresh_route_states_drive_dialog_thumbnail_updates() -> None:
    control_text = material_plan_control_text()

    clear_state = dds_detail_clear_state(control_text)

    assert clear_state.panel_visible is False
    assert clear_state.detail_text == "Select a row."
    assert clear_state.thumbnail.text == "No preview"
    assert clear_state.thumbnail.show_pixmap is False

    no_item = dds_detail_refresh_route_state(
        has_item=False,
        preview_source="source.dds",
        slot_kind="normal",
        control_text=control_text,
    )

    assert no_item.should_resolve is False
    assert no_item.preview_source is None
    assert no_item.slot_kind == "base"
    assert no_item.thumbnail.text == "No preview"

    with_item = dds_detail_refresh_route_state(
        has_item=True,
        preview_source="source.dds",
        slot_kind=" normal ",
        control_text=control_text,
    )

    assert with_item.should_resolve is True
    assert with_item.preview_source == "source.dds"
    assert with_item.slot_kind == " normal "
    assert with_item.thumbnail.text == "No preview"


def test_material_route_control_state_requires_material_route_sidecars_and_textures() -> None:
    state = material_route_control_state(
        has_item=True,
        material_name="Body",
        has_texture_sets=True,
        has_sidecar_bindings=True,
    )

    assert state.apply_selected_source_textures_enabled
    assert state.use_route_source_enabled
    assert state.keep_original_enabled
    assert state.choose_file_enabled
    assert state.neutralize_enabled
    assert state.do_not_emit_enabled

    no_textures = material_route_control_state(
        has_item=True,
        material_name="Body",
        has_texture_sets=False,
        has_sidecar_bindings=True,
    )
    assert not no_textures.apply_selected_source_textures_enabled
    assert not no_textures.use_route_source_enabled
    assert no_textures.keep_original_enabled

    no_route = material_route_control_state(
        has_item=True,
        material_name="",
        has_texture_sets=True,
        has_sidecar_bindings=True,
    )
    assert not no_route.choose_file_enabled
    assert not no_route.do_not_emit_enabled


def test_material_plan_detail_state_tracks_visibility_text_and_transform_panel() -> None:
    state = material_plan_detail_state(
        has_item=True,
        detail_html="<b>Body</b>",
        material_name="Body",
        empty_text="Select a row.",
    )

    assert state.visible is True
    assert state.detail_html == "<b>Body</b>"
    assert state.transform_visible is True

    empty_state = material_plan_detail_state(
        has_item=False,
        detail_html="",
        material_name="",
        empty_text="Select a row.",
    )
    assert empty_state.visible is False
    assert empty_state.detail_html == "Select a row."
    assert empty_state.transform_visible is False


def test_final_dds_contract_summary_html_preserves_row_count_copy() -> None:
    html = final_dds_contract_summary_html(1234)

    assert "Final DDS</span>" in html
    assert "| rows 1,234" in html


def test_texture_editor_control_text_preserves_selected_row_copy() -> None:
    text = texture_editor_control_text()

    assert text["selected_label"] == "Selected row"
    assert text["role_label"] == "Role"
    assert text["role_tooltip"] == "Manual repair role for the selected original DDS slot."
    assert text["source_label"] == "Source"
    assert text["source_tooltip"] == "Texture source for the selected original DDS slot. Keep original disables this manual override."
    assert text["choose_button"] == "Choose..."
    assert text["choose_tooltip"] == "Open the texture source picker for the selected row."
    assert text["apply_suggestion_button"] == "Use Suggested"
    assert text["texture_assignments_busy"] == "Updating texture assignments..."
    assert text["override_headers"] == ["Target", "Source", "Role", "DDS", "Assigned", "Status", "Controls"]
    assert text["role_options"] == ("base", "normal", "height", "material")
    assert text["no_editable_slots"] == "No editable texture slots were found for the currently suggested replacement mapping."
    assert text["no_sidecar_slots"] == "No sidecar texture slots were found for this asset."


def test_apply_texture_row_to_item_populates_columns_roles_and_colors() -> None:
    row: dict[str, object] = {
        "target_name": "Body",
        "part_display": "Body",
        "parameter_name": "_base",
        "target_path": "character/texture/body.dds",
        "slot_kind": "base",
        "source_indices": (2,),
        "source_path": "mods/body.dds",
        "checked": True,
    }
    item = QTreeWidgetItem([""] * 7)

    apply_texture_row_to_item(
        item,
        row,
        sync_assignment=lambda row_state: row_state,
        source_summary=lambda _row_state: "Source 2",
        source_summary_tooltip=lambda _row_state: "Source 2 full",
        effective_source=lambda _row_state: "mods/body.dds",
        assigned=lambda _row_state: True,
        status_color_for_label=lambda _label: "#3fb950",
    )

    assert item.text(0) == "Body"
    assert item.text(1) == "Source 2"
    assert item.text(3) == "_base: body.dds"
    assert item.text(4) == "body.dds"
    assert item.text(5) == "Ready"
    assert item.data(0, Qt.UserRole) == (2,)
    assert item.data(0, Qt.UserRole + 1) == row
    assert item.toolTip(1) == "Source 2 full"
    assert item.toolTip(4) == "mods/body.dds"
    assert item.foreground(4).color().name() == "#7ee787"
    assert item.background(5).color().name() == "#3fb950"


def test_texture_assignment_slot_item_stores_binding_route_details() -> None:
    item = texture_assignment_slot_item(
        part_display="Body",
        parameter_display="_base",
        target_path="character/texture/body_base.dds",
        source_indices=(2, 4),
        target_name="body_mesh",
        binding_part_name="BodyPart",
        binding_shader_family="uber",
        binding_sidecar_kind="material",
        binding_linked_mesh="body_lod0",
        slot_label="Base color",
        slot_kind="base",
        semantic_type="material",
        semantic_subtype="albedo",
        reason="matched shader parameter",
    )

    assert item.text(1) == "Body"
    assert item.text(2) == "_base"
    assert item.text(3) == "body_base.dds"
    assert item.data(0, Qt.UserRole) == (2, 4)
    assert item.data(0, Qt.UserRole + 1) == "body_mesh"
    assert "Target slot: body_mesh" in item.toolTip(1)
    assert "Linked mesh: body_lod0" in item.toolTip(1)
    assert "Classified as: Base color" in item.toolTip(2)
    assert "Semantic: material/albedo" in item.toolTip(2)
    assert item.toolTip(3) == "character/texture/body_base.dds"
    assert item.toolTip(4) == "matched shader parameter"


def test_texture_override_item_creates_expected_empty_columns() -> None:
    item = texture_override_item()

    assert item.columnCount() == 7
    assert [item.text(column) for column in range(7)] == [""] * 7


def test_texture_item_for_row_returns_matching_top_level_item() -> None:
    tree = QTreeWidget()
    first_row: dict[str, object] = {"target_name": "first"}
    second_row: dict[str, object] = {"target_name": "second"}
    first_item = QTreeWidgetItem(["first"])
    second_item = QTreeWidgetItem(["second"])
    first_item.setData(0, Qt.UserRole + 1, first_row)
    second_item.setData(0, Qt.UserRole + 1, second_row)
    tree.addTopLevelItem(first_item)
    tree.addTopLevelItem(second_item)

    assert texture_item_for_row(tree, second_row) is second_item
    assert texture_item_for_row(tree, {"target_name": "missing"}) is None


def test_selected_texture_editor_state_handles_no_row() -> None:
    state = selected_texture_editor_state(
        None,
        source_choices=lambda _row: [("Keep original", "")],
        effective_source=lambda _row: "unused",
        source_summary=lambda _row: "unused",
        source_summary_tooltip=lambda _row: "unused",
    )

    assert state.has_row is False
    assert state.source_choices == (("Keep original", ""),)
    assert state.source_index == 0
    assert state.label_text == "Selected row"
    assert state.role_kind == "material"
    assert state.suggestion_available is False
    assert state.suggestion_tooltip == "No unapplied suggestion is available for the selected row."


def test_selected_texture_editor_state_selects_source_and_suggestion() -> None:
    row = {"slot_kind": "normal", "source_path": "manual.dds", "suggested_source": "suggested.dds"}

    state = selected_texture_editor_state(
        row,
        source_choices=lambda _row: [("Keep original", ""), ("Manual", "manual.dds")],
        effective_source=lambda _row: "manual.dds",
        source_summary=lambda _row: "Source Body",
        source_summary_tooltip=lambda _row: "Source Body long",
    )

    assert state.has_row is True
    assert state.source_index == 1
    assert state.label_text == "Affects: Source Body"
    assert state.label_tooltip == "Source Body long"
    assert state.role_kind == "normal"
    assert state.suggestion_available is True
    assert state.suggestion_tooltip == "Apply suggested source:\nsuggested.dds"


def test_selected_texture_editor_state_truncates_long_source_summary() -> None:
    row = {"slot_kind": "base", "suggested_source": "same.dds"}
    long_summary = "Source " + "very-long " * 10

    state = selected_texture_editor_state(
        row,
        source_choices=lambda _row: [("Same", "same.dds")],
        effective_source=lambda _row: "same.dds",
        source_summary=lambda _row: long_summary,
        source_summary_tooltip=lambda _row: long_summary,
    )

    assert state.label_text.endswith("...")
    assert len(state.label_text.removeprefix("Affects: ")) <= 58
    assert state.suggestion_available is False


def test_texture_details_state_counts_assigned_rows_for_selected_target() -> None:
    row = {"target_name": "Body"}
    rows_by_target = {
        "Body": [
            {"checked": True},
            {"checked": False},
            {"checked": True},
        ]
    }

    state = texture_details_state(
        row,
        current_target_name=lambda: "Fallback",
        texture_rows_by_target=rows_by_target,
        assigned=lambda row_state: bool(row_state.get("checked")),
    )

    assert state.target_name == "Body"
    assert state.assigned_count == 2
    assert state.target_row_count == 3


def test_texture_details_state_uses_current_target_without_row() -> None:
    state = texture_details_state(
        None,
        current_target_name=lambda: "Fallback",
        texture_rows_by_target={"Fallback": [{"checked": True}]},
        assigned=lambda row_state: bool(row_state.get("checked")),
    )

    assert state.target_name == "Fallback"
    assert state.assigned_count == 1
    assert state.target_row_count == 1


def test_suggested_texture_plan_rows_filters_by_suggestion_and_policy() -> None:
    allowed = {"target_name": "Body", "suggested_source": "body.dds", "guidance": "ok"}
    blocked = {"target_name": "Cape", "suggested_source": "cape.dds", "guidance": "blocked"}
    empty = {"target_name": "Hair", "suggested_source": ""}

    assert suggested_texture_plan_rows(
        [allowed, blocked, empty],
        can_apply=lambda _row, guidance: guidance == "ok",
    ) == ((allowed, "body.dds", "Apply"),)
    assert all_suggested_texture_plan_rows([allowed, blocked, empty]) == (
        (allowed, "body.dds", "Apply"),
        (blocked, "cape.dds", "Apply"),
    )


def test_texture_plan_action_states_route_empty_and_confirmable_suggestions() -> None:
    allowed = {"target_name": "Body", "suggested_source": "body.dds", "guidance": "ok"}
    blocked = {"target_name": "Cape", "suggested_source": "cape.dds", "guidance": "blocked"}
    empty = {"target_name": "Hair", "suggested_source": ""}

    suggested_state = suggested_texture_plan_action_state(
        [allowed, blocked, empty],
        can_apply=lambda _row, guidance: guidance == "ok",
    )
    assert suggested_state.rows == ((allowed, "body.dds", "Apply"),)
    assert suggested_state.message_key == ""
    assert suggested_state.should_refresh is True

    all_state = all_suggested_override_sources_action_state([allowed, blocked, empty])
    assert all_state.rows == (
        (allowed, "body.dds", "Apply"),
        (blocked, "cape.dds", "Apply"),
    )
    assert all_state.message_key == ""

    empty_state = all_suggested_override_sources_action_state([empty])
    assert empty_state.rows == ()
    assert empty_state.message_key == "no_suggestions"
    assert empty_state.should_refresh is False


def test_selected_material_texture_action_states_route_clear_and_file_selection() -> None:
    rows = [{"target_name": "Body"}]

    missing = selected_material_texture_clear_action_state(())
    assert missing.rows == ()
    assert missing.message_key == "select_route"

    clear = selected_material_texture_clear_action_state(rows)
    assert clear.rows == tuple(rows)
    assert clear.message_key == ""
    assert clear.should_refresh is True

    no_rows_file = selected_material_texture_file_action_state(
        (),
        "body.dds",
        is_file=lambda _path: True,
    )
    assert no_rows_file.message_key == "select_route"

    cancelled = selected_material_texture_file_action_state(
        rows,
        "",
        is_file=lambda _path: True,
    )
    assert cancelled.message_key == "cancelled"

    missing_file = selected_material_texture_file_action_state(
        rows,
        "missing.dds",
        is_file=lambda _path: False,
    )
    assert missing_file.message_key == "missing_file"

    selected = selected_material_texture_file_action_state(
        rows,
        "body.dds",
        is_file=lambda path: path.name == "body.dds",
    )
    assert selected.rows == tuple(rows)
    assert selected.message_key == ""
    assert selected.texture_path.endswith("body.dds")
    assert selected.should_refresh is True


def test_registered_texture_sources_action_state_tracks_refresh_and_rebuild_checkbox() -> None:
    none_added = registered_texture_sources_action_state(
        (),
        has_texture_sets=True,
        rebuild_sidecar_checked=False,
    )
    assert none_added.message_key == "none_added"
    assert none_added.should_refresh is False

    added_without_rebuild_needed = registered_texture_sources_action_state(
        ("body.dds",),
        has_texture_sets=False,
        rebuild_sidecar_checked=False,
    )
    assert added_without_rebuild_needed.message_key == ""
    assert added_without_rebuild_needed.should_refresh is True
    assert added_without_rebuild_needed.should_check_rebuild_sidecar is False

    added_with_rebuild_needed = registered_texture_sources_action_state(
        2,
        has_texture_sets=True,
        rebuild_sidecar_checked=False,
    )
    assert added_with_rebuild_needed.should_check_rebuild_sidecar is True


def test_selected_material_override_rows_matches_selected_sources_or_material() -> None:
    body = {"target_name": "Body", "source_indices": (1,)}
    cape = {"target_name": "Cape", "source_indices": (3,)}
    hair = {"target_name": "Hair", "source_indices": ()}

    assert selected_material_override_rows(
        [body, cape, hair],
        {"source_indices": ("3",), "material_name": ""},
        texture_row_current_source_indices=lambda row: tuple(row.get("source_indices", ())),
    ) == (cape,)
    assert selected_material_override_rows(
        [body, cape, hair],
        {"source_indices": (), "material_name": "hair"},
        texture_row_current_source_indices=lambda row: tuple(row.get("source_indices", ())),
    ) == (hair,)


def test_texture_set_for_selected_source_material_matches_key_name_then_source_index() -> None:
    body_set = SimpleNamespace(material_name="Body")
    cape_set = SimpleNamespace(material_name="Cape")
    texture_sets = {"body": body_set, "cape_key": cape_set}

    assert (
        texture_set_for_selected_source_material(
            {"material_name": "body"},
            texture_sets,
            texture_set_for_source_index=lambda _index, _sets: None,
        )
        is body_set
    )
    assert (
        texture_set_for_selected_source_material(
            {"material_name": "Cape"},
            texture_sets,
            texture_set_for_source_index=lambda _index, _sets: None,
        )
        is cape_set
    )
    assert (
        texture_set_for_selected_source_material(
            {"source_indices": ("2",)},
            texture_sets,
            texture_set_for_source_index=lambda index, _sets: cape_set if index == 2 else None,
        )
        is cape_set
    )


def test_selected_source_material_indices_falls_back_to_material_lookup() -> None:
    texture_set = SimpleNamespace(material_name="Cape")

    assert selected_source_material_indices(
        {"source_indices": ("3", "bad", -1)},
        texture_set,
        source_indices_for_material_name=lambda _name: (9,),
    ) == {-1, 3}
    assert selected_source_material_indices(
        {"source_indices": ()},
        texture_set,
        source_indices_for_material_name=lambda name: (7,) if name == "Cape" else (),
    ) == {7}


def test_selected_source_material_texture_plan_rows_filters_by_source_overlap_and_path() -> None:
    body_row = {"target_name": "Body", "slot_kind": "base", "source_indices": (1,)}
    cape_row = {"target_name": "Cape", "slot_kind": "normal", "source_indices": (2,)}
    missing_row = {"target_name": "Hair", "slot_kind": "height", "source_indices": (2,)}
    texture_set = SimpleNamespace(
        slots={
            "base": SimpleNamespace(source_path=Path("body.dds")),
            "normal": SimpleNamespace(source_path=Path("cape.dds")),
            "height": SimpleNamespace(source_path="not-a-path"),
        }
    )

    assert selected_source_material_texture_plan_rows(
        [body_row, cape_row, missing_row],
        texture_set,
        {2},
        texture_row_current_source_indices=lambda row: tuple(row.get("source_indices", ())),
        source_slot_for_texture_row=lambda texture_set_arg, row: texture_set_arg.slots.get(row.get("slot_kind")),
    ) == ((cape_row, str(Path("cape.dds")), "Apply"),)


def test_selected_source_material_texture_action_state_routes_missing_base_and_confirmable_rows() -> None:
    body_set = SimpleNamespace(
        material_name="Body",
        slots={"base": SimpleNamespace(source_path=Path("body.dds"))},
    )
    normal_set = SimpleNamespace(
        material_name="NormalOnly",
        slots={"normal": SimpleNamespace(source_path=Path("normal.dds"))},
    )
    body_row = {"target_name": "Body", "slot_kind": "base", "source_indices": (1,)}
    normal_row = {"target_name": "Normal", "slot_kind": "normal", "source_indices": (2,)}

    missing = selected_source_material_texture_action_state(
        {"material_name": "Missing"},
        {"body": body_set},
        [body_row],
        texture_set_for_source_index=lambda _index, _sets: None,
        source_indices_for_material_name=lambda _name: (),
        texture_row_current_source_indices=lambda row: tuple(row.get("source_indices", ())),
        source_slot_for_texture_row=lambda texture_set, row: texture_set.slots.get(row.get("slot_kind")),
    )
    assert missing.message_key == "missing_selection"
    assert missing.planned_rows == ()

    base_enabled = selected_source_material_texture_action_state(
        {"material_name": "Body"},
        {"body": body_set},
        [normal_row],
        texture_set_for_source_index=lambda _index, _sets: None,
        source_indices_for_material_name=lambda _name: (99,),
        texture_row_current_source_indices=lambda row: tuple(row.get("source_indices", ())),
        source_slot_for_texture_row=lambda texture_set, row: texture_set.slots.get(row.get("slot_kind")),
    )
    assert base_enabled.message_key == "base_enabled"
    assert base_enabled.enable_base_controls is True

    confirmable = selected_source_material_texture_action_state(
        {"source_indices": ("2",)},
        {"normal": normal_set},
        [normal_row],
        texture_set_for_source_index=lambda index, _sets: normal_set if index == 2 else None,
        source_indices_for_material_name=lambda _name: (),
        texture_row_current_source_indices=lambda row: tuple(row.get("source_indices", ())),
        source_slot_for_texture_row=lambda texture_set, row: texture_set.slots.get(row.get("slot_kind")),
    )
    assert confirmable.message_key == ""
    assert confirmable.material_name == "NormalOnly"
    assert confirmable.planned_rows == ((normal_row, str(Path("normal.dds")), "Apply"),)
    assert confirmable.saw_base is False
