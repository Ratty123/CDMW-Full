"""UV completeness gate for external static-scene imports."""

from __future__ import annotations

import threading
from pathlib import Path

from cdmw.core.common import raise_if_cancelled

from .mesh_native_uv import apply_native_mesh_auto_uv
from .scene_import_result_ops import SceneImportResult, refresh_parsed_mesh_totals

_EXTERNAL_UV_REMEDY = (
    "Unwrap every mesh in Blender or another DCC, export OBJ/DAE/GLB/glTF with a complete "
    "TEXCOORD_0/UV channel, then import again."
)
_VERTEX_ALIGNED_CHANNELS = (
    "normals",
    "tangents",
    "tangent_signs",
    "bone_indices",
    "bone_weights",
    "source_vertex_map",
    "source_vertex_offsets",
)


def ensure_external_scene_uvs(
    result: SceneImportResult,
    source_path: Path,
    *,
    stop_event: threading.Event | None = None,
) -> SceneImportResult:
    """Generate missing external UV channels or fail before geometry is exposed."""
    mesh = result.mesh
    target_indices = {
        index
        for index, submesh in enumerate(mesh.submeshes)
        if submesh.vertices and submesh.faces and len(submesh.uvs) != len(submesh.vertices)
    }
    if not target_indices:
        return result

    aligned_channels = {
        index: tuple(
            name
            for name in _VERTEX_ALIGNED_CHANNELS
            if len(tuple(getattr(mesh.submeshes[index], name, ()) or ())) == len(mesh.submeshes[index].vertices)
        )
        for index in target_indices
    }
    raise_if_cancelled(stop_event, "Scene import cancelled before UV generation.")
    changed = apply_native_mesh_auto_uv(
        mesh,
        target_indices,
        allow_topology_change=True,
        stop_event=stop_event,
    )
    raise_if_cancelled(stop_event, "Scene import cancelled during UV generation.")
    incomplete = {
        index
        for index in target_indices
        if len(mesh.submeshes[index].uvs) != len(mesh.submeshes[index].vertices)
    }
    misaligned = {
        (index, name)
        for index, names in aligned_channels.items()
        for name in names
        if len(tuple(getattr(mesh.submeshes[index], name, ()) or ())) != len(mesh.submeshes[index].vertices)
    }
    if changed is None or incomplete or misaligned:
        detail = "bundled xatlas auto-unwrap was unavailable or failed"
        if changed is not None and incomplete:
            detail = "bundled xatlas auto-unwrap returned an incomplete UV channel"
        elif changed is not None and misaligned:
            detail = "bundled xatlas auto-unwrap could not preserve vertex-aligned channels"
        raise ValueError(
            f"{source_path.suffix.upper().lstrip('.')} source has missing or incomplete UVs; {detail}. "
            f"{_EXTERNAL_UV_REMEDY}"
        )

    refresh_parsed_mesh_totals(mesh)
    result.diagnostics = tuple(result.diagnostics or ()) + (
        f"Review required: generated UVs for {len(target_indices):,} submesh(es) with the bundled xatlas auto-unwrap; "
        "inspect the generated islands and seams before export.",
    )
    return result


__all__ = ["ensure_external_scene_uvs"]
