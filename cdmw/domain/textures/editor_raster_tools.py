"""Texture Editor fill, gradient, recolor, and patch rules."""

from __future__ import annotations

import math
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

from cdmw.domain.textures.editor_brush import _blend_constant_color, _blend_patch
from cdmw.domain.textures.editor_common import _parse_hex_rgb
from cdmw.domain.textures.editor_composite import (
    _apply_channel_edit_locks,
    _blend_layer_region,
    _layer_canvas_intersection,
    flatten_texture_editor_layers,
)
from cdmw.domain.textures.editor_selection_masks import build_texture_editor_selection_mask
from cdmw.models import TextureEditorDocument, TextureEditorToolSettings


def _blend_gradient_color(
    start_rgb: Tuple[int, int, int],
    end_rgb: Tuple[int, int, int],
    amount: np.ndarray,
) -> np.ndarray:
    start = np.asarray(start_rgb, dtype=np.float32)
    end = np.asarray(end_rgb, dtype=np.float32)
    return np.clip(
        np.round((start[None, None, :] * (1.0 - amount[..., None])) + (end[None, None, :] * amount[..., None])),
        0.0,
        255.0,
    ).astype(np.uint8)

def _match_rgb_luma(target_rgb: Tuple[int, int, int], source_rgb: Tuple[int, int, int]) -> Tuple[int, int, int]:
    target_luma = max(1.0, 0.299 * target_rgb[0] + 0.587 * target_rgb[1] + 0.114 * target_rgb[2])
    source_luma = 0.299 * source_rgb[0] + 0.587 * source_rgb[1] + 0.114 * source_rgb[2]
    scale = source_luma / target_luma
    return tuple(max(0, min(255, int(round(channel * scale)))) for channel in target_rgb)

def _blend_rgb(
    original_rgb: Tuple[int, int, int],
    target_rgb: Tuple[int, int, int],
    weight: float,
) -> Tuple[int, int, int]:
    return tuple(
        max(0, min(255, int(round((orig * (1.0 - weight)) + (target * weight)))))
        for orig, target in zip(original_rgb, target_rgb)
    )

def apply_texture_editor_recolor(
    image: np.ndarray,
    settings: TextureEditorToolSettings,
    *,
    selection_mask: Optional[np.ndarray] = None,
) -> np.ndarray:
    rgba = np.asarray(image, dtype=np.uint8).copy()
    target_rgb = _parse_hex_rgb(settings.recolor_target_hex, "#C85A30")
    source_rgb = _parse_hex_rgb(settings.recolor_source_hex, "#808080")
    tolerance = max(0.0, float(settings.recolor_tolerance))
    strength = max(0.0, min(1.0, settings.recolor_strength / 100.0))
    selection_alpha = selection_mask.astype(np.float32) / 255.0 if selection_mask is not None else None
    flat = rgba.reshape(-1, 4)
    selection_flat = selection_alpha.reshape(-1) if selection_alpha is not None else None
    for index, (r, g, b, a) in enumerate(flat):
        if a == 0:
            continue
        if selection_flat is not None and selection_flat[index] <= 0.0:
            continue
        base_rgb = (int(r), int(g), int(b))
        replacement_rgb = target_rgb
        weight = strength
        if settings.recolor_mode == "replace_color":
            distance = math.sqrt((r - source_rgb[0]) ** 2 + (g - source_rgb[1]) ** 2 + (b - source_rgb[2]) ** 2)
            if tolerance <= 0.0 or distance > tolerance:
                continue
            falloff = 1.0 - (distance / tolerance) if tolerance > 0.0 else 1.0
            weight *= max(0.0, min(1.0, falloff))
        if selection_flat is not None:
            weight *= float(selection_flat[index])
        if settings.recolor_preserve_luminance:
            replacement_rgb = _match_rgb_luma(target_rgb, base_rgb)
        merged_rgb = _blend_rgb(base_rgb, replacement_rgb, weight)
        flat[index, 0] = merged_rgb[0]
        flat[index, 1] = merged_rgb[1]
        flat[index, 2] = merged_rgb[2]
    return rgba

def apply_texture_editor_fill(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    tool_settings: TextureEditorToolSettings,
    point: Tuple[int, int],
    *,
    source_snapshot: Optional[np.ndarray] = None,
) -> Dict[str, np.ndarray]:
    if not document.active_layer_id or document.active_layer_id not in layer_pixels:
        return layer_pixels
    active_layer = next((layer for layer in document.layers if layer.layer_id == document.active_layer_id), None)
    if active_layer is None or active_layer.locked:
        return layer_pixels
    if point[0] < 0 or point[1] < 0 or point[0] >= document.width or point[1] >= document.height:
        return layer_pixels
    selection_mask = build_texture_editor_selection_mask(document.width, document.height, document.selection)
    if selection_mask is not None and selection_mask[point[1], point[0]] <= 0:
        return layer_pixels

    active = layer_pixels[document.active_layer_id].copy()
    updated = dict(layer_pixels)
    updated[document.active_layer_id] = active
    intersection = _layer_canvas_intersection(active_layer, active, document)
    if intersection is None:
        return updated
    dx0, dy0, dx1, dy1, sx0, sy0, sx1, sy1 = intersection
    if not (dx0 <= point[0] < dx1 and dy0 <= point[1] < dy1):
        return updated

    color_rgb = _parse_hex_rgb(tool_settings.color_hex)
    strength = max(0.0, min(1.0, tool_settings.opacity / 100.0))
    if strength <= 0.0:
        return updated

    if source_snapshot is None:
        sample_canvas = np.zeros((document.height, document.width, 4), dtype=np.uint8)
        sample_canvas[dy0:dy1, dx0:dx1] = active[sy0:sy1, sx0:sx1]
    else:
        sample_canvas = np.asarray(source_snapshot, dtype=np.uint8)

    tolerance = max(0, min(255, int(getattr(tool_settings, "fill_tolerance", 24))))
    contiguous = bool(getattr(tool_settings, "fill_contiguous", True))
    sample_rgb = sample_canvas[..., :3]
    seed = sample_rgb[point[1], point[0]].astype(np.int16)

    if contiguous:
        flood_source = cv2.cvtColor(sample_rgb, cv2.COLOR_RGB2BGR).copy()
        flood_mask = np.zeros((document.height + 2, document.width + 2), dtype=np.uint8)
        lo = (tolerance, tolerance, tolerance)
        hi = (tolerance, tolerance, tolerance)
        cv2.floodFill(
            flood_source,
            flood_mask,
            (int(point[0]), int(point[1])),
            (0, 0, 0),
            loDiff=lo,
            upDiff=hi,
            flags=4 | (255 << 8) | cv2.FLOODFILL_MASK_ONLY,
        )
        fill_mask = flood_mask[1:-1, 1:-1].astype(np.float32) / 255.0
    else:
        difference = np.max(np.abs(sample_rgb.astype(np.int16) - seed[None, None, :]), axis=2)
        fill_mask = (difference <= tolerance).astype(np.float32)

    if selection_mask is not None:
        fill_mask *= selection_mask.astype(np.float32) / 255.0
    if not np.any(fill_mask > 0.0):
        return updated

    local_fill = fill_mask[dy0:dy1, dx0:dx1]
    if not np.any(local_fill > 0.0):
        return updated
    region = active[sy0:sy1, sx0:sx1]
    blended = _blend_constant_color(
        region,
        np.clip(local_fill * strength, 0.0, 1.0),
        color_rgb,
        mode=getattr(tool_settings, "paint_blend_mode", "normal"),
    )
    blended = _apply_channel_edit_locks(document, region, blended)
    if active_layer.alpha_locked:
        blended[..., 3] = region[..., 3]
    active[sy0:sy1, sx0:sx1] = blended
    updated[document.active_layer_id] = active
    return updated

def apply_texture_editor_gradient(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    tool_settings: TextureEditorToolSettings,
    start_point: Tuple[int, int],
    end_point: Tuple[int, int],
) -> Dict[str, np.ndarray]:
    if not document.active_layer_id or document.active_layer_id not in layer_pixels:
        return layer_pixels
    active_layer = next((layer for layer in document.layers if layer.layer_id == document.active_layer_id), None)
    if active_layer is None or active_layer.locked:
        return layer_pixels
    active = layer_pixels[document.active_layer_id].copy()
    updated = dict(layer_pixels)
    updated[document.active_layer_id] = active
    intersection = _layer_canvas_intersection(active_layer, active, document)
    if intersection is None:
        return updated
    dx0, dy0, dx1, dy1, sx0, sy0, sx1, sy1 = intersection
    region = active[sy0:sy1, sx0:sx1]
    selection_mask = build_texture_editor_selection_mask(document.width, document.height, document.selection)
    if selection_mask is not None:
        local_selection = selection_mask[dy0:dy1, dx0:dx1].astype(np.float32) / 255.0
    else:
        local_selection = np.ones((dy1 - dy0, dx1 - dx0), dtype=np.float32)
    if not np.any(local_selection > 0.0):
        return updated
    start_x = float(start_point[0] - dx0)
    start_y = float(start_point[1] - dy0)
    end_x = float(end_point[0] - dx0)
    end_y = float(end_point[1] - dy0)
    yy, xx = np.mgrid[0:(dy1 - dy0), 0:(dx1 - dx0)].astype(np.float32)
    gradient_mode = str(getattr(tool_settings, "gradient_type", "linear") or "linear").strip().lower()
    if gradient_mode == "radial":
        radius = max(1.0, math.hypot(end_x - start_x, end_y - start_y))
        amount = np.clip(np.sqrt(((xx - start_x) ** 2) + ((yy - start_y) ** 2)) / radius, 0.0, 1.0)
    else:
        vector_x = end_x - start_x
        vector_y = end_y - start_y
        denom = max(1e-6, (vector_x * vector_x) + (vector_y * vector_y))
        amount = np.clip((((xx - start_x) * vector_x) + ((yy - start_y) * vector_y)) / denom, 0.0, 1.0)
    start_rgb = _parse_hex_rgb(tool_settings.color_hex, "#C85A30")
    end_rgb = _parse_hex_rgb(getattr(tool_settings, "secondary_color_hex", "#FFFFFF"), "#FFFFFF")
    gradient_rgba = np.zeros_like(region)
    gradient_rgba[..., :3] = _blend_gradient_color(start_rgb, end_rgb, amount)
    gradient_rgba[..., 3] = np.clip(np.round(local_selection * (max(0.0, min(1.0, tool_settings.opacity / 100.0)) * 255.0)), 0.0, 255.0).astype(np.uint8)
    blended = _blend_layer_region(
        region,
        gradient_rgba,
        opacity=100,
        mode=getattr(tool_settings, "paint_blend_mode", "normal"),
    )
    blended = _apply_channel_edit_locks(document, region, blended)
    if active_layer.alpha_locked:
        blended[..., 3] = region[..., 3]
    active[sy0:sy1, sx0:sx1] = blended
    updated[document.active_layer_id] = active
    return updated

def apply_texture_editor_patch(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    tool_settings: TextureEditorToolSettings,
    *,
    delta_x: int,
    delta_y: int,
    source_snapshot: Optional[np.ndarray] = None,
) -> Dict[str, np.ndarray]:
    if not document.active_layer_id or document.active_layer_id not in layer_pixels:
        return layer_pixels
    active_layer = next((layer for layer in document.layers if layer.layer_id == document.active_layer_id), None)
    if active_layer is None or active_layer.locked:
        return layer_pixels
    selection_mask = build_texture_editor_selection_mask(document.width, document.height, document.selection)
    if selection_mask is None or not np.any(selection_mask > 0):
        return layer_pixels
    ys, xs = np.where(selection_mask > 0)
    if xs.size == 0 or ys.size == 0:
        return layer_pixels
    x0 = int(xs.min())
    y0 = int(ys.min())
    x1 = int(xs.max()) + 1
    y1 = int(ys.max()) + 1
    active = layer_pixels[document.active_layer_id].copy()
    updated = dict(layer_pixels)
    updated[document.active_layer_id] = active
    intersection = _layer_canvas_intersection(active_layer, active, document)
    if intersection is None:
        return updated
    dx0, dy0, dx1, dy1, sx0, sy0, sx1, sy1 = intersection
    if x1 <= dx0 or x0 >= dx1 or y1 <= dy0 or y0 >= dy1:
        return updated
    region_x0 = max(dx0, x0)
    region_y0 = max(dy0, y0)
    region_x1 = min(dx1, x1)
    region_y1 = min(dy1, y1)
    local_x0 = region_x0 - dx0 + sx0
    local_y0 = region_y0 - dy0 + sy0
    local_x1 = local_x0 + (region_x1 - region_x0)
    local_y1 = local_y0 + (region_y1 - region_y0)
    if source_snapshot is None:
        sample_canvas = flatten_texture_editor_layers(document, layer_pixels)
    else:
        sample_canvas = np.asarray(source_snapshot, dtype=np.uint8)
    source_x0 = max(0, min(document.width, region_x0 + int(delta_x)))
    source_y0 = max(0, min(document.height, region_y0 + int(delta_y)))
    source_x1 = max(source_x0, min(document.width, source_x0 + (region_x1 - region_x0)))
    source_y1 = max(source_y0, min(document.height, source_y0 + (region_y1 - region_y0)))
    width = min(region_x1 - region_x0, source_x1 - source_x0)
    height = min(region_y1 - region_y0, source_y1 - source_y0)
    if width <= 0 or height <= 0:
        return updated
    target_region = active[local_y0:local_y0 + height, local_x0:local_x0 + width]
    source_patch = sample_canvas[source_y0:source_y0 + height, source_x0:source_x0 + width].copy()
    local_mask = selection_mask[region_y0:region_y0 + height, region_x0:region_x0 + width].astype(np.float32) / 255.0
    blend_strength = max(0.0, min(1.0, getattr(tool_settings, "patch_blend", 70) / 100.0))
    blended = _blend_patch(target_region, source_patch, np.clip(local_mask * blend_strength, 0.0, 1.0))
    blended = _apply_channel_edit_locks(document, target_region, blended)
    if active_layer.alpha_locked:
        blended[..., 3] = target_region[..., 3]
    active[local_y0:local_y0 + height, local_x0:local_x0 + width] = blended
    updated[document.active_layer_id] = active
    return updated
