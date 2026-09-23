"""Compact per-material surface controls, independent of glow and glass."""
from dataclasses import replace

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget)

from cdmw.domain.new_item.surface import SurfaceEdit
from cdmw.ui.wheel_guard import enable_focused_wheel


class SurfaceEditor(QGroupBox):
    changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Surface colour and reflections")
        self._loading, self._choices, self._glow_colours = False, {}, {}
        self._colour = (1.0, 1.0, 1.0)
        self.setEnabled(False)
        self.setCheckable(True)
        self.setChecked(False)
        layout = QVBoxLayout(self)
        self.details = QWidget()
        layout.addWidget(self.details)
        controls = QVBoxLayout(self.details)
        controls.setContentsMargins(0, 0, 0, 0)
        self.part = QComboBox()
        controls.addWidget(self.part)
        colour_row = QHBoxLayout()
        self.colour_enabled = QCheckBox("Surface colour")
        self.colour_button = QPushButton("Colour")
        self.match_glow = QPushButton("Match glow colour")
        colour_row.addWidget(self.colour_enabled)
        colour_row.addWidget(self.colour_button)
        controls.addLayout(colour_row)
        controls.addWidget(self.match_glow)
        self.colour_button.setToolTip("Replace the surface hue while keeping texture brightness and opacity. Glow remains unchanged.")
        self.match_glow.setToolTip("Use this part's glow colour for its surface too. This removes a competing surface hue without increasing glow.")
        form = QFormLayout()
        self.preset = QComboBox()
        for label, values in (("Source reflections", None), ("Low-shine", (0.9, 0.0)), ("Custom", "custom")):
            self.preset.addItem(label, values)
        form.addRow("Reflection preset", self.preset)
        self.fields = []
        for name, default in (("Roughness", 0.9), ("Metallic", 0.0)):
            check, spin = QCheckBox(name), enable_focused_wheel(QDoubleSpinBox())
            spin.setRange(0, 1)
            spin.setDecimals(3)
            spin.setSingleStep(0.05)
            spin.setKeyboardTracking(False)
            spin.setValue(default)
            form.addRow(check, spin)
            self.fields.append((check, spin))
            check.toggled.connect(self._values_changed)
            spin.valueChanged.connect(self._values_changed)
        self.fields[0][1].setToolTip("Higher values soften highlights. Uncheck to restore the source roughness texture.")
        self.fields[1][1].setToolTip("Zero is nonmetallic and reduces coloured metallic reflections. Uncheck to restore the source metallic texture.")
        controls.addLayout(form)
        note = QLabel("Selected part only. Lighting and glass can still affect its appearance.")
        note.setWordWrap(True)
        controls.addWidget(note)
        self.reset = QPushButton("Restore source surface")
        controls.addWidget(self.reset)
        self.part.currentIndexChanged.connect(self._show_part)
        self.colour_enabled.toggled.connect(self._values_changed)
        self.colour_button.clicked.connect(self._pick_colour)
        self.match_glow.clicked.connect(self._match_glow)
        self.preset.currentIndexChanged.connect(self._preset_changed)
        self.reset.clicked.connect(lambda: self._set_choice(SurfaceEdit()))
        self.toggled.connect(self._toggled)
        self.details.hide()

    def refresh(self, parts, choices, *, enabled, mesh=None, glow=None):
        old = self.part.currentData()
        self._loading = True
        self._choices = dict(choices)
        self.part.clear()
        for name, label in parts:
            self.part.addItem(label, name)
        self.part.setCurrentIndex(max(0, self.part.findData(old)))
        self.setEnabled(enabled and bool(parts))
        self.setToolTip("Edit the imported model's surface in preview and export. Uses Plain PBR materials."
                        if enabled else "Import a model to edit its surface colour and reflections.")
        self.setChecked(bool(choices))
        self.details.setVisible(bool(choices))
        self.update_glow(mesh, glow)
        self._loading = False
        self._show_part()

    def update_glow(self, mesh, glow):
        from cdmw.services.new_item_materials import appearance_preview_part_names, glow_preview_parameter_groups
        self._glow_colours = {}
        for group in glow_preview_parameter_groups(mesh, glow):
            colour = group.get("emissive_color")
            if colour is None or not group.get("emissive_intensity"):
                continue
            for index in group["source_submesh_indices"]:
                for name in appearance_preview_part_names(mesh.submeshes[index]):
                    self._glow_colours[name.casefold()] = tuple(colour)
        self.match_glow.setEnabled(str(self.part.currentData()).casefold() in self._glow_colours)

    def _show_part(self, *_args):
        if self._loading:
            return
        self._loading = True
        choice = self._choices.get(self.part.currentData(), SurfaceEdit())
        self._colour = choice.color or (1.0, 1.0, 1.0)
        self.colour_enabled.setChecked(choice.color is not None)
        self.colour_button.setEnabled(choice.color is not None)
        color = QColor.fromRgbF(*self._colour)
        self.colour_button.setText(color.name().upper())
        self.match_glow.setEnabled(str(self.part.currentData()).casefold() in self._glow_colours)
        for (check, spin), value, default in zip(self.fields, (choice.roughness, choice.metallic), (0.9, 0.0)):
            check.setChecked(value is not None)
            spin.setEnabled(value is not None)
            spin.setValue(default if value is None else value)
        values = (choice.roughness, choice.metallic)
        self.preset.setCurrentIndex(0 if values == (None, None) else 1 if values == (0.9, 0.0) else 2)
        self._loading = False

    def _set_choice(self, choice):
        if self._loading or self.part.currentData() is None:
            return
        choice.validate()
        name = self.part.currentData()
        if choice.wanted:
            self._choices[name] = choice
        else:
            self._choices.pop(name, None)
        self._show_part()
        self.changed.emit(tuple(self._choices.items()) if self.isChecked() else ())

    def _values_changed(self, *_args):
        self._set_choice(SurfaceEdit(self._colour if self.colour_enabled.isChecked() else None,
            *(spin.value() if check.isChecked() else None for check, spin in self.fields)))

    def _pick_colour(self):
        colour = QColorDialog.getColor(QColor.fromRgbF(*self._colour), self, "Surface colour")
        if colour.isValid():
            self._colour = (colour.redF(), colour.greenF(), colour.blueF())
            self._values_changed()

    def _match_glow(self):
        colour = self._glow_colours.get(str(self.part.currentData()).casefold())
        if colour is not None:
            self._set_choice(replace(self._choices.get(self.part.currentData(), SurfaceEdit()), color=colour))

    def _preset_changed(self, index):
        values = self.preset.itemData(index)
        if values != "custom":
            roughness, metallic = values if values is not None else (None, None)
            self._set_choice(replace(self._choices.get(self.part.currentData(), SurfaceEdit()), roughness=roughness, metallic=metallic))

    def _toggled(self, checked):
        self.details.setVisible(checked)
        if not self._loading:
            self.changed.emit(tuple(self._choices.items()) if checked else ())
