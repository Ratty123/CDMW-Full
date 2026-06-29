"""Pure Mesh Editor texture target helpers."""

from __future__ import annotations

from dataclasses import dataclass

from .editing import MeshEditSelection


@dataclass(frozen=True, slots=True)
class MeshTextureEditTarget:
    submesh_index: int
    part_name: str
    material: str
    texture: str
    source_texture_set_key: str = ""

    @property
    def display_name(self) -> str:
        return self.texture.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] or self.part_name


def selected_mesh_texture_edit_target(
    mesh: object,
    selection: MeshEditSelection | None = None,
) -> MeshTextureEditTarget | None:
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    candidates = _candidate_submesh_indices(submeshes, selection)
    for submesh_index in candidates:
        target = _texture_target(submesh_index, submeshes[submesh_index])
        if target is not None:
            return target
    if candidates:
        return None
    for submesh_index, submesh in enumerate(submeshes):
        target = _texture_target(submesh_index, submesh)
        if target is not None:
            return target
    return None


def _candidate_submesh_indices(submeshes: tuple[object, ...], selection: MeshEditSelection | None) -> tuple[int, ...]:
    if selection is None:
        return ()
    candidates: list[int] = []
    candidates.extend(selection.source_indices)
    candidates.extend(selection.vertex_map().keys())
    candidates.extend(selection.edge_map().keys())
    candidates.extend(selection.face_map().keys())
    seen: set[int] = set()
    result: list[int] = []
    for raw_index in candidates:
        index = int(raw_index)
        if index in seen or not 0 <= index < len(submeshes):
            continue
        seen.add(index)
        result.append(index)
    return tuple(result)


def _texture_target(submesh_index: int, submesh: object) -> MeshTextureEditTarget | None:
    texture = str(getattr(submesh, "texture", "") or "").strip()
    if not texture:
        return None
    return MeshTextureEditTarget(
        submesh_index=submesh_index,
        part_name=str(getattr(submesh, "name", "") or f"part_{submesh_index}"),
        material=str(getattr(submesh, "material", "") or ""),
        texture=texture,
        source_texture_set_key=str(getattr(submesh, "cdmw_source_texture_set_key", "") or ""),
    )


__all__ = ["MeshTextureEditTarget", "selected_mesh_texture_edit_target"]
