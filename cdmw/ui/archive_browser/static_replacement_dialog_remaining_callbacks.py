"""Remaining static replacement dialog callback factories."""

from __future__ import annotations

import traceback
from types import SimpleNamespace


class _StaticReplacementDialogState:
    def __init__(self, context: dict[str, object]) -> None:
        self._get_preview_render_settings = context.get('_get_preview_render_settings')
        self._set_preview_render_settings = context.get('_set_preview_render_settings')
        self._get_replacement_mesh_for_mapping = context.get('_get_replacement_mesh_for_mapping')
        self._set_replacement_mesh_for_mapping = context.get('_set_replacement_mesh_for_mapping')
        self._get_replacement_mesh_base_for_mapping = context.get('_get_replacement_mesh_base_for_mapping')
        self._set_replacement_mesh_base_for_mapping = context.get('_set_replacement_mesh_base_for_mapping')
        self._get_replacement_preview_model = context.get('_get_replacement_preview_model')
        self._set_replacement_preview_model = context.get('_set_replacement_preview_model')
        self._get_texture_sets = context.get('_get_texture_sets')
        self._set_texture_sets = context.get('_set_texture_sets')
        self._get_texture_override_preview_specs = context.get('_get_texture_override_preview_specs')
        self._set_texture_override_preview_specs = context.get('_set_texture_override_preview_specs')
        self._get_original_reference_preview_model = context.get('_get_original_reference_preview_model')
        self._set_original_reference_preview_model = context.get('_set_original_reference_preview_model')

    @property
    def preview_render_settings(self):
        return self._get_preview_render_settings()

    @preview_render_settings.setter
    def preview_render_settings(self, value) -> None:
        self._set_preview_render_settings(value)

    @property
    def replacement_mesh_for_mapping(self):
        return self._get_replacement_mesh_for_mapping()

    @replacement_mesh_for_mapping.setter
    def replacement_mesh_for_mapping(self, value) -> None:
        self._set_replacement_mesh_for_mapping(value)

    @property
    def replacement_mesh_base_for_mapping(self):
        return self._get_replacement_mesh_base_for_mapping()

    @replacement_mesh_base_for_mapping.setter
    def replacement_mesh_base_for_mapping(self, value) -> None:
        self._set_replacement_mesh_base_for_mapping(value)

    @property
    def replacement_preview_model(self):
        return self._get_replacement_preview_model()

    @replacement_preview_model.setter
    def replacement_preview_model(self, value) -> None:
        self._set_replacement_preview_model(value)

    @property
    def texture_sets(self):
        return self._get_texture_sets()

    @texture_sets.setter
    def texture_sets(self, value) -> None:
        self._set_texture_sets(value)

    @property
    def texture_override_preview_specs(self):
        return self._get_texture_override_preview_specs()

    @texture_override_preview_specs.setter
    def texture_override_preview_specs(self, value) -> None:
        self._set_texture_override_preview_specs(value)

    @property
    def original_reference_preview_model(self):
        return self._get_original_reference_preview_model()

    @original_reference_preview_model.setter
    def original_reference_preview_model(self, value) -> None:
        self._set_original_reference_preview_model(value)



def create_alignment_preview_render_settings_callbacks(context: dict[str, object]) -> SimpleNamespace:
    state = _StaticReplacementDialogState(context)
    ARCHIVE_MODEL_RENDERER_D3D11 = context.get('ARCHIVE_MODEL_RENDERER_D3D11')
    ModelPreviewRenderSettings = context.get('ModelPreviewRenderSettings')
    Optional = context.get('Optional')
    _alignment_d3d11_invalidate_package_cache = context.get('_alignment_d3d11_invalidate_package_cache')
    _alignment_d3d11_package_settings_changed_helper = context.get('_alignment_d3d11_package_settings_changed_helper')
    _alignment_d3d11_preview_active = context.get('_alignment_d3d11_preview_active')
    _alignment_d3d11_render_settings_rebuild_performance_helper = context.get('_alignment_d3d11_render_settings_rebuild_performance_helper')
    _alignment_d3d11_render_settings_route_helper = context.get('_alignment_d3d11_render_settings_route_helper')
    _alignment_d3d11_render_tuning_live_performance_helper = context.get('_alignment_d3d11_render_tuning_live_performance_helper')
    _alignment_lit_render_settings = context.get('_alignment_lit_render_settings_helper') or context.get('_alignment_lit_render_settings')
    _alignment_renderer_backend_for_dialog = context.get('_alignment_renderer_backend_for_dialog')
    _mark_alignment_d3d11_rebuild_reason = context.get('_mark_alignment_d3d11_rebuild_reason')
    _queue_static_preview_refresh = context.get('_queue_static_preview_refresh')
    _rough_control_value_from_settings = context.get('_rough_control_value_from_settings')
    _set_alignment_renderer_from_dialog = context.get('_set_alignment_renderer_from_dialog')
    _set_preview_performance_status = context.get('_set_preview_performance_status')
    _set_preview_renderer = context.get('_set_preview_renderer')
    _sync_from_modal_settings = context.get('_sync_from_modal_settings')
    alignment_d3d11_preview_host = context.get('alignment_d3d11_preview_host')
    alignment_d3d11_view_mode_combo = context.get('alignment_d3d11_view_mode_combo')
    backend = context.get('backend')
    base = context.get('base')
    base_settings = context.get('base_settings')
    checkbox = context.get('checkbox')
    clamp_model_preview_render_settings = context.get('clamp_model_preview_render_settings')
    combo = context.get('combo')
    combo_index = context.get('combo_index')
    current_settings = context.get('current_settings')
    data_value = context.get('data_value')
    dataclasses = context.get('dataclasses')
    dialog = context.get('dialog')
    index = context.get('index')
    normalize_archive_model_renderer_backend = context.get('normalize_archive_model_renderer_backend')
    old_settings = context.get('old_settings')
    original_dialog_preview = context.get('original_dialog_preview')
    overlay_dialog_preview = context.get('overlay_dialog_preview')
    preview_depth_spin = context.get('preview_depth_spin')
    preview_disable_brightness_checkbox = context.get('preview_disable_brightness_checkbox')
    preview_disable_tint_checkbox = context.get('preview_disable_tint_checkbox')
    preview_disable_uv_scale_checkbox = context.get('preview_disable_uv_scale_checkbox')
    preview_render_mode_combo = context.get('preview_render_mode_combo')
    preview_renderer_combo = context.get('preview_renderer_combo')
    preview_rough_spin = context.get('preview_rough_spin')
    preview_shine_spin = context.get('preview_shine_spin')
    preview_support_maps_checkbox = context.get('preview_support_maps_checkbox')
    preview_visible_mode_combo = context.get('preview_visible_mode_combo')
    preview_widget = context.get('preview_widget')
    previous_settings = context.get('previous_settings')
    rebuild_presentation = context.get('rebuild_presentation')
    render_settings_route = context.get('render_settings_route')
    render_tuning_presentation = context.get('render_tuning_presentation')
    replacement_only_preview = context.get('replacement_only_preview')
    self = context.get('self')
    settings = context.get('settings')
    spin = context.get('spin')
    static_dialog_preview = context.get('static_dialog_preview')
    value = context.get('value')

    def _alignment_preview_render_settings_from_controls(base_settings: Optional[ModelPreviewRenderSettings]=None) -> ModelPreviewRenderSettings:
        base = base_settings if isinstance(base_settings, ModelPreviewRenderSettings) else state.preview_render_settings
        settings = dataclasses.replace(clamp_model_preview_render_settings(base))
        settings.visible_texture_mode = str(preview_visible_mode_combo.currentData() or settings.visible_texture_mode)
        settings.render_diagnostic_mode = str(preview_render_mode_combo.currentData() or settings.render_diagnostic_mode)
        settings.d3d11_view_mode = str(alignment_d3d11_view_mode_combo.currentData() or settings.d3d11_view_mode)
        settings.disable_tint = bool(preview_disable_tint_checkbox.isChecked())
        settings.disable_brightness = bool(preview_disable_brightness_checkbox.isChecked())
        settings.disable_uv_scale = bool(preview_disable_uv_scale_checkbox.isChecked())
        settings.disable_all_support_maps = not bool(preview_support_maps_checkbox.isChecked())
        settings.height_effect_max = float(preview_depth_spin.value())
        settings.specular_max = float(preview_shine_spin.value())
        settings.shininess_max = 32.0 + float(preview_rough_spin.value()) * 224.0
        return clamp_model_preview_render_settings(settings)

    def _current_alignment_preview_render_settings() -> ModelPreviewRenderSettings:
        return _alignment_preview_render_settings_from_controls(state.preview_render_settings)

    def _lit_alignment_settings(settings: object) -> ModelPreviewRenderSettings:
        fallback_settings = state.preview_render_settings
        if not isinstance(fallback_settings, ModelPreviewRenderSettings):
            fallback_settings = self._current_model_preview_render_settings()
        if callable(_alignment_lit_render_settings):
            return _alignment_lit_render_settings(settings, fallback_settings)
        return clamp_model_preview_render_settings(
            settings if isinstance(settings, ModelPreviewRenderSettings) else fallback_settings
        )

    def _alignment_preview_package_settings_changed(previous_settings: ModelPreviewRenderSettings, current_settings: ModelPreviewRenderSettings) -> bool:
        return _alignment_d3d11_package_settings_changed_helper(previous_settings, current_settings)

    def _apply_alignment_preview_render_settings(*_args, previous_settings: Optional[ModelPreviewRenderSettings]=None) -> None:
        old_settings = clamp_model_preview_render_settings(previous_settings if isinstance(previous_settings, ModelPreviewRenderSettings) else state.preview_render_settings)
        state.preview_render_settings = _current_alignment_preview_render_settings()
        render_settings_route = _alignment_d3d11_render_settings_route_helper(d3d11_active=_alignment_d3d11_preview_active(), package_settings_changed=_alignment_preview_package_settings_changed(old_settings, state.preview_render_settings))
        if _alignment_d3d11_preview_active():
            if render_settings_route.action == 'd3d11_rebuild':
                if render_settings_route.should_invalidate_package_cache:
                    _alignment_d3d11_invalidate_package_cache('material')
                if render_settings_route.should_mark_rebuild_reason:
                    _mark_alignment_d3d11_rebuild_reason('material')
                if render_settings_route.should_queue_static_preview_refresh:
                    _queue_static_preview_refresh()
                rebuild_presentation = _alignment_d3d11_render_settings_rebuild_performance_helper()
                _set_preview_performance_status(rebuild_presentation.summary, details=rebuild_presentation.details)
                return
            if render_settings_route.should_apply_live_render_tuning:
                alignment_d3d11_preview_host.set_render_tuning(state.preview_render_settings)
            render_tuning_presentation = _alignment_d3d11_render_tuning_live_performance_helper()
            _set_preview_performance_status(render_tuning_presentation.summary, details=render_tuning_presentation.details)
            return
        if render_settings_route.should_apply_static_widget_settings:
            for preview_widget in (original_dialog_preview, static_dialog_preview, overlay_dialog_preview, replacement_only_preview):
                preview_widget.set_render_settings(state.preview_render_settings)
                preview_widget.set_use_textures(bool(state.preview_render_settings.use_textures_by_default))
                preview_widget.set_high_quality_textures(bool(state.preview_render_settings.high_quality_by_default))
        if render_settings_route.should_queue_static_preview_refresh:
            _queue_static_preview_refresh()

    def _sync_alignment_preview_controls_from_settings(settings: ModelPreviewRenderSettings) -> None:
        for combo, value in ((preview_visible_mode_combo, settings.visible_texture_mode), (preview_render_mode_combo, settings.render_diagnostic_mode), (alignment_d3d11_view_mode_combo, settings.d3d11_view_mode)):
            combo.blockSignals(True)
            combo_index = combo.findData(value)
            combo.setCurrentIndex(max(0, combo_index))
            combo.blockSignals(False)
        for checkbox, value in ((preview_disable_tint_checkbox, settings.disable_tint), (preview_disable_brightness_checkbox, settings.disable_brightness), (preview_disable_uv_scale_checkbox, settings.disable_uv_scale), (preview_support_maps_checkbox, not settings.disable_all_support_maps)):
            checkbox.blockSignals(True)
            checkbox.setChecked(bool(value))
            checkbox.blockSignals(False)
        for spin, value in ((preview_depth_spin, settings.height_effect_max), (preview_shine_spin, settings.specular_max)):
            spin.blockSignals(True)
            spin.setValue(float(value))
            spin.blockSignals(False)
        preview_rough_spin.blockSignals(True)
        preview_rough_spin.setValue(_rough_control_value_from_settings(settings))
        preview_rough_spin.blockSignals(False)

    def _use_global_alignment_preview_settings() -> None:
        previous_settings = _current_alignment_preview_render_settings()
        state.preview_render_settings = _lit_alignment_settings(self._current_model_preview_render_settings())
        _sync_alignment_preview_controls_from_settings(state.preview_render_settings)
        _apply_alignment_preview_render_settings(previous_settings=previous_settings)

    def _open_alignment_preview_settings_dialog() -> None:

        def _alignment_renderer_backend_for_dialog() -> str:
            return ARCHIVE_MODEL_RENDERER_D3D11

        def _set_alignment_renderer_from_dialog(backend: str) -> None:
            normalized = normalize_archive_model_renderer_backend(backend)
            data_value = 'd3d11'
            index = preview_renderer_combo.findData(data_value)
            if index >= 0 and index != preview_renderer_combo.currentIndex():
                preview_renderer_combo.setCurrentIndex(index)
            else:
                _set_preview_renderer()

        def _sync_from_modal_settings(settings: Optional[object]=None) -> None:
            previous_settings = _current_alignment_preview_render_settings()
            state.preview_render_settings = _lit_alignment_settings(settings if isinstance(settings, ModelPreviewRenderSettings) else self._current_model_preview_render_settings())
            _sync_alignment_preview_controls_from_settings(state.preview_render_settings)
            _apply_alignment_preview_render_settings(previous_settings=previous_settings)
        self._open_modal_model_preview_settings_dialog(dialog, archive_renderer_backend_enabled=True, archive_renderer_backend=_alignment_renderer_backend_for_dialog(), archive_renderer_backend_changed_handler=_set_alignment_renderer_from_dialog, settings_changed_handler=_sync_from_modal_settings, preview_settings=_current_alignment_preview_render_settings())

    return SimpleNamespace(_alignment_preview_render_settings_from_controls=_alignment_preview_render_settings_from_controls, _current_alignment_preview_render_settings=_current_alignment_preview_render_settings, _alignment_preview_package_settings_changed=_alignment_preview_package_settings_changed, _apply_alignment_preview_render_settings=_apply_alignment_preview_render_settings, _sync_alignment_preview_controls_from_settings=_sync_alignment_preview_controls_from_settings, _use_global_alignment_preview_settings=_use_global_alignment_preview_settings, _open_alignment_preview_settings_dialog=_open_alignment_preview_settings_dialog)


def create_alignment_geometry_history_callbacks(context: dict[str, object]) -> SimpleNamespace:
    state = _StaticReplacementDialogState(context)
    Any = context.get('Any')
    Dict = context.get('Dict')
    Mapping = context.get('Mapping')
    ParsedMesh = context.get('ParsedMesh')
    _apply_source_material_texture_overrides_to_ui_texture_sets = context.get('_apply_source_material_texture_overrides_to_ui_texture_sets')
    _default_texture_uv_transform_state = context.get('_default_texture_uv_transform_state')
    _geometry_history_capture_state_helper = context.get('_geometry_history_capture_state_helper')
    _geometry_history_push_state_helper = context.get('_geometry_history_push_state_helper')
    _geometry_history_restore_state_helper = context.get('_geometry_history_restore_state_helper')
    _geometry_mapping_text_by_target = context.get('_geometry_mapping_text_by_target')
    _geometry_original_copy_text_by_index = context.get('_geometry_original_copy_text_by_index')
    _geometry_reset_status_text_helper = context.get('_geometry_reset_status_text_helper')
    _geometry_undo_status_text_helper = context.get('_geometry_undo_status_text_helper')
    _invalidate_source_display_cache = context.get('_invalidate_source_display_cache')
    _load_selected_part_controls = context.get('_load_selected_part_controls')
    _morph_slider_refresh_controls = context.get('_morph_slider_refresh_controls')
    _morph_slider_reload_profiles = context.get('_morph_slider_reload_profiles')
    _queue_static_preview_rebuild = context.get('_queue_static_preview_rebuild')
    _rebuild_source_part_widgets = context.get('_rebuild_source_part_widgets')
    _record_texture_uv_global_transform_state_helper = context.get('_record_texture_uv_global_transform_state_helper')
    _refresh_original_reference_preview = context.get('_refresh_original_reference_preview')
    _refresh_source_assignment_columns = context.get('_refresh_source_assignment_columns')
    _refresh_texture_row_guidance = context.get('_refresh_texture_row_guidance')
    _refresh_texture_table = context.get('_refresh_texture_table')
    _refresh_texture_transform_editor = context.get('_refresh_texture_transform_editor')
    _selected_source_indices_from_tree = context.get('_selected_source_indices_from_tree')
    _sync_highlight_sets = context.get('_sync_highlight_sets')
    _update_mapping_status = context.get('_update_mapping_status')
    _update_selection_context = context.get('_update_selection_context')
    appended_source_indices = context.get('appended_source_indices')
    clone_mesh_for_editing = context.get('clone_mesh_for_editing')
    copied_original_physics_sensitive_sources = context.get('copied_original_physics_sensitive_sources')
    copied_original_source_indices = context.get('copied_original_source_indices')
    copied_original_source_to_original_index = context.get('copied_original_source_to_original_index')
    copied_original_texture_disabled_sources = context.get('copied_original_texture_disabled_sources')
    copied_original_texture_intents_by_source = context.get('copied_original_texture_intents_by_source')
    copy = context.get('copy')
    dialog_added_supplemental_files = context.get('dialog_added_supplemental_files')
    edit = context.get('edit')
    geometry_history_guard = context.get('geometry_history_guard')
    geometry_initial_snapshot = context.get('geometry_initial_snapshot')
    geometry_undo_stack = context.get('geometry_undo_stack')
    group_replacement_texture_sets = context.get('group_replacement_texture_sets')
    independent_output_source_indices = context.get('independent_output_source_indices')
    item = context.get('item')
    mapping_edit_refresh_timer = context.get('mapping_edit_refresh_timer')
    mapping_edits = context.get('mapping_edits')
    mapping_text_by_target = context.get('mapping_text_by_target')
    mesh_edit_active_stroke = context.get('mesh_edit_active_stroke')
    mesh_edit_redo_adjustment_stack = context.get('mesh_edit_redo_adjustment_stack')
    mesh_edit_redo_stack = context.get('mesh_edit_redo_stack')
    mesh_edit_revision = context.get('mesh_edit_revision')
    mesh_edit_selected_faces_by_submesh = context.get('mesh_edit_selected_faces_by_submesh')
    mesh_edit_selected_vertices_by_submesh = context.get('mesh_edit_selected_vertices_by_submesh')
    mesh_edit_undo_adjustment_stack = context.get('mesh_edit_undo_adjustment_stack')
    mesh_edit_undo_stack = context.get('mesh_edit_undo_stack')
    morph_slider_post_edit_deltas = context.get('morph_slider_post_edit_deltas')
    morph_slider_topology_blocked = context.get('morph_slider_topology_blocked')
    morph_slider_values = context.get('morph_slider_values')
    original_index = context.get('original_index')
    original_items_by_index = context.get('original_items_by_index')
    original_part_copies = context.get('original_part_copies')
    parsed_mesh_to_preview_model = context.get('parsed_mesh_to_preview_model')
    preview_only_source_indices = context.get('preview_only_source_indices')
    push_state = context.get('push_state')
    reason = context.get('reason')
    replacement_base_mesh = context.get('replacement_base_mesh')
    replacement_mesh = context.get('replacement_mesh')
    reset_geometry_button = context.get('reset_geometry_button')
    restore_state = context.get('restore_state')
    restored_morph_slider_post_edit_deltas = context.get('restored_morph_slider_post_edit_deltas')
    restored_morph_slider_topology_blocked = context.get('restored_morph_slider_topology_blocked')
    selected_original_highlight_indices = context.get('selected_original_highlight_indices')
    selected_original_part = context.get('selected_original_part')
    selected_source_highlight_indices = context.get('selected_source_highlight_indices')
    selected_source_part = context.get('selected_source_part')
    selected_target_original_highlight_indices = context.get('selected_target_original_highlight_indices')
    selected_target_slot = context.get('selected_target_slot')
    selected_target_source_highlight_indices = context.get('selected_target_source_highlight_indices')
    selected_texture_row = context.get('selected_texture_row')
    self = context.get('self')
    snapshot = context.get('snapshot')
    source_display_overrides = context.get('source_display_overrides')
    source_geometry_revision = context.get('source_geometry_revision')
    source_material_texture_override_assignments = context.get('source_material_texture_override_assignments')
    source_part_adjustments = context.get('source_part_adjustments')
    source_role_overrides = context.get('source_role_overrides')
    static_preview_geometry_cache = context.get('static_preview_geometry_cache')
    static_preview_prepared_cache = context.get('static_preview_prepared_cache')
    target_index = context.get('target_index')
    texture_files_for_mapping = context.get('texture_files_for_mapping') or []
    texture_override_assignments = context.get('texture_override_assignments')
    texture_overrides_dirty = context.get('texture_overrides_dirty')
    texture_uv_global_transform_state = context.get('texture_uv_global_transform_state')
    texture_uv_transform_state = context.get('texture_uv_transform_state')
    transform_source_indices = context.get('transform_source_indices')
    undo_geometry_button = context.get('undo_geometry_button')

    def _capture_geometry_history_state(reason: str) -> Dict[str, Any]:
        return _geometry_history_capture_state_helper(reason=reason, replacement_mesh=clone_mesh_for_editing(state.replacement_mesh_for_mapping) if state.replacement_mesh_for_mapping is not None else None, replacement_base_mesh=clone_mesh_for_editing(state.replacement_mesh_base_for_mapping) if state.replacement_mesh_base_for_mapping is not None else None, mapping_text_by_target=_geometry_mapping_text_by_target(), source_part_adjustments=source_part_adjustments, source_role_overrides=source_role_overrides, source_display_overrides=source_display_overrides, original_part_copies=original_part_copies, original_copy_text_by_index=_geometry_original_copy_text_by_index(), appended_source_indices=appended_source_indices, independent_output_source_indices=independent_output_source_indices, preview_only_source_indices=preview_only_source_indices, dialog_added_supplemental_files=dialog_added_supplemental_files, texture_files_for_mapping=texture_files_for_mapping, texture_override_assignments=texture_override_assignments, source_material_texture_override_assignments=source_material_texture_override_assignments, copied_original_texture_intents_by_source=copied_original_texture_intents_by_source, copied_original_texture_disabled_sources=copied_original_texture_disabled_sources, copied_original_source_indices=copied_original_source_indices, copied_original_source_to_original_index=copied_original_source_to_original_index, copied_original_physics_sensitive_sources=copied_original_physics_sensitive_sources, texture_uv_transform_state=texture_uv_transform_state, texture_uv_global_transform_state=texture_uv_global_transform_state, mesh_edit_revision=mesh_edit_revision.get('value', 0), source_geometry_revision=source_geometry_revision.get('value', 0), morph_slider_values=morph_slider_values, morph_slider_post_edit_deltas=morph_slider_post_edit_deltas, morph_slider_topology_blocked=morph_slider_topology_blocked, selected_source_index=selected_source_part.get('index', -1), selected_source_indices=_selected_source_indices_from_tree(), selected_target_index=selected_target_slot.get('index', -1), selected_original_index=selected_original_part.get('index', -1), selected_source_highlights=selected_source_highlight_indices, selected_target_source_highlights=selected_target_source_highlight_indices, transform_source_indices=transform_source_indices, selected_original_highlights=selected_original_highlight_indices, selected_target_original_highlights=selected_target_original_highlight_indices)

    def _refresh_geometry_history_buttons() -> None:
        try:
            if callable(getattr(undo_geometry_button, "setEnabled", None)):
                undo_geometry_button.setEnabled(bool(geometry_undo_stack))
            if callable(getattr(reset_geometry_button, "setEnabled", None)):
                reset_geometry_button.setEnabled(bool(geometry_initial_snapshot))
        except NameError:
            pass

    def _push_geometry_undo_snapshot(reason: str) -> None:
        snapshot = _capture_geometry_history_state(reason)
        push_state = _geometry_history_push_state_helper(geometry_undo_stack, snapshot, guard_active=bool(geometry_history_guard.get('active')))
        if not push_state.pushed:
            return
        geometry_undo_stack[:] = list(push_state.snapshots)
        _refresh_geometry_history_buttons()

    def _pop_geometry_undo_snapshot() -> None:
        if geometry_undo_stack:
            geometry_undo_stack.pop()
        _refresh_geometry_history_buttons()

    def _restore_geometry_history_state(snapshot: Mapping[str, Any]) -> None:
        if not snapshot:
            return
        geometry_history_guard['active'] = True
        try:
            restore_state = _geometry_history_restore_state_helper(snapshot, default_texture_uv_global_transform_state=_default_texture_uv_transform_state('__global__'))
            replacement_mesh = restore_state.replacement_mesh
            replacement_base_mesh = restore_state.replacement_base_mesh
            state.replacement_mesh_for_mapping = clone_mesh_for_editing(replacement_mesh) if isinstance(replacement_mesh, ParsedMesh) else None
            state.replacement_mesh_base_for_mapping = clone_mesh_for_editing(replacement_base_mesh) if isinstance(replacement_base_mesh, ParsedMesh) else None
            state.replacement_preview_model = parsed_mesh_to_preview_model(state.replacement_mesh_for_mapping) if state.replacement_mesh_for_mapping is not None else None
            source_part_adjustments.clear()
            source_part_adjustments.update(copy.deepcopy(restore_state.source_part_adjustments))
            source_role_overrides.clear()
            source_role_overrides.update(restore_state.source_role_overrides)
            source_display_overrides.clear()
            source_display_overrides.update(restore_state.source_display_overrides)
            _invalidate_source_display_cache()
            original_part_copies[:] = list(copy.deepcopy(restore_state.original_part_copies))
            appended_source_indices.clear()
            appended_source_indices.update(restore_state.appended_source_indices)
            independent_output_source_indices.clear()
            independent_output_source_indices.update(restore_state.independent_output_source_indices)
            preview_only_source_indices.clear()
            preview_only_source_indices.update(restore_state.preview_only_source_indices)
            dialog_added_supplemental_files[:] = restore_state.dialog_added_supplemental_files
            texture_files_for_mapping[:] = restore_state.texture_files_for_mapping
            texture_override_assignments.clear()
            texture_override_assignments.update(restore_state.texture_override_assignments)
            source_material_texture_override_assignments.clear()
            source_material_texture_override_assignments.update(restore_state.source_material_texture_override_assignments)
            copied_original_texture_intents_by_source.clear()
            copied_original_texture_intents_by_source.update(restore_state.copied_original_texture_intents_by_source)
            copied_original_texture_disabled_sources.clear()
            copied_original_texture_disabled_sources.update(restore_state.copied_original_texture_disabled_sources)
            copied_original_source_indices.clear()
            copied_original_source_indices.update(restore_state.copied_original_source_indices)
            copied_original_source_to_original_index.clear()
            copied_original_source_to_original_index.update(restore_state.copied_original_source_to_original_index)
            copied_original_physics_sensitive_sources.clear()
            copied_original_physics_sensitive_sources.update(restore_state.copied_original_physics_sensitive_sources)
            texture_uv_transform_state.clear()
            texture_uv_transform_state.update(restore_state.texture_uv_transform_state)
            _record_texture_uv_global_transform_state_helper(texture_uv_global_transform_state, restore_state.texture_uv_global_transform_state)
            mesh_edit_revision['value'] = restore_state.mesh_edit_revision
            source_geometry_revision['value'] = restore_state.source_geometry_revision
            morph_slider_values.clear()
            morph_slider_values.update(restore_state.morph_slider_values)
            morph_slider_post_edit_deltas[:] = copy.deepcopy(restore_state.morph_slider_post_edit_deltas)
            morph_slider_topology_blocked.clear()
            morph_slider_topology_blocked.update(restore_state.morph_slider_topology_blocked)
            selected_source_part['index'] = restore_state.selected_source_index
            selected_target_slot['index'] = restore_state.selected_target_index
            selected_original_part['index'] = restore_state.selected_original_index
            selected_source_highlight_indices.clear()
            selected_source_highlight_indices.update(restore_state.selected_source_highlights)
            selected_target_source_highlight_indices.clear()
            selected_target_source_highlight_indices.update(restore_state.selected_target_source_highlights)
            transform_source_indices.clear()
            transform_source_indices.update(restore_state.transform_source_indices)
            selected_original_highlight_indices.clear()
            selected_original_highlight_indices.update(restore_state.selected_original_highlights)
            selected_target_original_highlight_indices.clear()
            selected_target_original_highlight_indices.update(restore_state.selected_target_original_highlights)
            for original_index, item in original_items_by_index.items():
                item.setText(4, str(restore_state.original_copy_text_by_index.get(int(original_index), '')))
            mapping_text_by_target = restore_state.mapping_text_by_target
            for target_index, edit in mapping_edits:
                edit.setText(str(mapping_text_by_target.get(int(target_index), '')))
                edit.setProperty('committed_mapping_text', edit.text().strip())
            _rebuild_source_part_widgets(restore_state.selected_source_indices, current_index=restore_state.selected_source_index)
            static_preview_geometry_cache.clear()
            static_preview_prepared_cache.clear()
            mesh_edit_active_stroke.clear()
            mesh_edit_selected_vertices_by_submesh.clear()
            mesh_edit_selected_faces_by_submesh.clear()
            mesh_edit_undo_stack.clear()
            mesh_edit_redo_stack.clear()
            mesh_edit_undo_adjustment_stack.clear()
            mesh_edit_redo_adjustment_stack.clear()
            try:
                restored_morph_slider_post_edit_deltas = copy.deepcopy(morph_slider_post_edit_deltas)
                restored_morph_slider_topology_blocked = dict(morph_slider_topology_blocked)
                _morph_slider_reload_profiles(preserve_values=True)
                morph_slider_post_edit_deltas[:] = restored_morph_slider_post_edit_deltas
                morph_slider_topology_blocked.clear()
                morph_slider_topology_blocked.update(restored_morph_slider_topology_blocked)
                _morph_slider_refresh_controls()
            except NameError:
                pass
            texture_overrides_dirty['dirty'] = True
            state.texture_sets = group_replacement_texture_sets(texture_files_for_mapping, obj_mesh=state.replacement_mesh_for_mapping)
            _apply_source_material_texture_overrides_to_ui_texture_sets(state.texture_sets)
            _sync_highlight_sets()
            _refresh_original_reference_preview()
            _refresh_source_assignment_columns()
            try:
                _refresh_texture_row_guidance()
                _refresh_texture_table(selected_texture_row.get('row'))
            except NameError:
                pass
            try:
                _refresh_texture_transform_editor()
            except NameError:
                pass
            _load_selected_part_controls()
            _update_mapping_status()
            _update_selection_context()
            _queue_static_preview_rebuild()
        finally:
            geometry_history_guard['active'] = False
            _refresh_geometry_history_buttons()

    def _undo_geometry_change() -> None:
        if not geometry_undo_stack:
            return
        snapshot = geometry_undo_stack.pop()
        _restore_geometry_history_state(snapshot)
        self.set_status_message(_geometry_undo_status_text_helper(snapshot.get('reason', 'Geometry change')))

    def _reset_geometry_changes() -> None:
        if not geometry_initial_snapshot:
            return
        _push_geometry_undo_snapshot('Reset Geometry')
        _restore_geometry_history_state(geometry_initial_snapshot)
        _refresh_geometry_history_buttons()
        self.set_status_message(_geometry_reset_status_text_helper())

    def _capture_initial_geometry_snapshot() -> None:
        if geometry_initial_snapshot:
            return
        geometry_initial_snapshot.update(_capture_geometry_history_state('Initial Geometry'))
        _refresh_geometry_history_buttons()

    def _flush_mapping_edit_refresh() -> None:
        mapping_edit_refresh_timer.stop()
        texture_overrides_dirty['dirty'] = True
        _refresh_source_assignment_columns()
        _update_mapping_status()
        _update_selection_context()
        _queue_static_preview_rebuild()

    return SimpleNamespace(_capture_geometry_history_state=_capture_geometry_history_state, _refresh_geometry_history_buttons=_refresh_geometry_history_buttons, _push_geometry_undo_snapshot=_push_geometry_undo_snapshot, _pop_geometry_undo_snapshot=_pop_geometry_undo_snapshot, _restore_geometry_history_state=_restore_geometry_history_state, _undo_geometry_change=_undo_geometry_change, _reset_geometry_changes=_reset_geometry_changes, _capture_initial_geometry_snapshot=_capture_initial_geometry_snapshot, _flush_mapping_edit_refresh=_flush_mapping_edit_refresh)


def create_alignment_mapping_edit_callbacks(context: dict[str, object]) -> SimpleNamespace:
    state = _StaticReplacementDialogState(context)
    QLineEdit = context.get('QLineEdit')
    _flush_mapping_edit_refresh = context.get('_flush_mapping_edit_refresh')
    _mapping_target_index_for_edit_helper = context.get('_mapping_target_index_for_edit_helper')
    _push_geometry_undo_snapshot = context.get('_push_geometry_undo_snapshot')
    _sync_target_mapping_tree_item = context.get('_sync_target_mapping_tree_item')
    edit = context.get('edit')
    mapping_edits = context.get('mapping_edits')
    next_text = context.get('next_text')
    previous_text = context.get('previous_text')
    target_index = context.get('target_index')
    texture_overrides_dirty = context.get('texture_overrides_dirty')

    def _commit_mapping_edit(edit: QLineEdit) -> None:
        target_index = _mapping_target_index_for_edit_helper(mapping_edits, edit)
        previous_text = str(edit.property('committed_mapping_text') or '')
        next_text = edit.text().strip()
        if previous_text == next_text:
            return
        _push_geometry_undo_snapshot('Apply advanced mapping')
        texture_overrides_dirty['dirty'] = True
        edit.setProperty('committed_mapping_text', next_text)
        _sync_target_mapping_tree_item(target_index)
        _flush_mapping_edit_refresh()

    return SimpleNamespace(_commit_mapping_edit=_commit_mapping_edit)


def create_alignment_original_source_filter_callbacks(context: dict[str, object]) -> SimpleNamespace:
    state = _StaticReplacementDialogState(context)
    QEvent = context.get('QEvent')
    QObject = context.get('QObject')
    QTreeWidget = context.get('QTreeWidget')
    Qt = context.get('Qt')
    _qt_object_is_valid = context.get('_qt_object_is_valid')
    _selected_source_indices_from_tree = context.get('_selected_source_indices_from_tree')
    _source_tree_context_selection_record_multi_indices_helper = context.get('_source_tree_context_selection_record_multi_indices_helper')
    _source_tree_context_selection_set_right_press_helper = context.get('_source_tree_context_selection_set_right_press_helper')
    button = context.get('button')
    event = context.get('event')
    event_type = context.get('event_type')
    selected_indices = context.get('selected_indices')
    self = context.get('self')
    source_tree_context_selection_state = context.get('source_tree_context_selection_state')
    tree = context.get('tree')
    watched = context.get('watched')

    class _SourceTreeContextSelectionFilter(QObject):

        def __init__(self, tree: QTreeWidget) -> None:
            super().__init__(tree)
            self._tree = tree
            self._viewport = tree.viewport()

        def eventFilter(self, watched: QObject, event: QEvent) -> bool:
            if watched is not self._viewport or not _qt_object_is_valid(self._tree):
                return False
            try:
                event_type = event.type()
            except RuntimeError:
                return False
            if event_type == QEvent.MouseButtonPress:
                try:
                    button = event.button()
                except Exception:
                    button = None
                if button == Qt.RightButton:
                    _source_tree_context_selection_set_right_press_helper(source_tree_context_selection_state, True)
                    selected_indices = tuple(_selected_source_indices_from_tree(include_fallback=False))
                    if len(selected_indices) > 1:
                        _source_tree_context_selection_record_multi_indices_helper(source_tree_context_selection_state, selected_indices)
                elif button == Qt.LeftButton:
                    _source_tree_context_selection_set_right_press_helper(source_tree_context_selection_state, False)
            return False

    return SimpleNamespace(_SourceTreeContextSelectionFilter=_SourceTreeContextSelectionFilter)


def create_alignment_original_reference_preview_callbacks(context: dict[str, object]) -> SimpleNamespace:
    state = _StaticReplacementDialogState(context)
    _alignment_d3d11_preview_active = context.get('_alignment_d3d11_preview_active')
    _clone_preview_model = context.get('_clone_preview_model')
    _original_reference_preview_model_state_helper = context.get('_original_reference_preview_model_state_helper')
    _original_texture_preview_material_preview_enabled_helper = context.get('_original_texture_preview_material_preview_enabled_helper')
    _sync_highlight_sets = context.get('_sync_highlight_sets')
    highlighted_original_indices = context.get('highlighted_original_indices')
    modify_original_clone_mode = context.get('modify_original_clone_mode')
    original_dialog_preview = context.get('original_dialog_preview')
    original_texture_preview_state = context.get('original_texture_preview_state')
    preview_model = context.get('preview_model')
    view_state = context.get('view_state')

    def _refresh_original_reference_preview() -> None:
        if state.original_reference_preview_model is None:
            return
        if _alignment_d3d11_preview_active():
            _sync_highlight_sets()
            return
        preview_model = _original_reference_preview_model_state_helper(state.original_reference_preview_model, highlighted_indices=highlighted_original_indices, preserve_material_preview=_original_texture_preview_material_preview_enabled_helper(modify_original_clone_mode, original_texture_preview_state), clone_model=_clone_preview_model)
        view_state = original_dialog_preview.view_state_snapshot()
        original_dialog_preview.set_model(preview_model)
        original_dialog_preview.restore_view_state(view_state)
        original_dialog_preview.set_use_textures(True)
        original_dialog_preview.set_high_quality_textures(True)

    return SimpleNamespace(_refresh_original_reference_preview=_refresh_original_reference_preview)


def create_alignment_original_copy_payload_callbacks(context: dict[str, object]) -> SimpleNamespace:
    state = _StaticReplacementDialogState(context)
    Mapping = context.get('Mapping')
    QBrush = context.get('QBrush')
    QColor = context.get('QColor')
    QMessageBox = context.get('QMessageBox')
    _add_source_tree_item = context.get('_add_source_tree_item')
    _appended_original_copy_column_text_helper = context.get('_appended_original_copy_column_text_helper')
    _auto_fit_alignment_tree_columns = context.get('_auto_fit_alignment_tree_columns')
    _copied_original_dds_badge = context.get('_copied_original_dds_badge')
    _copied_original_dds_cell_text_helper = context.get('_copied_original_dds_cell_text_helper')
    _copied_original_part_source_helper = context.get('_copied_original_part_source_helper')
    _copied_original_physics_status_message_helper = context.get('_copied_original_physics_status_message_helper')
    _copied_original_texture_tooltip = context.get('_copied_original_texture_tooltip')
    _fit_alignment_tree_height_to_rows = context.get('_fit_alignment_tree_height_to_rows')
    _invalidate_source_display_cache = context.get('_invalidate_source_display_cache')
    _load_selected_part_controls = context.get('_load_selected_part_controls')
    _mapping_indices_with_appended_source_helper = context.get('_mapping_indices_with_appended_source_helper')
    _missing_copied_original_part_message_helper = context.get('_missing_copied_original_part_message_helper')
    _original_target_label = context.get('_original_target_label')
    _parse_mapping_edit = context.get('_parse_mapping_edit')
    _push_geometry_undo_snapshot = context.get('_push_geometry_undo_snapshot')
    _queue_static_preview_rebuild = context.get('_queue_static_preview_rebuild')
    _refresh_added_part_texture_tree = context.get('_refresh_added_part_texture_tree')
    _refresh_parts_outliner = context.get('_refresh_parts_outliner')
    _refresh_source_assignment_columns = context.get('_refresh_source_assignment_columns')
    _refresh_source_material_plan = context.get('_refresh_source_material_plan')
    _selected_target_index = context.get('_selected_target_index')
    _set_mapping_indices = context.get('_set_mapping_indices')
    _set_transform_source_indices = context.get('_set_transform_source_indices')
    _source_assigned_target_indices_helper = context.get('_source_assigned_target_indices_helper')
    _source_display_name = context.get('_source_display_name')
    _source_outliner_state = context.get('_source_outliner_state')
    appended_source_indices = context.get('appended_source_indices')
    assign_to_target = context.get('assign_to_target')
    copied_item = context.get('copied_item')
    copied_original_physics_sensitive_sources = context.get('copied_original_physics_sensitive_sources')
    copied_original_source_indices = context.get('copied_original_source_indices')
    copied_original_source_to_original_index = context.get('copied_original_source_to_original_index')
    copied_original_texture_disabled_sources = context.get('copied_original_texture_disabled_sources')
    copied_original_texture_intents_by_source = context.get('copied_original_texture_intents_by_source')
    copied_part = context.get('copied_part')
    copied_source = context.get('copied_source')
    copy = context.get('copy')
    dialog = context.get('dialog')
    disabled = context.get('disabled')
    edit = context.get('edit')
    group_replacement_texture_sets = context.get('group_replacement_texture_sets')
    mapping_edits = context.get('mapping_edits')
    mapping_edits_by_target = context.get('mapping_edits_by_target')
    message = context.get('message')
    new_source_index = context.get('new_source_index')
    original_index = context.get('original_index')
    original_item = context.get('original_item')
    original_items_by_index = context.get('original_items_by_index')
    original_mesh_for_mapping = context.get('original_mesh_for_mapping')
    parsed_mesh_to_preview_model = context.get('parsed_mesh_to_preview_model')
    part_source_combo = context.get('part_source_combo')
    payload = context.get('payload')
    preview_only = context.get('preview_only')
    preview_only_source_indices = context.get('preview_only_source_indices')
    previous = context.get('previous')
    refresh_parsed_mesh_totals = context.get('refresh_parsed_mesh_totals')
    role_value = context.get('role_value')
    selected_source_highlight_indices = context.get('selected_source_highlight_indices')
    selected_source_part = context.get('selected_source_part')
    self = context.get('self')
    source_display_overrides = context.get('source_display_overrides')
    source_geometry_revision = context.get('source_geometry_revision')
    source_index = context.get('source_index')
    source_item = context.get('source_item')
    source_items_by_index = context.get('source_items_by_index')
    source_role_overrides = context.get('source_role_overrides')
    source_tree = context.get('source_tree')
    source_tree_layout_state = context.get('source_tree_layout_state')
    state_text = context.get('state_text')
    static_preview_geometry_cache = context.get('static_preview_geometry_cache')
    static_preview_prepared_cache = context.get('static_preview_prepared_cache')
    target_index = context.get('target_index')
    texture_files_for_mapping = context.get('texture_files_for_mapping') or []
    texture_rows = context.get('texture_rows')
    title = context.get('title')
    undo_label = context.get('undo_label')

    def _refresh_copied_original_texture_ui(source_index: int=-1) -> None:
        source_item = source_items_by_index.get(int(source_index))
        if source_item is not None and int(source_index) in copied_original_texture_intents_by_source:
            disabled = int(source_index) in copied_original_texture_disabled_sources
            state_text, _state_color = _source_outliner_state(int(source_index), _source_assigned_target_indices_helper(int(source_index), mapping_edits, parse_mapping_edit=_parse_mapping_edit))
            source_item.setText(5, _copied_original_dds_cell_text_helper(state_text, disabled=disabled, copied_badge=_copied_original_dds_badge(int(source_index))))
            source_item.setForeground(5, QBrush(QColor('#d29922' if disabled else '#3fb950')))
            source_item.setToolTip(5, _copied_original_texture_tooltip(int(source_index)))
        try:
            _refresh_source_assignment_columns(lightweight=True)
        except NameError:
            pass
        try:
            _refresh_parts_outliner()
        except NameError:
            pass
        try:
            _refresh_source_material_plan(force=True)
        except NameError:
            pass
        try:
            _refresh_added_part_texture_tree(int(source_index))
        except NameError:
            pass

    def _append_original_part_payload_as_source(payload: Mapping[str, object], *, assign_to_target: bool, preview_only: bool, undo_label: str) -> int:
        if original_mesh_for_mapping is None or state.replacement_mesh_for_mapping is None:
            return -1
        try:
            original_index = int(payload.get('original_submesh_index', -1))
        except (TypeError, ValueError):
            original_index = -1
        copied_source = payload.get('submesh')
        if original_index < 0 or original_index >= len(original_mesh_for_mapping.submeshes) or copied_source is None:
            title, message = _missing_copied_original_part_message_helper()
            QMessageBox.information(dialog, title, message)
            return -1
        _push_geometry_undo_snapshot(undo_label)
        copied_part = _copied_original_part_source_helper(copied_source, payload, original_index, _original_target_label(original_index), undo_label.startswith('Paste'))
        new_source_index = len(state.replacement_mesh_for_mapping.submeshes)
        state.replacement_mesh_for_mapping.submeshes.append(copied_part)
        refresh_parsed_mesh_totals(state.replacement_mesh_for_mapping)
        source_geometry_revision['value'] = int(source_geometry_revision.get('value', 0) or 0) + 1
        static_preview_geometry_cache.clear()
        static_preview_prepared_cache.clear()
        role_value = str(payload.get('role', '') or '').strip()
        if role_value:
            source_role_overrides[new_source_index] = role_value
        source_display_overrides[new_source_index] = copied_part.name
        _invalidate_source_display_cache()
        copied_original_source_indices.add(new_source_index)
        copied_original_source_to_original_index[new_source_index] = original_index
        appended_source_indices.add(new_source_index)
        if str(payload.get('physics_review_reason', '') or '').strip():
            copied_original_physics_sensitive_sources.add(new_source_index)
        if preview_only and (not assign_to_target):
            preview_only_source_indices.add(new_source_index)
        texture_rows = copy.deepcopy(payload.get('texture_rows', []) or [])
        if texture_rows:
            copied_original_texture_intents_by_source[new_source_index] = texture_rows
            copied_original_texture_disabled_sources.discard(new_source_index)
        original_item = original_items_by_index.get(original_index)
        if original_item is not None:
            previous = original_item.text(4)
            original_item.setText(4, _appended_original_copy_column_text_helper(previous, new_source_index))
        _add_source_tree_item(new_source_index, copied_part)
        try:
            part_source_combo.addItem(_source_display_name(new_source_index), new_source_index)
        except NameError:
            pass
        _fit_alignment_tree_height_to_rows(source_tree, **source_tree_layout_state.height_fit_kwargs)
        state.replacement_preview_model = parsed_mesh_to_preview_model(state.replacement_mesh_for_mapping)
        source_tree.clearSelection()
        copied_item = source_items_by_index.get(new_source_index)
        if copied_item is not None:
            copied_item.setSelected(True)
            source_tree.setCurrentItem(copied_item)
        selected_source_part['index'] = new_source_index
        selected_source_highlight_indices.clear()
        selected_source_highlight_indices.add(new_source_index)
        _set_transform_source_indices((new_source_index,))
        target_index = _selected_target_index()
        if assign_to_target and target_index >= 0:
            edit = mapping_edits_by_target.get(target_index)
            if edit is not None:
                _set_mapping_indices(target_index, _mapping_indices_with_appended_source_helper(edit.text(), new_source_index), push_undo=False)
        state.texture_sets = group_replacement_texture_sets(texture_files_for_mapping, obj_mesh=state.replacement_mesh_for_mapping)
        _refresh_copied_original_texture_ui(new_source_index)
        _auto_fit_alignment_tree_columns(source_tree, source_tree_layout_state.autofit_min_widths, source_tree_layout_state.autofit_max_widths, expand_columns=source_tree_layout_state.expand_columns)
        _refresh_source_assignment_columns()
        _load_selected_part_controls()
        _queue_static_preview_rebuild()
        if int(new_source_index) in copied_original_physics_sensitive_sources:
            self.set_status_message(_copied_original_physics_status_message_helper())
        return new_source_index

    return SimpleNamespace(_refresh_copied_original_texture_ui=_refresh_copied_original_texture_ui, _append_original_part_payload_as_source=_append_original_part_payload_as_source)


def create_alignment_original_part_copy_callbacks(context: dict[str, object]) -> SimpleNamespace:
    state = _StaticReplacementDialogState(context)
    QMessageBox = context.get('QMessageBox')
    _append_original_part_payload_as_source = context.get('_append_original_part_payload_as_source')
    _copy_original_part_payload = context.get('_copy_original_part_payload')
    _selected_original_index_from_tree = context.get('_selected_original_index_from_tree')
    assign_to_target = context.get('assign_to_target')
    dialog = context.get('dialog')
    original_index = context.get('original_index')
    original_mesh_for_mapping = context.get('original_mesh_for_mapping')
    original_part_clipboard_action_text = context.get('original_part_clipboard_action_text')
    payload = context.get('payload')

    def _copy_selected_original_part(*, assign_to_target: bool = False) -> None:
        if original_mesh_for_mapping is None or state.replacement_mesh_for_mapping is None:
            return
        original_index = _selected_original_index_from_tree()
        payload = _copy_original_part_payload(original_index)
        if payload is None:
            QMessageBox.information(dialog, original_part_clipboard_action_text['select_original_title'], original_part_clipboard_action_text['select_original_message'])
            return
        _append_original_part_payload_as_source(payload, assign_to_target=assign_to_target, preview_only=not assign_to_target, undo_label=original_part_clipboard_action_text['copy_undo_label'])

    return SimpleNamespace(_copy_selected_original_part=_copy_selected_original_part)


def create_alignment_source_role_flush_callbacks(context: dict[str, object]) -> SimpleNamespace:
    state = _StaticReplacementDialogState(context)
    List = context.get('List')
    StaticSourcePartAdjustment = context.get('StaticSourcePartAdjustment')
    _apply_source_material_texture_overrides_to_ui_texture_sets = context.get('_apply_source_material_texture_overrides_to_ui_texture_sets')
    _ensure_source_part_adjustment = context.get('_ensure_source_part_adjustment')
    _parse_mapping_edit = context.get('_parse_mapping_edit')
    _selected_part_glow_rgb_from_controls = context.get('_selected_part_glow_rgb_from_controls')
    _source_assigned_target_indices_helper = context.get('_source_assigned_target_indices_helper')
    _source_part_glow_emissive_update_states_helper = context.get('_source_part_glow_emissive_update_states_helper')
    _source_part_role_export_flush_states_helper = context.get('_source_part_role_export_flush_states_helper')
    adjustment = context.get('adjustment')
    changed = context.get('changed')
    flush_state = context.get('flush_state')
    group_replacement_texture_sets = context.get('group_replacement_texture_sets')
    mapping_edits = context.get('mapping_edits')
    part_glow_color_checkbox = context.get('part_glow_color_checkbox')
    source_index = context.get('source_index')
    source_part_adjustments = context.get('source_part_adjustments')
    source_role_overrides = context.get('source_role_overrides')
    texture_files_for_mapping = context.get('texture_files_for_mapping') or []
    update_state = context.get('update_state')
    update_states = context.get('update_states')

    prompt_shell_context = context.get('prompt_shell_context')

    def _prompt_context_value(name: str) -> object:
        if isinstance(prompt_shell_context, dict) and name in prompt_shell_context:
            return prompt_shell_context.get(name)
        return context.get(name)

    def _part_glow_color_checkbox() -> object:
        return _prompt_context_value('part_glow_color_checkbox')

    def _apply_current_glow_color_to_role_overrides() -> None:
        checkbox = _part_glow_color_checkbox()
        use_color = bool(
            checkbox is not None
            and callable(getattr(checkbox, "isChecked", None))
            and checkbox.isChecked()
        )
        rgb = _selected_part_glow_rgb_from_controls() if callable(_selected_part_glow_rgb_from_controls) else ()
        update_states = _source_part_glow_emissive_update_states_helper(source_part_adjustments, rgb=rgb, use_color=use_color)
        for update_state in update_states:
            adjustment = source_part_adjustments.get(update_state.source_index)
            if adjustment is not None:
                adjustment.emissive_color_rgb = update_state.emissive_color_rgb
        if update_states:
            _refresh_ui_texture_sets_after_source_part_material_override()

    def _flush_source_role_overrides_for_export() -> None:
        changed = False
        for flush_state in _source_part_role_export_flush_states_helper(source_role_overrides, source_part_adjustments, default_adjustment=StaticSourcePartAdjustment):
            adjustment = _ensure_source_part_adjustment(flush_state.source_index)
            if flush_state.material_role_changed:
                adjustment.material_role = flush_state.normalized_role
            if flush_state.clear_emissive_color:
                adjustment.emissive_color_rgb = ()
            changed = changed or flush_state.changed
        _apply_current_glow_color_to_role_overrides()
        if changed:
            _refresh_ui_texture_sets_after_source_part_material_override()

    def _refresh_ui_texture_sets_after_source_part_material_override() -> None:
        if state.replacement_mesh_for_mapping is None:
            return
        try:
            state.texture_sets = group_replacement_texture_sets(texture_files_for_mapping, obj_mesh=state.replacement_mesh_for_mapping)
            _apply_source_material_texture_overrides_to_ui_texture_sets(state.texture_sets)
        except Exception:
            return

    def _part_mapped_target_indices(source_index: int) -> List[int]:
        return list(_source_assigned_target_indices_helper(source_index, mapping_edits, parse_mapping_edit=_parse_mapping_edit))

    return SimpleNamespace(_apply_current_glow_color_to_role_overrides=_apply_current_glow_color_to_role_overrides, _flush_source_role_overrides_for_export=_flush_source_role_overrides_for_export, _refresh_ui_texture_sets_after_source_part_material_override=_refresh_ui_texture_sets_after_source_part_material_override, _part_mapped_target_indices=_part_mapped_target_indices)


def create_alignment_selected_part_adjustment_callbacks(context: dict[str, object]) -> SimpleNamespace:
    state = _StaticReplacementDialogState(context)
    Qt = context.get('Qt')
    StaticSourcePartAdjustment = context.get('StaticSourcePartAdjustment')
    _ensure_source_part_adjustment = context.get('_ensure_source_part_adjustment')
    _push_geometry_undo_snapshot = context.get('_push_geometry_undo_snapshot')
    _queue_part_transform_preview_update = context.get('_queue_part_transform_preview_update')
    _refresh_source_assignment_columns = context.get('_refresh_source_assignment_columns')
    _selected_source_indices_from_tree = context.get('_selected_source_indices_from_tree')
    _set_source_parts_apply_pending = context.get('_set_source_parts_apply_pending')
    _sync_highlight_sets = context.get('_sync_highlight_sets')
    _source_part_adjustment_apply_state_helper = context.get('_source_part_adjustment_apply_state_helper')
    _source_part_edit_undo_label_helper = context.get('_source_part_edit_undo_label_helper')
    _source_part_include_exclude_pending_reason_helper = context.get('_source_part_include_exclude_pending_reason_helper')
    adjustment = context.get('adjustment')
    apply_state = context.get('apply_state')
    part_enabled_checkbox = context.get('part_enabled_checkbox')
    part_inspector_loading = context.get('part_inspector_loading')
    part_offset_x_spin = context.get('part_offset_x_spin')
    part_offset_y_spin = context.get('part_offset_y_spin')
    part_offset_z_spin = context.get('part_offset_z_spin')
    part_rotate_x_spin = context.get('part_rotate_x_spin')
    part_rotate_y_spin = context.get('part_rotate_y_spin')
    part_rotate_z_spin = context.get('part_rotate_z_spin')
    part_scale_x_spin = context.get('part_scale_x_spin')
    part_scale_y_spin = context.get('part_scale_y_spin')
    part_scale_z_spin = context.get('part_scale_z_spin')
    part_uniform_spin = context.get('part_uniform_spin')
    push_undo = context.get('push_undo')
    queue_preview = context.get('queue_preview')
    selected_source_part = context.get('selected_source_part')
    source_index = context.get('source_index')
    source_item = context.get('source_item')
    source_items_by_index = context.get('source_items_by_index')
    source_part_adjustments = context.get('source_part_adjustments')
    source_tree_item_update_guard = context.get('source_tree_item_update_guard')
    target_source_index = context.get('target_source_index')

    def _update_selected_part_adjustment(_signal_value: object = None, *, queue_preview: bool = True, push_undo: bool = True) -> bool:
        if part_inspector_loading['active']:
            return False
        source_index = int(selected_source_part.get('index', -1))
        apply_state = _source_part_adjustment_apply_state_helper(source_part_adjustments, source_index=source_index, selected_source_indices=_selected_source_indices_from_tree(), enabled=bool(part_enabled_checkbox.isChecked()), offset_xyz=(part_offset_x_spin.value(), part_offset_y_spin.value(), part_offset_z_spin.value()), rotate_xyz_degrees=(part_rotate_x_spin.value(), part_rotate_y_spin.value(), part_rotate_z_spin.value()), scale_xyz=(part_scale_x_spin.value(), part_scale_y_spin.value(), part_scale_z_spin.value()), uniform_scale=part_uniform_spin.value(), default_adjustment=StaticSourcePartAdjustment)
        if not apply_state.available or not apply_state.changed:
            return False
        if push_undo:
            _push_geometry_undo_snapshot(_source_part_edit_undo_label_helper("adjust"))
        for target_source_index in apply_state.target_indices:
            adjustment = _ensure_source_part_adjustment(target_source_index)
            adjustment.enabled = apply_state.enabled
            adjustment.offset_xyz = apply_state.offset_xyz
            adjustment.rotate_xyz_degrees = apply_state.rotate_xyz_degrees
            adjustment.scale_xyz = apply_state.scale_xyz
            adjustment.uniform_scale = apply_state.uniform_scale
            source_item = source_items_by_index.get(target_source_index)
            if source_item is not None:
                source_tree_item_update_guard['active'] = True
                try:
                    source_item.setCheckState(0, Qt.Checked if apply_state.enabled else Qt.Unchecked)
                finally:
                    source_tree_item_update_guard['active'] = False
        _refresh_source_assignment_columns(lightweight=not apply_state.enabled_changed)
        if queue_preview:
            if apply_state.enabled_changed:
                if callable(_sync_highlight_sets):
                    _sync_highlight_sets()
                _set_source_parts_preview_rebuild_pending(_source_part_include_exclude_pending_reason_helper())
                _queue_static_preview_rebuild()
            else:
                _queue_part_transform_preview_update(tuple(apply_state.target_indices))
        return True

    return SimpleNamespace(_update_selected_part_adjustment=_update_selected_part_adjustment)


def create_alignment_selected_part_glow_picker_callbacks(context: dict[str, object]) -> SimpleNamespace:
    state = _StaticReplacementDialogState(context)
    QColor = context.get('QColor')
    QColorDialog = context.get('QColorDialog')
    _selected_part_glow_rgb_from_controls = context.get('_selected_part_glow_rgb_from_controls')
    _set_selected_source_glow_color = context.get('_set_selected_source_glow_color')
    color = context.get('color')
    dialog = context.get('dialog')
    part_glow_color_pick_button = context.get('part_glow_color_pick_button')
    part_glow_color_spins = context.get('part_glow_color_spins')
    rgb = context.get('rgb')
    spin = context.get('spin')
    value = context.get('value')

    prompt_shell_context = context.get('prompt_shell_context')

    def _prompt_context_value(name: str) -> object:
        if isinstance(prompt_shell_context, dict) and name in prompt_shell_context:
            return prompt_shell_context.get(name)
        return context.get(name)

    def _part_glow_color_pick_button() -> object:
        return _prompt_context_value('part_glow_color_pick_button')

    def _part_glow_color_spins() -> tuple[object, ...]:
        spins = _prompt_context_value('part_glow_color_spins')
        if not isinstance(spins, (list, tuple)):
            return ()
        return tuple(
            spin
            for spin in spins
            if callable(getattr(spin, "blockSignals", None))
            and callable(getattr(spin, "setValue", None))
        )

    def _pick_selected_source_glow_color() -> None:
        pick_button = _part_glow_color_pick_button()
        if (
            pick_button is None
            or not callable(getattr(pick_button, "isEnabled", None))
            or not pick_button.isEnabled()
            or not callable(_selected_part_glow_rgb_from_controls)
        ):
            return
        rgb = _selected_part_glow_rgb_from_controls()
        color = QColorDialog.getColor(QColor(rgb[0], rgb[1], rgb[2]), dialog, 'Choose Glow Color')
        if not color.isValid():
            return
        for spin, value in zip(_part_glow_color_spins(), (color.red(), color.green(), color.blue())):
            spin.blockSignals(True)
            spin.setValue(int(value))
            spin.blockSignals(False)
        if callable(_set_selected_source_glow_color):
            _set_selected_source_glow_color()

    return SimpleNamespace(_pick_selected_source_glow_color=_pick_selected_source_glow_color)


def create_alignment_static_preview_refresh_callbacks(context: dict[str, object]) -> SimpleNamespace:
    state = _StaticReplacementDialogState(context)
    List = context.get('List')
    ModelPreviewData = context.get('ModelPreviewData')
    NativePreviewPanel = context.get('NativePreviewPanel')
    _accent_glow_preview_intensity_helper = context.get('_accent_glow_preview_intensity_helper')
    _alignment_d3d11_alignment_preview_failed_performance_helper = context.get('_alignment_d3d11_alignment_preview_failed_performance_helper')
    _alignment_d3d11_display_model_helper = context.get('_alignment_d3d11_display_model_helper')
    _alignment_d3d11_package_queued_performance_helper = context.get('_alignment_d3d11_package_queued_performance_helper')
    _alignment_d3d11_preview_active = context.get('_alignment_d3d11_preview_active')
    _alignment_d3d11_record_direct_source_preview_flags_helper = context.get('_alignment_d3d11_record_direct_source_preview_flags_helper')
    _alignment_mesh_edit_tab_active = context.get('_alignment_mesh_edit_tab_active')
    _alignment_preview_is_interactive = context.get('_alignment_preview_is_interactive')
    _alignment_preview_quality_label_helper = context.get('_alignment_preview_quality_label_helper')
    _alignment_preview_source_face_limit = context.get('_alignment_preview_source_face_limit')
    _alignment_preview_widget_render_settings = context.get('_alignment_preview_widget_render_settings')
    _append_selected_source_highlight_overlay = context.get('_append_selected_source_highlight_overlay')
    _apply_manual_preview_texture_override_specs_helper = context.get('_apply_manual_preview_texture_override_specs_helper')
    _apply_original_material_preview = context.get('_apply_original_material_preview')
    _apply_source_material_preview_for_model_helper = context.get('_apply_source_material_preview_for_model_helper')
    _apply_source_role_emissive_preview_for_model_helper = context.get('_apply_source_role_emissive_preview_for_model_helper')
    _basic_controls_profile_enabled = context.get('_basic_controls_profile_enabled')
    _build_direct_source_preview_model = context.get('_build_direct_source_preview_model')
    _cached_static_preview_geometry_helper = context.get('_cached_static_preview_geometry_helper')
    _capture_static_preview_baked_transform_state = context.get('_capture_static_preview_baked_transform_state')
    _clear_source_parts_preview_rebuild_pending = context.get('_clear_source_parts_preview_rebuild_pending')
    _clone_preview_model = context.get('_clone_preview_model')
    _combine_preview_models = context.get('_combine_preview_models')
    _complete_external_swap_enabled = context.get('_complete_external_swap_enabled')
    _current_alignment_transform_generation = context.get('_current_alignment_transform_generation')
    _current_complete_swap_material_profile_token = context.get('_current_complete_swap_material_profile_token')
    _current_dialog_mappings_for_preview = context.get('_current_dialog_mappings_for_preview')
    _current_material_authority_preview_profile = context.get('_current_material_authority_preview_profile')
    _current_static_placement_snapshot = context.get('_current_static_placement_snapshot')
    _direct_source_preview_indices_helper = context.get('_direct_source_preview_indices_helper')
    _ensure_original_reference_texture_preview_ready = context.get('_ensure_original_reference_texture_preview_ready')
    _infer_model_preview_normal_strength = context.get('_infer_model_preview_normal_strength')
    _is_gltf_metallic_roughness_path = context.get('_is_gltf_metallic_roughness_path')
    _mapped_source_indices = context.get('_mapped_source_indices')
    _mapped_source_indices_helper = context.get('_mapped_source_indices_helper')
    _material_authority_preview_inactive_reason = context.get('_material_authority_preview_inactive_reason')
    _material_authority_preview_parameters_helper = context.get('_material_authority_preview_parameters_helper')
    _material_authority_preview_signature = context.get('_material_authority_preview_signature')
    _mesh_edit_preview_source_indices = context.get('_mesh_edit_preview_source_indices')
    _original_overlay_preview_model_state_helper = context.get('_original_overlay_preview_model_state_helper')
    _original_texture_preview_material_preview_enabled_helper = context.get('_original_texture_preview_material_preview_enabled_helper')
    _overlay_editable_mesh_state_helper = context.get('_overlay_editable_mesh_state_helper')

    def _alignment_transform_generation() -> int:
        if not callable(_current_alignment_transform_generation):
            return 0
        return int(_current_alignment_transform_generation() or 0)

    def _mesh_edit_tab_active() -> bool:
        if not callable(_alignment_mesh_edit_tab_active):
            return False
        return bool(_alignment_mesh_edit_tab_active())

    def _mesh_edit_enabled_checked() -> bool:
        is_checked = getattr(mesh_edit_enabled_checkbox, "isChecked", None)
        if not callable(is_checked):
            return False
        try:
            return bool(is_checked())
        except RuntimeError:
            return False

    def _alignment_preview_is_interactive_value() -> bool:
        if not callable(_alignment_preview_is_interactive):
            return False
        return bool(_alignment_preview_is_interactive())

    def _basic_controls_profile_enabled_value() -> bool:
        if not callable(_basic_controls_profile_enabled):
            return False
        return bool(_basic_controls_profile_enabled())

    def _complete_external_swap_enabled_value() -> bool:
        if not callable(_complete_external_swap_enabled):
            return False
        return bool(_complete_external_swap_enabled())

    def _complete_swap_material_profile_token_value() -> str:
        if not callable(_current_complete_swap_material_profile_token):
            return ""
        return str(_current_complete_swap_material_profile_token() or "")

    def _material_authority_preview_inactive_reason_value() -> str:
        if not callable(_material_authority_preview_inactive_reason):
            return ""
        return str(_material_authority_preview_inactive_reason() or "")

    def _mesh_edit_preview_source_indices_value() -> tuple[int, ...]:
        if not callable(_mesh_edit_preview_source_indices):
            return ()
        return tuple(_mesh_edit_preview_source_indices() or ())

    def _mapped_source_indices_value(mappings: object) -> set[int]:
        if callable(_mapped_source_indices):
            return set(_mapped_source_indices(mappings) or ())
        if callable(_mapped_source_indices_helper):
            return set(_mapped_source_indices_helper(mappings) or ())
        return set()

    _preview_model_in_original_frame = context.get('_preview_model_in_original_frame')
    _preview_target_mesh_indices = context.get('_preview_target_mesh_indices')
    _queue_alignment_d3d11_preview = context.get('_queue_alignment_d3d11_preview')
    _record_runtime_event = context.get('_record_runtime_event')
    if not callable(_record_runtime_event):
        _record_runtime_event = lambda *_args, **_kwargs: None
    _refresh_alignment_virtual_sidecar_contract = context.get('_refresh_alignment_virtual_sidecar_contract')
    _remember_alignment_d3d11_source_editor_ids = context.get('_remember_alignment_d3d11_source_editor_ids')
    _resolve_model_texture_semantic_details = context.get('_resolve_model_texture_semantic_details')
    _restore_static_preview_geometry_cache_payload_helper = context.get('_restore_static_preview_geometry_cache_payload_helper')
    _selected_part_preview_indices = context.get('_selected_part_preview_indices')
    _set_alignment_d3d11_loading = context.get('_set_alignment_d3d11_loading')
    _set_cached_static_preview_model = context.get('_set_cached_static_preview_model')
    _set_preview_performance_status = context.get('_set_preview_performance_status')
    _should_use_direct_source_preview_helper = context.get('_should_use_direct_source_preview_helper')
    _source_display_name = context.get('_source_display_name')
    _source_index_is_enabled_renderable = context.get('_source_index_is_enabled_renderable')
    _source_preview_geometry_cache_key_helper = context.get('_source_preview_geometry_cache_key_helper')
    _source_preview_geometry_key = context.get('_source_preview_geometry_key')
    _static_options_from_placement_snapshot = context.get('_static_options_from_placement_snapshot')
    _static_preview_geometry_cache_payload_helper = context.get('_static_preview_geometry_cache_payload_helper')
    _static_preview_prepared_cache_key_helper = context.get('_static_preview_prepared_cache_key_helper')
    _static_preview_prepared_cache_result_helper = context.get('_static_preview_prepared_cache_result_helper')
    _static_preview_refresh_performance_status_helper = context.get('_static_preview_refresh_performance_status_helper')
    _static_preview_refresh_route_state_helper = context.get('_static_preview_refresh_route_state_helper')
    _static_preview_upload_elapsed_ms_helper = context.get('_static_preview_upload_elapsed_ms_helper')
    _static_preview_widget_mode_state_helper = context.get('_static_preview_widget_mode_state_helper')
    _static_preview_widget_model_action_helper = context.get('_static_preview_widget_model_action_helper')
    _store_static_preview_cache_entry_helper = context.get('_store_static_preview_cache_entry_helper')
    _sync_mesh_edit_preview_settings = context.get('_sync_mesh_edit_preview_settings')
    _tag_alignment_d3d11_workspace_model = context.get('_tag_alignment_d3d11_workspace_model')
    _texture_set_factor_parameters = context.get('_texture_set_factor_parameters')
    _texture_set_for_mapping_helper = context.get('_texture_set_for_mapping_helper')
    _texture_set_for_source_index = context.get('_texture_set_for_source_index')
    accent_glow_spin = context.get('accent_glow_spin')
    active_preview_mode = context.get('active_preview_mode')
    alignment_d3d11_state = context.get('alignment_d3d11_state')
    appended_source_indices = context.get('appended_source_indices')
    auto_brightness_spin = context.get('auto_brightness_spin')
    build_static_replacement_preview_mesh = context.get('build_static_replacement_preview_mesh')
    cache_key = context.get('cache_key')
    cache_suffix = context.get('cache_suffix')
    cached_preview = context.get('cached_preview')
    contract = context.get('contract')
    current_mappings = context.get('current_mappings')
    d3d11_preview_model = context.get('d3d11_preview_model')
    defer_original_texture_preview = context.get('defer_original_texture_preview')
    dialog_title = context.get('dialog_title')
    direct_source_preview_index_map = context.get('direct_source_preview_index_map')
    direct_source_preview_indices = context.get('direct_source_preview_indices')
    edge_relief_source_combo = context.get('edge_relief_source_combo')
    edge_relief_spin = context.get('edge_relief_spin')
    editable_kind = context.get('editable_kind')
    editable_value = context.get('editable_value')
    entry = context.get('entry')
    exc = context.get('exc')
    force_direct_source_preview = context.get('force_direct_source_preview')
    geometry_elapsed_ms = context.get('geometry_elapsed_ms')
    geometry_started = context.get('geometry_started')
    global_gloss_reduction_spin = context.get('global_gloss_reduction_spin')
    highlighted_original_indices = context.get('highlighted_original_indices')
    highlighted_source_indices = context.get('highlighted_source_indices')
    independent_base_index = context.get('independent_base_index')
    independent_ordinal = context.get('independent_ordinal')
    independent_part = context.get('independent_part')
    independent_preview_parts = context.get('independent_preview_parts')
    interactive_preview = context.get('interactive_preview')
    live_mesh_edit = context.get('live_mesh_edit')
    mapped = context.get('mapped')
    mapped_preview = context.get('mapped_preview')
    mapped_preview_source_indices = context.get('mapped_preview_source_indices')
    mapping = context.get('mapping')
    mappings = context.get('mappings')
    material_authority_preview_signature_state = context.get('material_authority_preview_signature_state')
    material_authority_preview_texture_slots = context.get('material_authority_preview_texture_slots')
    mesh_edit_direct_source_preview = context.get('mesh_edit_direct_source_preview')
    mesh_edit_enabled_checkbox = context.get('mesh_edit_enabled_checkbox')
    model = context.get('model')
    modify_original_clone_mode = context.get('modify_original_clone_mode')
    needs_original_material_preview = context.get('needs_original_material_preview')
    original_mesh_count = context.get('original_mesh_count')
    original_mesh_for_mapping = context.get('original_mesh_for_mapping')
    original_overlay_model = context.get('original_overlay_model')
    original_texture_preview_state = context.get('original_texture_preview_state')
    overlay_dialog_preview = context.get('overlay_dialog_preview')
    overlay_model = context.get('overlay_model')
    overlay_original_locked_checkbox = context.get('overlay_original_locked_checkbox')
    overlay_view_state = context.get('overlay_view_state')
    package_queued_presentation = context.get('package_queued_presentation')
    parsed_submesh_index = context.get('parsed_submesh_index')
    placement_snapshot = context.get('placement_snapshot')
    prepare_model_preview = context.get('prepare_model_preview')
    prepared_cache_result = context.get('prepared_cache_result')
    prepared_elapsed_ms = context.get('prepared_elapsed_ms')
    prepared_key = context.get('prepared_key')
    preview_accent_glow_intensity = context.get('preview_accent_glow_intensity')
    preview_controls_ready = context.get('preview_controls_ready')
    preview_failed_presentation = context.get('preview_failed_presentation')
    preview_index = context.get('preview_index')
    preview_material_authority_parameters = context.get('preview_material_authority_parameters')
    preview_material_authority_profile = context.get('preview_material_authority_profile')
    preview_mesh = context.get('preview_mesh')
    preview_mode_combo = context.get('preview_mode_combo')
    preview_model = context.get('preview_model')
    preview_performance = context.get('preview_performance')
    preview_replacement_mesh = context.get('preview_replacement_mesh')
    preview_submesh_index_map = context.get('preview_submesh_index_map')
    preview_widget = context.get('preview_widget')
    refresh_elapsed_ms = context.get('refresh_elapsed_ms')
    refresh_route = context.get('refresh_route')
    refresh_started = context.get('refresh_started')
    refresh_transform_generation = context.get('refresh_transform_generation')
    refreshed_preview_widgets = context.get('refreshed_preview_widgets')
    replacement_mesh_count = context.get('replacement_mesh_count')
    replacement_only_preview = context.get('replacement_only_preview')
    replacement_only_view_state = context.get('replacement_only_view_state')
    replacement_texture_slot_preview_semantics = context.get('replacement_texture_slot_preview_semantics')
    selected_preview_indices = context.get('selected_preview_indices')
    selected_source_highlight_indices = context.get('selected_source_highlight_indices')
    source_brightness_spin = context.get('source_brightness_spin')
    source_indices = context.get('source_indices')
    source_model = context.get('source_model')
    source_overlay_preview_index_map = context.get('source_overlay_preview_index_map')
    source_part_adjustments = context.get('source_part_adjustments')
    source_preview_cache_key = context.get('source_preview_cache_key')
    source_role_profile = context.get('source_role_profile')
    source_selection_overlay_editor_id_map = context.get('source_selection_overlay_editor_id_map')
    source_selection_overlay_preview_index_map = context.get('source_selection_overlay_preview_index_map')
    static_dialog_preview = context.get('static_dialog_preview')
    static_preview_geometry_cache = context.get('static_preview_geometry_cache')
    static_preview_prepared_cache = context.get('static_preview_prepared_cache')
    static_view_state = context.get('static_view_state')
    target_name = context.get('target_name')
    texture_overrides_dirty = context.get('texture_overrides_dirty')
    time = context.get('time')
    tone_contrast_spin = context.get('tone_contrast_spin')
    updated_specs = context.get('updated_specs')
    upload_elapsed_ms = context.get('upload_elapsed_ms')
    use_direct_source_preview = context.get('use_direct_source_preview')
    use_original_material_preview = context.get('use_original_material_preview')
    view_state = context.get('view_state')
    widget = context.get('widget')
    widget_action = context.get('widget_action')
    widget_mode_state = context.get('widget_mode_state')

    def _refresh_static_dialog_preview(*, live_mesh_edit: bool = False) -> None:
        refresh_started = time.perf_counter()
        refresh_transform_generation = _alignment_transform_generation()
        geometry_elapsed_ms = 0.0
        prepared_elapsed_ms = 0.0
        if state.replacement_preview_model is None:
            _record_runtime_event(
                "mesh_alignment_preview_refresh_skipped",
                path=getattr(entry, "path", ""),
                dialog_title=dialog_title,
                reason="missing_replacement_preview_model",
                modify_original_clone=modify_original_clone_mode,
            )
            return
        for preview_widget in (static_dialog_preview, overlay_dialog_preview, replacement_only_preview):
            preview_widget.set_alignment_editing_enabled(True)
        current_mappings = _current_dialog_mappings_for_preview()
        mapped_preview = False
        source_preview_cache_key = ''
        active_preview_mode = str(preview_mode_combo.currentData() or 'side_by_side')
        needs_original_material_preview = _original_texture_preview_material_preview_enabled_helper(modify_original_clone_mode, original_texture_preview_state)
        refresh_route = _static_preview_refresh_route_state_helper(active_preview_mode=active_preview_mode, mesh_edit_enabled=_mesh_edit_enabled_checked(), mesh_edit_tab_active=_mesh_edit_tab_active(), replacement_mesh_available=state.replacement_mesh_for_mapping is not None, interactive_preview=_alignment_preview_is_interactive_value(), complete_external_swap_enabled=_complete_external_swap_enabled_value(), needs_original_material_preview=needs_original_material_preview, preview_controls_ready=bool(preview_controls_ready.get('ready')), original_mesh_available=original_mesh_for_mapping is not None)
        mesh_edit_direct_source_preview = refresh_route.mesh_edit_direct_source_preview
        force_direct_source_preview = _alignment_d3d11_record_direct_source_preview_flags_helper(alignment_d3d11_state, replacement_only_direct_source_preview=refresh_route.replacement_only_direct_source_preview, source_owned_direct_source_preview=refresh_route.source_owned_direct_source_preview)
        if refresh_route.require_original_reference and (not _ensure_original_reference_texture_preview_ready(active_preview_mode, reason='preview_refresh')):
            _record_runtime_event(
                "mesh_alignment_preview_refresh_waiting",
                path=getattr(entry, "path", ""),
                dialog_title=dialog_title,
                active_preview_mode=active_preview_mode,
                reason="original_reference_texture_preview",
                modify_original_clone=modify_original_clone_mode,
            )
            return
        direct_source_preview_indices = _direct_source_preview_indices_helper(selected_source_highlight_indices, force_direct_source_preview=force_direct_source_preview, replacement_submesh_count=len(getattr(state.replacement_mesh_for_mapping, 'submeshes', ()) or ()), mesh_edit_direct_source_preview=mesh_edit_direct_source_preview, mesh_edit_source_indices=_mesh_edit_preview_source_indices_value() if mesh_edit_direct_source_preview else (), source_index_is_enabled_renderable=_source_index_is_enabled_renderable)
        mapped_preview_source_indices = _mapped_source_indices_value(current_mappings)
        use_direct_source_preview = _should_use_direct_source_preview_helper(direct_source_preview_indices, force_direct_source_preview=force_direct_source_preview, mesh_edit_direct_source_preview=mesh_edit_direct_source_preview, appended_source_indices=appended_source_indices, mapped_source_indices=mapped_preview_source_indices, active_preview_mode=active_preview_mode, original_mesh_available=original_mesh_for_mapping is not None, replacement_mesh_available=state.replacement_mesh_for_mapping is not None)
        if not use_direct_source_preview:
            direct_source_preview_index_map.clear()
        source_overlay_preview_index_map.clear()
        source_selection_overlay_preview_index_map.clear()
        source_selection_overlay_editor_id_map.clear()
        preview_submesh_index_map.clear()
        if refresh_route.can_build_source_geometry:
            cache_key = ""
            if callable(_source_preview_geometry_key) and callable(_source_preview_geometry_cache_key_helper):
                cache_key = _source_preview_geometry_cache_key_helper(_source_preview_geometry_key(current_mappings), use_direct_source_preview=use_direct_source_preview, direct_source_preview_indices=direct_source_preview_indices)
            source_preview_cache_key = cache_key
            cached_preview = _cached_static_preview_geometry_helper(static_preview_geometry_cache, cache_key, live_mesh_edit=live_mesh_edit) if cache_key else None
            if cached_preview is not None:
                source_model, mapped_preview = _restore_static_preview_geometry_cache_payload_helper(cached_preview, direct_source_preview_index_map=direct_source_preview_index_map, source_overlay_preview_index_map=source_overlay_preview_index_map, preview_submesh_index_map=preview_submesh_index_map)
            else:
                try:
                    if use_direct_source_preview:
                        direct_source_preview_index_map.clear()
                        preview_submesh_index_map.clear()
                        source_model = _build_direct_source_preview_model(current_mappings, tuple(direct_source_preview_indices)) or state.replacement_preview_model
                        mapped_preview = False
                    else:
                        preview_replacement_mesh = state.replacement_mesh_for_mapping or state.replacement_mesh_base_for_mapping
                        placement_snapshot = _current_static_placement_snapshot(current_mappings, include_preview_only_independent_parts=True)
                        independent_preview_parts = list(placement_snapshot.get('independent_output_parts', []) or [])
                        geometry_started = time.perf_counter()
                        preview_mesh = build_static_replacement_preview_mesh(original_mesh_for_mapping, preview_replacement_mesh, _static_options_from_placement_snapshot(placement_snapshot, complete_external_swap=_complete_external_swap_enabled_value(), complete_external_material_reset=_complete_external_swap_enabled_value(), complete_swap_material_profile=_complete_swap_material_profile_token_value(), global_gloss_reduction=float(global_gloss_reduction_spin.value()), edge_relief_strength=float(edge_relief_spin.value()), edge_relief_source=str(edge_relief_source_combo.currentData() or 'hybrid'), accent_glow_strength=float(accent_glow_spin.value()), auto_brightness_balance=float(auto_brightness_spin.value()), dark_detail_lift=float(source_brightness_spin.value()), tone_contrast=float(tone_contrast_spin.value())), max_source_faces_per_submesh=_alignment_preview_source_face_limit())
                        geometry_elapsed_ms += (time.perf_counter() - geometry_started) * 1000.0
                        source_overlay_preview_index_map.clear()
                        preview_submesh_index_map.clear()
                        independent_base_index = len(getattr(original_mesh_for_mapping, 'submeshes', ()) or ())
                        source_model = _preview_model_in_original_frame(preview_mesh, parsed_submesh_index_map=preview_submesh_index_map)
                        for independent_ordinal, independent_part in enumerate(independent_preview_parts):
                            parsed_submesh_index = independent_base_index + independent_ordinal
                            preview_index = preview_submesh_index_map.get(parsed_submesh_index)
                            if preview_index is not None:
                                source_overlay_preview_index_map[int(independent_part.source_submesh_index)] = preview_index
                        mapped_preview = True
                    if cache_key and not live_mesh_edit:
                        _store_static_preview_cache_entry_helper(static_preview_geometry_cache, cache_key, _static_preview_geometry_cache_payload_helper(source_model, mapped_preview=mapped_preview, direct_source_preview_index_map=direct_source_preview_index_map, source_overlay_preview_index_map=source_overlay_preview_index_map, preview_submesh_index_map=preview_submesh_index_map), paired_cache_to_clear=static_preview_prepared_cache)
                except Exception:
                    preview_submesh_index_map.clear()
                    source_model = state.replacement_preview_model
        else:
            _record_runtime_event(
                "mesh_alignment_preview_refresh_waiting",
                path=getattr(entry, "path", ""),
                dialog_title=dialog_title,
                active_preview_mode=active_preview_mode,
                reason="source_geometry_not_ready",
                modify_original_clone=modify_original_clone_mode,
            )
            return
        preview_model = _clone_preview_model(source_model)
        _apply_original_material_preview(preview_model, mapped_preview=mapped_preview, current_mappings=current_mappings)
        try:
            preview_material_authority_profile = _current_material_authority_preview_profile()
        except Exception:
            preview_material_authority_profile = None
        preview_accent_glow_intensity = _accent_glow_preview_intensity_helper(preview_material_authority_profile) if preview_material_authority_profile is not None else 1.0
        preview_material_authority_parameters = _material_authority_preview_parameters_helper(preview_material_authority_profile, enabled=True) if preview_material_authority_profile is not None and _complete_external_swap_enabled_value() and _basic_controls_profile_enabled_value() else ()
        use_original_material_preview = _original_texture_preview_material_preview_enabled_helper(modify_original_clone_mode, original_texture_preview_state)
        if state.texture_sets and (not use_original_material_preview) and (not mesh_edit_direct_source_preview):
            _apply_source_material_preview_for_model_helper(preview_model, use_direct_source_preview=use_direct_source_preview, direct_source_preview_index_map=direct_source_preview_index_map, mapped_preview=mapped_preview, source_overlay_preview_index_map=source_overlay_preview_index_map, current_mappings=current_mappings, texture_sets=state.texture_sets, material_authority_profile=preview_material_authority_profile, complete_external_swap_enabled=_complete_external_swap_enabled_value(), basic_controls_profile_enabled=_basic_controls_profile_enabled_value(), texture_set_for_source_index=_texture_set_for_source_index, texture_set_for_mapping=lambda mapping: _texture_set_for_mapping_helper(mapping, texture_sets=state.texture_sets, replacement_mesh=state.replacement_mesh_for_mapping, texture_set_for_source_index=_texture_set_for_source_index), source_display_name=_source_display_name, preview_target_mesh_indices=_preview_target_mesh_indices, texture_set_factor_parameters=_texture_set_factor_parameters, material_authority_preview_texture_slots=material_authority_preview_texture_slots, replacement_texture_slot_preview_semantics=replacement_texture_slot_preview_semantics, resolve_model_texture_semantic_details=_resolve_model_texture_semantic_details, is_gltf_metallic_roughness_path=_is_gltf_metallic_roughness_path, infer_model_preview_normal_strength=_infer_model_preview_normal_strength, accent_glow_preview_intensity=preview_accent_glow_intensity)
        source_role_profile = preview_material_authority_profile if preview_material_authority_profile is not None else object()
        _apply_source_role_emissive_preview_for_model_helper(preview_model, use_direct_source_preview=use_direct_source_preview, direct_source_preview_index_map=direct_source_preview_index_map, mapped_preview=mapped_preview, source_overlay_preview_index_map=source_overlay_preview_index_map, current_mappings=current_mappings, texture_sets=state.texture_sets, source_part_adjustments=source_part_adjustments, profile=source_role_profile, texture_set_for_source_index=_texture_set_for_source_index, source_display_name=_source_display_name, preview_target_mesh_indices=_preview_target_mesh_indices)
        preview_model = _append_selected_source_highlight_overlay(preview_model, current_mappings)
        if not use_direct_source_preview and (not mesh_edit_direct_source_preview):
            if texture_overrides_dirty['dirty']:
                contract = _refresh_alignment_virtual_sidecar_contract(current_mappings)
                updated_specs = list(contract.get("preview_specs") or ())
                state.texture_override_preview_specs = updated_specs
                texture_overrides_dirty['dirty'] = False
            _apply_manual_preview_texture_override_specs_helper(preview_model, state.texture_override_preview_specs, mapped_preview=mapped_preview, current_mappings=current_mappings, preview_target_mesh_indices=lambda model, target_name, source_indices, mapped, mappings: _preview_target_mesh_indices(model, target_name, source_indices, mapped_preview=mapped, current_mappings=mappings), resolve_model_texture_semantic_details=_resolve_model_texture_semantic_details, replacement_texture_slot_preview_semantics=replacement_texture_slot_preview_semantics, is_gltf_metallic_roughness_path=_is_gltf_metallic_roughness_path, infer_model_preview_normal_strength=_infer_model_preview_normal_strength, material_authority_preview_parameters=preview_material_authority_parameters, accent_glow_preview_intensity=preview_accent_glow_intensity)
        if not _material_authority_preview_inactive_reason_value():
            try:
                material_authority_preview_signature_state.update(_material_authority_preview_signature())
            except Exception:
                pass
        static_view_state = static_dialog_preview.view_state_snapshot()
        replacement_only_view_state = replacement_only_preview.view_state_snapshot()
        overlay_view_state = overlay_dialog_preview.view_state_snapshot()
        selected_preview_indices = _selected_part_preview_indices(preview_model, mapped_preview=mapped_preview, current_mappings=current_mappings)
        _remember_alignment_d3d11_source_editor_ids(preview_model, mapped_preview=mapped_preview, current_mappings=current_mappings)
        refreshed_preview_widgets: List[NativePreviewPanel] = []
        if _alignment_d3d11_preview_active():
            d3d11_preview_model = _alignment_d3d11_display_model_helper(preview_model, state.original_reference_preview_model, active_preview_mode=active_preview_mode, tag_workspace_model=_tag_alignment_d3d11_workspace_model, combine_preview_models=_combine_preview_models, clone_model=_clone_preview_model)
            _record_runtime_event(
                "mesh_alignment_preview_refresh_d3d11",
                path=getattr(entry, "path", ""),
                dialog_title=dialog_title,
                active_preview_mode=active_preview_mode,
                d3d11_model_ready=d3d11_preview_model is not None,
                source_model_meshes=len(getattr(preview_model, "meshes", ()) or ()),
                original_model_meshes=len(getattr(state.original_reference_preview_model, "meshes", ()) or ()),
                modify_original_clone=modify_original_clone_mode,
            )
            if d3d11_preview_model is not None:
                _queue_alignment_d3d11_preview(d3d11_preview_model, label=f"{active_preview_mode.replace('_', ' ').title()} alignment preview")
            _sync_mesh_edit_preview_settings()
            _capture_static_preview_baked_transform_state(selected_preview_indices, transform_generation=refresh_transform_generation)
            package_queued_presentation = _alignment_d3d11_package_queued_performance_helper(quality_label=_alignment_preview_quality_label_helper(alignment_d3d11_state), refresh_elapsed_ms=(time.perf_counter() - refresh_started) * 1000.0)
            _set_preview_performance_status(package_queued_presentation.summary, details=package_queued_presentation.details)
            return

        def _set_cached_static_preview_model(widget: NativePreviewPanel, model: ModelPreviewData, view_state: object, *, cache_suffix: str) -> None:
            nonlocal prepared_elapsed_ms
            interactive_preview = _alignment_preview_is_interactive_value()
            widget.set_render_settings(_alignment_preview_widget_render_settings())
            widget.set_use_textures(True)
            widget.set_high_quality_textures(not interactive_preview)
            prepared_key = _static_preview_prepared_cache_key_helper(model, source_preview_cache_key=source_preview_cache_key, active_preview_mode=active_preview_mode, cache_suffix=cache_suffix, selected_preview_indices=selected_preview_indices, highlighted_source_indices=tuple(highlighted_source_indices), highlighted_original_indices=tuple(highlighted_original_indices), texture_override_preview_specs=state.texture_override_preview_specs, material_authority_preview_signature=material_authority_preview_signature_state.get('cache', ''))
            widget_action = _static_preview_widget_model_action_helper(live_mesh_edit=live_mesh_edit, prepared_key=prepared_key)
            if widget_action.preserve_mesh_edit_cache:
                widget.set_model_preserving_view(model, preserve_mesh_edit_cache=True)
                refreshed_preview_widgets.append(widget)
                return
            elif widget_action.use_prepared_cache:
                prepared_cache_result = _static_preview_prepared_cache_result_helper(static_preview_prepared_cache, model, prepared_key=widget_action.prepared_key, prepare_model_preview=prepare_model_preview)
                prepared_elapsed_ms += prepared_cache_result.prepare_elapsed_ms
                widget.set_prepared_model(prepared_cache_result.prepared_model, prepared_cache_result.prepared_preview, prepare_elapsed_ms=prepared_cache_result.prepare_elapsed_ms)
            else:
                widget.set_model(model)
            refreshed_preview_widgets.append(widget)
            widget.restore_view_state(view_state)
        widget_mode_state = _static_preview_widget_mode_state_helper(active_preview_mode)
        if widget_mode_state.update_side_by_side:
            _set_cached_static_preview_model(static_dialog_preview, preview_model, static_view_state, cache_suffix='side_by_side')
            if selected_preview_indices is not None:
                static_dialog_preview.set_alignment_editable_mesh_indices(selected_preview_indices)
            else:
                static_dialog_preview.set_alignment_editable_mesh_range(0, -1)
        elif widget_mode_state.update_replacement_only:
            _set_cached_static_preview_model(replacement_only_preview, preview_model, replacement_only_view_state, cache_suffix='replacement_only')
            if selected_preview_indices is not None:
                replacement_only_preview.set_alignment_editable_mesh_indices(selected_preview_indices)
            else:
                replacement_only_preview.set_alignment_editable_mesh_range(0, -1)
        if widget_mode_state.update_overlay and state.original_reference_preview_model is not None:
            original_overlay_model = _original_overlay_preview_model_state_helper(state.original_reference_preview_model, highlighted_indices=highlighted_original_indices, highlight_color=(1.0, 0.72, 0.22))
            overlay_model = _combine_preview_models(original_overlay_model, preview_model)
            if overlay_model is not None:
                interactive_preview = _alignment_preview_is_interactive_value()
                overlay_dialog_preview.set_render_settings(_alignment_preview_widget_render_settings())
                overlay_dialog_preview.set_use_textures(True)
                overlay_dialog_preview.set_high_quality_textures(not interactive_preview)
                if live_mesh_edit:
                    overlay_dialog_preview.set_model_preserving_view(overlay_model, preserve_mesh_edit_cache=True)
                else:
                    overlay_dialog_preview.set_model(overlay_model)
                    overlay_dialog_preview.restore_view_state(overlay_view_state)
                refreshed_preview_widgets.append(overlay_dialog_preview)
                original_mesh_count = len(getattr(state.original_reference_preview_model, 'meshes', ()) or ())
                replacement_mesh_count = len(getattr(preview_model, 'meshes', ()) or ())
                editable_kind, editable_value = _overlay_editable_mesh_state_helper(original_mesh_count, replacement_mesh_count, selected_preview_indices=selected_preview_indices, original_locked=overlay_original_locked_checkbox.isChecked())
                if editable_kind == 'indices':
                    overlay_dialog_preview.set_alignment_editable_mesh_indices(list(editable_value))
                else:
                    overlay_dialog_preview.set_alignment_editable_mesh_range(*editable_value)
        _sync_mesh_edit_preview_settings()
        _capture_static_preview_baked_transform_state(selected_preview_indices, transform_generation=refresh_transform_generation)
        upload_elapsed_ms = _static_preview_upload_elapsed_ms_helper(refreshed_preview_widgets)
        refresh_elapsed_ms = (time.perf_counter() - refresh_started) * 1000.0
        preview_performance = _static_preview_refresh_performance_status_helper(quality_label=_alignment_preview_quality_label_helper(alignment_d3d11_state), refresh_ms=refresh_elapsed_ms, geometry_ms=geometry_elapsed_ms, prepare_ms=prepared_elapsed_ms, upload_ms=upload_elapsed_ms)
        _set_preview_performance_status(preview_performance.text, details=preview_performance.tooltip)
        _clear_source_parts_preview_rebuild_pending()

    def _safe_refresh_static_dialog_preview(*, live_mesh_edit: bool = False) -> None:
        try:
            _refresh_static_dialog_preview(live_mesh_edit=live_mesh_edit)
        except Exception as exc:
            _record_runtime_event("mesh_alignment_preview_refresh_failed", path=getattr(entry, "path", ""), dialog_title=dialog_title, message=str(exc), traceback=traceback.format_exc(), modify_original_clone=modify_original_clone_mode, defer_original_texture_preview=defer_original_texture_preview)
            _set_alignment_d3d11_loading(False, f'Preview failed: {exc}')
            preview_failed_presentation = _alignment_d3d11_alignment_preview_failed_performance_helper(str(exc))
            _set_preview_performance_status(preview_failed_presentation.summary, details=preview_failed_presentation.details)
            _clear_source_parts_preview_rebuild_pending()

    return SimpleNamespace(_refresh_static_dialog_preview=_refresh_static_dialog_preview, _safe_refresh_static_dialog_preview=_safe_refresh_static_dialog_preview)


def create_alignment_original_texture_worker_callbacks(context: dict[str, object]) -> SimpleNamespace:
    state = _StaticReplacementDialogState(context)
    ModelPreviewData = context.get('ModelPreviewData')
    QObject = context.get('QObject')
    Slot = context.get('Slot')
    _alignment_d3d11_clear_archive_parity_upgrade_helper = context.get('_alignment_d3d11_clear_archive_parity_upgrade_helper')
    _alignment_d3d11_invalidate_package_cache = context.get('_alignment_d3d11_invalidate_package_cache')
    _alignment_d3d11_original_texture_worker_request_current_helper = context.get('_alignment_d3d11_original_texture_worker_request_current_helper')
    _alignment_d3d11_preview_active = context.get('_alignment_d3d11_preview_active')
    _alignment_d3d11_reset_request_state_helper = context.get('_alignment_d3d11_reset_request_state_helper')
    _alignment_d3d11_stop_worker = context.get('_alignment_d3d11_stop_worker')
    _alignment_dialog_widgets_live = context.get('_alignment_dialog_widgets_live')
    _handle_original_reference_texture_preview_error = context.get('_handle_original_reference_texture_preview_error')
    _mark_alignment_d3d11_rebuild_reason = context.get('_mark_alignment_d3d11_rebuild_reason')
    _original_reference_texture_preview_ready_result_state_helper = context.get('_original_reference_texture_preview_ready_result_state_helper')
    _queue_static_preview_refresh = context.get('_queue_static_preview_refresh')
    _record_runtime_event = context.get('_record_runtime_event')
    if not callable(_record_runtime_event):
        _record_runtime_event = lambda *_args, **_kwargs: None
    _set_alignment_d3d11_progress = context.get('_set_alignment_d3d11_progress')
    _set_preview_performance_status = context.get('_set_preview_performance_status')
    alignment_d3d11_state = context.get('alignment_d3d11_state')
    dialog_title = context.get('dialog_title')
    entry = context.get('entry')
    elapsed_ms = context.get('elapsed_ms')
    message = context.get('message')
    modify_original_clone_mode = context.get('modify_original_clone_mode')
    native_material_batches = context.get('native_material_batches')
    original_dialog_preview = context.get('original_dialog_preview')
    original_reference_texture_preview_state = context.get('original_reference_texture_preview_state')
    preview_model = context.get('preview_model')
    preview_model_object = context.get('preview_model_object')
    ready_state = context.get('ready_state')
    request_id = context.get('request_id')

    def _handle_original_reference_texture_preview_ready(request_id: int, preview_model_object: object, native_material_batches: int, elapsed_ms: float) -> None:
        ready_state = _original_reference_texture_preview_ready_result_state_helper(original_reference_texture_preview_state, request_current=_alignment_d3d11_original_texture_worker_request_current_helper(alignment_d3d11_state, request_id), widgets_live=_alignment_dialog_widgets_live(), native_material_batches=native_material_batches, elapsed_ms=elapsed_ms, d3d11_preview_active=_alignment_d3d11_preview_active())
        if not ready_state.handled:
            return
        _record_runtime_event(
            "mesh_alignment_original_texture_preview_ready",
            path=getattr(entry, "path", ""),
            dialog_title=dialog_title,
            request_id=int(request_id or 0),
            native_material_batches=int(native_material_batches or 0),
            d3d11_preview_active=bool(_alignment_d3d11_preview_active()),
            modify_original_clone=modify_original_clone_mode,
        )
        state.original_reference_preview_model = preview_model_object if isinstance(preview_model_object, ModelPreviewData) else state.original_reference_preview_model
        if ready_state.should_apply_manifest_performance:
            _set_preview_performance_status(ready_state.manifest_performance.summary, details=ready_state.manifest_performance.details)
        _alignment_d3d11_reset_request_state_helper(alignment_d3d11_state, clear_active_request_id=False)
        _alignment_d3d11_stop_worker()
        _alignment_d3d11_invalidate_package_cache('material')
        if ready_state.should_update_d3d11_progress:
            _set_alignment_d3d11_progress(15, ready_state.progress_message, stage='source_textures', detail=ready_state.progress_detail)
        elif ready_state.should_apply_model:
            original_dialog_preview.set_model(state.original_reference_preview_model)
            original_dialog_preview.set_use_textures(True)
            original_dialog_preview.set_high_quality_textures(True)
        _alignment_d3d11_clear_archive_parity_upgrade_helper(alignment_d3d11_state)
        _set_preview_performance_status(ready_state.loaded_performance.summary, details=ready_state.loaded_performance.details)
        _mark_alignment_d3d11_rebuild_reason('material')
        _queue_static_preview_refresh()

    class _OriginalTexturePreviewWorkerReceiver(QObject):

        @Slot(int, object, int, float)
        def handle_completed(self, request_id: int, preview_model: object, native_material_batches: int, elapsed_ms: float) -> None:
            _handle_original_reference_texture_preview_ready(request_id, preview_model, native_material_batches, elapsed_ms)

        @Slot(int, str)
        def handle_error(self, request_id: int, message: str) -> None:
            _handle_original_reference_texture_preview_error(request_id, message)

    return SimpleNamespace(_handle_original_reference_texture_preview_ready=_handle_original_reference_texture_preview_ready, _OriginalTexturePreviewWorkerReceiver=_OriginalTexturePreviewWorkerReceiver)


def create_alignment_added_part_texture_override_callbacks(context: dict[str, object]) -> SimpleNamespace:
    state = _StaticReplacementDialogState(context)
    _added_part_texture_override_action_state_helper = context.get('_added_part_texture_override_action_state_helper')
    _queue_texture_preview_refresh = context.get('_queue_texture_preview_refresh')
    _refresh_added_part_texture_tree = context.get('_refresh_added_part_texture_tree')
    _refresh_source_material_plan = context.get('_refresh_source_material_plan')
    _source_material_name_for_index_helper = context.get('_source_material_name_for_index_helper')
    action_state = context.get('action_state')
    assignment_key = context.get('assignment_key')
    inject_base_color_checkbox = context.get('inject_base_color_checkbox')
    material_name = context.get('material_name')
    rebuild_sidecar_checkbox = context.get('rebuild_sidecar_checkbox')
    slot_kind = context.get('slot_kind')
    source_index = context.get('source_index')
    source_material_texture_override_assignments = context.get('source_material_texture_override_assignments')
    source_path = context.get('source_path')
    texture_overrides_dirty = context.get('texture_overrides_dirty')

    def _set_added_part_texture_override(source_index: int, slot_kind: str, source_path: str) -> None:
        material_name = _source_material_name_for_index_helper(source_index, state.replacement_mesh_for_mapping, state.texture_sets)
        action_state = _added_part_texture_override_action_state_helper(source_index=source_index, material_name=material_name, slot_kind=slot_kind, source_path=source_path)
        if not action_state['apply']:
            return
        assignment_key = action_state['assignment_key']
        if not action_state['clear']:
            source_material_texture_override_assignments[assignment_key] = str(action_state['source_path'])
            rebuild_sidecar_checkbox.setChecked(True)
            if action_state['enable_inject_base_color']:
                inject_base_color_checkbox.setChecked(True)
        else:
            source_material_texture_override_assignments.pop(assignment_key, None)
        texture_overrides_dirty['dirty'] = bool(action_state['mark_dirty'])
        try:
            _refresh_source_material_plan()
        except NameError:
            _refresh_added_part_texture_tree(source_index)
        _queue_texture_preview_refresh()

    return SimpleNamespace(_set_added_part_texture_override=_set_added_part_texture_override)


def create_alignment_added_part_texture_choice_callbacks(context: dict[str, object]) -> SimpleNamespace:
    state = _StaticReplacementDialogState(context)
    Path = context.get('Path')
    QFileDialog = context.get('QFileDialog')
    QMessageBox = context.get('QMessageBox')
    SCENE_TEXTURE_SOURCE_EXTENSIONS = context.get('SCENE_TEXTURE_SOURCE_EXTENSIONS')
    _added_part_texture_choose_dialog_state_helper = context.get('_added_part_texture_choose_dialog_state_helper')
    _added_part_texture_invalid_file_message_helper = context.get('_added_part_texture_invalid_file_message_helper')
    _current_added_part_texture_source_index = context.get('_current_added_part_texture_source_index')
    _refresh_source_material_plan = context.get('_refresh_source_material_plan')
    _register_added_part_texture_file = context.get('_register_added_part_texture_file')
    _set_added_part_texture_override = context.get('_set_added_part_texture_override')
    choose_state = context.get('choose_state')
    dialog = context.get('dialog')
    obj_path = context.get('obj_path')
    path = context.get('path')
    resolved = context.get('resolved')
    selected_file = context.get('selected_file')
    slot_kind = context.get('slot_kind')
    source_index = context.get('source_index')

    def _choose_added_part_texture(slot_kind: str) -> None:
        source_index = _current_added_part_texture_source_index()
        choose_state = _added_part_texture_choose_dialog_state_helper(source_index, slot_kind)
        if not choose_state['can_choose']:
            QMessageBox.information(dialog, str(choose_state['title']), str(choose_state['message']))
            return
        selected_file, _ = QFileDialog.getOpenFileName(dialog, str(choose_state['title']), str(obj_path.parent), 'Texture files (*.dds *.png *.tga *.bmp *.jpg *.jpeg);;All files (*.*)')
        if not selected_file:
            return
        path = Path(selected_file)
        if path.suffix.lower() not in SCENE_TEXTURE_SOURCE_EXTENSIONS:
            QMessageBox.warning(dialog, str(choose_state['invalid_title']), str(_added_part_texture_invalid_file_message_helper(path.name)))
            return
        resolved = _register_added_part_texture_file(path)
        _set_added_part_texture_override(source_index, slot_kind, str(resolved))
        _refresh_source_material_plan()

    return SimpleNamespace(_choose_added_part_texture=_choose_added_part_texture)


def create_alignment_preview_pixmap_callbacks(context: dict[str, object]) -> SimpleNamespace:
    state = _StaticReplacementDialogState(context)
    Optional = context.get('Optional')
    Path = context.get('Path')
    QImageReader = context.get('QImageReader')
    QPixmap = context.get('QPixmap')
    image = context.get('image')
    preview_path = context.get('preview_path')
    reader = context.get('reader')

    def _read_preview_pixmap(preview_path: Path) -> Optional[QPixmap]:
        reader = QImageReader(str(preview_path))
        image = reader.read()
        if image.isNull():
            return None
        return QPixmap.fromImage(image)

    return SimpleNamespace(_read_preview_pixmap=_read_preview_pixmap)


def create_alignment_source_material_plan_refresh_callbacks(context: dict[str, object]) -> SimpleNamespace:
    state = _StaticReplacementDialogState(context)
    TEXTURE_PLAN_STATUS_READY = context.get('TEXTURE_PLAN_STATUS_READY')
    TEXTURE_PLAN_STATUS_REVIEW = context.get('TEXTURE_PLAN_STATUS_REVIEW')
    TEXTURE_PLAN_STATUS_SUPPORT_ONLY = context.get('TEXTURE_PLAN_STATUS_SUPPORT_ONLY')
    _alignment_startup_step = context.get('_alignment_startup_step')
    _alignment_startup_texture_plan_progress_text_helper = context.get('_alignment_startup_texture_plan_progress_text_helper')
    _apply_source_material_texture_overrides_to_ui_texture_sets = context.get('_apply_source_material_texture_overrides_to_ui_texture_sets')
    _clear_tree_current_item = context.get('_clear_tree_current_item')
    _current_dialog_mappings_for_preview = context.get('_current_dialog_mappings_for_preview')
    _deferred_material_plan_display_state_helper = context.get('_deferred_material_plan_display_state_helper')
    _empty_material_plan_display_state_helper = context.get('_empty_material_plan_display_state_helper')
    _fit_alignment_tree_height_to_rows = context.get('_fit_alignment_tree_height_to_rows')
    _fit_material_plan_tree_columns = context.get('_fit_material_plan_tree_columns')
    _fit_material_routing_tree_columns = context.get('_fit_material_routing_tree_columns')
    _is_marker_source = context.get('_is_marker_source')
    _material_contract_block = context.get('_material_contract_block')
    _material_plan_profile_stats_helper = context.get('_material_plan_profile_stats_helper')
    _material_plan_route_stats_helper = context.get('_material_plan_route_stats_helper')
    _material_plan_summary_block = context.get('_material_plan_summary_block')
    _material_route_status_color = context.get('_material_route_status_color')
    _material_routing_conflict_messages = context.get('_material_routing_conflict_messages')
    _refresh_added_part_texture_tree = context.get('_refresh_added_part_texture_tree')
    _replacement_texture_plan_item_helper = context.get('_replacement_texture_plan_item_helper')
    _replacement_texture_plan_row_states_helper = context.get('_replacement_texture_plan_row_states_helper')
    _replacement_texture_plan_target_name_helper = context.get('_replacement_texture_plan_target_name_helper')
    _reset_selected_texture_plan_source_state_helper = context.get('_reset_selected_texture_plan_source_state_helper')
    _source_display_name = context.get('_source_display_name')
    _source_indices_for_material_name_helper = context.get('_source_indices_for_material_name_helper')
    _source_indices_for_route_parts_helper = context.get('_source_indices_for_route_parts_helper')
    _source_material_output_path = context.get('_source_material_output_path')
    _source_material_part_summary_helper = context.get('_source_material_part_summary_helper')
    _source_material_plan_display_state_helper = context.get('_source_material_plan_display_state_helper')
    _source_material_route_item_helper = context.get('_source_material_route_item_helper')
    _source_material_route_row_states_helper = context.get('_source_material_route_row_states_helper')
    _source_texture_path_for_plan_row = context.get('_source_texture_path_for_plan_row')
    _sync_texture_transform_materials = context.get('_sync_texture_transform_materials')
    _target_index_for_name = context.get('_target_index_for_name')
    _texture_plan_status_color = context.get('_texture_plan_status_color')
    alignment_startup_text = context.get('alignment_startup_text')
    apply_selected_source_textures_button = context.get('apply_selected_source_textures_button')
    apply_texture_plan_button = context.get('apply_texture_plan_button')
    build_replacement_texture_plan_rows = context.get('build_replacement_texture_plan_rows')
    build_source_material_routing_plan = context.get('build_source_material_routing_plan')
    conflict_messages = context.get('conflict_messages')
    dds_detail_panel = context.get('dds_detail_panel')
    detected_slot_count = context.get('detected_slot_count')
    display_state = context.get('display_state')
    entry = context.get('entry')
    force = context.get('force')
    group_replacement_texture_sets = context.get('group_replacement_texture_sets')
    material_contract_label = context.get('material_contract_label')
    material_name = context.get('material_name')
    material_plan_blocked = context.get('material_plan_blocked')
    material_plan_summary = context.get('material_plan_summary')
    material_plan_tree = context.get('material_plan_tree')
    material_routing_blocked = context.get('material_routing_blocked')
    material_routing_tree = context.get('material_routing_tree')
    plan_row_states = context.get('plan_row_states')
    plan_rows = context.get('plan_rows')
    plan_state = context.get('plan_state')
    profile_stats = context.get('profile_stats')
    route_source_indices = context.get('route_source_indices')
    route_state = context.get('route_state')
    route_stats = context.get('route_stats')
    routing_rows = context.get('routing_rows')
    row_index = context.get('row_index')
    selected_texture_plan_source = context.get('selected_texture_plan_source')
    sidecar_bindings_for_advanced = context.get('sidecar_bindings_for_advanced')
    source_indices_for_plan = context.get('source_indices_for_plan')
    source_path = context.get('source_path')
    source_preview_path = context.get('source_preview_path')
    source_texture_evidence = context.get('source_texture_evidence')
    target_name_for_plan = context.get('target_name_for_plan')
    texture_files_for_mapping = context.get('texture_files_for_mapping') or []
    texture_material_plan_loaded = context.get('texture_material_plan_loaded')
    texture_set = context.get('texture_set')
    texture_transform_group = context.get('texture_transform_group')

    def _refresh_source_material_plan(*, force: bool = False) -> None:
        material_plan_blocked = material_plan_tree.blockSignals(True)
        material_routing_blocked = material_routing_tree.blockSignals(True)
        try:
            _clear_tree_current_item(material_plan_tree)
            _clear_tree_current_item(material_routing_tree)
            material_plan_tree.clear()
            material_routing_tree.clear()
        finally:
            material_plan_tree.blockSignals(material_plan_blocked)
            material_routing_tree.blockSignals(material_routing_blocked)
        _reset_selected_texture_plan_source_state_helper(selected_texture_plan_source)
        dds_detail_panel.setVisible(False)
        texture_transform_group.setVisible(False)
        if not force and (not bool(texture_material_plan_loaded.get('loaded'))):
            display_state = _deferred_material_plan_display_state_helper(state.texture_sets)
            material_plan_summary.setText(_material_plan_summary_block(**display_state.summary_kwargs))
            material_contract_label.setText(_material_contract_block(**display_state.contract_kwargs))
            material_routing_tree.setVisible(display_state.routing_visible)
            material_plan_tree.setVisible(display_state.plan_visible)
            apply_texture_plan_button.setEnabled(display_state.apply_texture_plan_enabled)
            apply_selected_source_textures_button.setEnabled(display_state.apply_selected_source_enabled)
            return
        texture_material_plan_loaded['loaded'] = True
        _alignment_startup_step(alignment_startup_text['replacement_material_maps'])
        state.texture_sets = group_replacement_texture_sets(texture_files_for_mapping, obj_mesh=state.replacement_mesh_for_mapping)
        _apply_source_material_texture_overrides_to_ui_texture_sets(state.texture_sets)
        _sync_texture_transform_materials()
        try:
            _refresh_added_part_texture_tree()
        except NameError:
            pass
        detected_slot_count = sum((len(getattr(texture_set, 'slots', {}) or {}) for texture_set in state.texture_sets.values()))
        if not state.texture_sets:
            display_state = _empty_material_plan_display_state_helper()
            material_plan_summary.setText(_material_plan_summary_block(**display_state.summary_kwargs))
            material_contract_label.setText(_material_contract_block(**display_state.contract_kwargs))
            material_routing_tree.setVisible(display_state.routing_visible)
            material_plan_tree.setVisible(display_state.plan_visible)
            apply_texture_plan_button.setEnabled(display_state.apply_texture_plan_enabled)
            apply_selected_source_textures_button.setEnabled(display_state.apply_selected_source_enabled)
            return
        profile_stats = _material_plan_profile_stats_helper(tuple(source_texture_evidence or ()))
        conflict_messages = _material_routing_conflict_messages(_current_dialog_mappings_for_preview())
        routing_rows = build_source_material_routing_plan(state.replacement_mesh_for_mapping, state.texture_sets, _current_dialog_mappings_for_preview())
        route_stats = _material_plan_route_stats_helper(state.texture_sets, routing_rows, conflict_messages)
        display_state = _source_material_plan_display_state_helper(state.texture_sets, detected_slot_count=detected_slot_count, route_count=len(routing_rows), route_stats=route_stats, profile_stats=profile_stats, has_sidecar_bindings=bool(sidecar_bindings_for_advanced))
        material_plan_summary.setText(_material_plan_summary_block(**display_state.summary_kwargs))
        material_contract_label.setText(_material_contract_block(**display_state.contract_kwargs))
        material_routing_tree.setVisible(display_state.routing_visible)
        for route_state in _source_material_route_row_states_helper(routing_rows):
            route_source_indices = _source_indices_for_route_parts_helper(route_state.source_part_names, state.replacement_mesh_for_mapping, source_material_name=route_state.source_material_name, source_display_name=_source_display_name, source_indices_for_material_name=lambda material_name: _source_indices_for_material_name_helper(material_name, state.replacement_mesh_for_mapping, texture_set_count=len(state.texture_sets), is_marker_source=_is_marker_source), is_marker_source=_is_marker_source)
            material_routing_tree.addTopLevelItem(_source_material_route_item_helper(route_state.route, source_indices=route_source_indices, target_index=_target_index_for_name(route_state.target_material_name), status_color=_material_route_status_color(route_state.status_label)))
        _fit_alignment_tree_height_to_rows(material_routing_tree, minimum=80, screen_margin=420, maximum=180)
        _fit_material_routing_tree_columns()
        material_plan_tree.setVisible(display_state.plan_visible)
        apply_texture_plan_button.setEnabled(display_state.apply_texture_plan_enabled)
        plan_rows = build_replacement_texture_plan_rows(state.texture_sets, final_path_for_source=lambda source_path: _source_material_output_path(source_path, entry.path), part_summary_for_material=lambda material_name: _source_material_part_summary_helper(material_name, state.replacement_mesh_for_mapping, texture_set_count=len(state.texture_sets), is_marker_source=_is_marker_source))
        plan_row_states = _replacement_texture_plan_row_states_helper(plan_rows, ready_statuses=(TEXTURE_PLAN_STATUS_READY, TEXTURE_PLAN_STATUS_REVIEW), support_only_statuses=(TEXTURE_PLAN_STATUS_SUPPORT_ONLY,))
        for row_index, plan_state in enumerate(plan_row_states):
            if row_index and row_index % 24 == 0:
                _alignment_startup_step(_alignment_startup_texture_plan_progress_text_helper(row_index))
            source_indices_for_plan = _source_indices_for_material_name_helper(plan_state.material_name, state.replacement_mesh_for_mapping, texture_set_count=len(state.texture_sets), is_marker_source=_is_marker_source)
            source_preview_path = _source_texture_path_for_plan_row(plan_state.plan_row, plan_state.material_name, state.texture_sets)
            target_name_for_plan = _replacement_texture_plan_target_name_helper(source_indices_for_plan, _current_dialog_mappings_for_preview())
            material_plan_tree.addTopLevelItem(_replacement_texture_plan_item_helper(plan_state.plan_row, source_indices=source_indices_for_plan, target_index=_target_index_for_name(target_name_for_plan), target_name=target_name_for_plan, material_name=plan_state.material_name, source_preview_path=source_preview_path, preview_status=plan_state.preview_status, status_color=_texture_plan_status_color(plan_state.status_label), status_foreground=plan_state.status_foreground))
        _fit_alignment_tree_height_to_rows(material_plan_tree, minimum=76, screen_margin=420, maximum=190)
        _fit_material_plan_tree_columns()

    return SimpleNamespace(_refresh_source_material_plan=_refresh_source_material_plan)


def create_alignment_complete_swap_profile_select_callbacks(context: dict[str, object]) -> SimpleNamespace:
    state = _StaticReplacementDialogState(context)
    _material_authority_requested_profile_name_helper = context.get('_material_authority_requested_profile_name_helper')
    complete_swap_material_profile_combo = context.get('complete_swap_material_profile_combo')
    complete_swap_profile_store_path = context.get('complete_swap_profile_store_path')
    get_complete_swap_material_profile = context.get('get_complete_swap_material_profile')
    name = context.get('name')
    persist = context.get('persist')
    profile_index = context.get('profile_index')
    profile_name = context.get('profile_name')
    requested = context.get('requested')
    self = context.get('self')
    write_complete_swap_calibrated_material_profile = context.get('write_complete_swap_calibrated_material_profile')

    def _select_complete_swap_material_profile(profile_name: str, *, persist: bool = False) -> None:
        requested = _material_authority_requested_profile_name_helper(profile_name, resolve_profile_name=lambda name: getattr(get_complete_swap_material_profile(str(name)), 'name', ''))
        profile_index = complete_swap_material_profile_combo.findData(requested)
        if profile_index < 0:
            requested = 'material_authority_detail_mask'
            profile_index = complete_swap_material_profile_combo.findData(requested)
        if profile_index >= 0 and complete_swap_material_profile_combo.currentIndex() != profile_index:
            complete_swap_material_profile_combo.setCurrentIndex(profile_index)
        if persist:
            self.settings.setValue('settings/complete_swap_material_profile', requested)
            try:
                write_complete_swap_calibrated_material_profile(complete_swap_profile_store_path, requested)
            except Exception:
                pass

    return SimpleNamespace(_select_complete_swap_material_profile=_select_complete_swap_material_profile)


def create_alignment_manual_profile_preset_callbacks(context: dict[str, object]) -> SimpleNamespace:
    state = _StaticReplacementDialogState(context)
    Mapping = context.get('Mapping')
    Sequence = context.get('Sequence')
    _manual_material_profile_presets_payload_helper = context.get('_manual_material_profile_presets_payload_helper')
    json = context.get('json')
    manual_profile_default_values = context.get('manual_profile_default_values')
    manual_profile_presets_key = context.get('manual_profile_presets_key')
    payload = context.get('payload')
    presets = context.get('presets')
    self = context.get('self')

    def _save_manual_profile_presets(presets: Sequence[Mapping[str, object]]) -> None:
        payload = _manual_material_profile_presets_payload_helper(presets, defaults=manual_profile_default_values)
        self.settings.setValue(manual_profile_presets_key, json.dumps(payload, sort_keys=True, separators=(',', ':')))

    return SimpleNamespace(_save_manual_profile_presets=_save_manual_profile_presets)


def create_alignment_manual_profile_control_callbacks(context: dict[str, object]) -> SimpleNamespace:
    state = _StaticReplacementDialogState(context)
    QCheckBox = context.get('QCheckBox')
    QComboBox = context.get('QComboBox')
    QDoubleSpinBox = context.get('QDoubleSpinBox')
    QHBoxLayout = context.get('QHBoxLayout')
    QLabel = context.get('QLabel')
    QSlider = context.get('QSlider')
    QSpinBox = context.get('QSpinBox')
    Qt = context.get('Qt')
    Sequence = context.get('Sequence')
    _current_manual_material_profile_values = context.get('_current_manual_material_profile_values')
    _make_int_spin_helper = context.get('_make_int_spin_helper')
    _queue_material_authority_adjustment_preview_refresh = context.get('_queue_material_authority_adjustment_preview_refresh')
    _refresh_manual_profile_control_effects = context.get('_refresh_manual_profile_control_effects')
    _refresh_output_impact_review = context.get('_refresh_output_impact_review')
    _save_complete_swap_material_profile = context.get('_save_complete_swap_material_profile')
    _set_manual_profile_dirty = context.get('_set_manual_profile_dirty')
    channel_index = context.get('channel_index')
    channel_name = context.get('channel_name')
    channel_spin = context.get('channel_spin')
    channel_value = context.get('channel_value')
    checkbox = context.get('checkbox')
    choices = context.get('choices')
    combo = context.get('combo')
    complete_swap_material_profile_combo = context.get('complete_swap_material_profile_combo')
    index = context.get('index')
    json = context.get('json')
    key = context.get('key')
    label = context.get('label')
    label_widget = context.get('label_widget')
    manual_profile_control_tooltips = context.get('manual_profile_control_tooltips')
    manual_profile_controls = context.get('manual_profile_controls')
    manual_profile_default_values = context.get('manual_profile_default_values')
    manual_profile_effect_widgets = context.get('manual_profile_effect_widgets')
    manual_profile_layout = context.get('manual_profile_layout')
    manual_profile_ready = context.get('manual_profile_ready')
    manual_profile_saved_values = context.get('manual_profile_saved_values')
    manual_profile_settings_key = context.get('manual_profile_settings_key')
    maximum = context.get('maximum')
    minimum = context.get('minimum')
    raw = context.get('raw')
    raw_rgb = context.get('raw_rgb')
    rgb = context.get('rgb')
    row = context.get('row')
    row_layout = context.get('row_layout')
    self = context.get('self')
    slider = context.get('slider')
    slider_scale = context.get('slider_scale')
    spin = context.get('spin')
    spins = context.get('spins')
    step = context.get('step')
    target = context.get('target')
    text = context.get('text')
    tooltip = context.get('tooltip')
    value = context.get('value')
    values = context.get('values')

    def _manual_profile_mark_changed() -> None:
        if not manual_profile_ready.get('ready'):
            return
        values = _current_manual_material_profile_values()
        self.settings.setValue(manual_profile_settings_key, json.dumps(values, sort_keys=True, separators=(',', ':')))
        _save_complete_swap_material_profile()
        _refresh_manual_profile_control_effects(values)
        _set_manual_profile_dirty(True)
        if str(complete_swap_material_profile_combo.currentData() or '') == 'material_authority_manual':
            try:
                _refresh_output_impact_review()
                _queue_material_authority_adjustment_preview_refresh()
            except NameError:
                pass

    def _manual_combo(row: int, key: str, label: str, choices: Sequence[tuple[str, str]], tooltip: str) -> None:
        label_widget = QLabel(label)
        label_widget.setToolTip(tooltip)
        combo = QComboBox()
        combo.setObjectName(f'MeshAlignmentManualMaterialProfile_{key}')
        combo.setToolTip(tooltip)
        for text, value in choices:
            combo.addItem(text, value)
        index = combo.findData(str(manual_profile_saved_values.get(key, '')))
        combo.setCurrentIndex(max(0, index))
        combo.currentIndexChanged.connect(lambda _index: _manual_profile_mark_changed())
        manual_profile_controls[key] = combo
        manual_profile_effect_widgets[key] = [label_widget, combo]
        manual_profile_control_tooltips[key] = tooltip
        manual_profile_layout.addWidget(label_widget, row, 0)
        manual_profile_layout.addWidget(combo, row, 1, 1, 3)

    def _manual_int(row: int, key: str, label: str, minimum: int, maximum: int, tooltip: str) -> None:
        label_widget = QLabel(label)
        label_widget.setToolTip(tooltip)
        slider = QSlider(Qt.Horizontal)
        slider.setObjectName(f'MeshAlignmentManualMaterialProfile_{key}_Slider')
        slider.setRange(minimum, maximum)
        spin = QSpinBox()
        spin.setObjectName(f'MeshAlignmentManualMaterialProfile_{key}_Spin')
        spin.setRange(minimum, maximum)
        value = max(minimum, min(maximum, int(manual_profile_saved_values.get(key, manual_profile_default_values.get(key, minimum)) or minimum)))
        slider.setValue(value)
        spin.setValue(value)
        slider.setToolTip(tooltip)
        spin.setToolTip(tooltip)
        slider.valueChanged.connect(spin.setValue)
        spin.valueChanged.connect(slider.setValue)
        spin.valueChanged.connect(lambda _value: _manual_profile_mark_changed())
        manual_profile_controls[key] = spin
        manual_profile_effect_widgets[key] = [label_widget, slider, spin]
        manual_profile_control_tooltips[key] = tooltip
        manual_profile_layout.addWidget(label_widget, row, 0)
        manual_profile_layout.addWidget(slider, row, 1)
        manual_profile_layout.addWidget(spin, row, 2)

    def _manual_float(row: int, key: str, label: str, minimum: float, maximum: float, step: float, tooltip: str) -> None:
        label_widget = QLabel(label)
        label_widget.setToolTip(tooltip)
        slider_scale = 100
        slider = QSlider(Qt.Horizontal)
        slider.setObjectName(f'MeshAlignmentManualMaterialProfile_{key}_Slider')
        slider.setRange(int(round(minimum * slider_scale)), int(round(maximum * slider_scale)))
        spin = QDoubleSpinBox()
        spin.setObjectName(f'MeshAlignmentManualMaterialProfile_{key}_Spin')
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setDecimals(2)
        value = float(manual_profile_saved_values.get(key, manual_profile_default_values.get(key, minimum)) or minimum)
        value = max(minimum, min(maximum, value))
        slider.setValue(int(round(value * slider_scale)))
        spin.setValue(value)
        slider.setToolTip(tooltip)
        spin.setToolTip(tooltip)
        slider.valueChanged.connect(lambda raw, target=spin: target.setValue(float(raw) / slider_scale))
        spin.valueChanged.connect(lambda value, target=slider: target.setValue(int(round(float(value) * slider_scale))))
        spin.valueChanged.connect(lambda _value: _manual_profile_mark_changed())
        manual_profile_controls[key] = spin
        manual_profile_effect_widgets[key] = [label_widget, slider, spin]
        manual_profile_control_tooltips[key] = tooltip
        manual_profile_layout.addWidget(label_widget, row, 0)
        manual_profile_layout.addWidget(slider, row, 1)
        manual_profile_layout.addWidget(spin, row, 2)

    def _manual_check(row: int, key: str, text: str, tooltip: str) -> None:
        checkbox = QCheckBox(text)
        checkbox.setObjectName(f'MeshAlignmentManualMaterialProfile_{key}')
        checkbox.setToolTip(tooltip)
        checkbox.setChecked(bool(manual_profile_saved_values.get(key, manual_profile_default_values.get(key, False))))
        checkbox.toggled.connect(lambda _checked: _manual_profile_mark_changed())
        manual_profile_controls[key] = checkbox
        manual_profile_effect_widgets[key] = [checkbox]
        manual_profile_control_tooltips[key] = tooltip
        manual_profile_layout.addWidget(checkbox, row, 0, 1, 4)

    def _manual_rgb(row: int, key: str, label: str, tooltip: str) -> None:
        label_widget = QLabel(label)
        label_widget.setToolTip(tooltip)
        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)
        raw_rgb = manual_profile_saved_values.get(key, manual_profile_default_values.get(key, (216, 216, 216)))
        rgb = tuple(raw_rgb if isinstance(raw_rgb, Sequence) and (not isinstance(raw_rgb, (str, bytes))) else (216, 216, 216))
        spins: list[QSpinBox] = []
        for channel_index, channel_name in enumerate(('R', 'G', 'B')):
            try:
                channel_value = int(rgb[channel_index])
            except (TypeError, ValueError, IndexError):
                channel_value = 216
            channel_spin = _make_int_spin_helper(object_name=f'MeshAlignmentManualMaterialProfile_{key}_{channel_name}', minimum=0, maximum=255, value=channel_value, prefix=f'{channel_name} ', tooltip=tooltip)
            channel_spin.valueChanged.connect(lambda _value: _manual_profile_mark_changed())
            row_layout.addWidget(channel_spin)
            spins.append(channel_spin)
        manual_profile_controls[key] = tuple(spins)
        manual_profile_effect_widgets[key] = [label_widget, *spins]
        manual_profile_control_tooltips[key] = tooltip
        manual_profile_layout.addWidget(label_widget, row, 0)
        manual_profile_layout.addLayout(row_layout, row, 1, 1, 2)

    return SimpleNamespace(_manual_profile_mark_changed=_manual_profile_mark_changed, _manual_combo=_manual_combo, _manual_int=_manual_int, _manual_float=_manual_float, _manual_check=_manual_check, _manual_rgb=_manual_rgb)


def create_alignment_texture_orientation_callbacks(context: dict[str, object]) -> SimpleNamespace:
    state = _StaticReplacementDialogState(context)
    _queue_texture_uv_preview_refresh = context.get('_queue_texture_uv_preview_refresh')
    _record_texture_uv_global_transform_state_helper = context.get('_record_texture_uv_global_transform_state_helper')
    _texture_uv_global_transform_control_state_helper = context.get('_texture_uv_global_transform_control_state_helper')
    _try_apply_global_flip_v_fast_preview = context.get('_try_apply_global_flip_v_fast_preview')
    setup_texture_flip_u_checkbox = context.get('setup_texture_flip_u_checkbox')
    setup_texture_flip_v_checkbox = context.get('setup_texture_flip_v_checkbox')
    setup_texture_rotate_combo = context.get('setup_texture_rotate_combo')
    texture_uv_global_transform_state = context.get('texture_uv_global_transform_state')

    def _save_setup_texture_orientation() -> None:
        _record_texture_uv_global_transform_state_helper(texture_uv_global_transform_state, _texture_uv_global_transform_control_state_helper(rotate_degrees=int(setup_texture_rotate_combo.currentData() or 0), flip_u=bool(setup_texture_flip_u_checkbox.isChecked()), flip_v=bool(setup_texture_flip_v_checkbox.isChecked())))
        if _try_apply_global_flip_v_fast_preview():
            return
        _queue_texture_uv_preview_refresh()

    def _reset_setup_texture_orientation() -> None:
        setup_texture_rotate_combo.setCurrentIndex(max(0, setup_texture_rotate_combo.findData(0)))
        setup_texture_flip_u_checkbox.setChecked(False)
        setup_texture_flip_v_checkbox.setChecked(False)
        _save_setup_texture_orientation()

    return SimpleNamespace(_save_setup_texture_orientation=_save_setup_texture_orientation, _reset_setup_texture_orientation=_reset_setup_texture_orientation)


def create_alignment_transform_slider_callbacks(context: dict[str, object]) -> SimpleNamespace:
    state = _StaticReplacementDialogState(context)
    Optional = context.get('Optional')
    QDoubleSpinBox = context.get('QDoubleSpinBox')
    QSlider = context.get('QSlider')
    _make_spinbox_slider_helper = context.get('_make_spinbox_slider_helper')
    alignment_transform_sliders = context.get('alignment_transform_sliders')
    scale = context.get('scale')
    slider = context.get('slider')
    slider_maximum = context.get('slider_maximum')
    slider_minimum = context.get('slider_minimum')
    spin = context.get('spin')
    tooltip = context.get('tooltip')
    transform_layout_specs = context.get('transform_layout_specs')

    def _paired_transform_slider(spin: QDoubleSpinBox, *, scale: float, tooltip: str, slider_minimum: Optional[float]=None, slider_maximum: Optional[float]=None) -> QSlider:
        slider = _make_spinbox_slider_helper(spin, scale=scale, tooltip=tooltip, object_name=str(transform_layout_specs['slider_object_name']), minimum_width=int(transform_layout_specs['slider_minimum_width']), slider_minimum=slider_minimum, slider_maximum=slider_maximum)
        alignment_transform_sliders[spin] = slider
        return slider

    return SimpleNamespace(_paired_transform_slider=_paired_transform_slider)


def create_alignment_transform_row_callbacks(context: dict[str, object]) -> SimpleNamespace:
    state = _StaticReplacementDialogState(context)
    Optional = context.get('Optional')
    QDoubleSpinBox = context.get('QDoubleSpinBox')
    QHBoxLayout = context.get('QHBoxLayout')
    QLabel = context.get('QLabel')
    Qt = context.get('Qt')
    Sequence = context.get('Sequence')
    _alignment_transform_slider_sync_state_helper = context.get('_alignment_transform_slider_sync_state_helper')
    _spin_with_slider = context.get('_spin_with_slider')
    alignment_transform_control_text = context.get('alignment_transform_control_text')
    alignment_transform_sliders = context.get('alignment_transform_sliders')
    axis = context.get('axis')
    axis_label = context.get('axis_label')
    axis_labels = context.get('axis_labels')
    label_text = context.get('label_text')
    label_widget = context.get('label_widget')
    offset_x_spin = context.get('offset_x_spin')
    offset_y_spin = context.get('offset_y_spin')
    offset_z_spin = context.get('offset_z_spin')
    original_text = context.get('original_text')
    original_widget = context.get('original_widget')
    rotate_x_spin = context.get('rotate_x_spin')
    rotate_y_spin = context.get('rotate_y_spin')
    rotate_z_spin = context.get('rotate_z_spin')
    row_index = context.get('row_index')
    slider = context.get('slider')
    slider_maximum = context.get('slider_maximum')
    slider_minimum = context.get('slider_minimum')
    slider_scale = context.get('slider_scale')
    slider_spec = context.get('slider_spec')
    spin = context.get('spin')
    sync_state = context.get('sync_state')
    transform_layout = context.get('transform_layout')
    transform_slider_specs = context.get('transform_slider_specs')
    value_row = context.get('value_row')
    widget = context.get('widget')
    widgets = context.get('widgets')

    def _sync_alignment_transform_slider_from_spin(spin: QDoubleSpinBox) -> None:
        slider = alignment_transform_sliders.get(spin)
        if slider is None:
            return
        if spin in (offset_x_spin, offset_y_spin, offset_z_spin):
            slider_spec = transform_slider_specs['offset']
        elif spin in (rotate_x_spin, rotate_y_spin, rotate_z_spin):
            slider_spec = transform_slider_specs['rotation']
        else:
            slider_spec = transform_slider_specs['scale']
        sync_state = _alignment_transform_slider_sync_state_helper(value=spin.value(), slider_value=slider.value(), scale=slider_spec['slider_scale'])
        if not bool(sync_state['apply']):
            return
        slider.blockSignals(True)
        slider.setValue(int(sync_state['slider_value']))
        slider.blockSignals(False)

    def _add_transform_row(row_index: int, label_text: str, original_text: str, widgets: Sequence[QDoubleSpinBox], *, slider_scale: float, slider_minimum: Optional[float]=None, slider_maximum: Optional[float]=None) -> None:
        label_widget = QLabel(label_text)
        original_widget = QLabel(original_text)
        original_widget.setObjectName('HintLabel')
        original_widget.setTextInteractionFlags(Qt.TextSelectableByMouse)
        value_row = QHBoxLayout()
        value_row.setContentsMargins(0, 0, 0, 0)
        value_row.setSpacing(3)
        axis_labels = (alignment_transform_control_text['axis_x'], alignment_transform_control_text['axis_y'], alignment_transform_control_text['axis_z'])
        for axis_label, widget in zip(axis_labels, widgets):
            axis = QLabel(axis_label)
            axis.setObjectName('HintLabel')
            value_row.addWidget(axis)
            value_row.addWidget(_spin_with_slider(widget, slider_scale=slider_scale, slider_minimum=slider_minimum, slider_maximum=slider_maximum, tooltip=alignment_transform_control_text['axis_slider_tooltip_template'].format(label=label_text, axis=axis_label)), 1)
        transform_layout.addWidget(label_widget, row_index, 0)
        transform_layout.addWidget(original_widget, row_index, 1)
        transform_layout.addLayout(value_row, row_index, 2)

    return SimpleNamespace(_sync_alignment_transform_slider_from_spin=_sync_alignment_transform_slider_from_spin, _add_transform_row=_add_transform_row)


def create_alignment_modeless_dialog_callbacks(context: dict[str, object]) -> SimpleNamespace:
    state = _StaticReplacementDialogState(context)
    QDialog = context.get('QDialog')
    QTimer = context.get('QTimer')
    _alignment_builder_closed_empty_state_message_helper = context.get('_alignment_builder_closed_empty_state_message_helper')
    _alignment_cancel_handler_failed_status_helper = context.get('_alignment_cancel_handler_failed_status_helper')
    _alignment_dialog_accepted_helper = context.get('_alignment_dialog_accepted_helper')
    _alignment_dialog_finished_route_helper = context.get('_alignment_dialog_finished_route_helper')
    _alignment_dialog_mark_closing_helper = context.get('_alignment_dialog_mark_closing_helper')
    _finish_alignment_startup_progress = context.get('_finish_alignment_startup_progress')
    _safe_shutdown_alignment_d3d11_preview = context.get('_safe_shutdown_alignment_d3d11_preview')
    _safe_stop_alignment_timer = context.get('_safe_stop_alignment_timer')
    alignment_dialog_closing = context.get('alignment_dialog_closing')
    alignment_dialog_key = context.get('alignment_dialog_key')
    dialog = context.get('dialog')
    dialog_accepted_state = context.get('dialog_accepted_state')
    embedded_alignment_builder = context.get('embedded_alignment_builder')
    exc = context.get('exc')
    finished_route = context.get('finished_route')
    material_edit_refresh_timer = context.get('material_edit_refresh_timer')
    on_cancel = context.get('on_cancel')
    result = context.get('result')
    self = context.get('self')
    source_material_plan_refresh_timer = context.get('source_material_plan_refresh_timer')

    def _modeless_alignment_dialog_finished(result: int=0) -> None:
        _alignment_dialog_mark_closing_helper(alignment_dialog_closing)
        _safe_stop_alignment_timer(material_edit_refresh_timer)
        _safe_stop_alignment_timer(source_material_plan_refresh_timer)
        _safe_shutdown_alignment_d3d11_preview()
        _finish_alignment_startup_progress()
        self._unregister_modeless_alignment_dialog(alignment_dialog_key, dialog)
        finished_route = _alignment_dialog_finished_route_helper(result=int(result), accepted_code=int(QDialog.Accepted), accepted=_alignment_dialog_accepted_helper(dialog_accepted_state), has_cancel_handler=on_cancel is not None, embedded_builder=bool(embedded_alignment_builder), has_mesh_editor=hasattr(self, 'mesh_editor_tab'))
        if finished_route.should_call_cancel_handler and on_cancel is not None:
            try:
                on_cancel()
            except Exception as exc:
                self.set_status_message(_alignment_cancel_handler_failed_status_helper(exc), error=True)
        dialog.deleteLater()
        if finished_route.should_show_embedded_empty_state:
            QTimer.singleShot(0, lambda: self.mesh_editor_tab.show_empty_state(_alignment_builder_closed_empty_state_message_helper()))

    return SimpleNamespace(_modeless_alignment_dialog_finished=_modeless_alignment_dialog_finished)


def create_alignment_fit_dialog_callbacks(context: dict[str, object]) -> SimpleNamespace:
    state = _StaticReplacementDialogState(context)
    QApplication = context.get('QApplication')
    _alignment_dialog_fit_size_helper = context.get('_alignment_dialog_fit_size_helper')
    _alignment_dialog_frame_origin_helper = context.get('_alignment_dialog_frame_origin_helper')
    _apply_alignment_dialog_responsive_layout = context.get('_apply_alignment_dialog_responsive_layout')
    available = context.get('available')
    dialog = context.get('dialog')
    fit_size = context.get('fit_size')
    frame = context.get('frame')
    frame_origin = context.get('frame_origin')
    screen = context.get('screen')
    self = context.get('self')

    def _fit_alignment_dialog_to_screen() -> None:
        screen = dialog.screen() or self.screen() or QApplication.primaryScreen()
        if screen is None:
            dialog.resize(1500, 820)
            _apply_alignment_dialog_responsive_layout(force_sizes=True)
            return
        available = screen.availableGeometry()
        fit_size = _alignment_dialog_fit_size_helper(available_width=int(available.width()), available_height=int(available.height()))
        dialog.resize(fit_size.width, fit_size.height)
        frame = dialog.frameGeometry()
        frame.moveCenter(available.center())
        frame_origin = _alignment_dialog_frame_origin_helper(available_left=int(available.left()), available_top=int(available.top()), available_right=int(available.right()), available_bottom=int(available.bottom()), frame_left=int(frame.left()), frame_top=int(frame.top()), frame_width=int(frame.width()), frame_height=int(frame.height()))
        dialog.move(frame_origin.left, frame_origin.top)
        _apply_alignment_dialog_responsive_layout(force_sizes=True)

    return SimpleNamespace(_fit_alignment_dialog_to_screen=_fit_alignment_dialog_to_screen)
