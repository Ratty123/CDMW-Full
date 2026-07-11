from __future__ import annotations

from importlib import import_module
from typing import Mapping, Sequence

from cdmw.modding.mesh_native_binary_io import (
    _native_binary_descriptor,
    _read_int_binary_report_payload,
    _read_vec3_binary_report_payload,
)
from cdmw.modding.mesh_native_core_constants import Vec3
from cdmw.modding.mesh_native_core_payload_helpers import _index
from cdmw.modding.mesh_native_payloads import _contiguous_i32_range, _i32_range_report_values


def _vec3(value: object) -> Vec3:
    return import_module("cdmw.modding.mesh_native_core")._vec3(value)


def _native_history_vertex_delta(
    item: Mapping[str, object],
    submesh_index: int,
    changed_vertices: Sequence[int],
) -> dict[str, object] | None:
    native_sparse_snapshot_id = str(item.get("native_sparse_snapshot_id") or "").strip()
    if not changed_vertices:
        return None
    vertex_payload = _native_history_vertex_payload(changed_vertices)
    if not vertex_payload:
        return None
    before_positions_binary = item.get("before_positions_binary")
    if before_positions_binary is None:
        if native_sparse_snapshot_id:
            return {
                "source_submesh_index": int(submesh_index),
                **vertex_payload,
                "native_sparse_snapshot_id": native_sparse_snapshot_id,
            }
        raw_before_positions = item.get("before_positions")
        if isinstance(raw_before_positions, list) and len(raw_before_positions) == len(changed_vertices):
            return {
                "source_submesh_index": int(submesh_index),
                **vertex_payload,
                "before_positions": tuple(_vec3(position) for position in raw_before_positions),
            }
        return None
    descriptor = _native_binary_descriptor(
        before_positions_binary,
        expected_count=len(changed_vertices),
        components=3,
        kind="f64",
    )
    if descriptor is None:
        return None
    result: dict[str, object] = {
        "source_submesh_index": int(submesh_index),
        **vertex_payload,
        "before_positions_binary": descriptor,
    }
    if native_sparse_snapshot_id:
        result["native_sparse_snapshot_id"] = native_sparse_snapshot_id
    return result


def _native_history_vertex_payload(changed_vertices: Sequence[int]) -> dict[str, object]:
    if isinstance(changed_vertices, range):
        compact_range = _contiguous_i32_range(changed_vertices)
        if compact_range is not None:
            return {"vertex_index_start": compact_range[0], "vertex_index_count": compact_range[1]}
    return {"vertex_indices": tuple(int(index) for index in changed_vertices)}


def _native_history_delta_vertex_payload(delta: Mapping[str, object]) -> dict[str, object]:
    start = _index(delta.get("vertex_index_start"))
    count = _index(delta.get("vertex_index_count"))
    if start is not None and count is not None and start >= 0 and count > 0:
        return {"vertex_index_start": start, "vertex_index_count": count}
    return {"vertex_indices": tuple(delta.get("vertex_indices") or ())}


def _vertex_indices_from_history_descriptor(value: Mapping[str, object], vertex_count: int) -> Sequence[int] | None:
    ranged = _i32_range_report_values(
        value,
        start_key="vertex_index_start",
        count_key="vertex_index_count",
        max_count=max(0, int(vertex_count)),
    )
    if ranged is not None:
        return ranged
    raw_indices = value.get("vertex_indices")
    if not isinstance(raw_indices, (tuple, list, range)):
        return None
    indices: list[int] = []
    seen_indices: set[int] = set()
    for raw_vertex_index in raw_indices:
        vertex_index = _index(raw_vertex_index)
        if vertex_index is None or vertex_index < 0 or vertex_index >= vertex_count or vertex_index in seen_indices:
            return None
        indices.append(vertex_index)
        seen_indices.add(vertex_index)
    return tuple(indices) if indices else None


def native_mesh_history_delta_positions(raw_delta: object) -> tuple[Vec3, ...] | None:
    if not isinstance(raw_delta, Mapping):
        return None
    raw_indices = _vertex_indices_from_history_descriptor(raw_delta, 1 << 30)
    if raw_indices is None:
        return None
    raw_positions = raw_delta.get("before_positions")
    if isinstance(raw_positions, (tuple, list)):
        positions = tuple(_vec3(position) for position in raw_positions)
        return positions if len(positions) == len(raw_indices) else None
    raw_positions_binary = raw_delta.get("before_positions_binary")
    positions = _read_vec3_binary_report_payload(raw_positions_binary, expected_count=len(raw_indices))
    return tuple(positions) if positions is not None else None


def _changed_vertices_from_report_item(item: Mapping[str, object], vertex_count: int) -> Sequence[int] | None:
    if "changed_vertex_start" in item or "changed_vertex_count" in item:
        try:
            raw_start = item.get("changed_vertex_start", -1)
            raw_count = item.get("changed_vertex_count", 0)
            start = int(raw_start if raw_start is not None else -1)
            count = int(raw_count if raw_count is not None else 0)
        except (TypeError, ValueError, OverflowError):
            return None
        if count == 0 and start >= 0:
            return range(start, start)
        if start < 0 or count < 0 or start + count > max(0, int(vertex_count)):
            return None
        return range(start, start + count)
    raw_changed_binary = item.get("changed_vertices_binary")
    raw_changed = item.get("changed_vertices")
    if isinstance(raw_changed_binary, Mapping):
        raw_values = _read_int_binary_report_payload(raw_changed_binary, max_count=vertex_count)
        if raw_values is None:
            return None
    elif isinstance(raw_changed, list):
        raw_values = raw_changed
    else:
        return None
    changed: list[int] = []
    seen: set[int] = set()
    for raw_index in raw_values:
        index = _index(raw_index)
        if index is not None and 0 <= index < vertex_count and index not in seen:
            changed.append(index)
            seen.add(index)
    return changed


def _changed_vertices_for_report(indices: Sequence[int] | None) -> Sequence[int] | set[int]:
    if not indices:
        return set()
    return indices if isinstance(indices, range) else set(indices)


def _bounded_changed_vertices(indices: Sequence[int] | set[int], vertex_count: int) -> Sequence[int] | set[int]:
    if isinstance(indices, range) and indices.step == 1:
        start = max(0, int(indices.start))
        stop = min(int(indices.stop), max(0, int(vertex_count)))
        if start >= stop:
            return range(0, 0)
        if start == indices.start and stop == indices.stop:
            return indices
        return range(start, stop)
    return {int(index) for index in indices if 0 <= int(index) < vertex_count}
