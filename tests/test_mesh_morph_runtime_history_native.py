"""Runtime-only body history stays independent of other sessions' saved files."""

from __future__ import annotations

import pytest

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.modding import mesh_native_core
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


def test_twenty_body_edits_undo_through_native_setup_and_redo_every_step(resident):
    service, _open_session, session_id, _mesh, _profile = _open_body(resident)
    session = service._session(session_id)
    initial = _runtime_snapshot(service, session_id)
    setup_count = len(session.undo_stack)
    assert setup_count == 3
    states = [initial]
    for value in range(1, 21):
        assert service.set_morph_macro(session_id, "hip_thigh_transition", value)[0].ok
        states.append(_runtime_snapshot(service, session_id))

    for expected in reversed(states[:-1]):
        assert service.undo(session_id).ok
        _assert_runtime_snapshot(service, session_id, expected)
    for _ in range(setup_count):
        assert service.undo(session_id).ok
    assert not session.undo_stack
    assert len(session.redo_stack) == setup_count + 20

    for _ in range(setup_count):
        assert service.redo(session_id).ok
    _assert_runtime_snapshot(service, session_id, initial)
    for expected in states[1:]:
        assert service.redo(session_id).ok
        _assert_runtime_snapshot(service, session_id, expected)
    assert len(session.undo_stack) == setup_count + 20
    assert not session.redo_stack


def test_native_edits_between_morph_snapshots_keep_redo_and_branching(resident):
    service, _open_session, session_id, _mesh, _profile = _open_body(resident)
    session = service._session(session_id)
    states = [_runtime_snapshot(service, session_id)]
    for value in (10.0, 20.0):
        assert service.set_morph_macro(session_id, "hip_thigh_transition", value)[0].ok
        states.append(_runtime_snapshot(service, session_id))
        assert service.apply_command(session_id, MeshEditCommand(
            "transform",
            selection=MeshEditSelection.from_maps(vertices_by_submesh={2: (0, 1, 2)}),
            params={"delta": (0.1, 0.0, 0.0)},
            mode="edit",
        )).ok
        states.append(_runtime_snapshot(service, session_id))
    count = len(session.undo_stack)
    for expected in reversed(states[:-1]):
        assert service.undo(session_id).ok
        _assert_runtime_snapshot(service, session_id, expected)
    assert len(session.redo_stack) == 4
    for expected in states[1:]:
        assert service.redo(session_id).ok
        _assert_runtime_snapshot(service, session_id, expected)
    assert len(session.undo_stack) == count

    assert service.undo(session_id).ok
    assert service.undo(session_id).ok
    assert service.set_morph_macro(session_id, "hip_thigh_transition", 35.0)[0].ok
    branched = _runtime_snapshot(service, session_id)
    assert not session.redo_stack
    assert service.redo(session_id).status == "noop"
    assert service.undo(session_id).ok
    _assert_runtime_snapshot(service, session_id, states[2])
    assert service.redo(session_id).ok
    _assert_runtime_snapshot(service, session_id, branched)


def test_morph_history_keeps_its_budget_and_native_snapshot_storage(resident):
    from dataclasses import replace
    from cdmw.services.mesh_service_history import _history_snapshot_retained_bytes

    service, _open_session, session_id, _mesh, _profile = _open_body(resident)
    session = service._session(session_id)
    assert service.set_morph_macro(session_id, "hip_thigh_transition", 10.0)[0].ok
    marker = session.undo_stack[-1]
    descriptor = marker.morph_session_state.native_snapshot
    native_bytes = descriptor["history_retained_bytes"]
    without_history = replace(
        marker,
        retained_bytes=0,
        morph_session_state=replace(
            marker.morph_session_state,
            native_snapshot={**descriptor, "history_retained_bytes": 0},
        ),
    )
    assert native_bytes > 0
    # The integer's Python allocation can differ; the resident payload must
    # still be charged, rather than counted as a disk-backed runtime file.
    assert _history_snapshot_retained_bytes(marker) - _history_snapshot_retained_bytes(
        without_history
    ) >= native_bytes
    service.max_history = 4
    for value in range(11, 17):
        assert service.set_morph_macro(session_id, "hip_thigh_transition", value)[0].ok
    assert len(session.undo_stack) == 4
    final = _runtime_snapshot(service, session_id)
    for _ in range(4):
        assert service.undo(session_id).ok
    assert not session.undo_stack
    for _ in range(4):
        assert service.redo(session_id).ok
    _assert_runtime_snapshot(service, session_id, final)


def test_failed_morph_restore_retains_native_history_for_retry(resident, monkeypatch):
    from cdmw.services import mesh_service_morph

    service, _open_session, session_id, _mesh, _profile = _open_body(resident)
    assert service.set_morph_macro(session_id, "hip_thigh_transition", 20.0)[0].ok
    before = _runtime_snapshot(service, session_id)
    session = service._session(session_id)
    markers = list(session.undo_stack)
    restore = mesh_service_morph.restore_native_mesh_editor_morph_runtime_snapshot
    calls = 0

    def reject_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        return restore(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(
            mesh_service_morph, "restore_native_mesh_editor_morph_runtime_snapshot", reject_once
        )
        with pytest.raises(RuntimeError, match="snapshot restore failed"):
            service.undo(session_id)
    assert session.undo_stack == markers
    assert not session.redo_stack
    _assert_runtime_snapshot(service, session_id, before)
    native = mesh_native_core.summarize_native_mesh_editor_session(session_id)
    assert session.native_history_undo_count == native["history_undo_count"]
    assert session.native_history_redo_count == native["history_redo_count"]
    for _ in range(len(markers)):
        assert service.undo(session_id).ok
    assert not session.undo_stack


def test_native_morph_history_snapshot_refuses_transfer_and_disposes_owned_history(resident):
    from pathlib import Path

    service, open_session, session_id, _mesh, profile = _open_body(resident)
    target = open_session(_body_mesh())
    _activate(service, target, profile, bind=True)
    summary = mesh_native_core.summarize_native_mesh_editor_session(session_id)
    descriptor = mesh_native_core.create_native_mesh_editor_morph_runtime_snapshot(
        session_id, history_counts=(summary["history_undo_count"], 0),
    )
    assert descriptor is not None and descriptor["history_captured"]
    path = Path(descriptor["path"])
    data = path.read_bytes()
    try:
        target_before = mesh_native_core.summarize_native_mesh_editor_session(target)
        assert mesh_native_core.restore_native_mesh_editor_morph_runtime_snapshot(
            target, descriptor,
        ) is None
        assert "belongs to another session" in mesh_native_core.last_native_mesh_core_job_error()
        target_after = mesh_native_core.summarize_native_mesh_editor_session(target)
        assert target_after["edit_revision"] == target_before["edit_revision"]
        assert target_after["history_undo_count"] == target_before["history_undo_count"]
        restored = mesh_native_core.restore_native_mesh_editor_morph_runtime_snapshot(
            session_id, descriptor,
        )
        assert restored is not None
        assert restored["history_undo_count"] == summary["history_undo_count"]
        assert restored["history_cleared"] is False
    finally:
        assert mesh_native_core.dispose_native_mesh_editor_morph_runtime_snapshot(descriptor)
    # Recreating an otherwise valid runtime file must not resurrect disposed
    # resident history, or let a stale descriptor overwrite the current stack.
    path.write_bytes(data)
    try:
        assert mesh_native_core.restore_native_mesh_editor_morph_runtime_snapshot(
            session_id, descriptor,
        ) is None
        assert "history is unavailable" in mesh_native_core.last_native_mesh_core_job_error()
        after = mesh_native_core.summarize_native_mesh_editor_session(session_id)
        assert after["history_undo_count"] == summary["history_undo_count"]
    finally:
        path.unlink()


def test_undo_first_morph_authoring_preserves_earlier_geometry_history(resident):
    from tests.test_mesh_morph_service import _author_command

    service, open_session = resident
    session_id = open_session()
    original = tuple(service.working_mesh(session_id, clone=True).submeshes[0].vertices)
    assert service.apply_command(session_id, MeshEditCommand(
        "transform",
        selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1, 2)}),
        params={"delta": (0.1, 0.0, 0.0)},
        mode="edit",
    )).ok
    assert service.apply_command(session_id, _author_command()).ok
    count = len(service._session(session_id).undo_stack)
    for _ in range(count):
        assert service.undo(session_id).ok
    assert tuple(service.working_mesh(session_id, clone=True).submeshes[0].vertices) == original
    for _ in range(count):
        assert service.redo(session_id).ok
    assert service.cached_morph_state(session_id).profile_id == "resident-body"


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
