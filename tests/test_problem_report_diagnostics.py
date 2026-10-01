from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import threading
import time
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.domain.cancellation import RunCancelled
from cdmw.core.common import ProcessTimeoutExpired, run_process_with_cancellation
from cdmw.modding import mesh_native_dispatch, mesh_native_session_api
from cdmw.services.diagnostics_service import RuntimeDiagnosticLogHandler, RuntimeEventRecorder, read_jsonl_tail
from cdmw.services.mesh_interaction_diagnostics import MeshInteractionFlightRecorder
from cdmw.services.problem_report_diagnostics import EVENT_BYTE_LIMIT, _binary_identity, collect_report_logs
from cdmw.services.problem_report_service import ProblemReportRequest, ProblemSnapshot, collect_problem_report, load_problem_report
from cdmw.ui.shell.compact.workspace import append_compact_activity
from cdmw.ui.shell.problem_report_dialog import ProblemReportDialog
from cdmw.ui.shell.profile_controller import ProfileControllerMixin
from cdmw.workers.utility_workers import UtilityWorker
from tests.test_problem_reporting import app, details, fill_form


@pytest.fixture
def recorder(tmp_path, monkeypatch):
    monkeypatch.setattr(mesh_native_dispatch, "_LAST_NATIVE_JOB_ERROR", [""])
    monkeypatch.setattr(mesh_native_dispatch, "_LAST_NATIVE_JOB_REJECTION", [""])
    events = RuntimeEventRecorder(tmp_path / "logs" / "diagnostics_current.jsonl", session_id="diagnostic-test")
    handler = RuntimeDiagnosticLogHandler(events)
    logging.getLogger().addHandler(handler)
    try:
        yield events
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()


def report_snapshot(tmp_path, recorder):
    return ProblemSnapshot(workspace_root=str(tmp_path), event_log=str(recorder.log_path),
                           recent_events_json=json.dumps(recorder.tail()), captured_at=time.time())


def test_reports_preserve_errors_from_multiple_tools_and_the_native_reason_after_cleanup(tmp_path, recorder, monkeypatch):
    owner = SimpleNamespace(shell=SimpleNamespace(_record_runtime_event=recorder.record))
    append_compact_activity(owner, "Loading language tables", tool_key="translations")
    append_compact_activity(owner, "ERROR: Language table is invalid", tool_key="translations")
    append_compact_activity(owner, "Preparing a mod package", tool_key="mod_management")

    def fail_export(_log):
        raise ValueError("Package export failed; password=private-value")

    worker = UtilityWorker(fail_export)
    errors, finished = [], []
    worker.error.connect(errors.append)
    worker.finished.connect(lambda: finished.append(True))
    worker.run()
    assert errors == ["Package export failed; password=private-value"] and finished == [True]

    helper = SimpleNamespace(run_inline_job=lambda *a, **k: {
        "inline_report": {"status": "error", "error": "Snapshot source identity mismatch"}})
    monkeypatch.setattr(mesh_native_dispatch, "_get_native_mesh_core_service", lambda path: helper)
    assert mesh_native_dispatch._run_native_mesh_core_service_inline_job(
        Path("native-helper.exe"), "mesh-editor-session-json",
        {"command": "morph_snapshot_restore", "session_id": "isolated-session", "snapshot_id": "snapshot-1",
         "vertices": "private-game-payload", "backend": "resident-core"}, timeout_seconds=15) is None
    helper.run_inline_job = lambda *a, **k: {"inline_report": {"status": "ok"}}
    mesh_native_dispatch._run_native_mesh_core_service_inline_job(
        Path("native-helper.exe"), "mesh-editor-session-json", {"command": "close"}, timeout_seconds=5)
    assert mesh_native_dispatch.last_native_mesh_core_job_error() == ""

    report = collect_problem_report(ProblemReportRequest(details(), report_snapshot(tmp_path, recorder), include_layout=False))
    payload = json.loads(report.body)
    logs = payload["evidence"]["logs"]
    assert any(row.get("tool_key") == "translations" and row.get("severity") == "error" for row in logs["runtime_events"])
    assert "Loading language tables" in report.preview and "Preparing a mod package" in report.preview
    assert "ValueError: Package export failed" in report.preview
    assert "Snapshot source identity mismatch" in report.preview
    native = next(row for row in logs["latest_failures"] if row.get("component") == mesh_native_dispatch.__name__)
    assert native["diagnostic_context"]["command"] == "morph_snapshot_restore"
    assert native["diagnostic_context"]["session_id"] == "isolated-session"
    assert native["diagnostic_context"]["timeout_seconds"] == 15
    assert "private-game-payload" not in report.preview and "private-value" not in report.preview
    reopened = load_problem_report(str(report.draft_path), report_snapshot(tmp_path, recorder))
    assert reopened.body == report.body and reopened.preview == report.preview


def test_verbose_logging_is_not_required_to_keep_a_long_exception_chain(tmp_path):
    events = RuntimeEventRecorder(tmp_path / "events.jsonl", session_id="s", memory_snapshot=lambda pid: (_ for _ in ()).throw(OSError("memory unavailable")))
    trace = "Traceback: " + "frame\n" * 3000 + "ValueError: actual final cause"
    events.record("worker_failure", traceback=trace)
    events.record("tool_activity", severity="error", message="Export refused")
    events.record("tool_activity", severity="info", message="Normal progress")
    rows = read_jsonl_tail(events.log_path)
    assert len(rows) == 2 and rows[0]["traceback"].endswith("ValueError: actual final cause")
    assert "earlier frames truncated" in rows[0]["traceback"]
    assert len(events.tail()) == 3


def test_report_tails_are_bounded_filter_future_rows_and_expose_missing_or_broken_sources(tmp_path, recorder):
    directory = recorder.log_path.parent
    directory.mkdir()
    recorder.log_path.write_bytes(b"x" * (EVENT_BYTE_LIMIT + 1) + b'\n{"event":"old error","timestamp":1}\ninvalid\n{"timestamp":99,"event":"future"}\n')
    (directory / "archive_scan_breadcrumb.json").write_text("not-json")
    (directory / "ui_breadcrumb.json").write_text(json.dumps({"tool_key": "translations"}))
    (directory / "native_diagnostics_verbose.jsonl").write_text('{"event":"native warning"}\n')
    (directory / "unrelated-private.txt").write_text("do not read")
    for index in range(5):
        (directory / f"worker_error_20261001_185430_{index:03d}_1.log").write_text(f"Kind: worker_error\nOriginal traceback {index}\n")
    large_name = "custom_tool_failure_20261001_185435_555_1.log"
    (directory / large_name).write_text("Kind: custom_tool_failure\n" + "a" * 50000 + "Final exception\n")
    cutoff = time.time()
    # Keep only the numeric log cutoff old; on-disk breadcrumbs/crashes are
    # legitimately from before this snapshot.
    snap = dataclasses.replace(report_snapshot(tmp_path, recorder), captured_at=cutoff)
    logs = collect_report_logs(snap)
    assert logs["collection"]["runtime_current"]["truncated"]
    assert logs["collection"]["runtime_current"]["invalid_lines"] == 1
    assert logs["collection"]["mesh_protocol"]["status"] == "missing"
    assert logs["collection"]["archive_scan_breadcrumb"]["status"] == "invalid_json"
    assert logs["collection"]["native_events"]["events_without_timestamp"] == 1
    assert len(logs["crash_reports"]) == 3 and logs["collection"]["crash_reports"]["report_limit_reached"]
    large = next(item for item in logs["crash_reports"] if item["file"] == large_name)
    assert large["truncated"] and "Kind: custom_tool_failure" in large["excerpt"] and "Final exception" in large["excerpt"]
    old = collect_report_logs(dataclasses.replace(snap, captured_at=10))
    assert old["collection"]["runtime_current"]["events_after_snapshot"] == 1
    assert all(row.get("event") != "future" for row in old["runtime_events"])


def test_mesh_options_survive_memory_snapshot_without_geometry_or_file_payloads(tmp_path):
    recorder = MeshInteractionFlightRecorder(lambda: tmp_path / "protocol.jsonl")
    try:
        recorder.record("protocol", "helper_to_host", {"event": "replacement_compare", "session_id": "s",
            "args": {"mode": "original", "part_index": 15, "included": False, "part_indices": [0, 15],
                     "part_ids": ["stable-part-0", "stable-part-15"],
                     "payload": "private game file contents"}, "vertices": [[1, 2, 3]], "data": "private DDS data"})
        snapshot = recorder.snapshot()
        row = snapshot["recent_events"][0]
        assert row["args"]["mode"] == "original" and row["args"]["part_index"] == 15
        assert row["args"]["included"] is False and row["args"]["part_indices"] == [0, 15]
        assert row["args"]["part_ids"] == ["stable-part-0", "stable-part-15"]
        assert row["vertices"] == {"value_type": "list", "item_count": 1}
        assert "private game file contents" not in json.dumps(snapshot) and "private DDS data" not in json.dumps(snapshot)
        assert recorder.flush()
        # The persisted protocol may contain large inputs; reports summarize it
        # through the same policy instead of including the raw file contents.
        (tmp_path / "dotnet_protocol_current.jsonl").write_bytes((tmp_path / "protocol.jsonl").read_bytes())
        logs = collect_report_logs(ProblemSnapshot(workspace_root=str(tmp_path), event_log=str(tmp_path / "events.jsonl"), captured_at=time.time()))
        assert logs["mesh_events"][0]["args"]["mode"] == "original"
        assert "private DDS data" not in json.dumps(logs) and "private game file contents" not in json.dumps(logs)
    finally:
        assert recorder.shutdown()


def test_logs_opt_out_and_nonfinite_diagnostic_values_do_not_break_drafts(tmp_path, monkeypatch):
    snap = ProblemSnapshot(workspace_root=str(tmp_path), captured_at=time.time(),
        context_json='{"memory_value":NaN}', recent_events_json='[{"message":"private traceback"}]',
        mesh_diagnostics_json='{"last_error":"private helper error"}', tool_logs_json='{"translations":"private log"}')
    monkeypatch.setattr("cdmw.services.problem_report_diagnostics.collect_report_logs", lambda *a, **k: pytest.fail("opted-out logs collected"))
    report = collect_problem_report(ProblemReportRequest(details(), snap, include_logs=False, include_layout=False))
    payload = json.loads(report.body)
    assert "logs" not in payload["evidence"] and payload["evidence"]["context"]["memory_value"] == "nan"
    assert payload["evidence"]["collection_options"]["logs"] == "omitted by user"
    assert "private traceback" not in report.preview and "private log" not in report.preview
    assert load_problem_report(str(report.draft_path), snap).body == report.body


def test_cancelled_evidence_collection_and_binary_hashing_publish_nothing(tmp_path, recorder):
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(RunCancelled):
        collect_report_logs(report_snapshot(tmp_path, recorder), stop_event=cancelled)
    with pytest.raises(RunCancelled):
        collect_problem_report(ProblemReportRequest(details(), report_snapshot(tmp_path, recorder)), stop_event=cancelled)
    assert not (tmp_path / "problem_reports").exists()
    with pytest.raises(RunCancelled):
        _binary_identity(tmp_path / "helper.exe", stop_event=cancelled)


def test_binary_identity_hashes_helper_bytes_and_rejects_non_binary_inputs(tmp_path):
    binary = tmp_path / "helper.exe"
    binary.write_bytes(b"synthetic executable")
    result = _binary_identity(binary)
    assert result["status"] == "available" and result["sha256"] == hashlib.sha256(binary.read_bytes()).hexdigest()
    assert _binary_identity(tmp_path / "game.pamt")["status"] == "skipped_non_binary_extension"


@pytest.mark.parametrize("failure", ["schema", "missing_file", "length", "checksum"])
def test_snapshot_restore_validation_records_specific_reason_before_dispatch(tmp_path, recorder, monkeypatch, failure):
    path = tmp_path / "cdmw_mesh_preview_delta_test_morph_runtime_snapshot.json"
    path.write_bytes(b"{}")
    descriptor = {"schema": "cdmw_mesh_editor_morph_runtime_snapshot_v1", "version": 1,
        "snapshot_id": "snap", "source_session_id": "source", "path": str(path),
        "sha256": hashlib.sha256(b"{}").hexdigest(), "topology_digest": "0" * 64,
        "byte_length": 2, "retained_bytes": 1}
    monkeypatch.setattr(mesh_native_session_api.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(mesh_native_session_api, "native_mesh_editor_session_command", lambda *a, **k: pytest.fail("invalid snapshot reached native core"))
    expected = {"schema": "schema mismatch", "missing_file": "FileNotFoundError", "length": "file length differs", "checksum": "checksum differs"}[failure]
    if failure == "schema": descriptor["schema"] = "unknown"
    elif failure == "missing_file": path.unlink()
    elif failure == "length": path.write_bytes(b"{} ")
    else: path.write_bytes(b"[]")
    assert mesh_native_session_api.restore_native_mesh_editor_morph_runtime_snapshot("target", descriptor) is None
    assert expected in mesh_native_dispatch.last_native_mesh_core_job_error()
    row = recorder.tail()[-1]
    assert row["diagnostic_context"]["command"] == "morph_snapshot_restore"
    assert row["diagnostic_context"]["source_session_id"] == "source"
    assert expected in row["message"]


def test_collection_refreshes_snapshot_on_the_ui_thread(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QWidget

    app()
    parent = QWidget()
    old = ProblemSnapshot(workspace_root=str(tmp_path), live_log="before the error", captured_at=1)
    fresh = dataclasses.replace(old, live_log="ERROR: failure while form was open", captured_at=2)
    parent._problem_report_snapshot = lambda: fresh
    dialog = ProblemReportDialog(old, parent)
    requests = []
    monkeypatch.setattr(dialog, "_start_collection", requests.append)
    try:
        fill_form(dialog)
        dialog._collect()
        assert len(requests) == 1 and requests[0].snapshot == fresh
    finally:
        dialog.close()
        parent.close()


def test_shell_snapshot_uses_actual_log_directory_and_only_copies_memory(tmp_path, monkeypatch, recorder):
    from PySide6.QtWidgets import QPlainTextEdit, QWidget

    app()
    log = QPlainTextEdit()
    log.setPlainText("Translations import failed")
    tool = QWidget()
    tool.log_view = log
    owner = SimpleNamespace(settings_file_path=tmp_path / "settings.ini", crash_reports_dir=tmp_path / "custom-logs",
        _runtime_event_tail=recorder.tail, _tool_widgets_by_key={"translations": tool},
        _diagnostic_context_snapshot=lambda: {"current_tab": "Translations"},
        archive=SimpleNamespace(archive_package_root_edit=SimpleNamespace(text=lambda: "D:/Game/image"),
                                archive_log_view=SimpleNamespace(toPlainText=lambda: "archive")),
        textures=SimpleNamespace(log_view=SimpleNamespace(toPlainText=lambda: "live")))
    owner.shell = owner
    recorder.record("translation_import_failed", error="bad table")
    with monkeypatch.context() as guarded:
        for name in ("resolve", "stat", "open"):
            guarded.setattr(Path, name, lambda *a, **k: pytest.fail("snapshot performed filesystem inspection"))
        snap = ProfileControllerMixin._problem_report_snapshot(owner)
    assert snap.event_log == str(tmp_path / "custom-logs" / "diagnostics_current.jsonl")
    assert "translation_import_failed" in snap.recent_events_json
    assert "Translations import failed" in snap.tool_logs_json
    log.close()
    tool.close()


def test_external_helper_exit_and_timeout_keep_stderr_without_arguments_or_stdout(tmp_path, recorder):
    result = run_process_with_cancellation([sys.executable, "-c",
        "import sys; print('private mesh payload'); sys.stderr.write('x'*5000+'\\nactual helper failure\\n'); sys.exit(7)"])
    assert result[0] == 7 and "private mesh payload" in result[1]
    event = recorder.tail()[-1]
    assert event["diagnostic_context"]["exit_code"] == 7
    assert event["diagnostic_context"]["stderr"].endswith("actual helper failure\n")
    assert len(event["diagnostic_context"]["stderr"]) <= 4000
    assert "private mesh payload" not in json.dumps(event)
    with pytest.raises(ProcessTimeoutExpired):
        run_process_with_cancellation([sys.executable, "-c", "import time; time.sleep(20)"], timeout_seconds=0.1)
    assert recorder.tail()[-1]["diagnostic_context"]["timeout_seconds"] == 0.1


def test_archive_request_error_keeps_operation_generation_and_detail(tmp_path, recorder):
    from cdmw.domain.archives.catalogue_operations import ArchiveBackendEnvelope, ArchiveBackendError, ArchiveBackendOperation, PingRequest
    from cdmw.ui.shell.archive_backend_client import ArchiveBackendClient, _PendingRequest

    app()
    client = ArchiveBackendClient(cache_root=tmp_path)
    envelope = ArchiveBackendEnvelope.request(ArchiveBackendOperation.PING, PingRequest("test"), ui_generation=7)
    client._pending[envelope.request_id] = _PendingRequest(envelope, "session", None)
    failed = []
    client.request_failed.connect(lambda request_id, error: failed.append((request_id, error)))
    error = ArchiveBackendError("source_changed", "Archive source changed", "Archive backend stack detail")
    client._fail_request(envelope.request_id, error)
    assert failed == [(envelope.request_id, error)] and not client._pending
    event = recorder.tail()[-1]
    assert event["diagnostic_context"]["operation"] == "ping"
    assert event["diagnostic_context"]["ui_generation"] == 7
    assert event["diagnostic_context"]["detail"] == "Archive backend stack detail"
    assert event["diagnostic_context"]["session_id"] == "session"
    client.deleteLater()


def test_diagnostic_handler_failure_cannot_change_worker_result_or_completion(monkeypatch):
    from cdmw.workers.qt_worker_runner import run_worker_task
    from cdmw.workers.results import WorkerFailure

    def failure(_log=None):
        raise ValueError("original operation error")

    monkeypatch.setattr(logging.Logger, "exception", lambda *a, **k: (_ for _ in ()).throw(OSError("bad logger")))
    worker = UtilityWorker(failure)
    errors, finished = [], []
    worker.error.connect(errors.append)
    worker.finished.connect(lambda: finished.append(True))
    worker.run()
    assert errors == ["original operation error"] and finished == [True]
    result = run_worker_task(failure)
    assert isinstance(result, WorkerFailure) and result.message == "original operation error"


def test_normal_activity_does_not_sample_process_memory(tmp_path):
    samples = []
    events = RuntimeEventRecorder(tmp_path / "events.jsonl", session_id="s", memory_snapshot=lambda pid: samples.append(pid) or {})
    events.record("tool_activity", severity="info", message="progress")
    assert not samples and "memory_total_private_bytes" not in events.tail()[0]
    events.record("tool_activity", severity="error", message="failed")
    assert samples


def test_report_tracebacks_keep_application_locations_after_redaction(tmp_path, recorder):
    try:
        exec(compile("raise ValueError('source changed')", "D:/Private Name/CDMW/cdmw/services/mod_package_service.py", "exec"))
    except ValueError:
        logging.getLogger("cdmw.services.mod_package_service").exception("Export rejected")
    report = collect_problem_report(ProblemReportRequest(details(), report_snapshot(tmp_path, recorder), include_layout=False))
    assert 'cdmw/services/mod_package_service.py' in report.preview
    assert "Private Name" not in report.preview
    assert "ValueError: source changed" in report.preview


def test_cancellation_during_helper_hash_keeps_the_report_unpublished(tmp_path, monkeypatch):
    binary = tmp_path / "helper.exe"
    binary.write_bytes(b"x" * (2 * 1024 * 1024))
    stop = threading.Event()
    original_open = Path.open

    class CancellingReader:
        def __init__(self, handle): self.handle = handle
        def __enter__(self): return self
        def __exit__(self, *args): self.handle.close()
        def read(self, count):
            data = self.handle.read(count)
            stop.set()
            return data
        def fileno(self): return self.handle.fileno()

    def guarded_open(path, *args, **kwargs):
        handle = original_open(path, *args, **kwargs)
        return CancellingReader(handle) if path == binary else handle

    monkeypatch.setattr(Path, "open", guarded_open)
    monkeypatch.setattr("cdmw.services.mesh_rust_contract.resolve_rust_mesh_editor", lambda: SimpleNamespace(resolved_path=str(binary), is_file=True, source="test"))
    snap = ProblemSnapshot(workspace_root=str(tmp_path), captured_at=time.time())
    with pytest.raises(RunCancelled):
        collect_problem_report(ProblemReportRequest(details(), snap), stop_event=stop)
    assert not (tmp_path / "problem_reports").exists()


def test_broken_helper_resolution_does_not_block_reporting_another_tool(tmp_path, monkeypatch):
    def broken_resolution():
        raise OSError("Helper resolution failed")

    monkeypatch.setattr("cdmw.services.mesh_rust_contract.resolve_rust_mesh_editor", broken_resolution)
    monkeypatch.setattr("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", broken_resolution)
    snap = ProblemSnapshot(workspace_root=str(tmp_path), captured_at=time.time(), live_log="Translation import failed")
    report = collect_problem_report(ProblemReportRequest(details(), snap, include_layout=False))
    identity = json.loads(report.body)["evidence"]["environment"]["build_identity"]
    assert identity["rust_helper"]["status"] == "unavailable" and identity["native_mesh_core"]["status"] == "unavailable"
    assert "Helper resolution failed" in report.preview and "Translation import failed" in report.preview
    assert report.draft_path.read_bytes() == report.body
