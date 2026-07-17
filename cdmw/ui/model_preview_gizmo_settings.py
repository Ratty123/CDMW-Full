"""Shared Preview Settings controls for the resident placement Gizmo."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from cdmw.models import MODEL_PREVIEW_RENDER_LIMITS, ModelPreviewRenderSettings


GIZMO_COLOR_SETTING_FIELDS = (
    "gizmo_x_axis_color",
    "gizmo_y_axis_color",
    "gizmo_z_axis_color",
    "gizmo_highlight_color",
    "gizmo_label_color",
)

GIZMO_NUMERIC_SETTING_FIELDS = (
    "gizmo_line_thickness_pixels",
    "gizmo_size_scale",
    "gizmo_label_size_pixels",
    "gizmo_handle_size_pixels",
)

GIZMO_APPEARANCE_SETTING_FIELDS = GIZMO_COLOR_SETTING_FIELDS + GIZMO_NUMERIC_SETTING_FIELDS


class _PreviewColorButton(QPushButton):
    valueChanged = Signal()

    def __init__(self, value: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(value)
        self.setObjectName("PreviewColorButton")
        self.clicked.connect(self._choose_color)
        self._refresh_appearance()

    def value(self) -> str:
        return self._color.name().upper()

    def set_value(self, value: object) -> None:
        color = QColor(str(value or ""))
        if not color.isValid():
            return
        self._color = color
        self._refresh_appearance()

    def _choose_color(self) -> None:
        color = QColorDialog.getColor(
            self._color,
            self,
            "Choose Gizmo Color",
        )
        if not color.isValid():
            return
        color.setAlpha(255)
        if color == self._color:
            return
        self._color = color
        self._refresh_appearance()
        self.valueChanged.emit()

    def _refresh_appearance(self) -> None:
        value = self.value()
        text_color = "#111111" if self._color.lightness() >= 145 else "#F7F9FC"
        self.setText(value)
        self.setStyleSheet(
            "QPushButton#PreviewColorButton {"
            f"background-color: {value}; color: {text_color};"
            "border: 1px solid #5B6470; border-radius: 3px; padding: 5px 10px;"
            "}"
        )


class GizmoPreviewSettingsPanel(QScrollArea):
    """Live appearance editor backed by ``ModelPreviewRenderSettings``."""

    settings_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._applying_settings = False
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)
        self.setWidget(content)

        intro = QLabel(
            "Customize the placement Gizmo used by the resident Mesh Editor preview. "
            "Changes apply live and are saved with Preview Settings."
        )
        intro.setObjectName("HintLabel")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        layout.addLayout(form)

        defaults = ModelPreviewRenderSettings()
        self.controls_by_key: dict[str, QWidget] = {}
        for key, label in (
            ("gizmo_x_axis_color", "X axis color"),
            ("gizmo_y_axis_color", "Y axis color"),
            ("gizmo_z_axis_color", "Z axis color"),
            ("gizmo_highlight_color", "Active/hover color"),
            ("gizmo_label_color", "Label color"),
        ):
            control = _PreviewColorButton(str(getattr(defaults, key)))
            control.valueChanged.connect(self._emit_settings_changed)
            self.controls_by_key[key] = control
            form.addRow(label, control)

        for key, label, step, decimals, suffix in (
            ("gizmo_line_thickness_pixels", "Line thickness", 0.25, 2, " px"),
            ("gizmo_size_scale", "Overall size", 0.05, 2, " x"),
            ("gizmo_label_size_pixels", "Font/label size", 1.0, 0, " px"),
            ("gizmo_handle_size_pixels", "Handle size", 1.0, 0, " px"),
        ):
            minimum, maximum = MODEL_PREVIEW_RENDER_LIMITS[key]
            control = QDoubleSpinBox()
            control.setRange(float(minimum), float(maximum))
            control.setSingleStep(float(step))
            control.setDecimals(int(decimals))
            control.setSuffix(suffix)
            control.valueChanged.connect(self._emit_settings_changed)
            self.controls_by_key[key] = control
            form.addRow(label, control)

        reset_button = QPushButton("Reset Gizmo to Defaults")
        reset_button.clicked.connect(self.reset_to_defaults)
        layout.addWidget(reset_button)

        placement_note = QLabel(
            "The Gizmo is a placement aid. It is hidden and inactive whenever Edit Mesh is enabled."
        )
        placement_note.setObjectName("HintLabel")
        placement_note.setWordWrap(True)
        layout.addWidget(placement_note)
        layout.addStretch(1)

        self.set_settings(defaults)

    def apply_to(self, settings: ModelPreviewRenderSettings) -> None:
        for key in GIZMO_COLOR_SETTING_FIELDS:
            control = self.controls_by_key[key]
            setattr(settings, key, control.value())  # type: ignore[attr-defined]
        for key in GIZMO_NUMERIC_SETTING_FIELDS:
            control = self.controls_by_key[key]
            setattr(settings, key, float(control.value()))  # type: ignore[attr-defined]

    def set_settings(self, settings: ModelPreviewRenderSettings) -> None:
        self._applying_settings = True
        try:
            for key in GIZMO_COLOR_SETTING_FIELDS:
                self.controls_by_key[key].set_value(getattr(settings, key))  # type: ignore[attr-defined]
            for key in GIZMO_NUMERIC_SETTING_FIELDS:
                self.controls_by_key[key].setValue(float(getattr(settings, key)))  # type: ignore[attr-defined]
        finally:
            self._applying_settings = False

    def reset_to_defaults(self) -> None:
        self.set_settings(ModelPreviewRenderSettings())
        self.settings_changed.emit()

    def _emit_settings_changed(self, *_args: object) -> None:
        if not self._applying_settings:
            self.settings_changed.emit()


__all__ = [
    "GIZMO_APPEARANCE_SETTING_FIELDS",
    "GIZMO_COLOR_SETTING_FIELDS",
    "GIZMO_NUMERIC_SETTING_FIELDS",
    "GizmoPreviewSettingsPanel",
]
