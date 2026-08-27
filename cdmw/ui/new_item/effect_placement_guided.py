"""Guided Step 5 presentation for the resident effect placement viewport."""

from __future__ import annotations

import math
from typing import Optional, Tuple

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from cdmw.ui.new_item.effect_placement_dialog_support import (
    BACKDROP_BLACK,
    BACKDROP_DARK,
    BACKDROP_GREY,
    remembered_backdrop,
)
from cdmw.ui.mesh_editor.icons import mesh_editor_action_icon

Vec3 = Tuple[float, float, float]


class _GuidedToolbarPanel(QWidget):
    resized = Signal(int)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        width = self.width()
        self.resized.emit(width)
        QTimer.singleShot(0, lambda: self.resized.emit(width))


class EffectPlacementGuidedMixin:
    """Rearrange the compatibility controls into the approved resident workspace."""

    def _build_guided_presentation(self, root: QVBoxLayout) -> None:
        while root.count():
            root.takeAt(0)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setObjectName("effect_placement_splitter")
        splitter.setChildrenCollapsible(False)
        self.preview_splitter = splitter
        splitter.addWidget(self._guided_viewport_panel(splitter))
        splitter.addWidget(self._guided_inspector_panel(splitter))
        splitter.setStretchFactor(0, 13)
        splitter.setStretchFactor(1, 7)
        splitter.setSizes([650, 340])
        root.addWidget(splitter, 1)
        self._hide_compatibility_controls()

    def _guided_viewport_panel(self, parent: QWidget) -> QWidget:
        viewport = QWidget(parent)
        viewport.setObjectName("effect_viewport_panel")
        viewport.setMinimumWidth(480)
        layout = QVBoxLayout(viewport)
        layout.setContentsMargins(12, 8, 0, 8)
        layout.setSpacing(8)

        toolbar_panel = _GuidedToolbarPanel(viewport)
        toolbar_panel.setObjectName("effect_toolbar")
        toolbar = QGridLayout(toolbar_panel)
        toolbar.setContentsMargins(0, 0, 4, 0)
        toolbar.setHorizontalSpacing(4)
        toolbar.setVerticalSpacing(4)
        self._ensure_guided_view_buttons()
        self.view_buttons[-1].setVisible(False)
        self.frame_button = QPushButton("Frame")
        self.frame_button.setToolTip("Frame the item and the visible effect bounds without changing placement.")
        self.frame_button.clicked.connect(self._frame_subject)
        self._guided_toolbar_buttons = (
            self.move_button,
            self.rotate_button,
            self.scale_button,
            *self.view_buttons[:3],
            self.frame_button,
            self.pause_button,
        )
        toolbar_keys = (
            "transform_move",
            "transform_rotate",
            "transform_scale",
            "view_front",
            "view_side",
            "view_top",
            "frame",
            "pause",
        )
        for button, key in zip(self._guided_toolbar_buttons, toolbar_keys):
            button.setIcon(mesh_editor_action_icon(key, self.palette()))
            button.setProperty("effectToolbarButton", True)
            button.setFixedHeight(32)
            button.setIconSize(QSize(14, 14))
            button.setMinimumWidth(button.fontMetrics().horizontalAdvance(button.text()) + 20)
        self.guided_toolbar_panel = toolbar_panel
        self.guided_toolbar_layout = toolbar
        self._guided_toolbar_columns = 0
        toolbar_panel.resized.connect(self._reflow_guided_toolbar)
        QTimer.singleShot(0, lambda: self._reflow_guided_toolbar(toolbar_panel.width()))
        self._set_viewport_controls_available(self.host is not None)
        layout.addWidget(toolbar_panel)
        if self.host is not None:
            self.host.setMinimumSize(480, 360)
            layout.addWidget(self.host, 1)
        elif self.viewport_missing is not None:
            layout.addWidget(self.viewport_missing, 1)
        self.status.setObjectName("effect_workspace_status")
        layout.addWidget(self.status)
        return viewport

    def _reflow_guided_toolbar(self, width: int) -> None:
        buttons = self._guided_toolbar_buttons
        spacing = self.guided_toolbar_layout.horizontalSpacing()
        required = sum(button.minimumWidth() for button in buttons) + spacing * (len(buttons) - 1) + 4
        columns = len(buttons) if int(width) >= max(560, required) else 4
        if columns == self._guided_toolbar_columns:
            return
        self._guided_toolbar_columns = columns
        while self.guided_toolbar_layout.count():
            self.guided_toolbar_layout.takeAt(0)
        for column in range(len(buttons)):
            self.guided_toolbar_layout.setColumnStretch(column, 1 if column < columns else 0)
        for index, button in enumerate(buttons):
            self.guided_toolbar_layout.addWidget(button, index // columns, index % columns)
        rows = (len(buttons) + columns - 1) // columns
        height = rows * 32 + (rows - 1) * self.guided_toolbar_layout.verticalSpacing()
        self.guided_toolbar_panel.setFixedHeight(height)
        self.guided_toolbar_layout.setGeometry(self.guided_toolbar_panel.rect())
        self.guided_toolbar_panel.updateGeometry()

    def _ensure_guided_view_buttons(self) -> None:
        if self.view_buttons:
            return
        for index, title in enumerate(("Front", "Side", "Top", "Angled")):
            yaw, pitch = self._standing_view_angles[index]
            button = QPushButton(title)
            button.setCheckable(True)
            self.view_group.addButton(button)
            button.clicked.connect(lambda _checked=False, y=yaw, p=pitch: self._look_from(y, p))
            self.view_buttons.append(button)
        self.view_buttons[-1].setChecked(True)

    def _set_viewport_controls_available(self, available: bool) -> None:
        for button in (
            self.move_button,
            self.rotate_button,
            self.scale_button,
            *self.view_buttons,
            self.frame_button,
            self.pause_button,
            self.show_reach,
            self.backdrop_choice,
            self.show_character,
        ):
            button.setEnabled(bool(available))

    def _guided_inspector_panel(self, parent: QWidget) -> QScrollArea:
        scroll = QScrollArea(parent)
        scroll.setObjectName("effect_inspector_scroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(340)
        inspector = QWidget()
        inspector.setObjectName("effect_inspector")
        layout = QVBoxLayout(inspector)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        scroll.setWidget(inspector)
        self.inspector_widget = inspector

        heading = QLabel("Placement & Look")
        heading.setObjectName("effect_inspector_heading")
        layout.addWidget(heading)
        self._add_guided_transform_controls(layout)
        self._add_guided_scene_controls(layout)
        self._add_guided_look_controls(layout)
        layout.addStretch(1)
        return scroll

    def _add_guided_transform_controls(self, layout: QVBoxLayout) -> None:
        scale_row = QHBoxLayout()
        scale_row.addWidget(QLabel("Scale"))
        scale_row.addStretch(1)
        self.scale_spin.setMinimumWidth(182)
        scale_row.addWidget(self.scale_spin)
        layout.addLayout(scale_row)

        self._add_guided_axis_row(layout, "Position", self.offset_spins)
        self._add_guided_axis_row(layout, "Rotation", self.rotation_spins)

        anchor_row = QHBoxLayout()
        anchor_row.addWidget(QLabel("Anchor"))
        self.anchor_choice = QComboBox()
        self.anchor_choice.addItem("Origin", "origin")
        self.anchor_choice.addItem("Center", "center")
        self.anchor_choice.addItem("End", "end")
        self.anchor_choice.currentIndexChanged.connect(self._guided_anchor_changed)
        anchor_row.addWidget(self.anchor_choice, 1)
        layout.addLayout(anchor_row)
        anchor_help = QLabel("Sets the effect's reference point.")
        anchor_help.setObjectName("new_item_intro")
        anchor_help.setWordWrap(True)
        layout.addWidget(anchor_help)

    @staticmethod
    def _add_guided_axis_row(layout: QVBoxLayout, title: str, spins) -> None:
        row = QGridLayout()
        row.setHorizontalSpacing(4)
        caption = QLabel(title)
        caption.setFixedWidth(56)
        caption.setToolTip(title)
        caption.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        row.addWidget(caption, 0, 0)
        for index, (axis, spin) in enumerate(zip(("X", "Y", "Z"), spins)):
            axis_column = index * 2 + 1
            value_column = axis_column + 1
            row.addWidget(QLabel(axis), 0, axis_column)
            spin.setMinimumWidth(56)
            spin.setMaximumWidth(100)
            spin.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            row.addWidget(spin, 0, value_column)
            row.setColumnStretch(value_column, 1)
        layout.addLayout(row)

    def _add_guided_scene_controls(self, layout: QVBoxLayout) -> None:
        self.show_reach.setText("Show bounds")
        layout.addWidget(self.show_reach)
        fit_row = QHBoxLayout()
        fit_row.addWidget(QLabel("Fit to item"))
        fit_row.addStretch(1)
        self.fit_button.setText("Fit")
        self.fit_button.setMinimumWidth(94)
        fit_row.addWidget(self.fit_button)
        layout.addLayout(fit_row)

        backdrop_row = QHBoxLayout()
        backdrop_row.addWidget(QLabel("Backdrop"))
        remembered = remembered_backdrop()
        self.backdrop_choice.blockSignals(True)
        self.backdrop_choice.clear()
        self.backdrop_choice.addItem("Neutral", BACKDROP_GREY)
        self.backdrop_choice.addItem("Dark", BACKDROP_DARK)
        self.backdrop_choice.addItem("Black", BACKDROP_BLACK)
        for index in range(self.backdrop_choice.count()):
            if str(self.backdrop_choice.itemData(index)).casefold() == remembered.casefold():
                self.backdrop_choice.setCurrentIndex(index)
                break
        self.backdrop_choice.blockSignals(False)
        backdrop_row.addWidget(self.backdrop_choice, 1)
        layout.addLayout(backdrop_row)
        self.show_character.setText("Character")
        character_row = QHBoxLayout()
        character_row.addWidget(self.show_character)
        character_row.addStretch(1)
        if self._character_fit_control is not None:
            character_row.addWidget(self._character_fit_control)
        layout.addLayout(character_row)

    def _add_guided_look_controls(self, layout: QVBoxLayout) -> None:
        self.colour_as_shipped = QCheckBox("Colour as shipped")
        self.colour_as_shipped.setChecked(self.color is None)
        self.colour_as_shipped.toggled.connect(self._guided_colour_mode_changed)
        layout.addWidget(self.colour_as_shipped)
        self.guided_colour_button = QPushButton("Choose colour…")
        self.guided_colour_button.clicked.connect(self._choose_guided_colour)
        self.guided_colour_button.setVisible(self.color is not None)
        layout.addWidget(self.guided_colour_button)

        self.look_sliders: dict[str, QSlider] = {}
        self.look_spins: dict[str, QDoubleSpinBox] = {}
        for key, label in (
            ("intensity", "Brightness"),
            ("particle_size", "Particle size"),
            ("spawn_rate", "Spawn rate"),
            ("lifetime", "Lifetime"),
        ):
            self._add_guided_look_row(layout, key, label)

        self.decoder_reason = QLabel("")
        self.decoder_reason.setObjectName("new_item_warning")
        self.decoder_reason.setWordWrap(True)
        self.decoder_reason.setVisible(False)
        layout.addWidget(self.decoder_reason)
        self.guided_restore_button = QPushButton("Restore defaults")
        self.guided_restore_button.clicked.connect(self.restore_defaults)
        layout.addWidget(self.guided_restore_button)
        self.apply_button.setMinimumHeight(40)
        layout.addWidget(self.apply_button)

    def _add_guided_look_row(self, layout: QVBoxLayout, key: str, label: str) -> None:
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(-1000, 1000)
        slider.setSingleStep(25)
        slider.setPageStep(100)
        slider.setValue(self._factor_to_slider(float(getattr(self, key))))
        spin = QDoubleSpinBox()
        spin.setRange(0.05, 20.0)
        spin.setDecimals(2)
        spin.setSingleStep(0.1)
        spin.setValue(float(getattr(self, key)))
        spin.setMinimumWidth(88)
        slider.valueChanged.connect(lambda value, name=key: self._guided_look_slider_changed(name, value))
        spin.valueChanged.connect(lambda value, name=key: self._guided_look_spin_changed(name, value))
        row.addWidget(slider, 1)
        row.addWidget(spin)
        layout.addLayout(row)
        self.look_sliders[key] = slider
        self.look_spins[key] = spin

    def _hide_compatibility_controls(self) -> None:
        for widget in (
            *getattr(self, "_compatibility_only_widgets", ()),
            self.show_particles,
            self.invert_orbit_x_checkbox,
            self.invert_orbit_y_checkbox,
            self.size_label,
            self.legend_toggle,
            self.emitters_toggle,
            self.caveat,
            self.trail_button,
            self.effect_name_label,
            self.showing_label,
        ):
            widget.setVisible(False)

    @staticmethod
    def _factor_to_slider(value: float) -> int:
        bounded = max(0.05, min(20.0, float(value)))
        return int(round(math.log(bounded) / math.log(20.0) * 1000.0))

    @staticmethod
    def _slider_to_factor(value: int) -> float:
        return 20.0 ** (float(value) / 1000.0)

    def _guided_look_slider_changed(self, key: str, value: int) -> None:
        spin = self.look_spins[key]
        factor = self._slider_to_factor(value)
        spin.blockSignals(True)
        spin.setValue(factor)
        spin.blockSignals(False)
        setattr(self, key, float(spin.value()))
        self.look_changed.emit()

    def _guided_look_spin_changed(self, key: str, value: float) -> None:
        setattr(self, key, float(value))
        slider = self.look_sliders[key]
        slider.blockSignals(True)
        slider.setValue(self._factor_to_slider(float(value)))
        slider.blockSignals(False)
        self.look_changed.emit()

    def _guided_colour_mode_changed(self, shipped: bool) -> None:
        self.guided_colour_button.setVisible(not shipped)
        if shipped:
            self.color = None
        elif self.color is None:
            self.color = (1.0, 1.0, 1.0)
        self.look_changed.emit()

    def _choose_guided_colour(self) -> None:
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QColorDialog

        start = QColor.fromRgbF(*(self.color or (1.0, 0.47, 0.12)))
        chosen = QColorDialog.getColor(start, self, "Effect colour")
        if not chosen.isValid():
            return
        self.color = (chosen.redF(), chosen.greenF(), chosen.blueF())
        self.colour_as_shipped.blockSignals(True)
        self.colour_as_shipped.setChecked(False)
        self.colour_as_shipped.blockSignals(False)
        self.look_changed.emit()

    def set_look(
        self,
        *,
        color: Optional[Vec3],
        intensity: float,
        particle_size: float,
        spawn_rate: float,
        lifetime: float,
    ) -> None:
        self.color = None if color is None else tuple(float(v) for v in color)
        self.intensity = float(intensity)
        self.particle_size = float(particle_size)
        self.spawn_rate = float(spawn_rate)
        self.lifetime = float(lifetime)
        if not hasattr(self, "look_spins"):
            return
        self.colour_as_shipped.blockSignals(True)
        self.colour_as_shipped.setChecked(self.color is None)
        self.colour_as_shipped.blockSignals(False)
        self.guided_colour_button.setVisible(self.color is not None)
        for key in ("intensity", "particle_size", "spawn_rate", "lifetime"):
            value = float(getattr(self, key))
            self.look_spins[key].blockSignals(True)
            self.look_spins[key].setValue(value)
            self.look_spins[key].blockSignals(False)
            self.look_sliders[key].blockSignals(True)
            self.look_sliders[key].setValue(self._factor_to_slider(value))
            self.look_sliders[key].blockSignals(False)

    def set_decoder_reason(self, reason: str = "") -> None:
        message = str(reason or "").strip()
        self.decoder_reason.setText(message)
        self.decoder_reason.setVisible(bool(message))
        enabled = not bool(message)
        self.colour_as_shipped.setEnabled(enabled)
        self.guided_colour_button.setEnabled(enabled)
        for control in (*self.look_sliders.values(), *self.look_spins.values()):
            control.setEnabled(enabled)

    def restore_defaults(self) -> None:
        self._set_numbers((0.0, 0.0, 0.0), 1.0, (0.0, 0.0, 0.0))
        self.set_look(color=None, intensity=1.0, particle_size=1.0, spawn_rate=1.0, lifetime=1.0)
        self.look_changed.emit()
        self._sync_host()

    def _guided_anchor_changed(self, _index: int) -> None:
        self._put_it_at(str(self.anchor_choice.currentData() or "origin"))

    def _frame_subject(self) -> None:
        if not self.show_reach.isChecked():
            self.show_reach.setChecked(True)
        self._point_camera()
