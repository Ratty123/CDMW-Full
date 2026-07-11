from __future__ import annotations

def _routing_dialog_layout_step_001(_state):
    _state.Callable = _state.context.get('Callable')
    _state.QSizePolicy = _state.context.get('QSizePolicy')
    _state.QTimer = _state.context.get('QTimer')
    _state.Qt = _state.context.get('Qt')
    _state._alignment_dialog_responsive_layout_helper = _state.context.get('_alignment_dialog_responsive_layout_helper')
    _state._alignment_dialog_widgets_live = _state.context.get('_alignment_dialog_widgets_live')
    _state._preview_performance_status_helper = _state.context.get('_preview_performance_status_helper')
    _state._qt_object_is_valid = _state.context.get('_qt_object_is_valid')
    _state._queue_selection_preview_refresh = _state.context.get('_queue_selection_preview_refresh')
    _state._queue_static_preview_rebuild = _state.context.get('_queue_static_preview_rebuild')
    _state._queue_texture_preview_refresh = _state.context.get('_queue_texture_preview_refresh')
    _state._queue_texture_uv_preview_refresh = _state.context.get('_queue_texture_uv_preview_refresh')
    _state._refresh_mesh_editor_diagnostics = _state.context.get('_refresh_mesh_editor_diagnostics')
    _state._static_preview_batch_begin_helper = _state.context.get('_static_preview_batch_begin_helper')
    _state._static_preview_batch_end_helper = _state.context.get('_static_preview_batch_end_helper')
    _state.alignment_control_content_min_width = _state.context.get('alignment_control_content_min_width')
    _state.alignment_control_min_width = _state.context.get('alignment_control_min_width')
    _state.alignment_dialog_layout_state = _state.context.get('alignment_dialog_layout_state')
    _state.alignment_preview_min_width = _state.context.get('alignment_preview_min_width')
    _state.batch_requests = _state.context.get('batch_requests')
    _state.callback = _state.context.get('callback')
    _state.content_container = _state.context.get('content_container')
    _state.control_tabs = _state.context.get('control_tabs')
    _state.controls_panel = _state.context.get('controls_panel')
    _state.details = _state.context.get('details')
    _state.dialog = _state.context.get('dialog')
    _state.embedded_alignment_builder = _state.context.get('embedded_alignment_builder')
    _state.event = _state.context.get('event')
    _state.force_sizes = _state.context.get('force_sizes')
    _state.height = _state.context.get('height')
    _state.layout_spec = _state.context.get('layout_spec')
    _state.main_orientation = _state.context.get('main_orientation')
    _state.main_splitter = _state.context.get('main_splitter')
    _state.mesh_edit_control_content_min_width = _state.context.get('mesh_edit_control_content_min_width')
    _state.mesh_edit_control_max_width = _state.context.get('mesh_edit_control_max_width')
    _state.mesh_edit_control_min_width = _state.context.get('mesh_edit_control_min_width')
    _state.mesh_edit_enabled_checkbox = _state.context.get('mesh_edit_enabled_checkbox')
    _state.mesh_edit_tab = _state.context.get('mesh_edit_tab')
    _state.mesh_edit_tools_active = _state.context.get('mesh_edit_tools_active')
    _state.policy_by_name = _state.context.get('policy_by_name')
    _state.presentation = _state.context.get('presentation')
    _state.preview_orientation = _state.context.get('preview_orientation')
    _state.preview_panel = _state.context.get('preview_panel')
    _state.preview_performance_label = _state.context.get('preview_performance_label')
    _state.preview_splitter = _state.context.get('preview_splitter')
    _state.previous_dialog_resize_event = _state.context.get('previous_dialog_resize_event')
    _state.self = _state.context.get('self')
    _state.static_preview_batch_state = _state.context.get('static_preview_batch_state')
    _state.summary = _state.context.get('summary')
    _state.wants_rebuild = _state.context.get('wants_rebuild')
    _state.wants_refresh = _state.context.get('wants_refresh')
    _state.wants_texture = _state.context.get('wants_texture')
    _state.wants_texture_uv = _state.context.get('wants_texture_uv')
    _state.width = _state.context.get('width')

def _routing_dialog_layout_step_002(_state):

    def _set_preview_performance_status(summary: str, *, details: str='') -> None:
        presentation = _state._preview_performance_status_helper(summary, details=details)
        _state.preview_performance_label.setText(presentation.text)
        _state.preview_performance_label.setToolTip(presentation.tooltip)
        try:
            _state._refresh_mesh_editor_diagnostics(auto=True)
        except NameError:
            pass
    _state._set_preview_performance_status = _set_preview_performance_status

def _routing_dialog_layout_step_003(_state):

    def _layout_settings_key(kind: str, mode: str) -> str:
        scope = 'embedded' if bool(_state.embedded_alignment_builder) else 'dialog'
        return f'ui/mesh_alignment/{scope}/{mode}/{kind}_splitter_sizes'
    _state._layout_settings_key = _layout_settings_key

def _routing_dialog_layout_step_004(_state):

    def _saved_splitter_sizes(kind: str, mode: str, count: int) -> tuple[int, ...] | None:
        settings = getattr(_state.self, 'settings', None)
        if settings is None:
            return None
        try:
            raw = settings.value(_state._layout_settings_key(kind, mode), '')
        except Exception:
            return None
        values = raw if isinstance(raw, (list, tuple)) else str(raw or '').replace(';', ',').split(',')
        try:
            sizes = tuple((max(0, int(value)) for value in tuple(values)[:count]))
        except (TypeError, ValueError):
            return None
        if len(sizes) != count or sum(sizes) <= 0:
            return None
        return sizes
    _state._saved_splitter_sizes = _saved_splitter_sizes

def _routing_dialog_layout_step_005(_state):

    def _save_splitter_sizes(kind: str, mode: str, sizes: object) -> None:
        settings = getattr(_state.self, 'settings', None)
        if settings is None or not mode:
            return
        try:
            values = tuple((max(0, int(value)) for value in tuple(sizes or ())))
        except (TypeError, ValueError):
            return
        if len(values) != 2 or sum(values) <= 0:
            return
        settings.setValue(_state._layout_settings_key(kind, mode), ','.join((str(value) for value in values)))
    _state._save_splitter_sizes = _save_splitter_sizes

def _routing_dialog_layout_step_006(_state):

    def _save_alignment_dialog_splitter_sizes(*_args: object) -> None:
        mode = str(_state.alignment_dialog_layout_state.get('mode') or '')
        if not mode:
            return
        _state._save_splitter_sizes('main', mode, _state.main_splitter.sizes())
        _state._save_splitter_sizes('preview', mode, _state.preview_splitter.sizes())
    _state._save_alignment_dialog_splitter_sizes = _save_alignment_dialog_splitter_sizes

def _routing_dialog_layout_step_007(_state):

    def _apply_alignment_dialog_responsive_layout(*, force_sizes: bool=False) -> None:
        if not _state._alignment_dialog_widgets_live() or not _state._qt_object_is_valid(_state.main_splitter):
            return
        width = max(1, int(_state.dialog.width()))
        height = max(1, int(_state.dialog.height()))
        is_mesh_edit_checked = getattr(_state.mesh_edit_enabled_checkbox, 'isChecked', None)
        mesh_edit_tools_active = bool(is_mesh_edit_checked()) if callable(is_mesh_edit_checked) else False
        layout_spec = _state._alignment_dialog_responsive_layout_helper(_state.alignment_dialog_layout_state, width=width, height=height, embedded=bool(_state.embedded_alignment_builder), force_sizes=force_sizes, mesh_edit_tools_active=mesh_edit_tools_active, alignment_control_min_width=_state.alignment_control_min_width, alignment_control_content_min_width=_state.alignment_control_content_min_width, alignment_preview_min_width=_state.alignment_preview_min_width, mesh_edit_control_min_width=_state.mesh_edit_control_min_width, mesh_edit_control_content_min_width=_state.mesh_edit_control_content_min_width, mesh_edit_control_max_width=_state.mesh_edit_control_max_width)
        main_orientation = _state.Qt.Horizontal if layout_spec.main_orientation == 'horizontal' else _state.Qt.Vertical
        preview_orientation = _state.Qt.Horizontal if layout_spec.preview_orientation == 'horizontal' else _state.Qt.Vertical
        if _state.main_splitter.orientation() != main_orientation:
            _state.main_splitter.setOrientation(main_orientation)
        if _state.preview_splitter.orientation() != preview_orientation:
            _state.preview_splitter.setOrientation(preview_orientation)
        policy_by_name = {'fixed': _state.QSizePolicy.Fixed, 'minimum_expanding': _state.QSizePolicy.MinimumExpanding, 'preferred': _state.QSizePolicy.Preferred}
        _state.controls_panel.setVisible(True)
        _state.main_splitter.setHandleWidth(layout_spec.main_handle_width)
        _state.main_splitter.setCollapsible(0, False)
        _state.main_splitter.setCollapsible(1, False)
        _state.main_splitter.setStretchFactor(0, layout_spec.main_stretch[0])
        _state.main_splitter.setStretchFactor(1, layout_spec.main_stretch[1])
        _state.controls_panel.setSizePolicy(policy_by_name[layout_spec.controls_policy], _state.QSizePolicy.Expanding)
        _state.content_container.setSizePolicy(policy_by_name[layout_spec.content_policy], _state.QSizePolicy.Expanding)
        _state.controls_panel.setMinimumWidth(layout_spec.controls_min_width)
        _state.content_container.setMinimumWidth(layout_spec.content_min_width)
        _state.controls_panel.setMaximumWidth(layout_spec.controls_max_width)
        _state.content_container.setMaximumWidth(layout_spec.content_max_width)
        _state.preview_panel.setMinimumWidth(layout_spec.preview_min_width)
        if layout_spec.main_sizes is not None:
            _state.main_splitter.setSizes(list(_state._saved_splitter_sizes('main', layout_spec.mode, 2) or layout_spec.main_sizes))
        if layout_spec.preview_sizes is not None:
            _state.preview_splitter.setSizes(list(_state._saved_splitter_sizes('preview', layout_spec.mode, 2) or layout_spec.preview_sizes))
    _state._apply_alignment_dialog_responsive_layout = _apply_alignment_dialog_responsive_layout

def _routing_dialog_layout_step_008(_state):

    def _responsive_dialog_resize_event(event: object) -> None:
        if not _state._alignment_dialog_widgets_live():
            return
        if callable(_state.previous_dialog_resize_event):
            _state.previous_dialog_resize_event(event)
        _state.QTimer.singleShot(0, _state._apply_alignment_dialog_responsive_layout)
    _state._responsive_dialog_resize_event = _responsive_dialog_resize_event

def _routing_dialog_layout_step_009(_state):

    def _run_static_preview_batch(callback: Callable[[], None]) -> None:
        _state._static_preview_batch_begin_helper(_state.static_preview_batch_state)
        try:
            callback()
        finally:
            batch_requests = _state._static_preview_batch_end_helper(_state.static_preview_batch_state)
        if batch_requests is None:
            return
        wants_texture = bool(batch_requests.get('texture'))
        wants_texture_uv = bool(batch_requests.get('texture_uv'))
        wants_rebuild = bool(batch_requests.get('rebuild'))
        wants_refresh = bool(batch_requests.get('refresh'))
        if wants_texture:
            _state._queue_texture_preview_refresh()
        elif wants_texture_uv:
            _state._queue_texture_uv_preview_refresh()
        elif wants_rebuild:
            _state._queue_static_preview_rebuild()
        elif wants_refresh:
            _state._queue_selection_preview_refresh()
    _state._run_static_preview_batch = _run_static_preview_batch

def _routing_dialog_layout_step_010(_state):
    _state._factory_result_values.update({'_set_preview_performance_status': _state._set_preview_performance_status, '_apply_alignment_dialog_responsive_layout': _state._apply_alignment_dialog_responsive_layout, '_responsive_dialog_resize_event': _state._responsive_dialog_resize_event, '_save_alignment_dialog_splitter_sizes': _state._save_alignment_dialog_splitter_sizes, '_run_static_preview_batch': _state._run_static_preview_batch})

STEPS = (
    _routing_dialog_layout_step_001,
    _routing_dialog_layout_step_002,
    _routing_dialog_layout_step_003,
    _routing_dialog_layout_step_004,
    _routing_dialog_layout_step_005,
    _routing_dialog_layout_step_006,
    _routing_dialog_layout_step_007,
    _routing_dialog_layout_step_008,
    _routing_dialog_layout_step_009,
    _routing_dialog_layout_step_010,
)
