"""Authoritative settings, history and saved setup contracts for Fit to body."""
from dataclasses import replace
import json

import pytest

from cdmw.domain.mesh import MeshEditSelection
from cdmw.domain.mesh.morph import MeshMorphProfile, mesh_morph_driver_topology_fingerprint
from cdmw.services.mesh_service_morph_recipes import fitting_recipe_from_payload, fitting_recipe_payload
from tests.test_mesh_morph_authoring_native import resident
from tests.test_mesh_refit_tightening_native import _arm, _mesh, _sleeve
from tests.test_mesh_refit_saved_setups import _service, _saved_path


def test_fit_reads_authoritative_part_settings_and_publishes_one_undo(resident):
    service, open_session = resident
    mesh = _mesh(_arm(), _sleeve(), _sleeve(radius=.11))
    session = open_session(mesh)
    profile = MeshMorphProfile(profile_id="fit", name="Fit", topology_fingerprint=mesh_morph_driver_topology_fingerprint(mesh, ()))
    service._activate_morph_profile_locked(service._session(session), profile)
    assert service.set_refit_driver(session, (0,))[0].ok
    assert service.bind_refit(session, (1, 2))[0].ok
    assert service.configure_refit(session, (1,), enabled=True, intensity_percent=37.,
                                   mode="surface", clearance_percent=0.)[0].ok
    assert service.configure_refit(session, (2,), enabled=False, intensity_percent=64.,
                                   mode="rigid_component", clearance_percent=.2)[0].ok
    assert service.set_refit_vertex_influence(session, selection=MeshEditSelection.from_maps(
        vertices_by_submesh={1: (0,)}), weight=0.)[0].ok
    assert service.set_refit_driver_region(session, (1,), selection=MeshEditSelection.from_maps(
        faces_by_submesh={0: tuple(range(len(mesh.submeshes[0].faces)))}))[0].ok
    before = service.cached_morph_state(session).refit
    count = len(service._session(session).undo_stack)
    result, state = service.fit_refit_to_body(session)
    assert result.ok
    assert state.refit.garment_settings[0] == replace(before.garment_settings[0], tightness_percent=100., clearance_percent=.1)
    assert state.refit.garment_settings[1] == before.garment_settings[1]
    assert state.refit.garment_regions == before.garment_regions
    assert len(service._session(session).undo_stack) == count + 1
    fitted = service.working_mesh(session, clone=True).submeshes[1].vertices
    assert fitted != mesh.submeshes[1].vertices
    assert fitted[0] == mesh.submeshes[1].vertices[0]
    assert service.working_mesh(session, clone=True).submeshes[2].vertices == mesh.submeshes[2].vertices
    # A stale/older caller omits tightness without erasing the current native setting.
    assert service.configure_refit(session, (1,), enabled=True, intensity_percent=37.,
                                   mode="surface", clearance_percent=.1)[1].refit.garment_settings[0].tightness_percent == 100.
    assert service.reset_morph(session)[0].ok
    assert service.working_mesh(session, clone=True).submeshes[1].vertices == mesh.submeshes[1].vertices
    assert service.undo(session).ok
    for a, b in zip(service.working_mesh(session, clone=True).submeshes[1].vertices, fitted):
        assert a == pytest.approx(b)


def test_recipe_v2_roundtrip_and_legacy_read(tmp_path):
    service = _service(tmp_path)
    state = service.data.state
    service.data.state = replace(state, refit=replace(state.refit, garment_settings=tuple(
        replace(item, tightness_percent=68.) for item in state.refit.garment_settings)))
    _, state = service.save_refit_setup("mock", "Snug")
    _, path = _saved_path(service, state)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["format"] == "cdmw.mesh_refit_recipe.v2"
    recipe = fitting_recipe_from_payload(payload)
    assert all(item.tightness_percent == 68. for item in recipe.garment_settings)
    assert fitting_recipe_payload(recipe) == payload
    payload["format"] = "cdmw.mesh_refit_recipe.v1"
    for row in payload["garment_settings"]:
        row.pop("tightness_percent")
    assert all(item.tightness_percent == 0. for item in fitting_recipe_from_payload(payload).garment_settings)
    payload["format"] = "cdmw.mesh_refit_recipe.v2"
    with pytest.raises(ValueError, match="tightness"):
        fitting_recipe_from_payload(payload)


def test_draft_reopens_with_tightness_and_reset_neutral(resident, tmp_path):
    service, open_session = resident
    mesh = _mesh(_arm(), _sleeve())
    import hashlib
    mesh._cdmw_mesh_asset_source_hash = hashlib.sha256(repr(mesh.submeshes).encode()).hexdigest()
    session = open_session(mesh)
    profile = MeshMorphProfile(profile_id="fit", name="Fit", topology_fingerprint=mesh_morph_driver_topology_fingerprint(mesh, ()))
    service._activate_morph_profile_locked(service._session(session), profile)
    service.set_refit_driver(session, (0,))
    service.bind_refit(session, (1,))
    assert service.fit_refit_to_body(session)[0].ok
    fitted = service.working_mesh(session, clone=True).submeshes[1].vertices
    owner = service._session(session)
    project = tmp_path / "draft/mesh_layer_project.json"
    owner.mesh_layer_project_path = project
    service.retry_mesh_layer_autosave(session)
    assert json.loads(project.read_text())["format"] == "mesh_layer_project_v8"
    mesh._cdmw_mesh_layer_project_path = str(project)
    reopened = open_session(mesh)
    assert service.cached_morph_state(reopened).refit.garment_settings[0].tightness_percent == 100.
    for a, b in zip(service.working_mesh(reopened, clone=True).submeshes[1].vertices, fitted):
        assert a == pytest.approx(b)
    assert service.reset_morph(reopened)[0].ok
    for a, b in zip(service.working_mesh(reopened, clone=True).submeshes[1].vertices, mesh.submeshes[1].vertices):
        assert a == pytest.approx(b)


def test_invalid_morph_draft_never_publishes_geometry(resident, tmp_path):
    from copy import deepcopy
    import hashlib
    from cdmw.services.mesh_layer_project_service import load_mesh_layer_project
    service, open_session = resident
    mesh = _mesh(_arm(), _sleeve())
    mesh._cdmw_mesh_asset_source_hash = hashlib.sha256(repr(mesh.submeshes).encode()).hexdigest()
    session = open_session(mesh)
    profile = MeshMorphProfile(profile_id="fit", name="Fit", topology_fingerprint=mesh_morph_driver_topology_fingerprint(mesh, ()))
    owner = service._session(session)
    service._activate_morph_profile_locked(owner, profile)
    service.set_refit_driver(session, (0,))
    service.bind_refit(session, (1,))
    assert service.fit_refit_to_body(session)[0].ok
    project = tmp_path / "draft/mesh_layer_project.json"
    owner.mesh_layer_project_path = project
    service.retry_mesh_layer_autosave(session)
    descriptor = json.loads(project.read_text())
    generation = project.parent / descriptor["current_generation"] / "generation.json"
    payload = json.loads(generation.read_text())
    morph_file = project.parent / payload["morph"]["path"]
    morph_file.write_text("{}", encoding="utf-8")
    # A malformed Morph payload must not leave the successfully decoded fitted
    # geometry installed in the caller's original mesh.
    target = deepcopy(mesh)
    with pytest.raises(RuntimeError, match="No valid.*generation"):
        load_mesh_layer_project(target, project, expected_source_asset_sha256=mesh._cdmw_mesh_asset_source_hash)
    assert target.submeshes[1].vertices == mesh.submeshes[1].vertices


def test_failed_fit_through_background_protocol_keeps_preview_and_settings(resident, tmp_path):
    import threading
    from types import SimpleNamespace
    from PySide6.QtCore import Qt
    from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession, RUST_MESH_EDITOR_PROTOCOL
    from cdmw.workers.mesh_rust_editor_workers import MeshRustProtocolWorker

    service, open_session = resident
    far = _sleeve()
    far.vertices = [(x+3., y, z) for x, y, z in far.vertices]
    mesh = _mesh(_arm(), _sleeve(), far)
    session = open_session(mesh)
    profile = MeshMorphProfile(profile_id="fit", name="Fit", topology_fingerprint=mesh_morph_driver_topology_fingerprint(mesh, ()))
    service._activate_morph_profile_locked(service._session(session), profile)
    service.set_refit_driver(session, (0,))
    service.bind_refit(session, (1,2))
    editor = RustMeshAuthoringSession.create(SimpleNamespace(mesh_service=service, active_session_id=session),
                                           tmp_path / "rust-fit", process_generation=7)
    try:
        shadow, sid = editor.shadow_service, editor.shadow_session_id
        before = shadow.cached_morph_state_from_runtime(sid).refit
        vertices = shadow.working_mesh(sid, clone=True).submeshes[1].vertices
        revision = shadow.session_view(sid).revision
        count = len(shadow._session(sid).undo_stack)
        event = {"event": "command_request", "protocol": RUST_MESH_EDITOR_PROTOCOL,
                 "session_id": editor.session_id, "request_id": 1, "base_revision": revision,
                 "process_generation": 7, "command": "refit_fit_to_body", "arguments": {}}
        worker = MeshRustProtocolWorker(4, editor, event)
        errors, results = [], []
        worker.error.connect(lambda *args: errors.append(args), Qt.ConnectionType.DirectConnection)
        worker.completed.connect(lambda *args: results.append(args), Qt.ConnectionType.DirectConnection)
        thread = threading.Thread(target=worker.run)
        thread.start()
        thread.join(30.)
        assert not thread.is_alive()
        assert not results and len(errors) == 1
        assert "Part 2" in errors[0][3]
        assert shadow.cached_morph_state_from_runtime(sid).refit == before
        assert shadow.working_mesh(sid, clone=True).submeshes[1].vertices == vertices
        assert shadow.session_view(sid).revision == revision
        assert len(shadow._session(sid).undo_stack) == count
    finally:
        editor.cancel()
