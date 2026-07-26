"""Material preview combiner rules and parameter helpers."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from pathlib import PurePosixPath
from typing import Optional, Sequence, Tuple

from cdmw.models import PreviewMaterialTextureInput
from cdmw.rendering.crimson_shader_registry import (
    AUTHORITY_GUESS,
    decode_crimson_texture_binding,
    normalize_shader_family,
)

@dataclass(frozen=True, slots=True)
class MaterialPreviewCombinerSettings:
    normal_strength_floor: float = 0.5
    normal_strength_cap: float = 1.0
    height_amount: float = 0.04
    support_map_max_dimension: int = 256
    preserve_texture_orientation: bool = False


@dataclass(frozen=True, slots=True)
class MaterialPreviewCombinerResult:
    base_source: str = ""
    base_note: str = ""
    normal_source: str = ""
    normal_strength: float = 0.0
    occlusion_source: str = ""
    roughness_source: str = ""
    metalness_source: str = ""
    specular_source: str = ""
    height_source: str = ""
    height_amount: float = 0.0
    legacy_material_source: str = ""
    legacy_material_decode_mode: str = ""
    material_slots: Tuple[str, ...] = ()
    decode_modes: Tuple[str, ...] = ()
    notes: Tuple[str, ...] = ()
    outputs: Tuple[str, ...] = ()
    active: bool = False
    texture_flip_vertical: bool = False


_TECHNICAL_BASE_TOKENS = {
    "n",
    "normal",
    "normalmap",
    "norm",
    "nrm",
    "nm",
    "ma",
    "mg",
    "m",
    "mat",
    "material",
    "mask",
    "maskamg",
    "materialmask",
    "detailmask",
    "sp",
    "spec",
    "specular",
    "rough",
    "roughness",
    "metal",
    "metallic",
    "metalness",
    "ao",
    "occlusion",
    "disp",
    "displacement",
    "height",
    "hgt",
    "depth",
    "dmap",
    "bump",
    "pom",
    "parallax",
    "alpha",
    "opacity",
}

_VISIBLE_BASE_TOKENS = {
    "o",
    "d",
    "diff",
    "diffuse",
    "base",
    "basecolor",
    "basecolour",
    "base_color",
    "albedo",
    "color",
    "colour",
    "col",
    "ct",
    "bc",
    "overlay",
    "overlaycolor",
}

_LOW_AUTHORITY_BASE_MARKERS = (
    "nonetexture",
    "default_overlay",
    "common_default",
    "overlay_old",
    "texturelayer",
)

_SHADER_RULE_PARAMETER_NOTES = {
    "skin": "registry:skin base/normal/material/height + skin detail/damage parameters",
    "standard_v2": "registry:standard_v2 colorBlendingMask/detailMask/grime/detail/dye parameters",
    "emissive_v2": "registry:emissive_v2 standard_v2 mask/detail parameters plus emissive visible layers",
    "cloth_v2": "registry:cloth_v2 colorBlendingMask/detailMask/grime/detail/dye/cloth parameters",
    "cloth": "registry:cloth base/material/mask/detail/dye/cloth parameters",
    "standard": "registry:standard base/material/mask/detail/dye/damage parameters",
    "hair": "registry:hair base/material/flow/mask/hair dye parameters",
    "static_multitextured": "registry:static_multitextured rgbTexture color/normal/material/height layer parameters",
    "static_standard": "registry:static_standard base/material/normal/height parameters",
}

_LAYER_CHANNEL_INDEX = {"r": 0, "g": 1, "b": 2, "a": 3}

_NONMETAL_SURFACE_TOKENS = {
    "cloth": (
        "cloth",
        "cloak",
        "cape",
        "fabric",
        "flag",
        "banner",
        "mantle",
        "robe",
        "sash",
        "skirt",
        "dress",
        "ribbon",
        "tassel",
        "fringe",
        "flap",
        "vest",
    ),
    "leather": (
        "leather",
        "hide",
        "strap",
        "belt",
        "grip",
        "wrap",
        "handle",
    ),
    "wood": (
        "wood",
        "timber",
        "stick",
        "shaft",
        "haft",
        "plank",
    ),
    "skin": (
        "skin",
        "face",
        "nude",
        "body",
        "hand",
        "foot",
    ),
    "hair": (
        "hair",
        "fur",
        "beard",
        "brow",
        "eyebrow",
        "lash",
        "eyelash",
    ),
}

_METALLIC_SURFACE_TOKENS = (
    "metal",
    "metallic",
    "steel",
    "iron",
    "silver",
    "gold",
    "copper",
    "bronze",
    "brass",
    "chrome",
    "blade",
    "guard",
    "hilt",
    "helmet",
    "helm",
    "armor",
    "armour",
    "plate",
    "chain",
)

_STRUCTURAL_ANATOMY_TOKENS = (
    "robot",
    "golem",
    "automaton",
    "machine",
    "mechanical",
    "mech",
    "armor",
    "armour",
    "plate",
)

_AMBIGUOUS_ANATOMY_TOKENS = {"body", "hand", "foot"}

_NONMETAL_RESPONSE_LIMITS = {
    "cloth": (0.0, 0.28, 0.48),
    "leather": (0.0, 0.36, 0.38),
    "wood": (0.0, 0.30, 0.44),
    "skin": (0.0, 0.34, 0.30),
    "hair": (0.0, 0.46, 0.36),
}


def _finite_float(value: object, fallback: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    return result if math.isfinite(result) else fallback


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))



def _texture_label(*values: object) -> str:
    for value in values:
        text = str(value or "").replace("\\", "/").strip()
        if text:
            return PurePosixPath(text).name or text
    return "texture"


def _normalize_texture_key(value: object) -> str:
    text = str(value or "").replace("\\", "/").strip().lower()
    if not text:
        return ""
    path = PurePosixPath(text)
    return path.name or text


def _stem_tokens(*values: object) -> Tuple[str, ...]:
    tokens: list[str] = []
    for value in values:
        text = str(value or "").replace("\\", "/").strip()
        if not text:
            continue
        stem = PurePosixPath(text).stem.lower()
        tokens.extend(token for token in re.split(r"[^a-z0-9]+", stem) if token)
    return tuple(tokens)


def _descriptor_contains_token(descriptor: str, token: str) -> bool:
    needle = str(token or "").strip().lower()
    if not needle:
        return False
    start = 0
    while True:
        index = descriptor.find(needle, start)
        if index < 0:
            return False
        end = index + len(needle)
        left_boundary = index == 0 or not descriptor[index - 1].isalnum()
        right_boundary = end >= len(descriptor) or not descriptor[end].isalnum()
        if left_boundary and right_boundary:
            return True
        start = end


def _material_surface_descriptor(input_item: Optional[PreviewMaterialTextureInput], payload: object = None) -> str:
    parts: list[str] = []
    for source in (input_item, payload):
        if source is None:
            continue
        for name in (
            "slot_kind",
            "parameter_name",
            "source_texture_path",
            "source_dds_path",
            "texture_name",
            "semantic_type",
            "semantic_subtype",
            "material_name",
            "part_name",
            "shader_family",
            "layer_role",
            "layer_channel",
        ):
            parts.append(str(getattr(source, name, "") or ""))
        parts.extend(str(value or "") for value in tuple(getattr(source, "packed_channels", ()) or ()))
        parts.extend(str(value or "") for value in tuple(getattr(source, "blend_flags", ()) or ()))
    return " ".join(part.replace("\\", "/") for part in parts if str(part or "").strip()).lower()


def _material_surface_category(input_item: Optional[PreviewMaterialTextureInput], payload: object = None) -> str:
    if input_item is not None:
        shader_rule = _texture_rule_for_input(input_item)
        if shader_rule == "skin":
            return "skin"
        if shader_rule == "hair":
            return "hair"
        if shader_rule in {"cloth", "cloth_v2"}:
            return "cloth"
    descriptor = _material_surface_descriptor(input_item, payload)
    structural_anatomy = any(
        _descriptor_contains_token(descriptor, token)
        for token in _STRUCTURAL_ANATOMY_TOKENS
    )
    for category, tokens in _NONMETAL_SURFACE_TOKENS.items():
        matched_tokens = tokens
        if category == "skin" and structural_anatomy:
            # ``body``, ``hand``, and ``foot`` are anatomical only in context.
            # Robot, golem, and armor part names use the same tokens for rigid
            # pieces whose exact PAC material maps must remain eligible for
            # metallic response. Explicit skin/face/nude tokens still win.
            matched_tokens = tuple(
                token for token in tokens
                if token not in _AMBIGUOUS_ANATOMY_TOKENS
            )
        if any(_descriptor_contains_token(descriptor, token) for token in matched_tokens):
            return category
    if any(_descriptor_contains_token(descriptor, token) for token in _METALLIC_SURFACE_TOKENS):
        return "metal"
    return "generic"


def _strong_metallic_override(input_item: Optional[PreviewMaterialTextureInput], payload: object = None) -> bool:
    if input_item is None:
        return False
    descriptor = _material_surface_descriptor(input_item, payload)
    has_metal_token = any(_descriptor_contains_token(descriptor, token) for token in _METALLIC_SURFACE_TOKENS)
    channel = _layer_channel(input_item)
    metallic_hint = _material_parameter_channel_hint(input_item, channel, "metallic", "metalness", "scratchmetallic")
    surface_category = _material_surface_category(input_item, payload)
    if surface_category in _NONMETAL_RESPONSE_LIMITS:
        return bool(has_metal_token and metallic_hint >= 0.68)
    return bool(metallic_hint >= 0.82 or (has_metal_token and metallic_hint >= 0.48))


def _nonmetal_response_limits(category: str) -> Tuple[float, float, float]:
    return _NONMETAL_RESPONSE_LIMITS.get(str(category or "").strip().lower(), (1.0, 1.0, 0.04))


def _apply_nonmetal_response_limits(
    category: str,
    metalness: float,
    specular: float,
    roughness: float,
) -> Tuple[float, float, float]:
    metal_cap, spec_cap, roughness_floor = _nonmetal_response_limits(category)
    return (
        min(_clamp(metalness), metal_cap),
        min(_clamp(specular), spec_cap),
        max(_clamp(roughness), roughness_floor),
    )


_MATERIAL_PART_TOKENS = {
    "acc",
    "accessory",
    "arm",
    "blade",
    "body",
    "face",
    "foot",
    "guard",
    "hair",
    "hand",
    "handle",
    "head",
    "hel",
    "leg",
    "lb",
    "nude",
    "shoe",
    "tail",
    "ub",
}

_MATERIAL_MATCH_WEAK_TOKENS = {
    "cd",
    "dds",
    "map",
    "material",
    "texture",
}


def _material_core_tokens(*values: object) -> Tuple[str, ...]:
    tokens: list[str] = []
    for value in values:
        item_tokens = list(_stem_tokens(value))
        while item_tokens and item_tokens[-1] in _TECHNICAL_BASE_TOKENS:
            item_tokens.pop()
        tokens.extend(
            token
            for token in item_tokens
            if token and token not in _MATERIAL_MATCH_WEAK_TOKENS
        )
    return tuple(tokens)


def _material_compact_key(tokens: Sequence[str]) -> str:
    return "".join(str(token or "") for token in tokens if str(token or ""))


def _material_token_match_score(target_tokens: Sequence[str], input_tokens: Sequence[str]) -> int:
    target = tuple(str(token or "").strip().lower() for token in target_tokens if str(token or "").strip())
    source = tuple(str(token or "").strip().lower() for token in input_tokens if str(token or "").strip())
    if not target or not source:
        return 0
    target_key = _material_compact_key(target)
    source_key = _material_compact_key(source)
    score = 0
    if target_key and target_key == source_key:
        score = 120
    elif target_key and source_key and min(len(target_key), len(source_key)) >= 8 and (
        target_key in source_key or source_key in target_key
    ):
        score = 92
    target_set = set(target)
    source_set = set(source)
    shared = target_set.intersection(source_set)
    if shared:
        ratio = len(shared) / float(max(1, len(target_set)))
        if ratio >= 0.58:
            score = max(score, int(24 + (ratio * 66)))
    target_parts = target_set.intersection(_MATERIAL_PART_TOKENS)
    source_parts = source_set.intersection(_MATERIAL_PART_TOKENS)
    if target_parts and source_parts and target_parts.isdisjoint(source_parts):
        score = max(0, score - 45)
    return score


def _material_candidate_match_score(input_item: PreviewMaterialTextureInput, payload: object) -> int:
    target_groups = (
        _material_core_tokens(getattr(payload, "material_name", "")),
        _material_core_tokens(getattr(payload, "texture_name", "")),
    )
    source_groups = (
        _material_core_tokens(input_item.material_name),
        _material_core_tokens(input_item.part_name),
        _material_core_tokens(input_item.texture_name),
        _material_core_tokens(input_item.source_texture_path),
    )
    score = 0
    for target_tokens in target_groups:
        for source_tokens in source_groups:
            score = max(score, _material_token_match_score(target_tokens, source_tokens))
    confidence = str(input_item.confidence or "").strip().lower()
    if confidence in {"sidecar-exact", "prepared", "resolved"}:
        score += 8
    elif "sidecar" in confidence:
        score += 5
    return score


def _semantic_text(input_item: PreviewMaterialTextureInput) -> str:
    return " ".join(
        str(value or "").strip().lower()
        for value in (
            input_item.slot_kind,
            input_item.parameter_name,
            input_item.texture_name,
            input_item.source_texture_path,
            input_item.semantic_type,
            input_item.semantic_subtype,
            getattr(input_item, "shader_family", ""),
            " ".join(input_item.packed_channels),
        )
        if str(value or "").strip()
    )


def _normalized_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _material_parameters(input_item: PreviewMaterialTextureInput) -> Tuple[object, ...]:
    return tuple(getattr(input_item, "material_parameters", ()) or ())


def _material_parameter_count(input_item: PreviewMaterialTextureInput) -> int:
    return len(_material_parameters(input_item))


def _byte4_channels(value: object) -> Tuple[float, float, float, float]:
    text = str(value or "").strip()
    if not text:
        return ()
    if not re.fullmatch(r"[+-]?\d+", text):
        return ()
    try:
        integer = int(text)
    except (TypeError, ValueError, OverflowError):
        return ()
    integer = max(0, min(0xFFFFFFFF, integer))
    return tuple(((integer >> (8 * index)) & 0xFF) / 255.0 for index in range(4))  # type: ignore[return-value]


def _material_parameter_record_for_key(input_item: PreviewMaterialTextureInput, *tokens: str) -> Optional[object]:
    wanted = tuple(_normalized_key(token) for token in tokens if str(token or "").strip())
    if not wanted:
        return None
    best: Optional[object] = None
    best_score = -1
    for parameter in _material_parameters(input_item):
        key = _normalized_key(getattr(parameter, "parameter_name", ""))
        if not key:
            continue
        matched = [token for token in wanted if token and token in key]
        if not matched:
            continue
        score = max(len(token) for token in matched)
        if score > best_score:
            best = parameter
            best_score = score
    return best


def _material_parameter_color(input_item: PreviewMaterialTextureInput, *tokens: str) -> Tuple[float, float, float]:
    parameter = _material_parameter_record_for_key(input_item, *tokens)
    if parameter is None:
        return ()
    color = tuple(getattr(parameter, "color_value", ()) or ())
    if len(color) >= 3:
        return tuple(_clamp(_finite_float(value, 1.0), 0.0, 2.0) for value in color[:3])  # type: ignore[return-value]
    channels = _byte4_channels(getattr(parameter, "value", ""))
    if len(channels) >= 3:
        return tuple(_clamp(value, 0.0, 1.0) for value in channels[:3])  # type: ignore[return-value]
    return ()


def _material_parameter_color_exact(
    input_item: PreviewMaterialTextureInput,
    parameter_name: str,
) -> Tuple[float, float, float]:
    wanted = _normalized_key(parameter_name)
    if not wanted:
        return ()
    for parameter in _material_parameters(input_item):
        if _normalized_key(getattr(parameter, "parameter_name", "")) != wanted:
            continue
        color = tuple(getattr(parameter, "color_value", ()) or ())
        if len(color) >= 3:
            return tuple(
                _clamp(_finite_float(value, 1.0), 0.0, 2.0)
                for value in color[:3]
            )  # type: ignore[return-value]
        channels = _byte4_channels(getattr(parameter, "value", ""))
        if len(channels) >= 3:
            return tuple(_clamp(value) for value in channels[:3])  # type: ignore[return-value]
        return ()
    return ()


def _material_parameter_channels(input_item: PreviewMaterialTextureInput, *tokens: str) -> Tuple[float, float, float, float]:
    parameter = _material_parameter_record_for_key(input_item, *tokens)
    if parameter is None:
        return ()
    return _byte4_channels(getattr(parameter, "value", ""))


def _material_parameter_integer(input_item: PreviewMaterialTextureInput, *tokens: str) -> Optional[int]:
    parameter = _material_parameter_record_for_key(input_item, *tokens)
    if parameter is None:
        return None
    text = str(getattr(parameter, "value", "") or "").strip()
    if not text:
        return None
    try:
        return int(text, 0)
    except (TypeError, ValueError, OverflowError):
        return None


def _color_blending_disabled(input_item: PreviewMaterialTextureInput) -> bool:
    value = _material_parameter_integer(input_item, "colorblendingflag")
    return value == 0


def _color_blending_channel_enabled(input_item: PreviewMaterialTextureInput, channel: str, role: str) -> bool:
    value = _material_parameter_integer(input_item, "colorblendingflag")
    if value is None:
        return True
    if value == 0:
        return False
    channel_index = _LAYER_CHANNEL_INDEX.get(str(channel or "").strip().lower(), -1)
    if channel_index < 0:
        return True
    # Corpus values such as 0x00FF, 0x0F0F, and 0x0FFF appear to gate repeated
    # RGB/A layer groups rather than one single suffix. Until the exact shader
    # bit layout is proven, accept the channel if any known nibble group enables it.
    candidate_bits = (channel_index, channel_index + 4, channel_index + 8)
    if any(value & (1 << bit) for bit in candidate_bits):
        return True
    if role in {"base", "overlay", "emissive"}:
        return True
    return False


def _material_parameter_hint(input_item: PreviewMaterialTextureInput, *tokens: str) -> float:
    wanted = tuple(_normalized_key(token) for token in tokens if str(token or "").strip())
    if not wanted:
        return 0.0
    best = 0.0
    for parameter in _material_parameters(input_item):
        key = _normalized_key(getattr(parameter, "parameter_name", ""))
        if not key or not any(token in key for token in wanted):
            continue
        channels = _byte4_channels(getattr(parameter, "value", ""))
        if channels:
            best = max(best, max(channels[:3]))
            continue
        numeric_value = getattr(parameter, "numeric_value", None)
        if numeric_value is not None:
            best = max(best, _clamp(_finite_float(numeric_value, 0.0)))
            continue
        color = tuple(getattr(parameter, "color_value", ()) or ())
        if color:
            best = max(best, max(_clamp(_finite_float(value, 0.0)) for value in color[:3]))
    return _clamp(best)


def _material_parameter_numeric(input_item: PreviewMaterialTextureInput, *tokens: str) -> Optional[float]:
    wanted = tuple(_normalized_key(token) for token in tokens if str(token or "").strip())
    if not wanted:
        return None
    for parameter in _material_parameters(input_item):
        key = _normalized_key(getattr(parameter, "parameter_name", ""))
        if not key or not any(token in key for token in wanted):
            continue
        numeric_value = getattr(parameter, "numeric_value", None)
        if numeric_value is not None:
            try:
                return float(numeric_value)
            except (TypeError, ValueError, OverflowError):
                pass
        try:
            return float(str(getattr(parameter, "value", "") or ""))
        except (TypeError, ValueError, OverflowError):
            continue
    return None


def _material_parameter_channel_hint(input_item: PreviewMaterialTextureInput, channel: str, *tokens: str) -> float:
    channel_index = _LAYER_CHANNEL_INDEX.get(str(channel or "").strip().lower(), -1)
    if channel_index < 0:
        return _material_parameter_hint(input_item, *tokens)
    wanted = tuple(_normalized_key(token) for token in tokens if str(token or "").strip())
    if not wanted:
        return 0.0
    best = 0.0
    for parameter in _material_parameters(input_item):
        key = _normalized_key(getattr(parameter, "parameter_name", ""))
        if not key or not any(token in key for token in wanted):
            continue
        channels = _byte4_channels(getattr(parameter, "value", ""))
        if len(channels) > channel_index:
            best = max(best, channels[channel_index])
            continue
        numeric_value = getattr(parameter, "numeric_value", None)
        if numeric_value is not None:
            best = max(best, _clamp(_finite_float(numeric_value, 0.0)))
    return _clamp(best)


def _apply_sidecar_material_hints(
    input_item: PreviewMaterialTextureInput,
    decode_mode: str,
    ao: float,
    roughness: float,
    metalness: float,
    specular: float,
) -> Tuple[float, float, float, float]:
    mode = str(decode_mode or "").strip().lower()
    shader_rule = _texture_rule_for_input(input_item)
    surface_category = _material_surface_category(input_item)
    if shader_rule == "skin" or mode in {"skin_material", "skin_detail_mask"}:
        return ao, roughness, 0.0, min(specular, 0.42)
    if shader_rule not in {"standard_v2", "emissive_v2", "cloth_v2", "cloth", "standard", "static_multitextured", "static_standard"}:
        return ao, roughness, metalness, specular
    channel = _layer_channel(input_item)
    metallic_hint = _material_parameter_channel_hint(input_item, channel, "metallic", "metalness", "scratchmetallic")
    roughness_hint = _material_parameter_channel_hint(input_item, channel, "roughness", "scratchroughness")
    specular_hint = _material_parameter_hint(input_item, "specular", "specularamount")
    if metallic_hint > 0.02:
        metalness = max(metalness, metallic_hint * 0.42)
        specular = max(specular, 0.14 + metallic_hint * 0.32)
    if roughness_hint > 0.02:
        roughness = _clamp((roughness * 0.72) + (roughness_hint * 0.28), 0.04, 0.98)
    if specular_hint > 0.02:
        specular = max(specular, specular_hint * 0.58)
    if surface_category in _NONMETAL_RESPONSE_LIMITS and not _strong_metallic_override(input_item):
        metalness, specular, roughness = _apply_nonmetal_response_limits(
            surface_category,
            metalness,
            specular,
            roughness,
        )
    return _clamp(ao, 0.45, 1.0), _clamp(roughness, 0.04, 1.0), _clamp(metalness), _clamp(specular)


def _shader_rule_for_inputs(inputs: Sequence[PreviewMaterialTextureInput], payload: object) -> str:
    shader_text = " ".join(
        str(getattr(item, "shader_family", "") or "")
        for item in tuple(inputs or ())
    )
    shader_text = f"{shader_text} {getattr(payload, 'shader_family', '')}".lower()
    normalized_family = normalize_shader_family(shader_text)
    if normalized_family in {"skin", "hair", "emissive_v2", "cloth_v2", "cloth", "standard_v2", "standard", "static_multitextured", "static_standard"}:
        return normalized_family
    compact = _normalized_key(shader_text)
    if "skinnedmeshskin" in compact:
        return "skin"
    if any(marker in compact for marker in ("skinnedmeshanimalhair", "skinnedmeshhairstandard", "skinnedmeshhair", "skinnedmeshfur")):
        return "hair"
    if "skinnedmeshemissivever2" in compact or "skinnedmeshemissive" in compact:
        return "emissive_v2"
    if "skinnedmeshstandardver2" in compact:
        return "standard_v2"
    if "skinnedmeshclothver2" in compact:
        return "cloth_v2"
    if "skinnedmeshcloth" in compact:
        return "cloth"
    if "skinnedmeshstandard" in compact:
        return "standard"
    if "multitextured" in compact:
        return "static_multitextured"
    if "standard" in compact:
        return "static_standard"
    return "generic"


def _texture_rule_for_input(input_item: PreviewMaterialTextureInput) -> str:
    return _shader_rule_for_inputs((input_item,), object())


def _registry_decode_for_input(input_item: PreviewMaterialTextureInput) -> dict[str, object]:
    return dict(
        decode_crimson_texture_binding(
            shader_family=str(getattr(input_item, "shader_family", "") or ""),
            parameter_name=str(getattr(input_item, "parameter_name", "") or ""),
            source_path=str(getattr(input_item, "source_dds_path", "") or getattr(input_item, "source_texture_path", "") or getattr(input_item, "preview_texture_path", "") or ""),
            slot_name=str(getattr(input_item, "slot_kind", "") or "material"),
            semantic_subtype=str(getattr(input_item, "semantic_subtype", "") or ""),
            packed_channels=tuple(getattr(input_item, "packed_channels", ()) or ()),
            layer_channel=str(getattr(input_item, "layer_channel", "") or ""),
            blend_flags=tuple(getattr(input_item, "blend_flags", ()) or ()),
            sidecar_kind=str(getattr(input_item, "sidecar_kind", "") or ""),
            parameter_declared_by=str(getattr(input_item, "parameter_declared_by", "") or ""),
        )
    )


def _registry_decode_mode_for_input(input_item: PreviewMaterialTextureInput) -> str:
    decode = _registry_decode_for_input(input_item)
    source_kind = str(decode.get("source_kind", "") or "")
    disposition = str(decode.get("disposition", "") or "")
    authority = str(decode.get("authority", "") or AUTHORITY_GUESS)
    promoted = decode.get("promoted_channels", {})
    family = str(decode.get("shader_family", "") or _texture_rule_for_input(input_item))
    if authority == AUTHORITY_GUESS and source_kind not in {"explicit_packed_material"}:
        return ""
    if source_kind in {"crimson_overlay_color", "crimson_base_color", "crimson_diffuse", "crimson_albedo", "crimson_color"}:
        return "visible_color"
    if source_kind == "crimson_color_blending_mask":
        return "color_blending_mask"
    if disposition == "layer_material_response" or source_kind == "crimson_layer_material_response":
        if family == "skin":
            return "skin_material"
        if family == "hair":
            return "hair_material"
        parameter_key = _normalized_key(getattr(input_item, "parameter_name", ""))
        tokens = _stem_tokens(getattr(input_item, "source_texture_path", ""), getattr(input_item, "texture_name", ""))
        if parameter_key in {"materialtexture", "materialmap"} and tokens and tokens[-1] in {"sp", "spec", "specular"}:
            return "standard_v2_specular" if family in {"standard_v2", "emissive_v2", "cloth_v2", "cloth", "standard"} else "material_response"
        if family == "static_multitextured":
            return "static_multitextured_material"
        if family in {"standard_v2", "emissive_v2", "cloth_v2", "cloth", "standard"}:
            return "standard_v2_material"
        return "material_response"
    if disposition == "layer_only" or source_kind in {"crimson_detail_mask", "crimson_dye_control"}:
        return "standard_v2_detail" if family in {"standard_v2", "emissive_v2", "cloth_v2", "cloth", "standard"} else "detail_mask"
    if source_kind in {"crimson_flow_vector", "crimson_hair_direction", "crimson_eye_layer"}:
        return "diagnostic"
    if source_kind == "explicit_packed_material":
        return "orm"
    return ""


def _parameter_key(input_item: PreviewMaterialTextureInput) -> str:
    return _normalized_key(getattr(input_item, "parameter_name", ""))


def _layer_channel(input_item: PreviewMaterialTextureInput) -> str:
    declared = str(getattr(input_item, "layer_channel", "") or "").strip().lower()
    if declared in {"r", "g", "b", "a"}:
        return declared
    key = _parameter_key(input_item)
    for suffix in ("r", "g", "b", "a"):
        if key.endswith(suffix):
            return suffix
    return ""


def _is_low_authority_base(input_item: PreviewMaterialTextureInput) -> bool:
    descriptor = " ".join(
        str(value or "").replace("\\", "/").lower()
        for value in (
            input_item.source_texture_path,
            input_item.texture_name,
            input_item.parameter_name,
            input_item.semantic_subtype,
            input_item.confidence,
        )
    )
    return any(marker in descriptor for marker in _LOW_AUTHORITY_BASE_MARKERS)


def _is_visible_color_input(input_item: PreviewMaterialTextureInput) -> bool:
    key = _parameter_key(input_item)
    semantic_type = str(getattr(input_item, "semantic_type", "") or "").strip().lower()
    semantic_subtype = str(getattr(input_item, "semantic_subtype", "") or "").strip().lower()
    if semantic_type in {"color", "emissive"}:
        return not _looks_like_technical_base(input_item)
    if semantic_subtype in {"albedo", "diffuse", "detail_diffuse", "albedo_variant", "emissive"}:
        return not _looks_like_technical_base(input_item)
    if any(token in key for token in ("basecolor", "overlaycolor", "diffusetexture", "diffusemask", "colortexture", "albedo", "emissive", "glow", "illum")):
        return True
    return False


def _visible_layer_role(input_item: PreviewMaterialTextureInput) -> str:
    declared = str(getattr(input_item, "layer_role", "") or "").strip().lower()
    if declared:
        return declared
    key = _parameter_key(input_item)
    channel = _layer_channel(input_item)
    if "layerbasecolor" in key:
        return "layer"
    if "colortexture" in key and channel:
        return "layer"
    if "grimediffuse" in key:
        return "grime"
    if "detaildiffuse" in key:
        return "detail"
    if "damageblendingdiffuse" in key:
        return "damage"
    if "overlaycolor" in key:
        return "overlay"
    if "basecolor" in key or "basetexture" in key:
        return "base"
    if "emissive" in key:
        return "emissive"
    return "color"


def _looks_like_technical_base(input_item: PreviewMaterialTextureInput) -> bool:
    tokens = _stem_tokens(input_item.source_texture_path, input_item.texture_name, input_item.preview_texture_path)
    semantic = _semantic_text(input_item)
    if any(token in {"normal", "height", "displacement", "material", "mask", "opacity", "alpha", "vector"} for token in semantic.split()):
        if not any(token in semantic for token in ("basecolor", "overlaycolor", "diffuse", "albedo", "colortexture")):
            return True
    if not tokens:
        return False
    last = tokens[-1]
    if last in _TECHNICAL_BASE_TOKENS:
        return True
    normalized = "".join(tokens)
    return normalized.endswith(
        (
            "normalmap",
            "materialmask",
            "detailmask",
            "displacement",
            "roughness",
            "metallic",
            "specular",
            "opacity",
        )
    )


def _is_layer_only_base_color(input_item: PreviewMaterialTextureInput) -> bool:
    decode = _registry_decode_for_input(input_item)
    disposition = str(decode.get("disposition", "") or "").strip().lower()
    source_kind = str(decode.get("source_kind", "") or "").strip().lower()
    parameter_key = _parameter_key(input_item)
    if disposition in {"layer_only", "layer_material_response", "layer_flow", "layer_direction"}:
        return True
    return bool(
        source_kind.startswith("crimson_layer")
        or source_kind in {"crimson_detail_mask", "crimson_skin_detail_mask", "crimson_dye_control"}
        or any(token in parameter_key for token in ("detaildiffuse", "grimediffuse", "damageblendingdiffuse"))
    )


def _looks_like_visible_base(input_item: PreviewMaterialTextureInput) -> bool:
    semantic = _semantic_text(input_item)
    if any(token in semantic for token in ("basecolor", "overlaycolor", "diffuse", "albedo", "colortexture", "basetexture")):
        return True
    tokens = _stem_tokens(input_item.source_texture_path, input_item.texture_name)
    if tokens and tokens[-1] in _VISIBLE_BASE_TOKENS:
        return True
    return not _looks_like_technical_base(input_item)


def _select_visible_layer_inputs(
    inputs: Sequence[PreviewMaterialTextureInput],
    *,
    selected_base: Optional[PreviewMaterialTextureInput],
) -> Tuple[PreviewMaterialTextureInput, ...]:
    selected_key = (
        str(getattr(selected_base, "preview_texture_path", "") or "").strip().lower(),
        str(getattr(selected_base, "source_texture_path", "") or "").strip().lower(),
    )
    ranked: list[Tuple[int, int, PreviewMaterialTextureInput]] = []
    for index, item in enumerate(inputs):
        if not _is_visible_color_input(item):
            continue
        # Emissive and intensity maps are additive shader inputs. Treating one
        # as albedo turns its scalar mask into the full surface color.
        if _visible_layer_role(item) == "emissive":
            continue
        current_key = (
            str(getattr(item, "preview_texture_path", "") or "").strip().lower(),
            str(getattr(item, "source_texture_path", "") or "").strip().lower(),
        )
        if selected_base is not None and current_key == selected_key:
            continue
        role = _visible_layer_role(item)
        priority = {
            "base": 120,
            "layer": 102,
            "detail": 96,
            "grime": 88,
            "damage": 74,
            "overlay": 64,
            "color": 58,
            "emissive": 32,
        }.get(role, 40)
        match_score = _material_candidate_match_score(item, selected_base or item)
        ranked.append((priority + min(match_score, 40), -index, item))
    ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
    result: list[PreviewMaterialTextureInput] = []
    seen_bindings: set[Tuple[str, str, str, str, str, str]] = set()
    for _priority, _index, item in ranked:
        preview_path = str(getattr(item, "preview_texture_path", "") or "").strip().lower()
        source_path = str(getattr(item, "source_texture_path", "") or "").strip().lower()
        key = (
            preview_path,
            source_path,
            _parameter_key(item),
            _visible_layer_role(item),
            _layer_channel(item),
            str(getattr(item, "owner_wrapper_item_id", "") or "").strip().lower(),
        )
        if not (preview_path or source_path) or key in seen_bindings:
            continue
        seen_bindings.add(key)
        result.append(item)
    return tuple(result)


def _mask_inputs_for_albedo(inputs: Sequence[PreviewMaterialTextureInput]) -> dict[str, PreviewMaterialTextureInput]:
    result: dict[str, PreviewMaterialTextureInput] = {}
    authoritative_color_region_mask = next(
        (
            item
            for item in inputs
            if _parameter_key(item) == "colorblendingmasktexture"
            and str(getattr(item, "sidecar_kind", "") or "").strip().lower() == "pac_xml"
            and str(getattr(item, "binding_authority", "") or "").strip().lower() == "authoritative"
            and str(getattr(item, "binding_disposition", "") or "").strip().lower() == "layer_only"
            and str(getattr(item, "source_kind", "") or "").strip().lower()
            == "crimson_color_blending_mask"
        ),
        None,
    )
    if authoritative_color_region_mask is not None:
        # PAC suffixes are color-region ownership: _detailDiffuseMaskR/G/B and
        # their dye colors belong to the matching R/G/B area of the authored
        # _colorBlendingMaskTexture. _detailMaskTexture is a separate technical
        # detail input; using it as the color-layer selector assigns the wrong
        # material to otherwise correctly authored regions.
        result["detail"] = authoritative_color_region_mask
    for item in inputs:
        key = _parameter_key(item)
        if "colorblendingmask" in key:
            result.setdefault("grime", item)
            result.setdefault("color", item)
        elif key == "rgbtexture":
            result.setdefault("layer", item)
            result.setdefault("detail", item)
            result.setdefault("color", item)
        elif "layermask" in key:
            result.setdefault("layer", item)
        elif "detailmask" in key:
            result.setdefault("detail", item)
        elif key == "masktexture":
            result.setdefault("detail", item)
    return result


def _layer_weight_from_parameters(
    input_item: PreviewMaterialTextureInput,
    *,
    has_base: bool,
) -> float:
    if _color_blending_disabled(input_item):
        return 0.0
    role = _visible_layer_role(input_item)
    channel = _layer_channel(input_item)
    if not _color_blending_channel_enabled(input_item, channel, role):
        return 0.0
    if role == "base":
        return 1.0
    if role == "overlay":
        return 0.22 if has_base else 0.82
    if role == "layer":
        if channel == "g":
            alpha = max(
                _material_parameter_hint(input_item, "alphaheightintensityx", "heightintensityg", "heightintensityx"),
                0.45,
            )
        elif channel == "b":
            alpha = max(
                _material_parameter_hint(input_item, "alphaheightintensityy", "heightintensityb", "heightintensityy"),
                0.45,
            )
        else:
            alpha_x = _material_parameter_hint(input_item, "alphaheightintensityx")
            alpha_y = _material_parameter_hint(input_item, "alphaheightintensityy")
            alpha = max(alpha_x, alpha_y, 0.45)
        return _clamp(alpha, 0.08, 0.70 if has_base else 1.0)
    if role == "damage":
        channels = _material_parameter_channels(input_item, "damageblendingparameter")
        return _clamp(max(channels) if channels else 0.18, 0.04, 0.55)
    if role == "grime":
        token = f"grimeblendingparameter{channel}" if channel else "grimeblendingparameter"
        channels = _material_parameter_channels(input_item, token)
        opacity = channels[3] if len(channels) >= 4 else 0.35
        global_channels = _material_parameter_channels(input_item, "grimeblendingopacityparameter")
        global_channels_1 = _material_parameter_channels(input_item, "grimeblendingopacityparameter1")
        if channel == "r" and len(global_channels) >= 2:
            opacity *= max(0.10, global_channels[1] - global_channels[0])
        elif channel == "g" and len(global_channels) >= 4:
            opacity *= max(0.10, global_channels[3] - global_channels[2])
        elif channel == "b" and len(global_channels_1) >= 2:
            opacity *= max(0.10, global_channels_1[1] - global_channels_1[0])
        return _clamp(opacity, 0.03, 0.70 if has_base else 1.0)
    if role == "detail":
        channels = _material_parameter_channels(input_item, "dyeingglobalopacity")
        channel_index = _LAYER_CHANNEL_INDEX.get(channel, 0)
        opacity = channels[channel_index] if len(channels) > channel_index else 0.42
        authoritative_pac_layer = bool(
            str(getattr(input_item, "sidecar_kind", "") or "").strip().lower() == "pac_xml"
            and str(getattr(input_item, "binding_authority", "") or "").strip().lower()
            == "authoritative"
            and str(getattr(input_item, "binding_disposition", "") or "").strip().lower()
            in {"layer_only", "layer_material_response"}
            and str(getattr(input_item, "source_kind", "") or "").strip().lower()
            in {"crimson_layer_color", "crimson_layer_material_response"}
        )
        if authoritative_pac_layer:
            # ``_dyeingGlobalOpacity`` owns the RGB layer opacity. The packed
            # ``_dyeingPropertyBlend`` controls material properties and is not
            # another color/response opacity multiplier. Applying it here and
            # then imposing the legacy 0.62 cap muted authored dye colors and
            # metal response even when the PAC explicitly requested 255.
            return _clamp(opacity, 0.04, 1.0)
        property_channels = _material_parameter_channels(input_item, "dyeingpropertyblend")
        if property_channels:
            opacity *= max(0.25, max(property_channels[:3]))
        return _clamp(opacity, 0.04, 0.62 if has_base else 1.0)
    return 0.18 if has_base else 0.82


def _layer_tint(input_item: PreviewMaterialTextureInput) -> Tuple[float, float, float]:
    role = _visible_layer_role(input_item)
    channel = _layer_channel(input_item)
    candidates: Tuple[str, ...]
    if role == "detail" and channel:
        candidates = (f"dyeingdetaillayercolormask{channel}", f"dyeingcolormask{channel}", f"tintcolor{channel}")
    elif role == "layer" and channel:
        candidates = (f"tintcolor{channel}", f"heighttintcolor{channel}", "baseheighttintcolor", "tintcolor")
    elif role == "layer":
        candidates = ("baseheighttintcolor", "tintcolor")
    elif role == "grime" and channel:
        candidates = (f"scratchtintcolor{channel}", f"tintcolor{channel}", f"dyeingdetaillayercolormask{channel}")
    elif channel:
        candidates = (f"tintcolor{channel}", f"dyeingcolormask{channel}", f"dyeingdetaillayercolormask{channel}")
    else:
        candidates = ("tintcolor", "dyeingcolormask", "dyeingdetaillayercolormask")
    # Exact match only.  These candidates are an ordered precedence, and
    # substring matching silently defeats it: "tintcolorr" is a substring of
    # "scratchtintcolorr", so a layer asking for its primary dye got the
    # scratch/wear dye instead whenever both were declared.  On
    # `cd_phm_01_axe_0001` that swapped a neutral `_tintColorR`
    # (0.769, 0.765, 0.757) for a cyan `_scratchTintColorR`
    # (0.620, 0.765, 0.765) and turned the steel head blue-teal.
    # `_global_material_base_tint` already guards the same hazard.
    for candidate in candidates:
        color = _material_parameter_color_exact(input_item, candidate)
        if len(color) >= 3:
            return color
    return ()


def _height_amount_multiplier(input_item: PreviewMaterialTextureInput) -> Tuple[float, str]:
    parameter = _material_parameter_record_for_key(
        input_item,
        "screenspacedisplacementscale",
        "detailscreenspacedisplacementscale",
        "heightintensity",
    )
    if parameter is None:
        return 1.0, ""
    numeric_value = getattr(parameter, "numeric_value", None)
    if numeric_value is None:
        return 1.0, ""
    raw_value = _finite_float(numeric_value, 0.0)
    parameter_name = str(getattr(parameter, "parameter_name", "") or "").strip() or "height scale"
    key = _normalized_key(parameter_name)
    if "heightintensity" in key:
        return _clamp(raw_value, 0.0, 1.0), parameter_name
    return _clamp(raw_value * 8.0, 0.0, 1.0), parameter_name



def _payload_vertex_base_color(payload: object) -> Tuple[float, float, float]:
    raw = tuple(getattr(payload, "base_color", ()) or ())
    if len(raw) < 3:
        return ()
    color = tuple(_clamp(_finite_float(value, 0.62), 0.12, 1.0) for value in raw[:3])
    if max(color) - min(color) > 0.22:
        luma = _clamp((0.299 * color[0]) + (0.587 * color[1]) + (0.114 * color[2]), 0.38, 0.74)
        return (luma, luma, luma)
    return color  # type: ignore[return-value]


def _neutral_metal_tint_from_tokens(descriptor: str) -> Tuple[float, float, float]:
    if any(_descriptor_contains_token(descriptor, token) for token in ("gold", "brass")):
        return (0.78, 0.66, 0.36)
    if any(_descriptor_contains_token(descriptor, token) for token in ("bronze", "copper")):
        return (0.70, 0.48, 0.32)
    if any(_descriptor_contains_token(descriptor, token) for token in ("silver", "chrome", "steel", "iron")):
        return (0.66, 0.68, 0.70)
    return ()


def _global_material_base_tint(inputs: Sequence[PreviewMaterialTextureInput]) -> Tuple[float, float, float]:
    # PAC layer tints such as _scratchTintColorR or _tintColorB are scoped to a
    # packed selector channel. Substring matching them as a global tint paints
    # the entire material gold/brown. Only an exact unsuffixed base parameter
    # may affect the full neutral seed.
    for item in inputs:
        for token in ("basecolor", "tintcolor", "albedocolor"):
            color = _material_parameter_color_exact(item, token)
            if len(color) >= 3:
                return color
    return ()


def _authoritative_color_blending_tint_seed(
    inputs: Sequence[PreviewMaterialTextureInput],
) -> Tuple[
    Optional[PreviewMaterialTextureInput],
    Tuple[Tuple[float, float, float], ...],
    str,
]:
    """Return the PAC RGB selector, channel-local colors, and palette source.

    Crimson's ``_colorBlendingMaskTexture`` is a selector, not a PBR packed
    map. A seed is only emitted when the shader registry and PAC binding agree
    on that exact role and all three channel colors are present. This keeps an
    incomplete or filename-only guess from recoloring a whole submesh.
    """

    mask_item: Optional[PreviewMaterialTextureInput] = None
    for candidate in inputs:
        if _parameter_key(candidate) != "colorblendingmasktexture":
            continue
        decode = _registry_decode_for_input(candidate)
        if (
            str(getattr(candidate, "sidecar_kind", "") or "").strip().lower()
            == "pac_xml"
            and str(getattr(candidate, "binding_authority", "") or "").strip().lower()
            == "authoritative"
            and str(getattr(candidate, "binding_disposition", "") or "").strip().lower()
            == "layer_only"
            and str(getattr(candidate, "source_kind", "") or "").strip().lower()
            == "crimson_color_blending_mask"
            and str(decode.get("authority", "") or "") == "authoritative"
            and str(decode.get("source_kind", "") or "")
            == "crimson_color_blending_mask"
            and str(decode.get("disposition", "") or "") == "layer_only"
        ):
            mask_item = candidate
            break
    if mask_item is None:
        return None, (), ""

    scratch_tints: list[Tuple[float, float, float]] = []
    primary_tints: list[Tuple[float, float, float]] = []
    for channel in "rgb":
        scratch_tints.append(_material_parameter_color_exact(mask_item, f"scratchtintcolor{channel}"))
        primary_tints.append(_material_parameter_color_exact(mask_item, f"tintcolor{channel}"))

    # PACs commonly store neutral scratch defaults as black, white, 0.8 gray,
    # or a byte-close warm gray while their primary tint palette carries the
    # authored color. Treat up to 16/255 channel spread as neutral, but only
    # switch when the primary palette contains clear chroma. This preserves
    # intentionally silver/gold scratch palettes and avoids guessing when both
    # palettes are neutral.
    neutral_chroma_epsilon = 16.0 / 255.0

    def _palette_has_chroma(palette: Sequence[Tuple[float, float, float]]) -> bool:
        return any(
            len(color) >= 3 and max(color[:3]) - min(color[:3]) > neutral_chroma_epsilon
            for color in palette
        )

    scratch_present = any(len(color) >= 3 for color in scratch_tints)
    prefer_primary = bool(
        scratch_present
        and not _palette_has_chroma(scratch_tints)
        and _palette_has_chroma(primary_tints)
    )
    preferred_tints = primary_tints if prefer_primary else scratch_tints
    fallback_tints = scratch_tints if prefer_primary else primary_tints

    tints: list[Tuple[float, float, float]] = []
    used_fallback = False
    for preferred, fallback in zip(preferred_tints, fallback_tints):
        color = preferred
        if len(color) < 3:
            color = fallback
            used_fallback = len(color) >= 3
        if len(color) < 3:
            return None, (), ""
        tints.append(color)

    if prefer_primary:
        palette_source = "primary_neutral_scratch"
        if used_fallback:
            palette_source += "_fallback"
    elif scratch_present:
        palette_source = "scratch"
        if used_fallback:
            palette_source += "_primary_fallback"
    else:
        palette_source = "primary"
    return mask_item, tuple(tints), palette_source


def _neutral_metal_base_color(payload: object, inputs: Sequence[PreviewMaterialTextureInput]) -> Tuple[float, float, float]:
    color = _payload_vertex_base_color(payload) or (0.60, 0.61, 0.62)
    material_tint = _global_material_base_tint(inputs)
    if material_tint:
        tint_luma = max(0.08, (0.299 * material_tint[0]) + (0.587 * material_tint[1]) + (0.114 * material_tint[2]))
        tint_bias = tuple(_clamp(component / tint_luma, 0.70, 1.35) for component in material_tint[:3])
        color = tuple(_clamp(color[index] * (0.78 + tint_bias[index] * 0.22), 0.20, 0.88) for index in range(3))
    luma = _clamp((0.299 * color[0]) + (0.587 * color[1]) + (0.114 * color[2]), 0.42, 0.76)
    if max(color) - min(color) < 0.04:
        return (luma, _clamp(luma * 1.01, 0.0, 1.0), _clamp(luma * 1.025, 0.0, 1.0))
    return color  # type: ignore[return-value]


def _should_seed_neutral_metal_base(
    payload: object,
    inputs: Sequence[PreviewMaterialTextureInput],
    visible_layer_inputs: Sequence[PreviewMaterialTextureInput],
    *,
    selected_base_low_authority: bool,
    selected_base_item: Optional[PreviewMaterialTextureInput],
) -> bool:
    if not visible_layer_inputs:
        return False
    if _material_surface_category(None, payload) != "metal":
        return False
    if selected_base_item is not None and not selected_base_low_authority:
        return False
    return any(
        _visible_layer_role(item) in {"grime", "detail", "layer", "damage"}
        or _registry_decode_for_input(item).get("disposition") == "layer_only"
        for item in visible_layer_inputs
    )


def _material_parameter_color_luma(input_item: PreviewMaterialTextureInput, *tokens: str) -> Optional[float]:
    wanted = tuple(_normalized_key(token) for token in tokens if str(token or "").strip())
    if not wanted:
        return None
    for parameter in _material_parameters(input_item):
        key = _normalized_key(getattr(parameter, "parameter_name", ""))
        if not key or not any(token in key for token in wanted):
            continue
        color = tuple(getattr(parameter, "color_value", ()) or ())
        if len(color) >= 3:
            try:
                r, g, b = (_clamp(_finite_float(component, 0.0)) for component in color[:3])
            except (TypeError, ValueError, OverflowError):
                continue
            return _clamp((0.299 * r) + (0.587 * g) + (0.114 * b))
        numeric_value = getattr(parameter, "numeric_value", None)
        if numeric_value is not None:
            return _clamp(_finite_float(numeric_value, 0.0))
        channels = _byte4_channels(getattr(parameter, "value", ""))
        if channels:
            return _clamp((0.299 * channels[0]) + (0.587 * channels[1]) + (0.114 * channels[2]))
    return None



def _first_input_by_parameter(
    inputs: Sequence[PreviewMaterialTextureInput],
    *parameter_keys: str,
) -> Optional[PreviewMaterialTextureInput]:
    wanted = tuple(_normalized_key(key) for key in parameter_keys if str(key or "").strip())
    if not wanted:
        return None
    for item in inputs:
        key = _parameter_key(item)
        if key in wanted:
            return item
    return None


def _material_layer_mask_for_input(
    input_item: PreviewMaterialTextureInput,
    inputs: Sequence[PreviewMaterialTextureInput],
) -> Tuple[Optional[PreviewMaterialTextureInput], str, str]:
    key = _parameter_key(input_item)
    channel = _layer_channel(input_item) or "r"
    shader_rule = _texture_rule_for_input(input_item)
    if "detailmaterial" in key:
        return _first_input_by_parameter(inputs, "detailmasktexture", "detailmask"), channel, f"detail:{channel}"
    if "grimematerial" in key:
        return _first_input_by_parameter(inputs, "colorblendingmasktexture", "blendingmasktexture"), channel, f"grime:{channel}"
    if "damageblendingmaterial" in key:
        return _first_input_by_parameter(inputs, "masktexture", "damageblendingmasktexture"), channel, "damage"
    if shader_rule == "static_multitextured":
        if key.startswith("materialtexture") and channel:
            return _first_input_by_parameter(inputs, "rgbtexture", "layermasktexture", "layerblendmasktexture"), channel, f"layer:{channel}"
        if "layerspeculartexture" in key or "layermaterialtexture" in key:
            return _first_input_by_parameter(inputs, "layermasktexture", "layerblendmasktexture", "rgbtexture"), "r", "layer"
    return None, "", ""
