"""Workspace summaries and native-authority UV selection for MeshService."""

from __future__ import annotations

from functools import wraps
from typing import Iterable, Sequence

from cdmw.domain.mesh import (
    MeshCompareSummary,
    MeshEditResult,
    MeshEditSelection,
    MeshPanelUnavailableError,
    MeshUvSummary,
    MeshWorkspaceSummary,
    compare_meshes,
    summarize_mesh_uvs,
    summarize_mesh_workspace,
)
from cdmw.modding.mesh_native_core import (
    native_mesh_core_fallback_events,
    select_native_mesh_uv_vertices,
    summarize_native_mesh_editor_session,
    summarize_native_mesh_uvs,
)
from cdmw.services.mesh_service_kernel import _native_blocked_fallback_diagnostics
from cdmw.services.mesh_service_native_session import (
    _apply_native_editor_session_selection_operation,
)
from cdmw.services.mesh_service_reports import (
    _mesh_uv_summary_from_native,
    _mesh_workspace_summary_from_native,
    _vec2,
)
from cdmw.services.mesh_service_selection import (
    _prune_selection_to_mesh,
    _record_blocked_python_selection_fallback,
)
from cdmw.services.mesh_service_state import _MeshEditSession


def _with_mesh_session_export_lock(method):
    @wraps(method)
    def locked(self, session_id: str, *args: object, **kwargs: object):
        session = self._session(session_id)
        with session.export_lock:
            return method(self, session_id, *args, **kwargs)

    return locked


class MeshUvServiceMixin:
    def workspace_summary(self, session_id: str) -> MeshWorkspaceSummary:
        session = self._session(session_id)
        if session.native_editor_mesh_dirty:
            native_summary = _mesh_workspace_summary_from_native(
                summarize_native_mesh_editor_session(session.session_id),
                mesh_format=session.working_mesh.format,
            )
            if native_summary is None:
                raise MeshPanelUnavailableError(
                    "native_workspace_snapshot_unavailable",
                    "native mesh editor workspace summary failed; Python mesh state is stale",
                )
            return native_summary
        session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)
        return summarize_mesh_workspace(session.working_mesh, session.selection)

    def compare_summary(self, session_id: str) -> MeshCompareSummary:
        session = self._session(session_id)
        if session.native_editor_mesh_dirty:
            raise MeshPanelUnavailableError(
                "native_compare_snapshot_unavailable",
                "native mesh editor compare summary unavailable; Python mesh state is stale",
            )
        return compare_meshes(session.base_mesh, session.working_mesh)

    def uv_summary(self, session_id: str) -> MeshUvSummary:
        session = self._session(session_id)
        if session.native_editor_mesh_dirty:
            raise MeshPanelUnavailableError(
                "native_uv_snapshot_unavailable",
                "native mesh editor UV summary unavailable; Python mesh state is stale",
            )
        session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)
        native_summary = summarize_native_mesh_uvs(session.working_mesh, session.selection)
        parsed_native_summary = _mesh_uv_summary_from_native(native_summary)
        if parsed_native_summary is not None:
            return parsed_native_summary
        return summarize_mesh_uvs(session.working_mesh, session.selection)

    @_with_mesh_session_export_lock
    def select_uv_region(
        self,
        session_id: str,
        uv_min: Sequence[object],
        uv_max: Sequence[object],
        *,
        operation: str = "replace",
    ) -> MeshEditResult:
        session = self._session(session_id)
        fallback_event_start = len(native_mesh_core_fallback_events())
        native_vertices = select_native_mesh_uv_vertices(
            session.working_mesh,
            mode="region",
            uv_min=_vec2(uv_min),
            uv_max=_vec2(uv_max),
        )
        if native_vertices is None:
            _record_blocked_python_selection_fallback(
                session.working_mesh,
                "uv.region",
                "Native UV region selection is unavailable; Python selection fallback is blocked",
            )
            return self._result(
                session,
                "select",
                status="error",
                diagnostics=_native_blocked_fallback_diagnostics(fallback_event_start),
            )
        incoming = MeshEditSelection.from_maps(vertices_by_submesh=native_vertices)
        return self._select_native_uv_vertices(
            session,
            incoming,
            operation,
            fallback_event_start,
            label="Select UV Region",
        )

    @_with_mesh_session_export_lock
    def select_uv_lasso(
        self,
        session_id: str,
        points: Iterable[Sequence[object]],
        *,
        operation: str = "replace",
    ) -> MeshEditResult:
        session = self._session(session_id)
        polygon = tuple(_vec2(point) for point in points)
        fallback_event_start = len(native_mesh_core_fallback_events())
        native_vertices = select_native_mesh_uv_vertices(
            session.working_mesh,
            mode="lasso",
            points=polygon,
        )
        if native_vertices is None:
            _record_blocked_python_selection_fallback(
                session.working_mesh,
                "uv.lasso",
                "Native UV lasso selection is unavailable; Python selection fallback is blocked",
            )
            return self._result(
                session,
                "select",
                status="error",
                diagnostics=_native_blocked_fallback_diagnostics(fallback_event_start),
            )
        incoming = MeshEditSelection.from_maps(vertices_by_submesh=native_vertices)
        return self._select_native_uv_vertices(
            session,
            incoming,
            operation,
            fallback_event_start,
            label="Select UV Lasso",
        )

    def _select_native_uv_vertices(
        self,
        session: _MeshEditSession,
        selection: MeshEditSelection,
        operation: object,
        fallback_event_start: int,
        *,
        label: str,
    ) -> MeshEditResult:
        previous_selection = session.selection
        selected, native_selection_groups, diagnostics, metrics = (
            _apply_native_editor_session_selection_operation(session, selection, operation)
        )
        if selected is None:
            return self._result(
                session,
                "select",
                status="error",
                diagnostics=_native_blocked_fallback_diagnostics(fallback_event_start) + diagnostics,
                metrics=metrics,
            )
        self._record_selection_history(session, previous_selection, selected, label=label)
        session.selection = selected
        session.selection_revision += 1
        return self._result(
            session,
            "select",
            diagnostics=_native_blocked_fallback_diagnostics(fallback_event_start) + diagnostics,
            native_selection_groups=native_selection_groups,
            metrics=metrics,
        )


__all__ = ["MeshUvServiceMixin"]
