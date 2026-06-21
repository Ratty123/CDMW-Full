from __future__ import annotations

"""Floating selection and transform coordination for the standalone Texture Editor tab."""

import dataclasses
from typing import Optional, Tuple

import numpy as np
from PySide6.QtCore import Qt

from cdmw.ui.texture_workflow.editor_clipboard_state import (
    TextureEditorFloatingPasteState,
    texture_editor_clipboard_floating_paste_state,
    texture_editor_cut_selection_missing_status_text,
)
from cdmw.ui.texture_workflow.editor_floating_state import (
    current_texture_editor_floating_canvas_bounds,
    texture_editor_cleared_floating_selection_state,
    texture_editor_cut_selection_to_floating_state,
    texture_editor_floating_cancel_history_label,
    texture_editor_floating_cancel_status_text,
    texture_editor_floating_committed_layer_state,
    texture_editor_floating_layer_copy_state,
    texture_editor_floating_move_state,
    texture_editor_floating_selection_updated_status_text,
    texture_editor_set_floating_selection_state,
    texture_editor_snapshot_floating_pixels,
    transformed_texture_editor_floating_pixels,
)
from cdmw.ui.texture_workflow.editor_selection_state import (
    texture_editor_active_layer_selection_payload_state,
)
from cdmw.ui.texture_workflow.editor_transform_state import (
    texture_editor_applied_floating_transform_state,
    texture_editor_canvas_floating_transform_state,
    texture_editor_flipped_floating_transform_state,
    texture_editor_floating_transform_dirty_bounds,
    texture_editor_rotated_floating_transform_state,
    texture_editor_transform_controls_state,
)


class TextureEditorFloatingUiMixin:
    def float_active_layer_copy(self) -> None:
        if self.document is None:
            return
        copy_state = texture_editor_floating_layer_copy_state(
            self.document,
            current_layer_id=self._current_layer_id(),
            layer_pixels=self.layer_pixels,
        )
        if not copy_state.can_float or copy_state.pixels is None:
            if copy_state.status_text:
                self._set_status(copy_state.status_text, copy_state.error)
            return
        before_document = dataclasses.replace(self.document)
        before_floating_pixels = texture_editor_snapshot_floating_pixels(self._floating_pixels)
        self._set_floating_selection(
            copy_state.pixels,
            label=copy_state.label,
            bounds=copy_state.bounds,
            source_layer_id=copy_state.source_layer_id,
            paste_mode="in_place",
        )
        self._record_history_change(
            copy_state.history_label,
            before_document=before_document,
            before_layer_pixels={},
            kind="floating_create",
            tracked_layer_ids=[],
            dirty_bounds=copy_state.bounds,
            before_floating_pixels=before_floating_pixels,
        )
        self._set_active_tool("move")
        self._refresh_ui()
        self._set_status(copy_state.status_text, copy_state.error)

    def apply_floating_transform(self) -> None:
        transform_state = texture_editor_applied_floating_transform_state(
            self.document,
            scale_percent=self.transform_scale_spin.value(),
            rotation_degrees=self.transform_rotation_spin.value(),
        )
        if transform_state is None:
            return
        before_document = dataclasses.replace(self.document)
        before_floating_pixels = texture_editor_snapshot_floating_pixels(self._floating_pixels)
        self.document = transform_state.document
        self._invalidate_composite_cache()
        self._record_history_change(
            transform_state.history_label,
            before_document=before_document,
            before_layer_pixels={},
            kind="floating_transform",
            tracked_layer_ids=[],
            before_floating_pixels=before_floating_pixels,
        )
        self._refresh_ui()

    def flip_floating_selection(self, flip_x: bool, flip_y: bool) -> None:
        transform_state = texture_editor_flipped_floating_transform_state(self.document, flip_x=flip_x, flip_y=flip_y)
        if transform_state is None:
            return
        before_document = dataclasses.replace(self.document)
        before_floating_pixels = texture_editor_snapshot_floating_pixels(self._floating_pixels)
        self.document = transform_state.document
        self._invalidate_composite_cache()
        self._record_history_change(
            transform_state.history_label,
            before_document=before_document,
            before_layer_pixels={},
            kind="floating_transform",
            tracked_layer_ids=[],
            before_floating_pixels=before_floating_pixels,
        )
        self._refresh_ui()

    def rotate_floating_selection(self, degrees: int) -> None:
        transform_state = texture_editor_rotated_floating_transform_state(self.document, degrees=degrees)
        if transform_state is None:
            return
        before_document = dataclasses.replace(self.document)
        before_floating_pixels = texture_editor_snapshot_floating_pixels(self._floating_pixels)
        self.document = transform_state.document
        self.transform_rotation_spin.blockSignals(True)
        self.transform_rotation_spin.setValue(int(round(self.document.floating_selection.rotation_degrees)))
        self.transform_rotation_spin.blockSignals(False)
        self._invalidate_composite_cache()
        self._record_history_change(
            transform_state.history_label,
            before_document=before_document,
            before_layer_pixels={},
            kind="floating_transform",
            tracked_layer_ids=[],
            before_floating_pixels=before_floating_pixels,
        )
        self._refresh_ui()

    def _handle_canvas_floating_transform(self, payload: object) -> None:
        transform_state = texture_editor_canvas_floating_transform_state(self.document, payload)
        if transform_state is None:
            return
        if not transform_state.changed:
            if transform_state.commit:
                self._floating_transform_before_document = None
                self._floating_transform_before_floating_pixels = None
                self._floating_transform_label = ""
            return
        if self._floating_transform_before_document is None:
            self._floating_transform_before_document = dataclasses.replace(self.document)
            self._floating_transform_before_floating_pixels = texture_editor_snapshot_floating_pixels(self._floating_pixels)
            self._floating_transform_label = transform_state.history_label
        before_bounds = current_texture_editor_floating_canvas_bounds(self.document, self._floating_pixels)
        self.document = transform_state.document
        after_bounds = current_texture_editor_floating_canvas_bounds(self.document, self._floating_pixels)
        dirty_bounds = texture_editor_floating_transform_dirty_bounds(before_bounds, after_bounds)
        self._invalidate_composite_cache(dirty_bounds)
        if transform_state.commit and self._floating_transform_before_document is not None:
            self._record_history_change(
                self._floating_transform_label or "Transform Floating Selection",
                before_document=self._floating_transform_before_document,
                before_layer_pixels={},
                kind="floating_transform",
                tracked_layer_ids=[],
                dirty_bounds=dirty_bounds,
                before_floating_pixels=self._floating_transform_before_floating_pixels,
            )
            self._floating_transform_before_document = None
            self._floating_transform_before_floating_pixels = None
            self._floating_transform_label = ""
            self._set_status(texture_editor_floating_selection_updated_status_text(), False)
            self._refresh_editor_views(
                canvas=True,
                history=True,
                transform=True,
                status=True,
                tool_visibility=False,
            )
        else:
            self._refresh_editor_views(
                canvas=True,
                transform=True,
                status=True,
                tool_visibility=False,
            )

    def _set_floating_selection(
        self,
        pixels: np.ndarray,
        *,
        label: str,
        bounds: Tuple[int, int, int, int],
        source_layer_id: str = "",
        paste_mode: str = "in_place",
    ) -> None:
        if self.document is None:
            return
        self._floating_transform_before_document = None
        self._floating_transform_before_floating_pixels = None
        self._floating_transform_label = ""
        floating_state = texture_editor_set_floating_selection_state(
            self.document,
            pixels,
            label=label,
            bounds=bounds,
            source_layer_id=source_layer_id,
            paste_mode=paste_mode,
        )
        self._floating_pixels = floating_state.floating_pixels
        self._floating_mask = floating_state.floating_mask
        self.document = floating_state.document
        self._invalidate_composite_cache(floating_state.dirty_bounds)

    def _clear_floating_selection(self) -> None:
        if self.document is None:
            return
        self._floating_transform_before_document = None
        self._floating_transform_before_floating_pixels = None
        self._floating_transform_label = ""
        self._floating_pixels = None
        self._floating_mask = None
        self.document = texture_editor_cleared_floating_selection_state(self.document)
        self._invalidate_composite_cache()

    def commit_floating_selection(self) -> None:
        if self.document is None or self.document.floating_selection is None or self._floating_pixels is None:
            return
        transformed = transformed_texture_editor_floating_pixels(
            self.document.floating_selection,
            self._floating_pixels,
        )
        if transformed is None:
            self._clear_floating_selection()
            self._refresh_ui()
            return
        commit_state = texture_editor_floating_committed_layer_state(self.document, self.layer_pixels, transformed)
        if commit_state is None:
            return
        before_document = dataclasses.replace(self.document)
        before_layer_pixels = dict(self.layer_pixels)
        before_floating_pixels = texture_editor_snapshot_floating_pixels(self._floating_pixels)
        self.document = commit_state.document
        self.layer_pixels = commit_state.layer_pixels
        self._clear_floating_selection()
        self._record_history_change(
            commit_state.history_label,
            before_document=before_document,
            before_layer_pixels=before_layer_pixels,
            kind="floating_commit",
            dirty_bounds=commit_state.dirty_bounds,
            before_floating_pixels=before_floating_pixels,
        )
        self._refresh_ui()
        for row in range(self.layers_list.count()):
            item = self.layers_list.item(row)
            if item is not None and item.data(Qt.UserRole) == commit_state.layer_id:
                self.layers_list.setCurrentItem(item)
                break
        self._set_status(commit_state.status_text, False)

    def cancel_floating_selection(self) -> None:
        if self.document is None or self.document.floating_selection is None:
            return
        before_document = dataclasses.replace(self.document)
        before_layer_pixels = dict(self.layer_pixels)
        before_floating_pixels = texture_editor_snapshot_floating_pixels(self._floating_pixels)
        self._clear_floating_selection()
        self._record_history_change(
            texture_editor_floating_cancel_history_label(),
            before_document=before_document,
            before_layer_pixels=before_layer_pixels,
            kind="floating_cancel",
            dirty_bounds=None,
            before_floating_pixels=before_floating_pixels,
        )
        self._refresh_ui()
        self._set_status(texture_editor_floating_cancel_status_text(), False)

    def cut_selection_to_floating(self) -> None:
        if self.document is None:
            return
        selection_state = texture_editor_active_layer_selection_payload_state(
            self.document,
            self.layer_pixels,
            current_layer_id=self._current_layer_id(),
        )
        if selection_state is None:
            self._set_status(texture_editor_cut_selection_missing_status_text(), True)
            return
        before_document = dataclasses.replace(self.document)
        before_floating_pixels = texture_editor_snapshot_floating_pixels(self._floating_pixels)
        cut_state = texture_editor_cut_selection_to_floating_state(
            self.document,
            self.layer_pixels,
            selection_state,
            current_layer_id=self._current_layer_id(),
        )
        if cut_state is None:
            return
        self._floating_transform_before_document = None
        self._floating_transform_before_floating_pixels = None
        self._floating_transform_label = ""
        self.document = cut_state.document
        self.layer_pixels = cut_state.layer_pixels
        self.selection_clipboard = cut_state.selection_clipboard
        self._floating_pixels = cut_state.floating_pixels
        self._floating_mask = cut_state.floating_mask
        self._invalidate_layer_thumbnail(cut_state.layer_id)
        self._invalidate_composite_cache(cut_state.dirty_bounds)
        self._record_history_change(
            cut_state.history_label,
            before_document=before_document,
            before_layer_pixels=cut_state.before_layer_pixels,
            kind=cut_state.kind,
            tracked_layer_ids=cut_state.tracked_layer_ids,
            dirty_bounds=cut_state.dirty_bounds,
            before_floating_pixels=before_floating_pixels,
        )
        self._set_active_tool("move")
        self._refresh_ui()
        self._set_status(cut_state.status_text, False)

    def _paste_floating_state(
        self,
        pixels: np.ndarray,
        paste_state: TextureEditorFloatingPasteState,
        *,
        source_layer_id: str = "",
    ) -> None:
        before_document = dataclasses.replace(self.document)
        before_layer_pixels = dict(self.layer_pixels)
        before_floating_pixels = texture_editor_snapshot_floating_pixels(self._floating_pixels)
        self._set_floating_selection(
            pixels,
            label=paste_state.label,
            bounds=paste_state.bounds,
            paste_mode=paste_state.paste_mode,
            source_layer_id=source_layer_id,
        )
        self._record_history_change(
            paste_state.history_label,
            before_document=before_document,
            before_layer_pixels=before_layer_pixels,
            kind="floating_create",
            dirty_bounds=paste_state.bounds,
            before_floating_pixels=before_floating_pixels,
        )
        self._set_active_tool("move")
        self._refresh_ui()
        self._set_status(paste_state.status_text, False)

    def _paste_clipboard_floating_state(self, *, source: str = "any", centered: bool = False) -> None:
        clipboard_state = texture_editor_clipboard_floating_paste_state(
            self.document,
            layer_clipboard=self.layer_clipboard,
            selection_clipboard=self.selection_clipboard,
            source=source,
            centered=centered,
        )
        if (
            not clipboard_state.can_paste
            or clipboard_state.pixels is None
            or clipboard_state.paste_state is None
        ):
            return
        self._paste_floating_state(clipboard_state.pixels, clipboard_state.paste_state)

    def paste_layer(self) -> None:
        self._paste_clipboard_floating_state(source="layer")

    def paste_selection_as_layer(self) -> None:
        self._paste_clipboard_floating_state(source="selection")

    def paste_content(self) -> None:
        self._paste_clipboard_floating_state()

    def paste_content_centered(self) -> None:
        self._paste_clipboard_floating_state(centered=True)

    def _handle_floating_move_delta(self, dx: int, dy: int, before_document: object) -> Optional[bool]:
        if self.document.floating_selection is None or self._floating_pixels is None:
            return False
        before_floating_pixels = texture_editor_snapshot_floating_pixels(self._floating_pixels)
        move_state = texture_editor_floating_move_state(self.document, dx=dx, dy=dy)
        if move_state is None:
            return None
        self.document = move_state.document
        self._invalidate_composite_cache(move_state.dirty_bounds)
        self._record_history_change(
            move_state.history_label,
            before_document=before_document,
            before_layer_pixels={},
            kind=move_state.kind,
            tracked_layer_ids=move_state.tracked_layer_ids,
            dirty_bounds=move_state.dirty_bounds,
            before_floating_pixels=before_floating_pixels,
        )
        return True

    def _refresh_transform_controls(self) -> None:
        controls = texture_editor_transform_controls_state(self.document)
        for widget in (
            self.transform_scale_spin,
            self.transform_rotation_spin,
            self.transform_apply_button,
            self.transform_flip_h_button,
            self.transform_flip_v_button,
            self.transform_rotate_left_button,
            self.transform_rotate_right_button,
            self.transform_commit_button,
            self.transform_cancel_button,
        ):
            widget.setEnabled(controls.floating_controls_enabled)
        self.transform_float_layer_button.setEnabled(controls.float_layer_enabled)
        self.transform_scale_spin.blockSignals(True)
        self.transform_rotation_spin.blockSignals(True)
        self.transform_scale_spin.setValue(controls.scale_percent)
        self.transform_rotation_spin.setValue(controls.rotation_degrees)
        self.transform_scale_spin.blockSignals(False)
        self.transform_rotation_spin.blockSignals(False)


__all__ = ["TextureEditorFloatingUiMixin"]
