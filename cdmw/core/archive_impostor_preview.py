"""Read-only Archive Browser inspector for tree impostor descriptors (`.imp`).

Distant vegetation is drawn from impostors: `tree/impostor/<name>.imp` plus two
atlases beside it, `<name>_impostor_color.dds` (DXT1) and
`<name>_impostor_depth.dds` (BC4), each 1024 x 1024. In game 1.0.0.3446 all
1,612 `.imp` files are 72 bytes:

    0x00  "IMP "              magic
    0x04  00 01 00 00         version bytes
    0x08  8 zero bytes
    0x10  10 x float32        not identified (they vary per plant)
    0x38  u32 atlas size      1024 in every file; the atlases are 1024 px
    0x3C  u32 views per side  8 in every file; the colour atlas is an 8 x 8 grid of views
    0x40  u32                 1 in every file, not identified
    0x44  4 zero bytes

The two integer labels rest on those correlations (every atlas sampled is 1024
px, and the colour atlases visibly hold 8 x 8 views), not on game code.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import PurePosixPath

from cdmw.core.archive_model_references import _StructuredBinaryPreviewBundle

IMPOSTOR_EXTENSION = ".imp"
IMPOSTOR_SIZE = 72
_MAGIC = b"IMP "


class ImpostorError(ValueError):
    """The bytes are not an impostor descriptor this inspector knows."""


@dataclass(frozen=True)
class ImpostorPreview:
    bundle: _StructuredBinaryPreviewBundle
    #: The colour and depth atlases the descriptor's name implies.
    atlas_paths: tuple[str, str]


def impostor_atlas_paths(virtual_path: str) -> tuple[str, str]:
    path = PurePosixPath(str(virtual_path or "").replace("\\", "/"))
    stem = path.name[: -len(IMPOSTOR_EXTENSION)] if path.name.lower().endswith(IMPOSTOR_EXTENSION) else path.stem
    folder = str(path.parent) if str(path.parent) != "." else ""
    prefix = f"{folder}/{stem}" if folder else stem
    return f"{prefix}_impostor_color.dds", f"{prefix}_impostor_depth.dds"


def build_impostor_preview(data: bytes, virtual_path: str) -> ImpostorPreview:
    if len(data) != IMPOSTOR_SIZE or data[:4] != _MAGIC:
        raise ImpostorError(f"not a {IMPOSTOR_SIZE}-byte IMP descriptor")
    floats = struct.unpack_from("<10f", data, 0x10)
    atlas_size, views, unknown = struct.unpack_from("<III", data, 0x38)
    color, depth = impostor_atlas_paths(virtual_path)
    lines = [
        f"Tree impostor descriptor for {virtual_path}",
        "",
        "Summary:",
        f"- Version bytes: {data[4:8].hex(' ')}",
        f"- Atlas size: {atlas_size} px" + (" (matches the shipped atlases)" if atlas_size == 1024 else ""),
        f"- Views per side: {views}" + (f" ({views} x {views} grid in the colour atlas)" if views else ""),
        f"- Unidentified integer: {unknown}",
        "",
        "Atlases:",
        f"  Colour: {color}",
        f"  Depth: {depth}",
        "",
        "Unidentified floats (offset 0x10):",
        "  " + ", ".join(f"{value:.6g}" for value in floats),
    ]
    if data[8:16] != bytes(8) or data[0x44:0x48] != bytes(4):
        lines.extend(["", "Note: bytes the shipped files keep at zero are set in this file."])
    return ImpostorPreview(
        bundle=_StructuredBinaryPreviewBundle(
            preview_text="\n".join(lines),
            detail_lines=(
                "The image shows the colour atlas when it is in the archives.",
                "Atlas size and views per side are labelled from the shipped atlases, not from game code.",
                "This inspector is read-only.",
            ),
            metadata_label="Tree Impostor",
        ),
        atlas_paths=(color, depth),
    )


__all__ = ["IMPOSTOR_EXTENSION", "ImpostorError", "ImpostorPreview", "build_impostor_preview", "impostor_atlas_paths"]
