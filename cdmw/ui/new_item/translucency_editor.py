"""Compact part selection and live absorption controls for New Item."""

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QSlider, QVBoxLayout, QWidget

from cdmw.domain.new_item.translucency import TranslucencyChoice
from cdmw.ui.wheel_guard import enable_focused_wheel


class TranslucencyEditor(QGroupBox):
    changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__("Translucency (experimental)", parent)
        self.setCheckable(True)
        self.setChecked(False)
        self._loading = False
        self._settings = {}
        self._surfaces = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        self.details = QWidget(self)
        details = QVBoxLayout(self.details)
        details.setContentsMargins(0, 0, 0, 0)
        self.parts = QListWidget()
        self.parts.setMaximumHeight(110)
        self.parts.setToolTip("Check parts to override. Highlight a part to edit only its settings.")
        details.addWidget(self.parts)
        selection = QHBoxLayout()
        self.select_all = QPushButton("Select all")
        self.clear_selection = QPushButton("Clear selection")
        self.select_all.setToolTip("Enable translucency on every part with one preview update. Existing part settings are kept.")
        self.select_all.clicked.connect(lambda: self._select_parts(True))
        self.clear_selection.clicked.connect(lambda: self._select_parts(False))
        selection.addWidget(self.select_all)
        selection.addWidget(self.clear_selection)
        selection.addStretch(1)
        details.addLayout(selection)
        self.controls = QWidget()
        controls = QVBoxLayout(self.controls)
        controls.setContentsMargins(0, 0, 0, 0)
        self.preset = QComboBox()
        for label, values in (
            ("Custom", None), ("Clear glass", (0.1, 0.0)), ("Light absorption", (0.1, 0.3)),
            ("Medium absorption", (0.5, 0.6)), ("Dense absorption", (1.0, 1.0)),
        ):
            self.preset.addItem(label, values)
        presets = QFormLayout()
        presets.addRow("Absorption preset", self.preset)
        controls.addLayout(presets)
        self.absorption = enable_focused_wheel(QSlider(Qt.Orientation.Horizontal))
        self.absorption.setAccessibleName("Absorption strength")
        self.absorption.setRange(0, 1000)
        self.absorption.setSingleStep(5)
        self.absorption.setPageStep(50)
        self.absorption.setTracking(False)
        self.absorption.setToolTip("Adjusts exported thickness and extinction together. This is absorption strength, not an opacity percentage.")
        strength = QHBoxLayout()
        strength.addWidget(QLabel("Clear glass"))
        strength.addWidget(self.absorption, 1)
        strength.addWidget(QLabel("Dense"))
        controls.addLayout(strength)
        surface_form = QFormLayout()
        self.surface_preset = QComboBox()
        for label, values in (("Source surface", None), ("Low-shine translucent", (0.9, 0.0)), ("Custom", "custom")):
            self.surface_preset.addItem(label, values)
        surface_form.addRow("Surface preset", self.surface_preset)
        self.surface_fields = []
        for label, default in (("Roughness", 0.9), ("Metallic", 0.0)):
            enabled, spin = QCheckBox(label), enable_focused_wheel(QDoubleSpinBox())
            enabled.setToolTip("Override this channel on the highlighted part. Uncheck to keep its source texture.")
            spin.setRange(0, 1)
            spin.setDecimals(3)
            spin.setSingleStep(0.05)
            spin.setKeyboardTracking(False)
            spin.setValue(default)
            spin.setEnabled(False)
            surface_form.addRow(enabled, spin)
            self.surface_fields.append((enabled, spin))
            enabled.toggled.connect(self._surface_changed)
            spin.valueChanged.connect(self._surface_changed)
        self.surface_fields[0][1].setToolTip("Higher values soften shiny highlights. Overrides the roughness texture; does not change absorption.")
        self.surface_fields[1][1].setToolTip("Lower values reduce metallic reflections. Some reflections may remain in game.")
        self.surface_preset.currentIndexChanged.connect(self._surface_preset_changed)
        controls.addLayout(surface_form)
        self.advanced = QGroupBox("Advanced")
        self.advanced.setCheckable(True)
        self.advanced.setChecked(False)
        advanced_layout = QVBoxLayout(self.advanced)
        self.advanced_fields = QWidget()
        advanced_layout.addWidget(self.advanced_fields)
        form = QFormLayout()
        self.advanced_fields.setLayout(form)
        self.thickness = enable_focused_wheel(QDoubleSpinBox())
        self.extinction = enable_focused_wheel(QDoubleSpinBox())
        for spin, value in ((self.thickness, 0.1), (self.extinction, 0.3)):
            spin.setRange(0.0, 1.0)
            spin.setDecimals(3)
            spin.setSingleStep(0.01)
            spin.setKeyboardTracking(False)
            spin.setValue(value)
            spin.valueChanged.connect(self._values_changed)
        self.thickness.setToolTip("Higher thickness makes the material less see-through. Texture colour and viewing angle also affect it.")
        self.extinction.setToolTip("How much light is absorbed. Higher values make the material less see-through.")
        form.addRow("Thickness", self.thickness)
        form.addRow("Extinction", self.extinction)
        controls.addWidget(self.advanced)
        self.advanced_fields.setVisible(False)
        self.advanced.toggled.connect(self.advanced_fields.setVisible)
        details.addWidget(self.controls)
        self.setToolTip(
            "Approximate viewport preview; game refraction and lighting may differ. "
            "Uses Plain PBR materials. Authored glass is preserved automatically; these controls override selected parts. "
            "Glow maps and colours are kept; brightness and tint may differ in game."
        )
        layout.addWidget(self.details)
        self.parts.itemChanged.connect(self._part_checked)
        self.parts.currentItemChanged.connect(self._show_current)
        self.preset.currentIndexChanged.connect(self._preset_changed)
        self.absorption.valueChanged.connect(self._absorption_changed)
        self.toggled.connect(self._emit_choice)
        self.details.setVisible(False)

    def refresh(self, parts, choice):
        current = self.parts.currentItem()
        current_name = current.data(Qt.ItemDataRole.UserRole) if current else None
        self._loading = True
        try:
            self.parts.clear()
            self._settings = {name.casefold(): choice.values_for(name) for name in choice.parts} if choice else {}
            self._surfaces = {name.casefold(): choice.surface_for(name) for name in choice.parts} if choice else {}
            chosen = {name.casefold() for name in choice.parts} if choice else set()
            for name, label in parts:
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, name)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if name.casefold() in chosen else Qt.CheckState.Unchecked)
                self.parts.addItem(item)
            selected_row = next((index for index in range(self.parts.count())
                                 if self.parts.item(index).data(Qt.ItemDataRole.UserRole) == current_name
                                 and self.parts.item(index).checkState() == Qt.CheckState.Checked), None)
            if selected_row is None:
                selected_row = next((index for index in range(self.parts.count())
                                     if self.parts.item(index).checkState() == Qt.CheckState.Checked), 0)
            self.parts.setCurrentRow(selected_row if parts else -1)
            self.setChecked(choice is not None and bool(parts))
            self.setEnabled(bool(parts))
            self.details.setVisible(self.isChecked())
            self.setToolTip("Choose a template or import a model to edit its materials." if not parts else "Turn off to restore the source materials, including authored glass.")
        finally:
            self._loading = False
        self._show_current()

    def _show_current(self, *_args):
        if self._loading:
            return
        item = self.parts.currentItem()
        self.controls.setEnabled(item is not None and item.checkState() == Qt.CheckState.Checked)
        values = self._settings.get(str(item.data(Qt.ItemDataRole.UserRole)).casefold(), (0.1, 0.3)) if item else (0.1, 0.3)
        self._loading = True
        try:
            self.thickness.setValue(values[0])
            self.extinction.setValue(values[1])
            self.absorption.setValue(round((values[0] * values[1]) ** 0.5 * 1000))
            self.preset.setCurrentIndex(next((index for index in range(1, self.preset.count())
                                             if tuple(self.preset.itemData(index)) == values), 0))
            surface = self._surfaces.get(str(item.data(Qt.ItemDataRole.UserRole)).casefold()) if item else None
            for (enabled, spin), value in zip(self.surface_fields, surface or (None, None)):
                enabled.setChecked(value is not None)
                spin.setEnabled(value is not None)
                if value is not None:
                    spin.setValue(value)
            self.surface_preset.setCurrentIndex(0 if surface is None else 1 if surface == (0.9, 0.0) else 2)
        finally:
            self._loading = False

    def _part_checked(self, item):
        if self._loading:
            return
        if item.checkState() == Qt.CheckState.Checked:
            self._settings.setdefault(str(item.data(Qt.ItemDataRole.UserRole)).casefold(), (0.1, 0.3))
            self.parts.setCurrentItem(item)
        self._show_current()
        self._emit_choice()

    def _select_parts(self, checked):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        changed = False
        # Batch the list mutation: itemChanged would otherwise rebuild the preview
        # once per part and could refresh the list while we are still traversing it.
        with QSignalBlocker(self.parts):
            for index in range(self.parts.count()):
                item = self.parts.item(index)
                if item.checkState() != state:
                    item.setCheckState(state)
                    changed = True
                if checked:
                    self._settings.setdefault(str(item.data(Qt.ItemDataRole.UserRole)).casefold(), (0.1, 0.3))
        self._show_current()
        if changed:
            self._emit_choice()

    def _values_changed(self, *_args):
        self._set_pair((self.thickness.value(), self.extinction.value()))

    def _surface_changed(self, *_args):
        values = tuple(spin.value() if enabled.isChecked() else None for enabled, spin in self.surface_fields)
        self._set_surface(values if any(value is not None for value in values) else None)

    def _surface_preset_changed(self, index):
        values = self.surface_preset.itemData(index)
        if values != "custom":
            self._set_surface(tuple(values) if values is not None else None)

    def _set_surface(self, values):
        if self._loading:
            return
        item = self.parts.currentItem()
        if item is None or item.checkState() != Qt.CheckState.Checked:
            return
        self._surfaces[str(item.data(Qt.ItemDataRole.UserRole)).casefold()] = values
        self._show_current()
        self._emit_choice()

    def _preset_changed(self, index):
        values = self.preset.itemData(index)
        if values is not None:
            self._set_pair(tuple(values))

    def _absorption_changed(self, value):
        # Squared optical depth provides finer adjustment near clear glass.
        strength = value / 1000.0
        self._set_pair((strength, strength))

    def _set_pair(self, values):
        if self._loading:
            return
        item = self.parts.currentItem()
        if item is None or item.checkState() != Qt.CheckState.Checked:
            return
        self._settings[str(item.data(Qt.ItemDataRole.UserRole)).casefold()] = values
        self._show_current()
        self._emit_choice()

    def _emit_choice(self, *_args):
        if self._loading:
            return
        self.details.setVisible(self.isChecked())
        parts = tuple(
            str(self.parts.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.parts.count())
            if self.parts.item(index).checkState() == Qt.CheckState.Checked
        )
        self.changed.emit(
            TranslucencyChoice.from_settings({name: self._settings.get(name.casefold(), (0.1, 0.3)) for name in parts},
                                            {name: self._surfaces.get(name.casefold()) for name in parts})
            if self.isChecked() and parts else None
        )
