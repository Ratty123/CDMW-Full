"""Sequential mesh export with independent, bounded archive preparation."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from cdmw.domain.archives.catalogue import ArchiveEntryDto
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


@dataclass(frozen=True)
class BatchMeshSelection:
    entry: ArchiveEntry
    dto: ArchiveEntryDto | None = None


def _selected_batch_entries(archive: object):
    for node in archive.archive_tree.selectedItems():
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


def has_selected_batch_models(archive: object) -> bool:
    return next(_selected_batch_entries(archive), None) is not None


def selected_batch_models(archive: object) -> tuple[BatchMeshSelection, ...]:
    """Capture explicit file rows in both flat and tree views, without a 512-row cap."""
    models = {}
    for entry, dto in _selected_batch_entries(archive):
        models.setdefault(entry.identity, BatchMeshSelection(copy.deepcopy(entry), dto))
    return tuple(models.values())


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
