"""Mesh-edit and morph-slider callback factory for static replacement dialog."""

from __future__ import annotations

from collections.abc import Mapping as _MappingABC, Sequence as _SequenceABC
from types import SimpleNamespace

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.modding.static_mesh_replacer import (
    source_affine_for_transformed_preview as _default_source_affine_for_transformed_preview,
    source_normal_transform_for_transformed_preview as _default_source_normal_transform_for_transformed_preview,
)
from cdmw.ui.archive_browser.static_replacement_mesh_edit_state import (
    mesh_edit_has_inverse_transform_context as _default_mesh_edit_has_inverse_transform_context,
)
from cdmw.ui.archive_browser.static_replacement_sparse_history import (
    clear_mesh_history_snapshot_stack,
    release_mesh_history_snapshot,
    retain_mesh_history_snapshot,
)
from cdmw.ui.mesh_editor.controller import apply_native_update_to_host
from cdmw.ui.mesh_editor.native_preview_payloads import mesh_edit_selection_groups
from cdmw.ui.mesh_editor.static_replacement_adapter import StaticReplacementMeshEditSession
from cdmw.workers.mesh_editor_workers import MeshEditCommandWorker
_DEFAULT_INVERSE_TRANSFORM_HELPERS = {
    "source_affine_for_transformed_preview": _default_source_affine_for_transformed_preview,
    "source_normal_transform_for_transformed_preview": _default_source_normal_transform_for_transformed_preview,
}
_LEGACY_SCREEN_CAMERA_FIELDS = frozenset(
    {"camera_world", "yaw_degrees", "pitch_degrees", "distance", "vertical_fov_degrees", "pan"}
)


class _MeshEditDialogState:
    def __init__(self, context: dict[str, object]) -> None:
        self._get_replacement_mesh_for_mapping = context.get('_get_replacement_mesh_for_mapping')
        self._set_replacement_mesh_for_mapping = context.get('_set_replacement_mesh_for_mapping')
        self._get_replacement_mesh_base_for_mapping = context.get('_get_replacement_mesh_base_for_mapping')
        self._set_replacement_mesh_base_for_mapping = context.get('_set_replacement_mesh_base_for_mapping')
        self._get_replacement_preview_model = context.get('_get_replacement_preview_model')
        self._set_replacement_preview_model = context.get('_set_replacement_preview_model')

    @property
    def replacement_mesh_for_mapping(self):
        return self._get_replacement_mesh_for_mapping()

    @replacement_mesh_for_mapping.setter
    def replacement_mesh_for_mapping(self, value) -> None:
        self._set_replacement_mesh_for_mapping(value)

    @property
    def replacement_mesh_base_for_mapping(self):
        return self._get_replacement_mesh_base_for_mapping()

    @replacement_mesh_base_for_mapping.setter
    def replacement_mesh_base_for_mapping(self, value) -> None:
        self._set_replacement_mesh_base_for_mapping(value)

    @property
    def replacement_preview_model(self):
        return self._get_replacement_preview_model()

    @replacement_preview_model.setter
    def replacement_preview_model(self, value) -> None:
        self._set_replacement_preview_model(value)


def _native_screen_payload(payload: _MappingABC[object, object]) -> dict[object, object]:
    return {key: value for key, value in payload.items() if str(key) not in _LEGACY_SCREEN_CAMERA_FIELDS}


def create_alignment_mesh_edit_callbacks(context: dict[str, object]) -> SimpleNamespace:
    Dict = context.get('Dict')
    Iterable = context.get('Iterable')
    List = context.get('List')
    Mapping = context.get('Mapping')
    MeshMorphSliderDelta = context.get('MeshMorphSliderDelta')
    Optional = context.get('Optional')
    ParsedMesh = context.get('ParsedMesh')
    QDoubleSpinBox = context.get('QDoubleSpinBox')
    QFileDialog = context.get('QFileDialog')
    QFrame = context.get('QFrame')
    QGridLayout = context.get('QGridLayout')
    QInputDialog = context.get('QInputDialog')
    QLabel = context.get('QLabel')
    QMessageBox = context.get('QMessageBox')
    QProgressDialog = context.get('QProgressDialog')
    QPushButton = context.get('QPushButton')
    QSizePolicy = context.get('QSizePolicy')
    QSlider = context.get('QSlider')
    QTimer = context.get('QTimer')
    QThread = context.get('QThread')
    QWidget = context.get('QWidget')
    Qt = context.get('Qt')
    Sequence = context.get('Sequence')
    _alignment_d3d11_preview_active = context.get('_alignment_d3d11_preview_active')
    _alignment_d3d11_source_indices_for_editor_id_callback = context.get('_alignment_d3d11_source_indices_for_editor_id')
    _alignment_mesh_edit_tab_active = context.get('_alignment_mesh_edit_tab_active')
    classic_mesh_edit_action_bar = context.get('classic_mesh_edit_action_bar')
    classic_mesh_edit_toolbar = context.get('classic_mesh_edit_toolbar')
    compact_mesh_edit_status_label = context.get('compact_mesh_edit_status_label')
    compact_mesh_edit_clear_button = context.get('compact_mesh_edit_clear_button')
    compact_mesh_edit_grow_button = context.get('compact_mesh_edit_grow_button')
    compact_mesh_edit_shrink_button = context.get('compact_mesh_edit_shrink_button')
    compact_mesh_edit_feather_button = context.get('compact_mesh_edit_feather_button')
    compact_mesh_edit_reset_scope_button = context.get('compact_mesh_edit_reset_scope_button')
    compact_selection_mode_combo = context.get('compact_selection_mode_combo')
    compact_selection_depth_combo = context.get('compact_selection_depth_combo')
    prompt_shell_context = context.get('prompt_shell_context')
    source_skeleton = context.get('source_skeleton')

    def _context_or_prompt(name: str) -> object:
        value = context.get(name)
        if value is not None:
            return value
        if isinstance(prompt_shell_context, dict):
            return prompt_shell_context.get(name)
        return None

    def _mesh_edit_tab_active() -> bool:
        checkbox = _context_or_prompt("mesh_edit_enabled_checkbox")
        is_checked = getattr(checkbox, "isChecked", None)
        if callable(is_checked):
            return bool(is_checked())
        callback = _alignment_mesh_edit_tab_active
        if not callable(callback):
            callback = context.get('_alignment_mesh_edit_tab_active')
        if not callable(callback) and isinstance(prompt_shell_context, dict):
            callback = prompt_shell_context.get('_alignment_mesh_edit_tab_active')
        if not callable(callback):
            return False
        return bool(callback())

    def _alignment_d3d11_source_indices_for_editor_id(editor_id: int) -> tuple[int, ...]:
        callback = _alignment_d3d11_source_indices_for_editor_id_callback
        if not callable(callback):
            callback = context.get('_alignment_d3d11_source_indices_for_editor_id')
        if not callable(callback) and isinstance(prompt_shell_context, dict):
            callback = prompt_shell_context.get('_alignment_d3d11_source_indices_for_editor_id')
        if not callable(callback):
            return ()
        return tuple(int(index) for index in callback(editor_id) or () if int(index) >= 0)

    _d3d11_source_indices_for_editor_id = _alignment_d3d11_source_indices_for_editor_id

    _apply_alignment_dialog_responsive_layout = context.get('_apply_alignment_dialog_responsive_layout')
    _clear_alignment_d3d11_fast_transform_state = context.get('_clear_alignment_d3d11_fast_transform_state')
    _commit_spinbox_text = context.get('_commit_spinbox_text')
    _copy_source_part_with_adjustment = context.get('_copy_source_part_with_adjustment')
    _current_dialog_mappings_for_preview = context.get('_current_dialog_mappings_for_preview')
    _current_source_part_adjustments = context.get('_current_source_part_adjustments')
    _current_static_alignment_transform = context.get('_current_static_alignment_transform')
    _current_texture_uv_transforms = context.get('_current_texture_uv_transforms')
    _ensure_source_part_adjustment = context.get('_ensure_source_part_adjustment')
    _is_default_source_part_adjustment = context.get('_is_default_source_part_adjustment')
    _is_marker_source = context.get('_is_marker_source')
    _make_double_spin_helper = context.get('_make_double_spin_helper')
    _mapped_source_indices = context.get('_mapped_source_indices')
    _mesh_edit_all_live_vertices_for_sources_helper = context.get('_mesh_edit_all_live_vertices_for_sources_helper')
    _mesh_edit_all_vertices_by_source_helper = context.get('_mesh_edit_all_vertices_by_source_helper')
    _mesh_edit_allowed_source_indices_helper = context.get('_mesh_edit_allowed_source_indices_helper')
    _mesh_edit_apply_preview_mode_transition = context.get('_mesh_edit_apply_preview_mode_transition')
    _mesh_edit_blocked_title_helper = context.get('_mesh_edit_blocked_title_helper')
    _mesh_edit_can_edit_scope_helper = context.get('_mesh_edit_can_edit_scope_helper')
    _mesh_edit_control_status_text_helper = context.get('_mesh_edit_control_status_text_helper')
    _mesh_edit_delete_faces_text_helper = context.get('_mesh_edit_delete_faces_text_helper')
    _mesh_edit_deleted_faces_status_helper = context.get('_mesh_edit_deleted_faces_status_helper')
    _mesh_edit_deleted_selection_status_helper = context.get('_mesh_edit_deleted_selection_status_helper')
    _mesh_edit_dialog_title_helper = context.get('_mesh_edit_dialog_title_helper')
    _mesh_edit_distance_or_zero_helper = context.get('_mesh_edit_distance_or_zero_helper')
    _mesh_edit_editing_active_helper = context.get('_mesh_edit_editing_active_helper')
    _mesh_edit_editing_requested_helper = context.get('_mesh_edit_editing_requested_helper')
    _mesh_edit_enabled_snapshot_items_helper = context.get('_mesh_edit_enabled_snapshot_items_helper')
    _mesh_edit_full_reset_source_indices_helper = context.get('_mesh_edit_full_reset_source_indices_helper')
    _mesh_edit_has_index_groups_helper = context.get('_mesh_edit_has_index_groups_helper')
    _mesh_edit_has_inverse_transform_context_helper = context.get('_mesh_edit_has_inverse_transform_context_helper')
    if not callable(_mesh_edit_has_inverse_transform_context_helper):
        _mesh_edit_has_inverse_transform_context_helper = _default_mesh_edit_has_inverse_transform_context
    _mesh_edit_index_group_count_helper = context.get('_mesh_edit_index_group_count_helper')
    _mesh_edit_index_groups_as_sets_helper = context.get('_mesh_edit_index_groups_as_sets_helper')
    _mesh_edit_live_delete_status_helper = context.get('_mesh_edit_live_delete_status_helper')
    _mesh_edit_live_vertex_update_groups_helper = context.get('_mesh_edit_live_vertex_update_groups_helper')
    _mesh_edit_native_live_vertex_update_groups_helper = context.get('_mesh_edit_native_live_vertex_update_groups_helper')
    _mesh_edit_mapping_keys_helper = context.get('_mesh_edit_mapping_keys_helper')
    _mesh_edit_merge_index_groups_helper = context.get('_mesh_edit_merge_index_groups_helper')
    _mesh_edit_mesh_totals_helper = context.get('_mesh_edit_mesh_totals_helper')
    _mesh_edit_optional_sorted_indices_helper = context.get('_mesh_edit_optional_sorted_indices_helper')
    _mesh_edit_part_enabled_snapshot_helper = context.get('_mesh_edit_part_enabled_snapshot_helper')
    _mesh_edit_payload_choice_helper = context.get('_mesh_edit_payload_choice_helper')
    _mesh_edit_payload_edge_groups_helper = context.get('_mesh_edit_payload_edge_groups_helper')
    _mesh_edit_payload_float_helper = context.get('_mesh_edit_payload_float_helper')
    _mesh_edit_payload_has_drag_motion_helper = context.get('_mesh_edit_payload_has_drag_motion_helper')
    _mesh_edit_payload_int_helper = context.get('_mesh_edit_payload_int_helper')
    _mesh_edit_payload_native_vertex_groups_helper = context.get('_mesh_edit_payload_native_vertex_groups_helper')
    _mesh_edit_payload_selected_indices_helper = context.get('_mesh_edit_payload_selected_indices_helper')
    _mesh_edit_payload_vector3_helper = context.get('_mesh_edit_payload_vector3_helper')
    _mesh_edit_payload_vertex_groups_helper = context.get('_mesh_edit_payload_vertex_groups_helper')
    _mesh_edit_cleanup_native_vertex_group_descriptors_helper = context.get('_mesh_edit_cleanup_native_vertex_group_descriptors_helper')
    _mesh_edit_pending_live_normals_initial_state_helper = context.get('_mesh_edit_pending_live_normals_initial_state_helper')
    _mesh_edit_pruned_index_groups_helper = context.get('_mesh_edit_pruned_index_groups_helper')
    _mesh_edit_queue_live_vertex_updates_helper = context.get('_mesh_edit_queue_live_vertex_updates_helper')
    _mesh_edit_requested_source_indices_helper = context.get('_mesh_edit_requested_source_indices_helper')
    _mesh_edit_reset_available_helper = context.get('_mesh_edit_reset_available_helper')
    _mesh_edit_reset_scope_source_indices_helper = context.get('_mesh_edit_reset_scope_source_indices_helper')
    _mesh_edit_scope_mode_helper = context.get('_mesh_edit_scope_mode_helper')
    _mesh_edit_selection_depth_mode_helper = context.get('_mesh_edit_selection_depth_mode_helper')
    _mesh_edit_selection_mode_helper = context.get('_mesh_edit_selection_mode_helper')
    _mesh_edit_selection_region_default_amount_helper = context.get('_mesh_edit_selection_region_default_amount_helper')
    _mesh_edit_selection_status_text_helper = context.get('_mesh_edit_selection_status_text_helper')
    _mesh_edit_should_restore_deleted_output_helper = context.get('_mesh_edit_should_restore_deleted_output_helper')
    _mesh_edit_refined_selection_status_helper = context.get('_mesh_edit_refined_selection_status_helper')
    _mesh_edit_split_selection_status_helper = context.get('_mesh_edit_split_selection_status_helper')
    _mesh_edit_split_text_helper = context.get('_mesh_edit_split_text_helper')
    _mesh_edit_sorted_index_groups_helper = context.get('_mesh_edit_sorted_index_groups_helper')
    _mesh_edit_source_index_helper = context.get('_mesh_edit_source_index_helper')
    _mesh_edit_source_index_is_editable_helper = context.get('_mesh_edit_source_index_is_editable_helper')
    _mesh_edit_source_indices_helper = context.get('_mesh_edit_source_indices_helper')
    _mesh_edit_source_to_preview_point_helper = context.get('_mesh_edit_source_to_preview_point_helper')
    _mesh_edit_stroke_id_helper = context.get('_mesh_edit_stroke_id_helper')
    _mesh_edit_subdivide_text_helper = context.get('_mesh_edit_subdivide_text_helper')
    _mesh_edit_subdivided_selection_status_helper = context.get('_mesh_edit_subdivided_selection_status_helper')
    _mesh_edit_target_mode_for_tool_helper = context.get('_mesh_edit_target_mode_for_tool_helper')
    _mesh_edit_tool_context_helper = context.get('_mesh_edit_tool_context_helper')
    _mesh_edit_tool_helper = context.get('_mesh_edit_tool_helper')
    _mesh_edit_topology_changed_status_helper = context.get('_mesh_edit_topology_changed_status_helper')
    _mesh_edit_topology_source_indices_helper = context.get('_mesh_edit_topology_source_indices_helper')
    _mesh_edit_triangle_replace_groups_helper = context.get('_mesh_edit_triangle_replace_groups_helper')
    _mesh_edit_vector3_or_zero_helper = context.get('_mesh_edit_vector3_or_zero_helper')
    _morph_slider_active_deltas_helper = context.get('_morph_slider_active_deltas_helper')
    _morph_slider_add_target_action_text_helper = context.get('_morph_slider_add_target_action_text_helper')
    _morph_slider_add_target_route_state_helper = context.get('_morph_slider_add_target_route_state_helper')
    _morph_slider_added_status_text_helper = context.get('_morph_slider_added_status_text_helper')
    _morph_slider_amount_prompt_text_helper = context.get('_morph_slider_amount_prompt_text_helper')
    _morph_slider_bake_state_helper = context.get('_morph_slider_bake_state_helper')
    _morph_slider_capture_post_edit_deltas_helper = context.get('_morph_slider_capture_post_edit_deltas_helper')
    _morph_slider_control_state_helper = context.get('_morph_slider_control_state_helper')
    _morph_slider_create_action_text_helper = context.get('_morph_slider_create_action_text_helper')
    _morph_slider_create_route_state_helper = context.get('_morph_slider_create_route_state_helper')
    _morph_slider_created_status_text_helper = context.get('_morph_slider_created_status_text_helper')
    _morph_slider_default_name_text_helper = context.get('_morph_slider_default_name_text_helper')
    _morph_slider_expected_vertex_counts_helper = context.get('_morph_slider_expected_vertex_counts_helper')
    _morph_slider_feather_prompt_text_helper = context.get('_morph_slider_feather_prompt_text_helper')
    _morph_slider_has_loaded_deltas_helper = context.get('_morph_slider_has_loaded_deltas_helper')
    _morph_slider_has_nonzero_values_helper = context.get('_morph_slider_has_nonzero_values_helper')
    _morph_slider_import_action_text_helper = context.get('_morph_slider_import_action_text_helper')
    _morph_slider_import_route_state_helper = context.get('_morph_slider_import_route_state_helper')
    _morph_slider_imported_status_text_helper = context.get('_morph_slider_imported_status_text_helper')
    _morph_slider_name_prompt_text_helper = context.get('_morph_slider_name_prompt_text_helper')
    _morph_slider_post_edit_deltas_need_reset_helper = context.get('_morph_slider_post_edit_deltas_need_reset_helper')
    _morph_slider_reload_state_helper = context.get('_morph_slider_reload_state_helper')
    _morph_slider_reset_state_helper = context.get('_morph_slider_reset_state_helper')
    _morph_slider_row_state_helper = context.get('_morph_slider_row_state_helper')
    _morph_slider_row_sync_states_helper = context.get('_morph_slider_row_sync_states_helper')
    _morph_slider_status_text_helper = context.get('_morph_slider_status_text_helper')
    _morph_slider_supported_helper = context.get('_morph_slider_supported_helper')
    _morph_slider_target_mesh_file_filter_helper = context.get('_morph_slider_target_mesh_file_filter_helper')
    _morph_slider_topology_changed_reason_text_helper = context.get('_morph_slider_topology_changed_reason_text_helper')
    _morph_slider_unique_slider_id_helper = context.get('_morph_slider_unique_slider_id_helper')
    _morph_slider_value_commit_state_helper = context.get('_morph_slider_value_commit_state_helper')
    _morph_slider_value_or_default_helper = context.get('_morph_slider_value_or_default_helper')
    _morph_slider_zero_post_edit_deltas_for_sources_helper = context.get('_morph_slider_zero_post_edit_deltas_for_sources_helper')
    _morph_slider_zero_post_edit_deltas_helper = context.get('_morph_slider_zero_post_edit_deltas_helper')
    _pop_geometry_undo_snapshot = context.get('_pop_geometry_undo_snapshot')
    _push_geometry_undo_snapshot = context.get('_push_geometry_undo_snapshot')
    _push_geometry_sparse_mesh_edit_snapshot = context.get('_push_geometry_sparse_mesh_edit_snapshot')
    _rebuild_source_part_widgets = context.get('_rebuild_source_part_widgets')
    _alignment_d3d11_invalidate_package_cache = context.get('_alignment_d3d11_invalidate_package_cache')
    _mark_alignment_d3d11_rebuild_reason = context.get('_mark_alignment_d3d11_rebuild_reason')
    _queue_static_preview_rebuild = context.get('_queue_static_preview_rebuild')
    _queue_texture_preview_refresh = context.get('_queue_texture_preview_refresh')
    _record_runtime_event = context.get('_record_runtime_event')
    _refresh_source_assignment_columns = context.get('_refresh_source_assignment_columns')
    _refresh_source_tree_selection_state = context.get('_refresh_source_tree_selection_state')
    _safe_refresh_static_dialog_preview = context.get('_safe_refresh_static_dialog_preview')
    _delete_selected_source_parts = context.get('_delete_selected_source_parts')
    _source_display_name = context.get('_source_display_name')
    _source_index_is_enabled_renderable = context.get('_source_index_is_enabled_renderable')
    _transformed_replacement_sources = context.get('_transformed_replacement_sources')
    _current_complete_swap_material_profile_token = context.get('_current_complete_swap_material_profile_token')
    alignment_d3d11_preview_host = context.get('alignment_d3d11_preview_host')
    appended_source_indices = context.get('appended_source_indices')
    mesh_editor_static_replacement_session_state = context.get('mesh_editor_static_replacement_session_state')
    if not isinstance(mesh_editor_static_replacement_session_state, dict):
        mesh_editor_static_replacement_session_state = {}
    mesh_edit_preview_model_dirty = {"value": False}
    mesh_edit_native_result_submesh_counts = {"value": ()}
    apply_morph_slider_values = context.get('apply_morph_slider_values')
    assert_mesh_topology_unchanged = context.get('assert_mesh_topology_unchanged')
    control_tabs = context.get('control_tabs')
    copy = context.get('copy')
    create_region_volume_slider_profile = context.get('create_region_volume_slider_profile')
    dialog = context.get('dialog')
    entry = context.get('entry')
    import_body_slider_profile = context.get('import_body_slider_profile')
    import_single_morph_slider_profile = context.get('import_single_morph_slider_profile')
    load_morph_slider_delta = context.get('load_morph_slider_delta')
    load_morph_slider_profiles = context.get('load_morph_slider_profiles')
    mesh_edit_action_control_text = context.get('mesh_edit_action_control_text')
    mesh_edit_active_stroke = context.get('mesh_edit_active_stroke')
    mesh_edit_button_row = context.get('mesh_edit_button_row')
    mesh_edit_clear_selection_button = context.get('mesh_edit_clear_selection_button')
    mesh_edit_delete_faces_button = context.get('mesh_edit_delete_faces_button')
    mesh_edit_delete_mode_combo = context.get('mesh_edit_delete_mode_combo')
    mesh_edit_enabled_checkbox = context.get('mesh_edit_enabled_checkbox')
    mesh_edit_falloff_combo = context.get('mesh_edit_falloff_combo')
    mesh_edit_field_rows = context.get('mesh_edit_field_rows')
    mesh_edit_full_reset_button = context.get('mesh_edit_full_reset_button')
    mesh_edit_group = context.get('mesh_edit_group')
    mesh_edit_grow_selection_button = context.get('mesh_edit_grow_selection_button')
    mesh_edit_invert_selection_button = context.get('mesh_edit_invert_selection_button')
    mesh_edit_iterations_spin = context.get('mesh_edit_iterations_spin')
    mesh_edit_layout = context.get('mesh_edit_layout')
    mesh_edit_mirror_checkbox = context.get('mesh_edit_mirror_checkbox')
    mesh_edit_option_widget = context.get('mesh_edit_option_widget')
    mesh_edit_part_combo = context.get('mesh_edit_part_combo')
    mesh_edit_radius_spin = context.get('mesh_edit_radius_spin')
    mesh_edit_redo_adjustment_stack = context.get('mesh_edit_redo_adjustment_stack')
    mesh_edit_redo_button = context.get('mesh_edit_redo_button')
    mesh_edit_redo_stack = context.get('mesh_edit_redo_stack')
    mesh_edit_remove_mode_label = context.get('mesh_edit_remove_mode_label')
    mesh_edit_refine_smooth_selection_button = context.get('mesh_edit_refine_smooth_selection_button')
    mesh_edit_reset_part_button = context.get('mesh_edit_reset_part_button')
    mesh_edit_revision = context.get('mesh_edit_revision')
    mesh_edit_scope_combo = context.get('mesh_edit_scope_combo')
    mesh_edit_select_part_button = context.get('mesh_edit_select_part_button')
    mesh_edit_selected_faces_by_submesh = context.get('mesh_edit_selected_faces_by_submesh')
    mesh_edit_selected_edges_by_submesh: dict[int, set[tuple[int, int]]] = {}
    mesh_edit_selected_source_indices = context.get('mesh_edit_selected_source_indices')
    if not isinstance(mesh_edit_selected_source_indices, set):
        mesh_edit_selected_source_indices = set()
    mesh_edit_selected_vertices_by_submesh = context.get('mesh_edit_selected_vertices_by_submesh')
    mesh_edit_selection_actions_widget = context.get('mesh_edit_selection_actions_widget')
    mesh_edit_selection_depth_combo = context.get('mesh_edit_selection_depth_combo')
    mesh_edit_selection_mode_combo = context.get('mesh_edit_selection_mode_combo')
    mesh_edit_show_vertices_checkbox = context.get('mesh_edit_show_vertices_checkbox')
    mesh_edit_shrink_selection_button = context.get('mesh_edit_shrink_selection_button')
    mesh_edit_smooth_selection_button = context.get('mesh_edit_smooth_selection_button')
    mesh_edit_split_selection_button = context.get('mesh_edit_split_selection_button')
    mesh_edit_status_label = context.get('mesh_edit_status_label')
    mesh_edit_strength_spin = context.get('mesh_edit_strength_spin')
    mesh_edit_subdivide_selection_button = context.get('mesh_edit_subdivide_selection_button')
    mesh_edit_supported = context.get('mesh_edit_supported')
    mesh_edit_tab = context.get('mesh_edit_tab')
    mesh_edit_tool_buttons = context.get('mesh_edit_tool_buttons')
    mesh_edit_tool_combo = context.get('mesh_edit_tool_combo')
    mesh_edit_tool_palette = context.get('mesh_edit_tool_palette')
    mesh_edit_undo_adjustment_stack = context.get('mesh_edit_undo_adjustment_stack')
    mesh_edit_undo_button = context.get('mesh_edit_undo_button')
    mesh_edit_undo_stack = context.get('mesh_edit_undo_stack')
    mesh_topology_signature = context.get('mesh_topology_signature')
    modify_original_clone_mode = context.get('modify_original_clone_mode')
    morph_slider_add_action = context.get('morph_slider_add_action')
    morph_slider_bake_button = context.get('morph_slider_bake_button')
    morph_slider_change_active = context.get('morph_slider_change_active')
    morph_slider_create_button = context.get('morph_slider_create_button')
    morph_slider_deltas = context.get('morph_slider_deltas')
    morph_slider_group = context.get('morph_slider_group')
    morph_slider_import_action = context.get('morph_slider_import_action')
    morph_slider_manage_button = context.get('morph_slider_manage_button')
    morph_slider_post_edit_deltas = context.get('morph_slider_post_edit_deltas')
    morph_slider_profile_root = context.get('morph_slider_profile_root')
    morph_slider_profiles = context.get('morph_slider_profiles')
    morph_slider_reload_action = context.get('morph_slider_reload_action')
    morph_slider_reset_button = context.get('morph_slider_reset_button')
    morph_slider_rows = context.get('morph_slider_rows')
    morph_slider_rows_layout = context.get('morph_slider_rows_layout')
    morph_slider_rows_widget = context.get('morph_slider_rows_widget')
    morph_slider_status_label = context.get('morph_slider_status_label')
    morph_slider_topology_blocked = context.get('morph_slider_topology_blocked')
    morph_slider_update_guard = context.get('morph_slider_update_guard')
    morph_slider_values = context.get('morph_slider_values')
    original_mesh_for_mapping = context.get('original_mesh_for_mapping')
    original_reference_preview_model = context.get('original_reference_preview_model')
    overlay_dialog_preview = context.get('overlay_dialog_preview')
    parsed_mesh_to_preview_model = context.get('parsed_mesh_to_preview_model')
    replacement_only_preview = context.get('replacement_only_preview')
    selected_source_part = context.get('selected_source_part')
    self = context.get('self')
    source_items_by_index = context.get('source_items_by_index')
    source_geometry_revision = context.get('source_geometry_revision')
    if source_geometry_revision is None:
        source_geometry_revision = {}
    source_part_adjustments = context.get('source_part_adjustments')
    source_affine_for_transformed_preview = _context_or_prompt('source_affine_for_transformed_preview')
    if not callable(source_affine_for_transformed_preview):
        source_affine_for_transformed_preview = _default_source_affine_for_transformed_preview
    source_normal_transform_for_transformed_preview = _context_or_prompt('source_normal_transform_for_transformed_preview')
    if not callable(source_normal_transform_for_transformed_preview):
        source_normal_transform_for_transformed_preview = _default_source_normal_transform_for_transformed_preview
    source_tree = context.get('source_tree')
    source_tree_item_update_guard = context.get('source_tree_item_update_guard')
    static_dialog_preview = context.get('static_dialog_preview')
    static_preview_geometry_cache = context.get('static_preview_geometry_cache')
    static_preview_prepared_cache = context.get('static_preview_prepared_cache')
    validate_morph_target = context.get('validate_morph_target')
    _mesh_edit_state = _MeshEditDialogState(context)
    mesh_edit_button_row.addStretch(1)
    mesh_edit_layout.addLayout(mesh_edit_button_row)
    mesh_edit_layout.addWidget(mesh_edit_reset_part_button)
    mesh_edit_layout.addWidget(mesh_edit_full_reset_button)
    mesh_edit_layout.addWidget(mesh_edit_status_label)

    _mesh_edit_scope_mode = lambda: _mesh_edit_scope_mode_helper(mesh_edit_scope_combo.currentData())
    _mesh_edit_current_tool = lambda: _mesh_edit_tool_helper(mesh_edit_tool_combo.currentData())
    mesh_editor_action_bar_selection_mode = {"value": "vertex"}
    mesh_editor_action_bar_active_tool_key = {"value": "brush_grab"}
    def _mesh_edit_target_mode_for_tool() -> str:
        if str(mesh_editor_action_bar_active_tool_key.get("value") or "") == "transform_move":
            return "selection"
        if _mesh_edit_current_tool() == "vertex":
            return str(mesh_editor_action_bar_selection_mode.get("value") or "vertex")
        return _mesh_edit_target_mode_for_tool_helper(_mesh_edit_current_tool())
    _mesh_edit_selection_mode = lambda: _mesh_edit_selection_mode_helper(mesh_edit_selection_mode_combo.currentData())
    _mesh_edit_selection_depth_mode = lambda: _mesh_edit_selection_depth_mode_helper(mesh_edit_selection_depth_combo.currentData())
    _mesh_edit_selected_source_index = lambda: _mesh_edit_source_index_helper(selected_source_part.get("index", -1))
    _mesh_edit_selected_scope_source_index = lambda: _mesh_edit_source_index_helper(
        mesh_edit_part_combo.currentData(),
        fallback=_mesh_edit_selected_source_index(),
    )

    _mesh_edit_base_source_index_is_editable = lambda source_index: _mesh_edit_source_index_is_editable_helper(
        _mesh_edit_state.replacement_mesh_base_for_mapping or _mesh_edit_state.replacement_mesh_for_mapping,
        source_index,
        is_marker_source=_is_marker_source,
    )
    _mesh_edit_source_index_is_editable = lambda source_index, *, require_enabled=True: _mesh_edit_source_index_is_editable_helper(
        _mesh_edit_state.replacement_mesh_for_mapping,
        source_index,
        is_marker_source=_is_marker_source,
        is_enabled_renderable=(
            lambda source_index: _source_index_is_enabled_renderable(source_index)
        ) if require_enabled else None,
    )

    def _refresh_mesh_edit_part_combo() -> None:
        previous = _mesh_edit_selected_scope_source_index()
        fallback = _mesh_edit_selected_source_index()
        mesh_edit_part_combo.blockSignals(True)
        try:
            mesh_edit_part_combo.clear()
            if _mesh_edit_state.replacement_mesh_for_mapping is None:
                mesh_edit_part_combo.addItem(mesh_edit_action_control_text["no_editable_parts"], -1)
                return
            editable_indices = list(
                _mesh_edit_source_indices_helper(
                    _mesh_edit_state.replacement_mesh_for_mapping,
                    _mesh_edit_base_source_index_is_editable,
                )
            )
            if not editable_indices:
                mesh_edit_part_combo.addItem(mesh_edit_action_control_text["no_editable_parts"], -1)
                return
            for source_index in editable_indices:
                mesh_edit_part_combo.addItem(_source_display_name(int(source_index)), int(source_index))
            target_index = previous if previous in editable_indices else fallback
            if target_index not in editable_indices:
                target_index = editable_indices[0]
            combo_index = mesh_edit_part_combo.findData(int(target_index))
            if combo_index >= 0:
                mesh_edit_part_combo.setCurrentIndex(combo_index)
        finally:
            mesh_edit_part_combo.blockSignals(False)

    _mesh_edit_allowed_source_indices = lambda *, require_enabled=True: _mesh_edit_allowed_source_indices_helper(
        _mesh_edit_state.replacement_mesh_for_mapping,
        scope_mode=_mesh_edit_scope_mode(),
        selected_scope_source_index=_mesh_edit_selected_scope_source_index(),
        is_source_index_editable=lambda source_index: _mesh_edit_source_index_is_editable(
            source_index,
            require_enabled=require_enabled,
        ),
    )

    def _mesh_edit_selected_source_indices(*, allowed_indices: set[int] | None = None) -> tuple[int, ...]:
        allowed = allowed_indices if allowed_indices is not None else set(_mesh_edit_allowed_source_indices())
        return tuple(sorted(index for index in mesh_edit_selected_source_indices if index in allowed))

    def _mesh_edit_selected_source_vertex_count(*, allowed_indices: set[int] | None = None) -> int:
        mesh = _mesh_edit_state.replacement_mesh_for_mapping
        if mesh is None:
            return 0
        submeshes = getattr(mesh, "submeshes", ()) or ()
        total = 0
        for source_index in _mesh_edit_selected_source_indices(allowed_indices=allowed_indices):
            if 0 <= source_index < len(submeshes):
                total += len(getattr(submeshes[source_index], "vertices", ()) or ())
        return total

    def _mesh_editor_current_edit_revision() -> int:
        if not isinstance(mesh_edit_revision, dict):
            return -1
        try:
            return int(mesh_edit_revision.get("value", 0) or 0)
        except (TypeError, ValueError):
            return -1

    def _mesh_editor_clear_static_replacement_session() -> None:
        old_session = mesh_editor_static_replacement_session_state.get("session")
        if isinstance(old_session, StaticReplacementMeshEditSession):
            old_session.close()
        mesh_editor_static_replacement_session_state.clear()

    def _mesh_editor_ensure_static_replacement_session(mesh=None):
        source_mesh = mesh if mesh is not None else _mesh_edit_state.replacement_mesh_for_mapping
        current_revision = _mesh_editor_current_edit_revision()
        if source_mesh is None or current_revision < 0:
            return None
        session = mesh_editor_static_replacement_session_state.get("session")
        if (
            not isinstance(session, StaticReplacementMeshEditSession)
            or mesh_editor_static_replacement_session_state.get("mesh") is not source_mesh
            or mesh_editor_static_replacement_session_state.get("revision") != current_revision
        ):
            _mesh_editor_clear_static_replacement_session()
            session = StaticReplacementMeshEditSession(session_id="static-replacement")
            session.open(source_mesh)
            if source_skeleton is not None:
                try:
                    session.controller.attach_skeleton(
                        source_skeleton,
                        source_path=str(getattr(source_skeleton, "path", "") or ""),
                    )
                except Exception:
                    pass
            mesh_editor_static_replacement_session_state["session"] = session
            mesh_editor_static_replacement_session_state["mesh"] = source_mesh
            mesh_editor_static_replacement_session_state["revision"] = current_revision
            mesh_edit_native_result_submesh_counts["value"] = ()
        return session

    def _mesh_editor_result_has_deferred_native_python_apply(result: object) -> bool:
        edit_result = getattr(result, "edit_result", None)
        metrics = getattr(edit_result, "metrics", {}) if edit_result is not None else {}
        try:
            return float(metrics.get("python_apply_deferred", 0.0) or 0.0) == 1.0
        except (TypeError, ValueError):
            return False

    def _mesh_editor_result_mesh_for_state(result: object, fallback: object | None = None) -> object | None:
        if _mesh_editor_result_has_deferred_native_python_apply(result):
            return fallback if fallback is not None else _mesh_edit_state.replacement_mesh_for_mapping
        return getattr(result, "mesh", fallback)

    def _mesh_editor_result_submesh_counts(result: object) -> tuple[tuple[int, int], ...]:
        edit_result = getattr(result, "edit_result", None)
        raw_counts = getattr(edit_result, "submesh_counts", ()) if edit_result is not None else ()
        counts: list[tuple[int, int]] = []
        for raw_count in tuple(raw_counts or ()):
            try:
                vertex_count, face_count = raw_count
                counts.append((max(0, int(vertex_count)), max(0, int(face_count))))
            except (TypeError, ValueError):
                return ()
        return tuple(counts)

    def _mesh_editor_result_changes_mesh(result: object) -> bool:
        return bool(
            getattr(result, "affected_submesh_indices", None)
            or getattr(result, "changed_vertices_by_submesh", None)
            or getattr(result, "added_face_count", 0)
            or getattr(result, "removed_face_count", 0)
            or getattr(result, "moved_face_count", 0)
            or getattr(result, "material_override_groups", None)
        )

    def _mesh_editor_store_result_mesh(result: object, fallback: object | None = None) -> bool:
        mesh = _mesh_editor_result_mesh_for_state(result, fallback)
        if mesh is None:
            return False
        _mesh_edit_state.replacement_mesh_for_mapping = mesh
        counts = _mesh_editor_result_submesh_counts(result)
        mesh_edit_native_result_submesh_counts["value"] = counts if _mesh_editor_result_has_deferred_native_python_apply(result) else ()
        return True

    def _mesh_editor_apply_static_replacement_edit(mesh, action: str, **params: object):
        current_revision = _mesh_editor_current_edit_revision()
        if current_revision < 0:
            raise RuntimeError("active static Mesh Editor edit requires a native session revision")
        session = _mesh_editor_ensure_static_replacement_session(mesh)
        if session is None:
            raise RuntimeError("active static Mesh Editor edit requires a native session")
        result = session.apply(action, **params)
        changed = _mesh_editor_result_changes_mesh(result)
        mesh_editor_static_replacement_session_state["mesh"] = _mesh_editor_result_mesh_for_state(result, mesh)
        mesh_editor_static_replacement_session_state["revision"] = current_revision + (1 if changed else 0)
        return result

    def _mesh_editor_fresh_static_replacement_session():
        if _mesh_edit_state.replacement_mesh_for_mapping is None:
            return None
        current_revision = _mesh_editor_current_edit_revision()
        if current_revision < 0:
            return None
        session = mesh_editor_static_replacement_session_state.get("session")
        if not isinstance(session, StaticReplacementMeshEditSession):
            return None
        if (
            mesh_editor_static_replacement_session_state.get("mesh") is not _mesh_edit_state.replacement_mesh_for_mapping
            or mesh_editor_static_replacement_session_state.get("revision") != current_revision
        ):
            return None
        try:
            session.view()
        except (KeyError, RuntimeError):
            return None
        return session

    def _mesh_editor_remember_static_replacement_session_mesh() -> None:
        mesh_editor_static_replacement_session_state["mesh"] = _mesh_edit_state.replacement_mesh_for_mapping
        mesh_editor_static_replacement_session_state["revision"] = _mesh_editor_current_edit_revision()

    def _mesh_edit_commit_geometry_preview_state() -> None:
        _mesh_editor_remember_static_replacement_session_mesh()
        static_preview_geometry_cache.clear()
        static_preview_prepared_cache.clear()
        if callable(_mark_alignment_d3d11_rebuild_reason):
            _mark_alignment_d3d11_rebuild_reason("geometry")
        if callable(_alignment_d3d11_invalidate_package_cache):
            _alignment_d3d11_invalidate_package_cache("geometry")

    def _mesh_edit_refresh_replacement_preview_model(
        *,
        allow_defer_for_incremental_d3d11: bool = False,
    ) -> bool:
        if _mesh_edit_state.replacement_mesh_for_mapping is None or not callable(parsed_mesh_to_preview_model):
            return False
        if (
            allow_defer_for_incremental_d3d11
            and _mesh_edit_tab_active()
            and not _alignment_d3d11_preview_active()
        ):
            self.set_status_message(
                "Active Mesh Editor preview refresh requires native D3D11; Python preview rebuild fallback is disabled.",
                error=True,
            )
            return False
        if tuple(mesh_edit_native_result_submesh_counts.get("value") or ()):
            if allow_defer_for_incremental_d3d11 and _alignment_d3d11_preview_active():
                mesh_edit_preview_model_dirty["value"] = True
                return False
            raise RuntimeError("native deferred edit cannot rebuild Python preview model; Python preview rebuild fallback is disabled")
        if (
            allow_defer_for_incremental_d3d11
            and _mesh_edit_tab_active()
            and _alignment_d3d11_preview_active()
        ):
            mesh_edit_preview_model_dirty["value"] = True
            return False
        _mesh_edit_state.replacement_preview_model = parsed_mesh_to_preview_model(
            _mesh_edit_state.replacement_mesh_for_mapping
        )
        mesh_edit_preview_model_dirty["value"] = False
        return True

    _mesh_edit_preview_source_indices = lambda *, require_enabled=True: _mesh_edit_source_indices_helper(
        _mesh_edit_state.replacement_mesh_for_mapping,
        lambda source_index: _mesh_edit_source_index_is_editable(
            source_index,
            require_enabled=require_enabled,
        ),
    )

    _morph_slider_supported = lambda: _morph_slider_supported_helper(
        modify_original_clone_mode=modify_original_clone_mode,
        has_base_mesh=_mesh_edit_state.replacement_mesh_base_for_mapping is not None,
        has_working_mesh=_mesh_edit_state.replacement_mesh_for_mapping is not None,
    )
    _morph_slider_has_loaded_deltas = lambda: _morph_slider_has_loaded_deltas_helper(morph_slider_deltas)
    _morph_slider_has_nonzero_values = lambda: _morph_slider_has_nonzero_values_helper(morph_slider_values)
    _morph_slider_zero_post_edit_deltas = lambda: _morph_slider_zero_post_edit_deltas_helper(
        _mesh_edit_state.replacement_mesh_base_for_mapping
    )

    def _morph_slider_ensure_post_edit_deltas() -> None:
        if _mesh_edit_state.replacement_mesh_base_for_mapping is None:
            morph_slider_post_edit_deltas.clear()
            return
        expected_counts = _morph_slider_expected_vertex_counts_helper(_mesh_edit_state.replacement_mesh_base_for_mapping)
        if _morph_slider_post_edit_deltas_need_reset_helper(morph_slider_post_edit_deltas, expected_counts):
            morph_slider_post_edit_deltas[:] = _morph_slider_zero_post_edit_deltas()

    def _morph_slider_zero_post_edit_deltas_for_sources(source_indices: Sequence[int]) -> None:
        _morph_slider_ensure_post_edit_deltas()
        _morph_slider_zero_post_edit_deltas_for_sources_helper(morph_slider_post_edit_deltas, source_indices)

    def _morph_slider_mark_topology_changed(reason: str) -> None:
        morph_slider_topology_blocked["blocked"] = True
        morph_slider_topology_blocked["reason"] = str(
            reason or _morph_slider_topology_changed_reason_text_helper()
        )
        _morph_slider_refresh_controls()

    def _morph_slider_refresh_topology_block_state() -> bool:
        if _mesh_edit_state.replacement_mesh_base_for_mapping is None or _mesh_edit_state.replacement_mesh_for_mapping is None:
            return False
        try:
            validate_morph_target(_mesh_edit_state.replacement_mesh_base_for_mapping, _mesh_edit_state.replacement_mesh_for_mapping)
        except Exception as exc:
            morph_slider_topology_blocked["blocked"] = True
            morph_slider_topology_blocked["reason"] = str(exc)
            return False
        morph_slider_topology_blocked["blocked"] = False
        morph_slider_topology_blocked["reason"] = ""
        return True

    def _morph_slider_active_deltas() -> tuple[MeshMorphSliderDelta, ...]:
        return _morph_slider_active_deltas_helper(morph_slider_deltas)

    def _morph_slider_slider_only_mesh() -> Optional[ParsedMesh]:
        if _mesh_edit_state.replacement_mesh_base_for_mapping is None:
            return None
        return apply_morph_slider_values(
            _mesh_edit_state.replacement_mesh_base_for_mapping,
            _morph_slider_active_deltas(),
            morph_slider_values,
        )

    def _morph_slider_capture_post_edit_deltas() -> None:
        if not _morph_slider_has_loaded_deltas() or _mesh_edit_state.replacement_mesh_base_for_mapping is None or _mesh_edit_state.replacement_mesh_for_mapping is None:
            return
        if not _morph_slider_refresh_topology_block_state():
            return
        slider_only_mesh = _morph_slider_slider_only_mesh()
        if slider_only_mesh is None:
            return
        try:
            morph_slider_post_edit_deltas[:] = _morph_slider_capture_post_edit_deltas_helper(
                _mesh_edit_state.replacement_mesh_for_mapping,
                slider_only_mesh,
            )
        except Exception as exc:
            morph_slider_topology_blocked["blocked"] = True
            morph_slider_topology_blocked["reason"] = str(exc)
            self.set_status_message(str(exc))
            _morph_slider_refresh_controls()

    def _morph_slider_apply_to_working_mesh(
        *,
        increment_revision: bool = True,
        refresh_controls: bool = True,
        status_message: str = "",
    ) -> bool:
        if _mesh_edit_state.replacement_mesh_base_for_mapping is None:
            return False
        if _mesh_edit_tab_active():
            _mesh_edit_mark_native_preview_stale(
                "Active Mesh Editor morph-slider apply requires native geometry execution; Python mesh mutation fallback is disabled."
            )
            return False
        _morph_slider_ensure_post_edit_deltas()
        try:
            _mesh_edit_state.replacement_mesh_for_mapping = apply_morph_slider_values(
                _mesh_edit_state.replacement_mesh_base_for_mapping,
                _morph_slider_active_deltas(),
                morph_slider_values,
                post_edit_deltas=morph_slider_post_edit_deltas,
            )
        except Exception as exc:
            morph_slider_topology_blocked["blocked"] = True
            morph_slider_topology_blocked["reason"] = str(exc)
            if refresh_controls:
                _morph_slider_refresh_controls()
            return False
        _mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)
        if increment_revision:
            mesh_edit_revision["value"] = int(mesh_edit_revision.get("value", 0) or 0) + 1
        _mesh_edit_commit_geometry_preview_state()
        _refresh_source_tree_selection_state()
        _refresh_source_assignment_columns()
        if refresh_controls:
            _refresh_mesh_edit_controls()
        if _alignment_d3d11_preview_active():
            _mesh_edit_update_live_preview(
                _mesh_edit_all_live_vertices_for_sources(_mesh_edit_preview_source_indices()),
                include_normals=True,
                immediate=True,
            )
        elif _mesh_edit_tab_active():
            _mesh_edit_mark_native_preview_stale(
                "Active Mesh Editor morph-slider apply requires native D3D11 refresh; Python preview rebuild fallback is disabled."
            )
        else:
            _queue_static_preview_rebuild()
        if status_message:
            self.set_status_message(status_message)
        return True

    def _morph_slider_sync_row_widgets() -> None:
        morph_slider_update_guard["active"] = True
        try:
            for sync_state in _morph_slider_row_sync_states_helper(morph_slider_rows, morph_slider_values):
                slider = sync_state.row.get("slider")
                spin = sync_state.row.get("spin")
                if isinstance(slider, QSlider):
                    slider.setValue(sync_state.slider_value)
                if isinstance(spin, QDoubleSpinBox):
                    spin.setValue(sync_state.percent)
        finally:
            morph_slider_update_guard["active"] = False

    def _morph_slider_begin_change(reason: str = "Morph slider") -> None:
        if morph_slider_change_active.get("active"):
            return
        if _mesh_edit_state.replacement_mesh_for_mapping is not None:
            _mesh_edit_record_snapshot()
        morph_slider_change_active["active"] = True

    def _morph_slider_end_change() -> None:
        morph_slider_change_active["active"] = False

    def _morph_slider_set_value(
        slider_id: str,
        percent: float,
        *,
        record_snapshot: bool = True,
        finish_change: bool = True,
    ) -> None:
        delta = morph_slider_deltas.get(str(slider_id))
        commit_state = _morph_slider_value_commit_state_helper(
            update_active=bool(morph_slider_update_guard.get("active")),
            delta=delta,
            supported=_morph_slider_supported(),
            blocked=bool(morph_slider_topology_blocked.get("blocked")),
            values=morph_slider_values,
            percent=percent,
        )
        if not commit_state.should_commit:
            return
        if record_snapshot:
            _morph_slider_begin_change("Morph slider")
        morph_slider_values[commit_state.slider_id] = commit_state.clamped_percent
        _morph_slider_sync_row_widgets()
        _morph_slider_apply_to_working_mesh(status_message=commit_state.status_text)
        if record_snapshot and finish_change:
            _morph_slider_end_change()

    def _morph_slider_clear_rows() -> None:
        while morph_slider_rows_layout.count():
            item = morph_slider_rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        morph_slider_rows.clear()

    def _morph_slider_add_row(delta: MeshMorphSliderDelta) -> None:
        row_state = _morph_slider_row_state_helper(delta, morph_slider_values)
        row = QFrame(morph_slider_rows_widget)
        row_layout = QGridLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setHorizontalSpacing(3)
        row_layout.setVerticalSpacing(2)
        label = QLabel(row_state.label)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        reset_button = QPushButton(row_state.reset_text)
        reset_button.setMinimumWidth(0)
        slider = QSlider(Qt.Horizontal)
        slider.setRange(row_state.slider_minimum, row_state.slider_maximum)
        slider.setSingleStep(100)
        slider.setPageStep(1000)
        spin = _make_double_spin_helper(
            0.0,
            row_state.spin_minimum,
            row_state.spin_maximum,
            2,
            1.0,
            " %",
        )
        spin.setMinimumWidth(76)
        row_layout.addWidget(label, 0, 0, 1, 3)
        row_layout.addWidget(reset_button, 1, 0)
        row_layout.addWidget(slider, 1, 1)
        row_layout.addWidget(spin, 1, 2)
        reset_button.clicked.connect(
            lambda _checked=False, sid=row_state.slider_id, default=row_state.reset_percent: _morph_slider_set_value(
                sid,
                default,
            )
        )
        slider.sliderPressed.connect(lambda sid=row_state.slider_id: _morph_slider_begin_change("Morph slider"))
        slider.valueChanged.connect(
            lambda raw_value, sid=row_state.slider_id: _morph_slider_set_value(
                sid,
                float(raw_value) / 100.0,
                record_snapshot=False,
                finish_change=False,
            )
        )
        slider.sliderReleased.connect(_morph_slider_end_change)
        spin.valueChanged.connect(
            lambda value, sid=row_state.slider_id: _morph_slider_set_value(
                sid,
                float(value),
            )
        )
        morph_slider_rows_layout.addWidget(row)
        morph_slider_rows.append({"slider_id": row_state.slider_id, "slider": slider, "spin": spin, "row": row})

    def _morph_slider_rebuild_rows() -> None:
        _morph_slider_clear_rows()
        for delta in _morph_slider_active_deltas():
            _morph_slider_add_row(delta)
        _morph_slider_sync_row_widgets()

    def _morph_slider_refresh_controls() -> None:
        supported = _morph_slider_supported()
        loaded = _morph_slider_has_loaded_deltas()
        blocked = bool(morph_slider_topology_blocked.get("blocked"))
        selected_count = _mesh_edit_index_group_count_helper(mesh_edit_selected_vertices_by_submesh)
        has_nonzero_values = _morph_slider_has_nonzero_values()
        control_state = _morph_slider_control_state_helper(
            supported=supported,
            loaded=loaded,
            blocked=blocked,
            selected_count=selected_count,
            has_nonzero_values=has_nonzero_values,
        )
        morph_slider_group.setEnabled(control_state["group_enabled"])
        morph_slider_create_button.setEnabled(control_state["create_enabled"])
        morph_slider_manage_button.setEnabled(control_state["manage_enabled"])
        for row in morph_slider_rows:
            row_widget = row.get("row")
            if isinstance(row_widget, QWidget):
                row_widget.setEnabled(control_state["rows_enabled"])
        morph_slider_reset_button.setEnabled(control_state["reset_enabled"])
        morph_slider_bake_button.setEnabled(control_state["bake_enabled"])
        morph_slider_status_label.setText(
            _morph_slider_status_text_helper(
                supported=supported,
                blocked=blocked,
                block_reason=morph_slider_topology_blocked.get("reason"),
                loaded=loaded,
                profile_count=len(morph_slider_profiles),
                slider_count=len(morph_slider_deltas),
            )
        )

    def _morph_slider_reload_profiles(*, preserve_values: bool = False) -> None:
        reload_state = _morph_slider_reload_state_helper(
            preserve_values=preserve_values,
            values=morph_slider_values,
            supported=_morph_slider_supported(),
            has_base_mesh=_mesh_edit_state.replacement_mesh_base_for_mapping is not None,
        )
        old_values = reload_state.old_values
        morph_slider_profiles.clear()
        morph_slider_deltas.clear()
        morph_slider_values.clear()
        if reload_state.clear_block_reason:
            morph_slider_topology_blocked["blocked"] = False
            morph_slider_topology_blocked["reason"] = ""
        if not reload_state.should_load_profiles:
            morph_slider_post_edit_deltas.clear()
            _morph_slider_rebuild_rows()
            _morph_slider_refresh_controls()
            return
        profiles = load_morph_slider_profiles(
            morph_slider_profile_root,
            _mesh_edit_state.replacement_mesh_base_for_mapping,
            entry.path,
        )
        morph_slider_profiles.extend(profiles)
        used_slider_ids: set[str] = set()
        for profile_index, profile in enumerate(profiles):
            for spec in tuple(profile.sliders or ()):
                slider_id = _morph_slider_unique_slider_id_helper(
                    spec.slider_id,
                    used_slider_ids,
                    profile_index=profile_index,
                )
                try:
                    delta = load_morph_slider_delta(
                        _mesh_edit_state.replacement_mesh_base_for_mapping,
                        profile,
                        spec,
                        slider_id=slider_id,
                    )
                except Exception as exc:
                    self.append_archive_log(f"Skipped incompatible Morph Slider {spec.label or spec.slider_id}: {exc}")
                    continue
                used_slider_ids.add(slider_id.lower())
                morph_slider_deltas[delta.slider_id] = delta
                morph_slider_values[delta.slider_id] = _morph_slider_value_or_default_helper(
                    old_values,
                    delta.slider_id,
                    delta.default_percent,
                )
        morph_slider_post_edit_deltas[:] = _morph_slider_zero_post_edit_deltas()
        _morph_slider_capture_post_edit_deltas()
        _morph_slider_rebuild_rows()
        _morph_slider_refresh_controls()

    def _morph_slider_reset_all() -> None:
        reset_state = _morph_slider_reset_state_helper(loaded=_morph_slider_has_loaded_deltas())
        if not reset_state.should_reset:
            return
        _morph_slider_begin_change(reset_state.change_label)
        for delta in _morph_slider_active_deltas():
            morph_slider_values[delta.slider_id] = float(delta.default_percent)
        _morph_slider_sync_row_widgets()
        _morph_slider_apply_to_working_mesh(status_message=reset_state.status_text)
        _morph_slider_end_change()

    def _morph_slider_clone_working_mesh_for_bake() -> ParsedMesh | None:
        mesh = _mesh_edit_state.replacement_mesh_for_mapping
        if mesh is None:
            return None
        native_snapshot = None
        try:
            from cdmw.modding.mesh_native_core import (
                dispose_native_mesh_submesh_snapshot,
                invalidate_native_mesh_session_submeshes,
                restore_native_mesh_submesh_snapshot,
                snapshot_native_mesh_submeshes,
            )

            native_snapshot = snapshot_native_mesh_submeshes(mesh)
            if native_snapshot is not None:
                baked_mesh = ParsedMesh()
                if restore_native_mesh_submesh_snapshot(baked_mesh, native_snapshot):
                    invalidate_native_mesh_session_submeshes(
                        baked_mesh,
                        range(len(getattr(baked_mesh, "submeshes", ()) or ())),
                    )
                    return baked_mesh
        except Exception:
            pass
        finally:
            if native_snapshot is not None:
                try:
                    dispose_native_mesh_submesh_snapshot(native_snapshot)
                except Exception:
                    pass
        message = "Native morph-slider bake snapshot failed; Python full-mesh bake clone fallback is disabled."
        _record_mesh_edit_event(
            "morph_slider_native_bake_snapshot_failed",
            message=message,
        )
        self.set_status_message(message, error=True)
        return None

    def _morph_slider_bake() -> None:
        bake_state = _morph_slider_bake_state_helper(
            has_working_mesh=_mesh_edit_state.replacement_mesh_for_mapping is not None,
            loaded=_morph_slider_has_loaded_deltas(),
            has_nonzero_values=_morph_slider_has_nonzero_values(),
        )
        if not bake_state.should_bake:
            return
        baked_base_mesh = _morph_slider_clone_working_mesh_for_bake()
        if baked_base_mesh is None:
            return
        _morph_slider_begin_change(bake_state.change_label)
        _mesh_edit_state.replacement_mesh_base_for_mapping = baked_base_mesh
        morph_slider_values.clear()
        morph_slider_post_edit_deltas[:] = _morph_slider_zero_post_edit_deltas()
        morph_slider_topology_blocked["blocked"] = False
        morph_slider_topology_blocked["reason"] = ""
        _morph_slider_reload_profiles(preserve_values=False)
        mesh_edit_revision["value"] = int(mesh_edit_revision.get("value", 0) or 0) + 1
        _mesh_edit_commit_geometry_preview_state()
        _refresh_source_assignment_columns()
        _refresh_mesh_edit_controls()
        _mesh_edit_replace_live_triangles_or_queue_rebuild(_mesh_edit_preview_source_indices(), replace_all=True)
        _morph_slider_end_change()
        self.set_status_message(bake_state.status_text)

    def _morph_slider_import_pack() -> None:
        route_state = _morph_slider_import_route_state_helper(
            has_base_mesh=_mesh_edit_state.replacement_mesh_base_for_mapping is not None
        )
        if not route_state.allowed:
            QMessageBox.information(
                dialog,
                route_state.title,
                route_state.message,
            )
            return
        selected = QFileDialog.getExistingDirectory(
            dialog,
            _morph_slider_import_action_text_helper(),
            str(self.settings_file_path.parent),
        )
        if not selected:
            return
        try:
            profile = import_body_slider_profile(
                selected,
                _mesh_edit_state.replacement_mesh_base_for_mapping,
                entry.path,
                morph_slider_profile_root,
            )
        except Exception as exc:
            QMessageBox.warning(dialog, _morph_slider_import_action_text_helper(), str(exc))
            return
        _morph_slider_reload_profiles(preserve_values=True)
        self.set_status_message(_morph_slider_imported_status_text_helper(profile.name))

    def _morph_slider_add_target() -> None:
        route_state = _morph_slider_add_target_route_state_helper(
            has_base_mesh=_mesh_edit_state.replacement_mesh_base_for_mapping is not None
        )
        if not route_state.allowed:
            QMessageBox.information(
                dialog,
                route_state.title,
                route_state.message,
            )
            return
        selected, _selected_filter = QFileDialog.getOpenFileName(
            dialog,
            _morph_slider_add_target_action_text_helper(),
            str(self.settings_file_path.parent),
            _morph_slider_target_mesh_file_filter_helper(),
        )
        if not selected:
            return
        try:
            profile = import_single_morph_slider_profile(
                selected,
                _mesh_edit_state.replacement_mesh_base_for_mapping,
                entry.path,
                morph_slider_profile_root,
            )
        except Exception as exc:
            QMessageBox.warning(dialog, _morph_slider_add_target_action_text_helper(), str(exc))
            return
        _morph_slider_reload_profiles(preserve_values=True)
        self.set_status_message(_morph_slider_added_status_text_helper(profile.name))

    def _morph_slider_default_region_amount() -> float:
        if _mesh_edit_state.replacement_mesh_base_for_mapping is None:
            return 0.01
        return _mesh_edit_selection_region_default_amount_helper(
            _mesh_edit_state.replacement_mesh_base_for_mapping,
            mesh_edit_selected_vertices_by_submesh,
        )

    def _morph_slider_create_from_selection() -> None:
        route_state = _morph_slider_create_route_state_helper(
            has_base_mesh=_mesh_edit_state.replacement_mesh_base_for_mapping is not None,
            has_selection=_mesh_edit_has_index_groups_helper(mesh_edit_selected_vertices_by_submesh),
        )
        if not route_state.allowed:
            QMessageBox.information(
                dialog,
                route_state.title,
                route_state.message,
            )
            return
        name, accepted = QInputDialog.getText(
            dialog,
            _morph_slider_create_action_text_helper(),
            _morph_slider_name_prompt_text_helper(),
            text=_morph_slider_default_name_text_helper(),
        )
        if not accepted or not str(name or "").strip():
            return
        default_amount = _morph_slider_default_region_amount()
        amount, accepted = QInputDialog.getDouble(
            dialog,
            _morph_slider_create_action_text_helper(),
            _morph_slider_amount_prompt_text_helper(),
            float(default_amount),
            0.000001,
            1000000.0,
            6,
        )
        if not accepted:
            return
        feather, accepted = QInputDialog.getInt(
            dialog,
            _morph_slider_create_action_text_helper(),
            _morph_slider_feather_prompt_text_helper(),
            2,
            0,
            32,
            1,
        )
        if not accepted:
            return
        try:
            profile = create_region_volume_slider_profile(
                _mesh_edit_state.replacement_mesh_base_for_mapping,
                entry.path,
                morph_slider_profile_root,
                mesh_edit_selected_vertices_by_submesh,
                name=str(name),
                amount=float(amount),
                feather=int(feather),
            )
        except Exception as exc:
            QMessageBox.warning(dialog, _morph_slider_create_action_text_helper(), str(exc))
            return
        _morph_slider_reload_profiles(preserve_values=True)
        self.set_status_message(_morph_slider_created_status_text_helper(profile.name))

    def _mesh_edit_can_edit_scope() -> tuple[bool, str]:
        allowed_indices = _mesh_edit_allowed_source_indices()
        return _mesh_edit_can_edit_scope_helper(
            mesh_edit_supported=mesh_edit_supported,
            scope_mode=_mesh_edit_scope_mode(),
            selected_scope_source_index=_mesh_edit_selected_scope_source_index(),
            allowed_source_count=len(allowed_indices),
            current_tool=_mesh_edit_current_tool(),
            morph_slider_has_nonzero_values=_morph_slider_has_nonzero_values(),
        )

    def _alignment_d3d11_mesh_edit_commands_active() -> bool:
        return bool(
            _alignment_d3d11_preview_active()
            and callable(getattr(alignment_d3d11_preview_host, "set_mesh_edit_state", None))
            and callable(getattr(alignment_d3d11_preview_host, "update_mesh_edit_vertices", None))
            and callable(getattr(alignment_d3d11_preview_host, "replace_mesh_edit_triangles", None))
        )

    def _sync_mesh_edit_preview_settings() -> None:
        allowed_indices = _mesh_edit_allowed_source_indices()
        active = (
            bool(mesh_edit_enabled_checkbox.isChecked())
            and _mesh_edit_tab_active()
            and _mesh_edit_can_edit_scope()[0]
        )
        tool = _mesh_edit_current_tool()
        target_mode = _mesh_edit_target_mode_for_tool()
        delete_mode = str(mesh_edit_delete_mode_combo.currentData() or "release")
        if _alignment_d3d11_mesh_edit_commands_active():
            if active:
                _clear_alignment_d3d11_fast_transform_state()
                alignment_d3d11_preview_host.set_alignment_state(
                    enabled=False,
                    source_submesh_indices=(),
                    translation_sensitivity=0.85,
                    rotation_degrees_per_pixel=0.18,
                )
                alignment_d3d11_preview_host.set_alignment_preview_transform()
            alignment_d3d11_preview_host.set_mesh_edit_state(
                enabled=active,
                scope_mode=_mesh_edit_scope_mode(),
                source_submesh_indices=allowed_indices,
                target_mode=target_mode,
                tool=tool,
                delete_mode=delete_mode,
                radius_pixels=float(mesh_edit_radius_spin.value()),
                strength=float(mesh_edit_strength_spin.value()) / 100.0,
                falloff=str(mesh_edit_falloff_combo.currentData() or "smooth"),
                show_vertices=bool(mesh_edit_show_vertices_checkbox.isChecked()),
                selection_mode=_mesh_edit_selection_mode(),
                selection_depth_mode=_mesh_edit_selection_depth_mode(),
                smooth_iterations=int(mesh_edit_iterations_spin.value()),
            )
        for preview_widget in (static_dialog_preview, overlay_dialog_preview, replacement_only_preview):
            preview_widget.set_mesh_edit_target_mode(target_mode)
            preview_widget.set_mesh_edit_tool(tool)
            if hasattr(preview_widget, "set_mesh_edit_source_submesh_indices"):
                preview_widget.set_mesh_edit_source_submesh_indices(allowed_indices)
            if hasattr(preview_widget, "set_mesh_edit_delete_mode"):
                preview_widget.set_mesh_edit_delete_mode(delete_mode)
            preview_widget.set_mesh_edit_brush_settings(
                radius_pixels=float(mesh_edit_radius_spin.value()),
                strength=float(mesh_edit_strength_spin.value()) / 100.0,
                falloff=str(mesh_edit_falloff_combo.currentData() or "smooth"),
                show_vertices=bool(mesh_edit_show_vertices_checkbox.isChecked()),
            )
            preview_widget.set_mesh_editing_enabled(active)

    mesh_edit_topology_worker_state: dict[str, object] = {
        "request_id": 0,
        "thread": None,
        "worker": None,
        "progress": None,
        "start_revision": 0,
    }
    mesh_edit_selection_worker_state: dict[str, object] = {
        "request_id": 0,
        "thread": None,
        "worker": None,
        "start_revision": 0,
    }

    def _mesh_edit_topology_worker_active() -> bool:
        thread = mesh_edit_topology_worker_state.get("thread")
        is_running = getattr(thread, "isRunning", None)
        return bool(callable(is_running) and is_running())

    def _mesh_edit_selection_worker_active() -> bool:
        thread = mesh_edit_selection_worker_state.get("thread")
        is_running = getattr(thread, "isRunning", None)
        return bool(callable(is_running) and is_running())

    def _mesh_edit_worker_active() -> bool:
        return _mesh_edit_topology_worker_active() or _mesh_edit_selection_worker_active()

    def _mesh_edit_should_run_topology_worker(
        selected_vertices: Mapping[int, object] | None,
        selected_faces: Mapping[int, object] | None,
        selected_edges: Mapping[int, object] | None,
        selected_source_indices: Sequence[int] | None = None,
    ) -> bool:
        _ = selected_vertices, selected_faces, selected_edges, selected_source_indices
        if QThread is None or QProgressDialog is None:
            return False
        return True

    def _mesh_edit_cancel_topology_worker() -> None:
        worker = mesh_edit_topology_worker_state.get("worker")
        stop = getattr(worker, "stop", None)
        if callable(stop):
            stop()
        progress = mesh_edit_topology_worker_state.get("progress")
        set_label = getattr(progress, "setLabelText", None)
        if callable(set_label):
            set_label("Cancelling mesh edit...")
        self.set_status_message("Cancelling mesh edit...")

    def _mesh_edit_topology_worker_progress(request_id: int, percent: int, message: str) -> None:
        if int(request_id) != int(mesh_edit_topology_worker_state.get("request_id", 0) or 0):
            return
        progress = mesh_edit_topology_worker_state.get("progress")
        set_value = getattr(progress, "setValue", None)
        set_label = getattr(progress, "setLabelText", None)
        if callable(set_value):
            set_value(max(0, min(100, int(percent))))
        if callable(set_label) and message:
            set_label(str(message))

    def _mesh_edit_finish_topology_worker(request_id: int) -> None:
        if int(request_id) != int(mesh_edit_topology_worker_state.get("request_id", 0) or 0):
            return
        progress = mesh_edit_topology_worker_state.get("progress")
        disconnect = getattr(getattr(progress, "canceled", None), "disconnect", None)
        if callable(disconnect):
            try:
                disconnect(_mesh_edit_cancel_topology_worker)
            except (TypeError, RuntimeError):
                pass
        close = getattr(progress, "close", None)
        delete_later = getattr(progress, "deleteLater", None)
        if callable(close):
            close()
        if callable(delete_later):
            delete_later()
        mesh_edit_topology_worker_state.update(
            {
                "thread": None,
                "worker": None,
                "progress": None,
                "start_revision": 0,
            }
        )
        _refresh_mesh_edit_controls()

    def _mesh_edit_topology_worker_failed(request_id: int, message: str) -> None:
        if int(request_id) != int(mesh_edit_topology_worker_state.get("request_id", 0) or 0):
            return
        _mesh_edit_pop_undo_snapshot()
        _pop_geometry_undo_snapshot()
        _refresh_mesh_edit_controls()
        self.set_status_message(str(message or "Mesh edit failed."), error=True)

    def _mesh_edit_topology_worker_cancelled(request_id: int, message: str) -> None:
        if int(request_id) != int(mesh_edit_topology_worker_state.get("request_id", 0) or 0):
            return
        _mesh_edit_pop_undo_snapshot()
        _pop_geometry_undo_snapshot()
        _refresh_mesh_edit_controls()
        self.set_status_message(str(message or "Mesh edit cancelled."))

    def _mesh_edit_topology_worker_completed(
        request_id: int,
        result: object,
        commit_callback: object,
        result_adapter: object | None = None,
    ) -> None:
        if int(request_id) != int(mesh_edit_topology_worker_state.get("request_id", 0) or 0):
            return
        start_revision = int(mesh_edit_topology_worker_state.get("start_revision", 0) or 0)
        if int(mesh_edit_revision.get("value", 0) or 0) != start_revision:
            _mesh_edit_pop_undo_snapshot()
            _pop_geometry_undo_snapshot()
            _refresh_mesh_edit_controls()
            self.set_status_message("Mesh edit result was discarded because the mesh changed while it was running.", error=True)
            return
        if callable(result_adapter):
            try:
                result = result_adapter(result)
            except Exception as exc:
                _mesh_edit_topology_worker_failed(request_id, f"{type(exc).__name__}: {exc}")
                return
        if callable(commit_callback):
            commit_callback(result)

    def _mesh_edit_start_topology_worker(
        action: str,
        *,
        action_text: str,
        selected_vertices: Mapping[int, object] | None,
        selected_faces: Mapping[int, object] | None,
        selected_edges: Mapping[int, object] | None,
        params: Mapping[str, object],
        commit_callback: object,
        selected_source_indices: Sequence[int] | None = None,
    ) -> bool:
        if _mesh_edit_state.replacement_mesh_for_mapping is None:
            return False
        if _mesh_edit_worker_active():
            self.set_status_message("Wait for the current mesh edit to finish, or cancel it first.", error=True)
            return True
        if not _mesh_edit_should_run_topology_worker(
            selected_vertices,
            selected_faces,
            selected_edges,
            selected_source_indices,
        ):
            return False
        request_id = int(mesh_edit_topology_worker_state.get("request_id", 0) or 0) + 1
        _mesh_edit_record_snapshot()
        session = _mesh_editor_ensure_static_replacement_session(_mesh_edit_state.replacement_mesh_for_mapping)
        if not isinstance(session, StaticReplacementMeshEditSession):
            _mesh_edit_pop_undo_snapshot()
            _pop_geometry_undo_snapshot()
            return False
        selection = MeshEditSelection.from_maps(
            vertices_by_submesh=selected_vertices,
            edges_by_submesh=selected_edges,
            faces_by_submesh=selected_faces,
            source_indices=selected_source_indices,
        )
        before = session.submesh_counts
        service_action = "separate" if str(action or "").strip().lower() == "split" else str(action or "")
        action_params = dict(params or {})
        command_mode = action_params.pop("mode", None) or (
            "sculpt" if str(service_action).strip().lower() == "brush" else "edit"
        )
        command = MeshEditCommand(
            action=service_action,
            selection=selection,
            params=action_params,
            mode=str(command_mode),
        )

        def _result_adapter(edit_result: object) -> object:
            return session._result(edit_result, before=before, selection=selection)

        worker = MeshEditCommandWorker(
            request_id,
            session.controller.mesh_service,
            session.session_id,
            command,
            action_text=action_text,
        )
        thread = QThread(dialog)
        progress = QProgressDialog(f"Applying {action_text}...", "Cancel", 0, 100, dialog)
        progress.setWindowTitle(_mesh_edit_dialog_title_helper())
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(250)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.canceled.connect(_mesh_edit_cancel_topology_worker)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress_changed.connect(_mesh_edit_topology_worker_progress)
        worker.completed.connect(
            lambda finished_request_id, result, callback=commit_callback, adapter=_result_adapter: _mesh_edit_topology_worker_completed(
                finished_request_id,
                result,
                callback,
                adapter,
            )
        )
        worker.cancelled.connect(_mesh_edit_topology_worker_cancelled)
        worker.error.connect(_mesh_edit_topology_worker_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda finished_request_id=request_id: _mesh_edit_finish_topology_worker(finished_request_id))
        mesh_edit_topology_worker_state.update(
            {
                "request_id": request_id,
                "thread": thread,
                "worker": worker,
                "progress": progress,
                "start_revision": int(mesh_edit_revision.get("value", 0) or 0),
            }
        )
        _refresh_mesh_edit_controls()
        self.set_status_message(f"Applying {action_text} in the background...")
        thread.start(QThread.LowPriority)
        return True

    def _sync_mesh_editor_tab_action_state(
        *,
        editing_active: bool,
        sculpt_tool: bool,
        selected_count: int,
        selected_face_count: int,
        selected_edge_count: int = 0,
    ) -> None:
        active_selection_mode = str(mesh_editor_action_bar_selection_mode.get("value") or "vertex")
        mode = "edit" if editing_active else "object"
        selection_empty = (int(selected_count or 0) + int(selected_face_count or 0) + int(selected_edge_count or 0)) <= 0
        active_tool_key = _mesh_editor_active_tool_action_key()
        mesh_editor_tab = getattr(self, "mesh_editor_tab", None)
        update_action_state = getattr(mesh_editor_tab, "update_editor_action_state", None)
        if callable(update_action_state):
            update_action_state(
                mode=mode,
                active_selection_mode=active_selection_mode,
                active_tool_key=active_tool_key,
                selection_empty=selection_empty,
                undo_count=len(mesh_edit_undo_stack),
                redo_count=len(mesh_edit_redo_stack),
            )
        compact_update = getattr(classic_mesh_edit_action_bar, "update_action_state", None)
        if callable(compact_update):
            compact_update(
                has_target=bool(mesh_edit_supported),
                selection_empty=selection_empty,
                mode=mode,
                active_selection_mode=active_selection_mode,
                active_tool_key=active_tool_key,
                undo_count=len(mesh_edit_undo_stack),
                redo_count=len(mesh_edit_redo_stack),
            )
        compact_set_enabled = getattr(classic_mesh_edit_action_bar, "setEnabled", None)
        if callable(compact_set_enabled):
            compact_set_enabled(not _mesh_edit_worker_active())

    def _show_mesh_edit_tab() -> None:
        _refresh_mesh_edit_controls()
        if callable(_apply_alignment_dialog_responsive_layout):
            _apply_alignment_dialog_responsive_layout()

    def _mesh_editor_tool_action_key(tool: str) -> str:
        return {
            "grab": "brush_grab",
            "smooth": "brush_smooth",
            "inflate": "brush_inflate",
            "pinch": "brush_pinch",
        }.get(str(tool or "").strip().lower(), "")

    def _mesh_editor_active_tool_action_key() -> str:
        current_tool = _mesh_edit_current_tool()
        active_key = str(mesh_editor_action_bar_active_tool_key.get("value") or "")
        if current_tool == "grab" and active_key in {"transform_move", "brush_grab"}:
            return active_key
        expected_key = _mesh_editor_tool_action_key(current_tool)
        if expected_key:
            mesh_editor_action_bar_active_tool_key["value"] = expected_key
            return expected_key
        return ""

    def _set_mesh_edit_enabled(checked: bool) -> None:
        if bool(mesh_edit_enabled_checkbox.isChecked()) == bool(checked):
            _refresh_mesh_edit_controls()
            return
        mesh_edit_enabled_checkbox.setChecked(bool(checked))

    def _select_mesh_edit_tool(tool: str, *, active_action_key: str = "") -> bool:
        index = mesh_edit_tool_combo.findData(str(tool or ""))
        if int(index) < 0:
            return False
        mesh_editor_action_bar_active_tool_key["value"] = str(active_action_key or _mesh_editor_tool_action_key(tool) or "")
        if mesh_edit_tool_combo.currentIndex() == int(index):
            _refresh_mesh_edit_controls()
            _sync_mesh_edit_preview_settings()
            return True
        mesh_edit_tool_combo.setCurrentIndex(int(index))
        _refresh_mesh_edit_controls()
        _sync_mesh_edit_preview_settings()
        return True

    def _mesh_editor_action_selection() -> tuple[dict[int, set[int]], dict[int, set[int]]]:
        if _mesh_edit_state.replacement_mesh_for_mapping is None:
            return {}, {}
        allowed_indices = set(_mesh_edit_allowed_source_indices())
        selected_vertices = _mesh_edit_sorted_index_groups_helper(
            mesh_edit_selected_vertices_by_submesh,
            allowed_source_indices=allowed_indices,
            mesh=_mesh_edit_state.replacement_mesh_for_mapping,
        )
        selected_faces = _mesh_edit_sorted_index_groups_helper(
            mesh_edit_selected_faces_by_submesh,
            allowed_source_indices=allowed_indices,
            mesh=_mesh_edit_state.replacement_mesh_for_mapping,
        )
        return selected_vertices, selected_faces

    def _mesh_editor_action_source_indices() -> tuple[int, ...]:
        return _mesh_edit_selected_source_indices()

    def _mesh_editor_edge_selection(
        selected_vertices: Mapping[int, Iterable[int]],
        selected_faces: Mapping[int, Iterable[int]],
    ) -> dict[int, set[tuple[int, int]]]:
        _ = selected_vertices, selected_faces
        mesh = _mesh_edit_state.replacement_mesh_for_mapping
        if mesh is None:
            return {}

        def _edge(a: object, b: object) -> tuple[int, int]:
            left = int(a)
            right = int(b)
            return (left, right) if left <= right else (right, left)

        edges_by_submesh: dict[int, set[tuple[int, int]]] = {}
        allowed_indices = set(_mesh_edit_allowed_source_indices())
        for submesh_index, edge_items in (mesh_edit_selected_edges_by_submesh or {}).items():
            if not 0 <= int(submesh_index) < len(mesh.submeshes):
                continue
            if int(submesh_index) not in allowed_indices:
                continue
            vertex_count = len(getattr(mesh.submeshes[int(submesh_index)], "vertices", ()) or ())
            for edge_item in edge_items or ():
                try:
                    left, right = _edge(edge_item[0], edge_item[1])
                except (TypeError, ValueError, IndexError):
                    continue
                if left != right and 0 <= left < vertex_count and 0 <= right < vertex_count:
                    edges_by_submesh.setdefault(int(submesh_index), set()).add((left, right))
        return {index: edges for index, edges in edges_by_submesh.items() if edges}

    def _mesh_editor_selected_edge_count() -> int:
        count = 0
        for edge_items in (mesh_edit_selected_edges_by_submesh or {}).values():
            try:
                count += len(edge_items or ())
            except TypeError:
                continue
        return count

    def _mesh_editor_action_result_changed(result: object) -> bool:
        return bool(
            getattr(result, "affected_submesh_indices", ())
            or getattr(result, "changed_vertices_by_submesh", None)
            or int(getattr(result, "removed_face_count", 0) or 0) > 0
            or int(getattr(result, "added_face_count", 0) or 0) > 0
            or int(getattr(result, "moved_face_count", 0) or 0) > 0
            or int(getattr(result, "added_vertex_count", 0) or 0) > 0
            or int(getattr(result, "removed_vertex_count", 0) or 0) > 0
        )

    def _mesh_editor_action_result_within_allowed_scope(result: object) -> bool:
        allowed_indices = set(int(index) for index in _mesh_edit_allowed_source_indices(require_enabled=False))
        if not allowed_indices:
            return True
        touched_indices: set[int] = set()
        for raw_index in getattr(result, "affected_submesh_indices", ()) or ():
            try:
                touched_indices.add(int(raw_index))
            except (TypeError, ValueError):
                continue
        for attr_name in (
            "changed_vertices_by_submesh",
            "changed_normals_by_submesh",
            "changed_faces_by_submesh",
        ):
            changed = getattr(result, attr_name, None)
            keys = getattr(changed, "keys", None)
            if not callable(keys):
                continue
            for raw_index in keys() or ():
                try:
                    touched_indices.add(int(raw_index))
                except (TypeError, ValueError):
                    continue
        for attr_name in ("source_submesh_index", "target_submesh_index"):
            try:
                raw_index = int(getattr(result, attr_name, -1) or -1)
            except (TypeError, ValueError):
                raw_index = -1
            if raw_index >= 0:
                touched_indices.add(raw_index)
        try:
            new_submesh_index = int(getattr(result, "new_submesh_index", -1) or -1)
        except (TypeError, ValueError):
            new_submesh_index = -1
        unsafe_indices = {
            index
            for index in touched_indices
            if index >= 0 and index not in allowed_indices and index != new_submesh_index
        }
        return not unsafe_indices

    def _mesh_editor_sync_new_source_part(result: object) -> None:
        new_source_index = int(getattr(result, "new_submesh_index", -1) or -1)
        source_index = int(getattr(result, "source_submesh_index", -1) or -1)
        if new_source_index < 0:
            return
        if hasattr(appended_source_indices, "add"):
            appended_source_indices.add(new_source_index)
        selected_source_part["index"] = new_source_index
        if callable(_rebuild_source_part_widgets):
            _rebuild_source_part_widgets()

    def _mesh_editor_commit_action_bar_service_result(
        result: object,
        *,
        action_key: str,
        action_text: str,
        topology_action: bool,
    ) -> bool:
        if not _mesh_editor_action_result_changed(result):
            _mesh_edit_pop_undo_snapshot()
            _pop_geometry_undo_snapshot()
            _refresh_mesh_edit_controls()
            self.set_status_message(f"Mesh Editor action made no changes: {action_text}.")
            return True
        if not _mesh_editor_action_result_within_allowed_scope(result):
            _mesh_edit_pop_undo_snapshot()
            _pop_geometry_undo_snapshot()
            _refresh_mesh_edit_controls()
            self.set_status_message(
                f"Mesh Editor action blocked outside selected scope: {action_text}.",
                error=True,
            )
            return True
        _mesh_editor_store_result_mesh(result)
        edit_result = getattr(result, "edit_result", None)
        actual_topology_action = bool(topology_action or getattr(edit_result, "topology_changed", False))
        if actual_topology_action:
            _mesh_editor_sync_new_source_part(result)
            _morph_slider_mark_topology_changed(
                _mesh_edit_topology_changed_status_helper(action_key) or _morph_slider_topology_changed_reason_text_helper()
            )
            _mesh_edit_clear_topology_selection()
        native_update_applied = _mesh_editor_apply_result_native_update(result)
        _mesh_edit_update_mesh_totals()
        if not native_update_applied:
            _mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)
        mesh_edit_revision["value"] = int(mesh_edit_revision.get("value", 0) or 0) + 1
        _mesh_edit_commit_geometry_preview_state()
        _refresh_source_tree_selection_state()
        _refresh_source_assignment_columns()
        _refresh_mesh_edit_controls()
        if not native_update_applied:
            _mesh_edit_replace_live_triangles_or_queue_rebuild(getattr(result, "affected_submesh_indices", ()))
        self.set_status_message(f"Mesh Editor action applied: {action_text}.")
        return True

    def _mesh_editor_embedded_controller():
        session = _mesh_editor_ensure_static_replacement_session()
        return session.controller if isinstance(session, StaticReplacementMeshEditSession) else None

    def _mesh_editor_embedded_apply_native_update(native_update: object) -> bool:
        return _mesh_editor_apply_native_update(native_update)

    def _mesh_editor_embedded_set_skeleton_bone(bone_index: object) -> bool:
        setter = getattr(alignment_d3d11_preview_host, "set_skeleton_selected_bone", None)
        if not callable(setter):
            return False
        try:
            return bool(setter(int(bone_index)))
        except (TypeError, ValueError, RuntimeError):
            return False

    def _mesh_editor_embedded_run_part_action(action_key: str, source_indices: object) -> bool:
        normalized = str(action_key or "").strip().lower()
        try:
            selected_sources = tuple(sorted({int(index) for index in tuple(source_indices or ()) if int(index) >= 0}))
        except (TypeError, ValueError):
            selected_sources = ()
        if not selected_sources:
            self.set_status_message("Select one or more mesh parts first.", error=True)
            return False
        if normalized == "delete" and callable(_delete_selected_source_parts):
            _delete_selected_source_parts(selected_sources)
            _mesh_editor_clear_static_replacement_session()
            return True
        if normalized not in {"delete", "duplicate", "recalculate_normals", "weighted_normals", "flip_normals"}:
            return False
        if _mesh_edit_state.replacement_mesh_for_mapping is None:
            return False
        action_text = {
            "delete": "Delete Part",
            "duplicate": "Clone Part",
            "recalculate_normals": "Recalculate Normals",
            "weighted_normals": "Weighted Normals",
            "flip_normals": "Flip Normals",
        }.get(normalized, normalized)
        _mesh_edit_record_snapshot()
        params = {"delete_parts": True} if normalized == "delete" else {}
        result = _mesh_editor_apply_static_replacement_edit(
            _mesh_edit_state.replacement_mesh_for_mapping,
            normalized,
            source_indices=selected_sources,
            recompute_normals=True,
            **params,
        )
        return _mesh_editor_commit_action_bar_service_result(
            result,
            action_key=normalized,
            action_text=action_text,
            topology_action=normalized in {"delete", "duplicate"},
        )

    def _mesh_editor_apply_action_bar_service_action(
        action: str,
        *,
        action_key: str,
        action_text: str,
        params: dict[str, object] | None = None,
        params_factory: object | None = None,
        topology_action: bool,
        edge_action: bool = False,
        require_selection: bool = True,
    ) -> bool:
        if _mesh_edit_state.replacement_mesh_for_mapping is None:
            return False
        can_edit, reason = _mesh_edit_can_edit_scope()
        if not can_edit:
            QMessageBox.information(dialog, _mesh_edit_dialog_title_helper(), reason)
            return True
        if topology_action and _morph_slider_has_nonzero_values():
            QMessageBox.information(
                dialog,
                _mesh_edit_dialog_title_helper(),
                "Bake or reset Morph Sliders before changing mesh topology.",
            )
            return True
        selected_vertices, selected_faces = _mesh_editor_action_selection()
        selected_sources = _mesh_editor_action_source_indices()
        selected_edges = _mesh_editor_edge_selection(selected_vertices, selected_faces) if edge_action else {}
        if require_selection and not selected_vertices and not selected_faces and not selected_edges and not selected_sources:
            self.set_status_message(
                f"Select adjacent vertices, faces, or edges before using {action_text}." if edge_action
                else f"Select vertices or faces before using {action_text}.",
                error=True,
            )
            return True
        action_params = dict(params or {})
        if callable(params_factory):
            built_params = params_factory()
            if built_params is None:
                return True
            action_params.update(dict(built_params or {}))
        _show_mesh_edit_tab()
        _set_mesh_edit_enabled(True)
        if _mesh_edit_start_topology_worker(
            action,
            action_text=action_text,
            selected_vertices=selected_vertices,
            selected_faces=selected_faces,
            selected_edges=selected_edges,
            selected_source_indices=selected_sources,
            params={**action_params, "recompute_normals": True},
            commit_callback=lambda result: _mesh_editor_commit_action_bar_service_result(
                result,
                action_key=action_key,
                action_text=action_text,
                topology_action=topology_action,
            ),
        ):
            return True
        _mesh_edit_record_snapshot()
        result = _mesh_editor_apply_static_replacement_edit(
            _mesh_edit_state.replacement_mesh_for_mapping,
            action,
            edges_by_submesh=selected_edges,
            vertices_by_submesh=selected_vertices,
            faces_by_submesh=selected_faces,
            source_indices=selected_sources,
            recompute_normals=True,
            **action_params,
        )
        return _mesh_editor_commit_action_bar_service_result(
            result,
            action_key=action_key,
            action_text=action_text,
            topology_action=topology_action,
        )

    def _mesh_editor_prompt_action_value(
        action_text: str,
        label_text: str,
        default_value: float,
        minimum: float,
        maximum: float,
        decimals: int,
    ) -> float | None:
        if QInputDialog is None:
            self.set_status_message(f"Mesh Editor action needs an input dialog: {action_text}.", error=True)
            return None
        value, accepted = QInputDialog.getDouble(
            dialog,
            _mesh_edit_dialog_title_helper(),
            label_text,
            float(default_value),
            float(minimum),
            float(maximum),
            int(decimals),
        )
        return float(value) if accepted else None

    def _mesh_editor_material_part_choices() -> tuple[dict[str, object], ...]:
        mesh = _mesh_edit_state.replacement_mesh_for_mapping
        if mesh is None:
            return ()
        choices: list[dict[str, object]] = []
        allowed_indices = set(_mesh_edit_allowed_source_indices())
        for source_index, submesh in enumerate(tuple(getattr(mesh, "submeshes", ()) or ())):
            if allowed_indices and source_index not in allowed_indices:
                continue
            material = str(getattr(submesh, "material", "") or getattr(submesh, "name", "") or f"part_{source_index}")
            texture = str(getattr(submesh, "texture", "") or "")
            display_name = _source_display_name(source_index) if callable(_source_display_name) else f"Part {source_index}"
            label = f"{display_name}: {material}"
            if texture:
                label = f"{label} / {texture}"
            choices.append(
                {
                    "label": label,
                    "source_index": source_index,
                    "material": material,
                    "texture": texture,
                    "submesh": submesh,
                }
            )
        return tuple(choices)

    def _mesh_editor_default_material_choice_index(choices: tuple[dict[str, object], ...]) -> int:
        selected_vertices, selected_faces = _mesh_editor_action_selection()
        selected_sources = set(selected_vertices) | set(selected_faces) | set(_mesh_editor_action_source_indices())
        selected_source_index = _mesh_edit_selected_source_index()
        if selected_source_index >= 0:
            selected_sources.add(selected_source_index)
        for choice_index, choice in enumerate(choices):
            if int(choice.get("source_index", -1)) in selected_sources:
                return choice_index
        return 0

    def _mesh_editor_prompt_material_part(action_text: str, label_text: str) -> dict[str, object] | None:
        if QInputDialog is None or not callable(getattr(QInputDialog, "getItem", None)):
            self.set_status_message(f"Mesh Editor action needs a material picker: {action_text}.", error=True)
            return None
        choices = _mesh_editor_material_part_choices()
        if not choices:
            self.set_status_message(f"No material parts are available for {action_text}.", error=True)
            return None
        labels = [str(choice["label"]) for choice in choices]
        selected_label, accepted = QInputDialog.getItem(
            dialog,
            _mesh_edit_dialog_title_helper(),
            label_text,
            labels,
            _mesh_editor_default_material_choice_index(choices),
            False,
        )
        if not accepted:
            return None
        label_to_choice = {str(choice["label"]): choice for choice in choices}
        return label_to_choice.get(str(selected_label))

    def _mesh_editor_material_route_params_from_submesh(submesh: object) -> dict[str, object]:
        params: dict[str, object] = {}
        attr_params = (
            ("cdmw_material_authority_profile", "material_authority_profile"),
            ("cdmw_material_authority_contract", "material_authority_contract"),
            ("cdmw_source_material_name", "source_material_name"),
            ("cdmw_target_material_name", "target_material_name"),
            ("cdmw_target_material_slot_index", "target_material_slot_index"),
            ("cdmw_material_slot_kind", "slot_kind"),
            ("cdmw_source_texture_set_key", "source_texture_set_key"),
            ("cdmw_material_route_status", "route_status"),
            ("cdmw_material_route_reason", "route_reason"),
        )
        for attr_name, param_name in attr_params:
            if hasattr(submesh, attr_name):
                params[param_name] = getattr(submesh, attr_name)
        overrides = getattr(submesh, "preview_native_material_overrides", None)
        if isinstance(overrides, Mapping):
            params["preview_native_material_overrides"] = dict(overrides)
        if "material_authority_profile" not in params and callable(_current_complete_swap_material_profile_token):
            profile = str(_current_complete_swap_material_profile_token() or "").strip()
            if profile:
                params["material_authority_profile"] = profile
        return params

    def _mesh_editor_material_assign_params(action_text: str) -> dict[str, object] | None:
        choice = _mesh_editor_prompt_material_part(action_text, "Assign selected elements to material part:")
        if choice is None:
            return None
        params = {
            "material": str(choice.get("material", "") or ""),
            "texture": str(choice.get("texture", "") or ""),
            "target_material_name": str(choice.get("material", "") or ""),
        }
        params.update(_mesh_editor_material_route_params_from_submesh(choice.get("submesh")))
        return params

    def _mesh_editor_material_copy_params(action_text: str) -> dict[str, object] | None:
        choice = _mesh_editor_prompt_material_part(action_text, "Copy material routing from part:")
        if choice is None:
            return None
        return {"source_submesh_index": int(choice.get("source_index", -1))}

    def _mesh_editor_action_bar_action_requested(action: object) -> bool:
        key = str(getattr(action, "key", "") or "").strip()
        text = str(getattr(action, "text", "") or key or "tool").strip()
        command = str(getattr(action, "command", "") or "").strip()
        mode = str(getattr(action, "mode", "") or "").strip()
        selection_mode = str(getattr(action, "selection_mode", "") or "").strip()
        params = dict(tuple(getattr(action, "params", ()) or ()))
        if _mesh_edit_worker_active():
            self.set_status_message("Wait for the current mesh edit to finish, or cancel it first.", error=True)
            return True
        service_topology_actions = {
            "dissolve",
            "duplicate",
            "mirror",
            "extrude",
            "inset",
            "merge",
            "weld",
            "fill",
            "uv_transform",
            "recalculate_normals",
            "generate_tangents",
            "flip_normals",
            "sharpen_normals",
            "soften_normals",
            "weighted_normals",
            "copy_normals",
        }
        service_cleanup_actions = {
            "remove_doubles",
            "delete_loose_vertices",
            "compact_orphans",
            "fix_winding",
            "fill_holes",
        }
        service_non_topology_actions = {
            "uv_transform",
            "recalculate_normals",
            "generate_tangents",
            "flip_normals",
            "sharpen_normals",
            "soften_normals",
            "weighted_normals",
            "copy_normals",
        }
        edge_service_actions = {"loop_cut", "edge_split", "bridge"}
        if command == "set_mode":
            if mode == "object":
                _set_mesh_edit_enabled(False)
                return True
            _show_mesh_edit_tab()
            _set_mesh_edit_enabled(True)
            if mode == "edit":
                mesh_editor_action_bar_selection_mode["value"] = "vertex"
                return _select_mesh_edit_tool("vertex")
            if mode == "sculpt":
                return _select_mesh_edit_tool(_mesh_edit_current_tool() if _mesh_edit_current_tool() != "vertex" else "grab")
            return False
        if command == "select":
            if selection_mode not in {"vertex", "edge", "face"}:
                return False
            mesh_editor_action_bar_selection_mode["value"] = selection_mode
            _show_mesh_edit_tab()
            _set_mesh_edit_enabled(True)
            return _select_mesh_edit_tool("vertex")
        if key == "transform_rotate":
            degrees = _mesh_editor_prompt_action_value(text, "Rotate selected elements around Z axis (degrees):", 15.0, -360.0, 360.0, 2)
            if degrees is None:
                return True
            return _mesh_editor_apply_action_bar_service_action(
                "transform",
                action_key=key,
                action_text=text,
                params={"rotate": (0.0, 0.0, degrees)},
                topology_action=False,
            )
        if key == "transform_scale":
            factor = _mesh_editor_prompt_action_value(text, "Uniform scale selected elements:", 1.1, 0.01, 100.0, 4)
            if factor is None:
                return True
            return _mesh_editor_apply_action_bar_service_action(
                "transform",
                action_key=key,
                action_text=text,
                params={"scale": (factor, factor, factor)},
                topology_action=False,
            )
        if key == "transform_move":
            _show_mesh_edit_tab()
            _set_mesh_edit_enabled(True)
            return _select_mesh_edit_tool("grab", active_action_key="transform_move")
        if command == "brush":
            tool = str(params.get("tool") or "grab").strip()
            _show_mesh_edit_tab()
            _set_mesh_edit_enabled(True)
            active_key = key or _mesh_editor_tool_action_key(tool)
            return _select_mesh_edit_tool(tool, active_action_key=active_key)
        if command in service_topology_actions:
            return _mesh_editor_apply_action_bar_service_action(
                command,
                action_key=key or command,
                action_text=text,
                params=params,
                topology_action=command not in service_non_topology_actions,
            )
        if command in {"triangulate_display", "quadrangulate_display"}:
            self.set_status_message(
                f"{text} is legacy display-shape cleanup and is not available in active Mesh Edit.",
                error=True,
            )
            return True
        if command in service_cleanup_actions:
            return _mesh_editor_apply_action_bar_service_action(
                command,
                action_key=key or command,
                action_text=text,
                params=params,
                topology_action=True,
                require_selection=False,
            )
        if command == "material_assign":
            return _mesh_editor_apply_action_bar_service_action(
                command,
                action_key=key or command,
                action_text=text,
                params_factory=lambda: _mesh_editor_material_assign_params(text),
                topology_action=False,
            )
        if command == "material_copy":
            return _mesh_editor_apply_action_bar_service_action(
                command,
                action_key=key or command,
                action_text=text,
                params_factory=lambda: _mesh_editor_material_copy_params(text),
                topology_action=False,
            )
        if command in edge_service_actions:
            return _mesh_editor_apply_action_bar_service_action(
                command,
                action_key=key or command,
                action_text=text,
                params=params,
                topology_action=True,
                edge_action=True,
            )
        if command == "delete":
            _show_mesh_edit_tab()
            _mesh_edit_delete_selected_faces()
            return True
        if command == "subdivide":
            _show_mesh_edit_tab()
            _mesh_edit_subdivide_selection()
            return True
        if command == "refine_smooth":
            _show_mesh_edit_tab()
            _mesh_edit_subdivide_selection(refine_smooth=True)
            return True
        if command in {"split", "separate"}:
            _show_mesh_edit_tab()
            _mesh_edit_split_selection_to_part()
            return True
        if command == "undo":
            _mesh_edit_undo()
            return True
        if command == "redo":
            _mesh_edit_redo()
            return True
        return False

    def _refresh_mesh_edit_controls() -> None:
        _refresh_mesh_edit_part_combo()
        allowed_indices = set(_mesh_edit_allowed_source_indices())
        mesh_edit_selected_source_indices.intersection_update(allowed_indices)
        pruned_selected_vertices = _mesh_edit_pruned_index_groups_helper(
            mesh_edit_selected_vertices_by_submesh,
            allowed_indices,
        )
        mesh_edit_selected_vertices_by_submesh.clear()
        mesh_edit_selected_vertices_by_submesh.update(pruned_selected_vertices)
        topology_busy = _mesh_edit_worker_active()
        can_edit, reason = _mesh_edit_can_edit_scope()
        mesh_edit_group.setEnabled(mesh_edit_supported)
        set_toolbar_visible = getattr(classic_mesh_edit_toolbar, "setVisible", None)
        if callable(set_toolbar_visible):
            set_toolbar_visible(bool(mesh_edit_supported and mesh_edit_enabled_checkbox.isChecked()))
        mesh_edit_enabled_checkbox.setEnabled(mesh_edit_supported and not topology_busy)
        if not mesh_edit_supported:
            mesh_edit_enabled_checkbox.blockSignals(True)
            mesh_edit_enabled_checkbox.setChecked(False)
            mesh_edit_enabled_checkbox.blockSignals(False)
        editing_requested = _mesh_edit_editing_requested_helper(
            checkbox_checked=bool(mesh_edit_enabled_checkbox.isChecked()),
            mesh_edit_supported=mesh_edit_supported,
            mesh_edit_tab_active=_mesh_edit_tab_active(),
        )
        editing_active = _mesh_edit_editing_active_helper(
            editing_requested=editing_requested,
            can_edit=can_edit,
        ) and not topology_busy
        current_tool = _mesh_edit_current_tool()
        selected_count = _mesh_edit_index_group_count_helper(mesh_edit_selected_vertices_by_submesh)
        selected_count += _mesh_edit_selected_source_vertex_count(allowed_indices=allowed_indices)
        selected_face_count = _mesh_edit_index_group_count_helper(mesh_edit_selected_faces_by_submesh)
        selected_edge_count = _mesh_editor_selected_edge_count()
        selected_element_count = selected_count + selected_face_count + selected_edge_count
        tool_context = _mesh_edit_tool_context_helper(
            current_tool,
            _mesh_edit_selection_mode(),
            selected_count,
            editing_active=editing_active,
        )
        sculpt_tool = bool(tool_context["sculpt_tool"])
        remove_tool = bool(tool_context["remove_tool"])
        select_tool = bool(tool_context["select_tool"])
        brush_selection_tool = bool(tool_context["brush_selection_tool"])
        vertex_selection_active = bool(tool_context["selection_active"])
        selection_active = bool(editing_active and selected_element_count > 0)
        selection_actions_visible = bool(select_tool or selected_element_count > 0)
        smooth_tool = bool(tool_context["smooth_tool"])

        def _set_mesh_edit_row_visible(row_key: str, visible: bool) -> None:
            row = mesh_edit_field_rows.get(str(row_key))
            if row is None:
                return
            label, widget = row
            label.setVisible(bool(visible))
            widget.setVisible(bool(visible))

        for tool, button in mesh_edit_tool_buttons.items():
            button.setChecked(tool == current_tool)
        for widget in (
            mesh_edit_scope_combo,
            mesh_edit_part_combo,
            mesh_edit_tool_palette,
            mesh_edit_show_vertices_checkbox,
        ):
            widget.setEnabled(editing_requested and not topology_busy)
        mesh_edit_part_combo.setEnabled(editing_requested and not topology_busy and _mesh_edit_scope_mode() == "selected")
        _set_mesh_edit_row_visible("scope", True)
        _set_mesh_edit_row_visible("part", True)
        _set_mesh_edit_row_visible("radius", sculpt_tool or remove_tool or brush_selection_tool)
        _set_mesh_edit_row_visible("strength", sculpt_tool)
        _set_mesh_edit_row_visible("falloff", sculpt_tool)
        _set_mesh_edit_row_visible("iterations", smooth_tool)
        _set_mesh_edit_row_visible("selection", select_tool)
        _set_mesh_edit_row_visible("depth", select_tool)
        mesh_edit_delete_mode_combo.setEnabled(editing_requested and not topology_busy and remove_tool)
        mesh_edit_remove_mode_label.setVisible(remove_tool)
        mesh_edit_delete_mode_combo.setVisible(remove_tool)
        mesh_edit_radius_spin.setEnabled(editing_requested and not topology_busy and (sculpt_tool or remove_tool or brush_selection_tool))
        mesh_edit_strength_spin.setEnabled(editing_requested and not topology_busy and sculpt_tool)
        mesh_edit_falloff_combo.setEnabled(editing_requested and not topology_busy and sculpt_tool)
        mesh_edit_iterations_spin.setEnabled(editing_requested and not topology_busy and smooth_tool)
        mesh_edit_selection_mode_combo.setEnabled(editing_requested and not topology_busy and select_tool)
        mesh_edit_selection_depth_combo.setEnabled(editing_requested and not topology_busy and select_tool)
        for widget in (compact_selection_mode_combo, compact_selection_depth_combo):
            if widget is not None:
                widget.setVisible(select_tool)
                widget.setEnabled(editing_requested and not topology_busy and select_tool)
        mesh_edit_mirror_checkbox.setVisible(sculpt_tool)
        mesh_edit_mirror_checkbox.setEnabled(editing_requested and not topology_busy and sculpt_tool)
        mesh_edit_option_widget.setVisible(True)
        mesh_edit_clear_selection_button.setVisible(selection_actions_visible)
        mesh_edit_select_part_button.setVisible(select_tool)
        mesh_edit_invert_selection_button.setVisible(select_tool)
        mesh_edit_selection_actions_widget.setVisible(selection_actions_visible)
        mesh_edit_subdivide_selection_button.setVisible(select_tool)
        mesh_edit_refine_smooth_selection_button.setVisible(select_tool)
        mesh_edit_split_selection_button.setVisible(select_tool)
        mesh_edit_delete_faces_button.setVisible(select_tool)
        mesh_edit_clear_selection_button.setEnabled(selection_active and not topology_busy)
        mesh_edit_select_part_button.setEnabled(editing_active and select_tool and bool(allowed_indices) and not topology_busy)
        mesh_edit_invert_selection_button.setEnabled(editing_active and select_tool and bool(allowed_indices) and not topology_busy)
        mesh_edit_grow_selection_button.setEnabled(vertex_selection_active and not topology_busy)
        mesh_edit_shrink_selection_button.setEnabled(vertex_selection_active and not topology_busy)
        mesh_edit_smooth_selection_button.setEnabled(vertex_selection_active and not topology_busy)
        mesh_edit_subdivide_selection_button.setEnabled(
            select_tool and selection_active and not topology_busy and not _morph_slider_has_nonzero_values()
        )
        mesh_edit_refine_smooth_selection_button.setEnabled(
            select_tool and selection_active and not topology_busy and not _morph_slider_has_nonzero_values()
        )
        mesh_edit_split_selection_button.setEnabled(
            select_tool and selection_active and not topology_busy and not _morph_slider_has_nonzero_values()
        )
        mesh_edit_delete_faces_button.setEnabled(
            select_tool and selection_active and not topology_busy
        )
        mesh_edit_undo_button.setEnabled(bool(mesh_edit_undo_stack) and not topology_busy)
        mesh_edit_redo_button.setEnabled(bool(mesh_edit_redo_stack) and not topology_busy)
        mesh_edit_reset_part_button.setEnabled(
            not topology_busy and _mesh_edit_reset_available_helper(
                _mesh_edit_state.replacement_mesh_base_for_mapping,
                is_base_source_index_editable=_mesh_edit_base_source_index_is_editable,
            )
        )
        mesh_edit_full_reset_button.setEnabled(mesh_edit_reset_part_button.isEnabled())
        mesh_edit_status_label.setText(
            _mesh_edit_control_status_text_helper(
                reason,
                selected_count,
                int(mesh_edit_revision.get("value", 0) or 0),
                editing_active=editing_active,
            )
        )
        compact_status_set_text = getattr(compact_mesh_edit_status_label, "setText", None)
        if callable(compact_status_set_text):
            compact_status_set_text(mesh_edit_status_label.text())
        for compact_button, source_button in (
            (compact_mesh_edit_clear_button, mesh_edit_clear_selection_button),
            (compact_mesh_edit_grow_button, mesh_edit_grow_selection_button),
            (compact_mesh_edit_shrink_button, mesh_edit_shrink_selection_button),
            (compact_mesh_edit_feather_button, mesh_edit_smooth_selection_button),
            (compact_mesh_edit_reset_scope_button, mesh_edit_reset_part_button),
        ):
            set_enabled = getattr(compact_button, "setEnabled", None)
            is_enabled = getattr(source_button, "isEnabled", None)
            if callable(set_enabled) and callable(is_enabled):
                set_enabled(bool(editing_requested and is_enabled()))
        _sync_mesh_editor_tab_action_state(
            editing_active=editing_active,
            sculpt_tool=sculpt_tool,
            selected_count=selected_count,
            selected_face_count=selected_face_count,
            selected_edge_count=selected_edge_count,
        )
        _morph_slider_refresh_controls()
        _sync_mesh_edit_preview_settings()

    def _mesh_edit_capture_undo_snapshot(snapshot: object, *, take_ownership: bool = False) -> object | None:
        if isinstance(snapshot, ParsedMesh):
            try:
                from cdmw.modding.mesh_native_core import snapshot_native_mesh_submeshes

                native_snapshot = snapshot_native_mesh_submeshes(snapshot)
            except Exception:
                native_snapshot = None
            if native_snapshot is not None:
                return native_snapshot
            _record_mesh_edit_event(
                "mesh_edit_native_undo_snapshot_failed",
                message="Native undo snapshot failed; Python full-mesh undo snapshot fallback is disabled.",
            )
            self.set_status_message(
                "Native undo snapshot failed; Python full-mesh undo snapshot fallback is disabled.",
                error=True,
            )
            return None
        return snapshot

    def _mesh_edit_restore_undo_snapshot(snapshot: object) -> ParsedMesh | None:
        if isinstance(snapshot, ParsedMesh):
            return None
        if isinstance(snapshot, Mapping) and snapshot.get("kind") == "native_submesh_snapshot":
            try:
                from cdmw.modding.mesh_native_core import restore_native_mesh_submesh_snapshot

                restored = ParsedMesh()
                if restore_native_mesh_submesh_snapshot(restored, snapshot):
                    return restored
            except Exception:
                return None
        return None

    def _mesh_edit_push_undo_snapshot(snapshot: ParsedMesh, *, take_ownership: bool = False) -> bool:
        stored_snapshot = _mesh_edit_capture_undo_snapshot(snapshot, take_ownership=take_ownership)
        if stored_snapshot is None:
            return False
        mesh_edit_undo_stack.append(stored_snapshot)
        retain_mesh_history_snapshot(stored_snapshot)
        mesh_edit_undo_adjustment_stack.append(_mesh_edit_part_enabled_snapshot())
        if len(mesh_edit_undo_stack) > 30:
            release_mesh_history_snapshot(mesh_edit_undo_stack.pop(0))
            if mesh_edit_undo_adjustment_stack:
                del mesh_edit_undo_adjustment_stack[0]
        clear_mesh_history_snapshot_stack(mesh_edit_redo_stack)
        mesh_edit_redo_adjustment_stack.clear()
        return True

    def _mesh_edit_pop_undo_snapshot() -> None:
        if mesh_edit_undo_stack:
            release_mesh_history_snapshot(mesh_edit_undo_stack.pop())
        if mesh_edit_undo_adjustment_stack:
            mesh_edit_undo_adjustment_stack.pop()

    def _mesh_edit_pop_active_stroke_snapshots() -> None:
        if bool(mesh_edit_active_stroke.get("undo_snapshot_pushed", True)):
            _mesh_edit_pop_undo_snapshot()
        if bool(mesh_edit_active_stroke.get("geometry_snapshot_pushed", True)):
            _pop_geometry_undo_snapshot()

    _mesh_edit_part_enabled_snapshot = lambda: _mesh_edit_part_enabled_snapshot_helper(
        _mesh_edit_state.replacement_mesh_for_mapping,
        source_part_adjustments,
    )

    def _mesh_edit_source_enable_mutation_blocked(action: str, source_indices: object = ()) -> None:
        message = (
            "Active Mesh Editor source enable changes require native part-state execution; "
            "Python source adjustment mutation fallback is disabled."
        )
        _record_mesh_edit_event(
            "mesh_edit_source_enable_mutation_blocked",
            action=str(action or "source_enable"),
            source_indices=tuple(source_indices or ()),
            message=message,
        )
        self.set_status_message(message, error=True)

    def _mesh_edit_restore_enabled_snapshot(snapshot: Mapping[int, bool]) -> None:
        snapshot_items = tuple(_mesh_edit_enabled_snapshot_items_helper(snapshot))
        if snapshot_items:
            _mesh_edit_source_enable_mutation_blocked(
                "history.restore_source_enable",
                (source_index for source_index, _enabled in snapshot_items),
            )

    def _sync_source_tree_enabled_checks() -> None:
        source_tree_item_update_guard["active"] = True
        try:
            for source_index, source_item in source_items_by_index.items():
                adjustment = source_part_adjustments.get(int(source_index))
                source_item.setCheckState(0, Qt.Checked if adjustment is None or bool(adjustment.enabled) else Qt.Unchecked)
        finally:
            source_tree_item_update_guard["active"] = False

    def _mesh_edit_disable_emptied_parts(source_indices: Sequence[int]) -> None:
        if source_indices:
            _mesh_edit_source_enable_mutation_blocked("topology.disable_emptied_parts", source_indices)
        _sync_source_tree_enabled_checks()

    def _mesh_edit_record_snapshot() -> None:
        if _mesh_edit_state.replacement_mesh_for_mapping is None:
            return
        _push_geometry_undo_snapshot("Mesh edit")
        if not _mesh_edit_push_undo_snapshot(_mesh_edit_state.replacement_mesh_for_mapping):
            _pop_geometry_undo_snapshot()

    def _mesh_edit_restore_base_sources_native(source_indices: Sequence[int], *, operation: str) -> bool:
        if _mesh_edit_state.replacement_mesh_for_mapping is None or _mesh_edit_state.replacement_mesh_base_for_mapping is None:
            return False
        try:
            from cdmw.modding.mesh_native_core import restore_native_mesh_submeshes_from_mesh

            return restore_native_mesh_submeshes_from_mesh(
                _mesh_edit_state.replacement_mesh_for_mapping,
                _mesh_edit_state.replacement_mesh_base_for_mapping,
                source_indices,
                timeout_seconds=20.0,
            )
        except Exception as exc:
            _record_mesh_edit_event(
                "mesh_edit_native_base_restore_failed",
                operation=str(operation or "mesh_edit.reset"),
                message=str(exc),
                source_indices=tuple(source_indices or ()),
            )
            return False

    def _mesh_edit_abort_recorded_snapshot() -> None:
        _mesh_edit_pop_undo_snapshot()
        _pop_geometry_undo_snapshot()

    def _mesh_edit_replace_working_mesh(snapshot: object, *, native_update: object | None = None) -> None:
        if _mesh_edit_restore_sparse_vertex_snapshot(snapshot, increment_revision=True, include_normals=True):
            return
        restored_snapshot = _mesh_edit_restore_undo_snapshot(snapshot)
        if restored_snapshot is None:
            return
        mesh_edit_native_result_submesh_counts["value"] = ()
        _mesh_edit_state.replacement_mesh_for_mapping = restored_snapshot
        native_update_applied = bool(
            native_update is not None
            and _alignment_d3d11_preview_active()
            and _mesh_editor_apply_native_update(native_update)
        )
        if native_update_applied:
            mesh_edit_preview_model_dirty["value"] = True
        else:
            _morph_slider_capture_post_edit_deltas()
            _mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)
        mesh_edit_revision["value"] = int(mesh_edit_revision.get("value", 0) or 0) + 1
        _mesh_edit_commit_geometry_preview_state()
        _sync_source_tree_enabled_checks()
        _refresh_source_assignment_columns()
        _refresh_mesh_edit_controls()
        if not native_update_applied:
            _mesh_edit_replace_live_triangles_or_queue_rebuild(_mesh_edit_preview_source_indices(), replace_all=True)

    def _mesh_edit_replace_result_working_mesh(result: object) -> None:
        native_update = getattr(result, "native_update", None)
        if _mesh_editor_result_has_deferred_native_python_apply(result):
            if not _mesh_editor_store_result_mesh(result):
                return
            mesh_edit_revision["value"] = int(mesh_edit_revision.get("value", 0) or 0) + 1
            _mesh_edit_commit_geometry_preview_state()
            _sync_source_tree_enabled_checks()
            _refresh_source_assignment_columns()
            _refresh_mesh_edit_controls()
            if native_update is not None and _alignment_d3d11_preview_active() and _mesh_editor_apply_native_update(native_update):
                return
            raise RuntimeError("native deferred history result did not include preview payload; Python mesh replacement is disabled")
        _mesh_edit_replace_working_mesh(
            _mesh_editor_result_mesh_for_state(result),
            native_update=native_update,
        )

    def _mesh_edit_undo() -> None:
        if _mesh_edit_state.replacement_mesh_for_mapping is None or not mesh_edit_undo_stack:
            return
        mesh_editor_session = _mesh_editor_fresh_static_replacement_session()
        if mesh_editor_session is not None and mesh_editor_session.view().undo_count > 0:
            redo_snapshot = _mesh_edit_capture_undo_snapshot(_mesh_edit_state.replacement_mesh_for_mapping)
            if redo_snapshot is None:
                return
            result = mesh_editor_session.undo()
            mesh_edit_redo_stack.append(redo_snapshot)
            retain_mesh_history_snapshot(redo_snapshot)
            mesh_edit_redo_adjustment_stack.append(_mesh_edit_part_enabled_snapshot())
            adjustment_snapshot = (
                mesh_edit_undo_adjustment_stack.pop()
                if mesh_edit_undo_adjustment_stack
                else _mesh_edit_part_enabled_snapshot()
            )
            release_mesh_history_snapshot(mesh_edit_undo_stack.pop())
            _mesh_edit_restore_enabled_snapshot(adjustment_snapshot)
            _mesh_edit_replace_result_working_mesh(result)
            _mesh_editor_remember_static_replacement_session_mesh()
            return
        snapshot = mesh_edit_undo_stack.pop()
        current_snapshot = _mesh_edit_current_sparse_vertex_snapshot(snapshot)
        redo_snapshot = (
            current_snapshot
            if current_snapshot is not None
            else _mesh_edit_capture_undo_snapshot(_mesh_edit_state.replacement_mesh_for_mapping)
        )
        if redo_snapshot is None:
            mesh_edit_undo_stack.append(snapshot)
            return
        mesh_edit_redo_stack.append(redo_snapshot)
        retain_mesh_history_snapshot(redo_snapshot)
        mesh_edit_redo_adjustment_stack.append(_mesh_edit_part_enabled_snapshot())
        adjustment_snapshot = (
            mesh_edit_undo_adjustment_stack.pop()
            if mesh_edit_undo_adjustment_stack
            else _mesh_edit_part_enabled_snapshot()
        )
        _mesh_edit_restore_enabled_snapshot(adjustment_snapshot)
        _mesh_edit_replace_working_mesh(snapshot)
        release_mesh_history_snapshot(snapshot)

    def _mesh_edit_redo() -> None:
        if _mesh_edit_state.replacement_mesh_for_mapping is None or not mesh_edit_redo_stack:
            return
        mesh_editor_session = _mesh_editor_fresh_static_replacement_session()
        if mesh_editor_session is not None and mesh_editor_session.view().redo_count > 0:
            undo_snapshot = _mesh_edit_capture_undo_snapshot(_mesh_edit_state.replacement_mesh_for_mapping)
            if undo_snapshot is None:
                return
            result = mesh_editor_session.redo()
            mesh_edit_undo_stack.append(undo_snapshot)
            retain_mesh_history_snapshot(undo_snapshot)
            mesh_edit_undo_adjustment_stack.append(_mesh_edit_part_enabled_snapshot())
            adjustment_snapshot = (
                mesh_edit_redo_adjustment_stack.pop()
                if mesh_edit_redo_adjustment_stack
                else _mesh_edit_part_enabled_snapshot()
            )
            release_mesh_history_snapshot(mesh_edit_redo_stack.pop())
            _mesh_edit_restore_enabled_snapshot(adjustment_snapshot)
            _mesh_edit_replace_result_working_mesh(result)
            _mesh_editor_remember_static_replacement_session_mesh()
            return
        snapshot = mesh_edit_redo_stack.pop()
        current_snapshot = _mesh_edit_current_sparse_vertex_snapshot(snapshot)
        undo_snapshot = (
            current_snapshot
            if current_snapshot is not None
            else _mesh_edit_capture_undo_snapshot(_mesh_edit_state.replacement_mesh_for_mapping)
        )
        if undo_snapshot is None:
            mesh_edit_redo_stack.append(snapshot)
            return
        mesh_edit_undo_stack.append(undo_snapshot)
        retain_mesh_history_snapshot(undo_snapshot)
        mesh_edit_undo_adjustment_stack.append(_mesh_edit_part_enabled_snapshot())
        adjustment_snapshot = (
            mesh_edit_redo_adjustment_stack.pop()
            if mesh_edit_redo_adjustment_stack
            else _mesh_edit_part_enabled_snapshot()
        )
        _mesh_edit_restore_enabled_snapshot(adjustment_snapshot)
        _mesh_edit_replace_working_mesh(snapshot)
        release_mesh_history_snapshot(snapshot)

    def _mesh_edit_reset_scope() -> None:
        if _mesh_edit_state.replacement_mesh_for_mapping is None or _mesh_edit_state.replacement_mesh_base_for_mapping is None:
            return
        source_indices = _mesh_edit_reset_scope_source_indices_helper(
            _mesh_edit_state.replacement_mesh_for_mapping,
            _mesh_edit_state.replacement_mesh_base_for_mapping,
            scope_mode=_mesh_edit_scope_mode(),
            selected_scope_source_index=_mesh_edit_selected_scope_source_index(),
            is_base_source_index_editable=_mesh_edit_base_source_index_is_editable,
        )
        if not source_indices:
            return
        restore_deleted_output_by_source: dict[int, bool] = {}
        for source_index in source_indices:
            working_source = _mesh_edit_state.replacement_mesh_for_mapping.submeshes[source_index]
            base_source = _mesh_edit_state.replacement_mesh_base_for_mapping.submeshes[source_index]
            restore_deleted_output_by_source[source_index] = _mesh_edit_should_restore_deleted_output_helper(
                working_source,
                base_source,
        )
        _mesh_edit_record_snapshot()
        if not _mesh_edit_restore_base_sources_native(source_indices, operation="mesh_edit.reset_scope"):
            _mesh_edit_abort_recorded_snapshot()
            self.set_status_message(
                "Native Mesh Editor reset failed; Python geometry clone fallback is disabled.",
                error=True,
            )
            return
        for source_index in source_indices:
            mesh_edit_selected_vertices_by_submesh.pop(source_index, None)
            mesh_edit_selected_source_indices.discard(source_index)
        restore_deleted_sources = tuple(
            source_index for source_index in source_indices if restore_deleted_output_by_source.get(source_index)
        )
        if restore_deleted_sources:
            _mesh_edit_source_enable_mutation_blocked("reset.restore_deleted_output", restore_deleted_sources)
        if _morph_slider_has_loaded_deltas():
            _morph_slider_zero_post_edit_deltas_for_sources(source_indices)
            if _morph_slider_refresh_topology_block_state():
                _morph_slider_apply_to_working_mesh(increment_revision=False, refresh_controls=False)
        _mesh_edit_update_mesh_totals()
        _mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)
        mesh_edit_revision["value"] = int(mesh_edit_revision.get("value", 0) or 0) + 1
        _mesh_edit_commit_geometry_preview_state()
        _sync_source_tree_enabled_checks()
        _refresh_source_tree_selection_state()
        _refresh_source_assignment_columns()
        _refresh_mesh_edit_controls()
        _mesh_edit_replace_live_triangles_or_queue_rebuild(source_indices)

    def _mesh_edit_full_reset_mesh() -> None:
        if _mesh_edit_state.replacement_mesh_for_mapping is None or _mesh_edit_state.replacement_mesh_base_for_mapping is None:
            return
        source_indices = _mesh_edit_full_reset_source_indices_helper(
            _mesh_edit_state.replacement_mesh_for_mapping,
            _mesh_edit_state.replacement_mesh_base_for_mapping,
            is_base_source_index_editable=_mesh_edit_base_source_index_is_editable,
        )
        if not source_indices:
            return
        restore_deleted_output_by_source: dict[int, bool] = {}
        for source_index in source_indices:
            working_source = _mesh_edit_state.replacement_mesh_for_mapping.submeshes[source_index]
            base_source = _mesh_edit_state.replacement_mesh_base_for_mapping.submeshes[source_index]
            restore_deleted_output_by_source[source_index] = _mesh_edit_should_restore_deleted_output_helper(
                working_source,
                base_source,
        )
        _mesh_edit_record_snapshot()
        if not _mesh_edit_restore_base_sources_native(source_indices, operation="mesh_edit.full_reset"):
            _mesh_edit_abort_recorded_snapshot()
            self.set_status_message(
                "Native Mesh Editor full reset failed; Python geometry clone fallback is disabled.",
                error=True,
            )
            return
        restore_deleted_sources = tuple(
            source_index for source_index in source_indices if restore_deleted_output_by_source.get(source_index)
        )
        if restore_deleted_sources:
            _mesh_edit_source_enable_mutation_blocked("full_reset.restore_deleted_output", restore_deleted_sources)
        mesh_edit_selected_vertices_by_submesh.clear()
        mesh_edit_selected_edges_by_submesh.clear()
        mesh_edit_selected_faces_by_submesh.clear()
        mesh_edit_selected_source_indices.clear()
        if _morph_slider_has_loaded_deltas():
            _morph_slider_zero_post_edit_deltas_for_sources(source_indices)
            _morph_slider_refresh_topology_block_state()
        _mesh_edit_update_mesh_totals()
        _mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)
        mesh_edit_revision["value"] = int(mesh_edit_revision.get("value", 0) or 0) + 1
        _mesh_edit_commit_geometry_preview_state()
        _sync_source_tree_enabled_checks()
        _refresh_source_tree_selection_state()
        _refresh_source_assignment_columns()
        _refresh_mesh_edit_controls()
        if _alignment_d3d11_preview_active():
            alignment_d3d11_preview_host.clear_mesh_edit_vertex_selection()
        _mesh_edit_replace_live_triangles_or_queue_rebuild(source_indices)

    def _record_mesh_edit_event(event_name: str, **payload: object) -> None:
        if callable(_record_runtime_event):
            _record_runtime_event(event_name, **payload)

    def _mesh_edit_mark_native_preview_stale(message: str, **payload: object) -> None:
        _record_mesh_edit_event("mesh_edit_native_preview_stale", message=message, **payload)
        self.set_status_message(message, error=True)

    def _mesh_edit_capture_live_stroke_base_snapshot(mesh: ParsedMesh) -> object | None:
        try:
            from cdmw.modding.mesh_native_core import snapshot_native_mesh_submeshes

            native_snapshot = snapshot_native_mesh_submeshes(mesh)
        except Exception:
            native_snapshot = None
        if native_snapshot is not None:
            return native_snapshot
        _record_mesh_edit_event(
            "mesh_edit_native_live_stroke_snapshot_failed",
            message="Native live stroke snapshot failed; Python full-mesh live stroke clone fallback is disabled.",
        )
        self.set_status_message(
            "Native live stroke snapshot failed; Python full-mesh live stroke clone fallback is disabled.",
            error=True,
        )
        return None

    def _mesh_edit_restore_live_stroke_base_snapshot(snapshot: object) -> bool:
        if isinstance(snapshot, Mapping) and snapshot.get("kind") == "native_submesh_snapshot":
            try:
                from cdmw.modding.mesh_native_core import restore_native_mesh_submesh_snapshot

                restored = ParsedMesh()
                if restore_native_mesh_submesh_snapshot(restored, snapshot):
                    _mesh_edit_state.replacement_mesh_for_mapping = restored
                    return True
            except Exception:
                return False
            return False
        if isinstance(snapshot, ParsedMesh):
            return False
        return False

    def _mesh_edit_clear_active_stroke() -> None:
        release_mesh_history_snapshot(mesh_edit_active_stroke.get("base"))
        mesh_edit_active_stroke.clear()

    def _mesh_edit_python_normal_fallback_allowed(mesh: ParsedMesh, source_indices: Iterable[int]) -> bool:
        normalized: set[int] = set()
        for raw_index in source_indices or ():
            try:
                source_index = int(raw_index)
            except (TypeError, ValueError, OverflowError):
                continue
            if source_index >= 0:
                normalized.add(source_index)
        message = "Native normal recompute failed; Python normal fallback is disabled."
        _record_mesh_edit_event(
            "mesh_edit_python_normals_fallback_blocked",
            source_indices=tuple(sorted(normalized)),
            message=message,
        )
        self.set_status_message(message, error=True)
        return False

    def _mesh_edit_sparse_restore_source_indices(before_by_submesh: object) -> tuple[int, ...]:
        if not isinstance(before_by_submesh, Mapping):
            return ()
        indices: set[int] = set()
        for raw_index in before_by_submesh:
            try:
                source_index = int(raw_index)
            except (TypeError, ValueError, OverflowError):
                continue
            if source_index >= 0:
                indices.add(source_index)
        return tuple(sorted(indices))

    def _mesh_edit_python_sparse_restore_fallback_allowed(mesh: ParsedMesh, before_by_submesh: object) -> bool:
        source_indices = _mesh_edit_sparse_restore_source_indices(before_by_submesh)
        message = "Native sparse history restore failed; Python restore fallback is disabled."
        _record_mesh_edit_event(
            "mesh_edit_python_sparse_restore_fallback_blocked",
            source_indices=source_indices,
            message=message,
        )
        self.set_status_message(message, error=True)
        return False

    def _mesh_edit_python_sparse_current_fallback_allowed(mesh: ParsedMesh, before_by_submesh: object) -> bool:
        source_indices = _mesh_edit_sparse_restore_source_indices(before_by_submesh)
        message = "Native sparse history current snapshot failed; Python snapshot fallback is disabled."
        _record_mesh_edit_event(
            "mesh_edit_python_sparse_current_fallback_blocked",
            source_indices=source_indices,
            message=message,
        )
        self.set_status_message(message, error=True)
        return False

    def _mesh_edit_source_to_preview_point(point: Sequence[object]) -> tuple[float, float, float]:
        normalizer = original_reference_preview_model or _mesh_edit_state.replacement_preview_model
        return _mesh_edit_source_to_preview_point_helper(
            point,
            normalization_center=getattr(normalizer, "normalization_center", (0.0, 0.0, 0.0)),
            normalization_scale=getattr(normalizer, "normalization_scale", 1.0),
        )

    _mesh_edit_stroke_id = lambda payload: _mesh_edit_stroke_id_helper(payload)

    def _mesh_edit_update_mesh_totals() -> None:
        if _mesh_edit_state.replacement_mesh_for_mapping is None:
            return
        native_counts = tuple(mesh_edit_native_result_submesh_counts.get("value") or ())
        if native_counts:
            _mesh_edit_state.replacement_mesh_for_mapping.total_vertices = sum(vertex_count for vertex_count, _ in native_counts)
            _mesh_edit_state.replacement_mesh_for_mapping.total_faces = sum(face_count for _, face_count in native_counts)
            return
        totals = _mesh_edit_mesh_totals_helper(_mesh_edit_state.replacement_mesh_for_mapping)
        _mesh_edit_state.replacement_mesh_for_mapping.total_vertices = int(totals["total_vertices"])
        _mesh_edit_state.replacement_mesh_for_mapping.total_faces = int(totals["total_faces"])
        _mesh_edit_state.replacement_mesh_for_mapping.has_uvs = bool(totals["has_uvs"])

    def _mesh_edit_adjusted_sources_for_live_preview(source_indices: Iterable[int]) -> Dict[int, object]:
        if _mesh_edit_state.replacement_mesh_for_mapping is None:
            return {}
        requested = _mesh_edit_requested_source_indices_helper(_mesh_edit_state.replacement_mesh_for_mapping, source_indices)
        if not requested:
            return {}
        transformed: Dict[int, object] = {}
        for source_index in requested:
            source = _mesh_edit_state.replacement_mesh_for_mapping.submeshes[source_index]
            adjustment = source_part_adjustments.get(source_index)
            transformed[source_index] = (
                source
                if adjustment is None or _is_default_source_part_adjustment(adjustment)
                else _copy_source_part_with_adjustment(source, adjustment)
            )
        return transformed

    def _mesh_edit_transformed_sources_for_live_preview(source_indices: Iterable[int]) -> Dict[int, object]:
        if _mesh_edit_state.replacement_mesh_for_mapping is None:
            return {}
        requested = _mesh_edit_requested_source_indices_helper(_mesh_edit_state.replacement_mesh_for_mapping, source_indices)
        if not requested:
            return {}
        if original_mesh_for_mapping is None:
            return _mesh_edit_adjusted_sources_for_live_preview(requested)
        if not all(
            callable(callback)
            for callback in (
                _transformed_replacement_sources,
                _current_dialog_mappings_for_preview,
                _current_static_alignment_transform,
                _current_source_part_adjustments,
                _current_texture_uv_transforms,
                _mapped_source_indices,
            )
        ):
            return _mesh_edit_adjusted_sources_for_live_preview(requested)
        try:
            current_mappings = _current_dialog_mappings_for_preview()
            transformed_sources = _transformed_replacement_sources(
                original_mesh_for_mapping,
                _mesh_edit_state.replacement_mesh_for_mapping,
                _current_static_alignment_transform(),
                _current_source_part_adjustments(),
                _current_texture_uv_transforms(),
                global_transform_exempt_indices=set(appended_source_indices),
                global_transform_source_indices=_mapped_source_indices(current_mappings),
                max_source_faces_per_submesh=0,
                output_source_indices=set(requested),
                alignment_basis_mesh=_mesh_edit_state.replacement_mesh_base_for_mapping or _mesh_edit_state.replacement_mesh_for_mapping,
            )
        except Exception as exc:
            _record_mesh_edit_event("mesh_edit_live_transform_error", message=str(exc))
            return _mesh_edit_adjusted_sources_for_live_preview(requested)
        return {
            source_index: transformed_sources[source_index]
            for source_index in requested
            if 0 <= source_index < len(transformed_sources)
        }

    def _mesh_edit_submesh_for_live_preview(source_index: int):
        if _mesh_edit_state.replacement_mesh_for_mapping is None or source_index < 0 or source_index >= len(_mesh_edit_state.replacement_mesh_for_mapping.submeshes):
            return None
        return _mesh_edit_transformed_sources_for_live_preview((source_index,)).get(source_index)

    mesh_edit_live_update_timer = QTimer(dialog)
    mesh_edit_live_update_timer.setSingleShot(True)
    mesh_edit_live_update_timer.setInterval(16)
    mesh_edit_pending_live_vertices: Dict[int, object] = {}
    mesh_edit_pending_live_normals = _mesh_edit_pending_live_normals_initial_state_helper()

    def _mesh_edit_source_space_live_update_allowed(source_indices: Iterable[int]) -> bool:
        if original_mesh_for_mapping is not None:
            return False
        for source_index in source_indices or ():
            adjustment = source_part_adjustments.get(source_index)
            if adjustment is not None and not _is_default_source_part_adjustment(adjustment):
                return False
        return True

    def _mesh_edit_affine_preview_transforms(
        source_indices: Iterable[int],
        *,
        include_normals: bool = False,
    ) -> tuple[Dict[int, tuple[float, ...]], Dict[int, tuple[float, ...]]]:
        if (
            original_mesh_for_mapping is None
            or _mesh_edit_state.replacement_mesh_for_mapping is None
            or not callable(source_affine_for_transformed_preview)
            or (include_normals and not callable(source_normal_transform_for_transformed_preview))
            or not all(
                callable(callback)
                for callback in (
                    _current_dialog_mappings_for_preview,
                    _current_static_alignment_transform,
                    _current_source_part_adjustments,
                    _mapped_source_indices,
                )
            )
        ):
            return {}, {}
        normalizer = original_reference_preview_model or _mesh_edit_state.replacement_preview_model
        try:
            current_mappings = _current_dialog_mappings_for_preview()
            mapped_sources = _mapped_source_indices(current_mappings)
            transforms: Dict[int, tuple[float, ...]] = {}
            normal_transforms: Dict[int, tuple[float, ...]] = {}
            for source_index in source_indices or ():
                transform_args = {
                    "source_part_adjustments": _current_source_part_adjustments(),
                    "global_transform_exempt_indices": set(appended_source_indices),
                    "global_transform_source_indices": mapped_sources,
                    "alignment_basis_mesh": _mesh_edit_state.replacement_mesh_base_for_mapping or _mesh_edit_state.replacement_mesh_for_mapping,
                }
                affine = source_affine_for_transformed_preview(
                    original_mesh_for_mapping,
                    _mesh_edit_state.replacement_mesh_for_mapping,
                    _current_static_alignment_transform(),
                    int(source_index),
                    normalization_center=getattr(normalizer, "normalization_center", (0.0, 0.0, 0.0)),
                    normalization_scale=getattr(normalizer, "normalization_scale", 1.0),
                    **transform_args,
                )
                if affine is None:
                    return {}, {}
                transforms[int(source_index)] = affine
                if include_normals:
                    normal_transform = source_normal_transform_for_transformed_preview(
                        original_mesh_for_mapping,
                        _mesh_edit_state.replacement_mesh_for_mapping,
                        _current_static_alignment_transform(),
                        int(source_index),
                        **transform_args,
                    )
                    if normal_transform is None:
                        return {}, {}
                    normal_transforms[int(source_index)] = normal_transform
        except Exception as exc:
            _record_mesh_edit_event("mesh_edit_live_affine_transform_error", message=str(exc))
            return {}, {}
        return transforms, normal_transforms

    def _mesh_edit_live_vertex_update_groups(
        changed_vertices_by_submesh: Mapping[int, object] | None,
        *,
        include_normals: bool = False,
    ) -> List[Dict[str, object]]:
        if _mesh_edit_state.replacement_mesh_for_mapping is None or not changed_vertices_by_submesh:
            return []
        requested_source_indices = _mesh_edit_requested_source_indices_helper(
            _mesh_edit_state.replacement_mesh_for_mapping,
            changed_vertices_by_submesh.keys(),
        )
        if not requested_source_indices:
            return []
        normalizer = original_reference_preview_model or _mesh_edit_state.replacement_preview_model
        if callable(_mesh_edit_native_live_vertex_update_groups_helper):
            position_transforms, normal_transforms = _mesh_edit_affine_preview_transforms(
                requested_source_indices,
                include_normals=include_normals,
            )
            native_groups = _mesh_edit_native_live_vertex_update_groups_helper(
                _mesh_edit_state.replacement_mesh_for_mapping,
                changed_vertices_by_submesh,
                normalization_center=getattr(normalizer, "normalization_center", (0.0, 0.0, 0.0)),
                normalization_scale=getattr(normalizer, "normalization_scale", 1.0),
                include_normals=include_normals,
                position_transform_by_source=position_transforms or None,
                normal_transform_by_source=normal_transforms or None,
                allow_source_space=_mesh_edit_source_space_live_update_allowed(requested_source_indices),
            )
            if native_groups:
                return native_groups
            if _alignment_d3d11_mesh_edit_commands_active():
                return []
        transformed_sources_by_index = _mesh_edit_transformed_sources_for_live_preview(
            requested_source_indices
        )
        return _mesh_edit_live_vertex_update_groups_helper(
            _mesh_edit_state.replacement_mesh_for_mapping,
            changed_vertices_by_submesh,
            transformed_sources_by_index,
            source_to_preview_point=_mesh_edit_source_to_preview_point,
            include_normals=include_normals,
        )

    def _flush_mesh_edit_live_vertex_updates() -> None:
        if _mesh_edit_state.replacement_mesh_for_mapping is None or not mesh_edit_pending_live_vertices:
            mesh_edit_pending_live_vertices.clear()
            mesh_edit_pending_live_normals["include"] = False
            return
        groups = _mesh_edit_live_vertex_update_groups(
            mesh_edit_pending_live_vertices,
            include_normals=bool(mesh_edit_pending_live_normals.get("include")),
        )
        pending_source_indices = _mesh_edit_requested_source_indices_helper(
            _mesh_edit_state.replacement_mesh_for_mapping,
            mesh_edit_pending_live_vertices.keys(),
        )
        mesh_edit_pending_live_vertices.clear()
        mesh_edit_pending_live_normals["include"] = False
        if _alignment_d3d11_mesh_edit_commands_active():
            if not groups:
                _record_mesh_edit_event(
                    "mesh_edit_live_vertex_update_empty",
                    source_indices=pending_source_indices,
                )
                _mesh_edit_mark_native_preview_stale(
                    "Native D3D11 mesh edit preview produced no vertex update payload; preview is stale. Reload D3D11 preview to resync.",
                    source_indices=pending_source_indices,
                )
                return
            if alignment_d3d11_preview_host.update_mesh_edit_vertices(groups):
                return
            source_indices = _mesh_edit_source_indices_from_groups(groups)
            _record_mesh_edit_event(
                "mesh_edit_live_vertex_update_failed",
                source_indices=source_indices,
                group_count=len(groups),
            )
            if source_indices and _mesh_edit_replace_live_triangles(source_indices):
                return
            _mesh_edit_mark_native_preview_stale(
                "Native D3D11 mesh edit preview update failed; preview is stale. Reload D3D11 preview to resync.",
                source_indices=source_indices,
                group_count=len(groups),
            )

    mesh_edit_live_update_timer.timeout.connect(_flush_mesh_edit_live_vertex_updates)

    def _queue_mesh_edit_live_vertex_updates(
        changed_vertices_by_submesh: Mapping[int, object] | None,
        *,
        include_normals: bool = False,
        immediate: bool = False,
    ) -> None:
        if not changed_vertices_by_submesh:
            return
        _mesh_edit_queue_live_vertex_updates_helper(mesh_edit_pending_live_vertices, changed_vertices_by_submesh)
        mesh_edit_pending_live_normals["include"] = bool(mesh_edit_pending_live_normals.get("include") or include_normals)
        if immediate:
            mesh_edit_live_update_timer.stop()
            _flush_mesh_edit_live_vertex_updates()
        elif not mesh_edit_live_update_timer.isActive():
            mesh_edit_live_update_timer.start()

    _mesh_edit_all_live_vertices_for_sources = lambda source_indices: _mesh_edit_all_live_vertices_for_sources_helper(
        _mesh_edit_state.replacement_mesh_for_mapping,
        source_indices,
    )

    def _mesh_edit_triangle_replace_groups(source_indices: Iterable[int]) -> List[Dict[str, object]]:
        if _mesh_edit_state.replacement_mesh_for_mapping is None:
            return []
        requested_source_indices = _mesh_edit_requested_source_indices_helper(_mesh_edit_state.replacement_mesh_for_mapping, source_indices)
        normalizer = original_reference_preview_model or _mesh_edit_state.replacement_preview_model
        position_transforms, normal_transforms = _mesh_edit_affine_preview_transforms(
            requested_source_indices,
            include_normals=True,
        )
        groups = _mesh_edit_triangle_replace_groups_helper(
            _mesh_edit_state.replacement_mesh_for_mapping,
            requested_source_indices,
            {},
            source_to_preview_point=_mesh_edit_source_to_preview_point,
            normalization_center=getattr(normalizer, "normalization_center", (0.0, 0.0, 0.0)),
            normalization_scale=getattr(normalizer, "normalization_scale", 1.0),
            position_transform_by_source=position_transforms or None,
            normal_transform_by_source=normal_transforms or None,
            allow_source_space=_mesh_edit_source_space_live_update_allowed(requested_source_indices),
        )
        covered = {
            int(group.get("source_submesh_index", -1))
            for group in groups
            if hasattr(group, "get")
        }
        missing_source_indices = tuple(index for index in requested_source_indices if int(index) not in covered)
        if not missing_source_indices:
            return groups
        if _alignment_d3d11_mesh_edit_commands_active():
            return []
        transformed_sources_by_index = _mesh_edit_transformed_sources_for_live_preview(missing_source_indices)
        groups.extend(
            _mesh_edit_triangle_replace_groups_helper(
                _mesh_edit_state.replacement_mesh_for_mapping,
                missing_source_indices,
                transformed_sources_by_index,
                source_to_preview_point=_mesh_edit_source_to_preview_point,
            )
        )
        return groups

    def _mesh_edit_source_indices_from_groups(groups: Iterable[Mapping[str, object]]) -> tuple[int, ...]:
        indices: set[int] = set()
        for group in groups or ():
            if not hasattr(group, "get"):
                continue
            try:
                source_index = int(group.get("source_submesh_index", -1))
            except (TypeError, ValueError, OverflowError):
                continue
            if source_index >= 0:
                indices.add(source_index)
        return tuple(sorted(indices))

    def _mesh_edit_reusable_source_indices(source_indices: Iterable[int] | None) -> Iterable[int]:
        if source_indices is None:
            return ()
        if isinstance(source_indices, _SequenceABC):
            return source_indices
        return tuple(source_indices or ())

    def _mesh_edit_replace_live_triangles(source_indices: Iterable[int], *, replace_all: bool = False) -> bool:
        if _mesh_edit_state.replacement_mesh_for_mapping is None:
            return False
        if _alignment_d3d11_mesh_edit_commands_active():
            mesh_edit_live_update_timer.stop()
            _flush_mesh_edit_live_vertex_updates()
            requested_source_indices = _mesh_edit_requested_source_indices_helper(
                _mesh_edit_state.replacement_mesh_for_mapping,
                source_indices,
            )
            groups = _mesh_edit_triangle_replace_groups(source_indices)
            if groups or requested_source_indices:
                if alignment_d3d11_preview_host.replace_mesh_edit_triangles(
                    groups,
                    replace_all=replace_all,
                    source_submesh_indices=requested_source_indices,
                ):
                    return True
                _record_mesh_edit_event(
                    "mesh_edit_live_triangle_replace_failed",
                    source_indices=requested_source_indices,
                    group_count=len(groups),
                    replace_all=bool(replace_all),
                )
            return False
        return False

    def _mesh_edit_replace_live_triangles_or_queue_rebuild(source_indices: Iterable[int], *, replace_all: bool = False) -> None:
        requested_source_indices = _mesh_edit_reusable_source_indices(source_indices)
        if _mesh_edit_replace_live_triangles(requested_source_indices, replace_all=replace_all):
            return
        if _alignment_d3d11_mesh_edit_commands_active():
            _mesh_edit_mark_native_preview_stale(
                "Native D3D11 mesh edit triangle update failed; preview is stale. Reload D3D11 preview to resync.",
                source_indices=tuple(requested_source_indices or ()),
                replace_all=bool(replace_all),
            )
            return
        if _alignment_d3d11_preview_active():
            _mesh_edit_mark_native_preview_stale(
                "Native D3D11 mesh edit commands are unavailable; preview is stale. Reload D3D11 preview to resync.",
                source_indices=tuple(requested_source_indices or ()),
                replace_all=bool(replace_all),
            )
            return
        if _mesh_edit_tab_active():
            _mesh_edit_mark_native_preview_stale(
                "Active Mesh Editor triangle refresh requires native D3D11 refresh; Python preview rebuild fallback is disabled.",
                source_indices=tuple(requested_source_indices or ()),
                replace_all=bool(replace_all),
            )
            return
        _queue_static_preview_rebuild()

    def _mesh_editor_apply_native_update(native_update: object) -> bool:
        if not _alignment_d3d11_mesh_edit_commands_active():
            return False
        mesh_edit_live_update_timer.stop()
        _flush_mesh_edit_live_vertex_updates()
        return apply_native_update_to_host(alignment_d3d11_preview_host, native_update)

    def _mesh_editor_apply_result_native_update(result: object) -> bool:
        native_update = getattr(result, "native_update", None)
        active_commands = _alignment_d3d11_mesh_edit_commands_active()
        if native_update is None:
            if _mesh_editor_result_has_deferred_native_python_apply(result):
                raise RuntimeError("native deferred edit result did not include preview payload; Python live preview fallback is disabled")
            if active_commands and _mesh_editor_result_changes_mesh(result):
                raise RuntimeError("active native static replacement edit result did not include preview payload; Python live preview fallback is disabled")
            return False
        applied = _mesh_editor_apply_native_update(native_update)
        if not applied and _mesh_editor_result_has_deferred_native_python_apply(result):
            raise RuntimeError("native deferred edit preview payload was rejected; Python live preview fallback is disabled")
        if not applied and active_commands:
            _mesh_edit_mark_native_preview_stale(
                "Native D3D11 mesh edit preview payload was rejected; preview is stale. Reload D3D11 preview to resync."
            )
            raise RuntimeError("active native static replacement edit preview payload was rejected; Python live preview fallback is disabled")
        return applied

    def _mesh_edit_update_live_preview(
        changed_vertices_by_submesh: Mapping[int, object] | None = None,
        *,
        include_normals: bool = False,
        immediate: bool = False,
    ) -> None:
        if _mesh_edit_state.replacement_mesh_for_mapping is None:
            return
        _mesh_edit_update_mesh_totals()
        if _alignment_d3d11_mesh_edit_commands_active():
            if changed_vertices_by_submesh:
                _queue_mesh_edit_live_vertex_updates(
                    changed_vertices_by_submesh,
                    include_normals=include_normals,
                    immediate=immediate,
                )
                return
            _mesh_edit_replace_live_triangles_or_queue_rebuild(_mesh_edit_preview_source_indices())
            return
        if changed_vertices_by_submesh and not immediate and _alignment_d3d11_preview_active():
            _record_mesh_edit_event(
                "mesh_edit_live_preview_deferred",
                reason="native mesh edit commands unavailable",
            )
            return
        if _alignment_d3d11_preview_active():
            _mesh_edit_mark_native_preview_stale(
                "Native D3D11 mesh edit commands are unavailable; preview is stale. Reload D3D11 preview to resync.",
                reason="native mesh edit commands unavailable",
            )
            return
        if _mesh_edit_tab_active():
            self.set_status_message(
                "Active Mesh Editor live preview requires native D3D11; Python preview rebuild fallback is disabled.",
                error=True,
            )
            _record_mesh_edit_event(
                "mesh_edit_live_preview_rebuild_blocked",
                reason="native D3D11 unavailable",
            )
            return
        _mesh_edit_refresh_replacement_preview_model()
        _safe_refresh_static_dialog_preview(live_mesh_edit=True)

    def _mesh_edit_begin_stroke(payload: object) -> None:
        if _mesh_edit_state.replacement_mesh_for_mapping is None or not isinstance(payload, Mapping):
            return
        if _mesh_edit_worker_active():
            return
        can_edit, _reason = _mesh_edit_can_edit_scope()
        if not can_edit or not mesh_edit_enabled_checkbox.isChecked() or not _mesh_edit_tab_active():
            return
        stroke_id = _mesh_edit_stroke_id(payload)
        if stroke_id <= 0:
            return
        tool = _mesh_edit_payload_choice_helper(
            payload,
            "tool",
            _mesh_edit_current_tool(),
            {"move", "grab", "smooth", "inflate", "pinch", "remove", "vertex"},
        )
        delete_mode = _mesh_edit_payload_choice_helper(
            payload,
            "delete_mode",
            mesh_edit_delete_mode_combo.currentData() or "release",
            {"release", "live", "selection"},
        )
        native_descriptor_groups = (
            _mesh_edit_payload_native_vertex_groups_helper(
                payload,
                _mesh_edit_state.replacement_mesh_for_mapping,
                allowed_source_indices=_mesh_edit_allowed_source_indices(),
                source_indices_for_editor_id=_alignment_d3d11_source_indices_for_editor_id,
            )
            if tool != "remove" and callable(_mesh_edit_payload_native_vertex_groups_helper)
            else []
        )
        native_screen_selection_payload = _mesh_edit_native_screen_selection_payload(payload)
        native_screen_stroke = tool != "remove" and (
            isinstance(payload.get("screen_drag"), Mapping)
            or bool(native_screen_selection_payload)
            or isinstance(payload.get("screen_radius"), Mapping)
        )
        native_descriptor_stroke = (bool(native_descriptor_groups) or native_screen_stroke) and callable(
            _push_geometry_sparse_mesh_edit_snapshot
        )
        if native_descriptor_groups and callable(_mesh_edit_cleanup_native_vertex_group_descriptors_helper):
            _mesh_edit_cleanup_native_vertex_group_descriptors_helper(native_descriptor_groups)
        snapshot = None
        before_topology = None
        if not native_descriptor_stroke:
            snapshot = _mesh_edit_capture_live_stroke_base_snapshot(_mesh_edit_state.replacement_mesh_for_mapping)
            if snapshot is None:
                return
            before_topology = mesh_topology_signature(_mesh_edit_state.replacement_mesh_for_mapping)
            _push_geometry_undo_snapshot("Mesh edit stroke")
            undo_source = snapshot if isinstance(snapshot, ParsedMesh) else _mesh_edit_state.replacement_mesh_for_mapping
            if not _mesh_edit_push_undo_snapshot(undo_source, take_ownership=isinstance(snapshot, ParsedMesh)):
                release_mesh_history_snapshot(snapshot)
                _pop_geometry_undo_snapshot()
                return
        _mesh_edit_clear_active_stroke()
        mesh_edit_active_stroke.update(
            {
                "id": stroke_id,
                "tool": tool,
                "delete_mode": delete_mode,
                "snapshot": snapshot,
                "base": snapshot,
                "before_topology": None if tool == "remove" or native_descriptor_stroke else before_topology,
                "native_descriptor_stroke": native_descriptor_stroke,
                "native_screen_stroke": native_screen_stroke,
                "native_screen_selection_payload": native_screen_selection_payload,
                "geometry_snapshot_pushed": not native_descriptor_stroke,
                "geometry_history_mesh_edit_revision": int(mesh_edit_revision.get("value", 0) or 0),
                "geometry_history_source_geometry_revision": int(source_geometry_revision.get("value", 0) or 0),
                "geometry_history_morph_slider_values": copy.deepcopy(dict(morph_slider_values or {})),
                "geometry_history_morph_slider_post_edit_deltas": copy.deepcopy(list(morph_slider_post_edit_deltas or ())),
                "geometry_history_morph_slider_topology_blocked": copy.deepcopy(dict(morph_slider_topology_blocked or {})),
                "undo_snapshot_pushed": not native_descriptor_stroke,
                "changed": False,
                "remove_faces_by_submesh": {},
                "remove_vertices_by_submesh": {},
                "live_delete_submeshes": set(),
            }
        )
        _refresh_mesh_edit_controls()

    def _mesh_edit_restore_snapshot(snapshot: object) -> bool:
        if not _mesh_edit_restore_live_stroke_base_snapshot(snapshot):
            return False
        _mesh_edit_update_mesh_totals()
        if _alignment_d3d11_preview_active():
            mesh_edit_preview_model_dirty["value"] = True
            _mesh_edit_commit_geometry_preview_state()
            _mesh_edit_replace_live_triangles_or_queue_rebuild(_mesh_edit_preview_source_indices(), replace_all=True)
            return True
        _mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)
        _mesh_edit_commit_geometry_preview_state()
        _safe_refresh_static_dialog_preview(live_mesh_edit=True)
        return True

    _mesh_edit_payload_has_drag_motion = lambda payload: _mesh_edit_payload_has_drag_motion_helper(payload)
    _NATIVE_STROKE_HISTORY_ATTR = "cdmw_native_mesh_history_vertex_delta"

    def _mesh_edit_descriptor_vertex_range(raw_group: Mapping[str, object]) -> tuple[int, int] | None:
        try:
            raw_start = raw_group.get("vertex_index_start", -1)
            raw_count = raw_group.get("vertex_index_count", 0)
            start = int(raw_start if raw_start is not None else -1)
            count = int(raw_count if raw_count is not None else 0)
        except (TypeError, ValueError, OverflowError):
            return None
        if start < 0 or count <= 0:
            return None
        return start, count

    def _mesh_edit_descriptor_vertex_values(raw_group: Mapping[str, object]) -> Sequence[int]:
        vertex_range = _mesh_edit_descriptor_vertex_range(raw_group)
        if vertex_range is not None:
            start, count = vertex_range
            return range(start, start + count)
        raw_indices = raw_group.get("vertex_indices")
        return raw_indices if isinstance(raw_indices, (tuple, list, range)) else ()

    def _mesh_edit_sparse_descriptor_groups(raw_value: object) -> list[dict[str, object]]:
        if not isinstance(raw_value, Mapping):
            return []
        raw_groups = raw_value.get("groups")
        candidates = tuple(raw_groups) if isinstance(raw_groups, (tuple, list)) else (raw_value,)
        groups: list[dict[str, object]] = []
        for raw_group in candidates:
            if not isinstance(raw_group, Mapping):
                continue
            raw_indices = raw_group.get("vertex_indices")
            raw_binary = raw_group.get("before_positions_binary")
            raw_snapshot_id = str(
                raw_group.get("native_sparse_snapshot_id")
                or raw_group.get("sparse_snapshot_id")
                or ""
            ).strip()
            vertex_range = _mesh_edit_descriptor_vertex_range(raw_group)
            if vertex_range is not None:
                indices: Sequence[int] = range(vertex_range[0], vertex_range[0] + vertex_range[1])
                group: dict[str, object] = {
                    "vertex_index_start": vertex_range[0],
                    "vertex_index_count": vertex_range[1],
                }
            else:
                if not isinstance(raw_indices, (tuple, list, range)):
                    continue
                parsed_indices: list[int] = []
                seen: set[int] = set()
                for raw_index in raw_indices:
                    try:
                        index = int(raw_index)
                    except (TypeError, ValueError):
                        parsed_indices = []
                        break
                    if index < 0 or index in seen:
                        parsed_indices = []
                        break
                    parsed_indices.append(index)
                    seen.add(index)
                if not parsed_indices:
                    continue
                indices = tuple(parsed_indices)
                group = {"vertex_indices": indices}
            if raw_snapshot_id:
                group["native_sparse_snapshot_id"] = raw_snapshot_id
            if not isinstance(raw_binary, Mapping):
                if raw_snapshot_id:
                    groups.append(group)
                continue
            try:
                count = int(raw_binary.get("count", len(indices)) or 0)
                components = int(raw_binary.get("components", 3) or 0)
            except (TypeError, ValueError):
                continue
            raw_path = str(raw_binary.get("path") or "").strip()
            raw_type = str(raw_binary.get("type") or "f64").strip().lower()
            if not raw_path or count != len(indices) or components != 3 or raw_type != "f64":
                continue
            group["before_positions_binary"] = {
                "path": raw_path,
                "count": len(indices),
                "components": 3,
                "type": "f64",
            }
            groups.append(group)
        return groups

    def _mesh_edit_capture_native_stroke_delta(mesh: object, changed_vertices_by_submesh: object) -> None:
        if mesh is None or not isinstance(changed_vertices_by_submesh, Mapping):
            return
        submeshes = getattr(mesh, "submeshes", ()) or ()
        before_by_submesh = mesh_edit_active_stroke.setdefault("native_before_positions_by_submesh", {})
        if not isinstance(before_by_submesh, dict):
            return
        for raw_submesh_index in changed_vertices_by_submesh.keys():
            try:
                submesh_index = int(raw_submesh_index)
            except (TypeError, ValueError):
                continue
            if submesh_index < 0 or submesh_index >= len(submeshes):
                continue
            submesh = submeshes[submesh_index]
            raw_delta = getattr(submesh, _NATIVE_STROKE_HISTORY_ATTR, None)
            if hasattr(submesh, _NATIVE_STROKE_HISTORY_ATTR):
                delattr(submesh, _NATIVE_STROKE_HISTORY_ATTR)
            if not isinstance(raw_delta, Mapping):
                continue
            raw_indices = _mesh_edit_descriptor_vertex_values(raw_delta)
            descriptor_groups = _mesh_edit_sparse_descriptor_groups(raw_delta)
            if descriptor_groups:
                entry = before_by_submesh.setdefault(submesh_index, {"groups": []})
                if isinstance(entry, dict) and isinstance(entry.get("groups"), list):
                    entry["groups"].extend(descriptor_groups)
                continue
            raw_positions = tuple(raw_delta.get("before_positions") or ())
            if len(raw_indices) != len(raw_positions):
                continue
            vertex_count = len(getattr(submesh, "vertices", ()) or ())
            positions_by_vertex = before_by_submesh.setdefault(submesh_index, {})
            if not isinstance(positions_by_vertex, dict):
                continue
            for raw_vertex_index, raw_position in zip(raw_indices, raw_positions):
                try:
                    vertex_index = int(raw_vertex_index)
                    position = (
                        float(raw_position[0]),  # type: ignore[index]
                        float(raw_position[1]),  # type: ignore[index]
                        float(raw_position[2]),  # type: ignore[index]
                    )
                except (TypeError, ValueError, OverflowError, IndexError):
                    continue
                if vertex_index < 0 or vertex_index >= vertex_count:
                    continue
                if not all(-float("inf") < component < float("inf") for component in position):
                    continue
                positions_by_vertex.setdefault(vertex_index, position)

    def _mesh_edit_changed_vertex_range(raw_vertices: object) -> range | None:
        if isinstance(raw_vertices, range) and raw_vertices.step == 1:
            return raw_vertices
        if not isinstance(raw_vertices, Mapping):
            return None
        for start_key, count_key in (
            ("changed_vertex_start", "changed_vertex_count"),
            ("source_vertex_start", "source_vertex_count"),
        ):
            try:
                raw_start = raw_vertices.get(start_key, -1)
                raw_count = raw_vertices.get(count_key, 0)
                start = int(raw_start if raw_start is not None else -1)
                count = int(raw_count if raw_count is not None else 0)
            except (TypeError, ValueError, OverflowError):
                continue
            if start >= 0 and count >= 0:
                return range(start, start + count)
        return None

    def _mesh_edit_changed_vertices_for_source(changed_vertices_by_submesh: object, source_submesh_index: int) -> object:
        if not isinstance(changed_vertices_by_submesh, Mapping):
            return set()
        raw_vertices = changed_vertices_by_submesh.get(source_submesh_index, ())
        compact_range = _mesh_edit_changed_vertex_range(raw_vertices)
        if compact_range is not None:
            return compact_range
        if isinstance(raw_vertices, Mapping):
            return dict(raw_vertices)
        changed: set[int] = set()
        for raw_index in raw_vertices or ():
            try:
                vertex_index = int(raw_index)
            except (TypeError, ValueError, OverflowError):
                continue
            if vertex_index >= 0:
                changed.add(vertex_index)
        return changed

    def _mesh_edit_changed_vertex_groups_for_live_update(changed_vertices_by_submesh: object) -> dict[int, object]:
        if not isinstance(changed_vertices_by_submesh, Mapping):
            return {}
        changed: dict[int, object] = {}
        for raw_submesh_index, raw_vertices in changed_vertices_by_submesh.items():
            try:
                submesh_index = int(raw_submesh_index)
            except (TypeError, ValueError, OverflowError):
                continue
            if submesh_index < 0:
                continue
            compact_range = _mesh_edit_changed_vertex_range(raw_vertices)
            if compact_range is not None:
                changed[submesh_index] = compact_range
                continue
            if isinstance(raw_vertices, Mapping):
                changed[submesh_index] = dict(raw_vertices)
                continue
            values: set[int] = set()
            for raw_index in raw_vertices or ():
                try:
                    vertex_index = int(raw_index)
                except (TypeError, ValueError, OverflowError):
                    continue
                if vertex_index >= 0:
                    values.add(vertex_index)
            if values:
                changed[submesh_index] = values
        return changed

    def _mesh_edit_sparse_vertex_snapshot(before_by_submesh: object) -> dict[str, object] | None:
        if not isinstance(before_by_submesh, Mapping) or not before_by_submesh:
            return None
        positions: dict[int, object] = {}
        for raw_submesh_index, raw_positions_by_vertex in before_by_submesh.items():
            if not isinstance(raw_positions_by_vertex, Mapping):
                continue
            try:
                submesh_index = int(raw_submesh_index)
            except (TypeError, ValueError):
                continue
            descriptor_groups = _mesh_edit_sparse_descriptor_groups(raw_positions_by_vertex)
            if descriptor_groups:
                positions[submesh_index] = {"groups": descriptor_groups}
                continue
            vertices: dict[int, tuple[float, float, float]] = {}
            for raw_vertex_index, raw_position in raw_positions_by_vertex.items():
                try:
                    vertex_index = int(raw_vertex_index)
                    position = (
                        float(raw_position[0]),  # type: ignore[index]
                        float(raw_position[1]),  # type: ignore[index]
                        float(raw_position[2]),  # type: ignore[index]
                    )
                except (TypeError, ValueError, OverflowError, IndexError):
                    continue
                if vertex_index >= 0 and all(-float("inf") < component < float("inf") for component in position):
                    vertices[vertex_index] = position
            if vertices:
                positions[submesh_index] = vertices
        if not positions:
            return None
        return {
            "kind": "native_sparse_vertex_delta",
            "before_positions_by_submesh": positions,
        }

    def _mesh_edit_is_sparse_vertex_snapshot(snapshot: object) -> bool:
        return (
            isinstance(snapshot, Mapping)
            and snapshot.get("kind") == "native_sparse_vertex_delta"
            and isinstance(snapshot.get("before_positions_by_submesh"), Mapping)
        )

    def _mesh_edit_current_sparse_vertex_snapshot(snapshot: object) -> dict[str, object] | None:
        if not _mesh_edit_is_sparse_vertex_snapshot(snapshot) or _mesh_edit_state.replacement_mesh_for_mapping is None:
            return None
        before_by_submesh = snapshot.get("before_positions_by_submesh")  # type: ignore[union-attr]
        try:
            from cdmw.modding.mesh_native_core import snapshot_native_mesh_sparse_vertex_positions

            native_current = snapshot_native_mesh_sparse_vertex_positions(
                _mesh_edit_state.replacement_mesh_for_mapping,
                before_by_submesh,
            )
        except Exception:
            native_current = None
        if native_current:
            native_snapshot = _mesh_edit_sparse_vertex_snapshot(native_current)
            if native_snapshot is not None:
                return native_snapshot
        if not _mesh_edit_python_sparse_current_fallback_allowed(
            _mesh_edit_state.replacement_mesh_for_mapping,
            before_by_submesh,
        ):
            return None
        return None

    def _mesh_edit_restore_sparse_vertex_snapshot(
        snapshot: object,
        *,
        increment_revision: bool,
        include_normals: bool,
    ) -> bool:
        mesh = _mesh_edit_state.replacement_mesh_for_mapping
        if mesh is None:
            return False
        if not _mesh_edit_is_sparse_vertex_snapshot(snapshot):
            return False
        before_by_submesh = snapshot.get("before_positions_by_submesh")  # type: ignore[union-attr]
        changed_vertices_by_submesh: dict[int, object] = {}
        try:
            from cdmw.modding.mesh_native_core import apply_native_mesh_sparse_vertex_restore

            native_restore = apply_native_mesh_sparse_vertex_restore(mesh, before_by_submesh)
        except Exception:
            native_restore = None
        native_restore_applied = native_restore is not None
        if native_restore is not None:
            changed_vertices_by_submesh = _mesh_edit_changed_vertex_groups_for_live_update(native_restore or {})
        else:
            _mesh_edit_python_sparse_restore_fallback_allowed(mesh, before_by_submesh)
            return False
        if not changed_vertices_by_submesh:
            return False
        normal_changed_vertices_by_submesh: dict[int, object] = {}
        if include_normals:
            try:
                from cdmw.modding.mesh_native_core import apply_native_mesh_recalculate_normals

                native_normals = apply_native_mesh_recalculate_normals(
                    mesh,
                    set(changed_vertices_by_submesh),
                    return_changed_vertices=True,
                )
            except Exception:
                native_normals = None
            if native_normals is not None:
                normal_changed_vertices_by_submesh = _mesh_edit_changed_vertex_groups_for_live_update(native_normals or {})
            else:
                _mesh_edit_python_normal_fallback_allowed(mesh, changed_vertices_by_submesh)
        _mesh_editor_remember_static_replacement_session_mesh()
        _mesh_edit_update_mesh_totals()
        if native_restore_applied and _alignment_d3d11_preview_active():
            mesh_edit_preview_model_dirty["value"] = True
        else:
            _morph_slider_capture_post_edit_deltas()
            _mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)
        if increment_revision:
            mesh_edit_revision["value"] = int(mesh_edit_revision.get("value", 0) or 0) + 1
        _mesh_edit_commit_geometry_preview_state()
        _sync_source_tree_enabled_checks()
        _refresh_source_assignment_columns()
        _refresh_mesh_edit_controls()
        if _alignment_d3d11_preview_active():
            _mesh_edit_update_live_preview(
                normal_changed_vertices_by_submesh or changed_vertices_by_submesh,
                include_normals=include_normals,
                immediate=include_normals,
            )
        else:
            _safe_refresh_static_dialog_preview(live_mesh_edit=True)
        return True

    def _mesh_edit_restore_native_stroke_delta() -> bool:
        return _mesh_edit_restore_sparse_vertex_snapshot(
            _mesh_edit_sparse_vertex_snapshot(mesh_edit_active_stroke.get("native_before_positions_by_submesh")),
            increment_revision=False,
            include_normals=False,
        )

    def _mesh_edit_replace_active_undo_with_native_sparse_snapshot() -> None:
        snapshot = _mesh_edit_sparse_vertex_snapshot(mesh_edit_active_stroke.get("native_before_positions_by_submesh"))
        if snapshot is not None:
            if bool(mesh_edit_active_stroke.get("undo_snapshot_pushed")) and mesh_edit_undo_stack:
                retain_mesh_history_snapshot(snapshot)
                release_mesh_history_snapshot(mesh_edit_undo_stack[-1])
                mesh_edit_undo_stack[-1] = snapshot
            else:
                mesh_edit_undo_stack.append(snapshot)
                retain_mesh_history_snapshot(snapshot)
                mesh_edit_undo_adjustment_stack.append(_mesh_edit_part_enabled_snapshot())
                if len(mesh_edit_undo_stack) > 30:
                    release_mesh_history_snapshot(mesh_edit_undo_stack.pop(0))
                    if mesh_edit_undo_adjustment_stack:
                        del mesh_edit_undo_adjustment_stack[0]
                clear_mesh_history_snapshot_stack(mesh_edit_redo_stack)
                mesh_edit_redo_adjustment_stack.clear()
                mesh_edit_active_stroke["undo_snapshot_pushed"] = True

    def _mesh_edit_push_active_sparse_geometry_snapshot() -> None:
        if bool(mesh_edit_active_stroke.get("geometry_snapshot_pushed")):
            return
        if not callable(_push_geometry_sparse_mesh_edit_snapshot):
            return
        snapshot = _mesh_edit_sparse_vertex_snapshot(mesh_edit_active_stroke.get("native_before_positions_by_submesh"))
        if snapshot is None:
            return
        snapshot["mesh_edit_revision"] = int(
            mesh_edit_active_stroke.get("geometry_history_mesh_edit_revision", mesh_edit_revision.get("value", 0)) or 0
        )
        snapshot["source_geometry_revision"] = int(
            mesh_edit_active_stroke.get("geometry_history_source_geometry_revision", source_geometry_revision.get("value", 0)) or 0
        )
        snapshot["morph_slider_values"] = copy.deepcopy(
            dict(mesh_edit_active_stroke.get("geometry_history_morph_slider_values", morph_slider_values) or {})
        )
        snapshot["morph_slider_post_edit_deltas"] = copy.deepcopy(
            list(mesh_edit_active_stroke.get("geometry_history_morph_slider_post_edit_deltas", morph_slider_post_edit_deltas) or ())
        )
        snapshot["morph_slider_topology_blocked"] = copy.deepcopy(
            dict(mesh_edit_active_stroke.get("geometry_history_morph_slider_topology_blocked", morph_slider_topology_blocked) or {})
        )
        if _push_geometry_sparse_mesh_edit_snapshot("Mesh edit stroke", snapshot):
            mesh_edit_active_stroke["geometry_snapshot_pushed"] = True

    def _mesh_edit_inverse_transform_disabled() -> RuntimeError:
        return RuntimeError(
            "native mesh edit stroke payload did not include native screen update data; "
            "Python inverse transform fallback is disabled"
        )

    def _mesh_edit_preview_delta_to_source_delta(
        source_index: int,
        transformed_delta: Sequence[object],
    ) -> tuple[float, float, float]:
        raise _mesh_edit_inverse_transform_disabled()

    def _mesh_edit_preview_point_to_source_point(
        source_index: int,
        transformed_point: Sequence[object],
    ) -> tuple[float, float, float]:
        raise _mesh_edit_inverse_transform_disabled()

    def _mesh_edit_preview_distance_to_source_distance(
        source_index: int,
        transformed_distance: float,
    ) -> float:
        raise _mesh_edit_inverse_transform_disabled()

    _mesh_edit_vertices_from_payload = lambda payload: _mesh_edit_payload_selected_indices_helper(
        payload,
        _mesh_edit_state.replacement_mesh_for_mapping,
        allowed_source_indices=_mesh_edit_allowed_source_indices(),
        source_indices_for_editor_id=_d3d11_source_indices_for_editor_id,
        payload_index_key="source_vertex_indices",
        mesh_collection_attr="vertices",
    )

    _mesh_edit_faces_from_payload = lambda payload: _mesh_edit_payload_selected_indices_helper(
        payload,
        _mesh_edit_state.replacement_mesh_for_mapping,
        allowed_source_indices=_mesh_edit_allowed_source_indices(),
        source_indices_for_editor_id=_d3d11_source_indices_for_editor_id,
        payload_index_key="source_face_indices",
        mesh_collection_attr="faces",
    )

    def _mesh_edit_edges_from_payload(payload: object) -> dict[int, set[tuple[int, int]]]:
        if not callable(_mesh_edit_payload_edge_groups_helper):
            return {}
        return _mesh_edit_payload_edge_groups_helper(
            payload,
            _mesh_edit_state.replacement_mesh_for_mapping,
            allowed_source_indices=_mesh_edit_allowed_source_indices(),
            source_indices_for_editor_id=_d3d11_source_indices_for_editor_id,
        )

    _mesh_edit_merge_vertex_groups = lambda target, source: _mesh_edit_merge_index_groups_helper(target, source)
    _mesh_edit_merge_face_groups = lambda target, source: _mesh_edit_merge_index_groups_helper(target, source)

    def _mesh_edit_native_screen_selection_payload(
        payload: Mapping[object, object],
        fallback: object = None,
    ) -> dict[str, object]:
        raw_screen_brush = payload.get("screen_brush")
        raw_screen_region = payload.get("screen_region")
        if not isinstance(raw_screen_brush, Mapping) and not isinstance(raw_screen_region, Mapping):
            return dict(fallback) if isinstance(fallback, Mapping) else {}
        screen_payload = {
            "target_mode": str(payload.get("target_mode") or "vertex"),
            "selection_depth_mode": str(payload.get("selection_depth_mode") or "visible"),
            "falloff": str(payload.get("falloff") or "smooth"),
        }
        if isinstance(raw_screen_brush, Mapping):
            screen_payload["screen_brush"] = _native_screen_payload(raw_screen_brush)
        if isinstance(raw_screen_region, Mapping):
            screen_payload["screen_region"] = _native_screen_payload(raw_screen_region)
        return screen_payload

    def _mesh_edit_native_descriptor_selection_payload(native_descriptor_groups: object) -> dict[str, object]:
        vertices_by_submesh: dict[int, dict[str, object]] = {}
        for group in native_descriptor_groups or ():
            if not isinstance(group, Mapping):
                continue
            try:
                source_submesh_index = int(group.get("source_submesh_index", -1))
            except (TypeError, ValueError, OverflowError):
                continue
            if source_submesh_index < 0:
                continue
            item: dict[str, object] = {}
            raw_vertices = group.get("source_vertex_indices_binary")
            if isinstance(raw_vertices, Mapping):
                item["selected_vertices_binary"] = dict(raw_vertices)
            else:
                try:
                    start = int(group.get("source_vertex_start", -1))
                    count = int(group.get("source_vertex_count", 0))
                except (TypeError, ValueError, OverflowError):
                    start = -1
                    count = 0
                if start >= 0 and count > 0:
                    item["start"] = start
                    item["count"] = count
            raw_weights = group.get("source_vertex_weights_binary")
            if isinstance(raw_weights, Mapping):
                item["source_vertex_weights_binary"] = dict(raw_weights)
            if item:
                vertices_by_submesh[source_submesh_index] = item
        return {"vertices_by_submesh": vertices_by_submesh} if vertices_by_submesh else {}

    def _mesh_edit_set_selection_state(selection: MeshEditSelection) -> None:
        mesh_edit_selected_vertices_by_submesh.clear()
        mesh_edit_selected_edges_by_submesh.clear()
        mesh_edit_selected_faces_by_submesh.clear()
        mesh_edit_selected_source_indices.clear()
        mesh_edit_selected_vertices_by_submesh.update(selection.vertex_map())
        mesh_edit_selected_edges_by_submesh.update(selection.edge_map())
        mesh_edit_selected_faces_by_submesh.update(selection.face_map())
        mesh_edit_selected_source_indices.update(selection.source_indices)

    def _mesh_edit_apply_native_screen_selection(
        payload: Mapping[object, object],
        screen_payload: Mapping[str, object],
    ) -> bool:
        session = _mesh_editor_ensure_static_replacement_session(_mesh_edit_state.replacement_mesh_for_mapping)
        if not isinstance(session, StaticReplacementMeshEditSession):
            return False
        try:
            operation = str(payload.get("operation", payload.get("selection_operation", "replace")) or "replace")
            result = session.select(operation=operation, _native_screen_selection_payload=screen_payload)
            if not result.ok:
                return False
            _mesh_edit_set_selection_state(session.view().selection)
            _mesh_edit_sync_d3d11_selection()
            return True
        except Exception as exc:
            _record_mesh_edit_event("mesh_edit_screen_selection_failed", message=str(exc))
            return False

    def _mesh_edit_clear_topology_selection() -> None:
        mesh_edit_selected_vertices_by_submesh.clear()
        mesh_edit_selected_edges_by_submesh.clear()
        mesh_edit_selected_faces_by_submesh.clear()
        mesh_edit_selected_source_indices.clear()
        if _alignment_d3d11_preview_active():
            alignment_d3d11_preview_host.clear_mesh_edit_vertex_selection()
        for preview_widget in (static_dialog_preview, overlay_dialog_preview, replacement_only_preview):
            if hasattr(preview_widget, "clear_mesh_edit_vertex_selection"):
                preview_widget.clear_mesh_edit_vertex_selection()

    def _mesh_edit_commit_working_mesh(
        status_message: str = "",
        *,
        topology_source_indices: Iterable[int] | None = None,
        normal_source_indices: Iterable[int] | None = None,
        native_result: object | None = None,
    ) -> None:
        if _mesh_edit_state.replacement_mesh_for_mapping is None:
            return
        native_update_applied = (
            _mesh_editor_apply_result_native_update(native_result)
            if native_result is not None
            else False
        )
        _mesh_edit_update_mesh_totals()
        if not native_update_applied:
            _morph_slider_capture_post_edit_deltas()
            _mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)
        mesh_edit_revision["value"] = int(mesh_edit_revision.get("value", 0) or 0) + 1
        _mesh_edit_commit_geometry_preview_state()
        _refresh_source_tree_selection_state()
        _refresh_source_assignment_columns()
        _refresh_mesh_edit_controls()
        if native_update_applied:
            pass
        elif topology_source_indices is not None:
            _mesh_edit_replace_live_triangles_or_queue_rebuild(topology_source_indices)
        elif _alignment_d3d11_preview_active():
            _mesh_edit_update_live_preview(
                _mesh_edit_all_live_vertices_for_sources(normal_source_indices or _mesh_edit_preview_source_indices()),
                include_normals=True,
                immediate=True,
            )
        elif _mesh_edit_tab_active():
            _mesh_edit_mark_native_preview_stale(
                "Active Mesh Editor commit requires native D3D11 refresh; Python preview rebuild fallback is disabled."
            )
        else:
            _queue_static_preview_rebuild()
        if status_message:
            self.set_status_message(status_message)

    def _mesh_edit_apply_preview_payload(payload: object) -> None:
        if _mesh_edit_state.replacement_mesh_for_mapping is None or not isinstance(payload, Mapping):
            return
        stroke_id = _mesh_edit_stroke_id(payload)
        if stroke_id <= 0 or int(mesh_edit_active_stroke.get("id", 0) or 0) != stroke_id:
            return
        can_edit, _reason = _mesh_edit_can_edit_scope()
        if not can_edit or not mesh_edit_enabled_checkbox.isChecked() or not _mesh_edit_tab_active():
            return
        tool = _mesh_edit_payload_choice_helper(
            payload,
            "tool",
            mesh_edit_active_stroke.get("tool") or _mesh_edit_current_tool(),
            {"move", "grab", "smooth", "inflate", "pinch", "remove", "vertex"},
        )
        if tool == "remove":
            delete_mode = _mesh_edit_payload_choice_helper(
                payload,
                "delete_mode",
                mesh_edit_active_stroke.get("delete_mode") or mesh_edit_delete_mode_combo.currentData() or "release",
                {"release", "live", "selection"},
            )
            raw_screen_brush = payload.get("screen_brush")
            if delete_mode in {"live", "release"} and isinstance(raw_screen_brush, Mapping):
                screen_payload = {
                    "target_mode": "face",
                    "selection_depth_mode": str(payload.get("selection_depth_mode") or "visible"),
                    "falloff": str(payload.get("falloff") or "smooth"),
                    "screen_brush": _native_screen_payload(raw_screen_brush),
                }
                if delete_mode == "release":
                    session = _mesh_editor_ensure_static_replacement_session(_mesh_edit_state.replacement_mesh_for_mapping)
                    if not isinstance(session, StaticReplacementMeshEditSession):
                        return
                    select_result = session.select(
                        operation="add" if mesh_edit_active_stroke.get("native_release_remove_selected") else "replace",
                        _native_screen_selection_payload=screen_payload,
                    )
                    if not select_result.ok:
                        return
                    mesh_edit_active_stroke["native_release_remove_selected"] = True
                    _refresh_mesh_edit_controls()
                    return
                result = _mesh_editor_apply_static_replacement_edit(
                    _mesh_edit_state.replacement_mesh_for_mapping,
                    "delete",
                    remove_orphans=False,
                    recompute_normals=False,
                    record_history=False,
                    _native_screen_selection_payload=screen_payload,
                )
                if int(result.removed_face_count or 0) <= 0:
                    return
                _mesh_editor_store_result_mesh(result)
                _mesh_editor_remember_static_replacement_session_mesh()
                live_submeshes = mesh_edit_active_stroke.setdefault("live_delete_submeshes", set())
                if isinstance(live_submeshes, set):
                    live_submeshes.update(int(index) for index in result.affected_submesh_indices)
                mesh_edit_active_stroke["live_removed_face_count"] = int(
                    mesh_edit_active_stroke.get("live_removed_face_count", 0) or 0
                ) + int(result.removed_face_count or 0)
                mesh_edit_active_stroke["changed"] = True
                if not _mesh_editor_apply_result_native_update(result):
                    _mesh_edit_replace_live_triangles_or_queue_rebuild(result.affected_submesh_indices)
                return
            native_delete_groups = (
                _mesh_edit_payload_native_vertex_groups_helper(
                    payload,
                    _mesh_edit_state.replacement_mesh_for_mapping,
                    allowed_source_indices=_mesh_edit_allowed_source_indices(),
                    source_indices_for_editor_id=_alignment_d3d11_source_indices_for_editor_id,
                )
                if callable(_mesh_edit_payload_native_vertex_groups_helper)
                else []
            )
            native_delete_vertices_by_submesh: dict[int, object] = {}
            for native_group in native_delete_groups or ():
                try:
                    source_submesh_index = int(native_group.get("source_submesh_index", -1))
                except (TypeError, ValueError):
                    continue
                if source_submesh_index >= 0 and isinstance(native_group.get("source_vertex_indices_binary"), Mapping):
                    native_delete_vertices_by_submesh[source_submesh_index] = native_group["source_vertex_indices_binary"]
            faces_by_submesh = _mesh_edit_faces_from_payload(payload)
            vertices_by_submesh = (
                {}
                if delete_mode == "live" and native_delete_vertices_by_submesh and not faces_by_submesh
                else _mesh_edit_vertices_from_payload(payload)
            )
            if not vertices_by_submesh and not faces_by_submesh and not native_delete_vertices_by_submesh:
                return
            if delete_mode == "selection":
                if not vertices_by_submesh:
                    vertices_by_submesh = _mesh_edit_vertices_from_payload(payload)
                mesh_edit_selected_source_indices.clear()
                _mesh_edit_merge_vertex_groups(mesh_edit_selected_vertices_by_submesh, vertices_by_submesh)
                _mesh_edit_merge_face_groups(mesh_edit_selected_faces_by_submesh, faces_by_submesh)
                _refresh_mesh_edit_controls()
                return
            if delete_mode == "live":
                delete_selection = (
                    {"faces_by_submesh": faces_by_submesh}
                    if faces_by_submesh
                    else (
                        {"native_selected_vertices_binary_by_submesh": native_delete_vertices_by_submesh}
                        if native_delete_vertices_by_submesh
                        else {"vertices_by_submesh": vertices_by_submesh}
                    )
                )
                result = _mesh_editor_apply_static_replacement_edit(
                    _mesh_edit_state.replacement_mesh_for_mapping,
                    "delete",
                    remove_orphans=False,
                    recompute_normals=False,
                    record_history=False,
                    **delete_selection,
                )
                if callable(_mesh_edit_cleanup_native_vertex_group_descriptors_helper):
                    _mesh_edit_cleanup_native_vertex_group_descriptors_helper(native_delete_groups)
                if int(result.removed_face_count or 0) <= 0:
                    return
                _mesh_editor_store_result_mesh(result)
                _mesh_editor_remember_static_replacement_session_mesh()
                live_submeshes = mesh_edit_active_stroke.setdefault("live_delete_submeshes", set())
                if isinstance(live_submeshes, set):
                    live_submeshes.update(int(index) for index in result.affected_submesh_indices)
                mesh_edit_active_stroke["live_removed_face_count"] = int(
                    mesh_edit_active_stroke.get("live_removed_face_count", 0) or 0
                ) + int(result.removed_face_count or 0)
                mesh_edit_active_stroke["changed"] = True
                if not _mesh_editor_apply_result_native_update(result):
                    _mesh_edit_replace_live_triangles_or_queue_rebuild(result.affected_submesh_indices)
                return
            remove_faces = mesh_edit_active_stroke.setdefault("remove_faces_by_submesh", {})
            if isinstance(remove_faces, dict):
                _mesh_edit_merge_face_groups(remove_faces, faces_by_submesh)  # type: ignore[arg-type]
            remove_vertices = mesh_edit_active_stroke.setdefault("remove_vertices_by_submesh", {})
            if isinstance(remove_vertices, dict):
                _mesh_edit_merge_vertex_groups(remove_vertices, vertices_by_submesh)  # type: ignore[arg-type]
            _refresh_mesh_edit_controls()
            return
        raw_screen_drag = payload.get("screen_drag")
        raw_screen_brush = payload.get("screen_brush")
        raw_screen_radius = payload.get("screen_radius")
        has_screen_drag = isinstance(raw_screen_drag, Mapping)
        has_screen_brush = isinstance(raw_screen_brush, Mapping)
        has_screen_radius = isinstance(raw_screen_radius, Mapping)
        if tool in {"move", "grab", "vertex"} and not has_screen_drag and not _mesh_edit_payload_has_drag_motion(payload):
            return
        native_descriptor_groups = (
            _mesh_edit_payload_native_vertex_groups_helper(
                payload,
                _mesh_edit_state.replacement_mesh_for_mapping,
                allowed_source_indices=_mesh_edit_allowed_source_indices(),
                source_indices_for_editor_id=_alignment_d3d11_source_indices_for_editor_id,
            )
            if callable(_mesh_edit_payload_native_vertex_groups_helper)
            else []
        )
        if has_screen_drag or has_screen_brush or has_screen_radius:
            screen_selection_payload = _mesh_edit_native_screen_selection_payload(
                payload,
                mesh_edit_active_stroke.get("native_screen_selection_payload"),
            )
            descriptor_selection_payload = _mesh_edit_native_descriptor_selection_payload(native_descriptor_groups)
            if has_screen_brush:
                mesh_edit_active_stroke["native_screen_selection_payload"] = screen_selection_payload
            try:
                params: dict[str, object] = {
                    "mirror_x": bool(mesh_edit_mirror_checkbox.isChecked()),
                    "recompute_normals": False,
                    "record_history": False,
                    "_require_native_history_delta": True,
                }
                selected_vertices = _mesh_edit_sorted_index_groups_helper(mesh_edit_selected_vertices_by_submesh)
                transform_screen_stroke = tool in {"move", "grab", "vertex"} and has_screen_drag
                transform_screen_stroke_started = bool(mesh_edit_active_stroke.get("native_transform_stroke_started"))
                if transform_screen_stroke:
                    params["stroke_phase"] = "update" if transform_screen_stroke_started else "begin"
                    params["stroke_id"] = str(stroke_id)
                if has_screen_drag:
                    params["screen_drag"] = _native_screen_payload(raw_screen_drag)  # type: ignore[arg-type]
                if tool in {"move", "vertex"}:
                    if not has_screen_drag:
                        return
                    if transform_screen_stroke_started:
                        pass
                    elif screen_selection_payload:
                        params["_native_screen_selection_payload"] = screen_selection_payload
                    elif descriptor_selection_payload:
                        params["_native_selection_payload"] = descriptor_selection_payload
                    elif selected_vertices:
                        params["vertices_by_submesh"] = selected_vertices
                    else:
                        return
                    result = _mesh_editor_apply_static_replacement_edit(
                        _mesh_edit_state.replacement_mesh_for_mapping,
                        "transform",
                        **params,
                    )
                else:
                    params.update(
                        {
                            "mode": "sculpt",
                            "tool": tool,
                            "strength": _mesh_edit_payload_float_helper(payload, "strength", minimum=0.0, maximum=1.0),
                            "falloff": str(payload.get("falloff") or "smooth"),
                            "iterations": _mesh_edit_payload_int_helper(
                                payload,
                                "smooth_iterations",
                                int(mesh_edit_iterations_spin.value()),
                            ),
                            "invert": bool(payload.get("invert")),
                        }
                    )
                    if transform_screen_stroke_started and tool == "grab":
                        pass
                    elif has_screen_brush:
                        params["screen_brush"] = _native_screen_payload(raw_screen_brush)  # type: ignore[arg-type]
                    elif descriptor_selection_payload:
                        params["_native_selection_payload"] = descriptor_selection_payload
                    elif selected_vertices:
                        params["vertices_by_submesh"] = selected_vertices
                    else:
                        return
                    if "target_mode" in payload:
                        params["target_mode"] = str(payload.get("target_mode") or "vertex")
                    if "selection_depth_mode" in payload:
                        params["selection_depth_mode"] = str(payload.get("selection_depth_mode") or "visible")
                    if has_screen_radius:
                        params["screen_radius"] = _native_screen_payload(raw_screen_radius)  # type: ignore[arg-type]
                    result = _mesh_editor_apply_static_replacement_edit(
                        _mesh_edit_state.replacement_mesh_for_mapping,
                        "brush",
                        **params,
                    )
                edit_result = getattr(result, "edit_result", None)
                if edit_result is not None and not bool(getattr(edit_result, "ok", False)):
                    return
                _mesh_editor_store_result_mesh(result)
                _mesh_editor_remember_static_replacement_session_mesh()
                if transform_screen_stroke:
                    mesh_edit_active_stroke["native_transform_stroke_started"] = True
                _mesh_edit_capture_native_stroke_delta(
                    _mesh_editor_result_mesh_for_state(result),
                    result.changed_vertices_by_submesh,
                )
                live_native_update_applied = _mesh_editor_apply_result_native_update(result)
                if live_native_update_applied:
                    mesh_edit_active_stroke["native_update_applied"] = True
                changed_by_submesh = _mesh_edit_changed_vertex_groups_for_live_update(result.changed_vertices_by_submesh or {})
                if not changed_by_submesh:
                    return
                if not live_native_update_applied:
                    pending_live_vertices_by_submesh: Dict[int, object] = {}
                    _mesh_edit_queue_live_vertex_updates_helper(pending_live_vertices_by_submesh, changed_by_submesh)
                    _mesh_edit_update_live_preview(pending_live_vertices_by_submesh)
                stroke_changed_vertices = mesh_edit_active_stroke.setdefault("changed_vertices_by_submesh", {})
                if isinstance(stroke_changed_vertices, dict):
                    _mesh_edit_queue_live_vertex_updates_helper(stroke_changed_vertices, changed_by_submesh)
                mesh_edit_active_stroke["changed"] = True
                return
            finally:
                if native_descriptor_groups and callable(_mesh_edit_cleanup_native_vertex_group_descriptors_helper):
                    _mesh_edit_cleanup_native_vertex_group_descriptors_helper(native_descriptor_groups)
        if tool in {"move", "grab", "vertex", "smooth", "inflate", "pinch"}:
            raise RuntimeError("native mesh edit stroke payload did not include native screen update data; Python inverse transform fallback is disabled")

    def _mesh_edit_finish_stroke(payload: object) -> None:
        stroke_id = _mesh_edit_stroke_id(payload)
        if stroke_id <= 0 or int(mesh_edit_active_stroke.get("id", 0) or 0) != stroke_id:
            return
        tool = _mesh_edit_payload_choice_helper(
            payload if isinstance(payload, Mapping) else {},
            "tool",
            mesh_edit_active_stroke.get("tool") or _mesh_edit_current_tool(),
            {"move", "grab", "smooth", "inflate", "pinch", "remove", "vertex"},
        )
        if tool == "remove":
            if _mesh_edit_state.replacement_mesh_for_mapping is None:
                _mesh_edit_clear_active_stroke()
                _refresh_mesh_edit_controls()
                return
            delete_mode = _mesh_edit_payload_choice_helper(
                payload if isinstance(payload, Mapping) else {},
                "delete_mode",
                mesh_edit_active_stroke.get("delete_mode") or mesh_edit_delete_mode_combo.currentData() or "release",
                {"release", "live", "selection"},
            )
            if delete_mode == "selection":
                _mesh_edit_pop_undo_snapshot()
                _pop_geometry_undo_snapshot()
                _mesh_edit_clear_active_stroke()
                _refresh_mesh_edit_controls()
                return
            if delete_mode == "live":
                changed = bool(mesh_edit_active_stroke.get("changed"))
                if not changed:
                    _mesh_edit_pop_undo_snapshot()
                    _pop_geometry_undo_snapshot()
                    _mesh_edit_clear_active_stroke()
                    _refresh_mesh_edit_controls()
                    return
                live_submeshes = mesh_edit_active_stroke.get("live_delete_submeshes", set())
                submesh_indices = _mesh_edit_optional_sorted_indices_helper(live_submeshes)
                compact_result = _mesh_editor_apply_static_replacement_edit(
                    _mesh_edit_state.replacement_mesh_for_mapping,
                    "delete_loose_vertices",
                    source_indices=submesh_indices,
                    recompute_normals=True,
                    record_history=False,
                )
                _mesh_editor_store_result_mesh(compact_result)
                _mesh_editor_remember_static_replacement_session_mesh()
                _mesh_edit_disable_emptied_parts(compact_result.emptied_submesh_indices)
                _morph_slider_mark_topology_changed(_mesh_edit_topology_changed_status_helper("remove_faces"))
                _mesh_edit_clear_topology_selection()
                removed_faces = int(mesh_edit_active_stroke.get("live_removed_face_count", 0) or 0)
                topology_sources = _mesh_edit_topology_source_indices_helper(
                    live_submeshes,
                    compact_result.affected_submesh_indices,
                )
                _mesh_edit_clear_active_stroke()
                _mesh_edit_commit_working_mesh(
                    _mesh_edit_live_delete_status_helper(removed_faces),
                    topology_source_indices=topology_sources,
                    native_result=compact_result,
                )
                return
            if mesh_edit_active_stroke.get("native_release_remove_selected"):
                session = _mesh_editor_fresh_static_replacement_session() or _mesh_editor_ensure_static_replacement_session(
                    _mesh_edit_state.replacement_mesh_for_mapping
                )
                if not isinstance(session, StaticReplacementMeshEditSession) or session.view().selection.is_empty():
                    _mesh_edit_pop_undo_snapshot()
                    _pop_geometry_undo_snapshot()
                    _mesh_edit_clear_active_stroke()
                    _refresh_mesh_edit_controls()
                    return
                result = session.apply_current_selection(
                    "delete",
                    remove_orphans=True,
                    recompute_normals=True,
                    record_history=False,
                )
            else:
                remove_faces = mesh_edit_active_stroke.get("remove_faces_by_submesh", {})
                selected_faces = _mesh_edit_sorted_index_groups_helper(remove_faces)
                remove_vertices = mesh_edit_active_stroke.get("remove_vertices_by_submesh", {})
                selected_vertices = _mesh_edit_sorted_index_groups_helper(remove_vertices)
                if not selected_faces and not selected_vertices:
                    _mesh_edit_pop_undo_snapshot()
                    _pop_geometry_undo_snapshot()
                    _mesh_edit_clear_active_stroke()
                    _refresh_mesh_edit_controls()
                    return
                if selected_faces:
                    delete_selection = {"faces_by_submesh": selected_faces}
                else:
                    delete_selection = {"vertices_by_submesh": selected_vertices}
                result = _mesh_editor_apply_static_replacement_edit(
                    _mesh_edit_state.replacement_mesh_for_mapping,
                    "delete",
                    remove_orphans=True,
                    recompute_normals=True,
                    record_history=False,
                    **delete_selection,
                )
            if int(result.removed_face_count or 0) <= 0:
                _mesh_edit_pop_undo_snapshot()
                _pop_geometry_undo_snapshot()
                _mesh_edit_clear_active_stroke()
                _refresh_mesh_edit_controls()
                mesh_edit_delete_faces_text = _mesh_edit_delete_faces_text_helper()
                self.set_status_message(mesh_edit_delete_faces_text["no_brush_faces"])
                return
            _mesh_editor_store_result_mesh(result)
            _mesh_editor_remember_static_replacement_session_mesh()
            _mesh_edit_disable_emptied_parts(result.emptied_submesh_indices)
            _morph_slider_mark_topology_changed(_mesh_edit_topology_changed_status_helper("remove_faces"))
            _mesh_edit_clear_topology_selection()
            _mesh_edit_clear_active_stroke()
            _mesh_edit_commit_working_mesh(
                _mesh_edit_deleted_faces_status_helper(result.removed_face_count),
                topology_source_indices=result.affected_submesh_indices,
                native_result=result,
            )
            return
        native_transform_stroke_started = bool(mesh_edit_active_stroke.get("native_transform_stroke_started"))
        if native_transform_stroke_started and _mesh_edit_state.replacement_mesh_for_mapping is not None:
            try:
                if tool in {"move", "vertex"}:
                    _mesh_editor_apply_static_replacement_edit(
                        _mesh_edit_state.replacement_mesh_for_mapping,
                        "transform",
                        stroke_phase="end",
                        stroke_id=str(stroke_id),
                        record_history=False,
                        recompute_normals=False,
                        _require_native_history_delta=True,
                    )
                elif tool == "grab":
                    _mesh_editor_apply_static_replacement_edit(
                        _mesh_edit_state.replacement_mesh_for_mapping,
                        "brush",
                        mode="sculpt",
                        tool="grab",
                        strength=0.0,
                        stroke_phase="end",
                        stroke_id=str(stroke_id),
                        record_history=False,
                        recompute_normals=False,
                        _require_native_history_delta=True,
                    )
            except Exception as exc:
                self.set_status_message(f"Native Mesh Editor stroke finish failed: {exc}", error=True)
        changed = bool(mesh_edit_active_stroke.get("changed"))
        if not changed:
            _mesh_edit_pop_active_stroke_snapshots()
            _mesh_edit_clear_active_stroke()
            _refresh_mesh_edit_controls()
            return
        if _mesh_edit_state.replacement_mesh_for_mapping is None:
            _mesh_edit_clear_active_stroke()
            _refresh_mesh_edit_controls()
            return
        changed_sources_payload = mesh_edit_active_stroke.get("changed_vertices_by_submesh", {})
        changed_sources = _mesh_edit_mapping_keys_helper(changed_sources_payload)
        normal_sources = set(changed_sources or _mesh_edit_preview_source_indices())
        normal_changed_vertices_by_submesh = {}
        native_update_applied = bool(mesh_edit_active_stroke.get("native_update_applied"))
        if not native_update_applied:
            try:
                from cdmw.modding.mesh_native_core import apply_native_mesh_recalculate_normals

                native_normals = apply_native_mesh_recalculate_normals(
                    _mesh_edit_state.replacement_mesh_for_mapping,
                    normal_sources,
                    return_changed_vertices=True,
                )
            except Exception:
                native_normals = None
            if native_normals is not None:
                normal_changed_vertices_by_submesh = _mesh_edit_changed_vertex_groups_for_live_update(native_normals or {})
            else:
                _mesh_edit_python_normal_fallback_allowed(_mesh_edit_state.replacement_mesh_for_mapping, normal_sources)
        try:
            before_topology = mesh_edit_active_stroke.get("before_topology")
            if before_topology is not None:
                assert_mesh_topology_unchanged(before_topology, _mesh_edit_state.replacement_mesh_for_mapping)  # type: ignore[arg-type]
        except Exception as exc:
            snapshot = mesh_edit_active_stroke.get("snapshot")
            if snapshot is not None:
                _mesh_edit_restore_snapshot(snapshot)
            _mesh_edit_pop_active_stroke_snapshots()
            _mesh_edit_clear_active_stroke()
            _refresh_mesh_edit_controls()
            QMessageBox.warning(dialog, _mesh_edit_blocked_title_helper(), str(exc))
            return
        _mesh_edit_update_mesh_totals()
        if native_update_applied:
            mesh_edit_preview_model_dirty["value"] = True
        else:
            _morph_slider_capture_post_edit_deltas()
            _mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)
        mesh_edit_revision["value"] = int(mesh_edit_revision.get("value", 0) or 0) + 1
        _mesh_edit_commit_geometry_preview_state()
        _mesh_edit_replace_active_undo_with_native_sparse_snapshot()
        _mesh_edit_push_active_sparse_geometry_snapshot()
        _mesh_edit_clear_active_stroke()
        _refresh_mesh_edit_controls()
        if native_update_applied:
            return
        if _alignment_d3d11_preview_active():
            _mesh_edit_update_live_preview(
                normal_changed_vertices_by_submesh
                or _mesh_edit_changed_vertex_groups_for_live_update(changed_sources_payload or {})
                or _mesh_edit_all_live_vertices_for_sources(changed_sources or _mesh_edit_preview_source_indices()),
                include_normals=True,
                immediate=True,
            )
        else:
            _mesh_edit_mark_native_preview_stale(
                "Active Mesh Editor stroke finish requires native D3D11 refresh; Python preview rebuild fallback is disabled."
            )

    def _mesh_edit_cancel_stroke(payload: object) -> None:
        if not mesh_edit_active_stroke:
            return
        stroke_id = _mesh_edit_stroke_id(payload)
        if stroke_id > 0 and int(mesh_edit_active_stroke.get("id", 0) or 0) != stroke_id:
            return
        if not _mesh_edit_restore_native_stroke_delta():
            snapshot = mesh_edit_active_stroke.get("snapshot")
            if snapshot is not None:
                _mesh_edit_restore_snapshot(snapshot)
        _mesh_edit_pop_active_stroke_snapshots()
        _mesh_edit_clear_active_stroke()
        _refresh_mesh_edit_controls()

    def _mesh_edit_commit_delete_result(result: object) -> None:
        _mesh_editor_store_result_mesh(result)
        if int(result.removed_face_count or 0) <= 0:
            _mesh_edit_pop_undo_snapshot()
            _pop_geometry_undo_snapshot()
            _refresh_mesh_edit_controls()
            mesh_edit_delete_faces_text = _mesh_edit_delete_faces_text_helper()
            self.set_status_message(mesh_edit_delete_faces_text["no_selected_vertices"])
            return
        _mesh_edit_disable_emptied_parts(result.emptied_submesh_indices)
        _morph_slider_mark_topology_changed(_mesh_edit_topology_changed_status_helper("remove_faces"))
        _mesh_edit_clear_topology_selection()
        native_update_applied = _mesh_editor_apply_result_native_update(result)
        _mesh_edit_update_mesh_totals()
        if not native_update_applied:
            _mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)
        mesh_edit_revision["value"] = int(mesh_edit_revision.get("value", 0) or 0) + 1
        _mesh_edit_commit_geometry_preview_state()
        _refresh_source_tree_selection_state()
        _refresh_source_assignment_columns()
        _refresh_mesh_edit_controls()
        if not native_update_applied:
            _mesh_edit_replace_live_triangles_or_queue_rebuild(result.affected_submesh_indices)
        self.set_status_message(_mesh_edit_deleted_selection_status_helper(result.removed_face_count))

    def _mesh_edit_delete_selected_faces() -> None:
        if _mesh_edit_state.replacement_mesh_for_mapping is None:
            return
        can_edit, reason = _mesh_edit_can_edit_scope()
        if not can_edit:
            QMessageBox.information(dialog, _mesh_edit_dialog_title_helper(), reason)
            return
        if _morph_slider_has_nonzero_values():
            mesh_edit_delete_faces_text = _mesh_edit_delete_faces_text_helper()
            QMessageBox.information(dialog, _mesh_edit_dialog_title_helper(), mesh_edit_delete_faces_text["morph_blocker"])
            return
        allowed_indices = set(_mesh_edit_allowed_source_indices())
        selected_faces = _mesh_edit_sorted_index_groups_helper(
            mesh_edit_selected_faces_by_submesh,
            allowed_source_indices=allowed_indices,
            mesh=_mesh_edit_state.replacement_mesh_for_mapping,
        )
        selected_vertices = _mesh_edit_sorted_index_groups_helper(
            mesh_edit_selected_vertices_by_submesh,
            allowed_source_indices=allowed_indices,
            mesh=_mesh_edit_state.replacement_mesh_for_mapping,
        )
        selected_sources = _mesh_editor_action_source_indices()
        selected_edges = _mesh_editor_edge_selection(selected_vertices, selected_faces)
        if not selected_faces and not selected_vertices and not selected_edges and not selected_sources:
            mesh_edit_delete_faces_text = _mesh_edit_delete_faces_text_helper()
            QMessageBox.information(dialog, _mesh_edit_dialog_title_helper(), mesh_edit_delete_faces_text["select_faces"])
            return
        params = {"remove_orphans": True, "recompute_normals": True}
        if _mesh_edit_start_topology_worker(
            "delete",
            action_text="Delete Selection",
            selected_vertices=selected_vertices,
            selected_faces=selected_faces,
            selected_edges=selected_edges,
            selected_source_indices=selected_sources,
            params=params,
            commit_callback=_mesh_edit_commit_delete_result,
        ):
            return
        _mesh_edit_record_snapshot()
        result = _mesh_editor_apply_static_replacement_edit(
            _mesh_edit_state.replacement_mesh_for_mapping,
            "delete",
            edges_by_submesh=selected_edges,
            faces_by_submesh=selected_faces,
            vertices_by_submesh=selected_vertices,
            source_indices=selected_sources,
            **params,
        )
        _mesh_edit_commit_delete_result(result)

    def _mesh_edit_commit_subdivide_result(result: object, *, refine_smooth: bool = False) -> None:
        _mesh_editor_store_result_mesh(result)
        if not result.affected_submesh_indices:
            _mesh_edit_pop_undo_snapshot()
            _pop_geometry_undo_snapshot()
            _refresh_mesh_edit_controls()
            mesh_edit_subdivide_text = _mesh_edit_subdivide_text_helper()
            self.set_status_message(mesh_edit_subdivide_text["no_selected_vertices"])
            return
        status_key = "refine_smooth_selection" if refine_smooth else "subdivide_selection"
        _morph_slider_mark_topology_changed(_mesh_edit_topology_changed_status_helper(status_key))
        mesh_edit_selected_vertices_by_submesh.clear()
        mesh_edit_selected_edges_by_submesh.clear()
        mesh_edit_selected_faces_by_submesh.clear()
        mesh_edit_selected_source_indices.clear()
        mesh_edit_selected_vertices_by_submesh.update(
            _mesh_edit_index_groups_as_sets_helper(result.changed_vertices_by_submesh or {})
        )
        native_update_applied = _mesh_editor_apply_result_native_update(result)
        _mesh_edit_update_mesh_totals()
        if not native_update_applied:
            _mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)
        mesh_edit_revision["value"] = int(mesh_edit_revision.get("value", 0) or 0) + 1
        _mesh_edit_commit_geometry_preview_state()
        _refresh_source_tree_selection_state()
        _refresh_source_assignment_columns()
        _refresh_mesh_edit_controls()
        _mesh_edit_sync_d3d11_selection()
        if not native_update_applied:
            _mesh_edit_replace_live_triangles_or_queue_rebuild(result.affected_submesh_indices)
        status = (
            _mesh_edit_refined_selection_status_helper(result.added_face_count)
            if refine_smooth and callable(_mesh_edit_refined_selection_status_helper)
            else _mesh_edit_subdivided_selection_status_helper(result.added_face_count)
        )
        self.set_status_message(status)

    def _mesh_edit_subdivide_selection(*, refine_smooth: bool = False) -> None:
        if _mesh_edit_state.replacement_mesh_for_mapping is None:
            return
        can_edit, reason = _mesh_edit_can_edit_scope()
        if not can_edit:
            QMessageBox.information(dialog, _mesh_edit_dialog_title_helper(), reason)
            return
        if _morph_slider_has_nonzero_values():
            mesh_edit_subdivide_text = _mesh_edit_subdivide_text_helper()
            QMessageBox.information(dialog, _mesh_edit_dialog_title_helper(), mesh_edit_subdivide_text["morph_blocker"])
            return
        allowed_indices = set(_mesh_edit_allowed_source_indices())
        selected_vertices = _mesh_edit_sorted_index_groups_helper(
            mesh_edit_selected_vertices_by_submesh,
            allowed_source_indices=allowed_indices,
            mesh=_mesh_edit_state.replacement_mesh_for_mapping,
        )
        selected_faces = _mesh_edit_sorted_index_groups_helper(
            mesh_edit_selected_faces_by_submesh,
            allowed_source_indices=allowed_indices,
            mesh=_mesh_edit_state.replacement_mesh_for_mapping,
        )
        selected_sources = _mesh_editor_action_source_indices()
        selected_edges = _mesh_editor_edge_selection(selected_vertices, selected_faces)
        if not selected_vertices and not selected_faces and not selected_edges and not selected_sources:
            mesh_edit_subdivide_text = _mesh_edit_subdivide_text_helper()
            QMessageBox.information(dialog, _mesh_edit_dialog_title_helper(), mesh_edit_subdivide_text["select_vertices"])
            return
        params = {
            "max_faces_per_submesh": 512,
            "recompute_normals": True,
            "smooth_iterations": int(mesh_edit_iterations_spin.value()) if refine_smooth else 2,
            "smooth_strength": (float(mesh_edit_strength_spin.value()) / 100.0) if refine_smooth else 0.5,
        }
        if _mesh_edit_start_topology_worker(
            "refine_smooth" if refine_smooth else "subdivide",
            action_text="Refine Smooth" if refine_smooth else "Subdivide",
            selected_vertices=selected_vertices,
            selected_faces=selected_faces,
            selected_edges=selected_edges,
            selected_source_indices=selected_sources,
            params=params,
            commit_callback=lambda result, refine=refine_smooth: _mesh_edit_commit_subdivide_result(
                result,
                refine_smooth=refine,
            ),
        ):
            return
        _mesh_edit_record_snapshot()
        result = _mesh_editor_apply_static_replacement_edit(
            _mesh_edit_state.replacement_mesh_for_mapping,
            "refine_smooth" if refine_smooth else "subdivide",
            vertices_by_submesh=selected_vertices,
            edges_by_submesh=selected_edges,
            faces_by_submesh=selected_faces,
            source_indices=selected_sources,
            **params,
        )
        _mesh_edit_commit_subdivide_result(result, refine_smooth=refine_smooth)

    def _mesh_edit_commit_split_result(result: object) -> None:
        split_text = _mesh_edit_split_text_helper()
        _mesh_editor_store_result_mesh(result)
        if int(getattr(result, "moved_face_count", 0) or 0) <= 0 or int(getattr(result, "new_submesh_index", -1)) < 0:
            _mesh_edit_pop_undo_snapshot()
            _pop_geometry_undo_snapshot()
            _refresh_mesh_edit_controls()
            self.set_status_message(split_text["no_selected_faces"])
            return
        source_index = int(result.source_submesh_index)
        new_source_index = int(result.new_submesh_index)
        if hasattr(appended_source_indices, "add"):
            appended_source_indices.add(new_source_index)
        selected_source_part["index"] = new_source_index
        source_geometry_revision["value"] = int(source_geometry_revision.get("value", 0) or 0) + 1
        _morph_slider_mark_topology_changed(_mesh_edit_topology_changed_status_helper("split_selection"))
        _mesh_edit_clear_topology_selection()
        if _alignment_d3d11_preview_active():
            alignment_d3d11_preview_host.clear_mesh_edit_vertex_selection()
        native_update_applied = _mesh_editor_apply_result_native_update(result)
        _mesh_edit_update_mesh_totals()
        if not native_update_applied:
            _mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)
        mesh_edit_revision["value"] = int(mesh_edit_revision.get("value", 0) or 0) + 1
        _mesh_edit_commit_geometry_preview_state()
        if callable(_rebuild_source_part_widgets):
            _rebuild_source_part_widgets()
        if source_tree is not None and isinstance(source_items_by_index, dict):
            item = source_items_by_index.get(new_source_index)
            if item is not None:
                blocked = source_tree.blockSignals(True)
                try:
                    source_tree.clearSelection()
                    item.setSelected(True)
                    source_tree.setCurrentItem(item)
                finally:
                    source_tree.blockSignals(blocked)
                source_tree.scrollToItem(item)
        _refresh_source_tree_selection_state()
        _refresh_source_assignment_columns()
        _refresh_mesh_edit_controls()
        if not native_update_applied:
            _mesh_edit_replace_live_triangles_or_queue_rebuild((source_index, new_source_index))
        self.set_status_message(_mesh_edit_split_selection_status_helper(result.moved_face_count))

    def _mesh_edit_split_selection_to_part() -> None:
        if _mesh_edit_state.replacement_mesh_for_mapping is None:
            return
        can_edit, reason = _mesh_edit_can_edit_scope()
        if not can_edit:
            QMessageBox.information(dialog, _mesh_edit_dialog_title_helper(), reason)
            return
        split_text = _mesh_edit_split_text_helper()
        if _morph_slider_has_nonzero_values():
            QMessageBox.information(dialog, _mesh_edit_dialog_title_helper(), split_text["morph_blocker"])
            return
        allowed_indices = set(_mesh_edit_allowed_source_indices())
        selected_faces = _mesh_edit_sorted_index_groups_helper(
            mesh_edit_selected_faces_by_submesh,
            allowed_source_indices=allowed_indices,
            mesh=_mesh_edit_state.replacement_mesh_for_mapping,
        )
        selected_vertices = _mesh_edit_sorted_index_groups_helper(
            mesh_edit_selected_vertices_by_submesh,
            allowed_source_indices=allowed_indices,
            mesh=_mesh_edit_state.replacement_mesh_for_mapping,
        )
        selected_sources = _mesh_editor_action_source_indices()
        selected_edges = _mesh_editor_edge_selection(selected_vertices, selected_faces)
        if not selected_faces and not selected_vertices and not selected_edges and not selected_sources:
            QMessageBox.information(dialog, _mesh_edit_dialog_title_helper(), split_text["select_faces"])
            return
        if _mesh_edit_start_topology_worker(
            "split",
            action_text="Split Selection To Part",
            selected_vertices=selected_vertices,
            selected_faces=selected_faces,
            selected_edges=selected_edges,
            selected_source_indices=selected_sources,
            params={"recompute_normals": True},
            commit_callback=_mesh_edit_commit_split_result,
        ):
            return
        _mesh_edit_record_snapshot()
        try:
            result = _mesh_editor_apply_static_replacement_edit(
                _mesh_edit_state.replacement_mesh_for_mapping,
                "split",
                faces_by_submesh=selected_faces,
                edges_by_submesh=selected_edges,
                vertices_by_submesh=selected_vertices,
                source_indices=selected_sources,
                recompute_normals=True,
            )
        except ValueError as exc:
            _mesh_edit_pop_undo_snapshot()
            _pop_geometry_undo_snapshot()
            _refresh_mesh_edit_controls()
            QMessageBox.information(dialog, _mesh_edit_dialog_title_helper(), split_text.get("multiple_parts", str(exc)))
            return
        _mesh_edit_commit_split_result(result)

    def _mesh_edit_clear_vertex_selection() -> None:
        mesh_edit_selected_vertices_by_submesh.clear()
        mesh_edit_selected_edges_by_submesh.clear()
        mesh_edit_selected_faces_by_submesh.clear()
        mesh_edit_selected_source_indices.clear()
        if _alignment_d3d11_preview_active():
            alignment_d3d11_preview_host.clear_mesh_edit_vertex_selection()
            _refresh_mesh_edit_controls()
            return
        for preview_widget in (static_dialog_preview, overlay_dialog_preview, replacement_only_preview):
            preview_widget.clear_mesh_edit_vertex_selection()
        _refresh_mesh_edit_controls()

    def _mesh_edit_current_selection() -> MeshEditSelection:
        return MeshEditSelection.from_maps(
            vertices_by_submesh=mesh_edit_selected_vertices_by_submesh,
            edges_by_submesh=mesh_edit_selected_edges_by_submesh,
            faces_by_submesh=mesh_edit_selected_faces_by_submesh,
            source_indices=mesh_edit_selected_source_indices,
        )

    def _mesh_edit_sync_d3d11_selection() -> bool:
        if not _alignment_d3d11_preview_active():
            return False
        group_sender = getattr(alignment_d3d11_preview_host, "set_mesh_edit_selection_groups", None)
        if not callable(group_sender) or _mesh_edit_state.replacement_mesh_for_mapping is None:
            _record_mesh_edit_event("mesh_edit_selection_group_update_unavailable")
            return False
        selection = _mesh_edit_current_selection()
        try:
            groups = mesh_edit_selection_groups(
                _mesh_edit_state.replacement_mesh_for_mapping,
                selection,
            )
        except Exception as exc:
            _record_mesh_edit_event("mesh_edit_selection_group_build_failed", message=str(exc))
            return False
        if not groups and not selection.is_empty():
            _record_mesh_edit_event("mesh_edit_selection_group_build_empty")
            return False
        if group_sender(groups):
            return True
        _record_mesh_edit_event(
            "mesh_edit_selection_group_update_failed",
            group_count=len(groups),
        )
        return False

    def _mesh_edit_set_vertex_selection(selected_vertices_by_submesh: Mapping[int, Iterable[int]]) -> None:
        mesh_edit_selected_vertices_by_submesh.clear()
        mesh_edit_selected_edges_by_submesh.clear()
        mesh_edit_selected_faces_by_submesh.clear()
        mesh_edit_selected_source_indices.clear()
        mesh_edit_selected_vertices_by_submesh.update(
            _mesh_edit_index_groups_as_sets_helper(selected_vertices_by_submesh or {})
        )
        _mesh_edit_sync_d3d11_selection()
        for preview_widget in (static_dialog_preview, overlay_dialog_preview, replacement_only_preview):
            if hasattr(preview_widget, "set_mesh_edit_vertex_selection"):
                preview_widget.set_mesh_edit_vertex_selection(mesh_edit_selected_vertices_by_submesh)
        _refresh_mesh_edit_controls()

    def _mesh_edit_set_source_selection(source_indices: Iterable[int]) -> None:
        allowed_sources = set(_mesh_edit_allowed_source_indices())
        selected_sources: set[int] = set()
        for raw_index in source_indices or ():
            try:
                source_index = int(raw_index)
            except (TypeError, ValueError):
                continue
            if source_index in allowed_sources:
                selected_sources.add(source_index)
        mesh_edit_selected_vertices_by_submesh.clear()
        mesh_edit_selected_edges_by_submesh.clear()
        mesh_edit_selected_faces_by_submesh.clear()
        mesh_edit_selected_source_indices.clear()
        mesh_edit_selected_source_indices.update(selected_sources)
        d3d11_synced = _mesh_edit_sync_d3d11_selection()
        if not d3d11_synced and not _alignment_d3d11_preview_active():
            legacy_selection = _mesh_edit_all_vertices_by_source_helper(
                _mesh_edit_state.replacement_mesh_for_mapping,
                selected_sources,
            )
            for preview_widget in (static_dialog_preview, overlay_dialog_preview, replacement_only_preview):
                if hasattr(preview_widget, "set_mesh_edit_vertex_selection"):
                    preview_widget.set_mesh_edit_vertex_selection(legacy_selection)
        _refresh_mesh_edit_controls()

    def _mesh_edit_finish_selection_worker(request_id: int) -> None:
        if int(request_id) != int(mesh_edit_selection_worker_state.get("request_id", 0) or 0):
            return
        mesh_edit_selection_worker_state.update({"thread": None, "worker": None, "start_revision": 0})
        _refresh_mesh_edit_controls()

    def _mesh_edit_selection_worker_progress(request_id: int, _percent: int, message: str) -> None:
        if int(request_id) == int(mesh_edit_selection_worker_state.get("request_id", 0) or 0) and message:
            self.set_status_message(str(message))

    def _mesh_edit_selection_worker_failed(request_id: int, message: str) -> None:
        if int(request_id) == int(mesh_edit_selection_worker_state.get("request_id", 0) or 0):
            self.set_status_message(str(message or "Selection update failed."), error=True)

    def _mesh_edit_selection_worker_cancelled(request_id: int, message: str) -> None:
        if int(request_id) == int(mesh_edit_selection_worker_state.get("request_id", 0) or 0):
            self.set_status_message(str(message or "Selection update cancelled."))

    def _mesh_edit_selection_worker_completed(request_id: int, result: object, session: object) -> None:
        if int(request_id) != int(mesh_edit_selection_worker_state.get("request_id", 0) or 0):
            return
        start_revision = int(mesh_edit_selection_worker_state.get("start_revision", 0) or 0)
        if int(mesh_edit_revision.get("value", 0) or 0) != start_revision:
            self.set_status_message("Selection result was discarded because the mesh changed while it was running.", error=True)
            return
        controller = getattr(session, "controller", None)
        session_view = getattr(controller, "session_view", None)
        if not callable(session_view):
            self.set_status_message("Selection update failed.", error=True)
            return
        selection = session_view().selection
        _mesh_edit_set_vertex_selection(selection.vertex_map())
        diagnostics = tuple(getattr(result, "diagnostics", ()) or ())
        if diagnostics:
            self.set_status_message(str(diagnostics[0]), error=True)
        else:
            self.set_status_message("Selection updated.")

    def _mesh_edit_start_selection_worker(operation: str, action_text: str) -> bool:
        if _mesh_edit_state.replacement_mesh_for_mapping is None or QThread is None:
            return False
        if _mesh_edit_worker_active():
            self.set_status_message("Wait for the current mesh edit to finish, or cancel it first.", error=True)
            return True
        session = _mesh_editor_ensure_static_replacement_session(_mesh_edit_state.replacement_mesh_for_mapping)
        if not isinstance(session, StaticReplacementMeshEditSession):
            return False
        selection = _mesh_edit_current_selection()
        if selection.is_empty():
            _mesh_edit_set_vertex_selection({})
            return True
        request_id = int(mesh_edit_selection_worker_state.get("request_id", 0) or 0) + 1
        worker = MeshEditCommandWorker(
            request_id,
            session.controller.mesh_service,
            session.session_id,
            MeshEditCommand("select", selection=selection, params={"operation": operation}, mode="edit"),
            action_text=action_text,
        )
        thread = QThread(dialog)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress_changed.connect(_mesh_edit_selection_worker_progress)
        worker.completed.connect(lambda finished_request_id, result, worker_session=session: _mesh_edit_selection_worker_completed(
            finished_request_id,
            result,
            worker_session,
        ))
        worker.cancelled.connect(_mesh_edit_selection_worker_cancelled)
        worker.error.connect(_mesh_edit_selection_worker_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda finished_request_id=request_id: _mesh_edit_finish_selection_worker(finished_request_id))
        mesh_edit_selection_worker_state.update(
            {
                "request_id": request_id,
                "thread": thread,
                "worker": worker,
                "start_revision": int(mesh_edit_revision.get("value", 0) or 0),
            }
        )
        _refresh_mesh_edit_controls()
        self.set_status_message(f"Updating {action_text} in the background...")
        thread.start(QThread.LowPriority)
        return True

    def _mesh_edit_native_all_vertex_selection(*, operation: str) -> dict[int, set[int]] | None:
        if _mesh_edit_state.replacement_mesh_for_mapping is None:
            return None
        allowed_sources = _mesh_edit_allowed_source_indices()
        if not allowed_sources:
            return None
        try:
            from cdmw.modding.mesh_native_core import prune_native_mesh_selection

            native_selection = prune_native_mesh_selection(
                _mesh_edit_state.replacement_mesh_for_mapping,
                vertices_by_submesh={},
                edges_by_submesh={},
                faces_by_submesh={},
                selected_all_vertices_by_submesh=allowed_sources,
                source_indices=allowed_sources,
                current_vertices_by_submesh=mesh_edit_selected_vertices_by_submesh,
                selection_operation=operation,
            )
        except Exception:
            return None
        if not isinstance(native_selection, Mapping):
            return None
        return _mesh_edit_index_groups_as_sets_helper(native_selection.get("vertices_by_submesh") or {})

    def _mesh_edit_native_vertex_selection(operation: str, *, iterations: int = 1) -> dict[int, set[int]] | None:
        if _mesh_edit_state.replacement_mesh_for_mapping is None:
            return None
        allowed_indices = set(_mesh_edit_allowed_source_indices())
        selected_vertices = _mesh_edit_sorted_index_groups_helper(
            mesh_edit_selected_vertices_by_submesh,
            allowed_source_indices=allowed_indices,
            mesh=_mesh_edit_state.replacement_mesh_for_mapping,
        )
        selected_faces = _mesh_edit_sorted_index_groups_helper(
            mesh_edit_selected_faces_by_submesh,
            allowed_source_indices=allowed_indices,
            mesh=_mesh_edit_state.replacement_mesh_for_mapping,
        )
        selected_edges = _mesh_editor_edge_selection(selected_vertices, selected_faces)
        selected_sources = _mesh_editor_action_source_indices()
        if not selected_vertices and not selected_edges and not selected_faces and not selected_sources:
            return {}
        try:
            from cdmw.modding.mesh_native_core import apply_native_mesh_selection

            native_selection = apply_native_mesh_selection(
                _mesh_edit_state.replacement_mesh_for_mapping,
                selected_vertices,
                selected_edges_by_submesh=selected_edges,
                selected_faces_by_submesh=selected_faces,
                source_indices=selected_sources,
                operation=operation,
                iterations=iterations,
            )
        except Exception:
            return None
        if not isinstance(native_selection, Mapping):
            return None
        return _mesh_edit_index_groups_as_sets_helper(native_selection)

    def _mesh_edit_native_selection_unavailable(action_text: str) -> None:
        mesh_edit_status_label.setText(f"Native {action_text} is unavailable.")
        _refresh_mesh_edit_controls()

    def _mesh_edit_select_whole_part() -> None:
        allowed_sources = _mesh_edit_allowed_source_indices()
        if allowed_sources:
            _mesh_edit_set_source_selection(allowed_sources)
            return
        selection = _mesh_edit_native_all_vertex_selection(operation="replace")
        if selection is not None:
            _mesh_edit_set_vertex_selection(selection)
            return
        _mesh_edit_native_selection_unavailable("Select Part")

    def _mesh_edit_invert_selection() -> None:
        allowed_sources = tuple(_mesh_edit_allowed_source_indices())
        if mesh_edit_selected_source_indices and not (
            mesh_edit_selected_vertices_by_submesh
            or mesh_edit_selected_edges_by_submesh
            or mesh_edit_selected_faces_by_submesh
        ):
            selected_sources = set(mesh_edit_selected_source_indices)
            _mesh_edit_set_source_selection(source for source in allowed_sources if source not in selected_sources)
            return
        selection = _mesh_edit_native_all_vertex_selection(operation="toggle")
        if selection is not None:
            _mesh_edit_set_vertex_selection(selection)
            return
        _mesh_edit_native_selection_unavailable("Invert Selection")

    def _mesh_edit_grow_selection() -> None:
        if _mesh_edit_state.replacement_mesh_for_mapping is None:
            return
        if _mesh_edit_start_selection_worker("grow", "Grow Selection"):
            return
        selection = _mesh_edit_native_vertex_selection("grow")
        if selection is not None:
            _mesh_edit_set_vertex_selection(selection)
            return
        _mesh_edit_native_selection_unavailable("Grow Selection")

    def _mesh_edit_shrink_selection() -> None:
        if _mesh_edit_state.replacement_mesh_for_mapping is None:
            return
        if _mesh_edit_start_selection_worker("shrink", "Shrink Selection"):
            return
        selection = _mesh_edit_native_vertex_selection("shrink")
        if selection is not None:
            _mesh_edit_set_vertex_selection(selection)
            return
        _mesh_edit_native_selection_unavailable("Shrink Selection")

    def _mesh_edit_smooth_selection() -> None:
        if _mesh_edit_state.replacement_mesh_for_mapping is None:
            return
        if _mesh_edit_start_selection_worker("smooth", "Smooth Selection"):
            return
        selection = _mesh_edit_native_vertex_selection("smooth")
        if selection is not None:
            _mesh_edit_set_vertex_selection(selection)
            return
        _mesh_edit_native_selection_unavailable("Smooth Selection")

    def _mesh_edit_selection_changed(payload: object) -> None:
        native_screen_selection = False
        if isinstance(payload, Mapping):
            screen_payload = _mesh_edit_native_screen_selection_payload(payload)
            if screen_payload:
                if not _mesh_edit_apply_native_screen_selection(payload, screen_payload):
                    mesh_edit_status_label.setText("Native D3D11 mesh selection failed.")
                    _refresh_mesh_edit_controls()
                    return
                native_screen_selection = True
        if not native_screen_selection:
            _mesh_edit_set_selection_state(MeshEditSelection())
        if isinstance(payload, Mapping) and not native_screen_selection:
            _mesh_edit_merge_vertex_groups(mesh_edit_selected_vertices_by_submesh, _mesh_edit_vertices_from_payload(payload))
            mesh_edit_selected_edges_by_submesh.update(_mesh_edit_edges_from_payload(payload))
            _mesh_edit_merge_face_groups(mesh_edit_selected_faces_by_submesh, _mesh_edit_faces_from_payload(payload))
        selected_count = _mesh_edit_index_group_count_helper(mesh_edit_selected_vertices_by_submesh)
        selected_count += _mesh_edit_selected_source_vertex_count()
        selected_face_count = _mesh_edit_index_group_count_helper(mesh_edit_selected_faces_by_submesh)
        can_edit, reason = _mesh_edit_can_edit_scope()
        if can_edit and mesh_edit_enabled_checkbox.isChecked() and _mesh_edit_tab_active():
            revision_text = int(mesh_edit_revision.get("value", 0) or 0)
            mesh_edit_status_label.setText(
                _mesh_edit_selection_status_text_helper(
                    reason,
                    selected_count,
                    selected_face_count,
                    revision_text,
                )
            )
        _refresh_mesh_edit_controls()

    def _mesh_edit_surface_tab_active(index: int | None = None) -> bool:
        try:
            tab_index = control_tabs.currentIndex() if index is None else int(index)
            if control_tabs.widget(tab_index) is mesh_edit_tab:
                return True
            return control_tabs.tabText(tab_index).strip().lower() in {
                "mesh editing",
                "classic mesh editing",
                "merged mesh editing",
            }
        except Exception:
            return False

    mesh_edit_surface_tab_state = {"active": _mesh_edit_surface_tab_active()}

    def _mesh_edit_control_tab_changed(index: int) -> None:
        mesh_edit_surface_tab_state["active"] = _mesh_edit_surface_tab_active(index)
        _refresh_mesh_edit_controls()
        _apply_alignment_dialog_responsive_layout()

    def _mesh_edit_enabled_toggled(_checked: bool = False) -> None:
        edit_enabled = bool(mesh_edit_enabled_checkbox.isChecked())
        if mesh_edit_preview_model_dirty.get("value") and not edit_enabled:
            _mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)
        _refresh_mesh_edit_controls()
        _mesh_edit_apply_preview_mode_transition("mesh_edit_toggle")
        if not edit_enabled:
            _queue_static_preview_refresh()
            _queue_texture_preview_refresh()

    mesh_edit_enabled_checkbox.toggled.connect(_mesh_edit_enabled_toggled)
    for widget in (
        mesh_edit_show_vertices_checkbox,
        mesh_edit_mirror_checkbox,
    ):
        widget.toggled.connect(lambda _checked=False: _refresh_mesh_edit_controls())
    mesh_edit_scope_combo.currentIndexChanged.connect(lambda _index: _refresh_mesh_edit_controls())
    mesh_edit_part_combo.currentIndexChanged.connect(lambda _index: _refresh_mesh_edit_controls())
    mesh_edit_tool_combo.currentIndexChanged.connect(lambda _index: _refresh_mesh_edit_controls())
    mesh_edit_delete_mode_combo.currentIndexChanged.connect(lambda _index: _refresh_mesh_edit_controls())
    mesh_edit_falloff_combo.currentIndexChanged.connect(lambda _index: _refresh_mesh_edit_controls())
    mesh_edit_iterations_spin.valueChanged.connect(lambda _value: _refresh_mesh_edit_controls())
    mesh_edit_selection_mode_combo.currentIndexChanged.connect(lambda _index: _refresh_mesh_edit_controls())
    mesh_edit_selection_depth_combo.currentIndexChanged.connect(lambda _index: _refresh_mesh_edit_controls())
    mesh_edit_radius_spin.valueChanged.connect(lambda _value: _refresh_mesh_edit_controls())
    mesh_edit_strength_spin.valueChanged.connect(lambda _value: _refresh_mesh_edit_controls())
    mesh_edit_radius_spin.editingFinished.connect(
        lambda: (_commit_spinbox_text(mesh_edit_radius_spin), _refresh_mesh_edit_controls())
    )
    mesh_edit_strength_spin.editingFinished.connect(
        lambda: (_commit_spinbox_text(mesh_edit_strength_spin), _refresh_mesh_edit_controls())
    )
    mesh_edit_clear_selection_button.clicked.connect(lambda _checked=False: _mesh_edit_clear_vertex_selection())
    mesh_edit_select_part_button.clicked.connect(lambda _checked=False: _mesh_edit_select_whole_part())
    mesh_edit_invert_selection_button.clicked.connect(lambda _checked=False: _mesh_edit_invert_selection())
    mesh_edit_grow_selection_button.clicked.connect(lambda _checked=False: _mesh_edit_grow_selection())
    mesh_edit_shrink_selection_button.clicked.connect(lambda _checked=False: _mesh_edit_shrink_selection())
    mesh_edit_smooth_selection_button.clicked.connect(lambda _checked=False: _mesh_edit_smooth_selection())
    mesh_edit_subdivide_selection_button.clicked.connect(lambda _checked=False: _mesh_edit_subdivide_selection())
    mesh_edit_refine_smooth_selection_button.clicked.connect(
        lambda _checked=False: _mesh_edit_subdivide_selection(refine_smooth=True)
    )
    mesh_edit_split_selection_button.clicked.connect(lambda _checked=False: _mesh_edit_split_selection_to_part())
    mesh_edit_delete_faces_button.clicked.connect(lambda _checked=False: _mesh_edit_delete_selected_faces())
    mesh_edit_undo_button.clicked.connect(lambda _checked=False: _mesh_edit_undo())
    mesh_edit_redo_button.clicked.connect(lambda _checked=False: _mesh_edit_redo())
    mesh_edit_reset_part_button.clicked.connect(lambda _checked=False: _mesh_edit_reset_scope())
    mesh_edit_full_reset_button.clicked.connect(lambda _checked=False: _mesh_edit_full_reset_mesh())
    morph_slider_create_button.clicked.connect(lambda _checked=False: _morph_slider_create_from_selection())
    morph_slider_import_action.triggered.connect(lambda _checked=False: _morph_slider_import_pack())
    morph_slider_add_action.triggered.connect(lambda _checked=False: _morph_slider_add_target())
    morph_slider_reload_action.triggered.connect(lambda _checked=False: _morph_slider_reload_profiles(preserve_values=True))
    morph_slider_reset_button.clicked.connect(lambda _checked=False: _morph_slider_reset_all())
    morph_slider_bake_button.clicked.connect(lambda _checked=False: _morph_slider_bake())

    return SimpleNamespace(
        _mesh_edit_adjusted_sources_for_live_preview=_mesh_edit_adjusted_sources_for_live_preview,
        _mesh_edit_all_live_vertices_for_sources=_mesh_edit_all_live_vertices_for_sources,
        _mesh_edit_allowed_source_indices=_mesh_edit_allowed_source_indices,
        _mesh_editor_action_bar_action_requested=_mesh_editor_action_bar_action_requested,
        _mesh_editor_embedded_apply_native_update=_mesh_editor_embedded_apply_native_update,
        _mesh_editor_embedded_controller=_mesh_editor_embedded_controller,
        _mesh_editor_embedded_run_part_action=_mesh_editor_embedded_run_part_action,
        _mesh_editor_embedded_set_skeleton_bone=_mesh_editor_embedded_set_skeleton_bone,
        _mesh_edit_apply_preview_payload=_mesh_edit_apply_preview_payload,
        _mesh_edit_base_source_index_is_editable=_mesh_edit_base_source_index_is_editable,
        _mesh_edit_begin_stroke=_mesh_edit_begin_stroke,
        _mesh_edit_can_edit_scope=_mesh_edit_can_edit_scope,
        _mesh_edit_cancel_stroke=_mesh_edit_cancel_stroke,
        _mesh_edit_clear_topology_selection=_mesh_edit_clear_topology_selection,
        _mesh_edit_clear_vertex_selection=_mesh_edit_clear_vertex_selection,
        _mesh_edit_commit_working_mesh=_mesh_edit_commit_working_mesh,
        _mesh_edit_control_tab_changed=_mesh_edit_control_tab_changed,
        _mesh_edit_current_tool=_mesh_edit_current_tool,
        _mesh_edit_delete_selected_faces=_mesh_edit_delete_selected_faces,
        _mesh_edit_disable_emptied_parts=_mesh_edit_disable_emptied_parts,
        _mesh_edit_enabled_toggled=_mesh_edit_enabled_toggled,
        _mesh_edit_faces_from_payload=_mesh_edit_faces_from_payload,
        _mesh_edit_finish_stroke=_mesh_edit_finish_stroke,
        _mesh_edit_full_reset_mesh=_mesh_edit_full_reset_mesh,
        _mesh_edit_grow_selection=_mesh_edit_grow_selection,
        _mesh_edit_invert_selection=_mesh_edit_invert_selection,
        _mesh_edit_live_vertex_update_groups=_mesh_edit_live_vertex_update_groups,
        _mesh_edit_merge_face_groups=_mesh_edit_merge_face_groups,
        _mesh_edit_merge_vertex_groups=_mesh_edit_merge_vertex_groups,
        _mesh_edit_part_enabled_snapshot=_mesh_edit_part_enabled_snapshot,
        _mesh_edit_payload_has_drag_motion=_mesh_edit_payload_has_drag_motion,
        _mesh_edit_pop_undo_snapshot=_mesh_edit_pop_undo_snapshot,
        _mesh_edit_preview_delta_to_source_delta=_mesh_edit_preview_delta_to_source_delta,
        _mesh_edit_preview_distance_to_source_distance=_mesh_edit_preview_distance_to_source_distance,
        _mesh_edit_preview_point_to_source_point=_mesh_edit_preview_point_to_source_point,
        _mesh_edit_preview_source_indices=_mesh_edit_preview_source_indices,
        _mesh_edit_push_undo_snapshot=_mesh_edit_push_undo_snapshot,
        _mesh_edit_record_snapshot=_mesh_edit_record_snapshot,
        _mesh_edit_redo=_mesh_edit_redo,
        _mesh_edit_replace_live_triangles=_mesh_edit_replace_live_triangles,
        _mesh_edit_replace_live_triangles_or_queue_rebuild=_mesh_edit_replace_live_triangles_or_queue_rebuild,
        _mesh_edit_replace_working_mesh=_mesh_edit_replace_working_mesh,
        _mesh_edit_reset_scope=_mesh_edit_reset_scope,
        _mesh_edit_restore_enabled_snapshot=_mesh_edit_restore_enabled_snapshot,
        _mesh_edit_restore_snapshot=_mesh_edit_restore_snapshot,
        _mesh_edit_scope_mode=_mesh_edit_scope_mode,
        _mesh_edit_select_whole_part=_mesh_edit_select_whole_part,
        _mesh_edit_selected_scope_source_index=_mesh_edit_selected_scope_source_index,
        _mesh_edit_selected_source_index=_mesh_edit_selected_source_index,
        _mesh_edit_selection_changed=_mesh_edit_selection_changed,
        _mesh_edit_selection_depth_mode=_mesh_edit_selection_depth_mode,
        _mesh_edit_selection_mode=_mesh_edit_selection_mode,
        _mesh_edit_set_vertex_selection=_mesh_edit_set_vertex_selection,
        _mesh_edit_shrink_selection=_mesh_edit_shrink_selection,
        _mesh_edit_smooth_selection=_mesh_edit_smooth_selection,
        _mesh_edit_source_index_is_editable=_mesh_edit_source_index_is_editable,
        _mesh_edit_source_to_preview_point=_mesh_edit_source_to_preview_point,
        _mesh_edit_stroke_id=_mesh_edit_stroke_id,
        _mesh_edit_split_selection_to_part=_mesh_edit_split_selection_to_part,
        _mesh_edit_subdivide_selection=_mesh_edit_subdivide_selection,
        _mesh_edit_submesh_for_live_preview=_mesh_edit_submesh_for_live_preview,
        _mesh_edit_target_mode_for_tool=_mesh_edit_target_mode_for_tool,
        _mesh_edit_transformed_sources_for_live_preview=_mesh_edit_transformed_sources_for_live_preview,
        _mesh_edit_triangle_replace_groups=_mesh_edit_triangle_replace_groups,
        _mesh_edit_undo=_mesh_edit_undo,
        _mesh_edit_update_live_preview=_mesh_edit_update_live_preview,
        _mesh_edit_update_mesh_totals=_mesh_edit_update_mesh_totals,
        _mesh_edit_vertices_from_payload=_mesh_edit_vertices_from_payload,
        _morph_slider_active_deltas=_morph_slider_active_deltas,
        _morph_slider_add_row=_morph_slider_add_row,
        _morph_slider_add_target=_morph_slider_add_target,
        _morph_slider_apply_to_working_mesh=_morph_slider_apply_to_working_mesh,
        _morph_slider_bake=_morph_slider_bake,
        _morph_slider_begin_change=_morph_slider_begin_change,
        _morph_slider_capture_post_edit_deltas=_morph_slider_capture_post_edit_deltas,
        _morph_slider_clear_rows=_morph_slider_clear_rows,
        _morph_slider_create_from_selection=_morph_slider_create_from_selection,
        _morph_slider_default_region_amount=_morph_slider_default_region_amount,
        _morph_slider_end_change=_morph_slider_end_change,
        _morph_slider_ensure_post_edit_deltas=_morph_slider_ensure_post_edit_deltas,
        _morph_slider_has_loaded_deltas=_morph_slider_has_loaded_deltas,
        _morph_slider_has_nonzero_values=_morph_slider_has_nonzero_values,
        _morph_slider_import_pack=_morph_slider_import_pack,
        _morph_slider_mark_topology_changed=_morph_slider_mark_topology_changed,
        _morph_slider_rebuild_rows=_morph_slider_rebuild_rows,
        _morph_slider_refresh_controls=_morph_slider_refresh_controls,
        _morph_slider_refresh_topology_block_state=_morph_slider_refresh_topology_block_state,
        _morph_slider_reload_profiles=_morph_slider_reload_profiles,
        _morph_slider_reset_all=_morph_slider_reset_all,
        _morph_slider_set_value=_morph_slider_set_value,
        _morph_slider_slider_only_mesh=_morph_slider_slider_only_mesh,
        _morph_slider_supported=_morph_slider_supported,
        _morph_slider_sync_row_widgets=_morph_slider_sync_row_widgets,
        _morph_slider_zero_post_edit_deltas=_morph_slider_zero_post_edit_deltas,
        _morph_slider_zero_post_edit_deltas_for_sources=_morph_slider_zero_post_edit_deltas_for_sources,
        _refresh_mesh_edit_controls=_refresh_mesh_edit_controls,
        _refresh_mesh_edit_part_combo=_refresh_mesh_edit_part_combo,
        _sync_mesh_edit_preview_settings=_sync_mesh_edit_preview_settings,
    )
