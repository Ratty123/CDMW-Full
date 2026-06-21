"""Original-reference preview model helpers for static replacement."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from cdmw.ui.archive_browser.static_replacement_preview_models import clone_preview_model, tint_preview_model


def original_reference_preview_model_state(
    original_model: object,
    *,
    highlighted_indices: Iterable[int],
    preserve_material_preview: bool,
    clone_model: Callable[[object], object] = clone_preview_model,
    highlight_color: tuple[float, float, float] = (1.0, 0.86, 0.08),
    background_color: tuple[float, float, float] = (0.22, 0.30, 0.38),
) -> object:
    preview_model = clone_model(original_model)
    highlighted = {int(index) for index in tuple(highlighted_indices or ())}
    if highlighted and not bool(preserve_material_preview):
        for mesh_index, mesh in enumerate(getattr(preview_model, "meshes", ()) or ()):
            mesh.preview_color = highlight_color if mesh_index in highlighted else background_color
    return preview_model


def original_overlay_preview_model_state(
    original_model: object,
    *,
    highlighted_indices: Iterable[int],
    highlight_color: tuple[float, float, float],
    tint_color: tuple[float, float, float] = (0.30, 0.42, 0.54),
) -> object:
    overlay_model = tint_preview_model(original_model, tint_color, clear_textures=False)
    highlighted = {int(index) for index in tuple(highlighted_indices or ())}
    for mesh_index, mesh in enumerate(getattr(overlay_model, "meshes", ()) or ()):
        mesh.source_submesh_index = -1
        mesh.source_vertex_indices = []
        mesh.source_face_indices = []
        if mesh_index in highlighted:
            mesh.preview_color = highlight_color
    return overlay_model


def overlay_editable_mesh_state(
    original_mesh_count: int,
    replacement_mesh_count: int,
    *,
    selected_preview_indices: Iterable[int] | None,
    original_locked: bool,
) -> tuple[str, tuple[int, ...] | tuple[int, int]]:
    if selected_preview_indices is not None:
        return (
            "indices",
            tuple(int(original_mesh_count) + int(index) for index in tuple(selected_preview_indices or ())),
        )
    if original_locked:
        return "range", (int(original_mesh_count), int(replacement_mesh_count))
    return "range", (0, -1)


__all__ = [
    "original_overlay_preview_model_state",
    "original_reference_preview_model_state",
    "overlay_editable_mesh_state",
]
