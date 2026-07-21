"""Main window signal wiring."""

from __future__ import annotations


class ShellSignalWiringMixin:
    """Connect shell-owned actions and widget signals."""

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
        self.quick_start_menu_action.triggered.connect(self.show_quick_start_dialog)
        self.open_documentation_action.triggered.connect(self.show_documentation_dialog)
        self.open_about_action.triggered.connect(self.show_about_dialog)
        self.support_corner_button.clicked.connect(self.show_support_dialog)
        self.scan_button.clicked.connect(self.start_scan)
        self.preview_policy_button.clicked.connect(self.preview_texture_policy)
        self.clear_workflow_roots_button.clicked.connect(self.clear_workflow_roots)
        self.start_button.clicked.connect(self.start_build)
        self.stop_button.clicked.connect(self.stop_build)
        self.open_output_button.clicked.connect(self.open_output_folder)
        self.init_workspace_button.clicked.connect(self.initialize_workspace)
        self.create_folders_button.clicked.connect(self.create_missing_folders)
        self.open_texture_editor_button.clicked.connect(self._browse_texture_editor_source)
        self.download_chainner_button.clicked.connect(self.open_chainner_download_page)
        self.download_ncnn_button.clicked.connect(self.open_realesrgan_ncnn_download_page)
        self.import_ncnn_models_button.clicked.connect(self.import_ncnn_models)
        self.clear_log_button.clicked.connect(self.clear_live_log)
        self.clear_archive_log_button.clicked.connect(self.clear_archive_scan_log)
        self.refresh_compare_button.clicked.connect(self.refresh_compare_list)
        self.archive_package_root_detect_button.clicked.connect(self.autodetect_archive_package_root)
        self.archive_scan_button.clicked.connect(self.scan_archives)
        self.archive_refresh_scan_button.clicked.connect(lambda: self.scan_archives(force_refresh=True))
        self.archive_asset_catalog_button.clicked.connect(self._show_archive_asset_catalog_dialog)
        self.archive_material_finder_button.clicked.connect(self._show_archive_material_finder_dialog)
        self.archive_clear_asset_scope_button.clicked.connect(self._clear_archive_asset_catalog_scope)
        self.archive_extract_selected_button.clicked.connect(self.extract_selected_archive_entries)
        self.archive_extract_filtered_button.clicked.connect(self.extract_filtered_archive_entries)
        self.archive_extract_to_workflow_button.clicked.connect(self.extract_filtered_archive_dds_to_workflow)
        self.archive_open_in_editor_button.clicked.connect(self._open_archive_current_in_texture_editor)
        self.archive_resolve_in_research_button.clicked.connect(self._resolve_archive_current_in_research)
        self.archive_filter_apply_button.clicked.connect(self._apply_archive_filter)
        self.archive_path_search_button.clicked.connect(self._apply_archive_filter)
        self.archive_filter_clear_button.clicked.connect(self._clear_archive_filters)
        self.archive_filter_edit.returnPressed.connect(self._apply_archive_filter)
        self.archive_exclude_filter_edit.returnPressed.connect(self._apply_archive_filter)
        self.archive_package_filter_edit.returnPressed.connect(self._apply_archive_filter)
        self.archive_filter_edit.textChanged.connect(self.schedule_settings_save)
        self.archive_filter_edit.textChanged.connect(self._mark_archive_filters_dirty)
        self.archive_exclude_filter_edit.textChanged.connect(self.schedule_settings_save)
        self.archive_exclude_filter_edit.textChanged.connect(self._mark_archive_filters_dirty)
        self.archive_package_filter_edit.textChanged.connect(self.schedule_settings_save)
        self.archive_package_filter_edit.textChanged.connect(self._mark_archive_filters_dirty)
        self.archive_extension_filter_combo.currentIndexChanged.connect(self.schedule_settings_save)
        self.archive_extension_filter_combo.currentIndexChanged.connect(self._mark_archive_filters_dirty)
        self.archive_extension_filter_combo.currentTextChanged.connect(self._mark_archive_filters_dirty)
        self.archive_role_filter_combo.currentIndexChanged.connect(self.schedule_settings_save)
        self.archive_role_filter_combo.currentIndexChanged.connect(self._mark_archive_filters_dirty)
        self.archive_exclude_common_technical_checkbox.toggled.connect(self.schedule_settings_save)
        self.archive_exclude_common_technical_checkbox.toggled.connect(self._mark_archive_filters_dirty)
        self.archive_min_size_spin.valueChanged.connect(self.schedule_settings_save)
        self.archive_min_size_spin.valueChanged.connect(self._mark_archive_filters_dirty)
        self.archive_previewable_only_checkbox.toggled.connect(self.schedule_settings_save)
        self.archive_previewable_only_checkbox.toggled.connect(self._mark_archive_filters_dirty)
        self.archive_browser_view_mode_combo.currentIndexChanged.connect(self.schedule_settings_save)
        self.archive_browser_view_mode_combo.currentIndexChanged.connect(self._handle_archive_browser_view_mode_changed)
        self.archive_tree.currentItemChanged.connect(self._handle_archive_current_item_change)
        self.archive_tree.itemSelectionChanged.connect(self._schedule_archive_selection_state_update)
        self.archive_tree.customContextMenuRequested.connect(self._show_archive_tree_context_menu)
        self.archive_preview_zoom_fit_button.clicked.connect(self._set_archive_preview_fit_mode)
        self.archive_preview_zoom_100_button.clicked.connect(lambda: self._set_archive_preview_zoom_factor(1.0))
        self.archive_preview_zoom_out_button.clicked.connect(lambda: self._adjust_archive_preview_zoom(-1))
        self.archive_preview_zoom_in_button.clicked.connect(lambda: self._adjust_archive_preview_zoom(1))
        self.archive_model_preview_flip_v_checkbox.toggled.connect(self._handle_archive_model_preview_flip_v_toggled)
        self.archive_model_preview_disable_support_checkbox.toggled.connect(
            self._handle_archive_model_preview_disable_support_maps_toggled
        )
        self.archive_model_preview_refresh_button.clicked.connect(self._force_refresh_current_model_preview_assets)
        self.archive_isolated_renderer_button.clicked.connect(self._open_archive_isolated_d3d11_preview)
        self.archive_model_preview_reset_overrides_button.clicked.connect(
            self._handle_archive_model_preview_reset_overrides
        )
        self.archive_model_preview_settings_button.clicked.connect(self._open_model_preview_settings_dialog)
        self.archive_asset_family_button.clicked.connect(self._open_archive_asset_family_workspace_dialog)
        self.archive_action_preview_button.clicked.connect(self._preview_current_archive_entry)
        self.archive_action_open_preview_window_button.clicked.connect(self._open_current_archive_preview_window)
        self.archive_action_copy_filename_button.clicked.connect(self._copy_current_archive_filename)
        self.archive_action_export_file_button.clicked.connect(self._export_current_archive_file)
        self.archive_action_extract_file_button.clicked.connect(self._extract_current_archive_file)
        self.archive_action_show_only_file_button.clicked.connect(self._scope_current_archive_entry_only)
        self.archive_action_asset_family_button.clicked.connect(self._open_archive_asset_family_workspace_dialog)
        self.archive_action_filter_to_family_button.clicked.connect(self._scope_current_archive_asset_family)
        self.archive_action_export_family_button.clicked.connect(self._export_current_archive_asset_family)
        self.archive_action_source_mix_button.clicked.connect(self._open_current_archive_source_mix_package)
        self.archive_action_character_dependency_button.clicked.connect(
            self._export_current_archive_character_dependency_package
        )
        self.archive_model_export_obj_button.clicked.connect(self._export_current_archive_model)
        self.archive_model_export_fbx_button.clicked.connect(
            lambda: self._export_current_archive_mesh("fbx")
        )
        self.archive_model_import_preview_button.clicked.connect(self._preview_current_archive_mesh_import)
        self.archive_model_import_dds_preview_button.clicked.connect(self._preview_current_archive_mesh_dds_import)
        self.archive_model_import_patch_button.clicked.connect(self._patch_current_archive_mesh_from_obj)
        self.archive_model_modify_original_button.clicked.connect(self._modify_current_archive_original_mesh)
        self.archive_model_swap_in_game_button.clicked.connect(self._swap_current_archive_mesh_with_in_game)
        self.archive_appearance_composite_button.clicked.connect(self._open_current_archive_appearance_composite_preview)
        self.archive_appearance_swap_button.clicked.connect(self._open_current_archive_appearance_swap)
        self.archive_hkx_export_json_button.clicked.connect(self._export_current_archive_hkx_json)
        self.archive_hkx_import_json_button.clicked.connect(self._import_current_archive_hkx_json)
        self.archive_hkx_export_xml_button.clicked.connect(self._export_current_archive_hkx_xml)
        self.archive_hkx_export_havok_xml_view_button.clicked.connect(self._export_current_archive_hkx_havok_xml_view)
        self.archive_hkx_import_xml_button.clicked.connect(self._import_current_archive_hkx_xml)
        self.archive_hkx_edit_button.clicked.connect(self._edit_current_archive_hkx)
        self.archive_hkx_placement_button.clicked.connect(self._open_current_archive_hkx_placement)
        self.archive_hkx_corpus_button.clicked.connect(self._export_hkx_converter_corpus_report)
        self.archive_sidecar_export_json_button.clicked.connect(self._export_current_archive_binary_sidecar_json)
        self.archive_sidecar_inspect_button.clicked.connect(self._inspect_current_archive_binary_sidecar)
        self.archive_sidecar_corpus_button.clicked.connect(self._export_binary_sidecar_corpus_report)
        self.archive_material_values_button.clicked.connect(self._edit_current_archive_material_sidecar)
        self.archive_import_loose_mod_button.clicked.connect(self._open_archive_loose_mod_overlay_dialog)
        self.archive_restore_patch_backup_button.clicked.connect(self._restore_archive_patch_backup_from_ui)
        self.archive_texture_refs_tree.itemSelectionChanged.connect(self._update_archive_texture_reference_action_controls)
        self.archive_texture_refs_tree.itemDoubleClicked.connect(
            lambda _item, _column: self._open_selected_archive_texture_reference()
        )
        self.archive_texture_refs_tree.customContextMenuRequested.connect(
            self._show_archive_texture_reference_context_menu
        )
        for relation_tree in (
            self.archive_asset_map_tree,
            self.archive_asset_uses_tree,
            self.archive_asset_used_by_tree,
        ):
            relation_tree.itemSelectionChanged.connect(self._update_archive_texture_reference_action_controls)
            relation_tree.itemDoubleClicked.connect(
                lambda _item, _column: self._open_selected_archive_texture_reference()
            )
            relation_tree.customContextMenuRequested.connect(
                self._show_archive_texture_reference_context_menu
            )
        self.archive_preview_content_splitter.splitterMoved.connect(self._handle_archive_preview_content_splitter_moved)
        self.archive_preview_loose_toggle_button.clicked.connect(self._toggle_archive_loose_preview)
        self.compare_previous_button.clicked.connect(lambda: self._select_compare_offset(-1))
        self.compare_next_button.clicked.connect(lambda: self._select_compare_offset(1))
        self.compare_mip_details_button.clicked.connect(self._open_compare_in_texture_analysis)
        self.compare_open_in_editor_button.clicked.connect(self._open_compare_in_texture_editor)
        self.compare_sync_pan_checkbox.toggled.connect(self._sync_compare_scroll_positions)
        self.original_compare_zoom_fit_button.clicked.connect(lambda: self._set_compare_fit_mode("original"))
        self.original_compare_zoom_100_button.clicked.connect(lambda: self._set_compare_zoom_factor("original", 1.0))
        self.original_compare_zoom_out_button.clicked.connect(lambda: self._adjust_compare_zoom("original", -1))
        self.original_compare_zoom_in_button.clicked.connect(lambda: self._adjust_compare_zoom("original", 1))
        self.output_compare_zoom_fit_button.clicked.connect(lambda: self._set_compare_fit_mode("output"))
        self.output_compare_zoom_100_button.clicked.connect(lambda: self._set_compare_zoom_factor("output", 1.0))
        self.output_compare_zoom_out_button.clicked.connect(lambda: self._adjust_compare_zoom("output", -1))
        self.output_compare_zoom_in_button.clicked.connect(lambda: self._adjust_compare_zoom("output", 1))
        self.compare_list.currentItemChanged.connect(self._handle_compare_selection_change)
        self._compare_preview_timer.timeout.connect(self._flush_pending_compare_preview_selection)
        self.original_preview_scroll.horizontalScrollBar().valueChanged.connect(
            lambda value: self._sync_compare_scrollbar(
                self.original_preview_scroll.horizontalScrollBar(),
                self.output_preview_scroll.horizontalScrollBar(),
                value,
            )
        )
        self.original_preview_scroll.verticalScrollBar().valueChanged.connect(
            lambda value: self._sync_compare_scrollbar(
                self.original_preview_scroll.verticalScrollBar(),
                self.output_preview_scroll.verticalScrollBar(),
                value,
            )
        )
        self.output_preview_scroll.horizontalScrollBar().valueChanged.connect(
            lambda value: self._sync_compare_scrollbar(
                self.output_preview_scroll.horizontalScrollBar(),
                self.original_preview_scroll.horizontalScrollBar(),
                value,
            )
        )
        self.output_preview_scroll.verticalScrollBar().valueChanged.connect(
            lambda value: self._sync_compare_scrollbar(
                self.output_preview_scroll.verticalScrollBar(),
                self.original_preview_scroll.verticalScrollBar(),
                value,
            )
        )
        self._connect_auto_save()
