"""Cancellable, bounded catalogue paging for the path-list writer."""

from dataclasses import replace
from queue import Queue

from PySide6.QtCore import QObject, Qt, Signal

from cdmw.domain.archives.catalogue import ArchivePage, ArchiveQueryHandle, ArchiveViewMode
from cdmw.domain.archives.catalogue_operations import FetchPageRequest
from cdmw.services.archive_path_export import ArchivePathExportRequest, ArchivePathExportResult, export_archive_paths
from cdmw.ui.shell.request_task_controller import RequestTaskController


class ArchivePathExportController(QObject):
    progress = Signal(int, int)
    finished = Signal(object)
    failed = Signal(str)
    _page_consumed = Signal()

    def __init__(self, archive, guard):
        super().__init__(guard)
        self._service = archive.archive_catalogue_service
        self._tasks = RequestTaskController(archive.shell, guard, worker_label="archive_path_export")
        self._pending = None
        self._handle = None
        self._offset = 0
        self.active = False
        self._closed = False
        self._batches = Queue(maxsize=1)
        self._page_consumed.connect(self._next_page, Qt.ConnectionType.QueuedConnection)
        self._service.result_ready.connect(self._result)
        self._service.request_failed.connect(self._failure)
        self._service.request_cancelled.connect(self._cancelled)

    def start(self, query, destination, folder=""):
        if self.active or self._closed:
            return
        self.active = True
        self._handle = None
        self._offset = 0
        self._batches = Queue(maxsize=1)
        batches = self._batches
        consumed, progress = self._page_consumed.emit, self.progress.emit

        def write(request, *, stop_event):
            try:
                return export_archive_paths(request, batches, stop_event=stop_event,
                                            page_consumed=consumed, progress=progress)
            except Exception as exc:
                # Deliver backend failures even if their text resembles shell cancellation.
                return ArchivePathExportResult(request.request_id, request.destination, 0, error=str(exc))

        if not self._tasks.start(
            ArchivePathExportRequest(0, destination, folder), write,
            status_message="Exporting file paths...",
            on_complete=self._complete, on_error=self._failed,
        ):
            self.active = False
            return
        try:
            self._pending = self._service.create_query(
                replace(query, view_mode=ArchiveViewMode.FLAT), ui_generation=0,
            )
        except Exception as exc:
            self._batches.put_nowait(exc)

    def _result(self, request_id, _operation, result):
        if not self.active or request_id != self._pending:
            return
        self._pending = None
        try:
            if self._handle is None:
                if not isinstance(result, ArchiveQueryHandle):
                    raise ValueError("The archive path query returned an unexpected result.")
                self._handle = result
                self._next_page()
                return
            handle = self._handle
            expected = min(512, handle.total_matches - self._offset)
            if (not isinstance(result, ArchivePage) or result.session_id != handle.session_id
                    or result.query_id != handle.query_id or result.generation != handle.generation
                    or result.total_matches != handle.total_matches or result.page_start != self._offset
                    or len(result.rows) != expected):
                raise ValueError("The archive path list changed or returned an incomplete page. Retry the export.")
            self._offset += len(result.rows)
            self._batches.put_nowait((result.rows, result.total_matches))
        except Exception as exc:
            self._batches.put_nowait(exc)

    def _next_page(self):
        if not self.active or self._closed or self._pending is not None or self._handle is None:
            return
        try:
            if self._offset == self._handle.total_matches:
                self._batches.put_nowait(None)
            else:
                self._pending = self._service.fetch_page(
                    FetchPageRequest(self._handle.query_id, self._offset, 512), ui_generation=0,
                )
        except Exception as exc:
            self._batches.put_nowait(exc)

    def _failure(self, request_id, error):
        if self.active and request_id == self._pending:
            self._pending = None
            self._batches.put_nowait(RuntimeError(getattr(error, "message", str(error))))

    def _cancelled(self, request_id):
        self._failure(request_id, "The archive path query was cancelled. Retry the export.")

    def _stop_query(self):
        pending, self._pending = self._pending, None
        if pending is not None:
            self._service.cancel(pending)

    def _complete(self, result):
        self.active = False
        self._stop_query()
        if result.error:
            self.failed.emit(result.error)
        else:
            self.finished.emit(result)

    def _failed(self, message):
        self.active = False
        self._stop_query()
        self.failed.emit(message)

    def close(self):
        self._closed = True
        self.active = False
        self._stop_query()
        self._tasks.request_shutdown()
