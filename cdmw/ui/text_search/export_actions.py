"""Export actions for Text Search results."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Optional, Sequence

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QMessageBox

from cdmw.services.text_search_service import TextSearchResult
from cdmw.ui.text_search.workers import TextSearchExportWorker


class TextSearchExportMixin:
    def _resolve_export_root(self) -> Optional[Path]:
        text = self.export_root_edit.text().strip()
        if not text:
            self.status_message_requested.emit("Select an export root first.", True)
            return None
        return Path(text).expanduser()

    def _confirm_export(self, results: Sequence[TextSearchResult]) -> bool:
        answer = QMessageBox.question(
            self,
            "Export Files",
            f"Export {len(results):,} matched file(s) while preserving folder structure?",
        )
        return answer == QMessageBox.Yes

    def export_selected_results(self) -> None:
        selected = self.selected_results()
        if not selected:
            self.status_message_requested.emit("Select one or more results to export.", True)
            return
        self._export_results(selected, label="selected")

    def export_all_results(self) -> None:
        if not self.search_results:
            self.status_message_requested.emit("There are no search results to export.", True)
            return
        self._export_results(self.search_results, label="all results")

    def _export_results(self, results: Sequence[TextSearchResult], *, label: str) -> None:
        export_root = self._resolve_export_root()
        if export_root is None:
            return
        if not self._confirm_export(results):
            return
        if self.export_thread is not None:
            self.status_message_requested.emit("A text export is already running.", True)
            return

        request_id = self.export_request_id + 1
        self.export_request_id = request_id
        start_catalogue_export = getattr(self, "_start_catalogue_export", None)
        if callable(start_catalogue_export) and start_catalogue_export(
            request_id,
            results,
            export_root,
            label=label,
        ):
            return
        worker = TextSearchExportWorker(
            request_id=request_id,
            results=results,
            output_root=export_root,
            label=label,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.log_message.connect(self._handle_export_log)
        worker.progress_changed.connect(self._handle_export_progress)
        worker.completed.connect(self._handle_export_complete)
        worker.cancelled.connect(self._handle_export_cancelled)
        worker.error.connect(self._handle_export_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup_export_refs)
        self.export_worker = worker
        self.export_thread = thread
        self.search_progress_label.setText(f"Preparing to export {len(results):,} matched file(s)...")
        self.search_progress_bar.setRange(0, max(1, len(results)))
        self.search_progress_bar.setValue(0)
        self.search_progress_bar.setFormat(f"0 / {len(results):,}")
        self._update_controls()
        self.status_message_requested.emit("Starting text result export...", False)
        thread.start()

    def _handle_export_log(self, request_id: int, message: str) -> None:
        if request_id == self.export_request_id:
            self.append_log(message)

    def _handle_export_progress(self, request_id: int, current: int, total: int, detail: str) -> None:
        if request_id != self.export_request_id:
            return
        self.search_progress_label.setText(detail)
        self.search_progress_bar.setRange(0, max(1, total))
        self.search_progress_bar.setValue(min(max(0, current), max(1, total)))
        self.search_progress_bar.setFormat(f"{current:,} / {total:,}")

    def _handle_export_complete(self, request_id: int, payload: object, label: str) -> None:
        if request_id != self.export_request_id or not isinstance(payload, Mapping):
            return
        exported = int(payload.get("exported", 0) or 0)
        renamed = int(payload.get("renamed", 0) or 0)
        skipped = int(payload.get("skipped", 0) or 0)
        failed = int(payload.get("failed", 0) or 0)
        message = (
            f"Exported {exported:,} file(s) from {label}. "
            f"Renamed {renamed:,}, skipped {skipped:,}, failed {failed:,}."
        )
        self.search_progress_label.setText(message)
        self.search_progress_bar.setRange(0, 1)
        self.search_progress_bar.setValue(1)
        self.search_progress_bar.setFormat("Ready")
        self.status_message_requested.emit(message, False)
        self.append_log(message)

    def _handle_export_cancelled(self, request_id: int, message: str) -> None:
        if request_id != self.export_request_id:
            return
        self.search_progress_label.setText(message)
        self.search_progress_bar.setRange(0, 1)
        self.search_progress_bar.setValue(0)
        self.search_progress_bar.setFormat("Stopped")
        self.status_message_requested.emit(message, True)
        self.append_log(message)

    def _handle_export_error(self, request_id: int, message: str) -> None:
        if request_id != self.export_request_id:
            return
        self.search_progress_label.setText(message)
        self.search_progress_bar.setRange(0, 1)
        self.search_progress_bar.setValue(0)
        self.search_progress_bar.setFormat("Error")
        self.status_message_requested.emit(message, True)
        self.append_log(f"ERROR: {message}")

    def _cleanup_export_refs(self) -> None:
        self.export_thread = None
        self.export_worker = None
        self._update_controls()


__all__ = ["TextSearchExportMixin"]
