from __future__ import annotations

"""Navigation, zoom, grid, and view-state coordination for Texture Editor UI."""

from typing import Dict, Optional

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog

from cdmw.ui.texture_workflow.editor_guides import (
    format_texture_editor_guides_text,
    parse_texture_editor_guides_text,
    texture_editor_guides_cleared_status_text,
)
from cdmw.ui.texture_workflow.editor_session import texture_editor_document_key
from cdmw.ui.texture_workflow.editor_status_state import texture_editor_zoom_labels
from cdmw.ui.texture_workflow.editor_view_state import (
    texture_editor_center_scroll_values,
    texture_editor_empty_ruler_state,
    texture_editor_grid_color_button_state,
    texture_editor_grid_color_hex,
    texture_editor_grid_control_state,
    texture_editor_navigation_overlay_state,
    texture_editor_navigator_viewport_rect,
    texture_editor_resolved_view_state,
    texture_editor_ruler_states,
    texture_editor_view_controls_state,
    texture_editor_view_mode_key,
    texture_editor_view_state_payload,
    texture_editor_wheel_zoom_multiplier,
    texture_editor_zoom_factor_for_step,
    texture_editor_zoom_scroll_targets,
)


class TextureEditorViewCoordinationMixin:
    def _refresh_navigation_overlays(self) -> None:
        has_doc = self.document is not None
        navigation = texture_editor_navigation_overlay_state(
            has_document=has_doc,
            show_rulers=self._show_rulers,
            show_guides=self._show_guides,
            vertical_guides=self._vertical_guides,
            horizontal_guides=self._horizontal_guides,
        )
        self.top_ruler.setVisible(navigation.rulers_visible)
        self.left_ruler.setVisible(navigation.rulers_visible)
        self.ruler_corner.setVisible(navigation.rulers_visible)
        self.canvas.set_guide_state(
            enabled=navigation.guides_enabled,
            vertical_guides=navigation.vertical_guides,
            horizontal_guides=navigation.horizontal_guides,
        )
        if not has_doc:
            empty_ruler = texture_editor_empty_ruler_state()
            self.top_ruler.set_state(**empty_ruler.as_kwargs())
            self.left_ruler.set_state(**empty_ruler.as_kwargs())
            self.navigator_widget.set_state(None, image_width=0, image_height=0, viewport_rect=None)
            return
        scale = max(0.0001, self.canvas.current_display_scale())
        scroll_x = int(self.canvas_scroll.horizontalScrollBar().value())
        scroll_y = int(self.canvas_scroll.verticalScrollBar().value())
        canvas_origin = self.canvas.mapTo(self.canvas_scroll.viewport(), QPoint(0, 0))
        viewport_offset_x = int(canvas_origin.x())
        viewport_offset_y = int(canvas_origin.y())
        top_ruler, left_ruler = texture_editor_ruler_states(
            document_width=self.document.width,
            document_height=self.document.height,
            display_scale=scale,
            scroll_x=scroll_x,
            scroll_y=scroll_y,
            viewport_offset_x=viewport_offset_x,
            viewport_offset_y=viewport_offset_y,
            hover_pixel_info=self._hover_pixel_info,
            vertical_guides=navigation.vertical_guides,
            horizontal_guides=navigation.horizontal_guides,
        )
        self.top_ruler.set_state(**top_ruler.as_kwargs())
        self.left_ruler.set_state(**left_ruler.as_kwargs())
        display_image = getattr(self.canvas, "_display_image", None) or getattr(self.canvas, "_image", None)
        viewport = self.canvas_scroll.viewport().size()
        viewport_rect = texture_editor_navigator_viewport_rect(
            document_width=self.document.width,
            document_height=self.document.height,
            viewport_width=viewport.width(),
            viewport_height=viewport.height(),
            display_scale=scale,
            scroll_x=scroll_x,
            scroll_y=scroll_y,
        )
        self.navigator_widget.set_state(
            display_image,
            image_width=int(self.document.width),
            image_height=int(self.document.height),
            viewport_rect=viewport_rect,
        )

    def _handle_navigation_overlay_changed(self, *_args) -> None:
        self._show_rulers = bool(self.show_rulers_checkbox.isChecked())
        self._show_guides = bool(self.show_guides_checkbox.isChecked())
        self._vertical_guides = parse_texture_editor_guides_text(self.vertical_guides_edit.text())
        self._horizontal_guides = parse_texture_editor_guides_text(self.horizontal_guides_edit.text())
        self.vertical_guides_edit.blockSignals(True)
        self.horizontal_guides_edit.blockSignals(True)
        self.vertical_guides_edit.setText(format_texture_editor_guides_text(self._vertical_guides))
        self.horizontal_guides_edit.setText(format_texture_editor_guides_text(self._horizontal_guides))
        self.vertical_guides_edit.blockSignals(False)
        self.horizontal_guides_edit.blockSignals(False)
        self._refresh_navigation_overlays()
        document_key = texture_editor_document_key(self.document)
        if document_key:
            self.workspace.document_view_state[document_key] = self._capture_view_state()

    def clear_guides(self) -> None:
        self._vertical_guides = ()
        self._horizontal_guides = ()
        self.vertical_guides_edit.blockSignals(True)
        self.horizontal_guides_edit.blockSignals(True)
        self.vertical_guides_edit.setText("")
        self.horizontal_guides_edit.setText("")
        self.vertical_guides_edit.blockSignals(False)
        self.horizontal_guides_edit.blockSignals(False)
        self._refresh_navigation_overlays()
        document_key = texture_editor_document_key(self.document)
        if document_key:
            self.workspace.document_view_state[document_key] = self._capture_view_state()
        self._refresh_ui()
        self._set_status(texture_editor_guides_cleared_status_text(), False)

    def _handle_canvas_hover_changed(self, payload: object) -> None:
        self._hover_pixel_info = payload if isinstance(payload, dict) else None
        self._refresh_canvas_status_strip()
        self._refresh_navigation_overlays()

    def _handle_navigator_center_requested(self, image_x: float, image_y: float) -> None:
        if self.document is None:
            return
        viewport = self.canvas_scroll.viewport().size()
        hbar = self.canvas_scroll.horizontalScrollBar()
        vbar = self.canvas_scroll.verticalScrollBar()
        target_x, target_y = texture_editor_center_scroll_values(
            image_x=image_x,
            image_y=image_y,
            display_scale=self.canvas.current_display_scale(),
            viewport_width=viewport.width(),
            viewport_height=viewport.height(),
            horizontal_minimum=hbar.minimum(),
            horizontal_maximum=hbar.maximum(),
            vertical_minimum=vbar.minimum(),
            vertical_maximum=vbar.maximum(),
        )
        hbar.setValue(target_x)
        vbar.setValue(target_y)
        document_key = texture_editor_document_key(self.document)
        if document_key:
            self.workspace.document_view_state[document_key] = self._capture_view_state()

    def _capture_view_state(self) -> Dict[str, object]:
        return texture_editor_view_state_payload(
            zoom_factor=self.canvas.current_display_scale(),
            fit_to_view=self.canvas.is_fit_to_view(),
            view_mode=texture_editor_view_mode_key(self.view_mode_combo.currentData()),
            compare_split=self.compare_split_slider.value(),
            grid_enabled=self.grid_checkbox.isChecked(),
            grid_size=self.grid_size_spin.value(),
            grid_color=texture_editor_grid_color_hex(self._grid_color.name(QColor.HexRgb)),
            grid_opacity=self.grid_opacity_spin.value(),
            show_rulers=self._show_rulers,
            show_guides=self._show_guides,
            vertical_guides=self._vertical_guides,
            horizontal_guides=self._horizontal_guides,
            scroll_x=self.canvas_scroll.horizontalScrollBar().value(),
            scroll_y=self.canvas_scroll.verticalScrollBar().value(),
        )

    def _apply_view_state(self, state: Optional[Dict[str, object]]) -> None:
        if not state:
            self.show_rulers_checkbox.blockSignals(True)
            self.show_guides_checkbox.blockSignals(True)
            self.show_rulers_checkbox.setChecked(True)
            self.show_guides_checkbox.setChecked(False)
            self.show_rulers_checkbox.blockSignals(False)
            self.show_guides_checkbox.blockSignals(False)
            self._show_rulers = True
            self._show_guides = False
            self._vertical_guides = ()
            self._horizontal_guides = ()
            self.vertical_guides_edit.setText("")
            self.horizontal_guides_edit.setText("")
            self.canvas.set_zoom_factor(1.0)
            self.canvas_scroll.horizontalScrollBar().setValue(0)
            self.canvas_scroll.verticalScrollBar().setValue(0)
            self._refresh_zoom_indicators()
            self._refresh_navigation_overlays()
            return
        view_state = texture_editor_resolved_view_state(
            state,
            default_compare_split=self.compare_split_slider.value(),
            default_grid_enabled=self.grid_checkbox.isChecked(),
            default_grid_size=self.grid_size_spin.value(),
            default_grid_color=texture_editor_grid_color_hex(self._grid_color.name(QColor.HexRgb)),
            default_grid_opacity=self.grid_opacity_spin.value(),
        )
        index = self.view_mode_combo.findData(view_state.view_mode)
        if index >= 0:
            self.view_mode_combo.blockSignals(True)
            self.view_mode_combo.setCurrentIndex(index)
            self.view_mode_combo.blockSignals(False)
        self.compare_split_slider.blockSignals(True)
        self.compare_split_slider.setValue(view_state.compare_split)
        self.compare_split_slider.blockSignals(False)
        self.grid_checkbox.blockSignals(True)
        self.grid_checkbox.setChecked(view_state.grid_enabled)
        self.grid_checkbox.blockSignals(False)
        self.grid_size_spin.blockSignals(True)
        self.grid_size_spin.setValue(view_state.grid_size)
        self.grid_size_spin.blockSignals(False)
        self._set_grid_color(QColor(view_state.grid_color), save=False, apply=False)
        self.grid_opacity_spin.blockSignals(True)
        self.grid_opacity_spin.setValue(view_state.grid_opacity)
        self.grid_opacity_spin.blockSignals(False)
        self.show_rulers_checkbox.blockSignals(True)
        self.show_guides_checkbox.blockSignals(True)
        self.show_rulers_checkbox.setChecked(view_state.show_rulers)
        self.show_guides_checkbox.setChecked(view_state.show_guides)
        self.show_rulers_checkbox.blockSignals(False)
        self.show_guides_checkbox.blockSignals(False)
        self._show_rulers = bool(self.show_rulers_checkbox.isChecked())
        self._show_guides = bool(self.show_guides_checkbox.isChecked())
        self._vertical_guides = view_state.vertical_guides
        self._horizontal_guides = view_state.horizontal_guides
        self.vertical_guides_edit.setText(format_texture_editor_guides_text(self._vertical_guides))
        self.horizontal_guides_edit.setText(format_texture_editor_guides_text(self._horizontal_guides))
        if view_state.fit_to_view:
            self.canvas.set_fit_to_view(True)
        else:
            self.canvas.set_zoom_factor(view_state.zoom_factor)
            self.canvas_scroll.horizontalScrollBar().setValue(view_state.scroll_x)
            self.canvas_scroll.verticalScrollBar().setValue(view_state.scroll_y)
        self._refresh_zoom_indicators()
        self._refresh_navigation_overlays()

    def _adjust_zoom(self, step: int) -> None:
        self._set_zoom(texture_editor_zoom_factor_for_step(self.canvas.current_display_scale(), step))

    def _handle_canvas_wheel_zoom(self, delta: int, widget_x: int, widget_y: int) -> None:
        if self.document is None:
            return
        old_scale = max(0.0001, self.canvas.current_display_scale())
        viewport_pos = self.canvas.mapTo(self.canvas_scroll.viewport(), QPoint(int(widget_x), int(widget_y)))
        viewport_x = viewport_pos.x()
        viewport_y = viewport_pos.y()
        self._set_zoom(old_scale * texture_editor_wheel_zoom_multiplier(delta))
        new_scale = max(0.0001, self.canvas.current_display_scale())
        scroll_x, scroll_y = texture_editor_zoom_scroll_targets(
            widget_x=widget_x,
            widget_y=widget_y,
            old_scale=old_scale,
            new_scale=new_scale,
            viewport_x=viewport_x,
            viewport_y=viewport_y,
        )
        self.canvas_scroll.horizontalScrollBar().setValue(scroll_x)
        self.canvas_scroll.verticalScrollBar().setValue(scroll_y)
        document_key = texture_editor_document_key(self.document)
        if document_key:
            self.workspace.document_view_state[document_key] = self._capture_view_state()

    def _refresh_zoom_indicators(self) -> None:
        labels = texture_editor_zoom_labels(
            self.canvas.current_display_scale(),
            fit_to_view=self.canvas.is_fit_to_view(),
            has_document=self.document is not None,
        )
        self.zoom_label.setText(labels.zoom_label)
        self.canvas_status_zoom_label.setText(labels.canvas_status_zoom_label)

    def _set_fit_mode(self, fit_to_view: bool) -> None:
        self.canvas.set_fit_to_view(fit_to_view)
        self._refresh_zoom_indicators()
        self._refresh_navigation_overlays()
        document_key = texture_editor_document_key(self.document)
        if document_key:
            self.workspace.document_view_state[document_key] = self._capture_view_state()

    def _set_zoom(self, factor: float) -> None:
        self.canvas.set_zoom_factor(factor)
        self._refresh_zoom_indicators()
        self._refresh_navigation_overlays()
        document_key = texture_editor_document_key(self.document)
        if document_key:
            self.workspace.document_view_state[document_key] = self._capture_view_state()

    def _handle_view_mode_changed(self) -> None:
        mode = texture_editor_view_mode_key(self.view_mode_combo.currentData())
        controls = texture_editor_view_controls_state(
            mode,
            has_document=self.document is not None,
            busy=self._busy(),
            grid_enabled=self.grid_checkbox.isChecked(),
        )
        self.compare_split_slider.setVisible(controls.compare_split_visible)
        self.compare_split_slider.setEnabled(controls.compare_split_enabled)
        self.canvas.set_view_mode(mode)
        self._refresh_navigation_overlays()
        document_key = texture_editor_document_key(self.document)
        if document_key:
            self.workspace.document_view_state[document_key] = self._capture_view_state()
        self._save_settings()

    def _handle_compare_split_changed(self, value: int) -> None:
        self.canvas.set_compare_split_percent(value)
        self._refresh_navigation_overlays()
        document_key = texture_editor_document_key(self.document)
        if document_key:
            self.workspace.document_view_state[document_key] = self._capture_view_state()
        self._save_settings()

    def _handle_grid_state_changed(self, *_args) -> None:
        grid_color = QColor(getattr(self, "_grid_color", QColor("#74C1FF")))
        grid_state = texture_editor_grid_control_state(
            enabled=self.grid_checkbox.isChecked(),
            grid_size=self.grid_size_spin.value(),
            grid_color=grid_color,
            grid_color_hex=grid_color.name(QColor.HexRgb),
            grid_opacity=self.grid_opacity_spin.value(),
        )
        self.canvas.set_grid_state(
            enabled=grid_state.enabled,
            grid_size=grid_state.grid_size,
            grid_color=grid_state.grid_color,
            grid_opacity=grid_state.grid_opacity,
        )
        self._refresh_navigation_overlays()
        document_key = texture_editor_document_key(self.document)
        if document_key:
            self.workspace.document_view_state[document_key] = self._capture_view_state()
        self._save_settings()

    def _set_grid_color(self, color: QColor, *, save: bool = True, apply: bool = True) -> None:
        resolved = QColor(color) if color.isValid() else QColor("#74C1FF")
        self._grid_color = resolved
        self._update_grid_color_button()
        if apply:
            self._handle_grid_state_changed()
        elif save:
            self._save_settings()

    def _update_grid_color_button(self) -> None:
        color = QColor(self._grid_color if self._grid_color.isValid() else QColor("#74C1FF"))
        state = texture_editor_grid_color_button_state(texture_editor_grid_color_hex(color.name(QColor.HexRgb)))
        self.grid_color_button.setStyleSheet(state.style_sheet)
        self.grid_color_button.setText(state.text)
        self.grid_color_button.setToolTip(state.tooltip)

    def _pick_grid_color(self) -> None:
        chosen = QColorDialog.getColor(self._grid_color, self, "Select grid color")
        if not chosen.isValid():
            return
        self._set_grid_color(chosen)

    def _handle_canvas_viewport_changed(self, *_args) -> None:
        self._refresh_zoom_indicators()
        self._refresh_navigation_overlays()
        document_key = texture_editor_document_key(self.document)
        if document_key:
            self.workspace.document_view_state[document_key] = self._capture_view_state()


__all__ = ["TextureEditorViewCoordinationMixin"]
