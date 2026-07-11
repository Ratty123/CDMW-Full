"""Settings autosave signal wiring for the shell window."""

from __future__ import annotations

from cdmw.ui.shell.lazy_tool_tab import LazyToolTab


class SettingsAutosaveMixin:
    """Connect shell controls to persisted settings updates."""

    def _connect_auto_save(self) -> None:
        if getattr(self, "_texture_workflow_base_auto_save_connected", False):
            return
        self._texture_workflow_base_auto_save_connected = True
        for line_edit in (
            self.original_dds_edit,
            self.png_root_edit,
            self.texture_editor_png_root_edit,
            self.dds_staging_root_edit,
            self.output_root_edit,
            self.texconv_path_edit,
            self.archive_package_root_edit,
            self.archive_extract_root_edit,
        ):
            line_edit.textChanged.connect(self.schedule_settings_save)

        self.compare_sync_pan_checkbox.toggled.connect(self.schedule_settings_save)
        self.compare_preview_size_combo.currentIndexChanged.connect(self.schedule_settings_save)
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

        def connect_optional_splitters(tab: object, splitter_names: tuple[str, ...]) -> None:
            def connect(widget: object) -> None:
                for name in splitter_names:
                    getattr(widget, name).splitterMoved.connect(lambda *_args: self.schedule_settings_save())

            if isinstance(tab, LazyToolTab):
                tab.when_created(connect)
            else:
                connect(tab)

        connect_optional_splitters(self.replace_assistant_tab, ("main_splitter",))
        connect_optional_splitters(
            self.research_tab,
            (
                "main_splitter",
                "groups_splitter",
                "unknown_splitter",
                "reference_splitter",
                "analysis_splitter",
                "notes_splitter",
            ),
        )
        connect_optional_splitters(self.text_search_tab, ("main_splitter",))
        for section in (
            self.setup_section,
            self.paths_section,
            self.archive_locations_section,
            self.settings_section,
            self.asset_authoring_section,
            self.dds_output_section,
            self.filters_section,
            self.chainner_section,
        ):
            section.toggled.connect(self.schedule_settings_save)
        for widget in (
            self.original_dds_edit,
            self.png_root_edit,
            self.texture_editor_png_root_edit,
            self.dds_staging_root_edit,
            self.output_root_edit,
            self.texconv_path_edit,
        ):
            widget.textChanged.connect(self._schedule_workflow_match_refresh)

        for panel, section in (
            ("settings", self.settings_section),
            ("asset_authoring", self.asset_authoring_section),
            ("dds_output", self.dds_output_section),
            ("filters", self.filters_section),
            ("chainner", self.chainner_section),
        ):
            if section.is_body_built():
                SettingsAutosaveMixin._connect_texture_workflow_panel_auto_save(self, panel)

    def _connect_texture_workflow_panel_auto_save(self, panel: str) -> None:
        connected = getattr(self, "_texture_workflow_connected_panels", None)
        if connected is None:
            connected = self._texture_workflow_connected_panels = set()
        if panel in connected:
            return
        handlers = {
            "asset_authoring": SettingsAutosaveMixin._connect_asset_authoring_panel_auto_save,
            "dds_output": SettingsAutosaveMixin._connect_dds_output_panel_auto_save,
            "filters": SettingsAutosaveMixin._connect_workflow_profiles_panel_auto_save,
            "settings": SettingsAutosaveMixin._connect_workflow_settings_panel_auto_save,
            "chainner": SettingsAutosaveMixin._connect_upscale_panel_auto_save,
        }
        handler = handlers.get(panel)
        if handler is None:
            raise ValueError(f"Unknown Texture Workflow panel: {panel}")
        handler(self)
        connected.add(panel)

    def _connect_asset_authoring_panel_auto_save(self) -> None:
        for line_edit in (
            self.material_maker_project_edit,
            self.material_maker_export_dir_edit,
            self.openimageio_source_path_edit,
            self.openimageio_output_path_edit,
            self.openimageio_compare_path_edit,
        ):
            line_edit.textChanged.connect(self.schedule_settings_save)

    def _connect_workflow_settings_panel_auto_save(self) -> None:
        self.csv_log_path_edit.textChanged.connect(self.schedule_settings_save)
        for checkbox in (
            self.dry_run_checkbox,
            self.enable_incremental_resume_checkbox,
            self.csv_log_enabled_checkbox,
            self.unique_basename_checkbox,
            self.overwrite_existing_checkbox,
        ):
            checkbox.toggled.connect(self.schedule_settings_save)
        self.csv_log_enabled_checkbox.toggled.connect(self._apply_csv_log_enabled_state)

    def _connect_dds_output_panel_auto_save(self) -> None:
        self.enable_dds_staging_checkbox.toggled.connect(self.schedule_settings_save)
        self.enable_dds_staging_checkbox.toggled.connect(self._apply_dds_staging_enabled_state)
        self.enable_dds_staging_checkbox.toggled.connect(self._schedule_workflow_match_refresh)
        for combo in (
            self.dds_format_mode_combo,
            self.dds_custom_format_combo,
            self.dds_size_mode_combo,
            self.dds_mip_mode_combo,
        ):
            combo.currentIndexChanged.connect(self.schedule_settings_save)
            combo.currentIndexChanged.connect(self._schedule_workflow_match_refresh)
        for combo in (self.dds_format_mode_combo, self.dds_size_mode_combo, self.dds_mip_mode_combo):
            combo.currentIndexChanged.connect(self._apply_dds_output_state)
        for spin in (
            self.dds_custom_width_spin,
            self.dds_custom_height_spin,
            self.dds_custom_mip_spin,
        ):
            spin.valueChanged.connect(self.schedule_settings_save)
            spin.valueChanged.connect(self._schedule_workflow_match_refresh)

    def _connect_upscale_panel_auto_save(self) -> None:
        for line_edit in (
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
        ):
            line_edit.textChanged.connect(self.schedule_settings_save)
        for checkbox in (
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
        ):
            checkbox.toggled.connect(self.schedule_settings_save)
        for checkbox in self.mod_ready_profile_checkboxes.values():
            checkbox.toggled.connect(self.schedule_settings_save)
            checkbox.toggled.connect(lambda _checked=False: self._apply_mod_ready_export_state())
        for combo in (
            self.upscale_backend_combo,
            self.ncnn_model_combo,
            self.upscale_post_correction_combo,
            self.upscale_texture_preset_combo,
            self.mod_ready_manager_combo,
            self.mod_ready_structure_combo,
            self.mod_ready_conflict_mode_combo,
        ):
            combo.currentIndexChanged.connect(self.schedule_settings_save)
        for spin in (self.ncnn_scale_spin, self.ncnn_tile_size_spin):
            spin.valueChanged.connect(self.schedule_settings_save)
        self.upscale_backend_combo.currentIndexChanged.connect(self._apply_upscale_backend_state)
        self.upscale_texture_preset_combo.currentIndexChanged.connect(self._update_ncnn_preset_hint)
        self.enable_automatic_texture_rules_checkbox.toggled.connect(self._update_ncnn_preset_hint)
        self.enable_unsafe_technical_override_checkbox.toggled.connect(self._update_ncnn_preset_hint)
        self.safe_upscale_wizard_button.clicked.connect(self.open_run_summary)
        self.validate_chainner_button.clicked.connect(self.validate_chainner_chain)
        self.ncnn_model_refresh_button.clicked.connect(self._refresh_ncnn_model_picker)
        self.ncnn_model_catalog_button.clicked.connect(self.open_ncnn_model_catalog)
        self.ncnn_exe_path_edit.textChanged.connect(self._refresh_ncnn_model_picker)
        self.ncnn_model_dir_edit.textChanged.connect(self._refresh_ncnn_model_picker)
        self.mod_ready_export_browse_button.clicked.connect(self._browse_mod_ready_export_root)
        self.enable_mod_ready_loose_export_checkbox.toggled.connect(self._apply_mod_ready_export_state)
        self.mod_ready_manager_combo.currentIndexChanged.connect(self._apply_mod_ready_manager_profile_state)
        self.chainner_chain_path_edit.textChanged.connect(self._schedule_chainner_chain_info_refresh)
        self.chainner_override_edit.textChanged.connect(self.schedule_settings_save)
        self.chainner_override_edit.textChanged.connect(self._schedule_chainner_chain_info_refresh)
        for path_edit in (self.png_root_edit, self.dds_staging_root_edit, self.output_root_edit):
            path_edit.textChanged.connect(self._apply_upscale_backend_state)
        for widget in (
            self.enable_automatic_texture_rules_checkbox,
            self.enable_unsafe_technical_override_checkbox,
        ):
            widget.toggled.connect(self._schedule_workflow_match_refresh)
        for combo in (
            self.upscale_backend_combo,
            self.ncnn_model_combo,
            self.upscale_post_correction_combo,
            self.upscale_texture_preset_combo,
        ):
            combo.currentIndexChanged.connect(self._schedule_workflow_match_refresh)
        for spin in (self.ncnn_scale_spin, self.ncnn_tile_size_spin):
            spin.valueChanged.connect(self._schedule_workflow_match_refresh)

    def _connect_workflow_profiles_panel_auto_save(self) -> None:
        self.filters_edit.textChanged.connect(self.schedule_settings_save)
        self.filters_edit.textChanged.connect(self._schedule_workflow_match_refresh)
        self.workflow_profiles_tree.currentItemChanged.connect(
            lambda *_args: self._update_workflow_profile_detail_widgets()
        )
        self.workflow_rules_tree.currentItemChanged.connect(
            lambda *_args: self._update_workflow_rule_detail_widgets()
        )
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
        for widget in (
            self.workflow_profile_name_edit,
            self.workflow_profile_ncnn_extra_args_edit,
            self.workflow_rule_pattern_edit,
        ):
            widget.editingFinished.connect(
                self._apply_selected_workflow_rule_edits
                if widget is self.workflow_rule_pattern_edit
                else self._apply_selected_workflow_profile_edits
            )
        for combo in (
            self.workflow_profile_action_combo,
            self.workflow_profile_format_combo,
            self.workflow_profile_size_combo,
            self.workflow_profile_mip_combo,
            self.workflow_profile_ncnn_model_combo,
            self.workflow_profile_ncnn_scale_combo,
            self.workflow_profile_post_correction_combo,
        ):
            combo.currentIndexChanged.connect(self._apply_selected_workflow_profile_edits)
        self.workflow_profile_size_combo.currentIndexChanged.connect(self._set_workflow_profile_custom_controls_state)
        self.workflow_profile_mip_combo.currentIndexChanged.connect(self._set_workflow_profile_custom_controls_state)
        for spin in (
            self.workflow_profile_custom_width_spin,
            self.workflow_profile_custom_height_spin,
            self.workflow_profile_custom_mip_spin,
            self.workflow_profile_ncnn_tile_spin,
        ):
            spin.valueChanged.connect(self._apply_selected_workflow_profile_edits)
        self.workflow_profile_ncnn_tile_override_checkbox.toggled.connect(
            self._set_workflow_profile_custom_controls_state
        )
        self.workflow_profile_ncnn_tile_override_checkbox.toggled.connect(
            self._apply_selected_workflow_profile_edits
        )
        for widget in (
            self.workflow_rule_enabled_checkbox,
        ):
            widget.toggled.connect(self._apply_selected_workflow_rule_edits)
        for combo in (
            self.workflow_rule_match_mode_combo,
            self.workflow_rule_profile_combo,
            self.workflow_rule_planner_profile_combo,
            self.workflow_rule_colorspace_combo,
            self.workflow_rule_alpha_combo,
            self.workflow_rule_intermediate_combo,
        ):
            combo.currentIndexChanged.connect(self._apply_selected_workflow_rule_edits)
        self.workflow_rule_semantic_combo.currentTextChanged.connect(self._apply_selected_workflow_rule_edits)
        self.workflow_rule_semantic_combo.lineEdit().editingFinished.connect(self._apply_selected_workflow_rule_edits)

    def _handle_main_tab_changed(self, index: int) -> None:
        current_widget = self._current_navigation_widget()
        if current_widget is not None:
            self._handle_tool_activated(current_widget)
        self._update_window_menu_state()
        self.schedule_settings_save()

    def _handle_tool_group_tab_changed(self, _index: int) -> None:
        current_widget = self._current_navigation_widget()
        if current_widget is not None:
            self._handle_tool_activated(current_widget)
        self._update_window_menu_state()
        self.schedule_settings_save()
