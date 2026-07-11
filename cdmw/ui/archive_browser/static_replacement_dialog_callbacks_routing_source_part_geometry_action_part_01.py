from __future__ import annotations

def _routing_source_part_geometry_action_step_001(_state):
    _state.Path = _state.context.get('Path')
    _state.SCENE_TEXTURE_SOURCE_EXTENSIONS = _state.context.get('SCENE_TEXTURE_SOURCE_EXTENSIONS')
    _state.Sequence = _state.context.get('Sequence')
    _state._alignment_mesh_edit_tab_active = _state.context.get('_alignment_mesh_edit_tab_active')
    _state._ensure_source_part_adjustment = _state.context.get('_ensure_source_part_adjustment')
    _state._load_selected_part_controls = _state.context.get('_load_selected_part_controls')
    _state._push_geometry_undo_snapshot = _state.context.get('_push_geometry_undo_snapshot')
    _state._queue_static_preview_rebuild = _state.context.get('_queue_static_preview_rebuild')
    _state._reference_vertices_for_appended_part = _state.context.get('_reference_vertices_for_appended_part')
    _state._register_dialog_supplemental_file_helper = _state.context.get('_register_dialog_supplemental_file_helper')
    _state._selected_target_index = _state.context.get('_selected_target_index')
    _state._set_double_spin_value_silently_helper = _state.context.get('_set_double_spin_value_silently_helper')
    _state._source_part_appended_work_area_fit_state_helper = _state.context.get('_source_part_appended_work_area_fit_state_helper')
    _state._source_part_center_on_target_state_helper = _state.context.get('_source_part_center_on_target_state_helper')
    _state._source_part_edit_undo_label_helper = _state.context.get('_source_part_edit_undo_label_helper')
    _state._source_part_fit_size_state_helper = _state.context.get('_source_part_fit_size_state_helper')
    _state._source_part_nudge_delta_helper = _state.context.get('_source_part_nudge_delta_helper')
    _state._transformed_vertices_for_work_area = _state.context.get('_transformed_vertices_for_work_area')
    _state._update_selected_part_adjustment = _state.context.get('_update_selected_part_adjustment')
    _state.adjustment = _state.context.get('adjustment')
    _state.axis = _state.context.get('axis')
    _state.center_state = _state.context.get('center_state')
    _state.delta = _state.context.get('delta')
    _state.dialog_added_supplemental_files = _state.context.get('dialog_added_supplemental_files')
    _state.direction = _state.context.get('direction')
    _state.dx = _state.context.get('dx')
    _state.dy = _state.context.get('dy')
    _state.dz = _state.context.get('dz')
    _state.fit_state = _state.context.get('fit_state')
    _state.mesh = _state.context.get('mesh')
    _state.original_mesh_for_mapping = _state.context.get('original_mesh_for_mapping')
    _state.part_nudge_step_spin = _state.context.get('part_nudge_step_spin')
    _state.part_offset_x_spin = _state.context.get('part_offset_x_spin')
    _state.part_offset_y_spin = _state.context.get('part_offset_y_spin')
    _state.part_offset_z_spin = _state.context.get('part_offset_z_spin')
    _state.path = _state.context.get('path')
    _state.refresh_parsed_mesh_totals = _state.context.get('refresh_parsed_mesh_totals')
    _state.replacement_mesh_base_for_mapping = _state.context.get('replacement_mesh_base_for_mapping')
    _state.replacement_mesh_for_mapping = _state.context.get('replacement_mesh_for_mapping')
    _state.selected_source_part = _state.context.get('selected_source_part')
    _state.self = _state.context.get('self')
    _state.source_index = _state.context.get('source_index')
    _state.source_indices = _state.context.get('source_indices')
    _state.spin = _state.context.get('spin')
    _state.submesh = _state.context.get('submesh')
    _state.supplemental_files = _state.context.get('supplemental_files')
    _state.texture_files_for_mapping = _state.context.get('texture_files_for_mapping')
    _state.value = _state.context.get('value')

def _routing_source_part_geometry_action_step_002(_state):

    def _active_mesh_edit_source_part_geometry_action_blocked(action: str) -> bool:
        if not (callable(_state._alignment_mesh_edit_tab_active) and _state._alignment_mesh_edit_tab_active()):
            return False
        message = f'Active Mesh Editor source-part {action} requires native geometry execution; Python geometry mutation fallback is disabled.'
        set_status_message = getattr(_state.self, 'set_status_message', None)
        if callable(set_status_message):
            set_status_message(message, error=True)
        return True
    _state._active_mesh_edit_source_part_geometry_action_blocked = _active_mesh_edit_source_part_geometry_action_blocked

def _routing_source_part_geometry_action_step_003(_state):

    def _normalize_appended_part_to_work_area(source_indices: Sequence[int]) -> str:
        if _state._active_mesh_edit_source_part_geometry_action_blocked('work-area normalization'):
            return ''
        if _state.replacement_mesh_for_mapping is None or _state.replacement_mesh_base_for_mapping is None:
            return ''
        fit_state = _state._source_part_appended_work_area_fit_state_helper(source_indices=source_indices, source_count=len(_state.replacement_mesh_for_mapping.submeshes), replacement_mesh=_state.replacement_mesh_for_mapping, reference_vertices=_state._reference_vertices_for_appended_part())
        if not fit_state.should_apply or fit_state.fit is None:
            return ''
        for mesh in (_state.replacement_mesh_for_mapping, _state.replacement_mesh_base_for_mapping):
            for source_index in fit_state.source_indices:
                if 0 <= source_index < len(mesh.submeshes):
                    submesh = mesh.submeshes[source_index]
                    submesh.vertices = _state._transformed_vertices_for_work_area(submesh.vertices or [], fit_state.fit)
                    submesh.vertex_count = len(submesh.vertices)
                    submesh.face_count = len(submesh.faces)
            _state.refresh_parsed_mesh_totals(mesh)
        return fit_state.placement_note
    _state._normalize_appended_part_to_work_area = _normalize_appended_part_to_work_area

def _routing_source_part_geometry_action_step_004(_state):

    def _fit_selected_part_size() -> None:
        if _state._active_mesh_edit_source_part_geometry_action_blocked('fit-size'):
            return
        if _state.replacement_mesh_for_mapping is None or _state.original_mesh_for_mapping is None:
            return
        fit_state = _state._source_part_fit_size_state_helper(source_index=int(_state.selected_source_part.get('index', -1)), target_index=_state._selected_target_index(), replacement_mesh=_state.replacement_mesh_for_mapping, original_mesh=_state.original_mesh_for_mapping)
        if not fit_state.available or fit_state.uniform_scale is None:
            return
        _state._push_geometry_undo_snapshot(_state._source_part_edit_undo_label_helper('fit'))
        adjustment = _state._ensure_source_part_adjustment(fit_state.source_index)
        adjustment.uniform_scale = fit_state.uniform_scale
        adjustment.scale_xyz = (1.0, 1.0, 1.0)
        _state._load_selected_part_controls()
        _state._queue_static_preview_rebuild()
    _state._fit_selected_part_size = _fit_selected_part_size

def _routing_source_part_geometry_action_step_005(_state):

    def _nudge_selected_part(dx: float, dy: float, dz: float) -> None:
        if _state._active_mesh_edit_source_part_geometry_action_blocked('nudge'):
            return
        source_index = int(_state.selected_source_part.get('index', -1))
        if source_index < 0:
            return
        _state._push_geometry_undo_snapshot(_state._source_part_edit_undo_label_helper('nudge'))
        for spin, delta in ((_state.part_offset_x_spin, dx), (_state.part_offset_y_spin, dy), (_state.part_offset_z_spin, dz)):
            _state._set_double_spin_value_silently_helper(spin, float(spin.value()) + float(delta))
            _state._sync_part_slider_from_spin(spin)
        _state._update_selected_part_adjustment()
    _state._nudge_selected_part = _nudge_selected_part

def _routing_source_part_geometry_action_step_006(_state):

    def _nudge_selected_part_axis(axis: str, direction: float) -> None:
        _state._nudge_selected_part(*_state._source_part_nudge_delta_helper(axis, float(_state.part_nudge_step_spin.value()), direction))
    _state._nudge_selected_part_axis = _nudge_selected_part_axis

def _routing_source_part_geometry_action_step_007(_state):

    def _center_selected_part_on_target() -> None:
        if _state._active_mesh_edit_source_part_geometry_action_blocked('center-on-target'):
            return
        if _state.replacement_mesh_for_mapping is None or _state.original_mesh_for_mapping is None:
            return
        center_state = _state._source_part_center_on_target_state_helper(source_index=int(_state.selected_source_part.get('index', -1)), target_index=_state._selected_target_index(), replacement_mesh=_state.replacement_mesh_for_mapping, original_mesh=_state.original_mesh_for_mapping)
        if not center_state.available or center_state.offset is None:
            return
        _state._push_geometry_undo_snapshot(_state._source_part_edit_undo_label_helper('center'))
        for spin, value in ((_state.part_offset_x_spin, center_state.offset[0]), (_state.part_offset_y_spin, center_state.offset[1]), (_state.part_offset_z_spin, center_state.offset[2])):
            _state._set_double_spin_value_silently_helper(spin, value)
            _state._sync_part_slider_from_spin(spin)
        _state._update_selected_part_adjustment()
    _state._center_selected_part_on_target = _center_selected_part_on_target

def _routing_source_part_geometry_action_step_008(_state):

    def _add_dialog_supplemental_file(path: Path) -> None:
        _state._register_dialog_supplemental_file_helper(path, dialog_added_supplemental_files=_state.dialog_added_supplemental_files, supplemental_files=_state.supplemental_files or (), texture_files_for_mapping=_state.texture_files_for_mapping, allowed_texture_extensions=_state.SCENE_TEXTURE_SOURCE_EXTENSIONS)
    _state._add_dialog_supplemental_file = _add_dialog_supplemental_file

def _routing_source_part_geometry_action_step_009(_state):
    _state._factory_result_values.update({'_normalize_appended_part_to_work_area': _state._normalize_appended_part_to_work_area, '_fit_selected_part_size': _state._fit_selected_part_size, '_nudge_selected_part': _state._nudge_selected_part, '_nudge_selected_part_axis': _state._nudge_selected_part_axis, '_center_selected_part_on_target': _state._center_selected_part_on_target, '_add_dialog_supplemental_file': _state._add_dialog_supplemental_file})

STEPS = (
    _routing_source_part_geometry_action_step_001,
    _routing_source_part_geometry_action_step_002,
    _routing_source_part_geometry_action_step_003,
    _routing_source_part_geometry_action_step_004,
    _routing_source_part_geometry_action_step_005,
    _routing_source_part_geometry_action_step_006,
    _routing_source_part_geometry_action_step_007,
    _routing_source_part_geometry_action_step_008,
    _routing_source_part_geometry_action_step_009,
)
