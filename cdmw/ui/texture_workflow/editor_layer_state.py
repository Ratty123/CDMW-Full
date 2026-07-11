from __future__ import annotations

"""Layer list display rules for the standalone Texture Editor UI."""

import dataclasses
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Sequence, Tuple

import numpy as np

from cdmw.domain.textures.editor_layers import (
    add_texture_editor_layer,
    bump_texture_editor_layer_revision,
    create_texture_editor_layer_mask,
    delete_texture_editor_layer_mask,
    duplicate_texture_editor_layer,
    invert_texture_editor_layer_mask,
    merge_texture_editor_layer_down,
    move_texture_editor_layer,
    remove_texture_editor_layer,
    reorder_texture_editor_layer,
    set_texture_editor_layer_mask_enabled,
    update_texture_editor_layer,
)
from cdmw.domain.textures.editor_selection import (
    apply_texture_editor_selection_to_layer_mask,
    load_texture_editor_layer_mask_as_selection,
)
from cdmw.models import TextureEditorDocument, TextureEditorLayer


@dataclass(frozen=True, slots=True)
class TextureEditorLayerControlState:
    name: str
    visible_checked: bool
    locked_checked: bool
    alpha_locked_checked: bool
    mask_enabled_checked: bool
    edit_mask_checked: bool
    blend_mode: str
    opacity: int
    mask_controls_enabled: bool


@dataclass(frozen=True, slots=True)
class TextureEditorLayerPropertyChange:
    changed: bool
    structural_refresh_needed: bool


@dataclass(frozen=True, slots=True)
class TextureEditorLayerLockChange:
    changed: bool


@dataclass(frozen=True, slots=True)
class TextureEditorLayerRenameState:
    name: str
    changed: bool


@dataclass(frozen=True, slots=True)
class TextureEditorLayerDragReorderState:
    changed: bool
    updated_layers: Tuple[TextureEditorLayer, ...]


@dataclass(frozen=True, slots=True)
class TextureEditorEditMaskTargetState:
    allowed: bool
    editing_mask_target: bool
    reset_checkbox: bool
    status_text: str
    error: bool


@dataclass(frozen=True, slots=True)
class TextureEditorLayerPixelTargetState:
    layer_id: str
    layer: Optional[TextureEditorLayer]
    has_pixels: bool
    available: bool


@dataclass(frozen=True, slots=True)
class TextureEditorLayerMaskTargetState:
    layer_id: str
    layer: Optional[TextureEditorLayer]
    mask_layer_id: str
    has_mask_pixels: bool
    can_update_mask_pixels: bool


@dataclass(frozen=True, slots=True)
class TextureEditorSelectionToLayerMaskState:
    changed: bool
    document: TextureEditorDocument
    layer_pixels: Dict[str, np.ndarray]
    mask_layer_id: str
    history_label: str
    status_text: str
    error: bool


@dataclass(frozen=True, slots=True)
class TextureEditorLayerMaskToSelectionState:
    changed: bool
    document: TextureEditorDocument
    history_label: str
    status_text: str
    error: bool


@dataclass(frozen=True, slots=True)
class TextureEditorLayerMaskOperationState:
    changed: bool
    document: TextureEditorDocument
    layer_pixels: Dict[str, np.ndarray]
    before_layer_pixels: Dict[str, object]
    history_label: str
    tracked_layer_ids: Tuple[str, ...]
    force_checkpoint: bool
    invalidate_layer_id: str
    reset_editing_mask_target: bool


@dataclass(frozen=True, slots=True)
class TextureEditorLayerOperationState:
    document: TextureEditorDocument
    layer_pixels: Dict[str, np.ndarray]
    layer_id: str
    history_label: str
    kind: str
    force_checkpoint: bool
    tracked_layer_ids: Tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TextureEditorLayerDocumentUpdateState:
    changed: bool
    document: TextureEditorDocument
    structural_refresh_needed: bool = False


@dataclass(frozen=True, slots=True)
class TextureEditorLayerDocumentOperationState:
    changed: bool
    document: Optional[TextureEditorDocument]
    layer_id: str
    history_label: str
    kind: str = "layer_update"
    structural_refresh_needed: bool = False


@dataclass(frozen=True, slots=True)
class TextureEditorLayerMoveState:
    document: TextureEditorDocument
    layer_id: str
    history_label: str
    kind: str
    tracked_layer_ids: Tuple[str, ...]


def texture_editor_layer_list_label(layer: TextureEditorLayer) -> str:
    prefix = "[Visible]" if layer.visible else "[Hidden]"
    lock_suffix = "  Lock" if layer.locked else ""
    alpha_suffix = "  Alpha" if layer.alpha_locked else ""
    mask_suffix = "  Mask" if layer.mask_layer_id and layer.mask_enabled else ""
    offset_suffix = f"  @{layer.offset_x},{layer.offset_y}" if (layer.offset_x or layer.offset_y) else ""
    return f"{prefix} {layer.name}  {layer.blend_mode.title()}{offset_suffix}{mask_suffix}{lock_suffix}{alpha_suffix}"


def texture_editor_layer_thumbnail_cache_keys(
    layer_id: str,
    cache_keys: Iterable[Tuple[str, int]],
) -> Tuple[Tuple[str, int], ...]:
    return tuple(key for key in cache_keys if key[0] == layer_id)


def texture_editor_current_layer_id(item_value: object) -> Optional[str]:
    return str(item_value) if item_value else None


def texture_editor_active_layer_document(
    document: TextureEditorDocument,
    layer_id: str,
) -> TextureEditorDocument:
    return dataclasses.replace(document, active_layer_id=str(layer_id))


def texture_editor_layer_by_id(
    layers: Sequence[TextureEditorLayer],
    layer_id: Optional[str],
) -> Optional[TextureEditorLayer]:
    if not layer_id:
        return None
    return next((candidate for candidate in layers if candidate.layer_id == layer_id), None)


def texture_editor_layer_refresh_selection_id(
    document: Optional[TextureEditorDocument],
    current_layer_id: Optional[str],
) -> str:
    if document is None:
        return ""
    return str(current_layer_id or document.active_layer_id or "")


def texture_editor_layer_pixel_target_state(
    document: Optional[TextureEditorDocument],
    *,
    current_layer_id: Optional[str],
    layer_pixel_ids: Iterable[str],
) -> TextureEditorLayerPixelTargetState:
    if document is None:
        return TextureEditorLayerPixelTargetState(layer_id="", layer=None, has_pixels=False, available=False)
    layer_id = current_layer_id or document.active_layer_id
    if not layer_id:
        return TextureEditorLayerPixelTargetState(layer_id="", layer=None, has_pixels=False, available=False)
    layer_pixel_id_set = set(layer_pixel_ids)
    layer = texture_editor_layer_by_id(document.layers, layer_id)
    has_pixels = layer_id in layer_pixel_id_set
    return TextureEditorLayerPixelTargetState(
        layer_id=layer_id,
        layer=layer,
        has_pixels=has_pixels,
        available=bool(layer is not None and has_pixels),
    )


def texture_editor_layer_mask_target_state(
    document: Optional[TextureEditorDocument],
    *,
    current_layer_id: Optional[str],
    layer_pixel_ids: Iterable[str],
) -> TextureEditorLayerMaskTargetState:
    if document is None:
        return TextureEditorLayerMaskTargetState("", None, "", False, False)
    layer_id = current_layer_id or document.active_layer_id
    if not layer_id:
        return TextureEditorLayerMaskTargetState("", None, "", False, False)
    layer = texture_editor_layer_by_id(document.layers, layer_id)
    mask_layer_id = str(layer.mask_layer_id or "") if layer is not None else ""
    has_mask_pixels = bool(mask_layer_id and mask_layer_id in set(layer_pixel_ids))
    return TextureEditorLayerMaskTargetState(
        layer_id=layer_id,
        layer=layer,
        mask_layer_id=mask_layer_id,
        has_mask_pixels=has_mask_pixels,
        can_update_mask_pixels=bool(layer is not None and has_mask_pixels),
    )


def texture_editor_layer_mask_invert_before_pixels(
    layer_pixels: dict[str, object],
    mask_layer_id: str,
) -> dict[str, object]:
    pixels = layer_pixels.get(mask_layer_id)
    if hasattr(pixels, "copy"):
        return {mask_layer_id: pixels.copy()}  # type: ignore[union-attr]
    return {}


def texture_editor_layer_mask_history_label(action: str) -> str:
    labels = {
        "add": "Add Layer Mask",
        "invert": "Invert Layer Mask",
        "delete": "Delete Layer Mask",
        "toggle": "Toggle Layer Mask",
        "selection_to_mask": "Selection To Mask",
        "mask_to_selection": "Mask To Selection",
    }
    return labels.get(str(action or "").strip().lower(), "Layer Mask")


def texture_editor_layer_history_label(action: str) -> str:
    labels = {
        "add": "Add Layer",
        "duplicate": "Duplicate Layer",
        "remove": "Remove Layer",
        "merge_down": "Merge Layer Down",
        "reorder": "Reorder Layer",
        "rename": "Rename Layer",
        "change_opacity": "Change Layer Opacity",
        "toggle_visibility": "Toggle Layer Visibility",
        "lock_state": "Layer Lock State",
    }
    return labels.get(str(action or "").strip().lower(), "Layer Update")


def texture_editor_added_layer_state(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
) -> TextureEditorLayerOperationState:
    updated_document, updated_pixels, layer_id = add_texture_editor_layer(document, layer_pixels)
    return TextureEditorLayerOperationState(
        document=updated_document,
        layer_pixels=updated_pixels,
        layer_id=layer_id,
        history_label=texture_editor_layer_history_label("add"),
        kind="layer_add",
        force_checkpoint=True,
        tracked_layer_ids=(),
    )


def texture_editor_duplicated_layer_state(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    layer_id: str,
) -> Optional[TextureEditorLayerOperationState]:
    updated_document, updated_pixels, new_id = duplicate_texture_editor_layer(document, layer_pixels, layer_id)
    if new_id is None:
        return None
    return TextureEditorLayerOperationState(
        document=updated_document,
        layer_pixels=updated_pixels,
        layer_id=new_id,
        history_label=texture_editor_layer_history_label("duplicate"),
        kind="layer_duplicate",
        force_checkpoint=True,
        tracked_layer_ids=(),
    )


def texture_editor_removed_layer_state(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    layer_id: str,
) -> TextureEditorLayerOperationState:
    updated_document, updated_pixels = remove_texture_editor_layer(document, layer_pixels, layer_id)
    return TextureEditorLayerOperationState(
        document=updated_document,
        layer_pixels=updated_pixels,
        layer_id="",
        history_label=texture_editor_layer_history_label("remove"),
        kind="layer_remove",
        force_checkpoint=True,
        tracked_layer_ids=(),
    )


def texture_editor_merged_layer_down_state(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    layer_id: str,
) -> TextureEditorLayerOperationState:
    updated_document, updated_pixels = merge_texture_editor_layer_down(document, layer_pixels, layer_id)
    return TextureEditorLayerOperationState(
        document=updated_document,
        layer_pixels=updated_pixels,
        layer_id="",
        history_label=texture_editor_layer_history_label("merge_down"),
        kind="layer_merge",
        force_checkpoint=True,
        tracked_layer_ids=(),
    )


def texture_editor_reordered_layer_state(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    layer_id: str,
    *,
    direction: int,
) -> TextureEditorLayerOperationState:
    updated_document = reorder_texture_editor_layer(document, layer_id, direction=direction)
    return TextureEditorLayerOperationState(
        document=updated_document,
        layer_pixels=layer_pixels,
        layer_id="",
        history_label=texture_editor_layer_history_label("reorder"),
        kind="layer_reorder",
        force_checkpoint=False,
        tracked_layer_ids=(),
    )


def texture_editor_layer_action_operation_state(
    document: Optional[TextureEditorDocument],
    layer_pixels: Dict[str, np.ndarray],
    *,
    action: str,
    current_layer_id: Optional[str],
    direction: int = 0,
) -> Optional[TextureEditorLayerOperationState]:
    if document is None:
        return None
    action_key = str(action or "").strip().lower()
    if action_key == "add":
        return texture_editor_added_layer_state(document, layer_pixels)
    layer_id = current_layer_id or ""
    if not layer_id:
        return None
    if action_key == "duplicate":
        return texture_editor_duplicated_layer_state(document, layer_pixels, layer_id)
    if action_key == "remove":
        return texture_editor_removed_layer_state(document, layer_pixels, layer_id)
    if action_key == "merge_down":
        return texture_editor_merged_layer_down_state(document, layer_pixels, layer_id)
    if action_key == "reorder":
        return texture_editor_reordered_layer_state(document, layer_pixels, layer_id, direction=direction)
    return None


def texture_editor_moved_layer_state(
    document: TextureEditorDocument,
    layer_id: str,
    *,
    dx: int,
    dy: int,
) -> TextureEditorLayerMoveState:
    return TextureEditorLayerMoveState(
        document=move_texture_editor_layer(document, layer_id, dx=int(dx), dy=int(dy)),
        layer_id=layer_id,
        history_label="Move Layer",
        kind="layer_transform",
        tracked_layer_ids=(),
    )


def added_texture_editor_layer_mask_state(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    *,
    current_layer_id: Optional[str],
) -> TextureEditorLayerMaskOperationState:
    target = texture_editor_layer_mask_target_state(
        document,
        current_layer_id=current_layer_id,
        layer_pixel_ids=layer_pixels.keys(),
    )
    if not target.layer_id:
        return TextureEditorLayerMaskOperationState(
            changed=False,
            document=document,
            layer_pixels=layer_pixels,
            before_layer_pixels={},
            history_label=texture_editor_layer_mask_history_label("add"),
            tracked_layer_ids=(),
            force_checkpoint=False,
            invalidate_layer_id="",
            reset_editing_mask_target=False,
        )
    updated_document, updated_pixels, mask_layer_id = create_texture_editor_layer_mask(
        document,
        layer_pixels,
        target.layer_id,
    )
    return TextureEditorLayerMaskOperationState(
        changed=bool(mask_layer_id),
        document=updated_document,
        layer_pixels=updated_pixels,
        before_layer_pixels=dict(layer_pixels),
        history_label=texture_editor_layer_mask_history_label("add"),
        tracked_layer_ids=(),
        force_checkpoint=True,
        invalidate_layer_id="",
        reset_editing_mask_target=False,
    )


def inverted_texture_editor_layer_mask_state(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    *,
    current_layer_id: Optional[str],
) -> TextureEditorLayerMaskOperationState:
    target = texture_editor_layer_mask_target_state(
        document,
        current_layer_id=current_layer_id,
        layer_pixel_ids=layer_pixels.keys(),
    )
    if not target.can_update_mask_pixels:
        return TextureEditorLayerMaskOperationState(
            changed=False,
            document=document,
            layer_pixels=layer_pixels,
            before_layer_pixels={},
            history_label=texture_editor_layer_mask_history_label("invert"),
            tracked_layer_ids=(),
            force_checkpoint=False,
            invalidate_layer_id="",
            reset_editing_mask_target=False,
        )
    updated_pixels = invert_texture_editor_layer_mask(document, layer_pixels, target.layer_id)
    updated_document = bump_texture_editor_layer_revision(document, target.layer_id)
    return TextureEditorLayerMaskOperationState(
        changed=True,
        document=updated_document,
        layer_pixels=updated_pixels,
        before_layer_pixels=texture_editor_layer_mask_invert_before_pixels(layer_pixels, target.mask_layer_id),
        history_label=texture_editor_layer_mask_history_label("invert"),
        tracked_layer_ids=(target.mask_layer_id,),
        force_checkpoint=False,
        invalidate_layer_id=target.layer_id,
        reset_editing_mask_target=False,
    )


def deleted_texture_editor_layer_mask_state(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    *,
    current_layer_id: Optional[str],
) -> TextureEditorLayerMaskOperationState:
    target = texture_editor_layer_mask_target_state(
        document,
        current_layer_id=current_layer_id,
        layer_pixel_ids=layer_pixels.keys(),
    )
    if not target.layer_id:
        return TextureEditorLayerMaskOperationState(
            changed=False,
            document=document,
            layer_pixels=layer_pixels,
            before_layer_pixels={},
            history_label=texture_editor_layer_mask_history_label("delete"),
            tracked_layer_ids=(),
            force_checkpoint=False,
            invalidate_layer_id="",
            reset_editing_mask_target=False,
        )
    updated_document, updated_pixels = delete_texture_editor_layer_mask(document, layer_pixels, target.layer_id)
    return TextureEditorLayerMaskOperationState(
        changed=True,
        document=updated_document,
        layer_pixels=updated_pixels,
        before_layer_pixels=dict(layer_pixels),
        history_label=texture_editor_layer_mask_history_label("delete"),
        tracked_layer_ids=(),
        force_checkpoint=True,
        invalidate_layer_id="",
        reset_editing_mask_target=True,
    )


def toggled_texture_editor_layer_mask_state(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    *,
    current_layer_id: Optional[str],
    checked: bool,
) -> TextureEditorLayerMaskOperationState:
    target = texture_editor_layer_mask_target_state(
        document,
        current_layer_id=current_layer_id,
        layer_pixel_ids=layer_pixels.keys(),
    )
    if not target.layer_id:
        return TextureEditorLayerMaskOperationState(
            changed=False,
            document=document,
            layer_pixels=layer_pixels,
            before_layer_pixels={},
            history_label=texture_editor_layer_mask_history_label("toggle"),
            tracked_layer_ids=(),
            force_checkpoint=False,
            invalidate_layer_id="",
            reset_editing_mask_target=False,
        )
    return TextureEditorLayerMaskOperationState(
        changed=True,
        document=set_texture_editor_layer_mask_enabled(document, target.layer_id, checked),
        layer_pixels=layer_pixels,
        before_layer_pixels={},
        history_label=texture_editor_layer_mask_history_label("toggle"),
        tracked_layer_ids=(),
        force_checkpoint=False,
        invalidate_layer_id=target.layer_id,
        reset_editing_mask_target=False,
    )


def texture_editor_selection_to_layer_mask_state(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    layer_id: str,
) -> TextureEditorSelectionToLayerMaskState:
    updated_document, updated_pixels, mask_layer_id = apply_texture_editor_selection_to_layer_mask(
        document,
        layer_pixels,
        layer_id,
    )
    if not mask_layer_id:
        return TextureEditorSelectionToLayerMaskState(
            changed=False,
            document=document,
            layer_pixels=layer_pixels,
            mask_layer_id="",
            history_label=texture_editor_layer_mask_history_label("selection_to_mask"),
            status_text="Create a selection first, then use Selection To Mask.",
            error=True,
        )
    return TextureEditorSelectionToLayerMaskState(
        changed=True,
        document=updated_document,
        layer_pixels=updated_pixels,
        mask_layer_id=str(mask_layer_id),
        history_label=texture_editor_layer_mask_history_label("selection_to_mask"),
        status_text="Converted the current selection into the active layer mask.",
        error=False,
    )


def texture_editor_selection_to_current_layer_mask_state(
    document: Optional[TextureEditorDocument],
    layer_pixels: Dict[str, np.ndarray],
    *,
    current_layer_id: Optional[str],
) -> TextureEditorSelectionToLayerMaskState:
    if document is None:
        return TextureEditorSelectionToLayerMaskState(
            changed=False,
            document=TextureEditorDocument("", 0, 0),
            layer_pixels=layer_pixels,
            mask_layer_id="",
            history_label=texture_editor_layer_mask_history_label("selection_to_mask"),
            status_text="Create a selection first, then use Selection To Mask.",
            error=True,
        )
    layer_id = current_layer_id or document.active_layer_id
    if not layer_id:
        return TextureEditorSelectionToLayerMaskState(
            changed=False,
            document=document,
            layer_pixels=layer_pixels,
            mask_layer_id="",
            history_label=texture_editor_layer_mask_history_label("selection_to_mask"),
            status_text="Select a layer before using Selection To Mask.",
            error=True,
        )
    return texture_editor_selection_to_layer_mask_state(document, layer_pixels, layer_id)


def texture_editor_layer_mask_to_selection_state(
    document: TextureEditorDocument,
    layer_pixels: Dict[str, np.ndarray],
    layer_id: str,
    *,
    combine_mode: str,
) -> TextureEditorLayerMaskToSelectionState:
    updated_document = load_texture_editor_layer_mask_as_selection(
        document,
        layer_pixels,
        layer_id,
        combine_mode=combine_mode,
    )
    changed = updated_document is not document
    if not changed:
        return TextureEditorLayerMaskToSelectionState(
            changed=False,
            document=document,
            history_label=texture_editor_layer_mask_history_label("mask_to_selection"),
            status_text="The active layer does not have a mask to load as a selection.",
            error=True,
        )
    return TextureEditorLayerMaskToSelectionState(
        changed=True,
        document=updated_document,
        history_label=texture_editor_layer_mask_history_label("mask_to_selection"),
        status_text="Loaded the active layer mask into the current selection.",
        error=False,
    )


def texture_editor_current_layer_mask_to_selection_state(
    document: Optional[TextureEditorDocument],
    layer_pixels: Dict[str, np.ndarray],
    *,
    current_layer_id: Optional[str],
    combine_mode: str,
) -> TextureEditorLayerMaskToSelectionState:
    if document is None:
        return TextureEditorLayerMaskToSelectionState(
            changed=False,
            document=TextureEditorDocument("", 0, 0),
            history_label=texture_editor_layer_mask_history_label("mask_to_selection"),
            status_text="The active layer does not have a mask to load as a selection.",
            error=True,
        )
    layer_id = current_layer_id or document.active_layer_id
    if not layer_id:
        return TextureEditorLayerMaskToSelectionState(
            changed=False,
            document=document,
            history_label=texture_editor_layer_mask_history_label("mask_to_selection"),
            status_text="Select a layer before loading its mask as a selection.",
            error=True,
        )
    return texture_editor_layer_mask_to_selection_state(
        document,
        layer_pixels,
        layer_id,
        combine_mode=combine_mode,
    )


def texture_editor_edit_target_layer_id(
    document: Optional[TextureEditorDocument],
    *,
    current_layer_id: Optional[str],
    editing_mask_target: bool,
) -> Optional[str]:
    if document is None:
        return None
    layer_id = current_layer_id or document.active_layer_id
    if not layer_id:
        return None
    if not editing_mask_target:
        return layer_id
    layer = texture_editor_layer_by_id(document.layers, layer_id)
    if layer is None or not layer.mask_layer_id:
        return layer_id
    return layer.mask_layer_id


def texture_editor_layer_control_state(
    layer: TextureEditorLayer,
    *,
    layer_pixel_ids: Iterable[str],
    editing_mask_target: bool,
) -> TextureEditorLayerControlState:
    layer_pixel_id_set = set(layer_pixel_ids)
    has_mask = bool(layer.mask_layer_id and layer.mask_layer_id in layer_pixel_id_set)
    return TextureEditorLayerControlState(
        name=layer.name,
        visible_checked=bool(layer.visible),
        locked_checked=bool(layer.locked),
        alpha_locked_checked=bool(layer.alpha_locked),
        mask_enabled_checked=bool(layer.mask_layer_id) and bool(layer.mask_enabled),
        edit_mask_checked=bool(editing_mask_target and layer.mask_layer_id),
        blend_mode=str(layer.blend_mode or "normal"),
        opacity=int(layer.opacity),
        mask_controls_enabled=has_mask,
    )


def texture_editor_layer_property_change(
    layer: TextureEditorLayer,
    *,
    visible: bool,
    opacity: int,
    blend_mode: str,
) -> TextureEditorLayerPropertyChange:
    next_visible = bool(visible)
    next_opacity = int(opacity)
    next_blend_mode = str(blend_mode or "normal")
    visible_changed = layer.visible != next_visible
    blend_mode_changed = layer.blend_mode != next_blend_mode
    changed = visible_changed or layer.opacity != next_opacity or blend_mode_changed
    return TextureEditorLayerPropertyChange(
        changed=changed,
        structural_refresh_needed=visible_changed or blend_mode_changed,
    )


def texture_editor_layer_lock_change(
    layer: TextureEditorLayer,
    *,
    locked: bool,
    alpha_locked: bool,
) -> TextureEditorLayerLockChange:
    return TextureEditorLayerLockChange(
        changed=layer.locked != bool(locked) or layer.alpha_locked != bool(alpha_locked),
    )


def texture_editor_layer_rename_state(
    layer: TextureEditorLayer,
    *,
    raw_name: str,
) -> TextureEditorLayerRenameState:
    name = str(raw_name or "").strip() or "Layer"
    return TextureEditorLayerRenameState(name=name, changed=name != layer.name)


def texture_editor_renamed_layer_document_state(
    document: TextureEditorDocument,
    layer_id: str,
    *,
    raw_name: str,
) -> TextureEditorLayerDocumentUpdateState:
    layer = texture_editor_layer_by_id(document.layers, layer_id)
    if layer is None:
        return TextureEditorLayerDocumentUpdateState(changed=False, document=document)
    rename_state = texture_editor_layer_rename_state(layer, raw_name=raw_name)
    if not rename_state.changed:
        return TextureEditorLayerDocumentUpdateState(changed=False, document=document)
    return TextureEditorLayerDocumentUpdateState(
        changed=True,
        document=update_texture_editor_layer(document, layer_id, name=rename_state.name),
    )


def texture_editor_layer_rename_operation_state(
    document: Optional[TextureEditorDocument],
    *,
    current_layer_id: Optional[str],
    raw_name: str,
) -> TextureEditorLayerDocumentOperationState:
    if document is None or not current_layer_id:
        return TextureEditorLayerDocumentOperationState(
            changed=False,
            document=document,
            layer_id="",
            history_label=texture_editor_layer_history_label("rename"),
        )
    update_state = texture_editor_renamed_layer_document_state(document, current_layer_id, raw_name=raw_name)
    return TextureEditorLayerDocumentOperationState(
        changed=update_state.changed,
        document=update_state.document,
        layer_id=current_layer_id,
        history_label=texture_editor_layer_history_label("rename"),
    )


def texture_editor_layer_properties_document_state(
    document: TextureEditorDocument,
    layer_id: str,
    *,
    visible: bool,
    opacity: int,
    blend_mode: str,
) -> TextureEditorLayerDocumentUpdateState:
    layer = texture_editor_layer_by_id(document.layers, layer_id)
    if layer is None:
        return TextureEditorLayerDocumentUpdateState(changed=False, document=document)
    change = texture_editor_layer_property_change(
        layer,
        visible=visible,
        opacity=opacity,
        blend_mode=blend_mode,
    )
    if not change.changed:
        return TextureEditorLayerDocumentUpdateState(changed=False, document=document)
    return TextureEditorLayerDocumentUpdateState(
        changed=True,
        document=update_texture_editor_layer(
            document,
            layer_id,
            visible=visible,
            opacity=opacity,
            blend_mode=blend_mode,
        ),
        structural_refresh_needed=change.structural_refresh_needed,
    )


def texture_editor_layer_properties_operation_state(
    document: Optional[TextureEditorDocument],
    *,
    current_layer_id: Optional[str],
    visible: bool,
    opacity: int,
    blend_mode: str,
) -> TextureEditorLayerDocumentOperationState:
    if document is None or not current_layer_id:
        return TextureEditorLayerDocumentOperationState(
            changed=False,
            document=document,
            layer_id="",
            history_label=texture_editor_layer_history_label("change_opacity"),
        )
    update_state = texture_editor_layer_properties_document_state(
        document,
        current_layer_id,
        visible=visible,
        opacity=opacity,
        blend_mode=blend_mode,
    )
    return TextureEditorLayerDocumentOperationState(
        changed=update_state.changed,
        document=update_state.document,
        layer_id=current_layer_id,
        history_label=texture_editor_layer_history_label("change_opacity"),
        structural_refresh_needed=update_state.structural_refresh_needed,
    )


def texture_editor_layer_lock_document_state(
    document: TextureEditorDocument,
    layer_id: str,
    *,
    locked: bool,
    alpha_locked: bool,
) -> TextureEditorLayerDocumentUpdateState:
    layer = texture_editor_layer_by_id(document.layers, layer_id)
    if layer is None:
        return TextureEditorLayerDocumentUpdateState(changed=False, document=document)
    lock_change = texture_editor_layer_lock_change(layer, locked=locked, alpha_locked=alpha_locked)
    if not lock_change.changed:
        return TextureEditorLayerDocumentUpdateState(changed=False, document=document)
    return TextureEditorLayerDocumentUpdateState(
        changed=True,
        document=update_texture_editor_layer(
            document,
            layer_id,
            locked=locked,
            alpha_locked=alpha_locked,
        ),
    )


def texture_editor_layer_lock_operation_state(
    document: Optional[TextureEditorDocument],
    *,
    current_layer_id: Optional[str],
    locked: bool,
    alpha_locked: bool,
) -> TextureEditorLayerDocumentOperationState:
    if document is None or not current_layer_id:
        return TextureEditorLayerDocumentOperationState(
            changed=False,
            document=document,
            layer_id="",
            history_label=texture_editor_layer_history_label("lock_state"),
        )
    update_state = texture_editor_layer_lock_document_state(
        document,
        current_layer_id,
        locked=locked,
        alpha_locked=alpha_locked,
    )
    return TextureEditorLayerDocumentOperationState(
        changed=update_state.changed,
        document=update_state.document,
        layer_id=current_layer_id,
        history_label=texture_editor_layer_history_label("lock_state"),
    )


def texture_editor_drag_reorder_state(
    layers: Sequence[TextureEditorLayer],
    *,
    display_layer_ids: Sequence[str],
) -> TextureEditorLayerDragReorderState:
    if len(display_layer_ids) != len(layers):
        return TextureEditorLayerDragReorderState(changed=False, updated_layers=tuple(layers))
    desired_document_order = tuple(reversed(tuple(str(layer_id) for layer_id in display_layer_ids if layer_id)))
    current_document_order = tuple(layer.layer_id for layer in layers)
    if desired_document_order == current_document_order:
        return TextureEditorLayerDragReorderState(changed=False, updated_layers=tuple(layers))
    layers_by_id = {layer.layer_id: layer for layer in layers}
    if set(desired_document_order) != set(layers_by_id.keys()):
        return TextureEditorLayerDragReorderState(changed=False, updated_layers=tuple(layers))
    updated_layers = tuple(
        dataclasses.replace(
            layers_by_id[layer_id],
            revision=int(layers_by_id[layer_id].revision) + 1,
        )
        for layer_id in desired_document_order
    )
    return TextureEditorLayerDragReorderState(changed=True, updated_layers=updated_layers)


def texture_editor_drag_reordered_document_state(
    document: TextureEditorDocument,
    *,
    display_layer_ids: Sequence[str],
) -> TextureEditorLayerDocumentUpdateState:
    reorder_state = texture_editor_drag_reorder_state(document.layers, display_layer_ids=display_layer_ids)
    if not reorder_state.changed:
        return TextureEditorLayerDocumentUpdateState(changed=False, document=document)
    return TextureEditorLayerDocumentUpdateState(
        changed=True,
        document=dataclasses.replace(
            document,
            layers=reorder_state.updated_layers,
            composite_revision=int(document.composite_revision) + 1,
        ),
    )


def texture_editor_layers_reordered_status_text() -> str:
    return "Reordered layers."


def texture_editor_edit_mask_target_state(
    *,
    checked: bool,
    layer: Optional[TextureEditorLayer],
    layer_pixel_ids: Iterable[str],
) -> TextureEditorEditMaskTargetState:
    if checked:
        layer_pixel_id_set = set(layer_pixel_ids)
        if layer is None or not layer.mask_layer_id or layer.mask_layer_id not in layer_pixel_id_set:
            return TextureEditorEditMaskTargetState(
                allowed=False,
                editing_mask_target=False,
                reset_checkbox=True,
                status_text="Add a layer mask before switching the editor into mask paint mode.",
                error=True,
            )
        return TextureEditorEditMaskTargetState(
            allowed=True,
            editing_mask_target=True,
            reset_checkbox=False,
            status_text="Editing active layer mask. Paint/erase and other brush tools will target the mask.",
            error=False,
        )
    return TextureEditorEditMaskTargetState(
        allowed=True,
        editing_mask_target=False,
        reset_checkbox=False,
        status_text="",
        error=False,
    )
