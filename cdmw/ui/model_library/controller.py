"""Controller mixins for Model Library result coordination."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QTreeWidgetItem

from cdmw.ui.model_library.state import model_library_texture_status_kind


class ModelLibraryResultsMixin:
    """Filtering, sorting, and batched result-tree population."""

    def _filtered_result_rows(self, rows: list[dict[str, object]]) -> list[dict[str, object]]:
        self._last_hidden_downloaded_count = 0
        visible = list(rows)
        if self._active_results_view == "local":
            query = str(self.search_edit.text() if hasattr(self, "search_edit") else "").strip()
            if query:
                field = str(
                    self.results_filter_field_combo.currentData()
                    if hasattr(self, "results_filter_field_combo")
                    else "all"
                )
                terms = [term.casefold() for term in re.findall(r"[^\s,;]+", query) if term.strip()]
                if terms:
                    visible = [payload for payload in visible if self._local_payload_matches_filter(payload, terms, field)]
            visible = [payload for payload in visible if self._local_texture_filter_matches(payload)]
        elif self._active_results_view == "mirror" and getattr(self, "hide_downloaded_checkbox", None) and self.hide_downloaded_checkbox.isChecked():
            mirror_visible: list[dict[str, object]] = []
            for payload in visible:
                if not isinstance(payload, dict) or payload.get("kind") != "mirror":
                    mirror_visible.append(payload)
                    continue
                if self._mirror_payload_downloaded(payload):
                    self._last_hidden_downloaded_count += 1
                    continue
                mirror_visible.append(payload)
            visible = mirror_visible
        return self._filter_result_rows_by_columns(visible)

    def _local_texture_filter_matches(self, payload: dict[str, object]) -> bool:
        if not hasattr(self, "local_texture_filter_combo"):
            return True
        mode = str(self.local_texture_filter_combo.currentData() or "all")
        if mode == "all":
            return True
        status_kind = model_library_texture_status_kind(self._texture_status_for_payload(payload))
        if mode == "has":
            return status_kind == "present"
        if mode == "missing":
            return status_kind == "missing"
        return True

    def _filter_result_rows_by_columns(self, rows: list[dict[str, object]]) -> list[dict[str, object]]:
        filters = self._active_column_filters()
        if not filters:
            return rows
        filtered: list[dict[str, object]] = []
        for payload in rows:
            if self._payload_matches_column_filters(payload, filters):
                filtered.append(payload)
        return filtered

    def _payload_matches_column_filters(self, payload: dict[str, object], filters: dict[int, str]) -> bool:
        for column, query in filters.items():
            terms = [term.casefold() for term in re.findall(r"[^\s,;]+", query) if term.strip()]
            if not terms:
                continue
            haystack = self._result_column_filter_text(payload, column).casefold()
            if not haystack or not all(term in haystack for term in terms):
                return False
        return True

    def _local_payload_filter_values(self, payload: dict[str, object], field: str) -> list[str]:
        if field == "name":
            keys = ("name",)
        elif field == "creator":
            keys = ("creator_name", "creator_username", "source")
        elif field == "license":
            keys = ("license_label", "license_slug")
        elif field == "format":
            keys = ("extension", "format", "source")
        elif field == "path":
            keys = ("relative_path", "path", "root", "asset_dir", "archive_path", "import_path")
        elif field == "uid":
            keys = ("uid", "id")
        else:
            keys = (
                "name",
                "creator_name",
                "creator_username",
                "license_label",
                "license_slug",
                "extension",
                "format",
                "source",
                "relative_path",
                "path",
                "root",
                "asset_dir",
                "archive_path",
                "import_path",
                "uid",
                "id",
            )
        values: list[str] = []
        for key in keys:
            value = payload.get(key)
            if isinstance(value, (list, tuple, set)):
                values.extend(str(item) for item in value if str(item).strip())
            elif value is not None and str(value).strip():
                values.append(str(value))
        return values

    def _local_payload_matches_filter(self, payload: dict[str, object], terms: list[str], field: str) -> bool:
        if not isinstance(payload, dict):
            return False
        haystack = " ".join(self._local_payload_filter_values(payload, field)).casefold()
        return bool(haystack) and all(term in haystack for term in terms)

    def _mirror_payload_downloaded(self, payload: dict[str, object]) -> bool:
        if payload.get("kind") != "mirror":
            return False
        if str(payload.get("local_status", "") or "").strip():
            return True
        self._apply_mirror_local_state(payload)
        if str(payload.get("local_status", "") or "").strip():
            return True
        for key in ("import_path", "archive_path"):
            path_text = str(payload.get(key, "") or "").strip()
            if path_text and Path(path_text).is_file():
                return True
        asset_dir_text = str(payload.get("asset_dir", "") or "").strip()
        return bool(asset_dir_text and Path(asset_dir_text).is_dir())

    def _result_size_bytes(self, payload: dict[str, object]) -> int:
        if payload.get("kind") == "mirror":
            return self._mirror_size_bytes(payload)
        try:
            return int(payload.get("size", 0) or 0)
        except (TypeError, ValueError):
            return 0

    def _result_column_filter_text(self, payload: dict[str, object], column: int) -> str:
        if column == 0:
            return ""
        if column == 6:
            size = self._result_size_bytes(payload)
            return self._format_size(size) if size > 0 else "-"
        return self._result_sort_text(payload, column)

    def _result_sort_text(self, payload: dict[str, object], column: int) -> str:
        if payload.get("kind") == "mirror":
            if column == 2:
                return "Mirror"
            if column == 3:
                self._apply_mirror_local_state(payload)
                return self._mirror_local_status(payload)
            if column == 4:
                return self._texture_status_for_payload(payload)
            if column == 5:
                return ", ".join(candidate.format for candidate in self._mirror_candidates_for_payload(payload))
            if column == 7:
                return str(payload.get("license_label", "") or "")
            if column == 8:
                return str(payload.get("creator_name", "") or payload.get("creator_username", "") or "")
            if column == 9:
                return str(payload.get("viewer_url", "") or payload.get("metadata_url", "") or "")
            return str(payload.get("name", "") or "Untitled model")
        if column == 2:
            return str(payload.get("source", "") or "Local")
        if column == 3:
            return self._local_payload_status(payload)
        if column == 4:
            return self._texture_status_for_payload(payload)
        if column == 5:
            return str(payload.get("extension", "") or "")
        if column == 7:
            return str(payload.get("license_label", "") or "")
        if column == 8:
            return str(payload.get("creator_name", "") or payload.get("creator_username", "") or "")
        if column == 9:
            return str(payload.get("relative_path", "") or payload.get("path", "") or "")
        return str(payload.get("name", "") or "Untitled model")

    def _sort_result_rows(self, rows: list[dict[str, object]]) -> list[dict[str, object]]:
        if int(self._result_sort_column) < 0:
            return list(rows)
        column = max(0, min(int(self._result_sort_column), self.results_tree.columnCount() - 1))
        descending = self._result_sort_order == Qt.SortOrder.DescendingOrder

        def sort_key(payload: dict[str, object]) -> tuple[object, object, str]:
            name = str(payload.get("name", "") or "Untitled model").casefold()
            if column == 6:
                return (self._result_size_bytes(payload), 0, name)
            text = self._result_sort_text(payload, column).casefold()
            numeric_name_rank = 1 if column == 1 and text.strip().isdigit() else 0
            return (numeric_name_rank, text, name)

        return sorted(rows, key=sort_key, reverse=descending)

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
        self._results_filter_timer.stop()
        self._results_population_timer.stop()
        self._auto_preview_timer.stop()
        selected_payload = self._selected_payload()
        total_count = len(rows)
        visible_rows = self._sort_result_rows(self._filtered_result_rows(rows))
        self._pending_results_rows = list(visible_rows)
        self._pending_results_total_count = total_count
        self._pending_results_visible_count = len(visible_rows)
        self._pending_results_selected_payload = selected_payload
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
        kind = str(payload.get("kind", "") or "")
        if kind == "mirror":
            self._apply_mirror_local_state(payload)
            formats = ", ".join(candidate.format for candidate in self._mirror_candidates_for_payload(payload)) or "-"
            size_bytes = self._mirror_size_bytes(payload)
            size = self._format_size(size_bytes) if size_bytes > 0 else "-"
            location = str(payload.get("viewer_url", "") or payload.get("metadata_url", "") or "")
            source = "Mirror"
            local_status = self._mirror_local_status(payload)
            texture_status = self._texture_status_for_payload(payload)
            license_label = str(payload.get("license_label", "") or "")
            creator = str(payload.get("creator_name", "") or payload.get("creator_username", "") or "")
        else:
            formats = str(payload.get("extension", "") or "")
            size_bytes = int(payload.get("size", 0) or 0)
            size = self._format_size(size_bytes)
            location = str(payload.get("relative_path", "") or payload.get("path", "") or "")
            source = str(payload.get("source", "") or "Local")
            local_status = self._local_payload_status(payload)
            texture_status = self._texture_status_for_payload(payload)
            license_label = str(payload.get("license_label", "") or "")
            creator = str(payload.get("creator_name", "") or payload.get("creator_username", "") or "")
        item = QTreeWidgetItem(
            [
                "",
                str(payload.get("name", "") or "Untitled model"),
                source,
                local_status,
                texture_status,
                formats,
                size,
                license_label,
                creator,
                location,
            ]
        )
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Unchecked)
        item.setData(0, Qt.ItemDataRole.UserRole, payload)
        item.setData(1, Qt.ItemDataRole.UserRole, payload)
        self._result_payloads_by_item[id(item)] = payload
        self._result_items_by_payload_id[id(payload)] = item
        return item

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
        selected_key = self._payload_population_key(self._pending_results_selected_payload)
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
        self._populating_results = False
        self._update_selection_state()

    def _flush_results_population_batch(self) -> None:
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
        if payload is None or model_library_texture_status_kind(item.text(4)) != "missing":
            return
        if self._downloaded_model_folder_target_for_payload(payload) is not None:
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

    def _local_delete_targets_for_payloads(self, payloads: list[dict[str, object]]) -> list[tuple[Path, str]]:
        targets: list[tuple[Path, str]] = []
        seen: set[str] = set()
        for payload in payloads:
            target = self._local_delete_target_for_payload(payload)
            if target is None:
                continue
            path, label = target
            try:
                resolved_key = str(path.resolve()).casefold()
            except OSError:
                resolved_key = str(path.absolute()).casefold()
            if resolved_key in seen:
                continue
            seen.add(resolved_key)
            targets.append((path, label))
        return targets

    def _no_texture_download_delete_targets_for_payloads(self, payloads: list[dict[str, object]]) -> list[tuple[Path, str]]:
        targets: list[tuple[Path, str]] = []
        seen: set[str] = set()
        for payload in payloads:
            target = self._no_texture_download_delete_target_for_payload(payload)
            if target is None:
                continue
            path, label = target
            try:
                resolved_key = str(path.resolve()).casefold()
            except OSError:
                resolved_key = str(path.absolute()).casefold()
            if resolved_key in seen:
                continue
            seen.add(resolved_key)
            targets.append((path, label))
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

    def _local_delete_target_for_payload(self, payload: Optional[dict[str, object]]) -> Optional[tuple[Path, str]]:
        if not payload:
            return None
        asset_dir_text = str(payload.get("asset_dir", "") or "").strip()
        if asset_dir_text:
            asset_dir = Path(asset_dir_text)
            if asset_dir.is_dir() and (asset_dir / "model_metadata.json").is_file():
                return asset_dir, "downloaded model folder"
        archive_path = Path(str(payload.get("archive_path", "") or ""))
        try:
            download_root = self._download_output_root().resolve()
        except OSError:
            download_root = self._download_output_root().absolute()
        if archive_path.is_file() and self._download_metadata_path_for_local_path(archive_path, download_root) is not None:
            metadata_path = self._download_metadata_path_for_local_path(archive_path, download_root)
            if metadata_path is not None and metadata_path.parent.is_dir():
                return metadata_path.parent, "downloaded model folder"
        path = Path(str(payload.get("path", "") or ""))
        if payload.get("kind") == "local" and path.is_file():
            return path, "local model file"
        return None

    def _no_texture_download_delete_target_for_payload(self, payload: Optional[dict[str, object]]) -> Optional[tuple[Path, str]]:
        if not payload or model_library_texture_status_kind(self._texture_status_for_payload(payload)) != "missing":
            return None
        return self._downloaded_model_folder_target_for_payload(payload)

    def _downloaded_model_folder_target_for_payload(self, payload: Optional[dict[str, object]]) -> Optional[tuple[Path, str]]:
        if not payload:
            return None
        try:
            download_root = self._download_output_root().resolve()
        except OSError:
            download_root = self._download_output_root().absolute()
        asset_dir_text = str(payload.get("asset_dir", "") or "").strip()
        if asset_dir_text:
            asset_dir = Path(asset_dir_text)
            if (
                asset_dir.is_dir()
                and (asset_dir / "model_metadata.json").is_file()
                and self._path_is_under(asset_dir, download_root)
            ):
                return asset_dir, "downloaded model folder"
        archive_path = Path(str(payload.get("archive_path", "") or ""))
        if archive_path.is_file():
            metadata_path = self._download_metadata_path_for_local_path(archive_path, download_root)
            if metadata_path is not None and metadata_path.parent.is_dir() and self._path_is_under(metadata_path.parent, download_root):
                return metadata_path.parent, "downloaded model folder"
        return None

    def _path_is_under(self, path: Path, root: Path) -> bool:
        try:
            resolved_path = path.resolve()
        except OSError:
            resolved_path = path.absolute()
        try:
            resolved_root = root.resolve()
        except OSError:
            resolved_root = root.absolute()
        return resolved_path == resolved_root or resolved_root in resolved_path.parents

    def _confirm_delete_local_targets(self, targets: list[tuple[Path, str]]) -> bool:
        if not targets:
            return False
        box = QMessageBox(self)
        box.setWindowTitle("Delete Local Models")
        box.setIcon(QMessageBox.Warning)
        box.setText(f"Delete {len(targets):,} local item(s) from disk?")
        listed = "\n".join(f"- {label}: {path}" for path, label in targets[:8])
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

    def _confirm_delete_no_texture_download_targets(self, targets: list[tuple[Path, str]]) -> bool:
        if not targets:
            return False
        box = QMessageBox(self)
        box.setWindowTitle("Delete No-Texture Downloads")
        box.setIcon(QMessageBox.Warning)
        box.setText(f"Delete {len(targets):,} downloaded model folder(s) with no textures found?")
        listed = "\n".join(f"- {path}" for path, _label in targets[:8])
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
        def is_deleted_path(value: object) -> bool:
            text = str(value or "").strip()
            if not text:
                return False
            path = Path(text)
            try:
                resolved_path = path.resolve()
            except OSError:
                resolved_path = path.absolute()
            for target in deleted_targets:
                try:
                    resolved_target = target.resolve()
                except OSError:
                    resolved_target = target.absolute()
                if resolved_path == resolved_target or resolved_target in resolved_path.parents:
                    return True
            return False

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
