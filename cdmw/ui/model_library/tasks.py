"""Background task runner for Model Library UI actions."""

from __future__ import annotations

import re
from typing import Callable, Optional

from PySide6.QtCore import QThread, Slot

from cdmw.ui.model_library.workers import ModelLibraryTaskWorker as _ModelLibraryTaskWorker


class ModelLibraryTaskMixin:
    """Run cancellable Model Library tasks without blocking the UI thread."""

    def _run_task(
        self,
        status: str,
        task: Callable[[Callable[[str], None]], object],
        complete_handler: Callable[[object], None],
        *,
        error_handler: Optional[Callable[[str], None]] = None,
    ) -> None:
        if self._task_thread is not None and self._task_thread.isRunning():
            self._set_status("A model library task is already running.", error=True)
            return
        self._task_status_active = True
        self._set_status(status)
        self._task_complete_handler = complete_handler
        self._task_error_handler = error_handler
        thread = QThread(self)
        worker = _ModelLibraryTaskWorker(task)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._handle_task_progress)
        worker.completed.connect(self._handle_task_completed)
        worker.error.connect(self._handle_task_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._handle_task_finished)
        self._task_thread = thread
        self._task_worker = worker
        self.cancel_task_button.setEnabled(self._stop_event is not None)
        self.build_index_button.setEnabled(False)
        self.scan_local_button.setEnabled(False)
        self.search_mirror_button.setEnabled(False)
        self.show_indexed_button.setEnabled(False)
        self.mirror_results_view_button.setEnabled(False)
        self.local_results_view_button.setEnabled(False)
        self.refresh_results_view_button.setEnabled(False)
        self.download_button.setEnabled(False)
        self.download_import_button.setEnabled(False)
        self.open_file_url_button.setEnabled(False)
        self.preview_button.setEnabled(False)
        self.generate_icon_button.setEnabled(False)
        self.more_actions_button.setEnabled(False)
        self.delete_local_button.setEnabled(False)
        self.delete_no_texture_downloads_button.setEnabled(False)
        lower_status = status.lower()
        if "building" in lower_status or "index" in lower_status:
            self.build_index_button.setText("Building...")
        if "search" in lower_status:
            self.search_mirror_button.setText("Searching...")
        if "scanning" in lower_status:
            self.scan_local_button.setText("Scanning...")
        if "download" in lower_status:
            self.download_button.setText("Downloading...")
        thread.start()

    @Slot(str)
    def _handle_task_progress(self, message: str) -> None:
        self._set_status(str(message))

    @Slot(object)
    def _handle_task_completed(self, result: object) -> None:
        handler = self._task_complete_handler
        self._task_complete_handler = None
        if handler is not None:
            handler(result)

    @Slot(str)
    def _handle_task_error(self, message: str) -> None:
        handler = self._task_error_handler
        self._task_error_handler = None
        self._task_complete_handler = None
        if handler is not None:
            handler(str(message))
            return
        self._set_status(str(message), error=True)

    @Slot()
    def _handle_task_finished(self) -> None:
        self._task_thread = None
        self._task_worker = None
        self._task_error_handler = None
        self._stop_event = None
        self._task_status_active = False
        if hasattr(self, "task_status_label"):
            current_task_status = self.task_status_label.text()
            if current_task_status.startswith("Working: "):
                self.task_status_label.setText(f"Status: {current_task_status[len('Working: '):]}")
        if hasattr(self, "active_task_label"):
            current_active_status = self.active_task_label.text()
            if current_active_status.startswith("Working: "):
                self.active_task_label.setText(f"Status: {current_active_status[len('Working: '):]}")
        self.cancel_task_button.setEnabled(False)
        self.build_index_button.setText("Build Search Index")
        self.scan_local_button.setText("Show Local Models")
        self.search_mirror_button.setText("Search Mirror")
        self.show_indexed_button.setText("Popular")
        self.download_button.setText("Download Checked")
        if hasattr(self, "active_task_progress"):
            self.active_task_progress.setVisible(False)
        self.build_index_button.setEnabled(True)
        self.scan_local_button.setEnabled(True)
        self.search_mirror_button.setEnabled(True)
        self.show_indexed_button.setEnabled(True)
        self.mirror_results_view_button.setEnabled(True)
        self.local_results_view_button.setEnabled(True)
        self.refresh_results_view_button.setEnabled(True)
        self._update_selection_state()

    def _set_status(self, message: str, *, error: bool = False) -> None:
        self.status_label.setText(message)
        if hasattr(self, "task_status_label"):
            prefix = "Working: " if self._task_status_active else ("Error: " if error else "Status: ")
            self.task_status_label.setText(f"{prefix}{message}")
        self._update_active_task_progress(message, error=error)
        if self._task_status_active and hasattr(self, "results_status_label"):
            self.results_status_label.setText(f"Working: {message}")
        self.status_message_requested.emit(message, error)

    def _update_active_task_progress(self, message: str, *, error: bool = False) -> None:
        if not hasattr(self, "active_task_label") or not hasattr(self, "active_task_progress"):
            return
        text = str(message or "").strip()
        if not text:
            return
        if self._task_status_active:
            self.active_task_label.setText(f"Working: {text}")
            self.active_task_label.setVisible(True)
            self.active_task_progress.setVisible(True)
            match = re.search(r"(\d[\d,]*)\s*/\s*(\d[\d,]*)", text)
            if match:
                current = int(match.group(1).replace(",", ""))
                total = max(1, int(match.group(2).replace(",", "")))
                self.active_task_progress.setRange(0, total)
                self.active_task_progress.setValue(max(0, min(current, total)))
                self.active_task_progress.setFormat(f"{current:,} / {total:,}")
            else:
                self.active_task_progress.setRange(0, 0)
                self.active_task_progress.setFormat("Working...")
            return
        prefix = "Error: " if error else "Status: "
        self.active_task_label.setText(f"{prefix}{text}")
        self.active_task_label.setVisible(True)
        self.active_task_progress.setVisible(False)


__all__ = ["ModelLibraryTaskMixin"]
