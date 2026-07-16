"""Workflow profile, rule, and match panel construction."""

from __future__ import annotations

from typing import List

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from cdmw.constants import (
    DDS_FORMAT_MODE_MATCH_ORIGINAL,
    DDS_MIP_MODE_FULL_CHAIN,
    DDS_MIP_MODE_MATCH_ORIGINAL,
    DDS_MIP_MODE_SINGLE,
    DDS_SIZE_MODE_ORIGINAL,
    DDS_SIZE_MODE_PNG,
    SUPPORTED_DDS_FORMAT_CHOICES,
    UPSCALE_POST_CORRECTION_MATCH_HISTOGRAM,
    UPSCALE_POST_CORRECTION_MATCH_LEVELS,
    UPSCALE_POST_CORRECTION_MATCH_MEAN_LUMA,
    UPSCALE_POST_CORRECTION_NONE,
    UPSCALE_POST_CORRECTION_SOURCE_MATCH_BALANCED,
    UPSCALE_POST_CORRECTION_SOURCE_MATCH_EXPERIMENTAL,
    UPSCALE_POST_CORRECTION_SOURCE_MATCH_EXTENDED,
)
from cdmw.domain.textures.profiles import get_texture_processing_profile_keys
from cdmw.models import TextureProcessingPlan, TextureRule, TextureWorkflowProfile
from cdmw.ui.shell.texture_panel_persistence import finish_texture_workflow_panel_body
from cdmw.ui.widgets import CollapsibleSection, EmptyStateTreeWidget, make_tree_columns_persistent


class TextureWorkflowProfilesUiMixin:
    """Build profile/rule/match widgets for texture workflow."""
    def _build_workflow_profiles_section(self, *, expanded: bool = False) -> CollapsibleSection:
        self.texture_rules_legacy_text = ""
        self.workflow_profiles_state: List[TextureWorkflowProfile] = []
        self.texture_rules_state: List[TextureRule] = []
        self.workflow_matched_processing_plan: List[TextureProcessingPlan] = []
        self._workflow_editor_syncing = False
        self._workflow_match_refresh_timer = QTimer(self)
        self._workflow_match_refresh_timer.setSingleShot(True)
        self._workflow_match_refresh_timer.setInterval(300)
        self._workflow_match_refresh_timer.timeout.connect(self._refresh_workflow_matched_files_view)
        self.filters_section = CollapsibleSection(
            "Workflow Profiles, Rules & Matches",
            body_builder=lambda body_layout: TextureWorkflowProfilesUiMixin._build_workflow_profiles_body(self, body_layout),
        )
        self.filters_section.set_expanded(expanded)
        return self.filters_section

    def _build_workflow_profiles_body(self, body_layout: QVBoxLayout) -> None:
        filters_group = QWidget()
        filters_layout = QVBoxLayout(filters_group)
        filters_layout.setContentsMargins(0, 0, 0, 0)
        filters_layout.setSpacing(8)
        filters_label = QLabel("Folder / file filter")
        filters_hint = QLabel("Optional glob patterns, one per line or separated by semicolons.")
        filters_hint.setObjectName("HintLabel")
        filters_hint.setWordWrap(True)
        self.filters_edit = QPlainTextEdit()
        self.filters_edit.setPlaceholderText("examples:\ncharacters/*\nui/**/*.dds")
        self.filters_edit.setMinimumHeight(80)
        self.filters_edit.setMaximumHeight(96)
        self.filters_edit.document().setMaximumBlockCount(200)

        texture_rules_label = QLabel("Per-file workflow matching")
        texture_rules_hint = QLabel(
            "Build reusable per-file workflow profiles, assign them with ordered rules, and inspect the live matched DDS set."
        )
        texture_rules_hint.setObjectName("HintLabel")
        texture_rules_hint.setWordWrap(True)
        texture_rules_hint.setToolTip("")

        profiles_group = TextureWorkflowProfilesUiMixin._build_workflow_profiles_group(self)

        rules_group = TextureWorkflowProfilesUiMixin._build_workflow_rules_group(self)

        matched_group = TextureWorkflowProfilesUiMixin._build_workflow_matches_group(self)

        filters_layout.addWidget(filters_label)
        filters_layout.addWidget(filters_hint)
        filters_layout.addWidget(self.filters_edit)
        filters_layout.addWidget(texture_rules_label)
        filters_layout.addWidget(texture_rules_hint)
        filters_layout.addWidget(profiles_group)
        filters_layout.addWidget(rules_group)
        filters_layout.addWidget(matched_group)
        body_layout.addWidget(filters_group)
        finish_texture_workflow_panel_body(self, "filters")


    def _build_workflow_profiles_group(self) -> QGroupBox:
        profiles_group = QGroupBox("Workflow Profiles")
        profiles_layout = QVBoxLayout(profiles_group)
        profiles_layout.setContentsMargins(10, 10, 10, 10)
        profiles_layout.setSpacing(8)
        profiles_button_row = QHBoxLayout()
        profiles_button_row.setSpacing(6)
        self.workflow_profile_add_button = QPushButton("Add")
        self.workflow_profile_duplicate_button = QPushButton("Duplicate")
        self.workflow_profile_delete_button = QPushButton("Delete")
        profiles_button_row.addWidget(self.workflow_profile_add_button)
        profiles_button_row.addWidget(self.workflow_profile_duplicate_button)
        profiles_button_row.addWidget(self.workflow_profile_delete_button)
        profiles_button_row.addStretch(1)
        profiles_layout.addLayout(profiles_button_row)

        self.workflow_profiles_tree = EmptyStateTreeWidget(
            "No workflow profiles",
            "Add a profile to define reusable DDS output and upscale settings.",
        )
        self.workflow_profiles_tree.setRootIsDecorated(False)
        self.workflow_profiles_tree.setAlternatingRowColors(True)
        self.workflow_profiles_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.workflow_profiles_tree.setHeaderLabels(["Name", "Action", "DDS Output", "NCNN"])
        self.workflow_profiles_tree.header().setStretchLastSection(False)
        self.workflow_profiles_tree.header().resizeSection(0, 180)
        self.workflow_profiles_tree.header().resizeSection(1, 130)
        self.workflow_profiles_tree.header().resizeSection(2, 220)
        self.workflow_profiles_tree.header().resizeSection(3, 240)
        make_tree_columns_persistent(
            self.workflow_profiles_tree,
            self.settings,
            "main/workflow_profiles",
            minimum_width=56,
            save_callback=self.schedule_settings_save,
        )
        profiles_layout.addWidget(self.workflow_profiles_tree)

        profile_detail_group = QGroupBox("Selected Profile")
        profile_detail_layout = QVBoxLayout(profile_detail_group)
        profile_detail_layout.setContentsMargins(8, 8, 8, 8)
        profile_detail_layout.setSpacing(6)
        self.workflow_profile_name_edit = QLineEdit()
        self.workflow_profile_action_combo = QComboBox()
        self._add_combo_choice(self.workflow_profile_action_combo, "Inherit Planner", "")
        self._add_combo_choice(self.workflow_profile_action_combo, "Upscale Then Rebuild", "upscale_then_rebuild")
        self._add_combo_choice(self.workflow_profile_action_combo, "Rebuild From PNG", "rebuild_from_png")
        self._add_combo_choice(self.workflow_profile_action_combo, "Preserve Original", "preserve_original")
        self._add_combo_choice(self.workflow_profile_action_combo, "Skip", "skip")
        self.workflow_profile_format_combo = QComboBox()
        self._add_combo_choice(self.workflow_profile_format_combo, "Inherit Main DDS Output", "")
        self._add_combo_choice(self.workflow_profile_format_combo, "Match Original DDS", DDS_FORMAT_MODE_MATCH_ORIGINAL)
        for dds_format in SUPPORTED_DDS_FORMAT_CHOICES:
            self._add_combo_choice(self.workflow_profile_format_combo, dds_format, dds_format)
        self.workflow_profile_size_combo = QComboBox()
        self._add_combo_choice(self.workflow_profile_size_combo, "Inherit Main DDS Output", "")
        self._add_combo_choice(self.workflow_profile_size_combo, "Match PNG Size", DDS_SIZE_MODE_PNG)
        self._add_combo_choice(self.workflow_profile_size_combo, "Match Original DDS", DDS_SIZE_MODE_ORIGINAL)
        self._add_combo_choice(self.workflow_profile_size_combo, "Custom Size", "__custom__")
        self.workflow_profile_custom_width_spin = QSpinBox()
        self.workflow_profile_custom_width_spin.setRange(1, 65535)
        self.workflow_profile_custom_height_spin = QSpinBox()
        self.workflow_profile_custom_height_spin.setRange(1, 65535)
        self.workflow_profile_custom_size_widget = QWidget()
        workflow_profile_custom_size_row = QHBoxLayout(self.workflow_profile_custom_size_widget)
        workflow_profile_custom_size_row.setContentsMargins(0, 0, 0, 0)
        workflow_profile_custom_size_row.setSpacing(6)
        workflow_profile_custom_size_row.addWidget(self.workflow_profile_custom_width_spin)
        workflow_profile_custom_size_row.addWidget(QLabel("x"))
        workflow_profile_custom_size_row.addWidget(self.workflow_profile_custom_height_spin)
        workflow_profile_custom_size_row.addStretch(1)
        self.workflow_profile_mip_combo = QComboBox()
        self._add_combo_choice(self.workflow_profile_mip_combo, "Inherit Main DDS Output", "")
        self._add_combo_choice(self.workflow_profile_mip_combo, "Match Original DDS", DDS_MIP_MODE_MATCH_ORIGINAL)
        self._add_combo_choice(self.workflow_profile_mip_combo, "Full Chain", DDS_MIP_MODE_FULL_CHAIN)
        self._add_combo_choice(self.workflow_profile_mip_combo, "Single Mip", DDS_MIP_MODE_SINGLE)
        self._add_combo_choice(self.workflow_profile_mip_combo, "Custom Mip Count", "__custom__")
        self.workflow_profile_custom_mip_spin = QSpinBox()
        self.workflow_profile_custom_mip_spin.setRange(1, 32)
        self.workflow_profile_ncnn_model_combo = QComboBox()
        self._add_combo_choice(self.workflow_profile_ncnn_model_combo, "Inherit Direct NCNN Model", "")
        self.workflow_profile_ncnn_scale_combo = QComboBox()
        self._add_combo_choice(self.workflow_profile_ncnn_scale_combo, "Inherit Direct NCNN Scale", "")
        self._add_combo_choice(self.workflow_profile_ncnn_scale_combo, "2x", "2")
        self._add_combo_choice(self.workflow_profile_ncnn_scale_combo, "3x", "3")
        self._add_combo_choice(self.workflow_profile_ncnn_scale_combo, "4x", "4")
        self.workflow_profile_ncnn_tile_override_checkbox = QCheckBox("Override tile")
        self.workflow_profile_ncnn_tile_spin = QSpinBox()
        self.workflow_profile_ncnn_tile_spin.setRange(0, 65535)
        self.workflow_profile_ncnn_extra_args_edit = QLineEdit()
        self.workflow_profile_post_correction_combo = QComboBox()
        self._add_combo_choice(self.workflow_profile_post_correction_combo, "Inherit Direct NCNN Correction", "")
        self._add_combo_choice(self.workflow_profile_post_correction_combo, "Off", UPSCALE_POST_CORRECTION_NONE)
        self._add_combo_choice(self.workflow_profile_post_correction_combo, "Match Mean Luma", UPSCALE_POST_CORRECTION_MATCH_MEAN_LUMA)
        self._add_combo_choice(self.workflow_profile_post_correction_combo, "Match Levels", UPSCALE_POST_CORRECTION_MATCH_LEVELS)
        self._add_combo_choice(self.workflow_profile_post_correction_combo, "Match Histogram", UPSCALE_POST_CORRECTION_MATCH_HISTOGRAM)
        self._add_combo_choice(self.workflow_profile_post_correction_combo, "Source Match Balanced", UPSCALE_POST_CORRECTION_SOURCE_MATCH_BALANCED)
        self._add_combo_choice(self.workflow_profile_post_correction_combo, "Source Match Extended", UPSCALE_POST_CORRECTION_SOURCE_MATCH_EXTENDED)
        self._add_combo_choice(self.workflow_profile_post_correction_combo, "Source Match Experimental", UPSCALE_POST_CORRECTION_SOURCE_MATCH_EXPERIMENTAL)
        identity_panel, identity_layout = self._create_workflow_profile_panel("Profile", "identity")
        identity_layout.addWidget(self._workflow_profile_field_label("Name"), 0, 0)
        identity_layout.addWidget(self.workflow_profile_name_edit, 0, 1)
        identity_layout.addWidget(self._workflow_profile_field_label("Action"), 0, 2)
        identity_layout.addWidget(self.workflow_profile_action_combo, 0, 3)

        dds_panel, dds_layout = self._create_workflow_profile_panel("DDS Output Overrides", "dds")
        dds_layout.addWidget(self._workflow_profile_field_label("Format"), 0, 0)
        dds_layout.addWidget(self.workflow_profile_format_combo, 0, 1)
        dds_layout.addWidget(self._workflow_profile_field_label("Size"), 0, 2)
        dds_layout.addWidget(self.workflow_profile_size_combo, 0, 3)
        self.workflow_profile_custom_size_label = self._workflow_profile_field_label("Custom Size")
        dds_layout.addWidget(self.workflow_profile_custom_size_label, 1, 0)
        dds_layout.addWidget(self.workflow_profile_custom_size_widget, 1, 1)
        dds_layout.addWidget(self._workflow_profile_field_label("Mipmaps"), 1, 2)
        dds_layout.addWidget(self.workflow_profile_mip_combo, 1, 3)
        self.workflow_profile_custom_mip_label = self._workflow_profile_field_label("Custom Mips")
        dds_layout.addWidget(self.workflow_profile_custom_mip_label, 2, 0)
        dds_layout.addWidget(self.workflow_profile_custom_mip_spin, 2, 1)

        ncnn_panel, ncnn_layout = self._create_workflow_profile_panel("Direct NCNN / Correction Overrides", "ncnn")
        ncnn_layout.addWidget(self._workflow_profile_field_label("Model"), 0, 0)
        ncnn_layout.addWidget(self.workflow_profile_ncnn_model_combo, 0, 1)
        ncnn_layout.addWidget(self._workflow_profile_field_label("Scale"), 0, 2)
        ncnn_layout.addWidget(self.workflow_profile_ncnn_scale_combo, 0, 3)
        ncnn_layout.addWidget(self.workflow_profile_ncnn_tile_override_checkbox, 1, 0)
        ncnn_layout.addWidget(self.workflow_profile_ncnn_tile_spin, 1, 1)
        ncnn_layout.addWidget(self._workflow_profile_field_label("Extra Args"), 1, 2)
        ncnn_layout.addWidget(self.workflow_profile_ncnn_extra_args_edit, 1, 3)
        ncnn_layout.addWidget(self._workflow_profile_field_label("Post Correction"), 2, 0)
        ncnn_layout.addWidget(self.workflow_profile_post_correction_combo, 2, 1, 1, 3)

        profile_detail_layout.addWidget(identity_panel)
        profile_detail_layout.addWidget(dds_panel)
        profile_detail_layout.addWidget(ncnn_panel)
        profiles_layout.addWidget(profile_detail_group)
        return profiles_group

    def _build_workflow_rules_group(self) -> QGroupBox:
        rules_group = QGroupBox("Ordered Rules")
        rules_layout = QVBoxLayout(rules_group)
        rules_layout.setContentsMargins(10, 10, 10, 10)
        rules_layout.setSpacing(8)
        rules_button_row = QHBoxLayout()
        rules_button_row.setSpacing(6)
        self.workflow_rule_add_button = QPushButton("Add")
        self.workflow_rule_duplicate_button = QPushButton("Duplicate")
        self.workflow_rule_delete_button = QPushButton("Delete")
        self.workflow_rule_move_up_button = QPushButton("Move Up")
        self.workflow_rule_move_down_button = QPushButton("Move Down")
        rules_button_row.addWidget(self.workflow_rule_add_button)
        rules_button_row.addWidget(self.workflow_rule_duplicate_button)
        rules_button_row.addWidget(self.workflow_rule_delete_button)
        rules_button_row.addWidget(self.workflow_rule_move_up_button)
        rules_button_row.addWidget(self.workflow_rule_move_down_button)
        rules_button_row.addStretch(1)
        rules_layout.addLayout(rules_button_row)

        self.workflow_rules_tree = EmptyStateTreeWidget(
            "No matching rules",
            "Add rules to assign workflow profiles by path, package, size, or role.",
        )
        self.workflow_rules_tree.setRootIsDecorated(False)
        self.workflow_rules_tree.setAlternatingRowColors(True)
        self.workflow_rules_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.workflow_rules_tree.setHeaderLabels(
            ["On", "Match", "Pattern", "Workflow", "Semantic", "Planner", "Color", "Alpha", "Path"]
        )
        self.workflow_rules_tree.header().resizeSection(0, 50)
        self.workflow_rules_tree.header().resizeSection(1, 60)
        self.workflow_rules_tree.header().resizeSection(2, 210)
        self.workflow_rules_tree.header().resizeSection(3, 120)
        self.workflow_rules_tree.header().resizeSection(4, 140)
        self.workflow_rules_tree.header().resizeSection(5, 120)
        self.workflow_rules_tree.header().resizeSection(6, 90)
        self.workflow_rules_tree.header().resizeSection(7, 120)
        self.workflow_rules_tree.header().resizeSection(8, 150)
        make_tree_columns_persistent(
            self.workflow_rules_tree,
            self.settings,
            "main/workflow_rules",
            minimum_width=48,
            save_callback=self.schedule_settings_save,
        )
        rules_layout.addWidget(self.workflow_rules_tree)

        rule_detail_group = QGroupBox("Selected Rule")
        rule_detail_layout = QGridLayout(rule_detail_group)
        rule_detail_layout.setHorizontalSpacing(10)
        rule_detail_layout.setVerticalSpacing(8)
        self.workflow_rule_enabled_checkbox = QCheckBox("Enabled")
        self.workflow_rule_match_mode_combo = QComboBox()
        self._add_combo_choice(self.workflow_rule_match_mode_combo, "Glob", "glob")
        self._add_combo_choice(self.workflow_rule_match_mode_combo, "Exact Path", "exact")
        self.workflow_rule_pattern_edit = QLineEdit()
        self.workflow_rule_profile_combo = QComboBox()
        self._add_combo_choice(self.workflow_rule_profile_combo, "No Workflow Profile", "")
        self.workflow_rule_semantic_combo = QComboBox()
        self.workflow_rule_semantic_combo.setEditable(True)
        self.workflow_rule_semantic_combo.addItems(
            [
                "",
                "color:albedo",
                "normal:normal",
                "mask:packed_mask",
                "mask:opacity_mask",
                "height:height",
                "roughness:roughness",
                "ui:ui",
                "emissive:emissive",
            ]
        )
        self.workflow_rule_planner_profile_combo = QComboBox()
        self._add_combo_choice(self.workflow_rule_planner_profile_combo, "Inherit Planner Profile", "")
        for planner_profile_key in get_texture_processing_profile_keys():
            self._add_combo_choice(self.workflow_rule_planner_profile_combo, planner_profile_key, planner_profile_key)
        self.workflow_rule_planner_profile_combo.setToolTip("")
        self.workflow_rule_colorspace_combo = QComboBox()
        self._add_combo_choice(self.workflow_rule_colorspace_combo, "Inherit Colorspace", "")
        self._add_combo_choice(self.workflow_rule_colorspace_combo, "sRGB", "srgb")
        self._add_combo_choice(self.workflow_rule_colorspace_combo, "Linear", "linear")
        self._add_combo_choice(self.workflow_rule_colorspace_combo, "Match Source", "match_source")
        self.workflow_rule_alpha_combo = QComboBox()
        self._add_combo_choice(self.workflow_rule_alpha_combo, "Inherit Alpha Policy", "")
        self._add_combo_choice(self.workflow_rule_alpha_combo, "None", "none")
        self._add_combo_choice(self.workflow_rule_alpha_combo, "Straight", "straight")
        self._add_combo_choice(self.workflow_rule_alpha_combo, "Cutout Coverage", "cutout_coverage")
        self._add_combo_choice(self.workflow_rule_alpha_combo, "Channel Data", "channel_data")
        self._add_combo_choice(self.workflow_rule_alpha_combo, "Premultiplied", "premultiplied")
        self.workflow_rule_intermediate_combo = QComboBox()
        self._add_combo_choice(self.workflow_rule_intermediate_combo, "Inherit Planner Path", "")
        self._add_combo_choice(self.workflow_rule_intermediate_combo, "Visible Color PNG", "visible_color_png_path")
        self._add_combo_choice(self.workflow_rule_intermediate_combo, "Technical Preserve", "technical_preserve_path")
        self._add_combo_choice(self.workflow_rule_intermediate_combo, "Technical High Precision", "technical_high_precision_path")
        self.workflow_rule_intermediate_combo.setToolTip("")
        planner_profile_label_widget = QWidget()
        planner_profile_label_layout = QHBoxLayout(planner_profile_label_widget)
        planner_profile_label_layout.setContentsMargins(0, 0, 0, 0)
        planner_profile_label_layout.setSpacing(6)
        planner_profile_label_layout.addWidget(QLabel("Planner Profile"))
        self.workflow_rule_planner_profile_help_button = QPushButton("Docs")
        self.workflow_rule_planner_profile_help_button.setMaximumWidth(56)
        self.workflow_rule_planner_profile_help_button.setToolTip(
            "Open the in-app documentation topic that explains planner profiles."
        )
        planner_profile_label_layout.addWidget(self.workflow_rule_planner_profile_help_button)
        planner_profile_label_layout.addStretch(1)
        planner_path_label_widget = QWidget()
        planner_path_label_layout = QHBoxLayout(planner_path_label_widget)
        planner_path_label_layout.setContentsMargins(0, 0, 0, 0)
        planner_path_label_layout.setSpacing(6)
        planner_path_label_layout.addWidget(QLabel("Planner Path"))
        self.workflow_rule_planner_path_help_button = QPushButton("Docs")
        self.workflow_rule_planner_path_help_button.setMaximumWidth(56)
        self.workflow_rule_planner_path_help_button.setToolTip(
            "Open the in-app documentation topic that explains planner paths."
        )
        planner_path_label_layout.addWidget(self.workflow_rule_planner_path_help_button)
        planner_path_label_layout.addStretch(1)
        rule_detail_layout.addWidget(self.workflow_rule_enabled_checkbox, 0, 0)
        rule_detail_layout.addWidget(QLabel("Match"), 0, 1)
        rule_detail_layout.addWidget(self.workflow_rule_match_mode_combo, 0, 2)
        rule_detail_layout.addWidget(QLabel("Pattern"), 1, 0)
        rule_detail_layout.addWidget(self.workflow_rule_pattern_edit, 1, 1, 1, 3)
        rule_detail_layout.addWidget(QLabel("Workflow Profile"), 2, 0)
        rule_detail_layout.addWidget(self.workflow_rule_profile_combo, 2, 1)
        rule_detail_layout.addWidget(QLabel("Semantic"), 2, 2)
        rule_detail_layout.addWidget(self.workflow_rule_semantic_combo, 2, 3)
        rule_detail_layout.addWidget(planner_profile_label_widget, 3, 0)
        rule_detail_layout.addWidget(self.workflow_rule_planner_profile_combo, 3, 1)
        rule_detail_layout.addWidget(QLabel("Colorspace"), 3, 2)
        rule_detail_layout.addWidget(self.workflow_rule_colorspace_combo, 3, 3)
        rule_detail_layout.addWidget(QLabel("Alpha Policy"), 4, 0)
        rule_detail_layout.addWidget(self.workflow_rule_alpha_combo, 4, 1)
        rule_detail_layout.addWidget(planner_path_label_widget, 4, 2)
        rule_detail_layout.addWidget(self.workflow_rule_intermediate_combo, 4, 3)
        self.workflow_rule_planner_profile_help_button.clicked.connect(
            lambda: self.show_documentation_dialog(topic_id="workflow_planner_profiles")
        )
        self.workflow_rule_planner_path_help_button.clicked.connect(
            lambda: self.show_documentation_dialog(topic_id="workflow_planner_paths")
        )
        rules_layout.addWidget(rule_detail_group)
        return rules_group

    def _build_workflow_matches_group(self) -> QGroupBox:
        matched_group = QGroupBox("Matched Files")
        matched_layout = QVBoxLayout(matched_group)
        matched_layout.setContentsMargins(10, 10, 10, 10)
        matched_layout.setSpacing(8)
        matched_button_row = QHBoxLayout()
        matched_button_row.setSpacing(6)
        self.workflow_matched_refresh_button = QPushButton("Refresh")
        self.workflow_assign_profile_button = QPushButton("Assign Profile")
        matched_button_row.addWidget(self.workflow_matched_refresh_button)
        matched_button_row.addWidget(self.workflow_assign_profile_button)
        matched_button_row.addStretch(1)
        matched_layout.addLayout(matched_button_row)
        self.workflow_matched_summary_label = QLabel(
            "This table follows the current Original DDS root and workflow filter. Exact-path assignments append new last-match rules."
        )
        self.workflow_matched_summary_label.setObjectName("HintLabel")
        self.workflow_matched_summary_label.setWordWrap(True)
        matched_layout.addWidget(self.workflow_matched_summary_label)
        self.workflow_matched_files_tree = EmptyStateTreeWidget(
            "No matched files",
            "Scan or refresh workflow matching to see which DDS files use each profile.",
        )
        self.workflow_matched_files_tree.setRootIsDecorated(False)
        self.workflow_matched_files_tree.setAlternatingRowColors(True)
        self.workflow_matched_files_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.workflow_matched_files_tree.setHeaderLabels(
            ["Path", "Semantic", "Rule", "Workflow", "DDS Output", "NCNN", "Action"]
        )
        self.workflow_matched_files_tree.header().resizeSection(0, 300)
        self.workflow_matched_files_tree.header().resizeSection(1, 150)
        self.workflow_matched_files_tree.header().resizeSection(2, 200)
        self.workflow_matched_files_tree.header().resizeSection(3, 150)
        self.workflow_matched_files_tree.header().resizeSection(4, 200)
        self.workflow_matched_files_tree.header().resizeSection(5, 220)
        self.workflow_matched_files_tree.header().resizeSection(6, 150)
        make_tree_columns_persistent(
            self.workflow_matched_files_tree,
            self.settings,
            "main/workflow_matched_files",
            minimum_width=56,
            save_callback=self.schedule_settings_save,
        )
        matched_layout.addWidget(self.workflow_matched_files_tree)
        return matched_group

__all__ = ["TextureWorkflowProfilesUiMixin"]
