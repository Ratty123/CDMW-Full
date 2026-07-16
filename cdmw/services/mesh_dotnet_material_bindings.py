"""Preview and native material binding bridges for the .NET renderer."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence

from cdmw.models import PreviewMaterialParameterInput, PreviewMaterialTextureInput
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
        "emissive_color_authoritative",
        "emissive_intensity",
        "emissive_scalar_mask",
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
        "roughness_hint_present",
        "specular",
        "specular_hint_present",
        "metalness_hint_present",
    }
)

_DOTNET_LAYER_ONLY_MATERIAL_ROLES = frozenset(
    {"damage", "decal", "detail", "dye", "grime", "layer", "overlay"}
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


def _native_material_parameter_input(value: object) -> PreviewMaterialParameterInput | None:
    if isinstance(value, PreviewMaterialParameterInput):
        return copy.deepcopy(value)
    if not isinstance(value, Mapping):
        return None
    fields = PreviewMaterialParameterInput.__dataclass_fields__
    payload = {str(key): copy.deepcopy(item) for key, item in value.items() if key in fields}
    color = payload.get("color_value")
    if isinstance(color, Sequence) and not isinstance(color, (str, bytes, bytearray)):
        payload["color_value"] = tuple(color)
    return PreviewMaterialParameterInput(**payload)


def _native_material_texture_input(value: object) -> PreviewMaterialTextureInput | None:
    """Hydrate a native-manifest descriptor into the production graph type."""

    if isinstance(value, PreviewMaterialTextureInput):
        return copy.deepcopy(value)
    if not isinstance(value, Mapping):
        return None
    fields = PreviewMaterialTextureInput.__dataclass_fields__
    payload = {str(key): copy.deepcopy(item) for key, item in value.items() if key in fields}
    payload["slot_kind"] = str(
        payload.get("slot_kind") or value.get("slot") or "material"
    ).strip()
    source_path = str(
        value.get("source_path", "")
        or payload.get("source_dds_path", "")
        or payload.get("source_texture_path", "")
        or payload.get("preview_texture_path", "")
        or ""
    ).strip()
    if source_path:
        for field_name in (
            "source_dds_path",
            "source_texture_path",
            "preview_texture_path",
        ):
            if not str(payload.get(field_name, "") or "").strip():
                payload[field_name] = source_path
    for field_name in ("packed_channels", "blend_flags"):
        raw_items = payload.get(field_name, ())
        if isinstance(raw_items, Sequence) and not isinstance(
            raw_items, (str, bytes, bytearray)
        ):
            payload[field_name] = tuple(str(item or "") for item in raw_items)
        else:
            payload[field_name] = ()
    raw_parameters = value.get("material_parameters", ())
    if isinstance(raw_parameters, Sequence) and not isinstance(
        raw_parameters, (str, bytes, bytearray)
    ):
        payload["material_parameters"] = tuple(
            parameter
            for parameter in (
                _native_material_parameter_input(item) for item in raw_parameters
            )
            if parameter is not None
        )
    return PreviewMaterialTextureInput(**payload)


def _native_material_input_is_primary_base(value: object) -> bool:
    values = (
        value
        if isinstance(value, Mapping)
        else vars(value)
        if hasattr(value, "__dict__")
        else {}
    )

    def field(name: str) -> str:
        return str(values.get(name, "") or getattr(value, name, "") or "").strip()

    layer_role = field("layer_role").casefold()
    layer_channel = field("layer_channel").casefold()
    disposition = field("disposition").casefold()
    if (
        layer_role in _DOTNET_LAYER_ONLY_MATERIAL_ROLES
        or layer_channel
        or disposition == "layer_only"
    ):
        return False
    slot = field("slot_kind").casefold() or field("slot").casefold()
    semantic = field("semantic_type").casefold()
    if slot in {"albedo", "base", "base_color", "color", "diffuse"}:
        return True
    if semantic in {"albedo", "base", "base_color", "diffuse"}:
        return True
    parameter_name = field("parameter_name").casefold()
    return semantic == "color" and any(
        token in parameter_name for token in ("albedo", "basecolor", "base_color", "diffuse")
    )


def _native_material_input_has_primary_base_source(value: object) -> bool:
    if not _native_material_input_is_primary_base(value):
        return False
    values = (
        value
        if isinstance(value, Mapping)
        else vars(value)
        if hasattr(value, "__dict__")
        else {}
    )
    return any(
        str(values.get(name, "") or getattr(value, name, "") or "").strip()
        for name in (
            "source_path",
            "source_dds_path",
            "source_texture_path",
            "preview_texture_path",
        )
    )


def _native_batch_explicitly_omits_base_source(
    batch: Mapping[str, object],
    dds_textures: Mapping[str, object],
) -> bool:
    """Return whether a complete native batch explicitly resolved no base source."""

    raw_textures = batch.get("textures")
    if not isinstance(raw_textures, Mapping) or "base" not in raw_textures:
        return False
    if str(raw_textures.get("base", "") or "").strip():
        return False
    if _native_material_descriptor_path(dds_textures.get("base")):
        return False
    raw_inputs = dds_textures.get("material_inputs")
    if isinstance(raw_inputs, Sequence) and not isinstance(
        raw_inputs,
        (str, bytes, bytearray),
    ):
        return not any(
            _native_material_input_has_primary_base_source(item)
            for item in raw_inputs
        )
    return True


def _clear_dotnet_primary_base_bindings(target: object) -> None:
    for attr in (
        "texture",
        "preview_texture_path",
        "preview_texture_dds_path",
        "preview_base_texture_default_path",
        "preview_base_texture_default_name",
    ):
        setattr(target, attr, "")
    existing_inputs = tuple(
        getattr(target, "preview_material_texture_inputs", ()) or ()
    )
    if existing_inputs:
        setattr(
            target,
            "preview_material_texture_inputs",
            tuple(
                item
                for item in existing_inputs
                if not _native_material_input_is_primary_base(item)
            ),
        )


def apply_dotnet_native_material_batch_binding(target: object, batch: object) -> bool:
    """Apply one authoritative Native Preview Core material batch to a submesh.

    This consumes the native classifier, resolved DDS evidence, and distinct base
    color/base-strength/texture-tint contract without reclassifying the material.
    """

    if target is None or not isinstance(batch, Mapping):
        return False
    raw_dds = batch.get("dds_textures")
    dds_textures = raw_dds if isinstance(raw_dds, Mapping) else {}
    tint_only_base = bool(batch.get("base_tint_only_fallback", False)) or (
        _native_batch_explicitly_omits_base_source(batch, dds_textures)
    )
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
        typed
        for typed in (
            _native_material_texture_input(item)
            for item in raw_inputs
        )
        if typed is not None
    ) if isinstance(raw_inputs, Sequence) and not isinstance(raw_inputs, (str, bytes, bytearray)) else ()
    if not material_inputs:
        material_inputs = tuple(
            typed
            for slot, descriptor in dds_textures.items()
            if slot != "material_inputs" and isinstance(descriptor, Mapping)
            for typed in (
                _native_material_texture_input(
                    {
                        **copy.deepcopy(dict(descriptor)),
                        "slot": str(slot),
                        "slot_kind": str(slot),
                    }
                ),
            )
            if typed is not None
        )
    # Prepared preview inputs own the source material graph. Native-manifest
    # descriptors are post-package transport evidence and must not replace it.
    existing_material_inputs = tuple(
        getattr(target, "preview_material_texture_inputs", ()) or ()
    )
    if material_inputs and not existing_material_inputs:
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
        batch.get("material_shader_family", "")
        or batch.get("shader_family", "")
        or batch.get("material_category", "")
        or ""
    ).strip()
    if shader_family:
        setattr(target, "preview_sidecar_shader_family", shader_family)
    setattr(target, "preview_alpha_mode", str(batch.get("alpha_mode", "") or ""))
    setattr(target, "preview_double_sided", bool(batch.get("two_sided", batch.get("double_sided", False))))
    setattr(target, "preview_normal_y_policy", str(batch.get("normal_y_policy", "") or ""))
    setattr(target, "preview_texture_flip_vertical", bool(batch.get("texture_flip_vertical", False)))
    base_color = _color3(batch.get("base_color"))
    if base_color is not None:
        setattr(target, "preview_color", base_color)
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
    if tint_only_base:
        overrides["base_tint_only_fallback"] = True
    if overrides:
        setattr(target, "preview_native_material_overrides", overrides)

    if tint_only_base:
        _clear_dotnet_primary_base_bindings(target)
    return True


def apply_dotnet_native_material_batch_bindings(mesh: object, batches: object) -> int:
    """Apply direct native batches by authoritative local-submesh identity."""

    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    if not submeshes or not isinstance(batches, Sequence) or isinstance(batches, (str, bytes, bytearray)):
        return 0
    applied: set[int] = set()
    for fallback_index, batch in enumerate(batches):
        if not isinstance(batch, Mapping):
            continue
        identity = batch.get("editor_identity")
        identity = identity if isinstance(identity, Mapping) else {}
        if bool(identity.get("prefab_component", False)) or _safe_int(identity.get("source_component_index", 0), 0) != 0:
            continue
        local_index = _safe_int(
            identity.get("source_local_submesh_index", identity.get("source_submesh_index", fallback_index)),
            fallback_index,
        )
        if local_index < 0 or local_index >= len(submeshes) or local_index in applied:
            continue
        if apply_dotnet_native_material_batch_binding(submeshes[local_index], batch):
            applied.add(local_index)
    return len(applied)


def set_dotnet_preview_texture_flip_vertical(preview_model: object, flip_vertical: bool) -> int:
    """Apply the importer-owned V orientation to preview submeshes."""
    updated = 0
    for preview_mesh in tuple(getattr(preview_model, "meshes", ()) or ()):
        if not hasattr(preview_mesh, "preview_texture_flip_vertical"):
            continue
        preview_mesh.preview_texture_flip_vertical = bool(flip_vertical)
        updated += 1
    return updated
