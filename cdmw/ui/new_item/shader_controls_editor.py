"""Per-part experimental shader controls; unchecked fields inherit the source."""
from dataclasses import replace
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
                              QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget)

from cdmw.domain.mesh.shader_controls import NEW_ITEM_FAMILIES, EYE_COVER, ShaderControls, family_for, eye_cover_colour_range
from cdmw.ui.wheel_guard import enable_focused_wheel


class ShaderControlsEditor(QGroupBox):
    changed = Signal(object)
    paint_requested = Signal(str)
    restore_mask_requested = Signal(str)
    restore_surface_mask_requested = Signal(str)

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
        self.coverage_options = QWidget()
        coverage_form = QFormLayout(self.coverage_options)
        self.mapping = QComboBox()
        self.mapping.addItem("Raw channels (compatible)", "raw")
        self.mapping.addItem("Calibrated coverage (experimental)", "calibrated_v1")
        self.coverage = QDoubleSpinBox()
        self.coverage.setRange(0, 254)
        self.coverage.setDecimals(0)
        self.coverage.setKeyboardTracking(False)
        self.coverage.setToolTip("Colour contribution in 255 steps before BC7 compression, which can shift the endpoints. This preset reaches 0–254/255, not exact full coverage. White paint fades toward zero. Existing raw settings remain recoverable.")
        self.advanced = QCheckBox("Advanced raw channels")
        self.advanced.setChecked(True)
        coverage_form.addRow("Coverage mapping", self.mapping)
        coverage_form.addRow("Colour coverage / 255", self.coverage)
        coverage_form.addRow(self.advanced)
        layout.addWidget(self.coverage_options)
        self.mapping.currentIndexChanged.connect(self._mapping_changed)
        self.coverage.valueChanged.connect(self._coverage_changed)
        self.advanced.toggled.connect(self._show_part)
        self.fields = QWidget()
        self.form = QFormLayout(self.fields)
        layout.addWidget(self.fields)
        self.mask_actions = QWidget()
        mask_row = QVBoxLayout(self.mask_actions)
        mask_row.setContentsMargins(0, 0, 0, 0)
        self.paint_mask = QPushButton("Paint transparency…")
        self.restore_mask = QPushButton("Restore mask")
        self.restore_surface_mask = QPushButton("Restore surface mask")
        self.restore_colour_channel = QPushButton("Restore colour channel")
        self.restore_surface_channel = QPushButton("Restore surface channel")
        self.paint_mask.setToolTip("Paint different transparency values across this part's texture. White reduces colour coverage; black retains the selected Colour mixing.")
        self.restore_mask.setToolTip("Remove the painted mask and use Colour reduction or the source material texture again.")
        mask_row.addWidget(self.paint_mask)
        mask_row.addWidget(self.restore_mask)
        mask_row.addWidget(self.restore_surface_mask)
        channel_row = QHBoxLayout()
        channel_row.addWidget(self.restore_colour_channel)
        channel_row.addWidget(self.restore_surface_channel)
        mask_row.addLayout(channel_row)
        self.paint_mask.clicked.connect(lambda: self.paint_requested.emit(str(self.part.currentData())))
        self.restore_mask.clicked.connect(lambda: self.restore_mask_requested.emit(str(self.part.currentData())))
        self.restore_surface_mask.clicked.connect(lambda: self.restore_surface_mask_requested.emit(str(self.part.currentData())))
        self.restore_colour_channel.clicked.connect(lambda: self._restore_channel(False))
        self.restore_surface_channel.clicked.connect(lambda: self._restore_channel(True))
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
            eye = choice is not None and choice.shader == EYE_COVER.shader
            wing = choice is not None and choice.shader == "SkinnedMeshWing"
            self.mask_actions.setVisible(eye or wing)
            self.coverage_options.setVisible(eye)
            self.restore_surface_mask.setVisible(eye)
            self.restore_colour_channel.setVisible(eye)
            self.restore_surface_channel.setVisible(eye)
            self.restore_mask.setEnabled(choice is not None and (choice.transparency_mask is not None or choice.cutout_mask is not None))
            self.restore_surface_mask.setEnabled(eye and choice.surface_response_mask is not None)
            self.paint_mask.setText("Paint cutout…" if wing else "Paint transparency…")
            self.paint_mask.setToolTip("White removes pixels; black keeps pixels. Experimental hard cutouts use a private Wing mask; restoring the mask restores Patterned reveal controls." if wing else
                                      "Paint Colour coverage, Surface response, or Linked fade. Targets keep independent masks; white means more fade.")
            self.restore_mask.setText("Restore cutout mask" if wing else "Restore colour mask")
            if eye:
                self.mapping.setCurrentIndex(self.mapping.findData(choice.coverage_mapping))
                self.coverage.setValue((choice.colour_coverage if choice.colour_coverage is not None else 254 / 255) * 255)
                self.coverage.setEnabled(choice.coverage_mapping == "calibrated_v1")
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
                self.note.setText(self._coverage_note(choice))
                self.note.setVisible(True)
            elif wing and choice.cutout_mask is not None:
                self.note.setText("Experimental painted cutout: white removes pixels and black keeps them. Grays form a threshold field, not smooth transparency. Restore cutout mask to use Patterned reveal progress. Test shadows, animation and LODs in game.")
                self.note.setVisible(True)
            self.family.setToolTip(" ".join(value for value in (self._source_note(), family.note) if value))
            values = dict(choice.values)
            for field in family.fields:
                enabled = QCheckBox(field.label)
                enabled.setChecked(field.name in values)
                enabled.setToolTip("Override this field. Uncheck to retain the authored value.")
                painted = self._channel_owned(choice, field.name)
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
                if family == EYE_COVER and field.name in {"_eyeCoverDiffuseParameter", "material_red", "surface_alpha"}:
                    self.form.setRowVisible(enabled, self.advanced.isChecked())
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
                spin.setEnabled(enabled.isChecked() and not self._channel_owned(current, field.name))
            if enabled.isChecked():
                values.append((field.name, (1.,) if field.kind == "ExportToggle" else tuple(spin.value() for spin in spins)))
        self._choices[self.part.currentData()] = replace(current, values=tuple(values))
        if current.shader == EYE_COVER.shader:
            self.note.setText(self._coverage_note(self._choices[self.part.currentData()]))
        self.changed.emit(tuple(self._choices.items()))

    @staticmethod
    def _channel_owned(choice, name):
        return ((name == "material_red" and choice.transparency_mask is not None)
                or (name == "surface_alpha" and choice.surface_response_mask is not None)
                or (name in {"material_red", "_eyeCoverDiffuseParameter"} and choice.coverage_mapping == "calibrated_v1")
                or (name in {"_wingFlowProgress", "_wingFlowInverse"} and choice.cutout_mask is not None))

    @staticmethod
    def _coverage_note(choice):
        low, high = eye_cover_colour_range(choice)
        state = f"Colour mask: {'painted' if choice.transparency_mask else 'source/uniform'}; surface mask: {'painted' if choice.surface_response_mask else 'source/uniform'}."
        note = ("Approximate preview: colour and normal/material contribution are independent. "
                "The game's projection-dependent surface weighting is not reproduced. " + state)
        if choice.coverage_mapping == "calibrated_v1":
            note += " Calibrated range before BC7: 0–254/255; this is colour contribution, not whole-surface visibility."
        elif "_eyeCoverDiffuseParameter" not in dict(choice.values):
            note += " Packed colour is inherited; its range depends on the source. Weights outside 0–1 are clamped only in this preview."
        elif low < 0 or high > 1:
            note += f" Raw colour weight can span {low:.4f}–{high:.4f}, outside 0–1. Preview clamps it; the inspected game expression does not."
        return note

    def _mapping_changed(self, *_args):
        if self._loading or self.part.currentData() not in self._choices:
            return
        name = self.part.currentData()
        mode = self.mapping.currentData()
        self._choices[name] = replace(self._choices[name], coverage_mapping=mode,
                                      colour_coverage=254 / 255 if mode == "calibrated_v1" else None)
        self.advanced.setChecked(mode == "raw")
        self._show_part()
        self.changed.emit(tuple(self._choices.items()))

    def _coverage_changed(self, *_args):
        if self._loading or self.part.currentData() not in self._choices:
            return
        name = self.part.currentData()
        self._choices[name] = replace(self._choices[name], colour_coverage=self.coverage.value() / 255)
        self.note.setText(self._coverage_note(self._choices[name]))
        self.changed.emit(tuple(self._choices.items()))

    def _restore_channel(self, surface):
        name = self.part.currentData()
        current = self._choices[name]
        fields = {"surface_alpha"} if surface else {"material_red", "_eyeCoverDiffuseParameter"}
        changes = {"surface_response_mask": None} if surface else {
            "transparency_mask": None, "coverage_mapping": "raw", "colour_coverage": None}
        self._choices[name] = replace(current, values=tuple((key, value) for key, value in current.values if key not in fields), **changes)
        self._show_part()
        self.changed.emit(tuple(self._choices.items()))

    def _reset(self):
        self.family.setCurrentIndex(0)
