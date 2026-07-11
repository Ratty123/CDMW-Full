"""Compatibility facade for Texture Editor domain rules and project I/O."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from cdmw.domain.textures.editor_common import (
    _new_layer_id,
    _normalize_hex,
    _parse_hex_rgb,
    _safe_slug,
)
from cdmw.domain.textures.editor_layers import (
    bump_texture_editor_layer_revision,
    create_texture_editor_layer_mask,
    update_texture_editor_layer,
)
from cdmw.models import (
    DdsInfo,
    TextureEditorAdjustmentLayer,
    TextureEditorDocument,
    TextureEditorFloatingSelection,
    TextureEditorHistoryEntry,
    TextureEditorLayer,
    TextureEditorSelection,
    TextureEditorSourceBinding,
    TextureEditorToolSettings,
)


_PROJECT_VERSION = 1
_VISIBLE_TEXTURE_TYPES = {"color", "ui", "emissive", "impostor", "unknown"}


def _load_rgba_array(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGBA"), dtype=np.uint8).copy()


def save_rgba_array_png(array: np.ndarray, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.asarray(array, dtype=np.uint8), "RGBA").save(output_path, format="PNG")
    return output_path


_LAZY_EXPORT_MODULES = (
    "cdmw.core.texture_editor_project_io",
    "cdmw.core.texture_editor_raster_ops",
    "cdmw.core.texture_editor_layer_ops",
)


def __getattr__(name: str) -> object:
    from importlib import import_module

    if name.startswith("__"):
        raise AttributeError(name)
    for module_name in _LAZY_EXPORT_MODULES:
        module = import_module(module_name)
        try:
            value = getattr(module, name)
        except AttributeError:
            continue
        globals()[name] = value
        return value
    raise AttributeError(name)
