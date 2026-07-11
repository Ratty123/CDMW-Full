from __future__ import annotations

def _texture_original_texture_material_step_001(_state):
    _state.ARCHIVE_MESH_EXTENSIONS = _state.context.get('ARCHIVE_MESH_EXTENSIONS')
    _state.AlignmentOriginalTexturePreviewWorker = _state.context.get('AlignmentOriginalTexturePreviewWorker')
    _state.ArchiveEntry = _state.context.get('ArchiveEntry')
    _state.DONOR_MODE_OPTIONS = _state.context.get('DONOR_MODE_OPTIONS')
    _state.Dict = _state.context.get('Dict')
    _state.List = _state.context.get('List')
    _state.ModelPreviewData = _state.context.get('ModelPreviewData')
    _state.NativePreviewPanel = _state.context.get('NativePreviewPanel')
    _state.Optional = _state.context.get('Optional')
    _state.Path = _state.context.get('Path')
    _state.QAbstractItemView = _state.context.get('QAbstractItemView')
    _state.QComboBox = _state.context.get('QComboBox')
    _state.QDialog = _state.context.get('QDialog')
    _state.QDialogButtonBox = _state.context.get('QDialogButtonBox')
    _state.QHBoxLayout = _state.context.get('QHBoxLayout')
    _state.QLabel = _state.context.get('QLabel')
    _state.QMessageBox = _state.context.get('QMessageBox')
    _state.QPushButton = _state.context.get('QPushButton')
    _state.QSplitter = _state.context.get('QSplitter')
    _state.QThread = _state.context.get('QThread')
    _state.QTreeWidget = _state.context.get('QTreeWidget')
    _state.QTreeWidgetItem = _state.context.get('QTreeWidgetItem')
    _state.QVBoxLayout = _state.context.get('QVBoxLayout')
    _state.QWidget = _state.context.get('QWidget')
    _state.Qt = _state.context.get('Qt')
    _state.RunCancelled = _state.context.get('RunCancelled')
    _state.Sequence = _state.context.get('Sequence')
    _state.StaticSubmeshMapping = _state.context.get('StaticSubmeshMapping')
    _state.Tuple = _state.context.get('Tuple')
    _state._alignment_d3d11_clear_archive_parity_upgrade_helper = _state.context.get('_alignment_d3d11_clear_archive_parity_upgrade_helper')
    _state._alignment_d3d11_clear_original_texture_worker_refs_helper = _state.context.get('_alignment_d3d11_clear_original_texture_worker_refs_helper')
    _state._alignment_d3d11_next_original_texture_worker_request_id_helper = _state.context.get('_alignment_d3d11_next_original_texture_worker_request_id_helper')
    _state._alignment_d3d11_original_texture_worker_request_current_helper = _state.context.get('_alignment_d3d11_original_texture_worker_request_current_helper')
    _state._alignment_d3d11_record_original_texture_worker_refs_helper = _state.context.get('_alignment_d3d11_record_original_texture_worker_refs_helper')
    _state._alignment_mesh_edit_tab_active = _state.context.get('_alignment_mesh_edit_tab_active')
    _state._alignment_texture_lookup_indexes = _state.context.get('_alignment_texture_lookup_indexes')
    _state._apply_selected_donor_material = _state.context.get('_apply_selected_donor_material')
    _state._attach_model_sidecar_texture_preview_paths = _state.context.get('_attach_model_sidecar_texture_preview_paths')
    _state._attach_model_support_texture_preview_paths = _state.context.get('_attach_model_support_texture_preview_paths')
    _state._attach_model_texture_preview_paths = _state.context.get('_attach_model_texture_preview_paths')
    _state._auto_fit_alignment_tree_columns = _state.context.get('_auto_fit_alignment_tree_columns')
    _state._clear_transform_source_indices = _state.context.get('_clear_transform_source_indices')
    _state._clone_preview_model = _state.context.get('_clone_preview_model')
    _state._donor_material_plan_build_state_helper = _state.context.get('_donor_material_plan_build_state_helper')
    _state._donor_material_plan_item_helper = _state.context.get('_donor_material_plan_item_helper')
    _state._donor_material_plan_tree_size_state_helper = _state.context.get('_donor_material_plan_tree_size_state_helper')
    _state._donor_material_status_text_helper = _state.context.get('_donor_material_status_text_helper')
    _state._donor_mesh_picker_candidates_helper = _state.context.get('_donor_mesh_picker_candidates_helper')
    _state._donor_part_changed = _state.context.get('_donor_part_changed')
    _state._donor_part_rows_helper = _state.context.get('_donor_part_rows_helper')
    _state._donor_part_tree_item_helper = _state.context.get('_donor_part_tree_item_helper')
    _state._donor_texture_binding_display_state_helper = _state.context.get('_donor_texture_binding_display_state_helper')
    _state._donor_texture_binding_item_helper = _state.context.get('_donor_texture_binding_item_helper')
    _state._empty_donor_part_tree_item_helper = _state.context.get('_empty_donor_part_tree_item_helper')
    _state._load_native_preview_core_material_manifest_for_alignment = _state.context.get('_load_native_preview_core_material_manifest_for_alignment')
    _state._mark_alignment_d3d11_rebuild_reason = _state.context.get('_mark_alignment_d3d11_rebuild_reason')
    _state._material_plan_detail_state_helper = _state.context.get('_material_plan_detail_state_helper')
    _state._material_plan_highlight_state_helper = _state.context.get('_material_plan_highlight_state_helper')
    _state._material_plan_item_selection_helper = _state.context.get('_material_plan_item_selection_helper')
    _state._material_route_control_state_helper = _state.context.get('_material_route_control_state_helper')
    _state._material_routing_conflict_messages_helper = _state.context.get('_material_routing_conflict_messages_helper')
    _state._normalize_model_visible_texture_mode = _state.context.get('_normalize_model_visible_texture_mode')
    _state._original_reference_texture_preview_clear_loading_helper = _state.context.get('_original_reference_texture_preview_clear_loading_helper')
    _state._original_reference_texture_preview_error_state_helper = _state.context.get('_original_reference_texture_preview_error_state_helper')
    _state._original_reference_texture_preview_exception_state_helper = _state.context.get('_original_reference_texture_preview_exception_state_helper')
    _state._original_reference_texture_preview_load_start_state_helper = _state.context.get('_original_reference_texture_preview_load_start_state_helper')
    _state._original_texture_preview_toggle_state_helper = _state.context.get('_original_texture_preview_toggle_state_helper')
    _state._populate_combo_options_helper = _state.context.get('_populate_combo_options_helper')
    _state._populate_donor_texture_tree = _state.context.get('_populate_donor_texture_tree')
    _state._queue_selection_preview_refresh = _state.context.get('_queue_selection_preview_refresh')
    _state._queue_static_preview_refresh = _state.context.get('_queue_static_preview_refresh')
    _state._queue_texture_preview_refresh = _state.context.get('_queue_texture_preview_refresh')
    _state._record_runtime_event = _state.context.get('_record_runtime_event')
    _state._refresh_dds_detail_thumbnail = _state.context.get('_refresh_dds_detail_thumbnail')
    _state._refresh_original_reference_preview = _state.context.get('_refresh_original_reference_preview')
    _state._resolve_original_textures = _state.context.get('_resolve_original_textures')
    _state._selected_donor_bindings_for_plan = _state.context.get('_selected_donor_bindings_for_plan')
    _state._selected_donor_bindings_for_plan_helper = _state.context.get('_selected_donor_bindings_for_plan_helper')
    _state._selected_material_target_index_helper = _state.context.get('_selected_material_target_index_helper')
    _state._selected_target_index = _state.context.get('_selected_target_index')
    _state._selection_view_update_kwargs_helper = _state.context.get('_selection_view_update_kwargs_helper')
    _state._set_alignment_d3d11_loading = _state.context.get('_set_alignment_d3d11_loading')
    _state._set_alignment_d3d11_progress = _state.context.get('_set_alignment_d3d11_progress')
    _state._set_mesh_replacement_selection_view = _state.context.get('_set_mesh_replacement_selection_view')
    _state._set_preview_performance_status = _state.context.get('_set_preview_performance_status')
    _state._source_material_names_for_mapping_helper = _state.context.get('_source_material_names_for_mapping_helper')
    _state._sync_highlight_sets = _state.context.get('_sync_highlight_sets')
    _state._target_display_name = _state.context.get('_target_display_name')
    _state._target_material_name_for_index_helper = _state.context.get('_target_material_name_for_index_helper')
    _state._texture_uv_transform_key = _state.context.get('_texture_uv_transform_key')

def _texture_original_texture_material_step_002(_state):
    _state._update_selection_context = _state.context.get('_update_selection_context')
    _state.build_archive_preview_result = _state.context.get('build_archive_preview_result')
    _state.alignment_d3d11_state = _state.context.get('alignment_d3d11_state')
    _state.apply_selected_source_textures_button = _state.context.get('apply_selected_source_textures_button')
    _state.binding = _state.context.get('binding')
    _state.bindings_for_part = _state.context.get('bindings_for_part')
    _state.bindings_for_plan = _state.context.get('bindings_for_plan')
    _state.checked = _state.context.get('checked')
    _state.control_state = _state.context.get('control_state')
    _state.current = _state.context.get('current')
    _state.dds_detail_label = _state.context.get('dds_detail_label')
    _state.dds_detail_panel = _state.context.get('dds_detail_panel')
    _state.detail_html = _state.context.get('detail_html')
    _state.detail_state = _state.context.get('detail_state')
    _state.dialog = _state.context.get('dialog')
    _state.dialog_title = _state.context.get('dialog_title')
    _state.display_state = _state.context.get('display_state')
    _state.donor_apply_button = _state.context.get('donor_apply_button')
    _state.donor_bindings = _state.context.get('donor_bindings')
    _state.donor_bindings_from_profile = _state.context.get('donor_bindings_from_profile')
    _state.donor_buttons = _state.context.get('donor_buttons')
    _state.donor_control_text = _state.context.get('donor_control_text')
    _state.donor_dialog = _state.context.get('donor_dialog')
    _state.donor_entry = _state.context.get('donor_entry')
    _state.donor_header = _state.context.get('donor_header')
    _state.donor_layout = _state.context.get('donor_layout')
    _state.donor_material_group = _state.context.get('donor_material_group')
    _state.donor_material_plan_tree = _state.context.get('donor_material_plan_tree')
    _state.donor_material_plans_by_target = _state.context.get('donor_material_plans_by_target')
    _state.donor_mode_combo = _state.context.get('donor_mode_combo')
    _state.donor_mode_row = _state.context.get('donor_mode_row')
    _state.donor_part_tree = _state.context.get('donor_part_tree')
    _state.donor_preview = _state.context.get('donor_preview')
    _state.donor_right = _state.context.get('donor_right')
    _state.donor_right_layout = _state.context.get('donor_right_layout')
    _state.donor_sidecar_texts = _state.context.get('donor_sidecar_texts')
    _state.donor_splitter = _state.context.get('donor_splitter')
    _state.donor_status_label = _state.context.get('donor_status_label')
    _state.donor_texture_tree = _state.context.get('donor_texture_tree')
    _state.entry = _state.context.get('entry')
    _state.error_state = _state.context.get('error_state')
    _state.exc = _state.context.get('exc')
    _state.exception_state = _state.context.get('exception_state')
    _state.highlight_state = _state.context.get('highlight_state')
    _state.item = _state.context.get('item')
    _state.load_state = _state.context.get('load_state')
    _state.mapping = _state.context.get('mapping')
    _state.mappings = _state.context.get('mappings')
    _state.material_choose_file_button = _state.context.get('material_choose_file_button')
    _state.material_combo_index = _state.context.get('material_combo_index')
    _state.material_do_not_emit_button = _state.context.get('material_do_not_emit_button')
    _state.material_keep_original_button = _state.context.get('material_keep_original_button')
    _state.material_key = _state.context.get('material_key')
    _state.material_name = _state.context.get('material_name')
    _state.material_neutralize_button = _state.context.get('material_neutralize_button')
    _state.material_plan_control_text = _state.context.get('material_plan_control_text')
    _state.material_use_route_source_button = _state.context.get('material_use_route_source_button')
    _state.mesh_entries = _state.context.get('mesh_entries')
    _state.message = _state.context.get('message')
    _state.modify_original_clone_mode = _state.context.get('modify_original_clone_mode')
    _state.native_material_batches = _state.context.get('native_material_batches')
    _state.normalized_visible_texture_mode = _state.context.get('normalized_visible_texture_mode')
    _state.original_dialog_preview = _state.context.get('original_dialog_preview')
    _state.original_mesh_for_mapping = _state.context.get('original_mesh_for_mapping')
    _state.original_reference_preview_model = _state.context.get('original_reference_preview_model')
    _state.original_reference_texture_preview_state = _state.context.get('original_reference_texture_preview_state')
    _state.original_texture_preview_state = _state.context.get('original_texture_preview_state')
    _state.original_texture_worker_receiver = _state.context.get('original_texture_worker_receiver')
    _state.package_root_text = _state.context.get('package_root_text')
    _state.part_item = _state.context.get('part_item')
    _state.part_target_combo = _state.context.get('part_target_combo')
    _state.plan = _state.context.get('plan')
    _state.plan_state = _state.context.get('plan_state')
    _state.preview_model = _state.context.get('preview_model')
    _state._get_preview_render_settings = _state.context.get('_get_preview_render_settings')
    _state.preview_render_settings = _state.context.get('preview_render_settings')
    _state.profile_mode_index = _state.context.get('profile_mode_index')
    _state.progress = _state.context.get('progress')
    _state.rebuild_sidecar_checkbox = _state.context.get('rebuild_sidecar_checkbox')
    _state.replacement_mesh_for_mapping = _state.context.get('replacement_mesh_for_mapping')
    _state.request_id = _state.context.get('request_id')
    _state.row = _state.context.get('row')
    _state.selected_source_highlight_indices = _state.context.get('selected_source_highlight_indices')
    _state.selected_source_part = _state.context.get('selected_source_part')
    _state.selected_target_original_highlight_indices = _state.context.get('selected_target_original_highlight_indices')
    _state.selected_target_slot = _state.context.get('selected_target_slot')
    _state.selected_target_source_highlight_indices = _state.context.get('selected_target_source_highlight_indices')
    _state.selected_texture_plan_source = _state.context.get('selected_texture_plan_source')
    _state.selected_texture_plan_source_state = _state.context.get('selected_texture_plan_source_state')
    _state.selection = _state.context.get('selection')

def _texture_original_texture_material_step_003(_state):
    _state.self = _state.context.get('self')
    _state.sidecar_bindings = _state.context.get('sidecar_bindings')
    _state.sidecar_bindings_for_advanced = _state.context.get('sidecar_bindings_for_advanced')
    _state.sidecar_data = _state.context.get('sidecar_data')
    _state.sidecar_entry = _state.context.get('sidecar_entry')
    _state.sidecar_text = _state.context.get('sidecar_text')
    _state.sidecar_texts_by_basename = _state.context.get('sidecar_texts_by_basename')
    _state.sidecar_texts_by_normalized_path = _state.context.get('sidecar_texts_by_normalized_path')
    _state.size_state = _state.context.get('size_state')
    _state.source_entry = _state.context.get('source_entry')
    _state.stop_event = _state.context.get('stop_event')
    _state.target_index = _state.context.get('target_index')
    _state.target_material_name = _state.context.get('target_material_name')
    _state.texconv_path = _state.context.get('texconv_path')
    _state.texconv_text = _state.context.get('texconv_text')
    _state.texts = _state.context.get('texts')
    _state.texture_entries_by_basename_for_alignment = _state.context.get('texture_entries_by_basename_for_alignment')
    _state.texture_entries_by_normalized_path_for_alignment = _state.context.get('texture_entries_by_normalized_path_for_alignment')
    _state.texture_overrides_dirty = _state.context.get('texture_overrides_dirty')
    _state.texture_sets = _state.context.get('texture_sets')
    _state.texture_transform_group = _state.context.get('texture_transform_group')
    _state.texture_transform_material_combo = _state.context.get('texture_transform_material_combo')
    _state.thread = _state.context.get('thread')
    _state.threading = _state.context.get('threading')
    _state.toggle_state = _state.context.get('toggle_state')
    _state.worker = _state.context.get('worker')
    _state.worker_request_id = _state.context.get('worker_request_id')

def _texture_original_texture_material_step_004(_state):

    def _current_preview_render_settings() -> object:
        if callable(_state._get_preview_render_settings):
            return _state._get_preview_render_settings()
        return _state.preview_render_settings
    _state._current_preview_render_settings = _current_preview_render_settings

def _texture_original_texture_material_step_005(_state):

    def _stop_original_reference_texture_worker() -> None:
        worker = _state.alignment_d3d11_state.get('original_texture_worker')
        if isinstance(worker, _state.AlignmentOriginalTexturePreviewWorker):
            worker.stop()
        thread = _state.alignment_d3d11_state.get('original_texture_thread')
        if isinstance(thread, _state.QThread) and thread.isRunning():
            thread.quit()
            thread.wait(150)
        _state._alignment_d3d11_clear_original_texture_worker_refs_helper(_state.alignment_d3d11_state)
    _state._stop_original_reference_texture_worker = _stop_original_reference_texture_worker

def _texture_original_texture_material_step_006(_state):

    def _cleanup_original_reference_texture_worker_refs() -> None:
        _state._alignment_d3d11_clear_original_texture_worker_refs_helper(_state.alignment_d3d11_state)
    _state._cleanup_original_reference_texture_worker_refs = _cleanup_original_reference_texture_worker_refs

def _texture_original_texture_material_step_007(_state):

    def _handle_original_reference_texture_preview_error(request_id: int, message: str) -> None:
        error_state = _state._original_reference_texture_preview_error_state_helper(_state.original_reference_texture_preview_state, request_current=_state._alignment_d3d11_original_texture_worker_request_current_helper(_state.alignment_d3d11_state, request_id), message=message)
        if not error_state.handled:
            return
        _state._record_runtime_event('mesh_alignment_original_texture_preview_failed', path=getattr(_state.entry, 'path', ''), dialog_title=_state.dialog_title, message=str(message), modify_original_clone=_state.modify_original_clone_mode)
        _state.original_dialog_preview.clear_model(error_state.message)
        _state._set_alignment_d3d11_loading(False, error_state.message)
        _state._set_preview_performance_status(error_state.performance.summary, details=error_state.performance.details)
        _state._alignment_d3d11_clear_archive_parity_upgrade_helper(_state.alignment_d3d11_state)
        _state._mark_alignment_d3d11_rebuild_reason('material')
        _state._queue_static_preview_refresh()
    _state._handle_original_reference_texture_preview_error = _handle_original_reference_texture_preview_error

def _texture_original_texture_material_step_008(_state):

    def _current_archive_original_preview_model() -> object | None:
        if _state.ModelPreviewData is None or _state.ArchiveEntry is None or (not callable(getattr(_state.self, '_same_archive_entry', None))):
            return None
        current_entry = _state.self._current_archive_entry() if callable(getattr(_state.self, '_current_archive_entry', None)) else None
        if not isinstance(current_entry, _state.ArchiveEntry) or not _state.self._same_archive_entry(current_entry, _state.entry):
            return None
        sync_current = getattr(_state.self, '_sync_current_archive_preview_model_from_widget', None)
        if callable(sync_current):
            sync_current()
        current_result = getattr(_state.self, 'current_archive_preview_result', None)
        preview_model = getattr(current_result, 'preview_model', None)
        if not isinstance(preview_model, _state.ModelPreviewData) or not getattr(preview_model, 'meshes', None):
            return None
        clone_archive_preview = getattr(_state.self, '_clone_archive_preview_model', None)
        if callable(clone_archive_preview):
            cloned = clone_archive_preview(preview_model, strip_images=True)
        else:
            cloned = _state._clone_preview_model(preview_model)
        return cloned if isinstance(cloned, _state.ModelPreviewData) else preview_model
    _state._current_archive_original_preview_model = _current_archive_original_preview_model

def _texture_original_texture_material_step_009(_state):

    def _load_original_reference_texture_preview() -> None:
        load_state = _state._original_reference_texture_preview_load_start_state_helper(_state.original_reference_texture_preview_state, has_original_reference_model=_state.original_reference_preview_model is not None)
        if not load_state.should_start:
            return
        _state._set_alignment_d3d11_progress(10, load_state.progress_message, stage='source_textures', detail=load_state.detail)
        _state._set_preview_performance_status(load_state.performance.summary, details=load_state.performance.details)
        try:
            texconv_text = _state.self.texconv_path_edit.text().strip()
            texconv_path = _state.Path(texconv_text).expanduser() if texconv_text else None
            package_root_text = _state.self.archive_package_root_edit.text().strip()
            current_preview_render_settings = _state._current_preview_render_settings()
            normalized_visible_texture_mode = _state._normalize_model_visible_texture_mode(str(getattr(current_preview_render_settings, 'visible_texture_mode', '')))
            current_archive_preview_model = _state._current_archive_original_preview_model()
            companion_entry = _state.self._find_archive_preview_companion_entry(_state.entry) if callable(getattr(_state.self, '_find_archive_preview_companion_entry', None)) else None
            support_texture_slots = _state.self._archive_preview_support_texture_slots(current_preview_render_settings) if callable(getattr(_state.self, '_archive_preview_support_texture_slots', None)) else ('normal', 'material', 'height')
            archive_texture_entries_by_normalized_path = getattr(_state.self, 'archive_entries_by_normalized_path', {})
            archive_texture_entries_by_basename = getattr(_state.self, 'archive_entries_by_basename', {})
            archive_sidecar_entries_by_texture_path = getattr(_state.self, 'archive_sidecar_entries_by_texture_path', {})
            archive_sidecar_entries_by_texture_basename = getattr(_state.self, 'archive_sidecar_entries_by_texture_basename', {})

            def _resolve_original_textures(stop_event: threading.Event) -> tuple[object, int]:
                if stop_event.is_set():
                    raise _state.RunCancelled('Original texture preview cancelled.')
                archive_preview_authoritative = _state.ModelPreviewData is not None and isinstance(current_archive_preview_model, _state.ModelPreviewData)
                preview_model = _state._clone_preview_model(current_archive_preview_model) if archive_preview_authoritative else None
                if preview_model is None and callable(_state.build_archive_preview_result):
                    preview_result = _state.build_archive_preview_result(texconv_path, _state.entry, companion_entry=companion_entry, texture_entries_by_normalized_path=archive_texture_entries_by_normalized_path, texture_entries_by_basename=archive_texture_entries_by_basename, sidecar_entries_by_texture_path=archive_sidecar_entries_by_texture_path, sidecar_entries_by_texture_basename=archive_sidecar_entries_by_texture_basename, visible_texture_mode=normalized_visible_texture_mode, support_texture_slots=support_texture_slots, stop_event=stop_event)
                    preview_candidate = getattr(preview_result, 'preview_model', None)
                    if _state.ModelPreviewData is not None and isinstance(preview_candidate, _state.ModelPreviewData) and getattr(preview_candidate, 'meshes', None):
                        preview_model = _state._clone_preview_model(preview_candidate)
                        archive_preview_authoritative = True
                if preview_model is None:
                    preview_model = _state._clone_preview_model(_state.original_reference_preview_model)
                texture_entries_by_normalized_path_for_alignment, texture_entries_by_basename_for_alignment = _state._alignment_texture_lookup_indexes()
                if stop_event.is_set():
                    raise _state.RunCancelled('Original texture preview cancelled.')
                if not archive_preview_authoritative:
                    if normalized_visible_texture_mode == 'mesh_base_first':
                        _state._attach_model_texture_preview_paths(texconv_path, _state.entry, preview_model, texture_entries_by_normalized_path=texture_entries_by_normalized_path_for_alignment, texture_entries_by_basename=texture_entries_by_basename_for_alignment, sidecar_texts_by_normalized_path=_state.sidecar_texts_by_normalized_path, sidecar_texts_by_basename=_state.sidecar_texts_by_basename)
                    _state._attach_model_sidecar_texture_preview_paths(texconv_path, _state.entry, preview_model, parsed_mesh=_state.original_mesh_for_mapping, sidecar_texture_bindings=_state.sidecar_bindings, visible_texture_mode=normalized_visible_texture_mode, texture_entries_by_normalized_path=texture_entries_by_normalized_path_for_alignment, texture_entries_by_basename=texture_entries_by_basename_for_alignment, sidecar_texts_by_normalized_path=_state.sidecar_texts_by_normalized_path, sidecar_texts_by_basename=_state.sidecar_texts_by_basename)
                    if normalized_visible_texture_mode != 'mesh_base_first':
                        _state._attach_model_texture_preview_paths(texconv_path, _state.entry, preview_model, texture_entries_by_normalized_path=texture_entries_by_normalized_path_for_alignment, texture_entries_by_basename=texture_entries_by_basename_for_alignment, sidecar_texts_by_normalized_path=_state.sidecar_texts_by_normalized_path, sidecar_texts_by_basename=_state.sidecar_texts_by_basename)
                    if _state.sidecar_bindings and normalized_visible_texture_mode == 'mesh_base_first':
                        _state._attach_model_sidecar_texture_preview_paths(texconv_path, _state.entry, preview_model, parsed_mesh=_state.original_mesh_for_mapping, sidecar_texture_bindings=_state.sidecar_bindings, visible_texture_mode='layer_aware_visible', texture_entries_by_normalized_path=texture_entries_by_normalized_path_for_alignment, texture_entries_by_basename=texture_entries_by_basename_for_alignment, sidecar_texts_by_normalized_path=_state.sidecar_texts_by_normalized_path, sidecar_texts_by_basename=_state.sidecar_texts_by_basename, fallback_only=True)
                        _state._attach_model_texture_preview_paths(texconv_path, _state.entry, preview_model, texture_entries_by_normalized_path=texture_entries_by_normalized_path_for_alignment, texture_entries_by_basename=texture_entries_by_basename_for_alignment, sidecar_texts_by_normalized_path=_state.sidecar_texts_by_normalized_path, sidecar_texts_by_basename=_state.sidecar_texts_by_basename, override_existing_base=True, prefer_material_name_for_base=True)
                    if stop_event.is_set():
                        raise _state.RunCancelled('Original texture preview cancelled.')
                    _state._attach_model_support_texture_preview_paths(texconv_path, _state.entry, preview_model, parsed_mesh=_state.original_mesh_for_mapping, sidecar_texture_bindings=_state.sidecar_bindings, texture_entries_by_normalized_path=texture_entries_by_normalized_path_for_alignment, texture_entries_by_basename=texture_entries_by_basename_for_alignment, sidecar_texts_by_normalized_path=_state.sidecar_texts_by_normalized_path, sidecar_texts_by_basename=_state.sidecar_texts_by_basename)
                _state.self._attach_archive_model_preview_images(preview_model)
                native_material_batches = _state._load_native_preview_core_material_manifest_for_alignment(preview_model, package_root_text)
                return (preview_model, native_material_batches)
            _state._stop_original_reference_texture_worker()
            worker_request_id = _state._alignment_d3d11_next_original_texture_worker_request_id_helper(_state.alignment_d3d11_state)
            worker = _state.AlignmentOriginalTexturePreviewWorker(worker_request_id, _resolve_original_textures)
            thread = _state.QThread(_state.dialog)
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.completed.connect(_state.original_texture_worker_receiver.handle_completed, _state.Qt.QueuedConnection)
            worker.error.connect(_state.original_texture_worker_receiver.handle_error, _state.Qt.QueuedConnection)
            worker.finished.connect(thread.quit)
            worker.finished.connect(worker.deleteLater)
            thread.finished.connect(thread.deleteLater)
            thread.finished.connect(_state._cleanup_original_reference_texture_worker_refs)
            _state._alignment_d3d11_record_original_texture_worker_refs_helper(_state.alignment_d3d11_state, worker=worker, thread=thread)
            thread.start()
        except Exception as exc:
            exception_state = _state._original_reference_texture_preview_exception_state_helper(_state.original_reference_texture_preview_state, exc)
            _state._record_runtime_event('mesh_alignment_original_texture_preview_failed', path=getattr(_state.entry, 'path', ''), dialog_title=_state.dialog_title, message=str(exc), modify_original_clone=_state.modify_original_clone_mode)
            _state.original_dialog_preview.clear_model(exception_state.message)
            _state._set_alignment_d3d11_loading(False, exception_state.message)
            _state._set_preview_performance_status(exception_state.performance.summary, details=exception_state.performance.details)
            _state._queue_static_preview_refresh()
            _state._original_reference_texture_preview_clear_loading_helper(_state.original_reference_texture_preview_state)
    _state._load_original_reference_texture_preview = _load_original_reference_texture_preview

def _texture_original_texture_material_step_010(_state):

    def _highlight_texture_plan_item(item: Optional[QTreeWidgetItem]) -> None:
        selection = _state._material_plan_item_selection_helper(item)
        material_name = selection.material_name
        highlight_state = _state._material_plan_highlight_state_helper(has_item=selection.has_item, source_indices=selection.source_indices, target_index=selection.target_index, material_name=material_name, texture_role=selection.texture_role, texture_path=selection.texture_path)
        _state.selected_source_part['index'] = int(highlight_state['selected_source_index'])
        _state.selected_source_highlight_indices.clear()
        _state.selected_source_highlight_indices.update(tuple(highlight_state['source_highlight_indices']))
        _state._clear_transform_source_indices()
        selected_texture_plan_source_state = highlight_state['texture_plan_source']
        _state.selected_texture_plan_source['material_name'] = selected_texture_plan_source_state['material_name']
        _state.selected_texture_plan_source['source_indices'] = selected_texture_plan_source_state['source_indices']
        if material_name:
            try:
                material_key = _state._texture_uv_transform_key(material_name)
                material_combo_index = _state.texture_transform_material_combo.findData(material_key)
                if material_combo_index >= 0:
                    _state.texture_transform_material_combo.setCurrentIndex(material_combo_index)
            except NameError:
                pass
        _state.selected_target_source_highlight_indices.clear()
        _state.selected_target_source_highlight_indices.update(tuple(highlight_state['target_source_highlight_indices']))
        _state.selected_target_original_highlight_indices.clear()
        _state.selected_target_original_highlight_indices.update(tuple(highlight_state['target_original_highlight_indices']))
        _state.selected_target_slot['index'] = int(highlight_state['selected_target_index'])
        _state._sync_highlight_sets()
        _state._refresh_original_reference_preview()
        _state._set_mesh_replacement_selection_view(**_state._selection_view_update_kwargs_helper(highlight_state['selection_view']))
        _state._update_selection_context()
        try:
            control_state = _state._material_route_control_state_helper(has_item=item is not None, material_name=material_name, has_texture_sets=bool(_state.texture_sets), has_sidecar_bindings=bool(_state.sidecar_bindings_for_advanced))
            _state.apply_selected_source_textures_button.setEnabled(control_state.apply_selected_source_textures_enabled)
            _state.material_use_route_source_button.setEnabled(control_state.use_route_source_enabled)
            _state.material_keep_original_button.setEnabled(control_state.keep_original_enabled)
            _state.material_choose_file_button.setEnabled(control_state.choose_file_enabled)
            _state.material_neutralize_button.setEnabled(control_state.neutralize_enabled)
            _state.material_do_not_emit_button.setEnabled(control_state.do_not_emit_enabled)
        except NameError:
            pass
        try:
            detail_html = str(item.data(0, _state.Qt.UserRole + 3) or '') if item is not None else ''
            detail_state = _state._material_plan_detail_state_helper(has_item=item is not None, detail_html=detail_html, material_name=material_name, empty_text=str(_state.material_plan_control_text['dds_detail_select_row']))
            _state.dds_detail_panel.setVisible(detail_state.visible)
            _state.dds_detail_label.setText(detail_state.detail_html)
            _state._refresh_dds_detail_thumbnail(item)
        except NameError:
            pass
        try:
            _state.texture_transform_group.setVisible(detail_state.transform_visible)
        except NameError:
            pass
        _state._queue_selection_preview_refresh()
    _state._highlight_texture_plan_item = _highlight_texture_plan_item

def _texture_original_texture_material_step_011(_state):

    def _source_material_names_for_mapping(mapping: StaticSubmeshMapping) -> List[str]:
        return list(_state._source_material_names_for_mapping_helper(mapping, _state.replacement_mesh_for_mapping, _state.texture_sets))
    _state._source_material_names_for_mapping = _source_material_names_for_mapping

def _texture_original_texture_material_step_012(_state):

    def _material_routing_conflict_messages(mappings: Sequence[StaticSubmeshMapping]) -> List[str]:
        return list(_state._material_routing_conflict_messages_helper(mappings, _state.replacement_mesh_for_mapping, _state.texture_sets))
    _state._material_routing_conflict_messages = _material_routing_conflict_messages

def _texture_original_texture_material_step_013(_state):

    def _refresh_donor_material_plan_tree() -> None:
        _state.donor_material_plan_tree.clear()
        for target_index, plan in sorted(_state.donor_material_plans_by_target.items()):
            _state.donor_material_plan_tree.addTopLevelItem(_state._donor_material_plan_item_helper(int(target_index), plan, target_display_name=_state._target_display_name(int(target_index))))
        size_state = _state._donor_material_plan_tree_size_state_helper(_state.donor_material_plan_tree.topLevelItemCount())
        _state.donor_material_plan_tree.setVisible(size_state.has_rows)
        _state.donor_material_group.setMaximumHeight(size_state.group_max_height)
        _state.donor_material_plan_tree.setMaximumHeight(size_state.tree_max_height)
        _state._auto_fit_alignment_tree_columns(_state.donor_material_plan_tree, (120, 100, 140, 120, 90), (240, 180, 280, 240, 160), expand_columns=(0, 2, 3))
    _state._refresh_donor_material_plan_tree = _refresh_donor_material_plan_tree

def _texture_original_texture_material_step_014(_state):

    def _active_mesh_edit_donor_material_mutation_blocked() -> bool:
        if not (callable(_state._alignment_mesh_edit_tab_active) and _state._alignment_mesh_edit_tab_active()):
            return False
        message = 'Active Mesh Editor donor material routing requires native material execution; Python donor material plan mutation fallback is disabled.'
        set_status_message = getattr(_state.self, 'set_status_message', None)
        if callable(set_status_message):
            set_status_message(message, error=True)
        return True
    _state._active_mesh_edit_donor_material_mutation_blocked = _active_mesh_edit_donor_material_mutation_blocked

def _texture_original_texture_material_step_015(_state):

    def _clear_selected_donor_material_source() -> None:
        target_index = _state._selected_material_target_index_helper(_state._selected_target_index, _state.part_target_combo.currentData)
        if target_index < 0:
            item = _state.donor_material_plan_tree.currentItem()
            try:
                target_index = int(item.data(0, _state.Qt.UserRole)) if item is not None else -1
            except (TypeError, ValueError):
                target_index = -1
        if target_index < 0:
            return
        if _state._active_mesh_edit_donor_material_mutation_blocked():
            return
        _state.donor_material_plans_by_target.pop(target_index, None)
        _state.texture_overrides_dirty['dirty'] = True
        _state._refresh_donor_material_plan_tree()
        _state._queue_texture_preview_refresh()
    _state._clear_selected_donor_material_source = _clear_selected_donor_material_source

def _texture_original_texture_material_step_016(_state):
    _state.donor_material_request_state = {'request_id': 0}

def _texture_original_texture_material_step_017(_state):

    def _invalidate_donor_material_request(*_args: object) -> None:
        _state.donor_material_request_state['request_id'] += 1
    _state._invalidate_donor_material_request = _invalidate_donor_material_request

def _texture_original_texture_material_step_018(_state):
    _state.dialog.destroyed.connect(_state._invalidate_donor_material_request)

def _texture_original_texture_material_step_019(_state):

    def _open_original_material_source_picker() -> None:
        target_index = _state._selected_material_target_index_helper(_state._selected_target_index, _state.part_target_combo.currentData)
        if target_index < 0:
            _state.QMessageBox.information(_state.dialog, str(_state.donor_control_text['dialog_title']), str(_state.donor_control_text['select_target_message']))
            return
        target_material_name = _state._target_material_name_for_index_helper(target_index, _state.original_mesh_for_mapping)
        mesh_entries = _state._donor_mesh_picker_candidates_helper(tuple(getattr(_state.self, 'archive_entries', ()) or ()), _state.entry, same_entry=_state.self._same_archive_entry, mesh_extensions=_state.ARCHIVE_MESH_EXTENSIONS, archive_entry_type=_state.ArchiveEntry)
        if not mesh_entries:
            _state.QMessageBox.information(_state.dialog, str(_state.donor_control_text['dialog_title']), str(_state.donor_control_text['no_mesh_message']))
            return
        donor_entry = _state.self._choose_archive_mesh_source_dialog(_state.dialog, title=str(_state.donor_control_text['dialog_title']), entries=mesh_entries, prompt=str(_state.donor_control_text['picker_prompt']), excluded_entry=_state.entry)
        if not isinstance(donor_entry, _state.ArchiveEntry):
            return
        sidecar_entries = tuple(_state.self._archive_model_sidecar_entries_for_swap(donor_entry))
        request_id = _state.donor_material_request_state['request_id'] + 1
        _state.donor_material_request_state['request_id'] = request_id
        _state.self._run_utility_task(status_message=str(_state.donor_control_text['progress_message']), task=lambda _log, stop_event: _state.load_donor_material_source(donor_entry, sidecar_entries, _state.self.archive_entries_by_basename, stop_event=stop_event), on_complete=lambda result: _state._show_donor_material_source_picker(request_id, target_index, target_material_name, donor_entry, result), on_error=lambda message: _state._handle_donor_material_source_error(request_id, message), task_accepts_cancel=True)
    _state._open_original_material_source_picker = _open_original_material_source_picker

def _texture_original_texture_material_step_020(_state):

    def _handle_donor_material_source_error(request_id: int, message: str) -> None:
        if request_id != _state.donor_material_request_state['request_id']:
            return
        _state.QMessageBox.warning(_state.dialog, str(_state.donor_control_text['dialog_title']), str(message))
    _state._handle_donor_material_source_error = _handle_donor_material_source_error

def _texture_original_texture_material_step_021(_state):

    def _show_donor_material_source_picker(request_id: int, target_index: int, target_material_name: str, donor_entry: ArchiveEntry, result: object) -> None:
        if request_id != _state.donor_material_request_state['request_id']:
            return
        if not isinstance(result, _state.DonorMaterialSourceLoadResult):
            _state._handle_donor_material_source_error(request_id, 'Donor material worker returned invalid data.')
            return
        donor_bindings = result.bindings
        donor_sidecar_texts = dict(result.sidecar_texts)
        donor_bindings_from_profile = result.bindings_from_profile
        donor_dialog = _state.QDialog(_state.dialog)
        donor_dialog.setWindowTitle(f"{_state.donor_control_text['dialog_title']} - {donor_entry.basename}")
        donor_dialog.resize(1180, 720)
        donor_layout = _state.QVBoxLayout(donor_dialog)
        donor_layout.setContentsMargins(8, 8, 8, 8)
        donor_layout.setSpacing(6)
        donor_header = _state.QLabel(f'Target: {_state._target_display_name(target_index)} | Donor: {donor_entry.path}')
        donor_header.setTextInteractionFlags(_state.Qt.TextSelectableByMouse)
        donor_header.setWordWrap(True)
        donor_layout.addWidget(donor_header)
        donor_splitter = _state.QSplitter(_state.Qt.Horizontal)
        donor_preview = _state.NativePreviewPanel(str(_state.donor_control_text['donor_preview_note']), theme_key=_state.self.current_theme_key)
        donor_preview.setMinimumSize(330, 320)
        donor_preview.set_render_settings(_state._current_preview_render_settings())
        donor_preview.clear_model(str(_state.donor_control_text['donor_preview_clear']))
        donor_splitter.addWidget(donor_preview)
        donor_right = _state.QWidget()
        donor_right_layout = _state.QVBoxLayout(donor_right)
        donor_right_layout.setContentsMargins(6, 0, 0, 0)
        donor_right_layout.setSpacing(5)
        donor_part_tree = _state.QTreeWidget()
        donor_part_tree.setHeaderLabels(list(_state.donor_control_text['part_headers']))
        donor_part_tree.setMinimumHeight(160)
        for row in _state._donor_part_rows_helper(tuple(donor_bindings or ())):
            donor_part_tree.addTopLevelItem(_state._donor_part_tree_item_helper(row))
        if donor_part_tree.topLevelItemCount() <= 0:
            donor_part_tree.addTopLevelItem(_state._empty_donor_part_tree_item_helper())
        donor_texture_tree = _state.QTreeWidget()
        donor_texture_tree.setHeaderLabels(list(_state.donor_control_text['texture_headers']))
        donor_texture_tree.setMinimumHeight(240)
        donor_texture_tree.setSelectionMode(_state.QAbstractItemView.ExtendedSelection)

        def _populate_donor_texture_tree(bindings_for_part: Sequence[object]) -> None:
            donor_texture_tree.clear()
            for binding in tuple(bindings_for_part or ()):
                display_state = _state._donor_texture_binding_display_state_helper(binding)
                donor_texture_tree.addTopLevelItem(_state._donor_texture_binding_item_helper(binding, slot_label=display_state.slot_label, parameter_name=display_state.parameter_name, texture_path=display_state.texture_path, state=display_state.state))
            _state._auto_fit_alignment_tree_columns(donor_texture_tree, (90, 130, 220, 160, 100), (160, 230, 380, 260, 180), expand_columns=(2, 3))
        if donor_part_tree.topLevelItemCount() > 0:
            donor_part_tree.setCurrentItem(donor_part_tree.topLevelItem(0))
            _populate_donor_texture_tree(tuple(donor_part_tree.topLevelItem(0).data(0, _state.Qt.UserRole) or ()))

        def _donor_part_changed(current: Optional[QTreeWidgetItem], _previous: Optional[QTreeWidgetItem]) -> None:
            _populate_donor_texture_tree(tuple(current.data(0, _state.Qt.UserRole) if current is not None else ()))
        donor_part_tree.currentItemChanged.connect(_donor_part_changed)
        donor_right_layout.addWidget(_state.QLabel(str(_state.donor_control_text['parts_label'])))
        donor_right_layout.addWidget(donor_part_tree, 0)
        donor_right_layout.addWidget(_state.QLabel(str(_state.donor_control_text['textures_label'])))
        donor_right_layout.addWidget(donor_texture_tree, 1)
        donor_mode_row = _state.QHBoxLayout()
        donor_mode_row.setContentsMargins(0, 0, 0, 0)
        donor_mode_row.setSpacing(5)
        donor_mode_combo = _state.QComboBox()
        _state._populate_combo_options_helper(donor_mode_combo, _state.DONOR_MODE_OPTIONS)
        profile_mode_index = donor_mode_combo.findData('authoritative_recipe')
        if profile_mode_index >= 0:
            donor_mode_combo.setCurrentIndex(profile_mode_index)
        donor_mode_combo.setToolTip(str(_state.donor_control_text['mode_tooltip']))
        donor_apply_button = _state.QPushButton(str(_state.donor_control_text['apply_button']))
        donor_apply_button.setMinimumWidth(0)
        donor_apply_button.setToolTip(str(_state.donor_control_text['apply_button_tooltip']))
        donor_mode_row.addWidget(_state.QLabel(str(_state.donor_control_text['mode_label'])))
        donor_mode_row.addWidget(donor_mode_combo, 1)
        donor_mode_row.addWidget(donor_apply_button)
        donor_right_layout.addLayout(donor_mode_row)
        donor_status_label = _state.QLabel(_state._donor_material_status_text_helper(_state.donor_control_text, donor_bindings_from_profile=donor_bindings_from_profile))
        donor_status_label.setObjectName('HintLabel')
        donor_status_label.setWordWrap(True)
        donor_right_layout.addWidget(donor_status_label)
        donor_splitter.addWidget(donor_right)
        donor_splitter.setStretchFactor(0, 2)
        donor_splitter.setStretchFactor(1, 3)
        donor_layout.addWidget(donor_splitter, 1)
        donor_buttons = _state.QDialogButtonBox(_state.QDialogButtonBox.Close)
        donor_buttons.rejected.connect(donor_dialog.reject)
        donor_layout.addWidget(donor_buttons)

        def _selected_donor_bindings_for_plan() -> Tuple[object, ...]:
            part_item = donor_part_tree.currentItem()
            return _state._selected_donor_bindings_for_plan_helper(tuple((item.data(0, _state.Qt.UserRole) for item in donor_texture_tree.selectedItems() if item.data(0, _state.Qt.UserRole) is not None)), tuple(part_item.data(0, _state.Qt.UserRole) if part_item is not None else ()))

        def _apply_selected_donor_material() -> None:
            bindings_for_plan = _selected_donor_bindings_for_plan()
            plan_state = _state._donor_material_plan_build_state_helper(bindings_for_plan, donor_sidecar_texts, target_material_name=target_material_name, patch_mode=donor_mode_combo.currentData(), sidecar_bindings_for_advanced=tuple(_state.sidecar_bindings_for_advanced or ()))
            if plan_state.message_key == 'select_binding':
                _state.QMessageBox.information(donor_dialog, str(_state.donor_control_text['dialog_title']), str(_state.donor_control_text['select_binding_message']))
                return
            if plan_state.message_key == 'unreadable_sidecar' or plan_state.plan is None:
                _state.QMessageBox.warning(donor_dialog, str(_state.donor_control_text['dialog_title']), str(_state.donor_control_text['unreadable_sidecar_message']))
                return
            if _state._active_mesh_edit_donor_material_mutation_blocked():
                return
            _state.donor_material_plans_by_target[target_index] = plan_state.plan
            _state.rebuild_sidecar_checkbox.setChecked(True)
            _state.texture_overrides_dirty['dirty'] = True
            _state._refresh_donor_material_plan_tree()
            _state._queue_texture_preview_refresh()
            donor_status_label.setText(str(_state.donor_control_text['assigned_status']).format(donor_part_name=plan_state.donor_part_name or 'donor material', target_name=_state._target_display_name(target_index)))
        donor_apply_button.clicked.connect(_apply_selected_donor_material)
        donor_dialog.exec()
    _state._show_donor_material_source_picker = _show_donor_material_source_picker

def _texture_original_texture_material_step_022(_state):

    def _set_original_texture_preview_enabled(checked: bool) -> None:
        toggle_state = _state._original_texture_preview_toggle_state_helper(_state.original_texture_preview_state, _state.original_reference_texture_preview_state, checked, modify_original_clone_mode=_state.modify_original_clone_mode)
        if toggle_state.should_load:
            _state._load_original_reference_texture_preview()
        if toggle_state.should_refresh:
            _state._queue_texture_preview_refresh()
    _state._set_original_texture_preview_enabled = _set_original_texture_preview_enabled

def _texture_original_texture_material_step_023(_state):
    _state._factory_result_values.update({'_stop_original_reference_texture_worker': _state._stop_original_reference_texture_worker, '_cleanup_original_reference_texture_worker_refs': _state._cleanup_original_reference_texture_worker_refs, '_handle_original_reference_texture_preview_error': _state._handle_original_reference_texture_preview_error, '_load_original_reference_texture_preview': _state._load_original_reference_texture_preview, '_highlight_texture_plan_item': _state._highlight_texture_plan_item, '_source_material_names_for_mapping': _state._source_material_names_for_mapping, '_material_routing_conflict_messages': _state._material_routing_conflict_messages, '_refresh_donor_material_plan_tree': _state._refresh_donor_material_plan_tree, '_clear_selected_donor_material_source': _state._clear_selected_donor_material_source, '_open_original_material_source_picker': _state._open_original_material_source_picker, '_set_original_texture_preview_enabled': _state._set_original_texture_preview_enabled})

STEPS = (
    _texture_original_texture_material_step_001,
    _texture_original_texture_material_step_002,
    _texture_original_texture_material_step_003,
    _texture_original_texture_material_step_004,
    _texture_original_texture_material_step_005,
    _texture_original_texture_material_step_006,
    _texture_original_texture_material_step_007,
    _texture_original_texture_material_step_008,
    _texture_original_texture_material_step_009,
    _texture_original_texture_material_step_010,
    _texture_original_texture_material_step_011,
    _texture_original_texture_material_step_012,
    _texture_original_texture_material_step_013,
    _texture_original_texture_material_step_014,
    _texture_original_texture_material_step_015,
    _texture_original_texture_material_step_016,
    _texture_original_texture_material_step_017,
    _texture_original_texture_material_step_018,
    _texture_original_texture_material_step_019,
    _texture_original_texture_material_step_020,
    _texture_original_texture_material_step_021,
    _texture_original_texture_material_step_022,
    _texture_original_texture_material_step_023,
)
