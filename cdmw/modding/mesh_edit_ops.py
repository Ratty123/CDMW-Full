"""Mesh edit geometry operations for service/UI command dispatch."""

from __future__ import annotations

import math
import os
from copy import copy
from collections.abc import Callable, Mapping, Sequence

from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
from cdmw.domain.textures.material_authority import complete_swap_material_authority_contract, sanitize_texture_component

from .mesh_deformer import (
    apply_brush_deformation,
    apply_vertex_delta,
    compact_orphan_vertices,
    delete_faces_by_indices,
    recompute_submesh_normals,
    split_faces_to_submesh,
    subdivide_faces_touching_vertices,
)
from .mesh_native_core import (
    apply_native_mesh_auto_uv,
    apply_native_mesh_bridge,
    apply_native_mesh_brush,
    apply_native_mesh_brush_binary_selection,
    apply_native_mesh_brush_selection,
    apply_native_mesh_compact_orphans,
    apply_native_mesh_copy_normals,
    apply_native_mesh_delete,
    apply_native_mesh_dissolve,
    apply_native_mesh_duplicate,
    apply_native_mesh_edge_split,
    apply_native_mesh_extrude,
    apply_native_mesh_fill,
    apply_native_mesh_fill_holes,
    apply_native_mesh_fix_winding,
    apply_native_mesh_flip_normals,
    apply_native_mesh_generate_tangents,
    apply_native_mesh_inset,
    apply_native_mesh_loop_cut,
    apply_native_mesh_merge,
    apply_native_mesh_mirror,
    apply_native_mesh_recalculate_normals,
    apply_native_mesh_remove_doubles,
    apply_native_mesh_separate,
    apply_native_mesh_sharpen_normals,
    apply_native_mesh_split,
    apply_native_mesh_subdivide,
    apply_native_mesh_transform,
    apply_native_mesh_transform_binary_selection,
    apply_native_mesh_transform_selection,
    apply_native_mesh_triangulate_display,
    apply_native_mesh_uv_transform,
    apply_native_mesh_weld,
    apply_native_mesh_weighted_normals,
    native_mesh_core_available,
    record_native_mesh_core_fallback,
)
from .mesh_parser import ParsedMesh, SubMesh

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]
UvKey = tuple[float, float]
UvEdgeKey = tuple[tuple[int, int], tuple[UvKey, UvKey]]
MeshEditChangedVertices = dict[int, Sequence[int] | set[int]]
MeshEditAffected = set[int]


class NativeLiveHistoryUnavailable(RuntimeError):
    """Raised when native live undo deltas are required but unavailable."""


_NATIVE_MATERIAL_OVERRIDE_KEYS = {
    "texture_brightness",
    "roughness", "roughness_hint_present",
    "metalness", "metalness_hint_present",
    "specular", "specular_hint_present",
    "height_scale",
    "emissive_intensity",
    "emissive_color", "emissive_color_authoritative", "emissive_scalar_mask",
    "contrast",
    "saturation",
    "gamma",
    "tint_color",
    "native_material_hints",
    "material_shader_family",
}
_MATERIAL_ASSIGN_PARAM_KEYS = {
    "material",
    "texture",
    "material_authority_profile",
    "material_profile",
    "complete_swap_material_profile",
    "authority_contract",
    "material_authority_contract",
    "source_material_name",
    "target_material_name",
    "target_material_slot_index",
    "material_slot_index",
    "slot_kind",
    "source_texture_set_key",
    "route_status",
    "route_reason",
    "preview_native_material_overrides",
    "native_material_overrides",
}
def _record_native_edit_fallback(
    mesh: ParsedMesh,
    operation: str,
    reason: str,
    *,
    submesh_indices: object = None,
) -> None:
    details: dict[str, object] = {
        "vertex_count": _mesh_count(mesh, "total_vertices"),
        "face_count": _mesh_count(mesh, "total_faces"),
    }
    indices = _fallback_submesh_indices(submesh_indices)
    if indices:
        details["submesh_indices"] = indices
    record_native_mesh_core_fallback(operation, reason, **details)


def _allow_python_mesh_edit_fallback(mesh: ParsedMesh, operation: str, *, submesh_indices: object = None) -> bool:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE", "").strip():
        return True
    if not native_mesh_core_available():
        return True
    _record_native_edit_fallback(
        mesh,
        f"{operation}.blocked",
        "Python mesh edit fallback blocked while native mesh core is available",
        submesh_indices=submesh_indices,
    )
    return False


def _recompute_normals_after_native_edit(mesh: ParsedMesh, submesh_indices: object, reason: str) -> None:
    target_indices = {
        index for index in _fallback_submesh_indices(submesh_indices)
        if 0 <= index < len(mesh.submeshes)
    }
    if not target_indices:
        return
    native_normals = apply_native_mesh_recalculate_normals(mesh, target_indices)
    if native_normals is not None:
        return
    if not _allow_python_mesh_edit_fallback(mesh, "normals.recalculate", submesh_indices=target_indices):
        return
    _record_native_edit_fallback(mesh, "normals.recalculate", reason, submesh_indices=target_indices)
    for submesh_index in target_indices:
        recompute_submesh_normals(mesh.submeshes[submesh_index])


def _mesh_count(mesh: ParsedMesh, attr: str) -> int:
    try:
        value = int(getattr(mesh, attr, 0) or 0)
    except (TypeError, ValueError, OverflowError):
        return 0
    return value if value >= 0 else 0


def _fallback_submesh_indices(value: object) -> tuple[int, ...]:
    if value is None:
        return ()
    try:
        raw_values = value.keys() if isinstance(value, Mapping) else value
        return tuple(sorted({int(index) for index in raw_values}))  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return ()

MESH_TOPOLOGY_ACTIONS = {
    "delete",
    "dissolve",
    "subdivide",
    "refine_smooth",
    "split",
    "separate",
    "duplicate",
    "mirror",
    "extrude",
    "inset",
    "loop_cut",
    "edge_split",
    "merge",
    "weld",
    "bridge",
    "fill",
    "remove_doubles",
    "delete_loose_vertices",
    "compact_orphans",
    "fix_winding",
    "fill_holes",
    "triangulate_display",
    "quadrangulate_display",
}
MESH_GEOMETRY_ACTIONS = MESH_TOPOLOGY_ACTIONS | {
    "transform",
    "brush",
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
}


def apply_mesh_edit_geometry_action(
    mesh: ParsedMesh,
    command: MeshEditCommand,
    selection: MeshEditSelection,
) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    action = command.action.strip().lower()
    params = dict(command.params or {})
    if action == "transform":
        return _transform(mesh, selection, params)
    if action == "brush":
        return _brush(mesh, selection, params)
    if action == "delete":
        return _delete(mesh, selection, params, remove_orphans=True)
    if action == "dissolve":
        return _dissolve(mesh, selection)
    if action == "loop_cut" and selection.edge_map():
        return _loop_cut(mesh, selection, params)
    if action in {"subdivide", "loop_cut"}:
        return _subdivide(mesh, selection, params)
    if action == "refine_smooth":
        return _refine_smooth(mesh, selection, params)
    if action == "split":
        return _split(mesh, selection, params)
    if action == "separate":
        return _separate(mesh, selection, params)
    if action == "duplicate":
        return _duplicate(mesh, selection, params)
    if action == "mirror":
        return _mirror(mesh, selection, params)
    if action == "extrude":
        return _extrude(mesh, selection, params)
    if action == "inset":
        return _inset(mesh, selection, params)
    if action == "edge_split":
        return _edge_split(mesh, selection)
    if action == "merge":
        return _merge(mesh, selection)
    if action == "weld":
        return _weld(mesh, selection, params)
    if action == "bridge":
        return _bridge(mesh, selection)
    if action == "fill":
        return _fill(mesh, selection)
    if action == "remove_doubles":
        return _remove_doubles(mesh, selection, params)
    if action == "delete_loose_vertices":
        return _delete_loose_vertices(mesh, selection)
    if action == "compact_orphans":
        return _delete_loose_vertices(mesh, selection)
    if action == "fix_winding":
        return _fix_winding(mesh, selection)
    if action == "fill_holes":
        return _fill_holes(mesh, selection)
    if action == "triangulate_display":
        return _triangulate_display(mesh, selection)
    if action == "quadrangulate_display":
        return set(), {}
    if action == "recalculate_normals":
        return _recalculate_normals(mesh, selection)
    if action == "generate_tangents":
        return _generate_tangents(mesh, selection)
    if action == "flip_normals":
        return _flip_normals(mesh, selection)
    if action == "sharpen_normals":
        return _sharpen_normals(mesh, selection)
    if action == "soften_normals":
        return _recalculate_normals(mesh, selection)
    if action == "weighted_normals":
        return _weighted_normals(mesh, selection)
    if action == "copy_normals":
        return _copy_normals(mesh, selection, params)
    if action == "uv_transform":
        return _uv_transform(mesh, selection, params)
    if action == "material_assign":
        return _material_assign(mesh, selection, params)
    if action == "material_copy":
        return _material_copy(mesh, selection, params)
    return set(), {}


def _stop_event(params: Mapping[str, object]) -> object | None:
    candidate = params.get("stop_event")
    return candidate if callable(getattr(candidate, "is_set", None)) else None


def _native_kwargs(params: Mapping[str, object]) -> dict[str, object]:
    stop_event = _stop_event(params)
    return {"stop_event": stop_event} if stop_event is not None else {}


def refresh_mesh_totals(mesh: ParsedMesh) -> None:
    mesh.total_vertices = sum(len(submesh.vertices or []) for submesh in mesh.submeshes or [])
    mesh.total_faces = sum(len(submesh.faces or []) for submesh in mesh.submeshes or [])
    mesh.has_uvs = any(bool(submesh.uvs) for submesh in mesh.submeshes or [])
    mesh.has_bones = any(bool(submesh.bone_indices) or bool(submesh.bone_weights) for submesh in mesh.submeshes or [])
    for submesh in mesh.submeshes or []:
        submesh.vertex_count = len(submesh.vertices or [])
        submesh.face_count = len(submesh.faces or [])


def _vec2(value: object, fallback: Vec2 = (0.0, 0.0)) -> Vec2:
    if not isinstance(value, (tuple, list)) or len(value) < 2:
        return fallback
    try:
        parsed = (float(value[0]), float(value[1]))
    except (TypeError, ValueError, OverflowError):
        return fallback
    return parsed if all(math.isfinite(component) for component in parsed) else fallback


def _vec3(value: object, fallback: Vec3 = (0.0, 0.0, 0.0)) -> Vec3:
    if not isinstance(value, (tuple, list)) or len(value) < 3:
        return fallback
    try:
        parsed = (float(value[0]), float(value[1]), float(value[2]))
    except (TypeError, ValueError, OverflowError):
        return fallback
    return parsed if all(math.isfinite(component) for component in parsed) else fallback


def _add(left: Vec3, right: Vec3) -> Vec3:
    return (left[0] + right[0], left[1] + right[1], left[2] + right[2])


def _sub(left: Vec3, right: Vec3) -> Vec3:
    return (left[0] - right[0], left[1] - right[1], left[2] - right[2])


def _scale(value: Vec3, factor: float) -> Vec3:
    return (value[0] * factor, value[1] * factor, value[2] * factor)


def _dot(left: Vec3, right: Vec3) -> float:
    return left[0] * right[0] + left[1] * right[1] + left[2] * right[2]


def _normalized_vec3(value: Vec3) -> Vec3:
    length = math.sqrt(_dot(value, value))
    if length <= 1e-12:
        return (0.0, 0.0, 0.0)
    return (value[0] / length, value[1] / length, value[2] / length)


def _submesh_indices(mesh: ParsedMesh, selection: MeshEditSelection) -> list[int]:
    candidates: set[int] = set(selection.source_indices)
    candidates.update(selection.vertex_map())
    candidates.update(selection.edge_map())
    candidates.update(selection.face_map())
    if not candidates:
        candidates.update(range(len(mesh.submeshes)))
    return sorted(index for index in candidates if 0 <= index < len(mesh.submeshes))


def _selected_vertices(
    mesh: ParsedMesh,
    selection: MeshEditSelection,
    *,
    fallback_all: bool,
) -> dict[int, set[int]]:
    result = selection.vertex_map()
    for submesh_index, edges in selection.edge_map().items():
        if not 0 <= submesh_index < len(mesh.submeshes):
            continue
        valid_edges = _valid_selected_edges_for_submesh(mesh.submeshes[submesh_index], edges)
        if not valid_edges:
            continue
        vertices = result.setdefault(submesh_index, set())
        for a, b in valid_edges:
            vertices.update((a, b))
    for submesh_index, faces in selection.face_map().items():
        if 0 <= submesh_index < len(mesh.submeshes):
            vertices = result.setdefault(submesh_index, set())
            submesh = mesh.submeshes[submesh_index]
            for face_index in faces:
                if 0 <= face_index < len(submesh.faces):
                    vertices.update(_valid_face_vertices(submesh.faces[face_index], len(submesh.vertices)))
    for submesh_index in selection.source_indices:
        if 0 <= submesh_index < len(mesh.submeshes):
            result.setdefault(submesh_index, set()).update(range(len(mesh.submeshes[submesh_index].vertices)))
    if fallback_all and not result and selection.is_empty():
        for submesh_index, submesh in enumerate(mesh.submeshes):
            result[submesh_index] = set(range(len(submesh.vertices)))
    valid: dict[int, set[int]] = {}
    for submesh_index, indices in result.items():
        if not 0 <= submesh_index < len(mesh.submeshes):
            continue
        kept = {index for index in indices if 0 <= index < len(mesh.submeshes[submesh_index].vertices)}
        if kept:
            valid[submesh_index] = kept
    return valid


def _selected_vertices_with_source_ranges(
    mesh: ParsedMesh,
    selection: MeshEditSelection,
) -> dict[int, Sequence[int] | set[int]]:
    selected: dict[int, Sequence[int] | set[int]] = {}
    if selection.vertices_by_submesh or selection.edges_by_submesh or selection.faces_by_submesh:
        selected.update(
            _selected_vertices(
                mesh,
                MeshEditSelection.from_maps(
                    vertices_by_submesh=selection.vertex_map(),
                    edges_by_submesh=selection.edge_map(),
                    faces_by_submesh=selection.face_map(),
                ),
                fallback_all=False,
            )
        )
    for submesh_index in selection.source_indices:
        if not 0 <= submesh_index < len(mesh.submeshes):
            continue
        vertex_count = len(mesh.submeshes[submesh_index].vertices)
        if vertex_count > 0:
            selected[submesh_index] = range(vertex_count)
    return selected


def _selected_faces(mesh: ParsedMesh, selection: MeshEditSelection, *, fallback_all: bool = False) -> dict[int, set[int]]:
    result = selection.face_map()
    if not result and selection.edges_by_submesh:
        for submesh_index, edges in selection.edge_map().items():
            if not (0 <= submesh_index < len(mesh.submeshes)):
                continue
            submesh = mesh.submeshes[submesh_index]
            selected_edges = {_edge_key(a, b) for a, b in edges}
            touched: set[int] = set()
            for face_index, face in enumerate(submesh.faces or []):
                vertices = _valid_face_vertices(face, len(submesh.vertices))
                if len(vertices) != 3:
                    continue
                a, b, c = vertices
                face_edges = {_edge_key(a, b), _edge_key(b, c), _edge_key(c, a)}
                if face_edges & selected_edges:
                    touched.add(face_index)
            if touched:
                result[submesh_index] = touched
    if not result and selection.vertices_by_submesh:
        vertices = _selected_vertices(mesh, selection, fallback_all=False)
        for submesh_index, selected in vertices.items():
            submesh = mesh.submeshes[submesh_index]
            touched = {
                face_index
                for face_index, face in enumerate(submesh.faces or [])
                if any(index in selected for index in _valid_face_vertices(face, len(submesh.vertices)))
            }
            if touched:
                result[submesh_index] = touched
    for submesh_index in selection.source_indices:
        if 0 <= submesh_index < len(mesh.submeshes):
            result.setdefault(submesh_index, set()).update(range(len(mesh.submeshes[submesh_index].faces)))
    if fallback_all and not result and selection.is_empty():
        for submesh_index, submesh in enumerate(mesh.submeshes):
            result[submesh_index] = set(range(len(submesh.faces)))
    valid: dict[int, set[int]] = {}
    for submesh_index, indices in result.items():
        if not 0 <= submesh_index < len(mesh.submeshes):
            continue
        kept = _valid_face_indices_for_submesh(mesh.submeshes[submesh_index], indices)
        if kept:
            valid[submesh_index] = kept
    return valid


def _valid_face_indices_for_submesh(submesh: SubMesh, indices: set[int]) -> set[int]:
    return {
        index
        for index in indices
        if 0 <= index < len(submesh.faces)
        and len(_valid_face_vertices(submesh.faces[index], len(submesh.vertices))) == 3
    }


def _valid_face_items(submesh: SubMesh) -> tuple[tuple[int, tuple[int, int, int]], ...]:
    items: list[tuple[int, tuple[int, int, int]]] = []
    for face_index, face in enumerate(submesh.faces or ()):
        vertices = _valid_face_vertices(face, len(submesh.vertices))
        if len(vertices) == 3:
            items.append((face_index, (vertices[0], vertices[1], vertices[2])))
    return tuple(items)


def _selected_existing_edges(mesh: ParsedMesh, selection: MeshEditSelection) -> dict[int, set[tuple[int, int]]]:
    selected: dict[int, set[tuple[int, int]]] = {}
    for submesh_index, edges in selection.edge_map().items():
        if not 0 <= submesh_index < len(mesh.submeshes):
            continue
        kept = _valid_selected_edges_for_submesh(mesh.submeshes[submesh_index], edges)
        if kept:
            selected[submesh_index] = kept
    return selected


def _valid_selected_edges_for_submesh(submesh: SubMesh, edges: set[tuple[int, int]]) -> set[tuple[int, int]]:
    vertex_count = len(submesh.vertices)
    selected = {
        _edge_key(a, b)
        for a, b in edges
        if 0 <= a < vertex_count and 0 <= b < vertex_count
    }
    if not selected:
        return set()
    if not submesh.faces:
        return selected
    return selected & _existing_face_edges(submesh)


def _existing_face_edges(submesh: SubMesh) -> set[tuple[int, int]]:
    vertex_count = len(submesh.vertices)
    edges: set[tuple[int, int]] = set()
    for face in submesh.faces or ():
        if len(face) < 3:
            continue
        vertices = [_coerce_index(raw_index) for raw_index in face[:3]]
        if any(vertex_index is None for vertex_index in vertices):
            continue
        a, b, c = (int(vertex_index) for vertex_index in vertices if vertex_index is not None)
        if 0 <= a < vertex_count and 0 <= b < vertex_count and 0 <= c < vertex_count:
            edges.update((_edge_key(a, b), _edge_key(b, c), _edge_key(c, a)))
    return edges


def _changed_from_vertices(vertices: MeshEditChangedVertices) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    changed: MeshEditChangedVertices = {}
    for index, values in vertices.items():
        if not values:
            continue
        normalized = _changed_vertex_values(values)
        if normalized:
            changed[index] = normalized
    return set(changed), changed


def _changed_vertex_values(values: object) -> Sequence[int] | set[int]:
    if isinstance(values, range):
        return values if values.step == 1 and values.start >= 0 else ()
    if isinstance(values, Mapping):
        for start_key, count_key in (
            ("changed_vertex_start", "changed_vertex_count"),
            ("vertex_index_start", "vertex_index_count"),
            ("source_vertex_start", "source_vertex_count"),
        ):
            try:
                start = int(values.get(start_key, -1))
                count = int(values.get(count_key, 0))
            except (TypeError, ValueError, OverflowError):
                continue
            if start >= 0 and count > 0:
                return range(start, start + count)
        return set()
    return set(values)  # type: ignore[arg-type]


def _transform(
    mesh: ParsedMesh,
    selection: MeshEditSelection,
    params: dict[str, object],
) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    axis_mask = _axis_mask(params.get("axis", params.get("constraint_axis", "")))
    translate = _constrain_vec3(
        _vec3(params.get("translate", params.get("delta", (0.0, 0.0, 0.0)))),
        axis_mask,
        (0.0, 0.0, 0.0),
    )
    scale = _constrain_vec3(_vec3(params.get("scale", (1.0, 1.0, 1.0)), (1.0, 1.0, 1.0)), axis_mask, (1.0, 1.0, 1.0))
    rotate = _constrain_vec3(
        _vec3(params.get("rotate", params.get("rotate_degrees", (0.0, 0.0, 0.0)))),
        axis_mask,
        (0.0, 0.0, 0.0),
    )
    snap = _positive_float(params.get("snap", params.get("snap_increment", 0.0)))
    recompute_normals = bool(params.get("recompute_normals", True))
    history_delta = bool(params.get("_require_native_history_delta", False))
    pivot = params.get("pivot")
    pivot_vec = _vec3(pivot) if pivot is not None else None
    native_mirror_x = bool(params.get("mirror_x", False)) and scale == (1.0, 1.0, 1.0) and rotate == (0.0, 0.0, 0.0)
    native_binary_vertices = (
        params.get("native_selected_vertices_binary_by_submesh")
        if isinstance(params.get("native_selected_vertices_binary_by_submesh"), Mapping)
        else {}
    )
    native_changed = apply_native_mesh_transform_binary_selection(
        mesh,
        selected_vertices_binary_by_submesh=native_binary_vertices,
        translate=translate,
        scale=scale,
        rotate=rotate,
        pivot=pivot_vec,
        snap=snap,
        mirror_x=native_mirror_x,
        mirror_pairs_by_submesh=params.get("mirror_pairs_by_submesh") if isinstance(params.get("mirror_pairs_by_submesh"), Mapping) else None,
        history_delta=history_delta,
        **_native_kwargs(params),
    )
    if native_changed is not None:
        if recompute_normals:
            _recompute_normals_after_native_edit(
                mesh,
                native_changed,
                "native normal recompute unavailable after binary transform",
            )
        return _changed_from_vertices(native_changed)
    if native_binary_vertices:
        return set(), {}
    native_changed = apply_native_mesh_transform_selection(
        mesh,
        vertices_by_submesh=selection.vertex_map(),
        edges_by_submesh=selection.edge_map(),
        faces_by_submesh=selection.face_map(),
        source_indices=selection.source_indices,
        translate=translate,
        scale=scale,
        rotate=rotate,
        pivot=pivot_vec,
        snap=snap,
        mirror_x=native_mirror_x,
        mirror_pairs_by_submesh=params.get("mirror_pairs_by_submesh") if isinstance(params.get("mirror_pairs_by_submesh"), Mapping) else None,
        history_delta=history_delta,
        **_native_kwargs(params),
    )
    if native_changed is not None:
        if recompute_normals:
            _recompute_normals_after_native_edit(
                mesh,
                native_changed,
                "native normal recompute unavailable after transform",
            )
        return _changed_from_vertices(native_changed)
    if history_delta:
        raise NativeLiveHistoryUnavailable("native transform history delta unavailable")
    python_expansion_domains = selection.edge_map() or selection.face_map() or set(selection.source_indices)
    if python_expansion_domains and not _allow_python_mesh_edit_fallback(
        mesh,
        "live_edit.transform",
        submesh_indices=python_expansion_domains,
    ):
        return set(), {}
    vertices_by_submesh = _selected_vertices(mesh, selection, fallback_all=False)
    if not vertices_by_submesh:
        return set(), {}
    native_changed = apply_native_mesh_transform(
        mesh,
        vertices_by_submesh,
        translate=translate,
        scale=scale,
        rotate=rotate,
        pivot=pivot_vec,
        snap=snap,
        mirror_x=native_mirror_x,
        mirror_pairs_by_submesh=params.get("mirror_pairs_by_submesh") if isinstance(params.get("mirror_pairs_by_submesh"), Mapping) else None,
        history_delta=history_delta,
        **_native_kwargs(params),
    )
    if native_changed is not None:
        if recompute_normals:
            _recompute_normals_after_native_edit(
                mesh,
                native_changed,
                "native normal recompute unavailable after transform",
            )
        return _changed_from_vertices(native_changed)
    if history_delta:
        raise NativeLiveHistoryUnavailable("native transform history delta unavailable")
    _record_native_edit_fallback(mesh, "live_edit.transform", "native transform unavailable", submesh_indices=vertices_by_submesh)
    if not _allow_python_mesh_edit_fallback(mesh, "live_edit.transform", submesh_indices=vertices_by_submesh):
        return set(), {}
    pivot_vec = _selection_center(mesh, vertices_by_submesh) if pivot_vec is None else pivot_vec
    if native_mirror_x:
        changed: MeshEditChangedVertices = {}
        mirror_pairs_by_submesh = params.get("mirror_pairs_by_submesh")
        for submesh_index, indices in vertices_by_submesh.items():
            touched = apply_vertex_delta(
                mesh.submeshes[submesh_index],
                indices,
                translate,
                mirror_x=True,
                mirror_pairs=_mirror_pairs_for_submesh(mirror_pairs_by_submesh, submesh_index),
                recompute_normals=recompute_normals,
            )
            if touched:
                changed[submesh_index] = set(touched)
        return _changed_from_vertices(changed)
    changed: MeshEditChangedVertices = {}
    for submesh_index, indices in vertices_by_submesh.items():
        submesh = mesh.submeshes[submesh_index]
        vertices = list(submesh.vertices)
        touched = changed.setdefault(submesh_index, set())
        for vertex_index in indices:
            old_vertex = _vec3(vertices[vertex_index])
            transformed = _transform_vertex(old_vertex, pivot_vec, translate, scale, rotate)
            new_vertex = _snap_vertex(transformed, snap)
            if not _same_vec3(old_vertex, new_vertex):
                vertices[vertex_index] = new_vertex
                touched.add(vertex_index)
        if touched:
            submesh.vertices = vertices
            submesh.vertex_count = len(vertices)
            if recompute_normals:
                recompute_submesh_normals(submesh)
    return _changed_from_vertices(changed)


def _mirror_pairs_for_submesh(value: object, submesh_index: int) -> dict[int, int] | None:
    if not isinstance(value, dict):
        return None
    pairs = value.get(submesh_index, value.get(str(submesh_index)))
    if not isinstance(pairs, dict):
        return None
    result: dict[int, int] = {}
    for raw_index, raw_mirror in pairs.items():
        try:
            index = int(raw_index)
            mirror = int(raw_mirror)
        except (TypeError, ValueError, OverflowError):
            continue
        if index >= 0 and mirror >= 0:
            result[index] = mirror
    return result or None


def _adjacency_for_submesh(value: object, submesh_index: int) -> Sequence[set[int]] | None:
    if not isinstance(value, dict):
        return None
    adjacency = value.get(submesh_index, value.get(str(submesh_index)))
    return adjacency if isinstance(adjacency, (list, tuple)) else None


def _selection_center(mesh: ParsedMesh, vertices_by_submesh: dict[int, set[int]]) -> Vec3:
    vertices: list[Vec3] = []
    for submesh_index, indices in vertices_by_submesh.items():
        submesh = mesh.submeshes[submesh_index]
        for vertex_index in indices:
            vertices.append(_vec3(submesh.vertices[vertex_index]))
    if not vertices:
        return (0.0, 0.0, 0.0)
    count = float(len(vertices))
    return (
        sum(vertex[0] for vertex in vertices) / count,
        sum(vertex[1] for vertex in vertices) / count,
        sum(vertex[2] for vertex in vertices) / count,
    )


def _axis_mask(value: object) -> tuple[bool, bool, bool]:
    normalized = str(value or "").strip().lower()
    if not normalized or normalized in {"all", "free", "xyz"}:
        return (True, True, True)
    axes = {axis for axis in normalized if axis in {"x", "y", "z"}}
    if not axes:
        return (True, True, True)
    return ("x" in axes, "y" in axes, "z" in axes)


def _constrain_vec3(value: Vec3, mask: tuple[bool, bool, bool], defaults: Vec3) -> Vec3:
    return (
        value[0] if mask[0] else defaults[0],
        value[1] if mask[1] else defaults[1],
        value[2] if mask[2] else defaults[2],
    )


def _positive_float(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not math.isfinite(parsed) or parsed <= 0.0:
        return 0.0
    return parsed


def _nonnegative_int(value: object) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return parsed if parsed >= 0 else 0


def _snap_vertex(vertex: Vec3, increment: float) -> Vec3:
    if increment <= 0.0:
        return vertex
    return (
        _snap_value(vertex[0], increment),
        _snap_value(vertex[1], increment),
        _snap_value(vertex[2], increment),
    )


def _snap_value(value: float, increment: float) -> float:
    snapped = round(value / increment) * increment
    return 0.0 if abs(snapped) < 1e-12 else snapped


def _transform_vertex(vertex: Vec3, pivot: Vec3, translate: Vec3, scale: Vec3, rotate_degrees: Vec3) -> Vec3:
    x = (vertex[0] - pivot[0]) * scale[0]
    y = (vertex[1] - pivot[1]) * scale[1]
    z = (vertex[2] - pivot[2]) * scale[2]
    rx, ry, rz = (math.radians(value) for value in rotate_degrees)
    if abs(rx) > 1e-8:
        cy, sy = math.cos(rx), math.sin(rx)
        y, z = y * cy - z * sy, y * sy + z * cy
    if abs(ry) > 1e-8:
        cx, sx = math.cos(ry), math.sin(ry)
        x, z = x * cx + z * sx, -x * sx + z * cx
    if abs(rz) > 1e-8:
        cx, sx = math.cos(rz), math.sin(rz)
        x, y = x * cx - y * sx, x * sx + y * cx
    return (pivot[0] + x + translate[0], pivot[1] + y + translate[1], pivot[2] + z + translate[2])


def _same_vec3(left: Vec3, right: Vec3) -> bool:
    return abs(left[0] - right[0]) <= 1e-8 and abs(left[1] - right[1]) <= 1e-8 and abs(left[2] - right[2]) <= 1e-8


def _same_vec3_tuple(left: tuple[Vec3, ...], right: tuple[Vec3, ...]) -> bool:
    return len(left) == len(right) and all(_same_vec3(left_item, right_item) for left_item, right_item in zip(left, right))


def _brush(
    mesh: ParsedMesh,
    selection: MeshEditSelection,
    params: dict[str, object],
) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    history_delta = bool(params.get("_require_native_history_delta", False))
    native_binary_vertices = (
        params.get("native_selected_vertices_binary_by_submesh")
        if isinstance(params.get("native_selected_vertices_binary_by_submesh"), Mapping)
        else {}
    )
    native_binary_selection = apply_native_mesh_brush_binary_selection(
        mesh,
        selected_vertices_binary_by_submesh=native_binary_vertices,
        vertex_weights_binary_by_submesh=params.get("native_vertex_weights_binary_by_submesh")
        if isinstance(params.get("native_vertex_weights_binary_by_submesh"), Mapping)
        else {},
        params=params,
        history_delta=history_delta,
        **_native_kwargs(params),
    )
    if native_binary_selection is not None:
        return _changed_from_vertices(native_binary_selection)
    if native_binary_vertices:
        return _changed_from_vertices({})
    if not selection.is_empty():
        native_changed = apply_native_mesh_brush_selection(
            mesh,
            vertices_by_submesh=selection.vertex_map(),
            edges_by_submesh=selection.edge_map(),
            faces_by_submesh=selection.face_map(),
            source_indices=selection.source_indices,
            params=params,
            history_delta=history_delta,
            **_native_kwargs(params),
        )
        if native_changed is not None:
            return _changed_from_vertices(native_changed)
        if history_delta:
            raise NativeLiveHistoryUnavailable("native brush history delta unavailable")
    python_expansion_domains = selection.edge_map() or selection.face_map() or set(selection.source_indices)
    if python_expansion_domains and not _allow_python_mesh_edit_fallback(
        mesh,
        f"live_edit.{str(params.get('tool', 'brush') or 'brush')}",
        submesh_indices=python_expansion_domains,
    ):
        return set(), {}
    selected = _selected_vertices(mesh, selection, fallback_all=False)
    native_selected: dict[int, set[int] | None] = (
        {submesh_index: set(vertices) for submesh_index, vertices in selected.items()}
        if selected
        else {index: None for index, _submesh in enumerate(mesh.submeshes)}
    )
    native_changed = apply_native_mesh_brush(mesh, native_selected, params, history_delta=history_delta, **_native_kwargs(params))
    if native_changed is not None:
        return _changed_from_vertices(native_changed)
    if history_delta:
        raise NativeLiveHistoryUnavailable("native brush history delta unavailable")
    _record_native_edit_fallback(
        mesh,
        f"live_edit.{str(params.get('tool', 'brush') or 'brush')}",
        "native brush unavailable",
        submesh_indices=native_selected,
    )
    if not _allow_python_mesh_edit_fallback(
        mesh,
        f"live_edit.{str(params.get('tool', 'brush') or 'brush')}",
        submesh_indices=native_selected,
    ):
        return set(), {}
    if not selected:
        selected = {index: None for index, _submesh in enumerate(mesh.submeshes)}
    changed: MeshEditChangedVertices = {}
    mirror_pairs_by_submesh = params.get("mirror_pairs_by_submesh")
    adjacency_by_submesh = params.get("adjacency_by_submesh")
    for submesh_index, vertex_indices in selected.items():
        submesh = mesh.submeshes[submesh_index]
        touched = apply_brush_deformation(
            submesh,
            tool=str(params.get("tool", "grab")),
            center=_vec3(params.get("center", (0.0, 0.0, 0.0))),
            radius=params.get("radius", 1.0),  # type: ignore[arg-type]
            strength=params.get("strength", 1.0),  # type: ignore[arg-type]
            drag_delta=_vec3(params.get("drag_delta", params.get("delta", (0.0, 0.0, 0.0)))),
            amount=params.get("amount", 0.0),  # type: ignore[arg-type]
            falloff=str(params.get("falloff", "smooth")),
            vertex_indices=vertex_indices,
            vertex_weights=params.get("vertex_weights"),  # type: ignore[arg-type]
            mirror_x=bool(params.get("mirror_x", False)),
            mirror_pairs=_mirror_pairs_for_submesh(mirror_pairs_by_submesh, submesh_index),
            adjacency=_adjacency_for_submesh(adjacency_by_submesh, submesh_index),
            iterations=params.get("iterations", 1),  # type: ignore[arg-type]
            invert=bool(params.get("invert", False)),
            recompute_normals=bool(params.get("recompute_normals", True)),
        )
        if touched:
            changed[submesh_index] = set(touched)
    return _changed_from_vertices(changed)


def _delete(
    mesh: ParsedMesh,
    selection: MeshEditSelection,
    params: dict[str, object],
    *,
    remove_orphans: bool,
) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    if _truthy(params.get("delete_parts")) and selection.source_indices:
        return _delete_submeshes(mesh, selection.source_indices), {}
    faces = selection.face_map()
    edges = selection.edge_map()
    vertices = selection.vertex_map()
    all_faces = set(selection.source_indices)
    native_binary_vertices = (
        params.get("native_selected_vertices_binary_by_submesh")
        if isinstance(params.get("native_selected_vertices_binary_by_submesh"), Mapping)
        else {}
    )
    if faces or edges or vertices or native_binary_vertices or all_faces:
        native_affected = apply_native_mesh_delete(
            mesh,
            faces,
            vertices,
            selected_edges_by_submesh=edges,
            selected_vertices_binary_by_submesh=native_binary_vertices,
            all_faces_by_submesh=all_faces,
            remove_orphans=remove_orphans,
            recompute_normals=bool(params.get("recompute_normals", True)),
            **_native_kwargs(params),
        )
        if native_affected is not None:
            refresh_mesh_totals(mesh)
            return native_affected, {}
        _record_native_edit_fallback(mesh, "topology.delete", "native delete unavailable", submesh_indices=faces or vertices or edges or all_faces)
        if not _allow_python_mesh_edit_fallback(mesh, "topology.delete", submesh_indices=faces or vertices or edges or all_faces):
            return set(), {}
        faces = _selected_faces(mesh, selection, fallback_all=False)
    if faces:
        result = delete_faces_by_indices(mesh, faces, remove_orphans=remove_orphans)
    else:
        return set(), {}
    return set(result.affected_submesh_indices), {}


def _dissolve(mesh: ParsedMesh, selection: MeshEditSelection) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    faces = selection.face_map()
    edges = selection.edge_map()
    vertices = selection.vertex_map()
    all_faces = set(selection.source_indices)
    if faces or edges or vertices or all_faces:
        native_affected = apply_native_mesh_dissolve(
            mesh,
            faces,
            vertices,
            selected_edges_by_submesh=edges,
            all_faces_by_submesh=all_faces,
            recompute_normals=True,
        )
        if native_affected is not None:
            refresh_mesh_totals(mesh)
            return set(native_affected), {}
        _record_native_edit_fallback(mesh, "topology.dissolve", "native dissolve unavailable", submesh_indices=faces or vertices or edges or all_faces)
        if not _allow_python_mesh_edit_fallback(mesh, "topology.dissolve", submesh_indices=faces or vertices or edges or all_faces):
            return set(), {}
    if edges:
        affected = _dissolve_internal_edges(mesh, edges)
        if affected:
            refresh_mesh_totals(mesh)
            return affected, {}
    return _delete(mesh, selection, {}, remove_orphans=False)


def _delete_submeshes(mesh: ParsedMesh, source_indices: Sequence[int]) -> set[int]:
    indices = sorted(
        {int(index) for index in source_indices if 0 <= int(index) < len(mesh.submeshes)},
        reverse=True,
    )
    if not indices:
        return set()
    for index in indices:
        del mesh.submeshes[index]
    refresh_mesh_totals(mesh)
    return set(indices)


def _dissolve_internal_edges(mesh: ParsedMesh, selected_edges: dict[int, set[tuple[int, int]]]) -> set[int]:
    affected: set[int] = set()
    for submesh_index, raw_edges in selected_edges.items():
        if not 0 <= submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        valid_edges = {
            _edge_key(a, b)
            for a, b in raw_edges
            if 0 <= a < len(submesh.vertices) and 0 <= b < len(submesh.vertices)
        }
        if not valid_edges:
            continue
        edge_faces: dict[tuple[int, int], list[int]] = {}
        face_by_index: dict[int, tuple[int, int, int]] = {}
        face_order: list[int] = []
        for face_index, face in enumerate(submesh.faces or ()):
            vertices = _valid_face_vertices(face, len(submesh.vertices))
            if len(vertices) != 3:
                continue
            a, b, c = vertices
            face_by_index[face_index] = (a, b, c)
            face_order.append(face_index)
            for edge in (_edge_key(a, b), _edge_key(b, c), _edge_key(c, a)):
                edge_faces.setdefault(edge, []).append(face_index)
        if any(len(edge_faces.get(edge, ())) != 2 for edge in valid_edges):
            continue
        replacements: dict[int, tuple[int, int, int]] = {}
        used_faces: set[int] = set()
        for edge in sorted(valid_edges):
            face_indices = edge_faces[edge]
            if any(face_index in used_faces for face_index in face_indices):
                replacements = {}
                break
            left, right = edge
            first_face = face_by_index[face_indices[0]]
            second_face = face_by_index[face_indices[1]]
            first_opposite = next((index for index in first_face if index not in edge), -1)
            second_opposite = next((index for index in second_face if index not in edge), -1)
            if first_opposite < 0 or second_opposite < 0 or first_opposite == second_opposite:
                replacements = {}
                break
            lower, upper = sorted(face_indices)
            replacements[lower] = (first_opposite, left, second_opposite)
            replacements[upper] = (first_opposite, second_opposite, right)
            used_faces.update(face_indices)
        if not replacements:
            continue
        submesh.faces = [
            replacements.get(face_index, face_by_index[face_index])
            for face_index in face_order
        ]
        submesh.face_count = len(submesh.faces)
        recompute_submesh_normals(submesh)
        affected.add(submesh_index)
    return affected


def _subdivide(
    mesh: ParsedMesh,
    selection: MeshEditSelection,
    params: dict[str, object],
) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    faces = selection.face_map()
    edges = selection.edge_map()
    all_faces = set(selection.source_indices)
    face_selection = bool(edges or faces or all_faces)
    vertices = {} if face_selection else selection.vertex_map()
    if not (faces or edges or vertices or all_faces):
        return set(), {}
    native_result = apply_native_mesh_subdivide(
        mesh,
        faces,
        vertices,
        params,
        selected_edges_by_submesh=edges,
        all_faces_by_submesh=all_faces,
        refine=False,
        recompute_normals=bool(params.get("recompute_normals", True)),
        **_native_kwargs(params),
    )
    if native_result is not None:
        return native_result
    _record_native_edit_fallback(mesh, "topology.subdivide", "native subdivide unavailable", submesh_indices=faces or vertices or edges or all_faces)
    if not _allow_python_mesh_edit_fallback(mesh, "topology.subdivide", submesh_indices=faces or vertices or edges or all_faces):
        return set(), {}
    faces = _selected_faces(mesh, selection, fallback_all=False) if face_selection else {}
    vertices = {} if face_selection else _selected_vertices(mesh, selection, fallback_all=False)
    if face_selection and not faces:
        return set(), {}
    result = subdivide_faces_touching_vertices(
        mesh,
        vertices,
        selected_faces_by_submesh=faces,
        max_faces_per_submesh=int(params.get("max_faces_per_submesh", 256) or 256),
        recompute_normals=bool(params.get("recompute_normals", True)),
    )
    return set(result.affected_submesh_indices), result.changed_vertices_by_submesh or {}


def _refine_smooth(
    mesh: ParsedMesh,
    selection: MeshEditSelection,
    params: dict[str, object],
) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    faces = selection.face_map()
    edges = selection.edge_map()
    all_faces = set(selection.source_indices)
    face_selection = bool(edges or faces or all_faces)
    vertices = {} if face_selection else selection.vertex_map()
    if not (faces or edges or vertices or all_faces):
        return set(), {}
    native_result = apply_native_mesh_subdivide(
        mesh,
        faces,
        vertices,
        params,
        selected_edges_by_submesh=edges,
        all_faces_by_submesh=all_faces,
        refine=True,
        recompute_normals=bool(params.get("recompute_normals", True)),
        **_native_kwargs(params),
    )
    if native_result is not None:
        return native_result
    _record_native_edit_fallback(mesh, "topology.refine_smooth", "native refine smooth unavailable", submesh_indices=faces or vertices or edges or all_faces)
    if not _allow_python_mesh_edit_fallback(mesh, "topology.refine_smooth", submesh_indices=faces or vertices or edges or all_faces):
        return set(), {}
    faces = _selected_faces(mesh, selection, fallback_all=False) if face_selection else {}
    vertices = {} if face_selection else _selected_vertices(mesh, selection, fallback_all=False)
    if face_selection and not faces:
        return set(), {}
    affected, changed = _subdivide(mesh, selection, params)
    if not changed:
        return affected, changed
    strength = max(0.0, min(1.0, _float_value(params.get("smooth_strength", params.get("strength", 0.5)), 0.5)))
    iterations = max(1, min(12, _positive_int(params.get("smooth_iterations", params.get("iterations", 2)), 2)))
    recompute_normals = bool(params.get("recompute_normals", True))
    for submesh_index, vertex_indices in tuple(changed.items()):
        if not 0 <= submesh_index < len(mesh.submeshes):
            continue
        selected = {int(index) for index in vertex_indices if 0 <= int(index) < len(mesh.submeshes[submesh_index].vertices)}
        if not selected:
            continue
        smoothed = apply_brush_deformation(
            mesh.submeshes[submesh_index],
            tool="smooth",
            center=(0.0, 0.0, 0.0),
            radius=0.0,
            strength=strength,
            vertex_indices=selected,
            vertex_weights={index: 1.0 for index in selected},
            iterations=iterations,
            recompute_normals=recompute_normals,
        )
        if smoothed:
            changed.setdefault(submesh_index, set()).update(smoothed)
    refresh_mesh_totals(mesh)
    return affected, changed


def _split(
    mesh: ParsedMesh,
    selection: MeshEditSelection,
    params: dict[str, object],
) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    faces = selection.face_map()
    edges = selection.edge_map()
    all_faces = set(selection.source_indices)
    face_selection = bool(edges or faces or all_faces)
    vertices = {} if face_selection else selection.vertex_map()
    if faces or edges or vertices or all_faces:
        native_result = apply_native_mesh_split(
            mesh,
            faces,
            vertices,
            params,
            selected_edges_by_submesh=edges,
            all_faces_by_submesh=all_faces,
            recompute_normals=bool(params.get("recompute_normals", True)),
            **_native_kwargs(params),
        )
        if native_result is not None:
            return native_result
        _record_native_edit_fallback(mesh, "topology.split", "native split unavailable", submesh_indices=faces or vertices or edges or all_faces)
        if not _allow_python_mesh_edit_fallback(mesh, "topology.split", submesh_indices=faces or vertices or edges or all_faces):
            return set(), {}
    faces = _selected_faces(mesh, selection, fallback_all=False)
    changed: MeshEditChangedVertices = {}
    for submesh_index, face_indices in faces.items():
        submesh = mesh.submeshes[submesh_index]
        selected_faces = {
            int(face_index)
            for face_index in face_indices
            if 0 <= int(face_index) < len(submesh.faces)
        }
        if not selected_faces:
            continue
        selected_vertices: set[int] = set()
        unselected_vertices: set[int] = set()
        valid_faces: list[tuple[int, tuple[int, int, int]]] = []
        for face_index, face in enumerate(submesh.faces or ()):
            vertices = _valid_face_vertices(face, len(submesh.vertices))
            if len(vertices) != 3:
                continue
            normalized = (vertices[0], vertices[1], vertices[2])
            valid_faces.append((face_index, normalized))
            if face_index in selected_faces:
                selected_vertices.update(normalized)
            else:
                unselected_vertices.update(normalized)
        shared_vertices = sorted(selected_vertices & unselected_vertices)
        if not shared_vertices:
            continue
        split_map: dict[int, int] = {}
        touched = changed.setdefault(submesh_index, set())
        for vertex_index in shared_vertices:
            split_map[vertex_index] = _append_vertex_copy(submesh, vertex_index, _vec3(submesh.vertices[vertex_index]))
            touched.add(split_map[vertex_index])
        submesh.faces = [
            tuple(split_map.get(vertex_index, vertex_index) for vertex_index in face) if face_index in selected_faces else face
            for face_index, face in valid_faces
        ]
        submesh.face_count = len(submesh.faces)
        if bool(params.get("recompute_normals", True)):
            recompute_submesh_normals(submesh)
    refresh_mesh_totals(mesh)
    return _changed_from_vertices(changed)


def _separate(
    mesh: ParsedMesh,
    selection: MeshEditSelection,
    params: dict[str, object],
) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    native_result = apply_native_mesh_separate(
        mesh,
        selection.face_map(),
        selection.vertex_map(),
        selected_edges_by_submesh=selection.edge_map(),
        recompute_normals=bool(params.get("recompute_normals", True)),
    )
    if native_result is not None:
        affected = {
            index
            for index in (native_result.source_submesh_index, native_result.new_submesh_index)
            if index >= 0
        }
        for new_index in (native_result.new_submesh_index,):
            source_index = native_result.source_submesh_index
            if not (0 <= source_index < len(mesh.submeshes) and 0 <= new_index < len(mesh.submeshes)):
                continue
            source = mesh.submeshes[source_index]
            moved = mesh.submeshes[new_index]
            _copy_material_route_metadata(source, moved)
            moved.cdmw_mesh_edit_material_source_submesh_index = source_index
            moved.cdmw_mesh_edit_topology_source_submesh_index = source_index
        refresh_mesh_totals(mesh)
        return affected, {}

    raw_targets = selection.face_map() or selection.vertex_map() or selection.edge_map() or set(selection.source_indices)
    _record_native_edit_fallback(mesh, "topology.separate", "native separate unavailable", submesh_indices=raw_targets)
    if raw_targets and not _allow_python_mesh_edit_fallback(mesh, "topology.separate", submesh_indices=raw_targets):
        return set(), {}
    selected_faces = _selected_faces(mesh, selection, fallback_all=False)
    result = split_faces_to_submesh(
        mesh,
        selected_faces_by_submesh=selected_faces,
        recompute_normals=bool(params.get("recompute_normals", True)),
    )
    affected = {index for index in (result.source_submesh_index, result.new_submesh_index) if index >= 0}
    return affected, {}


def _duplicate(
    mesh: ParsedMesh,
    selection: MeshEditSelection,
    params: dict[str, object],
) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    raw_faces = selection.face_map()
    raw_vertices = selection.vertex_map()
    raw_edges = selection.edge_map()
    all_faces_by_submesh = {
        index
        for index in selection.source_indices
        if 0 <= index < len(mesh.submeshes)
    }
    if bool(params.get("all", False)) and selection.is_empty():
        all_faces_by_submesh.update(range(len(mesh.submeshes)))
    native_duplicate = apply_native_mesh_duplicate(
        mesh,
        raw_faces,
        raw_vertices,
        selected_edges_by_submesh=raw_edges,
        all_faces_by_submesh=all_faces_by_submesh,
        recompute_normals=bool(params.get("recompute_normals", True)),
    )
    if native_duplicate is not None:
        native_indices, source_by_new = native_duplicate
        for new_index, source_index in source_by_new.items():
            if not (0 <= source_index < len(mesh.submeshes) and 0 <= new_index < len(mesh.submeshes)):
                continue
            source = mesh.submeshes[source_index]
            copied = mesh.submeshes[new_index]
            _copy_material_route_metadata(source, copied)
            copied.cdmw_mesh_edit_material_source_submesh_index = source_index
            copied.cdmw_mesh_edit_topology_source_submesh_index = source_index
            if not copied.normals:
                recompute_submesh_normals(copied)
        refresh_mesh_totals(mesh)
        return set(native_indices), {}

    new_indices: set[int] = set()
    raw_targets = raw_faces or raw_vertices or raw_edges or all_faces_by_submesh
    if raw_targets:
        _record_native_edit_fallback(mesh, "topology.duplicate", "native duplicate unavailable", submesh_indices=raw_targets)
        if not _allow_python_mesh_edit_fallback(mesh, "topology.duplicate", submesh_indices=raw_targets):
            return set(), {}
    faces = _selected_faces(mesh, selection, fallback_all=bool(params.get("all", False)))
    if faces:
        for submesh_index, face_indices in faces.items():
            new_index = _append_face_copy(mesh, submesh_index, face_indices, " duplicate")
            if new_index >= 0:
                new_indices.add(new_index)
    else:
        return set(), {}
    refresh_mesh_totals(mesh)
    return new_indices, {}


def _mirror(
    mesh: ParsedMesh,
    selection: MeshEditSelection,
    params: dict[str, object],
) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    axis = str(params.get("axis", "x")).strip().lower()
    axis_index = {"x": 0, "y": 1, "z": 2}.get(axis, 0)
    axis_name = ("x", "y", "z")[axis_index]
    in_place = bool(params.get("in_place", False))
    face_selection = selection.face_map()
    edge_selection = selection.edge_map()
    vertex_selection = selection.vertex_map()
    all_faces = set(selection.source_indices)
    affected: set[int] = set()
    changed: MeshEditChangedVertices = {}
    if in_place:
        if not (face_selection or edge_selection or vertex_selection or all_faces):
            return set(), {}
        scale_values = [1.0, 1.0, 1.0]
        scale_values[axis_index] = -1.0
        native_changed = apply_native_mesh_transform_selection(
            mesh,
            vertices_by_submesh=vertex_selection,
            edges_by_submesh=edge_selection,
            faces_by_submesh=face_selection,
            source_indices=selection.source_indices,
            translate=(0.0, 0.0, 0.0),
            scale=(scale_values[0], scale_values[1], scale_values[2]),
            rotate=(0.0, 0.0, 0.0),
            pivot=(0.0, 0.0, 0.0),
            snap=0.0,
            **_native_kwargs(params),
        )
        if native_changed is not None:
            _recompute_normals_after_native_edit(
                mesh,
                native_changed,
                "native normal recompute unavailable after in-place mirror",
            )
            return _changed_from_vertices(native_changed)
        _record_native_edit_fallback(
            mesh,
            "topology.mirror",
            "native in-place mirror unavailable",
            submesh_indices=face_selection or vertex_selection or edge_selection or all_faces,
        )
        if not _allow_python_mesh_edit_fallback(
            mesh,
            "topology.mirror",
            submesh_indices=face_selection or vertex_selection or edge_selection or all_faces,
        ):
            return set(), {}
        selected = _selected_vertices(mesh, selection, fallback_all=False)
        if not selected:
            return set(), {}
        for submesh_index, vertex_indices in selected.items():
            submesh = mesh.submeshes[submesh_index]
            vertices = list(submesh.vertices)
            for vertex_index in vertex_indices:
                vertex = list(_vec3(vertices[vertex_index]))
                vertex[axis_index] = -vertex[axis_index]
                vertices[vertex_index] = tuple(vertex)  # type: ignore[assignment]
            submesh.vertices = vertices
            recompute_submesh_normals(submesh)
            affected.add(submesh_index)
            changed[submesh_index] = set(vertex_indices)
    else:
        if not (face_selection or edge_selection or vertex_selection or all_faces):
            return set(), {}
        native_result = apply_native_mesh_mirror(
            mesh,
            face_selection,
            vertex_selection,
            axis=axis_name,
            selected_edges_by_submesh=edge_selection,
            all_faces_by_submesh=all_faces,
            recompute_normals=True,
            **_native_kwargs(params),
        )
        if native_result is not None:
            native_indices, _source_by_new = native_result
            return set(native_indices), {}
        _record_native_edit_fallback(
            mesh,
            "topology.mirror",
            "native mirror unavailable",
            submesh_indices=face_selection or vertex_selection or edge_selection or all_faces,
        )
        if not _allow_python_mesh_edit_fallback(
            mesh,
            "topology.mirror",
            submesh_indices=face_selection or vertex_selection or edge_selection or all_faces,
        ):
            return set(), {}
        faces = _selected_faces(mesh, selection, fallback_all=False)
        if faces:
            for submesh_index, face_indices in faces.items():
                new_index = _append_mirrored_face_copy(mesh, submesh_index, face_indices, axis_index)
                if new_index >= 0:
                    affected.add(new_index)
    refresh_mesh_totals(mesh)
    return affected, changed


def _mirrored(vertex: object, axis_index: int) -> Vec3:
    values = list(_vec3(vertex))
    values[axis_index] = -values[axis_index]
    return (values[0], values[1], values[2])


def _extrude(
    mesh: ParsedMesh,
    selection: MeshEditSelection,
    params: dict[str, object],
) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    face_selection = selection.face_map()
    edge_selection = selection.edge_map()
    vertex_selection = selection.vertex_map()
    all_faces = set(selection.source_indices)
    if face_selection or edge_selection or vertex_selection or all_faces:
        native_result = apply_native_mesh_extrude(
            mesh,
            face_selection,
            vertex_selection,
            params,
            selected_edges_by_submesh=edge_selection,
            all_faces_by_submesh=all_faces,
            recompute_normals=bool(params.get("recompute_normals", True)),
        )
        if native_result is not None:
            return native_result
        _record_native_edit_fallback(mesh, "topology.extrude", "native extrude unavailable", submesh_indices=face_selection or vertex_selection or edge_selection or all_faces)
        if not _allow_python_mesh_edit_fallback(mesh, "topology.extrude", submesh_indices=face_selection or vertex_selection or edge_selection or all_faces):
            return set(), {}
    faces = _selected_faces(mesh, selection, fallback_all=False)
    offset = _vec3(params.get("offset", params.get("delta", (0.0, 0.0, 0.25))))
    if not faces and selection.edge_map():
        return _extrude_edges(mesh, _selected_existing_edges(mesh, selection), offset, bool(params.get("recompute_normals", True)))
    changed: MeshEditChangedVertices = {}
    for submesh_index, face_indices in faces.items():
        submesh = mesh.submeshes[submesh_index]
        valid_faces = dict(_valid_face_items(submesh))
        selected_faces = [valid_faces[face_index] for face_index in sorted(face_indices) if face_index in valid_faces]
        if not selected_faces:
            continue
        new_vertices: dict[int, int] = {}
        touched = changed.setdefault(submesh_index, set())
        edge_counts: dict[tuple[int, int], int] = {}
        edge_order: dict[tuple[int, int], tuple[int, int]] = {}
        for face in selected_faces:
            for vertex_index in face:
                if vertex_index not in new_vertices:
                    new_vertices[vertex_index] = _append_vertex_copy(submesh, vertex_index, _add(_vec3(submesh.vertices[vertex_index]), offset))
                    touched.add(new_vertices[vertex_index])
            a, b, c = face
            for left, right in ((a, b), (b, c), (c, a)):
                edge = _edge_key(left, right)
                edge_counts[edge] = edge_counts.get(edge, 0) + 1
                edge_order.setdefault(edge, (left, right))
        top_faces = [tuple(new_vertices[index] for index in face) for face in selected_faces]
        side_faces: list[tuple[int, int, int]] = []
        for edge, count in edge_counts.items():
            if count != 1:
                continue
            a, b = edge_order[edge]
            na = new_vertices[a]
            nb = new_vertices[b]
            side_faces.extend(((a, b, nb), (a, nb, na)))
        submesh.faces = [face for _face_index, face in _valid_face_items(submesh)]
        submesh.faces.extend((*top_faces, *side_faces))
        recompute_submesh_normals(submesh)
    refresh_mesh_totals(mesh)
    return _changed_from_vertices(changed)


def _extrude_edges(
    mesh: ParsedMesh,
    selected_edges: dict[int, set[tuple[int, int]]],
    offset: Vec3,
    recompute_normals: bool,
) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    changed: MeshEditChangedVertices = {}
    for submesh_index, edges in selected_edges.items():
        if not 0 <= submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        valid_edges = [
            (a, b)
            for a, b in sorted({_edge_key(a, b) for a, b in edges})
            if 0 <= a < len(submesh.vertices) and 0 <= b < len(submesh.vertices)
        ]
        if not valid_edges:
            continue
        extruded_vertices: dict[int, int] = {}
        touched = changed.setdefault(submesh_index, set())
        new_faces: list[tuple[int, int, int]] = []
        for a, b in valid_edges:
            if a not in extruded_vertices:
                extruded_vertices[a] = _append_vertex_copy(submesh, a, _add(_vec3(submesh.vertices[a]), offset))
                touched.add(extruded_vertices[a])
            if b not in extruded_vertices:
                extruded_vertices[b] = _append_vertex_copy(submesh, b, _add(_vec3(submesh.vertices[b]), offset))
                touched.add(extruded_vertices[b])
            na = extruded_vertices[a]
            nb = extruded_vertices[b]
            new_faces.extend(((a, b, nb), (a, nb, na)))
        submesh.faces = [face for _face_index, face in _valid_face_items(submesh)]
        submesh.faces.extend(new_faces)
        if recompute_normals:
            recompute_submesh_normals(submesh)
    refresh_mesh_totals(mesh)
    return _changed_from_vertices(changed)


def _inset(
    mesh: ParsedMesh,
    selection: MeshEditSelection,
    params: dict[str, object],
) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    amount = _inset_amount(params.get("amount", 0.25))
    if amount <= 1e-8:
        return set(), {}
    face_selection = selection.face_map()
    edge_selection = selection.edge_map()
    vertex_selection = selection.vertex_map()
    all_faces = set(selection.source_indices)
    if face_selection or edge_selection or vertex_selection or all_faces:
        native_result = apply_native_mesh_inset(
            mesh,
            face_selection,
            vertex_selection,
            {**params, "amount": amount},
            selected_edges_by_submesh=edge_selection,
            all_faces_by_submesh=all_faces,
            recompute_normals=bool(params.get("recompute_normals", True)),
        )
        if native_result is not None:
            return native_result
        _record_native_edit_fallback(
            mesh,
            "topology.inset",
            "native inset unavailable",
            submesh_indices=face_selection or vertex_selection or edge_selection or all_faces,
        )
        if not _allow_python_mesh_edit_fallback(mesh, "topology.inset", submesh_indices=face_selection or vertex_selection or edge_selection or all_faces):
            return set(), {}
    faces = _selected_faces(mesh, selection, fallback_all=False)
    changed: MeshEditChangedVertices = {}
    for submesh_index, face_indices in faces.items():
        submesh = mesh.submeshes[submesh_index]
        valid_faces = dict(_valid_face_items(submesh))
        selected_faces = [valid_faces[face_index] for face_index in sorted(face_indices) if face_index in valid_faces]
        if not selected_faces:
            continue
        selected_vertices = {vertex_index for face in selected_faces for vertex_index in face}
        center = _selection_center(mesh, {submesh_index: selected_vertices})
        inner_vertices: dict[int, int] = {}
        touched = changed.setdefault(submesh_index, set())
        edge_counts: dict[tuple[int, int], int] = {}
        edge_order: dict[tuple[int, int], tuple[int, int]] = {}
        for face in selected_faces:
            for vertex_index in face:
                if vertex_index in inner_vertices:
                    continue
                vertex = _vec3(submesh.vertices[vertex_index])
                inset_vertex = (
                    vertex[0] + (center[0] - vertex[0]) * amount,
                    vertex[1] + (center[1] - vertex[1]) * amount,
                    vertex[2] + (center[2] - vertex[2]) * amount,
                )
                inner_vertices[vertex_index] = _append_vertex_copy(submesh, vertex_index, inset_vertex)
                touched.add(inner_vertices[vertex_index])
            a, b, c = face
            for left, right in ((a, b), (b, c), (c, a)):
                edge = _edge_key(left, right)
                edge_counts[edge] = edge_counts.get(edge, 0) + 1
                edge_order.setdefault(edge, (left, right))
        inner_faces = [tuple(inner_vertices[index] for index in face) for face in selected_faces]
        side_faces: list[tuple[int, int, int]] = []
        for edge, count in edge_counts.items():
            if count != 1:
                continue
            a, b = edge_order[edge]
            ia = inner_vertices[a]
            ib = inner_vertices[b]
            side_faces.extend(((a, b, ib), (a, ib, ia)))
        new_faces = [face for face_index, face in _valid_face_items(submesh) if face_index not in face_indices]
        new_faces.extend((*inner_faces, *side_faces))
        submesh.faces = new_faces
        recompute_submesh_normals(submesh)
    refresh_mesh_totals(mesh)
    return _changed_from_vertices(changed)


def _inset_amount(value: object) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError, OverflowError):
        amount = 0.25
    if not math.isfinite(amount):
        amount = 0.25
    return max(0.0, min(0.95, amount))


def _loop_cut(
    mesh: ParsedMesh,
    selection: MeshEditSelection,
    params: dict[str, object],
) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    selected_edges = selection.edge_map()
    native_result = apply_native_mesh_loop_cut(
        mesh,
        selected_edges,
        params,
        recompute_normals=bool(params.get("recompute_normals", True)),
        **_native_kwargs(params),
    )
    if native_result is not None:
        return native_result
    _record_native_edit_fallback(
        mesh,
        "topology.loop_cut",
        "native loop cut unavailable",
        submesh_indices=selected_edges,
    )
    if selected_edges and not _allow_python_mesh_edit_fallback(
        mesh,
        "topology.loop_cut",
        submesh_indices=selected_edges,
    ):
        return set(), {}
    cut_count = _loop_cut_count(params)
    cut_fractions = _loop_cut_fractions(params, cut_count)
    changed: MeshEditChangedVertices = {}
    for submesh_index, edges in selected_edges.items():
        if not 0 <= submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        valid_edges = {
            _edge_key(a, b)
            for a, b in edges
            if 0 <= a < len(submesh.vertices) and 0 <= b < len(submesh.vertices)
        }
        if not valid_edges:
            continue

        edge_cut_vertices: dict[tuple[int, int], tuple[int, ...]] = {}
        edge_midpoints: dict[tuple[int, int], int] = {}
        new_faces: list[tuple[int, int, int]] = []
        touched = changed.setdefault(submesh_index, set())

        def cut_vertices(a: int, b: int) -> tuple[int, ...]:
            key = _edge_key(a, b)
            if key not in edge_cut_vertices:
                left, right = key
                edge_cut_vertices[key] = tuple(
                    _append_interpolated_vertex(submesh, left, right, fraction)
                    for fraction in cut_fractions
                )
                touched.update(edge_cut_vertices[key])
            return edge_cut_vertices[key] if key == (a, b) else tuple(reversed(edge_cut_vertices[key]))

        def cut_point(a: int, b: int) -> int:
            key = _edge_key(a, b)
            if key not in edge_midpoints:
                left, right = key
                edge_midpoints[key] = _append_interpolated_vertex(submesh, left, right, cut_fractions[0])
                touched.add(edge_midpoints[key])
            return edge_midpoints[key]

        for _face_index, (a, b, c) in _valid_face_items(submesh):
            matched = {
                edge
                for edge in (_edge_key(a, b), _edge_key(b, c), _edge_key(c, a))
                if edge in valid_edges
            }
            if not matched:
                new_faces.append((a, b, c))
            elif len(matched) == 1:
                edge = next(iter(matched))
                if edge == _edge_key(a, b):
                    new_faces.extend(_edge_cut_faces((a, *cut_vertices(a, b), b), c))
                elif edge == _edge_key(b, c):
                    new_faces.extend(_edge_cut_faces((b, *cut_vertices(b, c), c), a))
                else:
                    new_faces.extend(_edge_cut_faces((c, *cut_vertices(c, a), a), b))
            elif len(matched) == 2:
                has_ab = _edge_key(a, b) in matched
                has_bc = _edge_key(b, c) in matched
                has_ca = _edge_key(c, a) in matched
                if has_ab and has_bc:
                    ab = cut_point(a, b)
                    bc = cut_point(b, c)
                    new_faces.extend(((ab, b, bc), (a, ab, bc), (a, bc, c)))
                elif has_bc and has_ca:
                    bc = cut_point(b, c)
                    ca = cut_point(c, a)
                    new_faces.extend(((bc, c, ca), (a, b, bc), (a, bc, ca)))
                else:
                    ca = cut_point(c, a)
                    ab = cut_point(a, b)
                    new_faces.extend(((ca, a, ab), (ab, b, c), (ab, c, ca)))
            else:
                ab = cut_point(a, b)
                bc = cut_point(b, c)
                ca = cut_point(c, a)
                new_faces.extend(((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)))
        if touched:
            submesh.faces = new_faces
            if bool(params.get("recompute_normals", True)):
                recompute_submesh_normals(submesh)
        else:
            changed.pop(submesh_index, None)
    refresh_mesh_totals(mesh)
    return _changed_from_vertices(changed)


def _loop_cut_count(params: dict[str, object]) -> int:
    try:
        value = int(params.get("cuts", params.get("count", params.get("segments", 1))) or 1)
    except (TypeError, ValueError, OverflowError):
        return 1
    return max(1, min(16, value))


def _loop_cut_fractions(params: dict[str, object], cut_count: int) -> tuple[float, ...]:
    if cut_count == 1 and ("factor" in params or "position" in params):
        return (_loop_cut_factor(params.get("factor", params.get("position"))),)
    return tuple(cut_index / float(cut_count + 1) for cut_index in range(1, cut_count + 1))


def _loop_cut_factor(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.5
    if not math.isfinite(parsed):
        return 0.5
    return max(1e-6, min(1.0 - 1e-6, parsed))


def _edge_cut_faces(edge_vertices: tuple[int, ...], opposite_vertex: int) -> list[tuple[int, int, int]]:
    return [
        (edge_vertices[index], edge_vertices[index + 1], opposite_vertex)
        for index in range(max(0, len(edge_vertices) - 1))
    ]


def _edge_split(mesh: ParsedMesh, selection: MeshEditSelection) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    selected_edges = selection.edge_map()
    selected_faces = selection.face_map()
    selected_vertices = selection.vertex_map()
    native_result = apply_native_mesh_edge_split(
        mesh,
        selected_faces,
        selected_vertices,
        selected_edges_by_submesh=selected_edges,
        recompute_normals=True,
    )
    if native_result is not None:
        return native_result
    _record_native_edit_fallback(
        mesh,
        "topology.edge_split",
        "native edge split unavailable",
        submesh_indices=selected_edges or selected_faces or selected_vertices,
    )
    if (selected_edges or selected_faces or selected_vertices) and not _allow_python_mesh_edit_fallback(
        mesh,
        "topology.edge_split",
        submesh_indices=selected_edges or selected_faces or selected_vertices,
    ):
        return set(), {}
    changed: MeshEditChangedVertices = {}
    if selected_edges:
        for submesh_index, edges in selected_edges.items():
            if not 0 <= submesh_index < len(mesh.submeshes):
                continue
            submesh = mesh.submeshes[submesh_index]
            valid_edges = {
                _edge_key(a, b)
                for a, b in edges
                if 0 <= a < len(submesh.vertices) and 0 <= b < len(submesh.vertices)
            }
            if not valid_edges:
                continue
            seen_edges: set[tuple[int, int]] = set()
            new_faces: list[tuple[int, int, int]] = []
            touched = changed.setdefault(submesh_index, set())
            for _face_index, (a, b, c) in _valid_face_items(submesh):
                replacements: dict[int, int] = {}
                for edge in (_edge_key(a, b), _edge_key(b, c), _edge_key(c, a)):
                    if edge not in valid_edges:
                        continue
                    if edge in seen_edges:
                        for vertex_index in edge:
                            if vertex_index not in replacements:
                                replacements[vertex_index] = _append_vertex_copy(
                                    submesh,
                                    vertex_index,
                                    _vec3(submesh.vertices[vertex_index]),
                                )
                    else:
                        seen_edges.add(edge)
                if replacements:
                    touched.update(replacements.values())
                    new_faces.append(tuple(replacements.get(index, index) for index in (a, b, c)))
                else:
                    new_faces.append((a, b, c))
            if touched:
                submesh.faces = new_faces
                recompute_submesh_normals(submesh)
            else:
                changed.pop(submesh_index, None)
        refresh_mesh_totals(mesh)
        return _changed_from_vertices(changed)

    faces = _selected_faces(mesh, selection, fallback_all=False)
    for submesh_index, face_indices in faces.items():
        submesh = mesh.submeshes[submesh_index]
        touched = changed.setdefault(submesh_index, set())
        new_faces = list(submesh.faces)
        for face_index in sorted(face_indices):
            face_vertices = _valid_face_vertices(submesh.faces[face_index], len(submesh.vertices))
            if len(face_vertices) != 3:
                continue
            a, b, c = face_vertices
            copied = [_append_vertex_copy(submesh, index, _vec3(submesh.vertices[index])) for index in (a, b, c)]
            new_faces[face_index] = tuple(copied)  # type: ignore[assignment]
            touched.update(copied)
        if touched:
            submesh.faces = new_faces
            recompute_submesh_normals(submesh)
        else:
            changed.pop(submesh_index, None)
    refresh_mesh_totals(mesh)
    return _changed_from_vertices(changed)


def _edge_key(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a <= b else (b, a)


def _merge(mesh: ParsedMesh, selection: MeshEditSelection) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    selected_vertices = selection.vertex_map()
    selected_edges = selection.edge_map()
    selected_faces = selection.face_map()
    all_faces = set(selection.source_indices)
    native_result = apply_native_mesh_merge(
        mesh,
        selected_faces,
        selected_vertices,
        selected_edges_by_submesh=selected_edges,
        all_faces_by_submesh=all_faces,
        recompute_normals=True,
    )
    if native_result is not None:
        return native_result
    _record_native_edit_fallback(
        mesh,
        "topology.merge",
        "native merge unavailable",
        submesh_indices=selected_vertices or selected_edges or selected_faces or all_faces,
    )
    if (selected_vertices or selected_edges or selected_faces or all_faces) and not _allow_python_mesh_edit_fallback(
        mesh,
        "topology.merge",
        submesh_indices=selected_vertices or selected_edges or selected_faces or all_faces,
    ):
        return set(), {}
    selected = _selected_vertices(mesh, selection, fallback_all=False)
    changed: MeshEditChangedVertices = {}
    for submesh_index, vertex_indices in selected.items():
        if len(vertex_indices) < 2:
            continue
        submesh = mesh.submeshes[submesh_index]
        center = _selection_center(mesh, {submesh_index: vertex_indices})
        keeper = min(vertex_indices)
        vertices = list(submesh.vertices)
        vertices[keeper] = center
        index_map = {index: keeper for index in vertex_indices}
        seen_faces: set[tuple[int, int, int]] = set()
        remapped_faces: list[tuple[int, int, int]] = []
        for _face_index, face in _valid_face_items(submesh):
            remapped = tuple(index_map.get(index, index) for index in face)
            if len(set(remapped)) != 3 or remapped in seen_faces:
                continue
            seen_faces.add(remapped)
            remapped_faces.append(remapped)
        submesh.vertices = vertices
        submesh.faces = remapped_faces
        changed[submesh_index] = set(vertex_indices)
    if changed:
        compact_orphan_vertices(mesh, submesh_indices=changed, recompute_normals=True)
    refresh_mesh_totals(mesh)
    return set(changed), {}


def _weld(
    mesh: ParsedMesh,
    selection: MeshEditSelection,
    params: dict[str, object],
) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    threshold = _positive_float(params.get("threshold", params.get("distance", params.get("merge_distance", 1e-5)))) or 1e-5
    selected_vertices = selection.vertex_map()
    selected_edges = selection.edge_map()
    selected_faces = selection.face_map()
    all_faces = set(selection.source_indices)
    native_result = apply_native_mesh_weld(
        mesh,
        selected_faces,
        selected_vertices,
        threshold=threshold,
        selected_edges_by_submesh=selected_edges,
        all_faces_by_submesh=all_faces,
        recompute_normals=True,
    )
    if native_result is not None:
        return native_result
    _record_native_edit_fallback(
        mesh,
        "topology.weld",
        "native weld unavailable",
        submesh_indices=selected_vertices or selected_edges or selected_faces or all_faces,
    )
    if (selected_vertices or selected_edges or selected_faces or all_faces) and not _allow_python_mesh_edit_fallback(
        mesh,
        "topology.weld",
        submesh_indices=selected_vertices or selected_edges or selected_faces or all_faces,
    ):
        return set(), {}
    selected = _selected_vertices(mesh, selection, fallback_all=False)
    threshold_squared = threshold * threshold
    changed: MeshEditChangedVertices = {}
    for submesh_index, vertex_indices in selected.items():
        if len(vertex_indices) < 2:
            continue
        submesh = mesh.submeshes[submesh_index]
        vertices = list(submesh.vertices)
        remap: dict[int, int] = {}
        touched: set[int] = set()
        sorted_indices = sorted(vertex_indices)
        for position, keeper in enumerate(sorted_indices):
            if keeper in remap:
                continue
            keeper_vertex = _vec3(vertices[keeper])
            cluster = [keeper]
            for candidate in sorted_indices[position + 1 :]:
                if candidate in remap:
                    continue
                candidate_vertex = _vec3(vertices[candidate])
                distance_squared = sum((keeper_vertex[axis] - candidate_vertex[axis]) ** 2 for axis in range(3))
                if distance_squared <= threshold_squared:
                    cluster.append(candidate)
            if len(cluster) < 2:
                continue
            center = _selection_center(mesh, {submesh_index: set(cluster)})
            vertices[keeper] = center
            for duplicate in cluster[1:]:
                remap[duplicate] = keeper
            touched.update(cluster)
        if not remap:
            continue
        seen_faces: set[tuple[int, int, int]] = set()
        remapped_faces: list[tuple[int, int, int]] = []
        for _face_index, face in _valid_face_items(submesh):
            remapped = tuple(remap.get(index, index) for index in face)
            if len(set(remapped)) != 3 or remapped in seen_faces:
                continue
            seen_faces.add(remapped)
            remapped_faces.append(remapped)
        submesh.vertices = vertices
        submesh.faces = remapped_faces
        changed[submesh_index] = touched
    if changed:
        compact_orphan_vertices(mesh, submesh_indices=changed, recompute_normals=True)
    refresh_mesh_totals(mesh)
    return set(changed), {}


def _fill(mesh: ParsedMesh, selection: MeshEditSelection) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    selected = selection.vertex_map()
    selected_edges = selection.edge_map()
    native_affected = apply_native_mesh_fill(
        mesh,
        selected,
        selected_edges_by_submesh=selected_edges,
        recompute_normals=True,
    )
    if native_affected is not None:
        refresh_mesh_totals(mesh)
        return native_affected, {}
    _record_native_edit_fallback(mesh, "topology.fill", "native fill unavailable", submesh_indices=selected or selected_edges)
    if (selected or selected_edges) and not _allow_python_mesh_edit_fallback(
        mesh,
        "topology.fill",
        submesh_indices=selected or selected_edges,
    ):
        return set(), {}
    edge_loops: dict[int, list[int]] = {}
    for submesh_index, edges in selected_edges.items():
        vertices = selected.setdefault(submesh_index, set())
        for a, b in edges:
            vertices.update((a, b))
        loop = _closed_edge_loop_order(edges)
        if loop:
            edge_loops[submesh_index] = loop
    affected: set[int] = set()
    for submesh_index, vertex_indices in selected.items():
        if not 0 <= submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        valid_vertices = {index for index in vertex_indices if 0 <= index < len(submesh.vertices)}
        ordered_loop = edge_loops.get(submesh_index, ())
        if ordered_loop and set(ordered_loop) == valid_vertices and all(0 <= index < len(submesh.vertices) for index in ordered_loop):
            indices = list(ordered_loop)
        else:
            indices = sorted(valid_vertices)
        if len(indices) not in {3, 4}:
            continue
        existing_faces = {frozenset(face) for _face_index, face in _valid_face_items(submesh)}
        selected_vertices = frozenset(indices)
        faces_to_add: list[tuple[int, int, int]]
        if len(indices) == 3:
            if selected_vertices in existing_faces:
                continue
            faces_to_add = [(indices[0], indices[1], indices[2])]
        else:
            existing_inside = [face for face in existing_faces if face.issubset(selected_vertices)]
            if len(existing_inside) >= 2 and set().union(*existing_inside) == set(selected_vertices):
                continue
            proposed = [(indices[0], indices[1], indices[2]), (indices[0], indices[2], indices[3])]
            faces_to_add = [face for face in proposed if frozenset(face) not in existing_faces]
            if not faces_to_add:
                continue
        submesh.faces = [face for _face_index, face in _valid_face_items(submesh)]
        submesh.faces.extend(faces_to_add)
        recompute_submesh_normals(submesh)
        affected.add(submesh_index)
    refresh_mesh_totals(mesh)
    return affected, {}


def _remove_doubles(
    mesh: ParsedMesh,
    selection: MeshEditSelection,
    params: dict[str, object],
) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    selected: dict[int, set[int] | None] = {}
    for submesh_index in selection.source_indices:
        if 0 <= submesh_index < len(mesh.submeshes) and len(mesh.submeshes[submesh_index].vertices) >= 2:
            selected[submesh_index] = None
    if selection.vertices_by_submesh or selection.edges_by_submesh or selection.faces_by_submesh:
        explicit_selection = MeshEditSelection.from_maps(
            vertices_by_submesh=selection.vertex_map(),
            edges_by_submesh=selection.edge_map(),
            faces_by_submesh=selection.face_map(),
        )
        for submesh_index, vertices in _selected_vertices(mesh, explicit_selection, fallback_all=False).items():
            selected.setdefault(submesh_index, vertices)
    if not selected:
        selected = {index: None for index, submesh in enumerate(mesh.submeshes) if len(submesh.vertices) >= 2}
    threshold = _positive_float(params.get("threshold", params.get("distance", params.get("merge_distance", 1e-5)))) or 1e-5
    native_affected = apply_native_mesh_remove_doubles(mesh, selected, threshold=threshold)
    if native_affected is not None:
        refresh_mesh_totals(mesh)
        return native_affected, {}
    _record_native_edit_fallback(mesh, "topology.remove_doubles", "native remove doubles unavailable", submesh_indices=selected)
    if not _allow_python_mesh_edit_fallback(mesh, "topology.remove_doubles", submesh_indices=selected):
        return set(), {}
    fallback_selected = {
        submesh_index: (
            set(range(len(mesh.submeshes[submesh_index].vertices)))
            if vertices is None
            else set(vertices)
        )
        for submesh_index, vertices in selected.items()
        if 0 <= submesh_index < len(mesh.submeshes)
    }
    return _weld(mesh, MeshEditSelection.from_maps(vertices_by_submesh=fallback_selected), params)


def _delete_loose_vertices(mesh: ParsedMesh, selection: MeshEditSelection) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    target_indices = _submesh_indices(mesh, selection)
    native_result = apply_native_mesh_compact_orphans(mesh, submesh_indices=target_indices, recompute_normals=True)
    if native_result is not None:
        refresh_mesh_totals(mesh)
        return set(native_result.affected_submesh_indices), {}
    _record_native_edit_fallback(mesh, "topology.compact_orphans", "native compact orphans unavailable", submesh_indices=target_indices)
    if not _allow_python_mesh_edit_fallback(mesh, "topology.compact_orphans", submesh_indices=target_indices):
        return set(), {}
    result = compact_orphan_vertices(mesh, submesh_indices=target_indices, recompute_normals=True)
    refresh_mesh_totals(mesh)
    return set(result.affected_submesh_indices), {}


def _fix_winding(mesh: ParsedMesh, selection: MeshEditSelection) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    target_indices = _submesh_indices(mesh, selection)
    native_affected = apply_native_mesh_fix_winding(mesh, target_indices, recompute_normals=True)
    if native_affected is not None:
        refresh_mesh_totals(mesh)
        return set(native_affected), {}
    _record_native_edit_fallback(mesh, "topology.fix_winding", "native fix winding unavailable", submesh_indices=target_indices)
    if not _allow_python_mesh_edit_fallback(mesh, "topology.fix_winding", submesh_indices=target_indices):
        return set(), {}
    affected: set[int] = set()
    for submesh_index in target_indices:
        submesh = mesh.submeshes[submesh_index]
        vertices = submesh.vertices or ()
        normals = submesh.normals or ()
        new_faces: list[tuple[int, int, int]] = []
        for _face_index, (a, b, c) in _valid_face_items(submesh):
            face = (a, b, c)
            if len(normals) == len(vertices):
                face_normal = _face_normal(vertices, face)
                average_normal = _average_vertex_normal(normals, face)
                if _dot(face_normal, average_normal) < -1e-8:
                    face = (a, c, b)
            new_faces.append(face)
        if new_faces != list(submesh.faces or ()):
            submesh.faces = new_faces
            recompute_submesh_normals(submesh)
            affected.add(submesh_index)
    if affected:
        refresh_mesh_totals(mesh)
    return affected, {}


def _fill_holes(mesh: ParsedMesh, selection: MeshEditSelection) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    target_indices = _submesh_indices(mesh, selection)
    native_affected = apply_native_mesh_fill_holes(mesh, target_indices, recompute_normals=True)
    if native_affected is not None:
        refresh_mesh_totals(mesh)
        return set(native_affected), {}
    _record_native_edit_fallback(mesh, "topology.fill_holes", "native fill holes unavailable", submesh_indices=target_indices)
    if not _allow_python_mesh_edit_fallback(mesh, "topology.fill_holes", submesh_indices=target_indices):
        return set(), {}
    affected: set[int] = set()
    for submesh_index in target_indices:
        submesh = mesh.submeshes[submesh_index]
        boundary_edges = _boundary_edges(submesh)
        if not boundary_edges:
            continue
        existing_faces = {frozenset(face) for _face_index, face in _valid_face_items(submesh)}
        faces_to_add: list[tuple[int, int, int]] = []
        for component in _edge_components(boundary_edges):
            ordered = _closed_edge_loop_order(component)
            if len(ordered) == 3:
                face = (ordered[0], ordered[1], ordered[2])
                if frozenset(face) not in existing_faces:
                    faces_to_add.append(face)
                    existing_faces.add(frozenset(face))
            elif len(ordered) == 4:
                for face in ((ordered[0], ordered[1], ordered[2]), (ordered[0], ordered[2], ordered[3])):
                    if frozenset(face) not in existing_faces:
                        faces_to_add.append(face)
                        existing_faces.add(frozenset(face))
        if faces_to_add:
            submesh.faces = [face for _face_index, face in _valid_face_items(submesh)]
            submesh.faces.extend(faces_to_add)
            recompute_submesh_normals(submesh)
            affected.add(submesh_index)
    if affected:
        refresh_mesh_totals(mesh)
    return affected, {}


def _triangulate_display(mesh: ParsedMesh, selection: MeshEditSelection) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    target_indices = _submesh_indices(mesh, selection)
    native_affected = apply_native_mesh_triangulate_display(mesh, target_indices, recompute_normals=True)
    if native_affected is not None:
        refresh_mesh_totals(mesh)
        return set(native_affected), {}
    _record_native_edit_fallback(
        mesh,
        "topology.triangulate_display",
        "native display triangulate unavailable",
        submesh_indices=target_indices,
    )
    if not _allow_python_mesh_edit_fallback(mesh, "topology.triangulate_display", submesh_indices=target_indices):
        return set(), {}
    affected: set[int] = set()
    for submesh_index in target_indices:
        submesh = mesh.submeshes[submesh_index]
        vertex_count = len(submesh.vertices or ())
        new_faces: list[tuple[int, int, int]] = []
        for face in submesh.faces or ():
            if not isinstance(face, (tuple, list)):
                continue
            indices = [_coerce_index(value) for value in tuple(face or ())]
            if len(indices) < 3 or any(index is None or index < 0 or index >= vertex_count for index in indices):
                continue
            clean = [int(index) for index in indices if index is not None]
            if len(clean) == 3:
                if len(set(clean)) == 3:
                    new_faces.append((clean[0], clean[1], clean[2]))
                continue
            for offset in range(1, len(clean) - 1):
                triangle = (clean[0], clean[offset], clean[offset + 1])
                if len(set(triangle)) == 3:
                    new_faces.append(triangle)
        if new_faces != list(submesh.faces or ()):
            submesh.faces = new_faces
            recompute_submesh_normals(submesh)
            affected.add(submesh_index)
    if affected:
        refresh_mesh_totals(mesh)
    return affected, {}


def _closed_edge_loop_order(edges: set[tuple[int, int]]) -> list[int]:
    edge_keys = {_edge_key(a, b) for a, b in edges if a != b}
    if len(edge_keys) not in {3, 4}:
        return []
    adjacency: dict[int, set[int]] = {}
    for a, b in edge_keys:
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)
    if len(adjacency) != len(edge_keys) or any(len(neighbors) != 2 for neighbors in adjacency.values()):
        return []
    start = min(adjacency)
    previous = start
    current = min(adjacency[start])
    order = [start]
    while current != start:
        if current in order:
            return []
        order.append(current)
        next_vertices = [index for index in sorted(adjacency[current]) if index != previous]
        if not next_vertices:
            return []
        previous, current = current, next_vertices[0]
    return order if len(order) == len(adjacency) else []


def _boundary_edges(submesh: SubMesh) -> set[tuple[int, int]]:
    counts: dict[tuple[int, int], int] = {}
    for _face_index, (a, b, c) in _valid_face_items(submesh):
        for edge in (_edge_key(a, b), _edge_key(b, c), _edge_key(c, a)):
            counts[edge] = counts.get(edge, 0) + 1
    return {edge for edge, count in counts.items() if count == 1}


def _edge_components(edges: set[tuple[int, int]]) -> list[set[tuple[int, int]]]:
    pending = set(edges)
    components: list[set[tuple[int, int]]] = []
    while pending:
        seed = pending.pop()
        component = {seed}
        vertices = set(seed)
        changed = True
        while changed:
            changed = False
            for edge in tuple(pending):
                if edge[0] in vertices or edge[1] in vertices:
                    pending.remove(edge)
                    component.add(edge)
                    vertices.update(edge)
                    changed = True
        components.append(component)
    return components


def _face_normal(vertices: Sequence[object], face: tuple[int, int, int]) -> Vec3:
    a, b, c = (_vec3(vertices[index]) for index in face)
    return _normalized_vec3(_cross(_sub(b, a), _sub(c, a)))


def _average_vertex_normal(normals: Sequence[object], face: tuple[int, int, int]) -> Vec3:
    values = [_vec3(normals[index], (0.0, 0.0, 1.0)) for index in face]
    return _normalized_vec3(
        (
            sum(value[0] for value in values),
            sum(value[1] for value in values),
            sum(value[2] for value in values),
        )
    )


def _cross(left: Vec3, right: Vec3) -> Vec3:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _bridge(mesh: ParsedMesh, selection: MeshEditSelection) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    selected_edges = selection.edge_map()
    if selected_edges:
        native_affected = apply_native_mesh_bridge(mesh, selected_edges, recompute_normals=True)
        if native_affected is not None:
            refresh_mesh_totals(mesh)
            return set(native_affected), {}
        _record_native_edit_fallback(mesh, "topology.bridge", "native bridge unavailable", submesh_indices=selected_edges)
        if not _allow_python_mesh_edit_fallback(mesh, "topology.bridge", submesh_indices=selected_edges):
            return set(), {}
    affected: set[int] = set()
    bridge_candidate_seen = False
    for submesh_index, edges in selected_edges.items():
        if not 0 <= submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        existing_faces: set[frozenset[int]] = set()
        edge_use_count: dict[tuple[int, int], int] = {}
        for _face_index, (a, b, c) in _valid_face_items(submesh):
            existing_faces.add(frozenset((a, b, c)))
            for edge in (_edge_key(a, b), _edge_key(b, c), _edge_key(c, a)):
                edge_use_count[edge] = edge_use_count.get(edge, 0) + 1
        valid_edges = [
            (a, b)
            for a, b in sorted(edges)
            if 0 <= a < len(submesh.vertices) and 0 <= b < len(submesh.vertices)
        ]
        if len(valid_edges) != 2:
            continue
        bridge_candidate_seen = True
        (a, b), (c, d) = valid_edges
        if len({a, b, c, d}) != 4:
            continue
        if any(edge_use_count.get(_edge_key(*edge), 0) > 1 for edge in valid_edges):
            continue
        selected_vertices = frozenset((a, b, c, d))
        if any(face_vertices.issubset(selected_vertices) for face_vertices in existing_faces):
            continue
        new_faces = ((a, b, d), (a, d, c))
        if any(frozenset(face) in existing_faces for face in new_faces):
            continue
        submesh.faces = [face for _face_index, face in _valid_face_items(submesh)]
        submesh.faces.extend(new_faces)
        recompute_submesh_normals(submesh)
        affected.add(submesh_index)
    if affected:
        refresh_mesh_totals(mesh)
        return affected, {}
    if bridge_candidate_seen:
        return set(), {}
    return _fill(mesh, selection)


def _surface_channel_target_indices(mesh: ParsedMesh, selection: MeshEditSelection) -> set[int]:
    if selection.is_empty():
        return set()
    target_indices: set[int] = {
        index for index in selection.source_indices if 0 <= index < len(mesh.submeshes)
    }
    for submesh_index, vertices in selection.vertex_map().items():
        if not 0 <= submesh_index < len(mesh.submeshes):
            continue
        if any(0 <= index < len(mesh.submeshes[submesh_index].vertices) for index in vertices):
            target_indices.add(submesh_index)
    for submesh_index, faces in selection.face_map().items():
        if not 0 <= submesh_index < len(mesh.submeshes):
            continue
        if any(0 <= index < len(mesh.submeshes[submesh_index].faces) for index in faces):
            target_indices.add(submesh_index)
    for submesh_index, edges in selection.edge_map().items():
        if not 0 <= submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        selected_edges = {
            _edge_key(a, b)
            for a, b in edges
            if 0 <= a < len(submesh.vertices) and 0 <= b < len(submesh.vertices)
        }
        if not selected_edges:
            continue
        for _face_index, (a, b, c) in _valid_face_items(submesh):
            if {_edge_key(a, b), _edge_key(b, c), _edge_key(c, a)} & selected_edges:
                target_indices.add(submesh_index)
                break
    return target_indices


def _recalculate_normals(mesh: ParsedMesh, selection: MeshEditSelection) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    target_indices = _surface_channel_target_indices(mesh, selection)
    if not target_indices:
        return set(), {}
    native_changed = apply_native_mesh_recalculate_normals(mesh, target_indices, return_changed_vertices=True)
    if native_changed is not None:
        return _changed_from_vertices(native_changed)
    if not _allow_python_mesh_edit_fallback(mesh, "normals.recalculate", submesh_indices=target_indices):
        return set(), {}
    _record_native_edit_fallback(mesh, "normals.recalculate", "native normal recompute unavailable", submesh_indices=target_indices)
    affected: set[int] = set()
    for submesh_index in sorted(target_indices):
        submesh = mesh.submeshes[submesh_index]
        before = tuple(_vec3(normal) for normal in submesh.normals or ())
        recompute_submesh_normals(submesh)
        after = tuple(_vec3(normal) for normal in submesh.normals or ())
        if not _same_vec3_tuple(before, after):
            affected.add(submesh_index)
    return affected, {}


def _weighted_normals(mesh: ParsedMesh, selection: MeshEditSelection) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    target_indices = _surface_channel_target_indices(mesh, selection)
    if not target_indices:
        return set(), {}
    native_changed = apply_native_mesh_weighted_normals(mesh, target_indices)
    if native_changed is not None:
        return _changed_from_vertices(native_changed)
    _record_native_edit_fallback(mesh, "normals.weighted", "native weighted normals unavailable", submesh_indices=target_indices)
    if not _allow_python_mesh_edit_fallback(mesh, "normals.weighted", submesh_indices=target_indices):
        return set(), {}
    changed: MeshEditChangedVertices = {}
    for submesh_index in sorted(target_indices):
        submesh = mesh.submeshes[submesh_index]
        before = tuple(_vec3(normal, (0.0, 0.0, 0.0)) for normal in tuple(submesh.normals or ()))
        normals = _computed_weighted_normals(submesh)
        if not normals:
            continue
        touched = {
            index
            for index, normal in enumerate(normals)
            if index >= len(before) or not _same_vec3(before[index], normal)
        }
        if touched:
            submesh.normals = normals
            changed[submesh_index] = touched
    return _changed_from_vertices(changed)


def _computed_weighted_normals(submesh: SubMesh) -> list[Vec3]:
    vertices = tuple(_vec3(vertex) for vertex in tuple(submesh.vertices or ()))
    if not vertices:
        return []
    accum: list[Vec3] = [(0.0, 0.0, 0.0) for _vertex in vertices]
    for _face_index, (a, b, c) in _valid_face_items(submesh):
        weighted = _cross(_sub(vertices[b], vertices[a]), _sub(vertices[c], vertices[a]))
        if _dot(weighted, weighted) <= 1e-24:
            continue
        accum[a] = _add(accum[a], weighted)
        accum[b] = _add(accum[b], weighted)
        accum[c] = _add(accum[c], weighted)
    fallback_normals = tuple(_vec3(normal, (0.0, 1.0, 0.0)) for normal in tuple(submesh.normals or ()))
    result: list[Vec3] = []
    for index, value in enumerate(accum):
        normal = _normalized_vec3(value)
        if normal == (0.0, 0.0, 0.0) and index < len(fallback_normals):
            normal = _normalized_vec3(fallback_normals[index])
        result.append(normal if normal != (0.0, 0.0, 0.0) else (0.0, 1.0, 0.0))
    return result


def _generate_tangents(mesh: ParsedMesh, selection: MeshEditSelection) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    target_indices = _surface_channel_target_indices(mesh, selection)
    if not target_indices:
        return set(), {}
    native_affected = apply_native_mesh_generate_tangents(mesh, target_indices)
    if native_affected is not None:
        return native_affected, {}
    if not _allow_python_mesh_edit_fallback(mesh, "tangents.generate", submesh_indices=target_indices):
        return set(), {}
    _record_native_edit_fallback(mesh, "tangents.generate", "native tangent generation unavailable", submesh_indices=target_indices)
    affected: set[int] = set()
    for submesh_index in sorted(target_indices):
        submesh = mesh.submeshes[submesh_index]
        before = tuple(_vec3(tangent) for tangent in tuple(getattr(submesh, "tangents", ()) or ()))
        tangents = _computed_vertex_tangents(submesh)
        if not tangents:
            continue
        setattr(submesh, "tangents", tangents)
        after = tuple(_vec3(tangent) for tangent in tangents)
        if not _same_vec3_tuple(before, after):
            affected.add(submesh_index)
    return affected, {}


def _computed_vertex_tangents(submesh: SubMesh) -> list[Vec3]:
    vertices = tuple(_vec3(vertex) for vertex in tuple(submesh.vertices or ()))
    uvs = tuple(_vec2(uv) for uv in tuple(submesh.uvs or ()))
    if not vertices or len(uvs) != len(vertices):
        return []
    accum: list[Vec3] = [(0.0, 0.0, 0.0) for _vertex in vertices]
    for _face_index, (a, b, c) in _valid_face_items(submesh):
        p0, p1, p2 = vertices[a], vertices[b], vertices[c]
        uv0, uv1, uv2 = uvs[a], uvs[b], uvs[c]
        edge1 = _sub(p1, p0)
        edge2 = _sub(p2, p0)
        du1 = uv1[0] - uv0[0]
        dv1 = uv1[1] - uv0[1]
        du2 = uv2[0] - uv0[0]
        dv2 = uv2[1] - uv0[1]
        denom = du1 * dv2 - du2 * dv1
        if abs(denom) <= 1e-12:
            continue
        tangent = _scale(_sub(_scale(edge1, dv2), _scale(edge2, dv1)), 1.0 / denom)
        accum[a] = _add(accum[a], tangent)
        accum[b] = _add(accum[b], tangent)
        accum[c] = _add(accum[c], tangent)
    normals = tuple(_vec3(normal) for normal in tuple(submesh.normals or ()))
    result: list[Vec3] = []
    for index, tangent in enumerate(accum):
        normal = normals[index] if len(normals) == len(vertices) else (0.0, 0.0, 1.0)
        tangent = _sub(tangent, _scale(normal, _dot(normal, tangent)))
        normalized = _normalized_vec3(tangent)
        result.append(normalized if normalized != (0.0, 0.0, 0.0) else (1.0, 0.0, 0.0))
    return result


def _flip_normals(mesh: ParsedMesh, selection: MeshEditSelection) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    if selection.is_empty():
        return set(), {}
    has_explicit_selection = bool(selection.vertices_by_submesh or selection.edges_by_submesh or selection.faces_by_submesh)
    if selection.source_indices and not has_explicit_selection:
        target_indices = set(_submesh_indices(mesh, selection))
        if not target_indices:
            return set(), {}
        native_affected = apply_native_mesh_flip_normals(mesh, target_indices)
        if native_affected is not None:
            return native_affected, {}
        _record_native_edit_fallback(mesh, "normals.flip", "native submesh flip normals unavailable", submesh_indices=target_indices)
        if not _allow_python_mesh_edit_fallback(mesh, "normals.flip", submesh_indices=target_indices):
            return set(), {}
        affected: set[int] = set()
        for submesh_index in sorted(target_indices):
            submesh = mesh.submeshes[submesh_index]
            valid_faces = [face for _face_index, face in _valid_face_items(submesh)]
            if not valid_faces:
                continue
            submesh.faces = [(face[0], face[2], face[1]) for face in valid_faces]
            if len(submesh.normals) == len(submesh.vertices):
                submesh.normals = [(-normal[0], -normal[1], -normal[2]) for normal in submesh.normals]
            else:
                recompute_submesh_normals(submesh)
            affected.add(submesh_index)
        return affected, {}
    selected_faces = _selected_faces(mesh, selection, fallback_all=False)
    if selected_faces:
        native_affected = apply_native_mesh_flip_normals(
            mesh,
            set(selected_faces),
            selected_faces_by_submesh=selected_faces,
        )
        if native_affected is not None:
            return native_affected, {}
        _record_native_edit_fallback(mesh, "normals.flip", "native selected-face flip normals unavailable", submesh_indices=selected_faces)
        if not _allow_python_mesh_edit_fallback(mesh, "normals.flip", submesh_indices=selected_faces):
            return set(), {}
        affected: set[int] = set()
        for submesh_index, face_indices in selected_faces.items():
            submesh = mesh.submeshes[submesh_index]
            faces = list(submesh.faces)
            changed = False
            for face_index in sorted(face_indices):
                if not 0 <= face_index < len(faces):
                    continue
                face = _valid_face_vertices(faces[face_index], len(submesh.vertices))
                if len(face) != 3:
                    continue
                faces[face_index] = (face[0], face[2], face[1])
                changed = True
            if changed:
                submesh.faces = faces
                recompute_submesh_normals(submesh)
                affected.add(submesh_index)
        return affected, {}

    if selection.vertices_by_submesh or selection.edges_by_submesh or selection.faces_by_submesh:
        return set(), {}

    target_indices = set(_submesh_indices(mesh, selection))
    native_affected = apply_native_mesh_flip_normals(mesh, target_indices)
    if native_affected is not None:
        return native_affected, {}
    _record_native_edit_fallback(mesh, "normals.flip", "native submesh flip normals unavailable", submesh_indices=target_indices)
    if not _allow_python_mesh_edit_fallback(mesh, "normals.flip", submesh_indices=target_indices):
        return set(), {}
    affected: set[int] = set()
    for submesh_index in sorted(target_indices):
        submesh = mesh.submeshes[submesh_index]
        valid_faces = [face for _face_index, face in _valid_face_items(submesh)]
        if not valid_faces:
            continue
        submesh.faces = [(face[0], face[2], face[1]) for face in valid_faces]
        if len(submesh.normals) == len(submesh.vertices):
            submesh.normals = [(-normal[0], -normal[1], -normal[2]) for normal in submesh.normals]
        else:
            recompute_submesh_normals(submesh)
        affected.add(submesh_index)
    return affected, {}


def _sharpen_normals(mesh: ParsedMesh, selection: MeshEditSelection) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    has_explicit_selection = bool(selection.vertices_by_submesh or selection.edges_by_submesh or selection.faces_by_submesh)
    if selection.source_indices and not has_explicit_selection:
        target_indices = {
            submesh_index
            for submesh_index in selection.source_indices
            if 0 <= submesh_index < len(mesh.submeshes)
        }
        native_changed = apply_native_mesh_sharpen_normals(mesh, {submesh_index: set() for submesh_index in target_indices})
        if native_changed is not None:
            return _changed_from_vertices(native_changed)
        _record_native_edit_fallback(mesh, "normals.sharpen", "native sharpen normals unavailable", submesh_indices=target_indices)
        if not _allow_python_mesh_edit_fallback(mesh, "normals.sharpen", submesh_indices=target_indices):
            return set(), {}
    selected_faces = _selected_faces(mesh, selection, fallback_all=False)
    if not selected_faces:
        return set(), {}
    native_changed = apply_native_mesh_sharpen_normals(mesh, selected_faces)
    if native_changed is not None:
        return _changed_from_vertices(native_changed)
    _record_native_edit_fallback(mesh, "normals.sharpen", "native sharpen normals unavailable", submesh_indices=selected_faces)
    if not _allow_python_mesh_edit_fallback(mesh, "normals.sharpen", submesh_indices=selected_faces):
        return set(), {}
    changed: MeshEditChangedVertices = {}
    for submesh_index, face_indices in selected_faces.items():
        if not 0 <= submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        if not submesh.vertices:
            continue
        normals = list(submesh.normals) if len(submesh.normals) == len(submesh.vertices) else [(0.0, 0.0, 1.0)] * len(submesh.vertices)
        touched = changed.setdefault(submesh_index, set())
        for face_index in sorted(face_indices):
            if not 0 <= face_index < len(submesh.faces):
                continue
            face = _valid_face_vertices(submesh.faces[face_index], len(submesh.vertices))
            if len(face) != 3:
                continue
            face_normal = _face_normal(submesh.vertices, (face[0], face[1], face[2]))
            if face_normal == (0.0, 0.0, 0.0):
                continue
            # ponytail: per-vertex normals cannot store true per-corner hard edges; split edges first when that fidelity matters.
            for vertex_index in face:
                if not _same_vec3(_vec3(normals[vertex_index]), face_normal):
                    normals[vertex_index] = face_normal
                    touched.add(vertex_index)
        if touched:
            submesh.normals = normals
        else:
            changed.pop(submesh_index, None)
    return _changed_from_vertices(changed)


def _copy_normals(
    mesh: ParsedMesh,
    selection: MeshEditSelection,
    params: dict[str, object],
) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    source_mesh = params.get("source_mesh")
    if not isinstance(source_mesh, ParsedMesh):
        return set(), {}
    selected_vertices = selection.vertex_map()
    selected_edges = selection.edge_map()
    selected_faces = selection.face_map()
    source_indices = tuple(selection.source_indices)
    raw_targets = selected_vertices or selected_edges or selected_faces or set(source_indices)
    if not raw_targets:
        return set(), {}
    native_changed = apply_native_mesh_copy_normals(
        mesh,
        source_mesh,
        selected_vertices,
        selected_edges_by_submesh=selected_edges,
        selected_faces_by_submesh=selected_faces,
        source_indices=source_indices,
    )
    if native_changed is not None:
        return _changed_from_vertices(native_changed)
    _record_native_edit_fallback(mesh, "normals.copy", "native copy normals unavailable", submesh_indices=raw_targets)
    if not _allow_python_mesh_edit_fallback(
        mesh,
        "normals.copy",
        submesh_indices=raw_targets,
    ):
        return set(), {}
    selected = _selected_vertices(mesh, selection, fallback_all=False)
    if not selected:
        return set(), {}
    changed: MeshEditChangedVertices = {}
    for submesh_index, vertex_indices in selected.items():
        if not (0 <= submesh_index < len(mesh.submeshes) and 0 <= submesh_index < len(source_mesh.submeshes)):
            continue
        target = mesh.submeshes[submesh_index]
        source = source_mesh.submeshes[submesh_index]
        if len(source.normals) != len(source.vertices) or not target.vertices:
            continue
        normals = list(target.normals) if len(target.normals) == len(target.vertices) else [(0.0, 0.0, 1.0)] * len(target.vertices)
        touched = changed.setdefault(submesh_index, set())
        for vertex_index in sorted(vertex_indices):
            if not (0 <= vertex_index < len(normals) and vertex_index < len(source.normals)):
                continue
            normal = _normalized_vec3(_vec3(source.normals[vertex_index], (0.0, 0.0, 1.0)))
            if normal == (0.0, 0.0, 0.0):
                continue
            if not _same_vec3(_vec3(normals[vertex_index]), normal):
                normals[vertex_index] = normal
                touched.add(vertex_index)
        if touched:
            target.normals = normals
        else:
            changed.pop(submesh_index, None)
    return _changed_from_vertices(changed)


def _selection_target_sources(selection: MeshEditSelection) -> set[int]:
    targets: set[int] = set()
    targets.update(_fallback_submesh_indices(selection.vertex_map()))
    targets.update(_fallback_submesh_indices(selection.edge_map()))
    targets.update(_fallback_submesh_indices(selection.face_map()))
    targets.update(_fallback_submesh_indices(selection.source_indices))
    return targets


def _uv_transform(
    mesh: ParsedMesh,
    selection: MeshEditSelection,
    params: dict[str, object],
) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    use_python_selection_layout = _uses_uv_islands(params)
    native_auto_attempted = False
    native_uv_attempted = False
    selected_vertices = selection.vertex_map()
    selected_edges = selection.edge_map()
    selected_faces = selection.face_map()
    source_indices = tuple(selection.source_indices)
    native_target_sources = _selection_target_sources(selection)
    if not use_python_selection_layout and native_target_sources:
        if _uses_uv_auto(params):
            native_auto_attempted = True
            native_changed = apply_native_mesh_auto_uv(
                mesh,
                native_target_sources,
                resolution=_nonnegative_int(params.get("resolution", params.get("atlas_size", 0))),
                allow_topology_change=_truthy(params.get("allow_topology_change", params.get("confirm_topology_change", False))),
            )
            if native_changed is not None:
                return _changed_from_vertices(native_changed)
            _record_native_edit_fallback(mesh, "uv.auto", "native auto UV unavailable", submesh_indices=native_target_sources)
            if not _allow_python_mesh_edit_fallback(mesh, "uv.auto", submesh_indices=native_target_sources):
                return set(), {}
            params = {**params, "projection": params.get("fallback_projection", "planar")}
        offset = _vec2(params.get("offset", (0.0, 0.0)))
        scale = _vec2(params.get("scale", (1.0, 1.0)), (1.0, 1.0))
        rotate_degrees = _float_value(params.get("rotate", params.get("rotate_degrees", 0.0)))
        flip_u = bool(params.get("flip_u", False))
        flip_v = bool(params.get("flip_v", False))
        pivot = _uv_pivot(params, flip_u=flip_u, flip_v=flip_v)
        special_layout = (
            _uses_uv_projection(params)
            or _uses_uv_normalize(params)
            or _uses_uv_align(params)
            or _uses_uv_pack(params)
            or _uses_uv_snap(params)
        )
        native_uv_attempted = True
        native_changed = apply_native_mesh_uv_transform(
            mesh,
            selected_vertices,
            selected_edges_by_submesh=selected_edges,
            selected_faces_by_submesh=selected_faces,
            source_indices=source_indices,
            **_native_uv_transform_kwargs(
                params,
                offset=offset,
                scale=scale,
                rotate_degrees=rotate_degrees,
                flip_u=flip_u,
                flip_v=flip_v,
                pivot=pivot,
            ),
        )
        if native_changed is not None:
            return _changed_from_vertices(native_changed)
        native_operation = "uv.layout" if special_layout else "uv.transform"
        _record_native_edit_fallback(mesh, native_operation, "native UV transform unavailable", submesh_indices=native_target_sources)
        if not _allow_python_mesh_edit_fallback(mesh, native_operation, submesh_indices=native_target_sources):
            return set(), {}
    elif not use_python_selection_layout:
        return set(), {}
    python_layout_domains = selected_edges or selected_faces or set(source_indices)
    if use_python_selection_layout and python_layout_domains and not _allow_python_mesh_edit_fallback(
        mesh,
        "uv.layout" if use_python_selection_layout else "uv.transform",
        submesh_indices=python_layout_domains,
    ):
        return set(), {}
    selected = _selected_vertices(mesh, selection, fallback_all=False)
    if use_python_selection_layout:
        selected = _uv_island_vertices(mesh, selected)
    if not selected:
        return set(), {}
    if _uses_uv_auto(params) and not native_auto_attempted:
        native_changed = apply_native_mesh_auto_uv(
            mesh,
            set(selected),
            resolution=_nonnegative_int(params.get("resolution", params.get("atlas_size", 0))),
            allow_topology_change=_truthy(params.get("allow_topology_change", params.get("confirm_topology_change", False))),
        )
        if native_changed is not None:
            return _changed_from_vertices(native_changed)
        _record_native_edit_fallback(mesh, "uv.auto", "native auto UV unavailable", submesh_indices=selected)
        params = {**params, "projection": params.get("fallback_projection", "planar")}
    offset = _vec2(params.get("offset", (0.0, 0.0)))
    scale = _vec2(params.get("scale", (1.0, 1.0)), (1.0, 1.0))
    rotate_degrees = _float_value(params.get("rotate", params.get("rotate_degrees", 0.0)))
    flip_u = bool(params.get("flip_u", False))
    flip_v = bool(params.get("flip_v", False))
    pivot = _uv_pivot(params, flip_u=flip_u, flip_v=flip_v)
    special_layout = (
        _uses_uv_projection(params)
        or _uses_uv_normalize(params)
        or _uses_uv_align(params)
        or _uses_uv_pack(params)
        or _uses_uv_snap(params)
    )
    if not native_uv_attempted:
        native_changed = apply_native_mesh_uv_transform(
            mesh,
            selected,
            **_native_uv_transform_kwargs(
                params,
                offset=offset,
                scale=scale,
                rotate_degrees=rotate_degrees,
                flip_u=flip_u,
                flip_v=flip_v,
                pivot=pivot,
            ),
        )
        if native_changed is not None:
            return _changed_from_vertices(native_changed)
        native_operation = "uv.layout" if special_layout else "uv.transform"
        _record_native_edit_fallback(mesh, native_operation, "native UV transform unavailable", submesh_indices=selected)
        if not _allow_python_mesh_edit_fallback(mesh, native_operation, submesh_indices=selected):
            return set(), {}
    changed: MeshEditChangedVertices = {}
    for submesh_index, vertex_indices in selected.items():
        submesh = mesh.submeshes[submesh_index]
        initialized_uvs = False
        if len(submesh.uvs) != len(submesh.vertices):
            if not _uses_uv_projection(params):
                continue
            submesh.uvs = [(0.0, 0.0)] * len(submesh.vertices)
            initialized_uvs = True
        if len(submesh.uvs) != len(submesh.vertices):
            continue
        uvs = list(submesh.uvs)
        valid_vertices = {index for index in vertex_indices if 0 <= index < len(uvs)}
        original_uvs = {index: _vec2(uvs[index]) for index in valid_vertices}
        projected_uvs = _projected_uvs(submesh, valid_vertices, params) if _uses_uv_projection(params) else {}
        for vertex_index in valid_vertices:
            u, v = projected_uvs.get(vertex_index, _vec2(uvs[vertex_index]))
            if flip_u:
                u = (2.0 * pivot[0]) - u
            if flip_v:
                v = (2.0 * pivot[1]) - v
            u = pivot[0] + ((u - pivot[0]) * scale[0])
            v = pivot[1] + ((v - pivot[1]) * scale[1])
            if abs(rotate_degrees) > 1e-8:
                u, v = _rotate_uv((u, v), pivot, rotate_degrees)
            new_uv = (u + offset[0], v + offset[1])
            uvs[vertex_index] = new_uv
        if _uses_uv_normalize(params):
            _normalize_uvs(uvs, valid_vertices, params)
        if _uses_uv_pack(params):
            _pack_uvs(submesh, uvs, valid_vertices, params)
        _align_uvs(uvs, valid_vertices, params)
        if _uses_uv_snap(params):
            _snap_uvs(uvs, valid_vertices, params)
        touched = {
            index
            for index in valid_vertices
            if initialized_uvs or not _same_vec2(original_uvs[index], _vec2(uvs[index]))
        }
        if touched:
            changed[submesh_index] = touched
        submesh.uvs = uvs
    return _changed_from_vertices(changed)


def _uv_pivot(params: dict[str, object], *, flip_u: bool, flip_v: bool) -> Vec2:
    if "pivot" in params or "origin" in params:
        return _vec2(params.get("pivot", params.get("origin", (0.0, 0.0))))
    if flip_u or flip_v:
        return (0.5, 0.5)
    return (0.0, 0.0)


def _native_uv_transform_kwargs(
    params: dict[str, object],
    *,
    offset: Vec2,
    scale: Vec2,
    rotate_degrees: float,
    flip_u: bool,
    flip_v: bool,
    pivot: Vec2,
) -> dict[str, object]:
    return {
        "offset": offset,
        "scale": scale,
        "rotate_degrees": rotate_degrees,
        "flip_u": flip_u,
        "flip_v": flip_v,
        "pivot": pivot,
        "projection": _uv_projection_mode(params) if _uses_uv_projection(params) else "",
        "plane": str(params.get("plane", "") or ""),
        "axis": str(params.get("axis", params.get("cylindrical_axis", "")) or ""),
        "normalize": _uses_uv_normalize(params),
        "target_min": _vec2(params.get("target_min", params.get("normalize_min", (0.0, 0.0)))),
        "target_max": _vec2(params.get("target_max", params.get("normalize_max", (1.0, 1.0))), (1.0, 1.0)),
        "pack": _uses_uv_pack(params),
        "pack_columns": _nonnegative_int(params.get("pack_columns", 0)),
        "padding": max(0.0, _float_value(params.get("padding", params.get("pack_padding", 0.02)), 0.02)),
        "align_u": params.get("align_u"),
        "align_v": params.get("align_v"),
        "snap_step": _uv_snap_steps(params) if _uses_uv_snap(params) else (0.0, 0.0),
        "initialize_missing_uvs": _uses_uv_projection(params),
    }


def _uses_uv_projection(params: dict[str, object]) -> bool:
    projection = _uv_projection_mode(params)
    return projection in {"planar", "xy", "xz", "yz", "box", "cube", "cylindrical", "cylinder"}


def _uses_uv_auto(params: dict[str, object]) -> bool:
    unwrap = str(params.get("unwrap", params.get("auto_unwrap", "")) or "").strip().lower()
    return (
        _truthy(params.get("auto_uv", False))
        or _truthy(params.get("xatlas", False))
        or unwrap in {"auto", "xatlas", "true", "1", "yes"}
    )


def _uses_uv_normalize(params: dict[str, object]) -> bool:
    return _truthy(params.get("normalize", params.get("normalize_uv", False)))


def _uses_uv_align(params: dict[str, object]) -> bool:
    return "align_u" in params or "align_v" in params


def _uses_uv_pack(params: dict[str, object]) -> bool:
    return _truthy(params.get("pack", params.get("pack_uv", params.get("pack_islands", False))))


def _uses_uv_snap(params: dict[str, object]) -> bool:
    return (
        _truthy(params.get("snap", params.get("snap_uv", False)))
        or _truthy(params.get("pixel_snap", params.get("snap_pixels", False)))
        or "snap_grid" in params
        or "snap_increment" in params
    )


def _projected_uvs(submesh: SubMesh, vertex_indices: set[int], params: dict[str, object]) -> dict[int, Vec2]:
    projection = _uv_projection_mode(params)
    if projection in {"cylindrical", "cylinder"}:
        return _cylindrical_projected_uvs(submesh, vertex_indices, params)
    if projection in {"box", "cube"}:
        return _box_projected_uvs(submesh, vertex_indices)
    plane = str(params.get("plane", projection if projection in {"xy", "xz", "yz"} else "xy") or "xy").strip().lower()
    axes = _uv_plane_axes(plane)
    points = {index: _vec3(submesh.vertices[index]) for index in vertex_indices if 0 <= index < len(submesh.vertices)}
    if not points:
        return {}
    return _project_points_to_uvs(points, axes)


def _uv_projection_mode(params: dict[str, object]) -> str:
    projection = str(params.get("projection", params.get("project", "")) or "").strip().lower()
    if projection:
        return projection
    if _truthy(params.get("box_project", params.get("box_projection", False))):
        return "box"
    if _truthy(params.get("cylindrical_project", params.get("cylindrical_projection", False))):
        return "cylindrical"
    return "planar" if _truthy(params.get("planar", False)) else ""


def _uv_plane_axes(plane: str) -> tuple[int, int]:
    return {"xy": (0, 1), "xz": (0, 2), "yz": (1, 2)}.get(str(plane or "xy").strip().lower(), (0, 1))


def _project_points_to_uvs(points: dict[int, Vec3], axes: tuple[int, int]) -> dict[int, Vec2]:
    left_values = [point[axes[0]] for point in points.values()]
    right_values = [point[axes[1]] for point in points.values()]
    left_min, left_max = min(left_values), max(left_values)
    right_min, right_max = min(right_values), max(right_values)
    left_span = left_max - left_min
    right_span = right_max - right_min
    return {
        index: (
            0.0 if abs(left_span) <= 1e-12 else (point[axes[0]] - left_min) / left_span,
            0.0 if abs(right_span) <= 1e-12 else (point[axes[1]] - right_min) / right_span,
        )
        for index, point in points.items()
    }


def _box_projected_uvs(submesh: SubMesh, vertex_indices: set[int]) -> dict[int, Vec2]:
    points_by_axes: dict[tuple[int, int], dict[int, Vec3]] = {}
    for index in vertex_indices:
        if not 0 <= index < len(submesh.vertices):
            continue
        normal = _vec3(submesh.normals[index]) if 0 <= index < len(submesh.normals or ()) else (0.0, 0.0, 1.0)
        points_by_axes.setdefault(_box_projection_axes(normal), {})[index] = _vec3(submesh.vertices[index])
    projected: dict[int, Vec2] = {}
    for axes, points in points_by_axes.items():
        projected.update(_project_points_to_uvs(points, axes))
    return projected


def _box_projection_axes(normal: Vec3) -> tuple[int, int]:
    x, y, z = (abs(normal[0]), abs(normal[1]), abs(normal[2]))
    if x >= y and x >= z:
        return (1, 2)
    if y >= x and y >= z:
        return (0, 2)
    return (0, 1)


def _cylindrical_projected_uvs(submesh: SubMesh, vertex_indices: set[int], params: dict[str, object]) -> dict[int, Vec2]:
    axis = str(params.get("axis", params.get("cylindrical_axis", "z")) or "z").strip().lower()
    angle_axes, height_axis = {"x": ((1, 2), 0), "y": ((0, 2), 1)}.get(axis, ((0, 1), 2))
    points = {index: _vec3(submesh.vertices[index]) for index in vertex_indices if 0 <= index < len(submesh.vertices)}
    if not points:
        return {}
    heights = [point[height_axis] for point in points.values()]
    height_min, height_max = min(heights), max(heights)
    height_span = height_max - height_min
    return {
        index: (
            (math.atan2(point[angle_axes[1]], point[angle_axes[0]]) + math.pi) / (2.0 * math.pi),
            0.0 if abs(height_span) <= 1e-12 else (point[height_axis] - height_min) / height_span,
        )
        for index, point in points.items()
    }


def _normalize_uvs(uvs: list[Vec2], vertex_indices: set[int], params: dict[str, object]) -> None:
    selected = [index for index in sorted(vertex_indices) if 0 <= index < len(uvs)]
    if not selected:
        return
    target_min = _vec2(params.get("target_min", params.get("normalize_min", (0.0, 0.0))))
    target_max = _vec2(params.get("target_max", params.get("normalize_max", (1.0, 1.0))), (1.0, 1.0))
    _normalize_uv_indices(uvs, selected, target_min, target_max)


def _normalize_uv_indices(uvs: list[Vec2], selected: list[int], target_min: Vec2, target_max: Vec2) -> None:
    current = [_vec2(uvs[index]) for index in selected]
    min_u, max_u = min(value[0] for value in current), max(value[0] for value in current)
    min_v, max_v = min(value[1] for value in current), max(value[1] for value in current)
    span_u = max_u - min_u
    span_v = max_v - min_v
    target_span_u = target_max[0] - target_min[0]
    target_span_v = target_max[1] - target_min[1]
    for index in selected:
        u, v = _vec2(uvs[index])
        u = target_min[0] if abs(span_u) <= 1e-12 else target_min[0] + ((u - min_u) / span_u) * target_span_u
        v = target_min[1] if abs(span_v) <= 1e-12 else target_min[1] + ((v - min_v) / span_v) * target_span_v
        uvs[index] = (u, v)


def _pack_uvs(submesh: SubMesh, uvs: list[Vec2], vertex_indices: set[int], params: dict[str, object]) -> None:
    islands = _uv_selected_island_vertex_sets(submesh, vertex_indices)
    if not islands:
        return
    columns = _positive_int(params.get("pack_columns"), int(math.ceil(math.sqrt(len(islands)))))
    rows = int(math.ceil(len(islands) / columns))
    padding = max(0.0, _float_value(params.get("padding", params.get("pack_padding", 0.02))))
    cell_width = 1.0 / columns
    cell_height = 1.0 / rows
    inset_u = min(padding, cell_width * 0.45)
    inset_v = min(padding, cell_height * 0.45)
    for island_index, island in enumerate(islands):
        column = island_index % columns
        row = island_index // columns
        target_min = (column * cell_width + inset_u, row * cell_height + inset_v)
        target_max = ((column + 1) * cell_width - inset_u, (row + 1) * cell_height - inset_v)
        _normalize_uv_indices(uvs, sorted(island), target_min, target_max)


def _uv_selected_island_vertex_sets(submesh: SubMesh, vertex_indices: set[int]) -> tuple[set[int], ...]:
    selected = {index for index in vertex_indices if 0 <= index < len(submesh.uvs)}
    if not selected:
        return ()
    edge_faces: dict[UvEdgeKey, set[int]] = {}
    face_edges: list[tuple[UvEdgeKey, ...]] = []
    face_vertices: dict[int, set[int]] = {}
    seed_faces: set[int] = set()
    for face_index, face in enumerate(submesh.faces or []):
        vertices = set(_valid_face_vertices(face, len(submesh.vertices)))
        face_vertices[face_index] = vertices
        if vertices & selected:
            seed_faces.add(face_index)
        edges = tuple(_uv_face_edges(tuple(face or ())[:3], submesh.uvs))
        face_edges.append(edges)
        for edge in edges:
            edge_faces.setdefault(edge, set()).add(face_index)
    visited: set[int] = set()
    islands: list[set[int]] = []
    for face_index in sorted(seed_faces):
        island_faces = _connected_uv_faces(face_index, face_edges, edge_faces, visited)
        island_vertices = {
            vertex_index
            for island_face_index in island_faces
            for vertex_index in face_vertices.get(island_face_index, set())
            if vertex_index in selected
        }
        if island_vertices:
            islands.append(island_vertices)
    packed_vertices = set().union(*islands) if islands else set()
    islands.extend({index} for index in sorted(selected - packed_vertices))
    return tuple(sorted(islands, key=lambda island: min(island)))


def _connected_uv_faces(
    start_face_index: int,
    face_edges: list[tuple[UvEdgeKey, ...]],
    edge_faces: dict[UvEdgeKey, set[int]],
    visited: set[int],
) -> set[int]:
    pending = [start_face_index]
    island: set[int] = set()
    while pending:
        face_index = pending.pop()
        if face_index in visited or face_index < 0 or face_index >= len(face_edges):
            continue
        visited.add(face_index)
        island.add(face_index)
        for edge in face_edges[face_index]:
            pending.extend(edge_faces.get(edge, set()) - visited)
    return island


def _snap_uvs(uvs: list[Vec2], vertex_indices: set[int], params: dict[str, object]) -> None:
    step_u, step_v = _uv_snap_steps(params)
    if step_u <= 0.0 or step_v <= 0.0:
        return
    for index in sorted(vertex_indices):
        if not 0 <= index < len(uvs):
            continue
        u, v = _vec2(uvs[index])
        uvs[index] = (round(u / step_u) * step_u, round(v / step_v) * step_v)


def _uv_snap_steps(params: dict[str, object]) -> Vec2:
    if _truthy(params.get("pixel_snap", params.get("snap_pixels", False))):
        width = _positive_float(params.get("texture_width"))
        height = _positive_float(params.get("texture_height"))
        if width <= 0.0 or height <= 0.0:
            width, height = _vec2(params.get("texture_size", (1024.0, 1024.0)), (1024.0, 1024.0))
        return (1.0 / max(1.0, width), 1.0 / max(1.0, height))
    raw_step = params.get("snap_grid", params.get("snap_increment", params.get("grid", 0.0)))
    if isinstance(raw_step, (tuple, list)):
        return _vec2(raw_step)
    step = _positive_float(raw_step)
    return (step, step)


def _positive_int(value: object, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return max(1, fallback)
    return max(1, parsed)


def _align_uvs(uvs: list[Vec2], vertex_indices: set[int], params: dict[str, object]) -> None:
    selected = [index for index in sorted(vertex_indices) if 0 <= index < len(uvs)]
    if not selected:
        return
    values = [_vec2(uvs[index]) for index in selected]
    align_u = _uv_align_value(params.get("align_u"), [value[0] for value in values])
    align_v = _uv_align_value(params.get("align_v"), [value[1] for value in values])
    if align_u is None and align_v is None:
        return
    for index in selected:
        u, v = _vec2(uvs[index])
        uvs[index] = (u if align_u is None else align_u, v if align_v is None else align_v)


def _uv_align_value(raw_value: object, values: list[float]) -> float | None:
    if raw_value is None or not values:
        return None
    mode = str(raw_value or "").strip().lower()
    if mode in {"min", "left", "bottom"}:
        return min(values)
    if mode in {"max", "right", "top"}:
        return max(values)
    if mode in {"center", "middle"}:
        return (min(values) + max(values)) / 2.0
    parsed = _float_value(raw_value, float("nan"))
    return parsed if math.isfinite(parsed) else None


def _float_value(value: object, fallback: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    return parsed if math.isfinite(parsed) else fallback


def _rotate_uv(value: Vec2, pivot: Vec2, degrees: float) -> Vec2:
    radians = math.radians(degrees)
    cos_v = math.cos(radians)
    sin_v = math.sin(radians)
    u = value[0] - pivot[0]
    v = value[1] - pivot[1]
    return (pivot[0] + (u * cos_v - v * sin_v), pivot[1] + (u * sin_v + v * cos_v))


def _same_vec2(left: Vec2, right: Vec2) -> bool:
    return abs(left[0] - right[0]) <= 1e-8 and abs(left[1] - right[1]) <= 1e-8


def _uses_uv_islands(params: dict[str, object]) -> bool:
    mode = str(params.get("selection_mode", params.get("mode", "")) or "").strip().lower()
    return mode in {"island", "uv_island"} or _truthy(params.get("uv_island", params.get("island", False)))


def _truthy(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


def _uv_island_vertices(mesh: ParsedMesh, selected: dict[int, set[int]]) -> dict[int, set[int]]:
    expanded: dict[int, set[int]] = {}
    for submesh_index, seed_vertices in selected.items():
        if submesh_index < 0 or submesh_index >= len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        if len(submesh.uvs) != len(submesh.vertices):
            expanded[submesh_index] = set(seed_vertices)
            continue
        seed_faces = {
            face_index
            for face_index, face in enumerate(submesh.faces or [])
            if any(vertex_index in seed_vertices for vertex_index in _valid_face_vertices(face, len(submesh.vertices)))
        }
        if not seed_faces:
            expanded[submesh_index] = set(seed_vertices)
            continue
        edge_faces: dict[UvEdgeKey, set[int]] = {}
        face_edges: list[tuple[UvEdgeKey, ...]] = []
        for face_index, face in enumerate(submesh.faces or []):
            edges = tuple(_uv_face_edges(tuple(face or ())[:3], submesh.uvs))
            face_edges.append(edges)
            for edge in edges:
                edge_faces.setdefault(edge, set()).add(face_index)
        pending = list(seed_faces)
        island_faces: set[int] = set()
        while pending:
            face_index = pending.pop()
            if face_index in island_faces or face_index < 0 or face_index >= len(face_edges):
                continue
            island_faces.add(face_index)
            for edge in face_edges[face_index]:
                pending.extend(edge_faces.get(edge, set()) - island_faces)
        expanded[submesh_index] = {
            vertex_index
            for face_index in island_faces
            for vertex_index in _valid_face_vertices(submesh.faces[face_index], len(submesh.vertices))
        }
    return expanded


def _uv_face_edges(face: tuple[object, ...], uvs: list[tuple[float, float]]) -> list[UvEdgeKey]:
    indices = _valid_face_vertices(face, len(uvs))
    if len(indices) < 3:
        return []
    return [
        (_edge_key(indices[index], indices[(index + 1) % 3]), _uv_edge_key(uvs[indices[index]], uvs[indices[(index + 1) % 3]]))
        for index in range(3)
    ]


def _valid_face_vertices(face: object, vertex_count: int) -> list[int]:
    if not isinstance(face, (tuple, list)):
        return []
    items = tuple(face or ())
    if len(items) < 3:
        return []
    indices: list[int] = []
    for raw_index in items[:3]:
        vertex_index = _coerce_index(raw_index)
        if vertex_index is None:
            return []
        if vertex_index < 0 or vertex_index >= vertex_count:
            return []
        indices.append(vertex_index)
    return indices


def _coerce_index(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text or any(marker in text for marker in ".eE"):
            return None
        try:
            return int(text, 10)
        except ValueError:
            return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None


def _uv_edge_key(left: object, right: object) -> tuple[UvKey, UvKey]:
    a = _uv_key(left)
    b = _uv_key(right)
    return (a, b) if a <= b else (b, a)


def _uv_key(value: object) -> UvKey:
    u, v = _vec2(value)
    return (round(u, 6), round(v, 6))


def _material_assign(
    mesh: ParsedMesh,
    selection: MeshEditSelection,
    params: dict[str, object],
) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    if selection.is_empty():
        return set(), {}
    if not any(key in params for key in _MATERIAL_ASSIGN_PARAM_KEYS | _NATIVE_MATERIAL_OVERRIDE_KEYS):
        return set(), {}
    targets = _material_target_submesh_indices(
        mesh,
        selection,
        changes=lambda submesh: _material_assign_changes(submesh, params),
    )
    affected: set[int] = set()
    material = params.get("material")
    texture = params.get("texture")
    for submesh_index in targets:
        submesh = mesh.submeshes[submesh_index]
        before = _material_signature(submesh)
        if material is not None:
            submesh.material = str(material)
        if texture is not None:
            submesh.texture = str(texture)
        _apply_material_route_metadata(submesh, params)
        if _material_signature(submesh) != before:
            affected.add(submesh_index)
    return affected, {}


def _material_copy(
    mesh: ParsedMesh,
    selection: MeshEditSelection,
    params: dict[str, object],
) -> tuple[MeshEditAffected, MeshEditChangedVertices]:
    if selection.is_empty():
        return set(), {}
    source_index = _coerce_index(params.get("source_submesh_index", params.get("source_index", 0)))
    if source_index is None or source_index < 0 or source_index >= len(mesh.submeshes):
        return set(), {}
    source = mesh.submeshes[source_index]
    targets = _material_target_submesh_indices(
        mesh,
        selection,
        changes=lambda submesh: _material_copy_changes(source, submesh),
    )
    targets.discard(source_index)
    affected: set[int] = set()
    for submesh_index in targets:
        target = mesh.submeshes[submesh_index]
        before = _material_signature(target)
        target.material = str(source.material or "")
        target.texture = str(source.texture or "")
        _copy_material_route_metadata(source, target)
        target.cdmw_mesh_edit_material_source_submesh_index = source_index
        if _material_signature(target) != before:
            affected.add(submesh_index)
    return affected, {}


def _material_target_submesh_indices(
    mesh: ParsedMesh,
    selection: MeshEditSelection,
    *,
    changes: Callable[[SubMesh], bool],
) -> set[int]:
    candidate_indices = set(_submesh_indices(mesh, selection))
    changed_candidates = {
        index
        for index in candidate_indices
        if 0 <= index < len(mesh.submeshes) and changes(mesh.submeshes[index])
    }
    if not changed_candidates:
        return set()
    if selection.source_indices:
        return changed_candidates

    face_targets = _selected_faces(mesh, selection, fallback_all=False)
    if not face_targets:
        return changed_candidates if not (selection.edges_by_submesh or selection.faces_by_submesh or selection.vertices_by_submesh) else set()

    targets: set[int] = set()
    for submesh_index, face_indices in sorted(face_targets.items()):
        if submesh_index not in changed_candidates or not 0 <= submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        valid_faces = {index for index in face_indices if 0 <= index < len(submesh.faces)}
        if not valid_faces:
            continue
        if len(valid_faces) == len(submesh.faces):
            targets.add(submesh_index)
            continue
        split = split_faces_to_submesh(
            mesh,
            selected_faces_by_submesh={submesh_index: valid_faces},
            name_suffix=" material",
            recompute_normals=False,
        )
        if split.new_submesh_index >= 0:
            targets.add(split.new_submesh_index)
    return targets


def _material_assign_changes(submesh: SubMesh, params: dict[str, object]) -> bool:
    probe = copy(submesh)
    material = params.get("material")
    texture = params.get("texture")
    if material is not None:
        probe.material = str(material)
    if texture is not None:
        probe.texture = str(texture)
    _apply_material_route_metadata(probe, params)
    return _material_signature(probe) != _material_signature(submesh)


def _material_copy_changes(source: SubMesh, target: SubMesh) -> bool:
    probe = copy(target)
    probe.material = str(source.material or "")
    probe.texture = str(source.texture or "")
    _copy_material_route_metadata(source, probe)
    return _material_signature(probe) != _material_signature(target)


def _material_signature(submesh: SubMesh) -> tuple[object, ...]:
    return (
        str(submesh.material or ""),
        str(submesh.texture or ""),
        *(getattr(submesh, attr_name, None) for attr_name in _MATERIAL_ROUTE_ATTRS),
        dict(getattr(submesh, "preview_native_material_overrides", {}) or {}),
    )


def _apply_material_route_metadata(submesh: SubMesh, params: dict[str, object]) -> None:
    material_identity_changed = "material" in params or "texture" in params
    if material_identity_changed:
        _clear_material_route_metadata(submesh)
    profile = _first_param(params, "material_authority_profile", "material_profile", "complete_swap_material_profile")
    contract = _first_param(params, "authority_contract", "material_authority_contract")
    if not contract and profile:
        contract = complete_swap_material_authority_contract(profile)
    if profile:
        setattr(submesh, "cdmw_material_authority_profile", str(profile))
    if contract:
        setattr(submesh, "cdmw_material_authority_contract", sanitize_texture_component(contract))
    for param_key, attr_name in (
        ("source_material_name", "cdmw_source_material_name"),
        ("target_material_name", "cdmw_target_material_name"),
        ("slot_kind", "cdmw_material_slot_kind"),
        ("source_texture_set_key", "cdmw_source_texture_set_key"),
        ("route_status", "cdmw_material_route_status"),
        ("route_reason", "cdmw_material_route_reason"),
    ):
        if param_key in params:
            setattr(submesh, attr_name, _material_route_value(params[param_key]))
    slot_index = _first_param(params, "target_material_slot_index", "material_slot_index")
    if slot_index is not None:
        setattr(submesh, "cdmw_target_material_slot_index", _optional_int(slot_index))

    overrides = {} if material_identity_changed else dict(getattr(submesh, "preview_native_material_overrides", {}) or {})
    raw_overrides = _first_param(params, "preview_native_material_overrides", "native_material_overrides")
    if isinstance(raw_overrides, Mapping):
        overrides.update({str(key): value for key, value in raw_overrides.items()})
    for key in _NATIVE_MATERIAL_OVERRIDE_KEYS:
        if key in params:
            overrides[key] = params[key]
    if overrides:
        setattr(submesh, "preview_native_material_overrides", overrides)
    elif material_identity_changed and hasattr(submesh, "preview_native_material_overrides"):
        delattr(submesh, "preview_native_material_overrides")


def _clear_material_route_metadata(submesh: SubMesh) -> None:
    for attr_name in _MATERIAL_ROUTE_ATTRS:
        if hasattr(submesh, attr_name):
            delattr(submesh, attr_name)


def _copy_material_route_metadata(source: SubMesh, target: SubMesh) -> None:
    for attr_name in (*_MATERIAL_ROUTE_ATTRS, *_MATERIAL_PREVIEW_ATTRS):
        if hasattr(source, attr_name):
            value = getattr(source, attr_name)
            if isinstance(value, dict):
                value = dict(value)
            elif isinstance(value, list):
                value = list(value)
            elif isinstance(value, set):
                value = set(value)
            setattr(target, attr_name, value)
        elif hasattr(target, attr_name):
            delattr(target, attr_name)
    overrides = getattr(source, "preview_native_material_overrides", None)
    if isinstance(overrides, Mapping):
        setattr(target, "preview_native_material_overrides", dict(overrides))
    elif hasattr(target, "preview_native_material_overrides"):
        delattr(target, "preview_native_material_overrides")


_MATERIAL_ROUTE_ATTRS = (
        "cdmw_material_authority_profile",
        "cdmw_material_authority_contract",
        "cdmw_source_material_name",
        "cdmw_target_material_name",
        "cdmw_target_material_slot_index",
        "cdmw_material_slot_kind",
        "cdmw_source_texture_set_key",
        "cdmw_material_route_status",
        "cdmw_material_route_reason",
)

_MATERIAL_PREVIEW_ATTRS = (
        "texture_slots",
        "preview_color",
        "preview_role",
        "preview_texture_path",
        "preview_texture_name",
        "preview_texture_dds_path",
        "preview_texture_flip_vertical",
        "preview_texture_brightness",
        "preview_texture_contrast",
        "preview_texture_saturation",
        "preview_texture_gamma",
        "preview_texture_tint",
        "preview_texture_uv_scale",
        "preview_base_texture_default_path",
        "preview_base_texture_default_name",
        "preview_vertex_color_mean",
        "preview_vertex_alpha_mean",
        "preview_vertex_alpha_min",
        "preview_vertex_color_count",
        "preview_normal_texture_path",
        "preview_normal_texture_name",
        "preview_normal_texture_dds_path",
        "preview_normal_texture_strength",
        "preview_material_texture_path",
        "preview_material_texture_name",
        "preview_material_texture_dds_path",
        "preview_material_texture_type",
        "preview_material_texture_subtype",
        "preview_material_texture_packed_channels",
        "preview_material_texture_inputs",
        "preview_material_parameters",
        "preview_material_texture_default_path",
        "preview_material_texture_default_name",
        "preview_height_texture_path",
        "preview_height_texture_name",
        "preview_height_texture_dds_path",
        "preview_alpha_mode",
        "preview_double_sided",
        "preview_sidecar_shader_family",
        "cdmw_mesh_edit_material_source_submesh_index",
)


def _first_param(params: dict[str, object], *keys: str) -> object:
    for key in keys:
        if key in params:
            return params[key]
    return None


def _material_route_value(value: object) -> object:
    if isinstance(value, str):
        return value.strip()
    return value


def _optional_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return -1


def _append_vertex_copy(submesh: SubMesh, source_vertex_index: int, vertex: Vec3) -> int:
    new_index = len(submesh.vertices)
    submesh.vertices.append(vertex)
    if len(submesh.uvs) == new_index:
        submesh.uvs.append(submesh.uvs[source_vertex_index] if source_vertex_index < len(submesh.uvs) else (0.0, 0.0))
    if len(submesh.normals) == new_index:
        submesh.normals.append(submesh.normals[source_vertex_index] if source_vertex_index < len(submesh.normals) else (0.0, 1.0, 0.0))
    if len(submesh.tangents) == new_index:
        submesh.tangents.append(submesh.tangents[source_vertex_index] if source_vertex_index < len(submesh.tangents) else (1.0, 0.0, 0.0))
    if len(submesh.bone_indices) == new_index:
        submesh.bone_indices.append(submesh.bone_indices[source_vertex_index] if source_vertex_index < len(submesh.bone_indices) else ())
    if len(submesh.bone_weights) == new_index:
        submesh.bone_weights.append(submesh.bone_weights[source_vertex_index] if source_vertex_index < len(submesh.bone_weights) else ())
    if len(submesh.source_vertex_map) == new_index:
        submesh.source_vertex_map.append(-1)
    if len(submesh.source_vertex_offsets) == new_index:
        submesh.source_vertex_offsets.append(-1)
    submesh.vertex_count = len(submesh.vertices)
    return new_index


def _append_interpolated_vertex(submesh: SubMesh, left_index: int, right_index: int, fraction: float) -> int:
    t = max(0.0, min(1.0, float(fraction)))
    left = _vec3(submesh.vertices[left_index])
    right = _vec3(submesh.vertices[right_index])
    point = (
        left[0] + (right[0] - left[0]) * t,
        left[1] + (right[1] - left[1]) * t,
        left[2] + (right[2] - left[2]) * t,
    )
    new_index = _append_vertex_copy(submesh, left_index, point)
    if len(submesh.uvs) == len(submesh.vertices) and right_index < new_index:
        left_uv = _vec2(submesh.uvs[left_index])
        right_uv = _vec2(submesh.uvs[right_index])
        submesh.uvs[new_index] = (
            left_uv[0] + (right_uv[0] - left_uv[0]) * t,
            left_uv[1] + (right_uv[1] - left_uv[1]) * t,
        )
    return new_index


def _append_face_copy(mesh: ParsedMesh, submesh_index: int, face_indices: set[int], suffix: str) -> int:
    source = mesh.submeshes[submesh_index]
    selected_faces = [
        face
        for face_index, face in _valid_face_items(source)
        if face_index in face_indices
    ]
    if not selected_faces:
        return -1
    vertex_indices = sorted({index for face in selected_faces for index in face})
    index_map = {old_index: new_index for new_index, old_index in enumerate(vertex_indices)}
    new_submesh = SubMesh(
        name=f"{source.name or 'part'}{suffix}",
        material=str(source.material or ""),
        texture=str(source.texture or ""),
        vertices=[source.vertices[index] for index in vertex_indices],
        uvs=[source.uvs[index] for index in vertex_indices] if len(source.uvs) == len(source.vertices) else [],
        normals=[source.normals[index] for index in vertex_indices] if len(source.normals) == len(source.vertices) else [],
        tangents=[source.tangents[index] for index in vertex_indices] if len(source.tangents) == len(source.vertices) else [],
        faces=[
            (index_map[a], index_map[b], index_map[c])
            for a, b, c in selected_faces
        ],
        bone_indices=[source.bone_indices[index] for index in vertex_indices] if len(source.bone_indices) == len(source.vertices) else [],
        bone_weights=[source.bone_weights[index] for index in vertex_indices] if len(source.bone_weights) == len(source.vertices) else [],
        source_vertex_map=[source.source_vertex_map[index] for index in vertex_indices] if len(source.source_vertex_map) == len(source.vertices) else [],
        source_vertex_offsets=[source.source_vertex_offsets[index] for index in vertex_indices] if len(source.source_vertex_offsets) == len(source.vertices) else [],
        source_vertex_stride=int(source.source_vertex_stride or 0),
        source_lod_count=int(source.source_lod_count or 0),
    )
    new_submesh.vertex_count = len(new_submesh.vertices)
    new_submesh.face_count = len(new_submesh.faces)
    _copy_material_route_metadata(source, new_submesh)
    new_submesh.cdmw_mesh_edit_material_source_submesh_index = submesh_index
    new_submesh.cdmw_mesh_edit_topology_source_submesh_index = submesh_index
    if not new_submesh.normals:
        recompute_submesh_normals(new_submesh)
    mesh.submeshes.append(new_submesh)
    return len(mesh.submeshes) - 1


def _append_mirrored_face_copy(mesh: ParsedMesh, submesh_index: int, face_indices: set[int], axis_index: int) -> int:
    source = mesh.submeshes[submesh_index]
    selected_faces = [
        face
        for face_index, face in _valid_face_items(source)
        if face_index in face_indices
    ]
    if not selected_faces:
        return -1
    vertex_indices = sorted({index for face in selected_faces for index in face if 0 <= index < len(source.vertices)})
    index_map = {old_index: new_index for new_index, old_index in enumerate(vertex_indices)}
    if not vertex_indices:
        return -1
    mirrored_faces = [
        (index_map[a], index_map[c], index_map[b])
        for a, b, c in selected_faces
        if a in index_map and b in index_map and c in index_map
    ]
    if not mirrored_faces:
        return -1
    new_submesh = SubMesh(
        name=f"{source.name or 'part'} mirror",
        material=str(source.material or ""),
        texture=str(source.texture or ""),
        vertices=[_mirrored(source.vertices[index], axis_index) for index in vertex_indices],
        uvs=[source.uvs[index] for index in vertex_indices] if len(source.uvs) == len(source.vertices) else [],
        normals=[source.normals[index] for index in vertex_indices] if len(source.normals) == len(source.vertices) else [],
        tangents=[_mirrored(source.tangents[index], axis_index) for index in vertex_indices] if len(source.tangents) == len(source.vertices) else [],
        faces=mirrored_faces,
        bone_indices=[source.bone_indices[index] for index in vertex_indices] if len(source.bone_indices) == len(source.vertices) else [],
        bone_weights=[source.bone_weights[index] for index in vertex_indices] if len(source.bone_weights) == len(source.vertices) else [],
        source_vertex_map=[source.source_vertex_map[index] for index in vertex_indices] if len(source.source_vertex_map) == len(source.vertices) else [],
        source_vertex_offsets=[source.source_vertex_offsets[index] for index in vertex_indices] if len(source.source_vertex_offsets) == len(source.vertices) else [],
        source_vertex_stride=int(source.source_vertex_stride or 0),
        source_lod_count=int(source.source_lod_count or 0),
    )
    new_submesh.vertex_count = len(new_submesh.vertices)
    new_submesh.face_count = len(new_submesh.faces)
    _copy_material_route_metadata(source, new_submesh)
    recompute_submesh_normals(new_submesh)
    mesh.submeshes.append(new_submesh)
    return len(mesh.submeshes) - 1


__all__ = [
    "MESH_GEOMETRY_ACTIONS",
    "MESH_TOPOLOGY_ACTIONS",
    "NativeLiveHistoryUnavailable",
    "apply_mesh_edit_geometry_action",
    "refresh_mesh_totals",
]
