from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QAbstractItemView, QComboBox, QTreeWidget, QTreeWidgetItem

from cdmw.services.archive_query_service import build_archive_tree_index
from cdmw.models import ArchiveEntry
from cdmw.ui.research.archive_picker_state import (
    archive_picker_available_status_text,
    archive_picker_entries_from_sources,
    archive_picker_entry_for_path,
    archive_picker_entry_index_for_path,
    archive_picker_flat_limit_status_text,
    archive_picker_focus_flat_overflow_status_text,
    archive_picker_focus_missing_status_text,
    archive_picker_folder_parts,
    archive_picker_folder_status_text,
    archive_picker_path_lookup_maps,
    archive_picker_render_status_text,
    archive_picker_reusable_browser_tree_index,
    archive_picker_selected_entry_status_text,
    normalize_archive_path,
)
from cdmw.ui.research.models import (
    archive_picker_folder_key as _archive_picker_folder_key,
    archive_picker_item_kind as _archive_picker_item_kind,
    build_archive_picker_file_item,
    build_archive_picker_folder_item,
    current_archive_picker_entry_from_item,
    find_archive_picker_file_item as _find_archive_picker_file_item,
)

def refresh_archive_picker(self) -> None:
    self.archive_picker_entries = archive_picker_entries_from_sources(
        self.get_filtered_archive_entries(),
        self.get_archive_entries(),
    )
    self.archive_picker_lazy_entry_index_by_path = {}
    lookup_maps = archive_picker_path_lookup_maps(self.archive_picker_entries)
    self.archive_picker_entry_index_by_path = lookup_maps.entry_index_by_path
    self.archive_picker_entry_by_path = lookup_maps.entry_by_path
    reused_browser_index = False
    browser_tree_state = (
        self.get_archive_browser_tree_state()
        if self.get_archive_browser_tree_state is not None
        else {}
    )
    reusable_index = archive_picker_reusable_browser_tree_index(
        browser_tree_state,
        self.archive_picker_entries,
    )
    if reusable_index is not None:
        self.archive_picker_child_folders = reusable_index.child_folders
        self.archive_picker_direct_files = reusable_index.direct_files
        self.archive_picker_folder_entry_indexes = reusable_index.folder_entry_indexes
        self.archive_picker_folder_preview_stats = reusable_index.folder_preview_stats
        self.archive_picker_items_by_folder_key = {}
        reused_browser_index = True
    skipped_large_index = False
    if not reused_browser_index and len(self.archive_picker_entries) > 100_000:
        self.archive_picker_child_folders = {}
        self.archive_picker_direct_files = {}
        self.archive_picker_folder_entry_indexes = {}
        self.archive_picker_folder_preview_stats = {}
        self.archive_picker_items_by_folder_key = {}
        skipped_large_index = True
    elif not reused_browser_index:
        self._rebuild_archive_picker_index()
    self._populate_archive_picker_tree()
    self.archive_picker_status_label.setText(
        archive_picker_available_status_text(
            entry_count=len(self.archive_picker_entries),
            eager_path_maps=lookup_maps.eager_path_maps,
            view_mode=self._archive_picker_view_mode(),
            flat_render_limit=self.archive_picker_flat_render_limit,
            skipped_large_index=skipped_large_index,
        )
    )
    self.archive_picker_refresh_pending = False

def _archive_picker_view_mode(self) -> str:
    combo = getattr(self, "archive_picker_view_combo", None)
    if isinstance(combo, QComboBox):
        value = combo.currentData()
        if value in {"flat", "folders"}:
            return str(value)
    return "flat"

def _populate_archive_picker_tree(self) -> None:
    self._archive_picker_population_timer.stop()
    self.archive_picker_tree.blockSignals(True)
    self.archive_picker_tree.setUpdatesEnabled(False)
    self.archive_picker_tree.clear()
    self.archive_picker_items_by_folder_key = {}
    self.archive_picker_flat_rendered_count = 0
    self._pending_archive_picker_flat_index = 0
    self._pending_archive_picker_flat_total = 0
    if self._archive_picker_view_mode() == "flat":
        self._pending_archive_picker_flat_total = min(len(self.archive_picker_entries), self.archive_picker_flat_render_limit)
        self.archive_picker_tree.setRootIsDecorated(False)
    else:
        self.archive_picker_tree.setRootIsDecorated(True)
        for _leaf, child_key in self.archive_picker_child_folders.get((), []):
            self._create_archive_picker_folder_item(self.archive_picker_tree, child_key)
        for entry_index in self.archive_picker_direct_files.get((), []):
            self._create_archive_picker_file_item(self.archive_picker_tree, entry_index)
    self.archive_picker_tree.setUpdatesEnabled(True)
    self.archive_picker_tree.blockSignals(False)
    if self._pending_archive_picker_flat_total:
        self.archive_picker_status_label.setText(
            archive_picker_render_status_text(
                rendered_count=0,
                total=self._pending_archive_picker_flat_total,
            )
        )
        self._flush_archive_picker_population_batch()
        return
    if self.archive_picker_tree.topLevelItemCount() > 0:
        first = self.archive_picker_tree.topLevelItem(0)
        if first is not None:
            self.archive_picker_tree.setCurrentItem(first)
    self._column_autofit_timer.start()

def _flush_archive_picker_population_batch(self) -> None:
    total = self._pending_archive_picker_flat_total
    if total <= 0:
        return
    start = self._pending_archive_picker_flat_index
    end = min(total, start + self.ARCHIVE_PICKER_POPULATION_BATCH_SIZE)
    self.archive_picker_tree.setUpdatesEnabled(False)
    for entry_index in range(start, end):
        self._create_archive_picker_file_item(self.archive_picker_tree, entry_index, show_full_path=True)
    self.archive_picker_tree.setUpdatesEnabled(True)
    self._pending_archive_picker_flat_index = end
    self.archive_picker_flat_rendered_count = end
    self.archive_picker_status_label.setText(
        archive_picker_render_status_text(rendered_count=end, total=total)
    )
    if end < total:
        self._archive_picker_population_timer.start()
        return
    self._pending_archive_picker_flat_total = 0
    if self.archive_picker_tree.topLevelItemCount() > 0:
        first = self.archive_picker_tree.topLevelItem(0)
        if first is not None:
            self.archive_picker_tree.setCurrentItem(first)
    self._column_autofit_timer.start()

def _handle_archive_picker_view_changed(self) -> None:
    self._ensure_archive_picker_ready()
    self._populate_archive_picker_tree()
    if self._archive_picker_view_mode() == "flat" and len(self.archive_picker_entries) > self.archive_picker_flat_render_limit:
        self.archive_picker_status_label.setText(
            archive_picker_flat_limit_status_text(
                entry_count=len(self.archive_picker_entries),
                flat_render_limit=self.archive_picker_flat_render_limit,
            )
        )
    elif self.archive_picker_entries:
        self.archive_picker_status_label.setText(
            f"{len(self.archive_picker_entries):,} archive file(s) available from the current Archive Browser view."
        )

def mark_archive_picker_dirty(self) -> None:
    self.archive_picker_refresh_pending = True

def refresh_archive_picker_if_pending(self) -> None:
    if self.archive_picker_refresh_pending:
        self.refresh_archive_picker()

def _rebuild_archive_picker_index(self) -> None:
    (
        self.archive_picker_child_folders,
        self.archive_picker_direct_files,
        self.archive_picker_folder_entry_indexes,
        self.archive_picker_folder_preview_stats,
    ) = build_archive_tree_index(self.archive_picker_entries)
    self.archive_picker_items_by_folder_key = {}

def _create_archive_picker_folder_item(
    self,
    parent: QTreeWidget | QTreeWidgetItem,
    folder_key: tuple[str, ...],
) -> QTreeWidgetItem:
    item = build_archive_picker_folder_item(
        folder_key,
        has_children=bool(self.archive_picker_child_folders.get(folder_key) or self.archive_picker_direct_files.get(folder_key)),
    )
    parent.addTopLevelItem(item) if isinstance(parent, QTreeWidget) else parent.addChild(item)
    self.archive_picker_items_by_folder_key[folder_key] = item
    return item

def _create_archive_picker_file_item(
    self,
    parent: QTreeWidget | QTreeWidgetItem,
    entry_index: int,
    *,
    show_full_path: bool = False,
) -> Optional[QTreeWidgetItem]:
    if not (0 <= entry_index < len(self.archive_picker_entries)):
        return None
    entry = self.archive_picker_entries[entry_index]
    item = build_archive_picker_file_item(entry, entry_index, show_full_path=show_full_path)
    parent.addTopLevelItem(item) if isinstance(parent, QTreeWidget) else parent.addChild(item)
    return item

def _ensure_archive_picker_folder_item_populated(self, item: Optional[QTreeWidgetItem]) -> None:
    if item is None or _archive_picker_item_kind(item) != "folder":
        return
    if item.childCount() == 1 and item.child(0).text(0) == "Loading...":
        item.takeChildren()
    elif item.childCount() > 0:
        return
    folder_key = _archive_picker_folder_key(item)
    for _leaf, child_key in self.archive_picker_child_folders.get(folder_key, []):
        self._create_archive_picker_folder_item(item, child_key)
    for entry_index in self.archive_picker_direct_files.get(folder_key, []):
        self._create_archive_picker_file_item(item, entry_index)

def _handle_archive_picker_item_expanded(self, item: QTreeWidgetItem) -> None:
    self._ensure_archive_picker_folder_item_populated(item)

def _ensure_archive_picker_folder_path(
    self,
    folder_parts: tuple[str, ...],
) -> Optional[QTreeWidgetItem]:
    if not folder_parts:
        return None
    current_folder_key: tuple[str, ...] = ()
    current_item: Optional[QTreeWidgetItem] = None
    for part in folder_parts:
        current_folder_key = (*current_folder_key, part)
        folder_item = self.archive_picker_items_by_folder_key.get(current_folder_key)
        if folder_item is None:
            parent_item = self.archive_picker_items_by_folder_key.get(current_folder_key[:-1])
            if parent_item is not None:
                self._ensure_archive_picker_folder_item_populated(parent_item)
            folder_item = self.archive_picker_items_by_folder_key.get(current_folder_key)
        if folder_item is None:
            return None
        self._ensure_archive_picker_folder_item_populated(folder_item)
        folder_item.setExpanded(True)
        current_item = folder_item
    return current_item

def _focus_archive_picker_path(self, path_value: str) -> bool:
    self._ensure_archive_picker_ready()
    normalized = normalize_archive_path(path_value)
    if not normalized:
        return False
    entry_index = self._archive_picker_entry_index_for_path(normalized)
    if entry_index is None:
        self.archive_picker_status_label.setText(
            archive_picker_focus_missing_status_text(normalized)
        )
        return False

    container: QTreeWidget | QTreeWidgetItem = self.archive_picker_tree
    if self._archive_picker_view_mode() == "flat":
        if entry_index >= self.archive_picker_flat_rendered_count:
            self.archive_picker_status_label.setText(
                archive_picker_focus_flat_overflow_status_text(
                    normalized,
                    rendered_count=self.archive_picker_flat_rendered_count,
                )
            )
            return False
    else:
        folder_parts = archive_picker_folder_parts(normalized)
        if folder_parts:
            folder_item = self._ensure_archive_picker_folder_path(folder_parts)
            if folder_item is None:
                return False
            container = folder_item
    file_item = _find_archive_picker_file_item(container, entry_index)
    if file_item is None:
        return False
    self.right_panel_stack.setCurrentWidget(self.archive_picker_group)
    self.archive_picker_tree.setCurrentItem(file_item)
    self.archive_picker_tree.scrollToItem(file_item, QAbstractItemView.PositionAtCenter)
    return True

def _archive_picker_entry_index_for_path(self, path_value: str) -> Optional[int]:
    return archive_picker_entry_index_for_path(
        path_value,
        entries=self.archive_picker_entries,
        entry_index_by_path=self.archive_picker_entry_index_by_path,
        lazy_entry_index_by_path=self.archive_picker_lazy_entry_index_by_path,
    )

def _archive_picker_entry_for_path(self, path_value: str) -> Optional[ArchiveEntry]:
    return archive_picker_entry_for_path(
        path_value,
        entries=self.archive_picker_entries,
        entry_by_path=self.archive_picker_entry_by_path,
        entry_index_by_path=self.archive_picker_entry_index_by_path,
        lazy_entry_index_by_path=self.archive_picker_lazy_entry_index_by_path,
    )

def _handle_archive_picker_current_item_change(
    self,
    current: Optional[QTreeWidgetItem],
    _previous: Optional[QTreeWidgetItem],
) -> None:
    entry = current_archive_picker_entry_from_item(current, self.archive_picker_entries)
    if entry is not None:
        self.archive_picker_status_label.setText(archive_picker_selected_entry_status_text(entry))
        self._render_archive_picker_preview_for_entry(entry)
        return
    if current is not None and _archive_picker_item_kind(current) == "folder":
        folder_key = _archive_picker_folder_key(current)
        folder_text = "/".join(folder_key) if folder_key else "/"
        count = len(self.archive_picker_folder_entry_indexes.get(folder_key, []))
        self.archive_picker_status_label.setText(archive_picker_folder_status_text(folder_text, count=count))
        self._show_archive_picker_folder_preview(folder_text, count)
        return
    self._clear_archive_picker_preview("Select a file in Archive Files to preview it here.")

def use_selected_archive_picker_for_reference(self) -> None:
    self._ensure_archive_picker_ready()
    entry = current_archive_picker_entry_from_item(self.archive_picker_tree.currentItem(), self.archive_picker_entries)
    if entry is None:
        self.status_message_requested.emit("Select a file in Research -> Archive Files first.", True)
        return
    self._populate_reference_target(entry.path)

def use_selected_archive_picker_for_note(self) -> None:
    self._ensure_archive_picker_ready()
    entry = current_archive_picker_entry_from_item(self.archive_picker_tree.currentItem(), self.archive_picker_entries)
    if entry is None:
        self.status_message_requested.emit("Select a file in Research -> Archive Files first.", True)
        return
    self._populate_note_target("archive", entry.path)
