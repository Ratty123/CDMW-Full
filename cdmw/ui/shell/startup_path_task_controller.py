"""Latest-wins workers for startup archive-path validation and discovery."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QThread, QTimer

from cdmw.services.archive_environment_service import (
    autodetect_archive_package_roots,
    looks_like_archive_package_root,
)
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.workers.utility_workers import UtilityWorker


@dataclass(frozen=True, slots=True)
class StartupPathTaskResult:
    request_id: int
    kind: str
    payload: object
    logs: tuple[str, ...] = ()
    error: str = ""


def validate_startup_archive_path(
    path_text: str,
    stop_event: Optional[threading.Event] = None,
) -> tuple[str, bool, str]:
    source_text = str(path_text or "").strip()
    raise_if_cancelled(stop_event, "Archive path validation cancelled.")
    path = Path(source_text).expanduser()
    valid = looks_like_archive_package_root(path)
    try:
        resolved = str(path.resolve()) if valid else ""
    except OSError:
        resolved = str(path) if valid else ""
    return source_text, valid, resolved


class StartupPathTaskControllerMixin:
    def _initialize_startup_path_tasks(self) -> None:
        self._validated_path_text = ""
        self._validated_path_ok = False
        self._validated_resolved_path = ""
        self._path_task_request_id = 0
        self._path_task_thread: Optional[QThread] = None
        self._path_task_worker: Optional[UtilityWorker] = None
        self._pending_path_task: Optional[
            tuple[int, str, Callable[[Callable[[str], None], threading.Event], object]]
        ] = None
        self._path_validation_timer = QTimer(self)
        self._path_validation_timer.setSingleShot(True)
        self._path_validation_timer.setInterval(120)
        self._path_validation_timer.timeout.connect(self._start_path_validation)

    def _queue_path_task(
        self,
        kind: str,
        task: Callable[[Callable[[str], None], threading.Event], object],
    ) -> int:
        request_id = self._path_task_request_id + 1
        self._path_task_request_id = request_id
        pending = (request_id, str(kind), task)
        if self._path_task_worker is not None:
            self._pending_path_task = pending
            self._path_task_worker.stop()
            return request_id
        self._start_path_task(pending)
        return request_id

    def _start_path_task(
        self,
        pending: tuple[int, str, Callable[[Callable[[str], None], threading.Event], object]],
    ) -> None:
        request_id, kind, task = pending

        def wrapped(_log: Callable[[str], None], stop_event: threading.Event) -> StartupPathTaskResult:
            logs: list[str] = []
            try:
                payload = task(logs.append, stop_event)
                return StartupPathTaskResult(request_id, kind, payload, tuple(logs))
            except Exception as exc:
                return StartupPathTaskResult(request_id, kind, None, tuple(logs), str(exc))

        worker = UtilityWorker(wrapped, task_accepts_cancel=True)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._handle_path_task_completed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._handle_path_task_finished)
        self._path_task_worker = worker
        self._path_task_thread = thread
        thread.start()

    def _handle_path_task_finished(self, thread: Optional[QThread] = None) -> None:
        thread = thread or self._path_task_thread
        if thread is not None:
            try:
                if not thread.wait(0):
                    QTimer.singleShot(1, lambda target_thread=thread: self._handle_path_task_finished(target_thread))
                    return
            except RuntimeError:
                pass
        if self._path_task_thread is not thread:
            if thread is not None:
                thread.deleteLater()
            return
        self._path_task_worker = None
        self._path_task_thread = None
        if thread is not None:
            thread.deleteLater()
        pending = self._pending_path_task
        self._pending_path_task = None
        if pending is not None and self.isVisible():
            self._start_path_task(pending)

    def _handle_path_task_completed(self, result: object) -> None:
        if not isinstance(result, StartupPathTaskResult):
            return
        if result.request_id != self._path_task_request_id:
            return
        if result.kind == "validate":
            self._handle_path_validation_result(result)
        elif result.kind == "autodetect":
            self._handle_autodetect_result(result)

    def _start_path_validation(self) -> None:
        path_text = self.path_edit.text().strip()
        if not path_text or self._autodetect_busy:
            return
        self._queue_path_task(
            "validate",
            lambda _log, stop_event: validate_startup_archive_path(path_text, stop_event),
        )

    def _handle_path_validation_result(self, result: StartupPathTaskResult) -> None:
        if result.error:
            return
        payload = result.payload if isinstance(result.payload, tuple) else ()
        if len(payload) != 3:
            return
        path_text, valid, resolved = str(payload[0]), bool(payload[1]), str(payload[2])
        if path_text != self.path_edit.text().strip():
            return
        self._validated_path_text = path_text
        self._validated_path_ok = valid
        self._validated_resolved_path = resolved if valid else ""
        self.continue_button.setEnabled(valid and not self._autodetect_busy)
        self._set_status(
            "Ready to build the archive cache for this path."
            if valid
            else "Waiting for a valid Crimson Desert folder or package root.",
            error=not valid,
        )

    def _run_initial_autodetect(self) -> None:
        if self._autodetect_started or self.path_edit.text().strip():
            return
        self._run_autodetect()

    def _run_autodetect(self) -> None:
        if self._autodetect_busy:
            return
        self._autodetect_started = True
        self._set_busy(True)
        self._set_status("Checking Steam libraries and common custom install locations...")
        if self._startup_splash is not None:
            try:
                self._startup_splash.set_detail("Auto-detecting Crimson Desert path...")
            except Exception:
                pass
        self._queue_path_task(
            "autodetect",
            lambda log, stop_event: tuple(
                str(path)
                for path in autodetect_archive_package_roots(
                    on_log=log,
                    stop_event=stop_event,
                )
            ),
        )

    def _handle_autodetect_result(self, result: StartupPathTaskResult) -> None:
        self._set_busy(False)
        candidates = [str(path) for path in result.payload] if isinstance(result.payload, tuple) else []
        self.candidates_combo.blockSignals(True)
        try:
            self.candidates_combo.clear()
            self.candidates_combo.addItems(candidates)
            self.candidates_combo.setVisible(len(candidates) > 1)
        finally:
            self.candidates_combo.blockSignals(False)
        if candidates:
            self.path_edit.setText(candidates[0])
            self._path_validation_timer.stop()
            self._validated_path_text = candidates[0]
            self._validated_path_ok = True
            self._validated_resolved_path = candidates[0]
            self.continue_button.setEnabled(True)
            self._set_status(
                "Auto-detected a Crimson Desert package root. Continue to build the cache."
                if len(candidates) == 1
                else "Auto-detected multiple package roots. Pick one, then continue to build the cache."
            )
            return
        if result.error:
            self._set_status(
                f"Auto-detect failed: {result.error}. Use Browse to select the folder manually.",
                error=True,
            )
            return
        detail = result.logs[-1] if result.logs else "No valid Crimson Desert package root was auto-detected."
        self._set_status(f"{detail} Use Browse to select the folder manually.", error=True)

    def request_shutdown(self) -> None:
        self._path_task_request_id += 1
        self._pending_path_task = None
        self._path_validation_timer.stop()
        if self._path_task_worker is not None:
            self._path_task_worker.stop()

    def iter_shutdown_workers(self) -> tuple[tuple[str, Optional[QThread], Optional[UtilityWorker]], ...]:
        return (("startup archive path", self._path_task_thread, self._path_task_worker),)


__all__ = [
    "StartupPathTaskControllerMixin",
    "StartupPathTaskResult",
    "validate_startup_archive_path",
]
