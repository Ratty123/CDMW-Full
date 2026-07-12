"""Archive browser filter worker orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Optional

from PySide6.QtCore import QThread, QTimer

from cdmw.workers.archive_filter_workers import ArchiveFilterWorker
from cdmw.workers.archive_workers import ArchiveStructureFilterWorker


def _record_archive_filter_worker_lifecycle(target: object, event: str, **fields: object) -> None:
    recorder = getattr(target, "_record_runtime_event", None)
    if callable(recorder):
        try:
            recorder(str(event), **fields)
        except Exception:
            return


class ArchiveFilterWorkerMixin:
    """Filter worker start, completion, and structure-filter warmup handling."""

    def _start_archive_structure_filter_worker(self) -> None:
        if self._shutting_down or not self.archive_entries:
            self.archive_structure_filter_state = "idle"
            return
        if self.archive_structure_filter_children:
            self.archive_structure_filter_state = "ready"
            return
        if self.archive_structure_filter_thread is not None:
            return
        self.archive_structure_filter_state = "warming"
        self.append_archive_log("Archive Browser activation timing | cause=structure_filter | start=background", verbose=True)
        worker = ArchiveStructureFilterWorker(self.archive_entries)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._handle_archive_structure_filter_complete)
        worker.error.connect(self._handle_archive_structure_filter_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._cleanup_archive_structure_filter_refs)
        self.archive_structure_filter_worker = worker
        self.archive_structure_filter_thread = thread
        try:
            thread.start(QThread.LowPriority)
        except Exception:
            thread.start()

    def _handle_archive_structure_filter_complete(self, result: object) -> None:
        if self._shutting_down:
            _record_archive_filter_worker_lifecycle(
                self,
                "archive_structure_filter_result_ignored",
                reason="cancelled_by_shutdown",
            )
            return
        payload = result if isinstance(result, Mapping) else {}
        children = payload.get("structure_children")
        self.archive_structure_filter_children = children if isinstance(children, dict) else {}
        self.archive_structure_filter_state = "ready" if self.archive_structure_filter_children else "idle"
        self.append_archive_log(
            f"Archive Browser activation timing | cause=structure_filter | ready={len(self.archive_structure_filter_children):,}",
            verbose=True,
        )
        self._rebuild_archive_structure_filter_controls(defer_missing_children=True)

    def _handle_archive_structure_filter_error(self, message: str) -> None:
        self.archive_structure_filter_state = "failed"
        self.append_archive_log(f"Warning: archive folder filters could not be built: {message}")

    def _cleanup_archive_structure_filter_refs(
        self,
        thread: Optional[QThread] = None,
        worker: Optional[ArchiveStructureFilterWorker] = None,
    ) -> None:
        if thread is None:
            sender = self.sender()
            thread = sender if isinstance(sender, QThread) else self.archive_structure_filter_thread
        worker = self.archive_structure_filter_worker if worker is None else worker
        if thread is not None:
            try:
                if not thread.wait(0):
                    QTimer.singleShot(
                        1,
                        lambda target_thread=thread, target_worker=worker: self._cleanup_archive_structure_filter_refs(
                            target_thread,
                            target_worker,
                        ),
                    )
                    return
            except RuntimeError:
                pass
        if self.archive_structure_filter_thread is thread and self.archive_structure_filter_worker is worker:
            self.archive_structure_filter_thread = None
            self.archive_structure_filter_worker = None
        if thread is not None:
            try:
                thread.deleteLater()
            except RuntimeError:
                pass

    def _apply_archive_filter(self) -> None:
        self._capture_archive_controls_scroll_for_filter()
        self._mark_archive_browser_render_stale()
        if self.archive_active_asset_catalog_scope:
            self.archive_active_asset_catalog_scope = ""
            self.archive_clear_asset_scope_button.setVisible(False)
            if hasattr(self, "archive_scope_banner_label"):
                self.archive_scope_banner_label.clear()
                self.archive_scope_banner_label.setVisible(False)
            self.archive_filter_edit.setPlaceholderText("Include path/item-name filter or glob, e.g. Vow of the Dead King or */texture/*")
            self.archive_package_filter_hint_label.setText("Exclude accepts semicolon-separated substrings or globs.")
        self.pending_archive_preview_request = None
        self.scheduled_archive_preview_request = None
        self.archive_preview_debounce_timer.stop()
        self._stop_archive_native_preview_prefetch()
        if self.archive_preview_worker is not None:
            _record_archive_filter_worker_lifecycle(
                self,
                "archive_preview_worker_cancelled",
                reason="cancelled_by_filter_change",
            )
            try:
                self.archive_preview_worker.stop()
            except Exception as exc:
                _record_archive_filter_worker_lifecycle(
                    self,
                    "archive_preview_worker_failed",
                    reason="worker_failed",
                    error=str(exc),
                )
        self._stop_archive_preview_loading_indicator(success=None)
        if self.worker_thread is not None:
            if self.archive_filter_worker is not None:
                self.archive_filter_apply_pending = True
                _record_archive_filter_worker_lifecycle(
                    self,
                    "archive_filter_worker_cancelled",
                    reason="cancelled_by_filter_change",
                )
                self.archive_filter_worker.stop()
                self._set_archive_load_progress("Stopping previous archive filter...", phase="Stopping")
                self.set_status_message("Stopping previous archive filter...")
            return
        if not self.archive_entries:
            self.archive_filtered_entries = []
            self.archive_filtered_dds_count = 0
            self.archive_tree_category_entry_indexes = {}
            self.archive_filters_dirty = False
            self._update_archive_filter_button_state()
            self._populate_archive_tree("")
            self._refresh_or_defer_research_archive_picker()
            return
        if self._archive_filter_waits_for_item_search():
            self._ensure_archive_enhanced_index_worker_started()
            wait_text = "Item-name search is loading. Path searches are available; item-name search will run automatically when ready."
            self.archive_filter_requested_signature = self._current_archive_filter_signature()
            self.archive_filter_apply_pending = False
            self.archive_filters_dirty = False
            self._update_archive_filter_button_state()
            self.archive_enhanced_filter_refresh_pending = True
            self._set_archive_load_progress(wait_text, phase="Indexing")
            self.set_status_message(wait_text)
            self.append_archive_log(wait_text)
            self._schedule_archive_pending_enhanced_filter_refresh(500)
            return
        current_filter_state = self._capture_archive_filter_state()
        if self._current_archive_filter_needs_basic_lookup() and self._archive_basic_index_missing_for_lookup():
            self._ensure_archive_basic_index_worker_started()
            wait_text = "Archive lookup indexes are loading. This search will run automatically when lookup is ready."
            self.archive_filter_requested_signature = self._current_archive_filter_signature()
            self.archive_filter_apply_pending = False
            self.archive_filters_dirty = False
            self._update_archive_filter_button_state()
            self.archive_enhanced_filter_refresh_pending = True
            self._set_archive_load_progress(wait_text, phase="Indexing")
            self.set_status_message(wait_text)
            self.append_archive_log(wait_text)
            self._schedule_archive_pending_enhanced_filter_refresh(500)
            return
        current_entry = self._current_archive_entry()
        current_entry_path = current_entry.path if current_entry is not None else ""
        self._start_archive_filter_worker(current_entry_path)

    def _start_archive_filter_worker(
        self,
        preferred_path: str = "",
        *,
        build_category_index: Optional[bool] = None,
    ) -> None:
        filter_text = self.archive_filter_edit.text().strip()
        exclude_filter_text = self.archive_exclude_filter_edit.text().strip()
        extension_filter = self._combo_value(self.archive_extension_filter_combo)
        package_filter_text = self.archive_package_filter_edit.text().strip()
        structure_filter = self._current_archive_structure_filter_value()
        self.archive_structure_filter_pending_value = structure_filter
        role_filter = self._combo_value(self.archive_role_filter_combo)
        exclude_common_technical_suffixes = self.archive_exclude_common_technical_checkbox.isChecked()
        min_size_kb = self.archive_min_size_spin.value()
        previewable_only = self.archive_previewable_only_checkbox.isChecked()
        if build_category_index is None:
            build_category_index = self._archive_category_view_enabled()
        request_signature = self._current_archive_filter_signature()
        self.archive_filter_requested_signature = request_signature
        self.archive_filter_apply_pending = False
        self._mark_archive_browser_render_stale()
        self._reset_archive_load_progress()
        self._set_archive_load_progress("Preparing archive filter...", phase="Filtering")
        self.set_status_message("Applying archive filters...")
        self.append_archive_log("Applying archive filters...")
        performance_settings = self._current_archive_performance_settings()

        worker = ArchiveFilterWorker(
            self.archive_entries,
            entries_by_extension=self.archive_entries_by_extension,
            entries_by_role=self.archive_entries_by_role,
            entries_by_normalized_path=self.archive_entries_by_normalized_path,
            entries_by_basename=self.archive_entries_by_basename,
            archive_name_search_index=self.archive_name_search_index,
            request_signature=request_signature,
            preferred_path=preferred_path,
            build_tree_index=self._archive_folder_tree_enabled(),
            filter_text=filter_text,
            exclude_filter_text=exclude_filter_text,
            extension_filter=extension_filter,
            package_filter_text=package_filter_text,
            structure_filter=structure_filter,
            role_filter=role_filter,
            exclude_common_technical_suffixes=exclude_common_technical_suffixes,
            min_size_kb=min_size_kb,
            previewable_only=previewable_only,
            build_category_index=bool(build_category_index),
            item_search_aliases=self.archive_item_search_aliases,
            item_display_names=self.archive_item_display_names,
            item_exact_display_names=self.archive_item_exact_display_names,
            item_related_display_names=self.archive_item_related_display_names,
            sort_column=self.archive_tree_sort_column,
            sort_order=self.archive_tree_sort_order,
            native_archive_acceleration=performance_settings.native_archive_acceleration,
            resource_profile=performance_settings.resource_profile,
            record_runtime_event=getattr(self, "_record_runtime_event", None),
        )
        thread = QThread(self)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.log_message.connect(self._append_verbose_archive_log)
        worker.progress_changed.connect(self._handle_archive_scan_progress)
        worker.completed.connect(self._handle_archive_filter_complete)
        worker.error.connect(self._handle_worker_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._cleanup_archive_filter_worker_refs)

        self.archive_filter_worker = worker
        self.worker_thread = thread
        self.set_busy(True, build_mode=False)
        self._restore_archive_controls_scroll_after_filter()
        thread.start()

    def _cleanup_archive_filter_worker_refs(
        self,
        thread: Optional[QThread] = None,
        worker: Optional[ArchiveFilterWorker] = None,
    ) -> None:
        if thread is None:
            sender = self.sender()
            thread = sender if isinstance(sender, QThread) else self.worker_thread
        worker = self.archive_filter_worker if worker is None else worker
        if thread is not None:
            try:
                if not thread.wait(0):
                    QTimer.singleShot(
                        1,
                        lambda target_thread=thread, target_worker=worker: self._cleanup_archive_filter_worker_refs(
                            target_thread,
                            target_worker,
                        ),
                    )
                    return
            except RuntimeError:
                pass
        if self.worker_thread is thread and self.archive_filter_worker is worker:
            self._cleanup_worker_refs(thread)
        if thread is not None:
            try:
                thread.deleteLater()
            except RuntimeError:
                pass

    def _handle_archive_filter_complete(self, result: object) -> None:
        self._flush_archive_scan_progress()
        payload = result if isinstance(result, dict) else {}
        browser_state = payload.get("browser_state") if isinstance(payload.get("browser_state"), dict) else {}
        request_signature = tuple(payload.get("request_signature") or ())
        preferred_path = str(payload.get("preferred_path", "") or "").strip()
        if request_signature and request_signature != self._current_archive_filter_signature():
            _record_archive_filter_worker_lifecycle(
                self,
                "archive_filter_result_ignored",
                reason="stale_result_ignored",
                request_signature=request_signature,
            )
            self.archive_filters_dirty = True
            self._update_archive_filter_button_state()
            stale_text = "Archive filter inputs changed while results were still loading. Press Apply Filters to refresh."
            self._set_archive_load_progress(stale_text, phase="Stale", percent=0, allow_decrease=True)
            self.set_status_message(stale_text)
            return
        self.archive_filtered_entries = (
            browser_state.get("filtered_entries", [])
            if isinstance(browser_state.get("filtered_entries"), list)
            else []
        )
        self.archive_tree_child_folders = (
            browser_state.get("tree_child_folders", {})
            if isinstance(browser_state.get("tree_child_folders"), dict)
            else {}
        )
        self.archive_tree_direct_files = (
            browser_state.get("tree_direct_files", {})
            if isinstance(browser_state.get("tree_direct_files"), dict)
            else {}
        )
        self.archive_tree_folder_entry_indexes = (
            browser_state.get("tree_folder_entry_indexes", {})
            if isinstance(browser_state.get("tree_folder_entry_indexes"), dict)
            else {}
        )
        self.archive_tree_folder_preview_stats = (
            browser_state.get("tree_folder_preview_stats", {})
            if isinstance(browser_state.get("tree_folder_preview_stats"), dict)
            else {}
        )
        self.archive_tree_category_entry_indexes = (
            browser_state.get("category_entry_indexes", {})
            if isinstance(browser_state.get("category_entry_indexes"), dict)
            else {}
        )
        self.archive_tree_index_ready = bool(browser_state.get("tree_index_ready", True))
        self.archive_filtered_dds_count = int(browser_state.get("dds_count", 0))
        self.archive_filters_dirty = False
        self.archive_enhanced_filter_refresh_pending = False
        self._update_archive_filter_button_state()
        self._set_archive_load_progress("Rendering archive browser view...", phase="Rendering", percent=90)
        self._set_archive_warmup_overlay(
            True,
            "Preparing Archive Browser View",
            (
                "Rendering the browser from the prepared cache. Large views stream through the virtual model; "
                "use filters or Folders view for narrower browsing."
            ),
            fmt="Rendering...",
        )
        self.set_status_message("Rendering archive browser view...")
        self._restore_archive_controls_scroll_after_filter()
        QTimer.singleShot(
            0,
            lambda preferred_path=preferred_path: self._finalize_archive_filter_complete(preferred_path),
        )

    def _finalize_archive_filter_complete(self, preferred_path: str) -> None:
        def finish_filter_render() -> None:
            self._refresh_or_defer_research_archive_picker()
            filtered_entries = len(self.archive_filtered_entries)
            completion_text = f"Applied archive filters. Showing {filtered_entries:,} entries."
            self._set_archive_list_status(completion_text)
            self._set_archive_warmup_overlay(False)
            self.append_archive_log(completion_text)
            self._restore_archive_controls_scroll_after_filter()
            self.archive_controls_scroll_filter_anchor = None
            self._finish_startup_benchmark_search_after_filter()
            self._maybe_release_startup_after_archive_ready()

        defer_default_selection = bool(getattr(self, "archive_startup_autoload_defer_preview", False)) or self._startup_benchmark_enabled()
        self.archive_startup_autoload_defer_preview = False
        self._populate_archive_tree(
            preferred_path,
            rebuild_index=False,
            on_complete=finish_filter_render,
            defer_default_selection=defer_default_selection,
        )


__all__ = ["ArchiveFilterWorkerMixin"]
