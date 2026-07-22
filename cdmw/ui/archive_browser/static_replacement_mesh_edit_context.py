"""Shared closure state for static-replacement mesh editing."""

from __future__ import annotations

from functools import wraps
from types import SimpleNamespace


_CONTEXT_NAMES = (
    'Dict', 'Iterable', 'List', 'Mapping', 'MeshMorphSliderDelta', 'StaticSourcePartAdjustment',
    'Optional', 'ParsedMesh', 'QDoubleSpinBox', 'QFileDialog', 'QFrame',
    'QGridLayout', 'QInputDialog', 'QLabel', 'QMessageBox', 'QProgressDialog',
    'QPushButton', 'QSizePolicy', 'QSlider', 'QTimer', 'QThread',
    'QWidget', 'Qt', 'Sequence', '_alignment_d3d11_preview_active', '_alignment_mesh_edit_tab_active',
    'classic_mesh_edit_action_bar', 'classic_mesh_edit_toolbar', 'compact_mesh_edit_status_label', 'compact_mesh_edit_clear_button', 'compact_mesh_edit_grow_button',
    'compact_mesh_edit_shrink_button', 'compact_mesh_edit_feather_button', 'compact_mesh_edit_reset_scope_button', 'compact_selection_mode_combo', 'compact_selection_depth_combo',
    'prompt_shell_context', 'source_skeleton', '_apply_alignment_dialog_responsive_layout', '_clear_alignment_d3d11_fast_transform_state', '_commit_spinbox_text',
    '_copy_source_part_with_adjustment', '_current_dialog_mappings_for_preview', '_current_source_part_adjustments', '_current_static_alignment_transform', '_current_texture_uv_transforms',
    '_ensure_source_part_adjustment', '_is_default_source_part_adjustment', '_is_marker_source', '_make_double_spin_helper', '_mapped_source_indices',
    '_mesh_edit_all_live_vertices_for_sources_helper', '_mesh_edit_all_vertices_by_source_helper', '_mesh_edit_allowed_source_indices_helper', '_mesh_edit_apply_preview_mode_transition', '_mesh_edit_blocked_title_helper',
    '_mesh_edit_can_edit_scope_helper', '_mesh_edit_control_status_text_helper', '_mesh_edit_delete_faces_text_helper', '_mesh_edit_deleted_faces_status_helper', '_mesh_edit_deleted_selection_status_helper',
    '_mesh_edit_dialog_title_helper', '_mesh_edit_distance_or_zero_helper', '_mesh_edit_editing_active_helper', '_mesh_edit_editing_requested_helper', '_mesh_edit_enabled_snapshot_items_helper',
    '_mesh_edit_full_reset_source_indices_helper', '_mesh_edit_has_index_groups_helper', '_mesh_edit_has_inverse_transform_context_helper', '_mesh_edit_index_group_count_helper', '_mesh_edit_index_groups_as_sets_helper',
    '_mesh_edit_live_delete_status_helper', '_mesh_edit_live_vertex_update_groups_helper', '_mesh_edit_native_live_vertex_update_groups_helper', '_mesh_edit_mapping_keys_helper', '_mesh_edit_merge_index_groups_helper',
    '_mesh_edit_mesh_totals_helper', '_mesh_edit_optional_sorted_indices_helper', '_mesh_edit_part_enabled_snapshot_helper', '_mesh_edit_payload_choice_helper', '_mesh_edit_payload_edge_groups_helper',
    '_mesh_edit_payload_float_helper', '_mesh_edit_payload_has_drag_motion_helper', '_mesh_edit_payload_int_helper', '_mesh_edit_payload_native_vertex_groups_helper', '_mesh_edit_payload_selected_indices_helper',
    '_mesh_edit_payload_vector3_helper', '_mesh_edit_payload_vertex_groups_helper', '_mesh_edit_cleanup_native_vertex_group_descriptors_helper', '_mesh_edit_pending_live_normals_initial_state_helper', '_mesh_edit_pruned_index_groups_helper',
    '_mesh_edit_queue_live_vertex_updates_helper', '_mesh_edit_requested_source_indices_helper', '_mesh_edit_reset_available_helper', '_mesh_edit_reset_scope_source_indices_helper', '_mesh_edit_scope_mode_helper',
    '_mesh_edit_selection_depth_mode_helper', '_mesh_edit_selection_mode_helper', '_mesh_edit_selection_region_default_amount_helper', '_mesh_edit_selection_status_text_helper', '_mesh_edit_should_restore_deleted_output_helper',
    '_mesh_edit_refined_selection_status_helper', '_mesh_edit_split_selection_status_helper', '_mesh_edit_split_text_helper', '_mesh_edit_sorted_index_groups_helper', '_mesh_edit_source_index_helper',
    '_mesh_edit_source_index_is_editable_helper', '_mesh_edit_source_indices_helper', '_mesh_edit_source_to_preview_point_helper', '_mesh_edit_stroke_id_helper', '_mesh_edit_subdivide_text_helper',
    '_mesh_edit_subdivided_selection_status_helper', '_mesh_edit_target_mode_for_tool_helper', '_mesh_edit_tool_context_helper', '_mesh_edit_tool_helper', '_mesh_edit_topology_changed_status_helper',
    '_mesh_edit_topology_source_indices_helper', '_mesh_edit_triangle_replace_groups_helper', '_mesh_edit_vector3_or_zero_helper', '_morph_slider_active_deltas_helper',
    '_morph_slider_amount_prompt_text_helper', '_morph_slider_bake_state_helper', '_morph_slider_capture_post_edit_deltas_helper',
    '_morph_slider_control_state_helper', '_morph_slider_create_action_text_helper', '_morph_slider_create_route_state_helper', '_morph_slider_created_status_text_helper', '_morph_slider_default_name_text_helper',
    '_morph_slider_expected_vertex_counts_helper', '_morph_slider_feather_prompt_text_helper', '_morph_slider_has_loaded_deltas_helper', '_morph_slider_has_nonzero_values_helper',
    '_morph_slider_name_prompt_text_helper', '_morph_slider_post_edit_deltas_need_reset_helper', '_morph_slider_reload_state_helper',
    '_morph_slider_reset_state_helper', '_morph_slider_row_state_helper', '_morph_slider_row_sync_states_helper', '_morph_slider_status_text_helper', '_morph_slider_supported_helper',
    '_morph_slider_topology_changed_reason_text_helper', '_morph_slider_unique_slider_id_helper', '_morph_slider_value_commit_state_helper', '_morph_slider_value_or_default_helper',
    '_morph_slider_zero_post_edit_deltas_for_sources_helper', '_morph_slider_zero_post_edit_deltas_helper', '_pop_geometry_undo_snapshot', '_push_geometry_undo_snapshot', '_push_geometry_sparse_mesh_edit_snapshot',
    '_capture_geometry_history_state', '_restore_geometry_history_state',
    '_rebuild_source_part_widgets', '_alignment_d3d11_invalidate_package_cache', '_mark_alignment_d3d11_rebuild_reason', '_queue_latest_alignment_d3d11_rebuild_for_stale_reload', '_queue_static_preview_rebuild',
    '_queue_texture_preview_refresh', '_record_runtime_event', '_refresh_source_assignment_columns', '_refresh_source_tree_selection_state', '_safe_refresh_static_dialog_preview',
    '_delete_selected_source_parts', '_source_display_name', '_source_index_is_enabled_renderable', '_transformed_replacement_sources', '_current_complete_swap_material_profile_token',
    'alignment_d3d11_preview_host', 'alignment_d3d11_state', 'appended_source_indices', 'mesh_editor_static_replacement_session_state', 'apply_morph_slider_values',
    'assert_mesh_topology_unchanged', 'control_tabs', 'controls_panel', 'copy', 'create_region_volume_slider_profile', 'dialog',
    'entry', 'load_morph_slider_delta', 'load_morph_slider_profiles',
    'mesh_edit_action_control_text', 'mesh_edit_active_stroke', 'mesh_edit_button_row', 'mesh_edit_clear_selection_button', 'mesh_edit_delete_faces_button',
    'mesh_edit_delete_mode_combo', 'mesh_edit_enabled_checkbox', 'mesh_edit_falloff_combo', 'mesh_edit_field_rows', 'mesh_edit_full_reset_button',
    'mesh_edit_group', 'mesh_edit_grow_selection_button', 'mesh_edit_invert_selection_button', 'mesh_edit_iterations_spin', 'mesh_edit_layout',
    'mesh_edit_mirror_checkbox', 'mesh_edit_option_widget', 'mesh_edit_part_combo', 'mesh_edit_radius_spin', 'mesh_edit_redo_adjustment_stack',
    'mesh_edit_redo_button', 'mesh_edit_redo_stack', 'mesh_edit_remove_mode_label', 'mesh_edit_refine_smooth_selection_button', 'mesh_edit_reset_part_button',
    'mesh_edit_revision', 'mesh_edit_scope_combo', 'mesh_edit_select_part_button', 'mesh_edit_selected_faces_by_submesh', 'mesh_edit_selected_source_indices',
    'mesh_edit_selected_vertices_by_submesh', 'mesh_edit_selection_actions_widget', 'mesh_edit_selection_depth_combo', 'mesh_edit_selection_mode_combo', 'mesh_edit_show_vertices_checkbox',
    'mesh_edit_shrink_selection_button', 'mesh_edit_smooth_selection_button', 'mesh_edit_split_selection_button', 'mesh_edit_status_label', 'mesh_edit_strength_spin',
    'mesh_edit_subdivide_selection_button', 'mesh_edit_supported', 'mesh_edit_tab', 'mesh_edit_tool_buttons', 'mesh_edit_tool_combo',
    'mesh_edit_tool_palette', 'mesh_edit_undo_adjustment_stack', 'mesh_edit_undo_button', 'mesh_edit_undo_stack', 'mesh_topology_signature',
    'modify_original_clone_mode', 'morph_slider_bake_button', 'morph_slider_change_active', 'morph_slider_create_button',
    'morph_slider_deltas', 'morph_slider_group', 'morph_slider_manage_button', 'morph_slider_post_edit_deltas',
    'morph_slider_profile_root', 'morph_slider_profiles', 'morph_slider_reload_action', 'morph_slider_reset_button', 'morph_slider_rows',
    'morph_slider_rows_layout', 'morph_slider_rows_widget', 'morph_slider_status_label', 'morph_slider_topology_blocked', 'morph_slider_update_guard',
    'morph_slider_values', 'original_mesh_for_mapping', 'original_reference_preview_model', 'overlay_dialog_preview', 'parsed_mesh_to_preview_model',
    'replacement_only_preview', 'selected_source_part', 'self', 'source_items_by_index', 'source_geometry_revision',
    'source_part_adjustments', 'source_tree', 'source_tree_item_update_guard', 'static_dialog_preview', 'static_preview_geometry_cache',
    'static_preview_prepared_cache', 'validate_morph_target',
)


def _bind_state_callback(function: object, state: SimpleNamespace) -> object:
    @wraps(function)
    def callback(*args: object, **kwargs: object) -> object:
        return function(state, *args, **kwargs)

    return callback


def _context_or_prompt(state: SimpleNamespace, name: str) -> object:
    value = state.context.get(name)
    if value is not None:
        return value
    if isinstance(state.prompt_shell_context, dict):
        return state.prompt_shell_context.get(name)
    return None


def _mesh_edit_tab_active(state: SimpleNamespace) -> bool:
    checkbox = state._context_or_prompt("mesh_edit_enabled_checkbox")
    is_checked = getattr(checkbox, "isChecked", None)
    if callable(is_checked):
        return bool(is_checked())
    callback = state._alignment_mesh_edit_tab_active
    if not callable(callback):
        callback = state.context.get("_alignment_mesh_edit_tab_active")
    if not callable(callback) and isinstance(state.prompt_shell_context, dict):
        callback = state.prompt_shell_context.get("_alignment_mesh_edit_tab_active")
    return bool(callback()) if callable(callback) else False


def _alignment_d3d11_source_indices_for_editor_id(
    state: SimpleNamespace, editor_id: int
) -> tuple[int, ...]:
    callback = state._alignment_d3d11_source_indices_for_editor_id_callback
    if not callable(callback):
        callback = state.context.get("_alignment_d3d11_source_indices_for_editor_id")
    if not callable(callback) and isinstance(state.prompt_shell_context, dict):
        callback = state.prompt_shell_context.get("_alignment_d3d11_source_indices_for_editor_id")
    if not callable(callback):
        return ()
    return tuple(int(index) for index in callback(editor_id) or () if int(index) >= 0)


def _mesh_edit_surface_tab_active(
    state: SimpleNamespace, index: int | None = None
) -> bool:
    try:
        tab_index = state.control_tabs.currentIndex() if index is None else int(index)
        if state.control_tabs.widget(tab_index) is state.mesh_edit_tab:
            return True
        return state.control_tabs.tabText(tab_index).strip().lower() in {
            "mesh editing",
            "classic mesh editing",
            "merged mesh editing",
        }
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False


def _install_state_callbacks(state: SimpleNamespace) -> None:
    state._context_or_prompt = _bind_state_callback(_context_or_prompt, state)
    state._mesh_edit_tab_active = _bind_state_callback(_mesh_edit_tab_active, state)
    state._alignment_d3d11_source_indices_for_editor_id = _bind_state_callback(
        _alignment_d3d11_source_indices_for_editor_id, state
    )
    state._d3d11_source_indices_for_editor_id = (
        state._alignment_d3d11_source_indices_for_editor_id
    )
    state._mesh_edit_surface_tab_active = _bind_state_callback(
        _mesh_edit_surface_tab_active, state
    )


def _normalize_state(state: SimpleNamespace, context: dict[str, object]) -> None:
    if not callable(state._mesh_edit_has_inverse_transform_context_helper):
        state._mesh_edit_has_inverse_transform_context_helper = (
            state._default_mesh_edit_has_inverse_transform_context
        )
    if not isinstance(state.alignment_d3d11_state, dict):
        state.alignment_d3d11_state = {}
    if not isinstance(state.mesh_editor_static_replacement_session_state, dict):
        state.mesh_editor_static_replacement_session_state = {}
    if not isinstance(state.mesh_edit_selected_source_indices, set):
        state.mesh_edit_selected_source_indices = set()
    if state.source_geometry_revision is None:
        state.source_geometry_revision = {}
    state.source_affine_for_transformed_preview = state._context_or_prompt(
        "source_affine_for_transformed_preview"
    )
    if not callable(state.source_affine_for_transformed_preview):
        state.source_affine_for_transformed_preview = (
            state._default_source_affine_for_transformed_preview
        )
    state.source_normal_transform_for_transformed_preview = state._context_or_prompt(
        "source_normal_transform_for_transformed_preview"
    )
    if not callable(state.source_normal_transform_for_transformed_preview):
        state.source_normal_transform_for_transformed_preview = (
            state._default_source_normal_transform_for_transformed_preview
        )
    state._mesh_edit_state = state._MeshEditDialogState(context)


def _configure_layout(state: SimpleNamespace) -> None:
    state.mesh_edit_button_row.addStretch(1)
    state.mesh_edit_layout.addLayout(state.mesh_edit_button_row)
    state.mesh_edit_layout.addWidget(state.mesh_edit_reset_part_button)
    state.mesh_edit_layout.addWidget(state.mesh_edit_full_reset_button)
    state.mesh_edit_layout.addWidget(state.mesh_edit_status_label)


def _install_selection_accessors(state: SimpleNamespace) -> None:
    state._mesh_edit_scope_mode = lambda: state._mesh_edit_scope_mode_helper(
        state.mesh_edit_scope_combo.currentData()
    )
    state._mesh_edit_current_tool = lambda: state._mesh_edit_tool_helper(
        state.mesh_edit_tool_combo.currentData()
    )
    state._mesh_edit_selection_mode = lambda: state._mesh_edit_selection_mode_helper(
        state.mesh_edit_selection_mode_combo.currentData()
    )
    state._mesh_edit_selection_depth_mode = lambda: state._mesh_edit_selection_depth_mode_helper(
        state.mesh_edit_selection_depth_combo.currentData()
    )
    state._mesh_edit_selected_source_index = lambda: state._mesh_edit_source_index_helper(
        state.selected_source_part.get("index", -1)
    )
    state._mesh_edit_selected_scope_source_index = lambda: state._mesh_edit_source_index_helper(
        state.mesh_edit_part_combo.currentData(),
        fallback=state._mesh_edit_selected_source_index(),
    )
    state._mesh_edit_base_source_index_is_editable = lambda source_index: (
        state._mesh_edit_source_index_is_editable_helper(
            state._mesh_edit_state.replacement_mesh_base_for_mapping
            or state._mesh_edit_state.replacement_mesh_for_mapping,
            source_index,
            is_marker_source=state._is_marker_source,
        )
    )

    def source_index_is_editable(source_index, *, require_enabled=True):
        return state._mesh_edit_source_index_is_editable_helper(
            state._mesh_edit_state.replacement_mesh_for_mapping,
            source_index,
            is_marker_source=state._is_marker_source,
            is_enabled_renderable=(
                lambda index: state._source_index_is_enabled_renderable(index)
            )
            if require_enabled
            else None,
        )

    state._mesh_edit_source_index_is_editable = source_index_is_editable
    state._mesh_edit_allowed_source_indices = lambda *, require_enabled=True: (
        state._mesh_edit_allowed_source_indices_helper(
            state._mesh_edit_state.replacement_mesh_for_mapping,
            scope_mode=state._mesh_edit_scope_mode(),
            selected_scope_source_index=state._mesh_edit_selected_scope_source_index(),
            is_source_index_editable=lambda index: state._mesh_edit_source_index_is_editable(
                index, require_enabled=require_enabled
            ),
        )
    )
    state._mesh_edit_preview_source_indices = lambda *, require_enabled=True: (
        state._mesh_edit_source_indices_helper(
            state._mesh_edit_state.replacement_mesh_for_mapping,
            lambda index: state._mesh_edit_source_index_is_editable(
                index, require_enabled=require_enabled
            ),
        )
    )


def _install_morph_accessors(state: SimpleNamespace) -> None:
    state._morph_slider_supported = lambda: state._morph_slider_supported_helper(
        modify_original_clone_mode=state.modify_original_clone_mode,
        has_base_mesh=state._mesh_edit_state.replacement_mesh_base_for_mapping is not None,
        has_working_mesh=state._mesh_edit_state.replacement_mesh_for_mapping is not None,
    )
    state._morph_slider_has_loaded_deltas = lambda: (
        state._morph_slider_has_loaded_deltas_helper(state.morph_slider_deltas)
    )
    state._morph_slider_has_nonzero_values = lambda: (
        state._morph_slider_has_nonzero_values_helper(state.morph_slider_values)
    )
    state._morph_slider_zero_post_edit_deltas = lambda: (
        state._morph_slider_zero_post_edit_deltas_helper(
            state._mesh_edit_state.replacement_mesh_base_for_mapping
        )
    )


def _install_payload_accessors(state: SimpleNamespace) -> None:
    state._mesh_edit_part_enabled_snapshot = lambda: (
        state._mesh_edit_part_enabled_snapshot_helper(
            state._mesh_edit_state.replacement_mesh_for_mapping,
            state.source_part_adjustments,
        )
    )
    state._mesh_edit_part_state_snapshot = lambda: (
        state._capture_geometry_history_state('Mesh edit part state', metadata_only=True)
        if callable(state._capture_geometry_history_state)
        else state._mesh_edit_part_enabled_snapshot()
    )
    state._mesh_edit_stroke_id = lambda payload: state._mesh_edit_stroke_id_helper(payload)
    state._mesh_edit_all_live_vertices_for_sources = lambda source_indices: (
        state._mesh_edit_all_live_vertices_for_sources_helper(
            state._mesh_edit_state.replacement_mesh_for_mapping, source_indices
        )
    )
    state._mesh_edit_payload_has_drag_motion = lambda payload: (
        state._mesh_edit_payload_has_drag_motion_helper(payload)
    )
    state._mesh_edit_vertices_from_payload = lambda payload: (
        state._mesh_edit_payload_selected_indices_helper(
            payload,
            state._mesh_edit_state.replacement_mesh_for_mapping,
            allowed_source_indices=state._mesh_edit_allowed_source_indices(),
            source_indices_for_editor_id=state._d3d11_source_indices_for_editor_id,
            payload_index_key="source_vertex_indices",
            mesh_collection_attr="vertices",
        )
    )
    state._mesh_edit_faces_from_payload = lambda payload: (
        state._mesh_edit_payload_selected_indices_helper(
            payload,
            state._mesh_edit_state.replacement_mesh_for_mapping,
            allowed_source_indices=state._mesh_edit_allowed_source_indices(),
            source_indices_for_editor_id=state._d3d11_source_indices_for_editor_id,
            payload_index_key="source_face_indices",
            mesh_collection_attr="faces",
        )
    )
    state._mesh_edit_merge_vertex_groups = lambda target, source: (
        state._mesh_edit_merge_index_groups_helper(target, source)
    )
    state._mesh_edit_merge_face_groups = lambda target, source: (
        state._mesh_edit_merge_index_groups_helper(target, source)
    )


def _initialize_runtime_state(state: SimpleNamespace) -> None:
    state.mesh_edit_preview_model_dirty = {"value": False}
    state.mesh_edit_native_result_submesh_counts = {"value": ()}
    state.mesh_edit_selected_edges_by_submesh = {}
    state.mesh_editor_action_bar_selection_mode = {"value": "vertex"}
    state.mesh_editor_action_bar_active_tool_key = {"value": "brush_grab"}
    state.mesh_edit_topology_worker_state = {
        "request_id": 0,
        "thread": None,
        "worker": None,
        "progress": None,
        "start_revision": 0,
    }
    state.mesh_edit_selection_worker_state = {
        "request_id": 0,
        "thread": None,
        "worker": None,
        "start_revision": 0,
    }
    state.mesh_edit_live_update_timer = state.QTimer(state.dialog)
    state.mesh_edit_live_update_timer.setSingleShot(True)
    state.mesh_edit_live_update_timer.setInterval(16)
    state.mesh_edit_pending_live_vertices = {}
    state.mesh_edit_pending_live_normals = (
        state._mesh_edit_pending_live_normals_initial_state_helper()
    )
    state._NATIVE_STROKE_HISTORY_ATTR = "cdmw_native_mesh_history_vertex_delta"
    state.mesh_edit_surface_tab_state = {"active": state._mesh_edit_surface_tab_active()}


def create_mesh_edit_state(
    context: dict[str, object], module_globals: dict[str, object]
) -> SimpleNamespace:
    values = dict(module_globals)
    values.update({name: context.get(name) for name in _CONTEXT_NAMES})
    values["context"] = context
    values["_alignment_d3d11_source_indices_for_editor_id_callback"] = context.get(
        "_alignment_d3d11_source_indices_for_editor_id"
    )
    state = SimpleNamespace(**values)
    _install_state_callbacks(state)
    _normalize_state(state, context)
    _configure_layout(state)
    _install_selection_accessors(state)
    _install_morph_accessors(state)
    _install_payload_accessors(state)
    _initialize_runtime_state(state)
    return state
