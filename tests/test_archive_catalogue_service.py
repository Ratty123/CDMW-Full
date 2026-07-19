from __future__ import annotations

from pathlib import Path
import sys

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from cdmw.domain.archives.catalogue import (
    ArchiveEntryDto,
    ArchivePage,
    ArchiveQuery,
    ArchiveQueryHandle,
    ArchiveSessionHandle,
    ArchiveSortField,
)
from cdmw.domain.archives.catalogue_operations import (
    FetchPageRequest,
    OpenArchiveRequest,
)
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
from cdmw.ui.shell.archive_backend_client import ArchiveBackendClient, ArchiveBackendClientState


_APPLICATION: QCoreApplication | None = None
_STUB = Path(__file__).parent / "helpers" / "archive_backend_worker_stub.py"


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


def test_catalogue_service_publishes_typed_session_query_page_and_legacy_entry(tmp_path: Path) -> None:
    _app()
    client = ArchiveBackendClient(
        cache_root=tmp_path,
        worker_program=sys.executable,
        worker_arguments=("-u", str(_STUB)),
    )
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
