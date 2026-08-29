"""Immutable authoritative Mesh Editor UI state and lifecycle transitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from cdmw.domain.mesh.authoring_capability import MeshOutputPolicy


class MeshEditorSynchronizationStatus(str, Enum):
    CLOSED = "closed"
    SYNCHRONIZED = "synchronized"
    WAITING_RENDERER = "waiting_renderer"
    PENDING = "pending"
    RECOVERING = "recovering"
    FAILED = "failed"


class MeshEditorRecoveryStatus(str, Enum):
    IDLE = "idle"
    ACTIVE = "active"
    FAILED = "failed"


class MeshEditorUiEventKind(str, Enum):
    SESSION_OPENED = "session_opened"
    SESSION_CLOSED = "session_closed"
    PROCESS_GENERATION_CHANGED = "process_generation_changed"
    SERVICE_OBSERVED = "service_observed"
    RENDERER_OBSERVED = "renderer_observed"
    INTERACTION_CHANGED = "interaction_changed"
    REPORT_COMPLETED = "report_completed"


@dataclass(frozen=True, slots=True)
class MeshEditorSelectionSummary:
    vertex_count: int = 0
    edge_count: int = 0
    face_count: int = 0
    part_count: int = 0

    @property
    def empty(self) -> bool:
        return not any(
            (
                self.vertex_count,
                self.edge_count,
                self.face_count,
                self.part_count,
            )
        )


@dataclass(frozen=True, slots=True)
class MeshEditorUiEvent:
    kind: MeshEditorUiEventKind
    session_id: str = ""
    renderer_session_id: str = ""
    process_generation: int = -1
    service_revision: int = -1
    geometry_revision: int = -1
    renderer_revision: int = -1
    last_acked_revision: int = -1
    pending_request_id: int = 0
    pending_base_revision: int = -1
    pending_target_revision: int = -1
    mode: str = ""
    active_tool: str = ""
    element_type: str = ""
    selection_shape: str = ""
    selection: MeshEditorSelectionSummary | None = None
    undo_count: int = -1
    redo_count: int = -1
    recovery_status: MeshEditorRecoveryStatus | None = None
    report_kind: str = ""
    report_revision: int = -1
    report_ok: bool = False
    output_policy: str = ""
    mesh_format: str = ""
    lod_index: int = -1
    output_destination: str = ""
    output_destination_ready: bool | None = None
    exact_write_status: str = ""
    policy_reason: str = ""
    policy_authoring_enabled: bool | None = None
    writer_capabilities: frozenset[str] = frozenset()
    renderer_capabilities: frozenset[str] = frozenset()
    eligible_actions: frozenset[str] = frozenset()
    visible_actions: frozenset[str] = frozenset()
    blocked_actions: frozenset[str] = frozenset()
    action_blockers: tuple[tuple[str, str], ...] = ()
    mutation_actions: frozenset[str] = frozenset()

    @classmethod
    def session_opened(
        cls,
        session_id: str,
        *,
        process_generation: int,
        mode: str = "object",
    ) -> "MeshEditorUiEvent":
        return cls(
            MeshEditorUiEventKind.SESSION_OPENED,
            session_id=str(session_id or ""),
            process_generation=max(0, int(process_generation)),
            mode=str(mode or "object"),
        )

    @classmethod
    def session_closed(cls) -> "MeshEditorUiEvent":
        return cls(MeshEditorUiEventKind.SESSION_CLOSED)


@dataclass(frozen=True, slots=True)
class MeshEditorUiState:
    session_id: str = ""
    renderer_session_id: str = ""
    process_generation: int = 0
    service_revision: int = 0
    geometry_revision: int = 0
    renderer_revision: int = 0
    last_acked_revision: int = 0
    mode: str = "object"
    active_tool: str = ""
    element_type: str = "vertex"
    selection_shape: str = "brush"
    selection: MeshEditorSelectionSummary = field(default_factory=MeshEditorSelectionSummary)
    undo_count: int = 0
    redo_count: int = 0
    pending_request_id: int = 0
    pending_request_session_id: str = ""
    pending_request_process_generation: int = 0
    pending_base_revision: int = 0
    pending_target_revision: int = 0
    synchronization_status: MeshEditorSynchronizationStatus = MeshEditorSynchronizationStatus.CLOSED
    recovery_status: MeshEditorRecoveryStatus = MeshEditorRecoveryStatus.IDLE
    validation_revision: int | None = None
    rebuild_report_revision: int | None = None
    output_policy: str = MeshOutputPolicy.READ_ONLY.value
    mesh_format: str = ""
    lod_index: int = 0
    output_destination: str = ""
    output_destination_ready: bool = False
    exact_write_status: str = "read_only"
    policy_reason: str = ""
    writer_capabilities: frozenset[str] = frozenset()
    renderer_capabilities: frozenset[str] = frozenset()
    policy_authoring_enabled: bool = False
    eligible_actions: frozenset[str] = frozenset()
    visible_actions: frozenset[str] = frozenset()
    blocked_actions: frozenset[str] = frozenset()
    action_blockers: tuple[tuple[str, str], ...] = ()
    mutation_actions: frozenset[str] = frozenset()
    output_gate_requested: bool = False
    transition_sequence: int = 0
    recovery_error_code: str = ""
    invariant_errors: tuple[str, ...] = ()

    @property
    def authoring_enabled(self) -> bool:
        return bool(
            self.session_id
            and self.policy_authoring_enabled
            and self.output_policy != MeshOutputPolicy.READ_ONLY.value
            and not self.invariant_errors
            and self.recovery_status is MeshEditorRecoveryStatus.IDLE
            and self.pending_request_id == 0
            and self.synchronization_status is MeshEditorSynchronizationStatus.SYNCHRONIZED
            and self.renderer_revision == self.service_revision
        )

    @property
    def enabled_actions(self) -> frozenset[str]:
        if self.authoring_enabled:
            return self.eligible_actions
        return self.eligible_actions - self.mutation_actions

    @property
    def validation_gated_output_enabled(self) -> bool:
        return bool(
            self.output_gate_requested
            and self.validation_revision is not None
            and self.validation_revision == self.geometry_revision
        )

    @property
    def authoring_blocker(self) -> str:
        if not self.session_id:
            return "No Mesh Editor session is active."
        if self.invariant_errors or self.recovery_error_code:
            return "Mesh Editor renderer synchronization failed. Reload the session to continue editing."
        if self.recovery_status is MeshEditorRecoveryStatus.FAILED:
            return "Mesh Editor renderer synchronization failed. Reload the session to continue editing."
        if self.recovery_status is MeshEditorRecoveryStatus.ACTIVE:
            return "Mesh Editor is recovering renderer synchronization. Editing is temporarily unavailable."
        if self.pending_request_id > 0 or self.renderer_revision != self.service_revision:
            return "Mesh Editor is synchronizing with the renderer. Editing is temporarily unavailable."
        if self.output_policy == MeshOutputPolicy.READ_ONLY.value:
            return "This Mesh Editor session is read-only."
        if not self.policy_authoring_enabled:
            return "Authoring is unavailable for the active output policy."
        return ""

    def action_enabled(self, action_key: object) -> bool:
        return str(action_key or "").strip().lower() in self.enabled_actions

    def action_blocker(self, action_key: object) -> str:
        normalized = str(action_key or "").strip().lower()
        return dict(self.action_blockers).get(normalized, "")

    def as_payload(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "renderer_session_id": self.renderer_session_id,
            "process_generation": self.process_generation,
            "service_revision": self.service_revision,
            "geometry_revision": self.geometry_revision,
            "renderer_revision": self.renderer_revision,
            "last_acked_revision": self.last_acked_revision,
            "mode": self.mode,
            "active_tool": self.active_tool,
            "element_type": self.element_type,
            "selection_shape": self.selection_shape,
            "selection": {
                "vertex_count": self.selection.vertex_count,
                "edge_count": self.selection.edge_count,
                "face_count": self.selection.face_count,
                "part_count": self.selection.part_count,
                "empty": self.selection.empty,
            },
            "undo_count": self.undo_count,
            "redo_count": self.redo_count,
            "pending_request_id": self.pending_request_id,
            "pending_request_session_id": self.pending_request_session_id,
            "pending_request_process_generation": self.pending_request_process_generation,
            "pending_base_revision": self.pending_base_revision,
            "pending_target_revision": self.pending_target_revision,
            "synchronization_status": self.synchronization_status.value,
            "recovery_status": self.recovery_status.value,
            "validation_revision": self.validation_revision,
            "rebuild_report_revision": self.rebuild_report_revision,
            "output_policy": self.output_policy,
            "mesh_format": self.mesh_format,
            "lod_index": self.lod_index,
            "output_destination": self.output_destination,
            "output_destination_ready": self.output_destination_ready,
            "exact_write_status": self.exact_write_status,
            "policy_reason": self.policy_reason,
            "writer_capabilities": sorted(self.writer_capabilities),
            "renderer_capabilities": sorted(self.renderer_capabilities),
            "authoring_enabled": self.authoring_enabled,
            "validation_gated_output_enabled": self.validation_gated_output_enabled,
            "enabled_actions": sorted(self.enabled_actions),
            "visible_actions": sorted(self.visible_actions),
            "blocked_actions": sorted(self.blocked_actions),
            "action_blockers": dict(self.action_blockers),
            "transition_sequence": self.transition_sequence,
            "recovery_error_code": self.recovery_error_code,
            "invariant_errors": list(self.invariant_errors),
        }


class MeshEditorUiInvariantError(ValueError):
    def __init__(self, errors: Iterable[str]) -> None:
        self.errors = tuple(str(error) for error in errors)
        super().__init__("; ".join(self.errors))


def mesh_editor_ui_invariant_errors(state: MeshEditorUiState) -> tuple[str, ...]:
    errors: list[str] = []
    if state.renderer_revision > state.service_revision:
        errors.append("renderer_revision_exceeds_service_revision")
    if state.last_acked_revision > state.renderer_revision:
        errors.append("last_acked_revision_exceeds_renderer_revision")
    if state.recovery_status is not MeshEditorRecoveryStatus.IDLE and state.authoring_enabled:
        errors.append("recovery_state_allows_authoring")
    if state.pending_request_id > 0:
        if state.pending_request_session_id != state.session_id:
            errors.append("pending_request_session_mismatch")
        if state.pending_request_process_generation != state.process_generation:
            errors.append("pending_request_process_generation_mismatch")
        if not (
            0 <= state.pending_base_revision <= state.pending_target_revision <= state.service_revision
        ):
            errors.append("pending_request_revision_range_invalid")
    elif any(
        (
            state.pending_request_session_id,
            state.pending_request_process_generation,
            state.pending_base_revision,
            state.pending_target_revision,
        )
    ):
        errors.append("cleared_pending_request_retains_authority")
    for name, revision in (
        ("validation", state.validation_revision),
        ("rebuild_report", state.rebuild_report_revision),
    ):
        if revision is not None and revision > state.geometry_revision:
            errors.append(f"{name}_revision_exceeds_service_revision")
    if state.output_gate_requested and state.validation_revision != state.geometry_revision:
        errors.append("validation_gated_output_revision_mismatch")
    if (
        state.output_policy == MeshOutputPolicy.EXACT_GAME_ASSET.value
        and state.eligible_actions & state.blocked_actions
    ):
        errors.append("exact_policy_enables_blocked_action")
    if state.blocked_actions != frozenset(key for key, _reason in state.action_blockers):
        errors.append("blocked_action_reason_mismatch")
    if (
        state.output_policy == MeshOutputPolicy.READ_ONLY.value
        and state.eligible_actions & state.mutation_actions
    ):
        errors.append("read_only_policy_enables_mutation")
    if (
        state.renderer_session_id
        and state.renderer_session_id != state.session_id
        and (state.renderer_revision > 0 or state.pending_request_id > 0)
    ):
        errors.append("renderer_session_mismatch")
    if not state.session_id and any(
        (
            state.service_revision,
            state.geometry_revision,
            state.renderer_revision,
            state.last_acked_revision,
            state.pending_request_id,
            state.validation_revision is not None,
            state.rebuild_report_revision is not None,
            state.policy_authoring_enabled,
            bool(state.eligible_actions),
        )
    ):
        errors.append("closed_session_retains_authoring_authority")
    if state.authoring_enabled and state.renderer_revision != state.service_revision:
        errors.append("authoring_resumed_before_revision_equality")
    return tuple(errors)


def assert_mesh_editor_ui_invariants(state: MeshEditorUiState) -> None:
    errors = mesh_editor_ui_invariant_errors(state)
    if errors:
        raise MeshEditorUiInvariantError(errors)

__all__ = [
    "MeshEditorRecoveryStatus",
    "MeshEditorSelectionSummary",
    "MeshEditorSynchronizationStatus",
    "MeshEditorUiEvent",
    "MeshEditorUiEventKind",
    "MeshEditorUiInvariantError",
    "MeshEditorUiState",
    "assert_mesh_editor_ui_invariants",
    "mesh_editor_ui_invariant_errors",
]
