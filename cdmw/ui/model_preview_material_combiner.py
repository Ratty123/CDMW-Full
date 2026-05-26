from __future__ import annotations

from dataclasses import dataclass
import math
import re
from pathlib import Path, PurePosixPath
from typing import Optional, Sequence, Tuple

from PySide6.QtCore import QSize, QUrl, Qt
from PySide6.QtGui import QColor, QImage, QImageReader

from cdmw.models import PreviewMaterialTextureInput


@dataclass(frozen=True, slots=True)
class MaterialPreviewCombinerSettings:
    normal_strength_floor: float = 0.5
    normal_strength_cap: float = 1.0
    height_amount: float = 0.04
    support_map_max_dimension: int = 256


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


def _finite_float(value: object, fallback: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    return result if math.isfinite(result) else fallback


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def _byte(value: float) -> int:
    return max(0, min(255, int(round(_clamp(value) * 255.0))))


def _source_url_local_path(source_url: str) -> str:
    normalized = str(source_url or "").strip()
    if not normalized:
        return ""
    try:
        path = QUrl(normalized).toLocalFile()
    except Exception:
        path = ""
    return path or normalized


def _local_file_url(path: Path) -> str:
    return QUrl.fromLocalFile(str(path.resolve())).toString()


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
    return _clamp(ao, 0.45, 1.0), _clamp(roughness, 0.04, 1.0), _clamp(metalness), _clamp(specular)


def _shader_rule_for_inputs(inputs: Sequence[PreviewMaterialTextureInput], payload: object) -> str:
    shader_text = " ".join(
        str(getattr(item, "shader_family", "") or "")
        for item in tuple(inputs or ())
    )
    shader_text = f"{shader_text} {getattr(payload, 'shader_family', '')}".lower()
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
    seen_paths: set[str] = set()
    for _priority, _index, item in ranked:
        key = str(getattr(item, "preview_texture_path", "") or getattr(item, "source_texture_path", "") or "").strip().lower()
        if not key or key in seen_paths:
            continue
        seen_paths.add(key)
        result.append(item)
        if len(result) >= 4:
            break
    return tuple(result)


def _mask_inputs_for_albedo(inputs: Sequence[PreviewMaterialTextureInput]) -> dict[str, PreviewMaterialTextureInput]:
    result: dict[str, PreviewMaterialTextureInput] = {}
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
        candidates = (f"tintcolor{channel}", f"dyeingdetaillayercolormask{channel}", f"scratchtintcolor{channel}")
    elif channel:
        candidates = (f"tintcolor{channel}", f"dyeingcolormask{channel}", f"dyeingdetaillayercolormask{channel}")
    else:
        candidates = ("tintcolor", "dyeingcolormask", "dyeingdetaillayercolormask")
    for candidate in candidates:
        color = _material_parameter_color(input_item, candidate)
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


def _mask_alpha(
    mask_image: QImage,
    x: int,
    y: int,
    *,
    channel: str,
) -> float:
    if mask_image.isNull():
        return 1.0
    color = mask_image.pixelColor(x, y)
    index = _LAYER_CHANNEL_INDEX.get(channel, 0)
    values = (color.redF(), color.greenF(), color.blueF(), color.alphaF())
    return _clamp(values[index] if index < len(values) else values[0])


def _generate_synthesized_albedo_map(
    base_image: QImage,
    layer_inputs: Sequence[PreviewMaterialTextureInput],
    mask_inputs: dict[str, PreviewMaterialTextureInput],
    output_dir: Path,
    stem: str,
    *,
    flip_vertical: bool,
    max_dimension: int,
) -> Tuple[str, str]:
    prepared_base = _support_source_image(base_image, flip_vertical=flip_vertical, max_dimension=max_dimension)
    source_layers: list[Tuple[PreviewMaterialTextureInput, QImage]] = []
    for item in layer_inputs:
        image = _image_reader(str(getattr(item, "preview_texture_path", "") or ""), max_dimension=max_dimension)
        if image.isNull():
            continue
        prepared = _support_source_image(image, flip_vertical=flip_vertical, max_dimension=max_dimension)
        if prepared.isNull():
            continue
        source_layers.append((item, prepared.convertToFormat(QImage.Format.Format_RGBA8888)))
    if prepared_base.isNull() and not source_layers:
        return "", ""

    if not prepared_base.isNull():
        width = int(prepared_base.width())
        height = int(prepared_base.height())
        target = prepared_base.convertToFormat(QImage.Format.Format_RGB888)
        layer_start = 0
    else:
        first_item, first_image = source_layers[0]
        width = int(first_image.width())
        height = int(first_image.height())
        target = QImage(width, height, QImage.Format.Format_RGB888)
        tint = _layer_tint(first_item)
        for y in range(height):
            for x in range(width):
                color = first_image.pixelColor(x, y)
                red, green, blue = color.redF(), color.greenF(), color.blueF()
                if tint:
                    red *= tint[0]
                    green *= tint[1]
                    blue *= tint[2]
                target.setPixelColor(x, y, QColor(_byte(red), _byte(green), _byte(blue)))
        layer_start = 1

    prepared_masks: dict[str, QImage] = {}
    for role, item in mask_inputs.items():
        image = _image_reader(str(getattr(item, "preview_texture_path", "") or ""), max_dimension=max_dimension)
        if image.isNull():
            continue
        prepared = _support_source_image(image, flip_vertical=flip_vertical, max_dimension=max_dimension)
        if prepared.isNull():
            continue
        if int(prepared.width()) != width or int(prepared.height()) != height:
            prepared = prepared.scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        prepared_masks[role] = prepared.convertToFormat(QImage.Format.Format_RGBA8888)

    roles_used: list[str] = []
    has_base = not prepared_base.isNull()
    for item, image in source_layers[layer_start:]:
        layer = image
        if int(layer.width()) != width or int(layer.height()) != height:
            layer = layer.scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        role = _visible_layer_role(item)
        channel = _layer_channel(item)
        mask = prepared_masks.get(role) or prepared_masks.get("color") or QImage()
        weight = _layer_weight_from_parameters(item, has_base=has_base)
        if weight <= 0.001:
            continue
        tint = _layer_tint(item)
        for y in range(height):
            for x in range(width):
                base = target.pixelColor(x, y)
                overlay = layer.pixelColor(x, y)
                alpha = _clamp(weight * _mask_alpha(mask, x, y, channel=channel))
                red = overlay.redF()
                green = overlay.greenF()
                blue = overlay.blueF()
                if tint:
                    red *= tint[0]
                    green *= tint[1]
                    blue *= tint[2]
                out_r = (base.redF() * (1.0 - alpha)) + (_clamp(red) * alpha)
                out_g = (base.greenF() * (1.0 - alpha)) + (_clamp(green) * alpha)
                out_b = (base.blueF() * (1.0 - alpha)) + (_clamp(blue) * alpha)
                target.setPixelColor(x, y, QColor(_byte(out_r), _byte(out_g), _byte(out_b)))
        role_label = role if not channel else f"{role}:{channel}"
        if role_label not in roles_used:
            roles_used.append(role_label)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{stem}_albedo.png"
    if not target.save(str(output_path), "PNG"):
        return "", ""
    if roles_used:
        note = "albedo synthesized:" + ",".join(roles_used[:6])
    else:
        note = "albedo synthesized:visible layer"
    if prepared_base.isNull():
        note += "; no reliable base DDS"
    return _local_file_url(output_path), note


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


def _image_reader(source_url: str, *, max_dimension: int = 0) -> QImage:
    source_path = _source_url_local_path(source_url)
    if not source_path:
        return QImage()
    reader = QImageReader(source_path)
    reader.setAutoTransform(True)
    limit = max(0, int(max_dimension or 0))
    if limit > 0:
        size = reader.size()
        if size.isValid() and max(int(size.width()), int(size.height())) > limit:
            target = size.scaled(limit, limit, Qt.KeepAspectRatio)
            if target.width() > 0 and target.height() > 0:
                reader.setScaledSize(target)
    return reader.read()


def _prepare_image(
    image: QImage,
    output_dir: Path,
    stem: str,
    *,
    flip_vertical: bool,
    force_opaque: bool,
    max_dimension: int = 0,
) -> Tuple[str, str]:
    if image.isNull():
        return "", ""
    if max_dimension > 0:
        width = int(image.width())
        height = int(image.height())
        longest = max(width, height)
        if longest > int(max_dimension):
            target = QSize(width, height).scaled(int(max_dimension), int(max_dimension), Qt.KeepAspectRatio)
            if target.width() > 0 and target.height() > 0:
                image = image.scaled(target, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    image = image.convertToFormat(QImage.Format.Format_RGB888 if force_opaque else QImage.Format.Format_RGBA8888)
    if image.isNull():
        return "", ""
    if flip_vertical:
        image = image.flipped(Qt.Orientation.Vertical)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{stem}.png"
    if not image.save(str(output_path), "PNG"):
        return "", ""
    note = f"prepared:{output_path.name}"
    if flip_vertical:
        note += "; mirrored-v"
    if force_opaque:
        note += "; opaque-rgb"
    return _local_file_url(output_path), note


def _support_source_image(
    image: QImage,
    *,
    flip_vertical: bool,
    max_dimension: int,
) -> QImage:
    if image.isNull():
        return QImage()
    source = image.convertToFormat(QImage.Format.Format_RGBA8888)
    if source.isNull():
        return QImage()
    limit = max(0, int(max_dimension or 0))
    if limit > 0:
        width = int(source.width())
        height = int(source.height())
        longest = max(width, height)
        if longest > limit:
            target = QSize(width, height).scaled(limit, limit, Qt.KeepAspectRatio)
            if target.width() > 0 and target.height() > 0:
                source = source.scaled(target, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    if flip_vertical:
        source = source.flipped(Qt.Orientation.Vertical)
    return source


def _image_rgba8888_view(image: QImage, width: int, height: int) -> Tuple[Optional[memoryview], int]:
    if image.isNull() or width <= 0 or height <= 0:
        return None, 0
    try:
        stride = int(image.bytesPerLine())
        view = memoryview(image.constBits())
    except (BufferError, TypeError, ValueError, RuntimeError):
        return None, 0
    if stride < width * 4 or len(view) < stride * height:
        return None, 0
    return view, stride


def _image_rgb888_write_view(image: QImage, width: int, height: int) -> Tuple[Optional[memoryview], int]:
    if image.isNull() or width <= 0 or height <= 0:
        return None, 0
    try:
        stride = int(image.bytesPerLine())
        view = memoryview(image.bits())
    except (BufferError, TypeError, ValueError, RuntimeError):
        return None, 0
    if stride < width * 3 or len(view) < stride * height or view.readonly:
        return None, 0
    return view, stride


def _rgba8888_mask_alpha(
    view: memoryview,
    stride: int,
    x: int,
    y: int,
    *,
    channel: str,
) -> float:
    offset = (y * stride) + (x * 4)
    channel_index = _LAYER_CHANNEL_INDEX.get(channel, 0)
    try:
        return _clamp(float(view[offset + channel_index]) / 255.0)
    except (IndexError, TypeError, ValueError):
        return 1.0


def _image_luma_range(image: QImage) -> Tuple[float, float, float]:
    if image.isNull():
        return 0.0, 0.0, 0.0
    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    width = int(converted.width())
    height = int(converted.height())
    if width <= 0 or height <= 0:
        return 0.0, 0.0, 0.0
    values: list[float] = []
    step = max(1, int(math.sqrt(max(1, (width * height) // 8192))))
    for y in range(0, height, step):
        for x in range(0, width, step):
            color = converted.pixelColor(x, y)
            values.append((0.2126 * color.redF()) + (0.7152 * color.greenF()) + (0.0722 * color.blueF()))
    if not values:
        return 0.0, 0.0, 0.0
    values.sort()
    low = values[int((len(values) - 1) * 0.05)]
    high = values[int((len(values) - 1) * 0.95)]
    return low, high, max(0.0, high - low)


def _image_exceeds_dimension(image: QImage, max_dimension: int) -> bool:
    if image.isNull() or max_dimension <= 0:
        return False
    return max(int(image.width()), int(image.height())) > int(max_dimension)


def _decode_mode_for_input(input_item: PreviewMaterialTextureInput) -> str:
    texture_type = str(input_item.semantic_type or "").strip().lower()
    subtype = str(input_item.semantic_subtype or "").strip().lower()
    channels = tuple(str(channel or "").strip().lower() for channel in input_item.packed_channels if str(channel or "").strip())
    parameter_key = _normalized_key(input_item.parameter_name)
    shader_key = _normalized_key(getattr(input_item, "shader_family", ""))
    tokens = _stem_tokens(input_item.source_texture_path, input_item.texture_name)
    last_token = tokens[-1] if tokens else ""
    if _is_visible_color_input(input_item):
        return "visible_color"
    if parameter_key in {"layermasktexture", "layerblendmasktexture"}:
        return "blend_mask"
    if "skinnedmeshskin" in shader_key:
        if parameter_key in {"materialtexture", "skindetailmaterialtexture", "damageblendingmaterialtexture"}:
            return "skin_material"
        if parameter_key in {"skindetailmasktexture", "skindetailopacity"}:
            return "skin_detail_mask"
        if parameter_key == "masktexture":
            return "skin_detail_mask"
    if any(marker in shader_key for marker in ("skinnedmeshanimalhair", "skinnedmeshhairstandard", "skinnedmeshhair", "skinnedmeshfur")):
        if parameter_key in {"materialtexture", "masktexture", "flowtexture"}:
            return "hair_material"
    if any(marker in shader_key for marker in ("skinnedmeshstandardver2", "skinnedmeshemissivever2", "skinnedmeshemissive", "skinnedmeshclothver2", "skinnedmeshcloth")):
        if parameter_key in {"materialtexture", "materialmap"} and last_token in {"sp", "spec", "specular"}:
            return "standard_v2_specular"
        if parameter_key in {"colorblendingmasktexture", "blendingmasktexture"}:
            return "standard_v2_mask"
        if parameter_key in {"detailmasktexture", "detailmask"}:
            return "standard_v2_detail"
        if "grimematerial" in parameter_key or "detailmaterial" in parameter_key or parameter_key == "materialtexture":
            return "standard_v2_material"
        if parameter_key == "masktexture":
            return "standard_v2_mask"
    if "multitextured" in shader_key:
        if parameter_key in {"rgbtexture", "layermasktexture", "layerblendmasktexture"}:
            return "blend_mask"
        if "materialtexture" in parameter_key or "speculartexture" in parameter_key:
            return "static_multitextured_material"
    if "skinnedmeshstandard" in shader_key:
        if parameter_key in {"materialtexture", "materialmap"}:
            return "material_response"
        if parameter_key == "masktexture":
            return "detail_mask"
        if "detailmaterial" in parameter_key or "damageblendingmaterial" in parameter_key:
            return "material_response"
    if parameter_key in {"skindetailmaterialtexture", "damageblendingmaterialtexture"}:
        return "skin_material" if "skin" in shader_key or "skin" in parameter_key else "detail_mask"
    if any(marker in parameter_key for marker in ("grimematerial", "detailmaterial", "detailmask")):
        return "detail_mask"
    if parameter_key in {"materialtexture", "materialmap"} and last_token in {"sp", "spec", "specular"}:
        return "skin_material" if "skin" in shader_key else "material_response"
    if last_token in {"sp", "spec", "specular"}:
        return "specular"
    if last_token in {"rough", "roughness", "gloss", "smooth", "smoothness"}:
        return "roughness"
    if last_token in {"metal", "metallic", "metalness"}:
        return "metallic"
    if last_token in {"ao", "occlusion"}:
        return "ao"
    if last_token == "ma" and subtype not in {"orm", "rma", "mra", "arm"}:
        return "material_mask"
    if last_token == "mg":
        return "detail_mask"
    if subtype in {"opacity", "opacity_mask", "alpha"}:
        return "opacity"
    if subtype in {"metallic_roughness", "gltf_metallic_roughness"} or channels[:2] == ("roughness", "metallic"):
        return "metallic_roughness"
    if channels[:3] == ("ao", "roughness", "metallic"):
        return "orm"
    if channels[:3] == ("roughness", "metallic", "ao"):
        return "rma"
    if channels[:3] == ("metallic", "roughness", "ao"):
        return "mra"
    if len(channels) == 1:
        if channels[0] in {"specular", "spec"}:
            return "specular"
        if channels[0] in {"roughness", "gloss", "smoothness", "gloss_or_smoothness"}:
            return "roughness"
        if channels[0] in {"metallic", "metalness"}:
            return "metallic"
        if channels[0] in {"ao", "ambient_occlusion", "occlusion"}:
            return "ao"
    if subtype == "specular" or texture_type == "specular":
        return "specular"
    if subtype == "ao":
        return "ao"
    if subtype in {"roughness", "gloss_or_smoothness"} or texture_type == "roughness":
        return "roughness"
    if subtype == "metallic" or texture_type == "metallic":
        return "metallic"
    if subtype in {"material_mask", "material_response", "packed_mask"}:
        return subtype
    if subtype in {"orm", "rma", "mra", "arm"}:
        return subtype
    if channels:
        return "packed_mask"
    return "generic"


def _material_decode_output_flags(decode_mode: str) -> Tuple[bool, bool, bool, bool]:
    mode = str(decode_mode or "generic").strip().lower()
    if mode == "visible_color":
        return False, False, False, False
    if mode == "blend_mask":
        return False, False, False, False
    if mode == "ao":
        return True, False, False, False
    if mode == "specular":
        return False, False, False, True
    if mode == "skin_material":
        return False, True, False, True
    if mode == "skin_detail_mask":
        return False, False, False, False
    if mode == "standard_v2_mask":
        return False, False, False, False
    if mode == "standard_v2_material":
        return True, True, True, True
    if mode == "standard_v2_specular":
        return False, True, True, True
    if mode == "standard_v2_detail":
        return False, False, False, False
    if mode == "static_multitextured_material":
        return True, True, True, True
    if mode == "hair_material":
        return False, True, False, True
    if mode == "roughness":
        return False, True, False, True
    if mode == "metallic":
        return False, True, True, True
    if mode == "metallic_roughness":
        return False, True, True, True
    if mode in {"orm", "arm", "rma", "mra", "material_mask", "material_response"}:
        return True, True, True, True
    if mode in {"detail_mask", "packed_mask", "generic"}:
        return False, True, False, True
    return False, True, False, True


def _material_slot_priority(decode_mode: str, slot_name: str) -> int:
    mode = str(decode_mode or "generic").strip().lower()
    slot = str(slot_name or "").strip().lower()
    priorities = {
        "occlusion": {
            "ao": 100,
            "orm": 95,
            "arm": 95,
            "rma": 95,
            "mra": 95,
            "material_mask": 72,
            "material_response": 58,
            "standard_v2_mask": 80,
            "standard_v2_material": 72,
            "static_multitextured_material": 62,
        },
        "roughness": {
            "roughness": 100,
            "metallic_roughness": 98,
            "standard_v2_material": 92,
            "standard_v2_mask": 88,
            "standard_v2_specular": 82,
            "static_multitextured_material": 86,
            "orm": 94,
            "arm": 94,
            "rma": 94,
            "mra": 94,
            "material_mask": 86,
            "material_response": 76,
            "metallic": 66,
            "specular": 42,
            "skin_material": 58,
            "skin_detail_mask": 44,
            "standard_v2_detail": 42,
            "hair_material": 52,
            "packed_mask": 34,
            "detail_mask": 22,
            "generic": 18,
        },
        "metalness": {
            "metallic": 100,
            "metallic_roughness": 98,
            "orm": 96,
            "arm": 96,
            "rma": 96,
            "mra": 96,
            "standard_v2_material": 82,
            "standard_v2_mask": 76,
            "standard_v2_specular": 62,
            "static_multitextured_material": 58,
            "material_mask": 78,
            "material_response": 52,
            "specular": 38,
        },
        "specular": {
            "specular": 100,
            "standard_v2_specular": 96,
            "standard_v2_material": 88,
            "static_multitextured_material": 82,
            "material_response": 82,
            "material_mask": 68,
            "skin_material": 64,
            "skin_detail_mask": 42,
            "standard_v2_mask": 64,
            "standard_v2_detail": 38,
            "hair_material": 58,
            "orm": 50,
            "arm": 50,
            "rma": 50,
            "mra": 50,
            "metallic": 46,
            "metallic_roughness": 54,
            "roughness": 36,
            "packed_mask": 28,
            "detail_mask": 20,
            "generic": 18,
        },
    }
    return int(priorities.get(slot, {}).get(mode, 0))


def _material_parameter_index(input_item: PreviewMaterialTextureInput) -> int:
    key = _parameter_key(input_item)
    source = _normalize_texture_key(
        str(getattr(input_item, "source_texture_path", "") or "")
        or str(getattr(input_item, "texture_name", "") or "")
    )
    best_index = 9999
    for parameter in _material_parameters(input_item):
        parameter_key = _normalized_key(getattr(parameter, "parameter_name", ""))
        if key and parameter_key != key:
            continue
        texture_path = _normalize_texture_key(str(getattr(parameter, "texture_path", "") or ""))
        if source and texture_path and source != texture_path:
            continue
        try:
            index = int(getattr(parameter, "index", -1))
        except (TypeError, ValueError, OverflowError):
            index = -1
        if index >= 0:
            best_index = min(best_index, index)
    return best_index


def _material_slot_priority_for_input(
    input_item: PreviewMaterialTextureInput,
    decode_mode: str,
    slot_name: str,
) -> int:
    priority = _material_slot_priority(decode_mode, slot_name)
    if priority <= 0:
        return priority
    key = _parameter_key(input_item)
    adjustment = 0
    if "grimematerial" in key:
        adjustment += 12
    elif "detailmaterial" in key:
        adjustment += 8
    elif "damage" in key:
        adjustment += 7
    elif "specular" in key:
        adjustment += 5
    elif "materialtexture" in key:
        adjustment += 4
    parameter_index = _material_parameter_index(input_item)
    if parameter_index != 9999:
        adjustment += max(0, 6 - min(6, parameter_index // 24))
    return priority + adjustment


def _material_candidate_group(decode_mode: str) -> str:
    mode = str(decode_mode or "generic").strip().lower()
    if mode == "visible_color":
        return "albedo"
    if mode in {"specular", "standard_v2_specular"}:
        return "specular"
    if mode in {"detail_mask", "skin_detail_mask", "standard_v2_detail", "packed_mask", "generic", "blend_mask"}:
        return "detail"
    return "primary"


def _select_material_candidates_for_payload(
    material_candidates: Sequence[PreviewMaterialTextureInput],
    payload: object,
) -> Tuple[Tuple[PreviewMaterialTextureInput, ...], int]:
    rule = _shader_rule_for_inputs(material_candidates, payload)
    ranked: list[Tuple[str, int, int, PreviewMaterialTextureInput]] = []
    for index, item in enumerate(material_candidates):
        mode = _decode_mode_for_input(item)
        if mode == "opacity":
            ranked.append(("opacity", 0, index, item))
            continue
        score = _material_candidate_match_score(item, payload)
        ranked.append((_material_candidate_group(mode), score, index, item))
    selected: list[PreviewMaterialTextureInput] = []
    selected_ids: set[int] = set()
    if rule in {"standard_v2", "emissive_v2", "cloth_v2", "cloth", "static_multitextured"}:
        group_limits = (
            ("primary", 4, 0),
            ("specular", 2, 0),
            ("detail", 3, 42),
            ("opacity", 2, 0),
        )
    elif rule == "skin":
        group_limits = (
            ("primary", 3, 0),
            ("specular", 1, 0),
            ("detail", 2, 36),
            ("opacity", 2, 0),
        )
    else:
        group_limits = (
            ("primary", 2, 0),
            ("specular", 1, 0),
            ("detail", 1, 74),
            ("opacity", 2, 0),
        )
    for group_name, limit, minimum_score in group_limits:
        group_items = [
            (score, index, item)
            for group, score, index, item in ranked
            if group == group_name and (score >= minimum_score or group_name == "opacity")
        ]
        if not group_items:
            continue
        group_items.sort(key=lambda row: (row[0], -row[1]), reverse=True)
        for _score, index, item in group_items[:limit]:
            if id(item) in selected_ids:
                continue
            selected.append(item)
            selected_ids.add(id(item))
    selected.sort(key=lambda item: next((index for _group, _score, index, candidate in ranked if candidate is item), 0))
    return tuple(selected), max(0, len(material_candidates) - len(selected))


def decode_material_sample(
    red: float,
    green: float,
    blue: float,
    alpha: float,
    decode_mode: str,
) -> Tuple[float, float, float, float]:
    r = _clamp(red)
    g = _clamp(green)
    b = _clamp(blue)
    a = _clamp(alpha)
    average = (r * 0.3333) + (g * 0.3333) + (b * 0.3334)
    peak = max(r, g, b, a)
    minimum = min(r, g, b, a)
    variance = max(peak - minimum, 0.0)
    ao = 1.0
    roughness = 0.58
    metalness = 0.0
    specular = _clamp(0.12 + (variance * 0.24), 0.05, 0.42)
    mode = str(decode_mode or "generic").strip().lower()
    if mode == "specular":
        specular = _clamp(max(r, g, b), 0.06, 1.0)
        roughness = _clamp(1.0 - max(g, average), 0.08, 0.92)
    elif mode == "ao":
        ao = _clamp(r, 0.45, 1.0)
        roughness = 0.74
        specular = 0.08
    elif mode == "roughness":
        roughness = _clamp(max(g, average), 0.06, 0.98)
        specular = _clamp(0.42 - (roughness * 0.28), 0.04, 0.30)
    elif mode == "metallic":
        metalness = _clamp(max(r, average), 0.0, 1.0)
        roughness = _clamp(0.18 + ((1.0 - max(g, average)) * 0.62), 0.08, 0.92)
        specular = _clamp(0.16 + (metalness * 0.48), 0.06, 0.72)
    elif mode == "metallic_roughness":
        roughness = _clamp(g, 0.04, 0.98)
        metalness = _clamp(b, 0.0, 1.0)
        ao = 1.0
        specular = _clamp((0.10 + (metalness * 0.62)) * (1.0 - (roughness * 0.32)), 0.05, 0.78)
    elif mode == "material_mask":
        ao = _clamp(1.0 - (r * 0.30), 0.65, 1.0)
        roughness = _clamp(0.28 + (g * 0.56), 0.10, 0.96)
        specular = _clamp(0.10 + (b * 0.34) + (a * 0.10), 0.05, 0.46)
        metalness = _clamp(b * 0.28, 0.0, 0.55)
    elif mode == "material_response":
        ao = _clamp(1.0 - (r * 0.20), 0.70, 1.0)
        roughness = _clamp(0.16 + ((1.0 - g) * 0.72), 0.08, 0.96)
        specular = _clamp(0.12 + (max(b, a) * 0.42), 0.05, 0.62)
        metalness = _clamp((b * 0.24) + (a * 0.16), 0.0, 0.58)
    elif mode == "skin_material":
        roughness = _clamp(0.34 + ((1.0 - max(g, average)) * 0.42), 0.24, 0.92)
        specular = _clamp(0.06 + (max(b, average) * 0.24), 0.04, 0.34)
        metalness = 0.0
    elif mode == "skin_detail_mask":
        ao = _clamp(1.0 - (r * 0.08), 0.86, 1.0)
        roughness = _clamp(0.46 + (average * 0.28), 0.32, 0.88)
        specular = _clamp(0.05 + (variance * 0.16), 0.03, 0.24)
        metalness = 0.0
    elif mode == "hair_material":
        roughness = _clamp(0.22 + ((1.0 - average) * 0.52), 0.12, 0.88)
        specular = _clamp(0.10 + (max(b, a) * 0.34) + (variance * 0.16), 0.05, 0.54)
        metalness = 0.0
    elif mode == "standard_v2_specular":
        specular = _clamp(max(r, g, b, a), 0.08, 1.0)
        roughness = _clamp(0.16 + ((1.0 - max(g, average)) * 0.62), 0.06, 0.92)
        metalness = 0.0
    elif mode == "standard_v2_mask":
        ao = _clamp(1.0 - (r * 0.16), 0.72, 1.0)
        roughness = _clamp(0.22 + (g * 0.62), 0.08, 0.96)
        metalness = _clamp(max(0.0, b - (r * 0.20)) * 0.46, 0.0, 0.64)
        specular = _clamp(0.10 + (a * 0.38) + (b * 0.16) + (variance * 0.12), 0.05, 0.62)
    elif mode == "standard_v2_material":
        ao = _clamp(1.0 - (r * 0.22), 0.68, 1.0)
        roughness = _clamp(0.18 + (g * 0.68), 0.06, 0.96)
        metalness = _clamp(max(0.0, b - (r * 0.12)) * 0.58, 0.0, 0.78)
        specular = _clamp(0.12 + (a * 0.52) + (b * 0.22) + (variance * 0.10), 0.05, 0.78)
    elif mode == "standard_v2_detail":
        ao = _clamp(1.0 - (r * 0.10), 0.80, 1.0)
        roughness = _clamp(0.28 + (average * 0.52), 0.10, 0.96)
        metalness = _clamp(max(0.0, b - r) * 0.32, 0.0, 0.44)
        specular = _clamp(0.08 + (variance * 0.36) + (a * 0.20), 0.04, 0.50)
    elif mode == "static_multitextured_material":
        ao = _clamp(1.0 - (r * 0.18), 0.70, 1.0)
        roughness = _clamp(0.18 + ((1.0 - g) * 0.62), 0.08, 0.96)
        metalness = _clamp(max(0.0, b - 0.28) * 0.42, 0.0, 0.46)
        specular = _clamp(0.10 + (max(b, a) * 0.34) + (variance * 0.10), 0.05, 0.58)
    elif mode in {"packed_mask", "detail_mask"}:
        ao = _clamp(1.0 - (r * 0.18), 0.78, 1.0)
        roughness = _clamp(0.24 + (g * 0.56), 0.10, 0.96)
        specular = _clamp(0.10 + (b * 0.26) + (a * 0.12), 0.04, 0.44)
        metalness = _clamp(b * 0.18, 0.0, 0.35)
    elif mode in {"orm", "arm"}:
        ao = _clamp(r, 0.45, 1.0)
        roughness = _clamp(g, 0.05, 0.98)
        metalness = _clamp(b, 0.0, 1.0)
        specular = _clamp((0.10 + (metalness * 0.54)) * (1.0 - (roughness * 0.38)), 0.05, 0.72)
    elif mode == "rma":
        roughness = _clamp(r, 0.05, 0.98)
        metalness = _clamp(g, 0.0, 1.0)
        ao = _clamp(b, 0.45, 1.0)
        specular = _clamp((0.10 + (metalness * 0.54)) * (1.0 - (roughness * 0.38)), 0.05, 0.72)
    elif mode == "mra":
        metalness = _clamp(r, 0.0, 1.0)
        roughness = _clamp(g, 0.05, 0.98)
        ao = _clamp(b, 0.45, 1.0)
        specular = _clamp((0.10 + (metalness * 0.54)) * (1.0 - (roughness * 0.38)), 0.05, 0.72)
    else:
        ao = _clamp(1.0 - (r * 0.16), 0.82, 1.0)
        roughness = _clamp(0.22 + (g * 0.54), 0.10, 0.96)
        metalness = _clamp(max(0.0, b - (r * 0.30)) * 0.42, 0.0, 0.55)
        specular = _clamp(0.10 + (b * 0.22) + (a * 0.18) + (variance * 0.12), 0.04, 0.55)
    return _clamp(ao, 0.45, 1.0), _clamp(roughness, 0.04, 1.0), _clamp(metalness), _clamp(specular)


def _generate_material_maps(
    image: QImage,
    output_dir: Path,
    stem: str,
    *,
    decode_mode: str,
    input_item: Optional[PreviewMaterialTextureInput] = None,
    layer_mask: Optional[QImage] = None,
    layer_mask_channel: str = "",
    layer_weight: float = 1.0,
    flip_vertical: bool,
    max_dimension: int,
) -> Tuple[Tuple[str, ...], Tuple[str, str, str, str]]:
    if image.isNull():
        return (), ("", "", "", "")
    source = _support_source_image(image, flip_vertical=flip_vertical, max_dimension=max_dimension)
    if source.isNull():
        return (), ("", "", "", "")
    width = int(source.width())
    height = int(source.height())
    if width <= 0 or height <= 0:
        return (), ("", "", "", "")
    source_view, source_stride = _image_rgba8888_view(source, width, height)
    if source_view is None:
        return (), ("", "", "", "")
    mask_source = QImage()
    if layer_mask is not None and not layer_mask.isNull():
        mask_source = _support_source_image(layer_mask, flip_vertical=flip_vertical, max_dimension=max_dimension)
        if not mask_source.isNull() and (int(mask_source.width()) != width or int(mask_source.height()) != height):
            mask_source = mask_source.scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        if not mask_source.isNull():
            mask_source = mask_source.convertToFormat(QImage.Format.Format_RGBA8888)
    mask_view: Optional[memoryview] = None
    mask_stride = 0
    if not mask_source.isNull():
        mask_view, mask_stride = _image_rgba8888_view(mask_source, width, height)
        if mask_view is None:
            mask_source = QImage()
            mask_stride = 0
    mask_channel = str(layer_mask_channel or "r").strip().lower()
    effective_layer_weight = _clamp(layer_weight, 0.0, 1.0)
    if not mask_source.isNull() and effective_layer_weight <= 0.001:
        return (), ("", "", "", "")
    emit_occlusion, emit_roughness, emit_metalness, emit_specular = _material_decode_output_flags(decode_mode)
    ao_image = QImage(width, height, QImage.Format.Format_RGB888) if emit_occlusion else QImage()
    rough_image = QImage(width, height, QImage.Format.Format_RGB888) if emit_roughness else QImage()
    metal_image = QImage(width, height, QImage.Format.Format_RGB888) if emit_metalness else QImage()
    spec_image = QImage(width, height, QImage.Format.Format_RGB888) if emit_specular else QImage()
    ao_view, ao_stride = _image_rgb888_write_view(ao_image, width, height) if emit_occlusion else (None, 0)
    rough_view, rough_stride = _image_rgb888_write_view(rough_image, width, height) if emit_roughness else (None, 0)
    metal_view, metal_stride = _image_rgb888_write_view(metal_image, width, height) if emit_metalness else (None, 0)
    spec_view, spec_stride = _image_rgb888_write_view(spec_image, width, height) if emit_specular else (None, 0)
    if (
        (emit_occlusion and ao_view is None)
        or (emit_roughness and rough_view is None)
        or (emit_metalness and metal_view is None)
        or (emit_specular and spec_view is None)
    ):
        return (), ("", "", "", "")
    mode = str(decode_mode or "").strip().lower()
    shader_rule = _texture_rule_for_input(input_item) if input_item is not None else ""
    force_nonmetal_skin = bool(shader_rule == "skin" or mode in {"skin_material", "skin_detail_mask"})
    apply_sidecar_hints = bool(
        input_item is not None
        and not force_nonmetal_skin
        and shader_rule in {"standard_v2", "emissive_v2", "cloth_v2", "cloth", "standard", "static_multitextured", "static_standard"}
    )
    metallic_hint = 0.0
    roughness_hint = 0.0
    specular_hint = 0.0
    if apply_sidecar_hints and input_item is not None:
        channel = _layer_channel(input_item)
        metallic_hint = _material_parameter_channel_hint(input_item, channel, "metallic", "metalness", "scratchmetallic")
        roughness_hint = _material_parameter_channel_hint(input_item, channel, "roughness", "scratchroughness")
        specular_hint = _material_parameter_hint(input_item, "specular", "specularamount")
    metal_peak = 0.0
    spec_peak = 0.0
    contribution_peak = 1.0 if mask_source.isNull() else 0.0
    for y in range(height):
        source_row = y * source_stride
        for x in range(width):
            source_offset = source_row + (x * 4)
            ao, roughness, metalness, specular = decode_material_sample(
                float(source_view[source_offset]) / 255.0,
                float(source_view[source_offset + 1]) / 255.0,
                float(source_view[source_offset + 2]) / 255.0,
                float(source_view[source_offset + 3]) / 255.0,
                decode_mode,
            )
            if force_nonmetal_skin:
                metalness = 0.0
                specular = min(specular, 0.42)
            elif apply_sidecar_hints:
                if metallic_hint > 0.02:
                    metalness = max(metalness, metallic_hint * 0.42)
                    specular = max(specular, 0.14 + metallic_hint * 0.32)
                if roughness_hint > 0.02:
                    roughness = _clamp((roughness * 0.72) + (roughness_hint * 0.28), 0.04, 0.98)
                if specular_hint > 0.02:
                    specular = max(specular, specular_hint * 0.58)
                ao = _clamp(ao, 0.45, 1.0)
                roughness = _clamp(roughness, 0.04, 1.0)
                metalness = _clamp(metalness)
                specular = _clamp(specular)
            if mask_view is not None:
                layer_alpha = _clamp(
                    _rgba8888_mask_alpha(mask_view, mask_stride, x, y, channel=mask_channel)
                    * effective_layer_weight
                )
                contribution_peak = max(contribution_peak, layer_alpha)
                ao = (1.0 * (1.0 - layer_alpha)) + (ao * layer_alpha)
                roughness = (0.58 * (1.0 - layer_alpha)) + (roughness * layer_alpha)
                metalness *= layer_alpha
                specular *= layer_alpha
            metal_peak = max(metal_peak, metalness)
            spec_peak = max(spec_peak, specular)
            if emit_occlusion:
                ao_g = _byte(ao)
                offset = (y * ao_stride) + (x * 3)
                ao_view[offset : offset + 3] = bytes((ao_g, ao_g, ao_g))
            if emit_roughness:
                rough_g = _byte(roughness)
                offset = (y * rough_stride) + (x * 3)
                rough_view[offset : offset + 3] = bytes((rough_g, rough_g, rough_g))
            if emit_metalness:
                metal_g = _byte(metalness)
                offset = (y * metal_stride) + (x * 3)
                metal_view[offset : offset + 3] = bytes((metal_g, metal_g, metal_g))
            if emit_specular:
                spec_g = _byte(specular)
                offset = (y * spec_stride) + (x * 3)
                spec_view[offset : offset + 3] = bytes((spec_g, spec_g, spec_g))
    if contribution_peak <= 0.015:
        return (), ("", "", "", "")
    del source_view
    if mask_view is not None:
        del mask_view
    if ao_view is not None:
        del ao_view
    if rough_view is not None:
        del rough_view
    if metal_view is not None:
        del metal_view
    if spec_view is not None:
        del spec_view
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    slots: list[str] = []
    for slot, generated in (
        ("occlusion", ao_image),
        ("roughness", rough_image),
        ("metalness", metal_image),
        ("specular", spec_image),
    ):
        if generated.isNull():
            paths.append("")
            continue
        if slot == "metalness" and metal_peak <= 0.015:
            paths.append("")
            continue
        if slot == "specular" and spec_peak <= 0.015:
            paths.append("")
            continue
        output_path = output_dir / f"{stem}_{slot}.png"
        if generated.save(str(output_path), "PNG"):
            slots.append(slot)
            paths.append(_local_file_url(output_path))
        else:
            paths.append("")
    while len(paths) < 4:
        paths.append("")
    return tuple(slots), tuple(paths[:4])  # type: ignore[return-value]


def _read_generated_map(source_url: str) -> QImage:
    return _image_reader(source_url).convertToFormat(QImage.Format.Format_RGBA8888)


def _combine_material_slot_maps(
    slot_name: str,
    layers: Sequence[Tuple[int, str, str]],
    output_dir: Path,
    stem: str,
) -> Tuple[str, str]:
    valid_layers: list[Tuple[int, str, str, QImage]] = []
    for priority, mode, source_url in layers:
        image = _read_generated_map(source_url)
        if image.isNull():
            continue
        valid_layers.append((int(priority), str(mode or "generic"), str(source_url or ""), image))
    if not valid_layers:
        return "", ""
    valid_layers.sort(key=lambda item: item[0], reverse=True)
    if len(valid_layers) == 1:
        return valid_layers[0][2], valid_layers[0][1]

    base_width = int(valid_layers[0][3].width())
    base_height = int(valid_layers[0][3].height())
    if base_width <= 0 or base_height <= 0:
        return "", ""
    normalized_layers: list[Tuple[int, str, QImage]] = []
    for priority, mode, _source_url, image in valid_layers:
        source = image
        if int(source.width()) != base_width or int(source.height()) != base_height:
            source = source.scaled(base_width, base_height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        converted = source.convertToFormat(QImage.Format.Format_RGBA8888)
        if not converted.isNull():
            normalized_layers.append((priority, mode, converted))

    slot = str(slot_name or "").strip().lower()
    target = QImage(base_width, base_height, QImage.Format.Format_RGB888)
    target_view, target_stride = _image_rgb888_write_view(target, base_width, base_height)
    if target_view is None:
        return valid_layers[0][2], valid_layers[0][1]
    layer_views: list[Tuple[int, str, QImage, memoryview, int]] = []
    for priority, mode, image in normalized_layers:
        view, stride = _image_rgba8888_view(image, base_width, base_height)
        if view is not None:
            layer_views.append((priority, mode, image, view, stride))
    if not layer_views:
        return valid_layers[0][2], valid_layers[0][1]
    weight_total = max(1.0, sum(max(1.0, float(priority)) for priority, _mode, _image, _view, _stride in layer_views))
    for y in range(base_height):
        target_row = y * target_stride
        for x in range(base_width):
            values: list[Tuple[float, float]] = []
            for priority, _mode, _image, view, stride in layer_views:
                offset = (y * stride) + (x * 4)
                grey = (
                    (0.2126 * (float(view[offset]) / 255.0))
                    + (0.7152 * (float(view[offset + 1]) / 255.0))
                    + (0.0722 * (float(view[offset + 2]) / 255.0))
                )
                values.append((_clamp(grey), max(1.0, float(priority))))
            if slot == "occlusion":
                combined = 1.0
                for value, _weight in values:
                    combined = min(combined, value)
                combined = _clamp(combined, 0.55, 1.0)
            elif slot == "metalness":
                combined = max(
                    value * _clamp(0.45 + ((weight / 100.0) * 0.55), 0.45, 1.0)
                    for value, weight in values
                )
            elif slot == "specular":
                weighted = sum(value * weight for value, weight in values) / weight_total
                peak = max(value for value, _weight in values)
                combined = _clamp((weighted * 0.35) + (peak * 0.65), 0.0, 1.0)
            else:
                combined = sum(value * weight for value, weight in values) / weight_total
            grey_byte = _byte(combined)
            target_offset = target_row + (x * 3)
            target_view[target_offset : target_offset + 3] = bytes((grey_byte, grey_byte, grey_byte))

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{stem}_{slot}.png"
    del target_view
    del layer_views
    if not target.save(str(output_path), "PNG"):
        return valid_layers[0][2], valid_layers[0][1]
    return _local_file_url(output_path), "+".join(dict.fromkeys(mode for _priority, mode, _image in normalized_layers))


def _generate_legacy_pbr_response_map(
    output_dir: Path,
    stem: str,
    *,
    occlusion_source: str = "",
    roughness_source: str = "",
    metalness_source: str = "",
    specular_source: str = "",
) -> str:
    source_urls = [occlusion_source, roughness_source, metalness_source, specular_source]
    source_images = [_read_generated_map(source_url) if source_url else QImage() for source_url in source_urls]
    valid = [image for image in source_images if not image.isNull()]
    if not valid:
        return ""
    width = int(valid[0].width())
    height = int(valid[0].height())
    if width <= 0 or height <= 0:
        return ""

    normalized: list[QImage] = []
    for image in source_images:
        if image.isNull():
            normalized.append(QImage())
            continue
        source = image
        if int(source.width()) != width or int(source.height()) != height:
            source = source.scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        normalized.append(source.convertToFormat(QImage.Format.Format_RGBA8888))

    target = QImage(width, height, QImage.Format.Format_RGBA8888)
    for y in range(height):
        for x in range(width):
            values: list[int] = []
            for index, image in enumerate(normalized):
                if image.isNull():
                    if index == 0:
                        values.append(255)
                    elif index == 1:
                        values.append(148)
                    else:
                        values.append(0)
                    continue
                color = image.pixelColor(x, y)
                luma = (0.2126 * color.redF()) + (0.7152 * color.greenF()) + (0.0722 * color.blueF())
                values.append(_byte(luma))
            ao, roughness, metalness, specular = (values + [255, 148, 0, 0])[:4]
            target.setPixelColor(x, y, QColor(ao, roughness, metalness, specular))

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{stem}_legacy_pbr.png"
    if not target.save(str(output_path), "PNG"):
        return ""
    return _local_file_url(output_path)


def _generate_normal_map(
    image: QImage,
    output_dir: Path,
    stem: str,
    *,
    flip_vertical: bool,
    max_dimension: int,
) -> Tuple[str, float]:
    if image.isNull():
        return "", 0.0
    source = _support_source_image(image, flip_vertical=flip_vertical, max_dimension=max_dimension)
    if source.isNull():
        return "", 0.0
    width = int(source.width())
    height = int(source.height())
    if width <= 0 or height <= 0:
        return "", 0.0
    strength_total = 0.0
    sample_count = 0
    target = QImage(width, height, QImage.Format.Format_RGBA8888)
    for y in range(height):
        for x in range(width):
            color = source.pixelColor(x, y)
            red = color.red()
            green = 255 - color.green()
            blue = color.blue()
            target.setPixelColor(x, y, QColor(red, green, blue, 255))
            nx = (float(red) / 255.0) * 2.0 - 1.0
            ny = (float(green) / 255.0) * 2.0 - 1.0
            strength_total += min(1.0, math.sqrt((nx * nx) + (ny * ny)))
            sample_count += 1
    average_strength = strength_total / float(max(1, sample_count))
    if average_strength <= 0.012:
        return "", 0.0
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{stem}_normal.png"
    if not target.save(str(output_path), "PNG"):
        return "", 0.0
    return _local_file_url(output_path), average_strength


def _generate_height_map(
    image: QImage,
    output_dir: Path,
    stem: str,
    *,
    flip_vertical: bool,
    max_dimension: int,
) -> Tuple[str, float]:
    source = _support_source_image(image, flip_vertical=flip_vertical, max_dimension=max_dimension)
    if source.isNull():
        return "", 0.0
    low, high, contrast = _image_luma_range(source)
    if contrast < 0.010:
        return "", contrast
    width = int(source.width())
    height = int(source.height())
    target = QImage(width, height, QImage.Format.Format_RGB888)
    range_value = max(high - low, 0.001)
    gain = min(4.0, max(1.0, 0.24 / max(contrast, 0.018)))
    for y in range(height):
        for x in range(width):
            color = source.pixelColor(x, y)
            luma = (0.2126 * color.redF()) + (0.7152 * color.greenF()) + (0.0722 * color.blueF())
            normalized = _clamp((luma - low) / range_value)
            adjusted = _clamp(0.5 + ((normalized - 0.5) * gain))
            grey = _byte(adjusted)
            target.setPixelColor(x, y, QColor(grey, grey, grey))
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{stem}_height.png"
    if not target.save(str(output_path), "PNG"):
        return "", contrast
    return _local_file_url(output_path), contrast


def _derive_normal_from_height(
    image: QImage,
    output_dir: Path,
    stem: str,
    *,
    flip_vertical: bool,
    max_dimension: int,
) -> Tuple[str, float]:
    source = _support_source_image(image, flip_vertical=flip_vertical, max_dimension=max_dimension)
    if source.isNull():
        return "", 0.0
    low, high, contrast = _image_luma_range(source)
    if contrast < 0.018:
        return "", contrast
    width = int(source.width())
    height = int(source.height())
    if width <= 1 or height <= 1:
        return "", contrast
    luma_grid: list[list[float]] = []
    for y in range(height):
        row: list[float] = []
        for x in range(width):
            color = source.pixelColor(x, y)
            row.append((0.2126 * color.redF()) + (0.7152 * color.greenF()) + (0.0722 * color.blueF()))
        luma_grid.append(row)
    target = QImage(width, height, QImage.Format.Format_RGBA8888)
    range_value = max(high - low, 0.001)
    scale = min(2.5, max(0.65, 0.08 / max(contrast, 0.018)))
    for y in range(height):
        ym = max(0, y - 1)
        yp = min(height - 1, y + 1)
        for x in range(width):
            xm = max(0, x - 1)
            xp = min(width - 1, x + 1)
            dx = ((luma_grid[y][xp] - luma_grid[y][xm]) / range_value) * scale
            dy = ((luma_grid[yp][x] - luma_grid[ym][x]) / range_value) * scale
            nx = -dx
            ny = -dy
            nz = 1.0
            length = max(0.001, math.sqrt((nx * nx) + (ny * ny) + (nz * nz)))
            red = _byte((nx / length) * 0.5 + 0.5)
            green = _byte((ny / length) * 0.5 + 0.5)
            blue = _byte((nz / length) * 0.5 + 0.5)
            target.setPixelColor(x, y, QColor(red, green, blue, 255))
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{stem}_normal_from_height.png"
    if not target.save(str(output_path), "PNG"):
        return "", contrast
    return _local_file_url(output_path), contrast


def synthesize_material_texture_inputs(batch: object) -> Tuple[PreviewMaterialTextureInput, ...]:
    explicit = tuple(getattr(batch, "preview_material_texture_inputs", ()) or ())
    if explicit:
        return explicit
    material_name = str(getattr(batch, "material_name", "") or "").strip()
    texture_name = str(getattr(batch, "texture_name", "") or "").strip()
    inputs: list[PreviewMaterialTextureInput] = []
    base_path = str(getattr(batch, "preview_texture_path", "") or "").strip()
    if base_path:
        inputs.append(
            PreviewMaterialTextureInput(
                slot_kind="base",
                texture_name=texture_name,
                preview_texture_path=base_path,
                source_texture_path=texture_name or base_path,
                source_dds_path=str(getattr(batch, "preview_texture_dds_path", "") or ""),
                semantic_type="color",
                semantic_subtype="albedo",
                material_name=material_name,
                confidence="legacy",
                visualized=True,
            )
        )
    normal_path = str(getattr(batch, "preview_normal_texture_path", "") or "").strip()
    if normal_path:
        inputs.append(
            PreviewMaterialTextureInput(
                slot_kind="normal",
                texture_name=str(getattr(batch, "preview_normal_texture_name", "") or "") or normal_path,
                preview_texture_path=normal_path,
                source_texture_path=str(getattr(batch, "preview_normal_texture_name", "") or "") or normal_path,
                source_dds_path=str(getattr(batch, "preview_normal_texture_dds_path", "") or ""),
                semantic_type="normal",
                semantic_subtype="normal",
                material_name=material_name,
                confidence="legacy",
                visualized=True,
            )
        )
    material_path = str(getattr(batch, "preview_material_texture_path", "") or "").strip()
    if material_path:
        inputs.append(
            PreviewMaterialTextureInput(
                slot_kind="material",
                texture_name=str(getattr(batch, "preview_material_texture_name", "") or "") or material_path,
                preview_texture_path=material_path,
                source_texture_path=str(getattr(batch, "preview_material_texture_name", "") or "") or material_path,
                source_dds_path=str(getattr(batch, "preview_material_texture_dds_path", "") or ""),
                semantic_type=str(getattr(batch, "preview_material_texture_type", "") or "material").strip().lower(),
                semantic_subtype=str(getattr(batch, "preview_material_texture_subtype", "") or "").strip().lower(),
                packed_channels=tuple(getattr(batch, "preview_material_texture_packed_channels", ()) or ()),
                material_name=material_name,
                confidence="legacy",
                visualized=True,
            )
        )
    height_path = str(getattr(batch, "preview_height_texture_path", "") or "").strip()
    if height_path:
        inputs.append(
            PreviewMaterialTextureInput(
                slot_kind="height",
                texture_name=str(getattr(batch, "preview_height_texture_name", "") or "") or height_path,
                preview_texture_path=height_path,
                source_texture_path=str(getattr(batch, "preview_height_texture_name", "") or "") or height_path,
                source_dds_path=str(getattr(batch, "preview_height_texture_dds_path", "") or ""),
                semantic_type="height",
                semantic_subtype="displacement",
                material_name=material_name,
                confidence="legacy",
                visualized=True,
            )
        )
    return tuple(inputs)


def combine_preview_material(
    payload: object,
    output_dir: Path,
    batch_index: int,
    *,
    settings: MaterialPreviewCombinerSettings,
) -> MaterialPreviewCombinerResult:
    notes: list[str] = []
    outputs: list[str] = []
    decode_modes: list[str] = []
    flip_vertical = bool(getattr(payload, "texture_flip_vertical", False))
    inputs = tuple(getattr(payload, "material_texture_inputs", ()) or ())
    shader_rule = _shader_rule_for_inputs(inputs, payload)
    shader_families = tuple(
        dict.fromkeys(
            str(getattr(item, "shader_family", "") or "").strip()
            for item in inputs
            if str(getattr(item, "shader_family", "") or "").strip()
        )
    )
    if shader_rule != "generic":
        notes.append(f"shader rule:{shader_rule}")
        registry_note = _SHADER_RULE_PARAMETER_NOTES.get(shader_rule, "")
        if registry_note:
            notes.append(registry_note)
    if shader_families:
        notes.append("shader family:" + ",".join(shader_families[:3]))
    parameter_count = sum(_material_parameter_count(item) for item in inputs)
    if parameter_count > 0:
        notes.append(f"sidecar parameters:{parameter_count}")
    support_map_max_dimension = max(96, min(256, int(settings.support_map_max_dimension or 256)))
    base_map_max_dimension = max(512, min(1024, support_map_max_dimension * 4))

    base_source = ""
    base_note = ""
    selected_base_item: Optional[PreviewMaterialTextureInput] = None
    selected_base_image = QImage()
    selected_base_low_authority = False
    base_candidates = [item for item in inputs if str(item.slot_kind or "").strip().lower() in {"base", "color", "emissive"}]
    for item in base_candidates:
        if _looks_like_technical_base(item):
            notes.append(f"technical base rejected:{_texture_label(item.source_texture_path, item.texture_name)}")
            continue
        if not _looks_like_visible_base(item):
            notes.append(f"non-color base rejected:{_texture_label(item.source_texture_path, item.texture_name)}")
            continue
        image = _image_reader(str(item.preview_texture_path or ""), max_dimension=base_map_max_dimension)
        if image.isNull():
            notes.append(f"base unreadable:{_texture_label(item.preview_texture_path, item.texture_name)}")
            continue
        if _image_exceeds_dimension(image, base_map_max_dimension):
            notes.append(f"base maps capped:{base_map_max_dimension}px")
        selected_base_item = item
        selected_base_image = image
        selected_base_low_authority = _is_low_authority_base(item)
        base_source, base_note = _prepare_image(
            image,
            output_dir,
            f"batch_{batch_index:03d}_base",
            flip_vertical=flip_vertical,
            force_opaque=True,
            max_dimension=base_map_max_dimension,
        )
        if base_source:
            outputs.append("albedo")
            break

    visible_layer_inputs = _select_visible_layer_inputs(inputs, selected_base=selected_base_item)
    force_layer_synthesis = bool(
        shader_rule == "static_multitextured"
        and any(_visible_layer_role(item) == "layer" for item in visible_layer_inputs)
    )
    should_synthesize_albedo = bool(visible_layer_inputs and (not base_source or selected_base_low_authority or force_layer_synthesis))
    if should_synthesize_albedo:
        synthesized_source, synthesized_note = _generate_synthesized_albedo_map(
            selected_base_image,
            visible_layer_inputs,
            _mask_inputs_for_albedo(inputs),
            output_dir,
            f"batch_{batch_index:03d}",
            flip_vertical=flip_vertical,
            max_dimension=min(base_map_max_dimension, 512),
        )
        if synthesized_source:
            base_source = synthesized_source
            base_note = synthesized_note
            if "albedo" not in outputs:
                outputs.append("albedo")
            notes.append(synthesized_note)
        elif not base_source:
            notes.append("albedo synthesis failed")
    if not base_source and base_candidates:
        notes.append("no reliable base DDS")

    normal_source = ""
    normal_strength = 0.0
    tangents_usable = bool(getattr(payload, "tangents_usable", False))
    normal_candidates = [item for item in inputs if str(item.slot_kind or "").strip().lower() == "normal"]
    if normal_candidates and not tangents_usable:
        notes.append("missing tangents")
    if tangents_usable:
        for item in normal_candidates:
            image = _image_reader(str(item.preview_texture_path or ""), max_dimension=support_map_max_dimension)
            if image.isNull():
                notes.append(f"normal unreadable:{_texture_label(item.preview_texture_path, item.texture_name)}")
                continue
            if _image_exceeds_dimension(image, support_map_max_dimension):
                notes.append(f"support maps capped:{support_map_max_dimension}px")
            normal_source, normal_average_strength = _generate_normal_map(
                image,
                output_dir,
                f"batch_{batch_index:03d}",
                flip_vertical=flip_vertical,
                max_dimension=support_map_max_dimension,
            )
            if normal_source:
                configured_strength = _finite_float(getattr(payload, "normal_texture_strength", 0.0), 0.0)
                if configured_strength <= 0.0:
                    configured_strength = max(settings.normal_strength_floor, normal_average_strength)
                normal_strength = _clamp(configured_strength, settings.normal_strength_floor, settings.normal_strength_cap)
                outputs.append("normal")
                notes.append("normal green inverted")
                break

    occlusion_source = ""
    roughness_source = ""
    metalness_source = ""
    specular_source = ""
    material_slot_priorities = {
        "occlusion": -1,
        "roughness": -1,
        "metalness": -1,
        "specular": -1,
    }
    material_slot_modes: dict[str, str] = {}
    material_slot_layers: dict[str, list[Tuple[int, str, str]]] = {
        "occlusion": [],
        "roughness": [],
        "metalness": [],
        "specular": [],
    }
    raw_material_candidates = [
        item
        for item in inputs
        if str(item.slot_kind or "").strip().lower() in {"material", "material_mask", "detail_mask"}
        and not _is_visible_color_input(item)
    ]
    material_candidates, culled_material_count = _select_material_candidates_for_payload(raw_material_candidates, payload)
    if culled_material_count > 0:
        notes.append(f"material inputs culled:{len(raw_material_candidates)}->{len(material_candidates)}")
    material_candidate_decode_modes = tuple(_decode_mode_for_input(candidate) for candidate in material_candidates)
    suppress_standard_v2_specular_metalness = any(
        mode in {"standard_v2_mask", "standard_v2_material"}
        for mode in material_candidate_decode_modes
    )
    for material_index, item in enumerate(material_candidates):
        mode = material_candidate_decode_modes[material_index] if material_index < len(material_candidate_decode_modes) else _decode_mode_for_input(item)
        if mode == "opacity":
            notes.append(f"opacity ignored:{_texture_label(item.source_texture_path, item.texture_name)}")
            continue
        image = _image_reader(str(item.preview_texture_path or ""), max_dimension=support_map_max_dimension)
        if image.isNull():
            notes.append(f"material unreadable:{_texture_label(item.preview_texture_path, item.texture_name)}")
            continue
        if _image_exceeds_dimension(image, support_map_max_dimension):
            notes.append(f"support maps capped:{support_map_max_dimension}px")
        decode_modes.append(mode)
        hint_labels: list[str] = []
        if any(_material_decode_output_flags(mode)):
            channel = _layer_channel(item)
            if _material_parameter_channel_hint(item, channel, "metallic", "metalness", "scratchmetallic") > 0.02:
                hint_labels.append("metallic")
            if _material_parameter_channel_hint(item, channel, "roughness", "scratchroughness") > 0.02:
                hint_labels.append("roughness")
            if _material_parameter_hint(item, "specular", "specularamount") > 0.02:
                hint_labels.append("specular")
        if hint_labels:
            notes.append(f"sidecar material hints:{'+'.join(dict.fromkeys(hint_labels))}")
        layer_mask_image = QImage()
        layer_mask_channel = ""
        layer_weight = 1.0
        mask_item, mask_channel, mask_label = _material_layer_mask_for_input(item, inputs)
        if mask_item is not None:
            layer_mask_channel = mask_channel or "r"
            layer_weight = _layer_weight_from_parameters(item, has_base=bool(base_source))
            if layer_weight <= 0.001:
                notes.append(f"material layer disabled by colorBlendingFlag:{mask_label}")
            layer_mask_image = _image_reader(
                str(getattr(mask_item, "preview_texture_path", "") or ""),
                max_dimension=support_map_max_dimension,
            )
            if layer_mask_image.isNull():
                notes.append(f"material layer mask unreadable:{mask_label}")
            else:
                notes.append(f"material layer mask applied:{mask_label}")
        generated_slots, generated_paths = _generate_material_maps(
            image,
            output_dir,
            f"batch_{batch_index:03d}_{material_index:02d}_{mode}",
            decode_mode=mode,
            input_item=item,
            layer_mask=layer_mask_image if not layer_mask_image.isNull() else None,
            layer_mask_channel=layer_mask_channel,
            layer_weight=layer_weight,
            flip_vertical=flip_vertical,
            max_dimension=support_map_max_dimension,
        )
        if generated_slots:
            source_by_slot = {
                "occlusion": generated_paths[0],
                "roughness": generated_paths[1],
                "metalness": generated_paths[2],
                "specular": generated_paths[3],
            }
            if mode == "standard_v2_specular" and suppress_standard_v2_specular_metalness:
                generated_slots = tuple(slot for slot in generated_slots if slot != "metalness")
                source_by_slot["metalness"] = ""
            for slot_name in generated_slots:
                slot_source = source_by_slot.get(slot_name, "")
                if not slot_source:
                    continue
                priority = _material_slot_priority_for_input(item, mode, slot_name)
                if priority <= material_slot_priorities.get(slot_name, -1):
                    material_slot_layers.setdefault(slot_name, []).append((priority, mode, slot_source))
                else:
                    material_slot_priorities[slot_name] = priority
                    material_slot_modes[slot_name] = mode
                    material_slot_layers.setdefault(slot_name, []).append((priority, mode, slot_source))
            outputs.extend(slot for slot in generated_slots if slot not in outputs)

    if any(material_slot_layers.values()) and shader_rule in {"standard_v2", "emissive_v2", "cloth_v2", "cloth"}:
        notes.append("material blend order: sidecar parameter order + grime/detail channel masks")

    blended_slots: list[str] = []
    for slot_name in ("occlusion", "roughness", "metalness", "specular"):
        layers = material_slot_layers.get(slot_name, [])
        if not layers:
            continue
        combined_source, combined_mode = _combine_material_slot_maps(
            slot_name,
            layers,
            output_dir,
            f"batch_{batch_index:03d}_combined",
        )
        if not combined_source:
            continue
        if slot_name == "occlusion":
            occlusion_source = combined_source
        elif slot_name == "roughness":
            roughness_source = combined_source
        elif slot_name == "metalness":
            metalness_source = combined_source
        elif slot_name == "specular":
            specular_source = combined_source
        if combined_mode:
            material_slot_modes[slot_name] = combined_mode
        if len(layers) > 1:
            blended_slots.append(f"{slot_name}:{len(layers)}")

    material_sources = {
        "occlusion": occlusion_source,
        "roughness": roughness_source,
        "metalness": metalness_source,
        "specular": specular_source,
    }
    slots = tuple(slot_name for slot_name in ("occlusion", "roughness", "metalness", "specular") if material_sources[slot_name])
    legacy_material_source = ""
    if slots:
        legacy_material_source = _generate_legacy_pbr_response_map(
            output_dir,
            f"batch_{batch_index:03d}_combined",
            occlusion_source=occlusion_source,
            roughness_source=roughness_source,
            metalness_source=metalness_source,
            specular_source=specular_source,
        )
        if legacy_material_source:
            outputs.append("legacy_material")
    if len(tuple(dict.fromkeys(decode_modes))) > 1 and slots:
        slot_mode_text = ", ".join(
            f"{slot_name}={material_slot_modes.get(slot_name, 'unknown')}"
            for slot_name in slots
            if material_slot_modes.get(slot_name)
        )
        if slot_mode_text:
            notes.append(f"material inputs combined:{slot_mode_text}")
    if blended_slots:
        notes.append(f"material slots blended:{', '.join(blended_slots)}")

    height_source = ""
    height_amount = 0.0
    height_image = QImage()
    height_candidates = [item for item in inputs if str(item.slot_kind or "").strip().lower() == "height"]
    best_height_contrast = -1.0
    best_height_index = -1
    selected_height_source = ""
    selected_height_item: Optional[PreviewMaterialTextureInput] = None
    for height_index, item in enumerate(height_candidates):
        image = _image_reader(str(item.preview_texture_path or ""), max_dimension=support_map_max_dimension)
        if image.isNull():
            notes.append(f"height unreadable:{_texture_label(item.preview_texture_path, item.texture_name)}")
            continue
        if _image_exceeds_dimension(image, support_map_max_dimension):
            notes.append(f"support maps capped:{support_map_max_dimension}px")
        height_image = image
        height_source, contrast = _generate_height_map(
            image,
            output_dir,
            f"batch_{batch_index:03d}_{height_index:02d}",
            flip_vertical=flip_vertical,
            max_dimension=support_map_max_dimension,
        )
        if not height_source:
            notes.append(f"height flat:{contrast:.3f}")
            continue
        if contrast > best_height_contrast:
            best_height_contrast = contrast
            best_height_index = height_index
            height_image = image
            selected_height_source = height_source
            selected_height_item = item
    if best_height_contrast >= 0.0:
        height_source = selected_height_source
        height_multiplier = 1.0
        height_parameter = ""
        if selected_height_item is not None:
            height_multiplier, height_parameter = _height_amount_multiplier(selected_height_item)
        height_amount = _clamp(
            settings.height_amount * _clamp(0.65 + (best_height_contrast * 1.40), 0.65, 1.0) * height_multiplier,
            0.0,
            0.12,
        )
        outputs.append("height")
        if height_parameter:
            notes.append(f"height scale:{height_multiplier:.2f} from {height_parameter}")
        if len(height_candidates) > 1:
            notes.append(f"height selected:{best_height_index} contrast={best_height_contrast:.3f}")
    if not normal_source and tangents_usable and not height_image.isNull():
        derived_normal_source, contrast = _derive_normal_from_height(
            height_image,
            output_dir,
            f"batch_{batch_index:03d}",
            flip_vertical=flip_vertical,
            max_dimension=support_map_max_dimension,
        )
        if derived_normal_source:
            normal_source = derived_normal_source
            normal_strength = _clamp(settings.normal_strength_floor * 0.55, 0.15, settings.normal_strength_cap)
            outputs.append("normal-from-height")
            notes.append("normal derived from height")
        elif height_candidates:
            notes.append(f"height normal derivation skipped:{contrast:.3f}")

    return MaterialPreviewCombinerResult(
        base_source=base_source,
        base_note=base_note,
        normal_source=normal_source,
        normal_strength=normal_strength,
        occlusion_source=occlusion_source,
        roughness_source=roughness_source,
        metalness_source=metalness_source,
        specular_source=specular_source,
        height_source=height_source,
        height_amount=height_amount,
        legacy_material_source=legacy_material_source,
        legacy_material_decode_mode="pbr_combined" if legacy_material_source else "",
        material_slots=slots,
        decode_modes=tuple(dict.fromkeys(decode_modes)),
        notes=tuple(dict.fromkeys(notes)),
        outputs=tuple(dict.fromkeys(outputs)),
        active=bool(outputs or notes),
        texture_flip_vertical=False if outputs else flip_vertical,
    )


__all__ = [
    "MaterialPreviewCombinerResult",
    "MaterialPreviewCombinerSettings",
    "combine_preview_material",
    "decode_material_sample",
    "synthesize_material_texture_inputs",
]
