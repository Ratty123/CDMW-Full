"""Cancellable worker for canonical resident .NET material compilation."""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import QObject, Signal, Slot

from cdmw.domain.cancellation import RunCancelled
from cdmw.services.mesh_dotnet_material_compiler import (
    MeshDotNetMaterialCompileRequest,
    compile_mesh_dotnet_material_update,
)


class MeshDotNetMaterialUpdateWorker(QObject):
    completed = Signal(object, object, float)
    error = Signal(object, str)
    finished = Signal()

    def __init__(self, request: MeshDotNetMaterialCompileRequest) -> None:
        super().__init__()
        self.request = request
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            if self.stop_event.is_set():
                return
            started = time.perf_counter()
            payload = compile_mesh_dotnet_material_update(
                self.request,
                cancelled=self.stop_event.is_set,
            )
            elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000.0)
            if not self.stop_event.is_set():
                self.completed.emit(self.request, payload, elapsed_ms)
        except RunCancelled:
            return
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(self.request, f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()


__all__ = ["MeshDotNetMaterialUpdateWorker"]
