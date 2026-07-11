from __future__ import annotations

import threading
import sys
from collections import OrderedDict
from typing import Dict, Optional, Tuple

from cdmw.models import ModelPreviewRenderSettings, clamp_model_preview_render_settings


INITIAL_MODEL_PREVIEW_RENDER_SETTINGS = clamp_model_preview_render_settings()
MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION = (
    INITIAL_MODEL_PREVIEW_RENDER_SETTINGS.preview_texture_max_dimension
)
MODEL_SUPPORT_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION = min(
    256,
    max(128, int(INITIAL_MODEL_PREVIEW_RENDER_SETTINGS.low_quality_texture_max_dimension)),
)
FAST_ARCHIVE_PREVIEW_MAX_FACES = 35_000
FAST_ARCHIVE_PREVIEW_TEXTURE_NOTE = (
    "Fast preview skips high-resolution texture preparation while the full-quality preview builds in the background."
)
MODEL_TEXTURE_VISIBLE_FAMILY_SUFFIXES: Tuple[str, ...] = (
    "",
    "_d",
    "_diff",
    "_ct",
    "_color",
    "_col",
    "_bc",
    "_albedo",
    "_basecolor",
    "_base_color",
    "_diffuse",
)
MODEL_TEXTURE_SUPPORT_FAMILY_SUFFIXES: Dict[str, Tuple[str, ...]] = {
    "normal": ("_n", "_normal", "_normalmap"),
    "material": (
        "_sp",
        "_material",
        "_mask",
        "_ma",
        "_mg",
        "_m",
        "_orm",
        "_mra",
        "_rma",
        "_arm",
        "_ao",
        "_spec",
        "_specular",
    ),
    "height": (
        "_disp",
        "_displacement",
        "_height",
        "_hgt",
        "_dmap",
        "_bump",
        "_parallax",
        "_pom",
        "_ssdm",
    ),
}
MODEL_TEXTURE_PREVIEW_PATH_CACHE_LIMIT = 2048
MODEL_TEXTURE_PREVIEW_PATH_CACHE: OrderedDict[Tuple[object, ...], str] = OrderedDict()
MODEL_TEXTURE_PREVIEW_PATH_CACHE_LOCK = threading.Lock()


def set_model_texture_display_preview_max_dimension(
    value: int,
    *,
    low_quality_value: Optional[int] = None,
) -> None:
    global MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION, MODEL_SUPPORT_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION
    settings = clamp_model_preview_render_settings(
        ModelPreviewRenderSettings(
            preview_texture_max_dimension=int(value),
            low_quality_texture_max_dimension=(
                int(low_quality_value)
                if low_quality_value is not None
                else ModelPreviewRenderSettings().low_quality_texture_max_dimension
            ),
        )
    )
    MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION = int(settings.preview_texture_max_dimension)
    MODEL_SUPPORT_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION = min(
        256,
        max(128, int(settings.low_quality_texture_max_dimension)),
    )
    public = sys.modules.get("cdmw.core.archive_model_textures")
    if public is not None:
        public._MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION = MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION
        public._MODEL_SUPPORT_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION = MODEL_SUPPORT_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION
