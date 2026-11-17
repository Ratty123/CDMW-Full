"""Package choices for an already validated archive mesh."""

from __future__ import annotations

from pathlib import Path


from PySide6.QtCore import Qt
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
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.packages.layout import sanitize_mod_package_folder_name
from cdmw.models import ModPackageInfo
from cdmw.services.mesh_layer_visibility import CLOTHING_LAYERS


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
        body_files: tuple[str, ...] = (),
        texture_plan: tuple[str, ...] = (),
        texture_plan_with_body: tuple[str, ...] | None = None,
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
        # Step 8: each edited texture, written in the original's format, size and mips.
        # With a body a Fit follows, the list follows Include the body: the body's
        # textures are left out with it (item 5).
        self.texture_plan = QLabel(self)
        self.texture_plan.setObjectName("mesh_mod_texture_plan")
        self.texture_plan.setWordWrap(True)
        self.texture_plan.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._texture_plans = (tuple(texture_plan), tuple(
            texture_plan if texture_plan_with_body is None else texture_plan_with_body))
        layout.addWidget(self.texture_plan)
        # Off by default: the body a Fit follows is a reference, and shipping
        # it would override every other mod that changes that body.
        self.include_body = QCheckBox("Include the body", self)
        self.include_body_hint = QLabel(self.tr(
            "When off, the mod leaves out {files}, so other body mods keep working. "
            "Turn this on only to ship changes you made to the body."
        ).format(files=", ".join(body_files)), self)
        self.include_body_hint.setWordWrap(True)
        layout.addWidget(self.include_body)
        layout.addWidget(self.include_body_hint)
        self.include_body.setVisible(bool(body_files))
        self.include_body_hint.setVisible(bool(body_files))
        self._show_texture_plan(False)
        self.include_body.toggled.connect(self._show_texture_plan)
        # Off by default: changing shrink rules also ships the shared descriptor.
        self.keep_layers = QCheckBox("Keep layers underneath (experimental)", self)
        self.keep_layers.setObjectName("mesh_mod_keep_layers")
        self.keep_layers.setToolTip(
            "Stop this garment cutting the layers you tick where it used to cover them, for example "
            "Lowerbody to show pants under a shortened coat. Test in game: the preview does not simulate this.")
        self.layers = QListWidget(self)
        self.layers.setObjectName("mesh_mod_layers")
        self.layers.setMaximumHeight(140)
        for name in CLOTHING_LAYERS:
            # The list makes its own rows (B1): rows made in Python with the list as
            # their parent preceded a native fault when the Mesh Editor tab was
            # deleted after this dialog (6 of 8 runs; 0 of 8 made this way).
            self.layers.addItem(name)
            item = self.layers.item(self.layers.count() - 1)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
        self.layers_hint = QLabel(self.tr(
            "Changes every prefab that uses this mesh and ships the game's partshrinkdesc.xml, "
            "so another mod that ships that file conflicts with this one. Lowerbody is pants; "
            "layers this garment never cut are reported and change nothing."), self)
        self.layers_hint.setWordWrap(True)
        layout.addWidget(self.keep_layers)
        layout.addWidget(self.layers)
        layout.addWidget(self.layers_hint)
        self.keep_layers.toggled.connect(self._refresh_layers)
        self.layers.itemChanged.connect(self._refresh_destination)
        self.layers.setEnabled(False)
        self.layers_hint.setVisible(False)
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

    def kept_layers(self) -> tuple[str, ...]:
        if not self.keep_layers.isChecked():
            return ()
        return tuple(self.layers.item(row).data(Qt.ItemDataRole.UserRole) for row in range(self.layers.count())
                     if self.layers.item(row).checkState() == Qt.CheckState.Checked)

    def _show_texture_plan(self, include_body: bool) -> None:
        lines = self._texture_plans[1 if include_body else 0]
        if lines:
            self.texture_plan.setText("Edited textures in this mod:\n" + "\n".join(lines))
        self.texture_plan.setVisible(bool(lines))

    def _refresh_layers(self, *_args) -> None:
        enabled = self.keep_layers.isChecked()
        self.layers.setEnabled(enabled)
        self.layers_hint.setVisible(enabled)
        self._refresh_destination()

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose Build Mod Output Folder", self.output_parent.text())
        if folder:
            self.output_parent.setText(folder)

    def _refresh_destination(self) -> None:
        folder = self.output_parent.text().strip()
        layers = getattr(self, "keep_layers", None)
        valid = bool(self.mod_name.text().strip() and folder and Path(folder).is_absolute()
                     and (layers is None or not layers.isChecked() or self.kept_layers()))
        self.build_button.setEnabled(valid)
        self.destination.setText(str(self.output_path()) if valid else "")
