"""Small explicit per-part skinning editor; preparation stays on the controller worker."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout

from cdmw.domain.mesh.skin_policy import SkinningChoice


class SkinningDialog(QDialog):
    def __init__(self, source, apply_choices, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Imported skin weights")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(690, 380)
        layout = QVBoxLayout(self)
        explanation = QLabel("Choose weights for each part. Reduction reports appear in Import details before Apply placement.")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        table = QTableWidget(len(source.raw_import_mesh.submeshes), 3)
        table.setHorizontalHeaderLabels(["Imported part", "Skin weights", "Transfer donor"])
        table.horizontalHeader().setStretchLastSection(True)
        table.setColumnWidth(0, 260)
        layout.addWidget(table)
        current = {choice.part_index: choice for choice in source.skinning_choices}
        combos, donors = [], []
        for index, part in enumerate(source.raw_import_mesh.submeshes):
            name = QTableWidgetItem(part.name)
            name.setFlags(name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(index, 0, name)
            combo = QComboBox()
            authored = bool(part.interchange_skin or part.bone_indices or part.bone_weights)
            if authored:
                combo.addItem("Keep imported weights", ("preserve", 6))
                combo.addItem("Reduce to six influences", ("reduce", 6))
                combo.addItem("Reduce to four influences", ("reduce", 4))
            combo.addItem("Transfer from template", ("transfer", 6))
            combo.addItem("Transfer from verified body", ("body_transfer", 6))
            choice = current.get(index, SkinningChoice(index, "preserve" if authored else "transfer"))
            combo.setCurrentIndex(max(0, combo.findData((choice.policy, choice.capacity))))
            combo.setToolTip("Keep preserves rigid attachments too. Transfer replaces the artist's weights. "
                             "Reduction removes the weakest influences and reports lost mass; review deformation.")
            table.setCellWidget(index, 1, combo)
            combos.append(combo)
            donor = QComboBox()
            donor.addItem("Whole template", ())
            names = source.skinning_reports[0].donor_part_names if source.skinning_reports else ()
            for part_index, part_name in enumerate(names):
                donor.addItem(part_name, (part_index,))
            donor.setCurrentIndex(max(0, donor.findData(choice.donor_parts)))
            donor.setEnabled(choice.policy == "transfer")
            combo.currentIndexChanged.connect(lambda _index, c=combo, d=donor: d.setEnabled(c.currentData()[0] == "transfer"))
            table.setCellWidget(index, 2, donor)
            donors.append(donor)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(buttons)
        buttons.rejected.connect(self.reject)

        def apply():
            choices = tuple(SkinningChoice(index, *combo.currentData(),
                            donor_parts=tuple(donors[index].currentData()) if combo.currentData()[0] == "transfer" else ())
                            for index, combo in enumerate(combos))
            if apply_choices(choices):
                self.accept()

        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(apply)
