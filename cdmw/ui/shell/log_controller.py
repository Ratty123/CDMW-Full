"""Shell log, status, and busy-state helpers."""

from __future__ import annotations

import time

from cdmw.ui.shell.lazy_tool_tab import created_tool_widget


class LogControllerMixin:
    """Shared shell log appenders, status message, and busy state toggles."""
    def clear_live_log(self) -> None:
        self.textures.log_view.clear()
        self.set_status_message("Live log cleared.")

    def clear_archive_scan_log(self) -> None:
        self.archive.archive_log_view.clear()
        self.set_status_message("Archive scan log cleared.")

    def _background_task_active(self, *, block_on_archive_index: bool = True) -> bool:
        if self.worker_thread is not None:
            return True
        if getattr(self.textures, "_texture_export_kind", ""):
            return True
        if block_on_archive_index and self.archive.archive_basic_index_thread is not None:
            self.set_status_message("Archive lookup indexes are still warming. Wait for them to finish before refreshing archives.", error=True)
            return True
        text_search_tab = created_tool_widget(getattr(self, "text_search_tab", None))
        if text_search_tab is not None and text_search_tab.is_busy():
            self.set_status_message("Text Search is still running. Stop it first before starting another task.", error=True)
            return True
        return False

    def append_log(
        self,
        message: str,
        *,
        tool_key: str | None = None,
        source: str = "tool_log",
        severity: str = "info",
    ) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.textures.log_view.appendPlainText(f"[{timestamp}] {message}")
        scrollbar = self.textures.log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        from cdmw.ui.shell.compact.workspace import append_compact_activity

        append_compact_activity(
            self,
            message,
            tool_key=str(tool_key or "texture_workflow"),
            source=source,
            severity=severity,
        )

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

    def append_archive_log(
        self,
        message: str,
        *,
        verbose: bool = False,
        tool_key: str | None = None,
        source: str = "archive_log",
        severity: str = "info",
    ) -> None:
        if (verbose or self._archive_log_message_is_verbose(message)) and not self._show_verbose_archive_logs():
            return
        timestamp = time.strftime("%H:%M:%S")
        self.archive.archive_log_view.appendPlainText(f"[{timestamp}] {message}")
        scrollbar = self.archive.archive_log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        from cdmw.ui.shell.compact.workspace import append_compact_activity

        append_compact_activity(
            self,
            message,
            tool_key=str(tool_key or "archive_browser"),
            source=source,
            severity=severity,
        )

    def _append_verbose_archive_log(self, message: str) -> None:
        self.append_archive_log(message, verbose=True)

    def set_status_message(
        self,
        message: str,
        *,
        error: bool = False,
        tool_key: str | None = None,
        source: str = "status",
        severity: str | None = None,
        snapshot: object | None = None,
    ) -> None:
        self.textures.error_message_value.setText(message)
        self.textures.error_message_value.setProperty("error", error)
        self.textures.error_message_value.style().unpolish(self.textures.error_message_value)
        self.textures.error_message_value.style().polish(self.textures.error_message_value)
        self._refresh_dashboard()
        from cdmw.ui.shell.compact.workspace import append_compact_activity

        resolved_tool_key = str(tool_key or "")
        if not resolved_tool_key and getattr(self, "compact_workspace", None) is not None:
            current_widget = self._current_navigation_widget()
            resolved_tool_key = self._tool_key_for_widget(current_widget)
        append_compact_activity(
            self,
            message,
            tool_key=resolved_tool_key,
            source=source,
            severity=str(severity or ("error" if error else "info")),
        )
        compact_workspace = getattr(self, "compact_workspace", None)
        if compact_workspace is not None and snapshot is not None:
            from cdmw.ui.shell.compact.activity import CompactStatusSnapshot

            if isinstance(snapshot, CompactStatusSnapshot):
                compact_workspace.set_status_snapshot(snapshot)

    def set_busy(self, busy: bool, build_mode: bool = False) -> None:
        self.export_profile_action.setEnabled(not busy)
        self.import_profile_action.setEnabled(not busy)
        self.export_diagnostics_action.setEnabled(not busy)
        self.copy_problem_summary_action.setEnabled(not busy)
        self.open_crash_reports_action.setEnabled(not busy)
        self.open_settings_action.setEnabled(not busy)
        self.mod_package_tool_action.setEnabled(not busy)
        self.open_documentation_action.setEnabled(not busy)
        self.open_about_action.setEnabled(not busy)
        self.textures.left_panel.setEnabled(not busy)
        self.textures.scan_button.setEnabled(not busy)
        self.textures.preview_policy_button.setEnabled(not busy)
        self.textures.clear_workflow_roots_button.setEnabled(not busy)
        self.textures.start_button.setEnabled(not busy)
        self.textures.stop_button.setEnabled(busy and build_mode)
        self.textures.set_texture_job_busy(busy)
        self.archive.archive_package_root_edit.setEnabled(not busy)
        self.archive.archive_extract_root_edit.setEnabled(not busy)
        self.archive.archive_package_root_browse_button.setEnabled(not busy)
        self.archive.archive_package_root_detect_button.setEnabled(not busy)
        self.archive.archive_extract_root_browse_button.setEnabled(not busy)
        self.archive.archive_scan_button.setEnabled(not busy)
        self.archive.archive_refresh_scan_button.setEnabled(not busy)
        remote_bridge = getattr(self.archive, "archive_remote_bridge", None)
        remote_session_ready = bool(
            remote_bridge is not None
            and remote_bridge.displays_v2
            and remote_bridge.current_session is not None
        )
        self.archive.archive_asset_catalog_button.setEnabled(
            not busy and (remote_session_ready or bool(self.archive.archive_item_asset_catalog))
        )
        self.archive.archive_clear_asset_scope_button.setEnabled(not busy and bool(self.archive.archive_active_asset_catalog_scope))
        self.archive.archive_filter_edit.setEnabled(not busy)
        self.archive.archive_path_search_button.setEnabled(not busy)
        self.archive.archive_exclude_filter_edit.setEnabled(not busy)
        self.archive.archive_extension_filter_combo.setEnabled(not busy)
        self.archive.archive_extension_picker_button.setEnabled(not busy and bool(self.archive._archive_extension_counts()))
        self.archive.archive_package_filter_edit.setEnabled(not busy)
        self.archive._set_archive_structure_filter_enabled(not busy)
        self._refresh_dashboard()
        self.archive.archive_role_filter_combo.setEnabled(not busy)
        self.archive.archive_exclude_common_technical_checkbox.setEnabled(not busy)
        self.archive.archive_min_size_spin.setEnabled(not busy)
        self.archive.archive_previewable_only_checkbox.setEnabled(not busy)
        self.archive.archive_browser_view_mode_combo.setEnabled(not busy)
        selected_entries = self.archive._selected_archive_entries()
        self.archive.archive_extract_selected_button.setEnabled(not busy and len(selected_entries) > 0)
        self.archive.archive_extract_filtered_button.setEnabled(not busy and bool(self.archive.archive_filtered_entries))
        selected_has_dds = any(entry.extension == ".dds" for entry in selected_entries)
        self.archive.archive_resolve_in_research_button.setEnabled(
            not busy
            and self.archive._current_archive_entry() is not None
            and self.archive._current_archive_entry().extension == ".dds"
        )
        self.archive.archive_tree.setEnabled(not busy)
        for widget in self.archive._archive_model_preview_widgets():
            if hasattr(widget, "setEnabled"):
                widget.setEnabled(not busy)
        self.archive.archive_media_preview.setEnabled(not busy)
        self.archive.archive_preview_text_edit.setEnabled(not busy)
        self.archive.archive_preview_info_edit.setEnabled(not busy)
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
        self.archive.archive_preview_loose_toggle_button.setEnabled(
            not busy and self.archive.archive_preview_loose_toggle_button.isVisible()
        )
        zoomable_preview_enabled = not busy and self.archive._active_archive_preview_zoom_widget() is not None
        self.archive.archive_preview_zoom_out_button.setEnabled(zoomable_preview_enabled)
        self.archive.archive_preview_zoom_fit_button.setEnabled(zoomable_preview_enabled)
        self.archive.archive_preview_zoom_100_button.setEnabled(zoomable_preview_enabled)
        self.archive.archive_preview_zoom_in_button.setEnabled(zoomable_preview_enabled)
        self.archive._update_archive_model_action_controls(self.archive._archive_model_preview_controls_target())
        self.archive._update_archive_filter_button_state()
        compact_workspace = getattr(self, "compact_workspace", None)
        if compact_workspace is not None:
            compact_workspace.refresh_tool_enabled_states()

    def reset_progress(self, total: int = 0) -> None:
        self.textures.phase_value.setText("Idle")
        self.textures.phase_progress_value.setText("Waiting")
        self.textures._texture_workflow_total_files = int(total)
        self.ui_localizer.set_number_text(self.textures.total_files_value, total)
        self.textures.current_file_value.setText("Idle")
        self.ui_localizer.set_number_text(self.textures.converted_value, 0)
        self.ui_localizer.set_number_text(self.textures.skipped_value, 0)
        self.ui_localizer.set_number_text(self.textures.failed_value, 0)
        self.textures.progress_bar.setRange(0, max(total, 1))
        self.textures.progress_bar.setValue(0)
        self.textures.progress_bar.setFormat("%v / %m")
