"""Compact part selection and live absorption controls for New Item."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDoubleSpinBox, QFormLayout, QGroupBox, QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from cdmw.domain.new_item.translucency import TranslucencyChoice


class TranslucencyEditor(QGroupBox):
    changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__("Translucency (experimental)", parent)
        self.setCheckable(True)
        self.setChecked(False)
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        self.details = QWidget(self)
        details = QVBoxLayout(self.details)
        details.setContentsMargins(0, 0, 0, 0)
        self.parts = QListWidget()
        self.parts.setMaximumHeight(110)
        self.parts.setToolTip("Select the material parts that should be see-through.")
        details.addWidget(self.parts)
        form = QFormLayout()
        self.thickness = QDoubleSpinBox()
        self.extinction = QDoubleSpinBox()
        for spin, value in ((self.thickness, 0.1), (self.extinction, 0.3)):
            spin.setRange(0.0, 1.0)
            spin.setDecimals(3)
            spin.setSingleStep(0.01)
            spin.setKeyboardTracking(False)
            spin.setValue(value)
            spin.valueChanged.connect(self._edited)
        self.thickness.setToolTip("Higher thickness makes the material less see-through. Texture colour and viewing angle also affect it.")
        self.extinction.setToolTip("How much light is absorbed. Higher values make the material less see-through.")
        form.addRow("Thickness", self.thickness)
        form.addRow("Extinction", self.extinction)
        details.addLayout(form)
        hint = QLabel(
            "Approximate viewport preview; game refraction and lighting may differ. "
            "Uses Plain PBR materials. Keep glowing details on separate parts."
        )
        hint.setWordWrap(True)
        details.addWidget(hint)
        layout.addWidget(self.details)
        self.parts.itemChanged.connect(self._edited)
        self.toggled.connect(self._edited)
        self.details.setVisible(False)

    def refresh(self, parts, choice):
        self._loading = True
        try:
            self.parts.clear()
            chosen = {name.casefold() for name in choice.parts} if choice else set()
            for name, label in parts:
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, name)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if name.casefold() in chosen else Qt.CheckState.Unchecked)
                self.parts.addItem(item)
            if choice is not None:
                self.thickness.setValue(choice.thickness)
                self.extinction.setValue(choice.extinction)
            self.setChecked(choice is not None and bool(parts))
            self.setEnabled(bool(parts))
            self.details.setVisible(self.isChecked())
            self.setToolTip("Import a model to experiment with translucent materials." if not parts else "Turn off to restore the imported materials.")
        finally:
            self._loading = False

    def _edited(self, *_args):
        if self._loading:
            return
        self.details.setVisible(self.isChecked())
        parts = tuple(
            str(self.parts.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.parts.count())
            if self.parts.item(index).checkState() == Qt.CheckState.Checked
        )
        self.changed.emit(
            TranslucencyChoice(parts, self.thickness.value(), self.extinction.value())
            if self.isChecked() and parts else None
        )
