"""Shell-owned construction for primary workspace tool tabs."""

from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QWidget

_texture_editor_tab_class: type | None = None
_texture_editor_import_error: ModuleNotFoundError | None = None
_texture_editor_import_attempted = False


def _load_texture_editor_tab_class() -> type | None:
    """Load optional texture editor only when the GUI actually builds tabs."""
    global _texture_editor_import_attempted, _texture_editor_import_error, _texture_editor_tab_class
    if _texture_editor_import_attempted:
        return _texture_editor_tab_class
    _texture_editor_import_attempted = True
    try:
        from cdmw.ui.texture_editor_tab import TextureEditorTab
    except ModuleNotFoundError as exc:
        if (exc.name or "") not in {"cv2", "numpy", "PIL"}:
            raise
        _texture_editor_import_error = exc
        _texture_editor_tab_class = None
    else:
        _texture_editor_tab_class = TextureEditorTab
    return _texture_editor_tab_class


class ShellToolTabsMixin:
    """Build secondary tool tabs after archive/texture foundations exist."""

    def _build_shell_tool_tabs(self, pump_startup_splash: Callable[[str], None]) -> None:
        from cdmw.core.archive import ensure_archive_preview_source
        from cdmw.ui.item_icons import ItemIconLibraryTab
        from cdmw.ui.mesh_editor import MeshEditorSessionRequest, MeshEditorTab
        from cdmw.ui.model_library import ModelLibraryTab
        from cdmw.ui.recolor_variants_tab import RecolorVariantsTab
        from cdmw.ui.replace_assistant_tab import ReplaceAssistantTab
        from cdmw.ui.research import ResearchTab
        from cdmw.ui.settings_tab import SettingsTab
        from cdmw.ui.text_search import TextSearchTab
        from cdmw.ui.texture_workflow.unavailable_editor import UnavailableTextureEditorTab

        _ = MeshEditorSessionRequest

        pump_startup_splash("Preparing mesh editor...")
        self.mesh_editor_tab = MeshEditorTab(
            settings=self.settings,
            theme_key=self.current_theme_key,
        )
        self.mesh_editor_tab.status_message_requested.connect(
            lambda message, is_error: self.set_status_message(message, error=is_error)
        )
        self.mesh_editor_tab.modify_original_requested.connect(self._mesh_editor_modify_original_requested)
        self.mesh_editor_tab.import_replacement_requested.connect(self._mesh_editor_import_replacement_requested)
        self.mesh_editor_tab.import_preview_requested.connect(self._mesh_editor_import_preview_requested)
        self.mesh_editor_tab.in_game_swap_requested.connect(self._mesh_editor_in_game_swap_requested)
        self.mesh_editor_tab.open_archive_target_requested.connect(self._mesh_editor_show_archive_target_requested)
        self.assets_tabs.addTab(self.mesh_editor_tab, "Mesh Editor")

        pump_startup_splash("Preparing model library...")
        self.model_library_tab = ModelLibraryTab(
            settings=self.settings,
            base_dir=self.settings_file_path.parent,
            theme_key=self.current_theme_key,
            record_runtime_event=getattr(self, "_record_runtime_event", None),
        )
        self.model_library_tab.status_message_requested.connect(
            lambda message, is_error: self.set_status_message(message, error=is_error)
        )
        self.model_library_tab.import_mesh_requested.connect(
            self._import_local_model_to_current_archive
        )
        self.model_library_tab.preview_mesh_requested.connect(
            self._preview_model_library_mesh
        )
        self.assets_tabs.addTab(self.model_library_tab, "Model Library")

        pump_startup_splash("Preparing research tools...")
        self.text_search_tab = TextSearchTab(
            settings=self.settings,
            base_dir=self.settings_file_path.parent,
            theme_key=self.current_theme_key,
        )
        self.text_search_tab.status_message_requested.connect(
            lambda message, is_error: self.set_status_message(message, error=is_error)
        )
        self.research_tab = ResearchTab(
            settings=self.settings,
            base_dir=self.settings_file_path.parent,
            get_archive_entries=lambda: self.archive_entries,
            get_filtered_archive_entries=lambda: self.archive_filtered_entries,
            get_original_root=lambda: self.original_dds_edit.text(),
            get_output_root=lambda: self.output_root_edit.text(),
            get_texconv_path=lambda: self.texconv_path_edit.text(),
            get_app_config=self.collect_config,
            get_current_archive_path=self.current_archive_path_for_research,
            get_current_text_search_path=self.text_search_tab.current_result_path,
            get_current_compare_path=self.current_compare_path_for_research,
            get_archive_browser_tree_state=lambda: {
                "entries": self.archive_filtered_entries,
                "tree_child_folders": self.archive_tree_child_folders,
                "tree_direct_files": self.archive_tree_direct_files,
                "tree_folder_entry_indexes": self.archive_tree_folder_entry_indexes,
                "tree_folder_preview_stats": self.archive_tree_folder_preview_stats,
                "tree_index_ready": self.archive_tree_index_ready,
            },
        )
        self.research_tab.status_message_requested.connect(
            lambda message, is_error: self.set_status_message(message, error=is_error)
        )
        self.research_tab.focus_archive_browser_requested.connect(
            lambda: self._activate_tool_widget(self.archive_browser_tab)
        )
        self.research_tab.extract_related_set_requested.connect(self.extract_related_archive_set_from_paths)
        self.research_tab.review_reference_in_text_search_requested.connect(
            self._review_reference_in_text_search
        )
        self.research_tabs.addTab(self.research_tab, "Texture Research")
        self.research_tabs.addTab(self.text_search_tab, "Text Search")

        pump_startup_splash("Preparing settings...")
        self.settings_tab = SettingsTab(
            settings=self.settings,
            theme_key=self.current_theme_key,
        )
        self.settings_tab.set_language_options(
            self.ui_localizer.available_languages(),
            current_code=self.ui_localizer.language_code,
        )
        self.settings_tab.add_setup_paths_sections(self.setup_section, self.paths_section)
        self.settings_tab.add_archive_locations_section(self.archive_locations_section)
        self.settings_tab.appearance_change_started.connect(self._handle_appearance_change_started)
        self.settings_tab.appearance_changed.connect(self._handle_appearance_changed)
        self.settings_tab.language_changed.connect(self._handle_language_changed)
        self.settings_tab.export_language_requested.connect(self._export_language_file)
        self.settings_tab.import_language_requested.connect(self._import_language_file)
        self.settings_tab.crash_capture_changed.connect(self._set_crash_capture_enabled)
        self.settings_tab.model_preview_settings_changed.connect(self._handle_model_preview_settings_changed)
        self.settings_tab.archive_performance_settings_changed.connect(
            self._handle_archive_performance_settings_changed
        )
        settings_tab_index = self.main_tabs.addTab(self.settings_tab, "Settings")
        self.main_tabs.setTabVisible(settings_tab_index, False)

        pump_startup_splash("Preparing assistant tools...")
        self.replace_assistant_tab = ReplaceAssistantTab(
            settings=self.settings,
            base_dir=self.settings_file_path.parent,
            get_archive_entries=lambda: self.archive_entries,
            get_original_root=lambda: self.original_dds_edit.text(),
            get_texconv_path=lambda: self.texconv_path_edit.text(),
            get_current_config=self.collect_config,
        )
        self.replace_assistant_tab.status_message_requested.connect(
            lambda message, is_error: self.set_status_message(message, error=is_error)
        )
        self.replace_assistant_tab.open_in_texture_editor_requested.connect(self._open_source_in_texture_editor)
        self.texture_tabs.addTab(self.replace_assistant_tab, "Replacer")

        pump_startup_splash("Preparing recolor variants...")
        self.recolor_variants_tab = RecolorVariantsTab(
            settings=self.settings,
            base_dir=self.settings_file_path.parent,
            get_texconv_path=lambda: self.texconv_path_edit.text(),
        )
        self.recolor_variants_tab.status_message_requested.connect(
            lambda message, is_error: self.set_status_message(message, error=is_error)
        )
        self.recolor_variants_tab.open_recolor_target_in_editor_requested.connect(
            self._open_recolor_variant_target_in_texture_editor
        )
        self.texture_tabs.addTab(self.recolor_variants_tab, "Recolor Variants")

        pump_startup_splash("Preparing texture editor...")
        texture_editor_tab_class = _load_texture_editor_tab_class()
        if texture_editor_tab_class is None:
            self.texture_editor_tab = UnavailableTextureEditorTab(_texture_editor_import_error)
        else:
            self.texture_editor_tab = texture_editor_tab_class(
                settings=self.settings,
                base_dir=self.settings_file_path.parent,
                get_texconv_path=lambda: self.texconv_path_edit.text(),
                get_png_root=lambda: self.png_root_edit.text(),
                get_original_dds_root=lambda: self.original_dds_edit.text(),
                get_archive_entries=lambda: self.archive_entries,
                get_current_config=self.collect_config,
            )
        self.texture_editor_tab.set_ui_translator(self.ui_localizer.translate)
        self.texture_editor_tab.sync_ui_font_from_application()
        self.texture_editor_tab.status_message_requested.connect(
            lambda message, is_error: self.set_status_message(message, error=is_error)
        )
        self.texture_editor_tab.browse_archive_requested.connect(self._show_archive_browser_from_texture_editor)
        self.texture_editor_tab.open_in_compare_requested.connect(self._show_compare_from_texture_editor)
        self.texture_editor_tab.send_to_replace_assistant_requested.connect(
            self._handle_texture_editor_send_to_replace_assistant
        )
        self.texture_editor_tab.send_to_texture_workflow_requested.connect(
            self._handle_texture_editor_send_to_texture_workflow
        )
        self.texture_editor_tab.send_to_item_icons_requested.connect(
            self._handle_texture_editor_send_to_item_icons
        )
        self.texture_tabs.addTab(self.texture_editor_tab, "Editor")

        self.item_icons_tab = ItemIconLibraryTab(
            settings=self.settings,
            base_dir=self.settings_file_path.parent,
            get_archive_entries=lambda: self.archive_entries,
            get_texconv_path=lambda: self.texconv_path_edit.text(),
            resolve_target_template_path=lambda entry: ensure_archive_preview_source(entry)[0],
            get_current_archive_path=self.current_archive_path_for_research,
        )
        self.item_icons_tab.status_message_requested.connect(
            lambda message, is_error: self.set_status_message(message, error=is_error)
        )
        self.item_icons_tab.open_in_texture_editor_requested.connect(self._open_source_in_texture_editor)
        self.item_icons_tab.open_target_in_archive_requested.connect(
            lambda target_path: self._show_archive_browser_from_texture_editor(target_path)
        )
        self.model_library_tab.item_icon_source_generated.connect(
            self._handle_model_library_item_icon_generated
        )
        self.assets_tabs.addTab(self.item_icons_tab, "Icon Creator")

        pump_startup_splash("Preparing package tools...")
        self.mod_package_retrofit_tab = QWidget()
        self.mod_package_retrofit_tab.setObjectName("mod_package_retrofit")
        self._build_mod_package_retrofit_tool(
            self.mod_package_retrofit_tab,
            run_initial_scan=False,
        )
        self.tools_tabs.addTab(self.mod_package_retrofit_tab, "Retrofit/Repackage")

    def _register_shell_tool_tabs(self) -> None:
        self._initialize_archive_cache_status_chip()
        self._register_detachable_tool("texture_workflow", self.workflow_tab, "Texture Workflow")
        self._register_detachable_tool("replace_assistant", self.replace_assistant_tab, "Texture Replacer")
        self._register_detachable_tool("recolor_variants", self.recolor_variants_tab, "Recolor Variants")
        self._register_detachable_tool("texture_editor", self.texture_editor_tab, "Texture Editor")
        self._register_detachable_tool("archive_browser", self.archive_browser_tab, "Archive Browser")
        self._register_detachable_tool("mesh_editor", self.mesh_editor_tab, "Mesh Editor")
        self._register_detachable_tool("model_library", self.model_library_tab, "Model Library")
        self._register_detachable_tool("research", self.research_tab, "Texture Research")
        self._register_detachable_tool("text_search", self.text_search_tab, "Text Search")
        self._register_detachable_tool("item_icons", self.item_icons_tab, "Icon Creator")
        self._register_detachable_tool("mod_package_retrofit", self.mod_package_retrofit_tab, "Retrofit/Repackage")
        self._register_detachable_tool("settings", self.settings_tab, "Settings")
        self._build_window_tool_menu_actions()


__all__ = ["ShellToolTabsMixin"]
