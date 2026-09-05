"""Main window signal wiring."""

from __future__ import annotations


class ShellSignalWiringMixin:
    """Connect shell-owned actions and widget signals."""

    def _connect_archive_mesh_import_signals(self) -> None:
        return None

    def _connect_shell_signals(self) -> None:
        self.export_profile_action.triggered.connect(self.export_profile)
        self.import_profile_action.triggered.connect(self.import_profile)
        self.mod_package_tool_action.triggered.connect(lambda _checked=False: self._activate_tool_widget(self.mod_package_retrofit_tab))
        self.detach_current_tab_action.triggered.connect(self._detach_current_tool_tab)
        self.attach_current_tool_action.triggered.connect(self._attach_current_tool_tab)
        self.attach_all_tools_action.triggered.connect(self._attach_all_detached_tools)
        self.export_diagnostics_action.triggered.connect(self.export_diagnostic_bundle)
        self.copy_problem_summary_action.triggered.connect(self.copy_latest_problem_summary)
        self.open_crash_reports_action.triggered.connect(self.open_crash_reports_folder)
        self.open_settings_action.triggered.connect(self.show_settings)
        self.open_documentation_action.triggered.connect(self.show_documentation_dialog)
        self.open_about_action.triggered.connect(self.show_about_dialog)
        self.support_corner_button.clicked.connect(self.show_support_dialog)
        self.textures.scan_button.clicked.connect(self.textures.start_scan)
        self.textures.preview_policy_button.clicked.connect(self.textures.preview_texture_policy)
        self.textures.clear_workflow_roots_button.clicked.connect(self.clear_workflow_roots)
        self.textures.start_button.clicked.connect(self.textures.start_build)
        self.textures.stop_button.clicked.connect(self.textures.stop_build)
        self.textures.open_output_button.clicked.connect(self.textures.open_output_folder)
        self.textures.init_workspace_button.clicked.connect(self.initialize_workspace)
        self.textures.create_folders_button.clicked.connect(self.create_missing_folders)
        self.textures.open_texture_editor_button.clicked.connect(self.textures._browse_texture_editor_source)
        self.textures.download_chainner_button.clicked.connect(self.open_chainner_download_page)
        self.textures.download_ncnn_button.clicked.connect(self.open_realesrgan_ncnn_download_page)
        self.textures.import_ncnn_models_button.clicked.connect(self.import_ncnn_models)
        self.textures.clear_log_button.clicked.connect(self.clear_live_log)
        self.archive.clear_archive_log_button.clicked.connect(self.clear_archive_scan_log)
        self.archive.archive_package_root_detect_button.clicked.connect(self.autodetect_archive_package_root)
        self.archive.archive_scan_button.clicked.connect(self.archive.scan_archives)
        self.archive.archive_refresh_scan_button.clicked.connect(lambda: self.archive.scan_archives(force_refresh=True))
        self.archive.archive_asset_catalog_button.clicked.connect(self.archive._show_archive_asset_catalog_dialog)
        self.archive.archive_clear_asset_scope_button.clicked.connect(self.archive._clear_archive_asset_catalog_scope)
        self.archive.archive_extract_selected_button.clicked.connect(self.archive.extract_selected_archive_entries)
        self.archive.archive_extract_filtered_button.clicked.connect(self.archive.extract_filtered_archive_entries)
        self.archive.archive_resolve_in_research_button.clicked.connect(self.textures._resolve_archive_current_in_research)
        self.archive.archive_filter_apply_button.clicked.connect(self.archive._apply_archive_filter)
        self.archive.archive_path_search_button.clicked.connect(self.archive._apply_archive_filter)
        self.archive.archive_filter_clear_button.clicked.connect(self.archive._clear_archive_filters)
        self.archive.archive_filter_edit.returnPressed.connect(self.archive._apply_archive_filter)
        self.archive.archive_exclude_filter_edit.returnPressed.connect(self.archive._apply_archive_filter)
        self.archive.archive_package_filter_edit.returnPressed.connect(self.archive._apply_archive_filter)
        self.archive.archive_filter_edit.textChanged.connect(self.schedule_settings_save)
        self.archive.archive_filter_edit.textChanged.connect(self.archive._mark_archive_filters_dirty)
        self.archive.archive_exclude_filter_edit.textChanged.connect(self.schedule_settings_save)
        self.archive.archive_exclude_filter_edit.textChanged.connect(self.archive._mark_archive_filters_dirty)
        self.archive.archive_package_filter_edit.textChanged.connect(self.schedule_settings_save)
        self.archive.archive_package_filter_edit.textChanged.connect(self.archive._mark_archive_filters_dirty)
        self.archive.archive_extension_filter_combo.currentIndexChanged.connect(self.schedule_settings_save)
        self.archive.archive_extension_filter_combo.currentIndexChanged.connect(self.archive._mark_archive_filters_dirty)
        self.archive.archive_extension_filter_combo.currentTextChanged.connect(self.archive._mark_archive_filters_dirty)
        self.archive.archive_role_filter_combo.currentIndexChanged.connect(self.schedule_settings_save)
        self.archive.archive_role_filter_combo.currentIndexChanged.connect(self.archive._mark_archive_filters_dirty)
        self.archive.archive_exclude_common_technical_checkbox.toggled.connect(self.schedule_settings_save)
        self.archive.archive_exclude_common_technical_checkbox.toggled.connect(self.archive._mark_archive_filters_dirty)
        self.archive.archive_min_size_spin.valueChanged.connect(self.schedule_settings_save)
        self.archive.archive_min_size_spin.valueChanged.connect(self.archive._mark_archive_filters_dirty)
        self.archive.archive_previewable_only_checkbox.toggled.connect(self.schedule_settings_save)
        self.archive.archive_previewable_only_checkbox.toggled.connect(self.archive._mark_archive_filters_dirty)
        self.archive.archive_browser_view_mode_combo.currentIndexChanged.connect(self.schedule_settings_save)
        self.archive.archive_browser_view_mode_combo.currentIndexChanged.connect(self.archive._handle_archive_browser_view_mode_changed)
        self.archive.archive_tree.currentItemChanged.connect(self.archive._handle_archive_current_item_change)
        self.archive.archive_tree.itemSelectionChanged.connect(self.archive._schedule_archive_selection_state_update)
        self.archive.archive_tree.customContextMenuRequested.connect(self.archive._show_archive_tree_context_menu)
        self.archive.archive_preview_zoom_fit_button.clicked.connect(self.archive._set_archive_preview_fit_mode)
        self.archive.archive_preview_zoom_100_button.clicked.connect(lambda: self.archive._set_archive_preview_zoom_factor(1.0))
        self.archive.archive_preview_zoom_out_button.clicked.connect(lambda: self.archive._adjust_archive_preview_zoom(-1))
        self.archive.archive_preview_zoom_in_button.clicked.connect(lambda: self.archive._adjust_archive_preview_zoom(1))
        self.archive.archive_model_preview_flip_v_checkbox.toggled.connect(self.archive._handle_archive_model_preview_flip_v_toggled)
        self.archive.archive_model_preview_disable_support_checkbox.toggled.connect(
            self.archive._handle_archive_model_preview_disable_support_maps_toggled
        )
        self.archive.archive_model_preview_refresh_button.clicked.connect(self.archive._force_refresh_current_model_preview_assets)
        self.archive.archive_isolated_renderer_button.toggled.connect(lambda _checked=False: self.archive._open_archive_isolated_d3d11_preview())
        self.archive.archive_model_preview_reset_overrides_button.clicked.connect(
            self.archive._handle_archive_model_preview_reset_overrides
        )
        self.archive.archive_model_preview_settings_button.clicked.connect(self.archive._open_model_preview_settings_dialog)
        self.archive.archive_asset_family_button.toggled.connect(self.archive._open_archive_asset_family_workspace_dialog)
        self.archive.archive_action_preview_button.clicked.connect(self.archive._preview_current_archive_entry)
        self.archive.archive_action_open_preview_window_button.clicked.connect(self.archive._open_current_archive_preview_window)
        self.archive.archive_action_copy_filename_button.clicked.connect(self.archive._copy_current_archive_filename)
        self.archive.archive_action_export_file_button.clicked.connect(self.archive._export_current_archive_file)
        self.archive.archive_action_extract_file_button.clicked.connect(self.archive._extract_current_archive_file)
        self.archive.archive_action_show_only_file_button.clicked.connect(self.archive._scope_current_archive_entry_only)
        self.archive.archive_action_asset_family_button.clicked.connect(
            lambda _checked=False: self.archive._open_archive_asset_family_workspace_dialog(
                self.archive._current_archive_entry()
            )
        )
        self.archive.archive_action_filter_to_family_button.clicked.connect(self.archive._scope_current_archive_asset_family)
        self.archive.archive_action_export_family_button.clicked.connect(self.archive._export_current_archive_asset_family)
        self.archive.archive_action_character_dependency_button.clicked.connect(
            self.archive._export_current_archive_character_dependency_package
        )
        self.archive.archive_model_export_obj_button.clicked.connect(self.archive._export_current_archive_model)
        self.archive.archive_model_export_fbx_button.clicked.connect(
            lambda: self._export_current_archive_mesh("fbx")
        )
        self.archive.archive_model_open_mesh_editor_button.clicked.connect(self._open_current_archive_mesh_editor)
        self.archive.archive_appearance_composite_button.clicked.connect(self.archive._open_current_archive_appearance_composite_preview)
        self.archive.archive_hkx_export_json_button.clicked.connect(self.archive._export_current_archive_hkx_json)
        self.archive.archive_hkx_import_json_button.clicked.connect(self.archive._import_current_archive_hkx_json)
        self.archive.archive_hkx_export_xml_button.clicked.connect(self.archive._export_current_archive_hkx_xml)
        self.archive.archive_hkx_export_havok_xml_view_button.clicked.connect(self.archive._export_current_archive_hkx_havok_xml_view)
        self.archive.archive_hkx_import_xml_button.clicked.connect(self.archive._import_current_archive_hkx_xml)
        self.archive.archive_hkx_edit_button.clicked.connect(self.archive._edit_current_archive_hkx)
        self.archive.archive_hkx_placement_button.clicked.connect(self.archive._open_current_archive_hkx_placement)
        self.archive.archive_hkx_corpus_button.clicked.connect(self.archive._export_hkx_converter_corpus_report)
        self.archive.archive_sidecar_export_json_button.clicked.connect(self.archive._export_current_archive_binary_sidecar_json)
        self.archive.archive_sidecar_inspect_button.clicked.connect(self.archive._inspect_current_archive_binary_sidecar)
        self.archive.archive_sidecar_corpus_button.clicked.connect(self.archive._export_binary_sidecar_corpus_report)
        self.archive.archive_import_loose_mod_button.clicked.connect(self.archive._open_archive_loose_mod_overlay_dialog)
        self.archive.archive_restore_patch_backup_button.clicked.connect(self.archive._restore_archive_patch_backup_from_ui)
        self.archive.archive_texture_refs_tree.itemSelectionChanged.connect(self.archive._update_archive_texture_reference_action_controls)
        self.archive.archive_texture_refs_tree.itemDoubleClicked.connect(
            lambda _item, _column: self.archive._open_selected_archive_texture_reference()
        )
        self.archive.archive_texture_refs_tree.customContextMenuRequested.connect(
            self.archive._show_archive_texture_reference_context_menu
        )
        for relation_tree in (
            self.archive.archive_asset_map_tree,
            self.archive.archive_asset_uses_tree,
            self.archive.archive_asset_used_by_tree,
        ):
            relation_tree.itemSelectionChanged.connect(self.archive._update_archive_texture_reference_action_controls)
            relation_tree.itemDoubleClicked.connect(
                lambda _item, _column: self.archive._open_selected_archive_texture_reference()
            )
            relation_tree.customContextMenuRequested.connect(
                self.archive._show_archive_texture_reference_context_menu
            )
        self.archive.archive_preview_content_splitter.splitterMoved.connect(self.archive._handle_archive_preview_content_splitter_moved)
        self.archive.archive_preview_loose_toggle_button.clicked.connect(self.archive._toggle_archive_loose_preview)
        self._connect_auto_save()
