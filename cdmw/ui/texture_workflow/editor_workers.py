"""Background workers used by the texture editor."""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence

from PySide6.QtCore import QObject, Signal, Slot

from cdmw.core.research import summarize_ui_reference_constraints


class TextureEditorTaskWorker(QObject):
    completed = Signal(object)
    error = Signal(str)
    finished = Signal()

    def __init__(self, task: Callable[[], object]) -> None:
        super().__init__()
        self._task = task
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            if self.stop_event.is_set():
                return
            result = self._task()
            if not self.stop_event.is_set():
                self.completed.emit(result)
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(str(exc))
        finally:
            self.finished.emit()


class TextureEditorUIConstraintWorker(QObject):
    completed = Signal(str, str)
    error = Signal(str)
    finished = Signal()

    def __init__(self, archive_entries: Sequence[object], target_path: str) -> None:
        super().__init__()
        self._archive_entries = list(archive_entries)
        self._target_path = str(target_path or "").strip()
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            if self.stop_event.is_set() or not self._target_path:
                return
            warning_text = ""
            summary = summarize_ui_reference_constraints(
                self._archive_entries,
                self._target_path,
                stop_event=self.stop_event,
            )
            if not self.stop_event.is_set():
                warning_text = str(summary.get("warning_text", "") or "")
                self.completed.emit(self._target_path, warning_text)
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(str(exc))
        finally:
            self.finished.emit()


__all__ = ["TextureEditorTaskWorker", "TextureEditorUIConstraintWorker"]
