from __future__ import annotations

"""Clipboard and paste-state helpers for the standalone Texture Editor UI."""

from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Tuple

import numpy as np

from cdmw.domain.textures.editor_layers import add_texture_editor_layer
from cdmw.domain.textures.editor_selection import clear_texture_editor_selection
from cdmw.models import TextureEditorDocument, TextureEditorLayer
from cdmw.ui.texture_workflow.editor_layer_state import texture_editor_layer_pixel_target_state
from cdmw.ui.texture_workflow.editor_selection_state import TextureEditorActiveLayerSelectionPayloadState


TextureEditorLayerClipboardPayload = Tuple[np.ndarray, str, int, int, str]
TextureEditorSelectionClipboardPayload = Tuple[np.ndarray, str, int, int]


@dataclass(frozen=True, slots=True)
class TextureEditorFloatingPasteState:
    label: str
    bounds: Tuple[int, int, int, int]
    history_label: str
    status_text: str
    paste_mode: str


@dataclass(frozen=True, slots=True)
class TextureEditorClipboardFloatingPasteState:
    can_paste: bool
    pixels: Optional[np.ndarray]
    paste_state: Optional[TextureEditorFloatingPasteState]


@dataclass(frozen=True, slots=True)
class TextureEditorLayerClipboardCopyState:
    copied: bool
    layer_clipboard: Optional[TextureEditorLayerClipboardPayload]
    status_text: str
    error: bool


@dataclass(frozen=True, slots=True)
class TextureEditorSelectionToLayerState:
    document: TextureEditorDocument
    layer_pixels: Dict[str, np.ndarray]
    layer_id: str
    selection_clipboard: TextureEditorSelectionClipboardPayload
    history_label: str
    status_text: str


def texture_editor_layer_clipboard_payload(
    layer: TextureEditorLayer,
    pixels: np.ndarray,
) -> TextureEditorLayerClipboardPayload:
    return (
        pixels.copy(),
        layer.name,
        int(layer.offset_x),
        int(layer.offset_y),
        str(layer.blend_mode or "normal"),
    )


def texture_editor_selection_clipboard_payload(
    selection_state: TextureEditorActiveLayerSelectionPayloadState,
) -> TextureEditorSelectionClipboardPayload:
    return (
        selection_state.pixels.copy(),
        selection_state.label,
        int(selection_state.bounds[0]),
        int(selection_state.bounds[1]),
    )


def texture_editor_layer_floating_label(layer_name: str) -> str:
    return f"{layer_name} Copy"


def texture_editor_selection_floating_label(layer_name: str) -> str:
    return f"{layer_name} Selection"


def texture_editor_centered_paste_origin(
    document: TextureEditorDocument,
    pixels: np.ndarray,
) -> Tuple[int, int]:
    return (
        max(0, (int(document.width) - int(pixels.shape[1])) // 2),
        max(0, (int(document.height) - int(pixels.shape[0])) // 2),
    )


def texture_editor_layer_floating_paste_state(
    pixels: np.ndarray,
    layer_name: str,
    *,
    offset_x: int,
    offset_y: int,
    centered: bool = False,
) -> TextureEditorFloatingPasteState:
    label = texture_editor_layer_floating_label(layer_name)
    history_label = "Paste Centered Floating" if centered else "Paste Layer Floating"
    status_text = f"Pasted layer '{label}' centered." if centered else f"Pasted layer '{label}' as floating content."
    return TextureEditorFloatingPasteState(
        label=label,
        bounds=(int(offset_x), int(offset_y), int(pixels.shape[1]), int(pixels.shape[0])),
        history_label=history_label,
        status_text=status_text,
        paste_mode="centered" if centered else "in_place",
    )


def texture_editor_selection_floating_paste_state(
    pixels: np.ndarray,
    layer_name: str,
    *,
    offset_x: int,
    offset_y: int,
    centered: bool = False,
) -> TextureEditorFloatingPasteState:
    label = texture_editor_selection_floating_label(layer_name)
    history_label = "Paste Centered Floating" if centered else "Paste Selection Floating"
    status_text = (
        f"Pasted selection as a centered layer from '{layer_name}'."
        if centered
        else f"Pasted selection as floating content from '{layer_name}'."
    )
    return TextureEditorFloatingPasteState(
        label=label,
        bounds=(int(offset_x), int(offset_y), int(pixels.shape[1]), int(pixels.shape[0])),
        history_label=history_label,
        status_text=status_text,
        paste_mode="centered" if centered else "in_place",
    )


def texture_editor_layer_copy_clipboard_state(
    document: Optional[TextureEditorDocument],
    layer_pixels: Mapping[str, np.ndarray],
    *,
    current_layer_id: Optional[str],
) -> TextureEditorLayerClipboardCopyState:
    target = texture_editor_layer_pixel_target_state(
        document,
        current_layer_id=current_layer_id,
        layer_pixel_ids=layer_pixels.keys(),
    )
    if not target.available or target.layer is None:
        return TextureEditorLayerClipboardCopyState(
            copied=False,
            layer_clipboard=None,
            status_text="",
            error=False,
        )
    payload = texture_editor_layer_clipboard_payload(target.layer, layer_pixels[target.layer_id])
    return TextureEditorLayerClipboardCopyState(
        copied=True,
        layer_clipboard=payload,
        status_text=texture_editor_layer_copy_status_text(target.layer.name),
        error=False,
    )


def texture_editor_clipboard_floating_paste_state(
    document: Optional[TextureEditorDocument],
    *,
    layer_clipboard: Optional[TextureEditorLayerClipboardPayload],
    selection_clipboard: Optional[TextureEditorSelectionClipboardPayload],
    source: str = "any",
    centered: bool = False,
) -> TextureEditorClipboardFloatingPasteState:
    if document is None:
        return TextureEditorClipboardFloatingPasteState(False, None, None)
    source_key = str(source or "any").strip().lower()
    if source_key not in {"any", "layer", "selection"}:
        source_key = "any"
    if source_key in {"any", "selection"} and selection_clipboard is not None:
        pixels, layer_name, offset_x, offset_y = selection_clipboard
        if centered:
            offset_x, offset_y = texture_editor_centered_paste_origin(document, pixels)
        return TextureEditorClipboardFloatingPasteState(
            can_paste=True,
            pixels=pixels,
            paste_state=texture_editor_selection_floating_paste_state(
                pixels,
                layer_name,
                offset_x=offset_x,
                offset_y=offset_y,
                centered=centered,
            ),
        )
    if source_key in {"any", "layer"} and layer_clipboard is not None:
        pixels, layer_name, offset_x, offset_y, _blend_mode = layer_clipboard
        if centered:
            offset_x, offset_y = texture_editor_centered_paste_origin(document, pixels)
        return TextureEditorClipboardFloatingPasteState(
            can_paste=True,
            pixels=pixels,
            paste_state=texture_editor_layer_floating_paste_state(
                pixels,
                layer_name,
                offset_x=offset_x,
                offset_y=offset_y,
                centered=centered,
            ),
        )
    return TextureEditorClipboardFloatingPasteState(False, None, None)


def texture_editor_layer_copy_status_text(layer_name: str) -> str:
    return f"Copied layer '{layer_name}'."


def texture_editor_selection_copy_status_text(layer_name: str) -> str:
    return f"Copied the current selection from '{layer_name}'."


def texture_editor_cut_selection_status_text() -> str:
    return "Cut selection into floating content."


def texture_editor_cut_selection_missing_status_text() -> str:
    return "Create a selection first, then use Cut."


def texture_editor_copy_selection_to_layer_status_text() -> str:
    return "Copied selection to a new layer. Selection cleared so Move repositions the whole copied piece."


def texture_editor_copy_selection_to_layer_missing_status_text() -> str:
    return "Create a selection first, then use Copy To New Layer."


def texture_editor_copy_selection_to_layer_history_label() -> str:
    return "Copy Selection To Layer"


def texture_editor_selection_to_layer_state(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    selection_state: TextureEditorActiveLayerSelectionPayloadState,
) -> TextureEditorSelectionToLayerState:
    bounds = selection_state.bounds
    updated_document, updated_pixels, layer_id = add_texture_editor_layer(
        document,
        layer_pixels,
        name=texture_editor_selection_floating_label(selection_state.label),
        initial_pixels=selection_state.pixels,
        offset_x=int(bounds[0]),
        offset_y=int(bounds[1]),
    )
    updated_document = clear_texture_editor_selection(updated_document)
    return TextureEditorSelectionToLayerState(
        document=updated_document,
        layer_pixels=updated_pixels,
        layer_id=layer_id,
        selection_clipboard=texture_editor_selection_clipboard_payload(selection_state),
        history_label=texture_editor_copy_selection_to_layer_history_label(),
        status_text=texture_editor_copy_selection_to_layer_status_text(),
    )


__all__ = [
    "TextureEditorClipboardFloatingPasteState",
    "TextureEditorFloatingPasteState",
    "TextureEditorLayerClipboardCopyState",
    "TextureEditorLayerClipboardPayload",
    "TextureEditorSelectionClipboardPayload",
    "TextureEditorSelectionToLayerState",
    "texture_editor_centered_paste_origin",
    "texture_editor_clipboard_floating_paste_state",
    "texture_editor_copy_selection_to_layer_history_label",
    "texture_editor_copy_selection_to_layer_missing_status_text",
    "texture_editor_copy_selection_to_layer_status_text",
    "texture_editor_cut_selection_missing_status_text",
    "texture_editor_cut_selection_status_text",
    "texture_editor_layer_clipboard_payload",
    "texture_editor_layer_copy_clipboard_state",
    "texture_editor_layer_copy_status_text",
    "texture_editor_layer_floating_label",
    "texture_editor_layer_floating_paste_state",
    "texture_editor_selection_clipboard_payload",
    "texture_editor_selection_copy_status_text",
    "texture_editor_selection_floating_label",
    "texture_editor_selection_floating_paste_state",
    "texture_editor_selection_to_layer_state",
]
