"""Experimental equipment visibility choices for the current variant."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QGroupBox, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout

from cdmw.domain.new_item.body_visibility import BodyVisibilityChoice


class BodyVisibilityEditor(QGroupBox):
    changed = Signal(object)
    layers_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Underlying parts (experimental)")
        self.setObjectName("body_visibility_editor")
        layout = QVBoxLayout(self)
        self.keep_skin = QCheckBox("Keep underlying skin/head")
        self.keep_skin.setObjectName("body_visibility_keep_skin")
        self.keep_hair = QCheckBox("Keep hair/beard")
        self.keep_hair.setObjectName("body_visibility_keep_hair")
        self.keep_skin.setToolTip("Ask this equipment variant to preserve the body and head beneath it. Turn off to use template rules.")
        self.keep_hair.setToolTip("Ask this equipment variant to preserve character hair and beard. Helmet-owned item hair keeps its template rules.")
        layout.addWidget(self.keep_skin)
        layout.addWidget(self.keep_hair)
        self.layers_label = QLabel("Keep these layers underneath:")
        layout.addWidget(self.layers_label)
        self.layers = QListWidget()
        self.layers.setObjectName("body_visibility_layers")
        self.layers.setToolTip("Clothing layers this equipment's shrink rule cuts, such as Lowerbody for pants. "
                               "Ticked layers are no longer cut where this equipment covers them.")
        self.layers.setMaximumHeight(120)
        layout.addWidget(self.layers)
        self.layers_status = QLabel("")
        self.layers_status.setObjectName("body_visibility_layers_status")
        self.layers_status.setWordWrap(True)
        layout.addWidget(self.layers_status)
        self.find_layers = QPushButton("Find layers")
        self.find_layers.setObjectName("body_visibility_find_layers")
        self.find_layers.setToolTip("Read which layers this variant's shrink rule cuts.")
        layout.addWidget(self.find_layers)
        self.setToolTip("Applies to the current equipment variant, across its materials. Whole-part hiding applies to its entire prefab. "
                        "Test in game: the preview does not simulate these rules, and other equipment may still hide parts.")
        self._loading = False
        self.keep_skin.toggled.connect(self._changed)
        self.keep_hair.toggled.connect(self._changed)
        self.layers.itemChanged.connect(self._changed)
        self.find_layers.clicked.connect(self.layers_requested.emit)

    def refresh(self, choice, *, enabled=True, layers=None, looking=False):
        """``layers`` is the variant's cut receivers, or None before a lookup."""
        self._loading = True
        try:
            self.keep_skin.setChecked(choice.keep_skin)
            self.keep_hair.setChecked(choice.keep_hair)
            names = tuple(dict.fromkeys((*(layers or ()), *sorted(choice.keep_receivers))))
            self.layers.clear()
            for name in names:
                item = QListWidgetItem(name)
                item.setData(Qt.UserRole, name)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if name in choice.keep_receivers else Qt.Unchecked)
                self.layers.addItem(item)
            if looking:
                status = "Looking up layers…"
            elif layers is None:
                status = "Click Find layers to list the layers this variant cuts."
            elif not layers:
                status = "This variant's shrink rule cuts no other clothing layers."
            else:
                status = ""
            self.layers_status.setText(status)
            self.layers_status.setVisible(bool(status))
            self.find_layers.setEnabled(enabled and not looking)
            self.setEnabled(enabled)
        finally:
            self._loading = False

    def kept_layers(self) -> frozenset[str]:
        return frozenset(self.layers.item(row).data(Qt.UserRole) for row in range(self.layers.count())
                         if self.layers.item(row).checkState() == Qt.Checked)

    def _changed(self, *_args):
        if not self._loading:
            self.changed.emit(BodyVisibilityChoice(self.keep_skin.isChecked(), self.keep_hair.isChecked(), self.kept_layers()))
