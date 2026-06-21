"""Preview zoom/control helpers for Research tab preview panes."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtWidgets import QLabel, QPushButton

from cdmw.ui.research.state import next_preview_zoom_factor, preview_zoom_label

__all__ = [
    "apply_preview_zoom",
    "next_manual_preview_zoom",
    "set_preview_image_controls_enabled",
    "set_preview_zoom_label",
]


def set_preview_zoom_label(
    zoom_value_label: QLabel,
    *,
    fit_to_view: bool,
    zoom_factor: float,
) -> None:
    zoom_value_label.setText(preview_zoom_label(fit_to_view=fit_to_view, zoom_factor=zoom_factor))


def set_preview_image_controls_enabled(
    enabled: bool,
    *,
    buttons: Sequence[QPushButton],
    zoom_value_label: QLabel,
    refresh_label: Callable[[], None],
) -> None:
    for button in buttons:
        button.setEnabled(enabled)
    if enabled:
        refresh_label()
    else:
        zoom_value_label.setText("-")


def apply_preview_zoom(
    preview_label: object,
    zoom_value_label: QLabel,
    *,
    fit_to_view: bool,
    zoom_factor: float,
) -> None:
    preview_label.set_fit_to_view(fit_to_view)
    preview_label.set_zoom_factor(zoom_factor)
    set_preview_zoom_label(zoom_value_label, fit_to_view=fit_to_view, zoom_factor=zoom_factor)


def next_manual_preview_zoom(
    *,
    current_display_scale: float,
    fit_to_view: bool,
    zoom_factor: float,
    step: int,
) -> float:
    current_zoom = current_display_scale if fit_to_view else zoom_factor
    return next_preview_zoom_factor(current_zoom, step)
