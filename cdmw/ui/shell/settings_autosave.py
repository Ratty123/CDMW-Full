"""Settings autosave signal wiring for the shell window."""

from __future__ import annotations


class SettingsAutosaveMixin:
    """Connect shell controls to persisted settings updates."""

    def _connect_auto_save(self) -> None:
        line_edits = [
            self.original_dds_edit,
            self.png_root_edit,
            self.texture_editor_png_root_edit,
            self.dds_staging_root_edit,
            self.output_root_edit,
            self.texconv_path_edit,
            self.csv_log_path_edit,
            self.chainner_exe_path_edit,
            self.chainner_chain_path_edit,
            self.ncnn_exe_path_edit,
            self.ncnn_model_dir_edit,
            self.ncnn_extra_args_edit,
            self.mod_ready_export_root_edit,
            self.mod_ready_package_title_edit,
            self.mod_ready_package_version_edit,
            self.mod_ready_package_author_edit,
            self.mod_ready_package_description_edit,
            self.mod_ready_package_nexus_url_edit,
            self.mod_ready_target_language_edit,
            self.archive_package_root_edit,
            self.archive_extract_root_edit,
        ]
        for line_edit in line_edits:
            line_edit.textChanged.connect(self.schedule_settings_save)

        checkboxes = [
            self.dry_run_checkbox,
            self.enable_dds_staging_checkbox,
            self.enable_incremental_resume_checkbox,
            self.csv_log_enabled_checkbox,
            self.unique_basename_checkbox,
            self.overwrite_existing_checkbox,
            self.enable_automatic_texture_rules_checkbox,
            self.enable_unsafe_technical_override_checkbox,
            self.retry_smaller_tile_checkbox,
            self.enable_mod_ready_loose_export_checkbox,
            self.mod_ready_create_no_encrypt_checkbox,
            self.mod_ready_manifest_checkbox,
            self.mod_ready_mod_json_checkbox,
            self.mod_ready_modinfo_checkbox,
            self.mod_ready_info_json_checkbox,
            self.mod_ready_zip_checkbox,
        ]
        for checkbox in checkboxes:
            checkbox.toggled.connect(self.schedule_settings_save)
        for checkbox in self.mod_ready_profile_checkboxes.values():
            checkbox.toggled.connect(self.schedule_settings_save)
            checkbox.toggled.connect(lambda _checked=False: self._apply_mod_ready_export_state())

        combos = [
            self.dds_format_mode_combo,
            self.dds_custom_format_combo,
            self.dds_size_mode_combo,
            self.dds_mip_mode_combo,
            self.upscale_backend_combo,
            self.ncnn_model_combo,
            self.upscale_post_correction_combo,
            self.upscale_texture_preset_combo,
            self.mod_ready_manager_combo,
            self.mod_ready_structure_combo,
            self.mod_ready_conflict_mode_combo,
            self.compare_preview_size_combo,
        ]
        for combo in combos:
            combo.currentIndexChanged.connect(self.schedule_settings_save)

        spins = [
            self.dds_custom_width_spin,
            self.dds_custom_height_spin,
            self.dds_custom_mip_spin,
            self.ncnn_scale_spin,
            self.ncnn_tile_size_spin,
        ]
        for spin in spins:
            spin.valueChanged.connect(self.schedule_settings_save)

        self.csv_log_enabled_checkbox.toggled.connect(self._apply_csv_log_enabled_state)
        self.upscale_backend_combo.currentIndexChanged.connect(self._apply_upscale_backend_state)
        self.enable_dds_staging_checkbox.toggled.connect(self._apply_dds_staging_enabled_state)
        self.png_root_edit.textChanged.connect(lambda *_args: self._apply_upscale_backend_state())
        self.dds_staging_root_edit.textChanged.connect(lambda *_args: self._apply_upscale_backend_state())
        self.output_root_edit.textChanged.connect(lambda *_args: self._apply_upscale_backend_state())
        self.dds_format_mode_combo.currentIndexChanged.connect(self._apply_dds_output_state)
        self.dds_size_mode_combo.currentIndexChanged.connect(self._apply_dds_output_state)
        self.dds_mip_mode_combo.currentIndexChanged.connect(self._apply_dds_output_state)
        self.upscale_texture_preset_combo.currentIndexChanged.connect(self._update_ncnn_preset_hint)
        self.enable_automatic_texture_rules_checkbox.toggled.connect(self._update_ncnn_preset_hint)
        self.enable_unsafe_technical_override_checkbox.toggled.connect(self._update_ncnn_preset_hint)
        self.safe_upscale_wizard_button.clicked.connect(self.open_run_summary)
        self.ncnn_model_refresh_button.clicked.connect(self._refresh_ncnn_model_picker)
        self.ncnn_model_catalog_button.clicked.connect(self.open_ncnn_model_catalog)
        self.ncnn_exe_path_edit.textChanged.connect(self._refresh_ncnn_model_picker)
        self.ncnn_model_dir_edit.textChanged.connect(self._refresh_ncnn_model_picker)
        self.mod_ready_export_browse_button.clicked.connect(self._browse_mod_ready_export_root)
        self.enable_mod_ready_loose_export_checkbox.toggled.connect(self._apply_mod_ready_export_state)
        self.mod_ready_manager_combo.currentIndexChanged.connect(self._apply_mod_ready_manager_profile_state)
        self.compare_sync_pan_checkbox.toggled.connect(self.schedule_settings_save)
        self.compare_preview_size_combo.currentIndexChanged.connect(self._apply_compare_preview_size_mode)
        self.main_tabs.currentChanged.connect(self._handle_main_tab_changed)
        self.texture_tabs.currentChanged.connect(self._handle_tool_group_tab_changed)
        self.assets_tabs.currentChanged.connect(self._handle_tool_group_tab_changed)
        self.research_tabs.currentChanged.connect(self._handle_tool_group_tab_changed)
        self.tools_tabs.currentChanged.connect(self._handle_tool_group_tab_changed)
        self.content_tabs.currentChanged.connect(self._handle_workflow_content_tab_changed)
        self.workflow_splitter.splitterMoved.connect(lambda *_args: self.schedule_settings_save())
        self.workflow_right_splitter.splitterMoved.connect(lambda *_args: self.schedule_settings_save())
        self.compare_splitter.splitterMoved.connect(lambda *_args: self.schedule_settings_save())
        self.archive_splitter.splitterMoved.connect(
            lambda *_args: (self._note_archive_ui_activity(), self.schedule_settings_save())
        )
        self.replace_assistant_tab.main_splitter.splitterMoved.connect(lambda *_args: self.schedule_settings_save())
        self.research_tab.main_splitter.splitterMoved.connect(lambda *_args: self.schedule_settings_save())
        self.research_tab.groups_splitter.splitterMoved.connect(lambda *_args: self.schedule_settings_save())
        self.research_tab.unknown_splitter.splitterMoved.connect(lambda *_args: self.schedule_settings_save())
        self.research_tab.reference_splitter.splitterMoved.connect(lambda *_args: self.schedule_settings_save())
        self.research_tab.analysis_splitter.splitterMoved.connect(lambda *_args: self.schedule_settings_save())
        self.research_tab.notes_splitter.splitterMoved.connect(lambda *_args: self.schedule_settings_save())
        self.text_search_tab.main_splitter.splitterMoved.connect(lambda *_args: self.schedule_settings_save())
        self.setup_section.toggled.connect(self.schedule_settings_save)
        self.paths_section.toggled.connect(self.schedule_settings_save)
        self.archive_locations_section.toggled.connect(self.schedule_settings_save)
        self.settings_section.toggled.connect(self.schedule_settings_save)
        self.dds_output_section.toggled.connect(self.schedule_settings_save)
        self.filters_section.toggled.connect(self.schedule_settings_save)
        self.chainner_section.toggled.connect(self.schedule_settings_save)
        self.filters_edit.textChanged.connect(self.schedule_settings_save)
        self.chainner_override_edit.textChanged.connect(self.schedule_settings_save)
        self.chainner_chain_path_edit.textChanged.connect(self._schedule_chainner_chain_info_refresh)
        self.chainner_override_edit.textChanged.connect(self._schedule_chainner_chain_info_refresh)
        self.workflow_profiles_tree.currentItemChanged.connect(lambda *_args: self._update_workflow_profile_detail_widgets())
        self.workflow_rules_tree.currentItemChanged.connect(lambda *_args: self._update_workflow_rule_detail_widgets())
        self.workflow_matched_files_tree.itemSelectionChanged.connect(self._sync_workflow_editor_state)
        self.workflow_profile_add_button.clicked.connect(self._add_workflow_profile)
        self.workflow_profile_duplicate_button.clicked.connect(self._duplicate_workflow_profile)
        self.workflow_profile_delete_button.clicked.connect(self._delete_workflow_profile)
        self.workflow_rule_add_button.clicked.connect(self._add_workflow_rule)
        self.workflow_rule_duplicate_button.clicked.connect(self._duplicate_workflow_rule)
        self.workflow_rule_delete_button.clicked.connect(self._delete_workflow_rule)
        self.workflow_rule_move_up_button.clicked.connect(lambda: self._move_workflow_rule(-1))
        self.workflow_rule_move_down_button.clicked.connect(lambda: self._move_workflow_rule(1))
        self.workflow_matched_refresh_button.clicked.connect(self._refresh_workflow_matched_files_view)
        self.workflow_assign_profile_button.clicked.connect(self._assign_profile_to_selected_workflow_matches)
        self.workflow_profile_name_edit.editingFinished.connect(self._apply_selected_workflow_profile_edits)
        self.workflow_profile_action_combo.currentIndexChanged.connect(self._apply_selected_workflow_profile_edits)
        self.workflow_profile_format_combo.currentIndexChanged.connect(self._apply_selected_workflow_profile_edits)
        self.workflow_profile_size_combo.currentIndexChanged.connect(self._apply_selected_workflow_profile_edits)
        self.workflow_profile_size_combo.currentIndexChanged.connect(self._set_workflow_profile_custom_controls_state)
        self.workflow_profile_custom_width_spin.valueChanged.connect(self._apply_selected_workflow_profile_edits)
        self.workflow_profile_custom_height_spin.valueChanged.connect(self._apply_selected_workflow_profile_edits)
        self.workflow_profile_mip_combo.currentIndexChanged.connect(self._apply_selected_workflow_profile_edits)
        self.workflow_profile_mip_combo.currentIndexChanged.connect(self._set_workflow_profile_custom_controls_state)
        self.workflow_profile_custom_mip_spin.valueChanged.connect(self._apply_selected_workflow_profile_edits)
        self.workflow_profile_ncnn_model_combo.currentIndexChanged.connect(self._apply_selected_workflow_profile_edits)
        self.workflow_profile_ncnn_scale_combo.currentIndexChanged.connect(self._apply_selected_workflow_profile_edits)
        self.workflow_profile_ncnn_tile_override_checkbox.toggled.connect(self._set_workflow_profile_custom_controls_state)
        self.workflow_profile_ncnn_tile_override_checkbox.toggled.connect(self._apply_selected_workflow_profile_edits)
        self.workflow_profile_ncnn_tile_spin.valueChanged.connect(self._apply_selected_workflow_profile_edits)
        self.workflow_profile_ncnn_extra_args_edit.editingFinished.connect(self._apply_selected_workflow_profile_edits)
        self.workflow_profile_post_correction_combo.currentIndexChanged.connect(self._apply_selected_workflow_profile_edits)
        self.workflow_rule_enabled_checkbox.toggled.connect(self._apply_selected_workflow_rule_edits)
        self.workflow_rule_match_mode_combo.currentIndexChanged.connect(self._apply_selected_workflow_rule_edits)
        self.workflow_rule_pattern_edit.editingFinished.connect(self._apply_selected_workflow_rule_edits)
        self.workflow_rule_profile_combo.currentIndexChanged.connect(self._apply_selected_workflow_rule_edits)
        self.workflow_rule_semantic_combo.currentTextChanged.connect(self._apply_selected_workflow_rule_edits)
        self.workflow_rule_semantic_combo.lineEdit().editingFinished.connect(self._apply_selected_workflow_rule_edits)
        self.workflow_rule_planner_profile_combo.currentIndexChanged.connect(self._apply_selected_workflow_rule_edits)
        self.workflow_rule_colorspace_combo.currentIndexChanged.connect(self._apply_selected_workflow_rule_edits)
        self.workflow_rule_alpha_combo.currentIndexChanged.connect(self._apply_selected_workflow_rule_edits)
        self.workflow_rule_intermediate_combo.currentIndexChanged.connect(self._apply_selected_workflow_rule_edits)
        for widget in (
            self.original_dds_edit,
            self.filters_edit,
            self.png_root_edit,
            self.texture_editor_png_root_edit,
            self.dds_staging_root_edit,
            self.output_root_edit,
            self.texconv_path_edit,
        ):
            widget.textChanged.connect(self._schedule_workflow_match_refresh)
        for checkbox in (
            self.enable_automatic_texture_rules_checkbox,
            self.enable_unsafe_technical_override_checkbox,
            self.enable_dds_staging_checkbox,
        ):
            checkbox.toggled.connect(self._schedule_workflow_match_refresh)
        for combo in (
            self.dds_format_mode_combo,
            self.dds_custom_format_combo,
            self.dds_size_mode_combo,
            self.dds_mip_mode_combo,
            self.upscale_backend_combo,
            self.ncnn_model_combo,
            self.upscale_post_correction_combo,
            self.upscale_texture_preset_combo,
        ):
            combo.currentIndexChanged.connect(self._schedule_workflow_match_refresh)
        for spin in (
            self.dds_custom_width_spin,
            self.dds_custom_height_spin,
            self.dds_custom_mip_spin,
            self.ncnn_scale_spin,
            self.ncnn_tile_size_spin,
        ):
            spin.valueChanged.connect(self._schedule_workflow_match_refresh)

    def _handle_main_tab_changed(self, index: int) -> None:
        current_widget = self._current_navigation_widget()
        if current_widget is not None:
            self._handle_tool_activated(current_widget)
        self._update_window_menu_state()
        self._save_settings()

    def _handle_tool_group_tab_changed(self, _index: int) -> None:
        current_widget = self._current_navigation_widget()
        if current_widget is not None:
            self._handle_tool_activated(current_widget)
        self._update_window_menu_state()
        self._save_settings()
