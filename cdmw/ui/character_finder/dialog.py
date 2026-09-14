"""Paged Body & Face Finder with its own resident interactive preview."""

from __future__ import annotations

from html import escape
from collections import OrderedDict
from dataclasses import replace
from pathlib import Path
from PySide6.QtCore import QEvent, QProcess, QSize, QTimer, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit,
    QListView, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QSplitter, QTabBar, QTabWidget, QTextBrowser, QVBoxLayout, QWidget,
)

from cdmw.domain.archives.character_catalogue import (
    BuildCharacterCatalogResult, CharacterCatalogSearchRequest, CharacterCatalogSearchResult,
    CharacterCatalogDetailRequest, CharacterCatalogDetailResult,
    CharacterCatalogScopeRequest, CharacterCatalogScopeResult,
)
from cdmw.domain.character_finder import CHARACTER_FINDER_CACHED_PAGES, CHARACTER_FINDER_LOOKAHEAD_PAGES
from cdmw.ui.character_finder.preview_controller import CharacterFinderPreviewController
from cdmw.ui.preview.rust_host import RustPreviewHostFrame
from cdmw.ui.shell.close_controller import register_transient_worker_controller


ROLE_LABELS = {"body": "Body", "whole_character": "Whole character", "head": "Head",
               "facial_detail": "Facial detail", "hair": "Hair", "beard": "Beard", "unclassified": "Unclassified"}
SOURCE_LABELS = {"humanoid": "Humanoids", "1_pc": "Player families", "2_mon": "Creatures", "3_npc": "NPCs", "4_riding": "Mounts",
                 "6_object": "Objects", "7_montower": "Towers", "unknown": "Unknown"}
STATUS_LABELS = {"base_appearance": "Base appearance", "textures_unavailable": "Textures unavailable",
                 "unresolved_model": "Unresolved model"}
RESOLUTION_LABELS = {"resolved": "Resolved", "inferred": "Inferred", "ambiguous": "Ambiguous", "unresolved": "Unresolved"}


class CharacterFinderDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self._window = window
        self._service = window.archive.archive_catalogue_service
        self._bridge = window.archive.archive_remote_bridge
        session = self._bridge.current_session
        if session is None:
            raise ValueError("Scan the archives before opening Body & Face Finder.")
        self._session_id, self._fingerprint = session.session_id, session.fingerprint
        self._settings = getattr(window.shell, "settings", None)
        self._warmup = getattr(window.archive, "archive_character_finder_warmup_controller", None)
        self._closing = False
        self._invalid = False
        self._requests = {}
        self._active_search = None
        self._prefetch_search = None
        self._prefetch_failed = set()
        self._search_cache = OrderedDict()
        self._rows = {}
        self._items = {}
        self._details = None
        self._page_start = 0
        self._total = 0
        self._related_key = None
        self._select_after_search = None
        self._pending_package = None
        self._hair_preparation = None
        self._hair_handoff = None
        self._shown_key = ""
        self._thumbs = OrderedDict()
        self._thumbnail_icons = OrderedDict()
        self._build_ui()
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(220)
        self._search_timer.timeout.connect(self._search)
        self._visible_timer = QTimer(self)
        self._visible_timer.setSingleShot(True)
        self._visible_timer.setInterval(80)
        self._visible_timer.timeout.connect(self._visible)
        self._release_timer = QTimer(self)
        self._release_timer.setInterval(40)
        self._release_timer.timeout.connect(self._release)
        self._preview = CharacterFinderPreviewController(self._service, fingerprint=self._fingerprint,
            cache_root=Path(window.archive._native_preview_package_cache_root()),
            settings=window.archive._current_model_preview_render_settings(), parent=self)
        self._preview.package_ready.connect(self._package_ready)
        self._preview.thumbnail_ready.connect(self._thumbnail_ready)
        self._preview.failed.connect(self._preview_failed)
        self._preview.idle.connect(self._release)
        self._preview.idle.connect(self._preload_next_page)
        self._host.controller.package_applied.connect(self._package_applied)
        self._host.controller.package_failed.connect(self._package_failed)
        self._search_edit.textChanged.connect(self._queue_search)
        self._tabs.currentChanged.connect(self._tab_changed)
        self._view.currentIndexChanged.connect(self._queue_search)
        for combo in self._filters.values():
            combo.currentIndexChanged.connect(self._queue_search)
        self._grid.currentItemChanged.connect(self._selection_changed)
        self._grid.verticalScrollBar().valueChanged.connect(lambda: self._visible_timer.start())
        self._grid.viewport().installEventFilter(self)
        self._service.result_ready.connect(self._result)
        self._service.request_failed.connect(self._failed)
        self._service.progress.connect(self._progress)
        self._service.session_published.connect(self._session_changed)
        self._service.worker_crashed.connect(self._worker_crashed)
        self._restore()
        available = self.screen().availableGeometry()
        self.resize(min(self.width(), available.width() - 24), min(self.height(), available.height() - 60))
        register_transient_worker_controller(window, self)
        if self._warmup is not None:
            self._warmup.pause(self)
        QTimer.singleShot(0, self._build)

    def _build_ui(self):
        self.setWindowTitle("Body & Face Finder")
        self.resize(1360, 900)
        self.setMinimumSize(1040, 690)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        intro = QLabel("Browse character bodies, faces and appearance variants from the installed archives.")
        intro.setObjectName("HintLabel")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        row = QHBoxLayout()
        self._tabs = QTabBar()
        self._tabs.addTab("Bodies")
        self._tabs.addTab("Faces")
        row.addWidget(self._tabs)
        self._view = QComboBox()
        self._view.addItem("Unique assets", "assets")
        self._view.addItem("Appearance variants", "appearances")
        row.addWidget(self._view)
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search names, character IDs or paths")
        self._search_edit.setClearButtonEnabled(True)
        row.addWidget(self._search_edit, 1)
        clear = QPushButton("Clear filters")
        clear.clicked.connect(self._clear_filters)
        row.addWidget(clear)
        layout.addLayout(row)
        filters = QHBoxLayout()
        self._filters = {}
        for field, label in (("role", "All components"), ("source_group", "All types"),
                             ("body_family", "All body families"), ("resolution", "All resolution states")):
            combo = QComboBox()
            combo.setMinimumWidth(145)
            combo.addItem(label, "")
            combo.setProperty("allLabel", label)
            self._filters[field] = combo
            filters.addWidget(combo, 1)
        layout.addLayout(filters)
        self._relation_banner = QPushButton("Show all results")
        self._relation_banner.setVisible(False)
        self._relation_banner.clicked.connect(self._clear_filters)
        layout.addWidget(self._relation_banner)
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(self._splitter, 1)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 4, 0)
        self._grid = QListWidget()
        self._grid.setProperty("_i18n_translate_items", True)
        self._grid.setObjectName("CharacterFinderGrid")
        self._grid.setViewMode(QListView.ViewMode.IconMode)
        self._grid.setResizeMode(QListView.ResizeMode.Adjust)
        self._grid.setMovement(QListView.Movement.Static)
        self._grid.setIconSize(QSize(158, 158))
        self._grid.setGridSize(QSize(180, 254))
        self._grid.setSpacing(6)
        self._grid.setWordWrap(False)
        self._grid.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self._grid.setUniformItemSizes(True)
        left_layout.addWidget(self._grid, 1)
        paging = QHBoxLayout()
        self._previous = QPushButton("Previous")
        self._previous.clicked.connect(lambda: self._page(-1))
        self._next_button = QPushButton("Next")
        self._next_button.clicked.connect(lambda: self._page(1))
        self._page_label = QLabel()
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        paging.addWidget(self._previous)
        paging.addWidget(self._page_label, 1)
        paging.addWidget(self._next_button)
        left_layout.addLayout(paging)
        self._splitter.addWidget(left)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 0, 0, 0)
        self._title = QLabel("Select a body or face")
        font = self._title.font()
        font.setPointSize(font.pointSize() + 2)
        font.setBold(True)
        self._title.setFont(font)
        self._title.setWordWrap(True)
        right_layout.addWidget(self._title)
        self._preview_status = QLabel("The interactive preview appears here.")
        self._preview_status.setWordWrap(True)
        self._preview_status.setObjectName("HintLabel")
        right_layout.addWidget(self._preview_status)
        self._host = RustPreviewHostFrame(right, terminate_on_close=True,
            ui_localizer=getattr(self._window, "ui_localizer", None))
        self._host.setMinimumSize(360, 250)
        right_layout.addWidget(self._host, 3)
        preview_tools = QHBoxLayout()
        reset = QPushButton("Reset view")
        reset.clicked.connect(self._reset_view)
        preview_tools.addWidget(reset)
        preview_tools.addStretch(1)
        right_layout.addLayout(preview_tools)
        self._info_tabs = QTabWidget()
        self._relations = QListWidget()
        self._relations.setProperty("_i18n_translate_items", True)
        self._relations.itemActivated.connect(self._navigate)
        self._relations.itemClicked.connect(self._navigate)
        self._info_tabs.addTab(self._relations, "Used by / Components")
        self._evidence = QTextBrowser()
        self._evidence.setOpenExternalLinks(False)
        self._info_tabs.addTab(self._evidence, "Details")
        right_layout.addWidget(self._info_tabs, 2)
        actions = QHBoxLayout()
        self._exact = QPushButton("Show exact files")
        self._exact.clicked.connect(lambda: self._scope(False))
        self._related = QPushButton("Show related files")
        self._related.clicked.connect(lambda: self._scope(True))
        self._copy = QPushButton("Copy path")
        self._copy.clicked.connect(self._copy_path)
        self._create_hair = QPushButton("Create Hair")
        self._create_hair.clicked.connect(lambda: self._start_hair("generated"))
        self._edit_hair = QPushButton("Edit Hair")
        self._edit_hair.clicked.connect(lambda: self._start_hair("existing"))
        for button in (self._exact, self._related, self._copy, self._create_hair, self._edit_hair):
            button.setEnabled(False)
            actions.addWidget(button)
        right_layout.addLayout(actions)
        self._splitter.addWidget(right)
        self._splitter.setSizes([600, 670])
        self._status = QLabel("Indexing bodies and faces…")
        self._status.setObjectName("HintLabel")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

    def _restore(self):
        self._set_filter("source_group", "humanoid")
        if self._settings is None:
            return
        self._tabs.setCurrentIndex(1 if self._settings.value("ui/character_finder/tab", "bodies") == "faces" else 0)
        self._view.setCurrentIndex(1 if self._settings.value("ui/character_finder/view", "assets") == "appearances" else 0)
        for field, combo in self._filters.items():
            value = str(self._settings.value("ui/character_finder/" + field, "") or "")
            if field == "source_group":
                # Legacy empty values were the old all-types default. Preserve an
                # intentional all-types choice with an explicit persisted value.
                value = "" if value == "all" else value or "humanoid"
            if field == "role" and self._tabs.currentIndex() and value == "head":
                value = ""
            self._set_filter(field, value)
        geometry = self._settings.value("ui/character_finder/geometry")
        if geometry:
            self.restoreGeometry(geometry)
        splitter = self._settings.value("ui/character_finder/splitter")
        if splitter:
            self._splitter.restoreState(splitter)

    def _save(self):
        if self._settings is not None:
            for field, combo in self._filters.items():
                value = combo.currentData() or ("all" if field == "source_group" else "")
                self._settings.setValue("ui/character_finder/" + field, value)
            self._settings.setValue("ui/character_finder/tab", "faces" if self._tabs.currentIndex() else "bodies")
            self._settings.setValue("ui/character_finder/view", self._view.currentData())
            self._settings.setValue("ui/character_finder/geometry", self.saveGeometry())
            self._settings.setValue("ui/character_finder/splitter", self._splitter.saveState())

    def _set_filter(self, field, value):
        combo = self._filters[field]
        index = combo.findData(value)
        if index < 0:
            labels = SOURCE_LABELS if field == "source_group" else ROLE_LABELS if field == "role" else {}
            combo.addItem(labels.get(value, value), value)
            index = combo.count() - 1
        combo.setCurrentIndex(index)

    def _tab_changed(self, *_args):
        combo = self._filters["role"]
        label = "Head" if self._tabs.currentIndex() else "All components"
        combo.setProperty("allLabel", label)
        combo.setItemText(0, label)
        combo.setCurrentIndex(0)
        self._queue_search()

    def _cancel(self, kind):
        request = self._requests.pop(kind, None)
        if request:
            self._service.cancel(request)

    def _build(self):
        if self._closing or self._invalid:
            return
        self._search_timer.stop()
        cached = self._warmup.cached_summary(self._session_id) if self._warmup is not None else None
        if cached is not None:
            self._catalogue_summary = cached
            self._search()
            return
        try:
            self._requests["build"] = self._service.build_character_catalog(self._session_id,
                ui_generation=self._bridge.controller.generation)
        except Exception as error:
            self._status.setText(str(error))

    def _queue_search(self, *_args):
        if self._closing or self._invalid:
            return
        self._page_start = 0
        self._cancel("search")
        self._cancel("detail")
        self._cancel("scope")
        self._cancel("prefetch")
        self._prefetch_search = None
        self._prefetch_failed.clear()
        self._active_search = None
        self._details = None
        self._pending_package = None
        self._preview.clear_page()
        self._buttons()
        self._search_timer.start()

    def _search(self, *, keep_prepared=False):
        if self._closing or self._invalid or "build" in self._requests:
            return
        self._cancel("search")
        self._cancel("detail")
        if not keep_prepared:
            self._preview.clear_page()
        self._status.setText("Searching character catalogue…")
        request = CharacterCatalogSearchRequest(self._session_id, query=self._search_edit.text(),
            view=self._view.currentData(), tab="faces" if self._tabs.currentIndex() else "bodies",
            related_key=self._related_key, page_start=self._page_start,
            **{key: combo.currentData() or None for key, combo in self._filters.items()})
        self._active_search = request
        self._prefetch_failed.clear()
        cached = self._cached_search(request)
        if cached is not None:
            self._populate(cached)
            self._buttons()
            return
        if self._prefetch_search == request and "prefetch" in self._requests:
            # Next was clicked before the background catalogue request returned.
            # Promote that exact request instead of cancelling and repeating it.
            self._requests["search"] = self._requests.pop("prefetch")
            self._prefetch_search = None
            self._buttons()
            return
        self._cancel("prefetch")
        self._prefetch_search = None
        try:
            self._requests["search"] = self._service.search_character_catalog(request, ui_generation=self._bridge.controller.generation)
        except Exception as error:
            self._status.setText(str(error))
        self._buttons()

    def _cached_search(self, request):
        cached = self._search_cache.get(request)
        if cached is not None:
            self._search_cache.move_to_end(request)
            return cached
        return self._warmup.cached_search(request) if self._warmup is not None else None

    def _remember_search(self, request, result):
        if request is None:
            return
        self._search_cache[request] = result
        self._search_cache.move_to_end(request)
        while len(self._search_cache) > CHARACTER_FINDER_CACHED_PAGES:
            self._search_cache.popitem(last=False)

    def _preload_next_page(self):
        if (self._closing or self._invalid or self._active_search is None
                or "search" in self._requests or "build" in self._requests):
            return
        wanted = [replace(self._active_search, page_start=self._page_start + offset * 72)
            for offset in range(1, CHARACTER_FINDER_LOOKAHEAD_PAGES + 1)
            if self._page_start + offset * 72 < self._total]
        self._prefetch_failed.intersection_update(wanted)
        if self._prefetch_search not in wanted:
            self._cancel("prefetch")
            self._prefetch_search = None
        pages = [(request, self._cached_search(request)) for request in wanted]
        rows = tuple(row for _, page in pages if page is not None for row in page.rows)
        self._preview.prefetch(rows, session_id=self._session_id, generation=self._bridge.controller.generation)
        if "prefetch" in self._requests:
            return
        for request, cached in pages:
            if cached is not None or request in self._prefetch_failed:
                continue
            self._prefetch_search = request
            try:
                self._requests["prefetch"] = self._service.search_character_catalog(
                    request, ui_generation=self._bridge.controller.generation)
                return  # At most one lookahead catalogue request is outstanding.
            except Exception:
                self._prefetch_failed.add(request)
        self._prefetch_search = None

    def _result(self, request_id, _operation, result):
        if self._closing or self._invalid or getattr(result, "session_id", None) != self._session_id:
            return
        kind = next((kind for kind, token in self._requests.items() if token == request_id), None)
        if kind is None:
            return
        self._requests.pop(kind)
        if kind == "build" and isinstance(result, BuildCharacterCatalogResult):
            self._catalogue_summary = result
            self._search()
        elif kind == "search" and isinstance(result, CharacterCatalogSearchResult):
            self._populate(result)
        elif kind == "prefetch" and isinstance(result, CharacterCatalogSearchResult):
            self._remember_search(self._prefetch_search, result)
            self._prefetch_search = None
            self._preload_next_page()
        elif kind == "detail" and isinstance(result, CharacterCatalogDetailResult):
            if result.row.key == self._selected_key():
                self._show_detail(result)
        elif kind == "scope" and isinstance(result, CharacterCatalogScopeResult):
            if self._bridge.current_session is not None and self._bridge.current_session.session_id == self._session_id:
                if self._bridge.apply_entry_id_scope(result.entry_ids, label=self.windowTitle(),
                    preferred_prefab_stems=tuple(c.name for c in self._details.components) if self._details else ()):
                    self.accept()
        self._buttons()

    def _populate(self, result):
        self._remember_search(self._active_search, result)
        self._total = result.total_matches
        self._rows = {row.key: row for row in result.rows}
        self._items.clear()
        self._grid.blockSignals(True)
        self._grid.clear()
        for row in result.rows:
            text = row.label + "\n" + ROLE_LABELS.get(row.role, row.role) + "\n" + STATUS_LABELS.get(row.preview_status, row.preview_status)
            if row.embedded_face:
                text += "\nEmbedded face"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, row.key)
            item.setToolTip(row.label + "\n" + row.path + "\n" + row.evidence)
            item.setSizeHint(QSize(176, 250))
            thumb = self._thumbs.get(row.key)
            if thumb:
                self._thumbs.move_to_end(row.key)
                item.setIcon(self._thumbnail_icon(thumb))
            else:
                placeholder = QPixmap(158, 158)
                placeholder.fill(self._grid.palette().alternateBase().color())
                item.setIcon(QIcon(placeholder))
            self._grid.addItem(item)
            self._items[row.key] = item
        self._grid.blockSignals(False)
        for field, combo in self._filters.items():
            value = combo.currentData() or ""
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(combo.property("allLabel"), "")
            labels = ROLE_LABELS if field == "role" else SOURCE_LABELS if field == "source_group" else RESOLUTION_LABELS if field == "resolution" else {}
            for facet in result.facets:
                if facet.field == field:
                    label = f"{labels.get(facet.value, facet.value)} ({facet.count:,})"
                    if field == "role" and self._tabs.currentIndex() and facet.value == "head":
                        combo.setItemText(0, label)
                    else:
                        combo.addItem(label, facet.value)
            index = combo.findData(value)
            if index < 0 and value:
                combo.addItem(labels.get(value, value) + " (0)", value)
                index = combo.count() - 1
            combo.setCurrentIndex(max(0, index))
            combo.blockSignals(False)
        self._page_label.setText(f"{self._page_start + 1 if result.rows else 0:,}–{self._page_start + len(result.rows):,} of {self._total:,}")
        self._status.setText(" · ".join(result.warnings) if result.warnings else "Select a result to preview it. Thumbnails load as you browse.")
        # Promote preloaded jobs before selection signals can reprioritize them.
        self._preview.visible(result.rows, session_id=self._session_id, generation=self._bridge.controller.generation)
        selected = self._items.get(self._select_after_search) or (self._grid.item(0) if result.rows else None)
        self._select_after_search = None
        if selected:
            self._grid.setCurrentItem(selected)
        else:
            self._details = None
            self._title.setText("No matching bodies or faces")
        self._visible()
        self._visible_timer.start()
        self._preload_next_page()

    def _selected_key(self):
        item = self._grid.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selection_changed(self, *_args):
        self._cancel("detail")
        self._cancel("scope")
        self._details = None
        self._pending_package = None
        key = self._selected_key()
        if key is None or self._closing or self._invalid:
            self._buttons()
            return
        self._visible_timer.start()
        self._title.setText(self._rows[key].label)
        self._preview_status.setText("Preparing preview…")
        self._relations.clear()
        self._evidence.clear()
        cached = self._preview.cached_detail(key, self._session_id)
        if cached is None and self._warmup is not None:
            cached = self._warmup.cached_detail(key, self._session_id)
        if cached is not None:
            self._show_detail(cached)
            self._buttons()
            return
        try:
            self._requests["detail"] = self._service.get_character_catalog_detail(CharacterCatalogDetailRequest(self._session_id, key),
                ui_generation=self._bridge.controller.generation)
        except Exception as error:
            self._preview_status.setText(str(error))
        self._buttons()

    def _show_detail(self, detail):
        self._details = detail
        row = detail.row
        self._preview_status.setText(STATUS_LABELS.get(row.preview_status, row.preview_status) +
            (" · Embedded face; preview uses the owning body." if row.embedded_face else ""))
        self._relations.clear()
        for owner in detail.characters:
            item = QListWidgetItem(f"{owner.display_name or owner.internal_name} · ID {owner.character_id}")
            item.setToolTip(owner.evidence)
            self._relations.addItem(item)
        for related in detail.related:
            item = QListWidgetItem(f"{ROLE_LABELS.get(related.role, related.role)} · {related.label}  →")
            item.setData(Qt.ItemDataRole.UserRole, related)
            item.setToolTip(related.path)
            self._relations.addItem(item)
        if not detail.characters and not detail.related:
            self._relations.addItem("No resolved character or appearance links.")
        content = [f"<b>{escape(row.path)}</b>", f"<p>{escape(RESOLUTION_LABELS.get(row.resolution, row.resolution))} · {escape(row.evidence)}</p>"]
        content += ["<p>" + escape(line) + "</p>" for line in detail.evidence]
        content += [f"<p>{escape(f.relation)} · {escape(f.path)}<br><small>{escape(f.source_pamt)}</small></p>" for f in detail.files]
        if detail.truncated:
            content.append(f"<p>Details are bounded: {detail.total_file_count:,} files, {detail.total_related_count:,} related results, {detail.total_character_count:,} characters. Use Show related files for the full bounded archive scope.</p>")
        self._evidence.setHtml("".join(content))
        self._preview.select(detail, self._bridge.controller.generation)
        self._visible_timer.start()

    def _navigate(self, item):
        target = item.data(Qt.ItemDataRole.UserRole)
        if target is None or self._details is None:
            return
        self._related_key = self._details.row.key
        self._select_after_search = target.key
        self._view.setCurrentIndex(self._view.findData(target.view))
        self._tabs.setCurrentIndex(1 if target.role in {"head", "facial_detail", "hair", "beard"} else 0)
        for combo in self._filters.values():
            combo.setCurrentIndex(0)
        if target.role in {"unclassified", "facial_detail", "hair", "beard"}:
            self._set_filter("role", target.role)
        self._search_edit.setText(target.path)
        self._relation_banner.setText("Related results · Show all results")
        self._relation_banner.setVisible(True)
        self._queue_search()

    def _clear_filters(self):
        self._related_key = None
        self._relation_banner.setVisible(False)
        self._search_edit.clear()
        for combo in self._filters.values():
            combo.setCurrentIndex(0)
        self._set_filter("source_group", "humanoid")
        self._queue_search()

    def _reset_view(self):
        self._host.request_canonical_view()

    def _page(self, direction):
        self._page_start = max(0, self._page_start + direction * 72)
        self._cancel("scope")
        self._search(keep_prepared=True)

    def _scope(self, related):
        if self._details is None:
            return
        self._cancel("scope")
        self._requests["scope"] = self._service.scope_character_catalog(CharacterCatalogScopeRequest(
            self._session_id, self._details.row.key, related), ui_generation=self._bridge.controller.generation)
        self._buttons()

    def _copy_path(self):
        if self._details is not None:
            QApplication.clipboard().setText(self._details.row.path)

    def _hair_model(self):
        if self._details is None:
            return None
        models = [item for item in self._details.models if
            "1_pc/2_phw/head/hair/" in item.path.casefold() and item.path.casefold().endswith("_player.pac")]
        return models[0] if len(models) == 1 else None

    def _start_hair(self, mode):
        model = self._hair_model()
        if model is None or self._closing or self._invalid:
            return
        from cdmw.ui.character_finder.preview_preparation import CharacterPreviewPreparation
        if self._hair_preparation is None:
            self._hair_preparation = CharacterPreviewPreparation(self._service, self)
            self._hair_preparation.ready.connect(self._hair_prepared)
            self._hair_preparation.failed.connect(self._hair_failed)
        self._hair_handoff = (self._details.row.key, model.entry_id, mode)
        detail = replace(self._details, models=(model,),
            components=tuple(c for c in self._details.components if model.entry_id in c.model_entry_ids))
        self._status.setText("Preparing hair and its materials for Mesh Editor…")
        self._hair_preparation.start(detail, self._bridge.controller.generation)
        self._buttons()

    def _hair_failed(self, _token, message):
        self._hair_handoff = None
        if not self._closing:
            self._status.setText(message)
            self._buttons()

    def _hair_prepared(self, token, inputs):
        pending, self._hair_handoff = self._hair_handoff, None
        if (pending is None or self._closing or self._invalid or token != self._bridge.controller.generation
                or self._selected_key() != pending[0] or inputs.detail.session_id != self._session_id):
            if not self._closing:
                self._buttons()
            return
        if not inputs.dependencies_complete:
            self._hair_failed(token, "The hairstyle's material dependencies are incomplete.")
            return
        from cdmw.ui.archive_browser.workflow_dependencies import ArchiveWorkflowDependencyContext
        target = inputs.entries_by_id[pending[1]]
        paths, names = {}, {}
        for entry in inputs.entries:
            paths.setdefault(entry.path.casefold(), []).append(entry)
            names.setdefault(entry.basename.casefold(), []).append(entry)
        dependencies = ArchiveWorkflowDependencyContext(target, inputs.entries, paths, names, True)
        shell = self._window.shell
        if not shell._prepare_mesh_editor_archive_launch(target):
            self._buttons()
            return
        tab = shell.mesh_editor_tab
        tab._pending_hair_start = (target.identity, pending[2])
        tab.open_archive_session(target, archive_dependencies=dependencies)
        shell._activate_tool_widget(tab)
        self._status.setText("Hair opened in Mesh Editor. Choose its head reference there.")
        self._buttons()
        self.hide()

    def _visible(self):
        if self._closing or self._invalid or "search" in self._requests:
            return
        viewport = self._grid.viewport().rect()
        visible = {key for key, item in self._items.items() if self._grid.visualItemRect(item).intersects(viewport)}
        rows = [self._rows[key] for key in self._items if key in visible]
        rows.extend(self._rows[key] for key in self._items if key not in visible)
        self._preview.visible(rows, session_id=self._session_id, generation=self._bridge.controller.generation,
            priority_keys=visible or None)

    def eventFilter(self, watched, event):
        if watched is self._grid.viewport() and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            if hasattr(self, "_visible_timer"):
                self._visible_timer.start()
        return super().eventFilter(watched, event)

    def _package_ready(self, key, result):
        if self._closing or key != self._selected_key():
            return
        self._pending_package = (key, result)
        if not self._host.load_package(result.package_path, reset_view=True):
            self._preview_failed(key, "The interactive preview could not load this package.")

    def _package_applied(self, path, _generation):
        pending = self._pending_package
        if self._closing or pending is None or pending[0] != self._selected_key():
            return
        key, result = pending
        if Path(path) != Path(result.package_path):
            return
        self._shown_key = key
        status = STATUS_LABELS.get(result.status, result.status)
        if self._details and self._details.row.embedded_face:
            status += " · Embedded face; preview uses the owning body."
        self._preview_status.setText(status)
        if result.notes:
            self._evidence.append("<p><b>Preview details</b></p>" + "".join("<p>" + escape(note) + "</p>" for note in result.notes))

    def _package_failed(self, _path, _generation, message):
        if self._pending_package:
            self._preview_failed(self._pending_package[0], message)

    def _thumbnail_icon(self, path):
        icon = self._thumbnail_icons.get(path)
        if icon is None:
            icon = QIcon(path)
            if icon.isNull():
                return icon
            self._thumbnail_icons[path] = icon
        self._thumbnail_icons.move_to_end(path)
        while len(self._thumbnail_icons) > 72 * CHARACTER_FINDER_CACHED_PAGES:
            self._thumbnail_icons.popitem(last=False)
        return icon

    def _thumbnail_ready(self, key, result):
        if self._closing:
            return
        if result.thumbnail_path:
            self._thumbs[key] = result.thumbnail_path
            self._thumbs.move_to_end(key)
            while len(self._thumbs) > 72 * CHARACTER_FINDER_CACHED_PAGES:
                self._thumbs.popitem(last=False)
            icon = self._thumbnail_icon(result.thumbnail_path)
            item = self._items.get(key)
            if item:
                item.setIcon(icon)
                row = self._rows[key]
                text = row.label + "\n" + ROLE_LABELS.get(row.role, row.role) + "\n" + STATUS_LABELS.get(result.status, result.status)
                text += "\nEmbedded face" if row.embedded_face else ""
                # UiLocalizer retains the English list-item source at this role.
                item.setData(int(Qt.ItemDataRole.UserRole) + 1000, text)
                item.setText(text)

    def _preview_failed(self, key, message):
        if not self._closing and key == self._selected_key():
            suffix = " The previous preview is still shown." if self._shown_key and self._shown_key != key else ""
            self._preview_status.setText(message + suffix)
        item = self._items.get(key)
        if item:
            item.setToolTip(item.toolTip() + "\n" + message)

    def _failed(self, request, error):
        kind = next((kind for kind, token in self._requests.items() if token == request), None)
        if kind is not None and not self._closing:
            self._requests.pop(kind)
            if kind == "prefetch":
                if self._prefetch_search is not None:
                    self._prefetch_failed.add(self._prefetch_search)
                self._prefetch_search = None
                self._preload_next_page()
                return
            self._status.setText(str(getattr(error, "message", error)))
            self._buttons()

    def _progress(self, request, update):
        if request in self._requests.values() and request != self._requests.get("prefetch") and not self._closing:
            self._status.setText((update.current_item or "Indexing bodies and faces…") +
                                 (f" · {update.completed:,}/{update.total:,}" if update.total else ""))

    def _buttons(self):
        busy = bool(self._requests.get("search") or self._requests.get("build") or self._requests.get("scope"))
        self._previous.setEnabled(not busy and not self._invalid and self._page_start > 0)
        self._next_button.setEnabled(not busy and not self._invalid and self._page_start + 72 < self._total)
        for button in (self._exact, self._related, self._copy):
            button.setEnabled(self._details is not None and not busy and not self._invalid)
        for button in (self._create_hair, self._edit_hair):
            button.setEnabled(self._hair_model() is not None and not busy and not self._invalid and self._hair_handoff is None)

    def _session_changed(self, session):
        if session.session_id != self._session_id or session.fingerprint != self._fingerprint:
            self._invalidate("The archive changed. Close and reopen this finder for the current catalogue.")

    def _worker_crashed(self, message):
        self._invalidate(message)

    def _invalidate(self, message):
        self._invalid = True
        self._search_timer.stop()
        self._visible_timer.stop()
        for kind in tuple(self._requests):
            self._cancel(kind)
        self._preview.clear_page()
        self._search_cache.clear()
        self._thumbs.clear()
        self._thumbnail_icons.clear()
        self._status.setText(message)
        self._buttons()

    def iter_shutdown_workers(self):
        yield from self._preview.iter_shutdown_workers()

    def request_shutdown(self):
        self.close()

    def _shutdown(self):
        if self._closing:
            return
        self._save()
        self._closing = True
        self._search_timer.stop()
        self._visible_timer.stop()
        for kind in tuple(self._requests):
            self._cancel(kind)
        self._preview.shutdown()
        if self._hair_preparation is not None:
            self._hair_preparation.cancel()
        self._hair_handoff = None
        self._host.controller.shutdown()
        for signal, slot in ((self._service.result_ready, self._result), (self._service.request_failed, self._failed),
                             (self._service.progress, self._progress), (self._service.session_published, self._session_changed),
                             (self._service.worker_crashed, self._worker_crashed)):
            signal.disconnect(slot)
        self._release_timer.start()

    def done(self, result):
        self._shutdown()
        super().done(result)

    def closeEvent(self, event):
        self._shutdown()
        super().closeEvent(event)

    def _release(self):
        if not self._closing or self._preview.busy:
            return
        if any(p.state() != QProcess.ProcessState.NotRunning for p in self.findChildren(QProcess)):
            return
        self._release_timer.stop()
        if self._warmup is not None:
            self._warmup.resume(self)
        retained = getattr(self._window, "_character_finder_dialogs", None)
        if retained is not None:
            retained.discard(self)
        self.deleteLater()


def show_character_finder(window):
    service = getattr(window.archive, "archive_catalogue_service", None)
    if service is None or not service.character_catalog_available:
        QMessageBox.information(window, "Body & Face Finder",
            "Body & Face Finder requires an updated archive helper. Rebuild the archive worker or install a current CDMW build, then reopen the archives.")
        return
    retained = getattr(window, "_character_finder_dialogs", None)
    if retained is None:
        retained = set()
        setattr(window, "_character_finder_dialogs", retained)
    for dialog in retained:
        if not dialog._closing and not dialog._invalid:
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            return
    dialog = CharacterFinderDialog(window)
    retained.add(dialog)
    dialog.show()
