"""Texture Editor selection-mask construction and combination rules."""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

import cv2
import numpy as np

from cdmw.models import TextureEditorSelection


def _selection_mask_to_polygons(mask: np.ndarray) -> Tuple[Tuple[Tuple[float, float], ...], ...]:
    binary = np.asarray(mask > 0, dtype=np.uint8)
    if not np.any(binary):
        return ()
    contours, hierarchy = cv2.findContours(binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is not None and hierarchy.size:
        flattened_hierarchy = np.asarray(hierarchy).reshape(-1, 4)
        if np.any(flattened_hierarchy[:, 3] >= 0):
            return ()
    polygons: List[Tuple[Tuple[float, float], ...]] = []
    for contour in contours:
        if contour.shape[0] < 3:
            continue
        epsilon = max(0.35, cv2.arcLength(contour, True) * 0.002)
        simplified = cv2.approxPolyDP(contour, epsilon, closed=True)
        points = tuple((float(point[0][0]), float(point[0][1])) for point in simplified)
        if len(points) >= 3:
            polygons.append(points)
    polygons.sort(key=lambda polygon: len(polygon), reverse=True)
    return tuple(polygons)

def _encode_selection_mask_png(mask: Optional[np.ndarray]) -> bytes:
    if mask is None:
        return b""
    array = np.asarray(mask, dtype=np.uint8)
    if array.size == 0 or not np.any(array):
        return b""
    encoded = cv2.imencode(".png", array)[1]
    return bytes(encoded)

def _decode_selection_mask_png(blob: bytes, width: int, height: int) -> Optional[np.ndarray]:
    if not blob or width <= 0 or height <= 0:
        return None
    decoded = cv2.imdecode(np.frombuffer(blob, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if decoded is None:
        return None
    if decoded.ndim == 3:
        decoded = decoded[..., -1]
    mask = np.asarray(decoded, dtype=np.uint8)
    if mask.shape[:2] != (height, width):
        return None
    return mask.copy()

def _selection_from_mask(
    mask: Optional[np.ndarray],
    *,
    inverted: bool = False,
    feather_radius: int = 0,
) -> TextureEditorSelection:
    if mask is None or not np.any(mask):
        return TextureEditorSelection(inverted=False, feather_radius=max(0, int(feather_radius)))
    polygons = _selection_mask_to_polygons(mask)
    if not polygons:
        return TextureEditorSelection(
            mode="mask",
            inverted=bool(inverted),
            feather_radius=max(0, int(feather_radius)),
            mask_png_blob=_encode_selection_mask_png(mask),
        )
    first_polygon = polygons[0]
    return TextureEditorSelection(
        mode="mask",
        polygon_points=first_polygon,
        mask_polygons=polygons,
        mask_png_blob=_encode_selection_mask_png(mask),
        inverted=bool(inverted),
        feather_radius=max(0, int(feather_radius)),
    )

def _combine_selection_masks(
    existing_mask: Optional[np.ndarray],
    incoming_mask: Optional[np.ndarray],
    *,
    combine_mode: str,
) -> Optional[np.ndarray]:
    incoming = np.asarray(incoming_mask, dtype=np.uint8) if incoming_mask is not None else None
    existing = np.asarray(existing_mask, dtype=np.uint8) if existing_mask is not None else None
    mode_key = (combine_mode or "replace").strip().lower()
    if mode_key == "replace" or existing is None:
        return incoming.copy() if incoming is not None else None
    if incoming is None:
        return existing.copy()
    if mode_key == "add":
        return np.maximum(existing, incoming)
    if mode_key == "subtract":
        result = existing.astype(np.int16) - incoming.astype(np.int16)
        return np.clip(result, 0, 255).astype(np.uint8)
    if mode_key == "intersect":
        return np.minimum(existing, incoming)
    return incoming.copy()

def build_texture_editor_selection_mask(
    width: int,
    height: int,
    selection: TextureEditorSelection,
) -> Optional[np.ndarray]:
    width = max(0, int(width))
    height = max(0, int(height))
    if width <= 0 or height <= 0 or selection.mode == "none":
        return None
    decoded_mask = _decode_selection_mask_png(selection.mask_png_blob, width, height)
    if decoded_mask is not None:
        mask = decoded_mask
    else:
        mask = np.zeros((height, width), dtype=np.uint8)
    if decoded_mask is None and selection.mask_polygons:
        for polygon_points in selection.mask_polygons:
            points = np.asarray(polygon_points, dtype=np.float32)
            if len(points) < 3:
                continue
            scale_factor = 4
            min_x = max(0, int(math.floor(float(np.min(points[:, 0])))) - 2)
            min_y = max(0, int(math.floor(float(np.min(points[:, 1])))) - 2)
            max_x = min(width, int(math.ceil(float(np.max(points[:, 0])))) + 3)
            max_y = min(height, int(math.ceil(float(np.max(points[:, 1])))) + 3)
            if max_x <= min_x or max_y <= min_y:
                continue
            patch_width = max_x - min_x
            patch_height = max_y - min_y
            supersampled = np.zeros((patch_height * scale_factor, patch_width * scale_factor), dtype=np.uint8)
            shifted = np.empty_like(points)
            shifted[:, 0] = (points[:, 0] - float(min_x)) * float(scale_factor)
            shifted[:, 1] = (points[:, 1] - float(min_y)) * float(scale_factor)
            polygon = np.round(shifted).astype(np.int32).reshape((-1, 1, 2))
            cv2.fillPoly(supersampled, [polygon], 255, lineType=cv2.LINE_AA)
            antialiased_patch = cv2.resize(
                supersampled,
                (patch_width, patch_height),
                interpolation=cv2.INTER_AREA,
            )
            current_patch = mask[min_y:max_y, min_x:max_x]
            mask[min_y:max_y, min_x:max_x] = np.maximum(current_patch, antialiased_patch)
    elif decoded_mask is None and selection.mode == "rect" and selection.rect is not None:
        x, y, w, h = selection.rect
        x0 = max(0, min(width, int(x)))
        y0 = max(0, min(height, int(y)))
        x1 = max(x0, min(width, int(x + w)))
        y1 = max(y0, min(height, int(y + h)))
        if x1 > x0 and y1 > y0:
            mask[y0:y1, x0:x1] = 255
    elif decoded_mask is None and selection.mode == "lasso" and selection.polygon_points:
        points = np.asarray(selection.polygon_points, dtype=np.float32)
        if len(points) >= 3:
            scale_factor = 4
            min_x = max(0, int(math.floor(float(np.min(points[:, 0])))) - 2)
            min_y = max(0, int(math.floor(float(np.min(points[:, 1])))) - 2)
            max_x = min(width, int(math.ceil(float(np.max(points[:, 0])))) + 3)
            max_y = min(height, int(math.ceil(float(np.max(points[:, 1])))) + 3)
            if max_x > min_x and max_y > min_y:
                patch_width = max_x - min_x
                patch_height = max_y - min_y
                supersampled = np.zeros((patch_height * scale_factor, patch_width * scale_factor), dtype=np.uint8)
                shifted = np.empty_like(points)
                shifted[:, 0] = (points[:, 0] - float(min_x)) * float(scale_factor)
                shifted[:, 1] = (points[:, 1] - float(min_y)) * float(scale_factor)
                polygon = np.round(shifted).astype(np.int32).reshape((-1, 1, 2))
                cv2.fillPoly(supersampled, [polygon], 255, lineType=cv2.LINE_AA)
                antialiased_patch = cv2.resize(
                    supersampled,
                    (patch_width, patch_height),
                    interpolation=cv2.INTER_AREA,
                )
                current_patch = mask[min_y:max_y, min_x:max_x]
                mask[min_y:max_y, min_x:max_x] = np.maximum(current_patch, antialiased_patch)
    if not np.any(mask):
        return None
    feather_radius = max(0, int(selection.feather_radius))
    if feather_radius > 0:
        kernel = max(3, feather_radius * 2 + 1)
        mask = cv2.GaussianBlur(mask, (kernel, kernel), sigmaX=max(0.8, feather_radius / 2.0))
    if selection.inverted:
        mask = 255 - mask
    return mask if np.any(mask) else None
