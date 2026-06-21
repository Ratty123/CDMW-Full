"""Archive browser Item Finder dialog."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Dict, List, Tuple

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from cdmw.models import ArchiveEntry


class ArchiveAssetCatalogDialogMixin:
    """Item Finder dialog and visible-row icon loading UI."""
    def _show_archive_asset_catalog_dialog(self) -> None:
        if not self.archive_item_asset_catalog:
            QMessageBox.information(
                self,
                "Item Finder",
                "No item/asset index is available yet. Scan archives first, or refresh the archive scan so the derived item-name index can be rebuilt.",
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Item Finder")
        dialog.resize(1240, 780)
        self.archive_item_icon_negative_cache.clear()
        saved_geometry = self.settings.value("ui/item_finder_geometry")
        if saved_geometry:
            try:
                dialog.restoreGeometry(saved_geometry)
            except Exception:
                pass
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        intro = QLabel(
            "Browse recovered item names, icons, model links, and related files. Selecting an item scopes the Archive Browser through the direct index, without re-filtering every archive row."
        )
        intro.setObjectName("HintLabel")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        search_edit = QLineEdit()
        search_edit.setPlaceholderText("Search item name, internal ID, model stem, category, material tag, texture, or icon path")
        clear_search_button = QPushButton("Clear")
        clear_search_button.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        controls.addWidget(search_edit, stretch=1)
        controls.addWidget(clear_search_button)
        layout.addLayout(controls)

        content_splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(content_splitter, stretch=1)

        browser_panel = QFrame()
        browser_panel.setObjectName("ItemFinderBrowsePanel")
        browser_panel_layout = QVBoxLayout(browser_panel)
        browser_panel_layout.setContentsMargins(0, 0, 0, 0)
        browser_panel_layout.setSpacing(6)
        browser_title = QLabel("Browse")
        browser_title.setObjectName("SectionLabel")
        browser_panel_layout.addWidget(browser_title)
        category_tree = QTreeWidget()
        category_tree.setColumnCount(1)
        category_tree.setHeaderHidden(True)
        category_tree.setRootIsDecorated(True)
        category_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        category_tree.setUniformRowHeights(True)
        browser_panel_layout.addWidget(category_tree, stretch=1)
        content_splitter.addWidget(browser_panel)

        grid_panel = QFrame()
        grid_panel.setObjectName("ItemFinderGridPanel")
        grid_panel_layout = QVBoxLayout(grid_panel)
        grid_panel_layout.setContentsMargins(12, 0, 0, 0)
        grid_panel_layout.setSpacing(6)
        status_label = QLabel("")
        status_label.setObjectName("HintLabel")
        status_label.setWordWrap(True)
        status_label.setMinimumHeight(44)
        status_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        grid_panel_layout.addWidget(status_label)
        item_grid = QListWidget()
        item_grid.setObjectName("ItemFinderGrid")
        item_grid.setViewMode(QListView.ViewMode.IconMode)
        item_grid.setResizeMode(QListView.ResizeMode.Adjust)
        item_grid.setSelectionMode(QAbstractItemView.SingleSelection)
        item_grid.setIconSize(QSize(86, 86))
        item_grid.setGridSize(QSize(174, 150))
        item_grid.setSpacing(10)
        item_grid.setWordWrap(True)
        item_grid.setWrapping(True)
        item_grid.setUniformItemSizes(True)
        item_grid.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        grid_panel_layout.addWidget(item_grid, stretch=1)
        content_splitter.addWidget(grid_panel)

        detail_panel = QFrame()
        detail_panel.setObjectName("ItemFinderDetailPanel")
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(12, 0, 0, 0)
        detail_layout.setSpacing(8)
        detail_header = QHBoxLayout()
        detail_header.setSpacing(10)
        icon_preview = QLabel("Icon")
        icon_preview.setObjectName("ItemFinderIconPreview")
        icon_preview.setFixedSize(132, 132)
        icon_preview.setAlignment(Qt.AlignCenter)
        icon_preview.setStyleSheet(
            "QLabel#ItemFinderIconPreview { border: 1px solid #38424f; border-radius: 6px; background: #10161d; color: #7f8b99; }"
        )
        detail_header.addWidget(icon_preview)
        text_stack = QVBoxLayout()
        selected_title = QLabel("Select an item")
        selected_title.setObjectName("TitleLabel")
        selected_title.setWordWrap(True)
        selected_meta = QLabel("Recovered names, file links, icons, and evidence will appear here.")
        selected_meta.setObjectName("HintLabel")
        selected_meta.setWordWrap(True)
        text_stack.addWidget(selected_title)
        text_stack.addWidget(selected_meta)
        text_stack.addStretch(1)
        detail_header.addLayout(text_stack, stretch=1)
        detail_layout.addLayout(detail_header)

        evidence_label = QLabel("")
        evidence_label.setObjectName("HintLabel")
        evidence_label.setWordWrap(True)
        evidence_label.setMinimumHeight(112)
        evidence_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        evidence_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        detail_layout.addWidget(evidence_label)

        linked_tree = QTreeWidget()
        linked_tree.setColumnCount(2)
        linked_tree.setHeaderLabels(["Linked files", "Path"])
        linked_tree.setRootIsDecorated(True)
        linked_tree.setAlternatingRowColors(True)
        linked_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        linked_tree.setUniformRowHeights(True)
        linked_header = linked_tree.header()
        linked_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        linked_header.setSectionResizeMode(1, QHeaderView.Stretch)
        detail_layout.addWidget(linked_tree, stretch=1)

        detail_buttons = QHBoxLayout()
        exact_scope_button = QPushButton("Show Exact Links")
        exact_scope_button.setToolTip("Show only direct model/icon paths recovered for this item row.")
        scope_button = QPushButton("Show Related Set")
        scope_button.setToolTip(
            "Show direct links plus indexed companion files such as textures, material sidecars, HKX, meshinfo, and rig data. "
            "Some related rows can appear as Resolved (Partial) because they were matched through basename or companion evidence."
        )
        preview_icon_button = QPushButton("Open Icon")
        close_button = QPushButton("Close")
        detail_buttons.addWidget(exact_scope_button)
        detail_buttons.addWidget(scope_button)
        detail_buttons.addWidget(preview_icon_button)
        detail_buttons.addStretch(1)
        detail_buttons.addWidget(close_button)
        detail_layout.addLayout(detail_buttons)
        content_splitter.addWidget(detail_panel)
        content_splitter.setStretchFactor(0, 0)
        content_splitter.setStretchFactor(1, 1)
        content_splitter.setStretchFactor(2, 0)
        saved_splitter_sizes = self._load_saved_splitter_sizes("ui/item_finder_splitter_sizes")
        content_splitter.setSizes(saved_splitter_sizes or [220, 680, 340])

        icon_preview_timer = QTimer(dialog)
        icon_preview_timer.setSingleShot(True)
        icon_row_timer = QTimer(dialog)
        icon_row_timer.setSingleShot(True)
        icon_retry_timer = QTimer(dialog)
        icon_retry_timer.setSingleShot(True)
        icon_retry_timer.setInterval(220)
        icon_visible_queue_timer = QTimer(dialog)
        icon_visible_queue_timer.setSingleShot(True)
        icon_visible_queue_timer.setInterval(80)
        catalog_filter_timer = QTimer(dialog)
        catalog_filter_timer.setSingleShot(True)
        catalog_filter_timer.setInterval(160)
        icon_row_queue: List[QListWidgetItem] = []
        icon_visible_retry_budget = {"remaining": 8}
        restored_category = str(self.settings.value("ui/item_finder_category", "") or "")
        restored_group = str(self.settings.value("ui/item_finder_group", "") or "")
        restored_selected_key = str(self.settings.value("ui/item_finder_selected_key", "") or "")
        restored_scroll_value = self._read_int("ui/item_finder_scroll_value", 0)
        pending_restore = {
            "selection_key": restored_selected_key,
            "scroll_value": max(0, restored_scroll_value),
        }

        def _catalog_row_identity_key(row: Mapping[str, object]) -> str:
            internal_name = str(row.get("internal_name", "") or "").strip()
            display_name = str(row.get("display_name", "") or "").strip()
            category = str(row.get("category", "") or "").strip()
            group = str(row.get("group", "") or "").strip()
            model_stems = "|".join(self._archive_asset_catalog_row_values(row, "model_stems")[:4])
            icon_paths = "|".join(self._archive_asset_catalog_row_values(row, "icon_paths")[:4])
            return "\u001f".join((internal_name, display_name, category, group, model_stems, icon_paths))

        def _populate_category_tree() -> None:
            category_tree.clear()
            category_counts: Dict[str, int] = {}
            group_counts: Dict[Tuple[str, str], int] = {}
            for row in self.archive_item_asset_catalog:
                category = str(row.get("category", "") or "Item")
                group = str(row.get("group", "") or "Unclassified")
                category_counts[category] = category_counts.get(category, 0) + 1
                group_key = (category, group)
                group_counts[group_key] = group_counts.get(group_key, 0) + 1

            all_item = QTreeWidgetItem(category_tree)
            all_item.setText(0, f"All items ({len(self.archive_item_asset_catalog):,})")
            all_item.setData(0, Qt.UserRole, ("", ""))
            for category in self._archive_asset_catalog_categories():
                category_item = QTreeWidgetItem(category_tree)
                category_item.setText(0, f"{category} ({category_counts.get(category, 0):,})")
                category_item.setData(0, Qt.UserRole, (category, ""))
                for group in self._archive_asset_catalog_group_choices(category):
                    group_item = QTreeWidgetItem(category_item)
                    group_item.setText(0, f"{group} ({group_counts.get((category, group), 0):,})")
                    group_item.setData(0, Qt.UserRole, (category, group))
                category_item.setExpanded(False)
            category_tree.collapseAll()
            restore_item = all_item
            if restored_category:
                for top_index in range(category_tree.topLevelItemCount()):
                    top_item = category_tree.topLevelItem(top_index)
                    top_data = top_item.data(0, Qt.UserRole) if top_item is not None else None
                    if isinstance(top_data, tuple) and str(top_data[0] or "") == restored_category:
                        restore_item = top_item
                        if restored_group:
                            top_item.setExpanded(True)
                            for child_index in range(top_item.childCount()):
                                child = top_item.child(child_index)
                                child_data = child.data(0, Qt.UserRole) if child is not None else None
                                if (
                                    isinstance(child_data, tuple)
                                    and str(child_data[0] or "") == restored_category
                                    and str(child_data[1] or "") == restored_group
                                ):
                                    restore_item = child
                                    break
                        break
            category_tree.setCurrentItem(restore_item)

        def _current_browser_filter() -> Tuple[str, str]:
            item = category_tree.currentItem()
            if item is None:
                return "", ""
            data = item.data(0, Qt.UserRole)
            if isinstance(data, tuple) and len(data) == 2:
                return str(data[0] or ""), str(data[1] or "")
            return "", ""

        def _catalog_row_prepared_icon_available(row: Mapping[str, object]) -> bool:
            prepared_key = self._archive_asset_catalog_prepared_icon_cache_key(row)
            prepared = self.archive_item_icon_prepared_path_cache.get(prepared_key)
            if prepared is None:
                return False
            preview_path_text, _prepared_note = prepared
            try:
                preview_path = Path(str(preview_path_text))
                return preview_path.is_file() and preview_path.stat().st_size > 0
            except OSError:
                return False

        def _apply_catalog_item_cached_icon(item: QListWidgetItem, row: Mapping[str, object]) -> Tuple[bool, str]:
            pixmap, note = self._cached_archive_asset_catalog_inventory_icon_pixmap(
                row,
                86,
                allow_sync_prepare=False,
            )
            if pixmap is None or pixmap.isNull():
                return False, note
            item.setIcon(QIcon(pixmap))
            item.setToolTip(note or item.toolTip() or "Recovered inventory icon")
            item.setData(Qt.UserRole + 1, "thumb_loaded")
            item_rect = item_grid.visualItemRect(item)
            if item_rect.isValid():
                item_grid.viewport().update(item_rect)
            else:
                item_grid.viewport().update()
            if item is item_grid.currentItem():
                icon_preview_timer.start(0)
            return True, note

        def _queue_catalog_row_icons_for_visible_rows() -> None:
            if not dialog.isVisible():
                remaining = int(icon_visible_retry_budget.get("remaining", 0) or 0)
                if remaining > 0:
                    icon_visible_retry_budget["remaining"] = remaining - 1
                    icon_visible_queue_timer.start(80)
                return
            icon_visible_retry_budget["remaining"] = 8
            viewport_rect = item_grid.viewport().rect().adjusted(-180, -240, 220, 600)
            visible_candidates: List[QListWidgetItem] = []
            for row_index in range(item_grid.count()):
                item = item_grid.item(row_index)
                if item is None:
                    continue
                row = item.data(Qt.UserRole)
                if not isinstance(row, Mapping):
                    continue
                if not self._archive_asset_catalog_row_values(row, "icon_paths"):
                    continue
                state = item.data(Qt.UserRole + 1)
                if state == "thumb_loaded":
                    continue
                if state == "thumb_pending" and not _catalog_row_prepared_icon_available(row):
                    continue
                loaded, _note = _apply_catalog_item_cached_icon(item, row)
                if loaded:
                    continue
                item_rect = item_grid.visualItemRect(item)
                if item_rect.isValid() and item_rect.intersects(viewport_rect):
                    visible_candidates.append(item)
                elif not item_rect.isValid() and row_index < 80:
                    visible_candidates.append(item)
                if len(visible_candidates) >= 120:
                    break
            viewport_center_y = item_grid.viewport().rect().center().y()
            visible_candidates.sort(
                key=lambda candidate: abs(item_grid.visualItemRect(candidate).center().y() - viewport_center_y)
                if item_grid.visualItemRect(candidate).isValid()
                else 0
            )
            visible_ids = {id(item) for item in visible_candidates}
            if icon_row_queue:
                retained_queue: List[QListWidgetItem] = []
                for item in icon_row_queue:
                    if id(item) in visible_ids:
                        item.setData(Qt.UserRole + 1, "thumb_pending")
                        retained_queue.append(item)
                    elif item_grid.row(item) >= 0 and item.data(Qt.UserRole + 1) == "thumb_pending":
                        item.setData(Qt.UserRole + 1, "fallback")
                icon_row_queue[:] = retained_queue
            queued_ids = {id(item) for item in icon_row_queue}
            for item in visible_candidates:
                if id(item) in queued_ids:
                    item.setData(Qt.UserRole + 1, "thumb_pending")
                    continue
                item.setData(Qt.UserRole + 1, "thumb_pending")
                icon_row_queue.insert(0, item)
            self._queue_archive_asset_catalog_icon_warmup_rows(
                [
                    item.data(Qt.UserRole)
                    for item in visible_candidates
                    if isinstance(item.data(Qt.UserRole), Mapping)
                ],
                front=True,
                user_visible=True,
                delay_ms=0,
            )
            if icon_row_queue and not icon_row_timer.isActive():
                icon_row_timer.start(1)

        def _queue_catalog_row_icons_coalesced(delay_ms: int = 80) -> None:
            if not dialog.isVisible():
                return
            icon_visible_queue_timer.start(max(0, int(delay_ms)))

        def _load_next_catalog_row_icon() -> None:
            if not dialog.isVisible():
                icon_row_queue.clear()
                icon_row_timer.stop()
                return
            batch_started_at = time.perf_counter()
            loaded_count = 0
            while icon_row_queue:
                item = icon_row_queue.pop(0)
                if item_grid.row(item) < 0:
                    continue
                item_rect = item_grid.visualItemRect(item)
                active_rect = item_grid.viewport().rect().adjusted(-220, -280, 260, 680)
                if item_rect.isValid() and not item_rect.intersects(active_rect):
                    if item.data(Qt.UserRole + 1) == "thumb_pending":
                        item.setData(Qt.UserRole + 1, "fallback")
                    continue
                row = item.data(Qt.UserRole)
                if not isinstance(row, Mapping):
                    continue
                loaded, note = _apply_catalog_item_cached_icon(item, row)
                if loaded:
                    pass
                else:
                    note = self._archive_item_icon_negative_note(
                        self._archive_asset_catalog_prepared_icon_cache_key(row)
                    )
                    if not note:
                        _pixmap, note = self._cached_archive_asset_catalog_inventory_icon_pixmap(
                            row,
                            86,
                            allow_sync_prepare=False,
                        )
                if loaded:
                    pass
                elif "warming" in str(note).lower():
                    item.setData(Qt.UserRole + 1, "fallback")
                    if not icon_retry_timer.isActive():
                        icon_retry_timer.start()
                else:
                    item.setData(Qt.UserRole + 1, "thumb_missing")
                loaded_count += 1
                if loaded_count >= 4 or (time.perf_counter() - batch_started_at) >= 0.010:
                    break
            if icon_row_queue:
                icon_row_timer.start(16)

        def _populate_catalog() -> None:
            icon_row_timer.stop()
            icon_row_queue.clear()
            query = search_edit.text().strip().lower()
            query_tokens = tuple(re.findall(r"[a-z0-9]+", query))
            selected_category, selected_group = _current_browser_filter()
            item_grid.setUpdatesEnabled(False)
            item_grid.clear()
            shown = 0
            hidden = 0
            display_limit = 600 if not query_tokens and not selected_category and not selected_group else 2500
            for row in self.archive_item_asset_catalog:
                category = str(row.get("category", "") or "Item")
                if selected_category and category != selected_category:
                    continue
                group = str(row.get("group", "") or "Unclassified")
                if selected_group and group != selected_group:
                    continue
                haystack = self._archive_asset_catalog_text(row)
                if query_tokens and not all(token in haystack for token in query_tokens):
                    continue
                pac_files = self._archive_asset_catalog_row_values(row, "pac_files")
                icon_paths = self._archive_asset_catalog_row_values(row, "icon_paths")
                display_name = str(row.get("display_name", "") or row.get("internal_name", "") or "Unnamed asset")
                internal_name = str(row.get("internal_name", "") or "")
                category_evidence = str(row.get("category_evidence", "") or "").strip()
                variant_count = int(row.get("variant_count", 1) or 1)
                linked_count = len(pac_files) + len(icon_paths)
                table_labels = self._archive_asset_catalog_table_evidence_labels(row)
                compatibility_tags = self._archive_asset_catalog_row_values(row, "compatibility_tags")
                material_tags = self._archive_asset_catalog_row_values(row, "material_tags")
                item = QListWidgetItem(display_name)
                item.setIcon(self._build_archive_asset_catalog_icon(category, display_name))
                item.setSizeHint(QSize(166, 140))
                item.setData(Qt.UserRole, dict(row))
                item.setData(Qt.UserRole + 1, "fallback")
                item.setData(Qt.UserRole + 2, f"{category} / {group}")
                tooltip_lines = [
                    display_name,
                    f"Internal: {internal_name or '-'}",
                    f"Category: {category} > {group}",
                    f"Evidence: {category_evidence or 'Name hint'}",
                    f"Direct links: {linked_count:,}",
                    f"Variants grouped: {variant_count:,}",
                ]
                if table_labels:
                    tooltip_lines.append(
                        "Table fields: "
                        + ", ".join(table_labels[:6])
                        + (" ..." if len(table_labels) > 6 else "")
                    )
                if compatibility_tags:
                    tooltip_lines.append(
                        "Compatibility: "
                        + ", ".join(compatibility_tags[:6])
                        + (" ..." if len(compatibility_tags) > 6 else "")
                    )
                if material_tags:
                    tooltip_lines.append(
                        "Material tags: "
                        + ", ".join(material_tags[:10])
                        + (" ..." if len(material_tags) > 10 else "")
                    )
                if pac_files:
                    tooltip_lines.append("Models: " + ", ".join(pac_files[:5]) + (" ..." if len(pac_files) > 5 else ""))
                if icon_paths:
                    tooltip_lines.append("Icons: " + ", ".join(icon_paths[:3]) + (" ..." if len(icon_paths) > 3 else ""))
                item.setToolTip("\n".join(tooltip_lines))
                item_grid.addItem(item)
                shown += 1
                if shown >= display_limit:
                    hidden += 1
                    break
            item_grid.setUpdatesEnabled(True)
            filter_text = "all items"
            if selected_category and selected_group:
                filter_text = f"{selected_category} / {selected_group}"
            elif selected_category:
                filter_text = selected_category
            limit_note = " First matching rows shown; refine search or choose a category to narrow the result." if hidden else ""
            status_label.setText(
                f"{shown:,} shown in {filter_text}. Double-click an item, use Show Exact Links, or use Show Related Set to scope the Archive Browser through indexed links.{limit_note}"
            )
            if item_grid.count() > 0:
                restored_row = -1
                selection_key = str(pending_restore.get("selection_key", "") or "")
                if selection_key:
                    for row_index in range(item_grid.count()):
                        candidate_item = item_grid.item(row_index)
                        candidate_row = candidate_item.data(Qt.UserRole) if candidate_item is not None else None
                        if isinstance(candidate_row, Mapping) and _catalog_row_identity_key(candidate_row) == selection_key:
                            restored_row = row_index
                            break
                item_grid.setCurrentRow(restored_row if restored_row >= 0 else 0)
                scroll_value = int(pending_restore.get("scroll_value", 0) or 0)
                if scroll_value > 0:
                    QTimer.singleShot(0, lambda value=scroll_value: item_grid.verticalScrollBar().setValue(value))
                pending_restore["selection_key"] = ""
                pending_restore["scroll_value"] = 0
            else:
                _update_selected_catalog_detail()
            QTimer.singleShot(140, _queue_catalog_row_icons_for_visible_rows)
            QTimer.singleShot(360, _queue_catalog_row_icons_for_visible_rows)
            QTimer.singleShot(900, _queue_catalog_row_icons_for_visible_rows)

        def _selected_catalog_row() -> Optional[Dict[str, object]]:
            item = item_grid.currentItem()
            if item is None:
                return None
            raw = item.data(Qt.UserRole)
            return dict(raw) if isinstance(raw, Mapping) else None

        def _add_link_group(title: str, values: Sequence[str], *, limit: int = 24) -> None:
            if not values:
                return
            group_item = QTreeWidgetItem(linked_tree)
            group_item.setText(0, f"{title} ({len(values):,})")
            group_item.setText(1, "")
            for value in values[:limit]:
                child = QTreeWidgetItem(group_item)
                child.setText(0, title.rstrip("s"))
                child.setText(1, str(value))
            if len(values) > limit:
                child = QTreeWidgetItem(group_item)
                child.setText(0, "More")
                child.setText(1, f"{len(values) - limit:,} more hidden here; Show Exact Links still scopes all recovered direct links.")
            group_item.setExpanded(True)

        def _update_selected_catalog_detail() -> None:
            row = _selected_catalog_row()
            if row is None:
                icon_preview.clear()
                icon_preview.setText("Icon")
                selected_title.setText("Select an item")
                selected_meta.setText("Recovered names, file links, icons, and evidence will appear here.")
                evidence_label.setText("")
                linked_tree.clear()
                exact_scope_button.setEnabled(False)
                scope_button.setEnabled(False)
                preview_icon_button.setEnabled(False)
                return
            display_name = str(row.get("display_name", "") or row.get("internal_name", "") or "Unnamed asset")
            internal_name = str(row.get("internal_name", "") or "").strip()
            category = str(row.get("category", "") or "Item")
            group = str(row.get("group", "") or "Unclassified")
            pac_files = self._archive_asset_catalog_row_values(row, "pac_files")
            model_stems = self._archive_asset_catalog_row_values(row, "model_stems")
            icon_paths = self._archive_asset_catalog_row_values(row, "icon_paths")
            if icon_paths:
                self._queue_archive_asset_catalog_icon_warmup_rows([row], front=True, user_visible=True, delay_ms=0)
            localized_names = self._archive_asset_catalog_row_values(row, "localized_names")
            material_tags = self._archive_asset_catalog_row_values(row, "material_tags")
            material_evidence = self._archive_asset_catalog_row_values(row, "material_evidence")
            variant_count = int(row.get("variant_count", 1) or 1)
            selected_title.setText(display_name)
            selected_meta.setText(
                f"{category} / {group}\n"
                f"{len(pac_files):,} direct model link(s), {len(icon_paths):,} icon path(s), {variant_count:,} grouped variant(s)."
            )
            category_evidence = str(row.get("category_evidence", "") or "").strip()
            evidence_parts = [str(row.get("evidence", "") or "Recovered item/name evidence.")]
            if category_evidence:
                evidence_parts.append(f"Category evidence: {category_evidence}")
            if internal_name:
                evidence_parts.append(f"Internal ID: {internal_name}")
            if localized_names:
                evidence_parts.append("Names: " + ", ".join(localized_names[:4]) + (" ..." if len(localized_names) > 4 else ""))
            if material_tags:
                evidence_parts.append("Material tags: " + ", ".join(material_tags[:12]) + (" ..." if len(material_tags) > 12 else ""))
            if material_evidence:
                evidence_parts.append(
                    "Material evidence: "
                    + ", ".join(material_evidence[:4])
                    + (" ..." if len(material_evidence) > 4 else "")
                )
            evidence_label.setText("\n".join(evidence_parts))
            linked_tree.clear()
            _add_link_group("Models", pac_files)
            _add_link_group("Model stems", model_stems, limit=12)
            _add_link_group("Icons", icon_paths)
            _add_link_group("Material tags", material_tags, limit=12)
            if linked_tree.topLevelItemCount() == 0:
                empty = QTreeWidgetItem(linked_tree)
                empty.setText(0, "No direct file links")
                empty.setText(1, "This item is searchable by name, but no model/icon path was recovered.")
            exact_scope_button.setEnabled(bool(pac_files or model_stems or icon_paths))
            scope_button.setEnabled(bool(pac_files or model_stems or icon_paths))
            preview_icon_button.setEnabled(bool(icon_paths))
            icon_preview_timer.start(120)

        def _refresh_selected_icon_preview() -> None:
            row = _selected_catalog_row()
            if row is None:
                return
            item = item_grid.currentItem()
            pixmap, note = self._cached_archive_asset_catalog_inventory_icon_pixmap(
                row,
                120,
                allow_sync_prepare=False,
            )
            category = str(row.get("category", "") or "Item")
            display_name = str(row.get("display_name", "") or row.get("internal_name", "") or "Item")
            if pixmap is None or pixmap.isNull():
                if "warming" in str(note).lower():
                    fallback = self._build_archive_asset_catalog_icon(category, display_name).pixmap(QSize(96, 96))
                    icon_preview.setPixmap(fallback)
                    icon_preview.setToolTip(note or "Icon preview is warming in the background.")
                    if item is not None and item.data(Qt.UserRole + 1) != "thumb_loaded":
                        item.setData(Qt.UserRole + 1, "thumb_pending")
                    icon_preview_timer.start(220)
                    return
            if pixmap is not None and not pixmap.isNull():
                icon_preview.setPixmap(pixmap.scaled(120, 120, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                if item is not None:
                    item.setIcon(QIcon(pixmap))
                    item.setData(Qt.UserRole + 1, "thumb_loaded")
                icon_preview.setToolTip(note or "Recovered item icon preview")
                return
            fallback = self._build_archive_asset_catalog_icon(category, display_name).pixmap(QSize(96, 96))
            icon_preview.setPixmap(fallback)
            icon_preview.setToolTip(note or "No recovered icon preview is available for this asset row.")

        def _handle_catalog_icon_prepared(prepared_key: Tuple[Tuple[str, ...], str]) -> None:
            if not dialog.isVisible():
                return
            icon_paths, texconv_key = prepared_key
            if texconv_key != self.texconv_path_edit.text().strip():
                return
            matched_items: List[QListWidgetItem] = []
            active_rect = item_grid.viewport().rect().adjusted(-220, -280, 260, 680)
            for row_index in range(item_grid.count()):
                item = item_grid.item(row_index)
                if item is None:
                    continue
                row = item.data(Qt.UserRole)
                if not isinstance(row, Mapping):
                    continue
                if tuple(self._archive_asset_catalog_row_values(row, "icon_paths")) != icon_paths:
                    continue
                item_rect = item_grid.visualItemRect(item)
                if item_rect.isValid() and not item_rect.intersects(active_rect):
                    continue
                loaded, _note = _apply_catalog_item_cached_icon(item, row)
                if not loaded:
                    item.setData(Qt.UserRole + 1, "fallback")
                    matched_items.append(item)
                if len(matched_items) >= 16:
                    break
            if matched_items:
                icon_row_queue[0:0] = matched_items
                icon_row_timer.start(0)
            current_row = _selected_catalog_row()
            if isinstance(current_row, Mapping) and tuple(self._archive_asset_catalog_row_values(current_row, "icon_paths")) == icon_paths:
                icon_preview_timer.start(0)

        def _scope_selected(*, include_related: bool = True) -> None:
            row = _selected_catalog_row()
            if row is None:
                QMessageBox.information(dialog, "Item Finder", "Select an asset row first.")
                return
            self._apply_archive_asset_catalog_scope(row, include_related=include_related)
            dialog.accept()

        def _find_selected_icon() -> None:
            row = _selected_catalog_row()
            if row is None:
                return
            icon_paths = self._archive_asset_catalog_row_values(row, "icon_paths")
            if not icon_paths:
                QMessageBox.information(dialog, "Item Finder", "No recovered icon path is attached to this asset row.")
                return
            icon_entries: List[ArchiveEntry] = []
            selected_icon_path = ""

            def _exact_icon_entries(icon_path: str) -> List[ArchiveEntry]:
                normalized = PurePosixPath(str(icon_path or "").replace("\\", "/")).as_posix().strip()
                if not normalized:
                    return []
                exact_entries: List[ArchiveEntry] = []
                seen: set[Tuple[str, str, int]] = set()

                def add_candidate(candidate_text: str) -> None:
                    candidate = PurePosixPath(str(candidate_text or "").replace("\\", "/")).as_posix().strip()
                    if not candidate:
                        return
                    for entry in self.archive_entries_by_normalized_path.get(candidate.lower(), ()):
                        key = (entry.path.lower(), str(entry.pamt_path).lower(), int(entry.offset))
                        if key not in seen:
                            seen.add(key)
                            exact_entries.append(entry)

                add_candidate(normalized)
                if not PurePosixPath(normalized).suffix:
                    add_candidate(f"{normalized}.dds")
                    add_candidate(f"{normalized}.png")
                return exact_entries

            for icon_path in icon_paths:
                icon_entries = _exact_icon_entries(icon_path)
                if not icon_entries:
                    icon_entries = self._resolve_archive_asset_catalog_path_candidates(
                        icon_path,
                        fallback_extensions=(".dds", ".png"),
                    )
                if icon_entries:
                    selected_icon_path = str(icon_path)
                    break
            if not icon_entries:
                QMessageBox.information(
                    dialog,
                    "Item Finder",
                    "No loaded archive entry could be resolved for the recovered icon path.",
                )
                return

            display_name = str(row.get("display_name", "") or row.get("internal_name", "") or "selected item")
            self._activate_tool_widget(self.archive_browser_tab)
            self._apply_archive_direct_scope(
                icon_entries,
                scope_label=f"{display_name} icon",
                placeholder_text=f"Item Finder icon scope active: {selected_icon_path}",
                hint_text=(
                    f"Item Finder icon scope active: {display_name}. "
                    f"Showing only {selected_icon_path}. Use Clear Scope to return to normal archive filters."
                ),
                progress_text=f"Item Finder icon scope: {len(icon_entries):,} indexed file(s).",
                log_text=(
                    f"Item Finder opened icon for {display_name}: {selected_icon_path} "
                    f"({len(icon_entries):,} indexed file(s); no full archive scan)."
                ),
            )
            dialog.accept()

        icon_preview_timer.timeout.connect(_refresh_selected_icon_preview)
        icon_row_timer.timeout.connect(_load_next_catalog_row_icon)
        icon_retry_timer.timeout.connect(_queue_catalog_row_icons_for_visible_rows)
        icon_visible_queue_timer.timeout.connect(_queue_catalog_row_icons_for_visible_rows)
        catalog_filter_timer.timeout.connect(_populate_catalog)
        search_edit.textChanged.connect(lambda _text: catalog_filter_timer.start())
        clear_search_button.clicked.connect(search_edit.clear)
        item_grid.verticalScrollBar().valueChanged.connect(lambda _value: _queue_catalog_row_icons_coalesced(80))
        item_grid.itemSelectionChanged.connect(_update_selected_catalog_detail)
        item_grid.itemDoubleClicked.connect(lambda _item: _scope_selected(include_related=True))
        exact_scope_button.clicked.connect(lambda _checked=False: _scope_selected(include_related=False))
        scope_button.clicked.connect(lambda _checked=False: _scope_selected(include_related=True))
        preview_icon_button.clicked.connect(_find_selected_icon)
        close_button.clicked.connect(dialog.reject)
        self.archive_item_icon_prepared_callbacks.append(_handle_catalog_icon_prepared)
        _populate_category_tree()
        restored_search_text = str(self.settings.value("ui/item_finder_search_text", "") or "")
        if restored_search_text:
            search_edit.setText(restored_search_text)
        category_tree.itemSelectionChanged.connect(lambda: catalog_filter_timer.start())
        _populate_catalog()
        try:
            dialog.exec()
        finally:
            try:
                self.archive_item_icon_prepared_callbacks.remove(_handle_catalog_icon_prepared)
            except ValueError:
                pass
            selected_category, selected_group = _current_browser_filter()
            selected_row = _selected_catalog_row()
            self.settings.setValue("ui/item_finder_geometry", dialog.saveGeometry())
            self.settings.setValue(
                "ui/item_finder_splitter_sizes",
                ",".join(str(value) for value in content_splitter.sizes()),
            )
            self.settings.setValue("ui/item_finder_search_text", search_edit.text())
            self.settings.setValue("ui/item_finder_category", selected_category)
            self.settings.setValue("ui/item_finder_group", selected_group)
            self.settings.setValue(
                "ui/item_finder_selected_key",
                _catalog_row_identity_key(selected_row) if isinstance(selected_row, Mapping) else "",
            )
            self.settings.setValue("ui/item_finder_scroll_value", item_grid.verticalScrollBar().value())
            catalog_filter_timer.stop()
            icon_preview_timer.stop()
            icon_row_timer.stop()
            icon_retry_timer.stop()
            icon_visible_queue_timer.stop()
            icon_row_queue.clear()



__all__ = ["ArchiveAssetCatalogDialogMixin"]
