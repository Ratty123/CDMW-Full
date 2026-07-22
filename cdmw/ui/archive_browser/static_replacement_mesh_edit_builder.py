"""Composition and signal wiring for static-replacement mesh-edit callbacks."""

from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_mesh_edit_context import create_mesh_edit_state
from cdmw.ui.archive_browser.static_replacement_mesh_edit_session import create_session_callbacks
from cdmw.ui.archive_browser.static_replacement_mesh_edit_morph import create_morph_callbacks
from cdmw.ui.archive_browser.static_replacement_mesh_edit_workers import create_workers_callbacks
from cdmw.ui.archive_browser.static_replacement_mesh_edit_actions import create_actions_callbacks
from cdmw.ui.archive_browser.static_replacement_mesh_edit_action_bar import create_action_bar_callbacks
from cdmw.ui.archive_browser.static_replacement_mesh_edit_controls_history import create_controls_history_callbacks
from cdmw.ui.archive_browser.static_replacement_mesh_edit_metrics import create_metrics_callbacks
from cdmw.ui.archive_browser.static_replacement_mesh_edit_live_preview import create_live_preview_callbacks
from cdmw.ui.archive_browser.static_replacement_mesh_edit_stroke_history import create_stroke_history_callbacks
from cdmw.ui.archive_browser.static_replacement_mesh_edit_payload_helpers import create_payload_helpers_callbacks
from cdmw.ui.archive_browser.static_replacement_mesh_edit_payload_apply import create_payload_apply_callbacks
from cdmw.ui.archive_browser.static_replacement_mesh_edit_stroke_finish import create_stroke_finish_callbacks
from cdmw.ui.archive_browser.static_replacement_mesh_edit_topology import create_topology_callbacks
from cdmw.ui.archive_browser.static_replacement_mesh_edit_selection import create_selection_callbacks


_CALLBACK_FACTORIES = (
    create_session_callbacks,
    create_morph_callbacks,
    create_workers_callbacks,
    create_actions_callbacks,
    create_action_bar_callbacks,
    create_controls_history_callbacks,
    create_metrics_callbacks,
    create_live_preview_callbacks,
    create_stroke_history_callbacks,
    create_payload_helpers_callbacks,
    create_payload_apply_callbacks,
    create_stroke_finish_callbacks,
    create_topology_callbacks,
    create_selection_callbacks,
)

PUBLIC_CALLBACK_NAMES = (
    '_mesh_edit_adjusted_sources_for_live_preview',
    '_mesh_edit_all_live_vertices_for_sources',
    '_mesh_edit_allowed_source_indices',
    '_mesh_editor_action_bar_action_requested',
    '_mesh_editor_embedded_apply_native_update',
    '_mesh_editor_embedded_controller',
    '_mesh_editor_embedded_placement_state',
    '_mesh_editor_embedded_dotnet_failed',
    '_mesh_editor_embedded_dotnet_ready',
    '_mesh_editor_embedded_finalize_dotnet_import',
    '_mesh_editor_embedded_run_part_action',
    '_mesh_editor_embedded_set_skeleton_bone',
    '_mesh_edit_apply_preview_payload',
    '_mesh_edit_base_source_index_is_editable',
    '_mesh_edit_begin_stroke',
    '_mesh_edit_can_edit_scope',
    '_mesh_edit_cancel_stroke',
    '_mesh_edit_clear_topology_selection',
    '_mesh_edit_clear_vertex_selection',
    '_mesh_edit_commit_working_mesh',
    '_mesh_edit_control_tab_changed',
    '_mesh_edit_current_tool',
    '_mesh_edit_delete_selected_faces',
    '_mesh_edit_disable_emptied_parts',
    '_mesh_edit_enabled_toggled',
    '_mesh_edit_faces_from_payload',
    '_mesh_edit_finish_stroke',
    '_mesh_edit_full_reset_mesh',
    '_mesh_edit_grow_selection',
    '_mesh_edit_invert_selection',
    '_mesh_edit_live_vertex_update_groups',
    '_mesh_edit_merge_face_groups',
    '_mesh_edit_merge_vertex_groups',
    '_mesh_edit_part_enabled_snapshot',
    '_mesh_edit_payload_has_drag_motion',
    '_mesh_edit_pop_undo_snapshot',
    '_mesh_edit_preview_delta_to_source_delta',
    '_mesh_edit_preview_distance_to_source_distance',
    '_mesh_edit_preview_point_to_source_point',
    '_mesh_edit_preview_source_indices',
    '_mesh_edit_push_undo_snapshot',
    '_mesh_edit_record_snapshot',
    '_mesh_edit_redo',
    '_mesh_edit_replace_live_triangles',
    '_mesh_edit_replace_live_triangles_or_queue_rebuild',
    '_mesh_edit_replace_working_mesh',
    '_mesh_edit_reset_scope',
    '_mesh_edit_restore_enabled_snapshot',
    '_mesh_edit_restore_snapshot',
    '_mesh_edit_scope_mode',
    '_mesh_edit_select_whole_part',
    '_mesh_edit_selected_scope_source_index',
    '_mesh_edit_selected_source_index',
    '_mesh_edit_selection_changed',
    '_mesh_edit_selection_depth_mode',
    '_mesh_edit_selection_mode',
    '_mesh_edit_set_vertex_selection',
    '_mesh_edit_shrink_selection',
    '_mesh_edit_smooth_selection',
    '_mesh_edit_source_index_is_editable',
    '_mesh_edit_source_to_preview_point',
    '_mesh_edit_stroke_id',
    '_mesh_edit_split_selection_to_part',
    '_mesh_edit_subdivide_selection',
    '_mesh_edit_submesh_for_live_preview',
    '_mesh_edit_target_mode_for_tool',
    '_mesh_edit_transformed_sources_for_live_preview',
    '_mesh_edit_triangle_replace_groups',
    '_mesh_edit_undo',
    '_mesh_edit_update_live_preview',
    '_mesh_edit_update_mesh_totals',
    '_mesh_edit_vertices_from_payload',
    '_morph_slider_active_deltas',
    '_morph_slider_add_row',
    '_morph_slider_apply_to_working_mesh',
    '_morph_slider_bake',
    '_morph_slider_begin_change',
    '_morph_slider_capture_post_edit_deltas',
    '_morph_slider_clear_rows',
    '_morph_slider_create_from_selection',
    '_morph_slider_default_region_amount',
    '_morph_slider_end_change',
    '_morph_slider_ensure_post_edit_deltas',
    '_morph_slider_has_loaded_deltas',
    '_morph_slider_has_nonzero_values',
    '_morph_slider_mark_topology_changed',
    '_morph_slider_rebuild_rows',
    '_morph_slider_refresh_controls',
    '_morph_slider_refresh_topology_block_state',
    '_morph_slider_reload_profiles',
    '_morph_slider_reset_all',
    '_morph_slider_set_value',
    '_morph_slider_slider_only_mesh',
    '_morph_slider_supported',
    '_morph_slider_sync_row_widgets',
    '_morph_slider_zero_post_edit_deltas',
    '_morph_slider_zero_post_edit_deltas_for_sources',
    '_refresh_mesh_edit_controls',
    '_refresh_mesh_edit_part_combo',
    '_sync_mesh_edit_preview_settings',
)


def _connect_callbacks(state: SimpleNamespace, callbacks: SimpleNamespace) -> None:
    state.mesh_edit_live_update_timer.timeout.connect(callbacks._flush_mesh_edit_live_vertex_updates)
    if state.dialog is not None:
        setattr(state.dialog, "_mesh_editor_embedded_dotnet_ready", callbacks._mesh_editor_embedded_dotnet_ready)
        setattr(state.dialog, "_mesh_editor_embedded_dotnet_failed", callbacks._mesh_editor_embedded_dotnet_failed)

    state.mesh_edit_enabled_checkbox.toggled.connect(callbacks._mesh_edit_enabled_toggled)
    for widget in (state.mesh_edit_show_vertices_checkbox, state.mesh_edit_mirror_checkbox):
        widget.toggled.connect(lambda _checked=False: callbacks._refresh_mesh_edit_controls())
    for signal in (
        state.mesh_edit_scope_combo.currentIndexChanged,
        state.mesh_edit_part_combo.currentIndexChanged,
        state.mesh_edit_tool_combo.currentIndexChanged,
        state.mesh_edit_delete_mode_combo.currentIndexChanged,
        state.mesh_edit_falloff_combo.currentIndexChanged,
        state.mesh_edit_iterations_spin.valueChanged,
        state.mesh_edit_selection_mode_combo.currentIndexChanged,
        state.mesh_edit_selection_depth_combo.currentIndexChanged,
        state.mesh_edit_radius_spin.valueChanged,
        state.mesh_edit_strength_spin.valueChanged,
    ):
        signal.connect(lambda _value: callbacks._refresh_mesh_edit_controls())
    state.mesh_edit_radius_spin.editingFinished.connect(
        lambda: (state._commit_spinbox_text(state.mesh_edit_radius_spin), callbacks._refresh_mesh_edit_controls())
    )
    state.mesh_edit_strength_spin.editingFinished.connect(
        lambda: (state._commit_spinbox_text(state.mesh_edit_strength_spin), callbacks._refresh_mesh_edit_controls())
    )
    state.mesh_edit_clear_selection_button.clicked.connect(lambda _checked=False: callbacks._mesh_edit_clear_vertex_selection())
    state.mesh_edit_select_part_button.clicked.connect(lambda _checked=False: callbacks._mesh_edit_select_whole_part())
    state.mesh_edit_invert_selection_button.clicked.connect(lambda _checked=False: callbacks._mesh_edit_invert_selection())
    state.mesh_edit_grow_selection_button.clicked.connect(lambda _checked=False: callbacks._mesh_edit_grow_selection())
    state.mesh_edit_shrink_selection_button.clicked.connect(lambda _checked=False: callbacks._mesh_edit_shrink_selection())
    state.mesh_edit_smooth_selection_button.clicked.connect(lambda _checked=False: callbacks._mesh_edit_smooth_selection())
    state.mesh_edit_subdivide_selection_button.clicked.connect(lambda _checked=False: callbacks._mesh_edit_subdivide_selection())
    state.mesh_edit_refine_smooth_selection_button.clicked.connect(
        lambda _checked=False: callbacks._mesh_edit_subdivide_selection(refine_smooth=True)
    )
    state.mesh_edit_split_selection_button.clicked.connect(lambda _checked=False: callbacks._mesh_edit_split_selection_to_part())
    state.mesh_edit_delete_faces_button.clicked.connect(lambda _checked=False: callbacks._mesh_edit_delete_selected_faces())
    state.mesh_edit_undo_button.clicked.connect(lambda _checked=False: callbacks._mesh_edit_undo())
    state.mesh_edit_redo_button.clicked.connect(lambda _checked=False: callbacks._mesh_edit_redo())
    state.mesh_edit_reset_part_button.clicked.connect(lambda _checked=False: callbacks._mesh_edit_reset_scope())
    state.mesh_edit_full_reset_button.clicked.connect(lambda _checked=False: callbacks._mesh_edit_full_reset_mesh())
    state.morph_slider_create_button.clicked.connect(lambda _checked=False: callbacks._morph_slider_create_from_selection())
    state.morph_slider_reload_action.triggered.connect(lambda _checked=False: callbacks._morph_slider_reload_profiles(preserve_values=True))
    state.morph_slider_reset_button.clicked.connect(lambda _checked=False: callbacks._morph_slider_reset_all())
    state.morph_slider_bake_button.clicked.connect(lambda _checked=False: callbacks._morph_slider_bake())


def create_alignment_mesh_edit_callbacks(
    context: dict[str, object], module_globals: dict[str, object]
) -> SimpleNamespace:
    state = create_mesh_edit_state(context, module_globals)
    callbacks = SimpleNamespace()
    for name in PUBLIC_CALLBACK_NAMES:
        if hasattr(state, name):
            setattr(callbacks, name, getattr(state, name))
    for factory in _CALLBACK_FACTORIES:
        vars(callbacks).update(vars(factory(state, callbacks)))
    _connect_callbacks(state, callbacks)
    return SimpleNamespace(**{name: getattr(callbacks, name) for name in PUBLIC_CALLBACK_NAMES})
