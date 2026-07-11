"""Async loose-donor folder scan and incremental archive mapping."""

from __future__ import annotations

import time
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from cdmw.workers.directory_scan_workers import (
    DirectoryScanRequest,
    DirectoryScanResult,
    DirectoryScanWorker,
)


@dataclass(frozen=True, slots=True)
class LooseDonorScanResult:
    folder: Path
    candidates: tuple[tuple[object, Path, str], ...]
    truncated: bool


class LooseDonorScanController(QObject):
    """Keep scan I/O off the UI thread and map results in short UI slices."""

    completed = Signal(object)
    error = Signal(str)

    def __init__(
        self,
        *,
        thread_parent: QObject,
        map_file: Callable[[Path], Sequence[object]],
        entry_key: Callable[[object], object],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._thread_parent = thread_parent
        self._map_file = map_file
        self._entry_key = entry_key
        self._request_id = 0
        self._jobs: dict[int, tuple[DirectoryScanWorker, QThread]] = {}
        self._closed = False
        self._paths: tuple[Path, ...] = ()
        self._path_index = 0
        self._mapped: list[tuple[object, Path, str]] = []
        self._existing_keys: set[object] = set()
        self._folder = Path()
        self._truncated = False
        self._mapping_request_id = 0
        self._mapping_timer = QTimer(self)
        self._mapping_timer.setSingleShot(True)
        self._mapping_timer.timeout.connect(self._continue_mapping)

    def start(
        self,
        *,
        folder: Path,
        files_root: Path,
        suffixes: Sequence[str],
        existing_keys: Collection[object],
    ) -> int:
        self.stop()
        self._closed = False
        self._request_id += 1
        request_id = self._request_id
        self._folder = Path(folder)
        self._existing_keys = set(existing_keys)
        self._paths = ()
        self._path_index = 0
        self._mapped = []
        self._truncated = False
        request = DirectoryScanRequest(
            request_id=request_id,
            root=Path(files_root),
            suffixes=tuple(suffixes),
            max_results=100_000,
            max_entries=2_000_000,
        )
        worker = DirectoryScanWorker(request)
        thread = QThread(self._thread_parent)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._handle_scan_ready)
        worker.error.connect(self._handle_scan_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda rid=request_id: self._clear_job(rid))
        self._jobs[request_id] = (worker, thread)
        thread.start()
        return request_id

    def stop(self) -> None:
        self._request_id += 1
        self._mapping_timer.stop()
        for worker, _thread in tuple(self._jobs.values()):
            worker.stop()

    def close(self) -> None:
        self._closed = True
        self.stop()

    def is_running(self) -> bool:
        return bool(self._jobs)

    def _clear_job(self, request_id: int) -> None:
        self._jobs.pop(int(request_id), None)

    @Slot(int, object)
    def _handle_scan_ready(self, request_id: int, payload: object) -> None:
        if self._closed or request_id != self._request_id or not isinstance(payload, DirectoryScanResult):
            return
        self._paths = payload.paths
        self._path_index = 0
        self._mapped = []
        self._truncated = payload.truncated
        self._mapping_request_id = request_id
        self._mapping_timer.start(0)

    @Slot(int, str)
    def _handle_scan_error(self, request_id: int, message: str) -> None:
        if not self._closed and request_id == self._request_id:
            self.error.emit(message)

    @Slot()
    def _continue_mapping(self) -> None:
        if self._closed or self._mapping_request_id != self._request_id:
            return
        deadline = time.perf_counter() + 0.008
        while (
            self._path_index < len(self._paths)
            and len(self._mapped) < 800
            and time.perf_counter() < deadline
        ):
            local_path = self._paths[self._path_index]
            self._path_index += 1
            for entry in self._map_file(local_path):
                key = self._entry_key(entry)
                if key in self._existing_keys:
                    continue
                self._existing_keys.add(key)
                self._mapped.append((entry, local_path, f"mapped from {local_path.name}"))
                if len(self._mapped) >= 800:
                    break
        if self._path_index < len(self._paths) and len(self._mapped) < 800:
            self._mapping_timer.start(0)
            return
        self.completed.emit(
            LooseDonorScanResult(
                folder=self._folder,
                candidates=tuple(self._mapped),
                truncated=self._truncated,
            )
        )


__all__ = ["LooseDonorScanController", "LooseDonorScanResult"]
