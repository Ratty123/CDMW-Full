"""Output settings that write an edited texture back the way the original was stored (decision 48).

A texture edited inside the Mesh Editor keeps the original's DDS format, colour space
and mip chain. A format CDMW's encoder cannot write is refused before the edit starts,
with the reason, so nothing is converted silently. The rules here are pure; the encode
itself is `TextureEditorNativeDdsService.export_matching_original`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Tuple

from cdmw.constants import SUPPORTED_DDS_FORMAT_CHOICES
from cdmw.domain.textures.editor_presets import normalize_texture_editor_dds_format, texture_editor_dds_presets
from cdmw.domain.textures.output import max_mips_for_size
from cdmw.models import DdsInfo

#: Every format CDMW's DDS encoder (cd-texture-dx) is asked to write today: the Textures
#: workflow's choices and the Texture Editor's presets. Both reach the same helper.
WRITABLE_DDS_FORMATS = frozenset(SUPPORTED_DDS_FORMAT_CHOICES) | frozenset(
    fmt for preset in texture_editor_dds_presets() for fmt in preset.allowed_formats
)


class TextureOutputRefused(ValueError):
    """The texture cannot be written back unchanged; `reason` is the sentence to show."""

    def __init__(self, reason: str, *, dds_format: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.dds_format = dds_format


@dataclass(frozen=True, slots=True)
class OriginalTextureOutput:
    dds_format: str
    srgb: bool
    width: int
    height: int
    mip_count: int
    original_mip_count: int
    #: True when the original carried every mip down to 1x1 and the output does too.
    full_chain: bool
    notes: Tuple[str, ...] = field(default_factory=tuple)


def texture_colour_space(dds_format: str) -> str:
    """'srgb' for the _SRGB formats, 'linear' for the rest (their bytes are read as data)."""
    return "srgb" if normalize_texture_editor_dds_format(dds_format).endswith("_SRGB") else "linear"


def original_texture_output(info: DdsInfo, *, width: int | None = None, height: int | None = None) -> OriginalTextureOutput:
    """The output that matches `info`, at the edited size (default: the original size).

    Raises TextureOutputRefused when the original's format cannot be written.
    """
    dds_format = normalize_texture_editor_dds_format(info.dds_format)
    if not dds_format or dds_format == "UNKNOWN":
        raise TextureOutputRefused("This texture's format is unknown, so CDMW cannot write it back unchanged.")
    if dds_format not in WRITABLE_DDS_FORMATS:
        raise TextureOutputRefused(
            f"This texture is stored as {dds_format}, which CDMW's texture encoder cannot write. "
            "Editing it would change its format, so it stays as it is.",
            dds_format=dds_format,
        )
    if getattr(info, "preserve_only_source", False):
        raise TextureOutputRefused(
            f"This {dds_format} texture can only be kept as it is; CDMW does not rebuild it.",
            dds_format=dds_format,
        )
    out_width = int(width or info.width)
    out_height = int(height or info.height)
    if out_width <= 0 or out_height <= 0:
        raise ValueError("An edited texture needs a positive size.")
    original_mips = max(1, int(info.mip_count))
    original_max = max_mips_for_size(int(info.width), int(info.height))
    output_max = max_mips_for_size(out_width, out_height)
    full_chain = original_mips >= original_max
    notes = []
    if full_chain:
        mip_count = output_max
    else:
        mip_count = min(original_mips, output_max)
        if mip_count != original_mips:
            notes.append(f"The original's {original_mips} mips do not fit {out_width}x{out_height}; {mip_count} are written.")
    if (out_width, out_height) != (int(info.width), int(info.height)):
        notes.append(f"The size changes from {info.width}x{info.height} to {out_width}x{out_height}.")
    return OriginalTextureOutput(
        dds_format=dds_format,
        srgb=texture_colour_space(dds_format) == "srgb",
        width=out_width,
        height=out_height,
        mip_count=mip_count,
        original_mip_count=original_mips,
        full_chain=full_chain,
        notes=tuple(notes),
    )


def check_texture_editable(path: Path) -> OriginalTextureOutput:
    """Read a DDS and say how it would be written back; refuse before any edit starts."""
    from cdmw.core.texture_pipeline.inspection import parse_dds

    try:
        info = parse_dds(Path(path))
    except (OSError, ValueError) as exc:
        raise TextureOutputRefused(f"CDMW cannot read this texture, so it cannot edit it: {exc}") from exc
    return original_texture_output(info)


__all__ = [
    "OriginalTextureOutput",
    "TextureOutputRefused",
    "WRITABLE_DDS_FORMATS",
    "check_texture_editable",
    "original_texture_output",
    "texture_colour_space",
]
