"""Texture Editor selection and channel-edit rules."""

from __future__ import annotations

import dataclasses
from typing import Dict, Optional, Sequence, Tuple

import cv2
import numpy as np

from cdmw.domain.textures.editor_brush import (
    _build_effective_brush_stamp,
    _clip_stamp_region,
    _effective_brush_size,
    _interpolate_stroke,
    texture_editor_stroke_points_for_symmetry,
)
from cdmw.domain.textures.editor_composite import _layer_canvas_intersection, _resize_array
from cdmw.domain.textures.editor_layers import bump_texture_editor_layer_revision, create_texture_editor_layer_mask
from cdmw.domain.textures.editor_selection_masks import (
    _combine_selection_masks,
    _selection_from_mask,
    build_texture_editor_selection_mask,
)
from cdmw.models import TextureEditorDocument, TextureEditorSelection, TextureEditorToolSettings


def clear_texture_editor_selection(document: TextureEditorDocument) -> TextureEditorDocument:
    current = document.selection
    return dataclasses.replace(
        document,
        selection=TextureEditorSelection(
            inverted=False,
            feather_radius=max(0, int(current.feather_radius)),
        ),
        floating_selection=None,
    )

def apply_texture_editor_rect_selection(
    document: TextureEditorDocument,
    rect: Tuple[int, int, int, int],
    *,
    combine_mode: str = "replace",
) -> TextureEditorDocument:
    x, y, w, h = rect
    incoming = np.zeros((document.height, document.width), dtype=np.uint8)
    x0 = max(0, min(document.width, int(x)))
    y0 = max(0, min(document.height, int(y)))
    x1 = max(x0, min(document.width, int(x + w)))
    y1 = max(y0, min(document.height, int(y + h)))
    if x1 > x0 and y1 > y0:
        incoming[y0:y1, x0:x1] = 255
    existing = build_texture_editor_selection_mask(document.width, document.height, document.selection)
    combined = _combine_selection_masks(existing, incoming, combine_mode=combine_mode)
    return dataclasses.replace(
        document,
        selection=_selection_from_mask(
            combined,
            feather_radius=max(0, int(document.selection.feather_radius)),
        ),
    )

def apply_texture_editor_lasso_selection(
    document: TextureEditorDocument,
    polygon_points: Sequence[Tuple[float, float]],
    *,
    combine_mode: str = "replace",
) -> TextureEditorDocument:
    incoming = build_texture_editor_selection_mask(
        document.width,
        document.height,
        TextureEditorSelection(
            mode="lasso",
            polygon_points=tuple((float(x), float(y)) for x, y in polygon_points),
        ),
    )
    existing = build_texture_editor_selection_mask(document.width, document.height, document.selection)
    combined = _combine_selection_masks(existing, incoming, combine_mode=combine_mode)
    return dataclasses.replace(
        document,
        selection=_selection_from_mask(
            combined,
            feather_radius=max(0, int(document.selection.feather_radius)),
        ),
    )

def update_texture_editor_selection_settings(
    document: TextureEditorDocument,
    *,
    inverted: Optional[bool] = None,
    feather_radius: Optional[int] = None,
) -> TextureEditorDocument:
    selection = document.selection
    return dataclasses.replace(
        document,
        selection=dataclasses.replace(
            selection,
            inverted=selection.inverted if inverted is None else bool(inverted),
            feather_radius=max(0, int(selection.feather_radius if feather_radius is None else feather_radius)),
        ),
    )

def select_all_texture_editor(document: TextureEditorDocument) -> TextureEditorDocument:
    return dataclasses.replace(
        document,
        selection=TextureEditorSelection(
            mode="rect",
            rect=(0, 0, int(document.width), int(document.height)),
            inverted=False,
            feather_radius=max(0, int(document.selection.feather_radius)),
        ),
    )

def grow_texture_editor_selection(
    document: TextureEditorDocument,
    pixels: int,
) -> TextureEditorDocument:
    amount = max(0, int(pixels))
    mask = build_texture_editor_selection_mask(document.width, document.height, document.selection)
    if mask is None or amount <= 0:
        return document
    kernel_size = max(1, (amount * 2) + 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    grown = cv2.dilate(mask, kernel, iterations=1)
    return dataclasses.replace(
        document,
        selection=_selection_from_mask(
            grown,
            feather_radius=max(0, int(document.selection.feather_radius)),
        ),
    )

def shrink_texture_editor_selection(
    document: TextureEditorDocument,
    pixels: int,
) -> TextureEditorDocument:
    amount = max(0, int(pixels))
    mask = build_texture_editor_selection_mask(document.width, document.height, document.selection)
    if mask is None or amount <= 0:
        return document
    kernel_size = max(1, (amount * 2) + 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    shrunk = cv2.erode(mask, kernel, iterations=1)
    return dataclasses.replace(
        document,
        selection=_selection_from_mask(
            shrunk,
            feather_radius=max(0, int(document.selection.feather_radius)),
        ),
    )

def apply_texture_editor_selection_to_layer_mask(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    layer_id: str,
) -> Tuple[TextureEditorDocument, Dict[str, np.ndarray], Optional[str]]:
    selection_mask = build_texture_editor_selection_mask(document.width, document.height, document.selection)
    if selection_mask is None or not np.any(selection_mask > 0):
        return document, layer_pixels, None
    layer = next((candidate for candidate in document.layers if candidate.layer_id == layer_id), None)
    pixels = layer_pixels.get(layer_id)
    if layer is None or pixels is None:
        return document, layer_pixels, None
    updated_document, updated_pixels, mask_layer_id = create_texture_editor_layer_mask(document, layer_pixels, layer_id)
    if not mask_layer_id:
        return document, layer_pixels, None
    updated_layer = next((candidate for candidate in updated_document.layers if candidate.layer_id == layer_id), None)
    if updated_layer is None:
        return document, layer_pixels, None
    mask_pixels = np.zeros_like(updated_pixels.get(mask_layer_id, pixels), dtype=np.uint8)
    intersection = _layer_canvas_intersection(updated_layer, pixels, document)
    if intersection is not None:
        dx0, dy0, dx1, dy1, sx0, sy0, sx1, sy1 = intersection
        local_selection = selection_mask[dy0:dy1, dx0:dx1]
        if local_selection.shape[:2] == (sy1 - sy0, sx1 - sx0):
            mask_pixels[sy0:sy1, sx0:sx1, 0] = local_selection
            mask_pixels[sy0:sy1, sx0:sx1, 1] = local_selection
            mask_pixels[sy0:sy1, sx0:sx1, 2] = local_selection
            mask_pixels[sy0:sy1, sx0:sx1, 3] = local_selection
    updated_pixels[mask_layer_id] = mask_pixels
    updated_document = bump_texture_editor_layer_revision(updated_document, layer_id)
    return updated_document, updated_pixels, mask_layer_id

def load_texture_editor_layer_mask_as_selection(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    layer_id: str,
    *,
    combine_mode: str = "replace",
) -> TextureEditorDocument:
    layer = next((candidate for candidate in document.layers if candidate.layer_id == layer_id), None)
    pixels = layer_pixels.get(layer_id)
    if layer is None or pixels is None or not layer.mask_layer_id:
        return document
    mask_pixels = layer_pixels.get(layer.mask_layer_id)
    if mask_pixels is None:
        return document
    canvas_mask = np.zeros((document.height, document.width), dtype=np.uint8)
    intersection = _layer_canvas_intersection(layer, pixels, document)
    if intersection is None:
        return document
    dx0, dy0, dx1, dy1, sx0, sy0, sx1, sy1 = intersection
    mask_region = mask_pixels[sy0:sy1, sx0:sx1]
    if mask_region.shape[:2] != (dy1 - dy0, dx1 - dx0):
        return document
    canvas_mask[dy0:dy1, dx0:dx1] = mask_region[..., 3]
    existing = build_texture_editor_selection_mask(document.width, document.height, document.selection)
    combined = _combine_selection_masks(existing, canvas_mask, combine_mode=combine_mode)
    return dataclasses.replace(
        document,
        selection=_selection_from_mask(
            combined,
            feather_radius=max(0, int(document.selection.feather_radius)),
        ),
    )

def extract_texture_editor_layer_channel_to_rgba(
    pixels: np.ndarray,
    channel_key: str,
) -> np.ndarray:
    rgba = np.asarray(pixels, dtype=np.uint8)
    key = (channel_key or "alpha").strip().lower()
    channel_index = {
        "red": 0,
        "green": 1,
        "blue": 2,
        "alpha": 3,
    }.get(key, 3)
    channel = rgba[..., channel_index]
    extracted = np.stack(
        [channel, channel, channel, np.full_like(channel, 255, dtype=np.uint8)],
        axis=-1,
    )
    return np.ascontiguousarray(extracted, dtype=np.uint8)

def write_texture_editor_layer_luma_to_channel(
    pixels: np.ndarray,
    channel_key: str,
) -> np.ndarray:
    rgba = np.asarray(pixels, dtype=np.uint8)
    updated = rgba.copy()
    luma = np.clip(
        np.round(
            (rgba[..., 0].astype(np.float32) * 0.299)
            + (rgba[..., 1].astype(np.float32) * 0.587)
            + (rgba[..., 2].astype(np.float32) * 0.114)
        ),
        0.0,
        255.0,
    ).astype(np.uint8)
    channel_index = {
        "red": 0,
        "green": 1,
        "blue": 2,
        "alpha": 3,
    }.get((channel_key or "alpha").strip().lower(), 3)
    updated[..., channel_index] = luma
    return updated

def copy_texture_editor_layer_channel(
    pixels: np.ndarray,
    channel_key: str,
) -> np.ndarray:
    rgba = np.asarray(pixels, dtype=np.uint8)
    channel_index = {
        "red": 0,
        "green": 1,
        "blue": 2,
        "alpha": 3,
    }.get((channel_key or "alpha").strip().lower(), 3)
    return np.ascontiguousarray(rgba[..., channel_index].copy(), dtype=np.uint8)

def paste_texture_editor_channel_into_layer(
    pixels: np.ndarray,
    channel_key: str,
    channel_data: np.ndarray,
) -> np.ndarray:
    rgba = np.asarray(pixels, dtype=np.uint8)
    updated = rgba.copy()
    incoming = np.asarray(channel_data, dtype=np.uint8)
    if incoming.ndim == 3:
        incoming = incoming[..., 0]
    if incoming.shape[:2] != rgba.shape[:2]:
        incoming = _resize_array(incoming, rgba.shape[1], rgba.shape[0], nearest=False)
        if incoming.ndim == 3:
            incoming = incoming[..., 0]
    channel_index = {
        "red": 0,
        "green": 1,
        "blue": 2,
        "alpha": 3,
    }.get((channel_key or "alpha").strip().lower(), 3)
    updated[..., channel_index] = np.asarray(incoming, dtype=np.uint8)
    return updated

def swap_texture_editor_layer_channels(
    pixels: np.ndarray,
    channel_a: str,
    channel_b: str,
) -> np.ndarray:
    rgba = np.asarray(pixels, dtype=np.uint8)
    updated = rgba.copy()
    index_a = {
        "red": 0,
        "green": 1,
        "blue": 2,
        "alpha": 3,
    }.get((channel_a or "red").strip().lower(), 0)
    index_b = {
        "red": 0,
        "green": 1,
        "blue": 2,
        "alpha": 3,
    }.get((channel_b or "blue").strip().lower(), 2)
    if index_a == index_b:
        return updated
    temp = updated[..., index_a].copy()
    updated[..., index_a] = updated[..., index_b]
    updated[..., index_b] = temp
    return updated

def apply_texture_editor_selection_stroke(
    document: TextureEditorDocument,
    tool_settings: TextureEditorToolSettings,
    points: Sequence[Tuple[int, int]],
) -> TextureEditorDocument:
    mask = build_texture_editor_selection_mask(document.width, document.height, document.selection)
    if mask is None:
        mask = np.zeros((max(1, document.height), max(1, document.width)), dtype=np.uint8)
    updated_mask = np.asarray(mask, dtype=np.uint8).copy()
    effective_size = _effective_brush_size(tool_settings)
    spacing = max(1, int(round(effective_size * max(0.05, tool_settings.spacing / 100.0))))
    stroke_points = _interpolate_stroke(points, spacing, smoothing=max(0, int(getattr(tool_settings, "smoothing", 0))))
    if not stroke_points:
        return document
    stroke_points = texture_editor_stroke_points_for_symmetry(
        stroke_points,
        document.width,
        document.height,
        getattr(tool_settings, "symmetry_mode", "off"),
    )
    strength_percent = max(0, min(100, int(round(tool_settings.opacity * max(0.05, tool_settings.flow / 100.0)))))
    stamp = _build_effective_brush_stamp(tool_settings, size=effective_size, strength_percent=strength_percent)
    for point in stroke_points:
        clipped = _clip_stamp_region((int(point[0]), int(point[1])), stamp, document.width, document.height)
        if clipped is None:
            continue
        (x0, y0, x1, y1), (sx0, sy0, sx1, sy1) = clipped
        stamp_alpha = stamp[sy0:sy1, sx0:sx1]
        if not np.any(stamp_alpha):
            continue
        region = updated_mask[y0:y1, x0:x1].astype(np.float32) / 255.0
        if tool_settings.tool == "erase":
            region = region * (1.0 - stamp_alpha)
        else:
            region = np.maximum(region, stamp_alpha)
        updated_mask[y0:y1, x0:x1] = np.clip(np.round(region * 255.0), 0.0, 255.0).astype(np.uint8)
    return dataclasses.replace(
        document,
        selection=_selection_from_mask(
            updated_mask,
            feather_radius=max(0, int(document.selection.feather_radius)),
        ),
        quick_mask_enabled=True,
        composite_revision=int(document.composite_revision) + 1,
    )

def apply_texture_editor_selection_fill(
    document: TextureEditorDocument,
    tool_settings: TextureEditorToolSettings,
    point: Tuple[int, int],
) -> TextureEditorDocument:
    width = max(1, int(document.width))
    height = max(1, int(document.height))
    x = max(0, min(width - 1, int(point[0])))
    y = max(0, min(height - 1, int(point[1])))
    mask = build_texture_editor_selection_mask(width, height, document.selection)
    if mask is None:
        mask = np.zeros((height, width), dtype=np.uint8)
    updated_mask = np.asarray(mask, dtype=np.uint8).copy()
    fill_value = 0 if tool_settings.tool == "erase" else 255
    tolerance = max(0, min(255, int(getattr(tool_settings, "fill_tolerance", 24))))
    flags = 4 if bool(getattr(tool_settings, "fill_contiguous", True)) else 8
    working = updated_mask.copy()
    cv2.floodFill(
        working,
        None,
        (x, y),
        int(fill_value),
        loDiff=int(tolerance),
        upDiff=int(tolerance),
        flags=flags,
    )
    return dataclasses.replace(
        document,
        selection=_selection_from_mask(
            working,
            feather_radius=max(0, int(document.selection.feather_radius)),
        ),
        quick_mask_enabled=True,
        composite_revision=int(document.composite_revision) + 1,
    )

def load_texture_editor_layer_channel_as_selection(
    document: TextureEditorDocument,
    layer: TextureEditorLayer,
    pixels: np.ndarray,
    channel_key: str,
    *,
    mask_pixels: Optional[np.ndarray] = None,
    combine_mode: str = "replace",
) -> TextureEditorDocument:
    rgba = np.asarray(pixels, dtype=np.uint8)
    if rgba.ndim != 3 or rgba.shape[2] < 4:
        return document
    channel_index = {
        "red": 0,
        "green": 1,
        "blue": 2,
        "alpha": 3,
    }.get((channel_key or "alpha").strip().lower(), 3)
    canvas_mask = np.zeros((max(1, document.height), max(1, document.width)), dtype=np.uint8)
    intersection = _layer_canvas_intersection(layer, rgba, document)
    if intersection is None:
        return document
    dx0, dy0, dx1, dy1, sx0, sy0, sx1, sy1 = intersection
    channel_patch = rgba[sy0:sy1, sx0:sx1, channel_index].astype(np.uint8)
    if mask_pixels is not None and mask_pixels.shape[:2] == rgba.shape[:2]:
        channel_patch = np.clip(
            np.round(
                channel_patch.astype(np.float32)
                * (mask_pixels[sy0:sy1, sx0:sx1, 3].astype(np.float32) / 255.0)
            ),
            0.0,
            255.0,
        ).astype(np.uint8)
    canvas_mask[dy0:dy1, dx0:dx1] = np.maximum(canvas_mask[dy0:dy1, dx0:dx1], channel_patch)
    existing = build_texture_editor_selection_mask(document.width, document.height, document.selection)
    combined = _combine_selection_masks(existing, canvas_mask, combine_mode=combine_mode)
    return dataclasses.replace(
        document,
        selection=_selection_from_mask(
            combined,
            feather_radius=max(0, int(document.selection.feather_radius)),
        ),
        composite_revision=int(document.composite_revision) + 1,
    )

def write_texture_editor_selection_to_layer_channel(
    document: TextureEditorDocument,
    layer: TextureEditorLayer,
    pixels: np.ndarray,
    channel_key: str,
) -> np.ndarray:
    selection_mask = build_texture_editor_selection_mask(document.width, document.height, document.selection)
    if selection_mask is None or not np.any(selection_mask > 0):
        return pixels
    rgba = np.asarray(pixels, dtype=np.uint8)
    updated = rgba.copy()
    channel_index = {
        "red": 0,
        "green": 1,
        "blue": 2,
        "alpha": 3,
    }.get((channel_key or "alpha").strip().lower(), 3)
    intersection = _layer_canvas_intersection(layer, rgba, document)
    if intersection is None:
        return updated
    dx0, dy0, dx1, dy1, sx0, sy0, sx1, sy1 = intersection
    selection_patch = selection_mask[dy0:dy1, dx0:dx1]
    updated[sy0:sy1, sx0:sx1, channel_index] = selection_patch.astype(np.uint8)
    return updated
