from __future__ import annotations

"""Selection state helpers for the standalone Texture Editor UI."""

import dataclasses
from dataclasses import dataclass
from typing import AbstractSet, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from cdmw.domain.textures.editor_composite import flatten_texture_editor_layers
from cdmw.domain.textures.editor_document import snap_lasso_points_to_edges
from cdmw.domain.textures.editor_layers import extract_texture_editor_selection
from cdmw.domain.textures.editor_selection import (
    apply_texture_editor_lasso_selection,
    apply_texture_editor_rect_selection,
    clear_texture_editor_selection,
    grow_texture_editor_selection,
    select_all_texture_editor,
    shrink_texture_editor_selection,
    update_texture_editor_selection_settings,
)
from cdmw.domain.textures.editor_selection_masks import build_texture_editor_selection_mask
from cdmw.models import TextureEditorDocument, TextureEditorSelection, TextureEditorToolSettings
from cdmw.ui.texture_workflow.editor_layer_state import texture_editor_layer_pixel_target_state


@dataclass(frozen=True, slots=True)
class TextureEditorSelectionControlsState:
    help_text: str
    inverted: bool
    feather_radius: int
    quick_mask_enabled: bool
    copy_layer_enabled: bool
    select_all_enabled: bool
    clear_enabled: bool
    refine_enabled: bool
    to_mask_enabled: bool
    from_mask_enabled: bool
    invert_enabled: bool
    feather_enabled: bool
    combine_mode_enabled: bool
    quick_mask_checkbox_enabled: bool


@dataclass(frozen=True, slots=True)
class TextureEditorCanvasSelectionPayloadState:
    mode: str
    rect: Optional[Tuple[int, int, int, int]] = None
    points: Tuple[Tuple[float, float], ...] = ()


@dataclass(frozen=True, slots=True)
class TextureEditorCanvasSelectionUpdateState:
    document: TextureEditorDocument
    history_label: str


@dataclass(frozen=True, slots=True)
class TextureEditorSelectionDocumentUpdateState:
    document: TextureEditorDocument
    history_label: str


@dataclass(frozen=True, slots=True)
class TextureEditorActiveLayerSelectionPayloadState:
    pixels: np.ndarray
    label: str
    bounds: Tuple[int, int, int, int]


def texture_editor_selection_refine_labels(amount: int) -> Tuple[str, str]:
    normalized = max(1, int(amount))
    return (f"Grow +{normalized}", f"Shrink -{normalized}")


def texture_editor_canvas_selection_payload_state(
    payload: object,
) -> Optional[TextureEditorCanvasSelectionPayloadState]:
    if not isinstance(payload, dict):
        return None
    if payload.get("mode") == "rect":
        rect = payload.get("rect")
        if isinstance(rect, tuple) and len(rect) == 4:
            return TextureEditorCanvasSelectionPayloadState(
                mode="rect",
                rect=(int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])),
            )
    elif payload.get("mode") == "lasso":
        points = payload.get("points")
        if isinstance(points, list) and len(points) >= 3:
            return TextureEditorCanvasSelectionPayloadState(
                mode="lasso",
                points=tuple((float(x), float(y)) for x, y in points),
            )
    return None


def texture_editor_canvas_selection_source_pixels(
    document: Optional[TextureEditorDocument],
    layer_pixels: Dict[str, np.ndarray],
    composite_rgba: Optional[np.ndarray],
) -> Optional[np.ndarray]:
    if composite_rgba is not None:
        return composite_rgba
    if document is None:
        return None
    return flatten_texture_editor_layers(document, layer_pixels)


def texture_editor_clear_selection_update_state(
    document: TextureEditorDocument,
) -> TextureEditorSelectionDocumentUpdateState:
    return TextureEditorSelectionDocumentUpdateState(
        document=clear_texture_editor_selection(document),
        history_label="Clear Selection",
    )


def texture_editor_select_all_update_state(
    document: TextureEditorDocument,
) -> TextureEditorSelectionDocumentUpdateState:
    return TextureEditorSelectionDocumentUpdateState(
        document=select_all_texture_editor(document),
        history_label="Select All",
    )


def texture_editor_resized_selection_update_state(
    document: TextureEditorDocument,
    delta: int,
) -> Optional[TextureEditorSelectionDocumentUpdateState]:
    if document.selection.mode == "none":
        return None
    if delta > 0:
        return TextureEditorSelectionDocumentUpdateState(
            document=grow_texture_editor_selection(document, delta),
            history_label="Grow Selection",
        )
    return TextureEditorSelectionDocumentUpdateState(
        document=shrink_texture_editor_selection(document, abs(delta)),
        history_label="Shrink Selection",
    )


def texture_editor_quick_mask_update_state(
    document: TextureEditorDocument,
    checked: bool,
) -> TextureEditorSelectionDocumentUpdateState:
    return TextureEditorSelectionDocumentUpdateState(
        document=dataclasses.replace(document, quick_mask_enabled=bool(checked)),
        history_label="Toggle Quick Mask",
    )


def texture_editor_selection_feather_preview_document(
    document: TextureEditorDocument,
    feather_radius: int,
) -> TextureEditorDocument:
    return update_texture_editor_selection_settings(document, feather_radius=feather_radius)


def texture_editor_selection_feather_update_state(
    document: TextureEditorDocument,
    feather_radius: int,
) -> TextureEditorSelectionDocumentUpdateState:
    return TextureEditorSelectionDocumentUpdateState(
        document=texture_editor_selection_feather_preview_document(document, feather_radius),
        history_label="Selection Feather",
    )


def texture_editor_selection_invert_update_state(
    document: TextureEditorDocument,
    checked: bool,
) -> TextureEditorSelectionDocumentUpdateState:
    return TextureEditorSelectionDocumentUpdateState(
        document=update_texture_editor_selection_settings(document, inverted=checked),
        history_label="Invert Selection",
    )


def texture_editor_selection_operation_state(
    document: Optional[TextureEditorDocument],
    *,
    action: str,
    delta: int = 0,
    checked: bool = False,
    feather_radius: int = 0,
) -> Optional[TextureEditorSelectionDocumentUpdateState]:
    if document is None:
        return None
    action_key = str(action or "").strip().lower()
    if action_key == "clear":
        return texture_editor_clear_selection_update_state(document)
    if action_key == "select_all":
        return texture_editor_select_all_update_state(document)
    if action_key == "resize":
        return texture_editor_resized_selection_update_state(document, delta)
    if action_key == "quick_mask":
        return texture_editor_quick_mask_update_state(document, checked)
    if action_key == "feather":
        return texture_editor_selection_feather_update_state(document, feather_radius)
    if action_key == "invert":
        return texture_editor_selection_invert_update_state(document, checked)
    return None


def simplified_texture_editor_lasso_points(
    points: Sequence[Tuple[float, float]],
) -> List[Tuple[float, float]]:
    if len(points) < 3:
        return [(float(x), float(y)) for x, y in points]
    contour = np.array(points, dtype=np.float32).reshape((-1, 1, 2))
    simplified = cv2.approxPolyDP(contour, 0.35, closed=False)
    output = [(float(point[0][0]), float(point[0][1])) for point in simplified]
    if len(output) < 3:
        return [(float(x), float(y)) for x, y in points]
    return output


def texture_editor_prepared_lasso_selection_points(
    points: Sequence[Tuple[float, float]],
    settings: TextureEditorToolSettings,
    *,
    snap_pixels: Optional[np.ndarray],
) -> List[Tuple[float, float]]:
    prepared_points = simplified_texture_editor_lasso_points(points)
    if not settings.lasso_snap_to_edges or snap_pixels is None:
        return prepared_points
    return snap_lasso_points_to_edges(
        snap_pixels,
        prepared_points,
        search_radius=settings.lasso_snap_radius,
        edge_sensitivity=settings.lasso_edge_sensitivity,
    )


def texture_editor_canvas_selection_update_state(
    document: TextureEditorDocument,
    payload_state: Optional[TextureEditorCanvasSelectionPayloadState],
    *,
    settings: TextureEditorToolSettings,
    snap_pixels: Optional[np.ndarray],
) -> Optional[TextureEditorCanvasSelectionUpdateState]:
    if payload_state is None:
        return None
    if payload_state.mode == "rect" and payload_state.rect is not None:
        return TextureEditorCanvasSelectionUpdateState(
            document=apply_texture_editor_rect_selection(
                document,
                payload_state.rect,
                combine_mode=settings.selection_combine_mode,
            ),
            history_label="Rect Selection",
        )
    if payload_state.mode == "lasso" and len(payload_state.points) >= 3:
        prepared_points = texture_editor_prepared_lasso_selection_points(
            payload_state.points,
            settings,
            snap_pixels=snap_pixels,
        )
        return TextureEditorCanvasSelectionUpdateState(
            document=apply_texture_editor_lasso_selection(
                document,
                prepared_points,
                combine_mode=settings.selection_combine_mode,
            ),
            history_label="Lasso Selection",
        )
    return None


def texture_editor_document_with_cleared_selection_only(
    document: TextureEditorDocument,
) -> TextureEditorDocument:
    feather = max(0, int(document.selection.feather_radius))
    return dataclasses.replace(
        document,
        selection=TextureEditorSelection(
            inverted=False,
            feather_radius=feather,
        ),
    )


def current_texture_editor_selection_bounds(
    document: Optional[TextureEditorDocument],
) -> Optional[Tuple[int, int, int, int]]:
    if document is None:
        return None
    if document.selection.mode == "none":
        return None
    mask = build_texture_editor_selection_mask(document.width, document.height, document.selection)
    if mask is None:
        return None
    ys, xs = np.where(mask > 0)
    if xs.size == 0 or ys.size == 0:
        return None
    x0 = int(xs.min())
    y0 = int(ys.min())
    x1 = int(xs.max()) + 1
    y1 = int(ys.max()) + 1
    return (x0, y0, max(1, x1 - x0), max(1, y1 - y0))


def texture_editor_active_layer_selection_payload_state(
    document: Optional[TextureEditorDocument],
    layer_pixels: Dict[str, np.ndarray],
    *,
    current_layer_id: Optional[str],
) -> Optional[TextureEditorActiveLayerSelectionPayloadState]:
    if document is None or document.selection.mode == "none":
        return None
    target = texture_editor_layer_pixel_target_state(
        document,
        current_layer_id=current_layer_id,
        layer_pixel_ids=layer_pixels.keys(),
    )
    layer_id = target.layer_id
    if not layer_id or not target.has_pixels:
        return None
    selection_payload = extract_texture_editor_selection(document, layer_pixels, layer_id)
    if selection_payload is None:
        return None
    extracted, bounds = selection_payload
    layer = target.layer
    label = layer.name if layer is not None else "Selection"
    return TextureEditorActiveLayerSelectionPayloadState(pixels=extracted, label=label, bounds=bounds)


def texture_editor_selection_controls_state(
    document: Optional[TextureEditorDocument],
    *,
    current_tool: str,
    current_layer_id: Optional[str],
    layer_pixel_ids: AbstractSet[str],
    busy: bool,
) -> TextureEditorSelectionControlsState:
    has_doc = document is not None
    has_selection = bool(has_doc and document is not None and document.selection.mode != "none")
    quick_mask_enabled = bool(has_doc and document is not None and document.quick_mask_enabled)
    help_text = (
        "Selections limit paint, erase, fill, gradient, clone, heal, patch, smudge, sharpen, soften, dodge/burn, and recolor to the selected area."
        if has_selection or (has_doc and current_tool in {"select_rect", "lasso"})
        else "Selections limit editing to the selected area. Use Rect Select or Lasso to create one."
    )
    selected_layer = None
    if document is not None:
        target_layer_id = current_layer_id or document.active_layer_id
        selected_layer = next((candidate for candidate in document.layers if candidate.layer_id == target_layer_id), None)
    has_mask = bool(selected_layer and selected_layer.mask_layer_id and selected_layer.mask_layer_id in layer_pixel_ids)
    return TextureEditorSelectionControlsState(
        help_text=help_text,
        inverted=bool(document.selection.inverted) if document is not None else False,
        feather_radius=max(0, int(document.selection.feather_radius)) if document is not None else 0,
        quick_mask_enabled=quick_mask_enabled,
        copy_layer_enabled=bool(has_selection and not busy),
        select_all_enabled=bool(has_doc and not busy),
        clear_enabled=bool(has_doc and not busy and (has_selection or quick_mask_enabled)),
        refine_enabled=bool(has_selection and not busy),
        to_mask_enabled=bool(has_selection and selected_layer and not busy),
        from_mask_enabled=bool(has_doc and has_mask and not busy),
        invert_enabled=bool(has_selection and not busy),
        feather_enabled=bool(has_selection and not busy),
        combine_mode_enabled=bool(has_doc and not busy),
        quick_mask_checkbox_enabled=bool(has_doc and not busy),
    )
