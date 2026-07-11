"""Texture Editor document geometry and canvas transform rules."""

from __future__ import annotations

import dataclasses
import uuid
from typing import Dict, List, Sequence, Tuple

import cv2
import numpy as np

from cdmw.domain.textures.editor_composite import (
    _layer_canvas_intersection,
    _resize_array,
    flatten_texture_editor_layers,
)
from cdmw.domain.textures.editor_selection_masks import _selection_from_mask, build_texture_editor_selection_mask
from cdmw.models import TextureEditorDocument, TextureEditorLayer, TextureEditorSelection


def _blank_texture_editor_layer(
    document: TextureEditorDocument,
) -> Tuple[TextureEditorLayer, np.ndarray]:
    layer_id = _new_layer_id()
    layer = TextureEditorLayer(
        layer_id=layer_id,
        name="Base Layer",
        relative_png_path="layers/base_layer.png",
        visible=True,
        opacity=100,
        blend_mode="normal",
        offset_x=0,
        offset_y=0,
        revision=0,
        thumbnail_cache_key=uuid.uuid4().hex,
    )
    pixels = np.zeros((max(1, document.height), max(1, document.width), 4), dtype=np.uint8)
    return layer, pixels

def crop_texture_editor_document_to_bounds(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    bounds: Tuple[int, int, int, int],
) -> Tuple[TextureEditorDocument, Dict[str, np.ndarray]]:
    crop_x = max(0, min(document.width, int(bounds[0])))
    crop_y = max(0, min(document.height, int(bounds[1])))
    crop_w = max(0, int(bounds[2]))
    crop_h = max(0, int(bounds[3]))
    crop_x1 = min(document.width, crop_x + crop_w)
    crop_y1 = min(document.height, crop_y + crop_h)
    if crop_x1 <= crop_x or crop_y1 <= crop_y:
        return document, layer_pixels
    new_width = crop_x1 - crop_x
    new_height = crop_y1 - crop_y
    new_pixels: Dict[str, np.ndarray] = {}
    new_layers: List[TextureEditorLayer] = []
    for layer in document.layers:
        pixels = layer_pixels.get(layer.layer_id)
        if pixels is None:
            continue
        intersection = _layer_canvas_intersection(layer, pixels, document)
        if intersection is None:
            continue
        dx0, dy0, dx1, dy1, sx0, sy0, sx1, sy1 = intersection
        region_x0 = max(dx0, crop_x)
        region_y0 = max(dy0, crop_y)
        region_x1 = min(dx1, crop_x1)
        region_y1 = min(dy1, crop_y1)
        if region_x1 <= region_x0 or region_y1 <= region_y0:
            continue
        local_x0 = sx0 + (region_x0 - dx0)
        local_y0 = sy0 + (region_y0 - dy0)
        local_x1 = local_x0 + (region_x1 - region_x0)
        local_y1 = local_y0 + (region_y1 - region_y0)
        cropped_pixels = pixels[local_y0:local_y1, local_x0:local_x1].copy()
        if cropped_pixels.size == 0:
            continue
        next_mask_id = layer.mask_layer_id if layer.mask_layer_id in layer_pixels else ""
        if next_mask_id:
            mask_pixels = layer_pixels.get(next_mask_id)
            if mask_pixels is not None and mask_pixels.shape[:2] == pixels.shape[:2]:
                cropped_mask = mask_pixels[local_y0:local_y1, local_x0:local_x1].copy()
                if cropped_mask.size > 0:
                    new_pixels[next_mask_id] = cropped_mask
                else:
                    next_mask_id = ""
            else:
                next_mask_id = ""
        new_pixels[layer.layer_id] = cropped_pixels
        new_layers.append(
            dataclasses.replace(
                layer,
                offset_x=int(region_x0 - crop_x),
                offset_y=int(region_y0 - crop_y),
                mask_layer_id=next_mask_id,
                revision=int(layer.revision) + 1,
                thumbnail_cache_key=uuid.uuid4().hex,
            )
        )
    cropped_selection = build_texture_editor_selection_mask(document.width, document.height, document.selection)
    next_selection = TextureEditorSelection(inverted=False, feather_radius=max(0, int(document.selection.feather_radius)))
    if cropped_selection is not None:
        next_selection = _selection_from_mask(
            cropped_selection[crop_y:crop_y1, crop_x:crop_x1],
            feather_radius=max(0, int(document.selection.feather_radius)),
        )
    if not new_layers:
        blank_document = dataclasses.replace(document, width=new_width, height=new_height)
        blank_layer, blank_pixels = _blank_texture_editor_layer(blank_document)
        new_layers = [blank_layer]
        new_pixels = {blank_layer.layer_id: blank_pixels}
    available_auxiliary_ids = set(new_pixels.keys())
    updated_adjustments = tuple(
        dataclasses.replace(
            adjustment,
            mask_layer_id=adjustment.mask_layer_id if adjustment.mask_layer_id in available_auxiliary_ids else "",
            revision=int(adjustment.revision) + (0 if not adjustment.mask_layer_id or adjustment.mask_layer_id in available_auxiliary_ids else 1),
        )
        for adjustment in document.adjustment_layers
    )
    active_layer_id = document.active_layer_id if any(layer.layer_id == document.active_layer_id for layer in new_layers) else new_layers[-1].layer_id
    updated_document = dataclasses.replace(
        document,
        width=new_width,
        height=new_height,
        active_layer_id=active_layer_id,
        layers=tuple(new_layers),
        selection=next_selection,
        floating_selection=None,
        adjustment_layers=updated_adjustments,
        composite_revision=int(document.composite_revision) + 1,
    )
    return updated_document, new_pixels

def crop_texture_editor_document_to_selection(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
) -> Tuple[TextureEditorDocument, Dict[str, np.ndarray]]:
    selection_mask = build_texture_editor_selection_mask(document.width, document.height, document.selection)
    if selection_mask is None or not np.any(selection_mask > 0):
        return document, layer_pixels
    ys, xs = np.where(selection_mask > 0)
    if xs.size == 0 or ys.size == 0:
        return document, layer_pixels
    bounds = (int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))
    return crop_texture_editor_document_to_bounds(document, layer_pixels, bounds)

def trim_texture_editor_document_transparent_bounds(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
) -> Tuple[TextureEditorDocument, Dict[str, np.ndarray]]:
    flattened = flatten_texture_editor_layers(document, layer_pixels)
    alpha = flattened[..., 3]
    ys, xs = np.where(alpha > 0)
    if xs.size == 0 or ys.size == 0:
        return document, layer_pixels
    bounds = (int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))
    return crop_texture_editor_document_to_bounds(document, layer_pixels, bounds)

def flip_texture_editor_document(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    *,
    horizontal: bool,
    vertical: bool,
) -> Tuple[TextureEditorDocument, Dict[str, np.ndarray]]:
    if not horizontal and not vertical:
        return document, layer_pixels
    new_pixels = dict(layer_pixels)
    new_layers: List[TextureEditorLayer] = []
    for layer in document.layers:
        pixels = layer_pixels.get(layer.layer_id)
        if pixels is None:
            continue
        transformed = pixels.copy()
        if horizontal:
            transformed = np.ascontiguousarray(np.flip(transformed, axis=1))
        if vertical:
            transformed = np.ascontiguousarray(np.flip(transformed, axis=0))
        new_pixels[layer.layer_id] = transformed
        next_offset_x = int(document.width - layer.offset_x - pixels.shape[1]) if horizontal else int(layer.offset_x)
        next_offset_y = int(document.height - layer.offset_y - pixels.shape[0]) if vertical else int(layer.offset_y)
        if layer.mask_layer_id and layer.mask_layer_id in layer_pixels:
            mask_pixels = layer_pixels[layer.mask_layer_id]
            transformed_mask = mask_pixels.copy()
            if horizontal:
                transformed_mask = np.ascontiguousarray(np.flip(transformed_mask, axis=1))
            if vertical:
                transformed_mask = np.ascontiguousarray(np.flip(transformed_mask, axis=0))
            new_pixels[layer.mask_layer_id] = transformed_mask
        new_layers.append(
            dataclasses.replace(
                layer,
                offset_x=next_offset_x,
                offset_y=next_offset_y,
                revision=int(layer.revision) + 1,
                thumbnail_cache_key=uuid.uuid4().hex,
            )
        )
    selection_mask = build_texture_editor_selection_mask(document.width, document.height, document.selection)
    if selection_mask is not None:
        if horizontal:
            selection_mask = np.ascontiguousarray(np.flip(selection_mask, axis=1))
        if vertical:
            selection_mask = np.ascontiguousarray(np.flip(selection_mask, axis=0))
        next_selection = _selection_from_mask(
            selection_mask,
            feather_radius=max(0, int(document.selection.feather_radius)),
        )
    else:
        next_selection = TextureEditorSelection(inverted=False, feather_radius=max(0, int(document.selection.feather_radius)))
    updated_document = dataclasses.replace(
        document,
        layers=tuple(new_layers),
        selection=next_selection,
        composite_revision=int(document.composite_revision) + 1,
    )
    return updated_document, new_pixels

def rotate_texture_editor_document_90(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    *,
    clockwise: bool,
) -> Tuple[TextureEditorDocument, Dict[str, np.ndarray]]:
    new_width = int(document.height)
    new_height = int(document.width)
    rotation_k = 3 if clockwise else 1
    new_pixels = dict(layer_pixels)
    new_layers: List[TextureEditorLayer] = []
    for layer in document.layers:
        pixels = layer_pixels.get(layer.layer_id)
        if pixels is None:
            continue
        rotated = np.ascontiguousarray(np.rot90(pixels, rotation_k))
        new_pixels[layer.layer_id] = rotated
        old_h, old_w = pixels.shape[:2]
        if clockwise:
            next_offset_x = int(document.height - layer.offset_y - old_h)
            next_offset_y = int(layer.offset_x)
        else:
            next_offset_x = int(layer.offset_y)
            next_offset_y = int(document.width - layer.offset_x - old_w)
        if layer.mask_layer_id and layer.mask_layer_id in layer_pixels:
            mask_pixels = layer_pixels[layer.mask_layer_id]
            new_pixels[layer.mask_layer_id] = np.ascontiguousarray(np.rot90(mask_pixels, rotation_k))
        new_layers.append(
            dataclasses.replace(
                layer,
                offset_x=next_offset_x,
                offset_y=next_offset_y,
                revision=int(layer.revision) + 1,
                thumbnail_cache_key=uuid.uuid4().hex,
            )
        )
    selection_mask = build_texture_editor_selection_mask(document.width, document.height, document.selection)
    if selection_mask is not None:
        selection_mask = np.ascontiguousarray(np.rot90(selection_mask, rotation_k))
        next_selection = _selection_from_mask(
            selection_mask,
            feather_radius=max(0, int(document.selection.feather_radius)),
        )
    else:
        next_selection = TextureEditorSelection(inverted=False, feather_radius=max(0, int(document.selection.feather_radius)))
    updated_document = dataclasses.replace(
        document,
        width=new_width,
        height=new_height,
        layers=tuple(new_layers),
        selection=next_selection,
        composite_revision=int(document.composite_revision) + 1,
    )
    return updated_document, new_pixels

def resize_texture_editor_document_image(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    new_width: int,
    new_height: int,
) -> Tuple[TextureEditorDocument, Dict[str, np.ndarray]]:
    target_width = max(1, int(new_width))
    target_height = max(1, int(new_height))
    if target_width == int(document.width) and target_height == int(document.height):
        return document, layer_pixels
    scale_x = float(target_width) / max(1.0, float(document.width))
    scale_y = float(target_height) / max(1.0, float(document.height))
    new_pixels: Dict[str, np.ndarray] = {}
    new_layers: List[TextureEditorLayer] = []
    resized_mask_ids: set[str] = set()
    for layer in document.layers:
        pixels = layer_pixels.get(layer.layer_id)
        if pixels is None:
            continue
        resized = _resize_array(
            pixels,
            max(1, int(round(pixels.shape[1] * scale_x))),
            max(1, int(round(pixels.shape[0] * scale_y))),
        )
        new_pixels[layer.layer_id] = resized
        next_mask_id = layer.mask_layer_id if layer.mask_layer_id in layer_pixels else ""
        if next_mask_id and next_mask_id not in resized_mask_ids:
            mask_pixels = layer_pixels[next_mask_id]
            new_pixels[next_mask_id] = _resize_array(
                mask_pixels,
                max(1, int(round(mask_pixels.shape[1] * scale_x))),
                max(1, int(round(mask_pixels.shape[0] * scale_y))),
            )
            resized_mask_ids.add(next_mask_id)
        new_layers.append(
            dataclasses.replace(
                layer,
                offset_x=int(round(layer.offset_x * scale_x)),
                offset_y=int(round(layer.offset_y * scale_y)),
                revision=int(layer.revision) + 1,
                thumbnail_cache_key=uuid.uuid4().hex,
            )
        )
    selection_mask = build_texture_editor_selection_mask(document.width, document.height, document.selection)
    if selection_mask is not None:
        resized_selection = _resize_array(selection_mask, target_width, target_height, nearest=False)
        next_selection = _selection_from_mask(
            resized_selection,
            feather_radius=max(0, int(document.selection.feather_radius)),
        )
    else:
        next_selection = TextureEditorSelection(inverted=False, feather_radius=max(0, int(document.selection.feather_radius)))
    next_floating = document.floating_selection
    if next_floating is not None:
        bounds = next_floating.bounds
        next_floating = dataclasses.replace(
            next_floating,
            bounds=(
                int(round(bounds[0] * scale_x)),
                int(round(bounds[1] * scale_y)),
                max(1, int(round(bounds[2] * scale_x))),
                max(1, int(round(bounds[3] * scale_y))),
            ),
            offset_x=int(round(next_floating.offset_x * scale_x)),
            offset_y=int(round(next_floating.offset_y * scale_y)),
        )
    updated_document = dataclasses.replace(
        document,
        width=target_width,
        height=target_height,
        layers=tuple(new_layers),
        selection=next_selection,
        floating_selection=next_floating,
        composite_revision=int(document.composite_revision) + 1,
    )
    return updated_document, new_pixels

def resize_texture_editor_document_canvas(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    new_width: int,
    new_height: int,
    *,
    anchor: str = "top_left",
) -> Tuple[TextureEditorDocument, Dict[str, np.ndarray]]:
    target_width = max(1, int(new_width))
    target_height = max(1, int(new_height))
    if target_width == int(document.width) and target_height == int(document.height):
        return document, layer_pixels
    anchor_key = (anchor or "top_left").strip().lower()
    if anchor_key == "center":
        delta_x = int(round((target_width - int(document.width)) / 2.0))
        delta_y = int(round((target_height - int(document.height)) / 2.0))
    else:
        delta_x = 0
        delta_y = 0
    new_layers = tuple(
        dataclasses.replace(
            layer,
            offset_x=int(layer.offset_x + delta_x),
            offset_y=int(layer.offset_y + delta_y),
            revision=int(layer.revision) + 1,
            thumbnail_cache_key=uuid.uuid4().hex,
        )
        for layer in document.layers
    )
    selection_mask = build_texture_editor_selection_mask(document.width, document.height, document.selection)
    if selection_mask is not None:
        next_mask = np.zeros((target_height, target_width), dtype=np.uint8)
        src_x0 = max(0, -delta_x)
        src_y0 = max(0, -delta_y)
        dst_x0 = max(0, delta_x)
        dst_y0 = max(0, delta_y)
        copy_width = min(int(document.width) - src_x0, target_width - dst_x0)
        copy_height = min(int(document.height) - src_y0, target_height - dst_y0)
        if copy_width > 0 and copy_height > 0:
            next_mask[dst_y0:dst_y0 + copy_height, dst_x0:dst_x0 + copy_width] = selection_mask[
                src_y0:src_y0 + copy_height,
                src_x0:src_x0 + copy_width,
            ]
        next_selection = _selection_from_mask(
            next_mask,
            feather_radius=max(0, int(document.selection.feather_radius)),
        )
    else:
        next_selection = TextureEditorSelection(inverted=False, feather_radius=max(0, int(document.selection.feather_radius)))
    next_floating = document.floating_selection
    if next_floating is not None:
        bounds = next_floating.bounds
        next_floating = dataclasses.replace(
            next_floating,
            bounds=(
                int(bounds[0] + delta_x),
                int(bounds[1] + delta_y),
                int(bounds[2]),
                int(bounds[3]),
            ),
            offset_x=int(next_floating.offset_x + delta_x),
            offset_y=int(next_floating.offset_y + delta_y),
        )
    updated_document = dataclasses.replace(
        document,
        width=target_width,
        height=target_height,
        layers=new_layers,
        selection=next_selection,
        floating_selection=next_floating,
        composite_revision=int(document.composite_revision) + 1,
    )
    return updated_document, dict(layer_pixels)

def snap_lasso_points_to_edges(
    rgba_image: np.ndarray,
    polygon_points: Sequence[Tuple[float, float]],
    *,
    search_radius: int = 10,
    edge_sensitivity: int = 55,
) -> List[Tuple[float, float]]:
    if len(polygon_points) < 3:
        return [(float(x), float(y)) for x, y in polygon_points]
    radius = max(1, int(search_radius))
    sensitivity = max(1, min(100, int(edge_sensitivity)))
    rgba = np.asarray(rgba_image, dtype=np.uint8)
    gray = cv2.cvtColor(rgba, cv2.COLOR_RGBA2GRAY)
    blurred = cv2.GaussianBlur(gray, (0, 0), sigmaX=1.2, sigmaY=1.2)
    high = max(40, min(220, int(round(210 - (sensitivity * 1.4)))))
    low = max(10, int(round(high * 0.45)))
    edges = cv2.Canny(blurred, low, high)
    snapped: List[Tuple[float, float]] = []
    height, width = edges.shape[:2]
    for x, y in polygon_points:
        px = max(0, min(width - 1, int(round(float(x)))))
        py = max(0, min(height - 1, int(round(float(y)))))
        x0 = max(0, px - radius)
        y0 = max(0, py - radius)
        x1 = min(width, px + radius + 1)
        y1 = min(height, py + radius + 1)
        patch = edges[y0:y1, x0:x1]
        if patch.size == 0 or not np.any(patch):
            snapped.append((float(px), float(py)))
            continue
        ys, xs = np.where(patch > 0)
        best_x = px
        best_y = py
        best_dist = None
        for local_x, local_y in zip(xs, ys):
            candidate_x = x0 + int(local_x)
            candidate_y = y0 + int(local_y)
            dist = ((candidate_x - px) ** 2) + ((candidate_y - py) ** 2)
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_x = candidate_x
                best_y = candidate_y
        snapped.append((float(best_x), float(best_y)))
    deduped: List[Tuple[float, float]] = []
    for point in snapped:
        if not deduped or deduped[-1] != point:
            deduped.append(point)
    return deduped
