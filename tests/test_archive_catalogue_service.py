from __future__ import annotations

import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shiboken6
import pytest
from PySide6.QtCore import QEventLoop, QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from cdmw.domain.archives.catalogue import (
    ArchiveChildrenRequest,
    ArchiveChildrenResult,
    ArchiveEntryDto,
    ArchiveLookupKind,
    ArchiveLookupRequest,
    ArchiveLookupResult,
    ArchivePage,
    ArchiveQuery,
    ArchiveQueryHandle,
    ArchiveSessionHandle,
    ArchiveSortField,
)
from cdmw.domain.archives.catalogue_operations import (
    ArchiveExportRequest,
    ArchiveExportResult,
    ArchiveExportSelectionKind,
    FetchPageRequest,
    OpenArchiveRequest,
)
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
from cdmw.ui.shell.archive_backend_client import ArchiveBackendClient, ArchiveBackendClientState


_APPLICATION: QApplication | None = None
_STUB = Path(__file__).parent / "helpers" / "archive_backend_worker_stub.py"

#: Clients built without a parent, so only this module owns them.
_UNPARENTED_CLIENTS: list[ArchiveBackendClient] = []


def _own_client(client: ArchiveBackendClient) -> ArchiveBackendClient:
    """Destroy the client inside the test that made it.

    These clients own a real `QProcess` and are built with no parent, so the C++
    object outlives the test and is destroyed at whatever later moment the Python
    reference count happens to drop. Landing that inside another test's Qt work
    aborts the interpreter: exit 3, no traceback, no pytest summary. It is the
    same defect that killed the suite from `test_dotnet_preview_shared_host`, and
    it took out the 3.14 leg at
    `test_catalogue_service_retries_session_scoped_structure_children_after_crash`
    while 3.11 passed the whole suite.

    Calling `shutdown()` is not enough on its own; the QObject has to go.
    """

    _UNPARENTED_CLIENTS.append(client)
    return client


@pytest.fixture(autouse=True)
def _destroy_unparented_clients():
    yield
    while _UNPARENTED_CLIENTS:
        client = _UNPARENTED_CLIENTS.pop()
        if not shiboken6.isValid(client):
            continue
        try:
            client.shutdown()
        except RuntimeError:
            pass
        shiboken6.delete(client)



class _SignalClient(QObject):
    request_progress = Signal(str, object)
    request_batch = Signal(str, object)
    request_succeeded = Signal(str, object)
    request_failed = Signal(str, object)
    request_cancelled = Signal(str)
    state_changed = Signal(str)
    worker_crashed = Signal(str)
    worker_ready = Signal()

    def submit(self, *_args: object, **_kwargs: object) -> None:
        return None

    def cancel(self, _request_id: str) -> bool:
        return True

    def shutdown(self) -> None:
        return None


def _app() -> QApplication:
    global _APPLICATION
    _APPLICATION = QApplication.instance() or QApplication([])
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


def test_catalogue_service_publishes_typed_session_query_page_and_legacy_entry(tmp_path: Path) -> None:
    _app()
    client = _own_client(ArchiveBackendClient(
        cache_root=tmp_path,
        worker_program=sys.executable,
        worker_arguments=("-u", str(_STUB)),
    ))
    service = ArchiveCatalogueService(client)
    results: list[tuple[str, str, object]] = []
    failures: list[tuple[str, object]] = []
    sessions: list[ArchiveSessionHandle] = []
    service.result_ready.connect(
        lambda request_id, operation, result: results.append((request_id, operation, result))
    )
    service.request_failed.connect(lambda request_id, error: failures.append((request_id, error)))
    service.session_published.connect(sessions.append)

    open_id = service.open_archive(OpenArchiveRequest("synthetic-root"), ui_generation=1)
    assert _wait_until(lambda: any(row[0] == open_id for row in results or failures))
    assert not failures
    opened = next(row[2] for row in results if row[0] == open_id)
    assert isinstance(opened, ArchiveSessionHandle)
    assert opened.session_id == "session-stub"
    assert opened.fingerprint == "fingerprint-stub"
    assert service.current_session is opened
    assert sessions == [opened]

    query_id = service.create_query(
        ArchiveQuery(
            session_id=opened.session_id,
            include_text="stub",
            sort_field=ArchiveSortField.KNOWN_NAME,
        ),
        ui_generation=2,
    )
    assert _wait_until(lambda: any(row[0] == query_id for row in results or failures))
    query = next(row[2] for row in results if row[0] == query_id)
    assert isinstance(query, ArchiveQueryHandle)
    assert query.query_id == "query-stub"
    assert query.total_matches == 1

    page_id = service.fetch_page(
        FetchPageRequest(query.query_id, page_start=0, page_size=256),
        ui_generation=3,
    )
    assert _wait_until(lambda: any(row[0] == page_id for row in results or failures))
    page = next(row[2] for row in results if row[0] == page_id)
    assert isinstance(page, ArchivePage)
    assert len(page.rows) == 1
    dto = page.rows[0]
    assert isinstance(dto, ArchiveEntryDto)
    assert dto.known_name == "Stub Model"

    compatibility = service.compatibility_entry(dto)
    assert compatibility.path == dto.path
    assert compatibility.pamt_path == Path(dto.source_pamt)
    assert compatibility.paz_file == Path(dto.paz_file)
    assert compatibility.identity.normalized_path == dto.identity.normalized_path
    assert not hasattr(service, "archive_entries")

    service.request_shutdown()
    assert _wait_until(lambda: client.state is ArchiveBackendClientState.STOPPED)


def test_catalogue_service_reopens_session_and_reconstructs_query_after_crash(tmp_path: Path) -> None:
    _app()
    client = _own_client(ArchiveBackendClient(
        cache_root=tmp_path,
        worker_program=sys.executable,
        worker_arguments=("-u", str(_STUB)),
    ))
    service = ArchiveCatalogueService(client)
    results: list[tuple[str, str, object]] = []
    failures: list[tuple[str, object]] = []
    crashes: list[str] = []
    service.result_ready.connect(
        lambda request_id, operation, result: results.append((request_id, operation, result))
    )
    service.request_failed.connect(lambda request_id, error: failures.append((request_id, error)))
    service.worker_crashed.connect(crashes.append)

    open_id = service.open_archive(OpenArchiveRequest("synthetic-root"), ui_generation=1)
    assert _wait_until(lambda: any(row[0] == open_id for row in results))
    session = next(row[2] for row in results if row[0] == open_id)
    assert isinstance(session, ArchiveSessionHandle)

    query_request_id = service.create_query(
        ArchiveQuery(session_id=session.session_id, include_text="crash_query_once"),
        ui_generation=2,
    )
    assert _wait_until(
        lambda: any(row[0] == query_request_id for row in results or failures),
        timeout_ms=8_000,
    )
    assert not [row for row in failures if row[0] == query_request_id]
    query = next(row[2] for row in results if row[0] == query_request_id)
    assert isinstance(query, ArchiveQueryHandle)

    page_request_id = service.fetch_page(
        FetchPageRequest(query.query_id, page_start=512, page_size=128),
        ui_generation=3,
    )
    assert _wait_until(
        lambda: any(row[0] == page_request_id for row in results or failures),
        timeout_ms=8_000,
    )
    assert not [row for row in failures if row[0] == page_request_id]
    page = next(row[2] for row in results if row[0] == page_request_id)
    assert isinstance(page, ArchivePage)
    assert page.page_start == 512
    assert len(crashes) == 2

    operations = (tmp_path / "stub-operations.log").read_text(encoding="utf-8").splitlines()
    assert operations.count("open_archive") == 3
    assert operations.count("create_query") == 3
    assert operations.count("fetch_page") == 2

    service.request_shutdown()
    assert _wait_until(lambda: client.state is ArchiveBackendClientState.STOPPED)


def test_catalogue_service_reconstructs_query_scoped_lookup_after_crash(tmp_path: Path) -> None:
    _app()
    client = _own_client(ArchiveBackendClient(
        cache_root=tmp_path,
        worker_program=sys.executable,
        worker_arguments=("-u", str(_STUB)),
    ))
    service = ArchiveCatalogueService(client)
    results: list[tuple[str, str, object]] = []
    failures: list[tuple[str, object]] = []
    crashes: list[str] = []
    service.result_ready.connect(
        lambda request_id, operation, result: results.append((request_id, operation, result))
    )
    service.request_failed.connect(lambda request_id, error: failures.append((request_id, error)))
    service.worker_crashed.connect(crashes.append)

    open_id = service.open_archive(OpenArchiveRequest("synthetic-root"), ui_generation=1)
    assert _wait_until(lambda: any(row[0] == open_id for row in results))
    session = next(row[2] for row in results if row[0] == open_id)
    assert isinstance(session, ArchiveSessionHandle)
    query_id = service.create_query(
        ArchiveQuery(session_id=session.session_id, include_text="lookup-recovery"),
        ui_generation=2,
    )
    assert _wait_until(lambda: any(row[0] == query_id for row in results))
    query = next(row[2] for row in results if row[0] == query_id)
    assert isinstance(query, ArchiveQueryHandle)

    lookup_id = service.resolve_entries(
        ArchiveLookupRequest(
            session_id=session.session_id,
            kind=ArchiveLookupKind.EXTENSIONS,
            values=("crash_once",),
            limit=8,
            query_id=query.query_id,
        ),
        ui_generation=3,
    )
    assert _wait_until(
        lambda: any(row[0] == lookup_id for row in results or failures),
        timeout_ms=8_000,
    )
    assert not [row for row in failures if row[0] == lookup_id]
    lookup = next(row[2] for row in results if row[0] == lookup_id)
    assert isinstance(lookup, ArchiveLookupResult)
    assert lookup.entries == ()
    assert len(crashes) == 1

    operations = (tmp_path / "stub-operations.log").read_text(encoding="utf-8").splitlines()
    assert operations.count("open_archive") == 2
    assert operations.count("create_query") == 2
    assert operations.count("resolve_entries") == 2

    service.request_shutdown()
    assert _wait_until(lambda: client.state is ArchiveBackendClientState.STOPPED)


def test_catalogue_service_retries_session_scoped_structure_children_after_crash(tmp_path: Path) -> None:
    _app()
    client = _own_client(ArchiveBackendClient(
        cache_root=tmp_path,
        worker_program=sys.executable,
        worker_arguments=("-u", str(_STUB)),
    ))
    service = ArchiveCatalogueService(client)
    results: list[tuple[str, str, object]] = []
    failures: list[tuple[str, object]] = []
    service.result_ready.connect(
        lambda request_id, operation, result: results.append((request_id, operation, result))
    )
    service.request_failed.connect(lambda request_id, error: failures.append((request_id, error)))

    open_id = service.open_archive(OpenArchiveRequest("synthetic-root"), ui_generation=1)
    assert _wait_until(lambda: any(row[0] == open_id for row in results))
    session = next(row[2] for row in results if row[0] == open_id)
    assert isinstance(session, ArchiveSessionHandle)

    children_id = service.fetch_structure_children(
        session.session_id,
        ArchiveChildrenRequest(
            "",
            parent_path="crash_once",
            include_package_root=True,
        ),
        ui_generation=2,
    )
    assert _wait_until(
        lambda: any(row[0] == children_id for row in results or failures),
        timeout_ms=8_000,
    )
    assert not [row for row in failures if row[0] == children_id]
    children = next(row[2] for row in results if row[0] == children_id)
    assert isinstance(children, ArchiveChildrenResult)
    assert children.query_id == ""
    assert children.children[0].key == "0009"

    operations = (tmp_path / "stub-operations.log").read_text(encoding="utf-8").splitlines()
    assert operations.count("open_archive") == 2
    assert operations.count("fetch_children") == 2
    assert operations.count("create_query") == 0

    service.request_shutdown()
    assert _wait_until(lambda: client.state is ArchiveBackendClientState.STOPPED)


def test_catalogue_service_parses_streamed_export_items() -> None:
    _app()
    client = _SignalClient()
    service = ArchiveCatalogueService(client)
    session = ArchiveSessionHandle("session-a", "C:/Game", "fingerprint", 2, 2, True)
    service._sessions[session.session_id] = session
    service._current_session_id = session.session_id
    batches: list[tuple[str, str, object]] = []
    results: list[tuple[str, str, object]] = []
    service.batch_ready.connect(lambda request_id, operation, payload: batches.append((request_id, operation, payload)))
    service.result_ready.connect(lambda request_id, operation, payload: results.append((request_id, operation, payload)))
    request_id = service.export(
        ArchiveExportRequest(
            session.session_id,
            ArchiveExportSelectionKind.ENTRY_IDS,
            "C:/export",
            entry_ids=(7,),
        ),
        ui_generation=1,
    )
    batch_payload = {
        "session_id": session.session_id,
        "requested": 1,
        "exported": 1,
        "skipped": 0,
        "failed": 0,
        "cancelled": False,
        "manifest_path": "C:/export/cdmw-export-manifest.json",
        "items": [
            {
                "source_path": "texture/albedo.dds",
                "output_path": "C:/export/texture/albedo_2.dds",
                "status": "renamed",
                "message": None,
            }
        ],
        "items_truncated": False,
    }
    client.request_batch.emit(request_id, batch_payload)
    client.request_succeeded.emit(request_id, {**batch_payload, "items": []})

    assert len(batches) == 1
    assert batches[0][0:2] == (request_id, "export")
    assert isinstance(batches[0][2], ArchiveExportResult)
    assert batches[0][2].items[0].status == "renamed"
    assert len(results) == 1
    assert isinstance(results[0][2], ArchiveExportResult)
    assert results[0][2].items == ()
