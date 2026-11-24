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
        hair_mode: bool = False,
        hair_stem: str = "",
        hair_character: str = "",
        dmm_install: Path | str | None = None,
    ) -> None:
        super().__init__(parent)
        self._hair_mode = bool(hair_mode)
        self._initial_hair_stem = str(hair_stem or "").strip()
        self._hair_character = str(hair_character or "").strip()
        self._stem_manually_edited = False
        self._dmm_mods_dir: Path | None = None
        self._dmm_mods_error = ""
        if self._hair_mode and dmm_install is not None:
            from cdmw.services.dmm_send import dmm_mods_folder
            try:
                self._dmm_mods_dir = dmm_mods_folder(dmm_install)
            except ValueError as exc:
                self._dmm_mods_error = str(exc)

        self.setWindowTitle("Build Hairstyle Mod" if self._hair_mode else "Build Mod")
        self.resize(640 if self._hair_mode else 620, 440 if self._hair_mode else 360)
        layout = QVBoxLayout(self)
        hint = QLabel(
            "Not tested in game. Hairstyles may not work correctly. Choose how to package this hairstyle for DMM."
            if self._hair_mode
            else "Choose the mesh-only mod package and manager.",
            self,
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QFormLayout()
        self.manager = QComboBox(self)
        choices = (
            (
                ("Add New Barber Hairstyle (DMM Additive)", "hair_add", "overlay_package", "dmm", "hair-mod"),
                ("Replace Existing Hairstyle (DMM Loose Mod)", "hair_replace_loose", "loose_mod", "dmm", "hair-replace-dmm"),
                ("Add New Barber Hairstyle (Full Tables Archive)", "hair_add_full", "overlay_package", "dmm", "hair-mod-full"),
            )
            if self._hair_mode
            else (
                ("DMM Loose Mesh", "dmm_loose", "loose_mod", "dmm", "dmm"),
                ("DMM Archive Group", "dmm_archive", "overlay_package", "dmm", "dmm-archive"),
            )
        )
        for label, choice, kind, profile, suffix in choices:
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
        self.output_browse = QPushButton("Browse...", self)
        self.output_browse.clicked.connect(self._browse)
        folder_row.addWidget(self.output_browse)
        self.version = QLineEdit("1.0", self)
        self.author = QLineEdit(self)
        self.description = QLineEdit(description, self)
        form.addRow("Mod manager" if not self._hair_mode else "Package mode", self.manager)
        form.addRow("Mod name", self.mod_name)
        form.addRow("Output folder", folder_row)

        self.hair_stem = QLineEdit(self._initial_hair_stem, self)
        self.hair_stem.setObjectName("hair_mod_stem")
        self.hair_stem.setToolTip(
            "Lowercase ASCII prefab stem used in barber tables and private archive files (max 127 characters)."
        )
        self.hair_stem.textEdited.connect(self._mark_stem_edited)
        self.custom_icon_path = QLineEdit("", self)
        self.custom_icon_path.setObjectName("hair_custom_icon_path")
        self.custom_icon_path.setPlaceholderText("Use donor barber icon")
        self.custom_icon_path.setToolTip(
            "Optional PNG, JPG, WEBP, BMP, or DDS image resized and encoded to match the character's barber icon format."
        )
        icon_row = QWidget(self)
        icon_layout = QHBoxLayout(icon_row)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.addWidget(self.custom_icon_path)
        self.icon_browse = QPushButton("Browse...", icon_row)
        self.icon_browse.clicked.connect(self._browse_icon)
        icon_layout.addWidget(self.icon_browse)
        self.icon_clear = QPushButton("Clear", icon_row)
        self.icon_clear.clicked.connect(self.custom_icon_path.clear)
        icon_layout.addWidget(self.icon_clear)
        self._hair_stem_label = QLabel("Hairstyle ID", self)
        self._custom_icon_label = QLabel("Custom barber icon (optional)", self)
        self._custom_icon_row = icon_row
        if self._hair_mode:
            form.addRow(self._hair_stem_label, self.hair_stem)
            form.addRow(self._custom_icon_label, self._custom_icon_row)
        else:
            self.hair_stem.hide()
            self._hair_stem_label.hide()
            self._custom_icon_label.hide()
            self._custom_icon_row.hide()

        form.addRow("Version", self.version)
        form.addRow("Author", self.author)
        form.addRow("Description", self.description)
        layout.addLayout(form)
        self.hair_dmm_entries_hint = QLabel(self.tr(
            "DMM lists this mod as two entries: the hairstyle and its item registrations. Enable both, in "
            "DMM 4.4.0 or newer; without the item registrations the new hairstyle does not load."
        ), self)
        self.hair_dmm_entries_hint.setObjectName("hair_dmm_entries_hint")
        self.hair_dmm_entries_hint.setWordWrap(True)
        layout.addWidget(self.hair_dmm_entries_hint)
        self.hair_dmm_entries_hint.setVisible(False)
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
        self.include_body.setVisible(bool(body_files) and not self._hair_mode)
        self.include_body_hint.setVisible(bool(body_files) and not self._hair_mode)
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
        if self._hair_mode:
            self.keep_layers.hide()
            self.layers.hide()
            self.layers_hint.hide()

        self.send_to_dmm = QCheckBox("Send directly to DMM mods folder", self)
        self.send_to_dmm.setObjectName("hair_send_to_dmm")
        if self._hair_mode and dmm_install is not None:
            if self._dmm_mods_dir is not None:
                self.send_to_dmm.setToolTip(f"Publish or replace CDMW's mod folder directly inside {self._dmm_mods_dir}.")
            else:
                self.send_to_dmm.setEnabled(False)
                self.send_to_dmm.setToolTip(self._dmm_mods_error or "Open DMM once so its mods folder exists.")
        else:
            self.send_to_dmm.hide()
        layout.addWidget(self.send_to_dmm)

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
        self.manager.currentIndexChanged.connect(self._refresh_hair_fields)
        self.manager.currentIndexChanged.connect(self._refresh_destination)
        self.mod_name.textEdited.connect(self._sync_stem_from_name)
        self.mod_name.textChanged.connect(self._refresh_destination)
        self.output_parent.textChanged.connect(self._refresh_destination)
        self.hair_stem.textChanged.connect(self._refresh_destination)
        self.custom_icon_path.textChanged.connect(self._refresh_destination)
        self.send_to_dmm.toggled.connect(self._refresh_destination)
        self._refresh_hair_fields()
        self._refresh_destination()

    def package_info(self) -> ModPackageInfo:
        return ModPackageInfo(
            title=self.mod_name.text().strip(),
            version=self.version.text().strip() or "1.0",
            author=self.author.text().strip(),
            description=self.description.text().strip(),
        )

    def hair_export_choice(self) -> str:
        return str(self.manager.currentData()[0])

    def target_stem(self) -> str:
        return self.hair_stem.text().strip() if self._hair_mode else ""

    def custom_icon(self) -> Path | None:
        if not self._hair_mode:
            return None
        text = self.custom_icon_path.text().strip()
        return Path(text) if text else None

    def send_to_dmm_enabled(self) -> bool:
        return bool(self._hair_mode and self.send_to_dmm.isChecked() and self._dmm_mods_dir is not None)

    def dmm_mods_dir(self) -> Path | None:
        return self._dmm_mods_dir

    def output_path(self) -> Path:
        folder = sanitize_mod_package_folder_name(self.mod_name.text().strip())
        if self.send_to_dmm_enabled() and self._dmm_mods_dir is not None:
            return self._dmm_mods_dir / folder
        suffix = self.manager.currentData()[3]
        return Path(self.output_parent.text().strip()) / f"{folder}-{suffix}"

    def kept_layers(self) -> tuple[str, ...]:
        if not self.keep_layers.isChecked():
            return ()
        return tuple(self.layers.item(row).data(Qt.ItemDataRole.UserRole) for row in range(self.layers.count())
                     if self.layers.item(row).checkState() == Qt.CheckState.Checked)

    def _mark_stem_edited(self) -> None:
        self._stem_manually_edited = True

    def _sync_stem_from_name(self) -> None:
        if not self._hair_mode or self._stem_manually_edited or self.hair_export_choice() == "hair_replace_loose":
            return
        if not self._hair_character:
            return
        from cdmw.domain.hair_registration import HairRegistrationError, hair_stem_from_style_name
        try:
            self.hair_stem.setText(
                hair_stem_from_style_name(self.mod_name.text(), self._hair_character, self._initial_hair_stem)
            )
        except (HairRegistrationError, ValueError):
            pass

    def _refresh_hair_fields(self) -> None:
        if not self._hair_mode:
            return
        adding = self.hair_export_choice() != "hair_replace_loose"
        self.hair_dmm_entries_hint.setVisible(self.hair_export_choice() == "hair_add")
        self._hair_stem_label.setVisible(adding)
        self.hair_stem.setVisible(adding)
        self._custom_icon_label.setVisible(adding)
        self._custom_icon_row.setVisible(adding)
        self.custom_icon_path.setVisible(adding)

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

    def _browse_icon(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose Custom Barber Icon", self.custom_icon_path.text(),
            "Images & DDS (*.png *.jpg *.jpeg *.webp *.bmp *.dds)",
        )
        if path:
            self.custom_icon_path.setText(path)

    def _refresh_destination(self) -> None:
        send_direct = self.send_to_dmm_enabled()
        self.output_parent.setEnabled(not send_direct)
        self.output_browse.setEnabled(not send_direct)
        self.create_zip.setEnabled(not send_direct)
        folder = self.output_parent.text().strip()
        layers = getattr(self, "keep_layers", None)
        valid = bool(
            self.mod_name.text().strip()
            and (send_direct or (folder and Path(folder).is_absolute()))
            and (layers is None or not layers.isChecked() or self.kept_layers())
        )
        error_text = ""
        if valid and self._hair_mode and self.hair_export_choice() != "hair_replace_loose":
            from cdmw.domain.hair_registration import HairRegistrationError, validate_hair_stem
            try:
                validate_hair_stem(self.hair_stem.text().strip())
            except HairRegistrationError as exc:
                valid = False
                error_text = str(exc)
            if valid:
                icon_text = self.custom_icon_path.text().strip()
                if icon_text and not Path(icon_text).is_file():
                    valid = False
                    error_text = "Choose an existing image or DDS file for the custom barber icon."
        self.build_button.setEnabled(valid)
        self.destination.setText(error_text if error_text else (str(self.output_path()) if valid else ""))
