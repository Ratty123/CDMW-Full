"""Archive browser mod-ready export target dialogs."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cdmw.constants import (
    MOD_READY_PACKAGE_AUTHOR,
    MOD_READY_PACKAGE_DESCRIPTION,
    MOD_READY_PACKAGE_NEXUS_URL,
    MOD_READY_PACKAGE_TITLE,
    MOD_READY_PACKAGE_VERSION,
)
from cdmw.core.mod_package import (
    MOD_PACKAGE_MANAGER_PROFILE_LABELS,
    MOD_PACKAGE_MANAGER_PROFILES,
    MOD_PACKAGE_METADATA_ARTIFACTS_BY_KEY,
    ModPackageExportOptions,
    mod_package_export_options_for_profiles,
    mod_package_profile_uses_manager_metadata,
)
from cdmw.core.texture_pipeline.package_export import resolve_default_mod_ready_export_root
from cdmw.models import ModPackageInfo
from cdmw.services.workspace_layout import workspace_paths
from cdmw.ui.shell.help_widgets import make_help_button


class ArchiveModReadyExportMixin:
    """Shared dialogs for choosing mod-ready loose export targets."""



    def _prompt_archive_mod_ready_export_target(
        self,
        *,
        browse_title: str,
        initial_export_root: Path,
        initial_package_info: ModPackageInfo,
        initial_create_no_encrypt: bool,
        initial_include_related_files: bool = False,
        show_include_related_files_option: bool = False,
        dialog_title: str = "Write Mod-Ready Loose File",
        allow_dmm_texture_structure: bool = True,
        show_texture_resolution_manifest_option: bool = False,
        show_material_authority_report_option: bool = False,
        show_active_file_authority_audit_option: bool = False,
        parent: Optional[QWidget] = None,
    ) -> Optional[Tuple[Path, ModPackageInfo, bool, bool, ModPackageExportOptions]]:
        dialog_parent = parent if parent is not None else self
        dialog = QDialog(dialog_parent)
        dialog.setWindowTitle(dialog_title)
        dialog.setModal(True)
        dialog.resize(
            860,
            500
            if (
                show_include_related_files_option
                or show_texture_resolution_manifest_option
                or show_material_authority_report_option
                or show_active_file_authority_audit_option
            )
            else 420,
        )

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        intro_label = QLabel(
            "Choose target mod managers. The app will write the right folders and metadata for each selected manager."
            + (
                " You can also include the resolved related DDS and sidecar files that were detected for the selected mesh."
                if show_include_related_files_option
                else ""
            )
        )
        intro_label.setWordWrap(True)
        intro_label.setObjectName("HintLabel")
        layout.addWidget(intro_label)

        form_layout = QGridLayout()
        form_layout.setHorizontalSpacing(8)
        form_layout.setVerticalSpacing(8)

        export_root_edit = QLineEdit(str(initial_export_root))
        browse_button = QPushButton("Browse...")
        title_edit = QLineEdit(str(getattr(initial_package_info, "title", "") or "").strip())
        version_edit = QLineEdit(str(getattr(initial_package_info, "version", "") or "").strip())
        author_edit = QLineEdit(str(getattr(initial_package_info, "author", "") or "").strip())
        description_edit = QLineEdit(str(getattr(initial_package_info, "description", "") or "").strip())
        default_dialog_options = mod_package_export_options_for_profiles(("dmm",))
        profile_checks_widget = QWidget()
        profile_checks_layout = QHBoxLayout(profile_checks_widget)
        profile_checks_layout.setContentsMargins(0, 0, 0, 0)
        profile_checks_layout.setSpacing(10)
        profile_checkboxes: Dict[str, QCheckBox] = {}
        for profile in MOD_PACKAGE_MANAGER_PROFILES:
            checkbox = QCheckBox(MOD_PACKAGE_MANAGER_PROFILE_LABELS.get(profile, profile))
            checkbox.setChecked(profile == "dmm")
            profile_checks_layout.addWidget(checkbox)
            profile_checkboxes[profile] = checkbox
        profile_checks_layout.addStretch(1)
        create_zip_checkbox = QCheckBox(MOD_PACKAGE_METADATA_ARTIFACTS_BY_KEY["ready_zip"].label)
        create_zip_checkbox.setChecked(default_dialog_options.create_zip)
        conflict_mode_combo = QComboBox()
        conflict_mode_combo.addItem("Normal conflicts", "")
        conflict_mode_combo.addItem("Override wins", "override")
        target_language_edit = QLineEdit()
        target_language_edit.setPlaceholderText("Optional, e.g. ko")
        include_related_files_checkbox = QCheckBox("Include resolved related files (textures, .xml, .pami)")
        include_related_files_checkbox.setChecked(bool(initial_include_related_files))
        include_related_files_checkbox.setVisible(bool(show_include_related_files_option))
        texture_resolution_manifest_checkbox = QCheckBox("CDMW texture resolution manifest")
        texture_resolution_manifest_checkbox.setChecked(False)
        texture_resolution_manifest_checkbox.setVisible(bool(show_texture_resolution_manifest_option))
        texture_resolution_manifest_checkbox.setToolTip(
            "Optional Workbench diagnostic JSON for reviewing final texture binding decisions. "
            "It is not required for DMM file-replace imports."
        )
        material_authority_report_checkbox = QCheckBox("CDMW material authority report/check")
        material_authority_report_checkbox.setChecked(False)
        material_authority_report_checkbox.setVisible(bool(show_material_authority_report_option))
        material_authority_report_checkbox.setToolTip(
            "Optional Workbench diagnostic JSON pair for reviewing Material Authority evidence and check status. "
            "Leave unchecked for normal mod-manager imports."
        )
        active_file_authority_audit_checkbox = QCheckBox("Active file authority audit report")
        active_file_authority_audit_checkbox.setChecked(False)
        active_file_authority_audit_checkbox.setVisible(bool(show_active_file_authority_audit_option))
        active_file_authority_audit_checkbox.setToolTip(
            "Optional Workbench diagnostic JSON for checking whether stale active loose files or mod archives "
            "may override this package in game."
        )

        title_edit.setPlaceholderText(MOD_READY_PACKAGE_TITLE)
        version_edit.setPlaceholderText(MOD_READY_PACKAGE_VERSION)
        author_edit.setPlaceholderText(MOD_READY_PACKAGE_AUTHOR)
        description_edit.setPlaceholderText(MOD_READY_PACKAGE_DESCRIPTION)

        form_layout.addWidget(QLabel("Parent export root"), 0, 0)
        form_layout.addWidget(export_root_edit, 0, 1)
        form_layout.addWidget(browse_button, 0, 2)
        form_layout.addWidget(QLabel("Package title"), 1, 0)
        form_layout.addWidget(title_edit, 1, 1, 1, 2)
        form_layout.addWidget(QLabel("Version"), 2, 0)
        form_layout.addWidget(version_edit, 2, 1, 1, 2)
        form_layout.addWidget(QLabel("Author"), 3, 0)
        form_layout.addWidget(author_edit, 3, 1, 1, 2)
        form_layout.addWidget(QLabel("Description"), 4, 0)
        form_layout.addWidget(description_edit, 4, 1, 1, 2)
        form_layout.addWidget(QLabel("Target Mod Managers"), 5, 0)
        form_layout.addWidget(profile_checks_widget, 5, 1, 1, 3)
        form_layout.addWidget(QLabel("Package output"), 6, 0)
        form_layout.addWidget(create_zip_checkbox, 6, 1, 1, 3)
        conflict_mode_label = QLabel("Conflict mode")
        target_language_label = QLabel("Target language")
        conflict_mode_help = make_help_button("CDUMM compatibility metadata. Normal leaves manager conflict behavior unchanged; Override asks compatible managers to prefer this mod when conflicts are detected.")
        target_language_help = make_help_button("Optional CDUMM compatibility metadata for language-specific packages. Leave empty for general packages.")
        form_layout.addWidget(conflict_mode_label, 7, 0)
        form_layout.addWidget(conflict_mode_combo, 7, 1, 1, 2)
        form_layout.addWidget(conflict_mode_help, 7, 3)
        form_layout.addWidget(target_language_label, 8, 0)
        form_layout.addWidget(target_language_edit, 8, 1, 1, 2)
        form_layout.addWidget(target_language_help, 8, 3)
        form_layout.addWidget(include_related_files_checkbox, 9, 0, 1, 3)
        form_layout.addWidget(texture_resolution_manifest_checkbox, 10, 0, 1, 3)
        form_layout.addWidget(material_authority_report_checkbox, 11, 0, 1, 3)
        form_layout.addWidget(active_file_authority_audit_checkbox, 12, 0, 1, 3)
        form_layout.setColumnStretch(1, 1)
        layout.addLayout(form_layout)

        def _selected_profiles() -> Tuple[str, ...]:
            return tuple(
                profile
                for profile, checkbox in profile_checkboxes.items()
                if checkbox.isChecked()
            ) or ("dmm",)

        def _apply_manager_profile() -> None:
            uses_manager_metadata = any(mod_package_profile_uses_manager_metadata(profile) for profile in _selected_profiles())
            for widget in (
                conflict_mode_label,
                conflict_mode_combo,
                conflict_mode_help,
                target_language_label,
                target_language_edit,
                target_language_help,
            ):
                widget.setVisible(uses_manager_metadata)

        for checkbox in profile_checkboxes.values():
            checkbox.toggled.connect(lambda _checked=False: _apply_manager_profile())
        _apply_manager_profile()

        hint_label = QLabel(
            "Warning: rebuilding a mesh payload does not automatically rewrite every referenced DDS or the companion material sidecars. "
            "For many PAC meshes, the matching .pac.xml still controls important material and texture assignments. "
            "For PAM / PAMLOD meshes, the matching .pami often carries the same kind of texture-role data. "
            "If the imported mesh changes submesh/material usage, you may also need to review the linked DDS files and those companion sidecars."
        )
        hint_label.setWordWrap(True)
        hint_label.setObjectName("HintLabel")
        layout.addWidget(hint_label)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addStretch(1)
        cancel_button = QPushButton("Cancel")
        continue_button = QPushButton("Continue")
        continue_button.setDefault(True)
        button_row.addWidget(cancel_button)
        button_row.addWidget(continue_button)
        layout.addLayout(button_row)

        result: List[object] = []

        def _browse_export_root() -> None:
            selected_dir = QFileDialog.getExistingDirectory(
                dialog,
                browse_title,
                export_root_edit.text().strip() or str(initial_export_root),
            )
            if selected_dir:
                export_root_edit.setText(selected_dir)

        def _accept() -> None:
            export_root_text = export_root_edit.text().strip()
            if not export_root_text:
                QMessageBox.warning(dialog, dialog_title, "Parent export root is required.")
                return
            export_root = Path(export_root_text).expanduser()
            package_info = ModPackageInfo(
                title=title_edit.text().strip() or MOD_READY_PACKAGE_TITLE,
                version=version_edit.text().strip() or MOD_READY_PACKAGE_VERSION,
                author=author_edit.text().strip(),
                description=description_edit.text().strip(),
                nexus_url="",
            )
            selected_profiles = _selected_profiles()
            uses_manager_metadata = any(mod_package_profile_uses_manager_metadata(profile) for profile in selected_profiles)
            export_options = mod_package_export_options_for_profiles(
                selected_profiles,
                create_zip=create_zip_checkbox.isChecked(),
                create_texture_resolution_manifest=texture_resolution_manifest_checkbox.isChecked()
                if show_texture_resolution_manifest_option
                else False,
                create_material_authority_report=material_authority_report_checkbox.isChecked()
                if show_material_authority_report_option
                else False,
                create_active_file_authority_audit=active_file_authority_audit_checkbox.isChecked()
                if show_active_file_authority_audit_option
                else False,
                conflict_mode=str(conflict_mode_combo.currentData() or "") if uses_manager_metadata else "",
                target_language=target_language_edit.text().strip() if uses_manager_metadata else "",
            )
            result[:] = [
                export_root,
                package_info,
                bool(export_options.create_no_encrypt_file),
                bool(include_related_files_checkbox.isChecked()),
                export_options,
            ]
            dialog.accept()

        browse_button.clicked.connect(_browse_export_root)
        cancel_button.clicked.connect(dialog.reject)
        continue_button.clicked.connect(_accept)

        if dialog.exec() != QDialog.Accepted or len(result) != 5:
            return None

        export_root = Path(result[0]).expanduser()
        package_info = result[1] if isinstance(result[1], ModPackageInfo) else initial_package_info
        create_no_encrypt_file = bool(result[2])
        include_related_files = bool(result[3])
        export_options = result[4] if isinstance(result[4], ModPackageExportOptions) else ModPackageExportOptions()

        self.mod_ready_export_root_edit.setText(str(export_root))
        self.mod_ready_package_title_edit.setText(package_info.title)
        self.mod_ready_package_version_edit.setText(package_info.version)
        self.mod_ready_package_author_edit.setText(package_info.author)
        self.mod_ready_package_description_edit.setText(package_info.description)
        self.mod_ready_create_no_encrypt_checkbox.setChecked(create_no_encrypt_file)
        for profile, checkbox in self.mod_ready_profile_checkboxes.items():
            checkbox.setChecked(profile in set(export_options.export_profiles or export_options.manager_targets))
        self.schedule_settings_save()

        return export_root, package_info, create_no_encrypt_file, include_related_files, export_options

    def _collect_archive_mod_ready_export_target(
        self,
        *,
        browse_title: str,
        prompt_for_metadata: bool = False,
        initial_include_related_files: bool = False,
        show_include_related_files_option: bool = False,
        dialog_title: str = "Write Mod-Ready Loose File",
        allow_dmm_texture_structure: bool = True,
        show_texture_resolution_manifest_option: bool = False,
        show_material_authority_report_option: bool = False,
        show_active_file_authority_audit_option: bool = False,
        initial_package_title: str = "",
        initial_package_description: str = "",
        parent: Optional[QWidget] = None,
    ) -> Optional[Tuple[Path, ModPackageInfo, bool, bool, ModPackageExportOptions]]:
        config = self.collect_config()
        export_root_text = str(getattr(config, "mod_ready_export_root", "") or "").strip()
        if export_root_text:
            export_root = Path(export_root_text).expanduser()
        else:
            output_root_text = str(getattr(config, "output_root", "") or "").strip()
            default_root = (
                resolve_default_mod_ready_export_root(Path(output_root_text).expanduser())
                if output_root_text
                else workspace_paths(self.settings_file_path.parent)["mod_ready_export_root"]
            )
            selected_dir = QFileDialog.getExistingDirectory(parent if parent is not None else self, browse_title, str(default_root))
            if not selected_dir:
                return None
            export_root = Path(selected_dir)
        package_info = ModPackageInfo(
            title=str(getattr(config, "mod_ready_package_title", MOD_READY_PACKAGE_TITLE) or "").strip() or MOD_READY_PACKAGE_TITLE,
            version=str(getattr(config, "mod_ready_package_version", MOD_READY_PACKAGE_VERSION) or "").strip() or MOD_READY_PACKAGE_VERSION,
            author=str(getattr(config, "mod_ready_package_author", MOD_READY_PACKAGE_AUTHOR) or "").strip(),
            description=str(getattr(config, "mod_ready_package_description", MOD_READY_PACKAGE_DESCRIPTION) or "").strip(),
            nexus_url=str(getattr(config, "mod_ready_package_nexus_url", MOD_READY_PACKAGE_NEXUS_URL) or "").strip(),
        )
        if str(initial_package_title or "").strip():
            package_info = dataclasses.replace(package_info, title=str(initial_package_title or "").strip())
        if str(initial_package_description or "").strip():
            package_info = dataclasses.replace(package_info, description=str(initial_package_description or "").strip())
        create_no_encrypt_file = bool(getattr(config, "mod_ready_create_no_encrypt_file", True))
        if prompt_for_metadata:
            return self._prompt_archive_mod_ready_export_target(
                browse_title=browse_title,
                initial_export_root=export_root,
                initial_package_info=package_info,
                initial_create_no_encrypt=create_no_encrypt_file,
                initial_include_related_files=initial_include_related_files,
                show_include_related_files_option=show_include_related_files_option,
                dialog_title=dialog_title,
                allow_dmm_texture_structure=allow_dmm_texture_structure,
                show_texture_resolution_manifest_option=show_texture_resolution_manifest_option,
                show_material_authority_report_option=show_material_authority_report_option,
                show_active_file_authority_audit_option=show_active_file_authority_audit_option,
                parent=parent,
            )
        return (
            export_root,
            package_info,
            create_no_encrypt_file,
            False,
            ModPackageExportOptions(create_no_encrypt_file=create_no_encrypt_file),
        )

__all__ = ["ArchiveModReadyExportMixin"]
