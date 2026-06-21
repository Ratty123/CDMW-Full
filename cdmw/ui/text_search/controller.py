"""Controller mixins for Text Search UI coordination."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from time import strftime
from typing import Dict, List, Optional, Sequence

from PySide6.QtCore import QThread, Qt
from PySide6.QtWidgets import QFileDialog, QTreeWidgetItem

from cdmw.core.text_search import (
    DEFAULT_TEXT_SEARCH_EXTENSIONS,
    TextSearchResult,
    TextSearchRunStats,
)
from cdmw.models import ArchiveEntry
from cdmw.services.workspace_layout import workspace_paths
from cdmw.ui.text_search.workers import TextSearchWorker, shutdown_thread as _shutdown_thread


class TextSearchSettingsMixin:
    def _browse_loose_root(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select Loose Root", self.loose_root_edit.text() or str(self.base_dir))
        if selected:
            self.loose_root_edit.setText(selected)

    def _browse_export_root(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select Export Root",
            self.export_root_edit.text() or str(self.base_dir),
        )
        if selected:
            self.export_root_edit.setText(selected)

    def _handle_source_changed(self) -> None:
        self._apply_source_state()
        self.schedule_settings_save()

    def _apply_source_state(self) -> None:
        loose_mode = self.source_combo.currentData() == "loose"
        self.loose_root_label.setVisible(loose_mode)
        self.loose_root_edit.setVisible(loose_mode)
        self.loose_root_browse_button.setVisible(loose_mode)

    def _save_settings(self) -> None:
        if not self._settings_ready:
            return
        self.settings.setValue("text_search/source_kind", str(self.source_combo.currentData()))
        self.settings.setValue("text_search/query", self.query_edit.text())
        self.settings.setValue("text_search/path_filter", self.path_filter_edit.text())
        self.settings.setValue("text_search/extensions", self.extensions_edit.text())
        self.settings.setValue("text_search/loose_root", self.loose_root_edit.text())
        self.settings.setValue("text_search/export_root", self.export_root_edit.text())
        self.settings.setValue("text_search/case_sensitive", self.case_sensitive_checkbox.isChecked())
        self.settings.setValue("text_search/regex_enabled", self.regex_checkbox.isChecked())
        self.settings.setValue("text_search/preview_wrap", self.preview_wrap_checkbox.isChecked())
        self.settings.setValue("text_search/preview_find_case_sensitive", self.preview_find_case_checkbox.isChecked())
        self.settings.setValue("text_search/preview_font_size", self.preview_text_edit.font().pointSize())
        self.settings.sync()

    def schedule_settings_save(self, *_args: object) -> None:
        if not self._settings_ready:
            return
        self._settings_save_timer.start()

    def flush_settings_save(self) -> None:
        if self._settings_save_timer.isActive():
            self._settings_save_timer.stop()
        self._save_settings()

    def _load_settings(self) -> None:
        self._settings_ready = False
        source_kind = str(self.settings.value("text_search/source_kind", "archive"))
        index = self.source_combo.findData(source_kind)
        if index >= 0:
            self.source_combo.setCurrentIndex(index)
        self.query_edit.setText(str(self.settings.value("text_search/query", "")))
        self.path_filter_edit.setText(str(self.settings.value("text_search/path_filter", "")))
        self.extensions_edit.setText(str(self.settings.value("text_search/extensions", DEFAULT_TEXT_SEARCH_EXTENSIONS)))
        self.loose_root_edit.setText(str(self.settings.value("text_search/loose_root", "")))
        self.export_root_edit.setText(
            str(self.settings.value("text_search/export_root", str(workspace_paths(self.base_dir)["text_search_export_root"].resolve())))
        )
        self.case_sensitive_checkbox.setChecked(
            str(self.settings.value("text_search/case_sensitive", "false")).lower() in {"1", "true", "yes"}
        )
        self.regex_checkbox.setChecked(
            str(self.settings.value("text_search/regex_enabled", "false")).lower() in {"1", "true", "yes"}
        )
        self.preview_wrap_checkbox.setChecked(
            str(self.settings.value("text_search/preview_wrap", "false")).lower() in {"1", "true", "yes"}
        )
        self.preview_find_case_checkbox.setChecked(
            str(self.settings.value("text_search/preview_find_case_sensitive", "false")).lower() in {"1", "true", "yes"}
        )
        try:
            preview_font_size = int(self.settings.value("text_search/preview_font_size", 10))
        except (TypeError, ValueError):
            preview_font_size = 10
        self.preview_text_edit.set_font_size(preview_font_size)


class TextSearchControllerMixin:
    def set_external_busy(self, busy: bool) -> None:
        self.external_busy = busy
        self._update_controls()

    def is_busy(self) -> bool:
        return self.search_thread is not None

    def set_archive_entries(self, entries: Sequence[ArchiveEntry], package_root_text: str = "") -> None:
        self.archive_entries = entries if isinstance(entries, list) else list(entries)
        self.archive_package_root_text = package_root_text.strip()
        if self.source_combo.currentData() == "archive" and not self.search_results:
            self.results_summary_label.setText(
                f"Archive source ready: {len(self.archive_entries):,} scanned entry(s) available for text search."
            )

    def review_archive_entry(
        self,
        entry: ArchiveEntry,
        *,
        highlight_query: str,
    ) -> bool:
        query = highlight_query.strip()
        if not query:
            self.status_message_requested.emit("No highlight query was provided for the selected reference.", True)
            return False
        if self.search_thread is not None:
            self.status_message_requested.emit("Text Search is busy. Wait for the current search to finish first.", True)
            return False

        self._preview_debounce_timer.stop()
        self.pending_preview_result = None
        self.scheduled_preview_result = None
        self.preview_request_id += 1
        if self.preview_worker is not None:
            self.preview_worker.stop()

        archive_index = self.source_combo.findData("archive")
        if archive_index >= 0:
            self.source_combo.setCurrentIndex(archive_index)
        self.query_edit.setText(query)

        result = TextSearchResult(
            source_kind="archive",
            relative_path=entry.path.replace("\\", "/"),
            extension=entry.extension,
            match_count=1,
            snippet="Opened from Research -> References for targeted XML/material review.",
            package_label=entry.package_label,
            archive_entry=entry,
        )
        self.search_results = [result]
        self.current_preview_result = result
        self.last_search_query = query
        self.last_search_case_sensitive = False
        self.last_search_regex_enabled = False
        self.last_search_stats = TextSearchRunStats(source_kind="archive", candidate_count=1, searched_count=1)

        self.results_tree.blockSignals(True)
        self.results_tree.clear()
        item = self._build_result_item(0, result)
        self.results_tree.addTopLevelItem(item)
        self.results_tree.blockSignals(False)
        self.results_tree.setCurrentItem(item)
        self._column_autofit_timer.start()

        file_name = PurePosixPath(result.relative_path).name or result.relative_path
        self.results_summary_label.setText("Opened 1 archive text file from Research for focused review.")
        self.search_progress_label.setText("Reference review ready.")
        self.search_progress_bar.setRange(0, 1)
        self.search_progress_bar.setValue(1)
        self.search_progress_bar.setFormat("Ready")
        self.append_log(f"Opened {result.relative_path} in Text Search for reference review (highlight: {query}).")
        self.status_message_requested.emit(f"Opened {file_name} in Text Search and highlighted '{query}'.", False)
        self._update_controls()
        self._schedule_preview(result)
        return True

    def diagnostic_entries(self) -> Dict[str, str]:
        return {
            "text_search_log.txt": self.log_view.toPlainText(),
        }

    def iter_shutdown_workers(self) -> tuple[tuple[str, Optional[QThread], Optional[object]], ...]:
        return (
            ("search_thread", self.search_thread, self.search_worker),
            ("preview_thread", self.preview_thread, self.preview_worker),
        )

    def request_shutdown(self) -> None:
        self.flush_settings_save()
        self._preview_debounce_timer.stop()
        self._clear_pending_result_population()
        if self.search_worker is not None:
            self.search_worker.stop()
        if self.preview_worker is not None:
            self.preview_worker.stop()
        for _name, thread, _worker in self.iter_shutdown_workers():
            _shutdown_thread(thread)

    def shutdown(self) -> None:
        self.request_shutdown()

    def clear_log(self) -> None:
        self.log_view.clear()
        self.search_progress_label.setText("Search log cleared.")
        self.status_message_requested.emit("Text search log cleared.", False)

    def append_log(self, message: str) -> None:
        self.log_view.appendPlainText(f"[{strftime('%H:%M:%S')}] {message}")
        scrollbar = self.log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _update_controls(self) -> None:
        busy = self.search_thread is not None
        can_interact = not busy and not self.external_busy
        self.source_combo.setEnabled(can_interact)
        self.query_edit.setEnabled(can_interact)
        self.path_filter_edit.setEnabled(can_interact)
        self.extensions_edit.setEnabled(can_interact)
        self.loose_root_edit.setEnabled(can_interact and self.source_combo.currentData() == "loose")
        self.loose_root_browse_button.setEnabled(can_interact and self.source_combo.currentData() == "loose")
        self.export_root_edit.setEnabled(can_interact)
        self.export_root_browse_button.setEnabled(can_interact)
        self.case_sensitive_checkbox.setEnabled(can_interact)
        self.regex_checkbox.setEnabled(can_interact)
        self.search_button.setEnabled(can_interact)
        self.stop_button.setEnabled(busy)
        has_results = bool(self.search_results)
        has_selection = bool(self.selected_results())
        self.export_selected_button.setEnabled(can_interact and has_selection)
        self.export_all_button.setEnabled(can_interact and has_results)
        self.results_tree.setEnabled(not busy)
        if hasattr(self, "results_stack"):
            self.results_stack.setCurrentWidget(self.results_tree if has_results or busy else self.results_empty_state)
        self.clear_log_button.setEnabled(not busy)
        has_preview_text = bool(self.preview_text_cache)
        self.preview_find_edit.setEnabled(has_preview_text)
        self.preview_find_prev_button.setEnabled(has_preview_text and bool(self.preview_find_spans))
        self.preview_find_next_button.setEnabled(has_preview_text and bool(self.preview_find_spans))
        self.preview_find_case_checkbox.setEnabled(has_preview_text)
        self.preview_wrap_checkbox.setEnabled(has_preview_text)
        self.preview_font_smaller_button.setEnabled(has_preview_text)
        self.preview_font_larger_button.setEnabled(has_preview_text)

    def selected_results(self) -> List[TextSearchResult]:
        results: List[TextSearchResult] = []
        for item in self.results_tree.selectedItems():
            raw = item.data(0, Qt.UserRole)
            if isinstance(raw, int) and 0 <= raw < len(self.search_results):
                results.append(self.search_results[raw])
        return results

    def current_result(self) -> Optional[TextSearchResult]:
        item = self.results_tree.currentItem()
        if item is None:
            return None
        raw = item.data(0, Qt.UserRole)
        if isinstance(raw, int) and 0 <= raw < len(self.search_results):
            return self.search_results[raw]
        return None

    def current_result_path(self) -> str:
        result = self.current_result()
        return result.relative_path if result is not None else ""

    def current_results(self) -> List[TextSearchResult]:
        return list(self.search_results)

    def apply_regex_preset(self, pattern: str, extensions_text: str = "", path_hint: str = "") -> None:
        self.regex_checkbox.setChecked(True)
        self.query_edit.setText(pattern)
        if extensions_text.strip():
            self.extensions_edit.setText(extensions_text.strip())
        if path_hint.strip():
            self.path_filter_edit.setText(path_hint.strip())
        self.source_combo.setCurrentIndex(max(0, self.source_combo.findData("archive")))
        self.flush_settings_save()
        self.status_message_requested.emit("Regex preset applied to Text Search.", False)

    def start_search(self) -> None:
        if self.external_busy or self.search_thread is not None:
            return
        self._preview_debounce_timer.stop()
        self.pending_preview_result = None
        self.scheduled_preview_result = None
        self.preview_request_id += 1
        if self.preview_worker is not None:
            self.preview_worker.stop()

        query = self.query_edit.text().strip()
        source_kind = str(self.source_combo.currentData())
        if not self.regex_checkbox.isChecked() and query in {".", "*", "?"}:
            self.append_log(
                f"Note: Regex is off, so '{query}' is treated as a literal character. Enable Regex for wildcard-style matching."
            )
        loose_root = None
        if source_kind == "archive":
            if not self.archive_entries:
                message = "Scan archives first, or switch the source to a loose folder."
                self.status_message_requested.emit(message, True)
                self.append_log(f"ERROR: {message}")
                return
        else:
            loose_root_text = self.loose_root_edit.text().strip()
            if not loose_root_text:
                message = "Select a loose root folder before searching loose files."
                self.status_message_requested.emit(message, True)
                self.append_log(f"ERROR: {message}")
                return
            loose_root = Path(loose_root_text).expanduser()
            if not loose_root.exists() or not loose_root.is_dir():
                message = f"Loose root does not exist or is not a folder: {loose_root}"
                self.status_message_requested.emit(message, True)
                self.append_log(f"ERROR: {message}")
                return

        self.search_results = []
        self._clear_pending_result_population()
        self.results_tree.clear()
        self.results_stack.setCurrentWidget(self.results_tree)
        self.current_preview_result = None
        self.last_search_stats = TextSearchRunStats(source_kind=source_kind, candidate_count=0, searched_count=0)
        self.last_search_query = query
        self.last_search_case_sensitive = self.case_sensitive_checkbox.isChecked()
        self.last_search_regex_enabled = self.regex_checkbox.isChecked()
        self.preview_title_label.setText("Searching...")
        self.preview_meta_label.setText("Working...")
        self.preview_detail_label.setText("")
        self.preview_text_edit.setPlainText("")
        self.preview_text_edit.set_match_selections([])
        self.preview_search_spans = []
        self.preview_find_spans = []
        self.preview_find_active_index = -1
        self.preview_text_cache = ""
        self.preview_find_status_label.setText("Searching...")
        self.results_summary_label.setText("Search in progress...")
        self.search_progress_label.setText("Preparing search...")
        self.search_progress_bar.setRange(0, 0)
        self.search_progress_bar.setFormat("Working...")

        worker = TextSearchWorker(
            source_kind=source_kind,
            query=query,
            extension_text=self.extensions_edit.text().strip(),
            path_filter=self.path_filter_edit.text().strip(),
            case_sensitive=self.case_sensitive_checkbox.isChecked(),
            regex_enabled=self.regex_checkbox.isChecked(),
            archive_entries=self.archive_entries,
            loose_root=loose_root,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.log_message.connect(self.append_log)
        worker.progress_changed.connect(self._handle_progress)
        worker.completed.connect(self._handle_search_complete)
        worker.cancelled.connect(self._handle_search_cancelled)
        worker.error.connect(self._handle_search_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup_search_refs)
        self.search_worker = worker
        self.search_thread = thread
        self._update_controls()
        self.append_log(f"Starting text search in {'archive entries' if source_kind == 'archive' else 'loose files'}.")
        self.status_message_requested.emit("Starting text search...", False)
        thread.start()

    def stop_search(self) -> None:
        if self.search_worker is not None:
            self.search_worker.stop()

    def _clear_pending_result_population(self) -> None:
        self._results_population_timer.stop()
        self._pending_result_indexes = []
        self._pending_result_total = 0
        self._pending_auto_preview_enabled = False

    def _handle_progress(self, current: int, total: int, detail: str) -> None:
        self.search_progress_label.setText(detail)
        if total > 0:
            self.search_progress_bar.setRange(0, total)
            self.search_progress_bar.setValue(min(max(current, 0), total))
            display_value = min(max(current, 0), total)
            self.search_progress_bar.setFormat(f"{display_value} / {total}")
        else:
            self.search_progress_bar.setRange(0, 0)
            self.search_progress_bar.setFormat("Working...")
        self.status_message_requested.emit(detail, False)

    def _handle_search_complete(self, payload: object) -> None:
        self._clear_pending_result_population()
        data = payload if isinstance(payload, dict) else {}
        self.search_results = data.get("results", []) if isinstance(data.get("results"), list) else []
        stats = data.get("stats")
        self.last_search_stats = stats if isinstance(stats, TextSearchRunStats) else TextSearchRunStats(source_kind="archive", candidate_count=0, searched_count=0)
        auto_preview_enabled = len(self.search_results) <= self.AUTO_PREVIEW_RESULT_LIMIT
        self.results_tree.clear()
        summary = (
            f"Scanned {self.last_search_stats.candidate_count:,} candidate file(s). "
            f"Searched {self.last_search_stats.searched_count:,} readable file(s). "
            f"Found {len(self.search_results):,} matching file(s)."
        )
        if self.last_search_stats.decrypted_count:
            summary += f" Decrypted {self.last_search_stats.decrypted_count:,} archive file(s) during search."
        if self.last_search_stats.skipped_read_error_count:
            summary += f" {self.last_search_stats.skipped_read_error_count:,} file(s) could not be read."
        if self.search_results and not auto_preview_enabled:
            summary += " Auto-preview was skipped because the result set is very large."
        self.results_summary_label.setText(summary)
        self._pending_result_indexes = list(range(len(self.search_results)))
        self._pending_result_total = len(self._pending_result_indexes)
        self._pending_auto_preview_enabled = auto_preview_enabled
        if self._pending_result_total:
            self.search_progress_label.setText(f"Populating results... 0 / {self._pending_result_total}")
            self.search_progress_bar.setRange(0, self._pending_result_total)
            self.search_progress_bar.setValue(0)
            self.search_progress_bar.setFormat(f"0 / {self._pending_result_total}")
            self._results_population_timer.start()
        else:
            self._finalize_result_population()
        self.append_log(summary)
        self.status_message_requested.emit(summary, False)

    def _finalize_result_population(self) -> None:
        if self.search_results and self._pending_auto_preview_enabled:
            first_item = self.results_tree.topLevelItem(0)
            if first_item is not None:
                self.results_tree.setCurrentItem(first_item)
        else:
            if self.search_results:
                self.preview_title_label.setText("Large result set")
                self.preview_meta_label.setText(
                    "Select a file to preview. Auto-preview is disabled for large result sets to keep the UI responsive."
                )
            else:
                self.preview_title_label.setText("No matches")
                self.preview_meta_label.setText("No matching file was found for the current query.")
            self.preview_detail_label.setText("")
            self.preview_text_edit.setPlainText("")
            self.preview_text_edit.set_match_selections([])
            self.preview_text_cache = ""
            self.preview_search_spans = []
            self.preview_find_spans = []
            self.preview_find_active_index = -1
            self.preview_find_status_label.setText("No preview loaded.")
        self.search_progress_label.setText("Search complete.")
        self.search_progress_bar.setRange(0, 1)
        self.search_progress_bar.setValue(1)
        self.search_progress_bar.setFormat("Ready")
        self._clear_pending_result_population()
        self.results_stack.setCurrentWidget(self.results_tree if self.search_results else self.results_empty_state)
        self._column_autofit_timer.start()

    def _flush_result_population_batch(self) -> None:
        if not self._pending_result_indexes:
            self._finalize_result_population()
            return
        batch_indexes = self._pending_result_indexes[: self.RESULT_POPULATION_BATCH_SIZE]
        del self._pending_result_indexes[: self.RESULT_POPULATION_BATCH_SIZE]
        batch = [self._build_result_item(index, self.search_results[index]) for index in batch_indexes]
        self.results_tree.setUpdatesEnabled(False)
        self.results_tree.addTopLevelItems(batch)
        self.results_tree.setUpdatesEnabled(True)
        self.results_stack.setCurrentWidget(self.results_tree)
        self._column_autofit_timer.start()
        populated = self._pending_result_total - len(self._pending_result_indexes)
        self.search_progress_label.setText(f"Populating results... {populated} / {self._pending_result_total}")
        self.search_progress_bar.setRange(0, max(1, self._pending_result_total))
        self.search_progress_bar.setValue(populated)
        self.search_progress_bar.setFormat(f"{populated} / {self._pending_result_total}")
        if self._pending_result_indexes:
            self._results_population_timer.start()
            return
        self._finalize_result_population()

    def _build_result_item(self, index: int, result: TextSearchResult) -> QTreeWidgetItem:
        file_name = PurePosixPath(result.relative_path).name or result.relative_path
        item = QTreeWidgetItem(
            [
                file_name,
                f"{result.match_count:,}",
                result.package_label if result.source_kind == "archive" else "Loose file",
                result.relative_path,
                result.extension,
            ]
        )
        item.setToolTip(0, file_name)
        item.setToolTip(2, item.text(2))
        item.setToolTip(3, result.relative_path)
        item.setToolTip(4, result.extension)
        item.setData(0, Qt.UserRole, index)
        return item

    def _handle_search_cancelled(self, message: str) -> None:
        self._clear_pending_result_population()
        self.search_progress_label.setText(message)
        self.search_progress_bar.setRange(0, 1)
        self.search_progress_bar.setValue(0)
        self.search_progress_bar.setFormat("Stopped")
        self.append_log(message)
        self.status_message_requested.emit(message, True)

    def _handle_search_error(self, message: str) -> None:
        self._clear_pending_result_population()
        self.search_progress_label.setText(message)
        self.search_progress_bar.setRange(0, 1)
        self.search_progress_bar.setValue(0)
        self.search_progress_bar.setFormat("Error")
        self.append_log(f"ERROR: {message}")
        self.status_message_requested.emit(message, True)

    def _cleanup_search_refs(self) -> None:
        self.search_thread = None
        self.search_worker = None
        self._update_controls()


__all__ = ["TextSearchControllerMixin", "TextSearchSettingsMixin"]
