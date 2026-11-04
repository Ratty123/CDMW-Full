"""Experimental equipment visibility choices for the selected component."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout,
)

from cdmw.domain.new_item.body_visibility import BodyVisibilityChoice
from cdmw.services.active_ui_translation import translate_active_ui_text


class BodyVisibilityEditor(QGroupBox):
    changed = Signal(object)
    layers_requested = Signal()
    #: the current choice, for every worn component of the item
    apply_to_worn_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Body underneath (experimental)")
        self.setObjectName("body_visibility_editor")
        layout = QVBoxLayout(self)
        self.scope = QLabel("")
        self.scope.setObjectName("new_item_intro")
        self.scope.setWordWrap(True)
        layout.addWidget(self.scope)
        self.keep_skin = QCheckBox("Keep underlying skin/head")
        self.keep_skin.setObjectName("body_visibility_keep_skin")
        self.keep_hair = QCheckBox("Keep hair/beard")
        self.keep_hair.setObjectName("body_visibility_keep_hair")
        self.keep_skin.setToolTip("Stop this component's cut rule from hiding the body and head beneath it. Off uses the template's rule.")
        self.keep_hair.setToolTip("Ask this component to preserve character hair and beard. Helmet-owned item hair keeps its template rules.")
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
        apply_row = QHBoxLayout()
        self.apply_to_worn = QPushButton("Apply to all worn components")
        self.apply_to_worn.setObjectName("body_visibility_apply_worn")
        self.apply_to_worn.setToolTip("Give every worn component of this item these choices. Kept layers apply only where "
                                      "a component's own rule cuts them. The ground model and other items are not changed.")
        self.apply_to_worn.clicked.connect(self._apply_to_worn)
        apply_row.addWidget(self.apply_to_worn)
        apply_row.addStretch(1)
        layout.addLayout(apply_row)
        self.note = QLabel("A garment's cut rule hides the body near its geometry, even where the garment leaves skin "
                           "uncovered. Components hidden in export never keep their cut rule. Test in game: the preview does "
                           "not simulate these rules, and other equipment can still hide parts.")
        self.note.setObjectName("new_item_intro")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self._loading = False
        self.keep_skin.toggled.connect(self._changed)
        self.keep_hair.toggled.connect(self._changed)
        self.layers.itemChanged.connect(self._changed)
        self.find_layers.clicked.connect(self.layers_requested.emit)

    def refresh(self, choice, *, enabled=True, layers=None, looking=False, component="", applicable=True, hidden=False):
        """``layers`` is the selected component's cut receivers, or None before a lookup."""
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
            usable = bool(enabled and applicable)
            for widget in (self.keep_skin, self.keep_hair, self.layers):
                widget.setEnabled(usable)
            self.find_layers.setEnabled(usable and not looking)
            self.apply_to_worn.setEnabled(bool(enabled))
            if not enabled:
                self.scope.setText(translate_active_ui_text("Choose a template first."))
            elif not applicable:
                self.scope.setText(translate_active_ui_text(
                    "{name} has no body-cut rule in the template, so there is nothing to keep.").format(name=component))
            elif hidden:
                self.scope.setText(translate_active_ui_text(
                    "{name} is hidden in export and no longer hides the body. These choices apply if you show it again.").format(
                    name=component))
            elif component:
                self.scope.setText(translate_active_ui_text("Applies to {name} only.").format(name=component))
            else:
                self.scope.setText("")
        finally:
            self._loading = False

    def kept_layers(self) -> frozenset[str]:
        return frozenset(self.layers.item(row).data(Qt.UserRole) for row in range(self.layers.count())
                         if self.layers.item(row).checkState() == Qt.Checked)

    def current_choice(self) -> BodyVisibilityChoice:
        return BodyVisibilityChoice(self.keep_skin.isChecked(), self.keep_hair.isChecked(), self.kept_layers())

    def _changed(self, *_args):
        if not self._loading:
            self.changed.emit(self.current_choice())

    def _apply_to_worn(self):
        self.apply_to_worn_requested.emit(self.current_choice())
