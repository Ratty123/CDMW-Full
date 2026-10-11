"""Actual-native regressions for the Morph & Refit follow-up review."""

from __future__ import annotations

from dataclasses import replace
import json

import pytest

from cdmw.domain.mesh import MeshEditSelection
from tests.test_mesh_morph_authoring_native import (
    _assert_positions_equal,
    _positions,
    _sculpt,
    resident,
)
from tests.test_mesh_morph_service import _author_command
from tests.test_native_mesh_editor_morph_refit import _driver_garment_mesh, _part


def _all_positions(service, session_id):
    mesh = service.working_mesh(session_id, clone=True)
    return tuple(tuple(tuple(point) for point in part.vertices) for part in mesh.submeshes)


def _assert_all_positions_equal(actual, expected):
    assert len(actual) == len(expected)
    for actual_part, expected_part in zip(actual, expected):
        _assert_positions_equal(actual_part, expected_part)


def _split_rigid_mesh():
    mesh = _driver_garment_mesh()
    other = mesh.submeshes[3]
    mesh.submeshes[2] = _part(
        "panel-a", [(0., 0., .1), (1., 0., .1), (0., 1., .1)], [(0, 1, 2)],
        material="metal-a", texture="",
    )
    mesh.submeshes[3] = _part(
        "panel-b", [(1., 0., .1), (1., 1., .1), (0., 1., .1)], [(0, 1, 2)],
        material="metal-b", texture="",
    )
    mesh.submeshes.append(other)
    mesh.total_vertices = sum(len(part.vertices) for part in mesh.submeshes)
    mesh.total_faces = sum(len(part.faces) for part in mesh.submeshes)
    return mesh


def test_procedural_edit_retains_saved_correction_through_history_and_reopen(resident, tmp_path):
    service, open_session = resident
    session_id = open_session()
    command = _author_command()
    assert service.apply_command(session_id, command).ok
    assert service.set_refit_driver(session_id, (0, 1))[0].ok
    assert service.bind_refit(session_id, (2,))[0].ok
    assert service.begin_morph_correction(session_id, "volume", (2,))[0].ok
    assert _sculpt(service, session_id, {2: (0,)}, (0., 0., .2)).ok
    assert service.save_morph_correction(session_id)[0].ok
    corrected_target = _positions(service, session_id, 2)
    corrections = service.cached_morph_state(session_id).definitions[0].garment_corrections
    assert corrections
    assert service.reset_morph(session_id)[0].ok

    before_history = len(service._session(session_id).undo_stack)
    edited = replace(command, params={
        **command.params, "source_definition_id": "volume", "definition_id": "fit-volume",
        "label": "Fit Volume", "preserve_selection": True,
    })
    assert service.apply_command(session_id, edited).ok
    assert len(service._session(session_id).undo_stack) == before_history + 1
    definition = service.cached_morph_state(session_id).definitions[0]
    assert definition.definition_id == "fit-volume"
    assert definition.garment_corrections == tuple(
        replace(field, definition_id="fit-volume") for field in corrections
    )
    assert service.undo(session_id).ok
    original = service.cached_morph_state(session_id).definitions[0]
    assert original.definition_id == "volume"
    assert original.garment_corrections == corrections
    assert service.redo(session_id).ok
    assert service.cached_morph_state(session_id).definitions[0] == definition

    # Editing and history preserve the current garment fit as well as the fields.
    refit = service.cached_morph_state(session_id).refit
    assert refit.driver_submesh_indices == (0, 1)
    assert refit.garment_submesh_indices == (2,)
    assert service.set_morph_value(session_id, "fit-volume", 100.0)[0].ok
    _assert_positions_equal(_positions(service, session_id, 2), corrected_target)
    service.save_active_morph_profile(session_id)
    saved = json.loads(
        (tmp_path / "mesh_slider_profiles" / "definitions" / "resident-body.json").read_text()
    )
    assert saved["format"] == "cdmw.mesh_morph_profile.v3"

    reopened = open_session()
    assert service.activate_morph_profile(reopened, "resident-body")[0].ok
    assert service.set_refit_driver(reopened, (0, 1))[0].ok
    assert service.bind_refit(reopened, (2,))[0].ok
    assert service.set_morph_value(reopened, "fit-volume", 100.0)[0].ok
    _assert_positions_equal(_positions(service, reopened, 2), corrected_target)


def test_cancel_correction_restores_all_shapes_prior_values_and_pending_undo(resident):
    service, open_session = resident
    session_id = open_session()
    assert service.capture_morph_baseline(session_id, (0,))[0].ok
    assert _sculpt(service, session_id, {0: (0, 1, 2)}, (0., 0., .3)).ok
    assert service.capture_authored_morph_definition(
        session_id, profile_id="cancel-body", profile_name="Cancel Body",
        definition_id="shape", label="Shape",
    )[0].ok
    assert service.reset_morph(session_id)[0].ok
    assert service.set_refit_driver(session_id, (0,))[0].ok
    assert service.bind_refit(session_id, (2,))[0].ok
    assert service.set_morph_value(session_id, "shape", 35.0)[0].ok
    before = _all_positions(service, session_id)
    assert service.begin_morph_correction(session_id, "shape", (2,))[0].ok
    assert _sculpt(service, session_id, {0: (0,), 2: (0,), 3: (1,)}, (0., .125, 0.)).ok
    edited = _all_positions(service, session_id)
    with pytest.raises(ValueError, match="outside the chosen garments"):
        service.save_morph_correction(session_id)
    before_history = len(service._session(session_id).undo_stack)

    result, state = service.cancel_morph_correction(session_id)
    assert result.ok and not state.correction_definition_id
    assert state.values == (("shape", 35.0),)
    assert len(service._session(session_id).undo_stack) == before_history + 1
    _assert_all_positions_equal(_all_positions(service, session_id), before)

    assert service.undo(session_id).ok
    assert service.cached_morph_state(session_id).correction_definition_id == "shape"
    _assert_all_positions_equal(_all_positions(service, session_id), edited)
    assert service.redo(session_id).ok
    assert not service.cached_morph_state(session_id).correction_definition_id
    _assert_all_positions_equal(_all_positions(service, session_id), before)
    assert service.set_morph_value(session_id, "shape", 60.0)[0].ok
    assert service.set_morph_value(session_id, "shape", 35.0)[0].ok
    _assert_all_positions_equal(_all_positions(service, session_id), before)


def test_split_rigid_masks_and_recipe_apply_as_one_history_edit(resident, tmp_path):
    service, open_session = resident
    mesh = _split_rigid_mesh()
    session_id = open_session(mesh)
    assert service.apply_command(session_id, _author_command()).ok
    assert service.set_refit_driver(session_id, (0, 1))[0].ok
    assert service.bind_refit(session_id, (2, 3, 4))[0].ok
    assert service.configure_refit(
        session_id, (2, 3), enabled=True, intensity_percent=125.,
        mode="rigid_component", clearance_percent=0.,
    )[0].ok
    assert service.configure_refit(
        session_id, (4,), enabled=False, intensity_percent=25.,
        mode="rigid", clearance_percent=1.,
    )[0].ok
    assert service.set_morph_value(session_id, "volume", 50.0)[0].ok
    selection = MeshEditSelection.from_maps(vertices_by_submesh={2: (0, 1, 2), 3: (0, 1, 2)})
    full = _all_positions(service, session_id)
    before_history = len(service._session(session_id).undo_stack)

    result, state = service.set_refit_vertex_influence(session_id, selection=selection, weight=.5)
    assert result.ok
    assert len(service._session(session_id).undo_stack) == before_history + 1
    settings = {item.submesh_index: item for item in state.refit.garment_settings}
    for index in (2, 3):
        assert settings[index].vertex_mask == ((0, .5), (1, .5), (2, .5))
        assert settings[index].mode == "rigid_component"
        assert settings[index].intensity_percent == 125.
    assert not settings[4].enabled and settings[4].mode == "rigid"
    assert settings[4].intensity_percent == 25. and settings[4].clearance_percent == 1.
    half = _all_positions(service, session_id)
    assert half != full
    assert service.undo(session_id).ok
    _assert_all_positions_equal(_all_positions(service, session_id), full)
    assert service.redo(session_id).ok
    _assert_all_positions_equal(_all_positions(service, session_id), half)

    assert service.set_refit_vertex_influence(session_id, selection=selection, weight=0.)[0].ok
    for index in (2, 3):
        _assert_positions_equal(_positions(service, session_id, index), mesh.submeshes[index].vertices)
    assert service.clear_refit_vertex_influence(session_id, (2, 3))[0].ok
    _assert_all_positions_equal(_all_positions(service, session_id), full)
    assert service.set_refit_vertex_influence(session_id, selection=selection, weight=.5)[0].ok
    expected_state = service.cached_morph_state(session_id)
    recipe_path = service.export_refit_recipe(session_id, tmp_path / "split-panel.recipe.json", "Split Panel")

    reopened = open_session(_split_rigid_mesh())
    neutral = _all_positions(service, reopened)
    before_history = len(service._session(reopened).undo_stack)
    result, state = service.import_refit_recipe(reopened, recipe_path)
    assert result.ok
    assert state.refit.garment_settings == expected_state.refit.garment_settings
    assert state.values == (("volume", 50.0),)
    assert len(service._session(reopened).undo_stack) == before_history + 1
    _assert_all_positions_equal(_all_positions(service, reopened), half)
    assert service.undo(reopened).ok
    _assert_all_positions_equal(_all_positions(service, reopened), neutral)
    assert not service.cached_morph_state(reopened).refit.garment_submesh_indices
    assert service.redo(reopened).ok
    assert service.cached_morph_state(reopened).refit.garment_settings == expected_state.refit.garment_settings
    _assert_all_positions_equal(_all_positions(service, reopened), half)
