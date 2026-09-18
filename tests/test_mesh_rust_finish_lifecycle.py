import time
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import shiboken6
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication, QDialog

from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
from cdmw.ui.shell.compact.activity import ActivityHistory, tool_log_adapter_for
from cdmw.ui.shell.compact.drawer import CompactActivityDrawer
from cdmw.workers.mesh_rust_editor_workers import MeshRustProtocolWorker
from tests import test_mesh_rust_authoring as authoring_fixtures
from tests.test_mesh_rust_authoring import _candidate_reference, _request
from tests.test_mesh_rust_editor_selection import _BufferedProcess, _dispose, _tab


def _attach_session(tab, service, session):
    controller = SimpleNamespace(
        active_selection_mode="vertex",
        session_view=lambda: service.session_view(session.authoritative_session_id),
    )
    tab.standalone_controller = controller
    tab.standalone_rust_target_controller = controller
    tab.standalone_rust_authoring_session = session
    tab.standalone_rust_protocol_request_id = 7


@pytest.mark.parametrize("event", ["finish_request", "cancel"])
@pytest.mark.parametrize("exit_before_teardown", [False, True])
def test_terminal_response_survives_shadow_disposal_and_helper_exit(
    tmp_path, event, exit_before_teardown,
):
    tab = _tab(tmp_path)
    service, session = authoring_fixtures.RustMeshAuthoringTests()._create(tmp_path / "session")
    _attach_session(tab, service, session)
    process, thread = _BufferedProcess(), object()
    tab.standalone_rust_process = process
    tab.standalone_rust_protocol_thread = thread
    notices, sent = [], []
    tab.status_message_requested.connect(lambda message, error: notices.append((message, error)))
    try:
        edit = _request(session, "transaction_request", 1)
        edit["candidate"] = _candidate_reference(session, request_id=1, first_x=0.75)
        session.apply_candidate(edit)
        request = _request(session, event, 2)
        tab.standalone_rust_active_event = request
        worker = MeshRustProtocolWorker(7, session, request)
        tab.standalone_rust_protocol_worker = worker
        completed, errors = [], []
        worker.completed.connect(lambda *args: completed.append(args))
        worker.error.connect(lambda *args: errors.append(args))
        worker.run()
        assert not errors and len(completed) == 1
        assert session.closed
        with pytest.raises(KeyError):
            session.shadow_service.session_view(session.shadow_session_id)

        def send(response):
            sent.append((response, tab.standalone_rust_finish_accepted, tab.standalone_rust_closing))
            return True

        with patch.object(tab, "_send_rust_message", side_effect=send):
            tab._handle_rust_protocol_completed(*completed[0])
        assert sent[0][0]["ok"] is True
        assert sent[0][1 if event == "finish_request" else 2] is True
        if exit_before_teardown:
            tab._handle_rust_process_finished(process, 0, QProcess.ExitStatus.NormalExit)
        tab._handle_rust_protocol_thread_finished(thread)
        if not exit_before_teardown:
            tab._handle_rust_process_finished(process, 0, QProcess.ExitStatus.NormalExit)

        expected = "accepted the validated geometry" if event == "finish_request" else "cancelled; CDMW mesh unchanged"
        assert expected in tab.standalone_status_label.text()
        assert not any(error or "discarded" in message or "waiting" in message for message, error in notices)
        mesh = service.working_mesh(session.authoritative_session_id, clone=False)
        assert mesh.submeshes[0].vertices[0][0] == (0.75 if event == "finish_request" else 0.0)
        if event == "finish_request":
            service.undo(session.authoritative_session_id)
            assert service.working_mesh(session.authoritative_session_id, clone=False).submeshes[0].vertices[0][0] == 0.0
            service.redo(session.authoritative_session_id)
            assert service.working_mesh(session.authoritative_session_id, clone=False).submeshes[0].vertices[0][0] == 0.75
    finally:
        tab.standalone_rust_protocol_thread = None
        tab.standalone_rust_protocol_worker = None
        tab.standalone_rust_process = None
        tab.standalone_rust_authoring_session = None
        tab.standalone_controller = None
        session.cancel()
        service.close_edit_session(session.authoritative_session_id, force_without_saving=True)
        _dispose(tab)


def test_refit_finish_reaches_ui_and_preserves_refit_undo_redo(tmp_path):
    tab = _tab(tmp_path)
    original_finish = RustMeshAuthoringSession.finish
    accepted = []

    def finish(session, request, **kwargs):
        result = original_finish(session, request, **kwargs)
        _attach_session(tab, session.authoritative_service, session)
        tab.standalone_rust_active_event = request
        with patch.object(tab, "_send_rust_message", return_value=True):
            tab._handle_rust_protocol_completed(
                7, request["request_id"], {"event": "finish_result", "ok": True, "payload": result}, True,
            )
        accepted.append(tab.standalone_rust_finish_accepted)
        assert "accepted the validated geometry" in tab.standalone_status_label.text()
        return result

    try:
        with patch.object(RustMeshAuthoringSession, "finish", finish):
            authoring_fixtures.RustMeshAuthoringTests().test_morph_refit_runtime_survives_finish_undo_and_redo()
        assert accepted == [True]
    finally:
        tab.standalone_rust_authoring_session = None
        tab.standalone_controller = None
        _dispose(tab)


def test_unexpected_clean_exit_is_reported_as_an_error(tmp_path):
    tab = _tab(tmp_path)
    process = _BufferedProcess()
    tab.standalone_rust_process = process
    notices = []
    tab.status_message_requested.connect(lambda message, error: notices.append((message, error)))
    try:
        tab._handle_rust_process_finished(process, 0, QProcess.ExitStatus.NormalExit)
        assert len(notices) == 1
        assert "closed (exit 0)" in notices[0][0]
        assert notices[0][1] is True
    finally:
        _dispose(tab)


@pytest.mark.parametrize("event", ["finish_request", "cancel", "rejected_finish"])
def test_terminal_status_is_published_after_real_worker_teardown(tmp_path, event):
    tab = _tab(tmp_path)
    service, session = authoring_fixtures.RustMeshAuthoringTests()._create(tmp_path / "session")
    _attach_session(tab, service, session)
    request = _request(session, "finish_request" if event == "rejected_finish" else event, 1)
    tab.standalone_rust_process = _BufferedProcess()
    tab.standalone_rust_protocol_queue.append(request)
    notices, replies = [], []
    worker = None

    def status(message, error):
        if worker is not None:
            notices.append((message, error, shiboken6.isValid(worker)))

    tab.status_message_requested.connect(status)
    rejection = ValueError("Synthetic Finish validation rejection")
    finish_preparation = (
        patch.object(RustMeshAuthoringSession, "_prepare_finish_mesh", side_effect=rejection)
        if event == "rejected_finish" else nullcontext()
    )
    try:
        with (
            patch.object(tab, "_send_rust_message", side_effect=lambda reply: replies.append(reply) or True),
            finish_preparation,
        ):
            tab._start_next_rust_protocol_worker()
            worker = tab.standalone_rust_protocol_worker
            deadline = time.monotonic() + 10
            while tab.standalone_rust_protocol_thread is not None and time.monotonic() < deadline:
                QApplication.instance().processEvents()
                time.sleep(0.001)
        assert tab.standalone_rust_protocol_thread is None
        assert len(replies) == 1 and len(notices) == 1
        assert notices[0][2] is False
        assert replies[0]["ok"] is (event != "rejected_finish")
        assert notices[0][1] is (event == "rejected_finish")
        assert ("rejected" if event == "rejected_finish" else "cancelled" if event == "cancel" else "accepted") in notices[0][0]
        assert notices[0][0] in tab.log_view.toPlainText()
        if event == "rejected_finish":
            assert not session.closed
            assert not tab.standalone_rust_finish_accepted
            assert session.finish(_request(session, "finish_request", 2))["status"] == "accepted"
    finally:
        thread = tab.standalone_rust_protocol_thread
        if thread is not None:
            tab.standalone_rust_protocol_worker.stop()
            thread.quit()
            assert thread.wait(2000)
            QApplication.instance().processEvents()
        tab.standalone_rust_process = None
        tab.standalone_rust_authoring_session = None
        tab.standalone_controller = None
        session.cancel()
        service.close_edit_session(session.authoritative_session_id, force_without_saving=True)
        _dispose(tab)


def test_mesh_editor_log_is_live_bounded_and_clearable_in_the_drawer(tmp_path):
    tab = _tab(tmp_path)
    owner = SimpleNamespace(shell=SimpleNamespace(_tool_widgets_by_key={"mesh_editor": tab}))
    adapter = tool_log_adapter_for(owner, "mesh_editor")
    drawer = CompactActivityDrawer(ActivityHistory(parent=tab), tab)
    try:
        assert adapter.document is tab.log_view.document()
        assert adapter.document.maximumBlockCount() == 2000
        drawer.set_tool_log(adapter)
        tab._set_rust_status("Validating and finishing the isolated Mesh Editor session...")
        tab._set_rust_status("Synthetic validation failure", error=True)
        tab.status_message_requested.emit("Output action completed", False)
        assert drawer.tool_log_stack.currentWidget() is drawer.tool_log_view
        assert drawer.tool_log_view.toPlainText() == adapter.text()
        assert adapter.text().count("Synthetic validation failure") == 1
        assert "Output action completed" in adapter.text()
        assert adapter.copy() == QApplication.instance().clipboard().text()
        adapter.clear()
        assert adapter.text() == ""
        assert drawer.tool_log_stack.currentWidget() is drawer.tool_log_empty_label
    finally:
        _dispose(tab)


@pytest.mark.parametrize("failed", [False, True])
def test_late_command_result_does_not_replace_terminal_status(tmp_path, failed):
    tab = _tab(tmp_path)
    tab.standalone_rust_protocol_request_id = 7
    tab.standalone_rust_active_event = {"event": "command_request", "command": "refit_load_mesh"}
    thread, process = object(), _BufferedProcess()
    tab.standalone_rust_protocol_thread = thread
    tab.standalone_rust_process = process
    notices = []
    tab.status_message_requested.connect(lambda message, error: notices.append((message, error)))
    try:
        tab._handle_rust_process_finished(process, 0, QProcess.ExitStatus.NormalExit)
        assert not notices
        with patch.object(tab, "_send_rust_message") as send:
            if failed:
                tab._handle_rust_protocol_worker_error(7, 1, "command_request", "Late failure", {})
            else:
                tab._handle_rust_protocol_completed(7, 1, {"payload": {"result": {}}}, False)
        tab._handle_rust_protocol_thread_finished(thread)
        assert len(notices) == 1 and notices[0][1] is True
        assert "closed (exit 0)" in tab.standalone_status_label.text()
        send.assert_not_called()
    finally:
        tab.standalone_rust_protocol_thread = None
        tab.standalone_rust_process = None
        _dispose(tab)


def test_opening_hair_setup_after_finish_does_not_read_disposed_shadow(tmp_path):
    from cdmw.ui.mesh_editor.hair_flow import start_hair_workflow

    tab = _tab(tmp_path)
    service, session = authoring_fixtures.RustMeshAuthoringTests()._create(tmp_path / "session")
    _attach_session(tab, service, session)
    session.finish(_request(session, "finish_request", 1))
    dialog = QDialog(tab)
    try:
        with (
            patch("cdmw.ui.mesh_editor.hair_setup_dialog.HairSetupDialog", return_value=dialog),
            patch.object(dialog, "open") as opened,
        ):
            assert start_hair_workflow(tab) is dialog
        opened.assert_called_once()
    finally:
        tab.standalone_rust_authoring_session = None
        tab.standalone_controller = None
        service.close_edit_session(session.authoritative_session_id, force_without_saving=True)
        _dispose(tab)
