"""Latest-result source-mix tasks using the shell-owned utility worker."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

from PySide6.QtCore import QTimer

from cdmw.services.diagnostics_service import is_expected_cancellation_message
from cdmw.ui.archive_browser.static_replacement_qt_helpers import qt_object_is_valid


class SourceMixTaskController:
    def __init__(self, owner: object, guard: object) -> None:
        self._owner = owner
        self._guard = guard
        self._request_id = 0
        self._thread: object | None = None
        self._worker: object | None = None
        self._closed = False

    @property
    def active(self) -> bool:
        try:
            return bool(self._thread is not None and self._thread.isRunning())
        except RuntimeError:
            return False

    def start(
        self,
        request: object,
        operation: Callable[..., object],
        *,
        status_message: str,
        on_complete: Callable[[object], None],
        on_error: Callable[[str], None],
        on_idle: Callable[[], None] | None = None,
    ) -> bool:
        if (
            self._closed
            or bool(getattr(self._owner, "_shutting_down", False))
            or not qt_object_is_valid(self._guard)
        ):
            return False
        background_active = getattr(self._owner, "_background_task_active", None)
        if callable(background_active) and bool(background_active()):
            on_error("Another background task is still running. Wait for it before continuing.")
            return False
        run_task = getattr(self._owner, "_run_utility_task", None)
        if not callable(run_task):
            on_error("Background source processing is unavailable in this window.")
            return False
        self._request_id += 1
        request_id = self._request_id
        current_request = dataclasses.replace(request, request_id=request_id)

        def task(_log: Callable[[str], None], stop_event: object) -> object:
            return operation(current_request, stop_event=stop_event)

        def deliver(callback: Callable[[], None]) -> None:
            def when_idle() -> None:
                if not self._request_current(request_id):
                    return
                self._thread = None
                self._worker = None
                if on_idle is not None:
                    on_idle()
                callback()

            self._finish_when_idle(request_id, when_idle)

        def complete(result: object) -> None:
            if not self._request_current(request_id):
                return
            if int(getattr(result, "request_id", -1)) != request_id:
                deliver(lambda: None)
                return
            deliver(lambda: on_complete(result))

        def failed(message: str) -> None:
            if not self._request_current(request_id):
                return
            if is_expected_cancellation_message(message):
                deliver(lambda: None)
            else:
                deliver(lambda: on_error(str(message)))

        previous_thread = getattr(self._owner, "worker_thread", None)
        run_task(
            status_message=status_message,
            task=task,
            on_complete=complete,
            on_error=failed,
            task_accepts_cancel=True,
        )
        thread = getattr(self._owner, "worker_thread", None)
        worker = getattr(self._owner, "utility_worker", None)
        if thread is None or thread is previous_thread or worker is None:
            on_error("Background source processing could not start.")
            return False
        self._thread = thread
        self._worker = worker
        return True

    def request_shutdown(self) -> None:
        self._closed = True
        self._request_id += 1
        worker = self._worker
        stop = getattr(worker, "stop", None)
        if callable(stop):
            try:
                stop()
            except RuntimeError:
                pass

    def iter_shutdown_workers(self) -> tuple[tuple[str, object, object], ...]:
        if not self.active:
            return ()
        return (("source_mix", self._thread, self._worker),)

    def _request_current(self, request_id: int) -> bool:
        return bool(
            not self._closed
            and not bool(getattr(self._owner, "_shutting_down", False))
            and request_id == self._request_id
            and qt_object_is_valid(self._guard)
        )

    def _finish_when_idle(
        self,
        request_id: int,
        callback: Callable[[], None],
        attempt: int = 0,
    ) -> None:
        if not self._request_current(request_id):
            return
        owner_holds_thread = getattr(self._owner, "worker_thread", None) is self._thread
        if (self.active or owner_holds_thread) and attempt < 500:
            QTimer.singleShot(
                10,
                lambda: self._finish_when_idle(request_id, callback, attempt + 1),
            )
            return
        callback()


def source_mix_task_controller_for_guard(
    owner: object,
    guard: object,
    *,
    attribute: str = "_source_mix_task_controller",
) -> SourceMixTaskController:
    existing = getattr(guard, attribute, None)
    if isinstance(existing, SourceMixTaskController):
        return existing
    controller = SourceMixTaskController(owner, guard)
    setattr(guard, attribute, controller)
    finished = getattr(guard, "finished", None)
    connect = getattr(finished, "connect", None)
    if callable(connect):
        connect(lambda _result=0: controller.request_shutdown())
    return controller


__all__ = ["SourceMixTaskController", "source_mix_task_controller_for_guard"]
