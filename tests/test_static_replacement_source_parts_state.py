from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_source_parts_state import (
    part_inspector_loading_initial_state,
    selected_source_indices_state,
    selected_source_part_name_text,
    selected_source_part_target_text,
    source_part_added_export_blocker_message,
    source_part_added_export_blocker_title,
    source_part_added_import_message_lines,
    source_part_add_mesh_part_failed_title,
    source_part_added_mesh_part_status,
    source_part_adjustment_apply_state,
    source_part_adjustment_values_changed,
    source_part_append_display_override,
    source_part_append_file_route_state,
    source_part_append_index_state,
    source_part_append_imported_state,
    source_part_append_mesh_file_dialog_text,
    source_part_append_material_label,
    source_part_append_ordinal_suffix,
    source_part_append_presentations,
    source_part_append_role_hint_text,
    source_part_append_rollback_snapshot,
    source_part_append_texture_control_state,
    source_part_appended_work_area_fit_state,
    source_part_assignment_apply_state,
    source_part_assignment_button_state,
    source_part_assignment_dialog_text,
    source_part_assignment_highlight_state,
    source_part_assignment_import_state,
    source_part_assignment_primary_target,
    source_part_assignment_route_state,
    source_part_assignment_row_specs,
    source_part_assignment_summary_state,
    source_part_assignment_target_for_source,
    source_part_assignment_target_index,
    source_part_assignment_tree_headers,
    source_part_cancel_import_status,
    source_part_center_on_target_state,
    source_part_check_toggle_state,
    source_part_control_load_state,
    source_part_control_state,
    source_part_context_menu_text,
    source_part_copied_texture_action_state,
    source_part_copied_texture_controls_state,
    source_part_copied_texture_status_text,
    source_part_delete_index_map_state,
    source_part_delete_selection_state,
    source_part_delete_status_text,
    source_part_deleted_pending_reason,
    source_part_deleted_status,
    source_part_duplicate_available,
    source_part_duplicate_copy_suffix,
    source_part_duplicate_display_override,
    source_part_duplicate_output_route,
    source_part_duplicate_presentation_state,
    source_part_duplicate_role_override,
    source_part_duplicate_route_state,
    source_part_duplicate_status,
    source_part_duplicate_undo_label,
    source_part_edit_undo_label,
    source_part_fit_size_state,
    source_part_format_mesh_density_counts,
    source_part_glow_color_action_state,
    source_part_glow_color_controls_state,
    source_part_glow_color_button_text,
    source_part_glow_emissive_update_states,
    source_part_glow_rgb,
    source_part_group_routing_overflow_message,
    source_part_group_routing_text,
    source_part_group_initial_target_counts,
    source_part_group_items,
    source_part_material_groups,
    source_part_group_source_texts,
    source_part_group_target_score,
    source_part_high_density_import_action,
    source_part_high_density_reduction_limits,
    source_part_high_density_prompt_state,
    source_part_mapping_indices_for_target,
    source_part_nudge_delta,
    source_part_normalized_target_indices,
    source_part_output_action_state,
    source_part_pair_action_available,
    source_part_pair_action_state,
    source_part_high_density_import_message,
    source_part_inspector_control_text,
    source_part_include_exclude_pending_reason,
    source_part_map_to_target_state,
    source_part_multipart_import_action,
    source_part_multipart_import_message,
    source_part_multipart_import_state,
    source_part_multipart_prompt_state,
    source_part_properties_control_text,
    source_part_properties_inspector_state,
    source_part_properties_label_html,
    source_part_material_properties_text,
    source_part_properties_output_text,
    source_part_source_properties_dds_text,
    source_part_source_properties_warning,
    source_part_target_properties_warning,
    source_part_reduction_result_message,
    source_part_role_action_state,
    source_part_role_export_flush_states,
    source_part_role_override_state,
    source_part_routing_preview_action,
    source_part_scene_import_appendable_part_count,
    source_part_scene_import_is_high_density,
    source_part_scene_import_prompt_text,
    source_part_assign_groups_to_targets,
    source_part_assign_material_groups_to_targets,
    source_part_selected_target_index,
    source_part_source_combo_selection_state,
    source_part_target_button_state,
    source_part_target_combo_selection_state,
    source_part_selection_context_label_text,
    source_part_selection_context_state,
    source_part_selection_context_tooltip,
    source_part_selection_added_texture_context_text,
    source_part_selection_added_texture_text,
    source_part_selection_texture_fallback,
    source_part_selection_texture_row_context_text,
    source_part_selection_texture_row_text,
    source_part_should_be_preview_only_after_unmap,
    source_part_target_choice,
    source_part_target_sources_initial_state,
    source_part_transform_control_text,
    source_part_unmap_target_states,
    source_part_unmapped_indices_for_target,
    source_part_unsupported_mesh_part_message,
    source_part_valid_indices,
    source_parts_action_control_text,
    source_parts_apply_initial_state,
    source_parts_apply_pending_presentation,
    source_parts_clear_apply_pending,
    source_parts_clear_apply_pending_presentation,
    source_parts_mark_apply_pending,
    source_parts_mark_preview_rebuild_pending,
    source_parts_preview_rebuild_pending_presentation,
    source_parts_preview_rebuild_pending,
    source_parts_selection_pending_presentation,
)


def test_part_inspector_loading_initial_state_preserves_default() -> None:
    assert part_inspector_loading_initial_state() == {"active": False}


def test_selected_source_indices_state_deduplicates_and_uses_fallback() -> None:
    assert selected_source_indices_state(
        ("1", "bad", "1", "3"),
        source_index_from_item=lambda item: int(item) if str(item).isdigit() else -1,
        fallback_source_index=9,
        include_fallback=True,
    ) == (1, 3)
    assert selected_source_indices_state(
        (),
        source_index_from_item=lambda _item: -1,
        fallback_source_index="4",
        include_fallback=True,
    ) == (4,)
    assert selected_source_indices_state(
        (),
        source_index_from_item=lambda _item: -1,
        fallback_source_index=4,
        include_fallback=False,
    ) == ()


def test_source_part_control_state_tracks_enablement_from_source_target_and_mapping() -> None:
    state = source_part_control_state(
        source_index=2,
        has_replacement_sources=True,
        target_choice=4,
        mapped_target_indices=(4,),
        selected_target_index=4,
    )

    assert state.has_source is True
    assert state.source_combo_enabled is True
    assert state.target_choice_available is True
    assert state.mapped_target_available is True
    assert state.fit_part_enabled is True

    empty_state = source_part_control_state(
        source_index=-1,
        has_replacement_sources=False,
        target_choice=4,
        mapped_target_indices=(4,),
        selected_target_index=4,
    )
    assert empty_state.has_source is False
    assert empty_state.source_combo_enabled is False
    assert empty_state.target_choice_available is False
    assert empty_state.mapped_target_available is False
    assert empty_state.fit_part_enabled is False


def test_source_part_target_choice_prefers_selected_mapped_then_first_mapping() -> None:
    assert source_part_target_choice(4, (2, 4)) == 4
    assert source_part_target_choice(9, (2, 4)) == 2
    assert source_part_target_choice(3, ()) == 3
    assert source_part_target_choice("bad", ()) == -1
    assert source_part_target_choice(5, ("bad", 5)) == 5


def test_source_part_selected_target_index_normalizes_combo_data() -> None:
    assert source_part_selected_target_index("7") == 7
    assert source_part_selected_target_index(0) == 0
    assert source_part_selected_target_index(None) == -1
    assert source_part_selected_target_index("bad") == -1


def test_source_part_source_combo_selection_state_tracks_existing_source() -> None:
    state = source_part_source_combo_selection_state("4", available_source_indices=(1, "bad", 4))
    assert state.source_index == 4
    assert state.select_existing_source is True
    assert state.clear_selection is False

    missing_state = source_part_source_combo_selection_state("9", available_source_indices=(1, 4))
    assert missing_state.source_index == 9
    assert missing_state.select_existing_source is False
    assert missing_state.clear_selection is True

    invalid_state = source_part_source_combo_selection_state("bad", available_source_indices=(1, 4))
    assert invalid_state.source_index == -1
    assert invalid_state.clear_selection is True


def test_source_part_control_load_state_resets_invalid_selection_to_placeholders() -> None:
    state = source_part_control_load_state(
        source_index=99,
        source_count=2,
        has_replacement_sources=True,
        current_target_choice=4,
        mapped_target_indices=(4,),
        selected_target_index=4,
        name_placeholder="Select source",
        target_placeholder="No target",
        adjustment=SimpleNamespace(enabled=False),
    )

    assert state.has_source is False
    assert state.control_state.has_source is False
    assert state.control_state.source_combo_enabled is True
    assert state.control_state.target_choice_available is False
    assert state.name_text == "Select source"
    assert state.target_text == "No target"
    assert state.source_combo_value == -1
    assert state.enabled_checked is True
    assert state.role_value == ""
    assert state.target_choice == -1
    assert state.transform_values == (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0)


def test_source_part_control_load_state_builds_selected_part_values() -> None:
    adjustment = SimpleNamespace(
        enabled=False,
        offset_xyz=("1.5", "bad", 3),
        rotate_xyz_degrees=(10, 20, 30),
        scale_xyz=(2, None, "bad"),
        uniform_scale="4.5",
    )

    state = source_part_control_load_state(
        source_index="2",
        source_count=4,
        has_replacement_sources=True,
        current_target_choice=9,
        mapped_target_indices=(1, "bad", 7),
        selected_target_index=7,
        name_placeholder="Select source",
        target_placeholder="No target",
        source_label="Body_LOD0",
        target_summary="Target A, Target B",
        role_value="body",
        multi_selected_count=1234,
        adjustment=adjustment,
    )

    assert state.has_source is True
    assert state.control_state.has_source is True
    assert state.control_state.source_combo_enabled is True
    assert state.control_state.target_choice_available is True
    assert state.control_state.mapped_target_available is True
    assert state.control_state.fit_part_enabled is True
    assert state.name_text == "1,234 parts selected; primary 2: Body_LOD0"
    assert state.target_text == (
        "Transform scope is explicit source selection. Primary mapped target(s): Target A, Target B"
    )
    assert state.source_combo_value == 2
    assert state.enabled_checked is False
    assert state.role_value == "body"
    assert state.target_choice == 7
    assert state.transform_values == (1.5, 0.0, 3.0, 10.0, 20.0, 30.0, 2.0, 1.0, 1.0, 4.5)


def test_source_part_copied_texture_controls_state_tracks_visibility_and_actions() -> None:
    disabled_state = source_part_copied_texture_controls_state(has_rows=True, disabled=True)
    assert disabled_state.visible is True
    assert disabled_state.use_copied_enabled is True
    assert disabled_state.use_route_enabled is False
    assert disabled_state.remove_enabled is True

    route_state = source_part_copied_texture_controls_state(has_rows=True, disabled=False)
    assert route_state.use_copied_enabled is False
    assert route_state.use_route_enabled is True

    empty_state = source_part_copied_texture_controls_state(has_rows=False, disabled=True)
    assert empty_state.visible is False
    assert empty_state.use_copied_enabled is False
    assert empty_state.use_route_enabled is False
    assert empty_state.remove_enabled is False


def test_source_part_copied_texture_action_state_routes_selected_source_actions() -> None:
    copied_state = source_part_copied_texture_action_state(
        action="use_copied",
        source_index="4",
        copied_source_indices=(2, "bad", 4),
    )
    assert copied_state.available is True
    assert copied_state.source_index == 4
    assert copied_state.undo_label == "Use copied original texture"
    assert copied_state.disable_copied_texture is False
    assert copied_state.remove_intent is False
    assert copied_state.mark_dirty is True
    assert copied_state.queue_preview is True

    route_state = source_part_copied_texture_action_state(
        action="use_route",
        source_index=4,
        copied_source_indices=(4,),
    )
    assert route_state.undo_label == "Use route source texture"
    assert route_state.disable_copied_texture is True
    assert route_state.remove_intent is False

    remove_state = source_part_copied_texture_action_state(
        action="remove",
        source_index=4,
        copied_source_indices=(4,),
    )
    assert remove_state.undo_label == "Remove copied source texture"
    assert remove_state.remove_intent is True

    unavailable_state = source_part_copied_texture_action_state(
        action="use_copied",
        source_index=9,
        copied_source_indices=(4,),
    )
    assert unavailable_state.available is False
    assert unavailable_state.source_index == -1
    assert unavailable_state.mark_dirty is False


def test_source_part_normalized_target_indices_keeps_selected_source_first() -> None:
    assert source_part_normalized_target_indices(5, (2, 5, "bad", 2, -1, 8)) == (5, 2, 8)
    assert source_part_normalized_target_indices("bad", (2, "3", 2)) == (2, 3)


def test_source_part_check_toggle_state_routes_source_tree_checkbox() -> None:
    state = source_part_check_toggle_state(
        source_index="4",
        column=0,
        guard_active=False,
        checked=True,
        selected_source_index=4,
    )
    assert state.available is True
    assert state.source_index == 4
    assert state.enabled is True
    assert state.undo_action == "toggle"
    assert state.refresh_selected_controls is True
    assert state.apply_pending is False

    guarded_state = source_part_check_toggle_state(
        source_index=4,
        column=0,
        guard_active=True,
        checked=False,
        selected_source_index=4,
    )
    assert guarded_state.available is False
    assert guarded_state.apply_pending is False

    wrong_column_state = source_part_check_toggle_state(
        source_index=4,
        column=1,
        guard_active=False,
        checked=False,
        selected_source_index=4,
    )
    assert wrong_column_state.available is False

    unselected_state = source_part_check_toggle_state(
        source_index=4,
        column=0,
        guard_active=False,
        checked=False,
        selected_source_index=9,
    )
    assert unselected_state.available is True
    assert unselected_state.enabled is False
    assert unselected_state.refresh_selected_controls is False


def test_source_part_output_action_state_routes_reset_and_remove_controls() -> None:
    reset_state = source_part_output_action_state(
        action="reset",
        source_index=5,
        selected_source_indices=(2, 5, "bad", 8),
    )
    assert reset_state.available is True
    assert reset_state.target_indices == (5, 2, 8)
    assert reset_state.source_checked is True
    assert reset_state.part_enabled_checked is True
    assert reset_state.undo_action == "reset"
    assert reset_state.apply_pending is False

    remove_state = source_part_output_action_state(
        action="remove",
        source_index=5,
        selected_source_indices=(2, 5, 8),
    )
    assert remove_state.available is True
    assert remove_state.target_indices == (5, 2, 8)
    assert remove_state.source_checked is False
    assert remove_state.part_enabled_checked is False
    assert remove_state.undo_action == "remove"
    assert remove_state.apply_pending is False

    unavailable_state = source_part_output_action_state(
        action="remove",
        source_index=-1,
        selected_source_indices=(),
    )
    assert unavailable_state.available is False
    assert unavailable_state.target_indices == ()


def test_source_part_target_button_state_tracks_selected_target_and_mapping() -> None:
    state = source_part_target_button_state(
        source_index=2,
        target_index=4,
        mapped_target_indices=(4,),
    )
    assert state.replace_enabled is True
    assert state.add_enabled is True
    assert state.remove_enabled is True

    no_target_state = source_part_target_button_state(
        source_index=2,
        target_index=-1,
        mapped_target_indices=(),
    )
    assert no_target_state.replace_enabled is False
    assert no_target_state.add_enabled is False
    assert no_target_state.remove_enabled is False

    no_source_state = source_part_target_button_state(
        source_index=-1,
        target_index=4,
        mapped_target_indices=(4,),
    )
    assert no_source_state.replace_enabled is False
    assert no_source_state.add_enabled is False
    assert no_source_state.remove_enabled is False


def test_source_part_target_combo_selection_state_combines_target_and_buttons() -> None:
    state = source_part_target_combo_selection_state("7", source_index=2, mapped_target_indices=("bad", 7))
    assert state.target_index == 7
    assert state.button_state.replace_enabled is True
    assert state.button_state.add_enabled is True
    assert state.button_state.remove_enabled is True

    invalid_state = source_part_target_combo_selection_state("bad", source_index=2, mapped_target_indices=())
    assert invalid_state.target_index == -1
    assert invalid_state.button_state.replace_enabled is False
    assert invalid_state.button_state.remove_enabled is False


def test_source_part_adjustment_values_changed_compares_transform_fields() -> None:
    adjustment = SimpleNamespace(
        enabled=True,
        offset_xyz=(1.0, 2.0, 3.0),
        rotate_xyz_degrees=(4.0, 5.0, 6.0),
        scale_xyz=(1.0, 1.5, 2.0),
        uniform_scale=0.75,
    )

    assert (
        source_part_adjustment_values_changed(
            {2: adjustment},
            (2,),
            enabled=True,
            offset_xyz=(1.0, 2.0, 3.0),
            rotate_xyz_degrees=(4.0, 5.0, 6.0),
            scale_xyz=(1.0, 1.5, 2.0),
            uniform_scale=0.75,
            default_adjustment=lambda index: SimpleNamespace(
                enabled=True,
                offset_xyz=(0.0, 0.0, 0.0),
                rotate_xyz_degrees=(0.0, 0.0, 0.0),
                scale_xyz=(1.0, 1.0, 1.0),
                uniform_scale=1.0,
            ),
        )
        is False
    )

    assert (
        source_part_adjustment_values_changed(
            {2: adjustment},
            (2,),
            enabled=False,
            offset_xyz=(1.0, 2.0, 3.0),
            rotate_xyz_degrees=(4.0, 5.0, 6.0),
            scale_xyz=(1.0, 1.5, 2.0),
            uniform_scale=0.75,
            default_adjustment=lambda index: SimpleNamespace(
                enabled=True,
                offset_xyz=(0.0, 0.0, 0.0),
                rotate_xyz_degrees=(0.0, 0.0, 0.0),
                scale_xyz=(1.0, 1.0, 1.0),
                uniform_scale=1.0,
            ),
        )
        is True
    )


def test_source_part_adjustment_apply_state_normalizes_controls_and_detects_changes() -> None:
    adjustments = {
        2: SimpleNamespace(
            enabled=True,
            offset_xyz=(0.0, 0.0, 0.0),
            rotate_xyz_degrees=(0.0, 0.0, 0.0),
            scale_xyz=(1.0, 1.0, 1.0),
            uniform_scale=1.0,
        ),
        5: SimpleNamespace(
            enabled=False,
            offset_xyz=(0.0, 0.0, 0.0),
            rotate_xyz_degrees=(0.0, 0.0, 0.0),
            scale_xyz=(1.0, 1.0, 1.0),
            uniform_scale=1.0,
        ),
    }
    default_adjustment = lambda _index: SimpleNamespace(
        enabled=True,
        offset_xyz=(0.0, 0.0, 0.0),
        rotate_xyz_degrees=(0.0, 0.0, 0.0),
        scale_xyz=(1.0, 1.0, 1.0),
        uniform_scale=1.0,
    )

    state = source_part_adjustment_apply_state(
        adjustments,
        source_index="2",
        selected_source_indices=(5, "bad", 2),
        enabled=False,
        offset_xyz=("1.5", "bad", 3),
        rotate_xyz_degrees=(10, 20, 30),
        scale_xyz=(2, None, "bad"),
        uniform_scale="4.5",
        default_adjustment=default_adjustment,
    )

    assert state.available is True
    assert state.changed is True
    assert state.enabled_changed is True
    assert state.target_indices == (2, 5)
    assert state.enabled is False
    assert state.offset_xyz == (1.5, 0.0, 3.0)
    assert state.rotate_xyz_degrees == (10.0, 20.0, 30.0)
    assert state.scale_xyz == (2.0, 1.0, 1.0)
    assert state.uniform_scale == 4.5

    invalid_state = source_part_adjustment_apply_state(
        adjustments,
        source_index="bad",
        selected_source_indices=(5,),
        enabled=True,
        offset_xyz=(),
        rotate_xyz_degrees=(),
        scale_xyz=(),
        uniform_scale="bad",
        default_adjustment=default_adjustment,
    )
    assert invalid_state.available is False
    assert invalid_state.changed is False
    assert invalid_state.target_indices == ()


def test_source_part_glow_emissive_update_states_updates_only_changed_glow_roles() -> None:
    adjustments = {
        1: SimpleNamespace(material_role="glow", emissive_color_rgb=(1, 2, 3)),
        2: SimpleNamespace(material_role="geometry", emissive_color_rgb=(9, 9, 9)),
        3: SimpleNamespace(material_role="glow", emissive_color_rgb=(255, 0, 0)),
        -1: SimpleNamespace(material_role="glow", emissive_color_rgb=()),
    }

    updates = source_part_glow_emissive_update_states(
        adjustments,
        rgb=(300, -1, "bad"),
        use_color=True,
    )

    assert tuple((state.source_index, state.emissive_color_rgb) for state in updates) == (
        (1, (255, 0, 0)),
    )

    clear_updates = source_part_glow_emissive_update_states(
        adjustments,
        rgb=(255, 255, 255),
        use_color=False,
    )
    assert tuple((state.source_index, state.emissive_color_rgb) for state in clear_updates) == (
        (1, ()),
        (3, ()),
    )


def test_source_part_role_override_state_normalizes_role_and_glow_rgb() -> None:
    glow_state = source_part_role_override_state(
        source_index="3",
        role_value=" glow ",
        glow_color_checked=True,
        glow_rgb=(300, -2, "bad"),
    )
    assert glow_state.source_index == 3
    assert glow_state.normalized_role == "glow"
    assert glow_state.store_override
    assert glow_state.emissive_color_rgb == (255, 0, 0)

    geometry_state = source_part_role_override_state(
        source_index=4,
        role_value=" Geometry ",
        glow_color_checked=True,
        glow_rgb=(1, 2, 3),
    )
    assert geometry_state.normalized_role == "Geometry"
    assert geometry_state.emissive_color_rgb == ()

    empty_state = source_part_role_override_state(
        source_index=4,
        role_value="",
        glow_color_checked=True,
        glow_rgb=(1, 2, 3),
    )
    assert not empty_state.store_override
    assert empty_state.emissive_color_rgb == ()

    invalid_state = source_part_role_override_state(
        source_index="bad",
        role_value="glow",
        glow_color_checked=True,
        glow_rgb=(1, 2, 3),
    )
    assert invalid_state.source_index == -1
    assert invalid_state.normalized_role == ""


def test_source_part_role_action_state_normalizes_refresh_contract() -> None:
    state = source_part_role_action_state(
        source_index="3",
        role_value=" glow ",
        undo_label="Set role",
        refresh_reason="role changed",
    )

    assert state.available is True
    assert state.source_index == 3
    assert state.normalized_role == "glow"
    assert state.undo_label == "Set role"
    assert state.refresh_plan is True
    assert state.force_plan is True
    assert state.refresh_preview is True
    assert state.refresh_reason == "role changed"

    invalid_state = source_part_role_action_state(
        source_index="bad",
        role_value="glow",
        undo_label="Set role",
    )
    assert invalid_state.available is False
    assert invalid_state.source_index == -1


def test_source_part_glow_color_action_state_preserves_refresh_contract() -> None:
    state = source_part_glow_color_action_state()

    assert state.undo_action == "glow"
    assert state.refresh_plan is False
    assert state.force_plan is False
    assert state.refresh_preview is True
    assert state.refresh_reason == "source glow color change"


def test_source_part_role_export_flush_states_detect_role_and_emissive_changes() -> None:
    adjustments = {
        1: SimpleNamespace(material_role="", emissive_color_rgb=(1, 2, 3)),
        2: SimpleNamespace(material_role="glow", emissive_color_rgb=(4, 5, 6)),
        3: SimpleNamespace(material_role="cloth", emissive_color_rgb=()),
    }

    states = source_part_role_export_flush_states(
        {1: "cloth", 2: "glow", 3: "cloth", "bad": "glow"},
        adjustments,
        default_adjustment=lambda index: SimpleNamespace(material_role="", emissive_color_rgb=()),
    )

    assert tuple(
        (
            state.source_index,
            state.normalized_role,
            state.material_role_changed,
            state.clear_emissive_color,
            state.changed,
        )
        for state in states
    ) == (
        (1, "cloth", True, True, True),
        (2, "glow", False, False, False),
        (3, "cloth", False, False, False),
    )


def test_source_part_mapping_indices_for_target_replaces_or_appends_once() -> None:
    assert source_part_mapping_indices_for_target((1, 2), source_index=5, replace=True) == (5,)
    assert source_part_mapping_indices_for_target((1, 2), source_index=2, replace=False) == (1, 2)
    assert source_part_mapping_indices_for_target((1, 2), source_index=5, replace=False) == (1, 2, 5)
    assert source_part_mapping_indices_for_target((1, "bad", 1), source_index=3, replace=False) == (1, 3)
    assert source_part_mapping_indices_for_target((1, "bad", 1), source_index="bad", replace=False) == (1,)


def test_source_part_map_to_target_state_normalizes_route_request() -> None:
    replace_state = source_part_map_to_target_state(
        source_index="5",
        target_index="8",
        current_indices=(1, 2),
        replace=True,
    )
    assert replace_state.available is True
    assert replace_state.source_index == 5
    assert replace_state.target_index == 8
    assert replace_state.source_indices == (5,)

    append_state = source_part_map_to_target_state(
        source_index=5,
        target_index=8,
        current_indices=(1, "bad", 5),
        replace=False,
    )
    assert append_state.source_indices == (1, 5)

    invalid_state = source_part_map_to_target_state(
        source_index=-1,
        target_index=8,
        current_indices=(1,),
        replace=False,
    )
    assert invalid_state.available is False
    assert invalid_state.source_indices == ()


def test_source_part_preview_only_after_unmap_requires_appended_and_unmapped() -> None:
    assert (
        source_part_should_be_preview_only_after_unmap(
            source_index=4,
            appended_source_indices=(4, 5),
            mapped_source_indices=(5,),
        )
        is True
    )
    assert (
        source_part_should_be_preview_only_after_unmap(
            source_index=4,
            appended_source_indices=(4, 5),
            mapped_source_indices=(4,),
        )
        is False
    )
    assert (
        source_part_should_be_preview_only_after_unmap(
            source_index=2,
            appended_source_indices=(4, 5),
            mapped_source_indices=(),
        )
        is False
    )
    assert (
        source_part_should_be_preview_only_after_unmap(
            source_index=4,
            appended_source_indices=(4, "bad"),
            mapped_source_indices=("bad",),
        )
        is True
    )


def test_source_part_unmapped_indices_for_target_removes_selected_source_once() -> None:
    assert source_part_unmapped_indices_for_target((1, 2, 3), source_index=2) == (1, 3)
    assert source_part_unmapped_indices_for_target((1, "bad", 1, 3), source_index=2) == (1, 3)
    assert source_part_unmapped_indices_for_target((1, 2), source_index="bad") == (1, 2)


def test_source_part_unmap_target_states_preserve_target_order_and_undo_flag() -> None:
    states = source_part_unmap_target_states(
        source_index=2,
        target_indices=(4, 8, 9),
        target_source_indices={
            4: (1, 2, 3),
            9: (2, 5, 5),
        },
    )

    assert [(state.target_index, state.remaining_source_indices, state.push_undo) for state in states] == [
        (4, (1, 3), True),
        (9, (5,), False),
    ]
    assert source_part_unmap_target_states(
        source_index=-1,
        target_indices=(4,),
        target_source_indices={4: (1, 2)},
    ) == ()


def test_source_part_duplicate_output_route_follows_source_output_membership() -> None:
    assert (
        source_part_duplicate_output_route(
            source_index=2,
            mapped_target_indices=(1,),
            independent_output_source_indices=(2,),
            preview_only_source_indices=(),
        )
        == "independent"
    )
    assert (
        source_part_duplicate_output_route(
            source_index=2,
            mapped_target_indices=(1,),
            independent_output_source_indices=(),
            preview_only_source_indices=(2,),
        )
        == "preview"
    )
    assert (
        source_part_duplicate_output_route(
            source_index=2,
            mapped_target_indices=(),
            independent_output_source_indices=(),
            preview_only_source_indices=(),
        )
        == "preview"
    )
    assert (
        source_part_duplicate_output_route(
            source_index=2,
            mapped_target_indices=(1,),
            independent_output_source_indices=(),
            preview_only_source_indices=(),
        )
        == ""
    )


def test_source_part_pair_action_available_checks_source_and_target_bounds() -> None:
    assert (
        source_part_pair_action_available(
            source_index=1,
            target_index=2,
            source_count=3,
            target_count=4,
        )
        is True
    )
    assert (
        source_part_pair_action_available(
            source_index=3,
            target_index=2,
            source_count=3,
            target_count=4,
        )
        is False
    )
    assert (
        source_part_pair_action_available(
            source_index=1,
            target_index=-1,
            source_count=3,
            target_count=4,
        )
        is False
    )


def test_source_part_pair_action_state_normalizes_valid_indices() -> None:
    valid_state = source_part_pair_action_state(
        source_index="1",
        target_index="2",
        source_count=3,
        target_count=4,
    )
    assert valid_state.available is True
    assert valid_state.source_index == 1
    assert valid_state.target_index == 2

    invalid_state = source_part_pair_action_state(
        source_index=8,
        target_index=2,
        source_count=3,
        target_count=4,
    )
    assert invalid_state.available is False
    assert invalid_state.source_index == -1
    assert invalid_state.target_index == -1


def test_source_part_valid_indices_filters_and_deduplicates_by_source_count() -> None:
    assert source_part_valid_indices((2, "bad", 2, -1, 3), source_count=3) == (2,)
    assert source_part_valid_indices((0, 1), source_count="bad") == ()


def test_source_part_appended_work_area_fit_state_preserves_fit_note() -> None:
    mesh = SimpleNamespace(
        submeshes=(
            SimpleNamespace(vertices=((100.0, 0.0, 0.0), (200.0, 0.0, 0.0))),
            SimpleNamespace(vertices=((0.0, 0.0, 0.0),)),
        )
    )

    state = source_part_appended_work_area_fit_state(
        source_indices=(0, "bad", 0, 9),
        source_count=2,
        replacement_mesh=mesh,
        reference_vertices=((0.0, 0.0, 0.0), (10.0, 0.0, 0.0)),
    )

    assert state.source_indices == (0,)
    assert state.should_apply
    assert state.fit is not None
    assert state.placement_note == "centered in the current asset work area, scaled 0.115x for preview control"

    no_fit_state = source_part_appended_work_area_fit_state(
        source_indices=(1,),
        source_count=2,
        replacement_mesh=mesh,
        reference_vertices=((0.0, 0.0, 0.0),),
    )
    assert no_fit_state.source_indices == (1,)
    assert not no_fit_state.should_apply
    assert no_fit_state.placement_note == ""


def test_source_part_fit_and_center_states_preserve_geometry_actions() -> None:
    replacement_mesh = SimpleNamespace(
        submeshes=(
            SimpleNamespace(vertices=((0.0, 0.0, 0.0), (2.0, 0.0, 0.0))),
        )
    )
    original_mesh = SimpleNamespace(
        submeshes=(
            SimpleNamespace(vertices=((10.0, 0.0, 0.0), (14.0, 0.0, 0.0))),
        )
    )

    fit_state = source_part_fit_size_state(
        source_index=0,
        target_index=0,
        replacement_mesh=replacement_mesh,
        original_mesh=original_mesh,
    )
    center_state = source_part_center_on_target_state(
        source_index=0,
        target_index=0,
        replacement_mesh=replacement_mesh,
        original_mesh=original_mesh,
    )

    assert fit_state.source_index == 0
    assert fit_state.target_index == 0
    assert fit_state.uniform_scale == 2.0
    assert fit_state.available
    assert center_state.source_index == 0
    assert center_state.target_index == 0
    assert center_state.offset == (11.0, 0.0, 0.0)
    assert center_state.available

    invalid_state = source_part_fit_size_state(
        source_index=3,
        target_index=0,
        replacement_mesh=replacement_mesh,
        original_mesh=original_mesh,
    )
    assert invalid_state.source_index == -1
    assert not invalid_state.available


def test_source_part_nudge_delta_maps_axis_to_single_component() -> None:
    assert source_part_nudge_delta("x", 0.25, -2) == (-0.5, 0.0, 0.0)
    assert source_part_nudge_delta("Y", 0.25, 2) == (0.0, 0.5, 0.0)
    assert source_part_nudge_delta("z", 0.25, 2) == (0.0, 0.0, 0.5)
    assert source_part_nudge_delta("bad", 0.25, 2) == (0.0, 0.0, 0.0)


def test_source_part_target_sources_initial_state_preserves_empty_lists() -> None:
    assert source_part_target_sources_initial_state(3) == {0: [], 1: [], 2: []}
    assert source_part_target_sources_initial_state(-1) == {}


def test_source_part_group_target_score_weights_token_history_and_assigned_penalty() -> None:
    def _tokens(value: str) -> set[str]:
        return {part for part in value.lower().split() if part}

    score = source_part_group_target_score(
        group_label="body armor",
        source_texts=("body metal", "cape cloth"),
        target_index=2,
        target_label="body metal target",
        assigned_targets=set(),
        source_initial_targets={"body armor": {2: 3}},
        semantic_tokens=_tokens,
    )
    assigned_score = source_part_group_target_score(
        group_label="body armor",
        source_texts=("body metal", "cape cloth"),
        target_index=2,
        target_label="body metal target",
        assigned_targets={2},
        source_initial_targets={"body armor": {2: 3}},
        semantic_tokens=_tokens,
    )

    assert score == 14 + min(8.0, len("body") * 0.75) + 135 + 16
    assert assigned_score == score - 10000.0


def test_source_part_group_initial_target_counts_groups_suggested_mapping_targets() -> None:
    mappings = (
        SimpleNamespace(target_submesh_index=1, source_submesh_indices=(2, 3)),
        SimpleNamespace(target_submesh_index="bad", source_submesh_indices=(2,)),
    )

    counts = source_part_group_initial_target_counts(
        mappings,
        lambda source_index: "body" if source_index == 2 else "cape",
    )

    assert dict(counts["body"]) == {1: 1, -1: 1}
    assert dict(counts["cape"]) == {1: 1}


def test_source_part_material_groups_skips_markers_disabled_and_excluded_sources() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(name="Body", material="MatBody", faces=(1, 2, 3)),
            SimpleNamespace(name="Marker", material="", faces=(1,), marker=True),
            SimpleNamespace(name="Cape", material="MatCape", faces=(1, 2)),
            SimpleNamespace(name="Disabled", material="MatDisabled", faces=(1,)),
        ]
    )
    adjustments = {3: SimpleNamespace(enabled=False)}

    groups, face_counts = source_part_material_groups(
        mesh,
        adjustments,
        source_material_group_label=lambda source_index: f"group-{source_index}",
        source_group_label_or_fallback=lambda source_index, label: label or f"source {source_index}",
        is_marker_source=lambda source: bool(getattr(source, "marker", False)),
        excluded_source_indices=(2,),
    )

    assert groups == {"group-0": [0]}
    assert face_counts == {"group-0": 3}


def test_source_part_group_items_orders_by_face_count_then_part_count() -> None:
    items = source_part_group_items(
        {"low": [1, 2, 3], "high": [4], "wide": [5, 6]},
        {"low": 2, "high": 10, "wide": 10},
    )

    assert items == (("wide", (5, 6)), ("high", (4,)), ("low", (1, 2, 3)))


def test_source_part_group_source_texts_reads_valid_source_labels() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(name="Body", material="Skin"),
            SimpleNamespace(name="Cape", material="Cloth"),
        ]
    )

    assert source_part_group_source_texts(mesh, (1, 9, "bad", 0)) == ("Cape Cloth", "Body Skin")


def test_source_part_assign_groups_to_targets_prefers_free_targets_then_overflows() -> None:
    assigned_targets: set[int] = set()

    def _score(group_label: str, _source_indices: Sequence[int], target_index: int) -> float:
        base = {"body": {0: 10.0, 1: 1.0}, "cape": {0: 2.0, 1: 9.0}, "extra": {0: 8.0, 1: 1.0}}
        penalty = -10000.0 if target_index in assigned_targets else 0.0
        return base[group_label][target_index] + penalty

    target_sources, overflow = source_part_assign_groups_to_targets(
        (("body", (1,)), ("cape", (2,)), ("extra", (3,))),
        target_count=2,
        score_group_for_target=_score,
        assigned_targets=assigned_targets,
    )

    assert target_sources == {0: [1, 3], 1: [2]}
    assert overflow == ("extra",)
    assert assigned_targets == {0, 1}


def test_source_part_assign_material_groups_to_targets_scores_mesh_labels_and_overflow() -> None:
    original_mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(name="Body", material="Skin"),
            SimpleNamespace(name="Cape", material="Cloth"),
        ]
    )
    replacement_mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(name="Body", material="Skin"),
            SimpleNamespace(name="Cape", material="Cloth"),
            SimpleNamespace(name="Extra", material="Metal"),
        ]
    )

    target_sources, overflow = source_part_assign_material_groups_to_targets(
        (("body", (0,)), ("cape", (1,)), ("extra", (2,))),
        target_count=2,
        original_mesh=original_mesh,
        replacement_mesh=replacement_mesh,
        target_display_name=lambda _index, target: getattr(target, "name", ""),
        source_initial_targets={},
        semantic_tokens=lambda value: {part for part in str(value).lower().split() if part},
    )

    assert target_sources == {0: [0, 2], 1: [1]}
    assert overflow == ("extra",)


def test_source_parts_apply_initial_state_preserves_flags() -> None:
    assert source_parts_apply_initial_state() == {
        "pending": False,
        "reason": "",
        "preview_rebuild_pending": False,
        "preview_rebuild_reason": "",
    }


def test_source_parts_action_control_text_preserves_copy_and_object_names() -> None:
    text = source_parts_action_control_text()

    assert text["delete_button"] == "Delete Selected"
    assert text["apply_button"] == "Apply"
    assert text["delete_object"] == "MeshRoutingDeleteSourcePartsButton"
    assert text["apply_object"] == "MeshRoutingApplySourcePartsButton"
    assert "Original archive files are not modified" in text["delete_tooltip"]
    assert "Use, delete, and remove source changes rebuild the preview immediately" in text["apply_tooltip"]
    assert text["pending_label"] == "No unapplied source-part changes."


def test_source_part_inspector_control_text_preserves_labels_and_tooltips() -> None:
    text = source_part_inspector_control_text()

    assert text["group_title"] == "Selected Replacement Part"
    assert text["workflow_hint"] == "Transforms apply to the selected source part(s)."
    assert "Axis Scale for X/Y/Z-only changes" in text["workflow_hint_tooltip"]
    assert text["source_select_label"] == "Select part"
    assert "inspect, remove, resize, or route" in text["source_combo_tooltip"]
    assert text["name_placeholder"] == "No part selected."
    assert text["target_placeholder"] == "-"
    assert text["include_in_output"] == "Include in output"
    assert text["no_target_selected"] == "No target selected"
    assert "mapping clarity" in text["role_tooltip"]
    assert "original draw/material target" in text["target_tooltip"]
    assert text["replace_target"] == "Replace Target"
    assert text["add_target"] == "Add To Target"
    assert text["unmap_part"] == "Unmap Part"
    assert "only this selected source" in text["replace_target_tooltip"]
    assert "without removing any existing source indexes" in text["add_target_tooltip"]
    assert "every target row" in text["unmap_part_tooltip"]
    assert text["part_label"] == "Part"
    assert text["role_label"] == "Role"
    assert text["map_to_label"] == "Map to"
    assert text["add_mesh_part"] == "Add Mesh Part..."
    assert "OBJ, DAE, glTF/GLB" in text["add_mesh_part_tooltip"]
    assert text["duplicate_part"] == "Duplicate Part"
    assert "copy its current target mapping" in text["duplicate_part_tooltip"]
    assert text["mirror_duplicate_part"] == "Mirror Duplicate"
    assert "mirror it across the original model X center" in text["mirror_duplicate_part_tooltip"]
    assert text["texture_status_initial"] == "Texture: -"
    assert text["use_copied_texture"] == "Use copied original"
    assert text["use_route_texture"] == "Use route source"
    assert text["remove_copied_texture"] == "Remove copied texture"
    assert "DDS refs copied from the original part" in text["use_copied_texture_tooltip"]
    assert "normal replacement material route" in text["use_route_texture_tooltip"]
    assert "Geometry remains" in text["remove_copied_texture_tooltip"]


def test_source_part_glow_color_button_text_preserves_fallback_copy() -> None:
    assert source_part_glow_color_button_text("#AABBCC", enabled=True) == "#AABBCC"
    assert source_part_glow_color_button_text("#AABBCC", enabled=False) == "Pick"


def test_source_part_glow_color_controls_state_clamps_rgb_and_controls_button() -> None:
    assert source_part_glow_rgb((300, -5, "bad")) == (255, 0, 0)
    assert source_part_glow_rgb((16,)) == (16, 0, 0)

    enabled_state = source_part_glow_color_controls_state(
        rgb=(16, 32, 48),
        complete_external_swap_enabled=True,
        checked=True,
        checkbox_enabled=True,
    )
    assert enabled_state.enabled
    assert enabled_state.color_text == "#102030"
    assert enabled_state.style_sheet == "QPushButton { background-color: #102030; color: #0d1117; }"

    disabled_state = source_part_glow_color_controls_state(
        rgb=(16, 32, 48),
        complete_external_swap_enabled=False,
        checked=True,
        checkbox_enabled=True,
    )
    assert not disabled_state.enabled
    assert disabled_state.color_text == "Pick"
    assert disabled_state.style_sheet == ""


def test_selected_source_part_display_text_preserves_dialog_copy() -> None:
    assert selected_source_part_name_text(3, "Skin", multi_selected_count=1) == "3: Skin"
    assert selected_source_part_name_text(3, "Skin", multi_selected_count=1234) == (
        "1,234 parts selected; primary 3: Skin"
    )
    assert selected_source_part_target_text("target A", multi_selected_count=1) == "Mapped target(s): target A"
    assert selected_source_part_target_text("", multi_selected_count=1) == "Mapped target(s): none yet"
    assert selected_source_part_target_text("target A", multi_selected_count=2) == (
        "Transform scope is explicit source selection. Primary mapped target(s): target A"
    )


def test_source_part_properties_control_text_preserves_labels_and_object_names() -> None:
    text = source_part_properties_control_text()
    sections = text["sections"]

    assert text["title"] == "Properties"
    assert text["group_object"] == "MeshReplacementPropertiesContext"
    assert text["placeholder"] == "-"
    assert sections["identity"] == ("Identity", "MeshReplacementPropertiesIdentity")
    assert sections["assignment"] == ("Assignment", "MeshReplacementPropertiesAssignment")
    assert sections["dds"] == ("DDS / Sidecar", "MeshReplacementPropertiesDDS")
    assert sections["output"] == ("Output", "MeshReplacementPropertiesOutput")
    assert sections["warnings"] == ("Warnings", "MeshReplacementPropertiesWarnings")
    assert text["dds_default"] == "DDS | -"
    assert text["none_identity"] == "Selection | none"
    assert text["none_assignment"] == "Target/source/material row not selected."


def test_source_part_properties_label_and_output_text_escape_and_format_values() -> None:
    assert source_part_properties_label_html("Identity", "<source>") == "<b>Identity</b><br>&lt;source&gt;"
    assert source_part_properties_label_html("Warnings", "") == "<b>Warnings</b><br>-"
    assert source_part_properties_output_text(1234, 56, 7, 8, "prune removed") == (
        "Output | remove 1,234 | source 56 | disabled 7 | DDS 8 | sidecar prune removed"
    )


def test_source_part_properties_warnings_preserve_target_and_source_copy() -> None:
    assert source_part_target_properties_warning("Removed", "visible only") == (
        "Removed target: geometry is omitted; patched sidecar prunes its DDS parameters."
    )
    assert source_part_target_properties_warning("Removed", "keep") == (
        "Removed target: geometry is omitted; sidecar DDS references are kept unless material sidecar patching is enabled."
    )
    assert source_part_target_properties_warning("Physics", "mapped") == "Review physics/collision companion data."
    assert source_part_target_properties_warning("Mapped", "mapped") == ""
    assert source_part_source_properties_warning(()) == (
        "This source will not replace an original target until assigned."
    )
    assert source_part_source_properties_warning((1, 2)) == ""


def test_source_part_properties_dds_and_material_text_preserve_copy() -> None:
    assert source_part_source_properties_dds_text("Skin") == "DDS | Skin"
    assert source_part_source_properties_dds_text("") == "DDS | material route in Materials tab"
    assert source_part_material_properties_text("Skin", "Base", "skin.dds") == (
        "Material | Skin",
        "Base | skin.dds",
        "DDS | skin.dds",
    )
    assert source_part_material_properties_text("", "", "") == ("Material | -", "DDS | -", "DDS | -")


def _properties_state(selection: dict[str, object], **overrides: object):
    kwargs = {
        "output_counts": (2, 3, 1, 4, "prune removed"),
        "target_source_indices": lambda target_index: (0, 2) if target_index == 5 else (),
        "target_outliner_state": lambda target_index, source_indices: (
            ("Removed", "#fb923c") if not tuple(source_indices) else ("Mapped", "#3fb950")
        ),
        "format_source_indices": lambda indices: ", ".join(f"src {index}" for index in indices) or "-",
        "format_target_indices": lambda indices: ", ".join(f"target {index}" for index in indices) or "-",
        "target_dds_label": lambda target_index: f"TargetMat{target_index}" if target_index >= 0 else "",
        "target_texture_status_text": lambda target_name: f"Tex {target_name}",
        "source_assigned_target_indices": lambda source_index: (5,) if source_index == 2 else (),
        "source_outliner_state": lambda source_index, mapped_targets: (
            ("Assigned", "#3fb950") if tuple(mapped_targets) else ("Unassigned", "#d29922")
        ),
        "source_material_name": lambda source_index: f"Material{source_index}",
    }
    kwargs.update(overrides)
    return source_part_properties_inspector_state(selection, **kwargs)


def test_source_part_properties_inspector_state_builds_target_source_material_and_none_views() -> None:
    target = _properties_state({"kind": "target", "target_indices": (5,)})
    assert target.identity_text == "Target | target 5"
    assert target.assignment_text == "Mapped | src 0, src 2"
    assert target.dds_text == "DDS | Tex TargetMat5 | sidecar mapped"
    assert target.output_text == "Output | remove 2 | source 3 | disabled 1 | DDS 4 | sidecar prune removed"
    assert not target.warning_visible
    assert "<b>Identity</b><br>Target | target 5" == target.identity_html

    removed_target = _properties_state({"kind": "target", "target_indices": (9,)})
    assert removed_target.assignment_text == "Removed | -"
    assert removed_target.dds_text == "DDS | Tex TargetMat9 | sidecar prune removed"
    assert "patched sidecar prunes" in removed_target.warning_text
    assert removed_target.warning_visible

    source = _properties_state({"kind": "source", "source_indices": (2,)})
    assert source.identity_text == "Source | src 2 | Material2"
    assert source.assignment_text == "Assigned | target 5"
    assert source.dds_text == "DDS | Material2"
    assert not source.warning_visible

    material = _properties_state(
        {"kind": "material", "material_name": "Skin", "texture_role": "Base", "texture_path": "C:/tmp/skin.dds"}
    )
    assert material.identity_text == "Material | Skin"
    assert material.assignment_text == "Base | skin.dds"
    assert material.dds_text == "DDS | skin.dds"

    none = _properties_state({"kind": "none"})
    assert none.identity_text == "Selection | none"
    assert none.assignment_text == "Target/source/material row not selected."
    assert none.dds_text == "DDS | -"


def test_source_part_selection_context_presentation_preserves_copy() -> None:
    assert source_part_selection_context_label_text("Geometry", "src", "target", "texture.dds") == (
        "Geometry | Source: src | Target: target | Texture: texture.dds"
    )
    assert source_part_selection_context_label_text("", "", "", "") == (
        "Setup | Source: none | Target: none | Texture: none"
    )
    assert source_part_selection_context_tooltip("src", "target", "texture.dds") == (
        "Source: src\nTarget: target\nTexture: texture.dds"
    )
    assert source_part_selection_texture_row_text("target", "Base", "base.dds") == "target / Base -> base.dds"
    assert source_part_selection_texture_row_text("", "", "") == "target / DDS -> keep original"
    assert source_part_selection_added_texture_text("source 1", "Base / Color", "base.dds") == (
        "source 1 / Base / Color -> base.dds"
    )
    assert source_part_selection_added_texture_text("", "", "") == "source / Texture -> none"
    assert source_part_selection_texture_fallback("Skin") == "Skin"
    assert source_part_selection_texture_fallback("") == "none"


def test_source_part_selection_texture_context_helpers_extract_row_and_added_part_text() -> None:
    row_context = source_part_selection_texture_row_context_text(
        {
            "slot_kind": "base",
            "source_path": "C:/mods/body_base.dds",
            "target_name": "phw_body_a",
        },
        role_label_for_slot=lambda slot: {"base": "Base / Color"}.get(slot, slot),
        simplify_part_label=lambda text: text.replace("phw_", ""),
    )
    assert row_context == "body_a / Base / Color -> body_base.dds"

    suggested_context = source_part_selection_texture_row_context_text(
        {
            "original_slot_kind": "normal",
            "suggested_source": "C:/mods/body_n.dds",
            "target_name": "",
        },
        role_label_for_slot=lambda slot: slot.upper(),
        simplify_part_label=lambda text: text,
    )
    assert suggested_context == "target / NORMAL -> body_n.dds"

    added_context = source_part_selection_added_texture_context_text(
        4,
        "base",
        "C:/mods/added_base.dds",
        source_display_name=lambda index: f"source {index}",
        added_part_texture_role_label=lambda role: {"base": "Base / Color"}.get(role, role),
    )
    assert added_context == "source 4 / Base / Color -> added_base.dds"
    assert source_part_selection_added_texture_context_text(
        -1,
        "base",
        "",
        source_display_name=lambda index: str(index),
        added_part_texture_role_label=lambda role: role,
    ) == ""


def test_source_part_selection_context_state_uses_selection_fallbacks_and_compacts_label() -> None:
    state = source_part_selection_context_state(
        selected_tab="Materials",
        source_index=-1,
        target_index="bad",
        selected_source_highlight_indices=(3, 1),
        selected_target_highlight_indices=(9, 5),
        texture_text="texture_" + ("x" * 80) + ".dds",
        source_display_name=lambda index: f"source {index}",
        target_display_name=lambda index: f"target {index}",
    )

    assert state.source_index == 1
    assert state.target_index == 5
    assert state.source_text == "source 1"
    assert state.target_text == "target 5"
    assert state.label_text.startswith("Materials | Source: source 1 | Target: target 5 | Texture: texture_")
    assert state.label_text.endswith("...")
    assert state.tooltip_text.startswith("Source: source 1\nTarget: target 5\nTexture: texture_")

    empty = source_part_selection_context_state(
        selected_tab="",
        source_index=-1,
        target_index=-1,
        selected_source_highlight_indices=(),
        selected_target_highlight_indices=(),
        texture_text="",
        source_display_name=lambda index: f"source {index}",
        target_display_name=lambda index: f"target {index}",
    )
    assert empty.label_text == "Setup | Source: none | Target: none | Texture: none"
    assert empty.tooltip_text == "Source: none\nTarget: none\nTexture: none"


def test_source_part_copied_texture_status_text_preserves_display_copy() -> None:
    assert source_part_copied_texture_status_text(has_rows=False) == "Texture: -"
    assert source_part_copied_texture_status_text(has_rows=True, disabled=True, copied_badge="Copied Orig") == (
        "Texture: Route source"
    )
    assert source_part_copied_texture_status_text(has_rows=True, copied_badge="Copied Orig") == (
        "Texture: Copied Orig"
    )


def test_source_part_transform_control_text_preserves_labels_and_tooltips() -> None:
    text = source_part_transform_control_text()

    assert text["uniform_prefix"] == "All "
    assert text["translate_spin_tooltip"] == "Move selected part(s) on this local axis."
    assert text["rotate_spin_tooltip"] == "Rotate selected part(s) around this axis in degrees."
    assert text["axis_spin_tooltip"] == "Non-uniform axis scale. 1.0 leaves this axis unchanged."
    assert text["uniform_spin_tooltip"] == "Uniform scale. Multiplies all axes equally; 1.0 leaves size unchanged."
    assert text["translate_label"] == "Translate"
    assert text["translate_x_tooltip"] == "Selected part X translate slider."
    assert text["nudge_step_prefix"] == "Step "
    assert "keyboard shortcuts" in text["nudge_step_tooltip"]
    assert (text["nudge_x_minus"], text["nudge_x_plus"]) == ("-X", "+X")
    assert (text["nudge_y_minus"], text["nudge_y_plus"]) == ("-Y", "+Y")
    assert (text["nudge_z_minus"], text["nudge_z_plus"]) == ("-Z", "+Z")
    assert text["nudge_tooltip"] == "Nudge the selected part by the configured step."
    assert text["center_part"] == "Center To Target"
    assert "without changing rotation or scale" in text["center_part_tooltip"]
    assert text["rotate_label"] == "Rotate"
    assert text["axis_scale_label"] == "Axis Scale"
    assert "Non-uniform scale" in text["axis_scale_tooltip"]
    assert text["uniform_scale_label"] == "Uniform Scale"
    assert text["uniform_scale_tooltip"] == "Equal scale applied to all axes."
    assert text["reset_part"] == "Reset Part"
    assert text["remove_part"] == "Disable Part Output"
    assert text["fit_part"] == "Fit Size"
    assert text["undo_geometry"] == "Undo Geometry"
    assert text["reset_geometry"] == "Reset Geometry"
    assert "removed placeholders" in text["remove_part_tooltip"]
    assert "Reset the selected source part" in text["reset_part_tooltip"]
    assert "Use Translate" in text["fit_part_tooltip"]
    assert "last Geometry action" in text["undo_geometry_tooltip"]
    assert "initial alignment state" in text["reset_geometry_tooltip"]


def test_source_part_context_menu_text_preserves_source_actions() -> None:
    text = source_part_context_menu_text()

    assert text["delete_selected_parts"] == "Delete Selected Part(s)"
    assert text["apply"] == "Apply"
    assert text["set_role_glow"] == "Set Role: Glow / emissive"
    assert text["set_role_auto"] == "Set Role: Auto / inferred"


def test_source_part_delete_selection_and_index_map_state_normalize_sources() -> None:
    empty = source_part_delete_selection_state((), source_count=4)
    assert empty.available is False
    assert empty.status_key == "select_first"
    assert empty.delete_indices == frozenset()

    marker_only = source_part_delete_selection_state((2,), source_count=4, marker_source_indices=(2,))
    assert marker_only.available is False
    assert marker_only.status_key == "none_deletable"

    selection = source_part_delete_selection_state(
        (3, "bad", -1, 2, 5),
        source_count=4,
        marker_source_indices=(2,),
    )
    assert selection.available is True
    assert selection.delete_indices == frozenset({3})

    index_map = source_part_delete_index_map_state(source_count=5, delete_indices=(1, 4, 99))
    assert index_map.deleted_indices == (1, 4)
    assert index_map.kept_indices == (0, 2, 3)
    assert index_map.index_map == {0: 0, 2: 1, 3: 2}


def test_source_part_assignment_dialog_text_preserves_labels_and_tooltips() -> None:
    text = source_part_assignment_dialog_text()

    assert text["window_title"] == "Assign Added Mesh Parts"
    assert text["high_density_title"] == "High-density mesh import"
    assert text["added_parts_title"] == "Added mesh parts"
    assert "selected target" in text["default_target_summary"]
    assert "not final-exportable" in text["preview_only_summary"]
    assert "Materials & Textures" in text["texture_warning"]
    assert "65,535 vertices" in text["dense_warning"]
    assert text["preview_only_combo"] == "Preview only"
    assert text["attach_to_target_prefix"] == "Attach to "
    assert text["apply_button"] == "Apply Attachments"
    assert text["attach_all_current"] == "Attach All To Current"
    assert text["attach_all_current_fallback"] == "Attach all to current target"
    assert text["attach_all_current_tooltip_prefix"] == "Attach every imported source row to "
    assert text["assign_by_order"] == "Assign By Order"
    assert text["open_textures"] == "Open Textures"
    assert text["preview_only_button"] == "Preview Only"
    assert text["cancel_import"] == "Cancel Import"
    assert "previous Geometry state" in text["cancel_import_tooltip"]


def test_source_part_assignment_tree_headers_preserves_column_labels() -> None:
    assert source_part_assignment_tree_headers() == ("Added source", "Geometry", "Assign to target")


def test_source_part_added_import_message_lines_preserves_summary_warnings() -> None:
    lines = source_part_added_import_message_lines(
        part_count=1234,
        source_name="source.glb",
        placement_note="centered",
        texture_count=5,
        texture_warning=True,
        dense_warning=True,
    )

    assert lines[0] == "Added 1,234 mesh part(s) from source.glb."
    assert "original draw/material target" in lines[1]
    assert "Placement: centered." in lines
    assert any("Detected 5 texture file(s)" in line for line in lines)
    assert any("No texture files were discovered" in line for line in lines)
    assert any("PAC output can preserve" in line for line in lines)
    assert lines[-1] == "Preview-only parts are visible in this session but are blocked from final PAC/PAM export."


def test_source_part_assignment_import_state_summarizes_added_sources() -> None:
    source_a = SimpleNamespace(
        material="Cape Cloth",
        name="cape",
        vertices=[object()] * 4,
        faces=[object()] * 2,
    )
    source_b = SimpleNamespace(
        material="",
        name="Pin",
        vertices=[object()] * 7,
        faces=[object()] * 3,
    )

    state = source_part_assignment_import_state(
        source_indices=(1, "bad", 0, 1, 3),
        replacement_sources=(source_a, source_b),
        source_name="source.glb",
        placement_note="centered",
        discovered_texture_count=0,
        matched_texture_indices=(1,),
        vertex_limit=10,
    )

    assert state.appended_indices == (1, 0)
    assert state.total_vertices == 11
    assert state.total_faces == 5
    assert state.matched_texture_count == 1
    assert state.has_texture_files is False
    assert state.texture_warning is False
    assert state.dense_warning is True
    assert state.detail_lines == (
        "1. Source 1: Pin - 7 vertices, 3 faces",
        "2. Source 0: Cape Cloth - 4 vertices, 2 faces",
    )
    assert state.message_lines[0] == "Added 2 mesh part(s) from source.glb."
    assert any("Placement: centered." in line for line in state.message_lines)


def test_source_part_assignment_summary_rows_and_buttons_preserve_dialog_specs() -> None:
    source_a = SimpleNamespace(material="Cape Cloth", name="cape", vertices=[object()] * 4, faces=[object()] * 2)
    source_b = SimpleNamespace(material="", name="Pin", vertices=[object()] * 7, faces=[object()] * 3)
    import_state = source_part_assignment_import_state(
        source_indices=(0, 1),
        replacement_sources=(source_a, source_b),
        source_name="source.glb",
        placement_note="centered",
        discovered_texture_count=2,
        matched_texture_indices=(),
        vertex_limit=20,
    )

    summary = source_part_assignment_summary_state(
        import_state=import_state,
        source_name="source.glb",
        placement_note="centered",
        discovered_texture_count=2,
    )
    assert summary.title == "Added mesh parts"
    assert summary.show_texture_warning is False
    assert summary.show_dense_warning is False
    assert summary.summary_lines == (
        "2 part(s) from source.glb",
        "Default: attach to the selected target when one is selected.",
        "Placement: centered.",
        "Textures: 2 detected; route in Textures.",
        "Rows left as Preview only are not final-exportable in this pass.",
    )

    rows = source_part_assignment_row_specs(
        appended_indices=(1, 0, 99),
        replacement_sources=(source_a, source_b),
        source_display_names=("Cape", "Pin"),
        target_display_names=("Body", "Cape"),
        primary_target=1,
    )
    assert [row.source_index for row in rows] == [1, 0]
    assert rows[0].geometry_text == "7 vertices, 3 faces"
    assert rows[0].tooltip == "Pin"
    assert rows[0].default_target == 1
    assert [(option.label, option.target_index) for option in rows[0].target_options] == [
        ("Preview only", -1),
        ("Attach to Body", 0),
        ("Attach to Cape", 1),
    ]

    buttons = source_part_assignment_button_state(
        primary_target=1,
        target_count=2,
        texture_warning=True,
        current_target_name="Cape",
    )
    assert buttons.add_all_text == "Attach All To Current"
    assert buttons.add_all_enabled is True
    assert buttons.add_all_tooltip == "Attach every imported source row to Cape."
    assert buttons.assign_order_enabled is True
    assert buttons.textures_visible is True

    fallback = source_part_assignment_button_state(
        primary_target=-1,
        target_count=0,
        texture_warning=False,
    )
    assert fallback.add_all_text == "Attach all to current target"
    assert fallback.add_all_enabled is False
    assert fallback.add_all_tooltip == ""
    assert fallback.assign_order_enabled is False
    assert fallback.textures_visible is False


def test_source_part_assignment_target_and_apply_state_route_rows() -> None:
    assert source_part_assignment_target_index("3") == 3
    assert source_part_assignment_target_index("bad") == -1
    row_targets = ((5, 2), (6, -1), (7, 2), ("bad", 1), (8, 9))
    assert source_part_assignment_target_for_source(row_targets, 7) == 2
    assert source_part_assignment_target_for_source(row_targets, 9) == -1

    state = source_part_assignment_apply_state(row_targets=row_targets, target_count=3)
    assert state.assignments_by_target == {2: (5, 7)}
    assert state.preview_indices == (6,)
    assert state.attached_indices == (5, 7)


def test_source_part_assignment_primary_highlight_and_route_state() -> None:
    assert source_part_assignment_primary_target(
        selected_target_index=-1,
        selected_original_index=2,
        target_count=4,
    ) == 2
    assert source_part_assignment_primary_target(
        selected_target_index=5,
        selected_original_index=2,
        target_count=4,
    ) == -1

    highlight = source_part_assignment_highlight_state(
        source_index=7,
        target_index=2,
        mapped_source_indices=(4, "bad", 7, 9),
    )
    assert highlight.source_index == 7
    assert highlight.target_index == 2
    assert highlight.target_original_indices == (2,)
    assert highlight.target_source_indices == (7, 4, 9)

    textures_route = source_part_assignment_route_state(
        action="textures",
        appended_indices=(5, 6),
        primary_target=0,
        target_count=3,
    )
    assert textures_route.route == "textures"
    assert textures_route.preview_indices == (5, 6)
    assert textures_route.open_textures is True

    add_all_route = source_part_assignment_route_state(
        action="add_all",
        appended_indices=(5, 6),
        primary_target=1,
        target_count=3,
    )
    assert add_all_route.assignments_by_target == {1: (5, 6)}
    assert add_all_route.attached_indices == (5, 6)

    by_order_route = source_part_assignment_route_state(
        action="by_order",
        appended_indices=(5, 6, 7),
        primary_target=1,
        target_count=3,
    )
    assert by_order_route.assignments_by_target == {1: (5,), 2: (6, 7)}

    apply_route = source_part_assignment_route_state(
        action="apply",
        appended_indices=(5, 6, 7),
        primary_target=-1,
        target_count=3,
        row_targets=((5, 2), (6, -1), (7, 9)),
    )
    assert apply_route.assignments_by_target == {2: (5,)}
    assert apply_route.preview_indices == (6,)
    assert apply_route.attached_indices == (5,)

    cancel_route = source_part_assignment_route_state(
        action="bogus",
        appended_indices=(5,),
        primary_target=-1,
        target_count=0,
    )
    assert cancel_route.cancel_import is True


def test_source_part_append_route_and_texture_control_state() -> None:
    assert source_part_append_file_route_state("", allowed_extensions=(".glb",)).route == "cancel"
    assert source_part_append_file_route_state("asset.FBX", allowed_extensions=(".glb",)).route == "fbx_deferred"
    assert source_part_append_file_route_state("asset.txt", allowed_extensions=(".glb",)).route == "unsupported"
    assert source_part_append_file_route_state("asset.GLB", allowed_extensions=(".glb",)).route == "import"

    texture_set = SimpleNamespace(slots={"base": object()})
    state = source_part_append_texture_control_state(
        has_texture_files=True,
        texture_sets=(None, texture_set),
    )
    assert state.enable_rebuild_sidecar is True
    assert state.enable_inject_base_color is True

    empty_state = source_part_append_texture_control_state(
        has_texture_files=False,
        texture_sets=(texture_set,),
    )
    assert empty_state.enable_rebuild_sidecar is False
    assert empty_state.enable_inject_base_color is False


def test_source_part_added_export_blocker_message_preserves_guidance() -> None:
    assert source_part_added_export_blocker_title() == "Attach Added Mesh Parts"
    message = source_part_added_export_blocker_message("- Part 1")

    assert "must be attached to an original target" in message
    assert "Preview-only parts are shown in Live Alignment Preview only" in message
    assert "- Part 1" in message
    assert "use Add To Target" in message


def test_source_part_scene_import_prompt_text_preserves_buttons() -> None:
    text = source_part_scene_import_prompt_text()

    assert text["multipart_title"] == "Mesh Contains Multiple Parts"
    assert text["keep_separate_parts"] == "Keep Separate Parts"
    assert text["group_by_material"] == "Group By Material"
    assert text["flatten_to_one_part"] == "Flatten To One Part"
    assert text["cancel_import"] == "Cancel Import"
    assert text["high_density_title"] == "High Density Mesh Import"
    assert text["keep_full_quality"] == "Keep Full Quality"
    assert text["reduce_quality"] == "Reduce For Performance/Size"
    assert text["reduction_title"] == "Mesh Quality Reduced"
    assert text["cancel_status_suffix"] == "Geometry was unchanged."


def test_source_part_multipart_import_state_routes_prompt_and_buttons() -> None:
    mesh = SimpleNamespace(
        submeshes=(
            SimpleNamespace(vertices=range(4), faces=range(2)),
            SimpleNamespace(vertices=range(8), faces=range(4)),
            SimpleNamespace(vertices=(), faces=range(4)),
        )
    )

    state = source_part_multipart_import_state(mesh)

    assert state.part_count == 2
    assert state.should_prompt
    assert source_part_multipart_import_state(SimpleNamespace(submeshes=(mesh.submeshes[0],))).should_prompt is False

    keep_button = object()
    group_button = object()
    flatten_button = object()
    cancel_button = object()
    assert (
        source_part_multipart_import_action(
            cancel_button,
            cancel_button=cancel_button,
            group_button=group_button,
            flatten_button=flatten_button,
        )
        == "cancel"
    )
    assert (
        source_part_multipart_import_action(
            group_button,
            cancel_button=cancel_button,
            group_button=group_button,
            flatten_button=flatten_button,
        )
        == "group"
    )
    assert (
        source_part_multipart_import_action(
            flatten_button,
            cancel_button=cancel_button,
            group_button=group_button,
            flatten_button=flatten_button,
        )
        == "flatten"
    )
    assert (
        source_part_multipart_import_action(
            keep_button,
            cancel_button=cancel_button,
            group_button=group_button,
            flatten_button=flatten_button,
        )
        == "keep"
    )


def test_source_part_multipart_prompt_state_builds_dialog_copy() -> None:
    mesh = SimpleNamespace(
        submeshes=(
            SimpleNamespace(vertices=range(4), faces=range(2)),
            SimpleNamespace(vertices=range(8), faces=range(4)),
        )
    )

    state = source_part_multipart_prompt_state(source_name="mesh.glb", mesh=mesh)

    assert state.should_prompt is True
    assert state.part_count == 2
    assert state.title == "Mesh Contains Multiple Parts"
    assert "mesh.glb imports as 2 separate mesh part(s)." in state.message
    assert "2 part(s), 12 vertices, 6 faces" in state.message
    assert state.keep_separate_parts == "Keep Separate Parts"
    assert state.group_by_material == "Group By Material"
    assert state.flatten_to_one_part == "Flatten To One Part"
    assert state.cancel_import == "Cancel Import"


def test_source_part_high_density_import_state_routes_buttons_and_limits() -> None:
    reduce_button = object()
    cancel_button = object()
    keep_button = object()

    assert (
        source_part_high_density_import_action(
            cancel_button,
            cancel_button=cancel_button,
            reduce_button=reduce_button,
        )
        == "cancel"
    )
    assert (
        source_part_high_density_import_action(
            reduce_button,
            cancel_button=cancel_button,
            reduce_button=reduce_button,
        )
        == "reduce"
    )
    assert (
        source_part_high_density_import_action(
            keep_button,
            cancel_button=cancel_button,
            reduce_button=reduce_button,
        )
        == "keep"
    )

    limits = source_part_high_density_reduction_limits()
    assert limits.max_faces_per_submesh == 45_000
    assert limits.max_vertices_per_submesh == 55_000


def test_source_part_high_density_prompt_state_builds_dialog_copy() -> None:
    mesh = SimpleNamespace(
        submeshes=(SimpleNamespace(vertices=range(120_000), faces=range(10)),)
    )

    state = source_part_high_density_prompt_state(mesh=mesh, size_text="\nFile size: 20 MB")

    assert state.should_prompt is True
    assert state.title == "High Density Mesh Import"
    assert "1 part(s), 120,000 vertices, 10 faces" in state.message
    assert "File size: 20 MB" in state.message
    assert state.keep_full_quality == "Keep Full Quality"
    assert state.reduce_quality == "Reduce For Performance/Size"
    assert state.cancel_import == "Cancel Import"
    assert state.reduction_title == "Mesh Quality Reduced"

    small = source_part_high_density_prompt_state(
        mesh=SimpleNamespace(submeshes=(SimpleNamespace(vertices=range(4), faces=range(2)),)),
        size_text="",
    )
    assert small.should_prompt is False


def test_source_part_scene_import_messages_preserve_prompt_copy() -> None:
    multipart = source_part_multipart_import_message(
        source_name="mesh.glb",
        part_count=12,
        density_text="12 part(s), 1,000 vertices",
    )
    assert "mesh.glb imports as 12 separate mesh part(s)." in multipart
    assert "Keep Separate Parts lets you assign" in multipart
    assert "Group By Material keeps separate texture/material groups" in multipart
    assert "Flatten To One Part combines them" in multipart
    assert "Imported mesh: 12 part(s), 1,000 vertices" in multipart

    high_density = source_part_high_density_import_message(
        density_text="1 part(s), 120,000 vertices",
        size_text="\nFile size: 20 MB",
    )
    assert "high vertex/face count" in high_density
    assert "Keep Full Quality preserves" in high_density
    assert "Reduce For Performance/Size creates" in high_density

    reduction = source_part_reduction_result_message(
        original_vertices=120000,
        original_faces=180000,
        reduced_vertices=55000,
        reduced_faces=45000,
    )
    assert "Before: 120,000 vertices, 180,000 faces" in reduction
    assert "After: 55,000 vertices, 45,000 faces" in reduction
    assert "original mesh file was not modified" in reduction
    assert source_part_cancel_import_status("mesh.glb") == "Canceled mesh.glb; Geometry was unchanged."


def test_source_part_scene_import_density_helpers_preserve_thresholds() -> None:
    mesh = SimpleNamespace(
        submeshes=(
            SimpleNamespace(vertices=range(4), faces=range(2)),
            SimpleNamespace(vertices=range(120_000), faces=range(1)),
            SimpleNamespace(vertices=(), faces=range(10)),
        )
    )

    assert source_part_format_mesh_density_counts(mesh) == (
        "3 part(s), 120,004 vertices, 13 faces (largest part: 120,000 vertices, 10 faces)"
    )
    assert source_part_scene_import_appendable_part_count(mesh) == 2
    assert source_part_scene_import_is_high_density(mesh)
    assert not source_part_scene_import_is_high_density(SimpleNamespace(submeshes=(SimpleNamespace(vertices=range(4), faces=range(2)),)))


def test_source_part_append_mesh_file_dialog_text_preserves_copy() -> None:
    text = source_part_append_mesh_file_dialog_text()

    assert text["title"] == "Add Mesh Part"
    assert text["mesh_filter"] == "Mesh Sources (*.obj *.dae *.gltf *.glb *.pac *.pam *.pamlod);;All Files (*.*)"
    assert text["fbx_title"] == "FBX Import Deferred"
    assert "FBX import is not supported inside Geometry yet" in text["fbx_message"]
    assert text["unsupported_title"] == "Unsupported Mesh Part"
    assert "Geometry can append OBJ, DAE, glTF/GLB, PAC, PAM, or PAMLOD files." in text["unsupported_message_prefix"]
    assert source_part_unsupported_mesh_part_message("part.fbx") == (
        "Geometry can append OBJ, DAE, glTF/GLB, PAC, PAM, or PAMLOD files.\n\nSelected: part.fbx"
    )
    assert source_part_add_mesh_part_failed_title() == "Add Mesh Part Failed"
    assert source_part_added_mesh_part_status("part.obj") == "Added part.obj as a Geometry source part."
    assert source_part_added_mesh_part_status("part.obj", "Placement: centered") == "Added part.obj; Placement: centered."


def test_source_part_append_label_state_matches_dialog_formatting() -> None:
    source = SimpleNamespace(material="Cape Cloth", name="Cape")
    unnamed_source = SimpleNamespace(material="", name="")

    assert source_part_append_material_label(source, 4) == "Cape Cloth"
    assert source_part_append_material_label(unnamed_source, 4) == "part 4"
    assert source_part_append_ordinal_suffix(appended_ordinal=2, appended_source_count=3) == " part 2/3"
    assert source_part_append_ordinal_suffix(appended_ordinal=1, appended_source_count=1) == ""
    assert (
        source_part_append_display_override(
            source_stem="armor",
            material_label="Cape Cloth",
            ordinal_suffix=" part 2/3",
        )
        == "armor: Cape Cloth part 2/3"
    )
    assert source_part_append_role_hint_text(source_stem="armor", material_label="Cape Cloth") == "armor Cape Cloth"


def test_source_part_append_index_state_applies_preview_only_defaults() -> None:
    state = source_part_append_index_state(
        source_indices=(3, 5),
        appended_source_indices=(1, 3),
        independent_output_source_indices=(2, 3, 5),
        preview_only_source_indices=(8,),
    )

    assert state.appended_source_indices == (1, 3, 5)
    assert state.independent_output_source_indices == (2,)
    assert state.preview_only_source_indices == (3, 5, 8)


def test_source_part_append_presentations_match_dialog_rows() -> None:
    sources = (
        SimpleNamespace(material="Body", name=""),
        SimpleNamespace(material="", name="Cape"),
        SimpleNamespace(material="", name=""),
    )

    presentations = source_part_append_presentations(
        source_indices=(0, 2, 9),
        sources=sources,
        source_stem="armor",
    )

    assert tuple(p.source_index for p in presentations) == (0, 2)
    assert presentations[0].display_override == "armor: Body part 1/3"
    assert presentations[0].role_hint_text == "armor Body"
    assert presentations[1].display_override == "armor: part 2 part 2/3"
    assert presentations[1].role_hint_text == "armor part 2"


def test_source_part_append_imported_state_combines_route_and_presentations() -> None:
    sources = (
        SimpleNamespace(material="Body", name=""),
        SimpleNamespace(material="", name="Cape"),
    )

    state = source_part_append_imported_state(
        source_indices=("1", "bad", 4),
        sources=sources,
        source_stem="armor",
        appended_source_indices=(8,),
        independent_output_source_indices=(1, 2),
        preview_only_source_indices=(7,),
    )

    assert state.source_indices == (1, 4)
    assert state.first_source_index == 1
    assert state.index_state.appended_source_indices == (1, 4, 8)
    assert state.index_state.independent_output_source_indices == (2,)
    assert state.index_state.preview_only_source_indices == (1, 4, 7)
    assert tuple(p.source_index for p in state.presentations) == (1,)
    assert state.presentations[0].display_override == "armor: Cape part 1/2"


def test_source_part_append_rollback_snapshot_normalizes_mutable_state() -> None:
    adjustments = {1: SimpleNamespace(value=["keep"])}
    redo_adjustments = [SimpleNamespace(value=["redo"])]

    snapshot = source_part_append_rollback_snapshot(
        replacement_mesh="mesh",
        replacement_base_mesh="base",
        appended_source_indices=(2, "bad", 2),
        independent_output_source_indices=(3,),
        preview_only_source_indices=(4,),
        source_role_overrides={2: "role"},
        source_display_overrides={2: "display"},
        source_part_adjustments=adjustments,
        dialog_added_supplemental_files=["sidecar"],
        texture_files_for_mapping=["tex"],
        source_material_texture_override_assignments={"slot": "path"},
        mesh_edit_redo_stack=["redo"],
        mesh_edit_redo_adjustment_stack=redo_adjustments,
        source_geometry_revision="12",
        selected_source_index="2",
        selected_source_indices=(2, 3),
        selected_target_index="4",
        selected_original_index="5",
        selected_source_highlights=(2,),
        selected_target_source_highlights=(4,),
        transform_source_indices=(2, 3),
        selected_original_highlights=(5,),
        selected_target_original_highlights=(6,),
    )

    adjustments[1].value.append("changed")
    redo_adjustments[0].value.append("changed")

    assert snapshot.appended_source_indices == (2,)
    assert snapshot.source_geometry_revision == 12
    assert snapshot.selected_source_index == 2
    assert snapshot.selected_source_indices == (2, 3)
    assert snapshot.source_part_adjustments[1].value == ["keep"]
    assert snapshot.mesh_edit_redo_adjustment_stack[0].value == ["redo"]


def test_source_part_duplicate_text_preserves_undo_suffix_and_status() -> None:
    assert source_part_duplicate_undo_label(mirrored=False) == "Duplicate source part"
    assert source_part_duplicate_undo_label(mirrored=True) == "Mirror duplicate source part"
    assert source_part_duplicate_copy_suffix(mirrored=False) == "copy"
    assert source_part_duplicate_copy_suffix(mirrored=True) == "mirrored copy"
    assert source_part_duplicate_status(mirrored=False, source_index=2, new_index=7) == "Duplicated source part 2 as 7."
    assert source_part_duplicate_status(mirrored=True, source_index=2, new_index=7) == (
        "Mirrored duplicate source part 2 as 7."
    )


def test_source_part_duplicate_state_normalizes_guard_and_overrides() -> None:
    assert source_part_duplicate_available(source_index=1, source_count=2, has_base_mesh=True) is True
    assert source_part_duplicate_available(source_index=2, source_count=2, has_base_mesh=True) is False
    assert source_part_duplicate_available(source_index=0, source_count=2, has_base_mesh=False) is False
    assert source_part_duplicate_available(source_index="bad", source_count=2, has_base_mesh=True) is False

    assert source_part_duplicate_role_override(" Geometry ", "Fallback") == "Geometry"
    assert source_part_duplicate_role_override("", "Fallback") == "Fallback"
    assert source_part_duplicate_display_override("Cape", "copy") == "Cape (copy)"
    assert source_part_duplicate_display_override("Cape", "") == "Cape"


def test_source_part_duplicate_route_and_presentation_state() -> None:
    route = source_part_duplicate_route_state(
        mirrored=True,
        source_index="2",
        source_count=4,
        has_base_mesh=True,
        new_index=4,
        mapped_target_indices=(9, "bad", 9),
        independent_output_source_indices=(2,),
        preview_only_source_indices=(),
    )

    assert route.available is True
    assert route.source_index == 2
    assert route.new_index == 4
    assert route.mapped_target_indices == (9,)
    assert route.output_route == "independent"
    assert route.undo_label == "Mirror duplicate source part"
    assert route.copy_suffix == "mirrored copy"
    assert route.status_text == "Mirrored duplicate source part 2 as 4."

    unavailable = source_part_duplicate_route_state(
        mirrored=False,
        source_index="bad",
        source_count=4,
        has_base_mesh=True,
        new_index=5,
        mapped_target_indices=(),
        independent_output_source_indices=(),
        preview_only_source_indices=(),
    )
    assert unavailable.available is False
    assert unavailable.output_route == "preview"

    presentation = source_part_duplicate_presentation_state(
        existing_role=" Cape ",
        fallback_role="Fallback",
        source_label="Source A",
        copy_suffix="copy",
    )
    assert presentation.role_override == "Cape"
    assert presentation.display_override == "Source A (copy)"


def test_source_part_delete_and_edit_text_preserves_status_copy() -> None:
    delete_text = source_part_delete_status_text()
    assert delete_text["select_first"] == "Select replacement source part(s) to delete first."
    assert delete_text["none_deletable"] == "No deletable replacement source part selected."
    assert delete_text["undo_label"] == "Delete source part"
    assert source_part_deleted_pending_reason(3) == "deleted 3 source part(s); target routes were unassigned/remapped"
    assert source_part_deleted_status(3) == "Deleted 3 replacement source part(s). Preview is rebuilding."

    routing_text = source_part_group_routing_text()
    assert routing_text["no_source_title"] == "No Source Parts"
    assert routing_text["no_source_message"] == "There are no active replacement source parts to route."
    assert routing_text["no_target_title"] == "No Target Slots"
    assert routing_text["no_target_message"] == "The original model has no draw/material slots to route into."
    assert routing_text["undo_label"] == "Group routing by source material"
    assert routing_text["clear_manual_title"] == "Clear Manual DDS Overrides?"
    assert "Manual original-DDS override assignments can force the old slot layout" in routing_text["clear_manual_message"]
    assert routing_text["overflow_title"] == "Material Groups Exceed Target Slots"
    assert source_part_group_routing_overflow_message(("a", "b")) == (
        "The replacement has more source material group(s) than original target draw slot(s). "
        "Some groups still had to be merged, so those parts cannot keep separate textures unless you split the mesh "
        "differently or bake/atlas textures first.\n\n"
        "Merged groups: a, b"
    )
    assert source_part_group_routing_overflow_message(tuple(str(index) for index in range(9))).endswith(
        "Merged groups: 0, 1, 2, 3, 4, 5, 6, 7..."
    )

    assert source_part_include_exclude_pending_reason() == "source include/exclude changed"
    assert source_part_edit_undo_label("adjust") == "Adjust source part"
    assert source_part_edit_undo_label("toggle") == "Toggle source output"
    assert source_part_edit_undo_label("role") == "Change source part role"
    assert source_part_edit_undo_label("glow") == "Change accent glow color"
    assert source_part_edit_undo_label("unmap") == "Unmap source part"
    assert source_part_edit_undo_label("reset") == "Reset source part"
    assert source_part_edit_undo_label("remove") == "Remove source part from output"
    assert source_part_edit_undo_label("fit") == "Fit source part size"
    assert source_part_edit_undo_label("nudge") == "Nudge source part"
    assert source_part_edit_undo_label("center") == "Center source part on target"
    assert source_part_edit_undo_label("unknown") == ""


def test_source_part_routing_preview_action_routes_pending_or_rebuild() -> None:
    assert source_part_routing_preview_action(defer_preview=True, pending_reason="source unassigned") == {
        "apply_pending": True,
        "pending_reason": "source unassigned",
        "queue_preview": False,
    }
    assert source_part_routing_preview_action(defer_preview=True, pending_reason="") == {
        "apply_pending": True,
        "pending_reason": "source routing changed",
        "queue_preview": False,
    }
    assert source_part_routing_preview_action(defer_preview=False, pending_reason="ignored") == {
        "apply_pending": False,
        "pending_reason": "",
        "queue_preview": True,
    }


def test_source_parts_mark_apply_pending_sets_reason_and_clears_rebuild() -> None:
    state: dict[str, object] = {"preview_rebuild_pending": True, "preview_rebuild_reason": "old"}

    reason = source_parts_mark_apply_pending(state, " source disabled ")

    assert reason == "source disabled"
    assert state == {
        "pending": True,
        "reason": "source disabled",
        "preview_rebuild_pending": False,
        "preview_rebuild_reason": "",
    }


def test_source_parts_clear_apply_pending_resets_all_flags() -> None:
    state: dict[str, object] = {
        "pending": True,
        "reason": "source disabled",
        "preview_rebuild_pending": True,
        "preview_rebuild_reason": "rebuild",
    }

    source_parts_clear_apply_pending(state)

    assert state == {
        "pending": False,
        "reason": "",
        "preview_rebuild_pending": False,
        "preview_rebuild_reason": "",
    }


def test_source_parts_mark_preview_rebuild_pending_sets_rebuild_reason() -> None:
    state: dict[str, object] = {"pending": True, "reason": "source disabled"}

    reason = source_parts_mark_preview_rebuild_pending(state, "")

    assert reason == "source-part changes"
    assert state == {
        "pending": False,
        "reason": "",
        "preview_rebuild_pending": True,
        "preview_rebuild_reason": "source-part changes",
    }
    assert source_parts_preview_rebuild_pending(state) is True


def test_source_parts_apply_pending_presentation_keeps_existing_status_text() -> None:
    presentation = source_parts_apply_pending_presentation("source include/exclude changed")

    assert presentation.apply_button_enabled is True
    assert presentation.label_text == "Pending: source include/exclude changed. Press Apply to rebuild preview."
    assert presentation.label_visible is True
    assert presentation.performance_summary == "Part routing changes pending. Press Apply to rebuild preview."
    assert presentation.performance_details == "source include/exclude changed"


def test_source_parts_clear_apply_pending_presentation_hides_pending_label() -> None:
    presentation = source_parts_clear_apply_pending_presentation()

    assert presentation.apply_button_enabled is False
    assert presentation.label_text == "No unapplied source-part changes."
    assert presentation.label_visible is False
    assert presentation.performance_summary == ""
    assert presentation.performance_details == ""


def test_source_parts_preview_rebuild_pending_presentation_keeps_old_geometry_warning() -> None:
    presentation = source_parts_preview_rebuild_pending_presentation("source-part changes")

    assert presentation.apply_button_enabled is False
    assert presentation.label_text == (
        "Applied: source-part changes. Rebuilding preview; "
        "old D3D11 geometry may remain visible until reload finishes."
    )
    assert presentation.label_visible is True
    assert presentation.performance_summary == "Source-part changes applied. Rebuilding preview package."
    assert presentation.performance_details == (
        "source-part changes\nOld D3D11 geometry may remain visible until reload finishes."
    )


def test_source_parts_selection_pending_presentation_preserves_no_rebuild_feedback() -> None:
    presentation = source_parts_selection_pending_presentation("source disabled")

    assert presentation.apply_button_enabled is True
    assert presentation.label_text == ""
    assert presentation.label_visible is False
    assert presentation.performance_summary == "Part changes pending. Press Apply to rebuild preview."
    assert presentation.performance_details == (
        "Pending source disabled; selection update did not rebuild geometry."
    )
