from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_dotnet_presentation import (
    builder_part_highlight_state,
    effective_builder_comparison_mode,
    send_resident_presentation_state,
)
from cdmw.ui.archive_browser.static_replacement_preview_status_state import (
    preview_grid_visible,
)
from cdmw.ui.archive_browser.static_replacement_viewport_display_modes import (
    normalize_mesh_preview_display_mode,
)

def _preview_mode_step_001(_state):
    _state.ModelPreviewData = _state.context.get('ModelPreviewData')
    _state.NativePreviewPanel = _state.context.get('NativePreviewPanel')
    _state.QProcess = _state.context.get('QProcess')
    _state._alignment_d3d11_editor_ids_for_source_indices = _state.context.get('_alignment_d3d11_editor_ids_for_source_indices')
    _state._alignment_d3d11_invalidate_package_cache = _state.context.get('_alignment_d3d11_invalidate_package_cache')
    _state._alignment_d3d11_live_display_mode_performance_helper = _state.context.get('_alignment_d3d11_live_display_mode_performance_helper')
    _state._alignment_d3d11_mode_refresh_needed_helper = _state.context.get('_alignment_d3d11_mode_refresh_needed_helper')
    _state._alignment_d3d11_preview_active = _state.context.get('_alignment_d3d11_preview_active')
    _state._alignment_d3d11_preview_mode_static_refresh_needed_helper = _state.context.get('_alignment_d3d11_preview_mode_static_refresh_needed_helper')
    _state._alignment_d3d11_reset_request_state_helper = _state.context.get('_alignment_d3d11_reset_request_state_helper')
    _state._alignment_d3d11_stop_process = _state.context.get('_alignment_d3d11_stop_process')
    _state._alignment_d3d11_stop_worker = _state.context.get('_alignment_d3d11_stop_worker')
    _state._alignment_default_d3d11_editor_ids = _state.context.get('_alignment_default_d3d11_editor_ids')
    _state._alignment_dialog_widgets_live = _state.context.get('_alignment_dialog_widgets_live')
    _state._alignment_geometry_tab_active = _state.context.get('_alignment_geometry_tab_active')
    _state._alignment_preview_help_presentation_helper = _state.context.get('_alignment_preview_help_presentation_helper')
    _state._alignment_preview_mode_record_helper = _state.context.get('_alignment_preview_mode_record_helper')
    _state._alignment_preview_mode_route_helper = _state.context.get('_alignment_preview_mode_route_helper')
    _state._alignment_preview_renderer_route_helper = _state.context.get('_alignment_preview_renderer_route_helper')
    _state._disabled_source_part_indices = _state.context.get('_disabled_source_part_indices')
    _state._mark_alignment_d3d11_rebuild_reason = _state.context.get('_mark_alignment_d3d11_rebuild_reason')
    _state._mesh_edit_raw_preview_active = _state.context.get('_mesh_edit_raw_preview_active')
    _state._queue_selection_preview_refresh = _state.context.get('_queue_selection_preview_refresh')
    _state._queue_static_preview_refresh = _state.context.get('_queue_static_preview_refresh')
    _state._replay_alignment_d3d11_fast_transform = _state.context.get('_replay_alignment_d3d11_fast_transform')
    _state._restore_alignment_preview_mode_view_state = _state.context.get('_restore_alignment_preview_mode_view_state')
    _state._save_alignment_preview_mode_view_state = _state.context.get('_save_alignment_preview_mode_view_state')
    _state._selection_highlight_sets_state_helper = _state.context.get('_selection_highlight_sets_state_helper')
    _state._set_alignment_d3d11_loading = _state.context.get('_set_alignment_d3d11_loading')
    _state._set_preview_performance_status = _state.context.get('_set_preview_performance_status')
    _state.alignment_d3d11_available = _state.context.get('alignment_d3d11_available')
    _state.alignment_d3d11_preview_host = _state.context.get('alignment_d3d11_preview_host')
    _state.alignment_d3d11_preview_page = _state.context.get('alignment_d3d11_preview_page')
    _state.alignment_d3d11_state = _state.context.get('alignment_d3d11_state')
    _state.alignment_preview_control_text = _state.context.get('alignment_preview_control_text')
    _state.alignment_preview_mode_state = _state.context.get('alignment_preview_mode_state')
    _state.alignment_preview_settings_button = _state.context.get('alignment_preview_settings_button')
    _state.control_tabs = _state.context.get('control_tabs')

def _preview_mode_step_002(_state):

    def _geometry_tab_active() -> bool:
        if not callable(_state._alignment_geometry_tab_active):
            return False
        return bool(_state._alignment_geometry_tab_active())
    _state._geometry_tab_active = _geometry_tab_active

def _preview_mode_step_003(_state):

    def _d3d11_preview_active() -> bool:
        if not callable(_state._alignment_d3d11_preview_active):
            return False
        return bool(_state._alignment_d3d11_preview_active())
    _state._d3d11_preview_active = _d3d11_preview_active

def _preview_mode_step_004(_state):

    def _d3d11_editor_ids_for_source_indices(indices: object, **kwargs: object) -> tuple[object, ...]:
        if not callable(_state._alignment_d3d11_editor_ids_for_source_indices):
            return ()
        return tuple(_state._alignment_d3d11_editor_ids_for_source_indices(indices, **kwargs) or ())
    _state._d3d11_editor_ids_for_source_indices = _d3d11_editor_ids_for_source_indices

def _preview_mode_step_005(_state):

    def _disabled_source_indices() -> tuple[object, ...]:
        if not callable(_state._disabled_source_part_indices):
            return ()
        return tuple(_state._disabled_source_part_indices() or ())
    _state._disabled_source_indices = _disabled_source_indices

def _preview_mode_step_006(_state):

    def _default_d3d11_editor_ids() -> tuple[object, ...]:
        if not callable(_state._alignment_default_d3d11_editor_ids):
            return ()
        return tuple(_state._alignment_default_d3d11_editor_ids() or ())
    _state._default_d3d11_editor_ids = _default_d3d11_editor_ids

def _preview_mode_step_007(_state):
    _state.dialog = _state.context.get('dialog')
    _state.highlighted_original_indices = _state.context.get('highlighted_original_indices')
    _state.highlighted_source_indices = _state.context.get('highlighted_source_indices')
    _state.original_dialog_preview = _state.context.get('original_dialog_preview')
    _state.overlay_dialog_preview = _state.context.get('overlay_dialog_preview')
    _state.overlay_original_locked_checkbox = _state.context.get('overlay_original_locked_checkbox')
    _state.preview_grid_checkbox = _state.context.get('preview_grid_checkbox')
    _state.preview_gizmo_checkbox = _state.context.get('preview_gizmo_checkbox')
    _state.preview_part_pick_checkbox = _state.context.get('preview_part_pick_checkbox')
    _state.preview_help = _state.context.get('preview_help')
    _state.preview_mode_combo = _state.context.get('preview_mode_combo')
    _state.preview_mesh_view_combo = _state.context.get('preview_mesh_view_combo')
    _state.preview_renderer_combo = _state.context.get('preview_renderer_combo')
    _state.preview_stack = _state.context.get('preview_stack')
    _state.mesh_edit_enabled_checkbox = _state.context.get('mesh_edit_enabled_checkbox')
    if _state.mesh_edit_enabled_checkbox is None:
        _state.mesh_edit_enabled_checkbox = _state.SimpleNamespace(isChecked=lambda: False)
    _state.replacement_only_preview = _state.context.get('replacement_only_preview')
    _state.selected_original_highlight_indices = _state.context.get('selected_original_highlight_indices')
    _state.selected_source_highlight_indices = _state.context.get('selected_source_highlight_indices')
    _state.selected_target_original_highlight_indices = _state.context.get('selected_target_original_highlight_indices')
    _state.selected_target_source_highlight_indices = _state.context.get('selected_target_source_highlight_indices')
    _state.static_dialog_preview = _state.context.get('static_dialog_preview')
    _state.textures_tab = _state.context.get('textures_tab')
    _state.hovered_source_part = _state.context.get('hovered_source_part')
    if _state.hovered_source_part is None:
        _state.hovered_source_part = {}
    _state.part_pick_native_state = {'enabled': None}

def _preview_mode_step_008(_state):

    def _set_preview_renderer() -> None:
        if not _state._alignment_dialog_widgets_live():
            return
        renderer_route = _state._alignment_preview_renderer_route_helper(_state.preview_renderer_combo.currentData(), d3d11_available=_state.alignment_d3d11_available, d3d11_active=_state._d3d11_preview_active())
        if renderer_route.should_report_unavailable:
            _state._set_alignment_d3d11_loading(False, _state.alignment_preview_control_text['d3d11_unavailable_status'])
        d3d11_preview_help = _state._alignment_preview_help_presentation_helper(d3d11_active=True)
        _state.preview_stack.setCurrentWidget(_state.alignment_d3d11_preview_page)
        _state.preview_help.setText(d3d11_preview_help.text)
        _state.preview_help.setToolTip(d3d11_preview_help.tooltip)
        _state.alignment_preview_settings_button.setToolTip(d3d11_preview_help.settings_tooltip)
        if renderer_route.should_sync_highlights:
            _state._sync_highlight_sets()
        if renderer_route.should_queue_selection_preview_refresh:
            _state._queue_selection_preview_refresh()
        if renderer_route.should_report_unavailable:
            controller = getattr(_state.alignment_d3d11_preview_host, 'controller', None)
            retry_now = getattr(controller, 'retry_now', None)
            if callable(retry_now):
                retry_now()
    _state._set_preview_renderer = _set_preview_renderer

def _preview_mode_step_009(_state):

    def _sync_highlight_sets() -> None:
        d3d11_active = _state._d3d11_preview_active()
        resident_active = bool(getattr(_state.dialog, '_mesh_editor_embedded_dotnet_active', False))
        preview_active = bool(d3d11_active or resident_active)
        geometry_active = _state._geometry_tab_active() if preview_active else False
        texture_tab_active = _state.control_tabs.widget(_state.control_tabs.currentIndex()) is _state.textures_tab if preview_active else False
        part_pick_checked = bool(preview_active and _state.preview_part_pick_checkbox is not None and _state.preview_part_pick_checkbox.isChecked())
        try:
            hovered_source_index = int(_state.hovered_source_part.get('index', -1))
        except (TypeError, ValueError):
            hovered_source_index = -1
        if not part_pick_checked and hovered_source_index >= 0:
            _state.hovered_source_part['index'] = -1
            hovered_source_index = -1
        hovered_source_indices = (hovered_source_index,) if part_pick_checked and hovered_source_index >= 0 else ()
        selection_state = _state._selection_highlight_sets_state_helper(selected_source_highlights=tuple(_state.selected_source_highlight_indices), selected_target_source_highlights=tuple(_state.selected_target_source_highlight_indices), hovered_source_highlights=hovered_source_indices, selected_original_highlights=tuple(_state.selected_original_highlight_indices), selected_target_original_highlights=tuple(_state.selected_target_original_highlight_indices), d3d11_active=d3d11_active, geometry_active=geometry_active, texture_tab_active=texture_tab_active, mesh_edit_raw_active=bool(_state._mesh_edit_raw_preview_active()) if preview_active else False, preview_gizmo_checked=bool(_state.preview_gizmo_checkbox.isChecked()) if preview_active else False, mesh_edit_active=bool(_state.mesh_edit_enabled_checkbox.isChecked()) if preview_active else False, selected_source_overlay_ids=_state._d3d11_editor_ids_for_source_indices(tuple(_state.selected_source_highlight_indices), selection_overlay=True) if d3d11_active else (), selected_source_editor_ids=_state._d3d11_editor_ids_for_source_indices(tuple(_state.selected_source_highlight_indices)) if d3d11_active else (), selected_target_source_editor_ids=_state._d3d11_editor_ids_for_source_indices(tuple(_state.selected_target_source_highlight_indices)) if d3d11_active else (), hovered_source_editor_ids=_state._d3d11_editor_ids_for_source_indices(hovered_source_indices) if d3d11_active else (), disabled_source_editor_ids=_state._d3d11_editor_ids_for_source_indices(_state._disabled_source_indices()) if d3d11_active else (), default_d3d11_editor_ids=_state._default_d3d11_editor_ids() if d3d11_active else (), part_pick_checked=part_pick_checked)
        _state.highlighted_source_indices.clear()
        _state.highlighted_source_indices.update(tuple(selection_state['highlighted_source_indices']))
        _state.highlighted_original_indices.clear()
        _state.highlighted_original_indices.update(tuple(selection_state['highlighted_original_indices']))
        resident_state = builder_part_highlight_state(
            selection_active=bool(geometry_active or texture_tab_active or hovered_source_indices),
            highlighted_source_indices=tuple(selection_state['highlighted_source_indices']),
            highlighted_original_indices=tuple(selection_state['highlighted_original_indices']),
            hovered_source_index=hovered_source_index,
            hidden_source_indices=tuple(_state._disabled_source_indices()),
            grid_visible=preview_grid_visible(_state.preview_grid_checkbox),
            gizmo_visible=bool(_state.preview_gizmo_checkbox.isChecked()),
            part_pick_enabled=part_pick_checked,
            mesh_edit_active=bool(_state.mesh_edit_enabled_checkbox.isChecked()),
        )
        if send_resident_presentation_state(_state.dialog, resident_state):
            return
        if d3d11_active:
            if hasattr(_state.alignment_d3d11_preview_host, 'set_source_part_picking'):
                if _state.part_pick_native_state.get('enabled') != part_pick_checked:
                    _state.alignment_d3d11_preview_host.set_source_part_picking(part_pick_checked)
                    _state.part_pick_native_state['enabled'] = part_pick_checked
            _state.alignment_d3d11_preview_host.set_highlighted_alignment_submeshes(replacement_submesh_indices=tuple(selection_state['d3d11_highlighted_indices']), original_submesh_indices=tuple(selection_state['d3d11_original_highlighted_indices']))
            _state.alignment_d3d11_preview_host.set_hidden_source_submeshes(tuple(selection_state['d3d11_hidden_source_indices']))
            _state.alignment_d3d11_preview_host.set_alignment_state(enabled=bool(selection_state['d3d11_gizmo_enabled']), source_submesh_indices=tuple(selection_state['d3d11_selected_indices']), translation_sensitivity=0.85, rotation_degrees_per_pixel=0.18)
            try:
                if callable(_state._replay_alignment_d3d11_fast_transform):
                    _state._replay_alignment_d3d11_fast_transform()
            except NameError:
                pass
    _state._sync_highlight_sets = _sync_highlight_sets

def _preview_mode_step_010(_state):

    def _preview_mode_qt_widgets(mode: str) -> tuple[NativePreviewPanel, ...]:
        normalized_mode = str(mode or 'side_by_side')
        if normalized_mode == 'replacement_only':
            return (_state.replacement_only_preview,)
        if normalized_mode == 'overlay':
            return (_state.overlay_dialog_preview,)
        if normalized_mode == 'original_only':
            return (_state.original_dialog_preview,)
        return (_state.original_dialog_preview, _state.static_dialog_preview)
    _state._preview_mode_qt_widgets = _preview_mode_qt_widgets

def _preview_mode_step_011(_state):

    def _preview_mode_needs_static_refresh(mode: str) -> bool:
        if _state._d3d11_preview_active():
            mode_refresh_needed = _state._alignment_d3d11_mode_refresh_needed_helper(_state.alignment_d3d11_state, mode, queued_model_active=isinstance(_state.alignment_d3d11_state.get('queued_model'), _state.ModelPreviewData), pending_model_active=isinstance(_state.alignment_d3d11_state.get('pending_model'), _state.ModelPreviewData), mesh_edit_raw_preview_active=_state._mesh_edit_raw_preview_active())
            if mode_refresh_needed:
                return True
            process = _state.alignment_d3d11_state.get('process')
            renderer_active = isinstance(process, _state.QProcess) and process.state() != _state.QProcess.NotRunning
            queued = isinstance(_state.alignment_d3d11_state.get('queued_model'), _state.ModelPreviewData)
            pending = isinstance(_state.alignment_d3d11_state.get('pending_model'), _state.ModelPreviewData)
            return _state._alignment_d3d11_preview_mode_static_refresh_needed_helper(_state.alignment_d3d11_state, mode_refresh_needed=False, renderer_active=renderer_active, queued_model_active=queued, pending_model_active=pending)
        return any((getattr(widget, '_current_model', None) is None for widget in _state._preview_mode_qt_widgets(mode)))
    _state._preview_mode_needs_static_refresh = _preview_mode_needs_static_refresh

def _preview_mode_step_012(_state):

    def _set_preview_display_mode(_index: int = 0) -> None:
        del _index
        # Edit Mesh used to drop this silently while leaving the combo live, so
        # the control kept showing a mode the viewport was never put into. The
        # resident .NET viewport accepts display-mode updates during editing, so
        # the request is routed instead; the handler reports its own failures.
        mode = normalize_mesh_preview_display_mode(
            _state.preview_mesh_view_combo.currentData()
        )
        request_display = getattr(
            _state.dialog,
            "_mesh_editor_embedded_request_viewport_display",
            None,
        )
        if callable(request_display):
            request_display(mode)
            return
        if send_resident_presentation_state(
            _state.dialog,
            {"display": {"mode": mode}},
        ):
            return
        setter = getattr(
            _state.alignment_d3d11_preview_host,
            "set_viewport_display_mode",
            None,
        )
        if callable(setter):
            setter(mode)
    _state._set_preview_display_mode = _set_preview_display_mode

    def _set_preview_mode() -> None:
        mode = str(_state.preview_mode_combo.currentData() or 'side_by_side')
        previous_mode, mode = _state._alignment_preview_mode_record_helper(_state.alignment_preview_mode_state, mode)
        if previous_mode != mode:
            _state._save_alignment_preview_mode_view_state(previous_mode)
        resident_mode = effective_builder_comparison_mode(
            mode,
            bool(_state.mesh_edit_enabled_checkbox.isChecked()),
        )
        set_scene_state = getattr(_state.dialog, '_mesh_editor_embedded_set_scene_state', None)
        active_view = {
            'original_only': 'reference',
            'overlay': 'comparison',
            'side_by_side': 'comparison',
        }.get(resident_mode, 'editable')
        presentation_sent = send_resident_presentation_state(
            _state.dialog,
            {'active_view': active_view, 'comparison_mode': resident_mode},
        )
        if callable(set_scene_state) and bool(set_scene_state(comparison_mode=resident_mode)):
            return
        if presentation_sent:
            return
        needs_static_refresh = _state._preview_mode_needs_static_refresh(mode)
        mode_route = _state._alignment_preview_mode_route_helper(mode, d3d11_active=True, needs_static_refresh=needs_static_refresh)
        if mode_route.d3d11_active:
            if mode_route.should_set_live_d3d11_mode:
                _state.alignment_d3d11_preview_host.set_display_mode(mode_route.mode)
                live_mode_presentation = _state._alignment_d3d11_live_display_mode_performance_helper(mode)
                _state._set_preview_performance_status(live_mode_presentation.summary, details=live_mode_presentation.details)
            if mode_route.should_mark_d3d11_rebuild:
                _state._mark_alignment_d3d11_rebuild_reason('mode_missing_original')
            _state.preview_stack.setCurrentWidget(_state.alignment_d3d11_preview_page)
            if mode_route.should_restore_view_state:
                _state._restore_alignment_preview_mode_view_state(mode_route.mode)
            if mode_route.should_replay_fast_transform:
                if callable(_state._replay_alignment_d3d11_fast_transform):
                    _state._replay_alignment_d3d11_fast_transform()
        _state.overlay_original_locked_checkbox.blockSignals(True)
        _state.overlay_original_locked_checkbox.setChecked(True)
        _state.overlay_original_locked_checkbox.blockSignals(False)
        _state.overlay_original_locked_checkbox.setEnabled(False)
        if mode_route.should_queue_static_preview_refresh:
            _state._queue_static_preview_refresh()
    _state._set_preview_mode = _set_preview_mode

    def _refresh_preview_mode_controls_enabled() -> None:
        """Keep the Preview Mode combo honest about Edit Mesh's single pane.

        ``effective_builder_comparison_mode`` collapses every comparison layout
        to ``replacement_only`` while editing, so leaving the combo live let the
        user pick Side by side or Original only and get neither.
        """
        combo = _state.preview_mode_combo
        if combo is None or not callable(getattr(combo, 'setEnabled', None)):
            return
        try:
            mesh_edit_active = bool(_state.mesh_edit_enabled_checkbox.isChecked())
        except (AttributeError, RuntimeError, TypeError):
            mesh_edit_active = False
        try:
            combo.setEnabled(not mesh_edit_active)
            combo.setToolTip(
                'Edit Mesh renders the replacement on its own; comparison layouts '
                'return when Edit Mesh is off.'
                if mesh_edit_active
                else _state.alignment_preview_control_text['preview_mode_tooltip']
            )
        except RuntimeError:
            return
    _state._refresh_preview_mode_controls_enabled = _refresh_preview_mode_controls_enabled
    if _state.dialog is not None:
        setattr(
            _state.dialog,
            '_mesh_editor_refresh_preview_mode_controls',
            _refresh_preview_mode_controls_enabled,
        )
    _refresh_preview_mode_controls_enabled()

def _preview_mode_step_013(_state):
    _state._factory_result_values.update({'_set_preview_renderer': _state._set_preview_renderer, '_sync_highlight_sets': _state._sync_highlight_sets, '_preview_mode_qt_widgets': _state._preview_mode_qt_widgets, '_preview_mode_needs_static_refresh': _state._preview_mode_needs_static_refresh, '_set_preview_display_mode': _state._set_preview_display_mode, '_set_preview_mode': _state._set_preview_mode, '_refresh_preview_mode_controls_enabled': _state._refresh_preview_mode_controls_enabled})

STEPS = (
    _preview_mode_step_001,
    _preview_mode_step_002,
    _preview_mode_step_003,
    _preview_mode_step_004,
    _preview_mode_step_005,
    _preview_mode_step_006,
    _preview_mode_step_007,
    _preview_mode_step_008,
    _preview_mode_step_009,
    _preview_mode_step_010,
    _preview_mode_step_011,
    _preview_mode_step_012,
    _preview_mode_step_013,
)
