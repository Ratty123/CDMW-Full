"""Result-view state and query handling for Model Library."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLineEdit, QTreeWidgetItem


class ModelLibraryResultsViewMixin:
    """Coordinate active results view, debounced filters, and sort state."""

    def _handle_results_current_item_changed(self, _current: Optional[QTreeWidgetItem], _previous: Optional[QTreeWidgetItem]) -> None:
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
        if self._active_results_view == "local":
            self.settings.setValue("model_library/local_search_query", str(text))
            self._schedule_results_filter()
            self._update_results_view_label()
            return
        self.settings.setValue("model_library/search_query", str(text))
        self._update_results_view_label()

    def _handle_results_filter_field_changed(self) -> None:
        key = "model_library/local_search_field" if self._active_results_view == "local" else "model_library/search_field"
        self.settings.setValue(key, str(self.results_filter_field_combo.currentData() or "all"))
        if self._active_results_view == "local":
            self._schedule_results_filter()
            self._update_results_view_label()

    def _handle_local_texture_filter_changed(self) -> None:
        if not hasattr(self, "local_texture_filter_combo"):
            return
        self.settings.setValue("model_library/local_texture_filter", str(self.local_texture_filter_combo.currentData() or "all"))
        if self._active_results_view == "local":
            self._schedule_results_filter()
            self._update_results_view_label()

    def _handle_column_filter_changed(self, _editor: QLineEdit) -> None:
        if self._updating_column_filters:
            return
        self._save_column_filters_for_active_view()
        self._schedule_results_filter()
        self._update_results_view_label()

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
        finally:
            self._updating_results_query = False

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
        if self._active_results_view == "local":
            self.settings.setValue("model_library/local_search_query", self.search_edit.text().strip())
            self._populate_results(self.local_models)
            self._update_results_view_label()
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
            self._update_results_view_label()
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
        self._activation_preview_timer.start()

    def _preview_current_model_if_auto_enabled(self) -> None:
        if hasattr(self, "auto_preview_checkbox") and self.auto_preview_checkbox.isChecked():
            self.preview_selected_model_here()

    def _set_active_results_view(self, view: str, *, persist: bool = True) -> None:
        previous_view = getattr(self, "_active_results_view", "mirror")
        if hasattr(self, "search_edit") and not self._updating_results_query:
            if previous_view == "local":
                self.settings.setValue("model_library/local_search_query", self.search_edit.text().strip())
            else:
                self.settings.setValue("model_library/search_query", self.search_edit.text().strip())
        self._active_results_view = "local" if str(view).strip().lower() == "local" else "mirror"
        if hasattr(self, "mirror_results_view_button"):
            self.mirror_results_view_button.setChecked(self._active_results_view == "mirror")
            self.local_results_view_button.setChecked(self._active_results_view == "local")
        if hasattr(self, "mirror_group"):
            self.mirror_group.setVisible(self._active_results_view == "mirror")
        if hasattr(self, "results_search_label"):
            if self._active_results_view == "local":
                self.results_search_label.setText("Filter local")
                self.apply_results_query_button.setText("Apply")
                self.search_edit.setPlaceholderText("Filter local models by name, creator, license, format, path, or source")
                self.results_filter_field_combo.setEnabled(True)
                self._set_results_filter_field(str(self.settings.value("model_library/local_search_field", "all") or "all"))
                self._set_local_texture_filter(str(self.settings.value("model_library/local_texture_filter", "all") or "all"))
                self._set_results_query_text(str(self.settings.value("model_library/local_search_query", "") or ""))
            else:
                self.results_search_label.setText("Search mirror")
                self.apply_results_query_button.setText("Search")
                self.search_edit.setPlaceholderText("Search mirror by name, tag, creator, or UID")
                self.results_filter_field_combo.setEnabled(False)
                self._set_results_filter_field("all")
                self._set_results_query_text(str(self.settings.value("model_library/search_query", self.search_edit.text()) or ""))
            local_view = self._active_results_view == "local"
            self.local_texture_filter_label.setVisible(local_view)
            self.local_texture_filter_combo.setVisible(local_view)
            self._load_column_filters_for_active_view()
        if persist:
            self.settings.setValue("model_library/results_view", self._active_results_view)
        self._update_results_view_label()

    def _update_results_view_label(self) -> None:
        if not hasattr(self, "results_view_label"):
            return
        if self._active_results_view == "local":
            roots = len(getattr(self, "local_roots", ()) or ())
            query = str(self.search_edit.text() if hasattr(self, "search_edit") else "").strip()
            field = str(
                self.results_filter_field_combo.currentText()
                if hasattr(self, "results_filter_field_combo")
                else "All fields"
            )
            filter_text = f" Filter: {query} ({field})." if query else ""
            texture_filter = str(
                self.local_texture_filter_combo.currentText()
                if hasattr(self, "local_texture_filter_combo") and self.local_texture_filter_combo.currentData() != "all"
                else ""
            )
            texture_text = f" Textures: {texture_filter}." if texture_filter else ""
            self.results_view_label.setText(
                f"Local Library | {roots:,} folder(s), including downloaded mirror models when available.{filter_text}{texture_text}"
            )
            return
        query = str(self.search_edit.text() if hasattr(self, "search_edit") else "").strip()
        query_text = f" Search: {query}" if query else " Search: popular models"
        self.results_view_label.setText(f"Mirror Catalogue | Indexed metadata results from the mirror catalogue.{query_text}")

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
