"""Tab effect bridge into the immutable Mesh Editor UI state reducer."""

from __future__ import annotations

from cdmw.domain.mesh import (
    MeshEditorRecoveryStatus,
    MeshEditorSelectionSummary,
    MeshEditorUiEvent,
    MeshEditorUiEventKind,
    MeshEditorUiState,
    reduce_mesh_editor_ui_state,
)
from cdmw.domain.mesh.authoring_capability import MeshOutputPolicy
from cdmw.ui.mesh_editor.actions import (
    MESH_EDITOR_SESSION_ACTIONS,
    NATIVE_EDITOR_SESSION_COMMANDS,
    mesh_editor_action_authoring_blocker,
    visible_actions_for_session,
)


_UI_STATE_EVENT_LIMIT = 256
_MUTATION_COMMANDS = NATIVE_EDITOR_SESSION_COMMANDS | {"undo", "redo"}


class MeshEditorUiStateMixin:
    def _initialize_mesh_editor_ui_state(self) -> None:
        self.mesh_editor_ui_state = MeshEditorUiState()
        self.mesh_editor_ui_state_events: list[MeshEditorUiEvent] = []

    def _transition_mesh_editor_ui_state(
        self,
        event: MeshEditorUiEvent,
    ) -> MeshEditorUiState:
        previous = self.mesh_editor_ui_state
        current = reduce_mesh_editor_ui_state(previous, event, strict=False)
        if current is previous:
            return current
        self.mesh_editor_ui_state = current
        self.mesh_editor_ui_state_events.append(event)
        if len(self.mesh_editor_ui_state_events) > _UI_STATE_EVENT_LIMIT:
            del self.mesh_editor_ui_state_events[:-_UI_STATE_EVENT_LIMIT]
        return current

    def _close_mesh_editor_ui_state(self) -> MeshEditorUiState:
        return self._transition_mesh_editor_ui_state(MeshEditorUiEvent.session_closed())

    def _observe_mesh_editor_process_generation(
        self,
        process_generation: int,
        *,
        renderer_capabilities: object = (),
    ) -> MeshEditorUiState:
        return self._transition_mesh_editor_ui_state(
            MeshEditorUiEvent(
                MeshEditorUiEventKind.PROCESS_GENERATION_CHANGED,
                process_generation=max(0, int(process_generation or 0)),
                renderer_capabilities=_normalized_names(renderer_capabilities),
            )
        )

    def _record_mesh_editor_report_state(
        self,
        report_kind: str,
        *,
        session_id: str,
        revision: int,
        ok: bool = False,
        process_generation: int | None = None,
    ) -> MeshEditorUiState:
        generation = (
            int(process_generation)
            if process_generation is not None
            else int(getattr(self, "standalone_dotnet_process_generation", 0) or 0)
        )
        return self._transition_mesh_editor_ui_state(
            MeshEditorUiEvent(
                MeshEditorUiEventKind.REPORT_COMPLETED,
                session_id=str(session_id or ""),
                process_generation=max(0, generation),
                report_kind=str(report_kind or ""),
                report_revision=max(0, int(revision)),
                report_ok=bool(ok),
            )
        )

    def _refresh_mesh_editor_ui_state(self) -> MeshEditorUiState:
        generation = max(
            0,
            int(getattr(self, "standalone_dotnet_process_generation", 0) or 0),
        )
        if generation > self.mesh_editor_ui_state.process_generation:
            self._observe_mesh_editor_process_generation(
                generation,
                renderer_capabilities=getattr(self, "standalone_dotnet_capabilities", ()),
            )
        controller = getattr(self, "standalone_controller", None)
        session_view = getattr(controller, "session_view", None)
        if not callable(session_view):
            session_id = str(getattr(controller, "active_session_id", "") or "")
            if session_id and self.mesh_editor_ui_state.session_id != session_id:
                self._transition_mesh_editor_ui_state(
                    MeshEditorUiEvent.session_opened(
                        session_id,
                        process_generation=generation,
                        mode=str(getattr(self, "current_edit_mode", "object") or "object"),
                    )
                )
            return self.mesh_editor_ui_state
        try:
            view = session_view()
        except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
            return self.mesh_editor_ui_state
        session_id = str(
            getattr(view, "session_id", "")
            or getattr(controller, "active_session_id", "")
            or ""
        )
        if not session_id:
            return self.mesh_editor_ui_state
        if self.mesh_editor_ui_state.session_id != session_id:
            self._transition_mesh_editor_ui_state(
                MeshEditorUiEvent.session_opened(
                    session_id,
                    process_generation=generation,
                    mode=str(getattr(view, "mode", "object") or "object"),
                )
            )
        self._observe_mesh_editor_service_view(view, session_id=session_id)
        self._observe_mesh_editor_renderer_queue(session_id, generation)
        self._observe_legacy_report_authority(session_id, generation)
        return self.mesh_editor_ui_state

    def _observe_mesh_editor_service_view(
        self,
        view: object,
        *,
        session_id: str,
    ) -> None:
        mesh_format = str(
            getattr(view, "mesh_format", "")
            or getattr(self, "_standalone_mesh_format")()
            or ""
        )
        lod_index = int(getattr(view, "lod_index", 0) or 0)
        output_policy = str(getattr(view, "output_policy", "") or "")
        if not output_policy:
            output_policy = (
                MeshOutputPolicy.EXACT_GAME_ASSET.value
                if getattr(self, "_standalone_exact_output_required")()
                else MeshOutputPolicy.READ_ONLY.value
            )
        destination = str(getattr(view, "output_destination", "") or "")
        destination_ready = bool(getattr(view, "output_destination_ready", False))
        visible = visible_actions_for_session(
            mesh_format,
            lod_index,
            output_policy,
            free_edit_destination_ready=destination_ready,
        )
        visible_keys = {action.key for action in visible}
        blocked: set[str] = set()
        blocker_reasons: dict[str, str] = {}
        eligible: set[str] = set()
        mutation: set[str] = set()
        for action in MESH_EDITOR_SESSION_ACTIONS:
            if action.command in _MUTATION_COMMANDS:
                mutation.add(action.key)
            blocker = mesh_editor_action_authoring_blocker(
                action.key,
                mesh_format=mesh_format,
                lod_index=lod_index,
                output_policy=output_policy,
                free_edit_destination=destination,
                free_edit_destination_ready=destination_ready,
            )
            if blocker:
                blocked.add(action.key)
                blocker_reasons[action.key] = blocker
            elif action.key in visible_keys:
                eligible.add(action.key)
        selection = getattr(view, "selection", None)
        self._transition_mesh_editor_ui_state(
            MeshEditorUiEvent(
                MeshEditorUiEventKind.SERVICE_OBSERVED,
                session_id=session_id,
                service_revision=max(
                    0,
                    int(
                        getattr(
                            view,
                            "resident_revision",
                            getattr(view, "revision", 0),
                        )
                        or 0
                    ),
                ),
                geometry_revision=max(0, int(getattr(view, "revision", 0) or 0)),
                mode=str(getattr(self, "current_edit_mode", getattr(view, "mode", "object")) or "object"),
                active_tool=str(getattr(self, "current_tool_action_key", "") or ""),
                element_type=str(getattr(self, "current_element_type", "vertex") or "vertex"),
                selection_shape=str(getattr(self, "current_selection_mode", "brush") or "brush"),
                selection=_selection_summary(selection),
                undo_count=max(0, int(getattr(view, "undo_count", 0) or 0)),
                redo_count=max(0, int(getattr(view, "redo_count", 0) or 0)),
                output_policy=output_policy,
                mesh_format=mesh_format,
                lod_index=lod_index,
                output_destination=destination,
                output_destination_ready=destination_ready,
                exact_write_status=str(getattr(view, "exact_write_status", "read_only") or "read_only"),
                policy_reason=str(getattr(view, "output_policy_reason", "") or ""),
                policy_authoring_enabled=bool(
                    getattr(
                        view,
                        "authoring_enabled",
                        output_policy == MeshOutputPolicy.EXACT_GAME_ASSET.value,
                    )
                ),
                writer_capabilities=frozenset(eligible if output_policy == MeshOutputPolicy.EXACT_GAME_ASSET.value else ()),
                eligible_actions=frozenset(eligible),
                visible_actions=frozenset(visible_keys),
                blocked_actions=frozenset(blocked),
                action_blockers=tuple(sorted(blocker_reasons.items())),
                mutation_actions=frozenset(mutation),
            )
        )

    def _observe_mesh_editor_renderer_queue(
        self,
        session_id: str,
        generation: int,
    ) -> None:
        renderer_session_id = str(
            getattr(self, "standalone_dotnet_lifecycle_session_id", "") or ""
        )
        if not renderer_session_id or renderer_session_id != session_id:
            return
        queue = getattr(self, "standalone_dotnet_update_queue", None)
        metrics = queue.metrics() if queue is not None else {}
        recovery = MeshEditorRecoveryStatus.IDLE
        if bool(metrics.get("recovery_failed")):
            recovery = MeshEditorRecoveryStatus.FAILED
        elif bool(metrics.get("resync_active")):
            recovery = MeshEditorRecoveryStatus.ACTIVE
        self._transition_mesh_editor_ui_state(
            MeshEditorUiEvent(
                MeshEditorUiEventKind.RENDERER_OBSERVED,
                session_id=session_id,
                renderer_session_id=renderer_session_id,
                process_generation=generation,
                renderer_revision=max(0, int(metrics.get("last_acked_revision", 0) or 0)),
                last_acked_revision=max(0, int(metrics.get("last_acked_revision", 0) or 0)),
                pending_request_id=(
                    max(0, int(metrics.get("active_request_id", 0) or 0))
                    if int(metrics.get("active_revision", 0) or 0) > 0
                    else 0
                ),
                pending_base_revision=max(
                    0,
                    int(metrics.get("last_acked_revision", 0) or 0),
                ),
                pending_target_revision=max(
                    0,
                    int(metrics.get("active_revision", 0) or 0),
                ),
                recovery_status=recovery,
                renderer_capabilities=_normalized_names(
                    getattr(self, "standalone_dotnet_capabilities", ())
                ),
            )
        )

    def _observe_legacy_report_authority(
        self,
        session_id: str,
        generation: int,
    ) -> None:
        validation_revision = getattr(self, "standalone_export_validation_revision", None)
        if validation_revision is not None:
            report = getattr(self, "standalone_last_export_validation_report", None)
            self._record_mesh_editor_report_state(
                "validation",
                session_id=session_id,
                revision=int(validation_revision),
                ok=bool(getattr(report, "ok", False)),
                process_generation=generation,
            )
        rebuild_revision = getattr(self, "standalone_rebuild_report_revision", None)
        if rebuild_revision is not None:
            self._record_mesh_editor_report_state(
                "rebuild",
                session_id=session_id,
                revision=int(rebuild_revision),
                process_generation=generation,
            )

    def _mesh_editor_ui_state_snapshot(self) -> dict[str, object]:
        return self.mesh_editor_ui_state.as_payload()


def _selection_summary(selection: object) -> MeshEditorSelectionSummary:
    return MeshEditorSelectionSummary(
        vertex_count=_nested_count(getattr(selection, "vertices_by_submesh", ())),
        edge_count=_nested_count(getattr(selection, "edges_by_submesh", ())),
        face_count=_nested_count(getattr(selection, "faces_by_submesh", ())),
        part_count=len(tuple(getattr(selection, "source_indices", ()) or ())),
    )


def _nested_count(values: object) -> int:
    try:
        return sum(len(tuple(items or ())) for _index, items in values)
    except (TypeError, ValueError):
        return 0


def _normalized_names(values: object) -> frozenset[str]:
    try:
        return frozenset(
            str(value or "").strip().lower()
            for value in values
            if str(value or "").strip()
        )
    except TypeError:
        return frozenset()


__all__ = ["MeshEditorUiStateMixin"]
