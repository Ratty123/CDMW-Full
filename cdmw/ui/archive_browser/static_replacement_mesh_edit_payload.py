"""Mesh-edit payload parsing helpers for static replacement previews."""

from __future__ import annotations

import math
import os
from array import array
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path

from cdmw.ui.archive_browser.static_replacement_mesh_edit_state import (
    mesh_edit_all_vertices_by_source,
    mesh_edit_can_edit_scope,
    mesh_edit_control_status_text,
    mesh_edit_has_index_groups,
    mesh_edit_index_group_count,
    mesh_edit_index_groups_as_sets,
    mesh_edit_inverted_vertex_selection,
    mesh_edit_mapping_keys,
    mesh_edit_merge_index_groups,
    mesh_edit_optional_sorted_indices,
    mesh_edit_scope_mode,
    mesh_edit_selection_depth_mode,
    mesh_edit_selection_mode,
    mesh_edit_selected_vertex_points,
    mesh_edit_selection_region_default_amount,
    mesh_edit_selection_status_text,
    mesh_edit_sorted_index_groups,
    mesh_edit_target_mode_for_tool,
    mesh_edit_tool,
    mesh_edit_tool_context,
    mesh_edit_topology_source_indices,
)

def _record_native_preview_fallback(mesh: object, operation: str, reason: str, **details: object) -> None:
    try:
        from cdmw.modding.mesh_native_core import record_native_mesh_core_fallback
    except Exception:
        return
    record_native_mesh_core_fallback(
        operation,
        reason,
        vertex_count=_nonnegative_int(getattr(mesh, "total_vertices", 0)),
        face_count=_nonnegative_int(getattr(mesh, "total_faces", 0)),
        **details,
    )


def _native_mesh_core_available_for_preview() -> bool:
    if os.environ.get("CDMW_DISABLE_NATIVE_MESH_CORE"):
        return False
    try:
        from cdmw.modding.mesh_native_core import native_mesh_core_available
    except Exception:
        return False
    try:
        return bool(native_mesh_core_available())
    except Exception:
        return False


def _allow_python_preview_fallback(
    mesh: object,
    operation: str,
    *,
    submesh_index: int,
    vertex_count: int = 0,
    face_count: int = 0,
    allow_python_fallback: bool = False,
) -> bool:
    if not allow_python_fallback:
        _record_native_preview_fallback(
            mesh,
            f"{operation}.blocked",
            "Python preview fallback disabled; native preview payload is required",
            submesh_index=submesh_index,
            source_vertex_count=_nonnegative_int(vertex_count),
            source_face_count=_nonnegative_int(face_count),
        )
        return False
    if not _native_mesh_core_available_for_preview():
        return True
    _record_native_preview_fallback(
        mesh,
        f"{operation}.blocked",
        "Python preview fallback blocked while native mesh core is available",
        submesh_index=submesh_index,
        source_vertex_count=_nonnegative_int(vertex_count),
        source_face_count=_nonnegative_int(face_count),
    )
    return False


def _nonnegative_int(value: object, fallback: int = 0) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    return result if result >= 0 else fallback


def _bounded_float(value: object, fallback: float, minimum: float | None = None, maximum: float | None = None) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        result = float(fallback)
    if minimum is not None:
        result = max(float(minimum), result)
    if maximum is not None:
        result = min(float(maximum), result)
    return result


def mesh_edit_stroke_id(payload: object) -> int:
    if not isinstance(payload, Mapping):
        return 0
    try:
        return int(payload.get("stroke_id", 0) or 0)
    except (TypeError, ValueError):
        return 0


def mesh_edit_payload_has_drag_motion(payload: Mapping[object, object]) -> bool:
    raw_delta = tuple(payload.get("delta") or (0.0, 0.0, 0.0))
    try:
        return any(abs(float(raw_delta[index])) > 1e-10 for index in range(3))
    except Exception:
        return False


def mesh_edit_payload_choice(
    payload: Mapping[object, object],
    key: str,
    fallback: object,
    allowed_values: Iterable[str],
) -> str:
    fallback_text = str(fallback or "").strip().lower()
    value = str(payload.get(key) or fallback_text).strip().lower()
    allowed = {str(item).strip().lower() for item in allowed_values}
    return value if value in allowed else fallback_text


def mesh_edit_payload_vector3(
    payload: Mapping[object, object],
    key: str,
    fallback: Sequence[object] = (0.0, 0.0, 0.0),
) -> tuple[float, float, float]:
    raw_value = payload.get(key, fallback)
    try:
        values = tuple(raw_value or fallback)  # type: ignore[arg-type]
    except TypeError:
        values = tuple(fallback)
    try:
        return (float(values[0]), float(values[1]), float(values[2]))
    except (TypeError, ValueError, IndexError, OverflowError):
        fallback_values = tuple(fallback)
        return (float(fallback_values[0]), float(fallback_values[1]), float(fallback_values[2]))


def mesh_edit_payload_float(
    payload: Mapping[object, object],
    key: str,
    fallback: float = 0.0,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    return _bounded_float(payload.get(key, fallback), fallback, minimum, maximum)


def mesh_edit_payload_int(
    payload: Mapping[object, object],
    key: str,
    fallback: int,
) -> int:
    try:
        return int(payload.get(key) or fallback)
    except (TypeError, ValueError):
        return int(fallback)


def mesh_edit_payload_vertex_weights(
    group: Mapping[object, object],
    vertex_indices: Iterable[int],
) -> dict[int, float]:
    ordered_vertices = [int(vertex_index) for vertex_index in vertex_indices]
    binary_weights = _mesh_edit_f32_payload_values(group, "source_vertex_weights_binary")
    if len(binary_weights) == len(ordered_vertices):
        weights: dict[int, float] = {}
        for vertex_index, raw_weight in zip(ordered_vertices, binary_weights):
            if not math.isfinite(raw_weight):
                continue
            weight_value = max(0.0, min(1.0, float(raw_weight)))
            if weight_value > 0.0:
                weights[vertex_index] = max(weights.get(vertex_index, 0.0), weight_value)
        return weights
    allowed_vertices = set(ordered_vertices)
    weights: dict[int, float] = {}
    for raw_weight_entry in group.get("source_vertex_weights") or ():
        try:
            raw_weight_index, raw_weight_value = raw_weight_entry  # type: ignore[misc]
            weight_index = int(raw_weight_index)
            weight_value = _bounded_float(raw_weight_value, 0.0, 0.0, 1.0)
        except (TypeError, ValueError, OverflowError):
            continue
        if weight_index in allowed_vertices and weight_value > 0.0:
            weights[weight_index] = max(weights.get(weight_index, 0.0), weight_value)
    return weights


def _mesh_edit_i32_payload_values(group: Mapping[object, object], json_key: str, binary_key: str) -> Sequence[int]:
    descriptor = group.get(binary_key)
    if isinstance(descriptor, Mapping):
        try:
            count = int(descriptor.get("count", 0) or 0)
            components = int(descriptor.get("components", 1) or 1)
            path = Path(str(descriptor.get("path") or ""))
        except (TypeError, ValueError, OSError):
            return []
        if count >= 0 and components > 0 and path.is_file():
            try:
                raw = path.read_bytes()
            except OSError:
                raw = b""
            finally:
                if bool(descriptor.get("delete_after", False)):
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass
            expected_items = count * components
            if expected_items >= 0 and len(raw) == expected_items * 4:
                data = array("i")
                if data.itemsize != 4:
                    raise RuntimeError("mesh edit selection sidecar requires 32-bit array('i')")
                data.frombytes(raw)
                return [int(value) for value in data]
    if json_key == "source_vertex_indices":
        start_key, count_key = "source_vertex_start", "source_vertex_count"
    elif json_key == "source_face_indices":
        start_key, count_key = "source_face_start", "source_face_count"
    elif json_key == "selected_vertices":
        start_key, count_key = "selected_vertex_start", "selected_vertex_count"
    elif json_key == "selected_faces":
        start_key, count_key = "selected_face_start", "selected_face_count"
    else:
        start_key, count_key = "", ""
    if start_key:
        try:
            raw_start = group.get(start_key, -1)
            raw_count = group.get(count_key, 0)
            start = int(raw_start if raw_start is not None else -1)
            count = int(raw_count if raw_count is not None else 0)
        except (TypeError, ValueError, OverflowError):
            start, count = -1, 0
        if start >= 0 and count > 0:
            return range(start, start + count)
    try:
        raw_values = iter(group.get(json_key) or ())
    except (TypeError, ValueError, OverflowError):
        return []
    values: list[int] = []
    for raw_value in raw_values:
        try:
            values.append(int(raw_value))
        except (TypeError, ValueError, OverflowError):
            return []
    return values


def _mesh_edit_f32_payload_values(group: Mapping[object, object], binary_key: str) -> list[float]:
    descriptor = group.get(binary_key)
    if not isinstance(descriptor, Mapping):
        return []
    try:
        count = int(descriptor.get("count", 0) or 0)
        components = int(descriptor.get("components", 1) or 1)
        path = Path(str(descriptor.get("path") or ""))
    except (TypeError, ValueError, OSError):
        return []
    if count < 0 or components <= 0 or not path.is_file():
        return []
    try:
        raw = path.read_bytes()
    except OSError:
        raw = b""
    finally:
        if bool(descriptor.get("delete_after", False)):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
    expected_items = count * components
    if expected_items < 0 or len(raw) != expected_items * 4:
        return []
    data = array("f")
    if data.itemsize != 4:
        raise RuntimeError("mesh edit weight sidecar requires 32-bit array('f')")
    data.frombytes(raw)
    return [float(value) for value in data]


def _mesh_edit_existing_binary_descriptor(
    value: object,
    *,
    components: int,
    kinds: set[str],
) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        count = int(value.get("count", 0) or 0)
        raw_components = int(value.get("components", components) or components)
        path = Path(str(value.get("path") or ""))
    except (TypeError, ValueError, OSError):
        return None
    if count <= 0 or raw_components != components or not path.is_file():
        return None
    kind = str(value.get("type") or "").strip().lower()
    if kind not in kinds:
        return None
    descriptor: dict[str, object] = {
        "path": str(path),
        "count": count,
        "components": components,
        "type": kind,
    }
    if bool(value.get("delete_after", False)):
        descriptor["delete_after"] = True
    return descriptor


def _mesh_edit_source_vertex_range_descriptor(group: Mapping[object, object], vertex_count: int) -> dict[str, object] | None:
    try:
        raw_start = group.get("source_vertex_start", -1)
        raw_count = group.get("source_vertex_count", 0)
        start = int(raw_start if raw_start is not None else -1)
        count = int(raw_count if raw_count is not None else 0)
    except (TypeError, ValueError, OverflowError):
        return None
    if start < 0 or count <= 0 or start + count > max(0, int(vertex_count)):
        return None
    return {"start": start, "count": count, "components": 1, "type": "i32_range"}


def mesh_edit_payload_native_vertex_groups(
    payload: Mapping[object, object],
    mesh: object | None,
    *,
    allowed_source_indices: Iterable[int],
    source_indices_for_editor_id: Callable[[int], Sequence[int]],
) -> list[dict[str, object]]:
    if mesh is None:
        return []
    allowed_indices = set(int(index) for index in allowed_source_indices)
    submeshes = getattr(mesh, "submeshes", ()) or ()
    native_groups: list[dict[str, object]] = []
    for group in payload.get("groups") or ():
        if not isinstance(group, Mapping):
            continue
        try:
            editor_submesh_index = int(group.get("source_submesh_index", -1))
        except (TypeError, ValueError):
            continue
        source_indices = source_indices_for_editor_id(editor_submesh_index) or ()
        if not source_indices and editor_submesh_index >= 0:
            source_indices = (editor_submesh_index,)
        if len(source_indices) != 1:
            continue
        source_submesh_index = int(source_indices[0])
        if source_submesh_index not in allowed_indices:
            continue
        if source_submesh_index < 0 or source_submesh_index >= len(submeshes):
            continue
        source_vertices = _mesh_edit_existing_binary_descriptor(
            group.get("source_vertex_indices_binary"),
            components=1,
            kinds={"i32"},
        )
        if source_vertices is None:
            vertex_count = len(getattr(submeshes[source_submesh_index], "vertices", ()) or ())
            source_vertices = _mesh_edit_source_vertex_range_descriptor(group, vertex_count)
        if source_vertices is None:
            continue
        native_group: dict[str, object] = {
            "source_submesh_index": source_submesh_index,
            "source_vertex_indices_binary": source_vertices,
        }
        source_weights = _mesh_edit_existing_binary_descriptor(
            group.get("source_vertex_weights_binary"),
            components=1,
            kinds={"f32", "f64"},
        )
        if source_weights is not None:
            if source_vertices.get("type") == "i32_range":
                continue
            if int(source_weights["count"]) != int(source_vertices["count"]):
                continue
            native_group["source_vertex_weights_binary"] = source_weights
        native_groups.append(native_group)
    return native_groups


def mesh_edit_cleanup_native_vertex_group_descriptors(groups: Iterable[Mapping[str, object]]) -> None:
    seen: set[str] = set()
    for group in groups or ():
        for key in ("source_vertex_indices_binary", "source_vertex_weights_binary"):
            descriptor = group.get(key)
            if not isinstance(descriptor, Mapping) or not bool(descriptor.get("delete_after", False)):
                continue
            raw_path = str(descriptor.get("path") or "")
            if not raw_path or raw_path in seen:
                continue
            seen.add(raw_path)
            try:
                Path(raw_path).unlink(missing_ok=True)
            except OSError:
                pass


def mesh_edit_payload_vertex_groups(
    payload: Mapping[object, object],
    mesh: object | None,
    *,
    allowed_source_indices: Iterable[int],
    source_indices_for_editor_id: Callable[[int], Sequence[int]],
) -> list[tuple[int, list[int], dict[int, float]]]:
    if mesh is None:
        return []
    allowed_indices = set(int(index) for index in allowed_source_indices)
    submeshes = getattr(mesh, "submeshes", ()) or ()
    groups: list[tuple[int, list[int], dict[int, float]]] = []
    for group in payload.get("groups") or ():
        if not isinstance(group, Mapping):
            continue
        try:
            editor_submesh_index = int(group.get("source_submesh_index", -1))
        except (TypeError, ValueError):
            continue
        source_indices = source_indices_for_editor_id(editor_submesh_index) or ()
        if not source_indices and editor_submesh_index >= 0:
            source_indices = (editor_submesh_index,)
        for source_submesh_index in source_indices:
            if source_submesh_index not in allowed_indices:
                continue
            if source_submesh_index < 0 or source_submesh_index >= len(submeshes):
                continue
            vertex_count = len(getattr(submeshes[source_submesh_index], "vertices", ()) or ())
            vertex_indices: list[int] = []
            for raw_index in _mesh_edit_i32_payload_values(group, "source_vertex_indices", "source_vertex_indices_binary"):
                try:
                    vertex_index = int(raw_index)
                except (TypeError, ValueError):
                    continue
                if 0 <= vertex_index < vertex_count:
                    vertex_indices.append(vertex_index)
            if vertex_indices:
                groups.append(
                    (
                        int(source_submesh_index),
                        vertex_indices,
                        mesh_edit_payload_vertex_weights(group, vertex_indices),
                    )
                )
    return groups


def mesh_edit_payload_selected_indices(
    payload: Mapping[object, object],
    mesh: object | None,
    *,
    allowed_source_indices: Iterable[int],
    source_indices_for_editor_id: Callable[[int], Sequence[int]],
    payload_index_key: str,
    mesh_collection_attr: str,
) -> dict[int, set[int]]:
    selected: dict[int, set[int]] = {}
    if mesh is None:
        return selected
    allowed_indices = set(int(index) for index in allowed_source_indices)
    submeshes = getattr(mesh, "submeshes", ()) or ()
    for group in payload.get("groups") or ():
        if not isinstance(group, Mapping):
            continue
        try:
            editor_submesh_index = int(group.get("source_submesh_index", -1))
        except (TypeError, ValueError):
            continue
        for source_submesh_index in source_indices_for_editor_id(editor_submesh_index):
            if source_submesh_index not in allowed_indices:
                continue
            if source_submesh_index < 0 or source_submesh_index >= len(submeshes):
                continue
            collection_count = len(getattr(submeshes[source_submesh_index], mesh_collection_attr, ()) or ())
            for raw_index in _mesh_edit_i32_payload_values(group, payload_index_key, f"{payload_index_key}_binary"):
                try:
                    index = int(raw_index)
                except (TypeError, ValueError):
                    continue
                if 0 <= index < collection_count:
                    selected.setdefault(source_submesh_index, set()).add(index)
    return selected


def mesh_edit_payload_edge_groups(
    payload: Mapping[object, object],
    mesh: object | None,
    *,
    allowed_source_indices: Iterable[int],
    source_indices_for_editor_id: Callable[[int], Sequence[int]],
) -> dict[int, set[tuple[int, int]]]:
    selected: dict[int, set[tuple[int, int]]] = {}
    if mesh is None:
        return selected
    allowed_indices = set(int(index) for index in allowed_source_indices)
    submeshes = getattr(mesh, "submeshes", ()) or ()
    for group in payload.get("groups") or ():
        if not isinstance(group, Mapping):
            continue
        try:
            editor_submesh_index = int(group.get("source_submesh_index", -1))
        except (TypeError, ValueError):
            continue
        for source_submesh_index in source_indices_for_editor_id(editor_submesh_index):
            if source_submesh_index not in allowed_indices:
                continue
            if source_submesh_index < 0 or source_submesh_index >= len(submeshes):
                continue
            vertex_count = len(getattr(submeshes[source_submesh_index], "vertices", ()) or ())
            values = _mesh_edit_i32_payload_values(group, "source_edges", "source_edges_binary")
            if not values and not isinstance(group.get("source_edges_binary"), Mapping):
                raw_edges = []
                for raw_edge in group.get("source_edges") or ():
                    try:
                        left = raw_edge[0]  # type: ignore[index]
                        right = raw_edge[1]  # type: ignore[index]
                        raw_edges.extend((int(left), int(right)))
                    except (TypeError, ValueError, IndexError):
                        continue
                values = raw_edges
            for index in range(0, len(values) - 1, 2):
                left_index = int(values[index])
                right_index = int(values[index + 1])
                if left_index == right_index:
                    continue
                if 0 <= left_index < vertex_count and 0 <= right_index < vertex_count:
                    if right_index < left_index:
                        left_index, right_index = right_index, left_index
                    selected.setdefault(int(source_submesh_index), set()).add((left_index, right_index))
    return selected


def mesh_edit_requested_source_indices(mesh: object | None, source_indices: Iterable[int]) -> tuple[int, ...]:
    if mesh is None:
        return ()
    submeshes = getattr(mesh, "submeshes", ()) or ()
    requested: set[int] = set()
    for raw_index in source_indices or ():
        try:
            source_index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if 0 <= source_index < len(submeshes):
            requested.add(source_index)
    return tuple(sorted(requested))


def mesh_edit_all_live_vertices_for_sources(mesh: object | None, source_indices: Iterable[int]) -> dict[int, range]:
    if mesh is None:
        return {}
    submeshes = getattr(mesh, "submeshes", ()) or ()
    result: dict[int, range] = {}
    for source_index in mesh_edit_requested_source_indices(mesh, source_indices):
        result[source_index] = range(len(getattr(submeshes[source_index], "vertices", ()) or ()))
    return result


def mesh_edit_queue_live_vertex_updates(
    pending_vertices: MutableMapping[int, object],
    changed_vertices_by_submesh: Mapping[int, object] | None,
) -> None:
    if not changed_vertices_by_submesh:
        return
    for raw_source_index, raw_vertices in changed_vertices_by_submesh.items():
        try:
            source_index = int(raw_source_index)
        except (TypeError, ValueError):
            continue
        if isinstance(raw_vertices, Mapping):
            existing = pending_vertices.get(source_index)
            if isinstance(existing, range) and existing.start == 0:
                continue
            pending_vertices[source_index] = dict(raw_vertices)
            continue
        compact_range = _compact_vertex_range(raw_vertices)
        if compact_range is not None:
            if compact_range.start == 0:
                pending_vertices[source_index] = compact_range
                continue
            existing = pending_vertices.get(source_index)
            if existing is None or existing == compact_range:
                pending_vertices[source_index] = compact_range
                continue
            if isinstance(existing, range) and existing.start == 0:
                continue
            pending = existing if isinstance(existing, set) else set(_nonnegative_indices(existing))
            pending_vertices[source_index] = pending
            pending.update(compact_range)
            continue
        existing = pending_vertices.get(source_index)
        if isinstance(existing, range) and existing.start == 0:
            continue
        pending = existing if isinstance(existing, set) else set(_nonnegative_indices(existing))
        pending_vertices[source_index] = pending
        pending.update(_nonnegative_indices(raw_vertices))


def _nonnegative_indices(values: Iterable[int] | None) -> Iterable[int]:
    if values is None:
        return
    try:
        iterator = iter(values)
    except TypeError:
        return
    for raw_index in iterator:
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if index >= 0:
            yield index


def _full_vertex_range(value: object) -> range | None:
    if not isinstance(value, range) or value.start != 0 or value.step != 1 or value.stop <= 0:
        return None
    return value


def _compact_vertex_range(value: object) -> range | None:
    if not isinstance(value, range) or value.step != 1 or value.start < 0 or value.stop <= value.start:
        return None
    return value


def _sequence_len(value: object) -> int | None:
    try:
        length = len(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return length if length >= 0 else None


def _descriptor_count(value: object) -> int:
    if not isinstance(value, Mapping):
        return 0
    try:
        count = int(value.get("count", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        return 0
    return count if count > 0 else 0


def _changed_vertex_input_count(value: object, vertex_count: int) -> int | None:
    full_range = _full_vertex_range(value)
    if full_range is not None and full_range.stop == vertex_count:
        return vertex_count
    if isinstance(value, Mapping):
        for descriptor_key in ("changed_vertices_binary", "source_vertex_indices_binary"):
            count = _descriptor_count(value.get(descriptor_key))
            if 0 < count <= vertex_count:
                return count
        if "path" in value:
            count = _descriptor_count(value)
            if 0 < count <= vertex_count:
                return count
        for start_key, count_key in (
            ("changed_vertex_start", "changed_vertex_count"),
            ("source_vertex_start", "source_vertex_count"),
        ):
            start = _nonnegative_int(value.get(start_key), -1)
            count = _nonnegative_int(value.get(count_key), 0)
            if start < 0 and count <= 0:
                continue
            if start < 0 or count <= 0 or start + count > vertex_count:
                return None
            return count
        return None
    return _sequence_len(value)


def mesh_edit_live_vertex_update_groups(
    mesh: object | None,
    changed_vertices_by_submesh: Mapping[int, object] | None,
    transformed_sources_by_index: Mapping[int, object],
    *,
    source_to_preview_point: Callable[[Sequence[object]], Sequence[float]],
    include_normals: bool = False,
    allow_python_fallback: bool = False,
) -> list[dict[str, object]]:
    if mesh is None or not changed_vertices_by_submesh:
        return []
    submeshes = getattr(mesh, "submeshes", ()) or ()
    groups: list[dict[str, object]] = []
    for raw_source_index, raw_vertices in changed_vertices_by_submesh.items():
        try:
            source_index = int(raw_source_index)
        except (TypeError, ValueError):
            continue
        if source_index < 0 or source_index >= len(submeshes):
            continue
        submesh = transformed_sources_by_index.get(source_index)
        if submesh is None:
            continue
        raw_vertex_values = getattr(submesh, "vertices", ()) or ()
        raw_normal_values = getattr(submesh, "normals", ()) or ()
        vertex_count = _sequence_len(raw_vertex_values) or 0
        full_range = _full_vertex_range(raw_vertices)
        fallback_candidate_count = _changed_vertex_input_count(raw_vertices, vertex_count)
        mesh_vertex_count = _nonnegative_int(getattr(mesh, "total_vertices", 0))
        guard_vertex_count = max(mesh_vertex_count, vertex_count, fallback_candidate_count or 0)
        if not _allow_python_preview_fallback(
            mesh,
            "static_preview_vertex_update",
            submesh_index=source_index,
            vertex_count=guard_vertex_count,
            allow_python_fallback=allow_python_fallback,
        ):
            continue
        vertices = raw_vertex_values
        normals = raw_normal_values
        normal_count = _sequence_len(normals) or 0
        if full_range is not None and full_range.stop <= vertex_count:
            source_vertex_indices: Sequence[int] = full_range
        else:
            source_vertex_indices = _source_vertex_indices(raw_vertices, vertex_count)
        positions: list[float] = []
        normal_values: list[float] = []
        if source_vertex_indices and not _allow_python_preview_fallback(
            mesh,
            "static_preview_vertex_update",
            submesh_index=source_index,
            vertex_count=len(source_vertex_indices),
            allow_python_fallback=allow_python_fallback,
        ):
            continue
        for vertex_index in source_vertex_indices:
            preview_position = source_to_preview_point(vertices[vertex_index])
            positions.extend(float(component) for component in preview_position)
            if include_normals and normal_count == vertex_count:
                normal = tuple(normals[vertex_index])
                if len(normal) >= 3:
                    normal_values.extend(float(component) for component in normal[:3])
        if source_vertex_indices:
            _record_native_preview_fallback(
                mesh,
                "static_preview_vertex_update",
                "native static vertex update group unavailable",
                submesh_index=source_index,
                changed_vertex_count=len(source_vertex_indices),
            )
            group: dict[str, object] = {
                "source_submesh_index": source_index,
                "positions": positions,
            }
            _put_index_range_or_values(group, source_vertex_indices, "source_vertex_indices", "source_vertex_start", "source_vertex_count")
            if normal_values:
                group["normals"] = normal_values
            groups.append(group)
    return groups


def mesh_edit_native_live_vertex_update_groups(
    mesh: object | None,
    changed_vertices_by_submesh: Mapping[int, object] | None,
    *,
    normalization_center: Sequence[object],
    normalization_scale: object,
    include_normals: bool = False,
    position_transform_by_source: Mapping[int, Sequence[object]] | None = None,
    normal_transform_by_source: Mapping[int, Sequence[object]] | None = None,
    allow_source_space: bool = True,
) -> list[dict[str, object]]:
    if mesh is None or not changed_vertices_by_submesh:
        return []
    submeshes = getattr(mesh, "submeshes", ()) or ()
    center = _vector3(normalization_center, (0.0, 0.0, 0.0))
    scale = _bounded_float(normalization_scale, 1.0)
    if abs(scale) <= 1e-8:
        scale = 1.0
    pending: list[tuple[object, int, Sequence[int] | None, int | None, dict[str, object] | None]] = []
    missing_native: dict[int, object] = {}
    for raw_source_index, raw_vertices in changed_vertices_by_submesh.items():
        try:
            source_index = int(raw_source_index)
        except (TypeError, ValueError):
            continue
        if source_index < 0 or source_index >= len(submeshes):
            continue
        submesh = submeshes[source_index]
        vertex_count = len(getattr(submesh, "vertices", ()) or ())
        full_range = _full_vertex_range(raw_vertices)
        native_count = _changed_vertex_input_count(raw_vertices, vertex_count)
        raw_group = getattr(submesh, "cdmw_native_preview_vertex_update_group", None)
        group = (
            _native_source_vertex_group(raw_group, source_index, None, expected_count=native_count, include_normals=include_normals)
            if native_count is not None and native_count > 0
            else None
        )
        if group is not None:
            expected: Sequence[int] | None = ()
        elif isinstance(raw_vertices, Mapping):
            if native_count is None or native_count <= 0:
                continue
            expected = None
        elif full_range is not None and full_range.stop == vertex_count:
            expected = full_range
        else:
            expected = _source_vertex_indices(raw_vertices, vertex_count)
        if group is None and expected is not None and not expected:
            continue
        if group is None:
            group = _native_source_vertex_group(
                raw_group,
                source_index,
                expected,
                expected_count=native_count if expected is None else None,
                include_normals=include_normals,
            )
        if group is None:
            missing_native[source_index] = raw_vertices if isinstance(raw_vertices, Mapping) else expected
        pending.append((submesh, source_index, expected, native_count if expected is None else None, group))
    generated_native = _mesh_edit_generated_live_vertex_update_groups(mesh, missing_native, include_normals=include_normals)
    prepared: list[tuple[object, dict[str, object]]] = []
    for submesh, source_index, expected, native_count, group in pending:
        if group is None:
            group = _native_source_vertex_group(
                generated_native.get(source_index),
                source_index,
                expected,
                expected_count=native_count,
                include_normals=include_normals,
            )
        if group is None:
            return []
        position_transform = _affine_transform_for_source(position_transform_by_source, source_index)
        if position_transform:
            normal_transform = _normal_transform_for_source(normal_transform_by_source, source_index)
            if include_normals and not normal_transform:
                return []
            group["position_space"] = "source_affine"
            group["position_transform"] = position_transform
            if normal_transform:
                group["normal_transform"] = normal_transform
        elif allow_source_space:
            group["position_space"] = "source"
            group["normalization_center"] = [center[0], center[1], center[2]]
            group["normalization_scale"] = scale
        else:
            return []
        prepared.append((submesh, group))
    for submesh, _group in prepared:
        if hasattr(submesh, "cdmw_native_preview_vertex_update_group"):
            delattr(submesh, "cdmw_native_preview_vertex_update_group")
    return [group for _submesh, group in prepared]


def _mesh_edit_generated_live_vertex_update_groups(
    mesh: object,
    changed_vertices_by_submesh: Mapping[int, object],
    *,
    include_normals: bool,
) -> dict[int, dict[str, object]]:
    if not changed_vertices_by_submesh:
        return {}
    try:
        from cdmw.modding.mesh_native_core import (
            build_native_mesh_preview_vertex_update_groups,
            invalidate_native_mesh_session_submeshes,
        )
    except Exception:
        return {}
    requested: dict[int, object] = {}
    submeshes = getattr(mesh, "submeshes", ()) or ()
    for raw_source_index, raw_vertices in changed_vertices_by_submesh.items():
        try:
            source_index = int(raw_source_index)
        except (TypeError, ValueError):
            continue
        if 0 <= source_index < len(submeshes):
            requested[source_index] = raw_vertices
    if not requested:
        return {}
    result: dict[int, dict[str, object]] = {}

    def consume(native_groups: object) -> None:
        for raw_group in native_groups or ():
            if not isinstance(raw_group, Mapping):
                continue
            try:
                source_index = int(raw_group.get("source_submesh_index", -1))
            except (TypeError, ValueError, OverflowError):
                continue
            if source_index < 0:
                continue
            group = dict(raw_group)
            if not include_normals:
                group.pop("normals", None)
                group.pop("normals_binary", None)
            result[source_index] = group

    try:
        consume(build_native_mesh_preview_vertex_update_groups(mesh, requested))
    except Exception:
        return {}
    missing = {source_index: requested[source_index] for source_index in requested if source_index not in result}
    if missing:
        try:
            invalidate_native_mesh_session_submeshes(mesh, missing.keys())
            consume(build_native_mesh_preview_vertex_update_groups(mesh, missing))
        except Exception:
            pass
    return result


def mesh_edit_triangle_replace_groups(
    mesh: object | None,
    source_indices: Iterable[int],
    transformed_sources_by_index: Mapping[int, object],
    *,
    source_to_preview_point: Callable[[Sequence[object]], Sequence[float]],
    normalization_center: Sequence[object] = (0.0, 0.0, 0.0),
    normalization_scale: float = 1.0,
    position_transform_by_source: Mapping[int, Sequence[object]] | None = None,
    normal_transform_by_source: Mapping[int, Sequence[object]] | None = None,
    allow_source_space: bool = False,
    allow_python_fallback: bool = False,
) -> list[dict[str, object]]:
    if mesh is None:
        return []
    submeshes = getattr(mesh, "submeshes", ()) or ()
    groups: list[dict[str, object]] = []
    requested_source_indices = mesh_edit_requested_source_indices(mesh, source_indices)
    generated_native = _mesh_edit_triangle_replace_groups_native(mesh, requested_source_indices)
    for source_index in requested_source_indices:
        if source_index < 0 or source_index >= len(submeshes):
            continue
        source_submesh = submeshes[source_index]
        native_group = _consume_native_triangle_group(source_submesh, source_index) or generated_native.get(source_index)
        if native_group is not None and source_index in transformed_sources_by_index and not _triangle_group_has_geometry(native_group):
            native_group = None
        if native_group is not None:
            position_transform = _affine_transform_for_source(position_transform_by_source, source_index)
            normal_transform = _normal_transform_for_source(normal_transform_by_source, source_index)
            has_positions = bool(native_group.get("positions") or native_group.get("positions_binary"))
            has_normals = bool(native_group.get("normals") or native_group.get("normals_binary"))
            if position_transform:
                if has_normals and not normal_transform:
                    native_group = None
                else:
                    native_group["position_space"] = "source_affine"
                    native_group["position_transform"] = position_transform
                    if normal_transform:
                        native_group["normal_transform"] = normal_transform
            elif allow_source_space or not has_positions:
                if has_positions:
                    center = _vector3(normalization_center, (0.0, 0.0, 0.0))
                    native_group["position_space"] = "source"
                    native_group["normalization_center"] = [center[0], center[1], center[2]]
                    native_group["normalization_scale"] = _bounded_float(normalization_scale, 1.0)
            else:
                native_group = None
            if native_group is not None:
                groups.append(_triangle_group_with_material_fields(native_group, source_submesh, source_index))
                continue
        submesh = transformed_sources_by_index.get(source_index)
        if submesh is None:
            continue
        raw_vertex_values = getattr(submesh, "vertices", ()) or ()
        raw_normal_values = getattr(submesh, "normals", ()) or ()
        raw_face_values = getattr(submesh, "faces", ()) or ()
        vertex_count = _sequence_len(raw_vertex_values) or 0
        face_count = _sequence_len(raw_face_values) or 0
        if not _allow_python_preview_fallback(
            mesh,
            "static_preview_triangle_group",
            submesh_index=source_index,
            vertex_count=vertex_count,
            face_count=face_count,
            allow_python_fallback=allow_python_fallback,
        ):
            continue
        vertices = raw_vertex_values
        normals = raw_normal_values
        faces = raw_face_values
        normal_count = _sequence_len(normals) or 0
        positions: list[float] = []
        normal_values: list[float] = []
        source_vertex_indices: Sequence[int] = range(vertex_count)
        source_face_indices: list[int] = []
        indices: list[int] = []
        for vertex_index, vertex in enumerate(vertices):
            preview_position = source_to_preview_point(vertex)
            positions.extend(float(component) for component in preview_position)
            if normal_count == vertex_count:
                normal = tuple(normals[vertex_index])
                if len(normal) >= 3:
                    normal_values.extend(float(component) for component in normal[:3])
        for source_face_index, face in enumerate(faces):
            face_indices: list[int] = []
            try:
                face_iter = iter(face or ())
            except TypeError:
                continue
            for raw_vertex_index in face_iter:
                if len(face_indices) >= 3:
                    break
                try:
                    vertex_index = int(raw_vertex_index)
                except (TypeError, ValueError):
                    face_indices = []
                    break
                if vertex_index < 0 or vertex_index >= vertex_count:
                    face_indices = []
                    break
                face_indices.append(vertex_index)
            if len(face_indices) == 3:
                indices.extend(face_indices)
                source_face_indices.append(int(source_face_index))
        if not indices:
            positions = []
            normal_values = []
            source_vertex_indices = []
            source_face_indices = []
        else:
            _record_native_preview_fallback(
                mesh,
                "static_preview_triangle_group",
                "native static triangle group unavailable",
                submesh_index=source_index,
                source_vertex_count=len(source_vertex_indices),
                source_face_count=len(source_face_indices),
            )
        group: dict[str, object] = {
            "source_submesh_index": source_index,
            "material_source_submesh_index": int(getattr(source_submesh, "cdmw_mesh_edit_material_source_submesh_index", source_index) or source_index),
            "material_name": str(getattr(source_submesh, "material", "") or getattr(source_submesh, "name", "") or f"part_{source_index}"),
            "texture_name": str(getattr(source_submesh, "texture", "") or ""),
            "positions": positions,
            "indices": indices,
        }
        _put_index_range_or_values(group, source_vertex_indices, "source_vertex_indices", "source_vertex_start", "source_vertex_count")
        _put_index_range_or_values(group, source_face_indices, "source_face_indices", "source_face_start", "source_face_count")
        for attr_name in (
            "preview_texture_path",
            "preview_texture_dds_path",
            "preview_normal_texture_path",
            "preview_normal_texture_dds_path",
            "preview_material_texture_path",
            "preview_material_texture_dds_path",
            "preview_height_texture_path",
            "preview_height_texture_dds_path",
            "preview_alpha_mode",
            "preview_texture_flip_vertical",
            "preview_double_sided",
        ):
            value = getattr(source_submesh, attr_name, None)
            if value not in (None, ""):
                group[attr_name] = value
        if normal_values:
            group["normals"] = normal_values
        groups.append(group)
    return groups


def _triangle_group_has_geometry(group: Mapping[str, object]) -> bool:
    return bool(
        group.get("positions")
        or group.get("positions_binary")
        or group.get("indices")
        or group.get("indices_binary")
    )


def _mesh_edit_triangle_replace_groups_native(mesh: object, source_indices: Sequence[int]) -> dict[int, dict[str, object]]:
    if not source_indices:
        return {}
    try:
        from cdmw.modding.mesh_native_core import build_native_mesh_preview_triangle_groups
    except Exception:
        return {}
    try:
        native_groups = build_native_mesh_preview_triangle_groups(mesh, source_indices=source_indices)
    except Exception:
        return {}
    result: dict[int, dict[str, object]] = {}
    for raw_group in native_groups or ():
        if not isinstance(raw_group, Mapping):
            continue
        try:
            source_index = int(raw_group.get("source_submesh_index", -1))
        except (TypeError, ValueError, OverflowError):
            continue
        if source_index >= 0:
            result[source_index] = dict(raw_group)
    return result


def _vector3(value: Sequence[object], fallback: tuple[float, float, float]) -> tuple[float, float, float]:
    try:
        values = tuple(value or fallback)
        return (float(values[0]), float(values[1]), float(values[2]))
    except (TypeError, ValueError, IndexError, OverflowError):
        return fallback


def _consume_native_triangle_group(submesh: object, source_index: int) -> dict[str, object] | None:
    raw_group = getattr(submesh, "cdmw_native_preview_triangle_group", None)
    if hasattr(submesh, "cdmw_native_preview_triangle_group"):
        delattr(submesh, "cdmw_native_preview_triangle_group")
    if not isinstance(raw_group, Mapping):
        return None
    if str(raw_group.get("preview_backend") or "") != "cdmw_mesh_core":
        return None
    try:
        group_source_index = int(raw_group.get("source_submesh_index", -1))
    except (TypeError, ValueError):
        return None
    if group_source_index != source_index:
        return None
    group: dict[str, object] = {"preview_backend": "cdmw_mesh_core", "source_submesh_index": source_index}
    raw_source_vertices_binary = raw_group.get("source_vertex_indices_binary")
    try:
        source_vertex_start = int(raw_group.get("source_vertex_start", -1))
        source_vertex_range_count = int(raw_group.get("source_vertex_count", 0))
    except (TypeError, ValueError, OverflowError):
        source_vertex_start = -1
        source_vertex_range_count = 0
    has_source_vertex_range = source_vertex_start >= 0 and source_vertex_range_count > 0
    source_vertex_count = 0
    if isinstance(raw_source_vertices_binary, Mapping):
        try:
            source_vertex_count = int(raw_source_vertices_binary.get("count", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            return None
    elif has_source_vertex_range:
        source_vertex_count = source_vertex_range_count
    else:
        source_vertices = _source_vertex_indices(raw_group.get("source_vertex_indices", ()), 1 << 30)
        source_vertex_count = len(source_vertices)
        if source_vertices:
            group["source_vertex_indices"] = source_vertices
    source_vertices_binary = _native_binary_descriptor(raw_source_vertices_binary, expected_count=source_vertex_count, components=1, kind="i32")
    if source_vertices_binary is not None:
        group["source_vertex_indices_binary"] = source_vertices_binary
    elif has_source_vertex_range:
        group["source_vertex_start"] = source_vertex_start
        group["source_vertex_count"] = source_vertex_range_count

    raw_source_faces_binary = raw_group.get("source_face_indices_binary")
    try:
        source_face_start = int(raw_group.get("source_face_start", -1))
        source_face_range_count = int(raw_group.get("source_face_count", 0))
    except (TypeError, ValueError, OverflowError):
        source_face_start = -1
        source_face_range_count = 0
    has_source_face_range = source_face_start >= 0 and source_face_range_count > 0
    source_face_count = 0
    if isinstance(raw_source_faces_binary, Mapping):
        try:
            source_face_count = int(raw_source_faces_binary.get("count", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            return None
    elif has_source_face_range:
        source_face_count = source_face_range_count
    else:
        source_faces = _source_vertex_indices(raw_group.get("source_face_indices", ()), 1 << 30)
        source_face_count = len(source_faces)
        if source_faces:
            group["source_face_indices"] = source_faces
    source_faces_binary = _native_binary_descriptor(raw_source_faces_binary, expected_count=source_face_count, components=1, kind="i32")
    if source_faces_binary is not None:
        group["source_face_indices_binary"] = source_faces_binary
    elif has_source_face_range:
        group["source_face_start"] = source_face_start
        group["source_face_count"] = source_face_range_count

    positions = raw_group.get("positions")
    positions_binary = _native_binary_descriptor(raw_group.get("positions_binary"), expected_count=source_vertex_count, components=3, kind="f64")
    if positions_binary is not None:
        group["positions_binary"] = positions_binary
    elif isinstance(positions, list) and len(positions) == source_vertex_count * 3:
        group["positions"] = list(positions)
    else:
        return None

    normals = raw_group.get("normals")
    normals_binary = _native_binary_descriptor(raw_group.get("normals_binary"), expected_count=source_vertex_count, components=3, kind="f64")
    if normals_binary is not None:
        group["normals_binary"] = normals_binary
    elif isinstance(normals, list) and (not normals or len(normals) == source_vertex_count * 3):
        group["normals"] = list(normals)
    else:
        return None

    uvs = raw_group.get("uvs")
    uvs_binary = _native_binary_descriptor(raw_group.get("uvs_binary"), expected_count=source_vertex_count, components=2, kind="f64")
    if uvs_binary is not None:
        group["uvs_binary"] = uvs_binary
    elif isinstance(uvs, list) and (not uvs or len(uvs) == source_vertex_count * 2):
        group["uvs"] = list(uvs)
    else:
        return None

    raw_indices_binary = raw_group.get("indices_binary")
    indices: list[int] = []
    index_count = 0
    if isinstance(raw_indices_binary, Mapping):
        try:
            index_count = int(raw_indices_binary.get("count", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            return None
    else:
        try:
            raw_indices = iter(raw_group.get("indices", ()) or ())
        except (TypeError, ValueError, OverflowError):
            return None
        for raw_index in raw_indices:
            try:
                index = int(raw_index)
            except (TypeError, ValueError, OverflowError):
                return None
            if index >= 0:
                indices.append(index)
        index_count = len(indices)
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


def _triangle_group_with_material_fields(group: Mapping[str, object], submesh: object, source_index: int) -> dict[str, object]:
    result = dict(group)
    result.update(
        {
            "source_submesh_index": source_index,
            "material_source_submesh_index": int(getattr(submesh, "cdmw_mesh_edit_material_source_submesh_index", source_index) or source_index),
            "material_name": str(getattr(submesh, "material", "") or getattr(submesh, "name", "") or f"part_{source_index}"),
            "texture_name": str(getattr(submesh, "texture", "") or ""),
        }
    )
    for attr_name in (
        "preview_texture_path",
        "preview_texture_dds_path",
        "preview_normal_texture_path",
        "preview_normal_texture_dds_path",
        "preview_material_texture_path",
        "preview_material_texture_dds_path",
        "preview_height_texture_path",
        "preview_height_texture_dds_path",
        "preview_alpha_mode",
        "preview_texture_flip_vertical",
        "preview_double_sided",
    ):
        value = getattr(submesh, attr_name, None)
        if value not in (None, ""):
            result[attr_name] = value
    return result


def _source_vertex_indices(indices: Iterable[int], vertex_count: int) -> Sequence[int]:
    if isinstance(indices, range):
        if indices.step == 1:
            start = max(0, indices.start)
            stop = min(max(0, vertex_count), indices.stop)
            return range(start, stop) if start < stop else ()
        raw_indices: Iterable[int] = indices
    else:
        if indices is None:
            return ()
        compact_range = _contiguous_valid_index_range(indices, vertex_count)
        if compact_range is not None:
            return compact_range
        raw_indices = indices
    result: list[int] = []
    seen: set[int] = set()
    try:
        iterator = iter(raw_indices)
    except TypeError:
        return ()
    for raw_index in iterator:
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if 0 <= index < vertex_count and index not in seen:
            result.append(index)
            seen.add(index)
    return sorted(result)


def _contiguous_valid_index_range(indices: Iterable[int], vertex_count: int) -> range | None:
    try:
        raw_length = len(indices)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    if raw_length <= 0:
        return None
    try:
        iterator = iter(indices)
        first = int(next(iterator))
    except (StopIteration, TypeError, ValueError, OverflowError):
        return None
    if first < 0 or first >= vertex_count:
        return None
    for offset, raw_index in enumerate(iterator, start=1):
        try:
            index = int(raw_index)
        except (TypeError, ValueError, OverflowError):
            return None
        if index != first + offset or index >= vertex_count:
            return None
    return range(first, first + raw_length)


def _contiguous_index_range(indices: Sequence[int]) -> tuple[int, int] | None:
    if isinstance(indices, range):
        if indices.start >= 0 and indices.step == 1 and len(indices) > 0:
            return indices.start, len(indices)
        return None
    try:
        iterator = iter(indices)
        start = int(next(iterator))
    except (TypeError, ValueError, OverflowError):
        return None
    except StopIteration:
        return None
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
    return start, count


def _same_index_sequence(left: Sequence[int], right: Sequence[int]) -> bool:
    if len(left) != len(right):
        return False
    return all(int(left_value) == int(right_value) for left_value, right_value in zip(left, right))


def _index_upper_bound(indices: Sequence[int] | None) -> int:
    if indices is None:
        return 1 << 30
    if isinstance(indices, range):
        if not indices:
            return 0
        return max(0, int(indices[-1])) + 1
    return max(indices, default=-1) + 1


def _put_index_range_or_values(
    group: dict[str, object],
    indices: Sequence[int],
    json_key: str,
    start_key: str,
    count_key: str,
) -> None:
    index_range = _contiguous_index_range(indices)
    if index_range is not None:
        group[start_key] = index_range[0]
        group[count_key] = index_range[1]
    else:
        group[json_key] = list(indices)


def _native_binary_descriptor(value: object, *, expected_count: int, components: int, kind: str) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    raw_path = str(value.get("path") or "").strip()
    if not raw_path:
        return None
    try:
        count = int(value.get("count", expected_count))
        raw_components = int(value.get("components", components))
    except (TypeError, ValueError, OverflowError):
        return None
    if count != expected_count or raw_components != components:
        return None
    raw_kind = str(value.get("type") or kind).strip().lower()
    if raw_kind != kind:
        return None
    descriptor: dict[str, object] = {
        "path": raw_path,
        "count": expected_count,
        "components": components,
        "type": kind,
    }
    if bool(value.get("delete_after")):
        descriptor["delete_after"] = True
    return descriptor


def _native_source_vertex_group(
    value: object,
    source_index: int,
    expected_indices: Sequence[int] | None,
    *,
    expected_count: int | None = None,
    include_normals: bool,
) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    if str(value.get("preview_backend") or "") != "cdmw_mesh_core":
        return None
    try:
        group_source_index = int(value.get("source_submesh_index", -1))
    except (TypeError, ValueError):
        return None
    if group_source_index != source_index:
        return None
    expected_count = _sequence_len(expected_indices) if expected_count is None else expected_count
    if expected_count is None or expected_count < 0:
        return None
    try:
        source_vertex_start = int(value.get("source_vertex_start", 0))
        source_vertex_range_count = int(value.get("source_vertex_count", 0))
    except (TypeError, ValueError, OverflowError):
        source_vertex_start = -1
        source_vertex_range_count = 0
    has_source_vertex_range = source_vertex_start >= 0 and source_vertex_range_count == expected_count and expected_count > 0
    source_indices_binary = _native_binary_descriptor(
        value.get("source_vertex_indices_binary"),
        expected_count=expected_count,
        components=1,
        kind="i32",
    )
    source_indices: Sequence[int] = ()
    if source_indices_binary is None and not has_source_vertex_range:
        max_index = _index_upper_bound(expected_indices)
        source_indices = _source_vertex_indices(value.get("source_vertex_indices", ()), max_index)
        if expected_indices is not None and source_indices and not _same_index_sequence(source_indices, expected_indices):
            return None
        if expected_indices is None and source_indices and len(source_indices) != expected_count:
            return None
    if not source_indices and source_indices_binary is None and not has_source_vertex_range and expected_count > 0:
        return None
    positions = value.get("positions")
    positions_binary = _native_binary_descriptor(
        value.get("positions_binary"),
        expected_count=expected_count,
        components=3,
        kind="f64",
    )
    normals = value.get("normals")
    normals_binary = _native_binary_descriptor(
        value.get("normals_binary"),
        expected_count=expected_count,
        components=3,
        kind="f64",
    )
    if positions_binary is None and (not isinstance(positions, list) or len(positions) != expected_count * 3):
        return None
    if include_normals and normals_binary is None and (not isinstance(normals, list) or len(normals) != expected_count * 3):
        return None
    group: dict[str, object] = {
        "preview_backend": "cdmw_mesh_core",
        "source_submesh_index": source_index,
    }
    if source_indices_binary is not None:
        group["source_vertex_indices_binary"] = source_indices_binary
    elif has_source_vertex_range:
        group["source_vertex_start"] = source_vertex_start
        group["source_vertex_count"] = source_vertex_range_count
    else:
        group["source_vertex_indices"] = list(source_indices)
    if positions_binary is not None:
        group["positions_binary"] = positions_binary
    else:
        group["positions"] = list(positions or [])
    if include_normals:
        if normals_binary is not None:
            group["normals_binary"] = normals_binary
        else:
            group["normals"] = list(normals or [])
    return group


def _affine_transform_for_source(value: Mapping[int, Sequence[object]] | None, source_index: int) -> list[float]:
    if not isinstance(value, Mapping):
        return []
    raw_transform = value.get(source_index, value.get(str(source_index)))  # type: ignore[arg-type]
    try:
        transform = [float(component) for component in tuple(raw_transform or ())]
    except (TypeError, ValueError, OverflowError):
        return []
    return transform if len(transform) == 12 else []


def _normal_transform_for_source(value: Mapping[int, Sequence[object]] | None, source_index: int) -> list[float]:
    if not isinstance(value, Mapping):
        return []
    raw_transform = value.get(source_index, value.get(str(source_index)))  # type: ignore[arg-type]
    try:
        transform = [float(component) for component in tuple(raw_transform or ())]
    except (TypeError, ValueError, OverflowError):
        return []
    return transform if len(transform) == 9 else []


__all__ = [
    "mesh_edit_all_live_vertices_for_sources",
    "mesh_edit_all_vertices_by_source",
    "mesh_edit_can_edit_scope",
    "mesh_edit_control_status_text",
    "mesh_edit_has_index_groups",
    "mesh_edit_index_groups_as_sets",
    "mesh_edit_index_group_count",
    "mesh_edit_inverted_vertex_selection",
    "mesh_edit_live_vertex_update_groups",
    "mesh_edit_mapping_keys",
    "mesh_edit_merge_index_groups",
    "mesh_edit_native_live_vertex_update_groups",
    "mesh_edit_optional_sorted_indices",
    "mesh_edit_payload_has_drag_motion",
    "mesh_edit_payload_choice",
    "mesh_edit_payload_float",
    "mesh_edit_payload_int",
    "mesh_edit_payload_edge_groups",
    "mesh_edit_payload_selected_indices",
    "mesh_edit_payload_vector3",
    "mesh_edit_payload_vertex_groups",
    "mesh_edit_payload_vertex_weights",
    "mesh_edit_payload_native_vertex_groups",
    "mesh_edit_cleanup_native_vertex_group_descriptors",
    "mesh_edit_queue_live_vertex_updates",
    "mesh_edit_requested_source_indices",
    "mesh_edit_scope_mode",
    "mesh_edit_selection_depth_mode",
    "mesh_edit_selection_mode",
    "mesh_edit_selected_vertex_points",
    "mesh_edit_selection_region_default_amount",
    "mesh_edit_selection_status_text",
    "mesh_edit_sorted_index_groups",
    "mesh_edit_stroke_id",
    "mesh_edit_tool_context",
    "mesh_edit_target_mode_for_tool",
    "mesh_edit_tool",
    "mesh_edit_topology_source_indices",
    "mesh_edit_triangle_replace_groups",
]
