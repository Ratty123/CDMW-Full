"""Resident .NET topology snapshot helpers."""

from __future__ import annotations

from typing import Mapping, Sequence

from cdmw.ui.mesh_editor.native_preview_payloads import mesh_edit_triangle_groups


def complete_replace_all_triangle_update(
    controller: object,
    fallback_groups: Sequence[Mapping[str, object]],
    fallback_requested: Sequence[int],
) -> tuple[tuple[Mapping[str, object], ...], tuple[int, ...], int | None]:
    if not str(getattr(controller, "active_session_id", "") or ""):
        return tuple(fallback_groups), tuple(fallback_requested), None
    mesh = controller.working_mesh(clone=False)
    final_count = len(mesh.submeshes)
    requested = tuple(range(final_count))
    groups = tuple(mesh_edit_triangle_groups(mesh, requested))
    group_indices = {
        int(group.get("source_submesh_index", -1))
        for group in groups
        if int(group.get("source_submesh_index", -1)) >= 0
    }
    if group_indices != set(requested):
        raise RuntimeError("native replace-all topology snapshot is incomplete")
    base_submeshes = tuple(controller.base_mesh(clone=False).submeshes)
    groups = tuple(
        {
            **group,
            "material_source_submesh_index": _material_source_index(
                mesh.submeshes[int(group["source_submesh_index"])],
                int(group["source_submesh_index"]),
                base_submeshes,
            ),
        }
        for group in groups
    )
    return groups, requested, final_count


def _material_source_index(submesh: object, current_index: int, base_submeshes: Sequence[object]) -> int:
    for attribute in (
        "cdmw_mesh_edit_material_source_submesh_index",
        "cdmw_mesh_edit_topology_source_submesh_index",
    ):
        try:
            explicit = int(getattr(submesh, attribute))
        except (AttributeError, TypeError, ValueError, OverflowError):
            continue
        if 0 <= explicit < len(base_submeshes):
            return explicit
    fields = ("name", "material", "texture")
    for keys in (fields, ("name",), ("material", "texture")):
        matches = [
            index
            for index, candidate in enumerate(base_submeshes)
            if all(str(getattr(candidate, key, "") or "") == str(getattr(submesh, key, "") or "") for key in keys)
        ]
        if len(matches) == 1:
            return matches[0]
    return current_index if current_index < len(base_submeshes) else 0
