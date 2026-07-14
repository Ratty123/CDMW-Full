"""Original-preview material copy helpers for static replacement."""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping, Sequence

from PySide6.QtGui import QImage

from cdmw.services.mesh_dotnet_material_state import copy_dotnet_preview_material_bindings


ORIGINAL_PREVIEW_TEXTURE_ATTRS = (
    "material_name",
    "texture_name",
    "preview_color",
    "preview_texture_path",
    "preview_texture_dds_path",
    "preview_texture_image",
    "preview_normal_texture_path",
    "preview_normal_texture_dds_path",
    "preview_normal_texture_image",
    "preview_normal_texture_name",
    "preview_normal_texture_strength",
    "preview_material_texture_path",
    "preview_material_texture_dds_path",
    "preview_material_texture_image",
    "preview_material_texture_name",
    "preview_material_texture_type",
    "preview_material_texture_subtype",
    "preview_material_texture_packed_channels",
    "preview_height_texture_path",
    "preview_height_texture_dds_path",
    "preview_height_texture_image",
    "preview_height_texture_name",
    "preview_base_texture_default_path",
    "preview_base_texture_default_name",
    "preview_normal_texture_default_path",
    "preview_normal_texture_default_name",
    "preview_normal_texture_default_strength",
    "preview_material_texture_default_path",
    "preview_material_texture_default_name",
    "preview_material_texture_default_type",
    "preview_material_texture_default_subtype",
    "preview_material_texture_default_packed_channels",
    "preview_height_texture_default_path",
    "preview_height_texture_default_name",
    "preview_texture_flip_vertical",
    "preview_base_texture_source",
    "preview_base_texture_quality",
    "preview_sidecar_material_primitive",
    "preview_sidecar_shader_family",
    "preview_texture_brightness",
    "preview_texture_tint",
    "preview_texture_uv_scale",
    "preview_vertex_color_mean",
    "preview_vertex_alpha_mean",
    "preview_vertex_alpha_min",
    "preview_vertex_color_count",
    "preview_texture_approximation_note",
    "preview_material_texture_inputs",
    "preview_native_material_overrides",
    "preview_debug_flip_base_v",
    "preview_debug_disable_support_maps",
)


def preview_mesh_surface_matches(dst_mesh: object, src_mesh: object, *, epsilon: float = 2e-5) -> bool:
    dst_positions = list(getattr(dst_mesh, "positions", ()) or ())
    src_positions = list(getattr(src_mesh, "positions", ()) or ())
    if len(dst_positions) != len(src_positions) or not dst_positions:
        return False
    if list(getattr(dst_mesh, "indices", ()) or ()) != list(getattr(src_mesh, "indices", ()) or ()):
        return False
    translation_delta: tuple[float, float, float] | None = None
    for dst_position, src_position in zip(dst_positions, src_positions):
        try:
            delta = (
                float(dst_position[0]) - float(src_position[0]),
                float(dst_position[1]) - float(src_position[1]),
                float(dst_position[2]) - float(src_position[2]),
            )
            if translation_delta is None:
                translation_delta = delta
                continue
            if (
                abs(delta[0] - translation_delta[0]) > epsilon
                or abs(delta[1] - translation_delta[1]) > epsilon
                or abs(delta[2] - translation_delta[2]) > epsilon
            ):
                return False
        except (TypeError, ValueError, IndexError, OverflowError):
            return False
    return True


def clone_preview_attr_value(value: object) -> object:
    if isinstance(value, QImage):
        return value.copy()
    try:
        return copy.deepcopy(value)
    except (TypeError, RuntimeError):
        copy_method = getattr(value, "copy", None)
        if callable(copy_method):
            try:
                return copy_method()
            except (TypeError, RuntimeError):
                pass
        return value


def copy_original_preview_material(
    dst_mesh: object,
    src_mesh: object,
    *,
    copy_matching_surface: bool = False,
) -> None:
    for attr in ORIGINAL_PREVIEW_TEXTURE_ATTRS:
        if hasattr(dst_mesh, attr) and hasattr(src_mesh, attr):
            setattr(dst_mesh, attr, clone_preview_attr_value(getattr(src_mesh, attr)))
    if copy_matching_surface and preview_mesh_surface_matches(dst_mesh, src_mesh):
        for attr in ("texture_coordinates", "normals"):
            if hasattr(dst_mesh, attr) and hasattr(src_mesh, attr):
                setattr(dst_mesh, attr, clone_preview_attr_value(getattr(src_mesh, attr)))


def copy_preview_material_bindings_to_mesh(mesh: object, preview_model: object) -> int:
    """Keep resolved preview bindings on an exact-clone ParsedMesh session source."""
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    preview_meshes = tuple(getattr(preview_model, "meshes", ()) or ())
    if not submeshes or len(submeshes) != len(preview_meshes):
        return 0
    for submesh, preview_mesh in zip(submeshes, preview_meshes):
        for attr in ORIGINAL_PREVIEW_TEXTURE_ATTRS:
            if attr.endswith("_image") or not hasattr(preview_mesh, attr):
                continue
            setattr(submesh, attr, clone_preview_attr_value(getattr(preview_mesh, attr)))
    return len(submeshes)


def apply_resolved_original_materials_to_resident_editor(
    *,
    dialog: object,
    replacement_mesh_base: object,
    replacement_mesh: object,
    preview_model: object,
    modify_original_clone_mode: bool,
) -> None:
    """Publish late original bindings to the resident reference and exact clone."""
    if modify_original_clone_mode:
        copy_dotnet_preview_material_bindings(replacement_mesh_base, preview_model)
        copy_dotnet_preview_material_bindings(replacement_mesh, preview_model)
        apply_clone = getattr(dialog, "_mesh_editor_embedded_apply_clone_material_resources", None)
        if callable(apply_clone):
            apply_clone(preview_model)
    apply_reference = getattr(dialog, "_mesh_editor_embedded_apply_reference_material_resources", None)
    if callable(apply_reference):
        apply_reference(preview_model)


def copy_exact_clone_original_preview_materials(
    preview_model: object,
    *,
    modify_original_clone_mode: bool,
    original_texture_preview_enabled: bool,
    original_reference_preview_model: object | None,
) -> bool:
    if not bool(modify_original_clone_mode and original_texture_preview_enabled):
        return False
    if original_reference_preview_model is None:
        return False
    original_meshes = list(getattr(original_reference_preview_model, "meshes", ()) or ())
    preview_meshes = list(getattr(preview_model, "meshes", ()) or ())
    if not original_meshes or len(preview_meshes) != len(original_meshes):
        return False
    for mesh_index, src_mesh in enumerate(original_meshes):
        copy_original_preview_material(
            preview_meshes[mesh_index],
            src_mesh,
            copy_matching_surface=True,
        )
    return True


def apply_original_material_preview(
    preview_model: object,
    *,
    original_texture_preview_enabled: bool,
    original_reference_preview_model: object | None,
    modify_original_clone_mode: bool,
    mapped_preview: bool,
    current_mappings: Sequence[object],
    direct_source_preview_index_map: Mapping[int, int],
    preview_target_mesh_indices: Callable[[object, str, Sequence[int], bool, Sequence[object]], Sequence[int]],
) -> None:
    if not bool(original_texture_preview_enabled) or original_reference_preview_model is None:
        return
    original_meshes = list(getattr(original_reference_preview_model, "meshes", ()) or ())
    preview_meshes = list(getattr(preview_model, "meshes", ()) or ())
    if not original_meshes or not preview_meshes:
        return
    if copy_exact_clone_original_preview_materials(
        preview_model,
        modify_original_clone_mode=modify_original_clone_mode,
        original_texture_preview_enabled=original_texture_preview_enabled,
        original_reference_preview_model=original_reference_preview_model,
    ):
        return
    copied: set[int] = set()
    if modify_original_clone_mode and mapped_preview:
        for preview_index, preview_mesh in enumerate(preview_meshes):
            try:
                source_submesh_index = int(getattr(preview_mesh, "source_submesh_index", -1))
            except (TypeError, ValueError):
                source_submesh_index = -1
            if 0 <= source_submesh_index < len(original_meshes):
                copy_original_preview_material(
                    preview_mesh,
                    original_meshes[source_submesh_index],
                    copy_matching_surface=True,
                )
                copied.add(preview_index)
        if len(copied) >= len(preview_meshes):
            return
        for mapping in current_mappings:
            target_index = int(getattr(mapping, "target_submesh_index", -1))
            if target_index < 0 or target_index >= len(original_meshes):
                continue
            target_mesh_indices = preview_target_mesh_indices(
                preview_model,
                str(getattr(mapping, "target_submesh_name", "") or ""),
                tuple(getattr(mapping, "source_submesh_indices", ()) or ()),
                mapped_preview,
                current_mappings,
            )
            for mesh_index in target_mesh_indices:
                if mesh_index < 0 or mesh_index >= len(preview_meshes):
                    continue
                copy_original_preview_material(
                    preview_meshes[mesh_index],
                    original_meshes[target_index],
                    copy_matching_surface=True,
                )
                copied.add(mesh_index)
        if len(preview_meshes) == len(original_meshes):
            for mesh_index, src_mesh in enumerate(original_meshes):
                if mesh_index in copied:
                    continue
                copy_original_preview_material(
                    preview_meshes[mesh_index],
                    src_mesh,
                    copy_matching_surface=True,
                )
                copied.add(mesh_index)
        if copied and len(copied) >= len(preview_meshes):
            return
    if not mapped_preview and direct_source_preview_index_map:
        for source_index, preview_index in direct_source_preview_index_map.items():
            if 0 <= int(source_index) < len(original_meshes) and 0 <= int(preview_index) < len(preview_meshes):
                copy_original_preview_material(
                    preview_meshes[int(preview_index)],
                    original_meshes[int(source_index)],
                    copy_matching_surface=bool(modify_original_clone_mode),
                )
                copied.add(int(preview_index))
    else:
        for mapping in current_mappings:
            target_index = int(getattr(mapping, "target_submesh_index", -1))
            if target_index < 0 or target_index >= len(original_meshes):
                continue
            target_mesh_indices = preview_target_mesh_indices(
                preview_model,
                str(getattr(mapping, "target_submesh_name", "") or ""),
                tuple(getattr(mapping, "source_submesh_indices", ()) or ()),
                mapped_preview,
                current_mappings,
            )
            for mesh_index in target_mesh_indices:
                if 0 <= int(mesh_index) < len(preview_meshes):
                    copy_original_preview_material(
                        preview_meshes[int(mesh_index)],
                        original_meshes[target_index],
                        copy_matching_surface=bool(modify_original_clone_mode),
                    )
                    copied.add(int(mesh_index))
    if not copied and len(preview_meshes) == len(original_meshes):
        for mesh_index, src_mesh in enumerate(original_meshes):
            copy_original_preview_material(
                preview_meshes[mesh_index],
                src_mesh,
                copy_matching_surface=bool(modify_original_clone_mode),
            )


__all__ = [
    "ORIGINAL_PREVIEW_TEXTURE_ATTRS",
    "apply_resolved_original_materials_to_resident_editor",
    "apply_original_material_preview",
    "clone_preview_attr_value",
    "copy_exact_clone_original_preview_materials",
    "copy_original_preview_material",
    "copy_preview_material_bindings_to_mesh",
    "preview_mesh_surface_matches",
]
