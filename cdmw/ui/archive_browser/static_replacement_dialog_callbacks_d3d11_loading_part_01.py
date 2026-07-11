from __future__ import annotations

def _d3d11_loading_step_001(_state):
    _state.Dict = _state.context.get('Dict')
    _state.Mapping = _state.context.get('Mapping')
    _state.ModelPreviewData = _state.context.get('ModelPreviewData')
    _state.NativePreviewPanel = _state.context.get('NativePreviewPanel')
    _state.Path = _state.context.get('Path')
    _state.QProcess = _state.context.get('QProcess')
    _state.QThread = _state.context.get('QThread')
    _state.QTimer = _state.context.get('QTimer')
    _state._alignment_active_qt_camera_role_helper = _state.context.get('_alignment_active_qt_camera_role_helper')
    _state._alignment_d3d11_camera_active_helper = _state.context.get('_alignment_d3d11_camera_active_helper')
    _state._alignment_d3d11_clear_loading_start_helper = _state.context.get('_alignment_d3d11_clear_loading_start_helper')
    _state._alignment_d3d11_clear_stuck_loading_route_helper = _state.context.get('_alignment_d3d11_clear_stuck_loading_route_helper')
    _state._alignment_d3d11_ensure_loading_started_helper = _state.context.get('_alignment_d3d11_ensure_loading_started_helper')
    _state._alignment_d3d11_failed_performance_helper = _state.context.get('_alignment_d3d11_failed_performance_helper')
    _state._alignment_d3d11_host_ready_state_helper = _state.context.get('_alignment_d3d11_host_ready_state_helper')
    _state._alignment_d3d11_live_frame_available_helper = _state.context.get('_alignment_d3d11_live_frame_available_helper')
    _state._alignment_d3d11_loaded_package_transform_current_helper = _state.context.get('_alignment_d3d11_loaded_package_transform_current_helper')
    _state._alignment_d3d11_loading_active_helper = _state.context.get('_alignment_d3d11_loading_active_helper')
    _state._alignment_d3d11_loading_cleared_performance_helper = _state.context.get('_alignment_d3d11_loading_cleared_performance_helper')
    _state._alignment_d3d11_loading_next_frame_helper = _state.context.get('_alignment_d3d11_loading_next_frame_helper')
    _state._alignment_d3d11_loading_presentation_helper = _state.context.get('_alignment_d3d11_loading_presentation_helper')
    _state._alignment_d3d11_loading_recovery_action_helper = _state.context.get('_alignment_d3d11_loading_recovery_action_helper')
    _state._alignment_d3d11_loading_set_active_helper = _state.context.get('_alignment_d3d11_loading_set_active_helper')
    _state._alignment_d3d11_loading_spinner_frames_helper = _state.context.get('_alignment_d3d11_loading_spinner_frames_helper')
    _state._alignment_d3d11_loading_spinner_html_helper = _state.context.get('_alignment_d3d11_loading_spinner_html_helper')
    _state._alignment_d3d11_loading_stuck_helper = _state.context.get('_alignment_d3d11_loading_stuck_helper')
    _state._alignment_d3d11_loading_watchdog_snapshot_helper = _state.context.get('_alignment_d3d11_loading_watchdog_snapshot_helper')
    _state._alignment_d3d11_mark_preview_unloaded_helper = _state.context.get('_alignment_d3d11_mark_preview_unloaded_helper')
    _state._alignment_d3d11_pipeline_stage_helper = _state.context.get('_alignment_d3d11_pipeline_stage_helper')
    _state._alignment_d3d11_progress_update_helper = _state.context.get('_alignment_d3d11_progress_update_helper')
    _state._alignment_d3d11_record_stale_reload_restart_helper = _state.context.get('_alignment_d3d11_record_stale_reload_restart_helper')
    _state._alignment_d3d11_request_active_helper = _state.context.get('_alignment_d3d11_request_active_helper')
    _state._alignment_d3d11_reset_request_state_helper = _state.context.get('_alignment_d3d11_reset_request_state_helper')
    _state._alignment_d3d11_resources_waiting_detail_helper = _state.context.get('_alignment_d3d11_resources_waiting_detail_helper')
    _state._alignment_d3d11_resources_waiting_performance_details_helper = _state.context.get('_alignment_d3d11_resources_waiting_performance_details_helper')
    _state._alignment_d3d11_resources_waiting_performance_helper = _state.context.get('_alignment_d3d11_resources_waiting_performance_helper')
    _state._alignment_d3d11_restart_performance_helper = _state.context.get('_alignment_d3d11_restart_performance_helper')
    _state._alignment_d3d11_saved_view_state_route_helper = _state.context.get('_alignment_d3d11_saved_view_state_route_helper')
    _state._alignment_d3d11_stale_loading_detail_helper = _state.context.get('_alignment_d3d11_stale_loading_detail_helper')
    _state._alignment_d3d11_stop_process = _state.context.get('_alignment_d3d11_stop_process')
    _state._alignment_d3d11_view_state_payload_route_helper = _state.context.get('_alignment_d3d11_view_state_payload_route_helper')
    _state._alignment_d3d11_watchdog_ready_performance_helper = _state.context.get('_alignment_d3d11_watchdog_ready_performance_helper')
    _state._alignment_dialog_widgets_live = _state.context.get('_alignment_dialog_widgets_live')
    _state._alignment_preview_mode_key_helper = _state.context.get('_alignment_preview_mode_key_helper')
    _state._alignment_preview_mode_saved_state_helper = _state.context.get('_alignment_preview_mode_saved_state_helper')
    _state._alignment_preview_quality_label_helper = _state.context.get('_alignment_preview_quality_label_helper')
    _state._alignment_preview_view_sync_should_apply_helper = _state.context.get('_alignment_preview_view_sync_should_apply_helper')
    _state._clear_alignment_d3d11_fast_transform_state = _state.context.get('_clear_alignment_d3d11_fast_transform_state')
    _state._current_alignment_preview_render_settings = _state.context.get('_current_alignment_preview_render_settings')
    _state._fixed_alignment_camera_state_helper = _state.context.get('_fixed_alignment_camera_state_helper')
    _state._get_preview_render_settings = _state.context.get('_get_preview_render_settings')
    _state._nudged_alignment_camera_state_helper = _state.context.get('_nudged_alignment_camera_state_helper')
    _state._qt_alignment_camera_state_mapping_helper = _state.context.get('_qt_alignment_camera_state_mapping_helper')
    _state._qt_alignment_camera_tuple_helper = _state.context.get('_qt_alignment_camera_tuple_helper')
    _state._qt_object_is_valid = _state.context.get('_qt_object_is_valid')
    _state._queue_latest_alignment_d3d11_rebuild_for_stale_reload = _state.context.get('_queue_latest_alignment_d3d11_rebuild_for_stale_reload')
    _state._record_runtime_event = _state.context.get('_record_runtime_event')
    _state._replay_alignment_d3d11_fast_transform = _state.context.get('_replay_alignment_d3d11_fast_transform')
    _state._safe_alignment_timer_active = _state.context.get('_safe_alignment_timer_active')
    _state._safe_start_alignment_timer = _state.context.get('_safe_start_alignment_timer')
    _state._safe_stop_alignment_timer = _state.context.get('_safe_stop_alignment_timer')
    _state._set_preview_performance_status = _state.context.get('_set_preview_performance_status')
    _state._sync_highlight_sets = _state.context.get('_sync_highlight_sets')
    _state.alignment_d3d11_available = _state.context.get('alignment_d3d11_available')
    _state.alignment_d3d11_drag_transaction = _state.context.get('alignment_d3d11_drag_transaction') or {}
    _state.alignment_d3d11_loading_spinner_label = _state.context.get('alignment_d3d11_loading_spinner_label')
    _state.alignment_d3d11_loading_state = _state.context.get('alignment_d3d11_loading_state')
    _state.alignment_d3d11_loading_timer = _state.context.get('alignment_d3d11_loading_timer')
    _state.alignment_d3d11_preview_host = _state.context.get('alignment_d3d11_preview_host')
    _state.alignment_d3d11_preview_status_label = _state.context.get('alignment_d3d11_preview_status_label')
    _state.alignment_d3d11_reload_stuck_timeout_s = _state.context.get('alignment_d3d11_reload_stuck_timeout_s')
    _state.alignment_d3d11_state = _state.context.get('alignment_d3d11_state')
    _state.alignment_d3d11_view_state = _state.context.get('alignment_d3d11_view_state')
    _state.alignment_preview_mode_view_states = _state.context.get('alignment_preview_mode_view_states')
    _state.alignment_preview_view_sync = _state.context.get('alignment_preview_view_sync')
    _state.alignment_transform_generation = _state.context.get('alignment_transform_generation') or {}
    _state.dialog_title = _state.context.get('dialog_title')
    _state.entry = _state.context.get('entry')
    _state.original_dialog_preview = _state.context.get('original_dialog_preview')
    _state.overlay_dialog_preview = _state.context.get('overlay_dialog_preview')
    _state.preview_mode_combo = _state.context.get('preview_mode_combo')
    _state.preview_render_settings = _state.context.get('preview_render_settings')
    _state.preview_renderer_combo = _state.context.get('preview_renderer_combo')
    _state.replacement_only_preview = _state.context.get('replacement_only_preview')
    _state.self = _state.context.get('self')
    _state.static_dialog_preview = _state.context.get('static_dialog_preview')
    _state.time = _state.context.get('time')
    _state.prompt_shell_context = _state.context.get('prompt_shell_context')

def _d3d11_loading_step_002(_state):

    def _set_preview_performance_status_if_ready(summary: str, *, details: str='') -> None:
        if callable(_state._set_preview_performance_status):
            _state._set_preview_performance_status(summary, details=details)
    _state._set_preview_performance_status_if_ready = _set_preview_performance_status_if_ready

def _d3d11_loading_step_003(_state):

    def _stale_reload_rebuild_callback():
        if callable(_state._queue_latest_alignment_d3d11_rebuild_for_stale_reload):
            return _state._queue_latest_alignment_d3d11_rebuild_for_stale_reload
        if isinstance(_state.prompt_shell_context, dict):
            callback = _state.prompt_shell_context.get('_queue_latest_alignment_d3d11_rebuild_for_stale_reload')
            if callable(callback):
                return callback
        return None
    _state._stale_reload_rebuild_callback = _stale_reload_rebuild_callback

def _d3d11_loading_step_004(_state):

    def _current_alignment_preview_render_settings_value():
        if callable(_state._current_alignment_preview_render_settings):
            return _state._current_alignment_preview_render_settings()
        if callable(_state._get_preview_render_settings):
            return _state._get_preview_render_settings()
        if _state.preview_render_settings is not None:
            return _state.preview_render_settings
        return _state.self._current_model_preview_render_settings()
    _state._current_alignment_preview_render_settings_value = _current_alignment_preview_render_settings_value

def _d3d11_loading_step_005(_state):

    def _tick_alignment_d3d11_loading_spinner() -> None:
        if not _state._alignment_dialog_widgets_live() or not _state._qt_object_is_valid(_state.alignment_d3d11_loading_spinner_label):
            return
        frames = _state._alignment_d3d11_loading_spinner_frames_helper()
        frame_index = _state._alignment_d3d11_loading_next_frame_helper(_state.alignment_d3d11_loading_state, len(frames))
        _state.alignment_d3d11_loading_spinner_label.setText(_state._alignment_d3d11_loading_spinner_html_helper(frames[frame_index]))
        try:
            if _state._alignment_d3d11_loading_stuck():
                _state._clear_stuck_alignment_d3d11_loading('loading watchdog')
        except NameError:
            pass
    _state._tick_alignment_d3d11_loading_spinner = _tick_alignment_d3d11_loading_spinner

def _d3d11_loading_step_006(_state):

    def _set_alignment_d3d11_loading(active: bool, message: str='', *, detail: str='') -> None:
        active = _state._alignment_d3d11_loading_set_active_helper(_state.alignment_d3d11_loading_state, active)
        presentation = _state._alignment_d3d11_loading_presentation_helper(active, message=message, detail=detail)
        if not _state._alignment_dialog_widgets_live():
            _state._alignment_d3d11_loading_set_active_helper(_state.alignment_d3d11_loading_state, False)
            _state._alignment_d3d11_clear_loading_start_helper(_state.alignment_d3d11_state)
            inactive_presentation = _state._alignment_d3d11_loading_presentation_helper(False)
            try:
                _state._safe_stop_alignment_timer(_state.alignment_d3d11_loading_timer)
                if _state._qt_object_is_valid(_state.alignment_d3d11_loading_spinner_label):
                    _state.alignment_d3d11_loading_spinner_label.setVisible(inactive_presentation.spinner_visible)
                    if inactive_presentation.clear_spinner_text:
                        _state.alignment_d3d11_loading_spinner_label.setText('')
            except RuntimeError:
                pass
            return
        if presentation.status_text:
            _state.alignment_d3d11_preview_status_label.setText(presentation.status_text)
        if presentation.status_tooltip:
            _state.alignment_d3d11_preview_status_label.setToolTip(presentation.status_tooltip)
        if active:
            _state._alignment_d3d11_ensure_loading_started_helper(_state.alignment_d3d11_state, _state.time.perf_counter())
            _state.alignment_d3d11_loading_spinner_label.setVisible(presentation.spinner_visible)
            if not _state._safe_alignment_timer_active(_state.alignment_d3d11_loading_timer):
                _state._tick_alignment_d3d11_loading_spinner()
                _state._safe_start_alignment_timer(_state.alignment_d3d11_loading_timer)
        else:
            _state._alignment_d3d11_clear_loading_start_helper(_state.alignment_d3d11_state)
            _state._safe_stop_alignment_timer(_state.alignment_d3d11_loading_timer)
            _state.alignment_d3d11_loading_spinner_label.setVisible(presentation.spinner_visible)
            if presentation.clear_spinner_text:
                _state.alignment_d3d11_loading_spinner_label.setText('')
    _state._set_alignment_d3d11_loading = _set_alignment_d3d11_loading

def _d3d11_loading_step_007(_state):

    def _set_alignment_d3d11_progress(percent: int, message: str, *, request_id: int=0, stage: str='', detail: str='', active: bool=True) -> None:
        if int(request_id or 0) > 0 and int(request_id or 0) != int(_state.alignment_d3d11_state.get('request_id', 0) or 0):
            return
        message_text, tooltip_text, loading_active = _state._alignment_d3d11_progress_update_helper(_state.alignment_d3d11_state, percent, message, stage=stage, detail=detail, active=active)
        _state._set_alignment_d3d11_loading(loading_active, message_text, detail=tooltip_text)
    _state._set_alignment_d3d11_progress = _set_alignment_d3d11_progress

def _d3d11_loading_step_008(_state):

    def _set_alignment_d3d11_pipeline_stage(stage: str, detail: str='') -> None:
        normalized = _state._alignment_d3d11_pipeline_stage_helper(_state.alignment_d3d11_state, stage)
        if detail:
            _state._record_runtime_event('alignment_d3d11_preview_pipeline_stage', path=getattr(_state.entry, 'path', ''), dialog_title=_state.dialog_title, stage=normalized, detail=str(detail or ''))
    _state._set_alignment_d3d11_pipeline_stage = _set_alignment_d3d11_pipeline_stage

def _d3d11_loading_step_009(_state):
    _state.alignment_d3d11_loading_timer.timeout.connect(_state._tick_alignment_d3d11_loading_spinner)

def _d3d11_loading_step_010(_state):

    def _reset_alignment_d3d11_request_state(*, increment_request: bool=True, clear_loading: bool=False, message: str='') -> None:
        _state._alignment_d3d11_reset_request_state_helper(_state.alignment_d3d11_state, increment_request=increment_request, clear_loading=clear_loading)
        if clear_loading:
            _state._set_alignment_d3d11_loading(False, message or 'Preview idle.')
    _state._reset_alignment_d3d11_request_state = _reset_alignment_d3d11_request_state

def _d3d11_loading_step_011(_state):

    def _alignment_d3d11_request_active() -> bool:
        process = _state.alignment_d3d11_state.get('process')
        process_active = isinstance(process, _state.QProcess) and process.state() != _state.QProcess.NotRunning
        thread = _state.alignment_d3d11_state.get('thread')
        thread_active = isinstance(thread, _state.QThread) and thread.isRunning()
        queued_model_active = isinstance(_state.alignment_d3d11_state.get('queued_model'), _state.ModelPreviewData)
        pending_model_active = isinstance(_state.alignment_d3d11_state.get('pending_model'), _state.ModelPreviewData)
        active_package = _state.alignment_d3d11_state.get('active_package')
        active_package_exists = isinstance(active_package, _state.Path) and active_package.exists()
        return _state._alignment_d3d11_request_active_helper(process_active=process_active, thread_active=thread_active, queued_model_active=queued_model_active, pending_model_active=pending_model_active, active_package_exists=active_package_exists)
    _state._alignment_d3d11_request_active = _alignment_d3d11_request_active

def _d3d11_loading_step_012(_state):

    def _alignment_d3d11_live_frame_available() -> bool:
        process = _state.alignment_d3d11_state.get('process')
        active_package = _state.alignment_d3d11_state.get('active_package')
        return _state._alignment_d3d11_live_frame_available_helper(_state.alignment_d3d11_state, process_active=isinstance(process, _state.QProcess) and process.state() != _state.QProcess.NotRunning, active_package_exists=isinstance(active_package, _state.Path) and active_package.exists())
    _state._alignment_d3d11_live_frame_available = _alignment_d3d11_live_frame_available

def _d3d11_loading_step_013(_state):

    def _alignment_d3d11_host_ready(*, require_child: bool=False) -> tuple[bool, str]:
        if not _state._alignment_dialog_widgets_live():
            return (False, 'alignment dialog is closing')
        try:
            parent_hwnd = _state.alignment_d3d11_preview_host.winId()
            child_hwnd = 0
            if require_child:
                child_hwnd_getter = getattr(_state.alignment_d3d11_preview_host, '_host_hwnd', None)
                child_hwnd = child_hwnd_getter() if callable(child_hwnd_getter) else 0
            host_ready_state = _state._alignment_d3d11_host_ready_state_helper(dialog_live=_state._alignment_dialog_widgets_live(), host_visible=_state.alignment_d3d11_preview_host.isVisible(), width=_state.alignment_d3d11_preview_host.width(), height=_state.alignment_d3d11_preview_host.height(), parent_hwnd=parent_hwnd, child_hwnd=child_hwnd, require_child=require_child)
        except Exception as exc:
            host_ready_state = _state._alignment_d3d11_host_ready_state_helper(dialog_live=True, host_visible=True, width=0, height=0, parent_hwnd=0, require_child=require_child, check_error=exc)
        return (host_ready_state.ready, host_ready_state.detail)
    _state._alignment_d3d11_host_ready = _alignment_d3d11_host_ready

def _d3d11_loading_step_014(_state):

    def _alignment_d3d11_loading_stuck() -> bool:
        loading_active = _state._alignment_d3d11_loading_active_helper(_state.alignment_d3d11_loading_state)
        if bool(_state.alignment_d3d11_state.get('preview_loaded')):
            if isinstance(_state.alignment_d3d11_state.get('queued_model'), _state.ModelPreviewData):
                return False
            if isinstance(_state.alignment_d3d11_state.get('pending_model'), _state.ModelPreviewData):
                return False
            thread = _state.alignment_d3d11_state.get('thread')
            thread_active = False
            if isinstance(thread, _state.QThread):
                try:
                    if thread.isRunning():
                        return False
                    thread_active = False
                except RuntimeError:
                    return False
            return _state._alignment_d3d11_loading_stuck_helper(loading_active=loading_active, preview_loaded=True, queued_model_active=False, pending_model_active=False, thread_active=thread_active, loading_started_at=0.0, loading_elapsed_s=0.0, timeout_s=_state.alignment_d3d11_reload_stuck_timeout_s, request_active=False, process_active=False, active_package_exists=False)
        started_at = float(_state.alignment_d3d11_state.get('loading_started_at', 0.0) or 0.0)
        elapsed_s = _state.time.perf_counter() - started_at if started_at > 0.0 else 0.0
        request_active = _state._alignment_d3d11_request_active()
        process = _state.alignment_d3d11_state.get('process')
        process_active = isinstance(process, _state.QProcess) and process.state() != _state.QProcess.NotRunning
        active_package = _state.alignment_d3d11_state.get('active_package')
        active_package_exists = isinstance(active_package, _state.Path) and active_package.exists()
        return _state._alignment_d3d11_loading_stuck_helper(loading_active=loading_active, preview_loaded=False, queued_model_active=False, pending_model_active=False, thread_active=False, loading_started_at=started_at, loading_elapsed_s=elapsed_s, timeout_s=_state.alignment_d3d11_reload_stuck_timeout_s, request_active=request_active, process_active=process_active, active_package_exists=active_package_exists)
    _state._alignment_d3d11_loading_stuck = _alignment_d3d11_loading_stuck

def _d3d11_loading_step_015(_state):

    def _clear_stuck_alignment_d3d11_loading(reason: str) -> None:
        if not _state._alignment_dialog_widgets_live():
            closed_action = _state._alignment_d3d11_loading_recovery_action_helper(_state._alignment_d3d11_clear_stuck_loading_route_helper(dialog_live=False, preview_loaded=False, resources_loaded=False, process_active=False, active_package_exists=False, host_ready=False, child_ready=False, restart_count=0, drag_active=False))
            if closed_action.should_mark_preview_unloaded:
                _state._alignment_d3d11_mark_preview_unloaded_helper(_state.alignment_d3d11_state)
            if closed_action.should_set_loading_inactive:
                _state._alignment_d3d11_loading_set_active_helper(_state.alignment_d3d11_loading_state, False)
                _state._alignment_d3d11_clear_loading_start_helper(_state.alignment_d3d11_state)
            _state._safe_stop_alignment_timer(_state.alignment_d3d11_loading_timer)
            return
        process = _state.alignment_d3d11_state.get('process')
        active_package = _state.alignment_d3d11_state.get('active_package')
        process_active = isinstance(process, _state.QProcess) and process.state() != _state.QProcess.NotRunning
        package_active = isinstance(active_package, _state.Path) and active_package.exists()
        watchdog_snapshot = _state._alignment_d3d11_loading_watchdog_snapshot_helper(_state.alignment_d3d11_state, now_s=_state.time.perf_counter())
        host_ready = False
        host_detail = ''
        child_ready = False
        child_detail = ''
        if not watchdog_snapshot.preview_loaded:
            host_ready, host_detail = _state._alignment_d3d11_host_ready(require_child=False)
            child_ready, child_detail = _state._alignment_d3d11_host_ready(require_child=True)
        clear_route = _state._alignment_d3d11_clear_stuck_loading_route_helper(dialog_live=True, preview_loaded=watchdog_snapshot.preview_loaded, resources_loaded=watchdog_snapshot.resources_loaded, process_active=process_active, active_package_exists=package_active, host_ready=host_ready, child_ready=child_ready, restart_count=watchdog_snapshot.restart_count, drag_active=bool(_state.alignment_d3d11_drag_transaction.get('active')))
        recovery_action = _state._alignment_d3d11_loading_recovery_action_helper(clear_route)
        if recovery_action.should_reset_request_idle:
            _state._reset_alignment_d3d11_request_state(increment_request=False, clear_loading=True, message=recovery_action.loading_message)
            loading_cleared_presentation = _state._alignment_d3d11_loading_cleared_performance_helper(reason)
            _state._set_preview_performance_status_if_ready(loading_cleared_presentation.summary, details=loading_cleared_presentation.details)
            return
        if recovery_action.should_restore_loaded_preview:
            _state.alignment_d3d11_preview_host.set_display_mode(str(_state.preview_mode_combo.currentData() or 'side_by_side'))
            _state.alignment_d3d11_preview_host.set_render_tuning(_state._current_alignment_preview_render_settings_value())
            saved_view_state = _state._alignment_d3d11_saved_view_state()
            if saved_view_state:
                _state.alignment_d3d11_preview_host.restore_view_state(saved_view_state)
            if _state._alignment_d3d11_loaded_package_transform_current_helper(_state.alignment_d3d11_state, _state.alignment_transform_generation, request_id=watchdog_snapshot.active_request_id):
                if callable(_state._clear_alignment_d3d11_fast_transform_state):
                    _state._clear_alignment_d3d11_fast_transform_state(reset_host=True)
            if callable(_state._sync_highlight_sets):
                _state._sync_highlight_sets()
            if callable(_state._replay_alignment_d3d11_fast_transform):
                _state._replay_alignment_d3d11_fast_transform()
            _state._set_alignment_d3d11_progress(100, recovery_action.progress_message, active=False)
            watchdog_ready_presentation = _state._alignment_d3d11_watchdog_ready_performance_helper(quality_label=_state._alignment_preview_quality_label_helper(_state.alignment_d3d11_state), reason=reason, active_package=active_package)
            _state._set_preview_performance_status_if_ready(watchdog_ready_presentation.summary, details=watchdog_ready_presentation.details)
            return
        if recovery_action.action == 'resources_waiting':
            waiting_detail = _state._alignment_d3d11_resources_waiting_detail_helper(reason=reason, elapsed_s=watchdog_snapshot.elapsed_s, last_percent=watchdog_snapshot.last_percent, last_stage=watchdog_snapshot.last_stage, host_detail=host_detail, child_detail=child_detail, active_package=active_package)
            waiting_performance_details = _state._alignment_d3d11_resources_waiting_performance_details_helper(reason=reason, elapsed_s=watchdog_snapshot.elapsed_s, host_detail=host_detail, child_detail=child_detail, active_package=active_package)
            waiting_performance = _state._alignment_d3d11_resources_waiting_performance_helper(waiting_performance_details)
            _state._set_alignment_d3d11_loading(False, recovery_action.loading_message, detail=waiting_detail)
            _state._set_preview_performance_status_if_ready(waiting_performance.summary, details=waiting_performance.details)
            return
        stale_details = _state._alignment_d3d11_stale_loading_detail_helper(reason=reason, elapsed_s=watchdog_snapshot.elapsed_s, last_percent=watchdog_snapshot.last_percent, last_stage=watchdog_snapshot.last_stage, host_detail=host_detail, child_detail=child_detail, active_package=active_package)
        if recovery_action.should_record_restart:
            _state._alignment_d3d11_record_stale_reload_restart_helper(_state.alignment_d3d11_state)
        if recovery_action.action == 'restart':
            _state._set_alignment_d3d11_loading(False, recovery_action.loading_message, detail=stale_details)
            restart_presentation = _state._alignment_d3d11_restart_performance_helper(quality_label=_state._alignment_preview_quality_label_helper(_state.alignment_d3d11_state), stale_details=stale_details, restart_count=watchdog_snapshot.restart_count)
            _state._set_preview_performance_status_if_ready(restart_presentation.summary, details=restart_presentation.details)
            if recovery_action.should_stop_process and callable(_state._alignment_d3d11_stop_process):
                _state._alignment_d3d11_stop_process()

            def _restart_latest_alignment_d3d11_rebuild(expected_request=watchdog_snapshot.active_request_id) -> None:
                callback = _state._stale_reload_rebuild_callback()
                if callable(callback):
                    callback(expected_request)
            _state.QTimer.singleShot(0, _restart_latest_alignment_d3d11_rebuild)
            return
        _state._set_alignment_d3d11_loading(False, recovery_action.loading_message, detail=stale_details)
        failed_presentation = _state._alignment_d3d11_failed_performance_helper(quality_label=_state._alignment_preview_quality_label_helper(_state.alignment_d3d11_state), stale_details=stale_details)
        _state._set_preview_performance_status_if_ready(failed_presentation.summary, details=failed_presentation.details)
    _state._clear_stuck_alignment_d3d11_loading = _clear_stuck_alignment_d3d11_loading

def _d3d11_loading_step_016(_state):

    def _handle_alignment_d3d11_view_state_payload(payload: object) -> None:
        current_generation = int(getattr(_state.self, 'mesh_editor_d3d11_view_state_reset_generation', 0) or 0)
        view_state_route = _state._alignment_d3d11_view_state_payload_route_helper(_state.alignment_d3d11_state, current_generation, payload_is_mapping=isinstance(payload, _state.Mapping))
        if view_state_route.should_ignore:
            return
        if view_state_route.should_clear_saved_state:
            _state.alignment_d3d11_view_state.clear()
        if not view_state_route.should_store_snapshot:
            return
        _state.alignment_d3d11_view_state.update(_state.self._sanitize_d3d11_view_state_for_restore(_state.alignment_d3d11_preview_host.view_state_snapshot()))
    _state._handle_alignment_d3d11_view_state_payload = _handle_alignment_d3d11_view_state_payload

def _d3d11_loading_step_017(_state):
    _state.alignment_d3d11_preview_host.view_state_payload_changed.connect(_state._handle_alignment_d3d11_view_state_payload)

def _d3d11_loading_step_018(_state):

    def _alignment_d3d11_saved_view_state() -> Dict[str, object]:
        current_generation = int(getattr(_state.self, 'mesh_editor_d3d11_view_state_reset_generation', 0) or 0)
        saved_route = _state._alignment_d3d11_saved_view_state_route_helper(_state.alignment_d3d11_state, current_generation, has_saved_state=bool(_state.alignment_d3d11_view_state))
        if saved_route.should_clear_saved_state:
            _state.alignment_d3d11_view_state.clear()
            return {}
        if not saved_route.should_return_saved_state:
            return {}
        return _state.self._sanitize_d3d11_view_state_for_restore(_state.alignment_d3d11_view_state)
    _state._alignment_d3d11_saved_view_state = _alignment_d3d11_saved_view_state

def _d3d11_loading_step_019(_state):

    def _sync_alignment_preview_view_state(source_widget: NativePreviewPanel, *target_widgets: NativePreviewPanel) -> None:
        if not _state._alignment_preview_view_sync_should_apply_helper(_state.alignment_preview_view_sync, _state.preview_mode_combo.currentData()):
            return
        state = source_widget.view_state_snapshot()
        _state.alignment_preview_view_sync['active'] = True
        try:
            for target_widget in target_widgets:
                target_widget.restore_view_state(state)
        finally:
            _state.alignment_preview_view_sync['active'] = False
    _state._sync_alignment_preview_view_state = _sync_alignment_preview_view_state

def _d3d11_loading_step_020(_state):

    def _alignment_d3d11_camera_active() -> bool:
        return _state._alignment_d3d11_camera_active_helper(_state.preview_renderer_combo.currentData(), bool(_state.alignment_d3d11_available))
    _state._alignment_d3d11_camera_active = _alignment_d3d11_camera_active

def _d3d11_loading_step_021(_state):

    def _alignment_active_qt_camera_widgets() -> tuple[NativePreviewPanel, ...]:
        active_role = _state._alignment_active_qt_camera_role_helper(_state.preview_mode_combo.currentData())
        if active_role == 'replacement_only':
            return (_state.replacement_only_preview,)
        if active_role == 'overlay':
            return (_state.overlay_dialog_preview,)
        return (_state.original_dialog_preview, _state.static_dialog_preview)
    _state._alignment_active_qt_camera_widgets = _alignment_active_qt_camera_widgets

def _d3d11_loading_step_022(_state):

    def _alignment_current_camera_state() -> Dict[str, object]:
        if _state._alignment_d3d11_camera_active():
            return _state.self._sanitize_d3d11_view_state_for_restore(_state.alignment_d3d11_preview_host.view_state_snapshot())
        widgets = _state._alignment_active_qt_camera_widgets()
        state = widgets[0].view_state_snapshot() if widgets else _state.replacement_only_preview.view_state_snapshot()
        return _state._qt_alignment_camera_state_mapping_helper(state, role='replacement')
    _state._alignment_current_camera_state = _alignment_current_camera_state

def _d3d11_loading_step_023(_state):

    def _apply_alignment_camera_state(state: Mapping[str, object]) -> None:
        if _state._alignment_d3d11_camera_active():
            _state.alignment_d3d11_preview_host.restore_view_state(state)
            return
        qt_state = _state._qt_alignment_camera_tuple_helper(state, fit_distance=_state.NativePreviewPanel._FIT_DISTANCE)
        for preview_widget in (_state.original_dialog_preview, _state.static_dialog_preview, _state.overlay_dialog_preview, _state.replacement_only_preview):
            preview_widget.restore_view_state(qt_state)
    _state._apply_alignment_camera_state = _apply_alignment_camera_state

def _d3d11_loading_step_024(_state):

    def _save_alignment_preview_mode_view_state(mode: str) -> None:
        try:
            _state.alignment_preview_mode_view_states[_state._alignment_preview_mode_key_helper(mode)] = _state._alignment_current_camera_state()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
    _state._save_alignment_preview_mode_view_state = _save_alignment_preview_mode_view_state

def _d3d11_loading_step_025(_state):

    def _restore_alignment_preview_mode_view_state(mode: str) -> None:
        state = _state._alignment_preview_mode_saved_state_helper(_state.alignment_preview_mode_view_states, mode)
        if state is not None:
            _state._apply_alignment_camera_state(state)
    _state._restore_alignment_preview_mode_view_state = _restore_alignment_preview_mode_view_state

def _d3d11_loading_step_026(_state):

    def _set_alignment_camera(yaw: float, pitch: float) -> None:
        state = _state._alignment_current_camera_state()
        state.update(_state._fixed_alignment_camera_state_helper(yaw, pitch, role='replacement'))
        if _state._alignment_d3d11_camera_active():
            _state.alignment_d3d11_preview_host.set_view(yaw=float(yaw), pitch=float(pitch), zoom_factor=1.0, fit_to_view=True, pan=(0.0, 0.0, 0.0))
            return
        _state._apply_alignment_camera_state(state)
    _state._set_alignment_camera = _set_alignment_camera

def _d3d11_loading_step_027(_state):

    def _nudge_alignment_camera(delta_yaw: float=0.0, delta_pitch: float=0.0) -> None:
        state = _state._alignment_current_camera_state()
        _state._apply_alignment_camera_state(_state._nudged_alignment_camera_state_helper(state, delta_yaw=delta_yaw, delta_pitch=delta_pitch, role='replacement'))
    _state._nudge_alignment_camera = _nudge_alignment_camera

def _d3d11_loading_step_028(_state):
    _state._factory_result_values.update({'_tick_alignment_d3d11_loading_spinner': _state._tick_alignment_d3d11_loading_spinner, '_set_alignment_d3d11_loading': _state._set_alignment_d3d11_loading, '_set_alignment_d3d11_progress': _state._set_alignment_d3d11_progress, '_set_alignment_d3d11_pipeline_stage': _state._set_alignment_d3d11_pipeline_stage, '_reset_alignment_d3d11_request_state': _state._reset_alignment_d3d11_request_state, '_alignment_d3d11_request_active': _state._alignment_d3d11_request_active, '_alignment_d3d11_live_frame_available': _state._alignment_d3d11_live_frame_available, '_alignment_d3d11_host_ready': _state._alignment_d3d11_host_ready, '_alignment_d3d11_loading_stuck': _state._alignment_d3d11_loading_stuck, '_clear_stuck_alignment_d3d11_loading': _state._clear_stuck_alignment_d3d11_loading, '_handle_alignment_d3d11_view_state_payload': _state._handle_alignment_d3d11_view_state_payload, '_alignment_d3d11_saved_view_state': _state._alignment_d3d11_saved_view_state, '_sync_alignment_preview_view_state': _state._sync_alignment_preview_view_state, '_alignment_d3d11_camera_active': _state._alignment_d3d11_camera_active, '_alignment_active_qt_camera_widgets': _state._alignment_active_qt_camera_widgets, '_alignment_current_camera_state': _state._alignment_current_camera_state, '_apply_alignment_camera_state': _state._apply_alignment_camera_state, '_save_alignment_preview_mode_view_state': _state._save_alignment_preview_mode_view_state, '_restore_alignment_preview_mode_view_state': _state._restore_alignment_preview_mode_view_state, '_set_alignment_camera': _state._set_alignment_camera, '_nudge_alignment_camera': _state._nudge_alignment_camera})

STEPS = (
    _d3d11_loading_step_001,
    _d3d11_loading_step_002,
    _d3d11_loading_step_003,
    _d3d11_loading_step_004,
    _d3d11_loading_step_005,
    _d3d11_loading_step_006,
    _d3d11_loading_step_007,
    _d3d11_loading_step_008,
    _d3d11_loading_step_009,
    _d3d11_loading_step_010,
    _d3d11_loading_step_011,
    _d3d11_loading_step_012,
    _d3d11_loading_step_013,
    _d3d11_loading_step_014,
    _d3d11_loading_step_015,
    _d3d11_loading_step_016,
    _d3d11_loading_step_017,
    _d3d11_loading_step_018,
    _d3d11_loading_step_019,
    _d3d11_loading_step_020,
    _d3d11_loading_step_021,
    _d3d11_loading_step_022,
    _d3d11_loading_step_023,
    _d3d11_loading_step_024,
    _d3d11_loading_step_025,
    _d3d11_loading_step_026,
    _d3d11_loading_step_027,
    _d3d11_loading_step_028,
)
