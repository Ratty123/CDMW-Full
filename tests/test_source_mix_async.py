from __future__ import annotations

import os
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication, QDialog

from cdmw.models import ArchiveEntry, RunCancelled
from cdmw.ui.archive_browser.source_mix_task_controller import (
    SourceMixTaskController,
    source_mix_task_controller_for_guard,
)
from cdmw.ui.shell.utility_controller import UtilityControllerMixin
from cdmw.workers.source_mix_workers import (
    SourceMixScanRequest,
    SourceMixScanResult,
    SourceMixIndexSnapshot,
    run_source_mix_scan,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _wait_for(app: QApplication, predicate: object, timeout: float = 5.0) -> bool:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


class _UtilityOwner(UtilityControllerMixin, QObject):
    def __init__(self) -> None:
        QObject.__init__(self)
        self.worker_thread = None
        self.utility_worker = None
        self._utility_completion_handler = None
        self._utility_error_handler = None
        self._utility_updates_archive_progress = False

    def _background_task_active(self) -> bool:
        return self.worker_thread is not None

    def set_status_message(self, *_args: object, **_kwargs: object) -> None:
        pass

    def append_log(self, *_args: object, **_kwargs: object) -> None:
        pass

    def set_busy(self, *_args: object, **_kwargs: object) -> None:
        pass

    def _handle_utility_log_message(self, _message: str) -> None:
        pass

    def _handle_utility_progress_changed(self, _current: int, _total: int, _detail: str) -> None:
        pass

    def _handle_worker_error(self, message: str) -> None:
        if self._utility_error_handler is not None:
            self._utility_error_handler(message)

    def _cleanup_worker_refs(self) -> None:
        self.worker_thread = None
        self.utility_worker = None
        self._utility_completion_handler = None
        self._utility_error_handler = None


def test_source_mix_scan_is_bounded_and_cancellable(tmp_path: Path) -> None:
    for index in range(4):
        (tmp_path / f"part_{index}.pac").write_bytes(b"mesh")

    try:
        run_source_mix_scan(
            SourceMixScanRequest(
                source_path=tmp_path,
                max_entries=2,
            )
        )
    except ValueError as exc:
        assert "entry safety limit" in str(exc)
    else:
        raise AssertionError("source-mix scan must enforce its entry ceiling")

    stop_event = threading.Event()
    stop_event.set()
    try:
        run_source_mix_scan(
            SourceMixScanRequest(source_path=tmp_path),
            stop_event=stop_event,
        )
    except RunCancelled:
        pass
    else:
        raise AssertionError("pre-cancelled source-mix scan must stop")


def test_source_mix_scan_resolves_targets_inside_worker_request(tmp_path: Path) -> None:
    source = tmp_path / "body.pac"
    source.write_bytes(b"mesh")
    target = ArchiveEntry("body.pac", tmp_path / "0.pamt", tmp_path / "0.paz", 0, 4, 4, 0, 0)
    result = run_source_mix_scan(
        SourceMixScanRequest(
            source_path=tmp_path,
            index_snapshot=SourceMixIndexSnapshot.capture(
                {"body.pac": (target,)},
                {"body.pac": (target,)},
            ),
        )
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].target_archive_entry is target
    assert result.candidates[0].match_status == "exact"


def test_source_mix_controller_dispatches_slow_io_under_50_ms(tmp_path: Path) -> None:
    app = _app()
    owner = _UtilityOwner()
    dialog = QDialog()
    controller = SourceMixTaskController(owner, dialog)
    main_thread = threading.get_ident()
    worker_threads: list[int] = []
    completed: list[SourceMixScanResult] = []

    def slow_operation(request: SourceMixScanRequest, *, stop_event: threading.Event) -> SourceMixScanResult:
        worker_threads.append(threading.get_ident())
        time.sleep(0.15)
        return SourceMixScanResult(request.request_id, request.source_path, ())

    before = time.perf_counter()
    assert controller.start(
        SourceMixScanRequest(source_path=tmp_path),
        slow_operation,
        status_message="Scanning...",
        on_complete=completed.append,
        on_error=lambda message: (_ for _ in ()).throw(AssertionError(message)),
    )
    assert (time.perf_counter() - before) * 1000.0 < 50.0
    assert _wait_for(app, lambda: len(completed) == 1)
    assert len(worker_threads) == 1
    assert worker_threads[0] != main_thread
    assert owner.worker_thread is None
    dialog.deleteLater()
    app.processEvents()


def test_source_mix_controller_close_cancels_and_rejects_stale_result(tmp_path: Path) -> None:
    app = _app()
    owner = _UtilityOwner()
    dialog = QDialog()
    controller = source_mix_task_controller_for_guard(owner, dialog)
    started = threading.Event()
    cancelled = threading.Event()
    completed: list[object] = []

    def cancellable(request: SourceMixScanRequest, *, stop_event: threading.Event) -> SourceMixScanResult:
        started.set()
        if stop_event.wait(2.0):
            cancelled.set()
            raise RunCancelled("Source-mix scan cancelled.")
        return SourceMixScanResult(request.request_id, request.source_path, ())

    assert controller.start(
        SourceMixScanRequest(source_path=tmp_path),
        cancellable,
        status_message="Scanning...",
        on_complete=completed.append,
        on_error=lambda _message: None,
    )
    assert started.wait(1.0)
    before = time.perf_counter()
    dialog.reject()
    app.processEvents()
    assert (time.perf_counter() - before) * 1000.0 < 50.0
    assert cancelled.wait(1.0)
    assert _wait_for(app, lambda: owner.worker_thread is None)
    assert completed == []
    assert controller.iter_shutdown_workers() == ()
    dialog.deleteLater()
    app.processEvents()


def test_source_mix_ui_paths_only_dispatch_worker_requests() -> None:
    paths = (
        "cdmw/ui/archive_browser/source_mix_overlay.py",
        "cdmw/ui/archive_browser/source_mix_actions.py",
        "cdmw/ui/archive_browser/static_replacement_dialog_source_mix_callbacks.py",
        "cdmw/ui/archive_browser/static_replacement_dialog_source_part_mutation_callbacks.py",
    )
    source = "\n".join(Path(path).read_text(encoding="utf-8") for path in paths)

    assert "run_source_mix_scan" in source
    assert "run_scene_import" in source
    assert "scan_loose_folder_source(" not in source
    assert "scan_mod_archive_source(" not in source
    assert "import_scene_mesh_with_report(" not in source
    assert "QApplication.processEvents()" not in source
    assert "Qt.WaitCursor" not in source
