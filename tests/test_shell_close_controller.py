from __future__ import annotations

import threading
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QThread
from PySide6.QtWidgets import QApplication

from cdmw.ui.shell.close_controller import CloseControllerMixin


class _WaitProbeThread:
    def __init__(self, *results: bool) -> None:
        self._results = iter(results)
        self.wait_timeouts: list[int] = []

    def isRunning(self) -> bool:
        return False

    def wait(self, timeout: int) -> bool:
        self.wait_timeouts.append(timeout)
        return next(self._results)


class _CloseProbe:
    _close_after_workers_requested = True

    def __init__(self, thread: _WaitProbeThread) -> None:
        self._close_pending_worker_threads = [("worker", thread)]

    def _tracked_worker_threads(self) -> list[object]:
        return []


class _BlockingThread(QThread):
    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self.started_event = threading.Event()
        self.release_event = threading.Event()

    def run(self) -> None:
        self.started_event.set()
        self.release_event.wait()


class _QtCloseProbe(QObject):
    _close_after_workers_requested = False

    def __init__(self) -> None:
        super().__init__()
        self._close_pending_worker_threads: list[tuple[str, QThread]] = []

    def _tracked_worker_threads(self) -> list[object]:
        return []


def test_close_retains_finished_signal_thread_until_native_join_is_complete() -> None:
    thread = _WaitProbeThread(False, True)
    owner = _CloseProbe(thread)

    first = CloseControllerMixin._running_worker_thread_entries(owner)

    assert first == [("worker", thread)]
    assert owner._close_pending_worker_threads == [("worker", thread)]
    assert not thread.isRunning()

    second = CloseControllerMixin._running_worker_thread_entries(owner)

    assert second == []
    assert owner._close_pending_worker_threads == []
    assert thread.wait_timeouts == [0, 0]


def test_close_discovers_running_qthread_children_after_feature_refs_are_cleared() -> None:
    owner = _QtCloseProbe()
    thread = _BlockingThread(owner)
    thread.setObjectName("orphaned_feature_worker")
    thread.start()
    assert thread.started_event.wait(2.0)

    running = CloseControllerMixin._running_worker_thread_entries(owner)

    assert running == [("orphaned_feature_worker", thread)]
    thread.release_event.set()
    assert thread.wait(2000)
    assert CloseControllerMixin._running_worker_thread_entries(owner) == []


class _SignalProbe:
    def __init__(self) -> None:
        self.callbacks: list[object] = []

    def connect(self, callback: object, *_args: object) -> None:
        self.callbacks.append(callback)

    def emit(self, value: str) -> None:
        for callback in tuple(self.callbacks):
            callback(value)  # type: ignore[operator]


class _ArchiveBackendProbe:
    def __init__(self) -> None:
        self.state = type("State", (), {"value": "ready"})()
        self.state_changed = _SignalProbe()
        self.shutdown_calls = 0

    def shutdown(self) -> None:
        self.shutdown_calls += 1


class _CloseEventProbe:
    def __init__(self) -> None:
        self.ignored = False

    def ignore(self) -> None:
        self.ignored = True


class _ArchiveBackendCloseOwner:
    _close_force_accept = False
    _archive_backend_close_pending = False

    def __init__(self) -> None:
        self.archive_backend_client = _ArchiveBackendProbe()
        self.close_calls = 0

    def _running_worker_thread_entries(self) -> list[object]:
        return []

    def close(self) -> None:
        self.close_calls += 1


def test_close_waits_nonblocking_for_resident_archive_backend_shutdown() -> None:
    app = QApplication.instance() or QApplication([])
    owner = _ArchiveBackendCloseOwner()
    event = _CloseEventProbe()

    CloseControllerMixin.closeEvent(owner, event)

    assert event.ignored
    assert owner.archive_backend_client.shutdown_calls == 1
    assert owner._archive_backend_close_pending
    assert owner.close_calls == 0

    owner.archive_backend_client.state_changed.emit("stopped")
    app.processEvents()

    assert not owner._archive_backend_close_pending
    assert owner.close_calls == 1
