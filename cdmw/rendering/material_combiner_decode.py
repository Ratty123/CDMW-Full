"""Material preview combiner decode mode and slot ranking helpers."""

from __future__ import annotations

from typing import Optional, Sequence, Tuple

from cdmw.models import PreviewMaterialTextureInput
from cdmw.rendering.material_combiner_rules import (
    _NONMETAL_RESPONSE_LIMITS,
    _apply_nonmetal_response_limits,
    _clamp,
    _finite_float,
    _is_visible_color_input,
    _material_candidate_match_score,
    _material_parameter_hint,
    _material_parameter_numeric,
    _material_parameters,
    _material_surface_category,
    _normalize_texture_key,
    _normalized_key,
    _parameter_key,
    _registry_decode_mode_for_input,
    _shader_rule_for_inputs,
    _stem_tokens,
    _strong_metallic_override,
)

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
    registry_mode = _registry_decode_mode_for_input(input_item)
    if registry_mode:
        return registry_mode
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
    if (
        subtype in {"specular_glossiness", "specularglossiness", "gltf_specular_glossiness"}
        or channels[:2] == ("specular", "glossiness")
        or parameter_key in {"specularglossinesstexture", "specularglosstexture"}
        or last_token in {"specularglossiness", "specgloss", "speculargloss"}
    ):
        return "specular_glossiness"
    if subtype in {"glossiness", "gloss", "smoothness", "smooth"} or channels[:1] == ("glossiness",) or last_token in {"gloss", "glossiness", "smooth", "smoothness"}:
        return "glossiness"
    if subtype in {"clearcoat", "clearcoat_factor"}:
        return "clearcoat"
    if subtype == "clearcoat_roughness":
        return "roughness"
    if subtype in {"sheen", "sheen_color"}:
        return "sheen"
    if subtype == "sheen_roughness":
        return "roughness"
    if subtype in {"transmission", "volume", "anisotropy", "iridescence"}:
        return "diagnostic"
    if parameter_key in {"materialtexture", "materialmap"} and last_token in {"sp", "spec", "specular"}:
        return "skin_material" if "skin" in shader_key else "material_response"
    if last_token in {"sp", "spec", "specular"}:
        return "specular"
    if last_token in {"rough", "roughness"}:
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
            return "glossiness" if channels[0] in {"gloss", "smoothness", "gloss_or_smoothness"} else "roughness"
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
    if mode == "specular_glossiness":
        return False, True, False, True
    if mode == "glossiness":
        return False, True, False, False
    if mode == "clearcoat":
        return False, True, False, True
    if mode == "sheen":
        return False, False, False, True
    if mode == "diagnostic":
        return False, False, False, False
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
            "specular_glossiness": 96,
            "glossiness": 95,
            "clearcoat": 58,
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
            "specular_glossiness": 0,
            "glossiness": 0,
            "clearcoat": 0,
            "sheen": 0,
            "specular": 38,
        },
        "specular": {
            "specular": 100,
            "standard_v2_specular": 96,
            "standard_v2_material": 88,
            "specular_glossiness": 100,
            "clearcoat": 78,
            "sheen": 64,
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
    if mode in {"specular", "specular_glossiness", "clearcoat", "sheen", "standard_v2_specular"}:
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
    elif mode == "specular_glossiness":
        specular = _clamp(max(r, g, b), 0.0, 1.0)
        roughness = _clamp(1.0 - a, 0.04, 0.98)
        metalness = 0.0
    elif mode == "glossiness":
        roughness = _clamp(1.0 - max(r, g, b), 0.04, 0.98)
        specular = _clamp(0.18 + ((1.0 - roughness) * 0.22), 0.05, 0.42)
        metalness = 0.0
    elif mode == "clearcoat":
        coat = max(r, g, b, a)
        roughness = _clamp(0.08 + ((1.0 - max(g, a, average)) * 0.42), 0.04, 0.72)
        specular = _clamp(0.18 + (coat * 0.62), 0.08, 0.86)
        metalness = 0.0
    elif mode == "sheen":
        specular = _clamp(0.08 + (max(r, g, b) * 0.34), 0.04, 0.48)
        roughness = _clamp(0.42 + ((1.0 - average) * 0.32), 0.22, 0.94)
        metalness = 0.0
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


def _apply_external_material_factors(
    input_item: Optional[PreviewMaterialTextureInput],
    decode_mode: str,
    ao: float,
    roughness: float,
    metalness: float,
    specular: float,
) -> Tuple[float, float, float, float]:
    if input_item is None:
        return ao, roughness, metalness, specular
    mode = str(decode_mode or "").strip().lower()
    roughness_factor = _material_parameter_numeric(input_item, "roughnessfactor")
    metallic_factor = _material_parameter_numeric(input_item, "metallicfactor", "metalnessfactor")
    glossiness_factor = _material_parameter_numeric(input_item, "glossinessfactor")
    specular_factor = _material_parameter_numeric(input_item, "specularfactor")
    specular_color = _material_parameter_hint(input_item, "specularcolorfactor")
    occlusion_strength = _material_parameter_numeric(input_item, "texturestrengthocclusion", "occlusionstrength")
    if mode == "metallic_roughness":
        if roughness_factor is not None:
            roughness = _clamp(roughness * _clamp(roughness_factor))
        if metallic_factor is not None:
            metalness = _clamp(metalness * _clamp(metallic_factor))
    elif mode in {"specular_glossiness", "glossiness"}:
        if glossiness_factor is not None:
            glossiness = _clamp((1.0 - roughness) * _clamp(glossiness_factor))
            roughness = _clamp(1.0 - glossiness, 0.04, 0.98)
        if specular_factor is not None:
            specular = _clamp(specular * _clamp(specular_factor))
        if specular_color > 0.0:
            specular = _clamp(specular * specular_color)
    elif mode in {"specular", "clearcoat", "sheen"}:
        if specular_factor is not None:
            specular = _clamp(specular * _clamp(specular_factor))
        if specular_color > 0.0:
            specular = _clamp(specular * specular_color)
    if occlusion_strength is not None:
        strength = _clamp(occlusion_strength)
        ao = _clamp(1.0 + (ao - 1.0) * strength, 0.45, 1.0)
    return _clamp(ao, 0.45, 1.0), _clamp(roughness, 0.04, 1.0), _clamp(metalness), _clamp(specular)
