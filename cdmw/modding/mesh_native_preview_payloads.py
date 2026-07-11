from __future__ import annotations

from typing import Iterable, Mapping

from cdmw.modding.mesh_native_binary_io import (
    _native_binary_descriptor,
    _read_f64_binary_report_payload,
    _read_i32_binary_report_payload,
    _read_i32_components_binary_report_payload,
)
from cdmw.modding.mesh_native_core_blend_helpers import _int_list, _vertex_blends
from cdmw.modding.mesh_native_core_payload_helpers import _index


def _changed_vertex_range(value: object, vertex_count: int) -> tuple[int, int] | None:
    if isinstance(value, Mapping):
        for start_key, count_key in (
            ("changed_vertex_start", "changed_vertex_count"),
            ("source_vertex_start", "source_vertex_count"),
        ):
            start = _index(value.get(start_key))
            count = _index(value.get(count_key))
            if start is None and count is None:
                continue
            if start is None or count is None or start < 0 or count <= 0 or start + count > vertex_count:
                return None
            return start, count
        return None
    return _contiguous_vertex_range(value, vertex_count)


def _changed_vertices_binary_descriptor(value: object, vertex_count: int) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    if "changed_vertices_binary" in value:
        descriptor = value.get("changed_vertices_binary")
    elif "source_vertex_indices_binary" in value:
        descriptor = value.get("source_vertex_indices_binary")
    elif "path" in value:
        descriptor = value
    else:
        return None
    if not isinstance(descriptor, Mapping):
        return None
    count = _index(descriptor.get("count"))
    if count is None or count <= 0 or count > vertex_count:
        return None
    return _native_binary_descriptor(descriptor, expected_count=count, components=1, kind="i32")


def _iter_valid_changed_vertex_indices(value: object, vertex_count: int) -> Iterable[int]:
    if value is None:
        return
    try:
        iterator = iter(value)  # type: ignore[arg-type]
    except TypeError:
        return
    for raw_index in iterator:
        index = _index(raw_index)
        if index is not None and 0 <= index < vertex_count:
            yield index


def _contiguous_vertex_range(value: object, vertex_count: int) -> tuple[int, int] | None:
    if not isinstance(value, range) or value.step != 1:
        return None
    if value.start < 0 or value.stop > vertex_count or value.stop <= value.start:
        return None
    return int(value.start), int(value.stop - value.start)


def _native_preview_triangle_group(value: object, submesh_index: int) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    if str(value.get("preview_backend") or "") != "cdmw_mesh_core":
        return None
    source_index = _index(value.get("source_submesh_index"))
    if source_index != submesh_index:
        return None
    group: dict[str, object] = {"preview_backend": "cdmw_mesh_core", "source_submesh_index": submesh_index}
    source_vertices = _int_list(value.get("source_vertex_indices"))
    source_vertex_count = len(source_vertices)
    source_vertex_start = _index(value.get("source_vertex_start"))
    source_vertex_range_count = _index(value.get("source_vertex_count"))
    has_source_vertex_range = (
        source_vertex_start is not None
        and source_vertex_start >= 0
        and source_vertex_range_count is not None
        and source_vertex_range_count > 0
    )
    raw_source_vertices_binary = value.get("source_vertex_indices_binary")
    if source_vertex_count == 0 and isinstance(raw_source_vertices_binary, Mapping):
        source_vertex_count = _index(raw_source_vertices_binary.get("count")) or 0
    if source_vertex_count == 0 and has_source_vertex_range:
        source_vertex_count = int(source_vertex_range_count or 0)
    if source_vertices:
        group["source_vertex_indices"] = source_vertices
    source_vertices_binary = _native_binary_descriptor(raw_source_vertices_binary, expected_count=source_vertex_count, components=1, kind="i32")
    if source_vertices_binary is not None:
        group["source_vertex_indices_binary"] = source_vertices_binary
    elif has_source_vertex_range:
        group["source_vertex_start"] = int(source_vertex_start or 0)
        group["source_vertex_count"] = int(source_vertex_range_count or 0)

    source_faces = _int_list(value.get("source_face_indices"))
    source_face_count = len(source_faces)
    source_face_start = _index(value.get("source_face_start"))
    source_face_range_count = _index(value.get("source_face_count"))
    has_source_face_range = (
        source_face_start is not None
        and source_face_start >= 0
        and source_face_range_count is not None
        and source_face_range_count > 0
    )
    raw_source_faces_binary = value.get("source_face_indices_binary")
    if source_face_count == 0 and isinstance(raw_source_faces_binary, Mapping):
        source_face_count = _index(raw_source_faces_binary.get("count")) or 0
    if source_face_count == 0 and has_source_face_range:
        source_face_count = int(source_face_range_count or 0)
    if source_faces:
        group["source_face_indices"] = source_faces
    source_faces_binary = _native_binary_descriptor(raw_source_faces_binary, expected_count=source_face_count, components=1, kind="i32")
    if source_faces_binary is not None:
        group["source_face_indices_binary"] = source_faces_binary
    elif has_source_face_range:
        group["source_face_start"] = int(source_face_start or 0)
        group["source_face_count"] = int(source_face_range_count or 0)

    positions = value.get("positions")
    positions_binary = _native_binary_descriptor(value.get("positions_binary"), expected_count=source_vertex_count, components=3, kind="f64")
    if positions_binary is None:
        if not isinstance(positions, list) or len(positions) != source_vertex_count * 3:
            return None
        group["positions"] = list(positions)
    else:
        group["positions_binary"] = positions_binary

    normals = value.get("normals")
    normals_binary = _native_binary_descriptor(value.get("normals_binary"), expected_count=source_vertex_count, components=3, kind="f64")
    if normals_binary is not None:
        group["normals_binary"] = normals_binary
    elif isinstance(normals, list):
        if normals and len(normals) != source_vertex_count * 3:
            return None
        group["normals"] = list(normals)
    elif source_vertex_count > 0:
        return None

    uvs = value.get("uvs")
    uvs_binary = _native_binary_descriptor(value.get("uvs_binary"), expected_count=source_vertex_count, components=2, kind="f64")
    if uvs_binary is not None:
        group["uvs_binary"] = uvs_binary
    elif isinstance(uvs, list):
        if uvs and len(uvs) != source_vertex_count * 2:
            return None
        group["uvs"] = list(uvs)
    elif source_vertex_count > 0:
        return None

    indices = _int_list(value.get("indices"))
    raw_indices_binary = value.get("indices_binary")
    index_count = len(indices)
    if index_count == 0 and isinstance(raw_indices_binary, Mapping):
        index_count = _index(raw_indices_binary.get("count")) or 0
    if indices:
        group["indices"] = indices
    indices_binary = _native_binary_descriptor(raw_indices_binary, expected_count=index_count, components=1, kind="i32")
    if indices_binary is not None:
        group["indices_binary"] = indices_binary
    elif index_count > 0 and not indices:
        return None
    if source_vertex_count == 0:
        for key in ("source_vertex_indices", "source_face_indices", "positions", "normals", "uvs", "indices"):
            group.setdefault(key, [])
    return group


def _native_preview_vertex_update_group(value: object, submesh_index: int) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    if str(value.get("preview_backend") or "") != "cdmw_mesh_core":
        return None
    source_index = _index(value.get("source_submesh_index"))
    if source_index != submesh_index:
        return None
    source_vertices = _int_list(value.get("source_vertex_indices"))
    raw_source_vertices_binary = value.get("source_vertex_indices_binary")
    source_vertex_count = len(source_vertices)
    source_vertex_start = _index(value.get("source_vertex_start"))
    source_vertex_range_count = _index(value.get("source_vertex_count"))
    has_source_vertex_range = (
        source_vertex_start is not None
        and source_vertex_start >= 0
        and source_vertex_range_count is not None
        and source_vertex_range_count > 0
    )
    if source_vertex_count == 0 and isinstance(raw_source_vertices_binary, Mapping):
        source_vertex_count = _index(raw_source_vertices_binary.get("count")) or 0
    if source_vertex_count == 0 and has_source_vertex_range:
        source_vertex_count = int(source_vertex_range_count or 0)
    source_vertices_binary = _native_binary_descriptor(
        raw_source_vertices_binary,
        expected_count=source_vertex_count,
        components=1,
        kind="i32",
    )
    if source_vertex_count > 0 and not source_vertices and source_vertices_binary is None and not has_source_vertex_range:
        return None
    positions = value.get("positions")
    positions_binary = _native_binary_descriptor(
        value.get("positions_binary"),
        expected_count=source_vertex_count,
        components=3,
        kind="f64",
    )
    normals = value.get("normals")
    normals_binary = _native_binary_descriptor(
        value.get("normals_binary"),
        expected_count=source_vertex_count,
        components=3,
        kind="f64",
    )
    uvs = value.get("uvs")
    uvs_binary = _native_binary_descriptor(
        value.get("uvs_binary"),
        expected_count=source_vertex_count,
        components=2,
        kind="f64",
    )
    if positions_binary is None and not isinstance(positions, list):
        return None
    if isinstance(positions, list) and len(positions) != source_vertex_count * 3:
        return None
    if isinstance(normals, list) and normals and len(normals) != source_vertex_count * 3:
        return None
    if isinstance(uvs, list) and uvs and len(uvs) != source_vertex_count * 2:
        return None
    group: dict[str, object] = {
        "preview_backend": "cdmw_mesh_core",
        "source_submesh_index": submesh_index,
    }
    if source_vertices_binary is not None:
        group["source_vertex_indices_binary"] = source_vertices_binary
    elif has_source_vertex_range:
        group["source_vertex_start"] = int(source_vertex_start or 0)
        group["source_vertex_count"] = int(source_vertex_range_count or 0)
    else:
        group["source_vertex_indices"] = source_vertices
    if positions_binary is not None:
        group["positions_binary"] = positions_binary
    else:
        group["positions"] = list(positions or [])
    if normals_binary is not None:
        group["normals_binary"] = normals_binary
    else:
        group["normals"] = list(normals) if isinstance(normals, list) else []
    if uvs_binary is not None:
        group["uvs_binary"] = uvs_binary
    else:
        group["uvs"] = list(uvs) if isinstance(uvs, list) else []
    return group


def _copy_vertex_indices_from_report_item(item: Mapping[str, object], output_vertex_count: int) -> list[int] | None:
    raw_copy_binary = item.get("copy_vertex_indices_binary")
    if isinstance(raw_copy_binary, Mapping):
        return _read_i32_binary_report_payload(raw_copy_binary, expected_count=output_vertex_count)
    return _int_list(item.get("copy_vertex_indices"))


def _vertex_blends_from_report_item(item: Mapping[str, object]) -> dict[int, tuple[int, int, float]] | None:
    raw_indices_binary = item.get("vertex_blend_indices_binary")
    raw_factors_binary = item.get("vertex_blend_factors_binary")
    if isinstance(raw_indices_binary, Mapping) or isinstance(raw_factors_binary, Mapping):
        if not isinstance(raw_indices_binary, Mapping) or not isinstance(raw_factors_binary, Mapping):
            return None
        count = _index(raw_indices_binary.get("count"))
        if count is None or count < 0:
            return None
        if _index(raw_factors_binary.get("count")) != count:
            return None
        indices = _read_i32_components_binary_report_payload(raw_indices_binary, expected_count=count, components=3)
        factors = _read_f64_binary_report_payload(raw_factors_binary, expected_count=count)
        if indices is None or factors is None:
            return None
        return {
            int(index): (int(left), int(right), max(0.0, min(1.0, float(factor))))
            for (index, left, right), factor in zip(indices, factors)
        }
    return _vertex_blends(item.get("vertex_blends"))
