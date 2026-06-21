from __future__ import annotations

"""Adjustment display and default-state helpers for the standalone Texture Editor UI."""

import dataclasses
from dataclasses import dataclass
from typing import Dict, Optional, Sequence

from cdmw.core.texture_editor import (
    add_texture_editor_adjustment_layer,
    remove_texture_editor_adjustment_layer,
    update_texture_editor_adjustment_layer,
)
from cdmw.models import TextureEditorAdjustmentLayer, TextureEditorDocument


@dataclass(frozen=True, slots=True)
class TextureEditorAdjustmentParamState:
    label: str
    minimum: int
    maximum: int
    value: int


@dataclass(frozen=True, slots=True)
class TextureEditorAdjustmentControlState:
    has_adjustment: bool
    enabled_checked: bool
    opacity: int
    mode_visible: bool
    mode_value: str
    mode_enabled: bool
    params: tuple[TextureEditorAdjustmentParamState, ...]


@dataclass(frozen=True, slots=True)
class TextureEditorAdjustmentMoveState:
    changed: bool
    document: TextureEditorDocument
    target_index: int


@dataclass(frozen=True, slots=True)
class TextureEditorAdjustmentSoloState:
    found: bool
    document: TextureEditorDocument


@dataclass(frozen=True, slots=True)
class TextureEditorAdjustmentDocumentState:
    changed: bool
    document: TextureEditorDocument
    adjustment_id: str
    preserve_selection_id: str
    history_label: str
    status_text: str
    kind: str
    tracked_layer_ids: tuple[str, ...]


def texture_editor_adjustment_display_name(adjustment_type: str) -> str:
    display_names = {
        "hue_saturation": "Hue / Saturation",
        "vibrance": "Vibrance",
        "selective_color": "Selective Color",
        "brightness_contrast": "Brightness / Contrast",
        "exposure": "Exposure",
        "color_balance": "Color Balance",
        "levels": "Levels",
        "curves": "Curves",
    }
    return display_names.get(str(adjustment_type or "").strip(), "Adjustment")


def texture_editor_adjustment_copy_name(name: str) -> str:
    return f"{str(name or 'Adjustment').strip() or 'Adjustment'} Copy"


def texture_editor_adjustment_history_label(action: str) -> str:
    labels = {
        "add": "Add Adjustment",
        "remove": "Remove Adjustment",
        "duplicate": "Duplicate Adjustment",
        "move": "Move Adjustment",
        "solo": "Solo Adjustment",
        "assign_mask": "Assign Adjustment Mask",
        "clear_mask": "Clear Adjustment Mask",
        "reset": "Reset Adjustment",
        "update": "Adjustment Update",
    }
    return labels.get(str(action or "").strip().lower(), "Adjustment Update")


def texture_editor_adjustment_status_text(action: str) -> str:
    messages = {
        "solo": "Soloed the selected adjustment. Re-enable others manually if needed.",
        "assign_mask": "Assigned the active raster layer as the selected adjustment mask.",
    }
    return messages.get(str(action or "").strip().lower(), "")


def _texture_editor_adjustment_document_state(
    document: TextureEditorDocument,
    updated_document: TextureEditorDocument,
    *,
    action: str,
    adjustment_id: str = "",
    preserve_selection_id: str = "",
) -> TextureEditorAdjustmentDocumentState:
    normalized_action = str(action or "update").strip().lower()
    return TextureEditorAdjustmentDocumentState(
        changed=updated_document != document,
        document=updated_document,
        adjustment_id=str(adjustment_id or ""),
        preserve_selection_id=str(preserve_selection_id or ""),
        history_label=texture_editor_adjustment_history_label(normalized_action),
        status_text=texture_editor_adjustment_status_text(normalized_action),
        kind="adjustment_update",
        tracked_layer_ids=(),
    )


def added_texture_editor_adjustment_state(
    document: TextureEditorDocument,
    adjustment_type: str,
) -> TextureEditorAdjustmentDocumentState:
    normalized_type = str(adjustment_type or "levels")
    updated_document = add_texture_editor_adjustment_layer(
        document,
        adjustment_type=normalized_type,
        name=texture_editor_adjustment_display_name(normalized_type),
        parameters=default_texture_editor_adjustment_parameters(normalized_type),
    )
    adjustment_id = updated_document.adjustment_layers[-1].layer_id if updated_document.adjustment_layers else ""
    return _texture_editor_adjustment_document_state(
        document,
        updated_document,
        action="add",
        adjustment_id=adjustment_id,
        preserve_selection_id=adjustment_id,
    )


def removed_texture_editor_adjustment_state(
    document: TextureEditorDocument,
    adjustment_id: str,
) -> TextureEditorAdjustmentDocumentState:
    updated_document = remove_texture_editor_adjustment_layer(document, adjustment_id)
    return _texture_editor_adjustment_document_state(
        document,
        updated_document,
        action="remove",
        adjustment_id=adjustment_id,
    )


def duplicated_texture_editor_adjustment_state(
    document: TextureEditorDocument,
    adjustment: TextureEditorAdjustmentLayer,
) -> TextureEditorAdjustmentDocumentState:
    copy_name = texture_editor_adjustment_copy_name(adjustment.name)
    duplicated_document = add_texture_editor_adjustment_layer(
        document,
        adjustment_type=adjustment.adjustment_type,
        name=copy_name,
        parameters=dict(adjustment.parameters),
    )
    duplicated_adjustment = duplicated_document.adjustment_layers[-1]
    updated_document = update_texture_editor_adjustment_layer(
        duplicated_document,
        duplicated_adjustment.layer_id,
        enabled=adjustment.enabled,
        opacity=adjustment.opacity,
        parameters=dict(adjustment.parameters),
        mask_layer_id=adjustment.mask_layer_id,
        name=copy_name,
    )
    return _texture_editor_adjustment_document_state(
        document,
        updated_document,
        action="duplicate",
        adjustment_id=duplicated_adjustment.layer_id,
        preserve_selection_id=duplicated_adjustment.layer_id,
    )


def assigned_texture_editor_adjustment_mask_state(
    document: TextureEditorDocument,
    adjustment_id: str,
    mask_layer_id: str,
) -> TextureEditorAdjustmentDocumentState:
    if not adjustment_id or not mask_layer_id:
        return _texture_editor_adjustment_document_state(
            document,
            document,
            action="assign_mask",
            adjustment_id=adjustment_id,
        )
    updated_document = update_texture_editor_adjustment_layer(
        document,
        adjustment_id,
        mask_layer_id=mask_layer_id,
    )
    return _texture_editor_adjustment_document_state(
        document,
        updated_document,
        action="assign_mask",
        adjustment_id=adjustment_id,
        preserve_selection_id=adjustment_id,
    )


def cleared_texture_editor_adjustment_mask_state(
    document: TextureEditorDocument,
    adjustment: TextureEditorAdjustmentLayer,
) -> TextureEditorAdjustmentDocumentState:
    if not adjustment.mask_layer_id:
        return _texture_editor_adjustment_document_state(
            document,
            document,
            action="clear_mask",
            adjustment_id=adjustment.layer_id,
        )
    updated_document = update_texture_editor_adjustment_layer(
        document,
        adjustment.layer_id,
        mask_layer_id="",
    )
    return _texture_editor_adjustment_document_state(
        document,
        updated_document,
        action="clear_mask",
        adjustment_id=adjustment.layer_id,
        preserve_selection_id=adjustment.layer_id,
    )


def reset_texture_editor_adjustment_state(
    document: TextureEditorDocument,
    adjustment: TextureEditorAdjustmentLayer,
) -> TextureEditorAdjustmentDocumentState:
    updated_document = update_texture_editor_adjustment_layer(
        document,
        adjustment.layer_id,
        enabled=adjustment.enabled,
        opacity=adjustment.opacity,
        parameters=default_texture_editor_adjustment_parameters(adjustment.adjustment_type),
    )
    return _texture_editor_adjustment_document_state(
        document,
        updated_document,
        action="reset",
        adjustment_id=adjustment.layer_id,
        preserve_selection_id=adjustment.layer_id,
    )


def updated_texture_editor_adjustment_properties_document(
    document: TextureEditorDocument,
    adjustment: TextureEditorAdjustmentLayer,
    *,
    enabled: bool,
    opacity: int,
    parameters: Dict[str, object],
) -> TextureEditorDocument:
    return update_texture_editor_adjustment_layer(
        document,
        adjustment.layer_id,
        enabled=enabled,
        opacity=opacity,
        parameters=parameters,
    )


def texture_editor_selected_adjustment(
    adjustment_layers: Sequence[TextureEditorAdjustmentLayer],
    adjustment_id: Optional[str],
) -> Optional[TextureEditorAdjustmentLayer]:
    if not adjustment_id:
        return None
    return next((layer for layer in adjustment_layers if layer.layer_id == adjustment_id), None)


def texture_editor_adjustment_refresh_selection_id(
    adjustment_layers: Sequence[TextureEditorAdjustmentLayer],
    requested_adjustment_id: Optional[str],
) -> str:
    if requested_adjustment_id and texture_editor_selected_adjustment(adjustment_layers, requested_adjustment_id):
        return str(requested_adjustment_id)
    if adjustment_layers:
        return str(adjustment_layers[-1].layer_id)
    return ""


def texture_editor_adjustment_operation_state(
    document: Optional[TextureEditorDocument],
    *,
    action: str,
    adjustment_id: str = "",
    adjustment_type: str = "",
    direction: int = 0,
    active_layer_id: str = "",
) -> Optional[TextureEditorAdjustmentDocumentState]:
    if document is None:
        return None
    action_key = str(action or "").strip().lower()
    selected = texture_editor_selected_adjustment(document.adjustment_layers, adjustment_id)
    if action_key == "add":
        return added_texture_editor_adjustment_state(document, adjustment_type)
    if action_key == "remove":
        if not adjustment_id:
            return None
        return removed_texture_editor_adjustment_state(document, adjustment_id)
    if action_key == "duplicate":
        if selected is None:
            return None
        return duplicated_texture_editor_adjustment_state(document, selected)
    if action_key == "move":
        if not adjustment_id:
            return None
        move_state = moved_texture_editor_adjustment_document(document, adjustment_id, direction=direction)
        return _texture_editor_adjustment_document_state(
            document,
            move_state.document,
            action="move",
            adjustment_id=adjustment_id,
            preserve_selection_id=adjustment_id if move_state.changed else "",
        )
    if action_key == "solo":
        if not adjustment_id:
            return None
        solo_state = solo_texture_editor_adjustment_document(document, adjustment_id)
        if not solo_state.found:
            return None
        return _texture_editor_adjustment_document_state(
            document,
            solo_state.document,
            action="solo",
            adjustment_id=adjustment_id,
            preserve_selection_id=adjustment_id,
        )
    if action_key == "assign_mask":
        if selected is None or not active_layer_id:
            return None
        return assigned_texture_editor_adjustment_mask_state(document, selected.layer_id, active_layer_id)
    if action_key == "clear_mask":
        if selected is None or not selected.mask_layer_id:
            return None
        return cleared_texture_editor_adjustment_mask_state(document, selected)
    if action_key == "reset":
        if selected is None:
            return None
        return reset_texture_editor_adjustment_state(document, selected)
    return None


def texture_editor_adjustment_properties_update_state(
    document: Optional[TextureEditorDocument],
    *,
    adjustment_id: Optional[str],
    enabled: bool,
    opacity: int,
    parameters: Dict[str, object],
) -> Optional[TextureEditorAdjustmentDocumentState]:
    if document is None:
        return None
    adjustment = texture_editor_selected_adjustment(document.adjustment_layers, adjustment_id)
    if adjustment is None:
        return None
    updated_document = updated_texture_editor_adjustment_properties_document(
        document,
        adjustment,
        enabled=enabled,
        opacity=opacity,
        parameters=parameters,
    )
    return _texture_editor_adjustment_document_state(
        document,
        updated_document,
        action="update",
        adjustment_id=adjustment.layer_id,
        preserve_selection_id=adjustment.layer_id,
    )


def default_texture_editor_adjustment_parameters(adjustment_type: str) -> Dict[str, object]:
    adjustment_key = (adjustment_type or "levels").strip().lower()
    if adjustment_key == "hue_saturation":
        return {"hue": 0.0, "saturation": 0.0, "lightness": 0.0}
    if adjustment_key == "vibrance":
        return {"vibrance": 0.0, "saturation": 0.0, "lightness": 0.0}
    if adjustment_key == "selective_color":
        return {
            "target_range": "neutrals",
            "red_cyan": 0.0,
            "green_magenta": 0.0,
            "blue_yellow": 0.0,
        }
    if adjustment_key == "brightness_contrast":
        return {"brightness": 0.0, "contrast": 0.0, "saturation": 0.0}
    if adjustment_key == "exposure":
        return {"exposure": 0.0, "offset": 0.0, "gamma": 1.0}
    if adjustment_key == "color_balance":
        return {"red_cyan": 0.0, "green_magenta": 0.0, "blue_yellow": 0.0}
    if adjustment_key == "curves":
        return {"shadows": 0.0, "midtones": 0.0, "highlights": 0.0}
    return {"black": 0.0, "gamma": 1.0, "white": 255.0, "output_black": 0.0, "output_white": 255.0}


def texture_editor_adjustment_list_label(adjustment: TextureEditorAdjustmentLayer) -> str:
    prefix = "[On]" if adjustment.enabled else "[Off]"
    mask_suffix = "  Mask" if adjustment.mask_layer_id else ""
    if adjustment.adjustment_type == "hue_saturation":
        hue = int(round(float(adjustment.parameters.get("hue", 0.0))))
        sat = int(round(float(adjustment.parameters.get("saturation", 0.0))))
        light = int(round(float(adjustment.parameters.get("lightness", 0.0))))
        return f"{prefix} {adjustment.name}{mask_suffix}  H:{hue:+d} S:{sat:+d} L:{light:+d}"
    if adjustment.adjustment_type == "vibrance":
        vibrance = int(round(float(adjustment.parameters.get("vibrance", 0.0))))
        sat = int(round(float(adjustment.parameters.get("saturation", 0.0))))
        light = int(round(float(adjustment.parameters.get("lightness", 0.0))))
        return f"{prefix} {adjustment.name}{mask_suffix}  Vib:{vibrance:+d} S:{sat:+d} L:{light:+d}"
    if adjustment.adjustment_type == "selective_color":
        target = str(adjustment.parameters.get("target_range", "neutrals") or "neutrals").title()
        red = int(round(float(adjustment.parameters.get("red_cyan", 0.0))))
        green = int(round(float(adjustment.parameters.get("green_magenta", 0.0))))
        blue = int(round(float(adjustment.parameters.get("blue_yellow", 0.0))))
        return f"{prefix} {adjustment.name}{mask_suffix}  {target}  R:{red:+d} G:{green:+d} B:{blue:+d}"
    if adjustment.adjustment_type == "brightness_contrast":
        brightness = int(round(float(adjustment.parameters.get("brightness", 0.0))))
        contrast = int(round(float(adjustment.parameters.get("contrast", 0.0))))
        saturation = int(round(float(adjustment.parameters.get("saturation", 0.0))))
        return f"{prefix} {adjustment.name}{mask_suffix}  Br:{brightness:+d} Ct:{contrast:+d} Sat:{saturation:+d}"
    if adjustment.adjustment_type == "exposure":
        exposure = int(round(float(adjustment.parameters.get("exposure", 0.0))))
        offset = int(round(float(adjustment.parameters.get("offset", 0.0))))
        gamma = float(adjustment.parameters.get("gamma", 1.0))
        return f"{prefix} {adjustment.name}{mask_suffix}  Exp:{exposure:+d} Off:{offset:+d} G:{gamma:.2f}"
    if adjustment.adjustment_type == "color_balance":
        red = int(round(float(adjustment.parameters.get("red_cyan", 0.0))))
        green = int(round(float(adjustment.parameters.get("green_magenta", 0.0))))
        blue = int(round(float(adjustment.parameters.get("blue_yellow", 0.0))))
        return f"{prefix} {adjustment.name}{mask_suffix}  R:{red:+d} G:{green:+d} B:{blue:+d}"
    if adjustment.adjustment_type == "curves":
        shadows = int(round(float(adjustment.parameters.get("shadows", 0.0))))
        mids = int(round(float(adjustment.parameters.get("midtones", 0.0))))
        highs = int(round(float(adjustment.parameters.get("highlights", 0.0))))
        return f"{prefix} {adjustment.name}{mask_suffix}  Sh:{shadows:+d} Mid:{mids:+d} Hi:{highs:+d}"
    black = int(round(float(adjustment.parameters.get("black", 0.0))))
    gamma = float(adjustment.parameters.get("gamma", 1.0))
    white = int(round(float(adjustment.parameters.get("white", 255.0))))
    return f"{prefix} {adjustment.name}{mask_suffix}  B:{black} G:{gamma:.2f} W:{white}"


def _adjustment_int_param(adjustment: TextureEditorAdjustmentLayer, key: str, default: float = 0.0, *, scale: float = 1.0) -> int:
    return int(round(float(adjustment.parameters.get(key, default)) * float(scale)))


def _adjustment_param_state(
    label: str,
    minimum: int,
    maximum: int,
    value: int,
) -> TextureEditorAdjustmentParamState:
    return TextureEditorAdjustmentParamState(
        label=label,
        minimum=int(minimum),
        maximum=int(maximum),
        value=int(value),
    )


def texture_editor_adjustment_control_state(
    adjustment: TextureEditorAdjustmentLayer | None,
) -> TextureEditorAdjustmentControlState:
    if adjustment is None:
        return TextureEditorAdjustmentControlState(
            has_adjustment=False,
            enabled_checked=False,
            opacity=100,
            mode_visible=False,
            mode_value="neutrals",
            mode_enabled=False,
            params=(),
        )
    adjustment_type = str(adjustment.adjustment_type or "levels")
    mode_visible = adjustment_type == "selective_color"
    mode_value = str(adjustment.parameters.get("target_range", "neutrals") or "neutrals")
    if adjustment_type == "hue_saturation":
        params = (
            _adjustment_param_state("Hue", -180, 180, _adjustment_int_param(adjustment, "hue")),
            _adjustment_param_state("Saturation", -100, 100, _adjustment_int_param(adjustment, "saturation")),
            _adjustment_param_state("Lightness", -100, 100, _adjustment_int_param(adjustment, "lightness")),
        )
    elif adjustment_type == "vibrance":
        params = (
            _adjustment_param_state("Vibrance", -100, 100, _adjustment_int_param(adjustment, "vibrance")),
            _adjustment_param_state("Saturation", -100, 100, _adjustment_int_param(adjustment, "saturation")),
            _adjustment_param_state("Lightness", -100, 100, _adjustment_int_param(adjustment, "lightness")),
        )
    elif adjustment_type == "selective_color":
        params = (
            _adjustment_param_state("Red / Cyan", -100, 100, _adjustment_int_param(adjustment, "red_cyan")),
            _adjustment_param_state("Green / Magenta", -100, 100, _adjustment_int_param(adjustment, "green_magenta")),
            _adjustment_param_state("Blue / Yellow", -100, 100, _adjustment_int_param(adjustment, "blue_yellow")),
        )
    elif adjustment_type == "brightness_contrast":
        params = (
            _adjustment_param_state("Brightness", -100, 100, _adjustment_int_param(adjustment, "brightness")),
            _adjustment_param_state("Contrast", -100, 100, _adjustment_int_param(adjustment, "contrast")),
            _adjustment_param_state("Saturation", -100, 100, _adjustment_int_param(adjustment, "saturation")),
        )
    elif adjustment_type == "exposure":
        params = (
            _adjustment_param_state("Exposure", -100, 100, _adjustment_int_param(adjustment, "exposure")),
            _adjustment_param_state("Offset", -100, 100, _adjustment_int_param(adjustment, "offset")),
            _adjustment_param_state("Gamma x100", 10, 300, _adjustment_int_param(adjustment, "gamma", 1.0, scale=100.0)),
        )
    elif adjustment_type == "color_balance":
        params = (
            _adjustment_param_state("Red / Cyan", -100, 100, _adjustment_int_param(adjustment, "red_cyan")),
            _adjustment_param_state("Green / Magenta", -100, 100, _adjustment_int_param(adjustment, "green_magenta")),
            _adjustment_param_state("Blue / Yellow", -100, 100, _adjustment_int_param(adjustment, "blue_yellow")),
        )
    elif adjustment_type == "curves":
        params = (
            _adjustment_param_state("Shadows", -100, 100, _adjustment_int_param(adjustment, "shadows")),
            _adjustment_param_state("Midtones", -100, 100, _adjustment_int_param(adjustment, "midtones")),
            _adjustment_param_state("Highlights", -100, 100, _adjustment_int_param(adjustment, "highlights")),
        )
    else:
        params = (
            _adjustment_param_state("Black", 0, 254, _adjustment_int_param(adjustment, "black")),
            _adjustment_param_state("Gamma x100", 10, 400, _adjustment_int_param(adjustment, "gamma", 1.0, scale=100.0)),
            _adjustment_param_state("White", 1, 255, _adjustment_int_param(adjustment, "white", 255.0)),
        )
    return TextureEditorAdjustmentControlState(
        has_adjustment=True,
        enabled_checked=bool(adjustment.enabled),
        opacity=int(adjustment.opacity),
        mode_visible=mode_visible,
        mode_value=mode_value,
        mode_enabled=mode_visible,
        params=params,
    )


def texture_editor_adjustment_parameters_from_controls(
    adjustment_type: str,
    *,
    param_a: int,
    param_b: int,
    param_c: int,
    mode_value: str = "neutrals",
) -> Dict[str, object]:
    adjustment_key = str(adjustment_type or "levels")
    if adjustment_key == "hue_saturation":
        return {"hue": float(param_a), "saturation": float(param_b), "lightness": float(param_c)}
    if adjustment_key == "vibrance":
        return {"vibrance": float(param_a), "saturation": float(param_b), "lightness": float(param_c)}
    if adjustment_key == "selective_color":
        return {
            "target_range": str(mode_value or "neutrals"),
            "red_cyan": float(param_a),
            "green_magenta": float(param_b),
            "blue_yellow": float(param_c),
        }
    if adjustment_key == "brightness_contrast":
        return {"brightness": float(param_a), "contrast": float(param_b), "saturation": float(param_c)}
    if adjustment_key == "exposure":
        return {"exposure": float(param_a), "offset": float(param_b), "gamma": float(param_c) / 100.0}
    if adjustment_key == "color_balance":
        return {"red_cyan": float(param_a), "green_magenta": float(param_b), "blue_yellow": float(param_c)}
    if adjustment_key == "curves":
        return {"shadows": float(param_a), "midtones": float(param_b), "highlights": float(param_c)}
    return {"black": float(param_a), "gamma": float(param_b) / 100.0, "white": float(param_c)}


def moved_texture_editor_adjustment_document(
    document: TextureEditorDocument,
    adjustment_id: str,
    *,
    direction: int,
) -> TextureEditorAdjustmentMoveState:
    layers = list(document.adjustment_layers)
    current_index = next((index for index, layer in enumerate(layers) if layer.layer_id == adjustment_id), -1)
    if current_index < 0:
        return TextureEditorAdjustmentMoveState(changed=False, document=document, target_index=-1)
    target_index = max(0, min(len(layers) - 1, current_index + int(direction)))
    if target_index == current_index:
        return TextureEditorAdjustmentMoveState(changed=False, document=document, target_index=target_index)
    layer = layers.pop(current_index)
    layers.insert(target_index, dataclasses.replace(layer, revision=int(layer.revision) + 1))
    return TextureEditorAdjustmentMoveState(
        changed=True,
        document=dataclasses.replace(
            document,
            adjustment_layers=tuple(layers),
            composite_revision=int(document.composite_revision) + 1,
        ),
        target_index=target_index,
    )


def solo_texture_editor_adjustment_document(
    document: TextureEditorDocument,
    adjustment_id: str,
) -> TextureEditorAdjustmentSoloState:
    if texture_editor_selected_adjustment(document.adjustment_layers, adjustment_id) is None:
        return TextureEditorAdjustmentSoloState(found=False, document=document)
    updated_layers: list[TextureEditorAdjustmentLayer] = []
    for adjustment in document.adjustment_layers:
        enabled = adjustment.layer_id == adjustment_id
        updated_layers.append(
            dataclasses.replace(
                adjustment,
                enabled=enabled,
                revision=int(adjustment.revision) + (1 if adjustment.enabled != enabled else 0),
            )
        )
    return TextureEditorAdjustmentSoloState(
        found=True,
        document=dataclasses.replace(
            document,
            adjustment_layers=tuple(updated_layers),
            composite_revision=int(document.composite_revision) + 1,
        ),
    )


def texture_editor_adjustment_properties_dirty(
    before_document: TextureEditorDocument,
    after_document: TextureEditorDocument,
) -> bool:
    return before_document != after_document


__all__ = [
    "TextureEditorAdjustmentDocumentState",
    "TextureEditorAdjustmentMoveState",
    "TextureEditorAdjustmentSoloState",
    "added_texture_editor_adjustment_state",
    "assigned_texture_editor_adjustment_mask_state",
    "cleared_texture_editor_adjustment_mask_state",
    "duplicated_texture_editor_adjustment_state",
    "moved_texture_editor_adjustment_document",
    "removed_texture_editor_adjustment_state",
    "reset_texture_editor_adjustment_state",
    "solo_texture_editor_adjustment_document",
    "updated_texture_editor_adjustment_properties_document",
    "default_texture_editor_adjustment_parameters",
    "texture_editor_adjustment_operation_state",
    "texture_editor_adjustment_properties_update_state",
    "texture_editor_adjustment_copy_name",
    "texture_editor_adjustment_control_state",
    "texture_editor_adjustment_display_name",
    "texture_editor_adjustment_history_label",
    "texture_editor_adjustment_list_label",
    "texture_editor_adjustment_parameters_from_controls",
    "texture_editor_adjustment_properties_dirty",
    "texture_editor_adjustment_refresh_selection_id",
    "texture_editor_adjustment_status_text",
    "texture_editor_selected_adjustment",
]
