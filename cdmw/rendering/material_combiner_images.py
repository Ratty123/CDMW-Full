"""Material preview combiner image and map generation helpers."""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Callable, Optional, Sequence, Tuple

from PySide6.QtCore import QSize, QUrl, Qt
from PySide6.QtGui import QColor, QImage, QImageReader, QImageWriter

from cdmw.domain.cancellation import RunCancelled
from cdmw.rendering.material_combiner_pixels import numpy_module, to_byte_array
from cdmw.models import PreviewMaterialTextureInput
from cdmw.rendering.material_combiner_decode import (
    _apply_external_material_factors,
    _material_decode_output_flags,
    _resolve_external_material_factors,
    affine_decode_mode_terms,
    decode_material_sample,
)
from cdmw.rendering.material_combiner_rules import (
    _LAYER_CHANNEL_INDEX,
    _NONMETAL_RESPONSE_LIMITS,
    _apply_nonmetal_response_limits,
    _byte4_channels,
    _nonmetal_response_limits,
    _clamp,
    _finite_float,
    _height_amount_multiplier,
    _is_visible_color_input,
    _layer_channel,
    _layer_tint,
    _layer_weight_from_parameters,
    _material_parameter_channel_hint,
    _material_parameter_hint,
    _material_surface_category,
    _strong_metallic_override,
    _texture_label,
    _texture_rule_for_input,
    _visible_layer_role,
)


_IMAGE_BYTE_DECODE_RETRY_DELAYS_SECONDS = tuple(
    min(0.5, 0.1 * attempt) for attempt in range(1, 20)
)
_NUMPY_ROW_CHUNK = 32


def _save_generated_png(image: QImage, path: Path) -> bool:
    """Keep generated preview maps lossless without expensive PNG compression."""
    writer = QImageWriter(str(path), b"PNG")
    writer.setCompression(15)
    return writer.write(image)


def _raise_if_material_combiner_cancelled(
    cancelled: Callable[[], bool] | None,
) -> None:
    if cancelled is not None and cancelled():
        raise RunCancelled("Material preview synthesis cancelled.")


def _byte(value: float) -> int:
    return max(0, min(255, int(round(_clamp(value) * 255.0))))


def _source_url_local_path(source_url: str) -> str:
    normalized = str(source_url or "").strip()
    if not normalized:
        return ""
    try:
        path = QUrl(normalized).toLocalFile()
    except Exception:
        path = ""
    return path or normalized


def _local_file_url(path: Path) -> str:
    return QUrl.fromLocalFile(str(path.resolve())).toString()


def _mask_alpha(
    mask_image: QImage,
    x: int,
    y: int,
    *,
    channel: str,
) -> float:
    if mask_image.isNull():
        return 1.0
    color = mask_image.pixelColor(x, y)
    index = _LAYER_CHANNEL_INDEX.get(channel, 0)
    values = (color.redF(), color.greenF(), color.blueF(), color.alphaF())
    return _clamp(values[index] if index < len(values) else values[0])


def _selector_dye_strengths(tints: Sequence[Sequence[float]]) -> Tuple[float, float, float]:
    strengths: list[float] = []
    for channel in range(3):
        try:
            color = tuple(tints[channel] or ()) if channel < len(tints) else ()
            strength = (
                _clamp(float(color[3]))
                if len(color) >= 4
                else (1.0 if len(color) >= 3 else 0.0)
            )
        except (TypeError, ValueError, OverflowError):
            strength = 0.0
        strengths.append(strength)
    return tuple(strengths)  # type: ignore[return-value]


def _pac_layer_sampling_transform(
    input_item: Optional[PreviewMaterialTextureInput],
) -> Optional[Tuple[float, float, float, float, float]]:
    """Decode one channel's PAC detail-layer UV transform.

    The shipped character shader gives the R, G and B detail layers separate
    Byte4 transforms on properties 0, 1 and 3. The matching byte in
    ``_dyeingPropertyBlend`` is the quantized rotation. A missing transform is
    deliberately different from an all-zero Byte4: the former means no
    transform, while the latter is an authored very-small scale.
    """

    if input_item is None:
        return None
    channel = _layer_channel(input_item)
    channel_index = {"r": 0, "g": 1, "b": 2}.get(channel)
    property_suffix = {"r": "0", "g": "1", "b": "3"}.get(channel)
    if channel_index is None or property_suffix is None:
        return None

    transform_name = f"dyeingtransformproperty{property_suffix}"
    transform_channels: Tuple[float, ...] = ()
    rotation_channels: Tuple[float, ...] = ()
    for parameter in tuple(getattr(input_item, "material_parameters", ()) or ()):
        key = "".join(
            character
            for character in str(getattr(parameter, "parameter_name", "") or "").casefold()
            if character.isalnum()
        )
        if key == transform_name:
            transform_channels = _byte4_channels(getattr(parameter, "value", ""))
        elif key == "dyeingpropertyblend":
            rotation_channels = _byte4_channels(getattr(parameter, "value", ""))

    if len(transform_channels) < 4:
        return None
    scale_x, scale_y, offset_x, offset_y = (
        float(value) for value in transform_channels[:4]
    )
    angle = 0.0
    if len(rotation_channels) > channel_index:
        angle = (float(rotation_channels[channel_index]) * (2.0 * math.pi)) - math.pi

    # 127 and 128 are the two Byte4 encodings nearest zero rotation. Treat
    # their half-step quantization as identity when every other component is
    # also identity, avoiding a needless full-image resample and byte drift.
    quantized_zero_angle = math.pi / 255.0
    if (
        abs(scale_x - 1.0) <= 1e-12
        and abs(scale_y - 1.0) <= 1e-12
        and abs(offset_x) <= 1e-12
        and abs(offset_y) <= 1e-12
        and abs(angle) <= quantized_zero_angle + 1e-12
    ):
        return None
    return scale_x, scale_y, offset_x, offset_y, angle


def _apply_pac_layer_sampling_transform(
    image: QImage,
    input_item: Optional[PreviewMaterialTextureInput],
    *,
    cancelled: Callable[[], bool] | None = None,
) -> QImage:
    """Bake the shader's repeat-sampled PAC layer UV transform into an image."""

    transform = _pac_layer_sampling_transform(input_item)
    if image.isNull() or transform is None:
        return image
    width, height = int(image.width()), int(image.height())
    if width <= 0 or height <= 0:
        return image

    scale_x, scale_y, offset_x, offset_y, angle = transform
    scale_x = max(scale_x, 1e-5)
    scale_y = max(scale_y, 1e-5)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    source = image.convertToFormat(QImage.Format.Format_RGBA8888)
    result = QImage(width, height, QImage.Format.Format_RGBA8888)
    source_view, source_stride = _image_rgba8888_view(source, width, height)
    result_view, result_stride = _image_rgba8888_write_view(result, width, height)
    numpy = _numpy_module()

    if numpy is not None and source_view is not None and result_view is not None:
        try:
            source_bytes = numpy.ndarray(
                (height, width, 4),
                dtype=numpy.uint8,
                buffer=source_view,
                strides=(source_stride, 4, 1),
            )
            output_x = (numpy.arange(width, dtype=numpy.float64) + 0.5) / float(width)
            for row_start in range(0, height, _NUMPY_ROW_CHUNK):
                _raise_if_material_combiner_cancelled(cancelled)
                row_count = min(_NUMPY_ROW_CHUNK, height - row_start)
                output_y = (
                    numpy.arange(row_start, row_start + row_count, dtype=numpy.float64)
                    + 0.5
                ) / float(height)
                centered_x = (output_x[None, :] - 0.5 - offset_x) / scale_x
                centered_y = (output_y[:, None] - 0.5 + offset_y) / scale_y
                sample_u = numpy.mod(
                    (centered_x * cosine) - (centered_y * sine) + 0.5,
                    1.0,
                )
                sample_v = numpy.mod(
                    (centered_x * sine) + (centered_y * cosine) + 0.5,
                    1.0,
                )
                source_x = (sample_u * float(width)) - 0.5
                source_y = (sample_v * float(height)) - 0.5
                x0_floor = numpy.floor(source_x)
                y0_floor = numpy.floor(source_y)
                fraction_x = source_x - x0_floor
                fraction_y = source_y - y0_floor
                x0 = x0_floor.astype(numpy.int64) % width
                y0 = y0_floor.astype(numpy.int64) % height
                x1 = (x0 + 1) % width
                y1 = (y0 + 1) % height
                top = (
                    source_bytes[y0, x0].astype(numpy.float64)
                    * (1.0 - fraction_x)[:, :, None]
                    + source_bytes[y0, x1].astype(numpy.float64)
                    * fraction_x[:, :, None]
                )
                bottom = (
                    source_bytes[y1, x0].astype(numpy.float64)
                    * (1.0 - fraction_x)[:, :, None]
                    + source_bytes[y1, x1].astype(numpy.float64)
                    * fraction_x[:, :, None]
                )
                sampled = (
                    top * (1.0 - fraction_y)[:, :, None]
                    + bottom * fraction_y[:, :, None]
                )
                output = _numpy_write_row_chunk(
                    numpy,
                    result_view,
                    result_stride,
                    width,
                    row_start,
                    row_count,
                    4,
                )
                output[:, :, :] = numpy.rint(
                    numpy.clip(sampled, 0.0, 255.0)
                ).astype(numpy.uint8)
            return result
        except (BufferError, MemoryError, TypeError, ValueError):
            pass

    def repeated_bilinear(u: float, v: float) -> QColor:
        source_x = ((u % 1.0) * width) - 0.5
        source_y = ((v % 1.0) * height) - 0.5
        x0_floor = math.floor(source_x)
        y0_floor = math.floor(source_y)
        fraction_x = source_x - x0_floor
        fraction_y = source_y - y0_floor
        x0, y0 = x0_floor % width, y0_floor % height
        x1, y1 = (x0 + 1) % width, (y0 + 1) % height
        colors = (
            source.pixelColor(x0, y0),
            source.pixelColor(x1, y0),
            source.pixelColor(x0, y1),
            source.pixelColor(x1, y1),
        )
        values: list[int] = []
        for component in (QColor.red, QColor.green, QColor.blue, QColor.alpha):
            top = (component(colors[0]) * (1.0 - fraction_x)) + (
                component(colors[1]) * fraction_x
            )
            bottom = (component(colors[2]) * (1.0 - fraction_x)) + (
                component(colors[3]) * fraction_x
            )
            values.append(
                max(
                    0,
                    min(
                        255,
                        int(round(top * (1.0 - fraction_y) + bottom * fraction_y)),
                    ),
                )
            )
        return QColor(*values)

    result = QImage(width, height, QImage.Format.Format_RGBA8888)
    for y in range(height):
        _raise_if_material_combiner_cancelled(cancelled)
        output_v = (y + 0.5) / float(height)
        for x in range(width):
            output_u = (x + 0.5) / float(width)
            centered_x = (output_u - 0.5 - offset_x) / scale_x
            centered_y = (output_v - 0.5 + offset_y) / scale_y
            sample_u = (centered_x * cosine) - (centered_y * sine) + 0.5
            sample_v = (centered_x * sine) + (centered_y * cosine) + 0.5
            result.setPixelColor(x, y, repeated_bilinear(sample_u, sample_v))
    return result


def _largest_meaningful_image_size(
    images: Sequence[QImage],
    *,
    max_dimension: int = 0,
) -> QSize:
    """Return one real source/control domain, optionally reduced to the caller cap.

    The result is selected from the available images instead of filling the
    requested maximum.  That lets a high-resolution authoring caller preserve
    a 512x1024 selector domain without inflating a genuinely 256x256-only
    material to 2048x2048.
    """

    candidates = [
        image
        for image in images
        if not image.isNull() and int(image.width()) > 0 and int(image.height()) > 0
    ]
    if not candidates:
        return QSize()
    source = max(
        candidates,
        key=lambda image: (
            int(image.width()) * int(image.height()),
            max(int(image.width()), int(image.height())),
        ),
    )
    width = int(source.width())
    height = int(source.height())
    limit = max(0, int(max_dimension or 0))
    if limit > 0 and max(width, height) > limit:
        return QSize(width, height).scaled(limit, limit, Qt.KeepAspectRatio)
    return QSize(width, height)


def _initialize_synthesized_albedo_target(
    prepared_base: QImage,
    source_layers: Sequence[Tuple[PreviewMaterialTextureInput, QImage]],
    fallback_image: QImage,
    neutral_base_color: Tuple[float, float, float],
    control_images: Sequence[QImage] = (),
    *,
    preserve_base_alpha: bool,
    cancelled: Callable[[], bool] | None,
) -> tuple[QImage, int, int, int]:
    target_format = QImage.Format.Format_RGBA8888 if preserve_base_alpha else QImage.Format.Format_RGB888
    # Default PAC overlay swatches can be only 4x4. They may seed color, but
    # must not force authored layer textures and selector masks down to 4x4.
    size_candidates = [
        image
        for image in (
            prepared_base,
            *(image for _item, image in source_layers),
            fallback_image,
            *control_images,
        )
        if not image.isNull() and int(image.width()) > 0 and int(image.height()) > 0
    ]
    target_size = _largest_meaningful_image_size(size_candidates)
    width = int(target_size.width())
    height = int(target_size.height())
    if not prepared_base.isNull():
        target_base = prepared_base
        if int(target_base.width()) != width or int(target_base.height()) != height:
            target_base = target_base.scaled(
                width,
                height,
                Qt.IgnoreAspectRatio,
                Qt.SmoothTransformation,
            )
        return (
            target_base.convertToFormat(target_format),
            width,
            height,
            0,
        )
    color_seed_available = not fallback_image.isNull()
    first_item = source_layers[0][0] if source_layers else None
    first_image = source_layers[0][1] if source_layers else fallback_image
    target = QImage(width, height, target_format)
    if len(neutral_base_color) >= 3:
        red, green, blue = (_byte(float(value)) for value in neutral_base_color[:3])
        target.fill(QColor(red, green, blue))
        return target, width, height, 0
    if color_seed_available and not source_layers:
        target.fill(QColor(153, 156, 158, 255))
        return target, width, height, 0
    # When the PAC RGB selector will seed the base, the first visible layer is
    # only a fallback surface for selector gaps. Its channel-local dye remains
    # masked and is applied in the normal layer loop below.
    first_layer_is_channel_local = bool(
        first_item is not None and _layer_channel(first_item)
    )
    tint = (
        _layer_tint(first_item)
        if first_item is not None
        and not color_seed_available
        and not first_layer_is_channel_local
        else ()
    )
    if int(first_image.width()) != width or int(first_image.height()) != height:
        first_image = first_image.scaled(
            width,
            height,
            Qt.IgnoreAspectRatio,
            Qt.SmoothTransformation,
        )
    seeded = _seed_target_from_layer(
        first_image,
        tint,
        target_format=target_format,
        preserve_base_alpha=preserve_base_alpha,
        cancelled=cancelled,
    )
    if seeded is not None:
        return (
            seeded,
            width,
            height,
            0 if color_seed_available or first_layer_is_channel_local else 1,
        )
    for y in range(height):
        _raise_if_material_combiner_cancelled(cancelled)
        for x in range(width):
            color = first_image.pixelColor(x, y)
            red, green, blue = color.redF(), color.greenF(), color.blueF()
            if tint:
                red *= tint[0]
                green *= tint[1]
                blue *= tint[2]
            target.setPixelColor(
                x,
                y,
                QColor(
                    _byte(red),
                    _byte(green),
                    _byte(blue),
                    color.alpha() if preserve_base_alpha else 255,
                ),
            )
    return (
        target,
        width,
        height,
        0 if color_seed_available or first_layer_is_channel_local else 1,
    )


def _seed_target_from_layer(
    first_image,
    tint,
    *,
    target_format,
    preserve_base_alpha: bool,
    cancelled=None,
):
    """Seed the target from the first visible layer in bounded row tiles."""

    numpy = numpy_module()
    if numpy is None or first_image.isNull():
        return None
    source = first_image.convertToFormat(QImage.Format.Format_RGBA8888)
    width, height = int(source.width()), int(source.height())
    source_view, source_stride = _image_rgba8888_view(source, width, height)
    target = QImage(width, height, target_format)
    if target_format == QImage.Format.Format_RGBA8888:
        target_view, target_stride = _image_rgba8888_write_view(target, width, height)
        target_channels = 4
    else:
        target_view, target_stride = _image_rgb888_write_view(target, width, height)
        target_channels = 3
    if source_view is None or target_view is None:
        return None
    tint_values = (
        numpy.array([float(value) for value in tint[:3]], dtype=numpy.float64)
        if tint
        else None
    )
    try:
        for row_start in range(0, height, _NUMPY_ROW_CHUNK):
            _raise_if_material_combiner_cancelled(cancelled)
            row_count = min(_NUMPY_ROW_CHUNK, height - row_start)
            source_bytes = _numpy_rgba_byte_rows(
                numpy, source_view, source_stride, width, row_start, row_count
            )
            rgb = (
                source_bytes[:, :, :3].astype(numpy.float32) / numpy.float32(255.0)
            ).astype(numpy.float64)
            if tint_values is not None:
                rgb *= tint_values
            output = _numpy_write_row_chunk(
                numpy,
                target_view,
                target_stride,
                width,
                row_start,
                row_count,
                target_channels,
            )
            output[:, :, :3] = _numpy_unit_bytes(numpy, rgb)
            if target_channels == 4:
                output[:, :, 3] = source_bytes[:, :, 3] if preserve_base_alpha else 255
    except (BufferError, MemoryError, TypeError, ValueError):
        return None
    return target


def _apply_albedo_selector_dye(
    target, color_blending_mask, color_blending_tints, width, height, target_format, preserve_base_alpha,
    cancelled,
):
    color_blending_seed_applied = False
    color_blending_dye_strengths = _selector_dye_strengths(
        color_blending_tints
    )
    has_color_blending_dye = any(
        strength > 1.0 / 255.0 for strength in color_blending_dye_strengths
    )
    if (
        not color_blending_mask.isNull()
        and len(color_blending_tints) >= 3
        and has_color_blending_dye
    ):
        if int(color_blending_mask.width()) != width or int(color_blending_mask.height()) != height:
            color_blending_mask = color_blending_mask.scaled(
                width,
                height,
                Qt.IgnoreAspectRatio,
                Qt.SmoothTransformation,
            )
        blended = _blend_selector_tints(
            target, color_blending_mask, color_blending_tints,
            target_format=target_format,
            preserve_base_alpha=preserve_base_alpha,
            cancelled=cancelled,
        )
        if blended is not None:
            target = blended
        else:
            selector_reference_lumas = _selector_reference_lumas(
                target,
                color_blending_mask,
                cancelled=cancelled,
            )
            for y in range(height):
                _raise_if_material_combiner_cancelled(cancelled)
                for x in range(width):
                    selector = color_blending_mask.pixelColor(x, y)
                    weights = tuple(
                        selector_component * color_blending_dye_strengths[channel]
                        for channel, selector_component in enumerate(
                            (selector.redF(), selector.greenF(), selector.blueF())
                        )
                    )
                    total = sum(weights)
                    if total <= 0.001:
                        continue
                    normalized = tuple(weight / total for weight in weights)
                    seeded = tuple(
                        sum(
                            (
                                float(color_blending_tints[channel][component])
                                if len(tuple(color_blending_tints[channel] or ())) >= 3
                                else 0.0
                            )
                            * normalized[channel]
                            for channel in range(3)
                        )
                        for component in range(3)
                    )
                    coverage = _clamp(total)
                    base = target.pixelColor(x, y)
                    source_luma = (
                        base.redF() * 0.2126
                        + base.greenF() * 0.7152
                        + base.blueF() * 0.0722
                    )
                    reference_luma = sum(
                        selector_reference_lumas[channel] * normalized[channel]
                        for channel in range(3)
                    )
                    detail_scale = _clamp(
                        source_luma / max(reference_luma, 1.0 / 255.0),
                        0.55,
                        1.25,
                    )
                    seeded = tuple(component * detail_scale for component in seeded)
                    target.setPixelColor(
                        x,
                        y,
                        QColor(
                            _byte((base.redF() * (1.0 - coverage)) + (seeded[0] * coverage)),
                            _byte((base.greenF() * (1.0 - coverage)) + (seeded[1] * coverage)),
                            _byte((base.blueF() * (1.0 - coverage)) + (seeded[2] * coverage)),
                            base.alpha() if preserve_base_alpha else 255,
                        ),
                    )
        color_blending_seed_applied = True
    return target, color_blending_seed_applied


def _generate_synthesized_albedo_map(
    base_image: QImage,
    layer_inputs: Sequence[PreviewMaterialTextureInput],
    mask_inputs: dict[str, PreviewMaterialTextureInput],
    output_dir: Path,
    stem: str,
    *,
    flip_vertical: bool,
    max_dimension: int,
    neutral_base_color: Tuple[float, float, float] = (),
    color_blending_mask_input: Optional[PreviewMaterialTextureInput] = None,
    color_blending_tints: Sequence[Tuple[float, float, float]] = (),
    preserve_base_alpha: bool = False,
    prefer_largest_source_domain: bool = False,
    cancelled: Callable[[], bool] | None = None,
) -> Tuple[str, str]:
    _raise_if_material_combiner_cancelled(cancelled)
    prepared_base = (
        QImage()
        if len(neutral_base_color) >= 3
        else _support_source_image(base_image, flip_vertical=flip_vertical, max_dimension=max_dimension)
    )
    source_layers: list[Tuple[PreviewMaterialTextureInput, QImage]] = []
    for item in layer_inputs:
        _raise_if_material_combiner_cancelled(cancelled)
        image = _image_reader(str(getattr(item, "preview_texture_path", "") or ""), max_dimension=max_dimension)
        if image.isNull():
            continue
        prepared = _support_source_image(image, flip_vertical=flip_vertical, max_dimension=max_dimension)
        if prepared.isNull():
            continue
        prepared = _apply_pac_layer_sampling_transform(
            prepared,
            item,
            cancelled=cancelled,
        )
        source_layers.append((item, prepared.convertToFormat(QImage.Format.Format_RGBA8888)))
    color_blending_mask = QImage()
    if color_blending_mask_input is not None and len(color_blending_tints) >= 3:
        color_blending_mask = _image_reader(
            str(getattr(color_blending_mask_input, "preview_texture_path", "") or ""),
            max_dimension=max_dimension,
        )
        if not color_blending_mask.isNull():
            color_blending_mask = _support_source_image(
                color_blending_mask,
                flip_vertical=flip_vertical,
                max_dimension=max_dimension,
            ).convertToFormat(QImage.Format.Format_RGBA8888)
    if prepared_base.isNull() and not source_layers and color_blending_mask.isNull():
        return "", ""

    prepared_masks: dict[str, QImage] = {}
    for role, item in mask_inputs.items():
        _raise_if_material_combiner_cancelled(cancelled)
        image = _image_reader(
            str(getattr(item, "preview_texture_path", "") or ""),
            max_dimension=max_dimension,
        )
        if image.isNull():
            continue
        prepared = _support_source_image(image, flip_vertical=flip_vertical, max_dimension=max_dimension)
        if prepared.isNull():
            continue
        prepared_masks[role] = prepared.convertToFormat(QImage.Format.Format_RGBA8888)

    target_format = QImage.Format.Format_RGBA8888 if preserve_base_alpha else QImage.Format.Format_RGB888
    target, width, height, layer_start = _initialize_synthesized_albedo_target(
        prepared_base,
        source_layers,
        color_blending_mask,
        neutral_base_color,
        tuple(prepared_masks.values()) if prefer_largest_source_domain else (),
        preserve_base_alpha=preserve_base_alpha,
        cancelled=cancelled,
    )

    (
        target, color_blending_seed_applied,
    ) = _apply_albedo_selector_dye(
        target, color_blending_mask, color_blending_tints, width, height, target_format, preserve_base_alpha,
        cancelled,
    )

    for role, prepared in tuple(prepared_masks.items()):
        if int(prepared.width()) != width or int(prepared.height()) != height:
            prepared = prepared.scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        prepared_masks[role] = prepared.convertToFormat(QImage.Format.Format_RGBA8888)

    roles_used: list[str] = []
    masked_detail_dye_tint_applied = False
    has_base = bool(
        not prepared_base.isNull()
        or len(neutral_base_color) >= 3
        or color_blending_seed_applied
    )
    for item, image in source_layers[layer_start:]:
        _raise_if_material_combiner_cancelled(cancelled)
        layer = image
        if int(layer.width()) != width or int(layer.height()) != height:
            layer = layer.scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        role = _visible_layer_role(item)
        channel = _layer_channel(item)
        mask = prepared_masks.get(role) or prepared_masks.get("color") or QImage()
        weight = _layer_weight_from_parameters(item, has_base=has_base)
        if weight <= 0.001:
            continue
        tint = _layer_tint(item)
        composed = _compose_albedo_layer(
            target, layer, mask, channel=channel, weight=weight, tint=tint, role=role,
            color_blending_seed_applied=color_blending_seed_applied,
            target_format=target_format, preserve_base_alpha=preserve_base_alpha,
            cancelled=cancelled,
        )
        if composed is not None:
            target, layer_tinted_detail = composed
            masked_detail_dye_tint_applied = masked_detail_dye_tint_applied or layer_tinted_detail
            role_label = role if not channel else f"{role}:{channel}"
            if role_label not in roles_used:
                roles_used.append(role_label)
            continue
        for y in range(height):
            _raise_if_material_combiner_cancelled(cancelled)
            for x in range(width):
                base = target.pixelColor(x, y)
                overlay = layer.pixelColor(x, y)
                alpha = _clamp(weight * _mask_alpha(mask, x, y, channel=channel))
                red = overlay.redF()
                green = overlay.greenF()
                blue = overlay.blueF()
                if role == "detail" and tint:
                    # Detail dye colors are channel-local PAC authority.  Keep
                    # them behind the detail-mask channel instead of promoting
                    # them to a global tint or discarding them after the RGB
                    # selector seeds the base surface.
                    luma = _clamp((0.299 * red) + (0.587 * green) + (0.114 * blue))
                    modulation = 0.82 + (0.36 * luma)
                    tinted = tuple(_clamp(float(component) * modulation) for component in tint[:3])
                    dye_alpha = alpha * (
                        _clamp(float(tint[3])) if len(tint) >= 4 else 1.0
                    )
                    out_r = (base.redF() * (1.0 - dye_alpha)) + (tinted[0] * dye_alpha)
                    out_g = (base.greenF() * (1.0 - dye_alpha)) + (tinted[1] * dye_alpha)
                    out_b = (base.blueF() * (1.0 - dye_alpha)) + (tinted[2] * dye_alpha)
                    masked_detail_dye_tint_applied = True
                elif color_blending_seed_applied and role in {"grime", "layer", "damage"}:
                    # These auxiliary overlays add micro-variation behind the
                    # selector dye. Detail diffuse is intentionally excluded:
                    # with no exact detail dye, the shipped shader retains the
                    # sampled detail RGB instead of reducing it to luminance.
                    luma = _clamp((0.299 * red) + (0.587 * green) + (0.114 * blue))
                    modulation = 0.82 + (0.36 * luma)
                    factor = (1.0 - alpha) + (modulation * alpha)
                    out_r = _clamp(base.redF() * factor)
                    out_g = _clamp(base.greenF() * factor)
                    out_b = _clamp(base.blueF() * factor)
                else:
                    if tint:
                        red *= tint[0]
                        green *= tint[1]
                        blue *= tint[2]
                    out_r = (base.redF() * (1.0 - alpha)) + (_clamp(red) * alpha)
                    out_g = (base.greenF() * (1.0 - alpha)) + (_clamp(green) * alpha)
                    out_b = (base.blueF() * (1.0 - alpha)) + (_clamp(blue) * alpha)
                target.setPixelColor(
                    x,
                    y,
                    QColor(
                        _byte(out_r),
                        _byte(out_g),
                        _byte(out_b),
                        base.alpha() if preserve_base_alpha else 255,
                    ),
                )
        role_label = role if not channel else f"{role}:{channel}"
        if role_label not in roles_used:
            roles_used.append(role_label)

    _raise_if_material_combiner_cancelled(cancelled)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{stem}_albedo.png"
    if not _save_generated_png(target, output_path):
        return "", ""
    if roles_used:
        note = "albedo synthesized:" + ",".join(roles_used[:6])
    else:
        note = "albedo synthesized:visible layer"
    if len(neutral_base_color) >= 3:
        note += "; neutral_metal_base_synthesized"
    if color_blending_seed_applied:
        note += "; pac_color_blending_tint_seed:r,g,b; pac_color_layers_modulated"
    if masked_detail_dye_tint_applied:
        note += "; pac_detail_dye_tints_masked"
    if prepared_base.isNull():
        note += "; no reliable base DDS; no_reliable_full_base_albedo"
    return _local_file_url(output_path), note


def _selector_reference_lumas(target, selector_mask, *, cancelled=None):
    weighted_lumas = [0.0, 0.0, 0.0]
    weight_totals = [0.0, 0.0, 0.0]
    visible_luma = 0.0
    visible_count = 0
    for y in range(int(target.height())):
        _raise_if_material_combiner_cancelled(cancelled)
        for x in range(int(target.width())):
            base = target.pixelColor(x, y)
            source_luma = (
                base.redF() * 0.2126
                + base.greenF() * 0.7152
                + base.blueF() * 0.0722
            )
            if source_luma <= 1.0 / 255.0:
                continue
            visible_luma += source_luma
            visible_count += 1
            selector = selector_mask.pixelColor(x, y)
            weights = (selector.redF(), selector.greenF(), selector.blueF())
            for channel, weight in enumerate(weights):
                weighted_lumas[channel] += source_luma * weight
                weight_totals[channel] += weight
    fallback = visible_luma / visible_count if visible_count else 0.5
    return tuple(
        round(
            _clamp(
                weighted_lumas[channel] / weight_totals[channel]
                if weight_totals[channel] > 0.001
                else fallback,
                1.0 / 255.0,
                1.0,
            )
            * 4096.0
        )
        / 4096.0
        for channel in range(3)
    )


def _selector_tint_palette(numpy, tints):
    palette = numpy.zeros((3, 3), dtype=numpy.float64)
    channel_strengths = numpy.array(
        _selector_dye_strengths(tints),
        dtype=numpy.float64,
    )
    try:
        for channel in range(3):
            color = tuple(tints[channel] or ()) if channel < len(tints) else ()
            if len(color) < 3:
                continue
            palette[channel, :] = [
                _clamp(float(component)) for component in color[:3]
            ]
    except (TypeError, ValueError, OverflowError):
        return None
    return palette, channel_strengths


def _blend_selector_tints(
    target,
    selector_mask,
    tints,
    *,
    target_format,
    preserve_base_alpha: bool,
    cancelled=None,
):
    """Apply the PAC RGB palette without erasing the source texture's value detail."""

    numpy = numpy_module()
    if numpy is None or target.isNull() or selector_mask.isNull():
        return None
    palette_state = _selector_tint_palette(numpy, tints)
    if palette_state is None:
        return None
    palette, channel_strengths = palette_state
    if not bool(channel_strengths.any()):
        return target.convertToFormat(target_format)
    base_rgba = target.convertToFormat(QImage.Format.Format_RGBA8888)
    selector_rgba = selector_mask.convertToFormat(QImage.Format.Format_RGBA8888)
    width = int(base_rgba.width())
    height = int(base_rgba.height())
    if (
        width <= 0
        or height <= 0
        or int(selector_rgba.width()) != width
        or int(selector_rgba.height()) != height
    ):
        return None
    base_view, base_stride = _image_rgba8888_view(base_rgba, width, height)
    selector_view, selector_stride = _image_rgba8888_view(selector_rgba, width, height)
    result = QImage(width, height, target_format)
    if target_format == QImage.Format.Format_RGBA8888:
        result_view, result_stride = _image_rgba8888_write_view(result, width, height)
        result_channels = 4
    else:
        result_view, result_stride = _image_rgb888_write_view(result, width, height)
        result_channels = 3
    if base_view is None or selector_view is None or result_view is None:
        return None

    # The reference value is global, so obtain its five scalar reductions in a
    # first tiled pass. No source-sized float plane survives between tiles.
    weighted_lumas = numpy.zeros(3, dtype=numpy.float64)
    weight_totals = numpy.zeros(3, dtype=numpy.float64)
    visible_luma = 0.0
    visible_count = 0
    try:
        for row_start in range(0, height, _NUMPY_ROW_CHUNK):
            _raise_if_material_combiner_cancelled(cancelled)
            row_count = min(_NUMPY_ROW_CHUNK, height - row_start)
            base = _numpy_rgba_row_chunk(
                numpy, base_view, base_stride, width, row_start, row_count
            )
            weights = _numpy_rgba_row_chunk(
                numpy, selector_view, selector_stride, width, row_start, row_count
            )[:, :, :3] * channel_strengths
            source_luma = (
                base[:, :, 0] * 0.2126
                + base[:, :, 1] * 0.7152
                + base[:, :, 2] * 0.0722
            )
            visible = source_luma > (1.0 / 255.0)
            visible_weights = weights * visible[:, :, None]
            weight_totals += visible_weights.sum(axis=(0, 1))
            weighted_lumas += (
                visible_weights * source_luma[:, :, None]
            ).sum(axis=(0, 1))
            visible_luma += float(source_luma[visible].sum())
            visible_count += int(numpy.count_nonzero(visible))
        fallback = visible_luma / visible_count if visible_count else 0.5
        reference_lumas = numpy.array(
            [
                weighted_lumas[channel] / weight_totals[channel]
                if weight_totals[channel] > 0.001
                else fallback
                for channel in range(3)
            ],
            dtype=numpy.float64,
        )
        reference_lumas = numpy.rint(
            numpy.clip(reference_lumas, 1.0 / 255.0, 1.0) * 4096.0
        ) / 4096.0

        for row_start in range(0, height, _NUMPY_ROW_CHUNK):
            _raise_if_material_combiner_cancelled(cancelled)
            row_count = min(_NUMPY_ROW_CHUNK, height - row_start)
            base_bytes = _numpy_rgba_byte_rows(
                numpy, base_view, base_stride, width, row_start, row_count
            )
            base = (
                base_bytes.astype(numpy.float32) / numpy.float32(255.0)
            ).astype(numpy.float64)
            weights = _numpy_rgba_row_chunk(
                numpy, selector_view, selector_stride, width, row_start, row_count
            )[:, :, :3] * channel_strengths
            # Summed left to right, matching the original per-pixel expression.
            total = weights[:, :, 0] + weights[:, :, 1] + weights[:, :, 2]
            live = total > 0.001
            safe = numpy.where(live, total, 1.0)
            normalized = weights / safe[:, :, None]
            seeded = numpy.empty_like(normalized)
            for component in range(3):
                seeded[:, :, component] = (
                    (palette[0, component] * normalized[:, :, 0])
                    + (palette[1, component] * normalized[:, :, 1])
                    + (palette[2, component] * normalized[:, :, 2])
                )
            source_luma = (
                base[:, :, 0] * 0.2126
                + base[:, :, 1] * 0.7152
                + base[:, :, 2] * 0.0722
            )
            reference_luma = (
                normalized[:, :, 0] * reference_lumas[0]
                + normalized[:, :, 1] * reference_lumas[1]
                + normalized[:, :, 2] * reference_lumas[2]
            )
            detail_scale = numpy.clip(
                source_luma / numpy.maximum(reference_luma, 1.0 / 255.0),
                0.55,
                1.25,
            )
            seeded *= detail_scale[:, :, None]
            coverage = numpy.clip(total, 0.0, 1.0)[:, :, None]
            mixed = (base[:, :, :3] * (1.0 - coverage)) + (seeded * coverage)
            out = numpy.where(live[:, :, None], mixed, base[:, :, :3])
            result_bytes = _numpy_write_row_chunk(
                numpy,
                result_view,
                result_stride,
                width,
                row_start,
                row_count,
                result_channels,
            )
            result_bytes[:, :, :3] = _numpy_unit_bytes(numpy, out)
            if result_channels == 4:
                result_bytes[:, :, 3] = base_bytes[:, :, 3] if preserve_base_alpha else 255
    except (BufferError, MemoryError, TypeError, ValueError):
        return None
    return result


def _compose_albedo_layer(
    target,
    layer,
    mask,
    *,
    channel: str,
    weight: float,
    tint,
    role: str,
    color_blending_seed_applied: bool,
    target_format,
    preserve_base_alpha: bool,
    cancelled=None,
):
    """One albedo layer over the target, whole-image; `(image, tinted_detail)` or None.

    The three branches are the ones the per-pixel loop below takes, in the same order:
    a channel-local detail dye, a modulation behind the RGB selector, and the plain
    tinted blend.
    """

    numpy = numpy_module()
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
    result = QImage(width, height, target_format)
    if target_format == QImage.Format.Format_RGBA8888:
        result_view, result_stride = _image_rgba8888_write_view(result, width, height)
        result_channels = 4
    else:
        result_view, result_stride = _image_rgb888_write_view(result, width, height)
        result_channels = 3
    if base_view is None or layer_view is None or result_view is None or (not mask_rgba.isNull() and mask_view is None):
        return None
    tinted_detail = False
    dye_values = None
    if role == "detail" and tint:
        dye_values = numpy.array([float(value) for value in tint[:3]], dtype=numpy.float64)
        tinted_detail = True
    tint_values = (
        numpy.array([float(value) for value in tint[:3]], dtype=numpy.float64)
        if tint
        else None
    )
    try:
        for row_start in range(0, height, _NUMPY_ROW_CHUNK):
            _raise_if_material_combiner_cancelled(cancelled)
            row_count = min(_NUMPY_ROW_CHUNK, height - row_start)
            base_bytes = _numpy_rgba_byte_rows(
                numpy, base_view, base_stride, width, row_start, row_count
            )
            base = (
                base_bytes.astype(numpy.float32) / numpy.float32(255.0)
            ).astype(numpy.float64)
            over = _numpy_rgba_row_chunk(
                numpy, layer_view, layer_stride, width, row_start, row_count
            )
            if mask_view is None:
                mask_alpha = numpy.ones((row_count, width), dtype=numpy.float64)
            else:
                mask_alpha = _numpy_rgba_row_chunk(
                    numpy, mask_view, mask_stride, width, row_start, row_count
                )[:, :, _LAYER_CHANNEL_INDEX.get(channel, 0)]
            alpha = numpy.clip(float(weight) * mask_alpha, 0.0, 1.0)[:, :, None]
            red, green, blue = over[:, :, 0], over[:, :, 1], over[:, :, 2]
            if dye_values is not None:
                dye_strength = (
                    _clamp(float(tint[3])) if len(tint) >= 4 else 1.0
                )
                alpha = alpha * dye_strength
                luma = numpy.clip((0.299 * red) + (0.587 * green) + (0.114 * blue), 0.0, 1.0)
                modulation = (0.82 + (0.36 * luma))[:, :, None]
                dye = numpy.clip(dye_values * modulation, 0.0, 1.0)
                out = (base[:, :, :3] * (1.0 - alpha)) + (dye * alpha)
            elif color_blending_seed_applied and role in {"grime", "layer", "damage"}:
                luma = numpy.clip((0.299 * red) + (0.587 * green) + (0.114 * blue), 0.0, 1.0)
                modulation = (0.82 + (0.36 * luma))[:, :, None]
                factor = (1.0 - alpha) + (modulation * alpha)
                out = numpy.clip(base[:, :, :3] * factor, 0.0, 1.0)
            else:
                overlay = over[:, :, :3]
                if tint_values is not None:
                    overlay = overlay * tint_values
                out = (base[:, :, :3] * (1.0 - alpha)) + (numpy.clip(overlay, 0.0, 1.0) * alpha)
            result_bytes = _numpy_write_row_chunk(
                numpy,
                result_view,
                result_stride,
                width,
                row_start,
                row_count,
                result_channels,
            )
            result_bytes[:, :, :3] = _numpy_unit_bytes(numpy, out)
            if result_channels == 4:
                result_bytes[:, :, 3] = base_bytes[:, :, 3] if preserve_base_alpha else 255
    except (BufferError, MemoryError, TypeError, ValueError):
        return None
    return result, tinted_detail


def _vectorized_spec_gloss_albedo(spec_source, base_source, width, height, preserve_base_alpha, cancelled):
    spec_rgba = spec_source.convertToFormat(QImage.Format.Format_RGBA8888)
    base_rgba = base_source.convertToFormat(QImage.Format.Format_RGBA8888) if not base_source.isNull() else QImage()
    target_format = (
        QImage.Format.Format_RGBA8888
        if preserve_base_alpha
        else QImage.Format.Format_RGB888
    )
    target = QImage(width, height, target_format)
    numpy = numpy_module()
    spec_view, spec_stride = _image_rgba8888_view(
        spec_rgba,
        width,
        height,
    )
    base_view, base_stride = _image_rgba8888_view(
        base_rgba,
        width,
        height,
    )
    if preserve_base_alpha:
        target_view, target_stride = _image_rgba8888_write_view(
            target,
            width,
            height,
        )
        target_channels = 4
    else:
        target_view, target_stride = _image_rgb888_write_view(
            target,
            width,
            height,
        )
        target_channels = 3
    vectorized = bool(
        numpy is not None
        and spec_view is not None
        and target_view is not None
        and (base_rgba.isNull() or base_view is not None)
    )
    if vectorized:
        try:
            for row_start in range(0, height, 32):
                _raise_if_material_combiner_cancelled(cancelled)
                row_count = min(32, height - row_start)
                shape = (row_count, width, 4)
                spec_bytes = numpy.ndarray(
                    shape,
                    dtype=numpy.uint8,
                    buffer=spec_view,
                    offset=row_start * spec_stride,
                    strides=(spec_stride, 4, 1),
                )
                spec_array = (
                    spec_bytes.astype(numpy.float32)
                    / numpy.float32(255.0)
                ).astype(numpy.float64)
                if base_view is None:
                    base_bytes = None
                    base_rgb = numpy.zeros(
                        (row_count, width, 3),
                        dtype=numpy.float64,
                    )
                else:
                    base_bytes = numpy.ndarray(
                        shape,
                        dtype=numpy.uint8,
                        buffer=base_view,
                        offset=row_start * base_stride,
                        strides=(base_stride, 4, 1),
                    )
                    base_array = (
                        base_bytes.astype(numpy.float32)
                        / numpy.float32(255.0)
                    ).astype(numpy.float64)
                    base_rgb = base_array[:, :, :3]
                spec_rgb = spec_array[:, :, :3]
                spec_luma = (
                    (0.2126 * spec_rgb[:, :, 0])
                    + (0.7152 * spec_rgb[:, :, 1])
                    + (0.0722 * spec_rgb[:, :, 2])
                )
                base_luma = (
                    (0.2126 * base_rgb[:, :, 0])
                    + (0.7152 * base_rgb[:, :, 1])
                    + (0.0722 * base_rgb[:, :, 2])
                )
                use_specular_color = spec_luma > numpy.maximum(
                    base_luma * 1.20,
                    0.08,
                )
                spec_weight = numpy.clip(
                    0.72 + (spec_array[:, :, 3] * 0.38),
                    0.72,
                    1.08,
                )
                highlighted = numpy.maximum(
                    base_rgb,
                    spec_rgb * spec_weight[:, :, None],
                )
                output_rgb = numpy.where(
                    use_specular_color[:, :, None],
                    highlighted,
                    base_rgb,
                )
                target_array = numpy.ndarray(
                    (row_count, width, target_channels),
                    dtype=numpy.uint8,
                    buffer=target_view,
                    offset=row_start * target_stride,
                    strides=(target_stride, target_channels, 1),
                )
                target_array[:, :, :3] = to_byte_array(output_rgb)
                if target_channels == 4:
                    target_array[:, :, 3] = (
                        base_bytes[:, :, 3]
                        if base_bytes is not None
                        else 255
                    )
        except (BufferError, MemoryError, TypeError, ValueError):
            vectorized = False
    return spec_rgba, base_rgba, target, target_format, vectorized


def _generate_spec_gloss_preview_albedo_map(
    base_image: QImage,
    spec_gloss_image: QImage,
    output_dir: Path,
    stem: str,
    *,
    flip_vertical: bool,
    max_dimension: int,
    prefer_largest_source_domain: bool = False,
    preserve_base_alpha: bool = False,
    cancelled: Callable[[], bool] | None = None,
) -> Tuple[str, str]:
    _raise_if_material_combiner_cancelled(cancelled)
    spec_source = _support_source_image(spec_gloss_image, flip_vertical=flip_vertical, max_dimension=max_dimension)
    if spec_source.isNull():
        return "", ""
    base_source = _support_source_image(base_image, flip_vertical=flip_vertical, max_dimension=max_dimension)
    if prefer_largest_source_domain:
        target_size = _largest_meaningful_image_size(
            (spec_source, base_source),
            max_dimension=max_dimension,
        )
        width = int(target_size.width())
        height = int(target_size.height())
        if int(spec_source.width()) != width or int(spec_source.height()) != height:
            spec_source = spec_source.scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    else:
        width = int(spec_source.width())
        height = int(spec_source.height())
    if width <= 0 or height <= 0:
        return "", ""
    if not base_source.isNull() and (int(base_source.width()) != width or int(base_source.height()) != height):
        base_source = base_source.scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    (
        spec_rgba, base_rgba, target, target_format, vectorized,
    ) = _vectorized_spec_gloss_albedo(
        spec_source, base_source, width, height, preserve_base_alpha, cancelled,
    )
    if not vectorized:
        target = QImage(width, height, target_format)
        for y in range(height):
            _raise_if_material_combiner_cancelled(cancelled)
            for x in range(width):
                spec = spec_rgba.pixelColor(x, y)
                base = base_rgba.pixelColor(x, y) if not base_rgba.isNull() else QColor(0, 0, 0)
                gloss = spec.alphaF()
                spec_r, spec_g, spec_b = spec.redF(), spec.greenF(), spec.blueF()
                base_r, base_g, base_b = base.redF(), base.greenF(), base.blueF()
                spec_luma = (0.2126 * spec_r) + (0.7152 * spec_g) + (0.0722 * spec_b)
                base_luma = (0.2126 * base_r) + (0.7152 * base_g) + (0.0722 * base_b)
                if spec_luma <= max(base_luma * 1.20, 0.08):
                    out_r, out_g, out_b = base_r, base_g, base_b
                else:
                    spec_weight = _clamp(0.72 + (gloss * 0.38), 0.72, 1.08)
                    out_r = max(base_r, spec_r * spec_weight)
                    out_g = max(base_g, spec_g * spec_weight)
                    out_b = max(base_b, spec_b * spec_weight)
                target.setPixelColor(
                    x,
                    y,
                    QColor(
                        _byte(out_r),
                        _byte(out_g),
                        _byte(out_b),
                        base.alpha() if preserve_base_alpha and not base_rgba.isNull() else 255,
                    ),
                )
    _raise_if_material_combiner_cancelled(cancelled)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{stem}_spec_gloss_albedo.png"
    if not _save_generated_png(target, output_path):
        return "", ""
    return _local_file_url(output_path), "albedo synthesized:specular-glossiness color"


def _image_reader(source_url: str, *, max_dimension: int = 0) -> QImage:
    source_path = _source_url_local_path(source_url)
    if not source_path:
        return QImage()
    reader = QImageReader(source_path)
    reader.setAutoTransform(True)
    limit = max(0, int(max_dimension or 0))
    if limit > 0:
        size = reader.size()
        if size.isValid() and max(int(size.width()), int(size.height())) > limit:
            target = size.scaled(limit, limit, Qt.KeepAspectRatio)
            if target.width() > 0 and target.height() > 0:
                reader.setScaledSize(target)
    image = reader.read()
    device = reader.device()
    if device is not None:
        device.close()
    if not image.isNull():
        return image
    fallback = _image_from_file_bytes_with_retry(source_path)
    if fallback.isNull() or limit <= 0:
        return fallback
    target = fallback.size().scaled(limit, limit, Qt.KeepAspectRatio)
    if fallback.size() == target or target.isEmpty():
        return fallback
    return fallback.scaled(target, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def _image_from_file_bytes_with_retry(source_path: str) -> QImage:
    """Recover valid images from brief file-publication or decoder races."""

    fallback = QImage()
    # DDS payloads have no Qt decoder in this pipeline. They may still arrive
    # here because the resident renderer packages the authoritative DDS while
    # the combiner handles its decoded layer companions. One immediate probe is
    # useful; publication-race sleeps can never make Qt support DDS.
    retry_delays = (
        ()
        if Path(source_path).suffix.casefold() == ".dds"
        else _IMAGE_BYTE_DECODE_RETRY_DELAYS_SECONDS
    )
    for attempt in range(len(retry_delays) + 1):
        try:
            payload = Path(source_path).read_bytes()
        except OSError:
            payload = b""
        if payload:
            fallback = QImage.fromData(payload)
            if not fallback.isNull():
                return fallback
        if attempt < len(retry_delays):
            time.sleep(retry_delays[attempt])
    return fallback


def _prepare_image(
    image: QImage,
    output_dir: Path,
    stem: str,
    *,
    flip_vertical: bool,
    force_opaque: bool,
    max_dimension: int = 0,
) -> Tuple[str, str]:
    if image.isNull():
        return "", ""
    if max_dimension > 0:
        width = int(image.width())
        height = int(image.height())
        longest = max(width, height)
        if longest > int(max_dimension):
            target = QSize(width, height).scaled(int(max_dimension), int(max_dimension), Qt.KeepAspectRatio)
            if target.width() > 0 and target.height() > 0:
                image = image.scaled(target, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    image = image.convertToFormat(QImage.Format.Format_RGB888 if force_opaque else QImage.Format.Format_RGBA8888)
    if image.isNull():
        return "", ""
    if flip_vertical:
        image = image.flipped(Qt.Orientation.Vertical)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{stem}.png"
    if not _save_generated_png(image, output_path):
        return "", ""
    note = f"prepared:{output_path.name}"
    if flip_vertical:
        note += "; mirrored-v"
    if force_opaque:
        note += "; opaque-rgb"
    return _local_file_url(output_path), note


def _support_source_image(
    image: QImage,
    *,
    flip_vertical: bool,
    max_dimension: int,
) -> QImage:
    if image.isNull():
        return QImage()
    source = image.convertToFormat(QImage.Format.Format_RGBA8888)
    if source.isNull():
        return QImage()
    limit = max(0, int(max_dimension or 0))
    if limit > 0:
        width = int(source.width())
        height = int(source.height())
        longest = max(width, height)
        if longest > limit:
            target = QSize(width, height).scaled(limit, limit, Qt.KeepAspectRatio)
            if target.width() > 0 and target.height() > 0:
                source = source.scaled(target, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    if flip_vertical:
        source = source.flipped(Qt.Orientation.Vertical)
    return source


def _image_rgba8888_view(image: QImage, width: int, height: int) -> Tuple[Optional[memoryview], int]:
    if image.isNull() or width <= 0 or height <= 0:
        return None, 0
    try:
        stride = int(image.bytesPerLine())
        view = memoryview(image.constBits())
    except (BufferError, TypeError, ValueError, RuntimeError):
        return None, 0
    if stride < width * 4 or len(view) < stride * height:
        return None, 0
    return view, stride


def _image_rgb888_write_view(image: QImage, width: int, height: int) -> Tuple[Optional[memoryview], int]:
    if image.isNull() or width <= 0 or height <= 0:
        return None, 0
    try:
        stride = int(image.bytesPerLine())
        view = memoryview(image.bits())
    except (BufferError, TypeError, ValueError, RuntimeError):
        return None, 0
    if stride < width * 3 or len(view) < stride * height or view.readonly:
        return None, 0
    return view, stride


def _image_rgba8888_write_view(image: QImage, width: int, height: int) -> Tuple[Optional[memoryview], int]:
    """Writable view for layer maps that carry mask coverage in alpha."""

    if image.isNull() or width <= 0 or height <= 0:
        return None, 0
    try:
        stride = int(image.bytesPerLine())
        view = memoryview(image.bits())
    except (BufferError, TypeError, ValueError, RuntimeError):
        return None, 0
    if stride < width * 4 or len(view) < stride * height or view.readonly:
        return None, 0
    return view, stride


def _rgba8888_mask_alpha(
    view: memoryview,
    stride: int,
    x: int,
    y: int,
    *,
    channel: str,
) -> float:
    offset = (y * stride) + (x * 4)
    channel_index = _LAYER_CHANNEL_INDEX.get(channel, 0)
    try:
        return _clamp(float(view[offset + channel_index]) / 255.0)
    except (IndexError, TypeError, ValueError):
        return 1.0


def _image_luma_range(
    image: QImage,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> Tuple[float, float, float]:
    _raise_if_material_combiner_cancelled(cancelled)
    if image.isNull():
        return 0.0, 0.0, 0.0
    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    width = int(converted.width())
    height = int(converted.height())
    if width <= 0 or height <= 0:
        return 0.0, 0.0, 0.0
    values: list[float] = []
    step = max(1, int(math.sqrt(max(1, (width * height) // 8192))))
    for y in range(0, height, step):
        _raise_if_material_combiner_cancelled(cancelled)
        for x in range(0, width, step):
            color = converted.pixelColor(x, y)
            values.append((0.2126 * color.redF()) + (0.7152 * color.greenF()) + (0.0722 * color.blueF()))
    if not values:
        return 0.0, 0.0, 0.0
    values.sort()
    low = values[int((len(values) - 1) * 0.05)]
    high = values[int((len(values) - 1) * 0.95)]
    return low, high, max(0.0, high - low)


def _image_exceeds_dimension(image: QImage, max_dimension: int) -> bool:
    if image.isNull() or max_dimension <= 0:
        return False
    return max(int(image.width()), int(image.height())) > int(max_dimension)


def _numpy_module():
    """Return numpy if importable, else ``None`` so callers fall back."""

    try:
        import numpy
    except Exception:
        return None
    return numpy


def _numpy_rgba_byte_rows(
    np,
    view: memoryview,
    stride: int,
    width: int,
    row_start: int,
    row_count: int,
):
    """Zero-copy RGBA8888 bytes for a bounded row tile."""

    return np.ndarray(
        (row_count, width, 4),
        dtype=np.uint8,
        buffer=view,
        offset=row_start * stride,
        strides=(stride, 4, 1),
    )


def _numpy_rgba_row_chunk(
    np,
    view: memoryview,
    stride: int,
    width: int,
    row_start: int,
    row_count: int,
):
    """Float64 RGBA for one row tile, matching QColor's float32 decode."""

    rows = _numpy_rgba_byte_rows(np, view, stride, width, row_start, row_count)
    return (rows.astype(np.float32) / np.float32(255.0)).astype(np.float64)


def _numpy_write_row_chunk(
    np,
    view: memoryview,
    stride: int,
    width: int,
    row_start: int,
    row_count: int,
    channels: int,
):
    """Zero-copy writable RGB/RGBA bytes for a bounded row tile."""

    return np.ndarray(
        (row_count, width, channels),
        dtype=np.uint8,
        buffer=view,
        offset=row_start * stride,
        strides=(stride, channels, 1),
    )


def _numpy_unit_bytes(np, values):
    return np.clip(np.rint(np.clip(values, 0.0, 1.0) * 255.0), 0, 255).astype(np.uint8)


def _apply_vectorized_external_factors(np, external_factors, ao, roughness, metalness, specular):
    has_external_factors = bool(getattr(external_factors, "input_present", False))
    factor_mode = str(getattr(external_factors, "mode", "") or "")
    roughness_factor = getattr(external_factors, "roughness_factor", None)
    metallic_factor = getattr(external_factors, "metallic_factor", None)
    glossiness_factor = getattr(external_factors, "glossiness_factor", None)
    specular_factor = getattr(external_factors, "specular_factor", None)
    specular_color = float(getattr(external_factors, "specular_color", 0.0) or 0.0)
    occlusion_strength = getattr(external_factors, "occlusion_strength", None)
    if has_external_factors:
        if factor_mode == "metallic_roughness":
            if roughness_factor is not None:
                roughness = np.clip(roughness * float(roughness_factor), 0.0, 1.0)
            if metallic_factor is not None:
                metalness = np.clip(metalness * float(metallic_factor), 0.0, 1.0)
        elif factor_mode in {"specular_glossiness", "glossiness"}:
            if glossiness_factor is not None:
                glossiness = np.clip((1.0 - roughness) * float(glossiness_factor), 0.0, 1.0)
                roughness = np.clip(1.0 - glossiness, 0.04, 0.98)
            if specular_factor is not None:
                specular = np.clip(specular * float(specular_factor), 0.0, 1.0)
            if specular_color > 0.0:
                specular = np.clip(specular * specular_color, 0.0, 1.0)
        elif factor_mode in {"specular", "clearcoat", "sheen"}:
            if specular_factor is not None:
                specular = np.clip(specular * float(specular_factor), 0.0, 1.0)
            if specular_color > 0.0:
                specular = np.clip(specular * specular_color, 0.0, 1.0)
        if occlusion_strength is not None:
            ao = np.clip(1.0 + (ao - 1.0) * float(occlusion_strength), 0.45, 1.0)
        ao = np.clip(ao, 0.45, 1.0)
        roughness = np.clip(roughness, 0.04, 1.0)
        metalness = np.clip(metalness, 0.0, 1.0)
        specular = np.clip(specular, 0.0, 1.0)
    return ao, roughness, metalness, specular


def _vectorised_material_maps(
    *,
    mode: str,
    source_view: memoryview,
    source_stride: int,
    width: int,
    height: int,
    mask_view: Optional[memoryview],
    mask_stride: int,
    mask_channel: str,
    effective_layer_weight: float,
    has_mask: bool,
    external_factors: object,
    force_nonmetal_skin: bool,
    apply_sidecar_hints: bool,
    metallic_hint: float,
    roughness_hint: float,
    specular_hint: float,
    force_nonmetal_surface: bool,
    preserve_authored_metal_islands: bool,
    surface_category: str,
    emit: Tuple[bool, bool, bool, bool],
    views: Tuple[Optional[memoryview], ...],
    strides: Tuple[int, ...],
    cancelled: Callable[[], bool] | None = None,
) -> Optional[Tuple[float, float, float]]:
    """Decode and write every slot in bounded row tiles, matching the scalar loop.

    Returns ``(metal_peak, spec_peak, contribution_peak)``, or ``None`` when this
    input needs the scalar path.
    """

    affine = affine_decode_mode_terms(mode)
    if affine is None:
        return None
    np = _numpy_module()
    if np is None:
        return None

    metal_cap, spec_cap, roughness_floor = _nonmetal_response_limits(surface_category)
    mask_channel_index = _LAYER_CHANNEL_INDEX.get(mask_channel, 0)
    metal_peak = 0.0
    spec_peak = 0.0
    contribution_peak = 1.0 if has_mask is False else 0.0

    try:
        for row_start in range(0, height, _NUMPY_ROW_CHUNK):
            _raise_if_material_combiner_cancelled(cancelled)
            row_count = min(_NUMPY_ROW_CHUNK, height - row_start)
            source = _numpy_rgba_row_chunk(
                np, source_view, source_stride, width, row_start, row_count
            )
            if mode == "specular":
                # This newly accelerated mode previously decoded bytes directly
                # to doubles. Keep that precision for identical output texels.
                source = _numpy_rgba_byte_rows(
                    np, source_view, source_stride, width, row_start, row_count,
                ).astype(np.float64) / 255.0
            r, g, b, a = source[..., 0], source[..., 1], source[..., 2], source[..., 3]
            peak = np.maximum(np.maximum(r, g), np.maximum(b, a))
            minimum = np.minimum(np.minimum(r, g), np.minimum(b, a))
            terms = {
                "r": r,
                "g": g,
                "b": b,
                "a": a,
                "b_minus_18": np.maximum(0.0, b - 0.18),
                "rgb_peak": np.maximum(np.maximum(r, g), b),
                "g_or_average": np.maximum(g, (r * 0.3333) + (g * 0.3333) + (b * 0.3334)),
                "variance": np.maximum(peak - minimum, 0.0),
                "average": (r * 0.3333) + (g * 0.3333) + (b * 0.3334),
                "one": np.ones_like(r),
            }

            def slot(name: str):
                term, offset, gain, low, high = affine[name]
                return np.clip(offset + gain * terms[term], low, high)

            ao = slot("ao")
            roughness = slot("roughness")
            metalness = slot("metalness")
            specular = slot("specular")

            ao, roughness, metalness, specular = _apply_vectorized_external_factors(np, external_factors, ao, roughness, metalness, specular)

            source_metalness = metalness
            if force_nonmetal_skin:
                metalness = np.zeros_like(metalness)
                specular = np.minimum(specular, 0.42)
            elif apply_sidecar_hints:
                if metallic_hint > 0.02:
                    metalness = np.maximum(metalness, metallic_hint * 0.42)
                    specular = np.maximum(specular, 0.14 + metallic_hint * 0.32)
                if roughness_hint > 0.02:
                    roughness = np.clip((roughness * 0.72) + (roughness_hint * 0.28), 0.04, 0.98)
                if specular_hint > 0.02:
                    specular = np.maximum(specular, specular_hint * 0.58)
                ao = np.clip(ao, 0.45, 1.0)
                roughness = np.clip(roughness, 0.04, 1.0)
                metalness = np.clip(metalness, 0.0, 1.0)
                specular = np.clip(specular, 0.0, 1.0)

            if force_nonmetal_surface:
                limited = np.ones_like(metalness, dtype=bool)
                if preserve_authored_metal_islands:
                    limited = source_metalness < 0.35
                metalness = np.where(
                    limited,
                    np.minimum(np.clip(metalness, 0.0, 1.0), metal_cap),
                    metalness,
                )
                specular = np.where(
                    limited,
                    np.minimum(np.clip(specular, 0.0, 1.0), spec_cap),
                    specular,
                )
                roughness = np.where(
                    limited,
                    np.maximum(np.clip(roughness, 0.0, 1.0), roughness_floor),
                    roughness,
                )

            if mask_view is not None:
                mask = _numpy_rgba_row_chunk(
                    np, mask_view, mask_stride, width, row_start, row_count
                )
                if mode == "specular":
                    mask = _numpy_rgba_byte_rows(
                        np, mask_view, mask_stride, width, row_start, row_count,
                    ).astype(np.float64) / 255.0
                coverage = np.clip(
                    mask[..., mask_channel_index] * effective_layer_weight,
                    0.0,
                    1.0,
                )
                contribution_peak = max(contribution_peak, float(coverage.max()))
            else:
                coverage = np.ones_like(r)

            metal_peak = max(metal_peak, float((metalness * coverage).max()))
            spec_peak = max(spec_peak, float((specular * coverage).max()))
            coverage_bytes = _numpy_unit_bytes(np, coverage)
            for emit_slot, view, stride, values in zip(
                emit, views, strides, (ao, roughness, metalness, specular)
            ):
                if not emit_slot or view is None:
                    continue
                grey = _numpy_unit_bytes(np, values)
                output = _numpy_write_row_chunk(
                    np, view, stride, width, row_start, row_count, 4
                )
                output[:, :, :3] = grey[:, :, None]
                output[:, :, 3] = coverage_bytes
    except (BufferError, MemoryError, TypeError, ValueError):
        return None

    return metal_peak, spec_peak, contribution_peak


def _has_authoritative_pac_layer_metal_response(
    input_item: Optional[PreviewMaterialTextureInput],
    decode_mode: str,
) -> bool:
    if input_item is None:
        return False
    return bool(
        str(getattr(input_item, "sidecar_kind", "") or "").strip().lower()
        == "pac_xml"
        and str(getattr(input_item, "binding_authority", "") or "").strip().lower()
        == "authoritative"
        and str(getattr(input_item, "binding_disposition", "") or "").strip().lower()
        == "layer_material_response"
        and str(getattr(input_item, "source_kind", "") or "").strip().lower()
        == "crimson_layer_material_response"
        and str(decode_mode or "").strip().lower()
        in {"standard_v2_material", "standard_v2_specular"}
        and _texture_rule_for_input(input_item)
        # Cloth garments routinely carry metal studs, buckles and trim, so a
        # cloth rule must not discard an authoritatively authored metal layer the
        # way it should for skin and hair.
        in {"standard", "standard_v2", "emissive_v2", "cloth", "cloth_v2"}
    )


def _resolve_material_surface_hints(decode_mode, input_item, surface_category, force_nonmetal_surface):
    mode = str(decode_mode or "").strip().lower()
    shader_rule = _texture_rule_for_input(input_item) if input_item is not None else ""
    force_nonmetal_skin = bool(shader_rule == "skin" or mode in {"skin_material", "skin_detail_mask"})
    resolved_surface_category = str(surface_category or "").strip().lower() or _material_surface_category(input_item)
    resolved_force_nonmetal_surface = bool(
        surface_category in _NONMETAL_RESPONSE_LIMITS
        and not force_nonmetal_skin
        and not _strong_metallic_override(input_item)
    )
    if force_nonmetal_surface is not None:
        resolved_force_nonmetal_surface = bool(force_nonmetal_surface)
    else:
        resolved_force_nonmetal_surface = bool(
            resolved_surface_category in _NONMETAL_RESPONSE_LIMITS
            and not force_nonmetal_skin
            and not _strong_metallic_override(input_item)
        )
    force_nonmetal_surface = resolved_force_nonmetal_surface
    surface_category = resolved_surface_category
    preserve_authored_metal_islands = _has_authoritative_pac_layer_metal_response(
        input_item,
        decode_mode,
    )
    apply_sidecar_hints = bool(
        input_item is not None
        and not force_nonmetal_skin
        and shader_rule in {"standard_v2", "emissive_v2", "cloth_v2", "cloth", "standard", "static_multitextured", "static_standard"}
    )
    metallic_hint = 0.0
    roughness_hint = 0.0
    specular_hint = 0.0
    if apply_sidecar_hints and input_item is not None:
        channel = _layer_channel(input_item)
        metallic_hint = _material_parameter_channel_hint(input_item, channel, "metallic", "metalness", "scratchmetallic")
        roughness_hint = _material_parameter_channel_hint(input_item, channel, "roughness", "scratchroughness")
        specular_hint = _material_parameter_hint(input_item, "specular", "specularamount")
    return mode, force_nonmetal_skin, surface_category, force_nonmetal_surface, preserve_authored_metal_islands, apply_sidecar_hints, metallic_hint, roughness_hint, specular_hint


def _requested_material_map_output_flags(decode_mode, requested_slots):
    emit_occlusion, emit_roughness, emit_metalness, emit_specular = _material_decode_output_flags(decode_mode)
    if requested_slots is not None:
        normalized_requested_slots = {
            "metalness" if str(slot or "").strip().casefold() == "metallic" else str(slot or "").strip().casefold()
            for slot in requested_slots
        }
        emit_occlusion = emit_occlusion and "occlusion" in normalized_requested_slots
        emit_roughness = emit_roughness and "roughness" in normalized_requested_slots
        emit_metalness = emit_metalness and "metalness" in normalized_requested_slots
        emit_specular = emit_specular and "specular" in normalized_requested_slots
    return emit_occlusion, emit_roughness, emit_metalness, emit_specular


def _generate_material_maps(
    image: QImage,
    output_dir: Path,
    stem: str,
    *,
    decode_mode: str,
    input_item: Optional[PreviewMaterialTextureInput] = None,
    surface_category: str = "",
    force_nonmetal_surface: Optional[bool] = None,
    layer_mask: Optional[QImage] = None,
    layer_mask_channel: str = "",
    layer_weight: float = 1.0,
    flip_vertical: bool,
    max_dimension: int,
    prefer_largest_source_domain: bool = False,
    requested_slots: frozenset[str] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> Tuple[Tuple[str, ...], Tuple[str, str, str, str]]:
    _raise_if_material_combiner_cancelled(cancelled)
    if image.isNull():
        return (), ("", "", "", "")
    source = _support_source_image(image, flip_vertical=flip_vertical, max_dimension=max_dimension)
    if source.isNull():
        return (), ("", "", "", "")
    source = _apply_pac_layer_sampling_transform(
        source,
        input_item,
        cancelled=cancelled,
    )
    mask_source = QImage()
    if layer_mask is not None and not layer_mask.isNull():
        mask_source = _support_source_image(layer_mask, flip_vertical=flip_vertical, max_dimension=max_dimension)
    if prefer_largest_source_domain and not mask_source.isNull():
        target_size = _largest_meaningful_image_size(
            (source, mask_source),
            max_dimension=max_dimension,
        )
        width = int(target_size.width())
        height = int(target_size.height())
        if width <= 0 or height <= 0:
            return (), ("", "", "", "")
        if int(source.width()) != width or int(source.height()) != height:
            source = source.scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    else:
        width = int(source.width())
        height = int(source.height())
    if width <= 0 or height <= 0:
        return (), ("", "", "", "")
    source_view, source_stride = _image_rgba8888_view(source, width, height)
    if source_view is None:
        return (), ("", "", "", "")
    if not mask_source.isNull() and (
        int(mask_source.width()) != width or int(mask_source.height()) != height
    ):
        mask_source = mask_source.scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    if not mask_source.isNull():
        mask_source = mask_source.convertToFormat(QImage.Format.Format_RGBA8888)
    mask_view: Optional[memoryview] = None
    mask_stride = 0
    if not mask_source.isNull():
        mask_view, mask_stride = _image_rgba8888_view(mask_source, width, height)
        if mask_view is None:
            mask_source = QImage()
            mask_stride = 0
    mask_channel = str(layer_mask_channel or "r").strip().lower()
    effective_layer_weight = _clamp(layer_weight, 0.0, 1.0)
    if not mask_source.isNull() and effective_layer_weight <= 0.001:
        return (), ("", "", "", "")
    emit_occlusion, emit_roughness, emit_metalness, emit_specular = _requested_material_map_output_flags(decode_mode, requested_slots)
    if not any((emit_occlusion, emit_roughness, emit_metalness, emit_specular)):
        return (), ("", "", "", "")
    # Layer maps are RGBA: RGB carries the decoded value, alpha carries how much
    # of this layer's mask covers the texel.  Baking the uncovered value into RGB
    # instead loses coverage, and the blend step could then only average layers
    # together -- which is what flattened every roughness map toward one constant.
    ao_image = QImage(width, height, QImage.Format.Format_RGBA8888) if emit_occlusion else QImage()
    rough_image = QImage(width, height, QImage.Format.Format_RGBA8888) if emit_roughness else QImage()
    metal_image = QImage(width, height, QImage.Format.Format_RGBA8888) if emit_metalness else QImage()
    spec_image = QImage(width, height, QImage.Format.Format_RGBA8888) if emit_specular else QImage()
    ao_view, ao_stride = _image_rgba8888_write_view(ao_image, width, height) if emit_occlusion else (None, 0)
    rough_view, rough_stride = _image_rgba8888_write_view(rough_image, width, height) if emit_roughness else (None, 0)
    metal_view, metal_stride = _image_rgba8888_write_view(metal_image, width, height) if emit_metalness else (None, 0)
    spec_view, spec_stride = _image_rgba8888_write_view(spec_image, width, height) if emit_specular else (None, 0)
    if (
        (emit_occlusion and ao_view is None)
        or (emit_roughness and rough_view is None)
        or (emit_metalness and metal_view is None)
        or (emit_specular and spec_view is None)
    ):
        return (), ("", "", "", "")
    (
        mode, force_nonmetal_skin, surface_category, force_nonmetal_surface, preserve_authored_metal_islands,
        apply_sidecar_hints, metallic_hint, roughness_hint, specular_hint,
    ) = _resolve_material_surface_hints(
        decode_mode, input_item, surface_category, force_nonmetal_surface,
    )
    metal_peak = 0.0
    spec_peak = 0.0
    contribution_peak = 1.0 if mask_source.isNull() else 0.0
    external_material_factors = _resolve_external_material_factors(input_item, decode_mode)

    # Array fast path.  The per-texel work is elementwise arithmetic over scalar
    # parameters, so it vectorises exactly -- and it is what lets support maps
    # keep their resolution instead of being capped small enough for a Python
    # loop to finish.  Restricted to modes whose response is the shared affine
    # table. External material factors are scalar multipliers over those arrays,
    # so they stay in this path instead of forcing one Python call per texel.
    fast = _vectorised_material_maps(
        mode=mode,
        source_view=source_view,
        source_stride=source_stride,
        width=width,
        height=height,
        mask_view=mask_view,
        mask_stride=mask_stride,
        mask_channel=mask_channel,
        effective_layer_weight=effective_layer_weight,
        has_mask=not mask_source.isNull(),
        external_factors=external_material_factors,
        force_nonmetal_skin=force_nonmetal_skin,
        apply_sidecar_hints=apply_sidecar_hints,
        metallic_hint=metallic_hint,
        roughness_hint=roughness_hint,
        specular_hint=specular_hint,
        force_nonmetal_surface=force_nonmetal_surface,
        preserve_authored_metal_islands=preserve_authored_metal_islands,
        surface_category=surface_category,
        emit=(emit_occlusion, emit_roughness, emit_metalness, emit_specular),
        views=(ao_view, rough_view, metal_view, spec_view),
        strides=(ao_stride, rough_stride, metal_stride, spec_stride),
        cancelled=cancelled,
    )
    if fast is not None:
        metal_peak, spec_peak, contribution_peak = fast
        if contribution_peak <= 0.015:
            return (), ("", "", "", "")
        del source_view
        if mask_view is not None:
            del mask_view
        for released in (ao_view, rough_view, metal_view, spec_view):
            if released is not None:
                del released
        return _save_material_maps(
            output_dir,
            stem,
            images=(ao_image, rough_image, metal_image, spec_image),
            metal_peak=metal_peak,
            spec_peak=spec_peak,
            cancelled=cancelled,
        )
    for y in range(height):
        _raise_if_material_combiner_cancelled(cancelled)
        source_row = y * source_stride
        for x in range(width):
            source_offset = source_row + (x * 4)
            ao, roughness, metalness, specular = decode_material_sample(
                float(source_view[source_offset]) / 255.0,
                float(source_view[source_offset + 1]) / 255.0,
                float(source_view[source_offset + 2]) / 255.0,
                float(source_view[source_offset + 3]) / 255.0,
                decode_mode,
            )
            ao, roughness, metalness, specular = _apply_external_material_factors(
                external_material_factors,
                ao,
                roughness,
                metalness,
                specular,
            )
            source_metalness = metalness
            if force_nonmetal_skin:
                metalness = 0.0
                specular = min(specular, 0.42)
            elif apply_sidecar_hints:
                if metallic_hint > 0.02:
                    metalness = max(metalness, metallic_hint * 0.42)
                    specular = max(specular, 0.14 + metallic_hint * 0.32)
                if roughness_hint > 0.02:
                    roughness = _clamp((roughness * 0.72) + (roughness_hint * 0.28), 0.04, 0.98)
                if specular_hint > 0.02:
                    specular = max(specular, specular_hint * 0.58)
                ao = _clamp(ao, 0.45, 1.0)
                roughness = _clamp(roughness, 0.04, 1.0)
                metalness = _clamp(metalness)
                specular = _clamp(specular)
            if (
                force_nonmetal_surface
                and not (
                    preserve_authored_metal_islands
                    and source_metalness >= 0.35
                )
            ):
                metalness, specular, roughness = _apply_nonmetal_response_limits(
                    surface_category,
                    metalness,
                    specular,
                    roughness,
                )
            coverage = 1.0
            if mask_view is not None:
                coverage = _clamp(
                    _rgba8888_mask_alpha(mask_view, mask_stride, x, y, channel=mask_channel)
                    * effective_layer_weight
                )
                contribution_peak = max(contribution_peak, coverage)
            # Values stay as decoded; coverage rides in alpha so the blend step
            # can composite layers over one another instead of averaging them.
            metal_peak = max(metal_peak, metalness * coverage)
            spec_peak = max(spec_peak, specular * coverage)
            coverage_byte = _byte(coverage)
            if emit_occlusion:
                ao_g = _byte(ao)
                offset = (y * ao_stride) + (x * 4)
                ao_view[offset : offset + 4] = bytes((ao_g, ao_g, ao_g, coverage_byte))
            if emit_roughness:
                rough_g = _byte(roughness)
                offset = (y * rough_stride) + (x * 4)
                rough_view[offset : offset + 4] = bytes((rough_g, rough_g, rough_g, coverage_byte))
            if emit_metalness:
                metal_g = _byte(metalness)
                offset = (y * metal_stride) + (x * 4)
                metal_view[offset : offset + 4] = bytes((metal_g, metal_g, metal_g, coverage_byte))
            if emit_specular:
                spec_g = _byte(specular)
                offset = (y * spec_stride) + (x * 4)
                spec_view[offset : offset + 4] = bytes((spec_g, spec_g, spec_g, coverage_byte))
    if contribution_peak <= 0.015:
        return (), ("", "", "", "")
    del source_view
    if mask_view is not None:
        del mask_view
    if ao_view is not None:
        del ao_view
    if rough_view is not None:
        del rough_view
    if metal_view is not None:
        del metal_view
    if spec_view is not None:
        del spec_view
    return _save_material_maps(
        output_dir,
        stem,
        images=(ao_image, rough_image, metal_image, spec_image),
        metal_peak=metal_peak,
        spec_peak=spec_peak,
        cancelled=cancelled,
    )


def _save_material_maps(
    output_dir: Path,
    stem: str,
    *,
    images: tuple[QImage, QImage, QImage, QImage],
    metal_peak: float,
    spec_peak: float,
    cancelled: Callable[[], bool] | None,
) -> Tuple[Tuple[str, ...], Tuple[str, str, str, str]]:
    _raise_if_material_combiner_cancelled(cancelled)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    slots: list[str] = []
    for slot, generated in zip(("occlusion", "roughness", "metalness", "specular"), images):
        _raise_if_material_combiner_cancelled(cancelled)
        suppressed = (
            generated.isNull()
            or (slot == "metalness" and metal_peak <= 0.015)
            or (slot == "specular" and spec_peak <= 0.015)
        )
        if suppressed:
            paths.append("")
            continue
        output_path = output_dir / f"{stem}_{slot}.png"
        if _save_generated_png(generated, output_path):
            slots.append(slot)
            paths.append(_local_file_url(output_path))
        else:
            paths.append("")
    while len(paths) < 4:
        paths.append("")
    return tuple(slots), tuple(paths[:4])  # type: ignore[return-value]


def _read_generated_map(source_url: str) -> QImage:
    return _image_reader(source_url).convertToFormat(QImage.Format.Format_RGBA8888)


_MATERIAL_SLOT_DEFAULTS = {
    "occlusion": 1.0,
    "roughness": 0.58,
    "metalness": 0.0,
    "specular": 0.04,
}
# Layer means further apart than this describe different materials, not one
# surface, so their average is not a usable fallback for uncovered texels.
_SLOT_LEVEL_AGREEMENT_SPREAD = 0.14


def _coverage_weighted_slot_level(
    layer_views: Sequence[Tuple[int, str, QImage, memoryview, int]],
    width: int,
    height: int,
) -> Optional[float]:
    """Level to extend into texels no layer covers, or ``None`` to keep neutral.

    Layers that agree on a value describe one surface, and extending that value
    into the gaps between their masks is better than dropping to a constant.
    Layers that disagree describe genuinely different materials, and averaging
    them produces a level that belongs to neither -- a metal trim layer pulled a
    quilted cloth helmet from 0.52 down to 0.33 that way.  Sampled on a stride
    because this only characterises the surface; the caller does the real pass.
    """

    step = max(1, min(width, height) // 48)
    means: list[float] = []
    for _priority, _mode, _image, view, stride in layer_views:
        total = 0.0
        weight = 0.0
        for y in range(0, height, step):
            row = y * stride
            for x in range(0, width, step):
                offset = row + (x * 4)
                coverage = float(view[offset + 3]) / 255.0
                if coverage <= 0.0:
                    continue
                total += (float(view[offset]) / 255.0) * coverage
                weight += coverage
        if weight > 0.0:
            means.append(total / weight)
    if not means:
        return None
    if max(means) - min(means) > _SLOT_LEVEL_AGREEMENT_SPREAD:
        return None
    return _clamp(sum(means) / len(means))


def _combine_material_slot_maps(
    slot_name: str,
    layers: Sequence[Tuple[int, str, str]],
    output_dir: Path,
    stem: str,
    *,
    max_dimension: int = 0,
    prefer_largest_source_domain: bool = False,
    cancelled: Callable[[], bool] | None = None,
) -> Tuple[str, str]:
    _raise_if_material_combiner_cancelled(cancelled)
    valid_layers: list[Tuple[int, str, str, QImage]] = []
    for priority, mode, source_url in layers:
        _raise_if_material_combiner_cancelled(cancelled)
        image = _read_generated_map(source_url)
        if image.isNull():
            continue
        valid_layers.append((int(priority), str(mode or "generic"), str(source_url or ""), image))
    if not valid_layers:
        return "", ""
    # Ascending priority: the compositor lays each layer over the ones below it,
    # so the highest-priority layer must be applied last.  A single layer still
    # goes through the composite because its map now carries mask coverage in
    # alpha, and uncovered texels have to resolve to the slot default rather than
    # to whatever value happened to be decoded outside the mask.
    valid_layers.sort(key=lambda item: item[0])

    if prefer_largest_source_domain:
        target_size = _largest_meaningful_image_size(
            tuple(item[3] for item in valid_layers),
            max_dimension=max_dimension,
        )
        base_width = int(target_size.width())
        base_height = int(target_size.height())
    else:
        base_width = int(valid_layers[0][3].width())
        base_height = int(valid_layers[0][3].height())
    if base_width <= 0 or base_height <= 0:
        return "", ""
    normalized_layers: list[Tuple[int, str, QImage]] = []
    for priority, mode, _source_url, image in valid_layers:
        _raise_if_material_combiner_cancelled(cancelled)
        source = image
        if int(source.width()) != base_width or int(source.height()) != base_height:
            source = source.scaled(base_width, base_height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        converted = source.convertToFormat(QImage.Format.Format_RGBA8888)
        if not converted.isNull():
            normalized_layers.append((priority, mode, converted))

    slot = str(slot_name or "").strip().lower()
    target = QImage(base_width, base_height, QImage.Format.Format_RGB888)
    target_view, target_stride = _image_rgb888_write_view(target, base_width, base_height)
    if target_view is None:
        return valid_layers[0][2], valid_layers[0][1]
    layer_views: list[Tuple[int, str, QImage, memoryview, int]] = []
    for priority, mode, image in normalized_layers:
        view, stride = _image_rgba8888_view(image, base_width, base_height)
        if view is not None:
            layer_views.append((priority, mode, image, view, stride))
    if not layer_views:
        return valid_layers[0][2], valid_layers[0][1]
    # Value a texel keeps when no layer covers it.  Specular defaults to the
    # physical dielectric reflectance so an uncovered surface reads as a plain
    # non-metal rather than inheriting a neighbouring layer's gloss.
    slot_default = _MATERIAL_SLOT_DEFAULTS.get(slot, 0.0)
    if slot == "roughness":
        # A fixed 0.58 for uncovered texels was pulling whole submeshes toward
        # mid-roughness: a polished blade whose layers all sit near 0.21 came out
        # at 0.48 because the gaps between layer masks dominated the average.
        # The layers present are the best available description of the surface, so
        # fall back to their coverage-weighted level instead of a constant.
        derived = _coverage_weighted_slot_level(layer_views, base_width, base_height)
        if derived is not None:
            slot_default = derived
    numpy = _numpy_module()
    vectorized = False
    if numpy is not None:
        try:
            target_array = numpy.ndarray(
                (base_height, base_width, 3),
                dtype=numpy.uint8,
                buffer=target_view,
                strides=(target_stride, 3, 1),
            )
            for row_start in range(0, base_height, 32):
                _raise_if_material_combiner_cancelled(cancelled)
                row_count = min(32, base_height - row_start)
                shape = (row_count, base_width)
                combined = numpy.full(shape, slot_default, dtype=numpy.float64)
                covered = numpy.zeros(shape, dtype=numpy.bool_)
                for _priority, _mode, _image, view, stride in layer_views:
                    value = numpy.ndarray(
                        shape,
                        dtype=numpy.uint8,
                        buffer=view,
                        offset=row_start * stride,
                        strides=(stride, 4),
                    ).astype(numpy.float64) / 255.0
                    coverage = numpy.ndarray(
                        shape,
                        dtype=numpy.uint8,
                        buffer=view,
                        offset=(row_start * stride) + 3,
                        strides=(stride, 4),
                    ).astype(numpy.float64) / 255.0
                    active = coverage > 0.0
                    if slot == "occlusion":
                        contribution = (value * coverage) + (1.0 - coverage)
                        overlaid = numpy.where(covered, numpy.minimum(combined, contribution), contribution)
                    else:
                        overlaid = (combined * (1.0 - coverage)) + (value * coverage)
                    combined = numpy.where(active, overlaid, combined)
                    covered |= active
                grey = numpy.rint(numpy.clip(combined, 0.0, 1.0) * 255.0).astype(numpy.uint8)
                target_array[row_start : row_start + row_count, :, :] = grey[:, :, None]
            vectorized = True
        except (BufferError, TypeError, ValueError):
            vectorized = False
    if not vectorized:
        for y in range(base_height):
            _raise_if_material_combiner_cancelled(cancelled)
            target_row = y * target_stride
            for x in range(base_width):
                combined = slot_default
                covered = False
                for _priority, _mode, _image, view, stride in layer_views:
                    offset = (y * stride) + (x * 4)
                    value = _clamp(float(view[offset]) / 255.0)
                    coverage = _clamp(float(view[offset + 3]) / 255.0)
                    if coverage <= 0.0:
                        continue
                    if slot == "occlusion":
                        contribution = (value * coverage) + (1.0 * (1.0 - coverage))
                        combined = contribution if not covered else min(combined, contribution)
                    else:
                        combined = (combined * (1.0 - coverage)) + (value * coverage)
                    covered = True
                grey_byte = _byte(_clamp(combined))
                target_offset = target_row + (x * 3)
                target_view[target_offset : target_offset + 3] = bytes((grey_byte, grey_byte, grey_byte))

    _raise_if_material_combiner_cancelled(cancelled)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{stem}_{slot}.png"
    del target_view
    del layer_views
    if not _save_generated_png(target, output_path):
        return valid_layers[0][2], valid_layers[0][1]
    return _local_file_url(output_path), "+".join(dict.fromkeys(mode for _priority, mode, _image in normalized_layers))
