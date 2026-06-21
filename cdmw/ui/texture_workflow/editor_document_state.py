from __future__ import annotations

"""Document transform state helpers for the standalone Texture Editor UI."""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np

from cdmw.core.texture_editor import (
    crop_texture_editor_document_to_selection,
    flip_texture_editor_document,
    resize_texture_editor_document_canvas,
    resize_texture_editor_document_image,
    rotate_texture_editor_document_90,
    trim_texture_editor_document_transparent_bounds,
)
from cdmw.models import TextureEditorDocument


@dataclass(frozen=True, slots=True)
class TextureEditorDocumentTransformGateState:
    can_apply: bool
    status_text: str = ""
    error: bool = False


@dataclass(frozen=True, slots=True)
class TextureEditorDocumentPixelsChangeState:
    document: TextureEditorDocument
    layer_pixels: Dict[str, np.ndarray]
    before_layer_pixels: Dict[str, np.ndarray]
    history_label: str
    status_text: str
    kind: str
    tracked_layer_ids: Tuple[str, ...]
    force_checkpoint: bool


def texture_editor_document_pixels_change_gate(
    document: TextureEditorDocument | None,
) -> TextureEditorDocumentTransformGateState:
    if document is None:
        return TextureEditorDocumentTransformGateState(can_apply=False)
    if document.floating_selection is not None:
        return TextureEditorDocumentTransformGateState(
            can_apply=False,
            status_text="Commit or cancel the floating selection before changing the whole document.",
            error=True,
        )
    return TextureEditorDocumentTransformGateState(can_apply=True)


def texture_editor_crop_to_selection_gate(
    document: TextureEditorDocument | None,
) -> TextureEditorDocumentTransformGateState:
    if document is None or document.selection.mode == "none":
        return TextureEditorDocumentTransformGateState(
            can_apply=False,
            status_text="Create a selection first, then use Crop To Selection.",
            error=True,
        )
    return TextureEditorDocumentTransformGateState(can_apply=True)


def texture_editor_document_pixels_changed(
    *,
    current_document: TextureEditorDocument,
    current_layer_pixels: Dict[str, np.ndarray],
    updated_document: TextureEditorDocument,
    updated_layer_pixels: Dict[str, np.ndarray],
) -> bool:
    return updated_document is not current_document or updated_layer_pixels is not current_layer_pixels


def texture_editor_document_transform_applied_status(label: str) -> str:
    return f"{label} applied."


def _texture_editor_document_pixels_change_state(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    *,
    history_label: str,
    updated_document: TextureEditorDocument,
    updated_layer_pixels: Dict[str, np.ndarray],
) -> Optional[TextureEditorDocumentPixelsChangeState]:
    if not texture_editor_document_pixels_changed(
        current_document=document,
        current_layer_pixels=layer_pixels,
        updated_document=updated_document,
        updated_layer_pixels=updated_layer_pixels,
    ):
        return None
    return TextureEditorDocumentPixelsChangeState(
        document=updated_document,
        layer_pixels=updated_layer_pixels,
        before_layer_pixels={key: value.copy() for key, value in layer_pixels.items()},
        history_label=history_label,
        status_text=texture_editor_document_transform_applied_status(history_label),
        kind="document_transform",
        tracked_layer_ids=(),
        force_checkpoint=True,
    )


def texture_editor_resized_image_state(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    new_width: int,
    new_height: int,
) -> Optional[TextureEditorDocumentPixelsChangeState]:
    updated_document, updated_layer_pixels = resize_texture_editor_document_image(
        document,
        layer_pixels,
        new_width,
        new_height,
    )
    return _texture_editor_document_pixels_change_state(
        document,
        layer_pixels,
        history_label="Image Size",
        updated_document=updated_document,
        updated_layer_pixels=updated_layer_pixels,
    )


def texture_editor_resized_canvas_state(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    new_width: int,
    new_height: int,
    *,
    anchor: str = "top_left",
) -> Optional[TextureEditorDocumentPixelsChangeState]:
    updated_document, updated_layer_pixels = resize_texture_editor_document_canvas(
        document,
        layer_pixels,
        new_width,
        new_height,
        anchor=anchor,
    )
    return _texture_editor_document_pixels_change_state(
        document,
        layer_pixels,
        history_label="Canvas Size",
        updated_document=updated_document,
        updated_layer_pixels=updated_layer_pixels,
    )


def texture_editor_cropped_to_selection_state(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
) -> Optional[TextureEditorDocumentPixelsChangeState]:
    updated_document, updated_layer_pixels = crop_texture_editor_document_to_selection(document, layer_pixels)
    return _texture_editor_document_pixels_change_state(
        document,
        layer_pixels,
        history_label=texture_editor_crop_to_selection_history_label(),
        updated_document=updated_document,
        updated_layer_pixels=updated_layer_pixels,
    )


def texture_editor_trimmed_transparent_state(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
) -> Optional[TextureEditorDocumentPixelsChangeState]:
    updated_document, updated_layer_pixels = trim_texture_editor_document_transparent_bounds(document, layer_pixels)
    return _texture_editor_document_pixels_change_state(
        document,
        layer_pixels,
        history_label=texture_editor_trim_transparent_history_label(),
        updated_document=updated_document,
        updated_layer_pixels=updated_layer_pixels,
    )


def texture_editor_flip_document_history_label(*, horizontal: bool, vertical: bool) -> str:
    if not horizontal and not vertical:
        return ""
    return "Flip Horizontal" if horizontal else "Flip Vertical"


def texture_editor_flipped_document_state(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    *,
    horizontal: bool,
    vertical: bool,
) -> Optional[TextureEditorDocumentPixelsChangeState]:
    history_label = texture_editor_flip_document_history_label(horizontal=horizontal, vertical=vertical)
    if not history_label:
        return None
    updated_document, updated_layer_pixels = flip_texture_editor_document(
        document,
        layer_pixels,
        horizontal=horizontal,
        vertical=vertical,
    )
    return _texture_editor_document_pixels_change_state(
        document,
        layer_pixels,
        history_label=history_label,
        updated_document=updated_document,
        updated_layer_pixels=updated_layer_pixels,
    )


def texture_editor_rotate_document_history_label(*, clockwise: bool) -> str:
    return "Rotate 90 CW" if clockwise else "Rotate 90 CCW"


def texture_editor_rotated_document_state(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    *,
    clockwise: bool,
) -> Optional[TextureEditorDocumentPixelsChangeState]:
    history_label = texture_editor_rotate_document_history_label(clockwise=clockwise)
    updated_document, updated_layer_pixels = rotate_texture_editor_document_90(
        document,
        layer_pixels,
        clockwise=clockwise,
    )
    return _texture_editor_document_pixels_change_state(
        document,
        layer_pixels,
        history_label=history_label,
        updated_document=updated_document,
        updated_layer_pixels=updated_layer_pixels,
    )


def texture_editor_crop_to_selection_history_label() -> str:
    return "Crop To Selection"


def texture_editor_trim_transparent_history_label() -> str:
    return "Trim Transparent"


__all__ = [
    "TextureEditorDocumentPixelsChangeState",
    "TextureEditorDocumentTransformGateState",
    "texture_editor_crop_to_selection_gate",
    "texture_editor_crop_to_selection_history_label",
    "texture_editor_cropped_to_selection_state",
    "texture_editor_document_pixels_change_gate",
    "texture_editor_document_pixels_changed",
    "texture_editor_document_transform_applied_status",
    "texture_editor_flipped_document_state",
    "texture_editor_flip_document_history_label",
    "texture_editor_resized_canvas_state",
    "texture_editor_resized_image_state",
    "texture_editor_rotated_document_state",
    "texture_editor_rotate_document_history_label",
    "texture_editor_trimmed_transparent_state",
    "texture_editor_trim_transparent_history_label",
]
