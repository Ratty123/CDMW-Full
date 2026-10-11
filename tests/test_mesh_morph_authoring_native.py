"""Resident integration checks for authored targets and reusable fitting recipes.

Run only against the rebuilt native core. These exercise ordinary mesh edits
between authoring actions, native runtime snapshots, and persisted profile reuse.
"""

from __future__ import annotations

import json

import pytest

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.modding import mesh_native_core
from cdmw.services.mesh_service import MeshService
from tests.test_mesh_morph_service import _Settings, _author_command
from tests.test_native_mesh_editor_morph_refit import _driver_garment_mesh


@pytest.fixture
def resident(tmp_path):
    if not mesh_native_core.native_mesh_core_available():
        pytest.skip("rebuilt native mesh core is required")
    service = MeshService(settings=_Settings(tmp_path / "settings.ini"))
    sessions = []

    def open_session(mesh=None):
        session_id = service.open_edit_session(mesh or _driver_garment_mesh(), mode="edit").session_id
        sessions.append(session_id)
        return session_id

    yield service, open_session
    for session_id in reversed(sessions):
        service.close_edit_session(session_id)


def _sculpt(service, session_id, parts, delta):
    return service.apply_command(session_id, MeshEditCommand(
        "transform", selection=MeshEditSelection.from_maps(vertices_by_submesh=parts),
        params={"delta": delta}, mode="edit",
    ))


def _positions(service, session_id, index):
    return tuple(tuple(point) for point in service.working_mesh(session_id, clone=True).submeshes[index].vertices)


def _assert_positions_equal(actual, expected):
    assert len(actual) == len(expected)
    for left, right in zip(actual, expected):
        assert left == pytest.approx(right, abs=1e-6)


def test_authored_slider_capture_sculpt_undo_values_save_and_reopen(resident, tmp_path):
    service, open_session = resident
    session_id = open_session()
    original = _positions(service, session_id, 0)
    baseline, state = service.capture_morph_baseline(session_id, (0,))
    assert baseline.ok and state.authoring_baseline_ready
    with pytest.raises(RuntimeError, match="baseline"):
        service.finish_morph(session_id)
    assert _sculpt(service, session_id, {0: (0, 1, 2)}, (0.0, 0.0, 0.3)).ok
    target = _positions(service, session_id, 0)
    captured, state = service.capture_authored_morph_definition(
        session_id, profile_id="captured-body", profile_name="Captured Body",
        definition_id="shape", label="Shape",
    )
    assert captured.ok
    assert state.values == (("shape", 100.0),)
    assert not state.authoring_baseline_ready
    _assert_positions_equal(_positions(service, session_id, 0), target)
    assert service.undo(session_id).ok
    assert service.cached_morph_state(session_id).authoring_baseline_ready
    _assert_positions_equal(_positions(service, session_id, 0), target)
    assert service.redo(session_id).ok
    assert not service.cached_morph_state(session_id).authoring_baseline_ready
    assert service.set_morph_value(session_id, "shape", 50.0)[0].ok
    for before, after in zip(original, _positions(service, session_id, 0)):
        assert after[2] == pytest.approx(before[2] + 0.15, abs=1e-6)
    assert service.reset_morph(session_id)[0].ok
    _assert_positions_equal(_positions(service, session_id, 0), original)
    service.save_active_morph_profile(session_id)
    payload = json.loads((tmp_path / "mesh_slider_profiles" / "definitions" / "captured-body.json").read_text())
    assert payload["format"] == "cdmw.mesh_morph_profile.v3"

    reopened = open_session()
    assert service.activate_morph_profile(reopened, "captured-body")[0].ok
    assert service.set_morph_value(reopened, "shape", 50.0)[0].ok
    for before, after in zip(original, _positions(service, reopened, 0)):
        assert after[2] == pytest.approx(before[2] + 0.15, abs=1e-6)


def test_correction_capture_sculpt_save_zero_half_and_reopen(resident):
    service, open_session = resident
    session_id = open_session()
    neutral = _positions(service, session_id, 2)
    assert service.apply_command(session_id, _author_command()).ok
    assert service.set_refit_driver(session_id, (0, 1))[0].ok
    assert service.bind_refit(session_id, (2,))[0].ok
    begun, state = service.begin_morph_correction(session_id, "volume", (2,))
    assert begun.ok and state.correction_definition_id == "volume"
    preview = _positions(service, session_id, 2)
    assert _sculpt(service, session_id, {2: (0,)}, (0.0, 0.0, 0.2)).ok
    target = _positions(service, session_id, 2)
    saved, state = service.save_morph_correction(session_id)
    assert saved.ok and not state.correction_definition_id
    _assert_positions_equal(_positions(service, session_id, 2), target)
    assert service.undo(session_id).ok
    assert service.cached_morph_state(session_id).correction_definition_id == "volume"
    _assert_positions_equal(_positions(service, session_id, 2), target)
    assert service.redo(session_id).ok
    assert not service.cached_morph_state(session_id).correction_definition_id
    service.save_active_morph_profile(session_id)
    assert service.reset_morph(session_id)[0].ok
    _assert_positions_equal(_positions(service, session_id, 2), neutral)
    assert service.set_morph_value(session_id, "volume", 50.0)[0].ok
    half = _positions(service, session_id, 2)
    assert half[0][2] == pytest.approx(neutral[0][2] + (preview[0][2] - neutral[0][2]) * 0.5 + 0.1, abs=1e-5)

    reopened = open_session()
    assert service.activate_morph_profile(reopened, "resident-body")[0].ok
    assert service.set_refit_driver(reopened, (0, 1))[0].ok
    assert service.bind_refit(reopened, (2,))[0].ok
    assert service.set_morph_value(reopened, "volume", 50.0)[0].ok
    _assert_positions_equal(_positions(service, reopened, 2), half)


def test_active_recipe_reuses_masks_and_scoped_regions_in_compatible_session(resident, tmp_path):
    service, open_session = resident
    session_id = open_session()
    assert service.apply_command(session_id, _author_command()).ok
    assert service.set_refit_driver(session_id, (0, 1))[0].ok
    assert service.bind_refit(session_id, (2, 3))[0].ok
    assert service.set_refit_vertex_influence(
        session_id, selection=MeshEditSelection.from_maps(vertices_by_submesh={2: (0,)}), weight=0.0,
    )[0].ok
    assert service.set_refit_driver_region(
        session_id, (2,), selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
    )[0].ok
    assert service.set_morph_value(session_id, "volume", 50.0)[0].ok
    expected = _positions(service, session_id, 2)
    recipe_path = service.export_refit_recipe(session_id, tmp_path / "outfit.recipe.json", "Outfit")

    reopened = open_session()
    before_history = len(service._session(reopened).undo_stack)
    result, state = service.import_refit_recipe(reopened, recipe_path)
    assert result.ok and state.values == (("volume", 50.0),)
    assert len(service._session(reopened).undo_stack) == before_history + 1
    settings = {item.submesh_index: item for item in state.refit.garment_settings}
    assert dict(settings[2].vertex_mask).get(0, 0.0) == 0.0
    regions = dict(state.refit.garment_regions)
    assert regions[2][0].submesh_index == 0
    assert regions[2][0].vertex_indices == (0, 1, 2)
    _assert_positions_equal(_positions(service, reopened, 2), expected)
