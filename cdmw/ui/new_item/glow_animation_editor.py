"""Compact emission animation controls; all texture preparation stays in workers."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QFormLayout, QGroupBox, QLabel

from cdmw.domain.mesh.emission import GlowAnimation, RgbGlow
from cdmw.ui.wheel_guard import enable_focused_wheel


class GlowAnimationEditor(QGroupBox):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__("Animation (experimental)", parent)
        form = QFormLayout(self)
        self.spins = {}
        for name, label, maximum in (
            ("flow_u", "Scroll U", 10), ("flow_v", "Scroll V", 10),
            ("pulse_frequency", "Pulse speed", 10), ("pulse_minimum", "Pulse floor", 1),
        ):
            spin = enable_focused_wheel(QDoubleSpinBox())
            spin.setRange(0, maximum)
            spin.setDecimals(3)
            spin.setSingleStep(0.05)
            spin.setObjectName("new_item_glow_" + name)
            spin.valueChanged.connect(lambda _value: self.changed.emit())
            form.addRow(label, spin)
            self.spins[name] = spin
        note = QLabel("Zero speed is static. Scroll affects the glow map only; a solid map cannot show movement. "
                      "Pulse floor is a brightness floor, capped by the glow at each pixel. "
                      "Animated glow cannot share a part with translucency. Preview timing is approximate.")
        note.setWordWrap(True)
        form.addRow(note)
        self.rgb_box = QGroupBox("Use RGB glow map")
        self.rgb_box.setCheckable(True)
        self.rgb_box.setChecked(False)
        rgb_form = QFormLayout(self.rgb_box)
        self.rgb_spins = {}
        for name, label, minimum, value in (("intensity", "RGB strength", 0, 1),
            ("reveal", "Reveal", 0, 1), ("softness", "Reveal softness", .001, .1)):
            spin = enable_focused_wheel(QDoubleSpinBox())
            spin.setRange(minimum, 1)
            spin.setDecimals(3)
            spin.setSingleStep(.05)
            spin.setValue(value)
            spin.valueChanged.connect(lambda _value: self.changed.emit())
            rgb_form.addRow(label, spin)
            self.rgb_spins[name] = spin
        self.rgb_inverse = QCheckBox("Invert reveal mask")
        self.rgb_inverse.toggled.connect(lambda _on: self.changed.emit())
        rgb_form.addRow(self.rgb_inverse)
        description = QLabel("Requires the source glow map. RGB supplies the colours, alpha masks their intensity, "
            "and red is the reveal mask. Uses RGB strength instead of the single-colour strength above. "
            "Reveal 0 is off; 1 shows the full glow. Game brightness may differ.")
        description.setWordWrap(True)
        rgb_form.addRow(description)
        self.rgb_box.toggled.connect(lambda _on: self.changed.emit())
        form.addRow(self.rgb_box)

    def value(self):
        return GlowAnimation(**{name: spin.value() for name, spin in self.spins.items()})

    def rgb_value(self):
        return RgbGlow(**{name: spin.value() for name, spin in self.rgb_spins.items()},
                       inverse=self.rgb_inverse.isChecked()) if self.rgb_box.isChecked() else None

    def refresh(self, value, rgb=None):
        for name, spin in self.spins.items():
            spin.blockSignals(True)
            spin.setValue(getattr(value, name))
            spin.blockSignals(False)
        self.rgb_box.blockSignals(True)
        self.rgb_box.setChecked(rgb is not None)
        self.rgb_box.blockSignals(False)
        rgb = rgb or RgbGlow()
        for name, spin in self.rgb_spins.items():
            spin.blockSignals(True)
            spin.setValue(getattr(rgb, name))
            spin.blockSignals(False)
        self.rgb_inverse.blockSignals(True)
        self.rgb_inverse.setChecked(rgb.inverse)
        self.rgb_inverse.blockSignals(False)
