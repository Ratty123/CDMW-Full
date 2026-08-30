from __future__ import annotations

import threading
from pathlib import Path
from typing import Mapping, Sequence

from PySide6.QtCore import QObject, Signal, Slot

from cdmw.services.asset_authoring_service import AssetAuthoringService


class OpenImageIOTaskWorker(QObject):
    completed = Signal(object)
    cancelled = Signal(str)
    error = Signal(str)
    finished = Signal()

    def __init__(
        self,
        operation: str,
        paths: Sequence[Path | str],
        *,
        configured_paths: Mapping[str, object] | None = None,
        timeout_s: float | None = None,
        service: AssetAuthoringService | None = None,
    ) -> None:
        super().__init__()
        self.operation = str(operation or "")
        self.paths = tuple(paths)
        self.configured_paths = configured_paths
        self.timeout_s = timeout_s
        self.service = service or AssetAuthoringService()
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            if self.stop_event.is_set():
                self.cancelled.emit("OpenImageIO task stopped.")
                return
            result = self._run_operation()
            if self.stop_event.is_set():
                self.cancelled.emit("OpenImageIO task stopped.")
                return
            self.completed.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()

    def _run_operation(self) -> dict[str, object]:
        if self.operation == "metadata" and len(self.paths) == 1:
            return self.service.run_openimageio_metadata(
                self.paths[0],
                self.configured_paths,
                timeout_s=self.timeout_s,
            )
        if self.operation == "convert" and len(self.paths) == 2:
            return self.service.run_openimageio_convert(
                self.paths[0],
                self.paths[1],
                self.configured_paths,
                timeout_s=self.timeout_s,
            )
        if self.operation == "diff" and len(self.paths) == 2:
            return self.service.run_openimageio_diff(
                self.paths[0],
                self.paths[1],
                self.configured_paths,
                timeout_s=self.timeout_s,
            )
        raise ValueError(f"Unsupported OpenImageIO worker operation: {self.operation}")


__all__ = ["OpenImageIOTaskWorker"]
