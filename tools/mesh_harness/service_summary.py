from __future__ import annotations

from collections.abc import Mapping
from cdmw.domain.mesh import MeshEditSelection
from cdmw.modding.mesh_parser import ParsedMesh

def _mesh_textures(mesh: ParsedMesh) -> tuple[str, ...]:
    return tuple(str(getattr(submesh, "texture", "") or "") for submesh in tuple(mesh.submeshes or ()))

def _mesh_face_count(mesh: ParsedMesh) -> int:
    return sum(len(getattr(submesh, "faces", ()) or ()) for submesh in tuple(mesh.submeshes or ()))

def _mesh_vertex_count(mesh: ParsedMesh) -> int:
    return sum(len(getattr(submesh, "vertices", ()) or ()) for submesh in tuple(mesh.submeshes or ()))

def _mesh_geometry_signature(mesh: ParsedMesh) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            tuple(tuple(round(float(component), 8) for component in vertex) for vertex in (submesh.vertices or ())),
            tuple(tuple(int(index) for index in face) for face in (submesh.faces or ())),
            str(getattr(submesh, "material", "") or ""),
            str(getattr(submesh, "texture", "") or ""),
        )
        for submesh in tuple(mesh.submeshes or ())
    )

def _command_summary(result: object) -> dict[str, object]:
    summary = {
        "action": getattr(result, "action", ""),
        "status": getattr(result, "status", ""),
        "revision": getattr(result, "revision", 0),
        "affected_submesh_indices": list(getattr(result, "affected_submesh_indices", ())),
        "topology_changed": bool(getattr(result, "topology_changed", False)),
        "submesh_count_delta": int(getattr(result, "submesh_count_delta", 0) or 0),
    }
    metrics = getattr(result, "metrics", None)
    if isinstance(metrics, Mapping) and metrics:
        summary["metrics"] = {str(key): float(value) for key, value in metrics.items()}
    return summary

def _palette_command_summary(action_key: str, command: str, result: object) -> dict[str, object]:
    edit_result = getattr(result, "edit_result")
    native_update = getattr(result, "native_update")
    summary = _command_summary(edit_result)
    summary["key"] = action_key
    summary["command"] = command
    summary["vertex_update_group_count"] = len(getattr(native_update, "vertex_groups", ()) or ())
    summary["triangle_group_count"] = len(getattr(native_update, "triangle_groups", ()) or ())
    summary["selection_group_count"] = len(getattr(native_update, "selection_groups", ()) or ())
    summary["selection_refresh"] = bool(getattr(native_update, "refresh_selection", False))
    summary["material_override_group_count"] = len(getattr(native_update, "material_override_groups", ()) or ())
    return summary

def _selection_snapshot(selection: MeshEditSelection) -> dict[str, object]:
    return {
        "vertices_by_submesh": {str(submesh): list(indices) for submesh, indices in selection.vertices_by_submesh},
        "edges_by_submesh": {str(submesh): [list(edge) for edge in edges] for submesh, edges in selection.edges_by_submesh},
        "faces_by_submesh": {str(submesh): list(indices) for submesh, indices in selection.faces_by_submesh},
        "source_indices": list(selection.source_indices),
    }

def _mesh_vertices_changed(before: ParsedMesh, after: ParsedMesh) -> bool:
    for before_submesh, after_submesh in zip(before.submeshes, after.submeshes):
        for before_vertex, after_vertex in zip(before_submesh.vertices, after_submesh.vertices):
            before_vec = _vec3(before_vertex)
            after_vec = _vec3(after_vertex)
            if before_vec and after_vec and any(abs(after_vec[axis] - before_vec[axis]) > 1e-5 for axis in range(3)):
                return True
    return False

def _tuple_row(value: object) -> tuple[object, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        return (value,)
    try:
        return tuple(value)  # type: ignore[arg-type]
    except TypeError:
        return (value,)

def _vec3(value: object) -> tuple[float, float, float]:
    try:
        vec = tuple(float(component) for component in value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return ()
    return vec[:3] if len(vec) >= 3 else ()
