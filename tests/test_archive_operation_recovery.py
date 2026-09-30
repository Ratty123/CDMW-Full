from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from cdmw.domain.archives.catalogue import ArchiveLookupKind, ArchiveLookupRequest, ArchiveLookupResult, ArchivePage, ArchiveQuery, ArchiveQueryHandle, ArchiveSessionHandle
from cdmw.domain.archives.catalogue_operations import ArchiveBackendError, FetchPageRequest, OpenArchiveRequest
from cdmw.domain.archives.item_catalogue import BuildNameIndexResult
from cdmw.domain.archives.catalogue_wire import to_wire
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService


_APP = QApplication.instance() or QApplication([])


class Client(QObject):
    request_started = Signal(str)
    request_progress = Signal(str, object)
    request_batch = Signal(str, object)
    request_succeeded = Signal(str, object)
    request_failed = Signal(str, object)
    request_cancelled = Signal(str)
    state_changed = Signal(str)
    worker_crashed = Signal(str)
    worker_ready = Signal()

    def __init__(self):
        super().__init__()
        self.calls = []
        self.cancelled = []
        self.forced = 0
        self.is_ready = True
        self.backend_identity = "test standalone worker 3"
        self.diagnostics_tail = "diagnostic tail"

    def submit(self, operation, payload, **context):
        self.calls.append((operation.value, payload, context))
        self.request_started.emit(context["request_id"])

    def cancel(self, request_id):
        self.cancelled.append(request_id)
        return True

    def ensure_ready(self):
        self.is_ready = True
        self.worker_ready.emit()

    def abort_unresponsive(self):
        self.forced += 1
        self.worker_crashed.emit("forced termination")

    def invalidate_before(self, generation):
        pass

    def shutdown(self):
        pass

    def error(self, error):
        self.request_failed.emit(self.calls[-1][2]["request_id"], error)

    def result(self, value):
        self.request_succeeded.emit(self.calls[-1][2]["request_id"], to_wire(value))


@pytest.fixture
def operation():
    now = [1.0]
    client = Client()
    service = ArchiveCatalogueService(client, clock=lambda: now[0])
    failures = []
    results = []
    service.request_failed.connect(lambda request, error: failures.append((request, error)))
    service.result_ready.connect(lambda *result: results.append(result))
    yield now, client, service, failures, results
    service.request_shutdown()
    service.deleteLater()
    client.deleteLater()
    _APP.processEvents()


def advance(operation, seconds):
    now, client, service, failures, results = operation
    now[0] += seconds
    service._check_operations()
    _APP.processEvents()


def opened(operation):
    _, client, service, _, _ = operation
    request_id = service.open_archive(OpenArchiveRequest("C:/Users/Test/game"), ui_generation=1)
    session = ArchiveSessionHandle("session-a", "C:/Users/Test/game", "same-fingerprint", 4, 3, False)
    client.result(session)
    return session


@pytest.mark.parametrize("refresh", [False, True])
def test_one_transient_retry_uses_a_new_attempt_id_and_ignores_late_responses(operation, refresh):
    _, client, service, failures, results = operation
    request_id = service.open_archive(OpenArchiveRequest("C:/game", force_refresh=refresh), ui_generation=1)
    first_id = client.calls[-1][2]["request_id"]
    client.error(ArchiveBackendError("file_sharing", "Locked", "Win32 32"))
    advance(operation, .99)
    assert len(client.calls) == 1 and not failures
    advance(operation, .01)
    assert len(client.calls) == 2 and client.calls[-1][0] == ("refresh_archive" if refresh else "open_archive")
    assert client.calls[-1][2]["request_id"] != first_id
    client.request_failed.emit(first_id, ArchiveBackendError("permission_denied", "late error"))
    client.result(ArchiveSessionHandle("good", "C:/game", "fp", 2, 3, False))
    assert results[-1][0] == request_id and not failures


@pytest.mark.parametrize("code", ["permission_denied", "worker_missing", "backend_incompatible", "invalid_archive", "protocol_failure", "unknown_failure"])
def test_permanent_and_unknown_errors_keep_codes_and_exact_details(operation, code):
    _, client, service, failures, _ = operation
    request_id = service.open_archive(OpenArchiveRequest("C:/game"), ui_generation=1)
    client.error(ArchiveBackendError(code, "Exact message", "Exact detail"))
    advance(operation, 2)
    assert len(client.calls) == 1 and failures[-1][0] == request_id
    failure = failures[-1][1]
    assert (failure.code, failure.message, failure.detail) == (code, "Exact message", "Exact detail")
    assert "Exact detail" in failure.report and "Attempts: 1 / 2" in failure.report


def test_retry_exhaustion_and_targeted_manual_retry_have_fresh_budgets(operation):
    _, client, service, failures, _ = operation
    session = opened(operation)
    request_id = service.build_name_index(session.session_id, ui_generation=1)
    client.error(ArchiveBackendError("operation_timeout", "Index timed out"))
    advance(operation, 1)
    assert client.calls[-1][0] == "build_name_index"
    client.error(ArchiveBackendError("operation_timeout", "Index timed out again"))
    advance(operation, 2)
    assert len(client.calls) == 3 and failures[-1][0] == request_id
    assert "Attempts: 2 / 2" in failures[-1][1].report
    new_id = service.retry_failed(request_id)
    assert new_id != request_id and client.calls[-1][0] == "build_name_index"
    client.error(ArchiveBackendError("file_sharing", "Locked"))
    advance(operation, 1)
    assert len(client.calls) == 5 and client.calls[-1][0] == "build_name_index"


@pytest.mark.parametrize("stop", ["cancel", "new_generation", "shutdown"])
def test_backoff_is_invalidated_by_cancellation_obsolete_requests_and_shutdown(operation, stop):
    _, client, service, failures, _ = operation
    request_id = service.open_archive(OpenArchiveRequest("C:/game"), ui_generation=1)
    client.error(ArchiveBackendError("file_sharing", "Locked"))
    if stop == "cancel":
        service.cancel(request_id)
    elif stop == "new_generation":
        service.invalidate_before(2)
    else:
        service.request_shutdown()
    advance(operation, 10)
    assert len(client.calls) == 1 and not failures


def test_staged_publication_and_reopening_share_the_retry_budget(operation):
    _, client, service, failures, _ = operation
    service.begin_publication(1)
    service.open_archive(OpenArchiveRequest("C:/game"), ui_generation=1)
    client.error(ArchiveBackendError("file_sharing", "Locked"))
    advance(operation, 1)
    client.result(ArchiveSessionHandle("session", "C:/game", "fp", 4, 3, False))
    query_id = service.create_query(ArchiveQuery("session", include_text="hero"), ui_generation=1)
    client.worker_crashed.emit("unexpected exit")
    client.error(ArchiveBackendError("worker_crashed", "Exited"))
    advance(operation, 1)
    assert len(client.calls) == 3 and failures[-1][0] == query_id
    assert "Attempts: 2 / 2" in failures[-1][1].report


def test_page_recovery_preserves_query_and_rejects_changed_source_before_publication(operation):
    _, client, service, failures, _ = operation
    session = opened(operation)
    query = ArchiveQuery(session.session_id, include_text="hero", sort_descending=True)
    service.create_query(query, ui_generation=1)
    client.result(ArchiveQueryHandle(session.session_id, "query", 1, 4))
    request_id = service.fetch_page(FetchPageRequest("query", 2, 2), ui_generation=1)
    client.is_ready = False
    client.worker_crashed.emit("exit")
    client.error(ArchiveBackendError("worker_crashed", "Exited"))
    advance(operation, 1)
    assert client.calls[-1][0] == "open_archive"
    client.result(replace(session, session_id="new-session", fingerprint="changed"))
    _APP.processEvents()
    assert failures[-1][0] == request_id and failures[-1][1].code == "recovery_fingerprint_changed"
    assert service.current_session == session
    assert [call[0] for call in client.calls] == ["open_archive", "create_query", "fetch_page", "open_archive"]


def test_progressing_work_can_run_long_and_duplicate_progress_does_not_reset_idle_time(operation):
    _, client, service, failures, _ = operation
    request_id = service.open_archive(OpenArchiveRequest("C:/game"), ui_generation=1)
    notices = []
    service.operation_delayed.connect(lambda *notice: notices.append(notice))
    for completed in range(10):
        client.request_progress.emit(client.calls[-1][2]["request_id"], dict(completed=completed, total=10, phase="scan"))
        advance(operation, 29)
        assert not notices
    advance(operation, 1)
    assert notices[-1][0] == request_id and notices[-1][2] >= 290
    for _ in range(5):
        client.request_progress.emit(client.calls[-1][2]["request_id"], dict(completed=9, total=10, phase="scan"))
        advance(operation, 54)
    assert client.cancelled and not failures


@pytest.mark.parametrize("acknowledge", [True, False])
def test_stall_cancellation_acknowledgement_forced_stop_and_second_stall(operation, acknowledge):
    _, client, service, failures, _ = operation
    request_id = service.open_archive(OpenArchiveRequest("C:/game"), ui_generation=1)
    for attempt in range(2):
        advance(operation, 300)
        wire_id = client.calls[-1][2]["request_id"]
        assert client.cancelled[-1] == wire_id
        if acknowledge:
            client.request_cancelled.emit(wire_id)
        else:
            advance(operation, 1.99)
            assert client.forced == attempt
            advance(operation, .01)
        advance(operation, 1)
    assert len(client.calls) == 2 and failures[-1][0] == request_id
    assert failures[-1][1].code == "request_stalled"
    assert client.forced == (0 if acknowledge else 2)


def test_report_is_utf8_bounded_redacted_and_contains_last_twelve_progress_entries(operation, monkeypatch):
    _, client, service, failures, _ = operation
    monkeypatch.setenv("USERPROFILE", "C:/Users/Test")
    request_id = service.open_archive(OpenArchiveRequest("C:/Users/Test/game"), ui_generation=1)
    for completed in range(20):
        client.request_progress.emit(client.calls[-1][2]["request_id"], dict(completed=completed, total=20, phase=f"stage-{completed}", current_item="C:\\Users\\Test\\game\\0009\\0.pamt"))
    client.diagnostics_tail = "é" * 20000 + " C:/Users/Test/cache/log newest diagnostic"
    client.error(ArchiveBackendError("worker_failure", "Unknown cause", "C:/Users/Test/game/0009/0.pamt " + "😀" * 20000))
    _APP.processEvents()
    report = failures[-1][1].report
    assert len(report.encode("utf-8")) <= 16384 and "C:/Users/Test" not in report and "C:\\Users\\Test" not in report
    assert "<game>" in report and "<profile>" in report
    assert "newest diagnostic" in report
    assert "stage-7:" not in report and "stage-8:" in report and "stage-19:" in report
    assert "build_name_index" not in report and "Operation: open_archive" in report


def test_cancelled_terminal_failure_cannot_publish_a_queued_report(operation):
    _, client, service, failures, _ = operation
    request_id = service.open_archive(OpenArchiveRequest("C:/game"), ui_generation=1)
    client.error(ArchiveBackendError("permission_denied", "Denied"))
    service.cancel(request_id)
    _APP.processEvents()
    assert not failures


def test_maximum_report_fields_still_preserve_each_progress_entry_and_newest_diagnostic():
    from cdmw.services.archive_failure_report import archive_failure_report

    report = archive_failure_report(ArchiveBackendError("code" * 200, "message" * 1000, "detail" * 4000),
        operation="operation" * 200, backend="backend" * 1000, attempts=2, phase="phase" * 1000,
        completed=12, total=12, elapsed=400, current_item="path" * 1000,
        progress=tuple(f"entry-{i}: " + "progress" * 1000 for i in range(12)),
        diagnostic_tail="old diagnostic " * 1000 + "newest diagnostic", package_root="C:/game")
    assert len(report.encode("utf-8")) <= 16384
    assert all(f"entry-{i}: " in report for i in range(12))
    assert report.endswith("newest diagnostic")


def test_recovered_session_aliases_reconstruct_only_the_failed_page_and_names(operation):
    _, client, service, failures, results = operation
    session = opened(operation)
    service.create_query(ArchiveQuery(session.session_id, include_text="helm", sort_active=True), ui_generation=1)
    handle = ArchiveQueryHandle(session.session_id, "old-query", 1, 4)
    client.result(handle)
    names_id = service.build_name_index(session.session_id, ui_generation=1)
    client.worker_crashed.emit("Unexpected exit")
    client.error(ArchiveBackendError("worker_crashed", "Exited"))
    advance(operation, 1)
    assert client.calls[-1][0] == "open_archive"
    recovered = replace(session, session_id="recovered")
    client.result(recovered)
    assert client.calls[-1][0] == "build_name_index" and client.calls[-1][1].session_id == "recovered"
    client.result(BuildNameIndexResult("recovered", True, False, 1, 1))
    assert results[-1][0] == names_id
    page_id = service.fetch_page(FetchPageRequest("old-query", 2, 2), ui_generation=1)
    assert client.calls[-1][0] == "create_query"
    query = client.calls[-1][1].query
    assert query.session_id == "recovered" and query.include_text == "helm" and query.sort_active
    client.result(ArchiveQueryHandle("recovered", "reconstructed-query", 1, 4))
    assert client.calls[-1][0] == "fetch_page"
    assert client.calls[-1][1] == FetchPageRequest("reconstructed-query", 2, 2)
    assert client.calls[-1][2]["expected_fingerprint"] == session.fingerprint
    assert service._requests[page_id].budget.retries == 0
    assert not failures


@pytest.mark.parametrize("reuse_session_id", [False, True])
def test_a_second_worker_exit_reopens_even_after_session_alias_recovery(operation, reuse_session_id):
    _, client, service, failures, results = operation
    session = opened(operation)
    for attempt in range(2):
        request_id = service.build_name_index(session.session_id, ui_generation=1)
        client.worker_crashed.emit("Exited")
        client.error(ArchiveBackendError("worker_crashed", "Exited"))
        advance(operation, 1)
        assert client.calls[-1][0] == "open_archive"
        recovered = replace(session, session_id=session.session_id if reuse_session_id else f"recovered-{attempt}")
        client.result(recovered)
        assert client.calls[-1][0] == "build_name_index"
        assert client.calls[-1][1].session_id == recovered.session_id
        client.result(BuildNameIndexResult(recovered.session_id, True, False, 1, 1))
        assert results[-1][0] == request_id and not failures
    assert [call[0] for call in client.calls].count("open_archive") == 3


def test_cancelling_during_session_reopen_drops_late_responses(operation):
    _, client, service, failures, results = operation
    session = opened(operation)
    request_id = service.build_name_index(session.session_id, ui_generation=1)
    client.worker_crashed.emit("Exited")
    client.error(ArchiveBackendError("worker_crashed", "Exited"))
    advance(operation, 1)
    recovery_wire = client.calls[-1][2]["request_id"]
    assert service.cancel(request_id)
    before = len(client.calls)
    client.request_succeeded.emit(recovery_wire, to_wire(replace(session, session_id="obsolete")))
    advance(operation, 10)
    assert len(client.calls) == before and not failures
    assert all(result[0] != request_id for result in results)


def test_manual_retry_refreshes_the_whole_publication_budget(operation):
    _, client, service, failures, _ = operation
    service.begin_publication(1)
    request_id = service.open_archive(OpenArchiveRequest("C:/game"), ui_generation=1)
    for _ in range(2):
        client.error(ArchiveBackendError("file_sharing", "Locked"))
        advance(operation, 1)
    assert failures[-1][0] == request_id
    manual = service.retry_failed(request_id)
    client.error(ArchiveBackendError("file_sharing", "Still locked"))
    advance(operation, 1)
    session = ArchiveSessionHandle("new", "C:/game", "fp", 4, 3, False)
    client.result(session)
    query_id = service.create_query(ArchiveQuery(session.session_id), ui_generation=1)
    client.error(ArchiveBackendError("file_sharing", "Query locked"))
    advance(operation, 1)
    assert failures[-1][0] == query_id and "Attempts: 2 / 2" in failures[-1][1].report
    assert manual != request_id


def test_unavailable_item_names_keep_exact_warning_and_support_targeted_retry(operation):
    _, client, service, failures, results = operation
    session = opened(operation)
    request_id = service.build_name_index(session.session_id, ui_generation=1)
    client.result(BuildNameIndexResult(session.session_id, False, False, 0, 0, warning="ItemInfo table pair is missing."))
    advance(operation, 0)
    failure = failures[-1][1]
    assert failure.code == "item_names_unavailable" and "ItemInfo table pair is missing." in failure.report
    assert all(row[0] != request_id for row in results)
    service.retry_failed(request_id)
    assert client.calls[-1][0] == "build_name_index"


def test_large_stage_and_path_cannot_displace_the_exact_error(operation):
    _, client, service, failures, _ = operation
    service.open_archive(OpenArchiveRequest("C:/game"), ui_generation=1)
    client.request_progress.emit(client.calls[-1][2]["request_id"], dict(completed=0, total=1,
        phase="X" * 40000, current_item="C:/game/" + "Y" * 40000))
    client.error(ArchiveBackendError("worker_failure", "Exact failure message", "Exact failure detail"))
    advance(operation, 0)
    report = failures[-1][1].report
    assert len(report.encode("utf-8")) <= 16384
    assert "Exact failure message" in report and "Exact failure detail" in report


def test_recovery_startup_timeout_reaches_the_original_operation_without_an_extra_retry(operation):
    _, client, service, failures, _ = operation
    session = opened(operation)
    request_id = service.build_name_index(session.session_id, ui_generation=1)
    client.is_ready = False
    client.worker_crashed.emit("Exited")
    client.error(ArchiveBackendError("worker_crashed", "Exited"))
    advance(operation, 1)
    assert client.calls[-1][0] == "open_archive"
    client.error(ArchiveBackendError("startup_timeout", "No startup acknowledgement within ten seconds"))
    advance(operation, 1)
    assert failures[-1][0] == request_id and failures[-1][1].code == "startup_timeout"
    assert "Attempts: 2 / 2" in failures[-1][1].report
    assert len(client.calls) == 3


def test_missing_started_response_and_repeated_acknowledgements_cannot_hide_a_stall(operation):
    _, client, service, failures, _ = operation
    client.submit = lambda operation, payload, **context: client.calls.append((operation.value, payload, context))
    notices = []
    service.operation_delayed.connect(lambda *notice: notices.append(notice))
    service.open_archive(OpenArchiveRequest("C:/game"), ui_generation=1)
    advance(operation, 30)
    assert len(notices) == 1
    wire = client.calls[-1][2]["request_id"]
    client.request_started.emit(wire)
    advance(operation, 29)
    client.request_started.emit(wire)
    advance(operation, 1)
    assert len(notices) == 2
    advance(operation, 270)
    assert client.cancelled == [wire] and not failures


def test_manual_failed_name_retry_uses_a_session_recovered_by_another_operation(operation):
    _, client, service, failures, _ = operation
    session = opened(operation)
    names_id = service.build_name_index(session.session_id, ui_generation=1)
    client.error(ArchiveBackendError("permission_denied", "Denied"))
    advance(operation, 0)
    service.create_query(ArchiveQuery(session.session_id), ui_generation=1)
    client.worker_crashed.emit("Exited")
    client.error(ArchiveBackendError("worker_crashed", "Exited"))
    advance(operation, 1)
    recovered = replace(session, session_id="recovered-by-query")
    client.result(recovered)
    client.result(ArchiveQueryHandle(recovered.session_id, "fresh-query", 1, 4))
    assert service.session(session.session_id) == recovered
    service.retry_failed(names_id)
    assert client.calls[-1][0] == "build_name_index"
    assert client.calls[-1][1].session_id == recovered.session_id
    client.error(ArchiveBackendError("permission_denied", "Still denied"))
    advance(operation, 0)
    assert "<game>" in failures[-1][1].report or "Operation: build_name_index" in failures[-1][1].report
    assert "Attempts: 1 / 2" in failures[-1][1].report


def test_duplicate_batches_do_not_hide_stalled_work(operation):
    _, client, service, failures, _ = operation
    session = opened(operation)
    service.resolve_entries(ArchiveLookupRequest(session.session_id, ArchiveLookupKind.EXTENSIONS, values=(".pac",)), ui_generation=1)
    wire = client.calls[-1][2]["request_id"]
    batch = to_wire(ArchiveLookupResult(session.session_id, (), 0, False))
    for _ in range(10):
        client.request_batch.emit(wire, batch)
        advance(operation, 30)
    assert client.cancelled == [wire] and not failures


@pytest.mark.parametrize("on_retry", [False, True])
def test_dispatch_exception_becomes_a_typed_report_instead_of_a_stuck_request(operation, on_retry):
    _, client, service, failures, _ = operation
    def broken_submit(*args, **kwargs):
        raise OSError("Exact transport dispatch error")
    if on_retry:
        request_id = service.open_archive(OpenArchiveRequest("C:/game"), ui_generation=1)
        client.error(ArchiveBackendError("file_sharing", "Locked"))
        client.submit = broken_submit
        advance(operation, 1)
    else:
        client.submit = broken_submit
        request_id = service.open_archive(OpenArchiveRequest("C:/game"), ui_generation=1)
        advance(operation, 0)
    failure = failures[-1][1]
    assert failures[-1][0] == request_id and failure.code == "dispatch_failed"
    assert "Exact transport dispatch error" in failure.detail and "Traceback" in failure.report
    assert not service._requests


def test_page_from_a_retained_compiled_query_uses_the_current_ui_generation(operation):
    _, client, service, failures, results = operation
    session = opened(operation)
    service.create_query(ArchiveQuery(session.session_id), ui_generation=1)
    client.result(ArchiveQueryHandle(session.session_id, "query", 1, 4))
    request_id = service.fetch_page(FetchPageRequest("query", 2, 2), ui_generation=2)
    client.result(ArchivePage(session.session_id, "query", 1, 4, 2, ()))
    assert results[-1][0] == request_id and results[-1][2].generation == 2 and not failures


def test_invalid_page_range_reports_immediately_and_manual_retry_keeps_the_exact_page(operation):
    _, client, service, failures, results = operation
    session = opened(operation)
    service.create_query(ArchiveQuery(session.session_id), ui_generation=1)
    client.result(ArchiveQueryHandle(session.session_id, "query", 1, 4))
    request_id = service.fetch_page(FetchPageRequest("query", 0, 2), ui_generation=1)
    client.result(ArchivePage(session.session_id, "query", 1, 4, 2, ()))
    advance(operation, 1)
    assert failures[-1][0] == request_id and failures[-1][1].code == "invalid_result"
    assert "range or session" in failures[-1][1].detail
    manual = service.retry_failed(request_id)
    assert client.calls[-1][0] == "fetch_page" and client.calls[-1][1] == FetchPageRequest("query", 0, 2)
    assert service._requests[manual].budget.retries == 0
    client.result(ArchivePage(session.session_id, "query", 1, 4, 0, ()))
    assert results[-1][0] == manual
