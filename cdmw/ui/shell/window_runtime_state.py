"""Runtime worker references and shell timers initialized before widgets."""

from __future__ import annotations

from collections import Counter, OrderedDict, deque

from PySide6.QtCore import QProcess, Qt, QTimer

from cdmw.domain.archives.backend_mode import resolve_archive_backend_mode
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
from cdmw.ui.shell.archive_backend_client import ArchiveBackendClient


class ShellWindowRuntimeStateMixin:
    """Initialize runtime state that must exist before tab construction."""

    def _initialize_window_runtime_state(self) -> None:
        self.worker_thread: Optional[QThread] = None
        self.scan_worker: Optional[ScanWorker] = None
        self.archive_scan_worker: Optional[ArchiveScanWorker] = None
        self.archive_scan_ui_receiver: object | None = None
        self.archive_sidecar_thread: Optional[QThread] = None
        self.archive_sidecar_worker: Optional[ArchiveSidecarIndexWorker] = None
        self.archive_derived_cache_thread: Optional[QThread] = None
        self.archive_derived_cache_worker: Optional[ArchiveDerivedIndexCacheWriteWorker] = None
        self.archive_derived_cache_index_ui_receiver = self.archive_basic_index_ui_receiver = self.archive_enhanced_index_ui_receiver = self.archive_item_icon_priority_ui_receiver = self.archive_item_icon_warmup_ui_receiver = None
        self.archive_derived_cache_write_pending = False
        self.archive_filter_worker: Optional[ArchiveFilterWorker] = None
        self.build_worker: Optional[BuildWorker] = None
        self.dds_to_png_worker: Optional[DdsToPngWorker] = None
        self.utility_worker: Optional[UtilityWorker] = None
        self._utility_completion_handler: Optional[Callable[[object], None]] = None
        self._utility_error_handler: Optional[Callable[[str], None]] = None
        self._utility_updates_archive_progress = False
        self.archive_sidecar_request_id = 0
        self.archive_sidecar_pending_start = False
        self.compare_relative_paths: List[Path] = []
        self.compare_preview_thread: Optional[QThread] = None
        self.compare_preview_worker: Optional[ComparePreviewWorker] = None
        self.compare_preview_request_id = 0
        self.pending_compare_preview_request: Optional[Tuple[int, Path]] = None
        self.pending_compare_preview_selection: Optional[Path] = None
        self._pending_texture_editor_workflow_export: Optional[Dict[str, str]] = None
        self._pending_archive_workflow_extract: Optional[Dict[str, object]] = None
        self._shutting_down = False
        self._close_after_workers_requested = False
        self._close_force_accept = False
        self._close_pending_started_at = 0.0
        self._close_force_stop_requested = False
        self._close_pending_worker_threads: list[tuple[str, QThread]] = []
        self._close_pending_processes: list[tuple[str, QProcess]] = []
        self._close_pending_builder_dialogs: list[object] = []
        self._close_finalized = False
        self._close_worker_wait_timer = QTimer(self)
        self._close_worker_wait_timer.setInterval(100)
        self._close_worker_wait_timer.timeout.connect(self._finish_deferred_close_if_workers_stopped)
        self._settings_save_timer = QTimer(self)
        self._settings_save_timer.setSingleShot(True)
        self._settings_save_timer.setInterval(250)
        self._settings_save_timer.timeout.connect(self._save_settings)
        self._archive_sidecar_status_started_at = 0.0
        self._archive_sidecar_status_detail = ""
        self._archive_sidecar_status_current = 0
        self._archive_sidecar_status_total = 0
        self.pending_in_game_mesh_swap_target: Optional[ArchiveEntry] = None
        self._archive_sidecar_status_timer = QTimer(self)
        self._archive_sidecar_status_timer.setInterval(1000)
        self._archive_sidecar_status_timer.timeout.connect(self._refresh_archive_sidecar_status_elapsed)
        self._archive_scan_progress_pending: Optional[Tuple[int, int, str]] = None
        self._archive_scan_progress_last_flush = 0.0
        self._archive_scan_progress_min_interval_s = 1.0 / 30.0
        self._archive_load_progress_percent = 0
        self._archive_load_progress_active = False
        self._archive_load_progress_detail = ""
        self._archive_cache_health_state = "unknown"
        self._archive_cache_health_reason = "Cache Status: Unknown. Archive cache has not been checked."
        self._archive_cache_health_checked_path = ""
        self._archive_cache_stale_warning_shown_for = ""
        self._archive_scan_progress_timer = QTimer(self)
        self._archive_scan_progress_timer.setSingleShot(True)
        self._archive_scan_progress_timer.setTimerType(Qt.PreciseTimer)
        self._archive_scan_progress_timer.timeout.connect(self._flush_archive_scan_progress)
        self._column_autofit_timer = QTimer(self)
        self._column_autofit_timer.setSingleShot(True)
        self._column_autofit_timer.setInterval(90)
        self._column_autofit_timer.timeout.connect(self._apply_column_autofit)
        self._responsive_resize_timer = QTimer(self)
        self._responsive_resize_timer.setSingleShot(True)
        self._responsive_resize_timer.setInterval(180)
        self._responsive_resize_timer.timeout.connect(self._apply_responsive_resize_adjustments)
        self._pending_theme_key: Optional[str] = None
        self._pending_appearance_change: Optional[Dict[str, object]] = None
        self._appearance_apply_steps: deque[Tuple[str, Callable[[], None]]] = deque()
        self._appearance_apply_app: Optional[QApplication] = None
        self._theme_change_in_progress = False
        self._theme_change_apply_timer = QTimer(self)
        self._theme_change_apply_timer.setSingleShot(True)
        self._theme_change_apply_timer.setInterval(40)
        self._theme_change_apply_timer.timeout.connect(self._apply_pending_theme_change)
        self._appearance_apply_step_timer = QTimer(self)
        self._appearance_apply_step_timer.setSingleShot(True)
        self._appearance_apply_step_timer.setInterval(35)
        self._appearance_apply_step_timer.timeout.connect(self._run_next_appearance_apply_step)
        self._chainner_analysis_timer = QTimer(self)
        self._chainner_analysis_timer.setSingleShot(True)
        self._chainner_analysis_timer.setInterval(250)
        self._chainner_analysis_timer.timeout.connect(self._refresh_chainner_chain_info)
        self._compare_preview_timer = QTimer(self)
        self._compare_preview_timer.setSingleShot(True)
        self._compare_preview_timer.setInterval(90)
        self.compare_syncing_scrollbars = False
        self.workflow_right_splitter_normal_sizes: Optional[List[int]] = None

    def _initialize_archive_renderer_runtime_state(self) -> None:
        self.archive_isolated_renderer_active_package: Optional[Path] = None
        self.archive_isolated_renderer_debug_text = ""
        self.archive_isolated_renderer_package_source = ""

    def _initialize_archive_runtime_state(self) -> None:
        self.archive_backend_selection = resolve_archive_backend_mode()
        self.archive_backend_mode = self.archive_backend_selection.mode
        self.archive_backend_mode_warning_logged = False
        self.archive_backend_failure_dialog_open = False
        self.archive_remote_bridge = None
        self.archive_item_finder_warmup_controller = None
        self.archive_remote_query_pending = False
        self.archive_remote_actions_safe = True
        self.archive_remote_total_matches = 0
        self.archive_backend_client = ArchiveBackendClient(
            cache_root=self.archive_cache_root,
            parent=self,
        )
        self.archive_catalogue_service = ArchiveCatalogueService(
            self.archive_backend_client,
            parent=self,
        )
        self.app_context.services.archive_catalogue = self.archive_catalogue_service
        self._archive_backend_close_pending = False
        self.archive_preview_thread: Optional[QThread] = None
        self.archive_preview_worker: Optional[ArchivePreviewWorker] = None
        self.archive_preview_request_id = 0
        self.pending_archive_preview_request: Optional[Tuple[int, Optional[ArchiveEntry], bool]] = None
        self.scheduled_archive_preview_request: Optional[Tuple[int, Optional[ArchiveEntry], bool, bool]] = None
        self.current_archive_preview_result: Optional[ArchivePreviewResult] = None
        self.current_archive_model_texture_references: List[ArchiveModelTextureReference] = []
        self.current_archive_used_by_references: List[ArchiveModelTextureReference] = []
        self.current_archive_asset_family_graph: Optional[AssetFamilyGraph] = None
        self.current_archive_family_member_rows: List[AssetFamilyMember] = []
        self.archive_asset_family_preferred_width = 420
        self._tree_horizontal_wheel_guards: List[QObject] = []
        self.archive_preview_cache: OrderedDict[str, ArchivePreviewResult] = OrderedDict()
        self.archive_preview_cache_keys: Dict[int, str] = {}
        self.archive_preview_cache_limit = 64
        self.archive_preview_cache_last_miss_reason = ""
        self.archive_preview_cache_last_miss_detail = ""
        self.archive_asset_family_cache: OrderedDict[
            Tuple[str, str, int, int, int],
            Tuple[AssetFamilyGraph, Tuple[ArchiveModelTextureReference, ...]],
        ] = OrderedDict()
        self.archive_asset_family_cache_limit = 512
        self.archive_preview_request_started_at: Dict[int, float] = {}
        self.archive_preview_request_phase_timings: Dict[int, Dict[str, float]] = {}
        self.archive_preview_request_sources: Dict[int, str] = {}
        self._initialize_archive_renderer_runtime_state()
        self.archive_memory_audit_timer = QTimer(self)
        self.archive_memory_audit_timer.setInterval(30000)
        self.archive_memory_audit_timer.timeout.connect(
            lambda: self._record_archive_memory_audit("periodic_idle")
        )
        self.archive_memory_audit_timer.start()
        self.archive_memory_audit_last_log_at = 0.0
        self.archive_preview_core_idle_shutdown_ms = 120000
        self.archive_preview_core_idle_shutdown_count = 0
        self.archive_preview_core_last_activity_at = 0.0
        self.archive_preview_core_idle_shutdown_timer = QTimer(self)
        self.archive_preview_core_idle_shutdown_timer.setSingleShot(True)
        self.archive_preview_core_idle_shutdown_timer.setInterval(self.archive_preview_core_idle_shutdown_ms)
        self.archive_preview_core_idle_shutdown_timer.timeout.connect(self._shutdown_idle_native_preview_core_service)
        self.archive_preview_requested_loose = False
        self.archive_preview_showing_loose = False
        self.archive_entries: List[ArchiveEntry] = []
        self.archive_entries_by_normalized_path: Mapping[str, Sequence[ArchiveEntry]] = {}
        self.archive_entries_by_basename: Mapping[str, Sequence[ArchiveEntry]] = {}
        self.archive_entries_by_extension: Mapping[str, Sequence[ArchiveEntry]] = {}
        self.archive_entries_by_role: Mapping[str, Sequence[ArchiveEntry]] = {}
        self.archive_mesh_entries_by_normalized_path: Mapping[str, Sequence[ArchiveEntry]] = {}
        self.archive_mesh_companion_by_identity: Mapping[object, ArchiveEntry] = {}
        self.archive_character_appearance_swap_cache: Dict[object, Tuple[ArchiveEntry, ...]] = {}
        self.archive_extension_counts: Counter[str] = Counter()
        self.archive_entry_metadata_signature = ""
        self.archive_entry_metadata_sources: Tuple[Tuple[object, object, object], ...] = ()
        self.archive_scan_shard_entry_signatures: Dict[str, str] = {}
        self.archive_scan_shard_entry_counts: Dict[str, int] = {}
        self.archive_result_filter_signature: Tuple[object, ...] = ()
        self.archive_basic_index_state = "idle"
        self.archive_basic_index_request_id = 0
        self.archive_basic_index_thread: Optional[QThread] = None
        self.archive_basic_index_worker: Optional[ArchiveBasicIndexWorker] = None
        self.archive_name_search_index: Optional[ArchiveNameSearchIndex] = None
        self.archive_item_search_aliases: Dict[str, str] = {}
        self.archive_item_display_names: Dict[str, str] = {}
        self.archive_item_exact_display_names: Dict[str, str] = {}
        self.archive_item_related_display_names: Dict[str, str] = {}
        self.archive_enhanced_index_state = "idle"
        self.archive_enhanced_index_request_id = 0
        self.archive_enhanced_index_activity = "idle"
        self.archive_enhanced_index_auto_prewarm_pending = False
        self.archive_native_derived_cache_ready = False
        self.archive_enhanced_index_thread: Optional[QThread] = None
        self.archive_enhanced_index_worker: Optional[ArchiveEnhancedIndexWorker] = None
        self.archive_structure_filter_state = "idle"
        self.archive_structure_filter_thread: Optional[QThread] = None
        self.archive_structure_filter_worker: Optional[ArchiveStructureFilterWorker] = None
        self.archive_browser_row_display_cache: OrderedDict[
            Tuple[str, str, int, bool],
            ArchiveBrowserRowPayload,
        ] = OrderedDict()
        self.archive_browser_row_display_cache_limit = 12000
        self.archive_item_asset_catalog: List[Dict[str, object]] = []
        self.archive_item_icon_pixmap_cache: OrderedDict[
            Tuple[Tuple[str, ...], int, str],
            Tuple[Optional[QPixmap], str],
        ] = OrderedDict()
        self.archive_item_icon_prepared_path_cache: OrderedDict[
            Tuple[Tuple[str, ...], str],
            Tuple[str, str],
        ] = OrderedDict()
        self.archive_item_icon_negative_cache: OrderedDict[
            Tuple[Tuple[str, ...], str],
            Tuple[float, str],
        ] = OrderedDict()
        self.archive_asset_catalog_fallback_icon_cache: OrderedDict[Tuple[str, str], QIcon] = OrderedDict()
        self.archive_item_icon_prepared_callbacks: List[Callable[[Tuple[Tuple[str, ...], str]], None]] = []
        self.archive_item_icon_preload_queue: List[Dict[str, object]] = []
        self.archive_item_icon_preload_next_index = 0
        self.archive_item_icon_visible_warmup_remaining = 0
        self.archive_item_icon_warmup_user_visible = False
        self.archive_item_icon_pixmap_cache_limit = 1200
        self.archive_item_icon_prepared_cache_limit = 1800
        self.archive_item_icon_warmup_thread: Optional[QThread] = None
        self.archive_item_icon_warmup_worker: Optional[ArchiveItemIconWarmupWorker] = None
        self.archive_item_icon_priority_queue: List[Dict[str, object]] = []
        self.archive_item_icon_priority_thread: Optional[QThread] = None
        self.archive_item_icon_priority_worker: Optional[ArchiveItemIconWarmupWorker] = None
        self.archive_item_icon_warmup_generation = 0
        self.archive_active_asset_catalog_scope: str = ""
        self.archive_sidecar_entries_by_texture_path: Dict[str, List[ArchiveEntry]] = {}
        self.archive_sidecar_entries_by_texture_basename: Dict[str, List[ArchiveEntry]] = {}
        self.archive_sidecar_generation = 0
        self.archive_scan_finalize_pending = False
        self.archive_filtered_entries: List[ArchiveEntry] = []
        self.archive_filtered_dds_count = 0
        self.archive_filters_dirty = False
        self.archive_filter_apply_pending = False
        self.archive_filter_requested_signature: Tuple[object, ...] = ()
        self.archive_controls_scroll_filter_anchor: Optional[int] = None
        self.archive_tree_sort_column = -1
        self.archive_tree_sort_order = "asc"
        self.archive_initial_sort_apply_pending = False
        self.archive_enhanced_filter_refresh_pending = False
        self.archive_browser_refresh_pending = False
        self.archive_startup_autoload_defer_preview = False
        self.archive_startup_saved_filter_apply_pending = False
        self.archive_startup_saved_filter_state: Dict[str, object] = {}
        self.archive_startup_saved_filter_wait_logged = False
        self.archive_startup_hold_until_ready = False
        self.archive_startup_index_warmup_required = False
        self.archive_browser_preload_state = "idle"
        self.archive_browser_render_signature: Tuple[object, ...] = ()
        self.archive_browser_first_visible_paint_done = False
        self.archive_browser_first_visible_started_at = 0.0
        self.archive_browser_first_visible_painted_at = 0.0
        self.archive_browser_ready_at = 0.0
        self.archive_browser_render_started_at = 0.0
        self.archive_browser_render_reason = ""
        self.archive_context_menu_selection_suppressed = False
        self.archive_deferred_background_start_pending = False
        self.archive_deferred_basic_index_start_pending = False
        self.archive_deferred_enhanced_index_start_pending = False
        self.archive_deferred_derived_cache_write_pending = False
        self.archive_deferred_sidecar_start_pending = False
        self.archive_item_icon_preload_pending_after_ready = False
        self._activate_archive_browser_on_scan_complete = True
        self.archive_tree_child_folders: Dict[Tuple[str, ...], List[Tuple[str, Tuple[str, ...]]]] = {}
        self.archive_tree_direct_files: Dict[Tuple[str, ...], List[int]] = {}
        self.archive_tree_folder_entry_indexes: Dict[Tuple[str, ...], List[int]] = {}
        self.archive_tree_folder_preview_stats: Dict[Tuple[str, ...], Tuple[int, int, int]] = {}
        self.archive_tree_category_entry_indexes: Dict[str, List[int]] = {}
        self.archive_tree_index_ready = False
        self.archive_tree_flat_render_limit = 5_000
        self.archive_browser_warmup_pending = False
        self.archive_browser_warmup_completion_text = ""
        self.archive_preview_loading_started_at = 0.0
        self.archive_preview_loading_request_id = 0
        self.archive_preview_loading_stall_reported = False
        self.archive_preview_loading_entry_name = ""
        self.archive_preview_loading_loose = False
        self.archive_preview_quick_result_active = False
        self.pending_archive_texture_reference_update: Optional[
            Tuple[int, Tuple[ArchiveModelTextureReference, ...], Optional[AssetFamilyGraph]]
        ] = None
        self.archive_structure_filter_pending_value = ""
        self.archive_structure_filter_children: Dict[str, List[Tuple[str, int]]] = {}
        self.archive_structure_filter_combos: List[QComboBox] = []
        self.rebuilding_archive_structure_filters = False
        self.original_compare_zoom_factor = 1.0
        self.original_compare_fit_to_view = True
        self.output_compare_zoom_factor = 1.0
        self.output_compare_fit_to_view = True
        self.compare_preview_fit_scale = 1.25
        self.archive_preview_zoom_factor = 1.0
        self.archive_preview_fit_to_view = True
        self.archive_d3d11_view_state: Dict[str, object] = {}
        self.archive_d3d11_has_view_state = False
        self.archive_d3d11_pending_view_state: Dict[str, object] = {}
        self.archive_d3d11_active_model_key = ""
        self.archive_d3d11_pending_model_key = ""
        self.mesh_editor_d3d11_session_key = ""
        self.mesh_editor_d3d11_view_state_reset_generation = 0
        self.archive_ui_activity_until = 0.0
        self.archive_ui_activity_timer = QTimer(self)
        self.archive_ui_activity_timer.setSingleShot(True)
        self.archive_ui_activity_timer.timeout.connect(self._clear_archive_ui_activity)
        self.archive_preview_debounce_timer = QTimer(self)
        self.archive_preview_debounce_timer.setSingleShot(True)
        self.archive_preview_debounce_timer.setInterval(90)
        self.archive_preview_debounce_timer.timeout.connect(self._flush_scheduled_archive_preview_request)
        self.archive_preview_loading_timer = QTimer(self)
        self.archive_preview_loading_timer.setInterval(250)
        self.archive_preview_loading_timer.timeout.connect(self._update_archive_preview_loading_indicator)
        self.model_preview_refresh_timer = QTimer(self)
        self.model_preview_refresh_timer.setSingleShot(True)
        self.model_preview_refresh_timer.setInterval(260)
        self.model_preview_refresh_timer.timeout.connect(self._refresh_current_model_preview_assets)
        self.archive_selection_state_timer = QTimer(self)
        self.archive_selection_state_timer.setSingleShot(True)
        self.archive_selection_state_timer.setInterval(30)
        self.archive_selection_state_timer.timeout.connect(self._update_archive_selection_state)
        self.archive_texture_reference_update_timer = QTimer(self)
        self.archive_texture_reference_update_timer.setSingleShot(True)
        self.archive_texture_reference_update_timer.setInterval(16)
        self.archive_texture_reference_update_timer.timeout.connect(self._flush_archive_texture_reference_update)
        self.archive_item_icon_preload_timer = QTimer(self)
        self.archive_item_icon_preload_timer.setSingleShot(True)
        self.archive_item_icon_preload_timer.setInterval(0)
        self.archive_item_icon_preload_timer.timeout.connect(self._continue_archive_asset_catalog_icon_preload)
        self._last_build_unknown_review_result: Optional[Dict[str, object]] = None
        self._detachable_tool_order: List[str] = []
        self._tool_widgets_by_key: Dict[str, QWidget] = {}
        self._tool_titles_by_key: Dict[str, str] = {}
        self._tool_placeholders_by_key: Dict[str, QWidget] = {}
        self._tool_keys_by_placeholder: Dict[QWidget, str] = {}
        self._tool_tab_widgets_by_key: Dict[str, QTabWidget] = {}
        self._tool_tab_labels_by_key: Dict[str, str] = {}
        self._detached_tool_windows: Dict[str, DetachedToolWindow] = {}
        self._tool_window_actions: Dict[str, object] = {}
        self._dashboard_status_labels: Dict[str, QLabel] = {}
        self._dashboard_last_result_text = "No workflow results yet."


__all__ = ["ShellWindowRuntimeStateMixin"]
