"""Shared resident-session bookkeeping for the Mesh Editor tab mixins.

Four different mixins need to move the Edit Mesh session, ask which session a
command belongs to, or record a material publication transition: the lifecycle
mixin owns Finish, the process mixin owns renderer loss, the compilation mixin
owns publication results, and the shell mixin owns process identity. Calling
each other's methods across that boundary works only because `MeshEditorTab`
happens to compose all of them, and this codebase resolves that wiring at
runtime -- so a host that composed one without the others would fail when a user
clicked, not when a test imported.

Putting them here and inheriting this makes the dependency a declared one. Every
method still tolerates a host that skipped the tab's runtime initialiser,
because several of these mixins are genuinely composed into such hosts; what it
no longer tolerates is a host that has the state but not the method.
"""

from __future__ import annotations

from cdmw.services.mesh_edit_session_state import MeshEditSessionState
from cdmw.services.mesh_editor_error_codes import MeshEditorErrorCode, error_payload
from cdmw.services.mesh_material_publication import MaterialPublicationResult


class MeshEditorDotNetSessionEventMixin:
    # -- material publication -------------------------------------------

    def _record_dotnet_material_publication(
        self,
        result: MaterialPublicationResult | None,
    ) -> None:
        """Emit one structured event per publication state transition."""

        if result is None:
            return
        # Committed resources are not reported as finished here. A superseded or
        # replaced publication has already had its resources merged into the
        # request that displaced it, so they are still on their way to the
        # renderer; telling the builder they were abandoned would drop live
        # texture bindings. Only a genuinely dropped compile reports them, which
        # the compile-completed, compile-error, and cancel paths do.
        self._record_mesh_dotnet_event(
            "mesh_dotnet_material_publication",
            **result.as_event_payload(),
        )

    # -- edit session ---------------------------------------------------

    def _edit_session_machine(self):
        """The session machine, or ``None`` in a host without runtime state.

        getattr: these mixins are composed into hosts that do not run the tab's
        runtime initialiser. Those have no Edit Mesh session at all.
        """

        return getattr(self, "standalone_dotnet_edit_session", None)

    def _edit_session_generation(self) -> int:
        """The current session identity, or -1 where there is no machine."""

        machine = self._edit_session_machine()
        return int(getattr(machine, "generation", -1)) if machine is not None else -1

    def _edit_session_transition(
        self,
        target: MeshEditSessionState,
        *,
        reason: str,
    ) -> bool:
        """Ask the session machine to move, and record the answer either way."""

        machine = self._edit_session_machine()
        if machine is None:
            return False
        outcome = machine.transition(target, reason=reason)
        self._record_mesh_dotnet_event(
            "mesh_dotnet_edit_session_transition",
            **outcome.as_event_payload(),
        )
        return outcome.accepted

    def _require_edit_session_recovery(self, *, reason: str) -> bool:
        """Put a session that still holds edits into recovery.

        From there it cannot reach EDIT_COMMITTED at all, which is what stops a
        renderer that died mid-edit from being followed by a finish that reports
        success over a working state nobody can vouch for.
        """

        machine = self._edit_session_machine()
        if machine is None:
            return False
        outcome = machine.require_recovery(reason=reason)
        if not outcome.accepted:
            return False
        self._record_mesh_dotnet_event(
            "mesh_dotnet_edit_session_transition",
            **outcome.as_event_payload(),
            **error_payload(MeshEditorErrorCode.EDIT_SESSION_RECOVERY_REQUIRED, reason),
        )
        return True

    def _observe_edit_session_from_scene_frame(self) -> None:
        """Open the session when the helper acknowledges a mesh-edit scene frame.

        The acknowledged frame is the only authority on which interaction mode
        the helper is actually in. Inferring entry from the click that requested
        it is what let Modify Original race its own worker: the tab believed the
        session was open while the helper had not yet accepted the frame.
        """

        machine = self._edit_session_machine()
        if machine is None:
            return
        interaction = str(
            (getattr(self, "standalone_dotnet_scene_desired", None) or {}).get(
                "interaction_mode",
                "",
            )
            or ""
        ).strip().lower()
        if interaction != "mesh_edit":
            return
        if machine.state is MeshEditSessionState.BUILDER_IDLE:
            self._edit_session_transition(
                MeshEditSessionState.PREPARING_EDIT,
                reason="mesh_edit_scene_frame_requested",
            )
        if machine.state in {
            MeshEditSessionState.EDIT_COMMITTED,
            MeshEditSessionState.EDIT_CANCELED,
        }:
            self._edit_session_transition(
                MeshEditSessionState.PREPARING_EDIT,
                reason="mesh_edit_reopened",
            )
        if machine.state is MeshEditSessionState.PREPARING_EDIT:
            self._edit_session_transition(
                MeshEditSessionState.EDIT_ACTIVE,
                reason="mesh_edit_scene_frame_applied",
            )


__all__ = ["MeshEditorDotNetSessionEventMixin"]
