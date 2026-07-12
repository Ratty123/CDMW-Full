"""Deterministic Python fallback for static-mesh preview decimation."""

from __future__ import annotations

import math

from .mesh_parser import SubMesh
from .static_mesh_clone import _clone_submesh_fast


def decimate_submesh_for_preview(submesh: SubMesh, max_faces: int) -> SubMesh:
    faces = list(submesh.faces or [])
    if max_faces <= 0 or len(faces) <= max_faces or not submesh.vertices:
        return submesh

    step = max(1, math.ceil(len(faces) / float(max_faces)))
    sampled_faces = faces[::step][:max_faces]
    source_to_preview: dict[int, int] = {}
    preview_vertices: list[tuple[float, float, float]] = []
    preview_faces: list[tuple[int, int, int]] = []

    for face in sampled_faces:
        remapped_face: list[int] = []
        for raw_index in face[:3]:
            try:
                source_index = int(raw_index)
            except (TypeError, ValueError):
                remapped_face = []
                break
            if source_index < 0 or source_index >= len(submesh.vertices):
                remapped_face = []
                break
            preview_index = source_to_preview.get(source_index)
            if preview_index is None:
                preview_index = len(preview_vertices)
                source_to_preview[source_index] = preview_index
                preview_vertices.append(submesh.vertices[source_index])
            remapped_face.append(preview_index)
        if len(remapped_face) == 3:
            preview_faces.append((remapped_face[0], remapped_face[1], remapped_face[2]))

    if not preview_faces:
        return submesh

    ordered_source_indices = [
        source_index
        for source_index, _preview_index in sorted(source_to_preview.items(), key=lambda item: item[1])
    ]
    preview = _clone_submesh_fast(submesh)
    preview.vertices = preview_vertices
    preview.faces = preview_faces
    for attribute in ("uvs", "normals", "bone_indices", "bone_weights", "source_vertex_map"):
        values = getattr(submesh, attribute)
        setattr(
            preview,
            attribute,
            [values[source_index] for source_index in ordered_source_indices]
            if len(values) == len(submesh.vertices)
            else [],
        )
    preview.vertex_count = len(preview.vertices)
    preview.face_count = len(preview.faces)
    preview.source_vertex_offsets = []
    preview.source_index_offset = -1
    preview.source_index_count = len(preview.faces) * 3
    return preview
