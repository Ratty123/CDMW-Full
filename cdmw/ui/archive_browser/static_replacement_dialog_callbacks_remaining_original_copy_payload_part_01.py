from __future__ import annotations

def _remaining_original_copy_payload_step_001(_state):
    _state.state = _state._StaticReplacementDialogState(_state.context)
    _state.Mapping = _state.context.get('Mapping')
    _state.QBrush = _state.context.get('QBrush')
    _state.QColor = _state.context.get('QColor')
    _state.QMessageBox = _state.context.get('QMessageBox')
    _state._add_source_tree_item = _state.context.get('_add_source_tree_item')
    _state._appended_original_copy_column_text_helper = _state.context.get('_appended_original_copy_column_text_helper')
    _state._auto_fit_alignment_tree_columns = _state.context.get('_auto_fit_alignment_tree_columns')
    _state._copied_original_dds_badge = _state.context.get('_copied_original_dds_badge')
    _state._copied_original_dds_cell_text_helper = _state.context.get('_copied_original_dds_cell_text_helper')
    _state._copied_original_part_source_helper = _state.context.get('_copied_original_part_source_helper')
    _state._copied_original_physics_status_message_helper = _state.context.get('_copied_original_physics_status_message_helper')
    _state._copied_original_texture_tooltip = _state.context.get('_copied_original_texture_tooltip')
    _state._fit_alignment_tree_height_to_rows = _state.context.get('_fit_alignment_tree_height_to_rows')
    _state._invalidate_source_display_cache = _state.context.get('_invalidate_source_display_cache')
    _state._load_selected_part_controls = _state.context.get('_load_selected_part_controls')
    _state._mapping_indices_with_appended_source_helper = _state.context.get('_mapping_indices_with_appended_source_helper')
    _state._missing_copied_original_part_message_helper = _state.context.get('_missing_copied_original_part_message_helper')
    _state._original_target_label = _state.context.get('_original_target_label')
    _state._parse_mapping_edit = _state.context.get('_parse_mapping_edit')
    _state._push_geometry_undo_snapshot = _state.context.get('_push_geometry_undo_snapshot')
    _state._queue_static_preview_rebuild = _state.context.get('_queue_static_preview_rebuild')
    _state._refresh_added_part_texture_tree = _state.context.get('_refresh_added_part_texture_tree')
    _state._refresh_parts_outliner = _state.context.get('_refresh_parts_outliner')
    _state._refresh_source_assignment_columns = _state.context.get('_refresh_source_assignment_columns')
    _state._refresh_source_material_plan = _state.context.get('_refresh_source_material_plan')
    _state._selected_target_index = _state.context.get('_selected_target_index')
    _state._set_mapping_indices = _state.context.get('_set_mapping_indices')
    _state._set_transform_source_indices = _state.context.get('_set_transform_source_indices')
    _state._alignment_d3d11_preview_active = _state.context.get('_alignment_d3d11_preview_active')
    _state._alignment_mesh_edit_tab_active = _state.context.get('_alignment_mesh_edit_tab_active')
    _state._source_assigned_target_indices_helper = _state.context.get('_source_assigned_target_indices_helper')
    _state._source_display_name = _state.context.get('_source_display_name')
    _state._source_outliner_state = _state.context.get('_source_outliner_state')
    _state.appended_source_indices = _state.context.get('appended_source_indices')
    _state.assign_to_target = _state.context.get('assign_to_target')
    _state.copied_item = _state.context.get('copied_item')
    _state.copied_original_physics_sensitive_sources = _state.context.get('copied_original_physics_sensitive_sources')
    _state.copied_original_source_indices = _state.context.get('copied_original_source_indices')
    _state.copied_original_source_to_original_index = _state.context.get('copied_original_source_to_original_index')
    _state.copied_original_texture_disabled_sources = _state.context.get('copied_original_texture_disabled_sources')
    _state.copied_original_texture_intents_by_source = _state.context.get('copied_original_texture_intents_by_source')
    _state.copied_part = _state.context.get('copied_part')
    _state.copied_source = _state.context.get('copied_source')
    _state.copy = _state.context.get('copy')
    _state.dialog = _state.context.get('dialog')
    _state.disabled = _state.context.get('disabled')
    _state.edit = _state.context.get('edit')
    _state.group_replacement_texture_sets = _state.context.get('group_replacement_texture_sets')
    _state.mapping_edits = _state.context.get('mapping_edits')
    _state.mapping_edits_by_target = _state.context.get('mapping_edits_by_target')
    _state.message = _state.context.get('message')
    _state.new_source_index = _state.context.get('new_source_index')
    _state.original_index = _state.context.get('original_index')
    _state.original_item = _state.context.get('original_item')
    _state.original_items_by_index = _state.context.get('original_items_by_index')
    _state.original_mesh_for_mapping = _state.context.get('original_mesh_for_mapping')
    _state.parsed_mesh_to_preview_model = _state.context.get('parsed_mesh_to_preview_model')
    _state.part_source_combo = _state.context.get('part_source_combo')
    _state.payload = _state.context.get('payload')
    _state.preview_only = _state.context.get('preview_only')
    _state.preview_only_source_indices = _state.context.get('preview_only_source_indices')
    _state.previous = _state.context.get('previous')
    _state.refresh_parsed_mesh_totals = _state.context.get('refresh_parsed_mesh_totals')
    _state.role_value = _state.context.get('role_value')
    _state.selected_source_highlight_indices = _state.context.get('selected_source_highlight_indices')
    _state.selected_source_part = _state.context.get('selected_source_part')
    _state.self = _state.context.get('self')
    _state.source_display_overrides = _state.context.get('source_display_overrides')
    _state.source_geometry_revision = _state.context.get('source_geometry_revision')
    _state.source_index = _state.context.get('source_index')
    _state.source_item = _state.context.get('source_item')
    _state.source_items_by_index = _state.context.get('source_items_by_index')
    _state.source_role_overrides = _state.context.get('source_role_overrides')
    _state.source_tree = _state.context.get('source_tree')
    _state.source_tree_layout_state = _state.context.get('source_tree_layout_state')
    _state.state_text = _state.context.get('state_text')
    _state.static_preview_geometry_cache = _state.context.get('static_preview_geometry_cache')
    _state.static_preview_prepared_cache = _state.context.get('static_preview_prepared_cache')
    _state.target_index = _state.context.get('target_index')
    _state.texture_files_for_mapping = _state.context.get('texture_files_for_mapping') or []
    _state.texture_rows = _state.context.get('texture_rows')
    _state.title = _state.context.get('title')
    _state.undo_label = _state.context.get('undo_label')
    _state.prompt_shell_context = _state.context.get('prompt_shell_context')

def _remaining_original_copy_payload_step_002(_state):

    def _copied_original_live_triangle_replacer() -> object:
        replacer = _state.context.get('_mesh_edit_replace_live_triangles_or_queue_rebuild')
        if callable(replacer):
            return replacer
        if isinstance(_state.prompt_shell_context, dict):
            replacer = _state.prompt_shell_context.get('_mesh_edit_replace_live_triangles_or_queue_rebuild')
            if callable(replacer):
                return replacer
        return None
    _state._copied_original_live_triangle_replacer = _copied_original_live_triangle_replacer

def _remaining_original_copy_payload_step_003(_state):

    def _copied_original_mesh_edit_active() -> bool:
        if not callable(_state._alignment_mesh_edit_tab_active):
            return False
        return bool(_state._alignment_mesh_edit_tab_active())
    _state._copied_original_mesh_edit_active = _copied_original_mesh_edit_active

def _remaining_original_copy_payload_step_004(_state):

    def _refresh_copied_original_source_preview(source_index: int) -> None:
        _state.static_preview_geometry_cache.clear()
        _state.static_preview_prepared_cache.clear()
        if callable(_state._alignment_d3d11_preview_active) and _state._alignment_d3d11_preview_active():
            replacer = _state._copied_original_live_triangle_replacer()
            if callable(replacer):
                replacer((int(source_index),))
                return
            _state.self.set_status_message('.NET/Vortice copied-source preview commands are unavailable; preview is stale. Retry .NET/Vortice Preview to resync.', error=True)
            return
        if _state._copied_original_mesh_edit_active():
            _state.self.set_status_message('Active Mesh Editor copied-source preview requires .NET/Vortice refresh; Python preview rebuild fallback is disabled.', error=True)
            return
        _state.state.replacement_preview_model = _state.parsed_mesh_to_preview_model(_state.state.replacement_mesh_for_mapping)
        _state._queue_static_preview_rebuild()
    _state._refresh_copied_original_source_preview = _refresh_copied_original_source_preview

def _remaining_original_copy_payload_step_005(_state):

    def _refresh_copied_original_texture_ui(source_index: int=-1) -> None:
        source_item = _state.source_items_by_index.get(int(source_index))
        if source_item is not None and int(source_index) in _state.copied_original_texture_intents_by_source:
            disabled = int(source_index) in _state.copied_original_texture_disabled_sources
            state_text, _state_color = _state._source_outliner_state(int(source_index), _state._source_assigned_target_indices_helper(int(source_index), _state.mapping_edits, parse_mapping_edit=_state._parse_mapping_edit))
            source_item.setText(5, _state._copied_original_dds_cell_text_helper(state_text, disabled=disabled, copied_badge=_state._copied_original_dds_badge(int(source_index))))
            source_item.setForeground(5, _state.QBrush(_state.QColor('#d29922' if disabled else '#3fb950')))
            source_item.setToolTip(5, _state._copied_original_texture_tooltip(int(source_index)))
        try:
            _state._refresh_source_assignment_columns(lightweight=True)
        except NameError:
            pass
        try:
            _state._refresh_parts_outliner()
        except NameError:
            pass
        try:
            _state._refresh_source_material_plan(force=True)
        except NameError:
            pass
        try:
            _state._refresh_added_part_texture_tree(int(source_index))
        except NameError:
            pass
    _state._refresh_copied_original_texture_ui = _refresh_copied_original_texture_ui

def _remaining_original_copy_payload_step_006(_state):

    def _append_original_part_payload_as_source(payload: Mapping[str, object], *, assign_to_target: bool, preview_only: bool, undo_label: str) -> int:
        if _state.original_mesh_for_mapping is None or _state.state.replacement_mesh_for_mapping is None:
            return -1
        try:
            original_index = int(payload.get('original_submesh_index', -1))
        except (TypeError, ValueError):
            original_index = -1
        copied_source = payload.get('submesh')
        if original_index < 0 or original_index >= len(_state.original_mesh_for_mapping.submeshes) or copied_source is None:
            title, message = _state._missing_copied_original_part_message_helper()
            _state.QMessageBox.information(_state.dialog, title, message)
            return -1
        if _state._copied_original_mesh_edit_active():
            _state.self.set_status_message('Active Mesh Editor copied-original append requires native geometry execution; Python mesh mutation fallback is disabled.', error=True)
            return -1
        _state._push_geometry_undo_snapshot(undo_label)
        copied_part = _state._copied_original_part_source_helper(copied_source, payload, original_index, _state._original_target_label(original_index), undo_label.startswith('Paste'))
        new_source_index = len(_state.state.replacement_mesh_for_mapping.submeshes)
        _state.state.replacement_mesh_for_mapping.submeshes.append(copied_part)
        _state.refresh_parsed_mesh_totals(_state.state.replacement_mesh_for_mapping)
        _state.source_geometry_revision['value'] = int(_state.source_geometry_revision.get('value', 0) or 0) + 1
        _state.static_preview_geometry_cache.clear()
        _state.static_preview_prepared_cache.clear()
        role_value = str(payload.get('role', '') or '').strip()
        if role_value:
            _state.source_role_overrides[new_source_index] = role_value
        _state.source_display_overrides[new_source_index] = copied_part.name
        _state._invalidate_source_display_cache()
        _state.copied_original_source_indices.add(new_source_index)
        _state.copied_original_source_to_original_index[new_source_index] = original_index
        _state.appended_source_indices.add(new_source_index)
        if str(payload.get('physics_review_reason', '') or '').strip():
            _state.copied_original_physics_sensitive_sources.add(new_source_index)
        if preview_only and (not assign_to_target):
            _state.preview_only_source_indices.add(new_source_index)
        texture_rows = _state.copy.deepcopy(payload.get('texture_rows', []) or [])
        if texture_rows:
            _state.copied_original_texture_intents_by_source[new_source_index] = texture_rows
            _state.copied_original_texture_disabled_sources.discard(new_source_index)
        original_item = _state.original_items_by_index.get(original_index)
        if original_item is not None:
            previous = original_item.text(4)
            original_item.setText(4, _state._appended_original_copy_column_text_helper(previous, new_source_index))
        _state._add_source_tree_item(new_source_index, copied_part)
        try:
            _state.part_source_combo.addItem(_state._source_display_name(new_source_index), new_source_index)
        except NameError:
            pass
        _state._fit_alignment_tree_height_to_rows(_state.source_tree, **_state.source_tree_layout_state.height_fit_kwargs)
        _state.source_tree.clearSelection()
        copied_item = _state.source_items_by_index.get(new_source_index)
        if copied_item is not None:
            copied_item.setSelected(True)
            _state.source_tree.setCurrentItem(copied_item)
        _state.selected_source_part['index'] = new_source_index
        _state.selected_source_highlight_indices.clear()
        _state.selected_source_highlight_indices.add(new_source_index)
        _state._set_transform_source_indices((new_source_index,))
        target_index = _state._selected_target_index()
        if assign_to_target and target_index >= 0:
            edit = _state.mapping_edits_by_target.get(target_index)
            if edit is not None:
                _state._set_mapping_indices(target_index, _state._mapping_indices_with_appended_source_helper(edit.text(), new_source_index), push_undo=False)
        _state.state.texture_sets = _state.group_replacement_texture_sets(_state.texture_files_for_mapping, obj_mesh=_state.state.replacement_mesh_for_mapping)
        _state._refresh_copied_original_texture_ui(new_source_index)
        _state._auto_fit_alignment_tree_columns(_state.source_tree, _state.source_tree_layout_state.autofit_min_widths, _state.source_tree_layout_state.autofit_max_widths, expand_columns=_state.source_tree_layout_state.expand_columns)
        _state._refresh_source_assignment_columns()
        _state._load_selected_part_controls()
        _state._refresh_copied_original_source_preview(new_source_index)
        if int(new_source_index) in _state.copied_original_physics_sensitive_sources:
            _state.self.set_status_message(_state._copied_original_physics_status_message_helper())
        return new_source_index
    _state._append_original_part_payload_as_source = _append_original_part_payload_as_source

def _remaining_original_copy_payload_step_007(_state):
    _state._factory_result_values.update({'_refresh_copied_original_texture_ui': _state._refresh_copied_original_texture_ui, '_append_original_part_payload_as_source': _state._append_original_part_payload_as_source})

STEPS = (
    _remaining_original_copy_payload_step_001,
    _remaining_original_copy_payload_step_002,
    _remaining_original_copy_payload_step_003,
    _remaining_original_copy_payload_step_004,
    _remaining_original_copy_payload_step_005,
    _remaining_original_copy_payload_step_006,
    _remaining_original_copy_payload_step_007,
)
