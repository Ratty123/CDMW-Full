from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_dotnet_presentation import (
    send_resident_presentation_state,
)

def _remaining_preview_render_settings_step_001(_state):
    _state.state = _state._StaticReplacementDialogState(_state.context)
    _state.ARCHIVE_MODEL_RENDERER_D3D11 = _state.context.get('ARCHIVE_MODEL_RENDERER_D3D11')
    _state.ModelPreviewRenderSettings = _state.context.get('ModelPreviewRenderSettings')
    _state.Optional = _state.context.get('Optional')
    _state._alignment_d3d11_invalidate_package_cache = _state.context.get('_alignment_d3d11_invalidate_package_cache')
    _state._alignment_d3d11_package_settings_changed_helper = _state.context.get('_alignment_d3d11_package_settings_changed_helper')
    _state._alignment_d3d11_preview_active = _state.context.get('_alignment_d3d11_preview_active')
    _state._alignment_d3d11_render_settings_rebuild_performance_helper = _state.context.get('_alignment_d3d11_render_settings_rebuild_performance_helper')
    _state._alignment_d3d11_render_settings_route_helper = _state.context.get('_alignment_d3d11_render_settings_route_helper')
    _state._alignment_d3d11_render_tuning_live_performance_helper = _state.context.get('_alignment_d3d11_render_tuning_live_performance_helper')
    _state._alignment_lit_render_settings = _state.context.get('_alignment_lit_render_settings_helper') or _state.context.get('_alignment_lit_render_settings')
    _state._alignment_renderer_backend_for_dialog = _state.context.get('_alignment_renderer_backend_for_dialog')
    _state._mark_alignment_d3d11_rebuild_reason = _state.context.get('_mark_alignment_d3d11_rebuild_reason')
    _state._queue_static_preview_refresh = _state.context.get('_queue_static_preview_refresh')
    _state._load_original_reference_texture_preview = _state.context.get('_load_original_reference_texture_preview')
    _state._stop_original_reference_texture_worker = _state.context.get('_stop_original_reference_texture_worker')
    _state._rough_control_value_from_settings = _state.context.get('_rough_control_value_from_settings')
    _state._set_alignment_renderer_from_dialog = _state.context.get('_set_alignment_renderer_from_dialog')
    _state._set_preview_performance_status = _state.context.get('_set_preview_performance_status')
    _state._set_preview_renderer = _state.context.get('_set_preview_renderer')
    _state._sync_from_modal_settings = _state.context.get('_sync_from_modal_settings')
    _state.alignment_d3d11_preview_host = _state.context.get('alignment_d3d11_preview_host')
    _state.alignment_d3d11_view_mode_combo = _state.context.get('alignment_d3d11_view_mode_combo')
    _state.backend = _state.context.get('backend')
    _state.base = _state.context.get('base')
    _state.base_settings = _state.context.get('base_settings')
    _state.checkbox = _state.context.get('checkbox')
    _state.clamp_model_preview_render_settings = _state.context.get('clamp_model_preview_render_settings')
    _state.combo = _state.context.get('combo')
    _state.combo_index = _state.context.get('combo_index')
    _state.current_settings = _state.context.get('current_settings')
    _state.data_value = _state.context.get('data_value')
    _state.dataclasses = _state.context.get('dataclasses')
    _state.dialog = _state.context.get('dialog')
    _state.index = _state.context.get('index')
    _state.normalize_archive_model_renderer_backend = _state.context.get('normalize_archive_model_renderer_backend')
    _state.old_settings = _state.context.get('old_settings')
    _state.original_dialog_preview = _state.context.get('original_dialog_preview')
    _state.original_reference_texture_preview_state = _state.context.get('original_reference_texture_preview_state')
    _state.overlay_dialog_preview = _state.context.get('overlay_dialog_preview')
    _state.preview_depth_spin = _state.context.get('preview_depth_spin')
    _state.preview_disable_brightness_checkbox = _state.context.get('preview_disable_brightness_checkbox')
    _state.preview_disable_tint_checkbox = _state.context.get('preview_disable_tint_checkbox')
    _state.preview_disable_uv_scale_checkbox = _state.context.get('preview_disable_uv_scale_checkbox')
    _state.preview_render_mode_combo = _state.context.get('preview_render_mode_combo')
    _state.preview_renderer_combo = _state.context.get('preview_renderer_combo')
    _state.preview_rough_spin = _state.context.get('preview_rough_spin')
    _state.preview_shine_spin = _state.context.get('preview_shine_spin')
    _state.preview_support_maps_checkbox = _state.context.get('preview_support_maps_checkbox')
    _state.preview_visible_mode_combo = _state.context.get('preview_visible_mode_combo')
    _state.preview_widget = _state.context.get('preview_widget')
    _state.previous_settings = _state.context.get('previous_settings')
    _state.rebuild_presentation = _state.context.get('rebuild_presentation')
    _state.render_settings_route = _state.context.get('render_settings_route')
    _state.render_tuning_presentation = _state.context.get('render_tuning_presentation')
    _state.replacement_only_preview = _state.context.get('replacement_only_preview')
    _state.self = _state.context.get('self')
    _state.settings = _state.context.get('settings')
    _state.spin = _state.context.get('spin')
    _state.static_dialog_preview = _state.context.get('static_dialog_preview')
    _state.value = _state.context.get('value')

def _remaining_preview_render_settings_step_002(_state):

    def _alignment_preview_render_settings_from_controls(base_settings: Optional[ModelPreviewRenderSettings]=None) -> ModelPreviewRenderSettings:
        base = base_settings if isinstance(base_settings, _state.ModelPreviewRenderSettings) else _state.state.preview_render_settings
        settings = _state.dataclasses.replace(_state.clamp_model_preview_render_settings(base))
        settings.visible_texture_mode = str(_state.preview_visible_mode_combo.currentData() or settings.visible_texture_mode)
        settings.render_diagnostic_mode = str(_state.preview_render_mode_combo.currentData() or settings.render_diagnostic_mode)
        settings.d3d11_view_mode = str(_state.alignment_d3d11_view_mode_combo.currentData() or settings.d3d11_view_mode)
        settings.disable_tint = bool(_state.preview_disable_tint_checkbox.isChecked())
        settings.disable_brightness = bool(_state.preview_disable_brightness_checkbox.isChecked())
        settings.disable_uv_scale = bool(_state.preview_disable_uv_scale_checkbox.isChecked())
        settings.disable_all_support_maps = not bool(_state.preview_support_maps_checkbox.isChecked())
        settings.height_effect_max = float(_state.preview_depth_spin.value())
        settings.specular_max = float(_state.preview_shine_spin.value())
        settings.shininess_max = 32.0 + float(_state.preview_rough_spin.value()) * 224.0
        return _state.clamp_model_preview_render_settings(settings)
    _state._alignment_preview_render_settings_from_controls = _alignment_preview_render_settings_from_controls

def _remaining_preview_render_settings_step_003(_state):

    def _current_alignment_preview_render_settings() -> ModelPreviewRenderSettings:
        return _state._alignment_preview_render_settings_from_controls(_state.state.preview_render_settings)
    _state._current_alignment_preview_render_settings = _current_alignment_preview_render_settings

def _remaining_preview_render_settings_step_004(_state):

    def _lit_alignment_settings(settings: object) -> ModelPreviewRenderSettings:
        fallback_settings = _state.state.preview_render_settings
        if not isinstance(fallback_settings, _state.ModelPreviewRenderSettings):
            fallback_settings = _state.self._current_model_preview_render_settings()
        if callable(_state._alignment_lit_render_settings):
            return _state._alignment_lit_render_settings(settings, fallback_settings)
        return _state.clamp_model_preview_render_settings(settings if isinstance(settings, _state.ModelPreviewRenderSettings) else fallback_settings)
    _state._lit_alignment_settings = _lit_alignment_settings

def _remaining_preview_render_settings_step_005(_state):

    def _alignment_preview_package_settings_changed(previous_settings: ModelPreviewRenderSettings, current_settings: ModelPreviewRenderSettings) -> bool:
        return _state._alignment_d3d11_package_settings_changed_helper(previous_settings, current_settings)
    _state._alignment_preview_package_settings_changed = _alignment_preview_package_settings_changed

def _remaining_preview_render_settings_step_006(_state):

    def _apply_alignment_preview_render_settings(*_args, previous_settings: Optional[ModelPreviewRenderSettings]=None) -> None:
        old_settings = _state.clamp_model_preview_render_settings(previous_settings if isinstance(previous_settings, _state.ModelPreviewRenderSettings) else _state.state.preview_render_settings)
        _state.state.preview_render_settings = _state._current_alignment_preview_render_settings()
        visible_texture_mode_changed = (
            old_settings.visible_texture_mode
            != _state.state.preview_render_settings.visible_texture_mode
        )
        resident_getter = getattr(_state.dialog, '_mesh_editor_embedded_presentation_state', None)
        presentation_sent = False
        if callable(resident_getter):
            try:
                resident_state = resident_getter()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                resident_state = None
            if isinstance(resident_state, dict):
                presentation_sent = send_resident_presentation_state(_state.dialog, resident_state)
        if visible_texture_mode_changed and isinstance(
            _state.original_reference_texture_preview_state,
            dict,
        ):
            if callable(_state._stop_original_reference_texture_worker):
                _state._stop_original_reference_texture_worker()
            _state.original_reference_texture_preview_state.update(
                {
                    'loaded': False,
                    'loading': False,
                    'failed': False,
                    'error': '',
                    'native_package_path': '',
                }
            )
            if callable(_state._load_original_reference_texture_preview):
                _state._load_original_reference_texture_preview()
        if presentation_sent:
            return
        render_settings_route = _state._alignment_d3d11_render_settings_route_helper(d3d11_active=_state._alignment_d3d11_preview_active(), package_settings_changed=_state._alignment_preview_package_settings_changed(old_settings, _state.state.preview_render_settings))
        if _state._alignment_d3d11_preview_active():
            if render_settings_route.action == 'd3d11_rebuild':
                if render_settings_route.should_invalidate_package_cache:
                    _state._alignment_d3d11_invalidate_package_cache('material')
                if render_settings_route.should_mark_rebuild_reason:
                    _state._mark_alignment_d3d11_rebuild_reason('material')
                if render_settings_route.should_queue_static_preview_refresh:
                    _state._queue_static_preview_refresh()
                rebuild_presentation = _state._alignment_d3d11_render_settings_rebuild_performance_helper()
                _state._set_preview_performance_status(rebuild_presentation.summary, details=rebuild_presentation.details)
                return
            if render_settings_route.should_apply_live_render_tuning:
                _state.alignment_d3d11_preview_host.set_render_tuning(_state.state.preview_render_settings)
            render_tuning_presentation = _state._alignment_d3d11_render_tuning_live_performance_helper()
            _state._set_preview_performance_status(render_tuning_presentation.summary, details=render_tuning_presentation.details)
            return
        if render_settings_route.should_apply_static_widget_settings:
            for preview_widget in (_state.original_dialog_preview, _state.static_dialog_preview, _state.overlay_dialog_preview, _state.replacement_only_preview):
                preview_widget.set_render_settings(_state.state.preview_render_settings)
                preview_widget.set_use_textures(bool(_state.state.preview_render_settings.use_textures_by_default))
                preview_widget.set_high_quality_textures(bool(_state.state.preview_render_settings.high_quality_by_default))
        if render_settings_route.should_queue_static_preview_refresh:
            _state._queue_static_preview_refresh()
    _state._apply_alignment_preview_render_settings = _apply_alignment_preview_render_settings

def _remaining_preview_render_settings_step_007(_state):

    def _sync_alignment_preview_controls_from_settings(settings: ModelPreviewRenderSettings) -> None:
        for combo, value in ((_state.preview_visible_mode_combo, settings.visible_texture_mode), (_state.preview_render_mode_combo, settings.render_diagnostic_mode), (_state.alignment_d3d11_view_mode_combo, settings.d3d11_view_mode)):
            combo.blockSignals(True)
            combo_index = combo.findData(value)
            combo.setCurrentIndex(max(0, combo_index))
            combo.blockSignals(False)
        for checkbox, value in ((_state.preview_disable_tint_checkbox, settings.disable_tint), (_state.preview_disable_brightness_checkbox, settings.disable_brightness), (_state.preview_disable_uv_scale_checkbox, settings.disable_uv_scale), (_state.preview_support_maps_checkbox, not settings.disable_all_support_maps)):
            checkbox.blockSignals(True)
            checkbox.setChecked(bool(value))
            checkbox.blockSignals(False)
        for spin, value in ((_state.preview_depth_spin, settings.height_effect_max), (_state.preview_shine_spin, settings.specular_max)):
            spin.blockSignals(True)
            spin.setValue(float(value))
            spin.blockSignals(False)
        _state.preview_rough_spin.blockSignals(True)
        _state.preview_rough_spin.setValue(_state._rough_control_value_from_settings(settings))
        _state.preview_rough_spin.blockSignals(False)
    _state._sync_alignment_preview_controls_from_settings = _sync_alignment_preview_controls_from_settings

def _remaining_preview_render_settings_step_008(_state):

    def _use_global_alignment_preview_settings() -> None:
        previous_settings = _state._current_alignment_preview_render_settings()
        _state.state.preview_render_settings = _state._lit_alignment_settings(_state.self._current_model_preview_render_settings())
        _state._sync_alignment_preview_controls_from_settings(_state.state.preview_render_settings)
        _state._apply_alignment_preview_render_settings(previous_settings=previous_settings)
    _state._use_global_alignment_preview_settings = _use_global_alignment_preview_settings

def _remaining_preview_render_settings_step_009(_state):

    def _open_alignment_preview_settings_dialog() -> None:

        def _alignment_renderer_backend_for_dialog() -> str:
            return _state.ARCHIVE_MODEL_RENDERER_D3D11

        def _set_alignment_renderer_from_dialog(backend: str) -> None:
            normalized = _state.normalize_archive_model_renderer_backend(backend)
            data_value = 'd3d11'
            index = _state.preview_renderer_combo.findData(data_value)
            if index >= 0 and index != _state.preview_renderer_combo.currentIndex():
                _state.preview_renderer_combo.setCurrentIndex(index)
            else:
                _state._set_preview_renderer()

        def _sync_from_modal_settings(settings: Optional[object]=None) -> None:
            previous_settings = _state._current_alignment_preview_render_settings()
            _state.state.preview_render_settings = _state._lit_alignment_settings(settings if isinstance(settings, _state.ModelPreviewRenderSettings) else _state.self._current_model_preview_render_settings())
            _state._sync_alignment_preview_controls_from_settings(_state.state.preview_render_settings)
            _state._apply_alignment_preview_render_settings(previous_settings=previous_settings)
        preview_target = (
            'dotnet_vortice'
            if bool(getattr(_state.dialog, '_mesh_editor_embedded_dotnet_active', False))
            else 'archive_dotnet_vortice'
        )
        _state.self._open_modal_model_preview_settings_dialog(
            _state.dialog,
            archive_renderer_backend_enabled=True,
            archive_renderer_backend=_alignment_renderer_backend_for_dialog(),
            archive_renderer_backend_changed_handler=_set_alignment_renderer_from_dialog,
            settings_changed_handler=_sync_from_modal_settings,
            preview_settings=_state._current_alignment_preview_render_settings(),
            preview_target=preview_target,
        )
    _state._open_alignment_preview_settings_dialog = _open_alignment_preview_settings_dialog

def _remaining_preview_render_settings_step_010(_state):
    _state._factory_result_values.update({'_alignment_preview_render_settings_from_controls': _state._alignment_preview_render_settings_from_controls, '_current_alignment_preview_render_settings': _state._current_alignment_preview_render_settings, '_alignment_preview_package_settings_changed': _state._alignment_preview_package_settings_changed, '_apply_alignment_preview_render_settings': _state._apply_alignment_preview_render_settings, '_sync_alignment_preview_controls_from_settings': _state._sync_alignment_preview_controls_from_settings, '_use_global_alignment_preview_settings': _state._use_global_alignment_preview_settings, '_open_alignment_preview_settings_dialog': _state._open_alignment_preview_settings_dialog})

STEPS = (
    _remaining_preview_render_settings_step_001,
    _remaining_preview_render_settings_step_002,
    _remaining_preview_render_settings_step_003,
    _remaining_preview_render_settings_step_004,
    _remaining_preview_render_settings_step_005,
    _remaining_preview_render_settings_step_006,
    _remaining_preview_render_settings_step_007,
    _remaining_preview_render_settings_step_008,
    _remaining_preview_render_settings_step_009,
    _remaining_preview_render_settings_step_010,
)
