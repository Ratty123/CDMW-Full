"""Resident proof that partial fitting setup application respects correction scope."""

from __future__ import annotations

from tests.test_mesh_morph_authoring_native import (
    resident, _assert_positions_equal, _positions, _sculpt,
)
from tests.test_mesh_morph_outfit_workflows_native import _corrected_outfit


def _corrections(state):
    return {
        (definition.definition_id, field.submesh_index): field
        for definition in state.definitions for field in definition.garment_corrections
    }


def test_partial_setup_preserves_current_unselected_correction_and_history(resident):
    service, open_session = resident
    session_id = _corrected_outfit(service, open_session)
    expected_selected = _positions(service, session_id, 2)
    _result, saved = service.save_refit_setup(session_id, "Selected outfit correction")
    identifier = saved.matching_recipes[0][0]
    saved_fields = _corrections(saved)

    assert service.reset_morph_correction(session_id, "volume", (2,))[0].ok
    assert service.begin_morph_correction(session_id, "volume", (3,))[0].ok
    assert _sculpt(service, session_id, {3: (0,)}, (0.0, 0.0, 0.4)).ok
    assert service.save_morph_correction(session_id)[0].ok
    assert service.set_morph_value(session_id, "volume", 50.0)[0].ok
    before = service.cached_morph_state(session_id)
    before_fields = _corrections(before)
    before_selected = _positions(service, session_id, 2)
    before_other = _positions(service, session_id, 3)
    before_body = _positions(service, session_id, 0)
    assert ("volume", 2) not in before_fields
    assert before_fields[("volume", 3)] != saved_fields[("volume", 3)]

    result, applied = service.apply_refit_setup(session_id, identifier, (2,))
    assert result.ok
    assert applied.values == before.values
    assert applied.refit.garment_settings == before.refit.garment_settings
    assert _corrections(applied) == {
        ("volume", 2): saved_fields[("volume", 2)],
        ("volume", 3): before_fields[("volume", 3)],
    }
    _assert_positions_equal(_positions(service, session_id, 2), expected_selected)
    _assert_positions_equal(_positions(service, session_id, 3), before_other)
    _assert_positions_equal(_positions(service, session_id, 0), before_body)

    assert service.undo(session_id).ok
    assert _corrections(service.cached_morph_state(session_id)) == before_fields
    _assert_positions_equal(_positions(service, session_id, 2), before_selected)
    _assert_positions_equal(_positions(service, session_id, 3), before_other)
    assert service.redo(session_id).ok
    assert _corrections(service.cached_morph_state(session_id)) == _corrections(applied)
    _assert_positions_equal(_positions(service, session_id, 2), expected_selected)
    _assert_positions_equal(_positions(service, session_id, 3), before_other)


def test_partial_setup_on_reopen_binds_and_corrects_only_requested_garment(resident):
    service, open_session = resident
    original = _corrected_outfit(service, open_session)
    expected = _positions(service, original, 2)
    _result, saved = service.save_refit_setup(original, "Reopen selected garment")
    identifier = saved.matching_recipes[0][0]

    reopened = open_session()
    before_other = _positions(service, reopened, 3)
    available = service.morph_state(reopened)
    assert not available.profile_id and not available.refit.garment_submesh_indices
    assert available.matching_recipe_garments == ((identifier, (2, 3)),)
    result, applied = service.apply_refit_setup(reopened, identifier, (2,))
    assert result.ok
    assert applied.refit.garment_submesh_indices == (2,)
    assert set(_corrections(applied)) == {("volume", 2)}
    _assert_positions_equal(_positions(service, reopened, 2), expected)
    _assert_positions_equal(_positions(service, reopened, 3), before_other)
