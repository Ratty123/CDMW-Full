from __future__ import annotations

from pathlib import Path
from typing import Optional


SCENE_TEXTURE_V_NORMALIZED_FORMATS = frozenset({"obj", "gltf", "glb", "dae"})


def normalize_model_preview_format(source_format: object = "", source_path: object = "") -> str:
    text = str(source_format or "").strip().lower().lstrip(".")
    if not text and source_path:
        try:
            text = Path(str(source_path)).suffix.lower().lstrip(".")
        except (TypeError, ValueError, OSError):
            text = ""
    if text == "collada":
        return "dae"
    return text


def scene_import_normalizes_texture_v(source_format: object = "", source_path: object = "") -> bool:
    return normalize_model_preview_format(source_format, source_path) in SCENE_TEXTURE_V_NORMALIZED_FORMATS


def resolve_preview_texture_flip_vertical(
    value: Optional[bool],
    *,
    source_format: object = "",
    source_path: object = "",
    default: bool = True,
    flip_texture_v: bool = False,
) -> bool:
    if value is None:
        resolved = False if scene_import_normalizes_texture_v(source_format, source_path) else bool(default)
    else:
        resolved = bool(value)
    return not resolved if bool(flip_texture_v) else resolved


__all__ = [
    "SCENE_TEXTURE_V_NORMALIZED_FORMATS",
    "normalize_model_preview_format",
    "resolve_preview_texture_flip_vertical",
    "scene_import_normalizes_texture_v",
]
