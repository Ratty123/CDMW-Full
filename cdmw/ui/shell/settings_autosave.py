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
            self.textures.original_dds_edit,
            self.textures.png_root_edit,
            self.textures.texture_editor_png_root_edit,
            self.textures.dds_staging_root_edit,
            self.textures.output_root_edit,
            self.archive.archive_package_root_edit,
            self.archive.archive_extract_root_edit,
        ):
            line_edit.textChanged.connect(self.schedule_settings_save)

        self.main_tabs.currentChanged.connect(self._handle_main_tab_changed)
        self.textures.job_splitter.splitterMoved.connect(lambda *_args: self.schedule_settings_save())
        self.archive.archive_splitter.splitterMoved.connect(
            lambda *_args: (self.archive._note_archive_ui_activity(), self.schedule_settings_save())
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
            self.textures.setup_section,
            self.textures.paths_section,
            self.archive.archive_locations_section,
            self.textures.settings_section,
            self.textures.asset_authoring_section,
            self.textures.dds_output_section,
            self.textures.filters_section,
            self.textures.chainner_section,
        ):
            section.toggled.connect(self.schedule_settings_save)
        for widget in (
            self.textures.original_dds_edit,
            self.textures.png_root_edit,
            self.textures.texture_editor_png_root_edit,
            self.textures.dds_staging_root_edit,
            self.textures.output_root_edit,
        ):
            widget.textChanged.connect(self.textures._schedule_workflow_match_refresh)

        for panel, section in (
            ("settings", self.textures.settings_section),
            ("asset_authoring", self.textures.asset_authoring_section),
            ("dds_output", self.textures.dds_output_section),
            ("filters", self.textures.filters_section),
            ("chainner", self.textures.chainner_section),
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
            self.textures.openimageio_source_path_edit,
            self.textures.openimageio_output_path_edit,
            self.textures.openimageio_compare_path_edit,
        ):
            line_edit.textChanged.connect(self.schedule_settings_save)

    def _connect_workflow_settings_panel_auto_save(self) -> None:
        self.textures.csv_log_path_edit.textChanged.connect(self.schedule_settings_save)
        for checkbox in (
            self.textures.dry_run_checkbox,
            self.textures.enable_incremental_resume_checkbox,
            self.textures.csv_log_enabled_checkbox,
            self.textures.unique_basename_checkbox,
            self.textures.overwrite_existing_checkbox,
        ):
            checkbox.toggled.connect(self.schedule_settings_save)
        self.textures.csv_log_enabled_checkbox.toggled.connect(self._apply_csv_log_enabled_state)

    def _connect_dds_output_panel_auto_save(self) -> None:
        self.textures.enable_dds_staging_checkbox.toggled.connect(self.schedule_settings_save)
        self.textures.enable_dds_staging_checkbox.toggled.connect(self.textures._apply_dds_staging_enabled_state)
        self.textures.enable_dds_staging_checkbox.toggled.connect(self.textures._schedule_workflow_match_refresh)
        for combo in (
            self.textures.dds_format_mode_combo,
            self.textures.dds_custom_format_combo,
            self.textures.dds_size_mode_combo,
            self.textures.dds_mip_mode_combo,
        ):
            combo.currentIndexChanged.connect(self.schedule_settings_save)
            combo.currentIndexChanged.connect(self.textures._schedule_workflow_match_refresh)
        for combo in (self.textures.dds_format_mode_combo, self.textures.dds_size_mode_combo, self.textures.dds_mip_mode_combo):
            combo.currentIndexChanged.connect(self.textures._apply_dds_output_state)
        for spin in (
            self.textures.dds_custom_width_spin,
            self.textures.dds_custom_height_spin,
            self.textures.dds_custom_mip_spin,
        ):
            spin.valueChanged.connect(self.schedule_settings_save)
            spin.valueChanged.connect(self.textures._schedule_workflow_match_refresh)

    def _connect_upscale_panel_auto_save(self) -> None:
        for line_edit in (
            self.textures.chainner_exe_path_edit,
            self.textures.chainner_chain_path_edit,
            self.textures.ncnn_exe_path_edit,
            self.textures.ncnn_model_dir_edit,
            self.textures.ncnn_extra_args_edit,
            self.textures.mod_ready_export_root_edit,
            self.textures.mod_ready_package_title_edit,
            self.textures.mod_ready_package_version_edit,
            self.textures.mod_ready_package_author_edit,
            self.textures.mod_ready_package_description_edit,
            self.textures.mod_ready_package_nexus_url_edit,
            self.textures.mod_ready_target_language_edit,
        ):
            line_edit.textChanged.connect(self.schedule_settings_save)
        for checkbox in (
            self.textures.enable_automatic_texture_rules_checkbox,
            self.textures.enable_unsafe_technical_override_checkbox,
            self.textures.retry_smaller_tile_checkbox,
            self.textures.enable_mod_ready_loose_export_checkbox,
            self.textures.mod_ready_create_no_encrypt_checkbox,
            self.textures.mod_ready_manifest_checkbox,
            self.textures.mod_ready_mod_json_checkbox,
            self.textures.mod_ready_modinfo_checkbox,
            self.textures.mod_ready_info_json_checkbox,
            self.textures.mod_ready_zip_checkbox,
        ):
            checkbox.toggled.connect(self.schedule_settings_save)
        for checkbox in self.textures.mod_ready_profile_checkboxes.values():
            checkbox.toggled.connect(self.schedule_settings_save)
            checkbox.toggled.connect(lambda _checked=False: self.textures._apply_mod_ready_export_state())
        for combo in (
            self.textures.upscale_backend_combo,
            self.textures.ncnn_model_combo,
            self.textures.upscale_post_correction_combo,
            self.textures.upscale_texture_preset_combo,
            self.textures.mod_ready_manager_combo,
            self.textures.mod_ready_structure_combo,
            self.textures.mod_ready_conflict_mode_combo,
        ):
            combo.currentIndexChanged.connect(self.schedule_settings_save)
        for spin in (self.textures.ncnn_scale_spin, self.textures.ncnn_tile_size_spin):
            spin.valueChanged.connect(self.schedule_settings_save)
        self.textures.upscale_backend_combo.currentIndexChanged.connect(self.textures._apply_upscale_backend_state)
        self.textures.upscale_texture_preset_combo.currentIndexChanged.connect(self.textures._update_ncnn_preset_hint)
        self.textures.enable_automatic_texture_rules_checkbox.toggled.connect(self.textures._update_ncnn_preset_hint)
        self.textures.enable_unsafe_technical_override_checkbox.toggled.connect(self.textures._update_ncnn_preset_hint)
        self.textures.safe_upscale_wizard_button.clicked.connect(self.textures.open_run_summary)
        self.textures.validate_chainner_button.clicked.connect(self.validate_chainner_chain)
        self.textures.ncnn_model_refresh_button.clicked.connect(self.textures._refresh_ncnn_model_picker)
        self.textures.ncnn_model_catalog_button.clicked.connect(self.textures.open_ncnn_model_catalog)
        self.textures.ncnn_exe_path_edit.textChanged.connect(self.textures._refresh_ncnn_model_picker)
        self.textures.ncnn_model_dir_edit.textChanged.connect(self.textures._refresh_ncnn_model_picker)
        self.textures.mod_ready_export_browse_button.clicked.connect(self._browse_mod_ready_export_root)
        self.textures.enable_mod_ready_loose_export_checkbox.toggled.connect(self.textures._apply_mod_ready_export_state)
        self.textures.mod_ready_manager_combo.currentIndexChanged.connect(self.textures._apply_mod_ready_manager_profile_state)
        self.textures.chainner_chain_path_edit.textChanged.connect(self.textures._schedule_chainner_chain_info_refresh)
        self.textures.chainner_override_edit.textChanged.connect(self.schedule_settings_save)
        self.textures.chainner_override_edit.textChanged.connect(self.textures._schedule_chainner_chain_info_refresh)
        for path_edit in (self.textures.png_root_edit, self.textures.dds_staging_root_edit, self.textures.output_root_edit):
            path_edit.textChanged.connect(self.textures._apply_upscale_backend_state)
        for widget in (
            self.textures.enable_automatic_texture_rules_checkbox,
            self.textures.enable_unsafe_technical_override_checkbox,
        ):
            widget.toggled.connect(self.textures._schedule_workflow_match_refresh)
        for combo in (
            self.textures.upscale_backend_combo,
            self.textures.ncnn_model_combo,
            self.textures.upscale_post_correction_combo,
            self.textures.upscale_texture_preset_combo,
        ):
            combo.currentIndexChanged.connect(self.textures._schedule_workflow_match_refresh)
        for spin in (self.textures.ncnn_scale_spin, self.textures.ncnn_tile_size_spin):
            spin.valueChanged.connect(self.textures._schedule_workflow_match_refresh)

    def _connect_workflow_profiles_panel_auto_save(self) -> None:
        self.textures.filters_edit.textChanged.connect(self.schedule_settings_save)
        self.textures.filters_edit.textChanged.connect(self.textures._schedule_workflow_match_refresh)
        self.textures.workflow_profiles_tree.currentItemChanged.connect(
            lambda *_args: self.textures._update_workflow_profile_detail_widgets()
        )
        self.textures.workflow_rules_tree.currentItemChanged.connect(
            lambda *_args: self.textures._update_workflow_rule_detail_widgets()
        )
        self.textures.workflow_matched_files_tree.itemSelectionChanged.connect(self.textures._sync_workflow_editor_state)
        self.textures.workflow_profile_add_button.clicked.connect(self.textures._add_workflow_profile)
        self.textures.workflow_profile_duplicate_button.clicked.connect(self.textures._duplicate_workflow_profile)
        self.textures.workflow_profile_delete_button.clicked.connect(self.textures._delete_workflow_profile)
        self.textures.workflow_rule_add_button.clicked.connect(self.textures._add_workflow_rule)
        self.textures.workflow_rule_duplicate_button.clicked.connect(self.textures._duplicate_workflow_rule)
        self.textures.workflow_rule_delete_button.clicked.connect(self.textures._delete_workflow_rule)
        self.textures.workflow_rule_move_up_button.clicked.connect(lambda: self.textures._move_workflow_rule(-1))
        self.textures.workflow_rule_move_down_button.clicked.connect(lambda: self.textures._move_workflow_rule(1))
        self.textures.workflow_matched_refresh_button.clicked.connect(self.textures._refresh_workflow_matched_files_view)
        self.textures.workflow_assign_profile_button.clicked.connect(self.textures._assign_profile_to_selected_workflow_matches)
        for widget in (
            self.textures.workflow_profile_name_edit,
            self.textures.workflow_profile_ncnn_extra_args_edit,
            self.textures.workflow_rule_pattern_edit,
        ):
            widget.editingFinished.connect(
                self.textures._apply_selected_workflow_rule_edits
                if widget is self.textures.workflow_rule_pattern_edit
                else self.textures._apply_selected_workflow_profile_edits
            )
        for combo in (
            self.textures.workflow_profile_action_combo,
            self.textures.workflow_profile_format_combo,
            self.textures.workflow_profile_size_combo,
            self.textures.workflow_profile_mip_combo,
            self.textures.workflow_profile_ncnn_model_combo,
            self.textures.workflow_profile_ncnn_scale_combo,
            self.textures.workflow_profile_post_correction_combo,
        ):
            combo.currentIndexChanged.connect(self.textures._apply_selected_workflow_profile_edits)
        self.textures.workflow_profile_size_combo.currentIndexChanged.connect(self.textures._set_workflow_profile_custom_controls_state)
        self.textures.workflow_profile_mip_combo.currentIndexChanged.connect(self.textures._set_workflow_profile_custom_controls_state)
        for spin in (
            self.textures.workflow_profile_custom_width_spin,
            self.textures.workflow_profile_custom_height_spin,
            self.textures.workflow_profile_custom_mip_spin,
            self.textures.workflow_profile_ncnn_tile_spin,
        ):
            spin.valueChanged.connect(self.textures._apply_selected_workflow_profile_edits)
        self.textures.workflow_profile_ncnn_tile_override_checkbox.toggled.connect(
            self.textures._set_workflow_profile_custom_controls_state
        )
        self.textures.workflow_profile_ncnn_tile_override_checkbox.toggled.connect(
            self.textures._apply_selected_workflow_profile_edits
        )
        for widget in (
            self.textures.workflow_rule_enabled_checkbox,
        ):
            widget.toggled.connect(self.textures._apply_selected_workflow_rule_edits)
        for combo in (
            self.textures.workflow_rule_match_mode_combo,
            self.textures.workflow_rule_profile_combo,
            self.textures.workflow_rule_planner_profile_combo,
            self.textures.workflow_rule_colorspace_combo,
            self.textures.workflow_rule_alpha_combo,
            self.textures.workflow_rule_intermediate_combo,
        ):
            combo.currentIndexChanged.connect(self.textures._apply_selected_workflow_rule_edits)
        self.textures.workflow_rule_semantic_combo.currentTextChanged.connect(self.textures._apply_selected_workflow_rule_edits)
        self.textures.workflow_rule_semantic_combo.lineEdit().editingFinished.connect(self.textures._apply_selected_workflow_rule_edits)

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
