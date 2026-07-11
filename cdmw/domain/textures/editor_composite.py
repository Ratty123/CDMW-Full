"""Texture Editor compositing and raster-region rules."""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import cv2
import numpy as np

from cdmw.models import TextureEditorAdjustmentLayer, TextureEditorDocument, TextureEditorLayer


def _resize_array(
    pixels: np.ndarray,
    width: int,
    height: int,
    *,
    nearest: bool = False,
) -> np.ndarray:
    source = np.asarray(pixels, dtype=np.uint8)
    target_width = max(1, int(width))
    target_height = max(1, int(height))
    if source.shape[1] == target_width and source.shape[0] == target_height:
        return np.ascontiguousarray(source.copy())
    if nearest:
        interpolation = cv2.INTER_NEAREST
    else:
        shrinking = target_width < source.shape[1] or target_height < source.shape[0]
        interpolation = cv2.INTER_AREA if shrinking else cv2.INTER_LINEAR
    resized = cv2.resize(source, (target_width, target_height), interpolation=interpolation)
    return np.ascontiguousarray(resized, dtype=np.uint8)

def _channel_edit_flags(document: TextureEditorDocument) -> Tuple[bool, bool, bool, bool]:
    return (
        bool(getattr(document, "edit_red_channel", True)),
        bool(getattr(document, "edit_green_channel", True)),
        bool(getattr(document, "edit_blue_channel", True)),
        bool(getattr(document, "edit_alpha_channel", True)),
    )

def _apply_channel_edit_locks(
    document: TextureEditorDocument,
    before_region: np.ndarray,
    after_region: np.ndarray,
) -> np.ndarray:
    red_enabled, green_enabled, blue_enabled, alpha_enabled = _channel_edit_flags(document)
    if red_enabled and green_enabled and blue_enabled and alpha_enabled:
        return after_region
    locked = after_region.copy()
    if not red_enabled:
        locked[..., 0] = before_region[..., 0]
    if not green_enabled:
        locked[..., 1] = before_region[..., 1]
    if not blue_enabled:
        locked[..., 2] = before_region[..., 2]
    if not alpha_enabled:
        locked[..., 3] = before_region[..., 3]
    return locked

def _layer_canvas_intersection(
    layer: TextureEditorLayer,
    pixels: np.ndarray,
    document: TextureEditorDocument,
) -> Optional[Tuple[int, int, int, int, int, int, int, int]]:
    layer_h, layer_w = pixels.shape[:2]
    if layer_w <= 0 or layer_h <= 0:
        return None
    x0 = int(layer.offset_x)
    y0 = int(layer.offset_y)
    x1 = x0 + layer_w
    y1 = y0 + layer_h
    dx0 = max(0, x0)
    dy0 = max(0, y0)
    dx1 = min(document.width, x1)
    dy1 = min(document.height, y1)
    if dx1 <= dx0 or dy1 <= dy0:
        return None
    sx0 = dx0 - x0
    sy0 = dy0 - y0
    sx1 = sx0 + (dx1 - dx0)
    sy1 = sy0 + (dy1 - dy0)
    return dx0, dy0, dx1, dy1, sx0, sy0, sx1, sy1

def _blend_rgb_mode(dst_rgb: np.ndarray, src_rgb: np.ndarray, mode: str) -> np.ndarray:
    mode_key = (mode or "normal").strip().lower()
    if mode_key == "multiply":
        return dst_rgb * src_rgb
    if mode_key == "screen":
        return 1.0 - ((1.0 - dst_rgb) * (1.0 - src_rgb))
    if mode_key == "overlay":
        return np.where(
            dst_rgb <= 0.5,
            2.0 * dst_rgb * src_rgb,
            1.0 - (2.0 * (1.0 - dst_rgb) * (1.0 - src_rgb)),
        )
    return src_rgb

def _blend_layer_region(
    dst_region: np.ndarray,
    src_region: np.ndarray,
    *,
    opacity: int,
    mode: str,
) -> np.ndarray:
    if (
        int(opacity) >= 100
        and (mode or "normal").strip().lower() == "normal"
        and not np.any(dst_region)
    ):
        transparent = src_region[..., 3] == 0
        if not np.any(transparent):
            return src_region
        out = src_region.copy()
        out[transparent, :3] = 0
        return out
    dst = dst_region.astype(np.float32) / 255.0
    src = src_region.astype(np.float32) / 255.0
    src_alpha = src[..., 3:4] * max(0.0, min(1.0, float(opacity) / 100.0))
    dst_alpha = dst[..., 3:4]
    blended_rgb = _blend_rgb_mode(dst[..., :3], src[..., :3], mode)
    out_alpha = src_alpha + dst_alpha * (1.0 - src_alpha)
    safe_alpha = np.where(out_alpha > 1e-6, out_alpha, 1.0)
    out_rgb = (blended_rgb * src_alpha + dst[..., :3] * dst_alpha * (1.0 - src_alpha)) / safe_alpha
    out = dst.copy()
    out[..., :3] = np.where(out_alpha > 1e-6, out_rgb, out[..., :3])
    out[..., 3:4] = out_alpha
    return np.clip(np.round(out * 255.0), 0, 255).astype(np.uint8)

def _apply_mask_to_src_region(src_region: np.ndarray, mask_region: Optional[np.ndarray]) -> np.ndarray:
    if mask_region is None or mask_region.size == 0:
        return src_region
    mask_alpha = mask_region[..., 3:4].astype(np.float32) / 255.0
    masked = src_region.copy().astype(np.float32)
    masked[..., 3:4] *= mask_alpha
    return np.clip(np.round(masked), 0, 255).astype(np.uint8)

def _build_curves_lut(shadows: float, midtones: float, highlights: float) -> np.ndarray:
    xs = np.arange(256, dtype=np.float32)
    normalized = xs / 255.0
    shadow_bias = max(-1.0, min(1.0, shadows / 100.0))
    mid_bias = max(-1.0, min(1.0, midtones / 100.0))
    highlight_bias = max(-1.0, min(1.0, highlights / 100.0))
    curve = normalized.copy()
    curve += shadow_bias * ((1.0 - normalized) ** 2) * 0.25
    curve += mid_bias * (1.0 - np.abs((normalized * 2.0) - 1.0)) * 0.30
    curve += highlight_bias * (normalized ** 2) * 0.25
    return np.clip(np.round(curve * 255.0), 0, 255).astype(np.uint8)

def _adjustment_target_mask(rgb: np.ndarray, target_range: str) -> np.ndarray:
    rgb_f = rgb.astype(np.float32) / 255.0
    red = rgb_f[..., 0]
    green = rgb_f[..., 1]
    blue = rgb_f[..., 2]
    max_rgb = np.maximum(np.maximum(red, green), blue)
    min_rgb = np.minimum(np.minimum(red, green), blue)
    chroma = max_rgb - min_rgb
    target = (target_range or "neutrals").strip().lower()
    if target == "reds":
        weight = np.clip(red - np.maximum(green, blue), 0.0, 1.0)
    elif target == "greens":
        weight = np.clip(green - np.maximum(red, blue), 0.0, 1.0)
    elif target == "blues":
        weight = np.clip(blue - np.maximum(red, green), 0.0, 1.0)
    elif target == "cyans":
        weight = np.clip(np.minimum(green, blue) - red, 0.0, 1.0)
    elif target == "magentas":
        weight = np.clip(np.minimum(red, blue) - green, 0.0, 1.0)
    elif target == "yellows":
        weight = np.clip(np.minimum(red, green) - blue, 0.0, 1.0)
    elif target == "whites":
        weight = np.clip((max_rgb - 0.55) / 0.45, 0.0, 1.0)
        weight *= np.clip(1.0 - (chroma * 1.75), 0.0, 1.0)
    elif target == "blacks":
        weight = np.clip((0.35 - max_rgb) / 0.35, 0.0, 1.0)
        weight *= np.clip(1.0 - (chroma * 1.75), 0.0, 1.0)
    else:
        neutral_bias = np.clip(1.0 - (chroma * 2.0), 0.0, 1.0)
        luminance = (red * 0.299) + (green * 0.587) + (blue * 0.114)
        tonal = np.clip(1.0 - np.abs((luminance * 2.0) - 1.0), 0.0, 1.0)
        weight = neutral_bias * tonal
    return weight[..., None].astype(np.float32)

def _trim_rgba_transparent_bounds(pixels: np.ndarray) -> np.ndarray:
    rgba = np.asarray(pixels, dtype=np.uint8)
    if rgba.size == 0:
        return rgba
    alpha = rgba[..., 3]
    ys, xs = np.where(alpha > 0)
    if xs.size == 0 or ys.size == 0:
        return rgba[:1, :1].copy()
    x0 = int(xs.min())
    y0 = int(ys.min())
    x1 = int(xs.max()) + 1
    y1 = int(ys.max()) + 1
    return rgba[y0:y1, x0:x1].copy()

def _apply_adjustment_to_rgba(
    rgba: np.ndarray,
    adjustment: TextureEditorAdjustmentLayer,
    *,
    mask_region: Optional[np.ndarray] = None,
) -> np.ndarray:
    if rgba.size == 0 or not adjustment.enabled or adjustment.opacity <= 0:
        return rgba
    opacity = max(0.0, min(1.0, adjustment.opacity / 100.0))
    source = rgba.astype(np.uint8)
    result = source.copy()
    params = adjustment.parameters
    adj_type = (adjustment.adjustment_type or "").strip().lower()
    rgb = source[..., :3]
    alpha = source[..., 3:4]
    if adj_type == "hue_saturation":
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
        hue_shift = float(params.get("hue", 0.0))
        sat_shift = float(params.get("saturation", 0.0))
        light_shift = float(params.get("lightness", 0.0))
        hsv[..., 0] = np.mod(hsv[..., 0] + (hue_shift / 2.0), 180.0)
        hsv[..., 1] = np.clip(hsv[..., 1] * (1.0 + (sat_shift / 100.0)), 0.0, 255.0)
        hsv[..., 2] = np.clip(hsv[..., 2] * (1.0 + (light_shift / 100.0)), 0.0, 255.0)
        adjusted_rgb = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB)
    elif adj_type == "brightness_contrast":
        brightness = max(-1.0, min(1.0, float(params.get("brightness", 0.0)) / 100.0))
        contrast = max(-1.0, min(1.0, float(params.get("contrast", 0.0)) / 100.0))
        saturation = max(-1.0, min(1.0, float(params.get("saturation", 0.0)) / 100.0))
        rgb_f = rgb.astype(np.float32) / 255.0
        rgb_f = np.clip(((rgb_f - 0.5) * (1.0 + contrast)) + 0.5 + brightness, 0.0, 1.0)
        luma = (rgb_f[..., 0:1] * 0.299) + (rgb_f[..., 1:2] * 0.587) + (rgb_f[..., 2:3] * 0.114)
        rgb_f = np.clip(luma + ((rgb_f - luma) * (1.0 + saturation)), 0.0, 1.0)
        adjusted_rgb = np.clip(np.round(rgb_f * 255.0), 0.0, 255.0).astype(np.uint8)
    elif adj_type == "exposure":
        exposure = max(-2.0, min(2.0, float(params.get("exposure", 0.0)) / 50.0))
        offset = max(-0.5, min(0.5, float(params.get("offset", 0.0)) / 200.0))
        gamma = max(0.1, min(4.0, float(params.get("gamma", 1.0))))
        rgb_f = rgb.astype(np.float32) / 255.0
        rgb_f = np.clip((rgb_f * (2.0 ** exposure)) + offset, 0.0, 1.0)
        rgb_f = np.power(rgb_f, 1.0 / gamma)
        adjusted_rgb = np.clip(np.round(rgb_f * 255.0), 0.0, 255.0).astype(np.uint8)
    elif adj_type == "color_balance":
        red_cyan = max(-100.0, min(100.0, float(params.get("red_cyan", 0.0)))) * 0.9
        green_magenta = max(-100.0, min(100.0, float(params.get("green_magenta", 0.0)))) * 0.9
        blue_yellow = max(-100.0, min(100.0, float(params.get("blue_yellow", 0.0)))) * 0.9
        adjusted_rgb = rgb.astype(np.int16)
        adjusted_rgb[..., 0] += int(round(red_cyan))
        adjusted_rgb[..., 1] += int(round(green_magenta))
        adjusted_rgb[..., 2] += int(round(blue_yellow))
        adjusted_rgb = np.clip(adjusted_rgb, 0, 255).astype(np.uint8)
    elif adj_type == "vibrance":
        vibrance = max(-100.0, min(100.0, float(params.get("vibrance", 0.0)))) / 100.0
        saturation = max(-100.0, min(100.0, float(params.get("saturation", 0.0)))) / 100.0
        lightness = max(-100.0, min(100.0, float(params.get("lightness", 0.0)))) / 100.0
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
        sat_norm = hsv[..., 1] / 255.0
        vib_weight = np.where(vibrance >= 0.0, 1.0 - sat_norm, sat_norm)
        hsv[..., 1] = np.clip(hsv[..., 1] * (1.0 + (vibrance * vib_weight)), 0.0, 255.0)
        hsv[..., 1] = np.clip(hsv[..., 1] * (1.0 + saturation), 0.0, 255.0)
        hsv[..., 2] = np.clip(hsv[..., 2] * (1.0 + lightness), 0.0, 255.0)
        adjusted_rgb = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB)
    elif adj_type == "selective_color":
        target_range = str(params.get("target_range", "neutrals") or "neutrals")
        red_cyan = max(-100.0, min(100.0, float(params.get("red_cyan", 0.0))))
        green_magenta = max(-100.0, min(100.0, float(params.get("green_magenta", 0.0))))
        blue_yellow = max(-100.0, min(100.0, float(params.get("blue_yellow", 0.0))))
        mask = _adjustment_target_mask(rgb, target_range)
        adjusted_rgb_f = rgb.astype(np.float32)
        adjusted_rgb_f[..., 0:1] += red_cyan * mask
        adjusted_rgb_f[..., 1:2] += green_magenta * mask
        adjusted_rgb_f[..., 2:3] += blue_yellow * mask
        adjusted_rgb = np.clip(np.round(adjusted_rgb_f), 0.0, 255.0).astype(np.uint8)
    elif adj_type == "curves":
        lut = _build_curves_lut(
            float(params.get("shadows", 0.0)),
            float(params.get("midtones", 0.0)),
            float(params.get("highlights", 0.0)),
        )
        adjusted_rgb = cv2.LUT(rgb, lut)
    else:
        black = max(0.0, min(254.0, float(params.get("black", 0.0))))
        white = max(1.0, min(255.0, float(params.get("white", 255.0))))
        white = max(white, black + 1.0)
        gamma = max(0.1, min(4.0, float(params.get("gamma", 1.0))))
        out_black = max(0.0, min(254.0, float(params.get("output_black", 0.0))))
        out_white = max(out_black + 1.0, min(255.0, float(params.get("output_white", 255.0))))
        normalized = np.clip((rgb.astype(np.float32) - black) / max(1.0, white - black), 0.0, 1.0)
        leveled = np.power(normalized, 1.0 / gamma)
        adjusted_rgb = np.clip(
            np.round(out_black + (leveled * (out_white - out_black))),
            0.0,
            255.0,
        ).astype(np.uint8)
    adjusted = np.concatenate([adjusted_rgb, alpha], axis=2)
    if mask_region is not None and mask_region.size > 0:
        opacity *= 1.0
        mask_alpha = mask_region[..., 3:4].astype(np.float32) / 255.0
    else:
        mask_alpha = None
    blended = source.astype(np.float32)
    adjusted_f = adjusted.astype(np.float32)
    if mask_alpha is None:
        weight = opacity
    else:
        weight = opacity * mask_alpha
    blended[..., :3] = np.clip(
        (source[..., :3].astype(np.float32) * (1.0 - weight)) + (adjusted_f[..., :3] * weight),
        0.0,
        255.0,
    )
    result[..., :3] = np.round(blended[..., :3]).astype(np.uint8)
    return result

def _flatten_texture_editor_raster_layers(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
) -> np.ndarray:
    base = np.zeros((document.height, document.width, 4), dtype=np.uint8)
    for layer in document.layers:
        pixels = layer_pixels.get(layer.layer_id)
        if pixels is None or not layer.visible:
            continue
        intersection = _layer_canvas_intersection(layer, pixels, document)
        if intersection is None:
            continue
        dx0, dy0, dx1, dy1, sx0, sy0, sx1, sy1 = intersection
        dst_region = base[dy0:dy1, dx0:dx1]
        src_region = pixels[sy0:sy1, sx0:sx1]
        if layer.mask_layer_id and layer.mask_enabled:
            mask_pixels = layer_pixels.get(layer.mask_layer_id)
            if mask_pixels is not None:
                src_region = _apply_mask_to_src_region(src_region, mask_pixels[sy0:sy1, sx0:sx1])
        base[dy0:dy1, dx0:dx1] = _blend_layer_region(
            dst_region,
            src_region,
            opacity=layer.opacity,
            mode=layer.blend_mode,
        )
    return base

def _document_bounds(
    document: TextureEditorDocument,
    bounds: Tuple[int, int, int, int],
) -> Optional[Tuple[int, int, int, int]]:
    x = max(0, min(int(document.width), int(bounds[0])))
    y = max(0, min(int(document.height), int(bounds[1])))
    width = max(0, int(bounds[2]))
    height = max(0, int(bounds[3]))
    x1 = min(int(document.width), x + width)
    y1 = min(int(document.height), y + height)
    if x1 <= x or y1 <= y:
        return None
    return x, y, x1 - x, y1 - y

def _adjustment_mask_canvas_region(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    mask_layer_id: str,
    bounds: Optional[Tuple[int, int, int, int]] = None,
) -> Optional[np.ndarray]:
    if not mask_layer_id:
        return None
    layer = next((candidate for candidate in document.layers if candidate.layer_id == mask_layer_id), None)
    mask_pixels = layer_pixels.get(mask_layer_id)
    if layer is None or mask_pixels is None:
        return None
    if bounds is None:
        x = 0
        y = 0
        width = int(document.width)
        height = int(document.height)
    else:
        normalized = _document_bounds(document, bounds)
        if normalized is None:
            return None
        x, y, width, height = normalized
    canvas_mask = np.zeros((height, width, 4), dtype=np.uint8)
    intersection = _layer_canvas_intersection(layer, mask_pixels, document)
    if intersection is None:
        return canvas_mask
    dx0, dy0, dx1, dy1, sx0, sy0, sx1, sy1 = intersection
    rx0 = max(dx0, x)
    ry0 = max(dy0, y)
    rx1 = min(dx1, x + width)
    ry1 = min(dy1, y + height)
    if rx1 <= rx0 or ry1 <= ry0:
        return canvas_mask
    local_x0 = rx0 - x
    local_y0 = ry0 - y
    src_x0 = sx0 + (rx0 - dx0)
    src_y0 = sy0 + (ry0 - dy0)
    src_x1 = src_x0 + (rx1 - rx0)
    src_y1 = src_y0 + (ry1 - ry0)
    canvas_mask[local_y0:local_y0 + (ry1 - ry0), local_x0:local_x0 + (rx1 - rx0)] = mask_pixels[src_y0:src_y1, src_x0:src_x1]
    return canvas_mask

def _flatten_texture_editor_raster_layers_region(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    bounds: Tuple[int, int, int, int],
) -> np.ndarray:
    normalized = _document_bounds(document, bounds)
    if normalized is None:
        return np.zeros((1, 1, 4), dtype=np.uint8)
    crop_x, crop_y, crop_width, crop_height = normalized
    base = np.zeros((crop_height, crop_width, 4), dtype=np.uint8)
    for layer in document.layers:
        pixels = layer_pixels.get(layer.layer_id)
        if pixels is None or not layer.visible:
            continue
        intersection = _layer_canvas_intersection(layer, pixels, document)
        if intersection is None:
            continue
        dx0, dy0, dx1, dy1, sx0, sy0, sx1, sy1 = intersection
        rx0 = max(dx0, crop_x)
        ry0 = max(dy0, crop_y)
        rx1 = min(dx1, crop_x + crop_width)
        ry1 = min(dy1, crop_y + crop_height)
        if rx1 <= rx0 or ry1 <= ry0:
            continue
        src_x0 = sx0 + (rx0 - dx0)
        src_y0 = sy0 + (ry0 - dy0)
        src_x1 = src_x0 + (rx1 - rx0)
        src_y1 = src_y0 + (ry1 - ry0)
        dst_x0 = rx0 - crop_x
        dst_y0 = ry0 - crop_y
        src_region = pixels[src_y0:src_y1, src_x0:src_x1]
        if layer.mask_layer_id and layer.mask_enabled:
            mask_pixels = layer_pixels.get(layer.mask_layer_id)
            if mask_pixels is not None:
                src_region = _apply_mask_to_src_region(src_region, mask_pixels[src_y0:src_y1, src_x0:src_x1])
        base[dst_y0:dst_y0 + (ry1 - ry0), dst_x0:dst_x0 + (rx1 - rx0)] = _blend_layer_region(
            base[dst_y0:dst_y0 + (ry1 - ry0), dst_x0:dst_x0 + (rx1 - rx0)],
            src_region,
            opacity=layer.opacity,
            mode=layer.blend_mode,
        )
    return base

def flatten_texture_editor_layers(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
) -> np.ndarray:
    base = _flatten_texture_editor_raster_layers(document, layer_pixels)
    if not document.adjustment_layers:
        return base
    result = base
    for adjustment in document.adjustment_layers:
        mask_region = _adjustment_mask_canvas_region(document, layer_pixels, adjustment.mask_layer_id)
        result = _apply_adjustment_to_rgba(result, adjustment, mask_region=mask_region)
    return result

def flatten_texture_editor_layers_region(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    bounds: Tuple[int, int, int, int],
) -> np.ndarray:
    normalized = _document_bounds(document, bounds)
    if normalized is None:
        return np.zeros((1, 1, 4), dtype=np.uint8)
    base = _flatten_texture_editor_raster_layers_region(document, layer_pixels, normalized)
    if not document.adjustment_layers:
        return base
    result = base
    for adjustment in document.adjustment_layers:
        mask_region = _adjustment_mask_canvas_region(document, layer_pixels, adjustment.mask_layer_id, normalized)
        result = _apply_adjustment_to_rgba(result, adjustment, mask_region=mask_region)
    return result
