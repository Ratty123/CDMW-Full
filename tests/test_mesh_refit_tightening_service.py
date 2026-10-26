"""Authoritative settings, history and saved setup contracts for Fit to body."""
from dataclasses import replace
import json

import pytest

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.domain.mesh.morph import MeshMorphProfile, mesh_morph_driver_topology_fingerprint
from cdmw.services.mesh_service_morph_recipes import fitting_recipe_from_payload, fitting_recipe_payload
from tests.test_mesh_morph_authoring_native import resident
from tests.test_mesh_refit_tightening_native import _arm, _mesh, _sleeve
from tests.test_mesh_refit_saved_setups import _service, _saved_path


@pytest.mark.parametrize("targets", [(1,), (1, 2)])
@pytest.mark.parametrize("route", ["service", "rust", "command"])
def test_partial_refit_clearance_preserves_resident_part_settings_and_one_undo(resident, targets, route):
    from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession

    service, open_session = resident
    mesh = _mesh(_arm(), _sleeve(), _sleeve(radius=.11))
    session = open_session(mesh)
    owner = service._session(session)
    profile = MeshMorphProfile(profile_id="fit", name="Fit", topology_fingerprint=mesh_morph_driver_topology_fingerprint(mesh, ()))
    service._activate_morph_profile_locked(owner, profile)
    assert service.set_refit_driver(session, (0,))[0].ok
    assert service.bind_refit(session, (1, 2))[0].ok
    stale = service.cached_morph_state(session)
    assert service.set_refit_vertex_influence(session, selection=MeshEditSelection.from_maps(
        vertices_by_submesh={1: (0,)}), weight=0.)[0].ok
    assert service.set_refit_driver_region(session, (1,), selection=MeshEditSelection.from_maps(
        faces_by_submesh={0: tuple(range(len(mesh.submeshes[0].faces)))}))[0].ok
    assert service.configure_refit(session, (1,), enabled=True, intensity_percent=37.,
                                   mode="surface", clearance_percent=0., tightness_percent=25.)[0].ok
    assert service.configure_refit(session, (2,), enabled=False, intensity_percent=64.,
                                   mode="rigid_component", clearance_percent=.2, tightness_percent=63.)[0].ok
    before = service.cached_morph_state_from_runtime(session).refit
    vertices = [list(part.vertices) for part in service.working_mesh(session, clone=True).submeshes]
    count = len(owner.undo_stack)
    # An old Python/UI snapshot must never restore defaults over newer native settings.
    service._required_morph_data(owner).state = stale
    if route == "rust":
        editor = object.__new__(RustMeshAuthoringSession)
        editor.shadow_service = service
        editor.shadow_session_id = session
        result, state = editor._run_morph_command("refit_configure", {
            "submesh_indices": targets, "clearance_percent": .3,
        })
    elif route == "command":
        with owner.export_lock:
            result = service._apply_morph_edit_command_locked(owner, MeshEditCommand(
                action="morph_configure_refit",
                params={"garment_submesh_indices": targets, "clearance_percent": .3},
            ))
        state = service.cached_morph_state_from_runtime(session)
    else:
        result, state = service.configure_refit(session, targets, clearance_percent=.3)
    assert result.ok
    assert state.refit.garment_settings == tuple(
        replace(item, clearance_percent=.3) if item.submesh_index in targets else item
        for item in before.garment_settings
    )
    assert state.refit.garment_regions == before.garment_regions
    assert len(owner.undo_stack) == count + 1
    current = service.working_mesh(session, clone=True)
    assert current.submeshes[0].vertices == vertices[0]
    assert current.submeshes[1].vertices[0] == vertices[1][0]
    assert current.submeshes[2].vertices == vertices[2]
    assert service.undo(session).ok
    assert service.cached_morph_state_from_runtime(session).refit == before
    for actual, expected in zip(service.working_mesh(session, clone=True).submeshes, vertices):
        for point, old in zip(actual.vertices, expected):
            assert point == pytest.approx(old)


def test_partial_refit_failure_keeps_all_part_settings_geometry_and_history(resident):
    service, open_session = resident
    far = _sleeve()
    far.vertices = [(x + 3., y, z) for x, y, z in far.vertices]
    mesh = _mesh(_arm(), _sleeve(), far)
    session = open_session(mesh)
    owner = service._session(session)
    profile = MeshMorphProfile(profile_id="fit", name="Fit", topology_fingerprint=mesh_morph_driver_topology_fingerprint(mesh, ()))
    service._activate_morph_profile_locked(owner, profile)
    assert service.set_refit_driver(session, (0,))[0].ok
    assert service.bind_refit(session, (1, 2))[0].ok
    before = service.cached_morph_state_from_runtime(session).refit
    vertices = [list(part.vertices) for part in service.working_mesh(session, clone=True).submeshes]
    revision, count = service.session_view(session).revision, len(owner.undo_stack)
    with pytest.raises(RuntimeError, match="Part 2"):
        service.configure_refit(session, (1, 2), tightness_percent=100., clearance_percent=.1)
    assert service.cached_morph_state_from_runtime(session).refit == before
    assert [part.vertices for part in service.working_mesh(session, clone=True).submeshes] == vertices
    assert service.session_view(session).revision == revision
    assert len(owner.undo_stack) == count


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
    assert service.configure_refit(session, (1,), tightness_percent=25.)[0].ok
    before = service.cached_morph_state(session).refit
    count = len(service._session(session).undo_stack)
    result, state = service.fit_refit_to_body(session)
    assert result.ok
    assert state.refit.garment_settings[0] == replace(before.garment_settings[0], clearance_percent=.1)
    assert state.refit.garment_settings[1] == before.garment_settings[1]
    assert state.refit.garment_regions == before.garment_regions
    assert len(service._session(session).undo_stack) == count + 1
    fitted = service.working_mesh(session, clone=True).submeshes[1].vertices
    assert fitted != mesh.submeshes[1].vertices
    assert fitted[0] == mesh.submeshes[1].vertices[0]
    assert service.working_mesh(session, clone=True).submeshes[2].vertices == mesh.submeshes[2].vertices
    # A stale/older caller omits tightness without erasing the current native setting.
    assert service.configure_refit(session, (1,), enabled=True, intensity_percent=37.,
                                   mode="surface", clearance_percent=.1)[1].refit.garment_settings[0].tightness_percent == 25.
    assert service.reset_morph(session)[0].ok
    assert service.working_mesh(session, clone=True).submeshes[1].vertices == mesh.submeshes[1].vertices
    assert service.undo(session).ok
    for a, b in zip(service.working_mesh(session, clone=True).submeshes[1].vertices, fitted):
        assert a == pytest.approx(b)


def test_fit_default_tightens_a_new_binding_and_retains_a_deliberate_zero(resident):
    service, open_session = resident
    mesh = _mesh(_arm(), _sleeve(radius=.13))
    session = open_session(mesh)
    profile = MeshMorphProfile(profile_id="fit", name="Fit",
        topology_fingerprint=mesh_morph_driver_topology_fingerprint(mesh, ()))
    service._activate_morph_profile_locked(service._session(session), profile)
    service.set_refit_driver(session, (0,))
    service.bind_refit(session, (1,))
    before = service.cached_morph_state_from_runtime(session).refit
    assert before.garment_settings[0].tightness_percent == 0.
    assert before.garment_settings[0].tightness_initialized is False
    assert service.working_mesh(session, clone=True).submeshes[1].vertices == mesh.submeshes[1].vertices
    result, state = service.fit_refit_to_body(session)
    assert result.ok
    assert state.refit.garment_settings[0] == replace(before.garment_settings[0], clearance_percent=.1,
        tightness_percent=100., tightness_initialized=True)
    current = service.working_mesh(session, clone=True)
    assert current.submeshes[0].vertices == mesh.submeshes[0].vertices
    assert max((x*x + z*z)**.5 for x, _, z in current.submeshes[1].vertices) < .08
    service.reset_morph(session)
    reset = service.cached_morph_state_from_runtime(session).refit.garment_settings[0]
    assert reset.tightness_percent == 0. and not reset.tightness_initialized
    assert service.working_mesh(session, clone=True).submeshes[1].vertices == mesh.submeshes[1].vertices
    service.fit_refit_to_body(session)
    assert service.cached_morph_state_from_runtime(session).refit.garment_settings[0].tightness_percent == 100.
    service.configure_refit(session, (1,), tightness_percent=0.)
    service.bind_refit(session, (1,))
    assert service.cached_morph_state_from_runtime(session).refit.garment_settings[0].tightness_percent == 0.
    service.fit_refit_to_body(session)
    current = service.working_mesh(session, clone=True)
    for actual, original in zip(current.submeshes[1].vertices, mesh.submeshes[1].vertices):
        assert actual == pytest.approx(original, abs=1e-8)
    service.bake_morph(session)
    service.fit_refit_to_body(session)
    baked = service.cached_morph_state_from_runtime(session).refit.garment_settings[0]
    assert baked.tightness_percent == 0. and baked.tightness_initialized
    for actual, original in zip(service.working_mesh(session, clone=True).submeshes[1].vertices, mesh.submeshes[1].vertices):
        assert actual == pytest.approx(original, abs=1e-8)


def test_unconfigured_tightness_survives_draft_recipe_and_undo_with_island_choices(resident, tmp_path):
    import hashlib
    from cdmw.domain.mesh.morph import MeshMorphDefinition, MeshMorphRule, MeshMorphVertexWeight

    service, open_session = resident
    mesh = _mesh(_arm(), _sleeve(radius=.13))
    mesh._cdmw_mesh_asset_source_hash = hashlib.sha256(repr(mesh.submeshes).encode()).hexdigest()
    session = open_session(mesh)
    definitions = (MeshMorphDefinition(definition_id="shape", label="Shape", category="Test",
        vertices=(MeshMorphVertexWeight(0, 0, 1.),), pivot=(0., 0., 0.),
        local_basis=((1., 0., 0.), (0., 1., 0.), (0., 0., 1.)), rule=MeshMorphRule("move", "z")),)
    profile = MeshMorphProfile(profile_id="fit", name="Fit", definitions=definitions,
        topology_fingerprint=mesh_morph_driver_topology_fingerprint(mesh, definitions))
    service._activate_morph_profile_locked(service._session(session), profile)
    service.set_refit_driver(session, (0,))
    service.bind_refit(session, (1,))
    island = {"submesh_index": 1, "face_indices": tuple(range(len(mesh.submeshes[1].faces)))}
    service.configure_refit_islands(session, (island,), mode="surface")
    pending = service.cached_morph_state_from_runtime(session).refit.garment_settings[0]
    assert not pending.tightness_initialized
    assert not pending.island_settings[0].tightness_initialized
    assert service.working_mesh(session, clone=True).submeshes[1].vertices == mesh.submeshes[1].vertices
    _, saved = service.save_refit_setup(session, "Before first fit")
    identifier, _name = saved.matching_recipes[-1]
    path = service._profile_root() / "fitting_setups" / f"{identifier}.json"
    payload = json.loads(path.read_text())
    assert fitting_recipe_from_payload(payload).garment_settings[0] == pending
    payload["garment_settings"][0].pop("tightness_initialized")
    payload["garment_settings"][0]["island_settings"][0].pop("tightness_initialized")
    legacy = fitting_recipe_from_payload(payload).garment_settings[0]
    assert legacy.tightness_initialized and legacy.island_settings[0].tightness_initialized

    project = tmp_path / "pending/mesh_layer_project.json"
    service._session(session).mesh_layer_project_path = project
    service.retry_mesh_layer_autosave(session)
    mesh._cdmw_mesh_layer_project_path = str(project)
    reopened = open_session(mesh)
    assert service.cached_morph_state_from_runtime(reopened).refit.garment_settings[0] == pending
    service.fit_refit_to_body(reopened)
    fitted = service.cached_morph_state_from_runtime(reopened).refit.garment_settings[0]
    assert fitted.tightness_percent == fitted.island_settings[0].tightness_percent == 100.
    assert fitted.tightness_initialized and fitted.island_settings[0].tightness_initialized
    assert max((x*x + z*z)**.5 for x, _, z in service.working_mesh(reopened, clone=True).submeshes[1].vertices) < .08
    assert service.undo(reopened).ok
    assert service.cached_morph_state_from_runtime(reopened).refit.garment_settings[0] == pending
    service.configure_refit_islands(reopened, (island,), tightness_percent=0.)
    service.fit_refit_to_body(reopened)
    result = service.cached_morph_state_from_runtime(reopened).refit.garment_settings[0]
    assert result.tightness_percent == 100. and result.island_settings[0].tightness_percent == 0.
    for actual, original in zip(service.working_mesh(reopened, clone=True).submeshes[1].vertices, mesh.submeshes[1].vertices):
        assert actual == pytest.approx(original, abs=1e-8)


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
    service.configure_refit(session, (1,), tightness_percent=35.)
    assert service.fit_refit_to_body(session)[0].ok
    fitted = service.working_mesh(session, clone=True).submeshes[1].vertices
    owner = service._session(session)
    project = tmp_path / "draft/mesh_layer_project.json"
    owner.mesh_layer_project_path = project
    service.retry_mesh_layer_autosave(session)
    assert json.loads(project.read_text())["format"] == "mesh_layer_project_v8"
    mesh._cdmw_mesh_layer_project_path = str(project)
    reopened = open_session(mesh)
    assert service.cached_morph_state(reopened).refit.garment_settings[0].tightness_percent == 35.
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
    mesh = _mesh(_arm(), _sleeve(radius=.04), _sleeve())
    session = open_session(mesh)
    profile = MeshMorphProfile(profile_id="fit", name="Fit", topology_fingerprint=mesh_morph_driver_topology_fingerprint(mesh, ()))
    service._activate_morph_profile_locked(service._session(session), profile)
    service.set_refit_driver(session, (0,))
    service.bind_refit(session, (1,2))
    assert service.set_refit_vertex_influence(session, selection=MeshEditSelection.from_maps(
        vertices_by_submesh={1: tuple(range(len(mesh.submeshes[1].vertices)))}), weight=0.)[0].ok
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
        assert "Part 1" in errors[0][3]
        assert shadow.cached_morph_state_from_runtime(sid).refit == before
        assert shadow.working_mesh(sid, clone=True).submeshes[1].vertices == vertices
        assert shadow.session_view(sid).revision == revision
        assert len(shadow._session(sid).undo_stack) == count
    finally:
        editor.cancel()


def test_pull_to_skin_is_a_part_setting_kept_beside_the_others(resident):
    from cdmw.domain.mesh.morph import MeshRefitGarmentSettings

    service, open_session = resident
    mesh = _mesh(_arm(), _sleeve(), _sleeve(radius=.11))
    session = open_session(mesh)
    owner = service._session(session)
    profile = MeshMorphProfile(profile_id="fit", name="Fit", topology_fingerprint=mesh_morph_driver_topology_fingerprint(mesh, ()))
    service._activate_morph_profile_locked(owner, profile)
    assert service.set_refit_driver(session, (0,))[0].ok
    assert service.bind_refit(session, (1, 2))[0].ok
    assert service.configure_refit(session, (1,), tightness_percent=25.)[0].ok
    assert service.configure_refit(session, (1,), skin_pull_percent=55.)[0].ok
    rows = {item.submesh_index: item for item in service.cached_morph_state_from_runtime(session).refit.garment_settings}
    assert rows[1].skin_pull_percent == 55. and rows[1].tightness_percent == 25.
    assert rows[2].skin_pull_percent == 0.
    with pytest.raises(ValueError, match="Pull to skin"):
        MeshRefitGarmentSettings(1, skin_pull_percent=101.)


def test_recipe_keeps_pull_to_skin_and_older_setups_read_as_zero(tmp_path):
    service = _service(tmp_path)
    state = service.data.state
    service.data.state = replace(state, refit=replace(state.refit, garment_settings=tuple(
        replace(item, skin_pull_percent=30.) for item in state.refit.garment_settings)))
    _, state = service.save_refit_setup("mock", "Pulled")
    _, path = _saved_path(service, state)
    payload = json.loads(path.read_text(encoding="utf-8"))
    recipe = fitting_recipe_from_payload(payload)
    assert all(item.skin_pull_percent == 30. for item in recipe.garment_settings)
    assert fitting_recipe_payload(recipe) == payload
    for row in payload["garment_settings"]:
        row.pop("skin_pull_percent")
    assert all(item.skin_pull_percent == 0. for item in fitting_recipe_from_payload(payload).garment_settings)
