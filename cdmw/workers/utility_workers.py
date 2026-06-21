"""Generic Qt utility workers."""

from __future__ import annotations

import threading
from typing import Callable

from PySide6.QtCore import QObject, Signal, Slot


class UtilityWorker(QObject):
    log_message = Signal(str)
    progress_changed = Signal(int, int, str)
    completed = Signal(object)
    error = Signal(str)
    finished = Signal()

    def __init__(
        self,
        task: Callable[..., object],
        *,
        task_accepts_progress: bool = False,
        task_accepts_cancel: bool = False,
    ) -> None:
        super().__init__()
        self.task = task
        self.task_accepts_progress = task_accepts_progress
        self.task_accepts_cancel = task_accepts_cancel
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            if self.task_accepts_progress and self.task_accepts_cancel:
                result = self.task(self.log_message.emit, self.progress_changed.emit, self.stop_event)
            elif self.task_accepts_progress:
                result = self.task(self.log_message.emit, self.progress_changed.emit)
            elif self.task_accepts_cancel:
                result = self.task(self.log_message.emit, self.stop_event)
            else:
                result = self.task(self.log_message.emit)
            self.completed.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


__all__ = ["UtilityWorker"]
