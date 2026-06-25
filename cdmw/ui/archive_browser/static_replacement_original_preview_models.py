"""Original-reference preview model helpers for static replacement."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from cdmw.ui.archive_browser.static_replacement_preview_models import (
    clear_preview_mesh_textures,
    clone_preview_model,
    tint_preview_model,
)


def _apply_selected_original_reference_mesh_state(
    mesh: object,
    mesh_index: int,
    highlight_color: tuple[float, float, float],
) -> None:
    clear_preview_mesh_textures(mesh)
    mesh.texture_name = ""
    mesh.preview_texture_image = None
    mesh.preview_normal_texture_image = None
    mesh.preview_material_texture_image = None
    mesh.preview_height_texture_image = None
    mesh.preview_material_texture_inputs = ()
    mesh.preview_texture_tint = ()
    mesh.preview_color = highlight_color
    mesh.preview_double_sided = True
    mesh.preview_role = "original_reference_selection"
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
    mesh.material_name = f"selected original reference {int(mesh_index)}"


def original_reference_preview_model_state(
    original_model: object,
    *,
    highlighted_indices: Iterable[int],
    preserve_material_preview: bool,
    clone_model: Callable[[object], object] = clone_preview_model,
    highlight_color: tuple[float, float, float] = (1.0, 0.05, 0.95),
    background_color: tuple[float, float, float] = (0.22, 0.30, 0.38),
) -> object:
    preview_model = clone_model(original_model)
    highlighted = {int(index) for index in tuple(highlighted_indices or ())}
    if highlighted:
        for mesh_index, mesh in enumerate(getattr(preview_model, "meshes", ()) or ()):
            if mesh_index in highlighted:
                _apply_selected_original_reference_mesh_state(mesh, mesh_index, highlight_color)
            elif not bool(preserve_material_preview):
                mesh.preview_color = background_color
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
            _apply_selected_original_reference_mesh_state(mesh, mesh_index, highlight_color)
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
