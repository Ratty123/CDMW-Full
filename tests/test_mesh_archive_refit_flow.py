from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PySide6.QtCore import QEventLoop, QThread, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from cdmw.ui.mesh_editor.archive_refit_flow import prepare_archive_refit_event
from cdmw.ui.mesh_editor.replace_from_archive_dialog import ReplaceFromArchivePickerDialog
from cdmw.ui.mesh_editor.tab_rust_process import MeshEditorRustProcessMixin
from cdmw.ui.shell.tab_registry import DetachedToolWindow
from cdmw.workers.mesh_editor_aux_workers import MeshArchiveSessionLoadWorker
from tests.test_mesh_rust_authoring_exact_output import _open_exact_session, _request
from tests.test_mesh_rust_editor_selection import _tab, _dispose
from tests.test_replace_from_archive_dialog import _Catalogue, _entry, _context, _session


@pytest.mark.parametrize("role", ["body", "armor"])
@pytest.mark.parametrize("detached", [False, True])
def test_archive_refit_picker_uses_the_shell_archive_workspace(role, detached):
    app = QApplication.instance() or QApplication([])
    owner = QWidget()
    catalogue = _Catalogue()
    catalogue.current_session = _session()
    target, selected = _entry("body.pac", 1), _entry(f"chosen-{role}.pac", 2)
    owner.archive = SimpleNamespace(
        archive_catalogue_service=catalogue,
        archive_entries=(target,),
        archive_entries_by_normalized_path={target.path: (target,)},
        archive_entries_by_basename={target.basename: (target,)},
    )
    tool_window = (
        DetachedToolWindow(owner, "mesh_editor", "Mesh Editor") if detached else owner
    )
    tab = QWidget(tool_window)
    session = object()
    tab.standalone_rust_authoring_session = session
    tab.standalone_rust_closing = False
    tab._current_target_entry = lambda: target
    opened = []

    def choose(picker):
        opened.append(picker)
        assert picker._service is catalogue
        assert picker._session is catalogue.current_session
        assert picker.parent() is owner
        assert picker._refit_role == role
        picker.selected_entry = selected
        picker.selected_dependencies = _context(selected)
        picker.done(QDialog.Accepted)
        return QDialog.Accepted

    try:
        with patch.object(ReplaceFromArchivePickerDialog, "exec", choose):
            result = prepare_archive_refit_event(
                tab, session,
                {"command": "refit_choose_archive", "arguments": {"role": role}},
            )
        assert len(opened) == 1
        assert result["arguments"]["_archive_entry"] is selected
        assert result["arguments"]["_primary_entry"] is target
    finally:
        owner.deleteLater()
        app.processEvents()


def _wait_for_protocol_worker(tab):
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    thread = tab.standalone_rust_protocol_thread
    if thread is not None:
        thread.finished.connect(loop.quit)
        timer.start(5_000)
        loop.exec()
        timer.stop()
    QApplication.instance().processEvents()
    assert tab.standalone_rust_protocol_thread is None


@pytest.mark.parametrize("role", ["body", "armor"])
@pytest.mark.parametrize("reason", [
    "Archive selection cancelled; loaded meshes are unchanged",
    "Load the game archive catalogue before choosing a Refit mesh",
])
def test_archive_refit_picker_rejection_recovers_and_accepts_the_next_command(
    tmp_path, role, reason,
):
    app = QApplication.instance() or QApplication([])
    _source, authority, session = _open_exact_session(tmp_path / "session")
    tab = _tab(tmp_path)
    tab.standalone_rust_authoring_session = session
    tab.standalone_rust_process_generation = session.process_generation
    tab.standalone_rust_ready = True
    responses = []
    recovery_threads = []
    tab._send_rust_message = responses.append
    original_state_payload = session.state_payload

    def state_payload(current_session, **kwargs):
        assert current_session is session
        recovery_threads.append(QThread.currentThread() is app.thread())
        return original_state_payload(**kwargs)

    before = session.shadow_service.session_view(session.shadow_session_id)
    event = {
        **_request(session, "command_request", 1),
        "command": "refit_choose_archive", "arguments": {"role": role},
    }
    try:
        with (
            patch(
                "cdmw.ui.mesh_editor.archive_refit_flow.prepare_archive_refit_event",
                side_effect=ValueError(reason),
            ),
            patch.object(type(session), "state_payload", state_payload),
        ):
            tab._handle_rust_protocol_event(event)
            _wait_for_protocol_worker(tab)
        assert len(responses) == 1
        rejection = responses[0]
        assert rejection["event"] == "command_result"
        assert rejection["ok"] is False
        assert rejection["error"] == reason
        assert rejection["request_id"] == 1
        state = rejection["payload"]["state"]
        assert state["session_id"] == session.session_id
        assert state["base_revision"] == rejection["base_revision"] == before.revision
        assert (session.root / state["document"]["path"]).is_file()
        assert recovery_threads == [False]
        assert not session.closed
        assert not tab.standalone_rust_closing
        assert session.shadow_service.session_view(session.shadow_session_id) == before

        tab._handle_rust_protocol_event({
            **_request(session, "command_request", 2), "command": "state", "arguments": {},
        })
        _wait_for_protocol_worker(tab)
        assert len(responses) == 2
        assert responses[1]["request_id"] == 2
        assert responses[1]["ok"] is True
    finally:
        thread = tab.standalone_rust_protocol_thread
        if thread is not None:
            tab.standalone_rust_protocol_worker.stop()
            thread.quit()
            thread.wait(5_000)
            app.processEvents()
        tab.standalone_rust_authoring_session = None
        session.cancel()
        authority.close_edit_session("authoritative-rust-exact", force_without_saving=True)
        _dispose(tab)


@pytest.mark.parametrize("change", ["close", "session"])
def test_archive_refit_picker_does_not_recover_into_a_closed_or_replaced_session(tmp_path, change):
    app = QApplication.instance() or QApplication([])
    tab = _tab(tmp_path)
    session = object()
    tab.standalone_rust_authoring_session = session
    tab.standalone_rust_protocol_queue = [{
        "event": "command_request", "command": "refit_choose_archive",
        "request_id": 1, "arguments": {"role": "armor"},
    }]
    responses = []
    tab._send_rust_message = responses.append

    def close_during_picker(*_args):
        if change == "close":
            tab.standalone_rust_closing = True
        else:
            tab.standalone_rust_authoring_session = object()
        raise ValueError("The edit session closed while the archive picker was open")

    try:
        with patch(
            "cdmw.ui.mesh_editor.archive_refit_flow.prepare_archive_refit_event",
            side_effect=close_during_picker,
        ), patch("cdmw.workers.mesh_rust_editor_workers.MeshRustProtocolWorker") as worker:
            tab._start_next_rust_protocol_worker()
            app.processEvents()
        worker.assert_not_called()
        assert responses == []
        assert not tab._archive_refit_picker_active
        assert tab.standalone_rust_protocol_thread is None
    finally:
        tab.standalone_rust_authoring_session = None
        _dispose(tab)


def test_archive_refit_picker_uses_only_host_prepared_archive_objects():
    target, armor = _entry("body.pac", 1), _entry("armor.pac", 2)
    session = object()
    dependencies = _context(armor)
    calls = []

    def choose(entry, role):
        calls.append((entry, role))
        return armor, dependencies

    tab = SimpleNamespace(
        _archive_refit_picker=SimpleNamespace(choose=choose),
        _current_target_entry=lambda: target,
        standalone_rust_authoring_session=session, standalone_rust_closing=False,
    )
    event = {"command": "refit_choose_archive", "arguments": {
        "role": "armor", "path": "untrusted.obj", "_archive_entry": "untrusted",
    }}
    prepared = prepare_archive_refit_event(tab, session, event)
    assert calls == [(target, "armor")]
    assert prepared["arguments"]["_archive_entry"] is armor
    assert prepared["arguments"]["_archive_dependencies"] is dependencies
    assert "path" not in prepared["arguments"]


@pytest.mark.parametrize("change", ["session", "target", "close"])
def test_archive_refit_picker_rejects_stale_session_target_and_close(change):
    target, armor = _entry("body.pac", 1), _entry("armor.pac", 2)
    session = object()
    tab = SimpleNamespace(standalone_rust_authoring_session=session, standalone_rust_closing=False,
                          _current_target_entry=lambda: target)

    def choose(_entry, _role):
        if change == "session":
            tab.standalone_rust_authoring_session = object()
        elif change == "target":
            tab._current_target_entry = lambda: armor
        else:
            tab.standalone_rust_closing = True
        return armor, _context(armor)

    tab._archive_refit_picker = SimpleNamespace(choose=choose)
    with pytest.raises(ValueError, match="closed|changed"):
        prepare_archive_refit_event(tab, session, {"arguments": {"role": "armor"}})


def test_archive_picker_keeps_protocol_queue_single_flight():
    tab = SimpleNamespace(_archive_refit_picker_active=True)
    # No protocol worker or queue fields are touched while the modal picker runs.
    MeshEditorRustProcessMixin._start_next_rust_protocol_worker(tab)


def test_cancel_after_archive_session_open_disposes_unpublished_native_session():
    app = QApplication.instance() or QApplication([])
    worker = MeshArchiveSessionLoadWorker(3, _entry("body.pac", 1))
    closed, loaded, finished = [], [], []

    class Service:
        def load_mesh_bytes(self, *_args, **_kwargs):
            return SimpleNamespace()

        def open_edit_session(self, *_args, **_kwargs):
            worker.stop()
            return SimpleNamespace(session_id="cancelled-refit-load")

        def close_edit_session(self, session_id, *, force_without_saving):
            closed.append((session_id, force_without_saving))

    worker.loaded.connect(lambda *_args: loaded.append(True))
    worker.finished.connect(lambda: finished.append(True))
    with patch("cdmw.workers.mesh_editor_aux_workers.MeshService", Service), patch(
        "cdmw.workers.mesh_editor_aux_workers.read_archive_entry_data", return_value=(b"owned", False, ""),
    ):
        worker.run()
    assert not loaded
    assert closed == [("cancelled-refit-load", True)]
    assert finished == [True]
    app.processEvents()
