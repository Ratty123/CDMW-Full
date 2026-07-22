from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_dotnet_presentation import (
    send_resident_presentation_state,
)

def _d3d11_package_lifecycle_step_001(_state):
    _state.AlignmentD3D11PackageWorker = _state.context.get('AlignmentD3D11PackageWorker')
    _state.Dict = _state.context.get('Dict')
    _state.MODEL_PREVIEW_BACKGROUND_COLOR = _state.context.get('MODEL_PREVIEW_BACKGROUND_COLOR')
    _state.MODEL_PREVIEW_TEXT_COLOR = _state.context.get('MODEL_PREVIEW_TEXT_COLOR')
    _state.Mapping = _state.context.get('Mapping')
    _state.MeshPreviewCacheSignature = _state.context.get('MeshPreviewCacheSignature')
    _state.ModelPreviewData = _state.context.get('ModelPreviewData')
    _state.ModelPreviewRenderSettings = _state.context.get('ModelPreviewRenderSettings')
    _state.Optional = _state.context.get('Optional')
    _state.Path = _state.context.get('Path')
    _state.QObject = _state.context.get('QObject')
    _state.QProcess = _state.context.get('QProcess')
    _state.QThread = _state.context.get('QThread')
    _state.QTimer = _state.context.get('QTimer')
    _state.Qt = _state.context.get('Qt')
    _state.ReplacementTextureSet = _state.context.get('ReplacementTextureSet')
    _state.Slot = _state.context.get('Slot')
    _state._AlignmentD3D11PackageWorkerReceiver = _state.context.get('_AlignmentD3D11PackageWorkerReceiver')
    _state._active_tab_is_helper = _state.context.get('_active_tab_is_helper')
    _state._alignment_d3d11_active_package_matches_helper = _state.context.get('_alignment_d3d11_active_package_matches_helper')
    _state._alignment_d3d11_active_package_snapshot_helper = _state.context.get('_alignment_d3d11_active_package_snapshot_helper')
    _state._alignment_d3d11_begin_archive_parity_upgrade_helper = _state.context.get('_alignment_d3d11_begin_archive_parity_upgrade_helper')
    _state._alignment_d3d11_begin_package_request_helper = _state.context.get('_alignment_d3d11_begin_package_request_helper')
    _state._alignment_d3d11_cache_display_class_helper = _state.context.get('_alignment_d3d11_cache_display_class_helper')
    _state._alignment_d3d11_cache_key_with_native_reference_helper = _state.context.get('_alignment_d3d11_cache_key_with_native_reference_helper')
    _state._alignment_d3d11_cached_loading_performance_helper = _state.context.get('_alignment_d3d11_cached_loading_performance_helper')
    _state._alignment_d3d11_cached_loading_progress_detail_helper = _state.context.get('_alignment_d3d11_cached_loading_progress_detail_helper')
    _state._alignment_d3d11_cached_renderer_reload_detail_helper = _state.context.get('_alignment_d3d11_cached_renderer_reload_detail_helper')
    _state._alignment_d3d11_cached_reuse_performance_helper = _state.context.get('_alignment_d3d11_cached_reuse_performance_helper')
    _state._alignment_d3d11_clear_active_package_helper = _state.context.get('_alignment_d3d11_clear_active_package_helper')
    _state._alignment_d3d11_clear_archive_parity_upgrade_helper = _state.context.get('_alignment_d3d11_clear_archive_parity_upgrade_helper')
    _state._alignment_d3d11_clear_package_worker_refs_helper = _state.context.get('_alignment_d3d11_clear_package_worker_refs_helper')
    _state._alignment_d3d11_clear_pending_process_retry_helper = _state.context.get('_alignment_d3d11_clear_pending_process_retry_helper')
    _state._alignment_d3d11_clear_process_status_refs_helper = _state.context.get('_alignment_d3d11_clear_process_status_refs_helper')
    _state._alignment_d3d11_clear_queued_preview_request_helper = _state.context.get('_alignment_d3d11_clear_queued_preview_request_helper')
    _state._alignment_d3d11_closed_status_route_helper = _state.context.get('_alignment_d3d11_closed_status_route_helper')
    _state._alignment_d3d11_dirty_flags_for_reason = _state.context.get('_alignment_d3d11_dirty_flags_for_reason')
    _state._alignment_d3d11_drag_reload_stale_helper = _state.context.get('_alignment_d3d11_drag_reload_stale_helper')
    _state._alignment_d3d11_editor_ids_for_source_indices_helper = _state.context.get('_alignment_d3d11_editor_ids_for_source_indices_helper')
    _state._alignment_d3d11_error_status_route_helper = _state.context.get('_alignment_d3d11_error_status_route_helper')
    _state._alignment_d3d11_geometry_cache_key_helper = _state.context.get('_alignment_d3d11_geometry_cache_key_helper')
    _state._alignment_d3d11_host_ready = _state.context.get('_alignment_d3d11_host_ready')
    _state._alignment_d3d11_invalid_status_payload_route_helper = _state.context.get('_alignment_d3d11_invalid_status_payload_route_helper')
    _state._alignment_d3d11_invalidate_package_cache_helper = _state.context.get('_alignment_d3d11_invalidate_package_cache_helper')
    _state._alignment_d3d11_live_frame_available = _state.context.get('_alignment_d3d11_live_frame_available')
    _state._alignment_d3d11_loaded_package_transform_current_helper = _state.context.get('_alignment_d3d11_loaded_package_transform_current_helper')
    _state._alignment_d3d11_loaded_status_route_helper = _state.context.get('_alignment_d3d11_loaded_status_route_helper')
    _state._alignment_d3d11_loaded_timing_presentation_helper = _state.context.get('_alignment_d3d11_loaded_timing_presentation_helper')
    _state._alignment_d3d11_loading_status_route_helper = _state.context.get('_alignment_d3d11_loading_status_route_helper')
    _state._alignment_d3d11_loading_stuck = _state.context.get('_alignment_d3d11_loading_stuck')
    _state._alignment_d3d11_mark_active_cached_package_reused_helper = _state.context.get('_alignment_d3d11_mark_active_cached_package_reused_helper')
    _state._alignment_d3d11_mark_loaded_package_helper = _state.context.get('_alignment_d3d11_mark_loaded_package_helper')
    _state._alignment_d3d11_mark_loading_started_helper = _state.context.get('_alignment_d3d11_mark_loading_started_helper')
    _state._alignment_d3d11_mark_preview_loaded_helper = _state.context.get('_alignment_d3d11_mark_preview_loaded_helper')
    _state._alignment_d3d11_mark_preview_unloaded_helper = _state.context.get('_alignment_d3d11_mark_preview_unloaded_helper')
    _state._alignment_d3d11_mark_resources_loaded_helper = _state.context.get('_alignment_d3d11_mark_resources_loaded_helper')
    _state._alignment_d3d11_material_cache_key_helper = _state.context.get('_alignment_d3d11_material_cache_key_helper')
    _state._alignment_d3d11_model_cache_signature_helper = _state.context.get('_alignment_d3d11_model_cache_signature_helper')
    _state._alignment_d3d11_package_cache_get_helper = _state.context.get('_alignment_d3d11_package_cache_get_helper')
    _state._alignment_d3d11_package_cache_put_helper = _state.context.get('_alignment_d3d11_package_cache_put_helper')
    _state._alignment_d3d11_package_drop_cleanup_state_helper = _state.context.get('_alignment_d3d11_package_drop_cleanup_state_helper')
    _state._alignment_d3d11_package_failed_performance_helper = _state.context.get('_alignment_d3d11_package_failed_performance_helper')
    _state._alignment_d3d11_package_is_cached_helper = _state.context.get('_alignment_d3d11_package_is_cached_helper')
    _state._alignment_d3d11_package_loading_detail_helper = _state.context.get('_alignment_d3d11_package_loading_detail_helper')
    _state._alignment_d3d11_package_preparing_performance_helper = _state.context.get('_alignment_d3d11_package_preparing_performance_helper')
    _state._alignment_d3d11_package_quality_helper = _state.context.get('_alignment_d3d11_package_quality_helper')
    _state._alignment_d3d11_package_ready_route_helper = _state.context.get('_alignment_d3d11_package_ready_route_helper')
    _state._alignment_d3d11_package_start_route_helper = _state.context.get('_alignment_d3d11_package_start_route_helper')
    _state._alignment_d3d11_pending_host_performance_helper = _state.context.get('_alignment_d3d11_pending_host_performance_helper')
    _state._alignment_d3d11_prepare_active_package_helper = _state.context.get('_alignment_d3d11_prepare_active_package_helper')
    _state._alignment_d3d11_process_finished_route_helper = _state.context.get('_alignment_d3d11_process_finished_route_helper')
    _state._alignment_d3d11_process_request_metadata_helper = _state.context.get('_alignment_d3d11_process_request_metadata_helper')
    _state._alignment_d3d11_process_reuse_state_helper = _state.context.get('_alignment_d3d11_process_reuse_state_helper')
    _state._alignment_d3d11_process_start_route_helper = _state.context.get('_alignment_d3d11_process_start_route_helper')
    _state._alignment_d3d11_queue_pending_request_helper = _state.context.get('_alignment_d3d11_queue_pending_request_helper')
    _state._alignment_d3d11_queue_preview_request_helper = _state.context.get('_alignment_d3d11_queue_preview_request_helper')
    _state._alignment_d3d11_queued_latest_preview_reload_detail_helper = _state.context.get('_alignment_d3d11_queued_latest_preview_reload_detail_helper')
    _state._alignment_d3d11_queued_preview_reload_detail_helper = _state.context.get('_alignment_d3d11_queued_preview_reload_detail_helper')
    _state._alignment_d3d11_record_cache_hit_metadata_helper = _state.context.get('_alignment_d3d11_record_cache_hit_metadata_helper')
    _state._alignment_d3d11_record_cache_lookup_result_helper = _state.context.get('_alignment_d3d11_record_cache_lookup_result_helper')
    _state._alignment_d3d11_record_package_request_metadata_helper = _state.context.get('_alignment_d3d11_record_package_request_metadata_helper')
    _state._alignment_d3d11_record_package_timing_helper = _state.context.get('_alignment_d3d11_record_package_timing_helper')
    _state._alignment_d3d11_record_package_worker_refs_helper = _state.context.get('_alignment_d3d11_record_package_worker_refs_helper')
    _state._alignment_d3d11_record_pending_process_retry_helper = _state.context.get('_alignment_d3d11_record_pending_process_retry_helper')
    _state._alignment_d3d11_record_process_ref_helper = _state.context.get('_alignment_d3d11_record_process_ref_helper')
    _state._alignment_d3d11_record_status_payload_helper = _state.context.get('_alignment_d3d11_record_status_payload_helper')
    _state._alignment_d3d11_reload_queued_performance_helper = _state.context.get('_alignment_d3d11_reload_queued_performance_helper')
    _state._alignment_d3d11_remember_request_cache_key_helper = _state.context.get('_alignment_d3d11_remember_request_cache_key_helper')
    _state._alignment_d3d11_remember_request_package_quality_helper = _state.context.get('_alignment_d3d11_remember_request_package_quality_helper')
    _state._alignment_d3d11_renderer_error_message_helper = _state.context.get('_alignment_d3d11_renderer_error_message_helper')
    _state._alignment_d3d11_renderer_error_performance_helper = _state.context.get('_alignment_d3d11_renderer_error_performance_helper')
    _state._alignment_d3d11_renderer_host_restart_performance_helper = _state.context.get('_alignment_d3d11_renderer_host_restart_performance_helper')
    _state._alignment_d3d11_request_reason_helper = _state.context.get('_alignment_d3d11_request_reason_helper')
    _state._alignment_d3d11_reset_material_parity_state_helper = _state.context.get('_alignment_d3d11_reset_material_parity_state_helper')
    _state._alignment_d3d11_reset_request_state_helper = _state.context.get('_alignment_d3d11_reset_request_state_helper')
    _state._alignment_d3d11_resources_loaded_status_route_helper = _state.context.get('_alignment_d3d11_resources_loaded_status_route_helper')
    _state._alignment_d3d11_restore_active_package_helper = _state.context.get('_alignment_d3d11_restore_active_package_helper')
    _state._alignment_d3d11_saved_view_state = _state.context.get('_alignment_d3d11_saved_view_state')
    _state._alignment_d3d11_source_indices_for_editor_id_helper = _state.context.get('_alignment_d3d11_source_indices_for_editor_id_helper')
    _state._alignment_d3d11_stale_package_dropped_detail_helper = _state.context.get('_alignment_d3d11_stale_package_dropped_detail_helper')

def _d3d11_package_lifecycle_step_002(_state):
    _state._alignment_d3d11_stale_package_dropped_performance_helper = _state.context.get('_alignment_d3d11_stale_package_dropped_performance_helper')
    _state._alignment_d3d11_stale_reload_route_helper = _state.context.get('_alignment_d3d11_stale_reload_route_helper')
    _state._alignment_d3d11_start_timeout_route_helper = _state.context.get('_alignment_d3d11_start_timeout_route_helper')
    _state._alignment_d3d11_starting_performance_helper = _state.context.get('_alignment_d3d11_starting_performance_helper')
    _state._alignment_d3d11_startup_timeout_performance_helper = _state.context.get('_alignment_d3d11_startup_timeout_performance_helper')
    _state._alignment_d3d11_status_event_helper = _state.context.get('_alignment_d3d11_status_event_helper')
    _state._alignment_d3d11_status_read_error_route_helper = _state.context.get('_alignment_d3d11_status_read_error_route_helper')
    _state._alignment_d3d11_store_package_cache_helper = _state.context.get('_alignment_d3d11_store_package_cache_helper')
    _state._alignment_d3d11_take_pending_request_helper = _state.context.get('_alignment_d3d11_take_pending_request_helper')
    _state._alignment_d3d11_texture_flip_v_live_performance_helper = _state.context.get('_alignment_d3d11_texture_flip_v_live_performance_helper')
    _state._alignment_d3d11_theme_payload_helper = _state.context.get('_alignment_d3d11_theme_payload_helper')
    _state._alignment_d3d11_unavailable_performance_helper = _state.context.get('_alignment_d3d11_unavailable_performance_helper')
    _state._alignment_d3d11_unavailable_status_route_helper = _state.context.get('_alignment_d3d11_unavailable_status_route_helper')
    _state._alignment_d3d11_waiting_for_preview_panel_detail_helper = _state.context.get('_alignment_d3d11_waiting_for_preview_panel_detail_helper')
    _state._alignment_default_d3d11_editor_ids_helper = _state.context.get('_alignment_default_d3d11_editor_ids_helper')
    _state._alignment_dialog_widgets_live = _state.context.get('_alignment_dialog_widgets_live')
    _state._alignment_file_signature = _state.context.get('_alignment_file_signature')
    _state._alignment_preview_quality_label_helper = _state.context.get('_alignment_preview_quality_label_helper')
    _state._alignment_sample_sequence = _state.context.get('_alignment_sample_sequence')
    _state._alignment_sequence_digest = _state.context.get('_alignment_sequence_digest')
    _state._apply_source_material_texture_overrides_to_texture_sets_helper = _state.context.get('_apply_source_material_texture_overrides_to_texture_sets_helper')
    _state._apply_source_part_role_overrides = _state.context.get('_apply_source_part_role_overrides')
    _state._clear_alignment_d3d11_fast_transform_state = _state.context.get('_clear_alignment_d3d11_fast_transform_state')
    _state._clear_source_parts_preview_rebuild_pending = _state.context.get('_clear_source_parts_preview_rebuild_pending')
    _state._clear_stuck_alignment_d3d11_loading = _state.context.get('_clear_stuck_alignment_d3d11_loading')
    _state._clone_preview_model = _state.context.get('_clone_preview_model')
    _state._combine_preview_models = _state.context.get('_combine_preview_models')
    _state._current_alignment_preview_render_settings = _state.context.get('_current_alignment_preview_render_settings')
    _state._current_alignment_transform_generation = _state.context.get('_current_alignment_transform_generation')
    _state._current_donor_material_plans = _state.context.get('_current_donor_material_plans')
    _state._current_source_material_texture_overrides = _state.context.get('_current_source_material_texture_overrides')
    _state._d3d11_cache_event_user_label = _state.context.get('_d3d11_cache_event_user_label')
    _state._d3d11_status_file_signature = _state.context.get('_d3d11_status_file_signature')
    _state._donor_material_plan_payload_helper = _state.context.get('_donor_material_plan_payload_helper')
    _state._get_preview_render_settings = _state.context.get('_get_preview_render_settings')
    _state._global_flip_v_fast_preview_value_helper = _state.context.get('_global_flip_v_fast_preview_value_helper')
    _state._load_original_reference_texture_preview = _state.context.get('_load_original_reference_texture_preview')
    _state._mark_alignment_d3d11_rebuild_reason = _state.context.get('_mark_alignment_d3d11_rebuild_reason')
    _state._mesh_edit_raw_preview_active = _state.context.get('_mesh_edit_raw_preview_active')
    _state._model_bounds_x = _state.context.get('_model_bounds_x')
    _state._original_reference_texture_preview_archive_parity_state_helper = _state.context.get('_original_reference_texture_preview_archive_parity_state_helper')
    _state._queue_static_preview_refresh = _state.context.get('_queue_static_preview_refresh')
    _state._record_runtime_event = _state.context.get('_record_runtime_event')
    _state._replay_alignment_d3d11_fast_transform = _state.context.get('_replay_alignment_d3d11_fast_transform')
    _state._safe_start_alignment_timer = _state.context.get('_safe_start_alignment_timer')
    _state._safe_stop_alignment_timer = _state.context.get('_safe_stop_alignment_timer')
    _state._set_alignment_d3d11_loading = _state.context.get('_set_alignment_d3d11_loading')
    _state._set_alignment_d3d11_pipeline_stage = _state.context.get('_set_alignment_d3d11_pipeline_stage')
    _state._set_alignment_d3d11_progress = _state.context.get('_set_alignment_d3d11_progress')
    _state._set_preview_performance_status = _state.context.get('_set_preview_performance_status')
    _state._source_index_is_enabled_renderable = _state.context.get('_source_index_is_enabled_renderable')
    _state._sync_highlight_sets = _state.context.get('_sync_highlight_sets')
    _state._sync_mesh_edit_preview_settings = _state.context.get('_sync_mesh_edit_preview_settings')
    _state._texture_uv_fast_preview_record_global_flip_v_helper = _state.context.get('_texture_uv_fast_preview_record_global_flip_v_helper')
    _state._texture_uv_state_has_edits = _state.context.get('_texture_uv_state_has_edits')
    _state._tint_preview_model = _state.context.get('_tint_preview_model')
    _state._translated_preview_model = _state.context.get('_translated_preview_model')
    _state.alignment_d3d11_available = _state.context.get('alignment_d3d11_available')
    _state.alignment_d3d11_drag_generation = _state.context.get('alignment_d3d11_drag_generation')
    _state.alignment_d3d11_drag_transaction = _state.context.get('alignment_d3d11_drag_transaction') or {}
    _state.alignment_d3d11_drag_ui_timer = _state.context.get('alignment_d3d11_drag_ui_timer')
    _state.alignment_d3d11_fast_reload_interval_ms = _state.context.get('alignment_d3d11_fast_reload_interval_ms')
    _state.alignment_d3d11_loading_timer = _state.context.get('alignment_d3d11_loading_timer')
    _state.alignment_d3d11_package_reload_interval_ms = _state.context.get('alignment_d3d11_package_reload_interval_ms')
    _state.alignment_d3d11_preview_host = _state.context.get('alignment_d3d11_preview_host')
    _state.alignment_d3d11_preview_page = _state.context.get('alignment_d3d11_preview_page')
    _state.alignment_d3d11_preview_status_label = _state.context.get('alignment_d3d11_preview_status_label')
    _state.alignment_d3d11_reload_timer = _state.context.get('alignment_d3d11_reload_timer')
    _state.alignment_d3d11_state = _state.context.get('alignment_d3d11_state')
    _state.alignment_d3d11_status_timer = _state.context.get('alignment_d3d11_status_timer')
    _state.alignment_d3d11_texture_uv_fast_state = _state.context.get('alignment_d3d11_texture_uv_fast_state')
    _state.alignment_dialog_key_hash = _state.context.get('alignment_dialog_key_hash')
    _state.alignment_preview_control_text = _state.context.get('alignment_preview_control_text')
    _state.alignment_transform_generation = _state.context.get('alignment_transform_generation') or {}
    _state.control_tabs = _state.context.get('control_tabs')
    _state.dialog = _state.context.get('dialog')
    _state.dialog_title = _state.context.get('dialog_title')
    _state.hashlib = _state.context.get('hashlib')
    _state.json = _state.context.get('json')
    _state.entry = _state.context.get('entry')
    _state.material_authority_preview_signature_state = _state.context.get('material_authority_preview_signature_state')
    _state.mesh_edit_enabled_checkbox = _state.context.get('mesh_edit_enabled_checkbox')
    _state.mesh_edit_tab = _state.context.get('mesh_edit_tab')
    _state.modify_original_clone_mode = _state.context.get('modify_original_clone_mode')
    _state.scene_import_result = _state.context.get('scene_import_result')
    _state.source_skeleton = _state.context.get('source_skeleton')
    _state.original_reference_preview_model = _state.context.get('original_reference_preview_model')
    _state._get_original_reference_preview_model = _state.context.get('_get_original_reference_preview_model')
    _state.original_reference_texture_preview_state = _state.context.get('original_reference_texture_preview_state')
    _state.parts_tab = _state.context.get('parts_tab')
    _state.preview_mode_combo = _state.context.get('preview_mode_combo')
    _state.preview_render_settings = _state.context.get('preview_render_settings')
    _state.preview_renderer_combo = _state.context.get('preview_renderer_combo')
    _state.preview_stack = _state.context.get('preview_stack')
    _state.replacement_mesh_for_mapping = _state.context.get('replacement_mesh_for_mapping')
    _state.self = _state.context.get('self')
    _state.shutil = _state.context.get('shutil')
    _state.source_part_adjustments = _state.context.get('source_part_adjustments')
    _state.static_preview_geometry_cache = _state.context.get('static_preview_geometry_cache')

def _d3d11_package_lifecycle_step_003(_state):
    _state.static_preview_prepared_cache = _state.context.get('static_preview_prepared_cache')
    _state.static_preview_refresh_timer = _state.context.get('static_preview_refresh_timer')
    _state.texture_overrides_dirty = _state.context.get('texture_overrides_dirty')
    _state.texture_uv_global_transform_state = _state.context.get('texture_uv_global_transform_state')
    _state.texture_uv_transform_state = _state.context.get('texture_uv_transform_state')
    _state.time = _state.context.get('time')
    _state.transform_source_indices = _state.context.get('transform_source_indices')

def _d3d11_package_lifecycle_step_004(_state):

    def _current_original_reference_preview_model():
        if callable(_state._get_original_reference_preview_model):
            try:
                return _state._get_original_reference_preview_model()
            except RuntimeError:
                pass
        return _state.original_reference_preview_model
    _state._current_original_reference_preview_model = _current_original_reference_preview_model

def _d3d11_package_lifecycle_step_005(_state):

    def _apply_source_material_texture_overrides_to_ui_texture_sets(texture_sets_by_key: Dict[str, ReplacementTextureSet]) -> None:
        _state._apply_source_material_texture_overrides_to_texture_sets_helper(texture_sets_by_key, _state._current_source_material_texture_overrides(), replacement_mesh=_state.replacement_mesh_for_mapping, source_part_adjustments=_state.source_part_adjustments, apply_source_part_role_overrides=_state._apply_source_part_role_overrides)
    _state._apply_source_material_texture_overrides_to_ui_texture_sets = _apply_source_material_texture_overrides_to_ui_texture_sets

def _d3d11_package_lifecycle_step_006(_state):

    def _alignment_d3d11_preview_active() -> bool:
        return str(_state.preview_renderer_combo.currentData() or '').strip().lower() == 'd3d11' and bool(_state.alignment_d3d11_available)
    _state._alignment_d3d11_preview_active = _alignment_d3d11_preview_active

def _d3d11_package_lifecycle_step_007(_state):

    def _current_alignment_transform_generation_value() -> int:
        if callable(_state._current_alignment_transform_generation):
            return int(_state._current_alignment_transform_generation() or 0)
        if isinstance(_state.alignment_transform_generation, dict):
            return int(_state.alignment_transform_generation.get('value', 0) or 0)
        return 0
    _state._current_alignment_transform_generation_value = _current_alignment_transform_generation_value

def _d3d11_package_lifecycle_step_008(_state):

    def _current_alignment_preview_render_settings_value():
        if callable(_state._current_alignment_preview_render_settings):
            return _state._current_alignment_preview_render_settings()
        if callable(_state._get_preview_render_settings):
            return _state._get_preview_render_settings()
        if _state.preview_render_settings is not None:
            return _state.preview_render_settings
        return _state.self._current_model_preview_render_settings()
    _state._current_alignment_preview_render_settings_value = _current_alignment_preview_render_settings_value

def _d3d11_package_lifecycle_step_009(_state):

    def _mesh_edit_raw_preview_active_value() -> bool:
        if callable(_state._mesh_edit_raw_preview_active):
            return bool(_state._mesh_edit_raw_preview_active())
        return False
    _state._mesh_edit_raw_preview_active_value = _mesh_edit_raw_preview_active_value

def _d3d11_package_lifecycle_step_010(_state):

    def _set_preview_performance_status_if_ready(summary: str, *, details: str='') -> None:
        if callable(_state._set_preview_performance_status):
            _state._set_preview_performance_status(summary, details=details)
    _state._set_preview_performance_status_if_ready = _set_preview_performance_status_if_ready

def _d3d11_package_lifecycle_step_011(_state):

    def _sync_mesh_edit_preview_settings_if_ready() -> None:
        if callable(_state._sync_mesh_edit_preview_settings):
            _state._sync_mesh_edit_preview_settings()
    _state._sync_mesh_edit_preview_settings_if_ready = _sync_mesh_edit_preview_settings_if_ready

def _d3d11_package_lifecycle_step_012(_state):

    def _clear_alignment_d3d11_fast_transform_state_if_ready(*, reset_host: bool=False) -> None:
        if callable(_state._clear_alignment_d3d11_fast_transform_state):
            _state._clear_alignment_d3d11_fast_transform_state(reset_host=reset_host)
    _state._clear_alignment_d3d11_fast_transform_state_if_ready = _clear_alignment_d3d11_fast_transform_state_if_ready

def _d3d11_package_lifecycle_step_013(_state):

    def _clear_source_parts_preview_rebuild_pending_if_ready() -> None:
        if callable(_state._clear_source_parts_preview_rebuild_pending):
            _state._clear_source_parts_preview_rebuild_pending()
    _state._clear_source_parts_preview_rebuild_pending_if_ready = _clear_source_parts_preview_rebuild_pending_if_ready

def _d3d11_package_lifecycle_step_014(_state):

    def _active_mesh_edit_d3d11_static_preview_queue_blocked(kind: str, event: str) -> bool:
        if not _state._mesh_edit_raw_preview_active_value():
            return False
        message = f'Active Mesh Editor static preview {kind} is disabled; .NET/Vortice preview payloads are required.'
        if callable(_state._record_runtime_event):
            _state._record_runtime_event(event, path=getattr(_state.entry, 'path', ''), dialog_title=_state.dialog_title, reason=message)
        set_status_message = getattr(_state.self, 'set_status_message', None)
        if callable(set_status_message):
            set_status_message(message, error=True)
        return True
    _state._active_mesh_edit_d3d11_static_preview_queue_blocked = _active_mesh_edit_d3d11_static_preview_queue_blocked

def _d3d11_package_lifecycle_step_015(_state):

    def _sync_highlight_sets_if_ready() -> None:
        if callable(_state._sync_highlight_sets):
            _state._sync_highlight_sets()
    _state._sync_highlight_sets_if_ready = _sync_highlight_sets_if_ready

def _d3d11_package_lifecycle_step_016(_state):

    def _replay_alignment_d3d11_fast_transform_if_ready() -> None:
        if callable(_state._replay_alignment_d3d11_fast_transform):
            _state._replay_alignment_d3d11_fast_transform()
    _state._replay_alignment_d3d11_fast_transform_if_ready = _replay_alignment_d3d11_fast_transform_if_ready

def _d3d11_package_lifecycle_step_017(_state):
    _state._current_global_flip_v_fast_preview_value = lambda: _state._global_flip_v_fast_preview_value_helper(d3d11_preview_active=_state._alignment_d3d11_preview_active(), texture_uv_transform_state=_state.texture_uv_transform_state, texture_uv_global_transform_state=_state.texture_uv_global_transform_state, state_has_edits=_state._texture_uv_state_has_edits)

def _d3d11_package_lifecycle_step_018(_state):

    def _reapply_global_flip_v_fast_preview(expected_flip_v: bool) -> None:
        current_flip_v = _state._current_global_flip_v_fast_preview_value()
        if current_flip_v is None or bool(current_flip_v) != bool(expected_flip_v):
            return
        if send_resident_presentation_state(
            _state.dialog,
            {'uv': {'flip_v': bool(expected_flip_v)}},
        ):
            _state._texture_uv_fast_preview_record_global_flip_v_helper(
                _state.alignment_d3d11_texture_uv_fast_state,
                expected_flip_v,
            )
            return
        if _state.alignment_d3d11_preview_host.set_texture_flip_vertical(bool(expected_flip_v), editor_role='replacement_preview'):
            _state._texture_uv_fast_preview_record_global_flip_v_helper(_state.alignment_d3d11_texture_uv_fast_state, expected_flip_v)
    _state._reapply_global_flip_v_fast_preview = _reapply_global_flip_v_fast_preview

def _d3d11_package_lifecycle_step_019(_state):

    def _reapply_current_global_flip_v_fast_preview() -> None:
        current_flip_v = _state._current_global_flip_v_fast_preview_value()
        if current_flip_v is None:
            return
        _state._reapply_global_flip_v_fast_preview(bool(current_flip_v))
    _state._reapply_current_global_flip_v_fast_preview = _reapply_current_global_flip_v_fast_preview

def _d3d11_package_lifecycle_step_020(_state):

    def _try_apply_global_flip_v_fast_preview() -> bool:
        flip_v = _state._current_global_flip_v_fast_preview_value()
        if flip_v is None:
            return False
        if send_resident_presentation_state(
            _state.dialog,
            {'uv': {'flip_v': bool(flip_v)}},
        ):
            _state._texture_uv_fast_preview_record_global_flip_v_helper(
                _state.alignment_d3d11_texture_uv_fast_state,
                flip_v,
            )
            return True
        if _state.alignment_d3d11_preview_host.set_texture_flip_vertical(flip_v, editor_role='replacement_preview'):
            _state._texture_uv_fast_preview_record_global_flip_v_helper(_state.alignment_d3d11_texture_uv_fast_state, flip_v)
            _state._alignment_d3d11_mark_preview_loaded_helper(_state.alignment_d3d11_state)
            _state.texture_overrides_dirty['dirty'] = True
            _state._set_alignment_d3d11_progress(100, 'Preview ready.', active=False)
            flip_v_presentation = _state._alignment_d3d11_texture_flip_v_live_performance_helper()
            _state._set_preview_performance_status_if_ready(flip_v_presentation.summary, details=flip_v_presentation.details)
            _state.QTimer.singleShot(160, lambda expected_flip_v=flip_v: _state._reapply_global_flip_v_fast_preview(bool(expected_flip_v)))
            return True
        return False
    _state._try_apply_global_flip_v_fast_preview = _try_apply_global_flip_v_fast_preview

def _d3d11_package_lifecycle_step_021(_state):

    def _alignment_geometry_tab_active() -> bool:
        if _state._active_tab_is_helper(_state.control_tabs, _state.parts_tab):
            return True
        try:
            return _state.control_tabs.tabText(_state.control_tabs.currentIndex()).strip().lower() in {'mesh editing', 'merged mesh editing'}
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False
    _state._alignment_geometry_tab_active = _alignment_geometry_tab_active

def _d3d11_package_lifecycle_step_022(_state):

    def _alignment_mesh_edit_tab_active() -> bool:
        is_checked = getattr(_state.mesh_edit_enabled_checkbox, 'isChecked', None)
        if not callable(is_checked):
            return False
        try:
            return bool(is_checked())
        except RuntimeError:
            return False
    _state._alignment_mesh_edit_tab_active = _alignment_mesh_edit_tab_active

def _d3d11_package_lifecycle_step_023(_state):
    _state._alignment_d3d11_editor_ids_for_source_indices = lambda source_indices, *, selection_overlay=False: _state._alignment_d3d11_editor_ids_for_source_indices_helper(source_indices, _state.alignment_d3d11_state, selection_overlay=selection_overlay)
    _state._alignment_d3d11_source_indices_for_editor_id = lambda editor_id: _state._alignment_d3d11_source_indices_for_editor_id_helper(editor_id, _state.alignment_d3d11_state)

def _d3d11_package_lifecycle_step_024(_state):

    def _alignment_default_d3d11_editor_ids() -> tuple[int, ...]:
        submeshes = tuple(getattr(_state.replacement_mesh_for_mapping, 'submeshes', ()) or ()) if _state.replacement_mesh_for_mapping is not None else ()
        return _state._alignment_default_d3d11_editor_ids_helper(tuple(_state.transform_source_indices), len(submeshes), source_index_is_enabled_renderable=_state._source_index_is_enabled_renderable, editor_ids_for_source_indices=_state._alignment_d3d11_editor_ids_for_source_indices)
    _state._alignment_default_d3d11_editor_ids = _alignment_default_d3d11_editor_ids

def _d3d11_package_lifecycle_step_025(_state):

    def _cleanup_alignment_d3d11_package(package_dir: object, *, delay_ms: int=0, force: bool=False) -> None:
        if package_dir is None:
            return
        try:
            package_path = _state.Path(package_dir)
        except TypeError:
            return
        cleanup_path = (
            package_path.parent
            if package_path.name == 'package' and package_path.parent.name.startswith('cdmw_dotnet_preview_')
            else package_path
        )

        def _remove() -> None:
            if not force and _state._alignment_d3d11_package_is_cached_helper(package_path, _state.alignment_d3d11_state.get('package_cache')):
                return
            try:
                _state.shutil.rmtree(cleanup_path, ignore_errors=True)
            except OSError:
                pass
        if delay_ms > 0:
            _state.QTimer.singleShot(int(delay_ms), _remove)
        else:
            _remove()
    _state._cleanup_alignment_d3d11_package = _cleanup_alignment_d3d11_package

def _d3d11_package_lifecycle_step_026(_state):

    def _alignment_d3d11_invalidate_package_cache(reason: str='geometry') -> None:
        _state._alignment_d3d11_invalidate_package_cache_helper(_state.alignment_d3d11_state, reason, cleanup_package=lambda package_path, delay_ms: _state._cleanup_alignment_d3d11_package(package_path, delay_ms=delay_ms, force=True))
    _state._alignment_d3d11_invalidate_package_cache = _alignment_d3d11_invalidate_package_cache

def _d3d11_package_lifecycle_step_027(_state):
    _state._alignment_d3d11_model_cache_signature = lambda model: _state._alignment_d3d11_model_cache_signature_helper(model, file_signature=_state._alignment_file_signature, sample_sequence=_state._alignment_sample_sequence)

def _d3d11_package_lifecycle_step_028(_state):

    def _alignment_d3d11_geometry_cache_key(model: ModelPreviewData, settings: ModelPreviewRenderSettings, *, display_mode: str) -> str:
        _ = settings
        return _state._alignment_d3d11_geometry_cache_key_helper(model, display_mode=display_mode, modify_original_clone_mode=bool(_state.modify_original_clone_mode), sequence_digest=_state._alignment_sequence_digest)
    _state._alignment_d3d11_geometry_cache_key = _alignment_d3d11_geometry_cache_key

def _d3d11_package_lifecycle_step_029(_state):
    _state._alignment_d3d11_material_cache_key = lambda model, settings, *, package_quality: _state._alignment_d3d11_material_cache_key_helper(model, settings, package_quality=package_quality, donor_material_plan_payload=_state._donor_material_plan_payload_helper(_state._current_donor_material_plans()), material_authority_preview_signature=str(_state.material_authority_preview_signature_state.get('cache', '') or ''), file_signature=_state._alignment_file_signature)

def _d3d11_package_lifecycle_step_030(_state):

    def _alignment_d3d11_preview_cache_signature(model: ModelPreviewData, settings: ModelPreviewRenderSettings, *, display_mode: str, package_quality: str) -> MeshPreviewCacheSignature:
        return _state.MeshPreviewCacheSignature(geometry_key=_state._alignment_d3d11_geometry_cache_key(model, settings, display_mode=display_mode), material_key=_state._alignment_d3d11_material_cache_key(model, settings, package_quality=package_quality), display_class=f"{_state._alignment_d3d11_cache_display_class_helper(display_mode)}|{str(package_quality or 'normal')}")
    _state._alignment_d3d11_preview_cache_signature = _alignment_d3d11_preview_cache_signature

def _d3d11_package_lifecycle_step_031(_state):

    def _alignment_d3d11_preview_cache_key(model: ModelPreviewData, settings: ModelPreviewRenderSettings, *, label: str, display_mode: str, package_quality: str) -> str:
        _ = label
        return _state._alignment_d3d11_preview_cache_signature(model, settings, display_mode=display_mode, package_quality=package_quality).package_key
    _state._alignment_d3d11_preview_cache_key = _alignment_d3d11_preview_cache_key

def _d3d11_package_lifecycle_step_032(_state):

    def _alignment_d3d11_package_cache_get(cache_key: str) -> Optional[Mapping[str, object]]:
        package_cache = _state.alignment_d3d11_state.get('package_cache')
        return _state._alignment_d3d11_package_cache_get_helper(cache_key, package_cache, cleanup_package=lambda package_dir: _state._cleanup_alignment_d3d11_package(package_dir, force=True))
    _state._alignment_d3d11_package_cache_get = _alignment_d3d11_package_cache_get

def _d3d11_package_lifecycle_step_033(_state):

    def _alignment_d3d11_package_cache_put(cache_key: str, package_dir: Path, *, display_mode: str, package_quality: str, prepare_ms: float, package_ms: float) -> None:
        if not str(cache_key or ''):
            return
        package_cache, evicted_package_dirs = _state._alignment_d3d11_package_cache_put_helper(cache_key, package_dir, _state.alignment_d3d11_state.get('package_cache'), display_class=_state._alignment_d3d11_cache_display_class_helper(display_mode), display_mode=display_mode, package_quality=package_quality, prepare_ms=prepare_ms, package_ms=package_ms, created=_state.time.monotonic(), limit=_state.alignment_d3d11_state.get('package_cache_limit', 12))
        _state._alignment_d3d11_store_package_cache_helper(_state.alignment_d3d11_state, package_cache)
        for evicted_package_dir in evicted_package_dirs:
            _state._cleanup_alignment_d3d11_package(evicted_package_dir, force=True)
    _state._alignment_d3d11_package_cache_put = _alignment_d3d11_package_cache_put

def _d3d11_package_lifecycle_step_034(_state):

    def _drop_alignment_d3d11_package_reload(package_dir: object, *, request_id: int=0, reason: str) -> None:
        active_package = _state.alignment_d3d11_state.get('active_package')
        process = _state.alignment_d3d11_state.get('process')
        process_active = isinstance(process, _state.QProcess) and process.state() != _state.QProcess.NotRunning
        drop_cleanup_state = _state._alignment_d3d11_package_drop_cleanup_state_helper(package=package_dir, active_package=active_package, process_active=process_active)
        _state._record_runtime_event('alignment_d3d11_package_reload_dropped', reason=str(reason or 'unknown'), request_id=int(request_id or 0), active_request_id=int(_state.alignment_d3d11_state.get('request_id', 0) or 0), package_dir=str(drop_cleanup_state.package_path or ''), dialog_closing=not _state._alignment_dialog_widgets_live())
        if drop_cleanup_state.should_cleanup:
            _state._cleanup_alignment_d3d11_package(drop_cleanup_state.package_path)
    _state._drop_alignment_d3d11_package_reload = _drop_alignment_d3d11_package_reload

def _d3d11_package_lifecycle_step_035(_state):

    def _alignment_d3d11_stop_process() -> None:
        package_dir = _state._alignment_d3d11_clear_active_package_helper(_state.alignment_d3d11_state, clear_process=True, clear_request_id=False, clear_status=True)
        _state._safe_stop_alignment_timer(_state.alignment_d3d11_status_timer)
        try:
            _state.alignment_d3d11_preview_host.controller.shutdown()
        except RuntimeError:
            pass
        _state._cleanup_alignment_d3d11_package(package_dir, delay_ms=1000)
    _state._alignment_d3d11_stop_process = _alignment_d3d11_stop_process

def _d3d11_package_lifecycle_step_036(_state):
    if _state.dialog is not None:
        try:
            setattr(_state.dialog, '_mesh_editor_embedded_stop_dotnet_preview', _state._alignment_d3d11_stop_process)
        except (AttributeError, TypeError):
            pass

def _d3d11_package_lifecycle_step_037(_state):

    def _alignment_d3d11_stop_worker() -> None:
        worker = _state.alignment_d3d11_state.get('worker')
        if isinstance(worker, _state.AlignmentD3D11PackageWorker):
            worker.stop()
    _state._alignment_d3d11_stop_worker = _alignment_d3d11_stop_worker

def _d3d11_package_lifecycle_step_038(_state):

    def _shutdown_alignment_d3d11_preview() -> None:
        _state._safe_stop_alignment_timer(_state.alignment_d3d11_reload_timer)
        _state._safe_stop_alignment_timer(_state.alignment_d3d11_status_timer)
        _state._safe_stop_alignment_timer(_state.alignment_d3d11_loading_timer)
        try:
            _state._safe_stop_alignment_timer(_state.alignment_d3d11_drag_ui_timer)
        except NameError:
            pass
        _state._alignment_d3d11_reset_request_state_helper(_state.alignment_d3d11_state, clear_active_metadata=True, clear_mapping_ids=True)
        _state._alignment_d3d11_stop_worker()
        _state._alignment_d3d11_invalidate_package_cache('shutdown')
        _state._alignment_d3d11_stop_process()
        pending_package = _state.alignment_d3d11_state.get('active_package')
        _state._cleanup_alignment_d3d11_package(pending_package)
    _state._shutdown_alignment_d3d11_preview = _shutdown_alignment_d3d11_preview

def _d3d11_package_lifecycle_step_039(_state):

    def _safe_shutdown_alignment_d3d11_preview() -> None:
        try:
            _state._shutdown_alignment_d3d11_preview()
        except Exception as exc:
            _state._record_runtime_event('alignment_d3d11_shutdown_error', message=str(exc))
    _state._safe_shutdown_alignment_d3d11_preview = _safe_shutdown_alignment_d3d11_preview

def _d3d11_package_lifecycle_step_040(_state):

    def _side_by_side_alignment_preview_model(original_model: object, replacement_model: object) -> Optional[object]:
        if not isinstance(original_model, _state.ModelPreviewData) or not isinstance(replacement_model, _state.ModelPreviewData):
            return replacement_model if isinstance(replacement_model, _state.ModelPreviewData) else None
        original_min, original_max = _state._model_bounds_x(original_model)
        replacement_min, replacement_max = _state._model_bounds_x(replacement_model)
        original_width = max(0.1, original_max - original_min)
        replacement_width = max(0.1, replacement_max - replacement_min)
        gap = max(0.45, max(original_width, replacement_width) * 0.45)
        original_center = (original_min + original_max) * 0.5
        replacement_center = (replacement_min + replacement_max) * 0.5
        left_target = -((original_width + gap) * 0.5)
        right_target = (replacement_width + gap) * 0.5
        original_shifted = _state._translated_preview_model(_state._tint_preview_model(original_model, (0.3, 0.42, 0.54), clear_textures=False), left_target - original_center, clone_model=_state._clone_preview_model)
        replacement_shifted = _state._translated_preview_model(replacement_model, right_target - replacement_center, clone_model=_state._clone_preview_model)
        return _state._combine_preview_models(original_shifted, replacement_shifted)
    _state._side_by_side_alignment_preview_model = _side_by_side_alignment_preview_model

def _d3d11_package_lifecycle_step_041(_state):

    def _preview_overlay_present(preview_model: object) -> bool:
        return bool(getattr(preview_model, 'physics_overlay', None) is not None or getattr(preview_model, 'cloth_preview', None) is not None)
    _state._preview_overlay_present = _preview_overlay_present

def _d3d11_package_lifecycle_step_042(_state):

    def _queue_alignment_d3d11_preview(model: object, *, label: str='Live alignment preview', reason: str='') -> bool:
        del model, label
        _state._record_runtime_event('mesh_alignment_d3d11_preview_queue_skipped', path=getattr(_state.entry, 'path', ''), dialog_title=_state.dialog_title, reason='dotnet_authoritative', requested_reason=str(reason or ''), modify_original_clone=_state.modify_original_clone_mode)
        return False
    _state._queue_alignment_d3d11_preview = _queue_alignment_d3d11_preview

def _d3d11_package_lifecycle_step_043(_state):

    def _alignment_d3d11_package_quality(label: str, model: object=None, *, reason: str='') -> tuple[ModelPreviewRenderSettings, bool, bool, str]:
        settings = _state._current_alignment_preview_render_settings_value()
        normalized_reason = str(reason or _state.alignment_d3d11_state.get('next_rebuild_reason', '') or '').strip().lower()
        return _state._alignment_d3d11_package_quality_helper(settings, _state.alignment_d3d11_state, reason=normalized_reason, mesh_edit_raw_preview_active=_state._mesh_edit_raw_preview_active_value())
    _state._alignment_d3d11_package_quality = _alignment_d3d11_package_quality

def _d3d11_package_lifecycle_step_044(_state):

    def _queue_alignment_archive_parity_upgrade(reason: str='fast preview ready') -> None:
        if not _state._alignment_dialog_widgets_live() or not _state._alignment_d3d11_preview_active():
            return
        if not _state._alignment_d3d11_begin_archive_parity_upgrade_helper(_state.alignment_d3d11_state):
            return
        _state._set_alignment_d3d11_pipeline_stage('material_loading', reason)
        _state._set_alignment_d3d11_progress(100, 'Fast preview ready; loading full Archive Preview material parity in background. UI stays usable; preview-changing edits restart this load.', stage='material_loading', active=False)

        def _upgrade() -> None:
            if not _state._alignment_dialog_widgets_live() or not _state._alignment_d3d11_preview_active():
                _state._alignment_d3d11_clear_archive_parity_upgrade_helper(_state.alignment_d3d11_state)
                return
            parity_ready, parity_should_start = _state._original_reference_texture_preview_archive_parity_state_helper(_state.original_reference_texture_preview_state, active_preview_mode=str(_state.preview_mode_combo.currentData() or 'side_by_side'), has_original_reference_model=_state._current_original_reference_preview_model() is not None)
            if not parity_ready:
                if parity_should_start:
                    _state._load_original_reference_texture_preview()
                return
            _state._alignment_d3d11_clear_archive_parity_upgrade_helper(_state.alignment_d3d11_state)
            _state._mark_alignment_d3d11_rebuild_reason('material')
            _state._queue_static_preview_refresh()
        _state.QTimer.singleShot(120, _upgrade)
    _state._queue_alignment_archive_parity_upgrade = _queue_alignment_archive_parity_upgrade

def _d3d11_package_lifecycle_step_045(_state):

    def _queue_latest_alignment_d3d11_rebuild_for_stale_reload(request_id: int=0, *, force_active_mesh_edit: bool=False) -> None:
        if not _state._alignment_dialog_widgets_live() or bool(_state.alignment_d3d11_drag_transaction.get('active')):
            return
        reason = _state._alignment_d3d11_request_reason_helper(_state.alignment_d3d11_state, request_id=int(request_id or 0), fallback=str(_state.alignment_d3d11_state.get('last_rebuild_reason', 'geometry') or 'geometry'))
        dirty_flags = _state._alignment_d3d11_dirty_flags_for_reason(reason)
        _state._mark_alignment_d3d11_rebuild_reason(reason)
        if dirty_flags.affects_geometry():
            _state.static_preview_geometry_cache.clear()
            _state.static_preview_prepared_cache.clear()
        if dirty_flags.affects_material():
            _state.texture_overrides_dirty['dirty'] = True
        _state._alignment_d3d11_invalidate_package_cache(f'stale_{reason}')
        if not bool(force_active_mesh_edit) and _state._active_mesh_edit_d3d11_static_preview_queue_blocked('stale reload', 'mesh_edit_static_preview_stale_reload_blocked'):
            return
        _state.static_preview_refresh_timer.start()
    _state._queue_latest_alignment_d3d11_rebuild_for_stale_reload = _queue_latest_alignment_d3d11_rebuild_for_stale_reload

STEPS = (
    _d3d11_package_lifecycle_step_001,
    _d3d11_package_lifecycle_step_002,
    _d3d11_package_lifecycle_step_003,
    _d3d11_package_lifecycle_step_004,
    _d3d11_package_lifecycle_step_005,
    _d3d11_package_lifecycle_step_006,
    _d3d11_package_lifecycle_step_007,
    _d3d11_package_lifecycle_step_008,
    _d3d11_package_lifecycle_step_009,
    _d3d11_package_lifecycle_step_010,
    _d3d11_package_lifecycle_step_011,
    _d3d11_package_lifecycle_step_012,
    _d3d11_package_lifecycle_step_013,
    _d3d11_package_lifecycle_step_014,
    _d3d11_package_lifecycle_step_015,
    _d3d11_package_lifecycle_step_016,
    _d3d11_package_lifecycle_step_017,
    _d3d11_package_lifecycle_step_018,
    _d3d11_package_lifecycle_step_019,
    _d3d11_package_lifecycle_step_020,
    _d3d11_package_lifecycle_step_021,
    _d3d11_package_lifecycle_step_022,
    _d3d11_package_lifecycle_step_023,
    _d3d11_package_lifecycle_step_024,
    _d3d11_package_lifecycle_step_025,
    _d3d11_package_lifecycle_step_026,
    _d3d11_package_lifecycle_step_027,
    _d3d11_package_lifecycle_step_028,
    _d3d11_package_lifecycle_step_029,
    _d3d11_package_lifecycle_step_030,
    _d3d11_package_lifecycle_step_031,
    _d3d11_package_lifecycle_step_032,
    _d3d11_package_lifecycle_step_033,
    _d3d11_package_lifecycle_step_034,
    _d3d11_package_lifecycle_step_035,
    _d3d11_package_lifecycle_step_036,
    _d3d11_package_lifecycle_step_037,
    _d3d11_package_lifecycle_step_038,
    _d3d11_package_lifecycle_step_039,
    _d3d11_package_lifecycle_step_040,
    _d3d11_package_lifecycle_step_041,
    _d3d11_package_lifecycle_step_042,
    _d3d11_package_lifecycle_step_043,
    _d3d11_package_lifecycle_step_044,
    _d3d11_package_lifecycle_step_045,
)
