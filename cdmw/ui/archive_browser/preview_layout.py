"""Archive preview panel layout builder."""

from __future__ import annotations

from typing import Dict, Optional, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cdmw.ui.archive_browser.actions import archive_context_menu_icons
from cdmw.ui.archive_browser.preview_state import archive_model_preview_refresh_tooltip
from cdmw.ui.preview import DotNetPreviewHostFrame, DotNetPreviewProfile
from cdmw.ui.widgets import (
    ArchiveDetailsEditor,
    CodePreviewEditor,
    FlatSectionPanel,
    MediaPreviewWidget,
    NativePreviewPanel,
    PreviewLabel,
    PreviewScrollArea,
    responsive_sidebar_bounds,
)


class ArchivePreviewLayoutMixin:
    """Build the Archive Preview panel."""

    def _build_archive_preview_panel(self) -> None:
        archive_preview_group = FlatSectionPanel("Preview")
        archive_preview_min, _archive_preview_pref, _archive_preview_max = responsive_sidebar_bounds(self, role="wide")
        self.archive_preview_min_width = archive_preview_min
        archive_preview_group.setMinimumWidth(archive_preview_min)
        self.archive_preview_group = archive_preview_group
        archive_preview_container_layout = archive_preview_group.body_layout
        archive_preview_container_layout.setSpacing(4)
        archive_preview_main_widget = QWidget()
        archive_preview_main_widget.setMinimumWidth(0)
        archive_preview_main_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        archive_preview_main_layout = QVBoxLayout(archive_preview_main_widget)
        archive_preview_main_layout.setContentsMargins(0, 0, 0, 0)
        archive_preview_main_layout.setSpacing(4)

        archive_preview_header = QVBoxLayout()
        archive_preview_header.setSpacing(3)
        archive_preview_title_row = QHBoxLayout()
        archive_preview_title_row.setSpacing(8)
        self.archive_preview_title_label = QLabel("Select an archive file")
        self.archive_preview_title_label.setWordWrap(False)
        self.archive_preview_title_label.setMinimumWidth(0)
        self.archive_preview_title_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.archive_preview_role_badge = QLabel("")
        self.archive_preview_role_badge.setObjectName("WarningBadge")
        self.archive_preview_role_badge.setToolTip("Recovered archive role for the selected file.")
        self.archive_preview_role_badge.setVisible(False)
        self.archive_preview_warning_badge = QLabel("")
        self.archive_preview_warning_badge.setObjectName("WarningBadge")
        self.archive_preview_warning_badge.setVisible(False)
        self.archive_preview_loose_toggle_button = QPushButton("Loose File")
        self.archive_preview_loose_toggle_button.setToolTip("Switch between the archive preview and the matching loose file preview.")
        self.archive_preview_loose_toggle_button.setVisible(False)
        self.archive_preview_loose_toggle_button.setMinimumWidth(86)
        self.archive_preview_loose_toggle_button.setMinimumHeight(24)
        self.archive_preview_loose_toggle_button.setMaximumHeight(28)
        self.archive_preview_loose_toggle_button.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.archive_preview_zoom_out_button = QPushButton("-")
        self.archive_preview_zoom_out_button.setToolTip("Zoom out.")
        self.archive_preview_zoom_fit_button = QPushButton("Fit")
        self.archive_preview_zoom_fit_button.setToolTip("Fit the preview to the available space.")
        self.archive_preview_zoom_100_button = QPushButton("100%")
        self.archive_preview_zoom_100_button.setToolTip("Show the preview at 100% zoom.")
        self.archive_preview_zoom_in_button = QPushButton("+")
        self.archive_preview_zoom_in_button.setToolTip("Zoom in.")
        self.archive_preview_zoom_value = QLabel("Fit")
        self.archive_preview_zoom_value.setObjectName("HintLabel")
        self.archive_model_preview_flip_v_checkbox = QCheckBox("Flip V")
        self.archive_model_preview_flip_v_checkbox.setToolTip(
            "Temporarily invert the preview texture V direction for this model preview only."
        )
        self.archive_model_preview_flip_v_checkbox.setVisible(False)
        self.archive_model_preview_disable_support_checkbox = QCheckBox("No Support Maps")
        self.archive_model_preview_disable_support_checkbox.setToolTip(
            "Temporarily ignore normal, material, and height support textures for this preview."
        )
        self.archive_model_preview_disable_support_checkbox.setVisible(False)
        self.archive_model_preview_refresh_button = QPushButton("Refresh")
        self.archive_model_preview_refresh_button.setToolTip(archive_model_preview_refresh_tooltip())
        self.archive_isolated_renderer_button = QPushButton("Reload .NET/Vortice")
        self.archive_isolated_renderer_button.setToolTip(
            "Rebuild and reload the active native Direct3D 11 preview package."
        )
        self.archive_isolated_renderer_button.setEnabled(False)
        self.archive_isolated_renderer_button.setVisible(False)
        self.archive_d3d11_part_visibility_button = QToolButton()
        self.archive_d3d11_part_visibility_button.setObjectName("ArchivePartVisibilityButton")
        self.archive_d3d11_part_visibility_button.setText("Parts")
        self.archive_d3d11_part_visibility_button.setPopupMode(QToolButton.InstantPopup)
        self.archive_d3d11_part_visibility_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.archive_d3d11_part_visibility_button.setToolTip(
            "Show or hide base parts. Prefab components are packaged only after you enable them."
        )
        self.archive_d3d11_part_visibility_button.setEnabled(False)
        self.archive_d3d11_part_visibility_button.setVisible(False)
        self.archive_d3d11_part_visibility_menu = QMenu(self.archive_d3d11_part_visibility_button)
        self.archive_d3d11_part_visibility_menu.setObjectName("ArchivePartVisibilityMenu")
        if hasattr(self.archive_d3d11_part_visibility_menu, "setToolTipsVisible"):
            self.archive_d3d11_part_visibility_menu.setToolTipsVisible(True)
        self.archive_d3d11_part_visibility_button.setMenu(self.archive_d3d11_part_visibility_menu)
        self.archive_d3d11_part_visibility_actions: Dict[int, object] = {}
        self.archive_d3d11_part_visibility_groups: Dict[
            str,
            Tuple[object, Tuple[int, ...], bool, str],
        ] = {}
        self.archive_d3d11_prefab_component_selections: Dict[str, set[str]] = {}
        self.archive_d3d11_part_visibility_bulk_update = False
        self.archive_model_preview_reset_overrides_button = QPushButton("Reset")
        self.archive_model_preview_reset_overrides_button.setToolTip(
            "Clear the temporary Flip Base V and Disable Support Maps preview overrides."
        )
        self.archive_model_preview_reset_overrides_button.setVisible(False)
        self.archive_model_preview_settings_button = QPushButton("Preview Settings")
        self.archive_model_preview_settings_button.setToolTip(
            "Open preview controls for textures, quality, orbit, pan, and inversion."
        )
        self.archive_model_preview_settings_button.setMinimumWidth(142)
        self.archive_model_preview_settings_button.setMaximumWidth(180)
        self.archive_model_preview_settings_button.setMinimumHeight(24)
        self.archive_model_preview_settings_button.setMaximumHeight(28)
        self.archive_model_preview_settings_button.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.archive_asset_family_button = QPushButton("Asset Family")
        self.archive_asset_family_button.setToolTip(
            "Open the recovered file family for this selection: model, material, textures, HKX, meshinfo, prefab, rig, and animation links."
        )
        self.archive_asset_family_button.setMinimumWidth(110)
        self.archive_asset_family_button.setMaximumWidth(150)
        self.archive_asset_family_button.setMinimumHeight(24)
        self.archive_asset_family_button.setMaximumHeight(28)
        self.archive_asset_family_button.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.archive_asset_family_button.setVisible(False)
        self.archive_asset_family_button.setEnabled(False)
        self.archive_appearance_composite_button = QPushButton("Composite Preview...")
        self.archive_appearance_composite_button.setToolTip(
            "Preview a read-only composite from app XML sections or prefab/socket model evidence."
        )
        self.archive_appearance_composite_button.setEnabled(False)
        self.archive_appearance_swap_button = QPushButton("Armor Swap...")
        self.archive_appearance_swap_button.setToolTip(
            "Build a loose single-PAC appearance armor swap package from one target body app XML and one donor model."
        )
        self.archive_appearance_swap_button.setEnabled(False)
        self.archive_action_preview_button = QPushButton("Preview")
        self.archive_action_preview_button.setToolTip("Render the selected archive file in Archive Preview.")
        self.archive_action_preview_button.setEnabled(False)
        self.archive_action_open_preview_window_button = QPushButton("Open Preview Window...")
        self.archive_action_open_preview_window_button.setToolTip("Open the selected archive file in a separate preview window.")
        self.archive_action_open_preview_window_button.setEnabled(False)
        self.archive_action_copy_filename_button = QPushButton("Copy Filename")
        self.archive_action_copy_filename_button.setToolTip("Copy only the archive file name, without folders.")
        self.archive_action_copy_filename_button.setEnabled(False)
        self.archive_action_export_file_button = QPushButton("Export File...")
        self.archive_action_export_file_button.setToolTip("Export the selected archive file bytes to a chosen location.")
        self.archive_action_export_file_button.setEnabled(False)
        self.archive_action_extract_file_button = QPushButton("Extract File...")
        self.archive_action_extract_file_button.setToolTip("Extract the selected archive file through the Archive Extract workflow.")
        self.archive_action_extract_file_button.setEnabled(False)
        self.archive_action_show_only_file_button = QPushButton("Show Only This File")
        self.archive_action_show_only_file_button.setToolTip("Scope the Archive Browser to only the selected file.")
        self.archive_action_show_only_file_button.setEnabled(False)
        self.archive_action_asset_family_button = QPushButton("Asset Family...")
        self.archive_action_asset_family_button.setToolTip(
            "Open the recovered asset family for the selected archive file."
        )
        self.archive_action_asset_family_button.setEnabled(False)
        self.archive_action_filter_to_family_button = QPushButton("Filter to Family")
        self.archive_action_filter_to_family_button.setToolTip(
            "Filter Archive Files to the required/recommended files in this Asset Family."
        )
        self.archive_action_filter_to_family_button.setEnabled(False)
        self.archive_action_export_family_button = QPushButton("Export Family...")
        self.archive_action_export_family_button.setToolTip("Export the resolved files in the selected asset family.")
        self.archive_action_export_family_button.setEnabled(False)
        self.archive_action_source_mix_button = QPushButton("Build Loose Package From Sources...")
        self.archive_action_source_mix_button.setToolTip(
            "Build a loose package by matching source files to the selected archive target family."
        )
        self.archive_action_source_mix_button.setEnabled(False)
        self.archive_action_character_dependency_button = QPushButton("Export Character Dependency Package...")
        self.archive_action_character_dependency_button.setToolTip(
            "Collect the selected body/model with its strict appearance, prefab, material, texture, skeleton, physics, and motion dependencies."
        )
        self.archive_action_character_dependency_button.setEnabled(False)
        self.archive_model_export_obj_button = QPushButton("Export OBJ...")
        self.archive_model_export_obj_button.setToolTip(
            "Export the selected archive mesh as Wavefront OBJ with MTL and resolved preview textures for Blender."
        )
        self.archive_model_export_obj_button.setEnabled(False)
        self.archive_model_export_fbx_button = QPushButton("Export FBX...")
        self.archive_model_export_fbx_button.setToolTip(
            "Export the selected archive mesh as FBX. PAC exports also try to attach the matching PAB skeleton."
        )
        self.archive_model_export_fbx_button.setEnabled(False)
        self.archive_model_import_preview_button = QPushButton("Import Mesh Preview...")
        self.archive_model_import_preview_button.setToolTip(
            "Rebuild the selected archive mesh from OBJ, DAE, glTF, or GLB and show the result in the preview without patching the game files."
        )
        self.archive_model_import_preview_button.setEnabled(False)
        self.archive_model_import_dds_preview_button = QPushButton("Import DDS Preview...")
        self.archive_model_import_dds_preview_button.setToolTip(
            "Apply one local DDS onto the current archive mesh preview as a temporary import preview without patching the game files."
        )
        self.archive_model_import_dds_preview_button.setEnabled(False)
        self.archive_model_import_patch_button = QPushButton("Import Mesh...")
        self.archive_model_import_patch_button.setToolTip(
            "Rebuild the selected archive mesh from OBJ, DAE, glTF, or GLB, then choose whether to patch the game archives or write a mod-ready loose file."
        )
        self.archive_model_import_patch_button.setEnabled(False)
        self.archive_model_modify_original_button = QPushButton("Modify Original...")
        self.archive_model_modify_original_button.setToolTip(
            "Create a temporary editable clone from the selected archive mesh, then import the edited OBJ clone through Mesh Replacement Geometry."
        )
        self.archive_model_modify_original_button.setEnabled(False)
        self.archive_model_swap_in_game_button = QPushButton("Swap With In-Game Mesh...")
        self.archive_model_swap_in_game_button.setToolTip(
            "Use another loaded archive mesh as the replacement source, then open Mesh Replacement Alignment for this target."
        )
        self.archive_model_swap_in_game_button.setEnabled(False)
        self.archive_hkx_export_json_button = QPushButton("Export HKX JSON...")
        self.archive_hkx_export_json_button.setToolTip(
            "Export a documented editable JSON patch for decoded Crimson Desert HKX geometry."
        )
        self.archive_hkx_export_json_button.setEnabled(False)
        self.archive_hkx_import_json_button = QPushButton("Import HKX JSON...")
        self.archive_hkx_import_json_button.setToolTip(
            "Apply fixed-size numeric edits from an exported HKX JSON patch and write a mod-ready loose HKX package."
        )
        self.archive_hkx_import_json_button.setEnabled(False)
        self.archive_hkx_export_xml_button = QPushButton("Export HKX XML...")
        self.archive_hkx_export_xml_button.setToolTip(
            "Export a documented CDMW XML patch for decoded Crimson Desert HKX geometry. This is not official Havok XML yet."
        )
        self.archive_hkx_export_xml_button.setEnabled(False)
        self.archive_hkx_export_havok_xml_view_button = QPushButton("Export Havok XML View...")
        self.archive_hkx_export_havok_xml_view_button.setToolTip(
            "Export a read-only hkpackfile/hkobject/hkparam XML view for browsing and comparison with legacy Havok XML tools."
        )
        self.archive_hkx_export_havok_xml_view_button.setEnabled(False)
        self.archive_hkx_import_xml_button = QPushButton("Import HKX XML...")
        self.archive_hkx_import_xml_button.setToolTip(
            "Apply fixed-size numeric edits from a CDMW HKX XML patch and write a mod-ready loose HKX package."
        )
        self.archive_hkx_import_xml_button.setEnabled(False)
        self.archive_hkx_edit_button = QPushButton("Edit HKX...")
        self.archive_hkx_edit_button.setToolTip(
            "Open a documented editable HKX XML patch in-app, then write supported edits as a mod-ready loose HKX package."
        )
        self.archive_hkx_edit_button.setEnabled(False)
        self.archive_hkx_placement_button = QPushButton("Edit HKX...")
        self.archive_hkx_placement_button.setToolTip(
            "Edit the selected HKX/HKT, or a related HKX/HKT found from the selected model family, directly on the Placement view."
        )
        self.archive_hkx_placement_button.setEnabled(False)
        self.archive_hkx_corpus_button = QPushButton("Scan HKX Corpus...")
        self.archive_hkx_corpus_button.setToolTip(
            "Scan a local folder of extracted Crimson Desert .hkx files and export a converter coverage report as JSON or CSV."
        )
        self.archive_sidecar_export_json_button = QPushButton("Export Sidecar JSON...")
        self.archive_sidecar_export_json_button.setToolTip(
            "Export an experimental read-only JSON decode document for structured metadata, animation, and sequence-texture binaries such as .meshinfo, .motionblending, .paa, .paa_metabin, .prefab, .pappt, .pamhc, or .seqmt."
        )
        self.archive_sidecar_export_json_button.setEnabled(False)
        self.archive_sidecar_inspect_button = QPushButton("Inspect Sidecar...")
        self.archive_sidecar_inspect_button.setToolTip(
            "Inspect structured metadata/animation binaries in-app. Editing stays disabled until the binary schema is proven safe."
        )
        self.archive_sidecar_inspect_button.setEnabled(False)
        self.archive_sidecar_corpus_button = QPushButton("Scan Sidecar Corpus...")
        self.archive_sidecar_corpus_button.setToolTip(
            "Scan loose .meshinfo, .motionblending, .paa_metabin, .prefab, .pappt, .pamhc, and .seqmt files and export a read-only schema/layout ranking report."
        )
        self.archive_weapon_placement_studio_button = QPushButton("Weapon Placement Studio")
        self.archive_weapon_placement_studio_button.setToolTip(
            "Disabled - WIP. Weapon Placement Studio is paused until the preview/export flow is ready again."
        )
        self.archive_weapon_placement_studio_button.setEnabled(False)
        self.archive_material_values_button = QPushButton("Edit Material Values...")
        self.archive_material_values_button.setToolTip(
            "Read recognized values from a companion .pac_xml/.pam_xml/.pamlod_xml/.pami material sidecar and export edited values as a mod-ready package."
        )
        self.archive_material_values_button.setEnabled(False)
        self.archive_restore_patch_backup_button = QPushButton("Restore Backup...")
        self.archive_restore_patch_backup_button.setToolTip(
            "Restore a previously created archive patch backup."
        )
        self.archive_import_loose_mod_button = QPushButton("Import Loose Mod Folder...")
        self.archive_import_loose_mod_button.setToolTip(
            "Load a whole loose mod folder, match files by virtual path, review asset families, and write selected replacements as one loose package."
        )
        self.archive_model_action_menu_groups = []
        archive_action_menu_icons = archive_context_menu_icons()

        def _make_archive_action_menu_button(
            title: str,
            items: Sequence[Tuple[Optional[str], QPushButton]],
        ) -> QToolButton:
            button = QToolButton()
            button.setObjectName("ArchiveActionMenuButton")
            button.setText(title)
            button.setPopupMode(QToolButton.InstantPopup)
            button.setToolButtonStyle(Qt.ToolButtonTextOnly)
            button.setMinimumWidth(86)
            button.setMinimumHeight(24)
            button.setMaximumHeight(26)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            menu = QMenu(button)
            menu.setObjectName("ArchiveActionMenu")
            if hasattr(menu, "setToolTipsVisible"):
                menu.setToolTipsVisible(True)
            action_pairs = []
            for label, source_button in items:
                action_text = self._archive_action_menu_text(source_button, label, source_button.isEnabled())
                action = menu.addAction(action_text)
                action.setToolTip(source_button.toolTip())
                action.setStatusTip(source_button.toolTip())
                action.setWhatsThis(source_button.toolTip())
                action.setEnabled(source_button.isEnabled())
                action.triggered.connect(lambda _checked=False, target=source_button: target.click())
                action_pairs.append((action, source_button, label))
            button.setMenu(menu)
            button.setEnabled(any(source_button.isEnabled() for _label, source_button in items))
            self.archive_model_action_menu_groups.append((button, title, action_pairs))
            return button

        def _make_sectioned_archive_action_menu_button(
            title: str,
            sections: Sequence[Tuple[str, str, Sequence[Tuple[Optional[str], QPushButton]]]],
        ) -> QToolButton:
            button = QToolButton()
            button.setObjectName("ArchiveActionMenuButton")
            button.setText(title)
            button.setPopupMode(QToolButton.InstantPopup)
            button.setToolButtonStyle(Qt.ToolButtonTextOnly)
            button.setMinimumWidth(86)
            button.setMinimumHeight(24)
            button.setMaximumHeight(26)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            menu = QMenu(button)
            menu.setObjectName("ArchiveActionMenu")
            if hasattr(menu, "setToolTipsVisible"):
                menu.setToolTipsVisible(True)
            action_pairs = []
            for kind, section_label, items in sections:
                icon = archive_action_menu_icons.get(kind)
                if icon is None:
                    menu.addSection(section_label)
                else:
                    menu.addSection(icon, section_label)
                for label, source_button in items:
                    action_text = self._archive_action_menu_text(source_button, label, source_button.isEnabled())
                    action = menu.addAction(icon, action_text) if icon is not None else menu.addAction(action_text)
                    action.setToolTip(source_button.toolTip())
                    action.setStatusTip(source_button.toolTip())
                    action.setWhatsThis(source_button.toolTip())
                    action.setEnabled(source_button.isEnabled())
                    action.triggered.connect(lambda _checked=False, target=source_button: target.click())
                    action_pairs.append((action, source_button, label))
            button.setMenu(menu)
            button.setEnabled(any(source_button.isEnabled() for _action, source_button, _label in action_pairs))
            self.archive_model_action_menu_groups.append((button, title, action_pairs))
            return button

        self.archive_export_menu_button = _make_archive_action_menu_button(
            "Export",
            (
                ("Export File", self.archive_action_export_file_button),
                ("Extract File", self.archive_action_extract_file_button),
                ("Export OBJ", self.archive_model_export_obj_button),
                ("Export FBX", self.archive_model_export_fbx_button),
                ("Export Family", self.archive_action_export_family_button),
                ("Export Character Dependency Package", self.archive_action_character_dependency_button),
                ("Export Sidecar JSON", self.archive_sidecar_export_json_button),
                ("Export HKX JSON", self.archive_hkx_export_json_button),
                ("Export HKX XML", self.archive_hkx_export_xml_button),
                ("Export Havok XML View", self.archive_hkx_export_havok_xml_view_button),
            ),
        )
        self.archive_import_menu_button = _make_archive_action_menu_button(
            "Import",
            (
                ("Import Loose Mod Folder", self.archive_import_loose_mod_button),
                ("Preview Mesh Import", self.archive_model_import_preview_button),
                ("Import Mesh", self.archive_model_import_patch_button),
                ("Preview DDS on Mesh", self.archive_model_import_dds_preview_button),
                ("Import HKX JSON", self.archive_hkx_import_json_button),
                ("Import HKX XML", self.archive_hkx_import_xml_button),
            ),
        )
        self.archive_tools_menu_button = _make_sectioned_archive_action_menu_button(
            "Tools",
            (
                (
                    "view",
                    "View + Inspect",
                    (
                        ("Preview", self.archive_action_preview_button),
                        ("Open Preview Window", self.archive_action_open_preview_window_button),
                        ("Copy Filename", self.archive_action_copy_filename_button),
                    ),
                ),
                (
                    "family",
                    "Asset Family",
                    (
                        ("Asset Family", self.archive_action_asset_family_button),
                        ("Filter to Family", self.archive_action_filter_to_family_button),
                    ),
                ),
                (
                    "workflow",
                    "Source Package",
                    (("Build Loose Package From Sources", self.archive_action_source_mix_button),),
                ),
                (
                    "mesh",
                    "Mesh Edit",
                    (
                        ("Modify Original Mesh", self.archive_model_modify_original_button),
                        (None, self.archive_model_swap_in_game_button),
                    ),
                ),
                (
                    "physics",
                    "Physics / HKX",
                    (
                        ("Edit HKX", self.archive_hkx_placement_button),
                        ("Edit Selected HKX", self.archive_hkx_edit_button),
                        ("Scan HKX Corpus", self.archive_hkx_corpus_button),
                    ),
                ),
                (
                    "data",
                    "Structured Data",
                    (
                        ("Inspect Selected Sidecar", self.archive_sidecar_inspect_button),
                        ("Scan Sidecar Corpus", self.archive_sidecar_corpus_button),
                    ),
                ),
                (
                    "texture",
                    "Material",
                    (("Edit Material Values", self.archive_material_values_button),),
                ),
                (
                    "maintenance",
                    "Maintenance",
                    (
                        ("Restore Backup", self.archive_restore_patch_backup_button),
                        (None, self.archive_weapon_placement_studio_button),
                    ),
                ),
            ),
        )
        archive_preview_title_row.addWidget(self.archive_preview_title_label, stretch=1)
        archive_preview_title_row.addWidget(self.archive_preview_role_badge)
        archive_preview_title_row.addWidget(self.archive_preview_warning_badge)
        archive_preview_title_row.addWidget(self.archive_preview_loose_toggle_button)
        archive_preview_title_row.addWidget(self.archive_asset_family_button)
        archive_preview_title_row.addWidget(self.archive_model_preview_settings_button)

        archive_preview_toolbar = QWidget()
        archive_preview_toolbar.setMinimumWidth(0)
        archive_preview_toolbar.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        archive_preview_toolbar_layout = QVBoxLayout(archive_preview_toolbar)
        archive_preview_toolbar_layout.setContentsMargins(0, 0, 0, 0)
        archive_preview_toolbar_layout.setSpacing(4)
        archive_view_controls_layout = QHBoxLayout()
        archive_view_controls_layout.setContentsMargins(0, 0, 0, 0)
        archive_view_controls_layout.setSpacing(6)
        for button, width in (
            (self.archive_preview_zoom_out_button, 30),
            (self.archive_preview_zoom_fit_button, 42),
            (self.archive_preview_zoom_100_button, 52),
            (self.archive_preview_zoom_in_button, 30),
            (self.archive_model_preview_refresh_button, 72),
            (self.archive_isolated_renderer_button, 136),
        ):
            button.setMinimumWidth(width)
            button.setMinimumHeight(24)
            button.setMaximumHeight(26)
            button.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.archive_preview_zoom_value.setAlignment(Qt.AlignCenter)
        self.archive_preview_zoom_value.setFrameShape(QFrame.StyledPanel)
        self.archive_preview_zoom_value.setMinimumWidth(52)
        self.archive_preview_zoom_value.setMaximumWidth(62)
        self.archive_preview_zoom_value.setMinimumHeight(24)
        self.archive_preview_zoom_value.setMaximumHeight(26)
        self.archive_preview_zoom_value.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.archive_preview_zoom_value.setToolTip("Current preview zoom.")
        self.archive_model_preview_flip_v_checkbox.setMinimumWidth(66)
        self.archive_model_preview_flip_v_checkbox.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.archive_model_preview_disable_support_checkbox.setMinimumWidth(126)
        self.archive_model_preview_disable_support_checkbox.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.archive_model_preview_reset_overrides_button.setMinimumWidth(62)
        self.archive_model_preview_reset_overrides_button.setMinimumHeight(24)
        self.archive_model_preview_reset_overrides_button.setMaximumHeight(26)
        self.archive_model_preview_reset_overrides_button.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.archive_d3d11_part_visibility_button.setMinimumWidth(74)
        self.archive_d3d11_part_visibility_button.setMinimumHeight(24)
        self.archive_d3d11_part_visibility_button.setMaximumHeight(26)
        self.archive_d3d11_part_visibility_button.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        archive_view_controls_layout.addWidget(self.archive_preview_zoom_out_button)
        archive_view_controls_layout.addWidget(self.archive_preview_zoom_fit_button)
        archive_view_controls_layout.addWidget(self.archive_preview_zoom_100_button)
        archive_view_controls_layout.addWidget(self.archive_preview_zoom_in_button)
        archive_view_controls_layout.addWidget(self.archive_preview_zoom_value)
        archive_view_controls_layout.addSpacing(8)
        archive_view_controls_layout.addWidget(self.archive_model_preview_refresh_button)
        archive_view_controls_layout.addWidget(self.archive_isolated_renderer_button)
        archive_view_controls_layout.addWidget(self.archive_d3d11_part_visibility_button)
        archive_view_controls_layout.addWidget(self.archive_model_preview_reset_overrides_button)
        archive_view_controls_layout.addWidget(self.archive_model_preview_flip_v_checkbox)
        archive_view_controls_layout.addWidget(self.archive_model_preview_disable_support_checkbox)
        archive_view_controls_layout.addStretch(1)
        for button in (
            self.archive_model_export_obj_button,
            self.archive_model_export_fbx_button,
            self.archive_action_preview_button,
            self.archive_action_open_preview_window_button,
            self.archive_action_copy_filename_button,
            self.archive_action_export_file_button,
            self.archive_action_extract_file_button,
            self.archive_action_show_only_file_button,
            self.archive_action_asset_family_button,
            self.archive_action_filter_to_family_button,
            self.archive_action_export_family_button,
            self.archive_action_source_mix_button,
            self.archive_action_character_dependency_button,
            self.archive_model_import_preview_button,
            self.archive_model_import_dds_preview_button,
            self.archive_model_import_patch_button,
            self.archive_model_modify_original_button,
            self.archive_model_swap_in_game_button,
            self.archive_appearance_composite_button,
            self.archive_appearance_swap_button,
            self.archive_hkx_export_json_button,
            self.archive_hkx_import_json_button,
            self.archive_hkx_export_xml_button,
            self.archive_hkx_export_havok_xml_view_button,
            self.archive_hkx_import_xml_button,
            self.archive_hkx_edit_button,
            self.archive_hkx_placement_button,
            self.archive_hkx_corpus_button,
            self.archive_weapon_placement_studio_button,
            self.archive_sidecar_export_json_button,
            self.archive_sidecar_inspect_button,
            self.archive_sidecar_corpus_button,
            self.archive_restore_patch_backup_button,
            self.archive_material_values_button,
            self.archive_import_loose_mod_button,
        ):
            button.setMinimumWidth(0)
            button.setMinimumHeight(23)
            button.setMaximumHeight(28)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        archive_model_actions_layout = QHBoxLayout()
        archive_model_actions_layout.setContentsMargins(0, 0, 0, 0)
        archive_model_actions_layout.setSpacing(6)
        archive_model_action_menus = (
            self.archive_export_menu_button,
            self.archive_import_menu_button,
            self.archive_tools_menu_button,
        )
        for button in archive_model_action_menus:
            archive_model_actions_layout.addWidget(button)
        archive_preview_toolbar_layout.addLayout(archive_view_controls_layout)
        archive_preview_toolbar_layout.addLayout(archive_model_actions_layout)
        archive_preview_header.addLayout(archive_preview_title_row)
        archive_preview_header.addWidget(archive_preview_toolbar)
        archive_preview_main_layout.addLayout(archive_preview_header)

        self.archive_preview_meta_label = QLabel("Select an archive file to preview it here.")
        self.archive_preview_meta_label.setObjectName("HintLabel")
        self.archive_preview_meta_label.setWordWrap(True)
        archive_preview_main_layout.addWidget(self.archive_preview_meta_label)
        self.archive_preview_health_label = QLabel("")
        self.archive_preview_health_label.setObjectName("ArchivePreviewHealthLabel")
        self.archive_preview_health_label.setProperty("attention", False)
        self.archive_preview_health_label.setWordWrap(True)
        self.archive_preview_health_label.setVisible(False)
        archive_preview_main_layout.addWidget(self.archive_preview_health_label)
        self.archive_preview_warning_label = QLabel("")
        self.archive_preview_warning_label.setObjectName("WarningText")
        self.archive_preview_warning_label.setWordWrap(True)
        self.archive_preview_warning_label.setVisible(False)
        archive_preview_main_layout.addWidget(self.archive_preview_warning_label)
        self._build_archive_texture_references_panel()

        self.archive_preview_stack = QStackedWidget()
        self.archive_preview_label = PreviewLabel("Select an archive file to preview it here.")
        self.archive_preview_scroll = PreviewScrollArea()
        self.archive_preview_scroll.setWidgetResizable(False)
        self.archive_preview_scroll.setAlignment(Qt.AlignCenter)
        self.archive_preview_scroll.setWidget(self.archive_preview_label)
        self.archive_preview_label.attach_scroll_area(self.archive_preview_scroll)
        self.archive_preview_label.set_wheel_zoom_handler(self._adjust_archive_preview_zoom)
        self.archive_model_preview = NativePreviewPanel(
            "Select an archive file to preview it here.",
            theme_key=self.current_theme_key,
        )
        self.archive_model_preview.view_state_changed.connect(self._handle_archive_model_view_state_changed)
        self.archive_model_preview.debug_details_changed.connect(self._refresh_archive_preview_details_text)
        self.archive_model_preview.setVisible(False)
        self.archive_d3d11_preview_host = DotNetPreviewHostFrame(
            profile=DotNetPreviewProfile.PREVIEW,
            terminate_on_close=False,
        )
        self.archive_d3d11_preview_host.setObjectName("DotNetVorticePreviewHost")
        self.archive_d3d11_preview_host.setAttribute(Qt.WA_NativeWindow, True)
        self.archive_d3d11_preview_host.setMinimumHeight(260)
        self.archive_d3d11_preview_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.archive_d3d11_preview_host.view_state_changed.connect(self._handle_archive_model_view_state_changed)
        self.archive_d3d11_preview_host.view_state_payload_changed.connect(self._handle_archive_d3d11_view_state_payload)
        self.archive_d3d11_preview_status_label = QLabel(".NET/Vortice Preview")
        self.archive_d3d11_preview_status_label.setObjectName("HintLabel")
        self.archive_d3d11_preview_status_label.setAlignment(Qt.AlignCenter)
        self.archive_d3d11_preview_status_label.setVisible(False)
        self.archive_media_preview = MediaPreviewWidget(
            "Select an archive file to preview it here.",
            theme_key=self.current_theme_key,
        )
        self.archive_preview_text_edit = CodePreviewEditor(theme_key=self.current_theme_key)
        self.archive_preview_text_edit.document().setMaximumBlockCount(5000)
        self.archive_preview_info_edit = ArchiveDetailsEditor(theme_key=self.current_theme_key)
        self.archive_preview_info_edit.document().setMaximumBlockCount(2000)
        self.archive_preview_text_tools = self._build_archive_text_tools(self.archive_preview_text_edit)
        self.archive_preview_info_tools = self._build_archive_text_tools(self.archive_preview_info_edit)
        self.archive_preview_stack.addWidget(self.archive_preview_scroll)
        self.archive_preview_stack.addWidget(self.archive_d3d11_preview_host)
        self.archive_preview_stack.addWidget(self.archive_media_preview)
        self.archive_preview_stack.addWidget(self.archive_preview_text_edit)
        self.archive_preview_stack.addWidget(self.archive_preview_info_edit)
        self.archive_preview_details_edit = ArchiveDetailsEditor(theme_key=self.current_theme_key)
        self.archive_preview_details_edit.document().setMaximumBlockCount(2000)
        self._archive_preview_base_detail_text = ""
        self.archive_preview_tabs = QTabWidget()
        archive_preview_tab = QWidget()
        archive_preview_tab_layout = QVBoxLayout(archive_preview_tab)
        archive_preview_tab_layout.setContentsMargins(0, 0, 0, 0)
        archive_preview_tab_layout.setSpacing(6)
        self.archive_preview_controls_hint_label = QLabel(
            "Controls: left-drag orbit | middle/right-drag pan | Shift+left-drag pan | mouse wheel zoom | Fit resets view."
        )
        self.archive_preview_controls_hint_label.setObjectName("HintLabel")
        self.archive_preview_controls_hint_label.setWordWrap(True)
        self.archive_preview_controls_hint_label.setToolTip(
            "These controls move the preview camera/view only. Mesh placement and exported transforms are changed in edit/alignment tools."
        )
        archive_preview_tab_layout.addWidget(self.archive_preview_stack)
        archive_preview_tab_layout.addWidget(self.archive_preview_controls_hint_label)
        archive_preview_tab_layout.addWidget(self.archive_preview_text_tools)
        archive_preview_tab_layout.addWidget(self.archive_preview_info_tools)
        archive_details_tab = QWidget()
        archive_details_tab_layout = QVBoxLayout(archive_details_tab)
        archive_details_tab_layout.setContentsMargins(0, 0, 0, 0)
        archive_details_tab_layout.setSpacing(6)
        archive_details_tab_layout.addWidget(self.archive_preview_details_edit)
        self.archive_preview_tabs.addTab(archive_preview_tab, "Preview")
        self.archive_preview_tabs.addTab(archive_details_tab, "Details")
        self.archive_preview_stack.currentChanged.connect(self._update_archive_preview_text_tools_visibility)
        self._update_archive_preview_text_tools_visibility()
        archive_preview_main_layout.addWidget(self.archive_preview_tabs, stretch=1)
        self.archive_preview_content_splitter = QSplitter(Qt.Horizontal)
        self.archive_preview_content_splitter.setChildrenCollapsible(True)
        self.archive_preview_content_splitter.setHandleWidth(8)
        self.archive_preview_content_splitter.addWidget(archive_preview_main_widget)
        self.archive_preview_content_splitter.addWidget(self.archive_texture_refs_group)
        self.archive_preview_content_splitter.setCollapsible(0, False)
        self.archive_preview_content_splitter.setCollapsible(1, True)
        self.archive_preview_content_splitter.setStretchFactor(0, 1)
        self.archive_preview_content_splitter.setStretchFactor(1, 1)
        self.archive_preview_content_splitter.setSizes([920, 600])
        archive_preview_container_layout.addWidget(self.archive_preview_content_splitter, stretch=1)
        self.archive_splitter.addWidget(archive_preview_group)
