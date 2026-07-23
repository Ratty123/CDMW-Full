"""Typed control context for static replacement prompt state wiring."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeVar

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QPushButton, QWidget


_WidgetT = TypeVar("_WidgetT", bound=QWidget)


def _required_widget(
    context: Mapping[str, object],
    name: str,
    expected_type: type[_WidgetT],
) -> _WidgetT:
    value = context.get(name)
    if not isinstance(value, expected_type):
        actual = type(value).__name__ if value is not None else "missing"
        raise TypeError(
            f"Static replacement prompt state control {name!r} must be "
            f"{expected_type.__name__}; got {actual}."
        )
    return value


def _required_timer(context: Mapping[str, object], name: str) -> QTimer:
    value = context.get(name)
    if not isinstance(value, QTimer):
        actual = type(value).__name__ if value is not None else "missing"
        raise TypeError(
            f"Static replacement prompt state control {name!r} must be QTimer; got {actual}."
        )
    return value


@dataclass(frozen=True, slots=True)
class StaticReplacementPromptStateControls:
    """Required Qt controls at the Builder state-callback boundary."""

    alignment_d3d11_reload_timer: QTimer
    alignment_d3d11_status_timer: QTimer
    alignment_d3d11_view_mode_combo: QComboBox
    alignment_preview_settings_button: QPushButton
    alignment_use_global_preview_button: QPushButton
    overlay_original_locked_checkbox: QCheckBox
    preview_depth_spin: QDoubleSpinBox
    preview_disable_brightness_checkbox: QCheckBox
    preview_disable_tint_checkbox: QCheckBox
    preview_disable_uv_scale_checkbox: QCheckBox
    preview_mesh_view_combo: QComboBox
    preview_mode_combo: QComboBox
    preview_render_mode_combo: QComboBox
    preview_renderer_combo: QComboBox
    preview_rough_spin: QDoubleSpinBox
    preview_shine_spin: QDoubleSpinBox
    preview_support_maps_checkbox: QCheckBox
    preview_visible_mode_combo: QComboBox

    @classmethod
    def from_mapping(
        cls,
        context: Mapping[str, object],
    ) -> "StaticReplacementPromptStateControls":
        return cls(
            alignment_d3d11_reload_timer=_required_timer(
                context,
                "alignment_d3d11_reload_timer",
            ),
            alignment_d3d11_status_timer=_required_timer(
                context,
                "alignment_d3d11_status_timer",
            ),
            alignment_d3d11_view_mode_combo=_required_widget(
                context,
                "alignment_d3d11_view_mode_combo",
                QComboBox,
            ),
            alignment_preview_settings_button=_required_widget(
                context,
                "alignment_preview_settings_button",
                QPushButton,
            ),
            alignment_use_global_preview_button=_required_widget(
                context,
                "alignment_use_global_preview_button",
                QPushButton,
            ),
            overlay_original_locked_checkbox=_required_widget(
                context,
                "overlay_original_locked_checkbox",
                QCheckBox,
            ),
            preview_depth_spin=_required_widget(
                context,
                "preview_depth_spin",
                QDoubleSpinBox,
            ),
            preview_disable_brightness_checkbox=_required_widget(
                context,
                "preview_disable_brightness_checkbox",
                QCheckBox,
            ),
            preview_disable_tint_checkbox=_required_widget(
                context,
                "preview_disable_tint_checkbox",
                QCheckBox,
            ),
            preview_disable_uv_scale_checkbox=_required_widget(
                context,
                "preview_disable_uv_scale_checkbox",
                QCheckBox,
            ),
            preview_mesh_view_combo=_required_widget(
                context,
                "preview_mesh_view_combo",
                QComboBox,
            ),
            preview_mode_combo=_required_widget(
                context,
                "preview_mode_combo",
                QComboBox,
            ),
            preview_render_mode_combo=_required_widget(
                context,
                "preview_render_mode_combo",
                QComboBox,
            ),
            preview_renderer_combo=_required_widget(
                context,
                "preview_renderer_combo",
                QComboBox,
            ),
            preview_rough_spin=_required_widget(
                context,
                "preview_rough_spin",
                QDoubleSpinBox,
            ),
            preview_shine_spin=_required_widget(
                context,
                "preview_shine_spin",
                QDoubleSpinBox,
            ),
            preview_support_maps_checkbox=_required_widget(
                context,
                "preview_support_maps_checkbox",
                QCheckBox,
            ),
            preview_visible_mode_combo=_required_widget(
                context,
                "preview_visible_mode_combo",
                QComboBox,
            ),
        )


__all__ = ["StaticReplacementPromptStateControls"]
