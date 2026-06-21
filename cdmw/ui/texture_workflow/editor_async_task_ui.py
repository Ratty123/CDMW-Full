from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QThread, Slot
from PySide6.QtWidgets import QMessageBox

from cdmw.constants import APP_TITLE
from cdmw.ui.texture_workflow.editor_status_state import (
    texture_editor_busy_status_text,
    texture_editor_task_failed_status_text,
)
from cdmw.ui.texture_workflow.editor_workers import TextureEditorTaskWorker


class TextureEditorAsyncTaskUiMixin:
    """Own Texture Editor background task startup and completion routing."""

    def _run_async_task(
        self,
        *,
        label: str,
        task: Callable[[], object],
        on_success: Callable[[object], None],
    ) -> bool:
        if self._busy():
            self._set_status(texture_editor_busy_status_text(), True)
            return False
        self._busy_task_label = label
        self._task_success_callback = on_success
        self._set_status(label, False)
        thread = QThread(self)
        worker = TextureEditorTaskWorker(task)
        worker.moveToThread(thread)
        worker.completed.connect(self._handle_async_task_completed)
        worker.error.connect(self._handle_async_task_error)
        worker.finished.connect(thread.quit)
        thread.finished.connect(self._handle_async_task_finished)
        thread.started.connect(worker.run)
        self._task_thread = thread
        self._task_worker = worker
        self._refresh_ui()
        thread.start()
        return True

    @Slot(object)
    def _handle_async_task_completed(self, result: object) -> None:
        callback = self._task_success_callback
        if callback is not None:
            callback(result)

    @Slot(str)
    def _handle_async_task_error(self, message: str) -> None:
        QMessageBox.warning(self, APP_TITLE, message)
        self._set_status(texture_editor_task_failed_status_text(self._busy_task_label), True)

    @Slot()
    def _handle_async_task_finished(self) -> None:
        thread = self._task_thread
        worker = self._task_worker
        self._task_thread = None
        self._task_worker = None
        self._task_success_callback = None
        self._busy_task_label = ""
        if worker is not None:
            worker.deleteLater()
        if thread is not None:
            thread.deleteLater()
        self._refresh_ui()
