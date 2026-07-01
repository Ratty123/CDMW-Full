from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QThread, Qt, Slot
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
        worker.completed.connect(self._task_completed_on_ui, Qt.ConnectionType.QueuedConnection)
        worker.error.connect(self._task_error_on_ui, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(self._task_finished_on_ui, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
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
        self._task_thread = None
        self._task_worker = None
        self._task_success_callback = None
        self._busy_task_label = ""
        self._refresh_ui()
