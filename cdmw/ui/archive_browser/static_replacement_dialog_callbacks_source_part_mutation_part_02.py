from __future__ import annotations

def _source_part_mutation_step_018(_state):

    def _append_mesh_part_to_geometry(imported_source_path: object=None, imported_scene_result: object=None) -> None:
        replacement_mesh_for_mapping = _state._get_replacement_mesh_for_mapping()
        replacement_mesh_base_for_mapping = _state._get_replacement_mesh_base_for_mapping()
        if replacement_mesh_for_mapping is None or replacement_mesh_base_for_mapping is None:
            return
        if _state._source_part_active_geometry_mutation_blocked():
            return
        if not isinstance(imported_source_path, _state.Path) or imported_scene_result is None:
            source_part_append_mesh_file_dialog_text = _state._source_part_append_mesh_file_dialog_text_helper()
            selected_path, _selected_filter = _state.QFileDialog.getOpenFileName(_state.dialog, source_part_append_mesh_file_dialog_text['title'], str(_state.self._suggest_workspace_base_dir()), source_part_append_mesh_file_dialog_text['mesh_filter'])
            if not selected_path:
                return
            source_path = _state.Path(selected_path).expanduser()
            append_file_route = _state._source_part_append_file_route_state_helper(source_path, allowed_extensions=_state.SCENE_IMPORT_EXTENSIONS)
            if append_file_route.route == 'fbx_deferred':
                _state.QMessageBox.information(_state.dialog, source_part_append_mesh_file_dialog_text['fbx_title'], source_part_append_mesh_file_dialog_text['fbx_message'])
                return
            if append_file_route.route == 'unsupported':
                _state.QMessageBox.warning(_state.dialog, source_part_append_mesh_file_dialog_text['unsupported_title'], _state._source_part_unsupported_mesh_part_message_helper(source_path.name))
                return

            def _scene_imported(result: object) -> None:
                if not isinstance(result, _state.SceneImportTaskResult):
                    _state.QMessageBox.warning(_state.dialog, _state._source_part_add_mesh_part_failed_title_helper(), 'Scene import returned an unexpected result.')
                    return
                _state._append_mesh_part_to_geometry(result.source_path, result.scene)
            started = _state.source_task_controller.start(_state.SceneImportRequest(source_path=source_path), _state.run_scene_import, status_message=f'Importing mesh part: {source_path.name}...', on_complete=_scene_imported, on_error=lambda message: _state.QMessageBox.warning(_state.dialog, _state._source_part_add_mesh_part_failed_title_helper(), message), on_idle=lambda: _state.append_mesh_part_button.setEnabled(True))
            if started:
                _state.append_mesh_part_button.setEnabled(False)
            return
        source_path = imported_source_path
        rollback_replacement_mesh = _state._source_part_append_capture_mesh_snapshot(replacement_mesh_for_mapping, 'source_part.append_rollback_working_mesh')
        rollback_replacement_base_mesh = _state._source_part_append_capture_mesh_snapshot(replacement_mesh_base_for_mapping, 'source_part.append_rollback_base_mesh')
        if rollback_replacement_mesh is None or rollback_replacement_base_mesh is None:
            _state.release_native_submesh_snapshot(rollback_replacement_mesh)
            _state.release_native_submesh_snapshot(rollback_replacement_base_mesh)
            return
        append_rollback_snapshot = _state._source_part_append_rollback_snapshot_helper(replacement_mesh=rollback_replacement_mesh, replacement_base_mesh=rollback_replacement_base_mesh, appended_source_indices=_state.appended_source_indices, independent_output_source_indices=_state.independent_output_source_indices, preview_only_source_indices=_state.preview_only_source_indices, source_role_overrides=_state.source_role_overrides, source_display_overrides=_state.source_display_overrides, source_part_adjustments=_state.source_part_adjustments, dialog_added_supplemental_files=_state.dialog_added_supplemental_files, texture_files_for_mapping=_state.texture_files_for_mapping, source_material_texture_override_assignments=_state.source_material_texture_override_assignments, mesh_edit_redo_stack=_state.mesh_edit_redo_stack, mesh_edit_redo_adjustment_stack=_state.mesh_edit_redo_adjustment_stack, source_geometry_revision=_state.source_geometry_revision.get('value', 0), selected_source_index=_state.selected_source_part.get('index', -1), selected_source_indices=_state._selected_source_indices_from_tree(), selected_target_index=_state.selected_target_slot.get('index', -1), selected_original_index=_state.selected_original_part.get('index', -1), selected_source_highlights=_state.selected_source_highlight_indices, selected_target_source_highlights=_state.selected_target_source_highlight_indices, transform_source_indices=_state.transform_source_indices, selected_original_highlights=_state.selected_original_highlight_indices, selected_target_original_highlights=_state.selected_target_original_highlight_indices)
        append_undo_pushed = False
        try:
            append_scene_result = imported_scene_result
            append_scene_result = _state._maybe_flatten_scene_import_parts(source_path, append_scene_result)
            if append_scene_result is None:
                _state._source_part_append_release_rollback_snapshots(append_rollback_snapshot)
                return
            append_scene_result = _state._maybe_reduce_high_density_scene_import(source_path, append_scene_result)
            if append_scene_result is None:
                _state._source_part_append_release_rollback_snapshots(append_rollback_snapshot)
                return
            _state._push_geometry_undo_snapshot('Add mesh part')
            append_undo_pushed = True
            append_result = _state.append_scene_import_to_mesh(replacement_mesh_for_mapping, replacement_mesh_base_for_mapping, append_scene_result, source_path=source_path, label_prefix=source_path.stem)
        except Exception as exc:
            if append_undo_pushed:
                _state._pop_geometry_undo_snapshot()
            _state._source_part_append_release_rollback_snapshots(append_rollback_snapshot)
            _state.QMessageBox.warning(_state.dialog, _state._source_part_add_mesh_part_failed_title_helper(), str(exc))
            return
        placement_note = _state._normalize_appended_part_to_work_area(append_result.source_indices)
        append_imported_state = _state._source_part_append_imported_state_helper(source_indices=append_result.source_indices, sources=replacement_mesh_for_mapping.submeshes, source_stem=source_path.stem, appended_source_indices=_state.appended_source_indices, independent_output_source_indices=_state.independent_output_source_indices, preview_only_source_indices=_state.preview_only_source_indices)
        _state.appended_source_indices.clear()
        _state.appended_source_indices.update(append_imported_state.index_state.appended_source_indices)
        _state.independent_output_source_indices.clear()
        _state.independent_output_source_indices.update(append_imported_state.index_state.independent_output_source_indices)
        _state.preview_only_source_indices.clear()
        _state.preview_only_source_indices.update(append_imported_state.index_state.preview_only_source_indices)
        for supplemental_path in tuple(append_result.supplemental_files or ()):
            if isinstance(supplemental_path, _state.Path):
                _state._add_dialog_supplemental_file(supplemental_path)
        for presentation in append_imported_state.presentations:
            source = replacement_mesh_for_mapping.submeshes[presentation.source_index]
            _state.source_display_overrides[presentation.source_index] = presentation.display_override
            _state.source_role_overrides[presentation.source_index] = _state._mapping_role_hint(presentation.role_hint_text)
            _state._add_source_tree_item(presentation.source_index, source)
            _state.part_source_combo.addItem(_state._source_display_name(presentation.source_index), presentation.source_index)
        _state._invalidate_source_display_cache()
        _state.source_geometry_revision['value'] = int(_state.source_geometry_revision.get('value', 0) or 0) + 1
        _state.clear_mesh_history_snapshot_stack(_state.mesh_edit_redo_stack)
        _state.mesh_edit_redo_adjustment_stack.clear()
        texture_sets = _state.group_replacement_texture_sets(_state.texture_files_for_mapping, obj_mesh=replacement_mesh_for_mapping)
        _state._set_texture_sets(texture_sets)
        _state._apply_source_material_texture_overrides_to_ui_texture_sets(texture_sets)
        if callable(_state._texture_set_for_source_index) and callable(_state._source_part_append_texture_control_state_helper):
            appended_texture_sets = [_state._texture_set_for_source_index(int(source_index), texture_sets) for source_index in tuple(append_result.source_indices or ())]
            append_texture_control_state = _state._source_part_append_texture_control_state_helper(has_texture_files=bool(append_result.texture_files), texture_sets=tuple(appended_texture_sets))
            if append_texture_control_state.enable_rebuild_sidecar:
                rebuild_sidecar_checkbox = _state.rebuild_sidecar_checkbox
                if callable(rebuild_sidecar_checkbox) and not callable(getattr(rebuild_sidecar_checkbox, 'setChecked', None)):
                    rebuild_sidecar_checkbox = rebuild_sidecar_checkbox()
                set_checked = getattr(rebuild_sidecar_checkbox, 'setChecked', None)
                if callable(set_checked):
                    set_checked(True)
            if append_texture_control_state.enable_inject_base_color:
                inject_base_color_checkbox = _state.inject_base_color_checkbox
                if callable(inject_base_color_checkbox) and not callable(getattr(inject_base_color_checkbox, 'setChecked', None)):
                    inject_base_color_checkbox = inject_base_color_checkbox()
                set_checked = getattr(inject_base_color_checkbox, 'setChecked', None)
                if callable(set_checked):
                    set_checked(True)
        _state.source_tree.clearSelection()
        for source_index in append_result.source_indices:
            item = _state.source_items_by_index.get(int(source_index))
            if item is not None:
                item.setSelected(True)
                _state.source_tree.setCurrentItem(item)
        if append_imported_state.first_source_index >= 0:
            _state.selected_source_part['index'] = append_imported_state.first_source_index
        _state._fit_alignment_tree_height_to_rows(_state.source_tree, **_state.source_tree_layout_state.height_fit_kwargs)
        _state._refresh_source_tree_selection_state()
        _state._refresh_source_assignment_columns()
        if callable(_state._refresh_source_material_plan):
            _state._refresh_source_material_plan()
        if callable(_state._refresh_texture_row_guidance):
            _state._refresh_texture_row_guidance()
        if callable(_state._refresh_texture_table):
            selected_texture_row = _state.selected_texture_row if isinstance(_state.selected_texture_row, dict) else {}
            _state._refresh_texture_table(selected_texture_row.get('row'))
        _state._load_selected_part_controls()
        _state._source_part_refresh_geometry_preview(_state._source_part_added_mesh_part_status_helper(source_path.name, placement_note), append_result.source_indices)
        assignment_action = _state._prompt_assign_appended_mesh_parts(source_path, append_result.source_indices, placement_note=placement_note, discovered_texture_files=tuple(append_scene_result.discovered_texture_files or ()))
        if assignment_action == 'cancel':
            try:
                if _state._rollback_cancelled_appended_mesh_part_import(append_rollback_snapshot):
                    _state._pop_geometry_undo_snapshot()
                    _state.self.set_status_message(_state._source_part_cancel_import_status_helper(source_path.name))
                return
            finally:
                _state._source_part_append_release_rollback_snapshots(append_rollback_snapshot)
        _state._refresh_source_assignment_columns()
        if callable(_state._refresh_added_part_texture_tree):
            _state._refresh_added_part_texture_tree(int(append_result.source_indices[0]) if append_result.source_indices else None)
        if callable(_state._refresh_source_material_plan):
            _state._refresh_source_material_plan()
        _state._source_part_refresh_geometry_preview(_state._source_part_added_mesh_part_status_helper(source_path.name, placement_note), append_result.source_indices)
        _state._source_part_append_release_rollback_snapshots(append_rollback_snapshot)
        _state.self.set_status_message(_state._source_part_added_mesh_part_status_helper(source_path.name, placement_note))
    _state._append_mesh_part_to_geometry = _append_mesh_part_to_geometry

def _source_part_mutation_step_019(_state):
    _state._factory_result_values.update({'_delete_selected_source_parts': _state._delete_selected_source_parts, '_apply_source_part_preview_changes': _state._apply_source_part_preview_changes, '_apply_source_material_grouped_routing': _state._apply_source_material_grouped_routing, '_duplicate_selected_part': _state._duplicate_selected_part, '_append_mesh_part_to_geometry': _state._append_mesh_part_to_geometry})

STEPS = (
    _source_part_mutation_step_018,
    _source_part_mutation_step_019,
)
