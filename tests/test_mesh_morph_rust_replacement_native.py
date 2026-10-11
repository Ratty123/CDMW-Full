"""Native integration for morph state across Rust geometry publication boundaries."""
from __future__ import annotations

import pytest

from cdmw.domain.mesh import MeshEditSelection
from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession, RustMeshValidationError
from tests.test_mesh_morph_authoring_native import resident, _positions, _assert_positions_equal
from tests.test_mesh_morph_service import _author_command


def _bridge(service, session_id):
    bridge = object.__new__(RustMeshAuthoringSession)
    bridge.shadow_service = service
    bridge.shadow_session_id = session_id
    return bridge


def _prepared_offset(service, session_id, part, vertices, amount):
    candidate = service.working_mesh(session_id, clone=True)
    positions = list(candidate.submeshes[part].vertices)
    for index in vertices:
        point = positions[index]
        positions[index] = (point[0], point[1], point[2] + amount)
    candidate.submeshes[part].vertices = positions
    return service.prepare_working_mesh_replacement(session_id, candidate)


def _setup_fit(service, session_id):
    assert service.apply_command(session_id, _author_command()).ok
    assert service.set_refit_driver(session_id, (0, 1))[0].ok
    assert service.bind_refit(session_id, (2,))[0].ok


def test_rust_sculpt_preserves_baseline_bindings_and_masks_before_capture(resident):
    service, open_session = resident
    session_id = open_session()
    _setup_fit(service, session_id)
    assert service.set_refit_vertex_influence(
        session_id, selection=MeshEditSelection.from_maps(vertices_by_submesh={2: (0,)}),
        weight=0.0,
    )[0].ok
    original = _positions(service, session_id, 0)
    service.capture_morph_baseline(session_id, (0,))
    bridge = _bridge(service, session_id)
    prepared = _prepared_offset(service, session_id, 0, (0, 1, 2), 0.3)
    bridge._commit_morph_preserving_replacement(prepared, history_action="rust_transaction")
    state = service.morph_state(session_id)
    assert state.authoring_baseline_ready
    assert state.driver_submesh_indices == (0, 1)
    assert state.refit.garment_submesh_indices == (2,)
    assert dict(state.refit.garment_settings[0].vertex_mask).get(0, 0.0) == 0.0
    target = _positions(service, session_id, 0)
    result, state = service.capture_authored_morph_definition(
        session_id, profile_id="resident-body", profile_name="Body",
        definition_id="sculpt", label="Sculpt",
    )
    assert result.ok and not state.authoring_baseline_ready
    assert state.refit.garment_submesh_indices == (2,)
    _assert_positions_equal(_positions(service, session_id, 0), target)
    assert service.reset_morph(session_id)[0].ok
    _assert_positions_equal(_positions(service, session_id, 0), original)
    assert service.set_morph_value(session_id, "sculpt", 50.0)[0].ok
    for source, actual in zip(original, _positions(service, session_id, 0)):
        assert actual[2] == pytest.approx(source[2] + 0.15, abs=1e-6)


def test_rust_sculpt_keeps_pending_correction_and_real_edited_residual(resident):
    service, open_session = resident
    session_id = open_session()
    _setup_fit(service, session_id)
    neutral = _positions(service, session_id, 2)
    service.begin_morph_correction(session_id, "volume", (2,))
    bridge = _bridge(service, session_id)
    prepared = _prepared_offset(service, session_id, 2, (0,), 0.2)
    bridge._commit_morph_preserving_replacement(prepared, history_action="rust_transaction")
    state = service.morph_state(session_id)
    assert state.correction_definition_id == "volume"
    assert state.values == (("volume", 100.0),)
    target = _positions(service, session_id, 2)
    assert service.save_morph_correction(session_id)[0].ok
    _assert_positions_equal(_positions(service, session_id, 2), target)
    assert service.reset_morph(session_id)[0].ok
    _assert_positions_equal(_positions(service, session_id, 2), neutral)


def test_incompatible_pending_replacement_rejects_before_mesh_or_history_change(resident):
    service, open_session = resident
    session_id = open_session()
    service.capture_morph_baseline(session_id, (0,))
    original = _positions(service, session_id, 0)
    revision = service._session(session_id).revision
    undo_count = len(service._session(session_id).undo_stack)
    candidate = service.working_mesh(session_id, clone=True)
    candidate.submeshes[0].faces[0] = tuple(reversed(candidate.submeshes[0].faces[0]))
    prepared = service.prepare_working_mesh_replacement(session_id, candidate)
    with pytest.raises(RustMeshValidationError, match="unchanged topology and source mapping"):
        _bridge(service, session_id)._commit_morph_preserving_replacement(prepared)
    assert service._session(session_id).revision == revision
    assert len(service._session(session_id).undo_stack) == undo_count
    assert service.cached_morph_state(session_id).authoring_baseline_ready
    _assert_positions_equal(_positions(service, session_id, 0), original)
