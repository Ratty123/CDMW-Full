"""Preview-model transformation helpers for static replacement."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable, Sequence

from cdmw.models import ModelPreviewData
from cdmw.modding.mesh_parser import ParsedMesh

SOURCE_SELECTION_OVERLAY_EDITOR_ID_BASE = 2_000_000


def clone_preview_model(model: object) -> object:
    if not isinstance(model, ModelPreviewData):
        return model
    return dataclasses.replace(
        model,
        meshes=[
            dataclasses.replace(mesh)
            for mesh in getattr(model, "meshes", ()) or ()
        ],
    )


def tint_preview_model(
    model: object,
    color: tuple[float, float, float],
    *,
    clear_textures: bool = False,
) -> object:
    cloned = clone_preview_model(model)
    for mesh in getattr(cloned, "meshes", ()) or ():
        if hasattr(mesh, "preview_color"):
            mesh.preview_color = color
        if clear_textures:
            clear_preview_mesh_textures(mesh)
    return cloned


def clear_preview_mesh_textures(mesh: object) -> None:
    for attribute_name in (
        "preview_texture_path",
        "preview_normal_texture_path",
        "preview_material_texture_path",
        "preview_height_texture_path",
    ):
        if hasattr(mesh, attribute_name):
            setattr(mesh, attribute_name, "")


def combine_preview_models(*models: object) -> object | None:
    valid_models = [model for model in models if isinstance(model, ModelPreviewData)]
    if not valid_models:
        return None
    base = valid_models[-1]
    meshes = []
    for model in valid_models:
        meshes.extend([dataclasses.replace(mesh) for mesh in getattr(model, "meshes", ()) or ()])
    vertex_count = sum(len(getattr(mesh, "positions", ()) or ()) for mesh in meshes)
    face_count = sum(len(getattr(mesh, "indices", ()) or ()) // 3 for mesh in meshes)
    return dataclasses.replace(
        base,
        summary="Overlay alignment preview",
        mesh_count=len(meshes),
        vertex_count=vertex_count,
        face_count=face_count,
        meshes=meshes,
    )


def combine_optional_preview_models(models: Iterable[object | None]) -> object | None:
    present_models = tuple(model for model in tuple(models or ()) if model is not None)
    if not present_models:
        return None
    if len(present_models) == 1:
        return present_models[0]
    return combine_preview_models(*present_models)


def direct_source_preview_indices(
    selected_source_indices: Iterable[int],
    *,
    force_direct_source_preview: bool,
    replacement_submesh_count: int,
    mesh_edit_direct_source_preview: bool,
    mesh_edit_source_indices: Iterable[int],
    source_index_is_enabled_renderable: Callable[[int], bool],
) -> set[int]:
    raw_indices = {int(index) for index in tuple(selected_source_indices or ())}
    if force_direct_source_preview:
        raw_indices.update(range(max(0, int(replacement_submesh_count))))
    if mesh_edit_direct_source_preview:
        raw_indices.update(int(index) for index in tuple(mesh_edit_source_indices or ()))
    return {
        source_index
        for source_index in raw_indices
        if source_index_is_enabled_renderable(source_index)
    }


def should_use_direct_source_preview(
    direct_source_indices: Iterable[int],
    *,
    force_direct_source_preview: bool,
    mesh_edit_direct_source_preview: bool,
    appended_source_indices: Iterable[int],
    mapped_source_indices: Iterable[int],
    active_preview_mode: str,
    original_mesh_available: bool,
    replacement_mesh_available: bool,
) -> bool:
    direct_indices = {int(index) for index in tuple(direct_source_indices or ())}
    if not direct_indices:
        return False
    if active_preview_mode not in {"side_by_side", "replacement_only", "overlay"}:
        return False
    if not original_mesh_available or not replacement_mesh_available:
        return False
    if force_direct_source_preview or mesh_edit_direct_source_preview:
        return True
    appended_indices = {int(index) for index in tuple(appended_source_indices or ())}
    mapped_indices = {int(index) for index in tuple(mapped_source_indices or ())}
    return not bool(direct_indices & appended_indices) and not bool(direct_indices & mapped_indices)


def source_preview_geometry_cache_key(
    base_geometry_key: str,
    *,
    use_direct_source_preview: bool,
    direct_source_preview_indices: Iterable[int],
) -> str:
    if not use_direct_source_preview:
        return f"{base_geometry_key}|mapped"
    index_key = ",".join(
        str(index)
        for index in sorted({int(index) for index in tuple(direct_source_preview_indices or ())})
    )
    return f"{base_geometry_key}|direct-source:{index_key}"


def source_indices_in_range(source_indices: Iterable[int], source_count: int) -> set[int]:
    max_count = max(0, int(source_count))
    return {
        index
        for index in (int(source_index) for source_index in tuple(source_indices or ()))
        if 0 <= index < max_count
    }


def selected_source_overlay_indices(
    highlighted_source_indices: Iterable[int],
    source_submeshes: Sequence[object],
    *,
    is_marker_source: Callable[[object], bool],
) -> tuple[int, ...]:
    submeshes = tuple(source_submeshes or ())
    return tuple(
        sorted(
            source_index
            for source_index in source_indices_in_range(highlighted_source_indices, len(submeshes))
            if not is_marker_source(submeshes[source_index])
        )
    )


def disabled_source_indices_from_adjustments(adjustments: Iterable[object]) -> set[int]:
    return {
        int(getattr(adjustment, "source_submesh_index"))
        for adjustment in tuple(adjustments or ())
        if not bool(getattr(adjustment, "enabled", True))
    }


def source_index_groups_for_overlay(
    source_indices: Sequence[int],
    *,
    selected_source_index: int,
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    normalized = tuple(int(index) for index in tuple(source_indices or ()))
    selected = tuple(index for index in normalized if index == int(selected_source_index))
    background = tuple(index for index in normalized if index != int(selected_source_index))
    return background, selected


def source_mesh_pairs_for_indices(
    transformed_sources: Sequence[object],
    source_indices: Sequence[int],
) -> tuple[tuple[int, object], ...]:
    sources = tuple(transformed_sources or ())
    return tuple(
        (source_index, sources[source_index])
        for source_index in tuple(int(index) for index in tuple(source_indices or ()))
        if 0 <= source_index < len(sources)
    )


def source_indices_from_pairs(source_pairs: Iterable[tuple[int, object]]) -> tuple[int, ...]:
    return tuple(int(source_index) for source_index, _submesh in tuple(source_pairs or ()))


def submeshes_from_source_pairs(source_pairs: Iterable[tuple[int, object]]) -> list[object]:
    return [submesh for _source_index, submesh in tuple(source_pairs or ())]


def preview_overlay_offset(preview_model: object, overlay_model: object | None) -> int | None:
    if not isinstance(preview_model, ModelPreviewData):
        return None
    if overlay_model is None or not getattr(overlay_model, "meshes", None):
        return None
    return len(getattr(preview_model, "meshes", ()) or ())


def combine_preview_with_overlay(preview_model: object, overlay_model: object | None) -> object:
    if preview_overlay_offset(preview_model, overlay_model) is None:
        return preview_model
    return combine_preview_models(preview_model, overlay_model) or preview_model


def preview_submesh_bounds(submeshes: Sequence[object]) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    vertices = [
        vertex
        for submesh in tuple(submeshes or ())
        for vertex in (getattr(submesh, "vertices", ()) or ())
    ]
    if not vertices:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    xs, ys, zs = zip(*vertices)
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def parsed_preview_mesh_from_submeshes(source_mesh: object, submeshes: Sequence[object]) -> ParsedMesh:
    submesh_list = list(submeshes or ())
    bbox_min, bbox_max = preview_submesh_bounds(submesh_list)
    return ParsedMesh(
        path=str(getattr(source_mesh, "path", "") or ""),
        format=str(getattr(source_mesh, "format", "") or ""),
        bbox_min=bbox_min,
        bbox_max=bbox_max,
        submeshes=submesh_list,
        total_vertices=sum(len(getattr(submesh, "vertices", ()) or ()) for submesh in submesh_list),
        total_faces=sum(len(getattr(submesh, "faces", ()) or ()) for submesh in submesh_list),
        has_uvs=any(bool(getattr(submesh, "uvs", ()) or ()) for submesh in submesh_list),
        has_bones=False,
    )


def apply_missing_texture_overlay_color(
    model: object,
    color: tuple[float, float, float] = (0.58, 0.56, 0.50),
) -> None:
    for mesh in getattr(model, "meshes", ()) or ():
        if not str(getattr(mesh, "preview_texture_path", "") or "").strip():
            mesh.preview_color = color


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
    clear_preview_mesh_textures(mesh)
    mesh.texture_name = ""
    mesh.preview_texture_image = None
    mesh.preview_normal_texture_image = None
    mesh.preview_material_texture_image = None
    mesh.preview_height_texture_image = None
    mesh.preview_material_texture_inputs = ()
    mesh.preview_texture_tint = ()
    mesh.preview_color = (0.05, 0.95, 1.0)
    mesh.preview_double_sided = True
    mesh.preview_role = "replacement_source_selection_overlay"
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
    "apply_missing_texture_overlay_color",
    "apply_source_selection_overlay_model_state",
    "apply_source_selection_overlay_mesh_state",
    "clear_preview_mesh_textures",
    "clone_preview_model",
    "combine_optional_preview_models",
    "combine_preview_with_overlay",
    "combine_preview_models",
    "disabled_source_indices_from_adjustments",
    "direct_source_preview_indices",
    "parsed_preview_mesh_from_submeshes",
    "preview_submesh_bounds",
    "selected_source_overlay_indices",
    "should_use_direct_source_preview",
    "source_index_groups_for_overlay",
    "source_indices_in_range",
    "source_indices_from_pairs",
    "source_mesh_pairs_for_indices",
    "source_overlay_preview_index_state",
    "source_preview_geometry_cache_key",
    "source_selection_overlay_adjustments",
    "source_selection_overlay_editor_id",
    "source_selection_overlay_index_state",
    "submeshes_from_source_pairs",
    "tint_preview_model",
    "visible_direct_source_pairs",
]
