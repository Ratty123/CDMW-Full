"""Compatibility facade for static model-preview thumbnails."""

from __future__ import annotations

from typing import Optional

from PySide6.QtGui import QPixmap

from cdmw.services.preview_rendering_service import (
    StaticModelThumbnailPlan,
    prepare_static_model_thumbnail,
    render_static_model_thumbnail_image,
)


def render_static_model_preview_pixmap(
    preview_model: object,
    *,
    width: int,
    height: int,
    text_color: str,
    draw_point_cloud_when_no_triangles: bool = False,
) -> Optional[QPixmap]:
    """Legacy synchronous wrapper; picker workers use the QImage path directly."""

    image = render_static_model_thumbnail_image(
        preview_model,
        width=width,
        height=height,
        text_color=text_color,
        draw_point_cloud_when_no_triangles=draw_point_cloud_when_no_triangles,
    )
    if image is None or image.isNull():
        return None
    return QPixmap.fromImage(image)


__all__ = [
    "StaticModelThumbnailPlan",
    "prepare_static_model_thumbnail",
    "render_static_model_preview_pixmap",
    "render_static_model_thumbnail_image",
]
