"""Worker-backed source selection and review for Replace from Archive."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePosixPath

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSplitter,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.archives.catalogue import (
    ArchiveEntryDto,
    ArchivePage,
    ArchiveQuery,
    ArchiveQueryHandle,
    ArchiveSessionHandle,
    ArchiveSortField,
    ArchiveViewMode,
)
from cdmw.domain.archives.catalogue_operations import FetchPageRequest
from cdmw.domain.archives.replace_from_archive import (
    ReplaceFromArchiveActionKind,
    ReplaceFromArchiveCharacterMode,
    ReplaceFromArchivePlan,
)
from cdmw.models import ArchiveEntry, ArchivePreviewResult, ModelPreviewData
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
from cdmw.services.archive_query_service import find_archive_model_related_entries
from cdmw.services.replace_from_archive_service import (
    archive_entries_are_character_pair,
)
from cdmw.ui.archive_browser.remote_model import (
    RemoteArchiveBrowserModel,
    RemotePageFetch,
)
from cdmw.ui.archive_browser.remote_preview_dependencies import (
    ArchivePreviewDependencySet,
    ArchiveRemotePreviewDependencyProvider,
)
from cdmw.ui.archive_browser.workflow_dependencies import (
    ArchiveWorkflowDependencyContext,
)
from cdmw.workers.archive_preview_workers import ArchivePreviewWorker

_SORT_FIELDS: Mapping[int, ArchiveSortField] = {
    0: ArchiveSortField.NAME,
    1: ArchiveSortField.KNOWN_NAME,
    2: ArchiveSortField.ROLE,
    5: ArchiveSortField.PACKAGE,
    6: ArchiveSortField.ACTIVE_OVERRIDE,
    7: ArchiveSortField.PATH,
}


class _ArchivePreviewLane(QObject):
    idle = Signal()
    settled_changed = Signal()

    def __init__(
        self, image_label: QLabel, status_label: QLabel, parent: QObject
    ) -> None:
        super().__init__(parent)
        self._image_label = image_label
        self._status_label = status_label
        self._generation = 0
        self._jobs: dict[int, tuple[ArchivePreviewWorker, QThread]] = {}
        self.image: QImage | None = None
        self.settled = False

    @property
    def has_live_workers(self) -> bool:
        return bool(self._jobs)

    def iter_shutdown_workers(
        self,
    ) -> tuple[tuple[str, QThread, ArchivePreviewWorker], ...]:
        return tuple(
            (f"preview_{request_id}", thread, worker)
            for request_id, (worker, thread) in self._jobs.items()
        )

    def start(
        self, entry: ArchiveEntry, context: ArchiveWorkflowDependencyContext
    ) -> None:
        self.cancel()
        self._generation += 1
        request_id = self._generation
        self.image = None
        self.settled = False
        self._image_label.clear()
        self._image_label.setText(f"Loading {entry.basename}...")
        self._status_label.setText(entry.path)
        related = tuple(
            find_archive_model_related_entries(entry, dict(context.entries_by_basename))
        )
        companion = next(
            (
                candidate
                for candidate in related
                if candidate.identity != entry.identity
                and candidate.extension in {".pac", ".pam", ".pamlod"}
            ),
            None,
        )
        paths = {
            key: list(value)
            for key, value in context.entries_by_normalized_path.items()
        }
        basenames = {
            key: list(value) for key, value in context.entries_by_basename.items()
        }
        worker = ArchivePreviewWorker(
            request_id,
            entry,
            companion,
            paths,
            basenames,
            None,
            None,
            (),
            support_texture_slots=(),
            include_loose_preview_assets=False,
            attach_preview_images=False,
            static_thumbnail_size=(420, 320),
            static_thumbnail_point_cloud=True,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._completed)
        worker.error.connect(self._failed)
        worker.finished.connect(
            lambda target_worker=worker: self._finish_worker_thread(target_worker),
            Qt.ConnectionType.DirectConnection,
        )
        thread.finished.connect(self._cleanup_finished_jobs)
        self._jobs[request_id] = (worker, thread)
        thread.start()

    def cancel(self) -> None:
        self._generation += 1
        for worker, thread in tuple(self._jobs.values()):
            worker.stop()
            thread.quit()

    def _completed(self, request_id: int, payload: object) -> None:
        if request_id != self._generation or not isinstance(
            payload, ArchivePreviewResult
        ):
            return
        preview_model = getattr(payload, "preview_model", None)
        image = getattr(payload, "static_preview_image", None)
        if (
            not isinstance(preview_model, ModelPreviewData)
            or not isinstance(image, QImage)
            or image.isNull()
        ):
            self._image_label.clear()
            self._image_label.setText("No renderable geometry preview was recovered.")
            self.settled = True
            self.settled_changed.emit()
            return
        self.image = image.copy()
        pixmap = QPixmap.fromImage(self.image).scaled(
            self._image_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self._image_label.clear()
        self._image_label.setPixmap(pixmap)
        self._status_label.setText(
            f"{int(preview_model.vertex_count):,} vertices, {int(preview_model.face_count):,} faces"
        )
        self.settled = True
        self.settled_changed.emit()

    def _failed(self, request_id: int, message: str) -> None:
        if request_id != self._generation:
            return
        self._image_label.clear()
        self._image_label.setText("Preview unavailable.")
        self._status_label.setText(str(message or "Preview failed."))
        self.settled = True
        self.settled_changed.emit()

    def _finish_worker_thread(self, worker: ArchivePreviewWorker) -> None:
        current = QThread.currentThread()
        if worker.thread() is current:
            worker.moveToThread(self.thread())
        current.quit()

    def _cleanup_finished_jobs(self) -> None:
        removed = False
        for request_id, (worker, thread) in tuple(self._jobs.items()):
            if not thread.wait(0):
                continue
            self._jobs.pop(request_id, None)
            worker.deleteLater()
            thread.deleteLater()
            removed = True
        if self._jobs and any(not thread.isRunning() for _worker, thread in self._jobs.values()):
            QTimer.singleShot(0, self._cleanup_finished_jobs)
        elif removed and not self._jobs:
            self.idle.emit()


class ReplaceFromArchivePickerDialog(QDialog):
    """Remote, paged archive mesh picker with latest-wins dependency previews."""

    preview_workers_idle = Signal()

    def __init__(
        self,
        service: ArchiveCatalogueService,
        session: ArchiveSessionHandle,
        *,
        target_entry: ArchiveEntry,
        target_dependencies: ArchiveWorkflowDependencyContext,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._session = session
        self._target_entry = target_entry
        self._target_dependencies = target_dependencies
        self._generation = 0
        self._selection_generation = 0
        self._requests: dict[str, tuple[str, int, RemotePageFetch | None]] = {}
        self._closed = False
        self._sort_column = 7
        self._sort_descending = False
        self.selected_entry: ArchiveEntry | None = None
        self.selected_dependencies: ArchiveWorkflowDependencyContext | None = None
        self.character_mode = ReplaceFromArchiveCharacterMode.NOT_CHARACTER

        self.setWindowTitle("Replace from Archive")
        self.resize(1360, 820)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        intro = QLabel(
            "Choose another PAC, PAM, or PAMLOD already present in the loaded archives. "
            "The source bytes are mapped onto the current target and built as a separate loose mod."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            "Search item name, internal name, type, path, or package"
        )
        layout.addWidget(self.search_edit)

        content = QSplitter(Qt.Vertical)
        content.setChildrenCollapsible(False)
        layout.addWidget(content, 1)

        self.model = RemoteArchiveBrowserModel(self, page_size=256, page_cache_limit=12)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(False)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.setSortIndicator(self._sort_column, Qt.AscendingOrder)
        header.setSectionResizeMode(QHeaderView.Interactive)
        for column in (3, 4):
            self.table.setColumnHidden(column, True)
        for column, width in {0: 210, 1: 220, 2: 140, 5: 150, 6: 110, 7: 520}.items():
            self.table.setColumnWidth(column, width)
        content.addWidget(self.table)

        previews = QSplitter(Qt.Horizontal)
        previews.setChildrenCollapsible(False)
        self._target_image, self._target_status, target_panel = self._preview_panel(
            "Current target",
            target_entry.path,
        )
        self._source_image, self._source_status, source_panel = self._preview_panel(
            "Archive source",
            "Select a source row to prepare its preview.",
        )
        previews.addWidget(target_panel)
        previews.addWidget(source_panel)
        previews.setSizes((1, 1))
        content.addWidget(previews)
        content.setSizes((470, 300))

        self.character_mode_combo = QComboBox()
        self.character_mode_combo.addItem("Choose character identity handling...", None)
        self.character_mode_combo.addItem(
            "Preserve target identity, skeleton, and animation routing",
            ReplaceFromArchiveCharacterMode.PRESERVE_TARGET,
        )
        self.character_mode_combo.addItem(
            "Body and head retarget, preserving target hair and armour",
            ReplaceFromArchiveCharacterMode.BODY_HEAD_PATCH,
        )
        self.character_mode_combo.addItem(
            "Full source identity, appearance, skeleton, and animation graph",
            ReplaceFromArchiveCharacterMode.FULL_SOURCE_IDENTITY,
        )
        self.character_mode_combo.setVisible(False)
        layout.addWidget(self.character_mode_combo)

        self.status_label = QLabel("Querying the loaded archive catalogue...")
        self.status_label.setObjectName("HintLabel")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.choose_button = QPushButton("Review Replacement")
        cancel_button = QPushButton("Cancel")
        self.choose_button.setEnabled(False)
        buttons.addWidget(self.choose_button)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

        self._query_timer = QTimer(self)
        self._query_timer.setSingleShot(True)
        self._query_timer.setInterval(180)
        self._query_timer.timeout.connect(self._start_query)
        self._dependency_provider = ArchiveRemotePreviewDependencyProvider(
            service, parent=self
        )
        self._dependency_provider.ready.connect(self._dependencies_ready)
        self._dependency_provider.failed.connect(self._dependencies_failed)
        self._target_lane = _ArchivePreviewLane(
            self._target_image, self._target_status, self
        )
        self._source_lane = _ArchivePreviewLane(
            self._source_image, self._source_status, self
        )
        self._target_lane.idle.connect(self._preview_lane_idle)
        self._source_lane.idle.connect(self._preview_lane_idle)
        self._source_lane.settled_changed.connect(self._update_choose_state)

        self.search_edit.textChanged.connect(lambda _text: self._query_timer.start())
        header.sectionClicked.connect(self._sort_requested)
        self.table.selectionModel().selectionChanged.connect(
            lambda _selected, _deselected: self._selection_changed()
        )
        self.table.doubleClicked.connect(lambda _index: self._accept_current())
        self.table.verticalScrollBar().valueChanged.connect(
            lambda _value: self._request_visible_rows()
        )
        self.character_mode_combo.currentIndexChanged.connect(
            lambda _index: self._update_choose_state()
        )
        self.choose_button.clicked.connect(self._accept_current)
        cancel_button.clicked.connect(self.reject)
        self.model.pageRequested.connect(self._fetch_page)
        self._service.result_ready.connect(self._handle_result)
        self._service.request_failed.connect(self._handle_failure)
        self._service.request_cancelled.connect(self._handle_cancelled)

        QTimer.singleShot(0, self._start_query)
        QTimer.singleShot(0, self._start_target_preview)

    @property
    def target_preview_image(self) -> QImage | None:
        return (
            self._target_lane.image.copy()
            if isinstance(self._target_lane.image, QImage)
            else None
        )

    @property
    def source_preview_image(self) -> QImage | None:
        return (
            self._source_lane.image.copy()
            if isinstance(self._source_lane.image, QImage)
            else None
        )

    @property
    def has_live_preview_workers(self) -> bool:
        return self._target_lane.has_live_workers or self._source_lane.has_live_workers

    def iter_shutdown_workers(
        self,
    ) -> tuple[tuple[str, QThread, ArchivePreviewWorker], ...]:
        return (
            *self._target_lane.iter_shutdown_workers(),
            *self._source_lane.iter_shutdown_workers(),
        )

    def request_shutdown(self) -> None:
        if not self._closed:
            self.reject()
            return
        self._dependency_provider.cancel(clear_snapshot=True)
        self._target_lane.cancel()
        self._source_lane.cancel()

    @staticmethod
    def _preview_panel(title: str, detail: str) -> tuple[QLabel, QLabel, QWidget]:
        panel = QFrame()
        panel.setFrameShape(QFrame.StyledPanel)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(8, 8, 8, 8)
        heading = QLabel(title)
        heading.setObjectName("SectionTitle")
        panel_layout.addWidget(heading)
        image = QLabel(detail)
        image.setAlignment(Qt.AlignCenter)
        image.setWordWrap(True)
        image.setMinimumHeight(220)
        panel_layout.addWidget(image, 1)
        status = QLabel(detail)
        status.setObjectName("HintLabel")
        status.setWordWrap(True)
        panel_layout.addWidget(status)
        return image, status, panel

    def _cancel_requests(self) -> None:
        for request_id in tuple(self._requests):
            self._service.cancel(request_id)
        self._requests.clear()

    def _start_target_preview(self) -> None:
        if not self._closed:
            self._target_lane.start(self._target_entry, self._target_dependencies)

    def _start_query(self) -> None:
        if self._closed:
            return
        self._generation += 1
        generation = self._generation
        self._cancel_requests()
        self.model.clear()
        self.selected_entry = None
        self.selected_dependencies = None
        self._dependency_provider.cancel(clear_snapshot=False)
        self._source_lane.cancel()
        self._source_image.clear()
        self._source_image.setText("Select a source row to prepare its preview.")
        self.status_label.setText("Querying the loaded archive catalogue...")
        query = ArchiveQuery(
            session_id=self._session.session_id,
            include_text=self.search_edit.text().strip() or None,
            exclude_text=self._target_entry.path,
            extensions=(".pac", ".pam", ".pamlod"),
            view_mode=ArchiveViewMode.FLAT,
            sort_field=_SORT_FIELDS[self._sort_column],
            sort_active=True,
            sort_descending=self._sort_descending,
        )
        try:
            request_id = self._service.create_query(query, ui_generation=generation)
        except Exception as exc:  # noqa: BLE001 - service refusal is displayed in the dialog
            self.status_label.setText(str(exc))
            return
        self._requests[request_id] = ("query", generation, None)
        self._update_choose_state()

    def _sort_requested(self, column: int) -> None:
        if column not in _SORT_FIELDS:
            return
        if column == self._sort_column:
            self._sort_descending = not self._sort_descending
        else:
            self._sort_column = column
            self._sort_descending = False
        self.table.horizontalHeader().setSortIndicator(
            column,
            Qt.DescendingOrder if self._sort_descending else Qt.AscendingOrder,
        )
        self._start_query()

    def _fetch_page(self, fetch: object) -> None:
        if self._closed or not isinstance(fetch, RemotePageFetch):
            return
        handle = self.model.query_handle
        if (
            handle is None
            or fetch.query_id != handle.query_id
            or fetch.generation != handle.generation
        ):
            return
        try:
            request_id = self._service.fetch_page(
                FetchPageRequest(fetch.query_id, fetch.page_start, fetch.page_size),
                ui_generation=self._generation,
            )
        except Exception as exc:  # noqa: BLE001 - service refusal is displayed in the dialog
            self.model.reject_page(fetch.page_start)
            self.status_label.setText(str(exc))
            return
        self._requests[request_id] = ("page", self._generation, fetch)

    def _handle_result(self, request_id: str, operation: str, payload: object) -> None:
        tracked = self._requests.pop(request_id, None)
        if tracked is None or tracked[1] != self._generation or self._closed:
            return
        kind, _generation, fetch = tracked
        if (
            kind == "query"
            and operation == "create_query"
            and isinstance(payload, ArchiveQueryHandle)
        ):
            self.model.publish_query(payload, view_mode=ArchiveViewMode.FLAT)
            self.status_label.setText(
                f"{payload.total_matches:,} archive mesh entr{'y' if payload.total_matches == 1 else 'ies'} match. "
                "Rows load incrementally as you scroll."
            )
            QTimer.singleShot(0, self._request_visible_rows)
            return
        if (
            kind == "page"
            and operation == "fetch_page"
            and isinstance(payload, ArchivePage)
        ):
            self.model.accept_page(payload)
            QTimer.singleShot(0, self._request_visible_rows)
            return
        if isinstance(fetch, RemotePageFetch):
            self.model.reject_page(fetch.page_start)

    def _handle_failure(self, request_id: str, error: object) -> None:
        tracked = self._requests.pop(request_id, None)
        if tracked is None:
            return
        fetch = tracked[2]
        if isinstance(fetch, RemotePageFetch):
            self.model.reject_page(fetch.page_start)
        if tracked[1] == self._generation:
            self.status_label.setText(
                str(getattr(error, "message", "") or error or "Archive query failed.")
            )

    def _handle_cancelled(self, request_id: str) -> None:
        tracked = self._requests.pop(request_id, None)
        if tracked is not None and isinstance(tracked[2], RemotePageFetch):
            self.model.reject_page(tracked[2].page_start)

    def _request_visible_rows(self) -> None:
        if self._closed or self.model.query_handle is None:
            return
        first = self.table.rowAt(0)
        last = self.table.rowAt(max(0, self.table.viewport().height() - 1))
        first = max(first, 0)
        if last < first:
            last = first + self.model.page_size - 1
        self.model.request_visible_rows(first, last)

    def _selection_changed(self) -> None:
        self._selection_generation += 1
        selection_id = self._selection_generation
        self.selected_entry = None
        self.selected_dependencies = None
        self._dependency_provider.cancel(clear_snapshot=False)
        self._source_lane.cancel()
        selected = self.model.entry_for_index(self.table.currentIndex())
        if not isinstance(selected, ArchiveEntryDto):
            self._source_image.clear()
            self._source_image.setText("Select a loaded archive mesh row.")
            self._update_character_mode_visibility(None)
            self._update_choose_state()
            return
        compatibility = self._service.compatibility_entry(selected)
        if compatibility.identity == self._target_entry.identity:
            self.status_label.setText(
                "The current target cannot also be the replacement source."
            )
            self._update_choose_state()
            return
        self._source_image.clear()
        self._source_image.setText(f"Preparing {compatibility.basename}...")
        self._source_status.setText(
            "Resolving the bounded source family and preview dependencies..."
        )
        self._update_character_mode_visibility(compatibility)
        self._dependency_provider.request(selected, ui_request_id=selection_id)
        self._update_choose_state()

    def _dependencies_ready(self, request_id: int, payload: object) -> None:
        if (
            self._closed
            or request_id != self._selection_generation
            or not isinstance(payload, ArchivePreviewDependencySet)
        ):
            return
        context = ArchiveWorkflowDependencyContext(
            selected_entry=payload.selected_entry,
            entries=payload.entries,
            entries_by_normalized_path=payload.entries_by_normalized_path,
            entries_by_basename=payload.entries_by_basename,
            remote=True,
        )
        self.selected_entry = context.selected_entry
        self.selected_dependencies = context
        self._source_lane.start(context.selected_entry, context)
        self._update_character_mode_visibility(context.selected_entry)
        self.status_label.setText(
            f"Prepared {context.selected_entry.path}. Review the source preview and continue when ready."
        )
        self._update_choose_state()

    def _dependencies_failed(self, request_id: int, message: str) -> None:
        if self._closed or request_id != self._selection_generation:
            return
        self.selected_entry = None
        self.selected_dependencies = None
        self._source_image.clear()
        self._source_image.setText("Source preparation failed.")
        self._source_status.setText(message)
        self.status_label.setText(message)
        self._update_choose_state()

    def _update_character_mode_visibility(self, source: ArchiveEntry | None) -> None:
        character_pair = isinstance(
            source, ArchiveEntry
        ) and archive_entries_are_character_pair(
            self._target_entry,
            source,
        )
        self.character_mode_combo.setVisible(character_pair)
        if not character_pair:
            self.character_mode_combo.setCurrentIndex(0)
            self.character_mode = ReplaceFromArchiveCharacterMode.NOT_CHARACTER

    def _update_choose_state(self) -> None:
        ready = (
            isinstance(self.selected_entry, ArchiveEntry)
            and isinstance(
                self.selected_dependencies,
                ArchiveWorkflowDependencyContext,
            )
            and self._source_lane.settled
        )
        if ready and archive_entries_are_character_pair(
            self._target_entry, self.selected_entry
        ):
            ready = self._selected_character_mode() is not None
        self.choose_button.setEnabled(ready)

    def _accept_current(self) -> None:
        if not self.choose_button.isEnabled() or not isinstance(
            self.selected_entry, ArchiveEntry
        ):
            return
        if archive_entries_are_character_pair(self._target_entry, self.selected_entry):
            mode = self._selected_character_mode()
            if mode is None:
                return
            self.character_mode = mode
        else:
            self.character_mode = ReplaceFromArchiveCharacterMode.NOT_CHARACTER
        self.accept()

    def _selected_character_mode(self) -> ReplaceFromArchiveCharacterMode | None:
        value = self.character_mode_combo.currentData()
        if isinstance(value, ReplaceFromArchiveCharacterMode):
            return value
        try:
            return ReplaceFromArchiveCharacterMode(str(value))
        except ValueError:
            return None

    def _preview_lane_idle(self) -> None:
        if not self.has_live_preview_workers:
            self.preview_workers_idle.emit()

    def done(self, result: int) -> None:
        if not self._closed:
            self._closed = True
            self._query_timer.stop()
            self._cancel_requests()
            self.model.suspend_requests(True)
            self._dependency_provider.cancel(clear_snapshot=True)
            self._target_lane.cancel()
            self._source_lane.cancel()
            for signal, slot in (
                (self._service.result_ready, self._handle_result),
                (self._service.request_failed, self._handle_failure),
                (self._service.request_cancelled, self._handle_cancelled),
            ):
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
        super().done(result)


class ReplaceFromArchiveReviewDialog(QDialog):
    """Compact immutable plan review. Warnings allow Build Anyway; blockers do not."""

    def __init__(
        self,
        plan: ReplaceFromArchivePlan,
        *,
        target_preview: QImage | None = None,
        source_preview: QImage | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.choice = "cancel"
        self.setWindowTitle("Review Replace from Archive")
        self.resize(1220, 760)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        summary = QLabel(
            f"Source: {plan.request.source_entry.path}\nTarget: {plan.request.target_entry.path}"
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)

        if isinstance(target_preview, QImage) or isinstance(source_preview, QImage):
            preview_row = QHBoxLayout()
            preview_row.addWidget(self._review_preview("Target", target_preview))
            preview_row.addWidget(self._review_preview("Source", source_preview))
            layout.addLayout(preview_row)

        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(("Role", "Action", "Source", "Target", "Notes"))
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setAlternatingRowColors(True)
        for action in plan.copied_actions:
            row = table.rowCount()
            table.insertRow(row)
            values = (
                action.role,
                action.kind.value.title(),
                action.source_path or "Generated validated patch",
                action.target_path,
                action.note,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                table.setItem(row, column, item)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
        for column, width in {0: 170, 1: 80, 2: 300, 3: 300}.items():
            table.setColumnWidth(column, width)
        layout.addWidget(table, 1)

        reused = [
            action.source_path
            for action in plan.actions
            if action.kind is ReplaceFromArchiveActionKind.REUSE
        ]
        if reused:
            reused_label = QLabel(
                f"Reused game textures, not copied ({len(reused):,}): "
                + ", ".join(reused[:6])
            )
            reused_label.setWordWrap(True)
            reused_label.setObjectName("HintLabel")
            layout.addWidget(reused_label)

        issues = QListWidget()
        for blocker in plan.blockers:
            issues.addItem(f"BLOCKER: {blocker}")
        for warning in plan.warnings:
            issues.addItem(f"WARNING: {warning}")
        issues.setVisible(bool(plan.blockers or plan.warnings))
        if plan.blockers or plan.warnings:
            issues.setMaximumHeight(150)
            layout.addWidget(issues)

        buttons = QHBoxLayout()
        choose_again = QPushButton("Choose Another Source")
        cancel = QPushButton("Cancel")
        build = QPushButton(
            "Build Anyway" if plan.warnings and not plan.blockers else "Build Mod"
        )
        build.setEnabled(plan.can_build)
        buttons.addWidget(choose_again)
        buttons.addStretch(1)
        buttons.addWidget(build)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        choose_again.clicked.connect(self._choose_again)
        cancel.clicked.connect(self.reject)
        build.clicked.connect(self._build)

    @staticmethod
    def _review_preview(title: str, image: QImage | None) -> QWidget:
        panel = QFrame()
        panel.setFrameShape(QFrame.StyledPanel)
        panel.setMaximumHeight(190)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(6, 6, 6, 6)
        panel_layout.addWidget(QLabel(title))
        label = QLabel("Preview unavailable")
        label.setAlignment(Qt.AlignCenter)
        if isinstance(image, QImage) and not image.isNull():
            label.setPixmap(
                QPixmap.fromImage(image).scaled(
                    520, 145, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            )
        panel_layout.addWidget(label, 1)
        return panel

    def _choose_again(self) -> None:
        self.choice = "back"
        self.reject()

    def _build(self) -> None:
        self.choice = "build"
        self.accept()


def replacement_package_title(target: ArchiveEntry) -> str:
    stem = PurePosixPath(target.path.replace("\\", "/")).stem
    return f"Replace {stem} from Archive"


__all__ = [
    "ReplaceFromArchivePickerDialog",
    "ReplaceFromArchiveReviewDialog",
    "replacement_package_title",
]
