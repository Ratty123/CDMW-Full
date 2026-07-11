from __future__ import annotations

"""Canvas tool operation coordination for the standalone Texture Editor tab."""

import dataclasses

from cdmw.ui.texture_workflow.editor_clipboard_state import texture_editor_layer_copy_clipboard_state
from cdmw.ui.texture_workflow.editor_floating_state import (
    estimated_texture_editor_brush_dirty_bounds,
    texture_editor_layer_canvas_bounds,
)
from cdmw.ui.texture_workflow.editor_layer_state import (
    texture_editor_edit_target_layer_id,
    texture_editor_moved_layer_state,
)
from cdmw.ui.texture_workflow.editor_selection_state import current_texture_editor_selection_bounds
from cdmw.ui.texture_workflow.editor_tool_state import (
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
    texture_editor_recolor_layer_state,
    texture_editor_stroke_payload_state,
    texture_editor_stroke_source_snapshot,
    texture_editor_tool_settings_for_stroke,
)


class TextureEditorToolOperationUiMixin:
    def _handle_clone_source_picked(self, point: object) -> None:
        clone_source_state = texture_editor_clone_source_picked_state(self.current_tool_settings, point)
        if clone_source_state is None:
            return
        self.current_tool_settings = clone_source_state.settings
        self.canvas.set_clone_source_point(clone_source_state.clone_source_point)
        self._refresh_ui()
        self._set_status(texture_editor_clone_source_picked_status_text(clone_source_state.clone_source_point), False)

    def clear_clone_source_point(self) -> None:
        clone_source_state = texture_editor_clone_source_cleared_state(self.current_tool_settings)
        self.current_tool_settings = clone_source_state.settings
        self.canvas.set_clone_source_point(clone_source_state.clone_source_point)
        self._refresh_ui()
        self._set_status(texture_editor_clone_source_cleared_status_text(), False)

    def copy_active_layer(self) -> None:
        copy_state = texture_editor_layer_copy_clipboard_state(
            self.document,
            self.layer_pixels,
            current_layer_id=self._current_layer_id(),
        )
        if not copy_state.copied or copy_state.layer_clipboard is None:
            return
        self.layer_clipboard = copy_state.layer_clipboard
        self.selection_clipboard = None
        self._set_status(copy_state.status_text, copy_state.error)

    def _handle_canvas_stroke(self, payload: object) -> None:
        if self.document is None:
            return
        stroke_state = texture_editor_stroke_payload_state(payload, self.current_tool_settings.tool)
        if stroke_state is None:
            return
        points = stroke_state.points
        tool = stroke_state.tool
        before_document = dataclasses.replace(self.document)
        if tool == "move":
            move_delta = texture_editor_move_delta(points)
            if move_delta is None:
                return
            dx, dy = move_delta
            floating_move_handled = self._handle_floating_move_delta(dx, dy, before_document)
            if floating_move_handled is None:
                return
            if not floating_move_handled:
                if not self.document.active_layer_id or self.document.active_layer_id not in self.layer_pixels:
                    return
                move_state = texture_editor_moved_layer_state(
                    self.document,
                    self.document.active_layer_id,
                    dx=dx,
                    dy=dy,
                )
                self.document = move_state.document
                self._invalidate_layer_thumbnail(move_state.layer_id)
                self._invalidate_composite_cache()
                self._record_history_change(
                    move_state.history_label,
                    before_document=before_document,
                    before_layer_pixels={},
                    kind=move_state.kind,
                    tracked_layer_ids=move_state.tracked_layer_ids,
                )
            self._refresh_editor_views(
                canvas=True,
                layers=self.document.floating_selection is None,
                transform=self.document.floating_selection is not None,
                status=True,
                tool_visibility=False,
            )
            return
        tool_settings = texture_editor_tool_settings_for_stroke(self.current_tool_settings, tool)
        if self.document.quick_mask_enabled:
            if not texture_editor_quick_mask_tool_allowed(tool):
                self._set_status(texture_editor_quick_mask_tool_status(), True)
                return
            before_document = dataclasses.replace(self.document)
            quick_mask_state = texture_editor_quick_mask_stroke_state(self.document, tool_settings, points)
            if quick_mask_state is None:
                return
            self.document = quick_mask_state.document
            self._invalidate_composite_cache()
            self._record_history_change(
                quick_mask_state.history_label,
                before_document=before_document,
                before_layer_pixels={},
                kind=quick_mask_state.kind,
                tracked_layer_ids=quick_mask_state.tracked_layer_ids,
            )
            self._refresh_editor_views(
                canvas=True,
                selection=True,
                status=True,
                tool_visibility=False,
            )
            return
        if texture_editor_clone_source_required(tool_settings):
            self._set_status(texture_editor_clone_source_required_status(), True)
            return
        active_layer = self.layer_pixels.get(self.document.active_layer_id or "")
        active_layer_has_visible_pixels = (
            texture_editor_layer_has_visible_pixels(active_layer)
            if tool_settings.tool in {"sharpen", "soften"}
            else True
        )
        if texture_editor_empty_active_layer_filter_blocked(
            tool_settings,
            active_layer_exists=active_layer is not None,
            active_layer_has_visible_pixels=active_layer_has_visible_pixels,
        ):
            self._set_status(texture_editor_empty_active_layer_filter_status(), True)
            return
        source_snapshot = texture_editor_stroke_source_snapshot(
            self.document,
            self.layer_pixels,
            tool_settings,
            active_layer,
        )
        layer_id = texture_editor_edit_target_layer_id(
            self.document,
            current_layer_id=self._current_layer_id(),
            editing_mask_target=self._editing_mask_target,
        )
        if not layer_id or layer_id not in self.layer_pixels:
            return
        if texture_editor_patch_selection_required(tool_settings, self.document.selection.mode):
            self._set_status(texture_editor_patch_selection_required_status(), True)
            return
        layer_state = texture_editor_layer_stroke_state(
            self.document,
            self.layer_pixels,
            tool_settings,
            points,
            layer_id=layer_id,
            editing_mask_target=self._editing_mask_target,
            selection_bounds=current_texture_editor_selection_bounds(self.document),
            layer_canvas_bounds=texture_editor_layer_canvas_bounds(self.document, self.layer_pixels, layer_id),
            brush_dirty_bounds=estimated_texture_editor_brush_dirty_bounds(
                self.document,
                self.current_tool_settings,
                points,
            ),
            source_snapshot=source_snapshot,
        )
        if layer_state is None:
            return
        self.document = layer_state.document
        self.layer_pixels = layer_state.layer_pixels
        if layer_state.thumbnail_layer_id:
            self._invalidate_layer_thumbnail(layer_state.thumbnail_layer_id)
        self._invalidate_composite_cache(layer_state.dirty_bounds)
        self._record_history_change(
            layer_state.history_label,
            before_document=before_document,
            before_layer_pixels=layer_state.before_layer_pixels,
            kind=layer_state.kind,
            tracked_layer_ids=layer_state.tracked_layer_ids,
            dirty_bounds=layer_state.dirty_bounds,
        )
        self._refresh_editor_views(
            canvas=True,
            status=True,
            tool_visibility=False,
        )

    def apply_recolor_to_active_layer(self) -> None:
        if self.document is None:
            return
        if self.current_tool_settings.tool != "recolor":
            self._set_active_tool("recolor")
        layer_id = self.document.active_layer_id
        edit_target_id = texture_editor_edit_target_layer_id(
            self.document,
            current_layer_id=self._current_layer_id(),
            editing_mask_target=self._editing_mask_target,
        ) or layer_id
        if not edit_target_id or edit_target_id not in self.layer_pixels:
            return
        if self._editing_mask_target:
            layer_id = edit_target_id
        else:
            layer_id = edit_target_id
        before_document = dataclasses.replace(self.document)
        dirty_bounds = current_texture_editor_selection_bounds(self.document) or texture_editor_layer_canvas_bounds(
            self.document,
            self.layer_pixels,
            layer_id,
        )
        recolor_state = texture_editor_recolor_layer_state(
            self.document,
            self.layer_pixels,
            self.current_tool_settings,
            layer_id=layer_id,
            dirty_bounds=dirty_bounds,
        )
        if recolor_state is None:
            return
        self.document = recolor_state.document
        self.layer_pixels = recolor_state.layer_pixels
        self._invalidate_layer_thumbnail(recolor_state.layer_id)
        self._invalidate_composite_cache(recolor_state.dirty_bounds)
        self._record_history_change(
            recolor_state.history_label,
            before_document=before_document,
            before_layer_pixels=recolor_state.before_layer_pixels,
            kind=recolor_state.kind,
            tracked_layer_ids=recolor_state.tracked_layer_ids,
            dirty_bounds=recolor_state.dirty_bounds,
        )
        self._refresh_editor_views(
            canvas=True,
            status=True,
            tool_visibility=False,
        )
