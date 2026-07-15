"""Material preview combiner image and map generation helpers."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Callable, Optional, Sequence, Tuple

from PySide6.QtCore import QSize, QUrl, Qt
from PySide6.QtGui import QColor, QImage, QImageReader

from cdmw.domain.cancellation import RunCancelled
from cdmw.models import PreviewMaterialTextureInput
from cdmw.rendering.material_combiner_decode import (
    _apply_external_material_factors,
    _material_decode_output_flags,
    decode_material_sample,
)
from cdmw.rendering.material_combiner_rules import (
    _LAYER_CHANNEL_INDEX,
    _NONMETAL_RESPONSE_LIMITS,
    _apply_nonmetal_response_limits,
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
    preserve_base_alpha: bool = False,
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
        source_layers.append((item, prepared.convertToFormat(QImage.Format.Format_RGBA8888)))
    if prepared_base.isNull() and not source_layers and len(neutral_base_color) < 3:
        return "", ""

    if not prepared_base.isNull():
        width = int(prepared_base.width())
        height = int(prepared_base.height())
        target = prepared_base.convertToFormat(
            QImage.Format.Format_RGBA8888 if preserve_base_alpha else QImage.Format.Format_RGB888
        )
        layer_start = 0
    elif len(neutral_base_color) >= 3 and source_layers:
        _first_item, first_image = source_layers[0]
        width = int(first_image.width())
        height = int(first_image.height())
        target = QImage(
            width,
            height,
            QImage.Format.Format_RGBA8888 if preserve_base_alpha else QImage.Format.Format_RGB888,
        )
        red, green, blue = (_byte(float(value)) for value in neutral_base_color[:3])
        target.fill(QColor(red, green, blue))
        layer_start = 0
    else:
        first_item, first_image = source_layers[0]
        width = int(first_image.width())
        height = int(first_image.height())
        target = QImage(
            width,
            height,
            QImage.Format.Format_RGBA8888 if preserve_base_alpha else QImage.Format.Format_RGB888,
        )
        tint = _layer_tint(first_item)
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
        layer_start = 1

    prepared_masks: dict[str, QImage] = {}
    for role, item in mask_inputs.items():
        _raise_if_material_combiner_cancelled(cancelled)
        image = _image_reader(str(getattr(item, "preview_texture_path", "") or ""), max_dimension=max_dimension)
        if image.isNull():
            continue
        prepared = _support_source_image(image, flip_vertical=flip_vertical, max_dimension=max_dimension)
        if prepared.isNull():
            continue
        if int(prepared.width()) != width or int(prepared.height()) != height:
            prepared = prepared.scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        prepared_masks[role] = prepared.convertToFormat(QImage.Format.Format_RGBA8888)

    roles_used: list[str] = []
    has_base = not prepared_base.isNull()
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
        for y in range(height):
            _raise_if_material_combiner_cancelled(cancelled)
            for x in range(width):
                base = target.pixelColor(x, y)
                overlay = layer.pixelColor(x, y)
                alpha = _clamp(weight * _mask_alpha(mask, x, y, channel=channel))
                red = overlay.redF()
                green = overlay.greenF()
                blue = overlay.blueF()
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
    if not target.save(str(output_path), "PNG"):
        return "", ""
    if roles_used:
        note = "albedo synthesized:" + ",".join(roles_used[:6])
    else:
        note = "albedo synthesized:visible layer"
    if len(neutral_base_color) >= 3:
        note += "; neutral_metal_base_synthesized"
    if prepared_base.isNull():
        note += "; no reliable base DDS; no_reliable_full_base_albedo"
    return _local_file_url(output_path), note


def _generate_spec_gloss_preview_albedo_map(
    base_image: QImage,
    spec_gloss_image: QImage,
    output_dir: Path,
    stem: str,
    *,
    flip_vertical: bool,
    max_dimension: int,
    preserve_base_alpha: bool = False,
    cancelled: Callable[[], bool] | None = None,
) -> Tuple[str, str]:
    _raise_if_material_combiner_cancelled(cancelled)
    spec_source = _support_source_image(spec_gloss_image, flip_vertical=flip_vertical, max_dimension=max_dimension)
    if spec_source.isNull():
        return "", ""
    width = int(spec_source.width())
    height = int(spec_source.height())
    if width <= 0 or height <= 0:
        return "", ""
    base_source = _support_source_image(base_image, flip_vertical=flip_vertical, max_dimension=max_dimension)
    if not base_source.isNull() and (int(base_source.width()) != width or int(base_source.height()) != height):
        base_source = base_source.scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    spec_rgba = spec_source.convertToFormat(QImage.Format.Format_RGBA8888)
    base_rgba = base_source.convertToFormat(QImage.Format.Format_RGBA8888) if not base_source.isNull() else QImage()
    target = QImage(
        width,
        height,
        QImage.Format.Format_RGBA8888 if preserve_base_alpha else QImage.Format.Format_RGB888,
    )
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
    if not target.save(str(output_path), "PNG"):
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
    return reader.read()


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
    if not image.save(str(output_path), "PNG"):
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
    cancelled: Callable[[], bool] | None = None,
) -> Tuple[Tuple[str, ...], Tuple[str, str, str, str]]:
    _raise_if_material_combiner_cancelled(cancelled)
    if image.isNull():
        return (), ("", "", "", "")
    source = _support_source_image(image, flip_vertical=flip_vertical, max_dimension=max_dimension)
    if source.isNull():
        return (), ("", "", "", "")
    width = int(source.width())
    height = int(source.height())
    if width <= 0 or height <= 0:
        return (), ("", "", "", "")
    source_view, source_stride = _image_rgba8888_view(source, width, height)
    if source_view is None:
        return (), ("", "", "", "")
    mask_source = QImage()
    if layer_mask is not None and not layer_mask.isNull():
        mask_source = _support_source_image(layer_mask, flip_vertical=flip_vertical, max_dimension=max_dimension)
        if not mask_source.isNull() and (int(mask_source.width()) != width or int(mask_source.height()) != height):
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
    emit_occlusion, emit_roughness, emit_metalness, emit_specular = _material_decode_output_flags(decode_mode)
    ao_image = QImage(width, height, QImage.Format.Format_RGB888) if emit_occlusion else QImage()
    rough_image = QImage(width, height, QImage.Format.Format_RGB888) if emit_roughness else QImage()
    metal_image = QImage(width, height, QImage.Format.Format_RGB888) if emit_metalness else QImage()
    spec_image = QImage(width, height, QImage.Format.Format_RGB888) if emit_specular else QImage()
    ao_view, ao_stride = _image_rgb888_write_view(ao_image, width, height) if emit_occlusion else (None, 0)
    rough_view, rough_stride = _image_rgb888_write_view(rough_image, width, height) if emit_roughness else (None, 0)
    metal_view, metal_stride = _image_rgb888_write_view(metal_image, width, height) if emit_metalness else (None, 0)
    spec_view, spec_stride = _image_rgb888_write_view(spec_image, width, height) if emit_specular else (None, 0)
    if (
        (emit_occlusion and ao_view is None)
        or (emit_roughness and rough_view is None)
        or (emit_metalness and metal_view is None)
        or (emit_specular and spec_view is None)
    ):
        return (), ("", "", "", "")
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
    metal_peak = 0.0
    spec_peak = 0.0
    contribution_peak = 1.0 if mask_source.isNull() else 0.0
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
                input_item,
                decode_mode,
                ao,
                roughness,
                metalness,
                specular,
            )
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
            if force_nonmetal_surface:
                metalness, specular, roughness = _apply_nonmetal_response_limits(
                    surface_category,
                    metalness,
                    specular,
                    roughness,
                )
            if mask_view is not None:
                layer_alpha = _clamp(
                    _rgba8888_mask_alpha(mask_view, mask_stride, x, y, channel=mask_channel)
                    * effective_layer_weight
                )
                contribution_peak = max(contribution_peak, layer_alpha)
                ao = (1.0 * (1.0 - layer_alpha)) + (ao * layer_alpha)
                roughness = (0.58 * (1.0 - layer_alpha)) + (roughness * layer_alpha)
                metalness *= layer_alpha
                specular *= layer_alpha
            metal_peak = max(metal_peak, metalness)
            spec_peak = max(spec_peak, specular)
            if emit_occlusion:
                ao_g = _byte(ao)
                offset = (y * ao_stride) + (x * 3)
                ao_view[offset : offset + 3] = bytes((ao_g, ao_g, ao_g))
            if emit_roughness:
                rough_g = _byte(roughness)
                offset = (y * rough_stride) + (x * 3)
                rough_view[offset : offset + 3] = bytes((rough_g, rough_g, rough_g))
            if emit_metalness:
                metal_g = _byte(metalness)
                offset = (y * metal_stride) + (x * 3)
                metal_view[offset : offset + 3] = bytes((metal_g, metal_g, metal_g))
            if emit_specular:
                spec_g = _byte(specular)
                offset = (y * spec_stride) + (x * 3)
                spec_view[offset : offset + 3] = bytes((spec_g, spec_g, spec_g))
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
    _raise_if_material_combiner_cancelled(cancelled)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    slots: list[str] = []
    for slot, generated in (
        ("occlusion", ao_image),
        ("roughness", rough_image),
        ("metalness", metal_image),
        ("specular", spec_image),
    ):
        _raise_if_material_combiner_cancelled(cancelled)
        if generated.isNull():
            paths.append("")
            continue
        if slot == "metalness" and metal_peak <= 0.015:
            paths.append("")
            continue
        if slot == "specular" and spec_peak <= 0.015:
            paths.append("")
            continue
        output_path = output_dir / f"{stem}_{slot}.png"
        if generated.save(str(output_path), "PNG"):
            slots.append(slot)
            paths.append(_local_file_url(output_path))
        else:
            paths.append("")
    while len(paths) < 4:
        paths.append("")
    return tuple(slots), tuple(paths[:4])  # type: ignore[return-value]


def _read_generated_map(source_url: str) -> QImage:
    return _image_reader(source_url).convertToFormat(QImage.Format.Format_RGBA8888)


def _combine_material_slot_maps(
    slot_name: str,
    layers: Sequence[Tuple[int, str, str]],
    output_dir: Path,
    stem: str,
    *,
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
    valid_layers.sort(key=lambda item: item[0], reverse=True)
    if len(valid_layers) == 1:
        return valid_layers[0][2], valid_layers[0][1]

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
    weight_total = max(1.0, sum(max(1.0, float(priority)) for priority, _mode, _image, _view, _stride in layer_views))
    for y in range(base_height):
        _raise_if_material_combiner_cancelled(cancelled)
        target_row = y * target_stride
        for x in range(base_width):
            values: list[Tuple[float, float]] = []
            for priority, _mode, _image, view, stride in layer_views:
                offset = (y * stride) + (x * 4)
                grey = (
                    (0.2126 * (float(view[offset]) / 255.0))
                    + (0.7152 * (float(view[offset + 1]) / 255.0))
                    + (0.0722 * (float(view[offset + 2]) / 255.0))
                )
                values.append((_clamp(grey), max(1.0, float(priority))))
            if slot == "occlusion":
                combined = 1.0
                for value, _weight in values:
                    combined = min(combined, value)
                combined = _clamp(combined, 0.55, 1.0)
            elif slot == "metalness":
                combined = max(
                    value * _clamp(0.45 + ((weight / 100.0) * 0.55), 0.45, 1.0)
                    for value, weight in values
                )
            elif slot == "specular":
                weighted = sum(value * weight for value, weight in values) / weight_total
                peak = max(value for value, _weight in values)
                combined = _clamp((weighted * 0.35) + (peak * 0.65), 0.0, 1.0)
            else:
                combined = sum(value * weight for value, weight in values) / weight_total
            grey_byte = _byte(combined)
            target_offset = target_row + (x * 3)
            target_view[target_offset : target_offset + 3] = bytes((grey_byte, grey_byte, grey_byte))

    _raise_if_material_combiner_cancelled(cancelled)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{stem}_{slot}.png"
    del target_view
    del layer_views
    if not target.save(str(output_path), "PNG"):
        return valid_layers[0][2], valid_layers[0][1]
    return _local_file_url(output_path), "+".join(dict.fromkeys(mode for _priority, mode, _image in normalized_layers))
