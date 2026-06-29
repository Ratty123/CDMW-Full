from __future__ import annotations

"""Pure Texture Editor DDS preset rules."""

from dataclasses import dataclass
from typing import Mapping, Tuple

from cdmw.domain.textures.output import max_mips_for_size


MIP_MODE_FULL = "full"
MIP_MODE_SINGLE = "single"


@dataclass(frozen=True, slots=True)
class TextureEditorDdsPreset:
    key: str
    label: str
    default_format: str
    colorspace: str
    default_mip_mode: str
    allowed_formats: Tuple[str, ...]
    allowed_mip_modes: Tuple[str, ...]
    warning: str = ""


@dataclass(frozen=True, slots=True)
class TextureEditorResolvedDdsPreset:
    preset: TextureEditorDdsPreset
    dds_format: str
    mip_mode: str
    mip_count: int
    srgb: bool
    warning: str


_PRESETS: Tuple[TextureEditorDdsPreset, ...] = (
    TextureEditorDdsPreset(
        key="base_color",
        label="Base Color",
        default_format="BC7_UNORM_SRGB",
        colorspace="srgb",
        default_mip_mode=MIP_MODE_FULL,
        allowed_formats=("BC7_UNORM_SRGB",),
        allowed_mip_modes=(MIP_MODE_FULL,),
    ),
    TextureEditorDdsPreset(
        key="normal",
        label="Normal",
        default_format="BC5_UNORM",
        colorspace="linear",
        default_mip_mode=MIP_MODE_FULL,
        allowed_formats=("BC5_UNORM",),
        allowed_mip_modes=(MIP_MODE_FULL,),
    ),
    TextureEditorDdsPreset(
        key="mask_packed",
        label="Mask Packed",
        default_format="BC7_UNORM",
        colorspace="linear",
        default_mip_mode=MIP_MODE_FULL,
        allowed_formats=("BC7_UNORM",),
        allowed_mip_modes=(MIP_MODE_FULL,),
        warning="Packed mask export preserves independent channel data; review R/G/B/A assignments before saving.",
    ),
    TextureEditorDdsPreset(
        key="ui_icon",
        label="UI/Icon",
        default_format="BC7_UNORM_SRGB",
        colorspace="srgb",
        default_mip_mode=MIP_MODE_SINGLE,
        allowed_formats=("BC7_UNORM_SRGB", "R8G8B8A8_UNORM_SRGB"),
        allowed_mip_modes=(MIP_MODE_SINGLE, MIP_MODE_FULL),
    ),
    TextureEditorDdsPreset(
        key="emissive",
        label="Emissive",
        default_format="BC7_UNORM_SRGB",
        colorspace="srgb",
        default_mip_mode=MIP_MODE_FULL,
        allowed_formats=("BC7_UNORM_SRGB",),
        allowed_mip_modes=(MIP_MODE_FULL,),
    ),
    TextureEditorDdsPreset(
        key="height_scalar",
        label="Height/Scalar",
        default_format="R8_UNORM",
        colorspace="linear",
        default_mip_mode=MIP_MODE_FULL,
        allowed_formats=("R8_UNORM", "R16_UNORM"),
        allowed_mip_modes=(MIP_MODE_FULL,),
    ),
)

_PRESET_BY_KEY: Mapping[str, TextureEditorDdsPreset] = {preset.key: preset for preset in _PRESETS}
_FORMAT_ALIASES = {
    "BC7_SRGB": "BC7_UNORM_SRGB",
    "BC7_LINEAR": "BC7_UNORM",
    "RGBA": "R8G8B8A8_UNORM_SRGB",
    "RGBA_SRGB": "R8G8B8A8_UNORM_SRGB",
    "R8": "R8_UNORM",
    "R16": "R16_UNORM",
}
_FORMAT_LABELS = {
    "BC7_UNORM_SRGB": "BC7 sRGB",
    "BC7_UNORM": "BC7 linear",
    "BC5_UNORM": "BC5 linear",
    "R8G8B8A8_UNORM_SRGB": "RGBA sRGB",
    "R8_UNORM": "R8 linear",
    "R16_UNORM": "R16 linear",
}


def texture_editor_dds_presets() -> Tuple[TextureEditorDdsPreset, ...]:
    return _PRESETS


def texture_editor_dds_preset(key: str) -> TextureEditorDdsPreset:
    normalized = str(key or "").strip().lower()
    return _PRESET_BY_KEY.get(normalized, _PRESET_BY_KEY["base_color"])


def normalize_texture_editor_dds_format(value: str) -> str:
    normalized = str(value or "").strip().upper()
    return _FORMAT_ALIASES.get(normalized, normalized)


def texture_editor_dds_format_label(value: str) -> str:
    normalized = normalize_texture_editor_dds_format(value)
    return _FORMAT_LABELS.get(normalized, normalized)


def texture_editor_dds_preset_warning(key: str) -> str:
    return texture_editor_dds_preset(key).warning


def resolve_texture_editor_dds_preset(
    key: str,
    *,
    width: int,
    height: int,
    dds_format: str = "",
    mip_mode: str = "",
) -> TextureEditorResolvedDdsPreset:
    preset = texture_editor_dds_preset(key)
    resolved_format = normalize_texture_editor_dds_format(dds_format) if str(dds_format or "").strip() else preset.default_format
    if resolved_format not in preset.allowed_formats:
        raise ValueError(f"{resolved_format} is not valid for {preset.label}.")
    resolved_mip_mode = str(mip_mode or "").strip().lower() or preset.default_mip_mode
    if resolved_mip_mode not in preset.allowed_mip_modes:
        raise ValueError(f"{resolved_mip_mode} mips are not valid for {preset.label}.")
    mip_count = 1 if resolved_mip_mode == MIP_MODE_SINGLE else max_mips_for_size(int(width), int(height))
    return TextureEditorResolvedDdsPreset(
        preset=preset,
        dds_format=resolved_format,
        mip_mode=resolved_mip_mode,
        mip_count=max(1, int(mip_count)),
        srgb=preset.colorspace == "srgb" or resolved_format.endswith("_SRGB"),
        warning=preset.warning,
    )


__all__ = [
    "MIP_MODE_FULL",
    "MIP_MODE_SINGLE",
    "TextureEditorDdsPreset",
    "TextureEditorResolvedDdsPreset",
    "normalize_texture_editor_dds_format",
    "resolve_texture_editor_dds_preset",
    "texture_editor_dds_format_label",
    "texture_editor_dds_preset",
    "texture_editor_dds_preset_warning",
    "texture_editor_dds_presets",
]
