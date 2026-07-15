"""Support-map generators for material preview synthesis."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Callable, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage

from cdmw.rendering.material_combiner_images import (
    _byte,
    _image_luma_range,
    _local_file_url,
    _raise_if_material_combiner_cancelled,
    _read_generated_map,
    _support_source_image,
)
from cdmw.rendering.material_combiner_rules import _clamp


def _generate_legacy_pbr_response_map(
    output_dir: Path,
    stem: str,
    *,
    occlusion_source: str = "",
    roughness_source: str = "",
    metalness_source: str = "",
    specular_source: str = "",
    cancelled: Callable[[], bool] | None = None,
) -> str:
    _raise_if_material_combiner_cancelled(cancelled)
    source_urls = [occlusion_source, roughness_source, metalness_source, specular_source]
    source_images = [_read_generated_map(source_url) if source_url else QImage() for source_url in source_urls]
    valid = [image for image in source_images if not image.isNull()]
    if not valid:
        return ""
    width = int(valid[0].width())
    height = int(valid[0].height())
    if width <= 0 or height <= 0:
        return ""

    normalized: list[QImage] = []
    for image in source_images:
        _raise_if_material_combiner_cancelled(cancelled)
        if image.isNull():
            normalized.append(QImage())
            continue
        source = image
        if int(source.width()) != width or int(source.height()) != height:
            source = source.scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        normalized.append(source.convertToFormat(QImage.Format.Format_RGBA8888))

    target = QImage(width, height, QImage.Format.Format_RGBA8888)
    for y in range(height):
        _raise_if_material_combiner_cancelled(cancelled)
        for x in range(width):
            values: list[int] = []
            for index, image in enumerate(normalized):
                if image.isNull():
                    if index == 0:
                        values.append(255)
                    elif index == 1:
                        values.append(148)
                    else:
                        values.append(0)
                    continue
                color = image.pixelColor(x, y)
                luma = (0.2126 * color.redF()) + (0.7152 * color.greenF()) + (0.0722 * color.blueF())
                values.append(_byte(luma))
            ao, roughness, metalness, specular = (values + [255, 148, 0, 0])[:4]
            target.setPixelColor(x, y, QColor(ao, roughness, metalness, specular))

    _raise_if_material_combiner_cancelled(cancelled)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{stem}_legacy_pbr.png"
    if not target.save(str(output_path), "PNG"):
        return ""
    return _local_file_url(output_path)


def _generate_normal_map(
    image: QImage,
    output_dir: Path,
    stem: str,
    *,
    flip_vertical: bool,
    max_dimension: int,
    cancelled: Callable[[], bool] | None = None,
) -> Tuple[str, float]:
    _raise_if_material_combiner_cancelled(cancelled)
    if image.isNull():
        return "", 0.0
    source = _support_source_image(image, flip_vertical=flip_vertical, max_dimension=max_dimension)
    if source.isNull():
        return "", 0.0
    width = int(source.width())
    height = int(source.height())
    if width <= 0 or height <= 0:
        return "", 0.0
    strength_total = 0.0
    sample_count = 0
    target = QImage(width, height, QImage.Format.Format_RGBA8888)
    for y in range(height):
        _raise_if_material_combiner_cancelled(cancelled)
        for x in range(width):
            color = source.pixelColor(x, y)
            red = color.red()
            green = 255 - color.green()
            blue = color.blue()
            target.setPixelColor(x, y, QColor(red, green, blue, 255))
            nx = (float(red) / 255.0) * 2.0 - 1.0
            ny = (float(green) / 255.0) * 2.0 - 1.0
            strength_total += min(1.0, math.sqrt((nx * nx) + (ny * ny)))
            sample_count += 1
    average_strength = strength_total / float(max(1, sample_count))
    if average_strength <= 0.012:
        return "", 0.0
    _raise_if_material_combiner_cancelled(cancelled)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{stem}_normal.png"
    if not target.save(str(output_path), "PNG"):
        return "", 0.0
    return _local_file_url(output_path), average_strength


def _generate_height_map(
    image: QImage,
    output_dir: Path,
    stem: str,
    *,
    flip_vertical: bool,
    max_dimension: int,
    cancelled: Callable[[], bool] | None = None,
) -> Tuple[str, float]:
    _raise_if_material_combiner_cancelled(cancelled)
    source = _support_source_image(image, flip_vertical=flip_vertical, max_dimension=max_dimension)
    if source.isNull():
        return "", 0.0
    low, high, contrast = _image_luma_range(source, cancelled=cancelled)
    if contrast < 0.010:
        return "", contrast
    width = int(source.width())
    height = int(source.height())
    target = QImage(width, height, QImage.Format.Format_RGB888)
    range_value = max(high - low, 0.001)
    gain = min(4.0, max(1.0, 0.24 / max(contrast, 0.018)))
    for y in range(height):
        _raise_if_material_combiner_cancelled(cancelled)
        for x in range(width):
            color = source.pixelColor(x, y)
            luma = (0.2126 * color.redF()) + (0.7152 * color.greenF()) + (0.0722 * color.blueF())
            normalized = _clamp((luma - low) / range_value)
            adjusted = _clamp(0.5 + ((normalized - 0.5) * gain))
            grey = _byte(adjusted)
            target.setPixelColor(x, y, QColor(grey, grey, grey))
    _raise_if_material_combiner_cancelled(cancelled)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{stem}_height.png"
    if not target.save(str(output_path), "PNG"):
        return "", contrast
    return _local_file_url(output_path), contrast


def _derive_normal_from_height(
    image: QImage,
    output_dir: Path,
    stem: str,
    *,
    flip_vertical: bool,
    max_dimension: int,
    cancelled: Callable[[], bool] | None = None,
) -> Tuple[str, float]:
    _raise_if_material_combiner_cancelled(cancelled)
    source = _support_source_image(image, flip_vertical=flip_vertical, max_dimension=max_dimension)
    if source.isNull():
        return "", 0.0
    low, high, contrast = _image_luma_range(source, cancelled=cancelled)
    if contrast < 0.018:
        return "", contrast
    width = int(source.width())
    height = int(source.height())
    if width <= 1 or height <= 1:
        return "", contrast
    luma_grid: list[list[float]] = []
    for y in range(height):
        _raise_if_material_combiner_cancelled(cancelled)
        row: list[float] = []
        for x in range(width):
            color = source.pixelColor(x, y)
            row.append((0.2126 * color.redF()) + (0.7152 * color.greenF()) + (0.0722 * color.blueF()))
        luma_grid.append(row)
    target = QImage(width, height, QImage.Format.Format_RGBA8888)
    range_value = max(high - low, 0.001)
    scale = min(2.5, max(0.65, 0.08 / max(contrast, 0.018)))
    for y in range(height):
        _raise_if_material_combiner_cancelled(cancelled)
        ym = max(0, y - 1)
        yp = min(height - 1, y + 1)
        for x in range(width):
            xm = max(0, x - 1)
            xp = min(width - 1, x + 1)
            dx = ((luma_grid[y][xp] - luma_grid[y][xm]) / range_value) * scale
            dy = ((luma_grid[yp][x] - luma_grid[ym][x]) / range_value) * scale
            nx = -dx
            ny = -dy
            nz = 1.0
            length = max(0.001, math.sqrt((nx * nx) + (ny * ny) + (nz * nz)))
            red = _byte((nx / length) * 0.5 + 0.5)
            green = _byte((ny / length) * 0.5 + 0.5)
            blue = _byte((nz / length) * 0.5 + 0.5)
            target.setPixelColor(x, y, QColor(red, green, blue, 255))
    _raise_if_material_combiner_cancelled(cancelled)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{stem}_normal_from_height.png"
    if not target.save(str(output_path), "PNG"):
        return "", contrast
    return _local_file_url(output_path), contrast


__all__ = [
    "_derive_normal_from_height",
    "_generate_height_map",
    "_generate_legacy_pbr_response_map",
    "_generate_normal_map",
]
