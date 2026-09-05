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
        self.textures.scan_worker: Optional[ScanWorker] = None
        self.archive.archive_scan_worker: Optional[ArchiveScanWorker] = None
        self.archive.archive_scan_ui_receiver: object | None = None
        self.archive.archive_sidecar_thread: Optional[QThread] = None
        self.archive.archive_sidecar_worker: Optional[ArchiveSidecarIndexWorker] = None
        self.archive.archive_derived_cache_thread: Optional[QThread] = None
        self.archive.archive_derived_cache_worker: Optional[ArchiveDerivedIndexCacheWriteWorker] = None
        self.archive.archive_derived_cache_index_ui_receiver = self.archive.archive_basic_index_ui_receiver = self.archive.archive_enhanced_index_ui_receiver = self.archive.archive_item_icon_priority_ui_receiver = self.archive.archive_item_icon_warmup_ui_receiver = None
        self.archive.archive_derived_cache_write_pending = False
        self.archive.archive_filter_worker: Optional[ArchiveFilterWorker] = None
        self.textures.build_worker: Optional[BuildWorker] = None
        self.textures.dds_to_png_worker: Optional[DdsToPngWorker] = None
        self.utility_worker: Optional[UtilityWorker] = None
        self._utility_completion_handler: Optional[Callable[[object], None]] = None
        self._utility_error_handler: Optional[Callable[[str], None]] = None
        self._utility_updates_archive_progress = False
        self.archive.archive_sidecar_request_id = 0
        self.archive.archive_sidecar_pending_start = False
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
        self.archive._archive_sidecar_status_started_at = 0.0
        self.archive._archive_sidecar_status_detail = ""
        self.archive._archive_sidecar_status_current = 0
        self.archive._archive_sidecar_status_total = 0
        self.archive.pending_in_game_mesh_swap_target: Optional[ArchiveEntry] = None
        self.archive._archive_sidecar_status_timer = QTimer(self)
        self.archive._archive_sidecar_status_timer.setInterval(1000)
        self.archive._archive_sidecar_status_timer.timeout.connect(self.archive._refresh_archive_sidecar_status_elapsed)
        self.archive._archive_scan_progress_pending: Optional[Tuple[int, int, str]] = None
        self.archive._archive_scan_progress_last_flush = 0.0
        self.archive._archive_scan_progress_min_interval_s = 1.0 / 30.0
        self.archive._archive_load_progress_percent = 0
        self.archive._archive_load_progress_active = False
        self.archive._archive_load_progress_detail = ""
        self.archive._archive_cache_health_state = "unknown"
        self.archive._archive_cache_health_reason = "Cache Status: Unknown. Archive cache has not been checked."
        self.archive._archive_cache_health_checked_path = ""
        self.archive._archive_cache_stale_warning_shown_for = ""
        self.archive._archive_scan_progress_timer = QTimer(self)
        self.archive._archive_scan_progress_timer.setSingleShot(True)
        self.archive._archive_scan_progress_timer.setTimerType(Qt.PreciseTimer)
        self.archive._archive_scan_progress_timer.timeout.connect(self.archive._flush_archive_scan_progress)
        self._column_autofit_timer = QTimer(self)
        self._column_autofit_timer.setSingleShot(True)
        self._column_autofit_timer.setInterval(90)
        self._column_autofit_timer.timeout.connect(self._apply_column_autofit)
        self.archive._archive_tree_header_programmatic_depth = 0
        self.archive._archive_tree_content_autofit_done = False
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
        self._chainner_analysis_timer.timeout.connect(self.textures._refresh_chainner_chain_info)

    def _initialize_tool_window_state(self) -> None:
        self.mesh_editor_d3d11_session_key = ""
        self.mesh_editor_d3d11_view_state_reset_generation = 0
        self._detachable_tool_order: List[str] = []
        self._tool_widgets_by_key = self.tab_registry.widgets
        self._tool_titles_by_key = self.tab_registry.titles
        self._tool_placeholders_by_key: Dict[str, QWidget] = {}
        self._tool_keys_by_placeholder: Dict[QWidget, str] = {}
        self._tool_tab_home_index_by_key: Dict[str, int] = {}
        self._detached_tool_windows: Dict[str, DetachedToolWindow] = {}
        self._tool_window_actions: Dict[str, object] = {}
        self._dashboard_status_labels: Dict[str, QLabel] = {}


__all__ = ["ShellWindowRuntimeStateMixin"]
