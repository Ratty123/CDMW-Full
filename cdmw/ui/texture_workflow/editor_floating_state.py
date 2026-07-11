from __future__ import annotations

"""Floating-selection image helpers for the standalone Texture Editor UI."""

import dataclasses
import math
from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Sequence, Tuple

import cv2
import numpy as np

from cdmw.domain.textures.editor_brush import texture_editor_stroke_points_for_symmetry
from cdmw.domain.textures.editor_composite import _blend_layer_region
from cdmw.domain.textures.editor_layers import (
    add_texture_editor_layer,
    bump_texture_editor_layer_revision,
)
from cdmw.domain.textures.editor_selection_masks import build_texture_editor_selection_mask
from cdmw.models import TextureEditorDocument, TextureEditorFloatingSelection, TextureEditorLayer, TextureEditorToolSettings
from cdmw.ui.texture_workflow.editor_clipboard_state import (
    texture_editor_cut_selection_status_text,
    texture_editor_layer_floating_label,
    texture_editor_selection_clipboard_payload,
    texture_editor_selection_floating_label,
)
from cdmw.ui.texture_workflow.editor_history_state import texture_editor_history_layer_canvas_offset
from cdmw.ui.texture_workflow.editor_layer_state import texture_editor_layer_pixel_target_state
from cdmw.ui.texture_workflow.editor_selection_state import (
    TextureEditorActiveLayerSelectionPayloadState,
    texture_editor_document_with_cleared_selection_only,
)


@dataclass(frozen=True, slots=True)
class TextureEditorFloatingCommitState:
    layer_name: str
    target_x: int
    target_y: int
    dirty_bounds: Tuple[int, int, int, int]
    history_label: str
    status_text: str


@dataclass(frozen=True, slots=True)
class TextureEditorFloatingCommittedLayerState:
    document: TextureEditorDocument
    layer_pixels: Dict[str, np.ndarray]
    layer_id: str
    dirty_bounds: Tuple[int, int, int, int]
    history_label: str
    status_text: str


@dataclass(frozen=True, slots=True)
class TextureEditorFloatingMoveState:
    document: TextureEditorDocument
    dirty_bounds: Tuple[int, int, int, int]
    history_label: str
    kind: str
    tracked_layer_ids: Tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TextureEditorFloatingLayerCopyState:
    can_float: bool
    pixels: Optional[np.ndarray]
    label: str
    bounds: Tuple[int, int, int, int]
    source_layer_id: str
    history_label: str
    status_text: str
    error: bool


@dataclass(frozen=True, slots=True)
class TextureEditorSetFloatingSelectionState:
    document: TextureEditorDocument
    floating_pixels: np.ndarray
    floating_mask: np.ndarray
    dirty_bounds: Tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class TextureEditorFloatingCutSelectionState:
    document: TextureEditorDocument
    layer_pixels: Dict[str, np.ndarray]
    before_layer_pixels: Dict[str, np.ndarray]
    floating_pixels: np.ndarray
    floating_mask: np.ndarray
    selection_clipboard: Tuple[np.ndarray, str, int, int]
    layer_id: str
    dirty_bounds: Tuple[int, int, int, int]
    history_label: str
    status_text: str
    kind: str
    tracked_layer_ids: Tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TextureEditorFloatingCanvasTransformState:
    current_bounds: Optional[Tuple[int, int, int, int]]
    origin_bounds: Optional[Tuple[int, int, int, int]]
    offset_x: int
    offset_y: int
    scale_x: float
    scale_y: float
    rotation_degrees: float


def texture_editor_layer_canvas_bounds(
    document: Optional[TextureEditorDocument],
    layer_pixels: Mapping[str, np.ndarray],
    layer_id: str,
) -> Optional[Tuple[int, int, int, int]]:
    if document is None or layer_id not in layer_pixels:
        return None
    pixels = layer_pixels[layer_id]
    offset_x, offset_y = texture_editor_history_layer_canvas_offset(document, layer_id)
    return (int(offset_x), int(offset_y), int(pixels.shape[1]), int(pixels.shape[0]))


def estimated_texture_editor_brush_dirty_bounds(
    document: Optional[TextureEditorDocument],
    tool_settings: TextureEditorToolSettings,
    points: Sequence[Tuple[int, int]],
    *,
    padding: Optional[int] = None,
) -> Optional[Tuple[int, int, int, int]]:
    if document is None or not points:
        return None
    brush_padding = padding if padding is not None else int(math.ceil(max(1.0, float(tool_settings.size)) * 0.75)) + 4
    dirty_points = texture_editor_stroke_points_for_symmetry(
        points,
        document.width,
        document.height,
        tool_settings.symmetry_mode,
    )
    xs = [int(point[0]) for point in dirty_points]
    ys = [int(point[1]) for point in dirty_points]
    x0 = max(0, min(xs) - brush_padding)
    y0 = max(0, min(ys) - brush_padding)
    x1 = min(int(document.width), max(xs) + brush_padding + 1)
    y1 = min(int(document.height), max(ys) + brush_padding + 1)
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1 - x0, y1 - y0)


def shift_texture_editor_pixels(
    pixels: np.ndarray,
    dx: int,
    dy: int,
    *,
    selection_mask: Optional[np.ndarray] = None,
) -> np.ndarray:
    if dx == 0 and dy == 0:
        return pixels.copy()
    height, width = pixels.shape[:2]
    shifted = np.zeros_like(pixels)
    src_x0 = max(0, -dx)
    src_y0 = max(0, -dy)
    src_x1 = min(width, width - dx) if dx >= 0 else width
    src_y1 = min(height, height - dy) if dy >= 0 else height
    dst_x0 = max(0, dx)
    dst_y0 = max(0, dy)
    dst_x1 = dst_x0 + max(0, src_x1 - src_x0)
    dst_y1 = dst_y0 + max(0, src_y1 - src_y0)
    if src_x1 > src_x0 and src_y1 > src_y0:
        shifted[dst_y0:dst_y1, dst_x0:dst_x1] = pixels[src_y0:src_y1, src_x0:src_x1]
    if selection_mask is None:
        return shifted
    selection_alpha = np.clip(selection_mask.astype(np.float32) / 255.0, 0.0, 1.0)[..., None]
    selected = np.clip(np.round(pixels.astype(np.float32) * selection_alpha), 0, 255).astype(np.uint8)
    remainder = np.clip(np.round(pixels.astype(np.float32) * (1.0 - selection_alpha)), 0, 255).astype(np.uint8)
    shifted_selected = shift_texture_editor_pixels(selected, dx, dy, selection_mask=None)
    return np.clip(remainder.astype(np.uint16) + shifted_selected.astype(np.uint16), 0, 255).astype(np.uint8)


def texture_editor_nontransparent_pixel_bounds(pixels: np.ndarray) -> Tuple[int, int, int, int]:
    alpha = pixels[..., 3]
    ys, xs = np.where(alpha > 0)
    if xs.size > 0 and ys.size > 0:
        return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    return (0, 0, int(pixels.shape[1]), int(pixels.shape[0]))


def texture_editor_float_layer_copy_history_label() -> str:
    return "Float Active Layer Copy"


def texture_editor_float_layer_copy_empty_status_text() -> str:
    return "The active layer does not contain any pixels to float."


def texture_editor_float_layer_copy_status_text(layer_name: str) -> str:
    return f"Floating copy created from '{layer_name}'."


def texture_editor_floating_layer_copy_state(
    document: Optional[TextureEditorDocument],
    layer_pixels: Mapping[str, np.ndarray],
    *,
    current_layer_id: Optional[str],
) -> TextureEditorFloatingLayerCopyState:
    empty_state = TextureEditorFloatingLayerCopyState(
        can_float=False,
        pixels=None,
        label="",
        bounds=(0, 0, 0, 0),
        source_layer_id="",
        history_label=texture_editor_float_layer_copy_history_label(),
        status_text="",
        error=False,
    )
    if document is None:
        return empty_state
    target = texture_editor_layer_pixel_target_state(
        document,
        current_layer_id=current_layer_id,
        layer_pixel_ids=layer_pixels.keys(),
    )
    layer_id = target.layer_id
    layer = target.layer
    if not target.available or layer is None:
        return empty_state
    pixels = layer_pixels[layer_id]
    x0, y0, x1, y1 = texture_editor_nontransparent_pixel_bounds(pixels)
    extracted = pixels[y0:y1, x0:x1].copy()
    if extracted.size == 0:
        return TextureEditorFloatingLayerCopyState(
            can_float=False,
            pixels=None,
            label="",
            bounds=(0, 0, 0, 0),
            source_layer_id=layer_id,
            history_label=texture_editor_float_layer_copy_history_label(),
            status_text=texture_editor_float_layer_copy_empty_status_text(),
            error=True,
        )
    bounds = (int(layer.offset_x + x0), int(layer.offset_y + y0), int(extracted.shape[1]), int(extracted.shape[0]))
    return TextureEditorFloatingLayerCopyState(
        can_float=True,
        pixels=extracted,
        label=texture_editor_layer_floating_label(layer.name),
        bounds=bounds,
        source_layer_id=layer_id,
        history_label=texture_editor_float_layer_copy_history_label(),
        status_text=texture_editor_float_layer_copy_status_text(layer.name),
        error=False,
    )


def texture_editor_set_floating_selection_state(
    document: TextureEditorDocument,
    pixels: np.ndarray,
    *,
    label: str,
    bounds: Tuple[int, int, int, int],
    source_layer_id: str = "",
    paste_mode: str = "in_place",
) -> TextureEditorSetFloatingSelectionState:
    floating_pixels = np.asarray(pixels, dtype=np.uint8).copy()
    normalized_bounds = (
        int(bounds[0]),
        int(bounds[1]),
        int(bounds[2]),
        int(bounds[3]),
    )
    updated_document = dataclasses.replace(
        document,
        floating_selection=TextureEditorFloatingSelection(
            source_layer_id=source_layer_id,
            label=label,
            bounds=normalized_bounds,
            offset_x=0,
            offset_y=0,
            committed=False,
            paste_mode=paste_mode,
        ),
    )
    updated_document = texture_editor_document_with_cleared_selection_only(updated_document)
    return TextureEditorSetFloatingSelectionState(
        document=updated_document,
        floating_pixels=floating_pixels,
        floating_mask=floating_pixels[..., 3].copy(),
        dirty_bounds=normalized_bounds,
    )


def texture_editor_cleared_floating_selection_state(document: TextureEditorDocument) -> TextureEditorDocument:
    if document.floating_selection is None:
        return document
    return dataclasses.replace(document, floating_selection=None)


def texture_editor_cut_selection_to_floating_state(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    selection_state: TextureEditorActiveLayerSelectionPayloadState,
    *,
    current_layer_id: Optional[str] = None,
    layer_id: str = "",
    layer: Optional[TextureEditorLayer] = None,
) -> Optional[TextureEditorFloatingCutSelectionState]:
    target_layer_id = str(layer_id or "")
    target_layer = layer
    if not target_layer_id:
        target = texture_editor_layer_pixel_target_state(
            document,
            current_layer_id=current_layer_id,
            layer_pixel_ids=layer_pixels.keys(),
        )
        target_layer_id = target.layer_id
        target_layer = target.layer
        if not target.has_pixels:
            return None
    if not target_layer_id or target_layer_id not in layer_pixels or target_layer is None:
        return None
    bounds = (
        int(selection_state.bounds[0]),
        int(selection_state.bounds[1]),
        int(selection_state.bounds[2]),
        int(selection_state.bounds[3]),
    )
    selection_mask = build_texture_editor_selection_mask(document.width, document.height, document.selection)
    updated_pixels = dict(layer_pixels)
    if selection_mask is not None:
        updated_pixels[target_layer_id] = clear_texture_editor_selection_from_layer_pixels(
            layer_pixels[target_layer_id],
            selection_mask,
            target_layer,
            bounds,
        )
    floating_state = texture_editor_set_floating_selection_state(
        document,
        selection_state.pixels,
        label=texture_editor_selection_floating_label(selection_state.label),
        bounds=bounds,
        source_layer_id=target_layer_id,
    )
    updated_document = bump_texture_editor_layer_revision(floating_state.document, target_layer_id)
    return TextureEditorFloatingCutSelectionState(
        document=updated_document,
        layer_pixels=updated_pixels,
        before_layer_pixels={target_layer_id: layer_pixels[target_layer_id].copy()},
        floating_pixels=floating_state.floating_pixels,
        floating_mask=floating_state.floating_mask,
        selection_clipboard=texture_editor_selection_clipboard_payload(selection_state),
        layer_id=target_layer_id,
        dirty_bounds=bounds,
        history_label="Cut Selection To Floating",
        status_text=texture_editor_cut_selection_status_text(),
        kind="floating_cut",
        tracked_layer_ids=(target_layer_id,),
    )


def clear_texture_editor_selection_from_layer_pixels(
    target_pixels: np.ndarray,
    selection_mask: Optional[np.ndarray],
    layer: TextureEditorLayer,
    bounds: Tuple[int, int, int, int],
) -> np.ndarray:
    if selection_mask is None:
        return target_pixels.copy()
    lx0 = int(bounds[0] - layer.offset_x)
    ly0 = int(bounds[1] - layer.offset_y)
    lx1 = lx0 + int(bounds[2])
    ly1 = ly0 + int(bounds[3])
    updated = target_pixels.copy()
    if not (0 <= lx0 < lx1 <= updated.shape[1] and 0 <= ly0 < ly1 <= updated.shape[0]):
        return updated
    local_mask = selection_mask[int(bounds[1]):int(bounds[1] + bounds[3]), int(bounds[0]):int(bounds[0] + bounds[2])]
    if local_mask.shape[:2] == (ly1 - ly0, lx1 - lx0):
        alpha = np.clip(local_mask.astype(np.float32) / 255.0, 0.0, 1.0)[..., None]
        cleared_region = updated[ly0:ly1, lx0:lx1].astype(np.float32)
        cleared_region *= (1.0 - alpha)
        updated[ly0:ly1, lx0:lx1] = np.clip(np.round(cleared_region), 0.0, 255.0).astype(np.uint8)
    else:
        updated[ly0:ly1, lx0:lx1] = 0
    return updated


def transformed_texture_editor_floating_pixels(
    floating: Optional[TextureEditorFloatingSelection],
    floating_pixels: Optional[np.ndarray],
) -> Optional[np.ndarray]:
    if floating is None or floating_pixels is None:
        return None
    pixels = floating_pixels.copy()
    if floating.flip_x:
        pixels = np.ascontiguousarray(np.flip(pixels, axis=1))
    if floating.flip_y:
        pixels = np.ascontiguousarray(np.flip(pixels, axis=0))
    scale_x = max(0.05, float(floating.scale_x))
    scale_y = max(0.05, float(floating.scale_y))
    if abs(scale_x - 1.0) > 1e-3 or abs(scale_y - 1.0) > 1e-3:
        new_w = max(1, int(round(pixels.shape[1] * scale_x)))
        new_h = max(1, int(round(pixels.shape[0] * scale_y)))
        interpolation = cv2.INTER_CUBIC if (new_w >= pixels.shape[1] and new_h >= pixels.shape[0]) else cv2.INTER_AREA
        pixels = cv2.resize(pixels, (new_w, new_h), interpolation=interpolation)
    angle = float(floating.rotation_degrees)
    if abs(angle) > 1e-3:
        height, width = pixels.shape[:2]
        center = (width / 2.0, height / 2.0)
        matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
        cos = abs(matrix[0, 0])
        sin = abs(matrix[0, 1])
        bound_w = max(1, int((height * sin) + (width * cos)))
        bound_h = max(1, int((height * cos) + (width * sin)))
        matrix[0, 2] += (bound_w / 2.0) - center[0]
        matrix[1, 2] += (bound_h / 2.0) - center[1]
        pixels = cv2.warpAffine(
            pixels,
            matrix,
            (bound_w, bound_h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0, 0),
        )
    return np.ascontiguousarray(pixels, dtype=np.uint8)


def texture_editor_snapshot_floating_pixels(floating_pixels: Optional[np.ndarray]) -> Optional[np.ndarray]:
    return None if floating_pixels is None else floating_pixels.copy()


def texture_editor_floating_commit_state(
    floating: Optional[TextureEditorFloatingSelection],
    transformed_pixels: Optional[np.ndarray],
) -> Optional[TextureEditorFloatingCommitState]:
    if floating is None or transformed_pixels is None:
        return None
    target_x = int(floating.bounds[0] + floating.offset_x)
    target_y = int(floating.bounds[1] + floating.offset_y)
    return TextureEditorFloatingCommitState(
        layer_name=f"{floating.label or 'Floating'} Layer",
        target_x=target_x,
        target_y=target_y,
        dirty_bounds=(target_x, target_y, int(transformed_pixels.shape[1]), int(transformed_pixels.shape[0])),
        history_label="Commit Floating Selection",
        status_text="Committed floating selection to a new layer.",
    )


def texture_editor_floating_committed_layer_state(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    transformed_pixels: Optional[np.ndarray],
) -> Optional[TextureEditorFloatingCommittedLayerState]:
    commit_state = texture_editor_floating_commit_state(document.floating_selection, transformed_pixels)
    if commit_state is None or transformed_pixels is None:
        return None
    updated_document, updated_pixels, layer_id = add_texture_editor_layer(
        document,
        layer_pixels,
        name=commit_state.layer_name,
        initial_pixels=transformed_pixels,
        offset_x=commit_state.target_x,
        offset_y=commit_state.target_y,
    )
    return TextureEditorFloatingCommittedLayerState(
        document=updated_document,
        layer_pixels=updated_pixels,
        layer_id=layer_id,
        dirty_bounds=commit_state.dirty_bounds,
        history_label=commit_state.history_label,
        status_text=commit_state.status_text,
    )


def texture_editor_floating_move_state(
    document: TextureEditorDocument,
    *,
    dx: int,
    dy: int,
) -> Optional[TextureEditorFloatingMoveState]:
    floating = document.floating_selection
    if floating is None:
        return None
    dirty_bounds = (
        int(floating.bounds[0] + min(0, floating.offset_x + int(dx))),
        int(floating.bounds[1] + min(0, floating.offset_y + int(dy))),
        max(1, int(floating.bounds[2] + abs(int(dx)))),
        max(1, int(floating.bounds[3] + abs(int(dy)))),
    )
    return TextureEditorFloatingMoveState(
        document=dataclasses.replace(
            document,
            floating_selection=dataclasses.replace(
                floating,
                offset_x=int(floating.offset_x + int(dx)),
                offset_y=int(floating.offset_y + int(dy)),
                committed=False,
            ),
        ),
        dirty_bounds=dirty_bounds,
        history_label="Move Floating Selection",
        kind="floating_transform",
        tracked_layer_ids=(),
    )


def texture_editor_floating_cancel_history_label() -> str:
    return "Cancel Floating Selection"


def texture_editor_floating_cancel_status_text() -> str:
    return "Canceled floating selection."


def texture_editor_floating_selection_updated_status_text() -> str:
    return "Updated floating selection on the canvas."


def current_texture_editor_floating_canvas_bounds(
    document: Optional[TextureEditorDocument],
    floating_pixels: Optional[np.ndarray],
) -> Optional[Tuple[int, int, int, int]]:
    if document is None or document.floating_selection is None or floating_pixels is None:
        return None
    transformed = transformed_texture_editor_floating_pixels(document.floating_selection, floating_pixels)
    if transformed is None:
        return None
    floating = document.floating_selection
    return (
        int(floating.bounds[0] + floating.offset_x),
        int(floating.bounds[1] + floating.offset_y),
        int(transformed.shape[1]),
        int(transformed.shape[0]),
    )


def texture_editor_floating_canvas_transform_state(
    document: Optional[TextureEditorDocument],
    floating_pixels: Optional[np.ndarray],
) -> TextureEditorFloatingCanvasTransformState:
    empty_state = TextureEditorFloatingCanvasTransformState(
        current_bounds=None,
        origin_bounds=None,
        offset_x=0,
        offset_y=0,
        scale_x=1.0,
        scale_y=1.0,
        rotation_degrees=0.0,
    )
    if document is None or document.floating_selection is None:
        return empty_state
    floating = document.floating_selection
    current_bounds = current_texture_editor_floating_canvas_bounds(document, floating_pixels)
    if current_bounds is None:
        return empty_state
    return TextureEditorFloatingCanvasTransformState(
        current_bounds=current_bounds,
        origin_bounds=(
            int(floating.bounds[0]),
            int(floating.bounds[1]),
            int(floating.bounds[2]),
            int(floating.bounds[3]),
        ),
        offset_x=int(floating.offset_x),
        offset_y=int(floating.offset_y),
        scale_x=float(floating.scale_x),
        scale_y=float(floating.scale_y),
        rotation_degrees=float(floating.rotation_degrees),
    )


def compose_texture_editor_floating_selection(
    document: Optional[TextureEditorDocument],
    base: np.ndarray,
    floating_pixels: Optional[np.ndarray],
) -> np.ndarray:
    if document is None or document.floating_selection is None:
        return base
    transformed = transformed_texture_editor_floating_pixels(document.floating_selection, floating_pixels)
    if transformed is None or transformed.size == 0:
        return base
    floating = document.floating_selection
    x = int(floating.bounds[0] + floating.offset_x)
    y = int(floating.bounds[1] + floating.offset_y)
    h, w = transformed.shape[:2]
    dx0 = max(0, x)
    dy0 = max(0, y)
    dx1 = min(base.shape[1], x + w)
    dy1 = min(base.shape[0], y + h)
    if dx1 <= dx0 or dy1 <= dy0:
        return base
    sx0 = dx0 - x
    sy0 = dy0 - y
    sx1 = sx0 + (dx1 - dx0)
    sy1 = sy0 + (dy1 - dy0)
    composed = base.copy()
    composed[dy0:dy1, dx0:dx1] = _blend_layer_region(
        composed[dy0:dy1, dx0:dx1],
        transformed[sy0:sy1, sx0:sx1],
        opacity=100,
        mode="normal",
    )
    return composed


def compose_texture_editor_floating_selection_region(
    document: Optional[TextureEditorDocument],
    base_region: np.ndarray,
    floating_pixels: Optional[np.ndarray],
    bounds: Tuple[int, int, int, int],
) -> np.ndarray:
    if document is None or document.floating_selection is None:
        return base_region
    transformed = transformed_texture_editor_floating_pixels(document.floating_selection, floating_pixels)
    if transformed is None or transformed.size == 0:
        return base_region
    region_x, region_y, region_w, region_h = bounds
    floating = document.floating_selection
    x = int(floating.bounds[0] + floating.offset_x)
    y = int(floating.bounds[1] + floating.offset_y)
    h, w = transformed.shape[:2]
    dx0 = max(region_x, x)
    dy0 = max(region_y, y)
    dx1 = min(region_x + region_w, x + w)
    dy1 = min(region_y + region_h, y + h)
    if dx1 <= dx0 or dy1 <= dy0:
        return base_region
    sx0 = dx0 - x
    sy0 = dy0 - y
    sx1 = sx0 + (dx1 - dx0)
    sy1 = sy0 + (dy1 - dy0)
    local_x0 = dx0 - region_x
    local_y0 = dy0 - region_y
    composed = base_region.copy()
    composed[local_y0:local_y0 + (dy1 - dy0), local_x0:local_x0 + (dx1 - dx0)] = _blend_layer_region(
        composed[local_y0:local_y0 + (dy1 - dy0), local_x0:local_x0 + (dx1 - dx0)],
        transformed[sy0:sy1, sx0:sx1],
        opacity=100,
        mode="normal",
    )
    return composed
