from __future__ import annotations

def _routing_complete_swap_step_001(_state):
    _state.Callable = _state.context.get('Callable')
    _state.List = _state.context.get('List')
    _state.QTimer = _state.context.get('QTimer')
    _state.StaticSubmeshMapping = _state.context.get('StaticSubmeshMapping')
    _state._alignment_d3d11_live_frame_available = _state.context.get('_alignment_d3d11_live_frame_available')
    _state._alignment_dialog_widgets_live = _state.context.get('_alignment_dialog_widgets_live')
    _state._alignment_mesh_edit_tab_active = _state.context.get('_alignment_mesh_edit_tab_active')
    _state._apply_checked_complete_swap = _state.context.get('_apply_checked_complete_swap')
    _state._call_if_alignment_widgets_live = _state.context.get('_call_if_alignment_widgets_live')
    _state._is_marker_source = _state.context.get('_is_marker_source')
    _state._mapped_source_indices = _state.context.get('_mapped_source_indices')
    _state._mapped_source_indices_helper = _state.context.get('_mapped_source_indices_helper')
    _state._mapping_edit_valid_source_indices_helper = _state.context.get('_mapping_edit_valid_source_indices_helper')
    _state._mapping_table_build_complete_helper = _state.context.get('_mapping_table_build_complete_helper')
    _state._material_authority_complete_swap_forced_child_states_helper = _state.context.get('_material_authority_complete_swap_forced_child_states_helper')
    _state._material_authority_complete_swap_next_transition_generation_helper = _state.context.get('_material_authority_complete_swap_next_transition_generation_helper')
    _state._material_authority_complete_swap_profile_name_helper = _state.context.get('_material_authority_complete_swap_profile_name_helper')
    _state._material_authority_complete_swap_restored_child_states_helper = _state.context.get('_material_authority_complete_swap_restored_child_states_helper')
    _state._material_authority_complete_swap_routing_progress_message_helper = _state.context.get('_material_authority_complete_swap_routing_progress_message_helper')
    _state._material_authority_complete_swap_routing_reason_helper = _state.context.get('_material_authority_complete_swap_routing_reason_helper')
    _state._material_authority_complete_swap_should_apply_checked_helper = _state.context.get('_material_authority_complete_swap_should_apply_checked_helper')
    _state._material_authority_complete_swap_source_output_size_index_helper = _state.context.get('_material_authority_complete_swap_source_output_size_index_helper')
    _state._material_authority_complete_swap_update_performance_helper = _state.context.get('_material_authority_complete_swap_update_performance_helper')
    _state._material_authority_complete_swap_update_queued_message_helper = _state.context.get('_material_authority_complete_swap_update_queued_message_helper')
    _state._push_geometry_undo_snapshot = _state.context.get('_push_geometry_undo_snapshot')
    _state._queue_source_material_plan_refresh = _state.context.get('_queue_source_material_plan_refresh')
    _state._queue_static_preview_rebuild = _state.context.get('_queue_static_preview_rebuild')
    _state._queue_texture_preview_refresh = _state.context.get('_queue_texture_preview_refresh')
    _state._refresh_output_impact_review = _state.context.get('_refresh_output_impact_review')
    _state._refresh_sidecar_option_state = _state.context.get('_refresh_sidecar_option_state')
    _state._refresh_source_assignment_columns = _state.context.get('_refresh_source_assignment_columns')
    _state._refresh_texture_override_tree = _state.context.get('_refresh_texture_override_tree')
    _state._select_complete_swap_material_profile = _state.context.get('_select_complete_swap_material_profile')
    _state._semantic_tokens = _state.context.get('_semantic_tokens')
    _state._set_alignment_d3d11_progress = _state.context.get('_set_alignment_d3d11_progress')
    _state._set_checkbox_checked_silently_helper = _state.context.get('_set_checkbox_checked_silently_helper')
    _state._set_combo_index_silently_helper = _state.context.get('_set_combo_index_silently_helper')
    _state._set_preview_performance_status = _state.context.get('_set_preview_performance_status')
    _state._source_group_label_or_fallback_helper = _state.context.get('_source_group_label_or_fallback_helper')
    _state._source_material_group_label = _state.context.get('_source_material_group_label')
    _state._source_part_assign_material_groups_to_targets_helper = _state.context.get('_source_part_assign_material_groups_to_targets_helper')
    _state._source_part_group_initial_target_counts_helper = _state.context.get('_source_part_group_initial_target_counts_helper')
    _state._source_part_group_items_helper = _state.context.get('_source_part_group_items_helper')
    _state._source_part_material_groups_helper = _state.context.get('_source_part_material_groups_helper')
    _state._source_renderable_indices_helper = _state.context.get('_source_renderable_indices_helper')
    _state._target_submesh_display_name_helper = _state.context.get('_target_submesh_display_name_helper')
    _state._update_mapping_status = _state.context.get('_update_mapping_status')
    _state._update_selection_context = _state.context.get('_update_selection_context')
    _state.callback = _state.context.get('callback')
    _state.checked = _state.context.get('checked')
    _state.complete_external_swap_checkbox = _state.context.get('complete_external_swap_checkbox')
    _state.complete_swap_material_profile_combo = _state.context.get('complete_swap_material_profile_combo')
    _state.complete_swap_performance = _state.context.get('complete_swap_performance')
    _state.current_profile = _state.context.get('current_profile')
    _state.edit = _state.context.get('edit')
    _state.exc = _state.context.get('exc')
    _state.external_material_reset_checkbox = _state.context.get('external_material_reset_checkbox')
    _state.independent_output_source_indices = _state.context.get('independent_output_source_indices')
    _state.index = _state.context.get('index')
    _state.inject_base_color_checkbox = _state.context.get('inject_base_color_checkbox')
    _state.live_frame_available = _state.context.get('live_frame_available')
    _state.mapped_sources = _state.context.get('mapped_sources')
    _state.mapping = _state.context.get('mapping')
    _state.mapping_edits = _state.context.get('mapping_edits')
    _state.mapping_edits_by_target = _state.context.get('mapping_edits_by_target')
    _state.mapping_table_build_state = _state.context.get('mapping_table_build_state')
    _state.mapping_table_ready = _state.context.get('mapping_table_ready')
    _state.mappings = _state.context.get('mappings')
    _state.message = _state.context.get('message')
    _state.original_mesh_for_mapping = _state.context.get('original_mesh_for_mapping')
    _state.parsed_mappings = _state.context.get('parsed_mappings')
    _state.persist = _state.context.get('persist')
    _state.preview_only_source_indices = _state.context.get('preview_only_source_indices')
    _state.previous_blocked = _state.context.get('previous_blocked')
    _state.previous_states = _state.context.get('previous_states')
    _state.profile_name = _state.context.get('profile_name')
    _state.prune_unmapped_original_dds_checkbox = _state.context.get('prune_unmapped_original_dds_checkbox')
    _state.push_undo = _state.context.get('push_undo')
    _state.rebuild_sidecar_checkbox = _state.context.get('rebuild_sidecar_checkbox')
    _state.render_source_indices = _state.context.get('render_source_indices')
    _state.replacement_mesh_for_mapping = _state.context.get('replacement_mesh_for_mapping')
    _state.self = _state.context.get('self')
    _state.source_color_faithful_checkbox = _state.context.get('source_color_faithful_checkbox')
    _state.source_face_counts = _state.context.get('source_face_counts')
    _state.source_groups = _state.context.get('source_groups')
    _state.source_index = _state.context.get('source_index')
    _state.source_indices = _state.context.get('source_indices')
    _state.source_initial_targets = _state.context.get('source_initial_targets')
    _state.source_part_adjustments = _state.context.get('source_part_adjustments')
    _state.suggested_mappings = _state.context.get('suggested_mappings')

def _routing_complete_swap_step_002(_state):
    _state.target = _state.context.get('target')
    _state.target_count = _state.context.get('target_count')
    _state.target_index = _state.context.get('target_index')
    _state.target_sources = _state.context.get('target_sources')
    _state.text = _state.context.get('text')
    _state.texture_output_size_combo = _state.context.get('texture_output_size_combo')
    _state.texture_override_assignments = _state.context.get('texture_override_assignments')
    _state.texture_overrides_dirty = _state.context.get('texture_overrides_dirty')
    _state.texture_sets = _state.context.get('texture_sets')
    _state.transition_generation = _state.context.get('transition_generation')

def _routing_complete_swap_step_003(_state):

    def _complete_external_swap_mappings() -> List[StaticSubmeshMapping]:
        if _state.original_mesh_for_mapping is None or _state.replacement_mesh_for_mapping is None:
            return list(_state.suggested_mappings or [])
        mapping_table_ready = True
        try:
            mapping_table_ready = _state._mapping_table_build_complete_helper(_state.mapping_table_build_state)
        except NameError:
            mapping_table_ready = True
        if _state.mapping_edits and mapping_table_ready:
            render_source_indices = set(_state._source_renderable_indices_helper(_state.replacement_mesh_for_mapping, _state.source_part_adjustments, is_marker_source=_state._is_marker_source, excluded_source_indices=_state.preview_only_source_indices))
            parsed_mappings: _state.List[_state.StaticSubmeshMapping] = []
            for target_index, edit in _state.mapping_edits:
                source_indices = list(_state._mapping_edit_valid_source_indices_helper(edit, render_source_indices))
                target = _state.original_mesh_for_mapping.submeshes[target_index]
                parsed_mappings.append(_state.StaticSubmeshMapping(target_submesh_index=target_index, target_submesh_name=_state._target_submesh_display_name_helper(target_index, target), source_submesh_indices=source_indices, target_material_slot_index=target_index, merge_sources=True))
            if parsed_mappings:
                return parsed_mappings
        source_initial_targets = _state._source_part_group_initial_target_counts_helper(_state.suggested_mappings, lambda source_index: _state._source_material_group_label(int(source_index), _state.texture_sets))
        source_groups, source_face_counts = _state._source_part_material_groups_helper(_state.replacement_mesh_for_mapping, _state.source_part_adjustments, source_material_group_label=lambda source_index: _state._source_material_group_label(int(source_index), _state.texture_sets), source_group_label_or_fallback=_state._source_group_label_or_fallback_helper, is_marker_source=_state._is_marker_source, excluded_source_indices=tuple(_state.preview_only_source_indices))
        target_count = len(_state.original_mesh_for_mapping.submeshes)
        if not source_groups or target_count <= 0:
            return [_state.StaticSubmeshMapping(target_submesh_index=target_index, target_submesh_name=_state._target_submesh_display_name_helper(target_index, target), source_submesh_indices=[], target_material_slot_index=target_index, merge_sources=True) for target_index, target in enumerate(_state.original_mesh_for_mapping.submeshes)]
        target_sources, _overflow_groups = _state._source_part_assign_material_groups_to_targets_helper(_state._source_part_group_items_helper(source_groups, source_face_counts), target_count=target_count, original_mesh=_state.original_mesh_for_mapping, replacement_mesh=_state.replacement_mesh_for_mapping, target_display_name=_state._target_submesh_display_name_helper, source_initial_targets=source_initial_targets, semantic_tokens=_state._semantic_tokens)
        return [_state.StaticSubmeshMapping(target_submesh_index=target_index, target_submesh_name=_state._target_submesh_display_name_helper(target_index, target), source_submesh_indices=list(target_sources.get(target_index, [])), target_material_slot_index=target_index, merge_sources=True) for target_index, target in enumerate(_state.original_mesh_for_mapping.submeshes)]
    _state._complete_external_swap_mappings = _complete_external_swap_mappings

def _routing_complete_swap_step_004(_state):

    def _mapped_source_indices_value(mappings: object) -> set[int]:
        if callable(_state._mapped_source_indices):
            return set(_state._mapped_source_indices(mappings) or ())
        if callable(_state._mapped_source_indices_helper):
            return set(_state._mapped_source_indices_helper(mappings) or ())
        return set()
    _state._mapped_source_indices_value = _mapped_source_indices_value

def _routing_complete_swap_step_005(_state):

    def _active_mesh_edit_complete_swap_routing_blocked() -> bool:
        if not (callable(_state._alignment_mesh_edit_tab_active) and _state._alignment_mesh_edit_tab_active()):
            return False
        message = 'Active Mesh Editor complete-swap material routing requires native material execution; Python texture routing mutation fallback is disabled.'
        set_status_message = getattr(_state.self, 'set_status_message', None)
        if callable(set_status_message):
            set_status_message(message, error=True)
        return True
    _state._active_mesh_edit_complete_swap_routing_blocked = _active_mesh_edit_complete_swap_routing_blocked

def _routing_complete_swap_step_006(_state):

    def _apply_complete_external_swap_routing_to_ui(*, push_undo: bool=True) -> None:
        if not _state._alignment_dialog_widgets_live():
            return
        if _state._active_mesh_edit_complete_swap_routing_blocked():
            return

        def _call_if_alignment_widgets_live(callback: Callable[[], None]) -> None:
            if not callable(callback):
                return
            if not _state._alignment_dialog_widgets_live():
                return
            try:
                callback()
            except RuntimeError as exc:
                message = str(exc)
                if 'already deleted' in message or 'Internal C++ object' in message:
                    return
                raise
        mappings = _state._complete_external_swap_mappings()
        live_frame_available = bool(_state._alignment_d3d11_live_frame_available()) if callable(_state._alignment_d3d11_live_frame_available) else False
        progress_message = _state._material_authority_complete_swap_routing_progress_message_helper() if callable(_state._material_authority_complete_swap_routing_progress_message_helper) else 'Applying Material Authority routing...'
        if callable(_state._set_alignment_d3d11_progress):
            _state._set_alignment_d3d11_progress(8, progress_message, stage='complete_swap_routing', active=not live_frame_available)
        if push_undo and callable(_state._push_geometry_undo_snapshot):
            _state._push_geometry_undo_snapshot('Apply complete external swap routing')
        for mapping in mappings:
            edit = _state.mapping_edits_by_target.get(int(mapping.target_submesh_index))
            if edit is None:
                continue
            text = ', '.join((str(index) for index in tuple(mapping.source_submesh_indices or ())))
            edit.setText(text)
            edit.setProperty('committed_mapping_text', text)
        mapped_sources = _state._mapped_source_indices_value(mappings)
        _state.independent_output_source_indices.difference_update(mapped_sources)
        _state.texture_override_assignments.clear()
        _state.texture_overrides_dirty['dirty'] = True
        if not _state._alignment_dialog_widgets_live():
            return
        _call_if_alignment_widgets_live(_state._refresh_source_assignment_columns)
        _call_if_alignment_widgets_live(_state._update_mapping_status)
        _call_if_alignment_widgets_live(_state._update_selection_context)
        _call_if_alignment_widgets_live(_state._queue_static_preview_rebuild)
        try:
            _call_if_alignment_widgets_live(_state._refresh_texture_override_tree)
        except NameError:
            pass
        if callable(_state._queue_source_material_plan_refresh):
            routing_reason = _state._material_authority_complete_swap_routing_reason_helper() if callable(_state._material_authority_complete_swap_routing_reason_helper) else 'complete_swap_routing'
            _state._queue_source_material_plan_refresh(force_plan=True, reason=routing_reason)
        _call_if_alignment_widgets_live(_state._refresh_output_impact_review)
        _call_if_alignment_widgets_live(_state._queue_texture_preview_refresh)
    _state._apply_complete_external_swap_routing_to_ui = _apply_complete_external_swap_routing_to_ui

def _routing_complete_swap_step_007(_state):

    def _select_complete_swap_material_profile_silently(profile_name: str, *, persist: bool=False) -> None:
        block_signals = getattr(_state.complete_swap_material_profile_combo, 'blockSignals', None)
        if not callable(block_signals) or not callable(_state._select_complete_swap_material_profile):
            return
        previous_blocked = bool(block_signals(True))
        try:
            _state._select_complete_swap_material_profile(profile_name, persist=persist)
        finally:
            block_signals(previous_blocked)
    _state._select_complete_swap_material_profile_silently = _select_complete_swap_material_profile_silently

def _routing_complete_swap_step_008(_state):

    def _complete_swap_widgets_live() -> bool:
        return bool(callable(_state._alignment_dialog_widgets_live) and _state._alignment_dialog_widgets_live())
    _state._complete_swap_widgets_live = _complete_swap_widgets_live

def _routing_complete_swap_step_009(_state):

    def _complete_swap_refresh_sidecar_options() -> None:
        if callable(_state._refresh_sidecar_option_state):
            _state._refresh_sidecar_option_state()
    _state._complete_swap_refresh_sidecar_options = _complete_swap_refresh_sidecar_options

def _routing_complete_swap_step_010(_state):

    def _sync_complete_external_swap_mode(checked: bool, *, push_undo: bool = True) -> None:
        if not _state._complete_swap_widgets_live():
            return
        current_generation = _state.complete_external_swap_checkbox.property('transition_generation')
        if callable(_state._material_authority_complete_swap_next_transition_generation_helper):
            transition_generation = _state._material_authority_complete_swap_next_transition_generation_helper(current_generation)
        else:
            try:
                transition_generation = int(current_generation or 0) + 1
            except (TypeError, ValueError):
                transition_generation = 1
        _state.complete_external_swap_checkbox.setProperty('transition_generation', transition_generation)
        if callable(_state._set_alignment_d3d11_progress) and callable(_state._material_authority_complete_swap_update_queued_message_helper):
            live_frame_available = bool(_state._alignment_d3d11_live_frame_available()) if callable(_state._alignment_d3d11_live_frame_available) else False
            _state._set_alignment_d3d11_progress(5, _state._material_authority_complete_swap_update_queued_message_helper(), stage='complete_swap_toggle_queued', active=not live_frame_available)
        if callable(_state._material_authority_complete_swap_update_performance_helper) and callable(_state._set_preview_performance_status):
            complete_swap_performance = _state._material_authority_complete_swap_update_performance_helper()
            _state._set_preview_performance_status(complete_swap_performance.summary, details=complete_swap_performance.details)
        if checked:
            forced_child_states = None
            if callable(_state._material_authority_complete_swap_forced_child_states_helper):
                forced_child_states = _state._material_authority_complete_swap_forced_child_states_helper(rebuild_sidecar=_state.rebuild_sidecar_checkbox.isChecked(), inject_base_color=_state.inject_base_color_checkbox.isChecked(), source_color_faithful=_state.source_color_faithful_checkbox.isChecked(), external_material_reset=_state.external_material_reset_checkbox.isChecked(), prune_unmapped_original_dds=_state.prune_unmapped_original_dds_checkbox.isChecked())
            _state.complete_external_swap_checkbox.setProperty('previous_forced_child_states', forced_child_states)
            if callable(_state._set_checkbox_checked_silently_helper):
                _state._set_checkbox_checked_silently_helper(_state.rebuild_sidecar_checkbox, True)
                _state._set_checkbox_checked_silently_helper(_state.inject_base_color_checkbox, True)
                _state._set_checkbox_checked_silently_helper(_state.source_color_faithful_checkbox, True)
                _state._set_checkbox_checked_silently_helper(_state.external_material_reset_checkbox, True)
                _state._set_checkbox_checked_silently_helper(_state.prune_unmapped_original_dds_checkbox, True)
            find_data = getattr(_state.texture_output_size_combo, 'findData', None)
            if callable(find_data) and callable(_state._set_combo_index_silently_helper) and callable(_state._material_authority_complete_swap_source_output_size_index_helper):
                _state._set_combo_index_silently_helper(_state.texture_output_size_combo, _state._material_authority_complete_swap_source_output_size_index_helper(find_data('source')))
            current_data = getattr(_state.complete_swap_material_profile_combo, 'currentData', None)
            if callable(current_data) and callable(_state._material_authority_complete_swap_profile_name_helper):
                current_profile = current_data()
                _state._select_complete_swap_material_profile_silently(_state._material_authority_complete_swap_profile_name_helper(current_profile), persist=True)
            _state._complete_swap_refresh_sidecar_options()

            def _apply_checked_complete_swap() -> None:
                if not _state._complete_swap_widgets_live():
                    return
                if callable(_state._material_authority_complete_swap_should_apply_checked_helper) and (not _state._material_authority_complete_swap_should_apply_checked_helper(current_generation=_state.complete_external_swap_checkbox.property('transition_generation'), expected_generation=transition_generation, checked=_state.complete_external_swap_checkbox.isChecked())):
                    return
                _state._apply_complete_external_swap_routing_to_ui(push_undo=push_undo)
            _state.QTimer.singleShot(0, _apply_checked_complete_swap)
        else:
            previous_states = _state._material_authority_complete_swap_restored_child_states_helper(_state.complete_external_swap_checkbox.property('previous_forced_child_states')) if callable(_state._material_authority_complete_swap_restored_child_states_helper) else None
            if previous_states is not None and callable(_state._set_checkbox_checked_silently_helper):
                _state._set_checkbox_checked_silently_helper(_state.rebuild_sidecar_checkbox, previous_states['rebuild_sidecar'])
                _state._set_checkbox_checked_silently_helper(_state.inject_base_color_checkbox, previous_states['inject_base_color'])
                _state._set_checkbox_checked_silently_helper(_state.source_color_faithful_checkbox, previous_states['source_color_faithful'])
                _state._set_checkbox_checked_silently_helper(_state.external_material_reset_checkbox, previous_states['external_material_reset'])
                _state._set_checkbox_checked_silently_helper(_state.prune_unmapped_original_dds_checkbox, previous_states['prune_unmapped_original_dds'])
            _state.complete_external_swap_checkbox.setProperty('previous_forced_child_states', None)
            _state._complete_swap_refresh_sidecar_options()
            if not _state._complete_swap_widgets_live():
                return
            try:
                if callable(_state._refresh_output_impact_review):
                    _state._refresh_output_impact_review()
                if callable(_state._queue_texture_preview_refresh):
                    _state._queue_texture_preview_refresh()
            except RuntimeError as exc:
                message = str(exc)
                if 'already deleted' not in message and 'Internal C++ object' not in message:
                    raise
    _state._sync_complete_external_swap_mode = _sync_complete_external_swap_mode

def _routing_complete_swap_step_011(_state):
    _state._factory_result_values.update({'_complete_external_swap_mappings': _state._complete_external_swap_mappings, '_apply_complete_external_swap_routing_to_ui': _state._apply_complete_external_swap_routing_to_ui, '_select_complete_swap_material_profile_silently': _state._select_complete_swap_material_profile_silently, '_sync_complete_external_swap_mode': _state._sync_complete_external_swap_mode})

STEPS = (
    _routing_complete_swap_step_001,
    _routing_complete_swap_step_002,
    _routing_complete_swap_step_003,
    _routing_complete_swap_step_004,
    _routing_complete_swap_step_005,
    _routing_complete_swap_step_006,
    _routing_complete_swap_step_007,
    _routing_complete_swap_step_008,
    _routing_complete_swap_step_009,
    _routing_complete_swap_step_010,
    _routing_complete_swap_step_011,
)
