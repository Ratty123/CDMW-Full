"""Resident proof for reversible outfit correction comparison and scoped reset."""

from __future__ import annotations

import pytest

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection, MeshMorphValuePreset
from cdmw.domain.mesh.morph_layers import mesh_morph_profile_definition_fingerprint
from cdmw.services.mesh_morph_profiles import save_mesh_morph_preset
from tests.test_mesh_morph_authoring_native import (
    resident, _assert_positions_equal, _positions, _sculpt,
)
from tests.test_mesh_morph_service import _author_command


def _corrected_outfit(service, open_session):
    session_id = open_session()
    assert service.apply_command(session_id, _author_command()).ok
    assert service.set_refit_driver(session_id, (0, 1))[0].ok
    assert service.bind_refit(session_id, (2, 3))[0].ok
    assert service.begin_morph_correction(session_id, "volume", (2, 3))[0].ok
    assert _sculpt(service, session_id, {2: (0,)}, (0.0, 0.0, 0.2)).ok
    assert _sculpt(service, session_id, {3: (0,)}, (0.0, 0.0, 0.3)).ok
    assert service.save_morph_correction(session_id)[0].ok
    assert service.set_morph_value(session_id, "volume", 50.0)[0].ok
    return session_id


def _positions_for(service, session_id):
    return tuple(_positions(service, session_id, index) for index in range(4))


def _same_mesh(actual, expected):
    for left, right in zip(actual, expected):
        _assert_positions_equal(left, right)


def test_comparison_restores_corrections_and_blocks_edit_and_export(resident):
    service, open_session = resident
    session_id = _corrected_outfit(service, open_session)
    corrected = _positions_for(service, session_id)
    state_before = service.cached_morph_state(session_id)
    result, state = service.set_morph_corrections_enabled(session_id, False)
    assert result.ok and not state.corrections_enabled
    assert state.values == state_before.values
    assert state.definitions == state_before.definitions
    assert state.refit.garment_settings == state_before.refit.garment_settings
    automatic = _positions_for(service, session_id)
    _assert_positions_equal(automatic[0], corrected[0])
    _assert_positions_equal(automatic[1], corrected[1])
    assert automatic[2][0][2] == pytest.approx(corrected[2][0][2] - 0.1, abs=1e-5)
    assert automatic[3][0][2] == pytest.approx(corrected[3][0][2] - 0.15, abs=1e-5)
    before_rejected = len(service._session(session_id).undo_stack)
    for operation in (
        lambda: service.set_morph_value(session_id, "volume", 20),
        lambda: service.bake_morph(session_id),
        lambda: service.finish_morph(session_id),
        lambda: service.capture_export_snapshot(session_id),
        lambda: service.apply_command(session_id, MeshEditCommand(
            "transform", selection=MeshEditSelection.from_maps(vertices_by_submesh={2: (0,)}),
            params={"delta": (0, 0, 1)}, mode="edit",
        )),
    ):
        with pytest.raises(RuntimeError, match="corrections back on"):
            operation()
    assert len(service._session(session_id).undo_stack) == before_rejected
    _same_mesh(_positions_for(service, session_id), automatic)
    assert service.undo(session_id).ok
    assert service.cached_morph_state(session_id).corrections_enabled
    _same_mesh(_positions_for(service, session_id), corrected)
    assert service.redo(session_id).ok
    assert not service.cached_morph_state(session_id).corrections_enabled
    _same_mesh(_positions_for(service, session_id), automatic)
    assert service.set_morph_corrections_enabled(session_id, True)[0].ok
    _same_mesh(_positions_for(service, session_id), corrected)


def test_reset_correction_changes_only_selected_garment_and_is_reversible(resident):
    service, open_session = resident
    session_id = _corrected_outfit(service, open_session)
    corrected = _positions_for(service, session_id)
    assert service.set_morph_corrections_enabled(session_id, False)[0].ok
    automatic = _positions_for(service, session_id)
    assert service.set_morph_corrections_enabled(session_id, True)[0].ok
    before = service.cached_morph_state(session_id)
    before_history = len(service._session(session_id).undo_stack)
    result, state = service.reset_morph_correction(session_id, "volume", (2,))
    assert result.ok and len(service._session(session_id).undo_stack) == before_history + 1
    assert state.values == before.values
    assert state.refit.garment_settings == before.refit.garment_settings
    definition = state.definitions[0]
    assert {item.submesh_index for item in definition.garment_corrections} == {3}
    reset = _positions_for(service, session_id)
    _assert_positions_equal(reset[2], automatic[2])
    for index in (0, 1, 3):
        _assert_positions_equal(reset[index], corrected[index])
    assert service.undo(session_id).ok
    _same_mesh(_positions_for(service, session_id), corrected)
    assert service.cached_morph_state(session_id).definitions == before.definitions
    assert service.redo(session_id).ok
    _same_mesh(_positions_for(service, session_id), reset)
    unchanged_history = len(service._session(session_id).undo_stack)
    assert service.reset_morph_correction(session_id, "volume", (2,))[0].status == "noop"
    assert len(service._session(session_id).undo_stack) == unchanged_history
    assert service.reset_morph_correction(session_id, "volume", (3,))[0].ok
    assert service.cached_morph_state(session_id).definitions[0].garment_corrections == ()
    _same_mesh(_positions_for(service, session_id), automatic)


def test_correction_cancel_and_save_keep_retained_layer_inputs(resident):
    service, open_session = resident
    session_id = _corrected_outfit(service, open_session)
    data = service._morph_sessions[session_id]
    preset = MeshMorphValuePreset(
        preset_id="retained-manual", name="Retained manual", profile_id=data.profile.profile_id,
        topology_fingerprint=data.profile.topology_fingerprint, values=(("volume", 35.0),),
        manual_values=(("volume", 35.0),),
        profile_definition_fingerprint=mesh_morph_profile_definition_fingerprint(data.profile),
    )
    save_mesh_morph_preset(service._profile_root(), preset)
    assert service.apply_morph_preset(session_id, preset.preset_id)[0].ok
    before = _positions_for(service, session_id)
    assert service.begin_morph_correction(session_id, "volume", (2,))[0].ok
    assert _sculpt(service, session_id, {2: (0,)}, (0.0, 0.0, 0.2)).ok
    assert service.cancel_morph_correction(session_id)[0].ok
    state = service.cached_morph_state(session_id)
    assert state.manual_values == preset.manual_values and state.values == preset.values
    _same_mesh(_positions_for(service, session_id), before)
    assert service.begin_morph_correction(session_id, "volume", (2,))[0].ok
    assert _sculpt(service, session_id, {2: (0,)}, (0.0, 0.0, 0.2)).ok
    assert service.save_morph_correction(session_id)[0].ok
    state = service.cached_morph_state(session_id)
    assert state.manual_values == preset.manual_values and state.values == preset.values
    assert _positions(service, session_id, 2)[0][2] == pytest.approx(before[2][0][2] + 0.07, abs=1e-5)
    assert service.undo(session_id).ok
    assert service.cached_morph_state(session_id).correction_definition_id == "volume"
    assert service.cancel_morph_correction(session_id)[0].ok
    _same_mesh(_positions_for(service, session_id), before)


def test_rejected_comparison_upload_restores_metadata_geometry_and_history(resident, monkeypatch):
    from cdmw.services import mesh_service_morph
    service, open_session = resident
    session_id = _corrected_outfit(service, open_session)
    before = _positions_for(service, session_id)
    state_before = service.cached_morph_state(session_id)
    history_before = len(service._session(session_id).undo_stack)
    original = mesh_service_morph.native_mesh_editor_session_command

    def reject_upload(command, *args, **kwargs):
        if command == "morph_upload":
            return {"status": "error", "error": "Rejected test upload"}
        return original(command, *args, **kwargs)

    monkeypatch.setattr(mesh_service_morph, "native_mesh_editor_session_command", reject_upload)
    with pytest.raises(RuntimeError, match="Rejected test upload"):
        service.set_morph_corrections_enabled(session_id, False)
    assert service.cached_morph_state(session_id).corrections_enabled
    assert service.cached_morph_state(session_id).definitions == state_before.definitions
    assert len(service._session(session_id).undo_stack) == history_before
    _same_mesh(_positions_for(service, session_id), before)
