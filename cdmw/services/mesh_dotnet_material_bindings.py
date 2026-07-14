"""Preview and native material binding bridges for the .NET renderer."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence

from cdmw.services.mesh_dotnet_material_channels import _color3


_DOTNET_PREVIEW_MATERIAL_ATTRS = (
    "preview_color",
    "preview_texture_path",
    "preview_texture_dds_path",
    "preview_normal_texture_path",
    "preview_normal_texture_dds_path",
    "preview_normal_texture_name",
    "preview_normal_texture_strength",
    "preview_normal_texture_space",
    "preview_normal_y_policy",
    "preview_material_texture_path",
    "preview_material_texture_dds_path",
    "preview_material_texture_name",
    "preview_material_texture_type",
    "preview_material_texture_subtype",
    "preview_material_texture_packed_channels",
    "preview_height_texture_path",
    "preview_height_texture_dds_path",
    "preview_height_texture_name",
    "preview_emissive_texture_path",
    "preview_emissive_texture_dds_path",
    "preview_emissive_texture_name",
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
    "preview_emissive_texture_default_path",
    "preview_emissive_texture_default_name",
    "preview_texture_flip_vertical",
    "preview_base_texture_source",
    "preview_base_texture_quality",
    "preview_sidecar_material_primitive",
    "preview_sidecar_shader_family",
    "preview_texture_brightness",
    "preview_texture_contrast",
    "preview_texture_saturation",
    "preview_texture_gamma",
    "preview_texture_tint",
    "preview_texture_uv_scale",
    "preview_material_texture_inputs",
    "preview_material_parameters",
    "preview_native_material_overrides",
    "preview_alpha_mode",
    "preview_double_sided",
    "preview_vertex_color_mean",
    "preview_vertex_alpha_mean",
    "preview_vertex_alpha_min",
    "preview_vertex_color_count",
    "preview_role",
    "preview_source_asset_path",
    "texture_wrap_repeat",
    "cdmw_material_authority_profile",
    "material_authority_profile",
    "complete_swap_material_profile",
)

_DOTNET_NATIVE_MATERIAL_OVERRIDE_KEYS = frozenset(
    {
        "base_tint_only_fallback",
        "base_tint_strength",
        "emissive_color",
        "emissive_intensity",
        "height_amount",
        "height_scale",
        "material_category",
        "material_category_confidence",
        "material_category_reason",
        "material_layers",
        "material_response_disposition",
        "material_response_promoted",
        "metalness",
        "native_base_quality",
        "native_material_hints",
        "normal_strength",
        "opacity",
        "primary_material_layer",
        "roughness",
        "specular",
    }
)


def _safe_int(value: object, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return fallback


def _dotnet_material_sources(source: object) -> tuple[object, ...]:
    submeshes = tuple(getattr(source, "submeshes", ()) or ())
    if submeshes:
        return submeshes
    return tuple(getattr(source, "meshes", ()) or ())


def _dotnet_material_name(source: object) -> str:
    return str(
        getattr(source, "material", "")
        or getattr(source, "material_name", "")
        or ""
    )


def _dotnet_texture_name(source: object) -> str:
    return str(
        getattr(source, "texture", "")
        or getattr(source, "texture_name", "")
        or ""
    )


def copy_dotnet_preview_material_bindings(mesh: object, preview_model: object) -> int:
    """Copy resolved, non-image preview bindings onto a ParsedMesh-style source.

    This bridge deliberately copies material metadata only. Geometry stays owned by
    the MeshService snapshot and large QImage objects never cross worker threads.
    """

    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    preview_meshes = tuple(getattr(preview_model, "meshes", ()) or ())
    if not submeshes or not preview_meshes:
        return 0
    preview_source_asset_path = str(getattr(preview_model, "path", "") or "").strip()
    copied: set[int] = set()
    for fallback_index, preview_mesh in enumerate(preview_meshes):
        source_index = _safe_int(
            getattr(preview_mesh, "source_submesh_index", fallback_index),
            fallback_index,
        )
        if source_index < 0 and len(preview_meshes) == len(submeshes):
            source_index = fallback_index
        if source_index < 0 or source_index >= len(submeshes) or source_index in copied:
            continue
        submesh = submeshes[source_index]
        for attr in _DOTNET_PREVIEW_MATERIAL_ATTRS:
            if not hasattr(preview_mesh, attr):
                continue
            try:
                value = copy.deepcopy(getattr(preview_mesh, attr))
            except (TypeError, RuntimeError):
                value = getattr(preview_mesh, attr)
            setattr(submesh, attr, value)
        if preview_source_asset_path:
            setattr(submesh, "preview_source_asset_path", preview_source_asset_path)
        copied.add(source_index)
    return len(copied)


def _native_material_descriptor_path(descriptor: object) -> str:
    if not isinstance(descriptor, Mapping):
        return ""
    return str(
        descriptor.get("source_path", "")
        or descriptor.get("source_dds_path", "")
        or descriptor.get("source_texture_path", "")
        or ""
    ).strip()


def _native_packed_channel_semantics(value: object) -> tuple[str, ...]:
    text = str(value or "").strip().lower()
    if not text:
        return ()
    assignments: dict[str, str] = {}
    for item in text.split(","):
        channel, separator, semantic = item.strip().partition("=")
        if separator and channel in ("r", "g", "b", "a") and semantic:
            assignments[channel] = semantic.strip()
    if assignments:
        return tuple(assignments.get(channel, "") for channel in ("r", "g", "b", "a"))
    return tuple(item.strip() for item in text.split(",") if item.strip())


def apply_dotnet_native_material_batch_binding(target: object, batch: object) -> bool:
    """Apply a Native Preview Core material batch to a reference-only submesh.

    This consumes the native classifier and resolved DDS evidence. It deliberately
    uses ``base_color`` only for the manifest's explicit tint-only fallback so a
    normal textured material cannot acquire the native debug batch color.
    """

    if target is None or not isinstance(batch, Mapping):
        return False
    raw_dds = batch.get("dds_textures")
    dds_textures = raw_dds if isinstance(raw_dds, Mapping) else {}
    slot_attrs = {
        "base": ("preview_texture_path", "preview_texture_dds_path"),
        "normal": ("preview_normal_texture_path", "preview_normal_texture_dds_path"),
        "material": ("preview_material_texture_path", "preview_material_texture_dds_path"),
        "height": ("preview_height_texture_path", "preview_height_texture_dds_path"),
        "emissive": ("preview_emissive_texture_path", "preview_emissive_texture_dds_path"),
    }
    for slot, attrs in slot_attrs.items():
        path = _native_material_descriptor_path(dds_textures.get(slot))
        if not path:
            continue
        for attr in attrs:
            setattr(target, attr, path)

    raw_inputs = dds_textures.get("material_inputs")
    material_inputs = tuple(
        copy.deepcopy(dict(item))
        for item in raw_inputs
        if isinstance(item, Mapping)
    ) if isinstance(raw_inputs, Sequence) and not isinstance(raw_inputs, (str, bytes, bytearray)) else ()
    if not material_inputs:
        material_inputs = tuple(
            {
                **copy.deepcopy(dict(descriptor)),
                "slot": str(slot),
                "slot_kind": str(slot),
            }
            for slot, descriptor in dds_textures.items()
            if slot != "material_inputs" and isinstance(descriptor, Mapping)
        )
    if material_inputs:
        setattr(target, "preview_material_texture_inputs", material_inputs)

    material_descriptor = dds_textures.get("material")
    if isinstance(material_descriptor, Mapping):
        setattr(
            target,
            "preview_material_texture_subtype",
            str(material_descriptor.get("semantic_subtype", "") or ""),
        )
        packed = _native_packed_channel_semantics(material_descriptor.get("packed_channels"))
        if packed:
            setattr(target, "preview_material_texture_packed_channels", packed)

    shader_family = str(
        batch.get("shader_family", "")
        or batch.get("material_category", "")
        or ""
    ).strip()
    if shader_family:
        setattr(target, "preview_sidecar_shader_family", shader_family)
    setattr(target, "preview_alpha_mode", str(batch.get("alpha_mode", "") or ""))
    setattr(target, "preview_double_sided", bool(batch.get("two_sided", batch.get("double_sided", False))))
    setattr(target, "preview_normal_y_policy", str(batch.get("normal_y_policy", "") or ""))
    setattr(target, "preview_texture_flip_vertical", bool(batch.get("texture_flip_vertical", False)))
    texture_tint = _color3(batch.get("texture_tint"))
    if texture_tint is not None:
        setattr(target, "preview_texture_tint", texture_tint)
    try:
        setattr(target, "preview_normal_texture_strength", float(batch.get("normal_strength", 0.0) or 0.0))
    except (TypeError, ValueError, OverflowError):
        pass

    overrides = {
        str(key): copy.deepcopy(batch.get(key))
        for key in _DOTNET_NATIVE_MATERIAL_OVERRIDE_KEYS
        if key in batch
    }
    if shader_family:
        overrides["material_shader_family"] = shader_family
    if "alpha_threshold" in batch:
        overrides["alpha_cutoff"] = copy.deepcopy(batch.get("alpha_threshold"))
    if overrides:
        setattr(target, "preview_native_material_overrides", overrides)

    if bool(batch.get("base_tint_only_fallback", False)):
        color = _color3(batch.get("base_color"))
        if color is not None:
            setattr(target, "preview_color", color)
        setattr(target, "preview_texture_path", "")
        setattr(target, "preview_texture_dds_path", "")
    return True


def set_dotnet_preview_texture_flip_vertical(preview_model: object, flip_vertical: bool) -> int:
    """Apply the importer-owned V orientation to preview submeshes."""
    updated = 0
    for preview_mesh in tuple(getattr(preview_model, "meshes", ()) or ()):
        if not hasattr(preview_mesh, "preview_texture_flip_vertical"):
            continue
        preview_mesh.preview_texture_flip_vertical = bool(flip_vertical)
        updated += 1
    return updated
