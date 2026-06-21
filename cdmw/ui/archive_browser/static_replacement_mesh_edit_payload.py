"""Mesh-edit payload parsing helpers for static replacement previews."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence

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
    allowed_vertices = {int(vertex_index) for vertex_index in vertex_indices}
    weights: dict[int, float] = {}
    for raw_weight_entry in tuple(group.get("source_vertex_weights") or ()):
        try:
            raw_weight_index, raw_weight_value = raw_weight_entry  # type: ignore[misc]
            weight_index = int(raw_weight_index)
            weight_value = _bounded_float(raw_weight_value, 0.0, 0.0, 1.0)
        except (TypeError, ValueError, OverflowError):
            continue
        if weight_index in allowed_vertices and weight_value > 0.0:
            weights[weight_index] = max(weights.get(weight_index, 0.0), weight_value)
    return weights


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
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    groups: list[tuple[int, list[int], dict[int, float]]] = []
    for group in tuple(payload.get("groups") or ()):
        if not isinstance(group, Mapping):
            continue
        try:
            editor_submesh_index = int(group.get("source_submesh_index", -1))
        except (TypeError, ValueError):
            continue
        source_indices = tuple(source_indices_for_editor_id(editor_submesh_index))
        if not source_indices and editor_submesh_index >= 0:
            source_indices = (editor_submesh_index,)
        for source_submesh_index in source_indices:
            if source_submesh_index not in allowed_indices:
                continue
            if source_submesh_index < 0 or source_submesh_index >= len(submeshes):
                continue
            vertex_count = len(getattr(submeshes[source_submesh_index], "vertices", ()) or ())
            vertex_indices: list[int] = []
            for raw_index in tuple(group.get("source_vertex_indices") or ()):
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
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    for group in tuple(payload.get("groups") or ()):
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
            for raw_index in tuple(group.get(payload_index_key) or ()):
                try:
                    index = int(raw_index)
                except (TypeError, ValueError):
                    continue
                if 0 <= index < collection_count:
                    selected.setdefault(source_submesh_index, set()).add(index)
    return selected


def mesh_edit_requested_source_indices(mesh: object | None, source_indices: Iterable[int]) -> tuple[int, ...]:
    if mesh is None:
        return ()
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    requested: set[int] = set()
    for raw_index in tuple(source_indices or ()):
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
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    result: dict[int, range] = {}
    for source_index in mesh_edit_requested_source_indices(mesh, source_indices):
        result[source_index] = range(len(getattr(submeshes[source_index], "vertices", ()) or ()))
    return result


def mesh_edit_queue_live_vertex_updates(
    pending_vertices: MutableMapping[int, set[int]],
    changed_vertices_by_submesh: Mapping[int, Iterable[int]] | None,
) -> None:
    if not changed_vertices_by_submesh:
        return
    for raw_source_index, raw_vertices in dict(changed_vertices_by_submesh or {}).items():
        try:
            source_index = int(raw_source_index)
        except (TypeError, ValueError):
            continue
        pending = pending_vertices.setdefault(source_index, set())
        for raw_vertex_index in tuple(raw_vertices or ()):
            try:
                vertex_index = int(raw_vertex_index)
            except (TypeError, ValueError):
                continue
            if vertex_index >= 0:
                pending.add(vertex_index)


def mesh_edit_live_vertex_update_groups(
    mesh: object | None,
    changed_vertices_by_submesh: Mapping[int, Iterable[int]] | None,
    transformed_sources_by_index: Mapping[int, object],
    *,
    source_to_preview_point: Callable[[Sequence[object]], Sequence[float]],
    include_normals: bool = False,
) -> list[dict[str, object]]:
    if mesh is None or not changed_vertices_by_submesh:
        return []
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    groups: list[dict[str, object]] = []
    for raw_source_index, raw_vertices in dict(changed_vertices_by_submesh or {}).items():
        try:
            source_index = int(raw_source_index)
        except (TypeError, ValueError):
            continue
        if source_index < 0 or source_index >= len(submeshes):
            continue
        submesh = transformed_sources_by_index.get(source_index)
        if submesh is None:
            continue
        vertices = tuple(getattr(submesh, "vertices", ()) or ())
        normals = tuple(getattr(submesh, "normals", ()) or ())
        source_vertex_indices: list[int] = []
        positions: list[float] = []
        normal_values: list[float] = []
        normalized_vertices: set[int] = set()
        for raw_vertex_index in tuple(raw_vertices or ()):
            try:
                vertex_index = int(raw_vertex_index)
            except (TypeError, ValueError):
                continue
            if vertex_index >= 0:
                normalized_vertices.add(vertex_index)
        for vertex_index in sorted(normalized_vertices):
            if vertex_index >= len(vertices):
                continue
            preview_position = source_to_preview_point(vertices[vertex_index])
            source_vertex_indices.append(vertex_index)
            positions.extend(float(component) for component in preview_position)
            if include_normals and len(normals) == len(vertices):
                normal = tuple(normals[vertex_index])
                if len(normal) >= 3:
                    normal_values.extend(float(component) for component in normal[:3])
        if source_vertex_indices:
            group: dict[str, object] = {
                "source_submesh_index": source_index,
                "source_vertex_indices": source_vertex_indices,
                "positions": positions,
            }
            if normal_values:
                group["normals"] = normal_values
            groups.append(group)
    return groups


def mesh_edit_triangle_replace_groups(
    mesh: object | None,
    source_indices: Iterable[int],
    transformed_sources_by_index: Mapping[int, object],
    *,
    source_to_preview_point: Callable[[Sequence[object]], Sequence[float]],
) -> list[dict[str, object]]:
    if mesh is None:
        return []
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    groups: list[dict[str, object]] = []
    for source_index in mesh_edit_requested_source_indices(mesh, source_indices):
        if source_index < 0 or source_index >= len(submeshes):
            continue
        submesh = transformed_sources_by_index.get(source_index)
        if submesh is None:
            continue
        vertices = tuple(getattr(submesh, "vertices", ()) or ())
        normals = tuple(getattr(submesh, "normals", ()) or ())
        positions: list[float] = []
        normal_values: list[float] = []
        source_vertex_indices: list[int] = []
        source_face_indices: list[int] = []
        indices: list[int] = []
        for vertex_index, vertex in enumerate(vertices):
            preview_position = source_to_preview_point(vertex)
            positions.extend(float(component) for component in preview_position)
            source_vertex_indices.append(int(vertex_index))
            if len(normals) == len(vertices):
                normal = tuple(normals[vertex_index])
                if len(normal) >= 3:
                    normal_values.extend(float(component) for component in normal[:3])
        for source_face_index, face in enumerate(tuple(getattr(submesh, "faces", ()) or ())):
            face_indices: list[int] = []
            for raw_vertex_index in tuple(face or ())[:3]:
                try:
                    vertex_index = int(raw_vertex_index)
                except (TypeError, ValueError):
                    face_indices = []
                    break
                if vertex_index < 0 or vertex_index >= len(vertices):
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
        group: dict[str, object] = {
            "source_submesh_index": source_index,
            "source_vertex_indices": source_vertex_indices,
            "source_face_indices": source_face_indices,
            "positions": positions,
            "indices": indices,
        }
        if normal_values:
            group["normals"] = normal_values
        groups.append(group)
    return groups


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
    "mesh_edit_optional_sorted_indices",
    "mesh_edit_payload_has_drag_motion",
    "mesh_edit_payload_choice",
    "mesh_edit_payload_float",
    "mesh_edit_payload_int",
    "mesh_edit_payload_selected_indices",
    "mesh_edit_payload_vector3",
    "mesh_edit_payload_vertex_groups",
    "mesh_edit_payload_vertex_weights",
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
