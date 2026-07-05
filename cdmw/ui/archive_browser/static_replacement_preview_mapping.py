"""Pure preview mapping helpers for static replacement."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence

from cdmw.models import ModelPreviewData, ModelPreviewMesh
from cdmw.modding.static_mesh_replacer import _semantic_tokens


def preview_target_mesh_indices(
    preview_model: object,
    target_name: str,
    fallback_indices: Sequence[int],
    *,
    mapped_preview: bool,
    current_mappings: Sequence[object],
    preview_submesh_index_map: Mapping[int, int],
) -> tuple[int, ...]:
    meshes = tuple(getattr(preview_model, "meshes", ()) or ())
    if not mapped_preview:
        return tuple(index for index in fallback_indices if 0 <= index < len(meshes))
    target_key = str(target_name or "").strip().lower()
    fallback_tuple = tuple(int(index) for index in tuple(fallback_indices or ()))
    for mapping in tuple(current_mappings or ()):
        mapping_sources = tuple(int(index) for index in tuple(getattr(mapping, "source_submesh_indices", ()) or ()))
        if mapping_sources != fallback_tuple:
            continue
        if target_key and str(getattr(mapping, "target_submesh_name", "") or "").strip().lower() != target_key:
            continue
        target_index = int(getattr(mapping, "target_submesh_index", -1))
        mapped_index = preview_submesh_index_map.get(target_index)
        if mapped_index is not None and 0 <= mapped_index < len(meshes):
            return (mapped_index,)
        if not preview_submesh_index_map and 0 <= target_index < len(meshes):
            return (target_index,)
    target_tokens = _semantic_tokens(target_name)
    matched_indices: list[int] = []
    for mesh_index, mesh in enumerate(meshes):
        mesh_text = f"{getattr(mesh, 'name', '')} {getattr(mesh, 'material_name', '')}".strip()
        mesh_key = mesh_text.lower()
        if target_key and target_key in mesh_key:
            matched_indices.append(mesh_index)
            continue
        if target_tokens and (target_tokens & _semantic_tokens(mesh_text)):
            matched_indices.append(mesh_index)
    if matched_indices:
        return tuple(matched_indices)
    return tuple(
        int(getattr(mapping, "target_submesh_index", -1))
        for mapping in tuple(current_mappings or ())
        if getattr(mapping, "target_submesh_name", None) == target_name
        and 0 <= int(getattr(mapping, "target_submesh_index", -1)) < len(meshes)
    )


def mapped_source_indices(current_mappings: Sequence[object]) -> set[int]:
    return {
        int(source_index)
        for mapping in tuple(current_mappings or ())
        for source_index in tuple(getattr(mapping, "source_submesh_indices", ()) or ())
    }


def independent_parts(
    *,
    replacement_mesh: object | None,
    independent_output_source_indices: set[int],
    preview_only_source_indices: set[int],
    current_mappings: Sequence[object],
    source_part_adjustments: Mapping[int, object],
    default_adjustment: Callable[[int], object],
    is_marker_source: Callable[[object], bool],
    source_display_name: Callable[[int], str],
    independent_part_type: Callable[..., object],
    include_preview_only: bool = False,
) -> tuple[object, ...]:
    if replacement_mesh is None:
        return ()
    mapped_indices = mapped_source_indices(current_mappings)
    source_indices = set(independent_output_source_indices)
    if include_preview_only:
        source_indices.update(preview_only_source_indices)
    parts: list[object] = []
    submeshes = tuple(getattr(replacement_mesh, "submeshes", ()) or ())
    for source_index in sorted(source_indices):
        if source_index in mapped_indices and source_index not in preview_only_source_indices:
            continue
        if source_index < 0 or source_index >= len(submeshes):
            continue
        source = submeshes[source_index]
        if is_marker_source(source):
            continue
        adjustment = source_part_adjustments.get(source_index, default_adjustment(source_index))
        if not bool(getattr(adjustment, "enabled", True)):
            continue
        label = source_display_name(source_index)
        material_name = str(getattr(source, "material", "") or getattr(source, "name", "") or label).strip()
        parts.append(
            independent_part_type(
                source_submesh_index=source_index,
                label=label,
                material_name=material_name,
                enabled=True,
                preview_only=source_index in preview_only_source_indices,
            )
        )
    return tuple(parts)


def unmapped_appended_source_indices(
    *,
    replacement_mesh: object | None,
    appended_source_indices: set[int],
    current_mappings: Sequence[object],
    source_part_adjustments: Mapping[int, object],
    default_adjustment: Callable[[int], object],
    is_marker_source: Callable[[object], bool],
) -> tuple[int, ...]:
    if replacement_mesh is None or not appended_source_indices:
        return ()
    mapped_indices = mapped_source_indices(current_mappings)
    unmapped_indices: list[int] = []
    submeshes = tuple(getattr(replacement_mesh, "submeshes", ()) or ())
    for source_index in sorted(appended_source_indices):
        if source_index in mapped_indices:
            continue
        if source_index < 0 or source_index >= len(submeshes):
            continue
        submesh = submeshes[source_index]
        adjustment = source_part_adjustments.get(source_index, default_adjustment(source_index))
        if not bool(getattr(adjustment, "enabled", True)) or is_marker_source(submesh):
            continue
        unmapped_indices.append(source_index)
    return tuple(unmapped_indices)


def preview_model_in_original_frame(
    parsed_mesh: object,
    *,
    normalization_center: Sequence[float],
    normalization_scale: float,
    source_indices: Sequence[int] | None = None,
    source_index_map: dict[int, int] | None = None,
    parsed_submesh_index_map: dict[int, int] | None = None,
) -> ModelPreviewData:
    native_preview = _preview_model_in_original_frame_native(
        parsed_mesh,
        normalization_center=normalization_center,
        normalization_scale=normalization_scale,
        source_indices=source_indices,
        source_index_map=source_index_map,
        parsed_submesh_index_map=parsed_submesh_index_map,
    )
    if native_preview is not None:
        return native_preview
    return _preview_model_in_original_frame_python_reference(
        parsed_mesh,
        normalization_center=normalization_center,
        normalization_scale=normalization_scale,
        source_indices=source_indices,
        source_index_map=source_index_map,
        parsed_submesh_index_map=parsed_submesh_index_map,
    )


def _preview_model_in_original_frame_python_reference(
    parsed_mesh: object,
    *,
    normalization_center: Sequence[float],
    normalization_scale: float,
    source_indices: Sequence[int] | None = None,
    source_index_map: dict[int, int] | None = None,
    parsed_submesh_index_map: dict[int, int] | None = None,
) -> ModelPreviewData:
    center = tuple(normalization_center or (0.0, 0.0, 0.0))
    scale = float(normalization_scale or 1.0)
    preview_meshes: list[ModelPreviewMesh] = []
    for submesh_position, submesh in enumerate(getattr(parsed_mesh, "submeshes", ()) or ()):
        vertices = list(getattr(submesh, "vertices", ()) or ())
        faces = list(getattr(submesh, "faces", ()) or ())
        if not vertices or not faces:
            continue
        source_submesh_index = submesh_position
        if source_indices is not None and submesh_position < len(source_indices):
            source_submesh_index = int(source_indices[submesh_position])
        indices: list[int] = []
        for face in faces:
            indices.extend(int(index) for index in face[:3])
        preview_meshes.append(
            ModelPreviewMesh(
                material_name=str(getattr(submesh, "material", "") or getattr(submesh, "name", "") or ""),
                texture_name=str(getattr(submesh, "texture", "") or ""),
                positions=[
                    (
                        (float(vertex[0]) - float(center[0])) * scale,
                        (float(vertex[1]) - float(center[1])) * scale,
                        (float(vertex[2]) - float(center[2])) * scale,
                    )
                    for vertex in vertices
                ],
                texture_coordinates=[
                    tuple(uv)
                    for uv in (getattr(submesh, "uvs", ()) or ())[: len(vertices)]
                ],
                normals=[
                    tuple(normal)
                    for normal in (getattr(submesh, "normals", ()) or ())[: len(vertices)]
                ],
                indices=indices,
                source_submesh_index=source_submesh_index,
                source_vertex_range_start=0,
                source_vertex_range_count=len(vertices),
                source_face_range_start=0,
                source_face_range_count=len(faces),
                preview_double_sided=bool(
                    getattr(submesh, "preview_double_sided", False)
                    or getattr(submesh, "double_sided", False)
                ),
            )
        )
        if parsed_submesh_index_map is not None:
            parsed_submesh_index_map[submesh_position] = len(preview_meshes) - 1
        if source_indices is not None and source_index_map is not None and submesh_position < len(source_indices):
            source_index_map[int(source_indices[submesh_position])] = len(preview_meshes) - 1
    vertex_count = sum(len(mesh.positions) for mesh in preview_meshes)
    face_count = sum(len(mesh.indices) // 3 for mesh in preview_meshes)
    return ModelPreviewData(
        path=str(getattr(parsed_mesh, "path", "") or ""),
        format=str(getattr(parsed_mesh, "format", "") or ""),
        summary=f"{len(preview_meshes)} mapped mesh part(s), {vertex_count:,} vertices, {face_count:,} faces",
        mesh_count=len(preview_meshes),
        vertex_count=vertex_count,
        face_count=face_count,
        normalization_center=(float(center[0]), float(center[1]), float(center[2])),
        normalization_scale=scale,
        meshes=preview_meshes,
    )


def _preview_model_in_original_frame_native(
    parsed_mesh: object,
    *,
    normalization_center: Sequence[float],
    normalization_scale: float,
    source_indices: Sequence[int] | None = None,
    source_index_map: dict[int, int] | None = None,
    parsed_submesh_index_map: dict[int, int] | None = None,
) -> ModelPreviewData | None:
    try:
        from cdmw.modding.mesh_native_core import build_native_preview_model_in_original_frame
    except Exception:
        return None
    report = build_native_preview_model_in_original_frame(
        parsed_mesh,
        normalization_center=normalization_center,
        normalization_scale=normalization_scale,
        source_indices=source_indices,
    )
    if not isinstance(report, Mapping):
        return None
    raw_meshes = report.get("meshes")
    if not isinstance(raw_meshes, list):
        return None
    submeshes = tuple(getattr(parsed_mesh, "submeshes", ()) or ())
    source_indices_tuple = tuple(source_indices or ())
    preview_meshes: list[ModelPreviewMesh] = []
    for raw_mesh in raw_meshes:
        if not isinstance(raw_mesh, Mapping):
            return None
        try:
            parsed_submesh_index = int(raw_mesh.get("parsed_submesh_index", -1))
            source_submesh_index = int(raw_mesh.get("source_submesh_index", parsed_submesh_index))
        except (TypeError, ValueError, OverflowError):
            return None
        if parsed_submesh_index < 0 or parsed_submesh_index >= len(submeshes):
            return None
        submesh = submeshes[parsed_submesh_index]
        vertex_count = _nonnegative_int(raw_mesh.get("vertex_count"))
        face_count = _nonnegative_int(raw_mesh.get("face_count"))
        positions_binary = _native_preview_binary_descriptor(
            raw_mesh.get("positions_binary"),
            expected_count=vertex_count,
            components=3,
            kind="f64",
        )
        indices_binary = _native_preview_binary_descriptor(
            raw_mesh.get("indices_binary"),
            expected_count=face_count * 3,
            components=1,
            kind="i32",
        )
        positions = [] if positions_binary is not None else _tuple3_list(raw_mesh.get("positions"))
        indices = [] if indices_binary is not None else _int_list(raw_mesh.get("indices"))
        if positions_binary is None and not positions:
            continue
        if indices_binary is None and not indices:
            continue
        if positions and vertex_count <= 0:
            vertex_count = len(positions)
        if indices and face_count <= 0:
            face_count = len(indices) // 3
        texture_coordinates_binary = _native_preview_binary_descriptor(
            raw_mesh.get("texture_coordinates_binary"),
            expected_count=_native_preview_descriptor_count(raw_mesh.get("texture_coordinates_binary"), vertex_count),
            components=2,
            kind="f64",
        )
        normals_binary = _native_preview_binary_descriptor(
            raw_mesh.get("normals_binary"),
            expected_count=_native_preview_descriptor_count(raw_mesh.get("normals_binary"), vertex_count),
            components=3,
            kind="f64",
        )
        source_vertex_indices_binary = _native_preview_binary_descriptor(
            raw_mesh.get("source_vertex_indices_binary"),
            expected_count=vertex_count,
            components=1,
            kind="i32",
        )
        source_face_indices_binary = _native_preview_binary_descriptor(
            raw_mesh.get("source_face_indices_binary"),
            expected_count=face_count,
            components=1,
            kind="i32",
        )
        source_vertex_range_start, source_vertex_range_count = _native_preview_range(
            raw_mesh,
            start_key="source_vertex_start",
            count_key="source_vertex_count",
            expected_count=vertex_count,
            disabled=source_vertex_indices_binary is not None,
        )
        source_face_range_start, source_face_range_count = _native_preview_range(
            raw_mesh,
            start_key="source_face_start",
            count_key="source_face_count",
            expected_count=face_count,
            disabled=source_face_indices_binary is not None,
        )
        preview_meshes.append(
            ModelPreviewMesh(
                material_name=str(getattr(submesh, "material", "") or getattr(submesh, "name", "") or ""),
                texture_name=str(getattr(submesh, "texture", "") or ""),
                positions=positions,
                texture_coordinates=[] if texture_coordinates_binary is not None else _tuple2_list(raw_mesh.get("texture_coordinates")),
                normals=[] if normals_binary is not None else _tuple3_list(raw_mesh.get("normals")),
                indices=indices,
                positions_binary=positions_binary or {},
                texture_coordinates_binary=texture_coordinates_binary or {},
                normals_binary=normals_binary or {},
                indices_binary=indices_binary or {},
                source_submesh_index=source_submesh_index,
                source_vertex_indices=[] if source_vertex_indices_binary is not None else _int_list(raw_mesh.get("source_vertex_indices")),
                source_face_indices=[] if source_face_indices_binary is not None else _int_list(raw_mesh.get("source_face_indices")),
                source_vertex_indices_binary=source_vertex_indices_binary or {},
                source_face_indices_binary=source_face_indices_binary or {},
                source_vertex_range_start=source_vertex_range_start,
                source_vertex_range_count=source_vertex_range_count,
                source_face_range_start=source_face_range_start,
                source_face_range_count=source_face_range_count,
                preview_double_sided=bool(
                    getattr(submesh, "preview_double_sided", False)
                    or getattr(submesh, "double_sided", False)
                ),
            )
        )
        preview_index = len(preview_meshes) - 1
        if parsed_submesh_index_map is not None:
            parsed_submesh_index_map[parsed_submesh_index] = preview_index
        if source_indices is not None and source_index_map is not None and parsed_submesh_index < len(source_indices_tuple):
            source_index_map[source_submesh_index] = preview_index
    vertex_count = sum(_preview_mesh_vertex_count(mesh) for mesh in preview_meshes)
    face_count = sum(_preview_mesh_face_count(mesh) for mesh in preview_meshes)
    center = tuple(normalization_center or (0.0, 0.0, 0.0))
    scale = float(normalization_scale or 1.0)
    return ModelPreviewData(
        path=str(getattr(parsed_mesh, "path", "") or ""),
        format=str(getattr(parsed_mesh, "format", "") or ""),
        summary=f"{len(preview_meshes)} mapped mesh part(s), {vertex_count:,} vertices, {face_count:,} faces",
        mesh_count=len(preview_meshes),
        vertex_count=vertex_count,
        face_count=face_count,
        normalization_center=(float(center[0]), float(center[1]), float(center[2])),
        normalization_scale=scale,
        meshes=preview_meshes,
    )


def _nonnegative_int(value: object, default: int = 0) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if result >= 0 else default


def _native_preview_descriptor_count(value: object, default: int = 0) -> int:
    if not isinstance(value, Mapping):
        return default
    return _nonnegative_int(value.get("count"), default)


def _native_preview_range(
    raw_mesh: Mapping[object, object],
    *,
    start_key: str,
    count_key: str,
    expected_count: int,
    disabled: bool,
) -> tuple[int, int]:
    if disabled:
        return -1, 0
    try:
        raw_start = raw_mesh.get(start_key, -1)
        raw_count = raw_mesh.get(count_key, 0)
        start = int(raw_start if raw_start is not None else -1)
        count = int(raw_count if raw_count is not None else 0)
    except (TypeError, ValueError, OverflowError):
        return -1, 0
    if start < 0 or count <= 0 or count != int(expected_count):
        return -1, 0
    return start, count


def _native_preview_binary_descriptor(
    value: object,
    *,
    expected_count: int,
    components: int,
    kind: str,
) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    path = str(value.get("path") or "").strip()
    if not path:
        return None
    count = _native_preview_descriptor_count(value, expected_count)
    if count != expected_count:
        return None
    raw_components = value.get("components")
    try:
        parsed_components = int(raw_components) if raw_components is not None else components
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed_components != components:
        return None
    parsed_kind = str(value.get("type") or kind).strip().lower()
    if parsed_kind != kind:
        return None
    descriptor: dict[str, object] = {
        "path": path,
        "count": count,
        "components": components,
        "type": kind,
    }
    if bool(value.get("delete_after")):
        descriptor["delete_after"] = True
    return descriptor


def _preview_mesh_vertex_count(mesh: object) -> int:
    positions = getattr(mesh, "positions", ()) or ()
    if positions:
        return len(positions)
    return _native_preview_descriptor_count(getattr(mesh, "positions_binary", None), 0)


def _preview_mesh_face_count(mesh: object) -> int:
    indices = getattr(mesh, "indices", ()) or ()
    if indices:
        return len(indices) // 3
    return _native_preview_descriptor_count(getattr(mesh, "indices_binary", None), 0) // 3


def _tuple3_list(value: object) -> list[tuple[float, float, float]]:
    if not isinstance(value, list):
        return []
    result: list[tuple[float, float, float]] = []
    for item in value:
        if not isinstance(item, (tuple, list)) or len(item) < 3:
            return []
        try:
            result.append((float(item[0]), float(item[1]), float(item[2])))
        except (TypeError, ValueError, OverflowError):
            return []
    return result


def _tuple2_list(value: object) -> list[tuple[float, float]]:
    if not isinstance(value, list):
        return []
    result: list[tuple[float, float]] = []
    for item in value:
        if not isinstance(item, (tuple, list)) or len(item) < 2:
            return []
        try:
            result.append((float(item[0]), float(item[1])))
        except (TypeError, ValueError, OverflowError):
            return []
    return result


def _int_list(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError, OverflowError):
            return []
    return result


def source_preview_geometry_key(
    current_mappings: Sequence[object],
    source_part_adjustments: Sequence[object],
    original_part_copies: Sequence[object],
    *,
    alignment_mode: str,
    scale_to_length: bool,
    flip: bool,
    rotate_xyz: Sequence[float],
    scale_xyz: Sequence[float],
    offset_xyz: Sequence[float],
    texture_uv_payload: object,
    mesh_edit_revision: int,
    source_geometry_revision: int,
    independent_output_source_indices: set[int],
    preview_only_source_indices: set[int],
) -> str:
    adjustments = []
    for adjustment in tuple(source_part_adjustments or ()):
        adjustments.append(
            (
                int(getattr(adjustment, "source_submesh_index", 0)),
                bool(getattr(adjustment, "enabled", True)),
                tuple(float(value) for value in getattr(adjustment, "offset_xyz", ()) or ()),
                tuple(float(value) for value in getattr(adjustment, "rotate_xyz_degrees", ()) or ()),
                tuple(float(value) for value in getattr(adjustment, "scale_xyz", ()) or ()),
                float(getattr(adjustment, "uniform_scale", 1.0)),
                str(getattr(adjustment, "material_role", "") or ""),
                tuple(int(value) for value in tuple(getattr(adjustment, "emissive_color_rgb", ()) or ())),
            )
        )
    payload = {
        "mode": str(alignment_mode or "grid_flat"),
        "scale_to_length": bool(scale_to_length),
        "flip": bool(flip),
        "rotate": [float(value) for value in tuple(rotate_xyz or ())],
        "scale": [float(value) for value in tuple(scale_xyz or ())],
        "offset": [float(value) for value in tuple(offset_xyz or ())],
        "mappings": [
            (
                int(getattr(mapping, "target_submesh_index", 0)),
                tuple(int(index) for index in getattr(mapping, "source_submesh_indices", ()) or ()),
            )
            for mapping in tuple(current_mappings or ())
        ],
        "adjustments": adjustments,
        "copies": [
            (
                int(getattr(copy, "original_submesh_index", 0)),
                str(getattr(copy, "label", "") or ""),
                bool(getattr(copy, "keep_original_placement", False)),
            )
            for copy in tuple(original_part_copies or ())
        ],
        "texture_uv": texture_uv_payload,
        "mesh_edit_revision": int(mesh_edit_revision or 0),
        "source_geometry_revision": int(source_geometry_revision or 0),
        "preview_quality": "normal",
        "independent_sources": sorted(int(index) for index in independent_output_source_indices),
        "preview_only_sources": sorted(int(index) for index in preview_only_source_indices),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def selected_part_preview_indices(
    preview_model: object,
    *,
    source_index: int,
    highlighted_source_indices: set[int],
    mapped_preview: bool,
    current_mappings: Sequence[object],
    direct_source_preview_index_map: Mapping[int, int],
    source_overlay_preview_index_map: Mapping[int, int],
    preview_target_mesh_indices: Callable[[object, str, Sequence[int], bool, Sequence[object]], Sequence[int]],
) -> tuple[int, ...] | None:
    source_indices = [source_index] if source_index >= 0 else sorted(highlighted_source_indices)
    if not source_indices:
        return None
    meshes = tuple(getattr(preview_model, "meshes", ()) or ())
    if not mapped_preview:
        preview_indices: list[int] = []
        if direct_source_preview_index_map:
            for current_source_index in source_indices:
                mapped_index = direct_source_preview_index_map.get(current_source_index)
                if mapped_index is not None and 0 <= mapped_index < len(meshes):
                    preview_indices.append(int(mapped_index))
        else:
            preview_indices.extend(int(index) for index in source_indices if 0 <= int(index) < len(meshes))
        return tuple(sorted(set(preview_indices)))
    target_indices: set[int] = set()
    for current_source_index in source_indices:
        overlay_index = source_overlay_preview_index_map.get(current_source_index)
        if overlay_index is not None:
            if 0 <= overlay_index < len(meshes):
                target_indices.add(int(overlay_index))
            continue
        for mapping in tuple(current_mappings or ()):
            if current_source_index not in tuple(getattr(mapping, "source_submesh_indices", ()) or ()):
                continue
            target_indices.update(
                int(index)
                for index in preview_target_mesh_indices(
                    preview_model,
                    str(getattr(mapping, "target_submesh_name", "") or ""),
                    [current_source_index],
                    True,
                    current_mappings,
                )
            )
    return tuple(sorted(index for index in target_indices if 0 <= index < len(meshes)))


__all__ = [
    "independent_parts",
    "mapped_source_indices",
    "preview_model_in_original_frame",
    "preview_target_mesh_indices",
    "selected_part_preview_indices",
    "source_preview_geometry_key",
    "unmapped_appended_source_indices",
]
