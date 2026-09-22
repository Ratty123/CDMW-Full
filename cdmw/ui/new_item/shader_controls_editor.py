"""Per-part experimental shader controls; unchecked fields inherit the source."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
                              QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget)

from cdmw.domain.mesh.shader_controls import FAMILIES, ShaderControls, family_for


class ShaderControlsEditor(QGroupBox):
    changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__("Shader experiments", parent)
        self._loading = False
        self._choices = {}
        layout = QVBoxLayout(self)
        self.part = QComboBox()
        layout.addWidget(self.part)
        self.family = QComboBox()
        self.family.addItem("Keep source shader", "")
        for family in FAMILIES:
            if family.shader != "Dissolve":
                self.family.addItem(family.label, family.shader)
        layout.addWidget(self.family)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.fields = QWidget()
        self.form = QFormLayout(self.fields)
        layout.addWidget(self.fields)
        notice = QLabel("Test the result in game; the viewport does not reproduce every game shader pass.")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.reset = QPushButton("Restore source shader controls")
        layout.addWidget(self.reset)
        self.part.currentIndexChanged.connect(self._show_part)
        self.family.currentIndexChanged.connect(self._family_changed)
        self.reset.clicked.connect(self._reset)

    def refresh(self, parts, choices):
        old = self.part.currentData()
        self._loading = True
        self._choices = dict(choices)
        self.part.clear()
        for name, label in parts:
            self.part.addItem(label, name)
        index = self.part.findData(old)
        self.part.setCurrentIndex(index if index >= 0 else 0)
        self.setEnabled(bool(parts))
        self._loading = False
        self._show_part()

    def _show_part(self, *_args):
        if self._loading:
            return
        self._loading = True
        try:
            choice = self._choices.get(self.part.currentData())
            self.family.setCurrentIndex(max(0, self.family.findData(choice.shader if choice else "")))
            while self.form.rowCount():
                self.form.removeRow(0)
            self._rows = []
            self.reset.setEnabled(choice is not None)
            if choice is None:
                self.note.setText("Choose a compatible shader experiment for this part. Unchecked fields keep source values. Object dissolve is available for static objects in Mesh Editor.")
                return
            family = family_for(choice.shader)
            self.note.setText(family.note)
            values = dict(choice.values)
            for field in family.fields:
                enabled = QCheckBox(field.label)
                enabled.setChecked(field.name in values)
                enabled.setToolTip("Override this field. Uncheck to retain the authored value.")
                holder, row = QWidget(), QHBoxLayout()
                row.setContentsMargins(0, 0, 0, 0)
                holder.setLayout(row)
                spins = []
                for value in values.get(field.name, field.default):
                    spin = QDoubleSpinBox()
                    spin.setRange(field.minimum, field.maximum)
                    spin.setDecimals(0 if field.integer else 4)
                    spin.setSingleStep(1 if field.integer else .01)
                    spin.setKeyboardTracking(False)
                    spin.setValue(value)
                    spin.setEnabled(enabled.isChecked())
                    spin.valueChanged.connect(self._values_changed)
                    row.addWidget(spin)
                    spins.append(spin)
                self.form.addRow(enabled, holder)
                self._rows.append((field, enabled, spins))
                enabled.toggled.connect(self._values_changed)
        finally:
            self._loading = False

    def _family_changed(self, *_args):
        if self._loading or self.part.currentData() is None:
            return
        shader = self.family.currentData()
        name = self.part.currentData()
        if shader:
            values = (("_wingFlowProgress", (2.,)),) if shader == "SkinnedMeshWing" else ()
            self._choices[name] = ShaderControls(shader, values)
        else:
            self._choices.pop(name, None)
        self._show_part()
        self.changed.emit(tuple(self._choices.items()))

    def _values_changed(self, *_args):
        if self._loading:
            return
        values = []
        for field, enabled, spins in self._rows:
            for spin in spins:
                spin.setEnabled(enabled.isChecked())
            if enabled.isChecked():
                values.append((field.name, tuple(spin.value() for spin in spins)))
        self._choices[self.part.currentData()] = ShaderControls(self.family.currentData(), tuple(values))
        self.changed.emit(tuple(self._choices.items()))

    def _reset(self):
        self.family.setCurrentIndex(0)
