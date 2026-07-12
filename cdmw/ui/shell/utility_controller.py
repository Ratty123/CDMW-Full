"""Generic background utility task runner for shell actions."""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QThread, QTimer

from cdmw.services.diagnostics_service import is_expected_cancellation_message
from cdmw.workers.utility_workers import UtilityWorker


class UtilityControllerMixin:
    """UtilityWorker orchestration shared by shell actions."""

    def _run_utility_task(
        self,
        *,
        status_message: str,
        task: Callable[..., object],
        on_complete: Optional[Callable[[object], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        show_archive_progress: bool = False,
        task_accepts_progress: bool = False,
        task_accepts_cancel: bool = False,
    ) -> None:
        if self._background_task_active():
            if self.worker_thread is not None:
                self.set_status_message(
                    "Another background task is still running. Wait for it to finish before starting this action.",
                    error=True,
                )
            return

        self.set_status_message(status_message)
        self.append_log(status_message)
        self._utility_updates_archive_progress = bool(show_archive_progress)
        if self._utility_updates_archive_progress:
            self._reset_archive_load_progress()
            self._set_archive_load_progress(status_message)
            self.append_archive_log(status_message)

        worker = UtilityWorker(
            task,
            task_accepts_progress=task_accepts_progress,
            task_accepts_cancel=task_accepts_cancel,
        )
        thread = QThread(self)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.log_message.connect(self._handle_utility_log_message)
        worker.progress_changed.connect(self._handle_utility_progress_changed)
        worker.completed.connect(self._handle_utility_completed)
        worker.error.connect(self._handle_worker_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup_worker_refs)

        self.utility_worker = worker
        self.worker_thread = thread
        self._utility_completion_handler = on_complete
        self._utility_error_handler = on_error
        self.set_busy(True, build_mode=task_accepts_cancel)
        thread.start()

    def _run_when_background_idle(
        self,
        callback: Callable[[], None],
        *,
        label: str,
        attempt: int = 0,
    ) -> None:
        if self.worker_thread is None:
            callback()
            return
        if attempt == 0:
            self.append_log(f"Waiting for the current background task to finish before {label}.")
        if attempt >= 100:
            message = f"Could not continue {label} because the previous task did not finish cleanly."
            self.set_status_message(message, error=True)
            self.append_log(f"ERROR: {message}")
            return
        QTimer.singleShot(
            50,
            lambda: self._run_when_background_idle(callback, label=label, attempt=attempt + 1),
        )

    def _run_utility_task_when_idle(
        self,
        *,
        status_message: str,
        task: Callable[..., object],
        on_complete: Optional[Callable[[object], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        show_archive_progress: bool = False,
        task_accepts_progress: bool = False,
        task_accepts_cancel: bool = False,
        attempt: int = 0,
    ) -> None:
        if self.worker_thread is None:
            self._run_utility_task(
                status_message=status_message,
                task=task,
                on_complete=on_complete,
                on_error=on_error,
                show_archive_progress=show_archive_progress,
                task_accepts_progress=task_accepts_progress,
                task_accepts_cancel=task_accepts_cancel,
            )
            return
        if attempt == 0:
            self.append_log("Waiting for the current background task to finish before starting the next step.")
            if show_archive_progress:
                self.append_archive_log("Waiting for the current background task to finish before starting the next step.")
        if attempt >= 100:
            message = "Could not start the next background step because the previous task did not finish cleanly."
            self.set_status_message(message, error=True)
            self.append_log(f"ERROR: {message}")
            if show_archive_progress:
                self.append_archive_log(f"ERROR: {message}")
            if on_error is not None:
                on_error(message)
            return
        QTimer.singleShot(
            50,
            lambda: self._run_utility_task_when_idle(
                status_message=status_message,
                task=task,
                on_complete=on_complete,
                on_error=on_error,
                show_archive_progress=show_archive_progress,
                task_accepts_progress=task_accepts_progress,
                task_accepts_cancel=task_accepts_cancel,
                attempt=attempt + 1,
            ),
        )

    def _handle_utility_log_message(self, message: str) -> None:
        self.append_log(message)
        if not self._utility_updates_archive_progress:
            return
        if message.startswith("[") and ("] EXTRACT " in message or "] FAIL " in message):
            return
        self._set_archive_load_progress(message)
        self.append_archive_log(message)
        self.set_status_message(message)

    def _handle_utility_progress_changed(self, current: int, total: int, detail: str) -> None:
        if not self._utility_updates_archive_progress:
            return
        detail_text = str(detail or "").strip() or "Working..."
        self._set_archive_load_progress(detail_text, current, total)
        self.set_status_message(detail_text)

    def _handle_utility_completed(self, result: object) -> None:
        if self._utility_completion_handler is not None:
            self._utility_completion_handler(result)

    def _handle_worker_error(self, message: str) -> None:
        if hasattr(self, "_archive_scan_progress_timer"):
            self._archive_scan_progress_timer.stop()
            self._archive_scan_progress_pending = None
        if self._utility_error_handler is not None:
            try:
                self._utility_error_handler(str(message))
            except Exception as exc:
                self.append_log(f"ERROR: Utility error handler failed: {exc}")
        if is_expected_cancellation_message(message):
            self.set_status_message(message, error=True)
            self.append_log(message)
            if self.archive_scan_worker is not None or self.archive_filter_worker is not None or self._utility_updates_archive_progress:
                self.append_archive_log(message)
                self._set_archive_load_progress(message, phase="Stopping", percent=0, allow_decrease=True)
                self._write_heartbeat("running")
                self._release_startup_splash()
            return
        self._write_crash_report(
            "worker_error",
            "Background worker error",
            str(message),
            context=self._collect_crash_context(),
        )
        self.set_status_message(message, error=True)
        self.append_log(f"ERROR: {message}")
        if self.archive_scan_worker is not None or self.archive_filter_worker is not None or self._utility_updates_archive_progress:
            self.append_archive_log(f"ERROR: {message}")
            if self.archive_scan_worker is not None:
                self._set_archive_cache_health(
                    "unhealthy",
                    f"Cache Status: Unhealthy. Archive cache build failed: {message}",
                )
            self._set_archive_load_progress(
                f"Archive browser task failed: {message}",
                phase="Failed",
                percent=0,
                allow_decrease=True,
            )
            self._write_heartbeat("running")
            self._release_startup_splash()

    def _cleanup_worker_refs(self, owner_thread: object | None = None) -> None:
        if owner_thread is not None and self.worker_thread is not owner_thread:
            return
        rerun_archive_filter = bool(self.archive_filter_apply_pending and not self._shutting_down and self.archive_entries)
        archive_finalize_pending = bool(self.archive_scan_finalize_pending)
        utility_updates_archive_progress = bool(self._utility_updates_archive_progress)
        refresh_archive_browser = bool(
            self.archive_browser_refresh_pending
            and not rerun_archive_filter
            and not self._shutting_down
            and self.archive_entries
            and self._is_tool_visible_or_current(self.archive_browser_tab)
        )
        self.worker_thread = None
        self.scan_worker = None
        self.archive_scan_worker = None
        self.archive_filter_worker = None
        self.build_worker = None
        self.dds_to_png_worker = None
        self.utility_worker = None
        self._utility_completion_handler = None
        self._utility_error_handler = None
        self._utility_updates_archive_progress = False
        self.archive_filter_apply_pending = False
        if not archive_finalize_pending:
            self.set_busy(False, build_mode=False)
        if (
            self.archive_sidecar_pending_start
            and self.archive_sidecar_thread is None
            and self.archive_entries
            and self._current_archive_performance_settings().enable_sidecar_indexing
        ):
            QTimer.singleShot(0, self._start_archive_sidecar_index_worker)
        if utility_updates_archive_progress and self.archive_scan_worker is None and self.archive_filter_worker is None:
            detail = str(getattr(self, "_archive_load_progress_detail", "") or "Archive task complete.")
            self._set_archive_load_progress(detail, phase="Ready", percent=100)
        if rerun_archive_filter:
            QTimer.singleShot(0, self._apply_archive_filter)
        elif refresh_archive_browser:
            QTimer.singleShot(0, self._refresh_archive_browser_view)
        else:
            QTimer.singleShot(0, self._maybe_release_startup_after_archive_ready)


__all__ = ["UtilityControllerMixin"]
