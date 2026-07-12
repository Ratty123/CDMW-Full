"""Replacement mesh/routing setup owner for static replacement prompt."""

from __future__ import annotations

import traceback
from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_dialog_prompt_deps import (
    install_static_replacement_prompt_dependencies,
)
install_static_replacement_prompt_dependencies(globals())


def create_static_replacement_prompt_setup(context: dict[str, object]) -> SimpleNamespace:
    _alignment_startup_step = context['_alignment_startup_step']
    _alignment_texture_lookup_indexes = context['_alignment_texture_lookup_indexes']
    _capture_static_preview_baked_transform_state = context['_capture_static_preview_baked_transform_state']
    _mapping_table_action_control_text_helper = context['_mapping_table_action_control_text_helper']
    _record_runtime_event = context['_record_runtime_event']
    alignment_preview_render_control_text = context['alignment_preview_render_control_text']
    alignment_startup_text = context['alignment_startup_text']
    defer_original_texture_preview = context['defer_original_texture_preview']
    dialog_title = context['dialog_title']
    entry = context['entry']
    modify_original_clone_mode = context['modify_original_clone_mode']
    obj_path = context['obj_path']
    original_dialog_preview = context['original_dialog_preview']
    original_mesh = context['original_mesh']
    parts_layout = context['parts_layout']
    preview_render_settings = context['preview_render_settings']
    prompt_preflight = context['prompt_preflight']
    prompt_shell_context = context['prompt_shell_context']
    replacement_export_allowed = context['replacement_export_allowed']
    scene_import_result = context['scene_import_result']
    self = context['self']
    setup_layout = context['setup_layout']
    setup_summary_layout = context.get('setup_summary_layout') or setup_layout
    static_dialog_preview = context['static_dialog_preview']
    supplemental_files = context.get('supplemental_files', ())
    _set_replacement_mesh_base_for_mapping = context['_set_replacement_mesh_base_for_mapping']
    _set_replacement_mesh_for_mapping = context['_set_replacement_mesh_for_mapping']
    _set_replacement_preview_model = context['_set_replacement_preview_model']
    _set_texture_sets = context['_set_texture_sets']
    texture_uv_global_transform_state = context.get('texture_uv_global_transform_state')
    alignment_setup_failed = False
    alignment_setup_error = ""
    alignment_setup_traceback = ""
    try:
        for startup_key in (
            "original_mesh",
            "material_sidecar",
            "asset_compatibility",
            "replacement_mesh",
            "preview_meshes",
            "draw_section_routing",
        ):
            _alignment_startup_step(alignment_startup_text[startup_key])
        original_mesh_for_mapping = prompt_preflight.original_mesh
        sidecar_bindings = prompt_preflight.sidecar_bindings
        sidecar_text_values = prompt_preflight.sidecar_text_values
        sidecar_texts_by_normalized_path = prompt_preflight.sidecar_texts_by_normalized_path
        sidecar_texts_by_basename = prompt_preflight.sidecar_texts_by_basename
        texture_entries_by_normalized_path_for_alignment = prompt_preflight.texture_entries_by_normalized_path
        texture_entries_by_basename_for_alignment = prompt_preflight.texture_entries_by_basename
        asset_profile = prompt_preflight.asset_profile
        replacement_export_allowed["allowed"] = bool(asset_profile.export_supported)
        replacement_export_allowed["reason"] = "\n".join(asset_profile.errors)
        self._add_replacement_asset_profile_summary(setup_summary_layout, asset_profile)
        replacement_mesh_base_for_mapping = prompt_preflight.replacement_mesh_base
        replacement_mesh_for_mapping = prompt_preflight.replacement_mesh
        placement_fit = prompt_preflight.placement_fit
        _record_runtime_event(
            "mesh_external_import_work_area_fit",
            source_bounds=prompt_preflight.source_bounds or (),
            reference_bounds=prompt_preflight.reference_bounds or (),
            translation=getattr(placement_fit, "translation", ()),
            scale=float(getattr(placement_fit, "scale", 1.0) or 1.0),
            up_axis=int(getattr(placement_fit, "up_axis", 1) or 1),
            ground_plane=float(getattr(placement_fit, "ground_plane", 0.0) or 0.0),
            notes=tuple(getattr(placement_fit, "notes", ()) or ()),
            applied=placement_fit is not None,
            modify_original_clone=modify_original_clone_mode,
            source_path=str(getattr(replacement_mesh_base_for_mapping, "path", "") or obj_path),
        )
        if prompt_preflight.sidecar_lookup_error:
            _record_runtime_event(
                "mesh_alignment_sidecar_texture_lookup_failed",
                path=getattr(entry, "path", ""),
                dialog_title=dialog_title,
                error=prompt_preflight.sidecar_lookup_error,
                modify_original_clone=modify_original_clone_mode,
            )
        original_reference_preview_model = prompt_preflight.original_preview_model
        replacement_preview_model = prompt_preflight.replacement_preview_model
        _set_replacement_mesh_base_for_mapping(replacement_mesh_base_for_mapping)
        _set_replacement_mesh_for_mapping(replacement_mesh_for_mapping)
        _set_replacement_preview_model(replacement_preview_model)

        def _get_original_reference_preview_model():
            return original_reference_preview_model

        def _set_original_reference_preview_model(value) -> None:
            nonlocal original_reference_preview_model
            original_reference_preview_model = value

        if (
            isinstance(texture_uv_global_transform_state, dict)
            and prompt_preflight.scene_flip_v
            and not bool(texture_uv_global_transform_state.get("flip_v"))
            and not bool(texture_uv_global_transform_state.get("flip_u"))
            and int(texture_uv_global_transform_state.get("rotate_degrees") or 0) == 0
        ):
            texture_uv_global_transform_state.update(
                {
                    "source_material_name": "__global__",
                    "rotate_degrees": 0,
                    "flip_u": False,
                    "flip_v": True,
                    "offset_u": 0.0,
                    "offset_v": 0.0,
                    "scale_u": 1.0,
                    "scale_v": 1.0,
                }
            )
        original_dialog_preview.set_render_settings(preview_render_settings)
        static_dialog_preview.set_render_settings(preview_render_settings)
        original_dialog_preview.set_use_textures(True)
        original_dialog_preview.set_high_quality_textures(True)
        static_dialog_preview.set_use_textures(True)
        static_dialog_preview.set_high_quality_textures(True)
        original_dialog_preview.clear_model(alignment_preview_render_control_text["original_reference_loading"])
        static_dialog_preview.clear_model(alignment_preview_render_control_text["replacement_preview_loading"])
        _capture_static_preview_baked_transform_state()
        suggested_mappings = list(prompt_preflight.suggested_mappings)
        prompt_shell_context["suggested_mappings"] = suggested_mappings
        if not prompt_preflight.routing_error:
            _record_runtime_event(
                "mesh_alignment_routing_ready",
                path=getattr(entry, "path", ""),
                dialog_title=dialog_title,
                target_submesh_count=len(getattr(original_mesh_for_mapping, "submeshes", ()) or ()),
                source_submesh_count=len(getattr(replacement_mesh_for_mapping, "submeshes", ()) or ()),
                mapping_count=len(suggested_mappings),
                elapsed_ms=prompt_preflight.routing_elapsed_ms,
                modify_original_clone=modify_original_clone_mode,
                defer_original_texture_preview=defer_original_texture_preview,
            )
        else:
            _record_runtime_event(
                "mesh_alignment_routing_failed",
                path=getattr(entry, "path", ""),
                dialog_title=dialog_title,
                error=prompt_preflight.routing_error,
                target_submesh_count=len(getattr(original_mesh_for_mapping, "submeshes", ()) or ()),
                source_submesh_count=len(getattr(replacement_mesh_for_mapping, "submeshes", ()) or ()),
                elapsed_ms=prompt_preflight.routing_elapsed_ms,
                modify_original_clone=modify_original_clone_mode,
                defer_original_texture_preview=defer_original_texture_preview,
            )
        mapping_group = QWidget()
        mapping_table_action_control_text = _mapping_table_action_control_text_helper()
        mapping_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        mapping_layout = QVBoxLayout(mapping_group)
        mapping_layout.setContentsMargins(1, 1, 1, 1)
        mapping_layout.setSpacing(2)
        mapping_hint = QLabel(mapping_table_action_control_text["routing_hint_html"])
        mapping_hint.setWordWrap(True)
        mapping_hint.setTextFormat(Qt.RichText)
        mapping_hint.setObjectName("HintLabel")
        mapping_hint.setToolTip(mapping_table_action_control_text["routing_hint_tooltip"])

        alignment_source_parts_outliner_section = create_alignment_source_parts_outliner_section({**context, **globals(), **locals(), 'selected_added_part_texture_row': (selected_added_part_texture_row := _selected_added_part_texture_row_initial_state_helper()), 'selected_texture_plan_source': (selected_texture_plan_source := _selected_texture_plan_source_initial_state_helper()), 'selected_texture_row': (selected_texture_row := _selected_texture_row_initial_state_helper()), '_queue_part_transform_preview_update': (lambda *args, **kwargs: context['_queue_part_transform_preview_update'](*args, **kwargs))})
        _add_dialog_supplemental_file = alignment_source_parts_outliner_section._add_dialog_supplemental_file
        _add_source_tree_item = alignment_source_parts_outliner_section._add_source_tree_item
        _alignment_part_clipboard_can_paste = alignment_source_parts_outliner_section._alignment_part_clipboard_can_paste
        _append_original_part_payload_as_source = alignment_source_parts_outliner_section._append_original_part_payload_as_source
        _apply_current_glow_color_to_role_overrides = alignment_source_parts_outliner_section._apply_current_glow_color_to_role_overrides
        _apply_source_role_selection = alignment_source_parts_outliner_section._apply_source_role_selection
        _clear_part_selections_when_leaving_geometry = alignment_source_parts_outliner_section._clear_part_selections_when_leaving_geometry
        _clear_source_parts_preview_rebuild_pending = alignment_source_parts_outliner_section._clear_source_parts_preview_rebuild_pending
        _clear_transform_source_indices = alignment_source_parts_outliner_section._clear_transform_source_indices
        _clear_tree_current_item = alignment_source_parts_outliner_section._clear_tree_current_item
        _copied_original_dds_badge = alignment_source_parts_outliner_section._copied_original_dds_badge
        _copied_original_texture_tooltip = alignment_source_parts_outliner_section._copied_original_texture_tooltip
        _copy_original_part_payload = alignment_source_parts_outliner_section._copy_original_part_payload
        _copy_source_part_with_adjustment = alignment_source_parts_outliner_section._copy_source_part_with_adjustment
        _d3d11_source_part_selected = alignment_source_parts_outliner_section._d3d11_source_part_selected
        _delete_selected_source_parts = alignment_source_parts_outliner_section._delete_selected_source_parts
        _finish_source_tree_population = alignment_source_parts_outliner_section._finish_source_tree_population
        _flush_source_role_overrides_for_export = alignment_source_parts_outliner_section._flush_source_role_overrides_for_export
        _load_part_glow_color_controls = alignment_source_parts_outliner_section._load_part_glow_color_controls
        _load_selected_part_controls = alignment_source_parts_outliner_section._load_selected_part_controls
        _mapping_vertex_limit_issues = alignment_source_parts_outliner_section._mapping_vertex_limit_issues
        _maybe_flatten_scene_import_parts = alignment_source_parts_outliner_section._maybe_flatten_scene_import_parts
        _maybe_reduce_high_density_scene_import = alignment_source_parts_outliner_section._maybe_reduce_high_density_scene_import
        _mirror_submesh_x = alignment_source_parts_outliner_section._mirror_submesh_x
        _normalize_appended_part_to_work_area = alignment_source_parts_outliner_section._normalize_appended_part_to_work_area
        _original_index_from_tree_item = alignment_source_parts_outliner_section._original_index_from_tree_item
        _original_part_texture_intent_rows = alignment_source_parts_outliner_section._original_part_texture_intent_rows
        _original_selection_changed = alignment_source_parts_outliner_section._original_selection_changed
        _original_target_label = alignment_source_parts_outliner_section._original_target_label
        _parse_mapping_edit = alignment_source_parts_outliner_section._parse_mapping_edit
        _part_mapped_target_indices = alignment_source_parts_outliner_section._part_mapped_target_indices
        _parts_outliner_selection_changed = alignment_source_parts_outliner_section._parts_outliner_selection_changed
        _parts_outliner_set_source_selection = alignment_source_parts_outliner_section._parts_outliner_set_source_selection
        _paste_alignment_part_clipboard_as_replacement_source = alignment_source_parts_outliner_section._paste_alignment_part_clipboard_as_replacement_source
        _physics_status_tooltip = alignment_source_parts_outliner_section._physics_status_tooltip
        _pick_selected_source_glow_color = alignment_source_parts_outliner_section._pick_selected_source_glow_color
        _prompt_assign_appended_mesh_parts = alignment_source_parts_outliner_section._prompt_assign_appended_mesh_parts
        _rebuild_source_part_widgets = alignment_source_parts_outliner_section._rebuild_source_part_widgets
        _reference_vertices_for_appended_part = alignment_source_parts_outliner_section._reference_vertices_for_appended_part
        _refresh_copied_original_texture_ui = alignment_source_parts_outliner_section._refresh_copied_original_texture_ui
        _refresh_original_reference_preview = alignment_source_parts_outliner_section._refresh_original_reference_preview
        _refresh_part_glow_color_controls_enabled = alignment_source_parts_outliner_section._refresh_part_glow_color_controls_enabled
        _refresh_parts_outliner = alignment_source_parts_outliner_section._refresh_parts_outliner
        _refresh_source_tree_selection_state = alignment_source_parts_outliner_section._refresh_source_tree_selection_state
        _refresh_ui_texture_sets_after_source_part_material_override = alignment_source_parts_outliner_section._refresh_ui_texture_sets_after_source_part_material_override
        _remap_selected_source_index = alignment_source_parts_outliner_section._remap_selected_source_index
        _remap_source_index_collection = alignment_source_parts_outliner_section._remap_source_index_collection
        _remap_source_index_dict = alignment_source_parts_outliner_section._remap_source_index_dict
        _select_source_part_from_viewport = alignment_source_parts_outliner_section._select_source_part_from_viewport
        _selected_original_index_from_tree = alignment_source_parts_outliner_section._selected_original_index_from_tree
        _selected_part_glow_rgb_from_controls = alignment_source_parts_outliner_section._selected_part_glow_rgb_from_controls
        _selected_source_index = alignment_source_parts_outliner_section._selected_source_index
        _selected_source_indices_from_tree = alignment_source_parts_outliner_section._selected_source_indices_from_tree
        _selected_target_index = alignment_source_parts_outliner_section._selected_target_index
        _set_mapping_indices = alignment_source_parts_outliner_section._set_mapping_indices
        _set_selected_source_glow_color = alignment_source_parts_outliner_section._set_selected_source_glow_color
        _set_source_parts_apply_pending = alignment_source_parts_outliner_section._set_source_parts_apply_pending
        _set_source_parts_preview_rebuild_pending = alignment_source_parts_outliner_section._set_source_parts_preview_rebuild_pending
        _set_transform_source_indices = alignment_source_parts_outliner_section._set_transform_source_indices
        _source_index_from_tree_item = alignment_source_parts_outliner_section._source_index_from_tree_item
        _source_mapping_target_indices = alignment_source_parts_outliner_section._source_mapping_target_indices
        _source_material_group_label = alignment_source_parts_outliner_section._source_material_group_label
        _source_mirror_plane_x = alignment_source_parts_outliner_section._source_mirror_plane_x
        _source_physics_status_text = alignment_source_parts_outliner_section._source_physics_status_text
        _source_selection_changed = alignment_source_parts_outliner_section._source_selection_changed
        _sync_part_slider_from_spin = alignment_source_parts_outliner_section._sync_part_slider_from_spin
        _sync_target_mapping_tree_item = alignment_source_parts_outliner_section._sync_target_mapping_tree_item
        _target_physics_status_text = alignment_source_parts_outliner_section._target_physics_status_text
        _target_selection_changed = alignment_source_parts_outliner_section._target_selection_changed
        _target_texture_status_details = alignment_source_parts_outliner_section._target_texture_status_details
        _target_texture_status_text = alignment_source_parts_outliner_section._target_texture_status_text
        _texture_set_for_source_index = alignment_source_parts_outliner_section._texture_set_for_source_index
        _update_mapping_status = alignment_source_parts_outliner_section._update_mapping_status
        _update_selected_part_adjustment = alignment_source_parts_outliner_section._update_selected_part_adjustment
        alignment_original_texture_intent_callbacks = alignment_source_parts_outliner_section.alignment_original_texture_intent_callbacks
        apply_best_guesses_button = alignment_source_parts_outliner_section.apply_best_guesses_button
        apply_source_parts_button = alignment_source_parts_outliner_section.apply_source_parts_button
        assign_source_button = alignment_source_parts_outliner_section.assign_source_button
        center_part_button = alignment_source_parts_outliner_section.center_part_button
        clear_all_guesses_button = alignment_source_parts_outliner_section.clear_all_guesses_button
        clear_state = alignment_source_parts_outliner_section.clear_state
        clear_target_button = alignment_source_parts_outliner_section.clear_target_button
        duplicate_part_button = alignment_source_parts_outliner_section.duplicate_part_button
        empty_targets_filter_checkbox = alignment_source_parts_outliner_section.empty_targets_filter_checkbox
        fit_part_button = alignment_source_parts_outliner_section.fit_part_button
        group_materials_button = alignment_source_parts_outliner_section.group_materials_button
        index = alignment_source_parts_outliner_section.index
        index_map = alignment_source_parts_outliner_section.index_map
        initial_mapping_text_by_target = alignment_source_parts_outliner_section.initial_mapping_text_by_target
        label_text = alignment_source_parts_outliner_section.label_text
        low_confidence_filter_checkbox = alignment_source_parts_outliner_section.low_confidence_filter_checkbox
        mapping_progress_label = alignment_source_parts_outliner_section.mapping_progress_label
        mapping_status_label = alignment_source_parts_outliner_section.mapping_status_label
        mapping_table_action_control_text = alignment_source_parts_outliner_section.mapping_table_action_control_text
        mapping_table_build_requested = alignment_source_parts_outliner_section.mapping_table_build_requested
        mapping_table_build_state = alignment_source_parts_outliner_section.mapping_table_build_state
        mapping_table_build_timer = alignment_source_parts_outliner_section.mapping_table_build_timer
        mapping_targets = alignment_source_parts_outliner_section.mapping_targets
        mapping_tree = alignment_source_parts_outliner_section.mapping_tree
        mappings_by_target = alignment_source_parts_outliner_section.mappings_by_target
        merge_source_button = alignment_source_parts_outliner_section.merge_source_button
        mirror_duplicate_part_button = alignment_source_parts_outliner_section.mirror_duplicate_part_button
        mirrored = alignment_source_parts_outliner_section.mirrored
        original_button_panel = alignment_source_parts_outliner_section.original_button_panel
        original_part_clipboard_action_text = alignment_source_parts_outliner_section.original_part_clipboard_action_text
        original_parts_label = alignment_source_parts_outliner_section.original_parts_label
        original_tree = alignment_source_parts_outliner_section.original_tree
        part_add_target_button = alignment_source_parts_outliner_section.part_add_target_button
        part_controls = alignment_source_parts_outliner_section.part_controls
        part_copied_texture_status_label = alignment_source_parts_outliner_section.part_copied_texture_status_label
        part_enabled_checkbox = alignment_source_parts_outliner_section.part_enabled_checkbox
        part_inspector = alignment_source_parts_outliner_section.part_inspector
        part_inspector_loading = alignment_source_parts_outliner_section.part_inspector_loading
        part_name_label = alignment_source_parts_outliner_section.part_name_label
        part_nudge_step_spin = alignment_source_parts_outliner_section.part_nudge_step_spin
        part_nudge_x_minus_button = alignment_source_parts_outliner_section.part_nudge_x_minus_button
        part_nudge_x_plus_button = alignment_source_parts_outliner_section.part_nudge_x_plus_button
        part_nudge_y_minus_button = alignment_source_parts_outliner_section.part_nudge_y_minus_button
        part_nudge_y_plus_button = alignment_source_parts_outliner_section.part_nudge_y_plus_button
        part_nudge_z_minus_button = alignment_source_parts_outliner_section.part_nudge_z_minus_button
        part_nudge_z_plus_button = alignment_source_parts_outliner_section.part_nudge_z_plus_button
        part_offset_x_spin = alignment_source_parts_outliner_section.part_offset_x_spin
        part_offset_y_spin = alignment_source_parts_outliner_section.part_offset_y_spin
        part_offset_z_spin = alignment_source_parts_outliner_section.part_offset_z_spin
        part_remove_copied_texture_button = alignment_source_parts_outliner_section.part_remove_copied_texture_button
        part_remove_target_button = alignment_source_parts_outliner_section.part_remove_target_button
        part_replace_target_button = alignment_source_parts_outliner_section.part_replace_target_button
        part_role_combo = alignment_source_parts_outliner_section.part_role_combo
        part_rotate_x_spin = alignment_source_parts_outliner_section.part_rotate_x_spin
        part_rotate_y_spin = alignment_source_parts_outliner_section.part_rotate_y_spin
        part_rotate_z_spin = alignment_source_parts_outliner_section.part_rotate_z_spin
        part_scale_x_spin = alignment_source_parts_outliner_section.part_scale_x_spin
        part_scale_y_spin = alignment_source_parts_outliner_section.part_scale_y_spin
        part_scale_z_spin = alignment_source_parts_outliner_section.part_scale_z_spin
        part_source_combo = alignment_source_parts_outliner_section.part_source_combo
        part_target_combo = alignment_source_parts_outliner_section.part_target_combo
        part_target_label = alignment_source_parts_outliner_section.part_target_label
        part_transform_sliders = alignment_source_parts_outliner_section.part_transform_sliders
        part_uniform_spin = alignment_source_parts_outliner_section.part_uniform_spin
        part_use_copied_texture_button = alignment_source_parts_outliner_section.part_use_copied_texture_button
        part_use_route_texture_button = alignment_source_parts_outliner_section.part_use_route_texture_button
        parts_outliner_cache_state = alignment_source_parts_outliner_section.parts_outliner_cache_state
        parts_outliner_item_update_guard = alignment_source_parts_outliner_section.parts_outliner_item_update_guard
        parts_outliner_source_items = alignment_source_parts_outliner_section.parts_outliner_source_items
        parts_outliner_target_items = alignment_source_parts_outliner_section.parts_outliner_target_items
        parts_outliner_tree = alignment_source_parts_outliner_section.parts_outliner_tree
        preview_target_button = alignment_source_parts_outliner_section.preview_target_button
        previous_blocked = alignment_source_parts_outliner_section.previous_blocked
        remove_part_button = alignment_source_parts_outliner_section.remove_part_button
        remove_source_button = alignment_source_parts_outliner_section.remove_source_button
        reset_geometry_button = alignment_source_parts_outliner_section.reset_geometry_button
        reset_part_button = alignment_source_parts_outliner_section.reset_part_button
        role_value = alignment_source_parts_outliner_section.role_value
        scale = alignment_source_parts_outliner_section.scale
        slider_maximum = alignment_source_parts_outliner_section.slider_maximum
        slider_minimum = alignment_source_parts_outliner_section.slider_minimum
        source_part_inspector_control_text = alignment_source_parts_outliner_section.source_part_inspector_control_text
        source_parts_group = alignment_source_parts_outliner_section.source_parts_group
        source_parts_pending_label = alignment_source_parts_outliner_section.source_parts_pending_label
        source_tree = alignment_source_parts_outliner_section.source_tree
        source_tree_context_selection_state = alignment_source_parts_outliner_section.source_tree_context_selection_state
        source_tree_item_update_guard = alignment_source_parts_outliner_section.source_tree_item_update_guard
        source_tree_layout_state = alignment_source_parts_outliner_section.source_tree_layout_state
        source_tree_population_state = alignment_source_parts_outliner_section.source_tree_population_state
        source_tree_population_timer = alignment_source_parts_outliner_section.source_tree_population_timer
        source_tree_progress_label = alignment_source_parts_outliner_section.source_tree_progress_label
        target = alignment_source_parts_outliner_section.target
        target_slots_label = alignment_source_parts_outliner_section.target_slots_label
        tooltip = alignment_source_parts_outliner_section.tooltip
        tree = alignment_source_parts_outliner_section.tree
        undo_geometry_button = alignment_source_parts_outliner_section.undo_geometry_button
        value = alignment_source_parts_outliner_section.value
        values = alignment_source_parts_outliner_section.values

        alignment_mesh_geometry_preview_section = create_alignment_mesh_geometry_preview_section({
            **context,
            **globals(),
            **locals(),
            '_basic_controls_profile_enabled': (lambda *args, **kwargs: context['_basic_controls_profile_enabled'](*args, **kwargs)),
            '_current_complete_swap_material_profile_token': (lambda *args, **kwargs: context['_current_complete_swap_material_profile_token'](*args, **kwargs)),
            '_current_material_authority_preview_profile': (lambda *args, **kwargs: context['_current_material_authority_preview_profile'](*args, **kwargs)),
            '_material_authority_preview_inactive_reason': (lambda *args, **kwargs: context['_material_authority_preview_inactive_reason'](*args, **kwargs)),
            '_material_authority_preview_signature': (lambda *args, **kwargs: context['_material_authority_preview_signature'](*args, **kwargs)),
        })
        _append_selected_source_highlight_overlay = alignment_mesh_geometry_preview_section._append_selected_source_highlight_overlay
        _apply_original_material_preview = alignment_mesh_geometry_preview_section._apply_original_material_preview
        _build_direct_source_preview_model = alignment_mesh_geometry_preview_section._build_direct_source_preview_model
        _current_dialog_mappings_for_preview = alignment_mesh_geometry_preview_section._current_dialog_mappings_for_preview
        _current_static_alignment_transform = alignment_mesh_geometry_preview_section._current_static_alignment_transform
        _current_static_placement_snapshot = alignment_mesh_geometry_preview_section._current_static_placement_snapshot
        _ensure_original_reference_texture_preview_ready = alignment_mesh_geometry_preview_section._ensure_original_reference_texture_preview_ready
        _load_native_preview_core_material_manifest_for_alignment = alignment_mesh_geometry_preview_section._load_native_preview_core_material_manifest_for_alignment
        _mesh_edit_apply_preview_payload = alignment_mesh_geometry_preview_section._mesh_edit_apply_preview_payload
        _mesh_edit_begin_stroke = alignment_mesh_geometry_preview_section._mesh_edit_begin_stroke
        _mesh_edit_cancel_stroke = alignment_mesh_geometry_preview_section._mesh_edit_cancel_stroke
        _mesh_edit_finish_stroke = alignment_mesh_geometry_preview_section._mesh_edit_finish_stroke
        _mesh_edit_preview_source_indices = alignment_mesh_geometry_preview_section._mesh_edit_preview_source_indices
        _mesh_edit_replace_live_triangles_or_queue_rebuild = getattr(
            alignment_mesh_geometry_preview_section,
            "_mesh_edit_replace_live_triangles_or_queue_rebuild",
            None,
        )
        _mesh_edit_selection_changed = alignment_mesh_geometry_preview_section._mesh_edit_selection_changed
        _mesh_edit_update_live_preview = alignment_mesh_geometry_preview_section._mesh_edit_update_live_preview
        _morph_slider_refresh_controls = alignment_mesh_geometry_preview_section._morph_slider_refresh_controls
        _morph_slider_reload_profiles = alignment_mesh_geometry_preview_section._morph_slider_reload_profiles
        _preview_target_mesh_indices = alignment_mesh_geometry_preview_section._preview_target_mesh_indices
        _refresh_alignment_virtual_sidecar_contract = alignment_mesh_geometry_preview_section._refresh_alignment_virtual_sidecar_contract
        _refresh_mesh_edit_controls = alignment_mesh_geometry_preview_section._refresh_mesh_edit_controls
        _refresh_output_impact_review = alignment_mesh_geometry_preview_section._refresh_output_impact_review
        _remember_alignment_d3d11_source_editor_ids = alignment_mesh_geometry_preview_section._remember_alignment_d3d11_source_editor_ids
        _safe_refresh_static_dialog_preview = alignment_mesh_geometry_preview_section._safe_refresh_static_dialog_preview
        _selected_part_preview_indices = alignment_mesh_geometry_preview_section._selected_part_preview_indices
        _static_options_from_placement_snapshot = alignment_mesh_geometry_preview_section._static_options_from_placement_snapshot
        _sync_mesh_edit_preview_settings = alignment_mesh_geometry_preview_section._sync_mesh_edit_preview_settings
        if callable(_mesh_edit_replace_live_triangles_or_queue_rebuild):
            prompt_shell_context["_mesh_edit_replace_live_triangles_or_queue_rebuild"] = _mesh_edit_replace_live_triangles_or_queue_rebuild
        prompt_shell_context["_sync_mesh_edit_preview_settings"] = _sync_mesh_edit_preview_settings
        button = alignment_mesh_geometry_preview_section.button
        edit = alignment_mesh_geometry_preview_section.edit
        geometry_overview_group = alignment_mesh_geometry_preview_section.geometry_overview_group
        geometry_overview_layout = alignment_mesh_geometry_preview_section.geometry_overview_layout
        geometry_summary = alignment_mesh_geometry_preview_section.geometry_summary
        label = alignment_mesh_geometry_preview_section.label
        mesh_edit_action_control_text = alignment_mesh_geometry_preview_section.mesh_edit_action_control_text
        mesh_edit_button_row = alignment_mesh_geometry_preview_section.mesh_edit_button_row
        mesh_edit_clear_selection_button = alignment_mesh_geometry_preview_section.mesh_edit_clear_selection_button
        mesh_edit_delete_faces_button = alignment_mesh_geometry_preview_section.mesh_edit_delete_faces_button
        mesh_edit_delete_mode_combo = alignment_mesh_geometry_preview_section.mesh_edit_delete_mode_combo
        mesh_edit_enabled_checkbox = alignment_mesh_geometry_preview_section.mesh_edit_enabled_checkbox
        mesh_edit_falloff_combo = alignment_mesh_geometry_preview_section.mesh_edit_falloff_combo
        mesh_edit_field_rows = alignment_mesh_geometry_preview_section.mesh_edit_field_rows
        mesh_edit_full_reset_button = alignment_mesh_geometry_preview_section.mesh_edit_full_reset_button
        mesh_edit_group = alignment_mesh_geometry_preview_section.mesh_edit_group
        mesh_edit_grow_selection_button = alignment_mesh_geometry_preview_section.mesh_edit_grow_selection_button
        mesh_edit_invert_selection_button = alignment_mesh_geometry_preview_section.mesh_edit_invert_selection_button
        mesh_edit_iterations_spin = alignment_mesh_geometry_preview_section.mesh_edit_iterations_spin
        mesh_edit_layout = alignment_mesh_geometry_preview_section.mesh_edit_layout
        mesh_edit_mirror_checkbox = alignment_mesh_geometry_preview_section.mesh_edit_mirror_checkbox
        mesh_edit_option_widget = alignment_mesh_geometry_preview_section.mesh_edit_option_widget
        mesh_edit_part_combo = alignment_mesh_geometry_preview_section.mesh_edit_part_combo
        mesh_edit_radius_spin = alignment_mesh_geometry_preview_section.mesh_edit_radius_spin
        mesh_edit_redo_button = alignment_mesh_geometry_preview_section.mesh_edit_redo_button
        mesh_edit_remove_mode_label = alignment_mesh_geometry_preview_section.mesh_edit_remove_mode_label
        mesh_edit_reset_part_button = alignment_mesh_geometry_preview_section.mesh_edit_reset_part_button
        mesh_edit_scope_combo = alignment_mesh_geometry_preview_section.mesh_edit_scope_combo
        mesh_edit_select_part_button = alignment_mesh_geometry_preview_section.mesh_edit_select_part_button
        mesh_edit_selection_actions_widget = alignment_mesh_geometry_preview_section.mesh_edit_selection_actions_widget
        mesh_edit_selection_depth_combo = alignment_mesh_geometry_preview_section.mesh_edit_selection_depth_combo
        mesh_edit_selection_mode_combo = alignment_mesh_geometry_preview_section.mesh_edit_selection_mode_combo
        mesh_edit_show_vertices_checkbox = alignment_mesh_geometry_preview_section.mesh_edit_show_vertices_checkbox
        mesh_edit_shrink_selection_button = alignment_mesh_geometry_preview_section.mesh_edit_shrink_selection_button
        mesh_edit_smooth_selection_button = alignment_mesh_geometry_preview_section.mesh_edit_smooth_selection_button
        mesh_edit_refine_smooth_selection_button = alignment_mesh_geometry_preview_section.mesh_edit_refine_smooth_selection_button
        mesh_edit_status_label = alignment_mesh_geometry_preview_section.mesh_edit_status_label
        mesh_edit_strength_spin = alignment_mesh_geometry_preview_section.mesh_edit_strength_spin
        mesh_edit_split_selection_button = alignment_mesh_geometry_preview_section.mesh_edit_split_selection_button
        mesh_edit_subdivide_selection_button = alignment_mesh_geometry_preview_section.mesh_edit_subdivide_selection_button
        mesh_edit_supported = alignment_mesh_geometry_preview_section.mesh_edit_supported
        mesh_edit_tool_buttons = alignment_mesh_geometry_preview_section.mesh_edit_tool_buttons
        mesh_edit_tool_combo = alignment_mesh_geometry_preview_section.mesh_edit_tool_combo
        mesh_edit_tool_palette = alignment_mesh_geometry_preview_section.mesh_edit_tool_palette
        mesh_edit_undo_button = alignment_mesh_geometry_preview_section.mesh_edit_undo_button
        morph_slider_add_action = alignment_mesh_geometry_preview_section.morph_slider_add_action
        morph_slider_bake_button = alignment_mesh_geometry_preview_section.morph_slider_bake_button
        morph_slider_create_button = alignment_mesh_geometry_preview_section.morph_slider_create_button
        morph_slider_group = alignment_mesh_geometry_preview_section.morph_slider_group
        morph_slider_import_action = alignment_mesh_geometry_preview_section.morph_slider_import_action
        morph_slider_manage_button = alignment_mesh_geometry_preview_section.morph_slider_manage_button
        morph_slider_reload_action = alignment_mesh_geometry_preview_section.morph_slider_reload_action
        morph_slider_reset_button = alignment_mesh_geometry_preview_section.morph_slider_reset_button
        morph_slider_rows_layout = alignment_mesh_geometry_preview_section.morph_slider_rows_layout
        morph_slider_rows_widget = alignment_mesh_geometry_preview_section.morph_slider_rows_widget
        morph_slider_status_label = alignment_mesh_geometry_preview_section.morph_slider_status_label
        original_texture_worker_receiver = alignment_mesh_geometry_preview_section.original_texture_worker_receiver
        output_impact_review_label = alignment_mesh_geometry_preview_section.output_impact_review_label
        source = alignment_mesh_geometry_preview_section.source
        source_count = alignment_mesh_geometry_preview_section.source_count
        tooltip = alignment_mesh_geometry_preview_section.tooltip
        _alignment_startup_step(alignment_startup_text["replacement_texture_sources"])
        texture_files_for_mapping = list(prompt_preflight.texture_files)
        seen_texture_file_keys = {str(path).casefold() for path in texture_files_for_mapping}
        auto_scene_texture_sources = list(prompt_preflight.auto_texture_sources)
        _set_texture_sets(dict(prompt_preflight.texture_sets))
        alignment_texture_material_section = create_alignment_texture_material_section({
            **context,
            **globals(),
            **locals(),
            'inject_base_color_checkbox': (lambda: context.get('inject_base_color_checkbox')),
            'prune_unmapped_original_dds_checkbox': (lambda: context.get('prune_unmapped_original_dds_checkbox')),
            'rebuild_sidecar_checkbox': (lambda: context.get('rebuild_sidecar_checkbox')),
        })
        _copied_source_texture_slot_overrides = alignment_texture_material_section._copied_source_texture_slot_overrides
        _load_original_reference_texture_preview = alignment_texture_material_section._load_original_reference_texture_preview
        _stop_original_reference_texture_worker = alignment_texture_material_section._stop_original_reference_texture_worker
        _save_texture_transform_controls = alignment_texture_material_section._save_texture_transform_controls
        binding = alignment_texture_material_section.binding
        rows = alignment_texture_material_section.rows
        source_index = alignment_texture_material_section.source_index
        target_name = alignment_texture_material_section.target_name
        texture_transform_offset_u_spin = alignment_texture_material_section.texture_transform_offset_u_spin
        texture_transform_offset_v_spin = alignment_texture_material_section.texture_transform_offset_v_spin
        texture_transform_scale_u_spin = alignment_texture_material_section.texture_transform_scale_u_spin
        texture_transform_scale_v_spin = alignment_texture_material_section.texture_transform_scale_v_spin
    except Exception as exc:
        alignment_setup_failed = True
        alignment_setup_error = str(exc)
        alignment_setup_traceback = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )
        _record_runtime_event(
            "mesh_alignment_setup_warning",
            path=getattr(entry, "path", ""),
            dialog_title=dialog_title,
            message=str(exc),
            error_type=type(exc).__name__,
            traceback=alignment_setup_traceback,
            step="alignment_mapping_setup",
            modify_original_clone=modify_original_clone_mode,
            defer_original_texture_preview=defer_original_texture_preview,
        )
        _alignment_startup_step(_alignment_setup_warning_startup_text_helper())
        mapping_warning = QLabel(_alignment_setup_warning_label_text_helper(exc))
        mapping_warning.setWordWrap(True)
        mapping_warning.setStyleSheet("color: #fdd663;")
        parts_layout.addWidget(mapping_warning)


    return SimpleNamespace(**{name: value for name, value in locals().items() if name != "context"})


__all__ = ["create_static_replacement_prompt_setup"]
