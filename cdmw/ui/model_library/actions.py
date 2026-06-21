"""Local-folder and mirror-search actions for Model Library."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QTreeWidgetItem

from cdmw.core.model_catalogue import (
    build_mirror_catalogue_index,
    scan_local_model_files,
    search_catalogue_records,
)


class ModelLibraryActionsMixin:
    """Manage local roots, catalogue indexing, and mirror searches."""

    def _refresh_roots_tree(self) -> None:
        self.roots_tree.clear()
        for root in self.local_roots:
            item = QTreeWidgetItem([root])
            self.roots_tree.addTopLevelItem(item)
        if self.local_roots and not self.local_path_edit.text().strip():
            self.local_path_edit.setText(self.local_roots[-1])

    def browse_local_folder(self) -> None:
        start_dir = self.local_path_edit.text().strip() or (self.local_roots[-1] if self.local_roots else str(Path.home()))
        folder = QFileDialog.getExistingDirectory(self, "Choose Model Folder", start_dir)
        if folder:
            self.local_path_edit.setText(folder)

    def add_local_root(self) -> None:
        folder = self.local_path_edit.text().strip()
        if not folder:
            self.browse_local_folder()
            folder = self.local_path_edit.text().strip()
        if not folder:
            return
        path = Path(folder).expanduser()
        if not path.is_dir():
            self._set_status(f"Local model folder does not exist: {path}", error=True)
            return
        try:
            normalized = str(path.resolve())
        except OSError:
            normalized = str(path.absolute())
        if normalized not in self.local_roots:
            self.local_roots.append(normalized)
            self._save_roots()
            self._refresh_roots_tree()
        self.scan_local_roots()

    def remove_selected_local_root(self) -> None:
        item = self.roots_tree.currentItem()
        if item is None:
            return
        root = item.text(0)
        self.local_roots = [value for value in self.local_roots if value != root]
        self._save_roots()
        self._refresh_roots_tree()

    def open_selected_local_root(self) -> None:
        item = self.roots_tree.currentItem()
        path = Path(item.text(0)) if item is not None else Path(self.local_path_edit.text().strip() or "")
        if path.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def scan_local_roots(self) -> None:
        self._set_active_results_view("local")
        roots = list(self.local_roots)
        if not roots:
            self.local_models = []
            self._populate_results([])
            self._set_status("Add at least one local model folder before scanning.", error=True)
            return

        def task(progress: Callable[[str], None]) -> object:
            progress("Scanning local model folders...")
            return [item.to_dict() for item in scan_local_model_files(roots)]

        def complete(result: object) -> None:
            models = result if isinstance(result, list) else []
            self._texture_status_cache.clear()
            self.local_models = self._normalize_local_model_rows([dict(item) for item in models if isinstance(item, dict)])
            self._populate_results(self.local_models)
            visible_count = self.results_tree.topLevelItemCount()
            suffix = "" if visible_count == len(self.local_models) else f" ({visible_count:,} matching current filter)"
            self._set_status(f"Showing Local Library: {len(self.local_models):,} model file(s){suffix}.")

        self._run_task("Scanning local model folders...", task, complete)

    def browse_catalogue_dir(self) -> None:
        start_dir = str(self.catalogue_dir())
        folder = QFileDialog.getExistingDirectory(self, "Choose Catalogue Folder", start_dir)
        if folder:
            self.catalogue_dir_edit.setText(folder)
            self._save_mirror_settings()
            self._update_catalogue_status()

    def build_mirror_index(self) -> None:
        self._save_mirror_settings()
        self._stop_event = threading.Event()
        try:
            mirror_url = self.mirror_url()
        except ValueError as exc:
            self._set_status(str(exc), error=True)
            self._stop_event = None
            return
        output_dir = self.catalogue_dir()
        max_shards = int(self.max_shards_spin.value())
        index_current_search = bool(self.index_current_search_checkbox.isChecked())
        index_query = self.search_edit.text().strip() if index_current_search else ""
        license_filter = self.license_filter_edit.text().strip() if index_current_search else ""
        creator_filter = self.creator_filter_edit.text().strip() if index_current_search else ""
        creator_excludes = self.creator_exclude_edit.text().strip() if index_current_search else ""
        format_filter = str(self.format_filter_combo.currentData() or "") if index_current_search else ""
        if index_current_search and not any((index_query, license_filter, creator_filter, creator_excludes, format_filter)):
            self._set_status("Enter a search term or filter before building a scoped mirror index.", error=True)
            self._stop_event = None
            return

        def task(progress: Callable[[str], None]) -> object:
            return build_mirror_catalogue_index(
                mirror_url=mirror_url,
                output_dir=output_dir,
                max_shards=max_shards,
                index_query=index_query,
                license_contains=license_filter,
                creator_contains=creator_filter,
                creator_excludes=creator_excludes,
                required_format=format_filter,
                clear_existing=index_current_search,
                stop_event=self._stop_event,
                on_progress=lambda _current, _total, message: progress(message),
            )

        def complete(result: object) -> None:
            self._stop_event = None
            self._update_catalogue_status()
            if isinstance(result, dict):
                scope_label = ""
                if bool(result.get("index_scoped")):
                    scope = str(result.get("index_query", "") or "current filters")
                    seen = int(result.get("seen_model_records_this_run", 0) or 0)
                    scope_label = f" Scoped to {scope!r}; scanned {seen:,} record(s)."
                self._set_status(
                    f"Indexed {int(result.get('indexed_model_records_this_run', 0)):,} model record(s) from "
                    f"{int(result.get('indexed_catalogue_pages', 0)):,} catalogue page(s) this run. "
                    f"Database now has {int(result.get('models_in_database', 0)):,} model(s) from "
                    f"{int(result.get('shards_in_database', 0)):,} cached page(s)."
                    f"{scope_label}"
                )
            else:
                self._set_status("Mirror catalogue index finished.")

        self._run_task("Building mirror metadata index...", task, complete)

    def cancel_current_task(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
            self._set_status("Cancelling current model library task...")

    def search_mirror(self, *, query_override: Optional[str] = None) -> None:
        self._set_active_results_view("mirror")
        self._save_mirror_settings()
        query = self.search_edit.text().strip() if query_override is None else str(query_override)
        if query_override is None:
            self.settings.setValue("model_library/search_query", query)
        db_path = self.catalogue_db_path()
        if not db_path.is_file():
            self.mirror_results = []
            self._populate_results([])
            self._set_status("Build the mirror search index before searching.", error=True)
            return
        limit = int(self.result_limit_spin.value())
        license_filter = self.license_filter_edit.text().strip()
        creator_filter = self.creator_filter_edit.text().strip()
        creator_excludes = self.creator_exclude_edit.text().strip()
        format_filter = str(self.format_filter_combo.currentData() or "")

        def task(progress: Callable[[str], None]) -> object:
            progress("Searching mirror catalogue...")
            return list(
                search_catalogue_records(
                    db_path,
                    query,
                    limit=limit,
                    license_contains=license_filter,
                    creator_contains=creator_filter,
                    creator_excludes=creator_excludes,
                    required_format=format_filter,
                )
            )

        def complete(result: object) -> None:
            rows = result if isinstance(result, list) else []
            self.mirror_results = [dict(item) for item in rows if isinstance(item, dict)]
            self._use_result_source_order()
            self._populate_results(self.mirror_results)
            filters = [value for value in (license_filter, creator_filter, format_filter) if value]
            if creator_excludes:
                filters.append(f"excluding creators: {creator_excludes}")
            label = query or "popular models"
            if filters:
                label = f"{label} with filters: {', '.join(filters)}"
            hidden = int(getattr(self, "_last_hidden_downloaded_count", 0) or 0)
            suffix = f" {hidden:,} downloaded result(s) hidden." if hidden else ""
            self._update_results_view_label()
            self._set_status(
                f"Showing Mirror Catalogue: {self.results_tree.topLevelItemCount():,}/{len(self.mirror_results):,} result(s) for {label}.{suffix}"
            )

        self._run_task("Searching mirror catalogue...", task, complete)


__all__ = ["ModelLibraryActionsMixin"]
