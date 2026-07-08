"""Original-reference preview model helpers for static replacement."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from cdmw.ui.archive_browser.static_replacement_preview_models import (
    clone_preview_model,
    tint_preview_model,
)


def _mark_selected_original_reference_mesh_state(
    mesh: object,
    mesh_index: int,
    highlight_color: tuple[float, float, float],
    *,
    material_highlight: bool,
) -> None:
    mesh.preview_double_sided = True
    mesh.preview_role = "original_reference_selection_overlay"
    if material_highlight:
        mesh.preview_color = highlight_color
        mesh.material_name = str(getattr(mesh, "material_name", "") or f"selected original reference {int(mesh_index)}")


def original_reference_material_parity_model_state(
    original_model: object,
    *,
    highlighted_indices: Iterable[int],
    clone_model: Callable[[object], object] = clone_preview_model,
    highlight_color: tuple[float, float, float] = (1.0, 0.05, 0.95),
) -> object:
    preview_model = clone_model(original_model)
    highlighted = {int(index) for index in tuple(highlighted_indices or ())}
    for mesh_index, mesh in enumerate(getattr(preview_model, "meshes", ()) or ()):
        if mesh_index in highlighted:
            _mark_selected_original_reference_mesh_state(
                mesh,
                mesh_index,
                highlight_color,
                material_highlight=False,
            )
    return preview_model


def original_reference_debug_highlight_model_state(
    original_model: object,
    *,
    highlighted_indices: Iterable[int],
    clone_model: Callable[[object], object] = clone_preview_model,
    highlight_color: tuple[float, float, float] = (1.0, 0.05, 0.95),
    background_color: tuple[float, float, float] = (0.22, 0.30, 0.38),
) -> object:
    preview_model = clone_model(original_model)
    highlighted = {int(index) for index in tuple(highlighted_indices or ())}
    for mesh_index, mesh in enumerate(getattr(preview_model, "meshes", ()) or ()):
        if mesh_index in highlighted:
            _mark_selected_original_reference_mesh_state(
                mesh,
                mesh_index,
                highlight_color,
                material_highlight=True,
            )
        else:
            mesh.preview_color = background_color
    return preview_model


def original_reference_preview_model_state(
    original_model: object,
    *,
    highlighted_indices: Iterable[int],
    preserve_material_preview: bool,
    clone_model: Callable[[object], object] = clone_preview_model,
    highlight_color: tuple[float, float, float] = (1.0, 0.05, 0.95),
    background_color: tuple[float, float, float] = (0.22, 0.30, 0.38),
) -> object:
    if bool(preserve_material_preview):
        return original_reference_material_parity_model_state(
            original_model,
            highlighted_indices=highlighted_indices,
            clone_model=clone_model,
            highlight_color=highlight_color,
        )
    return original_reference_debug_highlight_model_state(
        original_model,
        highlighted_indices=highlighted_indices,
        clone_model=clone_model,
        highlight_color=highlight_color,
        background_color=background_color,
    )


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
            _mark_selected_original_reference_mesh_state(
                mesh,
                mesh_index,
                highlight_color,
                material_highlight=True,
            )
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
    "original_reference_debug_highlight_model_state",
    "original_reference_material_parity_model_state",
    "original_reference_preview_model_state",
    "overlay_editable_mesh_state",
]
