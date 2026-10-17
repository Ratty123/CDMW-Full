"""Current-fit diagnostics use the native query and existing background transport."""
from dataclasses import replace
import threading
from types import SimpleNamespace

import pytest

from cdmw.domain.mesh.morph import MeshMorphProfile, mesh_morph_driver_topology_fingerprint
from tests.test_mesh_morph_authoring_native import resident
from tests.test_mesh_refit_tightening_native import _arm, _mesh, _sleeve


def _bound_service(resident):
    service, open_session = resident
    mesh = _mesh(_arm(), _sleeve(), _sleeve(radius=.11))
    session = open_session(mesh)
    profile = MeshMorphProfile(
        profile_id="fit", name="Fit",
        topology_fingerprint=mesh_morph_driver_topology_fingerprint(mesh, ()),
    )
    service._activate_morph_profile_locked(service._session(session), profile)
    assert service.set_refit_driver(session, (0,))[0].ok
    assert service.bind_refit(session, (1, 2))[0].ok
    assert service.configure_refit(
        session, (1,), enabled=True, intensity_percent=37.,
        mode="surface", clearance_percent=0.,
    )[0].ok
    assert service.configure_refit(
        session, (2,), enabled=False, intensity_percent=64.,
        mode="rigid_component", clearance_percent=.2,
    )[0].ok
    return service, session


def _positions(service, session):
    return [part.vertices for part in service.working_mesh(session, clone=True).submeshes]


def _history_identity(owner):
    return (
        owner.revision,
        owner.morph_session_revision,
        tuple(id(item) for item in owner.undo_stack),
        tuple(id(item) for item in owner.redo_stack),
    )


def test_service_diagnostics_use_authoritative_geometry_and_leave_stale_cache_untouched(resident, monkeypatch):
    service, session = _bound_service(resident)
    owner = service._session(session)
    data = service._morph_sessions[session]
    state = service.cached_morph_state(session)
    # The UI cache is deliberately stale. The diagnostic must read the resident
    # settings and geometry, without installing this cache or rewriting it.
    stale = replace(state, refit=replace(
        state.refit,
        garment_settings=tuple(replace(row, enabled=True, mode="surface")
                               for row in state.refit.garment_settings),
    ))
    before_positions = _positions(service, session)
    before_history = _history_identity(owner)
    data.state = stale

    def mutation_path(*args, **kwargs):
        pytest.fail("A read-only diagnostic entered the morph mutation path")

    with monkeypatch.context() as patch:
        patch.setattr(type(service), "_run_morph_command_locked", mutation_path)
        patch.setattr(type(service), "_require_no_pending_morph_authoring", mutation_path)
        report = service.refit_diagnostics(session, (2,), sample_limit=64, detail_limit=2)
    assert report["shadow_revision"] == before_history[0]
    assert report["requested_submesh_indices"] == [2]
    assert report["body_clearance"]["evaluated_sample_count"] == 64
    assert report["parts"][0]["enabled"] is False
    assert report["parts"][0]["mode"] == "rigid_component"
    assert report["parts"][0]["minimum_distance"] > .04
    assert data.state is stale
    assert _history_identity(owner) == before_history
    assert _positions(service, session) == before_positions


@pytest.mark.parametrize("indices,limits", (
    ((), {}),
    ((1, 1), {}),
    ((True,), {}),
    ((1,), {"sample_limit": 0}),
    ((1,), {"sample_limit": 4097}),
    ((1,), {"detail_limit": 65}),
))
def test_service_diagnostic_limits_fail_without_changes(resident, indices, limits):
    service, session = _bound_service(resident)
    owner = service._session(session)
    history = _history_identity(owner)
    positions = _positions(service, session)
    state = service.cached_morph_state(session)
    with pytest.raises(ValueError, match="Refit diagnostics"):
        service.refit_diagnostics(session, indices, **limits)
    assert _history_identity(owner) == history
    assert service.cached_morph_state(session) == state
    assert _positions(service, session) == positions


def test_diagnostics_use_background_protocol_without_mutation_preflight_or_document_reload(
    resident, tmp_path, monkeypatch,
):
    from PySide6.QtCore import Qt
    from cdmw.services.mesh_rust_authoring import (
        RUST_MESH_EDITOR_PROTOCOL, RustMeshAuthoringSession, RustMeshProtocolError,
    )
    from cdmw.workers.mesh_rust_editor_workers import MeshRustProtocolWorker

    service, session = _bound_service(resident)
    editor = RustMeshAuthoringSession.create(
        SimpleNamespace(mesh_service=service, active_session_id=session),
        tmp_path / "rust-diagnostics", process_generation=13,
    )
    try:
        shadow, sid = editor.shadow_service, editor.shadow_session_id
        owner = shadow._session(sid)
        before_history = _history_identity(owner)
        before_positions = _positions(shadow, sid)
        with owner.export_lock:
            native_state = shadow._run_morph_query_locked(owner, "morph_state")
        native_revision = native_state.get("morph_state", native_state)["state_revision"]
        event = {
            "event": "command_request", "protocol": RUST_MESH_EDITOR_PROTOCOL,
            "session_id": editor.session_id, "request_id": 1,
            "base_revision": before_history[0], "process_generation": 13,
            "command": "refit_diagnostics",
            "arguments": {"submesh_indices": [2, 1], "sample_limit": 64, "detail_limit": 2},
        }
        query_threads = []
        native_query = type(shadow).refit_diagnostics

        def measured_query(self, *args, **kwargs):
            query_threads.append(threading.get_ident())
            return native_query(self, *args, **kwargs)

        def forbidden_path(*args, **kwargs):
            pytest.fail("A diagnostic entered a mutation guard, preflight, or publication path")

        with monkeypatch.context() as patch:
            patch.setattr(type(shadow), "refit_diagnostics", measured_query)
            for method in (
                "_ensure_morph_authoring_resolved", "_ensure_correction_comparison_resolved",
                "_require_authoring_enabled", "_preflight_current_command_document",
                "_advance_shadow_protocol_revision", "_write_mesh_document",
            ):
                patch.setattr(RustMeshAuthoringSession, method, forbidden_path)
            worker = MeshRustProtocolWorker(4, editor, event)
            errors, results = [], []
            worker.error.connect(lambda *args: errors.append(args), Qt.ConnectionType.DirectConnection)
            worker.completed.connect(lambda *args: results.append(args), Qt.ConnectionType.DirectConnection)
            thread = threading.Thread(target=worker.run)
            thread.start()
            try:
                thread.join(15.)
            finally:
                if thread.is_alive():
                    worker.stop()
                    thread.join(15.)
            assert not thread.is_alive()
            assert not errors, errors
            assert len(results) == 1
            response = results[0][2]
            assert response["event"] == "command_result"
            assert response["ok"] is True
            assert response["base_revision"] == before_history[0]
            payload = response["payload"]
            assert payload["result"]["status"] == "ok"
            diagnostics = payload["result"]["refit_diagnostics"]
            assert diagnostics["requested_submesh_indices"] == [1, 2]
            assert diagnostics["shadow_revision"] == before_history[0]
            assert diagnostics["state_revision"] == native_revision
            assert diagnostics["host_morph_revision"] == payload["state"]["morph_refit"]["state_revision"]
            assert "document" not in payload["state"]
            assert payload["state"]["base_revision"] == before_history[0]
            assert query_threads and all(value != threading.get_ident() for value in query_threads)
            # The read-only branch still obeys normal message/revision identity.
            with pytest.raises(RustMeshProtocolError, match="stale"):
                editor.run_command({**event, "request_id": 2, "base_revision": before_history[0] + 1})
        assert _history_identity(owner) == before_history
        assert _positions(shadow, sid) == before_positions
    finally:
        editor.cancel()


def test_failed_diagnostics_return_lightweight_worker_recovery(resident, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt
    from cdmw.services.mesh_rust_authoring import RUST_MESH_EDITOR_PROTOCOL, RustMeshAuthoringSession
    from cdmw.workers.mesh_rust_editor_workers import MeshRustProtocolWorker

    service, session = _bound_service(resident)
    editor = RustMeshAuthoringSession.create(
        SimpleNamespace(mesh_service=service, active_session_id=session),
        tmp_path / "rust-diagnostics-error", process_generation=13,
    )
    try:
        shadow, sid = editor.shadow_service, editor.shadow_session_id
        owner = shadow._session(sid)
        before_history = _history_identity(owner)
        before_positions = _positions(shadow, sid)
        event = {
            "event": "command_request", "protocol": RUST_MESH_EDITOR_PROTOCOL,
            "session_id": editor.session_id, "request_id": 1,
            "base_revision": before_history[0], "process_generation": 13,
            "command": "refit_diagnostics",
            "arguments": {"submesh_indices": [1], "sample_limit": 0},
        }
        document_requests = []
        original_state_payload = RustMeshAuthoringSession.state_payload

        def lightweight_state(self, *, include_document=True):
            document_requests.append(include_document)
            assert include_document is False
            return original_state_payload(self, include_document=include_document)

        def forbidden_document(*args, **kwargs):
            pytest.fail("A rejected diagnostic rebuilt the mesh document")

        with monkeypatch.context() as patch:
            patch.setattr(RustMeshAuthoringSession, "state_payload", lightweight_state)
            patch.setattr(RustMeshAuthoringSession, "_write_mesh_document", forbidden_document)
            worker = MeshRustProtocolWorker(5, editor, event)
            errors, results = [], []
            worker.error.connect(lambda *args: errors.append(args), Qt.ConnectionType.DirectConnection)
            worker.completed.connect(lambda *args: results.append(args), Qt.ConnectionType.DirectConnection)
            thread = threading.Thread(target=worker.run)
            thread.start()
            try:
                thread.join(15.)
            finally:
                if thread.is_alive():
                    worker.stop()
                    thread.join(15.)
            assert not thread.is_alive()
            assert not results
            assert len(errors) == 1, errors
            assert "Refit diagnostics" in errors[0][3]
            recovery = errors[0][4]
            assert recovery["state"]["base_revision"] == before_history[0]
            assert "document" not in recovery["state"]
            assert document_requests == [False]
        assert _history_identity(owner) == before_history
        assert _positions(shadow, sid) == before_positions
    finally:
        editor.cancel()
