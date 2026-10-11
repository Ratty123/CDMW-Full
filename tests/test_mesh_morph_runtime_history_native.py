"""Runtime-only body history stays independent of other sessions' saved files."""

from __future__ import annotations

import pytest

from cdmw.domain.mesh import MeshEditSelection
from tests.test_mesh_morph_authoring_native import resident
from tests.test_mesh_morph_body_workflow_native import (
    _activate,
    _assert_snapshot,
    _body_mesh,
    _open_body,
    _set_asymmetric_layers,
    _snapshot,
)


def _profile_files(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*") if path.is_file()
    }


def _runtime_snapshot(service, session_id):
    return _snapshot(service, session_id), service.cached_morph_state(session_id).refit


def _assert_runtime_snapshot(service, session_id, snapshot):
    _assert_snapshot(service, session_id, snapshot[0])
    assert service.cached_morph_state(session_id).refit == snapshot[1]


@pytest.mark.parametrize("operation", ["macro", "preset", "reset", "profile", "influence"])
def test_runtime_history_undo_redo_preserves_another_sessions_saved_presets(resident, operation):
    service, open_session, first, mesh, profile = _open_body(resident)
    _set_asymmetric_layers(service, first)
    preset = service.save_morph_preset(first, "first-session-preset", "First Session")
    assert service.set_morph_macro(first, "hip_thigh_transition", 10.0)[0].ok
    if operation == "profile":
        # Profile switches require a neutral evaluation. Keep the zero-valued
        # linked preview's independent side offsets in its retained layers.
        assert service.reset_morph_macros(first)[0].ok
        assert service.set_morph_side_value(first, "thigh_size", 0.0)[0].ok
    second = open_session(_body_mesh())
    _activate(service, second, profile, bind=True)
    before = _runtime_snapshot(service, first)

    if operation == "macro":
        result = service.set_morph_macro(first, "hip_thigh_transition", 40.0)[0]
    elif operation == "preset":
        result = service.apply_cached_morph_preset(first, preset.preset_id)[0]
    elif operation == "reset":
        result = service.reset_morph(first)[0]
    elif operation == "profile":
        result = service.activate_cached_morph_profile(first, profile.profile_id)[0]
    else:
        result = service.set_refit_vertex_influence(
            first, weight=0.25,
            selection=MeshEditSelection.from_maps(
                vertices_by_submesh={1: tuple(range(len(mesh.submeshes[1].vertices)))},
            ),
        )[0]
    assert result.ok
    changed = _runtime_snapshot(service, first)
    assert changed != before
    first_session = service._session(first)
    counts = len(first_session.undo_stack), len(first_session.redo_stack)

    service.save_morph_preset(second, "second-session-preset", "Second Session")
    files = _profile_files(service._profile_root())
    assert service.undo(first).ok
    _assert_runtime_snapshot(service, first, before)
    assert _profile_files(service._profile_root()) == files
    assert len(first_session.undo_stack) == counts[0] - 1
    assert len(first_session.redo_stack) == counts[1] + 1

    service.save_morph_preset(second, "second-session-another", "Another Second Session Preset")
    files = _profile_files(service._profile_root())
    other_session = _runtime_snapshot(service, second)
    assert service.redo(first).ok
    _assert_runtime_snapshot(service, first, changed)
    _assert_runtime_snapshot(service, second, other_session)
    assert _profile_files(service._profile_root()) == files
    assert (len(first_session.undo_stack), len(first_session.redo_stack)) == counts


@pytest.mark.parametrize("operation", ["preset", "setup"])
def test_file_changing_history_still_refuses_another_sessions_later_save(resident, operation):
    service, open_session, first, _mesh, profile = _open_body(resident)
    _set_asymmetric_layers(service, first)
    second = open_session(_body_mesh())
    _activate(service, second, profile, bind=True)
    if operation == "preset":
        service.save_morph_preset(first, "owned-preset", "Owned Preset")
    else:
        assert service.save_refit_setup(first, "Owned Setup")[0].ok
    first_session = service._session(first)
    before = _runtime_snapshot(service, first)
    counts = len(first_session.undo_stack), len(first_session.redo_stack)
    service.save_morph_preset(second, "other-preset", "Other Preset")
    files = _profile_files(service._profile_root())

    with pytest.raises(RuntimeError, match="Morph profiles changed outside Mesh Editor"):
        service.undo(first)

    _assert_runtime_snapshot(service, first, before)
    assert (len(first_session.undo_stack), len(first_session.redo_stack)) == counts
    assert _profile_files(service._profile_root()) == files
