"""Role-limited character choices with the real textured Finder preview path."""
from dataclasses import replace
from pathlib import Path
from PySide6.QtCore import QProcess, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout
from cdmw.domain.archives.character_catalogue import CharacterCatalogSearchRequest, CharacterCatalogSearchResult, CharacterCatalogDetailRequest, CharacterCatalogDetailResult
from cdmw.ui.character_finder.preview_controller import CharacterFinderPreviewController
from cdmw.ui.character_finder.preview_preparation import CharacterPreviewPreparation
from cdmw.ui.archive_browser.workflow_dependencies import ArchiveWorkflowDependencyContext
from cdmw.ui.preview.rust_host import RustPreviewHostFrame
from cdmw.ui.shell.close_controller import register_transient_worker_controller


class HairReferencePickerDialog(QDialog):
    preparation_failed = Signal(str)

    def __init__(self, owner, role, *, styles=()):
        super().__init__(owner)
        if role not in {"head", "body", "hair"}:
            raise ValueError("Unknown Hair reference role")
        self._owner, self._role = owner, role
        self._service = owner.archive.archive_catalogue_service
        session = self._service.current_session
        if session is None:
            raise ValueError("Load the archive catalogue first.")
        self._session_id = session.session_id
        self._closed, self._generation, self._page_start = False, 1, 0
        self._requests, self._rows, self._details = {}, {}, {}
        self._styles = tuple(styles)
        self.auto_choose_first = False
        self.selected_entry = self.selected_dependencies = None
        self.setWindowTitle({"head": "Choose a compatible head", "body": "Choose a base body", "hair": "Choose a Damiane hairstyle"}[role])
        self.resize(1020, 680)
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter these compatible choices")
        layout.addWidget(self.search)
        row = QHBoxLayout()
        self.grid = QListWidget()
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setIconSize(QSize(140, 140))
        self.grid.setWordWrap(True)
        row.addWidget(self.grid, 1)
        self.host = RustPreviewHostFrame(self, terminate_on_close=True, ui_localizer=getattr(owner, "ui_localizer", None))
        row.addWidget(self.host, 1)
        layout.addLayout(row, 1)
        self.status = QLabel("Loading compatible choices…")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.previous = QPushButton("Previous")
        self.next = QPushButton("Next")
        self.choose = QPushButton("Use selection")
        self.choose.setEnabled(False)
        cancel = QPushButton("Cancel")
        for button in (self.previous, self.next, self.choose, cancel): buttons.addWidget(button)
        layout.addLayout(buttons)
        self.previous.clicked.connect(lambda: self._page(-1))
        self.next.clicked.connect(lambda: self._page(1))
        cancel.clicked.connect(self.reject)
        self.choose.clicked.connect(self._choose)
        self.grid.currentItemChanged.connect(self._select)
        self._timer = QTimer(self); self._timer.setSingleShot(True); self._timer.setInterval(200)
        self._timer.timeout.connect(self._search)
        self.search.textChanged.connect(self._filter_changed)
        self._preview = CharacterFinderPreviewController(self._service, fingerprint=session.fingerprint,
            cache_root=Path(owner.archive._native_preview_package_cache_root()),
            settings=owner.archive._current_model_preview_render_settings(), parent=self)
        self._preview.thumbnail_ready.connect(self._thumbnail)
        self._preview.package_ready.connect(self._package)
        self._preview.failed.connect(lambda _key, message: self.status.setText(message) if not self._closed else None)
        self._prepare = CharacterPreviewPreparation(self._service, self)
        self._prepare.ready.connect(self._prepared)
        self._prepare.failed.connect(lambda token, message: self._error(message) if token == self._generation else None)
        self._service.result_ready.connect(self._result)
        self._service.request_failed.connect(self._failed)
        self._service.session_published.connect(self._session_changed)
        self._release_timer = QTimer(self); self._release_timer.setInterval(40); self._release_timer.timeout.connect(self._release)
        retained = getattr(owner, "_hair_reference_dialogs", None)
        if retained is None: retained = set(); owner._hair_reference_dialogs = retained
        retained.add(self)
        register_transient_worker_controller(owner, self)
        QTimer.singleShot(0, self._search)

    def _page(self, delta):
        self._page_start = max(0, self._page_start + delta * 72)
        self._search()

    def _filter_changed(self):
        self._page_start = 0
        self._timer.start()

    def _search(self):
        if self._closed: return
        self._generation += 1
        for request in self._requests: self._service.cancel(request)
        self._requests.clear(); self._rows.clear(); self._preview.clear_page()
        self._prepare.cancel(); self.grid.clear(); self.choose.setEnabled(False)
        try:
            if self._role == "hair":
                for index, stem in (self._styles[:1] if self.auto_choose_first else self._styles):
                    key = f"asset:character/model/1_pc/2_phw/head/hair/{stem}.pac"
                    request = self._service.get_character_catalog_detail(CharacterCatalogDetailRequest(self._session_id, key), ui_generation=self._generation)
                    self._requests[request] = ("style", index)
                self.previous.setEnabled(False); self.next.setEnabled(False)
            else:
                request = self._service.search_character_catalog(CharacterCatalogSearchRequest(self._session_id,
                    query=self.search.text(), tab="all", body_family="2_phw",
                    selection_purpose="hair_" + self._role, page_start=self._page_start), ui_generation=self._generation)
                self._requests[request] = ("search", None)
        except Exception as error:
            self._error(str(error))

    def _result(self, request, _operation, result):
        if self._closed or request not in self._requests or getattr(result, "session_id", None) != self._session_id: return
        kind, index = self._requests.pop(request)
        if kind == "search" and isinstance(result, CharacterCatalogSearchResult):
            for row in result.rows:
                path = row.path.casefold()
                eligible = (row.model_count == 1 and row.resolution in {"resolved", "inferred"} and row.body_family == "2_phw" and row.role in ({"head"} if self._role == "head" else {"body", "whole_character"})
                    and path.endswith(".pac") and ("/1_pc/2_phw/head/head/" in path if self._role == "head"
                    else "/1_pc/2_phw/nude/cd_phw_00_nude_" in path))
                if eligible:
                    self._add(row)
            self.previous.setEnabled(self._page_start > 0); self.next.setEnabled(self._page_start + 72 < result.total_matches)
            self.status.setText(f"{result.total_matches} compatible choices" if result.rows else "No compatible matches are available in the mounted character data.")
        elif isinstance(result, CharacterCatalogDetailResult):
            if kind == "style":
                row = replace(result.row, label=f"Damiane hairstyle {index + 1}")
                result = replace(result, row=row)
                self._details[row.key] = result
                if self.search.text().casefold() in row.label.casefold(): self._add(row)
            elif result.row.key == self._key():
                self._details[result.row.key] = result
                self._preview.select(result, self._generation)
                self.choose.setEnabled(len(result.models) == 1)
        if not self.auto_choose_first:
            self._preview.visible(tuple(self._rows.values()), session_id=self._session_id, generation=self._generation)
        if self.grid.currentRow() < 0 and self.grid.count(): self.grid.setCurrentRow(0)
        if self.auto_choose_first and self.choose.isEnabled():
            self._choose()

    def _add(self, row):
        self._rows[row.key] = row
        label = row.label
        if self._role != "hair" and (label.endswith(".pac") or label.startswith("cd_")):
            stem = Path(row.path).stem
            prefix = "cd_phw_00_head_00_" if self._role == "head" else "cd_phw_00_nude_00_"
            variant = stem.removeprefix(prefix).replace("_", " ")
            label = ("Damiane head " if self._role == "head" else "Damiane base body ") + variant
        item = QListWidgetItem(label)
        item.setToolTip(row.path)
        item.setData(Qt.UserRole, row.key); item.setSizeHint(QSize(168, 192))
        self.grid.addItem(item)

    def _key(self):
        item = self.grid.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def _select(self, *_):
        self._prepare.cancel(); self.choose.setEnabled(False)
        key = self._key()
        if key is None or self._closed: return
        detail = self._details.get(key)
        if detail:
            if not self.auto_choose_first:
                self._preview.select(detail, self._generation)
            self.choose.setEnabled(len(detail.models) == 1)
        else:
            try:
                request = self._service.get_character_catalog_detail(CharacterCatalogDetailRequest(self._session_id, key), ui_generation=self._generation)
                self._requests[request] = ("detail", None)
            except Exception as error:
                self._error(str(error))

    def _choose(self):
        detail = self._details.get(self._key())
        if detail is None: return
        self.choose.setEnabled(False); self.status.setText("Preparing character materials…")
        self._prepare.start(detail, self._generation)

    def _prepared(self, token, inputs):
        if self._closed or token != self._generation or inputs.detail.row.key != self._key(): return
        if not inputs.dependencies_complete or len(inputs.detail.models) != 1:
            self._error("This choice has incomplete or ambiguous dependencies."); return
        entry = inputs.entries_by_id[inputs.detail.models[0].entry_id]
        paths, names = {}, {}
        for item in inputs.entries:
            paths.setdefault(item.path.casefold(), []).append(item)
            names.setdefault(item.basename.casefold(), []).append(item)
        self.selected_entry = entry
        self.selected_dependencies = ArchiveWorkflowDependencyContext(entry, inputs.entries, paths, names, True)
        self.accept()

    def _thumbnail(self, key, result):
        if self._closed or not result.thumbnail_path: return
        for index in range(self.grid.count()):
            if self.grid.item(index).data(Qt.UserRole) == key: self.grid.item(index).setIcon(QIcon(result.thumbnail_path))

    def _package(self, key, result):
        if not self._closed and key == self._key(): self.host.load_package(result.package_path, reset_view=True)

    def _failed(self, request, error):
        if request in self._requests and not self._closed:
            self._requests.pop(request); self._error(str(getattr(error, "message", error)))

    def _error(self, message):
        if self._closed: return
        self.status.setText(str(message))
        self.preparation_failed.emit(str(message))
        if self.auto_choose_first: self.reject()

    def _session_changed(self, session):
        if session is None or session.session_id != self._session_id:
            self._error("The archive catalogue changed. Open Hair again after loading completes.")
            self.reject()

    def iter_shutdown_workers(self):
        yield from self._preview.iter_shutdown_workers()

    def request_shutdown(self): self.reject()

    def done(self, result):
        if not self._closed:
            self._closed = True; self._timer.stop()
            for request in self._requests: self._service.cancel(request)
            self._requests.clear(); self._prepare.cancel(); self._preview.shutdown(); self.host.controller.shutdown()
            self._release_timer.start()
        super().done(result)

    def _release(self):
        if self._preview.busy or any(p.state() != QProcess.NotRunning for p in self.findChildren(QProcess)): return
        self._release_timer.stop(); self._owner._hair_reference_dialogs.discard(self); self.deleteLater()
