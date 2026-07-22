"""Pure mesh edit command contracts."""

from __future__ import annotations

import math
from collections.abc import Mapping as MappingABC
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence


MeshIndexMap = Mapping[int, Iterable[int]]
MeshEdgeMap = Mapping[int, Iterable[Sequence[int]]]

MESH_EDIT_MODES = ("object", "edit", "sculpt")

MESH_MORPH_ACTIONS = (
    "morph_refresh",
    "morph_activate",
    "morph_author_definition",
    "morph_delete_definition",
    "morph_save_profile",
    "morph_delete_profile",
    "morph_change",
    "morph_apply_preset",
    "morph_save_preset",
    "morph_delete_preset",
    "morph_set_driver",
    "morph_bind",
    "morph_clear_refit",
    "morph_reset",
    "morph_bake",
    "morph_finish",
)

MESH_EDIT_ACTIONS = (
    "set_mode",
    "select",
    "transform",
    "brush",
    "delete",
    "dissolve",
    "subdivide",
    "refine_smooth",
    "split",
    "separate",
    "duplicate",
    "mirror",
    "extrude",
    "inset",
    "loop_cut",
    "edge_split",
    "merge",
    "weld",
    "bridge",
    "fill",
    "remove_doubles",
    "delete_loose_vertices",
    "compact_orphans",
    "fix_winding",
    "fill_holes",
    "triangulate_display",
    "quadrangulate_display",
    "recalculate_normals",
    "generate_tangents",
    "flip_normals",
    "sharpen_normals",
    "soften_normals",
    "weighted_normals",
    "copy_normals",
    "uv_transform",
    "material_assign",
    "material_copy",
)


def _mapping_items(values: object | None) -> tuple[tuple[object, object], ...]:
    if values is None:
        return ()
    if isinstance(values, MappingABC):
        return tuple(values.items())
    try:
        return tuple(dict(values).items())
    except (TypeError, ValueError):
        return ()


def _selection_values(values: object | None) -> tuple[object, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes)):
        return (values,)
    try:
        return tuple(values)
    except TypeError:
        return (values,)


def _edge_pair(value: object) -> tuple[int, int] | None:
    items = _selection_values(value)
    if len(items) < 2:
        return None
    left = _coerce_index(items[0])
    right = _coerce_index(items[1])
    if left is None or right is None:
        return None
    return left, right


def _index_items(values: MeshIndexMap | None) -> tuple[tuple[int, tuple[int, ...]], ...]:
    result: list[tuple[int, tuple[int, ...]]] = []
    for raw_submesh, raw_indices in _mapping_items(values):
        submesh_index = _coerce_index(raw_submesh)
        if submesh_index is None:
            continue
        indices: set[int] = set()
        for raw_index in _selection_values(raw_indices):
            index = _coerce_index(raw_index)
            if index is None:
                continue
            if index >= 0:
                indices.add(index)
        if indices:
            result.append((submesh_index, tuple(sorted(indices))))
    return tuple(sorted(result))


def _edge_items(values: MeshEdgeMap | None) -> tuple[tuple[int, tuple[tuple[int, int], ...]], ...]:
    result: list[tuple[int, tuple[tuple[int, int], ...]]] = []
    for raw_submesh, raw_edges in _mapping_items(values):
        submesh_index = _coerce_index(raw_submesh)
        if submesh_index is None:
            continue
        edges: set[tuple[int, int]] = set()
        raw_edge_values = (raw_edges,) if _edge_pair(raw_edges) is not None else _selection_values(raw_edges)
        for raw_edge in raw_edge_values:
            pair = _edge_pair(raw_edge)
            if pair is None:
                continue
            a, b = pair
            if a >= 0 and b >= 0 and a != b:
                edges.add((a, b) if a <= b else (b, a))
        if edges:
            result.append((submesh_index, tuple(sorted(edges))))
    return tuple(sorted(result))


@dataclass(frozen=True, slots=True)
class MeshEditSelection:
    vertices_by_submesh: tuple[tuple[int, tuple[int, ...]], ...] = ()
    edges_by_submesh: tuple[tuple[int, tuple[tuple[int, int], ...]], ...] = ()
    faces_by_submesh: tuple[tuple[int, tuple[int, ...]], ...] = ()
    source_indices: tuple[int, ...] = ()

    @classmethod
    def from_maps(
        cls,
        *,
        vertices_by_submesh: MeshIndexMap | None = None,
        edges_by_submesh: MeshEdgeMap | None = None,
        faces_by_submesh: MeshIndexMap | None = None,
        source_indices: Iterable[int] | None = None,
    ) -> "MeshEditSelection":
        sources: set[int] = set()
        for raw_index in _selection_values(source_indices):
            index = _coerce_index(raw_index)
            if index is None:
                continue
            if index >= 0:
                sources.add(index)
        return cls(
            vertices_by_submesh=_index_items(vertices_by_submesh),
            edges_by_submesh=_edge_items(edges_by_submesh),
            faces_by_submesh=_index_items(faces_by_submesh),
            source_indices=tuple(sorted(sources)),
        )

    def vertex_map(self) -> dict[int, set[int]]:
        return {submesh: set(indices) for submesh, indices in self.vertices_by_submesh}

    def edge_map(self) -> dict[int, set[tuple[int, int]]]:
        return {submesh: set(edges) for submesh, edges in self.edges_by_submesh}

    def face_map(self) -> dict[int, set[int]]:
        return {submesh: set(indices) for submesh, indices in self.faces_by_submesh}

    def is_empty(self) -> bool:
        return not (
            self.vertices_by_submesh
            or self.edges_by_submesh
            or self.faces_by_submesh
            or self.source_indices
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


@dataclass(frozen=True, slots=True)
class MeshEditCommand:
    action: str
    selection: MeshEditSelection | None = None
    params: Mapping[str, object] = field(default_factory=dict)
    mode: str | None = None
    label: str = ""


@dataclass(frozen=True, slots=True)
class MeshEditResult:
    action: str
    status: str
    revision: int
    affected_submesh_indices: tuple[int, ...] = ()
    changed_vertices_by_submesh: tuple[tuple[int, Sequence[int] | set[int]], ...] = ()
    topology_changed: bool = False
    submesh_count_delta: int = 0
    submesh_counts: tuple[tuple[int, int], ...] = ()
    diagnostics: tuple[str, ...] = ()
    metrics: Mapping[str, float] = field(default_factory=dict)
    native_selection_groups: tuple[Mapping[str, object], ...] = ()
    native_preview_vertex_update_groups: tuple[Mapping[str, object], ...] = ()
    native_preview_triangle_groups: tuple[Mapping[str, object], ...] = ()

    @property
    def ok(self) -> bool:
        return self.status == "ok"


@dataclass(frozen=True, slots=True)
class MeshEditHistoryEntry:
    action: str
    label: str
    state: str = "applied"


@dataclass(frozen=True, slots=True)
class MeshEditSessionView:
    session_id: str
    mode: str
    revision: int
    selection: MeshEditSelection
    submesh_count: int
    vertex_count: int
    face_count: int
    undo_count: int = 0
    redo_count: int = 0
    history_entries: tuple[MeshEditHistoryEntry, ...] = ()
    history_cursor: int = 0


__all__ = [
    "MESH_EDIT_ACTIONS",
    "MESH_EDIT_MODES",
    "MESH_MORPH_ACTIONS",
    "MeshEditCommand",
    "MeshEditHistoryEntry",
    "MeshEditResult",
    "MeshEditSelection",
    "MeshEditSessionView",
]
