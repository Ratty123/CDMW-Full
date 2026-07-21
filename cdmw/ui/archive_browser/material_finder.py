"""Archive browser Material Finder dialog."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Dict, List, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from cdmw.models import ArchiveEntry


class ArchiveMaterialFinderMixin:
    """Material Finder dialog and scoped Archive Browser navigation."""

    def _show_archive_material_finder_dialog(self) -> None:
        remote_bridge = getattr(self, "archive_remote_bridge", None)
        if remote_bridge is not None and remote_bridge.displays_v2 and remote_bridge.current_session is not None:
            from cdmw.ui.archive_browser.remote_finder_dialog import show_remote_archive_finder

            show_remote_archive_finder(self, material_only=True)
            return
        if not self.archive_item_asset_catalog:
            QMessageBox.information(
                self,
                "Material Finder",
                "No item/material index is available yet. Scan archives first, or refresh the archive scan so the derived item-name index can be rebuilt.",
            )
            return
        material_rows = self._archive_material_catalog_rows()
        if not material_rows:
            QMessageBox.information(
                self,
                "Material Finder",
                "The current item index has no material tag evidence yet. Refresh the archive scan so item-to-material evidence can be rebuilt.",
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Material Finder")
        dialog.resize(1280, 780)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        intro = QLabel(
            "Search indexed material evidence and scope the Archive Browser to matching item links, models, material sidecars, DDS textures, and texture-layer families."
        )
        intro.setObjectName("HintLabel")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        search_edit = QLineEdit()
        search_edit.setPlaceholderText("Search material tag, item name, model stem, texture family, e.g. stone wood metal cloth")
        clear_search_button = QPushButton("Clear")
        clear_search_button.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        controls.addWidget(search_edit, stretch=1)
        controls.addWidget(clear_search_button)
        layout.addLayout(controls)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter, stretch=1)

        tag_panel = QFrame()
        tag_layout = QVBoxLayout(tag_panel)
        tag_layout.setContentsMargins(0, 0, 0, 0)
        tag_layout.setSpacing(6)
        tag_title = QLabel("Material Tags")
        tag_title.setObjectName("SectionLabel")
        tag_layout.addWidget(tag_title)
        tag_tree = QTreeWidget()
        tag_tree.setColumnCount(2)
        tag_tree.setHeaderLabels(["Material", "Items"])
        tag_tree.setRootIsDecorated(False)
        tag_tree.setUniformRowHeights(True)
        tag_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        tag_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        tag_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        tag_layout.addWidget(tag_tree, stretch=1)
        splitter.addWidget(tag_panel)

        result_panel = QFrame()
        result_layout = QVBoxLayout(result_panel)
        result_layout.setContentsMargins(12, 0, 0, 0)
        result_layout.setSpacing(6)
        result_status = QLabel("")
        result_status.setObjectName("HintLabel")
        result_status.setWordWrap(True)
        result_status.setMinimumHeight(42)
        result_layout.addWidget(result_status)
        result_tree = QTreeWidget()
        result_tree.setColumnCount(4)
        result_tree.setHeaderLabels(["Item", "Material tags", "Links", "Evidence"])
        result_tree.setRootIsDecorated(False)
        result_tree.setAlternatingRowColors(True)
        result_tree.setUniformRowHeights(True)
        result_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        result_header = result_tree.header()
        result_header.setSectionResizeMode(0, QHeaderView.Stretch)
        result_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        result_header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        result_header.setSectionResizeMode(3, QHeaderView.Stretch)
        result_layout.addWidget(result_tree, stretch=1)
        splitter.addWidget(result_panel)

        detail_panel = QFrame()
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(12, 0, 0, 0)
        detail_layout.setSpacing(8)
        detail_title = QLabel("Material Evidence")
        detail_title.setObjectName("SectionLabel")
        detail_layout.addWidget(detail_title)
        detail_summary = QLabel("Select a material row to inspect linked files and evidence.")
        detail_summary.setObjectName("HintLabel")
        detail_summary.setWordWrap(True)
        detail_summary.setMinimumHeight(84)
        detail_summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        detail_layout.addWidget(detail_summary)
        detail_tree = QTreeWidget()
        detail_tree.setColumnCount(2)
        detail_tree.setHeaderLabels(["Group", "Value"])
        detail_tree.setRootIsDecorated(True)
        detail_tree.setAlternatingRowColors(True)
        detail_tree.setUniformRowHeights(True)
        detail_tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        detail_tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        detail_layout.addWidget(detail_tree, stretch=1)

        buttons = QHBoxLayout()
        scope_selected_button = QPushButton("Show Selected Related Set")
        scope_selected_button.setToolTip("Scope the Archive Browser to the selected material row(s), including companion sidecars and DDS references.")
        scope_all_button = QPushButton("Show All Matches")
        scope_all_button.setToolTip("Scope the Archive Browser to all currently filtered material matches. Large result sets are capped to keep the UI responsive.")
        close_button = QPushButton("Close")
        buttons.addWidget(scope_selected_button)
        buttons.addWidget(scope_all_button)
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        detail_layout.addLayout(buttons)
        splitter.addWidget(detail_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([220, 650, 410])

        tag_counts = self._archive_material_catalog_tag_counts(material_rows)
        filtered_rows: List[Dict[str, object]] = []

        def _populate_tags() -> None:
            tag_tree.clear()
            all_item = QTreeWidgetItem(tag_tree)
            all_item.setText(0, "All material evidence")
            all_item.setText(1, f"{len(material_rows):,}")
            all_item.setData(0, Qt.UserRole, "")
            for tag, count in sorted(tag_counts.items(), key=lambda item: (-int(item[1]), str(item[0]))):
                tag_item = QTreeWidgetItem(tag_tree)
                tag_item.setText(0, str(tag))
                tag_item.setText(1, f"{int(count):,}")
                tag_item.setData(0, Qt.UserRole, str(tag))
            tag_tree.setCurrentItem(all_item)

        def _selected_material_tag() -> str:
            item = tag_tree.currentItem()
            if item is None:
                return ""
            return str(item.data(0, Qt.UserRole) or "").strip().lower()

        def _row_matches_material_tag(row: Mapping[str, object], selected_tag: str) -> bool:
            if not selected_tag:
                return True
            tags = [tag.strip().lower() for tag in self._archive_asset_catalog_row_values(row, "material_tags")]
            if selected_tag == "untagged evidence":
                return not tags and bool(self._archive_asset_catalog_row_values(row, "material_evidence"))
            if selected_tag in tags:
                return True
            evidence_text = " ".join(self._archive_asset_catalog_row_values(row, "material_evidence")).casefold()
            return selected_tag.casefold() in evidence_text

        def _row_search_text(row: Mapping[str, object]) -> str:
            values = [self._archive_asset_catalog_text(row)]
            values.extend(self._archive_asset_catalog_row_values(row, "material_tags"))
            values.extend(self._archive_asset_catalog_row_values(row, "material_evidence"))
            return " ".join(values).casefold()

        def _populate_results() -> None:
            query_tokens = tuple(re.findall(r"[a-z0-9]+", search_edit.text().strip().casefold()))
            selected_tag = _selected_material_tag()
            result_tree.setUpdatesEnabled(False)
            result_tree.clear()
            filtered_rows.clear()
            shown = 0
            hidden = 0
            for row in material_rows:
                if not _row_matches_material_tag(row, selected_tag):
                    continue
                haystack = _row_search_text(row)
                if query_tokens and not all(token in haystack for token in query_tokens):
                    continue
                filtered_rows.append(dict(row))
                display_name = str(row.get("display_name", "") or row.get("internal_name", "") or "Unnamed asset")
                category = str(row.get("category", "") or "Item")
                group = str(row.get("group", "") or "Unclassified")
                tags = self._archive_asset_catalog_row_values(row, "material_tags")
                evidence = self._archive_asset_catalog_row_values(row, "material_evidence")
                pac_files = self._archive_asset_catalog_row_values(row, "pac_files")
                model_stems = self._archive_asset_catalog_row_values(row, "model_stems")
                icon_paths = self._archive_asset_catalog_row_values(row, "icon_paths")
                item = QTreeWidgetItem(result_tree)
                item.setText(0, display_name)
                item.setText(1, ", ".join(tags[:6]) + (" ..." if len(tags) > 6 else ""))
                item.setText(2, f"{len(pac_files) + len(model_stems) + len(icon_paths):,}")
                item.setText(3, ", ".join(evidence[:3]) + (" ..." if len(evidence) > 3 else ""))
                item.setData(0, Qt.UserRole, dict(row))
                item.setToolTip(
                    0,
                    "\n".join(
                        [
                            display_name,
                            f"{category} / {group}",
                            "Materials: " + (", ".join(tags) if tags else "untagged evidence"),
                            "Evidence: " + (", ".join(evidence[:8]) if evidence else "-"),
                        ]
                    ),
                )
                shown += 1
                if shown >= 2500:
                    hidden += 1
                    break
            result_tree.setUpdatesEnabled(True)
            material_label = selected_tag or "all indexed materials"
            result_status.setText(
                f"{shown:,} item/material row(s) shown for {material_label}. "
                "Double-click or use Show Selected Related Set to scope models, sidecars, DDS textures, and item links."
                + (" Refine search to narrow the result." if hidden else "")
            )
            if result_tree.topLevelItemCount() > 0:
                result_tree.setCurrentItem(result_tree.topLevelItem(0))
            else:
                _update_detail()

        def _selected_rows() -> List[Dict[str, object]]:
            rows: List[Dict[str, object]] = []
            for item in result_tree.selectedItems():
                raw = item.data(0, Qt.UserRole)
                if isinstance(raw, Mapping):
                    rows.append(dict(raw))
            if rows:
                return rows
            current = result_tree.currentItem()
            if current is not None:
                raw = current.data(0, Qt.UserRole)
                if isinstance(raw, Mapping):
                    return [dict(raw)]
            return []

        def _add_detail_group(title: str, values: Sequence[str], *, limit: int = 24) -> None:
            if not values:
                return
            group_item = QTreeWidgetItem(detail_tree)
            group_item.setText(0, f"{title} ({len(values):,})")
            for value in values[:limit]:
                child = QTreeWidgetItem(group_item)
                child.setText(0, title.rstrip("s"))
                child.setText(1, str(value))
            if len(values) > limit:
                child = QTreeWidgetItem(group_item)
                child.setText(0, "More")
                child.setText(1, f"{len(values) - limit:,} more hidden here; scoping still uses all recovered links.")
            group_item.setExpanded(True)

        def _update_detail() -> None:
            rows = _selected_rows()
            detail_tree.clear()
            if not rows:
                detail_summary.setText("Select a material row to inspect linked files and evidence.")
                scope_selected_button.setEnabled(False)
                return
            if len(rows) > 1:
                tag_counter: Counter = Counter()
                for row in rows:
                    tag_counter.update(self._archive_asset_catalog_row_values(row, "material_tags"))
                detail_summary.setText(
                    f"{len(rows):,} selected material row(s). "
                    f"Top tags: {', '.join(tag for tag, _count in tag_counter.most_common(8)) or 'untagged evidence'}."
                )
                _add_detail_group(
                    "Selected items",
                    [str(row.get("display_name", "") or row.get("internal_name", "") or "Unnamed asset") for row in rows],
                    limit=40,
                )
                _add_detail_group("Material tags", [tag for tag, _count in tag_counter.most_common(24)], limit=24)
                scope_selected_button.setEnabled(True)
                return
            row = rows[0]
            display_name = str(row.get("display_name", "") or row.get("internal_name", "") or "Unnamed asset")
            category = str(row.get("category", "") or "Item")
            group = str(row.get("group", "") or "Unclassified")
            tags = self._archive_asset_catalog_row_values(row, "material_tags")
            evidence = self._archive_asset_catalog_row_values(row, "material_evidence")
            pac_files = self._archive_asset_catalog_row_values(row, "pac_files")
            model_stems = self._archive_asset_catalog_row_values(row, "model_stems")
            icon_paths = self._archive_asset_catalog_row_values(row, "icon_paths")
            detail_summary.setText(
                f"{display_name}\n{category} / {group}\n"
                f"Materials: {', '.join(tags) if tags else 'untagged evidence'}"
            )
            _add_detail_group("Material tags", tags, limit=16)
            _add_detail_group("Material evidence", evidence, limit=32)
            _add_detail_group("Models", pac_files, limit=32)
            _add_detail_group("Model stems", model_stems, limit=16)
            _add_detail_group("Icons", icon_paths, limit=16)
            if detail_tree.topLevelItemCount() == 0:
                empty = QTreeWidgetItem(detail_tree)
                empty.setText(0, "No detail")
                empty.setText(1, "This row matched only through searchable text.")
            scope_selected_button.setEnabled(bool(pac_files or model_stems or icon_paths))

        def _scope_material_rows(rows: Sequence[Mapping[str, object]], *, scope_label: str) -> None:
            capped_rows = [dict(row) for row in rows[:250] if isinstance(row, Mapping)]
            scoped_entries: List[ArchiveEntry] = []
            seen: set[Tuple[str, str, int]] = set()
            for row in capped_rows:
                row_entries, _primary_count, _related_count = self._resolve_archive_asset_catalog_scope_entries(row, include_related=True)
                for entry in row_entries:
                    key = (entry.path.lower(), str(entry.pamt_path).lower(), int(entry.offset))
                    if key in seen:
                        continue
                    seen.add(key)
                    scoped_entries.append(entry)
                if len(scoped_entries) >= 4000:
                    break
            if not scoped_entries:
                QMessageBox.information(
                    dialog,
                    "Material Finder",
                    "No archive files could be resolved for the selected material row(s).",
                )
                return
            if len(rows) > len(capped_rows):
                scope_label = f"{scope_label} ({len(capped_rows):,} of {len(rows):,} rows)"
            self._activate_tool_widget(self.archive_browser_tab)
            self._apply_archive_direct_scope(
                scoped_entries,
                scope_label=scope_label,
                placeholder_text=f"Material Finder scope active: {scope_label}",
                hint_text=(
                    f"Material Finder scope active: {scope_label}. "
                    "Showing linked models, material sidecars, DDS textures, icons, and companion rows. "
                    "Use Clear Scope to return to normal archive filters."
                ),
                progress_text=f"Material Finder scope: {len(scoped_entries):,} indexed file(s).",
                log_text=(
                    f"Material Finder scoped Archive Browser to: {scope_label} "
                    f"({len(scoped_entries):,} indexed file(s); {len(capped_rows):,} material row(s); no full archive scan)."
                ),
            )
            dialog.accept()

        def _scope_selected() -> None:
            rows = _selected_rows()
            if not rows:
                QMessageBox.information(dialog, "Material Finder", "Select at least one material row first.")
                return
            label = str(rows[0].get("display_name", "") or rows[0].get("internal_name", "") or _selected_material_tag() or "selected materials")
            if len(rows) > 1:
                label = f"{len(rows):,} selected material rows"
            _scope_material_rows(rows, scope_label=f"Material Finder: {label}")

        def _scope_all_matches() -> None:
            if not filtered_rows:
                QMessageBox.information(dialog, "Material Finder", "No matching material rows are currently shown.")
                return
            label = _selected_material_tag() or "all indexed materials"
            _scope_material_rows(filtered_rows, scope_label=f"Material Finder: {label}")

        clear_search_button.clicked.connect(search_edit.clear)
        search_edit.textChanged.connect(_populate_results)
        tag_tree.itemSelectionChanged.connect(_populate_results)
        result_tree.itemSelectionChanged.connect(_update_detail)
        result_tree.itemDoubleClicked.connect(lambda _item, _column: _scope_selected())
        scope_selected_button.clicked.connect(lambda _checked=False: _scope_selected())
        scope_all_button.clicked.connect(lambda _checked=False: _scope_all_matches())
        close_button.clicked.connect(dialog.reject)
        _populate_tags()
        _populate_results()
        dialog.exec()


__all__ = ["ArchiveMaterialFinderMixin"]
