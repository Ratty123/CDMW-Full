"""Experimental equipment visibility choices for the current variant."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QGroupBox, QVBoxLayout

from cdmw.domain.new_item.body_visibility import BodyVisibilityChoice


class BodyVisibilityEditor(QGroupBox):
    changed = Signal(object)

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
        self.setToolTip("Applies to the current equipment variant, across its materials. Whole-part hiding applies to its entire prefab. "
                        "Test in game: the preview does not simulate these rules, and other equipment may still hide parts.")
        self._loading = False
        self.keep_skin.toggled.connect(self._changed)
        self.keep_hair.toggled.connect(self._changed)

    def refresh(self, choice, *, enabled=True):
        self._loading = True
        try:
            self.keep_skin.setChecked(choice.keep_skin)
            self.keep_hair.setChecked(choice.keep_hair)
            self.setEnabled(enabled)
        finally:
            self._loading = False

    def _changed(self, *_args):
        if not self._loading:
            self.changed.emit(BodyVisibilityChoice(self.keep_skin.isChecked(), self.keep_hair.isChecked()))
