"""glTF primitive and accessor decoding."""

from __future__ import annotations

import math
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
    if any(index < 0 or index >= vertex_count for index in raw_indices):
        raise ValueError("glTF face references a missing vertex.")
    if mode == 4 and len(raw_indices) % 3:
        raise ValueError("glTF triangle index count is incomplete.")
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
        normalized_uvs = (gltf_uvs if getattr(payload, "preserve_authoring", False)
                          else [(u, 1.0 - v) for u, v in gltf_uvs])
    else:
        normalized_uvs = []
    if len(normals) != len(positions):
        if getattr(payload, "preserve_authoring", False):
            if "NORMAL" in attributes:
                raise ValueError(f"glTF normal count mismatch in {name}.")
            normals = []
        else:
            normals = _compute_smooth_normals(positions, faces)
    authored_tangents = (
        [(float(row[0]), float(row[1]), float(row[2])) if getattr(payload, "preserve_authoring", False)
         else _normalize_vec((float(row[0]), float(row[1]), float(row[2]))) for row in tangents]
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
    if "_CDMW_VERTEX_ID" in attributes:
        ids = _read_gltf_accessor(payload, int(attributes["_CDMW_VERTEX_ID"]), expected_components=1)
        if len(ids) != len(positions) or any(v[0] < 0 or int(v[0]) != v[0] for v in ids):
            raise ValueError("Invalid CDMW vertex identity attribute.")
        submesh.interchange_vertex_ids = [int(row[0]) for row in ids]
    if authored_tangents:
        setattr(submesh, "tangent_signs", [float(row[3]) for row in tangents])
    if len(vertex_colors) == len(positions):
        submesh.vertex_colors = list(vertex_colors)
        _attach_gltf_vertex_color_summary(submesh, vertex_colors)
    for key, accessor in attributes.items():
        if key.startswith("TEXCOORD_"):
            rows = _read_gltf_accessor(payload, int(accessor), expected_components=2)
            if len(rows) != len(positions):
                if getattr(payload, "preserve_authoring", False):
                    raise ValueError(f"glTF {key} vertex count mismatch in {name}.")
                continue
            submesh.uv_sets[int(key.split("_")[-1])] = [
                (float(u), float(v) if getattr(payload, "preserve_authoring", False) else 1.0 - float(v))
                for u, v in rows
            ]
    joint_sets = sorted(int(key.split("_")[-1]) for key in attributes if key.startswith("JOINTS_"))
    if joint_sets:
        indices = [[] for _ in positions]
        weights = [[] for _ in positions]
        for slot in joint_sets:
            joints = _read_gltf_accessor(payload, int(attributes[f"JOINTS_{slot}"]), expected_components=4)
            values = _read_gltf_accessor(payload, _safe_int(attributes.get(f"WEIGHTS_{slot}"), -1), expected_components=4)
            if len(joints) != len(positions) or len(values) != len(positions):
                raise ValueError(f"glTF skin attribute count mismatch in {name}.")
            for i, (joint_row, weight_row) in enumerate(zip(joints, values)):
                for joint, weight in zip(joint_row, weight_row):
                    if not math.isfinite(weight) or weight < 0 or joint < 0 or int(joint) != joint:
                        raise ValueError(f"Invalid glTF skin influence in {name}.")
                    if weight > 0:
                        indices[i].append(int(joint))
                        weights[i].append(float(weight))
        submesh.bone_indices = [tuple(row) for row in indices]
        submesh.bone_weights = [tuple(row) for row in weights]
    target_names = primitive.get("_cdmw_target_names", ())
    for index, target in enumerate(primitive.get("targets", ()) or ()):
        target_name = str(target_names[index]) if index < len(target_names) else f"target_{index}"
        deltas = _read_gltf_accessor(payload, _safe_int(target.get("POSITION"), -1), expected_components=3)
        if not deltas:
            deltas = [(0.0, 0.0, 0.0)] * len(positions)
        if len(deltas) != len(positions):
            raise ValueError(f"glTF morph target count mismatch in {name}.")
        submesh.morph_targets[target_name] = [tuple(float(p[a] + d[a]) for a in range(3)) for p, d in zip(positions, deltas)]
        normal_deltas = _read_gltf_accessor(payload, _safe_int(target.get("NORMAL"), -1), expected_components=3)
        if normal_deltas:
            if len(normal_deltas) != len(positions):
                raise ValueError(f"glTF morph normal count mismatch in {name}.")
            submesh.morph_normals[target_name] = [tuple(float(n[a] + d[a]) for a in range(3)) for n, d in zip(normals, normal_deltas)]
        tangent_deltas = _read_gltf_accessor(payload, _safe_int(target.get("TANGENT"), -1), expected_components=3)
        if tangent_deltas:
            if len(tangent_deltas) != len(positions) or len(authored_tangents) != len(positions):
                raise ValueError(f"glTF morph tangent count mismatch in {name}.")
            submesh.morph_tangents[target_name] = [tuple(float(t[a] + d[a]) for a in range(3)) for t, d in zip(authored_tangents, tangent_deltas)]
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
    component_type = int(accessor.get("componentType", 0) or 0)
    component_count = _GLTF_TYPE_COUNTS.get(str(accessor.get("type", "SCALAR") or "SCALAR"), 1)
    if expected_components > component_count:
        return []
    count = int(accessor.get("count", 0) or 0)
    if count < 0 or count > 10_000_000:
        raise ValueError("glTF accessor count is outside supported bounds.")
    fmt, component_size, _signed = _GLTF_COMPONENT_FORMATS.get(component_type, ("", 0, False))
    if not fmt:
        raise ValueError(f"Unsupported glTF accessor component type: {component_type}")
    buffer_view_index = _safe_int(accessor.get("bufferView"), -1)
    normalized = bool(accessor.get("normalized", False))
    def read_rows(view_index, offset, nrows, code, size, width, normalize=False):
        view = _gltf_buffer_view(payload, view_index)
        data = _read_gltf_buffer_view_bytes(payload, view_index)
        stride = int(view.get("byteStride", 0) or 0) or size * width
        if offset < 0 or stride < size * width or (nrows and offset + (nrows - 1) * stride + size * width > len(data)):
            raise ValueError("glTF accessor exceeds its bufferView or has an invalid stride.")
        unpack = struct.Struct("<" + code * width)
        result = []
        for i in range(nrows):
            values = unpack.unpack_from(data, offset + i * stride)
            result.append(tuple(float(_normalize_gltf_component(v, component_type)) if normalize else float(v) for v in values))
        return result
    rows = (read_rows(buffer_view_index, int(accessor.get("byteOffset", 0) or 0), count, fmt, component_size,
                      component_count, normalized) if buffer_view_index >= 0
            else [(0.0,) * component_count for _ in range(count)])
    sparse = accessor.get("sparse")
    if sparse:
        sparse_count = int(sparse.get("count", 0))
        if not 0 <= sparse_count <= count:
            raise ValueError("glTF sparse accessor count exceeds its accessor.")
        indices = sparse["indices"]
        index_type = int(indices.get("componentType", 0))
        if index_type not in {5121, 5123, 5125}:
            raise ValueError("Invalid glTF sparse index component type.")
        index_code, index_size, _ = _GLTF_COMPONENT_FORMATS[index_type]
        index_rows = read_rows(int(indices["bufferView"]), int(indices.get("byteOffset", 0)), sparse_count, index_code, index_size, 1)
        values = sparse["values"]
        value_rows = read_rows(int(values["bufferView"]), int(values.get("byteOffset", 0)), sparse_count, fmt, component_size,
                              component_count, normalized)
        previous = -1
        for (index,), row in zip(index_rows, value_rows):
            index = int(index)
            if index <= previous or index >= count:
                raise ValueError("glTF sparse indices must be increasing and within the accessor.")
            rows[index] = row
            previous = index
    rows = [row[:expected_components] for row in rows]
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
    if offset < 0 or length < 0 or offset + length > len(payload.buffers[buffer_index]):
        raise ValueError("glTF bufferView exceeds its buffer.")
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
