from __future__ import annotations

"""Action enablement rules for the standalone Texture Editor UI."""

from dataclasses import dataclass
from typing import Optional

from cdmw.models import TextureEditorAdjustmentLayer, TextureEditorDocument


@dataclass(frozen=True, slots=True)
class TextureEditorImageActionState:
    crop_selection_enabled: bool
    image_transform_enabled: bool
    undo_enabled: bool
    redo_enabled: bool


@dataclass(frozen=True, slots=True)
class TextureEditorMainActionState:
    open_enabled: bool
    document_action_enabled: bool
    actions_menu_enabled: bool
    shortcuts_enabled: bool
    canvas_enabled: bool
    document_tabs_enabled: bool


@dataclass(frozen=True, slots=True)
class TextureEditorLayerActionState:
    property_controls_enabled: bool


@dataclass(frozen=True, slots=True)
class TextureEditorGuideActionState:
    controls_enabled: bool
    clear_enabled: bool


@dataclass(frozen=True, slots=True)
class TextureEditorToolActionState:
    controls_enabled: bool
    clear_clone_source_enabled: bool


@dataclass(frozen=True, slots=True)
class TextureEditorAdjustmentActionState:
    add_enabled: bool
    duplicate_enabled: bool
    remove_enabled: bool
    reset_enabled: bool
    up_enabled: bool
    down_enabled: bool
    solo_enabled: bool
    use_active_mask_enabled: bool
    clear_mask_enabled: bool
    list_enabled: bool


@dataclass(frozen=True, slots=True)
class TextureEditorAtlasActionState:
    controls_enabled: bool
    export_selection_enabled: bool
    export_grid_enabled: bool
    history_list_enabled: bool


@dataclass(frozen=True, slots=True)
class TextureEditorHistoryActionState:
    restore_enabled: bool


def texture_editor_main_action_state(
    document: Optional[TextureEditorDocument],
    *,
    busy: bool,
) -> TextureEditorMainActionState:
    has_document = document is not None
    available = has_document and not bool(busy)
    idle = not bool(busy)
    return TextureEditorMainActionState(
        open_enabled=idle,
        document_action_enabled=available,
        actions_menu_enabled=idle,
        shortcuts_enabled=idle,
        canvas_enabled=available,
        document_tabs_enabled=idle,
    )


def texture_editor_image_action_state(
    document: Optional[TextureEditorDocument],
    *,
    busy: bool,
    history_index: int,
    history_count: int,
) -> TextureEditorImageActionState:
    has_document = document is not None
    available = has_document and not bool(busy)
    has_selection = bool(document is not None and document.selection.mode != "none")
    has_no_floating = bool(document is not None and document.floating_selection is None)
    return TextureEditorImageActionState(
        crop_selection_enabled=available and has_selection and has_no_floating,
        image_transform_enabled=available and has_no_floating,
        undo_enabled=available and int(history_index) > 0,
        redo_enabled=available and int(history_index) < int(history_count) - 1,
    )


def texture_editor_layer_action_state(
    document: Optional[TextureEditorDocument],
    *,
    busy: bool,
) -> TextureEditorLayerActionState:
    return TextureEditorLayerActionState(property_controls_enabled=document is not None and not bool(busy))


def texture_editor_guide_action_state(
    document: Optional[TextureEditorDocument],
    *,
    busy: bool,
    vertical_guides_present: bool,
    horizontal_guides_present: bool,
    vertical_text: str,
    horizontal_text: str,
) -> TextureEditorGuideActionState:
    available = document is not None and not bool(busy)
    has_guide_state = bool(vertical_guides_present or horizontal_guides_present)
    has_guide_text = bool(str(vertical_text or "").strip() or str(horizontal_text or "").strip())
    return TextureEditorGuideActionState(
        controls_enabled=available,
        clear_enabled=available and (has_guide_state or has_guide_text),
    )


def texture_editor_tool_action_state(
    document: Optional[TextureEditorDocument],
    *,
    busy: bool,
    clone_source_point: Optional[tuple[int, int]],
) -> TextureEditorToolActionState:
    available = document is not None and not bool(busy)
    return TextureEditorToolActionState(
        controls_enabled=available,
        clear_clone_source_enabled=available and clone_source_point is not None,
    )


def texture_editor_adjustment_action_state(
    *,
    has_document: bool,
    busy: bool,
    has_adjustment_item: bool,
    current_row: int,
    adjustment_count: int,
    current_layer_id: Optional[str],
    selected_adjustment: Optional[TextureEditorAdjustmentLayer],
) -> TextureEditorAdjustmentActionState:
    available = bool(has_document) and not bool(busy)
    selected_available = available and bool(has_adjustment_item)
    row = int(current_row)
    count = int(adjustment_count)
    return TextureEditorAdjustmentActionState(
        add_enabled=available,
        duplicate_enabled=selected_available,
        remove_enabled=selected_available,
        reset_enabled=selected_available,
        up_enabled=selected_available and row > 0,
        down_enabled=selected_available and 0 <= row < count - 1,
        solo_enabled=selected_available,
        use_active_mask_enabled=selected_available and bool(current_layer_id),
        clear_mask_enabled=available and selected_adjustment is not None and bool(selected_adjustment.mask_layer_id),
        list_enabled=available,
    )


def texture_editor_atlas_action_state(
    document: Optional[TextureEditorDocument],
    *,
    busy: bool,
    has_selection_bounds: bool,
) -> TextureEditorAtlasActionState:
    available = document is not None and not bool(busy)
    return TextureEditorAtlasActionState(
        controls_enabled=available,
        export_selection_enabled=available and bool(has_selection_bounds),
        export_grid_enabled=available,
        history_list_enabled=available,
    )


def texture_editor_history_action_state(
    document: Optional[TextureEditorDocument],
    *,
    busy: bool,
    selected_row: int,
    history_index: int,
    history_count: int,
) -> TextureEditorHistoryActionState:
    available = document is not None and not bool(busy)
    row = int(selected_row)
    return TextureEditorHistoryActionState(
        restore_enabled=available and 0 <= row < int(history_count) and row != int(history_index),
    )
