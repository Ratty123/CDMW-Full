"""Texture Editor brush construction and stroke rules."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

import cv2
import numpy as np
from PIL import Image

from cdmw.domain.textures.editor_common import _parse_hex_rgb
from cdmw.domain.textures.editor_composite import (
    _apply_channel_edit_locks,
    _layer_canvas_intersection,
)
from cdmw.domain.textures.editor_selection_masks import build_texture_editor_selection_mask
from cdmw.models import TextureEditorDocument, TextureEditorLayer, TextureEditorToolSettings


def _effective_brush_size(settings: TextureEditorToolSettings) -> float:
    base = max(0.25, float(settings.size))
    mode = (getattr(settings, "size_step_mode", "normal") or "normal").strip().lower()
    if mode == "fine":
        return max(0.25, base * 0.25)
    return base

def texture_editor_stroke_points_for_symmetry(
    points: Sequence[Tuple[int, int]],
    width: int,
    height: int,
    symmetry_mode: str,
) -> List[Tuple[int, int]]:
    if not points:
        return []
    mode = (symmetry_mode or "off").strip().lower()
    if mode == "off" or width <= 0 or height <= 0:
        return [(int(x), int(y)) for x, y in points]
    unique_points: List[Tuple[int, int]] = []
    seen: set[Tuple[int, int]] = set()
    for x, y in points:
        candidates = [(int(x), int(y))]
        if mode in {"horizontal", "both"}:
            candidates.append((max(0, width - 1 - int(x)), int(y)))
        if mode in {"vertical", "both"}:
            candidates.append((int(x), max(0, height - 1 - int(y))))
        if mode == "both":
            candidates.append((max(0, width - 1 - int(x)), max(0, height - 1 - int(y))))
        for point in candidates:
            if point not in seen:
                seen.add(point)
                unique_points.append(point)
    return unique_points

def _load_custom_brush_tip_alpha(path_text: str, mtime_ns: int) -> Optional[np.ndarray]:
    try:
        path = Path(path_text).expanduser().resolve()
        with Image.open(path) as image:
            rgba = image.convert("RGBA")
            alpha = np.asarray(rgba.getchannel("A"), dtype=np.uint8)
            if not np.any(alpha):
                grayscale = np.asarray(rgba.convert("L"), dtype=np.uint8)
                alpha = grayscale
    except Exception:
        return None
    if alpha.size == 0:
        return None
    max_side = max(alpha.shape[0], alpha.shape[1], 1)
    canvas = np.zeros((max_side, max_side), dtype=np.uint8)
    offset_y = (max_side - alpha.shape[0]) // 2
    offset_x = (max_side - alpha.shape[1]) // 2
    canvas[offset_y:offset_y + alpha.shape[0], offset_x:offset_x + alpha.shape[1]] = alpha
    return np.ascontiguousarray(canvas, dtype=np.uint8)

def _build_custom_brush_stamp(
    path_text: str,
    size: float,
    strength_percent: int,
    *,
    roundness: int = 100,
    angle_degrees: int = 0,
    hardness: int = 100,
) -> Optional[np.ndarray]:
    try:
        resolved = Path(path_text).expanduser().resolve()
        stat = resolved.stat()
    except Exception:
        return None
    base_alpha = _load_custom_brush_tip_alpha(str(resolved), int(getattr(stat, "st_mtime_ns", 0)))
    if base_alpha is None:
        return None
    radius = max(0.5, float(size) / 2.0)
    diameter = max(1, int(math.ceil(radius * 2.0 + 2.0)))
    roundness_ratio = max(0.15, min(1.0, float(roundness) / 100.0))
    target_w = max(1, int(round(float(diameter) * roundness_ratio)))
    target_h = max(1, int(round(float(diameter))))
    pil_alpha = Image.fromarray(base_alpha, mode="L")
    pil_alpha = pil_alpha.resize((target_w, target_h), resample=Image.Resampling.LANCZOS)
    canvas = Image.new("L", (diameter, diameter), 0)
    canvas.paste(pil_alpha, ((diameter - target_w) // 2, (diameter - target_h) // 2))
    if angle_degrees:
        canvas = canvas.rotate(float(angle_degrees), resample=Image.Resampling.BICUBIC, expand=False, fillcolor=0)
    stamp = np.asarray(canvas, dtype=np.float32) / 255.0
    hardness_ratio = max(0.0, min(1.0, hardness / 100.0))
    exponent = max(0.25, 2.0 - (hardness_ratio * 1.75))
    stamp = np.power(np.clip(stamp, 0.0, 1.0), exponent)
    stamp *= max(0.0, min(1.0, strength_percent / 100.0))
    return np.clip(stamp, 0.0, 1.0).astype(np.float32)

def _smooth_stroke_points(
    points: Sequence[Tuple[int, int]],
    smoothing: int,
) -> List[Tuple[float, float]]:
    if len(points) <= 2:
        return [(float(x), float(y)) for x, y in points]
    strength = max(0, min(100, int(smoothing)))
    if strength <= 0:
        return [(float(x), float(y)) for x, y in points]
    window = 1 + max(1, int(round((strength / 100.0) * 5.0)))
    output: List[Tuple[float, float]] = []
    for index, _point in enumerate(points):
        if index in {0, len(points) - 1}:
            output.append((float(points[index][0]), float(points[index][1])))
            continue
        x_total = 0.0
        y_total = 0.0
        weight_total = 0.0
        for sample_index in range(max(0, index - window), min(len(points), index + window + 1)):
            distance = abs(sample_index - index)
            weight = float(window + 1 - distance)
            x_total += float(points[sample_index][0]) * weight
            y_total += float(points[sample_index][1]) * weight
            weight_total += weight
        output.append((x_total / max(1.0, weight_total), y_total / max(1.0, weight_total)))
    return output

def _build_brush_stamp(
    size: float,
    hardness: int,
    strength_percent: int,
    tip: str = "round",
    pattern: str = "solid",
    roundness: int = 100,
    angle_degrees: int = 0,
) -> np.ndarray:
    radius = max(0.5, float(size) / 2.0)
    diameter = max(1, int(math.ceil(radius * 2.0 + 2.0)))
    yy, xx = np.mgrid[0:diameter, 0:diameter].astype(np.float32)
    center = (diameter - 1) / 2.0
    dx = xx - center
    dy = yy - center
    radians = math.radians(float(angle_degrees))
    cos_value = math.cos(radians)
    sin_value = math.sin(radians)
    rotated_x = (dx * cos_value) + (dy * sin_value)
    rotated_y = (-dx * sin_value) + (dy * cos_value)
    roundness_ratio = max(0.15, min(1.0, float(roundness) / 100.0))
    scaled_x = rotated_x / max(roundness_ratio, 1e-6)
    scaled_y = rotated_y
    tip_key = (tip or "round").strip().lower()
    if tip_key == "square":
        distances = np.maximum(np.abs(scaled_x), np.abs(scaled_y))
    elif tip_key == "diamond":
        distances = (np.abs(scaled_x) + np.abs(scaled_y)) / math.sqrt(2.0)
    elif tip_key == "flat":
        distances = np.sqrt(((scaled_x / 1.5) ** 2) + ((scaled_y / 0.75) ** 2))
    else:
        distances = np.sqrt((scaled_x ** 2) + (scaled_y ** 2))
    outer = radius
    inner = outer * max(0.0, min(1.0, hardness / 100.0))
    stamp = np.zeros((diameter, diameter), dtype=np.float32)
    stamp[distances <= inner] = 1.0
    soft_mask = (distances > inner) & (distances <= outer)
    if np.any(soft_mask):
        stamp[soft_mask] = 1.0 - ((distances[soft_mask] - inner) / max(outer - inner, 1e-6))
    pattern_key = (pattern or "solid").strip().lower()
    if pattern_key != "solid":
        grid_y, grid_x = np.indices((diameter, diameter), dtype=np.float32)
        noise = np.sin((grid_x + 0.73) * 12.9898 + (grid_y + 1.41) * 78.233) * 43758.5453
        noise = noise - np.floor(noise)
        if pattern_key == "speckle":
            modulation = (noise > 0.58).astype(np.float32)
        elif pattern_key == "hatch":
            stripes = np.mod(grid_x + grid_y, 6.0)
            modulation = np.where(stripes < 2.0, 1.0, 0.22).astype(np.float32)
        elif pattern_key == "crosshatch":
            stripes_a = np.mod(grid_x + grid_y, 6.0)
            stripes_b = np.mod(grid_x - grid_y + (diameter * 2.0), 6.0)
            modulation = np.where((stripes_a < 2.0) | (stripes_b < 2.0), 1.0, 0.18).astype(np.float32)
        elif pattern_key == "grain":
            modulation = (0.42 + (noise * 0.58)).astype(np.float32)
        else:
            modulation = np.ones_like(stamp, dtype=np.float32)
        stamp *= modulation
    stamp *= max(0.0, min(1.0, strength_percent / 100.0))
    return np.clip(stamp, 0.0, 1.0)

def _build_effective_brush_stamp(
    tool_settings: TextureEditorToolSettings,
    *,
    size: float,
    strength_percent: int,
) -> np.ndarray:
    brush_tip = str(getattr(tool_settings, "brush_tip", "round") or "round")
    if brush_tip == "image_stamp":
        custom_path = str(getattr(tool_settings, "custom_brush_tip_path", "") or "").strip()
        stamp = _build_custom_brush_stamp(
            custom_path,
            size,
            strength_percent,
            roundness=max(10, min(100, int(getattr(tool_settings, "roundness", 100)))),
            angle_degrees=int(getattr(tool_settings, "angle_degrees", 0)),
            hardness=max(0, min(100, int(getattr(tool_settings, "hardness", 100)))),
        )
        if stamp is not None:
            return stamp
        brush_tip = "round"
    brush_pattern = getattr(tool_settings, "brush_pattern", "solid")
    if getattr(tool_settings, "tool", "") not in {"paint", "erase", "clone", "heal", "smudge", "dodge_burn"}:
        brush_pattern = "solid"
    return _build_brush_stamp(
        size,
        max(0, min(100, int(getattr(tool_settings, "hardness", 100)))),
        strength_percent,
        brush_tip,
        brush_pattern,
        max(10, min(100, int(getattr(tool_settings, "roundness", 100)))),
        int(getattr(tool_settings, "angle_degrees", 0)),
    )

def _interpolate_stroke(
    points: Sequence[Tuple[int, int]],
    spacing: int,
    *,
    smoothing: int = 0,
) -> List[Tuple[int, int]]:
    if not points:
        return []
    smoothed = _smooth_stroke_points(points, smoothing)
    if len(smoothed) == 1:
        return [(int(round(smoothed[0][0])), int(round(smoothed[0][1])))]
    output: List[Tuple[int, int]] = []
    step = max(1.0, float(spacing))
    for start, end in zip(smoothed[:-1], smoothed[1:]):
        x0, y0 = start
        x1, y1 = end
        dx = float(x1 - x0)
        dy = float(y1 - y0)
        distance = math.hypot(dx, dy)
        steps = max(1, int(math.ceil(distance / step)))
        for index in range(steps):
            t = index / steps
            output.append((int(round(x0 + dx * t)), int(round(y0 + dy * t))))
    output.append((int(round(smoothed[-1][0])), int(round(smoothed[-1][1]))))
    deduped: List[Tuple[int, int]] = []
    for point in output:
        if not deduped or deduped[-1] != point:
            deduped.append(point)
    return deduped

def _clip_stamp_region(
    point: Tuple[int, int],
    stamp: np.ndarray,
    width: int,
    height: int,
) -> Optional[Tuple[Tuple[int, int, int, int], Tuple[int, int, int, int]]]:
    stamp_h, stamp_w = stamp.shape[:2]
    half_w = stamp_w // 2
    half_h = stamp_h // 2
    x0 = point[0] - half_w
    y0 = point[1] - half_h
    x1 = x0 + stamp_w
    y1 = y0 + stamp_h
    tx0 = max(0, x0)
    ty0 = max(0, y0)
    tx1 = min(width, x1)
    ty1 = min(height, y1)
    if tx1 <= tx0 or ty1 <= ty0:
        return None
    sx0 = tx0 - x0
    sy0 = ty0 - y0
    sx1 = sx0 + (tx1 - tx0)
    sy1 = sy0 + (ty1 - ty0)
    return (tx0, ty0, tx1, ty1), (sx0, sy0, sx1, sy1)

def _blend_constant_color(
    region: np.ndarray,
    stamp_alpha: np.ndarray,
    rgb: Tuple[int, int, int],
    *,
    mode: str = "normal",
) -> np.ndarray:
    dst = region.astype(np.float32) / 255.0
    src_alpha = stamp_alpha[..., None]
    src_rgb = np.zeros_like(dst[..., :3])
    src_rgb[..., 0] = rgb[0] / 255.0
    src_rgb[..., 1] = rgb[1] / 255.0
    src_rgb[..., 2] = rgb[2] / 255.0
    mode_key = (mode or "normal").strip().lower()
    if mode_key == "multiply":
        paint_rgb = dst[..., :3] * src_rgb
    elif mode_key == "screen":
        paint_rgb = 1.0 - ((1.0 - dst[..., :3]) * (1.0 - src_rgb))
    elif mode_key == "overlay":
        paint_rgb = np.where(
            dst[..., :3] <= 0.5,
            2.0 * dst[..., :3] * src_rgb,
            1.0 - (2.0 * (1.0 - dst[..., :3]) * (1.0 - src_rgb)),
        )
    else:
        paint_rgb = src_rgb
    dst_alpha = dst[..., 3:4]
    out_alpha = src_alpha + dst_alpha * (1.0 - src_alpha)
    safe_alpha = np.where(out_alpha > 1e-6, out_alpha, 1.0)
    out_rgb = (paint_rgb * src_alpha + dst[..., :3] * dst_alpha * (1.0 - src_alpha)) / safe_alpha
    out = dst.copy()
    out[..., :3] = np.where(out_alpha > 1e-6, out_rgb, out[..., :3])
    out[..., 3:4] = out_alpha
    return np.clip(np.round(out * 255.0), 0, 255).astype(np.uint8)

def _blend_patch(
    region: np.ndarray,
    patch: np.ndarray,
    stamp_alpha: np.ndarray,
) -> np.ndarray:
    dst = region.astype(np.float32) / 255.0
    src = patch.astype(np.float32) / 255.0
    src_alpha = src[..., 3:4] * stamp_alpha[..., None]
    dst_alpha = dst[..., 3:4]
    out_alpha = src_alpha + dst_alpha * (1.0 - src_alpha)
    safe_alpha = np.where(out_alpha > 1e-6, out_alpha, 1.0)
    out_rgb = (src[..., :3] * src_alpha + dst[..., :3] * dst_alpha * (1.0 - src_alpha)) / safe_alpha
    out = dst.copy()
    out[..., :3] = np.where(out_alpha > 1e-6, out_rgb, out[..., :3])
    out[..., 3:4] = out_alpha
    return np.clip(np.round(out * 255.0), 0, 255).astype(np.uint8)

def _apply_smudge_patch(
    target_region: np.ndarray,
    source_patch: np.ndarray,
    stamp_alpha: np.ndarray,
    strength: float,
) -> np.ndarray:
    weight = np.clip(stamp_alpha * max(0.0, min(1.0, strength)), 0.0, 1.0)
    return _blend_patch(target_region, source_patch, weight)

def _apply_dodge_burn_region(
    region: np.ndarray,
    stamp_alpha: np.ndarray,
    *,
    exposure: float,
    mode: str,
) -> np.ndarray:
    rgb = region[..., :3].astype(np.float32)
    luma = (0.299 * rgb[..., 0]) + (0.587 * rgb[..., 1]) + (0.114 * rgb[..., 2])
    normalized_luma = np.clip(luma / 255.0, 0.0, 1.0)
    mode_key = (mode or "dodge_midtones").strip().lower()
    if "shadows" in mode_key:
        tonal_weight = np.clip(1.0 - normalized_luma, 0.0, 1.0)
    elif "highlights" in mode_key:
        tonal_weight = np.clip(normalized_luma, 0.0, 1.0)
    else:
        tonal_weight = 1.0 - np.abs((normalized_luma * 2.0) - 1.0)
    weight = np.clip(stamp_alpha[..., None] * tonal_weight[..., None] * max(0.0, min(1.0, exposure)), 0.0, 1.0)
    adjusted = region.astype(np.float32)
    if mode_key.startswith("burn"):
        adjusted[..., :3] = np.clip(adjusted[..., :3] * (1.0 - (weight * 0.85)), 0.0, 255.0)
    else:
        adjusted[..., :3] = np.clip(adjusted[..., :3] + ((255.0 - adjusted[..., :3]) * weight * 0.85), 0.0, 255.0)
    return np.clip(np.round(adjusted), 0.0, 255.0).astype(np.uint8)


@dataclass(frozen=True, slots=True)
class _StrokeContext:
    document: TextureEditorDocument
    active_layer: TextureEditorLayer
    updated: Dict[str, np.ndarray]
    active: np.ndarray
    selection_mask: Optional[np.ndarray]
    effective_size: float
    stroke_points: Tuple[Tuple[int, int], ...]
    stamp: np.ndarray
    color_rgb: Tuple[int, int, int]
    sample_snapshot: Optional[np.ndarray]
    source_canvas: Optional[np.ndarray]
    clone_delta: Optional[Tuple[int, int]]
    layer_width: int
    layer_height: int


def _stroke_sample_snapshot(
    document: TextureEditorDocument,
    active_layer: TextureEditorLayer,
    active: np.ndarray,
    tool_settings: TextureEditorToolSettings,
    source_snapshot: Optional[np.ndarray],
) -> Optional[np.ndarray]:
    if source_snapshot is not None:
        sample = np.zeros_like(active)
        intersection = _layer_canvas_intersection(active_layer, active, document)
        if intersection is not None:
            dx0, dy0, dx1, dy1, sx0, sy0, sx1, sy1 = intersection
            sample[sy0:sy1, sx0:sx1] = source_snapshot[dy0:dy1, dx0:dx1]
        return sample
    if tool_settings.tool in {"clone", "heal", "sharpen", "soften", "smudge"}:
        return active.copy()
    return None


def _stroke_clone_delta(
    tool_settings: TextureEditorToolSettings,
    stroke_origin: Tuple[int, int],
) -> Optional[Tuple[int, int]]:
    if tool_settings.tool not in {"clone", "heal"} or tool_settings.clone_source_point is None:
        return None
    return (
        int(tool_settings.clone_source_point[0] - stroke_origin[0]),
        int(tool_settings.clone_source_point[1] - stroke_origin[1]),
    )


def _prepare_stroke_context(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    tool_settings: TextureEditorToolSettings,
    points: Sequence[Tuple[int, int]],
    *,
    source_snapshot: Optional[np.ndarray],
    mutate_active_layer: bool,
) -> Tuple[Dict[str, np.ndarray], Optional[_StrokeContext]]:
    if not document.active_layer_id or document.active_layer_id not in layer_pixels:
        return layer_pixels, None
    active_layer = next((layer for layer in document.layers if layer.layer_id == document.active_layer_id), None)
    if active_layer is None or active_layer.locked:
        return layer_pixels, None
    selection_mask = build_texture_editor_selection_mask(document.width, document.height, document.selection)
    source_active = np.asarray(layer_pixels[document.active_layer_id], dtype=np.uint8)
    active = source_active if mutate_active_layer and source_active.flags.writeable else source_active.copy()
    updated = dict(layer_pixels)
    updated[document.active_layer_id] = active
    layer_height, layer_width = active.shape[:2]
    effective_size = _effective_brush_size(tool_settings)
    spacing = max(1, int(round(effective_size * max(0.05, tool_settings.spacing / 100.0))))
    stroke_points = _interpolate_stroke(
        points,
        spacing,
        smoothing=max(0, int(getattr(tool_settings, "smoothing", 0))),
    )
    if not stroke_points:
        return updated, None
    if tool_settings.tool in {"paint", "erase", "sharpen", "soften", "smudge", "dodge_burn"}:
        stroke_points = texture_editor_stroke_points_for_symmetry(
            stroke_points,
            document.width,
            document.height,
            getattr(tool_settings, "symmetry_mode", "off"),
        )
    strength = max(0, min(100, int(round(tool_settings.opacity * max(0.05, tool_settings.flow / 100.0)))))
    stamp = _build_effective_brush_stamp(tool_settings, size=effective_size, strength_percent=strength)
    if tool_settings.tool in {"clone", "heal"} and source_snapshot is None:
        return updated, None
    sample = _stroke_sample_snapshot(document, active_layer, active, tool_settings, source_snapshot)
    return updated, _StrokeContext(
        document=document,
        active_layer=active_layer,
        updated=updated,
        active=active,
        selection_mask=selection_mask,
        effective_size=effective_size,
        stroke_points=tuple(stroke_points),
        stamp=stamp,
        color_rgb=_parse_hex_rgb(tool_settings.color_hex),
        sample_snapshot=sample,
        source_canvas=source_snapshot,
        clone_delta=_stroke_clone_delta(tool_settings, stroke_points[0]),
        layer_width=layer_width,
        layer_height=layer_height,
    )


def _clip_stroke_to_active_layer(
    context: _StrokeContext,
    global_point: Tuple[int, int],
) -> Optional[Tuple[Tuple[int, int, int, int], Tuple[int, int, int, int]]]:
    local_point = (
        int(global_point[0] - context.active_layer.offset_x),
        int(global_point[1] - context.active_layer.offset_y),
    )
    return _clip_stamp_region(local_point, context.stamp, context.layer_width, context.layer_height)


def _apply_stroke_locks(
    context: _StrokeContext,
    before: np.ndarray,
    after: np.ndarray,
) -> np.ndarray:
    locked = _apply_channel_edit_locks(context.document, before, after)
    if context.active_layer.alpha_locked:
        locked = locked.copy()
        locked[..., 3] = before[..., 3]
    return locked


def _selected_stamp_alpha(
    context: _StrokeContext,
    layer_bounds: Tuple[int, int, int, int],
    stamp_bounds: Tuple[int, int, int, int],
) -> np.ndarray:
    lx0, ly0, lx1, ly1 = layer_bounds
    sx0, sy0, sx1, sy1 = stamp_bounds
    alpha = context.stamp[sy0:sy1, sx0:sx1]
    if context.selection_mask is None:
        return alpha
    gx0 = context.active_layer.offset_x + lx0
    gy0 = context.active_layer.offset_y + ly0
    gx1 = gx0 + (lx1 - lx0)
    gy1 = gy0 + (ly1 - ly0)
    return alpha * (context.selection_mask[gy0:gy1, gx0:gx1].astype(np.float32) / 255.0)


def _stroke_coverage(context: _StrokeContext) -> np.ndarray:
    coverage = np.zeros((context.layer_height, context.layer_width), dtype=np.float32)
    for point in context.stroke_points:
        clipped = _clip_stroke_to_active_layer(context, point)
        if clipped is None:
            continue
        layer_bounds, stamp_bounds = clipped
        lx0, ly0, lx1, ly1 = layer_bounds
        alpha = _selected_stamp_alpha(context, layer_bounds, stamp_bounds)
        if np.any(alpha):
            coverage[ly0:ly1, lx0:lx1] = np.maximum(coverage[ly0:ly1, lx0:lx1], alpha)
    return coverage


def _soften_or_sharpen_rgb(
    rgb: np.ndarray,
    settings: TextureEditorToolSettings,
    effective_size: float,
) -> Tuple[np.ndarray, float]:
    strength = max(0.0, min(1.0, settings.strength / 100.0))
    sigma = max(0.8, float(effective_size) / 28.0)
    if settings.tool != "sharpen":
        mode = getattr(settings, "soften_mode", "gaussian")
        if mode == "median":
            kernel = max(3, int(round(effective_size / 18.0)) * 2 + 1)
            result = cv2.medianBlur(np.clip(np.round(rgb), 0, 255).astype(np.uint8), kernel).astype(np.float32)
        elif mode == "surface":
            diameter = max(3, int(round(effective_size / 12.0)) * 2 + 1)
            result = cv2.bilateralFilter(
                np.clip(np.round(rgb), 0, 255).astype(np.uint8),
                diameter,
                12.0 + strength * 36.0,
                6.0 + strength * 20.0,
            ).astype(np.float32)
        else:
            result = cv2.GaussianBlur(rgb, (0, 0), sigmaX=sigma, sigmaY=sigma)
        return result, 0.03 + strength * 0.22
    mode = getattr(settings, "sharpen_mode", "unsharp_mask")
    if mode == "high_pass":
        blurred = cv2.GaussianBlur(rgb, (0, 0), sigmaX=sigma * 1.6, sigmaY=sigma * 1.6)
        return np.clip(rgb + (rgb - blurred) * (0.04 + strength * 0.20), 0.0, 255.0), 0.08 + strength * 0.34
    if mode == "local_contrast":
        blurred = cv2.GaussianBlur(rgb, (0, 0), sigmaX=sigma * 2.2, sigmaY=sigma * 2.2)
        return np.clip(rgb + (rgb - blurred) * (0.03 + strength * 0.12), 0.0, 255.0), 0.07 + strength * 0.30
    blurred = cv2.GaussianBlur(rgb, (0, 0), sigmaX=sigma, sigmaY=sigma)
    amount = 0.05 + strength * 0.42
    result = np.clip(cv2.addWeighted(rgb, 1.0 + amount, blurred, -amount, 0.0), 0.0, 255.0)
    return result, 0.06 + strength * 0.34


def _apply_soften_or_sharpen(
    context: _StrokeContext,
    settings: TextureEditorToolSettings,
) -> Dict[str, np.ndarray]:
    if context.sample_snapshot is None:
        return context.updated
    coverage = _stroke_coverage(context)
    if not np.any(coverage):
        return context.updated
    rgba = context.active.copy()
    processed_rgb, blend_strength = _soften_or_sharpen_rgb(
        context.sample_snapshot[..., :3].astype(np.float32),
        settings,
        context.effective_size,
    )
    processed = context.sample_snapshot.copy()
    processed[..., :3] = np.clip(np.round(processed_rgb), 0, 255).astype(np.uint8)
    blended = _blend_patch(rgba, processed, np.clip(coverage * blend_strength, 0.0, 1.0))
    context.updated[context.document.active_layer_id] = _apply_stroke_locks(context, rgba, blended)
    return context.updated


def _apply_smudge_point(
    context: _StrokeContext,
    settings: TextureEditorToolSettings,
    point_index: int,
    bounds: Tuple[int, int, int, int],
    alpha: np.ndarray,
) -> None:
    if context.sample_snapshot is None:
        return
    previous = context.stroke_points[0] if point_index == 0 else context.stroke_points[point_index - 1]
    previous_clip = _clip_stroke_to_active_layer(context, previous)
    if previous_clip is None:
        return
    lx0, ly0, lx1, ly1 = bounds
    px0, py0, px1, py1 = previous_clip[0]
    width, height = min(lx1 - lx0, px1 - px0), min(ly1 - ly0, py1 - py0)
    if width <= 0 or height <= 0:
        return
    source = context.sample_snapshot[py0:py0 + height, px0:px0 + width].copy()
    target = context.active[ly0:ly0 + height, lx0:lx0 + width]
    changed = _apply_smudge_patch(
        target,
        source,
        alpha[:height, :width],
        max(0.0, min(1.0, getattr(settings, "smudge_strength", 45) / 100.0)),
    )
    context.active[ly0:ly0 + height, lx0:lx0 + width] = _apply_stroke_locks(context, target, changed)


def _apply_clone_or_heal_point(
    context: _StrokeContext,
    settings: TextureEditorToolSettings,
    point: Tuple[int, int],
    bounds: Tuple[int, int, int, int],
    alpha: np.ndarray,
) -> None:
    if context.sample_snapshot is None or context.clone_delta is None:
        return
    if getattr(settings, "clone_aligned", True):
        source_center = (point[0] + context.clone_delta[0], point[1] + context.clone_delta[1])
    else:
        source_center = tuple(int(value) for value in settings.clone_source_point)
    if settings.sample_visible_layers:
        source_clip = _clip_stamp_region(source_center, context.stamp, context.document.width, context.document.height)
        patch_source = context.source_canvas
    else:
        local = (
            int(source_center[0] - context.active_layer.offset_x),
            int(source_center[1] - context.active_layer.offset_y),
        )
        source_clip = _clip_stamp_region(local, context.stamp, context.layer_width, context.layer_height)
        patch_source = context.sample_snapshot
    if source_clip is None or patch_source is None:
        return
    lx0, ly0, lx1, ly1 = bounds
    px0, py0, px1, py1 = source_clip[0]
    width, height = min(lx1 - lx0, px1 - px0), min(ly1 - ly0, py1 - py0)
    if width <= 0 or height <= 0:
        return
    patch = patch_source[py0:py0 + height, px0:px0 + width].copy()
    target = context.active[ly0:ly0 + height, lx0:lx0 + width]
    if settings.tool == "heal":
        patch_rgb, target_rgb = patch[..., :3].astype(np.float32), target[..., :3].astype(np.float32)
        patch[..., :3] = np.clip(np.round(patch_rgb * 0.7 + target_rgb * 0.3), 0, 255).astype(np.uint8)
    changed = _blend_patch(target, patch, alpha[:height, :width])
    context.active[ly0:ly0 + height, lx0:lx0 + width] = _apply_stroke_locks(context, target, changed)


def _apply_stroke_point(
    context: _StrokeContext,
    settings: TextureEditorToolSettings,
    point_index: int,
    point: Tuple[int, int],
) -> None:
    clipped = _clip_stroke_to_active_layer(context, point)
    if clipped is None:
        return
    bounds, stamp_bounds = clipped
    lx0, ly0, lx1, ly1 = bounds
    alpha = _selected_stamp_alpha(context, bounds, stamp_bounds)
    if not np.any(alpha):
        return
    region = context.active[ly0:ly1, lx0:lx1]
    if settings.tool == "paint":
        changed = _blend_constant_color(region, alpha, context.color_rgb, mode=getattr(settings, "paint_blend_mode", "normal"))
        context.active[ly0:ly1, lx0:lx1] = _apply_stroke_locks(context, region, changed)
    elif settings.tool == "erase":
        changed = region.copy().astype(np.float32)
        changed[..., 3] = np.clip(np.round((changed[..., 3] / 255.0) * (1.0 - alpha) * 255.0), 0, 255)
        context.active[ly0:ly1, lx0:lx1] = _apply_stroke_locks(context, region, changed.astype(np.uint8))
    elif settings.tool == "smudge":
        _apply_smudge_point(context, settings, point_index, bounds, alpha)
    elif settings.tool == "dodge_burn":
        changed = _apply_dodge_burn_region(
            region,
            alpha,
            exposure=max(0.0, min(1.0, getattr(settings, "dodge_burn_exposure", 20) / 100.0)),
            mode=str(getattr(settings, "dodge_burn_mode", "dodge_midtones")),
        )
        context.active[ly0:ly1, lx0:lx1] = _apply_stroke_locks(context, region, changed)
    elif settings.tool in {"clone", "heal"}:
        _apply_clone_or_heal_point(context, settings, point, bounds, alpha)


def apply_texture_editor_stroke(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    tool_settings: TextureEditorToolSettings,
    points: Sequence[Tuple[int, int]],
    *,
    source_snapshot: Optional[np.ndarray] = None,
    mutate_active_layer: bool = False,
) -> Dict[str, np.ndarray]:
    updated, context = _prepare_stroke_context(
        document,
        layer_pixels,
        tool_settings,
        points,
        source_snapshot=source_snapshot,
        mutate_active_layer=mutate_active_layer,
    )
    if context is None:
        return updated
    if tool_settings.tool in {"soften", "sharpen"}:
        return _apply_soften_or_sharpen(context, tool_settings)
    for index, point in enumerate(context.stroke_points):
        _apply_stroke_point(context, tool_settings, index, point)
    return context.updated
