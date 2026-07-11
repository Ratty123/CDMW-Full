from __future__ import annotations

import math
from typing import Iterable, Mapping

from cdmw.domain.mesh import MESH_EDIT_MODES, MeshEditCommand, MeshEditSelection
from cdmw.modding.mesh_edit_ops import MESH_TOPOLOGY_ACTIONS
from cdmw.modding.mesh_native_core import native_mesh_core_fallback_events
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.services.mesh_service_payloads import _native_editor_transform_vec3_payload
from cdmw.services.mesh_service_reports import _coerce_index
from cdmw.services.mesh_service_state import _MeshEditSession

_TANGENT_INVALIDATING_ACTIONS = frozenset(MESH_TOPOLOGY_ACTIONS) | frozenset(
    {
        "transform",
        "brush",
        "recalculate_normals",
        "flip_normals",
        "sharpen_normals",
        "soften_normals",
        "weighted_normals",
        "copy_normals",
        "uv_transform",
    }
)


def _brush_selection_for_command(mesh: ParsedMesh, command: MeshEditCommand) -> MeshEditSelection | None:
    params = command.params or {}
    center = params.get("center")
    if not isinstance(center, (tuple, list)) or len(center) < 3:
        return None
    try:
        point = tuple(float(center[index]) for index in range(3))
        radius = float(params.get("radius", 0.0))
    except (TypeError, ValueError, OverflowError):
        return None
    if radius <= 0.0 or not all(math.isfinite(value) for value in (*point, radius)):
        return None
    radius_squared = radius * radius
    selected: dict[int, tuple[int, ...]] = {}
    for submesh_index, submesh in enumerate(mesh.submeshes or ()):
        indices = tuple(
            vertex_index
            for vertex_index, vertex in enumerate(submesh.vertices or ())
            if len(vertex) >= 3
            and sum((float(vertex[axis]) - point[axis]) ** 2 for axis in range(3)) <= radius_squared
        )
        if indices:
            selected[submesh_index] = indices
    return MeshEditSelection.from_maps(vertices_by_submesh=selected) if selected else None

def _apply_native_editor_dirty_counts(session: _MeshEditSession) -> None:
    counts = session.native_editor_mesh_dirty_counts
    if not counts:
        return
    session.working_mesh.total_vertices = sum(vertex_count for vertex_count, _ in counts)
    session.working_mesh.total_faces = sum(face_count for _, face_count in counts)




def _mesh_count_hint(mesh: ParsedMesh, attr: str) -> int:
    count = _diagnostic_count(getattr(mesh, attr, 0))
    return count if count is not None else 0


def _native_blocked_fallback_diagnostics(event_start: int) -> tuple[str, ...]:
    events = native_mesh_core_fallback_events()
    recent = events[event_start:] if 0 <= event_start <= len(events) else events
    messages: list[str] = []
    for event in recent:
        operation = str(event.get("operation") or "").strip()
        if not operation.endswith(".blocked"):
            continue
        label = operation[: -len(".blocked")] or "mesh edit"
        reason = str(event.get("reason") or "").strip()
        vertex_count = _diagnostic_count(event.get("vertex_count"))
        face_count = _diagnostic_count(event.get("face_count"))
        size = f" ({vertex_count:,} vertices, {face_count:,} faces)" if vertex_count is not None and face_count is not None else ""
        suffix = f" {reason}" if reason else ""
        messages.append(f"Edit was not applied: native mesh core failed and Python fallback was blocked for {label}{size}.{suffix}")
    return tuple(messages)


def _diagnostic_count(value: object) -> int | None:
    try:
        count = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return count if count >= 0 else None


def _truthy(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


def _mesh_structure_signature(mesh: ParsedMesh) -> tuple[tuple[int, int], ...]:
    return tuple((len(submesh.vertices or ()), len(submesh.faces or ())) for submesh in mesh.submeshes or ())


def _command_may_change_topology(action: str, command: MeshEditCommand, selection: MeshEditSelection) -> bool:
    if action in MESH_TOPOLOGY_ACTIONS:
        return True
    if action == "generate_tangents":
        return True
    if action in {"material_assign", "material_copy"}:
        return bool(selection.face_map())
    if action == "uv_transform":
        return _truthy(command.params.get("auto_uv")) and _truthy(
            command.params.get("allow_topology_change", command.params.get("confirm_topology_change", False))
        )
    return False


def _invalidate_tangents_after_edit(
    mesh: ParsedMesh,
    action: str,
    affected: set[int] | tuple[int, ...],
    changed: Mapping[int, object] | None,
    *,
    topology_changed: bool,
) -> tuple[int, ...]:
    if action not in _TANGENT_INVALIDATING_ACTIONS:
        return ()
    indices = {int(index) for index in affected if 0 <= int(index) < len(mesh.submeshes)}
    indices.update(int(index) for index in (changed or {}) if 0 <= int(index) < len(mesh.submeshes))
    if topology_changed and not indices:
        indices.update(range(len(mesh.submeshes)))
    invalidated: list[int] = []
    for index in sorted(indices):
        submesh = mesh.submeshes[index]
        if getattr(submesh, "tangents", None):
            submesh.tangents = []
            if getattr(submesh, "tangent_signs", None):
                submesh.tangent_signs = []
            if hasattr(submesh, "tangent_face_corner_report"):
                delattr(submesh, "tangent_face_corner_report")
            invalidated.append(index)
    return tuple(invalidated)


def _required_mode(action: str) -> str:
    if action == "brush":
        return "sculpt"
    if action in MESH_TOPOLOGY_ACTIONS or action in {
        "recalculate_normals",
        "generate_tangents",
        "flip_normals",
        "sharpen_normals",
        "soften_normals",
        "weighted_normals",
        "copy_normals",
        "uv_transform",
        "material_assign",
        "material_copy",
    }:
        return "edit"
    return ""


def _mode(value: object) -> str:
    mode = str(value or "object").strip().lower()
    if mode not in MESH_EDIT_MODES:
        raise ValueError(f"Unsupported mesh edit mode: {value!r}")
    return mode


def _native_editor_mesh_storage_signature(mesh: ParsedMesh) -> tuple[object, ...]:
    signature: list[object] = [len(mesh.submeshes or ())]
    for submesh in mesh.submeshes or ():
        for attr_name in (
            "vertices",
            "faces",
            "normals",
            "uvs",
            "tangents",
            "bone_indices",
            "bone_weights",
            "source_vertex_map",
            "source_vertex_offsets",
        ):
            values = getattr(submesh, attr_name, ()) or ()
            signature.extend((len(values), id(values)))
        signature.extend(
            (
                str(getattr(submesh, "name", "") or ""),
                str(getattr(submesh, "material", "") or ""),
                str(getattr(submesh, "texture", "") or ""),
            )
        )
    return tuple(signature)


def _records_history(command: MeshEditCommand) -> bool:
    value = command.params.get("record_history", command.params.get("history", True))
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _record_session_edit_operations(
    session: _MeshEditSession,
    action: str,
    command: MeshEditCommand,
    affected: Iterable[int],
    changed: Mapping[int, object] | None,
    *,
    topology_changed: bool,
) -> None:
    operation_names = _operation_names_for_command(action, command)
    if not operation_names or topology_changed:
        return
    targets = _operation_target_indices(session, affected, changed)
    if not targets:
        return
    existing = [dict(operation) if isinstance(operation, Mapping) else operation for operation in session.edit_operations]
    for submesh_index in targets:
        if not 0 <= submesh_index < len(session.working_mesh.submeshes):
            continue
        submesh = session.working_mesh.submeshes[submesh_index]
        target_operations = list(operation_names)
        if any(name in {"replace_positions_same_count", "translate_vertices", "scale_vertices", "rotate_vertices"} for name in target_operations):
            if _submesh_channel_changed(session.base_mesh, session.working_mesh, submesh_index, "normals"):
                target_operations.append("replace_normals_same_count")
        for operation_name in dict.fromkeys(target_operations):
            existing.append(
                {
                    "operation": operation_name,
                    "lod_index": 0,
                    "submesh_index": submesh_index,
                    "vertex_count": len(submesh.vertices or ()),
                    "source": str(command.label or action or "Mesh Editor"),
                    "created_by": "Mesh Editor v2",
                    "metadata": {"service_action": action},
                }
            )
    session.edit_operations = tuple(existing)


def _operation_names_for_command(action: str, command: MeshEditCommand) -> tuple[str, ...]:
    if action == "transform":
        params = command.params or {}
        has_translate = _vector_has_value(params.get("translate", params.get("delta")))
        has_scale = _vector_has_non_identity_scale(params.get("scale"))
        has_rotate = _vector_has_value(params.get("rotate", params.get("rotate_degrees")))
        if has_translate and not has_scale and not has_rotate:
            return _with_recomputed_normals("translate_vertices", params)
        if has_scale and not has_translate and not has_rotate:
            return _with_recomputed_normals("scale_vertices", params)
        if has_rotate and not has_translate and not has_scale:
            return _with_recomputed_normals("rotate_vertices", params)
        return _with_recomputed_normals("replace_positions_same_count", params)
    if action == "brush":
        return _with_recomputed_normals("replace_positions_same_count", command.params or {})
    if action in {"recalculate_normals", "flip_normals", "sharpen_normals", "soften_normals", "weighted_normals", "copy_normals"}:
        return ("replace_normals_same_count",)
    if action == "generate_tangents":
        return ("replace_tangents_same_count",)
    if action == "uv_transform":
        return ("replace_uv0_same_count",)
    return ()


def _with_recomputed_normals(operation: str, params: Mapping[str, object]) -> tuple[str, ...]:
    if _truthy(params.get("recompute_normals", True)):
        return (operation, "replace_normals_same_count")
    return (operation,)


def _submesh_channel_changed(base_mesh: ParsedMesh, working_mesh: ParsedMesh, submesh_index: int, channel: str) -> bool:
    if not 0 <= submesh_index < len(base_mesh.submeshes or ()):
        return False
    if not 0 <= submesh_index < len(working_mesh.submeshes or ()):
        return False
    before = base_mesh.submeshes[submesh_index]
    after = working_mesh.submeshes[submesh_index]
    attr = {"normals": "normals", "uv0": "uvs", "tangents": "tangents"}.get(channel, channel)
    return tuple(getattr(before, attr, ()) or ()) != tuple(getattr(after, attr, ()) or ())


def _operation_target_indices(
    session: _MeshEditSession,
    affected: Iterable[int],
    changed: Mapping[int, object] | None,
) -> tuple[int, ...]:
    indices = {_coerce_index(value) for value in affected}
    indices.update(_coerce_index(value) for value in (changed or {}).keys())
    return tuple(sorted(index for index in indices if index is not None and 0 <= index < len(session.working_mesh.submeshes)))


def _vector_has_value(value: object) -> bool:
    vector = _native_editor_transform_vec3_payload(value, fallback=(0.0, 0.0, 0.0))
    if not isinstance(vector, (list, tuple)):
        return False
    try:
        return any(abs(float(component)) > 1e-8 for component in vector[:3])
    except (TypeError, ValueError, OverflowError):
        return False


def _vector_has_non_identity_scale(value: object) -> bool:
    vector = _native_editor_transform_vec3_payload(value, fallback=(1.0, 1.0, 1.0))
    if not isinstance(vector, (list, tuple)):
        return False
    try:
        return any(abs(float(component) - 1.0) > 1e-8 for component in vector[:3])
    except (TypeError, ValueError, OverflowError):
        return False


def _append_unique_diagnostics(existing: tuple[str, ...], extra: tuple[str, ...]) -> tuple[str, ...]:
    if not extra:
        return existing
    result: list[str] = []
    seen: set[str] = set()
    for message in (*existing, *extra):
        text = str(message or "").strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return tuple(result)
