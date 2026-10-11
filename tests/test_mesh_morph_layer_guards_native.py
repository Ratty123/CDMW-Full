"""Resident regressions for normal edit guards around retained morph layers."""

from __future__ import annotations

import pytest

from cdmw.domain.mesh import MeshEditCommand
from tests.test_mesh_morph_authoring_native import resident, _sculpt
from tests.test_mesh_morph_body_workflow_native import _geometry, _open_body


@pytest.fixture
def layered_body(resident):
    service, _open_session, session_id, _mesh, profile = _open_body(resident)
    assert service.set_morph_macro(session_id, "waist_shape", 20.0)[0].ok
    assert service.begin_morph_correction(session_id, "spine_lower_size", (1,))[0].ok
    assert _sculpt(service, session_id, {1: (0,)}, (0.0, 0.0, 0.2)).ok
    assert service.save_morph_correction(session_id)[0].ok
    service.save_morph_preset(session_id, "guarded-layers", "Guarded Layers")
    return service, session_id, profile.profile_id


def _edit(service, session_id, profile_id, operation):
    if operation == "manual":
        return service.set_morph_value(session_id, "spine_lower_size", 30.0)
    if operation == "macro":
        return service.apply_command(session_id, MeshEditCommand(
            "morph_set_macro", params={"macro_id": "waist_shape", "value": 30.0}, mode="edit",
        ))
    if operation == "preset":
        return service.apply_morph_preset(session_id, "guarded-layers")
    if operation == "cached_preset":
        return service.apply_cached_morph_preset(session_id, "guarded-layers")
    if operation == "cached_profile":
        return service.activate_cached_morph_profile(session_id, profile_id)
    raise AssertionError(operation)


def _snapshot(service, session_id):
    state = service.cached_morph_state(session_id)
    session = service._session(session_id)
    return (
        state.profile_id, state.definitions, state.values, state.manual_values,
        state.macro_values, state.symmetry_enabled, state.corrections_enabled,
        state.authoring_baseline_ready, state.refit, _geometry(service, session_id),
        len(session.undo_stack), len(session.redo_stack), session.morph_session_revision,
    )


@pytest.mark.parametrize("operation", ["manual", "preset", "cached_preset", "cached_profile"])
def test_layered_public_edits_refuse_hidden_correction_comparison(layered_body, operation):
    service, session_id, profile_id = layered_body
    if operation == "cached_profile":
        assert service.reset_morph_macros(session_id)[0].ok
    assert service.set_morph_corrections_enabled(session_id, False)[0].ok
    before = _snapshot(service, session_id)
    with pytest.raises(RuntimeError, match="corrections back on"):
        _edit(service, session_id, profile_id, operation)
    assert _snapshot(service, session_id) == before


@pytest.mark.parametrize("operation", ["manual", "cached_profile"])
def test_layered_public_edits_refuse_pending_authored_baseline(layered_body, operation):
    service, session_id, profile_id = layered_body
    assert service.reset_morph_macros(session_id)[0].ok
    assert service.capture_morph_baseline(session_id, (0,))[0].ok
    before = _snapshot(service, session_id)
    with pytest.raises(RuntimeError, match="baseline"):
        _edit(service, session_id, profile_id, operation)
    assert _snapshot(service, session_id) == before


@pytest.mark.parametrize("operation", ["macro", "preset"])
def test_layered_values_require_every_corrected_garment_to_remain_bound(layered_body, operation):
    service, session_id, profile_id = layered_body
    assert service.clear_refit(session_id)[0].ok
    before = _snapshot(service, session_id)
    with pytest.raises(RuntimeError, match="Bind every garment"):
        _edit(service, session_id, profile_id, operation)
    assert _snapshot(service, session_id) == before


@pytest.mark.parametrize("operation", ["macro", "preset"])
def test_layered_values_refuse_corrections_after_neutral_geometry_changes(layered_body, operation):
    service, session_id, profile_id = layered_body
    assert service.reset_morph_macros(session_id)[0].ok
    assert _sculpt(service, session_id, {1: (0,)}, (0.0, 0.0, 0.4)).ok
    before = _snapshot(service, session_id)
    with pytest.raises(ValueError, match="base geometry or source/skin identity"):
        _edit(service, session_id, profile_id, operation)
    assert _snapshot(service, session_id) == before
