"""Mesh total/flag recomputation, split out to stay import-light.

`refresh_mesh_totals` lived in `mesh_edit_ops`, whose module-level
`from .mesh_native_core import (...)` pulls the native editing core. Modules
that only needed to recount vertices and faces were paying for that whole
dependency, which put `cdmw.modding.mesh_native_core` in `sys.modules` as soon
as the Mesh Editor tab was imported.

This module deliberately imports nothing at runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - annotation only
    from cdmw.services.mesh_workflow_service import ParsedMesh


def refresh_mesh_totals(mesh: "ParsedMesh") -> None:
    mesh.total_vertices = sum(len(submesh.vertices or []) for submesh in mesh.submeshes or [])
    mesh.total_faces = sum(len(submesh.faces or []) for submesh in mesh.submeshes or [])
    mesh.has_uvs = any(bool(submesh.uvs) for submesh in mesh.submeshes or [])
    mesh.has_bones = any(bool(submesh.bone_indices) or bool(submesh.bone_weights) for submesh in mesh.submeshes or [])
    for submesh in mesh.submeshes or []:
        submesh.vertex_count = len(submesh.vertices or [])
        submesh.face_count = len(submesh.faces or [])


__all__ = ["refresh_mesh_totals"]
