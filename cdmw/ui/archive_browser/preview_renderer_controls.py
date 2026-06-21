"""Archive model preview renderer selection and widget-control helpers."""

from __future__ import annotations

import dataclasses
from typing import Optional, Tuple

from cdmw.ui.model_preview_native import (
    ARCHIVE_MODEL_RENDERER_D3D11,
    ARCHIVE_MODEL_RENDERER_DEFAULT,
    normalize_archive_model_renderer_backend,
)


class ArchivePreviewRendererControlsMixin:
    """Renderer backend state and preview widget control helpers."""

    def _archive_model_renderer_backend(self) -> str:
        return normalize_archive_model_renderer_backend(
            getattr(self, "archive_model_renderer_backend", ARCHIVE_MODEL_RENDERER_DEFAULT)
        )

    def _read_archive_model_renderer_backend(self) -> str:
        return normalize_archive_model_renderer_backend(
            self.settings.value("preview/archive_renderer_backend", ARCHIVE_MODEL_RENDERER_DEFAULT)
        )

    def _archive_model_preview_widgets(self) -> Tuple[object, ...]:
        return (self.archive_model_preview,)

    def _selected_archive_model_preview_widget(self) -> object:
        return self.archive_model_preview

    def _active_archive_model_preview_widget(self) -> Optional[object]:
        current = self.archive_preview_stack.currentWidget()
        for widget in self._archive_model_preview_widgets():
            if current is widget:
                return widget
        return None

    def _pause_archive_model_preview_widgets(self) -> None:
        for widget in self._archive_model_preview_widgets():
            pause_timers = getattr(widget, "pause_interactive_timers", None)
            if callable(pause_timers):
                pause_timers()

    def _cancel_archive_isolated_package_worker_for_non_model_preview(self) -> None:
        self.archive_isolated_package_pending_result = None
        self.archive_isolated_package_request_id += 1
        worker = getattr(self, "archive_isolated_package_worker", None)
        if worker is not None:
            worker.stop()

    def _deactivate_archive_model_renderers_for_non_model_preview(self) -> None:
        self._pause_archive_model_preview_widgets()
        self._cancel_archive_isolated_package_worker_for_non_model_preview()
        if (
            self._archive_isolated_renderer_process_running()
            or getattr(self, "archive_isolated_renderer_active_package", None) is not None
        ):
            self._shutdown_archive_isolated_renderer_host()

    def _archive_model_renderer_status_note(self, selected_widget: Optional[object] = None) -> str:
        return ""

    def _detail_text_with_renderer_note(self, detail_text: str, selected_widget: Optional[object]) -> str:
        return str(detail_text or "")

    def _archive_model_preview_controls_target(self) -> Optional[object]:
        if self.archive_preview_showing_loose:
            return None
        current_widget = self.archive_preview_stack.currentWidget()
        if (
            self._active_archive_model_preview_widget() is None
            and current_widget is not self.archive_d3d11_preview_host
        ):
            return None
        if self.current_archive_preview_result is None:
            return None
        return self.current_archive_preview_result.preview_model

    def _sync_archive_model_preview_debug_controls(self, preview_model: Optional[object]) -> None:
        active_preview = self._active_archive_model_preview_widget()
        native_panel_active = active_preview is self.archive_model_preview
        controls_visible = (
            preview_model is not None
            and not self.archive_preview_showing_loose
            and native_panel_active
        )
        supports_textures = bool(controls_visible and self.archive_model_preview.textures_available())
        supports_support_maps = bool(controls_visible and self.archive_model_preview.support_maps_available())
        for widget in (
            self.archive_model_preview_flip_v_checkbox,
            self.archive_model_preview_disable_support_checkbox,
            self.archive_model_preview_reset_overrides_button,
        ):
            widget.setVisible(controls_visible)
        self.archive_model_preview_flip_v_checkbox.setEnabled(supports_textures)
        self.archive_model_preview_disable_support_checkbox.setEnabled(supports_support_maps)
        self.archive_model_preview_reset_overrides_button.setEnabled(
            bool(controls_visible and self.archive_model_preview.debug_overrides_active())
        )
        self.archive_model_preview_flip_v_checkbox.blockSignals(True)
        self.archive_model_preview_flip_v_checkbox.setChecked(
            bool(controls_visible and self.archive_model_preview.base_flip_override_enabled())
        )
        self.archive_model_preview_flip_v_checkbox.blockSignals(False)
        self.archive_model_preview_disable_support_checkbox.blockSignals(True)
        self.archive_model_preview_disable_support_checkbox.setChecked(
            bool(controls_visible and self.archive_model_preview.support_maps_disabled())
        )
        self.archive_model_preview_disable_support_checkbox.blockSignals(False)

    def _handle_archive_model_preview_flip_v_toggled(self, checked: bool) -> None:
        self.archive_model_preview.set_base_texture_flip_override_enabled(bool(checked))
        self._sync_current_archive_preview_model_from_widget()
        self._sync_archive_model_preview_debug_controls(self._archive_model_preview_controls_target())

    def _handle_archive_model_preview_disable_support_maps_toggled(self, checked: bool) -> None:
        self.archive_model_preview.set_support_maps_disabled(bool(checked))
        self._sync_current_archive_preview_model_from_widget()
        self._sync_archive_model_preview_debug_controls(self._archive_model_preview_controls_target())

    def _handle_archive_model_preview_reset_overrides(self) -> None:
        self.archive_model_preview.reset_preview_overrides()
        self._sync_current_archive_preview_model_from_widget()
        self._sync_archive_model_preview_debug_controls(self._archive_model_preview_controls_target())

    def _sync_current_archive_preview_model_from_widget(self) -> None:
        if self.current_archive_preview_result is None or self.archive_preview_showing_loose:
            return
        active_preview = self._active_archive_model_preview_widget() or self.archive_model_preview
        if not hasattr(active_preview, "current_model_preview"):
            return
        preview_model = active_preview.current_model_preview()
        if preview_model is None:
            return
        self.current_archive_preview_result = dataclasses.replace(
            self.current_archive_preview_result,
            preview_model=preview_model,
        )

    def _handle_archive_model_preview_darkmode_toggled(self, checked: bool) -> None:
        self.archive_model_preview_dark_background_enabled = bool(checked)
        for widget in self._archive_model_preview_widgets():
            if hasattr(widget, "set_dark_background_enabled"):
                widget.set_dark_background_enabled(bool(checked))
        if (
            self._archive_model_renderer_backend() == ARCHIVE_MODEL_RENDERER_D3D11
            and self.current_archive_preview_result is not None
            and not self.archive_preview_showing_loose
            and getattr(self.current_archive_preview_result, "preview_model", None) is not None
        ):
            self._launch_archive_isolated_preview_result(self.current_archive_preview_result)
        self.schedule_settings_save()
