"""Archive lookup and search index worker orchestration."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import Path

from PySide6.QtCore import QThread, QTimer

from cdmw.services.archive_workflow_service import ArchiveNameSearchIndex
from cdmw.workers.archive_workers import (
    ArchiveBasicIndexWorker,
    ArchiveDerivedIndexCacheWriteWorker,
    ArchiveEnhancedIndexWorker,
)


class ArchiveIndexWorkerMixin:
    """Path lookup, item-name search, and derived cache workers."""

    def _start_archive_basic_index_worker(self) -> None:
        if self._shutting_down or not self.archive_entries:
            self.archive_basic_index_state = "idle"
            return
        if self.archive_basic_index_thread is not None:
            return
        if (
            self.archive_entries_by_normalized_path
            and self.archive_entries_by_basename
            and self.archive_entries_by_extension
            and self.archive_entries_by_role
        ):
            self.archive_basic_index_state = "ready"
            return
        self.archive_basic_index_state = "warming"
        request_id = int(getattr(self, "archive_basic_index_request_id", 0) or 0) + 1
        self.archive_basic_index_request_id = request_id
        performance_settings = self._current_archive_performance_settings()
        package_root_text = self.archive_package_root_edit.text().strip()
        worker = ArchiveBasicIndexWorker(
            Path(package_root_text).expanduser(),
            self.archive_cache_root,
            tuple(self.archive_entries),
            native_archive_acceleration=performance_settings.native_archive_acceleration,
            request_id=request_id,
            entry_metadata_signature=self.archive_entry_metadata_signature,
            entry_metadata_sources=self.archive_entry_metadata_sources,
            shard_entry_signatures=getattr(self, "archive_scan_shard_entry_signatures", {}) or {},
            shard_entry_counts=getattr(self, "archive_scan_shard_entry_counts", {}) or {},
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.log_message.connect(self.append_log)
        worker.log_message.connect(self.append_archive_log)
        worker.progress_changed.connect(
            lambda current, total, detail, rid=request_id: self._handle_archive_basic_index_progress(
                current,
                total,
                detail,
                request_id=rid,
            )
        )
        worker.completed.connect(self._handle_archive_basic_index_complete)
        worker.error.connect(
            lambda message, rid=request_id: self._handle_archive_basic_index_error(message, request_id=rid)
        )
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda rid=request_id, owner_thread=thread: self._cleanup_archive_basic_index_refs(rid, owner_thread)
        )
        self.archive_basic_index_worker = worker
        self.archive_basic_index_thread = thread
        try:
            thread.start(QThread.LowPriority)
        except Exception:
            thread.start()

    def _handle_archive_basic_index_progress(
        self,
        current: int,
        total: int,
        detail: str,
        *,
        request_id: int,
    ) -> None:
        if self._shutting_down or int(request_id) != int(getattr(self, "archive_basic_index_request_id", 0) or 0):
            return
        self._handle_archive_scan_progress(current, total, detail)

    def _handle_archive_basic_index_complete(self, result: object) -> None:
        if self._shutting_down:
            return
        payload = result if isinstance(result, Mapping) else {}
        request_id = int(payload.get("request_id", getattr(self, "archive_basic_index_request_id", 0)) or 0)
        if request_id != int(getattr(self, "archive_basic_index_request_id", 0) or 0):
            self._record_runtime_event(
                "archive_basic_index_result_ignored",
                reason="stale_result_ignored",
                request_id=request_id,
                current_request_id=getattr(self, "archive_basic_index_request_id", 0),
            )
            return
        path_index = payload.get("path_index")
        basename_index = payload.get("basename_index")
        extension_index = payload.get("extension_index")
        role_index = payload.get("role_index")
        if isinstance(path_index, Mapping):
            self.archive_entries_by_normalized_path = path_index
        if isinstance(basename_index, Mapping):
            self.archive_entries_by_basename = basename_index
        if isinstance(extension_index, Mapping):
            self.archive_entries_by_extension = extension_index
            self.archive_extension_counts = Counter(
                {
                    str(extension): len(items)
                    for extension, items in extension_index.items()
                    if extension
                }
            )
        if isinstance(role_index, Mapping):
            self.archive_entries_by_role = role_index
        self.archive_basic_index_state = "ready"
        if (
            self.archive_item_icon_preload_pending_after_ready
            or self.archive_item_icon_preload_queue
            or self.archive_item_icon_priority_queue
        ):
            self.archive_item_icon_negative_cache.clear()
            if self.archive_item_icon_priority_queue:
                self.archive_item_icon_preload_pending_after_ready = False
                self._start_archive_item_icon_priority_warmup()
            elif self.archive_item_icon_preload_queue:
                self.archive_item_icon_preload_pending_after_ready = False
                if not self.archive_item_icon_preload_timer.isActive():
                    self.archive_item_icon_preload_timer.start(0)
            else:
                self.archive_item_icon_preload_pending_after_ready = False
                self._schedule_archive_asset_catalog_icon_preload(delay_ms=0)
        elapsed_s = max(0.0, float(payload.get("elapsed_s", 0.0) or 0.0))
        self._record_runtime_event(
            "basic_indexes_ready",
            elapsed_s=elapsed_s,
            native_used=bool(payload.get("native_used")),
            path_keys=len(self.archive_entries_by_normalized_path),
            basename_keys=len(self.archive_entries_by_basename),
            extension_keys=len(self.archive_entries_by_extension),
            role_keys=len(self.archive_entries_by_role),
        )
        if bool(payload.get("cache_loaded")):
            self.append_archive_log(f"Path lookup loaded from cache in {elapsed_s:.2f}s.")
        else:
            self.append_archive_log(f"Path lookup ready in {elapsed_s:.2f}s.")
        self._record_archive_memory_audit("archive_basic_index_ready", log_if_high=True)
        self._set_archive_list_status("Archive list available")
        self._rebuild_archive_extension_filter_choices()
        self._refresh_archive_browser_if_pending(reason="basic_indexes_ready")
        self._try_apply_startup_saved_filters()
        self._maybe_release_startup_after_archive_ready()

    def _handle_archive_basic_index_error(self, message: str, *, request_id: int | None = None) -> None:
        if request_id is not None and int(request_id) != int(getattr(self, "archive_basic_index_request_id", 0) or 0):
            return
        self.archive_basic_index_state = "failed"
        self.append_archive_log(f"Warning: path lookup could not be built: {message}")
        self.set_status_message("Path lookup failed; direct archive browsing remains available.", error=True)
        self._try_apply_startup_saved_filters()
        self._maybe_release_startup_after_archive_ready()

    def _cleanup_archive_basic_index_refs(self, _request_id: int = 0, owner_thread: object | None = None) -> None:
        if owner_thread is not None and self.archive_basic_index_thread is not owner_thread:
            return
        self.archive_basic_index_thread = None
        self.archive_basic_index_worker = None
        if self.archive_deferred_basic_index_start_pending and not self._shutting_down:
            QTimer.singleShot(0, self._start_archive_basic_index_worker)
        self._maybe_release_startup_after_archive_ready()

    def _start_archive_enhanced_index_worker(self) -> None:
        if self._shutting_down or not self.archive_entries:
            self.archive_enhanced_index_state = "idle"
            self.archive_enhanced_index_activity = "idle"
            return
        if self.archive_enhanced_index_thread is not None:
            return
        self.archive_enhanced_index_auto_prewarm_pending = False
        self.archive_enhanced_index_state = "warming"
        self.archive_enhanced_index_activity = "loading"
        request_id = int(getattr(self, "archive_enhanced_index_request_id", 0) or 0) + 1
        self.archive_enhanced_index_request_id = request_id
        self._set_archive_load_progress("Loading archive search cache...", phase="Indexing")
        self.set_status_message("Loading archive search cache...")
        package_root_text = self.archive_package_root_edit.text().strip()
        worker = ArchiveEnhancedIndexWorker(
            Path(package_root_text).expanduser(),
            self.archive_cache_root,
            tuple(self.archive_entries),
            request_id=request_id,
            entry_metadata_signature=self.archive_entry_metadata_signature,
            entry_metadata_sources=self.archive_entry_metadata_sources,
            shard_entry_signatures=getattr(self, "archive_scan_shard_entry_signatures", {}) or {},
            shard_entry_counts=getattr(self, "archive_scan_shard_entry_counts", {}) or {},
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.log_message.connect(self.append_log)
        worker.log_message.connect(self.append_archive_log)
        worker.progress_changed.connect(
            lambda current, total, detail, rid=request_id: self._handle_archive_enhanced_index_progress(
                current,
                total,
                detail,
                request_id=rid,
            )
        )
        worker.completed.connect(self._handle_archive_enhanced_index_complete)
        worker.error.connect(
            lambda message, rid=request_id: self._handle_archive_enhanced_index_error(message, request_id=rid)
        )
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda rid=request_id, owner_thread=thread: self._cleanup_archive_enhanced_index_refs(rid, owner_thread)
        )
        self.archive_enhanced_index_worker = worker
        self.archive_enhanced_index_thread = thread
        try:
            thread.start(QThread.LowPriority)
        except Exception:
            thread.start()

    def _handle_archive_enhanced_index_progress(
        self,
        current: int,
        total: int,
        detail: str,
        *,
        request_id: int | None = None,
    ) -> None:
        if self._shutting_down:
            return
        if request_id is not None and int(request_id) != int(getattr(self, "archive_enhanced_index_request_id", 0) or 0):
            return
        detail_text = str(detail or "Preparing archive search cache...")
        lower_detail = detail_text.lower()
        if "load" in lower_detail:
            self.archive_enhanced_index_activity = "loading"
        elif "build" in lower_detail:
            self.archive_enhanced_index_activity = "building"
        self._handle_archive_scan_progress(current, total, detail_text)

    def _handle_archive_enhanced_index_complete(self, result: object) -> None:
        if self._shutting_down:
            return
        payload = result if isinstance(result, Mapping) else {}
        request_id = int(payload.get("request_id", getattr(self, "archive_enhanced_index_request_id", 0)) or 0)
        if request_id != int(getattr(self, "archive_enhanced_index_request_id", 0) or 0):
            self._record_runtime_event(
                "archive_enhanced_index_result_ignored",
                reason="stale_result_ignored",
                request_id=request_id,
                current_request_id=getattr(self, "archive_enhanced_index_request_id", 0),
            )
            return
        name_search_index = payload.get("name_search_index")
        self.archive_name_search_index = name_search_index if isinstance(name_search_index, ArchiveNameSearchIndex) else None
        self.archive_item_search_aliases = dict(payload.get("item_search_aliases", {}) or {})
        self.archive_item_display_names = dict(payload.get("item_display_names", {}) or {})
        self.archive_item_exact_display_names = dict(payload.get("item_exact_display_names", {}) or {})
        self.archive_item_related_display_names = dict(payload.get("item_related_display_names", {}) or {})
        self.archive_item_asset_catalog = [
            dict(row)
            for row in (payload.get("item_asset_catalog", []) or [])
            if isinstance(row, Mapping)
        ]
        self.archive_enhanced_index_state = "ready"
        self.archive_enhanced_index_activity = "idle"
        cache_loaded = bool(payload.get("cache_loaded"))
        self.archive_derived_cache_write_pending = not cache_loaded
        self.archive_asset_catalog_button.setEnabled(bool(self.archive_item_asset_catalog))
        self.archive_material_finder_button.setEnabled(bool(self._archive_material_catalog_rows()))
        self._clear_archive_asset_catalog_icon_cache()
        self._schedule_archive_asset_catalog_icon_preload()
        self._invalidate_archive_browser_name_columns()
        if cache_loaded:
            self.append_archive_log("Archive search cache loaded.")
        else:
            self.append_archive_log("Archive search cache ready.")
        self._record_archive_memory_audit("archive_name_search_ready", log_if_high=True)
        self._set_archive_list_status("Archive list available")
        if self.archive_initial_sort_apply_pending:
            self._schedule_archive_initial_sort_after_first_paint(150)
        if self.archive_enhanced_filter_refresh_pending:
            self._schedule_archive_pending_enhanced_filter_refresh(150)
        self._try_apply_startup_saved_filters()
        if not cache_loaded:
            QTimer.singleShot(0, self._start_archive_derived_index_cache_writer)
        self._maybe_release_startup_after_archive_ready()

    def _handle_archive_enhanced_index_error(self, message: str, *, request_id: int | None = None) -> None:
        if request_id is not None and int(request_id) != int(getattr(self, "archive_enhanced_index_request_id", 0) or 0):
            return
        self.archive_enhanced_index_state = "failed"
        self.archive_enhanced_index_activity = "idle"
        self.append_archive_log(f"Warning: item-name search could not be built: {message}")
        self.set_status_message("Item-name search failed; path browsing remains available.", error=True)
        self._try_apply_startup_saved_filters()
        self._maybe_release_startup_after_archive_ready()

    def _cleanup_archive_enhanced_index_refs(self, _request_id: int = 0, owner_thread: object | None = None) -> None:
        if owner_thread is not None and self.archive_enhanced_index_thread is not owner_thread:
            return
        self.archive_enhanced_index_thread = None
        self.archive_enhanced_index_worker = None
        if self.archive_deferred_enhanced_index_start_pending and not self._shutting_down:
            QTimer.singleShot(0, self._start_archive_enhanced_index_worker)
        self._maybe_release_startup_after_archive_ready()

    def _start_archive_derived_index_cache_writer(self) -> None:
        if self._shutting_down:
            self.archive_derived_cache_write_pending = False
            return
        if not self.archive_derived_cache_write_pending:
            return
        if self.archive_derived_cache_thread is not None:
            return
        if not self.archive_entries:
            self.archive_derived_cache_write_pending = False
            return
        package_root_text = self.archive_package_root_edit.text().strip()
        if not package_root_text:
            self.archive_derived_cache_write_pending = False
            return

        self._handle_archive_scan_progress(0, 0, "Saving archive search cache...")
        self.archive_derived_cache_write_pending = False
        worker = ArchiveDerivedIndexCacheWriteWorker(
            Path(package_root_text).expanduser(),
            self.archive_cache_root,
            self.archive_entries,
            item_search_aliases=self.archive_item_search_aliases,
            item_display_names=self.archive_item_display_names,
            item_exact_display_names=self.archive_item_exact_display_names,
            item_related_display_names=self.archive_item_related_display_names,
            item_asset_catalog=self.archive_item_asset_catalog,
            archive_name_search_index=self.archive_name_search_index,
            entry_metadata_signature=self.archive_entry_metadata_signature,
            entry_metadata_sources=self.archive_entry_metadata_sources,
        )
        thread = QThread(self)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.log_message.connect(self.append_log)
        worker.log_message.connect(self.append_archive_log)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup_archive_derived_cache_refs)

        self.archive_derived_cache_worker = worker
        self.archive_derived_cache_thread = thread
        try:
            thread.start(QThread.LowPriority)
        except Exception:
            thread.start()

    def _cleanup_archive_derived_cache_refs(self) -> None:
        self.archive_derived_cache_thread = None
        self.archive_derived_cache_worker = None
        if self.archive_derived_cache_write_pending and not self._shutting_down:
            QTimer.singleShot(0, self._start_archive_derived_index_cache_writer)
        else:
            self._set_archive_list_status("Archive list available")
        self._maybe_release_startup_after_archive_ready()


__all__ = ["ArchiveIndexWorkerMixin"]
