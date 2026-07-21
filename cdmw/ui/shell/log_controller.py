"""Shell log, status, and busy-state helpers."""

from __future__ import annotations

import time

from cdmw.ui.shell.lazy_tool_tab import created_tool_widget


class LogControllerMixin:
    """Shared shell log appenders, status message, and busy state toggles."""
    def clear_live_log(self) -> None:
        self.log_view.clear()
        self.set_status_message("Live log cleared.")

    def clear_archive_scan_log(self) -> None:
        self.archive_log_view.clear()
        self.set_status_message("Archive scan log cleared.")

    def _background_task_active(self, *, block_on_archive_index: bool = True) -> bool:
        if self.worker_thread is not None:
            return True
        if block_on_archive_index and self.archive_basic_index_thread is not None:
            self.set_status_message("Archive lookup indexes are still warming. Wait for them to finish before refreshing archives.", error=True)
            return True
        text_search_tab = created_tool_widget(getattr(self, "text_search_tab", None))
        if text_search_tab is not None and text_search_tab.is_busy():
            self.set_status_message("Text Search is still running. Stop it first before starting another task.", error=True)
            return True
        return False

    def append_log(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.log_view.appendPlainText(f"[{timestamp}] {message}")
        scrollbar = self.log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _show_verbose_archive_logs(self) -> bool:
        return self._read_bool("preferences/show_verbose_archive_logs", False)

    def _archive_log_message_is_verbose(self, message: str) -> bool:
        lowered = message.lower()
        verbose_markers = (
            " timings |",
            "preview timings",
            "cache hit is slower",
            "sidecar cache hit is slower",
            "worker_count=",
            "cache_lookup=",
            "lazy-index",
            "lazy index",
            "metadata format changed",
        )
        return any(marker in lowered for marker in verbose_markers)

    def append_archive_log(self, message: str, *, verbose: bool = False) -> None:
        if (verbose or self._archive_log_message_is_verbose(message)) and not self._show_verbose_archive_logs():
            return
        timestamp = time.strftime("%H:%M:%S")
        self.archive_log_view.appendPlainText(f"[{timestamp}] {message}")
        scrollbar = self.archive_log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _append_verbose_archive_log(self, message: str) -> None:
        self.append_archive_log(message, verbose=True)

    def set_status_message(self, message: str, *, error: bool = False) -> None:
        self.error_message_value.setText(message)
        self.error_message_value.setProperty("error", error)
        self.error_message_value.style().unpolish(self.error_message_value)
        self.error_message_value.style().polish(self.error_message_value)
        self._refresh_dashboard()

    def set_busy(self, busy: bool, build_mode: bool = False) -> None:
        self.export_profile_action.setEnabled(not busy)
        self.import_profile_action.setEnabled(not busy)
        self.export_diagnostics_action.setEnabled(not busy)
        self.copy_problem_summary_action.setEnabled(not busy)
        self.open_crash_reports_action.setEnabled(not busy)
        self.open_settings_action.setEnabled(not busy)
        self.mod_package_tool_action.setEnabled(not busy)
        self.quick_start_menu_action.setEnabled(not busy)
        self.open_documentation_action.setEnabled(not busy)
        self.open_about_action.setEnabled(not busy)
        self.left_panel.setEnabled(not busy)
        self.scan_button.setEnabled(not busy)
        self.preview_policy_button.setEnabled(not busy)
        self.clear_workflow_roots_button.setEnabled(not busy)
        self.start_button.setEnabled(not busy)
        self.stop_button.setEnabled(busy and build_mode)
        self.refresh_compare_button.setEnabled(not busy)
        self.compare_list.setEnabled(not busy)
        self.compare_previous_button.setEnabled(not busy and self.compare_list.currentRow() > 0)
        self.compare_next_button.setEnabled(
            not busy and 0 <= self.compare_list.currentRow() < self.compare_list.count() - 1
        )
        self.compare_mip_details_button.setEnabled(
            not busy and 0 <= self.compare_list.currentRow() < self.compare_list.count()
        )
        self.compare_open_in_editor_button.setEnabled(
            not busy and 0 <= self.compare_list.currentRow() < self.compare_list.count()
        )
        self.compare_sync_pan_checkbox.setEnabled(not busy)
        self.archive_package_root_edit.setEnabled(not busy)
        self.archive_extract_root_edit.setEnabled(not busy)
        self.archive_package_root_browse_button.setEnabled(not busy)
        self.archive_package_root_detect_button.setEnabled(not busy)
        self.archive_extract_root_browse_button.setEnabled(not busy)
        self.archive_scan_button.setEnabled(not busy)
        self.archive_refresh_scan_button.setEnabled(not busy)
        remote_bridge = getattr(self, "archive_remote_bridge", None)
        remote_session_ready = bool(
            remote_bridge is not None
            and remote_bridge.displays_v2
            and remote_bridge.current_session is not None
        )
        self.archive_asset_catalog_button.setEnabled(
            not busy and (remote_session_ready or bool(self.archive_item_asset_catalog))
        )
        self.archive_clear_asset_scope_button.setEnabled(not busy and bool(self.archive_active_asset_catalog_scope))
        self.archive_filter_edit.setEnabled(not busy)
        self.archive_path_search_button.setEnabled(not busy)
        self.archive_exclude_filter_edit.setEnabled(not busy)
        self.archive_extension_filter_combo.setEnabled(not busy)
        self.archive_extension_picker_button.setEnabled(not busy)
        self.archive_package_filter_edit.setEnabled(not busy)
        self._set_archive_structure_filter_enabled(not busy)
        self._refresh_dashboard()
        self.archive_role_filter_combo.setEnabled(not busy)
        self.archive_exclude_common_technical_checkbox.setEnabled(not busy)
        self.archive_min_size_spin.setEnabled(not busy)
        self.archive_previewable_only_checkbox.setEnabled(not busy)
        self.archive_browser_view_mode_combo.setEnabled(not busy)
        selected_entries = self._selected_archive_entries()
        self.archive_extract_selected_button.setEnabled(not busy and len(selected_entries) > 0)
        self.archive_extract_filtered_button.setEnabled(not busy and bool(self.archive_filtered_entries))
        selected_has_dds = any(entry.extension == ".dds" for entry in selected_entries)
        filtered_has_dds = int(getattr(self, "archive_filtered_dds_count", 0) or 0) > 0
        workflow_extract_enabled = selected_has_dds if selected_entries else filtered_has_dds
        self.archive_extract_to_workflow_button.setEnabled(not busy and workflow_extract_enabled)
        self.archive_open_in_editor_button.setEnabled(not busy and self._current_archive_entry() is not None)
        self.archive_resolve_in_research_button.setEnabled(
            not busy
            and self._current_archive_entry() is not None
            and self._current_archive_entry().extension == ".dds"
        )
        self.archive_tree.setEnabled(not busy)
        for widget in self._archive_model_preview_widgets():
            if hasattr(widget, "setEnabled"):
                widget.setEnabled(not busy)
        self.archive_media_preview.setEnabled(not busy)
        self.archive_preview_text_edit.setEnabled(not busy)
        self.archive_preview_info_edit.setEnabled(not busy)
        self.text_search_tab.setEnabled(not busy)
        text_search_tab = created_tool_widget(self.text_search_tab)
        if text_search_tab is not None:
            text_search_tab.set_external_busy(busy)
        self.research_tab.setEnabled(not busy)
        self.replace_assistant_tab.setEnabled(not busy)
        replace_assistant_tab = created_tool_widget(self.replace_assistant_tab)
        if replace_assistant_tab is not None:
            replace_assistant_tab.set_external_busy(busy)
        self.texture_editor_tab.setEnabled(not busy)
        self.settings_tab.setEnabled(not busy)
        self.archive_preview_loose_toggle_button.setEnabled(
            not busy and self.archive_preview_loose_toggle_button.isVisible()
        )
        zoomable_preview_enabled = not busy and self._active_archive_preview_zoom_widget() is not None
        self.archive_preview_zoom_out_button.setEnabled(zoomable_preview_enabled)
        self.archive_preview_zoom_fit_button.setEnabled(zoomable_preview_enabled)
        self.archive_preview_zoom_100_button.setEnabled(zoomable_preview_enabled)
        self.archive_preview_zoom_in_button.setEnabled(zoomable_preview_enabled)
        self._update_archive_model_action_controls(self._archive_model_preview_controls_target())
        self._update_archive_filter_button_state()

    def reset_progress(self, total: int = 0) -> None:
        self.phase_value.setText("Idle")
        self.phase_progress_value.setText("Waiting")
        self.total_files_value.setText(str(total))
        self.current_file_value.setText("Idle")
        self.converted_value.setText("0")
        self.skipped_value.setText("0")
        self.failed_value.setText("0")
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%v / %m")
