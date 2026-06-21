from __future__ import annotations

import base64
import dataclasses
import json
import math
import time
import uuid
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np
from PIL import Image

from cdmw.core.texture_pipeline.inspection import parse_dds
from cdmw.core.texture_pipeline.preview import ensure_dds_display_preview_png
from cdmw.core.upscale_profiles import infer_texture_semantics, is_technical_texture_type
from cdmw.models import (
    DdsInfo,
    TextureEditorAdjustmentLayer,
    TextureEditorDocument,
    TextureEditorFloatingSelection,
    TextureEditorHistoryEntry,
    TextureEditorLayer,
    TextureEditorSelection,
    TextureEditorSourceBinding,
    TextureEditorToolSettings,
)

_PROJECT_VERSION = 1
_VISIBLE_TEXTURE_TYPES = {"color", "ui", "emissive", "impostor", "unknown"}






def _safe_slug(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value.strip())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or "texture_editor"


def _normalize_hex(value: str, fallback: str) -> str:
    text = value.strip().upper()
    if not text:
        return fallback.upper()
    if not text.startswith("#"):
        text = f"#{text}"
    if len(text) != 7:
        return fallback.upper()
    try:
        int(text[1:], 16)
    except Exception:
        return fallback.upper()
    return text


def _parse_hex_rgb(value: str, fallback: str = "#C85A30") -> Tuple[int, int, int]:
    text = _normalize_hex(value, fallback)
    return (int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16))


def _new_layer_id() -> str:
    return uuid.uuid4().hex[:12]


def _load_rgba_array(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
        return np.asarray(rgba, dtype=np.uint8).copy()


def save_rgba_array_png(array: np.ndarray, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.asarray(array, dtype=np.uint8), "RGBA").save(output_path, format="PNG")
    return output_path




























































































































































































def update_texture_editor_layer(
    document: TextureEditorDocument,
    layer_id: str,
    *,
    name: Optional[str] = None,
    visible: Optional[bool] = None,
    opacity: Optional[int] = None,
    blend_mode: Optional[str] = None,
    offset_x: Optional[int] = None,
    offset_y: Optional[int] = None,
    locked: Optional[bool] = None,
    alpha_locked: Optional[bool] = None,
    mask_layer_id: Optional[str] = None,
    mask_enabled: Optional[bool] = None,
) -> TextureEditorDocument:
    updated_layers: List[TextureEditorLayer] = []
    for layer in document.layers:
        if layer.layer_id != layer_id:
            updated_layers.append(layer)
            continue
        updated_layers.append(
            dataclasses.replace(
                layer,
                name=name if name is not None else layer.name,
                visible=visible if visible is not None else layer.visible,
                opacity=int(opacity) if opacity is not None else layer.opacity,
                blend_mode=blend_mode if blend_mode is not None else layer.blend_mode,
                offset_x=int(offset_x) if offset_x is not None else layer.offset_x,
                offset_y=int(offset_y) if offset_y is not None else layer.offset_y,
                locked=bool(locked) if locked is not None else layer.locked,
                alpha_locked=bool(alpha_locked) if alpha_locked is not None else layer.alpha_locked,
                mask_layer_id=str(mask_layer_id) if mask_layer_id is not None else layer.mask_layer_id,
                mask_enabled=bool(mask_enabled) if mask_enabled is not None else layer.mask_enabled,
                revision=int(layer.revision) + 1,
                thumbnail_cache_key=uuid.uuid4().hex,
            )
        )
    return dataclasses.replace(document, layers=tuple(updated_layers))


def bump_texture_editor_layer_revision(
    document: TextureEditorDocument,
    layer_id: str,
) -> TextureEditorDocument:
    layer = next((candidate for candidate in document.layers if candidate.layer_id == layer_id), None)
    if layer is None:
        return document
    return update_texture_editor_layer(document, layer_id)




def create_texture_editor_layer_mask(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    layer_id: str,
) -> Tuple[TextureEditorDocument, Dict[str, np.ndarray], Optional[str]]:
    layer = next((candidate for candidate in document.layers if candidate.layer_id == layer_id), None)
    pixels = layer_pixels.get(layer_id)
    if layer is None or pixels is None:
        return document, layer_pixels, None
    if layer.mask_layer_id and layer.mask_layer_id in layer_pixels:
        updated_document = update_texture_editor_layer(document, layer_id, mask_enabled=True)
        return updated_document, dict(layer_pixels), layer.mask_layer_id
    mask_layer_id = _new_layer_id()
    mask_pixels = np.full_like(pixels, 255, dtype=np.uint8)
    mask_pixels[..., 0] = 255
    mask_pixels[..., 1] = 255
    mask_pixels[..., 2] = 255
    mask_pixels[..., 3] = 255
    updated_layers = []
    for candidate in document.layers:
        if candidate.layer_id != layer_id:
            updated_layers.append(candidate)
            continue
        updated_layers.append(
            dataclasses.replace(
                candidate,
                mask_layer_id=mask_layer_id,
                mask_enabled=True,
                revision=int(candidate.revision) + 1,
                thumbnail_cache_key=uuid.uuid4().hex,
            )
        )
    updated_document = dataclasses.replace(document, layers=tuple(updated_layers))
    new_pixels = dict(layer_pixels)
    new_pixels[mask_layer_id] = mask_pixels
    return updated_document, new_pixels, mask_layer_id

from cdmw.core.texture_editor_project_io import (
    make_texture_editor_workspace_root,
    build_texture_editor_document_root,
    normalize_texture_editor_source_to_png,
    derive_texture_editor_binding,
    create_texture_editor_document_from_source,
    _selection_to_dict,
    _selection_from_dict,
    _floating_selection_to_dict,
    _floating_selection_from_dict,
    _adjustment_layer_to_dict,
    _adjustment_layer_from_dict,
    save_texture_editor_project,
    load_texture_editor_project,
)

from cdmw.core.texture_editor_raster_ops import (
    _selection_mask_to_polygons,
    _encode_selection_mask_png,
    _decode_selection_mask_png,
    _selection_from_mask,
    _combine_selection_masks,
    _effective_brush_size,
    _expand_stroke_points_for_symmetry,
    _resize_array,
    _load_custom_brush_tip_alpha,
    _build_custom_brush_stamp,
    _smooth_stroke_points,
    _channel_edit_flags,
    _apply_channel_edit_locks,
    _layer_canvas_intersection,
    _blend_rgb_mode,
    _blend_layer_region,
    _apply_mask_to_src_region,
    _build_curves_lut,
    _adjustment_target_mask,
    _trim_rgba_transparent_bounds,
    _apply_adjustment_to_rgba,
    _flatten_texture_editor_raster_layers,
    _document_bounds,
    _adjustment_mask_canvas_region,
    _flatten_texture_editor_raster_layers_region,
    flatten_texture_editor_layers,
    flatten_texture_editor_layers_region,
    export_texture_editor_flattened_png,
    export_texture_editor_region_png,
    export_texture_editor_grid_slices,
    build_texture_editor_selection_mask,
    clear_texture_editor_selection,
    apply_texture_editor_rect_selection,
    apply_texture_editor_lasso_selection,
    update_texture_editor_selection_settings,
    select_all_texture_editor,
    grow_texture_editor_selection,
    shrink_texture_editor_selection,
    apply_texture_editor_selection_to_layer_mask,
    load_texture_editor_layer_mask_as_selection,
    extract_texture_editor_layer_channel_to_rgba,
    write_texture_editor_layer_luma_to_channel,
    copy_texture_editor_layer_channel,
    paste_texture_editor_channel_into_layer,
    swap_texture_editor_layer_channels,
    apply_texture_editor_selection_stroke,
    apply_texture_editor_selection_fill,
    load_texture_editor_layer_channel_as_selection,
    write_texture_editor_selection_to_layer_channel,
    _blank_texture_editor_layer,
    crop_texture_editor_document_to_bounds,
    crop_texture_editor_document_to_selection,
    trim_texture_editor_document_transparent_bounds,
    flip_texture_editor_document,
    rotate_texture_editor_document_90,
    resize_texture_editor_document_image,
    resize_texture_editor_document_canvas,
    snap_lasso_points_to_edges,
    _build_brush_stamp,
    _build_effective_brush_stamp,
    _interpolate_stroke,
    _clip_stamp_region,
    _blend_constant_color,
    _blend_patch,
    _apply_smudge_patch,
    _apply_dodge_burn_region,
    _blend_gradient_color,
    _match_rgb_luma,
    _blend_rgb,
    apply_texture_editor_recolor,
    apply_texture_editor_stroke,
    apply_texture_editor_fill,
    apply_texture_editor_gradient,
    apply_texture_editor_patch,
)

from cdmw.core.texture_editor_layer_ops import (
    capture_texture_editor_snapshot,
    restore_texture_editor_snapshot,
    extract_texture_editor_selection,
    add_texture_editor_layer,
    duplicate_texture_editor_layer,
    remove_texture_editor_layer,
    merge_texture_editor_layer_down,
    reorder_texture_editor_layer,
    move_texture_editor_layer,
    set_texture_editor_layer_mask_enabled,
    invert_texture_editor_layer_mask,
    delete_texture_editor_layer_mask,
    add_texture_editor_adjustment_layer,
    update_texture_editor_adjustment_layer,
    remove_texture_editor_adjustment_layer,
)
