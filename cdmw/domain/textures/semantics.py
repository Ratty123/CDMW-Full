"""Texture semantic lookup helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import List, Tuple

from cdmw.constants import (
    UPSCALE_TEXTURE_PRESET_ALL,
    UPSCALE_TEXTURE_PRESET_BALANCED,
    UPSCALE_TEXTURE_PRESET_COLOR_UI,
    UPSCALE_TEXTURE_PRESET_COLOR_UI_EMISSIVE,
)
from cdmw.domain.textures.profiles import _DEFAULT_SEMANTIC_SUBTYPES


_PRESET_UPSCALE_TYPES = {
    UPSCALE_TEXTURE_PRESET_BALANCED: ("color", "ui", "emissive", "impostor"),
    UPSCALE_TEXTURE_PRESET_COLOR_UI: ("color", "ui"),
    UPSCALE_TEXTURE_PRESET_COLOR_UI_EMISSIVE: ("color", "ui", "emissive", "impostor"),
    UPSCALE_TEXTURE_PRESET_ALL: (
        "color",
        "ui",
        "emissive",
        "impostor",
        "normal",
        "roughness",
        "mask",
        "height",
        "vector",
        "unknown",
    ),
}
_TECHNICAL_TEXTURE_TYPES = frozenset({"normal", "roughness", "mask", "height", "vector"})
_LOSSY_PNG_RISK_TYPES = frozenset({"height", "vector", "roughness", "mask"})


@dataclass(slots=True)
class TextureUpscaleDecision:
    path: str
    texture_type: str
    semantic_subtype: str
    semantic_confidence: int
    should_upscale: bool
    recommended_colorspace: str
    format_strategy: str
    recommended_texconv_format: str
    preserve_alpha: bool
    alpha_mode: str
    packed_channels: Tuple[str, ...] = ()
    precision_sensitive: bool = False
    preserve_original_due_to_intermediate: bool = False
    intermediate_policy: str = "png_ok"
    source_evidence: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


def default_semantic_subtypes() -> Mapping[str, tuple[str, ...]]:
    return dict(_DEFAULT_SEMANTIC_SUBTYPES)


def should_upscale_texture(texture_type: str, preset: str) -> bool:
    normalized = str(preset or "").strip().lower()
    upscale_types = _PRESET_UPSCALE_TYPES.get(
        normalized,
        _PRESET_UPSCALE_TYPES[UPSCALE_TEXTURE_PRESET_BALANCED],
    )
    return texture_type in upscale_types


def is_technical_texture_type(texture_type: str) -> bool:
    return texture_type in _TECHNICAL_TEXTURE_TYPES


def is_png_intermediate_high_risk(texture_type: str, original_texconv_format: str = "") -> bool:
    original_upper = str(original_texconv_format or "").strip().upper()
    return texture_type in _LOSSY_PNG_RISK_TYPES or "FLOAT" in original_upper or "SNORM" in original_upper


__all__ = [
    "TextureUpscaleDecision",
    "default_semantic_subtypes",
    "is_png_intermediate_high_risk",
    "is_technical_texture_type",
    "should_upscale_texture",
]
