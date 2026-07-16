"""Upscaling backend and mod-package setup panel construction."""

from __future__ import annotations

from collections.abc import Callable
from typing import Dict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from cdmw.constants import (
    MOD_READY_PACKAGE_TITLE,
    MOD_READY_PACKAGE_VERSION,
    UPSCALE_BACKEND_CHAINNER,
    UPSCALE_BACKEND_NONE,
    UPSCALE_BACKEND_REALESRGAN_NCNN,
    UPSCALE_POST_CORRECTION_MATCH_HISTOGRAM,
    UPSCALE_POST_CORRECTION_MATCH_LEVELS,
    UPSCALE_POST_CORRECTION_MATCH_MEAN_LUMA,
    UPSCALE_POST_CORRECTION_NONE,
    UPSCALE_POST_CORRECTION_SOURCE_MATCH_BALANCED,
    UPSCALE_POST_CORRECTION_SOURCE_MATCH_EXPERIMENTAL,
    UPSCALE_POST_CORRECTION_SOURCE_MATCH_EXTENDED,
    UPSCALE_TEXTURE_PRESET_ALL,
    UPSCALE_TEXTURE_PRESET_BALANCED,
    UPSCALE_TEXTURE_PRESET_COLOR_UI,
    UPSCALE_TEXTURE_PRESET_COLOR_UI_EMISSIVE,
)
from cdmw.domain.packages.export_policy import (
    MOD_PACKAGE_MANAGER_PROFILES,
    MOD_PACKAGE_MANAGER_PROFILE_LABELS,
    MOD_PACKAGE_METADATA_ARTIFACTS_BY_KEY,
    mod_package_export_options_for_manager,
)
from cdmw.ui.shell.help_widgets import make_help_button
from cdmw.ui.shell.texture_panel_persistence import finish_texture_workflow_panel_body
from cdmw.ui.widgets import CollapsibleSection


class TextureWorkflowUpscaleBackendPanelMixin:
    """Build backend, texture policy, and mod-package controls."""
    def _build_upscale_backend_section(
        self,
        pump_startup_splash: Callable[[str], None],
        *,
        expanded: bool = False,
    ) -> CollapsibleSection:
        self.chainner_section = CollapsibleSection(
            "Upscaling",
            body_builder=lambda body_layout: TextureWorkflowUpscaleBackendPanelMixin._build_upscale_backend_body(
                self,
                body_layout,
                pump_startup_splash,
            ),
        )
        self.chainner_section.set_expanded(expanded)
        return self.chainner_section

    def _build_upscale_backend_body(
        self,
        body_layout: QVBoxLayout,
        pump_startup_splash: Callable[[str], None],
    ) -> None:
        upscale_group = QWidget()
        upscale_layout = QVBoxLayout(upscale_group)
        upscale_layout.setContentsMargins(0, 0, 0, 0)
        upscale_layout.setSpacing(8)
        pump_startup_splash("Preparing processing controls...")

        TextureWorkflowUpscaleBackendPanelMixin._build_upscale_backend_selector(self, upscale_layout)

        TextureWorkflowUpscaleBackendPanelMixin._build_chainner_backend_page(self)

        TextureWorkflowUpscaleBackendPanelMixin._build_upscale_policy_controls(self)

        TextureWorkflowUpscaleBackendPanelMixin._build_upscale_policy_layout(self, upscale_layout)

        body_layout.addWidget(upscale_group)
        finish_texture_workflow_panel_body(self, "chainner")


    def _build_upscale_backend_selector(self, upscale_layout: QVBoxLayout) -> None:
        upscale_backend_grid = QGridLayout()
        upscale_backend_grid.setHorizontalSpacing(10)
        upscale_backend_grid.setVerticalSpacing(8)
        upscale_backend_grid.setColumnMinimumWidth(0, 136)
        upscale_backend_grid.setColumnStretch(1, 1)
        self.upscale_backend_combo = QComboBox()
        self._add_combo_choice(self.upscale_backend_combo, "Disabled", UPSCALE_BACKEND_NONE)
        self._add_combo_choice(self.upscale_backend_combo, "chaiNNer", UPSCALE_BACKEND_CHAINNER)
        self._add_combo_choice(self.upscale_backend_combo, "Real-ESRGAN NCNN", UPSCALE_BACKEND_REALESRGAN_NCNN)
        self.safe_upscale_wizard_button = QPushButton("Run Summary")
        self.safe_upscale_wizard_button.setToolTip(
            "Open a read-only summary of the current sources, backend, texture policy, and direct upscale settings before running."
        )
        upscale_backend_grid.addWidget(QLabel("Backend"), 0, 0)
        upscale_backend_grid.addWidget(self.upscale_backend_combo, 0, 1)
        upscale_backend_grid.addWidget(self.safe_upscale_wizard_button, 0, 2)
        upscale_layout.addLayout(upscale_backend_grid)

        upscale_hint = QLabel(
            "Choose one optional upscaling backend. Texture Policy below still applies before DDS rebuild, while scale/tile controls only appear for the direct NCNN backend."
        )
        upscale_hint.setObjectName("HintLabel")
        upscale_hint.setWordWrap(True)
        upscale_layout.addWidget(upscale_hint)

        self.upscale_backend_stack = QStackedWidget()
        self.upscale_backend_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        upscale_layout.addWidget(self.upscale_backend_stack)

        upscale_none_page = QWidget()
        upscale_none_page.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        upscale_none_layout = QVBoxLayout(upscale_none_page)
        upscale_none_layout.setContentsMargins(0, 0, 0, 0)
        upscale_none_layout.setSpacing(8)
        no_upscale_hint = QLabel(
            "Disabled: the app will rebuild DDS from the existing PNG root. If DDS-to-PNG conversion is enabled, Start stops after PNG creation."
        )
        no_upscale_hint.setObjectName("HintLabel")
        no_upscale_hint.setWordWrap(True)
        upscale_none_layout.addWidget(no_upscale_hint)
        self.upscale_backend_stack.addWidget(upscale_none_page)

    def _build_chainner_backend_page(self) -> None:
        chainner_page = QWidget()
        chainner_page.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        chainner_layout = QVBoxLayout(chainner_page)
        chainner_layout.setContentsMargins(0, 0, 0, 0)
        chainner_layout.setSpacing(8)

        chainner_paths_layout = QGridLayout()
        chainner_paths_layout.setHorizontalSpacing(10)
        chainner_paths_layout.setVerticalSpacing(10)
        chainner_paths_layout.setColumnMinimumWidth(0, 136)
        chainner_paths_layout.setColumnStretch(1, 1)
        self.chainner_exe_path_edit = QLineEdit()
        self.chainner_chain_path_edit = QLineEdit()
        self.chainner_exe_browse_button = self._add_path_row(
            chainner_paths_layout,
            0,
            "chaiNNer exe path",
            self.chainner_exe_path_edit,
            self._browse_chainner_exe_path,
        )
        self.chainner_chain_browse_button = self._add_path_row(
            chainner_paths_layout,
            1,
            ".chn file path",
            self.chainner_chain_path_edit,
            self._browse_chainner_chain_path,
        )
        chainner_layout.addLayout(chainner_paths_layout)

        chainner_actions = QHBoxLayout()
        chainner_actions.setSpacing(8)
        self.validate_chainner_button = QPushButton("Validate Chain")
        chainner_actions.addStretch(1)
        chainner_actions.addWidget(self.validate_chainner_button)
        chainner_layout.addLayout(chainner_actions)

        chainner_detected_paths_label = QLabel("Chain inspection")
        chainner_detected_paths_label.setObjectName("HintLabel")
        self.chainner_chain_info_view = QPlainTextEdit()
        self.chainner_chain_info_view.setReadOnly(True)
        self.chainner_chain_info_view.setMinimumHeight(128)
        self.chainner_chain_info_view.setMaximumHeight(190)
        self.chainner_chain_info_view.document().setMaximumBlockCount(120)
        self.chainner_chain_info_view.setPlainText(
            "Select a .chn file to inspect and validate its Load Images, Save Images, model paths, and upscale nodes."
        )
        chainner_layout.addWidget(chainner_detected_paths_label)
        chainner_layout.addWidget(self.chainner_chain_info_view)

        chainner_hint = QLabel("Optional override JSON. Supports app path tokens.")
        chainner_hint.setObjectName("HintLabel")
        chainner_hint.setWordWrap(True)
        chainner_hint.setToolTip(
            "Paste either the full chaiNNer override object or just the inputs object. "
            "Supported path tokens: ${original_dds_root}, ${staging_png_root}, ${png_root}, ${output_root}."
        )
        self.chainner_override_edit = QPlainTextEdit()
        self.chainner_override_edit.setPlaceholderText(
            '{\n  "inputs": {\n    "your_override_id": "${png_root}"\n  }\n}'
        )
        self.chainner_override_edit.setMinimumHeight(116)
        self.chainner_override_edit.setMaximumHeight(120)
        self.chainner_override_edit.document().setMaximumBlockCount(300)
        chainner_layout.addWidget(chainner_hint)
        chainner_layout.addWidget(self.chainner_override_edit)
        self.upscale_backend_stack.addWidget(chainner_page)

    def _build_upscale_policy_controls(self) -> None:
        self.upscale_backend_stack.addWidget(self._build_ncnn_model_picker_page())

        self.ncnn_scale_spin = QSpinBox()
        self.ncnn_scale_spin.setRange(1, 8)
        self.ncnn_tile_size_spin = QSpinBox()
        self.ncnn_tile_size_spin.setRange(0, 32768)
        self.ncnn_tile_size_spin.setSingleStep(32)
        self.ncnn_extra_args_edit = QLineEdit()
        self.upscale_post_correction_combo = QComboBox()
        self._add_combo_choice(self.upscale_post_correction_combo, "Off", UPSCALE_POST_CORRECTION_NONE)
        self._add_combo_choice(
            self.upscale_post_correction_combo,
            "Match Mean Luma",
            UPSCALE_POST_CORRECTION_MATCH_MEAN_LUMA,
        )
        self._add_combo_choice(
            self.upscale_post_correction_combo,
            "Match Levels",
            UPSCALE_POST_CORRECTION_MATCH_LEVELS,
        )
        self._add_combo_choice(
            self.upscale_post_correction_combo,
            "Match Histogram",
            UPSCALE_POST_CORRECTION_MATCH_HISTOGRAM,
        )
        self._add_combo_choice(
            self.upscale_post_correction_combo,
            "Source Match Balanced (recommended)",
            UPSCALE_POST_CORRECTION_SOURCE_MATCH_BALANCED,
        )
        self._add_combo_choice(
            self.upscale_post_correction_combo,
            "Source Match Extended",
            UPSCALE_POST_CORRECTION_SOURCE_MATCH_EXTENDED,
        )
        self._add_combo_choice(
            self.upscale_post_correction_combo,
            "Source Match Experimental",
            UPSCALE_POST_CORRECTION_SOURCE_MATCH_EXPERIMENTAL,
        )
        self.upscale_texture_preset_combo = QComboBox()
        self._add_combo_choice(self.upscale_texture_preset_combo, "Balanced mixed textures (recommended)", UPSCALE_TEXTURE_PRESET_BALANCED)
        self._add_combo_choice(self.upscale_texture_preset_combo, "Color + UI only (safer)", UPSCALE_TEXTURE_PRESET_COLOR_UI)
        self._add_combo_choice(self.upscale_texture_preset_combo, "Color + UI + emissive", UPSCALE_TEXTURE_PRESET_COLOR_UI_EMISSIVE)
        self._add_combo_choice(self.upscale_texture_preset_combo, "All textures (advanced)", UPSCALE_TEXTURE_PRESET_ALL)
        self.enable_automatic_texture_rules_checkbox = QCheckBox("Use automatic texture safety rules")
        self.enable_unsafe_technical_override_checkbox = QCheckBox(
            "Expert override: force technical maps through PNG/upscale path (unsafe)"
        )
        self.retry_smaller_tile_checkbox = QCheckBox("Retry with smaller tile on failure")
        self.enable_mod_ready_loose_export_checkbox = QCheckBox("Create ready mod package after rebuild")
        self.mod_ready_export_root_edit = QLineEdit()
        self.mod_ready_export_browse_button = QPushButton("Browse")
        default_mod_package_options = mod_package_export_options_for_manager("dmm")
        self.mod_ready_create_no_encrypt_checkbox = QCheckBox(MOD_PACKAGE_METADATA_ARTIFACTS_BY_KEY["no_encrypt"].label)
        self.mod_ready_create_no_encrypt_checkbox.setChecked(default_mod_package_options.create_no_encrypt_file)
        self.mod_ready_package_title_edit = QLineEdit()
        self.mod_ready_package_version_edit = QLineEdit()
        self.mod_ready_package_author_edit = QLineEdit()
        self.mod_ready_package_description_edit = QLineEdit()
        self.mod_ready_package_nexus_url_edit = QLineEdit()
        self.mod_ready_manager_combo = QComboBox()
        self.mod_ready_manager_combo.addItem("Definitive Mod Manager", "dmm")
        self.mod_ready_manager_combo.addItem("JMM JSON", "jmm")
        self.mod_ready_manager_combo.addItem("CDUMM", "cdumm")
        self.mod_ready_manager_combo.addItem("Crimson Sharp / Crimson Browser", "crimson_sharp")
        self.mod_ready_manager_combo.addItem("Field-JSON v3.1", "field_json")
        self.mod_ready_profile_checkboxes: Dict[str, QCheckBox] = {}
        self.mod_ready_profiles_widget = QWidget()
        mod_ready_profiles_layout = QHBoxLayout(self.mod_ready_profiles_widget)
        mod_ready_profiles_layout.setContentsMargins(0, 0, 0, 0)
        mod_ready_profiles_layout.setSpacing(10)
        for profile in MOD_PACKAGE_MANAGER_PROFILES:
            checkbox = QCheckBox(MOD_PACKAGE_MANAGER_PROFILE_LABELS.get(profile, profile))
            checkbox.setChecked(profile == "dmm")
            mod_ready_profiles_layout.addWidget(checkbox)
            self.mod_ready_profile_checkboxes[profile] = checkbox
        mod_ready_profiles_layout.addStretch(1)
        self.mod_ready_structure_combo = QComboBox()
        self.mod_ready_structure_combo.addItem("Game-relative folders", "game_relative")
        self.mod_ready_structure_combo.addItem("files/ wrapper", "files_wrapper")
        self.mod_ready_structure_combo.addItem("Custom compact paths", "custom_compact_paths")
        self.mod_ready_structure_combo.addItem("DMM texture folder", "dmm_texture")
        self.mod_ready_structure_combo.addItem("Field-JSON v3.1 assets", "field_json_v31")
        self.mod_ready_manifest_checkbox = QCheckBox(MOD_PACKAGE_METADATA_ARTIFACTS_BY_KEY["manifest_json"].label)
        self.mod_ready_manifest_checkbox.setChecked(default_mod_package_options.create_manifest_json)
        self.mod_ready_mod_json_checkbox = QCheckBox(MOD_PACKAGE_METADATA_ARTIFACTS_BY_KEY["mod_json"].label)
        self.mod_ready_mod_json_checkbox.setChecked(default_mod_package_options.create_mod_json)
        self.mod_ready_modinfo_checkbox = QCheckBox(MOD_PACKAGE_METADATA_ARTIFACTS_BY_KEY["modinfo_json"].label)
        self.mod_ready_modinfo_checkbox.setChecked(default_mod_package_options.create_modinfo_json)
        self.mod_ready_info_json_checkbox = QCheckBox(MOD_PACKAGE_METADATA_ARTIFACTS_BY_KEY["info_json"].label)
        self.mod_ready_info_json_checkbox.setChecked(default_mod_package_options.create_info_json)
        self.mod_ready_zip_checkbox = QCheckBox(MOD_PACKAGE_METADATA_ARTIFACTS_BY_KEY["ready_zip"].label)
        self.mod_ready_conflict_mode_combo = QComboBox()
        self.mod_ready_conflict_mode_combo.addItem("Normal", "")
        self.mod_ready_conflict_mode_combo.addItem("Override wins", "override")
        self.mod_ready_target_language_edit = QLineEdit()
        self.mod_ready_target_language_edit.setPlaceholderText("Optional, for language-specific managers")
        self.mod_ready_package_title_edit.setPlaceholderText(MOD_READY_PACKAGE_TITLE)
        self.mod_ready_package_version_edit.setPlaceholderText(MOD_READY_PACKAGE_VERSION)
        self.mod_ready_package_nexus_url_edit.setPlaceholderText("https://www.nexusmods.com/...")
        self.ncnn_scale_spin.setToolTip("")
        self.ncnn_tile_size_spin.setToolTip("")
        self.ncnn_extra_args_edit.setToolTip("")
        self.ncnn_extra_args_edit.setPlaceholderText('Example: -dn 0.2')
        self.upscale_post_correction_combo.setToolTip("")
        self.upscale_texture_preset_combo.setToolTip(
            "Controls which texture types are allowed into the PNG/upscale path and which ones are copied through unchanged."
        )
        self.enable_automatic_texture_rules_checkbox.setToolTip(
            "Applies safer DDS rebuild recommendations for format flags, alpha handling, and technical-map preservation. "
            "This is a safety/policy feature, not a brightness correction feature."
        )
        self.enable_unsafe_technical_override_checkbox.setToolTip(
            "Expert-only override. Forces technical textures such as normals, masks, roughness, height, and vectors onto the generic visible-color PNG/upscale path "
            "instead of preserving them. This can produce broken normals, bad masks, or incorrect shading."
        )

    def _build_upscale_policy_layout(self, upscale_layout: QVBoxLayout) -> None:
        self.texture_policy_group = QGroupBox("Texture Policy")
        policy_layout = QGridLayout(self.texture_policy_group)
        policy_layout.setHorizontalSpacing(10)
        policy_layout.setVerticalSpacing(8)
        policy_layout.setColumnMinimumWidth(0, 136)
        policy_layout.setColumnStretch(1, 1)

        policy_layout.addWidget(QLabel("Preset"), 0, 0)
        policy_layout.addWidget(self.upscale_texture_preset_combo, 0, 1)
        policy_layout.addWidget(self.enable_automatic_texture_rules_checkbox, 1, 0, 1, 2)
        policy_layout.addWidget(self.enable_unsafe_technical_override_checkbox, 2, 0, 1, 2)
        policy_layout.addWidget(self.enable_mod_ready_loose_export_checkbox, 3, 0, 1, 2)
        policy_layout.addWidget(QLabel("Mod package parent root"), 4, 0)
        loose_export_row = QHBoxLayout()
        loose_export_row.setContentsMargins(0, 0, 0, 0)
        loose_export_row.setSpacing(8)
        loose_export_row.addWidget(self.mod_ready_export_root_edit, stretch=1)
        loose_export_row.addWidget(self.mod_ready_export_browse_button)
        policy_layout.addLayout(loose_export_row, 4, 1)
        self.mod_ready_package_group = QGroupBox("Mod Package Metadata")
        mod_package_layout = QGridLayout(self.mod_ready_package_group)
        mod_package_layout.setHorizontalSpacing(10)
        mod_package_layout.setVerticalSpacing(8)
        mod_package_layout.setColumnMinimumWidth(0, 136)
        mod_package_layout.setColumnStretch(1, 1)
        mod_package_layout.addWidget(QLabel("Title"), 0, 0)
        mod_package_layout.addWidget(self.mod_ready_package_title_edit, 0, 1)
        mod_package_layout.addWidget(QLabel("Version"), 1, 0)
        mod_package_layout.addWidget(self.mod_ready_package_version_edit, 1, 1)
        mod_package_layout.addWidget(QLabel("Author"), 2, 0)
        mod_package_layout.addWidget(self.mod_ready_package_author_edit, 2, 1)
        mod_package_layout.addWidget(QLabel("Description"), 3, 0)
        mod_package_layout.addWidget(self.mod_ready_package_description_edit, 3, 1)
        mod_package_layout.addWidget(QLabel("Target Mod Managers"), 4, 0)
        mod_package_layout.addWidget(self.mod_ready_profiles_widget, 4, 1, 1, 2)
        mod_package_layout.addWidget(QLabel("Package output"), 5, 0)
        mod_package_layout.addWidget(self.mod_ready_zip_checkbox, 5, 1, 1, 2)
        self.mod_ready_conflict_mode_label = QLabel("Conflict mode")
        self.mod_ready_target_language_label = QLabel("Target language")
        self.mod_ready_conflict_mode_help = make_help_button("CDUMM compatibility metadata. Normal leaves manager conflict behavior unchanged; Override asks compatible managers to prefer this mod when conflicts are detected.")
        self.mod_ready_target_language_help = make_help_button("Optional CDUMM compatibility metadata for language-specific packages. Leave empty for general packages.")
        mod_package_layout.addWidget(self.mod_ready_conflict_mode_label, 6, 0)
        mod_package_layout.addWidget(self.mod_ready_conflict_mode_combo, 6, 1)
        mod_package_layout.addWidget(self.mod_ready_conflict_mode_help, 6, 2)
        mod_package_layout.addWidget(self.mod_ready_target_language_label, 7, 0)
        mod_package_layout.addWidget(self.mod_ready_target_language_edit, 7, 1)
        mod_package_layout.addWidget(self.mod_ready_target_language_help, 7, 2)
        self.mod_ready_package_group.setVisible(False)
        policy_layout.addWidget(self.mod_ready_package_group, 5, 0, 1, 2)

        self.texture_policy_hint_panel, self.texture_policy_hint_rows = self._create_guidance_panel(
            [
                ("summary", "Preset summary"),
                ("upscaled", "Upscaled"),
                ("copied", "Copied unchanged"),
                ("rules", "Safety rules"),
                ("override", "Expert override"),
                ("warning", "Warning"),
            ]
        )
        policy_layout.addWidget(self.texture_policy_hint_panel, 6, 0, 1, 2)
        policy_layout.addWidget(make_help_button(
            "Texture Policy controls which texture types are allowed into the PNG/upscale path and which are copied unchanged. "
            "Preset summary, upscaled/copied categories, safety rules, expert override, and warnings are summarized here when relevant."
        ), 0, 2, alignment=Qt.AlignRight)
        upscale_layout.addWidget(self.texture_policy_group)

        self.direct_backend_controls_group = QGroupBox("Direct Upscale Controls (NCNN only)")
        direct_layout = QGridLayout(self.direct_backend_controls_group)
        direct_layout.setHorizontalSpacing(10)
        direct_layout.setVerticalSpacing(8)
        direct_layout.setColumnMinimumWidth(0, 136)
        direct_layout.setColumnStretch(1, 1)

        scale_label = QLabel("Scale")
        direct_layout.addWidget(scale_label, 0, 0)
        direct_layout.addWidget(self.ncnn_scale_spin, 0, 1)
        direct_layout.addWidget(make_help_button("Final PNG scale for direct backends. Keep close to the selected model's intended native scale for predictable output."), 0, 2)
        tile_size_label = QLabel("Tile size")
        direct_layout.addWidget(tile_size_label, 1, 0)
        direct_layout.addWidget(self.ncnn_tile_size_spin, 1, 1)
        direct_layout.addWidget(make_help_button("Tile size for direct backends. 0 means no manual tiling. Smaller values use less VRAM and can recover from failures, but run slower."), 1, 2)
        ncnn_extra_args_label = QLabel("NCNN extra args")
        direct_layout.addWidget(ncnn_extra_args_label, 2, 0)
        direct_layout.addWidget(self.ncnn_extra_args_edit, 2, 1)
        direct_layout.addWidget(make_help_button("Optional extra command-line arguments appended to the Real-ESRGAN NCNN call. Example: -dn 0.2. Use only flags supported by the selected NCNN build/model."), 2, 2)
        post_correction_label = QLabel("Post correction")
        direct_layout.addWidget(post_correction_label, 3, 0)
        direct_layout.addWidget(self.upscale_post_correction_combo, 3, 1)
        direct_layout.addWidget(make_help_button("Optional post-upscale correction applied after direct backend output and before DDS rebuild. Source Match modes decide per texture whether to correct visible RGB, scalar grayscale, or skip."), 3, 2)
        direct_layout.addWidget(self.retry_smaller_tile_checkbox, 4, 0, 1, 2)
        upscale_layout.addWidget(self.direct_backend_controls_group)

__all__ = ["TextureWorkflowUpscaleBackendPanelMixin"]
