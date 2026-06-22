from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel

from cdmw.models import (
    TextureEditorAdjustmentLayer,
    TextureEditorDocument,
    TextureEditorFloatingSelection,
    TextureEditorLayer,
    TextureEditorSelection,
    TextureEditorSourceBinding,
    TextureEditorToolSettings,
)
from cdmw.ui.texture_workflow.editor_adjustments import (
    added_texture_editor_adjustment_state,
    assigned_texture_editor_adjustment_mask_state,
    cleared_texture_editor_adjustment_mask_state,
    default_texture_editor_adjustment_parameters,
    duplicated_texture_editor_adjustment_state,
    moved_texture_editor_adjustment_document,
    removed_texture_editor_adjustment_state,
    reset_texture_editor_adjustment_state,
    solo_texture_editor_adjustment_document,
    texture_editor_adjustment_copy_name,
    texture_editor_adjustment_control_state,
    texture_editor_adjustment_display_name,
    texture_editor_adjustment_history_label,
    texture_editor_adjustment_list_label,
    texture_editor_adjustment_operation_state,
    texture_editor_adjustment_parameters_from_controls,
    texture_editor_adjustment_properties_update_state,
    texture_editor_adjustment_properties_dirty,
    texture_editor_adjustment_refresh_selection_id,
    texture_editor_adjustment_status_text,
    texture_editor_selected_adjustment,
    updated_texture_editor_adjustment_properties_document,
)
from cdmw.ui.texture_workflow.editor_action_state import (
    texture_editor_adjustment_action_state,
    texture_editor_atlas_action_state,
    texture_editor_guide_action_state,
    texture_editor_history_action_state,
    texture_editor_image_action_state,
    texture_editor_layer_action_state,
    texture_editor_main_action_state,
    texture_editor_tool_action_state,
)
from cdmw.ui.texture_workflow.editor_brush_presets import (
    BUILTIN_TEXTURE_EDITOR_BRUSH_PRESET_ORDER,
    merged_texture_editor_brush_presets,
    normalized_texture_editor_custom_brush_preset_key,
    normalize_texture_editor_custom_brush_presets,
    serialize_texture_editor_custom_brush_presets,
    texture_editor_brush_preset_combo_state,
    texture_editor_brush_preset_control_state,
    texture_editor_brush_preset_definitions,
    texture_editor_brush_preset_label,
    texture_editor_brush_preset_values,
    texture_editor_brush_preset_missing_name_status_text,
    texture_editor_brush_preset_saved_status_text,
    texture_editor_cleared_custom_brush_tip_state,
    texture_editor_custom_brush_cleared_status_text,
    texture_editor_custom_brush_loaded_status_text,
    texture_editor_custom_brush_preset_from_controls,
    texture_editor_loaded_custom_brush_tip_state,
    texture_editor_saved_custom_brush_preset_state,
    texture_editor_should_mark_brush_preset_custom,
)
from cdmw.ui.texture_workflow.editor_canvas import TextureEditorCanvas
from cdmw.ui.texture_workflow.editor_clipboard_state import (
    texture_editor_centered_paste_origin,
    texture_editor_clipboard_floating_paste_state,
    texture_editor_copy_selection_to_layer_history_label,
    texture_editor_copy_selection_to_layer_missing_status_text,
    texture_editor_copy_selection_to_layer_status_text,
    texture_editor_cut_selection_missing_status_text,
    texture_editor_cut_selection_status_text,
    texture_editor_layer_clipboard_payload,
    texture_editor_layer_copy_clipboard_state,
    texture_editor_layer_copy_status_text,
    texture_editor_layer_floating_label,
    texture_editor_layer_floating_paste_state,
    texture_editor_selection_clipboard_payload,
    texture_editor_selection_copy_status_text,
    texture_editor_selection_floating_label,
    texture_editor_selection_floating_paste_state,
    texture_editor_selection_to_layer_state,
)
from cdmw.ui.texture_workflow.editor_dialogs import ShortcutEditorDialog
from cdmw.ui.texture_workflow.editor_document_state import (
    texture_editor_crop_to_selection_gate,
    texture_editor_crop_to_selection_history_label,
    texture_editor_cropped_to_selection_state,
    texture_editor_document_pixels_change_gate,
    texture_editor_document_pixels_changed,
    texture_editor_document_transform_applied_status,
    texture_editor_flipped_document_state,
    texture_editor_flip_document_history_label,
    texture_editor_resized_canvas_state,
    texture_editor_resized_image_state,
    texture_editor_rotated_document_state,
    texture_editor_rotate_document_history_label,
    texture_editor_trimmed_transparent_state,
    texture_editor_trim_transparent_history_label,
)
from cdmw.ui.texture_workflow.editor_floating_state import (
    clear_texture_editor_selection_from_layer_pixels,
    compose_texture_editor_floating_selection,
    compose_texture_editor_floating_selection_region,
    current_texture_editor_floating_canvas_bounds,
    estimated_texture_editor_brush_dirty_bounds,
    shift_texture_editor_pixels,
    texture_editor_cut_selection_to_floating_state,
    texture_editor_cleared_floating_selection_state,
    texture_editor_floating_cancel_history_label,
    texture_editor_floating_cancel_status_text,
    texture_editor_floating_canvas_transform_state,
    texture_editor_floating_committed_layer_state,
    texture_editor_floating_commit_state,
    texture_editor_floating_layer_copy_state,
    texture_editor_floating_move_state,
    texture_editor_floating_selection_updated_status_text,
    texture_editor_float_layer_copy_empty_status_text,
    texture_editor_float_layer_copy_history_label,
    texture_editor_float_layer_copy_status_text,
    texture_editor_nontransparent_pixel_bounds,
    texture_editor_layer_canvas_bounds,
    texture_editor_set_floating_selection_state,
    texture_editor_snapshot_floating_pixels,
    transformed_texture_editor_floating_pixels,
)
from cdmw.ui.texture_workflow.editor_export_state import (
    texture_editor_default_workspace_root,
    texture_editor_document_with_last_flattened_output,
    texture_editor_existing_project_status_text,
    texture_editor_flattened_png_default_path,
    texture_editor_flattened_png_status_text,
    texture_editor_flattened_png_task_label,
    texture_editor_grid_slices_status_text,
    texture_editor_grid_slices_task_label,
    texture_editor_handoff_delivery_state,
    texture_editor_handoff_export_suffix,
    texture_editor_handoff_source_binding,
    texture_editor_handoff_status_text,
    texture_editor_open_project_history_label,
    texture_editor_open_project_status_text,
    texture_editor_open_project_task_label,
    texture_editor_project_default_path,
    texture_editor_save_project_status_text,
    texture_editor_save_project_task_label,
    texture_editor_selection_region_default_path,
    texture_editor_selection_region_missing_status_text,
    texture_editor_selection_region_status_text,
    texture_editor_selection_region_task_label,
    texture_editor_workspace_exports_root,
    texture_editor_workspace_export_task_label,
    texture_editor_workspace_png_path,
    texture_editor_workspace_png_stem,
)
from cdmw.ui.texture_workflow.editor_export_tasks import (
    copy_texture_editor_layer_pixels,
    create_texture_editor_source_document_task,
    export_texture_editor_flattened_png_task,
    export_texture_editor_grid_slices_task,
    export_texture_editor_region_png_task,
    export_texture_editor_workspace_png_task,
    save_texture_editor_project_task,
)
from cdmw.ui.texture_workflow.editor_guides import (
    format_texture_editor_guides_text,
    parse_texture_editor_guides_text,
    texture_editor_guides_cleared_status_text,
)
from cdmw.ui.texture_workflow.editor_history_state import (
    build_texture_editor_checkpoint_record,
    build_texture_editor_delta_history_record,
    decode_texture_editor_history_layer_state,
    decode_texture_editor_rgba_blob,
    encode_texture_editor_history_layer_state,
    encode_texture_editor_rgba_blob,
    texture_editor_applied_history_document_state,
    texture_editor_history_auxiliary_layer_ids,
    texture_editor_history_cleared_state,
    texture_editor_history_cleared_status_text,
    texture_editor_history_layer_canvas_offset,
    texture_editor_history_list_item_text,
    texture_editor_history_record_application_state,
    texture_editor_history_replay_plan,
    texture_editor_history_restore_state,
    texture_editor_history_restored_status_text,
    texture_editor_history_selected_row_state,
    texture_editor_history_selection_status_text,
    texture_editor_history_should_checkpoint,
    texture_editor_history_tracked_layer_ids,
    texture_editor_history_with_appended_record,
)
from cdmw.ui.texture_workflow.editor_channel_state import (
    texture_editor_channel_alpha_lock_blocked,
    texture_editor_channel_alpha_lock_message,
    texture_editor_channel_clipboard_state,
    texture_editor_channel_controls_state,
    texture_editor_channel_copy_operation_state,
    texture_editor_channel_extract_operation_state,
    texture_editor_channel_lock_update_state,
    texture_editor_channel_lock_status_text,
    texture_editor_channel_luma_pack_operation_state,
    texture_editor_channel_operation_history_label,
    texture_editor_channel_operation_status_text,
    texture_editor_channel_paste_operation_state,
    texture_editor_channel_selection_required_status_text,
    texture_editor_channel_selection_load_operation_state,
    texture_editor_channel_selection_write_operation_state,
    texture_editor_channel_swap_operation_state,
    texture_editor_channel_to_selection_state,
    texture_editor_extracted_channel_layer_state,
    texture_editor_luma_to_channel_state,
    texture_editor_normalized_channel_key,
    texture_editor_pasted_channel_state,
    texture_editor_same_channel_swap_status,
    texture_editor_selection_to_channel_state,
    texture_editor_swapped_channels_state,
)
from cdmw.ui.texture_workflow.editor_images import (
    _create_tool_icon,
    _rgba_array_to_qimage,
    texture_editor_layer_thumbnail_preview_pixels,
    texture_editor_quick_mask_overlay_image,
)
from cdmw.ui.texture_workflow.editor_layer_state import (
    added_texture_editor_layer_mask_state,
    deleted_texture_editor_layer_mask_state,
    inverted_texture_editor_layer_mask_state,
    toggled_texture_editor_layer_mask_state,
    texture_editor_active_layer_document,
    texture_editor_added_layer_state,
    texture_editor_current_layer_id,
    texture_editor_drag_reorder_state,
    texture_editor_drag_reordered_document_state,
    texture_editor_duplicated_layer_state,
    texture_editor_edit_target_layer_id,
    texture_editor_edit_mask_target_state,
    texture_editor_merged_layer_down_state,
    texture_editor_moved_layer_state,
    texture_editor_removed_layer_state,
    texture_editor_reordered_layer_state,
    texture_editor_layer_control_state,
    texture_editor_layer_by_id,
    texture_editor_layer_action_operation_state,
    texture_editor_current_layer_mask_to_selection_state,
    texture_editor_layer_history_label,
    texture_editor_layer_list_label,
    texture_editor_layer_lock_operation_state,
    texture_editor_layer_mask_history_label,
    texture_editor_layer_mask_invert_before_pixels,
    texture_editor_layer_mask_target_state,
    texture_editor_layers_reordered_status_text,
    texture_editor_layer_lock_change,
    texture_editor_layer_lock_document_state,
    texture_editor_layer_mask_to_selection_state,
    texture_editor_layer_pixel_target_state,
    texture_editor_layer_property_change,
    texture_editor_layer_properties_document_state,
    texture_editor_layer_properties_operation_state,
    texture_editor_layer_refresh_selection_id,
    texture_editor_layer_rename_state,
    texture_editor_layer_rename_operation_state,
    texture_editor_renamed_layer_document_state,
    texture_editor_layer_thumbnail_cache_keys,
    texture_editor_selection_to_current_layer_mask_state,
    texture_editor_selection_to_layer_mask_state,
)
from cdmw.ui.texture_workflow.editor_session import (
    _TextureEditorSession,
    create_texture_editor_session,
    texture_editor_active_session_label_update_state,
    texture_editor_active_session_original_flattened,
    texture_editor_document_composite_revision,
    texture_editor_document_key,
    texture_editor_existing_project_session_index,
    texture_editor_existing_source_session_index,
    texture_editor_open_document_ids,
    texture_editor_session_close_state,
    texture_editor_session_tab_state,
)
from cdmw.ui.texture_workflow.editor_selection_state import (
    current_texture_editor_selection_bounds,
    simplified_texture_editor_lasso_points,
    texture_editor_active_layer_selection_payload_state,
    texture_editor_canvas_selection_payload_state,
    texture_editor_canvas_selection_source_pixels,
    texture_editor_canvas_selection_update_state,
    texture_editor_clear_selection_update_state,
    texture_editor_document_with_cleared_selection_only,
    texture_editor_prepared_lasso_selection_points,
    texture_editor_quick_mask_update_state,
    texture_editor_resized_selection_update_state,
    texture_editor_select_all_update_state,
    texture_editor_selection_controls_state,
    texture_editor_selection_feather_preview_document,
    texture_editor_selection_feather_update_state,
    texture_editor_selection_invert_update_state,
    texture_editor_selection_operation_state,
    texture_editor_selection_refine_labels,
)
from cdmw.ui.texture_workflow.editor_shortcuts import (
    default_texture_editor_shortcuts,
    load_texture_editor_shortcuts,
    texture_editor_shortcut_labels,
    texture_editor_shortcuts_updated_status_text,
)
from cdmw.ui.texture_workflow.editor_source_binding import (
    build_texture_editor_source_binding,
    configured_texture_editor_root_path,
    texture_editor_browse_archive_request_path,
    texture_editor_combined_warning,
    texture_editor_compare_request_state,
    texture_editor_existing_source_status_text,
    texture_editor_metadata_display_state,
    texture_editor_metadata_html,
    texture_editor_open_source_history_label,
    texture_editor_open_source_status_text,
    texture_editor_open_source_task_label,
)
from cdmw.ui.texture_workflow.editor_status_state import (
    texture_editor_busy_status_text,
    texture_editor_canvas_status_state,
    texture_editor_hover_pixel_text,
    texture_editor_sampled_color_status,
    texture_editor_selection_status_text,
    texture_editor_task_failed_status_text,
    texture_editor_tool_status_text,
    texture_editor_zoom_labels,
)
from cdmw.ui.texture_workflow.editor_tool_state import (
    normalized_texture_editor_clone_source_point,
    nudged_texture_editor_brush_hardness,
    nudged_texture_editor_brush_size,
    texture_editor_active_tool_state,
    texture_editor_brush_visual_state,
    texture_editor_clone_source_cleared_state,
    texture_editor_clone_source_cleared_status_text,
    texture_editor_clone_source_picked_state,
    texture_editor_clone_source_picked_status_text,
    texture_editor_clone_source_required,
    texture_editor_clone_source_required_status,
    texture_editor_empty_active_layer_filter_blocked,
    texture_editor_empty_active_layer_filter_status,
    texture_editor_layer_has_visible_pixels,
    texture_editor_layer_stroke_state,
    texture_editor_move_delta,
    texture_editor_patch_selection_required,
    texture_editor_patch_selection_required_status,
    texture_editor_quick_mask_stroke_state,
    texture_editor_quick_mask_tool_allowed,
    texture_editor_quick_mask_tool_status,
    texture_editor_recolor_pixels_with_channel_locks,
    texture_editor_recolor_control_state,
    texture_editor_recolor_layer_history_label,
    texture_editor_recolor_layer_state,
    texture_editor_recolor_settings_loaded_status_text,
    texture_editor_stroke_source_snapshot,
    texture_editor_stroke_source_snapshot_mode,
    texture_editor_stroke_payload_state,
    TextureEditorToolControlSnapshot,
    texture_editor_tool_settings_for_stroke,
    texture_editor_tool_settings_from_controls,
    texture_editor_tool_setting_visibility,
)
from cdmw.ui.texture_workflow.editor_transform_state import (
    texture_editor_applied_floating_transform_state,
    texture_editor_canvas_floating_transform_state,
    texture_editor_flipped_floating_transform_state,
    texture_editor_floating_transform_dirty_bounds,
    texture_editor_rotated_floating_transform_state,
    texture_editor_transform_controls_state,
)
from cdmw.ui.texture_workflow.editor_ui_constraints import (
    looks_like_texture_editor_ui_constraint_candidate,
    texture_editor_ui_constraint_cache_key,
    texture_editor_ui_constraint_lookup_start_state,
    texture_editor_ui_constraint_ready_state,
    texture_editor_ui_constraint_target_path,
    texture_editor_ui_constraint_warning_lookup_state,
    texture_editor_ui_constraint_warning_state,
)
from cdmw.ui.texture_workflow.editor_view_state import (
    clamped_texture_editor_composite_dirty_bounds,
    merged_texture_editor_composite_dirty_bounds,
    texture_editor_center_scroll_values,
    texture_editor_composite_render_state,
    texture_editor_empty_ruler_state,
    texture_editor_guides_from_view_state,
    texture_editor_grid_control_state,
    texture_editor_grid_color_hex,
    texture_editor_grid_color_button_state,
    texture_editor_navigation_overlay_state,
    texture_editor_navigator_viewport_rect,
    texture_editor_resolved_view_state,
    texture_editor_ruler_states,
    texture_editor_view_mode_key,
    texture_editor_view_controls_state,
    texture_editor_view_state_payload,
    texture_editor_wheel_zoom_multiplier,
    texture_editor_zoom_factor_for_step,
    texture_editor_zoom_scroll_targets,
)
from cdmw.ui.texture_workflow.editor_widgets import CollapsibleSection, TextureEditorNavigator, TextureEditorRuler


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_texture_editor_image_helper_copies_rgba_array() -> None:
    _app()
    pixels = np.zeros((2, 2, 4), dtype=np.uint8)
    pixels[0, 0] = [10, 20, 30, 40]
    quick_mask_document = TextureEditorDocument(
        "doc",
        2,
        2,
        selection=TextureEditorSelection(mode="rect", rect=(0, 0, 1, 1)),
        quick_mask_enabled=True,
    )

    image = _rgba_array_to_qimage(pixels)
    quick_mask_overlay = texture_editor_quick_mask_overlay_image(quick_mask_document)
    pixels[0, 0] = [200, 200, 200, 200]

    assert image.width() == 2
    assert image.height() == 2
    assert image.pixelColor(0, 0).getRgb() == (10, 20, 30, 40)
    assert quick_mask_overlay is not None
    assert quick_mask_overlay.width() == 2
    assert quick_mask_overlay.height() == 2
    assert quick_mask_overlay.pixelColor(0, 0).getRgb() == (235, 70, 90, 82)
    assert quick_mask_overlay.pixelColor(1, 1).alpha() == 0
    assert texture_editor_quick_mask_overlay_image(dataclasses.replace(quick_mask_document, quick_mask_enabled=False)) is None


def test_texture_editor_layer_thumbnail_preview_pixels_crops_visible_alpha() -> None:
    pixels = np.zeros((4, 5, 4), dtype=np.uint8)
    pixels[1:3, 2:5, 3] = 255
    pixels[1, 2] = [10, 20, 30, 255]
    cropped = texture_editor_layer_thumbnail_preview_pixels(pixels)
    transparent = texture_editor_layer_thumbnail_preview_pixels(np.zeros((2, 3, 4), dtype=np.uint8))

    assert cropped is not None
    assert cropped.shape == (2, 3, 4)
    assert cropped[0, 0].tolist() == [10, 20, 30, 255]
    assert transparent is not None
    assert transparent.shape == (2, 3, 4)
    assert texture_editor_layer_thumbnail_preview_pixels(None) is None


def test_texture_editor_tool_icon_is_created() -> None:
    _app()

    icon = _create_tool_icon("paint")

    assert not icon.isNull()


def test_texture_editor_image_action_state() -> None:
    selected = TextureEditorDocument(
        "doc",
        8,
        8,
        selection=TextureEditorSelection(mode="rect", rect=(1, 1, 3, 3)),
    )
    floating = TextureEditorDocument(
        "floating",
        8,
        8,
        selection=TextureEditorSelection(mode="rect", rect=(1, 1, 3, 3)),
        floating_selection=TextureEditorFloatingSelection(),
    )

    enabled = texture_editor_image_action_state(selected, busy=False, history_index=1, history_count=3)
    busy = texture_editor_image_action_state(selected, busy=True, history_index=1, history_count=3)
    blocked_by_floating = texture_editor_image_action_state(floating, busy=False, history_index=1, history_count=3)
    no_doc = texture_editor_image_action_state(None, busy=False, history_index=1, history_count=3)

    assert enabled.crop_selection_enabled is True
    assert enabled.image_transform_enabled is True
    assert enabled.undo_enabled is True
    assert enabled.redo_enabled is True
    assert busy.crop_selection_enabled is False
    assert blocked_by_floating.crop_selection_enabled is False
    assert blocked_by_floating.image_transform_enabled is False
    assert no_doc.undo_enabled is False


def test_texture_editor_main_layer_guide_tool_and_atlas_action_state() -> None:
    document = TextureEditorDocument(
        "doc",
        8,
        8,
        selection=TextureEditorSelection(mode="rect", rect=(1, 1, 3, 3)),
    )

    main = texture_editor_main_action_state(document, busy=False)
    main_busy = texture_editor_main_action_state(document, busy=True)
    layer = texture_editor_layer_action_state(document, busy=False)
    guide = texture_editor_guide_action_state(
        document,
        busy=False,
        vertical_guides_present=False,
        horizontal_guides_present=True,
        vertical_text="",
        horizontal_text="",
    )
    guide_text = texture_editor_guide_action_state(
        document,
        busy=False,
        vertical_guides_present=False,
        horizontal_guides_present=False,
        vertical_text="  12 ",
        horizontal_text="",
    )
    tool = texture_editor_tool_action_state(document, busy=False, clone_source_point=(1, 2))
    atlas = texture_editor_atlas_action_state(document, busy=False, has_selection_bounds=True)
    no_doc_atlas = texture_editor_atlas_action_state(None, busy=False, has_selection_bounds=True)

    assert main.open_enabled is True
    assert main.document_action_enabled is True
    assert main.document_tabs_enabled is True
    assert main_busy.open_enabled is False
    assert main_busy.document_action_enabled is False
    assert layer.property_controls_enabled is True
    assert guide.controls_enabled is True
    assert guide.clear_enabled is True
    assert guide_text.clear_enabled is True
    assert tool.controls_enabled is True
    assert tool.clear_clone_source_enabled is True
    assert atlas.export_selection_enabled is True
    assert atlas.export_grid_enabled is True
    assert no_doc_atlas.export_selection_enabled is False


def test_texture_editor_document_state_helpers_gate_transform_actions() -> None:
    selected = TextureEditorDocument(
        "Doc",
        16,
        16,
        selection=TextureEditorSelection(mode="rect", rect=(1, 2, 3, 4)),
    )
    empty_selection = TextureEditorDocument("Doc", 16, 16)
    floating = dataclasses.replace(selected, floating_selection=TextureEditorFloatingSelection())
    pixels = {"base": np.zeros((1, 1, 4), dtype=np.uint8)}
    updated_pixels = {"base": pixels["base"].copy()}
    transform_document = TextureEditorDocument(
        "Doc",
        4,
        3,
        active_layer_id="layer",
        layers=(TextureEditorLayer("layer", "Paint", ""),),
        selection=TextureEditorSelection(mode="rect", rect=(1, 1, 2, 1)),
    )
    transform_pixels = {"layer": np.zeros((3, 4, 4), dtype=np.uint8)}
    transform_pixels["layer"][1, 1] = [10, 20, 30, 255]
    resized_image = texture_editor_resized_image_state(transform_document, transform_pixels, 8, 6)
    unchanged_resize = texture_editor_resized_image_state(transform_document, transform_pixels, 4, 3)
    resized_canvas = texture_editor_resized_canvas_state(transform_document, transform_pixels, 6, 5, anchor="center")
    cropped = texture_editor_cropped_to_selection_state(transform_document, transform_pixels)
    trimmed = texture_editor_trimmed_transparent_state(transform_document, transform_pixels)
    flipped = texture_editor_flipped_document_state(transform_document, transform_pixels, horizontal=True, vertical=False)
    no_flip = texture_editor_flipped_document_state(transform_document, transform_pixels, horizontal=False, vertical=False)
    rotated = texture_editor_rotated_document_state(transform_document, transform_pixels, clockwise=True)

    assert texture_editor_document_pixels_change_gate(None).can_apply is False
    assert texture_editor_document_pixels_change_gate(selected).can_apply is True
    floating_gate = texture_editor_document_pixels_change_gate(floating)
    crop_gate = texture_editor_crop_to_selection_gate(empty_selection)
    assert floating_gate.can_apply is False
    assert floating_gate.error is True
    assert "floating selection" in floating_gate.status_text
    assert texture_editor_crop_to_selection_gate(selected).can_apply is True
    assert crop_gate.error is True
    assert "Crop To Selection" in crop_gate.status_text
    assert texture_editor_document_pixels_changed(
        current_document=selected,
        current_layer_pixels=pixels,
        updated_document=selected,
        updated_layer_pixels=pixels,
    ) is False
    assert texture_editor_document_pixels_changed(
        current_document=selected,
        current_layer_pixels=pixels,
        updated_document=dataclasses.replace(selected, width=8),
        updated_layer_pixels=updated_pixels,
    ) is True
    assert texture_editor_crop_to_selection_history_label() == "Crop To Selection"
    assert texture_editor_trim_transparent_history_label() == "Trim Transparent"
    assert texture_editor_flip_document_history_label(horizontal=True, vertical=False) == "Flip Horizontal"
    assert texture_editor_flip_document_history_label(horizontal=False, vertical=True) == "Flip Vertical"
    assert texture_editor_flip_document_history_label(horizontal=False, vertical=False) == ""
    assert texture_editor_rotate_document_history_label(clockwise=True) == "Rotate 90 CW"
    assert texture_editor_rotate_document_history_label(clockwise=False) == "Rotate 90 CCW"
    assert texture_editor_document_transform_applied_status("Trim Transparent") == "Trim Transparent applied."
    assert resized_image is not None
    assert resized_image.document.width == 8
    assert resized_image.document.height == 6
    assert resized_image.before_layer_pixels["layer"][1, 1].tolist() == [10, 20, 30, 255]
    assert resized_image.history_label == "Image Size"
    assert resized_image.status_text == "Image Size applied."
    assert resized_image.kind == "document_transform"
    assert resized_image.tracked_layer_ids == ()
    assert resized_image.force_checkpoint is True
    assert unchanged_resize is None
    assert resized_canvas is not None
    assert resized_canvas.document.width == 6
    assert resized_canvas.document.height == 5
    assert resized_canvas.document.layers[0].offset_x == 1
    assert resized_canvas.document.layers[0].offset_y == 1
    assert cropped is not None
    assert cropped.document.width == 2
    assert cropped.document.height == 1
    assert cropped.history_label == "Crop To Selection"
    assert trimmed is not None
    assert trimmed.document.width == 1
    assert trimmed.document.height == 1
    assert trimmed.history_label == "Trim Transparent"
    assert flipped is not None
    assert flipped.history_label == "Flip Horizontal"
    assert flipped.layer_pixels["layer"][1, 2, 3] == 255
    assert no_flip is None
    assert rotated is not None
    assert rotated.document.width == 3
    assert rotated.document.height == 4
    assert rotated.history_label == "Rotate 90 CW"


def test_texture_editor_history_action_state() -> None:
    document = TextureEditorDocument("doc", 8, 8)

    restore = texture_editor_history_action_state(
        document,
        busy=False,
        selected_row=0,
        history_index=1,
        history_count=3,
    )
    current = texture_editor_history_action_state(
        document,
        busy=False,
        selected_row=1,
        history_index=1,
        history_count=3,
    )
    missing = texture_editor_history_action_state(
        document,
        busy=False,
        selected_row=9,
        history_index=1,
        history_count=3,
    )
    busy = texture_editor_history_action_state(
        document,
        busy=True,
        selected_row=0,
        history_index=1,
        history_count=3,
    )

    assert restore.restore_enabled is True
    assert current.restore_enabled is False
    assert missing.restore_enabled is False
    assert busy.restore_enabled is False


def test_texture_editor_adjustment_action_state() -> None:
    adjustment = TextureEditorAdjustmentLayer("adj", "Levels", "levels", mask_layer_id="mask")

    state = texture_editor_adjustment_action_state(
        has_document=True,
        busy=False,
        has_adjustment_item=True,
        current_row=1,
        adjustment_count=3,
        current_layer_id="layer",
        selected_adjustment=adjustment,
    )
    first = texture_editor_adjustment_action_state(
        has_document=True,
        busy=False,
        has_adjustment_item=True,
        current_row=0,
        adjustment_count=3,
        current_layer_id="",
        selected_adjustment=TextureEditorAdjustmentLayer("adj", "Levels", "levels"),
    )
    busy = texture_editor_adjustment_action_state(
        has_document=True,
        busy=True,
        has_adjustment_item=True,
        current_row=1,
        adjustment_count=3,
        current_layer_id="layer",
        selected_adjustment=adjustment,
    )

    assert state.add_enabled is True
    assert state.duplicate_enabled is True
    assert state.up_enabled is True
    assert state.down_enabled is True
    assert state.use_active_mask_enabled is True
    assert state.clear_mask_enabled is True
    assert first.up_enabled is False
    assert first.clear_mask_enabled is False
    assert busy.add_enabled is False
    assert busy.list_enabled is False


def test_texture_editor_adjustment_control_state() -> None:
    none_state = texture_editor_adjustment_control_state(None)
    selective = texture_editor_adjustment_control_state(
        TextureEditorAdjustmentLayer(
            "adj",
            "Selective",
            "selective_color",
            enabled=False,
            opacity=64,
            parameters={
                "target_range": "reds",
                "red_cyan": 10.2,
                "green_magenta": -4.6,
                "blue_yellow": 3.0,
            },
        )
    )
    exposure = texture_editor_adjustment_control_state(
        TextureEditorAdjustmentLayer(
            "adj",
            "Exposure",
            "exposure",
            parameters={"exposure": 1.2, "offset": -2.6, "gamma": 1.25},
        )
    )

    assert none_state.has_adjustment is False
    assert none_state.mode_visible is False
    assert none_state.opacity == 100
    assert none_state.params == ()
    assert selective.has_adjustment is True
    assert selective.enabled_checked is False
    assert selective.opacity == 64
    assert selective.mode_visible is True
    assert selective.mode_enabled is True
    assert selective.mode_value == "reds"
    assert selective.params[0].label == "Red / Cyan"
    assert selective.params[0].value == 10
    assert selective.params[1].value == -5
    assert exposure.mode_visible is False
    assert exposure.params[2].label == "Gamma x100"
    assert exposure.params[2].minimum == 10
    assert exposure.params[2].maximum == 300
    assert exposure.params[2].value == 125


def test_texture_editor_adjustment_parameters_from_controls() -> None:
    assert texture_editor_adjustment_parameters_from_controls(
        "selective_color",
        param_a=1,
        param_b=-2,
        param_c=3,
        mode_value="blues",
    ) == {
        "target_range": "blues",
        "red_cyan": 1.0,
        "green_magenta": -2.0,
        "blue_yellow": 3.0,
    }
    assert texture_editor_adjustment_parameters_from_controls(
        "exposure",
        param_a=4,
        param_b=-5,
        param_c=125,
    ) == {"exposure": 4.0, "offset": -5.0, "gamma": 1.25}
    assert texture_editor_adjustment_parameters_from_controls(
        "levels",
        param_a=2,
        param_b=150,
        param_c=250,
    ) == {"black": 2.0, "gamma": 1.5, "white": 250.0}


def test_texture_editor_adjustment_state_helpers_update_documents() -> None:
    base = TextureEditorDocument(
        "doc",
        8,
        8,
        adjustment_layers=(
            TextureEditorAdjustmentLayer("a", "Levels", "levels", enabled=True, revision=1),
            TextureEditorAdjustmentLayer("b", "Exposure", "exposure", enabled=False, revision=2),
            TextureEditorAdjustmentLayer("c", "Curves", "curves", enabled=False, revision=3),
        ),
        composite_revision=10,
    )

    moved = moved_texture_editor_adjustment_document(base, "b", direction=-1)
    unchanged_move = moved_texture_editor_adjustment_document(base, "a", direction=-1)
    missing_move = moved_texture_editor_adjustment_document(base, "missing", direction=1)
    soloed = solo_texture_editor_adjustment_document(base, "b")
    missing_solo = solo_texture_editor_adjustment_document(base, "missing")
    added = added_texture_editor_adjustment_state(base, "exposure")
    removed = removed_texture_editor_adjustment_state(base, "b")
    missing_remove = removed_texture_editor_adjustment_state(base, "missing")
    duplicated = duplicated_texture_editor_adjustment_state(base, base.adjustment_layers[1])
    assigned_mask = assigned_texture_editor_adjustment_mask_state(base, "b", "paint")
    missing_assign = assigned_texture_editor_adjustment_mask_state(base, "", "paint")
    cleared_mask = cleared_texture_editor_adjustment_mask_state(
        dataclasses.replace(
            base,
            adjustment_layers=(dataclasses.replace(base.adjustment_layers[1], mask_layer_id="paint"),),
        ),
        dataclasses.replace(base.adjustment_layers[1], mask_layer_id="paint"),
    )
    unchanged_clear = cleared_texture_editor_adjustment_mask_state(base, base.adjustment_layers[1])
    reset = reset_texture_editor_adjustment_state(base, base.adjustment_layers[1])
    updated_properties = updated_texture_editor_adjustment_properties_document(
        base,
        base.adjustment_layers[1],
        enabled=True,
        opacity=42,
        parameters={"exposure": 5.0},
    )
    add_operation = texture_editor_adjustment_operation_state(base, action="add", adjustment_type="exposure")
    remove_operation = texture_editor_adjustment_operation_state(base, action="remove", adjustment_id="b")
    duplicate_operation = texture_editor_adjustment_operation_state(base, action="duplicate", adjustment_id="b")
    move_operation = texture_editor_adjustment_operation_state(base, action="move", adjustment_id="b", direction=-1)
    unchanged_move_operation = texture_editor_adjustment_operation_state(base, action="move", adjustment_id="a", direction=-1)
    solo_operation = texture_editor_adjustment_operation_state(base, action="solo", adjustment_id="b")
    assign_mask_operation = texture_editor_adjustment_operation_state(
        base,
        action="assign_mask",
        adjustment_id="b",
        active_layer_id="paint",
    )
    clear_mask_operation = texture_editor_adjustment_operation_state(
        dataclasses.replace(
            base,
            adjustment_layers=(dataclasses.replace(base.adjustment_layers[1], mask_layer_id="paint"),),
        ),
        action="clear_mask",
        adjustment_id="b",
    )
    reset_operation = texture_editor_adjustment_operation_state(base, action="reset", adjustment_id="b")
    missing_operation = texture_editor_adjustment_operation_state(base, action="duplicate", adjustment_id="missing")
    property_operation = texture_editor_adjustment_properties_update_state(
        base,
        adjustment_id="b",
        enabled=True,
        opacity=42,
        parameters={"exposure": 5.0},
    )
    missing_property_operation = texture_editor_adjustment_properties_update_state(
        base,
        adjustment_id="missing",
        enabled=True,
        opacity=42,
        parameters={"exposure": 5.0},
    )

    assert texture_editor_adjustment_display_name("hue_saturation") == "Hue / Saturation"
    assert texture_editor_adjustment_display_name("unknown") == "Adjustment"
    assert texture_editor_adjustment_copy_name("  Paint  ") == "Paint Copy"
    assert texture_editor_adjustment_copy_name("") == "Adjustment Copy"
    assert texture_editor_adjustment_history_label("assign_mask") == "Assign Adjustment Mask"
    assert texture_editor_adjustment_history_label("update") == "Adjustment Update"
    assert texture_editor_adjustment_history_label("missing") == "Adjustment Update"
    assert texture_editor_adjustment_status_text("solo").startswith("Soloed the selected adjustment.")
    assert texture_editor_adjustment_status_text("assign_mask").startswith("Assigned the active raster layer")
    assert texture_editor_adjustment_status_text("clear_mask") == ""
    assert texture_editor_selected_adjustment(base.adjustment_layers, "b") == base.adjustment_layers[1]
    assert texture_editor_selected_adjustment(base.adjustment_layers, None) is None
    assert texture_editor_adjustment_refresh_selection_id(base.adjustment_layers, "b") == "b"
    assert texture_editor_adjustment_refresh_selection_id(base.adjustment_layers, "missing") == "c"
    assert texture_editor_adjustment_refresh_selection_id((), "missing") == ""
    assert tuple(layer.layer_id for layer in moved.document.adjustment_layers) == ("b", "a", "c")
    assert moved.changed is True
    assert moved.target_index == 0
    assert moved.document.composite_revision == 11
    assert moved.document.adjustment_layers[0].revision == 3
    assert unchanged_move.changed is False
    assert missing_move.target_index == -1
    assert soloed.found is True
    assert tuple(layer.enabled for layer in soloed.document.adjustment_layers) == (False, True, False)
    assert soloed.document.adjustment_layers[0].revision == 2
    assert soloed.document.adjustment_layers[1].revision == 3
    assert soloed.document.composite_revision == 11
    assert missing_solo.found is False
    assert added.changed is True
    assert added.history_label == "Add Adjustment"
    assert added.kind == "adjustment_update"
    assert added.tracked_layer_ids == ()
    assert added.preserve_selection_id == added.adjustment_id
    assert added.document.adjustment_layers[-1].name == "Exposure"
    assert added.document.adjustment_layers[-1].parameters == default_texture_editor_adjustment_parameters("exposure")
    assert removed.changed is True
    assert removed.history_label == "Remove Adjustment"
    assert tuple(layer.layer_id for layer in removed.document.adjustment_layers) == ("a", "c")
    assert missing_remove.changed is False
    assert duplicated.changed is True
    assert duplicated.history_label == "Duplicate Adjustment"
    assert duplicated.document.adjustment_layers[-1].name == "Exposure Copy"
    assert duplicated.document.adjustment_layers[-1].enabled is False
    assert assigned_mask.changed is True
    assert assigned_mask.history_label == "Assign Adjustment Mask"
    assert assigned_mask.status_text.startswith("Assigned the active raster layer")
    assert assigned_mask.document.adjustment_layers[1].mask_layer_id == "paint"
    assert missing_assign.changed is False
    assert cleared_mask.changed is True
    assert cleared_mask.history_label == "Clear Adjustment Mask"
    assert cleared_mask.document.adjustment_layers[0].mask_layer_id == ""
    assert unchanged_clear.changed is False
    assert reset.changed is True
    assert reset.history_label == "Reset Adjustment"
    assert reset.document.adjustment_layers[1].parameters == default_texture_editor_adjustment_parameters("exposure")
    assert updated_properties.adjustment_layers[1].enabled is True
    assert updated_properties.adjustment_layers[1].opacity == 42
    assert updated_properties.adjustment_layers[1].parameters["exposure"] == 5.0
    assert add_operation is not None
    assert add_operation.history_label == "Add Adjustment"
    assert remove_operation is not None
    assert remove_operation.history_label == "Remove Adjustment"
    assert duplicate_operation is not None
    assert duplicate_operation.history_label == "Duplicate Adjustment"
    assert move_operation is not None
    assert move_operation.changed is True
    assert move_operation.history_label == "Move Adjustment"
    assert move_operation.preserve_selection_id == "b"
    assert unchanged_move_operation is not None
    assert unchanged_move_operation.changed is False
    assert solo_operation is not None
    assert solo_operation.history_label == "Solo Adjustment"
    assert solo_operation.status_text.startswith("Soloed")
    assert assign_mask_operation is not None
    assert assign_mask_operation.history_label == "Assign Adjustment Mask"
    assert clear_mask_operation is not None
    assert clear_mask_operation.history_label == "Clear Adjustment Mask"
    assert reset_operation is not None
    assert reset_operation.history_label == "Reset Adjustment"
    assert missing_operation is None
    assert property_operation is not None
    assert property_operation.history_label == "Adjustment Update"
    assert property_operation.document.adjustment_layers[1].opacity == 42
    assert missing_property_operation is None
    assert texture_editor_adjustment_properties_dirty(base, soloed.document) is True
    assert texture_editor_adjustment_properties_dirty(base, base) is False


def test_texture_editor_layer_control_and_change_state() -> None:
    layer = TextureEditorLayer(
        "paint",
        "Paint",
        "",
        visible=False,
        opacity=72,
        blend_mode="multiply",
        locked=True,
        alpha_locked=False,
        mask_layer_id="mask",
        mask_enabled=True,
    )
    document = TextureEditorDocument("doc", 4, 4, active_layer_id="paint", layers=(layer,))

    controls = texture_editor_layer_control_state(
        layer,
        layer_pixel_ids={"paint", "mask"},
        editing_mask_target=True,
    )
    missing_mask_controls = texture_editor_layer_control_state(
        layer,
        layer_pixel_ids={"paint"},
        editing_mask_target=True,
    )
    opacity_only = texture_editor_layer_property_change(layer, visible=False, opacity=50, blend_mode="multiply")
    structural = texture_editor_layer_property_change(layer, visible=True, opacity=72, blend_mode="screen")
    unchanged = texture_editor_layer_property_change(layer, visible=False, opacity=72, blend_mode="multiply")
    opacity_update = texture_editor_layer_properties_document_state(
        document,
        "paint",
        visible=False,
        opacity=50,
        blend_mode="multiply",
    )
    structural_update = texture_editor_layer_properties_document_state(
        document,
        "paint",
        visible=True,
        opacity=72,
        blend_mode="screen",
    )
    unchanged_update = texture_editor_layer_properties_document_state(
        document,
        "paint",
        visible=False,
        opacity=72,
        blend_mode="multiply",
    )
    lock_update = texture_editor_layer_lock_document_state(
        document,
        "paint",
        locked=False,
        alpha_locked=True,
    )
    property_operation = texture_editor_layer_properties_operation_state(
        document,
        current_layer_id="paint",
        visible=True,
        opacity=64,
        blend_mode="screen",
    )
    missing_property_operation = texture_editor_layer_properties_operation_state(
        document,
        current_layer_id=None,
        visible=True,
        opacity=64,
        blend_mode="screen",
    )
    lock_operation = texture_editor_layer_lock_operation_state(
        document,
        current_layer_id="paint",
        locked=False,
        alpha_locked=True,
    )
    missing_lock_operation = texture_editor_layer_lock_operation_state(
        document,
        current_layer_id=None,
        locked=False,
        alpha_locked=True,
    )

    assert controls.name == "Paint"
    assert controls.visible_checked is False
    assert controls.locked_checked is True
    assert controls.mask_enabled_checked is True
    assert controls.edit_mask_checked is True
    assert controls.blend_mode == "multiply"
    assert controls.opacity == 72
    assert controls.mask_controls_enabled is True
    assert missing_mask_controls.mask_controls_enabled is False
    assert opacity_only.changed is True
    assert opacity_only.structural_refresh_needed is False
    assert structural.changed is True
    assert structural.structural_refresh_needed is True
    assert unchanged.changed is False
    assert opacity_update.changed is True
    assert opacity_update.structural_refresh_needed is False
    assert opacity_update.document.layers[0].opacity == 50
    assert structural_update.changed is True
    assert structural_update.structural_refresh_needed is True
    assert structural_update.document.layers[0].visible is True
    assert structural_update.document.layers[0].blend_mode == "screen"
    assert unchanged_update.changed is False
    assert lock_update.changed is True
    assert lock_update.document.layers[0].locked is False
    assert lock_update.document.layers[0].alpha_locked is True
    assert property_operation.changed is True
    assert property_operation.layer_id == "paint"
    assert property_operation.document is not None
    assert property_operation.document.layers[0].opacity == 64
    assert property_operation.structural_refresh_needed is True
    assert property_operation.history_label == "Change Layer Opacity"
    assert missing_property_operation.changed is False
    assert missing_property_operation.document is document
    assert lock_operation.changed is True
    assert lock_operation.layer_id == "paint"
    assert lock_operation.document is not None
    assert lock_operation.document.layers[0].locked is False
    assert lock_operation.history_label == "Layer Lock State"
    assert missing_lock_operation.changed is False
    assert missing_lock_operation.document is document
    assert texture_editor_layer_lock_change(layer, locked=True, alpha_locked=False).changed is False
    assert texture_editor_layer_lock_change(layer, locked=False, alpha_locked=False).changed is True


def test_texture_editor_layer_rename_reorder_and_mask_target_state() -> None:
    base = TextureEditorLayer("base", "Base", "", revision=1)
    paint = TextureEditorLayer("paint", "Paint", "", revision=2, mask_layer_id="mask")
    document = TextureEditorDocument("doc", 8, 8, active_layer_id="paint", layers=(base, paint))
    mask_pixels = np.zeros((2, 2, 4), dtype=np.uint8)
    mask_pixels[0, 0] = [255, 255, 255, 255]
    rename = texture_editor_layer_rename_state(paint, raw_name="  Detail Paint  ")
    fallback_rename = texture_editor_layer_rename_state(paint, raw_name="   ")
    unchanged_rename = texture_editor_layer_rename_state(paint, raw_name="Paint")
    reorder = texture_editor_drag_reorder_state((base, paint), display_layer_ids=("base", "paint"))
    same_reorder = texture_editor_drag_reorder_state((base, paint), display_layer_ids=("paint", "base"))
    invalid_reorder = texture_editor_drag_reorder_state((base, paint), display_layer_ids=("paint", "missing"))
    active_document = texture_editor_active_layer_document(document, "base")
    reorder_document = texture_editor_drag_reordered_document_state(document, display_layer_ids=("base", "paint"))
    same_reorder_document = texture_editor_drag_reordered_document_state(document, display_layer_ids=("paint", "base"))
    allowed_mask = texture_editor_edit_mask_target_state(checked=True, layer=paint, layer_pixel_ids={"mask"})
    missing_mask = texture_editor_edit_mask_target_state(checked=True, layer=paint, layer_pixel_ids=set())
    disabled_mask = texture_editor_edit_mask_target_state(checked=False, layer=paint, layer_pixel_ids={"mask"})
    mask_target = texture_editor_layer_mask_target_state(
        document,
        current_layer_id=None,
        layer_pixel_ids={"paint", "mask"},
    )
    missing_mask_target = texture_editor_layer_mask_target_state(
        document,
        current_layer_id="paint",
        layer_pixel_ids={"paint"},
    )
    invert_before = texture_editor_layer_mask_invert_before_pixels({"mask": mask_pixels}, "mask")
    rename_update = texture_editor_renamed_layer_document_state(document, "paint", raw_name="  Detail Paint  ")
    unchanged_rename_update = texture_editor_renamed_layer_document_state(document, "paint", raw_name="Paint")
    missing_rename_update = texture_editor_renamed_layer_document_state(document, "missing", raw_name="Detail")
    rename_operation = texture_editor_layer_rename_operation_state(
        document,
        current_layer_id="paint",
        raw_name="  Detail Paint  ",
    )
    missing_rename_operation = texture_editor_layer_rename_operation_state(
        document,
        current_layer_id=None,
        raw_name="Detail",
    )

    assert rename.name == "Detail Paint"
    assert rename.changed is True
    assert fallback_rename.name == "Layer"
    assert unchanged_rename.changed is False
    assert reorder.changed is True
    assert tuple(layer.layer_id for layer in reorder.updated_layers) == ("paint", "base")
    assert reorder.updated_layers[0].revision == 3
    assert same_reorder.changed is False
    assert invalid_reorder.changed is False
    assert active_document.active_layer_id == "base"
    assert reorder_document.changed is True
    assert tuple(layer.layer_id for layer in reorder_document.document.layers) == ("paint", "base")
    assert reorder_document.document.composite_revision == document.composite_revision + 1
    assert same_reorder_document.changed is False
    assert same_reorder_document.document is document
    assert allowed_mask.allowed is True
    assert allowed_mask.editing_mask_target is True
    assert allowed_mask.error is False
    assert missing_mask.allowed is False
    assert missing_mask.reset_checkbox is True
    assert "Add a layer mask" in missing_mask.status_text
    assert disabled_mask.allowed is True
    assert disabled_mask.editing_mask_target is False
    assert disabled_mask.status_text == ""
    assert mask_target.layer_id == "paint"
    assert mask_target.mask_layer_id == "mask"
    assert mask_target.can_update_mask_pixels is True
    assert missing_mask_target.can_update_mask_pixels is False
    assert invert_before["mask"][0, 0].tolist() == [255, 255, 255, 255]
    assert rename_update.changed is True
    assert rename_update.document.layers[1].name == "Detail Paint"
    assert unchanged_rename_update.changed is False
    assert missing_rename_update.changed is False
    assert rename_operation.changed is True
    assert rename_operation.layer_id == "paint"
    assert rename_operation.document is not None
    assert rename_operation.document.layers[1].name == "Detail Paint"
    assert rename_operation.history_label == "Rename Layer"
    assert missing_rename_operation.changed is False
    assert missing_rename_operation.document is document
    mask_pixels[0, 0] = [0, 0, 0, 0]
    assert invert_before["mask"][0, 0].tolist() == [255, 255, 255, 255]
    assert texture_editor_layer_mask_history_label("add") == "Add Layer Mask"
    assert texture_editor_layer_mask_history_label("invert") == "Invert Layer Mask"
    assert texture_editor_layer_mask_history_label("delete") == "Delete Layer Mask"
    assert texture_editor_layer_mask_history_label("toggle") == "Toggle Layer Mask"
    assert texture_editor_layer_mask_history_label("selection_to_mask") == "Selection To Mask"
    assert texture_editor_layer_mask_history_label("mask_to_selection") == "Mask To Selection"
    assert texture_editor_layer_mask_history_label("unknown") == "Layer Mask"
    assert texture_editor_layers_reordered_status_text() == "Reordered layers."
    assert texture_editor_layer_history_label("add") == "Add Layer"
    assert texture_editor_layer_history_label("duplicate") == "Duplicate Layer"
    assert texture_editor_layer_history_label("remove") == "Remove Layer"
    assert texture_editor_layer_history_label("merge_down") == "Merge Layer Down"
    assert texture_editor_layer_history_label("reorder") == "Reorder Layer"
    assert texture_editor_layer_history_label("rename") == "Rename Layer"
    assert texture_editor_layer_history_label("change_opacity") == "Change Layer Opacity"
    assert texture_editor_layer_history_label("toggle_visibility") == "Toggle Layer Visibility"
    assert texture_editor_layer_history_label("lock_state") == "Layer Lock State"
    assert texture_editor_layer_history_label("missing") == "Layer Update"


def test_texture_editor_selection_layer_mask_state_helpers_update_documents() -> None:
    selected = TextureEditorDocument(
        "doc",
        4,
        4,
        active_layer_id="paint",
        layers=(TextureEditorLayer("paint", "Paint", ""),),
        selection=TextureEditorSelection(mode="rect", rect=(1, 1, 2, 2)),
    )
    paint_pixels = np.zeros((4, 4, 4), dtype=np.uint8)
    paint_pixels[..., 3] = 255
    mask_state = texture_editor_selection_to_layer_mask_state(
        selected,
        {"paint": paint_pixels},
        "paint",
    )
    missing_mask_state = texture_editor_selection_to_layer_mask_state(
        TextureEditorDocument("empty", 4, 4, active_layer_id="paint", layers=selected.layers),
        {"paint": paint_pixels},
        "paint",
    )
    current_mask_state = texture_editor_selection_to_current_layer_mask_state(
        selected,
        {"paint": paint_pixels},
        current_layer_id=None,
    )
    masked_layer = next(layer for layer in mask_state.document.layers if layer.layer_id == "paint")
    mask_pixels = mask_state.layer_pixels[masked_layer.mask_layer_id]
    mask_to_selection_state = texture_editor_layer_mask_to_selection_state(
        dataclasses.replace(mask_state.document, selection=TextureEditorSelection()),
        mask_state.layer_pixels,
        "paint",
        combine_mode="replace",
    )
    current_mask_to_selection_state = texture_editor_current_layer_mask_to_selection_state(
        dataclasses.replace(mask_state.document, selection=TextureEditorSelection()),
        mask_state.layer_pixels,
        current_layer_id=None,
        combine_mode="replace",
    )
    missing_selection_state = texture_editor_layer_mask_to_selection_state(
        selected,
        {"paint": paint_pixels},
        "paint",
        combine_mode="replace",
    )

    assert mask_state.changed is True
    assert mask_state.history_label == "Selection To Mask"
    assert mask_state.status_text.startswith("Converted the current selection")
    assert mask_state.error is False
    assert mask_state.mask_layer_id == masked_layer.mask_layer_id
    assert mask_pixels[1, 1, 3] == 255
    assert mask_pixels[0, 0, 3] == 0
    assert missing_mask_state.changed is False
    assert missing_mask_state.error is True
    assert missing_mask_state.status_text.startswith("Create a selection first")
    assert current_mask_state.changed is True
    assert current_mask_state.mask_layer_id
    assert mask_to_selection_state.changed is True
    assert mask_to_selection_state.history_label == "Mask To Selection"
    assert mask_to_selection_state.status_text.startswith("Loaded the active layer mask")
    assert current_texture_editor_selection_bounds(mask_to_selection_state.document) == (1, 1, 2, 2)
    assert current_mask_to_selection_state.changed is True
    assert current_texture_editor_selection_bounds(current_mask_to_selection_state.document) == (1, 1, 2, 2)
    assert missing_selection_state.changed is False
    assert missing_selection_state.error is True
    assert missing_selection_state.status_text.startswith("The active layer does not have a mask")


def test_texture_editor_layer_operation_states_update_documents() -> None:
    base = TextureEditorLayer("base", "Base", "")
    paint = TextureEditorLayer("paint", "Paint", "")
    document = TextureEditorDocument("doc", 2, 2, active_layer_id="paint", layers=(base, paint))
    base_pixels = np.zeros((2, 2, 4), dtype=np.uint8)
    paint_pixels = np.zeros((2, 2, 4), dtype=np.uint8)
    paint_pixels[0, 0] = [200, 10, 20, 255]
    layer_pixels = {"base": base_pixels, "paint": paint_pixels}

    added = texture_editor_added_layer_state(document, layer_pixels)
    duplicated = texture_editor_duplicated_layer_state(document, layer_pixels, "paint")
    missing_duplicate = texture_editor_duplicated_layer_state(document, layer_pixels, "missing")
    removed = texture_editor_removed_layer_state(document, layer_pixels, "paint")
    merged = texture_editor_merged_layer_down_state(document, layer_pixels, "paint")
    reordered = texture_editor_reordered_layer_state(document, layer_pixels, "paint", direction=-1)
    moved = texture_editor_moved_layer_state(document, layer_id="paint", dx=2, dy=-1)
    add_operation = texture_editor_layer_action_operation_state(
        document,
        layer_pixels,
        action="add",
        current_layer_id=None,
    )
    duplicate_operation = texture_editor_layer_action_operation_state(
        document,
        layer_pixels,
        action="duplicate",
        current_layer_id="paint",
    )
    missing_duplicate_operation = texture_editor_layer_action_operation_state(
        document,
        layer_pixels,
        action="duplicate",
        current_layer_id=None,
    )
    remove_operation = texture_editor_layer_action_operation_state(
        document,
        layer_pixels,
        action="remove",
        current_layer_id="paint",
    )
    merge_operation = texture_editor_layer_action_operation_state(
        document,
        layer_pixels,
        action="merge_down",
        current_layer_id="paint",
    )
    reorder_operation = texture_editor_layer_action_operation_state(
        document,
        layer_pixels,
        action="reorder",
        current_layer_id="paint",
        direction=-1,
    )
    unknown_operation = texture_editor_layer_action_operation_state(
        document,
        layer_pixels,
        action="unknown",
        current_layer_id="paint",
    )

    assert added.kind == "layer_add"
    assert added.force_checkpoint is True
    assert added.layer_id in added.layer_pixels
    assert added.document.active_layer_id == added.layer_id
    assert duplicated is not None
    assert duplicated.kind == "layer_duplicate"
    assert duplicated.layer_id in duplicated.layer_pixels
    assert duplicated.layer_pixels[duplicated.layer_id][0, 0].tolist() == [200, 10, 20, 255]
    assert missing_duplicate is None
    assert removed.kind == "layer_remove"
    assert tuple(layer.layer_id for layer in removed.document.layers) == ("base",)
    assert "paint" not in removed.layer_pixels
    assert merged.kind == "layer_merge"
    assert tuple(layer.layer_id for layer in merged.document.layers) == ("base",)
    assert "paint" not in merged.layer_pixels
    assert reordered.kind == "layer_reorder"
    assert reordered.force_checkpoint is False
    assert reordered.tracked_layer_ids == ()
    assert tuple(layer.layer_id for layer in reordered.document.layers) == ("paint", "base")
    assert moved.document.layers[1].offset_x == 2
    assert moved.document.layers[1].offset_y == -1
    assert moved.history_label == "Move Layer"
    assert moved.kind == "layer_transform"
    assert moved.tracked_layer_ids == ()
    assert add_operation is not None
    assert add_operation.kind == "layer_add"
    assert duplicate_operation is not None
    assert duplicate_operation.kind == "layer_duplicate"
    assert missing_duplicate_operation is None
    assert remove_operation is not None
    assert remove_operation.kind == "layer_remove"
    assert merge_operation is not None
    assert merge_operation.kind == "layer_merge"
    assert reorder_operation is not None
    assert reorder_operation.kind == "layer_reorder"
    assert unknown_operation is None


def test_texture_editor_layer_mask_operation_states_update_documents() -> None:
    document = TextureEditorDocument(
        "doc",
        4,
        4,
        active_layer_id="paint",
        layers=(TextureEditorLayer("paint", "Paint", ""),),
    )
    paint_pixels = np.zeros((4, 4, 4), dtype=np.uint8)
    paint_pixels[..., 3] = 255
    add_state = added_texture_editor_layer_mask_state(
        document,
        {"paint": paint_pixels},
        current_layer_id=None,
    )
    masked_layer = next(layer for layer in add_state.document.layers if layer.layer_id == "paint")
    mask_pixels = add_state.layer_pixels[masked_layer.mask_layer_id].copy()
    mask_pixels[..., 3] = 255
    mask_pixels[0, 0, 3] = 0
    mask_layer_pixels = dict(add_state.layer_pixels)
    mask_layer_pixels[masked_layer.mask_layer_id] = mask_pixels
    masked_document = dataclasses.replace(
        add_state.document,
        layers=(dataclasses.replace(masked_layer, mask_enabled=True),),
    )

    invert_state = inverted_texture_editor_layer_mask_state(
        masked_document,
        mask_layer_pixels,
        current_layer_id="paint",
    )
    toggle_state = toggled_texture_editor_layer_mask_state(
        masked_document,
        mask_layer_pixels,
        current_layer_id="paint",
        checked=False,
    )
    delete_state = deleted_texture_editor_layer_mask_state(
        masked_document,
        mask_layer_pixels,
        current_layer_id="paint",
    )
    missing_invert = inverted_texture_editor_layer_mask_state(
        document,
        {"paint": paint_pixels},
        current_layer_id=None,
    )

    assert add_state.changed is True
    assert add_state.history_label == "Add Layer Mask"
    assert add_state.force_checkpoint is True
    assert add_state.before_layer_pixels["paint"] is paint_pixels
    assert masked_layer.mask_layer_id in add_state.layer_pixels
    assert invert_state.changed is True
    assert invert_state.history_label == "Invert Layer Mask"
    assert invert_state.tracked_layer_ids == (masked_layer.mask_layer_id,)
    assert invert_state.invalidate_layer_id == "paint"
    assert invert_state.layer_pixels[masked_layer.mask_layer_id][0, 0, 3] == 255
    assert invert_state.layer_pixels[masked_layer.mask_layer_id][1, 1, 3] == 0
    assert toggle_state.changed is True
    assert toggle_state.history_label == "Toggle Layer Mask"
    assert toggle_state.document.layers[0].mask_enabled is False
    assert delete_state.changed is True
    assert delete_state.history_label == "Delete Layer Mask"
    assert delete_state.reset_editing_mask_target is True
    assert delete_state.force_checkpoint is True
    assert delete_state.document.layers[0].mask_layer_id == ""
    assert masked_layer.mask_layer_id not in delete_state.layer_pixels
    assert missing_invert.changed is False


def test_texture_editor_layer_id_and_edit_target_state() -> None:
    document = TextureEditorDocument(
        "doc",
        8,
        8,
        active_layer_id="base",
        layers=(
            TextureEditorLayer("base", "Base", ""),
            TextureEditorLayer("paint", "Paint", "", mask_layer_id="mask"),
        ),
    )

    assert texture_editor_current_layer_id("paint") == "paint"
    assert texture_editor_current_layer_id(12) == "12"
    assert texture_editor_current_layer_id("") is None
    assert texture_editor_layer_by_id(document.layers, "paint") == document.layers[1]
    assert texture_editor_layer_by_id(document.layers, "missing") is None
    assert texture_editor_layer_by_id(document.layers, "") is None
    selected_target = texture_editor_layer_pixel_target_state(
        document,
        current_layer_id="paint",
        layer_pixel_ids={"paint"},
    )
    active_target = texture_editor_layer_pixel_target_state(
        document,
        current_layer_id=None,
        layer_pixel_ids={"base"},
    )
    missing_pixels_target = texture_editor_layer_pixel_target_state(
        document,
        current_layer_id="paint",
        layer_pixel_ids={"base"},
    )
    missing_layer_target = texture_editor_layer_pixel_target_state(
        TextureEditorDocument("missing", 8, 8, active_layer_id="ghost"),
        current_layer_id=None,
        layer_pixel_ids={"ghost"},
    )

    assert selected_target.layer_id == "paint"
    assert selected_target.layer == document.layers[1]
    assert selected_target.has_pixels is True
    assert selected_target.available is True
    assert active_target.layer_id == "base"
    assert active_target.available is True
    assert missing_pixels_target.has_pixels is False
    assert missing_pixels_target.available is False
    assert missing_layer_target.has_pixels is True
    assert missing_layer_target.layer is None
    assert missing_layer_target.available is False
    assert texture_editor_edit_target_layer_id(
        document,
        current_layer_id="paint",
        editing_mask_target=False,
    ) == "paint"
    assert texture_editor_edit_target_layer_id(
        document,
        current_layer_id=None,
        editing_mask_target=False,
    ) == "base"
    assert texture_editor_edit_target_layer_id(
        document,
        current_layer_id="paint",
        editing_mask_target=True,
    ) == "mask"
    assert texture_editor_edit_target_layer_id(
        document,
        current_layer_id="base",
        editing_mask_target=True,
    ) == "base"
    assert texture_editor_edit_target_layer_id(
        None,
        current_layer_id="paint",
        editing_mask_target=True,
    ) is None


def test_texture_editor_session_has_independent_thumbnail_cache() -> None:
    first = _TextureEditorSession("first", None, {}, [], 0)
    second = _TextureEditorSession("second", None, {}, [], 0)

    first.thumbnail_cache[("layer", 1)] = _create_tool_icon("paint")

    assert ("layer", 1) in first.thumbnail_cache
    assert second.thumbnail_cache == {}


def test_texture_editor_session_helpers_build_ids_and_revision() -> None:
    document_path = Path("C:/mods/editor/project.cdmwtex")
    floating = TextureEditorFloatingSelection(
        offset_x=4,
        offset_y=5,
        scale_x=1.2,
        scale_y=0.5,
        rotation_degrees=12.3,
        flip_x=True,
    )
    document = TextureEditorDocument(
        "Project",
        8,
        8,
        project_path=document_path,
        layers=(
            TextureEditorLayer("base", "Base", "", revision=2),
            TextureEditorLayer("paint", "Paint", "", revision=3),
        ),
        adjustment_layers=(TextureEditorAdjustmentLayer("adj", "Contrast", "brightness_contrast", revision=5),),
        floating_selection=floating,
        composite_revision=10,
    )
    stored = _TextureEditorSession("stored", document, {}, [], 0)
    unsaved = _TextureEditorSession("Unsaved", None, {}, [], 0)

    assert texture_editor_document_key(None) == ""
    assert texture_editor_document_key(document) == "C:/mods/editor/project.cdmwtex"
    assert texture_editor_open_document_ids((stored, unsaved)) == ("C:/mods/editor/project.cdmwtex", "Unsaved")
    assert texture_editor_document_composite_revision(document, has_floating_pixels=False) == 20
    assert texture_editor_document_composite_revision(document, has_floating_pixels=True) == 1000422


def test_texture_editor_session_helpers_build_tab_close_and_factory_state(tmp_path: Path) -> None:
    source_path = tmp_path / "source" / "body_d.dds"
    project_path = tmp_path / "project.ctfedit.json"
    pixels = {"base": np.zeros((2, 2, 4), dtype=np.uint8)}
    pixels["base"][0, 0] = [10, 20, 30, 255]
    document = TextureEditorDocument(
        "Project",
        2,
        2,
        project_path=project_path,
        layers=(TextureEditorLayer("base", "Base", ""),),
        source_binding=TextureEditorSourceBinding(source_path=str(source_path)),
    )

    session = create_texture_editor_session(document, pixels, label="Body Diffuse")
    other_session = _TextureEditorSession("Other", TextureEditorDocument("Other", 1, 1), {}, [], 0)
    tab_state = texture_editor_session_tab_state(session, 0)
    fallback_tab_state = texture_editor_session_tab_state(_TextureEditorSession("", document, {}, [], 0), 1)
    close_last = texture_editor_session_close_state(session_count_before=1, active_index=0, closed_index=0)
    close_current = texture_editor_session_close_state(session_count_before=3, active_index=1, closed_index=1)
    close_before_active = texture_editor_session_close_state(session_count_before=3, active_index=2, closed_index=0)
    label_update = texture_editor_active_session_label_update_state((other_session, session), 1, "Saved Title")
    missing_label_update = texture_editor_active_session_label_update_state((other_session, session), 9, "Saved Title")

    assert session.original_flattened is not None
    assert session.original_flattened[0, 0].tolist() == [10, 20, 30, 255]
    assert texture_editor_active_session_original_flattened((other_session, session), 1) is session.original_flattened
    assert texture_editor_active_session_original_flattened((other_session, session), 9) is None
    assert label_update.can_update is True
    assert label_update.index == 1
    assert label_update.label == "Saved Title"
    assert missing_label_update.can_update is False
    assert missing_label_update.index == -1
    assert texture_editor_existing_source_session_index((other_session, session), source_path) == 1
    assert texture_editor_existing_source_session_index((other_session, session), tmp_path / "missing.dds") == -1
    assert texture_editor_existing_project_session_index((other_session, session), project_path) == 1
    assert texture_editor_existing_project_session_index((other_session, session), tmp_path / "missing.json") == -1
    assert tab_state.label == "Body Diffuse"
    assert tab_state.tooltip == str(source_path)
    assert fallback_tab_state.label == "Document 2"
    assert close_last.has_remaining_sessions is False
    assert close_last.next_index == -1
    assert close_last.status_message == "Closed the last Texture Editor document."
    assert close_current.next_index == 1
    assert close_current.adjusted_active_index == 1
    assert close_before_active.next_index == 1
    assert close_before_active.adjusted_active_index == 1


def test_shortcut_editor_dialog_resets_to_defaults() -> None:
    _app()
    dialog = ShortcutEditorDialog(
        shortcuts={"save": "Ctrl+S"},
        labels={"save": "Save"},
        defaults={"save": "Ctrl+Shift+S"},
    )

    assert dialog.shortcut_map()["save"]
    dialog.reset_to_defaults()

    assert dialog.shortcut_map()["save"] == "Ctrl+Shift+S"


def test_collapsible_section_controls_content_visibility() -> None:
    _app()
    content = QLabel("content")
    section = CollapsibleSection("Details", content, expanded=True)

    assert section.is_expanded() is True
    assert content.isHidden() is False

    section.set_expanded(False)

    assert section.is_expanded() is False
    assert content.isHidden() is True


def test_texture_editor_navigator_and_ruler_state_updates() -> None:
    _app()
    navigator = TextureEditorNavigator()
    navigator.resize(220, 160)
    navigator.set_state(None, image_width=1024, image_height=512, viewport_rect=(100.0, 80.0, 300.0, 120.0))

    assert not navigator._target_rect().isEmpty()

    ruler = TextureEditorRuler(Qt.Horizontal)
    ruler.set_state(
        image_length=2048,
        other_length=512,
        display_scale=2.0,
        scroll_value=0,
        viewport_offset=8,
        hover_position=128,
        guides=[64, 256],
    )

    assert ruler._tick_step() > 0


def test_texture_editor_canvas_rgba_state_and_zoom() -> None:
    _app()
    canvas = TextureEditorCanvas()
    pixels = np.zeros((4, 5, 4), dtype=np.uint8)
    pixels[..., 3] = 255

    canvas.set_rgba_images(pixels)
    canvas.set_fit_to_view(False)
    canvas.set_zoom_factor(2.0)

    assert canvas.current_display_scale() == 2.0
    assert canvas.width() == 10
    assert canvas.height() == 8


def test_texture_editor_canvas_view_mode_builds_channel_image() -> None:
    _app()
    canvas = TextureEditorCanvas()
    pixels = np.zeros((2, 2, 4), dtype=np.uint8)
    pixels[..., 0] = 64
    pixels[..., 3] = 255

    canvas.set_rgba_images(pixels)
    canvas.set_view_mode("red")

    assert canvas._display_image is not None
    assert canvas._display_image.pixelColor(0, 0).red() == 64


def test_texture_editor_shortcut_helpers_merge_settings_values() -> None:
    stored = {"texture_editor/shortcuts/open_file": "Alt+O"}
    shortcuts = load_texture_editor_shortcuts(lambda key, default: stored.get(key, default))

    assert shortcuts["open_file"] == "Alt+O"
    assert shortcuts["undo"] == default_texture_editor_shortcuts()["undo"]
    assert texture_editor_shortcut_labels()["open_file"] == "Open file"
    assert texture_editor_shortcuts_updated_status_text() == "Texture Editor shortcuts updated."


def test_texture_editor_guide_text_helpers_normalize_values() -> None:
    assert parse_texture_editor_guides_text("10, 2.4; bad, -3, 10") == (0, 2, 10)
    assert format_texture_editor_guides_text((10, -1, 3)) == "10, 0, 3"
    assert texture_editor_guides_cleared_status_text() == "Texture Editor guides cleared."


def test_texture_editor_brush_preset_helpers_merge_custom_values() -> None:
    raw = '{"custom": {"size": 1}, "My Brush": {"size": 9, "tip": "round"}, "": {"size": 2}}'
    custom = normalize_texture_editor_custom_brush_presets(raw)
    merged = merged_texture_editor_brush_presets(custom)
    combo_state = texture_editor_brush_preset_combo_state(
        custom,
        preserve_key=None,
        current_key="my brush",
    )
    selected_values = texture_editor_brush_preset_values(custom, " MY BRUSH ")
    missing_values = texture_editor_brush_preset_values(custom, "missing")
    control_state = texture_editor_brush_preset_control_state(
        {
            "size": "12",
            "hardness": 80,
            "opacity": 75,
            "flow": 70,
            "spacing": 16,
            "tip": "flat",
            "pattern": "grain",
            "custom_tip_path": "stamp.png",
        }
    )

    assert BUILTIN_TEXTURE_EDITOR_BRUSH_PRESET_ORDER[0] == "detail"
    assert texture_editor_brush_preset_definitions()["detail"]["size"] == 4
    assert custom == {"my brush": {"size": 9, "tip": "round"}}
    assert merged["my brush"]["size"] == 9
    assert texture_editor_brush_preset_label("soft_paint") == "Soft Paint"
    assert texture_editor_brush_preset_label("my brush", custom=True) == "My Brush *"
    assert combo_state.entries[0].label == "Custom"
    assert combo_state.entries[1].key == "detail"
    assert combo_state.entries[-1].label == "My Brush *"
    assert combo_state.selected_key == "my brush"
    assert selected_values == {"size": 9, "tip": "round"}
    assert selected_values is not custom["my brush"]
    assert missing_values is None
    assert texture_editor_should_mark_brush_preset_custom("detail") is True
    assert texture_editor_should_mark_brush_preset_custom("custom") is False
    assert control_state.size == 12
    assert control_state.roundness == 100
    assert control_state.angle_degrees == 0
    assert control_state.tip == "flat"
    assert control_state.custom_tip_path == "stamp.png"


def test_texture_editor_brush_preset_serialization_normalizes_keys() -> None:
    serialized = serialize_texture_editor_custom_brush_presets(
        {"Custom": {"size": 1}, " Named ": {"size": 5}}
    )
    preset = texture_editor_custom_brush_preset_from_controls(
        size="4",
        hardness=5,
        opacity=6,
        flow=7,
        spacing=8,
        tip="",
        pattern="",
        custom_tip_path=" stamp.png ",
        roundness=91,
        angle=-10,
        smoothing=12,
        size_step_mode="",
    )
    saved_state = texture_editor_saved_custom_brush_preset_state(
        {},
        " Fine Detail ",
        size="4",
        hardness=5,
        opacity=6,
        flow=7,
        spacing=8,
        tip="",
        pattern="",
        custom_tip_path=" stamp.png ",
        roundness=91,
        angle=-10,
        smoothing=12,
        size_step_mode="",
    )
    missing_name_state = texture_editor_saved_custom_brush_preset_state(
        {},
        "   ",
        size="4",
        hardness=5,
        opacity=6,
        flow=7,
        spacing=8,
        tip="",
        pattern="",
        custom_tip_path=" stamp.png ",
        roundness=91,
        angle=-10,
        smoothing=12,
        size_step_mode="",
    )
    loaded_tip = texture_editor_loaded_custom_brush_tip_state("stamp.png")
    ignored_load = texture_editor_loaded_custom_brush_tip_state("")
    cleared_stamp = texture_editor_cleared_custom_brush_tip_state("stamp.png", current_tip="image_stamp")
    cleared_non_stamp = texture_editor_cleared_custom_brush_tip_state("stamp.png", current_tip="flat")
    ignored_clear = texture_editor_cleared_custom_brush_tip_state("", current_tip="image_stamp")

    assert '"named"' in serialized
    assert '"custom"' not in serialized
    assert normalized_texture_editor_custom_brush_preset_key(" Fine Detail ") == "fine_detail"
    assert texture_editor_brush_preset_missing_name_status_text() == "Enter a preset name first."
    assert texture_editor_brush_preset_saved_status_text("fine_detail") == "Saved brush preset 'fine_detail'."
    assert texture_editor_custom_brush_loaded_status_text() == "Loaded custom brush image stamp."
    assert texture_editor_custom_brush_cleared_status_text() == "Cleared custom brush image stamp."
    assert preset["size"] == 4
    assert preset["tip"] == "round"
    assert preset["pattern"] == "solid"
    assert preset["custom_tip_path"] == "stamp.png"
    assert preset["size_step_mode"] == "normal"
    assert saved_state.changed is True
    assert saved_state.preset_name == "fine_detail"
    assert saved_state.custom_presets["fine_detail"]["custom_tip_path"] == "stamp.png"
    assert saved_state.status_text == "Saved brush preset 'fine_detail'."
    assert missing_name_state.changed is False
    assert missing_name_state.error is True
    assert missing_name_state.status_text == "Enter a preset name first."
    assert loaded_tip.changed is True
    assert Path(loaded_tip.custom_tip_path).name == "stamp.png"
    assert loaded_tip.brush_tip_key == "image_stamp"
    assert ignored_load.changed is False
    assert cleared_stamp.changed is True
    assert cleared_stamp.brush_tip_key == "round"
    assert cleared_non_stamp.brush_tip_key == "flat"
    assert ignored_clear.changed is False


def test_texture_editor_history_blob_round_trips_rgba_pixels() -> None:
    pixels = np.zeros((2, 3, 4), dtype=np.uint8)
    pixels[1, 2] = [10, 20, 30, 40]

    restored = decode_texture_editor_rgba_blob(encode_texture_editor_rgba_blob(pixels))

    assert restored is not None
    assert restored.shape == pixels.shape
    assert restored[1, 2].tolist() == [10, 20, 30, 40]


def test_texture_editor_history_layer_state_uses_patch_for_small_dirty_bounds() -> None:
    document = TextureEditorDocument(
        "doc",
        4,
        4,
        layers=(TextureEditorLayer("layer", "Layer", "", offset_x=2, offset_y=3),),
    )
    before = np.zeros((4, 4, 4), dtype=np.uint8)
    after = before.copy()
    after[1, 1] = [100, 80, 60, 255]

    payload = encode_texture_editor_history_layer_state(
        document,
        "layer",
        after,
        dirty_bounds=(3, 4, 1, 1),
        previous_pixels=before,
    )
    restored = decode_texture_editor_history_layer_state(before, payload)

    assert isinstance(payload, dict)
    assert payload["local_bounds"] == [1, 1, 1, 1]
    assert restored is not None
    assert restored[1, 1].tolist() == [100, 80, 60, 255]


def test_texture_editor_history_layer_offset_and_aux_ids() -> None:
    document = TextureEditorDocument(
        "doc",
        4,
        4,
        layers=(
            TextureEditorLayer("base", "Base", "", offset_x=7, offset_y=9, mask_layer_id="mask"),
        ),
        adjustment_layers=(
            TextureEditorAdjustmentLayer("adjust", "Adjust", "brightness_contrast", mask_layer_id="adjust_mask"),
        ),
    )

    assert texture_editor_history_layer_canvas_offset(document, "mask") == (7, 9)
    assert texture_editor_history_auxiliary_layer_ids(document) == {"mask", "adjust_mask"}


def test_texture_editor_history_record_helpers_build_records_and_trim_redo() -> None:
    before_document = TextureEditorDocument(
        "doc",
        4,
        4,
        layers=(TextureEditorLayer("base", "Base", ""),),
    )
    after_document = dataclasses.replace(
        before_document,
        layers=(TextureEditorLayer("base", "Base", "", revision=1, mask_layer_id="mask"),),
        adjustment_layers=(TextureEditorAdjustmentLayer("adj", "Adjust", "brightness_contrast", mask_layer_id="adj_mask"),),
    )
    before_pixels = {"base": np.zeros((4, 4, 4), dtype=np.uint8)}
    after_pixels = {"base": before_pixels["base"].copy()}
    after_pixels["base"][1, 1] = [50, 60, 70, 255]
    floating_pixels = np.zeros((1, 1, 4), dtype=np.uint8)
    floating_pixels[0, 0] = [1, 2, 3, 4]

    checkpoint = build_texture_editor_checkpoint_record(
        after_document,
        after_pixels,
        "Checkpoint",
        timestamp=10.0,
        floating_pixels=floating_pixels,
    )
    delta = build_texture_editor_delta_history_record(
        label="Paint",
        before_document=before_document,
        after_document=after_document,
        before_layer_pixels=before_pixels,
        after_layer_pixels=after_pixels,
        kind="paint",
        timestamp=11.0,
        dirty_bounds=(1, 1, 1, 1),
        tracked_layer_ids=("base",),
        before_floating_pixels=None,
        after_floating_pixels=floating_pixels,
    )
    restored_after = decode_texture_editor_history_layer_state(before_pixels["base"], delta["after_layers"]["base"])
    restored_floating = decode_texture_editor_rgba_blob(checkpoint["floating_pixels"])
    updated, updated_index = texture_editor_history_with_appended_record(
        [{"entry": "old0"}, {"entry": "old1"}, {"entry": "redo"}],
        1,
        delta,
        limit=3,
    )
    capped, capped_index = texture_editor_history_with_appended_record(
        [{"entry": "old0"}, {"entry": "old1"}, {"entry": "old2"}],
        2,
        checkpoint,
        limit=3,
    )

    assert checkpoint["command"]["checkpoint"] is True
    assert restored_floating is not None
    assert restored_floating[0, 0].tolist() == [1, 2, 3, 4]
    assert delta["entry"].label == "Paint"
    assert delta["command"]["kind"] == "paint"
    assert restored_after is not None
    assert restored_after[1, 1].tolist() == [50, 60, 70, 255]
    assert texture_editor_history_should_checkpoint(history_count=0, force_checkpoint=False) is True
    assert texture_editor_history_should_checkpoint(history_count=18, force_checkpoint=False) is False
    assert texture_editor_history_should_checkpoint(history_count=19, force_checkpoint=False) is True
    assert texture_editor_history_should_checkpoint(history_count=2, force_checkpoint=True) is True
    assert texture_editor_history_tracked_layer_ids(before_document, after_document) == {"base", "mask", "adj_mask"}
    assert updated == [{"entry": "old0"}, {"entry": "old1"}, delta]
    assert updated_index == 2
    assert capped == [{"entry": "old1"}, {"entry": "old2"}, checkpoint]
    assert capped_index == 2


def test_texture_editor_history_replay_helpers_apply_records_and_format_rows() -> None:
    before_document = TextureEditorDocument(
        "doc",
        4,
        4,
        layers=(TextureEditorLayer("base", "Base", ""),),
    )
    after_document = dataclasses.replace(
        before_document,
        layers=(TextureEditorLayer("base", "Base", "", revision=1),),
    )
    before_pixels = {"base": np.zeros((4, 4, 4), dtype=np.uint8)}
    after_pixels = {"base": before_pixels["base"].copy()}
    after_pixels["base"][2, 2] = [90, 80, 70, 255]
    checkpoint = build_texture_editor_checkpoint_record(
        before_document,
        before_pixels,
        "Base",
        timestamp=1.0,
    )
    delta = build_texture_editor_delta_history_record(
        label="Paint",
        before_document=before_document,
        after_document=after_document,
        before_layer_pixels=before_pixels,
        after_layer_pixels=after_pixels,
        kind="paint",
        timestamp=2.0,
        dirty_bounds=(2, 2, 1, 1),
        tracked_layer_ids=("base",),
    )

    applied_after = texture_editor_history_record_application_state(
        delta,
        direction="after",
        current_layer_pixels=before_pixels,
    )
    applied_before = texture_editor_history_record_application_state(
        delta,
        direction="before",
        current_layer_pixels=after_pixels,
    )
    applied_checkpoint = texture_editor_history_record_application_state(
        checkpoint,
        direction="after",
        current_layer_pixels={},
    )
    applied_document_pixels = texture_editor_applied_history_document_state(
        after_document,
        {"base": before_pixels["base"], "orphan": np.ones((1, 1, 4), dtype=np.uint8)},
        delta["after_layers"],
    )
    checkpoint_plan = texture_editor_history_replay_plan([checkpoint, delta], 1)
    no_checkpoint_plan = texture_editor_history_replay_plan([delta, delta], 1)
    invalid_plan = texture_editor_history_replay_plan([checkpoint], 5)
    restore_state = texture_editor_history_restore_state([checkpoint, delta], 1)
    invalid_restore_state = texture_editor_history_restore_state([checkpoint], 5)
    selected_state = texture_editor_history_selected_row_state([checkpoint, delta], 1, history_index=0)
    current_selection_state = texture_editor_history_selected_row_state([checkpoint, delta], 0, history_index=0)
    cleared_state = texture_editor_history_cleared_state(delta)

    assert applied_after.document.layers[0].revision == 1
    assert applied_after.layer_pixels["base"][2, 2].tolist() == [90, 80, 70, 255]
    assert applied_after.floating_pixels is None
    assert applied_before.layer_pixels["base"][2, 2].tolist() == [0, 0, 0, 0]
    assert applied_checkpoint.document.title == "doc"
    assert applied_checkpoint.layer_pixels["base"].shape == (4, 4, 4)
    assert applied_document_pixels["base"][2, 2].tolist() == [90, 80, 70, 255]
    assert "orphan" not in applied_document_pixels
    assert checkpoint_plan.checkpoint_index == 0
    assert checkpoint_plan.apply_indices == (0, 1)
    assert no_checkpoint_plan.checkpoint_index == -1
    assert no_checkpoint_plan.apply_indices == (0, 1)
    assert invalid_plan.apply_indices == ()
    assert restore_state.can_restore is True
    assert restore_state.replay_plan.apply_indices == (0, 1)
    assert restore_state.status_text == "Restored history step: Paint."
    assert invalid_restore_state.can_restore is False
    assert selected_state.selected_index == 1
    assert selected_state.status_text.startswith("Selected history step 'Paint'.")
    assert current_selection_state.selected_index is None
    assert current_selection_state.status_text == ""
    assert cleared_state.history_snapshots == [delta]
    assert cleared_state.history_index == 0
    assert cleared_state.status_text.startswith("Texture Editor history cleared.")
    assert texture_editor_history_list_item_text("Paint", current=False) == "Paint"
    assert texture_editor_history_list_item_text("Paint", current=True) == "Paint (current)"
    assert texture_editor_history_selection_status_text("Paint").startswith("Selected history step 'Paint'.")
    assert texture_editor_history_restored_status_text("Paint") == "Restored history step: Paint."
    assert texture_editor_history_cleared_status_text().startswith("Texture Editor history cleared.")


def test_texture_editor_adjustment_helpers_format_defaults_and_labels() -> None:
    assert default_texture_editor_adjustment_parameters("exposure") == {
        "exposure": 0.0,
        "offset": 0.0,
        "gamma": 1.0,
    }

    label = texture_editor_adjustment_list_label(
        TextureEditorAdjustmentLayer(
            "adj",
            "Warmth",
            "color_balance",
            enabled=False,
            parameters={"red_cyan": 5.2, "green_magenta": -2.1, "blue_yellow": 0.0},
            mask_layer_id="mask",
        )
    )

    assert label == "[Off] Warmth  Mask  R:+5 G:-2 B:+0"


def test_texture_editor_ui_constraint_helpers_detect_ui_paths() -> None:
    binding = TextureEditorSourceBinding(
        relative_path="textures/world/foo.dds",
        archive_relative_path="ui/icons/itemicon_sword.dds",
    )
    cached_binding = TextureEditorSourceBinding(relative_path="ui/menu/title.dds")
    ignored_binding = TextureEditorSourceBinding(relative_path="textures/world/rock.dds")
    lookup_binding = TextureEditorSourceBinding(relative_path="ui/icons/itemicon_missing.dds")
    cached_state = texture_editor_ui_constraint_warning_lookup_state(
        cached_binding,
        {"ui/menu/title.dds": "cached warning"},
    )
    ignored_state = texture_editor_ui_constraint_warning_lookup_state(ignored_binding, {})
    lookup_state = texture_editor_ui_constraint_warning_lookup_state(lookup_binding, {})
    cached_warning_state = texture_editor_ui_constraint_warning_state(
        cached_binding,
        {"ui/menu/title.dds": "cached warning"},
    )
    ignored_warning_state = texture_editor_ui_constraint_warning_state(ignored_binding, {})
    lookup_warning_state = texture_editor_ui_constraint_warning_state(lookup_binding, {})
    empty_warning_state = texture_editor_ui_constraint_warning_state(None, {})

    assert texture_editor_ui_constraint_target_path(binding) == "ui/icons/itemicon_sword.dds"
    assert texture_editor_ui_constraint_cache_key(" UI/Menu/Title.dds ") == "ui/menu/title.dds"
    assert looks_like_texture_editor_ui_constraint_candidate("ui/icons/itemicon_sword.dds") is True
    assert looks_like_texture_editor_ui_constraint_candidate("textures/world/rock.dds") is False
    assert cached_state.warning_text == "cached warning"
    assert cached_state.should_start_lookup is False
    assert ignored_state.should_cache_empty is True
    assert ignored_state.should_start_lookup is False
    assert lookup_state.target_path == "ui/icons/itemicon_missing.dds"
    assert lookup_state.should_start_lookup is True
    assert cached_warning_state.warning_text == "cached warning"
    assert cached_warning_state.empty_cache_key == ""
    assert cached_warning_state.lookup_target_path == ""
    assert ignored_warning_state.empty_cache_key == "textures/world/rock.dds"
    assert ignored_warning_state.lookup_target_path == ""
    assert lookup_warning_state.empty_cache_key == ""
    assert lookup_warning_state.lookup_target_path == "ui/icons/itemicon_missing.dds"
    assert empty_warning_state.warning_text == ""
    start_state = texture_editor_ui_constraint_lookup_start_state(
        "ui/icons/itemicon_missing.dds",
        {},
        pending_cache_key="",
        worker_active=False,
    )
    cached_start_state = texture_editor_ui_constraint_lookup_start_state(
        "ui/icons/itemicon_missing.dds",
        {"ui/icons/itemicon_missing.dds": "cached"},
        pending_cache_key="",
        worker_active=False,
    )
    pending_start_state = texture_editor_ui_constraint_lookup_start_state(
        "ui/icons/itemicon_missing.dds",
        {},
        pending_cache_key="ui/icons/itemicon_missing.dds",
        worker_active=False,
    )
    busy_start_state = texture_editor_ui_constraint_lookup_start_state(
        "ui/icons/itemicon_missing.dds",
        {},
        pending_cache_key="",
        worker_active=True,
    )
    ready_state = texture_editor_ui_constraint_ready_state(
        "ui/icons/itemicon_missing.dds",
        "new warning",
        lookup_binding,
    )
    closed_ready_state = texture_editor_ui_constraint_ready_state(
        "ui/icons/itemicon_missing.dds",
        "new warning",
        None,
    )

    assert start_state.cache_key == "ui/icons/itemicon_missing.dds"
    assert start_state.should_start is True
    assert cached_start_state.should_start is False
    assert pending_start_state.should_start is False
    assert busy_start_state.should_start is False
    assert ready_state.warning_text == "new warning"
    assert ready_state.should_refresh_metadata is True
    assert closed_ready_state.cache_key == "ui/icons/itemicon_missing.dds"
    assert closed_ready_state.should_refresh_metadata is False


def test_texture_editor_floating_bounds_helpers_use_layer_offsets_and_document_limits() -> None:
    document = TextureEditorDocument(
        "doc",
        10,
        8,
        layers=(TextureEditorLayer("layer", "Layer", "", offset_x=2, offset_y=3, mask_layer_id="mask"),),
    )
    layer_pixels = {"mask": np.zeros((2, 3, 4), dtype=np.uint8)}

    assert texture_editor_layer_canvas_bounds(document, layer_pixels, "mask") == (2, 3, 3, 2)
    assert estimated_texture_editor_brush_dirty_bounds(
        document,
        TextureEditorToolSettings(size=4),
        ((1, 1), (5, 6)),
        padding=2,
    ) == (0, 0, 8, 8)


def test_texture_editor_shift_pixels_moves_full_and_masked_regions() -> None:
    pixels = np.zeros((3, 3, 4), dtype=np.uint8)
    pixels[1, 1] = [10, 20, 30, 255]

    shifted = shift_texture_editor_pixels(pixels, 1, -1)

    assert shifted[0, 2].tolist() == [10, 20, 30, 255]
    assert shifted[1, 1].tolist() == [0, 0, 0, 0]

    mask = np.zeros((3, 3), dtype=np.uint8)
    mask[1, 1] = 255
    masked = shift_texture_editor_pixels(pixels, 1, 0, selection_mask=mask)

    assert masked[1, 1].tolist() == [0, 0, 0, 0]
    assert masked[1, 2].tolist() == [10, 20, 30, 255]


def test_texture_editor_floating_pixel_bounds_and_cut_clear_helpers() -> None:
    pixels = np.zeros((3, 4, 4), dtype=np.uint8)
    pixels[1, 2] = [10, 20, 30, 255]
    empty_pixels = np.zeros((2, 3, 4), dtype=np.uint8)

    target_pixels = np.full((3, 3, 4), [100, 80, 60, 200], dtype=np.uint8)
    selection_mask = np.zeros((5, 5), dtype=np.uint8)
    selection_mask[1, 1] = 255
    layer = TextureEditorLayer("layer", "Layer", "", offset_x=1, offset_y=1)
    cleared = clear_texture_editor_selection_from_layer_pixels(
        target_pixels,
        selection_mask,
        layer,
        (1, 1, 2, 2),
    )

    assert texture_editor_nontransparent_pixel_bounds(pixels) == (2, 1, 3, 2)
    assert texture_editor_nontransparent_pixel_bounds(empty_pixels) == (0, 0, 3, 2)
    assert cleared[0, 0].tolist() == [0, 0, 0, 0]
    assert cleared[0, 1].tolist() == [100, 80, 60, 200]
    assert target_pixels[0, 0].tolist() == [100, 80, 60, 200]


def test_texture_editor_floating_transform_bounds_and_composition() -> None:
    floating = TextureEditorFloatingSelection(bounds=(1, 1, 2, 1), offset_x=1, flip_x=True)
    document = TextureEditorDocument("doc", 5, 4, floating_selection=floating)
    floating_pixels = np.zeros((1, 2, 4), dtype=np.uint8)
    floating_pixels[0, 0] = [200, 20, 10, 255]
    floating_pixels[0, 1] = [10, 200, 20, 255]
    base = np.zeros((4, 5, 4), dtype=np.uint8)

    transformed = transformed_texture_editor_floating_pixels(floating, floating_pixels)
    snapshot = texture_editor_snapshot_floating_pixels(floating_pixels)
    composed = compose_texture_editor_floating_selection(document, base, floating_pixels)
    region = compose_texture_editor_floating_selection_region(
        document,
        base[1:3, 1:4],
        floating_pixels,
        (1, 1, 3, 2),
    )
    canvas_state = texture_editor_floating_canvas_transform_state(document, floating_pixels)
    empty_canvas_state = texture_editor_floating_canvas_transform_state(document, None)

    assert transformed is not None
    assert transformed[0, 0].tolist() == [10, 200, 20, 255]
    assert snapshot is not None
    assert snapshot is not floating_pixels
    assert snapshot.tolist() == floating_pixels.tolist()
    assert texture_editor_snapshot_floating_pixels(None) is None
    assert current_texture_editor_floating_canvas_bounds(document, floating_pixels) == (2, 1, 2, 1)
    assert canvas_state.current_bounds == (2, 1, 2, 1)
    assert canvas_state.origin_bounds == (1, 1, 2, 1)
    assert canvas_state.offset_x == 1
    assert canvas_state.scale_x == 1.0
    assert empty_canvas_state.current_bounds is None
    assert empty_canvas_state.origin_bounds is None
    assert composed[1, 2].tolist() == [10, 200, 20, 255]
    assert composed[1, 3].tolist() == [200, 20, 10, 255]
    assert region[0, 1].tolist() == [10, 200, 20, 255]


def test_texture_editor_floating_commit_state_helpers() -> None:
    floating = TextureEditorFloatingSelection(label="Paint Selection", bounds=(1, 2, 3, 4), offset_x=5, offset_y=-1)
    document = TextureEditorDocument("doc", 8, 8, floating_selection=floating)
    transformed = np.zeros((4, 3, 4), dtype=np.uint8)
    transformed[0, 0] = [90, 80, 70, 255]

    state = texture_editor_floating_commit_state(floating, transformed)
    layer_state = texture_editor_floating_committed_layer_state(document, {}, transformed)
    move_state = texture_editor_floating_move_state(document, dx=2, dy=-3)

    assert state is not None
    assert state.layer_name == "Paint Selection Layer"
    assert state.target_x == 6
    assert state.target_y == 1
    assert state.dirty_bounds == (6, 1, 3, 4)
    assert state.history_label == "Commit Floating Selection"
    assert state.status_text == "Committed floating selection to a new layer."
    assert texture_editor_floating_commit_state(None, transformed) is None
    assert texture_editor_floating_commit_state(floating, None) is None
    assert layer_state is not None
    assert layer_state.document.active_layer_id == layer_state.layer_id
    assert layer_state.document.layers[-1].name == "Paint Selection Layer"
    assert layer_state.document.layers[-1].offset_x == 6
    assert layer_state.document.layers[-1].offset_y == 1
    assert layer_state.layer_pixels[layer_state.layer_id][0, 0].tolist() == [90, 80, 70, 255]
    assert layer_state.dirty_bounds == (6, 1, 3, 4)
    assert layer_state.history_label == "Commit Floating Selection"
    assert layer_state.status_text == "Committed floating selection to a new layer."
    assert texture_editor_floating_committed_layer_state(document, {}, None) is None
    assert move_state is not None
    assert move_state.document.floating_selection is not None
    assert move_state.document.floating_selection.offset_x == 7
    assert move_state.document.floating_selection.offset_y == -4
    assert move_state.document.floating_selection.committed is False
    assert move_state.dirty_bounds == (1, -2, 5, 7)
    assert move_state.history_label == "Move Floating Selection"
    assert move_state.kind == "floating_transform"
    assert move_state.tracked_layer_ids == ()
    assert texture_editor_floating_move_state(TextureEditorDocument("doc", 8, 8), dx=1, dy=1) is None
    assert texture_editor_floating_cancel_history_label() == "Cancel Floating Selection"
    assert texture_editor_floating_cancel_status_text() == "Canceled floating selection."
    assert texture_editor_floating_selection_updated_status_text() == "Updated floating selection on the canvas."


def test_texture_editor_set_and_clear_floating_selection_state() -> None:
    document = TextureEditorDocument(
        "doc",
        8,
        8,
        selection=TextureEditorSelection(mode="rect", rect=(1, 1, 2, 2)),
    )
    pixels = np.zeros((2, 3, 4), dtype=np.uint8)
    pixels[..., 3] = 128

    state = texture_editor_set_floating_selection_state(
        document,
        pixels,
        label="Pasted",
        bounds=(2, 3, 3, 2),
        source_layer_id="layer",
        paste_mode="centered",
    )
    floating = state.document.floating_selection

    assert floating is not None
    assert floating.label == "Pasted"
    assert floating.source_layer_id == "layer"
    assert floating.bounds == (2, 3, 3, 2)
    assert floating.paste_mode == "centered"
    assert floating.committed is False
    assert state.document.selection.mode == "none"
    assert state.floating_pixels is not pixels
    assert state.floating_pixels.shape == pixels.shape
    assert state.floating_mask.shape == pixels.shape[:2]
    assert state.floating_mask[0, 0] == 128
    assert state.dirty_bounds == (2, 3, 3, 2)
    cleared = texture_editor_cleared_floating_selection_state(state.document)
    assert cleared.floating_selection is None


def test_texture_editor_floating_layer_copy_state_extracts_visible_bounds() -> None:
    document = TextureEditorDocument(
        "doc",
        8,
        8,
        active_layer_id="paint",
        layers=(TextureEditorLayer("paint", "Paint", "", offset_x=2, offset_y=1),),
    )
    pixels = np.zeros((4, 5, 4), dtype=np.uint8)
    pixels[1:3, 2:4, 0] = 200
    pixels[1:3, 2:4, 3] = 255

    copy_state = texture_editor_floating_layer_copy_state(
        document,
        {"paint": pixels},
        current_layer_id=None,
    )
    missing_state = texture_editor_floating_layer_copy_state(
        document,
        {},
        current_layer_id=None,
    )

    assert copy_state.can_float is True
    assert copy_state.pixels is not None
    assert copy_state.pixels.shape == (2, 2, 4)
    assert copy_state.label == "Paint Copy"
    assert copy_state.bounds == (4, 2, 2, 2)
    assert copy_state.source_layer_id == "paint"
    assert copy_state.history_label == "Float Active Layer Copy"
    assert copy_state.status_text == "Floating copy created from 'Paint'."
    assert missing_state.can_float is False
    assert missing_state.status_text == ""
    assert texture_editor_float_layer_copy_history_label() == "Float Active Layer Copy"
    assert texture_editor_float_layer_copy_empty_status_text().startswith("The active layer")
    assert texture_editor_float_layer_copy_status_text("Paint") == "Floating copy created from 'Paint'."


def test_texture_editor_status_helpers_format_tool_and_hover_text() -> None:
    assert "Patch tool active" in texture_editor_tool_status_text("patch")
    assert texture_editor_tool_status_text("custom_tool") == "Custom Tool tool active."
    assert texture_editor_hover_pixel_text({"x": 3, "y": 4, "rgba": (1, 2, 3, 4)}) == "XY 3, 4  RGBA 1, 2, 3, 4"
    assert texture_editor_hover_pixel_text({"rgba": (1, 2, 3)}) == "XY -, -  RGBA -"


def test_texture_editor_canvas_status_state_summarizes_document_state() -> None:
    floating = TextureEditorFloatingSelection(bounds=(1, 1, 2, 1))
    document = TextureEditorDocument(
        "doc",
        16,
        8,
        active_layer_id="layer",
        layers=(TextureEditorLayer("layer", "Paint", ""),),
        source_binding=TextureEditorSourceBinding(relative_path="textures/a.dds"),
        selection=TextureEditorSelection(mode="rect"),
        floating_selection=floating,
        quick_mask_enabled=True,
        edit_green_channel=False,
        edit_alpha_channel=False,
    )
    adjustment = TextureEditorAdjustmentLayer("adj", "Exposure", "exposure")

    status = texture_editor_canvas_status_state(
        document,
        TextureEditorToolSettings(tool="select_rect", symmetry_mode="mirror_x"),
        hover_pixel_info={"x": 1, "y": 2, "rgba": (10, 20, 30, 40)},
        editing_mask_target=True,
        layer_property_dirty=True,
        adjustment_property_dirty=False,
        selected_adjustment=adjustment,
        has_floating_pixels=True,
    )

    assert texture_editor_selection_status_text(document, has_floating_pixels=True) == "Floating selection active | Quick Mask"
    assert status.tool_text == "Tool Select Rect"
    assert status.layer_text == "Layer Paint"
    assert status.selection_text == "Floating selection active | Quick Mask"
    assert status.state_text == "Edit Mask | Layer Pending | Adj Exposure | Ch RB | Sym Mirror_X"
    assert status.document_text == "16x8"
    assert status.source_text == "textures/a.dds"


def test_texture_editor_canvas_status_state_handles_no_document() -> None:
    status = texture_editor_canvas_status_state(
        None,
        TextureEditorToolSettings(),
        hover_pixel_info=None,
        editing_mask_target=False,
        layer_property_dirty=False,
        adjustment_property_dirty=False,
        selected_adjustment=None,
        has_floating_pixels=False,
    )

    assert status.tool_text == "No tool"
    assert status.document_text == "No document"


def test_texture_editor_selection_state_helpers_format_labels_and_bounds() -> None:
    document = TextureEditorDocument(
        "doc",
        10,
        8,
        selection=TextureEditorSelection(mode="rect", rect=(2, 1, 4, 3)),
    )
    inverted_document = TextureEditorDocument(
        "doc",
        10,
        8,
        selection=TextureEditorSelection(mode="rect", rect=(2, 1, 4, 3), inverted=True, feather_radius=5),
    )
    cleared = texture_editor_document_with_cleared_selection_only(inverted_document)
    short_lasso = simplified_texture_editor_lasso_points(((1, 2), (3, 4)))
    fallback_lasso = simplified_texture_editor_lasso_points(((0, 0), (1, 1), (2, 2)))

    assert texture_editor_selection_refine_labels(0) == ("Grow +1", "Shrink -1")
    assert texture_editor_selection_refine_labels(5) == ("Grow +5", "Shrink -5")
    assert current_texture_editor_selection_bounds(document) == (2, 1, 4, 3)
    assert current_texture_editor_selection_bounds(TextureEditorDocument("empty", 10, 8)) is None
    assert cleared.selection.mode == "none"
    assert cleared.selection.inverted is False
    assert cleared.selection.feather_radius == 5
    assert short_lasso == [(1.0, 2.0), (3.0, 4.0)]
    assert fallback_lasso == [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)]


def test_texture_editor_canvas_selection_payload_helpers_update_document() -> None:
    document = TextureEditorDocument("doc", 10, 8)
    settings = TextureEditorToolSettings(lasso_snap_to_edges=True, lasso_snap_radius=4, lasso_edge_sensitivity=50)
    rect_state = texture_editor_canvas_selection_payload_state({"mode": "rect", "rect": (2, 1, 4, 3)})
    lasso_state = texture_editor_canvas_selection_payload_state(
        {"mode": "lasso", "points": [(1, 1), (6, 1), (6, 5), (1, 5)]}
    )
    source_document = TextureEditorDocument(
        "source",
        2,
        2,
        active_layer_id="paint",
        layers=(TextureEditorLayer("paint", "Paint", ""),),
    )
    source_pixels = {"paint": np.zeros((2, 2, 4), dtype=np.uint8)}
    source_pixels["paint"][0, 0] = [11, 22, 33, 255]
    composite_rgba = np.full((2, 2, 4), [1, 2, 3, 4], dtype=np.uint8)
    composite_source = texture_editor_canvas_selection_source_pixels(source_document, source_pixels, composite_rgba)
    flattened_source = texture_editor_canvas_selection_source_pixels(source_document, source_pixels, None)

    assert rect_state is not None
    assert rect_state.mode == "rect"
    assert rect_state.rect == (2, 1, 4, 3)
    assert lasso_state is not None
    assert lasso_state.mode == "lasso"
    assert texture_editor_canvas_selection_payload_state({"mode": "rect", "rect": [2, 1, 4, 3]}) is None
    assert texture_editor_canvas_selection_payload_state({"mode": "lasso", "points": ((1, 1), (6, 1), (6, 5))}) is None
    assert composite_source is composite_rgba
    assert flattened_source is not None
    assert flattened_source[0, 0].tolist() == [11, 22, 33, 255]
    assert texture_editor_canvas_selection_source_pixels(None, source_pixels, None) is None

    rect_update = texture_editor_canvas_selection_update_state(
        document,
        rect_state,
        settings=settings,
        snap_pixels=None,
    )
    prepared_lasso = texture_editor_prepared_lasso_selection_points(
        lasso_state.points,
        settings,
        snap_pixels=None,
    )
    lasso_update = texture_editor_canvas_selection_update_state(
        document,
        lasso_state,
        settings=settings,
        snap_pixels=None,
    )

    assert rect_update is not None
    assert rect_update.history_label == "Rect Selection"
    assert current_texture_editor_selection_bounds(rect_update.document) == (2, 1, 4, 3)
    assert len(prepared_lasso) >= 3
    assert lasso_update is not None
    assert lasso_update.history_label == "Lasso Selection"
    assert current_texture_editor_selection_bounds(lasso_update.document) is not None


def test_texture_editor_selection_control_update_helpers_track_history_labels() -> None:
    selected = TextureEditorDocument(
        "doc",
        8,
        8,
        selection=TextureEditorSelection(mode="rect", rect=(2, 2, 2, 2), feather_radius=1),
    )
    empty = TextureEditorDocument("empty", 8, 8)

    cleared = texture_editor_clear_selection_update_state(selected)
    selected_all = texture_editor_select_all_update_state(empty)
    grown = texture_editor_resized_selection_update_state(selected, 1)
    shrunk = texture_editor_resized_selection_update_state(selected, -1)
    ignored_resize = texture_editor_resized_selection_update_state(empty, 1)
    quick_mask = texture_editor_quick_mask_update_state(empty, True)
    feather_preview = texture_editor_selection_feather_preview_document(selected, 4)
    feather_commit = texture_editor_selection_feather_update_state(selected, 5)
    inverted = texture_editor_selection_invert_update_state(selected, True)
    clear_operation = texture_editor_selection_operation_state(selected, action="clear")
    select_all_operation = texture_editor_selection_operation_state(empty, action="select_all")
    grow_operation = texture_editor_selection_operation_state(selected, action="resize", delta=1)
    ignored_operation = texture_editor_selection_operation_state(empty, action="resize", delta=1)
    quick_mask_operation = texture_editor_selection_operation_state(empty, action="quick_mask", checked=True)
    feather_operation = texture_editor_selection_operation_state(selected, action="feather", feather_radius=6)
    invert_operation = texture_editor_selection_operation_state(selected, action="invert", checked=True)
    unknown_operation = texture_editor_selection_operation_state(selected, action="unknown")

    assert cleared.history_label == "Clear Selection"
    assert cleared.document.selection.mode == "none"
    assert selected_all.history_label == "Select All"
    assert selected_all.document.selection.mode == "rect"
    assert current_texture_editor_selection_bounds(selected_all.document) == (0, 0, 8, 8)
    assert grown is not None
    assert grown.history_label == "Grow Selection"
    assert shrunk is not None
    assert shrunk.history_label == "Shrink Selection"
    assert ignored_resize is None
    assert quick_mask.history_label == "Toggle Quick Mask"
    assert quick_mask.document.quick_mask_enabled is True
    assert feather_preview.selection.feather_radius == 4
    assert feather_commit.history_label == "Selection Feather"
    assert feather_commit.document.selection.feather_radius == 5
    assert inverted.history_label == "Invert Selection"
    assert inverted.document.selection.inverted is True
    assert clear_operation is not None
    assert clear_operation.history_label == "Clear Selection"
    assert select_all_operation is not None
    assert select_all_operation.history_label == "Select All"
    assert grow_operation is not None
    assert grow_operation.history_label == "Grow Selection"
    assert ignored_operation is None
    assert quick_mask_operation is not None
    assert quick_mask_operation.document.quick_mask_enabled is True
    assert feather_operation is not None
    assert feather_operation.document.selection.feather_radius == 6
    assert invert_operation is not None
    assert invert_operation.document.selection.inverted is True
    assert unknown_operation is None


def test_texture_editor_active_layer_selection_payload_helper_extracts_label_and_bounds() -> None:
    document = TextureEditorDocument(
        "doc",
        4,
        4,
        active_layer_id="layer",
        layers=(TextureEditorLayer("layer", "Paint", ""),),
        selection=TextureEditorSelection(mode="rect", rect=(1, 1, 2, 2)),
    )
    pixels = np.zeros((4, 4, 4), dtype=np.uint8)
    pixels[..., 0] = 10
    pixels[..., 3] = 255

    selection_state = texture_editor_active_layer_selection_payload_state(
        document,
        {"layer": pixels},
        current_layer_id=None,
    )

    assert selection_state is not None
    assert selection_state.label == "Paint"
    assert selection_state.bounds == (1, 1, 2, 2)
    assert selection_state.pixels.shape == (2, 2, 4)
    assert selection_state.pixels[..., 3].min() == 255
    assert texture_editor_active_layer_selection_payload_state(
        TextureEditorDocument("empty", 4, 4),
        {"layer": pixels},
        current_layer_id=None,
    ) is None


def test_texture_editor_clipboard_state_helpers_build_payloads_and_paste_state() -> None:
    document = TextureEditorDocument("doc", 10, 8)
    pixels = np.zeros((3, 4, 4), dtype=np.uint8)
    pixels[..., 3] = 255
    layer = TextureEditorLayer("layer", "Paint", "body.dds", offset_x=2, offset_y=3, blend_mode="screen")
    selected_document = TextureEditorDocument(
        "selected",
        6,
        6,
        active_layer_id="layer",
        layers=(TextureEditorLayer("layer", "Paint", ""),),
        selection=TextureEditorSelection(mode="rect", rect=(1, 2, 3, 2)),
    )
    selected_pixels = np.full((6, 6, 4), [1, 2, 3, 255], dtype=np.uint8)
    selection_state = texture_editor_active_layer_selection_payload_state(
        selected_document,
        {"layer": selected_pixels},
        current_layer_id=None,
    )

    layer_payload = texture_editor_layer_clipboard_payload(layer, pixels)
    layer_copy = texture_editor_layer_copy_clipboard_state(
        selected_document,
        {"layer": selected_pixels},
        current_layer_id=None,
    )
    missing_layer_copy = texture_editor_layer_copy_clipboard_state(
        selected_document,
        {},
        current_layer_id=None,
    )
    centered_origin = texture_editor_centered_paste_origin(document, pixels)
    layer_paste = texture_editor_layer_floating_paste_state(
        pixels,
        "Paint",
        offset_x=2,
        offset_y=3,
    )
    centered_layer_paste = texture_editor_layer_floating_paste_state(
        pixels,
        "Paint",
        offset_x=centered_origin[0],
        offset_y=centered_origin[1],
        centered=True,
    )
    assert selection_state is not None
    selection_payload = texture_editor_selection_clipboard_payload(selection_state)
    layer_clipboard_paste = texture_editor_clipboard_floating_paste_state(
        document,
        layer_clipboard=layer_payload,
        selection_clipboard=None,
        source="layer",
    )
    selection_clipboard_paste = texture_editor_clipboard_floating_paste_state(
        document,
        layer_clipboard=None,
        selection_clipboard=selection_payload,
        source="selection",
    )
    content_clipboard_paste = texture_editor_clipboard_floating_paste_state(
        document,
        layer_clipboard=layer_payload,
        selection_clipboard=selection_payload,
    )
    centered_content_paste = texture_editor_clipboard_floating_paste_state(
        document,
        layer_clipboard=layer_payload,
        selection_clipboard=selection_payload,
        centered=True,
    )
    missing_clipboard_paste = texture_editor_clipboard_floating_paste_state(
        document,
        layer_clipboard=None,
        selection_clipboard=None,
    )
    selection_paste = texture_editor_selection_floating_paste_state(
        selection_state.pixels,
        selection_state.label,
        offset_x=1,
        offset_y=2,
    )
    centered_selection_paste = texture_editor_selection_floating_paste_state(
        selection_state.pixels,
        selection_state.label,
        offset_x=centered_origin[0],
        offset_y=centered_origin[1],
        centered=True,
    )
    selection_to_layer = texture_editor_selection_to_layer_state(
        TextureEditorDocument(
            "target",
            10,
            8,
            selection=TextureEditorSelection(mode="rect", rect=(1, 2, 3, 2)),
        ),
        {},
        selection_state,
    )
    cut_state = texture_editor_cut_selection_to_floating_state(
        selected_document,
        {"layer": selected_pixels.copy()},
        selection_state,
        current_layer_id=None,
    )
    legacy_cut_state = texture_editor_cut_selection_to_floating_state(
        selected_document,
        {"layer": selected_pixels.copy()},
        selection_state,
        layer_id="layer",
        layer=selected_document.layers[0],
    )
    missing_cut_state = texture_editor_cut_selection_to_floating_state(
        selected_document,
        {"layer": selected_pixels.copy()},
        selection_state,
        current_layer_id="missing",
    )

    assert layer_payload[1:] == ("Paint", 2, 3, "screen")
    assert layer_payload[0] is not pixels
    assert layer_payload[0].shape == pixels.shape
    assert layer_copy.copied is True
    assert layer_copy.layer_clipboard is not None
    assert layer_copy.layer_clipboard[1] == "Paint"
    assert layer_copy.status_text == "Copied layer 'Paint'."
    assert missing_layer_copy.copied is False
    assert selection_payload[1:] == ("Paint", 1, 2)
    assert layer_clipboard_paste.can_paste is True
    assert layer_clipboard_paste.pixels is layer_payload[0]
    assert layer_clipboard_paste.paste_state == layer_paste
    assert selection_clipboard_paste.paste_state == selection_paste
    assert content_clipboard_paste.paste_state == selection_paste
    assert centered_content_paste.paste_state is not None
    assert centered_content_paste.paste_state.bounds == (3, 3, 3, 2)
    assert centered_content_paste.paste_state.paste_mode == "centered"
    assert missing_clipboard_paste.can_paste is False
    assert texture_editor_layer_floating_label("Paint") == "Paint Copy"
    assert texture_editor_selection_floating_label("Paint") == "Paint Selection"
    assert centered_origin == (3, 2)
    assert layer_paste.bounds == (2, 3, 4, 3)
    assert layer_paste.history_label == "Paste Layer Floating"
    assert layer_paste.status_text == "Pasted layer 'Paint Copy' as floating content."
    assert centered_layer_paste.paste_mode == "centered"
    assert centered_layer_paste.history_label == "Paste Centered Floating"
    assert selection_paste.bounds == (1, 2, 3, 2)
    assert selection_paste.history_label == "Paste Selection Floating"
    assert selection_paste.status_text == "Pasted selection as floating content from 'Paint'."
    assert centered_selection_paste.status_text == "Pasted selection as a centered layer from 'Paint'."
    assert texture_editor_layer_copy_status_text("Paint") == "Copied layer 'Paint'."
    assert texture_editor_selection_copy_status_text("Paint") == "Copied the current selection from 'Paint'."
    assert texture_editor_cut_selection_status_text() == "Cut selection into floating content."
    assert texture_editor_cut_selection_missing_status_text() == "Create a selection first, then use Cut."
    assert texture_editor_copy_selection_to_layer_status_text().startswith("Copied selection to a new layer.")
    assert (
        texture_editor_copy_selection_to_layer_missing_status_text()
        == "Create a selection first, then use Copy To New Layer."
    )
    assert texture_editor_copy_selection_to_layer_history_label() == "Copy Selection To Layer"
    assert selection_to_layer.document.selection.mode == "none"
    assert selection_to_layer.document.active_layer_id == selection_to_layer.layer_id
    assert selection_to_layer.document.layers[-1].name == "Paint Selection"
    assert selection_to_layer.document.layers[-1].offset_x == 1
    assert selection_to_layer.document.layers[-1].offset_y == 2
    assert selection_to_layer.layer_pixels[selection_to_layer.layer_id].shape == selection_state.pixels.shape
    assert selection_to_layer.selection_clipboard[1:] == ("Paint", 1, 2)
    assert selection_to_layer.history_label == "Copy Selection To Layer"
    assert selection_to_layer.status_text.startswith("Copied selection to a new layer.")
    assert cut_state is not None
    assert cut_state.document.selection.mode == "none"
    assert cut_state.document.floating_selection is not None
    assert cut_state.document.floating_selection.label == "Paint Selection"
    assert cut_state.document.floating_selection.bounds == (1, 2, 3, 2)
    assert cut_state.document.layers[0].revision == 1
    assert cut_state.layer_pixels["layer"][2, 1, 3] == 0
    assert cut_state.layer_pixels["layer"][0, 0, 3] == 255
    assert cut_state.before_layer_pixels["layer"][2, 1, 3] == 255
    assert cut_state.selection_clipboard[1:] == ("Paint", 1, 2)
    assert cut_state.floating_pixels.shape == selection_state.pixels.shape
    assert cut_state.floating_mask.shape == selection_state.pixels.shape[:2]
    assert cut_state.dirty_bounds == (1, 2, 3, 2)
    assert cut_state.history_label == "Cut Selection To Floating"
    assert cut_state.status_text == "Cut selection into floating content."
    assert cut_state.kind == "floating_cut"
    assert cut_state.tracked_layer_ids == ("layer",)
    assert legacy_cut_state is not None
    assert legacy_cut_state.layer_id == "layer"
    assert missing_cut_state is None


def test_texture_editor_tool_visibility_helpers_cover_conditional_rows() -> None:
    paint = texture_editor_tool_setting_visibility("paint", brush_tip="image_stamp")
    lasso = texture_editor_tool_setting_visibility("lasso", lasso_snap_enabled=True)
    recolor = texture_editor_tool_setting_visibility("recolor")
    selection = texture_editor_tool_setting_visibility("move", has_active_selection=True)
    clone_settings = TextureEditorToolSettings(tool="clone", clone_source_point=(3, 4))
    preserved_clone = texture_editor_active_tool_state(clone_settings, "heal")
    cleared_clone = texture_editor_active_tool_state(clone_settings, "paint")
    clone_source = normalized_texture_editor_clone_source_point(("5", 6.2))
    picked_clone_source = texture_editor_clone_source_picked_state(clone_settings, ("8", 9.8))
    cleared_clone_source = texture_editor_clone_source_cleared_state(clone_settings)
    control_settings = texture_editor_tool_settings_from_controls(
        clone_settings,
        TextureEditorToolControlSnapshot(
            color_hex="",
            secondary_color_hex="",
            brush_preset="detail",
            brush_tip="flat",
            brush_pattern="grain",
            custom_brush_tip_path=" stamp.png ",
            symmetry_mode="mirror_x",
            size="12.5",
            hardness="75",
            roundness="91",
            angle_degrees="-10",
            recolor_source_hex="",
            recolor_target_hex="",
        ),
    )
    brush_visual = texture_editor_brush_visual_state(control_settings)
    stroke_state = texture_editor_stroke_payload_state({"tool": "move", "points": [(1, 2), (6.9, 5.2)]}, "paint")
    stroke_settings = texture_editor_tool_settings_for_stroke(clone_settings, "heal")
    active_snapshot_settings = TextureEditorToolSettings(tool="smudge", sample_visible_layers=False)
    visible_snapshot_settings = TextureEditorToolSettings(tool="sharpen", sample_visible_layers=True)
    blocked_filter_settings = TextureEditorToolSettings(tool="soften", sample_visible_layers=False)
    patch_settings = TextureEditorToolSettings(tool="patch")
    snapshot_document = TextureEditorDocument(
        "doc",
        2,
        2,
        active_layer_id="paint",
        layers=(TextureEditorLayer("paint", "Paint", ""),),
    )
    snapshot_pixels = {"paint": np.zeros((2, 2, 4), dtype=np.uint8)}
    snapshot_pixels["paint"][0, 0] = [90, 80, 70, 255]
    active_snapshot = texture_editor_stroke_source_snapshot(
        snapshot_document,
        snapshot_pixels,
        active_snapshot_settings,
        snapshot_pixels["paint"],
    )
    visible_snapshot = texture_editor_stroke_source_snapshot(
        snapshot_document,
        snapshot_pixels,
        visible_snapshot_settings,
        snapshot_pixels["paint"],
    )
    no_snapshot = texture_editor_stroke_source_snapshot(
        snapshot_document,
        snapshot_pixels,
        TextureEditorToolSettings(tool="paint"),
        snapshot_pixels["paint"],
    )
    before_pixels = np.array([[[1, 2, 3, 4], [10, 20, 30, 40]]], dtype=np.uint8)
    recolored_pixels = np.array([[[101, 102, 103, 104], [110, 120, 130, 140]]], dtype=np.uint8)
    locked_recolor = texture_editor_recolor_pixels_with_channel_locks(
        recolored_pixels.copy(),
        before_pixels,
        edit_red_channel=False,
        edit_green_channel=True,
        edit_blue_channel=False,
        edit_alpha_channel=True,
        alpha_locked=True,
    )
    recolor_state = texture_editor_recolor_control_state(
        mode="",
        source_color="",
        target_color="",
        tolerance=400,
        strength=0,
        preserve_luminance=False,
    )
    recolor_document = TextureEditorDocument(
        "doc",
        2,
        1,
        active_layer_id="paint",
        layers=(TextureEditorLayer("paint", "Paint", "", alpha_locked=True),),
        selection=TextureEditorSelection(mode="rect", rect=(0, 0, 1, 1)),
        edit_red_channel=False,
        edit_green_channel=True,
        edit_blue_channel=True,
        edit_alpha_channel=True,
    )
    recolor_pixels = {
        "paint": np.array(
            [[[20, 30, 40, 50], [60, 70, 80, 90]]],
            dtype=np.uint8,
        )
    }
    recolor_layer = texture_editor_recolor_layer_state(
        recolor_document,
        recolor_pixels,
        dataclasses.replace(
            TextureEditorToolSettings(tool="recolor"),
            recolor_target_hex="#FF0000",
            recolor_strength=100,
            recolor_preserve_luminance=False,
        ),
        layer_id="paint",
        dirty_bounds=(0, 0, 1, 1),
    )
    quick_mask_document = TextureEditorDocument("doc", 3, 3)
    quick_mask_state = texture_editor_quick_mask_stroke_state(
        quick_mask_document,
        TextureEditorToolSettings(tool="fill"),
        [(1, 1)],
    )
    blocked_quick_mask_state = texture_editor_quick_mask_stroke_state(
        quick_mask_document,
        TextureEditorToolSettings(tool="clone"),
        [(1, 1)],
    )
    layer_stroke_document = TextureEditorDocument(
        "doc",
        2,
        2,
        active_layer_id="paint",
        layers=(TextureEditorLayer("paint", "Paint", ""),),
    )
    layer_stroke_pixels = {"paint": np.zeros((2, 2, 4), dtype=np.uint8)}
    layer_stroke = texture_editor_layer_stroke_state(
        layer_stroke_document,
        layer_stroke_pixels,
        TextureEditorToolSettings(tool="fill", color_hex="#112233", fill_contiguous=False),
        [(0, 0)],
        layer_id="paint",
        editing_mask_target=False,
        selection_bounds=(0, 0, 1, 1),
        layer_canvas_bounds=(0, 0, 2, 2),
        brush_dirty_bounds=(0, 0, 1, 1),
    )
    missing_layer_stroke = texture_editor_layer_stroke_state(
        layer_stroke_document,
        layer_stroke_pixels,
        TextureEditorToolSettings(tool="fill"),
        [(0, 0)],
        layer_id="missing",
        editing_mask_target=False,
        selection_bounds=None,
        layer_canvas_bounds=(0, 0, 2, 2),
        brush_dirty_bounds=(0, 0, 1, 1),
    )

    assert paint.rows["brush_preset"] is True
    assert paint.rows["custom_brush_tip"] is True
    assert lasso.rows["lasso_snap_to_edges"] is True
    assert lasso.rows["lasso_snap_radius"] is True
    assert lasso.selection_section_visible is True
    assert recolor.rows["recolor_apply"] is True
    assert recolor.rows["brush_preset"] is False
    assert selection.selection_section_visible is True
    assert preserved_clone.settings.tool == "heal"
    assert preserved_clone.clone_source_point == (3, 4)
    assert cleared_clone.settings.tool == "paint"
    assert cleared_clone.clone_source_point is None
    assert clone_source == (5, 6)
    assert normalized_texture_editor_clone_source_point([5, 6]) is None
    assert normalized_texture_editor_clone_source_point((5, 6, 7)) is None
    assert picked_clone_source is not None
    assert picked_clone_source.settings.clone_source_point == (8, 9)
    assert picked_clone_source.clone_source_point == (8, 9)
    assert texture_editor_clone_source_picked_status_text(picked_clone_source.clone_source_point) == "Clone source set to (8, 9)."
    assert texture_editor_clone_source_picked_state(clone_settings, [8, 9]) is None
    assert cleared_clone_source.settings.clone_source_point is None
    assert cleared_clone_source.clone_source_point is None
    assert texture_editor_clone_source_cleared_status_text() == "Clone/heal source cleared."
    assert control_settings.tool == "clone"
    assert control_settings.clone_source_point == (3, 4)
    assert control_settings.color_hex == "#C85A30"
    assert control_settings.secondary_color_hex == "#FFFFFF"
    assert control_settings.custom_brush_tip_path == "stamp.png"
    assert control_settings.brush_tip == "flat"
    assert control_settings.size == 12.5
    assert brush_visual.pattern == "grain"
    assert brush_visual.symmetry_mode == "mirror_x"
    assert stroke_state is not None
    assert stroke_state.tool == "move"
    assert texture_editor_stroke_payload_state({"tool": "recolor", "points": [(1, 1)]}, "paint") is None
    assert texture_editor_stroke_payload_state({"points": []}, "paint") is None
    assert texture_editor_move_delta(stroke_state.points) == (5, 3)
    assert texture_editor_move_delta([(1, 2), (1, 2)]) is None
    assert stroke_settings.tool == "heal"
    assert stroke_settings.clone_source_point == (3, 4)
    assert texture_editor_quick_mask_tool_allowed("fill") is True
    assert texture_editor_quick_mask_tool_allowed("clone") is False
    assert texture_editor_quick_mask_tool_status().startswith("Quick Mask editing")
    assert texture_editor_clone_source_required(TextureEditorToolSettings(tool="clone")) is True
    assert texture_editor_clone_source_required(stroke_settings) is False
    assert texture_editor_clone_source_required_status().startswith("Set a clone/heal source")
    assert texture_editor_recolor_settings_loaded_status_text().startswith("Recolor settings loaded.")
    assert texture_editor_recolor_layer_history_label() == "Recolor Layer"
    assert texture_editor_stroke_source_snapshot_mode(active_snapshot_settings) == "active_layer"
    assert texture_editor_stroke_source_snapshot_mode(visible_snapshot_settings) == "visible_layers"
    assert texture_editor_stroke_source_snapshot_mode(TextureEditorToolSettings(tool="paint")) == "none"
    assert active_snapshot is not None
    assert active_snapshot is not snapshot_pixels["paint"]
    assert active_snapshot[0, 0].tolist() == [90, 80, 70, 255]
    assert visible_snapshot is not None
    assert visible_snapshot[0, 0].tolist() == [90, 80, 70, 255]
    assert no_snapshot is None
    assert texture_editor_layer_has_visible_pixels(snapshot_pixels["paint"]) is True
    assert texture_editor_layer_has_visible_pixels(np.zeros((1, 1, 4), dtype=np.uint8)) is False
    assert texture_editor_layer_has_visible_pixels(None) is False
    assert texture_editor_empty_active_layer_filter_blocked(
        blocked_filter_settings,
        active_layer_exists=True,
        active_layer_has_visible_pixels=False,
    ) is True
    assert texture_editor_empty_active_layer_filter_blocked(
        blocked_filter_settings,
        active_layer_exists=False,
        active_layer_has_visible_pixels=False,
    ) is False
    assert texture_editor_empty_active_layer_filter_status().startswith("The active layer is empty")
    assert texture_editor_patch_selection_required(patch_settings, "none") is True
    assert texture_editor_patch_selection_required(patch_settings, "rect") is False
    assert texture_editor_patch_selection_required_status().startswith("Create a selection first")
    assert locked_recolor[0, 0].tolist() == [1, 102, 3, 4]
    assert locked_recolor[0, 1].tolist() == [10, 120, 30, 40]
    assert recolor_state.mode == "tint"
    assert recolor_state.source_color == "#808080"
    assert recolor_state.target_color == "#C85A30"
    assert recolor_state.tolerance == 255
    assert recolor_state.strength == 1
    assert recolor_state.preserve_luminance is False
    assert recolor_layer is not None
    assert recolor_layer.layer_pixels["paint"][0, 0, 0] == 20
    assert recolor_layer.layer_pixels["paint"][0, 0, 1] == 0
    assert recolor_layer.layer_pixels["paint"][0, 0, 2] == 0
    assert recolor_layer.layer_pixels["paint"][0, 0, 3] == 50
    assert recolor_layer.layer_pixels["paint"][0, 1].tolist() == [60, 70, 80, 90]
    assert recolor_layer.before_layer_pixels["paint"][0, 0].tolist() == [20, 30, 40, 50]
    assert recolor_layer.document.layers[0].revision == 1
    assert recolor_layer.history_label == "Recolor Layer"
    assert recolor_layer.kind == "recolor_stroke"
    assert recolor_layer.tracked_layer_ids == ("paint",)
    assert recolor_layer.dirty_bounds == (0, 0, 1, 1)
    assert quick_mask_state is not None
    assert quick_mask_state.document.quick_mask_enabled is True
    assert quick_mask_state.document.composite_revision == quick_mask_document.composite_revision + 1
    assert quick_mask_state.history_label == "Quick Mask Fill"
    assert quick_mask_state.kind == "selection_update"
    assert quick_mask_state.tracked_layer_ids == ()
    assert blocked_quick_mask_state is None
    assert layer_stroke is not None
    assert layer_stroke.document.layers[0].revision == 1
    assert layer_stroke.layer_id == "paint"
    assert layer_stroke.thumbnail_layer_id == "paint"
    assert layer_stroke.dirty_bounds == (0, 0, 1, 1)
    assert layer_stroke.before_layer_pixels["paint"][0, 0].tolist() == [0, 0, 0, 0]
    assert layer_stroke.history_label == "Fill"
    assert layer_stroke.kind == "fill_stroke"
    assert layer_stroke.tracked_layer_ids == ("paint",)
    assert missing_layer_stroke is None
    assert texture_editor_recolor_layer_state(
        recolor_document,
        recolor_pixels,
        TextureEditorToolSettings(tool="recolor"),
        layer_id="missing",
        dirty_bounds=None,
    ) is None


def test_texture_editor_layer_label_helper_includes_flags_and_offset() -> None:
    label = texture_editor_layer_list_label(
        TextureEditorLayer(
            "layer",
            "Paint",
            "",
            visible=False,
            blend_mode="overlay",
            offset_x=2,
            offset_y=-3,
            locked=True,
            alpha_locked=True,
            mask_layer_id="mask",
            mask_enabled=True,
        )
    )

    assert label == "[Hidden] Paint  Overlay  @2,-3  Mask  Lock  Alpha"


def test_texture_editor_layer_thumbnail_cache_keys_filter_by_layer_id() -> None:
    cache_keys = (("layer", 1), ("other", 1), ("layer", 2))
    document = TextureEditorDocument("doc", 4, 4, active_layer_id="layer")

    assert texture_editor_layer_thumbnail_cache_keys("layer", cache_keys) == (("layer", 1), ("layer", 2))
    assert texture_editor_layer_thumbnail_cache_keys("missing", cache_keys) == ()
    assert texture_editor_layer_refresh_selection_id(document, "other") == "other"
    assert texture_editor_layer_refresh_selection_id(document, None) == "layer"
    assert texture_editor_layer_refresh_selection_id(None, "layer") == ""


def test_texture_editor_transform_control_state_tracks_floating_selection() -> None:
    floating = TextureEditorFloatingSelection(scale_x=1.25, scale_y=0.5, rotation_degrees=33.6)
    document = TextureEditorDocument("doc", 8, 8, active_layer_id="layer", floating_selection=floating)

    empty = texture_editor_transform_controls_state(None)
    state = texture_editor_transform_controls_state(document)
    applied = texture_editor_applied_floating_transform_state(document, scale_percent=80, rotation_degrees=-15)
    flipped = texture_editor_flipped_floating_transform_state(document, flip_x=True, flip_y=False)
    rotated = texture_editor_rotated_floating_transform_state(document, degrees=90)
    canvas_move = texture_editor_canvas_floating_transform_state(
        document,
        {
            "offset_x": 3,
            "offset_y": -2,
            "scale_x": 0.25,
            "scale_y": 0.4,
            "rotation_degrees": 12,
            "mode": "scale_ne",
            "commit": True,
        },
    )
    unchanged_canvas_move = texture_editor_canvas_floating_transform_state(
        document,
        {
            "offset_x": 0,
            "offset_y": 0,
            "scale_x": 1.25,
            "scale_y": 0.5,
            "rotation_degrees": 33.6,
            "commit": True,
        },
    )

    assert empty.floating_controls_enabled is False
    assert empty.scale_percent == 100
    assert state.floating_controls_enabled is True
    assert state.float_layer_enabled is True
    assert state.scale_percent == 125
    assert state.rotation_degrees == 34
    assert applied is not None
    assert applied.document.floating_selection is not None
    assert applied.document.floating_selection.scale_x == 0.8
    assert applied.document.floating_selection.scale_y == 0.8
    assert applied.document.floating_selection.rotation_degrees == -15
    assert applied.document.floating_selection.committed is False
    assert applied.history_label == "Transform Floating Selection"
    assert flipped is not None
    assert flipped.document.floating_selection is not None
    assert flipped.document.floating_selection.flip_x is True
    assert flipped.document.floating_selection.flip_y is False
    assert flipped.history_label == "Flip Floating Selection"
    assert rotated is not None
    assert rotated.document.floating_selection is not None
    assert abs(rotated.document.floating_selection.rotation_degrees - 123.6) < 1e-6
    assert rotated.history_label == "Rotate Floating Selection"
    assert canvas_move is not None
    assert canvas_move.changed is True
    assert canvas_move.commit is True
    assert canvas_move.history_label == "Scale Floating Selection"
    assert canvas_move.document.floating_selection is not None
    assert canvas_move.document.floating_selection.offset_x == 3
    assert canvas_move.document.floating_selection.offset_y == -2
    assert canvas_move.document.floating_selection.scale_x == 0.25
    assert canvas_move.document.floating_selection.scale_y == 0.4
    assert canvas_move.document.floating_selection.rotation_degrees == 12
    assert unchanged_canvas_move is not None
    assert unchanged_canvas_move.changed is False
    assert unchanged_canvas_move.commit is True
    assert texture_editor_canvas_floating_transform_state(None, {}) is None
    assert texture_editor_floating_transform_dirty_bounds((1, 2, 3, 4), (0, 3, 5, 2)) == (0, 2, 5, 4)
    assert texture_editor_floating_transform_dirty_bounds(None, (0, 0, 1, 1)) is None


def test_texture_editor_channel_control_state_tracks_document_busy_and_clipboard() -> None:
    document = TextureEditorDocument(
        "doc",
        8,
        8,
        active_layer_id="layer",
        selection=TextureEditorSelection(mode="rect", rect=(0, 0, 2, 2)),
        edit_green_channel=False,
        edit_alpha_channel=False,
    )

    enabled = texture_editor_channel_controls_state(
        document,
        current_layer_id=None,
        busy=False,
        has_clipboard=True,
    )
    busy = texture_editor_channel_controls_state(
        document,
        current_layer_id=None,
        busy=True,
        has_clipboard=True,
    )

    assert enabled.channel_values == (True, False, True, False)
    assert enabled.extract_enabled is True
    assert enabled.selection_to_enabled is True
    assert enabled.paste_enabled is True
    assert busy.extract_enabled is False
    assert busy.paste_enabled is False


def test_texture_editor_selection_controls_state_tracks_mask_and_busy_state() -> None:
    document = TextureEditorDocument(
        "doc",
        8,
        8,
        active_layer_id="layer",
        layers=(TextureEditorLayer("layer", "Layer", "", mask_layer_id="mask"),),
        selection=TextureEditorSelection(mode="rect", rect=(0, 0, 2, 2), inverted=True, feather_radius=3),
        quick_mask_enabled=True,
    )

    controls = texture_editor_selection_controls_state(
        document,
        current_tool="paint",
        current_layer_id=None,
        layer_pixel_ids={"mask"},
        busy=False,
    )
    busy = texture_editor_selection_controls_state(
        document,
        current_tool="paint",
        current_layer_id=None,
        layer_pixel_ids={"mask"},
        busy=True,
    )

    assert controls.inverted is True
    assert controls.feather_radius == 3
    assert controls.quick_mask_enabled is True
    assert controls.copy_layer_enabled is True
    assert controls.clear_enabled is True
    assert controls.to_mask_enabled is True
    assert controls.from_mask_enabled is True
    assert busy.copy_layer_enabled is False
    assert busy.from_mask_enabled is False


def test_texture_editor_source_binding_helpers_infer_package_paths() -> None:
    png_root = (Path.cwd() / "virtual_png_root").resolve()
    source_path = png_root / "0001" / "textures" / "foo.dds"

    binding = build_texture_editor_source_binding(
        source_path,
        launch_origin="file",
        png_root=png_root,
        original_root=None,
    )

    assert configured_texture_editor_root_path(lambda: str(png_root)) == png_root.resolve()
    assert binding.display_name == "foo.dds"
    assert binding.relative_path == "0001/textures/foo.dds"
    assert binding.package_root == "0001"
    assert binding.archive_relative_path == "textures/foo.dds"
    assert binding.original_dds_path == str(source_path.resolve())

    archive_document = TextureEditorDocument("doc", 4, 4, source_binding=binding)
    fallback_binding = dataclasses.replace(binding, archive_relative_path="", relative_path="0001/ui/icon.dds")
    fallback_document = TextureEditorDocument("doc", 4, 4, source_binding=fallback_binding)
    compare_state = texture_editor_compare_request_state(fallback_document)
    missing_compare_state = texture_editor_compare_request_state(TextureEditorDocument("doc", 4, 4))

    assert texture_editor_browse_archive_request_path(archive_document) == "textures/foo.dds"
    assert texture_editor_browse_archive_request_path(fallback_document) == "ui/icon.dds"
    assert texture_editor_existing_source_status_text(Path("C:/textures/body.dds")) == "body.dds is already open in Texture Editor."
    assert texture_editor_open_source_history_label() == "Open Document"
    assert texture_editor_open_source_status_text(Path("C:/textures/body.dds")) == "Opened body.dds in Texture Editor."
    assert texture_editor_open_source_task_label(Path("C:/textures/body.dds")) == "Opening body.dds in Texture Editor..."
    assert compare_state.can_request is True
    assert compare_state.relative_path == "0001/ui/icon.dds"
    assert compare_state.binding is not fallback_binding
    assert missing_compare_state.can_request is False
    assert "relative game path" in missing_compare_state.status_text


def test_texture_editor_export_state_helpers_build_paths_and_document_state(tmp_path: Path) -> None:
    save_dir = Path.cwd() / "virtual_save_dir"
    workspace_root = Path.cwd() / "virtual_workspace"
    document = TextureEditorDocument(
        "Paint Job",
        4,
        4,
        workspace_root=workspace_root,
        source_binding=TextureEditorSourceBinding(
            archive_relative_path="textures/armor/body_d.dds",
            relative_path="0001/textures/armor/body_d.dds",
            source_path="C:/source/fallback.dds",
        ),
    )
    project_document = dataclasses.replace(document, project_path=save_dir / "custom.ctfedit.json")

    selection_path = texture_editor_selection_region_default_path(document, str(save_dir))
    default_workspace = texture_editor_default_workspace_root(tmp_path)
    updated_document = texture_editor_document_with_last_flattened_output(document, save_dir / "flat.png")
    handoff_binding = texture_editor_handoff_source_binding(document)
    delivery = texture_editor_handoff_delivery_state("texture_workflow", save_dir / "out.png", handoff_binding)
    unknown_delivery = texture_editor_handoff_delivery_state("custom", save_dir / "out.png", handoff_binding)

    assert selection_path == (save_dir / "Paint Job_selection.png").resolve()
    assert texture_editor_project_default_path(document, str(save_dir)) == save_dir / "Paint Job.ctfedit.json"
    assert texture_editor_project_default_path(project_document, str(save_dir)) == save_dir / "custom.ctfedit.json"
    assert texture_editor_flattened_png_default_path(document, str(save_dir)) == save_dir / "Paint Job.png"
    assert default_workspace == tmp_path / "workspace" / "texture_editor_projects"
    assert default_workspace.exists()
    assert texture_editor_workspace_exports_root(document, Path("fallback")) == workspace_root / "exports"
    assert texture_editor_workspace_png_stem(document, "replace_assistant") == "body_d"
    assert texture_editor_workspace_png_stem(document, "texture_workflow") == "Paint Job_texture_workflow"
    assert texture_editor_workspace_png_stem(None, "replace_assistant") == "texture_editor_replace_assistant"
    assert texture_editor_workspace_png_path(document, Path("fallback"), "item_icons") == workspace_root / "exports" / "Paint Job_item_icons.png"
    assert updated_document.last_flattened_png_path == str(save_dir / "flat.png")
    assert document.last_flattened_png_path == ""
    assert handoff_binding == document.source_binding
    assert handoff_binding is not document.source_binding
    assert delivery.target == "texture_workflow"
    assert delivery.output_path == save_dir / "out.png"
    assert delivery.source_binding == handoff_binding
    assert delivery.emit_replace_assistant is False
    assert delivery.emit_texture_workflow is True
    assert delivery.emit_item_icons is False
    assert delivery.status_text == "Preparing Texture Workflow handoff: out.png"
    assert unknown_delivery.status_text == "Exported flattened PNG: out.png"
    assert texture_editor_handoff_export_suffix("texture_workflow") == "texture_workflow"
    assert texture_editor_handoff_status_text("replace_assistant", save_dir / "out.png") == "Sent flattened PNG to Texture Replacer: out.png"
    assert texture_editor_handoff_status_text("texture_workflow", save_dir / "out.png") == "Preparing Texture Workflow handoff: out.png"
    assert texture_editor_handoff_status_text("item_icons", save_dir / "out.png") == "Sent flattened PNG to Icon Creator: out.png"
    assert texture_editor_existing_project_status_text(save_dir / "custom.ctfedit.json") == "Project custom.ctfedit.json is already open."
    assert texture_editor_open_project_history_label() == "Open Project"
    assert texture_editor_open_project_status_text(save_dir / "custom.ctfedit.json") == "Opened project custom.ctfedit.json."
    assert texture_editor_open_project_task_label(save_dir / "custom.ctfedit.json") == "Opening project custom.ctfedit.json..."
    assert texture_editor_save_project_status_text(save_dir / "custom.ctfedit.json") == f"Saved project to {save_dir / 'custom.ctfedit.json'}."
    assert texture_editor_save_project_task_label(save_dir / "custom.ctfedit.json") == "Saving project custom.ctfedit.json..."
    assert texture_editor_flattened_png_status_text(save_dir / "flat.png") == f"Saved flattened PNG to {save_dir / 'flat.png'}."
    assert texture_editor_flattened_png_task_label(save_dir / "flat.png") == "Saving flattened PNG to flat.png..."
    assert texture_editor_workspace_export_task_label("replace_assistant") == "Exporting replace assistant PNG..."
    assert texture_editor_selection_region_missing_status_text() == "Create a selection first, then use Export Selection Region."
    assert texture_editor_selection_region_status_text(save_dir / "selection.png") == "Exported selection region to selection.png."
    assert texture_editor_selection_region_task_label() == "Exporting selection region PNG..."
    assert texture_editor_grid_slices_status_text(save_dir / "slices", 4) == "Exported 4 grid slice(s) to slices."
    assert texture_editor_grid_slices_task_label() == "Exporting atlas grid slices..."


def test_texture_editor_export_tasks_copy_and_write_files(tmp_path: Path) -> None:
    document = TextureEditorDocument(
        "Task Export",
        2,
        2,
        workspace_root=tmp_path / "workspace",
        active_layer_id="base",
        layers=(TextureEditorLayer("base", "Base", ""),),
    )
    pixels = np.zeros((2, 2, 4), dtype=np.uint8)
    pixels[..., 0] = 32
    pixels[..., 3] = 255
    layer_pixels = {"base": pixels}

    snapshot = copy_texture_editor_layer_pixels(layer_pixels)
    pixels[0, 0] = [0, 0, 0, 0]
    flattened_path = export_texture_editor_flattened_png_task(document, snapshot, tmp_path / "flat.png")
    region_path = export_texture_editor_region_png_task(
        document,
        snapshot,
        tmp_path / "region.png",
        (0, 0, 1, 1),
        padding=0,
        trim_transparent=False,
    )
    grid_paths = export_texture_editor_grid_slices_task(
        document,
        snapshot,
        tmp_path / "slices",
        cell_size=1,
        padding=0,
        trim_transparent=False,
        skip_empty=True,
    )
    workspace_path = export_texture_editor_workspace_png_task(document, snapshot, tmp_path / "fallback", "item_icons")
    saved_document = save_texture_editor_project_task(document, snapshot, tmp_path / "project.ctfedit.json")
    opened_document, opened_pixels = create_texture_editor_source_document_task(
        flattened_path,
        texconv_path=None,
        workspace_root=tmp_path / "open-workspace",
        binding=TextureEditorSourceBinding(launch_origin="file"),
    )

    assert snapshot["base"][0, 0].tolist() == [32, 0, 0, 255]
    assert flattened_path == (tmp_path / "flat.png").resolve()
    assert flattened_path.exists()
    assert region_path == (tmp_path / "region.png").resolve()
    assert region_path.exists()
    assert isinstance(grid_paths, list)
    assert len(grid_paths) == 4
    assert workspace_path == tmp_path / "workspace" / "exports" / "Task Export_item_icons.png"
    assert workspace_path.exists()
    assert saved_document.project_path == (tmp_path / "project.ctfedit.json").resolve()
    assert saved_document.project_path.exists()
    assert opened_document.title == "flat"
    assert opened_document.width == 2
    assert opened_pixels[opened_document.active_layer_id].shape == (2, 2, 4)


def test_texture_editor_metadata_helpers_escape_values_and_combine_warnings() -> None:
    document = TextureEditorDocument(
        "doc <unsafe>",
        4,
        2,
        source_binding=TextureEditorSourceBinding(
            launch_origin="archive",
            source_path="C:/source/foo.png",
            relative_path="0001/ui/foo.png",
            package_root="0001",
            original_dds_path="C:/source/foo.dds",
            texture_type="ui",
            semantic_subtype="icon",
        ),
        technical_warning="warn",
    )
    html = texture_editor_metadata_html(document)
    empty_display = texture_editor_metadata_display_state(None)
    warning_display = texture_editor_metadata_display_state(document, ui_constraint_warning="constraint")

    assert texture_editor_combined_warning("warn", "constraint") == "warn\nconstraint"
    assert "doc &lt;unsafe&gt;" in html
    assert "0001/ui/foo.png" in html
    assert "ui/icon" in html
    assert empty_display.html == "<p>No document open.</p>"
    assert empty_display.warning_visible is False
    assert warning_display.warning_text == "warn\nconstraint"
    assert warning_display.warning_visible is True
    assert "doc &lt;unsafe&gt;" in warning_display.html


def test_texture_editor_zoom_color_and_nudge_helpers() -> None:
    fit = texture_editor_zoom_labels(1.25, fit_to_view=True, has_document=True)
    free = texture_editor_zoom_labels(0.5, fit_to_view=False, has_document=True)
    empty = texture_editor_zoom_labels(1.0, fit_to_view=False, has_document=False)

    assert fit.zoom_label == "Fit 125%"
    assert fit.canvas_status_zoom_label == "Zoom Fit 125%"
    assert free.zoom_label == "50%"
    assert free.canvas_status_zoom_label == "Zoom 50%"
    assert empty.canvas_status_zoom_label == "No zoom"
    assert texture_editor_sampled_color_status("#ABCDEF") == "Sampled color #ABCDEF."
    assert texture_editor_busy_status_text().startswith("Texture Editor is already busy.")
    assert texture_editor_task_failed_status_text("") == "Texture Editor task failed."
    assert texture_editor_task_failed_status_text("Save Project") == "Save Project failed."
    assert nudged_texture_editor_brush_size(10, 1, minimum=1, maximum=20, size_step_mode="fine") == 11
    assert nudged_texture_editor_brush_size(18, 1, minimum=1, maximum=20, size_step_mode="normal") == 20
    assert nudged_texture_editor_brush_hardness(3, -1, minimum=0, maximum=100) == 0
    assert nudged_texture_editor_brush_hardness(96, 1, minimum=0, maximum=100) == 100


def test_texture_editor_channel_lock_status_text() -> None:
    document = TextureEditorDocument("doc", 4, 4)
    update_state = texture_editor_channel_lock_update_state(
        document,
        red=True,
        green=False,
        blue=True,
        alpha=False,
    )
    assert texture_editor_channel_lock_status_text(red=True, green=False, blue=True, alpha=False) == "Channel edit locks: R-B-"
    assert update_state.document.edit_red_channel is True
    assert update_state.document.edit_green_channel is False
    assert update_state.document.edit_blue_channel is True
    assert update_state.document.edit_alpha_channel is False
    assert update_state.status_text == "Channel edit locks: R-B-"
    assert texture_editor_normalized_channel_key(None, "alpha") == "alpha"
    assert texture_editor_normalized_channel_key("red", "alpha") == "red"
    assert texture_editor_channel_operation_history_label("extract", "green") == "Extract Green Channel"
    assert texture_editor_channel_operation_history_label("swap", "red", other_channel_key="blue") == "Swap Red / Blue"
    assert texture_editor_channel_operation_status_text("copy", "alpha") == "Copied the Alpha channel to the editor clipboard."
    assert (
        texture_editor_channel_operation_status_text("swap", "red", other_channel_key="blue")
        == "Swapped the Red and Blue channels."
    )
    assert texture_editor_channel_selection_required_status_text() == "Create a selection first, then write it to a channel."
    assert texture_editor_same_channel_swap_status("red", "red") == "Choose two different channels to swap."
    assert texture_editor_same_channel_swap_status("red", "blue") == ""
    locked = TextureEditorLayer("layer", "Layer", "", alpha_locked=True)
    unlocked = TextureEditorLayer("layer", "Layer", "", alpha_locked=False)

    assert texture_editor_channel_alpha_lock_blocked(locked, channel_keys=("red", "alpha")) is True
    assert texture_editor_channel_alpha_lock_blocked(locked, channel_keys=("red", "blue")) is False
    assert texture_editor_channel_alpha_lock_blocked(unlocked, channel_keys=("alpha",)) is False
    assert texture_editor_channel_alpha_lock_message("paste") == "Unlock alpha before pasting into the alpha channel."
    assert texture_editor_channel_alpha_lock_message("unknown") == "Unlock alpha before editing the alpha channel."


def test_texture_editor_channel_operation_states_update_documents_and_pixels() -> None:
    layer = TextureEditorLayer("paint", "Paint", "", offset_x=0, offset_y=0)
    document = TextureEditorDocument(
        "doc",
        2,
        2,
        active_layer_id="paint",
        layers=(layer,),
        selection=TextureEditorSelection(mode="rect", rect=(0, 0, 1, 1)),
    )
    pixels = np.array(
        [
            [[10, 20, 30, 40], [50, 60, 70, 80]],
            [[90, 100, 110, 120], [130, 140, 150, 160]],
        ],
        dtype=np.uint8,
    )
    layer_pixels = {"paint": pixels}

    extracted = texture_editor_extracted_channel_layer_state(
        document,
        layer_pixels,
        layer_id="paint",
        layer=layer,
        channel_key="red",
    )
    luma = texture_editor_luma_to_channel_state(document, layer_pixels, layer_id="paint", channel_key="alpha")
    channel_selection = texture_editor_channel_to_selection_state(
        TextureEditorDocument("doc", 2, 2, active_layer_id="paint", layers=(layer,)),
        layer,
        pixels,
        channel_key="alpha",
        mask_pixels=None,
        combine_mode="replace",
    )
    selection_write = texture_editor_selection_to_channel_state(
        document,
        layer_pixels,
        layer_id="paint",
        layer=layer,
        channel_key="green",
    )
    clipboard = texture_editor_channel_clipboard_state(pixels, channel_key="alpha")
    pasted = texture_editor_pasted_channel_state(
        document,
        layer_pixels,
        layer_id="paint",
        channel_key="blue",
        channel_data=np.full((2, 2), 123, dtype=np.uint8),
    )
    swapped = texture_editor_swapped_channels_state(
        document,
        layer_pixels,
        layer_id="paint",
        channel_a="red",
        channel_b="blue",
    )
    extract_operation = texture_editor_channel_extract_operation_state(
        document,
        layer_pixels,
        current_layer_id=None,
        channel_key="blue",
    )
    luma_operation = texture_editor_channel_luma_pack_operation_state(
        document,
        layer_pixels,
        current_layer_id=None,
        channel_key="alpha",
    )
    selection_load_operation = texture_editor_channel_selection_load_operation_state(
        document,
        layer_pixels,
        current_layer_id=None,
        channel_key="red",
        combine_mode="replace",
    )
    selection_write_operation = texture_editor_channel_selection_write_operation_state(
        document,
        layer_pixels,
        current_layer_id=None,
        channel_key="green",
    )
    copy_operation = texture_editor_channel_copy_operation_state(
        document,
        layer_pixels,
        current_layer_id=None,
        channel_key="alpha",
    )
    paste_operation = texture_editor_channel_paste_operation_state(
        document,
        layer_pixels,
        current_layer_id=None,
        channel_key="blue",
        channel_clipboard=clipboard.clipboard,
    )
    swap_operation = texture_editor_channel_swap_operation_state(
        document,
        layer_pixels,
        current_layer_id=None,
        channel_a="red",
        channel_b="blue",
    )
    no_selection_operation = texture_editor_channel_selection_write_operation_state(
        dataclasses.replace(document, selection=TextureEditorSelection()),
        layer_pixels,
        current_layer_id=None,
        channel_key="green",
    )
    locked_document = dataclasses.replace(
        document,
        layers=(dataclasses.replace(layer, alpha_locked=True),),
    )
    locked_luma_operation = texture_editor_channel_luma_pack_operation_state(
        locked_document,
        layer_pixels,
        current_layer_id=None,
        channel_key="alpha",
    )
    same_swap_operation = texture_editor_channel_swap_operation_state(
        document,
        layer_pixels,
        current_layer_id=None,
        channel_a="red",
        channel_b="red",
    )
    missing_copy_operation = texture_editor_channel_copy_operation_state(
        document,
        {},
        current_layer_id=None,
        channel_key="alpha",
    )

    assert extracted.new_layer_id in extracted.layer_pixels
    assert extracted.layer_pixels[extracted.new_layer_id][0, 0].tolist() == [10, 10, 10, 255]
    assert extracted.history_label == "Extract Red Channel"
    assert extracted.status_text == "Extracted the Red channel into a new layer."
    assert extracted.tracked_layer_ids == ("paint", extracted.new_layer_id)
    assert extracted.force_checkpoint is True
    assert luma.layer_pixels["paint"][0, 0, 3] == 18
    assert luma.before_layer_pixels["paint"][0, 0, 3] == 40
    assert luma.document.layers[0].revision == 1
    assert channel_selection.document.selection.mode != "none"
    assert channel_selection.kind == "selection_update"
    assert selection_write.layer_pixels["paint"][0, 0, 1] == 255
    assert selection_write.kind == "channel_pack"
    assert clipboard.clipboard[0].shape == (2, 2)
    assert clipboard.clipboard[1] == "alpha"
    assert pasted.layer_pixels["paint"][1, 1, 2] == 123
    assert swapped.layer_pixels["paint"][0, 0, 0] == 30
    assert swapped.layer_pixels["paint"][0, 0, 2] == 10
    assert swapped.status_text == "Swapped the Red and Blue channels."
    assert extract_operation.layer_state is not None
    assert extract_operation.layer_state.history_label == "Extract Blue Channel"
    assert luma_operation.layer_state is not None
    assert luma_operation.layer_state.layer_id == "paint"
    assert selection_load_operation.document_state is not None
    assert selection_load_operation.document_state.kind == "selection_update"
    assert selection_write_operation.layer_state is not None
    assert selection_write_operation.layer_state.history_label == "Write Selection To Green"
    assert copy_operation.clipboard_state is not None
    assert copy_operation.clipboard_state.clipboard[1] == "alpha"
    assert paste_operation.layer_state is not None
    assert paste_operation.layer_state.history_label == "Paste Channel To Blue"
    assert swap_operation.layer_state is not None
    assert swap_operation.layer_state.status_text == "Swapped the Red and Blue channels."
    assert no_selection_operation.layer_state is None
    assert no_selection_operation.status_text == "Create a selection first, then write it to a channel."
    assert no_selection_operation.error is True
    assert locked_luma_operation.layer_state is None
    assert locked_luma_operation.status_text == "Unlock alpha before packing luminance into the alpha channel."
    assert locked_luma_operation.error is True
    assert same_swap_operation.layer_state is None
    assert same_swap_operation.status_text == "Choose two different channels to swap."
    assert same_swap_operation.error is True
    assert missing_copy_operation.clipboard_state is None
    assert missing_copy_operation.status_text == ""


def test_texture_editor_view_state_helpers() -> None:
    split = texture_editor_view_controls_state("split", has_document=True, busy=False, grid_enabled=True)
    edited_busy = texture_editor_view_controls_state("edited", has_document=True, busy=True, grid_enabled=True)
    no_grid = texture_editor_view_controls_state("split", has_document=True, busy=False, grid_enabled=False)
    grid_state = texture_editor_grid_control_state(
        enabled=1,
        grid_size="32",
        grid_color="color-object",
        grid_color_hex="",
        grid_opacity="55",
    )
    color = texture_editor_grid_color_button_state("#74c1ff")
    merged_dirty = merged_texture_editor_composite_dirty_bounds((5, 5, 4, 4), (2, 7, 3, 8))
    initial_dirty = merged_texture_editor_composite_dirty_bounds(None, (1, 2, 3, 4))
    clamped_dirty = clamped_texture_editor_composite_dirty_bounds(
        (-2, 3, 8, 4),
        document_width=5,
        document_height=10,
    )
    empty_dirty = clamped_texture_editor_composite_dirty_bounds(
        (8, 3, 1, 1),
        document_width=5,
        document_height=10,
    )
    composite_document = TextureEditorDocument(
        "doc",
        2,
        2,
        active_layer_id="paint",
        layers=(TextureEditorLayer("paint", "Paint", ""),),
    )
    composite_pixels = {"paint": np.zeros((2, 2, 4), dtype=np.uint8)}
    composite_pixels["paint"][0, 0] = [10, 20, 30, 255]
    full_composite = texture_editor_composite_render_state(
        composite_document,
        composite_pixels,
        None,
        revision=1,
        composite_cache=None,
        composite_cache_revision=0,
        dirty_bounds=None,
    )
    cache_hit = texture_editor_composite_render_state(
        composite_document,
        composite_pixels,
        None,
        revision=1,
        composite_cache=full_composite.cache,
        composite_cache_revision=1,
        dirty_bounds=(0, 0, 1, 1),
    )
    updated_pixels = {"paint": composite_pixels["paint"].copy()}
    updated_pixels["paint"][1, 1] = [80, 90, 100, 255]
    dirty_composite = texture_editor_composite_render_state(
        composite_document,
        updated_pixels,
        None,
        revision=2,
        composite_cache=full_composite.cache,
        composite_cache_revision=1,
        dirty_bounds=(1, 1, 1, 1),
    )

    assert texture_editor_zoom_factor_for_step(1.0, 1) == 1.15
    assert texture_editor_zoom_factor_for_step(1.0, -1) == 0.87
    assert texture_editor_view_mode_key(None) == "edited"
    assert texture_editor_view_mode_key("split") == "split"
    assert texture_editor_grid_color_hex("") == "#74C1FF"
    assert grid_state.enabled is True
    assert grid_state.grid_size == 32
    assert grid_state.grid_color == "color-object"
    assert grid_state.grid_color_hex == "#74C1FF"
    assert grid_state.grid_opacity == 55
    assert abs(texture_editor_wheel_zoom_multiplier(120) - 1.15) < 0.000001
    assert abs(texture_editor_wheel_zoom_multiplier(30) - (1.0025**30)) < 0.000001
    assert texture_editor_zoom_scroll_targets(
        widget_x=80,
        widget_y=120,
        old_scale=2.0,
        new_scale=4.0,
        viewport_x=10,
        viewport_y=20,
    ) == (150, 220)
    assert split.compare_split_visible is True
    assert split.compare_split_enabled is True
    assert split.grid_color_enabled is True
    assert edited_busy.compare_split_visible is False
    assert edited_busy.grid_size_enabled is False
    assert no_grid.grid_opacity_enabled is False
    assert "background-color: #74c1ff;" in color.style_sheet
    assert color.text == ""
    assert color.tooltip == "Grid color: #74C1FF"
    assert merged_dirty == (2, 5, 7, 10)
    assert initial_dirty == (1, 2, 3, 4)
    assert clamped_dirty == (0, 3, 5, 4)
    assert empty_dirty is None
    assert full_composite.rgba[0, 0].tolist() == [10, 20, 30, 255]
    assert full_composite.cache_revision == 1
    assert full_composite.dirty_bounds is None
    assert cache_hit.rgba is full_composite.cache
    assert cache_hit.dirty_bounds == (0, 0, 1, 1)
    assert dirty_composite.rgba[0, 0].tolist() == [10, 20, 30, 255]
    assert dirty_composite.rgba[1, 1].tolist() == [80, 90, 100, 255]
    assert dirty_composite.cache_revision == 2
    assert dirty_composite.dirty_bounds is None


def test_texture_editor_view_state_payload_normalizes_values() -> None:
    payload = texture_editor_view_state_payload(
        zoom_factor=1,
        fit_to_view=False,
        view_mode="split",
        compare_split=42,
        grid_enabled=True,
        grid_size=16,
        grid_color="#123456",
        grid_opacity=70,
        show_rulers=True,
        show_guides=True,
        vertical_guides=(1, 2.5, "bad"),
        horizontal_guides=[3, object(), 4.8],
        scroll_x=12,
        scroll_y=34,
    )

    assert payload["zoom_factor"] == 1.0
    assert payload["view_mode"] == "split"
    assert payload["vertical_guides"] == [1, 2]
    assert payload["horizontal_guides"] == [3, 4]
    assert texture_editor_guides_from_view_state("123") == ()
    assert texture_editor_guides_from_view_state((7, "x", 9.2)) == (7, 9)


def test_texture_editor_resolved_view_state_uses_defaults_and_saved_values() -> None:
    resolved = texture_editor_resolved_view_state(
        {
            "view_mode": "split",
            "compare_split": 44,
            "grid_enabled": False,
            "grid_size": 32,
            "grid_color": "#112233",
            "grid_opacity": 80,
            "show_rulers": False,
            "show_guides": True,
            "vertical_guides": [5, "skip", 7.8],
            "horizontal_guides": [9],
            "fit_to_view": False,
            "zoom_factor": 2,
            "scroll_x": 11,
            "scroll_y": 12,
        },
        default_compare_split=50,
        default_grid_enabled=True,
        default_grid_size=8,
        default_grid_color="#74C1FF",
        default_grid_opacity=45,
    )
    defaults = texture_editor_resolved_view_state(
        {},
        default_compare_split=50,
        default_grid_enabled=True,
        default_grid_size=8,
        default_grid_color="#74C1FF",
        default_grid_opacity=45,
    )

    assert resolved.view_mode == "split"
    assert resolved.compare_split == 44
    assert resolved.grid_enabled is False
    assert resolved.grid_color == "#112233"
    assert resolved.vertical_guides == (5, 7)
    assert resolved.fit_to_view is False
    assert resolved.zoom_factor == 2.0
    assert resolved.scroll_y == 12
    assert defaults.view_mode == "edited"
    assert defaults.compare_split == 50
    assert defaults.grid_enabled is True
    assert defaults.grid_size == 8
    assert defaults.grid_opacity == 45


def test_texture_editor_navigation_state_helpers() -> None:
    empty_overlay = texture_editor_navigation_overlay_state(
        has_document=False,
        show_rulers=True,
        show_guides=True,
        vertical_guides=(10,),
        horizontal_guides=(20,),
    )
    overlay = texture_editor_navigation_overlay_state(
        has_document=True,
        show_rulers=True,
        show_guides=False,
        vertical_guides=(10, 12.5, "bad"),
        horizontal_guides=(20,),
    )
    empty_ruler = texture_editor_empty_ruler_state()
    top, left = texture_editor_ruler_states(
        document_width=256,
        document_height=128,
        display_scale=2.0,
        scroll_x=30,
        scroll_y=40,
        viewport_offset_x=-5,
        viewport_offset_y=7,
        hover_pixel_info={"x": 17, "y": 23},
        vertical_guides=overlay.vertical_guides,
        horizontal_guides=overlay.horizontal_guides,
    )
    viewport_rect = texture_editor_navigator_viewport_rect(
        document_width=256,
        document_height=128,
        viewport_width=100,
        viewport_height=80,
        display_scale=2.0,
        scroll_x=30,
        scroll_y=40,
    )
    center_scroll = texture_editor_center_scroll_values(
        image_x=100,
        image_y=20,
        display_scale=2.0,
        viewport_width=80,
        viewport_height=100,
        horizontal_minimum=0,
        horizontal_maximum=150,
        vertical_minimum=0,
        vertical_maximum=120,
    )

    assert empty_overlay.rulers_visible is False
    assert empty_overlay.guides_enabled is False
    assert empty_overlay.vertical_guides == ()
    assert overlay.rulers_visible is True
    assert overlay.guides_enabled is False
    assert overlay.vertical_guides == (10, 12)
    assert empty_ruler.as_kwargs()["image_length"] == 0
    assert top.image_length == 256
    assert top.hover_position == 17
    assert top.guides == (10, 12)
    assert left.image_length == 128
    assert left.hover_position == 23
    assert left.viewport_offset == 7
    assert viewport_rect == (15.0, 20.0, 50.0, 40.0)
    assert center_scroll == (150, 0)
