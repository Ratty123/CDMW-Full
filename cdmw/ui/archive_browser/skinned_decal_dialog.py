"""Small editor for existing, structurally decoded decal properties."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from cdmw.core.skinned_decal import SkinnedDecalDocument, encode_decal_value


class SkinnedDecalDialog(QDialog):
    def __init__(self, document: SkinnedDecalDocument, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Skinned Decal")
        self.resize(900, 520)
        layout = QVBoxLayout(self)
        note = QLabel("Edit existing texture paths and decal settings. Missing settings keep their game defaults. Save creates a loose PASEQ copy; in-game appearance and attachment are not verified.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(len(document.fields), 2, self)
        self.table.setHorizontalHeaderLabels(["Setting", "Value"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._editors = []
        events = {}
        for row, field in enumerate(document.fields):
            # Full paths in tooltips disambiguate multiple events and the two
            # independently authored transform properties.
            label = field.path.removeprefix("[0].")
            if "._eventData." in field.path:
                prefix, label = field.path.split("._eventData.", 1)
                number = events.setdefault(prefix, len(events) + 1)
                label = f"{number}: {label}"
            item = QTableWidgetItem(label)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item.setToolTip(field.path)
            self.table.setItem(row, 0, item)
            editor = QLineEdit(field.text(), self.table)
            editor.setToolTip(field.type_name + "\n" + field.path)
            if field.type_name == "Transform":
                editor.setToolTip("Transform: scale XYZ, rotation quaternion XYZW, position XYZ.")
            self.table.setCellWidget(row, 1, editor)
            self._editors.append((field, editor))
        layout.addWidget(self.table)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def changes(self) -> tuple[tuple[str, str], ...]:
        return tuple((field.path, editor.text()) for field, editor in self._editors if editor.text() != field.text())

    def accept(self):
        try:
            for field, editor in self._editors:
                if editor.text() != field.text():
                    encode_decal_value(field, editor.text())
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Decal Setting", str(exc))
            return
        super().accept()
