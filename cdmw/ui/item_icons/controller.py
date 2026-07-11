"""Controller mixins for the Item Icons UI."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QMessageBox, QTreeWidgetItem

from cdmw.domain.library.item_icons import ItemIconLibraryRecord
from cdmw.ui.item_icons.state import is_probable_item_icon_entry


class ItemIconRecordListMixin:
    def _record_matches_filter(self, record: ItemIconLibraryRecord, text: str) -> bool:
        if self.favorite_only_checkbox.isChecked() and not record.favorite:
            return False
        if not text:
            return True
        haystack = " ".join(
            (
                record.path.name,
                record.relative_path,
                str(record.path),
                " ".join(record.tags),
                record.notes,
                record.source_kind,
            )
        ).casefold()
        return all(part in haystack for part in text.casefold().split())

    def _schedule_records_tree_population(self, *, select_path: Optional[Path] = None) -> None:
        if select_path is not None:
            self._pending_record_select_key = str(select_path).casefold()
        self._record_filter_timer.start()

    def _populate_records_tree(self, *, select_path: Optional[Path] = None) -> None:
        self._record_filter_timer.stop()
        self._record_population_timer.stop()
        if select_path is not None:
            self._pending_record_select_key = str(select_path).casefold()
        selected_key = self._pending_record_select_key
        self._pending_record_select_key = ""
        filter_text = self.filter_edit.text().strip()
        self._pending_record_rows = [
            record
            for record in self.records
            if self._record_matches_filter(record, filter_text)
        ]
        self._pending_record_total = len(self._pending_record_rows)
        self.records_tree.blockSignals(True)
        self.records_tree.setUpdatesEnabled(False)
        sort_column = self.records_tree.sortColumn()
        sort_order = self.records_tree.header().sortIndicatorOrder()
        self.records_tree.setSortingEnabled(False)
        self.records_tree.clear()
        self.records_tree.header().setSortIndicator(sort_column, sort_order)
        self.records_tree.setUpdatesEnabled(True)
        self.records_tree.blockSignals(False)
        self._pending_record_select_key = selected_key
        self.library_status_label.setText(
            f"Populating icon sources... 0/{self._pending_record_total:,} shown."
        )
        self._flush_record_population_batch()

    def _build_record_item(self, record: ItemIconLibraryRecord) -> QTreeWidgetItem:
        size_text = f"{record.width}x{record.height}" if record.width and record.height else "-"
        name = ("* " if record.favorite else "") + record.path.name
        item = QTreeWidgetItem([name, size_text, ", ".join(record.tags), record.source_kind, record.relative_path])
        item.setData(0, Qt.ItemDataRole.UserRole, str(record.path))
        item.setToolTip(0, str(record.path))
        item.setToolTip(4, str(record.path))
        return item

    def _flush_record_population_batch(self) -> None:
        if not self._pending_record_rows:
            self.records_tree.setSortingEnabled(True)
            selected_key = self._pending_record_select_key
            target_item: Optional[QTreeWidgetItem] = None
            if selected_key:
                for index in range(self.records_tree.topLevelItemCount()):
                    item = self.records_tree.topLevelItem(index)
                    if str(item.data(0, Qt.ItemDataRole.UserRole) or "").casefold() == selected_key:
                        target_item = item
                        break
            if target_item is None and self.records_tree.topLevelItemCount() > 0:
                target_item = self.records_tree.topLevelItem(0)
            self._pending_record_select_key = ""
            if target_item is not None:
                self.records_tree.setCurrentItem(target_item)
            self.library_status_label.setText(
                f"{self._pending_record_total:,}/{len(self.records):,} icon source(s) shown."
            )
            return
        batch = self._pending_record_rows[: self.RECORD_POPULATION_BATCH_SIZE]
        del self._pending_record_rows[: self.RECORD_POPULATION_BATCH_SIZE]
        items = [self._build_record_item(record) for record in batch]
        self.records_tree.setUpdatesEnabled(False)
        self.records_tree.addTopLevelItems(items)
        self.records_tree.setUpdatesEnabled(True)
        shown = self._pending_record_total - len(self._pending_record_rows)
        self.library_status_label.setText(
            f"Populating icon sources... {shown:,}/{self._pending_record_total:,} shown."
        )
        if self._pending_record_rows:
            self._record_population_timer.start()
            return
        self._flush_record_population_batch()

    def _handle_record_selection(self, item: Optional[QTreeWidgetItem]) -> None:
        path = self.current_source_path(item)
        record = self._record_for_path(path) if path is not None else None
        self._loading_record = True
        try:
            self.favorite_checkbox.setChecked(bool(record.favorite) if record else False)
            self.tags_edit.setText(", ".join(record.tags) if record else "")
            self.notes_edit.setPlainText(record.notes if record else "")
        finally:
            self._loading_record = False
        if hasattr(self, "delete_source_button"):
            self.delete_source_button.setEnabled(bool(path is not None and path.is_file()))
        self._schedule_selected_record_previews()

    def _schedule_selected_record_previews(self) -> None:
        self._selection_preview_timer.start()

    def _refresh_selected_record_previews(self) -> None:
        self._selection_preview_timer.stop()
        self.update_source_preview()
        self.update_final_preview()

    def _record_for_path(self, path: Optional[Path]) -> Optional[ItemIconLibraryRecord]:
        if path is None:
            return None
        return self._records_by_key.get(str(path).casefold())

    def _record_tree_item(self, key: str) -> Optional[QTreeWidgetItem]:
        for index in range(self.records_tree.topLevelItemCount()):
            item = self.records_tree.topLevelItem(index)
            if str(item.data(0, Qt.ItemDataRole.UserRole) or "").casefold() == key:
                return item
        return None

    def _apply_record_to_item(self, item: QTreeWidgetItem, record: ItemIconLibraryRecord) -> None:
        item.setText(0, ("* " if record.favorite else "") + record.path.name)
        item.setText(1, f"{record.width}x{record.height}" if record.width and record.height else "-")
        item.setText(2, ", ".join(record.tags))
        item.setText(3, record.source_kind)
        item.setText(4, record.relative_path)
        item.setData(0, Qt.ItemDataRole.UserRole, str(record.path))
        item.setToolTip(0, str(record.path))
        item.setToolTip(4, str(record.path))

    def _upsert_loaded_record(self, record: ItemIconLibraryRecord, *, select: bool = False) -> None:
        key = str(record.path).casefold()
        position = self._record_positions_by_key.get(key)
        if position is None:
            self._record_positions_by_key[key] = len(self.records)
            self.records.append(record)
        elif 0 <= position < len(self.records):
            self.records[position] = record
        self._records_by_key[key] = record

        pending_match = False
        for index, pending in enumerate(self._pending_record_rows):
            if str(pending.path).casefold() == key:
                self._pending_record_rows[index] = record
                pending_match = True
                break
        item = self._record_tree_item(key)
        if self._record_matches_filter(record, self.filter_edit.text().strip()):
            if item is not None:
                self._apply_record_to_item(item, record)
            elif not pending_match:
                self.records_tree.addTopLevelItem(self._build_record_item(record))
        elif item is not None:
            self.records_tree.takeTopLevelItem(self.records_tree.indexOfTopLevelItem(item))
        if select:
            self.select_source_path(record.path)

    def _remove_loaded_record(self, path: Path) -> bool:
        key = str(path).casefold()
        selected = self.current_source_path()
        was_selected = selected is not None and str(selected).casefold() == key
        position = self._record_positions_by_key.pop(key, None)
        self._records_by_key.pop(key, None)
        if position is not None and 0 <= position < len(self.records):
            self.records.pop(position)
            self._record_positions_by_key = {
                str(record.path).casefold(): index for index, record in enumerate(self.records)
            }
        self._pending_record_rows = [
            record for record in self._pending_record_rows if str(record.path).casefold() != key
        ]
        item = self._record_tree_item(key)
        if item is not None:
            self.records_tree.takeTopLevelItem(self.records_tree.indexOfTopLevelItem(item))
        return was_selected

    def current_source_path(self, item: Optional[QTreeWidgetItem] = None) -> Optional[Path]:
        current = item or self.records_tree.currentItem()
        if current is None:
            return None
        text = str(current.data(0, Qt.ItemDataRole.UserRole) or "").strip()
        return Path(text).expanduser() if text else None

    def selected_library_source_path(self) -> Optional[Path]:
        return self.current_source_path()

    def select_source_path(self, source_path: Path) -> None:
        target = str(source_path.expanduser()).casefold()
        for index in range(self.records_tree.topLevelItemCount()):
            item = self.records_tree.topLevelItem(index)
            if str(item.data(0, Qt.ItemDataRole.UserRole) or "").casefold() == target:
                self.records_tree.setCurrentItem(item)
                self.records_tree.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)
                return

    def _target_path_for_entry(self, entry: object) -> str:
        return str(getattr(entry, "path", "") or "").replace("\\", "/").strip()

    def _target_entry_for_path(self, target_path: str) -> Optional[object]:
        normalized = str(target_path or "").replace("\\", "/").strip().casefold()
        if not normalized:
            return None
        return next((entry for entry in self._target_entries if self._target_path_for_entry(entry).casefold() == normalized), None)

    def _matching_target_entries(self, filter_text: str) -> list[object]:
        text = str(filter_text or "").replace("\\", "/").strip().casefold()
        if not text:
            return list(self._target_entries)
        terms = [part for part in text.split() if part]
        exact = self._target_entry_for_path(text)
        matches = [
            entry
            for entry in self._target_entries
            if all(term in self._target_path_for_entry(entry).casefold() for term in terms)
        ]
        if exact is not None and exact not in matches:
            matches.insert(0, exact)
        return matches

    def _populate_target_combo(self, *, select_path: str = "") -> None:
        filter_text = self.target_filter_edit.text().strip()
        matches = self._matching_target_entries(filter_text)
        exact_filter_entry = self._target_entry_for_path(filter_text)
        selected_entry = self._target_entry_for_path(select_path) or exact_filter_entry
        display_limit = 300
        shown = list(matches[:display_limit])
        if selected_entry is not None and selected_entry not in shown:
            shown.insert(0, selected_entry)
        self.target_combo.blockSignals(True)
        self.target_combo.clear()
        for entry in shown:
            path = self._target_path_for_entry(entry)
            self.target_combo.addItem(path, entry)
        if not self._target_entries:
            self.target_combo.addItem("Load archive data to choose existing item icon targets", None)
        elif not shown:
            self.target_combo.addItem("No existing item icon target matches this filter", None)
        if selected_entry is not None:
            selected_path = self._target_path_for_entry(selected_entry)
            selected_index = self.target_combo.findText(selected_path)
            if selected_index >= 0:
                self.target_combo.setCurrentIndex(selected_index)
        self.target_combo.blockSignals(False)
        if not self._target_entries:
            self.target_match_label.setText("No archive item icon targets are loaded yet.")
        elif len(matches) > len(shown):
            self.target_match_label.setText(
                f"Showing {len(shown):,} of {len(matches):,} matching existing icon target(s). Type more of the path/name to narrow it."
            )
        else:
            self.target_match_label.setText(f"{len(matches):,} matching existing icon target(s).")

    def _handle_target_filter_changed(self) -> None:
        self._target_filter_timer.stop()
        self._populate_target_combo(select_path=self.target_filter_edit.text().strip())
        self.update_final_preview()

    def _archive_target_signature(self, entries: Sequence[object]) -> tuple[object, ...]:
        first_path = str(getattr(entries[0], "path", "") or "") if entries else ""
        last_path = str(getattr(entries[-1], "path", "") or "") if entries else ""
        return (id(entries), len(entries), first_path, last_path)

    def schedule_targets_refresh(self, *, update_preview: bool = False) -> None:
        self._pending_target_refresh_update_preview = self._pending_target_refresh_update_preview or bool(update_preview)
        self._target_refresh_timer.start()

    def _flush_scheduled_target_refresh(self) -> None:
        update_preview = self._pending_target_refresh_update_preview
        self._pending_target_refresh_update_preview = False
        if not self.isVisible():
            return
        self.refresh_targets(update_preview=update_preview)

    def refresh_targets(self, *, force: bool = False, update_preview: bool = True) -> None:
        current_entry = self._current_target_entry()
        current_path = str(getattr(current_entry, "path", "") or "") if current_entry is not None else ""
        archive_entries = self.get_archive_entries()
        signature = self._archive_target_signature(archive_entries)
        if not force and signature == self._target_entries_signature:
            if update_preview:
                self.update_final_preview()
            return
        self._target_entries_signature = signature
        self._target_entries = sorted(
            (entry for entry in archive_entries if is_probable_item_icon_entry(entry)),
            key=lambda entry: str(getattr(entry, "path", "") or "").casefold(),
        )
        self._populate_target_combo(select_path=current_path)
        if update_preview:
            self.update_final_preview()

    def _current_target_entry(self) -> Optional[object]:
        typed_entry = self._target_entry_for_path(self.target_filter_edit.text().strip())
        if typed_entry is not None:
            return typed_entry
        entry = self.target_combo.currentData()
        return entry if entry is not None else None

    def _current_target_path(self) -> str:
        entry = self._current_target_entry()
        return str(getattr(entry, "path", "") or "") if entry is not None else ""

    def use_archive_selection_as_target(self) -> None:
        selected_path = str(self.get_current_archive_path() or "").replace("\\", "/").strip()
        if not selected_path:
            QMessageBox.information(self, "Icon Creator", "Select an item icon DDS in Archive Browser first.")
            return
        entry = self._target_entry_for_path(selected_path)
        if entry is None:
            QMessageBox.warning(
                self,
                "Icon Creator",
                "The current Archive Browser selection is not a loaded existing item icon target.",
            )
            return
        self.target_filter_edit.setText(self._target_path_for_entry(entry))
        self._populate_target_combo(select_path=self._target_path_for_entry(entry))
        self.update_final_preview()

    def open_current_target_in_archive_browser(self) -> None:
        target_path = self._current_target_path()
        if not target_path:
            QMessageBox.information(self, "Icon Creator", "Choose an existing target icon path first.")
            return
        self.open_target_in_archive_requested.emit(target_path)


__all__ = ["ItemIconRecordListMixin"]
