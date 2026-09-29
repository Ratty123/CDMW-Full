"""Package choices for an already validated archive mesh."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.packages.layout import sanitize_mod_package_folder_name
from cdmw.models import ModPackageInfo


class MeshModExportDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        *,
        title: str,
        description: str,
        output_parent: str,
        output_choice: str,
        manager_profile: str,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Build Mod")
        self.resize(620, 360)
        layout = QVBoxLayout(self)
        hint = QLabel("Choose the mesh-only mod package and manager.", self)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QFormLayout()
        self.manager = QComboBox(self)
        for label, choice, kind, profile, suffix in (
            ("DMM Loose Mesh", "dmm_loose", "loose_mod", "dmm", "dmm"),
            ("JMM Loose Mesh", "jmm_loose", "loose_mod", "jmm", "jmm"),
            ("CDUMM Loose Mesh", "cdumm_loose", "loose_mod", "cdumm", "cdumm"),
            ("Crimson Sharp Loose Mesh", "crimson_sharp_loose", "loose_mod", "crimson_sharp", "crimson-sharp"),
            ("DMM Archive Group", "dmm_archive", "overlay_package", "dmm", "dmm-archive"),
        ):
            self.manager.addItem(label, userData=(choice, kind, profile, suffix))
        selected = next(
            (index for index in range(self.manager.count()) if self.manager.itemData(index)[0] == output_choice),
            next((index for index in range(self.manager.count()) if self.manager.itemData(index)[2] == manager_profile), 0),
        )
        self.manager.setCurrentIndex(selected)
        self.mod_name = QLineEdit(title, self)
        self.output_parent = QLineEdit(output_parent, self)
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.output_parent)
        browse = QPushButton("Browse...", self)
        browse.clicked.connect(self._browse)
        folder_row.addWidget(browse)
        self.version = QLineEdit("1.0", self)
        self.author = QLineEdit(self)
        self.description = QLineEdit(description, self)
        form.addRow("Mod manager", self.manager)
        form.addRow("Mod name", self.mod_name)
        form.addRow("Output folder", folder_row)
        form.addRow("Version", self.version)
        form.addRow("Author", self.author)
        form.addRow("Description", self.description)
        layout.addLayout(form)
        self.create_zip = QCheckBox("Create ZIP beside the mod folder", self)
        self.open_folder = QCheckBox("Open folder after creation", self)
        layout.addWidget(self.create_zip)
        layout.addWidget(self.open_folder)
        self.destination = QLabel(self)
        self.destination.setWordWrap(True)
        layout.addWidget(self.destination)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        self.build_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.build_button.setText("Build Mod")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.manager.currentIndexChanged.connect(self._refresh_destination)
        self.mod_name.textChanged.connect(self._refresh_destination)
        self.output_parent.textChanged.connect(self._refresh_destination)
        self._refresh_destination()

    def package_info(self) -> ModPackageInfo:
        return ModPackageInfo(
            title=self.mod_name.text().strip(),
            version=self.version.text().strip() or "1.0",
            author=self.author.text().strip(),
            description=self.description.text().strip(),
        )

    def output_path(self) -> Path:
        suffix = self.manager.currentData()[3]
        folder = sanitize_mod_package_folder_name(self.mod_name.text().strip())
        return Path(self.output_parent.text().strip()) / f"{folder}-{suffix}"

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose Build Mod Output Folder", self.output_parent.text())
        if folder:
            self.output_parent.setText(folder)

    def _refresh_destination(self) -> None:
        folder = self.output_parent.text().strip()
        valid = bool(self.mod_name.text().strip() and folder and Path(folder).is_absolute())
        self.build_button.setEnabled(valid)
        self.destination.setText(str(self.output_path()) if valid else "")
