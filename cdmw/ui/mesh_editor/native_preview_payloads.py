"""Native preview payload helpers for Mesh Editor sessions."""

from __future__ import annotations

import math
import struct
from pathlib import Path
from typing import Mapping, Sequence

from cdmw.domain.mesh import MeshEditSelection
from cdmw.models import PreparedModelPreviewBatch, PreparedModelPreviewData
from cdmw.modding.mesh_parser import ParsedMesh

_VERTEX_STRUCT = struct.Struct("<23f")
_NATIVE_MATERIAL_OVERRIDE_KEYS = (
    "texture_brightness",
    "roughness",
    "metalness",
    "specular",
    "height_scale",
    "emissive_intensity",
    "emissive_color",
    "contrast",
    "saturation",
    "gamma",
    "tint_color",
)
_NATIVE_MATERIAL_SCALAR_OVERRIDE_KEYS = (
    "texture_brightness",
    "roughness",
    "metalness",
    "specular",
    "height_scale",
    "emissive_intensity",
    "contrast",
    "saturation",
    "gamma",
)
_NATIVE_MATERIAL_COLOR_OVERRIDE_KEYS = ("emissive_color", "tint_color")
_DEFAULT_NATIVE_MATERIAL_OVERRIDES: Mapping[str, object] = {
    "texture_brightness": 1.0,
    "roughness": 0.0,
    "metalness": 0.0,
    "specular": 0.0,
    "height_scale": 0.0,
    "emissive_intensity": 0.0,
    "emissive_color": [0.35, 0.68, 1.0],
    "contrast": 1.0,
    "saturation": 1.0,
    "gamma": 1.0,
    "tint_color": [1.0, 1.0, 1.0],
}


def mesh_to_native_preview(mesh: ParsedMesh) -> PreparedModelPreviewData:
    batches: list[PreparedModelPreviewBatch] = []
    valid_face_count = 0
    for submesh_index, submesh in enumerate(mesh.submeshes):
        positions: list[tuple[float, float, float]] = []
        normals: list[tuple[float, float, float]] = []
        uvs: list[tuple[float, float]] = []
        source_vertices: list[int] = []
        source_faces: list[int] = []
        valid_faces = _valid_face_items(submesh)
        valid_face_count += len(valid_faces)
        for face_index, face in valid_faces:
            for vertex_index in face:
                positions.append(_vec3(submesh.vertices[vertex_index]))
                normal = submesh.normals[vertex_index] if vertex_index < len(submesh.normals) else (0.0, 0.0, 1.0)
                uv = submesh.uvs[vertex_index] if vertex_index < len(submesh.uvs) else (0.0, 0.0)
                normals.append(_vec3(normal, (0.0, 0.0, 1.0)))
                uvs.append(_vec2(uv))
                source_vertices.append(int(vertex_index))
            source_faces.append(int(face_index))
        batches.append(
            PreparedModelPreviewBatch(
                material_name=str(submesh.material or submesh.name or f"part_{submesh_index}"),
                texture_name=str(submesh.texture or ""),
                preview_texture_path=_local_texture_preview_path(submesh.texture),
                preview_texture_dds_path=_local_texture_dds_path(submesh.texture),
                vertex_blob=b"".join(_vertex_blob(position, normal, uv) for position, normal, uv in zip(positions, normals, uvs)),
                index_count=len(positions),
                has_texture_coordinates=bool(uvs),
                preview_native_material_overrides=dict(getattr(submesh, "preview_native_material_overrides", {}) or {}),
                source_submesh_index=submesh_index,
                source_vertex_indices=tuple(source_vertices),
                source_face_indices=tuple(source_faces),
                editor_role="replacement_preview",
                editor_part_name=str(submesh.name or ""),
                editor_editable=True,
            )
        )
    return PreparedModelPreviewData(
        source_path=str(mesh.path or "mesh_editor.pac"),
        format=str(mesh.format or "pac"),
        mesh_count=len(mesh.submeshes),
        vertex_count=_nonnegative_int(mesh.total_vertices),
        face_count=valid_face_count,
        batches=tuple(batches),
    )


def _local_texture_preview_path(value: object) -> str:
    path = _local_texture_path(value)
    if path is None:
        return ""
    return str(path)


def _local_texture_dds_path(value: object) -> str:
    path = _local_texture_path(value)
    if path is None or path.suffix.lower() != ".dds":
        return ""
    return str(path)


def _local_texture_path(value: object) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        path = Path(text).expanduser()
    except OSError:
        return None
    try:
        if path.is_file():
            return path.resolve()
    except OSError:
        return None
    return None


def mesh_edit_triangle_groups(mesh: ParsedMesh, source_submesh_indices: Sequence[int] | None = None) -> list[dict[str, object]]:
    groups: list[dict[str, object]] = []
    selected = None if source_submesh_indices is None else set(_source_submesh_indices(source_submesh_indices))
    for submesh_index, submesh in enumerate(mesh.submeshes):
        if selected is not None and submesh_index not in selected:
            continue
        valid_faces = _valid_face_items(submesh)
        has_valid_faces = bool(valid_faces)
        groups.append(
            {
                "source_submesh_index": submesh_index,
                "material_name": str(submesh.material or submesh.name or f"part_{submesh_index}"),
                "texture_name": str(submesh.texture or ""),
                "positions": [component for vertex in submesh.vertices for component in _vec3(vertex)] if has_valid_faces else [],
                "normals": [
                    component
                    for index in range(len(submesh.vertices))
                    for component in _vec3(submesh.normals[index] if index < len(submesh.normals) else (0.0, 0.0, 1.0), (0.0, 0.0, 1.0))
                ]
                if has_valid_faces
                else [],
                "uvs": [
                    component
                    for index in range(len(submesh.vertices))
                    for component in _vec2(submesh.uvs[index] if index < len(submesh.uvs) else (0.0, 0.0))
                ]
                if has_valid_faces
                else [],
                "source_vertex_indices": list(range(len(submesh.vertices))) if has_valid_faces else [],
                "source_face_indices": [face_index for face_index, _face in valid_faces],
                "indices": [index for _face_index, face in valid_faces for index in face],
            }
        )
    return groups


def mesh_edit_material_override_groups(
    mesh: ParsedMesh,
    source_submesh_indices: Sequence[int],
    *,
    include_defaults: bool = False,
) -> list[dict[str, object]]:
    groups: list[dict[str, object]] = []
    for submesh_index in _source_submesh_indices(source_submesh_indices):
        if submesh_index >= len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        overrides = dict(getattr(submesh, "preview_native_material_overrides", {}) or {})
        group: dict[str, object] = {
            "source_submesh_indices": [submesh_index],
            "editor_role": "replacement_preview",
            "material_name": str(submesh.material or submesh.name or f"part_{submesh_index}"),
            "texture_name": str(submesh.texture or ""),
        }
        if include_defaults:
            group.update(_sanitized_material_override_values(_DEFAULT_NATIVE_MATERIAL_OVERRIDES, include_defaults=False))
        group.update(_sanitized_material_override_values(overrides, include_defaults=include_defaults))
        if include_defaults or len(group) > 4:
            groups.append(group)
    return groups


def mesh_edit_selection_groups(mesh: ParsedMesh, selection: MeshEditSelection) -> list[dict[str, object]]:
    vertices_by_submesh = selection.vertex_map()
    edges_by_submesh = selection.edge_map()
    faces_by_submesh = selection.face_map()
    selected_vertices: dict[int, set[int]] = {submesh: set(indices) for submesh, indices in vertices_by_submesh.items()}
    selected_edges_by_submesh: dict[int, set[tuple[int, int]]] = {}
    for submesh_index, edges in edges_by_submesh.items():
        if not 0 <= submesh_index < len(mesh.submeshes):
            continue
        edges = _valid_selected_edges_for_submesh(mesh.submeshes[submesh_index], edges)
        if not edges:
            continue
        selected_edges_by_submesh[submesh_index] = edges
        vertices = selected_vertices.setdefault(submesh_index, set())
        for a, b in edges:
            vertices.update((a, b))
    for submesh_index, faces in faces_by_submesh.items():
        if not 0 <= submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        valid_faces = dict(_valid_face_items(submesh))
        vertices = selected_vertices.setdefault(submesh_index, set())
        for face_index in faces:
            face = valid_faces.get(face_index)
            if face is not None:
                vertices.update(face)
    for submesh_index in selection.source_indices:
        if 0 <= submesh_index < len(mesh.submeshes):
            selected_vertices.setdefault(submesh_index, set()).update(range(len(mesh.submeshes[submesh_index].vertices)))

    groups: list[dict[str, object]] = []
    for submesh_index, raw_vertices in sorted(selected_vertices.items()):
        if not 0 <= submesh_index < len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        vertices = sorted(index for index in raw_vertices if 0 <= index < len(submesh.vertices))
        if not vertices:
            continue
        group: dict[str, object] = {
            "source_submesh_index": submesh_index,
            "source_vertex_indices": vertices,
        }
        selected_edges = sorted(selected_edges_by_submesh.get(submesh_index, ()))
        if selected_edges:
            group["source_edges"] = [[a, b] for a, b in selected_edges]
        valid_face_indices = {face_index for face_index, _face in _valid_face_items(submesh)}
        selected_faces = sorted(index for index in faces_by_submesh.get(submesh_index, ()) if index in valid_face_indices)
        if selected_faces:
            group["source_face_indices"] = selected_faces
        groups.append(group)
    return groups


def mesh_edit_vertex_update_groups(mesh: ParsedMesh, changed_vertices_by_submesh: Mapping[int, Sequence[int]]) -> list[dict[str, object]]:
    groups: list[dict[str, object]] = []
    for raw_submesh_index, raw_indices in changed_vertices_by_submesh.items():
        try:
            submesh_index = int(raw_submesh_index)
        except (TypeError, ValueError, OverflowError):
            continue
        if submesh_index < 0 or submesh_index >= len(mesh.submeshes):
            continue
        submesh = mesh.submeshes[submesh_index]
        indices = _source_vertex_indices(raw_indices, len(submesh.vertices))
        if not indices:
            continue
        groups.append(
            {
                "source_submesh_index": submesh_index,
                "source_vertex_indices": indices,
                "positions": [component for index in indices for component in _vec3(submesh.vertices[index])],
                "normals": [
                    component
                    for index in indices
                    for component in _vec3(submesh.normals[index] if index < len(submesh.normals) else (0.0, 0.0, 1.0), (0.0, 0.0, 1.0))
                ],
                "uvs": [
                    component
                    for index in indices
                    for component in _vec2(submesh.uvs[index] if index < len(submesh.uvs) else (0.0, 0.0))
                ],
            }
        )
    return groups


def _vertex_blob(position: Sequence[float], normal: Sequence[float], uv: Sequence[float]) -> bytes:
    position_vec = _vec3(position)
    normal_vec = _vec3(normal, (0.0, 0.0, 1.0))
    uv_vec = _vec2(uv)
    return _VERTEX_STRUCT.pack(
        position_vec[0],
        position_vec[1],
        position_vec[2],
        normal_vec[0],
        normal_vec[1],
        normal_vec[2],
        0.25,
        0.55,
        0.85,
        uv_vec[0],
        uv_vec[1],
        1.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        normal_vec[0],
        normal_vec[1],
        normal_vec[2],
        0.0,
        0.0,
        0.0,
    )


def _finite_float(value: object, fallback: float = 0.0) -> float:
    parsed = _finite_float_or_none(value)
    return fallback if parsed is None else parsed


def _finite_float_or_none(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _nonnegative_int(value: object, fallback: int = 0) -> int:
    parsed = _coerce_index(value)
    if parsed is None:
        return fallback
    return parsed if parsed >= 0 else fallback


def _vec3(value: object, fallback: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> tuple[float, float, float]:
    if not isinstance(value, (tuple, list)) or len(value) < 3:
        return fallback
    parsed = (_finite_float(value[0]), _finite_float(value[1]), _finite_float(value[2]))
    return parsed if all(math.isfinite(component) for component in parsed) else fallback


def _vec2(value: object, fallback: tuple[float, float] = (0.0, 0.0)) -> tuple[float, float]:
    if not isinstance(value, (tuple, list)) or len(value) < 2:
        return fallback
    parsed = (_finite_float(value[0]), _finite_float(value[1]))
    return parsed if all(math.isfinite(component) for component in parsed) else fallback


def _source_submesh_indices(indices: Sequence[int] | None) -> tuple[int, ...]:
    result: list[int] = []
    seen: set[int] = set()
    try:
        raw_indices = tuple(indices or ())
    except TypeError:
        return ()
    for raw_index in raw_indices:
        index = _coerce_index(raw_index)
        if index is None:
            continue
        if index >= 0 and index not in seen:
            result.append(index)
            seen.add(index)
    return tuple(result)


def _source_vertex_indices(indices: Sequence[int], vertex_count: int) -> list[int]:
    result: list[int] = []
    seen: set[int] = set()
    try:
        raw_indices = tuple(indices or ())
    except TypeError:
        return []
    for raw_index in raw_indices:
        index = _coerce_index(raw_index)
        if index is None:
            continue
        if 0 <= index < vertex_count and index not in seen:
            result.append(index)
            seen.add(index)
    return result


def _valid_face_items(submesh: object) -> tuple[tuple[int, tuple[int, int, int]], ...]:
    vertices = tuple(getattr(submesh, "vertices", ()) or ())
    items: list[tuple[int, tuple[int, int, int]]] = []
    for face_index, face in enumerate(tuple(getattr(submesh, "faces", ()) or ())):
        face_vertices = _valid_face_vertices(face, len(vertices))
        if len(face_vertices) == 3:
            items.append((face_index, (face_vertices[0], face_vertices[1], face_vertices[2])))
    return tuple(items)


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


def _sanitized_material_override_values(overrides: Mapping[str, object], *, include_defaults: bool) -> dict[str, object]:
    values: dict[str, object] = {}
    defaults = _DEFAULT_NATIVE_MATERIAL_OVERRIDES if include_defaults else {}
    for key in _NATIVE_MATERIAL_SCALAR_OVERRIDE_KEYS:
        if key not in overrides:
            continue
        parsed = _finite_float_or_none(overrides[key])
        if parsed is not None:
            values[key] = parsed
        elif key in defaults:
            values[key] = defaults[key]
    for key in _NATIVE_MATERIAL_COLOR_OVERRIDE_KEYS:
        if key not in overrides:
            continue
        parsed_color = _finite_color(overrides[key])
        if parsed_color is not None:
            values[key] = parsed_color
        elif key in defaults:
            values[key] = list(defaults[key]) if isinstance(defaults[key], list) else defaults[key]
    return values


def _finite_color(value: object) -> list[float] | None:
    if not isinstance(value, (tuple, list)) or len(value) < 3:
        return None
    parsed = [_finite_float_or_none(component) for component in value[:3]]
    if any(component is None for component in parsed):
        return None
    return [float(component) for component in parsed if component is not None]


def _valid_selected_edges_for_submesh(submesh: object, edges: set[tuple[int, int]]) -> set[tuple[int, int]]:
    vertex_count = len(tuple(getattr(submesh, "vertices", ()) or ()))
    selected = {
        _edge_key(a, b)
        for a, b in edges
        if 0 <= a < vertex_count and 0 <= b < vertex_count and a != b
    }
    if not selected:
        return set()
    if not tuple(getattr(submesh, "faces", ()) or ()):
        return selected
    return selected & _existing_face_edges(submesh)


def _existing_face_edges(submesh: object) -> set[tuple[int, int]]:
    edges: set[tuple[int, int]] = set()
    for _face_index, (a, b, c) in _valid_face_items(submesh):
        edges.update((_edge_key(a, b), _edge_key(b, c), _edge_key(c, a)))
    return edges


def _edge_key(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a <= b else (b, a)


__all__ = [
    "mesh_edit_material_override_groups",
    "mesh_edit_selection_groups",
    "mesh_edit_triangle_groups",
    "mesh_edit_vertex_update_groups",
    "mesh_to_native_preview",
]
