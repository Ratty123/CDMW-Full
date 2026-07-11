from __future__ import annotations

def _parts_outliner_mapping_step_029(_state):

    def _clear_all_mapping_guesses() -> None:
        _state._push_geometry_undo_snapshot('Clear all routing guesses')
        for _target_index, edit in _state.mapping_edits:
            edit.setText('')
    _state._clear_all_mapping_guesses = _clear_all_mapping_guesses

def _parts_outliner_mapping_step_030(_state):

    def _apply_best_mapping_guesses() -> None:
        _state._push_geometry_undo_snapshot('Apply best routing guesses')
        for target_index, edit in _state.mapping_edits:
            edit.setText(_state.initial_mapping_text_by_target.get(target_index, ''))
    _state._apply_best_mapping_guesses = _apply_best_mapping_guesses

def _parts_outliner_mapping_step_031(_state):

    def _preview_selected_target_slot() -> None:
        item = _state.mapping_tree.currentItem()
        if item is not None:
            _state._target_selection_changed(item, None)
        _state._queue_static_preview_refresh()
    _state._preview_selected_target_slot = _preview_selected_target_slot

def _parts_outliner_mapping_step_032(_state):
    _state._selected_source_index = lambda: _state._tree_item_source_index_or_fallback_helper(_state.source_tree.currentItem(), int(_state.selected_source_part.get('index', -1)))
    _state._selected_target_index = lambda: _state._tree_item_target_index_or_fallback_helper(_state.mapping_tree.currentItem(), int(_state.selected_target_slot.get('index', -1)))
    _state._parse_mapping_edit = lambda edit: list(_state._mapping_edit_indices_helper(edit))
    _state._texture_set_for_source_index = lambda source_index, texture_sets_by_key: _state._texture_set_for_source_index_helper(source_index, _state.replacement_mesh_for_mapping, texture_sets_by_key)
    _state._source_material_group_label = lambda source_index, texture_sets_by_key: _state._source_material_group_label_helper(source_index, _state.replacement_mesh_for_mapping, texture_sets_by_key, _state.source_part_adjustments)
    _state._mapped_target_vertex_count = lambda source_indices: _state._mapped_target_vertex_count_helper(source_indices, _state.replacement_mesh_for_mapping, _state.source_part_adjustments, default_adjustment=_state.StaticSourcePartAdjustment, is_marker_source=_state._is_marker_source)
    _state._mapped_source_vertex_counts = lambda source_indices: list(_state._mapped_source_vertex_counts_helper(source_indices, _state.replacement_mesh_for_mapping, _state.source_part_adjustments, default_adjustment=_state.StaticSourcePartAdjustment, is_marker_source=_state._is_marker_source))
    _state._mapping_preserve_split_group_count = lambda source_indices: _state._mapping_preserve_split_group_count_helper(_state._mapped_source_vertex_counts(source_indices), _state.static_replacement_vertex_limit, source_display_name=_state._source_display_name)
    _state._mapping_vertex_limit_issues = lambda mappings: list(_state._mapping_vertex_limit_issues_helper(mappings, original_format=str(getattr(_state.original_mesh_for_mapping, 'format', '') or ''), vertex_limit=_state.static_replacement_vertex_limit, target_display_name=_state._target_display_name, mapped_target_vertex_count=_state._mapped_target_vertex_count, preserve_split_group_count=_state._mapping_preserve_split_group_count))
    _state._routing_source_material_labels = lambda source_indices: list(_state._routing_source_material_labels_helper(source_indices, _state.replacement_mesh_for_mapping, _state.texture_sets))
    _state._routing_effect_lines = lambda target_index, source_indices, *, selection_ok, selection_summary: list(_state._routing_effect_lines_helper(target_index, source_indices, selection_ok=selection_ok, selection_summary=selection_summary, target_display_name=_state._target_display_name, source_display_name=_state._source_display_name, source_material_labels=_state._routing_source_material_labels))

def _parts_outliner_mapping_step_033(_state):

    def _set_advanced_mapping_visible(checked: bool) -> None:
        visibility_state = _state._mapping_table_advanced_visibility_state_helper(checked)
        _state.original_parts_label.setVisible(True)
        _state.original_tree.setVisible(True)
        _state.original_button_panel.setVisible(True)
        _state.source_parts_group.setVisible(True)
        for mapping_action_button in (_state.clear_all_guesses_button, _state.apply_best_guesses_button, _state.group_materials_button, _state.preview_target_button):
            mapping_action_button.setVisible(visibility_state.visible_widgets)
        _state.mapping_tree.setVisible(visibility_state.visible_widgets)
        _state.target_slots_label.setVisible(visibility_state.visible_widgets)
        _state.mapping_progress_label.setVisible(visibility_state.visible_widgets)
        for column, hidden in visibility_state.hidden_columns:
            _state.mapping_tree.setColumnHidden(column, hidden)
        if visibility_state.expand_part_tools:
            _state.mapping_tree.setColumnWidth(2, max(118, _state.mapping_tree.columnWidth(2)))
            _state.mapping_tree.setHorizontalScrollBarPolicy(_state.Qt.ScrollBarAlwaysOff)
            try:
                _state.advanced_part_tools_section.set_expanded(True)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        else:
            _state.mapping_tree.setHorizontalScrollBarPolicy(_state.Qt.ScrollBarAlwaysOff)
        _state.mapping_tree.doItemsLayout()
        _state.QTimer.singleShot(0, _state.mapping_tree.doItemsLayout)
        _state.QTimer.singleShot(0, lambda: _state._fit_alignment_tree_height_to_rows(_state.mapping_tree, **_state._mapping_table_height_fit_kwargs_helper()))
        _state.QTimer.singleShot(0, lambda: _state._auto_fit_alignment_tree_columns(_state.mapping_tree, _state._mapping_table_column_min_widths_helper(), _state._mapping_table_column_max_widths_helper(), expand_columns=_state._mapping_table_expand_columns_helper()))
    _state._set_advanced_mapping_visible = _set_advanced_mapping_visible

def _parts_outliner_mapping_step_034(_state):

    def _update_mapping_status() -> None:
        source_index = _state._selected_source_index()
        target_index = _state._selected_target_index()
        source_text = _state._source_display_name(source_index) if source_index >= 0 else 'no source selected'
        target_text = _state._target_display_name(target_index) if target_index >= 0 else 'no target selected'
        status_lines = list(_state._mapping_status_selection_lines_helper(source_text, target_text))
        edit = _state.mapping_edits_by_target.get(target_index)
        if edit is not None:
            summary, ok = _state._selected_source_summary(edit.text())
            source_indices = _state._parse_mapping_edit(edit)
            status_lines.append(_state._mapping_status_current_target_line_helper(summary, selection_ok=ok))
            status_lines.extend(_state._routing_effect_lines(target_index, source_indices, selection_ok=ok, selection_summary=summary))
            vertex_count = _state._mapped_target_vertex_count(source_indices)
            if vertex_count > _state.static_replacement_vertex_limit:
                split_count, split_error = _state._mapping_preserve_split_group_count(source_indices)
                limit_line = _state._mapping_vertex_limit_status_line_helper(vertex_count, split_count=split_count, split_error=split_error, original_format=str(getattr(_state.original_mesh_for_mapping, 'format', '') or ''), vertex_limit=_state.static_replacement_vertex_limit)
                if limit_line:
                    status_lines.append(limit_line)
        else:
            status_lines.extend(_state._routing_effect_lines(target_index, (), selection_ok=True, selection_summary=''))
        dds_text = '-'
        target_physics_text = '-'
        source_physics_text = '-'
        source_indices_for_target: _state.List[int] = []
        if edit is not None:
            source_indices_for_target = _state._parse_mapping_edit(edit)
            if _state.original_mesh_for_mapping is not None and 0 <= target_index < len(_state.original_mesh_for_mapping.submeshes):
                target = _state.original_mesh_for_mapping.submeshes[target_index]
                target_label_text = str(getattr(target, 'material', '') or getattr(target, 'name', '') or target_text)
                dds_text = _state._removed_target_dds_cell_text(target_label_text) if not source_indices_for_target else _state._target_texture_status_text(target_label_text)
                target_physics_text = _state._target_physics_status_text(target_label_text, target)
        elif source_index >= 0:
            dds_text = _state._source_outliner_dds_text(source_index)
        action_state = _state._mapping_status_action_state_helper(has_target_edit=edit is not None, source_index=source_index, source_indices_for_target=source_indices_for_target, preview_only_source_indices=_state.preview_only_source_indices)
        if source_index >= 0:
            source_physics_text = _state._source_physics_status_text(source_index, target_index)
        physics_state = _state._mapping_status_physics_state_helper(target_index=target_index, source_indices_for_target=source_indices_for_target, target_physics_text=target_physics_text, source_physics_text=source_physics_text)
        _state.mapping_status_label.setText(_state._mapping_status_summary_html_helper(_state._mapping_status_summary_badges_helper(source_text=source_text, target_text=target_text, action_text=action_state['text'], action_color=action_state['color'], dds_text=dds_text, physics_text=physics_state['text'], physics_color=physics_state['color'])))
        _state.mapping_status_label.setToolTip('\n'.join(status_lines))
        route_enabled_state = _state._mapping_route_button_enabled_state_helper(source_index=source_index, target_index=target_index)
        _state.assign_source_button.setEnabled(route_enabled_state['assign_source'])
        _state.merge_source_button.setEnabled(route_enabled_state['merge_source'])
        _state.remove_source_button.setEnabled(route_enabled_state['remove_source'])
        _state.clear_target_button.setEnabled(route_enabled_state['clear_target'])
    _state._update_mapping_status = _update_mapping_status

def _parts_outliner_mapping_step_035(_state):

    def _sync_target_mapping_tree_item(target_index: int) -> None:
        edit = _state.mapping_edits_by_target.get(int(target_index))
        item = _state.mapping_items_by_target.get(int(target_index))
        if edit is None or item is None:
            return
        committed_text = _state._mapping_edit_committed_text_helper(edit)
        committed_indices = _state._parse_mapping_edit(edit)
        summary, ok = _state._selected_source_summary(committed_text)
        source_cell_state = _state._mapping_committed_source_cell_state_helper(selection_ok=ok, has_source_indices=bool(committed_indices))
        item.setText(3, _state._mapping_source_cell_text(summary, ok))
        item.setForeground(3, _state.QBrush(_state.QColor(str(source_cell_state['foreground']))))
        item.setData(0, _state.Qt.UserRole, tuple(committed_indices))
        item.setData(0, _state.Qt.UserRole + 3, bool(source_cell_state['is_empty']))
        state_text, state_color = _state._target_outliner_state(int(target_index), committed_indices)
        item.setText(4, state_text)
        item.setForeground(4, _state.QBrush(_state.QColor(state_color)))
        dds_cell_state = _state._mapping_target_dds_cell_state_helper(state_text=state_text, has_source_indices=bool(committed_indices))
        if dds_cell_state['uses_removed_target_text']:
            item.setText(5, _state._removed_target_dds_cell_text(item.text(0)))
            item.setToolTip(5, _state._removed_target_dds_tooltip_helper())
        else:
            item.setText(5, _state._target_texture_status_text(item.text(0)))
            item.setToolTip(5, _state._target_texture_status_details(item.text(0)))
        item.setForeground(5, _state.QBrush(_state.QColor(str(dds_cell_state['foreground']))))
    _state._sync_target_mapping_tree_item = _sync_target_mapping_tree_item

def _parts_outliner_mapping_step_036(_state):

    def _set_mapping_indices(target_index: int, source_indices: Sequence[int], *, push_undo: bool=True, undo_label: str='Change target routing', defer_preview: bool=False) -> None:
        edit = _state.mapping_edits_by_target.get(target_index)
        if edit is None:
            return
        if _state._active_mesh_edit_source_routing_mutation_blocked('target changes'):
            return
        if push_undo:
            _state._push_geometry_undo_snapshot(undo_label, metadata_only=True)
        for source_index in source_indices:
            try:
                mapped_source_index = int(source_index)
            except (TypeError, ValueError):
                continue
            _state.independent_output_source_indices.discard(mapped_source_index)
            _state.preview_only_source_indices.discard(mapped_source_index)
        edit.setText(_state._mapping_source_indices_text_helper(source_indices))
        edit.setProperty('committed_mapping_text', edit.text().strip())
        _state._sync_target_mapping_tree_item(int(target_index))
        _state.texture_overrides_dirty['dirty'] = True
        _state.mapping_edit_refresh_timer.stop()
        _state._refresh_source_assignment_columns()
        _state._update_mapping_status()
        selection_payload = _state._target_mapping_selection_view_payload_helper(selected_target_index=int(_state.selected_target_slot.get('index', -1)), target_index=int(target_index), source_indices=tuple(source_indices or ()))
        if selection_payload is not None:
            _state._set_mesh_replacement_selection_view(**_state._selection_view_update_kwargs_helper(selection_payload))
        _state._update_selection_context()
        preview_action = _state._source_part_routing_preview_action_helper(defer_preview=defer_preview, pending_reason='routing removal changed')
        if _state._resident_parts_session_active():
            _state._set_source_parts_apply_pending('resident source routing change awaits renderer/service confirmation')
        elif preview_action['apply_pending']:
            _state._set_source_parts_apply_pending(str(preview_action['pending_reason']))
        elif preview_action['queue_preview']:
            _state._queue_static_preview_rebuild()
    _state._set_mapping_indices = _set_mapping_indices

def _parts_outliner_mapping_step_037(_state):
    _state._factory_result_values.update({'_parts_outliner_source_label': _state._parts_outliner_source_label, '_parts_outliner_source_geometry': _state._parts_outliner_source_geometry, '_selected_source_indices_from_tree': _state._selected_source_indices_from_tree, '_set_transform_source_indices': _state._set_transform_source_indices, '_clear_transform_source_indices': _state._clear_transform_source_indices, '_set_source_parts_apply_pending': _state._set_source_parts_apply_pending, '_clear_source_parts_apply_pending': _state._clear_source_parts_apply_pending, '_set_source_parts_preview_rebuild_pending': _state._set_source_parts_preview_rebuild_pending, '_clear_source_parts_preview_rebuild_pending': _state._clear_source_parts_preview_rebuild_pending, '_add_source_tree_item': _state._add_source_tree_item, '_source_item_check_state_changed': _state._source_item_check_state_changed, '_outliner_source_index_from_item': _state._outliner_source_index_from_item, '_parts_outliner_set_source_selection': _state._parts_outliner_set_source_selection, '_refresh_parts_outliner': _state._refresh_parts_outliner, '_show_parts_outliner_context_menu': _state._show_parts_outliner_context_menu, '_apply_parts_outliner_source_target': _state._apply_parts_outliner_source_target, '_parts_outliner_drop_target_index': _state._parts_outliner_drop_target_index, '_handle_parts_outliner_source_drop': _state._handle_parts_outliner_source_drop, '_apply_parts_outliner_source_role': _state._apply_parts_outliner_source_role, '_open_parts_outliner_target_dropdown': _state._open_parts_outliner_target_dropdown, '_open_parts_outliner_role_dropdown': _state._open_parts_outliner_role_dropdown, '_handle_parts_outliner_item_clicked': _state._handle_parts_outliner_item_clicked, '_append_mapping_target_row': _state._append_mapping_target_row, '_build_mapping_table_chunk': _state._build_mapping_table_chunk, '_apply_target_slot_filters': _state._apply_target_slot_filters, '_ensure_mapping_table_building': _state._ensure_mapping_table_building, '_clear_all_mapping_guesses': _state._clear_all_mapping_guesses, '_apply_best_mapping_guesses': _state._apply_best_mapping_guesses, '_preview_selected_target_slot': _state._preview_selected_target_slot, '_selected_source_index': _state._selected_source_index, '_selected_target_index': _state._selected_target_index, '_parse_mapping_edit': _state._parse_mapping_edit, '_texture_set_for_source_index': _state._texture_set_for_source_index, '_source_material_group_label': _state._source_material_group_label, '_mapped_target_vertex_count': _state._mapped_target_vertex_count, '_mapped_source_vertex_counts': _state._mapped_source_vertex_counts, '_mapping_preserve_split_group_count': _state._mapping_preserve_split_group_count, '_mapping_vertex_limit_issues': _state._mapping_vertex_limit_issues, '_routing_source_material_labels': _state._routing_source_material_labels, '_routing_effect_lines': _state._routing_effect_lines, '_set_advanced_mapping_visible': _state._set_advanced_mapping_visible, '_update_mapping_status': _state._update_mapping_status, '_sync_target_mapping_tree_item': _state._sync_target_mapping_tree_item, '_set_mapping_indices': _state._set_mapping_indices})

STEPS = (
    _parts_outliner_mapping_step_029,
    _parts_outliner_mapping_step_030,
    _parts_outliner_mapping_step_031,
    _parts_outliner_mapping_step_032,
    _parts_outliner_mapping_step_033,
    _parts_outliner_mapping_step_034,
    _parts_outliner_mapping_step_035,
    _parts_outliner_mapping_step_036,
    _parts_outliner_mapping_step_037,
)
