"""Source-selection overlay preview helpers for static replacement."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence

SOURCE_SELECTION_OVERLAY_EDITOR_ID_BASE = 2_000_000


def source_overlay_preview_index_state(
    overlay_model: object,
    *,
    overlay_offset: int,
) -> dict[int, int]:
    preview_index_by_source: dict[int, int] = {}
    for local_index, overlay_mesh in enumerate(getattr(overlay_model, "meshes", ()) or ()):
        try:
            source_index = int(getattr(overlay_mesh, "source_submesh_index", -1))
        except (TypeError, ValueError):
            continue
        if source_index >= 0:
            preview_index_by_source[source_index] = int(overlay_offset) + local_index
    return preview_index_by_source


def source_selection_overlay_editor_id(source_index: int) -> int:
    return SOURCE_SELECTION_OVERLAY_EDITOR_ID_BASE + max(0, int(source_index))


def source_selection_overlay_index_state(
    overlay_model: object,
    *,
    overlay_offset: int,
    editor_id_base: int = SOURCE_SELECTION_OVERLAY_EDITOR_ID_BASE,
) -> tuple[dict[int, int], dict[int, int]]:
    preview_index_by_source: dict[int, int] = {}
    editor_id_by_source: dict[int, int] = {}
    for local_index, overlay_mesh in enumerate(getattr(overlay_model, "meshes", ()) or ()):
        try:
            editor_id = int(getattr(overlay_mesh, "source_submesh_index", -1))
        except (TypeError, ValueError):
            continue
        source_index = editor_id - int(editor_id_base)
        if source_index >= 0:
            preview_index_by_source[source_index] = int(overlay_offset) + local_index
            editor_id_by_source[source_index] = editor_id
    return preview_index_by_source, editor_id_by_source


def source_selection_overlay_adjustments(
    source_indices: Sequence[int],
    current_adjustments: Sequence[object],
    adjustment_factory: Callable[..., object],
) -> list[object]:
    selected = {int(index) for index in tuple(source_indices or ())}
    adjustments: list[object] = []
    seen: set[int] = set()
    for adjustment in tuple(current_adjustments or ()):
        try:
            source_index = int(getattr(adjustment, "source_submesh_index"))
        except (TypeError, ValueError):
            continue
        if source_index in selected and not bool(getattr(adjustment, "enabled", True)):
            adjustment = dataclasses.replace(adjustment, enabled=True)
        adjustments.append(adjustment)
        seen.add(source_index)
    for source_index in sorted(selected - seen):
        adjustments.append(adjustment_factory(source_submesh_index=source_index, enabled=True))
    return adjustments


def apply_source_selection_overlay_mesh_state(mesh: object, source_index: int) -> None:
    mesh.preview_color = (1.0, 0.05, 0.95)
    mesh.preview_double_sided = True
    mesh.preview_role = "replacement_source_selection_overlay"
    overrides = dict(getattr(mesh, "preview_native_material_overrides", {}) or {})
    overrides.update(
        {
            "material_shader_family": "gltf_unlit",
            "roughness": 0.0,
            "metalness": 0.0,
            "specular": 1.0,
        }
    )
    mesh.preview_native_material_overrides = overrides
    mesh.material_name = f"selected source overlay {int(source_index)}"


def apply_source_selection_overlay_model_state(model: object) -> None:
    for mesh in getattr(model, "meshes", ()) or ():
        try:
            source_index = int(getattr(mesh, "source_submesh_index", -1))
        except (TypeError, ValueError):
            source_index = -1
        if source_index < 0:
            continue
        apply_source_selection_overlay_mesh_state(mesh, source_index)
        mesh.source_submesh_index = source_selection_overlay_editor_id(source_index)


def visible_direct_source_pairs(
    transformed_sources: Sequence[object],
    *,
    requested_source_indices: Sequence[int] | set[int],
    disabled_source_indices: Sequence[int] | set[int],
    is_marker_source: Callable[[object], bool],
) -> tuple[tuple[int, object], ...]:
    requested = {int(index) for index in tuple(requested_source_indices or ())}
    disabled = {int(index) for index in tuple(disabled_source_indices or ())}
    return tuple(
        (source_index, submesh)
        for source_index, submesh in enumerate(tuple(transformed_sources or ()))
        if (
            source_index in requested
            and source_index not in disabled
            and not is_marker_source(submesh)
        )
    )


__all__ = [
    "SOURCE_SELECTION_OVERLAY_EDITOR_ID_BASE",
    "apply_source_selection_overlay_model_state",
    "apply_source_selection_overlay_mesh_state",
    "source_overlay_preview_index_state",
    "source_selection_overlay_adjustments",
    "source_selection_overlay_editor_id",
    "source_selection_overlay_index_state",
    "visible_direct_source_pairs",
]
