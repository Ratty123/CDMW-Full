"""Path-list output and the real Archive Browser action, with metadata-only pages."""

from __future__ import annotations

import csv
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from queue import Queue

import pytest
from PySide6.QtCore import QItemSelectionModel, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QToolButton

from cdmw.domain.archives.catalogue import ArchivePage, ArchiveQuery, ArchiveQueryHandle, ArchiveViewMode
from cdmw.domain.archives.catalogue_operations import OpenArchiveRequest
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
from cdmw.services.archive_path_export import ArchivePathExportRequest, export_archive_paths
from cdmw.ui.archive_browser import path_export_dialog
from cdmw.ui.archive_browser.path_export_dialog import ArchivePathExportDialog, path_export_scopes
from cdmw.ui.shell.archive_backend_client import ArchiveBackendClient, ArchiveBackendClientState
from tests.test_archive_bulk_extract_ui import app, window, _publish
from tests.test_archive_remote_window_bridge import _remote


def _write(target, rows, *, folder="", stop=None, progress=lambda *_args: None, failure=None):
    batches = Queue()
    batches.put((tuple(rows), len(rows)))
    batches.put(failure)
    return export_archive_paths(ArchivePathExportRequest(7, target, folder), batches,
                                stop_event=stop or threading.Event(), page_consumed=lambda: None,
                                progress=progress)


@pytest.mark.parametrize("suffix", ["txt", "csv"])
def test_unicode_paths_duplicates_and_csv_source_identity(tmp_path, suffix):
    target = tmp_path / ("paths." + suffix)
    rows = [_remote(1, "object/日本語,coat.pac"), _remote(2, "object/日本語,coat.pac")]
    rows[1] = replace(rows[1], package="DLC", source_pamt="C:/game/dlc/1.pamt")
    result = _write(target, rows)
    assert result.count == 2 and not result.cancelled
    if suffix == "txt":
        assert target.read_text(encoding="utf-8").splitlines() == [row.path for row in rows]
    else:
        with target.open(encoding="utf-8-sig", newline="") as stream:
            records = list(csv.DictReader(stream))
        assert [row["path"] for row in records] == [row.path for row in rows]
        assert records[1] == dict(path=rows[1].path, filename="日本語,coat.pac",
                                  package="DLC", source_pamt="C:/game/dlc/1.pamt")
    assert not list(tmp_path.glob(".cdmw-paths-*"))


def test_folder_matches_descendants_without_matching_siblings(tmp_path):
    target = tmp_path / "folder.txt"
    rows = [_remote(i + 1, path) for i, path in enumerate(
        ("object/a.pac", "OBJECT/sub/b.pac", "objects/c.pac", "other/object/d.pac"))]
    result = _write(target, rows, folder="object")
    assert result.count == 2
    assert target.read_text().splitlines() == [rows[0].path, rows[1].path]


@pytest.mark.parametrize("failure", ["cancel", "page", "publish"])
def test_cancel_or_failure_preserves_existing_destination(tmp_path, monkeypatch, failure):
    target = tmp_path / "existing.txt"
    target.write_bytes(b"keep me")
    stop = threading.Event()
    progress = (lambda *_args: stop.set()) if failure == "cancel" else (lambda *_args: None)
    if failure == "publish":
        def deny(*_args):
            raise PermissionError("destination locked")
        monkeypatch.setattr("cdmw.services.archive_path_export.os.replace", deny)
    if failure == "cancel":
        assert _write(target, [_remote(1, "a.pac")], stop=stop, progress=progress).cancelled
    else:
        with pytest.raises((RuntimeError, PermissionError)):
            _write(target, [_remote(1, "a.pac")], failure=RuntimeError("page failed") if failure == "page" else None)
    assert target.read_bytes() == b"keep me"
    assert not list(tmp_path.glob(".cdmw-paths-*"))


def _until(app, predicate):
    end = time.monotonic() + 10
    while not predicate() and time.monotonic() < end:
        app.processEvents()
        QTest.qWait(5)
    assert predicate()


def _metadata_backend(window, monkeypatch, rows, *, hold_pages=False):
    service = window.archive.archive_catalogue_service
    calls = []
    handle = ArchiveQueryHandle("session-a", "path-query", 1, len(rows))

    def query(request, **_kwargs):
        calls.append(request)
        QTimer.singleShot(0, lambda: service.result_ready.emit("path-query-request", "create_query", handle))
        return "path-query-request"

    def page(request, **_kwargs):
        calls.append(request)
        request_id = f"path-page-{request.page_start}"
        result = ArchivePage("session-a", "path-query", 1, len(rows), request.page_start,
                             tuple(rows[request.page_start:request.page_start + request.page_size]))
        if not hold_pages:
            QTimer.singleShot(0, lambda: service.result_ready.emit(request_id, "fetch_page", result))
        return request_id

    monkeypatch.setattr(service, "create_query", query)
    monkeypatch.setattr(service, "fetch_page", page)
    monkeypatch.setattr(service, "cancel", lambda request_id: calls.append(("cancel", request_id)))
    return service, calls


def test_real_action_opens_scope_dialog_and_tracks_busy_state(window, app, monkeypatch):
    archive = window.archive
    _publish(window)
    opened = []

    def execute(dialog):
        opened.append(path_export_dialog._SCOPE_KEYS[dialog.scope.currentIndex()])
        assert dialog._scopes["all"][0].include_text is None
        assert dialog._scopes["filtered"][0].include_text == "object/"
        dialog.reject()

    monkeypatch.setattr(ArchivePathExportDialog, "exec", execute)
    assert archive.archive_export_paths_button.isEnabled()
    menu = archive.findChild(QToolButton, "CompactArchiveActionsButton").menu()
    menu.aboutToShow.emit()
    next(action for action in menu.actions() if action.text() == "Export File Paths...").trigger()
    assert opened == ["filtered"]
    window.set_busy(True)
    assert not archive.archive_export_paths_button.isEnabled()
    window.set_busy(False)
    assert archive.archive_export_paths_button.isEnabled()


def test_selected_files_and_folder_capture_exact_scope(window, app):
    archive = window.archive
    bridge = _publish(window)
    selection = archive.archive_tree.selectionModel()
    for row in (0, 2):
        selection.select(bridge.model.index(row, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
    assert path_export_scopes(archive)["selected"][0].entry_ids == (1, 3)
    bridge = _publish(window, ArchiveViewMode.FOLDERS, folder=True)
    archive.archive_tree.selectionModel().select(bridge.model.index(0, 0),
                                                QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
    query, folder = path_export_scopes(archive)["folder"]
    assert query == bridge.controller.current_query and folder == "object"


def test_export_pages_every_result_and_never_extracts(window, app, tmp_path, monkeypatch):
    _publish(window)
    rows = [_remote(i + 1, f"object/{i:04d}.pac") for i in range(1030)]
    service, calls = _metadata_backend(window, monkeypatch, rows)
    target = tmp_path / "paths.txt"
    monkeypatch.setattr(path_export_dialog.QFileDialog, "getSaveFileName", lambda *_args: (str(target), "Text files (*.txt)"))
    dialog = ArchivePathExportDialog(window.archive)
    try:
        dialog.export_button.click()
        # Other catalogue consumers and old operations cannot supply this export's data.
        service.result_ready.emit("unrelated", "fetch_page", object())
        _until(app, lambda: not dialog.controller.active and window.worker_thread is None)
        assert target.read_text().splitlines() == [row.path for row in rows]
        assert [call.page_start for call in calls if hasattr(call, "page_start")] == [0, 512, 1024]
        assert calls[0].include_text == "object/"
        assert not window.extract_requests
        assert dialog.export_button.isEnabled()
    finally:
        dialog.reject()
        dialog.deleteLater()


def test_close_cancels_pending_query_and_preserves_output(window, app, tmp_path, monkeypatch):
    _publish(window)
    service, calls = _metadata_backend(window, monkeypatch, [_remote(1, "object/a.pac")], hold_pages=True)
    target = tmp_path / "paths.csv"
    target.write_bytes(b"previous list")
    dialog = ArchivePathExportDialog(window.archive)
    dialog.controller.start(dialog._scopes["filtered"][0], target)
    _until(app, lambda: any(hasattr(call, "page_start") for call in calls))
    dialog.reject()
    assert ("cancel", "path-page-0") in calls
    service.result_ready.emit("path-page-0", "fetch_page", object())
    _until(app, lambda: window.worker_thread is None)
    assert target.read_bytes() == b"previous list"
    assert not list(tmp_path.glob(".cdmw-paths-*"))
    dialog.deleteLater()


def test_incomplete_page_fails_without_replacing_destination(window, app, tmp_path, monkeypatch):
    _publish(window)
    service, calls = _metadata_backend(window, monkeypatch, [_remote(1, "object/a.pac")], hold_pages=True)
    target = tmp_path / "paths.txt"
    target.write_bytes(b"previous list")
    dialog = ArchivePathExportDialog(window.archive)
    dialog.controller.start(dialog._scopes["filtered"][0], target)
    _until(app, lambda: any(hasattr(call, "page_start") for call in calls))
    service.result_ready.emit("path-page-0", "fetch_page", ArchivePage("session-a", "path-query", 1, 1, 0, ()))
    _until(app, lambda: not dialog.controller.active and window.worker_thread is None)
    assert "incomplete page" in dialog.status.text()
    assert target.read_bytes() == b"previous list"
    assert not list(tmp_path.glob(".cdmw-paths-*"))
    dialog.reject()
    dialog.deleteLater()


def test_appended_extension_confirms_the_actual_existing_file(window, app, tmp_path, monkeypatch):
    _publish(window)
    target = tmp_path / "paths.csv"
    target.write_bytes(b"previous list")
    monkeypatch.setattr(path_export_dialog.QFileDialog, "getSaveFileName",
                        lambda *_args: (str(target.with_suffix("")), "CSV files (*.csv)"))
    prompts = []
    monkeypatch.setattr(path_export_dialog.QMessageBox, "question",
                        lambda *args: prompts.append(args[2]) or path_export_dialog.QMessageBox.No)
    dialog = ArchivePathExportDialog(window.archive)
    dialog.export_button.click()
    assert prompts == [str(target)]
    assert not dialog.controller.active and target.read_bytes() == b"previous list"
    dialog.reject()
    dialog.deleteLater()


def test_backend_cancellation_message_releases_export_controls(window, app, tmp_path, monkeypatch):
    _publish(window)
    service, calls = _metadata_backend(window, monkeypatch, [_remote(1, "object/a.pac")], hold_pages=True)
    target = tmp_path / "paths.txt"
    dialog = ArchivePathExportDialog(window.archive)
    dialog.controller.start(dialog._scopes["filtered"][0], target)
    _until(app, lambda: any(hasattr(call, "page_start") for call in calls))
    service.request_failed.emit("path-page-0", "Processing stopped by user.")
    _until(app, lambda: not dialog.controller.active and window.worker_thread is None)
    assert dialog.export_button.isEnabled()
    assert not target.exists() and not list(tmp_path.glob(".cdmw-paths-*"))
    dialog.reject()
    dialog.deleteLater()


@pytest.mark.parametrize("invalidate_at", [None, "query", "page"], ids=["current", "cancel-query", "cancel-page"])
def test_export_with_resident_catalogue(window, app, tmp_path, monkeypatch, invalidate_at):
    """Use the real service/client, including cancellation inside submit()."""
    client = ArchiveBackendClient(
        cache_root=tmp_path / "worker-cache", worker_program=sys.executable,
        worker_arguments=("-u", str(Path(__file__).parent / "helpers/archive_backend_worker_stub.py")),
        parent=window,
    )
    service = ArchiveCatalogueService(client, parent=window)
    dialog = None
    try:
        service.invalidate_before(7)
        service.open_archive(OpenArchiveRequest("synthetic-root"), ui_generation=7)
        _until(app, lambda: service.current_session is not None)
        assert client.is_ready
        monkeypatch.setattr(window.archive, "archive_catalogue_service", service)
        browser = window.archive.archive_remote_bridge.controller
        browser._generation = 7
        browser._current_session = service.current_session
        browser._current_query = ArchiveQuery(service.current_session.session_id)
        target = tmp_path / "paths.txt"
        target.write_text("previous list", encoding="utf-8")
        monkeypatch.setattr(path_export_dialog.QFileDialog, "getSaveFileName",
                            lambda *_args: (str(target), "Text files (*.txt)"))
        dialog = ArchivePathExportDialog(window.archive)
        if invalidate_at == "query":
            service.invalidate_before(8)
        elif invalidate_at == "page":
            service.result_ready.connect(
                lambda _request_id, operation, _result:
                    service.invalidate_before(8) if operation == "create_query" else None)
        dialog.export_button.click()
        _until(app, lambda: not dialog.controller.active and window.worker_thread is None)
        assert dialog.export_button.isEnabled() and dialog.scope.isEnabled()
        if invalidate_at is None:
            assert target.read_text(encoding="utf-8").splitlines() == ["character/model/stub.pac"]
            assert "Exported 1 paths" in dialog.status.text()
        else:
            assert "cancelled" in dialog.status.text()
            assert target.read_text(encoding="utf-8") == "previous list"
        assert not list(tmp_path.glob(".cdmw-paths-*"))
        operations = (tmp_path / "worker-cache/stub-operations.log").read_text().splitlines()
        assert set(operations) <= {"ping", "open_archive", "create_query", "fetch_page"}
    finally:
        if dialog is not None:
            dialog.reject()
            _until(app, lambda: window.worker_thread is None)
            dialog.deleteLater()
        service.request_shutdown()
        _until(app, lambda: client.state is ArchiveBackendClientState.STOPPED)
        service.deleteLater()
        client.deleteLater()
        app.processEvents()
