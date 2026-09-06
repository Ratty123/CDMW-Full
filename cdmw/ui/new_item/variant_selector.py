"""Exact variant selection and camera restoration after a replacement is ready."""
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QComboBox


class VariantSelector(QWidget):
    def __init__(self, controller, panel):
        super().__init__(panel)
        self.controller,self.panel,self._restore = controller,panel,None
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
        controller.variant_about_to_change.connect(self._save_camera)
        controller.variant_changed.connect(self._changed)
        panel.preview.ready.connect(self._ready)
        self.refresh()

    def refresh(self,*_):
        identity = self.controller.current_variant_identity()
        self.choice.blockSignals(True)
        self.choice.clear()
        for key,label in self.controller.variant_choices():
            self.choice.addItem(label,key)
        # QVariant compares Python tuple payloads by object identity. Bindings are
        # reconstructed by the controller, so select by their exact path values.
        index = next((i for i in range(self.choice.count())
                      if self.choice.itemData(i) == identity), -1)
        self.choice.setCurrentIndex(index)
        self.choice.blockSignals(False)
        if identity:
            self.choice.setToolTip(f"Prefab: {identity[0]}\nModel: {identity[1]}")
        authored = sum(state.appearance.custom_model or state.appearance.dyes is not None for state in self.controller._variant_states.values())
        self.state.setText(f"{authored}/{self.choice.count()}")
        self.state.setToolTip(f"{authored} customized / {self.choice.count()} bindings")

    def _select(self):
        identity = self.choice.currentData()
        if identity is not None:
            self.controller.select_variant(identity)

    def _save_camera(self,identity):
        state = self.controller._variant_states.get(identity)
        host = self.panel.preview.host
        if state is not None and host is not None:
            state.camera = host.view_state_snapshot()

    def _changed(self,identity):
        state = self.controller._variant_states.get(identity)
        self._restore = (identity,state.camera) if state is not None and state.camera else None
        self.panel._preview_mesh_token = None
        self.panel._sync_placement_numbers(self.controller.model_placement)
        for control,value in ((self.panel.plain_pbr,self.controller.draft.material_route.value=="plain_pbr"),
                              (self.panel.keep_physics,self.controller.draft.keep_template_physics)):
            control.blockSignals(True)
            control.setChecked(value)
            control.blockSignals(False)
        self.refresh()
        self.panel.refresh_preview()

    def _ready(self):
        if self._restore is None or self.panel.preview.host is None:
            return
        identity,state = self._restore
        if identity == self.controller.current_variant_identity() and self.panel.preview._loaded_token == self.panel._preview_mesh_token:
            self.panel.preview.host.restore_view_state(state)
            self._restore = None
