from __future__ import annotations

import math
import os
import sys
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.modding.mesh_deformer import recompute_mesh_normals
from cdmw.modding.mesh_edit_ops import MESH_GEOMETRY_ACTIONS, refresh_mesh_totals
from cdmw.modding.mesh_native_core import (
    NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR,
    apply_native_mesh_editor_session,
    apply_native_mesh_recalculate_normals,
    apply_native_mesh_sparse_vertex_restore,
    close_native_mesh_editor_session,
    dispose_native_mesh_history_delta,
    export_native_mesh_editor_session_to_mesh,
    last_native_mesh_core_job_error,
    last_native_mesh_editor_apply_error,
    native_mesh_core_available,
    native_mesh_editor_session_preview_triangle_groups,
    native_mesh_editor_session_preview_vertex_update_groups,
    native_mesh_editor_session_selection_from_report,
    native_mesh_editor_session_selection_groups_from_report,
    native_mesh_editor_source_normals_payload,
    native_mesh_history_delta_positions,
    open_native_mesh_editor_session,
    record_native_mesh_core_fallback,
    select_native_mesh_editor_session,
)
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.models import RunCancelled
from cdmw.services.mesh_service_kernel import (
    _apply_native_editor_dirty_counts,
    _mesh_count_hint,
    _native_editor_mesh_storage_signature,
    _truthy,
)
from cdmw.services.mesh_service_payloads import (
    _can_reuse_native_live_stroke_selection,
    _can_reuse_native_stroke_begin_mesh_selection,
    _can_reuse_native_stroke_begin_selection,
    _mesh_edit_selection_signature,
    _native_editor_edit_payload,
    _native_editor_metrics,
    _native_editor_selection_payload,
    _native_editor_selection_payload_for_apply,
    _native_editor_selection_signature_for_apply,
    _native_editor_selection_target_indices,
    _native_editor_stroke_id,
    _native_editor_stroke_metrics,
    _native_editor_stroke_phase,
    _prefixed_metrics,
    _stop_event_from_params,
)
from cdmw.services.mesh_service_reports import (
    _coerce_index,
    _native_editor_dirty_counts_from_report,
    _native_editor_report_affected_indices,
    _native_editor_report_changed_vertices,
    _native_editor_report_submesh_counts,
)
from cdmw.services.mesh_service_selection import (
    _prune_selection_to_mesh,
    _selected_skin_weight_vertex_count,
)
from cdmw.services.mesh_service_state import (
    _MeshEditSession,
    _MeshHistorySnapshot,
    _MeshVertexPositionDelta,
    _NativeEditorApplyResult,
)

_LEGACY_DISPLAY_CLEANUP_ACTIONS = frozenset({"triangulate_display", "quadrangulate_display"})
_NATIVE_EDITOR_SESSION_ACTIONS = frozenset({"select"}) | (
    frozenset(MESH_GEOMETRY_ACTIONS) - _LEGACY_DISPLAY_CLEANUP_ACTIONS
)


def _service_call(name: str, *args: object, **kwargs: object) -> object:
    """Resolve facade re-exports so existing integrations keep one patch surface."""
    return getattr(sys.modules["cdmw.services.mesh_service"], name)(*args, **kwargs)


def _close_native_editor_session(session: _MeshEditSession) -> None:
    if not session.native_editor_session_ready:
        session.native_history_undo_count = 0
        session.native_history_redo_count = 0
        session.native_history_retained_bytes = 0
        return
    _service_call("close_native_mesh_editor_session", session.session_id, timeout_seconds=2.0)
    session.native_editor_session_ready = False
    session.native_editor_selection_signature = ()
    session.native_editor_active_stroke_id = ""
    session.native_editor_mesh_signature = ()
    session.native_editor_mesh_dirty = False
    session.native_editor_mesh_dirty_counts = ()
    session.native_history_undo_count = 0
    session.native_history_redo_count = 0
    session.native_history_retained_bytes = 0


def _refresh_native_editor_session_if_mesh_changed(session: _MeshEditSession) -> None:
    if not session.native_editor_session_ready:
        return
    if session.native_editor_mesh_dirty:
        return
    current = _native_editor_mesh_storage_signature(session.working_mesh)
    if current != session.native_editor_mesh_signature:
        _close_native_editor_session(session)


def _abandon_lost_native_editor_session(session: _MeshEditSession) -> bool:
    """Return the working mesh to its last exported state and carry on.

    A resident session that has died while holding edits this side never
    received takes those edits with it; nothing here can get them back. What
    this repairs is the aftermath. `native_editor_mesh_dirty` stayed true with
    no session able to clear it, so every read of the working mesh raised and
    every apply was refused -- one failed stroke turned the whole editor dead,
    permanently, and the reader saw Move, then Clear Selection, then Finish Edit
    Mesh stop working in sequence with an endless RuntimeError behind each.

    Only `total_vertices` and `total_faces` were ever moved ahead of the real
    geometry, by `_apply_native_editor_dirty_counts`, so recomputing the totals
    puts the mesh back in agreement with itself. The next apply reopens the
    resident session from it.
    """

    session.native_editor_session_ready = False
    session.native_editor_selection_signature = ()
    session.native_editor_active_stroke_id = ""
    session.native_editor_mesh_dirty = False
    session.native_editor_mesh_dirty_counts = ()
    session.native_editor_lost_recoveries += 1
    refresh_mesh_totals(session.working_mesh)
    session.selection = _service_call("_prune_selection_to_mesh", session.working_mesh, session.selection)  # type: ignore[assignment]
    session.native_editor_mesh_signature = _native_editor_mesh_storage_signature(session.working_mesh)
    return True


def _sync_native_editor_session_to_working_mesh(session: _MeshEditSession) -> bool:
    if not session.native_editor_mesh_dirty:
        return True
    if not session.native_editor_session_ready:
        return _abandon_lost_native_editor_session(session)
    if not _service_call(
        "export_native_mesh_editor_session_to_mesh",
        session.working_mesh,
        session.session_id,
        timeout_seconds=20.0,
    ):
        return _abandon_lost_native_editor_session(session)
    refresh_mesh_totals(session.working_mesh)
    session.selection = _service_call("_prune_selection_to_mesh", session.working_mesh, session.selection)  # type: ignore[assignment]
    session.native_editor_mesh_signature = _native_editor_mesh_storage_signature(session.working_mesh)
    session.native_editor_mesh_dirty = False
    session.native_editor_mesh_dirty_counts = ()
    return True




def _apply_native_editor_session_selection_operation(
    session: _MeshEditSession,
    selection: MeshEditSelection,
    operation: object,
    *,
    native_selection_payload: Mapping[str, object] | None = None,
    stop_event: object | None = None,
) -> tuple[MeshEditSelection | None, tuple[Mapping[str, object], ...], tuple[str, ...], dict[str, float]]:
    metrics: dict[str, float] = {}
    try:
        _refresh_native_editor_session_if_mesh_changed(session)
        if not session.native_editor_session_ready:
            if session.native_editor_mesh_dirty:
                return None, (), ("Native editor selection failed; resident C++ mesh is dirty and Python mesh state is stale.",), metrics
            open_started = time.perf_counter()
            opened = _service_call(
                "open_native_mesh_editor_session",
                session.working_mesh,
                session.session_id,
                stop_event=stop_event,  # type: ignore[arg-type]
                timeout_seconds=10.0,
            )
            open_roundtrip_ms = max(0.0, (time.perf_counter() - open_started) * 1000.0)
            if opened is None:
                session.native_editor_session_ready = False
                session.native_editor_selection_signature = ()
                session.native_editor_active_stroke_id = ""
                return None, (), ("Native editor selection session failed to open; Python fallback is disabled while native core is available.",), metrics
            session.native_editor_session_ready = True
            session.native_editor_selection_signature = ()
            session.native_editor_mesh_signature = _native_editor_mesh_storage_signature(session.working_mesh)
            metrics.update(_prefixed_metrics(_native_editor_metrics(opened), "editor_open"))
            metrics["editor_open_roundtrip_ms"] = open_roundtrip_ms
        select_started = time.perf_counter()
        selected = _service_call(
            "select_native_mesh_editor_session",
            session.session_id,
            native_selection_payload if native_selection_payload is not None else _native_editor_selection_payload(selection),
            operation=operation,
            iterations=1,
            stop_event=stop_event,  # type: ignore[arg-type]
            timeout_seconds=5.0,
        )
        select_roundtrip_ms = max(0.0, (time.perf_counter() - select_started) * 1000.0)
        if selected is None:
            session.native_editor_session_ready = False
            session.native_editor_selection_signature = ()
            session.native_editor_active_stroke_id = ""
            return None, (), ("Native editor selection command failed; Python fallback is disabled while native core is available.",), metrics
        selected_payload = native_mesh_editor_session_selection_from_report(selected)
        if selected_payload is None:
            session.native_editor_session_ready = False
            session.native_editor_selection_signature = ()
            session.native_editor_active_stroke_id = ""
            return None, (), ("Native editor selection command returned an invalid selection report.",), metrics
        result = MeshEditSelection.from_maps(
            vertices_by_submesh=selected_payload.get("vertices_by_submesh"),  # type: ignore[arg-type]
            edges_by_submesh=selected_payload.get("edges_by_submesh"),  # type: ignore[arg-type]
            faces_by_submesh=selected_payload.get("faces_by_submesh"),  # type: ignore[arg-type]
            source_indices=selected_payload.get("source_indices"),  # type: ignore[arg-type]
        )
        native_selection_groups = native_mesh_editor_session_selection_groups_from_report(selected)
        select_metrics = _native_editor_metrics(selected)
        metrics.update(select_metrics)
        metrics.update(_prefixed_metrics(select_metrics, "editor_select"))
        try:
            source_pick_count = selected.get("source_pick_count") if isinstance(selected, Mapping) else None
            if source_pick_count is not None:
                metrics["editor_select_source_pick_count"] = float(source_pick_count)
        except (TypeError, ValueError):
            pass
        metrics["editor_select_roundtrip_ms"] = select_roundtrip_ms
        metrics["editor_select_resident_operation"] = 1.0
        session.native_editor_selection_signature = _mesh_edit_selection_signature(result)
        return result, native_selection_groups, (), metrics
    except RunCancelled:
        session.native_editor_session_ready = False
        raise




def _native_editor_refusal(session: _MeshEditSession, action: str, reason: str, **detail: object) -> None:
    """Name which of the six ways this gave up.

    Every one of them returned a bare `None` that the caller turned into the
    same sentence: "native mesh editor session failed for <action>". A session
    where every stroke, Clear Selection and Finish Edit Mesh was refused
    therefore said only that something native had failed, six different causes
    wearing one message, and no capture could tell them apart.
    """

    if detail:
        described = ", ".join(f"{key}={value!r}" for key, value in sorted(detail.items()))
        session.native_editor_last_refusal = f"{reason} ({described})"
    else:
        session.native_editor_last_refusal = reason


@dataclass(slots=True)
class _NativeEditorRequest:
    action: str
    params: dict[str, object]
    stop_event: object | None
    dirty_at_start: bool
    stroke_phase: str
    stroke_id: str
    reuse_selection: bool
    selection_payload: dict[str, object]
    selection_signature: tuple[object, ...]


@dataclass(slots=True)
class _NativeEditorExecution:
    report: dict[str, object]
    affected: Iterable[int]
    changed: Mapping[int, object]
    dirty_counts: Sequence[object]
    native_submesh_counts: Sequence[object]
    native_before_submesh_count: int
    report_submesh_count: int | None
    native_preview_vertex_update_groups: object
    native_preview_triangle_groups: object
    open_roundtrip_ms: float
    select_roundtrip_ms: float
    native_apply_roundtrip_ms: float
    python_apply_ms: float
    selection_inlined: bool


def _prepare_native_editor_request(
    session: _MeshEditSession,
    command: MeshEditCommand,
    selection: MeshEditSelection,
) -> _NativeEditorRequest | None:
    action = command.action.strip().lower()
    if action not in getattr(
        sys.modules["cdmw.services.mesh_service"],
        "_NATIVE_EDITOR_SESSION_ACTIONS",
    ):
        _native_editor_refusal(session, action, "action_not_native")
        return None
    if not _service_call("native_mesh_core_available"):
        _native_editor_refusal(session, action, "native_mesh_core_unavailable")
        return None

    params = dict(command.params or {})
    dirty_at_start = session.native_editor_mesh_dirty
    if dirty_at_start and not session.native_editor_session_ready:
        _abandon_lost_native_editor_session(session)
        dirty_at_start = False
    if (
        dirty_at_start
        and action == "delete"
        and _truthy(params.get("delete_parts"))
        and not _truthy(params.get("geometry_layer_delete"))
    ):
        _native_editor_refusal(session, action, "delete_parts_while_mesh_dirty")
        return None

    stroke_phase = _native_editor_stroke_phase(params)
    stroke_id = _native_editor_stroke_id(params)
    if (
        stroke_phase in {"update", "end"}
        and bool(stroke_id)
        and session.native_editor_lost_recoveries
        and stroke_id != session.native_editor_active_stroke_id
    ):
        _native_editor_refusal(
            session,
            action,
            "stroke_orphaned_by_session_loss",
            stroke_phase=str(stroke_phase),
            stroke_id=str(stroke_id),
            host_active_stroke_id=str(session.native_editor_active_stroke_id or ""),
            lost_recoveries=int(session.native_editor_lost_recoveries),
        )
        return None

    reuse_selection = (
        stroke_phase in {"update", "end", "cancel"}
        and not isinstance(params.get("_native_selection_payload"), Mapping)
        and bool(stroke_id)
        and stroke_id == session.native_editor_active_stroke_id
        and session.native_editor_session_ready
        and bool(session.native_editor_selection_signature)
    )
    if reuse_selection:
        selection_payload: dict[str, object] = {}
        selection_signature: tuple[object, ...] = ()
    elif _can_reuse_native_stroke_begin_mesh_selection(session, params, selection):
        selection_payload = {}
        selection_signature = session.native_editor_selection_signature
        reuse_selection = True
    else:
        selection_signature = _service_call("_native_editor_selection_signature_for_apply", selection, params)  # type: ignore[assignment]
        reuse_selection = (
            _can_reuse_native_live_stroke_selection(session, params, selection_signature)
            or _can_reuse_native_stroke_begin_selection(session, params, selection_signature)
        )
        selection_payload = (
            {} if reuse_selection else _native_editor_selection_payload_for_apply(selection, params)
        )
    return _NativeEditorRequest(
        action=action,
        params=params,
        stop_event=_stop_event_from_params(params),
        dirty_at_start=dirty_at_start,
        stroke_phase=stroke_phase,
        stroke_id=stroke_id,
        reuse_selection=reuse_selection,
        selection_payload=selection_payload,
        selection_signature=selection_signature,
    )


def _execute_native_editor_request(
    session: _MeshEditSession,
    selection: MeshEditSelection,
    request: _NativeEditorRequest,
) -> _NativeEditorExecution | None:
    try:
        _refresh_native_editor_session_if_mesh_changed(session)
        if request.reuse_selection and not session.native_editor_session_ready:
            request.reuse_selection = False
            request.selection_payload = _native_editor_selection_payload_for_apply(selection, request.params)
            request.selection_signature = _native_editor_selection_signature_for_apply(selection, request.params)
        if not session.native_editor_session_ready:
            open_started = time.perf_counter()
            opened = _service_call(
                "open_native_mesh_editor_session",
                session.working_mesh,
                session.session_id,
                stop_event=request.stop_event,  # type: ignore[arg-type]
                timeout_seconds=10.0,
            )
            open_roundtrip_ms = max(0.0, (time.perf_counter() - open_started) * 1000.0)
            if opened is None:
                _native_editor_refusal(
                    session,
                    request.action,
                    "open_session_failed",
                    open_roundtrip_ms=round(open_roundtrip_ms, 2),
                )
                return None
            session.native_editor_session_ready = True
            session.native_editor_selection_signature = ()
            session.native_editor_active_stroke_id = ""
            session.native_editor_mesh_signature = _native_editor_mesh_storage_signature(
                session.working_mesh
            )
        else:
            open_roundtrip_ms = 0.0
        selection_inlined = not request.reuse_selection
        edit_payload = _native_editor_edit_payload(request.action, request.params)
        if request.action == "copy_normals":
            source_mesh = request.params.get("source_mesh")
            if isinstance(source_mesh, ParsedMesh):
                source_normals = native_mesh_editor_source_normals_payload(
                    source_mesh,
                    _native_editor_selection_target_indices(selection),
                )
                if source_normals:
                    edit_payload["source_normals_by_submesh"] = source_normals
        native_before_submesh_count = (
            len(session.native_editor_mesh_dirty_counts)
            if request.dirty_at_start and session.native_editor_mesh_dirty_counts
            else len(session.working_mesh.submeshes or ())
        )
        native_apply_started = time.perf_counter()
        report = _service_call(
            "apply_native_mesh_editor_session",
            session.session_id,
            edit_payload,
            selection=request.selection_payload if selection_inlined else None,
            include_preview_deltas=bool(request.params.get("_include_preview_deltas", True)),
            binary_preview_deltas=not bool(request.stroke_phase),
            stroke_phase=request.stroke_phase,
            stroke_id=request.stroke_id,
            stop_event=request.stop_event,  # type: ignore[arg-type]
            timeout_seconds=20.0,
        )
        native_apply_roundtrip_ms = max(
            0.0,
            (time.perf_counter() - native_apply_started) * 1000.0,
        )
        if report is None:
            session.native_editor_session_ready = False
            _native_editor_refusal(
                session,
                request.action,
                "native_apply_returned_no_report",
                stroke_phase=str(request.stroke_phase),
                stroke_id=str(request.stroke_id),
                reuse_selection=bool(request.reuse_selection),
                roundtrip_ms=round(native_apply_roundtrip_ms, 2),
                native_error=last_native_mesh_editor_apply_error() or "none recorded",
                native_job_error=last_native_mesh_core_job_error() or "none recorded",
                first_refusal=not bool(session.native_editor_last_refusal),
                had_inline_selection_payload=isinstance(
                    request.params.get("_native_selection_payload"),
                    Mapping,
                ),
                host_active_stroke_id=str(session.native_editor_active_stroke_id or ""),
                session_ready=bool(session.native_editor_session_ready),
                selection_signature_len=len(session.native_editor_selection_signature or ()),
                mesh_dirty=bool(session.native_editor_mesh_dirty),
                lost_recoveries=int(session.native_editor_lost_recoveries),
            )
            return None
        preview_vertices = native_mesh_editor_session_preview_vertex_update_groups(report)
        preview_triangles = native_mesh_editor_session_preview_triangle_groups(report)
        report_submesh_count = _coerce_index(report.get("submesh_count"))
        native_submesh_counts = (
            _native_editor_report_submesh_counts(report, report_submesh_count)
            if report_submesh_count is not None and report_submesh_count >= 0
            else ()
        )
        dirty_counts = _native_editor_dirty_counts_from_report(
            report,
            current_submesh_count=native_before_submesh_count,
        )
        apply_started = time.perf_counter()
        if not dirty_counts:
            session.native_editor_session_ready = False
            _native_editor_refusal(
                session,
                request.action,
                "native_report_had_no_dirty_counts",
                stroke_phase=str(request.stroke_phase),
                stroke_id=str(request.stroke_id),
                submesh_count=report_submesh_count,
                report_keys=sorted(str(key) for key in report)[:12],
            )
            return None
        session.native_editor_mesh_dirty = True
        session.native_editor_mesh_dirty_counts = dirty_counts
        _apply_native_editor_dirty_counts(session)
        affected = _native_editor_report_affected_indices(report, len(dirty_counts))
        changed = _native_editor_report_changed_vertices(report, dirty_counts)
        python_apply_ms = max(0.0, (time.perf_counter() - apply_started) * 1000.0)
    except RunCancelled:
        session.native_editor_session_ready = False
        session.native_editor_selection_signature = ()
        session.native_editor_active_stroke_id = ""
        session.native_editor_mesh_dirty = False
        session.native_editor_mesh_dirty_counts = ()
        raise
    return _NativeEditorExecution(
        report=report,
        affected=affected,
        changed=changed,
        dirty_counts=dirty_counts,
        native_submesh_counts=native_submesh_counts,
        native_before_submesh_count=native_before_submesh_count,
        report_submesh_count=report_submesh_count,
        native_preview_vertex_update_groups=preview_vertices,
        native_preview_triangle_groups=preview_triangles,
        open_roundtrip_ms=open_roundtrip_ms,
        select_roundtrip_ms=0.0,
        native_apply_roundtrip_ms=native_apply_roundtrip_ms,
        python_apply_ms=python_apply_ms,
        selection_inlined=selection_inlined,
    )


def _native_editor_result_from_execution(
    session: _MeshEditSession,
    request: _NativeEditorRequest,
    execution: _NativeEditorExecution,
) -> _NativeEditorApplyResult:
    report = execution.report
    metrics = _native_editor_metrics(report)
    stroke_metrics, native_stroke_id, native_stroke_phase, native_stroke_cancelled = (
        _native_editor_stroke_metrics(report)
    )
    metrics.update(stroke_metrics)
    metrics["python_apply_ms"] = execution.python_apply_ms
    metrics["python_apply_deferred"] = 1.0 if session.native_editor_mesh_dirty else 0.0
    metrics["editor_open_roundtrip_ms"] = execution.open_roundtrip_ms
    metrics["editor_select_roundtrip_ms"] = execution.select_roundtrip_ms
    metrics["editor_select_reused"] = 1.0 if request.reuse_selection else 0.0
    metrics["editor_select_inlined"] = 1.0 if execution.selection_inlined else 0.0
    metrics["native_apply_roundtrip_ms"] = execution.native_apply_roundtrip_ms
    metrics["native_apply_overhead_ms"] = max(
        0.0,
        execution.native_apply_roundtrip_ms
        - metrics.get("cpp_ms", 0.0)
        - metrics.get("io_serialization_ms", 0.0),
    )
    if native_stroke_phase == "begin" and native_stroke_id:
        session.native_editor_active_stroke_id = native_stroke_id
    elif native_stroke_phase in {"end", "cancel"}:
        session.native_editor_active_stroke_id = ""
    elif native_stroke_phase == "update" and native_stroke_id:
        session.native_editor_active_stroke_id = native_stroke_id

    topology_changed = bool(report.get("topology_changed")) if "topology_changed" in report else None
    selection_payload = native_mesh_editor_session_selection_from_report(report)
    native_selection = (
        MeshEditSelection.from_maps(
            vertices_by_submesh=selection_payload.get("vertices_by_submesh"),  # type: ignore[arg-type]
            edges_by_submesh=selection_payload.get("edges_by_submesh"),  # type: ignore[arg-type]
            faces_by_submesh=selection_payload.get("faces_by_submesh"),  # type: ignore[arg-type]
            source_indices=selection_payload.get("source_indices"),  # type: ignore[arg-type]
        )
        if selection_payload is not None
        else None
    )
    native_selection_groups = native_mesh_editor_session_selection_groups_from_report(report)
    if topology_changed:
        session.native_editor_selection_signature = ()
    elif execution.selection_inlined:
        session.native_editor_selection_signature = request.selection_signature
    return _NativeEditorApplyResult(
        set(execution.affected),
        dict(execution.changed),
        metrics,
        native_preview_vertex_update_groups=execution.native_preview_vertex_update_groups,
        native_preview_triangle_groups=execution.native_preview_triangle_groups,
        native_selection=native_selection,
        native_selection_groups=native_selection_groups,
        native_stroke_id=native_stroke_id,
        native_stroke_phase=native_stroke_phase,
        native_stroke_cancelled=native_stroke_cancelled,
        topology_changed=topology_changed,
        submesh_count_delta=(
            int(execution.report_submesh_count) - execution.native_before_submesh_count
            if execution.report_submesh_count is not None
            else 0
        ),
        submesh_counts=execution.dirty_counts or execution.native_submesh_counts,
    )


def _apply_native_editor_session_geometry_action(
    session: _MeshEditSession,
    command: MeshEditCommand,
    selection: MeshEditSelection,
) -> _NativeEditorApplyResult | None:
    request = _prepare_native_editor_request(session, command, selection)
    if request is None:
        return None
    execution = _execute_native_editor_request(session, selection, request)
    if execution is None:
        return None
    return _native_editor_result_from_execution(session, request, execution)


def _native_live_history_snapshot(
    session: _MeshEditSession,
    changed: Mapping[int, object] | None,
    *,
    mode: str,
    selection: MeshEditSelection,
) -> _MeshHistorySnapshot | None:
    deltas: list[_MeshVertexPositionDelta] = []
    for submesh_index in sorted(changed or {}):
        if not 0 <= int(submesh_index) < len(session.working_mesh.submeshes):
            continue
        submesh = session.working_mesh.submeshes[int(submesh_index)]
        raw_delta = getattr(submesh, NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR, None)
        if hasattr(submesh, NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR):
            delattr(submesh, NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR)
        delta = _coerce_vertex_position_delta(raw_delta, int(submesh_index), len(submesh.vertices or ()))
        if delta is None:
            dispose_native_mesh_history_delta(raw_delta)
            for captured in deltas:
                if captured.before_positions_binary is not None:
                    dispose_native_mesh_history_delta(captured.before_positions_binary)
            return None
        deltas.append(delta)
    if not deltas:
        return None
    return _MeshHistorySnapshot(
        mesh=None,
        mode=mode,
        selection=selection,
        edit_operations=tuple(session.edit_operations),
        vertex_position_deltas=tuple(deltas),
    )


def _coerce_vertex_position_delta(
    raw_delta: object,
    submesh_index: int,
    vertex_count: int,
) -> _MeshVertexPositionDelta | None:
    if not isinstance(raw_delta, Mapping):
        return None
    indices = _vertex_indices_from_delta_descriptor(raw_delta, vertex_count)
    if indices is None:
        return None
    native_sparse_snapshot_id = str(raw_delta.get("native_sparse_snapshot_id") or "").strip()
    raw_positions_binary = raw_delta.get("before_positions_binary")
    if isinstance(raw_positions_binary, Mapping):
        raw_path = str(raw_positions_binary.get("path") or "").strip()
        count = _coerce_index(raw_positions_binary.get("count"))
        components = _coerce_index(raw_positions_binary.get("components"))
        kind = str(raw_positions_binary.get("type") or "f64").strip().lower()
        if not raw_path or count != len(indices) or components not in (None, 3) or kind != "f64":
            return None
        return _MeshVertexPositionDelta(
            submesh_index=submesh_index,
            vertex_indices=indices,
            positions=(),
            native_sparse_snapshot_id=native_sparse_snapshot_id,
            before_positions_binary={
                "path": raw_path,
                "count": len(indices),
                "components": 3,
                "type": "f64",
            },
        )
    if native_sparse_snapshot_id and raw_delta.get("before_positions") is None:
        return _MeshVertexPositionDelta(
            submesh_index=submesh_index,
            vertex_indices=indices,
            positions=(),
            native_sparse_snapshot_id=native_sparse_snapshot_id,
        )
    positions = native_mesh_history_delta_positions(raw_delta)
    if positions is None or len(positions) != len(indices):
        return None
    return _MeshVertexPositionDelta(
        submesh_index=submesh_index,
        vertex_indices=indices,
        positions=tuple(positions),
        native_sparse_snapshot_id=native_sparse_snapshot_id,
    )


def _vertex_indices_from_delta_descriptor(raw_delta: Mapping[str, object], vertex_count: int) -> Sequence[int] | None:
    try:
        if "vertex_index_start" in raw_delta or "vertex_index_count" in raw_delta:
            raw_start = raw_delta.get("vertex_index_start", -1)
            raw_count = raw_delta.get("vertex_index_count", 0)
            start = int(raw_start if raw_start is not None else -1)
            count = int(raw_count if raw_count is not None else 0)
            if start < 0 or count <= 0 or start + count > max(0, int(vertex_count)):
                return None
            return range(start, start + count)
    except (TypeError, ValueError, OverflowError):
        return None
    raw_indices = raw_delta.get("vertex_indices")
    if not isinstance(raw_indices, (tuple, list, range)):
        return None
    indices: list[int] = []
    seen: set[int] = set()
    for raw_index in raw_indices:
        try:
            index = int(raw_index)
        except (TypeError, ValueError, OverflowError):
            return None
        if index < 0 or index >= vertex_count or index in seen:
            return None
        indices.append(index)
        seen.add(index)
    if len(indices) != len(raw_indices):
        return None
    return tuple(indices) if not isinstance(raw_indices, range) else raw_indices


def _delta_vertex_indices_payload(vertex_indices: Sequence[int]) -> dict[str, object]:
    if isinstance(vertex_indices, range) and vertex_indices.step == 1 and vertex_indices.start >= 0 and len(vertex_indices) > 0:
        return {
            "vertex_index_start": int(vertex_indices.start),
            "vertex_index_count": len(vertex_indices),
        }
    return {"vertex_indices": tuple(int(index) for index in vertex_indices)}


def _vertex_position(value: object) -> tuple[float, float, float] | None:
    try:
        position = (float(value[0]), float(value[1]), float(value[2]))  # type: ignore[index]
    except (TypeError, ValueError, OverflowError, IndexError):
        return None
    if not all(math.isfinite(component) for component in position):
        return None
    return position


def _current_vertex_position_deltas(
    mesh: ParsedMesh,
    template_deltas: tuple[_MeshVertexPositionDelta, ...],
) -> tuple[_MeshVertexPositionDelta, ...]:
    current: list[_MeshVertexPositionDelta] = []
    for delta in template_deltas:
        if not 0 <= delta.submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[delta.submesh_index]
        vertices = submesh.vertices or ()
        positions: list[tuple[float, float, float]] = []
        for index in delta.vertex_indices:
            if not 0 <= index < len(vertices):
                continue
            position = _vertex_position(vertices[index])
            if position is not None:
                positions.append(position)
        if len(positions) == len(delta.vertex_indices):
            current.append(
                _MeshVertexPositionDelta(
                    submesh_index=delta.submesh_index,
                    vertex_indices=delta.vertex_indices,
                    positions=tuple(positions),
                )
            )
    return tuple(current)


def _restore_vertex_position_deltas(
    mesh: ParsedMesh,
    deltas: tuple[_MeshVertexPositionDelta, ...],
) -> tuple[_MeshVertexPositionDelta, ...]:
    restore_positions: dict[int, object] = {}
    for delta in deltas:
        if not 0 <= delta.submesh_index < len(mesh.submeshes):
            continue
        if delta.native_sparse_snapshot_id or delta.before_positions_binary is not None:
            group: dict[str, object] = _delta_vertex_indices_payload(delta.vertex_indices)
            if delta.native_sparse_snapshot_id:
                group["native_sparse_snapshot_id"] = delta.native_sparse_snapshot_id
            if delta.before_positions_binary is not None:
                group["before_positions_binary"] = delta.before_positions_binary
            restore_positions[int(delta.submesh_index)] = group
            continue
        positions_by_vertex: dict[int, tuple[float, float, float]] = {}
        vertex_count = len(mesh.submeshes[delta.submesh_index].vertices or ())
        for index, position in zip(delta.vertex_indices, delta.positions):
            if 0 <= index < vertex_count:
                positions_by_vertex[int(index)] = position
        if positions_by_vertex:
            restore_positions[int(delta.submesh_index)] = positions_by_vertex
    if not restore_positions:
        return ()

    affected: set[int] = set()
    current_deltas: tuple[_MeshVertexPositionDelta, ...] = ()
    native_restore = _service_call(
        "apply_native_mesh_sparse_vertex_restore",
        mesh,
        restore_positions,
        history_delta=True,
    )
    if native_restore is not None:
        affected = {
            int(submesh_index)
            for submesh_index, changed_vertices in (native_restore or {}).items()
            if changed_vertices
        }
        if affected:
            captured: list[_MeshVertexPositionDelta] = []
            for submesh_index in sorted(affected):
                if not 0 <= submesh_index < len(mesh.submeshes):
                    continue
                submesh = mesh.submeshes[submesh_index]
                raw_delta = getattr(submesh, NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR, None)
                if hasattr(submesh, NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR):
                    delattr(submesh, NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR)
                delta = _coerce_vertex_position_delta(raw_delta, submesh_index, len(submesh.vertices or ()))
                if delta is not None:
                    captured.append(delta)
            current_deltas = tuple(captured)
    if not affected:
        if not _allow_python_history_restore_fallback(mesh, deltas, "history.sparse_restore"):
            raise RuntimeError("native sparse history restore failed and Python fallback was blocked")
        current_deltas = _current_vertex_position_deltas(mesh, deltas)
        for delta in deltas:
            submesh_index = int(delta.submesh_index)
            positions_by_vertex = _delta_positions_by_vertex(delta)
            if not positions_by_vertex or not 0 <= submesh_index < len(mesh.submeshes):
                continue
            submesh = mesh.submeshes[submesh_index]
            vertices = list(submesh.vertices or ())
            if not vertices:
                continue
            changed = False
            for index, position in positions_by_vertex.items():
                vertices[index] = position
                changed = True
            if changed:
                submesh.vertices = vertices
                submesh.vertex_count = len(vertices)
                affected.add(submesh_index)
    if affected:
        native_normals = _service_call("apply_native_mesh_recalculate_normals", mesh, affected)
        if native_normals is None:
            if not _allow_python_history_restore_fallback(mesh, deltas, "history.restore_normals"):
                raise RuntimeError("native history normal recompute failed and Python fallback was blocked")
            for submesh_index in affected:
                if 0 <= submesh_index < len(mesh.submeshes):
                    _service_call("recompute_mesh_normals", mesh)
                    break
    return current_deltas


def _allow_python_history_restore_fallback(
    mesh: ParsedMesh,
    deltas: tuple[_MeshVertexPositionDelta, ...],
    operation: str,
) -> bool:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return True
    if not _service_call("native_mesh_core_available"):
        return True
    vertex_count = _mesh_count_hint(mesh, "total_vertices")
    face_count = _mesh_count_hint(mesh, "total_faces")
    changed_vertex_count = sum(len(delta.vertex_indices or ()) for delta in deltas)
    _service_call(
        "record_native_mesh_core_fallback",
        f"{operation}.blocked",
        "Python mesh history restore fallback blocked while native mesh core is available",
        vertex_count=vertex_count,
        face_count=face_count,
        changed_vertex_count=changed_vertex_count,
    )
    return False


def _allow_python_history_snapshot_fallback(mesh: ParsedMesh, operation: str) -> bool:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return True
    if not _service_call("native_mesh_core_available"):
        return True
    vertex_count = _mesh_count_hint(mesh, "total_vertices")
    face_count = _mesh_count_hint(mesh, "total_faces")
    _service_call(
        "record_native_mesh_core_fallback",
        f"{operation}.blocked",
        "Python mesh history snapshot fallback blocked while native mesh core is available",
        vertex_count=vertex_count,
        face_count=face_count,
    )
    return False


def _allow_python_service_clone_fallback(mesh: ParsedMesh, operation: str, reason: str) -> bool:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return True
    if not _service_call("native_mesh_core_available"):
        return True
    vertex_count = _mesh_count_hint(mesh, "total_vertices")
    face_count = _mesh_count_hint(mesh, "total_faces")
    _service_call(
        "record_native_mesh_core_fallback",
        f"{operation}.blocked",
        reason,
        vertex_count=vertex_count,
        face_count=face_count,
    )
    return False


def _allow_python_pose_preview_fallback(mesh: ParsedMesh, operation: str) -> bool:
    vertex_count = _mesh_count_hint(mesh, "total_vertices")
    face_count = _mesh_count_hint(mesh, "total_faces")
    _service_call(
        "record_native_mesh_core_fallback",
        f"{operation}.blocked",
        "Python pose preview fallback blocked; native mesh core is required for active Mesh Editor pose preview",
        vertex_count=vertex_count,
        face_count=face_count,
        native_core_available=bool(_service_call("native_mesh_core_available")),
        native_core_disabled=bool(os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip()),
    )
    return False


def _allow_python_skin_weight_fallback(
    mesh: ParsedMesh,
    selected_vertices_by_submesh: Mapping[int, Iterable[int]],
    selected_all_submeshes: Iterable[int],
    operation: str,
) -> bool:
    vertex_count = _mesh_count_hint(mesh, "total_vertices")
    face_count = _mesh_count_hint(mesh, "total_faces")
    selected_vertex_count = _selected_skin_weight_vertex_count(mesh, selected_vertices_by_submesh, selected_all_submeshes)
    _service_call(
        "record_native_mesh_core_fallback",
        f"{operation}.blocked",
        "Python skin weight fallback blocked; native mesh core is required for active Mesh Editor skin-weight edits",
        vertex_count=vertex_count,
        face_count=face_count,
        selected_vertex_count=selected_vertex_count,
        native_core_available=bool(_service_call("native_mesh_core_available")),
        native_core_disabled=bool(os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip()),
    )
    return False


def _delta_positions_by_vertex(delta: _MeshVertexPositionDelta) -> dict[int, tuple[float, float, float]]:
    if delta.positions:
        return {
            int(index): position
            for index, position in zip(delta.vertex_indices, delta.positions)
        }
    raw_delta = {
        **_delta_vertex_indices_payload(delta.vertex_indices),
        "before_positions_binary": delta.before_positions_binary,
    }
    positions = native_mesh_history_delta_positions(raw_delta)
    if positions is None or len(positions) != len(delta.vertex_indices):
        return {}
    return {
        int(index): position
        for index, position in zip(delta.vertex_indices, positions)
    }

__all__ = [
    "_NATIVE_EDITOR_SESSION_ACTIONS",
    "_abandon_lost_native_editor_session",
    "_allow_python_history_restore_fallback",
    "_allow_python_history_snapshot_fallback",
    "_allow_python_pose_preview_fallback",
    "_allow_python_service_clone_fallback",
    "_allow_python_skin_weight_fallback",
    "_apply_native_editor_session_geometry_action",
    "_apply_native_editor_session_selection_operation",
    "_close_native_editor_session",
    "_coerce_vertex_position_delta",
    "_current_vertex_position_deltas",
    "_delta_positions_by_vertex",
    "_native_live_history_snapshot",
    "_refresh_native_editor_session_if_mesh_changed",
    "_restore_vertex_position_deltas",
    "_sync_native_editor_session_to_working_mesh",
]
