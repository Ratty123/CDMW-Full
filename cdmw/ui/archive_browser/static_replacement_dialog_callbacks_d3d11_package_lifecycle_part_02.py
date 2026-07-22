from __future__ import annotations

def _d3d11_package_lifecycle_step_046(_state):

    def _handle_alignment_d3d11_stale_reload(package_dir: object, *, request_id: int=0, reason: str) -> None:
        _state._drop_alignment_d3d11_package_reload(package_dir, request_id=int(request_id or 0), reason=str(reason or 'stale_reload'))
        process = _state.alignment_d3d11_state.get('process')
        active_package = _state.alignment_d3d11_state.get('active_package')
        stale_reload_route = _state._alignment_d3d11_stale_reload_route_helper(dialog_live=_state._alignment_dialog_widgets_live(), drag_active=bool(_state.alignment_d3d11_drag_transaction.get('active')), process_active=isinstance(process, _state.QProcess) and process.state() != _state.QProcess.NotRunning, active_package_exists=isinstance(active_package, _state.Path) and active_package.exists())
        if stale_reload_route.should_pause_loading:
            _state._set_alignment_d3d11_loading(False, stale_reload_route.pause_message)
            return
        if not stale_reload_route.should_continue:
            return
        active_preview_alive = stale_reload_route.active_preview_alive
        if active_preview_alive:
            _state._alignment_d3d11_mark_preview_loaded_helper(_state.alignment_d3d11_state)
            _state._alignment_d3d11_mark_resources_loaded_helper(_state.alignment_d3d11_state)
            _state._sync_highlight_sets_if_ready()
            _state._replay_alignment_d3d11_fast_transform_if_ready()
        _state._set_alignment_d3d11_progress(100 if active_preview_alive else 0, 'Preview changed; rebuilding current view.', request_id=0, stage='stale_reload_requeued', detail=_state._alignment_d3d11_stale_package_dropped_detail_helper(reason=reason, request_id=int(request_id or 0), active_preview_alive=active_preview_alive), active=False)
        stale_dropped_presentation = _state._alignment_d3d11_stale_package_dropped_performance_helper(reason=reason, request_id=int(request_id or 0), active_preview_alive=active_preview_alive)
        _state._set_preview_performance_status_if_ready(stale_dropped_presentation.summary, details=stale_dropped_presentation.details)
        _state.QTimer.singleShot(0, lambda expected_request=int(request_id or 0): _state._queue_latest_alignment_d3d11_rebuild_for_stale_reload(expected_request))
    _state._handle_alignment_d3d11_stale_reload = _handle_alignment_d3d11_stale_reload

def _d3d11_package_lifecycle_step_047(_state):

    def _handle_alignment_d3d11_package_progress(request_id: int, current: int, total: int, message: str) -> None:
        if not _state._alignment_dialog_widgets_live():
            return
        if int(request_id or 0) != int(_state.alignment_d3d11_state.get('request_id', 0) or 0):
            return
        total = max(1, int(total or 1))
        current = max(0, min(total, int(current or 0)))
        percent = current if total == 100 else int(round(float(current) / float(total) * 80.0))
        percent = max(0, min(80, percent))
        _state._set_alignment_d3d11_progress(percent, str(message or 'Preparing preview package.'), request_id=int(request_id or 0), stage='package', detail=f'request_id={int(request_id or 0)}\nprogress={current}/{total}')
    _state._handle_alignment_d3d11_package_progress = _handle_alignment_d3d11_package_progress

def _d3d11_package_lifecycle_step_048(_state):

    class _AlignmentD3D11PackageWorkerReceiver(_state.QObject):

        @_state.Slot(int, int, int, str)
        def handle_progress(self, request_id: int, current: int, total: int, message: str) -> None:
            _state._handle_alignment_d3d11_package_progress(request_id, current, total, message)

        @_state.Slot(int, object, float, float)
        def handle_completed(self, request_id: int, package_dir_object: object, prepare_ms: float, package_ms: float) -> None:
            _state._handle_alignment_d3d11_package_ready(request_id, package_dir_object, prepare_ms, package_ms)

        @_state.Slot(int, str)
        def handle_error(self, request_id: int, message: str) -> None:
            _state._handle_alignment_d3d11_package_error(request_id, message)

        @_state.Slot()
        def handle_thread_finished(self) -> None:
            _state._cleanup_alignment_d3d11_package_worker_refs()
    _state._AlignmentD3D11PackageWorkerReceiver = _AlignmentD3D11PackageWorkerReceiver

def _d3d11_package_lifecycle_step_049(_state):
    _state.alignment_d3d11_package_worker_receiver = _state._AlignmentD3D11PackageWorkerReceiver(_state.dialog)

def _d3d11_package_lifecycle_step_050(_state):

    def _start_alignment_d3d11_package_worker(model: object, label: str, transform_generation: Optional[int]=None, display_mode: str='', reason: str='geometry') -> None:
        _state._record_runtime_event('mesh_alignment_d3d11_package_start_entered', path=getattr(_state.entry, 'path', ''), dialog_title=_state.dialog_title, model_type=type(model).__name__, display_mode=str(display_mode or ''), reason=str(reason or ''), transform_generation=int(transform_generation or 0), modify_original_clone=_state.modify_original_clone_mode)
        route_state = _state._alignment_d3d11_package_start_route_helper(dialog_live=_state._alignment_dialog_widgets_live(), preview_active=_state._alignment_d3d11_preview_active(), model_is_preview_data=isinstance(model, _state.ModelPreviewData), display_mode=display_mode, fallback_display_mode=_state.preview_mode_combo.currentData() or 'side_by_side', reason=reason, transform_generation=transform_generation, current_transform_generation=_state._current_alignment_transform_generation_value(), active_request_id=_state.alignment_d3d11_state.get('request_id', 0))
        if route_state.should_drop:
            _state._record_runtime_event('alignment_d3d11_package_reload_dropped', reason=route_state.drop_reason, request_id=int(_state.alignment_d3d11_state.get('request_id', 0) or 0), active_request_id=int(_state.alignment_d3d11_state.get('request_id', 0) or 0), package_dir='', dialog_closing=True)
            return
        if not route_state.should_start:
            _state._record_runtime_event('mesh_alignment_d3d11_package_start_skipped', path=getattr(_state.entry, 'path', ''), dialog_title=_state.dialog_title, drop_reason=str(route_state.drop_reason or ''), display_mode=str(route_state.display_mode or ''), rebuild_reason=str(route_state.rebuild_reason or ''), modify_original_clone=_state.modify_original_clone_mode)
            return
        requested_display_mode = route_state.display_mode
        rebuild_reason = route_state.rebuild_reason
        dirty_flags = _state._alignment_d3d11_dirty_flags_for_reason(rebuild_reason)
        if dirty_flags.affects_geometry():
            _state._alignment_d3d11_reset_material_parity_state_helper(_state.alignment_d3d11_state)
            _state._set_alignment_d3d11_pipeline_stage('material_loading', f'starting {rebuild_reason} rebuild')
        request_transform_generation = route_state.transform_generation
        settings, high_quality_textures, enable_material_combiner, package_quality = _state._alignment_d3d11_package_quality(label, model, reason=rebuild_reason)
        if isinstance(_state.alignment_d3d11_state.get('thread'), _state.QThread):
            _state._alignment_d3d11_queue_pending_request_helper(_state.alignment_d3d11_state, model=model, label=label, display_mode=requested_display_mode, reason=rebuild_reason, transform_generation=request_transform_generation, package_quality=package_quality)
            live_frame_available = _state._alignment_d3d11_live_frame_available()
            if not live_frame_available:
                _state._alignment_d3d11_mark_preview_unloaded_helper(_state.alignment_d3d11_state)
            _state._alignment_d3d11_stop_worker()
            _state._set_alignment_d3d11_progress(0, 'Preparing preview - queued latest request.', stage='queued', detail=_state._alignment_d3d11_queued_latest_preview_reload_detail_helper(rebuild_reason), active=not live_frame_available)
            _state._record_runtime_event('mesh_alignment_d3d11_package_start_deferred', path=getattr(_state.entry, 'path', ''), dialog_title=_state.dialog_title, rebuild_reason=rebuild_reason, package_quality=package_quality, modify_original_clone=_state.modify_original_clone_mode)
            return
        request_id = _state._alignment_d3d11_begin_package_request_helper(_state.alignment_d3d11_state, drag_generation=int(_state.alignment_d3d11_drag_generation.get('value', 0) or 0), transform_generation=request_transform_generation, display_mode=requested_display_mode, reason=rebuild_reason, package_quality=package_quality)
        _state._alignment_d3d11_record_package_request_metadata_helper(_state.alignment_d3d11_state, package_quality=package_quality, rebuild_reason=rebuild_reason)
        live_frame_available = _state._alignment_d3d11_live_frame_available()
        if not live_frame_available:
            _state._alignment_d3d11_mark_preview_unloaded_helper(_state.alignment_d3d11_state)
        cache_key = _state._alignment_d3d11_preview_cache_key(model, settings, label=label, display_mode=requested_display_mode, package_quality=package_quality)
        _state._alignment_d3d11_remember_request_cache_key_helper(_state.alignment_d3d11_state, request_id, cache_key)
        cache_entry = _state._alignment_d3d11_package_cache_get(cache_key)
        if isinstance(cache_entry, _state.Mapping):
            try:
                cached_package_dir = _state.Path(cache_entry.get('package_dir', ''))
            except TypeError:
                cached_package_dir = None
            if isinstance(cached_package_dir, _state.Path):
                package_quality = _state._alignment_d3d11_record_cache_hit_metadata_helper(_state.alignment_d3d11_state, cache_entry, package_quality=package_quality)
                _state._alignment_d3d11_remember_request_package_quality_helper(_state.alignment_d3d11_state, request_id, package_quality)
                existing_process = _state.alignment_d3d11_state.get('process')
                active_package = _state.alignment_d3d11_state.get('active_package')
                active_matches = _state._alignment_d3d11_active_package_matches_helper(process_active=isinstance(existing_process, _state.QProcess) and existing_process.state() != _state.QProcess.NotRunning, active_package=active_package, package=cached_package_dir)
                if active_matches:
                    active_matches, _active_host_detail = _state._alignment_d3d11_host_ready(require_child=True)
                if active_matches:
                    if _state._alignment_d3d11_loaded_package_transform_current_helper(_state.alignment_d3d11_state, _state.alignment_transform_generation, request_id=request_id):
                        _state._clear_alignment_d3d11_fast_transform_state_if_ready(reset_host=True)
                    cached_quality = _state._alignment_d3d11_mark_active_cached_package_reused_helper(_state.alignment_d3d11_state, request_id=request_id, display_mode=requested_display_mode, package_quality=package_quality, cache_key=cache_key)
                    _state.alignment_d3d11_preview_host.set_display_mode(str(_state.preview_mode_combo.currentData() or requested_display_mode))
                    _state.alignment_d3d11_preview_host.set_render_tuning(_state._current_alignment_preview_render_settings_value())
                    _state._reapply_current_global_flip_v_fast_preview()
                    _state.preview_stack.setCurrentWidget(_state.alignment_d3d11_preview_page)
                    _state._sync_highlight_sets_if_ready()
                    _state._replay_alignment_d3d11_fast_transform_if_ready()
                    if cached_quality == 'fast_geometry':
                        _state._set_alignment_d3d11_pipeline_stage('fast_geometry', 'active cached fast package reused')
                    elif cached_quality == 'archive_parity':
                        _state._set_alignment_d3d11_pipeline_stage('archive_parity_ready', 'active cached archive package reused')
                    _state._set_alignment_d3d11_progress(100, 'Preview ready.', request_id=request_id, stage='ready', detail=f'Reused active cached package. reason={rebuild_reason}', active=False)
                    cached_reuse_presentation = _state._alignment_d3d11_cached_reuse_performance_helper(_state.alignment_d3d11_state, quality_label=_state._alignment_preview_quality_label_helper(_state.alignment_d3d11_state), rebuild_reason=rebuild_reason)
                    _state._set_preview_performance_status_if_ready(cached_reuse_presentation.summary, details=cached_reuse_presentation.details)
                    _state._clear_source_parts_preview_rebuild_pending_if_ready()
                    if cached_quality == 'fast_geometry':
                        _state._queue_alignment_archive_parity_upgrade('active cached fast package reused')
                    return
                live_frame_available = _state._alignment_d3d11_live_frame_available()
                _state._set_alignment_d3d11_progress(82, 'Loading cached preview package.', request_id=request_id, stage='cached_package', detail=_state._alignment_d3d11_cached_loading_progress_detail_helper(rebuild_reason), active=not live_frame_available)
                cached_loading_presentation = _state._alignment_d3d11_cached_loading_performance_helper(rebuild_reason)
                _state._set_preview_performance_status_if_ready(cached_loading_presentation.summary, details=cached_loading_presentation.details)
                _state._start_alignment_d3d11_process(cached_package_dir, request_id=request_id)
                _state._record_runtime_event('mesh_alignment_d3d11_package_cache_used', path=getattr(_state.entry, 'path', ''), dialog_title=_state.dialog_title, request_id=int(request_id or 0), package_dir=str(cached_package_dir), rebuild_reason=rebuild_reason, package_quality=package_quality, modify_original_clone=_state.modify_original_clone_mode)
                return
        _state._alignment_d3d11_record_cache_lookup_result_helper(_state.alignment_d3d11_state, cache_key)
        mesh_edit_raw_package = _state._mesh_edit_raw_preview_active_value()
        package_quality_key = str(package_quality).strip().lower()
        worker_use_textures = bool(getattr(settings, 'use_textures_by_default', True))
        worker_high_quality_textures = bool(worker_use_textures and high_quality_textures)
        worker_enable_material_combiner = bool(worker_use_textures and enable_material_combiner)
        worker_original_reference_material_parity = bool(worker_use_textures)
        geometry_signature = _state._alignment_d3d11_geometry_cache_key(model, settings, display_mode=requested_display_mode)
        preview_cache_root = _state.self.archive_cache_root / 'd3d11_preview_cache' / _state.alignment_dialog_key_hash
        worker = _state.AlignmentD3D11PackageWorker(request_id, model, settings, use_textures=worker_use_textures, high_quality_textures=worker_high_quality_textures, enable_material_combiner=worker_enable_material_combiner, original_reference_material_parity=worker_original_reference_material_parity, display_mode=requested_display_mode, editor_workspace='modify_original_alignment' if _state.modify_original_clone_mode else 'mesh_replacement_alignment', package_quality=package_quality, geometry_signature=geometry_signature, reuse_prepared_geometry=bool(geometry_signature), geometry_cache_dir=preview_cache_root / 'geometry', texture_cache_dir=preview_cache_root / 'textures')
        thread = _state.QThread(_state.dialog)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress_changed.connect(_state.alignment_d3d11_package_worker_receiver.handle_progress, _state.Qt.QueuedConnection)
        worker.completed.connect(_state.alignment_d3d11_package_worker_receiver.handle_completed, _state.Qt.QueuedConnection)
        worker.error.connect(_state.alignment_d3d11_package_worker_receiver.handle_error, _state.Qt.QueuedConnection)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(
            _state.alignment_d3d11_package_worker_receiver.handle_thread_finished,
            _state.Qt.QueuedConnection,
        )
        _state._alignment_d3d11_record_package_worker_refs_helper(_state.alignment_d3d11_state, worker=worker, thread=thread)
        loading_detail = _state._alignment_d3d11_package_loading_detail_helper(package_quality=package_quality_key, high_quality_textures=high_quality_textures, mesh_edit_raw_package=mesh_edit_raw_package, fast_geometry_loaded=bool(_state.alignment_d3d11_state.get('fast_geometry_loaded')))
        _state._set_alignment_d3d11_progress(0, f'Preparing preview - {loading_detail}.', request_id=request_id, stage='package', detail=f'Building preview package. quality={package_quality} reason={rebuild_reason} label={label}', active=not live_frame_available)
        preparing_presentation = _state._alignment_d3d11_package_preparing_performance_helper(_state.alignment_d3d11_state, quality_label=_state._alignment_preview_quality_label_helper(_state.alignment_d3d11_state), cache_label=_state._d3d11_cache_event_user_label(_state.alignment_d3d11_state.get('last_cache_event')), rebuild_reason=rebuild_reason)
        _state._set_preview_performance_status_if_ready(preparing_presentation.summary, details=preparing_presentation.details)
        _state._record_runtime_event('mesh_alignment_d3d11_package_worker_started', path=getattr(_state.entry, 'path', ''), dialog_title=_state.dialog_title, request_id=int(request_id or 0), rebuild_reason=rebuild_reason, package_quality=package_quality, display_mode=requested_display_mode, modify_original_clone=_state.modify_original_clone_mode)
        thread.start()
    _state._start_alignment_d3d11_package_worker = _start_alignment_d3d11_package_worker

def _d3d11_package_lifecycle_step_051(_state):

    def _flush_alignment_d3d11_preview_request() -> None:
        if not _state._alignment_dialog_widgets_live():
            return
        model = _state.alignment_d3d11_state.get('queued_model')
        label = str(_state.alignment_d3d11_state.get('queued_label', '') or 'Live alignment preview')
        display_mode = str(_state.alignment_d3d11_state.get('queued_display_mode', '') or _state.preview_mode_combo.currentData() or 'side_by_side')
        reason = str(_state.alignment_d3d11_state.get('queued_reason', '') or 'geometry')
        transform_generation = int(_state.alignment_d3d11_state.get('queued_transform_generation', 0) or 0)
        _state._alignment_d3d11_clear_queued_preview_request_helper(_state.alignment_d3d11_state)
        _state._record_runtime_event('mesh_alignment_d3d11_preview_flush', path=getattr(_state.entry, 'path', ''), dialog_title=_state.dialog_title, model_type=type(model).__name__, display_mode=display_mode, reason=reason, transform_generation=transform_generation, modify_original_clone=_state.modify_original_clone_mode)
        _state._start_alignment_d3d11_package_worker(model, label, transform_generation, display_mode=display_mode, reason=reason)
    _state._flush_alignment_d3d11_preview_request = _flush_alignment_d3d11_preview_request

def _d3d11_package_lifecycle_step_052(_state):

    def _handle_alignment_d3d11_package_ready(request_id: int, package_dir_object: object, prepare_ms: float, package_ms: float) -> None:
        try:
            package_dir = _state.Path(package_dir_object)
        except TypeError:
            return
        drag_reload_stale = _state._alignment_d3d11_drag_reload_stale_helper(_state.alignment_d3d11_state, _state.alignment_d3d11_drag_transaction, _state.alignment_d3d11_drag_generation, _state.alignment_transform_generation, request_id=int(request_id))
        ready_route = _state._alignment_d3d11_package_ready_route_helper(dialog_live=_state._alignment_dialog_widgets_live(), request_id=request_id, current_request_id=_state.alignment_d3d11_state.get('request_id', 0), drag_reload_stale=drag_reload_stale)
        if ready_route.should_drop:
            if ready_route.drop_reason == 'dialog_closing':
                _state._drop_alignment_d3d11_package_reload(package_dir, request_id=int(request_id), reason='dialog_closing')
                return
            if ready_route.drop_reason == 'stale_request':
                _state._drop_alignment_d3d11_package_reload(package_dir, request_id=int(request_id), reason='stale_request')
                return
            _state._drop_alignment_d3d11_package_reload(package_dir, request_id=int(request_id), reason=ready_route.drop_reason)
            return
        if ready_route.should_handle_stale_drag:
            _state._handle_alignment_d3d11_stale_reload(package_dir, request_id=int(request_id), reason='stale_drag')
            return
        if not ready_route.should_accept:
            return
        _state._alignment_d3d11_record_package_timing_helper(_state.alignment_d3d11_state, prepare_ms=prepare_ms, package_ms=package_ms)
        package_metadata = _state._alignment_d3d11_process_request_metadata_helper(_state.alignment_d3d11_state, int(request_id), display_mode_fallback=_state.preview_mode_combo.currentData() or 'side_by_side', package_quality_fallback=_state.alignment_d3d11_state.get('package_quality', 'normal') or 'normal', rebuild_reason_fallback=_state.alignment_d3d11_state.get('last_rebuild_reason', 'geometry') or 'geometry')
        _state._alignment_d3d11_package_cache_put(package_metadata.cache_key, package_dir, display_mode=package_metadata.display_mode, package_quality=package_metadata.package_quality, prepare_ms=float(prepare_ms), package_ms=float(package_ms))
        _state._start_alignment_d3d11_process(package_dir, request_id=int(request_id))
    _state._handle_alignment_d3d11_package_ready = _handle_alignment_d3d11_package_ready

def _d3d11_package_lifecycle_step_053(_state):

    def _handle_alignment_d3d11_package_error(request_id: int, message: str) -> None:
        if not _state._alignment_dialog_widgets_live():
            return
        if int(request_id) != int(_state.alignment_d3d11_state.get('request_id', 0) or 0):
            return
        _state._set_alignment_d3d11_loading(False, f'Preview load failed: {message}')
        package_failed_presentation = _state._alignment_d3d11_package_failed_performance_helper(message)
        _state._set_preview_performance_status_if_ready(package_failed_presentation.summary, details=package_failed_presentation.details)
        _state._clear_source_parts_preview_rebuild_pending_if_ready()
    _state._handle_alignment_d3d11_package_error = _handle_alignment_d3d11_package_error

def _d3d11_package_lifecycle_step_054(_state):

    def _cleanup_alignment_d3d11_package_worker_refs(thread: object=None, worker: object=None) -> None:
        thread = thread if isinstance(thread, _state.QThread) else _state.alignment_d3d11_state.get('thread')
        worker = _state.alignment_d3d11_state.get('worker') if worker is None else worker
        if isinstance(thread, _state.QThread):
            try:
                if not thread.wait(0):
                    _state.QTimer.singleShot(1, lambda target_thread=thread, target_worker=worker: _state._cleanup_alignment_d3d11_package_worker_refs(target_thread, target_worker))
                    return
            except RuntimeError:
                pass
        if _state.alignment_d3d11_state.get('thread') is not thread or _state.alignment_d3d11_state.get('worker') is not worker:
            if isinstance(thread, _state.QThread):
                try:
                    thread.deleteLater()
                except RuntimeError:
                    pass
            return
        _state._alignment_d3d11_clear_package_worker_refs_helper(_state.alignment_d3d11_state)
        if isinstance(thread, _state.QThread):
            try:
                thread.deleteLater()
            except RuntimeError:
                pass
        pending_request = _state._alignment_d3d11_take_pending_request_helper(_state.alignment_d3d11_state, label_fallback='Live alignment preview', display_mode_fallback=str(_state.preview_mode_combo.currentData() or 'side_by_side'))
        pending_model = pending_request['model']
        if _state._alignment_dialog_widgets_live() and _state._alignment_d3d11_preview_active() and isinstance(pending_model, _state.ModelPreviewData):
            pending_label = str(pending_request['label'])
            pending_display_mode = str(pending_request['display_mode'])
            pending_reason = str(pending_request['reason'])
            pending_transform_generation = int(pending_request['transform_generation'])
            _state.QTimer.singleShot(0, lambda model=pending_model, label=pending_label, generation=pending_transform_generation, mode=pending_display_mode, queued_reason=pending_reason: _state._start_alignment_d3d11_package_worker(model, label, generation, display_mode=mode, reason=queued_reason))
    _state._cleanup_alignment_d3d11_package_worker_refs = _cleanup_alignment_d3d11_package_worker_refs

def _d3d11_package_lifecycle_step_055(_state):

    def _start_alignment_d3d11_process(package_dir: Path, *, request_id: int=0) -> None:
        drag_reload_stale = int(request_id or 0) > 0 and _state._alignment_d3d11_drag_reload_stale_helper(_state.alignment_d3d11_state, _state.alignment_d3d11_drag_transaction, _state.alignment_d3d11_drag_generation, _state.alignment_transform_generation, request_id=int(request_id))
        route_state = _state._alignment_d3d11_process_start_route_helper(dialog_live=_state._alignment_dialog_widgets_live(), request_id=request_id, current_request_id=_state.alignment_d3d11_state.get('request_id', 0), drag_active=bool(_state.alignment_d3d11_drag_transaction.get('active')), drag_reload_stale=drag_reload_stale)
        if route_state.should_drop:
            if route_state.drop_reason == 'dialog_closing':
                _state._drop_alignment_d3d11_package_reload(package_dir, request_id=int(request_id or 0), reason='dialog_closing')
                return
            if route_state.drop_reason == 'stale_request':
                _state._drop_alignment_d3d11_package_reload(package_dir, request_id=int(request_id or 0), reason='stale_request')
                return
            _state._drop_alignment_d3d11_package_reload(package_dir, request_id=int(request_id or 0), reason=route_state.drop_reason)
            if route_state.should_pause_loading:
                _state._set_alignment_d3d11_loading(False, route_state.pause_message)
            return
        if route_state.should_handle_stale_drag:
            _state._handle_alignment_d3d11_stale_reload(package_dir, request_id=int(request_id or 0), reason='stale_drag')
            return
        if not route_state.should_start:
            return
        package_metadata = _state._alignment_d3d11_process_request_metadata_helper(
            _state.alignment_d3d11_state,
            int(request_id or 0),
            display_mode_fallback=_state.preview_mode_combo.currentData() or 'side_by_side',
            package_quality_fallback=_state.alignment_d3d11_state.get('package_quality', 'normal') or 'normal',
            rebuild_reason_fallback=_state.alignment_d3d11_state.get('last_rebuild_reason', 'geometry') or 'geometry',
        )
        previous_package = _state.alignment_d3d11_state.get('active_package')
        _state.alignment_d3d11_state['active_package'] = package_dir
        _state.alignment_d3d11_state['active_package_request_id'] = int(request_id or 0)
        _state.alignment_d3d11_state['display_mode'] = package_metadata.display_mode
        _state.alignment_d3d11_state['package_quality'] = package_metadata.package_quality
        _state.preview_stack.setCurrentWidget(_state.alignment_d3d11_preview_page)
        accepted = _state.alignment_d3d11_preview_host.load_package(
            package_dir,
            reset_view=previous_package is None,
        )
        if not accepted:
            _state.alignment_d3d11_state['active_package'] = previous_package
            _state._set_alignment_d3d11_loading(False, '.NET/Vortice Preview rejected the prepared package.')
            _state._cleanup_alignment_d3d11_package(package_dir)
            return
        _state.alignment_d3d11_preview_host.set_display_mode(
            str(_state.preview_mode_combo.currentData() or 'side_by_side')
        )
        _state.alignment_d3d11_preview_host.set_render_tuning(
            _state._current_alignment_preview_render_settings_value()
        )
        if previous_package is not None and previous_package != package_dir:
            _state._cleanup_alignment_d3d11_package(previous_package, delay_ms=5000)
        _state.alignment_d3d11_state['preview_loaded'] = True
        _state._set_alignment_d3d11_progress(
            100,
            '.NET/Vortice preview package accepted.',
            request_id=int(request_id or 0),
            stage='dotnet_resident_load',
            detail=f'reason={package_metadata.rebuild_reason}',
            active=False,
        )
    _state._start_alignment_d3d11_process = _start_alignment_d3d11_process

def _d3d11_package_lifecycle_step_056(_state):

    def _check_alignment_d3d11_start_timeout(expected_status: Path) -> None:
        process = _state.alignment_d3d11_state.get('process')
        timeout_route = _state._alignment_d3d11_start_timeout_route_helper(dialog_live=_state._alignment_dialog_widgets_live(), status_matches=_state.alignment_d3d11_state.get('status_file') == expected_status, process_active=isinstance(process, _state.QProcess) and process.state() != _state.QProcess.NotRunning, status_file_exists=expected_status.is_file())
        if not timeout_route.should_report_timeout:
            return
        _state._set_alignment_d3d11_progress(82, 'Starting .NET/Vortice Preview renderer.', stage='native_start_timeout', detail='.NET/Vortice startup timeout waiting for status.')
        startup_timeout_presentation = _state._alignment_d3d11_startup_timeout_performance_helper()
        _state._set_preview_performance_status_if_ready(startup_timeout_presentation.summary, details=startup_timeout_presentation.details)
    _state._check_alignment_d3d11_start_timeout = _check_alignment_d3d11_start_timeout

def _d3d11_package_lifecycle_step_057(_state):

    def _handle_alignment_d3d11_stderr(process: QProcess) -> None:
        if not _state._alignment_dialog_widgets_live():
            return
        if process is not _state.alignment_d3d11_state.get('process'):
            return
        try:
            chunk = bytes(process.readAllStandardError()).decode('utf-8', errors='replace').strip()
        except RuntimeError:
            return
        if chunk:
            _state._set_alignment_d3d11_loading(False, f'Preview renderer message: {chunk[-300:]}')
    _state._handle_alignment_d3d11_stderr = _handle_alignment_d3d11_stderr

def _d3d11_package_lifecycle_step_058(_state):

    def _handle_alignment_d3d11_error(process: QProcess, error: object) -> None:
        if not _state._alignment_dialog_widgets_live():
            return
        if process is not _state.alignment_d3d11_state.get('process'):
            return
        _state._set_alignment_d3d11_loading(False, f'Preview process error: {error}')
        _state._clear_source_parts_preview_rebuild_pending_if_ready()
    _state._handle_alignment_d3d11_error = _handle_alignment_d3d11_error

def _d3d11_package_lifecycle_step_059(_state):

    def _handle_alignment_d3d11_finished(process: QProcess, exit_code: int, exit_status: object) -> None:
        widgets_live = _state._alignment_dialog_widgets_live()
        finish_route = _state._alignment_d3d11_process_finished_route_helper(current_process=process is _state.alignment_d3d11_state.get('process'), widgets_live=widgets_live, exit_code=exit_code)
        if finish_route.should_ignore:
            return
        if widgets_live:
            _state._poll_alignment_d3d11_status()
        _state._safe_stop_alignment_timer(_state.alignment_d3d11_status_timer)
        package_dir = _state._alignment_d3d11_clear_active_package_helper(_state.alignment_d3d11_state)
        _state._alignment_d3d11_clear_process_status_refs_helper(_state.alignment_d3d11_state)
        _state._cleanup_alignment_d3d11_package(package_dir)
        if finish_route.should_report_error:
            _state._set_alignment_d3d11_loading(False, f'Preview closed with code {int(exit_code)} ({exit_status}).')
            _state._clear_source_parts_preview_rebuild_pending_if_ready()
    _state._handle_alignment_d3d11_finished = _handle_alignment_d3d11_finished

def _d3d11_package_lifecycle_step_060(_state):

    def _poll_alignment_d3d11_status() -> None:
        if not _state._alignment_dialog_widgets_live():
            return
        status_file = _state.alignment_d3d11_state.get('status_file')
        if not isinstance(status_file, _state.Path):
            return
        try:
            stat = status_file.stat()
        except OSError:
            unavailable_route = _state._alignment_d3d11_unavailable_status_route_helper(preview_loaded=bool(_state.alignment_d3d11_state.get('preview_loaded')), loading_stuck=_state._alignment_d3d11_loading_stuck(), reason='missing status file')
            if unavailable_route.action == 'ready':
                _state._set_alignment_d3d11_progress(100, unavailable_route.message, active=False)
            elif unavailable_route.action == 'clear_stuck':
                _state._clear_stuck_alignment_d3d11_loading(unavailable_route.message)
            return
        signature = _state._d3d11_status_file_signature(stat)
        try:
            payload_text = status_file.read_text(encoding='utf-8')
        except (OSError, UnicodeError) as exc:
            read_error_route = _state._alignment_d3d11_status_read_error_route_helper(exc)
            _state._set_alignment_d3d11_loading(False, read_error_route.message)
            return
        if not payload_text.strip():
            empty_route = _state._alignment_d3d11_unavailable_status_route_helper(preview_loaded=bool(_state.alignment_d3d11_state.get('preview_loaded')), loading_stuck=_state._alignment_d3d11_loading_stuck(), reason='empty status file')
            if empty_route.action == 'ready':
                _state._set_alignment_d3d11_progress(100, empty_route.message, active=False)
            elif empty_route.action == 'clear_stuck':
                _state._clear_stuck_alignment_d3d11_loading(empty_route.message)
            return
        if not _state._alignment_d3d11_record_status_payload_helper(_state.alignment_d3d11_state, signature=signature, payload_text=payload_text):
            unchanged_route = _state._alignment_d3d11_unavailable_status_route_helper(preview_loaded=bool(_state.alignment_d3d11_state.get('preview_loaded')), loading_stuck=_state._alignment_d3d11_loading_stuck(), reason='unchanged status file')
            if unchanged_route.action == 'ready':
                _state._set_alignment_d3d11_progress(100, unchanged_route.message, active=False)
            elif unchanged_route.action == 'clear_stuck':
                _state._clear_stuck_alignment_d3d11_loading(unchanged_route.message)
            return
        try:
            payload = _state.json.loads(payload_text)
        except ValueError as exc:
            partial_route = _state._alignment_d3d11_unavailable_status_route_helper(preview_loaded=bool(_state.alignment_d3d11_state.get('preview_loaded')), loading_stuck=_state._alignment_d3d11_loading_stuck(), reason=f'partial status file: {exc}')
            if partial_route.action == 'ready':
                _state._set_alignment_d3d11_progress(100, partial_route.message, active=False)
            elif partial_route.action == 'clear_stuck':
                _state._clear_stuck_alignment_d3d11_loading(partial_route.message)
            return
        if not isinstance(payload, _state.Mapping):
            _state._alignment_d3d11_invalid_status_payload_route_helper()
            return
        event = _state._alignment_d3d11_status_event_helper(payload)
        if event == 'loaded':
            loaded_quality = _state._alignment_d3d11_mark_loaded_package_helper(_state.alignment_d3d11_state)
            active_request_id = int(_state.alignment_d3d11_state.get('active_package_request_id', 0) or 0)
            drag_reload_stale = active_request_id and _state._alignment_d3d11_drag_reload_stale_helper(_state.alignment_d3d11_state, _state.alignment_d3d11_drag_transaction, _state.alignment_d3d11_drag_generation, _state.alignment_transform_generation, request_id=active_request_id)
            drag_active = False
            if bool(_state.alignment_d3d11_drag_transaction.get('active')):
                drag_active = True
            loaded_route = _state._alignment_d3d11_loaded_status_route_helper(loaded_quality=loaded_quality, active_request_id=active_request_id, drag_active=drag_active, drag_reload_stale=bool(drag_reload_stale))
            if loaded_route.pipeline_stage:
                _state._set_alignment_d3d11_pipeline_stage(loaded_route.pipeline_stage, loaded_route.pipeline_detail)
            if loaded_route.should_sync_mesh_edit_preview:
                try:
                    _state._sync_mesh_edit_preview_settings_if_ready()
                except NameError:
                    pass
            if loaded_route.should_defer_for_drag:
                _state._set_alignment_d3d11_progress(100, loaded_route.progress_message, active=False)
                return
            if loaded_route.should_keep_live_transform:
                live_transform_message = loaded_route.progress_message or 'Preview loaded; keeping live transform.'
                _state._reapply_current_global_flip_v_fast_preview()
                _state._replay_alignment_d3d11_fast_transform_if_ready()
                _state._set_alignment_d3d11_progress(100, live_transform_message, active=False)
                return
            _state.alignment_d3d11_preview_host.set_display_mode(str(_state.preview_mode_combo.currentData() or 'side_by_side'))
            _state.alignment_d3d11_preview_host.set_render_tuning(_state._current_alignment_preview_render_settings_value())
            _state._reapply_current_global_flip_v_fast_preview()
            saved_view_state = _state._alignment_d3d11_saved_view_state()
            if saved_view_state:
                _state.alignment_d3d11_preview_host.restore_view_state(saved_view_state)
            if _state._alignment_d3d11_loaded_package_transform_current_helper(_state.alignment_d3d11_state, _state.alignment_transform_generation, request_id=active_request_id):
                _state._clear_alignment_d3d11_fast_transform_state_if_ready(reset_host=True)
            _state._sync_highlight_sets_if_ready()
            _state._replay_alignment_d3d11_fast_transform_if_ready()
            channel_debug = _state.self._archive_material_channel_debug_from_package(_state.alignment_d3d11_state.get('active_package'))
            _state._set_alignment_d3d11_progress(100, loaded_route.progress_message, stage=loaded_route.progress_stage, active=False)
            cache_event = str(_state.alignment_d3d11_state.get('last_cache_event', 'miss') or 'miss')
            cache_label = _state._d3d11_cache_event_user_label(cache_event)
            timing_presentation = _state._alignment_d3d11_loaded_timing_presentation_helper(_state.alignment_d3d11_state, payload, quality_label=_state._alignment_preview_quality_label_helper(_state.alignment_d3d11_state), cache_label=cache_label, channel_debug=channel_debug)
            _state._set_preview_performance_status_if_ready(timing_presentation.summary, details=timing_presentation.details)
            _state._clear_source_parts_preview_rebuild_pending_if_ready()
            if loaded_route.should_queue_archive_parity:
                _state._queue_alignment_archive_parity_upgrade('fast geometry loaded')
        elif event == 'resources_loaded':
            _state._alignment_d3d11_mark_resources_loaded_helper(_state.alignment_d3d11_state)
            resources_route = _state._alignment_d3d11_resources_loaded_status_route_helper(payload)
            _state._set_alignment_d3d11_progress(98, resources_route.message, stage=resources_route.stage, detail=resources_route.detail, active=resources_route.active)
            if resources_route.waiting_for_visible_panel:
                return
        elif event == 'loading':
            loading_route = _state._alignment_d3d11_loading_status_route_helper(payload, preview_loaded=bool(_state.alignment_d3d11_state.get('preview_loaded')), loading_stuck=_state._alignment_d3d11_loading_stuck())
            message = loading_route.message
            if loading_route.action == 'tooltip':
                _state.alignment_d3d11_preview_status_label.setToolTip(message)
                return
            if loading_route.action == 'clear_stuck':
                _state._clear_stuck_alignment_d3d11_loading('stale loading status')
                return
            _state._set_alignment_d3d11_progress(loading_route.progress_percent, message, stage=loading_route.stage, detail=message)
        elif event == 'error':
            message = _state._alignment_d3d11_renderer_error_message_helper(payload.get('message', ''))
            error_route = _state._alignment_d3d11_error_status_route_helper(message)
            if error_route.should_mark_preview_unloaded:
                _state._alignment_d3d11_mark_preview_unloaded_helper(_state.alignment_d3d11_state)
            _state._set_alignment_d3d11_loading(False, f'Preview load failed: {error_route.message}')
            renderer_error_presentation = _state._alignment_d3d11_renderer_error_performance_helper(error_route.performance_message)
            _state._set_preview_performance_status_if_ready(renderer_error_presentation.summary, details=renderer_error_presentation.details)
            if error_route.should_clear_pending_rebuild:
                _state._clear_source_parts_preview_rebuild_pending_if_ready()
        elif event == 'closed':
            closed_route = _state._alignment_d3d11_closed_status_route_helper(_state.alignment_preview_control_text['d3d11_closed_status'])
            if closed_route.should_mark_preview_unloaded:
                _state._alignment_d3d11_mark_preview_unloaded_helper(_state.alignment_d3d11_state)
            _state._set_alignment_d3d11_loading(False, closed_route.message)
            if closed_route.should_clear_pending_rebuild:
                _state._clear_source_parts_preview_rebuild_pending_if_ready()
    _state._poll_alignment_d3d11_status = _poll_alignment_d3d11_status

def _d3d11_package_lifecycle_step_061(_state):
    _state._factory_result_values.update({'_apply_source_material_texture_overrides_to_ui_texture_sets': _state._apply_source_material_texture_overrides_to_ui_texture_sets, '_alignment_d3d11_preview_active': _state._alignment_d3d11_preview_active, '_alignment_d3d11_editor_ids_for_source_indices': _state._alignment_d3d11_editor_ids_for_source_indices, '_alignment_d3d11_source_indices_for_editor_id': _state._alignment_d3d11_source_indices_for_editor_id, '_alignment_mesh_edit_tab_active': _state._alignment_mesh_edit_tab_active, '_reapply_global_flip_v_fast_preview': _state._reapply_global_flip_v_fast_preview, '_reapply_current_global_flip_v_fast_preview': _state._reapply_current_global_flip_v_fast_preview, '_try_apply_global_flip_v_fast_preview': _state._try_apply_global_flip_v_fast_preview, '_alignment_default_d3d11_editor_ids': _state._alignment_default_d3d11_editor_ids, '_cleanup_alignment_d3d11_package': _state._cleanup_alignment_d3d11_package, '_alignment_d3d11_invalidate_package_cache': _state._alignment_d3d11_invalidate_package_cache, '_alignment_d3d11_geometry_cache_key': _state._alignment_d3d11_geometry_cache_key, '_alignment_d3d11_preview_cache_signature': _state._alignment_d3d11_preview_cache_signature, '_alignment_d3d11_preview_cache_key': _state._alignment_d3d11_preview_cache_key, '_alignment_d3d11_package_cache_get': _state._alignment_d3d11_package_cache_get, '_alignment_d3d11_package_cache_put': _state._alignment_d3d11_package_cache_put, '_drop_alignment_d3d11_package_reload': _state._drop_alignment_d3d11_package_reload, '_alignment_d3d11_stop_process': _state._alignment_d3d11_stop_process, '_alignment_d3d11_stop_worker': _state._alignment_d3d11_stop_worker, '_shutdown_alignment_d3d11_preview': _state._shutdown_alignment_d3d11_preview, '_safe_shutdown_alignment_d3d11_preview': _state._safe_shutdown_alignment_d3d11_preview, '_side_by_side_alignment_preview_model': _state._side_by_side_alignment_preview_model, '_queue_alignment_d3d11_preview': _state._queue_alignment_d3d11_preview, '_alignment_d3d11_package_quality': _state._alignment_d3d11_package_quality, '_queue_alignment_archive_parity_upgrade': _state._queue_alignment_archive_parity_upgrade, '_queue_latest_alignment_d3d11_rebuild_for_stale_reload': _state._queue_latest_alignment_d3d11_rebuild_for_stale_reload, '_handle_alignment_d3d11_stale_reload': _state._handle_alignment_d3d11_stale_reload, '_handle_alignment_d3d11_package_progress': _state._handle_alignment_d3d11_package_progress, '_start_alignment_d3d11_package_worker': _state._start_alignment_d3d11_package_worker, '_flush_alignment_d3d11_preview_request': _state._flush_alignment_d3d11_preview_request, '_handle_alignment_d3d11_package_ready': _state._handle_alignment_d3d11_package_ready, '_handle_alignment_d3d11_package_error': _state._handle_alignment_d3d11_package_error, '_cleanup_alignment_d3d11_package_worker_refs': _state._cleanup_alignment_d3d11_package_worker_refs, '_start_alignment_d3d11_process': _state._start_alignment_d3d11_process, '_check_alignment_d3d11_start_timeout': _state._check_alignment_d3d11_start_timeout, '_handle_alignment_d3d11_stderr': _state._handle_alignment_d3d11_stderr, '_handle_alignment_d3d11_error': _state._handle_alignment_d3d11_error, '_handle_alignment_d3d11_finished': _state._handle_alignment_d3d11_finished, '_poll_alignment_d3d11_status': _state._poll_alignment_d3d11_status})

STEPS = (
    _d3d11_package_lifecycle_step_046,
    _d3d11_package_lifecycle_step_047,
    _d3d11_package_lifecycle_step_048,
    _d3d11_package_lifecycle_step_049,
    _d3d11_package_lifecycle_step_050,
    _d3d11_package_lifecycle_step_051,
    _d3d11_package_lifecycle_step_052,
    _d3d11_package_lifecycle_step_053,
    _d3d11_package_lifecycle_step_054,
    _d3d11_package_lifecycle_step_055,
    _d3d11_package_lifecycle_step_056,
    _d3d11_package_lifecycle_step_057,
    _d3d11_package_lifecycle_step_058,
    _d3d11_package_lifecycle_step_059,
    _d3d11_package_lifecycle_step_060,
    _d3d11_package_lifecycle_step_061,
)
