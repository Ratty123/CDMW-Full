"""Whole-island fitting uses the resident fitter without changing PAC topology."""
from copy import deepcopy
import json

import numpy as np
import pytest

from cdmw.domain.mesh import MeshRefitIslandSettings
from cdmw.domain.mesh.morph import MeshMorphDefinition, MeshMorphProfile, MeshMorphRule, MeshMorphVertexWeight, mesh_morph_driver_topology_fingerprint
from cdmw.services.mesh_morph_draft import (
    capture_morph_draft, load_morph_draft, persist_morph_draft, restore_morph_draft,
)
from cdmw.services.mesh_service_morph_recipes import read_fitting_recipe
from tests.test_mesh_morph_authoring_native import resident
from tests.test_mesh_refit_tightening_native import _bound, _mesh
from tests.test_native_mesh_editor_morph_refit import _command, _part, _snapshot, _state, mesh_native_core


def _islands_mesh():
    body = _part("body", [(-.5, 0., 0.), (.5, 0., 0.), (.5, .5, 0.), (-.5, .5, 0.)],
                 [(0, 1, 2), (0, 2, 3)], material="skin", texture="")
    vertices = [(x, y, .1) for start in (-.2, .1) for x, y in
                ((start, .1), (start+.1, .1), (start+.1, .3), (start, .3))]
    garment = _part("two islands", vertices, [(0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7)],
                    material="cloth", texture="cloth.dds")
    return _mesh(body, garment)


def _configure(session, overrides, **parent):
    return _command(session, "morph_configure_refit", {
        "garment_submesh_indices": [1], "garment_settings": [{
            "submesh_index": 1, "mode": "surface", "clearance_percent": .1,
            "tightness_percent": 100., "island_settings": overrides, **parent,
        }],
    })


@pytest.mark.parametrize("mode", ["surface", "rigid_component", "rigid"])
def test_native_island_mode_clearance_and_skip_preserve_source_slots(mode):
    mesh = _islands_mesh()
    with _bound(mesh) as session:
        _configure(session, [
            {"face_indices": [0, 1], "mode": mode, "clearance_percent": 1.,
             "tightness_percent": 0. if mode == "rigid" else 100.},
            {"face_indices": [2, 3], "enabled": False},
        ])
        actual = _snapshot(mesh, session)
        points = np.array(actual.submeshes[1].vertices)
        assert points[4:] == pytest.approx(np.array(mesh.submeshes[1].vertices[4:]))
        expected = .1 if mode == "rigid" else np.sqrt(1.25) * .02
        assert points[:4, 2] == pytest.approx(expected)
        for name in ("faces", "uvs", "bone_indices", "bone_weights", "material", "texture"):
            assert getattr(actual.submeshes[1], name) == getattr(mesh.submeshes[1], name)
        if mode == "rigid_component":
            before = np.array(mesh.submeshes[1].vertices[:4])
            assert np.linalg.norm(points[:4, None]-points[None, :4], axis=2) == pytest.approx(
                np.linalg.norm(before[:, None]-before[None, :], axis=2))
        _command(session, "undo", {})
        assert _snapshot(mesh, session).submeshes[1].vertices == mesh.submeshes[1].vertices
        _command(session, "redo", {})
        assert _snapshot(mesh, session).submeshes[1].vertices == actual.submeshes[1].vertices


def test_native_enabled_override_of_skipped_part_and_explicit_inheritance():
    mesh = _islands_mesh()
    with _bound(mesh) as session:
        _configure(session, [{"face_indices": [2, 3], "enabled": True}], enabled=False)
        points = np.array(_snapshot(mesh, session).submeshes[1].vertices)
        assert points[:4, 2] == pytest.approx(.1)
        assert points[4:, 2].max() < .01
        _configure(session, [], enabled=False)
        assert _snapshot(mesh, session).submeshes[1].vertices == mesh.submeshes[1].vertices


def test_nearby_rigid_islands_can_have_independent_fitting_settings():
    mesh = _islands_mesh()
    part = mesh.submeshes[1]
    part.vertices[4:] = [(x-.1999, y, z) for x, y, z in part.vertices[4:]]
    with _bound(mesh) as session:
        _configure(session, [{"face_indices": [2, 3], "clearance_percent": .2}], mode="rigid_component")
        points = np.array(_snapshot(mesh, session).submeshes[1].vertices)
        assert points[:4, 2] == pytest.approx(np.sqrt(1.25)*.002)
        assert points[4:, 2] == pytest.approx(np.sqrt(1.25)*.004)
        for indices in (slice(0, 4), slice(4, 8)):
            before = np.array(part.vertices)[indices]
            after = points[indices]
            assert np.linalg.norm(after[:, None]-after[None, :], axis=2) == pytest.approx(
                np.linalg.norm(before[:, None]-before[None, :], axis=2))


@pytest.mark.parametrize("faces", [[0], [0, 2], [0, 1, 2, 3], [99]])
def test_native_partial_island_refuses_atomically(faces):
    mesh = _islands_mesh()
    with _bound(mesh) as session:
        before = _state(session)
        report = mesh_native_core.native_mesh_editor_session_command("morph_configure_refit", session, {
            "garment_submesh_indices": [1], "garment_settings": [{
                "submesh_index": 1, "island_settings": [{"face_indices": faces}],
            }],
        })
        assert report is None or report.get("status") == "error"
        assert _state(session) == before
        assert _snapshot(mesh, session).submeshes[1].vertices == mesh.submeshes[1].vertices


def _service_session(resident):
    service, open_session = resident
    mesh = _islands_mesh()
    session = open_session(mesh)
    definitions = (MeshMorphDefinition(definition_id="shape", label="Shape", category="Test", rule=MeshMorphRule("move", "z"),
                    pivot=(0., 0., 0.), local_basis=((1., 0., 0.), (0., 1., 0.), (0., 0., 1.)),
                    vertices=tuple(MeshMorphVertexWeight(0, v, 1.) for v in range(4))),)
    service._activate_morph_profile_locked(service._session(session), MeshMorphProfile(
        profile_id="islands", name="Islands", definitions=definitions,
        topology_fingerprint=mesh_morph_driver_topology_fingerprint(mesh, definitions)))
    assert service.set_refit_driver(session, (0,))[0].ok
    assert service.bind_refit(session, (1,))[0].ok
    return service, session, mesh


def test_service_host_partial_changes_inheritance_and_undo(resident):
    from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession
    service, session, mesh = _service_session(resident)
    owner = service._session(session)
    target = [{"submesh_index": 1, "face_indices": [2, 3]}]
    editor = object.__new__(RustMeshAuthoringSession)
    editor.shadow_service, editor.shadow_session_id = service, session
    count = len(owner.undo_stack)
    result, state = editor._run_morph_command("refit_island_configure", {
        "islands": target, "tightness_percent": 50., "clearance_percent": .2, "mode": "rigid_component",
    })
    assert result.ok and len(owner.undo_stack) == count+1
    setting = state.refit.garment_settings[0]
    assert setting.tightness_percent == 0.
    assert setting.island_settings == (MeshRefitIslandSettings((2, 3), mode="rigid_component",
        tightness_percent=50., clearance_percent=.2),)
    result, state = service.configure_refit(session, (1,), clearance_percent=.4)
    assert result.ok and state.refit.garment_settings[0].island_settings == setting.island_settings
    result, state = editor._run_morph_command("refit_island_configure", {"islands": target, "inherit": True})
    assert result.ok and not state.refit.garment_settings[0].island_settings
    assert service.undo(session).ok
    assert service.cached_morph_state_from_runtime(session).refit.garment_settings[0].island_settings == setting.island_settings
    assert service.working_mesh(session, clone=True).submeshes[1].faces == mesh.submeshes[1].faces


def test_island_overrides_round_trip_recipe_draft_and_bake(resident, tmp_path):
    service, session, mesh = _service_session(resident)
    owner = service._session(session)
    target = [{"submesh_index": 1, "face_indices": [2, 3]}]
    assert service.configure_refit_islands(session, target, mode="rigid_component",
                                         tightness_percent=100., clearance_percent=.2)[0].ok
    state = service.cached_morph_state_from_runtime(session)
    positions = deepcopy(service.working_mesh(session, clone=True).submeshes[1].vertices)
    recipe_path = tmp_path / "islands.json"
    service.export_refit_recipe(session, recipe_path, "Island fit")
    recipe = read_fitting_recipe(recipe_path)
    assert recipe.format == "cdmw.mesh_refit_recipe.v3"
    assert recipe.garment_settings == state.refit.garment_settings
    fitted_mesh = service.working_mesh(session, clone=True)
    payload = capture_morph_draft(service, owner)
    assert payload["format"] == "cdmw.morph_draft.v3"
    assert json.loads(payload["native"])["version"] == 3
    generation = tmp_path / "generation"
    generation.mkdir()
    payload = load_morph_draft(persist_morph_draft(payload, generation, tmp_path), tmp_path)
    assert service.configure_refit_islands(session, target, inherit=True)[0].ok
    assert service.import_refit_recipe(session, recipe_path)[0].ok
    assert service.cached_morph_state_from_runtime(session).refit.garment_settings == state.refit.garment_settings
    # Reopening a draft loads its saved visible mesh before the runtime snapshot.
    session = resident[1](fitted_mesh)
    owner = service._session(session)
    restore_morph_draft(service, owner, payload)
    assert service.cached_morph_state_from_runtime(session).refit == state.refit
    # Draft loading restores its visible geometry separately. The next resident
    # composition must recover the same preview from the restored neutral state.
    assert service.configure_refit_islands(session, target, clearance_percent=.2)[0].ok
    assert np.array(service.working_mesh(session, clone=True).submeshes[1].vertices) == pytest.approx(np.array(positions))
    assert service.bake_morph(session)[0].ok
    baked = service.cached_morph_state_from_runtime(session).refit.garment_settings[0]
    assert baked.island_settings[0].tightness_percent == 0.
    assert np.array(service.working_mesh(session, clone=True).submeshes[1].vertices) == pytest.approx(np.array(positions))
    assert service.working_mesh(session, clone=True).submeshes[1].faces == mesh.submeshes[1].faces


def test_island_following_is_independent_and_global_fit_respects_skips(resident):
    service, session, mesh = _service_session(resident)
    target = [{"submesh_index": 1, "face_indices": [2, 3]}]
    assert service.configure_refit_islands(session, target, mode="rigid_component", intensity_percent=0.)[0].ok
    assert service.set_morph_value(session, "shape", -50.)[0].ok
    actual = np.array(service.working_mesh(session, clone=True).submeshes[1].vertices)
    expected = np.array(mesh.submeshes[1].vertices)
    assert actual[:4, 2] == pytest.approx(expected[:4, 2]-.05)
    assert actual[4:] == pytest.approx(expected[4:])
    assert service.reset_morph(session)[0].ok
    assert service.configure_refit(session, (1,), enabled=False)[0].ok
    assert service.configure_refit_islands(session, target, enabled=True, tightness_percent=25.)[0].ok
    assert service.fit_refit_to_body(session)[0].ok
    state = service.cached_morph_state_from_runtime(session).refit.garment_settings[0]
    assert not state.enabled and state.island_settings[0].enabled
    assert state.island_settings[0].tightness_percent == 25.
    actual = np.array(service.working_mesh(session, clone=True).submeshes[1].vertices)
    assert actual[:4] == pytest.approx(expected[:4])


@pytest.mark.parametrize("faces", [[0], [0, 1, 1], [False, 1], [.1, 1]])
def test_service_rejects_invalid_island_identity_without_history(resident, faces):
    service, session, _ = _service_session(resident)
    count = len(service._session(session).undo_stack)
    with pytest.raises(ValueError):
        service.configure_refit_islands(session, [{"submesh_index": 1, "face_indices": faces}], enabled=False)
    assert len(service._session(session).undo_stack) == count
