"""Resident .NET material-state snapshots; no package or renderer ownership."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from cdmw.domain.mesh.material_resource_policy import (
    canonical_material_channel,
    mesh_material_resource_policy,
)
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.modding.asset_replacement import infer_cd_texture_role_from_path
from cdmw.rendering.crimson_shader_registry import (
    decode_crimson_texture_binding,
    infer_shader_family_contract,
    normalize_shader_family,
)


_COMPONENT_NAMES = ("r", "g", "b", "a")

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
        if separator and channel in _COMPONENT_NAMES and semantic:
            assignments[channel] = semantic.strip()
    if assignments:
        return tuple(assignments.get(channel, "") for channel in _COMPONENT_NAMES)
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


def _dotnet_crimson_material_input_decode(
    source: object,
    item: object,
    values: Mapping[str, object],
) -> dict[str, object]:
    def field(name: str, fallback: object = "") -> object:
        return values.get(name, fallback) or getattr(item, name, fallback)

    return decode_crimson_texture_binding(
        shader_family=(
            getattr(source, "preview_sidecar_shader_family", "")
            or field("shader_family")
        ),
        parameter_name=field("parameter_name"),
        source_path=(
            field("source_dds_path")
            or field("source_texture_path")
            or field("preview_texture_path")
        ),
        slot_name=field("semantic_type") or field("slot_kind") or "material",
        semantic_subtype=field("semantic_subtype"),
        packed_channels=tuple(field("packed_channels", ()) or ()),
        layer_channel=field("layer_channel"),
        blend_flags=tuple(field("blend_flags", ()) or ()),
        sidecar_kind=field("sidecar_kind"),
        parameter_declared_by=field("parameter_declared_by"),
    )


def _dotnet_material_input_channels(source: object | None) -> dict[str, str]:
    result: dict[str, str] = {}
    if source is None:
        return result
    overrides = getattr(source, "preview_native_material_overrides", {}) or {}
    tint_only_base = bool(
        isinstance(overrides, Mapping) and overrides.get("base_tint_only_fallback", False)
    )
    layer_only_roles = {"damage", "decal", "detail", "dye", "grime", "layer", "overlay"}
    for item in tuple(getattr(source, "preview_material_texture_inputs", ()) or ()):
        values = item if isinstance(item, Mapping) else vars(item) if hasattr(item, "__dict__") else {}
        semantic = str(
            values.get("semantic_type", "")
            or values.get("slot_kind", "")
            or getattr(item, "semantic_type", "")
            or getattr(item, "slot_kind", "")
            or ""
        ).strip().lower()
        semantic_subtype = str(
            values.get("semantic_subtype", "")
            or getattr(item, "semantic_subtype", "")
            or ""
        ).strip().lower()
        layer_role = str(
            values.get("layer_role", "")
            or getattr(item, "layer_role", "")
            or ""
        ).strip().lower()
        parameter_name = str(
            values.get("parameter_name", "")
            or getattr(item, "parameter_name", "")
            or ""
        ).strip().lower()
        # Preserve the source DDS when one is available. Preview PNGs are useful
        # fallbacks, but selecting them first discards the source format, mip
        # chain, precision, and color-space view before Vortice sees the asset.
        candidates = tuple(
            str(values.get(name, "") or getattr(item, name, "") or "").strip()
            for name in (
                "source_dds_path",
                "source_texture_path",
                "source_path",
                "preview_texture_path",
            )
        )
        path = next((value for value in candidates if value and Path(value).expanduser().is_file()), "")
        if not path:
            path = next((value for value in candidates if value), "")
        semantic = {"base_color": "base", "color": "base", "metalness": "metallic"}.get(
            semantic, semantic
        )
        decode = _dotnet_crimson_material_input_decode(source, item, values)
        promoted_channels = decode.get("promoted_channels")
        if (
            path
            and str(decode.get("disposition", "") or "") == "promoted"
            and isinstance(promoted_channels, Mapping)
        ):
            for promoted_channel in promoted_channels:
                channel = canonical_material_channel(str(promoted_channel))
                if channel:
                    result.setdefault(channel, path)
        is_layer_only = layer_role in layer_only_roles
        is_base_channel = semantic in {"albedo", "base", "diffuse"}
        if semantic and path and semantic not in result and not is_layer_only and not (tint_only_base and is_base_channel):
            result[semantic] = path
        if path and (
            semantic in {"mask", "layer_mask", "material_mask"}
            or "mask" in semantic_subtype
            or "mask" in layer_role
            or "mask" in parameter_name
        ):
            result.setdefault("layer_mask", path)
    return result


def _material_texture_metadata(source: object | None) -> tuple[str, tuple[str, ...]]:
    if source is None:
        return "", ()
    subtype = str(getattr(source, "preview_material_texture_subtype", "") or "").strip().lower()
    packed = tuple(
        str(value or "").strip().lower()
        for value in tuple(getattr(source, "preview_material_texture_packed_channels", ()) or ())
        if str(value or "").strip()
    )
    for item in tuple(getattr(source, "preview_material_texture_inputs", ()) or ()):
        values = item if isinstance(item, Mapping) else vars(item) if hasattr(item, "__dict__") else {}
        semantic = str(
            values.get("semantic_type", "")
            or values.get("slot_kind", "")
            or getattr(item, "semantic_type", "")
            or getattr(item, "slot_kind", "")
            or ""
        ).strip().lower()
        if semantic != "material":
            continue
        subtype = str(
            values.get("semantic_subtype", "")
            or getattr(item, "semantic_subtype", "")
            or subtype
        ).strip().lower()
        item_packed = tuple(
            str(value or "").strip().lower()
            for value in tuple(values.get("packed_channels", ()) or getattr(item, "packed_channels", ()) or ())
            if str(value or "").strip()
        )
        if item_packed:
            packed = item_packed
        break
    return subtype, packed


def _dotnet_material_channel_components(source: object | None) -> dict[str, str]:
    subtype, packed = _material_texture_metadata(source)
    normalized = tuple(value.replace("metalness", "metallic") for value in packed)
    if subtype in {"metallic_roughness", "metallicroughness", "gltf_metallic_roughness"}:
        result: dict[str, str] = {"roughness": "g", "metallic": "b"}
    elif subtype in {"orm", "arm"}:
        result = {"roughness": "g", "metallic": "b"}
    elif subtype == "rma":
        result = {"roughness": "r", "metallic": "g"}
    elif subtype == "mra":
        result = {"metallic": "r", "roughness": "g"}
    elif subtype in {"specular_glossiness", "specularglossiness", "gltf_specular_glossiness"}:
        result = {"roughness": "a", "specular": "rgb"}
    elif normalized[:2] == ("roughness", "metallic"):
        result = {"roughness": "g", "metallic": "b"}
    else:
        result = {}
        for index, semantic in enumerate(normalized[:4]):
            if semantic in {"roughness", "metallic", "specular"}:
                result.setdefault(semantic, _COMPONENT_NAMES[index])
    for item in tuple(getattr(source, "preview_material_texture_inputs", ()) or ()):
        values = item if isinstance(item, Mapping) else vars(item) if hasattr(item, "__dict__") else {}
        decode = _dotnet_crimson_material_input_decode(source, item, values)
        promoted_channels = decode.get("promoted_channels")
        if (
            str(decode.get("disposition", "") or "") == "promoted"
            and isinstance(promoted_channels, Mapping)
        ):
            for raw_semantic, raw_component in promoted_channels.items():
                semantic = canonical_material_channel(str(raw_semantic))
                component = str(raw_component or "").strip().casefold()
                if semantic and component in _COMPONENT_NAMES:
                    result.setdefault(semantic, component)
        semantic = str(
            values.get("semantic_type", "")
            or values.get("slot_kind", "")
            or getattr(item, "semantic_type", "")
            or getattr(item, "slot_kind", "")
            or ""
        ).strip().lower()
        subtype = str(
            values.get("semantic_subtype", "")
            or getattr(item, "semantic_subtype", "")
            or ""
        ).strip().lower()
        parameter_name = str(
            values.get("parameter_name", "")
            or getattr(item, "parameter_name", "")
            or ""
        ).strip().lower()
        if semantic not in {"mask", "layer_mask", "material_mask"} and "mask" not in subtype and "mask" not in parameter_name:
            continue
        component = str(
            values.get("layer_channel", "")
            or getattr(item, "layer_channel", "")
            or "r"
        ).strip().lower()
        result["layer_mask"] = component if component in _COMPONENT_NAMES else "r"
        break
    return result


def _dotnet_material_normal_y_policy(source: object | None) -> str:
    """Translate source normal-space evidence into one explicit shader policy."""

    if source is None:
        return "preserve"
    explicit_policy = str(getattr(source, "preview_normal_y_policy", "") or "").strip().casefold()
    if explicit_policy in {"invert_green_for_directx", "shader_invert_legacy_compat"}:
        return "invert_green_for_directx"
    if explicit_policy in {"preserve", "directx", "legacy_no_flip"}:
        return "preserve"
    explicit = str(
        getattr(source, "preview_normal_texture_space", "")
        or getattr(source, "normal_space", "")
        or ""
    ).strip().casefold()
    if explicit in {"green_up", "ogl"}:
        return "invert_green_for_directx"
    if explicit in {"directx", "green_down", "dx"}:
        return "preserve"
    for item in tuple(getattr(source, "preview_material_texture_inputs", ()) or ()):
        values = item if isinstance(item, Mapping) else vars(item) if hasattr(item, "__dict__") else {}
        semantic = str(
            values.get("semantic_type", "")
            or values.get("slot_kind", "")
            or getattr(item, "semantic_type", "")
            or getattr(item, "slot_kind", "")
            or ""
        ).strip().casefold()
        if semantic != "normal":
            continue
        normal_space = str(
            values.get("normal_space", "") or getattr(item, "normal_space", "") or ""
        ).strip().casefold()
        confidence = str(
            values.get("confidence", "") or getattr(item, "confidence", "") or ""
        ).strip().casefold()
        path = str(
            values.get("preview_texture_path", "")
            or values.get("source_path", "")
            or values.get("source_texture_path", "")
            or getattr(item, "preview_texture_path", "")
            or getattr(item, "source_path", "")
            or getattr(item, "source_texture_path", "")
            or ""
        ).strip().casefold()
        if normal_space in {"green_up", "ogl"} or confidence == "gltf" or "green_up" in path:
            return "invert_green_for_directx"
        if normal_space in {"directx", "green_down", "dx"} or "directx" in path or "_dx." in path:
            return "preserve"
    return "preserve"


def _material_parameter_value(source: object | None, parameter_name: str) -> object | None:
    wanted = parameter_name.strip().casefold()
    for item in tuple(getattr(source, "preview_material_parameters", ()) or ()):
        values = item if isinstance(item, Mapping) else vars(item) if hasattr(item, "__dict__") else {}
        name = str(values.get("parameter_name", "") or getattr(item, "parameter_name", "") or "").strip().casefold()
        if name != wanted:
            continue
        color = tuple(values.get("color_value", ()) or getattr(item, "color_value", ()) or ())
        if len(color) >= 3:
            return tuple(color[:3])
        numeric = values.get("numeric_value", getattr(item, "numeric_value", None))
        if numeric is not None:
            return numeric
        return values.get("value", getattr(item, "value", None))
    return None


def _finite_float(value: object, *, minimum: float, maximum: float) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return max(minimum, min(maximum, number)) if math.isfinite(number) else None


def _color3(value: object) -> tuple[float, float, float] | None:
    if isinstance(value, str) and len(value.strip()) == 7 and value.strip().startswith("#"):
        try:
            return tuple(int(value.strip()[offset : offset + 2], 16) / 255.0 for offset in (1, 3, 5))  # type: ignore[return-value]
        except ValueError:
            return None
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) < 3:
        return None
    components = tuple(_finite_float(component, minimum=0.0, maximum=2.0) for component in value[:3])
    return components if all(component is not None for component in components) else None  # type: ignore[return-value]


def _dotnet_initial_material_parameters(
    source: object | None,
    resolved_channels: Mapping[str, str],
) -> dict[str, object]:
    if source is None:
        return {}
    result: dict[str, object] = {}
    color = _color3(getattr(source, "preview_color", ()))
    if color is not None and color != (1.0, 1.0, 1.0):
        result["tint_color"] = list(color)
    overrides = getattr(source, "preview_native_material_overrides", {})
    overrides = overrides if isinstance(overrides, Mapping) else {}
    subtype, _packed = _material_texture_metadata(source)
    is_gltf = subtype in {
        "metallic_roughness",
        "metallicroughness",
        "gltf_metallic_roughness",
        "specular_glossiness",
        "specularglossiness",
        "gltf_specular_glossiness",
    } or any(
        str(
            (item if isinstance(item, Mapping) else vars(item) if hasattr(item, "__dict__") else {}).get(
                "parameter_name", getattr(item, "parameter_name", "")
            )
            or ""
        ).startswith("_gltf")
        for item in tuple(getattr(source, "preview_material_parameters", ()) or ())
    )
    roughness = _finite_float(
        overrides.get("roughness", _material_parameter_value(source, "_roughnessFactor")),
        minimum=0.0,
        maximum=1.0,
    )
    metallic = _finite_float(
        overrides.get("metalness", overrides.get("metallic", _material_parameter_value(source, "_metallicFactor"))),
        minimum=0.0,
        maximum=1.0,
    )
    if is_gltf and roughness is None and "roughness" not in resolved_channels:
        roughness = 1.0
    if is_gltf and metallic is None and "metallic" not in resolved_channels:
        metallic = 1.0
    specular = _finite_float(
        overrides.get("specular", _material_parameter_value(source, "_specularFactor")),
        minimum=0.0,
        maximum=1.0,
    )
    if roughness is not None:
        result["roughness_scale" if "roughness" in resolved_channels else "roughness"] = roughness
    if metallic is not None:
        result["metalness_scale" if "metallic" in resolved_channels else "metalness"] = metallic
    if specular is not None and abs(specular - 1.0) > 1e-6:
        result["specular"] = specular
    if subtype in {"specular_glossiness", "specularglossiness", "gltf_specular_glossiness"}:
        result["roughness_inverted"] = True
    emissive_color = _color3(
        overrides.get("emissive_color", _material_parameter_value(source, "_emissiveColor"))
    )
    emissive_intensity = _finite_float(
        overrides.get("emissive_intensity", _material_parameter_value(source, "_emissiveIntensity")),
        minimum=0.0,
        maximum=32.0,
    )
    if emissive_color is not None:
        result["emissive_color"] = list(emissive_color)
    if emissive_intensity is not None:
        result["emissive_intensity"] = emissive_intensity
    return result


def _dotnet_resolved_texture_channels(source: object | None) -> dict[str, str]:
    if source is None:
        return {}
    texture = str(getattr(source, "texture", "") or "").strip()
    result = ({channel: texture for channel in ("base", "albedo", "diffuse")} if texture else {})
    material_input_channels = _dotnet_material_input_channels(source)
    result.update(material_input_channels)
    pairs = {
        "base": ("preview_texture_dds_path", "preview_texture_path", "preview_base_texture_default_path"),
        "albedo": ("preview_texture_dds_path", "preview_texture_path", "preview_base_texture_default_path"),
        "diffuse": ("preview_texture_dds_path", "preview_texture_path", "preview_base_texture_default_path"),
        "normal": ("preview_normal_texture_dds_path", "preview_normal_texture_path", "preview_normal_texture_default_path"),
        "material": ("preview_material_texture_dds_path", "preview_material_texture_path", "preview_material_texture_default_path"),
        "height": ("preview_height_texture_dds_path", "preview_height_texture_path", "preview_height_texture_default_path"),
        "emissive": ("preview_emissive_texture_dds_path", "preview_emissive_texture_path", "preview_emissive_texture_default_path"),
    }
    for channel, attrs in pairs.items():
        for attr in attrs:
            value = str(getattr(source, attr, "") or "").strip()
            if value:
                result[channel] = value
                break
    # Base/albedo/diffuse are transport aliases for one color input. A resolved
    # material input (especially a source DDS) must replace every alias instead
    # of coexisting with a stale parser-level ``texture`` fallback. Otherwise
    # the manifest can load two different color resources for one material and
    # diagnostics/report ordering decides which one appears authoritative.
    preferred_color = next(
        (
            material_input_channels[channel]
            for channel in ("base", "albedo", "diffuse")
            if material_input_channels.get(channel)
        ),
        "",
    ) or next(
        (result[channel] for channel in ("base", "albedo", "diffuse") if result.get(channel)),
        "",
    )
    if preferred_color:
        for channel in ("base", "albedo", "diffuse"):
            result[channel] = preferred_color
    _reroute_technical_color_fallback(source, result)
    material_path = result.get("material", "")
    if material_path:
        for channel in _dotnet_material_channel_components(source):
            result.setdefault(channel, material_path)
    return result


def _reroute_technical_color_fallback(source: object, channels: dict[str, str]) -> None:
    """Keep clearly named Crimson support maps out of the base-color slot.

    Native sidecar or source-format bindings remain authoritative. This only
    repairs legacy/fallback paths where a parser-level texture reference was
    treated as color despite an explicit Crimson role suffix such as ``_mg``.
    """

    color_paths = tuple(
        dict.fromkeys(
            str(channels.get(channel, "") or "").strip()
            for channel in ("base", "albedo", "diffuse")
            if str(channels.get(channel, "") or "").strip()
        )
    )
    for path in color_paths:
        role = infer_cd_texture_role_from_path(path)
        if role in {"", "base"} or _has_authoritative_color_input(source, path):
            continue
        for channel in ("base", "albedo", "diffuse"):
            if _same_texture_reference(channels.get(channel, ""), path):
                channels.pop(channel, None)
        if role == "normal":
            channels.setdefault("normal", path)
        elif role == "height":
            channels.setdefault("height", path)
        elif role == "emissive":
            channels.setdefault("emissive", path)
        elif role == "detail_mask":
            channels.setdefault("layer_mask", path)
        elif role == "material_mask":
            channels.setdefault("material", path)
        elif role == "material":
            stem = Path(path.replace("\\", "/")).stem.casefold()
            if stem.endswith(("_sp", "_spec", "_specular")):
                channels.setdefault("specular", path)
            else:
                channels.setdefault("material", path)
        elif role == "flow":
            channels.setdefault("flow", path)


def _has_authoritative_color_input(source: object, path: str) -> bool:
    for item in tuple(getattr(source, "preview_material_texture_inputs", ()) or ()):
        values = item if isinstance(item, Mapping) else vars(item) if hasattr(item, "__dict__") else {}
        semantic = canonical_material_channel(
            str(
                values.get("semantic_type", "")
                or values.get("slot_kind", "")
                or getattr(item, "semantic_type", "")
                or getattr(item, "slot_kind", "")
                or ""
            )
        )
        if semantic != "base":
            continue
        candidate = next(
            (
                str(values.get(name, "") or getattr(item, name, "") or "").strip()
                for name in ("source_dds_path", "source_texture_path", "source_path", "preview_texture_path")
                if str(values.get(name, "") or getattr(item, name, "") or "").strip()
            ),
            "",
        )
        if not _same_texture_reference(candidate, path):
            continue
        confidence = str(values.get("confidence", "") or getattr(item, "confidence", "") or "").strip().casefold()
        declared_by = str(
            values.get("parameter_declared_by", "")
            or getattr(item, "parameter_declared_by", "")
            or ""
        ).strip()
        sidecar_kind = str(values.get("sidecar_kind", "") or getattr(item, "sidecar_kind", "") or "").strip()
        if declared_by or sidecar_kind or confidence in {
            "authoritative",
            "exact",
            "gltf",
            "manual",
            "scene",
            "shader_parameter_rule",
        }:
            return True
    return False


def _same_texture_reference(left: object, right: object) -> bool:
    return str(left or "").replace("\\", "/").strip().casefold() == str(right or "").replace(
        "\\", "/"
    ).strip().casefold()


def _normalized_color_space(value: object) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized in {"true", "1", "yes", "srgb", "s_rgb", "color"}:
        return "srgb"
    if normalized in {"false", "0", "no", "linear", "data", "raw"}:
        return "linear"
    return ""


def _dotnet_material_semantic_contract(
    source: object | None,
    resolved_channels: Mapping[str, str] | None = None,
    *,
    source_asset_path: str = "",
) -> dict[str, object]:
    """Translate existing material evidence without inventing shader parity."""

    channels = dict(resolved_channels or _dotnet_resolved_texture_channels(source))
    raw_family = str(getattr(source, "preview_sidecar_shader_family", "") or "").strip()
    inputs = tuple(getattr(source, "preview_material_texture_inputs", ()) or ())
    if not raw_family:
        raw_family = next(
            (
                str(
                    (item.get("shader_family", "") if isinstance(item, Mapping) else getattr(item, "shader_family", ""))
                    or ""
                ).strip()
                for item in inputs
                if str(
                    (item.get("shader_family", "") if isinstance(item, Mapping) else getattr(item, "shader_family", ""))
                    or ""
                ).strip()
            ),
            "",
        )
    material_name = _dotnet_material_name(source) if source is not None else ""
    resolved_asset_path = str(
        getattr(source, "preview_source_asset_path", "") if source is not None else ""
    ).strip() or str(source_asset_path or "").strip()
    overrides = getattr(source, "preview_native_material_overrides", {}) or {}
    has_emissive_factor = bool(
        isinstance(overrides, Mapping)
        and (
            any(
                key in overrides and overrides.get(key) not in (None, "")
                for key in ("emissive_color", "emissive_intensity")
            )
            or str(overrides.get("material_role", "") or "").strip().casefold()
            in {"emissive", "glow"}
        )
    )
    family_contract = infer_shader_family_contract(
        raw_family,
        material_name=material_name,
        asset_path=resolved_asset_path,
        has_emissive=bool(channels.get("emissive")) or has_emissive_factor,
    )
    shader_family = normalize_shader_family(family_contract.get("family", "")) or "generic"
    family_authority = str(family_contract.get("authority", "guess") or "guess")
    channel_color_spaces = {
        str(channel): "srgb" if canonical_material_channel(channel) in {"base", "emissive"} else "linear"
        for channel in channels
    }
    channel_authorities = {
        str(channel): family_authority
        for channel in channels
    }
    layer_bindings: list[dict[str, object]] = []
    for item in inputs:
        values = item if isinstance(item, Mapping) else vars(item) if hasattr(item, "__dict__") else {}
        semantic = str(
            values.get("semantic_type", "")
            or values.get("slot_kind", "")
            or getattr(item, "semantic_type", "")
            or getattr(item, "slot_kind", "")
            or ""
        ).strip().casefold()
        parameter_name = str(
            values.get("parameter_name", "") or getattr(item, "parameter_name", "") or ""
        ).strip()
        decode = decode_crimson_texture_binding(
            shader_family=raw_family,
            parameter_name=parameter_name,
            source_path=str(
                values.get("source_dds_path", "")
                or values.get("source_texture_path", "")
                or values.get("preview_texture_path", "")
                or getattr(item, "source_dds_path", "")
                or getattr(item, "source_texture_path", "")
                or getattr(item, "preview_texture_path", "")
                or ""
            ),
            slot_name=semantic or "material",
            semantic_subtype=str(
                values.get("semantic_subtype", "") or getattr(item, "semantic_subtype", "") or ""
            ),
            packed_channels=tuple(
                values.get("packed_channels", ()) or getattr(item, "packed_channels", ()) or ()
            ),
            layer_channel=str(
                values.get("layer_channel", "") or getattr(item, "layer_channel", "") or ""
            ),
            blend_flags=tuple(values.get("blend_flags", ()) or getattr(item, "blend_flags", ()) or ()),
            sidecar_kind=str(values.get("sidecar_kind", "") or getattr(item, "sidecar_kind", "") or ""),
            parameter_declared_by=str(
                values.get("parameter_declared_by", "")
                or getattr(item, "parameter_declared_by", "")
                or ""
            ),
        )
        channel = canonical_material_channel(str(decode.get("slot", "") or semantic))
        if channel in channels:
            explicit_space = _normalized_color_space(
                values.get("srgb_mode", "") or getattr(item, "srgb_mode", "") or ""
            )
            registry_space = _normalized_color_space(decode.get("srgb", ""))
            channel_color_spaces[channel] = explicit_space or registry_space or channel_color_spaces[channel]
            channel_authorities[channel] = str(decode.get("authority", "") or channel_authorities[channel])
        layer_role = str(values.get("layer_role", "") or getattr(item, "layer_role", "") or "").strip()
        layer_channel = str(
            values.get("layer_channel", "") or getattr(item, "layer_channel", "") or ""
        ).strip()
        if layer_role or layer_channel or str(decode.get("disposition", "")) == "layer_only":
            layer_bindings.append(
                {
                    "parameter": parameter_name,
                    "role": layer_role,
                    "channel": layer_channel,
                    "slot": str(decode.get("slot", "") or semantic),
                    "authority": str(decode.get("authority", "") or "guess"),
                    "disposition": str(decode.get("disposition", "") or ""),
                }
            )

    raw_alpha_mode = str(getattr(source, "preview_alpha_mode", "") or "").strip().casefold()
    alpha_mode = {
        "mask": "cutout",
        "alpha_cutout": "cutout",
        "coverage": "cutout",
        "transparent": "blend",
        "alpha": "blend",
    }.get(raw_alpha_mode, raw_alpha_mode or "opaque")
    if raw_alpha_mode:
        alpha_authority = "sidecar"
        alpha_reason = f"source declared alpha mode {raw_alpha_mode}"
    elif shader_family == "hair" and any(
        channels.get(channel) for channel in ("base", "albedo", "diffuse")
    ):
        alpha_mode = "cutout"
        alpha_authority = "inferred"
        alpha_reason = "hair/fur material with a bound color texture uses conservative alpha cutout"
    else:
        alpha_authority = "guess"
        alpha_reason = "no source alpha contract was available; opaque fallback retained"
    alpha_cutoff = 0.5
    if isinstance(overrides, Mapping):
        for name in ("alpha_cutoff", "alpha_clip_threshold", "alpha_threshold"):
            candidate = _finite_float(overrides.get(name), minimum=0.0, maximum=1.0)
            if candidate is not None:
                alpha_cutoff = candidate
                break
    opacity_factor: float | None = None
    if isinstance(overrides, Mapping):
        opacity_factor = _finite_float(overrides.get("opacity"), minimum=0.0, maximum=1.0)
    if opacity_factor is None:
        opacity_parameter_names = {
            "alphafactor",
            "basecoloralphafactor",
            "diffusealphafactor",
            "gltfbasecoloralphafactor",
            "gltfdiffusealphafactor",
            "opacity",
            "opacityfactor",
        }
        for parameter in tuple(getattr(source, "preview_material_parameters", ()) or ()):
            values = parameter if isinstance(parameter, Mapping) else vars(parameter) if hasattr(parameter, "__dict__") else {}
            name = re.sub(
                r"[^a-z0-9]+",
                "",
                str(values.get("parameter_name", "") or getattr(parameter, "parameter_name", "") or "").casefold(),
            )
            if name not in opacity_parameter_names:
                continue
            opacity_factor = _finite_float(
                values.get("numeric_value", None)
                if values.get("numeric_value", None) is not None
                else getattr(parameter, "numeric_value", None),
                minimum=0.0,
                maximum=1.0,
            )
            if opacity_factor is None:
                opacity_factor = _finite_float(
                    values.get("value", None) if "value" in values else getattr(parameter, "value", None),
                    minimum=0.0,
                    maximum=1.0,
                )
            if opacity_factor is not None:
                break
    if opacity_factor is None:
        opacity_factor = _finite_float(
            getattr(source, "preview_vertex_alpha_mean", None),
            minimum=0.0,
            maximum=1.0,
        )
    if opacity_factor is None:
        opacity_factor = 1.0
    explicit_double_sided = bool(getattr(source, "preview_double_sided", False))
    inferred_hair_double_sided = (
        not explicit_double_sided
        and shader_family == "hair"
        and family_authority == "inferred"
    )
    double_sided = explicit_double_sided or inferred_hair_double_sided
    if explicit_double_sided:
        double_sided_authority = "sidecar"
        double_sided_reason = "source declared a double-sided material"
    elif inferred_hair_double_sided:
        double_sided_authority = "inferred"
        double_sided_reason = "inferred hair/fur cards require visible back faces"
    else:
        double_sided_authority = "guess"
        double_sided_reason = "no source double-sided contract was available"

    unsupported_features: list[str] = []
    if alpha_mode == "blend":
        unsupported_features.append("per_triangle_alpha_blend_sorting")
    if layer_bindings:
        unsupported_features.append("shader_family_layer_graph")
    if shader_family in {"hair", "fur"}:
        unsupported_features.append("hair_fur_anisotropy_and_flow")
    if shader_family in {"skin", "skin_wrinkle"}:
        unsupported_features.append("skin_subsurface_and_wrinkle_response")
    return {
        "shader_family": shader_family,
        "shader_technique": raw_family,
        "shader_authority": family_authority,
        "shader_family_source": str(family_contract.get("source", "") or ""),
        "shader_family_reason": str(family_contract.get("reason", "") or ""),
        "channel_color_spaces": dict(sorted(channel_color_spaces.items())),
        "channel_authorities": dict(sorted(channel_authorities.items())),
        "alpha_mode": alpha_mode,
        "alpha_cutoff": alpha_cutoff,
        "opacity_factor": opacity_factor,
        "alpha_authority": alpha_authority,
        "alpha_reason": alpha_reason,
        "double_sided": double_sided,
        "double_sided_authority": double_sided_authority,
        "double_sided_reason": double_sided_reason,
        "layer_bindings": layer_bindings,
        "unsupported_features": sorted(set(unsupported_features)),
        "vertex_color": {
            "count": max(0, _safe_int(getattr(source, "preview_vertex_color_count", 0), 0)),
            "mean": list(tuple(getattr(source, "preview_vertex_color_mean", ()) or ())[:3]),
            "alpha_mean": getattr(source, "preview_vertex_alpha_mean", None),
            "alpha_min": getattr(source, "preview_vertex_alpha_min", None),
        },
    }


def _source_file_stat_key(source: Path) -> str:
    resolved = source.resolve()
    stat = source.stat()
    return f"{resolved}|size:{stat.st_size}|mtime:{stat.st_mtime_ns}".casefold()


def mesh_dotnet_material_input_signature(mesh: object) -> str:
    rows: list[dict[str, object]] = []
    source_asset_path = str(getattr(mesh, "path", "") or "").strip()
    for submesh in _dotnet_material_sources(mesh):
        channels: list[tuple[str, str]] = []
        resolved_channels = _dotnet_resolved_texture_channels(submesh)
        for channel, value in sorted(resolved_channels.items()):
            raw_path = str(value or "").strip()
            source = Path(raw_path).expanduser()
            try:
                identity = _source_file_stat_key(source) if source.is_file() else raw_path
            except OSError:
                identity = raw_path
            channels.append((channel, identity))
        rows.append(
            {
                "material": _dotnet_material_name(submesh),
                "texture": _dotnet_texture_name(submesh),
                "texture_flip_vertical": bool(
                    getattr(submesh, "preview_texture_flip_vertical", False)
                ),
                "channels": channels,
                "normal_y_policy": _dotnet_material_normal_y_policy(submesh),
                "channel_components": _dotnet_material_channel_components(submesh),
                "semantic_contract": _dotnet_material_semantic_contract(
                    submesh,
                    resolved_channels,
                    source_asset_path=source_asset_path,
                ),
                "parameters": _dotnet_initial_material_parameters(
                    submesh, resolved_channels
                ),
            }
        )
    payload = json.dumps(rows, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _dotnet_material_resource(raw_path: str) -> tuple[str, str]:
    source = Path(raw_path).expanduser()
    try:
        resolved = source.resolve()
        stat = resolved.stat()
        normalized_path = resolved.as_posix()
        identity = f"{normalized_path.casefold()}|size:{stat.st_size}|mtime_ns:{stat.st_mtime_ns}"
    except OSError:
        normalized_path = os.path.normpath(raw_path).replace("\\", "/")
        identity = f"raw:{normalized_path.casefold()}"
    return normalized_path, hashlib.sha256(identity.encode("utf-8")).hexdigest()


def mesh_dotnet_texture_resource_id(raw_path: str | Path) -> str:
    _normalized_path, fingerprint = _dotnet_material_resource(str(raw_path or ""))
    return f"texture:{fingerprint}"


def _material_profile_name(source: object | None) -> str:
    if source is None:
        return ""
    return str(
        getattr(source, "cdmw_material_authority_profile", "")
        or getattr(source, "material_authority_profile", "")
        or getattr(source, "complete_swap_material_profile", "")
        or ""
    ).strip()


def _resource_channel_rank(channel: str) -> int:
    return {
        "base": 0,
        "normal": 1,
        "material": 2,
        "roughness": 3,
        "metallic": 4,
        "specular": 5,
        "emissive": 6,
        "height": 7,
    }.get(canonical_material_channel(channel), 99)


def _dotnet_manifest_resource_bindings(
    resolved_channels: Mapping[str, str],
    packaged_channels: Mapping[str, str],
    *,
    source: object | None = None,
    source_asset_path: str = "",
    submesh_index: int = 0,
    role: str = "replacement",
) -> tuple[dict[str, str], dict[str, dict[str, object]]]:
    channels: dict[str, str] = {}
    resources: dict[str, dict[str, object]] = {}
    profile_name = _material_profile_name(source)
    semantic_contract = _dotnet_material_semantic_contract(
        source,
        resolved_channels,
        source_asset_path=source_asset_path,
    )
    channel_color_spaces = semantic_contract["channel_color_spaces"]
    channel_authorities = semantic_contract["channel_authorities"]
    for semantic, raw_path in sorted(resolved_channels.items()):
        source_path = str(raw_path or "").strip()
        if not source_path:
            continue
        normalized_path, fingerprint = _dotnet_material_resource(source_path)
        resource_id = (
            f"texture:{fingerprint}"
            if role == "replacement"
            else f"texture:{fingerprint}:{role}:{int(submesh_index)}"
        )
        channels[str(semantic)] = resource_id
        existing = resources.get(resource_id)
        if existing is None:
            policy = mesh_material_resource_policy(
                profile_name,
                semantic,
                concrete_expected_resource=True,
            )
            resources[resource_id] = {
                "resource_id": resource_id,
                "path": str(packaged_channels.get(semantic, normalized_path) or normalized_path),
                "source_reference": normalized_path,
                "fingerprint": fingerprint,
                "role": str(role or "replacement"),
                "submesh_index": int(submesh_index),
                "material_channel": policy.channel,
                "semantic": canonical_material_channel(semantic),
                "color_space": str(channel_color_spaces.get(semantic, "linear")),
                "semantic_authority": str(channel_authorities.get(semantic, "guess")),
                "profile": policy.profile,
                "required": policy.required,
                "criticality": policy.criticality,
                "fallback_policy": policy.fallback_policy,
            }
        elif _resource_channel_rank(str(semantic)) < _resource_channel_rank(
            str(existing.get("material_channel", ""))
        ):
            policy = mesh_material_resource_policy(
                profile_name,
                semantic,
                concrete_expected_resource=True,
            )
            existing.update(
                material_channel=policy.channel,
                semantic=canonical_material_channel(semantic),
                color_space=str(channel_color_spaces.get(semantic, "linear")),
                semantic_authority=str(channel_authorities.get(semantic, "guess")),
                required=policy.required,
                criticality=policy.criticality,
                fallback_policy=policy.fallback_policy,
            )
        elif not bool(existing.get("required", False)):
            policy = mesh_material_resource_policy(
                profile_name,
                semantic,
                concrete_expected_resource=True,
            )
            if policy.required:
                existing.update(
                    profile=policy.profile,
                    material_channel=policy.channel,
                    required=True,
                    criticality=policy.criticality,
                    fallback_policy=policy.fallback_policy,
                )
    return channels, resources


def mesh_dotnet_material_state_payload(
    mesh: object,
    *,
    session_id: str,
    edit_revision: int,
    generation: int,
    affected_submeshes: Sequence[int] | None = None,
    role: str = "replacement",
    submesh_index_offset: int = 0,
    material_signature: str = "",
) -> dict[str, object]:
    """Snapshot resident material bindings without rebuilding a package."""
    resources: dict[str, dict[str, object]] = {}
    submesh_payloads: list[dict[str, object]] = []
    all_indices: list[int] = []
    source_asset_path = str(getattr(mesh, "path", "") or "").strip()
    for fallback_index, submesh in enumerate(_dotnet_material_sources(mesh)):
        local_index = _safe_int(
            getattr(
                submesh,
                "submesh_index",
                getattr(submesh, "source_submesh_index", fallback_index),
            ),
            fallback_index,
        )
        if local_index < 0:
            local_index = fallback_index
        submesh_index = (
            max(0, _safe_int(submesh_index_offset, 0)) + fallback_index
            if role != "replacement" or submesh_index_offset
            else local_index
        )
        all_indices.append(submesh_index)
        resolved_channels = _dotnet_resolved_texture_channels(submesh)
        semantic_contract = _dotnet_material_semantic_contract(
            submesh,
            resolved_channels,
            source_asset_path=source_asset_path,
        )
        channels, submesh_resources = _dotnet_manifest_resource_bindings(
            resolved_channels,
            {},
            source=submesh,
            source_asset_path=source_asset_path,
            submesh_index=submesh_index,
            role=role,
        )
        resources.update(submesh_resources)
        submesh_payloads.append(
            {
                "submesh_index": submesh_index,
                "material_slot_index": _safe_int(
                    getattr(submesh, "material_slot_index", fallback_index), fallback_index
                ),
                "material": _dotnet_material_name(submesh),
                "texture": _dotnet_texture_name(submesh),
                "texture_flip_vertical": bool(
                    getattr(submesh, "preview_texture_flip_vertical", False)
                ),
                "channels": channels,
                "normal_y_policy": _dotnet_material_normal_y_policy(submesh),
                "channel_components": _dotnet_material_channel_components(submesh),
                **semantic_contract,
                "parameters": _dotnet_initial_material_parameters(
                    submesh, resolved_channels
                ),
            }
        )
    valid_indices = set(all_indices)
    affected = sorted(valid_indices) if affected_submeshes is None else sorted(
        {
            index
            for value in affected_submeshes
            if (index := _safe_int(value, -1)) in valid_indices
        }
    )
    return {
        "schema": "cdmw_mesh_material_state_v2",
        "version": 2,
        "event": "material_state_update",
        "session_id": str(session_id or ""),
        "edit_revision": max(0, _safe_int(edit_revision, 0)),
        "generation": max(0, _safe_int(generation, 0)),
        "material_signature": str(material_signature or mesh_dotnet_material_input_signature(mesh)),
        "affected_submeshes": affected,
        "resources": [resources[key] for key in sorted(resources)],
        "submeshes": submesh_payloads,
    }


__all__ = [
    "apply_dotnet_native_material_batch_binding",
    "copy_dotnet_preview_material_bindings",
    "mesh_dotnet_material_input_signature",
    "mesh_dotnet_material_state_payload",
    "mesh_dotnet_texture_resource_id",
    "set_dotnet_preview_texture_flip_vertical",
]
