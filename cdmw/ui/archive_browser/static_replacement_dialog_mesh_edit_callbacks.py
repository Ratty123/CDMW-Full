"""Mesh-edit and morph-slider callback factory for static replacement dialog."""

from __future__ import annotations

from types import SimpleNamespace


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
    QPushButton = context.get('QPushButton')
    QSizePolicy = context.get('QSizePolicy')
    QSlider = context.get('QSlider')
    QTimer = context.get('QTimer')
    QWidget = context.get('QWidget')
    Qt = context.get('Qt')
    Sequence = context.get('Sequence')
    _alignment_d3d11_preview_active = context.get('_alignment_d3d11_preview_active')
    _alignment_d3d11_source_indices_for_editor_id = context.get('_alignment_d3d11_source_indices_for_editor_id')
    _alignment_mesh_edit_tab_active = context.get('_alignment_mesh_edit_tab_active')

    def _mesh_edit_tab_active() -> bool:
        if not callable(_alignment_mesh_edit_tab_active):
            return False
        return bool(_alignment_mesh_edit_tab_active())

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
    _mesh_edit_index_group_count_helper = context.get('_mesh_edit_index_group_count_helper')
    _mesh_edit_index_groups_as_sets_helper = context.get('_mesh_edit_index_groups_as_sets_helper')
    _mesh_edit_inverted_vertex_selection_helper = context.get('_mesh_edit_inverted_vertex_selection_helper')
    _mesh_edit_live_delete_status_helper = context.get('_mesh_edit_live_delete_status_helper')
    _mesh_edit_live_vertex_update_groups_helper = context.get('_mesh_edit_live_vertex_update_groups_helper')
    _mesh_edit_mapping_keys_helper = context.get('_mesh_edit_mapping_keys_helper')
    _mesh_edit_merge_index_groups_helper = context.get('_mesh_edit_merge_index_groups_helper')
    _mesh_edit_mesh_totals_helper = context.get('_mesh_edit_mesh_totals_helper')
    _mesh_edit_optional_sorted_indices_helper = context.get('_mesh_edit_optional_sorted_indices_helper')
    _mesh_edit_part_enabled_snapshot_helper = context.get('_mesh_edit_part_enabled_snapshot_helper')
    _mesh_edit_payload_choice_helper = context.get('_mesh_edit_payload_choice_helper')
    _mesh_edit_payload_float_helper = context.get('_mesh_edit_payload_float_helper')
    _mesh_edit_payload_has_drag_motion_helper = context.get('_mesh_edit_payload_has_drag_motion_helper')
    _mesh_edit_payload_int_helper = context.get('_mesh_edit_payload_int_helper')
    _mesh_edit_payload_selected_indices_helper = context.get('_mesh_edit_payload_selected_indices_helper')
    _mesh_edit_payload_vector3_helper = context.get('_mesh_edit_payload_vector3_helper')
    _mesh_edit_payload_vertex_groups_helper = context.get('_mesh_edit_payload_vertex_groups_helper')
    _mesh_edit_pending_live_normals_initial_state_helper = context.get('_mesh_edit_pending_live_normals_initial_state_helper')
    _mesh_edit_preview_to_source_point_helper = context.get('_mesh_edit_preview_to_source_point_helper')
    _mesh_edit_preview_to_source_vector_helper = context.get('_mesh_edit_preview_to_source_vector_helper')
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
    _queue_static_preview_rebuild = context.get('_queue_static_preview_rebuild')
    _record_runtime_event = context.get('_record_runtime_event')
    _refresh_source_assignment_columns = context.get('_refresh_source_assignment_columns')
    _refresh_source_tree_selection_state = context.get('_refresh_source_tree_selection_state')
    _safe_refresh_static_dialog_preview = context.get('_safe_refresh_static_dialog_preview')
    _source_display_name = context.get('_source_display_name')
    _source_index_is_enabled_renderable = context.get('_source_index_is_enabled_renderable')
    _transformed_replacement_sources = context.get('_transformed_replacement_sources')
    alignment_d3d11_preview_host = context.get('alignment_d3d11_preview_host')
    appended_source_indices = context.get('appended_source_indices')
    apply_brush_deformation = context.get('apply_brush_deformation')
    apply_morph_slider_values = context.get('apply_morph_slider_values')
    apply_vertex_delta = context.get('apply_vertex_delta')
    assert_mesh_topology_unchanged = context.get('assert_mesh_topology_unchanged')
    build_vertex_adjacency = context.get('build_vertex_adjacency')
    build_x_mirror_pairs = context.get('build_x_mirror_pairs')
    clone_mesh_for_editing = context.get('clone_mesh_for_editing')
    compact_orphan_vertices = context.get('compact_orphan_vertices')
    control_tabs = context.get('control_tabs')
    copy = context.get('copy')
    create_region_volume_slider_profile = context.get('create_region_volume_slider_profile')
    delete_faces_by_indices = context.get('delete_faces_by_indices')
    delete_faces_touching_vertices = context.get('delete_faces_touching_vertices')
    dialog = context.get('dialog')
    entry = context.get('entry')
    grow_vertex_selection = context.get('grow_vertex_selection')
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
    mesh_edit_reset_part_button = context.get('mesh_edit_reset_part_button')
    mesh_edit_revision = context.get('mesh_edit_revision')
    mesh_edit_scope_combo = context.get('mesh_edit_scope_combo')
    mesh_edit_select_part_button = context.get('mesh_edit_select_part_button')
    mesh_edit_selected_faces_by_submesh = context.get('mesh_edit_selected_faces_by_submesh')
    mesh_edit_selected_vertices_by_submesh = context.get('mesh_edit_selected_vertices_by_submesh')
    mesh_edit_selection_actions_widget = context.get('mesh_edit_selection_actions_widget')
    mesh_edit_selection_depth_combo = context.get('mesh_edit_selection_depth_combo')
    mesh_edit_selection_mode_combo = context.get('mesh_edit_selection_mode_combo')
    mesh_edit_show_vertices_checkbox = context.get('mesh_edit_show_vertices_checkbox')
    mesh_edit_shrink_selection_button = context.get('mesh_edit_shrink_selection_button')
    mesh_edit_smooth_selection_button = context.get('mesh_edit_smooth_selection_button')
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
    recompute_mesh_normals = context.get('recompute_mesh_normals')
    replacement_only_preview = context.get('replacement_only_preview')
    selected_source_part = context.get('selected_source_part')
    self = context.get('self')
    shrink_vertex_selection = context.get('shrink_vertex_selection')
    smooth_vertex_selection = context.get('smooth_vertex_selection')
    source_delta_for_transformed_delta = context.get('source_delta_for_transformed_delta')
    source_distance_for_transformed_distance = context.get('source_distance_for_transformed_distance')
    source_items_by_index = context.get('source_items_by_index')
    source_part_adjustments = context.get('source_part_adjustments')
    source_point_for_transformed_point = context.get('source_point_for_transformed_point')
    source_tree_item_update_guard = context.get('source_tree_item_update_guard')
    static_dialog_preview = context.get('static_dialog_preview')
    static_preview_geometry_cache = context.get('static_preview_geometry_cache')
    static_preview_prepared_cache = context.get('static_preview_prepared_cache')
    subdivide_faces_touching_vertices = context.get('subdivide_faces_touching_vertices')
    validate_morph_target = context.get('validate_morph_target')
    _mesh_edit_state = _MeshEditDialogState(context)
    mesh_edit_button_row.addStretch(1)
    mesh_edit_layout.addLayout(mesh_edit_button_row)
    mesh_edit_layout.addWidget(mesh_edit_reset_part_button)
    mesh_edit_layout.addWidget(mesh_edit_full_reset_button)
    mesh_edit_layout.addWidget(mesh_edit_status_label)

    _mesh_edit_scope_mode = lambda: _mesh_edit_scope_mode_helper(mesh_edit_scope_combo.currentData())
    _mesh_edit_current_tool = lambda: _mesh_edit_tool_helper(mesh_edit_tool_combo.currentData())
    _mesh_edit_target_mode_for_tool = lambda: _mesh_edit_target_mode_for_tool_helper(_mesh_edit_current_tool())
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
        morph_slider_post_edit_deltas[:] = _morph_slider_capture_post_edit_deltas_helper(
            _mesh_edit_state.replacement_mesh_for_mapping,
            slider_only_mesh,
        )

    def _morph_slider_apply_to_working_mesh(
        *,
        increment_revision: bool = True,
        refresh_controls: bool = True,
        status_message: str = "",
    ) -> bool:
        if _mesh_edit_state.replacement_mesh_base_for_mapping is None:
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
        _mesh_edit_state.replacement_preview_model = parsed_mesh_to_preview_model(_mesh_edit_state.replacement_mesh_for_mapping)
        if increment_revision:
            mesh_edit_revision["value"] = int(mesh_edit_revision.get("value", 0) or 0) + 1
        static_preview_geometry_cache.clear()
        static_preview_prepared_cache.clear()
        _refresh_source_tree_selection_state()
        _refresh_source_assignment_columns()
        if refresh_controls:
            _refresh_mesh_edit_controls()
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

    def _morph_slider_bake() -> None:
        bake_state = _morph_slider_bake_state_helper(
            has_working_mesh=_mesh_edit_state.replacement_mesh_for_mapping is not None,
            loaded=_morph_slider_has_loaded_deltas(),
            has_nonzero_values=_morph_slider_has_nonzero_values(),
        )
        if not bake_state.should_bake:
            return
        _morph_slider_begin_change(bake_state.change_label)
        _mesh_edit_state.replacement_mesh_base_for_mapping = clone_mesh_for_editing(_mesh_edit_state.replacement_mesh_for_mapping)
        morph_slider_values.clear()
        morph_slider_post_edit_deltas[:] = _morph_slider_zero_post_edit_deltas()
        morph_slider_topology_blocked["blocked"] = False
        morph_slider_topology_blocked["reason"] = ""
        _morph_slider_reload_profiles(preserve_values=False)
        mesh_edit_revision["value"] = int(mesh_edit_revision.get("value", 0) or 0) + 1
        static_preview_geometry_cache.clear()
        static_preview_prepared_cache.clear()
        _refresh_source_assignment_columns()
        _refresh_mesh_edit_controls()
        _queue_static_preview_rebuild()
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
        if _alignment_d3d11_preview_active():
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

    def _refresh_mesh_edit_controls() -> None:
        _refresh_mesh_edit_part_combo()
        allowed_indices = set(_mesh_edit_allowed_source_indices())
        pruned_selected_vertices = _mesh_edit_pruned_index_groups_helper(
            mesh_edit_selected_vertices_by_submesh,
            allowed_indices,
        )
        mesh_edit_selected_vertices_by_submesh.clear()
        mesh_edit_selected_vertices_by_submesh.update(pruned_selected_vertices)
        can_edit, reason = _mesh_edit_can_edit_scope()
        mesh_edit_group.setEnabled(mesh_edit_supported)
        mesh_edit_enabled_checkbox.setEnabled(mesh_edit_supported)
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
        )
        current_tool = _mesh_edit_current_tool()
        selected_count = _mesh_edit_index_group_count_helper(mesh_edit_selected_vertices_by_submesh)
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
        selection_active = bool(tool_context["selection_active"])
        selection_actions_visible = bool(tool_context["selection_actions_visible"])
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
            widget.setEnabled(editing_requested)
        mesh_edit_part_combo.setEnabled(editing_requested and _mesh_edit_scope_mode() == "selected")
        _set_mesh_edit_row_visible("scope", True)
        _set_mesh_edit_row_visible("part", True)
        _set_mesh_edit_row_visible("radius", sculpt_tool or remove_tool or brush_selection_tool)
        _set_mesh_edit_row_visible("strength", sculpt_tool)
        _set_mesh_edit_row_visible("falloff", sculpt_tool)
        _set_mesh_edit_row_visible("iterations", smooth_tool)
        _set_mesh_edit_row_visible("selection", select_tool)
        _set_mesh_edit_row_visible("depth", select_tool)
        mesh_edit_delete_mode_combo.setEnabled(editing_requested and remove_tool)
        mesh_edit_remove_mode_label.setVisible(remove_tool)
        mesh_edit_delete_mode_combo.setVisible(remove_tool)
        mesh_edit_radius_spin.setEnabled(editing_requested and (sculpt_tool or remove_tool or brush_selection_tool))
        mesh_edit_strength_spin.setEnabled(editing_requested and sculpt_tool)
        mesh_edit_falloff_combo.setEnabled(editing_requested and sculpt_tool)
        mesh_edit_iterations_spin.setEnabled(editing_requested and smooth_tool)
        mesh_edit_selection_mode_combo.setEnabled(editing_requested and select_tool)
        mesh_edit_selection_depth_combo.setEnabled(editing_requested and select_tool)
        mesh_edit_mirror_checkbox.setVisible(sculpt_tool)
        mesh_edit_mirror_checkbox.setEnabled(editing_requested and sculpt_tool)
        mesh_edit_option_widget.setVisible(True)
        mesh_edit_clear_selection_button.setVisible(selection_actions_visible)
        mesh_edit_select_part_button.setVisible(select_tool)
        mesh_edit_invert_selection_button.setVisible(select_tool)
        mesh_edit_selection_actions_widget.setVisible(selection_actions_visible)
        mesh_edit_subdivide_selection_button.setVisible(select_tool)
        mesh_edit_delete_faces_button.setVisible(select_tool)
        mesh_edit_clear_selection_button.setEnabled(selection_active)
        mesh_edit_select_part_button.setEnabled(editing_active and select_tool and bool(allowed_indices))
        mesh_edit_invert_selection_button.setEnabled(editing_active and select_tool and bool(allowed_indices))
        mesh_edit_grow_selection_button.setEnabled(selection_active)
        mesh_edit_shrink_selection_button.setEnabled(selection_active)
        mesh_edit_smooth_selection_button.setEnabled(selection_active)
        mesh_edit_subdivide_selection_button.setEnabled(
            select_tool and selection_active and not _morph_slider_has_nonzero_values()
        )
        mesh_edit_delete_faces_button.setEnabled(
            select_tool and selection_active
        )
        mesh_edit_undo_button.setEnabled(bool(mesh_edit_undo_stack))
        mesh_edit_redo_button.setEnabled(bool(mesh_edit_redo_stack))
        mesh_edit_reset_part_button.setEnabled(
            _mesh_edit_reset_available_helper(
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
        _morph_slider_refresh_controls()
        _sync_mesh_edit_preview_settings()

    def _mesh_edit_push_undo_snapshot(snapshot: ParsedMesh) -> None:
        mesh_edit_undo_stack.append(clone_mesh_for_editing(snapshot))
        mesh_edit_undo_adjustment_stack.append(_mesh_edit_part_enabled_snapshot())
        if len(mesh_edit_undo_stack) > 30:
            del mesh_edit_undo_stack[0]
            if mesh_edit_undo_adjustment_stack:
                del mesh_edit_undo_adjustment_stack[0]
        mesh_edit_redo_stack.clear()
        mesh_edit_redo_adjustment_stack.clear()

    def _mesh_edit_pop_undo_snapshot() -> None:
        if mesh_edit_undo_stack:
            mesh_edit_undo_stack.pop()
        if mesh_edit_undo_adjustment_stack:
            mesh_edit_undo_adjustment_stack.pop()

    _mesh_edit_part_enabled_snapshot = lambda: _mesh_edit_part_enabled_snapshot_helper(
        _mesh_edit_state.replacement_mesh_for_mapping,
        source_part_adjustments,
    )

    def _mesh_edit_restore_enabled_snapshot(snapshot: Mapping[int, bool]) -> None:
        for source_index, enabled in _mesh_edit_enabled_snapshot_items_helper(snapshot):
            if bool(enabled):
                adjustment = source_part_adjustments.get(source_index)
                if adjustment is not None:
                    adjustment.enabled = True
            else:
                adjustment = _ensure_source_part_adjustment(source_index)
                adjustment.enabled = False

    def _sync_source_tree_enabled_checks() -> None:
        source_tree_item_update_guard["active"] = True
        try:
            for source_index, source_item in source_items_by_index.items():
                adjustment = source_part_adjustments.get(int(source_index))
                source_item.setCheckState(0, Qt.Checked if adjustment is None or bool(adjustment.enabled) else Qt.Unchecked)
        finally:
            source_tree_item_update_guard["active"] = False

    def _mesh_edit_disable_emptied_parts(source_indices: Sequence[int]) -> None:
        for source_index in tuple(source_indices or ()):
            adjustment = _ensure_source_part_adjustment(int(source_index))
            adjustment.enabled = False
        _sync_source_tree_enabled_checks()

    def _mesh_edit_record_snapshot() -> None:
        if _mesh_edit_state.replacement_mesh_for_mapping is None:
            return
        _push_geometry_undo_snapshot("Mesh edit")
        _mesh_edit_push_undo_snapshot(_mesh_edit_state.replacement_mesh_for_mapping)

    def _mesh_edit_replace_working_mesh(snapshot: ParsedMesh) -> None:
        _mesh_edit_state.replacement_mesh_for_mapping = clone_mesh_for_editing(snapshot)
        _morph_slider_capture_post_edit_deltas()
        _mesh_edit_state.replacement_preview_model = parsed_mesh_to_preview_model(_mesh_edit_state.replacement_mesh_for_mapping)
        mesh_edit_revision["value"] = int(mesh_edit_revision.get("value", 0) or 0) + 1
        static_preview_geometry_cache.clear()
        static_preview_prepared_cache.clear()
        _sync_source_tree_enabled_checks()
        _refresh_source_assignment_columns()
        _refresh_mesh_edit_controls()
        if _alignment_d3d11_preview_active():
            _mesh_edit_replace_live_triangles(_mesh_edit_preview_source_indices())
        else:
            _queue_static_preview_rebuild()

    def _mesh_edit_undo() -> None:
        if _mesh_edit_state.replacement_mesh_for_mapping is None or not mesh_edit_undo_stack:
            return
        mesh_edit_redo_stack.append(clone_mesh_for_editing(_mesh_edit_state.replacement_mesh_for_mapping))
        mesh_edit_redo_adjustment_stack.append(_mesh_edit_part_enabled_snapshot())
        adjustment_snapshot = (
            mesh_edit_undo_adjustment_stack.pop()
            if mesh_edit_undo_adjustment_stack
            else _mesh_edit_part_enabled_snapshot()
        )
        snapshot = mesh_edit_undo_stack.pop()
        _mesh_edit_restore_enabled_snapshot(adjustment_snapshot)
        _mesh_edit_replace_working_mesh(snapshot)

    def _mesh_edit_redo() -> None:
        if _mesh_edit_state.replacement_mesh_for_mapping is None or not mesh_edit_redo_stack:
            return
        mesh_edit_undo_stack.append(clone_mesh_for_editing(_mesh_edit_state.replacement_mesh_for_mapping))
        mesh_edit_undo_adjustment_stack.append(_mesh_edit_part_enabled_snapshot())
        adjustment_snapshot = (
            mesh_edit_redo_adjustment_stack.pop()
            if mesh_edit_redo_adjustment_stack
            else _mesh_edit_part_enabled_snapshot()
        )
        snapshot = mesh_edit_redo_stack.pop()
        _mesh_edit_restore_enabled_snapshot(adjustment_snapshot)
        _mesh_edit_replace_working_mesh(snapshot)

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
        _mesh_edit_record_snapshot()
        for source_index in source_indices:
            working_source = _mesh_edit_state.replacement_mesh_for_mapping.submeshes[source_index]
            base_source = _mesh_edit_state.replacement_mesh_base_for_mapping.submeshes[source_index]
            restore_deleted_output = _mesh_edit_should_restore_deleted_output_helper(working_source, base_source)
            _mesh_edit_state.replacement_mesh_for_mapping.submeshes[source_index] = copy.deepcopy(
                base_source
            )
            mesh_edit_selected_vertices_by_submesh.pop(source_index, None)
            if restore_deleted_output:
                adjustment = _ensure_source_part_adjustment(source_index)
                adjustment.enabled = True
        if _morph_slider_has_loaded_deltas():
            _morph_slider_zero_post_edit_deltas_for_sources(source_indices)
            if _morph_slider_refresh_topology_block_state():
                _morph_slider_apply_to_working_mesh(increment_revision=False, refresh_controls=False)
        _mesh_edit_update_mesh_totals()
        _mesh_edit_state.replacement_preview_model = parsed_mesh_to_preview_model(_mesh_edit_state.replacement_mesh_for_mapping)
        mesh_edit_revision["value"] = int(mesh_edit_revision.get("value", 0) or 0) + 1
        static_preview_geometry_cache.clear()
        static_preview_prepared_cache.clear()
        _sync_source_tree_enabled_checks()
        _refresh_source_tree_selection_state()
        _refresh_source_assignment_columns()
        _refresh_mesh_edit_controls()
        if _alignment_d3d11_preview_active():
            _mesh_edit_replace_live_triangles(source_indices)
        else:
            _queue_static_preview_rebuild()

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
        _mesh_edit_record_snapshot()
        for source_index in source_indices:
            working_source = _mesh_edit_state.replacement_mesh_for_mapping.submeshes[source_index]
            base_source = _mesh_edit_state.replacement_mesh_base_for_mapping.submeshes[source_index]
            restore_deleted_output = _mesh_edit_should_restore_deleted_output_helper(working_source, base_source)
            _mesh_edit_state.replacement_mesh_for_mapping.submeshes[source_index] = copy.deepcopy(
                base_source
            )
            if restore_deleted_output:
                adjustment = _ensure_source_part_adjustment(source_index)
                adjustment.enabled = True
        mesh_edit_selected_vertices_by_submesh.clear()
        mesh_edit_selected_faces_by_submesh.clear()
        if _morph_slider_has_loaded_deltas():
            _morph_slider_zero_post_edit_deltas_for_sources(source_indices)
            _morph_slider_refresh_topology_block_state()
        _mesh_edit_update_mesh_totals()
        _mesh_edit_state.replacement_preview_model = parsed_mesh_to_preview_model(_mesh_edit_state.replacement_mesh_for_mapping)
        mesh_edit_revision["value"] = int(mesh_edit_revision.get("value", 0) or 0) + 1
        static_preview_geometry_cache.clear()
        static_preview_prepared_cache.clear()
        _sync_source_tree_enabled_checks()
        _refresh_source_tree_selection_state()
        _refresh_source_assignment_columns()
        _refresh_mesh_edit_controls()
        if _alignment_d3d11_preview_active():
            alignment_d3d11_preview_host.clear_mesh_edit_vertex_selection()
            _mesh_edit_replace_live_triangles(source_indices)
        else:
            _queue_static_preview_rebuild()

    _mesh_edit_preview_to_source_vector = lambda vector: _mesh_edit_preview_to_source_vector_helper(
        vector,
        getattr(original_reference_preview_model, "normalization_scale", 1.0),
    )
    _mesh_edit_preview_to_source_point = lambda point: _mesh_edit_preview_to_source_point_helper(
        point,
        normalization_center=getattr(original_reference_preview_model, "normalization_center", (0.0, 0.0, 0.0)),
        normalization_scale=getattr(original_reference_preview_model, "normalization_scale", 1.0),
    )

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
            _record_runtime_event("mesh_edit_live_transform_error", message=str(exc))
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
    mesh_edit_pending_live_vertices: Dict[int, set[int]] = {}
    mesh_edit_pending_live_normals = _mesh_edit_pending_live_normals_initial_state_helper()

    def _mesh_edit_live_vertex_update_groups(
        changed_vertices_by_submesh: Mapping[int, Iterable[int]] | None,
        *,
        include_normals: bool = False,
    ) -> List[Dict[str, object]]:
        if _mesh_edit_state.replacement_mesh_for_mapping is None or not changed_vertices_by_submesh:
            return []
        transformed_sources_by_index = _mesh_edit_transformed_sources_for_live_preview(
            int(source_index)
            for source_index in dict(changed_vertices_by_submesh or {}).keys()
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
        mesh_edit_pending_live_vertices.clear()
        mesh_edit_pending_live_normals["include"] = False
        if groups and _alignment_d3d11_preview_active():
            alignment_d3d11_preview_host.update_mesh_edit_vertices(groups)

    mesh_edit_live_update_timer.timeout.connect(_flush_mesh_edit_live_vertex_updates)

    def _queue_mesh_edit_live_vertex_updates(
        changed_vertices_by_submesh: Mapping[int, Iterable[int]] | None,
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
        transformed_sources_by_index = _mesh_edit_transformed_sources_for_live_preview(requested_source_indices)
        return _mesh_edit_triangle_replace_groups_helper(
            _mesh_edit_state.replacement_mesh_for_mapping,
            requested_source_indices,
            transformed_sources_by_index,
            source_to_preview_point=_mesh_edit_source_to_preview_point,
        )

    def _mesh_edit_replace_live_triangles(source_indices: Iterable[int]) -> bool:
        if _mesh_edit_state.replacement_mesh_for_mapping is None:
            return False
        if _alignment_d3d11_preview_active():
            mesh_edit_live_update_timer.stop()
            _flush_mesh_edit_live_vertex_updates()
            groups = _mesh_edit_triangle_replace_groups(source_indices)
            if groups:
                alignment_d3d11_preview_host.replace_mesh_edit_triangles(groups)
            return True
        return False

    def _mesh_edit_update_live_preview(
        changed_vertices_by_submesh: Mapping[int, Iterable[int]] | None = None,
        *,
        include_normals: bool = False,
        immediate: bool = False,
    ) -> None:
        if _mesh_edit_state.replacement_mesh_for_mapping is None:
            return
        _mesh_edit_update_mesh_totals()
        if _alignment_d3d11_preview_active():
            if changed_vertices_by_submesh:
                _queue_mesh_edit_live_vertex_updates(
                    changed_vertices_by_submesh,
                    include_normals=include_normals,
                    immediate=immediate,
                )
                return
            _mesh_edit_replace_live_triangles(_mesh_edit_preview_source_indices())
            return
        _mesh_edit_state.replacement_preview_model = parsed_mesh_to_preview_model(_mesh_edit_state.replacement_mesh_for_mapping)
        _safe_refresh_static_dialog_preview(live_mesh_edit=True)

    def _mesh_edit_begin_stroke(payload: object) -> None:
        if _mesh_edit_state.replacement_mesh_for_mapping is None or not isinstance(payload, Mapping):
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
            {"grab", "smooth", "inflate", "pinch", "remove", "vertex"},
        )
        delete_mode = _mesh_edit_payload_choice_helper(
            payload,
            "delete_mode",
            mesh_edit_delete_mode_combo.currentData() or "release",
            {"release", "live", "selection"},
        )
        _push_geometry_undo_snapshot("Mesh edit stroke")
        snapshot = clone_mesh_for_editing(_mesh_edit_state.replacement_mesh_for_mapping)
        _mesh_edit_push_undo_snapshot(snapshot)
        mesh_edit_active_stroke.clear()
        mesh_edit_active_stroke.update(
            {
                "id": stroke_id,
                "tool": tool,
                "delete_mode": delete_mode,
                "snapshot": clone_mesh_for_editing(snapshot),
                "base": clone_mesh_for_editing(snapshot),
                "before_topology": None if tool == "remove" else mesh_topology_signature(snapshot),
                "changed": False,
                "remove_faces_by_submesh": {},
                "remove_vertices_by_submesh": {},
                "live_delete_submeshes": set(),
                "mirror_pairs": {
                    index: build_x_mirror_pairs(submesh.vertices)
                    for index, submesh in enumerate(snapshot.submeshes)
                },
                "adjacency": {
                    index: build_vertex_adjacency(submesh)
                    for index, submesh in enumerate(snapshot.submeshes)
                },
            }
        )
        _refresh_mesh_edit_controls()

    def _mesh_edit_restore_snapshot(snapshot: ParsedMesh) -> None:
        _mesh_edit_state.replacement_mesh_for_mapping = clone_mesh_for_editing(snapshot)
        _mesh_edit_update_mesh_totals()
        _mesh_edit_state.replacement_preview_model = parsed_mesh_to_preview_model(_mesh_edit_state.replacement_mesh_for_mapping)
        static_preview_geometry_cache.clear()
        static_preview_prepared_cache.clear()
        if _alignment_d3d11_preview_active():
            _mesh_edit_replace_live_triangles(_mesh_edit_preview_source_indices())
            return
        _safe_refresh_static_dialog_preview(live_mesh_edit=True)

    _mesh_edit_payload_has_drag_motion = lambda payload: _mesh_edit_payload_has_drag_motion_helper(payload)

    def _mesh_edit_preview_delta_to_source_delta(
        source_index: int,
        transformed_delta: Sequence[object],
    ) -> tuple[float, float, float]:
        delta = _mesh_edit_vector3_or_zero_helper(transformed_delta)
        if not _mesh_edit_has_inverse_transform_context_helper(
            original_mesh=original_mesh_for_mapping,
            replacement_mesh=_mesh_edit_state.replacement_mesh_for_mapping,
            source_index=source_index,
        ):
            return delta
        try:
            return source_delta_for_transformed_delta(
                original_mesh_for_mapping,
                _mesh_edit_state.replacement_mesh_for_mapping,
                _current_static_alignment_transform(),
                int(source_index),
                delta,
                source_part_adjustments=_current_source_part_adjustments(),
                global_transform_exempt_indices=set(appended_source_indices),
                global_transform_source_indices=_mapped_source_indices(_current_dialog_mappings_for_preview()),
                alignment_basis_mesh=_mesh_edit_state.replacement_mesh_base_for_mapping or _mesh_edit_state.replacement_mesh_for_mapping,
            )
        except Exception as exc:
            _record_runtime_event(
                "mesh_edit_delta_inverse_error",
                source_index=int(source_index),
                message=str(exc),
            )
            return delta

    def _mesh_edit_preview_point_to_source_point(
        source_index: int,
        transformed_point: Sequence[object],
    ) -> tuple[float, float, float]:
        point = _mesh_edit_vector3_or_zero_helper(transformed_point)
        if not _mesh_edit_has_inverse_transform_context_helper(
            original_mesh=original_mesh_for_mapping,
            replacement_mesh=_mesh_edit_state.replacement_mesh_for_mapping,
            source_index=source_index,
        ):
            return point
        try:
            return source_point_for_transformed_point(
                original_mesh_for_mapping,
                _mesh_edit_state.replacement_mesh_for_mapping,
                _current_static_alignment_transform(),
                int(source_index),
                point,
                source_part_adjustments=_current_source_part_adjustments(),
                global_transform_exempt_indices=set(appended_source_indices),
                global_transform_source_indices=_mapped_source_indices(_current_dialog_mappings_for_preview()),
                alignment_basis_mesh=_mesh_edit_state.replacement_mesh_base_for_mapping or _mesh_edit_state.replacement_mesh_for_mapping,
            )
        except Exception as exc:
            _record_runtime_event(
                "mesh_edit_point_inverse_error",
                source_index=int(source_index),
                message=str(exc),
            )
            return point

    def _mesh_edit_preview_distance_to_source_distance(
        source_index: int,
        transformed_distance: float,
    ) -> float:
        distance = _mesh_edit_distance_or_zero_helper(transformed_distance)
        if not _mesh_edit_has_inverse_transform_context_helper(
            original_mesh=original_mesh_for_mapping,
            replacement_mesh=_mesh_edit_state.replacement_mesh_for_mapping,
            source_index=source_index,
        ):
            return abs(distance)
        try:
            return source_distance_for_transformed_distance(
                original_mesh_for_mapping,
                _mesh_edit_state.replacement_mesh_for_mapping,
                _current_static_alignment_transform(),
                int(source_index),
                distance,
                source_part_adjustments=_current_source_part_adjustments(),
                global_transform_exempt_indices=set(appended_source_indices),
                global_transform_source_indices=_mapped_source_indices(_current_dialog_mappings_for_preview()),
                alignment_basis_mesh=_mesh_edit_state.replacement_mesh_base_for_mapping or _mesh_edit_state.replacement_mesh_for_mapping,
            )
        except Exception as exc:
            _record_runtime_event(
                "mesh_edit_distance_inverse_error",
                source_index=int(source_index),
                message=str(exc),
            )
            return abs(distance)

    _mesh_edit_vertices_from_payload = lambda payload: _mesh_edit_payload_selected_indices_helper(
        payload,
        _mesh_edit_state.replacement_mesh_for_mapping,
        allowed_source_indices=_mesh_edit_allowed_source_indices(),
        source_indices_for_editor_id=_alignment_d3d11_source_indices_for_editor_id,
        payload_index_key="source_vertex_indices",
        mesh_collection_attr="vertices",
    )

    _mesh_edit_faces_from_payload = lambda payload: _mesh_edit_payload_selected_indices_helper(
        payload,
        _mesh_edit_state.replacement_mesh_for_mapping,
        allowed_source_indices=_mesh_edit_allowed_source_indices(),
        source_indices_for_editor_id=_alignment_d3d11_source_indices_for_editor_id,
        payload_index_key="source_face_indices",
        mesh_collection_attr="faces",
    )

    _mesh_edit_merge_vertex_groups = lambda target, source: _mesh_edit_merge_index_groups_helper(target, source)
    _mesh_edit_merge_face_groups = lambda target, source: _mesh_edit_merge_index_groups_helper(target, source)

    def _mesh_edit_clear_topology_selection() -> None:
        mesh_edit_selected_vertices_by_submesh.clear()
        mesh_edit_selected_faces_by_submesh.clear()
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
    ) -> None:
        if _mesh_edit_state.replacement_mesh_for_mapping is None:
            return
        _mesh_edit_update_mesh_totals()
        _morph_slider_capture_post_edit_deltas()
        _mesh_edit_state.replacement_preview_model = parsed_mesh_to_preview_model(_mesh_edit_state.replacement_mesh_for_mapping)
        mesh_edit_revision["value"] = int(mesh_edit_revision.get("value", 0) or 0) + 1
        static_preview_geometry_cache.clear()
        static_preview_prepared_cache.clear()
        _refresh_source_tree_selection_state()
        _refresh_source_assignment_columns()
        _refresh_mesh_edit_controls()
        if _alignment_d3d11_preview_active():
            if topology_source_indices is not None:
                _mesh_edit_replace_live_triangles(tuple(topology_source_indices))
            else:
                _mesh_edit_update_live_preview(
                    _mesh_edit_all_live_vertices_for_sources(normal_source_indices or _mesh_edit_preview_source_indices()),
                    include_normals=True,
                    immediate=True,
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
            {"grab", "smooth", "inflate", "pinch", "remove", "vertex"},
        )
        if tool == "remove":
            delete_mode = _mesh_edit_payload_choice_helper(
                payload,
                "delete_mode",
                mesh_edit_active_stroke.get("delete_mode") or mesh_edit_delete_mode_combo.currentData() or "release",
                {"release", "live", "selection"},
            )
            vertices_by_submesh = _mesh_edit_vertices_from_payload(payload)
            faces_by_submesh = _mesh_edit_faces_from_payload(payload)
            if not vertices_by_submesh and not faces_by_submesh:
                return
            if delete_mode == "selection":
                _mesh_edit_merge_vertex_groups(mesh_edit_selected_vertices_by_submesh, vertices_by_submesh)
                _mesh_edit_merge_face_groups(mesh_edit_selected_faces_by_submesh, faces_by_submesh)
                _refresh_mesh_edit_controls()
                return
            if delete_mode == "live":
                if faces_by_submesh:
                    result = delete_faces_by_indices(
                        _mesh_edit_state.replacement_mesh_for_mapping,
                        faces_by_submesh,
                        remove_orphans=False,
                        recompute_normals=False,
                    )
                else:
                    result = delete_faces_touching_vertices(
                        _mesh_edit_state.replacement_mesh_for_mapping,
                        vertices_by_submesh,
                        remove_orphans=False,
                        recompute_normals=False,
                    )
                if int(result.removed_face_count or 0) <= 0:
                    return
                live_submeshes = mesh_edit_active_stroke.setdefault("live_delete_submeshes", set())
                if isinstance(live_submeshes, set):
                    live_submeshes.update(int(index) for index in result.affected_submesh_indices)
                mesh_edit_active_stroke["live_removed_face_count"] = int(
                    mesh_edit_active_stroke.get("live_removed_face_count", 0) or 0
                ) + int(result.removed_face_count or 0)
                mesh_edit_active_stroke["changed"] = True
                if _alignment_d3d11_preview_active():
                    _mesh_edit_replace_live_triangles(result.affected_submesh_indices)
                else:
                    _mesh_edit_update_live_preview()
                return
            remove_faces = mesh_edit_active_stroke.setdefault("remove_faces_by_submesh", {})
            if isinstance(remove_faces, dict):
                _mesh_edit_merge_face_groups(remove_faces, faces_by_submesh)  # type: ignore[arg-type]
            remove_vertices = mesh_edit_active_stroke.setdefault("remove_vertices_by_submesh", {})
            if isinstance(remove_vertices, dict):
                _mesh_edit_merge_vertex_groups(remove_vertices, vertices_by_submesh)  # type: ignore[arg-type]
            _refresh_mesh_edit_controls()
            return
        if tool in {"grab", "vertex"} and not _mesh_edit_payload_has_drag_motion(payload):
            return
        if tool in {"grab", "vertex"} and isinstance(mesh_edit_active_stroke.get("base"), ParsedMesh):
            _mesh_edit_state.replacement_mesh_for_mapping = clone_mesh_for_editing(mesh_edit_active_stroke["base"])  # type: ignore[index]
        center = _mesh_edit_preview_to_source_point(_mesh_edit_payload_vector3_helper(payload, "center"))
        delta_payload = _mesh_edit_payload_vector3_helper(payload, "delta")
        delta = _mesh_edit_preview_to_source_vector(delta_payload)
        step_delta = _mesh_edit_preview_to_source_vector(
            _mesh_edit_payload_vector3_helper(payload, "step_delta", delta_payload)
        )
        scale = max(float(getattr(original_reference_preview_model, "normalization_scale", 1.0) or 1.0), 1e-8)
        radius = max(1e-8, _mesh_edit_payload_float_helper(payload, "radius") / scale)
        amount = _mesh_edit_payload_float_helper(payload, "amount") / scale
        strength = _mesh_edit_payload_float_helper(payload, "strength", minimum=0.0, maximum=1.0)
        falloff = str(payload.get("falloff") or "smooth")
        smooth_iterations = _mesh_edit_payload_int_helper(payload, "smooth_iterations", int(mesh_edit_iterations_spin.value()))
        mirror_pairs_by_submesh = mesh_edit_active_stroke.get("mirror_pairs", {})
        adjacency_by_submesh = mesh_edit_active_stroke.get("adjacency", {})
        changed_any = False
        changed_vertices_by_submesh: Dict[int, set[int]] = {}
        vertex_groups = _mesh_edit_payload_vertex_groups_helper(
            payload,
            _mesh_edit_state.replacement_mesh_for_mapping,
            allowed_source_indices=_mesh_edit_allowed_source_indices(),
            source_indices_for_editor_id=_alignment_d3d11_source_indices_for_editor_id,
        )
        for source_submesh_index, vertex_indices, vertex_weights in vertex_groups:
            submesh = _mesh_edit_state.replacement_mesh_for_mapping.submeshes[source_submesh_index]
            source_delta = _mesh_edit_preview_delta_to_source_delta(source_submesh_index, delta)
            source_step_delta = _mesh_edit_preview_delta_to_source_delta(source_submesh_index, step_delta)
            source_center = _mesh_edit_preview_point_to_source_point(source_submesh_index, center)
            source_radius = _mesh_edit_preview_distance_to_source_distance(source_submesh_index, radius)
            source_amount = _mesh_edit_preview_distance_to_source_distance(source_submesh_index, amount)
            mirror_pairs = (
                mirror_pairs_by_submesh.get(source_submesh_index)
                if isinstance(mirror_pairs_by_submesh, Mapping)
                else None
            )
            adjacency = (
                adjacency_by_submesh.get(source_submesh_index)
                if isinstance(adjacency_by_submesh, Mapping)
                else None
            )
            if tool == "vertex":
                changed = apply_vertex_delta(
                    submesh,
                    vertex_indices,
                    source_delta,
                    mirror_x=bool(mesh_edit_mirror_checkbox.isChecked()),
                    mirror_pairs=mirror_pairs if isinstance(mirror_pairs, Mapping) else None,
                    recompute_normals=False,
                )
            else:
                changed = apply_brush_deformation(
                    submesh,
                    tool=tool,
                    center=source_center,
                    radius=source_radius,
                    strength=strength,
                    drag_delta=source_delta if tool in {"grab"} else source_step_delta,
                    amount=source_amount,
                    falloff=falloff,
                    vertex_indices=vertex_indices,
                    vertex_weights=vertex_weights or None,
                    mirror_x=bool(mesh_edit_mirror_checkbox.isChecked()),
                    mirror_pairs=mirror_pairs if isinstance(mirror_pairs, Mapping) else None,
                    adjacency=adjacency if isinstance(adjacency, (list, tuple)) else None,
                    iterations=smooth_iterations,
                    invert=bool(payload.get("invert")),
                    recompute_normals=False,
                )
            changed_any = changed_any or bool(changed)
            if changed:
                changed_vertices_by_submesh.setdefault(source_submesh_index, set()).update(
                    int(index) for index in tuple(changed or ()) if int(index) >= 0
                )
                stroke_changed_vertices = mesh_edit_active_stroke.setdefault("changed_vertices_by_submesh", {})
                if isinstance(stroke_changed_vertices, dict):
                    stroke_changed_vertices.setdefault(source_submesh_index, set()).update(
                        int(index) for index in tuple(changed or ()) if int(index) >= 0
                    )
        if not changed_any:
            return
        try:
            before_topology = mesh_edit_active_stroke.get("before_topology")
            if before_topology is not None:
                assert_mesh_topology_unchanged(before_topology, _mesh_edit_state.replacement_mesh_for_mapping)  # type: ignore[arg-type]
        except Exception as exc:
            snapshot = mesh_edit_active_stroke.get("snapshot")
            if isinstance(snapshot, ParsedMesh):
                _mesh_edit_restore_snapshot(snapshot)
            _mesh_edit_pop_undo_snapshot()
            _pop_geometry_undo_snapshot()
            mesh_edit_active_stroke.clear()
            _refresh_mesh_edit_controls()
            QMessageBox.warning(dialog, _mesh_edit_blocked_title_helper(), str(exc))
            return
        mesh_edit_active_stroke["changed"] = True
        _mesh_edit_update_live_preview(changed_vertices_by_submesh)

    def _mesh_edit_finish_stroke(payload: object) -> None:
        stroke_id = _mesh_edit_stroke_id(payload)
        if stroke_id <= 0 or int(mesh_edit_active_stroke.get("id", 0) or 0) != stroke_id:
            return
        tool = _mesh_edit_payload_choice_helper(
            payload if isinstance(payload, Mapping) else {},
            "tool",
            mesh_edit_active_stroke.get("tool") or _mesh_edit_current_tool(),
            {"grab", "smooth", "inflate", "pinch", "remove", "vertex"},
        )
        if tool == "remove":
            if _mesh_edit_state.replacement_mesh_for_mapping is None:
                mesh_edit_active_stroke.clear()
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
                mesh_edit_active_stroke.clear()
                _refresh_mesh_edit_controls()
                return
            if delete_mode == "live":
                changed = bool(mesh_edit_active_stroke.get("changed"))
                if not changed:
                    _mesh_edit_pop_undo_snapshot()
                    _pop_geometry_undo_snapshot()
                    mesh_edit_active_stroke.clear()
                    _refresh_mesh_edit_controls()
                    return
                live_submeshes = mesh_edit_active_stroke.get("live_delete_submeshes", set())
                submesh_indices = _mesh_edit_optional_sorted_indices_helper(live_submeshes)
                compact_result = compact_orphan_vertices(
                    _mesh_edit_state.replacement_mesh_for_mapping,
                    submesh_indices=submesh_indices,
                    recompute_normals=True,
                )
                _mesh_edit_disable_emptied_parts(compact_result.emptied_submesh_indices)
                _morph_slider_mark_topology_changed(_mesh_edit_topology_changed_status_helper("remove_faces"))
                _mesh_edit_clear_topology_selection()
                removed_faces = int(mesh_edit_active_stroke.get("live_removed_face_count", 0) or 0)
                topology_sources = _mesh_edit_topology_source_indices_helper(
                    live_submeshes,
                    compact_result.affected_submesh_indices,
                )
                mesh_edit_active_stroke.clear()
                _mesh_edit_commit_working_mesh(
                    _mesh_edit_live_delete_status_helper(removed_faces),
                    topology_source_indices=topology_sources,
                )
                return
            remove_faces = mesh_edit_active_stroke.get("remove_faces_by_submesh", {})
            selected_faces = _mesh_edit_sorted_index_groups_helper(remove_faces)
            remove_vertices = mesh_edit_active_stroke.get("remove_vertices_by_submesh", {})
            selected_vertices = _mesh_edit_sorted_index_groups_helper(remove_vertices)
            if not selected_faces and not selected_vertices:
                _mesh_edit_pop_undo_snapshot()
                _pop_geometry_undo_snapshot()
                mesh_edit_active_stroke.clear()
                _refresh_mesh_edit_controls()
                return
            if selected_faces:
                result = delete_faces_by_indices(
                    _mesh_edit_state.replacement_mesh_for_mapping,
                    selected_faces,
                    remove_orphans=True,
                    recompute_normals=True,
                )
            else:
                result = delete_faces_touching_vertices(
                    _mesh_edit_state.replacement_mesh_for_mapping,
                    selected_vertices,
                    remove_orphans=True,
                    recompute_normals=True,
                )
            if int(result.removed_face_count or 0) <= 0:
                _mesh_edit_pop_undo_snapshot()
                _pop_geometry_undo_snapshot()
                mesh_edit_active_stroke.clear()
                _refresh_mesh_edit_controls()
                mesh_edit_delete_faces_text = _mesh_edit_delete_faces_text_helper()
                self.set_status_message(mesh_edit_delete_faces_text["no_brush_faces"])
                return
            _mesh_edit_disable_emptied_parts(result.emptied_submesh_indices)
            _morph_slider_mark_topology_changed(_mesh_edit_topology_changed_status_helper("remove_faces"))
            _mesh_edit_clear_topology_selection()
            affected_sources = tuple(result.affected_submesh_indices)
            mesh_edit_active_stroke.clear()
            _mesh_edit_commit_working_mesh(
                _mesh_edit_deleted_faces_status_helper(result.removed_face_count),
                topology_source_indices=affected_sources,
            )
            return
        changed = bool(mesh_edit_active_stroke.get("changed"))
        if not changed:
            _mesh_edit_pop_undo_snapshot()
            _pop_geometry_undo_snapshot()
            mesh_edit_active_stroke.clear()
            _refresh_mesh_edit_controls()
            return
        if _mesh_edit_state.replacement_mesh_for_mapping is None:
            mesh_edit_active_stroke.clear()
            _refresh_mesh_edit_controls()
            return
        recompute_mesh_normals(_mesh_edit_state.replacement_mesh_for_mapping)
        try:
            before_topology = mesh_edit_active_stroke.get("before_topology")
            if before_topology is not None:
                assert_mesh_topology_unchanged(before_topology, _mesh_edit_state.replacement_mesh_for_mapping)  # type: ignore[arg-type]
        except Exception as exc:
            snapshot = mesh_edit_active_stroke.get("snapshot")
            if isinstance(snapshot, ParsedMesh):
                _mesh_edit_restore_snapshot(snapshot)
            _mesh_edit_pop_undo_snapshot()
            _pop_geometry_undo_snapshot()
            mesh_edit_active_stroke.clear()
            _refresh_mesh_edit_controls()
            QMessageBox.warning(dialog, _mesh_edit_blocked_title_helper(), str(exc))
            return
        _morph_slider_capture_post_edit_deltas()
        _mesh_edit_update_mesh_totals()
        _mesh_edit_state.replacement_preview_model = parsed_mesh_to_preview_model(_mesh_edit_state.replacement_mesh_for_mapping)
        mesh_edit_revision["value"] = int(mesh_edit_revision.get("value", 0) or 0) + 1
        static_preview_geometry_cache.clear()
        static_preview_prepared_cache.clear()
        changed_sources_payload = mesh_edit_active_stroke.get("changed_vertices_by_submesh", {})
        changed_sources = _mesh_edit_mapping_keys_helper(changed_sources_payload)
        mesh_edit_active_stroke.clear()
        _refresh_mesh_edit_controls()
        if _alignment_d3d11_preview_active():
            _mesh_edit_update_live_preview(
                _mesh_edit_all_live_vertices_for_sources(changed_sources or _mesh_edit_preview_source_indices()),
                include_normals=True,
                immediate=True,
            )
        else:
            _queue_static_preview_rebuild()

    def _mesh_edit_cancel_stroke(payload: object) -> None:
        if not mesh_edit_active_stroke:
            return
        stroke_id = _mesh_edit_stroke_id(payload)
        if stroke_id > 0 and int(mesh_edit_active_stroke.get("id", 0) or 0) != stroke_id:
            return
        snapshot = mesh_edit_active_stroke.get("snapshot")
        if isinstance(snapshot, ParsedMesh):
            _mesh_edit_restore_snapshot(snapshot)
        _mesh_edit_pop_undo_snapshot()
        _pop_geometry_undo_snapshot()
        mesh_edit_active_stroke.clear()
        _refresh_mesh_edit_controls()

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
        if not selected_faces and not selected_vertices:
            mesh_edit_delete_faces_text = _mesh_edit_delete_faces_text_helper()
            QMessageBox.information(dialog, _mesh_edit_dialog_title_helper(), mesh_edit_delete_faces_text["select_faces"])
            return
        _mesh_edit_record_snapshot()
        if selected_faces:
            result = delete_faces_by_indices(
                _mesh_edit_state.replacement_mesh_for_mapping,
                selected_faces,
                remove_orphans=True,
                recompute_normals=True,
            )
        else:
            result = delete_faces_touching_vertices(
                _mesh_edit_state.replacement_mesh_for_mapping,
                selected_vertices,
                remove_orphans=True,
                recompute_normals=True,
            )
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
        _mesh_edit_update_mesh_totals()
        _mesh_edit_state.replacement_preview_model = parsed_mesh_to_preview_model(_mesh_edit_state.replacement_mesh_for_mapping)
        mesh_edit_revision["value"] = int(mesh_edit_revision.get("value", 0) or 0) + 1
        static_preview_geometry_cache.clear()
        static_preview_prepared_cache.clear()
        _refresh_source_tree_selection_state()
        _refresh_source_assignment_columns()
        _refresh_mesh_edit_controls()
        if _alignment_d3d11_preview_active():
            _mesh_edit_replace_live_triangles(result.affected_submesh_indices)
        else:
            _queue_static_preview_rebuild()
        self.set_status_message(_mesh_edit_deleted_selection_status_helper(result.removed_face_count))

    def _mesh_edit_subdivide_selection() -> None:
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
        if not selected_vertices:
            mesh_edit_subdivide_text = _mesh_edit_subdivide_text_helper()
            QMessageBox.information(dialog, _mesh_edit_dialog_title_helper(), mesh_edit_subdivide_text["select_vertices"])
            return
        _mesh_edit_record_snapshot()
        result = subdivide_faces_touching_vertices(
            _mesh_edit_state.replacement_mesh_for_mapping,
            selected_vertices,
            max_faces_per_submesh=512,
            recompute_normals=True,
        )
        if not result.affected_submesh_indices:
            _mesh_edit_pop_undo_snapshot()
            _pop_geometry_undo_snapshot()
            _refresh_mesh_edit_controls()
            mesh_edit_subdivide_text = _mesh_edit_subdivide_text_helper()
            self.set_status_message(mesh_edit_subdivide_text["no_selected_vertices"])
            return
        _morph_slider_mark_topology_changed(_mesh_edit_topology_changed_status_helper("subdivide_selection"))
        mesh_edit_selected_vertices_by_submesh.clear()
        mesh_edit_selected_faces_by_submesh.clear()
        mesh_edit_selected_vertices_by_submesh.update(
            _mesh_edit_index_groups_as_sets_helper(result.changed_vertices_by_submesh or {})
        )
        _mesh_edit_update_mesh_totals()
        _mesh_edit_state.replacement_preview_model = parsed_mesh_to_preview_model(_mesh_edit_state.replacement_mesh_for_mapping)
        mesh_edit_revision["value"] = int(mesh_edit_revision.get("value", 0) or 0) + 1
        static_preview_geometry_cache.clear()
        static_preview_prepared_cache.clear()
        _refresh_source_tree_selection_state()
        _refresh_source_assignment_columns()
        _refresh_mesh_edit_controls()
        if _alignment_d3d11_preview_active():
            alignment_d3d11_preview_host.set_mesh_edit_vertex_selection(mesh_edit_selected_vertices_by_submesh)
            _mesh_edit_replace_live_triangles(result.affected_submesh_indices)
        else:
            _queue_static_preview_rebuild()
        self.set_status_message(_mesh_edit_subdivided_selection_status_helper(result.added_face_count))

    def _mesh_edit_clear_vertex_selection() -> None:
        mesh_edit_selected_vertices_by_submesh.clear()
        mesh_edit_selected_faces_by_submesh.clear()
        if _alignment_d3d11_preview_active():
            alignment_d3d11_preview_host.clear_mesh_edit_vertex_selection()
            _refresh_mesh_edit_controls()
            return
        for preview_widget in (static_dialog_preview, overlay_dialog_preview, replacement_only_preview):
            preview_widget.clear_mesh_edit_vertex_selection()
        _refresh_mesh_edit_controls()

    def _mesh_edit_set_vertex_selection(selected_vertices_by_submesh: Mapping[int, Iterable[int]]) -> None:
        mesh_edit_selected_vertices_by_submesh.clear()
        mesh_edit_selected_faces_by_submesh.clear()
        mesh_edit_selected_vertices_by_submesh.update(
            _mesh_edit_index_groups_as_sets_helper(selected_vertices_by_submesh or {})
        )
        if _alignment_d3d11_preview_active():
            alignment_d3d11_preview_host.set_mesh_edit_vertex_selection(mesh_edit_selected_vertices_by_submesh)
        for preview_widget in (static_dialog_preview, overlay_dialog_preview, replacement_only_preview):
            if hasattr(preview_widget, "set_mesh_edit_vertex_selection"):
                preview_widget.set_mesh_edit_vertex_selection(mesh_edit_selected_vertices_by_submesh)
        _refresh_mesh_edit_controls()

    _mesh_edit_all_vertices_in_scope = lambda: _mesh_edit_all_vertices_by_source_helper(
        _mesh_edit_state.replacement_mesh_for_mapping,
        _mesh_edit_allowed_source_indices(),
    )

    def _mesh_edit_select_whole_part() -> None:
        selection = _mesh_edit_all_vertices_in_scope()
        if not selection:
            return
        _mesh_edit_set_vertex_selection(selection)

    def _mesh_edit_invert_selection() -> None:
        all_vertices = _mesh_edit_all_vertices_in_scope()
        _mesh_edit_set_vertex_selection(
            _mesh_edit_inverted_vertex_selection_helper(
                all_vertices,
                mesh_edit_selected_vertices_by_submesh,
            )
        )

    def _mesh_edit_grow_selection() -> None:
        if _mesh_edit_state.replacement_mesh_for_mapping is None:
            return
        _mesh_edit_set_vertex_selection(
            grow_vertex_selection(_mesh_edit_state.replacement_mesh_for_mapping, mesh_edit_selected_vertices_by_submesh)
        )

    def _mesh_edit_shrink_selection() -> None:
        if _mesh_edit_state.replacement_mesh_for_mapping is None:
            return
        _mesh_edit_set_vertex_selection(
            shrink_vertex_selection(_mesh_edit_state.replacement_mesh_for_mapping, mesh_edit_selected_vertices_by_submesh)
        )

    def _mesh_edit_smooth_selection() -> None:
        if _mesh_edit_state.replacement_mesh_for_mapping is None:
            return
        _mesh_edit_set_vertex_selection(
            smooth_vertex_selection(_mesh_edit_state.replacement_mesh_for_mapping, mesh_edit_selected_vertices_by_submesh)
        )

    def _mesh_edit_selection_changed(payload: object) -> None:
        mesh_edit_selected_vertices_by_submesh.clear()
        mesh_edit_selected_faces_by_submesh.clear()
        if isinstance(payload, Mapping):
            _mesh_edit_merge_vertex_groups(mesh_edit_selected_vertices_by_submesh, _mesh_edit_vertices_from_payload(payload))
            _mesh_edit_merge_face_groups(mesh_edit_selected_faces_by_submesh, _mesh_edit_faces_from_payload(payload))
        selected_count = _mesh_edit_index_group_count_helper(mesh_edit_selected_vertices_by_submesh)
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

    def _mesh_edit_control_tab_changed(index: int) -> None:
        if control_tabs.widget(index) is not mesh_edit_tab and mesh_edit_enabled_checkbox.isChecked():
            mesh_edit_enabled_checkbox.blockSignals(True)
            mesh_edit_enabled_checkbox.setChecked(False)
            mesh_edit_enabled_checkbox.blockSignals(False)
            _refresh_mesh_edit_controls()
            _mesh_edit_apply_preview_mode_transition("left_mesh_edit_tab")
        elif control_tabs.widget(index) is mesh_edit_tab:
            _refresh_mesh_edit_controls()
            _mesh_edit_apply_preview_mode_transition("entered_mesh_edit_tab")
        _apply_alignment_dialog_responsive_layout(force_sizes=True)

    def _mesh_edit_enabled_toggled(_checked: bool = False) -> None:
        _refresh_mesh_edit_controls()
        _mesh_edit_apply_preview_mode_transition("mesh_edit_toggle")

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
        _mesh_edit_all_vertices_in_scope=_mesh_edit_all_vertices_in_scope,
        _mesh_edit_allowed_source_indices=_mesh_edit_allowed_source_indices,
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
        _mesh_edit_preview_to_source_point=_mesh_edit_preview_to_source_point,
        _mesh_edit_preview_to_source_vector=_mesh_edit_preview_to_source_vector,
        _mesh_edit_push_undo_snapshot=_mesh_edit_push_undo_snapshot,
        _mesh_edit_record_snapshot=_mesh_edit_record_snapshot,
        _mesh_edit_redo=_mesh_edit_redo,
        _mesh_edit_replace_live_triangles=_mesh_edit_replace_live_triangles,
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
