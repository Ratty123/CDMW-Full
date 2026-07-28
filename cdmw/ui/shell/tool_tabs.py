"""Shell-owned construction for primary workspace tool tabs."""

from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QApplication, QWidget

from cdmw.ui.shell.lazy_tool_tab import LazyToolTab, as_label, created_tool_widget


_texture_editor_tab_class: type | None = None
_texture_editor_import_error: ModuleNotFoundError | None = None
_texture_editor_import_attempted = False


def _load_texture_editor_tab_class() -> type | None:
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
    """Register optional tools cheaply; build each tool on first use."""

    def _add_lazy_shell_tool(
        self,
        tabs: object,
        title: str,
        key: str,
        factory: Callable[[], QWidget],
        *,
        index: int | None = None,
    ) -> LazyToolTab:
        container = LazyToolTab(factory)
        container.setObjectName(key)
        container.when_created(self._finish_lazy_shell_tool)
        if index is None:
            tabs.addTab(container, as_label(title))
        else:
            tabs.insertTab(index, container, as_label(title))
        return container

    def _finish_lazy_shell_tool(self, widget: QWidget) -> None:
        if self.ui_localizer.language_code != "en":
            self.ui_localizer.apply(widget)
        from cdmw.ui.shell.theme_controller import apply_window_ui_fonts

        app = QApplication.instance()
        if app is not None:
            apply_window_ui_fonts(widget, app, settings=self.settings)
        self._cache_responsive_control_widgets()
        self._apply_responsive_window_defaults(
            apply_expensive_metrics=False,
            adjust_window_geometry=False,
        )

    def _create_mesh_editor_tab(self) -> QWidget:
        from cdmw.domain.archives.constants import ARCHIVE_MESH_EXTENSIONS
        from cdmw.ui.mesh_editor.tab import MeshEditorTab

        tab = MeshEditorTab(
            settings=self.settings,
            theme_key=self.current_theme_key,
            get_archive_texture_entries_by_normalized_path=lambda: getattr(
                self, "archive_entries_by_normalized_path", {}
            )
            or {},
            get_archive_texture_entries_by_basename=lambda: getattr(
                self, "archive_entries_by_basename", {}
            )
            or {},
        )
        tab.status_message_requested.connect(
            lambda message, is_error: self.set_status_message(message, error=is_error)
        )
        runtime_recorder = getattr(self, "_record_runtime_event", None)
        if callable(runtime_recorder):
            tab.runtime_event_requested.connect(
                lambda event, fields, sink=runtime_recorder: sink(event, **dict(fields or {}))
            )
        tab.modify_original_requested.connect(self._mesh_editor_modify_original_requested)
        tab.import_replacement_requested.connect(self._mesh_editor_import_replacement_requested)
        tab.import_preview_requested.connect(self._mesh_editor_import_preview_requested)
        tab.preview_rebuilt_asset_requested.connect(self._mesh_editor_preview_rebuilt_asset_requested)
        tab.package_rebuilt_asset_requested.connect(self._mesh_editor_package_rebuilt_asset_requested)
        tab.in_game_swap_requested.connect(self._mesh_editor_in_game_swap_requested)
        tab.open_archive_target_requested.connect(self._mesh_editor_show_archive_target_requested)
        tab.mesh_action_requested.connect(self._mesh_editor_action_requested)
        tab.open_texture_source_requested.connect(self._open_source_in_texture_editor)
        current_entry = self._current_archive_entry()
        tab.set_archive_selection(
            current_entry
            if current_entry is not None and current_entry.extension in ARCHIVE_MESH_EXTENSIONS
            else None
        )
        return tab

    def _create_model_library_tab(self) -> QWidget:
        from cdmw.ui.model_library import ModelLibraryTab

        tab = ModelLibraryTab(
            settings=self.settings,
            base_dir=self.settings_file_path.parent,
            theme_key=self.current_theme_key,
            record_runtime_event=getattr(self, "_record_runtime_event", None),
            model_library_service=self.app_context.services.require_model_library(),
        )
        tab.status_message_requested.connect(
            lambda message, is_error: self.set_status_message(message, error=is_error)
        )
        tab.import_mesh_requested.connect(self._import_local_model_to_current_archive)
        tab.preview_mesh_requested.connect(self._preview_model_library_mesh)
        tab.item_icon_source_generated.connect(self._handle_model_library_item_icon_generated)
        return tab

    def _create_text_search_tab(self) -> QWidget:
        from cdmw.ui.text_search import TextSearchTab

        tab = TextSearchTab(
            settings=self.settings,
            base_dir=self.settings_file_path.parent,
            theme_key=self.current_theme_key,
            archive_catalogue_service=getattr(self, "archive_catalogue_service", None),
        )
        tab.status_message_requested.connect(
            lambda message, is_error: self.set_status_message(message, error=is_error)
        )
        remote_bridge = getattr(self, "archive_remote_bridge", None)
        if remote_bridge is not None and remote_bridge.displays_v2 and remote_bridge.current_session is not None:
            tab.set_archive_catalogue_session(remote_bridge.current_session)
        else:
            tab.set_archive_entries(
                getattr(self, "archive_entries", []),
                self.archive_package_root_edit.text().strip(),
            )
        return tab

    def _publish_archive_catalogue_session_to_consumers(
        self,
        session: object,
        query_handle: object = None,
    ) -> None:
        for tab_name in ("text_search_tab", "replace_assistant_tab"):
            tab = created_tool_widget(getattr(self, tab_name, None))
            if tab is None:
                continue
            setter = getattr(tab, "set_archive_catalogue_session", None)
            if callable(setter):
                setter(session)
        research_tab = created_tool_widget(getattr(self, "research_tab", None))
        research_setter = getattr(research_tab, "set_archive_catalogue_context", None)
        if callable(research_setter):
            research_setter(session, query_handle)

    def _research_archive_browser_tree_state(self) -> dict[str, object]:
        remote_bridge = getattr(self, "archive_remote_bridge", None)
        if remote_bridge is not None and remote_bridge.displays_v2:
            return {}
        return {
            "entries": self.archive_filtered_entries,
            "tree_child_folders": self.archive_tree_child_folders,
            "tree_direct_files": self.archive_tree_direct_files,
            "tree_folder_entry_indexes": self.archive_tree_folder_entry_indexes,
            "tree_folder_preview_stats": self.archive_tree_folder_preview_stats,
            "tree_index_ready": self.archive_tree_index_ready,
        }

    def _create_research_tab(self) -> QWidget:
        from cdmw.ui.research import ResearchTab

        tab = ResearchTab(
            settings=self.settings,
            base_dir=self.settings_file_path.parent,
            get_archive_entries=lambda: self.archive_entries,
            get_filtered_archive_entries=lambda: self.archive_filtered_entries,
            get_original_root=lambda: self.original_dds_edit.text(),
            get_output_root=lambda: self.output_root_edit.text(),
            get_app_config=self.collect_config,
            get_current_archive_path=self.current_archive_path_for_research,
            get_current_text_search_path=lambda: self.text_search_tab.current_result_path(),
            get_current_compare_path=self.current_compare_path_for_research,
            get_archive_browser_tree_state=self._research_archive_browser_tree_state,
            archive_catalogue_service=getattr(self, "archive_catalogue_service", None),
        )
        tab.status_message_requested.connect(
            lambda message, is_error: self.set_status_message(message, error=is_error)
        )
        tab.focus_archive_browser_requested.connect(lambda: self._activate_tool_widget(self.archive_browser_tab))
        tab.extract_related_set_requested.connect(self.extract_related_archive_set_from_paths)
        tab.review_reference_in_text_search_requested.connect(self._review_reference_in_text_search)
        remote_bridge = getattr(self, "archive_remote_bridge", None)
        if remote_bridge is not None and remote_bridge.displays_v2 and remote_bridge.current_session is not None:
            tab.set_archive_catalogue_context(remote_bridge.current_session, remote_bridge.model.query_handle)
        return tab

    def _create_replace_assistant_tab(self) -> QWidget:
        from cdmw.ui.replace_assistant_tab import ReplaceAssistantTab

        tab = ReplaceAssistantTab(
            settings=self.settings,
            base_dir=self.settings_file_path.parent,
            get_archive_entries=lambda: self.archive_entries,
            get_original_root=lambda: self.original_dds_edit.text(),
            get_current_config=self.collect_config,
            archive_catalogue_service=getattr(self, "archive_catalogue_service", None),
        )
        tab.status_message_requested.connect(
            lambda message, is_error: self.set_status_message(message, error=is_error)
        )
        tab.open_in_texture_editor_requested.connect(self._open_source_in_texture_editor)
        remote_bridge = getattr(self, "archive_remote_bridge", None)
        if remote_bridge is not None and remote_bridge.displays_v2 and remote_bridge.current_session is not None:
            tab.set_archive_catalogue_session(remote_bridge.current_session)
        else:
            tab.set_archive_entries(
                getattr(self, "archive_entries", []),
                self.archive_package_root_edit.text().strip(),
            )
        return tab

    def _create_recolor_variants_tab(self) -> QWidget:
        from cdmw.ui.recolor_variants_tab import RecolorVariantsTab

        tab = RecolorVariantsTab(
            settings=self.settings,
            base_dir=self.settings_file_path.parent,
        )
        tab.status_message_requested.connect(
            lambda message, is_error: self.set_status_message(message, error=is_error)
        )
        tab.open_recolor_target_in_editor_requested.connect(self._open_recolor_variant_target_in_texture_editor)
        return tab

    def _create_texture_editor_tab(self) -> QWidget:
        texture_editor_tab_class = _load_texture_editor_tab_class()
        if texture_editor_tab_class is None:
            from cdmw.ui.texture_workflow.unavailable_editor import UnavailableTextureEditorTab

            tab = UnavailableTextureEditorTab(_texture_editor_import_error)
        else:
            tab = texture_editor_tab_class(
                settings=self.settings,
                base_dir=self.settings_file_path.parent,
                get_png_root=lambda: self.png_root_edit.text(),
                get_original_dds_root=lambda: self.original_dds_edit.text(),
                get_archive_entries=lambda: self.archive_entries,
                get_current_config=self.collect_config,
            )
        tab.set_ui_translator(self.ui_localizer.translate)
        tab.sync_ui_font_from_application()
        tab.status_message_requested.connect(
            lambda message, is_error: self.set_status_message(message, error=is_error)
        )
        tab.browse_archive_requested.connect(self._show_archive_browser_from_texture_editor)
        tab.open_in_compare_requested.connect(self._show_compare_from_texture_editor)
        tab.send_to_replace_assistant_requested.connect(self._handle_texture_editor_send_to_replace_assistant)
        tab.send_to_texture_workflow_requested.connect(self._handle_texture_editor_send_to_texture_workflow)
        tab.send_to_item_icons_requested.connect(self._handle_texture_editor_send_to_item_icons)
        tab.native_dds_ready.connect(lambda *args: self.mesh_editor_tab.apply_texture_editor_dds_result(*args))
        tab.resident_texture_patch_ready.connect(
            lambda patch: self.mesh_editor_tab.apply_texture_editor_region_patch(patch)
        )
        return tab

    def _create_item_icons_tab(self) -> QWidget:
        from cdmw.services.archive_preview_service import ensure_archive_preview_source
        from cdmw.ui.item_icons import ItemIconLibraryTab

        tab = ItemIconLibraryTab(
            settings=self.settings,
            base_dir=self.settings_file_path.parent,
            get_archive_entries=lambda: self.archive_entries,
            resolve_target_template_path=lambda entry: ensure_archive_preview_source(entry)[0],
            get_current_archive_path=self.current_archive_path_for_research,
            item_icon_service=self.app_context.services.require_item_icons(),
        )
        tab.status_message_requested.connect(
            lambda message, is_error: self.set_status_message(message, error=is_error)
        )
        tab.open_in_texture_editor_requested.connect(self._open_source_in_texture_editor)
        tab.open_target_in_archive_requested.connect(
            lambda target_path: self._show_archive_browser_from_texture_editor(target_path)
        )
        return tab

    def _create_mod_package_retrofit_tab(self) -> QWidget:
        from cdmw.ui.tools.mod_package_retrofit_tasks import ModPackageRetrofitToolWidget

        tab = ModPackageRetrofitToolWidget()
        tab.setObjectName("mod_package_retrofit")
        self._build_mod_package_retrofit_tool(tab, run_initial_scan=False)
        return tab

    def _create_placement_studio_tab(self) -> QWidget:
        """Weapon/armour socket placement and draw-animation retargeting.

        Lazily created like every other tool, which matters more here than elsewhere: the tab
        pins a vanilla baseline from the archives on first open, and that must not run during
        startup. It reports its own failures and never raises into the shell.
        """

        from tools.placement_studio.tab import PlacementStudioTab

        tab = PlacementStudioTab(settings=self.settings, window=self)
        tab.setObjectName("placement_studio")
        return tab

    def _create_format_explorer_tab(self) -> QWidget:
        """What every game file format can and cannot do, and which tool does it.

        Reads the capability manifest, so it cannot drift from what the code actually
        supports. Lazy like the rest; it touches no archives.
        """

        from tools.format_explorer.tab import FormatExplorerTab

        tab = FormatExplorerTab()
        tab.setObjectName("format_explorer")
        return tab

    def _create_translation_studio_tab(self) -> QWidget:
        """Search, retranslate and machine-translate the game's string tables.

        Lazy like the rest, and for the same reason as Placement Studio: opening it
        lists the languages in the archives, and a language table is 16-25 MB. Neither
        belongs in startup. It takes the window so it can read the configured archive
        root off the Settings widget rather than assuming the default install path.
        """

        from tools.translation_studio.tab import TranslationStudioTab

        tab = TranslationStudioTab(settings=self.settings, window=self)
        tab.setObjectName("translation_studio")
        return tab

    def _build_shell_tool_tabs(self, pump_startup_splash: Callable[[str], None]) -> None:
        from cdmw.ui.settings_tab import SettingsTab

        pump_startup_splash("Preparing settings...")
        self.settings_tab = SettingsTab(
            settings=self.settings,
            theme_key=self.current_theme_key,
            asset_authoring_service=lambda: self.app_context.services.asset_authoring,
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

        pump_startup_splash("Registering optional tools...")
        self.mesh_editor_tab = self._add_lazy_shell_tool(
            self.assets_tabs, "Mesh Editor", "mesh_editor", self._create_mesh_editor_tab
        )
        self.model_library_tab = self._add_lazy_shell_tool(
            self.assets_tabs, "Model Library", "model_library", self._create_model_library_tab
        )
        self.item_icons_tab = self._add_lazy_shell_tool(
            self.assets_tabs, "Icon Creator", "item_icons", self._create_item_icons_tab
        )
        self.replace_assistant_tab = self._add_lazy_shell_tool(
            self.texture_tabs, "Replacer", "replace_assistant", self._create_replace_assistant_tab
        )
        self.recolor_variants_tab = self._add_lazy_shell_tool(
            self.texture_tabs, "Recolor Variants", "recolor_variants", self._create_recolor_variants_tab
        )
        self.texture_editor_tab = self._add_lazy_shell_tool(
            self.texture_tabs, "Editor", "texture_editor", self._create_texture_editor_tab
        )
        self.research_tab = self._add_lazy_shell_tool(
            self.research_tabs, "Texture Research", "research", self._create_research_tab
        )
        self.text_search_tab = self._add_lazy_shell_tool(
            self.research_tabs, "Text Search", "text_search", self._create_text_search_tab
        )
        self.mod_package_retrofit_tab = self._add_lazy_shell_tool(
            self.tools_tabs,
            "Retrofit/Repackage",
            "mod_package_retrofit",
            self._create_mod_package_retrofit_tab,
        )
        # Top level, immediately after Assets — not inside Tools. See `root_layout.py`.
        self.placement_studio_tab = self._add_lazy_shell_tool(
            self.main_tabs,
            "Placement & Animation Studio",
            "placement_studio",
            self._create_placement_studio_tab,
            index=1,
        )
        self.format_explorer_tab = self._add_lazy_shell_tool(
            self.tools_tabs,
            "Format Explorer",
            "format_explorer",
            self._create_format_explorer_tab,
        )
        self.translation_studio_tab = self._add_lazy_shell_tool(
            self.tools_tabs,
            "Translation Studio",
            "translation_studio",
            self._create_translation_studio_tab,
        )

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
        self._register_detachable_tool("placement_studio", self.placement_studio_tab, "Placement & Animation Studio")
        self._register_detachable_tool("settings", self.settings_tab, "Settings")
        self._build_window_tool_menu_actions()


__all__ = ["ShellToolTabsMixin"]
