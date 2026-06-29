"""Pure Mesh Editor workspace summary helpers."""

from __future__ import annotations

from dataclasses import dataclass

from .editing import MeshEditSelection


@dataclass(frozen=True, slots=True)
class MeshPartSummary:
    index: int
    name: str
    material: str
    texture: str
    vertex_count: int
    face_count: int
    uv_count: int
    normal_count: int
    tangent_count: int
    selected: bool = False
    selected_vertex_count: int = 0
    selected_edge_count: int = 0
    selected_face_count: int = 0
    material_slot_index: int = -1
    material_slot_kind: str = ""
    source_texture_set_key: str = ""
    has_skinning: bool = False

    @property
    def uv_coverage(self) -> str:
        return _coverage(self.uv_count, self.vertex_count)

    @property
    def normal_coverage(self) -> str:
        return _coverage(self.normal_count, self.vertex_count)

    @property
    def tangent_coverage(self) -> str:
        return _coverage(self.tangent_count, self.vertex_count)

    @property
    def texture_coverage(self) -> str:
        return "linked" if self.texture else "missing"


@dataclass(frozen=True, slots=True)
class MeshWorkspaceSummary:
    mesh_format: str
    part_count: int
    vertex_count: int
    face_count: int
    selected_part_count: int
    parts: tuple[MeshPartSummary, ...] = ()


def summarize_mesh_workspace(mesh: object, selection: MeshEditSelection | None = None) -> MeshWorkspaceSummary:
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    selected_sources = set(selection.source_indices if selection is not None else ())
    selected_vertices = selection.vertex_map() if selection is not None else {}
    selected_edges = selection.edge_map() if selection is not None else {}
    selected_faces = selection.face_map() if selection is not None else {}
    parts = tuple(
        _part_summary(
            index,
            submesh,
            selected_by_source=index in selected_sources,
            selected_vertex_count=len(selected_vertices.get(index, ())),
            selected_edge_count=len(selected_edges.get(index, ())),
            selected_face_count=len(selected_faces.get(index, ())),
        )
        for index, submesh in enumerate(submeshes)
    )
    return MeshWorkspaceSummary(
        mesh_format=str(getattr(mesh, "format", "") or "").strip().lower(),
        part_count=len(parts),
        vertex_count=sum(part.vertex_count for part in parts),
        face_count=sum(part.face_count for part in parts),
        selected_part_count=sum(1 for part in parts if part.selected),
        parts=parts,
    )


def _part_summary(
    index: int,
    submesh: object,
    *,
    selected_by_source: bool,
    selected_vertex_count: int,
    selected_edge_count: int,
    selected_face_count: int,
) -> MeshPartSummary:
    vertices = tuple(getattr(submesh, "vertices", ()) or ())
    faces = tuple(getattr(submesh, "faces", ()) or ())
    uvs = tuple(getattr(submesh, "uvs", ()) or ())
    normals = tuple(getattr(submesh, "normals", ()) or ())
    tangents = tuple(getattr(submesh, "tangents", ()) or ())
    bone_indices = tuple(getattr(submesh, "bone_indices", ()) or ())
    bone_weights = tuple(getattr(submesh, "bone_weights", ()) or ())
    return MeshPartSummary(
        index=index,
        name=str(getattr(submesh, "name", "") or f"part_{index}"),
        material=str(getattr(submesh, "material", "") or ""),
        texture=str(getattr(submesh, "texture", "") or ""),
        vertex_count=len(vertices),
        face_count=len(faces),
        uv_count=len(uvs),
        normal_count=len(normals),
        tangent_count=len(tangents),
        selected=bool(selected_by_source or selected_vertex_count or selected_edge_count or selected_face_count),
        selected_vertex_count=max(0, int(selected_vertex_count or 0)),
        selected_edge_count=max(0, int(selected_edge_count or 0)),
        selected_face_count=max(0, int(selected_face_count or 0)),
        material_slot_index=_int_attr(submesh, "cdmw_target_material_slot_index"),
        material_slot_kind=str(getattr(submesh, "cdmw_material_slot_kind", "") or ""),
        source_texture_set_key=str(getattr(submesh, "cdmw_source_texture_set_key", "") or ""),
        has_skinning=bool(bone_indices or bone_weights),
    )


def _coverage(count: int, total: int) -> str:
    if total <= 0:
        return "empty"
    if count == total:
        return "complete"
    if count <= 0:
        return "missing"
    return f"partial {count}/{total}"


def _int_attr(source: object, name: str) -> int:
    try:
        return int(getattr(source, name, -1))
    except (TypeError, ValueError):
        return -1


__all__ = ["MeshPartSummary", "MeshWorkspaceSummary", "summarize_mesh_workspace"]
