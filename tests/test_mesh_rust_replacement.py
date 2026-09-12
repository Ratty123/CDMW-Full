from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from cdmw.models import ArchiveEntry
from cdmw.services.mesh_rust_authoring import RustMeshValidationError
from tests.test_mesh_rust_authoring_exact_output import _open_exact_session, _request, _candidate_reference


def command(session, name, arguments=None):
    if name == "replacement_apply" and session.pending_replacement is not None:
        arguments = {"token": session.pending_replacement.token, **(arguments or {})}
    return session.run_command({**_request(session, "command_request", 1), "command": name, "arguments": arguments or {}})


def prepare_source(session, tmp_path):
    path = tmp_path / "replacement.obj"
    path.write_text("o replacement\nv 12 3 7\nv 16 3 7\nv 12 5 8\nf 1 2 3\n")
    entry = ArchiveEntry("owned-rust-exact.pac", tmp_path / "0009/0.pamt", tmp_path / "0009/0.paz", 0, 0, 0, 0, 0)
    context = SimpleNamespace(entries_by_basename={}, entries_by_normalized_path={})
    return command(session, "replacement_choose", {"scope": "entire", "source_path": str(path),
        "_archive_entry": entry, "_archive_dependencies": context})


def test_rust_replacement_preview_edit_and_finish(tmp_path):
    source, service, session = _open_exact_session(tmp_path / "session")
    try:
        result = prepare_source(session, tmp_path)
        pending = result["state"]["replacement"]["pending"]
        key = pending["targets"][0]["id"]
        before = service.capture_export_snapshot(session.authoritative_session_id)
        result = command(session, "replacement_apply", {"targets": [key], "materials": "original"})
        assert result["state"]["output_policy"] == "replacement_game_asset"
        assert service.session_view(session.authoritative_session_id).revision == before.mesh_revision
        edit = session.shadow_service.working_mesh(session.shadow_session_id)
        assert list(edit.submeshes[0].vertices) == [(12, 3, 7), (16, 3, 7), (12, 5, 8)]
        result = command(session, "replacement_compare", {"mode": "output"})
        assert result["state"]["authoring_enabled"] is False
        assert "document" in result["state"]
        with pytest.raises(RustMeshValidationError, match="Return to Edit"):
            command(session, "replacement_include", {"part_ids": [key], "included": False})
        command(session, "replacement_compare", {"mode": "edit"})
        candidate = _candidate_reference(session, request_id=21, first_x=13)
        session.apply_candidate({**_request(session, "transaction_request", 21), "candidate": candidate})
        snapshot = session.shadow_service.capture_export_snapshot(session.shadow_session_id)
        expected = session.shadow_service._replacement_output_for_snapshot(snapshot)
        session.finish(_request(session, "finish_request", 22))
        snapshot = service.capture_export_snapshot(session.authoritative_session_id)
        output, _ = service.rebuild_result_from_snapshot(snapshot)
        assert snapshot.replacement_state is not None
        assert output.data == expected.data
        assert list(snapshot.mesh.submeshes[0].vertices)[0] == (13, 3, 7)
    finally:
        if not session.closed:
            session.cancel()
        service.close_edit_session(session.authoritative_session_id)


def test_failed_renderer_preparation_and_old_mapping_are_inert(tmp_path, monkeypatch):
    _, service, session = _open_exact_session(tmp_path / "session")
    try:
        prepare_source(session, tmp_path)
        old = session.pending_replacement.token
        prepared = prepare_source(session, tmp_path)
        key = prepared["state"]["replacement"]["pending"]["targets"][0]["id"]
        with pytest.raises(ValueError, match="older import"):
            command(session, "replacement_apply", {"token": old, "targets": [key]})
        before = session.shadow_service.capture_export_snapshot(session.shadow_session_id)
        monkeypatch.setattr("cdmw.services.mesh_rust_replacement_materials.stage_replacement_materials",
                            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Renderer resource rejected")))
        with pytest.raises(RuntimeError, match="Renderer resource rejected"):
            command(session, "replacement_apply", {"targets": [key]})
        after = session.shadow_service.capture_export_snapshot(session.shadow_session_id)
        assert after.mesh_revision == before.mesh_revision
        assert after.replacement_state is None
        assert session.shadow_service.session_view(session.shadow_session_id).undo_count == 0
    finally:
        session.cancel()
        service.close_edit_session(session.authoritative_session_id)


def test_cancel_and_stale_import_keep_previous_authoritative_session(tmp_path):
    _, service, session = _open_exact_session(tmp_path / "session")
    try:
        before = service.capture_export_snapshot(session.authoritative_session_id)
        result = prepare_source(session, tmp_path)
        key = result["state"]["replacement"]["pending"]["targets"][0]["id"]
        command(session, "select", {"selection": {"source_indices": [0]}, "operation": "replace"})
        with pytest.raises(ValueError, match="mesh changed"):
            command(session, "replacement_apply", {"targets": [key]})
        command(session, "replacement_cancel")
        assert session.pending_replacement is None
        assert service._session(session.authoritative_session_id).replacement_state is None
        assert service.session_view(session.authoritative_session_id).revision == before.mesh_revision
    finally:
        session.cancel()
        service.close_edit_session(session.authoritative_session_id)
@pytest.mark.parametrize("reject", [False, True])
def test_protocol_status_waits_for_worker_destruction(reject):
    import time
    import shiboken6
    from PySide6.QtCore import QObject, QThread, Signal, Slot
    from PySide6.QtWidgets import QApplication
    from tests.test_mesh_rejection_logging import _Editor

    class Worker(QObject):
        completed = Signal(int, int, dict, bool)
        error = Signal(int, int, str, str, dict)
        finished = Signal()

        @Slot()
        def run(self):
            if reject:
                self.error.emit(7, 1, "command_request", "Missing required texture", {})
            else:
                self.completed.emit(7, 1, {"payload": {"result": {}}}, False)
            self.finished.emit()

    app = QApplication.instance() or QApplication([])
    editor = _Editor()
    editor._initialize_rust_editor_runtime_state()
    editor.standalone_rust_protocol_request_id = 7
    editor.standalone_rust_active_event = {"event": "command_request", "command": "replacement_include"}
    editor._start_next_rust_protocol_worker = lambda: None
    worker, thread = Worker(), QThread()
    editor.standalone_rust_protocol_worker = worker
    editor.standalone_rust_protocol_thread = thread
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.completed.connect(editor._handle_rust_protocol_completed)
    worker.error.connect(editor._handle_rust_protocol_worker_error)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(lambda: editor._handle_rust_protocol_thread_finished(thread))
    observed = []
    editor.status_message_requested.connect(lambda message, error: observed.append(
        (message, error, shiboken6.isValid(worker), QThread.currentThread() == app.thread())))
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not observed and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.001)
        assert len(editor.responses) == 1
        assert len(observed) == 1
        assert observed[0][1:] == (reject, False, True)
        assert ("Missing required texture" if reject else "completed") in observed[0][0]
        assert editor.standalone_rust_protocol_status is None
    finally:
        thread.quit()
        assert thread.wait(2000)
        thread.deleteLater()
        editor.standalone_status_label.deleteLater()
        editor.deleteLater()
        app.processEvents()
