"""Texture Editor layer, adjustment, and snapshot rules."""

from __future__ import annotations

import dataclasses
import time
import uuid
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from cdmw.domain.textures.editor_common import _new_layer_id, _safe_slug
from cdmw.domain.textures.editor_composite import (
    _apply_mask_to_src_region,
    _flatten_texture_editor_raster_layers,
    _layer_canvas_intersection,
)
from cdmw.domain.textures.editor_selection_masks import build_texture_editor_selection_mask
from cdmw.models import (
    TextureEditorAdjustmentLayer,
    TextureEditorDocument,
    TextureEditorHistoryEntry,
    TextureEditorLayer,
)


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

def capture_texture_editor_snapshot(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    label: str,
) -> Dict[str, object]:
    layer_blobs: Dict[str, bytes] = {}
    for layer_id, pixels in layer_pixels.items():
        encoded = cv2.imencode(".png", cv2.cvtColor(np.asarray(pixels, dtype=np.uint8), cv2.COLOR_RGBA2BGRA))[1]
        layer_blobs[layer_id] = bytes(encoded)
    return {
        "entry": TextureEditorHistoryEntry(label=label, timestamp=time.time()),
        "document": dataclasses.replace(document),
        "layer_blobs": layer_blobs,
    }

def restore_texture_editor_snapshot(snapshot: Dict[str, object]) -> Tuple[TextureEditorDocument, Dict[str, np.ndarray], TextureEditorHistoryEntry]:
    document = dataclasses.replace(snapshot["document"])  # type: ignore[arg-type]
    entry = snapshot["entry"]  # type: ignore[assignment]
    layer_pixels: Dict[str, np.ndarray] = {}
    for layer_id, blob in (snapshot.get("layer_blobs") or {}).items():
        decoded = cv2.imdecode(np.frombuffer(blob, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if decoded is None:
            continue
        if decoded.ndim == 2:
            decoded = cv2.cvtColor(decoded, cv2.COLOR_GRAY2BGRA)
        elif decoded.shape[2] == 3:
            decoded = cv2.cvtColor(decoded, cv2.COLOR_BGR2BGRA)
        rgba = cv2.cvtColor(decoded, cv2.COLOR_BGRA2RGBA)
        layer_pixels[str(layer_id)] = np.asarray(rgba, dtype=np.uint8).copy()
    return document, layer_pixels, entry

def extract_texture_editor_selection(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    layer_id: str,
) -> Optional[Tuple[np.ndarray, Tuple[int, int, int, int]]]:
    pixels = layer_pixels.get(layer_id)
    layer = next((candidate for candidate in document.layers if candidate.layer_id == layer_id), None)
    if pixels is None or layer is None:
        return None
    selection_mask = build_texture_editor_selection_mask(document.width, document.height, document.selection)
    if selection_mask is None:
        return None
    intersection = _layer_canvas_intersection(layer, pixels, document)
    if intersection is None:
        return None
    dx0, dy0, dx1, dy1, sx0, sy0, sx1, sy1 = intersection
    layer_selection = selection_mask[dy0:dy1, dx0:dx1]
    if not np.any(layer_selection):
        return None
    ys, xs = np.where(layer_selection > 0)
    if xs.size == 0 or ys.size == 0:
        return None
    min_x = int(xs.min())
    min_y = int(ys.min())
    max_x = int(xs.max()) + 1
    max_y = int(ys.max()) + 1
    local_pixels = pixels[sy0 + min_y:sy0 + max_y, sx0 + min_x:sx0 + max_x].copy()
    if layer.mask_layer_id and layer.mask_enabled:
        mask_pixels = layer_pixels.get(layer.mask_layer_id)
        if mask_pixels is not None:
            local_mask = mask_pixels[sy0 + min_y:sy0 + max_y, sx0 + min_x:sx0 + max_x]
            if local_mask.shape[:2] == local_pixels.shape[:2]:
                local_pixels = _apply_mask_to_src_region(local_pixels, local_mask)
    local_alpha = np.clip(layer_selection[min_y:max_y, min_x:max_x].astype(np.float32) / 255.0, 0.0, 1.0)[..., None]
    extracted = local_pixels.copy()
    extracted[..., 3:4] = np.clip(
        np.round(extracted[..., 3:4].astype(np.float32) * local_alpha),
        0,
        255,
    ).astype(np.uint8)
    return extracted, (dx0 + min_x, dy0 + min_y, max_x - min_x, max_y - min_y)

def add_texture_editor_layer(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    *,
    name: str = "New Layer",
    initial_pixels: Optional[np.ndarray] = None,
    offset_x: int = 0,
    offset_y: int = 0,
    blend_mode: str = "normal",
) -> Tuple[TextureEditorDocument, Dict[str, np.ndarray], str]:
    new_id = _new_layer_id()
    new_layer = TextureEditorLayer(
        layer_id=new_id,
        name=name,
        relative_png_path=f"layers/{_safe_slug(name)}.png",
        visible=True,
        opacity=100,
        blend_mode=blend_mode,
        offset_x=int(offset_x),
        offset_y=int(offset_y),
        revision=0,
        thumbnail_cache_key=uuid.uuid4().hex,
    )
    layers = list(document.layers)
    layers.append(new_layer)
    new_pixels = dict(layer_pixels)
    if initial_pixels is None:
        new_pixels[new_id] = np.zeros((document.height, document.width, 4), dtype=np.uint8)
    else:
        new_pixels[new_id] = np.asarray(initial_pixels, dtype=np.uint8).copy()
    return dataclasses.replace(document, layers=tuple(layers), active_layer_id=new_id), new_pixels, new_id

def duplicate_texture_editor_layer(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    layer_id: str,
) -> Tuple[TextureEditorDocument, Dict[str, np.ndarray], Optional[str]]:
    source_layer = next((layer for layer in document.layers if layer.layer_id == layer_id), None)
    if source_layer is None or layer_id not in layer_pixels:
        return document, layer_pixels, None
    new_id = _new_layer_id()
    duplicated = dataclasses.replace(
        source_layer,
        layer_id=new_id,
        name=f"{source_layer.name} Copy",
        revision=int(source_layer.revision) + 1,
        thumbnail_cache_key=uuid.uuid4().hex,
    )
    layers = list(document.layers)
    insert_at = layers.index(source_layer) + 1
    layers.insert(insert_at, duplicated)
    new_pixels = dict(layer_pixels)
    new_pixels[new_id] = layer_pixels[layer_id].copy()
    if source_layer.mask_layer_id and source_layer.mask_layer_id in layer_pixels:
        duplicated_mask_id = _new_layer_id()
        duplicated = dataclasses.replace(
            duplicated,
            mask_layer_id=duplicated_mask_id,
            thumbnail_cache_key=uuid.uuid4().hex,
        )
        layers[insert_at] = duplicated
        new_pixels[duplicated_mask_id] = layer_pixels[source_layer.mask_layer_id].copy()
    return dataclasses.replace(document, layers=tuple(layers), active_layer_id=new_id), new_pixels, new_id

def remove_texture_editor_layer(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    layer_id: str,
) -> Tuple[TextureEditorDocument, Dict[str, np.ndarray]]:
    if len(document.layers) <= 1:
        return document, layer_pixels
    removed_layer = next((layer for layer in document.layers if layer.layer_id == layer_id), None)
    if removed_layer is None:
        return document, layer_pixels
    removed_auxiliary_ids = {layer_id}
    if removed_layer.mask_layer_id:
        removed_auxiliary_ids.add(removed_layer.mask_layer_id)
    layers: List[TextureEditorLayer] = []
    for layer in document.layers:
        if layer.layer_id == layer_id:
            continue
        next_mask_layer_id = layer.mask_layer_id
        next_revision = int(layer.revision)
        next_thumbnail_cache_key = layer.thumbnail_cache_key
        if next_mask_layer_id in removed_auxiliary_ids:
            next_mask_layer_id = ""
            next_revision += 1
            next_thumbnail_cache_key = uuid.uuid4().hex
        layers.append(
            dataclasses.replace(
                layer,
                mask_layer_id=next_mask_layer_id,
                revision=next_revision,
                thumbnail_cache_key=next_thumbnail_cache_key,
            )
        )
    new_pixels = dict(layer_pixels)
    for removed_id in removed_auxiliary_ids:
        new_pixels.pop(removed_id, None)
    adjustment_layers: List[TextureEditorAdjustmentLayer] = []
    for adjustment in document.adjustment_layers:
        if adjustment.mask_layer_id in removed_auxiliary_ids:
            adjustment_layers.append(
                dataclasses.replace(
                    adjustment,
                    mask_layer_id="",
                    revision=int(adjustment.revision) + 1,
                )
            )
        else:
            adjustment_layers.append(adjustment)
    active_layer_id = document.active_layer_id
    if active_layer_id == layer_id:
        active_layer_id = layers[-1].layer_id
    return (
        dataclasses.replace(
            document,
            layers=tuple(layers),
            adjustment_layers=tuple(adjustment_layers),
            active_layer_id=active_layer_id,
            composite_revision=int(document.composite_revision) + 1,
        ),
        new_pixels,
    )

def merge_texture_editor_layer_down(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    layer_id: str,
) -> Tuple[TextureEditorDocument, Dict[str, np.ndarray]]:
    layers = list(document.layers)
    current_index = next((index for index, layer in enumerate(layers) if layer.layer_id == layer_id), -1)
    if current_index <= 0:
        return document, layer_pixels
    top_layer = layers[current_index]
    bottom_layer = layers[current_index - 1]
    top_pixels = layer_pixels.get(top_layer.layer_id)
    bottom_pixels = layer_pixels.get(bottom_layer.layer_id)
    if top_pixels is None or bottom_pixels is None:
        return document, layer_pixels
    merge_pixels = {
        bottom_layer.layer_id: bottom_pixels,
        top_layer.layer_id: top_pixels,
    }
    for auxiliary_id in (bottom_layer.mask_layer_id, top_layer.mask_layer_id):
        if auxiliary_id and auxiliary_id in layer_pixels:
            merge_pixels[auxiliary_id] = layer_pixels[auxiliary_id]
    merge_document = dataclasses.replace(
        document,
        layers=(bottom_layer, top_layer),
        active_layer_id=bottom_layer.layer_id,
        adjustment_layers=(),
    )
    merged_pixels = _flatten_texture_editor_raster_layers(merge_document, merge_pixels)
    new_pixels = dict(layer_pixels)
    new_pixels[bottom_layer.layer_id] = merged_pixels
    new_pixels.pop(top_layer.layer_id, None)
    layers[current_index - 1] = dataclasses.replace(
        bottom_layer,
        offset_x=0,
        offset_y=0,
        opacity=100,
        blend_mode="normal",
        mask_layer_id="",
        mask_enabled=True,
        revision=int(bottom_layer.revision) + 1,
        thumbnail_cache_key=uuid.uuid4().hex,
    )
    del layers[current_index]
    updated_document = dataclasses.replace(
        document,
        layers=tuple(layers),
        active_layer_id=bottom_layer.layer_id,
        composite_revision=int(document.composite_revision) + 1,
    )
    referenced_auxiliary_ids = {
        layer.mask_layer_id
        for layer in updated_document.layers
        if layer.mask_layer_id
    }
    referenced_auxiliary_ids.update(
        adjustment.mask_layer_id
        for adjustment in updated_document.adjustment_layers
        if adjustment.mask_layer_id
    )
    for auxiliary_id in {top_layer.mask_layer_id, bottom_layer.mask_layer_id}:
        if auxiliary_id and auxiliary_id not in referenced_auxiliary_ids:
            new_pixels.pop(auxiliary_id, None)
    return updated_document, new_pixels

def reorder_texture_editor_layer(
    document: TextureEditorDocument,
    layer_id: str,
    *,
    direction: int,
) -> TextureEditorDocument:
    layers = list(document.layers)
    index = next((pos for pos, layer in enumerate(layers) if layer.layer_id == layer_id), -1)
    if index < 0:
        return document
    target = index + int(direction)
    if target < 0 or target >= len(layers):
        return document
    layers[index], layers[target] = layers[target], layers[index]
    return dataclasses.replace(document, layers=tuple(layers))

def move_texture_editor_layer(
    document: TextureEditorDocument,
    layer_id: str,
    *,
    dx: int,
    dy: int,
) -> TextureEditorDocument:
    if dx == 0 and dy == 0:
        return document
    layer = next((candidate for candidate in document.layers if candidate.layer_id == layer_id), None)
    if layer is None or layer.locked:
        return document
    return update_texture_editor_layer(
        document,
        layer_id,
        offset_x=int(layer.offset_x + dx),
        offset_y=int(layer.offset_y + dy),
    )

def set_texture_editor_layer_mask_enabled(
    document: TextureEditorDocument,
    layer_id: str,
    enabled: bool,
) -> TextureEditorDocument:
    layer = next((candidate for candidate in document.layers if candidate.layer_id == layer_id), None)
    if layer is None:
        return document
    updated_layers = [
        dataclasses.replace(
            candidate,
            mask_enabled=bool(enabled) if candidate.layer_id == layer_id else candidate.mask_enabled,
            revision=(candidate.revision + 1) if candidate.layer_id == layer_id else candidate.revision,
            thumbnail_cache_key=uuid.uuid4().hex if candidate.layer_id == layer_id else candidate.thumbnail_cache_key,
        )
        for candidate in document.layers
    ]
    return dataclasses.replace(document, layers=tuple(updated_layers))

def invert_texture_editor_layer_mask(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    layer_id: str,
) -> Dict[str, np.ndarray]:
    layer = next((candidate for candidate in document.layers if candidate.layer_id == layer_id), None)
    if layer is None or not layer.mask_layer_id or layer.mask_layer_id not in layer_pixels:
        return layer_pixels
    new_pixels = dict(layer_pixels)
    mask_pixels = new_pixels[layer.mask_layer_id].copy()
    mask_pixels[..., :3] = 255 - mask_pixels[..., :3]
    mask_pixels[..., 3] = 255 - mask_pixels[..., 3]
    new_pixels[layer.mask_layer_id] = mask_pixels
    return new_pixels

def delete_texture_editor_layer_mask(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    layer_id: str,
) -> Tuple[TextureEditorDocument, Dict[str, np.ndarray]]:
    layer = next((candidate for candidate in document.layers if candidate.layer_id == layer_id), None)
    if layer is None or not layer.mask_layer_id:
        return document, layer_pixels
    mask_layer_id = layer.mask_layer_id
    updated_layers = [
        dataclasses.replace(
            candidate,
            mask_layer_id="" if candidate.layer_id == layer_id else candidate.mask_layer_id,
            mask_enabled=False if candidate.layer_id == layer_id else candidate.mask_enabled,
            revision=(candidate.revision + 1) if candidate.layer_id == layer_id else candidate.revision,
            thumbnail_cache_key=uuid.uuid4().hex if candidate.layer_id == layer_id else candidate.thumbnail_cache_key,
        )
        for candidate in document.layers
    ]
    new_pixels = dict(layer_pixels)
    new_pixels.pop(mask_layer_id, None)
    return dataclasses.replace(document, layers=tuple(updated_layers)), new_pixels

def add_texture_editor_adjustment_layer(
    document: TextureEditorDocument,
    *,
    adjustment_type: str,
    name: str,
    parameters: Optional[Dict[str, float]] = None,
) -> TextureEditorDocument:
    adjustment = TextureEditorAdjustmentLayer(
        layer_id=_new_layer_id(),
        name=name,
        adjustment_type=adjustment_type,
        parameters=dict(parameters or {}),
        revision=0,
    )
    return dataclasses.replace(
        document,
        adjustment_layers=tuple(list(document.adjustment_layers) + [adjustment]),
        composite_revision=int(document.composite_revision) + 1,
    )

def update_texture_editor_adjustment_layer(
    document: TextureEditorDocument,
    adjustment_layer_id: str,
    *,
    enabled: Optional[bool] = None,
    opacity: Optional[int] = None,
    parameters: Optional[Dict[str, float]] = None,
    mask_layer_id: Optional[str] = None,
    name: Optional[str] = None,
) -> TextureEditorDocument:
    updated: List[TextureEditorAdjustmentLayer] = []
    changed = False
    for layer in document.adjustment_layers:
        if layer.layer_id != adjustment_layer_id:
            updated.append(layer)
            continue
        changed = True
        next_params = dict(layer.parameters)
        if parameters is not None:
            next_params.update(parameters)
        updated.append(
            dataclasses.replace(
                layer,
                name=name if name is not None else layer.name,
                enabled=bool(enabled) if enabled is not None else layer.enabled,
                opacity=int(opacity) if opacity is not None else layer.opacity,
                parameters=next_params,
                mask_layer_id=mask_layer_id if mask_layer_id is not None else layer.mask_layer_id,
                revision=int(layer.revision) + 1,
            )
        )
    if not changed:
        return document
    return dataclasses.replace(
        document,
        adjustment_layers=tuple(updated),
        composite_revision=int(document.composite_revision) + 1,
    )

def remove_texture_editor_adjustment_layer(
    document: TextureEditorDocument,
    adjustment_layer_id: str,
) -> TextureEditorDocument:
    remaining = tuple(layer for layer in document.adjustment_layers if layer.layer_id != adjustment_layer_id)
    if len(remaining) == len(document.adjustment_layers):
        return document
    return dataclasses.replace(document, adjustment_layers=remaining, composite_revision=int(document.composite_revision) + 1)
