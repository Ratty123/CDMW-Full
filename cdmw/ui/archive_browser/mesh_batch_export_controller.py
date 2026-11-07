"""Sequential mesh export with independent, bounded archive preparation."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from cdmw.domain.archives.catalogue import ArchiveEntryDto, ArchivePage
from cdmw.domain.archives.catalogue_operations import FetchPageRequest
from cdmw.domain.archives.constants import ARCHIVE_MESH_EXTENSIONS
from cdmw.models import ArchiveEntry
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
from cdmw.services.archive_mesh_batch_export import (
    BatchMeshExportRequest, BatchMeshExportResult, export_batch_mesh_item,
)
from cdmw.ui.archive_browser.remote_preview_dependencies import (
    ArchivePreviewDependencySet, ArchiveRemotePreviewDependencyProvider,
)
from cdmw.ui.archive_browser.workflow_dependencies import archive_workflow_dependency_context
from cdmw.ui.shell.request_task_controller import RequestTaskController


#: Selected rows a batch export reads from the worker when the flat view has not
#: loaded their pages: about 200 pages of the live catalogue's query.
MAX_BATCH_SELECTED_ROWS = 50_000


@dataclass(frozen=True)
class BatchMeshSelection:
    entry: ArchiveEntry
    dto: ArchiveEntryDto | None = None


def _selected_batch_entries(archive: object, nodes=None):
    for node in archive.archive_tree.selectedItems() if nodes is None else nodes:
        if node.kind != "file":
            continue
        dto = getattr(node, "entry", None)
        if isinstance(dto, ArchiveEntryDto):
            entry = ArchiveCatalogueService.compatibility_entry(dto)
        else:
            index = node.value
            if not isinstance(index, int) or not 0 <= index < len(archive.archive_filtered_entries):
                continue
            entry = archive.archive_filtered_entries[index]
            dto = None
        if entry.extension in ARCHIVE_MESH_EXTENSIONS:
            yield entry, dto


def _selected_flat_ranges(archive: object) -> tuple[tuple[int, int], ...]:
    """The live flat view's selected row ranges, loaded or not.

    A row whose page the view has not loaded (or has evicted from its bounded cache)
    is not selectable, so the selected items leave it out while a Ctrl+A or Shift
    range still spans it. Only the ranges say which rows the user selected.
    """
    tree = archive.archive_tree
    if not getattr(tree, "remote_flat_view_active", False):
        return ()
    selection_model = tree.selectionModel()
    if selection_model is None:
        return ()
    ranges = sorted((int(r.top()), int(r.bottom())) for r in selection_model.selection()
                    if not r.parent().isValid() and r.bottom() >= r.top() >= 0)
    merged: list[tuple[int, int]] = []
    for top, bottom in ranges:
        if merged and top <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], bottom))
        else:
            merged.append((top, bottom))
    return tuple(merged)


def selected_batch_row_count(archive: object) -> int:
    """Rows the live flat view's selection spans; 0 in the tree and legacy views."""
    return sum(bottom - top + 1 for top, bottom in _selected_flat_ranges(archive))


def batch_selection_has_unloaded_rows(archive: object, nodes=None) -> bool:
    """Whether the flat selection spans rows the view holds no entry for."""
    count = selected_batch_row_count(archive)
    if not count:
        return False
    nodes = archive.archive_tree.selectedItems() if nodes is None else nodes
    return count > sum(1 for node in nodes if node.kind == "file")


def has_selected_batch_models(archive: object) -> bool:
    nodes = archive.archive_tree.selectedItems()
    return next(_selected_batch_entries(archive, nodes), None) is not None or batch_selection_has_unloaded_rows(archive, nodes)


def _batch_selections(pairs) -> tuple[BatchMeshSelection, ...]:
    models = {}
    for entry, dto in pairs:
        models.setdefault(entry.identity, BatchMeshSelection(copy.deepcopy(entry), dto))
    return tuple(models.values())


def selected_batch_models(archive: object, nodes=None) -> tuple[BatchMeshSelection, ...]:
    """Capture explicit file rows in both flat and tree views, without a 512-row cap."""
    return _batch_selections(_selected_batch_entries(archive, nodes))


class BatchSelectionPageReader(QObject):
    """Read the selected flat-view rows the view has no page for, through the worker.

    The pages come from the query the view shows, one at a time. A page from another
    query or generation, or a view that published another query meanwhile, ends the
    whole read with ``list_changed``; a worker failure gives ``failed(message)``.
    ``resolved`` carries the selections in row order. Every outcome is delivered from
    the event loop rather than inside the worker's result signal.
    """

    resolved = Signal(object)
    list_changed = Signal()
    failed = Signal(str)

    def __init__(self, archive: object, nodes, parent: QObject | None = None):
        super().__init__(parent)
        bridge = archive.archive_remote_bridge
        self._model = bridge.model
        self._service = archive.archive_catalogue_service
        self._ui_generation = int(bridge.controller.generation)
        self._handle = self._model.query_handle
        self._page_size = int(self._model.page_size)
        self._rows = tuple(row for top, bottom in _selected_flat_ranges(archive) for row in range(top, bottom + 1))
        self._known = {int(node.row_number): node.entry for node in nodes
                       if node.kind == "file" and isinstance(getattr(node, "entry", None), ArchiveEntryDto)}
        self._read: dict[int, ArchiveEntryDto] = {}
        self._starts = sorted({row // self._page_size * self._page_size for row in self._rows if row not in self._known})
        self._request_id: str | None = None
        self.active = False
        self._service.result_ready.connect(self._handle_result)
        self._service.request_failed.connect(self._handle_failure)
        self._service.request_cancelled.connect(self._handle_cancelled)

    def start(self) -> None:
        if self.active:
            return
        self.active = True
        if self._handle is None:
            self._end(self.list_changed)
            return
        self._next()

    def cancel(self) -> None:
        request_id, self._request_id = self._request_id, None
        self.active = False
        if request_id is not None:
            try:
                self._service.cancel(request_id)
            except (AttributeError, RuntimeError):
                pass

    def _next(self) -> None:
        if not self._starts:
            self._finish()
            return
        try:
            self._request_id = str(self._service.fetch_page(
                FetchPageRequest(self._handle.query_id, self._starts[0], self._page_size),
                ui_generation=self._ui_generation,
            ))
        except Exception as exc:  # noqa: BLE001 - the service refuses a stale query by raising
            self._end(self.failed, str(exc))

    def _handle_result(self, request_id: str, _operation: str, payload: object) -> None:
        if not self.active or request_id != self._request_id:
            return
        self._request_id = None
        handle, start = self._handle, self._starts[0]
        if (not isinstance(payload, ArchivePage) or payload.page_start != start or len(payload.rows) > self._page_size
                or (payload.session_id, payload.query_id, payload.generation, payload.total_matches)
                != (handle.session_id, handle.query_id, handle.generation, handle.total_matches)):
            self._end(self.list_changed)
            return
        for offset, dto in enumerate(payload.rows):
            self._read[start + offset] = dto
        self._starts.pop(0)
        self._next()

    def _handle_failure(self, request_id: str, error: object) -> None:
        if self.active and request_id == self._request_id:
            self._request_id = None
            self._end(self.failed, str(getattr(error, "message", "") or error))

    def _handle_cancelled(self, request_id: str) -> None:
        if self.active and request_id == self._request_id:
            self._request_id = None
            self._end(self.list_changed)

    def _finish(self) -> None:
        dtos = [self._known.get(row) or self._read.get(row) for row in self._rows]
        if self._model.query_handle != self._handle or any(dto is None for dto in dtos):
            self._end(self.list_changed)
            return
        selections = _batch_selections(
            (entry, dto) for dto in dtos
            for entry in (ArchiveCatalogueService.compatibility_entry(dto),)
            if entry.extension in ARCHIVE_MESH_EXTENSIONS)
        self._end(self.resolved, selections)

    def _end(self, signal, *arguments) -> None:
        self.active = False
        QTimer.singleShot(0, self, lambda: signal.emit(*arguments))


class BatchMeshExportController(QObject):
    progress = Signal(int, int, str, str)
    item_finished = Signal(object)
    finished = Signal()

    def __init__(self, archive: object, guard: QObject, selections: tuple[BatchMeshSelection, ...]):
        super().__init__(guard)
        self.archive = archive
        self.owner = archive.shell
        self.selections = selections
        self.results: list[BatchMeshExportResult] = []
        self.active = False
        self.cancelled = False
        self.closed = False
        self._position = 0
        self._generation = 0
        self._export_pending = False
        self._preparing = False
        self._tasks = RequestTaskController(self.owner, guard, worker_label="batch_mesh_export")
        self._provider = None
        if any(selection.dto is not None for selection in selections):
            self._provider = ArchiveRemotePreviewDependencyProvider(archive.archive_catalogue_service, self)
            self._provider.ready.connect(self._prepared)
            self._provider.failed.connect(self._preparation_failed)

    def start(self, output_root: Path, export_format: str, allow_missing_skeleton: bool) -> None:
        if self.active or self.closed or self.results:
            return
        self.output_root = output_root
        self.export_format = export_format
        self.allow_missing_skeleton = allow_missing_skeleton
        self.active = True
        self._next()

    def cancel(self) -> None:
        if not self.active:
            return
        self.cancelled = True
        self._generation += 1
        if self._provider is not None:
            self._provider.cancel(clear_snapshot=True)
        self._preparing = False
        if self._export_pending:
            # Keep delivery alive: a result committed just before Cancel is still a success.
            if self._tasks.active:
                self.owner.utility_worker.stop()
            return
        self._next()

    def close(self) -> None:
        self.closed = True
        self._generation += 1
        if self._provider is not None:
            self._provider.cancel(clear_snapshot=True)
        self._tasks.request_shutdown()

    def _next(self) -> None:
        if self.closed or not self.active or self._export_pending or self._preparing:
            return
        if self.cancelled or bool(getattr(self.owner, "_shutting_down", False)):
            for selection in self.selections[self._position:]:
                result = BatchMeshExportResult(0, "cancelled", selection.entry.path)
                self.results.append(result)
                self.item_finished.emit(result)
            self._position = len(self.selections)
        if self._position == len(self.selections):
            self.active = False
            if self._provider is not None:
                self._provider.cancel(clear_snapshot=True)
            self.finished.emit()
            return
        self._generation += 1
        selection = self.selections[self._position]
        self.progress.emit(self._position, len(self.selections), "Preparing files", selection.entry.path)
        if selection.dto is not None:
            self._preparing = True
            self._provider.request(selection.dto, ui_request_id=self._generation)
        else:
            try:
                context = archive_workflow_dependency_context(self.archive, selection.entry)
                self._export(context.selected_entry, context.entries_by_normalized_path, context.entries_by_basename)
            except Exception as exc:
                self._preparation_failed(self._generation, str(exc))

    def _prepared(self, generation: int, snapshot: object) -> None:
        if generation != self._generation or not self.active or self.cancelled or self.closed:
            return
        selection = self.selections[self._position]
        if (not isinstance(snapshot, ArchivePreviewDependencySet) or snapshot.truncated or not snapshot.entries
                or snapshot.session_id != selection.dto.session_id or snapshot.entry_id != selection.dto.entry_id
                or snapshot.selected_entry.identity != selection.entry.identity
                or any(entry.prepared_path is None for entry in snapshot.entries)):
            self._preparation_failed(generation, "The model dependencies are incomplete or no longer match the selection.")
            return
        self._preparing = False
        self._export(snapshot.selected_entry, snapshot.entries_by_normalized_path, snapshot.entries_by_basename)

    def _preparation_failed(self, generation: int, message: str) -> None:
        if generation == self._generation and self.active and not self.closed and not self.cancelled:
            self._preparing = False
            self._item_done(BatchMeshExportResult(0, "failed", self.selections[self._position].entry.path, details=(message,)))

    def _export(self, entry: ArchiveEntry, paths: object, basenames: object) -> None:
        self.progress.emit(self._position, len(self.selections), "Exporting", entry.path)
        request = BatchMeshExportRequest(0, entry, self.output_root, self.export_format,
                                         paths, basenames, self.allow_missing_skeleton)
        self._export_pending = True
        started = self._tasks.start(
            request, export_batch_mesh_item,
            status_message="Batch mesh export",
            on_complete=self._item_done,
            on_error=lambda message: self._item_done(BatchMeshExportResult(0, "failed", entry.path, details=(message,))),
        )
        if not started and self._export_pending:
            self._item_done(BatchMeshExportResult(0, "failed", entry.path, details=("Background processing could not start.",)))

    def _item_done(self, result: BatchMeshExportResult) -> None:
        if self.closed or not self.active:
            return
        self._export_pending = False
        self.results.append(result)
        self.item_finished.emit(result)
        self._position += 1
        if result.status == "cancelled":
            self.cancelled = True
        QTimer.singleShot(0, self, self._next)
