"""Clone helpers for static mesh replacement."""

from __future__ import annotations

from .mesh_parser import ParsedMesh, SubMesh


def _clone_submesh_fast(submesh: SubMesh) -> SubMesh:
    cloned = SubMesh(
        name=str(submesh.name or ""),
        material=str(submesh.material or ""),
        texture=str(submesh.texture or ""),
        vertices=list(submesh.vertices or []),
        uvs=list(submesh.uvs or []),
        normals=list(submesh.normals or []),
        faces=list(submesh.faces or []),
        bone_indices=list(submesh.bone_indices or []),
        bone_weights=list(submesh.bone_weights or []),
        source_vertex_map=list(submesh.source_vertex_map or []),
        vertex_count=int(submesh.vertex_count or 0),
        face_count=int(submesh.face_count or 0),
        source_vertex_offsets=list(submesh.source_vertex_offsets or []),
        source_index_offset=int(submesh.source_index_offset or -1),
        source_index_count=int(submesh.source_index_count or 0),
        source_vertex_stride=int(submesh.source_vertex_stride or 0),
        source_descriptor_offset=int(submesh.source_descriptor_offset or -1),
        source_bbox_min=tuple(submesh.source_bbox_min or (0.0, 0.0, 0.0)),
        source_bbox_extent=tuple(submesh.source_bbox_extent or (0.0, 0.0, 0.0)),
        source_lod_count=int(submesh.source_lod_count or 0),
    )
    for attr_name in (
        "texture_slots",
        "preview_color",
        "preview_vertex_color_mean",
        "preview_vertex_alpha_mean",
        "preview_vertex_alpha_min",
        "preview_vertex_color_count",
        "preview_normal_texture_path",
        "preview_normal_texture_name",
        "preview_normal_texture_strength",
        "preview_material_texture_path",
        "preview_material_texture_name",
        "preview_material_texture_type",
        "preview_material_texture_subtype",
        "preview_material_texture_packed_channels",
        "preview_material_texture_inputs",
        "preview_material_parameters",
        "preview_height_texture_path",
        "preview_height_texture_name",
        "preview_sidecar_shader_family",
    ):
        if hasattr(submesh, attr_name):
            setattr(cloned, attr_name, getattr(submesh, attr_name))
    return cloned


def _clone_parsed_mesh_fast(mesh: ParsedMesh) -> ParsedMesh:
    return ParsedMesh(
        path=str(mesh.path or ""),
        format=str(mesh.format or ""),
        bbox_min=tuple(mesh.bbox_min or (0.0, 0.0, 0.0)),
        bbox_max=tuple(mesh.bbox_max or (0.0, 0.0, 0.0)),
        submeshes=[_clone_submesh_fast(submesh) for submesh in mesh.submeshes],
        lod_levels=[
            [_clone_submesh_fast(submesh) for submesh in lod_level]
            for lod_level in (mesh.lod_levels or [])
        ],
        total_vertices=int(mesh.total_vertices or 0),
        total_faces=int(mesh.total_faces or 0),
        has_uvs=bool(mesh.has_uvs),
        has_bones=bool(mesh.has_bones),
    )
