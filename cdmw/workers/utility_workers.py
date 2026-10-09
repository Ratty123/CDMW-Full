"""Generic Qt utility workers."""

from __future__ import annotations

import threading
import logging
from dataclasses import dataclass
from typing import Callable, Literal

from PySide6.QtCore import QObject, Signal, Slot


@dataclass(frozen=True, slots=True)
class UtilityTaskOutcome:
    """Actual terminal result, independent of a later cancellation request."""

    kind: Literal['completed', 'committed', 'cancelled', 'failed']
    value: object = None
    message: str = ''


class UtilityWorker(QObject):
    log_message = Signal(str)
    progress_changed = Signal(int, int, str)
    completed = Signal(object)
    error = Signal(str)
    # Consumers choose this signal OR the legacy completed/error pair.
    outcome = Signal(object)
    finished = Signal()

    def __init__(
        self,
        task: Callable[..., object],
        *,
        task_accepts_progress: bool = False,
        task_accepts_cancel: bool = False,
        publishes_result: bool = False,
    ) -> None:
        super().__init__()
        self.task = task
        self.task_accepts_progress = task_accepts_progress
        self.task_accepts_cancel = task_accepts_cancel
        # A publishing task returns only after its service commits successfully.
        # Its service must raise RunCancelled before commit, not return a sentinel.
        self.publishes_result = publishes_result
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
            self.outcome.emit(UtilityTaskOutcome('committed' if self.publishes_result else 'completed', result))
            self.completed.emit(result)
        except Exception as exc:
            from cdmw.models import RunCancelled

            if not isinstance(exc, RunCancelled):
                try:
                    logging.getLogger(__name__).exception("Background utility task failed: %s", exc)
                except Exception:
                    pass
            self.outcome.emit(UtilityTaskOutcome('cancelled' if isinstance(exc, RunCancelled) else 'failed',
                                                 message=str(exc)))
            self.error.emit(str(exc))
        finally:
            self.finished.emit()


__all__ = ["UtilityWorker", "UtilityTaskOutcome"]
