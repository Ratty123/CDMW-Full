"""Preview-model transformation helpers for static replacement."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable, Mapping, Sequence

from cdmw.models import ModelPreviewData
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.ui.archive_browser.static_replacement_preview_frame import (
    alignment_preview_frame_from_model,
    apply_alignment_preview_frame,
)
from cdmw.ui.archive_browser.static_replacement_preview_selection_overlay import (
    SOURCE_SELECTION_OVERLAY_EDITOR_ID_BASE,
    apply_source_selection_overlay_model_state,
    apply_source_selection_overlay_mesh_state,
    source_overlay_preview_index_state,
    source_selection_overlay_adjustments,
    source_selection_overlay_editor_id,
    source_selection_overlay_index_state,
    visible_direct_source_pairs,
)


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


def clear_preview_model_overlays(model: object) -> object:
    if not isinstance(model, ModelPreviewData):
        return model
    return dataclasses.replace(model, physics_overlay=None, cloth_preview=None)


def combine_preview_models(*models: object, preserve_overlays: bool = False) -> object | None:
    valid_models = [model for model in models if isinstance(model, ModelPreviewData)]
    if not valid_models:
        return None
    base = valid_models[-1]
    meshes = []
    for model in valid_models:
        meshes.extend([dataclasses.replace(mesh) for mesh in getattr(model, "meshes", ()) or ()])
    vertex_count = sum(_preview_mesh_vertex_count(mesh) for mesh in meshes)
    face_count = sum(_preview_mesh_face_count(mesh) for mesh in meshes)
    combined = dataclasses.replace(
        base,
        summary="Overlay alignment preview",
        mesh_count=len(meshes),
        vertex_count=vertex_count,
        face_count=face_count,
        meshes=meshes,
    )
    return combined if preserve_overlays else clear_preview_model_overlays(combined)


def combine_alignment_preview_models(
    original_model: object,
    replacement_model: object,
    *,
    frame_authority: str = "original",
    preserve_overlays: bool = False,
) -> object | None:
    if not isinstance(original_model, ModelPreviewData) and not isinstance(replacement_model, ModelPreviewData):
        return None
    if not isinstance(original_model, ModelPreviewData):
        return combine_preview_models(replacement_model, preserve_overlays=preserve_overlays)
    if not isinstance(replacement_model, ModelPreviewData):
        return combine_preview_models(original_model, preserve_overlays=preserve_overlays)
    meshes = [
        dataclasses.replace(mesh)
        for model in (original_model, replacement_model)
        for mesh in getattr(model, "meshes", ()) or ()
    ]
    vertex_count = sum(_preview_mesh_vertex_count(mesh) for mesh in meshes)
    face_count = sum(_preview_mesh_face_count(mesh) for mesh in meshes)
    frame_source = original_model if str(frame_authority or "original").strip().lower() == "original" else replacement_model
    frame = alignment_preview_frame_from_model(
        frame_source,
        preserve_original_materials=True,
    )
    combined = dataclasses.replace(
        frame_source,
        summary="Overlay alignment preview",
        mesh_count=len(meshes),
        vertex_count=vertex_count,
        face_count=face_count,
        meshes=meshes,
    )
    combined = combined if preserve_overlays else clear_preview_model_overlays(combined)
    return apply_alignment_preview_frame(combined, frame)


def _descriptor_count(value: object) -> int:
    if not isinstance(value, dict):
        return 0
    try:
        count = int(value.get("count", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        return 0
    return count if count > 0 else 0


def _preview_mesh_vertex_count(mesh: object) -> int:
    positions = getattr(mesh, "positions", ()) or ()
    if positions:
        return len(positions)
    return _descriptor_count(getattr(mesh, "positions_binary", None))


def _preview_mesh_face_count(mesh: object) -> int:
    indices = getattr(mesh, "indices", ()) or ()
    if indices:
        return len(indices) // 3
    return _descriptor_count(getattr(mesh, "indices_binary", None)) // 3


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


def _preview_submesh_native_metadata(submesh_list: Sequence[object]) -> Mapping[str, object] | None:
    try:
        from cdmw.modding.mesh_native_core import summarize_native_mesh_submesh_metadata

        report = summarize_native_mesh_submesh_metadata(submesh_list)  # type: ignore[arg-type]
    except Exception:
        return None
    return report if isinstance(report, Mapping) else None


def _preview_submesh_metadata_bounds(
    report: Mapping[str, object] | None,
) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    if isinstance(report, Mapping):
        try:
            total_vertices = int(report.get("total_vertices", 0))
            bbox_min = tuple(float(value) for value in tuple(report.get("bbox_min") or ())[:3])
            bbox_max = tuple(float(value) for value in tuple(report.get("bbox_max") or ())[:3])
        except (TypeError, ValueError, OverflowError):
            total_vertices = 0
            bbox_min = ()
            bbox_max = ()
        if total_vertices > 0 and len(bbox_min) == 3 and len(bbox_max) == 3:
            return (bbox_min[0], bbox_min[1], bbox_min[2]), (bbox_max[0], bbox_max[1], bbox_max[2])
    return None


def _preview_submesh_metadata_count(report: Mapping[str, object] | None, key: str) -> int | None:
    if not isinstance(report, Mapping):
        return None
    try:
        value = int(report.get(key, 0))
    except (TypeError, ValueError, OverflowError):
        return None
    return value if value >= 0 else None


def preview_submesh_bounds(
    submeshes: Sequence[object],
    *,
    native_metadata: Mapping[str, object] | None = None,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    submesh_list = list(submeshes or ())
    report = (
        native_metadata
        if isinstance(native_metadata, Mapping)
        else _preview_submesh_native_metadata(submesh_list)
    )
    native_bounds = _preview_submesh_metadata_bounds(report)
    if native_bounds is not None:
        return native_bounds

    vertices = [
        vertex
        for submesh in submesh_list
        for vertex in (getattr(submesh, "vertices", ()) or ())
    ]
    if not vertices:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    xs, ys, zs = zip(*vertices)
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def parsed_preview_mesh_from_submeshes(source_mesh: object, submeshes: Sequence[object]) -> ParsedMesh:
    submesh_list = list(submeshes or ())
    native_metadata = _preview_submesh_native_metadata(submesh_list)
    bbox_min, bbox_max = preview_submesh_bounds(submesh_list, native_metadata=native_metadata)
    total_vertices = _preview_submesh_metadata_count(native_metadata, "total_vertices")
    total_faces = _preview_submesh_metadata_count(native_metadata, "total_faces")
    has_uvs = native_metadata.get("has_uvs") if isinstance(native_metadata, Mapping) else None
    return ParsedMesh(
        path=str(getattr(source_mesh, "path", "") or ""),
        format=str(getattr(source_mesh, "format", "") or ""),
        bbox_min=bbox_min,
        bbox_max=bbox_max,
        submeshes=submesh_list,
        total_vertices=(
            total_vertices
            if total_vertices is not None
            else sum(len(getattr(submesh, "vertices", ()) or ()) for submesh in submesh_list)
        ),
        total_faces=(
            total_faces
            if total_faces is not None
            else sum(len(getattr(submesh, "faces", ()) or ()) for submesh in submesh_list)
        ),
        has_uvs=(
            bool(has_uvs)
            if isinstance(has_uvs, bool)
            else any(bool(getattr(submesh, "uvs", ()) or ()) for submesh in submesh_list)
        ),
        has_bones=False,
    )


def apply_missing_texture_overlay_color(
    model: object,
    color: tuple[float, float, float] = (0.58, 0.56, 0.50),
) -> None:
    for mesh in getattr(model, "meshes", ()) or ():
        if not str(getattr(mesh, "preview_texture_path", "") or "").strip():
            mesh.preview_color = color


__all__ = [
    "SOURCE_SELECTION_OVERLAY_EDITOR_ID_BASE",
    "apply_missing_texture_overlay_color",
    "apply_source_selection_overlay_model_state",
    "apply_source_selection_overlay_mesh_state",
    "clear_preview_mesh_textures",
    "clear_preview_model_overlays",
    "clone_preview_model",
    "combine_alignment_preview_models",
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
