"""Compatibility exports and file-output helpers for Texture Editor raster rules."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, List

import cv2
import numpy as np

from cdmw.core.texture_editor import _safe_slug, save_rgba_array_png
from cdmw.domain.textures.editor_brush import (
    _apply_dodge_burn_region,
    _apply_smudge_patch,
    _blend_constant_color,
    _blend_patch,
    _build_brush_stamp,
    _build_custom_brush_stamp,
    _build_effective_brush_stamp,
    _clip_stamp_region,
    _effective_brush_size,
    _interpolate_stroke,
    _load_custom_brush_tip_alpha,
    _smooth_stroke_points,
    apply_texture_editor_stroke,
    texture_editor_stroke_points_for_symmetry,
)
from cdmw.domain.textures.editor_composite import (
    _adjustment_mask_canvas_region,
    _adjustment_target_mask,
    _apply_adjustment_to_rgba,
    _apply_channel_edit_locks,
    _apply_mask_to_src_region,
    _blend_layer_region,
    _blend_rgb_mode,
    _build_curves_lut,
    _channel_edit_flags,
    _document_bounds,
    _flatten_texture_editor_raster_layers,
    _flatten_texture_editor_raster_layers_region,
    _layer_canvas_intersection,
    _resize_array,
    _trim_rgba_transparent_bounds,
    flatten_texture_editor_layers,
    flatten_texture_editor_layers_region,
)
from cdmw.domain.textures.editor_document import (
    _blank_texture_editor_layer,
    crop_texture_editor_document_to_bounds,
    crop_texture_editor_document_to_selection,
    flip_texture_editor_document,
    resize_texture_editor_document_canvas,
    resize_texture_editor_document_image,
    rotate_texture_editor_document_90,
    snap_lasso_points_to_edges,
    trim_texture_editor_document_transparent_bounds,
)
from cdmw.domain.textures.editor_raster_tools import (
    _blend_gradient_color,
    _blend_rgb,
    _match_rgb_luma,
    apply_texture_editor_fill,
    apply_texture_editor_gradient,
    apply_texture_editor_patch,
    apply_texture_editor_recolor,
)
from cdmw.domain.textures.editor_selection import (
    apply_texture_editor_lasso_selection,
    apply_texture_editor_rect_selection,
    apply_texture_editor_selection_fill,
    apply_texture_editor_selection_stroke,
    apply_texture_editor_selection_to_layer_mask,
    clear_texture_editor_selection,
    copy_texture_editor_layer_channel,
    extract_texture_editor_layer_channel_to_rgba,
    grow_texture_editor_selection,
    load_texture_editor_layer_channel_as_selection,
    load_texture_editor_layer_mask_as_selection,
    paste_texture_editor_channel_into_layer,
    select_all_texture_editor,
    shrink_texture_editor_selection,
    swap_texture_editor_layer_channels,
    update_texture_editor_selection_settings,
    write_texture_editor_layer_luma_to_channel,
    write_texture_editor_selection_to_layer_channel,
)
from cdmw.domain.textures.editor_selection_masks import (
    _combine_selection_masks,
    _decode_selection_mask_png,
    _encode_selection_mask_png,
    _selection_from_mask,
    _selection_mask_to_polygons,
    build_texture_editor_selection_mask,
)
from cdmw.models import TextureEditorDocument


_expand_stroke_points_for_symmetry = texture_editor_stroke_points_for_symmetry


def export_texture_editor_flattened_png(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    output_path: Path,
) -> Path:
    flattened = flatten_texture_editor_layers(document, layer_pixels)
    return save_rgba_array_png(flattened, output_path.expanduser().resolve())

def export_texture_editor_region_png(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    output_path: Path,
    bounds: Tuple[int, int, int, int],
    *,
    padding: int = 0,
    trim_transparent: bool = False,
) -> Path:
    normalized = _document_bounds(document, bounds)
    if normalized is None:
        raise ValueError("Region export bounds are empty.")
    crop_x, crop_y, crop_width, crop_height = normalized
    flattened = flatten_texture_editor_layers(document, layer_pixels)
    region = flattened[crop_y:crop_y + crop_height, crop_x:crop_x + crop_width].copy()
    if trim_transparent:
        region = _trim_rgba_transparent_bounds(region)
    pad_amount = max(0, int(padding))
    if pad_amount > 0:
        region = cv2.copyMakeBorder(
            region,
            pad_amount,
            pad_amount,
            pad_amount,
            pad_amount,
            cv2.BORDER_CONSTANT,
            value=(0, 0, 0, 0),
        )
    return save_rgba_array_png(region, output_path.expanduser().resolve())

def export_texture_editor_grid_slices(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    output_dir: Path,
    *,
    cell_width: int,
    cell_height: int,
    padding: int = 0,
    trim_transparent: bool = False,
    skip_empty: bool = True,
) -> List[Path]:
    grid_w = max(1, int(cell_width))
    grid_h = max(1, int(cell_height))
    pad_amount = max(0, int(padding))
    output_root = output_dir.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    flattened = flatten_texture_editor_layers(document, layer_pixels)
    exported: List[Path] = []
    rows = int(math.ceil(float(document.height) / float(grid_h)))
    cols = int(math.ceil(float(document.width) / float(grid_w)))
    for row in range(rows):
        for col in range(cols):
            x = col * grid_w
            y = row * grid_h
            x1 = min(int(document.width), x + grid_w)
            y1 = min(int(document.height), y + grid_h)
            if x1 <= x or y1 <= y:
                continue
            tile = flattened[y:y1, x:x1].copy()
            if skip_empty and not np.any(tile[..., 3] > 0):
                continue
            if trim_transparent:
                tile = _trim_rgba_transparent_bounds(tile)
            if pad_amount > 0:
                tile = cv2.copyMakeBorder(
                    tile,
                    pad_amount,
                    pad_amount,
                    pad_amount,
                    pad_amount,
                    cv2.BORDER_CONSTANT,
                    value=(0, 0, 0, 0),
                )
            file_name = f"{_safe_slug(document.title)}_r{row:02d}_c{col:02d}.png"
            exported.append(save_rgba_array_png(tile, output_root / file_name))
    return exported
