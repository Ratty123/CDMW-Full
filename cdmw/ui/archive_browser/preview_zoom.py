"""Archive preview zoom and view-state helpers."""

from __future__ import annotations

from collections.abc import Mapping


class ArchivePreviewZoomMixin:
    """Archive preview zoom controls and D3D11 view-state hooks."""
    def _active_archive_preview_zoom_widget(self):
        current_widget = self.archive_preview_stack.currentWidget()
        if current_widget is self.archive_preview_scroll:
            return self.archive_preview_label
        if current_widget is self.archive_d3d11_preview_host:
            return self.archive_d3d11_preview_host
        active_model_preview = self._active_archive_model_preview_widget()
        if active_model_preview is not None:
            return active_model_preview
        return None

    def _handle_archive_d3d11_view_state_payload(self, payload: object) -> None:
        if not isinstance(payload, Mapping):
            return
        if self.archive_preview_stack.currentWidget() is not self.archive_d3d11_preview_host:
            return
        view_state = self._sanitize_d3d11_view_state_for_restore(
            self.archive_d3d11_preview_host.view_state_snapshot()
        )
        if view_state:
            self.archive_d3d11_view_state = view_state
            self.archive_d3d11_has_view_state = True

    def _handle_archive_model_view_state_changed(self, zoom_factor: float, fit_to_view: bool) -> None:
        if (
            self._active_archive_model_preview_widget() is None
            and self.archive_preview_stack.currentWidget() is not self.archive_d3d11_preview_host
        ):
            return
        self.archive_preview_zoom_factor = min(max(float(zoom_factor), 0.1), 16.0)
        self.archive_preview_fit_to_view = bool(fit_to_view)
        self._update_archive_preview_zoom_label()

    def _update_archive_preview_zoom_label(self) -> None:
        if self.archive_preview_fit_to_view:
            self.archive_preview_zoom_value.setText("Fit")
        else:
            self.archive_preview_zoom_value.setText(f"{int(round(self.archive_preview_zoom_factor * 100))}%")

    def _apply_archive_preview_zoom(self) -> None:
        target = self._active_archive_preview_zoom_widget()
        if target is not None:
            target.set_fit_to_view(self.archive_preview_fit_to_view)
            target.set_zoom_factor(self.archive_preview_zoom_factor)
        self._update_archive_preview_zoom_label()

    def _set_archive_preview_fit_mode(self) -> None:
        self.archive_preview_fit_to_view = True
        self._apply_archive_preview_zoom()

    def _set_archive_preview_zoom_factor(self, zoom_factor: float) -> None:
        self.archive_preview_fit_to_view = False
        self.archive_preview_zoom_factor = min(max(zoom_factor, 0.1), 16.0)
        self._apply_archive_preview_zoom()

    def _adjust_archive_preview_zoom(self, step: int) -> None:
        target = self._active_archive_preview_zoom_widget()
        current_zoom = (
            target.current_display_scale()
            if self.archive_preview_fit_to_view and target is not None
            else self.archive_preview_zoom_factor
        )
        zoom_steps = [0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 16.0]
        closest_index = min(range(len(zoom_steps)), key=lambda idx: abs(zoom_steps[idx] - current_zoom))
        next_index = min(max(closest_index + step, 0), len(zoom_steps) - 1)
        self._set_archive_preview_zoom_factor(zoom_steps[next_index])
