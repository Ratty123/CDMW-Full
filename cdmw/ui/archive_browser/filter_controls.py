"""Archive browser filter widgets, buttons, and structure controls."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QComboBox, QLabel

from cdmw.constants import (
    ARCHIVE_BROWSER_VIEW_MODE,
    ARCHIVE_EXCLUDE_COMMON_TECHNICAL_SUFFIXES,
    ARCHIVE_EXTENSION_FILTER,
    ARCHIVE_MIN_SIZE_KB,
    ARCHIVE_PREVIEWABLE_ONLY,
    ARCHIVE_ROLE_FILTER,
    ARCHIVE_STRUCTURE_FILTER,
)
from cdmw.services.archive_query_service import build_archive_structure_children_map
from cdmw.domain.archives.filters import normalize_archive_structure_filter_value


class ArchiveFilterControlsMixin:
    """Archive filter widget state, structure picker controls, and clear actions."""

    def _mark_archive_filters_dirty(self) -> None:
        self.archive_filters_dirty = True
        self._mark_archive_browser_render_stale()
        if self.archive_filter_worker is not None:
            try:
                self.archive_filter_worker.stop()
            except Exception:
                pass
        self._update_archive_filter_button_state()

    def _capture_archive_controls_scroll_for_filter(self) -> None:
        try:
            scrollbar = self.archive_controls_scroll.verticalScrollBar()
            self.archive_controls_scroll_filter_anchor = int(scrollbar.value())
        except Exception:
            self.archive_controls_scroll_filter_anchor = None

    def _restore_archive_controls_scroll_after_filter(self) -> None:
        value = getattr(self, "archive_controls_scroll_filter_anchor", None)
        if value is None:
            return

        def _restore() -> None:
            try:
                scrollbar = self.archive_controls_scroll.verticalScrollBar()
                scrollbar.setValue(max(0, min(int(value), int(scrollbar.maximum()))))
            except Exception:
                pass

        _restore()
        QTimer.singleShot(0, _restore)
        QTimer.singleShot(80, _restore)

    def _clear_archive_structure_filter_widgets(self) -> None:
        while self.archive_structure_filter_layout.count():
            item = self.archive_structure_filter_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _current_archive_structure_filter_value(self) -> str:
        if not self.archive_structure_filter_combos:
            return normalize_archive_structure_filter_value(self.archive_structure_filter_pending_value)
        selected_value = ""
        for combo in self.archive_structure_filter_combos:
            value = normalize_archive_structure_filter_value(self._combo_value(combo))
            if not value or value == selected_value:
                break
            selected_value = value
        return selected_value

    def _set_archive_structure_filter_enabled(self, enabled: bool) -> None:
        for combo in self.archive_structure_filter_combos:
            combo.setEnabled(enabled)

    def _format_archive_structure_combo_label(self, value: str, count: int) -> str:
        leaf = value.rsplit("/", 1)[-1]
        return f"{leaf}/ ({count:,})"

    def _rebuild_archive_structure_filter_controls(
        self,
        selected_value: Optional[str] = None,
        *,
        rebuild_children: bool = False,
        defer_missing_children: bool = False,
    ) -> None:
        preferred_value = normalize_archive_structure_filter_value(
            selected_value
            if selected_value is not None
            else (self._current_archive_structure_filter_value() or self.archive_structure_filter_pending_value)
        )
        if rebuild_children or (not self.archive_structure_filter_children and self.archive_entries):
            if defer_missing_children:
                if len(self.archive_entries) >= 100_000:
                    self.append_archive_log(
                        "Archive Browser activation timing | cause=structure_filter | start=deferred",
                        verbose=True,
                    )
                QTimer.singleShot(0, self._start_archive_structure_filter_worker)
            else:
                if len(self.archive_entries) >= 500_000:
                    self.append_archive_log(
                        "WARNING: Archive structure filter map would build on the UI thread for a large archive; deferring to background worker.",
                        verbose=True,
                    )
                    QTimer.singleShot(0, self._start_archive_structure_filter_worker)
                else:
                    self.archive_structure_filter_children = build_archive_structure_children_map(self.archive_entries)
                    self.archive_structure_filter_state = "ready"
        self.rebuilding_archive_structure_filters = True
        self._clear_archive_structure_filter_widgets()
        self.archive_structure_filter_combos = []

        if not self.archive_structure_filter_children:
            if self.archive_entries:
                detail = (
                    "Folder filters warming..."
                    if self.archive_structure_filter_state == "warming"
                    else "Folder filters will load after the browser opens."
                )
            else:
                detail = "Scan archives to load folder filters."
            empty_label = QLabel(detail)
            empty_label.setObjectName("HintLabel")
            self.archive_structure_filter_layout.addWidget(empty_label)
            self.archive_structure_filter_layout.addStretch(1)
            self.archive_structure_filter_pending_value = preferred_value
            self.rebuilding_archive_structure_filters = False
            return

        segments = preferred_value.split("/") if preferred_value else []
        parent = ""
        level = 0
        while True:
            child_options = self.archive_structure_filter_children.get(parent, [])
            if not child_options:
                break

            combo = QComboBox()
            combo.setMaxVisibleItems(30)
            combo.setMinimumWidth(170)
            if parent == "":
                self._add_combo_choice(combo, "All packages", "")
            else:
                self._add_combo_choice(combo, f"All in {parent.rsplit('/', 1)[-1]}/", parent)
            for child_value, count in child_options:
                self._add_combo_choice(combo, self._format_archive_structure_combo_label(child_value, count), child_value)

            selected_child_value = ""
            if len(segments) > level:
                candidate = "/".join(segments[: level + 1])
                if combo.findData(candidate) >= 0:
                    selected_child_value = candidate
            self._set_combo_by_value(combo, selected_child_value if selected_child_value else (parent if parent else ""))
            combo.currentIndexChanged.connect(
                lambda _index, level=level: self._handle_archive_structure_combo_changed(level)
            )
            combo.setEnabled(self.worker_thread is None)
            self.archive_structure_filter_layout.addWidget(combo)
            self.archive_structure_filter_combos.append(combo)

            if not selected_child_value:
                break
            parent = selected_child_value
            level += 1

        self.archive_structure_filter_layout.addStretch(1)
        self.archive_structure_filter_pending_value = self._current_archive_structure_filter_value() or preferred_value
        self.rebuilding_archive_structure_filters = False

    def _handle_archive_structure_combo_changed(self, _level: int) -> None:
        if self.rebuilding_archive_structure_filters:
            return
        self.archive_structure_filter_pending_value = self._current_archive_structure_filter_value()
        self._rebuild_archive_structure_filter_controls(self.archive_structure_filter_pending_value)
        self._save_settings()
        self._mark_archive_filters_dirty()

    def _update_archive_filter_button_state(self) -> None:
        button_label = "Apply Filters*" if self.archive_filters_dirty else "Apply Filters"
        search_button_label = "Search*" if self.archive_filters_dirty else "Search"
        self.archive_filter_apply_button.setText(button_label)
        self.archive_path_search_button.setText(search_button_label)
        can_apply = self.worker_thread is None and self.archive_filters_dirty
        self.archive_filter_apply_button.setEnabled(can_apply)
        self.archive_path_search_button.setEnabled(self.worker_thread is None)
        self.archive_filter_clear_button.setEnabled(self.worker_thread is None)
        self.archive_asset_catalog_button.setEnabled(self.worker_thread is None and bool(self.archive_item_asset_catalog))
        self.archive_material_finder_button.setEnabled(self.worker_thread is None and bool(self._archive_material_catalog_rows()))
        self.archive_clear_asset_scope_button.setVisible(bool(self.archive_active_asset_catalog_scope))
        self.archive_clear_asset_scope_button.setEnabled(self.worker_thread is None and bool(self.archive_active_asset_catalog_scope))
        if hasattr(self, "archive_scope_banner_label"):
            scope_text = str(self.archive_active_asset_catalog_scope or "").strip()
            if scope_text:
                self.archive_scope_banner_label.setText(
                    f"Scope active: {scope_text}. Clear Scope returns to normal archive filtering."
                )
                self.archive_scope_banner_label.setVisible(True)
            else:
                self.archive_scope_banner_label.clear()
                self.archive_scope_banner_label.setVisible(False)

    def _clear_archive_filters(self) -> None:
        self.archive_active_asset_catalog_scope = ""
        self.archive_clear_asset_scope_button.setVisible(False)
        if hasattr(self, "archive_scope_banner_label"):
            self.archive_scope_banner_label.clear()
            self.archive_scope_banner_label.setVisible(False)
        self.archive_filter_edit.setPlaceholderText("Include path/item-name filter or glob, e.g. Vow of the Dead King or */texture/*")
        self.archive_filter_edit.clear()
        self.archive_exclude_filter_edit.clear()
        self._set_combo_by_value(self.archive_extension_filter_combo, ARCHIVE_EXTENSION_FILTER)
        self.archive_package_filter_edit.clear()
        self.archive_structure_filter_pending_value = ARCHIVE_STRUCTURE_FILTER
        self._rebuild_archive_structure_filter_controls(ARCHIVE_STRUCTURE_FILTER)
        self._set_combo_by_value(self.archive_role_filter_combo, ARCHIVE_ROLE_FILTER)
        self.archive_exclude_common_technical_checkbox.setChecked(ARCHIVE_EXCLUDE_COMMON_TECHNICAL_SUFFIXES)
        self.archive_min_size_spin.setValue(ARCHIVE_MIN_SIZE_KB)
        self.archive_previewable_only_checkbox.setChecked(ARCHIVE_PREVIEWABLE_ONLY)
        self._set_combo_by_value(self.archive_browser_view_mode_combo, ARCHIVE_BROWSER_VIEW_MODE)
        self.archive_package_filter_hint_label.setText("Exclude accepts semicolon-separated substrings or globs.")
        self._save_settings()
        self._apply_archive_filter()

    def _clear_archive_asset_catalog_scope(self) -> None:
        if not self.archive_active_asset_catalog_scope:
            return
        self.archive_active_asset_catalog_scope = ""
        self.archive_clear_asset_scope_button.setVisible(False)
        if hasattr(self, "archive_scope_banner_label"):
            self.archive_scope_banner_label.clear()
            self.archive_scope_banner_label.setVisible(False)
        self.archive_filter_edit.setPlaceholderText("Include path/item-name filter or glob, e.g. Vow of the Dead King or */texture/*")
        self.archive_filter_edit.clear()
        self.archive_package_filter_hint_label.setText("Exclude accepts semicolon-separated substrings or globs.")
        self._apply_archive_filter()
