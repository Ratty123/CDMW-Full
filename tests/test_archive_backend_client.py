from __future__ import annotations

from pathlib import Path
import sys
import time

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from cdmw.domain.archives.catalogue_operations import (
    ArchiveBackendOperation,
    ArchiveExportRequest,
    ArchiveExportSelectionKind,
    CacheHealthRequest,
)
from cdmw.ui.shell.archive_backend_client import (
    ARCHIVE_BACKEND_STDERR_LIMIT,
    ArchiveBackendClient,
    ArchiveBackendClientState,
)


_STUB = Path(__file__).parent / "helpers" / "archive_backend_worker_stub.py"
_APPLICATION: QCoreApplication | None = None


def _app() -> QCoreApplication:
    global _APPLICATION
    _APPLICATION = QCoreApplication.instance() or QCoreApplication([])
    return _APPLICATION


def _wait_until(predicate, *, timeout_ms: int = 5_000) -> bool:
    _app()
    if predicate():
        return True
    loop = QEventLoop()
    poll = QTimer()
    poll.setInterval(10)
    poll.timeout.connect(lambda: loop.quit() if predicate() else None)
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    poll.start()
    timeout.start(timeout_ms)
    loop.exec()
    poll.stop()
    timeout.stop()
    return bool(predicate())


def _client(tmp_path: Path) -> ArchiveBackendClient:
    _app()
    return ArchiveBackendClient(
        cache_root=tmp_path,
        worker_program=sys.executable,
        worker_arguments=("-u", str(_STUB)),
    )


def _shutdown(client: ArchiveBackendClient) -> None:
    client.shutdown()
    assert _wait_until(lambda: client.state is ArchiveBackendClientState.STOPPED)


def test_qprocess_client_handshakes_streams_and_bounds_diagnostics(tmp_path: Path) -> None:
    client = _client(tmp_path)
    ready: list[bool] = []
    started: list[str] = []
    progress: list[object] = []
    batches: list[object] = []
    results: list[tuple[str, object]] = []
    failures: list[tuple[str, object]] = []
    client.worker_ready.connect(lambda: ready.append(True))
    client.request_started.connect(started.append)
    client.request_progress.connect(lambda request_id, payload: progress.append(payload))
    client.request_batch.connect(lambda request_id, payload: batches.append(payload))
    client.request_succeeded.connect(lambda request_id, payload: results.append((request_id, payload)))
    client.request_failed.connect(lambda request_id, error: failures.append((request_id, error)))

    request_id = client.submit(
        ArchiveBackendOperation.CACHE_HEALTH,
        CacheHealthRequest("synthetic-root"),
        ui_generation=4,
    )
    assert _wait_until(lambda: bool(results or failures))
    assert not failures
    assert ready == [True]
    assert started == [request_id]
    assert progress == [{"completed": 1, "total": 1, "phase": "health"}]
    assert batches == [{"rows": [1]}]
    assert results[0][0] == request_id
    assert results[0][1]["root_id"] == "stub-root"
    assert _wait_until(lambda: len(client.diagnostics_tail) >= ARCHIVE_BACKEND_STDERR_LIMIT)
    assert len(client.diagnostics_tail.encode("utf-8")) <= ARCHIVE_BACKEND_STDERR_LIMIT
    assert client.process_id > 0
    _shutdown(client)


def test_qprocess_client_rejects_inflight_stale_generation(tmp_path: Path) -> None:
    client = _client(tmp_path)
    warm_results: list[str] = []
    failures: list[tuple[str, object]] = []
    rejected: list[tuple[str, str]] = []
    client.request_succeeded.connect(lambda request_id, payload: warm_results.append(request_id))
    client.request_failed.connect(lambda request_id, error: failures.append((request_id, error)))
    client.response_rejected.connect(lambda request_id, reason: rejected.append((request_id, reason)))
    client.submit(
        ArchiveBackendOperation.CACHE_HEALTH,
        CacheHealthRequest("warm"),
        ui_generation=0,
    )
    assert _wait_until(lambda: bool(warm_results))

    request_id = client.submit(
        ArchiveBackendOperation.CACHE_HEALTH,
        CacheHealthRequest("delay"),
        ui_generation=1,
    )
    QTimer.singleShot(20, lambda: client.invalidate_before(2))
    assert _wait_until(lambda: any(row[0] == request_id for row in failures))
    error = next(row[1] for row in failures if row[0] == request_id)
    assert error.code == "stale_generation"
    assert _wait_until(lambda: any(row[0] == request_id for row in rejected), timeout_ms=2_000)
    assert next(reason for target, reason in rejected if target == request_id) == "unknown_or_stale_request"
    _shutdown(client)


def test_qprocess_client_restarts_once_and_retries_only_safe_request(tmp_path: Path) -> None:
    client = _client(tmp_path)
    crashes: list[str] = []
    results: list[tuple[str, object]] = []
    failures: list[tuple[str, object]] = []
    client.worker_crashed.connect(crashes.append)
    client.request_succeeded.connect(lambda request_id, payload: results.append((request_id, payload)))
    client.request_failed.connect(lambda request_id, error: failures.append((request_id, error)))

    request_id = client.submit(
        ArchiveBackendOperation.CACHE_HEALTH,
        CacheHealthRequest("crash_once"),
        ui_generation=3,
    )
    assert _wait_until(lambda: any(row[0] == request_id for row in results or failures))
    assert not failures
    assert len(crashes) == 1
    operations = (tmp_path / "stub-operations.log").read_text(encoding="utf-8").splitlines()
    assert operations.count("cache_health") == 2

    export_id = client.submit(
        ArchiveBackendOperation.EXPORT,
        ArchiveExportRequest(
            session_id="session-a",
            selection_kind=ArchiveExportSelectionKind.ENTRY_IDS,
            destination=str(tmp_path / "export"),
            entry_ids=(1,),
        ),
        ui_generation=4,
        session_id="session-a",
    )
    assert _wait_until(lambda: any(row[0] == export_id for row in failures))
    export_error = next(row[1] for row in failures if row[0] == export_id)
    assert export_error.code == "worker_crashed"
    assert _wait_until(lambda: client.state is ArchiveBackendClientState.READY)
    time.sleep(0.05)
    _app().processEvents()
    operations = (tmp_path / "stub-operations.log").read_text(encoding="utf-8").splitlines()
    assert operations.count("export") == 1
    _shutdown(client)
