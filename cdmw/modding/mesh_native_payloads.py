from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Mapping, Sequence

from cdmw.modding.mesh_native_binary_io import _read_i32_binary_report_payload
from cdmw.modding.mesh_native_core_payload_helpers import _index


def _facade_attr(name: str):
    return getattr(import_module("cdmw.modding.mesh_native_core"), name)


def _write_edge_binary_payload(path: Path, edges: object) -> dict[str, object]:
    return _facade_attr("_write_edge_binary_payload")(path, edges)


def _write_int_binary_payload(path: Path, values: object) -> dict[str, object]:
    return _facade_attr("_write_int_binary_payload")(path, values)


def _contiguous_i32_range(values: Sequence[int], max_count: int | None = None) -> tuple[int, int] | None:
    if isinstance(values, range):
        if values.step != 1 or not values:
            return None
        start = int(values.start)
        count = len(values)
        if start < 0:
            return None
        if max_count is not None and start + count > max(0, int(max_count)):
            return None
        return start, count
    try:
        iterator = iter(values)
        first = int(next(iterator))
    except (StopIteration, TypeError, ValueError, OverflowError):
        return None
    start = first
    if start < 0:
        return None
    count = 1
    for offset, raw_value in enumerate(iterator, start=1):
        try:
            value = int(raw_value)
        except (TypeError, ValueError, OverflowError):
            return None
        if value != start + offset:
            return None
        count += 1
    if max_count is not None and start + count > max(0, int(max_count)):
        return None
    return start, count


def _is_identity_i32_sequence(values: Sequence[int]) -> bool:
    for offset, raw_value in enumerate(values):
        try:
            value = int(raw_value)
        except (TypeError, ValueError, OverflowError):
            return False
        if value != offset:
            return False
    return True


def _contiguous_i32_stride_range(values: Sequence[int]) -> tuple[int, int, int] | None:
    try:
        iterator = iter(values)
        start = int(next(iterator))
    except (StopIteration, TypeError, ValueError, OverflowError):
        return None
    if start < 0:
        return None
    try:
        second = int(next(iterator))
    except StopIteration:
        return start, 1, 1
    except (TypeError, ValueError, OverflowError):
        return None
    stride = second - start
    if stride <= 0:
        return None
    count = 2
    for offset, raw_value in enumerate(iterator, start=2):
        try:
            value = int(raw_value)
        except (TypeError, ValueError, OverflowError):
            return None
        if value < 0 or value != start + offset * stride:
            return None
        count += 1
    return start, count, stride


def _put_i32_range_or_binary_payload(
    item: dict[str, object],
    *,
    values: Sequence[int],
    start_key: str,
    count_key: str,
    binary_key: str,
    binary_path: Path,
    max_count: int | None = None,
) -> None:
    compact_range = _contiguous_i32_range(values, max_count=max_count)
    if compact_range is not None:
        start, count = compact_range
        item[start_key] = start
        item[count_key] = count
        return
    item[binary_key] = _write_int_binary_payload(binary_path, values)


def _put_source_vertex_map_payload(item: dict[str, object], prefix: Path, values: Sequence[int]) -> None:
    _put_i32_range_or_binary_payload(
        item,
        values=values,
        start_key="source_vertex_map_start",
        count_key="source_vertex_map_count",
        binary_key="source_vertex_map_binary",
        binary_path=prefix.with_name(prefix.name + "_source_vertex_map.bin"),
    )


def _put_source_vertex_indices_payload(item: dict[str, object], prefix: Path, values: Sequence[int]) -> None:
    _put_i32_range_or_binary_payload(
        item,
        values=values,
        start_key="source_vertex_start",
        count_key="source_vertex_count",
        binary_key="source_vertex_indices_binary",
        binary_path=prefix.with_name(prefix.name + "_source_vertices.bin"),
    )


def _put_source_vertex_offsets_payload(item: dict[str, object], prefix: Path | None, values: Sequence[int]) -> None:
    compact_range = _contiguous_i32_stride_range(values)
    if compact_range is not None:
        start, count, stride = compact_range
        item["source_vertex_offsets_start"] = start
        item["source_vertex_offsets_count"] = count
        item["source_vertex_offsets_stride"] = stride
        return
    if prefix is None:
        item["source_vertex_offsets"] = [int(value) for value in values]
        return
    item["source_vertex_offsets_binary"] = _write_int_binary_payload(
        prefix.with_name(prefix.name + "_source_vertex_offsets.bin"),
        values,
    )


def _put_source_face_indices_payload(item: dict[str, object], prefix: Path, values: Sequence[int]) -> None:
    _put_i32_range_or_binary_payload(
        item,
        values=values,
        start_key="source_face_start",
        count_key="source_face_count",
        binary_key="source_face_indices_binary",
        binary_path=prefix.with_name(prefix.name + "_source_faces.bin"),
    )


def _put_source_face_indices_json_payload(item: dict[str, object], values: Sequence[int]) -> None:
    compact_range = _contiguous_i32_range(values)
    if compact_range is not None:
        item["source_face_start"], item["source_face_count"] = compact_range
        return
    item["source_face_indices"] = [int(index) for index in values]


def _put_vertex_indices_payload(
    item: dict[str, object],
    prefix: Path,
    values: Sequence[int],
    *,
    max_count: int | None = None,
) -> None:
    _put_i32_range_or_binary_payload(
        item,
        values=values,
        start_key="vertex_index_start",
        count_key="vertex_index_count",
        binary_key="vertex_indices_binary",
        binary_path=prefix.with_name(prefix.name + "_indices.bin"),
        max_count=max_count,
    )


def _put_selected_vertices_payload(
    item: dict[str, object],
    prefix: Path,
    values: Sequence[int],
    *,
    max_count: int | None = None,
) -> None:
    _put_i32_range_or_binary_payload(
        item,
        values=values,
        start_key="selected_vertex_start",
        count_key="selected_vertex_count",
        binary_key="selected_vertices_binary",
        binary_path=prefix.with_name(prefix.name + "_selected.bin"),
        max_count=max_count,
    )


def _selected_edge_values(raw_edges: object, vertex_count: int) -> tuple[tuple[int, int], ...]:
    vertex_limit = max(0, int(vertex_count))
    if vertex_limit <= 0:
        return ()
    selected: set[tuple[int, int]] = set()
    try:
        values = iter(raw_edges or ())  # type: ignore[arg-type]
    except TypeError:
        return ()
    for raw_edge in values:
        if not isinstance(raw_edge, (tuple, list)) or len(raw_edge) < 2:
            continue
        left = _index(raw_edge[0])
        right = _index(raw_edge[1])
        if left is None or right is None or left == right:
            continue
        if 0 <= left < vertex_limit and 0 <= right < vertex_limit:
            selected.add((min(left, right), max(left, right)))
    return tuple(sorted(selected))


def _selected_face_values(raw_faces: object, face_count: int) -> Sequence[int]:
    face_limit = max(0, int(face_count))
    if face_limit <= 0:
        return ()
    if isinstance(raw_faces, range) and raw_faces.step == 1:
        start = max(0, int(raw_faces.start))
        stop = min(face_limit, int(raw_faces.stop))
        return range(start, stop) if start < stop else ()
    selected: set[int] = set()
    try:
        values = iter(raw_faces or ())  # type: ignore[arg-type]
    except TypeError:
        return ()
    for raw_value in values:
        index = _index(raw_value)
        if index is not None and 0 <= index < face_limit:
            selected.add(index)
    return tuple(sorted(selected))


def _put_selected_edit_domain_payload(
    item: dict[str, object],
    prefix: Path,
    *,
    selected_vertices: object,
    selected_edges: object,
    selected_faces: object,
    selected_all_vertices: bool,
    vertex_count: int,
    face_count: int,
) -> bool:
    wrote_selection = False
    kept_vertices = _selected_vertex_values(selected_vertices, vertex_count)
    if kept_vertices:
        _put_selected_vertices_payload(item, prefix, kept_vertices, max_count=vertex_count)
        wrote_selection = True
    kept_edges = _selected_edge_values(selected_edges, vertex_count)
    if kept_edges:
        item["selected_edges_binary"] = _write_edge_binary_payload(prefix.with_name(prefix.name + "_selected_edges.bin"), kept_edges)
        wrote_selection = True
    kept_faces = _selected_face_values(selected_faces, face_count)
    if kept_faces:
        _put_i32_range_or_binary_payload(
            item,
            values=kept_faces,
            start_key="selected_face_start",
            count_key="selected_face_count",
            binary_key="selected_faces_binary",
            binary_path=prefix.with_name(prefix.name + "_selected_faces.bin"),
            max_count=face_count,
        )
        wrote_selection = True
    if selected_all_vertices:
        item["selected_all_vertices"] = True
        wrote_selection = True
    return wrote_selection


def _selected_vertex_values(raw_values: object, vertex_count: int) -> Sequence[int]:
    vertex_limit = max(0, int(vertex_count))
    if vertex_limit <= 0:
        return ()
    if isinstance(raw_values, range) and raw_values.step == 1:
        start = max(0, int(raw_values.start))
        stop = min(vertex_limit, int(raw_values.stop))
        return range(start, stop) if start < stop else ()
    selected: set[int] = set()
    try:
        values = iter(raw_values or ())  # type: ignore[arg-type]
    except TypeError:
        return ()
    for raw_value in values:
        index = _index(raw_value)
        if index is not None and 0 <= index < vertex_limit:
            selected.add(index)
    return tuple(sorted(selected))


def _i32_range_report_values(
    item: Mapping[object, object],
    *,
    start_key: str,
    count_key: str,
    max_count: int,
) -> Sequence[int] | None:
    try:
        raw_start = item.get(start_key, -1)
        raw_count = item.get(count_key, 0)
        start = int(raw_start if raw_start is not None else -1)
        count = int(raw_count if raw_count is not None else 0)
    except (TypeError, ValueError, OverflowError):
        return None
    if start < 0 or count <= 0 or start + count > max(0, int(max_count)):
        return None
    return range(start, start + count)


def _i32_stride_range_report_values(item: Mapping[object, object], *, max_count: int) -> Sequence[int] | None:
    try:
        start = int(item.get("source_vertex_offsets_start", -1) or -1)
        count = int(item.get("source_vertex_offsets_count", 0) or 0)
        stride = int(item.get("source_vertex_offsets_stride", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        return None
    if start < 0 or count <= 0 or count > max(0, int(max_count)) or stride <= 0:
        return None
    return range(start, start + count * stride, stride)


def _source_vertex_map_report_values(item: Mapping[object, object], vertex_count: int) -> list[int] | None:
    raw_binary = item.get("source_vertex_map_binary")
    if isinstance(raw_binary, Mapping):
        values = _read_i32_binary_report_payload(raw_binary, expected_count=vertex_count)
        return values if values is not None and len(values) == vertex_count else None
    values_from_range = _i32_range_report_values(
        item,
        start_key="source_vertex_map_start",
        count_key="source_vertex_map_count",
        max_count=1 << 30,
    )
    if values_from_range is not None:
        values = list(values_from_range)
        return values if len(values) == vertex_count else None
    raw_values = item.get("source_vertex_map")
    if isinstance(raw_values, list):
        values = _int_list(raw_values)
        return values if len(values) == vertex_count else None
    return []


def _source_vertex_offsets_report_values(item: Mapping[object, object], vertex_count: int) -> list[int] | None:
    raw_binary = item.get("source_vertex_offsets_binary")
    if isinstance(raw_binary, Mapping):
        values = _read_i32_binary_report_payload(raw_binary, expected_count=vertex_count)
        return values if values is not None and len(values) == vertex_count else None
    values_from_range = _i32_stride_range_report_values(item, max_count=vertex_count)
    if values_from_range is not None:
        values = list(values_from_range)
        return values if len(values) == vertex_count else None
    raw_values = item.get("source_vertex_offsets")
    if isinstance(raw_values, list):
        values = _int_list(raw_values)
        return values if len(values) == vertex_count else None
    return []
