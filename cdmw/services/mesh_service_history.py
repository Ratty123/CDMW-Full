from __future__ import annotations

import hashlib
import os
import shutil
import stat
import sys
import time
import ctypes
from contextlib import contextmanager, nullcontext
from ctypes import wintypes
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Mapping, Sequence
from uuid import uuid4

from cdmw.domain.mesh import MeshEditResult
from cdmw.modding.mesh_edit_ops import refresh_mesh_totals
from cdmw.services.mesh_service_kernel import _apply_native_editor_dirty_counts
from cdmw.services.mesh_service_payloads import _coerce_metrics
from cdmw.services.mesh_service_reports import _changed_vertex_indices_for_result, _coerce_index
from cdmw.services.mesh_service_state import (
    _MeshEditSession,
    _MeshGeometryLayer,
    _MeshHistorySnapshot,
    _MeshRestoreOutcome,
)

from cdmw.services.mesh_service_history_files import (
    _mesh_morph_profile_directory_state,
    _mesh_history_path_is_link,
    _mesh_history_directory_identity,
    _pinned_mesh_history_parent,
    _mesh_morph_profile_state_fingerprint,
    _validated_mesh_morph_profile_files,
    _restore_mesh_morph_profile_directory_state,
    _validate_mesh_morph_profile_history_state,
    _MESH_MORPH_PROFILE_MAX_DEPTH,
    _MESH_MORPH_PROFILE_MAX_ENTRIES,
    _MESH_MORPH_PROFILE_MAX_FILE_BYTES,
    _MESH_MORPH_PROFILE_MAX_TOTAL_BYTES,
)


@dataclass(slots=True)
class _MeshTransactionalRestoreCheckpoint:
    """Full pre-restore state used for reciprocal history or atomic rollback."""

    snapshot: _MeshHistorySnapshot
    revision: int
    selection_revision: int
    geometry_layer_revision: int
    morph_session_revision: int
    material_generation: int
    committed_texture_resources: dict[tuple[str, str], object]
    native_editor_selection_signature: tuple[object, ...]
    native_history_undo_count: int
    native_history_redo_count: int
    native_history_retained_bytes: int


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
            snapshot.geometry_layers,
            snapshot.active_geometry_layer_id,
            snapshot.geometry_layer_copy_counter,
            snapshot.restore_geometry_layer_state,
            snapshot.output_policy,
            snapshot.output_destination,
            snapshot.output_destination_ready,
            snapshot.morph_profile_root,
            snapshot.morph_profile_root_existed,
            snapshot.morph_profile_files,
            snapshot.morph_profile_expected_fingerprint,
            snapshot.morph_session_state,
            snapshot.material_generation,
            snapshot.committed_texture_resources,
            snapshot.object_transform,
            snapshot.archive_refit_context,
        )
    )
    if snapshot.native_submesh_snapshot is not None:
        retained += _native_submesh_snapshot_payload_bytes(snapshot.native_submesh_snapshot)
    for delta in snapshot.vertex_position_deltas:
        if delta.native_sparse_snapshot_id or delta.before_positions_binary is not None:
            retained += len(delta.vertex_indices) * 3 * 8
    if snapshot.morph_session_state is not None:
        retained += max(0, int(snapshot.morph_session_state.retained_bytes or 0))
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


def _dispose_history_snapshot_without_state_failure(
    snapshot: _MeshHistorySnapshot,
) -> bool:
    """Release an owned snapshot without turning cleanup into an editor rollback."""

    try:
        _service_call("_dispose_history_snapshot", snapshot)
        return True
    except Exception:
        morph_state = snapshot.morph_session_state
        if morph_state is not None:
            from cdmw.services.mesh_service_morph import (
                defer_mesh_morph_session_state_disposal,
            )

            snapshot.morph_session_state = None
            try:
                defer_mesh_morph_session_state_disposal(morph_state)
            except Exception:
                pass
        return False


class MeshHistoryServiceMixin:
    def _publish_history_reciprocal_locked(
        self,
        session: _MeshEditSession,
        reciprocal: _MeshHistorySnapshot,
        *,
        target: str,
        metrics: Mapping[str, object],
    ) -> bool:
        """Publish Undo/Redo bookkeeping after restore without downgrading it."""

        cleanup_ok = True
        installed_removed: list[_MeshHistorySnapshot] = []

        def bounded(
            undo: list[_MeshHistorySnapshot],
            redo: list[_MeshHistorySnapshot],
        ) -> tuple[
            list[_MeshHistorySnapshot],
            list[_MeshHistorySnapshot],
            list[_MeshHistorySnapshot],
        ]:
            removed: list[_MeshHistorySnapshot] = []
            max_count = max(1, int(self.max_history or 1))
            max_bytes = max(0, int(self.max_history_bytes or 0))
            while undo or redo:
                retained = _history_stack_retained_bytes(
                    undo
                ) + _history_stack_retained_bytes(redo)
                if (
                    len(undo) + len(redo) <= max_count
                    and retained + session.native_history_retained_bytes <= max_bytes
                ):
                    break
                trim_stack = undo if undo else redo
                removed.append(trim_stack.pop(0))
            return undo, redo, removed

        try:
            reciprocal.retained_bytes = _history_snapshot_retained_bytes(
                reciprocal
            )
            next_undo = list(session.undo_stack)
            next_redo = list(session.redo_stack)
            (next_redo if target == "redo" else next_undo).append(reciprocal)
            next_undo, next_redo, removed = bounded(next_undo, next_redo)
        except Exception:
            # A restored semantic state is more important than optional budget
            # cleanup. Preserve its reciprocal and retry bounded cleanup later.
            cleanup_ok = False
            next_undo = list(session.undo_stack)
            next_redo = list(session.redo_stack)
            (next_redo if target == "redo" else next_undo).append(reciprocal)
            removed = []
        session.undo_stack[:] = next_undo
        session.redo_stack[:] = next_redo
        installed_removed.extend(removed)
        session.revision += 1

        try:
            history_counts = _service_call(
                "_update_native_history_usage",
                session,
                metrics,
            )
            _service_call(
                "_trim_native_history_markers",
                session,
                *history_counts,
            )
        except Exception:
            cleanup_ok = False
        try:
            next_undo, next_redo, removed = bounded(
                list(session.undo_stack),
                list(session.redo_stack),
            )
            session.undo_stack[:] = next_undo
            session.redo_stack[:] = next_redo
            installed_removed.extend(removed)
        except Exception:
            cleanup_ok = False
        for discarded in installed_removed:
            cleanup_ok = (
                _dispose_history_snapshot_without_state_failure(discarded)
                and cleanup_ok
            )
        return cleanup_ok

    def undo(self, session_id: str) -> MeshEditResult:
        session = self._session(session_id)
        with session.export_lock:
            snapshot = session.undo_stack[-1] if session.undo_stack else None
            profile_lock = self._history_profile_lock(snapshot)
            with profile_lock:
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
        _service_call("_validate_mesh_morph_profile_history_state", session.undo_stack[-1])
        snapshot = session.undo_stack.pop()
        native_editor_history = snapshot.native_editor_history
        try:
            if native_editor_history:
                outcome = _service_call("_restore_native_editor_history", session, snapshot, "undo")
            else:
                outcome = self._restore_snapshot_with_morph_locked(session, snapshot)
        except Exception:
            session.undo_stack.append(snapshot)
            raise
        if snapshot.morph_profile_root is not None and snapshot.morph_session_state is None:
            self._morph_sessions.pop(session.session_id, None)
        history_publication_cleanup_ok = self._publish_history_reciprocal_locked(
            session,
            outcome.snapshot,
            target="redo",
            metrics=outcome.metrics,
        )
        history_snapshot_cleanup_ok = _dispose_history_snapshot_without_state_failure(
            snapshot
        )
        finalize_started = time.perf_counter()
        history_finalize_deferred = False
        try:
            if session.native_editor_mesh_dirty:
                _apply_native_editor_dirty_counts(session)
            else:
                refresh_mesh_totals(session.working_mesh)
                session.selection = _service_call(
                    "_prune_selection_to_mesh",
                    session.working_mesh,
                    session.selection,
                )
            if native_editor_history:
                self._refresh_cached_morph_after_history_locked(
                    session,
                    topology_changed=outcome.topology_changed,
                )
        except Exception as exc:
            # The history cursor and semantic state are already committed. A
            # cache/preview refresh must not make the caller retry another step.
            history_finalize_deferred = True
            self._morph_sessions.pop(session.session_id, None)
            session.mesh_layer_autosave_error = f"{type(exc).__name__}: {exc}"
        metrics = dict(outcome.metrics)
        metrics["history_snapshot_cleanup_deferred"] = (
            0.0
            if history_snapshot_cleanup_ok and history_publication_cleanup_ok
            else 1.0
        )
        metrics["history_finalize_deferred"] = 1.0 if history_finalize_deferred else 0.0
        metrics["service_finalize_ms"] = max(0.0, (time.perf_counter() - finalize_started) * 1000.0)
        result = self._result(
            session,
            "undo",
            affected=outcome.affected_submesh_indices,
            changed=outcome.changed_vertices_by_submesh,
            native_selection_groups=outcome.native_selection_groups,
            native_preview_vertex_update_groups=outcome.native_preview_vertex_update_groups,
            native_preview_triangle_groups=outcome.native_preview_triangle_groups,
            topology_changed=outcome.topology_changed,
            submesh_count_delta=outcome.submesh_count_delta,
            submesh_counts=outcome.submesh_counts,
            metrics=metrics,
        )
        final_metrics = dict(result.metrics)
        final_metrics["service_total_ms"] = max(0.0, (time.perf_counter() - service_started) * 1000.0)
        autosave = getattr(self, "_schedule_mesh_layer_autosave", None)
        if callable(autosave):
            try:
                autosave(session)
            except Exception:
                final_metrics["history_autosave_deferred"] = 1.0
        return replace(result, metrics=final_metrics)

    def redo(self, session_id: str) -> MeshEditResult:
        session = self._session(session_id)
        with session.export_lock:
            snapshot = session.redo_stack[-1] if session.redo_stack else None
            profile_lock = self._history_profile_lock(snapshot)
            with profile_lock:
                return self._redo_locked(session)

    @staticmethod
    def _history_profile_lock(snapshot: _MeshHistorySnapshot | None):
        if snapshot is None or snapshot.morph_profile_root is None:
            return nullcontext()
        # Imported lazily to keep the history primitives independent while all
        # profile publication paths still share the same root-keyed lock.
        from cdmw.services.mesh_service_morph import mesh_morph_profile_lock

        return mesh_morph_profile_lock(snapshot.morph_profile_root)

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
        _service_call("_validate_mesh_morph_profile_history_state", session.redo_stack[-1])
        snapshot = session.redo_stack.pop()
        native_editor_history = snapshot.native_editor_history
        try:
            if native_editor_history:
                outcome = _service_call("_restore_native_editor_history", session, snapshot, "redo")
            else:
                outcome = self._restore_snapshot_with_morph_locked(session, snapshot)
        except Exception:
            session.redo_stack.append(snapshot)
            raise
        if snapshot.morph_profile_root is not None and snapshot.morph_session_state is None:
            self._morph_sessions.pop(session.session_id, None)
        history_publication_cleanup_ok = self._publish_history_reciprocal_locked(
            session,
            outcome.snapshot,
            target="undo",
            metrics=outcome.metrics,
        )
        history_snapshot_cleanup_ok = _dispose_history_snapshot_without_state_failure(
            snapshot
        )
        finalize_started = time.perf_counter()
        history_finalize_deferred = False
        try:
            if session.native_editor_mesh_dirty:
                _apply_native_editor_dirty_counts(session)
            else:
                refresh_mesh_totals(session.working_mesh)
                session.selection = _service_call(
                    "_prune_selection_to_mesh",
                    session.working_mesh,
                    session.selection,
                )
            if native_editor_history:
                self._refresh_cached_morph_after_history_locked(
                    session,
                    topology_changed=outcome.topology_changed,
                )
        except Exception as exc:
            history_finalize_deferred = True
            self._morph_sessions.pop(session.session_id, None)
            session.mesh_layer_autosave_error = f"{type(exc).__name__}: {exc}"
        metrics = dict(outcome.metrics)
        metrics["history_snapshot_cleanup_deferred"] = (
            0.0
            if history_snapshot_cleanup_ok and history_publication_cleanup_ok
            else 1.0
        )
        metrics["history_finalize_deferred"] = 1.0 if history_finalize_deferred else 0.0
        metrics["service_finalize_ms"] = max(0.0, (time.perf_counter() - finalize_started) * 1000.0)
        result = self._result(
            session,
            "redo",
            affected=outcome.affected_submesh_indices,
            changed=outcome.changed_vertices_by_submesh,
            native_selection_groups=outcome.native_selection_groups,
            native_preview_vertex_update_groups=outcome.native_preview_vertex_update_groups,
            native_preview_triangle_groups=outcome.native_preview_triangle_groups,
            topology_changed=outcome.topology_changed,
            submesh_count_delta=outcome.submesh_count_delta,
            submesh_counts=outcome.submesh_counts,
            metrics=metrics,
        )
        final_metrics = dict(result.metrics)
        final_metrics["service_total_ms"] = max(0.0, (time.perf_counter() - service_started) * 1000.0)
        autosave = getattr(self, "_schedule_mesh_layer_autosave", None)
        if callable(autosave):
            try:
                autosave(session)
            except Exception:
                final_metrics["history_autosave_deferred"] = 1.0
        return replace(result, metrics=final_metrics)

    def _restore_snapshot_with_morph_locked(
        self,
        session: _MeshEditSession,
        snapshot: _MeshHistorySnapshot,
    ) -> _MeshRestoreOutcome:
        """Restore geometry and its resident Morph runtime as one history step."""

        target_morph = snapshot.morph_session_state
        if target_morph is None and snapshot.morph_profile_root is None:
            return _service_call("_restore_snapshot", session, snapshot)

        checkpoint = self._capture_transactional_restore_checkpoint_locked(
            session,
            snapshot,
        )
        generated_reciprocal: _MeshHistorySnapshot | None = None
        try:
            outcome = _service_call("_restore_snapshot", session, snapshot)
            if target_morph is not None:
                self._install_morph_session_state_locked(session, target_morph)
            generated_reciprocal = outcome.snapshot
            outcome.snapshot = checkpoint.snapshot
            outcome.snapshot.retained_bytes = 0
            outcome.snapshot.retained_bytes = _history_snapshot_retained_bytes(
                outcome.snapshot,
            )
        except Exception:
            try:
                self._rollback_transactional_restore_locked(session, checkpoint)
            except Exception as rollback_error:
                raise RuntimeError(
                    "Mesh history restore failed and its atomic rollback could not be completed."
                ) from rollback_error
            raise
        if generated_reciprocal is not None:
            _dispose_history_snapshot_without_state_failure(generated_reciprocal)
        return outcome

    def _capture_transactional_restore_checkpoint_locked(
        self,
        session: _MeshEditSession,
        template: _MeshHistorySnapshot,
    ) -> _MeshTransactionalRestoreCheckpoint:
        checkpoint = _service_call("_snapshot", session)
        try:
            checkpoint.history_action = template.history_action
            checkpoint.history_label = template.history_label
            checkpoint.selection_only = template.selection_only
            checkpoint.native_editor_stroke_id = template.native_editor_stroke_id
            _service_call("_capture_history_material_state", session, checkpoint)
            _service_call(
                "_capture_history_session_state",
                session,
                checkpoint,
                template,
            )
            if template.morph_session_state is not None:
                checkpoint.morph_session_state = (
                    self._capture_morph_session_state_locked(session)
                )
            checkpoint.retained_bytes = _history_snapshot_retained_bytes(checkpoint)
            return _MeshTransactionalRestoreCheckpoint(
                snapshot=checkpoint,
                revision=int(session.revision),
                selection_revision=int(session.selection_revision),
                geometry_layer_revision=int(session.geometry_layer_revision),
                morph_session_revision=int(session.morph_session_revision),
                material_generation=int(session.material_generation),
                committed_texture_resources=dict(session.committed_texture_resources),
                native_editor_selection_signature=tuple(
                    session.native_editor_selection_signature
                ),
                native_history_undo_count=int(session.native_history_undo_count),
                native_history_redo_count=int(session.native_history_redo_count),
                native_history_retained_bytes=int(
                    session.native_history_retained_bytes
                ),
            )
        except Exception:
            _dispose_history_snapshot_without_state_failure(checkpoint)
            raise

    def _rollback_transactional_restore_locked(
        self,
        session: _MeshEditSession,
        checkpoint: _MeshTransactionalRestoreCheckpoint,
    ) -> None:
        """Restore the checkpoint without replaying the failed profile operation."""

        rollback_marker = replace(
            checkpoint.snapshot,
            morph_profile_root=None,
            morph_profile_root_existed=None,
            morph_profile_files=None,
            morph_profile_expected_fingerprint=None,
            morph_session_state=None,
            retained_bytes=0,
        )
        rollback_outcome: _MeshRestoreOutcome | None = None
        rollback_errors: list[Exception] = []
        invalid_native_markers: list[_MeshHistorySnapshot] = []
        try:
            try:
                rollback_outcome = _service_call(
                    "_restore_snapshot",
                    session,
                    rollback_marker,
                )
            except Exception as exc:
                rollback_errors.append(exc)

            if rollback_outcome is not None and checkpoint.snapshot.morph_profile_root is not None:
                try:
                    current_fingerprint = _mesh_morph_profile_directory_state(
                        checkpoint.snapshot.morph_profile_root
                    )[2]
                    _restore_mesh_morph_profile_directory_state(
                        checkpoint.snapshot.morph_profile_root,
                        existed=bool(checkpoint.snapshot.morph_profile_root_existed),
                        files=tuple(checkpoint.snapshot.morph_profile_files or ()),
                        expected_fingerprint=current_fingerprint,
                    )
                except Exception as exc:
                    rollback_errors.append(exc)

            if rollback_outcome is not None and checkpoint.snapshot.morph_session_state is not None:
                try:
                    self._install_morph_session_state_locked(
                        session,
                        checkpoint.snapshot.morph_session_state,
                        reconcile_profiles=False,
                        advance_revision=False,
                    )
                except Exception as exc:
                    rollback_errors.append(exc)
        finally:
            if rollback_errors:
                # Never advertise the checkpoint's CAS tokens after a partial
                # rollback. Resident geometry/runtime/history may no longer
                # correspond to that checkpoint.
                session.revision = max(int(session.revision), checkpoint.revision) + 1
                session.selection_revision = max(
                    int(session.selection_revision),
                    checkpoint.selection_revision,
                ) + 1
                session.geometry_layer_revision = max(
                    int(session.geometry_layer_revision),
                    checkpoint.geometry_layer_revision,
                ) + 1
                session.morph_session_revision = max(
                    int(session.morph_session_revision),
                    checkpoint.morph_session_revision,
                ) + 1
                session.material_generation = max(
                    int(session.material_generation),
                    checkpoint.material_generation,
                ) + 1
                session.native_editor_selection_signature = ()
                session.native_history_undo_count = 0
                session.native_history_redo_count = 0
                session.native_history_retained_bytes = 0
                for stack in (session.undo_stack, session.redo_stack):
                    retained = []
                    for snapshot in stack:
                        if snapshot.native_editor_history:
                            invalid_native_markers.append(snapshot)
                        else:
                            retained.append(snapshot)
                    stack[:] = retained
            else:
                session.revision = checkpoint.revision
                session.selection_revision = checkpoint.selection_revision
                session.geometry_layer_revision = checkpoint.geometry_layer_revision
                session.morph_session_revision = checkpoint.morph_session_revision
                session.material_generation = checkpoint.material_generation
                session.committed_texture_resources = dict(
                    checkpoint.committed_texture_resources
                )
                session.native_editor_selection_signature = (
                    checkpoint.native_editor_selection_signature
                )
                session.native_history_undo_count = checkpoint.native_history_undo_count
                session.native_history_redo_count = checkpoint.native_history_redo_count
                session.native_history_retained_bytes = (
                    checkpoint.native_history_retained_bytes
                )
            if rollback_outcome is not None:
                _dispose_history_snapshot_without_state_failure(
                    rollback_outcome.snapshot
                )
            _dispose_history_snapshot_without_state_failure(checkpoint.snapshot)
            disposed: set[int] = set()
            for invalid_marker in invalid_native_markers:
                if id(invalid_marker) in disposed:
                    continue
                disposed.add(id(invalid_marker))
                _dispose_history_snapshot_without_state_failure(invalid_marker)

        if rollback_errors:
            raise RuntimeError(
                "The pre-restore Mesh Editor state could not be restored atomically."
            ) from rollback_errors[0]

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
        session_view = (
            self._session_view_locked(session, selection_is_authoritative=True)
            if action == "select" or topology_changed
            else None
        )
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
            session_view=session_view,
        )

def _capture_history_material_state(
    session: _MeshEditSession,
    snapshot: _MeshHistorySnapshot,
) -> _MeshHistorySnapshot:
    if snapshot.material_generation is None:
        snapshot.material_generation = int(session.material_generation)
    if snapshot.committed_texture_resources is None:
        snapshot.committed_texture_resources = tuple(
            session.committed_texture_resources[key]
            for key in sorted(session.committed_texture_resources)
        )
    return snapshot



def _capture_history_session_state(
    session: _MeshEditSession,
    snapshot: _MeshHistorySnapshot,
    template: _MeshHistorySnapshot,
) -> _MeshHistorySnapshot:
    """Capture the reciprocal service-owned state carried by one history marker."""

    if template.restore_archive_refit_context:
        snapshot.archive_refit_context = session.archive_refit_context
        snapshot.restore_archive_refit_context = True
    if template.restore_geometry_layer_state:
        snapshot.geometry_layers = tuple(session.geometry_layers)
        snapshot.active_geometry_layer_id = session.active_geometry_layer_id
        snapshot.geometry_layer_copy_counter = session.geometry_layer_copy_counter
        snapshot.restore_geometry_layer_state = True
    if template.output_policy is not None:
        snapshot.output_policy = session.output_policy
    if template.output_destination is not None:
        snapshot.output_destination = session.output_destination
    if template.output_destination_ready is not None:
        snapshot.output_destination_ready = session.output_destination_ready
    if template.morph_profile_root is not None:
        existed, files, _fingerprint = _mesh_morph_profile_directory_state(
            template.morph_profile_root
        )
        snapshot.morph_profile_root = template.morph_profile_root
        snapshot.morph_profile_root_existed = existed
        snapshot.morph_profile_files = files
        snapshot.morph_profile_expected_fingerprint = _mesh_morph_profile_state_fingerprint(
            bool(template.morph_profile_root_existed),
            tuple(template.morph_profile_files or ()),
        )
    return snapshot



def _restore_history_session_state(
    session: _MeshEditSession,
    snapshot: _MeshHistorySnapshot,
) -> None:
    """Restore only the service-owned fields explicitly included in a marker."""

    if snapshot.restore_archive_refit_context:
        session.archive_refit_context = snapshot.archive_refit_context
    if snapshot.restore_geometry_layer_state:
        target_layers = tuple(snapshot.geometry_layers or ())
        target_active = str(snapshot.active_geometry_layer_id or "base")
        target_copy_counter = int(snapshot.geometry_layer_copy_counter or 0)
        layers_changed = (
            session.geometry_layers != target_layers
            or session.active_geometry_layer_id != target_active
            or session.geometry_layer_copy_counter != target_copy_counter
        )
        session.geometry_layers = target_layers
        session.active_geometry_layer_id = target_active
        session.geometry_layer_copy_counter = target_copy_counter
        if layers_changed:
            session.geometry_layer_revision += 1
    if snapshot.output_policy is not None:
        session.output_policy = snapshot.output_policy
    if snapshot.output_destination is not None:
        session.output_destination = snapshot.output_destination
    if snapshot.output_destination_ready is not None:
        session.output_destination_ready = snapshot.output_destination_ready
    if snapshot.morph_profile_root is not None:
        _restore_mesh_morph_profile_directory_state(
            snapshot.morph_profile_root,
            existed=bool(snapshot.morph_profile_root_existed),
            files=tuple(snapshot.morph_profile_files or ()),
            expected_fingerprint=str(snapshot.morph_profile_expected_fingerprint or ""),
        )



def _restore_history_material_state(session: _MeshEditSession, snapshot: _MeshHistorySnapshot) -> None:
    resources = snapshot.committed_texture_resources
    if resources is None:
        return
    current = dict(session.committed_texture_resources)
    target = {(resource.resource_id, resource.channel): resource for resource in resources}
    assignment_keys = {
        key
        for key in set(current) | set(target)
        if bool(getattr(current.get(key), "source_dds_path", ""))
        or bool(getattr(target.get(key), "source_dds_path", ""))
    }
    restored = dict(current)
    for key in assignment_keys:
        if key in target:
            restored[key] = target[key]
        else:
            restored.pop(key, None)
    if restored != current:
        session.committed_texture_resources = restored
        session.material_generation = max(
            int(session.material_generation),
            int(snapshot.material_generation or 0),
        ) + 1



def _restore_geometry_layer_structure(
    target_layers: tuple[_MeshGeometryLayer, ...],
    current_layers: tuple[_MeshGeometryLayer, ...],
) -> tuple[_MeshGeometryLayer, ...]:
    """Restore geometry membership without rolling back non-history metadata."""

    current_by_id = {layer.layer_id: layer for layer in current_layers}
    target_by_id = {layer.layer_id: layer for layer in target_layers}
    restored_by_id = {
        layer.layer_id: (
            replace(
                layer,
                name=current_by_id[layer.layer_id].name,
                visible=current_by_id[layer.layer_id].visible,
            )
            if layer.layer_id in current_by_id
            else layer
        )
        for layer in target_layers
    }

    # Existing layers keep the user's current Move Up/Down order. A layer that
    # the geometry action removed is reinserted beside its closest historical
    # neighbour, so Undo Delete restores its former position without moving the
    # layers that remained editable in the meantime.
    ordered_ids = [layer.layer_id for layer in current_layers if layer.layer_id in target_by_id]
    for target_index, target in enumerate(target_layers):
        if target.layer_id in ordered_ids:
            continue
        previous = next(
            (
                target_layers[index].layer_id
                for index in range(target_index - 1, -1, -1)
                if target_layers[index].layer_id in ordered_ids
            ),
            None,
        )
        if previous is not None:
            ordered_ids.insert(ordered_ids.index(previous) + 1, target.layer_id)
            continue
        following = next(
            (
                target_layers[index].layer_id
                for index in range(target_index + 1, len(target_layers))
                if target_layers[index].layer_id in ordered_ids
            ),
            None,
        )
        ordered_ids.insert(ordered_ids.index(following) if following is not None else len(ordered_ids), target.layer_id)

    return tuple(restored_by_id[layer_id] for layer_id in ordered_ids)
