"""glTF primitive and accessor decoding."""

from __future__ import annotations

import struct
from typing import Any, Sequence

from .mesh_parser import SubMesh, _compute_smooth_normals
from .scene_geometry_utils import _normalize_vec, _safe_int
from .scene_gltf_uv import transform_gltf_uv


_GLTF_COMPONENT_FORMATS = {
    5120: ("b", 1, True),
    5121: ("B", 1, False),
    5122: ("h", 2, True),
    5123: ("H", 2, False),
    5125: ("I", 4, False),
    5126: ("f", 4, True),
}

_GLTF_TYPE_COUNTS = {
    "SCALAR": 1,
    "VEC2": 2,
    "VEC3": 3,
    "VEC4": 4,
    "MAT2": 4,
    "MAT3": 9,
    "MAT4": 16,
}


def _gltf_triangle_faces(
    raw_indices: Sequence[int],
    mode: int,
    vertex_count: int,
) -> list[tuple[int, int, int]]:
    candidates: list[tuple[int, int, int]] = []
    if mode == 4:
        candidates = [
            (raw_indices[index], raw_indices[index + 1], raw_indices[index + 2])
            for index in range(0, len(raw_indices) - 2, 3)
        ]
    elif mode == 5:
        for index in range(len(raw_indices) - 2):
            a, b, c = raw_indices[index : index + 3]
            candidates.append((b, a, c) if index % 2 else (a, b, c))
    elif mode == 6 and raw_indices:
        anchor = raw_indices[0]
        candidates = [
            (anchor, raw_indices[index], raw_indices[index + 1])
            for index in range(1, len(raw_indices) - 1)
        ]
    return [
        face
        for face in candidates
        if min(face) >= 0 and max(face) < vertex_count and len(set(face)) == 3
    ]


def _parse_gltf_primitive(
    payload: Any,
    primitive: dict[str, Any],
    *,
    name: str,
    material: str,
    texture: str,
    texcoord_index: int = 0,
    texcoord_transform: Sequence[float] = (),
    texcoord_rows: Sequence[Sequence[float]] | None = None,
) -> SubMesh:
    attributes = primitive.get("attributes", {})
    positions = _read_gltf_accessor(payload, _safe_int(attributes.get("POSITION"), -1), expected_components=3)
    normals = _read_gltf_accessor(payload, _safe_int(attributes.get("NORMAL"), -1), expected_components=3)
    tangents = _read_gltf_accessor(payload, _safe_int(attributes.get("TANGENT"), -1), expected_components=4)
    texcoord_name = f"TEXCOORD_{max(0, int(texcoord_index or 0))}"
    texcoord_accessor = _safe_int(attributes.get(texcoord_name), -1)
    if texcoord_accessor < 0 and texcoord_name != "TEXCOORD_0":
        payload.diagnostics.append(f"glTF primitive {name} does not provide {texcoord_name}; falling back to TEXCOORD_0.")
        texcoord_accessor = _safe_int(attributes.get("TEXCOORD_0"), -1)
    uvs = (
        [tuple(float(value) for value in row[:2]) for row in texcoord_rows]
        if texcoord_rows is not None
        else _read_gltf_accessor(payload, texcoord_accessor, expected_components=2)
    )
    vertex_colors = _read_gltf_vertex_colors(payload, _safe_int(attributes.get("COLOR_0"), -1))
    index_accessor = _safe_int(primitive.get("indices"), -1)
    raw_indices = (
        [int(values[0]) for values in _read_gltf_accessor(payload, index_accessor, expected_components=1)]
        if index_accessor >= 0
        else list(range(len(positions)))
    )
    faces = _gltf_triangle_faces(raw_indices, _safe_int(primitive.get("mode"), 4), len(positions))
    if len(uvs) == len(positions):
        gltf_uvs = (
            [transform_gltf_uv(uv, texcoord_transform) for uv in uvs]
            if len(texcoord_transform) >= 5
            else [(float(uv[0]), float(uv[1])) for uv in uvs]
        )
        normalized_uvs = [(u, 1.0 - v) for u, v in gltf_uvs]
    else:
        normalized_uvs = []
    if len(normals) != len(positions):
        normals = _compute_smooth_normals(positions, faces)
    authored_tangents = (
        [_normalize_vec((float(row[0]), float(row[1]), float(row[2]))) for row in tangents]
        if len(tangents) == len(positions)
        else []
    )
    submesh = SubMesh(
        name=name,
        material=material,
        texture=texture,
        vertices=[(float(v[0]), float(v[1]), float(v[2])) for v in positions],
        uvs=normalized_uvs,
        normals=[(float(n[0]), float(n[1]), float(n[2])) for n in normals],
        tangents=authored_tangents,
        faces=faces,
        vertex_count=len(positions),
        face_count=len(faces),
    )
    if authored_tangents:
        setattr(submesh, "tangent_signs", [float(row[3]) for row in tangents])
    if len(vertex_colors) == len(positions):
        _attach_gltf_vertex_color_summary(submesh, vertex_colors)
    return submesh


def _read_gltf_vertex_colors(payload: Any, accessor_index: int) -> list[tuple[float, float, float, float]]:
    if accessor_index < 0:
        return []
    color_rows = _read_gltf_accessor(payload, accessor_index, expected_components=4)
    if not color_rows:
        rgb_rows = _read_gltf_accessor(payload, accessor_index, expected_components=3)
        color_rows = [tuple(row[:3]) + (1.0,) for row in rgb_rows]
    output: list[tuple[float, float, float, float]] = []
    for row in color_rows:
        if len(row) < 3:
            continue
        rgba = tuple(max(0.0, min(1.0, float(value))) for value in (tuple(row[:4]) + (1.0,))[:4])
        output.append(rgba)  # type: ignore[arg-type]
    return output


def _attach_gltf_vertex_color_summary(
    submesh: SubMesh,
    vertex_colors: Sequence[Sequence[float]],
) -> None:
    rows = [
        tuple(float(value) for value in tuple(row or ())[:4])
        for row in tuple(vertex_colors or ())
        if len(tuple(row or ())) >= 4
    ]
    if not rows:
        return
    count = float(len(rows))
    mean = tuple(sum(row[index] for row in rows) / count for index in range(4))
    setattr(submesh, "preview_vertex_color_mean", tuple(round(max(0.0, min(1.0, value)), 4) for value in mean[:3]))
    setattr(submesh, "preview_vertex_alpha_mean", round(max(0.0, min(1.0, mean[3])), 4))
    setattr(submesh, "preview_vertex_alpha_min", round(max(0.0, min(1.0, min(row[3] for row in rows))), 4))
    setattr(submesh, "preview_vertex_color_count", len(rows))


def _read_gltf_accessor(payload: Any, accessor_index: int, *, expected_components: int) -> list[tuple[float, ...]]:
    accessors = payload.document.get("accessors", []) or []
    if accessor_index < 0:
        return []
    if accessor_index >= len(accessors) or not isinstance(accessors[accessor_index], dict):
        raise ValueError(f"glTF accessor index is invalid: {accessor_index}")
    accessor = accessors[accessor_index]
    if accessor.get("sparse"):
        payload.diagnostics.append("glTF sparse accessors are not expanded; affected attributes may import incompletely.")
    component_type = int(accessor.get("componentType", 0) or 0)
    component_count = _GLTF_TYPE_COUNTS.get(str(accessor.get("type", "SCALAR") or "SCALAR"), 1)
    if expected_components > component_count:
        return []
    count = int(accessor.get("count", 0) or 0)
    buffer_view_index = _safe_int(accessor.get("bufferView"), -1)
    if buffer_view_index < 0:
        return [(0.0,) * expected_components for _index in range(count)]
    view = _gltf_buffer_view(payload, buffer_view_index)
    fmt, component_size, _signed = _GLTF_COMPONENT_FORMATS.get(component_type, ("", 0, False))
    if not fmt or component_size <= 0:
        raise ValueError(f"Unsupported glTF accessor component type: {component_type}")
    buffer_index = _safe_int(view.get("buffer"), -1)
    if buffer_index < 0 or buffer_index >= len(payload.buffers):
        raise ValueError(f"glTF accessor references missing buffer {buffer_index}.")
    buffer_data = payload.buffers[buffer_index]
    byte_stride = int(view.get("byteStride", 0) or 0) or component_size * component_count
    start = int(view.get("byteOffset", 0) or 0) + int(accessor.get("byteOffset", 0) or 0)
    normalized = bool(accessor.get("normalized", False))
    rows: list[tuple[float, ...]] = []
    unpack = struct.Struct("<" + fmt)
    for row_index in range(count):
        row_start = start + row_index * byte_stride
        values: list[float] = []
        for component_index in range(component_count):
            offset = row_start + component_index * component_size
            value = unpack.unpack_from(buffer_data, offset)[0] if offset + component_size <= len(buffer_data) else 0.0
            values.append(float(_normalize_gltf_component(value, component_type)) if normalized else float(value))
        rows.append(tuple(values[:expected_components]))
    return rows


def _gltf_buffer_view(payload: Any, view_index: int) -> dict[str, Any]:
    views = payload.document.get("bufferViews", []) or []
    if view_index < 0 or view_index >= len(views) or not isinstance(views[view_index], dict):
        raise ValueError(f"glTF bufferView index is invalid: {view_index}")
    return views[view_index]


def _read_gltf_buffer_view_bytes(payload: Any, view_index: int) -> bytes:
    view = _gltf_buffer_view(payload, view_index)
    buffer_index = _safe_int(view.get("buffer"), -1)
    if buffer_index < 0 or buffer_index >= len(payload.buffers):
        raise ValueError(f"glTF image references missing buffer {buffer_index}.")
    offset = int(view.get("byteOffset", 0) or 0)
    length = int(view.get("byteLength", 0) or 0)
    return payload.buffers[buffer_index][offset : offset + length]


def _normalize_gltf_component(value: object, component_type: int) -> float:
    number = float(value)
    if component_type == 5120:
        return max(number / 127.0, -1.0)
    if component_type == 5121:
        return number / 255.0
    if component_type == 5122:
        return max(number / 32767.0, -1.0)
    if component_type == 5123:
        return number / 65535.0
    if component_type == 5125:
        return number / 4294967295.0
    return number
