"""Support-map generators for material preview synthesis."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Callable, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage

from cdmw.models import PreviewMaterialTextureInput
from cdmw.rendering.material_combiner_decode import _material_parameter_index
from cdmw.rendering.material_combiner_images import (
    _byte,
    _image_reader,
    _image_luma_range,
    _local_file_url,
    _mask_alpha,
    _raise_if_material_combiner_cancelled,
    _read_generated_map,
    _support_source_image,
)
from cdmw.rendering.material_combiner_rules import (
    _clamp,
    _layer_channel,
    _layer_weight_from_parameters,
    _texture_label,
    _visible_layer_role,
)


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


def _is_layer_normal_input(input_item: PreviewMaterialTextureInput) -> bool:
    disposition = str(getattr(input_item, "binding_disposition", "") or "").strip().lower()
    source_kind = str(getattr(input_item, "source_kind", "") or "").strip().lower()
    role = _visible_layer_role(input_item)
    return bool(
        disposition in {"layer_only", "layer_material_response"}
        or source_kind == "crimson_layer_normal"
        or role in {"damage", "detail", "grime", "layer"}
    )


def _normal_input_order_key(
    input_item: PreviewMaterialTextureInput,
) -> tuple[object, ...]:
    """Return the authored, deterministic order for normal composition."""

    role = _visible_layer_role(input_item)
    channel = _layer_channel(input_item)
    try:
        owner_slot_index = int(getattr(input_item, "owner_slot_index", -1))
    except (TypeError, ValueError, OverflowError):
        owner_slot_index = -1

    def normalized(value: object) -> str:
        return str(value or "").replace("\\", "/").strip().casefold()

    return (
        1 if _is_layer_normal_input(input_item) else 0,
        _material_parameter_index(input_item),
        owner_slot_index if owner_slot_index >= 0 else 9999,
        {
            "damage": 0,
            "grime": 1,
            "detail": 2,
            "layer": 3,
        }.get(role, 4),
        {"": 0, "r": 1, "g": 2, "b": 3, "a": 4}.get(channel, 5),
        normalized(getattr(input_item, "parameter_name", "")),
        normalized(getattr(input_item, "source_texture_path", "")),
        normalized(getattr(input_item, "source_dds_path", "")),
        normalized(getattr(input_item, "texture_name", "")),
        normalized(getattr(input_item, "preview_texture_path", "")),
    )


def _generate_synthesized_normal_map(
    normal_inputs: Sequence[PreviewMaterialTextureInput],
    mask_inputs: dict[str, PreviewMaterialTextureInput],
    output_dir: Path,
    stem: str,
    *,
    flip_vertical: bool,
    max_dimension: int,
    cancelled: Callable[[], bool] | None = None,
) -> Tuple[str, float, Tuple[str, ...], Tuple[str, ...]]:
    """Combine a macro normal with masked PAC detail normals.

    PAC material graphs bind grime/detail normals separately from the primary
    tangent-space normal. Whiteout composition retains the macro shape while
    adding each authored layer behind its role/channel selector.
    """

    _raise_if_material_combiner_cancelled(cancelled)
    ordered_normal_inputs = tuple(sorted(normal_inputs, key=_normal_input_order_key))
    layer_items = tuple(
        item for item in ordered_normal_inputs if _is_layer_normal_input(item)
    )
    if not layer_items:
        return "", 0.0, (), ()

    prepared_normals: list[Tuple[PreviewMaterialTextureInput, QImage]] = []
    unreadable_inputs: list[str] = []
    for item in ordered_normal_inputs:
        _raise_if_material_combiner_cancelled(cancelled)
        image = _image_reader(
            str(getattr(item, "preview_texture_path", "") or ""),
            max_dimension=max_dimension,
        )
        if image.isNull():
            unreadable_inputs.append(
                "normal unreadable:"
                + _texture_label(item.preview_texture_path, item.texture_name)
            )
            continue
        prepared = _support_source_image(
            image,
            flip_vertical=flip_vertical,
            max_dimension=max_dimension,
        )
        if not prepared.isNull():
            prepared_normals.append(
                (item, prepared.convertToFormat(QImage.Format.Format_RGBA8888))
            )
    if not prepared_normals:
        return "", 0.0, (), tuple(unreadable_inputs)

    prepared_masks: dict[str, QImage] = {}
    for role, item in mask_inputs.items():
        _raise_if_material_combiner_cancelled(cancelled)
        image = _image_reader(
            str(getattr(item, "preview_texture_path", "") or ""),
            max_dimension=max_dimension,
        )
        if image.isNull():
            unreadable_inputs.append(
                "normal mask unreadable:"
                + _texture_label(item.preview_texture_path, item.texture_name)
            )
            continue
        prepared = _support_source_image(
            image,
            flip_vertical=flip_vertical,
            max_dimension=max_dimension,
        )
        if not prepared.isNull():
            prepared_masks[role] = prepared.convertToFormat(QImage.Format.Format_RGBA8888)

    size_candidates = [
        image
        for _item, image in prepared_normals
        if int(image.width()) > 0 and int(image.height()) > 0
    ]
    size_candidates.extend(
        image
        for image in prepared_masks.values()
        if int(image.width()) > 0 and int(image.height()) > 0
    )
    if not size_candidates:
        return "", 0.0, (), tuple(unreadable_inputs)
    target_size_source = max(
        size_candidates,
        key=lambda image: (
            int(image.width()) * int(image.height()),
            max(int(image.width()), int(image.height())),
        ),
    )
    width = int(target_size_source.width())
    height = int(target_size_source.height())
    if width <= 0 or height <= 0:
        return "", 0.0, (), tuple(unreadable_inputs)

    base_entry = next(
        (
            (item, image)
            for item, image in prepared_normals
            if not _is_layer_normal_input(item)
        ),
        None,
    )
    target = QImage(width, height, QImage.Format.Format_RGBA8888)
    if base_entry is None:
        target.fill(QColor(128, 127, 255, 255))
    else:
        base_image = base_entry[1]
        if int(base_image.width()) != width or int(base_image.height()) != height:
            base_image = base_image.scaled(
                width,
                height,
                Qt.IgnoreAspectRatio,
                Qt.SmoothTransformation,
            )
        for y in range(height):
            _raise_if_material_combiner_cancelled(cancelled)
            for x in range(width):
                color = base_image.pixelColor(x, y)
                target.setPixelColor(
                    x,
                    y,
                    QColor(color.red(), 255 - color.green(), color.blue(), 255),
                )

    for role, image in tuple(prepared_masks.items()):
        if int(image.width()) != width or int(image.height()) != height:
            prepared_masks[role] = image.scaled(
                width,
                height,
                Qt.IgnoreAspectRatio,
                Qt.SmoothTransformation,
            ).convertToFormat(QImage.Format.Format_RGBA8888)

    roles_used: list[str] = []
    has_base = base_entry is not None
    for item, source_image in prepared_normals:
        if not _is_layer_normal_input(item):
            continue
        _raise_if_material_combiner_cancelled(cancelled)
        layer = source_image
        if int(layer.width()) != width or int(layer.height()) != height:
            layer = layer.scaled(
                width,
                height,
                Qt.IgnoreAspectRatio,
                Qt.SmoothTransformation,
            ).convertToFormat(QImage.Format.Format_RGBA8888)
        role = _visible_layer_role(item)
        channel = _layer_channel(item)
        mask = prepared_masks.get(role) or prepared_masks.get("color") or QImage()
        weight = _layer_weight_from_parameters(item, has_base=has_base)
        if weight <= 0.001:
            continue
        layer_applied = False
        for y in range(height):
            _raise_if_material_combiner_cancelled(cancelled)
            for x in range(width):
                alpha = _clamp(weight * _mask_alpha(mask, x, y, channel=channel))
                if alpha <= 0.001:
                    continue
                base_color = target.pixelColor(x, y)
                layer_color = layer.pixelColor(x, y)
                base_x = (base_color.redF() * 2.0) - 1.0
                base_y = (base_color.greenF() * 2.0) - 1.0
                base_z = (base_color.blueF() * 2.0) - 1.0
                layer_x = (layer_color.redF() * 2.0) - 1.0
                layer_y = (((255 - layer_color.green()) / 255.0) * 2.0) - 1.0
                layer_z = (layer_color.blueF() * 2.0) - 1.0
                detail_x = layer_x * alpha
                detail_y = layer_y * alpha
                detail_z = (1.0 - alpha) + (layer_z * alpha)
                out_x = base_x + detail_x
                out_y = base_y + detail_y
                out_z = base_z * detail_z
                length = max(
                    0.001,
                    math.sqrt((out_x * out_x) + (out_y * out_y) + (out_z * out_z)),
                )
                target.setPixelColor(
                    x,
                    y,
                    QColor(
                        _byte(((out_x / length) * 0.5) + 0.5),
                        _byte(((out_y / length) * 0.5) + 0.5),
                        _byte(((out_z / length) * 0.5) + 0.5),
                        255,
                    ),
                )
                layer_applied = True
        if layer_applied:
            role_label = role if not channel else f"{role}:{channel}"
            if role_label not in roles_used:
                roles_used.append(role_label)

    strength_total = 0.0
    sample_count = 0
    for y in range(height):
        _raise_if_material_combiner_cancelled(cancelled)
        for x in range(width):
            color = target.pixelColor(x, y)
            nx = (color.redF() * 2.0) - 1.0
            ny = (color.greenF() * 2.0) - 1.0
            strength_total += min(1.0, math.sqrt((nx * nx) + (ny * ny)))
            sample_count += 1
    average_strength = strength_total / float(max(1, sample_count))
    if average_strength <= 0.012 or not roles_used:
        return "", 0.0, (), tuple(unreadable_inputs)

    _raise_if_material_combiner_cancelled(cancelled)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{stem}_normal.png"
    if not target.save(str(output_path), "PNG"):
        return "", 0.0, (), tuple(unreadable_inputs)
    return (
        _local_file_url(output_path),
        average_strength,
        tuple(roles_used),
        tuple(unreadable_inputs),
    )


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
    "_generate_synthesized_normal_map",
    "_is_layer_normal_input",
]
