from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN_WINDOW = REPO_ROOT / "cdmw" / "ui" / "shell" / "app_window.py"
SHELL_MENUS = REPO_ROOT / "cdmw" / "ui" / "shell" / "menus.py"
SHELL_TOOL_TABS = REPO_ROOT / "cdmw" / "ui" / "shell" / "tool_tabs.py"
TEXTURE_WORKFLOW_DDS_OUTPUT_PANEL = REPO_ROOT / "cdmw" / "ui" / "texture_workflow" / "dds_output_panel.py"
TEXTURE_WORKFLOW_SHELL_CONTROLS = REPO_ROOT / "cdmw" / "ui" / "texture_workflow" / "shell_controls.py"
ARCHIVE_CONTROLS_PANEL = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "controls_panel.py"
DASHBOARD_CONTROLLER = REPO_ROOT / "cdmw" / "ui" / "shell" / "dashboard_controller.py"
SHELL_ROOT_LAYOUT = REPO_ROOT / "cdmw" / "ui" / "shell" / "root_layout.py"
SHELL_WORKSPACE_LAYOUT = REPO_ROOT / "cdmw" / "ui" / "shell" / "workspace_layout.py"
REPLACE_ASSISTANT_TAB = REPO_ROOT / "cdmw" / "ui" / "replace_assistant_tab.py"
REPLACE_ASSISTANT_REVIEW_DIALOG = REPO_ROOT / "cdmw" / "ui" / "replace_assistant" / "review_dialog.py"
RESEARCH_TAB = REPO_ROOT / "cdmw" / "ui" / "research" / "tab.py"
TEXTURE_EDITOR_TAB = REPO_ROOT / "cdmw" / "ui" / "texture_editor_tab.py"
ITEM_ICONS_TAB = REPO_ROOT / "cdmw" / "ui" / "item_icons" / "tab.py"
ITEM_ICONS_PANELS = REPO_ROOT / "cdmw" / "ui" / "item_icons" / "panels.py"
THEMES = REPO_ROOT / "cdmw" / "ui" / "themes.py"
README = REPO_ROOT / "README.md"


class TextureWorkflowUiSourceGuards(unittest.TestCase):
    def test_dds_output_selectors_have_room_for_default_labels(self) -> None:
        source = TEXTURE_WORKFLOW_DDS_OUTPUT_PANEL.read_text(encoding="utf-8")

        self.assertIn("(self.dds_format_mode_combo, 28)", source)
        self.assertIn("(self.dds_size_mode_combo, 32)", source)
        self.assertIn("(self.dds_mip_mode_combo, 30)", source)
        self.assertIn("combo.setMinimumContentsLength(minimum_contents_length)", source)
        self.assertIn("combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)", source)
        self.assertIn("combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)", source)
        self.assertIn("dds_output_options_layout.setColumnMinimumWidth(0, 84)", source)
        self.assertIn("dds_output_header_widget = QWidget()", source)
        self.assertIn("dds_output_header_layout.addWidget(self.enable_dds_staging_checkbox, 1)", source)
        self.assertNotIn("dds_output_options_layout.setColumnMinimumWidth(0, 132)", source)
        self.assertNotIn("dds_output_options_layout.addWidget(self.enable_dds_staging_checkbox, 0, 0, 1, 3)", source)

    def test_user_facing_tool_names_are_current(self) -> None:
        main_source = (
            MAIN_WINDOW.read_text(encoding="utf-8")
            + "\n"
            + SHELL_MENUS.read_text(encoding="utf-8")
            + "\n"
            + SHELL_TOOL_TABS.read_text(encoding="utf-8")
            + "\n"
            + DASHBOARD_CONTROLLER.read_text(encoding="utf-8")
            + "\n"
            + SHELL_ROOT_LAYOUT.read_text(encoding="utf-8")
            + "\n"
            + SHELL_WORKSPACE_LAYOUT.read_text(encoding="utf-8")
            + "\n"
            + TEXTURE_WORKFLOW_SHELL_CONTROLS.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_CONTROLS_PANEL.read_text(encoding="utf-8")
        )
        replacer_source = (
            REPLACE_ASSISTANT_TAB.read_text(encoding="utf-8")
            + "\n"
            + REPLACE_ASSISTANT_REVIEW_DIALOG.read_text(encoding="utf-8")
        )
        research_source = RESEARCH_TAB.read_text(encoding="utf-8")
        editor_source = TEXTURE_EDITOR_TAB.read_text(encoding="utf-8")
        readme = README.read_text(encoding="utf-8")
        theme_source = THEMES.read_text(encoding="utf-8")

        assets_nav = 'self.main_tabs.addTab(self.assets_tabs, "Assets")'
        textures_nav = 'self.main_tabs.addTab(self.texture_tabs, "Textures")'
        research_nav = 'self.main_tabs.addTab(self.research_tabs, "Research")'
        tools_nav = 'self.main_tabs.addTab(self.tools_tabs, "Tools")'
        for nav_label in (assets_nav, textures_nav, research_nav, tools_nav):
            self.assertIn(nav_label, main_source)
        self.assertNotIn('self.main_tabs.addTab(self.dashboard_tab, "Dashboard")', main_source)
        self.assertLess(main_source.index(assets_nav), main_source.index(textures_nav))
        self.assertLess(main_source.index(textures_nav), main_source.index(research_nav))
        self.assertLess(main_source.index(research_nav), main_source.index(tools_nav))
        self.assertIn('self.texture_tabs.addTab(self.workflow_tab, "Workflow")', main_source)
        self.assertIn('self.texture_tabs.addTab(self.replace_assistant_tab, "Replacer")', main_source)
        self.assertIn('self.texture_tabs.addTab(self.texture_editor_tab, "Editor")', main_source)
        self.assertIn('self.assets_tabs.addTab(self.archive_browser_tab, "Archive Browser")', main_source)
        self.assertIn('self.assets_tabs.addTab(self.model_library_tab, "Model Library")', main_source)
        self.assertIn('self.assets_tabs.addTab(self.item_icons_tab, "Icon Creator")', main_source)
        self.assertIn('self.research_tabs.addTab(self.research_tab, "Texture Research")', main_source)
        self.assertIn('self.research_tabs.addTab(self.text_search_tab, "Text Search")', main_source)
        self.assertIn('self.tools_tabs.addTab(self.mod_package_retrofit_tab, "Retrofit/Repackage")', main_source)
        self.assertIn('self._register_detachable_tool("research", self.research_tab, "Texture Research")', main_source)
        self.assertIn('self._register_detachable_tool("replace_assistant", self.replace_assistant_tab, "Texture Replacer")', main_source)
        self.assertIn('self._register_detachable_tool("item_icons", self.item_icons_tab, "Icon Creator")', main_source)
        self.assertIn('self._register_detachable_tool("mod_package_retrofit", self.mod_package_retrofit_tab, "Retrofit/Repackage")', main_source)
        self.assertIn("self.item_icons_tab.open_target_in_archive_requested.connect(", main_source)
        self.assertIn("self.archive_cache_status_chip = QLabel(\"Cache: Unknown\")", main_source)
        self.assertIn('self.archive_cache_status_chip.setObjectName("ArchiveCacheStatusChip")', main_source)
        self.assertIn("self.archive_cache_status_chip.setFixedWidth(132)", main_source)
        self.assertIn("self.archive_cache_status_chip.setAlignment(Qt.AlignCenter)", main_source)
        self.assertIn("self.archive_cache_status_chip.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)", main_source)
        self.assertIn('self.archive_scan_progress_label = QLabel("Ready")', main_source)
        self.assertIn("self.archive_scan_progress_label.setFixedWidth(110)", main_source)
        self.assertIn("self.archive_scan_progress_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)", main_source)
        self.assertIn("self.archive_scan_progress_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)", main_source)
        self.assertIn("self.archive_scan_progress_bar = QProgressBar()", main_source)
        self.assertIn("self.archive_scan_progress_bar.setFixedSize(118, 18)", main_source)
        self.assertIn("self.support_corner_button.setFixedWidth(136)", main_source)
        self.assertIn("self.support_corner_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)", main_source)
        self.assertIn("menu_corner_layout.setSpacing(8)", main_source)
        self.assertLess(
            main_source.index("menu_corner_layout.addWidget(self.archive_scan_progress_bar)"),
            main_source.index("menu_corner_layout.addWidget(self.archive_cache_status_chip)"),
        )
        self.assertIn("self._initialize_archive_cache_status_chip()", main_source)
        self.assertIn("def _set_archive_cache_status_chip(", main_source)
        self.assertIn("def _dashboard_set_archive_progress(", main_source)
        self.assertIn("def _check_archive_cache_health(", main_source)
        self.assertIn("def _set_widget_health_state(", main_source)
        self.assertIn('widget.setProperty("healthState", normalized)', main_source)
        self.assertIn("archive_scan_shard_cache_health(package_root, self.archive_cache_root)", main_source)
        self.assertIn("Cache: Healthy", main_source)
        self.assertNotIn('QLabel#ArchiveCacheStatusChip[healthState=', theme_source)
        self.assertIn('QLabel#HintLabel[healthState="healthy"]', theme_source)
        self.assertIn("#2fbf64", theme_source)
        self.assertNotIn('QGroupBox("Recent Work")', main_source)
        self.assertNotIn('QGroupBox("Last Results")', main_source)
        self.assertNotIn("def _dashboard_task_specs(self)", main_source)
        self.assertNotIn('QLabel("Start a Task")', main_source)
        self.assertNotIn('button.setObjectName("DashboardTaskButton")', main_source)
        self.assertIn('QPushButton("Resolve In Research")', main_source)
        self.assertIn('self.setWindowTitle("Texture Replacer Review")', replacer_source)
        self.assertIn('QAction("Send To Texture Replacer", self)', editor_source)
        self.assertIn('QAction("Send To Icon Creator", self)', editor_source)
        self.assertIn("send_to_item_icons_requested = Signal(str, object)", editor_source)
        self.assertIn('QPushButton("Refresh Research")', research_source)
        self.assertIn("`Texture Replacer`", readme)
        self.assertNotIn('"Replace Assistant"', main_source)

    def test_item_icons_workspace_has_library_and_generation_controls(self) -> None:
        tab_source = ITEM_ICONS_TAB.read_text(encoding="utf-8")
        panels_source = ITEM_ICONS_PANELS.read_text(encoding="utf-8")
        controller_source = Path("cdmw/ui/item_icons/controller.py").read_text(encoding="utf-8")
        source = tab_source + "\n" + panels_source + "\n" + controller_source

        self.assertIn("class ItemIconLibraryTab(ItemIconRecordListMixin, QWidget)", tab_source)
        self.assertIn("class ItemIconRecordListMixin:", controller_source)
        self.assertIn('header = QLabel("Icon Creator")', source)
        self.assertIn('self.settings.value("item_icons/library_roots", "[]")', source)
        self.assertIn('self.index_path = self.library_root / "icon_index.json"', source)
        self.assertIn('QGroupBox("Library Folders")', source)
        self.assertIn('QGroupBox("Compatible Output")', source)
        self.assertIn('target_filter_edit.setPlaceholderText("Filter or paste an existing archive item icon path")', source)
        self.assertIn('use_archive_selection_button = QPushButton("Use Archive Selection")', source)
        self.assertIn('open_target_archive_button = QPushButton("Open In Archive Browser")', source)
        self.assertIn("open_target_in_archive_requested = Signal(str)", source)
        self.assertIn("def _matching_target_entries", source)
        self.assertIn("display_limit = 300", source)
        self.assertIn("choose_source_dialog", source)
        self.assertIn("build_item_icon_payload(", source)
        self.assertIn("target_template_path=template_path", source)
        self.assertIn('add_to_loose_mod_button = QPushButton("Add To Existing Loose Mod...")', source)
        self.assertIn("add_to_loose_mod_button.clicked.connect(", source)
        self.assertIn("add_to_existing_loose_mod", source)
        self.assertIn("def add_to_existing_loose_mod", source)
        self.assertIn("patch_existing_loose_mod_with_item_icon(", source)
        self.assertIn("background_mode=self._background_mode()", source)
        self.assertIn('delete_source_button = QPushButton("Delete Source")', source)
        self.assertIn("def delete_selected_source", source)
        self.assertIn("path.unlink()", source)
        self.assertIn("customContextMenuRequested", source)
        self.assertIn("def _show_records_context_menu", source)


if __name__ == "__main__":
    unittest.main()
