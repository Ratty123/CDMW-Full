"""The shared, persistent gizmo preference for New Item preview surfaces."""

from weakref import WeakSet

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QCheckBox
from shiboken6 import isValid


GIZMO_VISIBLE_SETTING = "ui/new_item/gizmo_visible"


class PreviewGizmoCheckBox(QCheckBox):
    _instances: WeakSet = WeakSet()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setText("Show gizmo")
        self.setObjectName("new_item_gizmo_visible")
        self.setToolTip(
            "Show the model or effect transform handles. The upper-right orientation control stays available."
        )
        settings = QSettings("CrimsonDesertModWorkbench", "CrimsonDesertModWorkbench")
        self.setChecked(settings.value(GIZMO_VISIBLE_SETTING, True, type=bool))
        self._instances.add(self)
        self.toggled.connect(self._remember)

    def _remember(self, visible: bool) -> None:
        settings = QSettings("CrimsonDesertModWorkbench", "CrimsonDesertModWorkbench")
        settings.setValue(GIZMO_VISIBLE_SETTING, visible)
        for checkbox in tuple(self._instances):
            if checkbox is not self and isValid(checkbox) and checkbox.isChecked() != visible:
                checkbox.setChecked(visible)
