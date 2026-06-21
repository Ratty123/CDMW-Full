"""Dependency exports for static replacement prompt owner."""

from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_added_part_textures import (
    added_texture_editor_loading_initial_state as _added_texture_editor_loading_initial_state_helper,
    added_texture_editor_loading_set as _added_texture_editor_loading_set_helper,
    added_part_detected_missing_message as _added_part_detected_missing_message_helper,
    added_part_attached_targets as _added_part_attached_targets_helper,
    added_part_detected_assignment_state as _added_part_detected_assignment_state_helper,
    added_part_selected_texture_assignment_state as _added_part_selected_texture_assignment_state_helper,
    added_part_texture_choose_dialog_state as _added_part_texture_choose_dialog_state_helper,
    added_part_texture_editor_context_state as _added_part_texture_editor_context_state_helper,
    added_part_texture_group_size_state as _added_part_texture_group_size_state_helper,
    added_part_texture_override_action_state as _added_part_texture_override_action_state_helper,
    added_part_texture_row_states as _added_part_texture_row_states_helper,
    added_part_texture_tree_visibility_state as _added_part_texture_tree_visibility_state_helper,
    added_part_texture_control_text as _added_part_texture_control_text_helper,
    added_part_texture_invalid_file_message as _added_part_texture_invalid_file_message_helper,
    added_part_target_has_material_conflict as _added_part_target_has_material_conflict_helper,
    added_part_texture_role_label as _added_part_texture_role_label_helper,
    added_part_texture_status as _added_part_texture_status_helper,
    current_added_part_texture_source_index as _current_added_part_texture_source_index_helper,
    selected_added_part_texture_row_initial_state as _selected_added_part_texture_row_initial_state_helper,
    source_material_name_for_index as _source_material_name_for_index_helper,
    source_slot_for_added_part as _source_slot_for_added_part_helper,
)
from cdmw.ui.archive_browser.static_replacement_dialog_callback_factories import (
    create_alignment_accept_build_callbacks,
    create_alignment_accept_dispatch_callbacks,
    create_alignment_custom_icon_callbacks,
    create_alignment_d3d11_loading_callbacks,
    create_alignment_d3d11_package_lifecycle_callbacks,
    create_alignment_mesh_diagnostics_callbacks,
    create_alignment_parts_outliner_mapping_callbacks,
    create_alignment_preview_mode_callbacks,
    create_alignment_preview_model_callbacks,
    create_alignment_refresh_queue_callbacks,
    create_alignment_selected_part_control_callbacks,
    create_alignment_source_mix_callbacks,
    create_alignment_source_part_assignment_callbacks,
    create_alignment_source_role_tree_callbacks,
    create_alignment_source_tree_selection_callbacks,
    create_alignment_texture_detail_uv_callbacks,
    create_alignment_transform_drag_callbacks,
    create_manual_material_profile_runtime_callbacks,
    create_material_authority_adjustment_callbacks,
)
from cdmw.ui.archive_browser.static_replacement_dialog_texture_callbacks import (
    create_alignment_added_part_texture_callbacks,
    create_alignment_material_plan_column_callbacks,
    create_alignment_material_plan_final_preview_callbacks,
    create_alignment_original_texture_material_callbacks,
    create_alignment_texture_table_callbacks,
)
from cdmw.ui.archive_browser.static_replacement_dialog_routing_callbacks import (
    create_alignment_complete_swap_callbacks,
    create_alignment_dialog_layout_callbacks,
    create_alignment_original_clipboard_callbacks,
    create_alignment_original_texture_intent_callbacks,
    create_alignment_selection_clear_callbacks,
    create_alignment_selection_route_callbacks,
    create_alignment_source_part_geometry_action_callbacks,
    create_alignment_source_part_glow_callbacks,
    create_alignment_source_part_transform_control_callbacks,
    create_alignment_source_tree_role_callbacks,
)
from cdmw.ui.archive_browser.static_replacement_dialog_source_part_mutation_callbacks import (
    create_alignment_source_part_mutation_callbacks,
)
from cdmw.ui.archive_browser.static_replacement_dialog_mesh_edit_callbacks import (
    create_alignment_mesh_edit_callbacks,
)
from cdmw.ui.archive_browser.static_replacement_dialog_section_binding import (
    static_replacement_section_values,
)
from cdmw.ui.archive_browser.static_replacement_dialog_preview_shell import create_alignment_preview_shell_section
from cdmw.ui.archive_browser.static_replacement_dialog_workflow_shell import create_alignment_workflow_shell_section
from cdmw.ui.archive_browser.static_replacement_dialog_selection_mapping import (
    create_alignment_selection_mapping_helpers,
)
from cdmw.ui.archive_browser.static_replacement_dialog_ui_sections import (
    create_alignment_mesh_geometry_preview_section,
    create_alignment_setup_options_transform_section,
    create_alignment_source_parts_outliner_section,
    create_alignment_texture_material_section,
)
from cdmw.ui.archive_browser.static_replacement_dialog_remaining_callbacks import (
    create_alignment_preview_render_settings_callbacks,
    create_alignment_geometry_history_callbacks,
    create_alignment_mapping_edit_callbacks,
    create_alignment_original_source_filter_callbacks,
    create_alignment_original_reference_preview_callbacks,
    create_alignment_original_copy_payload_callbacks,
    create_alignment_original_part_copy_callbacks,
    create_alignment_source_role_flush_callbacks,
    create_alignment_selected_part_adjustment_callbacks,
    create_alignment_selected_part_glow_picker_callbacks,
    create_alignment_static_preview_refresh_callbacks,
    create_alignment_original_texture_worker_callbacks,
    create_alignment_added_part_texture_override_callbacks,
    create_alignment_added_part_texture_choice_callbacks,
    create_alignment_preview_pixmap_callbacks,
    create_alignment_source_material_plan_refresh_callbacks,
    create_alignment_complete_swap_profile_select_callbacks,
    create_alignment_manual_profile_preset_callbacks,
    create_alignment_manual_profile_control_callbacks,
    create_alignment_texture_orientation_callbacks,
    create_alignment_transform_slider_callbacks,
    create_alignment_transform_row_callbacks,
    create_alignment_modeless_dialog_callbacks,
    create_alignment_fit_dialog_callbacks,
)



from cdmw.ui.archive_browser.static_replacement_dialog_helpers import (
    alignment_file_signature as _alignment_file_signature,
    alignment_contract_preview_path as _alignment_contract_preview_path,
    alignment_sample_sequence as _alignment_sample_sequence,
    alignment_sequence_digest as _alignment_sequence_digest,
    default_texture_uv_transform_state as _default_texture_uv_transform_state,
    final_preview_binding_preview_status as _final_preview_binding_preview_status,
    final_preview_material_status_color as _final_preview_material_status_color,
    best_source_for_slot as _best_source_for_slot_helper,
    html_chip_span as _html_chip_span,
    binding_matches_target as _binding_matches_target_helper,
    important_static_texture_tokens as _important_static_texture_tokens,
    is_default_source_part_adjustment as _is_default_source_part_adjustment,
    is_gltf_metallic_roughness_path as _is_gltf_metallic_roughness_path,
    is_marker_source as _is_marker_source,
    mapping_source_cell_text as _mapping_source_cell_text,
    looks_like_standalone_pbr_source as _looks_like_standalone_pbr_source,
    material_contract_block as _material_contract_block,
    material_plan_summary_block as _material_plan_summary_block,
    material_routing_conflict_messages as _material_routing_conflict_messages_helper,
    material_route_status_color as _material_route_status_color,
    mesh_center_for_ui as _mesh_center_for_ui,
    model_bounds_x as _model_bounds_x,
    native_manifest_input_from_descriptor as _native_manifest_input_from_descriptor,
    part_specific_tokens as _part_specific_tokens_helper,
    rough_control_value_from_settings as _rough_control_value_from_settings,
    routing_source_material_labels as _routing_source_material_labels_helper,
    set_texture_row_assignment as _set_texture_row_assignment_helper,
    slot_kind_for_final_preview_row as _slot_kind_for_final_preview_row,
    source_indices_for_target_contract as _source_indices_for_target_contract_helper,
    source_material_group_label as _source_material_group_label_helper,
    source_material_names_for_mapping as _source_material_names_for_mapping_helper,
    source_material_output_path as _source_material_output_path,
    source_slot_for_texture_row as _source_slot_for_texture_row_helper,
    source_texture_evidence_by_local_path as _source_texture_evidence_by_local_path_helper,
    source_texture_path_for_plan_row as _source_texture_path_for_plan_row,
    source_texture_slot_count as _source_texture_slot_count_helper,
    tag_alignment_d3d11_workspace_model as _tag_alignment_d3d11_workspace_model,
    target_texture_status_details as _target_texture_status_details_helper,
    target_texture_status_text as _target_texture_status_text_helper,
    texture_assignment_summary_html as _texture_assignment_summary_html,
    texture_override_row_sort_key as _texture_override_row_sort_key,
    texture_plan_status_color as _texture_plan_status_color,
    texture_role_label_for_slot as _texture_role_label_for_slot,
    texture_row_can_apply_suggested_for_target as _texture_row_can_apply_suggested_for_target,
    texture_row_current_source_indices as _texture_row_current_source_indices_helper,
    texture_row_effective_source as _texture_row_effective_source_helper,
    texture_row_is_assigned as _texture_row_is_assigned_helper,
    texture_row_is_shared as _texture_row_is_shared,
    texture_row_override_key as _texture_row_override_key,
    texture_row_source_summary as _texture_row_source_summary_helper,
    texture_row_visible as _texture_row_visible_helper,
    texture_set_factor_parameters as _texture_set_factor_parameters,
    texture_set_for_source_index as _texture_set_for_source_index_helper,
    texture_file_lookup_maps as _texture_file_lookup_maps_helper,
    texture_source_choices_for_row as _texture_source_choices_for_row_helper,
    texture_summary_label_html as _texture_summary_label_html,
    texture_summary_metrics as _texture_summary_metrics,
    translated_preview_model as _translated_preview_model,
    sync_texture_row_assignment_state as _sync_texture_row_assignment_state_helper,
    texture_slot_contract_key as _texture_slot_contract_key,
    texture_source_key as _texture_source_key,
    texture_uv_state_has_edits as _texture_uv_state_has_edits,
    texture_uv_transform_key as _texture_uv_transform_key,
)
from cdmw.ui.archive_browser.static_replacement_virtual_texture_contract import (
    alignment_virtual_contract_preview_specs as _alignment_virtual_contract_preview_specs_helper,
    alignment_virtual_contract_rows as _alignment_virtual_contract_rows_helper,
    alignment_virtual_sidecar_contract_state as _alignment_virtual_sidecar_contract_state_helper,
    alignment_virtual_texture_contract_defaults as _alignment_virtual_texture_contract_defaults_helper,
    copied_source_texture_preview_specs as _copied_source_texture_preview_specs_helper,
    copied_source_texture_slot_overrides as _copied_source_texture_slot_overrides_helper,
    virtual_contract_sidecar_text_for_path as _virtual_contract_sidecar_text_for_path_helper,
)
from cdmw.ui.archive_browser.static_replacement_texture_rows import (
    resolve_dds_detail_preview_path as _resolve_dds_detail_preview_path_helper,
    selected_material_target_index as _selected_material_target_index_helper,
    target_material_name_for_index as _target_material_name_for_index_helper,
    texture_overrides_dirty_initial_state as _texture_overrides_dirty_initial_state_helper,
)
from cdmw.ui.mesh_editor.builder_host import MeshReplacementPartsOutlinerTree
from cdmw.ui.model_preview_native import ARCHIVE_MODEL_RENDERER_D3D11, normalize_archive_model_renderer_backend
from cdmw.ui.shell.diagnostics_controller import (
    d3d11_cache_event_user_label as _d3d11_cache_event_user_label,
    d3d11_status_file_signature as _d3d11_status_file_signature,
)
from cdmw.ui.widgets import CollapsibleSection, NativePreviewPanel, make_tree_columns_persistent
from cdmw.workers.archive_preview_native import NATIVE_PREVIEW_CORE_MODEL_EXTENSIONS
from cdmw.workers.d3d11_package_workers import AlignmentD3D11PackageWorker
from cdmw.workers.preview_workers import AlignmentOriginalTexturePreviewWorker


def install_static_replacement_prompt_callbacks_dependencies(namespace: dict[str, object]) -> None:
    namespace.update(
        {
            name: value
            for name, value in globals().items()
            if not name.startswith("__")
            and name != "install_static_replacement_prompt_callbacks_dependencies"
        }
    )


__all__ = ["install_static_replacement_prompt_callbacks_dependencies"]
