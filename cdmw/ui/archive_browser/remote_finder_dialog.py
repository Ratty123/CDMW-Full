"""Lazy paged Item Finder dialog for the Full archive backend."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, QSize, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
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

    def __init__(
        self,
        sources: dict[int, str],
        stop_event: threading.Event,
        generation: int,
        owner_thread: QThread,
    ) -> None:
        super().__init__()
        self._sources = dict(sources)
        self._stop_event = stop_event
        self._generation = int(generation)
        self._owner_thread = owner_thread

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
        self.moveToThread(self._owner_thread)
        self.finished.emit((self._generation, results))


class _ItemFinderGrid(QListWidget):
    """Icon grid with the prior private test hooks retained during the UI transition."""

    def topLevelItemCount(self) -> int:
        return self.count()

    def topLevelItem(self, index: int) -> QListWidgetItem | None:
        return self.item(index)


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
        self._tree_items: dict[int, QListWidgetItem] = {}
        self._icon_requested: set[int] = set()
        self._icon_threads: set[QThread] = set()
        self._icon_workers: dict[QThread, _IconConversionWorker] = {}
        self._icon_stop_events: set[threading.Event] = set()
        self._icon_generation = 0
        self._closing = False
        self._facets_ready = False
        self._settings = getattr(window, "settings", None)
        self._preferred_category = self._read_setting("ui/item_finder_category")
        self._preferred_group = self._read_setting("ui/item_finder_group")
        self._preferred_material = self._read_setting("ui/item_finder_material_tag")
        self._item_grid: _ItemFinderGrid | None = None
        self._tree: _ItemFinderGrid | None = None
        self._item_splitter: QSplitter | None = None
        self._build_ui()
        self._restore_geometry()
        self._connect_service()
        QTimer.singleShot(0, self._start_search)

    def _read_setting(self, key: str, default: object = "") -> str:
        if self._settings is None:
            return str(default or "")
        try:
            return str(self._settings.value(key, default) or "")
        except Exception:
            return str(default or "")

    def _restore_geometry(self) -> None:
        if self._settings is None:
            return
        try:
            geometry = self._settings.value("ui/item_finder_geometry")
            if geometry:
                self.restoreGeometry(geometry)
        except Exception:
            pass

    def _build_ui(self) -> None:
        self.setWindowTitle("Item Finder")
        self.resize(1240, 800)
        self.setMinimumSize(940, 640)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        intro = QLabel(
            "Browse recovered item names, icons, model links, and categories. Results are paged so the Finder stays responsive."
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
        search_button = QPushButton("Search")
        clear_button = QPushButton("Clear")
        controls.addWidget(self._search_edit, stretch=1)
        controls.addWidget(self._category_combo)
        controls.addWidget(self._material_combo)
        controls.addWidget(search_button)
        controls.addWidget(clear_button)
        layout.addLayout(controls)

        self._build_item_results(layout)

        buttons = QHBoxLayout()
        self._status = QLabel("Loading catalogue...")
        self._status.setObjectName("HintLabel")
        self._status.setWordWrap(True)
        self._status.setMinimumHeight(38)
        self._previous_button = QPushButton("Previous")
        self._next_button = QPushButton("Next")
        self._retry_button = QPushButton("Retry")
        self._retry_button.setVisible(False)
        self._cancel_button = QPushButton("Cancel Loading")
        close_button = QPushButton("Close")
        buttons.addWidget(self._status, stretch=1)
        buttons.addWidget(self._previous_button)
        buttons.addWidget(self._next_button)
        buttons.addWidget(self._retry_button)
        buttons.addWidget(self._cancel_button)
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
        self._search_edit.returnPressed.connect(self._start_search)
        search_button.clicked.connect(self._start_search)
        clear_button.clicked.connect(self._clear_filters)
        self._search_timer.timeout.connect(self._start_search)
        self._visible_icon_timer.timeout.connect(self._request_visible_icons)
        self._item_grid.verticalScrollBar().valueChanged.connect(lambda _value: self._visible_icon_timer.start())
        self._item_grid.itemSelectionChanged.connect(self._update_selected_item_detail)
        self._item_grid.itemDoubleClicked.connect(lambda _item: self._scope_selected(include_related=True))
        self._previous_button.clicked.connect(self._previous_page)
        self._next_button.clicked.connect(self._next_page)
        self._retry_button.clicked.connect(self._start_search)
        self._cancel_button.clicked.connect(self._cancel_search)
        self._exact_button.clicked.connect(lambda: self._scope_selected(include_related=False))
        self._related_button.clicked.connect(lambda: self._scope_selected(include_related=True))
        close_button.clicked.connect(self.reject)
        restored_query = self._read_setting("ui/item_finder_search_text")
        if restored_query:
            self._search_edit.setText(restored_query)
        localizer = getattr(self._window, "ui_localizer", None)
        if localizer is not None and callable(getattr(localizer, "apply", None)):
            localizer.apply(self)
        self._update_buttons()

    def _build_item_results(self, layout: QVBoxLayout) -> None:
        splitter = QSplitter(Qt.Horizontal)
        self._item_splitter = splitter

        browser_panel = QFrame()
        browser_panel.setObjectName("ItemFinderBrowsePanel")
        browser_layout = QVBoxLayout(browser_panel)
        browser_layout.setContentsMargins(0, 0, 0, 0)
        self._item_grid = _ItemFinderGrid()
        self._tree = self._item_grid
        self._item_grid.setObjectName("ItemFinderGrid")
        self._item_grid.setViewMode(QListView.IconMode)
        self._item_grid.setResizeMode(QListView.Adjust)
        self._item_grid.setMovement(QListView.Static)
        self._item_grid.setWrapping(True)
        self._item_grid.setWordWrap(True)
        self._item_grid.setUniformItemSizes(True)
        self._item_grid.setIconSize(QSize(112, 112))
        self._item_grid.setGridSize(QSize(176, 184))
        self._item_grid.setSpacing(4)
        self._item_grid.setSelectionMode(QAbstractItemView.SingleSelection)
        browser_layout.addWidget(self._item_grid)
        splitter.addWidget(browser_panel)

        detail_panel = QFrame()
        detail_panel.setObjectName("ItemFinderDetailPanel")
        detail_panel.setMinimumWidth(300)
        detail_panel.setMaximumWidth(520)
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(8, 8, 8, 8)

        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setFrameShape(QFrame.NoFrame)
        detail_body = QWidget()
        detail_body_layout = QVBoxLayout(detail_body)
        detail_body_layout.setContentsMargins(4, 4, 4, 4)
        detail_body_layout.setSpacing(6)

        header = QHBoxLayout()
        self._detail_icon = QLabel("?")
        self._detail_icon.setObjectName("ItemFinderIconPreview")
        self._detail_icon.setAlignment(Qt.AlignCenter)
        self._detail_icon.setFixedSize(120, 120)
        self._detail_icon.setFrameShape(QFrame.StyledPanel)
        header.addWidget(self._detail_icon)
        header_text = QVBoxLayout()
        self._detail_title = self._detail_label("Select an item", prominent=True)
        self._detail_internal = self._detail_label("Recovered item details will appear here.")
        self._detail_category = self._detail_label("")
        self._detail_summary = self._detail_label("")
        header_text.addWidget(self._detail_title)
        header_text.addWidget(self._detail_internal)
        header_text.addWidget(self._detail_category)
        header_text.addWidget(self._detail_summary)
        header_text.addStretch(1)
        header.addLayout(header_text, stretch=1)
        detail_body_layout.addLayout(header)

        detail_body_layout.addWidget(self._section_label("Evidence"))
        self._detail_evidence = self._detail_label("Select an item to inspect its recovered evidence.")
        self._detail_category_evidence = self._detail_label("")
        detail_body_layout.addWidget(self._detail_evidence)
        detail_body_layout.addWidget(self._detail_category_evidence)
        self._detail_localized = self._add_detail_section(detail_body_layout, "Localized names")
        self._detail_materials = self._add_detail_section(detail_body_layout, "Materials")
        self._detail_models = self._add_detail_section(detail_body_layout, "Models and PAC links")
        self._detail_icons = self._add_detail_section(detail_body_layout, "Icons")
        detail_body_layout.addStretch(1)
        detail_scroll.setWidget(detail_body)
        detail_layout.addWidget(detail_scroll, stretch=1)

        self._exact_button = QPushButton("Show Exact Links")
        self._exact_button.setToolTip("Show only direct model and icon paths recovered for this item.")
        self._related_button = QPushButton("Show Related Set")
        self._related_button.setToolTip(
            "Show direct links plus indexed companions such as textures, material sidecars, HKX, meshinfo, and rig data."
        )
        detail_actions = QHBoxLayout()
        detail_actions.addWidget(self._exact_button)
        detail_actions.addWidget(self._related_button)
        detail_actions.addStretch(1)
        detail_layout.addLayout(detail_actions)
        splitter.addWidget(detail_panel)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes(self._restored_splitter_sizes() or [820, 380])
        layout.addWidget(splitter, stretch=1)

    @staticmethod
    def _detail_label(text: str, *, prominent: bool = False) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        if prominent:
            font = label.font()
            font.setBold(True)
            font.setPointSize(max(font.pointSize() + 2, 11))
            label.setFont(font)
        return label

    @staticmethod
    def _section_label(text: str) -> QLabel:
        label = QLabel(text)
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        label.setContentsMargins(0, 10, 0, 0)
        return label

    def _add_detail_section(self, layout: QVBoxLayout, title: str) -> QLabel:
        layout.addWidget(self._section_label(title))
        value = self._detail_label("None")
        layout.addWidget(value)
        return value

    def _restored_splitter_sizes(self) -> list[int]:
        if self._settings is None:
            return []
        try:
            raw = self._settings.value("ui/item_finder_splitter_sizes")
        except Exception:
            return []
        if not isinstance(raw, (list, tuple)):
            return []
        try:
            sizes = [max(1, int(value)) for value in raw]
        except (TypeError, ValueError):
            return []
        return sizes if len(sizes) == 2 else []

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

    def _clear_filters(self) -> None:
        self._search_timer.stop()
        for widget in (self._search_edit, self._category_combo, self._material_combo):
            widget.blockSignals(True)
        try:
            self._search_edit.clear()
            self._category_combo.setCurrentIndex(0)
            self._material_combo.setCurrentIndex(0)
        finally:
            for widget in (self._search_edit, self._category_combo, self._material_combo):
                widget.blockSignals(False)
        self._page_start = 0
        self._start_search()

    def _selected_filters(self) -> tuple[str | None, str | None, str | None]:
        category: str | None = self._preferred_category or None
        group: str | None = self._preferred_group or None
        if category is None:
            value = self._category_combo.currentData()
            if isinstance(value, tuple) and len(value) == 2:
                category = str(value[0]) if value[0] else None
                group = str(value[1]) if value[1] else None
        material_value = self._material_combo.currentData()
        material = self._preferred_material or (str(material_value) if material_value else None)
        return category, group, material

    def _start_search(self) -> None:
        if self._closing:
            return
        self._search_timer.stop()
        if not self._session_is_current():
            self._show_error("The archive was refreshed. Close and reopen this Finder for the new catalogue.")
            return
        self._cancel_request("_search_request_id")
        self._cancel_icon_loading()
        category, group, material = self._selected_filters()
        self._status.setText("Loading catalogue..." if not self._facets_ready else "Searching catalogue...")
        self._retry_button.setVisible(False)
        self._cancel_button.setVisible(True)
        self._item_grid.setEnabled(False)
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
        self._item_grid.setEnabled(True)
        self._visible_icon_timer.start()
        self._update_buttons()

    def _cancel_request(self, attribute: str) -> bool:
        request_id = getattr(self, attribute)
        if not request_id:
            return False
        setattr(self, attribute, None)
        return bool(self._service.cancel(request_id))

    def _cancel_icon_loading(self) -> None:
        self._icon_generation += 1
        self._cancel_request("_icon_request_id")
        self._icon_requested.clear()
        for stop_event in tuple(self._icon_stop_events):
            stop_event.set()

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
            if not self._closing:
                self._visible_icon_timer.start()

    def _handle_cancelled(self, request_id: str) -> None:
        for attribute in ("_search_request_id", "_scope_request_id", "_icon_request_id"):
            if getattr(self, attribute) == request_id:
                setattr(self, attribute, None)
        self._update_buttons()

    def _show_error(self, message: str) -> None:
        self._status.setText(f"Catalogue error: {message}")
        self._retry_button.setVisible(True)
        self._cancel_button.setVisible(False)
        self._item_grid.setEnabled(True)
        if self._tree_items and not self._closing:
            self._visible_icon_timer.start()
        self._update_buttons()

    def _publish_search(self, result: ItemCatalogSearchResult) -> None:
        if not self._session_is_current() or result.session_id != self._session_id:
            return
        previous_selection = self._selected_item_ids()
        self._total_matches = result.total_matches
        self._page_start = result.page_start
        self._rows = {row.item_id: row for row in result.items}
        self._tree_items.clear()
        self._icon_requested.clear()
        self._item_grid.clear()
        for row in result.items:
            display_name = row.display_name or row.internal_name or f"Item {row.item_id}"
            item = QListWidgetItem(self._fallback_icon(row), f"{display_name}\n{row.category} / {row.group}")
            item.setData(Qt.UserRole, row.item_id)
            item.setSizeHint(QSize(168, 178))
            item.setTextAlignment(Qt.AlignHCenter)
            item.setToolTip(
                f"{row.internal_name} (ID {row.item_id})\n"
                f"{row.evidence or row.category_evidence or 'Recovered item catalogue row'}"
            )
            self._item_grid.addItem(item)
            self._tree_items[row.item_id] = item
        if not self._facets_ready:
            self._populate_facets(result)
        self._facets_ready = True
        if previous_selection and previous_selection[0] in self._tree_items:
            self._item_grid.setCurrentItem(self._tree_items[previous_selection[0]])
        self._update_selected_item_detail()
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
        self._item_grid.setEnabled(True)
        self._update_buttons()
        QTimer.singleShot(0, self._request_visible_icons)

    def _fallback_icon(self, row: ItemCatalogRow) -> QIcon:
        builder = getattr(self._window, "_build_archive_asset_catalog_icon", None)
        if callable(builder):
            try:
                icon = builder(row.category, row.display_name or row.internal_name)
                if isinstance(icon, QIcon) and not icon.isNull():
                    return icon
            except Exception:
                pass
        pixmap = QPixmap(112, 112)
        palette = self.palette()
        pixmap.fill(palette.color(QPalette.Window))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(palette.color(QPalette.Mid))
        painter.setBrush(palette.color(QPalette.AlternateBase))
        painter.drawRoundedRect(4, 4, 104, 104, 9, 9)
        painter.setPen(palette.color(QPalette.Text))
        font = painter.font()
        font.setBold(True)
        font.setPixelSize(38)
        painter.setFont(font)
        display_name = row.display_name or row.internal_name or "?"
        fallback = next((character.upper() for character in display_name if character.isalnum()), "?")
        painter.drawText(pixmap.rect(), Qt.AlignCenter, fallback)
        painter.end()
        return QIcon(pixmap)

    def _selected_row(self) -> ItemCatalogRow | None:
        item = self._item_grid.currentItem()
        if item is None and self._item_grid.selectedItems():
            item = self._item_grid.selectedItems()[0]
        if item is None:
            return None
        item_id = item.data(Qt.UserRole)
        return self._rows.get(item_id) if isinstance(item_id, int) else None

    def _update_selected_item_detail(self) -> None:
        row = self._selected_row()
        if row is None:
            self._detail_icon.clear()
            self._detail_icon.setText("?")
            self._detail_title.setText("Select an item")
            self._detail_internal.setText("Recovered item details will appear here.")
            self._detail_category.clear()
            self._detail_summary.clear()
            self._detail_evidence.setText("Select an item to inspect its recovered evidence.")
            self._detail_category_evidence.clear()
            for label in (self._detail_localized, self._detail_materials, self._detail_models, self._detail_icons):
                label.setText("None")
            self._update_buttons()
            return

        item = self._tree_items.get(row.item_id)
        if isinstance(item, QListWidgetItem):
            pixmap = item.icon().pixmap(QSize(112, 112))
            if not pixmap.isNull():
                self._detail_icon.setText("")
                self._detail_icon.setPixmap(pixmap.scaled(112, 112, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self._detail_title.setText(row.display_name or row.internal_name or f"Item {row.item_id}")
        self._detail_internal.setText(f"{row.internal_name or 'Unknown internal name'} (ID {row.item_id})")
        self._detail_category.setText(f"{row.category} / {row.group}")
        self._detail_summary.setText(
            f"{len(row.pac_files):,} PAC link(s), {len(row.icon_paths):,} icon path(s), "
            f"{row.variant_count:,} grouped variant(s)."
        )
        self._detail_evidence.setText(row.evidence or "Recovered item/name evidence.")
        self._detail_category_evidence.setText(
            f"Category evidence: {row.category_evidence}" if row.category_evidence else ""
        )
        self._detail_localized.setText(", ".join(row.localized_names) or "None")
        self._detail_materials.setText(", ".join(row.material_tags) or "None")
        model_lines = [*(f"PAC: {value}" for value in row.pac_files), *(f"Model: {value}" for value in row.model_stems)]
        self._detail_models.setText("\n".join(model_lines) or "None")
        self._detail_icons.setText("\n".join(row.icon_paths) or "None")
        self._update_buttons()

    def _populate_facets(self, result: ItemCatalogSearchResult) -> None:
        category_value = (
            (self._preferred_category, self._preferred_group)
            if self._preferred_category
            else self._category_combo.currentData()
        )
        material_value = self._preferred_material or self._material_combo.currentData()
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
            for facet in result.material_tags[:250]:
                self._material_combo.addItem(f"{facet.value} ({facet.count:,})", facet.value)
            self._restore_combo_data(self._category_combo, category_value)
            self._restore_combo_data(self._material_combo, material_value)
        finally:
            self._category_combo.blockSignals(False)
            self._material_combo.blockSignals(False)
        self._preferred_category = ""
        self._preferred_group = ""
        self._preferred_material = ""

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
        selected = self._item_grid.selectedItems()
        item = selected[0] if selected else self._item_grid.currentItem()
        if item is None:
            return ()
        item_id = item.data(Qt.UserRole)
        return (int(item_id),) if isinstance(item_id, int) else ()

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
            self.accept()
        self._update_buttons()

    def _request_visible_icons(self) -> None:
        if self._icon_request_id or not self._tree_items or self._closing:
            return
        viewport = self._item_grid.viewport()
        active_rect = viewport.rect().adjusted(-176, -184, 176, 368)
        visible_ids: list[int] = []
        deferred_ids: list[int] = []
        for row_index in range(self._item_grid.count()):
            item = self._item_grid.item(row_index)
            item_id = item.data(Qt.UserRole)
            record = self._rows.get(item_id) if isinstance(item_id, int) else None
            if record is not None and record.icon_paths and item_id not in self._icon_requested:
                item_rect = self._item_grid.visualItemRect(item)
                target = visible_ids if item_rect.isValid() and item_rect.intersects(active_rect) else deferred_ids
                target.append(item_id)
        ids = (visible_ids + deferred_ids)[:24]
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
        if self._closing or result.session_id != self._session_id or not self._session_is_current():
            return
        generation = self._icon_generation
        direct: dict[int, str] = {}
        sources: dict[int, str] = {}
        for item in result.items:
            if item.png_path:
                direct[item.item_id] = item.png_path
            elif item.source_path:
                sources[item.item_id] = item.source_path
        self._apply_icons((generation, direct))
        if not sources:
            self._visible_icon_timer.start()
            return
        stop_event = threading.Event()
        thread = QThread(self)
        worker = _IconConversionWorker(sources, stop_event, generation, self.thread())
        worker.moveToThread(thread)
        self._icon_threads.add(thread)
        self._icon_workers[thread] = worker
        self._icon_stop_events.add(stop_event)
        thread.started.connect(worker.run)
        worker.finished.connect(self._apply_icons)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda thread=thread, stop_event=stop_event: self._icon_thread_finished(thread, stop_event))
        thread.start()

    @Slot(object)
    def _apply_icons(self, payload: object) -> None:
        if (
            not isinstance(payload, tuple)
            or len(payload) != 2
            or not isinstance(payload[0], int)
            or not isinstance(payload[1], dict)
            or payload[0] != self._icon_generation
            or self._closing
        ):
            return
        paths = payload[1]
        for item_id, path in paths.items():
            tree_item = self._tree_items.get(int(item_id))
            if not isinstance(tree_item, QListWidgetItem):
                continue
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                continue
            tree_item.setIcon(QIcon(pixmap.scaled(112, 112, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
        if self._selected_row() is not None:
            self._update_selected_item_detail()

    def _icon_thread_finished(self, thread: QThread, stop_event: threading.Event) -> None:
        if not thread.wait(0):
            QTimer.singleShot(0, lambda: self._icon_thread_finished(thread, stop_event))
            return
        self._icon_threads.discard(thread)
        self._icon_workers.pop(thread, None)
        self._icon_stop_events.discard(stop_event)
        thread.deleteLater()
        if not self._closing:
            self._visible_icon_timer.start()
        self._release_if_finished()

    def _update_buttons(self) -> None:
        busy = bool(self._search_request_id or self._scope_request_id)
        self._previous_button.setEnabled(not busy and self._page_start > 0)
        self._next_button.setEnabled(not busy and self._page_start + self._page_size < self._total_matches)
        has_selection = bool(self._selected_item_ids())
        self._exact_button.setEnabled(not busy and has_selection)
        self._related_button.setEnabled(not busy and has_selection)

    def closeEvent(self, event: object) -> None:
        self._save_settings()
        self._closing = True
        self._search_timer.stop()
        self._visible_icon_timer.stop()
        for attribute in ("_search_request_id", "_scope_request_id"):
            self._cancel_request(attribute)
        self._cancel_icon_loading()
        self._disconnect_service()
        self._release_if_finished()
        super().closeEvent(event)  # type: ignore[arg-type]

    def _save_settings(self) -> None:
        if self._settings is None:
            return
        category, group, material = self._selected_filters()
        try:
            self._settings.setValue("ui/item_finder_geometry", self.saveGeometry())
            if self._item_splitter is not None:
                self._settings.setValue("ui/item_finder_splitter_sizes", self._item_splitter.sizes())
            self._settings.setValue("ui/item_finder_search_text", self._search_edit.text())
            self._settings.setValue("ui/item_finder_category", category or "")
            self._settings.setValue("ui/item_finder_group", group or "")
            self._settings.setValue("ui/item_finder_material_tag", material or "")
        except Exception:
            pass

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
