"""Per-part experimental shader controls; unchecked fields inherit the source."""
from dataclasses import replace
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
                              QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget)

from cdmw.domain.mesh.shader_controls import NEW_ITEM_FAMILIES, EYE_COVER, ShaderControls, family_for
from cdmw.ui.wheel_guard import enable_focused_wheel


class ShaderControlsEditor(QGroupBox):
    changed = Signal(object)
    paint_requested = Signal(str)
    restore_mask_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__("Shader experiments", parent)
        self._loading = False
        self._choices = {}
        self._source_options = None
        layout = QVBoxLayout(self)
        self.part = QComboBox()
        layout.addWidget(self.part)
        self.family = QComboBox()
        self.family.addItem("Keep source shader", "")
        for family in NEW_ITEM_FAMILIES:
            self.family.addItem(family.label, family.shader)
        layout.addWidget(self.family)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.overlap_warning = QLabel(
            "<b>Transparency limitation:</b> Overlapping transparent surfaces may show visible triangles or other visual glitches in game, even within the same model. Avoid overlapping transparent surfaces where possible.")
        self.overlap_warning.setWordWrap(True)
        self.overlap_warning.hide()
        layout.addWidget(self.overlap_warning)
        self.fields = QWidget()
        self.form = QFormLayout(self.fields)
        layout.addWidget(self.fields)
        self.mask_actions = QWidget()
        mask_row = QHBoxLayout(self.mask_actions)
        mask_row.setContentsMargins(0, 0, 0, 0)
        self.paint_mask = QPushButton("Paint transparency…")
        self.restore_mask = QPushButton("Restore mask")
        self.paint_mask.setToolTip("Paint different transparency values across this part's texture. White reduces colour coverage; black retains the selected Colour mixing.")
        self.restore_mask.setToolTip("Remove the painted mask and use Colour reduction or the source material texture again.")
        mask_row.addWidget(self.paint_mask)
        mask_row.addWidget(self.restore_mask)
        self.paint_mask.clicked.connect(lambda: self.paint_requested.emit(str(self.part.currentData())))
        self.restore_mask.clicked.connect(lambda: self.restore_mask_requested.emit(str(self.part.currentData())))
        layout.addWidget(self.mask_actions)
        self.setToolTip("Test the result in game; the viewport does not reproduce every game shader pass.")
        self.reset = QPushButton("Restore source shader controls")
        layout.addWidget(self.reset)
        self.part.currentIndexChanged.connect(self._show_part)
        self.family.currentIndexChanged.connect(self._family_changed)
        self.reset.clicked.connect(self._reset)

    def refresh(self, parts, choices, source_options=None):
        old = self.part.currentData()
        self._loading = True
        self._choices = dict(choices)
        self._source_options = source_options
        self.part.clear()
        for name, label in parts:
            self.part.addItem(label, name)
        index = self.part.findData(old)
        self.part.setCurrentIndex(index if index >= 0 else 0)
        self.setEnabled(bool(parts))
        self._loading = False
        self._show_part()

    def _source_note(self):
        if self._source_options is None:
            return ""
        shader, supported = self._source_options.get(str(self.part.currentData()).casefold(), ("", ()))
        if not shader:
            return "Source material information is unavailable; shader experiments are disabled."
        note = f"Source shader: {shader}."
        if not supported:
            note += " No compatible shader experiments. Glow and translucency have separate controls."
        else:
            labels = [family.label for family in NEW_ITEM_FAMILIES if family.shader in supported]
            note += " Available for this part: " + ", ".join(labels) + "."
        note += " Options marked Unavailable require a different source material. Hover over an option for its requirements."
        return note

    def _update_available_families(self):
        options = self._source_options
        _shader, supported = (options.get(str(self.part.currentData()).casefold(), ("", ()))
                              if options is not None else ("", ()))
        for index in range(1, self.family.count()):
            item = self.family.model().item(index)
            available = options is None or self.family.itemData(index) in supported
            family = family_for(self.family.itemData(index))
            item.setText(family.label if available else f"{family.label} — Unavailable")
            item.setEnabled(available)
            requirement = ("Requires a Plain PBR material with a base colour texture, or an existing Wing material." if family.shader == "SkinnedMeshWing"
                           else "Requires a plain opaque, glowing or translucent material with a base colour texture, or an existing transparent surface blending material." if family == EYE_COVER
                           else f"Requires a {family.shader} source material.")
            item.setToolTip(family.note if available else
                            f"Unavailable for this part. {requirement} "
                            + (f"This part uses {_shader}." if _shader else "Source material information is unavailable."))

    def _show_part(self, *_args):
        if self._loading:
            return
        self._loading = True
        try:
            self._update_available_families()
            choice = self._choices.get(self.part.currentData())
            self.mask_actions.setVisible(choice is not None and choice.shader == EYE_COVER.shader)
            self.restore_mask.setEnabled(choice is not None and choice.transparency_mask is not None)
            self.family.setCurrentIndex(max(0, self.family.findData(choice.shader if choice else "")))
            while self.form.rowCount():
                self.form.removeRow(0)
            self._rows = []
            self.reset.setEnabled(choice is not None)
            source = (self._source_options or {}).get(str(self.part.currentData()).casefold(), ("", ()))[0]
            self.note.setText(f"Source shader: {source}" if source else "")
            self.note.setVisible(bool(source))
            self.overlap_warning.setVisible((choice.shader if choice else source) == EYE_COVER.shader)
            if choice is None:
                self.family.setToolTip(self._source_note() or "Choose a compatible shader experiment for this part. Unchecked fields keep source values. Object dissolve is available for static objects in Mesh Editor.")
                return
            family = family_for(choice.shader)
            if family == EYE_COVER:
                self.note.setText("Approximate preview: Colour mixing and Colour reduction change colour coverage; Surface detail and shine changes highlights and surface detail. Test the final result in game.")
                self.note.setVisible(True)
            self.family.setToolTip(" ".join(value for value in (self._source_note(), family.note) if value))
            values = dict(choice.values)
            for field in family.fields:
                enabled = QCheckBox(field.label)
                enabled.setChecked(field.name in values)
                enabled.setToolTip("Override this field. Uncheck to retain the authored value.")
                painted = field.name == "material_red" and choice.transparency_mask is not None
                enabled.setEnabled(not painted)
                if field.kind == "ExportToggle":
                    enabled.setChecked(values.get(field.name, field.default) == (1.,))
                    warning = QLabel("Affects every material using transparent surface blending, including character eyes, while the mod is installed. Tests character visibility behind the material, not overlapping transparency. The viewport does not simulate this test.")
                    warning.setWordWrap(True)
                    enabled.setToolTip(warning.text())
                    self.form.addRow(enabled)
                    self.form.addRow(warning)
                    self._rows.append((field, enabled, []))
                    enabled.toggled.connect(self._values_changed)
                    continue
                if family == EYE_COVER:
                    tips = {
                        "_eyeCoverDiffuseParameter": "Packed into 256 steps. Colour weight is twice this value minus Colour reduction; this is not a whole-material opacity percentage. Unchecked: keep the authored value, or use 0.5.",
                        "surface_alpha": "Replaces the alpha texture's red channel. Blends normals and surface properties separately from colour. Unchecked: keep the source texture, or use white (1).",
                        "material_red": "Reduces the surface's colour coverage. Subtracted from twice the Colour mixing value and stored in the material texture's red channel. Unchecked: keep the source texture, or use black (0).",
                        "roughness": "Replaces material green: 0 smooth, 1 rough. This override takes precedence over Surface roughness. Unchecked: keep the source channel.",
                        "metallic": "Replaces material blue: 0 nonmetal, 1 metal. This override takes precedence over Surface metallic. Unchecked: keep the source channel.",
                    }
                    enabled.setToolTip(tips[field.name])
                holder, row = QWidget(), QHBoxLayout()
                row.setContentsMargins(0, 0, 0, 0)
                holder.setLayout(row)
                spins = []
                for value in values.get(field.name, field.default):
                    spin = enable_focused_wheel(QDoubleSpinBox())
                    spin.setRange(field.minimum, field.maximum)
                    spin.setDecimals(0 if field.integer else 4)
                    spin.setSingleStep(1 if field.integer else .01)
                    spin.setKeyboardTracking(False)
                    spin.setValue(value)
                    spin.setEnabled(enabled.isChecked() and not painted)
                    if painted:
                        spin.setToolTip("The painted transparency mask controls this channel. Restore mask to use a uniform value.")
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
        if shader and not self.family.model().item(self.family.currentIndex()).isEnabled():
            # Programmatic selection must obey the same gate as the dropdown.
            self._show_part()
            return
        if shader:
            values = (("_wingFlowProgress", (2.,)),) if shader == "SkinnedMeshWing" else ()
            if shader == EYE_COVER.shader:
                values = tuple((field.name, field.default) for field in EYE_COVER.fields[:3])
            self._choices[name] = ShaderControls(shader, values)
        else:
            self._choices.pop(name, None)
        self._show_part()
        self.changed.emit(tuple(self._choices.items()))

    def _values_changed(self, *_args):
        if self._loading:
            return
        values = []
        current = self._choices[self.part.currentData()]
        for field, enabled, spins in self._rows:
            for spin in spins:
                spin.setEnabled(enabled.isChecked() and not (field.name == "material_red" and current.transparency_mask is not None))
            if enabled.isChecked():
                values.append((field.name, (1.,) if field.kind == "ExportToggle" else tuple(spin.value() for spin in spins)))
        self._choices[self.part.currentData()] = replace(current, values=tuple(values))
        self.changed.emit(tuple(self._choices.items()))

    def _reset(self):
        self.family.setCurrentIndex(0)
