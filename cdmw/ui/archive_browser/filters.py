"""Archive browser filter and category-index helpers."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from cdmw.constants import (
    ARCHIVE_EXTENSION_FILTER,
    ARCHIVE_BROWSER_VIEW_MODE,
)
from cdmw.domain.archives.format import normalize_archive_extension_filter
from cdmw.domain.archives.filters import (
    ArchiveFilterState,
    archive_browser_entry_category,
    archive_filter_text_explicitly_requests_item_name,
    archive_filter_text_needs_item_name_search,
    build_archive_category_entry_index,
    normalize_archive_browser_sort_column,
    normalize_archive_browser_sort_order,
    normalize_archive_structure_filter_value,
)


class ArchiveFilterStateMixin:
    """Archive browser filter-state capture, restore, and lookup decisions."""

    def _canonicalize_archive_extension_filter_control(self) -> None:
        raw_value = self._combo_value(self.archive_extension_filter_combo)
        normalized_value = normalize_archive_extension_filter(raw_value) or "*"
        if normalized_value == str(raw_value or "").strip().lower():
            return
        signals_blocked = self.archive_extension_filter_combo.blockSignals(True)
        try:
            self._set_combo_by_value(self.archive_extension_filter_combo, normalized_value)
        finally:
            self.archive_extension_filter_combo.blockSignals(signals_blocked)

    def _archive_filter_signature_from_values(
        self,
        *,
        filter_text: str = "",
        exclude_filter_text: str = "",
        extension_filter: str = "*",
        package_filter_text: str = "",
        structure_filter: str = "",
        role_filter: str = "all",
        exclude_common_technical_suffixes: bool = False,
        min_size_kb: int = 0,
        previewable_only: bool = False,
        view_mode: str = ARCHIVE_BROWSER_VIEW_MODE,
        sort_column: int = -1,
        sort_order: str = "asc",
    ) -> Tuple[object, ...]:
        return (
            str(filter_text or "").strip(),
            str(exclude_filter_text or "").strip(),
            normalize_archive_extension_filter(extension_filter),
            str(package_filter_text or "").strip(),
            normalize_archive_structure_filter_value(str(structure_filter or "")),
            str(role_filter or "all").strip().lower() or "all",
            bool(exclude_common_technical_suffixes),
            int(min_size_kb or 0),
            bool(previewable_only),
            str(view_mode or ARCHIVE_BROWSER_VIEW_MODE),
            normalize_archive_browser_sort_column(sort_column),
            normalize_archive_browser_sort_order(sort_order),
        )

    def _neutral_archive_filter_signature(self) -> Tuple[object, ...]:
        return self._archive_filter_signature_from_values()

    def _neutral_archive_filter_state(self) -> Dict[str, object]:
        return {
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

    def _current_archive_filter_signature(self) -> Tuple[object, ...]:
        return self._archive_filter_signature_from_values(
            filter_text=self.archive_filter_edit.text().strip(),
            exclude_filter_text=self.archive_exclude_filter_edit.text().strip(),
            extension_filter=self._combo_value(self.archive_extension_filter_combo),
            package_filter_text=self.archive_package_filter_edit.text().strip(),
            structure_filter=self._current_archive_structure_filter_value(),
            role_filter=self._combo_value(self.archive_role_filter_combo),
            exclude_common_technical_suffixes=self.archive_exclude_common_technical_checkbox.isChecked(),
            min_size_kb=self.archive_min_size_spin.value(),
            previewable_only=self.archive_previewable_only_checkbox.isChecked(),
            view_mode=self._archive_browser_view_mode(),
            sort_column=self.archive_tree_sort_column,
            sort_order=self.archive_tree_sort_order,
        )

    def _current_archive_browser_render_signature(self) -> Tuple[object, ...]:
        result_filter_signature = tuple(self.archive_result_filter_signature or self._current_archive_filter_signature())
        return (
            *result_filter_signature,
            len(self.archive_entries),
            len(self.archive_filtered_entries),
            int(self.archive_filtered_dds_count),
            bool(self.archive_tree_index_ready),
            bool(self._archive_category_index_ready()) if self.archive_filtered_entries else False,
            bool(self.archive_active_asset_catalog_scope),
            bool(self.archive_initial_sort_apply_pending),
        )

    def _capture_archive_filter_state(self) -> Dict[str, object]:
        return {
            "filter_text": self.archive_filter_edit.text().strip(),
            "exclude_filter_text": self.archive_exclude_filter_edit.text().strip(),
            "extension_filter": self._combo_value(self.archive_extension_filter_combo),
            "package_filter_text": self.archive_package_filter_edit.text().strip(),
            "structure_filter": self._current_archive_structure_filter_value(),
            "role_filter": self._combo_value(self.archive_role_filter_combo),
            "exclude_common_technical_suffixes": bool(self.archive_exclude_common_technical_checkbox.isChecked()),
            "min_size_kb": int(self.archive_min_size_spin.value()),
            "previewable_only": bool(self.archive_previewable_only_checkbox.isChecked()),
            "view_mode": self._archive_browser_view_mode(),
            "sort_column": int(self.archive_tree_sort_column),
            "sort_order": self.archive_tree_sort_order,
        }

    def _archive_filter_state_signature(self, state: Mapping[str, object]) -> Tuple[object, ...]:
        try:
            sort_column = int(state.get("sort_column", -1))
        except (TypeError, ValueError):
            sort_column = -1
        return self._archive_filter_signature_from_values(
            filter_text=str(state.get("filter_text", "") or ""),
            exclude_filter_text=str(state.get("exclude_filter_text", "") or ""),
            extension_filter=str(state.get("extension_filter", "*") or "*"),
            package_filter_text=str(state.get("package_filter_text", "") or ""),
            structure_filter=str(state.get("structure_filter", "") or ""),
            role_filter=str(state.get("role_filter", "all") or "all"),
            exclude_common_technical_suffixes=bool(state.get("exclude_common_technical_suffixes", False)),
            min_size_kb=int(state.get("min_size_kb", 0) or 0),
            previewable_only=bool(state.get("previewable_only", False)),
            view_mode=str(state.get("view_mode", ARCHIVE_BROWSER_VIEW_MODE) or ARCHIVE_BROWSER_VIEW_MODE),
            sort_column=sort_column,
            sort_order=str(state.get("sort_order", "asc") or "asc"),
        )

    def _apply_archive_filter_state(self, state: Mapping[str, object]) -> None:
        widgets = (
            self.archive_filter_edit,
            self.archive_exclude_filter_edit,
            self.archive_extension_filter_combo,
            self.archive_package_filter_edit,
            self.archive_role_filter_combo,
            self.archive_exclude_common_technical_checkbox,
            self.archive_min_size_spin,
            self.archive_previewable_only_checkbox,
            self.archive_browser_view_mode_combo,
        )
        previous_blocks = [widget.blockSignals(True) for widget in widgets]
        try:
            self.archive_filter_edit.setText(str(state.get("filter_text", "") or ""))
            self.archive_exclude_filter_edit.setText(str(state.get("exclude_filter_text", "") or ""))
            self._rebuild_archive_extension_filter_choices(str(state.get("extension_filter", "*") or "*"))
            self._set_combo_by_value(self.archive_extension_filter_combo, str(state.get("extension_filter", "*") or "*"))
            self.archive_package_filter_edit.setText(str(state.get("package_filter_text", "") or ""))
            self.archive_structure_filter_pending_value = str(state.get("structure_filter", "") or "")
            self._rebuild_archive_structure_filter_controls(self.archive_structure_filter_pending_value)
            self._set_combo_by_value(self.archive_role_filter_combo, str(state.get("role_filter", "all") or "all"))
            self.archive_exclude_common_technical_checkbox.setChecked(bool(state.get("exclude_common_technical_suffixes", False)))
            self.archive_min_size_spin.setValue(int(state.get("min_size_kb", 0) or 0))
            self.archive_previewable_only_checkbox.setChecked(bool(state.get("previewable_only", False)))
            self._set_combo_by_value(self.archive_browser_view_mode_combo, str(state.get("view_mode", ARCHIVE_BROWSER_VIEW_MODE) or ARCHIVE_BROWSER_VIEW_MODE))
            self.archive_tree_sort_column = normalize_archive_browser_sort_column(state.get("sort_column", -1))
            self.archive_tree_sort_order = normalize_archive_browser_sort_order(state.get("sort_order", "asc"))
            self._update_archive_tree_sort_indicator()
        finally:
            for widget, blocked in zip(widgets, previous_blocks):
                widget.blockSignals(blocked)

    def _archive_saved_filter_needs_item_search(self, state: Mapping[str, object]) -> bool:
        return archive_filter_text_needs_item_name_search(state.get("filter_text", ""))

    def _archive_filter_state_explicitly_requires_item_search(self, state: Mapping[str, object]) -> bool:
        return archive_filter_text_explicitly_requests_item_name(state.get("filter_text", ""))

    def _archive_extension_counts(self) -> Counter:
        entries_by_extension = getattr(self, "archive_entries_by_extension", {})
        if isinstance(entries_by_extension, dict) and entries_by_extension:
            return Counter(
                {
                    str(extension): len(items)
                    for extension, items in entries_by_extension.items()
                    if extension and isinstance(items, list)
                }
            )
        cached_counts = getattr(self, "archive_extension_counts", Counter())
        if isinstance(cached_counts, Counter) and cached_counts:
            return Counter(cached_counts)
        entries = getattr(self, "archive_entries", [])
        return Counter(entry.extension for entry in entries if getattr(entry, "extension", ""))

    @staticmethod
    def _archive_extension_group_label(extension: str) -> str:
        ext = str(extension or "").strip().lower()
        if ext in {".pac", ".pam", ".pamlod", ".meshinfo", ".hkx", ".hkt", ".pab", ".pae", ".pat", ".obj", ".fbx", ".gltf", ".glb"}:
            return "Model / Mesh / Physics"
        if ext in {".dds", ".png", ".tga", ".jpg", ".jpeg", ".texture"}:
            return "Texture / Image"
        if ext in {
            ".pac_xml",
            ".app_xml",
            ".prefab",
            ".pappt",
            ".pamhc",
            ".prefabdata_xml",
            ".paa_metabin",
            ".motionblending",
            ".seqmt",
            ".pabgb",
            ".pabgh",
            ".pami",
            ".xml",
            ".json",
            ".material",
            ".levelinfo",
            ".binarygimmick",
        }:
            return "Material / Metadata"
        if ext in {".wem", ".bnk", ".mp4", ".wav", ".ogg", ".mp3"}:
            return "Audio / Video"
        if ext in {".html", ".thtml", ".css", ".txt", ".paloc", ".ui", ".uianiminit"}:
            return "UI / Text"
        if ext in {".paseqc", ".paseqcpath", ".pastage", ".palevel", ".paa_metabin", ".paem", ".paa", ".ani", ".pai"}:
            return "Animation / Scene"
        return "Other"

    def _open_archive_extension_picker(self) -> None:
        extension_counts = self._archive_extension_counts()
        if not extension_counts:
            extension_counts = Counter({".dds": 0})
        current_value = normalize_archive_extension_filter(
            self._combo_value(self.archive_extension_filter_combo) or ARCHIVE_EXTENSION_FILTER
        )

        dialog = QDialog(self)
        dialog.setWindowTitle("Select Archive Extension")
        dialog.resize(560, 660)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        intro = QLabel("Pick a loaded extension group, or keep typing a rare extension in the search box.")
        intro.setObjectName("HintLabel")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        search_edit = QLineEdit()
        search_edit.setPlaceholderText("Filter extensions or groups, e.g. hkx, texture, metadata")
        layout.addWidget(search_edit)

        extension_tree = QTreeWidget()
        extension_tree.setColumnCount(3)
        extension_tree.setHeaderLabels(["Extension", "Entries", "Group"])
        extension_tree.setRootIsDecorated(True)
        extension_tree.setAlternatingRowColors(True)
        extension_tree.setUniformRowHeights(True)
        extension_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        extension_tree.header().setStretchLastSection(True)
        extension_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        extension_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        extension_tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        count_brush = QBrush(QColor("#fbbf24"))
        group_brush = QBrush(QColor("#93c5fd"))
        all_count = sum(int(count) for count in extension_counts.values())
        all_item = QTreeWidgetItem(extension_tree, ["All files", f"{all_count:,}", "All"])
        all_item.setData(0, Qt.UserRole, "*")
        all_item.setForeground(1, count_brush)

        grouped: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
        for extension, count in sorted(extension_counts.items(), key=lambda item: (-item[1], item[0])):
            grouped[self._archive_extension_group_label(extension)].append((extension, int(count)))

        selected_item: Optional[QTreeWidgetItem] = None
        if current_value in {"*", "all", ".*"}:
            selected_item = all_item
        group_order = (
            "Model / Mesh / Physics",
            "Texture / Image",
            "Material / Metadata",
            "Animation / Scene",
            "Audio / Video",
            "UI / Text",
            "Other",
        )
        for group_name in group_order:
            values = grouped.get(group_name, [])
            if not values:
                continue
            group_total = sum(count for _extension, count in values)
            group_item = QTreeWidgetItem(extension_tree, [group_name, f"{group_total:,}", group_name])
            group_item.setData(0, Qt.UserRole, "")
            group_item.setForeground(0, group_brush)
            group_item.setForeground(1, count_brush)
            group_item.setExpanded(True)
            for extension, count in values:
                child = QTreeWidgetItem(group_item, [extension, f"{count:,}", group_name])
                child.setData(0, Qt.UserRole, extension)
                child.setForeground(0, QBrush(self._archive_role_color(group_name)))
                child.setForeground(1, count_brush)
                if extension == current_value:
                    selected_item = child
        if selected_item is not None:
            extension_tree.setCurrentItem(selected_item)
            extension_tree.scrollToItem(selected_item)
        layout.addWidget(extension_tree, stretch=1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        clear_button = QPushButton("All Files")
        select_button = QPushButton("Select")
        cancel_button = QPushButton("Cancel")
        select_button.setDefault(True)
        actions.addWidget(clear_button)
        actions.addStretch(1)
        actions.addWidget(select_button)
        actions.addWidget(cancel_button)
        layout.addLayout(actions)

        def _apply_filter(text: str) -> None:
            needle = text.strip().casefold()
            for top_index in range(extension_tree.topLevelItemCount()):
                top_item = extension_tree.topLevelItem(top_index)
                top_match = needle in top_item.text(0).casefold() or needle in top_item.text(2).casefold()
                any_child_visible = False
                for child_index in range(top_item.childCount()):
                    child = top_item.child(child_index)
                    child_match = (
                        not needle
                        or top_match
                        or needle in child.text(0).casefold()
                        or needle in child.text(2).casefold()
                    )
                    child.setHidden(not child_match)
                    any_child_visible = any_child_visible or child_match
                top_item.setHidden(bool(needle) and not top_match and not any_child_visible)

        def _select_value(value: str) -> None:
            normalized = normalize_archive_extension_filter(value or "*")
            self._set_combo_by_value(self.archive_extension_filter_combo, normalized)
            self._mark_archive_filters_dirty()
            self.schedule_settings_save()
            dialog.accept()

        def _select_current() -> None:
            item = extension_tree.currentItem()
            if item is None:
                return
            value = item.data(0, Qt.UserRole)
            if not isinstance(value, str) or not value:
                item.setExpanded(not item.isExpanded())
                return
            _select_value(value)

        search_edit.textChanged.connect(_apply_filter)
        clear_button.clicked.connect(lambda _checked=False: _select_value("*"))
        select_button.clicked.connect(lambda _checked=False: _select_current())
        cancel_button.clicked.connect(dialog.reject)
        extension_tree.itemDoubleClicked.connect(lambda _item, _column: _select_current())
        dialog.exec()

    def _rebuild_archive_extension_filter_choices(self, selected_value: Optional[str] = None) -> None:
        selected_raw = (
            selected_value
            if selected_value is not None
            else (self._combo_value(self.archive_extension_filter_combo) or ARCHIVE_EXTENSION_FILTER)
        )
        preferred_value = normalize_archive_extension_filter(selected_raw)
        extension_counts = self._archive_extension_counts()

        self.archive_extension_filter_combo.blockSignals(True)
        self.archive_extension_filter_combo.clear()
        self._add_combo_choice(self.archive_extension_filter_combo, "All files", "*")

        if extension_counts:
            for extension, count in sorted(extension_counts.items(), key=lambda item: (-item[1], item[0])):
                self._add_combo_choice(
                    self.archive_extension_filter_combo,
                    f"{extension} ({count:,})",
                    extension,
                )
        else:
            self._add_combo_choice(self.archive_extension_filter_combo, "DDS only", ".dds")

        if preferred_value and preferred_value not in {"*", "all", ".*"}:
            if self.archive_extension_filter_combo.findData(preferred_value) < 0:
                self._add_combo_choice(
                    self.archive_extension_filter_combo,
                    f"{preferred_value} (saved)",
                    preferred_value,
                )

        target_value = preferred_value or "*"
        if self.archive_extension_filter_combo.findData(target_value) < 0:
            target_value = "*"
        self._set_combo_by_value(self.archive_extension_filter_combo, target_value)
        self.archive_extension_filter_combo.blockSignals(False)

    def _archive_filter_state_needs_path_lookup(self, state: Mapping[str, object]) -> bool:
        if not self._archive_filter_state_explicitly_requires_item_search(state):
            return False
        extension_filter = normalize_archive_extension_filter(str(state.get("extension_filter", "*") or "*"))
        return extension_filter != ".pac"

    def _archive_filter_state_needs_basic_lookup(self, state: Mapping[str, object]) -> bool:
        # Extension, role, package, size, and ordinary sort can scan the loaded row list.
        # Path lookup is only required for item-name related-file expansion.
        return self._archive_filter_state_needs_path_lookup(state)

    def _current_archive_filter_needs_path_lookup(self) -> bool:
        return self._archive_filter_state_needs_path_lookup(self._capture_archive_filter_state())

    def _current_archive_filter_needs_basic_lookup(self) -> bool:
        return self._archive_filter_state_needs_basic_lookup(self._capture_archive_filter_state())

    def _archive_basic_index_missing_for_lookup(self) -> bool:
        return bool(
            self.archive_entries
            and not (
                self.archive_entries_by_normalized_path
                and self.archive_entries_by_basename
                and self.archive_entries_by_extension
                and self.archive_entries_by_role
            )
            and str(getattr(self, "archive_basic_index_state", "idle") or "idle") in {"idle", "warming"}
        )

    def _archive_enhanced_index_missing_for_search(self) -> bool:
        return bool(
            self.archive_entries
            and self.archive_name_search_index is None
            and str(getattr(self, "archive_enhanced_index_state", "idle") or "idle") in {"idle", "warming"}
        )

    def _archive_filter_waits_for_item_search(self) -> bool:
        state = self._capture_archive_filter_state()
        return self._archive_filter_state_waits_for_item_search(state)

    def _archive_filter_state_waits_for_item_search(self, state: Mapping[str, object]) -> bool:
        return (
            self._archive_enhanced_index_missing_for_search()
            and self._archive_saved_filter_needs_item_search(state)
            and self._archive_filter_state_explicitly_requires_item_search(state)
            and not self._archive_filter_can_use_loaded_item_aliases(state)
        )

    def _archive_filter_can_use_loaded_item_aliases(self, state: Mapping[str, object]) -> bool:
        if not self.archive_item_search_aliases:
            return False
        candidates: List[int] = []
        normalized_extension = normalize_archive_extension_filter(str(state.get("extension_filter", "") or ""))
        if normalized_extension and normalized_extension not in {"*", "all", ".*"}:
            if self.archive_entries_by_extension:
                candidates.append(len(self.archive_entries_by_extension.get(normalized_extension, ())))
            elif self.archive_extension_counts:
                candidates.append(int(self.archive_extension_counts.get(normalized_extension, 0) or 0))
        role_filter = str(state.get("role_filter", "") or "all").strip().lower()
        if role_filter and role_filter != "all" and self.archive_entries_by_role:
            candidates.append(len(self.archive_entries_by_role.get(role_filter, ())))
        candidate_count = min(candidates) if candidates else len(self.archive_entries)
        return 0 < int(candidate_count or 0) <= 250_000

    def _archive_browser_view_mode(self) -> str:
        mode = str(self._combo_value(self.archive_browser_view_mode_combo) or ARCHIVE_BROWSER_VIEW_MODE)
        return mode if mode in {"folders", "categories", "categories_folders", "flat"} else ARCHIVE_BROWSER_VIEW_MODE

    def _archive_tree_view_enabled(self) -> bool:
        return self._archive_browser_view_mode() != "flat"

    def _archive_folder_tree_enabled(self) -> bool:
        return self._archive_browser_view_mode() in {"folders", "categories_folders"}

    def _archive_category_view_enabled(self) -> bool:
        return self._archive_browser_view_mode() in {"categories", "categories_folders"}

    def _archive_category_index_ready(self) -> bool:
        return sum(len(indexes) for indexes in self.archive_tree_category_entry_indexes.values()) == len(self.archive_filtered_entries)

    def _archive_entry_category(self, entry: object) -> str:
        return archive_browser_entry_category(entry)

    def _archive_category_sort_key(self, category: str) -> Tuple[int, str]:
        order = {
            "Texture": 0,
            "Mesh": 1,
            "Material Sidecar": 2,
            "Skeleton/Rig": 3,
            "Physics": 4,
            "Animation": 5,
            "Audio": 6,
            "Video": 7,
            "Text/Metadata": 8,
            "Other": 9,
        }
        return order.get(category, 99), category

    def _archive_category_entry_indexes(self) -> Dict[str, List[int]]:
        return self.archive_tree_category_entry_indexes


__all__ = [
    "ArchiveFilterStateMixin",
    "ArchiveFilterState",
    "archive_filter_text_explicitly_requests_item_name",
    "archive_filter_text_needs_item_name_search",
    "archive_browser_entry_category",
    "build_archive_category_entry_index",
]
