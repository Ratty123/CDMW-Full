"""Result-view state and query handling for Model Library."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLineEdit, QTreeWidgetItem


class ModelLibraryResultsViewMixin:
    """Coordinate active results view, debounced filters, and sort state."""

    def _handle_results_current_item_changed(self, _current: Optional[QTreeWidgetItem], _previous: Optional[QTreeWidgetItem]) -> None:
        cancel_icon_output = getattr(self, "_cancel_stale_icon_output", None)
        if callable(cancel_icon_output):
            cancel_icon_output()
        self._update_selection_state()
        if self._populating_results:
            return
        self._schedule_auto_inline_preview()

    def _handle_result_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column == 0:
            self._sync_checked_payload_cache_for_item(item)
        self._update_selection_state()

    def _handle_auto_preview_toggled(self, checked: bool) -> None:
        self.settings.setValue("model_library/auto_preview", bool(checked))
        if checked:
            self._schedule_auto_inline_preview()

    def _handle_hide_downloaded_toggled(self, checked: bool) -> None:
        self.settings.setValue("model_library/hide_downloaded", bool(checked))
        self._update_filters_button()
        if self._active_results_view == "mirror":
            self._populate_results(self.mirror_results)
            hidden = int(getattr(self, "_last_hidden_downloaded_count", 0) or 0)
            if checked and hidden and self.results_tree.topLevelItemCount() == 0:
                self._set_status(
                    f"Hide downloaded is on. All {hidden:,} cached mirror result(s) are already downloaded, so the table is empty."
                )
            else:
                suffix = f" Hidden downloaded: {hidden:,}." if checked else ""
                self._set_status(f"Showing Mirror Catalogue with {self.results_tree.topLevelItemCount():,} visible result(s).{suffix}")

    def _handle_results_query_changed(self, text: str) -> None:
        if self._updating_results_query:
            return
        # Typing records the query but never searches. Re-filtering the local
        # table on every keystroke made a long query unusable; the search runs
        # on Enter or the Search button, through _apply_active_results_query,
        # which is what the mirror view already did.
        if self._active_results_view == "local":
            self.settings.setValue("model_library/local_search_query", str(text))
            return
        self.settings.setValue("model_library/search_query", str(text))

    def _handle_results_filter_field_changed(self) -> None:
        key = "model_library/local_search_field" if self._active_results_view == "local" else "model_library/search_field"
        self.settings.setValue(key, str(self.results_filter_field_combo.currentData() or "all"))
        if self._active_results_view == "local":
            self._schedule_results_filter()

    def _handle_local_texture_filter_changed(self) -> None:
        if not hasattr(self, "local_texture_filter_combo"):
            return
        self.settings.setValue("model_library/local_texture_filter", str(self.local_texture_filter_combo.currentData() or "all"))
        self._update_filters_button()
        if self._active_results_view == "local":
            self._schedule_results_filter()

    def _handle_column_filter_changed(self, _editor: QLineEdit) -> None:
        if self._updating_column_filters:
            return
        self._save_column_filters_for_active_view()
        self._update_filters_button()
        self._schedule_results_filter()

    def _schedule_results_filter(self) -> None:
        self._results_filter_timer.start()

    def _flush_debounced_results_filter(self) -> None:
        if self._active_results_view == "local":
            self._populate_results(self.local_models)
        else:
            self._populate_results(self.mirror_results)

    def _set_results_query_text(self, text: str) -> None:
        self._updating_results_query = True
        try:
            self.search_edit.setText(str(text or ""))
            # Programmatic text is an applied query: it is either the stored
            # query of the view being switched to, or a clear.
            self._applied_results_query = str(text or "").strip()
        finally:
            self._updating_results_query = False

    def applied_results_query(self) -> str:
        """The query rows are filtered by, which is not what is being typed.

        Only Enter, Search, Clear, and a view switch move the typed draft into
        this value. Reading the edit box directly meant any unrelated refresh —
        a sort, a texture filter, a Hide downloaded toggle — silently applied a
        query the reader had not submitted.
        """
        applied = getattr(self, "_applied_results_query", None)
        if applied is None:
            return str(self.search_edit.text() if hasattr(self, "search_edit") else "").strip()
        return str(applied).strip()

    def _set_results_filter_field(self, field: str) -> None:
        if not hasattr(self, "results_filter_field_combo"):
            return
        index = self.results_filter_field_combo.findData(str(field or "all"))
        self.results_filter_field_combo.setCurrentIndex(index if index >= 0 else 0)

    def _set_local_texture_filter(self, value: str) -> None:
        if not hasattr(self, "local_texture_filter_combo"):
            return
        index = self.local_texture_filter_combo.findData(str(value or "all"))
        self.local_texture_filter_combo.setCurrentIndex(index if index >= 0 else 0)

    def _apply_active_results_query(self) -> None:
        self._applied_results_query = self.search_edit.text().strip()
        if self._active_results_view == "local":
            self.settings.setValue("model_library/local_search_query", self.search_edit.text().strip())
            self._populate_results(self.local_models)
            self._set_status(
                f"Showing Local Library: {self._pending_results_visible_count:,}/{len(self.local_models):,} matching model file(s)."
            )
            return
        self.search_mirror()

    def _clear_active_results_query(self) -> None:
        self._set_results_query_text("")
        if self._active_results_view == "local":
            self.settings.setValue("model_library/local_search_query", "")
            self._populate_results(self.local_models)
            return
        self.settings.setValue("model_library/search_query", "")
        self.search_mirror(query_override="")

    def _handle_results_header_clicked(self, column: int) -> None:
        column = max(0, min(int(column), self.results_tree.columnCount() - 1))
        if column == self._result_sort_column:
            self._result_sort_order = (
                Qt.SortOrder.DescendingOrder
                if self._result_sort_order == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
        else:
            self._result_sort_column = column
            self._result_sort_order = Qt.SortOrder.DescendingOrder if column == 6 else Qt.SortOrder.AscendingOrder
        self.settings.setValue("model_library/result_sort_column", self._result_sort_column)
        self.settings.setValue(
            "model_library/result_sort_order",
            "desc" if self._result_sort_order == Qt.SortOrder.DescendingOrder else "asc",
        )
        self.results_tree.header().setSortIndicatorShown(True)
        self.results_tree.header().setSortIndicator(self._result_sort_column, self._result_sort_order)
        if self._active_results_view == "local":
            self._populate_results(self.local_models)
        else:
            self._populate_results(self.mirror_results)

    def _use_result_source_order(self) -> None:
        self._result_sort_column = -1
        if hasattr(self, "results_tree"):
            self.results_tree.header().setSortIndicatorShown(False)

    def _schedule_auto_inline_preview(self) -> None:
        if not hasattr(self, "auto_preview_checkbox") or not self.auto_preview_checkbox.isChecked():
            return
        if not self.isVisible():
            return
        payload = self._selected_payload()
        if not self._payload_can_preview_here(payload):
            return
        self._auto_preview_timer.start()

    def handle_activated(self) -> None:
        self._auto_preview_timer.stop()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._presentation_paused = True
        self._auto_preview_timer.stop()
        self._results_population_timer.stop()
        super().hideEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        self._presentation_paused = False
        if self._populating_results:
            self._results_population_timer.start()
        super().showEvent(event)

    def _preview_current_model_if_auto_enabled(self) -> None:
        if not self.isVisible():
            return
        if not hasattr(self, "auto_preview_checkbox") or not self.auto_preview_checkbox.isChecked():
            return
        payload = self._selected_payload()
        if not self._payload_can_preview_here(payload):
            return
        self.preview_selected_model_here()

    def _set_active_results_view(self, view: str, *, persist: bool = True) -> None:
        previous_view = getattr(self, "_active_results_view", "mirror")
        if hasattr(self, "search_edit") and not self._updating_results_query:
            if previous_view == "local":
                self.settings.setValue("model_library/local_search_query", self.search_edit.text().strip())
            else:
                self.settings.setValue("model_library/search_query", self.search_edit.text().strip())
        self._active_results_view = "local" if str(view).strip().lower() == "local" else "mirror"
        local_view = self._active_results_view == "local"
        if hasattr(self, "mirror_results_view_button"):
            self.mirror_results_view_button.setChecked(not local_view)
            self.local_results_view_button.setChecked(local_view)
        if hasattr(self, "mirror_group"):
            # The Sources lane and the filter strip show only what the active view uses.
            self.mirror_group.setVisible(not local_view)
            self.local_group.setVisible(local_view)
            self._mirror_filter_fields.setVisible(not local_view)
            self._local_filter_fields.setVisible(local_view)
            self.download_button.setVisible(not local_view)
        if hasattr(self, "search_edit"):
            self.results_filter_field_combo.setVisible(local_view)
            if local_view:
                self.search_edit.setPlaceholderText("Filter local models by name, creator, license, format, path, or source")
                self._set_results_filter_field(str(self.settings.value("model_library/local_search_field", "all") or "all"))
                self._set_local_texture_filter(str(self.settings.value("model_library/local_texture_filter", "all") or "all"))
                self._set_results_query_text(str(self.settings.value("model_library/local_search_query", "") or ""))
            else:
                self.search_edit.setPlaceholderText("Search mirror by name, tag, creator, or UID")
                self._set_results_filter_field("all")
                self._set_results_query_text(str(self.settings.value("model_library/search_query", self.search_edit.text()) or ""))
            self._load_column_filters_for_active_view()
        if persist:
            self.settings.setValue("model_library/results_view", self._active_results_view)
        self._update_filters_button()

    def _set_sources_panel_visible(self, visible: bool, *, persist: bool = True) -> None:
        panel = getattr(self, "_model_library_controls_panel", None)
        if panel is None:
            return
        visible = bool(visible)
        if panel.isHidden() == visible:
            panel.setVisible(visible)
            if visible:
                splitter = self._model_library_splitter
                total = sum(splitter.sizes())
                lane = max(panel.minimumWidth(), min(panel.maximumWidth(), 280))
                splitter.setSizes([lane, max(0, total - lane)])
        if persist:
            self.settings.setValue("model_library/sources_visible", visible)

    def _set_filters_visible(self, visible: bool, *, persist: bool = True) -> None:
        if not hasattr(self, "filters_strip"):
            return
        visible = bool(visible)
        self.filters_strip.setVisible(visible)
        self.column_filter_row.setVisible(visible)
        if persist:
            self.settings.setValue("model_library/filters_visible", visible)

    def _active_filter_count(self) -> int:
        count = len(self._active_column_filters())
        if self._active_results_view == "local":
            if hasattr(self, "local_texture_filter_combo") and str(self.local_texture_filter_combo.currentData() or "all") != "all":
                count += 1
            return count
        if not hasattr(self, "license_filter_edit"):
            return count
        count += sum(
            1
            for edit in (self.license_filter_edit, self.creator_filter_edit, self.creator_exclude_edit)
            if edit.text().strip()
        )
        if str(self.format_filter_combo.currentData() or ""):
            count += 1
        if self.hide_downloaded_checkbox.isChecked():
            count += 1
        return count

    def _update_filters_button(self) -> None:
        """Keep active filters visible on the toggle while the strip is collapsed."""

        if not hasattr(self, "filters_toggle_button"):
            return
        count = self._active_filter_count()
        self.filters_toggle_button.setText(f"Filters ({count})" if count else "Filters")
        if hasattr(self, "clear_filters_button"):
            self.clear_filters_button.setEnabled(bool(count))

    def _clear_all_filters(self) -> None:
        local_view = self._active_results_view == "local"
        self._updating_column_filters = True
        try:
            for edit in self.results_column_filter_edits.values():
                edit.clear()
        finally:
            self._updating_column_filters = False
        self._save_column_filters_for_active_view()
        catalogue_filters_changed = False
        if local_view:
            self.local_texture_filter_combo.blockSignals(True)
            self._set_local_texture_filter("all")
            self.local_texture_filter_combo.blockSignals(False)
            self.settings.setValue("model_library/local_texture_filter", "all")
        else:
            mirror_edits = (self.license_filter_edit, self.creator_filter_edit, self.creator_exclude_edit)
            catalogue_filters_changed = any(edit.text().strip() for edit in mirror_edits) or bool(
                str(self.format_filter_combo.currentData() or "")
            )
            for edit in mirror_edits:
                edit.clear()
            self.format_filter_combo.setCurrentIndex(0)
            self.hide_downloaded_checkbox.blockSignals(True)
            self.hide_downloaded_checkbox.setChecked(False)
            self.hide_downloaded_checkbox.blockSignals(False)
            self.settings.setValue("model_library/hide_downloaded", False)
        self._update_filters_button()
        # Catalogue filters narrow the mirror query itself, so only a new
        # search can widen it again; the other filters re-filter loaded rows.
        if catalogue_filters_changed:
            self.search_mirror()
        else:
            self._populate_results(self.local_models if local_view else self.mirror_results)

    def _load_initial_results_view(self) -> bool:
        self._populate_results([])
        if self._active_results_view == "local":
            if not self.local_roots:
                return False
            self._set_status("Loading local model library...")
            QTimer.singleShot(0, self.scan_local_roots)
            return True
        if not self.catalogue_db_path().is_file():
            return False
        self._set_status("Loading mirror catalogue results...")
        QTimer.singleShot(0, self.search_mirror)
        return True

    def show_mirror_catalogue_view(self) -> None:
        self._set_active_results_view("mirror")
        if self.mirror_results:
            self._use_result_source_order()
            self._populate_results(self.mirror_results)
            hidden = int(getattr(self, "_last_hidden_downloaded_count", 0) or 0)
            suffix = f" {hidden:,} downloaded result(s) hidden." if hidden else ""
            self._set_status(
                f"Showing {self.results_tree.topLevelItemCount():,}/{len(self.mirror_results):,} cached mirror catalogue result(s).{suffix} Use Refresh to search again."
            )
            return
        self.search_mirror()

    def show_local_library_view(self) -> None:
        self._set_active_results_view("local")
        if self.local_models:
            self._populate_results(self.local_models)
            visible_count = self.results_tree.topLevelItemCount()
            suffix = "" if visible_count == len(self.local_models) else f" ({visible_count:,} matching current filter)"
            self._set_status(f"Showing {len(self.local_models):,} cached local model file(s){suffix}. Use Refresh to scan again.")
            return
        self.scan_local_roots()

    def refresh_active_results_view(self) -> None:
        if self._active_results_view == "local":
            self.scan_local_roots()
            return
        self.search_mirror()


__all__ = ["ModelLibraryResultsViewMixin"]
