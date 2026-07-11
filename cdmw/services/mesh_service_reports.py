from __future__ import annotations

import math
from typing import Mapping, Sequence

from cdmw.domain.mesh import (
    MeshEditSelection,
    MeshPartSummary,
    MeshTextureEditTarget,
    MeshUvIslandSummary,
    MeshUvSummary,
    MeshWorkspaceSummary,
)

_CHANGED_VERTEX_RESULT_TUPLE_LIMIT = 10_000

def _mesh_workspace_summary_from_native(
    report: Mapping[str, object] | None,
    *,
    mesh_format: object,
) -> MeshWorkspaceSummary | None:
    if not isinstance(report, Mapping) or str(report.get("command") or "") != "summary":
        return None
    raw_parts = report.get("submeshes")
    if not isinstance(raw_parts, list):
        return None
    parts: list[MeshPartSummary] = []
    for raw_part in raw_parts:
        if not isinstance(raw_part, Mapping):
            return None
        index = _coerce_index(raw_part.get("index"))
        vertex_count = _coerce_index(raw_part.get("vertex_count"))
        face_count = _coerce_index(raw_part.get("face_count"))
        if index is None or vertex_count is None or face_count is None:
            return None
        parts.append(
            MeshPartSummary(
                index=index,
                name=str(raw_part.get("name") or f"part_{index}"),
                material=str(raw_part.get("material") or ""),
                texture=str(raw_part.get("texture") or ""),
                vertex_count=max(0, vertex_count),
                face_count=max(0, face_count),
                uv_count=max(0, _coerce_index(raw_part.get("uv_count")) or 0),
                normal_count=max(0, _coerce_index(raw_part.get("normal_count")) or 0),
                tangent_count=max(0, _coerce_index(raw_part.get("tangent_count")) or 0),
                selected=bool(raw_part.get("selected")),
                selected_vertex_count=max(0, _coerce_index(raw_part.get("selected_vertex_count")) or 0),
                selected_edge_count=max(0, _coerce_index(raw_part.get("selected_edge_count")) or 0),
                selected_face_count=max(0, _coerce_index(raw_part.get("selected_face_count")) or 0),
                has_skinning=bool(raw_part.get("has_skinning")),
            )
        )
    return MeshWorkspaceSummary(
        mesh_format=str(mesh_format or "").strip().lower(),
        part_count=len(parts),
        vertex_count=sum(part.vertex_count for part in parts),
        face_count=sum(part.face_count for part in parts),
        selected_part_count=sum(1 for part in parts if part.selected),
        parts=tuple(parts),
    )

def _mesh_texture_edit_target_from_native_summary(
    report: Mapping[str, object] | None,
    selection: MeshEditSelection,
) -> MeshTextureEditTarget | None:
    if not isinstance(report, Mapping) or str(report.get("command") or "") != "summary":
        raise RuntimeError("native mesh editor texture target failed; Python mesh state is stale")
    raw_parts = report.get("submeshes")
    if not isinstance(raw_parts, list):
        raise RuntimeError("native mesh editor texture target failed; Python mesh state is stale")
    parts: dict[int, Mapping[str, object]] = {}
    ordered_indices: list[int] = []
    for raw_part in raw_parts:
        if not isinstance(raw_part, Mapping):
            raise RuntimeError("native mesh editor texture target failed; Python mesh state is stale")
        index = _coerce_index(raw_part.get("index"))
        if index is None or index < 0:
            raise RuntimeError("native mesh editor texture target failed; Python mesh state is stale")
        parts[index] = raw_part
        ordered_indices.append(index)
    candidates: list[int] = []
    candidates.extend(int(index) for index in selection.source_indices)
    candidates.extend(int(index) for index in selection.vertex_map())
    candidates.extend(int(index) for index in selection.edge_map())
    candidates.extend(int(index) for index in selection.face_map())
    if candidates:
        seen: set[int] = set()
        ordered: list[int] = []
        for index in candidates:
            if index in seen:
                continue
            seen.add(index)
            ordered.append(index)
        indices = tuple(ordered)
    else:
        indices = tuple(ordered_indices)
    for index in indices:
        part = parts.get(index)
        if part is None:
            continue
        texture = str(part.get("texture") or "").strip()
        if not texture:
            continue
        extra_attrs = part.get("extra_attrs")
        source_texture_set_key = (
            str(extra_attrs.get("cdmw_source_texture_set_key") or "")
            if isinstance(extra_attrs, Mapping)
            else ""
        )
        return MeshTextureEditTarget(
            submesh_index=index,
            part_name=str(part.get("name") or f"part_{index}"),
            material=str(part.get("material") or ""),
            texture=texture,
            source_texture_set_key=source_texture_set_key,
        )
    return None

def _mesh_uv_summary_from_native(report: Mapping[str, object] | None) -> MeshUvSummary | None:
    if not isinstance(report, Mapping) or str(report.get("operation") or "") != "uv_summary":
        return None
    raw_islands = report.get("islands")
    if not isinstance(raw_islands, list):
        return None
    islands: list[MeshUvIslandSummary] = []
    for raw_island in raw_islands:
        if not isinstance(raw_island, Mapping):
            return None
        index = _coerce_index(raw_island.get("index"))
        submesh_index = _coerce_index(raw_island.get("submesh_index"))
        vertex_count = _coerce_index(raw_island.get("vertex_count"))
        face_count = _coerce_index(raw_island.get("face_count"))
        selected_vertex_count = _coerce_index(raw_island.get("selected_vertex_count"))
        selected_face_count = _coerce_index(raw_island.get("selected_face_count"))
        if (
            index is None
            or submesh_index is None
            or vertex_count is None
            or face_count is None
            or selected_vertex_count is None
            or selected_face_count is None
        ):
            return None
        islands.append(
            MeshUvIslandSummary(
                index=index,
                submesh_index=submesh_index,
                part_name=str(raw_island.get("part_name") or f"part_{submesh_index}"),
                material=str(raw_island.get("material") or ""),
                texture=str(raw_island.get("texture") or ""),
                vertex_count=max(0, vertex_count),
                face_count=max(0, face_count),
                uv_min=_vec2(raw_island.get("uv_min")),
                uv_max=_vec2(raw_island.get("uv_max")),
                selected=bool(raw_island.get("selected")),
                selected_vertex_count=max(0, selected_vertex_count),
                selected_face_count=max(0, selected_face_count),
            )
        )
    selected_island_count = _coerce_index(report.get("selected_island_count"))
    return MeshUvSummary(
        island_count=len(islands),
        selected_island_count=sum(1 for island in islands if island.selected) if selected_island_count is None else max(0, selected_island_count),
        islands=tuple(islands),
    )

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

def _vec2(value: Sequence[object], fallback: tuple[float, float] = (0.0, 0.0)) -> tuple[float, float]:
    try:
        parsed = (float(value[0]), float(value[1]))
    except (TypeError, ValueError, OverflowError, IndexError):
        return fallback
    return parsed if all(math.isfinite(component) for component in parsed) else fallback


def _changed_vertex_indices_for_result(indices: object) -> Sequence[int] | set[int]:
    if isinstance(indices, range):
        if indices.step != 1 or indices.start < 0 or len(indices) <= 0:
            return ()
        return indices
    if isinstance(indices, Mapping):
        descriptor = _changed_vertex_descriptor_for_result(indices)
        if descriptor is not None:
            return descriptor  # type: ignore[return-value]
        raw_changed = indices.get("changed_vertices")
        if isinstance(raw_changed, list):
            normalized = _changed_vertex_indices_for_result(raw_changed)
            if normalized:
                return {"changed_vertices": sorted(int(index) for index in normalized)}  # type: ignore[return-value]
        for start_key, count_key in (
            ("changed_vertex_start", "changed_vertex_count"),
            ("vertex_index_start", "vertex_index_count"),
            ("source_vertex_start", "source_vertex_count"),
        ):
            try:
                start = int(indices.get(start_key, -1))
                count = int(indices.get(count_key, 0))
            except (TypeError, ValueError, OverflowError):
                continue
            if start >= 0 and count > 0:
                return range(start, start + count)
        return ()
    if isinstance(indices, set) and len(indices) > _CHANGED_VERTEX_RESULT_TUPLE_LIMIT:
        return indices
    normalized: set[int] = set()
    try:
        iterator = iter(indices)  # type: ignore[arg-type]
    except TypeError:
        return ()
    for raw_index in iterator:
        try:
            index = int(raw_index)
        except (TypeError, ValueError, OverflowError):
            continue
        if index >= 0:
            normalized.add(index)
    return tuple(sorted(normalized))


def _changed_vertex_descriptor_for_result(indices: Mapping[object, object]) -> dict[str, object] | None:
    for key in ("changed_vertices_binary", "source_vertex_indices_binary"):
        descriptor = indices.get(key)
        if isinstance(descriptor, Mapping) and str(descriptor.get("path") or "").strip():
            result = {str(item_key): item_value for item_key, item_value in descriptor.items()}
            result.setdefault("components", 1)
            result.setdefault("type", "i32")
            return {key: result}
    if str(indices.get("path") or "").strip():
        result = {str(item_key): item_value for item_key, item_value in indices.items()}
        result.setdefault("components", 1)
        result.setdefault("type", "i32")
        return {"changed_vertices_binary": result}
    return None


def _native_editor_report_submesh_counts(report: Mapping[str, object], expected_count: int) -> tuple[tuple[int, int], ...]:
    raw_items = report.get("submeshes")
    if not isinstance(raw_items, list) or expected_count < 0:
        return ()
    counts: list[tuple[int, int] | None] = [None] * expected_count
    ordered_counts: list[tuple[int, int]] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, Mapping):
            continue
        index = _coerce_index(raw_item.get("index"))
        vertex_count = _coerce_index(raw_item.get("vertex_count"))
        face_count = _coerce_index(raw_item.get("face_count"))
        if index is None or vertex_count is None or face_count is None:
            continue
        if vertex_count < 0 or face_count < 0:
            continue
        item_counts = (vertex_count, face_count)
        ordered_counts.append(item_counts)
        if 0 <= index < expected_count:
            counts[index] = item_counts
    if any(item is None for item in counts):
        return tuple(ordered_counts) if len(ordered_counts) == expected_count else ()
    return tuple(item for item in counts if item is not None)


def _native_editor_report_affected_indices(report: Mapping[str, object], submesh_count: int) -> set[int]:
    affected: set[int] = set()
    raw_affected = report.get("affected_submesh_indices")
    if isinstance(raw_affected, list):
        for raw_index in raw_affected:
            index = _coerce_index(raw_index)
            if index is not None and 0 <= index < submesh_count:
                affected.add(index)
    edit_report = report.get("edit_report")
    raw_items = edit_report.get("submeshes") if isinstance(edit_report, Mapping) else None
    if isinstance(raw_items, list):
        for raw_item in raw_items:
            if not isinstance(raw_item, Mapping):
                continue
            index = _coerce_index(raw_item.get("index"))
            if index is not None and 0 <= index < submesh_count:
                affected.add(index)
    return affected


def _native_editor_report_changed_vertices(
    report: Mapping[str, object],
    submesh_counts: Sequence[tuple[int, int]],
) -> dict[int, Sequence[int] | set[int]]:
    edit_report = report.get("edit_report")
    raw_items = edit_report.get("submeshes") if isinstance(edit_report, Mapping) else None
    if not isinstance(raw_items, list):
        return {}
    changed: dict[int, Sequence[int] | set[int]] = {}
    for raw_item in raw_items:
        if not isinstance(raw_item, Mapping):
            continue
        submesh_index = _coerce_index(raw_item.get("index"))
        if submesh_index is None or not 0 <= submesh_index < len(submesh_counts):
            continue
        indices = _changed_vertex_indices_for_result(raw_item)
        if not indices and isinstance(raw_item.get("changed_vertices"), list):
            json_indices = _bounded_native_editor_changed_vertices(
                _changed_vertex_indices_for_result(raw_item.get("changed_vertices")),
                submesh_counts[submesh_index][0],
            )
            if json_indices:
                changed[submesh_index] = {"changed_vertices": sorted(int(index) for index in json_indices)}  # type: ignore[assignment]
            continue
        if not indices:
            continue
        bounded = _bounded_native_editor_changed_vertices(indices, submesh_counts[submesh_index][0])
        if bounded:
            changed[submesh_index] = bounded
    return changed


def _bounded_native_editor_changed_vertices(
    indices: object,
    vertex_count: int,
) -> Sequence[int] | set[int]:
    if isinstance(indices, Mapping):
        return indices  # type: ignore[return-value]
    if isinstance(indices, range):
        if indices.step != 1:
            return ()
        start = max(0, int(indices.start))
        stop = min(max(0, int(vertex_count)), int(indices.stop))
        return range(start, stop) if start < stop else ()
    bounded: set[int] = set()
    try:
        iterator = iter(indices)  # type: ignore[arg-type]
    except TypeError:
        return ()
    for raw_index in iterator:
        try:
            index = int(raw_index)
        except (TypeError, ValueError, OverflowError):
            continue
        if 0 <= index < vertex_count:
            bounded.add(index)
    return bounded


def _native_editor_dirty_counts_from_report(
    report: Mapping[str, object],
    *,
    current_submesh_count: int,
) -> tuple[tuple[int, int], ...]:
    report_submesh_count = _coerce_index(report.get("submesh_count"))
    if report_submesh_count is None or report_submesh_count < 0:
        return ()
    if report_submesh_count != current_submesh_count and not bool(report.get("topology_changed")):
        return ()
    counts = _native_editor_report_submesh_counts(report, report_submesh_count)
    return counts
