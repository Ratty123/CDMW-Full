from __future__ import annotations

def _remaining_static_preview_refresh_step_001(_state):
    _state.state = _state._StaticReplacementDialogState(_state.context)
    _state.List = _state.context.get('List')
    _state.ModelPreviewData = _state.context.get('ModelPreviewData')
    _state.NativePreviewPanel = _state.context.get('NativePreviewPanel')
    _state._accent_glow_preview_intensity_helper = _state.context.get('_accent_glow_preview_intensity_helper')
    _state._alignment_d3d11_alignment_preview_failed_performance_helper = _state.context.get('_alignment_d3d11_alignment_preview_failed_performance_helper')
    _state._alignment_d3d11_display_model_helper = _state.context.get('_alignment_d3d11_display_model_helper')
    _state._alignment_d3d11_package_queued_performance_helper = _state.context.get('_alignment_d3d11_package_queued_performance_helper')
    _state._alignment_d3d11_preview_active = _state.context.get('_alignment_d3d11_preview_active')
    _state._alignment_d3d11_record_direct_source_preview_flags_helper = _state.context.get('_alignment_d3d11_record_direct_source_preview_flags_helper')
    _state._alignment_mesh_edit_tab_active = _state.context.get('_alignment_mesh_edit_tab_active')
    _state._alignment_preview_is_interactive = _state.context.get('_alignment_preview_is_interactive')
    _state._alignment_preview_quality_label_helper = _state.context.get('_alignment_preview_quality_label_helper')
    _state._alignment_preview_source_face_limit = _state.context.get('_alignment_preview_source_face_limit')
    _state._alignment_preview_widget_render_settings = _state.context.get('_alignment_preview_widget_render_settings')
    _state._append_selected_source_highlight_overlay = _state.context.get('_append_selected_source_highlight_overlay')
    _state._apply_manual_preview_texture_override_specs_helper = _state.context.get('_apply_manual_preview_texture_override_specs_helper')
    _state._apply_original_material_preview = _state.context.get('_apply_original_material_preview')
    _state._apply_source_material_preview_for_model_helper = _state.context.get('_apply_source_material_preview_for_model_helper')
    _state._apply_source_role_emissive_preview_for_model_helper = _state.context.get('_apply_source_role_emissive_preview_for_model_helper')
    _state._basic_controls_profile_enabled = _state.context.get('_basic_controls_profile_enabled')
    _state._build_direct_source_preview_model = _state.context.get('_build_direct_source_preview_model')
    _state._cached_static_preview_geometry_helper = _state.context.get('_cached_static_preview_geometry_helper')
    _state._capture_static_preview_baked_transform_state = _state.context.get('_capture_static_preview_baked_transform_state')
    _state._clear_source_parts_preview_rebuild_pending = _state.context.get('_clear_source_parts_preview_rebuild_pending')
    _state._clone_preview_model = _state.context.get('_clone_preview_model')
    _state._combine_preview_models = _state.context.get('_combine_preview_models')
    _state._complete_external_swap_enabled = _state.context.get('_complete_external_swap_enabled')
    _state._current_alignment_transform_generation = _state.context.get('_current_alignment_transform_generation')
    _state._current_complete_swap_material_profile_token = _state.context.get('_current_complete_swap_material_profile_token')
    _state._current_dialog_mappings_for_preview = _state.context.get('_current_dialog_mappings_for_preview')
    _state._current_material_authority_preview_profile = _state.context.get('_current_material_authority_preview_profile')
    _state._current_static_placement_snapshot = _state.context.get('_current_static_placement_snapshot')
    _state._modify_original_texture_tuning_enabled = _state.context.get('_modify_original_texture_tuning_enabled')
    _state._direct_source_preview_indices_helper = _state.context.get('_direct_source_preview_indices_helper')
    _state._ensure_original_reference_texture_preview_ready = _state.context.get('_ensure_original_reference_texture_preview_ready')
    _state._infer_model_preview_normal_strength = _state.context.get('_infer_model_preview_normal_strength')
    _state._is_gltf_metallic_roughness_path = _state.context.get('_is_gltf_metallic_roughness_path')
    _state._mapped_source_indices = _state.context.get('_mapped_source_indices')
    _state._mapped_source_indices_helper = _state.context.get('_mapped_source_indices_helper')
    _state._material_authority_preview_inactive_reason = _state.context.get('_material_authority_preview_inactive_reason')
    _state._material_authority_preview_parameters_helper = _state.context.get('_material_authority_preview_parameters_helper')
    _state._material_authority_preview_signature = _state.context.get('_material_authority_preview_signature')
    _state._mesh_edit_preview_source_indices = _state.context.get('_mesh_edit_preview_source_indices')
    _state._original_overlay_preview_model_state_helper = _state.context.get('_original_overlay_preview_model_state_helper')
    _state._original_texture_preview_material_preview_enabled_helper = _state.context.get('_original_texture_preview_material_preview_enabled_helper')
    _state._overlay_editable_mesh_state_helper = _state.context.get('_overlay_editable_mesh_state_helper')

def _remaining_static_preview_refresh_step_002(_state):

    def _alignment_transform_generation() -> int:
        if not callable(_state._current_alignment_transform_generation):
            return 0
        return int(_state._current_alignment_transform_generation() or 0)
    _state._alignment_transform_generation = _alignment_transform_generation

def _remaining_static_preview_refresh_step_003(_state):

    def _mesh_edit_tab_active() -> bool:
        if not callable(_state._alignment_mesh_edit_tab_active):
            return False
        return bool(_state._alignment_mesh_edit_tab_active())
    _state._mesh_edit_tab_active = _mesh_edit_tab_active

def _remaining_static_preview_refresh_step_004(_state):

    def _mesh_edit_enabled_checked() -> bool:
        is_checked = getattr(_state.mesh_edit_enabled_checkbox, 'isChecked', None)
        if not callable(is_checked):
            return False
        try:
            return bool(is_checked())
        except RuntimeError:
            return False
    _state._mesh_edit_enabled_checked = _mesh_edit_enabled_checked

def _remaining_static_preview_refresh_step_005(_state):

    def _alignment_preview_is_interactive_value() -> bool:
        if not callable(_state._alignment_preview_is_interactive):
            return False
        return bool(_state._alignment_preview_is_interactive())
    _state._alignment_preview_is_interactive_value = _alignment_preview_is_interactive_value

def _remaining_static_preview_refresh_step_006(_state):

    def _basic_controls_profile_enabled_value() -> bool:
        if not callable(_state._basic_controls_profile_enabled):
            return False
        return bool(_state._basic_controls_profile_enabled())
    _state._basic_controls_profile_enabled_value = _basic_controls_profile_enabled_value

def _remaining_static_preview_refresh_step_007(_state):

    def _complete_external_swap_enabled_value() -> bool:
        if not callable(_state._complete_external_swap_enabled):
            return False
        return bool(_state._complete_external_swap_enabled())
    _state._complete_external_swap_enabled_value = _complete_external_swap_enabled_value

def _remaining_static_preview_refresh_step_008(_state):

    def _modify_original_tuning_enabled_value() -> bool:
        if not callable(_state._modify_original_texture_tuning_enabled):
            return False
        return bool(_state._modify_original_texture_tuning_enabled())
    _state._modify_original_tuning_enabled_value = _modify_original_tuning_enabled_value

def _remaining_static_preview_refresh_step_009(_state):

    def _complete_swap_material_profile_token_value() -> str:
        if not callable(_state._current_complete_swap_material_profile_token):
            return ''
        return str(_state._current_complete_swap_material_profile_token() or '')
    _state._complete_swap_material_profile_token_value = _complete_swap_material_profile_token_value

def _remaining_static_preview_refresh_step_010(_state):

    def _material_authority_preview_inactive_reason_value() -> str:
        if not callable(_state._material_authority_preview_inactive_reason):
            return ''
        return str(_state._material_authority_preview_inactive_reason() or '')
    _state._material_authority_preview_inactive_reason_value = _material_authority_preview_inactive_reason_value

def _remaining_static_preview_refresh_step_011(_state):

    def _mesh_edit_preview_source_indices_value() -> tuple[int, ...]:
        if not callable(_state._mesh_edit_preview_source_indices):
            return ()
        return tuple(_state._mesh_edit_preview_source_indices() or ())
    _state._mesh_edit_preview_source_indices_value = _mesh_edit_preview_source_indices_value

def _remaining_static_preview_refresh_step_012(_state):

    def _mapped_source_indices_value(mappings: object) -> set[int]:
        if callable(_state._mapped_source_indices):
            return set(_state._mapped_source_indices(mappings) or ())
        if callable(_state._mapped_source_indices_helper):
            return set(_state._mapped_source_indices_helper(mappings) or ())
        return set()
    _state._mapped_source_indices_value = _mapped_source_indices_value

def _remaining_static_preview_refresh_step_013(_state):
    _state._preview_model_in_original_frame = _state.context.get('_preview_model_in_original_frame')
    _state._preview_target_mesh_indices = _state.context.get('_preview_target_mesh_indices')
    _state._queue_alignment_d3d11_preview = _state.context.get('_queue_alignment_d3d11_preview')
    _state._record_runtime_event = _state.context.get('_record_runtime_event')
    if not callable(_state._record_runtime_event):
        _state._record_runtime_event = lambda *_args, **_kwargs: None
    _state._refresh_alignment_virtual_sidecar_contract = _state.context.get('_refresh_alignment_virtual_sidecar_contract')
    _state._remember_alignment_d3d11_source_editor_ids = _state.context.get('_remember_alignment_d3d11_source_editor_ids')
    _state._resolve_model_texture_semantic_details = _state.context.get('_resolve_model_texture_semantic_details')
    _state._restore_static_preview_geometry_cache_payload_helper = _state.context.get('_restore_static_preview_geometry_cache_payload_helper')
    _state._selected_part_preview_indices = _state.context.get('_selected_part_preview_indices')
    _state._set_alignment_d3d11_loading = _state.context.get('_set_alignment_d3d11_loading')
    _state._set_cached_static_preview_model = _state.context.get('_set_cached_static_preview_model')
    _state._set_preview_performance_status = _state.context.get('_set_preview_performance_status')
    _state._should_use_direct_source_preview_helper = _state.context.get('_should_use_direct_source_preview_helper')
    _state._source_display_name = _state.context.get('_source_display_name')
    _state._source_index_is_enabled_renderable = _state.context.get('_source_index_is_enabled_renderable')
    _state._source_preview_geometry_cache_key_helper = _state.context.get('_source_preview_geometry_cache_key_helper')
    _state._source_preview_geometry_key = _state.context.get('_source_preview_geometry_key')
    _state._static_options_from_placement_snapshot = _state.context.get('_static_options_from_placement_snapshot')
    _state._static_preview_geometry_cache_payload_helper = _state.context.get('_static_preview_geometry_cache_payload_helper')
    _state._static_preview_prepared_cache_key_helper = _state.context.get('_static_preview_prepared_cache_key_helper')
    _state._static_preview_prepared_cache_result_helper = _state.context.get('_static_preview_prepared_cache_result_helper')
    _state._static_preview_refresh_performance_status_helper = _state.context.get('_static_preview_refresh_performance_status_helper')
    _state._static_preview_refresh_route_state_helper = _state.context.get('_static_preview_refresh_route_state_helper')
    _state._static_preview_upload_elapsed_ms_helper = _state.context.get('_static_preview_upload_elapsed_ms_helper')
    _state._static_preview_widget_mode_state_helper = _state.context.get('_static_preview_widget_mode_state_helper')
    _state._static_preview_widget_model_action_helper = _state.context.get('_static_preview_widget_model_action_helper')
    _state._store_static_preview_cache_entry_helper = _state.context.get('_store_static_preview_cache_entry_helper')
    _state._sync_mesh_edit_preview_settings = _state.context.get('_sync_mesh_edit_preview_settings')
    _state._tag_alignment_d3d11_workspace_model = _state.context.get('_tag_alignment_d3d11_workspace_model')
    _state._texture_set_factor_parameters = _state.context.get('_texture_set_factor_parameters')
    _state._texture_set_for_mapping_helper = _state.context.get('_texture_set_for_mapping_helper')
    _state._texture_set_for_source_index = _state.context.get('_texture_set_for_source_index')
    _state.accent_glow_spin = _state.context.get('accent_glow_spin')
    _state.active_preview_mode = _state.context.get('active_preview_mode')
    _state.alignment_d3d11_state = _state.context.get('alignment_d3d11_state')
    _state.appended_source_indices = _state.context.get('appended_source_indices')
    _state.auto_brightness_spin = _state.context.get('auto_brightness_spin')
    _state.build_static_replacement_preview_mesh = _state.context.get('build_static_replacement_preview_mesh')
    _state.cache_key = _state.context.get('cache_key')
    _state.cache_suffix = _state.context.get('cache_suffix')
    _state.cached_preview = _state.context.get('cached_preview')
    _state.contract = _state.context.get('contract')
    _state.current_mappings = _state.context.get('current_mappings')
    _state.d3d11_preview_model = _state.context.get('d3d11_preview_model')
    _state.defer_original_texture_preview = _state.context.get('defer_original_texture_preview')
    _state.dialog_title = _state.context.get('dialog_title')
    _state.direct_source_preview_index_map = _state.context.get('direct_source_preview_index_map')
    _state.direct_source_preview_indices = _state.context.get('direct_source_preview_indices')
    _state.edge_relief_source_combo = _state.context.get('edge_relief_source_combo')
    _state.edge_relief_spin = _state.context.get('edge_relief_spin')
    _state.editable_kind = _state.context.get('editable_kind')
    _state.editable_value = _state.context.get('editable_value')
    _state.entry = _state.context.get('entry')
    _state.exc = _state.context.get('exc')
    _state.force_direct_source_preview = _state.context.get('force_direct_source_preview')
    _state.geometry_elapsed_ms = _state.context.get('geometry_elapsed_ms')
    _state.geometry_started = _state.context.get('geometry_started')
    _state.global_gloss_reduction_spin = _state.context.get('global_gloss_reduction_spin')
    _state.highlighted_original_indices = _state.context.get('highlighted_original_indices')
    _state.highlighted_source_indices = _state.context.get('highlighted_source_indices')
    _state.independent_base_index = _state.context.get('independent_base_index')
    _state.independent_ordinal = _state.context.get('independent_ordinal')
    _state.independent_part = _state.context.get('independent_part')
    _state.independent_preview_parts = _state.context.get('independent_preview_parts')
    _state.interactive_preview = _state.context.get('interactive_preview')
    _state.live_mesh_edit = _state.context.get('live_mesh_edit')
    _state.mapped = _state.context.get('mapped')
    _state.mapped_preview = _state.context.get('mapped_preview')
    _state.mapped_preview_source_indices = _state.context.get('mapped_preview_source_indices')
    _state.mapping = _state.context.get('mapping')
    _state.mappings = _state.context.get('mappings')
    _state.material_authority_preview_signature_state = _state.context.get('material_authority_preview_signature_state')
    _state.material_authority_preview_texture_slots = _state.context.get('material_authority_preview_texture_slots')
    _state.mesh_edit_direct_source_preview = _state.context.get('mesh_edit_direct_source_preview')
    _state.mesh_edit_enabled_checkbox = _state.context.get('mesh_edit_enabled_checkbox')
    _state.model = _state.context.get('model')
    _state.modify_original_clone_mode = _state.context.get('modify_original_clone_mode')
    _state.needs_original_material_preview = _state.context.get('needs_original_material_preview')
    _state.original_mesh_count = _state.context.get('original_mesh_count')
    _state.original_mesh_for_mapping = _state.context.get('original_mesh_for_mapping')
    _state.original_overlay_model = _state.context.get('original_overlay_model')
    _state.original_texture_preview_state = _state.context.get('original_texture_preview_state')
    _state.overlay_dialog_preview = _state.context.get('overlay_dialog_preview')
    _state.overlay_model = _state.context.get('overlay_model')
    _state.overlay_original_locked_checkbox = _state.context.get('overlay_original_locked_checkbox')
    _state.overlay_view_state = _state.context.get('overlay_view_state')
    _state.package_queued_presentation = _state.context.get('package_queued_presentation')
    _state.parsed_submesh_index = _state.context.get('parsed_submesh_index')

def _remaining_static_preview_refresh_step_014(_state):
    _state.placement_snapshot = _state.context.get('placement_snapshot')
    _state.prepare_model_preview = _state.context.get('prepare_model_preview')
    _state.prepared_cache_result = _state.context.get('prepared_cache_result')
    _state.prepared_elapsed_ms = _state.context.get('prepared_elapsed_ms')
    _state.prepared_key = _state.context.get('prepared_key')
    _state.preview_accent_glow_intensity = _state.context.get('preview_accent_glow_intensity')
    _state.preview_controls_ready = _state.context.get('preview_controls_ready')
    _state.preview_failed_presentation = _state.context.get('preview_failed_presentation')
    _state.preview_index = _state.context.get('preview_index')
    _state.preview_material_authority_parameters = _state.context.get('preview_material_authority_parameters')
    _state.preview_material_authority_profile = _state.context.get('preview_material_authority_profile')
    _state.preview_mesh = _state.context.get('preview_mesh')
    _state.preview_mode_combo = _state.context.get('preview_mode_combo')
    _state.preview_model = _state.context.get('preview_model')
    _state.preview_performance = _state.context.get('preview_performance')
    _state.preview_replacement_mesh = _state.context.get('preview_replacement_mesh')
    _state.preview_submesh_index_map = _state.context.get('preview_submesh_index_map')
    _state.preview_widget = _state.context.get('preview_widget')
    _state.refresh_elapsed_ms = _state.context.get('refresh_elapsed_ms')
    _state.refresh_route = _state.context.get('refresh_route')
    _state.refresh_started = _state.context.get('refresh_started')
    _state.refresh_transform_generation = _state.context.get('refresh_transform_generation')
    _state.refreshed_preview_widgets = _state.context.get('refreshed_preview_widgets')
    _state.replacement_mesh_count = _state.context.get('replacement_mesh_count')
    _state.replacement_only_preview = _state.context.get('replacement_only_preview')
    _state.replacement_only_view_state = _state.context.get('replacement_only_view_state')
    _state.replacement_texture_slot_preview_semantics = _state.context.get('replacement_texture_slot_preview_semantics')
    _state.selected_preview_indices = _state.context.get('selected_preview_indices')
    _state.selected_source_highlight_indices = _state.context.get('selected_source_highlight_indices')
    _state.source_brightness_spin = _state.context.get('source_brightness_spin')
    _state.source_indices = _state.context.get('source_indices')
    _state.source_model = _state.context.get('source_model')
    _state.source_overlay_preview_index_map = _state.context.get('source_overlay_preview_index_map')
    _state.source_part_adjustments = _state.context.get('source_part_adjustments')
    _state.source_preview_cache_key = _state.context.get('source_preview_cache_key')
    _state.source_role_profile = _state.context.get('source_role_profile')
    _state.source_selection_overlay_editor_id_map = _state.context.get('source_selection_overlay_editor_id_map')
    _state.source_selection_overlay_preview_index_map = _state.context.get('source_selection_overlay_preview_index_map')
    _state.static_dialog_preview = _state.context.get('static_dialog_preview')
    _state.static_preview_geometry_cache = _state.context.get('static_preview_geometry_cache')
    _state.static_preview_prepared_cache = _state.context.get('static_preview_prepared_cache')
    _state.static_view_state = _state.context.get('static_view_state')
    _state.target_name = _state.context.get('target_name')
    _state.texture_overrides_dirty = _state.context.get('texture_overrides_dirty')
    _state.time = _state.context.get('time')
    _state.tone_contrast_spin = _state.context.get('tone_contrast_spin')
    _state.prompt_shell_context = _state.context.get('prompt_shell_context')
    _state.updated_specs = _state.context.get('updated_specs')
    _state.upload_elapsed_ms = _state.context.get('upload_elapsed_ms')
    _state.use_direct_source_preview = _state.context.get('use_direct_source_preview')
    _state.use_original_material_preview = _state.context.get('use_original_material_preview')
    _state.view_state = _state.context.get('view_state')
    _state.widget = _state.context.get('widget')
    _state.widget_action = _state.context.get('widget_action')
    _state.widget_mode_state = _state.context.get('widget_mode_state')

    def _preview_control_value(name: str, method_name: str, default: object) -> object:
        widget = getattr(_state, name, None)
        if widget is None and isinstance(_state.prompt_shell_context, dict):
            widget = _state.prompt_shell_context.get(name)
        method = getattr(widget, method_name, None)
        if not callable(method):
            return default
        try:
            return method()
        except RuntimeError:
            return default

    _state._preview_control_value = _preview_control_value

def _remaining_static_preview_refresh_step_015(_state):

    def _empty_direct_source_preview_model() -> ModelPreviewData:
        reference_model = _state.state.original_reference_preview_model or _state.state.replacement_preview_model
        return _state.ModelPreviewData(path=str(getattr(_state.state.replacement_preview_model, 'path', '') or ''), format=str(getattr(_state.state.replacement_preview_model, 'format', '') or ''), summary='0 visible replacement mesh part(s).', mesh_count=0, vertex_count=0, face_count=0, normalization_center=tuple(getattr(reference_model, 'normalization_center', (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0)), normalization_scale=float(getattr(reference_model, 'normalization_scale', 1.0) or 1.0), meshes=[])
    _state._empty_direct_source_preview_model = _empty_direct_source_preview_model

def _remaining_static_preview_refresh_step_016(_state):

    def _set_cached_static_preview_model(widget: NativePreviewPanel, model: ModelPreviewData, view_state: object, *, cache_suffix: str, live_mesh_edit, source_preview_cache_key, active_preview_mode, selected_preview_indices, refreshed_preview_widgets) -> float:
        prepared_elapsed_ms = 0.0
        interactive_preview = _state._alignment_preview_is_interactive_value()
        widget.set_render_settings(_state._alignment_preview_widget_render_settings())
        widget.set_use_textures(True)
        widget.set_high_quality_textures(not interactive_preview)
        prepared_key = _state._static_preview_prepared_cache_key_helper(model, source_preview_cache_key=source_preview_cache_key, active_preview_mode=active_preview_mode, cache_suffix=cache_suffix, selected_preview_indices=selected_preview_indices, highlighted_source_indices=tuple(_state.highlighted_source_indices), highlighted_original_indices=tuple(_state.highlighted_original_indices), texture_override_preview_specs=_state.state.texture_override_preview_specs, material_authority_preview_signature=_state.material_authority_preview_signature_state.get('cache', ''))
        widget_action = _state._static_preview_widget_model_action_helper(live_mesh_edit=live_mesh_edit, prepared_key=prepared_key)
        if widget_action.preserve_mesh_edit_cache:
            widget.set_model_preserving_view(model, preserve_mesh_edit_cache=True)
            refreshed_preview_widgets.append(widget)
            return prepared_elapsed_ms
        elif widget_action.use_prepared_cache:
            prepared_cache_result = _state._static_preview_prepared_cache_result_helper(_state.static_preview_prepared_cache, model, prepared_key=widget_action.prepared_key, prepare_model_preview=_state.prepare_model_preview)
            prepared_elapsed_ms += prepared_cache_result.prepare_elapsed_ms
            widget.set_prepared_model(prepared_cache_result.prepared_model, prepared_cache_result.prepared_preview, prepare_elapsed_ms=prepared_cache_result.prepare_elapsed_ms)
        else:
            widget.set_model(model)
        refreshed_preview_widgets.append(widget)
        widget.restore_view_state(view_state)
        return prepared_elapsed_ms
    _state._set_cached_static_preview_model = _set_cached_static_preview_model

def _remaining_static_preview_refresh_step_017(_state):

    def _queue_static_d3d11_preview_if_active(preview_model, active_preview_mode, selected_preview_indices, refresh_transform_generation, refresh_started) -> bool:
        if not _state._alignment_d3d11_preview_active():
            return False
        d3d11_preview_model = _state._alignment_d3d11_display_model_helper(preview_model, _state.state.original_reference_preview_model, active_preview_mode=active_preview_mode, tag_workspace_model=_state._tag_alignment_d3d11_workspace_model, combine_preview_models=_state._combine_preview_models, clone_model=_state._clone_preview_model)
        _state._record_runtime_event('mesh_alignment_preview_refresh_d3d11', path=getattr(_state.entry, 'path', ''), dialog_title=_state.dialog_title, active_preview_mode=active_preview_mode, d3d11_model_ready=d3d11_preview_model is not None, source_model_meshes=len(getattr(preview_model, 'meshes', ()) or ()), original_model_meshes=len(getattr(_state.state.original_reference_preview_model, 'meshes', ()) or ()), modify_original_clone=_state.modify_original_clone_mode)
        preview_queued = bool(
            d3d11_preview_model is not None
            and _state._queue_alignment_d3d11_preview(
                d3d11_preview_model,
                label=f"{active_preview_mode.replace('_', ' ').title()} alignment preview",
            )
        )
        if not preview_queued:
            return False
        _state._sync_mesh_edit_preview_settings()
        _state._capture_static_preview_baked_transform_state(selected_preview_indices, transform_generation=refresh_transform_generation)
        package_queued_presentation = _state._alignment_d3d11_package_queued_performance_helper(quality_label=_state._alignment_preview_quality_label_helper(_state.alignment_d3d11_state), refresh_elapsed_ms=(_state.time.perf_counter() - refresh_started) * 1000.0)
        _state._set_preview_performance_status(package_queued_presentation.summary, details=package_queued_presentation.details)
        return True
    _state._queue_static_d3d11_preview_if_active = _queue_static_d3d11_preview_if_active

def _remaining_static_preview_refresh_step_018(_state):

    def _finish_static_preview_widgets(active_preview_mode, geometry_elapsed_ms, live_mesh_edit, overlay_view_state, prepared_elapsed_ms, preview_model, refresh_started, refresh_transform_generation, refreshed_preview_widgets, replacement_only_view_state, selected_preview_indices, source_preview_cache_key, static_view_state):
        widget_mode_state = _state._static_preview_widget_mode_state_helper(active_preview_mode)
        if widget_mode_state.update_side_by_side:
            prepared_elapsed_ms += _state._set_cached_static_preview_model(_state.static_dialog_preview, preview_model, static_view_state, cache_suffix='side_by_side', live_mesh_edit=live_mesh_edit, source_preview_cache_key=source_preview_cache_key, active_preview_mode=active_preview_mode, selected_preview_indices=selected_preview_indices, refreshed_preview_widgets=refreshed_preview_widgets)
            if selected_preview_indices is not None:
                _state.static_dialog_preview.set_alignment_editable_mesh_indices(selected_preview_indices)
            else:
                _state.static_dialog_preview.set_alignment_editable_mesh_range(0, -1)
        elif widget_mode_state.update_replacement_only:
            _state._set_cached_static_preview_model(_state.replacement_only_preview, preview_model, replacement_only_view_state, cache_suffix='replacement_only')
            if selected_preview_indices is not None:
                _state.replacement_only_preview.set_alignment_editable_mesh_indices(selected_preview_indices)
            else:
                _state.replacement_only_preview.set_alignment_editable_mesh_range(0, -1)
        if widget_mode_state.update_overlay and _state.state.original_reference_preview_model is not None:
            original_overlay_model = _state._original_overlay_preview_model_state_helper(_state.state.original_reference_preview_model, highlighted_indices=_state.highlighted_original_indices, highlight_color=(1.0, 0.72, 0.22))
            overlay_model = _state._combine_preview_models(original_overlay_model, preview_model)
            if overlay_model is not None:
                interactive_preview = _state._alignment_preview_is_interactive_value()
                _state.overlay_dialog_preview.set_render_settings(_state._alignment_preview_widget_render_settings())
                _state.overlay_dialog_preview.set_use_textures(True)
                _state.overlay_dialog_preview.set_high_quality_textures(not interactive_preview)
                if live_mesh_edit:
                    _state.overlay_dialog_preview.set_model_preserving_view(overlay_model, preserve_mesh_edit_cache=True)
                else:
                    _state.overlay_dialog_preview.set_model(overlay_model)
                    _state.overlay_dialog_preview.restore_view_state(overlay_view_state)
                refreshed_preview_widgets.append(_state.overlay_dialog_preview)
                original_mesh_count = len(getattr(_state.state.original_reference_preview_model, 'meshes', ()) or ())
                replacement_mesh_count = len(getattr(preview_model, 'meshes', ()) or ())
                editable_kind, editable_value = _state._overlay_editable_mesh_state_helper(original_mesh_count, replacement_mesh_count, selected_preview_indices=selected_preview_indices, original_locked=_state.overlay_original_locked_checkbox.isChecked())
                if editable_kind == 'indices':
                    _state.overlay_dialog_preview.set_alignment_editable_mesh_indices(list(editable_value))
                else:
                    _state.overlay_dialog_preview.set_alignment_editable_mesh_range(*editable_value)
        _state._sync_mesh_edit_preview_settings()
        _state._capture_static_preview_baked_transform_state(selected_preview_indices, transform_generation=refresh_transform_generation)
        upload_elapsed_ms = _state._static_preview_upload_elapsed_ms_helper(refreshed_preview_widgets)
        refresh_elapsed_ms = (_state.time.perf_counter() - refresh_started) * 1000.0
        preview_performance = _state._static_preview_refresh_performance_status_helper(quality_label=_state._alignment_preview_quality_label_helper(_state.alignment_d3d11_state), refresh_ms=refresh_elapsed_ms, geometry_ms=geometry_elapsed_ms, prepare_ms=prepared_elapsed_ms, upload_ms=upload_elapsed_ms)
        _state._set_preview_performance_status(preview_performance.text, details=preview_performance.tooltip)
        _state._clear_source_parts_preview_rebuild_pending()
    _state._finish_static_preview_widgets = _finish_static_preview_widgets

def _remaining_static_preview_refresh_step_019(_state):

    def _refresh_static_dialog_preview(*, live_mesh_edit: bool=False) -> None:
        refresh_started = _state.time.perf_counter()
        refresh_transform_generation = _state._alignment_transform_generation()
        geometry_elapsed_ms = 0.0
        prepared_elapsed_ms = 0.0
        if _state.state.replacement_preview_model is None:
            _state._record_runtime_event('mesh_alignment_preview_refresh_skipped', path=getattr(_state.entry, 'path', ''), dialog_title=_state.dialog_title, reason='missing_replacement_preview_model', modify_original_clone=_state.modify_original_clone_mode)
            return
        for preview_widget in (_state.static_dialog_preview, _state.overlay_dialog_preview, _state.replacement_only_preview):
            preview_widget.set_alignment_editing_enabled(True)
        current_mappings = _state._current_dialog_mappings_for_preview()
        mapped_preview = False
        source_preview_cache_key = ''
        active_preview_mode = str(_state.preview_mode_combo.currentData() or 'side_by_side')
        needs_original_material_preview = _state._original_texture_preview_material_preview_enabled_helper(_state.modify_original_clone_mode, _state.original_texture_preview_state)
        refresh_route = _state._static_preview_refresh_route_state_helper(active_preview_mode=active_preview_mode, mesh_edit_enabled=_state._mesh_edit_enabled_checked(), mesh_edit_tab_active=_state._mesh_edit_tab_active(), replacement_mesh_available=_state.state.replacement_mesh_for_mapping is not None, interactive_preview=_state._alignment_preview_is_interactive_value(), complete_external_swap_enabled=_state._complete_external_swap_enabled_value(), needs_original_material_preview=needs_original_material_preview, preview_controls_ready=bool(_state.preview_controls_ready.get('ready')), original_mesh_available=_state.original_mesh_for_mapping is not None)
        mesh_edit_direct_source_preview = refresh_route.mesh_edit_direct_source_preview
        force_direct_source_preview = _state._alignment_d3d11_record_direct_source_preview_flags_helper(_state.alignment_d3d11_state, replacement_only_direct_source_preview=refresh_route.replacement_only_direct_source_preview, source_owned_direct_source_preview=refresh_route.source_owned_direct_source_preview)
        original_reference_ready = True
        if refresh_route.require_original_reference:
            original_reference_ready = _state._ensure_original_reference_texture_preview_ready(active_preview_mode, reason='preview_refresh')
        if not original_reference_ready:
            wait_for_reference = refresh_route.waits_for_original_reference(ready=False)
            _state._record_runtime_event('mesh_alignment_preview_refresh_waiting', path=getattr(_state.entry, 'path', ''), dialog_title=_state.dialog_title, active_preview_mode=active_preview_mode, reason='original_reference_texture_preview', geometry_continues=not wait_for_reference, modify_original_clone=_state.modify_original_clone_mode)
            if wait_for_reference:
                return
        direct_source_preview_indices = _state._direct_source_preview_indices_helper(_state.selected_source_highlight_indices, force_direct_source_preview=force_direct_source_preview, replacement_submesh_count=len(getattr(_state.state.replacement_mesh_for_mapping, 'submeshes', ()) or ()), mesh_edit_direct_source_preview=mesh_edit_direct_source_preview, mesh_edit_source_indices=_state._mesh_edit_preview_source_indices_value() if mesh_edit_direct_source_preview else (), source_index_is_enabled_renderable=_state._source_index_is_enabled_renderable)
        mapped_preview_source_indices = _state._mapped_source_indices_value(current_mappings)
        use_direct_source_preview = _state._should_use_direct_source_preview_helper(direct_source_preview_indices, force_direct_source_preview=force_direct_source_preview, mesh_edit_direct_source_preview=mesh_edit_direct_source_preview, appended_source_indices=_state.appended_source_indices, mapped_source_indices=mapped_preview_source_indices, active_preview_mode=active_preview_mode, original_mesh_available=_state.original_mesh_for_mapping is not None, replacement_mesh_available=_state.state.replacement_mesh_for_mapping is not None)
        if not use_direct_source_preview:
            _state.direct_source_preview_index_map.clear()
        _state.source_overlay_preview_index_map.clear()
        _state.source_selection_overlay_preview_index_map.clear()
        _state.source_selection_overlay_editor_id_map.clear()
        _state.preview_submesh_index_map.clear()
        modify_original_tuning_enabled = _state._modify_original_tuning_enabled_value()
        if refresh_route.can_build_source_geometry:
            cache_key = ''
            if callable(_state._source_preview_geometry_key) and callable(_state._source_preview_geometry_cache_key_helper):
                cache_key = _state._source_preview_geometry_cache_key_helper(_state._source_preview_geometry_key(current_mappings), use_direct_source_preview=use_direct_source_preview, direct_source_preview_indices=direct_source_preview_indices)
            source_preview_cache_key = cache_key
            cached_preview = _state._cached_static_preview_geometry_helper(_state.static_preview_geometry_cache, cache_key, live_mesh_edit=live_mesh_edit) if cache_key else None
            if cached_preview is not None:
                source_model, mapped_preview = _state._restore_static_preview_geometry_cache_payload_helper(cached_preview, direct_source_preview_index_map=_state.direct_source_preview_index_map, source_overlay_preview_index_map=_state.source_overlay_preview_index_map, preview_submesh_index_map=_state.preview_submesh_index_map)
            else:
                try:
                    if use_direct_source_preview:
                        _state.direct_source_preview_index_map.clear()
                        _state.preview_submesh_index_map.clear()
                        source_model = _state._build_direct_source_preview_model(current_mappings, tuple(direct_source_preview_indices))
                        if source_model is None:
                            source_model = _state._empty_direct_source_preview_model()
                        mapped_preview = False
                    else:
                        preview_replacement_mesh = _state.state.replacement_mesh_for_mapping or _state.state.replacement_mesh_base_for_mapping
                        placement_snapshot = _state._current_static_placement_snapshot(current_mappings, include_preview_only_independent_parts=True)
                        independent_preview_parts = list(placement_snapshot.get('independent_output_parts', []) or [])
                        geometry_started = _state.time.perf_counter()
                        preview_mesh = _state.build_static_replacement_preview_mesh(_state.original_mesh_for_mapping, preview_replacement_mesh, _state._static_options_from_placement_snapshot(placement_snapshot, complete_external_swap=False if _state.modify_original_clone_mode else _state._complete_external_swap_enabled_value(), complete_external_material_reset=modify_original_tuning_enabled if _state.modify_original_clone_mode else _state._complete_external_swap_enabled_value(), complete_swap_material_profile=_state._complete_swap_material_profile_token_value(), global_gloss_reduction=0.0 if _state.modify_original_clone_mode else float(_state._preview_control_value('global_gloss_reduction_spin', 'value', 0.0)), edge_relief_strength=0.0 if _state.modify_original_clone_mode else float(_state._preview_control_value('edge_relief_spin', 'value', 0.0)), edge_relief_source='hybrid' if _state.modify_original_clone_mode else str(_state._preview_control_value('edge_relief_source_combo', 'currentData', 'hybrid') or 'hybrid'), accent_glow_strength=0.0 if _state.modify_original_clone_mode else float(_state._preview_control_value('accent_glow_spin', 'value', 0.0)), auto_brightness_balance=0.0 if _state.modify_original_clone_mode else float(_state._preview_control_value('auto_brightness_spin', 'value', 0.0)), dark_detail_lift=0.0 if _state.modify_original_clone_mode else float(_state._preview_control_value('source_brightness_spin', 'value', 0.0)), tone_contrast=0.0 if _state.modify_original_clone_mode else float(_state._preview_control_value('tone_contrast_spin', 'value', 0.0))), max_source_faces_per_submesh=_state._alignment_preview_source_face_limit())
                        geometry_elapsed_ms += (_state.time.perf_counter() - geometry_started) * 1000.0
                        _state.source_overlay_preview_index_map.clear()
                        _state.preview_submesh_index_map.clear()
                        independent_base_index = len(getattr(_state.original_mesh_for_mapping, 'submeshes', ()) or ())
                        source_model = _state._preview_model_in_original_frame(preview_mesh, parsed_submesh_index_map=_state.preview_submesh_index_map)
                        for independent_ordinal, independent_part in enumerate(independent_preview_parts):
                            parsed_submesh_index = independent_base_index + independent_ordinal
                            preview_index = _state.preview_submesh_index_map.get(parsed_submesh_index)
                            if preview_index is not None:
                                _state.source_overlay_preview_index_map[int(independent_part.source_submesh_index)] = preview_index
                        mapped_preview = True
                    if cache_key and (not live_mesh_edit):
                        _state._store_static_preview_cache_entry_helper(_state.static_preview_geometry_cache, cache_key, _state._static_preview_geometry_cache_payload_helper(source_model, mapped_preview=mapped_preview, direct_source_preview_index_map=_state.direct_source_preview_index_map, source_overlay_preview_index_map=_state.source_overlay_preview_index_map, preview_submesh_index_map=_state.preview_submesh_index_map), paired_cache_to_clear=_state.static_preview_prepared_cache)
                except Exception:
                    _state.preview_submesh_index_map.clear()
                    raise
        else:
            _state._record_runtime_event('mesh_alignment_preview_refresh_waiting', path=getattr(_state.entry, 'path', ''), dialog_title=_state.dialog_title, active_preview_mode=active_preview_mode, reason='source_geometry_not_ready', modify_original_clone=_state.modify_original_clone_mode)
            return
        preview_model = _state._clone_preview_model(source_model)
        _state._apply_original_material_preview(preview_model, mapped_preview=mapped_preview, current_mappings=current_mappings)
        try:
            preview_material_authority_profile = _state._current_material_authority_preview_profile()
        except Exception:
            preview_material_authority_profile = None
        preview_accent_glow_intensity = _state._accent_glow_preview_intensity_helper(preview_material_authority_profile) if preview_material_authority_profile is not None else 1.0
        material_authority_preview_route_enabled = bool(modify_original_tuning_enabled if _state.modify_original_clone_mode else _state._complete_external_swap_enabled_value())
        material_authority_preview_active = preview_material_authority_profile is not None and material_authority_preview_route_enabled and _state._basic_controls_profile_enabled_value()
        preview_material_authority_parameters = _state._material_authority_preview_parameters_helper(preview_material_authority_profile, enabled=True) if material_authority_preview_active else ()
        use_original_material_preview = _state._original_texture_preview_material_preview_enabled_helper(_state.modify_original_clone_mode, _state.original_texture_preview_state)
        if (_state.state.texture_sets or material_authority_preview_active) and (not use_original_material_preview) and (not mesh_edit_direct_source_preview):
            _state._apply_source_material_preview_for_model_helper(preview_model, use_direct_source_preview=use_direct_source_preview, direct_source_preview_index_map=_state.direct_source_preview_index_map, mapped_preview=mapped_preview, source_overlay_preview_index_map=_state.source_overlay_preview_index_map, current_mappings=current_mappings, texture_sets=_state.state.texture_sets, material_authority_profile=preview_material_authority_profile, complete_external_swap_enabled=material_authority_preview_route_enabled, basic_controls_profile_enabled=_state._basic_controls_profile_enabled_value(), texture_set_for_source_index=_state._texture_set_for_source_index, texture_set_for_mapping=lambda mapping: _state._texture_set_for_mapping_helper(mapping, texture_sets=_state.state.texture_sets, replacement_mesh=_state.state.replacement_mesh_for_mapping, texture_set_for_source_index=_state._texture_set_for_source_index), source_display_name=_state._source_display_name, preview_target_mesh_indices=_state._preview_target_mesh_indices, texture_set_factor_parameters=_state._texture_set_factor_parameters, material_authority_preview_texture_slots=_state.material_authority_preview_texture_slots, replacement_texture_slot_preview_semantics=_state.replacement_texture_slot_preview_semantics, resolve_model_texture_semantic_details=_state._resolve_model_texture_semantic_details, is_gltf_metallic_roughness_path=_state._is_gltf_metallic_roughness_path, infer_model_preview_normal_strength=_state._infer_model_preview_normal_strength, accent_glow_preview_intensity=preview_accent_glow_intensity)
        source_role_profile = preview_material_authority_profile if preview_material_authority_profile is not None else object()
        _state._apply_source_role_emissive_preview_for_model_helper(preview_model, use_direct_source_preview=use_direct_source_preview, direct_source_preview_index_map=_state.direct_source_preview_index_map, mapped_preview=mapped_preview, source_overlay_preview_index_map=_state.source_overlay_preview_index_map, current_mappings=current_mappings, texture_sets=_state.state.texture_sets, source_part_adjustments=_state.source_part_adjustments, profile=source_role_profile, texture_set_for_source_index=_state._texture_set_for_source_index, source_display_name=_state._source_display_name, preview_target_mesh_indices=_state._preview_target_mesh_indices)
        if _state._alignment_d3d11_preview_active():
            _state.source_selection_overlay_preview_index_map.clear()
            _state.source_selection_overlay_editor_id_map.clear()
        else:
            preview_model = _state._append_selected_source_highlight_overlay(preview_model, current_mappings)
        if not use_direct_source_preview and (not mesh_edit_direct_source_preview):
            if _state.texture_overrides_dirty['dirty']:
                contract = _state._refresh_alignment_virtual_sidecar_contract(current_mappings)
                updated_specs = list(contract.get('preview_specs') or ())
                _state.state.texture_override_preview_specs = updated_specs
                _state.texture_overrides_dirty['dirty'] = False
            _state._apply_manual_preview_texture_override_specs_helper(preview_model, _state.state.texture_override_preview_specs, mapped_preview=mapped_preview, current_mappings=current_mappings, preview_target_mesh_indices=lambda model, target_name, source_indices, mapped, mappings: _state._preview_target_mesh_indices(model, target_name, source_indices, mapped_preview=mapped, current_mappings=mappings), resolve_model_texture_semantic_details=_state._resolve_model_texture_semantic_details, replacement_texture_slot_preview_semantics=_state.replacement_texture_slot_preview_semantics, is_gltf_metallic_roughness_path=_state._is_gltf_metallic_roughness_path, infer_model_preview_normal_strength=_state._infer_model_preview_normal_strength, material_authority_preview_parameters=preview_material_authority_parameters, accent_glow_preview_intensity=preview_accent_glow_intensity)
        if not _state._material_authority_preview_inactive_reason_value():
            try:
                _state.material_authority_preview_signature_state.update(_state._material_authority_preview_signature())
            except Exception:
                pass
        static_view_state = _state.static_dialog_preview.view_state_snapshot()
        replacement_only_view_state = _state.replacement_only_preview.view_state_snapshot()
        overlay_view_state = _state.overlay_dialog_preview.view_state_snapshot()
        selected_preview_indices = _state._selected_part_preview_indices(preview_model, mapped_preview=mapped_preview, current_mappings=current_mappings)
        _state._remember_alignment_d3d11_source_editor_ids(preview_model, mapped_preview=mapped_preview, current_mappings=current_mappings)
        refreshed_preview_widgets: _state.List[_state.NativePreviewPanel] = []
        if _state._queue_static_d3d11_preview_if_active(preview_model, active_preview_mode, selected_preview_indices, refresh_transform_generation, refresh_started):
            return
        _state._finish_static_preview_widgets(active_preview_mode, geometry_elapsed_ms, live_mesh_edit, overlay_view_state, prepared_elapsed_ms, preview_model, refresh_started, refresh_transform_generation, refreshed_preview_widgets, replacement_only_view_state, selected_preview_indices, source_preview_cache_key, static_view_state)
    _state._refresh_static_dialog_preview = _refresh_static_dialog_preview

def _remaining_static_preview_refresh_step_020(_state):

    def _safe_refresh_static_dialog_preview(*, live_mesh_edit: bool=False) -> None:
        if live_mesh_edit and _state._mesh_edit_tab_active():
            message = 'Active Mesh Editor static preview refresh requires native D3D11; Python preview rebuild fallback is disabled.'
            _state._record_runtime_event('mesh_edit_static_preview_refresh_blocked', path=getattr(_state.entry, 'path', ''), dialog_title=_state.dialog_title, message=message)
            _state._set_alignment_d3d11_loading(False, message)
            _state._set_preview_performance_status(message, details=message)
            _state._clear_source_parts_preview_rebuild_pending()
            return
        try:
            _state._refresh_static_dialog_preview(live_mesh_edit=live_mesh_edit)
        except Exception as exc:
            _state._record_runtime_event('mesh_alignment_preview_refresh_failed', path=getattr(_state.entry, 'path', ''), dialog_title=_state.dialog_title, message=str(exc), traceback=_state.traceback.format_exc(), modify_original_clone=_state.modify_original_clone_mode, defer_original_texture_preview=_state.defer_original_texture_preview)
            _state._set_alignment_d3d11_loading(False, f'Preview failed: {exc}')
            preview_failed_presentation = _state._alignment_d3d11_alignment_preview_failed_performance_helper(str(exc))
            _state._set_preview_performance_status(preview_failed_presentation.summary, details=preview_failed_presentation.details)
            _state._clear_source_parts_preview_rebuild_pending()
    _state._safe_refresh_static_dialog_preview = _safe_refresh_static_dialog_preview

def _remaining_static_preview_refresh_step_021(_state):
    _state._factory_result_values.update({'_refresh_static_dialog_preview': _state._refresh_static_dialog_preview, '_safe_refresh_static_dialog_preview': _state._safe_refresh_static_dialog_preview})

STEPS = (
    _remaining_static_preview_refresh_step_001,
    _remaining_static_preview_refresh_step_002,
    _remaining_static_preview_refresh_step_003,
    _remaining_static_preview_refresh_step_004,
    _remaining_static_preview_refresh_step_005,
    _remaining_static_preview_refresh_step_006,
    _remaining_static_preview_refresh_step_007,
    _remaining_static_preview_refresh_step_008,
    _remaining_static_preview_refresh_step_009,
    _remaining_static_preview_refresh_step_010,
    _remaining_static_preview_refresh_step_011,
    _remaining_static_preview_refresh_step_012,
    _remaining_static_preview_refresh_step_013,
    _remaining_static_preview_refresh_step_014,
    _remaining_static_preview_refresh_step_015,
    _remaining_static_preview_refresh_step_016,
    _remaining_static_preview_refresh_step_017,
    _remaining_static_preview_refresh_step_018,
    _remaining_static_preview_refresh_step_019,
    _remaining_static_preview_refresh_step_020,
    _remaining_static_preview_refresh_step_021,
)
