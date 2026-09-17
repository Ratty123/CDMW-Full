"""Serial, coalesced cache requests owned by the shell close lifecycle."""

from dataclasses import replace

from PySide6.QtCore import QObject, Qt, Signal, Slot

from cdmw.ui.shell.close_controller import register_transient_worker_controller
from cdmw.workers.new_item_cleanup_worker import ModelSourceCleanupLane
from cdmw.workers.preview_cache_maintenance import PreviewCacheMaintenanceJob, PreviewCacheMaintenanceRequest


class PreviewCacheMaintenanceController(QObject):
    completed = Signal(object, str)

    def __init__(self, owner: QObject, shell: object) -> None:
        super().__init__(owner)
        self.lane = ModelSourceCleanupLane(parent=self)
        self._pending: dict[object, PreviewCacheMaintenanceRequest] = {}
        self._active: PreviewCacheMaintenanceJob | None = None
        self._closed = False
        register_transient_worker_controller(shell, self)

    def request(self, request: PreviewCacheMaintenanceRequest) -> None:
        if self._closed:
            return
        key = (request.cache_root, request.index_root)
        previous = self._pending.get(key)
        if previous is not None:
            request = replace(request, cleared_count=previous.cleared_count + request.cleared_count)
        self._pending[key] = request
        self._start_next()

    def _start_next(self) -> None:
        if self._closed or self._active is not None or not self._pending:
            return
        key = next(iter(self._pending))
        job = PreviewCacheMaintenanceJob(self._pending.pop(key), self)
        self._active = job
        job.finished.connect(self._finished, Qt.ConnectionType.QueuedConnection)
        self.lane.retire(job)

    @Slot(object, str)
    def _finished(self, request: PreviewCacheMaintenanceRequest, error: str) -> None:
        job, self._active = self._active, None
        if job is not None:
            job.deleteLater()
        if not self._closed:
            self.completed.emit(request, error)
            self._start_next()

    def request_shutdown(self) -> None:
        self._closed = True
        self._pending.clear()

    def iter_shutdown_workers(self):
        return self.lane.iter_shutdown_workers()
