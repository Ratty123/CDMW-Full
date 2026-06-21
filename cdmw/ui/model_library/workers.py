"""Background workers for Model Library tasks."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Signal, Slot


class ModelLibraryTaskWorker(QObject):
    completed = Signal(object)
    error = Signal(str)
    finished = Signal()
    progress = Signal(str)

    def __init__(self, task: Callable[[Callable[[str], None]], object]) -> None:
        super().__init__()
        self.task = task

    @Slot()
    def run(self) -> None:
        try:
            self.completed.emit(self.task(lambda message: self.progress.emit(str(message))))
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


__all__ = ["ModelLibraryTaskWorker"]
