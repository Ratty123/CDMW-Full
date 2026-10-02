from dataclasses import replace
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from cdmw.domain.archives.catalogue import ArchiveEntryRef, ArchivePage, ArchiveQueryHandle
from cdmw.domain.archives.catalogue_operations import PrepareEntryResult
from cdmw.ui.mesh_editor.cloth_collision_flow import prepare_cloth_collision_event
from cdmw.ui.replace_assistant.archive_picker import RemoteArchiveOriginalDialog
from cdmw.ui.shell.tab_registry import DetachedToolWindow
from tests.test_replace_assistant_archive_catalogue import _CatalogueService, _entry, _session
from tests.test_replace_from_archive_dialog import _entry as _target_entry
from tests.test_mesh_cloth_decoded_preview import collision_session
from tests.test_mesh_jiggle_decoded_preview import rig_session, decoded
from tests.test_mesh_jiggle import jiggle_session
from tests.test_mesh_weapon_collisions import weapon_fixture
from tests.test_mesh_rust_replacement import command
from tests.test_mesh_cloth_influence import shadow_output


def _input(root, role, data=b"prepared collision input"):
    extension = ".pac" if role == "weapon" else ".pabv"
    entry = replace(_entry(root, 21, f"character/{role}/reference{extension}"),
                    extension=extension, original_size=len(data))
    path = root / "prepared-input.bin"
    path.write_bytes(data)
    prepared = PrepareEntryResult(ArchiveEntryRef(entry.session_id, entry.entry_id, entry.identity, entry.path),
                                  str(path), len(data), hashlib.sha256(data).hexdigest())
    return entry, prepared


@pytest.mark.parametrize("role", ["body", "head", "weapon"])
def test_collision_picker_queries_one_filtered_page_and_prepares_only_the_selected_file(tmp_path, role):
    app = QApplication.instance() or QApplication([])
    session = _session(tmp_path)
    service = _CatalogueService(session)
    entry, prepared = _input(tmp_path, role)
    picker = RemoteArchiveOriginalDialog(service, session, initial_filter="reference",
        extensions=(entry.extension,), prepare_selection=True)
    try:
        picker._query_timer.stop()
        picker._start_query()
        query, generation = service.query_requests[-1]
        assert query.extensions == (entry.extension,)
        service.result_ready.emit("query-1", "create_query",
                                 ArchiveQueryHandle(session.session_id, "collision-query", generation, 900))
        assert service.page_requests[-1][0].page_size == 500
        service.result_ready.emit("page-1", "fetch_page",
            ArchivePage(session.session_id, "collision-query", generation, 900, 0, (entry,)))
        picker._accept_current()
        assert service.prepare_requests[-1][0].entry_id == entry.entry_id
        assert not picker.choose_button.isEnabled()
        assert not picker.results_list.isEnabled()
        assert picker.selected_prepared is None
        service.result_ready.emit("prepare-1", "prepare_entry", prepared)
        assert picker.result() == QDialog.Accepted
        assert picker.selected_entry is entry and picker.selected_prepared is prepared
    finally:
        picker.reject()
        picker.deleteLater()
        app.processEvents()


def test_collision_picker_close_cancels_preparation_and_ignores_late_completion(tmp_path):
    app = QApplication.instance() or QApplication([])
    session = _session(tmp_path)
    service = _CatalogueService(session)
    entry, prepared = _input(tmp_path, "weapon")
    picker = RemoteArchiveOriginalDialog(service, session, initial_filter="",
                                         extensions=(".pac",), prepare_selection=True)
    try:
        picker._query_timer.stop()
        from PySide6.QtWidgets import QListWidgetItem
        item = QListWidgetItem(entry.path)
        item.setData(Qt.UserRole, entry)
        picker.results_list.addItem(item)
        picker.results_list.setCurrentRow(0)
        picker._accept_current()
        picker.reject()
        assert "prepare-1" in service.cancelled
        service.result_ready.emit("prepare-1", "prepare_entry", prepared)
        assert picker.result() == QDialog.Rejected
        assert picker.selected_prepared is None
    finally:
        picker.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("detached", [False, True])
@pytest.mark.parametrize("outcome", ["accepted", "cancelled", "archive_changed", "edit_closed"])
def test_collision_flow_uses_shell_archives_and_rejects_stale_or_cancelled_selection(tmp_path, detached, outcome):
    app = QApplication.instance() or QApplication([])
    owner = QWidget()
    service = _CatalogueService(_session(tmp_path))
    service.current_session = service.active_session
    owner.archive = SimpleNamespace(archive_catalogue_service=service)
    window = DetachedToolWindow(owner, "mesh_editor", "Mesh Editor") if detached else owner
    tab = QWidget(window)
    session = object()
    tab.standalone_rust_authoring_session = session
    tab.standalone_rust_closing = False
    tab._current_target_entry = lambda: _target_entry("cloak.pac", 1)
    entry, prepared = _input(tmp_path, "weapon")

    def choose(picker):
        assert picker.parent() is owner
        assert picker._service is service and picker._extensions == (".pac",)
        picker.selected_entry, picker.selected_prepared = entry, prepared
        if outcome == "archive_changed":
            service.current_session = replace(service.current_session, session_id="new-session")
        if outcome == "edit_closed":
            tab.standalone_rust_closing = True
        return QDialog.Rejected if outcome == "cancelled" else QDialog.Accepted

    try:
        with patch.object(RemoteArchiveOriginalDialog, "exec", choose):
            event = {"command": "cloth_collision_input", "arguments": {"role": "weapon", "source": "archive"}}
            if outcome == "accepted":
                result = prepare_cloth_collision_event(tab, session, event)
                assert result["arguments"]["_archive_entry"] is entry
                assert result["arguments"]["_archive_prepared"] is prepared
            else:
                with pytest.raises(ValueError, match="cancelled|changed"):
                    prepare_cloth_collision_event(tab, session, event)
        assert tab._cloth_collision_picker is None
    finally:
        owner.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("role", ["body", "head", "weapon"])
def test_archive_collision_inputs_verify_prepared_bytes_and_leave_authored_output_unchanged(collision_session, tmp_path, role):
    from tests.test_pabv_parser import container, record
    original, session, host = collision_session
    data = weapon_fixture() if role == "weapon" else container(record(
        key=session.skeleton.bones[0 if role == "body" else 1].name_hash, parameters=(.5, 2.)))
    entry, prepared = _input(tmp_path, role, data)
    before = shadow_output(host)
    history = (len(session.undo_stack), len(session.redo_stack))
    result = command(host, "cloth_collision_input", {"role": role, "_archive_entry": entry, "_archive_prepared": prepared})
    assert result["result"]["changed"]
    assert result["state"]["jiggle"]["collision_inputs"] == {role: entry.path}
    assert result["state"]["jiggle"]["decoded"]["cloth"]["weapon_collider_count" if role == "weapon" else "body_collider_count"] > 0
    assert shadow_output(host) == before
    assert session.original_data == original
    assert (len(session.undo_stack), len(session.redo_stack)) == history


@pytest.mark.parametrize("failure", ["hash", "size", "identity", "role", "untrusted"])
def test_invalid_prepared_archive_collision_preserves_last_good_input(collision_session, tmp_path, failure):
    _, session, host = collision_session
    entry, prepared = _input(tmp_path, "weapon", weapon_fixture())
    args = {"role": "weapon", "_archive_entry": entry, "_archive_prepared": prepared}
    command(host, "cloth_collision_input", args)
    before = decoded(host)
    inputs, revision = dict(host.cloth_collision_inputs), session.revision
    if failure == "hash":
        args["_archive_prepared"] = replace(prepared, sha256="0" * 64)
    elif failure == "size":
        args["_archive_prepared"] = replace(prepared, size=prepared.size + 1)
    elif failure == "identity":
        args["_archive_prepared"] = replace(prepared, entry=replace(prepared.entry, entry_id=22))
    elif failure == "role":
        args["role"] = "body"
    else:
        args["_archive_prepared"] = {"prepared_path": str(Path(prepared.prepared_path))}
    with pytest.raises(ValueError, match="archive|changed"):
        command(host, "cloth_collision_input", args)
    assert decoded(host) == before
    assert host.cloth_collision_inputs == inputs and session.revision == revision


def test_archive_collision_picker_cancel_uses_protocol_worker_and_recovers_queue(tmp_path):
    from PySide6.QtCore import QThread
    from tests.test_mesh_archive_refit_flow import _wait_for_protocol_worker
    from tests.test_mesh_rust_authoring_exact_output import _open_exact_session, _request
    from tests.test_mesh_rust_editor_selection import _tab, _dispose
    app = QApplication.instance() or QApplication([])
    _, authority, session = _open_exact_session(tmp_path / "session")
    tab = _tab(tmp_path)
    tab.standalone_rust_authoring_session = session
    tab.standalone_rust_process_generation = session.process_generation
    tab.standalone_rust_ready = True
    responses, worker_threads = [], []
    tab._send_rust_message = responses.append
    original = session.state_payload
    before = session.shadow_service.session_view(session.shadow_session_id)

    def state_payload(current, **kwargs):
        worker_threads.append(QThread.currentThread() is app.thread())
        return original(**kwargs)

    try:
        with patch("cdmw.ui.mesh_editor.cloth_collision_flow.prepare_cloth_collision_event",
                   side_effect=ValueError("Collision input selection cancelled; preview inputs are unchanged.")), \
                patch.object(type(session), "state_payload", state_payload):
            tab._handle_rust_protocol_event({**_request(session, "command_request", 1),
                "command": "cloth_collision_input", "arguments": {"role": "weapon", "source": "archive"}})
            _wait_for_protocol_worker(tab)
        assert len(responses) == 1 and not responses[0]["ok"]
        assert "cancelled" in responses[0]["error"]
        assert worker_threads == [False]
        assert not tab._archive_refit_picker_active
        assert session.shadow_service.session_view(session.shadow_session_id) == before
        tab._handle_rust_protocol_event({**_request(session, "command_request", 2), "command": "state", "arguments": {}})
        _wait_for_protocol_worker(tab)
        assert responses[1]["ok"]
    finally:
        tab.standalone_rust_authoring_session = None
        session.cancel()
        authority.close_edit_session("authoritative-rust-exact", force_without_saving=True)
        _dispose(tab)
