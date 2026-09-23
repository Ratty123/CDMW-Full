"""Exact variant selection without changing the resident preview camera."""
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QComboBox


class VariantSelector(QWidget):
    def __init__(self, controller, panel):
        super().__init__(panel)
        self.controller,self.panel = controller,panel
        self._choices = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.addWidget(QLabel("Variant:"))
        self.choice = QComboBox()
        self.choice.setMinimumContentsLength(24)
        self.choice.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.choice.currentIndexChanged.connect(self._select)
        layout.addWidget(self.choice,1)
        self.state = QLabel()
        layout.addWidget(self.state)
        controller.template_changed.connect(self.refresh)
        controller.plan_invalidated.connect(self.refresh)
        controller.variant_changed.connect(self._changed)
        self.refresh()

    def refresh(self,*_):
        identity = self.controller.current_variant_identity()
        self.choice.blockSignals(True)
        choices = self.controller.variant_choices()
        if choices != self._choices:
            self._choices = choices
            self.choice.clear()
            for key,label in choices:
                self.choice.addItem(label,key)
        # QVariant compares Python tuple payloads by object identity. Bindings are
        # reconstructed by the controller, so select by their exact path values.
        index = next((i for i in range(self.choice.count())
                      if self.choice.itemData(i) == identity), -1)
        self.choice.setCurrentIndex(index)
        self.choice.blockSignals(False)
        if identity:
            self.choice.setToolTip(f"Prefab: {identity[0]}\nModel: {identity[1]}")
        authored = sum(bool(state.appearance.custom_model or state.appearance.dyes != ()
                            or state.appearance.glow_parts or state.appearance.translucency is not None or state.appearance.shader_controls
                            or state.appearance.template_transform)
                       for state in self.controller._variant_states.values())
        self.state.setText(f"{authored}/{self.choice.count()}")
        self.state.setToolTip(f"{authored} customized / {self.choice.count()} bindings")

    def _select(self):
        identity = self.choice.currentData()
        if identity is not None:
            self.controller.select_variant(identity)

    def _changed(self,identity):
        self.panel._preview_mesh_token = None
        self.panel._sync_placement_numbers(self.controller.model_placement)
        for control,value in ((self.panel.plain_pbr,self.controller.draft.material_route.value=="plain_pbr"),
                              (self.panel.keep_physics,self.controller.draft.keep_template_physics)):
            control.blockSignals(True)
            control.setChecked(value)
            control.blockSignals(False)
        self.refresh()
        self.panel.refresh_preview()
