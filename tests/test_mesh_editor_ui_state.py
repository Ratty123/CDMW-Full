from __future__ import annotations

from dataclasses import replace

import pytest

from cdmw.domain.mesh.authoring_capability import MeshOutputPolicy
from cdmw.domain.mesh.ui_state import (
    MeshEditorRecoveryStatus,
    MeshEditorSelectionSummary,
    MeshEditorSynchronizationStatus,
    MeshEditorUiEvent,
    MeshEditorUiEventKind,
    MeshEditorUiInvariantError,
    MeshEditorUiState,
    assert_mesh_editor_ui_invariants,
    mesh_editor_ui_invariant_errors,
)
from cdmw.domain.mesh.ui_state_reducer import (
    reduce_mesh_editor_ui_state,
    replay_mesh_editor_ui_events,
)


MUTATIONS = frozenset({"delete", "extrude"})
SAFE_ACTIONS = frozenset({"select_parts", "mode_edit", "delete"})


def _open(session_id: str = "session-a", generation: int = 3) -> MeshEditorUiState:
    return reduce_mesh_editor_ui_state(
        MeshEditorUiState(),
        MeshEditorUiEvent.session_opened(
            session_id,
            process_generation=generation,
            mode="edit",
        ),
        strict=True,
    )


def _service_event(
    revision: int,
    *,
    session_id: str = "session-a",
    output_policy: MeshOutputPolicy = MeshOutputPolicy.EXACT_GAME_ASSET,
    authoring: bool = True,
    eligible: frozenset[str] = SAFE_ACTIONS,
    blocked: frozenset[str] = frozenset({"extrude"}),
) -> MeshEditorUiEvent:
    return MeshEditorUiEvent(
        MeshEditorUiEventKind.SERVICE_OBSERVED,
        session_id=session_id,
        service_revision=revision,
        mode="edit",
        active_tool="select_parts",
        element_type="face",
        selection_shape="lasso",
        selection=MeshEditorSelectionSummary(face_count=2),
        output_policy=output_policy.value,
        policy_authoring_enabled=authoring,
        writer_capabilities=frozenset({"delete"}),
        eligible_actions=eligible,
        visible_actions=eligible | blocked,
        blocked_actions=blocked,
        action_blockers=tuple((action, f"{action} blocked") for action in sorted(blocked)),
        mutation_actions=MUTATIONS,
    )


def _renderer_event(
    revision: int,
    *,
    pending_request_id: int = 0,
    recovery: MeshEditorRecoveryStatus = MeshEditorRecoveryStatus.IDLE,
    session_id: str = "session-a",
    generation: int = 3,
) -> MeshEditorUiEvent:
    return MeshEditorUiEvent(
        MeshEditorUiEventKind.RENDERER_OBSERVED,
        session_id=session_id,
        renderer_session_id=session_id,
        process_generation=generation,
        renderer_revision=revision,
        last_acked_revision=revision,
        pending_request_id=pending_request_id,
        recovery_status=recovery,
        renderer_capabilities=frozenset({"resident_mutation_batch_v3"}),
    )


@pytest.mark.parametrize(
    ("state", "expected_error"),
    (
        (
            MeshEditorUiState(session_id="s", service_revision=1, renderer_revision=2),
            "renderer_revision_exceeds_service_revision",
        ),
        (
            MeshEditorUiState(
                session_id="s",
                service_revision=2,
                renderer_revision=1,
                last_acked_revision=2,
            ),
            "last_acked_revision_exceeds_renderer_revision",
        ),
        (
            MeshEditorUiState(
                session_id="s",
                process_generation=2,
                pending_request_id=7,
                pending_request_session_id="old",
                pending_request_process_generation=2,
            ),
            "pending_request_session_mismatch",
        ),
        (
            MeshEditorUiState(
                session_id="s",
                process_generation=2,
                pending_request_id=7,
                pending_request_session_id="s",
                pending_request_process_generation=1,
            ),
            "pending_request_process_generation_mismatch",
        ),
        (
            MeshEditorUiState(session_id="s", service_revision=1, validation_revision=2),
            "validation_revision_exceeds_service_revision",
        ),
        (
            MeshEditorUiState(
                session_id="s",
                service_revision=2,
                validation_revision=1,
                output_gate_requested=True,
            ),
            "validation_gated_output_revision_mismatch",
        ),
        (
            MeshEditorUiState(
                session_id="s",
                output_policy=MeshOutputPolicy.EXACT_GAME_ASSET.value,
                eligible_actions=frozenset({"extrude"}),
                blocked_actions=frozenset({"extrude"}),
            ),
            "exact_policy_enables_blocked_action",
        ),
        (
            MeshEditorUiState(
                session_id="s",
                output_policy=MeshOutputPolicy.READ_ONLY.value,
                eligible_actions=frozenset({"delete"}),
                mutation_actions=MUTATIONS,
            ),
            "read_only_policy_enables_mutation",
        ),
        (
            MeshEditorUiState(
                session_id="s",
                renderer_session_id="old",
                service_revision=1,
                renderer_revision=1,
            ),
            "renderer_session_mismatch",
        ),
        (
            MeshEditorUiState(session_id="", service_revision=1),
            "closed_session_retains_authoring_authority",
        ),
    ),
)
def test_invalid_authority_state_has_one_direct_invariant(
    state: MeshEditorUiState,
    expected_error: str,
) -> None:
    assert expected_error in mesh_editor_ui_invariant_errors(state)
    with pytest.raises(MeshEditorUiInvariantError):
        assert_mesh_editor_ui_invariants(state)


@pytest.mark.parametrize(
    "recovery",
    (MeshEditorRecoveryStatus.ACTIVE, MeshEditorRecoveryStatus.FAILED),
)
def test_recovery_state_always_disables_authoring(
    recovery: MeshEditorRecoveryStatus,
) -> None:
    state = replace(
        _open(),
        service_revision=1,
        renderer_revision=1,
        last_acked_revision=1,
        policy_authoring_enabled=True,
        output_policy=MeshOutputPolicy.EXACT_GAME_ASSET.value,
        recovery_status=recovery,
        synchronization_status=(
            MeshEditorSynchronizationStatus.RECOVERING
            if recovery is MeshEditorRecoveryStatus.ACTIVE
            else MeshEditorSynchronizationStatus.FAILED
        ),
    )

    assert not state.authoring_enabled
    assert "recovery_state_allows_authoring" not in mesh_editor_ui_invariant_errors(state)


def test_process_restart_invalidates_pending_renderer_request() -> None:
    state = reduce_mesh_editor_ui_state(_open(), _service_event(1), strict=True)
    state = reduce_mesh_editor_ui_state(
        state,
        _renderer_event(0, pending_request_id=41),
        strict=True,
    )

    restarted = reduce_mesh_editor_ui_state(
        state,
        MeshEditorUiEvent(
            MeshEditorUiEventKind.PROCESS_GENERATION_CHANGED,
            process_generation=4,
            renderer_capabilities=frozenset({"resident_mutation_batch_v3"}),
        ),
        strict=True,
    )

    assert restarted.pending_request_id == 0
    assert restarted.process_generation == 4
    assert restarted.renderer_session_id == ""
    assert not restarted.authoring_enabled


def test_session_switch_invalidates_old_renderer_state() -> None:
    state = reduce_mesh_editor_ui_state(_open(), _service_event(1), strict=True)
    state = reduce_mesh_editor_ui_state(state, _renderer_event(1), strict=True)

    switched = reduce_mesh_editor_ui_state(
        state,
        MeshEditorUiEvent.session_opened(
            "session-b",
            process_generation=state.process_generation,
            mode="edit",
        ),
        strict=True,
    )
    stale = reduce_mesh_editor_ui_state(
        switched,
        _renderer_event(1, session_id="session-a"),
        strict=True,
    )

    assert stale is switched
    assert switched.renderer_revision == 0
    assert switched.renderer_session_id == ""


def test_stale_worker_completion_is_ignored() -> None:
    state = reduce_mesh_editor_ui_state(_open(), _service_event(2), strict=True)
    stale = reduce_mesh_editor_ui_state(
        state,
        MeshEditorUiEvent(
            MeshEditorUiEventKind.REPORT_COMPLETED,
            session_id="old-session",
            process_generation=3,
            report_kind="validation",
            report_revision=2,
            report_ok=True,
        ),
        strict=True,
    )

    assert stale is state
    assert stale.validation_revision is None


def test_recovery_failure_disables_every_mutation_action() -> None:
    state = reduce_mesh_editor_ui_state(_open(), _service_event(1), strict=True)
    state = reduce_mesh_editor_ui_state(
        state,
        _renderer_event(0, recovery=MeshEditorRecoveryStatus.FAILED),
        strict=True,
    )

    assert not state.authoring_enabled
    assert "delete" not in state.enabled_actions
    assert state.synchronization_status is MeshEditorSynchronizationStatus.FAILED


def test_successful_recovery_reenables_only_at_revision_equality() -> None:
    state = reduce_mesh_editor_ui_state(_open(), _service_event(2), strict=True)
    recovering = reduce_mesh_editor_ui_state(
        state,
        _renderer_event(1, recovery=MeshEditorRecoveryStatus.ACTIVE),
        strict=True,
    )
    still_behind = reduce_mesh_editor_ui_state(
        recovering,
        _renderer_event(1),
        strict=True,
    )
    synchronized = reduce_mesh_editor_ui_state(
        still_behind,
        _renderer_event(2),
        strict=True,
    )

    assert not recovering.authoring_enabled
    assert not still_behind.authoring_enabled
    assert synchronized.authoring_enabled
    assert synchronized.action_enabled("delete")


def test_read_only_mode_never_enables_mutation() -> None:
    state = reduce_mesh_editor_ui_state(
        _open(),
        _service_event(
            0,
            output_policy=MeshOutputPolicy.READ_ONLY,
            authoring=False,
            eligible=frozenset({"select_parts"}),
            blocked=MUTATIONS,
        ),
        strict=True,
    )

    assert state.enabled_actions == frozenset({"select_parts"})
    assert not state.authoring_enabled


def test_exact_mode_never_enables_blocked_action() -> None:
    state = reduce_mesh_editor_ui_state(_open(), _service_event(0), strict=True)

    assert "extrude" in state.blocked_actions
    assert "extrude" not in state.enabled_actions
    assert state.action_enabled("delete")


def test_report_revision_cannot_move_backward_due_to_late_completion() -> None:
    state = reduce_mesh_editor_ui_state(_open(), _service_event(3), strict=True)
    current = reduce_mesh_editor_ui_state(
        state,
        MeshEditorUiEvent(
            MeshEditorUiEventKind.REPORT_COMPLETED,
            session_id="session-a",
            process_generation=3,
            report_kind="validation",
            report_revision=3,
            report_ok=True,
        ),
        strict=True,
    )
    late = reduce_mesh_editor_ui_state(
        current,
        MeshEditorUiEvent(
            MeshEditorUiEventKind.REPORT_COMPLETED,
            session_id="session-a",
            process_generation=3,
            report_kind="validation",
            report_revision=2,
            report_ok=True,
        ),
        strict=True,
    )

    assert late is current
    assert late.validation_revision == 3
    assert late.validation_gated_output_enabled


def test_selection_only_service_revision_preserves_geometry_report_authority() -> None:
    state = reduce_mesh_editor_ui_state(_open(), _service_event(1), strict=True)
    validated = reduce_mesh_editor_ui_state(
        state,
        MeshEditorUiEvent(
            MeshEditorUiEventKind.REPORT_COMPLETED,
            session_id="session-a",
            process_generation=3,
            report_kind="validation",
            report_revision=1,
            report_ok=True,
        ),
        strict=True,
    )
    selection_only = reduce_mesh_editor_ui_state(
        validated,
        replace(_service_event(2), geometry_revision=1),
        strict=True,
    )
    geometry_edit = reduce_mesh_editor_ui_state(
        selection_only,
        replace(_service_event(3), geometry_revision=2),
        strict=True,
    )

    assert selection_only.validation_gated_output_enabled
    assert selection_only.service_revision == 2
    assert selection_only.geometry_revision == 1
    assert not geometry_edit.validation_gated_output_enabled


def test_close_clears_authority_without_blocking_warm_helper_next_session() -> None:
    state = reduce_mesh_editor_ui_state(_open(), _service_event(1), strict=True)
    state = reduce_mesh_editor_ui_state(state, _renderer_event(1), strict=True)
    closed = reduce_mesh_editor_ui_state(
        state,
        MeshEditorUiEvent.session_closed(),
        strict=True,
    )
    reopened = reduce_mesh_editor_ui_state(
        closed,
        MeshEditorUiEvent.session_opened(
            "session-b",
            process_generation=closed.process_generation,
            mode="edit",
        ),
        strict=True,
    )

    assert closed.session_id == ""
    assert closed.process_generation == 3
    assert closed.pending_request_id == 0
    assert reopened.session_id == "session-b"
    assert reopened.process_generation == 3
    assert reopened.synchronization_status is MeshEditorSynchronizationStatus.SYNCHRONIZED


def test_deterministic_replay_reconstructs_ui_state() -> None:
    events = (
        MeshEditorUiEvent.session_opened("session-a", process_generation=3, mode="edit"),
        _service_event(1),
        _renderer_event(0, pending_request_id=7),
        _renderer_event(1),
        MeshEditorUiEvent(
            MeshEditorUiEventKind.REPORT_COMPLETED,
            session_id="session-a",
            process_generation=3,
            report_kind="validation",
            report_revision=1,
            report_ok=True,
        ),
    )

    first = replay_mesh_editor_ui_events(events)
    second = replay_mesh_editor_ui_events(events)

    assert first == second
    assert first.authoring_enabled
    assert first.validation_gated_output_enabled
    assert first.selection.face_count == 2


def test_invalid_renderer_transition_enters_safe_recovery_in_production_mode() -> None:
    state = reduce_mesh_editor_ui_state(_open(), _service_event(1), strict=True)
    malformed = _renderer_event(2)

    with pytest.raises(MeshEditorUiInvariantError):
        reduce_mesh_editor_ui_state(state, malformed, strict=True)
    safe = reduce_mesh_editor_ui_state(state, malformed, strict=False)

    assert safe.recovery_status is MeshEditorRecoveryStatus.FAILED
    assert safe.recovery_error_code == "mesh_editor_ui_state_invariant_failed"
    assert "renderer_revision_exceeds_service_revision" in safe.invariant_errors
    assert not safe.authoring_enabled

    restarted = reduce_mesh_editor_ui_state(
        safe,
        MeshEditorUiEvent(
            MeshEditorUiEventKind.PROCESS_GENERATION_CHANGED,
            process_generation=4,
        ),
        strict=True,
    )
    assert restarted.recovery_status is MeshEditorRecoveryStatus.FAILED
    assert "synchronization failed" in restarted.authoring_blocker.lower()
    assert not restarted.authoring_enabled
