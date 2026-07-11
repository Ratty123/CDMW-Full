"""Post-tab startup restore and first-run scheduling."""

from __future__ import annotations

import os
from typing import Callable

from PySide6.QtCore import QTimer


class ShellStartupRestoreMixin:
    """Restore persisted shell state once all tabs and widgets exist."""

    def _prepare_archive_preview_startup_state(self) -> None:
        self._archive_preview_startup_state_pending = True
        tree = getattr(self, "archive_tree", None)
        current_item = tree.currentItem() if tree is not None else None
        debounce_timer = getattr(self, "archive_preview_debounce_timer", None)
        idle = bool(
            current_item is None
            and getattr(self, "current_archive_preview_result", None) is None
            and getattr(self, "archive_preview_thread", None) is None
            and getattr(self, "archive_preview_worker", None) is None
            and getattr(self, "pending_archive_preview_request", None) is None
            and getattr(self, "scheduled_archive_preview_request", None) is None
            and getattr(self, "model_preview_settings_dialog", None) is None
            and not tuple(getattr(self, "_modal_model_preview_settings_dialogs", ()) or ())
            and not (debounce_timer is not None and debounce_timer.isActive())
        )
        if not idle:
            self._ensure_archive_preview_startup_state()

    def _ensure_archive_preview_startup_state(self) -> None:
        if not getattr(self, "_archive_preview_startup_state_pending", False):
            return
        if getattr(self, "_archive_preview_startup_state_applying", False):
            return
        self._archive_preview_startup_state_applying = True
        try:
            if getattr(self, "_model_preview_settings_read_pending", False):
                self._model_preview_render_settings = self._read_model_preview_render_settings()
                self._model_preview_settings_read_pending = False
            self._handle_model_preview_settings_changed(self._model_preview_render_settings)
            self._clear_archive_preview("Select an archive file to preview it here.")
            self._archive_preview_startup_state_pending = False
        finally:
            self._archive_preview_startup_state_applying = False

    def _restore_shell_startup_state(
        self,
        pump_startup_splash: Callable[[str], None],
        *,
        previous_session_unclean: bool,
    ) -> None:
        pump_startup_splash("Restoring saved workspace...")

        self._load_settings()
        self._connect_shell_signals()
        self._refresh_dashboard()
        self._apply_startup_benchmark_overrides()
        self._startup_texture_preview_defer_env = bool(
            self._startup_benchmark_enabled()
            or previous_session_unclean
            or self._startup_archive_autoload_expected()
        )
        if self._startup_texture_preview_defer_env:
            os.environ["CDMW_DEFER_TEXTURE_PREVIEW"] = "1"
        self._prepare_archive_preview_startup_state()
        self._rebuild_archive_structure_filter_controls()
        self._refresh_chainner_chain_info()
        self._apply_csv_log_enabled_state()
        self._apply_upscale_backend_state()
        self._apply_dds_staging_enabled_state()
        self._apply_dds_output_state()
        self._apply_compare_zoom("original")
        self._apply_compare_zoom("output")
        self._cache_responsive_control_widgets()
        self.archive_filters_dirty = False
        self._update_archive_filter_button_state()
        if not self._archive_preview_startup_state_pending:
            self._update_archive_selection_state()
            self._refresh_archive_preview_settings_status()
        self._update_compare_navigation_state()
        self.refresh_compare_list()
        self._apply_ui_language()
        self._settings_ready = True
        self._schedule_workflow_match_refresh()
        if not self._startup_benchmark_enabled():
            self._save_settings()

        geometry = self.settings.value("window/geometry")
        if geometry:
            self.restoreGeometry(geometry)
        QTimer.singleShot(0, self._connect_responsive_screen_signals)
        QTimer.singleShot(0, self._apply_initial_responsive_window_defaults)
        QTimer.singleShot(140, self._schedule_column_autofit)
        if os.environ.get("CDMW_GUI_STARTUP_SMOKE") != "1":
            QTimer.singleShot(120, self._show_first_run_guide_if_needed)
            QTimer.singleShot(900, self._maybe_autoload_archive_on_startup)


__all__ = ["ShellStartupRestoreMixin"]
