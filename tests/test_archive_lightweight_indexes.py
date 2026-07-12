from __future__ import annotations

import os
import threading
import time
import inspect
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEventLoop, QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid as qt_wrapper_is_valid

from cdmw.models import ArchiveEntry, ArchiveEntryIdentity, RunCancelled
from cdmw.ui.archive_browser.controller import ArchiveBrowserRowPayloadMixin
from cdmw.ui.archive_browser.index_workers import ArchiveIndexWorkerMixin, _ArchiveIndexUiReceiver
from cdmw.ui.archive_browser.mesh_modify_original import ArchiveMeshModifyOriginalMixin
from cdmw.ui.archive_browser.scan_lifecycle import ArchiveScanLifecycleMixin
from cdmw.ui.archive_browser.virtual_path_lookup import ArchiveVirtualPathLookupMixin
from cdmw.workers.archive_scan_workers import build_archive_lightweight_lookup_indexes


_APP = QApplication.instance() or QApplication([])


class _IndexEntry:
    __slots__ = ("path", "extension", "pamt_path", "offset", "paz_index")

    def __init__(self, path: str, extension: str, offset: int) -> None:
        self.path = path
        self.extension = extension
        self.pamt_path = Path("0009/0.pamt")
        self.offset = offset
        self.paz_index = 0

    @property
    def identity(self) -> ArchiveEntryIdentity:
        return ArchiveEntryIdentity(
            self.path.casefold(),
            str(self.pamt_path).replace("\\", "/").casefold(),
            self.paz_index,
            self.offset,
        )


def test_lightweight_indexes_keep_500k_entry_work_off_heartbeat_thread() -> None:
    entries = [_IndexEntry(f"object/model/{index}.bin", ".bin", index) for index in range(499_998)]
    pam = _IndexEntry("character/model/body.pam", ".pam", 499_998)
    pamlod = _IndexEntry("character/model/body.pamlod", ".pamlod", 499_999)
    entries.extend((pam, pamlod))
    result: list[object] = []
    failure: list[BaseException] = []

    def build() -> None:
        try:
            result.append(build_archive_lightweight_lookup_indexes(entries))  # type: ignore[arg-type]
        except BaseException as exc:
            failure.append(exc)

    worker = threading.Thread(target=build)
    worker.start()
    heartbeat_gaps: list[float] = []
    previous = time.perf_counter()
    while worker.is_alive():
        time.sleep(0.005)
        current = time.perf_counter()
        heartbeat_gaps.append(current - previous)
        previous = current
    worker.join()

    assert not failure
    extension_index, extension_counts, mesh_path_index, companion_index = result[0]  # type: ignore[misc]
    assert extension_counts[".bin"] == 499_998
    assert mesh_path_index["character/model/body.pam"] == [pam]
    assert companion_index[pam.identity] is pamlod
    assert companion_index[pamlod.identity] is pam
    assert max(heartbeat_gaps, default=0.0) < 0.2
    assert len(extension_index[".bin"]) == 499_998


def test_lightweight_index_build_honors_cancellation() -> None:
    stop_event = threading.Event()
    stop_event.set()
    with pytest.raises(RunCancelled):
        build_archive_lightweight_lookup_indexes(
            [_IndexEntry("character/model/body.pam", ".pam", 1)],  # type: ignore[list-item]
            stop_event=stop_event,
        )


def test_stale_basic_index_result_is_rejected() -> None:
    class Owner:
        _handle_archive_basic_index_complete = ArchiveIndexWorkerMixin._handle_archive_basic_index_complete

        def __init__(self) -> None:
            self._shutting_down = False
            self.archive_basic_index_request_id = 2
            self.archive_entries_by_normalized_path = {"current": ()}
            self.archive_entries_by_basename = {"current": ()}
            self.archive_entries_by_extension = {".current": ()}
            self.archive_entries_by_role = {"current": ()}
            self.events: list[tuple[str, dict[str, object]]] = []

        def _record_runtime_event(self, event: str, **fields: object) -> None:
            self.events.append((event, fields))

    owner = Owner()
    owner._handle_archive_basic_index_complete(
        {
            "request_id": 1,
            "path_index": {"stale": ()},
            "basename_index": {"stale": ()},
            "extension_index": {".stale": ()},
            "role_index": {"stale": ()},
        }
    )

    assert owner.archive_entries_by_normalized_path == {"current": ()}
    assert owner.events[0][0] == "archive_basic_index_result_ignored"


def test_archive_index_workers_queue_ui_callbacks_through_qobject_receiver() -> None:
    basic = inspect.getsource(ArchiveIndexWorkerMixin._start_archive_basic_index_worker)
    enhanced = inspect.getsource(ArchiveIndexWorkerMixin._start_archive_enhanced_index_worker)
    derived = inspect.getsource(ArchiveIndexWorkerMixin._start_archive_derived_index_cache_writer)

    for source in (basic, enhanced):
        assert "_ArchiveIndexUiReceiver" in source
        assert "Qt.ConnectionType.QueuedConnection" in source
        assert "worker.progress_changed.connect(receiver.handle_progress" in source
        assert "worker.error.connect(receiver.handle_error" in source
        assert "lambda" not in source
    assert "_ArchiveIndexUiReceiver" in derived
    assert "worker.log_message.connect(receiver.handle_log, Qt.ConnectionType.QueuedConnection)" in derived
    assert "thread.finished.connect(receiver.handle_thread_finished, Qt.ConnectionType.QueuedConnection)" in derived


@pytest.mark.parametrize("kind", ("basic", "enhanced"))
def test_archive_index_receiver_delivers_worker_lifecycle_on_ui_thread(kind: str) -> None:
    app = _APP
    loop = QEventLoop()
    events: list[tuple[str, QThread, object | None]] = []

    class Owner(QObject):
        def record(self, event: str, detail: object | None = None) -> None:
            events.append((event, QThread.currentThread(), detail))

        def _handle_archive_basic_index_progress(
            self,
            _current: int,
            _total: int,
            _detail: str,
            *,
            request_id: int,
        ) -> None:
            self.record("progress", request_id)

        def _handle_archive_enhanced_index_progress(
            self,
            _current: int,
            _total: int,
            _detail: str,
            *,
            request_id: int,
        ) -> None:
            self.record("progress", request_id)

        def _handle_archive_basic_index_complete(self, result: object) -> None:
            self.record("completed", result)

        def _handle_archive_enhanced_index_complete(self, result: object) -> None:
            self.record("completed", result)

        def _handle_archive_basic_index_error(self, message: str, *, request_id: int) -> None:
            self.record("error", (message, request_id))

        def _handle_archive_enhanced_index_error(self, message: str, *, request_id: int) -> None:
            self.record("error", (message, request_id))

        def _cleanup_archive_basic_index_refs(self, request_id: int, owner_thread: object) -> None:
            self.record("cleanup", (request_id, id(owner_thread), owner_thread.wait(0)))

        def _cleanup_archive_enhanced_index_refs(self, request_id: int, owner_thread: object) -> None:
            self.record("cleanup", (request_id, id(owner_thread), owner_thread.wait(0)))

    class Worker(QObject):
        progress = Signal(int, int, str)
        completed = Signal(object)
        error = Signal(str)
        finished = Signal()

        @Slot()
        def run(self) -> None:
            self.progress.emit(1, 2, "working")
            self.completed.emit({"request_id": 7})
            self.error.emit("expected test error")
            self.finished.emit()

    owner = Owner()
    thread = QThread()
    worker = Worker()
    worker.moveToThread(thread)
    receiver = _ArchiveIndexUiReceiver(owner, 7, kind, thread)
    setattr(owner, f"archive_{kind}_index_ui_receiver", receiver)

    thread.started.connect(worker.run)
    worker.progress.connect(receiver.handle_progress, Qt.ConnectionType.QueuedConnection)
    worker.completed.connect(receiver.handle_completed, Qt.ConnectionType.QueuedConnection)
    worker.error.connect(receiver.handle_error, Qt.ConnectionType.QueuedConnection)
    worker.finished.connect(worker.deleteLater, Qt.ConnectionType.DirectConnection)
    worker.finished.connect(thread.quit, Qt.ConnectionType.DirectConnection)
    thread.finished.connect(receiver.handle_thread_finished, Qt.ConnectionType.QueuedConnection)
    receiver.destroyed.connect(loop.quit)

    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    timeout.start(2_000)
    thread.start()
    loop.exec()
    timeout.stop()

    if qt_wrapper_is_valid(thread) and not thread.wait(0):
        thread.requestInterruption()
        thread.quit()
        assert thread.wait(2_000)

    assert [event for event, _thread, _detail in events] == ["progress", "completed", "error", "cleanup"]
    assert all(callback_thread is app.thread() for _event, callback_thread, _detail in events)
    assert events[0][2] == 7
    assert events[-1][2] == (7, id(thread), True)
    assert getattr(owner, f"archive_{kind}_index_ui_receiver") is None


def test_scan_complete_extension_fallback_only_schedules_worker() -> None:
    class Entries:
        def __bool__(self) -> bool:
            return True

        def __iter__(self):  # type: ignore[no-untyped-def]
            raise AssertionError("UI thread must not scan archive entries")

    class Owner:
        _ensure_archive_extension_index_ready = ArchiveScanLifecycleMixin._ensure_archive_extension_index_ready

        def __init__(self) -> None:
            self.archive_entries_by_extension = {}
            self.archive_entries = Entries()
            self.ensure_calls = 0

        def _ensure_archive_basic_index_worker_started(self) -> None:
            self.ensure_calls += 1

    owner = Owner()
    owner._ensure_archive_extension_index_ready()
    assert owner.ensure_calls == 1


def test_mesh_lookup_and_companion_use_scan_worker_indexes() -> None:
    pam = ArchiveEntry("character/model/body.pam", Path("0009/0.pamt"), Path("0009/0.paz"), 1, 1, 1, 0, 0)
    pamlod = ArchiveEntry("character/model/body.pamlod", Path("0009/0.pamt"), Path("0009/0.paz"), 2, 1, 1, 0, 0)

    class Owner:
        _find_archive_entry_by_virtual_path = ArchiveVirtualPathLookupMixin._find_archive_entry_by_virtual_path
        _find_archive_preview_companion_entry = ArchiveBrowserRowPayloadMixin._find_archive_preview_companion_entry
        _normalize_archive_entry_path = staticmethod(ArchiveBrowserRowPayloadMixin._normalize_archive_entry_path)

        def __init__(self) -> None:
            self.archive_entries = [pam, pamlod]
            self.archive_entries_by_normalized_path = {}
            self.archive_mesh_entries_by_normalized_path = {
                pam.path.casefold(): [pam],
                pamlod.path.casefold(): [pamlod],
            }
            self.archive_mesh_companion_by_identity = {pam.identity: pamlod, pamlod.identity: pam}
            self.ensure_calls = 0

        def _ensure_archive_basic_index_worker_started(self) -> None:
            self.ensure_calls += 1

    owner = Owner()
    assert owner._find_archive_entry_by_virtual_path(pam.path) is pam
    assert owner._find_archive_preview_companion_entry(pam) is pamlod
    assert owner.ensure_calls == 0


def test_modify_original_supplemental_scan_is_bounded_and_cancellable(tmp_path: Path) -> None:
    referenced = tmp_path / "referenced_files"
    referenced.mkdir()
    wanted = referenced / "character" / "body.pac_xml"
    wanted.parent.mkdir()
    wanted.write_text("x", encoding="utf-8")
    (referenced / "ignore.bin").write_bytes(b"x")

    result = ArchiveMeshModifyOriginalMixin._modify_original_workspace_supplemental_files(tmp_path)
    assert result == (wanted,)

    stop_event = threading.Event()
    stop_event.set()
    with pytest.raises(RunCancelled):
        ArchiveMeshModifyOriginalMixin._modify_original_workspace_supplemental_files(
            tmp_path,
            stop_event=stop_event,
        )


def test_attachment_loose_recursive_scan_is_worker_owned() -> None:
    loose_source = Path("cdmw/ui/archive_browser/attachment_loose_files.py").read_text(encoding="utf-8")
    dialog_source = Path("cdmw/ui/archive_browser/attachment_placement_diff_dialog.py").read_text(encoding="utf-8")
    plan_source = Path("cdmw/ui/archive_browser/attachment_plan.py").read_text(encoding="utf-8")
    worker_source = Path("cdmw/workers/attachment_loose_workers.py").read_text(encoding="utf-8")
    assert 'files_root.rglob("*")' not in loose_source
    assert '.rglob("*")' not in dialog_source
    assert "prepare_attachment_loose_targets(" in plan_source
    assert "def prepare_attachment_loose_targets(" in worker_source
    assert "raise_if_cancelled(stop_event" in worker_source
