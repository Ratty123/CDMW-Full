"""Native sparse mesh-edit history handle ownership helpers."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Mapping, MutableSequence, Sequence


_SPARSE_VERTEX_SNAPSHOT_REFCOUNTS: dict[str, int] = {}


def sparse_vertex_snapshot_ids(snapshot: object) -> set[str]:
    if not isinstance(snapshot, Mapping) or snapshot.get("kind") != "native_sparse_vertex_delta":
        return set()
    before_by_submesh = snapshot.get("before_positions_by_submesh")
    if not isinstance(before_by_submesh, Mapping):
        return set()
    snapshot_ids: set[str] = set()
    for raw_positions in before_by_submesh.values():
        if not isinstance(raw_positions, Mapping):
            continue
        raw_groups = raw_positions.get("groups")
        groups: Sequence[object] = raw_groups if isinstance(raw_groups, (tuple, list)) else (raw_positions,)
        for group in groups:
            if not isinstance(group, Mapping):
                continue
            snapshot_id = str(
                group.get("native_sparse_snapshot_id")
                or group.get("sparse_snapshot_id")
                or ""
            ).strip()
            if snapshot_id:
                snapshot_ids.add(snapshot_id)
    return snapshot_ids


def retain_sparse_vertex_snapshot(snapshot: object) -> None:
    for snapshot_id in sparse_vertex_snapshot_ids(snapshot):
        _SPARSE_VERTEX_SNAPSHOT_REFCOUNTS[snapshot_id] = (
            _SPARSE_VERTEX_SNAPSHOT_REFCOUNTS.get(snapshot_id, 0) + 1
        )


def release_sparse_vertex_snapshot(snapshot: object) -> None:
    snapshot_ids = sparse_vertex_snapshot_ids(snapshot)
    if not snapshot_ids:
        return
    try:
        from cdmw.modding.mesh_native_core import dispose_native_mesh_sparse_vertex_snapshot
    except Exception:
        return
    for snapshot_id in snapshot_ids:
        refcount = int(_SPARSE_VERTEX_SNAPSHOT_REFCOUNTS.get(snapshot_id, 0) or 0)
        if refcount > 1:
            _SPARSE_VERTEX_SNAPSHOT_REFCOUNTS[snapshot_id] = refcount - 1
            continue
        _SPARSE_VERTEX_SNAPSHOT_REFCOUNTS.pop(snapshot_id, None)
        dispose_native_mesh_sparse_vertex_snapshot(snapshot_id)


def release_native_submesh_snapshot(snapshot: object) -> None:
    if not isinstance(snapshot, Mapping) or snapshot.get("kind") != "native_submesh_snapshot":
        return
    try:
        from cdmw.modding.mesh_native_core import dispose_native_mesh_submesh_snapshot
    except Exception:
        return
    dispose_native_mesh_submesh_snapshot(snapshot)


def allow_python_sparse_history_restore_fallback(
    mesh: object,
    submesh_indices: Iterable[int],
    operation: str,
) -> bool:
    normalized_set: set[int] = set()
    for raw_index in tuple(submesh_indices or ()):
        try:
            index = int(raw_index)
        except (TypeError, ValueError, OverflowError):
            continue
        if index >= 0:
            normalized_set.add(index)
    normalized = tuple(sorted(normalized_set))
    if not normalized:
        return True
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return True
    try:
        from cdmw.modding.mesh_native_core import native_mesh_core_available, record_native_mesh_core_fallback
    except Exception:
        return True
    if not native_mesh_core_available():
        return True
    vertex_count, face_count = _mesh_counts(mesh)
    record_native_mesh_core_fallback(
        f"{operation}.blocked",
        "Python sparse history restore fallback blocked while native mesh core is available",
        vertex_count=vertex_count,
        face_count=face_count,
        submesh_indices=normalized,
    )
    return False


def allow_python_full_mesh_clone_fallback(mesh: object, operation: str, reason: str) -> bool:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return True
    try:
        from cdmw.modding.mesh_native_core import native_mesh_core_available, record_native_mesh_core_fallback
    except Exception:
        return True
    if not native_mesh_core_available():
        return True
    vertex_count, face_count = _mesh_counts(mesh)
    record_native_mesh_core_fallback(
        f"{operation}.blocked",
        str(reason or "Python full-mesh clone fallback blocked while native mesh core is available"),
        vertex_count=vertex_count,
        face_count=face_count,
    )
    return False


def clone_mesh_for_static_replacement_native_first(
    mesh: object,
    operation: str,
    reason: str,
    *,
    fallback_allowed: Callable[[object], bool] | None = None,
) -> object | None:
    native_snapshot = None
    try:
        from cdmw.modding.mesh_native_core import (
            dispose_native_mesh_submesh_snapshot,
            invalidate_native_mesh_session_submeshes,
            restore_native_mesh_submesh_snapshot,
            snapshot_native_mesh_submeshes,
        )
        from cdmw.modding.mesh_parser import ParsedMesh

        native_snapshot = snapshot_native_mesh_submeshes(mesh)  # type: ignore[arg-type]
        if native_snapshot is not None:
            restored = ParsedMesh()
            if restore_native_mesh_submesh_snapshot(restored, native_snapshot):
                invalidate_native_mesh_session_submeshes(
                    restored,
                    range(len(getattr(restored, "submeshes", ()) or ())),
                )
                return restored
    except Exception:
        pass
    finally:
        if native_snapshot is not None:
            try:
                dispose_native_mesh_submesh_snapshot(native_snapshot)  # type: ignore[name-defined]
            except Exception:
                pass
    if fallback_allowed is not None:
        allowed = fallback_allowed(mesh)
    else:
        allowed = allow_python_full_mesh_clone_fallback(mesh, operation, reason)
    if not allowed:
        return None
    from cdmw.modding.mesh_deformer import clone_mesh_for_editing

    return clone_mesh_for_editing(mesh)  # type: ignore[arg-type]


def allow_python_mesh_history_snapshot_fallback(mesh: object, operation: str) -> bool:
    return allow_python_full_mesh_clone_fallback(
        mesh,
        operation,
        "Python mesh history snapshot fallback blocked while native mesh core is available",
    )


def _mesh_counts(mesh: object) -> tuple[int, int]:
    vertices = _nonnegative_int(getattr(mesh, "total_vertices", 0))
    faces = _nonnegative_int(getattr(mesh, "total_faces", 0))
    if vertices > 0 and faces > 0:
        return vertices, faces
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    if vertices <= 0:
        vertices = sum(len(getattr(submesh, "vertices", ()) or ()) for submesh in submeshes)
    if faces <= 0:
        faces = sum(len(getattr(submesh, "faces", ()) or ()) for submesh in submeshes)
    return vertices, faces


def _nonnegative_int(value: object) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return 0
    return parsed if parsed >= 0 else 0


def retain_mesh_history_snapshot(snapshot: object) -> None:
    retain_sparse_vertex_snapshot(snapshot)


def release_mesh_history_snapshot(snapshot: object) -> None:
    release_sparse_vertex_snapshot(snapshot)
    release_native_submesh_snapshot(snapshot)


def retain_sparse_vertex_snapshot_stack(stack: Sequence[object]) -> None:
    for snapshot in tuple(stack or ()):
        retain_sparse_vertex_snapshot(snapshot)


def release_sparse_vertex_snapshot_stack(stack: Sequence[object]) -> None:
    for snapshot in tuple(stack or ()):
        release_sparse_vertex_snapshot(snapshot)


def clear_sparse_vertex_snapshot_stack(stack: MutableSequence[object]) -> None:
    release_sparse_vertex_snapshot_stack(stack)
    stack.clear()


def clear_mesh_history_snapshot_stack(stack: MutableSequence[object]) -> None:
    for snapshot in tuple(stack or ()):
        release_mesh_history_snapshot(snapshot)
    stack.clear()


def replace_sparse_vertex_snapshot_stack(
    stack: MutableSequence[object],
    snapshots: Sequence[object],
) -> None:
    old_unmatched = list(stack or ())
    for snapshot in tuple(snapshots or ()):
        for index, old_snapshot in enumerate(old_unmatched):
            if old_snapshot is snapshot:
                del old_unmatched[index]
                break
        else:
            retain_sparse_vertex_snapshot(snapshot)
    for old_snapshot in old_unmatched:
        release_sparse_vertex_snapshot(old_snapshot)
    stack[:] = list(snapshots or ())


def replace_mesh_history_snapshot_stack(
    stack: MutableSequence[object],
    snapshots: Sequence[object],
) -> None:
    old_unmatched = list(stack or ())
    for snapshot in tuple(snapshots or ()):
        for index, old_snapshot in enumerate(old_unmatched):
            if old_snapshot is snapshot:
                del old_unmatched[index]
                break
        else:
            retain_mesh_history_snapshot(snapshot)
    for old_snapshot in old_unmatched:
        release_mesh_history_snapshot(old_snapshot)
    stack[:] = list(snapshots or ())


__all__ = [
    "allow_python_full_mesh_clone_fallback",
    "allow_python_mesh_history_snapshot_fallback",
    "allow_python_sparse_history_restore_fallback",
    "clone_mesh_for_static_replacement_native_first",
    "clear_mesh_history_snapshot_stack",
    "clear_sparse_vertex_snapshot_stack",
    "release_mesh_history_snapshot",
    "release_native_submesh_snapshot",
    "release_sparse_vertex_snapshot",
    "release_sparse_vertex_snapshot_stack",
    "retain_mesh_history_snapshot",
    "replace_mesh_history_snapshot_stack",
    "replace_sparse_vertex_snapshot_stack",
    "retain_sparse_vertex_snapshot",
    "retain_sparse_vertex_snapshot_stack",
    "sparse_vertex_snapshot_ids",
]
