"""Pure transition functions for :mod:`cdmw.domain.mesh.ui_state`."""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from cdmw.domain.mesh.authoring_capability import MeshOutputPolicy
from cdmw.domain.mesh.ui_state import (
    MeshEditorRecoveryStatus,
    MeshEditorSynchronizationStatus,
    MeshEditorUiEvent,
    MeshEditorUiEventKind,
    MeshEditorUiInvariantError,
    MeshEditorUiState,
    mesh_editor_ui_invariant_errors,
)


def reduce_mesh_editor_ui_state(
    state: MeshEditorUiState,
    event: MeshEditorUiEvent,
    *,
    strict: bool = False,
) -> MeshEditorUiState:
    candidate = _apply_mesh_editor_ui_event(state, event)
    if candidate is state or candidate == state:
        return state
    candidate = _with_synchronization_status(
        replace(candidate, transition_sequence=state.transition_sequence + 1)
    )
    errors = mesh_editor_ui_invariant_errors(candidate)
    if not errors:
        return candidate
    if strict:
        raise MeshEditorUiInvariantError(errors)
    return _safe_recovery_state(candidate, errors)


def replay_mesh_editor_ui_events(
    events: Iterable[MeshEditorUiEvent],
    *,
    initial: MeshEditorUiState | None = None,
    strict: bool = True,
) -> MeshEditorUiState:
    state = initial or MeshEditorUiState()
    for event in events:
        state = reduce_mesh_editor_ui_state(state, event, strict=strict)
    return state


def _apply_mesh_editor_ui_event(
    state: MeshEditorUiState,
    event: MeshEditorUiEvent,
) -> MeshEditorUiState:
    if event.kind in {
        MeshEditorUiEventKind.SESSION_OPENED,
        MeshEditorUiEventKind.SESSION_CLOSED,
    }:
        return _apply_session_event(state, event)
    if event.kind is MeshEditorUiEventKind.PROCESS_GENERATION_CHANGED:
        return _apply_process_event(state, event)
    if event.kind is MeshEditorUiEventKind.SERVICE_OBSERVED:
        return _apply_service_event(state, event)
    if event.kind is MeshEditorUiEventKind.RENDERER_OBSERVED:
        return _apply_renderer_event(state, event)
    if event.kind is MeshEditorUiEventKind.INTERACTION_CHANGED:
        return _apply_interaction_event(state, event)
    if event.kind is MeshEditorUiEventKind.REPORT_COMPLETED:
        return _apply_report_event(state, event)
    return state


def _apply_session_event(
    state: MeshEditorUiState,
    event: MeshEditorUiEvent,
) -> MeshEditorUiState:
    if event.kind is MeshEditorUiEventKind.SESSION_CLOSED:
        return MeshEditorUiState(
            process_generation=state.process_generation,
            renderer_capabilities=state.renderer_capabilities,
            transition_sequence=state.transition_sequence,
        )
    if not event.session_id:
        return state
    return MeshEditorUiState(
        session_id=event.session_id,
        process_generation=max(state.process_generation, event.process_generation),
        mode=event.mode or "object",
        synchronization_status=MeshEditorSynchronizationStatus.SYNCHRONIZED,
        renderer_capabilities=state.renderer_capabilities,
        transition_sequence=state.transition_sequence,
    )


def _apply_process_event(
    state: MeshEditorUiState,
    event: MeshEditorUiEvent,
) -> MeshEditorUiState:
    generation = max(0, event.process_generation)
    if generation <= state.process_generation:
        return state
    return replace(
        state,
        process_generation=generation,
        renderer_session_id="",
        renderer_revision=0,
        last_acked_revision=0,
        pending_request_id=0,
        pending_request_session_id="",
        pending_request_process_generation=0,
        pending_base_revision=0,
        pending_target_revision=0,
        recovery_status=(
            MeshEditorRecoveryStatus.FAILED
            if state.invariant_errors
            else MeshEditorRecoveryStatus.IDLE
        ),
        renderer_capabilities=event.renderer_capabilities,
        output_gate_requested=False,
    )


def _apply_service_event(
    state: MeshEditorUiState,
    event: MeshEditorUiEvent,
) -> MeshEditorUiState:
    geometry_revision = (
        max(0, event.geometry_revision)
        if event.geometry_revision >= 0
        else event.service_revision
    )
    if (
        event.session_id != state.session_id
        or event.service_revision < state.service_revision
        or geometry_revision < state.geometry_revision
    ):
        return state
    renderer_revision = state.renderer_revision
    last_acked_revision = state.last_acked_revision
    if not state.renderer_session_id and state.process_generation == 0:
        renderer_revision = event.service_revision
        last_acked_revision = event.service_revision
    return replace(
        state,
        service_revision=event.service_revision,
        geometry_revision=geometry_revision,
        renderer_revision=renderer_revision,
        last_acked_revision=last_acked_revision,
        mode=event.mode or state.mode,
        active_tool=event.active_tool or state.active_tool,
        element_type=event.element_type or state.element_type,
        selection_shape=event.selection_shape or state.selection_shape,
        selection=event.selection or state.selection,
        undo_count=(max(0, event.undo_count) if event.undo_count >= 0 else state.undo_count),
        redo_count=(max(0, event.redo_count) if event.redo_count >= 0 else state.redo_count),
        output_policy=event.output_policy or state.output_policy,
        mesh_format=event.mesh_format or state.mesh_format,
        lod_index=(max(0, event.lod_index) if event.lod_index >= 0 else state.lod_index),
        output_destination=event.output_destination,
        output_destination_ready=bool(event.output_destination_ready),
        exact_write_status=event.exact_write_status or state.exact_write_status,
        policy_reason=event.policy_reason,
        policy_authoring_enabled=bool(event.policy_authoring_enabled),
        writer_capabilities=event.writer_capabilities,
        eligible_actions=event.eligible_actions,
        visible_actions=event.visible_actions,
        blocked_actions=event.blocked_actions,
        action_blockers=event.action_blockers,
        mutation_actions=event.mutation_actions,
        output_gate_requested=(
            state.output_gate_requested
            and state.validation_revision
            == geometry_revision
        ),
    )


def _apply_renderer_event(
    state: MeshEditorUiState,
    event: MeshEditorUiEvent,
) -> MeshEditorUiState:
    if state.invariant_errors:
        return state
    if (
        event.session_id != state.session_id
        or event.process_generation != state.process_generation
    ):
        return state
    if (
        event.last_acked_revision < state.last_acked_revision
        or event.renderer_revision < state.renderer_revision
    ):
        return state
    pending_id = max(0, event.pending_request_id)
    return replace(
        state,
        renderer_session_id=event.renderer_session_id or event.session_id,
        renderer_revision=max(0, event.renderer_revision),
        last_acked_revision=max(0, event.last_acked_revision),
        pending_request_id=pending_id,
        pending_request_session_id=event.session_id if pending_id else "",
        pending_request_process_generation=event.process_generation if pending_id else 0,
        pending_base_revision=(max(0, event.pending_base_revision) if pending_id else 0),
        pending_target_revision=(max(0, event.pending_target_revision) if pending_id else 0),
        recovery_status=event.recovery_status or MeshEditorRecoveryStatus.IDLE,
        renderer_capabilities=(
            event.renderer_capabilities
            if event.renderer_capabilities
            else state.renderer_capabilities
        ),
    )


def _apply_interaction_event(
    state: MeshEditorUiState,
    event: MeshEditorUiEvent,
) -> MeshEditorUiState:
    if event.session_id and event.session_id != state.session_id:
        return state
    return replace(
        state,
        mode=event.mode or state.mode,
        active_tool=event.active_tool or state.active_tool,
        element_type=event.element_type or state.element_type,
        selection_shape=event.selection_shape or state.selection_shape,
        selection=event.selection or state.selection,
    )


def _apply_report_event(
    state: MeshEditorUiState,
    event: MeshEditorUiEvent,
) -> MeshEditorUiState:
    if (
        event.session_id != state.session_id
        or event.process_generation != state.process_generation
        or event.report_revision < 0
    ):
        return state
    report_kind = event.report_kind.strip().lower()
    if report_kind == "validation":
        if state.validation_revision is not None and event.report_revision < state.validation_revision:
            return state
        return replace(
            state,
            validation_revision=event.report_revision,
            output_gate_requested=bool(
                event.report_ok and event.report_revision == state.geometry_revision
            ),
        )
    if report_kind == "rebuild":
        if (
            state.rebuild_report_revision is not None
            and event.report_revision < state.rebuild_report_revision
        ):
            return state
        return replace(state, rebuild_report_revision=event.report_revision)
    return state


def _with_synchronization_status(state: MeshEditorUiState) -> MeshEditorUiState:
    if not state.session_id:
        status = MeshEditorSynchronizationStatus.CLOSED
    elif state.recovery_status is MeshEditorRecoveryStatus.FAILED:
        status = MeshEditorSynchronizationStatus.FAILED
    elif state.recovery_status is MeshEditorRecoveryStatus.ACTIVE:
        status = MeshEditorSynchronizationStatus.RECOVERING
    elif state.pending_request_id > 0:
        status = MeshEditorSynchronizationStatus.PENDING
    elif state.renderer_revision == state.service_revision:
        status = MeshEditorSynchronizationStatus.SYNCHRONIZED
    else:
        status = MeshEditorSynchronizationStatus.WAITING_RENDERER
    return replace(state, synchronization_status=status)


def _safe_recovery_state(
    state: MeshEditorUiState,
    errors: Iterable[str],
) -> MeshEditorUiState:
    error_tuple = tuple(str(error) for error in errors)
    service_revision = max(0, state.service_revision)
    geometry_revision = min(max(0, state.geometry_revision), service_revision)
    renderer_revision = min(max(0, state.renderer_revision), service_revision)
    last_acked_revision = min(max(0, state.last_acked_revision), renderer_revision)
    eligible = state.eligible_actions - state.blocked_actions
    if state.output_policy == MeshOutputPolicy.READ_ONLY.value:
        eligible -= state.mutation_actions
    return replace(
        state,
        renderer_session_id=(state.session_id if renderer_revision > 0 else ""),
        renderer_revision=renderer_revision,
        last_acked_revision=last_acked_revision,
        geometry_revision=geometry_revision,
        pending_request_id=0,
        pending_request_session_id="",
        pending_request_process_generation=0,
        pending_base_revision=0,
        pending_target_revision=0,
        recovery_status=MeshEditorRecoveryStatus.FAILED,
        synchronization_status=MeshEditorSynchronizationStatus.FAILED,
        validation_revision=(
            min(state.validation_revision, geometry_revision)
            if state.validation_revision is not None
            else None
        ),
        rebuild_report_revision=(
            min(state.rebuild_report_revision, geometry_revision)
            if state.rebuild_report_revision is not None
            else None
        ),
        eligible_actions=eligible,
        output_gate_requested=False,
        recovery_error_code="mesh_editor_ui_state_invariant_failed",
        invariant_errors=error_tuple,
    )


__all__ = ["reduce_mesh_editor_ui_state", "replay_mesh_editor_ui_events"]
