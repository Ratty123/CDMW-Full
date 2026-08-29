"""Cancellable background publication for Mesh Editor Free Edit output."""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal, Slot

from cdmw.models import RunCancelled


class MeshFreeEditOutputWorker(QObject):
    progress_changed = Signal(int, int, str)
    completed = Signal(int, object)
    cancelled = Signal(int, str)
    error = Signal(int, str)
    finished = Signal()

    def __init__(self, request_id: int, service: object, session_id: str) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.service = service
        self.session_id = str(session_id or "")
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            if self.stop_event.is_set():
                raise RunCancelled("Free Edit output cancelled")
            self.progress_changed.emit(
                self.request_id,
                0,
                "Capturing the Free Edit revision...",
            )
            result = self.service.export_free_edit_output(
                self.session_id,
                stop_event=self.stop_event,
            )
            self.progress_changed.emit(self.request_id, 100, "Free Edit OBJ output is ready.")
            self.completed.emit(self.request_id, result)
        except RunCancelled:
            self.cancelled.emit(self.request_id, "Free Edit output cancelled.")
        except Exception as exc:
            if self.stop_event.is_set():
                self.cancelled.emit(self.request_id, "Free Edit output cancelled.")
            else:
                self.error.emit(self.request_id, f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()


__all__ = ["MeshFreeEditOutputWorker"]
