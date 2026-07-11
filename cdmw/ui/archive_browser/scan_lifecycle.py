"""Archive scan lifecycle orchestration."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import QObject, QThread, QTimer, QUrl, Qt, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox

from cdmw.constants import ARCHIVE_BROWSER_VIEW_MODE
from cdmw.services.archive_workflow_service import ArchiveNameSearchIndex
from cdmw.domain.archives.filters import archive_browser_sort_is_active
from cdmw.services.diagnostics_service import timing_value as _timing_value
from cdmw.services.archive_environment_service import find_suspicious_archive_tree_roots
from cdmw.ui.shell.lazy_tool_tab import created_tool_widget
from cdmw.workers.archive_scan_workers import ArchiveScanWorker


class _ArchiveScanUiReceiver(QObject):
    """Deliver archive worker results on the window's Qt thread."""

    def __init__(self, window: object) -> None:
        super().__init__(window)  # type: ignore[arg-type]
        self._window = window

    @Slot(str)
    def handle_log(self, message: str) -> None:
        self._window.append_log(message)
        self._window.append_archive_log(message)

    @Slot(int, int, str)
    def handle_progress(self, current: int, total: int, detail: str) -> None:
        self._window._handle_archive_scan_progress(current, total, detail)

    @Slot(object)
    def handle_completed(self, result: object) -> None:
        self._window._handle_archive_scan_complete(result)

    @Slot(str)
    def handle_error(self, message: str) -> None:
        self._window._handle_worker_error(message)

    @Slot()
    def handle_thread_finished(self) -> None:
        self._window._cleanup_worker_refs()
        if getattr(self._window, "archive_scan_ui_receiver", None) is self:
            self._window.archive_scan_ui_receiver = None
        self.deleteLater()


class ArchiveScanLifecycleMixin:
    """Archive scan start, result intake, and scan finalization."""

    def _confirm_suspicious_archive_tree_scan(self, package_root: Path) -> bool:
        try:
            suspicious_roots = find_suspicious_archive_tree_roots(package_root)
        except (OSError, ValueError) as exc:
            self.append_log(f"Archive root preflight could not inspect the selected folder: {exc}")
            return True
        if not suspicious_roots:
            return True
        shown = suspicious_roots[:8]
        locations = "\n".join(f"- {path}" for path in shown)
        if len(suspicious_roots) > len(shown):
            locations += f"\n- ...and {len(suspicious_roots) - len(shown)} more"
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Possible Duplicate Game Archives")
        box.setText(
            "CDMW found archive indexes outside the normal game archive layout. "
            "Backup or copied archives can create duplicate results and inflated file counts."
        )
        box.setInformativeText(
            f"Suspicious locations:\n{locations}\n\n"
            "Verify or repair the game installation and move archive backups outside the game folder."
        )
        scan_button = box.addButton("Scan Anyway", QMessageBox.AcceptRole)
        open_button = box.addButton("Open Folder", QMessageBox.ActionRole)
        box.addButton("Cancel Scan", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is open_button:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(suspicious_roots[0])))
        if clicked is scan_button:
            return True
        self.set_status_message("Archive scan cancelled: possible duplicate game archives found.")
        return False

    def scan_archives(self, force_refresh: bool = False, *, activate_archive_tab: bool = True) -> None:
        self._archive_scan_progress_timer.stop()
        self._archive_scan_progress_pending = None
        self._mark_archive_browser_render_stale()
        self.archive_browser_first_visible_paint_done = False
        self.archive_deferred_basic_index_start_pending = self.archive_deferred_enhanced_index_start_pending = False
        self.archive_deferred_derived_cache_write_pending = self.archive_deferred_sidecar_start_pending = False
        self.archive_item_icon_preload_pending_after_ready = False
        self.archive_enhanced_filter_refresh_pending = False
        self.archive_basic_index_state = "idle"
        self.archive_enhanced_index_activity = "idle"
        self.archive_entry_metadata_signature = ""
        self.archive_entry_metadata_sources = ()
        self.archive_scan_shard_entry_signatures = {}
        self.archive_scan_shard_entry_counts = {}
        self.archive_result_filter_signature = ()
        self.archive_structure_filter_state = "idle"
        self.archive_structure_filter_children = {}
        if not bool(getattr(self, "archive_startup_hold_until_ready", False)):
            self.archive_startup_index_warmup_required = False
        if self._background_task_active(block_on_archive_index=False):
            return
        package_root_text = self.archive_package_root_edit.text().strip()
        if not package_root_text:
            if not self._prompt_for_archive_package_root_if_missing(
                reason="refresh" if force_refresh else "scan",
                after_autodetect=lambda: self.scan_archives(
                    force_refresh=force_refresh,
                    activate_archive_tab=activate_archive_tab,
                ),
            ):
                return
            package_root_text = self.archive_package_root_edit.text().strip()
            if not package_root_text:
                return
        self._stop_archive_sidecar_worker()
        self._stop_archive_derived_cache_worker()
        self._stop_archive_basic_index_worker()
        self.archive_sidecar_request_id += 1
        self.archive_sidecar_pending_start = False

        package_root = Path(package_root_text).expanduser()
        if not self._confirm_suspicious_archive_tree_scan(package_root):
            return
        self._activate_archive_browser_on_scan_complete = activate_archive_tab
        if activate_archive_tab:
            self._activate_tool_widget(self.archive_browser_tab)
        self._set_archive_cache_health(
            "building",
            "Cache Status: Building. Archive scan/cache build is running.",
            package_root=package_root_text,
        )
        self._reset_archive_load_progress()
        preparing_text = "Preparing archive refresh..." if force_refresh else "Preparing archive scan / cache load..."
        self._set_archive_load_progress(preparing_text)
        self._update_startup_splash(f"{preparing_text} (1%)", 1, 100)
        self._write_heartbeat("archive_refresh" if force_refresh else "archive_load")
        self._set_archive_warmup_overlay(
            True,
            "Preparing Archive Browser",
            (
                "Loading the archive index first. Texture sidecar bindings can continue warming in the background "
                "after the browser opens."
            ),
        )
        self.set_status_message("Refreshing archives..." if force_refresh else "Loading archives...")
        self.append_log("Refreshing archives..." if force_refresh else "Loading archives...")
        self.clear_archive_scan_log()
        self.append_archive_log(
            "Starting archive refresh." if force_refresh else "Starting archive scan (cache-aware)."
        )
        self._set_last_active_operation(
            "archive_scan",
            package_root=str(package_root),
            force_refresh=force_refresh,
        )

        browser_view_will_render_now = bool(
            activate_archive_tab or self._is_tool_visible_or_current(self.archive_browser_tab)
        )
        startup_deferred_archive_load = bool(
            getattr(self, "archive_startup_autoload_defer_preview", False)
            and not activate_archive_tab
        )
        if not startup_deferred_archive_load:
            queued_filter_state = self._capture_archive_filter_state()
            queued_filter_signature = self._archive_filter_state_signature(queued_filter_state)
            queue_filters_after_first_list = bool(
                queued_filter_signature != self._neutral_archive_filter_signature()
            )
            if queue_filters_after_first_list:
                self.archive_startup_saved_filter_state = dict(queued_filter_state)
                self.archive_startup_saved_filter_apply_pending = True
                self.archive_startup_saved_filter_wait_logged = False
                self.append_archive_log("Current filters will apply when search is ready.")
                self.set_status_message("Current filters will apply when search is ready.")
                self._apply_archive_filter_state(
                    {
                        "filter_text": "",
                        "exclude_filter_text": "",
                        "extension_filter": "*",
                        "package_filter_text": "",
                        "structure_filter": "",
                        "role_filter": "all",
                        "exclude_common_technical_suffixes": False,
                        "min_size_kb": 0,
                        "previewable_only": False,
                        "view_mode": ARCHIVE_BROWSER_VIEW_MODE,
                        "sort_column": -1,
                        "sort_order": "asc",
                    }
                )
            else:
                self.archive_startup_saved_filter_apply_pending = False
                self.archive_startup_saved_filter_state = {}
                self.archive_startup_saved_filter_wait_logged = False
        browser_view_will_warm_for_startup = bool(browser_view_will_render_now or startup_deferred_archive_load)
        build_browser_tree_index = bool(
            not startup_deferred_archive_load
            and
            self._archive_folder_tree_enabled()
            and browser_view_will_warm_for_startup
        )
        build_browser_category_index = bool(
            not startup_deferred_archive_load
            and
            self._archive_category_view_enabled()
            and browser_view_will_warm_for_startup
        )
        initial_sort_column = self.archive_tree_sort_column
        initial_sort_deferred = bool(
            not startup_deferred_archive_load
            and
            browser_view_will_warm_for_startup
            and archive_browser_sort_is_active(initial_sort_column)
        )
        initial_worker_sort_column = -1 if initial_sort_deferred else initial_sort_column
        worker_filter_text = self.archive_filter_edit.text().strip()
        worker_exclude_filter_text = self.archive_exclude_filter_edit.text().strip()
        worker_extension_filter = self._combo_value(self.archive_extension_filter_combo)
        worker_package_filter_text = self.archive_package_filter_edit.text().strip()
        worker_structure_filter = self._current_archive_structure_filter_value()
        worker_role_filter = self._combo_value(self.archive_role_filter_combo)
        worker_exclude_common_technical_suffixes = self.archive_exclude_common_technical_checkbox.isChecked()
        worker_min_size_kb = self.archive_min_size_spin.value()
        worker_previewable_only = self.archive_previewable_only_checkbox.isChecked()
        worker_view_mode = self._archive_browser_view_mode()
        if startup_deferred_archive_load:
            worker_filter_text = ""
            worker_exclude_filter_text = ""
            worker_extension_filter = "*"
            worker_package_filter_text = ""
            worker_structure_filter = ""
            worker_role_filter = "all"
            worker_exclude_common_technical_suffixes = False
            worker_min_size_kb = 0
            worker_previewable_only = False
            worker_view_mode = ARCHIVE_BROWSER_VIEW_MODE
            initial_worker_sort_column = -1
        result_filter_signature = self._archive_filter_signature_from_values(
            filter_text=worker_filter_text,
            exclude_filter_text=worker_exclude_filter_text,
            extension_filter=worker_extension_filter,
            package_filter_text=worker_package_filter_text,
            structure_filter=worker_structure_filter,
            role_filter=worker_role_filter,
            exclude_common_technical_suffixes=worker_exclude_common_technical_suffixes,
            min_size_kb=worker_min_size_kb,
            previewable_only=worker_previewable_only,
            view_mode=worker_view_mode,
            sort_column=initial_worker_sort_column,
            sort_order=self.archive_tree_sort_order,
        )
        self.archive_initial_sort_apply_pending = initial_sort_deferred
        if initial_sort_deferred:
            self.append_archive_log(
                "Archive Browser first render is skipping active column sort; sort will apply after the first paint.",
                verbose=True,
            )
        performance_settings = self._current_archive_performance_settings()
        startup_index_warmup = bool(
            getattr(self, "archive_startup_hold_until_ready", False)
            and getattr(self, "archive_startup_index_warmup_required", False)
        )
        worker = ArchiveScanWorker(
            package_root,
            self.archive_cache_root,
            force_refresh=force_refresh,
            build_structure_children=False,
            build_tree_index=build_browser_tree_index,
            filter_text=worker_filter_text,
            exclude_filter_text=worker_exclude_filter_text,
            extension_filter=worker_extension_filter,
            package_filter_text=worker_package_filter_text,
            structure_filter=worker_structure_filter,
            role_filter=worker_role_filter,
            exclude_common_technical_suffixes=worker_exclude_common_technical_suffixes,
            min_size_kb=worker_min_size_kb,
            previewable_only=worker_previewable_only,
            build_category_index=build_browser_category_index,
            sort_column=initial_worker_sort_column,
            sort_order=self.archive_tree_sort_order,
            result_filter_signature=result_filter_signature,
            load_basic_index_cache=bool(
                startup_index_warmup
                or
                self.archive_startup_saved_filter_apply_pending
                and self._archive_filter_state_needs_basic_lookup(
                    getattr(self, "archive_startup_saved_filter_state", {}) or {}
                )
            ),
            load_name_search_index_cache=startup_index_warmup,
            native_archive_acceleration=performance_settings.native_archive_acceleration,
            resource_profile=performance_settings.resource_profile,
            game_executable_fingerprints=self._load_game_executable_fingerprints(),
            crash_reports_dir=self.crash_reports_dir,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        receiver = _ArchiveScanUiReceiver(self)
        thread.started.connect(worker.run)
        worker.log_message.connect(receiver.handle_log, Qt.ConnectionType.QueuedConnection)
        worker.progress_changed.connect(receiver.handle_progress, Qt.ConnectionType.QueuedConnection)
        worker.completed.connect(receiver.handle_completed, Qt.ConnectionType.QueuedConnection)
        worker.error.connect(receiver.handle_error, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(receiver.handle_thread_finished, Qt.ConnectionType.QueuedConnection)

        self.archive_scan_ui_receiver = receiver
        self.archive_scan_worker = worker
        self.worker_thread = thread
        self.set_busy(True, build_mode=False)
        thread.start()

    def _ensure_archive_extension_index_ready(self) -> None:
        if self.archive_entries_by_extension or not self.archive_entries:
            return
        self._ensure_archive_basic_index_worker_started()

    def _handle_archive_scan_complete(self, result: object) -> None:
        self._flush_archive_scan_progress()
        payload = result if isinstance(result, dict) else {}
        updated_fingerprints = payload.get("game_executable_fingerprints")
        if isinstance(updated_fingerprints, Mapping):
            self._save_game_executable_fingerprints(updated_fingerprints)
        self._clear_archive_preview_cache()
        self._clear_archive_asset_family_cache()
        self.archive_entries = payload.get("entries", []) if isinstance(payload.get("entries"), list) else []
        self.archive_entries_by_normalized_path = (
            payload.get("path_index", {})
            if isinstance(payload.get("path_index"), Mapping)
            else {}
        )
        self.archive_entries_by_basename = (
            payload.get("basename_index", {})
            if isinstance(payload.get("basename_index"), Mapping)
            else {}
        )
        self.archive_entries_by_extension = (
            payload.get("extension_index", {})
            if isinstance(payload.get("extension_index"), Mapping)
            else {}
        )
        self.archive_mesh_entries_by_normalized_path = (
            payload.get("mesh_path_index", {})
            if isinstance(payload.get("mesh_path_index"), Mapping)
            else {}
        )
        self.archive_mesh_companion_by_identity = (
            payload.get("mesh_companion_index", {})
            if isinstance(payload.get("mesh_companion_index"), Mapping)
            else {}
        )
        self.archive_entries_by_role = (
            payload.get("role_index", {})
            if isinstance(payload.get("role_index"), Mapping)
            else {}
        )
        extension_counts_payload = payload.get("extension_counts", {})
        self.archive_extension_counts = Counter(
            {
                str(extension): int(count)
                for extension, count in (extension_counts_payload.items() if isinstance(extension_counts_payload, Mapping) else ())
                if extension
            }
        )
        if self.archive_entries_by_extension and not self.archive_extension_counts:
            self.archive_extension_counts = Counter(
                {
                    str(extension): len(items)
                    for extension, items in self.archive_entries_by_extension.items()
                    if extension
                }
            )
        self._ensure_archive_extension_index_ready()
        self.archive_character_appearance_swap_cache = {}
        self.archive_entry_metadata_signature = str(payload.get("entry_metadata_signature", "") or "").strip()
        self.archive_entry_metadata_sources = tuple(
            tuple(row)
            for row in (payload.get("entry_metadata_sources", ()) or ())
            if isinstance(row, (list, tuple)) and len(row) == 3
        )
        scan_metadata_payload = payload.get("scan_metadata", {}) if isinstance(payload.get("scan_metadata"), Mapping) else {}
        raw_shard_signatures = scan_metadata_payload.get("scan_shard_entry_signatures")
        self.archive_scan_shard_entry_signatures = {
            str(key): str(value)
            for key, value in (raw_shard_signatures.items() if isinstance(raw_shard_signatures, Mapping) else ())
            if str(key)
        }
        raw_shard_counts = scan_metadata_payload.get("scan_shard_entry_counts")
        self.archive_scan_shard_entry_counts = {}
        if isinstance(raw_shard_counts, Mapping):
            for key, value in raw_shard_counts.items():
                try:
                    self.archive_scan_shard_entry_counts[str(key)] = int(value)
                except (TypeError, ValueError):
                    continue
        self.archive_result_filter_signature = tuple(payload.get("result_filter_signature") or self._current_archive_filter_signature())
        performance_settings = self._current_archive_performance_settings()
        saved_filter_state = getattr(self, "archive_startup_saved_filter_state", {}) or {}
        if not isinstance(saved_filter_state, Mapping):
            saved_filter_state = {}
        saved_filter_needs_basic = bool(
            self.archive_startup_saved_filter_apply_pending
            and self._archive_filter_state_needs_basic_lookup(saved_filter_state)
        )
        saved_filter_needs_item_search = bool(
            self.archive_startup_saved_filter_apply_pending
            and self._archive_saved_filter_needs_item_search(saved_filter_state)
        )
        current_filter_state = self._capture_archive_filter_state()
        current_filter_needs_basic = self._archive_filter_state_needs_basic_lookup(current_filter_state)
        current_filter_needs_item_search = self._archive_saved_filter_needs_item_search(current_filter_state)
        priority_prewarm_indexes = bool(
            performance_settings.maximum_indexing_priority
            or performance_settings.resource_profile == "maximum_throughput"
        )
        startup_index_warmup = bool(
            getattr(self, "archive_startup_hold_until_ready", False)
            and getattr(self, "archive_startup_index_warmup_required", False)
        )
        basic_indexes_ready = bool(
            self.archive_entries_by_normalized_path
            and self.archive_entries_by_basename
            and self.archive_entries_by_extension
            and self.archive_entries_by_role
        )
        basic_index_needs_build = bool(payload.get("basic_index_needs_build") and self.archive_entries)
        prewarm_basic_index = bool(
            basic_index_needs_build
            and (
                startup_index_warmup
                or
                priority_prewarm_indexes
                or saved_filter_needs_basic
                or current_filter_needs_basic
            )
        )
        self.archive_basic_index_state = (
            "ready"
            if basic_indexes_ready
            else "warming"
            if prewarm_basic_index
            else "idle"
        )
        name_search_index = payload.get("name_search_index")
        self.archive_name_search_index = (
            name_search_index
            if isinstance(name_search_index, ArchiveNameSearchIndex)
            else None
        )
        self.archive_item_search_aliases = (
            payload.get("item_search_aliases", {})
            if isinstance(payload.get("item_search_aliases"), dict)
            else {}
        )
        self.archive_item_display_names = (
            payload.get("item_display_names", {})
            if isinstance(payload.get("item_display_names"), dict)
            else {}
        )
        self.archive_item_exact_display_names = (
            payload.get("item_exact_display_names", {})
            if isinstance(payload.get("item_exact_display_names"), dict)
            else {}
        )
        self.archive_item_related_display_names = (
            payload.get("item_related_display_names", {})
            if isinstance(payload.get("item_related_display_names"), dict)
            else {}
        )
        self.archive_item_asset_catalog = [
            dict(row)
            for row in (payload.get("item_asset_catalog", []) or [])
            if isinstance(row, Mapping)
        ]
        self._clear_archive_asset_catalog_icon_cache()
        self.archive_item_icon_preload_pending_after_ready = bool(self.archive_item_asset_catalog)
        self._schedule_archive_asset_catalog_icon_preload()
        self.archive_active_asset_catalog_scope = ""
        self.archive_clear_asset_scope_button.setVisible(False)
        self.archive_clear_asset_scope_button.setEnabled(False)
        self.archive_filter_edit.setPlaceholderText("Include path/item-name filter or glob, e.g. Vow of the Dead King or */texture/*")
        self.archive_asset_catalog_button.setEnabled(bool(self.archive_item_asset_catalog))
        self.archive_material_finder_button.setEnabled(bool(self._archive_material_catalog_rows()))
        self.archive_derived_cache_write_pending = bool(
            payload.get("derived_cache_needs_write") and self.archive_entries
        )
        enhanced_index_needs_build = bool(payload.get("enhanced_index_needs_build") and self.archive_entries)
        prewarm_enhanced_index = bool(
            enhanced_index_needs_build
            and (
                startup_index_warmup
                or
                priority_prewarm_indexes
                or saved_filter_needs_item_search
                or current_filter_needs_item_search
            )
        )
        self.archive_enhanced_index_auto_prewarm_pending = bool(
            enhanced_index_needs_build
            and not prewarm_enhanced_index
            and not self._startup_benchmark_enabled()
        )
        self.archive_deferred_basic_index_start_pending = bool(prewarm_basic_index)
        self.archive_enhanced_index_state = (
            "ready"
            if self.archive_name_search_index is not None or not enhanced_index_needs_build
            else "warming"
            if prewarm_enhanced_index
            else "idle"
        )
        self.archive_enhanced_index_activity = "loading" if prewarm_enhanced_index else "idle"
        self.archive_deferred_enhanced_index_start_pending = bool(prewarm_enhanced_index)
        if basic_index_needs_build and not prewarm_basic_index:
            self.append_archive_log(
                "Path lookup cache deferred; it will build when filters, related-file lookup, preview, or priority indexing need it."
            )
        if enhanced_index_needs_build and not prewarm_enhanced_index:
            self.append_archive_log(
                "Item-name search cache will warm after the archive list opens; item-name searches can start it sooner."
            )
        self.archive_native_derived_cache_ready = bool(payload.get("archive_native_derived_cache_ready"))
        self.archive_sidecar_entries_by_texture_path = (
            payload.get("sidecar_entries_by_texture_path", {})
            if isinstance(payload.get("sidecar_entries_by_texture_path"), Mapping)
            else {}
        )
        self.archive_sidecar_entries_by_texture_basename = (
            payload.get("sidecar_entries_by_texture_basename", {})
            if isinstance(payload.get("sidecar_entries_by_texture_basename"), Mapping)
            else {}
        )
        self.archive_sidecar_generation += 1
        self.archive_sidecar_pending_start = bool(
            self.archive_entries and performance_settings.enable_sidecar_indexing
        )
        if not performance_settings.enable_sidecar_indexing:
            self.archive_sidecar_entries_by_texture_path = {}
            self.archive_sidecar_entries_by_texture_basename = {}
        package_root_text = self.archive_package_root_edit.text().strip()
        def update_text_search_entries() -> None:
            text_search_tab = created_tool_widget(getattr(self, "text_search_tab", None))
            if text_search_tab is not None:
                text_search_tab.set_archive_entries(self.archive_entries, package_root_text)

        QTimer.singleShot(0, update_text_search_entries)
        browser_state = payload.get("browser_state") if isinstance(payload.get("browser_state"), dict) else {}
        self.archive_structure_filter_children = (
            browser_state.get("structure_children", {})
            if isinstance(browser_state.get("structure_children"), dict)
            else {}
        )
        self.archive_structure_filter_state = "ready" if self.archive_structure_filter_children else "idle"
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
        self._rebuild_archive_extension_filter_choices()
        self.archive_filtered_dds_count = int(browser_state.get("dds_count", 0))
        self.archive_filters_dirty = False
        self._update_archive_filter_button_state()
        def update_replace_assistant_entries() -> None:
            replace_assistant_tab = created_tool_widget(getattr(self, "replace_assistant_tab", None))
            if replace_assistant_tab is not None:
                replace_assistant_tab.set_archive_entries(self.archive_entries, package_root_text)

        QTimer.singleShot(0, update_replace_assistant_entries)
        source = str(payload.get("source", "scan"))
        cache_path_text = str(payload.get("cache_path", "")).strip()
        timings = payload.get("timings", {}) if isinstance(payload.get("timings"), dict) else {}
        timing_summary = str(payload.get("timing_summary", "")).strip()
        scan_metadata = payload.get("scan_metadata", {}) if isinstance(payload.get("scan_metadata"), Mapping) else {}
        raw_shard_signatures = scan_metadata.get("scan_shard_entry_signatures")
        self.archive_scan_shard_entry_signatures = {
            str(key): str(value)
            for key, value in (raw_shard_signatures.items() if isinstance(raw_shard_signatures, Mapping) else ())
            if str(key)
        }
        raw_shard_counts = scan_metadata.get("scan_shard_entry_counts")
        shard_entry_counts: Dict[str, int] = {}
        if isinstance(raw_shard_counts, Mapping):
            for key, value in raw_shard_counts.items():
                try:
                    shard_entry_counts[str(key)] = int(value)
                except (TypeError, ValueError):
                    continue
        self.archive_scan_shard_entry_counts = shard_entry_counts
        stale_count = int(scan_metadata.get("scan_shard_stale_count", 0) or 0)
        rebuilt_count = int(scan_metadata.get("scan_shard_rebuilt_count", 0) or 0)
        if self.archive_entries:
            if source == "cache" and stale_count <= 0 and rebuilt_count <= 0:
                self._set_archive_cache_health(
                    "healthy",
                    f"Cache Status: Healthy. {len(self.archive_entries):,} archive entries loaded from current cache.",
                    package_root=package_root_text,
                )
            else:
                rebuild_note = (
                    f" Rebuilt {rebuilt_count:,} stale shard(s)." if rebuilt_count > 0 else ""
                )
                self._set_archive_cache_health(
                    "healthy",
                    f"Cache Status: Healthy. Archive cache matches current game files.{rebuild_note}",
                    package_root=package_root_text,
                )
        rendering_archive_view = (
            self._activate_archive_browser_on_scan_complete
            or self._is_tool_visible_or_current(self.archive_browser_tab)
        )
        self._write_heartbeat("archive_finalize")
        finalize_text = "Rendering archive browser view..." if rendering_archive_view else "Finalizing archive load..."
        self._set_archive_load_progress(finalize_text, percent=90 if rendering_archive_view else 96)
        self._update_startup_splash(f"{finalize_text} ({self._archive_load_progress_percent}%)", self._archive_load_progress_percent, 100)
        self.set_status_message(finalize_text)
        self.append_archive_log(finalize_text)
        self.archive_scan_finalize_pending = True
        QTimer.singleShot(
            0,
            lambda source=source, cache_path_text=cache_path_text, timings=timings, timing_summary=timing_summary: self._finalize_archive_scan_complete(
                source,
                cache_path_text,
                timings,
                timing_summary,
            ),
        )

    def _finalize_archive_scan_complete(
        self,
        source: str,
        cache_path_text: str,
        timings: Optional[Dict[str, float]] = None,
        timing_summary: str = "",
    ) -> None:
        start_sidecar_after_finalize = False
        try:
            completion_text = (
                f"Loaded {len(self.archive_entries):,} archive entries from cache."
                if source == "cache"
                else f"Archive scan complete. Found {len(self.archive_entries):,} entries."
            )
            self._record_runtime_event(
                "archive_scan_complete",
                source=source,
                entry_count=len(self.archive_entries),
                cache_path=cache_path_text,
                timing_summary=timing_summary,
            )
            if cache_path_text and source == "scan":
                self.append_archive_log(f"Archive cache ready: {cache_path_text}")
            if timing_summary:
                self.append_archive_log(timing_summary, verbose=True)
            if source == "cache" and _timing_value(timings, "total_s") > 2.0:
                self.append_archive_log(
                    f"WARNING: Archive cache hit is slower than expected: total={_timing_value(timings, 'total_s'):.2f}s.",
                    verbose=True,
                )
            performance_settings = self._current_archive_performance_settings()
            if (
                self.archive_sidecar_pending_start
                and self.archive_entries
                and performance_settings.enable_sidecar_indexing
            ):
                start_sidecar_after_finalize = True
                self.archive_browser_warmup_pending = False
                self.archive_browser_warmup_completion_text = completion_text
                warmup_text = "Loading texture sidecar cache in the background..."
                self.archive_tree.setEnabled(True)
                self._set_archive_load_progress(
                    "Archive entries loaded. Texture sidecar cache is tracked in the compact status indicator.",
                    phase="Sidecar",
                    percent=96,
                )
                self._set_archive_sidecar_status(warmup_text)
                self.set_status_message(warmup_text)
                self.append_archive_log(warmup_text)
            else:
                self.archive_sidecar_pending_start = False
            release_startup_now = bool(
                getattr(self, "_startup_splash_window", None) is not None
                and not bool(getattr(self, "archive_startup_hold_until_ready", False))
            )
            if release_startup_now:
                self._update_startup_splash(completion_text, 1, 1)
                self._write_heartbeat("running")
                self._release_startup_splash()
            self._refresh_or_defer_archive_browser_view(
                activate_tab=self._activate_archive_browser_on_scan_complete,
                on_complete=None,
                force_render=False,
            )
            self._activate_archive_browser_on_scan_complete = False
            self._refresh_or_defer_research_archive_picker()
            self._set_archive_list_status(completion_text)
            self.append_archive_log(completion_text)
            self._record_archive_memory_audit("archive_scan_complete", log_if_high=True)
            self._set_archive_warmup_overlay(False)
            self._finish_startup_benchmark_after_archive_ready(
                reason="archive_scan_complete",
                source=source,
                timings=timings,
                timing_summary=timing_summary,
            )
            if (
                not release_startup_now
                and not bool(getattr(self, "archive_startup_hold_until_ready", False))
            ):
                self._write_heartbeat("running")
                self._release_startup_splash()
        finally:
            self.archive_scan_finalize_pending = False
            if self.archive_derived_cache_write_pending:
                self.archive_deferred_derived_cache_write_pending = True
            if start_sidecar_after_finalize:
                self.archive_deferred_sidecar_start_pending = True
            if self._startup_benchmark_enabled():
                self.archive_deferred_background_start_pending = False
                self.archive_deferred_basic_index_start_pending = False
                self.archive_deferred_enhanced_index_start_pending = False
                self.archive_deferred_derived_cache_write_pending = False
                self.archive_startup_hold_until_ready = False
                if not release_startup_now:
                    self._write_heartbeat("running")
                    self._release_startup_splash()
            elif bool(getattr(self, "archive_startup_hold_until_ready", False)):
                self.archive_deferred_background_start_pending = False
                QTimer.singleShot(0, self._start_archive_deferred_background_work)
                QTimer.singleShot(50, self._maybe_release_startup_after_archive_ready)
            else:
                self._schedule_archive_post_ready_background_work()
            if self.worker_thread is None:
                self.set_busy(False, build_mode=False)


__all__ = ["ArchiveScanLifecycleMixin"]
