from __future__ import annotations

"""Channel control state rules for the standalone Texture Editor UI."""

import dataclasses
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple

import numpy as np

from cdmw.domain.textures.editor_layers import (
    add_texture_editor_layer,
    bump_texture_editor_layer_revision,
)
from cdmw.domain.textures.editor_selection import (
    copy_texture_editor_layer_channel,
    extract_texture_editor_layer_channel_to_rgba,
    load_texture_editor_layer_channel_as_selection,
    paste_texture_editor_channel_into_layer,
    swap_texture_editor_layer_channels,
    write_texture_editor_layer_luma_to_channel,
    write_texture_editor_selection_to_layer_channel,
)
from cdmw.models import TextureEditorDocument, TextureEditorLayer
from cdmw.ui.texture_workflow.editor_layer_state import texture_editor_layer_pixel_target_state


@dataclass(frozen=True, slots=True)
class TextureEditorChannelControlsState:
    channel_values: Tuple[bool, bool, bool, bool]
    extract_enabled: bool
    pack_enabled: bool
    selection_from_enabled: bool
    selection_to_enabled: bool
    copy_enabled: bool
    paste_enabled: bool
    swap_enabled: bool


@dataclass(frozen=True, slots=True)
class TextureEditorChannelLockUpdateState:
    document: TextureEditorDocument
    status_text: str


@dataclass(frozen=True, slots=True)
class TextureEditorChannelLayerOperationState:
    document: TextureEditorDocument
    layer_pixels: Dict[str, np.ndarray]
    before_layer_pixels: Dict[str, np.ndarray]
    layer_id: str
    new_layer_id: str
    history_label: str
    status_text: str
    kind: str
    tracked_layer_ids: Tuple[str, ...]
    force_checkpoint: bool


@dataclass(frozen=True, slots=True)
class TextureEditorChannelDocumentOperationState:
    document: TextureEditorDocument
    history_label: str
    status_text: str
    kind: str
    tracked_layer_ids: Tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TextureEditorChannelClipboardState:
    clipboard: Tuple[np.ndarray, str]
    status_text: str


@dataclass(frozen=True, slots=True)
class TextureEditorChannelOperationState:
    layer_state: Optional[TextureEditorChannelLayerOperationState] = None
    document_state: Optional[TextureEditorChannelDocumentOperationState] = None
    clipboard_state: Optional[TextureEditorChannelClipboardState] = None
    status_text: str = ""
    error: bool = False


def texture_editor_channel_controls_state(
    document: Optional[TextureEditorDocument],
    *,
    current_layer_id: Optional[str],
    busy: bool,
    has_clipboard: bool,
) -> TextureEditorChannelControlsState:
    values = (True, True, True, True)
    if document is not None:
        values = (
            bool(document.edit_red_channel),
            bool(document.edit_green_channel),
            bool(document.edit_blue_channel),
            bool(document.edit_alpha_channel),
        )
    has_doc = document is not None
    active_layer_id = document.active_layer_id if document is not None else ""
    has_layer = bool(has_doc and (current_layer_id or active_layer_id))
    has_selection = bool(has_doc and document is not None and document.selection.mode != "none")
    base_enabled = has_layer and not busy
    return TextureEditorChannelControlsState(
        channel_values=values,
        extract_enabled=base_enabled,
        pack_enabled=base_enabled,
        selection_from_enabled=base_enabled,
        selection_to_enabled=base_enabled and has_selection,
        copy_enabled=base_enabled,
        paste_enabled=base_enabled and has_clipboard,
        swap_enabled=base_enabled,
    )


def texture_editor_channel_lock_update_state(
    document: TextureEditorDocument,
    *,
    red: bool,
    green: bool,
    blue: bool,
    alpha: bool,
) -> TextureEditorChannelLockUpdateState:
    updated_document = dataclasses.replace(
        document,
        edit_red_channel=bool(red),
        edit_green_channel=bool(green),
        edit_blue_channel=bool(blue),
        edit_alpha_channel=bool(alpha),
    )
    return TextureEditorChannelLockUpdateState(
        document=updated_document,
        status_text=texture_editor_channel_lock_status_text(
            red=updated_document.edit_red_channel,
            green=updated_document.edit_green_channel,
            blue=updated_document.edit_blue_channel,
            alpha=updated_document.edit_alpha_channel,
        ),
    )


def texture_editor_channel_lock_status_text(
    *,
    red: bool,
    green: bool,
    blue: bool,
    alpha: bool,
) -> str:
    return (
        "Channel edit locks: "
        f"{'R' if red else '-'}"
        f"{'G' if green else '-'}"
        f"{'B' if blue else '-'}"
        f"{'A' if alpha else '-'}"
    )


def texture_editor_normalized_channel_key(value: object, default: str) -> str:
    return str(value or default)


def texture_editor_channel_title(channel_key: str) -> str:
    return str(channel_key or "").title()


def texture_editor_channel_operation_history_label(
    operation: str,
    channel_key: str,
    *,
    other_channel_key: str = "",
) -> str:
    channel_title = texture_editor_channel_title(channel_key)
    other_title = texture_editor_channel_title(other_channel_key)
    labels = {
        "extract": f"Extract {channel_title} Channel",
        "pack_luma": f"Pack Luma To {channel_title}",
        "load_selection": f"Load {channel_title} Channel As Selection",
        "write_selection": f"Write Selection To {channel_title}",
        "paste": f"Paste Channel To {channel_title}",
        "swap": f"Swap {channel_title} / {other_title}",
    }
    return labels.get(operation, channel_title)


def texture_editor_channel_operation_status_text(
    operation: str,
    channel_key: str,
    *,
    other_channel_key: str = "",
) -> str:
    channel_title = texture_editor_channel_title(channel_key)
    other_title = texture_editor_channel_title(other_channel_key)
    messages = {
        "extract": f"Extracted the {channel_title} channel into a new layer.",
        "pack_luma": f"Packed active-layer luminance into the {channel_title} channel.",
        "load_selection": f"Loaded the {channel_title} channel as a selection.",
        "write_selection": f"Wrote the current selection into the {channel_title} channel.",
        "copy": f"Copied the {channel_title} channel to the editor clipboard.",
        "paste": f"Pasted the channel clipboard into the {channel_title} channel.",
        "swap": f"Swapped the {channel_title} and {other_title} channels.",
    }
    return messages.get(operation, channel_title)


def texture_editor_channel_selection_required_status_text() -> str:
    return "Create a selection first, then write it to a channel."


def texture_editor_same_channel_swap_status(channel_a: str, channel_b: str) -> str:
    if channel_a == channel_b:
        return "Choose two different channels to swap."
    return ""


def texture_editor_channel_alpha_lock_blocked(
    layer: TextureEditorLayer,
    *,
    channel_keys: Iterable[str],
) -> bool:
    return bool(layer.alpha_locked and "alpha" in {str(channel_key or "").casefold() for channel_key in channel_keys})


def texture_editor_channel_alpha_lock_message(operation: str) -> str:
    messages = {
        "pack_luma": "Unlock alpha before packing luminance into the alpha channel.",
        "write_selection": "Unlock alpha before writing the selection into the alpha channel.",
        "paste": "Unlock alpha before pasting into the alpha channel.",
        "swap": "Unlock alpha before swapping with the alpha channel.",
    }
    return messages.get(operation, "Unlock alpha before editing the alpha channel.")


def texture_editor_channel_missing_operation_state() -> TextureEditorChannelOperationState:
    return TextureEditorChannelOperationState()


def texture_editor_channel_extract_operation_state(
    document: Optional[TextureEditorDocument],
    layer_pixels: Dict[str, np.ndarray],
    *,
    current_layer_id: Optional[str],
    channel_key: object,
) -> TextureEditorChannelOperationState:
    target = texture_editor_layer_pixel_target_state(
        document,
        current_layer_id=current_layer_id,
        layer_pixel_ids=layer_pixels.keys(),
    )
    if document is None or not target.available or target.layer is None:
        return texture_editor_channel_missing_operation_state()
    return TextureEditorChannelOperationState(
        layer_state=texture_editor_extracted_channel_layer_state(
            document,
            layer_pixels,
            layer_id=target.layer_id,
            layer=target.layer,
            channel_key=texture_editor_normalized_channel_key(channel_key, "alpha"),
        )
    )


def texture_editor_channel_luma_pack_operation_state(
    document: Optional[TextureEditorDocument],
    layer_pixels: Dict[str, np.ndarray],
    *,
    current_layer_id: Optional[str],
    channel_key: object,
) -> TextureEditorChannelOperationState:
    target = texture_editor_layer_pixel_target_state(
        document,
        current_layer_id=current_layer_id,
        layer_pixel_ids=layer_pixels.keys(),
    )
    if document is None or not target.available or target.layer is None:
        return texture_editor_channel_missing_operation_state()
    normalized = texture_editor_normalized_channel_key(channel_key, "alpha")
    if texture_editor_channel_alpha_lock_blocked(target.layer, channel_keys=(normalized,)):
        return TextureEditorChannelOperationState(
            status_text=texture_editor_channel_alpha_lock_message("pack_luma"),
            error=True,
        )
    return TextureEditorChannelOperationState(
        layer_state=texture_editor_luma_to_channel_state(
            document,
            layer_pixels,
            layer_id=target.layer_id,
            channel_key=normalized,
        )
    )


def texture_editor_channel_selection_load_operation_state(
    document: Optional[TextureEditorDocument],
    layer_pixels: Dict[str, np.ndarray],
    *,
    current_layer_id: Optional[str],
    channel_key: object,
    combine_mode: str,
) -> TextureEditorChannelOperationState:
    target = texture_editor_layer_pixel_target_state(
        document,
        current_layer_id=current_layer_id,
        layer_pixel_ids=layer_pixels.keys(),
    )
    if document is None or not target.available or target.layer is None:
        return texture_editor_channel_missing_operation_state()
    layer = target.layer
    return TextureEditorChannelOperationState(
        document_state=texture_editor_channel_to_selection_state(
            document,
            layer,
            layer_pixels[target.layer_id],
            channel_key=texture_editor_normalized_channel_key(channel_key, "alpha"),
            mask_pixels=layer_pixels.get(layer.mask_layer_id) if layer.mask_layer_id else None,
            combine_mode=combine_mode,
        )
    )


def texture_editor_channel_selection_write_operation_state(
    document: Optional[TextureEditorDocument],
    layer_pixels: Dict[str, np.ndarray],
    *,
    current_layer_id: Optional[str],
    channel_key: object,
) -> TextureEditorChannelOperationState:
    if document is None:
        return texture_editor_channel_missing_operation_state()
    if document.selection.mode == "none":
        return TextureEditorChannelOperationState(
            status_text=texture_editor_channel_selection_required_status_text(),
            error=True,
        )
    target = texture_editor_layer_pixel_target_state(
        document,
        current_layer_id=current_layer_id,
        layer_pixel_ids=layer_pixels.keys(),
    )
    if not target.available or target.layer is None:
        return texture_editor_channel_missing_operation_state()
    normalized = texture_editor_normalized_channel_key(channel_key, "alpha")
    if texture_editor_channel_alpha_lock_blocked(target.layer, channel_keys=(normalized,)):
        return TextureEditorChannelOperationState(
            status_text=texture_editor_channel_alpha_lock_message("write_selection"),
            error=True,
        )
    return TextureEditorChannelOperationState(
        layer_state=texture_editor_selection_to_channel_state(
            document,
            layer_pixels,
            layer_id=target.layer_id,
            layer=target.layer,
            channel_key=normalized,
        )
    )


def texture_editor_channel_copy_operation_state(
    document: Optional[TextureEditorDocument],
    layer_pixels: Dict[str, np.ndarray],
    *,
    current_layer_id: Optional[str],
    channel_key: object,
) -> TextureEditorChannelOperationState:
    target = texture_editor_layer_pixel_target_state(
        document,
        current_layer_id=current_layer_id,
        layer_pixel_ids=layer_pixels.keys(),
    )
    if not target.layer_id or not target.has_pixels:
        return texture_editor_channel_missing_operation_state()
    return TextureEditorChannelOperationState(
        clipboard_state=texture_editor_channel_clipboard_state(
            layer_pixels[target.layer_id],
            channel_key=texture_editor_normalized_channel_key(channel_key, "alpha"),
        )
    )


def texture_editor_channel_paste_operation_state(
    document: Optional[TextureEditorDocument],
    layer_pixels: Dict[str, np.ndarray],
    *,
    current_layer_id: Optional[str],
    channel_key: object,
    channel_clipboard: Optional[Tuple[np.ndarray, str]],
) -> TextureEditorChannelOperationState:
    if document is None or channel_clipboard is None:
        return texture_editor_channel_missing_operation_state()
    target = texture_editor_layer_pixel_target_state(
        document,
        current_layer_id=current_layer_id,
        layer_pixel_ids=layer_pixels.keys(),
    )
    if not target.available or target.layer is None:
        return texture_editor_channel_missing_operation_state()
    normalized = texture_editor_normalized_channel_key(channel_key, "alpha")
    if texture_editor_channel_alpha_lock_blocked(target.layer, channel_keys=(normalized,)):
        return TextureEditorChannelOperationState(
            status_text=texture_editor_channel_alpha_lock_message("paste"),
            error=True,
        )
    channel_data, _source_key = channel_clipboard
    return TextureEditorChannelOperationState(
        layer_state=texture_editor_pasted_channel_state(
            document,
            layer_pixels,
            layer_id=target.layer_id,
            channel_key=normalized,
            channel_data=channel_data,
        )
    )


def texture_editor_channel_swap_operation_state(
    document: Optional[TextureEditorDocument],
    layer_pixels: Dict[str, np.ndarray],
    *,
    current_layer_id: Optional[str],
    channel_a: object,
    channel_b: object,
) -> TextureEditorChannelOperationState:
    target = texture_editor_layer_pixel_target_state(
        document,
        current_layer_id=current_layer_id,
        layer_pixel_ids=layer_pixels.keys(),
    )
    if document is None or not target.available or target.layer is None:
        return texture_editor_channel_missing_operation_state()
    normalized_a = texture_editor_normalized_channel_key(channel_a, "red")
    normalized_b = texture_editor_normalized_channel_key(channel_b, "blue")
    same_channel_status = texture_editor_same_channel_swap_status(normalized_a, normalized_b)
    if same_channel_status:
        return TextureEditorChannelOperationState(status_text=same_channel_status, error=True)
    if texture_editor_channel_alpha_lock_blocked(target.layer, channel_keys=(normalized_a, normalized_b)):
        return TextureEditorChannelOperationState(
            status_text=texture_editor_channel_alpha_lock_message("swap"),
            error=True,
        )
    return TextureEditorChannelOperationState(
        layer_state=texture_editor_swapped_channels_state(
            document,
            layer_pixels,
            layer_id=target.layer_id,
            channel_a=normalized_a,
            channel_b=normalized_b,
        )
    )


def texture_editor_extracted_channel_layer_state(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    *,
    layer_id: str,
    layer: TextureEditorLayer,
    channel_key: str,
) -> TextureEditorChannelLayerOperationState:
    extracted = extract_texture_editor_layer_channel_to_rgba(layer_pixels[layer_id], channel_key)
    updated_document, updated_pixels, new_id = add_texture_editor_layer(
        document,
        layer_pixels,
        name=f"{layer.name} {texture_editor_channel_title(channel_key)}",
        initial_pixels=extracted,
        offset_x=int(layer.offset_x),
        offset_y=int(layer.offset_y),
    )
    return TextureEditorChannelLayerOperationState(
        document=updated_document,
        layer_pixels=updated_pixels,
        before_layer_pixels=dict(layer_pixels),
        layer_id=layer_id,
        new_layer_id=new_id,
        history_label=texture_editor_channel_operation_history_label("extract", channel_key),
        status_text=texture_editor_channel_operation_status_text("extract", channel_key),
        kind="channel_extract",
        tracked_layer_ids=(layer_id, new_id),
        force_checkpoint=True,
    )


def texture_editor_luma_to_channel_state(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    *,
    layer_id: str,
    channel_key: str,
) -> TextureEditorChannelLayerOperationState:
    updated_pixels = dict(layer_pixels)
    updated_pixels[layer_id] = write_texture_editor_layer_luma_to_channel(layer_pixels[layer_id], channel_key)
    return TextureEditorChannelLayerOperationState(
        document=bump_texture_editor_layer_revision(document, layer_id),
        layer_pixels=updated_pixels,
        before_layer_pixels={layer_id: layer_pixels[layer_id].copy()},
        layer_id=layer_id,
        new_layer_id="",
        history_label=texture_editor_channel_operation_history_label("pack_luma", channel_key),
        status_text=texture_editor_channel_operation_status_text("pack_luma", channel_key),
        kind="channel_pack",
        tracked_layer_ids=(layer_id,),
        force_checkpoint=False,
    )


def texture_editor_channel_to_selection_state(
    document: TextureEditorDocument,
    layer: TextureEditorLayer,
    pixels: np.ndarray,
    *,
    channel_key: str,
    mask_pixels: Optional[np.ndarray],
    combine_mode: str,
) -> TextureEditorChannelDocumentOperationState:
    updated_document = load_texture_editor_layer_channel_as_selection(
        document,
        layer,
        pixels,
        channel_key,
        mask_pixels=mask_pixels,
        combine_mode=combine_mode,
    )
    return TextureEditorChannelDocumentOperationState(
        document=updated_document,
        history_label=texture_editor_channel_operation_history_label("load_selection", channel_key),
        status_text=texture_editor_channel_operation_status_text("load_selection", channel_key),
        kind="selection_update",
        tracked_layer_ids=(),
    )


def texture_editor_selection_to_channel_state(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    *,
    layer_id: str,
    layer: TextureEditorLayer,
    channel_key: str,
) -> TextureEditorChannelLayerOperationState:
    updated_pixels = dict(layer_pixels)
    updated_pixels[layer_id] = write_texture_editor_selection_to_layer_channel(
        document,
        layer,
        layer_pixels[layer_id],
        channel_key,
    )
    return TextureEditorChannelLayerOperationState(
        document=bump_texture_editor_layer_revision(document, layer_id),
        layer_pixels=updated_pixels,
        before_layer_pixels={layer_id: layer_pixels[layer_id].copy()},
        layer_id=layer_id,
        new_layer_id="",
        history_label=texture_editor_channel_operation_history_label("write_selection", channel_key),
        status_text=texture_editor_channel_operation_status_text("write_selection", channel_key),
        kind="channel_pack",
        tracked_layer_ids=(layer_id,),
        force_checkpoint=False,
    )


def texture_editor_channel_clipboard_state(
    pixels: np.ndarray,
    *,
    channel_key: str,
) -> TextureEditorChannelClipboardState:
    return TextureEditorChannelClipboardState(
        clipboard=(copy_texture_editor_layer_channel(pixels, channel_key), channel_key),
        status_text=texture_editor_channel_operation_status_text("copy", channel_key),
    )


def texture_editor_pasted_channel_state(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    *,
    layer_id: str,
    channel_key: str,
    channel_data: np.ndarray,
) -> TextureEditorChannelLayerOperationState:
    updated_pixels = dict(layer_pixels)
    updated_pixels[layer_id] = paste_texture_editor_channel_into_layer(
        layer_pixels[layer_id],
        channel_key,
        channel_data,
    )
    return TextureEditorChannelLayerOperationState(
        document=bump_texture_editor_layer_revision(document, layer_id),
        layer_pixels=updated_pixels,
        before_layer_pixels={layer_id: layer_pixels[layer_id].copy()},
        layer_id=layer_id,
        new_layer_id="",
        history_label=texture_editor_channel_operation_history_label("paste", channel_key),
        status_text=texture_editor_channel_operation_status_text("paste", channel_key),
        kind="channel_pack",
        tracked_layer_ids=(layer_id,),
        force_checkpoint=False,
    )


def texture_editor_swapped_channels_state(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    *,
    layer_id: str,
    channel_a: str,
    channel_b: str,
) -> TextureEditorChannelLayerOperationState:
    updated_pixels = dict(layer_pixels)
    updated_pixels[layer_id] = swap_texture_editor_layer_channels(
        layer_pixels[layer_id],
        channel_a,
        channel_b,
    )
    return TextureEditorChannelLayerOperationState(
        document=bump_texture_editor_layer_revision(document, layer_id),
        layer_pixels=updated_pixels,
        before_layer_pixels={layer_id: layer_pixels[layer_id].copy()},
        layer_id=layer_id,
        new_layer_id="",
        history_label=texture_editor_channel_operation_history_label("swap", channel_a, other_channel_key=channel_b),
        status_text=texture_editor_channel_operation_status_text("swap", channel_a, other_channel_key=channel_b),
        kind="channel_pack",
        tracked_layer_ids=(layer_id,),
        force_checkpoint=False,
    )
