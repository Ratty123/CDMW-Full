from __future__ import annotations

def _source_part_mutation_step_001(_state):
    _state.Dict = _state.context.get('Dict')
    _state.List = _state.context.get('List')
    _state.Optional = _state.context.get('Optional')
    _state.Path = _state.context.get('Path')
    _state.QFileDialog = _state.context.get('QFileDialog')
    _state.QMessageBox = _state.context.get('QMessageBox')
    _state.SCENE_IMPORT_EXTENSIONS = _state.context.get('SCENE_IMPORT_EXTENSIONS')
    _state.Sequence = _state.context.get('Sequence')
    _state.StaticSourcePartAdjustment = _state.context.get('StaticSourcePartAdjustment')
    _state._add_dialog_supplemental_file = _state.context.get('_add_dialog_supplemental_file')
    _state._add_source_tree_item = _state.context.get('_add_source_tree_item')
    _state._apply_source_material_texture_overrides_to_ui_texture_sets = _state.context.get('_apply_source_material_texture_overrides_to_ui_texture_sets')
    _state._copy_source_part_with_adjustment = _state.context.get('_copy_source_part_with_adjustment')
    _state._fit_alignment_tree_height_to_rows = _state.context.get('_fit_alignment_tree_height_to_rows')
    _state._get_replacement_mesh_base_for_mapping = _state.context.get('_get_replacement_mesh_base_for_mapping')
    _state._get_replacement_mesh_for_mapping = _state.context.get('_get_replacement_mesh_for_mapping')
    _state._get_texture_sets = _state.context.get('_get_texture_sets')
    _state._invalidate_source_display_cache = _state.context.get('_invalidate_source_display_cache')
    _state._is_marker_source = _state.context.get('_is_marker_source')
    _state._load_selected_part_controls = _state.context.get('_load_selected_part_controls')
    _state._mapping_role_hint = _state.context.get('_mapping_role_hint')
    _state._maybe_flatten_scene_import_parts = _state.context.get('_maybe_flatten_scene_import_parts')
    _state._maybe_reduce_high_density_scene_import = _state.context.get('_maybe_reduce_high_density_scene_import')
    _state._normalize_appended_part_to_work_area = _state.context.get('_normalize_appended_part_to_work_area')
    _state._parse_mapping_edit = _state.context.get('_parse_mapping_edit')
    _state._pop_geometry_undo_snapshot = _state.context.get('_pop_geometry_undo_snapshot')
    _state._prompt_assign_appended_mesh_parts = _state.context.get('_prompt_assign_appended_mesh_parts')
    _state._push_geometry_undo_snapshot = _state.context.get('_push_geometry_undo_snapshot')
    _state._queue_static_preview_rebuild = _state.context.get('_queue_static_preview_rebuild')
    _state._rebuild_source_part_widgets = _state.context.get('_rebuild_source_part_widgets')
    _state._refresh_added_part_texture_tree = _state.context.get('_refresh_added_part_texture_tree')
    _state._refresh_original_reference_preview = _state.context.get('_refresh_original_reference_preview')
    _state._refresh_source_assignment_columns = _state.context.get('_refresh_source_assignment_columns')
    _state._refresh_source_material_plan = _state.context.get('_refresh_source_material_plan')
    _state._refresh_source_tree_selection_state = _state.context.get('_refresh_source_tree_selection_state')
    _state._refresh_texture_override_tree = _state.context.get('_refresh_texture_override_tree')
    _state._refresh_texture_row_guidance = _state.context.get('_refresh_texture_row_guidance')
    _state._refresh_texture_table = _state.context.get('_refresh_texture_table')
    _state._remap_selected_source_index = _state.context.get('_remap_selected_source_index')
    _state._remap_source_index_collection = _state.context.get('_remap_source_index_collection')
    _state._remap_source_index_dict = _state.context.get('_remap_source_index_dict')
    _state._remapped_original_copy_source_text_helper = _state.context.get('_remapped_original_copy_source_text_helper')
    _state._rollback_cancelled_appended_mesh_part_import = _state.context.get('_rollback_cancelled_appended_mesh_part_import')
    _state._selected_source_indices_from_tree = _state.context.get('_selected_source_indices_from_tree')
    _state._semantic_tokens = _state.context.get('_semantic_tokens')
    _state._set_mapping_indices = _state.context.get('_set_mapping_indices')
    _state._set_replacement_mesh_base_for_mapping = _state.context.get('_set_replacement_mesh_base_for_mapping')
    _state._set_replacement_mesh_for_mapping = _state.context.get('_set_replacement_mesh_for_mapping')
    _state._set_replacement_preview_model = _state.context.get('_set_replacement_preview_model')
    _state._set_source_parts_apply_pending = _state.context.get('_set_source_parts_apply_pending')
    _state._set_source_parts_preview_rebuild_pending = _state.context.get('_set_source_parts_preview_rebuild_pending')
    _state._set_texture_sets = _state.context.get('_set_texture_sets')
    _state._set_transform_source_indices = _state.context.get('_set_transform_source_indices')
    _state._alignment_d3d11_preview_active = _state.context.get('_alignment_d3d11_preview_active')
    _state._alignment_mesh_edit_tab_active = _state.context.get('_alignment_mesh_edit_tab_active')
    _state._mesh_edit_preview_source_indices = _state.context.get('_mesh_edit_preview_source_indices')
    _state._mesh_edit_replace_live_triangles_or_queue_rebuild = _state.context.get('_mesh_edit_replace_live_triangles_or_queue_rebuild')
    _state._source_display_name = _state.context.get('_source_display_name')
    _state._source_group_label_or_fallback_helper = _state.context.get('_source_group_label_or_fallback_helper')
    _state._source_mapping_target_indices = _state.context.get('_source_mapping_target_indices')
    _state._source_material_group_label = _state.context.get('_source_material_group_label')
    _state._source_part_add_mesh_part_failed_title_helper = _state.context.get('_source_part_add_mesh_part_failed_title_helper')
    _state._source_part_added_mesh_part_status_helper = _state.context.get('_source_part_added_mesh_part_status_helper')
    _state._source_part_append_file_route_state_helper = _state.context.get('_source_part_append_file_route_state_helper')
    _state._source_part_append_imported_state_helper = _state.context.get('_source_part_append_imported_state_helper')
    _state._source_part_append_mesh_file_dialog_text_helper = _state.context.get('_source_part_append_mesh_file_dialog_text_helper')
    _state._source_part_append_rollback_snapshot_helper = _state.context.get('_source_part_append_rollback_snapshot_helper')
    _state._source_part_append_texture_control_state_helper = _state.context.get('_source_part_append_texture_control_state_helper')
    _state._source_part_assign_material_groups_to_targets_helper = _state.context.get('_source_part_assign_material_groups_to_targets_helper')
    _state._source_part_cancel_import_status_helper = _state.context.get('_source_part_cancel_import_status_helper')
    _state._source_part_delete_index_map_state_helper = _state.context.get('_source_part_delete_index_map_state_helper')
    _state._source_part_delete_selection_state_helper = _state.context.get('_source_part_delete_selection_state_helper')
    _state._source_part_delete_status_text_helper = _state.context.get('_source_part_delete_status_text_helper')
    _state._source_part_deleted_pending_reason_helper = _state.context.get('_source_part_deleted_pending_reason_helper')
    _state._source_part_deleted_status_helper = _state.context.get('_source_part_deleted_status_helper')
    _state._source_part_display_label_helper = _state.context.get('_source_part_display_label_helper')
    _state._source_part_duplicate_presentation_state_helper = _state.context.get('_source_part_duplicate_presentation_state_helper')
    _state._source_part_duplicate_route_state_helper = _state.context.get('_source_part_duplicate_route_state_helper')
    _state._source_part_group_initial_target_counts_helper = _state.context.get('_source_part_group_initial_target_counts_helper')
    _state._source_part_group_items_helper = _state.context.get('_source_part_group_items_helper')
    _state._source_part_group_routing_overflow_message_helper = _state.context.get('_source_part_group_routing_overflow_message_helper')
    _state._source_part_group_routing_text_helper = _state.context.get('_source_part_group_routing_text_helper')
    _state._source_part_mapping_indices_for_target_helper = _state.context.get('_source_part_mapping_indices_for_target_helper')
    _state._source_part_material_groups_helper = _state.context.get('_source_part_material_groups_helper')
    _state._source_part_unsupported_mesh_part_message_helper = _state.context.get('_source_part_unsupported_mesh_part_message_helper')
    _state._source_role_label = _state.context.get('_source_role_label')
    _state._sync_highlight_sets = _state.context.get('_sync_highlight_sets')
    _state._target_submesh_display_name_helper = _state.context.get('_target_submesh_display_name_helper')
    _state._texture_set_for_source_index = _state.context.get('_texture_set_for_source_index')
    _state._update_mapping_status = _state.context.get('_update_mapping_status')

def _source_part_mutation_step_002(_state):
    _state._update_selection_context = _state.context.get('_update_selection_context')
    _state.adjustment = _state.context.get('adjustment')
    _state.append_file_route = _state.context.get('append_file_route')
    _state.append_imported_state = _state.context.get('append_imported_state')
    _state.append_mesh_part_button = _state.context.get('append_mesh_part_button')
    _state.append_result = _state.context.get('append_result')
    _state.append_rollback_snapshot = _state.context.get('append_rollback_snapshot')
    _state.append_scene_import_to_mesh = _state.context.get('append_scene_import_to_mesh')
    _state.append_scene_result = _state.context.get('append_scene_result')
    _state.append_texture_control_state = _state.context.get('append_texture_control_state')
    _state.append_undo_pushed = _state.context.get('append_undo_pushed')
    _state.appended_source_indices = _state.context.get('appended_source_indices')
    _state.appended_texture_sets = _state.context.get('appended_texture_sets')
    _state.assignment_action = _state.context.get('assignment_action')
    _state.baked_source = _state.context.get('baked_source')
    _state.base_copy = _state.context.get('base_copy')
    _state.base_submeshes = _state.context.get('base_submeshes')
    _state.clear_response = _state.context.get('clear_response')
    _state.copied_original_physics_sensitive_sources = _state.context.get('copied_original_physics_sensitive_sources')
    _state.copied_original_source_indices = _state.context.get('copied_original_source_indices')
    _state.copied_original_source_to_original_index = _state.context.get('copied_original_source_to_original_index')
    _state.copied_original_texture_disabled_sources = _state.context.get('copied_original_texture_disabled_sources')
    _state.copied_original_texture_intents_by_source = _state.context.get('copied_original_texture_intents_by_source')
    _state.copy = _state.context.get('copy')
    _state.delete_index_map_state = _state.context.get('delete_index_map_state')
    _state.delete_indices = _state.context.get('delete_indices')
    _state.delete_selection_state = _state.context.get('delete_selection_state')
    _state.deltas = _state.context.get('deltas')
    _state.dialog = _state.context.get('dialog')
    _state.dialog_added_supplemental_files = _state.context.get('dialog_added_supplemental_files')
    _state.duplicate_presentation = _state.context.get('duplicate_presentation')
    _state.duplicate_route = _state.context.get('duplicate_route')
    _state.edit = _state.context.get('edit')
    _state.exc = _state.context.get('exc')
    _state.group_replacement_texture_sets = _state.context.get('group_replacement_texture_sets')
    _state.independent_output_source_indices = _state.context.get('independent_output_source_indices')
    _state.index = _state.context.get('index')
    _state.index_map = _state.context.get('index_map')
    _state.inject_base_color_checkbox = _state.context.get('inject_base_color_checkbox')
    _state.item = _state.context.get('item')
    _state.kept_submeshes = _state.context.get('kept_submeshes')
    _state.mapped_targets = _state.context.get('mapped_targets')
    _state.mapping_edits = _state.context.get('mapping_edits')
    _state.mapping_edits_by_target = _state.context.get('mapping_edits_by_target')
    _state.marker_source_indices = _state.context.get('marker_source_indices')
    _state.mesh_edit_redo_adjustment_stack = _state.context.get('mesh_edit_redo_adjustment_stack')
    _state.mesh_edit_redo_stack = _state.context.get('mesh_edit_redo_stack')
    _state.mesh_edit_selected_faces_by_submesh = _state.context.get('mesh_edit_selected_faces_by_submesh')
    _state.mesh_edit_selected_source_indices = _state.context.get('mesh_edit_selected_source_indices')
    _state.mesh_edit_selected_vertices_by_submesh = _state.context.get('mesh_edit_selected_vertices_by_submesh')
    _state.mesh_edit_undo_adjustment_stack = _state.context.get('mesh_edit_undo_adjustment_stack')
    _state.mesh_edit_undo_stack = _state.context.get('mesh_edit_undo_stack')
    _state.mirrored = _state.context.get('mirrored')
    _state.morph_slider_post_edit_deltas = _state.context.get('morph_slider_post_edit_deltas')
    _state.new_adjustment = _state.context.get('new_adjustment')
    _state.new_current_index = _state.context.get('new_current_index')
    _state.new_index = _state.context.get('new_index')
    _state.new_item = _state.context.get('new_item')
    _state.old_index = _state.context.get('old_index')
    _state.original_item = _state.context.get('original_item')
    _state.original_items_by_index = _state.context.get('original_items_by_index')
    _state.original_mesh_for_mapping = _state.context.get('original_mesh_for_mapping')
    _state.overflow_groups = _state.context.get('overflow_groups')
    _state.parsed_mesh_to_preview_model = _state.context.get('parsed_mesh_to_preview_model')
    _state.part_source_combo = _state.context.get('part_source_combo')
    _state.placement_note = _state.context.get('placement_note')
    _state.plane_x = _state.context.get('plane_x')
    _state.presentation = _state.context.get('presentation')
    _state.preview_only_source_indices = _state.context.get('preview_only_source_indices')
    _state.rebuild_reason = _state.context.get('rebuild_reason')
    _state.rebuild_sidecar_checkbox = _state.context.get('rebuild_sidecar_checkbox')
    _state.refresh_parsed_mesh_totals = _state.context.get('refresh_parsed_mesh_totals')
    _state.remapped = _state.context.get('remapped')
    _state.remapped_adjustment = _state.context.get('remapped_adjustment')
    _state.remapped_adjustments = _state.context.get('remapped_adjustments')
    _state.remapped_copied_original_source_to_original_index = _state.context.get('remapped_copied_original_source_to_original_index')
    _state.remapped_copied_original_texture_intents = _state.context.get('remapped_copied_original_texture_intents')
    _state.remapped_indices = _state.context.get('remapped_indices')
    _state.remapped_source_display_overrides = _state.context.get('remapped_source_display_overrides')
    _state.remapped_source_role_overrides = _state.context.get('remapped_source_role_overrides')
    _state.replacement_mesh_base_for_mapping = _state.context.get('replacement_mesh_base_for_mapping')
    _state.replacement_mesh_for_mapping = _state.context.get('replacement_mesh_for_mapping')
    _state.selected_added_part_texture_row = _state.context.get('selected_added_part_texture_row')
    _state.selected_indices = _state.context.get('selected_indices')
    _state.selected_original_highlight_indices = _state.context.get('selected_original_highlight_indices')
    _state.selected_original_part = _state.context.get('selected_original_part')
    _state.selected_path = _state.context.get('selected_path')
    _state.selected_source_highlight_indices = _state.context.get('selected_source_highlight_indices')
    _state.selected_source_part = _state.context.get('selected_source_part')
    _state.selected_target_original_highlight_indices = _state.context.get('selected_target_original_highlight_indices')

def _source_part_mutation_step_003(_state):
    _state.selected_target_slot = _state.context.get('selected_target_slot')
    _state.selected_target_source_highlight_indices = _state.context.get('selected_target_source_highlight_indices')
    _state.selected_texture_plan_source = _state.context.get('selected_texture_plan_source')
    _state.selected_texture_row = _state.context.get('selected_texture_row')
    _state.self = _state.context.get('self')
    _state.source = _state.context.get('source')
    _state.source_adjustment = _state.context.get('source_adjustment')
    _state.source_count = _state.context.get('source_count')
    _state.source_display_overrides = _state.context.get('source_display_overrides')
    _state.source_face_counts = _state.context.get('source_face_counts')
    _state.source_geometry_revision = _state.context.get('source_geometry_revision')
    _state.source_groups = _state.context.get('source_groups')
    _state.source_index = _state.context.get('source_index')
    _state.source_indices = _state.context.get('source_indices')
    _state.source_initial_targets = _state.context.get('source_initial_targets')
    _state.source_items_by_index = _state.context.get('source_items_by_index')
    _state.source_label = _state.context.get('source_label')
    _state.source_material_texture_override_assignments = _state.context.get('source_material_texture_override_assignments')
    _state.source_part_adjustments = _state.context.get('source_part_adjustments')
    _state.source_part_append_mesh_file_dialog_text = _state.context.get('source_part_append_mesh_file_dialog_text')
    _state.source_part_delete_status_text = _state.context.get('source_part_delete_status_text')
    _state.source_part_group_routing_text = _state.context.get('source_part_group_routing_text')
    _state.source_parts_apply_state = _state.context.get('source_parts_apply_state')
    _state.source_path = _state.context.get('source_path')
    _state.source_role_overrides = _state.context.get('source_role_overrides')
    _state.source_tree = _state.context.get('source_tree')
    _state.source_tree_layout_state = _state.context.get('source_tree_layout_state')
    _state.static_preview_baked_transform_state = _state.context.get('static_preview_baked_transform_state')
    _state.static_preview_geometry_cache = _state.context.get('static_preview_geometry_cache')
    _state.static_preview_prepared_cache = _state.context.get('static_preview_prepared_cache')
    _state.submesh = _state.context.get('submesh')
    _state.suggested_mappings = _state.context.get('suggested_mappings')
    _state.supplemental_path = _state.context.get('supplemental_path')
    _state.target_count = _state.context.get('target_count')
    _state.target_index = _state.context.get('target_index')
    _state.target_set = _state.context.get('target_set')
    _state.target_sources = _state.context.get('target_sources')
    _state.texture_files_for_mapping = _state.context.get('texture_files_for_mapping')
    _state.texture_override_assignments = _state.context.get('texture_override_assignments')
    _state.texture_overrides_dirty = _state.context.get('texture_overrides_dirty')
    _state.texture_sets = _state.context.get('texture_sets')
    _state.transform_source_indices = _state.context.get('transform_source_indices')
    _state.value = _state.context.get('value')
    _state.working_copy = _state.context.get('working_copy')
    _state.source_task_controller = _state.source_mix_task_controller_for_guard(_state.self, _state.dialog)

def _source_part_mutation_step_004(_state):

    def _source_part_current_preview_indices() -> object:
        if callable(_state._mesh_edit_preview_source_indices):
            return _state._mesh_edit_preview_source_indices()
        mesh = _state._get_replacement_mesh_for_mapping()
        return range(len(getattr(mesh, 'submeshes', ()) or ())) if mesh is not None else ()
    _state._source_part_current_preview_indices = _source_part_current_preview_indices

def _source_part_mutation_step_005(_state):

    def _source_part_mesh_edit_active() -> bool:
        if not callable(_state._alignment_mesh_edit_tab_active):
            return False
        return bool(_state._alignment_mesh_edit_tab_active())
    _state._source_part_mesh_edit_active = _source_part_mesh_edit_active

def _source_part_mutation_step_006(_state):

    def _source_part_refresh_geometry_preview(reason: str, source_indices: object | None=None, *, replace_all: bool=False) -> None:
        _state.static_preview_geometry_cache.clear()
        _state.static_preview_prepared_cache.clear()
        _state.texture_overrides_dirty['dirty'] = True
        if callable(_state._alignment_d3d11_preview_active) and _state._alignment_d3d11_preview_active():
            if callable(_state._mesh_edit_replace_live_triangles_or_queue_rebuild):
                _state._mesh_edit_replace_live_triangles_or_queue_rebuild(source_indices if source_indices is not None else _state._source_part_current_preview_indices(), replace_all=replace_all)
                return
            _state.self.set_status_message('Native D3D11 source-part preview commands are unavailable; preview is stale. Reload D3D11 preview to resync.', error=True)
            return
        if _state._source_part_mesh_edit_active():
            _state.self.set_status_message('Active Mesh Editor source-part preview requires native D3D11 refresh; Python preview rebuild fallback is disabled.', error=True)
            return
        replacement_mesh_for_mapping = _state._get_replacement_mesh_for_mapping()
        _state._set_replacement_preview_model(_state.parsed_mesh_to_preview_model(replacement_mesh_for_mapping) if replacement_mesh_for_mapping is not None else None)
        _state._set_source_parts_preview_rebuild_pending(reason)
        _state._queue_static_preview_rebuild()
    _state._source_part_refresh_geometry_preview = _source_part_refresh_geometry_preview

def _source_part_mutation_step_007(_state):

    def _source_part_active_geometry_mutation_blocked() -> bool:
        if not _state._source_part_mesh_edit_active():
            return False
        _state.self.set_status_message('Active Mesh Editor source-part topology changes require native geometry execution; Python mesh mutation fallback is disabled.', error=True)
        return True
    _state._source_part_active_geometry_mutation_blocked = _source_part_active_geometry_mutation_blocked

def _source_part_mutation_step_008(_state):

    def _source_part_material_routing_mutation_blocked() -> bool:
        if not _state._source_part_mesh_edit_active():
            return False
        if bool(getattr(_state.dialog, '_mesh_editor_embedded_dotnet_active', False)) and callable(getattr(_state.dialog, '_mesh_editor_embedded_apply_material_parameters', None)):
            return False
        _state.self.set_status_message('Active Mesh Editor source-part material routing requires native material execution; Python routing mutation fallback is disabled.', error=True)
        return True
    _state._source_part_material_routing_mutation_blocked = _source_part_material_routing_mutation_blocked

def _source_part_mutation_step_009(_state):

    def _source_part_append_capture_mesh_snapshot(mesh: object, operation: str) -> object | None:
        if mesh is None:
            return None
        try:
            from cdmw.services.mesh_workflow_service import snapshot_native_mesh_submeshes
            native_snapshot = snapshot_native_mesh_submeshes(mesh)
        except Exception:
            native_snapshot = None
        if native_snapshot is not None:
            return native_snapshot

        def _fallback_allowed(candidate: object) -> bool:
            if _state.allow_python_full_mesh_clone_fallback(candidate, operation, 'Python source-part append rollback clone fallback blocked while native mesh core is available'):
                return True
            _state.self.set_status_message('Native source-part append rollback snapshot failed; Python full-mesh clone fallback blocked while native mesh core is available.', error=True)
            return False
        return _state.clone_mesh_for_static_replacement_native_first(mesh, operation, 'Python source-part append rollback clone fallback blocked while native mesh core is available', fallback_allowed=_fallback_allowed)
    _state._source_part_append_capture_mesh_snapshot = _source_part_append_capture_mesh_snapshot

def _source_part_mutation_step_010(_state):

    def _source_part_append_restore_mesh_snapshot(snapshot: object) -> object | None:
        if isinstance(snapshot, _state.Mapping) and snapshot.get('kind') == 'native_submesh_snapshot':
            try:
                from cdmw.services.mesh_workflow_service import restore_native_mesh_submesh_snapshot
                restored = _state.ParsedMesh()
                if restore_native_mesh_submesh_snapshot(restored, snapshot):
                    return restored
            except Exception:
                return None
            return None
        if isinstance(snapshot, _state.ParsedMesh):
            return _state._source_part_append_clone_parsed_mesh_snapshot(snapshot)
        return None
    _state._source_part_append_restore_mesh_snapshot = _source_part_append_restore_mesh_snapshot

def _source_part_mutation_step_011(_state):

    def _source_part_append_clone_parsed_mesh_snapshot(snapshot: ParsedMesh) -> ParsedMesh | None:

        def _fallback_allowed(candidate: object) -> bool:
            if _state.allow_python_full_mesh_clone_fallback(candidate, 'source_part.append_rollback_restore', 'Python source-part append rollback restore clone fallback blocked while native mesh core is available'):
                return True
            _state.self.set_status_message('Native source-part append rollback restore failed; Python full-mesh clone fallback blocked while native mesh core is available.', error=True)
            return False
        restored = _state.clone_mesh_for_static_replacement_native_first(snapshot, 'source_part.append_rollback_restore', 'Python source-part append rollback restore clone fallback blocked while native mesh core is available', fallback_allowed=_fallback_allowed)
        return restored if isinstance(restored, _state.ParsedMesh) else None
    _state._source_part_append_clone_parsed_mesh_snapshot = _source_part_append_clone_parsed_mesh_snapshot

def _source_part_mutation_step_012(_state):

    def _source_part_append_release_rollback_snapshots(snapshot: object) -> None:
        _state.release_native_submesh_snapshot(getattr(snapshot, 'replacement_mesh', None))
        _state.release_native_submesh_snapshot(getattr(snapshot, 'replacement_base_mesh', None))
    _state._source_part_append_release_rollback_snapshots = _source_part_append_release_rollback_snapshots

def _source_part_mutation_step_013(_state):

    def _delete_selected_source_parts(
        source_indices: Optional[Sequence[int]]=None,
        *,
        resident_state_only: bool=False,
        previous_source_count: int=0,
    ) -> None:
        replacement_mesh_for_mapping = _state._get_replacement_mesh_for_mapping()
        replacement_mesh_base_for_mapping = _state._get_replacement_mesh_base_for_mapping()
        if replacement_mesh_for_mapping is None:
            return
        if source_indices is None or isinstance(source_indices, bool):
            selected_indices = _state._selected_source_indices_from_tree()
        else:
            selected_indices = list(source_indices)
        source_count = int(previous_source_count or 0) if resident_state_only else len(getattr(replacement_mesh_for_mapping, 'submeshes', ()) or ())
        marker_source_indices = () if resident_state_only else tuple((index for index, source in enumerate(tuple(replacement_mesh_for_mapping.submeshes or ())) if _state._is_marker_source(source)))
        delete_selection_state = _state._source_part_delete_selection_state_helper(selected_indices, source_count=source_count, marker_source_indices=marker_source_indices)
        source_part_delete_status_text = _state._source_part_delete_status_text_helper()
        if not delete_selection_state.available:
            _state.self.set_status_message(source_part_delete_status_text[delete_selection_state.status_key])
            return
        if not resident_state_only and _state._source_part_active_geometry_mutation_blocked():
            return
        delete_indices = set(delete_selection_state.delete_indices)
        if not resident_state_only:
            _state._push_geometry_undo_snapshot(source_part_delete_status_text['undo_label'])
        delete_index_map_state = _state._source_part_delete_index_map_state_helper(source_count=source_count, delete_indices=tuple(delete_indices))
        index_map = delete_index_map_state.index_map
        if not resident_state_only:
            kept_submeshes = [submesh for old_index, submesh in enumerate(tuple(replacement_mesh_for_mapping.submeshes or ())) if old_index in delete_index_map_state.kept_indices]
            replacement_mesh_for_mapping.submeshes[:] = kept_submeshes
        if replacement_mesh_base_for_mapping is not None:
            base_submeshes = tuple(getattr(replacement_mesh_base_for_mapping, 'submeshes', ()) or ())
            if len(base_submeshes) == source_count:
                replacement_mesh_base_for_mapping.submeshes[:] = [submesh for old_index, submesh in enumerate(base_submeshes) if old_index in delete_index_map_state.kept_indices]
                _state.refresh_parsed_mesh_totals(replacement_mesh_base_for_mapping)
        _state.refresh_parsed_mesh_totals(replacement_mesh_for_mapping)
        _state.source_geometry_revision['value'] = int(_state.source_geometry_revision.get('value', 0) or 0) + 1
        remapped_adjustments: _state.Dict[int, _state.StaticSourcePartAdjustment] = {}
        for old_index, adjustment in _state.source_part_adjustments.items():
            new_index = index_map.get(int(old_index))
            if new_index is None:
                continue
            remapped_adjustment = _state.copy.deepcopy(adjustment)
            remapped_adjustment.source_submesh_index = int(new_index)
            remapped_adjustments[int(new_index)] = remapped_adjustment
        _state.source_part_adjustments.clear()
        _state.source_part_adjustments.update(remapped_adjustments)
        remapped_source_role_overrides = {int(new_index): str(value) for new_index, value in _state._remap_source_index_dict(_state.source_role_overrides, index_map).items()}
        remapped_source_display_overrides = {int(new_index): str(value) for new_index, value in _state._remap_source_index_dict(_state.source_display_overrides, index_map).items()}
        _state.source_role_overrides.clear()
        _state.source_role_overrides.update(remapped_source_role_overrides)
        _state.source_display_overrides.clear()
        _state.source_display_overrides.update(remapped_source_display_overrides)
        _state._invalidate_source_display_cache()
        for target_set in (_state.appended_source_indices, _state.independent_output_source_indices, _state.preview_only_source_indices, _state.copied_original_source_indices, _state.copied_original_texture_disabled_sources, _state.copied_original_physics_sensitive_sources, _state.selected_source_highlight_indices, _state.selected_target_source_highlight_indices, _state.transform_source_indices):
            remapped = _state._remap_source_index_collection(target_set, index_map)
            target_set.clear()
            target_set.update(remapped)
        remapped_copied_original_source_to_original_index = {int(new_index): int(value) for new_index, value in _state._remap_source_index_dict(_state.copied_original_source_to_original_index, index_map).items()}
        remapped_copied_original_texture_intents = {int(new_index): list(value) for new_index, value in _state._remap_source_index_dict(_state.copied_original_texture_intents_by_source, index_map, copy_values=True).items() if isinstance(value, list)}
        _state.copied_original_source_to_original_index.clear()
        _state.copied_original_source_to_original_index.update(remapped_copied_original_source_to_original_index)
        _state.copied_original_texture_intents_by_source.clear()
        _state.copied_original_texture_intents_by_source.update(remapped_copied_original_texture_intents)
        _state.selected_source_part['index'] = _state._remap_selected_source_index(int(_state.selected_source_part.get('index', -1)), index_map)
        for original_item in _state.original_items_by_index.values():
            original_item.setText(4, _state._remapped_original_copy_source_text_helper(original_item.text(4), index_map))
        if isinstance(_state.static_preview_baked_transform_state.get('parts'), dict):
            _state.static_preview_baked_transform_state['parts'] = _state._remap_source_index_dict(_state.static_preview_baked_transform_state.get('parts', {}), index_map, copy_values=True)
        _state.mesh_edit_selected_vertices_by_submesh.clear()
        _state.mesh_edit_selected_faces_by_submesh.clear()
        if hasattr(_state.mesh_edit_selected_source_indices, 'clear'):
            _state.mesh_edit_selected_source_indices.clear()
        if _state.morph_slider_post_edit_deltas and len(_state.morph_slider_post_edit_deltas) == source_count:
            _state.morph_slider_post_edit_deltas[:] = [deltas for old_index, deltas in enumerate(_state.morph_slider_post_edit_deltas) if old_index not in delete_indices]
        new_current_index = int(_state.selected_source_part.get('index', -1))
        _state._rebuild_source_part_widgets((new_current_index,) if new_current_index >= 0 else (), current_index=new_current_index)
        for target_index, edit in tuple(_state.mapping_edits):
            remapped_indices: _state.List[int] = []
            for old_index in _state._parse_mapping_edit(edit):
                new_index = index_map.get(int(old_index))
                if new_index is not None and int(new_index) not in remapped_indices:
                    remapped_indices.append(int(new_index))
            _state._set_mapping_indices(int(target_index), remapped_indices, push_undo=False, undo_label=source_part_delete_status_text['undo_label'], defer_preview=True)
        if not resident_state_only:
            _state.clear_mesh_history_snapshot_stack(_state.mesh_edit_undo_stack)
            _state.clear_mesh_history_snapshot_stack(_state.mesh_edit_redo_stack)
            _state.mesh_edit_undo_adjustment_stack.clear()
            _state.mesh_edit_redo_adjustment_stack.clear()
        texture_sets = _state.group_replacement_texture_sets(_state.texture_files_for_mapping, obj_mesh=replacement_mesh_for_mapping)
        _state._set_texture_sets(texture_sets)
        _state._apply_source_material_texture_overrides_to_ui_texture_sets(texture_sets)
        try:
            _state.selected_added_part_texture_row['source_index'] = _state._remap_selected_source_index(int(_state.selected_added_part_texture_row.get('source_index', -1)), index_map)
        except NameError:
            pass
        try:
            _state.selected_texture_plan_source['source_indices'] = tuple(sorted(_state._remap_source_index_collection(_state.selected_texture_plan_source.get('source_indices', ()), index_map)))
        except NameError:
            pass
        _state._refresh_source_assignment_columns()
        try:
            _state._refresh_texture_row_guidance()
            _state._refresh_texture_table(_state.selected_texture_row.get('row'))
        except NameError:
            pass
        try:
            _state._refresh_added_part_texture_tree(new_current_index if new_current_index >= 0 else None)
        except NameError:
            pass
        try:
            _state._refresh_source_material_plan(force=True)
        except NameError:
            pass
        _state._load_selected_part_controls()
        _state._sync_highlight_sets()
        if not resident_state_only:
            _state._source_part_refresh_geometry_preview(_state._source_part_deleted_pending_reason_helper(len(delete_indices)), replace_all=True)
        _state.self.set_status_message(_state._source_part_deleted_status_helper(len(delete_indices)))
    _state._delete_selected_source_parts = _delete_selected_source_parts

def _source_part_mutation_step_014(_state):

    def _apply_source_part_preview_changes() -> None:
        rebuild_reason = str(_state.source_parts_apply_state.get('reason', '') or 'source-part changes')
        _state.static_preview_geometry_cache.clear()
        _state.static_preview_prepared_cache.clear()
        _state.texture_overrides_dirty['dirty'] = True
        _state._refresh_source_assignment_columns()
        _state._update_mapping_status()
        _state._update_selection_context()
        _state._source_part_refresh_geometry_preview(rebuild_reason, replace_all=True)
    _state._apply_source_part_preview_changes = _apply_source_part_preview_changes

def _source_part_mutation_step_015(_state):

    def _apply_source_material_grouped_routing() -> None:
        if _state._source_part_material_routing_mutation_blocked():
            return
        replacement_mesh_for_mapping = _state._get_replacement_mesh_for_mapping()
        texture_sets = _state._get_texture_sets()
        if _state.original_mesh_for_mapping is None or replacement_mesh_for_mapping is None:
            return
        try:
            texture_sets = _state.group_replacement_texture_sets(_state.texture_files_for_mapping, obj_mesh=replacement_mesh_for_mapping)
            _state._set_texture_sets(texture_sets)
            _state._apply_source_material_texture_overrides_to_ui_texture_sets(texture_sets)
        except NameError:
            texture_sets = {}
            _state._set_texture_sets(texture_sets)
        source_initial_targets = _state._source_part_group_initial_target_counts_helper(_state.suggested_mappings, lambda source_index: _state._source_material_group_label(int(source_index), texture_sets))
        source_groups, source_face_counts = _state._source_part_material_groups_helper(replacement_mesh_for_mapping, _state.source_part_adjustments, source_material_group_label=lambda source_index: _state._source_material_group_label(int(source_index), texture_sets), source_group_label_or_fallback=_state._source_group_label_or_fallback_helper, is_marker_source=_state._is_marker_source)
        if not source_groups:
            source_part_group_routing_text = _state._source_part_group_routing_text_helper()
            _state.QMessageBox.information(_state.dialog, source_part_group_routing_text['no_source_title'], source_part_group_routing_text['no_source_message'])
            return
        target_count = len(_state.original_mesh_for_mapping.submeshes)
        if target_count <= 0:
            source_part_group_routing_text = _state._source_part_group_routing_text_helper()
            _state.QMessageBox.information(_state.dialog, source_part_group_routing_text['no_target_title'], source_part_group_routing_text['no_target_message'])
            return
        source_part_group_routing_text = _state._source_part_group_routing_text_helper()
        _state._push_geometry_undo_snapshot(source_part_group_routing_text['undo_label'], metadata_only=True)
        if any((str(value or '').strip() for value in _state.texture_override_assignments.values())):
            clear_response = _state.QMessageBox.question(_state.dialog, source_part_group_routing_text['clear_manual_title'], source_part_group_routing_text['clear_manual_message'], _state.QMessageBox.Yes | _state.QMessageBox.No, _state.QMessageBox.Yes)
            if clear_response == _state.QMessageBox.Yes:
                _state.texture_override_assignments.clear()
                try:
                    _state._refresh_texture_override_tree()
                except NameError:
                    pass
        target_sources, overflow_groups = _state._source_part_assign_material_groups_to_targets_helper(_state._source_part_group_items_helper(source_groups, source_face_counts), target_count=target_count, original_mesh=_state.original_mesh_for_mapping, replacement_mesh=replacement_mesh_for_mapping, target_display_name=_state._target_submesh_display_name_helper, source_initial_targets=source_initial_targets, semantic_tokens=_state._semantic_tokens)
        for target_index, source_indices in target_sources.items():
            _state._set_mapping_indices(target_index, source_indices, push_undo=False)
        try:
            if texture_sets and (not _state.rebuild_sidecar_checkbox.isChecked()):
                _state.rebuild_sidecar_checkbox.setChecked(True)
        except NameError:
            pass
        try:
            _state._refresh_source_material_plan()
        except NameError:
            pass
        if overflow_groups:
            source_part_group_routing_text = _state._source_part_group_routing_text_helper()
            _state.QMessageBox.warning(_state.dialog, source_part_group_routing_text['overflow_title'], _state._source_part_group_routing_overflow_message_helper(overflow_groups))
    _state._apply_source_material_grouped_routing = _apply_source_material_grouped_routing

def _source_part_mutation_step_016(_state):

    def _duplicate_selected_part(*, mirrored: bool=False) -> None:
        replacement_mesh_for_mapping = _state._get_replacement_mesh_for_mapping()
        replacement_mesh_base_for_mapping = _state._get_replacement_mesh_base_for_mapping()
        source_index = int(_state.selected_source_part.get('index', -1))
        if replacement_mesh_for_mapping is None or replacement_mesh_base_for_mapping is None:
            return
        mapped_targets = _state._source_mapping_target_indices(source_index)
        duplicate_route = _state._source_part_duplicate_route_state_helper(mirrored=mirrored, source_index=source_index, source_count=len(replacement_mesh_for_mapping.submeshes), has_base_mesh=replacement_mesh_base_for_mapping is not None, new_index=len(replacement_mesh_for_mapping.submeshes), mapped_target_indices=mapped_targets, independent_output_source_indices=_state.independent_output_source_indices, preview_only_source_indices=_state.preview_only_source_indices)
        if not duplicate_route.available:
            return
        if _state._source_part_active_geometry_mutation_blocked():
            return
        _state._push_geometry_undo_snapshot(duplicate_route.undo_label)
        source = replacement_mesh_for_mapping.submeshes[source_index]
        source_adjustment = _state.source_part_adjustments.get(source_index, _state.StaticSourcePartAdjustment(source_index))
        if mirrored:
            working_copy = _state._copy_source_part_with_adjustment(source, source_adjustment, mirror_x_around_bounds_center=True)
            base_copy = _state._copy_source_part_with_adjustment(working_copy, _state.StaticSourcePartAdjustment(source_submesh_index=0))
            new_adjustment = _state.StaticSourcePartAdjustment(source_submesh_index=0)
        else:
            working_copy = _state._copy_source_part_with_adjustment(source, _state.StaticSourcePartAdjustment(source_submesh_index=source_index))
            base_source = replacement_mesh_base_for_mapping.submeshes[source_index] if source_index < len(replacement_mesh_base_for_mapping.submeshes) else source
            base_copy = _state._copy_source_part_with_adjustment(base_source, _state.StaticSourcePartAdjustment(source_submesh_index=source_index))
            new_adjustment = _state.copy.deepcopy(source_adjustment)
        new_index = duplicate_route.new_index
        new_adjustment.source_submesh_index = new_index
        new_adjustment.enabled = True
        replacement_mesh_for_mapping.submeshes.append(working_copy)
        replacement_mesh_base_for_mapping.submeshes.append(base_copy)
        _state.refresh_parsed_mesh_totals(replacement_mesh_for_mapping)
        _state.refresh_parsed_mesh_totals(replacement_mesh_base_for_mapping)
        _state.source_part_adjustments[new_index] = new_adjustment
        _state.appended_source_indices.add(new_index)
        source_label = _state._source_part_display_label_helper(source_index, source, _state.source_display_overrides)
        duplicate_presentation = _state._source_part_duplicate_presentation_state_helper(existing_role=_state.source_role_overrides.get(source_index, ''), fallback_role=_state._source_role_label(source_index), source_label=source_label, copy_suffix=duplicate_route.copy_suffix)
        _state.source_role_overrides[new_index] = duplicate_presentation.role_override
        _state.source_display_overrides[new_index] = duplicate_presentation.display_override
        _state._invalidate_source_display_cache()
        if duplicate_route.output_route == 'independent':
            _state.independent_output_source_indices.add(new_index)
        elif duplicate_route.output_route == 'preview':
            _state.preview_only_source_indices.add(new_index)
        _state._add_source_tree_item(new_index, working_copy)
        _state.part_source_combo.addItem(_state._source_display_name(new_index), new_index)
        _state.source_tree.clearSelection()
        new_item = _state.source_items_by_index.get(new_index)
        if new_item is not None:
            new_item.setSelected(True)
            _state.source_tree.setCurrentItem(new_item)
        _state.selected_source_part['index'] = new_index
        _state.selected_source_highlight_indices.clear()
        _state.selected_source_highlight_indices.add(new_index)
        _state._set_transform_source_indices((new_index,))
        for target_index in mapped_targets:
            edit = _state.mapping_edits_by_target.get(target_index)
            if edit is None:
                continue
            _state._set_mapping_indices(target_index, list(_state._source_part_mapping_indices_for_target_helper(_state._parse_mapping_edit(edit), source_index=new_index, replace=False)), push_undo=False)
        _state.source_geometry_revision['value'] = int(_state.source_geometry_revision.get('value', 0) or 0) + 1
        _state.clear_mesh_history_snapshot_stack(_state.mesh_edit_redo_stack)
        _state.mesh_edit_redo_adjustment_stack.clear()
        texture_sets = _state.group_replacement_texture_sets(_state.texture_files_for_mapping, obj_mesh=replacement_mesh_for_mapping)
        _state._set_texture_sets(texture_sets)
        _state._apply_source_material_texture_overrides_to_ui_texture_sets(texture_sets)
        _state._fit_alignment_tree_height_to_rows(_state.source_tree, **_state.source_tree_layout_state.height_fit_kwargs)
        _state._refresh_source_tree_selection_state()
        _state._refresh_source_assignment_columns()
        try:
            _state._refresh_added_part_texture_tree(new_index)
        except NameError:
            pass
        try:
            _state._refresh_source_material_plan()
        except NameError:
            pass
        try:
            _state._refresh_texture_row_guidance()
            _state._refresh_texture_table(_state.selected_texture_row.get('row'))
        except NameError:
            pass
        _state._load_selected_part_controls()
        _state._source_part_refresh_geometry_preview(duplicate_route.status_text, (new_index,))
        _state.self.set_status_message(duplicate_route.status_text)
    _state._duplicate_selected_part = _duplicate_selected_part

def _source_part_mutation_step_017(_state):

    def _rollback_cancelled_appended_mesh_part_import(append_rollback_snapshot) -> bool:
        replacement_mesh_for_mapping = _state._source_part_append_restore_mesh_snapshot(append_rollback_snapshot.replacement_mesh)
        replacement_mesh_base_for_mapping = _state._source_part_append_restore_mesh_snapshot(append_rollback_snapshot.replacement_base_mesh)
        if replacement_mesh_for_mapping is None or replacement_mesh_base_for_mapping is None:
            _state.self.set_status_message('Could not restore source-part append rollback snapshot; reload the preview before continuing.', error=True)
            return False
        _state._set_replacement_mesh_for_mapping(replacement_mesh_for_mapping)
        _state._set_replacement_mesh_base_for_mapping(replacement_mesh_base_for_mapping)
        _state.appended_source_indices.clear()
        _state.appended_source_indices.update(append_rollback_snapshot.appended_source_indices)
        _state.independent_output_source_indices.clear()
        _state.independent_output_source_indices.update(append_rollback_snapshot.independent_output_source_indices)
        _state.preview_only_source_indices.clear()
        _state.preview_only_source_indices.update(append_rollback_snapshot.preview_only_source_indices)
        _state.source_role_overrides.clear()
        _state.source_role_overrides.update(append_rollback_snapshot.source_role_overrides)
        _state.source_display_overrides.clear()
        _state.source_display_overrides.update(append_rollback_snapshot.source_display_overrides)
        _state._invalidate_source_display_cache()
        _state.source_part_adjustments.clear()
        _state.source_part_adjustments.update(_state.copy.deepcopy(append_rollback_snapshot.source_part_adjustments))
        _state.dialog_added_supplemental_files[:] = list(append_rollback_snapshot.dialog_added_supplemental_files)
        _state.texture_files_for_mapping[:] = list(append_rollback_snapshot.texture_files_for_mapping)
        _state.source_material_texture_override_assignments.clear()
        _state.source_material_texture_override_assignments.update(append_rollback_snapshot.source_material_texture_override_assignments)
        _state.replace_mesh_history_snapshot_stack(_state.mesh_edit_redo_stack, append_rollback_snapshot.mesh_edit_redo_stack)
        _state.mesh_edit_redo_adjustment_stack[:] = _state.copy.deepcopy(append_rollback_snapshot.mesh_edit_redo_adjustment_stack)
        _state.source_geometry_revision['value'] = append_rollback_snapshot.source_geometry_revision
        _state.selected_source_part['index'] = append_rollback_snapshot.selected_source_index
        _state.selected_target_slot['index'] = append_rollback_snapshot.selected_target_index
        _state.selected_original_part['index'] = append_rollback_snapshot.selected_original_index
        _state.selected_source_highlight_indices.clear()
        _state.selected_source_highlight_indices.update(append_rollback_snapshot.selected_source_highlights)
        _state.transform_source_indices.clear()
        _state.transform_source_indices.update(append_rollback_snapshot.transform_source_indices)
        _state.selected_target_source_highlight_indices.clear()
        _state.selected_target_source_highlight_indices.update(append_rollback_snapshot.selected_target_source_highlights)
        _state.selected_original_highlight_indices.clear()
        _state.selected_original_highlight_indices.update(append_rollback_snapshot.selected_original_highlights)
        _state.selected_target_original_highlight_indices.clear()
        _state.selected_target_original_highlight_indices.update(append_rollback_snapshot.selected_target_original_highlights)
        _state._rebuild_source_part_widgets(append_rollback_snapshot.selected_source_indices, current_index=append_rollback_snapshot.selected_source_index)
        _state._sync_highlight_sets()
        _state._refresh_original_reference_preview()
        texture_sets = _state.group_replacement_texture_sets(_state.texture_files_for_mapping, obj_mesh=replacement_mesh_for_mapping)
        _state._set_texture_sets(texture_sets)
        _state._apply_source_material_texture_overrides_to_ui_texture_sets(texture_sets)
        _state._refresh_source_assignment_columns()
        try:
            _state._refresh_source_material_plan()
        except NameError:
            pass
        try:
            _state._refresh_texture_row_guidance()
            _state._refresh_texture_table(_state.selected_texture_row.get('row'))
        except NameError:
            pass
        _state._load_selected_part_controls()
        _state._source_part_refresh_geometry_preview('cancelled mesh part import', replace_all=True)
        return True
    _state._rollback_cancelled_appended_mesh_part_import = _rollback_cancelled_appended_mesh_part_import

STEPS = (
    _source_part_mutation_step_001,
    _source_part_mutation_step_002,
    _source_part_mutation_step_003,
    _source_part_mutation_step_004,
    _source_part_mutation_step_005,
    _source_part_mutation_step_006,
    _source_part_mutation_step_007,
    _source_part_mutation_step_008,
    _source_part_mutation_step_009,
    _source_part_mutation_step_010,
    _source_part_mutation_step_011,
    _source_part_mutation_step_012,
    _source_part_mutation_step_013,
    _source_part_mutation_step_014,
    _source_part_mutation_step_015,
    _source_part_mutation_step_016,
    _source_part_mutation_step_017,
)
