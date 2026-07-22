from __future__ import annotations

import sys
import time
from dataclasses import replace
from typing import Mapping, Sequence

from cdmw.domain.mesh import MeshEditResult
from cdmw.modding.mesh_edit_ops import refresh_mesh_totals
from cdmw.services.mesh_service_kernel import _apply_native_editor_dirty_counts
from cdmw.services.mesh_service_payloads import _coerce_metrics
from cdmw.services.mesh_service_reports import _changed_vertex_indices_for_result, _coerce_index
from cdmw.services.mesh_service_state import _MeshEditSession, _MeshHistorySnapshot

def _history_stack_retained_bytes(stack: Sequence[_MeshHistorySnapshot]) -> int:
    return sum(max(0, int(snapshot.retained_bytes or _history_snapshot_retained_bytes(snapshot))) for snapshot in stack)


def _history_snapshot_retained_bytes(snapshot: _MeshHistorySnapshot) -> int:
    if snapshot.retained_bytes > 0:
        return int(snapshot.retained_bytes)
    retained = _history_value_retained_bytes(
        (
            snapshot.mesh,
            snapshot.mode,
            snapshot.selection,
            snapshot.edit_operations,
            snapshot.vertex_position_deltas,
            snapshot.native_submesh_snapshot,
            snapshot.native_editor_history,
            snapshot.native_editor_stroke_id,
            snapshot.material_generation,
            snapshot.committed_texture_resources,
        )
    )
    if snapshot.native_submesh_snapshot is not None:
        retained += _native_submesh_snapshot_payload_bytes(snapshot.native_submesh_snapshot)
    for delta in snapshot.vertex_position_deltas:
        if delta.native_sparse_snapshot_id or delta.before_positions_binary is not None:
            retained += len(delta.vertex_indices) * 3 * 8
    return max(1, retained)


def _history_value_retained_bytes(value: object, seen: set[int] | None = None) -> int:
    if value is None:
        return 0
    if seen is None:
        seen = set()
    value_id = id(value)
    if value_id in seen:
        return 0
    seen.add(value_id)
    try:
        retained = sys.getsizeof(value)
    except TypeError:
        retained = 0
    if isinstance(value, Mapping):
        return retained + sum(
            _history_value_retained_bytes(key, seen) + _history_value_retained_bytes(item, seen)
            for key, item in value.items()
        )
    if isinstance(value, range):
        return retained
    if isinstance(value, (tuple, list, set, frozenset)):
        return retained + sum(_history_value_retained_bytes(item, seen) for item in value)
    raw_attrs = getattr(value, "__dict__", None)
    if isinstance(raw_attrs, Mapping):
        retained += _history_value_retained_bytes(raw_attrs, seen)
    slots = getattr(type(value), "__slots__", ())
    if isinstance(slots, str):
        slots = (slots,)
    for name in slots:
        if name == "__dict__" or not hasattr(value, name):
            continue
        retained += _history_value_retained_bytes(getattr(value, name), seen)
    return retained


def _native_submesh_snapshot_payload_bytes(snapshot: Mapping[str, object]) -> int:
    retained = 0
    raw_submeshes = snapshot.get("submeshes")
    for item in raw_submeshes if isinstance(raw_submeshes, list) else ():
        if not isinstance(item, Mapping):
            continue
        for key, descriptor in item.items():
            if not str(key).endswith("_binary") or not isinstance(descriptor, Mapping):
                continue
            count = _coerce_index(descriptor.get("count")) or 0
            components = _coerce_index(descriptor.get("components")) or 1
            kind = str(descriptor.get("type") or "").lower()
            component_bytes = 8 if kind == "f64" else 4
            retained += max(0, count) * max(1, components) * component_bytes
    return retained


def _history_metrics(session: _MeshEditSession) -> dict[str, float]:
    python_retained = _history_stack_retained_bytes(session.undo_stack) + _history_stack_retained_bytes(session.redo_stack)
    return {
        "python_history_undo_count": float(len(session.undo_stack)),
        "python_history_redo_count": float(len(session.redo_stack)),
        "python_history_retained_bytes": float(python_retained),
        "native_history_undo_count": float(session.native_history_undo_count),
        "native_history_redo_count": float(session.native_history_redo_count),
        "native_history_retained_bytes": float(session.native_history_retained_bytes),
        "history_retained_bytes": float(python_retained + session.native_history_retained_bytes),
    }



def _service_call(name: str, *args: object, **kwargs: object) -> object:
    return getattr(sys.modules["cdmw.services.mesh_service"], name)(*args, **kwargs)


class MeshHistoryServiceMixin:
    def undo(self, session_id: str) -> MeshEditResult:
        session = self._session(session_id)
        with session.export_lock:
            return self._undo_locked(session)

    def _undo_locked(self, session: _MeshEditSession) -> MeshEditResult:
        service_started = time.perf_counter()
        if not session.undo_stack:
            return self._result(session, "undo", status="noop")
        if (
            session.native_editor_mesh_dirty
            and not session.undo_stack[-1].native_editor_history
            and not session.undo_stack[-1].selection_only
        ):
            raise RuntimeError("native mesh editor undo requires native history; Python mesh state is stale")
        snapshot = session.undo_stack.pop()
        native_editor_history = snapshot.native_editor_history
        if native_editor_history:
            outcome = _service_call("_restore_native_editor_history", session, snapshot, "undo")
        else:
            outcome = _service_call("_restore_snapshot", session, snapshot)
        _service_call("_dispose_history_snapshot", snapshot)
        self._append_history_snapshot(session.redo_stack, outcome.snapshot)
        self._trim_session_history(session)
        history_counts = _service_call("_update_native_history_usage", session, outcome.metrics)
        _service_call("_trim_native_history_markers", session, *history_counts)
        self._trim_session_history(session)
        session.revision += 1
        finalize_started = time.perf_counter()
        if session.native_editor_mesh_dirty:
            _apply_native_editor_dirty_counts(session)
        else:
            refresh_mesh_totals(session.working_mesh)
            session.selection = _service_call("_prune_selection_to_mesh", session.working_mesh, session.selection)
        if native_editor_history:
            self._refresh_cached_morph_after_history_locked(
                session,
                topology_changed=outcome.topology_changed,
            )
        metrics = dict(outcome.metrics)
        metrics["service_finalize_ms"] = max(0.0, (time.perf_counter() - finalize_started) * 1000.0)
        result = self._result(
            session,
            "undo",
            affected=outcome.affected_submesh_indices,
            changed=outcome.changed_vertices_by_submesh,
            native_preview_vertex_update_groups=outcome.native_preview_vertex_update_groups,
            native_preview_triangle_groups=outcome.native_preview_triangle_groups,
            topology_changed=outcome.topology_changed,
            submesh_count_delta=outcome.submesh_count_delta,
            submesh_counts=outcome.submesh_counts,
            metrics=metrics,
        )
        final_metrics = dict(result.metrics)
        final_metrics["service_total_ms"] = max(0.0, (time.perf_counter() - service_started) * 1000.0)
        return replace(result, metrics=final_metrics)

    def redo(self, session_id: str) -> MeshEditResult:
        session = self._session(session_id)
        with session.export_lock:
            return self._redo_locked(session)

    def _redo_locked(self, session: _MeshEditSession) -> MeshEditResult:
        service_started = time.perf_counter()
        if not session.redo_stack:
            return self._result(session, "redo", status="noop")
        if (
            session.native_editor_mesh_dirty
            and not session.redo_stack[-1].native_editor_history
            and not session.redo_stack[-1].selection_only
        ):
            raise RuntimeError("native mesh editor redo requires native history; Python mesh state is stale")
        snapshot = session.redo_stack.pop()
        native_editor_history = snapshot.native_editor_history
        if native_editor_history:
            outcome = _service_call("_restore_native_editor_history", session, snapshot, "redo")
        else:
            outcome = _service_call("_restore_snapshot", session, snapshot)
        _service_call("_dispose_history_snapshot", snapshot)
        self._append_history_snapshot(session.undo_stack, outcome.snapshot)
        self._trim_session_history(session)
        history_counts = _service_call("_update_native_history_usage", session, outcome.metrics)
        _service_call("_trim_native_history_markers", session, *history_counts)
        self._trim_session_history(session)
        session.revision += 1
        finalize_started = time.perf_counter()
        if session.native_editor_mesh_dirty:
            _apply_native_editor_dirty_counts(session)
        else:
            refresh_mesh_totals(session.working_mesh)
            session.selection = _service_call("_prune_selection_to_mesh", session.working_mesh, session.selection)
        if native_editor_history:
            self._refresh_cached_morph_after_history_locked(
                session,
                topology_changed=outcome.topology_changed,
            )
        metrics = dict(outcome.metrics)
        metrics["service_finalize_ms"] = max(0.0, (time.perf_counter() - finalize_started) * 1000.0)
        result = self._result(
            session,
            "redo",
            affected=outcome.affected_submesh_indices,
            changed=outcome.changed_vertices_by_submesh,
            native_preview_vertex_update_groups=outcome.native_preview_vertex_update_groups,
            native_preview_triangle_groups=outcome.native_preview_triangle_groups,
            topology_changed=outcome.topology_changed,
            submesh_count_delta=outcome.submesh_count_delta,
            submesh_counts=outcome.submesh_counts,
            metrics=metrics,
        )
        final_metrics = dict(result.metrics)
        final_metrics["service_total_ms"] = max(0.0, (time.perf_counter() - service_started) * 1000.0)
        return replace(result, metrics=final_metrics)

    def _session(self, session_id: str) -> _MeshEditSession:
        session = self._sessions.get(str(session_id))
        if session is None:
            raise KeyError(f"Unknown mesh edit session: {session_id}")
        return session

    def _push_history(
        self,
        session: _MeshEditSession,
        *,
        prefer_native: bool = False,
        action: str = "",
        label: str = "",
    ) -> None:
        snapshot = _service_call("_snapshot", session, prefer_native=prefer_native)
        snapshot.history_action = str(action or "")
        snapshot.history_label = str(label or "")
        self._push_history_snapshot(session, snapshot)

    def _push_history_snapshot(self, session: _MeshEditSession, snapshot: _MeshHistorySnapshot) -> None:
        _service_call("_capture_history_material_state", session, snapshot)
        self._append_history_snapshot(session.undo_stack, snapshot)

    def _append_history_snapshot(
        self,
        stack: list[_MeshHistorySnapshot],
        snapshot: _MeshHistorySnapshot,
    ) -> None:
        snapshot.retained_bytes = _history_snapshot_retained_bytes(snapshot)
        stack.append(snapshot)
        max_count = max(1, int(self.max_history or 1))
        max_bytes = max(0, int(self.max_history_bytes or 0))
        while stack and (len(stack) > max_count or _history_stack_retained_bytes(stack) > max_bytes):
            _service_call("_discard_history_snapshot", stack, 0)

    def _trim_session_history(self, session: _MeshEditSession) -> None:
        max_count = max(1, int(self.max_history or 1))
        max_bytes = max(0, int(self.max_history_bytes or 0))
        while session.undo_stack or session.redo_stack:
            retained = _history_stack_retained_bytes(session.undo_stack) + _history_stack_retained_bytes(session.redo_stack)
            if (
                len(session.undo_stack) + len(session.redo_stack) <= max_count
                and retained + session.native_history_retained_bytes <= max_bytes
            ):
                return
            stack = session.undo_stack if session.undo_stack else session.redo_stack
            _service_call("_discard_history_snapshot", stack, 0)

    def _result(
        self,
        session: _MeshEditSession,
        action: str,
        *,
        status: str = "ok",
        affected: set[int] | tuple[int, ...] = (),
        changed: Mapping[int, object] | None = None,
        native_selection_groups: Sequence[Mapping[str, object]] = (),
        native_preview_vertex_update_groups: Sequence[Mapping[str, object]] = (),
        native_preview_triangle_groups: Sequence[Mapping[str, object]] = (),
        topology_changed: bool = False,
        submesh_count_delta: int = 0,
        submesh_counts: Sequence[tuple[int, int]] = (),
        diagnostics: tuple[str, ...] = (),
        metrics: Mapping[str, object] | None = None,
    ) -> MeshEditResult:
        changed_items: list[tuple[int, Sequence[int] | set[int]]] = []
        for raw_submesh_index, indices in sorted((changed or {}).items()):
            try:
                submesh_index = int(raw_submesh_index)
            except (TypeError, ValueError, OverflowError):
                continue
            normalized_indices = _changed_vertex_indices_for_result(indices)
            if normalized_indices:
                changed_items.append((submesh_index, normalized_indices))
        result_metrics = _coerce_metrics(metrics)
        result_metrics.update(_history_metrics(session))
        return MeshEditResult(
            action=action,
            status=status,
            revision=session.revision,
            affected_submesh_indices=tuple(sorted(set(affected))),
            changed_vertices_by_submesh=tuple(changed_items),
            native_selection_groups=tuple(dict(group) for group in native_selection_groups),
            native_preview_vertex_update_groups=tuple(dict(group) for group in native_preview_vertex_update_groups),
            native_preview_triangle_groups=tuple(dict(group) for group in native_preview_triangle_groups),
            topology_changed=topology_changed,
            submesh_count_delta=int(submesh_count_delta),
            submesh_counts=tuple((int(vertices), int(faces)) for vertices, faces in submesh_counts),
            diagnostics=diagnostics,
            metrics=result_metrics,
        )
