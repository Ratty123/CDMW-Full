from __future__ import annotations

def _accept_build_step_001(_state):
    _state.List = _state.context.get('List')
    _state.Mapping = _state.context.get('Mapping')
    _state.Optional = _state.context.get('Optional')
    _state.QMessageBox = _state.context.get('QMessageBox')
    _state.StaticMeshReplacementOptions = _state.context.get('StaticMeshReplacementOptions')
    _state.StaticSubmeshMapping = _state.context.get('StaticSubmeshMapping')
    _state.StaticTextureSlotOverride = _state.context.get('StaticTextureSlotOverride')
    _state.Tuple = _state.context.get('Tuple')
    _state._alignment_accept_handler_failed_status_helper = _state.context.get('_alignment_accept_handler_failed_status_helper')
    _state._alignment_build_status_finished_helper = _state.context.get('_alignment_build_status_finished_helper')
    _state._alignment_build_status_started_helper = _state.context.get('_alignment_build_status_started_helper')
    _state._alignment_builder_warning_title_helper = _state.context.get('_alignment_builder_warning_title_helper')
    _state._alignment_custom_icon_override_spec = _state.context.get('_alignment_custom_icon_override_spec')
    _state._commit_spinbox_text = _state.context.get('_commit_spinbox_text')
    _state._complete_external_swap_enabled = _state.context.get('_complete_external_swap_enabled')
    _state._complete_external_swap_mappings = _state.context.get('_complete_external_swap_mappings')
    _state._copied_source_texture_slot_overrides = _state.context.get('_copied_source_texture_slot_overrides')
    _state._current_complete_swap_material_profile_token = _state.context.get('_current_complete_swap_material_profile_token')
    _state._current_static_placement_snapshot = _state.context.get('_current_static_placement_snapshot')
    _state._flush_source_role_overrides_for_export = _state.context.get('_flush_source_role_overrides_for_export')
    _state._modify_original_texture_tuning_enabled = _state.context.get('_modify_original_texture_tuning_enabled')
    _state._invalid_submesh_mapping_missing_source_message_helper = _state.context.get('_invalid_submesh_mapping_missing_source_message_helper')
    _state._invalid_submesh_mapping_non_numeric_message_helper = _state.context.get('_invalid_submesh_mapping_non_numeric_message_helper')
    _state._invalid_submesh_mapping_title_helper = _state.context.get('_invalid_submesh_mapping_title_helper')
    _state._is_marker_source = _state.context.get('_is_marker_source')
    _state._mapping_table_build_complete_helper = _state.context.get('_mapping_table_build_complete_helper')
    _state._mapping_vertex_limit_issues = _state.context.get('_mapping_vertex_limit_issues')
    _state._mesh_replacement_too_large_message_helper = _state.context.get('_mesh_replacement_too_large_message_helper')
    _state._mesh_replacement_too_large_title_helper = _state.context.get('_mesh_replacement_too_large_title_helper')
    _state._save_texture_transform_controls = _state.context.get('_save_texture_transform_controls')
    _state._source_display_name = _state.context.get('_source_display_name')
    _state._source_part_added_export_blocker_message_helper = _state.context.get('_source_part_added_export_blocker_message_helper')
    _state._source_part_added_export_blocker_title_helper = _state.context.get('_source_part_added_export_blocker_title_helper')
    _state._source_renderable_indices_helper = _state.context.get('_source_renderable_indices_helper')
    _state._static_options_from_placement_snapshot = _state.context.get('_static_options_from_placement_snapshot')
    _state._target_submesh_display_name_helper = _state.context.get('_target_submesh_display_name_helper')
    _state._texture_row_effective_source_helper = _state.context.get('_texture_row_effective_source_helper')
    _state._texture_slot_contract_key = _state.context.get('_texture_slot_contract_key')
    _state._unmapped_appended_source_indices = _state.context.get('_unmapped_appended_source_indices')
    _state._update_selected_part_adjustment = _state.context.get('_update_selected_part_adjustment')
    _state._validate_mapping_text_source_indices_helper = _state.context.get('_validate_mapping_text_source_indices_helper')
    _state._vertex_limit_issue_display_text_helper = _state.context.get('_vertex_limit_issue_display_text_helper')
    _state.accent_glow_spin = _state.context.get('accent_glow_spin')
    _state.auto_brightness_spin = _state.context.get('auto_brightness_spin')
    _state.build_accept_state = _state.context.get('build_accept_state')
    _state.build_status_bar = _state.context.get('build_status_bar')
    _state.build_status_label = _state.context.get('build_status_label')
    _state.custom_icon_checkbox = _state.context.get('custom_icon_checkbox')
    _state.dialog = _state.context.get('dialog')
    _state.dialog_added_supplemental_files = _state.context.get('dialog_added_supplemental_files')
    _state.edge_relief_source_combo = _state.context.get('edge_relief_source_combo')
    _state.edge_relief_spin = _state.context.get('edge_relief_spin')
    _state.external_material_reset_checkbox = _state.context.get('external_material_reset_checkbox')
    _state.global_gloss_reduction_spin = _state.context.get('global_gloss_reduction_spin')
    _state.import_button = _state.context.get('import_button')
    _state.inject_base_color_checkbox = _state.context.get('inject_base_color_checkbox')
    _state.mapping_edits = _state.context.get('mapping_edits')
    _state.mapping_table_build_state = _state.context.get('mapping_table_build_state')
    _state.mesh_edit_iterations_spin = _state.context.get('mesh_edit_iterations_spin')
    _state.mesh_edit_radius_spin = _state.context.get('mesh_edit_radius_spin')
    _state.mesh_edit_strength_spin = _state.context.get('mesh_edit_strength_spin')
    _state.modify_original_clone_mode = bool(_state.context.get('modify_original_clone_mode'))
    _state.offset_x_spin = _state.context.get('offset_x_spin')
    _state.offset_y_spin = _state.context.get('offset_y_spin')
    _state.offset_z_spin = _state.context.get('offset_z_spin')
    _state.on_accept = _state.context.get('on_accept')
    _state.original_mesh_for_mapping = _state.context.get('original_mesh_for_mapping')
    _state.part_nudge_step_spin = _state.context.get('part_nudge_step_spin')
    _state.part_offset_x_spin = _state.context.get('part_offset_x_spin')
    _state.part_offset_y_spin = _state.context.get('part_offset_y_spin')
    _state.part_offset_z_spin = _state.context.get('part_offset_z_spin')
    _state.part_rotate_x_spin = _state.context.get('part_rotate_x_spin')
    _state.part_rotate_y_spin = _state.context.get('part_rotate_y_spin')
    _state.part_rotate_z_spin = _state.context.get('part_rotate_z_spin')
    _state.part_scale_x_spin = _state.context.get('part_scale_x_spin')
    _state.part_scale_y_spin = _state.context.get('part_scale_y_spin')
    _state.part_scale_z_spin = _state.context.get('part_scale_z_spin')
    _state.part_uniform_spin = _state.context.get('part_uniform_spin')
    _state.prune_unmapped_original_dds_checkbox = _state.context.get('prune_unmapped_original_dds_checkbox')
    _state.rebuild_sidecar_checkbox = _state.context.get('rebuild_sidecar_checkbox')
    _state.replacement_export_allowed = _state.context.get('replacement_export_allowed')
    _state.replacement_mesh_for_mapping = _state.context.get('replacement_mesh_for_mapping')
    _state.rotate_x_spin = _state.context.get('rotate_x_spin')
    _state.rotate_y_spin = _state.context.get('rotate_y_spin')
    _state.rotate_z_spin = _state.context.get('rotate_z_spin')
    _state.scale_x_spin = _state.context.get('scale_x_spin')
    _state.scale_y_spin = _state.context.get('scale_y_spin')
    _state.scale_z_spin = _state.context.get('scale_z_spin')
    _state.self = _state.context.get('self')
    _state.source_brightness_spin = _state.context.get('source_brightness_spin')
    _state.source_color_faithful_checkbox = _state.context.get('source_color_faithful_checkbox')
    _state.suggested_mappings = _state.context.get('suggested_mappings')
    _state.texture_output_size_combo = _state.context.get('texture_output_size_combo')
    _state.texture_override_assignments = _state.context.get('texture_override_assignments')
    _state.texture_override_rows = _state.context.get('texture_override_rows')
    _state.texture_transform_offset_u_spin = _state.context.get('texture_transform_offset_u_spin')
    _state.texture_transform_offset_v_spin = _state.context.get('texture_transform_offset_v_spin')
    _state.texture_transform_scale_u_spin = _state.context.get('texture_transform_scale_u_spin')
    _state.texture_transform_scale_v_spin = _state.context.get('texture_transform_scale_v_spin')
    _state.tone_contrast_spin = _state.context.get('tone_contrast_spin')

def _accept_build_step_002(_state):
    _state.unsafe_material_preflight_checkbox = _state.context.get('unsafe_material_preflight_checkbox')

def _accept_build_step_003(_state):

    def _modify_original_tuning_enabled_value() -> bool:
        if not callable(_state._modify_original_texture_tuning_enabled):
            return False
        return bool(_state._modify_original_texture_tuning_enabled())
    _state._modify_original_tuning_enabled_value = _modify_original_tuning_enabled_value

def _accept_build_step_004(_state):

    def _apply_alignment_build_status_view(view_state: Mapping[str, object]) -> tuple[str, bool]:
        text = str(view_state.get('text', '') or '')
        try:
            _state.build_status_label.setText(text)
            _state.build_status_label.setVisible(bool(view_state.get('label_visible')))
            _state.build_status_bar.setVisible(bool(view_state.get('bar_visible')))
            if 'import_enabled' in view_state:
                _state.import_button.setEnabled(bool(view_state.get('import_enabled')))
        except RuntimeError:
            return (text, False)
        return (text, True)
    _state._apply_alignment_build_status_view = _apply_alignment_build_status_view

def _accept_build_step_005(_state):

    def _set_alignment_build_status(message: str) -> None:
        text, applied = _state._apply_alignment_build_status_view(_state._alignment_build_status_started_helper(message))
        if text and (not applied):
            _state.self.set_status_message(text)
    _state._set_alignment_build_status = _set_alignment_build_status

def _accept_build_step_006(_state):

    def _finish_alignment_build_state(message: str, success: bool) -> None:
        view_state = _state._alignment_build_status_finished_helper(_state.build_accept_state, message, success=success, export_allowed=bool(_state.replacement_export_allowed['allowed']))
        text, _applied = _state._apply_alignment_build_status_view(view_state)
        if text:
            _state.self.set_status_message(text, error=bool(view_state.get('status_error')))
    _state._finish_alignment_build_state = _finish_alignment_build_state

def _accept_build_step_007(_state):

    def _dispatch_alignment_accept(options: StaticMeshReplacementOptions) -> None:
        if _state.on_accept is None:
            return
        try:
            _state.on_accept(options)
        except Exception as exc:
            _state.self.set_status_message(_state._alignment_accept_handler_failed_status_helper(exc), error=True)
            _state.QMessageBox.warning(_state.dialog, _state._alignment_builder_warning_title_helper(), str(exc))
    _state._dispatch_alignment_accept = _dispatch_alignment_accept

def _accept_build_step_008(_state):

    def _commit_alignment_numeric_edits(*, refresh_preview: bool=True) -> None:
        # Manual Material Authority edits are debounced, so a build started
        # within the coalescing window must not read the previous profile.
        flush_manual_profile = getattr(
            _state.dialog, '_material_authority_flush_manual_profile_changes', None
        )
        if callable(flush_manual_profile):
            flush_manual_profile()
        for spin in (_state.offset_x_spin, _state.offset_y_spin, _state.offset_z_spin, _state.rotate_x_spin, _state.rotate_y_spin, _state.rotate_z_spin, _state.scale_x_spin, _state.scale_y_spin, _state.scale_z_spin, _state.part_offset_x_spin, _state.part_offset_y_spin, _state.part_offset_z_spin, _state.part_rotate_x_spin, _state.part_rotate_y_spin, _state.part_rotate_z_spin, _state.part_scale_x_spin, _state.part_scale_y_spin, _state.part_scale_z_spin, _state.part_uniform_spin, _state.part_nudge_step_spin, _state.mesh_edit_radius_spin, _state.mesh_edit_strength_spin, _state.mesh_edit_iterations_spin, _state.texture_transform_offset_u_spin, _state.texture_transform_offset_v_spin, _state.texture_transform_scale_u_spin, _state.texture_transform_scale_v_spin):
            _state._commit_spinbox_text(spin, block_signals=not bool(refresh_preview))
        _state._update_selected_part_adjustment(queue_preview=refresh_preview, push_undo=refresh_preview)
        _state._save_texture_transform_controls(queue_preview=refresh_preview)
    _state._commit_alignment_numeric_edits = _commit_alignment_numeric_edits

def _accept_build_step_009(_state):

    def _build_static_options_from_dialog(*, show_messages: bool=True, include_edited_source_mesh: bool=True) -> Optional[StaticMeshReplacementOptions]:
        _state._commit_alignment_numeric_edits(refresh_preview=False)
        parsed_mappings = list(_state.suggested_mappings or [])
        explicit_mapping_validation = False
        mapping_table_ready = True
        try:
            mapping_table_ready = _state._mapping_table_build_complete_helper(_state.mapping_table_build_state)
        except NameError:
            mapping_table_ready = True
        modify_original_tuning_enabled = _state._modify_original_tuning_enabled_value()
        complete_swap_enabled = bool(_state._complete_external_swap_enabled()) and (not _state.modify_original_clone_mode)
        resolved_material_state = getattr(_state.dialog, '_material_authority_resolved_state', None)
        resolved_status = getattr(getattr(resolved_material_state, 'status', None), 'value', '')
        material_state_ready = bool(
            getattr(resolved_material_state, 'build_allowed', False)
            and str(getattr(_state.dialog, '_material_authority_sync_status', '') or '') == str(resolved_status or '')
        )
        if (
            complete_swap_enabled
            and bool(getattr(_state.dialog, '_mesh_editor_embedded_dotnet_active', False))
            and not material_state_ready
        ):
            reason = str(
                getattr(_state.dialog, '_material_authority_sync_reason', '')
                or 'The latest Material Authority revision is not acknowledged by the active .NET preview.'
            )
            if show_messages:
                _state.QMessageBox.warning(_state.dialog, 'Build Mod', f'Build is blocked: {reason}')
            return None
        if complete_swap_enabled and _state.original_mesh_for_mapping is not None and (_state.replacement_mesh_for_mapping is not None):
            parsed_mappings = _state._complete_external_swap_mappings()
            explicit_mapping_validation = True
        elif _state.mapping_edits and mapping_table_ready and (_state.original_mesh_for_mapping is not None) and (_state.replacement_mesh_for_mapping is not None):
            render_source_indices = set(_state._source_renderable_indices_helper(_state.replacement_mesh_for_mapping, is_marker_source=_state._is_marker_source, require_enabled=False))
            parsed_mappings: _state.List[_state.StaticSubmeshMapping] = []
            for target_index, edit in _state.mapping_edits:
                raw_text = str(edit.property('committed_mapping_text') or edit.text() or '').strip()
                validation = _state._validate_mapping_text_source_indices_helper(raw_text, render_source_indices)
                if validation.invalid_token:
                    if show_messages:
                        _state.QMessageBox.warning(_state.dialog, _state._invalid_submesh_mapping_title_helper(), _state._invalid_submesh_mapping_non_numeric_message_helper(target_index, validation.invalid_token))
                    return None
                if validation.missing_source_index is not None:
                    if show_messages:
                        _state.QMessageBox.warning(_state.dialog, _state._invalid_submesh_mapping_title_helper(), _state._invalid_submesh_mapping_missing_source_message_helper(target_index, validation.missing_source_index))
                    return None
                source_indices = list(validation.source_indices)
                target = _state.original_mesh_for_mapping.submeshes[target_index]
                parsed_mappings.append(_state.StaticSubmeshMapping(target_submesh_index=target_index, target_submesh_name=_state._target_submesh_display_name_helper(target_index, target), source_submesh_indices=source_indices, target_material_slot_index=target_index, merge_sources=True))
            explicit_mapping_validation = True
        if explicit_mapping_validation:
            vertex_limit_issues = _state._mapping_vertex_limit_issues(parsed_mappings)
            if vertex_limit_issues:
                displayed_issues = _state._vertex_limit_issue_display_text_helper(vertex_limit_issues)
                if show_messages:
                    _state.QMessageBox.warning(_state.dialog, _state._mesh_replacement_too_large_title_helper(), _state._mesh_replacement_too_large_message_helper(displayed_issues))
                return None
            unmapped_added_sources = _state._unmapped_appended_source_indices(parsed_mappings)
            if unmapped_added_sources:
                displayed_sources = '\n'.join((f'- {_state._source_display_name(source_index)}' for source_index in unmapped_added_sources[:10]))
                if len(unmapped_added_sources) > 10:
                    displayed_sources += f'\n- ... {len(unmapped_added_sources) - 10} more'
                if show_messages:
                    _state.QMessageBox.warning(_state.dialog, _state._source_part_added_export_blocker_title_helper(), _state._source_part_added_export_blocker_message_helper(displayed_sources))
                return None
        texture_slot_overrides: _state.List[_state.StaticTextureSlotOverride] = []
        occupied_texture_override_keys: set[_state.Tuple[str, str]] = set()
        if not _state.modify_original_clone_mode:
            for texture_row in _state.texture_override_rows:
                source_path = _state._texture_row_effective_source_helper(texture_row, _state.texture_override_assignments)
                if not source_path:
                    continue
                target_path = str(texture_row.get('target_path', '') or '')
                slot_kind = str(texture_row.get('slot_kind', '') or 'material')
                occupied_texture_override_keys.add((target_path.replace('\\', '/').lower(), _state._texture_slot_contract_key(slot_kind)))
                texture_slot_overrides.append(_state.StaticTextureSlotOverride(target_texture_path=target_path, source_path=source_path, slot_kind=slot_kind, target_material_name=str(texture_row.get('target_name', '') or ''), enabled=True))
            texture_slot_overrides.extend(_state._copied_source_texture_slot_overrides(parsed_mappings, occupied_keys=occupied_texture_override_keys))
        custom_item_icon_override = None
        if _state.custom_icon_checkbox.isChecked():
            custom_item_icon_override = _state._alignment_custom_icon_override_spec(show_messages=show_messages)
            if custom_item_icon_override is None:
                return None
        try:
            _state._flush_source_role_overrides_for_export()
        except NameError:
            pass
        placement_snapshot = _state._current_static_placement_snapshot(parsed_mappings, include_preview_only_independent_parts=False)
        options = _state._static_options_from_placement_snapshot(placement_snapshot, texture_slot_overrides=texture_slot_overrides, include_edited_source_mesh=bool(include_edited_source_mesh), rebuild_material_sidecar=bool(modify_original_tuning_enabled if _state.modify_original_clone_mode else _state.rebuild_sidecar_checkbox.isChecked() or complete_swap_enabled), complete_external_swap=bool(False if _state.modify_original_clone_mode else complete_swap_enabled), neutralize_inherited_material_layers=bool(False if _state.modify_original_clone_mode else _state.source_color_faithful_checkbox.isChecked() or complete_swap_enabled), complete_external_material_reset=bool(modify_original_tuning_enabled if _state.modify_original_clone_mode else _state.external_material_reset_checkbox.isChecked() or complete_swap_enabled), enable_missing_base_color_parameters=bool(False if _state.modify_original_clone_mode else _state.inject_base_color_checkbox.isChecked() or complete_swap_enabled), texture_output_size_mode=str(_state.texture_output_size_combo.currentData() or 'source'), complete_swap_material_profile=str(_state._current_complete_swap_material_profile_token()), global_gloss_reduction=0.0 if _state.modify_original_clone_mode else float(_state.global_gloss_reduction_spin.value()), edge_relief_strength=0.0 if _state.modify_original_clone_mode else float(_state.edge_relief_spin.value()), edge_relief_source='hybrid' if _state.modify_original_clone_mode else str(_state.edge_relief_source_combo.currentData() or 'hybrid'), accent_glow_strength=0.0 if _state.modify_original_clone_mode else float(_state.accent_glow_spin.value()), auto_brightness_balance=0.0 if _state.modify_original_clone_mode else float(_state.auto_brightness_spin.value()), dark_detail_lift=0.0 if _state.modify_original_clone_mode else float(_state.source_brightness_spin.value()), tone_contrast=0.0 if _state.modify_original_clone_mode else float(_state.tone_contrast_spin.value()), allow_unsafe_material_preflight_export=bool(False if _state.modify_original_clone_mode else _state.unsafe_material_preflight_checkbox.isChecked()), additional_supplemental_files=[] if _state.modify_original_clone_mode else list(_state.dialog_added_supplemental_files), custom_item_icon_override=custom_item_icon_override, prune_unmapped_original_texture_parameters=bool(False if _state.modify_original_clone_mode else _state.prune_unmapped_original_dds_checkbox.isChecked() or complete_swap_enabled))
        if complete_swap_enabled and material_state_ready:
            options.material_authority_fingerprint = str(getattr(resolved_material_state, 'fingerprint', '') or '')
            options.material_authority_revision = int(getattr(resolved_material_state, 'revision', 0) or 0)
            options.material_authority_resolved_bindings = [
                dict(binding) for binding in tuple(getattr(resolved_material_state, 'dds_bindings', ()) or ())
            ]
            options.material_authority_residual_parameter_groups = [
                dict(group) for group in tuple(getattr(resolved_material_state, 'residual_parameter_groups', ()) or ())
            ]
        if bool(_state.context.get('full_import_model_replacement')):
            from cdmw.services.mesh_workflow_service import apply_full_import_model_replacement_preset
            return apply_full_import_model_replacement_preset(options)
        return options
    _state._build_static_options_from_dialog = _build_static_options_from_dialog

def _accept_build_step_010(_state):
    _state._factory_result_values.update({'_apply_alignment_build_status_view': _state._apply_alignment_build_status_view, '_set_alignment_build_status': _state._set_alignment_build_status, '_finish_alignment_build_state': _state._finish_alignment_build_state, '_dispatch_alignment_accept': _state._dispatch_alignment_accept, '_commit_alignment_numeric_edits': _state._commit_alignment_numeric_edits, '_build_static_options_from_dialog': _state._build_static_options_from_dialog})

STEPS = (
    _accept_build_step_001,
    _accept_build_step_002,
    _accept_build_step_003,
    _accept_build_step_004,
    _accept_build_step_005,
    _accept_build_step_006,
    _accept_build_step_007,
    _accept_build_step_008,
    _accept_build_step_009,
    _accept_build_step_010,
)
