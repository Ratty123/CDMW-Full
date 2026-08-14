"""When a Mesh Editor operation may fall back to the Python path.

Split out of :mod:`mesh_service_native_session` to keep that module inside
the owned-file line cap. The rule is the same for every operation here: the
fallback is allowed only when the native core is switched off or genuinely
unavailable, and otherwise it is refused and recorded with the mesh size that
would have taken the slow path. Refusing quietly would let the native core
regress into a Python path nobody notices.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable, Mapping

from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.services.mesh_service_kernel import _mesh_count_hint
from cdmw.services.mesh_service_selection import _selected_skin_weight_vertex_count
from cdmw.services.mesh_service_state import _MeshVertexPositionDelta


def _service_call(name: str, *args: object, **kwargs: object) -> object:
    """Resolve facade re-exports so existing integrations keep one patch surface."""
    return getattr(sys.modules["cdmw.services.mesh_service"], name)(*args, **kwargs)


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
