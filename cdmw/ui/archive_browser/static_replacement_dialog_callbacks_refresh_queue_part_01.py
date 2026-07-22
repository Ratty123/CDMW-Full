from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_dotnet_presentation import (
    send_resident_presentation_state,
)

def _refresh_queue_step_001(_state):
    _state.Callable = _state.context.get('Callable')
    _state.Dict = _state.context.get('Dict')
    _state.ModelPreviewData = _state.context.get('ModelPreviewData')
    _state.ModelPreviewRenderSettings = _state.context.get('ModelPreviewRenderSettings')
    _state.Optional = _state.context.get('Optional')
    _state.Path = _state.context.get('Path')
    _state.QApplication = _state.context.get('QApplication')
    _state.QProcess = _state.context.get('QProcess')
    _state.QThread = _state.context.get('QThread')
    _state.QTimer = _state.context.get('QTimer')
    _state.QTreeWidget = _state.context.get('QTreeWidget')
    _state.Sequence = _state.context.get('Sequence')
    _state.StaticSourcePartAdjustment = _state.context.get('StaticSourcePartAdjustment')
    _state._alignment_d3d11_clear_fast_transform_state_helper = _state.context.get('_alignment_d3d11_clear_fast_transform_state_helper')
    _state._alignment_d3d11_invalidate_package_cache = _state.context.get('_alignment_d3d11_invalidate_package_cache')
    _state._alignment_d3d11_mark_rebuild_reason_helper = _state.context.get('_alignment_d3d11_mark_rebuild_reason_helper')
    _state._alignment_d3d11_mark_transform_changed_helper = _state.context.get('_alignment_d3d11_mark_transform_changed_helper')
    _state._alignment_d3d11_package_refresh_in_flight_helper = _state.context.get('_alignment_d3d11_package_refresh_in_flight_helper')
    _state._alignment_d3d11_preview_active = _state.context.get('_alignment_d3d11_preview_active')
    _state._alignment_d3d11_selection_highlight_performance_helper = _state.context.get('_alignment_d3d11_selection_highlight_performance_helper')
    _state._alignment_d3d11_stop_worker = _state.context.get('_alignment_d3d11_stop_worker')
    _state._alignment_dialog_widgets_live = _state.context.get('_alignment_dialog_widgets_live')
    _state._alignment_mesh_edit_tab_active = _state.context.get('_alignment_mesh_edit_tab_active')
    _state._alignment_preview_background_source_face_limit_for_total = _state.context.get('_alignment_preview_background_source_face_limit_for_total')
    _state._alignment_preview_is_interactive_helper = _state.context.get('_alignment_preview_is_interactive_helper')
    _state._alignment_preview_requested_source_indices_helper = _state.context.get('_alignment_preview_requested_source_indices_helper')
    _state._alignment_preview_selected_source_face_limit_for_total = _state.context.get('_alignment_preview_selected_source_face_limit_for_total')
    _state._alignment_preview_source_face_limit_for_counts = _state.context.get('_alignment_preview_source_face_limit_for_counts')
    _state._alignment_preview_source_face_total_helper = _state.context.get('_alignment_preview_source_face_total_helper')
    _state._alignment_preview_widget_render_settings_helper = _state.context.get('_alignment_preview_widget_render_settings_helper')
    _state._auto_fit_tree_columns_helper = _state.context.get('_auto_fit_tree_columns_helper')
    _state._capture_static_preview_baked_transform_state_helper = _state.context.get('_capture_static_preview_baked_transform_state_helper')
    _state._configure_alignment_tree_helper = _state.context.get('_configure_alignment_tree_helper')
    _state._configure_texture_mapping_tree_helper = _state.context.get('_configure_texture_mapping_tree_helper')
    _state._current_alignment_preview_render_settings = _state.context.get('_current_alignment_preview_render_settings')
    _state._current_alignment_transform_generation_helper = _state.context.get('_current_alignment_transform_generation_helper')
    _state._get_preview_render_settings = _state.context.get('_get_preview_render_settings')
    _state._fit_tree_height_to_rows_helper = _state.context.get('_fit_tree_height_to_rows_helper')
    _state._install_tree_column_autofit_helper = _state.context.get('_install_tree_column_autofit_helper')
    _state._material_edit_refresh_queued_performance_helper = _state.context.get('_material_edit_refresh_queued_performance_helper')
    _state._material_edit_refresh_queued_progress_message_helper = _state.context.get('_material_edit_refresh_queued_progress_message_helper')
    _state._material_edit_refresh_running_performance_helper = _state.context.get('_material_edit_refresh_running_performance_helper')
    _state._material_edit_refresh_running_progress_message_helper = _state.context.get('_material_edit_refresh_running_progress_message_helper')
    _state._mesh_edit_raw_preview_active_helper = _state.context.get('_mesh_edit_raw_preview_active_helper')
    _state._mesh_edit_raw_preview_initial_state_helper = _state.context.get('_mesh_edit_raw_preview_initial_state_helper')
    _state._queue_alignment_post_open_task_helper = _state.context.get('_queue_alignment_post_open_task_helper')
    _state._queue_material_edit_refresh_state_helper = _state.context.get('_queue_material_edit_refresh_state_helper')
    _state._queue_source_material_plan_refresh_state_helper = _state.context.get('_queue_source_material_plan_refresh_state_helper')
    _state._record_runtime_event = _state.context.get('_record_runtime_event')
    _state._refresh_source_material_plan = _state.context.get('_refresh_source_material_plan')
    _state._run_alignment_post_open_tasks_helper = _state.context.get('_run_alignment_post_open_tasks_helper')
    _state._safe_stop_alignment_timer = _state.context.get('_safe_stop_alignment_timer')
    _state._set_alignment_d3d11_progress = _state.context.get('_set_alignment_d3d11_progress')
    _state._set_preview_performance_status = _state.context.get('_set_preview_performance_status')
    _state._source_part_transform_values_helper = _state.context.get('_source_part_transform_values_helper')
    _state._source_parts_selection_pending_presentation_helper = _state.context.get('_source_parts_selection_pending_presentation_helper')
    _state._spinbox_transform_values_helper = _state.context.get('_spinbox_transform_values_helper')
    _state._static_preview_batch_queue_request_helper = _state.context.get('_static_preview_batch_queue_request_helper')
    _state._sync_highlight_sets = _state.context.get('_sync_highlight_sets')
    _state._take_material_edit_refresh_state_helper = _state.context.get('_take_material_edit_refresh_state_helper')
    _state._take_source_material_plan_refresh_state_helper = _state.context.get('_take_source_material_plan_refresh_state_helper')
    _state.alignment_d3d11_drag_transaction = _state.context.get('alignment_d3d11_drag_transaction') or {}
    _state.alignment_d3d11_preview_host = _state.context.get('alignment_d3d11_preview_host')
    _state.alignment_d3d11_reload_timer = _state.context.get('alignment_d3d11_reload_timer')
    _state.alignment_d3d11_state = _state.context.get('alignment_d3d11_state')
    _state.alignment_post_open_state = _state.context.get('alignment_post_open_state')
    _state.alignment_post_open_tasks = _state.context.get('alignment_post_open_tasks')
    _state.alignment_transform_generation = _state.context.get('alignment_transform_generation')
    _state.alignment_tree_event_filters = _state.context.get('alignment_tree_event_filters')
    _state.control_tabs = _state.context.get('control_tabs')
    _state.defer_original_texture_preview = _state.context.get('defer_original_texture_preview')
    _state.dialog = _state.context.get('dialog')
    _state.dialog_title = _state.context.get('dialog_title')
    _state.entry = _state.context.get('entry')
    _state.make_tree_columns_persistent = _state.context.get('make_tree_columns_persistent')
    _state.material_edit_refresh_state = _state.context.get('material_edit_refresh_state')
    _state.material_edit_refresh_timer = _state.context.get('material_edit_refresh_timer')
    _state.mesh_edit_enabled_checkbox = _state.context.get('mesh_edit_enabled_checkbox')
    _state.modify_original_clone_mode = _state.context.get('modify_original_clone_mode')
    _state.offset_x_spin = _state.context.get('offset_x_spin')
    _state.offset_y_spin = _state.context.get('offset_y_spin')
    _state.offset_z_spin = _state.context.get('offset_z_spin')
    _state.preview_render_settings = _state.context.get('preview_render_settings')
    _state.replacement_mesh_base_for_mapping = _state.context.get('replacement_mesh_base_for_mapping')
    _state.replacement_mesh_for_mapping = _state.context.get('replacement_mesh_for_mapping')
    _state.rotate_x_spin = _state.context.get('rotate_x_spin')
    _state.rotate_y_spin = _state.context.get('rotate_y_spin')
    _state.rotate_z_spin = _state.context.get('rotate_z_spin')
    _state.scale_x_spin = _state.context.get('scale_x_spin')
    _state.scale_y_spin = _state.context.get('scale_y_spin')
    _state.scale_z_spin = _state.context.get('scale_z_spin')
    _state.selected_source_part = _state.context.get('selected_source_part')
    _state.self = _state.context.get('self')
    _state.setup_layout = _state.context.get('setup_layout')
    _state.source_geometry_revision = _state.context.get('source_geometry_revision')
    _state.source_material_plan_refresh_state = _state.context.get('source_material_plan_refresh_state')
    _state.source_material_plan_refresh_timer = _state.context.get('source_material_plan_refresh_timer')
    _state.source_part_adjustments = _state.context.get('source_part_adjustments')
    _state.source_parts_apply_state = _state.context.get('source_parts_apply_state')
    _state.static_preview_baked_transform_state = _state.context.get('static_preview_baked_transform_state')

def _refresh_queue_step_002(_state):
    _state.static_preview_batch_state = _state.context.get('static_preview_batch_state')
    _state.static_preview_geometry_cache = _state.context.get('static_preview_geometry_cache')
    _state.static_preview_interactive_until = _state.context.get('static_preview_interactive_until')
    _state.static_preview_prepared_cache = _state.context.get('static_preview_prepared_cache')
    _state.static_preview_refresh_timer = _state.context.get('static_preview_refresh_timer')
    _state.static_preview_settle_timer = _state.context.get('static_preview_settle_timer')
    _state.texture_material_plan_loaded = _state.context.get('texture_material_plan_loaded')
    _state.texture_overrides_dirty = _state.context.get('texture_overrides_dirty')
    _state.textures_tab = _state.context.get('textures_tab')
    _state.time = _state.context.get('time')

def _refresh_queue_step_003(_state):

    def _d3d11_preview_active() -> bool:
        if not callable(_state._alignment_d3d11_preview_active):
            return False
        return bool(_state._alignment_d3d11_preview_active())
    _state._d3d11_preview_active = _d3d11_preview_active

def _refresh_queue_step_004(_state):

    def _queue_alignment_post_open_task(callback: Callable[[], None]) -> None:
        _state._queue_alignment_post_open_task_helper(_state.alignment_post_open_state, _state.alignment_post_open_tasks, callback, schedule=_state.QTimer.singleShot)
    _state._queue_alignment_post_open_task = _queue_alignment_post_open_task

def _refresh_queue_step_005(_state):

    def _run_alignment_post_open_tasks() -> None:
        _state._run_alignment_post_open_tasks_helper(_state.alignment_post_open_state, _state.alignment_post_open_tasks, schedule=_state.QTimer.singleShot)
    _state._run_alignment_post_open_tasks = _run_alignment_post_open_tasks

def _refresh_queue_step_006(_state):

    def _load_original_reference_texture_preview() -> None:
        callback = _state.context.get('_load_original_reference_texture_preview')
        if callable(callback) and callback is not _state._load_original_reference_texture_preview:
            callback()
    _state._load_original_reference_texture_preview = _load_original_reference_texture_preview

def _refresh_queue_step_007(_state):
    _state._global_transform_values = lambda: _state._spinbox_transform_values_helper((_state.offset_x_spin, _state.offset_y_spin, _state.offset_z_spin), (_state.rotate_x_spin, _state.rotate_y_spin, _state.rotate_z_spin), (_state.scale_x_spin, _state.scale_y_spin, _state.scale_z_spin), catch_runtime=True)
    _state._part_transform_values = lambda source_index: _state._source_part_transform_values_helper(_state.source_part_adjustments, source_index, _state.StaticSourcePartAdjustment)
    _state._current_alignment_transform_generation = lambda: _state._current_alignment_transform_generation_helper(_state.alignment_transform_generation)

def _refresh_queue_step_008(_state):

    def _current_alignment_preview_render_settings_value():
        if callable(_state._current_alignment_preview_render_settings):
            return _state._current_alignment_preview_render_settings()
        if callable(_state._get_preview_render_settings):
            return _state._get_preview_render_settings()
        if _state.preview_render_settings is not None:
            return _state.preview_render_settings
        return _state.self._current_model_preview_render_settings()
    _state._current_alignment_preview_render_settings_value = _current_alignment_preview_render_settings_value

def _refresh_queue_step_009(_state):

    def _mark_alignment_transform_changed() -> int:
        generation = _state._alignment_d3d11_mark_transform_changed_helper(_state.alignment_d3d11_state, _state.alignment_transform_generation)
        _state._safe_stop_alignment_timer(_state.alignment_d3d11_reload_timer)
        stop_worker = _state._alignment_d3d11_stop_worker
        if not callable(stop_worker):
            stop_worker = _state.context.get('_alignment_d3d11_stop_worker')
        if callable(stop_worker):
            stop_worker()
        return generation
    _state._mark_alignment_transform_changed = _mark_alignment_transform_changed

def _refresh_queue_step_010(_state):

    def _clear_alignment_d3d11_fast_transform_state(*, reset_host: bool=False) -> None:
        _state._alignment_d3d11_clear_fast_transform_state_helper(_state.alignment_d3d11_state)
        if reset_host and (not bool(_state.alignment_d3d11_drag_transaction.get('active'))):
            try:
                _state.alignment_d3d11_preview_host.set_alignment_preview_transforms()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
    _state._clear_alignment_d3d11_fast_transform_state = _clear_alignment_d3d11_fast_transform_state

def _refresh_queue_step_011(_state):

    def _alignment_d3d11_package_refresh_in_flight() -> bool:
        queued_model_active = isinstance(_state.alignment_d3d11_state.get('queued_model'), _state.ModelPreviewData)
        pending_model_active = isinstance(_state.alignment_d3d11_state.get('pending_model'), _state.ModelPreviewData)
        thread_active = False
        thread = _state.alignment_d3d11_state.get('thread')
        if isinstance(thread, _state.QThread):
            try:
                thread_active = bool(thread.isRunning())
            except RuntimeError:
                thread_active = True
        process_active = False
        process = _state.alignment_d3d11_state.get('process')
        if isinstance(process, _state.QProcess):
            try:
                process_active = process.state() != _state.QProcess.NotRunning
            except RuntimeError:
                process_active = True
        active_package = _state.alignment_d3d11_state.get('active_package')
        if not callable(_state._alignment_d3d11_package_refresh_in_flight_helper):
            return False
        preview_active = bool(_state._d3d11_preview_active()) if callable(_state._alignment_d3d11_preview_active) else False
        return _state._alignment_d3d11_package_refresh_in_flight_helper(_state.alignment_d3d11_state, preview_active=preview_active, queued_model_active=queued_model_active, pending_model_active=pending_model_active, thread_active=thread_active, process_active=process_active, active_package_exists=isinstance(active_package, _state.Path) and active_package.exists(), committed_transform_generation=int(_state.alignment_transform_generation.get('committed', 0) or 0))
    _state._alignment_d3d11_package_refresh_in_flight = _alignment_d3d11_package_refresh_in_flight

def _refresh_queue_step_012(_state):

    def _capture_static_preview_baked_transform_state(selected_preview_indices: Optional[Sequence[int]]=None, *, transform_generation: Optional[int]=None) -> None:
        capture_generation = int(transform_generation) if transform_generation is not None else _state._current_alignment_transform_generation()
        part_state: _state.Dict[int, object] = {}
        if _state.replacement_mesh_for_mapping is not None:
            for source_index in range(len(getattr(_state.replacement_mesh_for_mapping, 'submeshes', ()) or ())):
                part_state[source_index] = _state._part_transform_values(source_index)
        _state._capture_static_preview_baked_transform_state_helper(_state.static_preview_baked_transform_state, global_values=_state._global_transform_values(), part_values=part_state, selected_preview_indices=selected_preview_indices, transform_generation=capture_generation)
        committed_generation = int(_state.alignment_transform_generation.get('committed', 0) or 0)
        if not bool(_state.alignment_d3d11_drag_transaction.get('active')) and capture_generation >= committed_generation:
            if not _state._alignment_d3d11_package_refresh_in_flight():
                _state._clear_alignment_d3d11_fast_transform_state(reset_host=True)
    _state._capture_static_preview_baked_transform_state = _capture_static_preview_baked_transform_state

def _refresh_queue_step_013(_state):
    _state._alignment_preview_is_interactive = lambda: _state._alignment_preview_is_interactive_helper(_state.static_preview_interactive_until)
    _state._mesh_edit_raw_preview_active = lambda: _state._mesh_edit_raw_preview_active_helper(_state.mesh_edit_enabled_checkbox, _state._alignment_mesh_edit_tab_active)

def _refresh_queue_step_014(_state):

    def _mesh_edit_enabled_checked() -> bool:
        is_checked = getattr(_state.mesh_edit_enabled_checkbox, 'isChecked', None)
        if not callable(is_checked):
            return False
        try:
            return bool(is_checked())
        except RuntimeError:
            return False
    _state._mesh_edit_enabled_checked = _mesh_edit_enabled_checked

def _refresh_queue_step_015(_state):
    _state.mesh_edit_raw_preview_state = _state._mesh_edit_raw_preview_initial_state_helper()

def _refresh_queue_step_016(_state):

    def _alignment_preview_widget_render_settings() -> ModelPreviewRenderSettings:
        settings = _state._current_alignment_preview_render_settings_value()
        return _state._alignment_preview_widget_render_settings_helper(settings, interactive=_state._alignment_preview_is_interactive())
    _state._alignment_preview_widget_render_settings = _alignment_preview_widget_render_settings

def _refresh_queue_step_017(_state):

    def _alignment_preview_source_face_limit() -> int:
        if _state._mesh_edit_enabled_checked():
            return 0
        mesh = _state.replacement_mesh_for_mapping or _state.replacement_mesh_base_for_mapping
        if mesh is None:
            return 0
        submesh_face_counts = [len(getattr(submesh, 'faces', ()) or ()) for submesh in getattr(mesh, 'submeshes', ()) or () if len(getattr(submesh, 'faces', ()) or ()) > 0]
        appended_geometry = 0
        if _state.modify_original_clone_mode:
            appended_geometry = int(_state.source_geometry_revision.get('value', 0) or 0)
        try:
            d3d11_normal_active = _state._d3d11_preview_active()
        except NameError:
            d3d11_normal_active = False
        return _state._alignment_preview_source_face_limit_for_counts(tuple(submesh_face_counts), modify_original_clone_mode=bool(_state.modify_original_clone_mode), appended_geometry=appended_geometry, d3d11_normal_active=bool(d3d11_normal_active), interactive=_state._alignment_preview_is_interactive())
    _state._alignment_preview_source_face_limit = _alignment_preview_source_face_limit

def _refresh_queue_step_018(_state):

    def _alignment_preview_selected_source_face_limit(source_indices: Sequence[int]) -> int:
        if _state._mesh_edit_enabled_checked():
            return 0
        mesh = _state.replacement_mesh_for_mapping or _state.replacement_mesh_base_for_mapping
        if mesh is None:
            return _state._alignment_preview_source_face_limit()
        requested_indices = _state._alignment_preview_requested_source_indices_helper(mesh, source_indices)
        if not requested_indices:
            return _state._alignment_preview_source_face_limit()
        total_faces = _state._alignment_preview_source_face_total_helper(mesh, requested_indices)
        selected_source_index = int(_state.selected_source_part.get('index', -1))
        selected_requested = selected_source_index in requested_indices
        return _state._alignment_preview_selected_source_face_limit_for_total(total_faces, selected_requested=selected_requested, interactive=_state._alignment_preview_is_interactive(), fallback_limit=_state._alignment_preview_source_face_limit())
    _state._alignment_preview_selected_source_face_limit = _alignment_preview_selected_source_face_limit

def _refresh_queue_step_019(_state):

    def _alignment_preview_background_source_face_limit(source_indices: Sequence[int]) -> int:
        if _state._mesh_edit_enabled_checked() and callable(_state._alignment_mesh_edit_tab_active) and _state._alignment_mesh_edit_tab_active():
            return 0
        mesh = _state.replacement_mesh_for_mapping or _state.replacement_mesh_base_for_mapping
        if mesh is None:
            return _state._alignment_preview_source_face_limit()
        requested_indices = _state._alignment_preview_requested_source_indices_helper(mesh, source_indices)
        if not requested_indices:
            return _state._alignment_preview_source_face_limit()
        total_faces = _state._alignment_preview_source_face_total_helper(mesh, requested_indices)
        return _state._alignment_preview_background_source_face_limit_for_total(total_faces, interactive=_state._alignment_preview_is_interactive(), fallback_limit=_state._alignment_preview_source_face_limit())
    _state._alignment_preview_background_source_face_limit = _alignment_preview_background_source_face_limit

def _refresh_queue_step_020(_state):

    def _configure_alignment_tree(tree: QTreeWidget, widths: Sequence[int], *, max_height: int=0, stretch_columns: Sequence[int]=(), persist_key: str='') -> None:
        _state._configure_alignment_tree_helper(tree, widths, max_height=max_height, stretch_columns=stretch_columns, persist_key=persist_key, settings=_state.self.settings, save_callback=_state.self.schedule_settings_save, persist_columns=_state.make_tree_columns_persistent)
    _state._configure_alignment_tree = _configure_alignment_tree

def _refresh_queue_step_021(_state):

    def _configure_texture_mapping_tree(tree: QTreeWidget, *, persist_key: str='') -> None:
        _state._configure_texture_mapping_tree_helper(tree, persist_key=persist_key, settings=_state.self.settings, save_callback=_state.self.schedule_settings_save, persist_columns=_state.make_tree_columns_persistent)
    _state._configure_texture_mapping_tree = _configure_texture_mapping_tree

def _refresh_queue_step_022(_state):

    def _fit_alignment_tree_height_to_rows(tree: QTreeWidget, *, minimum: int, screen_margin: int, maximum: int=0) -> None:
        _state._fit_tree_height_to_rows_helper(tree, minimum=minimum, screen_margin=screen_margin, maximum=maximum, screen_provider=lambda: _state.dialog.screen() or _state.self.screen() or _state.QApplication.primaryScreen())
    _state._fit_alignment_tree_height_to_rows = _fit_alignment_tree_height_to_rows

def _refresh_queue_step_023(_state):

    def _auto_fit_alignment_tree_columns(tree: QTreeWidget, minimums: Sequence[int], maximums: Sequence[int], *, expand_column: int=-1, expand_columns: Sequence[int]=()) -> None:
        _state._auto_fit_tree_columns_helper(tree, minimums, maximums, expand_column=expand_column, expand_columns=expand_columns)
    _state._auto_fit_alignment_tree_columns = _auto_fit_alignment_tree_columns

def _refresh_queue_step_024(_state):

    def _install_alignment_tree_column_autofit(tree: QTreeWidget, minimums: Sequence[int], maximums: Sequence[int], *, expand_column: int=-1, expand_columns: Sequence[int]=()) -> None:
        _state._install_tree_column_autofit_helper(tree, minimums, maximums, expand_column=expand_column, expand_columns=expand_columns, event_filters=_state.alignment_tree_event_filters)
    _state._install_alignment_tree_column_autofit = _install_alignment_tree_column_autofit

def _refresh_queue_step_025(_state):

    def _mark_alignment_d3d11_rebuild_reason(reason: str) -> None:
        _state._alignment_d3d11_mark_rebuild_reason_helper(_state.alignment_d3d11_state, reason)
    _state._mark_alignment_d3d11_rebuild_reason = _mark_alignment_d3d11_rebuild_reason

def _refresh_queue_step_026(_state):

    def _active_mesh_edit_preview_queue_blocked(kind: str, event: str) -> bool:
        if _state._mesh_edit_enabled_checked() and callable(_state._alignment_mesh_edit_tab_active) and _state._alignment_mesh_edit_tab_active():
            message = f'Active Mesh Editor static preview {kind} is disabled; .NET/Vortice preview payloads are required.'
            _state._record_runtime_event(event, path=getattr(_state.entry, 'path', ''), dialog_title=_state.dialog_title, reason=message)
            _state.self.set_status_message(message, error=True)
            return True
        return False
    _state._active_mesh_edit_preview_queue_blocked = _active_mesh_edit_preview_queue_blocked

def _refresh_queue_step_027(_state):

    def _queue_static_preview_refresh(*_args: object) -> None:
        resident_getter = getattr(_state.dialog, '_mesh_editor_embedded_presentation_state', None)
        if callable(resident_getter):
            try:
                resident_state = resident_getter()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                resident_state = None
            if isinstance(resident_state, dict):
                send_resident_presentation_state(_state.dialog, resident_state)
        _state._mark_alignment_d3d11_rebuild_reason('geometry')
        if _state._active_mesh_edit_preview_queue_blocked('refresh', 'mesh_edit_static_preview_refresh_blocked'):
            return
        if _state._static_preview_batch_queue_request_helper(_state.static_preview_batch_state, 'refresh'):
            _state._record_runtime_event('mesh_alignment_static_preview_refresh_batched', path=getattr(_state.entry, 'path', ''), dialog_title=_state.dialog_title, modify_original_clone=_state.modify_original_clone_mode)
            return
        _state._record_runtime_event('mesh_alignment_static_preview_refresh_queued', path=getattr(_state.entry, 'path', ''), dialog_title=_state.dialog_title, d3d11_preview_active=bool(_state._d3d11_preview_active()), next_rebuild_reason=str(_state.alignment_d3d11_state.get('next_rebuild_reason', '') or ''), modify_original_clone=_state.modify_original_clone_mode)
        _state.static_preview_refresh_timer.start()
    _state._queue_static_preview_refresh = _queue_static_preview_refresh

def _refresh_queue_step_028(_state):

    def _queue_selection_preview_refresh(*_args: object) -> None:

        def _set_preview_performance_status_if_ready(summary: str, *, details: str='') -> None:
            if callable(_state._set_preview_performance_status):
                _state._set_preview_performance_status(summary, details=details)
        if bool(_state.source_parts_apply_state.get('pending')):
            if callable(_state._sync_highlight_sets):
                _state._sync_highlight_sets()
            reason = str(_state.source_parts_apply_state.get('reason', '') or 'part changes').strip()
            if callable(_state._source_parts_selection_pending_presentation_helper):
                presentation = _state._source_parts_selection_pending_presentation_helper(reason)
                _set_preview_performance_status_if_ready(presentation.performance_summary, details=presentation.performance_details)
            return
        if _state._d3d11_preview_active():
            if callable(_state._sync_highlight_sets):
                _state._sync_highlight_sets()
            if callable(_state._alignment_d3d11_selection_highlight_performance_helper):
                performance = _state._alignment_d3d11_selection_highlight_performance_helper()
                _set_preview_performance_status_if_ready(performance.summary, details=performance.details)
            return
        if callable(_state._sync_highlight_sets):
            _state._sync_highlight_sets()
        _state._queue_static_preview_refresh()
    _state._queue_selection_preview_refresh = _queue_selection_preview_refresh

def _refresh_queue_step_029(_state):

    def _queue_static_preview_rebuild(*_args: object) -> None:
        _state._mark_alignment_d3d11_rebuild_reason('geometry')
        if _state._active_mesh_edit_preview_queue_blocked('rebuild', 'mesh_edit_static_preview_rebuild_blocked'):
            return
        if _state._static_preview_batch_queue_request_helper(_state.static_preview_batch_state, 'rebuild'):
            return
        _state.static_preview_interactive_until['time'] = _state.time.monotonic() + 0.8
        _state.static_preview_settle_timer.start()
        _state.static_preview_refresh_timer.start()
    _state._queue_static_preview_rebuild = _queue_static_preview_rebuild

def _refresh_queue_step_030(_state):

    def _queue_texture_preview_refresh(*_args: object) -> None:
        _state._mark_alignment_d3d11_rebuild_reason('material')
        if _state._active_mesh_edit_preview_queue_blocked('texture refresh', 'mesh_edit_static_preview_texture_refresh_blocked'):
            return
        if _state._static_preview_batch_queue_request_helper(_state.static_preview_batch_state, 'texture'):
            return
        if callable(_state._alignment_d3d11_invalidate_package_cache):
            _state._alignment_d3d11_invalidate_package_cache('material')
        _state.texture_overrides_dirty['dirty'] = True
        _state.static_preview_refresh_timer.start()
    _state._queue_texture_preview_refresh = _queue_texture_preview_refresh

def _refresh_queue_step_031(_state):

    def _queue_texture_uv_preview_refresh(*_args: object) -> None:
        _state._mark_alignment_d3d11_rebuild_reason('texture_uv')
        if _state._active_mesh_edit_preview_queue_blocked('texture UV refresh', 'mesh_edit_static_preview_texture_uv_refresh_blocked'):
            return
        if _state._static_preview_batch_queue_request_helper(_state.static_preview_batch_state, 'texture_uv'):
            return
        _state.static_preview_geometry_cache.clear()
        _state.static_preview_prepared_cache.clear()
        if callable(_state._alignment_d3d11_invalidate_package_cache):
            _state._alignment_d3d11_invalidate_package_cache('texture_uv')
        _state.texture_overrides_dirty['dirty'] = True
        _state.static_preview_refresh_timer.start()
    _state._queue_texture_uv_preview_refresh = _queue_texture_uv_preview_refresh

def _refresh_queue_step_032(_state):

    def _queue_material_edit_refresh(*, refresh_plan: bool=False, force_plan: bool=False, refresh_preview: bool=True, reason: str='material edit') -> None:
        if not _state._alignment_dialog_widgets_live():
            return
        queued_reason = _state._queue_material_edit_refresh_state_helper(_state.material_edit_refresh_state, refresh_plan=refresh_plan, force_plan=force_plan, refresh_preview=refresh_preview, reason=reason)
        _state.texture_overrides_dirty['dirty'] = True
        queued_performance = _state._material_edit_refresh_queued_performance_helper(queued_reason)
        _state._set_preview_performance_status(queued_performance.summary, details=queued_performance.details)
        try:
            _state._set_alignment_d3d11_progress(5, _state._material_edit_refresh_queued_progress_message_helper(queued_reason), stage='material_edit_queued', active=False)
        except RuntimeError:
            pass
        _state.material_edit_refresh_timer.start()
    _state._queue_material_edit_refresh = _queue_material_edit_refresh

def _refresh_queue_step_033(_state):

    def _queue_source_material_plan_refresh(*, force_plan: bool=False, reason: str='material edit') -> None:
        if not _state._alignment_dialog_widgets_live():
            return
        _state._queue_source_material_plan_refresh_state_helper(_state.source_material_plan_refresh_state, force_plan=force_plan, reason=reason)
        _state.source_material_plan_refresh_timer.start()
    _state._queue_source_material_plan_refresh = _queue_source_material_plan_refresh

def _refresh_queue_step_034(_state):

    def _run_source_material_plan_refresh() -> None:
        if not _state._alignment_dialog_widgets_live():
            return
        source_plan_refresh = _state._take_source_material_plan_refresh_state_helper(_state.source_material_plan_refresh_state)
        force_plan = bool(source_plan_refresh['force_plan'])
        reason = str(source_plan_refresh['reason'])
        try:
            material_tab_active = _state.control_tabs.currentWidget() is _state.textures_tab
        except (NameError, RuntimeError):
            material_tab_active = False
        if not material_tab_active:
            _state.texture_material_plan_loaded['loaded'] = False
            _state._record_runtime_event('mesh_alignment_source_material_plan_deferred', path=getattr(_state.entry, 'path', ''), dialog_title=_state.dialog_title, reason=reason, force_plan=force_plan, modify_original_clone=_state.modify_original_clone_mode)
            return
        started_at = _state.time.perf_counter()
        try:
            _state._refresh_source_material_plan(force=force_plan)
        except TypeError:
            _state._refresh_source_material_plan()
        except NameError:
            return
        _state._record_runtime_event('mesh_alignment_source_material_plan_refresh', path=getattr(_state.entry, 'path', ''), dialog_title=_state.dialog_title, reason=reason, force_plan=force_plan, elapsed_ms=int((_state.time.perf_counter() - started_at) * 1000), modify_original_clone=_state.modify_original_clone_mode)
    _state._run_source_material_plan_refresh = _run_source_material_plan_refresh

def _refresh_queue_step_035(_state):

    def _run_material_edit_refresh() -> None:
        if not _state._alignment_dialog_widgets_live():
            return
        material_refresh = _state._take_material_edit_refresh_state_helper(_state.material_edit_refresh_state)
        refresh_plan = bool(material_refresh['refresh_plan'])
        force_plan = bool(material_refresh['force_plan'])
        refresh_preview = bool(material_refresh['refresh_preview'])
        reason = str(material_refresh['reason'])
        started_at = _state.time.perf_counter()
        running_performance = _state._material_edit_refresh_running_performance_helper(reason)
        _state._set_preview_performance_status(running_performance.summary, details=running_performance.details)
        try:
            _state._set_alignment_d3d11_progress(20, _state._material_edit_refresh_running_progress_message_helper(reason), stage='material_edit_refresh', active=False)
        except RuntimeError:
            pass
        if refresh_preview:
            _state._queue_texture_preview_refresh()
        if refresh_plan:
            _state._queue_source_material_plan_refresh(force_plan=force_plan, reason=reason)
        _state._record_runtime_event('mesh_alignment_material_edit_refresh', path=getattr(_state.entry, 'path', ''), dialog_title=_state.dialog_title, reason=reason, refresh_plan=refresh_plan, force_plan=force_plan, refresh_preview=refresh_preview, elapsed_ms=int((_state.time.perf_counter() - started_at) * 1000), modify_original_clone=_state.modify_original_clone_mode, defer_original_texture_preview=_state.defer_original_texture_preview)
    _state._run_material_edit_refresh = _run_material_edit_refresh

def _refresh_queue_step_036(_state):
    _state._factory_result_values.update({'_queue_alignment_post_open_task': _state._queue_alignment_post_open_task, '_run_alignment_post_open_tasks': _state._run_alignment_post_open_tasks, '_load_original_reference_texture_preview': _state._load_original_reference_texture_preview, '_mark_alignment_transform_changed': _state._mark_alignment_transform_changed, '_clear_alignment_d3d11_fast_transform_state': _state._clear_alignment_d3d11_fast_transform_state, '_alignment_d3d11_package_refresh_in_flight': _state._alignment_d3d11_package_refresh_in_flight, '_capture_static_preview_baked_transform_state': _state._capture_static_preview_baked_transform_state, '_alignment_preview_widget_render_settings': _state._alignment_preview_widget_render_settings, '_alignment_preview_source_face_limit': _state._alignment_preview_source_face_limit, '_alignment_preview_selected_source_face_limit': _state._alignment_preview_selected_source_face_limit, '_alignment_preview_background_source_face_limit': _state._alignment_preview_background_source_face_limit, '_configure_alignment_tree': _state._configure_alignment_tree, '_configure_texture_mapping_tree': _state._configure_texture_mapping_tree, '_fit_alignment_tree_height_to_rows': _state._fit_alignment_tree_height_to_rows, '_auto_fit_alignment_tree_columns': _state._auto_fit_alignment_tree_columns, '_install_alignment_tree_column_autofit': _state._install_alignment_tree_column_autofit, '_mark_alignment_d3d11_rebuild_reason': _state._mark_alignment_d3d11_rebuild_reason, '_queue_static_preview_refresh': _state._queue_static_preview_refresh, '_queue_selection_preview_refresh': _state._queue_selection_preview_refresh, '_queue_static_preview_rebuild': _state._queue_static_preview_rebuild, '_queue_texture_preview_refresh': _state._queue_texture_preview_refresh, '_queue_texture_uv_preview_refresh': _state._queue_texture_uv_preview_refresh, '_queue_material_edit_refresh': _state._queue_material_edit_refresh, '_queue_source_material_plan_refresh': _state._queue_source_material_plan_refresh, '_run_source_material_plan_refresh': _state._run_source_material_plan_refresh, '_run_material_edit_refresh': _state._run_material_edit_refresh})

STEPS = (
    _refresh_queue_step_001,
    _refresh_queue_step_002,
    _refresh_queue_step_003,
    _refresh_queue_step_004,
    _refresh_queue_step_005,
    _refresh_queue_step_006,
    _refresh_queue_step_007,
    _refresh_queue_step_008,
    _refresh_queue_step_009,
    _refresh_queue_step_010,
    _refresh_queue_step_011,
    _refresh_queue_step_012,
    _refresh_queue_step_013,
    _refresh_queue_step_014,
    _refresh_queue_step_015,
    _refresh_queue_step_016,
    _refresh_queue_step_017,
    _refresh_queue_step_018,
    _refresh_queue_step_019,
    _refresh_queue_step_020,
    _refresh_queue_step_021,
    _refresh_queue_step_022,
    _refresh_queue_step_023,
    _refresh_queue_step_024,
    _refresh_queue_step_025,
    _refresh_queue_step_026,
    _refresh_queue_step_027,
    _refresh_queue_step_028,
    _refresh_queue_step_029,
    _refresh_queue_step_030,
    _refresh_queue_step_031,
    _refresh_queue_step_032,
    _refresh_queue_step_033,
    _refresh_queue_step_034,
    _refresh_queue_step_035,
    _refresh_queue_step_036,
)
