"""Controller mixins for Model Library result coordination."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QMessageBox, QTreeWidgetItem

from cdmw.workers.model_library_rows import (
    ModelLibraryDeleteTarget,
    ModelLibraryPreparedRow,
    ModelLibraryPreparedRowsResult,
    ModelLibraryRowsRequest,
    freeze_model_library_rows,
    prepare_model_library_rows,
)


class ModelLibraryResultsMixin:
    """Filtering, sorting, and batched result-tree population."""

    def _next_results_request_id(self) -> int:
        self._results_request_id = int(getattr(self, "_results_request_id", 0) or 0) + 1
        return self._results_request_id

    def _model_library_rows_request(
        self,
        rows: list[dict[str, object]],
        *,
        view: Optional[str] = None,
        normalize_local: bool = False,
        request_id: Optional[int] = None,
    ) -> ModelLibraryRowsRequest:
        target_view = str(view or self._active_results_view)
        try:
            mirror_url = self.mirror_url()
        except ValueError:
            mirror_url = ""
        if target_view == "local" and rows is self.local_models and len(self._local_frozen_rows) == len(rows):
            frozen_rows = self._local_frozen_rows
        elif target_view == "mirror" and rows is self.mirror_results and len(self._mirror_frozen_rows) == len(rows):
            frozen_rows = self._mirror_frozen_rows
        else:
            frozen_rows = freeze_model_library_rows(rows)
        return ModelLibraryRowsRequest(
            request_id=self._next_results_request_id() if request_id is None else int(request_id),
            view=target_view,
            rows=frozen_rows,
            download_root=str(self._download_output_root()),
            mirror_url=mirror_url,
            preferred_format=self._primary_preferred_format(),
            query=str(self.search_edit.text() if hasattr(self, "search_edit") else "").strip(),
            local_filter_field=str(self.results_filter_field_combo.currentData() or "all") if hasattr(self, "results_filter_field_combo") else "all",
            local_texture_filter=str(self.local_texture_filter_combo.currentData() or "all") if hasattr(self, "local_texture_filter_combo") else "all",
            column_filters=tuple(sorted(self._active_column_filters().items())),
            hide_downloaded=bool(
                target_view == "mirror"
                and getattr(self, "hide_downloaded_checkbox", None)
                and self.hide_downloaded_checkbox.isChecked()
            ),
            sort_column=int(self._result_sort_column),
            sort_descending=self._result_sort_order == Qt.SortOrder.DescendingOrder,
            normalize_local=bool(normalize_local),
        )

    def _mirror_payload_downloaded(self, payload: dict[str, object]) -> bool:
        prepared = self._prepared_result_row(payload)
        return prepared.downloaded if prepared is not None else bool(str(payload.get("local_status", "") or "").strip())

    def _result_size_bytes(self, payload: dict[str, object]) -> int:
        prepared = self._prepared_result_row(payload)
        if prepared is not None:
            return prepared.size_bytes
        try:
            return int(payload.get("size", 0) or 0)
        except (TypeError, ValueError):
            return 0

    def _result_column_filter_text(self, payload: dict[str, object], column: int) -> str:
        prepared = self._prepared_result_row(payload)
        if prepared is None or not 0 <= column < len(prepared.columns):
            return ""
        return prepared.columns[column]

    def _result_sort_text(self, payload: dict[str, object], column: int) -> str:
        return self._result_column_filter_text(payload, column)

    def _sort_result_rows(self, rows: list[dict[str, object]]) -> list[dict[str, object]]:
        """Compatibility view; production sorting is part of worker preparation."""

        return list(rows)

    def _update_empty_results_message(self, visible_count: int, total_count: int) -> None:
        if not hasattr(self, "empty_results_label"):
            return
        message = ""
        if visible_count <= 0:
            if self._active_results_view == "mirror":
                hidden = int(getattr(self, "_last_hidden_downloaded_count", 0) or 0)
                if hidden and getattr(self, "hide_downloaded_checkbox", None) and self.hide_downloaded_checkbox.isChecked():
                    message = (
                        f"All {hidden:,} mirror result(s) are hidden because they are already downloaded. "
                        "Turn off Hide downloaded, search a different term, or delete local copies to show them again."
                    )
                elif total_count <= 0:
                    query = str(self.search_edit.text() if hasattr(self, "search_edit") else "").strip()
                    message = f"No mirror results found for \"{query}\"." if query else "No mirror results loaded. Search the mirror catalogue or show popular models."
            else:
                query = str(self.search_edit.text() if hasattr(self, "search_edit") else "").strip()
                if total_count > 0 and query:
                    message = f"No local models match \"{query}\". Clear the local filter or choose another field."
                else:
                    message = "No local models are loaded. Add a folder, then show local models."
        self.empty_results_label.setText(message)
        self.empty_results_label.setVisible(bool(message))

    def _populate_results(self, rows: list[dict[str, object]]) -> None:
        if bool(getattr(self, "_model_library_shutting_down", False)):
            return
        if self._pending_prepared_rows_result is not None:
            self._pending_results_refresh = True
            return
        self._results_filter_timer.stop()
        self._results_population_timer.stop()
        self._auto_preview_timer.stop()
        running = self._task_thread is not None and self._task_thread.isRunning()
        if running and self._results_task_kind in {"scan", "search"}:
            self._pending_results_refresh = True
            self._populating_results = True
            return
        request_id = self._next_results_request_id()
        self._results_selection_keys[request_id] = self._payload_population_key(self._selected_payload())
        self._pending_results_rows = []
        self._populating_results = True
        if not rows:
            if self._results_task_stop_event is not None:
                self._results_task_stop_event.set()
            self._apply_empty_results(request_id)
            return
        request = self._model_library_rows_request(rows, request_id=request_id)
        if running:
            self._pending_results_request = request
            if self._results_task_stop_event is not None:
                self._results_task_stop_event.set()
            return
        self._start_results_request(request)

    def _start_results_request(self, request: ModelLibraryRowsRequest) -> None:
        stop_event = threading.Event()
        self._results_task_kind = "population"
        self._results_task_stop_event = stop_event
        self._stop_event = stop_event

        def task(_progress: object) -> object:
            return prepare_model_library_rows(request, stop_event=stop_event)

        def complete(value: object) -> None:
            if isinstance(value, ModelLibraryPreparedRowsResult):
                self._apply_prepared_results(value)

        def handle_error(message: str) -> None:
            self._results_selection_keys.pop(request.request_id, None)
            if request.request_id != self._results_request_id or stop_event.is_set():
                return
            self._populating_results = False
            self._set_status(f"Model row preparation failed: {message}", error=True)

        self._run_task("Preparing model rows...", task, complete, error_handler=handle_error)

    def _start_pending_results_request(self) -> None:
        if bool(getattr(self, "_model_library_shutting_down", False)):
            return
        if self._pending_prepared_rows_result is not None:
            return
        if self._task_thread is not None and self._task_thread.isRunning():
            return
        request = self._pending_results_request
        self._pending_results_request = None
        self._results_task_stop_event = None
        if request is not None and request.request_id == self._results_request_id:
            self._start_results_request(request)
            return
        if self._pending_results_refresh:
            self._pending_results_refresh = False
            rows = self.local_models if self._active_results_view == "local" else self.mirror_results
            self._populate_results(rows)

    def _apply_empty_results(self, request_id: int) -> None:
        if request_id != self._results_request_id:
            return
        self._last_hidden_downloaded_count = 0
        self._pending_prepared_rows_result = None
        self._pending_prepared_payloads.clear()
        self._pending_prepared_cursor = 0
        self._prepared_rows_by_payload_id.clear()
        if self._active_results_view == "local":
            self.local_models = []
            self._local_frozen_rows = ()
        else:
            self.mirror_results = []
            self._mirror_frozen_rows = ()
        self._begin_results_population([], 0, request_id)

    def _apply_prepared_results(self, result: ModelLibraryPreparedRowsResult) -> bool:
        if result.request_id != self._results_request_id:
            self._results_selection_keys.pop(result.request_id, None)
            return False
        self._last_hidden_downloaded_count = result.hidden_downloaded_count
        self._pending_prepared_rows_result = result
        self._pending_prepared_payloads = []
        self._pending_prepared_cursor = 0
        self._prepared_rows_by_payload_id.clear()
        self._pending_results_total_count = len(result.all_rows)
        self._pending_results_visible_count = len(result.visible_indices)
        self._populating_results = True
        self.results_status_label.setText(f"Applying prepared rows... 0 / {len(result.all_rows):,}")
        self._results_population_timer.start()
        return True

    def _apply_prepared_payload_batch(self) -> bool:
        result = self._pending_prepared_rows_result
        if not isinstance(result, ModelLibraryPreparedRowsResult):
            return False
        start = self._pending_prepared_cursor
        end = min(len(result.all_rows), start + self.PREPARED_ROWS_APPLY_BATCH_SIZE)
        for row in result.all_rows[start:end]:
            payload = row.payload.to_dict()
            self._pending_prepared_payloads.append(payload)
            self._prepared_rows_by_payload_id[id(payload)] = row
        self._pending_prepared_cursor = end
        if end < len(result.all_rows):
            self.results_status_label.setText(f"Applying prepared rows... {end:,} / {len(result.all_rows):,}")
            self._results_population_timer.start()
            return True
        payloads = self._pending_prepared_payloads
        if result.view == "local":
            self.local_models = payloads
            self._local_frozen_rows = tuple(row.payload for row in result.all_rows)
        else:
            self.mirror_results = payloads
            self._mirror_frozen_rows = tuple(row.payload for row in result.all_rows)
        visible_rows = [payloads[index] for index in result.visible_indices]
        self._pending_prepared_rows_result = None
        self._pending_prepared_payloads = []
        self._pending_prepared_cursor = 0
        self._begin_results_population(visible_rows, len(payloads), result.request_id)
        return True

    def _begin_results_population(
        self,
        visible_rows: list[dict[str, object]],
        total_count: int,
        request_id: int,
    ) -> None:
        self._pending_results_rows = list(visible_rows)
        self._pending_results_total_count = total_count
        self._pending_results_visible_count = len(visible_rows)
        self._pending_results_selected_payload = None
        self._pending_results_selected_key = self._results_selection_keys.pop(request_id, ("", "", ""))
        self._populating_results = True
        self.results_tree.setSortingEnabled(False)
        self.results_tree.blockSignals(True)
        self.results_tree.setUpdatesEnabled(False)
        self.results_tree.clear()
        self._result_payloads_by_item.clear()
        self._result_items_by_payload_id.clear()
        self._checked_payloads_by_item.clear()
        self._no_texture_download_item_ids.clear()
        self.results_tree.setUpdatesEnabled(True)
        self.results_tree.blockSignals(False)
        self._update_empty_results_message(len(visible_rows), total_count)
        if visible_rows:
            self.results_status_label.setText(
                f"Populating results... 0 / {len(visible_rows):,}"
            )
        self._flush_results_population_batch()

    def _build_result_item(self, payload: dict[str, object]) -> QTreeWidgetItem:
        prepared = self._prepared_result_row(payload)
        columns = prepared.columns if prepared is not None else (
            "",
            str(payload.get("name", "") or "Untitled model"),
            str(payload.get("source", "") or "Local"),
            str(payload.get("local_status", "") or ""),
            str(payload.get("texture_status", "") or "Unknown"),
            str(payload.get("extension", "") or ""),
            self._format_size(int(payload.get("size", 0) or 0)),
            str(payload.get("license_label", "") or ""),
            str(payload.get("creator_name", "") or payload.get("creator_username", "") or ""),
            str(payload.get("relative_path", "") or payload.get("path", "") or ""),
        )
        item = QTreeWidgetItem(list(columns))
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Unchecked)
        item.setData(0, Qt.ItemDataRole.UserRole, payload)
        item.setData(1, Qt.ItemDataRole.UserRole, payload)
        self._result_payloads_by_item[id(item)] = payload
        self._result_items_by_payload_id[id(payload)] = item
        return item

    def _prepared_result_row(self, payload: Optional[dict[str, object]]) -> Optional[ModelLibraryPreparedRow]:
        if payload is None:
            return None
        return self._prepared_rows_by_payload_id.get(id(payload))

    def _payload_population_key(self, payload: Optional[dict[str, object]]) -> tuple[str, str, str]:
        if not isinstance(payload, dict):
            return ("", "", "")
        return (
            str(payload.get("kind", "") or ""),
            str(payload.get("uid", "") or payload.get("id", "") or ""),
            str(payload.get("import_path", "") or payload.get("path", "") or payload.get("relative_path", "") or payload.get("name", "") or ""),
        )

    def _finish_results_population(self) -> None:
        self.results_tree.setSortingEnabled(False)
        target_item: Optional[QTreeWidgetItem] = None
        selected_key = self._pending_results_selected_key
        if any(selected_key):
            for index in range(self.results_tree.topLevelItemCount()):
                item = self.results_tree.topLevelItem(index)
                payload = self._payload_from_item(item)
                if payload is self._pending_results_selected_payload or self._payload_population_key(payload) == selected_key:
                    target_item = item
                    break
        if target_item is None and self.results_tree.topLevelItemCount() > 0:
            target_item = self.results_tree.topLevelItem(0)
        if target_item is not None:
            self.results_tree.setCurrentItem(target_item)
        self._pending_results_rows = []
        self._pending_results_selected_payload = None
        self._pending_results_selected_key = ("", "", "")
        # Keep the busy state truthful until both row application and the
        # owning worker/thread teardown have completed.  A stopped QThread can
        # still have its queued ``finished`` cleanup pending; allowing another
        # action in that window lets the old cleanup clear the new task.
        result_task_owned = (
            self._task_thread is not None
            and self._results_task_kind in {"population", "scan", "search"}
        )
        self._populating_results = result_task_owned
        self._update_selection_state()
        if self._pending_results_refresh and (self._task_thread is None or not self._task_thread.isRunning()):
            self._results_population_timer.stop()
            QTimer.singleShot(0, self._start_pending_results_request)

    def _flush_results_population_batch(self) -> None:
        if self._apply_prepared_payload_batch():
            return
        if not self._pending_results_rows:
            self._finish_results_population()
            return
        batch = self._pending_results_rows[: self.RESULTS_POPULATION_BATCH_SIZE]
        del self._pending_results_rows[: self.RESULTS_POPULATION_BATCH_SIZE]
        items = [self._build_result_item(payload) for payload in batch]
        for item in items:
            self._sync_no_texture_download_cache_for_item(item)
        self.results_tree.setUpdatesEnabled(False)
        self.results_tree.addTopLevelItems(items)
        self.results_tree.setUpdatesEnabled(True)
        populated = self._pending_results_visible_count - len(self._pending_results_rows)
        self.results_status_label.setText(
            f"Populating results... {populated:,} / {self._pending_results_visible_count:,}"
        )
        if self._pending_results_rows:
            self._results_population_timer.start()
            return
        self._finish_results_population()

    def _result_item_for_payload(self, payload: Optional[dict[str, object]]) -> Optional[QTreeWidgetItem]:
        if not payload:
            return None
        item = self._result_items_by_payload_id.get(id(payload))
        if item is not None:
            return item
        target_key = self._payload_population_key(payload)
        for index in range(self.results_tree.topLevelItemCount()):
            candidate = self.results_tree.topLevelItem(index)
            candidate_payload = self._payload_from_item(candidate)
            if candidate_payload is payload or self._payload_population_key(candidate_payload) == target_key:
                self._result_items_by_payload_id[id(payload)] = candidate
                return candidate
        return None

    def _sync_checked_payload_cache_for_item(self, item: Optional[QTreeWidgetItem]) -> None:
        if item is None:
            return
        item_id = id(item)
        payload = self._payload_from_item(item)
        if payload is not None and item.checkState(0) == Qt.CheckState.Checked:
            self._checked_payloads_by_item[item_id] = payload
            return
        self._checked_payloads_by_item.pop(item_id, None)

    def _rebuild_checked_payload_cache(self) -> None:
        self._checked_payloads_by_item.clear()
        for index in range(self.results_tree.topLevelItemCount()):
            self._sync_checked_payload_cache_for_item(self.results_tree.topLevelItem(index))

    def _sync_no_texture_download_cache_for_item(self, item: Optional[QTreeWidgetItem]) -> None:
        if item is None:
            return
        item_id = id(item)
        self._no_texture_download_item_ids.discard(item_id)
        if self._active_results_view != "local":
            return
        payload = self._payload_from_item(item)
        prepared = self._prepared_result_row(payload)
        if prepared is not None and prepared.no_texture_delete_target is not None:
            self._no_texture_download_item_ids.add(item_id)

    def _selected_payload(self) -> Optional[dict[str, object]]:
        item = self.results_tree.currentItem()
        return self._payload_from_item(item)

    def _selected_payloads(self) -> list[dict[str, object]]:
        payloads: list[dict[str, object]] = []
        seen_items: set[int] = set()
        for item in self.results_tree.selectedItems():
            item_id = id(item)
            if item_id in seen_items:
                continue
            payload = self._payload_from_item(item)
            if isinstance(payload, dict):
                seen_items.add(item_id)
                payloads.append(payload)
        current_item = self.results_tree.currentItem()
        current = self._selected_payload()
        if current is not None and (current_item is None or id(current_item) not in seen_items):
            payloads.append(current)
        return payloads

    def _payload_from_item(self, item: Optional[QTreeWidgetItem]) -> Optional[dict[str, object]]:
        if item is None:
            return None
        mapped_payload = self._result_payloads_by_item.get(id(item))
        if mapped_payload is not None:
            return mapped_payload
        for column in (0, 1):
            payload = item.data(column, Qt.ItemDataRole.UserRole)
            if isinstance(payload, dict):
                return payload
        return None

    def _checked_payloads(self) -> list[dict[str, object]]:
        return list(self._checked_payloads_by_item.values())

    def _batch_action_payloads(self) -> list[dict[str, object]]:
        return self._checked_payloads()

    def _set_all_result_checks(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.results_tree.blockSignals(True)
        try:
            for index in range(self.results_tree.topLevelItemCount()):
                self.results_tree.topLevelItem(index).setCheckState(0, state)
        finally:
            self.results_tree.blockSignals(False)
        self._rebuild_checked_payload_cache()
        self._update_selection_state()

    def _local_delete_payloads(self) -> list[dict[str, object]]:
        checked_payloads = [
            payload
            for payload in self._checked_payloads()
            if self._local_delete_target_for_payload(payload) is not None
        ]
        if checked_payloads:
            return checked_payloads
        current = self._selected_payload()
        if current is not None and self._local_delete_target_for_payload(current) is not None:
            return [current]
        return []

    def _local_delete_targets_for_payloads(self, payloads: list[dict[str, object]]) -> list[ModelLibraryDeleteTarget]:
        targets: list[ModelLibraryDeleteTarget] = []
        seen: set[str] = set()
        for payload in payloads:
            target = self._local_delete_target_for_payload(payload)
            if target is None:
                continue
            if target.identity in seen:
                continue
            seen.add(target.identity)
            targets.append(target)
        return targets

    def _no_texture_download_delete_targets_for_payloads(self, payloads: list[dict[str, object]]) -> list[ModelLibraryDeleteTarget]:
        targets: list[ModelLibraryDeleteTarget] = []
        seen: set[str] = set()
        for payload in payloads:
            target = self._no_texture_download_delete_target_for_payload(payload)
            if target is None:
                continue
            if target.identity in seen:
                continue
            seen.add(target.identity)
            targets.append(target)
        return targets

    def _visible_no_texture_download_payloads(self) -> list[dict[str, object]]:
        if self._active_results_view != "local" or not hasattr(self, "results_tree"):
            return []
        payloads: list[dict[str, object]] = []
        for index in range(self.results_tree.topLevelItemCount()):
            payload = self._payload_from_item(self.results_tree.topLevelItem(index))
            if payload is not None and self._no_texture_download_delete_target_for_payload(payload) is not None:
                payloads.append(payload)
        return payloads

    def _local_delete_target_for_payload(self, payload: Optional[dict[str, object]]) -> Optional[ModelLibraryDeleteTarget]:
        prepared = self._prepared_result_row(payload)
        return prepared.local_delete_target if prepared is not None else None

    def _no_texture_download_delete_target_for_payload(self, payload: Optional[dict[str, object]]) -> Optional[ModelLibraryDeleteTarget]:
        prepared = self._prepared_result_row(payload)
        return prepared.no_texture_delete_target if prepared is not None else None

    def _downloaded_model_folder_target_for_payload(self, payload: Optional[dict[str, object]]) -> Optional[ModelLibraryDeleteTarget]:
        prepared = self._prepared_result_row(payload)
        if prepared is None:
            return None
        target = prepared.local_delete_target
        return target if target is not None and target.target_kind == "download_dir" else None

    def _confirm_delete_local_targets(self, targets: list[ModelLibraryDeleteTarget]) -> bool:
        if not targets:
            return False
        box = QMessageBox(self)
        box.setWindowTitle("Delete Local Models")
        box.setIcon(QMessageBox.Warning)
        box.setText(f"Delete {len(targets):,} local item(s) from disk?")
        listed = "\n".join(f"- {target.label}: {target.path}" for target in targets[:8])
        if len(targets) > 8:
            listed = f"{listed}\n- ... {len(targets) - 8:,} more"
        box.setInformativeText(
            "Downloaded mirror rows delete their whole downloaded model folder. "
            "Regular local rows delete only the selected model file.\n\n"
            f"{listed}"
        )
        delete_button = box.addButton("Delete", QMessageBox.DestructiveRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Cancel)
        box.exec()
        return box.clickedButton() == delete_button

    def _confirm_delete_no_texture_download_targets(self, targets: list[ModelLibraryDeleteTarget]) -> bool:
        if not targets:
            return False
        box = QMessageBox(self)
        box.setWindowTitle("Delete No-Texture Downloads")
        box.setIcon(QMessageBox.Warning)
        box.setText(f"Delete {len(targets):,} downloaded model folder(s) with no textures found?")
        listed = "\n".join(f"- {target.path}" for target in targets[:8])
        if len(targets) > 8:
            listed = f"{listed}\n- ... {len(targets) - 8:,} more"
        box.setInformativeText(
            "Only visible downloaded Model Library folders with texture status 'None found' are included. "
            "Standalone local model files are never included in this bulk cleanup.\n\n"
            f"{listed}"
        )
        delete_button = box.addButton("Delete Downloads", QMessageBox.DestructiveRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Cancel)
        box.exec()
        return box.clickedButton() == delete_button

    def _visible_no_texture_download_count(self) -> int:
        if self._active_results_view != "local":
            return 0
        return len(self._no_texture_download_item_ids)

    def _clear_deleted_local_state(self, deleted_targets: list[Path]) -> None:
        self._invalidate_prepared_row_source()
        target_ids = tuple(
            os.path.normcase(os.path.abspath(str(target))).casefold().rstrip("\\/")
            for target in deleted_targets
        )

        def is_deleted_path(value: object) -> bool:
            text = str(value or "").strip()
            if not text:
                return False
            path_id = os.path.normcase(os.path.abspath(text)).casefold().rstrip("\\/")
            return any(path_id == target or path_id.startswith(f"{target}{os.sep}") for target in target_ids)

        for payload in self.mirror_results:
            if any(is_deleted_path(payload.get(key)) for key in ("asset_dir", "archive_path", "import_path")):
                for key in ("asset_dir", "archive_path", "import_path", "download_format", "local_status"):
                    payload.pop(key, None)
        self.local_models = [
            payload
            for payload in self.local_models
            if not any(is_deleted_path(payload.get(key)) for key in ("asset_dir", "archive_path", "import_path", "path"))
        ]


__all__ = ["ModelLibraryResultsMixin"]
