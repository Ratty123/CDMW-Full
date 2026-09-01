"""Support-map generators for material preview synthesis."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Callable, Optional, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage

from cdmw.models import PreviewMaterialTextureInput
from cdmw.rendering.material_combiner_decode import _material_parameter_index
from cdmw.rendering.material_combiner_images import (
    _apply_pac_layer_sampling_transform,
    _byte,
    _image_reader,
    _image_luma_range,
    _image_rgb888_write_view,
    _image_rgba8888_view,
    _image_rgba8888_write_view,
    _local_file_url,
    _mask_alpha,
    _numpy_module,
    _numpy_rgba_byte_rows,
    _numpy_rgba_row_chunk,
    _numpy_unit_bytes,
    _numpy_write_row_chunk,
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


_NUMPY_ROW_CHUNK = 32


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
    target_view, target_stride = _image_rgba8888_write_view(target, width, height)
    source_views = [
        _image_rgba8888_view(image, width, height) if not image.isNull() else (None, 0)
        for image in normalized
    ]
    numpy = _numpy_module()
    vectorized = False
    if numpy is not None and target_view is not None:
        try:
            target_array = numpy.ndarray(
                (height, width, 4),
                dtype=numpy.uint8,
                buffer=target_view,
                strides=(target_stride, 4, 1),
            )
            defaults = (255, 148, 0, 0)
            for row_start in range(0, height, 32):
                _raise_if_material_combiner_cancelled(cancelled)
                row_count = min(32, height - row_start)
                for channel, (view, stride) in enumerate(source_views):
                    if view is None:
                        target_array[row_start : row_start + row_count, :, channel] = defaults[channel]
                        continue
                    source = numpy.ndarray(
                        (row_count, width, 3),
                        dtype=numpy.uint8,
                        buffer=view,
                        offset=row_start * stride,
                        strides=(stride, 4, 1),
                    ).astype(numpy.float32)
                    source = (source / numpy.float32(255.0)).astype(numpy.float64)
                    luma = (
                        (0.2126 * source[:, :, 0])
                        + (0.7152 * source[:, :, 1])
                        + (0.0722 * source[:, :, 2])
                    ) * 255.0
                    target_array[row_start : row_start + row_count, :, channel] = numpy.rint(
                        numpy.clip(luma, 0.0, 255.0)
                    ).astype(numpy.uint8)
            vectorized = True
        except (BufferError, TypeError, ValueError):
            vectorized = False
    if not vectorized:
        for y in range(height):
            _raise_if_material_combiner_cancelled(cancelled)
            for x in range(width):
                values: list[int] = []
                for index, image in enumerate(normalized):
                    if image.isNull():
                        values.append(255 if index == 0 else 148 if index == 1 else 0)
                        continue
                    color = image.pixelColor(x, y)
                    luma = (0.2126 * color.redF()) + (0.7152 * color.greenF()) + (0.0722 * color.blueF())
                    values.append(_byte(luma))
                ao, roughness, metalness, specular = (values + [255, 148, 0, 0])[:4]
                target.setPixelColor(x, y, QColor(ao, roughness, metalness, specular))

    _raise_if_material_combiner_cancelled(cancelled)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{stem}_legacy_pbr.png"
    del target_view
    del source_views
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
    source_view, source_stride = _image_rgba8888_view(source, width, height)
    target_view, target_stride = _image_rgba8888_write_view(target, width, height)
    numpy = _numpy_module()
    vectorized = bool(numpy is not None and source_view is not None and target_view is not None)
    if vectorized:
        try:
            for row_start in range(0, height, _NUMPY_ROW_CHUNK):
                _raise_if_material_combiner_cancelled(cancelled)
                row_count = min(_NUMPY_ROW_CHUNK, height - row_start)
                source_bytes = _numpy_rgba_byte_rows(
                    numpy, source_view, source_stride, width, row_start, row_count
                )
                output = _numpy_write_row_chunk(
                    numpy, target_view, target_stride, width, row_start, row_count, 4
                )
                output[:, :, 0] = source_bytes[:, :, 0]
                output[:, :, 1] = 255 - source_bytes[:, :, 1]
                output[:, :, 2] = source_bytes[:, :, 2]
                output[:, :, 3] = 255
                nx = (source_bytes[:, :, 0].astype(numpy.float64) / 255.0) * 2.0 - 1.0
                ny = ((255 - source_bytes[:, :, 1]).astype(numpy.float64) / 255.0) * 2.0 - 1.0
                strength_total += float(
                    numpy.minimum(1.0, numpy.sqrt((nx * nx) + (ny * ny))).sum()
                )
                sample_count += row_count * width
        except (BufferError, MemoryError, TypeError, ValueError):
            vectorized = False
    if not vectorized:
        target = QImage(width, height, QImage.Format.Format_RGBA8888)
        strength_total = 0.0
        sample_count = 0
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


def _positive_tangent_z(x: float, y: float) -> float:
    """Reconstruct the positive tangent hemisphere used for BC5 DDS normals."""

    return math.sqrt(max(0.0, 1.0 - (x * x) - (y * y)))


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
        if _is_layer_normal_input(item):
            prepared = _apply_pac_layer_sampling_transform(
                prepared,
                item,
                cancelled=cancelled,
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
        flipped = _flip_normal_green(base_image, cancelled=cancelled)
        if flipped is not None:
            target = flipped
        else:
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
        composed = _compose_normal_layer(
            target,
            layer,
            mask,
            channel=channel,
            weight=weight,
            cancelled=cancelled,
        )
        if composed is not None:
            target, layer_applied = composed
            if layer_applied:
                role_label = role if not channel else f"{role}:{channel}"
                if role_label not in roles_used:
                    roles_used.append(role_label)
            continue
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
                base_z = _positive_tangent_z(base_x, base_y)
                layer_x = (layer_color.redF() * 2.0) - 1.0
                layer_y = (((255 - layer_color.green()) / 255.0) * 2.0) - 1.0
                layer_z = _positive_tangent_z(layer_x, layer_y)
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

    average_strength = _average_normal_strength(target, cancelled=cancelled)
    if average_strength is None:
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


def _flip_normal_green(
    base_image: QImage,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> Optional[QImage]:
    """Flip the macro normal's green byte in bounded row tiles."""

    numpy = _numpy_module()
    if numpy is None or base_image.isNull():
        return None
    source = base_image.convertToFormat(QImage.Format.Format_RGBA8888)
    height, width = int(source.height()), int(source.width())
    source_view, source_stride = _image_rgba8888_view(source, width, height)
    target = QImage(width, height, QImage.Format.Format_RGBA8888)
    target_view, target_stride = _image_rgba8888_write_view(target, width, height)
    if source_view is None or target_view is None:
        return None
    try:
        for row_start in range(0, height, _NUMPY_ROW_CHUNK):
            _raise_if_material_combiner_cancelled(cancelled)
            row_count = min(_NUMPY_ROW_CHUNK, height - row_start)
            source_bytes = _numpy_rgba_byte_rows(
                numpy, source_view, source_stride, width, row_start, row_count
            )
            output = _numpy_write_row_chunk(
                numpy, target_view, target_stride, width, row_start, row_count, 4
            )
            output[:, :, 0] = source_bytes[:, :, 0]
            output[:, :, 1] = 255 - source_bytes[:, :, 1]
            output[:, :, 2] = source_bytes[:, :, 2]
            output[:, :, 3] = 255
    except (BufferError, MemoryError, TypeError, ValueError):
        return None
    return target


def _compose_normal_layer(
    target: QImage,
    layer: QImage,
    mask: QImage,
    *,
    channel: str,
    weight: float,
    cancelled: Callable[[], bool] | None = None,
):
    """Whiteout-compose one detail normal behind its mask in row tiles.

    `(image, applied)` where `applied` says whether any texel had a live alpha, the way
    the per-pixel loop's `layer_applied` flag does; None when NumPy cannot take it.
    """

    numpy = _numpy_module()
    if numpy is None or target.isNull() or layer.isNull():
        return None
    base_rgba = target.convertToFormat(QImage.Format.Format_RGBA8888)
    layer_rgba = layer.convertToFormat(QImage.Format.Format_RGBA8888)
    height, width = int(base_rgba.height()), int(base_rgba.width())
    if (
        width <= 0
        or height <= 0
        or int(layer_rgba.width()) != width
        or int(layer_rgba.height()) != height
    ):
        return None
    base_view, base_stride = _image_rgba8888_view(base_rgba, width, height)
    layer_view, layer_stride = _image_rgba8888_view(layer_rgba, width, height)
    mask_rgba = QImage()
    mask_view = None
    mask_stride = 0
    if mask is not None and not mask.isNull():
        mask_rgba = mask.convertToFormat(QImage.Format.Format_RGBA8888)
        if int(mask_rgba.width()) != width or int(mask_rgba.height()) != height:
            return None
        mask_view, mask_stride = _image_rgba8888_view(mask_rgba, width, height)
    result = QImage(width, height, QImage.Format.Format_RGBA8888)
    result_view, result_stride = _image_rgba8888_write_view(result, width, height)
    if base_view is None or layer_view is None or result_view is None or (not mask_rgba.isNull() and mask_view is None):
        return None
    applied = False
    mask_index = {"r": 0, "g": 1, "b": 2, "a": 3}.get(channel, 0)
    try:
        for row_start in range(0, height, _NUMPY_ROW_CHUNK):
            _raise_if_material_combiner_cancelled(cancelled)
            row_count = min(_NUMPY_ROW_CHUNK, height - row_start)
            base = _numpy_rgba_row_chunk(
                numpy, base_view, base_stride, width, row_start, row_count
            )
            over_bytes = _numpy_rgba_byte_rows(
                numpy, layer_view, layer_stride, width, row_start, row_count
            )
            over = (
                over_bytes.astype(numpy.float32) / numpy.float32(255.0)
            ).astype(numpy.float64)
            if mask_view is None:
                mask_alpha = numpy.ones((row_count, width), dtype=numpy.float64)
            else:
                mask_alpha = _numpy_rgba_row_chunk(
                    numpy, mask_view, mask_stride, width, row_start, row_count
                )[:, :, mask_index]
            alpha = numpy.clip(float(weight) * mask_alpha, 0.0, 1.0)
            live = alpha > 0.001
            applied = applied or bool(live.any())
            base_x = (base[:, :, 0] * 2.0) - 1.0
            base_y = (base[:, :, 1] * 2.0) - 1.0
            base_z = numpy.sqrt(
                numpy.maximum(0.0, 1.0 - (base_x * base_x) - (base_y * base_y))
            )
            layer_x = (over[:, :, 0] * 2.0) - 1.0
            layer_y = (((255.0 - over_bytes[:, :, 1]) / 255.0) * 2.0) - 1.0
            layer_z = numpy.sqrt(
                numpy.maximum(0.0, 1.0 - (layer_x * layer_x) - (layer_y * layer_y))
            )
            detail_z = (1.0 - alpha) + (layer_z * alpha)
            out_x = base_x + (layer_x * alpha)
            out_y = base_y + (layer_y * alpha)
            out_z = base_z * detail_z
            length = numpy.maximum(
                0.001,
                numpy.sqrt((out_x * out_x) + (out_y * out_y) + (out_z * out_z)),
            )
            red = numpy.where(live, ((out_x / length) * 0.5) + 0.5, base[:, :, 0])
            green = numpy.where(live, ((out_y / length) * 0.5) + 0.5, base[:, :, 1])
            blue = numpy.where(live, ((out_z / length) * 0.5) + 0.5, base[:, :, 2])
            output = _numpy_write_row_chunk(
                numpy, result_view, result_stride, width, row_start, row_count, 4
            )
            output[:, :, 0] = _numpy_unit_bytes(numpy, red)
            output[:, :, 1] = _numpy_unit_bytes(numpy, green)
            output[:, :, 2] = _numpy_unit_bytes(numpy, blue)
            output[:, :, 3] = 255
    except (BufferError, MemoryError, TypeError, ValueError):
        return None
    return (result, True) if applied else (target, False)


def _average_normal_strength(
    target: QImage,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> Optional[float]:
    """The mean xy length of the composed normal using bounded row tiles."""

    numpy = _numpy_module()
    if numpy is None or target.isNull():
        return None
    source = target.convertToFormat(QImage.Format.Format_RGBA8888)
    height, width = int(source.height()), int(source.width())
    source_view, source_stride = _image_rgba8888_view(source, width, height)
    if source_view is None:
        return None
    total = 0.0
    count = 0
    try:
        for row_start in range(0, height, _NUMPY_ROW_CHUNK):
            _raise_if_material_combiner_cancelled(cancelled)
            row_count = min(_NUMPY_ROW_CHUNK, height - row_start)
            array = _numpy_rgba_row_chunk(
                numpy, source_view, source_stride, width, row_start, row_count
            )
            nx = (array[:, :, 0] * 2.0) - 1.0
            ny = (array[:, :, 1] * 2.0) - 1.0
            lengths = numpy.minimum(1.0, numpy.sqrt((nx * nx) + (ny * ny)))
            total += float(lengths.sum())
            count += int(lengths.size)
    except (BufferError, MemoryError, TypeError, ValueError):
        return None
    return total / float(max(1, count))


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
    source_view, source_stride = _image_rgba8888_view(source, width, height)
    target_view, target_stride = _image_rgb888_write_view(target, width, height)
    numpy = _numpy_module()
    vectorized = bool(numpy is not None and source_view is not None and target_view is not None)
    if vectorized:
        try:
            for row_start in range(0, height, _NUMPY_ROW_CHUNK):
                _raise_if_material_combiner_cancelled(cancelled)
                row_count = min(_NUMPY_ROW_CHUNK, height - row_start)
                source_array = _numpy_rgba_row_chunk(
                    numpy, source_view, source_stride, width, row_start, row_count
                )
                luma = (
                    (0.2126 * source_array[:, :, 0])
                    + (0.7152 * source_array[:, :, 1])
                    + (0.0722 * source_array[:, :, 2])
                )
                normalized = numpy.clip((luma - low) / range_value, 0.0, 1.0)
                adjusted = numpy.clip(0.5 + ((normalized - 0.5) * gain), 0.0, 1.0)
                grey = _numpy_unit_bytes(numpy, adjusted)
                output = _numpy_write_row_chunk(
                    numpy, target_view, target_stride, width, row_start, row_count, 3
                )
                output[:, :, :] = grey[:, :, None]
        except (BufferError, MemoryError, TypeError, ValueError):
            vectorized = False
    if not vectorized:
        target = QImage(width, height, QImage.Format.Format_RGB888)
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
    target = QImage(width, height, QImage.Format.Format_RGBA8888)
    range_value = max(high - low, 0.001)
    scale = min(2.5, max(0.65, 0.08 / max(contrast, 0.018)))
    source_view, source_stride = _image_rgba8888_view(source, width, height)
    target_view, target_stride = _image_rgba8888_write_view(target, width, height)
    numpy = _numpy_module()
    vectorized = bool(numpy is not None and source_view is not None and target_view is not None)
    if vectorized:
        try:
            for row_start in range(0, height, _NUMPY_ROW_CHUNK):
                _raise_if_material_combiner_cancelled(cancelled)
                row_count = min(_NUMPY_ROW_CHUNK, height - row_start)
                row_end = row_start + row_count
                read_start = max(0, row_start - 1)
                read_end = min(height, row_end + 1)
                source_array = _numpy_rgba_row_chunk(
                    numpy,
                    source_view,
                    source_stride,
                    width,
                    read_start,
                    read_end - read_start,
                )
                luma = (
                    (0.2126 * source_array[:, :, 0])
                    + (0.7152 * source_array[:, :, 1])
                    + (0.0722 * source_array[:, :, 2])
                )
                center_indices = numpy.arange(row_start, row_end) - read_start
                previous_indices = numpy.maximum(0, numpy.arange(row_start, row_end) - 1) - read_start
                next_indices = numpy.minimum(height - 1, numpy.arange(row_start, row_end) + 1) - read_start
                center = luma[center_indices]
                left = numpy.concatenate((center[:, :1], center[:, :-1]), axis=1)
                right = numpy.concatenate((center[:, 1:], center[:, -1:]), axis=1)
                dx = ((right - left) / range_value) * scale
                dy = ((luma[next_indices] - luma[previous_indices]) / range_value) * scale
                nx = -dx
                ny = -dy
                length = numpy.maximum(0.001, numpy.sqrt((nx * nx) + (ny * ny) + 1.0))
                output = _numpy_write_row_chunk(
                    numpy, target_view, target_stride, width, row_start, row_count, 4
                )
                output[:, :, 0] = _numpy_unit_bytes(numpy, ((nx / length) * 0.5) + 0.5)
                output[:, :, 1] = _numpy_unit_bytes(numpy, ((ny / length) * 0.5) + 0.5)
                output[:, :, 2] = _numpy_unit_bytes(numpy, ((1.0 / length) * 0.5) + 0.5)
                output[:, :, 3] = 255
        except (BufferError, MemoryError, TypeError, ValueError):
            vectorized = False
    if not vectorized:
        luma_grid: list[list[float]] = []
        for y in range(height):
            _raise_if_material_combiner_cancelled(cancelled)
            row: list[float] = []
            for x in range(width):
                color = source.pixelColor(x, y)
                row.append((0.2126 * color.redF()) + (0.7152 * color.greenF()) + (0.0722 * color.blueF()))
            luma_grid.append(row)
        target = QImage(width, height, QImage.Format.Format_RGBA8888)
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
