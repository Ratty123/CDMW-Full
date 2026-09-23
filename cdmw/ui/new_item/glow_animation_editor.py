"""Compact emission animation controls; all texture preparation stays in workers."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QFormLayout, QGroupBox

from cdmw.domain.mesh.emission import GlowAnimation, RgbGlow
from cdmw.ui.wheel_guard import enable_focused_wheel


class GlowAnimationEditor(QGroupBox):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__("Animation (experimental)", parent)
        form = QFormLayout(self)
        self.spins = {}
        for name, label, maximum, description in (
            ("flow_u", "Scroll U", 10, "Moves the glow texture horizontally across its UVs. Zero stops scrolling; a solid glow map has no visible motion."),
            ("flow_v", "Scroll V", 10, "Moves the glow texture vertically across its UVs. Zero stops scrolling; a solid glow map has no visible motion."),
            ("pulse_frequency", "Pulse speed", 10, "How quickly the glow brightens and dims. Zero keeps it steady. Uses the shader's time scale, not cycles per second."),
            ("pulse_minimum", "Pulse floor", 1, "Minimum brightness during a pulse, capped by each pixel's glow strength. Zero lets the pulse fade out fully."),
        ):
            spin = enable_focused_wheel(QDoubleSpinBox())
            spin.setRange(0, maximum)
            spin.setDecimals(3)
            spin.setSingleStep(0.05)
            spin.setKeyboardTracking(False)
            spin.setToolTip(description)
            spin.setObjectName("new_item_glow_" + name)
            spin.valueChanged.connect(lambda _value: self.changed.emit())
            form.addRow(label, spin)
            form.labelForField(spin).setToolTip(description)
            self.spins[name] = spin
        self.setToolTip("Zero speed is static. Scroll affects the glow map only; a solid map cannot show movement. "
                      "Pulse floor is a brightness floor, capped by the glow at each pixel. "
                      "Animated glow cannot share a part with translucency. Preview timing is approximate.")
        self.rgb_box = QGroupBox("Use RGB glow map")
        self.rgb_box.setCheckable(True)
        self.rgb_box.setChecked(False)
        rgb_form = QFormLayout(self.rgb_box)
        self.rgb_spins = {}
        for name, label, minimum, value, description in (
            ("intensity", "RGB strength", 0, 1, "Brightness of the source RGB glow, from off at 0 to full strength at 1. Replaces the ordinary Strength setting."),
            ("reveal", "Reveal", 0, 1, "Reveals glow using the source texture's red channel as a mask. Zero hides all glow; 1 reveals it all."),
            ("softness", "Reveal softness", .001, .1, "Width of the reveal transition. Lower values give a sharp edge; higher values give a softer fade.")):
            spin = enable_focused_wheel(QDoubleSpinBox())
            spin.setRange(minimum, 1)
            spin.setDecimals(3)
            spin.setSingleStep(.05)
            spin.setValue(value)
            spin.setKeyboardTracking(False)
            spin.setToolTip(description)
            spin.valueChanged.connect(lambda _value: self.changed.emit())
            rgb_form.addRow(label, spin)
            rgb_form.labelForField(spin).setToolTip(description)
            self.rgb_spins[name] = spin
        self.rgb_inverse = QCheckBox("Invert reveal mask")
        self.rgb_inverse.setToolTip("Reverses the source red-channel mask so the opposite areas appear first as Reveal increases.")
        self.rgb_inverse.toggled.connect(lambda _on: self.changed.emit())
        rgb_form.addRow(self.rgb_inverse)
        self.rgb_box.setToolTip("Requires the source glow map. RGB supplies the colours, alpha masks their intensity, "
            "and red is the reveal mask. Uses RGB strength instead of the single-colour strength above. "
            "Reveal 0 is off; 1 shows the full glow. Game brightness may differ.")
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
