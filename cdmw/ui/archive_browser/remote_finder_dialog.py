"""Lazy paged Item Finder dialog for the Full archive backend."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from cdmw.domain.archives.item_catalogue import (
    ItemCatalogRow,
    ItemCatalogScopeRequest,
    ItemCatalogScopeResult,
    ItemCatalogSearchRequest,
    ItemCatalogSearchResult,
    ItemIconBatchRequest,
    ItemIconBatchResult,
)
from cdmw.services.preview_workflow_service import ensure_dds_display_preview_png


class _IconConversionWorker(QObject):
    finished = Signal(object)

    def __init__(self, sources: dict[int, str], stop_event: threading.Event) -> None:
        super().__init__()
        self._sources = dict(sources)
        self._stop_event = stop_event

    @Slot()
    def run(self) -> None:
        results: dict[int, str] = {}
        for item_id, source in self._sources.items():
            if self._stop_event.is_set():
                break
            try:
                path = Path(source)
                preview = (
                    ensure_dds_display_preview_png(
                        path,
                        max_dimension=120,
                        slot_kind="base",
                        stop_event=self._stop_event,
                    )
                    if path.suffix.casefold() == ".dds"
                    else path
                )
                if preview.is_file():
                    results[item_id] = str(preview)
            except Exception:
                continue
        self.finished.emit(results)


class RemoteArchiveFinderDialog(QDialog):
    """A latest-request-wins Item Finder over one published archive fingerprint."""

    def __init__(self, window: object) -> None:
        super().__init__(window)  # type: ignore[arg-type]
        self._window = window
        self._service = window.archive_catalogue_service
        self._bridge = window.archive_remote_bridge
        session = self._bridge.current_session
        if session is None:
            raise RuntimeError("A Full archive session must be ready before opening a Finder.")
        self._session_id = session.session_id
        self._fingerprint = session.fingerprint
        self._page_size = 72
        self._page_start = 0
        self._total_matches = 0
        self._search_request_id: str | None = None
        self._scope_request_id: str | None = None
        self._icon_request_id: str | None = None
        self._rows: dict[int, ItemCatalogRow] = {}
        self._tree_items: dict[int, QTreeWidgetItem] = {}
        self._icon_requested: set[int] = set()
        self._icon_threads: set[QThread] = set()
        self._icon_stop_events: set[threading.Event] = set()
        self._closing = False
        self._facets_ready = False
        self._build_ui()
        self._connect_service()
        QTimer.singleShot(0, self._start_search)

    def _build_ui(self) -> None:
        self.setWindowTitle("Item Finder")
        self.resize(1160, 760)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        intro = QLabel(
            "Search recovered item names, model links, icons, and categories. Results are loaded one page at a time."
        )
        intro.setObjectName("HintLabel")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        controls = QHBoxLayout()
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search item name, ID, model stem, category, material tag, or icon path")
        self._category_combo = QComboBox()
        self._category_combo.addItem("All categories", (None, None))
        self._material_combo = QComboBox()
        self._material_combo.addItem("All materials", None)
        clear_button = QPushButton("Clear")
        controls.addWidget(self._search_edit, stretch=1)
        controls.addWidget(self._category_combo)
        controls.addWidget(self._material_combo)
        controls.addWidget(clear_button)
        layout.addLayout(controls)

        self._status = QLabel("Loading catalogue...")
        self._status.setObjectName("HintLabel")
        self._status.setWordWrap(True)
        self._status.setMinimumHeight(38)
        layout.addWidget(self._status)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(5)
        self._tree.setHeaderLabels(["Item", "Category", "Materials", "Links", "Evidence"])
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        self._tree.setUniformRowHeights(True)
        self._tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self._tree.header().setStretchLastSection(True)
        self._tree.setColumnWidth(0, 310)
        self._tree.setColumnWidth(1, 180)
        self._tree.setColumnWidth(2, 230)
        self._tree.setColumnWidth(3, 90)
        layout.addWidget(self._tree, stretch=1)

        buttons = QHBoxLayout()
        self._previous_button = QPushButton("Previous")
        self._next_button = QPushButton("Next")
        self._retry_button = QPushButton("Retry")
        self._retry_button.setVisible(False)
        self._cancel_button = QPushButton("Cancel Loading")
        self._exact_button = QPushButton("Show Exact Links")
        self._related_button = QPushButton("Show Related Set")
        close_button = QPushButton("Close")
        buttons.addWidget(self._previous_button)
        buttons.addWidget(self._next_button)
        buttons.addWidget(self._retry_button)
        buttons.addWidget(self._cancel_button)
        buttons.addStretch(1)
        buttons.addWidget(self._exact_button)
        buttons.addWidget(self._related_button)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(220)
        self._visible_icon_timer = QTimer(self)
        self._visible_icon_timer.setSingleShot(True)
        self._visible_icon_timer.setInterval(100)
        self._search_edit.textChanged.connect(self._queue_first_page)
        self._category_combo.currentIndexChanged.connect(self._queue_first_page)
        self._material_combo.currentIndexChanged.connect(self._queue_first_page)
        clear_button.clicked.connect(self._search_edit.clear)
        self._search_timer.timeout.connect(self._start_search)
        self._visible_icon_timer.timeout.connect(self._request_visible_icons)
        self._tree.verticalScrollBar().valueChanged.connect(lambda _value: self._visible_icon_timer.start())
        self._tree.itemSelectionChanged.connect(self._update_buttons)
        self._previous_button.clicked.connect(self._previous_page)
        self._next_button.clicked.connect(self._next_page)
        self._retry_button.clicked.connect(self._start_search)
        self._cancel_button.clicked.connect(self._cancel_search)
        self._exact_button.clicked.connect(lambda: self._scope_selected(include_related=False))
        self._related_button.clicked.connect(lambda: self._scope_selected(include_related=True))
        self._tree.itemDoubleClicked.connect(lambda _item, _column: self._scope_selected(include_related=True))
        close_button.clicked.connect(self.reject)
        self._update_buttons()

    def _connect_service(self) -> None:
        self._service.result_ready.connect(self._handle_result)
        self._service.request_failed.connect(self._handle_failure)
        self._service.request_cancelled.connect(self._handle_cancelled)
        self._service.progress.connect(self._handle_progress)

    def _disconnect_service(self) -> None:
        for signal, slot in (
            (self._service.result_ready, self._handle_result),
            (self._service.request_failed, self._handle_failure),
            (self._service.request_cancelled, self._handle_cancelled),
            (self._service.progress, self._handle_progress),
        ):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    def _session_is_current(self) -> bool:
        session = self._bridge.current_session
        return bool(session is not None and session.session_id == self._session_id and session.fingerprint == self._fingerprint)

    def _queue_first_page(self) -> None:
        self._page_start = 0
        self._search_timer.start()

    def _selected_filters(self) -> tuple[str | None, str | None, str | None]:
        category: str | None = None
        group: str | None = None
        value = self._category_combo.currentData()
        if isinstance(value, tuple) and len(value) == 2:
            category = str(value[0]) if value[0] else None
            group = str(value[1]) if value[1] else None
        material_value = self._material_combo.currentData()
        material = str(material_value) if material_value else None
        return category, group, material

    def _start_search(self) -> None:
        if self._closing:
            return
        if not self._session_is_current():
            self._show_error("The archive was refreshed. Close and reopen this Finder for the new catalogue.")
            return
        self._cancel_request("_search_request_id")
        category, group, material = self._selected_filters()
        self._status.setText("Loading catalogue..." if not self._facets_ready else "Searching catalogue...")
        self._retry_button.setVisible(False)
        self._cancel_button.setVisible(True)
        self._tree.setEnabled(False)
        try:
            self._search_request_id = self._service.search_item_catalog(
                ItemCatalogSearchRequest(
                    self._session_id,
                    query=self._search_edit.text().strip(),
                    category=category,
                    group=group,
                    material_tag=material,
                    page_start=self._page_start,
                    page_size=self._page_size,
                ),
                ui_generation=self._bridge.controller.generation,
            )
        except Exception as exc:
            self._search_request_id = None
            self._show_error(str(exc))
        self._update_buttons()

    def _cancel_search(self) -> None:
        if self._cancel_request("_search_request_id"):
            self._status.setText("Catalogue request cancelled. Retry when ready.")
            self._retry_button.setVisible(True)
        self._cancel_button.setVisible(False)
        self._tree.setEnabled(True)
        self._update_buttons()

    def _cancel_request(self, attribute: str) -> bool:
        request_id = getattr(self, attribute)
        if not request_id:
            return False
        setattr(self, attribute, None)
        return bool(self._service.cancel(request_id))

    def _handle_progress(self, request_id: str, update: object) -> None:
        if request_id != self._search_request_id:
            return
        phase = str(getattr(update, "phase", "catalogue") or "catalogue").replace("_", " ").capitalize()
        completed = int(getattr(update, "completed", 0) or 0)
        total = int(getattr(update, "total", 0) or 0)
        self._status.setText(f"{phase}: {completed:,} / {total:,}" if total > 0 else f"{phase}...")

    def _handle_result(self, request_id: str, operation: str, result: object) -> None:
        if request_id == self._search_request_id and isinstance(result, ItemCatalogSearchResult):
            self._search_request_id = None
            self._publish_search(result)
            return
        if request_id == self._scope_request_id and isinstance(result, ItemCatalogScopeResult):
            self._scope_request_id = None
            self._publish_scope(result)
            return
        if request_id == self._icon_request_id and isinstance(result, ItemIconBatchResult):
            self._icon_request_id = None
            self._publish_icon_sources(result)

    def _handle_failure(self, request_id: str, error: object) -> None:
        if request_id == self._search_request_id:
            self._search_request_id = None
            self._show_error(str(error))
        elif request_id == self._scope_request_id:
            self._scope_request_id = None
            self._show_error(f"Could not build the archive scope: {error}")
        elif request_id == self._icon_request_id:
            self._icon_request_id = None

    def _handle_cancelled(self, request_id: str) -> None:
        for attribute in ("_search_request_id", "_scope_request_id", "_icon_request_id"):
            if getattr(self, attribute) == request_id:
                setattr(self, attribute, None)
        self._update_buttons()

    def _show_error(self, message: str) -> None:
        self._status.setText(f"Catalogue error: {message}")
        self._retry_button.setVisible(True)
        self._cancel_button.setVisible(False)
        self._tree.setEnabled(True)
        self._update_buttons()

    def _publish_search(self, result: ItemCatalogSearchResult) -> None:
        if not self._session_is_current() or result.session_id != self._session_id:
            return
        self._total_matches = result.total_matches
        self._page_start = result.page_start
        self._rows = {row.item_id: row for row in result.items}
        self._tree_items.clear()
        self._icon_requested.clear()
        self._tree.clear()
        for row in result.items:
            item = QTreeWidgetItem(
                [
                    row.display_name or row.internal_name,
                    f"{row.category} / {row.group}",
                    ", ".join(row.material_tags[:6]) or "—",
                    str(len(row.pac_files) + len(row.model_stems) + len(row.icon_paths)),
                    row.evidence or row.category_evidence,
                ]
            )
            item.setData(0, Qt.UserRole, row.item_id)
            item.setToolTip(0, f"{row.internal_name} (ID {row.item_id})")
            self._tree.addTopLevelItem(item)
            self._tree_items[row.item_id] = item
        if not self._facets_ready:
            self._populate_facets(result)
        self._facets_ready = True
        shown_end = min(result.total_matches, result.page_start + len(result.items))
        if result.warning:
            self._status.setText(result.warning)
        elif result.total_matches == 0:
            self._status.setText("No catalogue entries match the current search and filters.")
        else:
            self._status.setText(
                f"Showing {result.page_start + 1:,}–{shown_end:,} of {result.total_matches:,} matching entries."
            )
        self._cancel_button.setVisible(False)
        self._retry_button.setVisible(bool(result.warning))
        self._tree.setEnabled(True)
        self._update_buttons()
        QTimer.singleShot(0, self._request_visible_icons)

    def _populate_facets(self, result: ItemCatalogSearchResult) -> None:
        category_value = self._category_combo.currentData()
        material_value = self._material_combo.currentData()
        self._category_combo.blockSignals(True)
        self._material_combo.blockSignals(True)
        try:
            self._category_combo.clear()
            self._category_combo.addItem("All categories", (None, None))
            for facet in result.categories:
                self._category_combo.addItem(
                    f"{facet.category} / {facet.group} ({facet.count:,})",
                    (facet.category, facet.group),
                )
            self._material_combo.clear()
            self._material_combo.addItem("All materials", None)
            for facet in result.material_tags:
                self._material_combo.addItem(f"{facet.value} ({facet.count:,})", facet.value)
            self._restore_combo_data(self._category_combo, category_value)
            self._restore_combo_data(self._material_combo, material_value)
        finally:
            self._category_combo.blockSignals(False)
            self._material_combo.blockSignals(False)

    @staticmethod
    def _restore_combo_data(combo: QComboBox, value: object) -> None:
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                combo.setCurrentIndex(index)
                return

    def _previous_page(self) -> None:
        self._page_start = max(0, self._page_start - self._page_size)
        self._start_search()

    def _next_page(self) -> None:
        if self._page_start + self._page_size < self._total_matches:
            self._page_start += self._page_size
            self._start_search()

    def _selected_item_ids(self) -> tuple[int, ...]:
        return tuple(
            int(item.data(0, Qt.UserRole))
            for item in self._tree.selectedItems()
            if isinstance(item.data(0, Qt.UserRole), int)
        )

    def _scope_selected(self, *, include_related: bool) -> None:
        item_ids = self._selected_item_ids()
        if not item_ids:
            QMessageBox.information(self, self.windowTitle(), "Select at least one catalogue row first.")
            return
        label = self._rows[item_ids[0]].display_name if len(item_ids) == 1 else f"{len(item_ids):,} selected items"
        self._start_scope(
            ItemCatalogScopeRequest(
                self._session_id,
                item_ids=item_ids,
                include_related=include_related,
            ),
            label=f"{self.windowTitle()}: {label}",
        )

    def _start_scope(self, request: ItemCatalogScopeRequest, *, label: str) -> None:
        self._cancel_request("_scope_request_id")
        self._pending_scope_label = label
        self._status.setText("Resolving archive links for the selected scope...")
        try:
            self._scope_request_id = self._service.scope_item_catalog(
                request,
                ui_generation=self._bridge.controller.generation,
            )
        except Exception as exc:
            self._scope_request_id = None
            self._show_error(str(exc))
        self._update_buttons()

    def _publish_scope(self, result: ItemCatalogScopeResult) -> None:
        if not self._session_is_current() or result.session_id != self._session_id:
            return
        if not result.entry_ids:
            self._status.setText("The selected catalogue rows have no resolvable archive links.")
            self._update_buttons()
            return
        label = getattr(self, "_pending_scope_label", self.windowTitle())
        if self._bridge.apply_entry_id_scope(result.entry_ids, label=label):
            suffix = " (result capped)" if result.truncated else ""
            self._status.setText(f"Scoped the Archive Browser to {len(result.entry_ids):,} files{suffix}.")
        self._update_buttons()

    def _request_visible_icons(self) -> None:
        if self._icon_request_id or not self._tree_items or self._closing:
            return
        viewport = self._tree.viewport()
        first = self._tree.indexAt(QPoint(2, 2)).row()
        last = self._tree.indexAt(QPoint(2, max(2, viewport.height() - 2))).row()
        if first < 0:
            first = 0
        if last < first:
            last = min(self._tree.topLevelItemCount() - 1, first + 23)
        ids: list[int] = []
        for row_index in range(first, min(last + 1, self._tree.topLevelItemCount())):
            item = self._tree.topLevelItem(row_index)
            item_id = item.data(0, Qt.UserRole)
            record = self._rows.get(item_id) if isinstance(item_id, int) else None
            if record is not None and record.icon_paths and item_id not in self._icon_requested:
                ids.append(item_id)
            if len(ids) >= 64:
                break
        if not ids:
            return
        self._icon_requested.update(ids)
        try:
            self._icon_request_id = self._service.load_item_icons(
                ItemIconBatchRequest(self._session_id, tuple(ids), thumbnail_size=120),
                ui_generation=self._bridge.controller.generation,
            )
        except Exception:
            self._icon_request_id = None

    def _publish_icon_sources(self, result: ItemIconBatchResult) -> None:
        if self._closing or result.session_id != self._session_id:
            return
        direct: dict[int, str] = {}
        sources: dict[int, str] = {}
        for item in result.items:
            if item.png_path:
                direct[item.item_id] = item.png_path
            elif item.source_path:
                sources[item.item_id] = item.source_path
        self._apply_icons(direct)
        if not sources:
            return
        stop_event = threading.Event()
        thread = QThread(self)
        worker = _IconConversionWorker(sources, stop_event)
        worker.moveToThread(thread)
        self._icon_threads.add(thread)
        self._icon_stop_events.add(stop_event)
        thread.started.connect(worker.run)
        worker.finished.connect(self._apply_icons)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda thread=thread, stop_event=stop_event: self._icon_thread_finished(thread, stop_event))
        thread.finished.connect(thread.deleteLater)
        thread.start()

    @Slot(object)
    def _apply_icons(self, paths: object) -> None:
        if not isinstance(paths, dict) or self._closing:
            return
        for item_id, path in paths.items():
            tree_item = self._tree_items.get(int(item_id))
            if tree_item is None:
                continue
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                continue
            tree_item.setIcon(0, QIcon(pixmap.scaled(72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation)))

    def _icon_thread_finished(self, thread: QThread, stop_event: threading.Event) -> None:
        self._icon_threads.discard(thread)
        self._icon_stop_events.discard(stop_event)
        if not self._closing:
            self._visible_icon_timer.start()
        self._release_if_finished()

    def _update_buttons(self) -> None:
        busy = bool(self._search_request_id or self._scope_request_id)
        self._previous_button.setEnabled(not busy and self._page_start > 0)
        self._next_button.setEnabled(not busy and self._page_start + self._page_size < self._total_matches)
        has_selection = bool(self._tree.selectedItems())
        self._exact_button.setEnabled(not busy and has_selection)
        self._related_button.setEnabled(not busy and has_selection)

    def closeEvent(self, event: object) -> None:
        self._closing = True
        self._search_timer.stop()
        self._visible_icon_timer.stop()
        for attribute in ("_search_request_id", "_scope_request_id", "_icon_request_id"):
            self._cancel_request(attribute)
        for stop_event in tuple(self._icon_stop_events):
            stop_event.set()
        self._disconnect_service()
        self._release_if_finished()
        super().closeEvent(event)  # type: ignore[arg-type]

    def _release_if_finished(self) -> None:
        if not self._closing or self._icon_threads:
            return
        retained = getattr(self._window, "_remote_archive_finder_dialogs", None)
        if isinstance(retained, set):
            retained.discard(self)


def show_remote_archive_finder(window: object) -> None:
    dialog = RemoteArchiveFinderDialog(window)
    retained = getattr(window, "_remote_archive_finder_dialogs", None)
    if not isinstance(retained, set):
        retained = set()
        setattr(window, "_remote_archive_finder_dialogs", retained)
    retained.add(dialog)
    dialog.exec()
    dialog._closing = True
    dialog.close()
    dialog._release_if_finished()


__all__ = ["RemoteArchiveFinderDialog", "show_remote_archive_finder"]
