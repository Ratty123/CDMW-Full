from __future__ import annotations

import threading
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QThread
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow

from cdmw.ui.shell import close_controller as close_controller_module
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


class _ArchiveBackendProbe:
    def __init__(self) -> None:
        self.state = type("State", (), {"value": "ready"})()
        self.shutdown_calls = 0

    def shutdown(self) -> None:
        self.shutdown_calls += 1
        self.state.value = "stopping"


class _TimerProbe:
    def __init__(self) -> None:
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False


class _ShutdownCoordinatorWindow(CloseControllerMixin, QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.archive_backend_client = _ArchiveBackendProbe()
        self._close_after_workers_requested = False
        self._close_force_accept = False
        self._close_force_stop_requested = False
        self._close_finalized = False
        self._close_pending_started_at = 0.0
        self._close_pending_worker_threads: list[tuple[str, QThread]] = []
        self._close_pending_processes: list[object] = []
        self._close_pending_builder_dialogs: list[object] = []
        self._modeless_alignment_dialogs: dict[str, QDialog] = {}
        self._close_worker_wait_timer = _TimerProbe()
        self.events: list[str] = []
        self.status_messages: list[str] = []
        for name in (
            "_settings_save_timer",
            "_external_activation_timer",
            "_chainner_analysis_timer",
            "_compare_preview_timer",
            "archive_preview_debounce_timer",
            "archive_native_prefetch_timer",
            "archive_preview_loading_timer",
            "archive_selection_state_timer",
            "archive_item_icon_preload_timer",
        ):
            setattr(self, name, _TimerProbe())
        self.pending_compare_preview_selection = object()
        self.pending_compare_preview_request = object()
        self.pending_archive_preview_request = object()
        self.scheduled_archive_preview_request = object()
        self.compare_preview_request_id = 0
        self.archive_preview_request_id = 0
        self.archive_item_icon_preload_queue: list[object] = [object()]
        self.archive_item_icon_priority_queue: list[object] = [object()]
        self.archive_item_icon_visible_warmup_remaining = 1

    def _running_worker_thread_entries(self) -> list[object]:
        return []

    def _running_owned_process_entries(self) -> list[object]:
        return []

    def _request_tracked_workers_to_stop(self) -> None:
        self.events.append("workers_requested")

    def _shutdown_archive_isolated_renderer_host(self) -> None:
        self.events.append("renderer_requested")

    def _release_startup_splash(self) -> None:
        self.events.append("splash_released")

    def _save_detached_tool_geometries(self) -> None:
        self.events.append("geometry_saved")

    def set_status_message(self, message: str) -> None:
        self.status_messages.append(message)

    def _record_runtime_event(self, event: str, **_fields: object) -> None:
        self.events.append(event)

    def _finalize_close(self) -> None:
        assert self._modeless_alignment_dialogs == {}
        assert self.archive_backend_client.state.value == "stopped"
        self._close_finalized = True
        self.events.append("closed")


def test_one_close_hides_immediately_closes_builder_and_finalizes_after_backend() -> None:
    app = QApplication.instance() or QApplication([])
    window = _ShutdownCoordinatorWindow()
    builder = QDialog(window)
    builder.setWindowTitle("Mesh Replacement Builder")
    window._modeless_alignment_dialogs["builder"] = builder

    def builder_finished(_result: int) -> None:
        window.events.append("builder_finished")
        window._modeless_alignment_dialogs.pop("builder", None)

    builder.finished.connect(builder_finished)
    window.show()
    builder.show()
    app.processEvents()

    window.close()
    app.processEvents()

    assert not window.isVisible()
    assert not builder.isVisible()
    assert window.archive_backend_client.shutdown_calls == 1
    assert window._close_after_workers_requested
    assert not window._close_finalized
    assert "builder_finished" in window.events
    assert window.events.index("builder_finished") < window.events.index("workers_requested")

    window.close()
    app.processEvents()
    assert window.archive_backend_client.shutdown_calls == 1

    window.archive_backend_client.state.value = "stopped"
    window._finish_deferred_close_if_workers_stopped()
    app.processEvents()

    assert window._close_finalized
    assert window.events[-1] == "closed"


def test_force_stop_after_grace_targets_only_owned_external_processes(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[object] = []

    class _Process:
        def processId(self) -> int:
            return 42

        def kill(self) -> None:
            calls.append("kill")

    owner = type(
        "Owner",
        (),
        {"_record_close_event": lambda self, event, **fields: calls.append((event, fields))},
    )()
    monkeypatch.setattr(
        close_controller_module,
        "force_stop_windows_process_tree",
        lambda pid, *, include_root: calls.append((pid, include_root)),
    )

    CloseControllerMixin._force_stop_owned_external_processes(owner, [("renderer", _Process())])

    assert (42, False) in calls
    assert "kill" in calls
