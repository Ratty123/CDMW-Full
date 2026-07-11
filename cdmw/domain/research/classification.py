"""Pure Research path and classification-choice rules."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import List, Tuple

_SYSTEM_AREA_RULES: Tuple[Tuple[str, str], ...] = (
    ("ui", "ui"),
    ("ui", "icon"),
    ("ui", "hud"),
    ("ui", "menu"),
    ("ui", "widget"),
    ("sound", "sound"),
    ("sound", "voice"),
    ("sound", "dialog"),
    ("gameplay", "gameplay"),
    ("gameplay", "quest"),
    ("gameplay", "skill"),
    ("gameplay", "actor"),
    ("gameplay", "npc"),
    ("gameplay", "battle"),
    ("materials", "material"),
    ("materials", "renderpass"),
    ("materials", "shader"),
    ("materials", "effect"),
    ("textures", "texture"),
    ("textures", "impostor"),
    ("textures", "decal"),
    ("textures", "atlas"),
    ("world", "object"),
    ("world", "interior"),
    ("world", "gimmick"),
    ("world", "nature"),
    ("character", "character"),
    ("character", "head"),
    ("character", "body"),
    ("animation", "anim"),
    ("animation", "motion"),
    ("animation", "hkx"),
)


def _normalized_parts(path_value: str) -> Tuple[str, ...]:
    return tuple(part for part in PurePosixPath(path_value.replace("\\", "/")).parts if part)


def system_area_from_path(path_value: str) -> str:
    lowered = path_value.replace("\\", "/").lower()
    for area, token in _SYSTEM_AREA_RULES:
        if f"/{token}/" in lowered or lowered.startswith(f"{token}/") or token in lowered.split("/")[0]:
            return area
    parts = _normalized_parts(path_value)
    if not parts:
        return "other"
    head = parts[0].lower()
    return {
        "object": "world",
        "character": "character",
        "sound": "sound",
        "material": "materials",
        "ui": "ui",
    }.get(head, head if len(head) <= 16 else "other")


def _package_bucket_for_path(path_value: str) -> str:
    parts = _normalized_parts(path_value)
    if not parts:
        return "other"
    prefix = "/".join(parts[:2]) if len(parts) >= 2 else "/".join(parts)
    return f"{system_area_from_path(path_value)} :: {prefix}"


_UNKNOWN_RESOLVER_LABELS: Tuple[Tuple[str, str, str], ...] = (
    ("color_albedo", "color", "albedo"),
    ("color_variant", "color", "albedo_variant"),
    ("ui", "ui", "ui"),
    ("emissive", "emissive", "emissive"),
    ("normal", "normal", "normal"),
    ("roughness", "roughness", "roughness"),
    ("height", "height", "displacement"),
    ("mask_generic", "mask", "mask"),
    ("mask_specular", "mask", "specular"),
    ("mask_opacity", "mask", "opacity_mask"),
    ("vector", "vector", "vector"),
    ("unknown", "unknown", "unknown"),
)


def default_unknown_resolver_label_choice() -> str:
    return "color_albedo"


def unknown_resolver_label_choices() -> List[Tuple[str, str, str]]:
    return list(_UNKNOWN_RESOLVER_LABELS)


def unknown_resolver_choice_for(texture_type: str, semantic_subtype: str) -> str:
    normalized_type = str(texture_type or "").strip().lower()
    normalized_subtype = str(semantic_subtype or "").strip().lower()
    for choice_key, choice_type, choice_subtype in _UNKNOWN_RESOLVER_LABELS:
        if normalized_type == choice_type and normalized_subtype == choice_subtype:
            return choice_key
    for choice_key, choice_type, _choice_subtype in _UNKNOWN_RESOLVER_LABELS:
        if normalized_type == choice_type:
            return choice_key
    return default_unknown_resolver_label_choice()


def unknown_resolver_choice_label(choice_key: str) -> str:
    mapping = {
        "color_albedo": "Color / Albedo",
        "color_variant": "Color / Variant",
        "ui": "UI",
        "emissive": "Emissive",
        "normal": "Normal",
        "roughness": "Roughness",
        "height": "Height / Displacement",
        "mask_generic": "Mask / Generic",
        "mask_specular": "Mask / Specular",
        "mask_opacity": "Mask / Opacity",
        "vector": "Vector",
        "unknown": "Keep Unknown",
    }
    return mapping.get(choice_key, choice_key)


def _default_semantic_subtype_for_type(texture_type: str) -> str:
    return {
        "color": "albedo",
        "ui": "ui",
        "emissive": "emissive",
        "impostor": "impostor",
        "normal": "normal",
        "roughness": "roughness",
        "height": "displacement",
        "mask": "mask",
        "vector": "vector",
    }.get(str(texture_type or "").strip().lower(), "unknown")


__all__ = [
    "default_unknown_resolver_label_choice",
    "system_area_from_path",
    "unknown_resolver_choice_for",
    "unknown_resolver_choice_label",
    "unknown_resolver_label_choices",
]
