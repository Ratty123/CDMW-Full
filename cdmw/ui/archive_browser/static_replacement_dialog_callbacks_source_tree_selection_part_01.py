from __future__ import annotations

def _source_tree_selection_step_001(_state):
    _state.QPoint = _state.context.get('QPoint')
    _state.QTimer = _state.context.get('QTimer')
    _state.Qt = _state.context.get('Qt')
    _state._add_source_tree_item = _state.context.get('_add_source_tree_item')
    _state._alignment_d3d11_preview_active = _state.context.get('_alignment_d3d11_preview_active')
    _state._alignment_d3d11_source_indices_for_editor_id = _state.context.get('_alignment_d3d11_source_indices_for_editor_id')
    _state._alignment_geometry_tab_active = _state.context.get('_alignment_geometry_tab_active')
    _state._clear_transform_source_indices = _state.context.get('_clear_transform_source_indices')
    _state._clear_tree_current_item = _state.context.get('_clear_tree_current_item')
    _state._d3d11_source_part_selection_route_helper = _state.context.get('_d3d11_source_part_selection_route_helper')
    _state._fit_alignment_tree_height_to_rows = _state.context.get('_fit_alignment_tree_height_to_rows')
    _state._is_marker_source = _state.context.get('_is_marker_source')
    _state._load_selected_part_controls = _state.context.get('_load_selected_part_controls')
    _state._original_selection_route_state_helper = _state.context.get('_original_selection_route_state_helper')
    _state._parse_mapping_edit = _state.context.get('_parse_mapping_edit')
    _state._part_selection_clear_state_helper = _state.context.get('_part_selection_clear_state_helper')
    _state._part_selection_state_active_helper = _state.context.get('_part_selection_state_active_helper')
    _state._parts_outliner_selection_row_state_helper = _state.context.get('_parts_outliner_selection_row_state_helper')
    _state._parts_outliner_set_source_selection = _state.context.get('_parts_outliner_set_source_selection')
    _state._parts_outliner_target_selection_state_helper = _state.context.get('_parts_outliner_target_selection_state_helper')
    _state._queue_selection_preview_refresh = _state.context.get('_queue_selection_preview_refresh')
    _state._refresh_original_reference_preview = _state.context.get('_refresh_original_reference_preview')
    _state._selected_source_indices_from_tree = _state.context.get('_selected_source_indices_from_tree')
    _state._selection_filter_refresh_needed_helper = _state.context.get('_selection_filter_refresh_needed_helper')
    _state._selection_view_update_kwargs_helper = _state.context.get('_selection_view_update_kwargs_helper')
    _state._set_mesh_replacement_selection_view = _state.context.get('_set_mesh_replacement_selection_view')
    _state._set_transform_source_indices = _state.context.get('_set_transform_source_indices')
    _state._show_replacement_sources_context_menu_for_viewport = _state.context.get('_show_replacement_sources_context_menu_for_viewport')
    _state._source_assigned_target_indices_helper = _state.context.get('_source_assigned_target_indices_helper')
    _state._source_index_from_tree_item = _state.context.get('_source_index_from_tree_item')
    _state._source_selection_route_state_helper = _state.context.get('_source_selection_route_state_helper')
    _state._source_tree_context_selection_action_helper = _state.context.get('_source_tree_context_selection_action_helper')
    _state._source_tree_context_selection_clear_multi_indices_helper = _state.context.get('_source_tree_context_selection_clear_multi_indices_helper')
    _state._source_tree_context_selection_record_multi_indices_helper = _state.context.get('_source_tree_context_selection_record_multi_indices_helper')
    _state._source_tree_context_selection_right_press_helper = _state.context.get('_source_tree_context_selection_right_press_helper')
    _state._source_tree_current_selection_index_helper = _state.context.get('_source_tree_current_selection_index_helper')
    _state._sync_highlight_sets = _state.context.get('_sync_highlight_sets')
    _state._target_selection_index_helper = _state.context.get('_target_selection_index_helper')
    _state._target_selection_route_state_helper = _state.context.get('_target_selection_route_state_helper')
    _state._target_source_indices_helper = _state.context.get('_target_source_indices_helper')
    _state._update_mapping_status = _state.context.get('_update_mapping_status')
    _state._update_selection_context = _state.context.get('_update_selection_context')
    _state.alignment_d3d11_preview_host = _state.context.get('alignment_d3d11_preview_host')
    _state.control_tabs = _state.context.get('control_tabs')
    _state.dialog = _state.context.get('dialog')
    _state.hovered_source_part = _state.context.get('hovered_source_part')
    if _state.hovered_source_part is None:
        _state.hovered_source_part = {}
    _state.index = _state.context.get('index')
    _state.mapping_edits = _state.context.get('mapping_edits')
    _state.mapping_edits_by_target = _state.context.get('mapping_edits_by_target')
    _state.mapping_items_by_target = _state.context.get('mapping_items_by_target')
    _state.mapping_tree = _state.context.get('mapping_tree')
    _state.original_tree = _state.context.get('original_tree')
    _state.parts_outliner_tree = _state.context.get('parts_outliner_tree')
    _state.parts_tab = _state.context.get('parts_tab')
    _state.preview_part_pick_checkbox = _state.context.get('preview_part_pick_checkbox')
    _state.preview_renderer_combo = _state.context.get('preview_renderer_combo')
    _state.replacement_mesh_for_mapping = _state.context.get('replacement_mesh_for_mapping')
    _state.selected_original_highlight_indices = _state.context.get('selected_original_highlight_indices')
    _state.selected_original_part = _state.context.get('selected_original_part')
    _state.selected_source_highlight_indices = _state.context.get('selected_source_highlight_indices')
    _state.selected_source_part = _state.context.get('selected_source_part')
    _state.selected_target_original_highlight_indices = _state.context.get('selected_target_original_highlight_indices')
    _state.selected_target_slot = _state.context.get('selected_target_slot')
    _state.selected_target_source_highlight_indices = _state.context.get('selected_target_source_highlight_indices')
    _state.source_items_by_index = _state.context.get('source_items_by_index')
    _state.source_parts_group = _state.context.get('source_parts_group')
    _state.source_tree = _state.context.get('source_tree')
    _state.source_tree_context_selection_state = _state.context.get('source_tree_context_selection_state')
    _state.source_tree_layout_state = _state.context.get('source_tree_layout_state')
    _state.texture_filter_refresh = _state.context.get('texture_filter_refresh')
    _state.texture_filter_selected_checkbox = _state.context.get('texture_filter_selected_checkbox')

def _source_tree_selection_step_002(_state):

    def _part_pick_checked() -> bool:
        return bool(_state.preview_part_pick_checkbox is not None and callable(getattr(_state.preview_part_pick_checkbox, 'isChecked', None)) and _state.preview_part_pick_checkbox.isChecked())
    _state._part_pick_checked = _part_pick_checked

def _source_tree_selection_step_003(_state):

    def _geometry_tab_active() -> bool:
        if callable(_state._alignment_geometry_tab_active):
            return bool(_state._alignment_geometry_tab_active())
        try:
            return bool(_state.control_tabs is not None and _state.parts_tab is not None and (_state.control_tabs.widget(_state.control_tabs.currentIndex()) is _state.parts_tab))
        except RuntimeError:
            return False
    _state._geometry_tab_active = _geometry_tab_active

def _source_tree_selection_step_004(_state):

    def _source_tree_selection_should_queue_preview() -> bool:
        current_data = getattr(_state.preview_renderer_combo, 'currentData', None)
        if not callable(current_data):
            return True
        try:
            renderer_key = str(current_data() or '').strip().lower()
        except RuntimeError:
            return False
        return renderer_key != 'd3d11'
    _state._source_tree_selection_should_queue_preview = _source_tree_selection_should_queue_preview

    def _sync_embedded_part_selection(source_indices: object) -> bool:
        if bool(getattr(_state.dialog, '_mesh_editor_embedded_selection_sync_active', False)):
            return False
        setter = getattr(_state.dialog, '_mesh_editor_embedded_set_part_selection', None)
        if not callable(setter):
            return False
        setattr(_state.dialog, '_mesh_editor_embedded_selection_sync_active', True)
        try:
            return bool(setter(tuple(source_indices or ())))
        finally:
            setattr(_state.dialog, '_mesh_editor_embedded_selection_sync_active', False)
    _state._sync_embedded_part_selection = _sync_embedded_part_selection

    def _apply_embedded_part_selection_from_viewport(source_indices: object) -> bool:
        if bool(getattr(_state.dialog, '_mesh_editor_embedded_selection_sync_active', False)):
            return False
        try:
            normalized = tuple(sorted({int(index) for index in tuple(source_indices or ()) if int(index) >= 0}))
        except (TypeError, ValueError):
            return False
        setattr(_state.dialog, '_mesh_editor_embedded_selection_sync_active', True)
        blocked = _state.source_tree.blockSignals(True)
        try:
            _state.source_tree.clearSelection()
            for source_index in normalized:
                source_item = _state._ensure_source_tree_item_available(source_index)
                if source_item is not None:
                    source_item.setSelected(True)
            current = _state.source_items_by_index.get(normalized[0]) if normalized else None
            _state.source_tree.setCurrentItem(current)
        finally:
            _state.source_tree.blockSignals(blocked)
        try:
            _state._refresh_source_tree_selection_state(current)
            return True
        finally:
            setattr(_state.dialog, '_mesh_editor_embedded_selection_sync_active', False)
    _state._apply_embedded_part_selection_from_viewport = _apply_embedded_part_selection_from_viewport

def _source_tree_selection_step_005(_state):

    def _refresh_source_tree_selection_state(current_item: Optional[QTreeWidgetItem]=None) -> None:
        selected_source_indices = _state._selected_source_indices_from_tree(include_fallback=False)
        context_action = _state._source_tree_context_selection_action_helper(selected_source_indices, right_press_active=_state._source_tree_context_selection_right_press_helper(_state.source_tree_context_selection_state))
        if context_action == 'record_multi':
            _state._source_tree_context_selection_record_multi_indices_helper(_state.source_tree_context_selection_state, selected_source_indices)
        elif context_action == 'clear_multi':
            _state._source_tree_context_selection_clear_multi_indices_helper(_state.source_tree_context_selection_state)
        current = current_item if current_item is not None else _state.source_tree.currentItem()
        current_index = _state._source_index_from_tree_item(current)
        selected_item_indices = tuple((_state._source_index_from_tree_item(item) for item in tuple(_state.source_tree.selectedItems() or ())))
        current_index = _state._source_tree_current_selection_index_helper(current_index, selected_item_indices)
        mapped_targets = _state._source_assigned_target_indices_helper(current_index, _state.mapping_edits, parse_mapping_edit=_state._parse_mapping_edit) if current_index >= 0 else ()
        filter_refresh = _state.texture_filter_refresh.get('func')
        selection_state = _state._source_selection_route_state_helper(current_index, mapped_targets, has_filter_refresh=filter_refresh is not None, selected_filter_enabled=_state.texture_filter_selected_checkbox is not None and _state.texture_filter_selected_checkbox.isChecked())
        _state.selected_source_part['index'] = int(selection_state['source_index'])
        exact_source_indices = tuple(selected_source_indices or selection_state['source_highlight_indices'])
        source_highlight_indices = exact_source_indices
        transform_source_indices = exact_source_indices
        _state.selected_source_highlight_indices.clear()
        _state.selected_source_highlight_indices.update(source_highlight_indices)
        if not bool(selection_state['clear_transform_source_indices']):
            _state._set_transform_source_indices(transform_source_indices)
        else:
            _state._clear_transform_source_indices()
        _state.selected_target_original_highlight_indices.clear()
        _state.selected_target_source_highlight_indices.clear()
        _state._sync_highlight_sets()
        _state._load_selected_part_controls()
        _state._update_mapping_status()
        selection_view_kwargs = dict(selection_state['selection_view_kwargs'])
        selection_view_kwargs['source_indices'] = exact_source_indices
        _state._set_mesh_replacement_selection_view(**selection_view_kwargs)
        _state._update_selection_context()
        if bool(selection_state['refresh_filter']):
            filter_refresh()
        if _state._source_tree_selection_should_queue_preview():
            _state._queue_selection_preview_refresh()
        _state._sync_embedded_part_selection(exact_source_indices)
    _state._refresh_source_tree_selection_state = _refresh_source_tree_selection_state

def _source_tree_selection_step_006(_state):

    def _source_selection_changed(_current: Optional[QTreeWidgetItem], _previous: Optional[QTreeWidgetItem]) -> None:
        _state._refresh_source_tree_selection_state(_current)
    _state._source_selection_changed = _source_selection_changed

def _source_tree_selection_step_007(_state):

    def _ensure_source_tree_item_available(source_index: int) -> Optional[QTreeWidgetItem]:
        try:
            source_index = int(source_index)
        except (TypeError, ValueError):
            return None
        source_item = _state.source_items_by_index.get(source_index)
        if source_item is not None:
            return source_item
        if _state.replacement_mesh_for_mapping is None:
            return None
        submeshes = tuple(getattr(_state.replacement_mesh_for_mapping, 'submeshes', ()) or ())
        if source_index < 0 or source_index >= len(submeshes):
            return None
        source = submeshes[source_index]
        if _state._is_marker_source(source):
            return None
        blocked = _state.source_tree.blockSignals(True)
        try:
            _state._add_source_tree_item(source_index, source)
        finally:
            _state.source_tree.blockSignals(blocked)
        _state._fit_alignment_tree_height_to_rows(_state.source_tree, **_state.source_tree_layout_state.height_fit_kwargs)
        _state.source_parts_group.setMaximumHeight(16777215)
        return _state.source_items_by_index.get(source_index)
    _state._ensure_source_tree_item_available = _ensure_source_tree_item_available

def _source_tree_selection_step_008(_state):

    def _select_source_part_from_viewport(source_index: int, *, refresh_filter: bool=True, refresh_preview: bool=True, preserve_existing_selection_if_selected: bool=False) -> bool:
        try:
            source_index = int(source_index)
        except (TypeError, ValueError):
            return False
        source_item = _state._ensure_source_tree_item_available(source_index)
        if source_item is None:
            return False
        if _state._part_pick_checked():
            _state.hovered_source_part['index'] = source_index
        preserve_existing_selection = False
        if bool(preserve_existing_selection_if_selected):
            try:
                preserve_existing_selection = bool(source_item.isSelected())
            except RuntimeError:
                preserve_existing_selection = False
        blocked = _state.source_tree.blockSignals(True)
        try:
            if not preserve_existing_selection:
                _state.source_tree.clearSelection()
            source_item.setSelected(True)
            _state.source_tree.setCurrentItem(source_item)
        finally:
            _state.source_tree.blockSignals(blocked)
        _state.source_tree.scrollToItem(source_item)
        mapped_targets = _state._source_assigned_target_indices_helper(source_index, _state.mapping_edits, parse_mapping_edit=_state._parse_mapping_edit)
        filter_refresh = _state.texture_filter_refresh.get('func')
        selection_state = _state._source_selection_route_state_helper(source_index, mapped_targets, has_filter_refresh=filter_refresh is not None, selected_filter_enabled=_state.texture_filter_selected_checkbox is not None and _state.texture_filter_selected_checkbox.isChecked())
        exact_source_indices = tuple(_state._selected_source_indices_from_tree(include_fallback=False))
        _state.selected_source_part['index'] = int(selection_state['source_index'])
        _state.selected_source_highlight_indices.clear()
        _state.selected_source_highlight_indices.update(exact_source_indices)
        _state._set_transform_source_indices(exact_source_indices)
        _state._sync_highlight_sets()
        _state._load_selected_part_controls()
        _state._update_mapping_status()
        _state.selected_target_original_highlight_indices.clear()
        _state.selected_target_source_highlight_indices.clear()
        _state.selected_target_slot['index'] = -1
        selection_view_kwargs = dict(selection_state['selection_view_kwargs'])
        selection_view_kwargs['source_indices'] = exact_source_indices
        _state._set_mesh_replacement_selection_view(**selection_view_kwargs)
        _state._update_selection_context()
        if refresh_filter and bool(selection_state['refresh_filter']):
            filter_refresh()
        if refresh_preview:
            _state._queue_selection_preview_refresh()
        _state._sync_embedded_part_selection(exact_source_indices)
        return True
    _state._select_source_part_from_viewport = _select_source_part_from_viewport

def _source_tree_selection_step_009(_state):

    def _d3d11_source_part_selected(source_index: int) -> None:
        source_indices = _state._alignment_d3d11_source_indices_for_editor_id(int(source_index))
        route_state = _state._d3d11_source_part_selection_route_helper(preview_active=_state._alignment_d3d11_preview_active(), geometry_tab_active=_state._geometry_tab_active(), source_index=source_index, current_source_index=_state.selected_source_part.get('index', -1), editor_source_indices=source_indices)
        if not route_state['should_select']:
            return
        selected_source_index = int(route_state['selected_source_index'])
        _state._select_source_part_from_viewport(selected_source_index, refresh_preview=False)
        exact_setter = getattr(_state.dialog, '_mesh_editor_embedded_set_part_selection', None)
        merged_visible = getattr(_state.dialog, '_mesh_editor_embedded_merged_visible', None)
        embedded_select = getattr(_state.dialog, '_mesh_editor_embedded_native_part_selected', None)
        if not callable(exact_setter) and callable(merged_visible) and bool(merged_visible()) and callable(embedded_select):
            embedded_select(selected_source_index)
    _state._d3d11_source_part_selected = _d3d11_source_part_selected

def _source_tree_selection_step_010(_state):

    def _d3d11_source_part_hovered(editor_id: int) -> None:
        next_source_index = -1
        if _state._alignment_d3d11_preview_active() and _state._part_pick_checked():
            source_indices = _state._alignment_d3d11_source_indices_for_editor_id(int(editor_id))
            if source_indices:
                next_source_index = int(source_indices[0])
        try:
            previous_source_index = int(_state.hovered_source_part.get('index', -1))
        except (TypeError, ValueError):
            previous_source_index = -1
        if previous_source_index == next_source_index:
            return
        _state.hovered_source_part['index'] = next_source_index
        _state._sync_highlight_sets()
    _state._d3d11_source_part_hovered = _d3d11_source_part_hovered

def _source_tree_selection_step_011(_state):

    def _d3d11_source_part_context_requested(editor_id: int, x: int, y: int) -> None:
        if not _state._alignment_d3d11_preview_active() or not _state._part_pick_checked():
            return
        source_indices = _state._alignment_d3d11_source_indices_for_editor_id(int(editor_id))
        source_index = int(source_indices[0]) if source_indices else int(editor_id)
        if not _state._select_source_part_from_viewport(source_index, refresh_filter=False, refresh_preview=False, preserve_existing_selection_if_selected=True):
            return
        if _state.QPoint is None or _state.alignment_d3d11_preview_host is None or (not callable(_state._show_replacement_sources_context_menu_for_viewport)):
            return
        global_pos = None
        cursor = getattr(_state.alignment_d3d11_preview_host, 'cursor', None)
        if callable(cursor):
            try:
                global_pos = cursor().pos()
            except RuntimeError:
                global_pos = None
        if global_pos is None:
            global_pos = _state.alignment_d3d11_preview_host.mapToGlobal(_state.QPoint(int(x), int(y)))
        open_context_menu = lambda: _state._show_replacement_sources_context_menu_for_viewport(source_index, global_pos)
        if _state.QTimer is not None:
            _state.QTimer.singleShot(0, open_context_menu)
        else:
            open_context_menu()
    _state._d3d11_source_part_context_requested = _d3d11_source_part_context_requested

def _source_tree_selection_step_012(_state):

    def _original_selection_changed(current: Optional[QTreeWidgetItem], _previous: Optional[QTreeWidgetItem]) -> None:
        raw_indices = current.data(0, _state.Qt.UserRole) if current is not None else ()
        selection_state = _state._original_selection_route_state_helper(raw_indices)
        _state.selected_original_part['index'] = int(selection_state['original_index'])
        _state.selected_original_highlight_indices.clear()
        _state.selected_original_highlight_indices.update(tuple(selection_state['original_highlight_indices']))
        _state._sync_highlight_sets()
        _state._refresh_original_reference_preview()
        _state._set_mesh_replacement_selection_view(**selection_state['selection_view_kwargs'])
        _state._update_selection_context()
        _state._queue_selection_preview_refresh()
    _state._original_selection_changed = _original_selection_changed

def _source_tree_selection_step_013(_state):

    def _target_selection_changed(current: Optional[QTreeWidgetItem], _previous: Optional[QTreeWidgetItem]) -> None:
        raw_target_index = current.data(0, _state.Qt.UserRole + 1) if current is not None else None
        target_index = _state._target_selection_index_helper(raw_target_index)
        source_indices = _state._target_source_indices_helper(target_index, _state.mapping_edits_by_target, parse_mapping_edit=_state._parse_mapping_edit) if target_index >= 0 else ()
        selection_state = _state._target_selection_route_state_helper(raw_target_index, source_indices)
        _state.selected_target_slot['index'] = int(selection_state['target_index'])
        _state.selected_target_original_highlight_indices.clear()
        _state.selected_target_original_highlight_indices.update(tuple(selection_state['target_original_highlight_indices']))
        _state.selected_target_source_highlight_indices.clear()
        _state.selected_target_source_highlight_indices.update(tuple(selection_state['target_source_highlight_indices']))
        _state._parts_outliner_set_source_selection(selection_state['outliner_source_selection'], activate_transform=False, select_reference_rows=False)
        source_blocked = _state.source_tree.blockSignals(True)
        try:
            _state.source_tree.clearSelection()
        finally:
            _state.source_tree.blockSignals(source_blocked)
        _state._sync_highlight_sets()
        _state._refresh_original_reference_preview()
        _state._load_selected_part_controls()
        _state._update_mapping_status()
        _state._set_mesh_replacement_selection_view(**selection_state['selection_view_kwargs'])
        _state._update_selection_context()
        _state._queue_selection_preview_refresh()
    _state._target_selection_changed = _target_selection_changed

def _source_tree_selection_step_014(_state):

    def _parts_outliner_selection_changed(current: Optional[QTreeWidgetItem], _previous: Optional[QTreeWidgetItem]) -> None:
        row_state = _state._parts_outliner_selection_row_state_helper(current, user_role=int(_state.Qt.UserRole))
        if row_state is None:
            return
        row_kind = str(row_state['row_kind'])
        target_index = int(row_state['target_index'])
        source_indices = list(row_state['source_indices'])
        if row_kind == 'source' and source_indices:
            _state._select_source_part_from_viewport(source_indices[0])
            if target_index >= 0:
                target_item = _state.mapping_items_by_target.get(target_index)
                if target_item is not None:
                    _state.mapping_tree.blockSignals(True)
                    try:
                        _state.mapping_tree.setCurrentItem(target_item)
                    finally:
                        _state.mapping_tree.blockSignals(False)
                _state.selected_target_slot['index'] = target_index
                _state.selected_target_original_highlight_indices.clear()
                _state.selected_target_source_highlight_indices.clear()
                _state._sync_highlight_sets()
                _state._refresh_original_reference_preview()
            return
        if row_kind == 'target':
            selection_state = _state._parts_outliner_target_selection_state_helper(row_kind=row_kind, target_index=target_index, source_indices=tuple(source_indices))
            if selection_state is None:
                return
            _state.selected_target_slot['index'] = int(selection_state['selected_target_index'])
            target_item = _state.mapping_items_by_target.get(target_index)
            if target_item is not None:
                _state.mapping_tree.blockSignals(True)
                try:
                    _state.mapping_tree.setCurrentItem(target_item)
                finally:
                    _state.mapping_tree.blockSignals(False)
            _state._parts_outliner_set_source_selection(source_indices, activate_transform=False, select_reference_rows=False)
            source_blocked = _state.source_tree.blockSignals(True)
            try:
                _state.source_tree.clearSelection()
            finally:
                _state.source_tree.blockSignals(source_blocked)
            _state.selected_target_original_highlight_indices.clear()
            _state.selected_target_source_highlight_indices.clear()
            _state.selected_target_original_highlight_indices.update(tuple(selection_state['target_original_highlight_indices']))
            _state.selected_target_source_highlight_indices.update(tuple(selection_state['target_source_highlight_indices']))
            _state._sync_highlight_sets()
            _state._refresh_original_reference_preview()
            _state._load_selected_part_controls()
            _state._update_mapping_status()
            _state._set_mesh_replacement_selection_view(**_state._selection_view_update_kwargs_helper(selection_state['selection_view']))
            _state._update_selection_context()
            _state._queue_selection_preview_refresh()
    _state._parts_outliner_selection_changed = _parts_outliner_selection_changed

def _source_tree_selection_step_015(_state):

    def _clear_part_selections_when_leaving_geometry(index: int) -> None:
        if _state.control_tabs.widget(index) is _state.parts_tab:
            return
        has_selection = _state._part_selection_state_active_helper(selected_source_index=int(_state.selected_source_part.get('index', -1)), selected_original_index=int(_state.selected_original_part.get('index', -1)), selected_target_index=int(_state.selected_target_slot.get('index', -1)), selected_source_highlights=tuple(_state.selected_source_highlight_indices), selected_target_source_highlights=tuple(_state.selected_target_source_highlight_indices), selected_original_highlights=tuple(_state.selected_original_highlight_indices), selected_target_original_highlights=tuple(_state.selected_target_original_highlight_indices), source_tree_has_selection=bool(_state.source_tree.selectedItems()), original_tree_has_selection=bool(_state.original_tree.selectedItems()), mapping_tree_has_selection=bool(_state.mapping_tree.selectedItems()))
        if not has_selection:
            return
        clear_state = _state._part_selection_clear_state_helper()
        for tree in (_state.source_tree, _state.original_tree, _state.mapping_tree, _state.parts_outliner_tree):
            previous_blocked = tree.blockSignals(True)
            try:
                _state._clear_tree_current_item(tree)
            finally:
                tree.blockSignals(previous_blocked)
        _state.selected_source_part['index'] = int(clear_state['selected_source_index'])
        _state.selected_original_part['index'] = int(clear_state['selected_original_index'])
        _state.selected_target_slot['index'] = int(clear_state['selected_target_index'])
        _state.selected_source_highlight_indices.clear()
        _state._clear_transform_source_indices()
        _state.selected_target_source_highlight_indices.clear()
        _state.selected_original_highlight_indices.clear()
        _state.selected_target_original_highlight_indices.clear()
        _state._sync_highlight_sets()
        _state._refresh_original_reference_preview()
        _state._load_selected_part_controls()
        _state._update_mapping_status()
        selection_payload = clear_state['selection_view']
        _state._set_mesh_replacement_selection_view(**_state._selection_view_update_kwargs_helper(selection_payload))
        _state._update_selection_context()
        filter_refresh = _state.texture_filter_refresh.get('func')
        if _state._selection_filter_refresh_needed_helper(has_filter_refresh=filter_refresh is not None, selected_filter_enabled=_state.texture_filter_selected_checkbox is not None and _state.texture_filter_selected_checkbox.isChecked()):
            filter_refresh()
        _state._queue_selection_preview_refresh()
    _state._clear_part_selections_when_leaving_geometry = _clear_part_selections_when_leaving_geometry

def _source_tree_selection_step_016(_state):
    if _state.dialog is not None:
        setattr(_state.dialog, '_mesh_editor_embedded_apply_part_selection_from_viewport', _state._apply_embedded_part_selection_from_viewport)
    _state._factory_result_values.update({'_refresh_source_tree_selection_state': _state._refresh_source_tree_selection_state, '_source_selection_changed': _state._source_selection_changed, '_ensure_source_tree_item_available': _state._ensure_source_tree_item_available, '_d3d11_source_part_context_requested': _state._d3d11_source_part_context_requested, '_d3d11_source_part_hovered': _state._d3d11_source_part_hovered, '_select_source_part_from_viewport': _state._select_source_part_from_viewport, '_d3d11_source_part_selected': _state._d3d11_source_part_selected, '_original_selection_changed': _state._original_selection_changed, '_target_selection_changed': _state._target_selection_changed, '_parts_outliner_selection_changed': _state._parts_outliner_selection_changed, '_clear_part_selections_when_leaving_geometry': _state._clear_part_selections_when_leaving_geometry, '_apply_embedded_part_selection_from_viewport': _state._apply_embedded_part_selection_from_viewport})

STEPS = (
    _source_tree_selection_step_001,
    _source_tree_selection_step_002,
    _source_tree_selection_step_003,
    _source_tree_selection_step_004,
    _source_tree_selection_step_005,
    _source_tree_selection_step_006,
    _source_tree_selection_step_007,
    _source_tree_selection_step_008,
    _source_tree_selection_step_009,
    _source_tree_selection_step_010,
    _source_tree_selection_step_011,
    _source_tree_selection_step_012,
    _source_tree_selection_step_013,
    _source_tree_selection_step_014,
    _source_tree_selection_step_015,
    _source_tree_selection_step_016,
)
