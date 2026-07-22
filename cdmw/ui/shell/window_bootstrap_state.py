"""Initial main-window context, settings, and theme state."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from cdmw.constants import APP_TITLE, DEFAULT_UI_THEME
from cdmw.models import clamp_archive_performance_settings, clamp_model_preview_render_settings
from cdmw.services.cache_layout import migrate_runtime_cache_layout
from cdmw.services.settings_service import create_settings
from cdmw.services.workspace_layout import workspace_paths
from cdmw.ui.localization import UiLocalizer
from cdmw.ui.model_preview_native import ARCHIVE_MODEL_RENDERER_DEFAULT
from cdmw.ui.shell.app_context import AppContext
from cdmw.ui.shell.app_state import AppState
from cdmw.ui.shell.tab_registry import TabRegistry


class ShellWindowBootstrapStateMixin:
    """Initialize shell state required before widget construction."""

    def _initialize_window_bootstrap_state(
        self,
        *,
        app_context: AppContext | None,
        settings_file_path: Path,
        crash_reports_dir: Path,
        session_id: str,
        previous_session_unclean: bool,
        set_crash_capture_enabled: Callable[[bool], None],
        record_runtime_event: Callable[..., dict],
        set_last_active_operation: Callable[..., None],
        collect_crash_context: Callable[[], dict],
        clear_active_main_window: Callable[[], None],
        write_crash_report: Callable[[dict, str], Path],
        write_heartbeat: Callable[..., None],
    ) -> None:
        self.app_context = app_context or AppContext.create_default()
        self.app_state = AppState()
        self.tab_registry = TabRegistry(self.app_context)
        self.setWindowTitle(APP_TITLE)

        self.settings = self.app_context.settings if app_context is not None else create_settings()
        self.app_context.settings = self.settings
        self.app_context.services.bind_settings(self.settings)
        set_crash_capture_enabled(self._preference_bool("capture_crash_details", False))
        self._set_crash_capture_enabled = set_crash_capture_enabled

        self.settings_file_path = settings_file_path
        archive_cache_root_override = os.environ.get("CDMW_ARCHIVE_CACHE_ROOT", "").strip()
        self.archive_cache_root = (
            Path(archive_cache_root_override).expanduser()
            if archive_cache_root_override
            else workspace_paths(self.settings_file_path.parent)["archive_cache_root"]
        )
        if archive_cache_root_override:
            os.environ["CDMW_TEMP_CACHE_ROOT"] = str(self.archive_cache_root)
        cache_migration = migrate_runtime_cache_layout(self.archive_cache_root)
        if cache_migration.moved or cache_migration.skipped:
            try:
                record_runtime_event(
                    "runtime_cache_layout_migration",
                    moved_count=len(cache_migration.moved),
                    skipped_count=len(cache_migration.skipped),
                )
            except Exception:
                pass

        self.language_dir = self.settings_file_path.parent / "languages"
        self.ui_localizer = UiLocalizer(
            language_dir=self.language_dir,
            language_code=str(self.settings.value("appearance/language", "en") or "en"),
        )
        self._settings_ready = False
        self._record_runtime_event = record_runtime_event
        self._set_last_active_operation = set_last_active_operation
        self._collect_crash_context = collect_crash_context
        self._clear_active_main_window = clear_active_main_window
        self._write_crash_report = write_crash_report
        self._write_heartbeat = write_heartbeat
        self.crash_reports_dir = crash_reports_dir
        self._session_id = session_id
        self._previous_session_unclean = bool(previous_session_unclean)

        self._startup_benchmark_finish_requested = False
        self._startup_benchmark_search_pending = False
        self._startup_benchmark_search_started_at = 0.0
        self._startup_benchmark_archive_source = ""
        self._startup_benchmark_archive_timings = {}
        self._startup_benchmark_archive_timing_summary = ""
        self._startup_splash_window = None
        self._startup_splash_holds_main_window = False
        self._startup_splash_released = False
        self._startup_splash_release_pending = False
        self._startup_splash_finish_pending = False
        self._startup_splash_finish_after_paint_deadline = 0.0
        self._startup_archive_path_prompt_handled = False
        self._startup_archive_path_prompt_accepted = False
        self._startup_archive_path_prompt_open = False

        self.app_tray_icon = None
        self.app_tray_menu = None
        self._initialize_existing_instance_activation_polling()
        self._responsive_screen_signal_connected = False
        self._modeless_alignment_dialogs = {}
        self.archive_preview_refresh_deferred_by_builder = False
        self.archive_model_preview_dark_background_enabled = True
        self._current_responsive_control_scale = 0.0
        self._applying_responsive_layout = False
        self._responsive_metrics_dirty = True
        self._responsive_last_screen_signature = (0, 0, 0.0)
        self._responsive_resize_last_elapsed_ms = 0
        self._responsive_control_widgets = ()

        self.current_theme_key = str(self.settings.value("appearance/theme", DEFAULT_UI_THEME))
        self.app_state.current_theme_key = self.current_theme_key
        self.archive_model_renderer_backend = ARCHIVE_MODEL_RENDERER_DEFAULT
        self.show_quick_start_on_launch = (
            not self.settings.contains("ui/startup_setup_shown")
            or not str(self.settings.value("archive/package_root", "") or "").strip()
        )
        self._model_preview_render_settings = clamp_model_preview_render_settings()
        self.model_preview_settings_dialog = None
        self._archive_performance_settings = clamp_archive_performance_settings()
        self.resize(1360, 840)
        self.setMinimumSize(1120, 720)


__all__ = ["ShellWindowBootstrapStateMixin"]
