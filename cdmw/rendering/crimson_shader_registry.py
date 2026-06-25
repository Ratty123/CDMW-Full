from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Dict, Mapping, Sequence, Tuple


CRIMSON_SHADER_REGISTRY_SCHEMA_VERSION = 1

AUTHORITY_AUTHORITATIVE = "authoritative"
AUTHORITY_SIDECAR = "sidecar"
AUTHORITY_CAPTURE_INFERRED = "capture_inferred"
AUTHORITY_GUESS = "guess"
AUTHORITY_VALUES = (
    AUTHORITY_AUTHORITATIVE,
    AUTHORITY_SIDECAR,
    AUTHORITY_CAPTURE_INFERRED,
    AUTHORITY_GUESS,
)

CRIMSON_SHADER_FAMILIES = (
    "standard_v2",
    "cloth",
    "cloth_v2",
    "skin",
    "hair",
    "emissive",
    "emissive_v2",
    "static_multitextured",
    "environment_water",
)

_FAMILY_DISPLAY_NAMES = {
    "standard_v2": "SkinnedMeshStandard_Ver2",
    "cloth": "Cloth",
    "cloth_v2": "Cloth_Ver2",
    "skin": "Skin",
    "hair": "Hair",
    "emissive": "Emissive",
    "emissive_v2": "Emissive_Ver2",
    "static_multitextured": "StaticMultiTextured",
    "environment_water": "Environment Water",
}

_SUPPORTED_GLOBAL_MASK_FAMILIES = {
    "standard",
    "standard_v2",
    "static_standard",
    "static_multitextured",
    "emissive",
    "emissive_v2",
}

_CHANNEL_SUFFIXES = {
    "r": "r",
    "red": "r",
    "g": "g",
    "green": "g",
    "b": "b",
    "blue": "b",
    "a": "a",
    "alpha": "a",
}

_DIRECT_SLOT_RULES = {
    "overlaycolortexture": ("base", "crimson_overlay_color", {"base_color": "rgb"}, "sRGB color texture"),
    "basecolortexture": ("base", "crimson_base_color", {"base_color": "rgb"}, "sRGB color texture"),
    "diffusetexture": ("base", "crimson_diffuse", {"base_color": "rgb"}, "sRGB color texture"),
    "albedotexture": ("base", "crimson_albedo", {"base_color": "rgb"}, "sRGB color texture"),
    "colortexture": ("base", "crimson_color", {"base_color": "rgb"}, "sRGB color texture"),
    "normaltexture": ("normal", "crimson_normal", {"normal": "rgb"}, "normal map"),
    "detailnormaltexture": ("normal", "crimson_detail_normal", {"normal": "rgb"}, "layer normal map"),
    "wrinklenormaltexture": ("normal", "crimson_wrinkle_normal", {"normal": "rgb"}, "layer normal map"),
    "emissivetexture": ("emissive", "crimson_emissive", {"emissive": "rgb"}, "sRGB emissive texture"),
    "emissivecolortexture": ("emissive", "crimson_emissive", {"emissive": "rgb"}, "sRGB emissive texture"),
    "heighttexture": ("height", "crimson_height", {}, "height/displacement map"),
    "displacementtexture": ("height", "crimson_height", {}, "height/displacement map"),
    "opacitytexture": ("opacity", "crimson_opacity", {}, "opacity/cutout map"),
    "alphatexture": ("opacity", "crimson_opacity", {}, "opacity/cutout map"),
}

_WATER_ENVIRONMENT_RULES = {
    "gwaternormaltexture": ("normal", "crimson_water_normal", "environment_layer", "Water surface normal input; keep runtime-owned"),
    "gdisplacementtexture": ("height", "crimson_water_displacement", "environment_height", "Water displacement input; keep runtime-owned"),
    "gshallowwaterheight": ("height", "crimson_water_height", "environment_height", "Shallow-water height simulation input; keep runtime-owned"),
    "gshallowwatervelocity": ("layer", "crimson_water_velocity", "environment_simulation", "Shallow-water velocity simulation input; not a material texture"),
    "gshallowwaterfoam": ("detail", "crimson_water_foam", "environment_layer", "Water foam layer input; keep runtime-owned"),
    "gfoamtexture": ("detail", "crimson_water_foam", "environment_layer", "Water foam layer input; keep runtime-owned"),
    "ggradienttexture": ("detail", "crimson_water_gradient", "environment_layer", "Water gradient/ramp input; keep runtime-owned"),
    "gshallowwatermask": ("layer", "crimson_water_mask", "environment_mask", "Shallow-water mask input; not a source material slot"),
    "grepuddlemask": ("layer", "crimson_puddle_mask", "environment_mask", "Puddle mask input; not a source material slot"),
    "gnormaldepthhalf": ("layer", "crimson_normal_depth_buffer", "render_buffer", "Render buffer input; never promote as material texture"),
    "gfdepthopaque": ("layer", "crimson_depth_buffer", "render_buffer", "Depth buffer input; never promote as material texture"),
    "gbindlesstextures": ("material", "crimson_bindless_texture_table", "descriptor_table", "Bindless texture table; descriptor indices are not fixed material slots"),
}


@dataclass(frozen=True)
class CrimsonShaderSlotRule:
    parameter_key: str
    slot: str
    source_kind: str
    disposition: str
    authority: str = AUTHORITY_AUTHORITATIVE
    promoted_channels: Mapping[str, str] = field(default_factory=dict)
    reason: str = ""


def _normalize_key(value: object) -> str:
    return "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum())


def _semantic_parameter_key(value: object) -> str:
    text = str(value or "").strip()
    if text.startswith("__"):
        parts = [part for part in text.split("__") if part]
        if parts:
            return _normalize_key(parts[-1])
    return _normalize_key(text)


def normalize_shader_family(value: object) -> str:
    text = str(value or "").strip().lower()
    compact = _normalize_key(text)
    if not compact:
        return ""
    if "skin" in compact and "skinnedmesh" not in compact:
        return "skin"
    if "skinnedmeshskin" in compact:
        return "skin"
    if any(marker in compact for marker in ("skinnedmeshanimalhair", "skinnedmeshhairstandard", "skinnedmeshhair", "skinnedmeshfur")):
        return "hair"
    if "hair" in compact or "fur" in compact:
        return "hair"
    if "cloth" in compact:
        return "cloth_v2" if "v2" in compact or "ver2" in compact else "cloth"
    if "emissive" in compact:
        return "emissive_v2" if "v2" in compact or "ver2" in compact else "emissive"
    if any(marker in compact for marker in ("water", "shallowwater", "sea")):
        return "environment_water"
    if "static" in compact and ("multi" in compact or "rgbtexture" in compact):
        return "static_multitextured"
    if "multitextured" in compact or "rgbtexture" in compact:
        return "static_multitextured"
    if "static" in compact:
        return "static_standard"
    if "standard" in compact:
        return "standard_v2" if "v2" in compact or "ver2" in compact else "standard"
    return text.replace(" ", "_")


def shader_family_display_name(shader_family: object) -> str:
    family = normalize_shader_family(shader_family)
    return _FAMILY_DISPLAY_NAMES.get(family, str(shader_family or "").strip() or "Generic")


def texture_suffix_from_path(path_value: object) -> str:
    text = str(path_value or "").replace("\\", "/").strip()
    if not text:
        return ""
    try:
        stem = PurePosixPath(text).stem.lower()
    except (OSError, ValueError):
        stem = text.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
    for marker in ("_ma", "_mg", "_sp", "_n", "_wn", "_disp", "_flow", "_d", "_o"):
        if stem.endswith(marker):
            return marker[1:]
    parts = [part for part in stem.replace("-", "_").split("_") if part]
    return parts[-1] if parts else ""


def parameter_channel_suffix(parameter_name: object) -> str:
    compact = _normalize_key(parameter_name)
    if not compact:
        return ""
    for suffix, channel in _CHANNEL_SUFFIXES.items():
        if compact.endswith(suffix) and len(compact) > len(suffix):
            return channel
    return ""


def infer_layer_channel(parameter_name: object = "", declared: object = "") -> str:
    explicit = str(declared or "").strip().lower()
    if explicit in {"r", "g", "b", "a"}:
        return explicit
    return parameter_channel_suffix(parameter_name)


def _authority_from_source(
    *,
    exact_rule: bool,
    sidecar_kind: object = "",
    parameter_declared_by: object = "",
    capture_inferred: bool = False,
    fallback_guess: bool = False,
) -> str:
    if fallback_guess:
        return AUTHORITY_GUESS
    if capture_inferred:
        return AUTHORITY_CAPTURE_INFERRED
    if exact_rule:
        return AUTHORITY_AUTHORITATIVE
    if str(sidecar_kind or parameter_declared_by or "").strip():
        return AUTHORITY_SIDECAR
    return AUTHORITY_GUESS


def _default_decode(
    *,
    shader_family: str,
    parameter_name: str,
    source_path: str,
    slot_name: str,
    semantic_subtype: str,
    layer_channel: str,
    blend_flags: Sequence[object],
    authority: str,
) -> Dict[str, object]:
    suffix = texture_suffix_from_path(source_path)
    return {
        "schema_version": CRIMSON_SHADER_REGISTRY_SCHEMA_VERSION,
        "shader_family": shader_family or "generic",
        "parameter_name": parameter_name,
        "parameter_key": _normalize_key(parameter_name),
        "slot": slot_name or "material",
        "source_kind": "unknown_crimson_texture",
        "authority": authority,
        "disposition": "diagnostic_only",
        "promoted_channels": {},
        "source_channels": {},
        "suffix": suffix,
        "semantic_subtype": semantic_subtype,
        "layer_channel": layer_channel,
        "blend_flags": [str(value) for value in tuple(blend_flags or ()) if str(value)],
        "srgb": "",
        "scalar_hints": {},
        "known_slot": False,
        "reason": "unknown Crimson packed or control map; keep diagnostic until registry/capture proves layout",
    }


def decode_crimson_texture_binding(
    *,
    shader_family: object = "",
    parameter_name: object = "",
    source_path: object = "",
    slot_name: object = "",
    semantic_subtype: object = "",
    packed_channels: Sequence[object] = (),
    layer_channel: object = "",
    blend_flags: Sequence[object] = (),
    sidecar_kind: object = "",
    parameter_declared_by: object = "",
    capture_inferred: bool = False,
    fallback_guess: bool = False,
) -> Dict[str, object]:
    family = normalize_shader_family(shader_family)
    parameter = str(parameter_name or "").strip()
    parameter_key = _semantic_parameter_key(parameter)
    source = str(source_path or "").strip()
    slot = str(slot_name or "").strip().lower()
    subtype = str(semantic_subtype or "").strip().lower()
    suffix = texture_suffix_from_path(source)
    channel = infer_layer_channel(parameter, layer_channel)
    authority = _authority_from_source(
        exact_rule=False,
        sidecar_kind=sidecar_kind,
        parameter_declared_by=parameter_declared_by,
        capture_inferred=capture_inferred,
        fallback_guess=fallback_guess,
    )
    decode = _default_decode(
        shader_family=family,
        parameter_name=parameter,
        source_path=source,
        slot_name=slot,
        semantic_subtype=subtype,
        layer_channel=channel,
        blend_flags=blend_flags,
        authority=authority,
    )

    direct_rule = _DIRECT_SLOT_RULES.get(parameter_key)
    if direct_rule is not None:
        target_slot, source_kind, promoted, reason = direct_rule
        decode.update(
            {
                "slot": target_slot,
                "source_kind": source_kind,
                "authority": _authority_from_source(
                    exact_rule=True,
                    sidecar_kind=sidecar_kind,
                    parameter_declared_by=parameter_declared_by,
                    capture_inferred=capture_inferred,
                    fallback_guess=fallback_guess,
                ),
                "disposition": "promoted" if promoted else "recorded",
                "promoted_channels": dict(promoted),
                "source_channels": dict(promoted),
                "srgb": "true" if target_slot in {"base", "emissive"} else "false",
                "known_slot": True,
                "reason": reason,
            }
        )
        return decode

    water_rule = _WATER_ENVIRONMENT_RULES.get(parameter_key)
    if water_rule is not None:
        target_slot, source_kind, disposition, reason = water_rule
        decode.update(
            {
                "slot": target_slot,
                "source_kind": source_kind,
                "authority": _authority_from_source(
                    exact_rule=True,
                    sidecar_kind=sidecar_kind,
                    parameter_declared_by=parameter_declared_by,
                    capture_inferred=capture_inferred,
                    fallback_guess=fallback_guess,
                ),
                "disposition": disposition,
                "srgb": "false",
                "known_slot": True,
                "reason": reason,
            }
        )
        return decode

    if parameter_key in {"colorblendingmasktexture", "blendingmasktexture"}:
        promoted = {"ao": "r", "roughness": "g", "metalness": "b"} if family in _SUPPORTED_GLOBAL_MASK_FAMILIES else {}
        decode.update(
            {
                "slot": "material",
                "source_kind": "crimson_color_blending_mask",
                "authority": _authority_from_source(
                    exact_rule=bool(promoted),
                    sidecar_kind=sidecar_kind,
                    parameter_declared_by=parameter_declared_by,
                    capture_inferred=capture_inferred,
                    fallback_guess=fallback_guess,
                ),
                "disposition": "promoted" if promoted else "diagnostic_only",
                "promoted_channels": dict(promoted),
                "source_channels": dict(promoted),
                "srgb": "false",
                "known_slot": True,
                "reason": (
                    "Crimson _colorBlendingMaskTexture: R=AO, G=roughness, B=metalness"
                    if promoted
                    else "Crimson color blending mask family not yet proven for global PBR promotion"
                ),
            }
        )
        return decode

    if (
        parameter_key in {"detailmasktexture", "detailmask", "masktexture"}
        or "skindetailmask" in parameter_key
        or "hairanisotropydetailmask" in parameter_key
        or "wrinklemask" in parameter_key
        or "tornpattern" in parameter_key
        or suffix == "mg"
        or subtype == "detail_mask"
    ):
        source_kind = "crimson_detail_mask"
        if "skindetailmask" in parameter_key or (family == "skin" and parameter_key in {"masktexture", "skindetailmasktexture", "skindetailopacity"}):
            source_kind = "crimson_skin_detail_mask"
        elif "hairanisotropydetailmask" in parameter_key or (family == "hair" and parameter_key == "masktexture"):
            source_kind = "crimson_hair_mask"
        decode.update(
            {
                "slot": "detail",
                "source_kind": source_kind,
                "authority": _authority_from_source(
                    exact_rule=True,
                    sidecar_kind=sidecar_kind,
                    parameter_declared_by=parameter_declared_by,
                    capture_inferred=capture_inferred,
                    fallback_guess=fallback_guess,
                ),
                "disposition": "layer_only",
                "srgb": "false",
                "known_slot": True,
                "reason": "Crimson detail/grime/dye mask controls layers; not whole-material PBR",
            }
        )
        return decode

    if (
        "grimediffuse" in parameter_key
        or "detaildiffuse" in parameter_key
        or "damageblendingdiffuse" in parameter_key
        or "wrinklecolor" in parameter_key
    ):
        decode.update(
            {
                "slot": "base",
                "source_kind": "crimson_layer_color",
                "authority": _authority_from_source(
                    exact_rule=True,
                    sidecar_kind=sidecar_kind,
                    parameter_declared_by=parameter_declared_by,
                    capture_inferred=capture_inferred,
                    fallback_guess=fallback_guess,
                ),
                "disposition": "layer_only",
                "srgb": "true",
                "known_slot": True,
                "reason": "Crimson detail/grime/damage diffuse textures are RGB layer inputs; not a whole-material base map",
            }
        )
        return decode

    if (
        "grimenormal" in parameter_key
        or "detailnormalmask" in parameter_key
        or "damageblendingnormal" in parameter_key
        or "wrinklenormal" in parameter_key
        or "hairanisotropydetailnormal" in parameter_key
        or "skindetailnormal" in parameter_key
    ):
        decode.update(
            {
                "slot": "normal",
                "source_kind": "crimson_layer_normal",
                "authority": _authority_from_source(
                    exact_rule=True,
                    sidecar_kind=sidecar_kind,
                    parameter_declared_by=parameter_declared_by,
                    capture_inferred=capture_inferred,
                    fallback_guess=fallback_guess,
                ),
                "disposition": "layer_only",
                "srgb": "false",
                "known_slot": True,
                "reason": "Crimson detail/grime/damage normal textures are layer-scoped; not promoted as the global normal map",
            }
        )
        return decode

    if (
        "detailheight" in parameter_key
        or "damageblendingheight" in parameter_key
        or "wrinkledisplacement" in parameter_key
        or "wrinkleheight" in parameter_key
    ):
        decode.update(
            {
                "slot": "height",
                "source_kind": "crimson_layer_height",
                "authority": _authority_from_source(
                    exact_rule=True,
                    sidecar_kind=sidecar_kind,
                    parameter_declared_by=parameter_declared_by,
                    capture_inferred=capture_inferred,
                    fallback_guess=fallback_guess,
                ),
                "disposition": "layer_only",
                "srgb": "false",
                "known_slot": True,
                "reason": "Crimson detail/damage height textures are layer-scoped displacement controls",
            }
        )
        return decode

    if (
        parameter_key.startswith("basecolortexture")
        or parameter_key.startswith("colortexture")
        or parameter_key.startswith("layerbasecolortexture")
        or parameter_key.startswith("lavastonecolortexture")
    ):
        decode.update(
            {
                "slot": "base",
                "source_kind": "crimson_layer_color",
                "authority": _authority_from_source(
                    exact_rule=True,
                    sidecar_kind=sidecar_kind,
                    parameter_declared_by=parameter_declared_by,
                    capture_inferred=capture_inferred,
                    fallback_guess=fallback_guess,
                ),
                "disposition": "layer_only",
                "srgb": "true",
                "known_slot": True,
                "reason": "Crimson indexed/channel color texture is layer-scoped",
            }
        )
        return decode

    if parameter_key.startswith("normaltexture") or parameter_key.startswith("layernormaltexture") or parameter_key.startswith("uniquenormaltexture"):
        decode.update(
            {
                "slot": "normal",
                "source_kind": "crimson_layer_normal",
                "authority": _authority_from_source(
                    exact_rule=True,
                    sidecar_kind=sidecar_kind,
                    parameter_declared_by=parameter_declared_by,
                    capture_inferred=capture_inferred,
                    fallback_guess=fallback_guess,
                ),
                "disposition": "layer_only",
                "srgb": "false",
                "known_slot": True,
                "reason": "Crimson indexed/channel normal texture is layer-scoped",
            }
        )
        return decode

    if parameter_key.startswith("heighttexture") or parameter_key.startswith("layerheighttexture") or parameter_key.startswith("uniqueheighttexture"):
        decode.update(
            {
                "slot": "height",
                "source_kind": "crimson_layer_height",
                "authority": _authority_from_source(
                    exact_rule=True,
                    sidecar_kind=sidecar_kind,
                    parameter_declared_by=parameter_declared_by,
                    capture_inferred=capture_inferred,
                    fallback_guess=fallback_guess,
                ),
                "disposition": "layer_only",
                "srgb": "false",
                "known_slot": True,
                "reason": "Crimson indexed/channel height texture is layer-scoped",
            }
        )
        return decode

    if (
        "grimematerial" in parameter_key
        or "detailmaterial" in parameter_key
        or "damageblendingmaterial" in parameter_key
        or "skindetailmaterial" in parameter_key
        or parameter_key.startswith("materialtexture")
        or parameter_key.startswith("layermaterialtexture")
        or parameter_key.startswith("layerspeculartexture")
        or "materialtexture" == parameter_key
        or "speculartexture" == parameter_key
        or suffix == "sp"
    ):
        source_kind = "crimson_layer_material_response"
        if family == "skin" or "skin" in parameter_key:
            source_kind = "crimson_skin_material_response"
        elif family == "hair":
            source_kind = "crimson_hair_material_response"
        elif family == "static_multitextured":
            source_kind = "crimson_static_multitextured_material_response"
        decode.update(
            {
                "slot": "material",
                "source_kind": source_kind,
                "authority": _authority_from_source(
                    exact_rule=bool(parameter_key),
                    sidecar_kind=sidecar_kind,
                    parameter_declared_by=parameter_declared_by,
                    capture_inferred=capture_inferred,
                    fallback_guess=fallback_guess,
                ),
                "disposition": "layer_material_response" if parameter_key else "diagnostic_only",
                "srgb": "false",
                "known_slot": bool(parameter_key),
                "reason": "Crimson grime/detail/skin material response is layer dependent; not whole-material PBR",
            }
        )
        return decode

    if "dyemask" in parameter_key or "dyecolor" in parameter_key or "dye" in parameter_key:
        decode.update(
            {
                "slot": "detail",
                "source_kind": "crimson_dye_control",
                "authority": _authority_from_source(
                    exact_rule=True,
                    sidecar_kind=sidecar_kind,
                    parameter_declared_by=parameter_declared_by,
                    capture_inferred=capture_inferred,
                    fallback_guess=fallback_guess,
                ),
                "disposition": "layer_only",
                "known_slot": True,
                "reason": "Crimson dye channel controls layer color; not whole-material PBR",
            }
        )
        return decode

    if parameter_key in {"rgbtexture", "rgbdiffusetexture", "layercolortexture"}:
        decode.update(
            {
                "slot": "base",
                "source_kind": "crimson_static_multitextured_layer_color",
                "authority": _authority_from_source(
                    exact_rule=family == "static_multitextured",
                    sidecar_kind=sidecar_kind,
                    parameter_declared_by=parameter_declared_by,
                    capture_inferred=capture_inferred,
                    fallback_guess=fallback_guess,
                ),
                "disposition": "layer_only" if family == "static_multitextured" else "diagnostic_only",
                "srgb": "true",
                "known_slot": family == "static_multitextured",
                "reason": "StaticMultiTextured RGB texture supplies a layer color, not a single whole-material base map",
            }
        )
        return decode

    if parameter_key in {"layermasktexture", "layerblendmasktexture", "rgbmasktexture"}:
        decode.update(
            {
                "slot": "detail",
                "source_kind": "crimson_static_multitextured_blend_mask",
                "authority": _authority_from_source(
                    exact_rule=family == "static_multitextured",
                    sidecar_kind=sidecar_kind,
                    parameter_declared_by=parameter_declared_by,
                    capture_inferred=capture_inferred,
                    fallback_guess=fallback_guess,
                ),
                "disposition": "layer_only",
                "known_slot": family == "static_multitextured",
                "reason": "StaticMultiTextured layer blend mask gates RGB material layers",
            }
        )
        return decode

    if parameter_key in {"rgbnormaltexture", "layernormaltexture"}:
        decode.update(
            {
                "slot": "normal",
                "source_kind": "crimson_static_multitextured_layer_normal",
                "authority": _authority_from_source(
                    exact_rule=family == "static_multitextured",
                    sidecar_kind=sidecar_kind,
                    parameter_declared_by=parameter_declared_by,
                    capture_inferred=capture_inferred,
                    fallback_guess=fallback_guess,
                ),
                "disposition": "layer_only",
                "known_slot": family == "static_multitextured",
                "reason": "StaticMultiTextured normal texture is layer-scoped",
            }
        )
        return decode

    if parameter_key == "flowtexture" or suffix == "flow":
        decode.update(
            {
                "slot": "layer",
                "source_kind": "crimson_flow_vector",
                "authority": _authority_from_source(
                    exact_rule=True,
                    sidecar_kind=sidecar_kind,
                    parameter_declared_by=parameter_declared_by,
                    capture_inferred=capture_inferred,
                    fallback_guess=fallback_guess,
                ),
                "disposition": "layer_flow",
                "known_slot": True,
                "reason": "Crimson flow texture is vector/layer control data; not promoted",
            }
        )
        return decode

    if "emissive" in parameter_key and "texture" in parameter_key:
        decode.update(
            {
                "slot": "emissive",
                "source_kind": "crimson_emissive_control",
                "authority": _authority_from_source(
                    exact_rule=True,
                    sidecar_kind=sidecar_kind,
                    parameter_declared_by=parameter_declared_by,
                    capture_inferred=capture_inferred,
                    fallback_guess=fallback_guess,
                ),
                "disposition": "recorded",
                "srgb": "false",
                "known_slot": True,
                "reason": "Crimson emissive control texture affects emissive strength/layering; not base color",
            }
        )
        return decode

    if parameter_key in {"ssdmdirectiontexture", "ssdmhairdirectiontexture"} or "hairdirection" in parameter_key:
        decode.update(
            {
                "slot": "layer",
                "source_kind": "crimson_hair_direction",
                "authority": _authority_from_source(
                    exact_rule=True,
                    sidecar_kind=sidecar_kind,
                    parameter_declared_by=parameter_declared_by,
                    capture_inferred=capture_inferred,
                    fallback_guess=fallback_guess,
                ),
                "disposition": "layer_direction",
                "known_slot": True,
                "reason": "Crimson hair direction texture is anisotropic/layer control data; not promoted",
            }
        )
        return decode

    if any(token in parameter_key for token in ("eyetexture", "iris", "pupil", "cornea")):
        decode.update(
            {
                "slot": "layer",
                "source_kind": "crimson_eye_layer",
                "authority": _authority_from_source(
                    exact_rule=True,
                    sidecar_kind=sidecar_kind,
                    parameter_declared_by=parameter_declared_by,
                    capture_inferred=capture_inferred,
                    fallback_guess=fallback_guess,
                ),
                "disposition": "diagnostic_only",
                "known_slot": True,
                "reason": "Crimson eye/iris/cornea texture is anatomy-layer data; not promoted",
            }
        )
        return decode

    if packed_channels:
        packed = [str(channel_value or "").strip().lower() for channel_value in packed_channels if str(channel_value or "").strip()]
        if packed[:3] in (["ao", "roughness", "metallic"], ["occlusion", "roughness", "metallic"]):
            decode.update(
                {
                    "slot": "material",
                    "source_kind": "explicit_packed_material",
                    "authority": AUTHORITY_AUTHORITATIVE if not fallback_guess else AUTHORITY_GUESS,
                    "disposition": "promoted",
                    "promoted_channels": {"ao": "r", "roughness": "g", "metalness": "b"},
                    "source_channels": {"ao": "r", "roughness": "g", "metalness": "b"},
                    "known_slot": True,
                    "reason": "explicit packed channel metadata",
                }
            )
            return decode

    scalar_hints: Dict[str, str] = {}
    if "scratchroughness" in parameter_key or parameter_key.endswith("roughness"):
        scalar_hints["roughness"] = channel or "value"
    if "scratchmetallic" in parameter_key or "scratchmetalness" in parameter_key or parameter_key.endswith("metallic"):
        scalar_hints["metalness"] = channel or "value"
    if scalar_hints:
        decode.update(
            {
                "slot": "material",
                "source_kind": "crimson_scalar_material_hint",
                "authority": _authority_from_source(
                    exact_rule=True,
                    sidecar_kind=sidecar_kind,
                    parameter_declared_by=parameter_declared_by,
                    capture_inferred=capture_inferred,
                    fallback_guess=fallback_guess,
                ),
                "disposition": "scalar_hint",
                "scalar_hints": scalar_hints,
                "known_slot": True,
                "reason": "Crimson scalar material response hint",
            }
        )
    return decode


def decode_crimson_texture_entry(entry: Mapping[str, object], *, default_slot: str = "material") -> Dict[str, object]:
    return decode_crimson_texture_binding(
        shader_family=entry.get("shader_family", ""),
        parameter_name=entry.get("parameter_name", ""),
        source_path=entry.get("source_dds_path", "") or entry.get("source_path", "") or entry.get("archive_path", "") or entry.get("preview_path", ""),
        slot_name=entry.get("slot", default_slot) or default_slot,
        semantic_subtype=entry.get("semantic_subtype", ""),
        packed_channels=tuple(entry.get("packed_channels", ()) or ()) if isinstance(entry.get("packed_channels", ()), Sequence) and not isinstance(entry.get("packed_channels", ()), (str, bytes, bytearray)) else (),
        layer_channel=entry.get("layer_channel", ""),
        blend_flags=tuple(entry.get("blend_flags", ()) or ()) if isinstance(entry.get("blend_flags", ()), Sequence) and not isinstance(entry.get("blend_flags", ()), (str, bytes, bytearray)) else (),
        sidecar_kind=entry.get("sidecar_kind", ""),
        parameter_declared_by=entry.get("parameter_declared_by", ""),
    )


def decode_profile_for_family(shader_family: object) -> Dict[str, object]:
    family = normalize_shader_family(shader_family) or "generic"
    policy = {
        "schema_version": CRIMSON_SHADER_REGISTRY_SCHEMA_VERSION,
        "family": family,
        "family_display": shader_family_display_name(family),
        "authority": AUTHORITY_AUTHORITATIVE if family in CRIMSON_SHADER_FAMILIES or family in {"standard", "static_standard"} else AUTHORITY_GUESS,
        "global_material_promotions": ["_colorBlendingMaskTexture"] if family in _SUPPORTED_GLOBAL_MASK_FAMILIES else [],
        "layer_only_parameters": [
            "_detailMaskTexture",
            "_grimeMaterialTextureR/G/B/A",
            "_detailMaterialTextureR/G/B/A",
            "_dyeMaskTexture",
        ],
        "scalar_parameters": ["_scratchRoughness*", "_scratchMetallic*"],
        "capture_status": "not_captured",
        "renderdoc_truth_pass": renderdoc_truth_pass_checklist(),
    }
    if family == "environment_water":
        policy.update(
            {
                "capture_status": "captured_partial",
                "material_profile_rule": {
                    "recommended_profile": "material_authority_runtime_xml",
                    "authority": AUTHORITY_CAPTURE_INFERRED,
                    "reason": "RenderDoc rank 1 water draw uses runtime water, depth, bindless, and simulation inputs; preserve target XML/runtime bindings.",
                },
            }
        )
    if family == "generic":
        policy["note"] = "unknown family; unresolved/diagnostic until sidecar or capture proves layout"
    return policy


def renderdoc_truth_pass_checklist() -> Dict[str, object]:
    return {
        "status": "checklist_only",
        "required_capture_data": [
            "SRV slot table",
            "bindless descriptor table index-to-resource mapping",
            "sampler states",
            "constant buffers",
            "pixel shader disassembly",
            "texture SRGB views",
            "normal Y convention",
            "blend/raster state",
        ],
        "policy": "extract rules/formulas, implement clean approximation; do not run game bytecode in preview; bindless textures are not fixed SRV slots",
    }


def registry_manifest() -> Dict[str, object]:
    return {
        "schema_version": CRIMSON_SHADER_REGISTRY_SCHEMA_VERSION,
        "families": [
            decode_profile_for_family(family)
            for family in CRIMSON_SHADER_FAMILIES
        ],
        "authority_values": list(AUTHORITY_VALUES),
        "known_slots": [
            "_overlayColorTexture",
            "_normalTexture",
            "_colorBlendingMaskTexture",
            "_detailMaskTexture",
            "grime/detail/dye channel masks",
            "scratch roughness/metallic scalar hints",
            "RenderDoc water environment globals",
            "bindless descriptor tables",
        ],
        "unknown_policy": "unresolved_diagnostic",
    }


__all__ = [
    "AUTHORITY_AUTHORITATIVE",
    "AUTHORITY_CAPTURE_INFERRED",
    "AUTHORITY_GUESS",
    "AUTHORITY_SIDECAR",
    "AUTHORITY_VALUES",
    "CRIMSON_SHADER_FAMILIES",
    "CRIMSON_SHADER_REGISTRY_SCHEMA_VERSION",
    "CrimsonShaderSlotRule",
    "decode_crimson_texture_binding",
    "decode_crimson_texture_entry",
    "decode_profile_for_family",
    "infer_layer_channel",
    "normalize_shader_family",
    "parameter_channel_suffix",
    "registry_manifest",
    "renderdoc_truth_pass_checklist",
    "shader_family_display_name",
    "texture_suffix_from_path",
]
