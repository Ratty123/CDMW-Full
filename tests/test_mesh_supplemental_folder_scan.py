from __future__ import annotations

import os
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QThread
from PySide6.QtWidgets import QApplication

from cdmw.models import RunCancelled
from cdmw.ui.archive_browser.directory_scan_controller import DirectoryScanController
from cdmw.workers import directory_scan_workers
from cdmw.workers.directory_scan_workers import DirectoryScanResult


def _pump_until(app: QApplication, predicate, *, timeout: float = 3.0) -> None:  # type: ignore[no-untyped-def]
    deadline = time.perf_counter() + timeout
    while not predicate() and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.002)
    assert predicate()


def test_directory_scan_controller_returns_immediately_and_rejects_stale_results(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    app = QApplication.instance() or QApplication([])
    slow_root = tmp_path / "slow"
    fast_root = tmp_path / "fast"
    slow_root.mkdir()
    fast_root.mkdir()

    def injected_scan(request, *, stop_event=None):  # type: ignore[no-untyped-def]
        time.sleep(0.15 if request.root.name == "slow" else 0.01)
        return DirectoryScanResult((request.root / f"{request.root.name}.dds",), 1, 0, False)

    monkeypatch.setattr(directory_scan_workers, "scan_directory_files", injected_scan)
    owner = QObject()
    controller = DirectoryScanController(thread_parent=owner, parent=owner, batch_size=1)
    batches: list[tuple[int, tuple[Path, ...], bool]] = []
    completions: list[int] = []
    controller.batch_ready.connect(
        lambda request_id, paths: batches.append(
            (request_id, tuple(paths), QThread.currentThread() is app.thread())
        )
    )
    controller.completed.connect(lambda request_id, _truncated: completions.append(request_id))

    controller.start(slow_root, suffixes=(".dds",))
    started_at = time.perf_counter()
    fast_request_id = controller.start(fast_root, suffixes=(".dds",))
    assert time.perf_counter() - started_at < 0.05

    _pump_until(app, lambda: bool(completions))
    _pump_until(app, lambda: not controller.has_jobs())
    controller.close()

    assert completions == [fast_request_id]
    assert batches == [(fast_request_id, (fast_root / "fast.dds",), True)]


def test_directory_scan_controller_close_cancels_without_waiting(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    app = QApplication.instance() or QApplication([])
    entered = threading.Event()
    cancelled = threading.Event()

    def injected_scan(_request, *, stop_event=None):  # type: ignore[no-untyped-def]
        entered.set()
        while stop_event is not None and not stop_event.wait(0.002):
            pass
        cancelled.set()
        raise RunCancelled("cancelled")

    monkeypatch.setattr(directory_scan_workers, "scan_directory_files", injected_scan)
    owner = QObject()
    controller = DirectoryScanController(thread_parent=owner, parent=owner)
    controller.start(tmp_path, suffixes=(".dds",))
    _pump_until(app, entered.is_set)

    started_at = time.perf_counter()
    controller.close()
    assert time.perf_counter() - started_at < 0.05
    _pump_until(app, lambda: not controller.has_jobs())
    assert cancelled.is_set()


def test_mesh_folder_handlers_have_no_recursive_ui_thread_scan() -> None:
    direct_source = Path("cdmw/ui/archive_browser/mesh_direct_patch.py").read_text(encoding="utf-8")
    import_source = Path("cdmw/ui/archive_browser/mesh_import_export.py").read_text(encoding="utf-8")

    assert "_prompt_archive_mesh_import_supplemental_files" not in direct_source
    assert ".rglob(" not in direct_source
    assert ".rglob(" not in import_source
    assert "folder_scan.start(" in import_source
    assert "not folder_scan.is_running()" in import_source
    assert "dialog.finished.connect(lambda _result=0: folder_scan.close())" in import_source
    controller_source = Path("cdmw/ui/archive_browser/directory_scan_controller.py").read_text(encoding="utf-8")
    assert "thread = QThread(self._thread_parent)" in controller_source
